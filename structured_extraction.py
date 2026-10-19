"""Stdlib supervisor for the exact-URL extraction worker (never an agent)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
from time import monotonic

from runtime_paths import hermes_runtime
from extraction_contract import strict_json_loads

MAX_REQUEST_BYTES = 8192
MAX_RESPONSE_BYTES = 100_000
MAX_STDERR_BYTES = 16_384
ERROR_REASONS = frozenset({
    'invalid_request', 'malformed_response', 'provider_error', 'empty_content',
    'timeout', 'output_limit', 'worker_exit', 'worker_unavailable', 'unsafe_url',
    'url_mismatch',
})


def failure(reason):
    return {'version': 1, 'status': 'error', 'reason': reason if reason in ERROR_REASONS else 'malformed_response'}


def worker_command():
    """Use the installed isolated runtime AND its dependency bootstrap, not raw Python."""
    python, source = hermes_runtime()
    worker = Path(__file__).with_name('extraction_worker.py')
    bootstrap = (
        "import os, sys, runpy; "
        "os.environ.pop('PYTHONHOME', None); os.environ.pop('PYTHONPATH', None); "
        "os.environ.pop('VIRTUAL_ENV', None); "
        f"sys.path.insert(0, {str(source)!r}); "
        "sys._hermes_pin_default_home = True; import hermes_bootstrap; "
        "os.environ.get('HERMES_HOME') or os.environ.__setitem__('HERMES_HOME', "
        "str(__import__('hermes_constants').get_default_hermes_root())); "
        f"sys.path.insert(0, {str(worker.parent)!r}); "
        f"runpy.run_path({str(worker)!r}, run_name='__main__')"
    )
    return [python, '-I', '-c', bootstrap]


def record_attempts(rows, path):
    """Private-only ledger, deliberately not registered with public SQLite views.

    Exact request identifiers are run-salted opaque hashes. Persist no domain,
    URL, body, prompt, provider response, stderr or exception text.
    """
    import datetime as dt
    import re
    from durable_jsonl import append_jsonl
    direct_reasons = {'focused_reuse_hit', 'cache_hit', 'success', 'source_fetch_failed', 'source_fetch_timeout',
                      'source_http_forbidden', 'source_rate_limited',
                      'source_upstream_error', 'source_connection_failed',
                      'source_deadline_exhausted', 'source_url_mismatch'}
    fallback_results = ERROR_REASONS | {'success', 'not_attempted', 'unavailable'}
    for row in rows:
        if (not re.fullmatch(r'[0-9a-f]{32}', str(row.get('run_id', '')))
                or not re.fullmatch(r'[0-9a-f]{64}', str(row.get('url_id', '')))):
            continue
        out = {key: row[key] for key in ('run_id', 'url_id')}
        collection = row.get('collection_id')
        if re.fullmatch(r'[0-9a-f]{32}', str(collection or '')):
            out['collection_id'] = collection
        out['network_attempted'] = row.get('network_attempted') is True
        if row.get('focused_reuse') in {'hit', 'miss'}:
            out['focused_reuse'] = row['focused_reuse']
        out['timestamp'] = dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')
        out['direct_reason'] = row.get('direct_reason') if row.get('direct_reason') in direct_reasons else 'source_fetch_failed'
        out['fallback_result'] = row.get('fallback_result') if row.get('fallback_result') in fallback_results else 'unavailable'
        status = row.get('direct_status')
        out['direct_status'] = status if type(status) is int and 100 <= status <= 599 else None
        for key in ('direct_elapsed_ms', 'fallback_elapsed_ms', 'remaining_ms'):
            value = row.get(key, 0)
            out[key] = min(86_400_000, max(0, value)) if type(value) is int else 0
        append_jsonl(path, out)


def run_worker(url: str, timeout_seconds: float = 30):
    """Bound startup/tool/output and signal the worker process group on exit.

    Kill group members and reap the leader. This is not a sandbox: descendants
    that escape the group are not contained, and grandchildren are not reaped.
    """
    start = monotonic()
    if not isinstance(url, str) or not url or len(url) > 4096:
        return failure('invalid_request')
    if timeout_seconds <= 0:
        return failure('timeout')
    timeout_seconds = min(30, timeout_seconds)
    request = json.dumps({'version': 1, 'url': url, 'timeout_seconds': timeout_seconds}).encode('utf-8')
    if len(request) > MAX_REQUEST_BYTES:
        return failure('invalid_request')
    process = None
    try:
        command = worker_command()
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True, bufsize=0,
                                   cwd=Path(__file__).resolve().parent)
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        for pipe in (process.stdin, process.stdout, process.stderr):
            os.set_blocking(pipe.fileno(), False)
        offset = 0
        stdout = bytearray()
        stderr_size = 0
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
            selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
            selector.register(process.stdin, selectors.EVENT_WRITE, 'stdin')
            while selector.get_map():
                remaining = timeout_seconds - (monotonic() - start)
                if remaining <= 0:
                    return failure('timeout')
                for key, _ in selector.select(remaining):
                    if key.data == 'stdin':
                        try:
                            offset += os.write(key.fd, request[offset:])
                        except BlockingIOError:
                            continue
                        except BrokenPipeError:
                            # Still supervise output/deadline after an early close.
                            offset = len(request)
                        if offset == len(request):
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                        continue
                    try:
                        chunk = os.read(key.fd, 8192)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif key.data == 'stdout':
                        stdout.extend(chunk)
                        if len(stdout) > MAX_RESPONSE_BYTES:
                            return failure('output_limit')
                    else:
                        stderr_size += len(chunk)
                        if stderr_size > MAX_STDERR_BYTES:
                            return failure('output_limit')
        remaining = timeout_seconds - (monotonic() - start)
        if remaining <= 0:
            return failure('timeout')
        if process.wait(timeout=remaining):
            return failure('worker_exit')
        try:
            out = strict_json_loads(stdout)
        except (ValueError, UnicodeError, RecursionError):
            return failure('malformed_response')
        return out if isinstance(out, dict) else failure('malformed_response')
    except subprocess.TimeoutExpired:
        return failure('timeout')
    except (OSError, ValueError):
        return failure('worker_unavailable')
    finally:
        if process is not None:
            # Signal remaining group members even if the leader already exited.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
