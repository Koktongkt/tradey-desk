import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from sqlite_ledger import DEFAULT_STREAMS


class OperationalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'private').mkdir()
        self.db = self.root / 'private/trading_journal.sqlite3'
        Path(str(self.db) + '.lock').write_bytes(b'')
        self.connection = sqlite3.connect(self.db)
        self.connection.execute('CREATE TABLE ledger_entries(stream TEXT, sequence INTEGER, record_json TEXT, record_sha256 TEXT, appended_at TEXT)')
        self.connection.execute('PRAGMA user_version=1')
        for stream in DEFAULT_STREAMS:
            path = self.root / stream
            path.parent.mkdir(exist_ok=True)
            path.write_text('')
        self.add_row('order_ledger.jsonl', {'timestamp': '2026-01-01T00:00:00Z', 'symbol': 'ABC'})
        (self.root / 'private/broker_baseline.json').write_text('{"preexisting_symbols": ["XYZ"]}')
        self.connection.close()

    def add_row(self, stream, row):
        payload = json.dumps(row, sort_keys=True, separators=(',', ':'))
        self.connection.execute('INSERT INTO ledger_entries VALUES (?,1,?,?,?)', (stream, payload, hashlib.sha256(payload.encode()).hexdigest(), '2026-01-01T00:00:00Z'))
        self.connection.commit()
        (self.root / stream).write_text(payload + '\n')

    def test_invalid_inputs_are_incomplete_without_writes(self):
        from watchdog.operational import read_operational
        cases = ('missing_db', 'missing_history', 'partial', 'digest', 'sequence', 'payload_type', 'baseline')
        original = self.state()
        for case in cases:
            with self.subTest(case=case):
                for name, (data, _, _) in original.items():
                    (self.root / name).write_bytes(data)
                if case == 'missing_db':
                    self.db.unlink()
                elif case == 'missing_history':
                    (self.root / 'trade_journal.jsonl').unlink()
                elif case == 'partial':
                    (self.root / 'order_ledger.jsonl').write_text('{"unfinished":')
                elif case == 'payload_type':
                    with sqlite3.connect(self.db) as conn:
                        conn.execute('UPDATE ledger_entries SET record_json=NULL')
                    conn.close()
                elif case in ('digest', 'sequence'):
                    with sqlite3.connect(self.db) as conn:
                        conn.execute('UPDATE ledger_entries SET ' + ('record_sha256="bad"' if case == 'digest' else 'sequence=2'))
                    conn.close()
                else:
                    (self.root / 'private/broker_baseline.json').write_text('{"preexisting_symbols": [true]}')
                before = self.state()
                self.assertFalse(read_operational(self.root).complete)
                self.assertEqual(before, self.state())

    def test_money_and_timestamp_contracts(self):
        from datetime import datetime, timezone
        from decimal import Decimal
        from watchdog.types import money, aware_timestamp, snapshot_time_reasons
        self.assertEqual(money('12.30'), Decimal('12.30'))
        for value in (True, False, 'NaN', float('inf'), None, {}, ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                money(value)
        self.assertEqual(aware_timestamp('2026-01-01T00:00:00Z').tzinfo, timezone.utc)
        for value in ('2026-01-01', '2026-01-01T00:00:00', True, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                aware_timestamp(value)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        future = '2026-01-02T00:00:00Z'
        self.assertEqual(aware_timestamp(future).day, 2)
        self.assertEqual(snapshot_time_reasons(future, now=now), ['snapshot_timestamp_future'])
        self.assertEqual(snapshot_time_reasons('2025-12-01T00:00:00Z', now=now, max_age_seconds=60), ['snapshot_timestamp_stale'])
        self.assertEqual(snapshot_time_reasons(now.isoformat(), now=now), [])

    def test_shared_contract_fields(self):
        from watchdog.types import BrokerSnapshot, LineageResult, RunObservation
        broker = BrokerSnapshot({}, [], [], [], [], '2026-01-01T00:00:00Z', False, {})
        self.assertFalse(broker.complete)
        self.assertEqual(LineageResult([], [], {}, []).positions, [])
        self.assertEqual(RunObservation('run', '2026-01-01', 'mechanical', [], {}, {}, [], {}, []).run_id, 'run')

    def test_active_wal_read_parity_without_artifacts(self):
        from watchdog.operational import read_operational
        writer = sqlite3.connect(self.db)
        self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("UPDATE ledger_entries SET appended_at='2026-01-02T00:00:00Z'")
        writer.commit()
        # A current broker/ledger reader has established a usable read mark.
        current = sqlite3.connect(self.db)
        self.addCleanup(current.close)
        current.execute('BEGIN')
        current.execute('SELECT * FROM ledger_entries').fetchall()
        before = self.state()
        snapshot = read_operational(self.root)
        self.assertTrue(snapshot.complete, snapshot.reasons)
        self.assertEqual(before, self.state())

    def test_wal_without_sidecars_never_creates_them(self):
        from watchdog.operational import read_operational
        with sqlite3.connect(self.db) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
        conn.close()
        before = self.state()
        snapshot = read_operational(self.root)
        self.assertFalse(snapshot.complete)
        self.assertIn('operational_wal_unavailable', snapshot.reasons)
        self.assertEqual(before, self.state())

    def test_concurrent_projection_change_is_retryable(self):
        from unittest.mock import patch
        from watchdog.operational import read_operational
        original = Path.read_bytes
        changed = False
        def read(path):
            nonlocal changed
            raw = original(path)
            if path == self.root / 'order_ledger.jsonl' and not changed:
                changed = True
                path.write_bytes(raw + b'\n')
            return raw
        with patch.object(Path, 'read_bytes', read):
            result = read_operational(self.root)
        self.assertFalse(result.complete)
        self.assertIn('operational_snapshot_changed', result.reasons)

    def test_readonly_open_failure_is_incomplete(self):
        from unittest.mock import patch
        from watchdog.operational import read_operational
        before = self.state()
        with patch('watchdog.operational.sqlite3.connect', side_effect=sqlite3.OperationalError('secret path')):
            snapshot = read_operational(self.root)
        self.assertFalse(snapshot.complete)
        self.assertNotIn('secret', str(snapshot.reasons))
        self.assertEqual(before, self.state())

    def test_unusable_wal_shm_is_incomplete_without_open(self):
        from watchdog.operational import read_operational
        with sqlite3.connect(self.db) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
        writer.close()
        Path(str(self.db) + '-wal').write_bytes(b'')
        Path(str(self.db) + '-shm').write_bytes(b'bad')
        before = self.state()
        result = read_operational(self.root)
        self.assertFalse(result.complete)
        self.assertIn('operational_wal_unavailable', result.reasons)
        self.assertEqual(before, self.state())

    def test_unsupported_schema_is_incomplete(self):
        from watchdog.operational import read_operational
        with sqlite3.connect(self.db) as conn:
            conn.execute('PRAGMA user_version=99')
        conn.close()
        self.assertFalse(read_operational(self.root).complete)

    def test_duplicate_projection_keys_are_not_silently_accepted(self):
        from watchdog.operational import read_operational
        (self.root / 'order_ledger.jsonl').write_text('{"symbol":"OTHER","symbol":"ABC","timestamp":"2026-01-01T00:00:00Z"}\n')
        self.assertFalse(read_operational(self.root).complete)

    def test_active_wal_with_older_reader_does_not_change_shm(self):
        from watchdog.operational import read_operational
        writer = sqlite3.connect(self.db)
        reader = sqlite3.connect(self.db)
        self.addCleanup(writer.close)
        self.addCleanup(reader.close)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('UPDATE ledger_entries SET appended_at=appended_at')
        writer.commit()
        reader.execute('BEGIN')
        reader.execute('SELECT * FROM ledger_entries').fetchall()
        writer.execute("UPDATE ledger_entries SET appended_at='2026-01-02T00:00:00Z'")
        writer.commit()
        before = self.state()
        result = read_operational(self.root)
        self.assertFalse(result.complete)
        self.assertIn('operational_wal_unavailable', result.reasons)
        self.assertEqual(before, self.state())

    def test_existing_writer_lock_is_retryable_without_modification(self):
        import fcntl
        from watchdog.operational import read_operational
        before = self.state()
        with Path(str(self.db) + '.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = read_operational(self.root)
        self.assertFalse(result.complete)
        self.assertIn('operational_snapshot_changed', result.reasons)
        self.assertEqual(before, self.state())

    def state(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_size) for p in self.root.rglob('*') if p.is_file()}

    def test_read_does_not_repair_or_create_files(self):
        from watchdog.operational import read_operational
        before = self.state()
        first = read_operational(self.root)
        second = read_operational(self.root)
        self.assertTrue(first.complete, first.reasons)
        self.assertEqual(first.streams, second.streams)
        self.assertEqual(first.baseline_symbols, frozenset({'XYZ'}))
        self.assertEqual(before, self.state())
        (self.root / 'order_ledger.jsonl').write_text('{"symbol":"OTHER"}\n')
        before = self.state()
        self.assertFalse(read_operational(self.root).complete)
        self.assertEqual(before, self.state())
