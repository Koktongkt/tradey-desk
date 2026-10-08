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


def configured_broker(root, now):
    """Read exact durable references, then collect a bounded 90-day snapshot.

    The requested interval is not a lifetime accounting baseline. Missing
    history remains unknown in the accounting layer. Never truncate references.
    """
    snapshot = read_operational(Path(root))
    if not snapshot.complete:
        raise ValueError('broker_operational_snapshot_incomplete')
    submitted_rows = [row for stream in ('private/order_intents.jsonl',
                      'private/protection_orders.jsonl', 'trade_journal.jsonl')
                      for row in snapshot.streams.get(stream, [])]
    submitted_rows += [row for row in snapshot.streams.get('order_ledger.jsonl', [])
                       if row.get('status') in {'submission_started', 'placed', 'filled', 'closed', 'new'}]
    fields = ('client_order_id', 'parent_client_order_id', 'protection_client_order_id')
    values = [row[field] for row in submitted_rows for field in fields if field in row]
    if any(not isinstance(ref, str) or not ref or len(ref) > 128 for ref in values):
        raise ValueError('broker_references_invalid')
    refs = sorted(set(values))
    if len(refs) > 500 or any(len(ref) > 128 for ref in refs):
        raise ValueError('broker_references_invalid')
    payload = dict(refs=refs, start=(now - timedelta(days=90)).isoformat(),
                   end=(now + timedelta(days=1)).isoformat())
    try:
        result = _run_worker([sys.executable, '-m', 'watchdog.broker'],
            input=json.dumps(payload), capture_output=True, text=True,
            timeout=90, cwd=CHECKOUT)
        if result.returncode != 0 or len(result.stdout) > 4_000_000:
            raise ValueError('broker_runtime_failed')
        row = json.loads(result.stdout)
        if set(row) != set(BrokerSnapshot.__dataclass_fields__):
            raise ValueError('broker_runtime_failed')
        aware_timestamp(row['captured_at'])
        if (type(row['complete']) is not bool or not isinstance(row['account'], dict)
                or not isinstance(row['coverage'], dict)
                or any(not isinstance(row[k], list) or any(not isinstance(x, dict) for x in row[k])
                       for k in ('positions', 'orders', 'activities', 'sessions'))):
            raise ValueError('broker_runtime_failed')
        return BrokerSnapshot(**row)
    except subprocess.TimeoutExpired:
        raise TimeoutError('broker_runtime_timeout') from None
    except (OSError, ValueError, TypeError, RecursionError):
        raise ValueError('broker_runtime_failed') from None


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
        self.process = subprocess.Popen(['/opt/hermes/.venv/bin/python', str(CHECKOUT / 'watchdog/provider_gateway.py'), str(self.socket)],
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
    def broker():
        snapshot = configured_broker(root, now)
        if mode == 'daily' and eligibility(mode, now, snapshot.sessions)[0]:
            try:
                gateway.start()
                adapters['thesis_runtime_status'] = 'available'
            except (OSError, ValueError):
                adapters['thesis_runtime_status'] = 'provider_gateway_unavailable'
            adapters['thesis'] = dict(gateway.commands(), now=now.isoformat())
        return snapshot
    adapters['broker'] = broker
    try:
        yield adapters
    finally:
        gateway.close()


class RelayOutput:
    """Collect sanitized rendered alerts; cron delivers stdout after process exit.

    No provider receipt is available here. Returning None intentionally keeps
    the outbox pending; subsequent eligible runs may repeat these notifications.
    """
    def __init__(self):
        self.messages = []

    def __call__(self, alert, rendered):
        self.messages.append(rendered)
        return None

    def text(self):
        if not self.messages:
            return ''
        return '\n\n'.join(self.messages) + '\n\nDelivery unverified; pending alerts may repeat.'


if __name__ == '__main__':
    raise SystemExit(main())
