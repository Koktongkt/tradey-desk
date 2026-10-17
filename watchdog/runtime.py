"""Concrete deterministic paper-broker adapter and receipt-honest cron output.

No trading operations, repair helpers, generic tool passthrough or model calls.
The broker subprocess owns credentials; thesis workers must not import this.
"""
from datetime import timedelta
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import time

from .operational import read_operational
from .types import BrokerSnapshot, aware_timestamp

CHECKOUT = Path(__file__).resolve().parents[1]


def _run_worker(argv, *, input, timeout, cwd, capture_output=True, text=True):
    """Kill credential-bearing worker descendants on timeout AND normal exit."""
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=text, cwd=cwd,
                               close_fds=True, start_new_session=True)
    try:
        stdout, _ = process.communicate(input=input, timeout=timeout)
        return subprocess.CompletedProcess(argv, process.returncode, stdout, '')
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()


class BrokerFailure(ValueError):
    """Private structural evidence only; never retain a raw exception/payload."""
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = dict(reason=reason, **details)


def configured_broker(root, now, *, deadline=None, clock=time.monotonic, sleep=time.sleep):
    """Read exact durable references, then collect a bounded 90-day snapshot.

    The requested interval is not a lifetime accounting baseline. Missing
    history remains unknown in the accounting layer. Never truncate references.
    """
    started = clock()
    deadline = started + 120 if deadline is None else deadline
    retry_until = min(started + 5, deadline)
    attempts, wait = 0, 0.0
    while True:
        if clock() >= deadline:
            raise BrokerFailure('broker_deadline_exceeded', stage='operational',
                reasons=['operational_lock_busy'] if attempts else [], attempts=attempts,
                wait_seconds=wait, elapsed_seconds=clock() - started)
        if attempts and clock() >= retry_until:
            raise BrokerFailure('broker_operational_snapshot_incomplete', stage='operational',
                reasons=list(snapshot.reasons), attempts=attempts, wait_seconds=wait,
                elapsed_seconds=clock() - started)
        attempts += 1
        snapshot = read_operational(Path(root))
        if snapshot.complete:
            break
        # Only pure contention is retryable. Every attempt releases its lock,
        # obtains fresh copied authority, and repeats all integrity/parity gates.
        if snapshot.reasons != ['operational_lock_busy'] or clock() >= retry_until or attempts >= 51:
            raise BrokerFailure('broker_operational_snapshot_incomplete', stage='operational',
                reasons=list(snapshot.reasons), attempts=attempts, wait_seconds=wait,
                elapsed_seconds=clock() - started)
        delay = min(0.1, max(0, retry_until - clock()))
        wait_started = clock()
        sleep(delay)
        wait += max(0, clock() - wait_started)
    submitted_rows = [row for stream in ('private/order_intents.jsonl',
                      'private/protection_orders.jsonl', 'trade_journal.jsonl')
                      for row in snapshot.streams.get(stream, [])]
    submitted_rows += [row for row in snapshot.streams.get('order_ledger.jsonl', [])
                       if row.get('status') in {'submission_started', 'placed', 'filled', 'closed', 'new'}]
    fields = ('client_order_id', 'parent_client_order_id', 'protection_client_order_id')
    values = [row[field] for row in submitted_rows for field in fields if field in row]
    if any(not isinstance(ref, str) or not ref or len(ref) > 128 for ref in values):
        raise BrokerFailure('broker_references_invalid', stage='references', attempts=attempts,
            wait_seconds=wait, elapsed_seconds=clock() - started)
    refs = sorted(set(values))
    if len(refs) > 500 or any(len(ref) > 128 for ref in refs):
        raise BrokerFailure('broker_references_invalid', stage='references', attempts=attempts,
            wait_seconds=wait, elapsed_seconds=clock() - started)
    payload = dict(refs=refs, start=(now - timedelta(days=90)).isoformat(),
                   end=(now + timedelta(days=1)).isoformat())
    worker_started = clock()
    stage, worker_exit = 'worker_deadline', None
    try:
        remaining = deadline - clock()
        if remaining <= 0:
            raise BrokerFailure('broker_deadline_exceeded', stage=stage,
                attempts=attempts, wait_seconds=wait, elapsed_seconds=clock() - started,
                worker_exit=None, worker_elapsed_seconds=0)
        stage = 'worker_spawn'
        result = _run_worker([sys.executable, '-m', 'watchdog.broker'],
            input=json.dumps(payload), capture_output=True, text=True,
            timeout=min(90, remaining), cwd=CHECKOUT)
        worker_exit = result.returncode
        stage = 'worker_exit'
        if worker_exit != 0:
            raise ValueError('broker_runtime_failed')
        stage = 'worker_decode'
        if len(result.stdout) > 4_000_000:
            raise ValueError('broker_runtime_failed')
        row = json.loads(result.stdout)
        stage = 'worker_schema'
        if not isinstance(row, dict) or set(row) != set(BrokerSnapshot.__dataclass_fields__):
            raise ValueError('broker_runtime_failed')
        aware_timestamp(row['captured_at'])
        if (type(row['complete']) is not bool or not isinstance(row['account'], dict)
                or not isinstance(row['coverage'], dict)
                or any(not isinstance(row[k], list) or any(not isinstance(x, dict) for x in row[k])
                       for k in ('positions', 'orders', 'activities', 'sessions'))):
            raise ValueError('broker_runtime_failed')
        if clock() >= deadline:
            stage = 'worker_deadline'
            raise ValueError('broker_runtime_failed')
        return BrokerSnapshot(**row)
    except BrokerFailure:
        raise
    except (OSError, ValueError, TypeError, RecursionError, subprocess.TimeoutExpired) as error:
        if isinstance(error, subprocess.TimeoutExpired):
            stage = 'worker_timeout'
        reason = ('broker_runtime_timeout' if stage == 'worker_timeout' else
                  'broker_deadline_exceeded' if stage == 'worker_deadline' else 'broker_runtime_failed')
        raise BrokerFailure(reason, stage=stage, attempts=attempts, wait_seconds=wait,
            elapsed_seconds=clock() - started, worker_exit=worker_exit,
            worker_elapsed_seconds=clock() - worker_started) from None


