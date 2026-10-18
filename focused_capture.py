"""Private, bounded same-run tool receipts. Never a source-discovery input."""
from __future__ import annotations

import datetime as dt
import json
import os
import stat
import threading

from extraction_contract import strict_json_loads

FD_ENV = 'TRADEY_FOCUSED_CAPTURE_FD'
NONCE_ENV = 'TRADEY_FOCUSED_CAPTURE_NONCE'
MAX_CALLS = 15
MAX_URLS = 15
MAX_URL_LENGTH = 4096
MAX_REQUEST_BYTES = 24_000
MAX_RAW_BYTES = 100_000
MAX_ARTIFACT_BYTES = 1_600_000


class CapturedResult(dict):
    """Strict worker envelope with parent-channel receipt time kept out of schema."""
    def __init__(self, result, checked_at):
        super().__init__(result)
        self.checked_at = checked_at


class FocusedURLs(dict):
    """Model URL choices and trusted tool pages occupy separate namespaces."""
    def __init__(self, choices, pages):
        super().__init__(choices)
        self.focused_pages = pages


def run_focused(command, *, input, capture_output, text, timeout, cwd):
    """Own one focused process group and an optional preopened private channel."""
    from contextlib import ExitStack
    import secrets
    import signal
    import subprocess
    import tempfile
    from time import monotonic
    started = monotonic()
    with ExitStack() as cleanup:
        fd = None
        env = dict(os.environ)
        env.pop(FD_ENV, None)
        env.pop(NONCE_ENV, None)
        nonce = secrets.token_hex(32)
        try:
            directory = cleanup.enter_context(tempfile.TemporaryDirectory(prefix='tradey-focused-'))
            os.chmod(directory, 0o700)
            fd = os.open(os.path.join(directory, 'capture'), os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            cleanup.callback(os.close, fd)
            os.fchmod(fd, 0o600)
            env.update({FD_ENV: str(fd), NONCE_ENV: nonce})
        except OSError:
            fd = None  # Optional recording unavailability is an ordinary miss.
        try:
            argv = focused_command(command)
        except ValueError as error:
            raise OSError('focused runtime unavailable') from error
        remaining = timeout - (monotonic() - started)
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, timeout)
        process = None
        try:
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=text, cwd=cwd, env=env,
                                       pass_fds=() if fd is None else (fd,), start_new_session=True)
            remaining = timeout - (monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            payload = input.encode('utf-8') if isinstance(input, str) else input
            if len(payload) > 8192:
                raise OSError('focused input limit')
            # Bound both pipes while the child is alive; communicate() alone
            # buffers unbounded chatter from tools and blocked executor threads.
            import selectors
            process.stdin.write(payload.decode('utf-8') if text else payload)
            process.stdin.close()
            buffers = {'stdout': bytearray(), 'stderr': bytearray()}
            caps = {'stdout': 100_000, 'stderr': 16_384}
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
                selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
                while selector.get_map():
                    remaining = timeout - (monotonic() - started)
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    for key, _ in selector.select(remaining):
                        chunk = os.read(key.fileobj.fileno(), 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            buffers[key.data].extend(chunk)
                            if len(buffers[key.data]) > caps[key.data]:
                                raise OSError('focused output limit')
            remaining = timeout - (monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            process.wait(timeout=remaining)
            stdout, stderr = (bytes(buffers[name]) for name in ('stdout', 'stderr'))
            if text:
                stdout, stderr = stdout.decode('utf-8'), stderr.decode('utf-8')
            result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        finally:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                for pipe in (process.stdin, process.stdout, process.stderr):
                    if pipe is not None:
                        pipe.close()
        result.focused_pages = read_capture(fd, nonce) if result.returncode == 0 and fd is not None else {}
        return result


def focused_command(command):
    """Installed isolated runtime + dependency bootstrap + unchanged CLI tail."""
    from pathlib import Path
    from runtime_paths import hermes_runtime
    python, source = hermes_runtime()
    wrapper = Path(__file__).with_name('focused_wrapper.py')
    bootstrap = (
        "import os, sys, runpy; "
        "os.environ.pop('PYTHONHOME', None); os.environ.pop('PYTHONPATH', None); "
        "os.environ.pop('VIRTUAL_ENV', None); "
        f"sys.path.insert(0, {str(source)!r}); "
        "sys._hermes_pin_default_home = True; import hermes_bootstrap; "
        "os.environ.get('HERMES_HOME') or os.environ.__setitem__('HERMES_HOME', "
        "str(__import__('hermes_constants').get_default_hermes_root())); "
        f"sys.path.insert(0, {str(wrapper.parent)!r}); "
        f"runpy.run_path({str(wrapper)!r}, run_name='__main__')"
    )
    return [python, '-I', '-c', bootstrap, *command[1:]]


def valid_request(request):
    return (isinstance(request, dict) and set(request) == {'urls', 'format', 'char_limit'}
            and isinstance(request['urls'], list) and 1 <= len(request['urls']) <= 5
            and all(isinstance(u, str) and 1 <= len(u) <= MAX_URL_LENGTH for u in request['urls'])
            and request['format'] in ('markdown', 'text', 'html')
            and (request['char_limit'] is None or type(request['char_limit']) is int)
            and len(json.dumps(request, ensure_ascii=False).encode('utf-8')) <= MAX_REQUEST_BYTES)


class Recorder:
    def __init__(self, fd, nonce):
        self.fd, self.nonce = fd, nonce
        self.lock = threading.Lock()
        self.calls = []
        self.bytes = 0
        self.urls = 0
        self.invocations = 0
        self.disabled = False
        self.guarded = False

    def wrap(self, original):
        async def captured(*args, **kwargs):
            # Snapshot before awaiting: the tool still receives the original objects.
            request = None
            try:
                urls = args[0] if args else kwargs.get('urls')
                candidate = {'urls': list(urls) if isinstance(urls, list) else urls,
                             'format': args[1] if len(args) > 1 else kwargs.get('format', 'markdown'),
                             'char_limit': args[2] if len(args) > 2 else kwargs.get('char_limit')}
                if valid_request(candidate):
                    request = candidate
            except Exception:
                pass
            result = await original(*args, **kwargs)
            try:
                self.record(request, result)
            except Exception:
                with self.lock:
                    self.disabled = True
            return result
        return captured

    def record(self, request, raw):
        with self.lock:
            self.invocations += 1
            if self.disabled or self.invocations > MAX_CALLS:
                self.disabled = True
                return
            if request is None or not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_RAW_BYTES:
                self.disabled = True
                return
            entry = {'request': request, 'raw': raw, 'guarded': self.guarded,
                     'checked_at': dt.datetime.now(dt.timezone.utc).isoformat()}
            size = len(json.dumps(entry, ensure_ascii=False).encode('utf-8'))
            if self.bytes + size > MAX_ARTIFACT_BYTES - 1024 or self.urls + len(request['urls']) > MAX_URLS:
                self.disabled = True
                return
            self.calls.append(entry)
            self.bytes += size
            self.urls += len(request['urls'])

    def complete(self):
        # A single completed artifact, written only after successful CLI completion.
        try:
            with self.lock:
                if self.disabled:
                    return
                data = json.dumps({'version': 1, 'nonce': self.nonce, 'complete': True,
                                   'calls': self.calls}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                if len(data) > MAX_ARTIFACT_BYTES:
                    return
                os.ftruncate(self.fd, 0)
                offset = 0
                while offset < len(data):
                    written = os.pwrite(self.fd, data[offset:], offset)
                    if written <= 0:
                        raise OSError('capture write failed')
                    offset += written
        except Exception:
            # Optional capture cannot fail or alter a successful focused stage.
            pass


def read_capture(fd, nonce):
    """Read only the parent's expected descriptor; any artifact defect is a miss."""
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink > 1
                or not 0 < info.st_size <= MAX_ARTIFACT_BYTES):
            return {}
        data = os.pread(fd, MAX_ARTIFACT_BYTES + 1, 0)
        if len(data) != info.st_size:
            return {}
        artifact = strict_json_loads(data)
        if (not isinstance(artifact, dict) or set(artifact) != {'version', 'nonce', 'complete', 'calls'}
                or type(artifact['version']) is not int or artifact['version'] != 1
                or artifact['nonce'] != nonce or artifact['complete'] is not True
                or not isinstance(artifact['calls'], list) or len(artifact['calls']) > MAX_CALLS):
            return {}
        total_urls = 0
        for call in artifact['calls']:
            if (not isinstance(call, dict) or set(call) != {'request', 'raw', 'guarded', 'checked_at'}
                    or not valid_request(call['request']) or type(call['guarded']) is not bool
                    or not isinstance(call['raw'], str) or len(call['raw'].encode('utf-8')) > MAX_RAW_BYTES
                    or not isinstance(call['checked_at'], str)):
                return {}
            checked = dt.datetime.fromisoformat(call['checked_at'])
            if checked.tzinfo is None or checked > dt.datetime.now(dt.timezone.utc):
                return {}
            total_urls += len(call['request']['urls'])
        if total_urls > MAX_URLS:
            return {}
        return bind_calls(artifact['calls'])
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError, KeyError):
        return {}


def bind_calls(calls):
    from extraction_worker import provider_rows, project_row
    results, seen, duplicates = {}, set(), set()
    for call in calls:
        requested = call['request']['urls']
        # Repeated requested keys, including across invocations, are ambiguous.
        for url in requested:
            if url in seen:
                duplicates.add(url)
            seen.add(url)
        rows, reason = provider_rows(call['raw'])
        if reason or rows is None or len(rows) > 5:
            continue
        matched = set()
        for row in rows:
            returned = row.get('url')
            key = returned if isinstance(returned, str) and returned in requested else None
            from publication_provenance import extraction_extensions
            extensions = extraction_extensions(row, returned)
            if extensions is None:
                return {}
            location = extensions.get('extraction_location')
            if location is not None:
                bound = location['requested_url']
                if bound not in requested or (key is not None and key != bound):
                    return {}
                key = bound
            if key is None and len(requested) == 1 and len(rows) == 1:
                key = requested[0]
            if key is None:
                continue
            if key in matched:
                duplicates.add(key)
            matched.add(key)
            projected = project_row(row, call['guarded'])
            if projected['status'] == 'ok':
                results[key] = CapturedResult(projected, call['checked_at'])
    return {u: page for u, page in results.items() if u not in duplicates}
