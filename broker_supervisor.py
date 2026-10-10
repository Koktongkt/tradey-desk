"""Linux-only, per-launch subreaper. Never changes the shared runtime's prctl.

Owns the wrapper and adopted orphans until every child has been killed/reaped.
Protocol output is emitted only after that proof; broker output is data, not
supervisor protocol. No broker/model/network operations are implemented here.
"""
import ctypes
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time


def identity(pid):
    try:
        fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
        return int(fields[1]), fields[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def freeze_kill_tree(pid, *, include_root=True):
    """Freeze before enumerating; pidfds bind signals to the observed lifetime.

    Root is an unreaped owned subprocess. Each descendant's parent/start-time
    is rechecked after opening its pidfd. No numeric-PID signal fallback.
    """
    owned = []
    def visit(current, expected):
        try:
            fd = os.pidfd_open(current)
        except ProcessLookupError:
            return
        try:
            if identity(current) != expected:
                return
            if include_root or current != pid:
                try:
                    signal.pidfd_send_signal(fd, signal.SIGSTOP)
                except ProcessLookupError:
                    return
            owned.append(fd)
            fd = None
            for path in Path('/proc').iterdir():
                if not path.name.isdigit():
                    continue
                observed = identity(int(path.name))
                if observed and observed[0] == current:
                    visit(int(path.name), observed)
        finally:
            if fd is not None:
                os.close(fd)
    observed = identity(pid)
    if observed:
        visit(pid, observed)
    try:
        for fd in reversed(owned[1:] if not include_root else owned):
            try:
                signal.pidfd_send_signal(fd, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if owned and not include_root:
            signal.pidfd_send_signal(owned[0], signal.SIGCONT)
    finally:
        for fd in owned:
            os.close(fd)


def reap_owned():
    """Only this isolated subreaper's children; never unrelated runtime children."""
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return True
        if not pid:
            return False


def cleanup():
    # Kill all descendants, keeping the supervisor alive to adopt and reap.
    deadline = time.monotonic() + .6
    while True:
        freeze_kill_tree(os.getpid(), include_root=False)
        if reap_owned():
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('broker_containment_unconfirmed')
        time.sleep(.005)


def supervise(request):
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), 'broker_subreaper_unavailable')
    # Fail before launching if safe process signalling is unavailable.
    fd = os.pidfd_open(os.getpid())
    try:
        signal.pidfd_send_signal(fd, 0)  # Kernel/permission check before launch.
    finally:
        os.close(fd)
    interrupted = []
    signal.signal(signal.SIGTERM, lambda *_: interrupted.append(True))
    output = [bytearray(), bytearray()]
    process = None
    timed_out = False
    try:
        process = subprocess.Popen(request['command'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
            **request['options'])
        # Input is a small broker JSON request. Use nonblocking I/O throughout.
        selector = selectors.DefaultSelector()
        payload = request['input'].encode('utf-8')
        for index, stream in enumerate((process.stdout, process.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, index)
        os.set_blocking(process.stdin.fileno(), False)
        if payload:
            selector.register(process.stdin, selectors.EVENT_WRITE, 2)
        else:
            process.stdin.close()
        deadline = time.monotonic() + request['timeout']
        cleaned = False
        while selector.get_map() or process.returncode is None:
            if process.poll() is not None and not cleaned:
                # Wrapper exit is NOT descendant exit. Orphans now belong to us.
                cleanup()
                cleaned = True
            if interrupted or time.monotonic() >= deadline:
                timed_out = True
                break
            for key, _ in selector.select(min(.02, max(0, deadline - time.monotonic()))):
                if key.data == 2:
                    try:
                        sent = os.write(key.fd, payload)
                        payload = payload[sent:]
                    except BrokenPipeError:
                        payload = b''
                    if not payload:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                else:
                    chunk = os.read(key.fd, 65536)
                    if chunk:
                        output[key.data].extend(chunk)
                    else:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
        returncode = process.returncode
    finally:
        cleanup()
        if process is not None:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed:
                    stream.close()
        if 'selector' in locals():
            selector.close()
    return dict(returncode=returncode, stdout=output[0].decode('utf-8'),
                stderr=output[1].decode('utf-8'), timed_out=timed_out)


def main():
    try:
        request = json.load(sys.stdin)
        result = supervise(request)
    except BaseException as error:
        # Any ordinary supervisor failure must clean up before emitting failure.
        try:
            cleanup()
        except BaseException:
            # No success protocol; parent retains authority until its cleanup.
            raise
        result = {'error': type(error).__name__}
    print(json.dumps(result), flush=True)


def guardian_main():
    """Stable per-launch custodian; the inner supervisor may be forcibly killed.

    Only this dedicated process adopts/reaps orphans; the shared caller's
    subreaper state and unrelated children are untouched. Its independent
    deadline also handles a stopped inner supervisor. External SIGKILL/OOM
    of this custodian is outside the internally controlled cleanup guarantee.
    """
    try:
        request = json.load(sys.stdin)
        result = supervise(dict(
            command=[sys.executable, '-I', str(Path(__file__).resolve()), '--inner'],
            input=json.dumps(request), timeout=request['timeout'] + .2, options={}))
        # supervise has already killed/reaped every owned child before returning.
        if result['timed_out']:
            result = dict(returncode=None, stdout='', stderr='', timed_out=True)
        elif result['returncode'] != 0:
            result = {'error': 'broker_inner_supervisor_failure'}
        else:
            result = json.loads(result['stdout'])
    except BaseException as error:
        cleanup()
        result = {'error': type(error).__name__}
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['--inner']:
        main()
    else:
        guardian_main()
