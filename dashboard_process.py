"""Linux dashboard-only containment; no broker operations or lock inheritance.

An isolated subreaper monitors the exact caller pidfd and supervises a bounded
collector. Raw CLI output never enters the supervisor's unbounded buffers.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys


def run_owned(command, root, timeout, *, outer=False):
    from broker_supervisor import freeze_kill_tree
    caller_fd = os.pidfd_open(os.getpid())
    request = dict(command=list(command), root=str(root), timeout=max(.001, timeout),
                   caller_fd=caller_fd, outer=outer)
    try:
        process = subprocess.Popen([sys.executable, '-I', str(Path(__file__).resolve()), '--guardian'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, close_fds=True, start_new_session=True, pass_fds=(caller_fd,))
    finally:
        os.close(caller_fd)
    try:
        try:
            stdout, _ = process.communicate(json.dumps(request), timeout=timeout+1.2)
        except BaseException:
            process.send_signal(signal.SIGTERM)
            try:
                process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                freeze_kill_tree(process.pid, include_root=False)
                process.communicate(timeout=1)
            raise
        if process.returncode != 0:
            raise RuntimeError('dashboard_containment_unconfirmed')
        row = json.loads(stdout)
        if row.get('error'):
            raise RuntimeError('dashboard_containment_unconfirmed')
        result = subprocess.CompletedProcess([], row['returncode'], row['stdout'], '')
        result.observed_classifications = frozenset(row['observed'])
        return result
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream and not stream.closed:
                stream.close()


def collector(request):
    from dashboard_deployment import _collect_attempt
    result = _collect_attempt(request['command'], Path(request['root']), request['timeout'])
    output = result.stdout
    if request['outer']:
        # Outer boundary emits only an allowlisted small token, never raw data.
        from run_cycle import parse_failure_event
        output = (parse_failure_event(output) or '') + ('\n' if output else '')
    print(json.dumps(dict(returncode=result.returncode, stdout=output,
                         observed=sorted(getattr(result, 'observed_classifications', ())))), flush=True)


def guardian(request):
    from broker_supervisor import supervise, cleanup
    try:
        result = supervise(dict(command=[sys.executable, '-I', str(Path(__file__).resolve()), '--collector'],
            input=json.dumps(request), timeout=request['timeout'] + (0 if request['outer'] else .2),
            options={}), caller_fd=request['caller_fd'])
        if result['timed_out']:
            row = dict(returncode=124, stdout='', observed=[])
        elif result['returncode'] != 0:
            row = {'error': 'dashboard_collector_failed'}
        else:
            row = json.loads(result['stdout'])
    except BaseException:
        cleanup()  # Never acknowledge containment until owned children are reaped.
        row = {'error': 'dashboard_guardian_failed'}
    print(json.dumps(row), flush=True)


if __name__ == '__main__':
    # -I excludes the checkout from sys.path; explicitly trust this module's root.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    request = json.load(sys.stdin)
    if sys.argv[1:] == ['--collector']:
        collector(request)
    else:
        guardian(request)
