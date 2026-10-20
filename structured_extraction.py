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
    return _run_process(request, timeout_seconds, start, failure)


class SupervisorFailure(dict):
    """Internal distinction: no valid worker envelope was received."""


def _batch_supervisor_failure(reason):
    from extraction_worker import batch_error
    return SupervisorFailure(batch_error(reason))


def run_validation_worker(urls: list[str], timeout_seconds: float = 30) -> dict:
    from extraction_worker import batch_error, valid_batch_request
    start = monotonic()
    payload = {'version': 2, 'operation': 'validate_urls', 'urls': urls,
               'timeout_seconds': timeout_seconds}
    if not valid_batch_request(payload):
        return batch_error('invalid_request')
    payload['timeout_seconds'] = min(30, timeout_seconds)
    out = _run_process(json.dumps(payload).encode('utf-8'), payload['timeout_seconds'],
                       start, _batch_supervisor_failure)
    return out if _valid_validation_response(out, urls) else _batch_supervisor_failure('malformed_response')


def _valid_validation_response(out, urls):
    if (not isinstance(out, dict) or type(out.get('version')) is not int or out['version'] != 2):
        return False
    if out.get('status') == 'error':
        return _valid_batch_response(out, urls)
    if set(out) != {'version', 'status', 'results'} or out.get('status') != 'ok':
        return False
    rows = out['results']
    if not isinstance(rows, list) or len(rows) != len(urls):
        return False
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'requested_url', 'eligible', 'reason'}
                or not isinstance(row['requested_url'], str) or row['requested_url'] not in urls
                or row['requested_url'] in seen or type(row['eligible']) is not bool
                or not isinstance(row['reason'], str)
                or (row['reason'] != 'success' if row['eligible'] else row['reason'] not in ERROR_REASONS)):
            return False
        seen.add(row['requested_url'])
    return True


def run_batch_worker(urls: list[str], timeout_seconds: float = 30) -> dict:
    """One owned worker and one startup/write/provider/read deadline per batch."""
    from extraction_worker import batch_error, valid_batch_request
    start = monotonic()
    payload = {'version': 2, 'urls': urls, 'timeout_seconds': timeout_seconds}
    if not valid_batch_request(payload):
        return batch_error('invalid_request')
    timeout_seconds = min(30, timeout_seconds)
    payload['timeout_seconds'] = timeout_seconds
    request = json.dumps(payload).encode('utf-8')
    out = _run_process(request, timeout_seconds, start, _batch_supervisor_failure)
    return out if _valid_batch_response(out, urls) else _batch_supervisor_failure('malformed_response')


def _valid_batch_response(out, urls):
    """Validate the v2 boundary without changing v1's compatibility contract."""
    if not isinstance(out, dict) or type(out.get('version')) is not int or out['version'] != 2:
        return False
    if out.get('status') == 'error':
        return (set(out) == {'version', 'status', 'reason'} and isinstance(out.get('reason'), str)
                and out['reason'] in ERROR_REASONS)
    if out.get('status') != 'ok' or set(out) != {'version', 'status', 'results'}:
        return False
    rows = out['results']
    if not isinstance(rows, list) or len(rows) != len(urls):
        return False
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'requested_url', 'result'}:
            return False
        key, result = row['requested_url'], row['result']
        if not isinstance(key, str) or key not in urls or key in seen:
            return False
        seen.add(key)
        if not isinstance(result, dict) or type(result.get('version')) is not int or result['version'] != 1:
            return False
        if result.get('status') == 'error':
            if (set(result) != {'version', 'status', 'reason'} or not isinstance(result.get('reason'), str)
                    or result['reason'] not in ERROR_REASONS):
                return False
        elif result.get('status') == 'ok' and set(result) == {'version', 'status', 'page'}:
            page = result['page']
            if (not isinstance(page, dict)
                    or not all(isinstance(page.get(k), str) and 1 <= len(page[k]) <= cap
                               for k, cap in (('url', 4096), ('text', 6000)))
                    or not isinstance(page.get('title'), str) or len(page['title']) > 200):
                return False
            from publication_provenance import extraction_extensions
            if extraction_extensions(page, page['url'], key) is None:
                return False
            if page['url'] != key and 'extraction_location' not in page:
                return False
            if 'location_provenance' in page and page['location_provenance'] != 'uncached_dispatch':
                return False
        else:
            return False
    return True


def _run_process(request, timeout_seconds, start, fail):
    """Shared stdlib pipe/deadline/group containment; no protocol projection."""
    process = None
    try:
        command = worker_command()
        if timeout_seconds - (monotonic() - start) <= 0:
            return fail('timeout')
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
                    return fail('timeout')
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
                            return fail('output_limit')
                    else:
                        stderr_size += len(chunk)
                        if stderr_size > MAX_STDERR_BYTES:
                            return fail('output_limit')
        remaining = timeout_seconds - (monotonic() - start)
        if remaining <= 0:
            return fail('timeout')
        if process.wait(timeout=remaining):
            return fail('worker_exit')
        try:
            out = strict_json_loads(stdout)
        except (ValueError, UnicodeError, RecursionError):
            return fail('malformed_response')
        return out if isinstance(out, dict) else fail('malformed_response')
    except subprocess.TimeoutExpired:
        return fail('timeout')
    except (OSError, ValueError):
        return fail('worker_unavailable')
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
