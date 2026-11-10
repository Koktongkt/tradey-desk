import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from sqlite_ledger import DEFAULT_STREAMS


class OperationalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=tempfile.gettempdir())
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

    def test_zeroed_equal_shm_never_mutates_source(self):
        from watchdog.operational import read_operational
        writer = sqlite3.connect(self.db)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.close()
        Path(str(self.db) + '-wal').write_bytes(b'')
        for raw in (bytes(136), b'x' * 32768, b'bad'):
            with self.subTest(shm_size=len(raw)):
                Path(str(self.db) + '-shm').write_bytes(raw)
                before = self.state()
                result = read_operational(self.root)
                self.assertTrue(result.complete, result.reasons)
                self.assertEqual(before, self.state())

    def test_baseline_case_normalization_preserves_genuine_strings(self):
        from watchdog.operational import read_operational
        baseline = self.root / 'private/broker_baseline.json'
        baseline.write_text(json.dumps({'preexisting_symbols': ['aapl', 'MsFt', 'AAPL', 'éx']}))
        before = self.state()
        result = read_operational(self.root)
        self.assertTrue(result.complete, result.reasons)
        self.assertEqual(result.baseline_symbols, frozenset({'AAPL', 'MSFT', 'ÉX'}))
        self.assertEqual(before, self.state())
        for value in (True, 123, None, {}, [], '', 'BRK.B', ' AAPL'):
            with self.subTest(value=value):
                baseline.write_text(json.dumps({'preexisting_symbols': [value]}))
                before = self.state()
                self.assertFalse(read_operational(self.root).complete)
                self.assertEqual(before, self.state())

    def test_orphaned_valid_sidecars_are_read_without_source_attachment(self):
        from unittest.mock import patch
        from watchdog.operational import read_operational
        writer = sqlite3.connect(self.db)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("UPDATE ledger_entries SET appended_at='orphan'")
        writer.commit()
        sidecars = {suffix: Path(str(self.db) + suffix).read_bytes() for suffix in ('-wal', '-shm')}
        writer.close()
        for suffix, raw in sidecars.items():
            Path(str(self.db) + suffix).write_bytes(raw)
        before = self.state()
        scratch = Path(tempfile.gettempdir())
        prior = set(scratch.glob('watchdog-*'))
        connect = sqlite3.connect
        targets = []
        def local_connect(database, **kwargs):
            targets.append(database)
            self.assertTrue(database.startswith(scratch.as_uri() + '/watchdog-'), database)
            self.assertTrue(database.endswith('?mode=ro'), database)
            return connect(database, **kwargs)
        with patch('watchdog.operational.sqlite3.connect', side_effect=local_connect):
            result = read_operational(self.root)
        self.assertTrue(result.complete, result.reasons)
        self.assertEqual(len(targets), 1)
        self.assertEqual(before, self.state())
        self.assertEqual(prior, set(scratch.glob('watchdog-*')))

    def test_normal_ledger_writer_lifecycle_produces_complete_snapshots(self):
        from sqlite_ledger import migrate_jsonl, append_jsonl
        from watchdog.operational import read_operational
        # Real writer schema, migration and append; every connection closes
        # before watchdog starts, just like production. No live storage involved.
        self.db.unlink()
        migrate_jsonl(self.root)
        for index in range(3):
            row = {'symbol': 'ABC', 'iteration': index}
            append_jsonl(self.root / 'order_ledger.jsonl', row)
            before = self.state()
            first = read_operational(self.root)
            second = read_operational(self.root)
            self.assertTrue(first.complete, first.reasons)
            self.assertTrue(second.complete, second.reasons)
            self.assertEqual(first.streams['order_ledger.jsonl'][-1], row)
            self.assertEqual(first.streams, second.streams)
            self.assertEqual(before, self.state())

    def test_ledger_streams_outside_defaults_are_recognized(self):
        # Production journal drift: newer features (source-attempts tracking,
        # overlay publication) write ledger streams the operational reader did
        # not whitelist, so every snapshot was rejected as history-incomplete
        # and the protection watchdog failed closed. After the registry
        # includes those streams, a journal holding them reads complete, and
        # their projections are verified against the SQLite history.
        from watchdog.operational import read_operational
        rows = {
            'private/source_attempts.jsonl': [
                {'timestamp': '2026-10-19T14:02:50Z', 'url': 'https://example.com/a'}],
            'public/overlay/candidates.jsonl': [
                {'timestamp': '2026-10-17T05:16:00Z', 'symbol': 'ABC'}],
            'public/overlay/decision_audit.jsonl': [
                {'timestamp': '2026-10-17T05:16:00Z', 'symbol': 'ABC'}],
            'public/overlay/order_ledger.jsonl': [
                {'timestamp': '2026-10-17T05:16:00Z', 'symbol': 'ABC'}],
        }
        for stream, stream_rows in rows.items():
            for row in stream_rows:
                # setUp closes its connection; reopen a private writer.
                connection = sqlite3.connect(self.db)
                try:
                    payload = json.dumps(row, sort_keys=True, separators=(',', ':'))
                    connection.execute(
                        'INSERT INTO ledger_entries VALUES (?,1,?,?,?)',
                        (stream, payload, hashlib.sha256(payload.encode()).hexdigest(), '2026-01-01T00:00:00Z'))
                    connection.commit()
                finally:
                    connection.close()
                path = self.root / stream
                path.parent.mkdir(exist_ok=True)
                path.write_text(payload + '\n')
        result = read_operational(self.root)
        self.assertTrue(result.complete, result.reasons)
        for stream, stream_rows in rows.items():
            self.assertEqual(result.streams[stream], stream_rows)

    def test_research_policy_diagnostics_writer_remains_readable_without_writes(self):
        from sqlite_ledger import migrate_jsonl, append_jsonl
        from watchdog.operational import read_operational
        self.db.unlink()
        migrate_jsonl(self.root)
        stream = 'private/research_policy_diagnostics.jsonl'
        rows = [
            {'timestamp': '2026-11-09T14:04:26Z', 'reason': 'opportunity_identity_unknown'},
            {'timestamp': '2026-11-09T14:04:27Z', 'reason': 'opportunity_identity_unknown'},
        ]
        from policy_diagnostics import policy_diagnostic
        rows.append(policy_diagnostic('opportunity_identity_unknown',timestamp='2026-11-10T14:04:27Z',
                                      run_id='a'*32,symbol='ACME',capture_count=0))
        for row in rows:
            append_jsonl(self.root / stream, row)
        before = self.state()
        snapshot = read_operational(self.root)
        self.assertTrue(snapshot.complete, snapshot.reasons)
        self.assertEqual(snapshot.streams[stream], rows)
        self.assertEqual(before, self.state())

    def test_research_policy_diagnostics_corruption_stays_fail_closed(self):
        from watchdog.operational import read_operational
        stream = 'private/research_policy_diagnostics.jsonl'
        self.connection = sqlite3.connect(self.db)
        try:
            self.add_row(stream, {'timestamp': '2026-11-09T14:04:26Z',
                                  'reason': 'opportunity_identity_unknown'})
        finally:
            self.connection.close()
        original = self.state()
        for case in ('digest', 'sequence', 'projection', 'missing_projection'):
            with self.subTest(case=case):
                for name, (data, _, _) in original.items():
                    (self.root / name).write_bytes(data)
                if case in ('digest', 'sequence'):
                    with sqlite3.connect(self.db) as connection:
                        connection.execute(
                            'UPDATE ledger_entries SET ' +
                            ('record_sha256=?' if case == 'digest' else 'sequence=?') +
                            ' WHERE stream=?',
                            ('0' * 64 if case == 'digest' else 2, stream))
                    connection.close()
                elif case == 'projection':
                    (self.root / stream).write_text('{"reason":"different"}\n')
                else:
                    (self.root / stream).unlink()
                before = self.state()
                result = read_operational(self.root)
                self.assertFalse(result.complete)
                self.assertIn('operational_history_incomplete', result.reasons)
                self.assertEqual(before, self.state())

    def test_research_policy_projection_without_history_stays_fail_closed(self):
        from watchdog.operational import read_operational
        path = self.root / 'private/research_policy_diagnostics.jsonl'
        path.write_text('')
        before = self.state()
        empty = read_operational(self.root)
        self.assertTrue(empty.complete, empty.reasons)
        self.assertIn('private/research_policy_diagnostics.jsonl', empty.streams)
        self.assertEqual(empty.streams[path.relative_to(self.root).as_posix()], [])
        self.assertEqual(before, self.state())
        path.write_text('{"reason":"opportunity_identity_unknown"}\n')
        before = self.state()
        unimported = read_operational(self.root)
        self.assertFalse(unimported.complete)
        self.assertIn('operational_history_incomplete', unimported.reasons)
        self.assertEqual(before, self.state())

    def test_watchdog_registration_preserves_existing_prospective_baseline(self):
        import opportunity_cutover as cutover
        import sqlite_ledger as storage
        # Persist the exact 18-stream contract used before the watchdog repair.
        # This fixture must not grow implicitly with DEFAULT_STREAMS.
        prior_streams = (
            'candidates.jsonl', 'candidate_outcomes.jsonl', 'decision_audit.jsonl',
            'order_ledger.jsonl', 'trade_journal.jsonl',
            'private/blocker_diagnostics.jsonl', 'private/bridge_diagnostics.jsonl',
            'private/opportunity_policy.jsonl', 'private/order_intents.jsonl',
            'private/order_notifications.jsonl', 'private/protection_orders.jsonl',
            'private/research_diagnostics.jsonl', 'private/reviews.jsonl',
            'private/source_attempts.jsonl', 'public/disagreements.jsonl',
            'public/overlay/candidates.jsonl', 'public/overlay/decision_audit.jsonl',
            'public/overlay/order_ledger.jsonl',
        )
        def digest(value):
            raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                             allow_nan=False, ensure_ascii=True).encode()
            return hashlib.sha256(raw).hexdigest()
        order_row = {'timestamp': '2026-01-01T00:00:00Z', 'symbol': 'ABC'}
        baseline = {
            'version': 1, 'root': str(self.root.resolve()),
            'reopening_mode': 'manual_only',
            'streams': {name: {
                'sequence': 1 if name == 'order_ledger.jsonl' else 0,
                'prefix_sha256': (hashlib.sha256(json.dumps(
                    order_row, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                    if name == 'order_ledger.jsonl' else hashlib.sha256(b'').hexdigest()),
            } for name in prior_streams},
        }
        baseline['baseline_id'] = digest(baseline)
        manifest = {'manifest_version': 2, 'policy_version': 2, 'baseline': baseline}
        self.connection = sqlite3.connect(self.db)
        try:
            self.add_row('private/opportunity_policy.jsonl', {
                'record_type': 'activation', 'schema_version': 1, 'policy_version': 2,
                'timestamp': '2026-11-09T10:04:32Z',
                'manifest_sha256': digest(manifest), 'prospective_baseline': baseline,
            })
        finally:
            self.connection.close()
        before = self.state()
        snapshot = storage.read_stream_snapshot_readonly(self.root, cutover.BASELINE_STREAMS)
        self.assertEqual(cutover.active_baseline(snapshot), baseline)
        self.assertEqual(before, self.state())

    def test_unregistered_stream_stays_fail_closed_without_writes(self):
        from watchdog.operational import read_operational
        self.connection = sqlite3.connect(self.db)
        try:
            self.add_row('private/unregistered_diagnostic.jsonl', {'reason': 'unknown'})
        finally:
            self.connection.close()
        before = self.state()
        result = read_operational(self.root)
        self.assertFalse(result.complete)
        self.assertIn('operational_history_incomplete', result.reasons)
        self.assertEqual(before, self.state())

    def test_money_and_timestamp_contracts(self):
        from datetime import datetime, timezone
        from decimal import Decimal
        from watchdog.types import money, aware_timestamp, snapshot_time_reasons
        self.assertEqual(money('12.30'), Decimal('12.30'))
        for value in (True, False, 'NaN', float('inf'), None, {}, ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                money(value)
        # Finite Decimals with absurd exponents/digit counts are rejected:
        # they would later render as unrepresentable public amounts.
        for value in ('1e+200', '1e-1000', '1' + '0' * 250, Decimal('1E+500')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                money(value)
        self.assertEqual(money('1e+199'), Decimal('1e+199'))
        self.assertEqual(money('0.001'), Decimal('0.001'))
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
        self.assertTrue(snapshot.complete, snapshot.reasons)
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
        scratch = Path(tempfile.gettempdir())
        prior = set(scratch.glob('watchdog-*'))
        with patch('watchdog.operational.sqlite3.connect', side_effect=sqlite3.OperationalError('secret path')):
            snapshot = read_operational(self.root)
        self.assertFalse(snapshot.complete)
        self.assertNotIn('secret', str(snapshot.reasons))
        self.assertEqual(prior, set(scratch.glob('watchdog-*')))
        self.assertEqual(before, self.state())

    def test_undersized_shm_is_ignored_without_source_writes(self):
        from watchdog.operational import read_operational
        with sqlite3.connect(self.db) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
        writer.close()
        Path(str(self.db) + '-wal').write_bytes(b'')
        Path(str(self.db) + '-shm').write_bytes(b'bad')
        before = self.state()
        result = read_operational(self.root)
        self.assertTrue(result.complete, result.reasons)
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
        self.assertTrue(result.complete, result.reasons)
        self.assertEqual(before, self.state())

    def test_existing_writer_lock_is_retryable_without_modification(self):
        import fcntl
        from watchdog.operational import read_operational
        before = self.state()
        with Path(str(self.db) + '.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = read_operational(self.root)
        self.assertFalse(result.complete)
        self.assertEqual(['operational_lock_busy'], result.reasons)
        self.assertEqual(before, self.state())

    def state(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), (p.stat().st_dev, p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_ctime_ns), p.stat().st_size) for p in self.root.rglob('*') if p.is_file()}

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
