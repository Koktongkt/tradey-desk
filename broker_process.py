"""Pinned broker launch mechanics; retry and response policies stay with callers."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from broker_supervisor import freeze_kill_tree

_NATIVE_RUN = subprocess.run


def _group_run(command, *, input, timeout, **kwargs):
    """Per-launch Linux subreaper owns wrapper + detached orphans until reaped.

    Parent timeout asks the still-owned supervisor to kill/reap before returning;
    neither output draining nor exceptional cleanup has an unbounded wait.
    """
    check = kwargs.pop('check', False)
    kwargs.pop('capture_output', None)
    kwargs.pop('text', None)
    options = {key: kwargs.pop(key) for key in ('cwd', 'env') if key in kwargs}
    if kwargs:
        raise TypeError('unsupported broker launch options')
    request = json.dumps(dict(command=command, input=input, timeout=timeout, options=options))
    process = subprocess.Popen([sys.executable, '-I', str(Path(__file__).with_name('broker_supervisor.py'))],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, close_fds=True, start_new_session=True)
    try:
        try:
            stdout, stderr = process.communicate(request, timeout=timeout + 1)
        except BaseException:
            # Do not kill/reap supervisor first: adopted children need its reaper.
            process.send_signal(signal.SIGTERM)
            try:
                process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                # Never destroy the isolated custodian: kill its owned tree,
                # resume it, and await its cleanup/reaping acknowledgement.
                freeze_kill_tree(process.pid, include_root=False)
                process.communicate(timeout=1)
            raise
        if process.returncode != 0:
            raise RuntimeError('broker_containment_unconfirmed')
        result = json.loads(stdout)
        if result.get('error'):
            raise OSError('broker_supervisor_failure')
        if result['timed_out']:
            raise subprocess.TimeoutExpired(command, timeout, output=result['stdout'], stderr=result['stderr'])
        completed = subprocess.CompletedProcess(command, result['returncode'], result['stdout'], result['stderr'])
        if check:
            completed.check_returncode()
        return completed
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream and not stream.closed:
                stream.close()


def bridge_command(root, operation: str, *, executable: str) -> list[str]:
    return [executable, "run", "--with", "fastmcp<4", "python",
            str(root / "broker_mcp_bridge.py"), operation]


def run_bridge(command, *, input: str, timeout: int, run, **kwargs):
    """Launch once; caller's injected runner seam remains unchanged."""
    runner = _group_run if run is _NATIVE_RUN else run
    return runner(command, input=input, text=True, capture_output=True,
                  timeout=timeout, **kwargs)
