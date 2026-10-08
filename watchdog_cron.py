"""Cron-only entry point: actual clock, read-only modes, hard wall bounds.

No --now or output/root overrides are accepted on the scheduled path. TERM
and ALRM unwind Python finally blocks, closing gateway/worker process groups.
"""
import signal
import sys
from watchdog.cli import main


def run(mode, call=main):
    if mode not in ('mechanical', 'daily'):
        raise ValueError('watchdog_mode_rejected')
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGALRM, signal.SIGTERM)}
    def stop(signum, frame):
        print(f'Watchdog {mode} interrupted/deadline exceeded; observation and delivery unverified.', flush=True)
        raise SystemExit(124)
    try:
        for sig in saved:
            signal.signal(sig, stop)
        signal.alarm(120 if mode == 'mechanical' else 900)
        return call([mode, '--cron'])
    finally:
        signal.alarm(0)
        for sig, handler in saved.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('mechanical', 'daily'):
        print('Watchdog scheduled action rejected.')
        raise SystemExit(2)
    raise SystemExit(run(sys.argv[1]))