def configured_benchmark(strategy):
    """Load only an explicit observed interval; never fill absent strategy marks."""
    from .benchmark import compare_benchmark
    dates = sorted({row['date'] for row in strategy.get('observations', [])})
    if len(dates) < 2:
        return compare_benchmark(strategy, {})
    try:
        result = _run_worker([sys.executable, '-m', 'watchdog.runtime', 'benchmark'],
            input=json.dumps(dict(start=dates[0], end=dates[-1])),
            capture_output=True, text=True, timeout=30, cwd=CHECKOUT)
        if result.returncode or len(result.stdout) > 4_000_000:
            raise ValueError('benchmark_runtime_failed')
        benchmark = json.loads(result.stdout)
        if not isinstance(benchmark, dict):
            raise ValueError('benchmark_runtime_failed')
    except (OSError, ValueError, RecursionError, subprocess.TimeoutExpired):
        raise ValueError('benchmark_runtime_failed') from None
    return compare_benchmark(strategy, benchmark)


def main():
    """Isolated credential-bearing benchmark worker; one fixed operation."""
    from .benchmark import load_benchmark
    from decimal import Decimal
    try:
        if sys.argv[1:] != ['benchmark']:
            raise ValueError('operation_rejected')
        payload = json.loads(sys.stdin.read(65537))
        if set(payload) != {'start', 'end'}:
            raise ValueError('payload_rejected')
        def encode(value):
            if isinstance(value, Decimal):
                return str(value)
            raise TypeError('unsupported_value')
        print(json.dumps(load_benchmark(**payload), default=encode, allow_nan=False))
        return 0
    except Exception:
        print('benchmark_runtime_failed', file=sys.stderr)
        return 3


class ProviderSession:
    """Lazy, ephemeral provider-only process; no persistent service/config edit."""
    def __init__(self):
        self.directory = self.process = self.socket = None

    def start(self):
        import tempfile
        import time
        self.directory = tempfile.TemporaryDirectory(prefix='watchdog-provider-')
        home = Path(self.directory.name)
        home.chmod(0o700)
        self.socket = home / 'gateway.sock'
        env = {key: os.environ[key] for key in ('HOME', 'HERMES_HOME', 'PATH', 'LANG') if key in os.environ}
        from runtime_paths import hermes_runtime
        python, source = hermes_runtime()
        env.update(HERMES_PYTHON=python, HERMES_SOURCE_ROOT=str(source))
        self.process = subprocess.Popen([python, str(CHECKOUT / 'watchdog/provider_gateway.py'), str(self.socket)],
            env=env, cwd=str(home), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        deadline = time.monotonic() + 12
        while not self.socket.exists():
            if self.process.poll() is not None or time.monotonic() >= deadline:
                raise ValueError('provider_gateway_unavailable')
            time.sleep(0.05)

    def commands(self):
        from .thesis import JSONCommand
        return dict(discover=JSONCommand([sys.executable, '-I', str(CHECKOUT / 'watchdog/source_worker.py'), 'discover']),
                    retrieve=JSONCommand([sys.executable, '-I', str(CHECKOUT / 'watchdog/source_worker.py'), 'retrieve']),
                    classify=JSONCommand([sys.executable, '-I', str(CHECKOUT / 'watchdog/classifier_worker.py'), str(self.socket or '/unavailable/watchdog.sock')]))

    def close(self):
        if self.process is not None:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()
        if self.directory is not None:
            self.directory.cleanup()


from contextlib import contextmanager


@contextmanager
def live_adapters(mode, root, now, transport):
    """Start source/classifier infrastructure only after real eligible broker read.

    Gateway/auth failure leaves broker/mechanical accounting intact and sources
    available; it is a typed thesis gap, not a whole-observation failure.
    """
    from .schedule import eligibility
    gateway = ProviderSession()
    adapters = dict(transport=transport, benchmark=configured_benchmark)
    def broker(*, deadline=None, clock=time.monotonic):
        snapshot = configured_broker(root, now, deadline=deadline, clock=clock)
        if mode == 'daily' and eligibility(mode, now, snapshot.sessions)[0]:
            try:
                gateway.start()
                adapters['thesis_runtime_status'] = 'available'
            except (OSError, ValueError):
                adapters['thesis_runtime_status'] = 'provider_gateway_unavailable'
            adapters['thesis'] = dict(gateway.commands(), now=now.isoformat())
        return snapshot
    adapters['broker'] = broker
    adapters['broker_with_deadline'] = broker
    try:
        yield adapters
    finally:
        gateway.close()


class RelayOutput:
    """Collect sanitized rendered alerts; cron delivers stdout after process exit.

    No provider receipt is available here. Returning None leaves evidence outbox
    rows pending. Under the explicitly activated concise policy, independent
    emission bookkeeping prevents historical receiptless outbox replay.
    """
    def __init__(self):
        self.messages = []

    def __call__(self, alert, rendered):
        self.messages.append(rendered)
        return None

    def text(self):
        if not self.messages:
            return ''
        return '\n\n'.join(self.messages) + '\n\nDelivery unverified.'


if __name__ == '__main__':
    raise SystemExit(main())
