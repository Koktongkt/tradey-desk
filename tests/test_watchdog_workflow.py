"""Task 8 scenario workflow tests: isolated vertical CLI workflows.

Real pure modules/store plus only fake external adapters. All writes stay
inside <worktree>/test_artifacts; no live network, broker, scheduler or
publication. Marker files, locks and reports live solely under the selected
output root.
"""
import copy
import fcntl
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from unittest import TestCase
from zoneinfo import ZoneInfo

from sqlite_ledger import append_jsonl, migrate_jsonl  # noqa: F401  (fixture docs)
from watchdog.store import pending_alerts, read_report, read_source_state
from watchdog.types import BrokerSnapshot

CHECKOUT = Path(__file__).resolve().parents[1]
UTC = ZoneInfo('UTC')
NOW = datetime(2026, 10, 7, 14, 5, tzinfo=UTC)  # Wednesday, inside session
DAILY_NOW = datetime(2026, 10, 7, 20, 15, tzinfo=UTC)  # close+15, first daily slot
SESSION = dict(date='2026-10-07', open='09:30', close='16:00',
               open_at='2026-10-07T09:30:00-04:00', close_at='2026-10-07T16:00:00-04:00')


def build_operational_root(base, candidate_overrides=None):
    """Isolated operational fixture root built directly (sqlite_ledger's
    _storage_root hoists test_artifacts subtrees to the shared root, so the
    ledger is constructed in place with the same schema and rows)."""
    import hashlib
    import sqlite3
    root = base / 'root'
    (root / 'private').mkdir(parents=True)
    candidate = dict(candidate_id='idea-a', dossier_hash='da', symbol='ABC',
                     thesis='grow', event_date='2026-10-30',
                     catalyst=dict(date='2026-10-30', description='earnings'),
                     assumptions=[dict(id='a1', metric='eps', operator='>', threshold='1')],
                     breakers=[dict(id='b1', metric='eps', operator='<', threshold='0.5')],
                     kpis=['k'], risks=['r'])
    if candidate_overrides:
        candidate.update(candidate_overrides)
    rows = {
        'candidates.jsonl': [candidate],
        'private/reviews.jsonl': [dict(dossier_hash='da', proposal_hash='pa', evidence_id='ea',
                                       reviews=[dict(decision='APPROVE')])],
        'private/order_intents.jsonl': [dict(client_order_id='parent',
                                             plan=dict(proposal_hash='pa', symbol='ABC', action='BUY',
                                                       planned_exit_at='2026-10-09T20:00:00Z',
                                                       stop=9, target=12, qty=2))],
    }
    canonical = {}
    for stream, entries in rows.items():
        path = root / stream
        path.write_text(''.join(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n'
                                for row in entries))
        canonical[stream] = [json.dumps(row, sort_keys=True, separators=(',', ':')) for row in entries]
    db = root / 'private/trading_journal.sqlite3'
    connection = sqlite3.connect(db)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.executescript('''
        CREATE TABLE ledger_entries (
            id INTEGER PRIMARY KEY,
            stream TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            record_json TEXT NOT NULL,
            record_sha256 TEXT NOT NULL,
            appended_at TEXT NOT NULL,
            UNIQUE(stream, sequence));''')
    sequence = {}
    for stream, payloads in canonical.items():
        for payload in payloads:
            sequence[stream] = sequence.get(stream, 0) + 1
            connection.execute('INSERT INTO ledger_entries VALUES (?,?,?,?,?,?)',
                               (None, stream, sequence[stream], payload,
                                hashlib.sha256(payload.encode()).hexdigest(),
                                '2026-10-07T13:00:00+00:00'))
    connection.execute('PRAGMA user_version=1')
    connection.commit()
    connection.close()
    from sqlite_ledger import DEFAULT_STREAMS
    for stream in DEFAULT_STREAMS:
        stream_path = root / stream
        if not stream_path.exists():
            stream_path.parent.mkdir(parents=True, exist_ok=True)
            stream_path.touch()
    (root / 'private/trading_journal.sqlite3.lock').touch()
    (root / 'private/broker_baseline.json').write_text(json.dumps({'preexisting_symbols': ['LEG']}))
    return root


def broker_snapshot(complete=True, extra_symbol='LEG', stop_status='open'):
    order = dict(id='broker-parent', client_order_id='parent', symbol='ABC', side='buy',
                 type='market', status='filled', qty=D('2'), filled_qty=D('2'),
                 filled_avg_price=D('10'), legs=[])
    if stop_status is not None:
        order['legs'] = [dict(id='leg-stop', client_order_id='stop-1', symbol='ABC', side='sell',
                              type='stop', status=stop_status, qty=D('2'), filled_qty=D('0'), stop_price=D('9'))]
    positions = [dict(symbol='ABC', qty=D('2'))]
    if extra_symbol:
        positions.append(dict(symbol=extra_symbol, qty=D('1')))
    return BrokerSnapshot(
        dict(equity=D('50000'), cash=D('40000'),
             provenance=dict(equity='get_account.equity', cash='get_account.cash')),
        positions, [order], [], [dict(SESSION)],
        '2026-10-07T14:00:00+00:00', complete,
        dict(orders='complete', references='complete', activities='complete',
             account='complete', calendar='complete'))


class WorkflowCase(TestCase):
    def setUp(self):
        self.artifacts = Path(tempfile.mkdtemp(prefix='workflow-', dir=CHECKOUT / 'test_artifacts'))
        self.root = build_operational_root(self.artifacts)
        self.output_root = self.artifacts / 'output'
        self.output_root.mkdir()
        self.db = self.output_root / 'private/watchdog/monitoring.sqlite3'
        self.receipts = []

    def tearDown(self):
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def adapters(self, broker=None, **overrides):
        adapters = {
            'broker': (broker or (lambda: broker_snapshot())),
            'benchmark': lambda strategy: dict(return_kind='total_return',
                                               strategy_return=None, benchmark_return=None),
            'transport': lambda alert, rendered: self.receipts.append(alert) or dict(
                provider='test', message_id='m-' + alert.get('key', 'x'), status='delivered',
                verified_at='2026-10-07T14:06:00+00:00', verification='provider_readback'),
        }
        adapters.update(overrides)
        return adapters

    def input_digest(self):
        import hashlib
        db = self.root / 'private/trading_journal.sqlite3'
        return hashlib.sha256(db.read_bytes()).hexdigest()

    def thesis_adapters(self, now=NOW, checked_offset_seconds=-60):
        worker = self.artifacts / 'thesis_worker.py'
        worker.write_text(
            "import json,sys\n"
            "from datetime import datetime, timedelta\n"
            "req = json.load(sys.stdin)\n"
            "if 'classifications' in req:\n"
            "    json.dump({'classifications': [{'events': []} for _ in req['classifications']]}, sys.stdout)\n"
            "else:\n"
            "    checked = (datetime.fromisoformat(req['now']) + timedelta(seconds=%d)).isoformat()\n"
            "    json.dump({'sources': {s: {'status': 'complete', 'checked_through': checked,\n"
            "        'coverage_url': 'https://example.com/' + s + '/listing', 'urls': []}\n"
            "        for s in ('sec', 'issuer', 'earnings')}}, sys.stdout)\n" % checked_offset_seconds)
        from watchdog.thesis import JSONCommand
        return {'discover': JSONCommand([sys.executable, str(worker)]),
                'retrieve': JSONCommand([sys.executable, str(worker)]),
                'classify': JSONCommand([sys.executable, str(worker)]),
                'now': now.astimezone(timezone.utc).isoformat()}


class MechanicalWorkflowTests(WorkflowCase):
    def test_mechanical_run_commits_reports_and_delivers_alerts(self):
        from watchdog.cli import run_watchdog
        before = self.input_digest()
        inputs = (self.root / 'private/trading_journal.sqlite3').read_bytes()
        result = run_watchdog('mechanical', self.root, self.output_root,
                              self.adapters(broker=lambda: broker_snapshot(stop_status='canceled')), NOW)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['mode'], 'mechanical')
        self.assertTrue(self.db.exists())
        report = read_report(self.db)
        self.assertEqual(report.get('mode'), 'mechanical')
        self.assertEqual(report.get('run_id'), result['run_id'])
        # Reports installed under the selected output root only.
        self.assertTrue((self.output_root / 'private/watchdog/latest.json').exists())
        # Cancelled stop must surface as a pending condition alert, delivered.
        pending = pending_alerts(self.db)
        self.assertEqual(pending, [])
        self.assertTrue(self.receipts)
        self.assertTrue(any(a.get('kind') in ('protection', 'recovery') for a in self.receipts))
        # Operational input bytes and stat immutability before/after.
        self.assertEqual(self.input_digest(), before)
        self.assertTrue(result['input_unchanged'])
        self.assertEqual((self.root / 'private/trading_journal.sqlite3').read_bytes(), inputs)

    def test_mechanical_inputs_not_mutated_by_run(self):
        from watchdog.cli import run_watchdog
        broker = broker_snapshot()
        frozen = copy.deepcopy(broker)
        run_watchdog('mechanical', self.root, self.output_root, self.adapters(broker=lambda: broker), NOW)
        self.assertEqual(broker, frozen)

    def test_legacy_holdings_and_missing_thesis_baseline_are_gaps_not_all_clear(self):
        from watchdog.cli import run_watchdog
        result = run_watchdog('mechanical', self.root, self.output_root, self.adapters(), NOW)
        self.assertFalse(result['all_clear'])
        report = read_report(self.db)
        exposure = report['portfolio']['exposure']
        self.assertTrue(any(row['symbol'] == 'LEG' for row in exposure['legacy_holdings']))
        self.assertTrue(result['reasons'] or exposure['coverage']['status'] != 'complete')

    def test_pending_protection_is_observed(self):
        from watchdog.cli import run_watchdog
        run_watchdog('mechanical', self.root, self.output_root,
                     self.adapters(broker=lambda: broker_snapshot(stop_status='canceled')), NOW)
        report = read_report(self.db)
        statuses = {p['protection_status'] for p in report['positions']}
        self.assertIn('unprotected', statuses)

    def test_incomplete_broker_snapshot_is_successful_with_gaps(self):
        from watchdog.cli import run_watchdog
        result = run_watchdog('mechanical', self.root, self.output_root,
                              self.adapters(broker=lambda: broker_snapshot(complete=False)), NOW)
        self.assertEqual(result['status'], 'ok')
        self.assertFalse(result['all_clear'])
        self.assertIn('incomplete', (read_report(self.db)['coverage']['status'], *result['reasons']))

    def test_operational_input_change_after_run_is_typed(self):
        from watchdog.cli import run_watchdog
        original = self.adapters()['broker']

        def mutating_broker():
            snapshot = original()
            with (self.root / 'candidates.jsonl').open('ab') as stream:
                stream.write(b'\n')  # size change on an operational input
            return snapshot

        result = run_watchdog('mechanical', self.root, self.output_root,
                              self.adapters(broker=mutating_broker), NOW)
        self.assertFalse(result['input_unchanged'])
        self.assertIn('operational_input_changed_after_run', result['reasons'])


class OperationalInputDigestTests(WorkflowCase):
    def test_digests_cover_sqlite_wal_and_shm_when_present(self):
        from watchdog.cli import _input_digests, _input_unchanged
        db = self.root / 'private/trading_journal.sqlite3'
        wal = Path(str(db) + '-wal')
        shm = Path(str(db) + '-shm')
        self.assertFalse(wal.exists())  # fixture db was checkpointed on close
        # A prior run's digest snapshot only records WAL sidecars that exist.
        digests = _input_digests(self.root)
        self.assertNotIn(str(wal), digests)
        # WAL/-shm sidecars are covered once they exist.
        wal.write_bytes(b'wal-frame-bytes')
        shm.write_bytes(b'shm-bytes')
        digests = _input_digests(self.root)
        self.assertIn(str(wal), digests)
        self.assertIn(str(shm), digests)
        import hashlib
        self.assertEqual(digests[str(wal)]['sha256'],
                         hashlib.sha256(b'wal-frame-bytes').hexdigest())
        self.assertEqual(digests[str(shm)]['size'], len(b'shm-bytes'))
        # A WAL change between before/after snapshots is detected.
        before = _input_digests(self.root)
        wal.write_bytes(b'wal-frame-bytes-changed')
        self.assertFalse(_input_unchanged(before, self.root))

    def test_wal_write_mid_run_is_detected_without_main_db_change(self):
        import hashlib
        from watchdog.cli import run_watchdog
        db_path = self.root / 'private/trading_journal.sqlite3'
        self.assertFalse(Path(str(db_path) + '-wal').exists())
        main_sha_before = hashlib.sha256(db_path.read_bytes()).hexdigest()
        original = self.adapters()['broker']
        held = {}
        def wal_writing_broker():
            snapshot = original()
            conn = sqlite3.connect(db_path)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute(
                'INSERT INTO ledger_entries (stream, sequence, record_json, record_sha256, appended_at) '
                'VALUES (?,?,?,?,?)',
                ('private/order_intents.jsonl', 999, json.dumps({'noise': True}),
                 'deadbeef', '2026-10-07T14:01:00+00:00'))
            conn.commit()
            held['conn'] = conn  # stay open: change lives in -wal, not main db
            return snapshot
        result = run_watchdog('mechanical', self.root, self.output_root,
                              self.adapters(broker=wal_writing_broker), NOW)
        try:
            self.assertFalse(result['input_unchanged'])
            self.assertIn('operational_input_changed_after_run', result['reasons'])
            self.assertEqual(result['all_clear'], False)
            # The main-db digest alone would have missed this mutation.
            self.assertEqual(hashlib.sha256(db_path.read_bytes()).hexdigest(), main_sha_before)
        finally:
            held['conn'].close()


class DailyWorkflowTests(WorkflowCase):
    def adapters(self, broker=None, **overrides):
        return super().adapters(broker or (lambda: broker_snapshot(extra_symbol=None)), **overrides)

    def test_daily_partitions_source_cutoffs_outbox_and_marker(self):
        from watchdog.cli import run_watchdog
        adapters = self.adapters(thesis=self.thesis_adapters())
        result = run_watchdog('daily', self.root, self.output_root, adapters, DAILY_NOW)
        self.assertEqual(result['status'], 'ok')
        report = read_report(self.db)
        for key in ('actual', 'research', 'decisions', 'shadow'):
            self.assertIn(key, report['attribution'])
        # Source cutoffs advanced through the committed thesis rows.
        state = read_source_state(self.db)
        self.assertEqual(set(state.get('ABC', {})), {'sec', 'issuer', 'earnings'})
        # Exactly one daily digest per session date in the outbox (acked rows
        # remain in the outbox with a receipt, so query the table directly).
        import sqlite3
        with sqlite3.connect(self.db) as conn:
            digests = [json.loads(row[0]) for row in conn.execute(
                "SELECT payload FROM alert_outbox WHERE instr(payload, '\"kind\":\"digest\"') > 0")]
        self.assertEqual(len(digests), 1)
        self.assertEqual(digests[0].get('status'), 'complete')
        # Completion marker exists only after report commit, stamped by the
        # trusted `now`, not by broker capture time.
        marker = self.output_root / 'private/watchdog/completions/2026-10-07.json'
        self.assertTrue(marker.exists())
        stamped = json.loads(marker.read_text())
        self.assertEqual(stamped['run_id'], result['run_id'])
        self.assertEqual(stamped['session_date'], '2026-10-07')
        self.assertIn('2026-10-07T20:15', stamped['completed_at'])
        self.assertNotIn('2026-10-07T14:00', stamped['completed_at'])

    def test_completion_marker_only_after_successful_report_commit(self):
        from watchdog.cli import run_watchdog
        def broken_install(db):
            raise ValueError('report_install_failed')
        result = run_watchdog('daily', self.root, self.output_root,
                              self.adapters(thesis=self.thesis_adapters(),
                                            install_reports=broken_install), DAILY_NOW)
        self.assertNotEqual(result['status'], 'ok')
        self.assertFalse((self.output_root / 'private/watchdog/completions/2026-10-07.json').exists())
        # Pending alerts are retained for the bounded next-slot retry.
        self.assertTrue(pending_alerts(self.db))
        # Next eligible slot with repaired reporting: marker written, drained.
        result2 = run_watchdog('daily', self.root, self.output_root,
                               self.adapters(thesis=self.thesis_adapters()), DAILY_NOW)
        self.assertEqual(result2['status'], 'ok')
        self.assertTrue((self.output_root / 'private/watchdog/completions/2026-10-07.json').exists())

    def _outbox_digest_count(self):
        with sqlite3.connect(self.db) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM alert_outbox WHERE instr(payload, '\"kind\":\"digest\"') > 0"
            ).fetchone()[0]

    def test_next_slot_retry_is_reporting_only_with_stable_run_identity(self):
        from watchdog.cli import run_watchdog
        def broken_install(db):
            raise ValueError('report_install_failed')
        result = run_watchdog('daily', self.root, self.output_root,
                              self.adapters(thesis=self.thesis_adapters(),
                                            install_reports=broken_install), DAILY_NOW)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(pending_alerts(self.db))
        source_state_before = read_source_state(self.db)
        report_run_id = read_report(self.db).get('run_id')
        # Next eligible daily slot (close+45) with repaired reporting: the
        # retry must reuse the stable session-date run identity, skip thesis
        # retrieval/recommit, drain pending alerts and install reports.
        later = datetime(2026, 10, 7, 20, 45, tzinfo=UTC)
        result2 = run_watchdog('daily', self.root, self.output_root,
                               self.adapters(thesis=self.thesis_adapters(now=later)), later)
        self.assertEqual(result2['status'], 'ok')
        self.assertEqual(result2['run_id'], result['run_id'])
        self.assertEqual(result2['run_id'], report_run_id)
        self.assertFalse(result2.get('committed_now', True))
        self.assertTrue(result2.get('reporting_retry'))
        # Thesis retrieval/recommit skipped: source state untouched by the retry.
        self.assertEqual(read_source_state(self.db), source_state_before)
        self.assertEqual(read_report(self.db).get('run_id'), report_run_id)
        # Reports installed, alerts drained, marker written with the retry `now`.
        self.assertTrue((self.output_root / 'private/watchdog/latest.json').exists())
        self.assertEqual(pending_alerts(self.db), [])
        self.assertTrue(self.receipts)
        marker = json.loads((self.output_root / 'private/watchdog/completions/2026-10-07.json').read_text())
        self.assertIn('2026-10-07T20:45', marker['completed_at'])
        # No second daily digest for the same session date.
        self.assertEqual(self._outbox_digest_count(), 1)

    def test_second_slot_after_successful_daily_is_still_reporting_only(self):
        from watchdog.cli import run_watchdog
        first = run_watchdog('daily', self.root, self.output_root,
                             self.adapters(thesis=self.thesis_adapters()), DAILY_NOW)
        self.assertEqual(first['status'], 'ok')
        self.assertEqual(self._outbox_digest_count(), 1)
        source_state_before = read_source_state(self.db)
        later = datetime(2026, 10, 7, 20, 45, tzinfo=UTC)
        second = run_watchdog('daily', self.root, self.output_root, self.adapters(), later)
        self.assertEqual(second['status'], 'ok')
        self.assertEqual(second['run_id'], first['run_id'])
        self.assertFalse(second.get('committed_now', True))
        self.assertTrue(second.get('reporting_retry'))
        self.assertEqual(read_source_state(self.db), source_state_before)
        self.assertEqual(self._outbox_digest_count(), 1)

    def test_daily_without_thesis_worker_is_typed_blocker_not_crash(self):
        from watchdog.cli import run_watchdog
        result = run_watchdog('daily', self.root, self.output_root, self.adapters(), DAILY_NOW)
        self.assertEqual(result['status'], 'ok')
        self.assertFalse(result['all_clear'])
        self.assertIn('thesis_worker_blocker', result['reasons'])

    def test_daily_outside_eligible_slot_is_silent_no_op(self):
        from watchdog.cli import run_watchdog
        late = datetime(2026, 10, 7, 21, 50, tzinfo=UTC)
        result = run_watchdog('daily', self.root, self.output_root, self.adapters(), late)
        self.assertEqual(result['status'], 'no_op')
        self.assertFalse(self.db.exists())


class PathSafetyTests(WorkflowCase):
    def test_fixture_mode_cannot_choose_operational_output(self):
        from watchdog.cli import run_watchdog
        with self.assertRaises(ValueError):
            run_watchdog('mechanical', self.root, CHECKOUT, self.adapters(), NOW, fixture=True)
        with self.assertRaises(ValueError):
            run_watchdog('mechanical', self.root, CHECKOUT / 'private', self.adapters(), NOW, fixture=True)

    def test_external_root_is_rejected(self):
        from watchdog.cli import run_watchdog
        with self.assertRaises(ValueError):
            run_watchdog('mechanical', Path(tempfile.gettempdir()) / 'not-tradey', self.output_root,
                         self.adapters(), NOW)

    def test_operational_output_overlap_is_rejected(self):
        from watchdog.cli import run_watchdog
        with self.assertRaises(ValueError):
            run_watchdog('mechanical', self.root, self.root / 'private', self.adapters(), NOW)
        with self.assertRaises(ValueError):
            run_watchdog('mechanical', self.root, self.output_root.parent, self.adapters(), NOW)

    def test_symlink_escape_is_rejected(self):
        from watchdog.cli import run_watchdog
        escape = self.artifacts / 'escape-link'
        escape.symlink_to(Path(tempfile.gettempdir()))
        with self.assertRaises(ValueError):
            run_watchdog('mechanical', self.root, escape / 'out', self.adapters(), NOW)

    def test_unknown_cli_action_fails_closed_without_writes(self):
        from watchdog.cli import main
        marker = self.artifacts / 'cli-untouched'
        marker.mkdir()
        before = sorted(p.name for p in marker.iterdir())
        self.assertEqual(main(['explode', '--root', str(self.root),
                               '--output-root', str(self.output_root)]), 2)
        self.assertEqual(sorted(p.name for p in marker.iterdir()), before)
        self.assertFalse((self.output_root / 'private/watchdog').exists())

    def test_cli_fixture_flag_confines_roots(self):
        from watchdog.cli import main
        confined = CHECKOUT / 'test_artifacts/watchdog'
        rc = main(['mechanical', '--fixture', '--root', str(self.root),
                   '--output-root', str(confined / 'cli-should-not-write')])
        self.assertNotEqual(rc, 0)
        self.assertFalse((confined / 'cli-should-not-write' / 'private').exists())


class DeliveryAndLockTests(WorkflowCase):
    def adapters(self, broker=None, **overrides):
        # Pending protection guarantees at least one durable outbox row.
        return super().adapters(broker or (lambda: broker_snapshot(stop_status='canceled')), **overrides)

    def test_ack_only_on_genuine_receipt_ambiguous_stays_pending(self):
        from watchdog.cli import run_watchdog
        run_watchdog('mechanical', self.root, self.output_root,
                     self.adapters(transport=lambda alert, rendered: None), NOW)
        pending = pending_alerts(self.db)
        self.assertTrue(pending)  # ambiguous/no-ack transport keeps rows pending

        def genuine(alert, rendered):
            self.assertTrue(rendered.startswith('Watchdog '))
            return dict(provider='test', message_id='m1', status='delivered',
                        verified_at='2026-10-07T14:06:00+00:00', verification='provider_readback')

        result = run_watchdog('mechanical', self.root, self.output_root,
                              self.adapters(transport=genuine), NOW)
        self.assertEqual(pending_alerts(self.db), [])
        self.assertEqual(result['delivered'], len(pending))
        self.assertEqual(result['pending'], 0)

    def test_equivalent_run_skip_still_drains_outbox(self):
        from watchdog.cli import run_watchdog
        first = run_watchdog('mechanical', self.root, self.output_root,
                             self.adapters(transport=lambda a, r: None), NOW)
        self.assertTrue(pending_alerts(self.db))
        count_before = len(pending_alerts(self.db))
        # Same trusted now: identical run identity/digest, no duplicate alerts,
        # but the outbox is still drained by the delivery wrapper.
        second = run_watchdog('mechanical', self.root, self.output_root, self.adapters(), NOW)
        self.assertEqual(second['run_id'], first['run_id'])
        self.assertEqual(second['committed'], False)
        self.assertEqual(len(self.receipts), count_before)
        self.assertEqual(pending_alerts(self.db), [])

    def test_monitoring_lock_is_isolated_from_trading_lock(self):
        from watchdog.cli import run_watchdog
        lock_dir = self.output_root / 'private/watchdog'
        lock_dir.mkdir(parents=True)
        with (lock_dir / 'monitor.lock').open('w') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = run_watchdog('mechanical', self.root, self.output_root, self.adapters(), NOW)
            self.assertEqual(result['status'], 'skipped')
            self.assertIn('monitoring_lock_busy', result['reasons'])
        # The watchdog never takes the trading writer lock exclusively.
        trading = self.root / 'private/trading_journal.sqlite3.lock'
        with trading.open('rb') as fd:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertFalse(self.db.exists())

    def test_outer_wall_clock_budget_kills_run_before_commit(self):
        from watchdog.cli import run_watchdog
        def slow_broker():
            time.sleep(0.4)
            return broker_snapshot()
        result = run_watchdog('mechanical', self.root, self.output_root,
                              self.adapters(broker=slow_broker), NOW,
                              budgets={'outer': 0.1, 'active': 0.1, 'reserve': 0.0})
        self.assertEqual(result['status'], 'budget_exceeded')
        self.assertFalse(self.db.exists())
        self.assertIn('outer_deadline_exceeded', result['reasons'])

    def test_run_budget_constants(self):
        from watchdog.cli import run_budgets
        self.assertEqual(run_budgets('mechanical'), {'outer': 120, 'active': 120, 'reserve': 0})
        self.assertEqual(run_budgets('daily'), {'outer': 900, 'active': 840, 'reserve': 60})
        with self.assertRaises(ValueError):
            run_budgets('weekly')

    def test_digest_identity_conflict_is_typed(self):
        from watchdog.cli import run_watchdog
        run_watchdog('mechanical', self.root, self.output_root,
                     self.adapters(broker=lambda: broker_snapshot(stop_status='open')), NOW)
        # A same-identity content change is a typed failed result with the
        # store reason, not a raw ValueError escaping the run wrapper.
        result = run_watchdog('mechanical', self.root, self.output_root,
                              self.adapters(broker=lambda: broker_snapshot(stop_status='canceled')), NOW)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['run_id'], 'mechanical:20261007T140500Z')
        self.assertIn('run_identity_conflict', result['reasons'])
        self.assertFalse(result['committed'])
        self.assertFalse(result['all_clear'])

    def test_smoke_sends_nothing_and_publishes_nothing(self):
        from watchdog.cli import run_watchdog
        sent = []
        result = run_watchdog('mechanical', self.root, self.output_root,
                              self.adapters(transport=lambda a, r: sent.append(a)), NOW, smoke=True)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(sent, [])
        self.assertFalse((self.output_root / 'private/watchdog/latest.json').exists())
        self.assertFalse((self.output_root / 'public').exists())


class SmokeDryRunTests(WorkflowCase):
    def adapters(self, broker=None, **overrides):
        # Pending protection guarantees the old smoke path would have written
        # condition state and outbox rows.
        return super().adapters(broker or (lambda: broker_snapshot(stop_status='canceled')), **overrides)

    def test_smoke_is_dry_run_commit_no_condition_state_or_outbox(self):
        import sqlite3
        from watchdog.cli import run_watchdog
        result = run_watchdog('mechanical', self.root, self.output_root, self.adapters(), NOW, smoke=True)
        self.assertEqual(result['status'], 'ok')
        # Run evidence is committed, but the real-alert state machine is not.
        self.assertTrue(self.db.exists())
        self.assertEqual(read_report(self.db).get('mode'), 'mechanical')
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM alert_outbox').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM condition_state').fetchone()[0], 0)
        self.assertEqual(pending_alerts(self.db), [])

    def test_smoke_cannot_suppress_a_real_alert(self):
        from watchdog.cli import run_watchdog
        # Smoke probes the same condition first: it must not arm the 24h
        # quiet window that would silence the real alert for that condition.
        run_watchdog('mechanical', self.root, self.output_root, self.adapters(), NOW, smoke=True)
        # Mechanical runs are eligible at :05 only; one hour later the same
        # condition is unchanged and still inside the 24h quiet window, so an
        # old smoke run that had armed condition state would silence it.
        later = datetime(2026, 10, 7, 15, 5, tzinfo=UTC)
        result = run_watchdog('mechanical', self.root, self.output_root, self.adapters(), later)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(pending_alerts(self.db), [])
        self.assertTrue(self.receipts)

    def test_smoke_output_may_nest_under_test_artifacts_watchdog_only(self):
        import shutil
        from watchdog.cli import run_watchdog
        probe_root = CHECKOUT / 'test_artifacts/watchdog/smoke-overlap-probe'
        shutil.rmtree(probe_root, ignore_errors=True)
        try:
            root = build_operational_root(probe_root)
            output = root / 'smoke-out'
            result = run_watchdog('mechanical', root, output, self.adapters(), NOW, smoke=True)
            self.assertEqual(result['status'], 'ok')
            # The documented test_artifacts/watchdog exception is smoke-only:
            # a real run may never nest output inside the operational root.
            with self.assertRaises(ValueError):
                run_watchdog('mechanical', root, output, self.adapters(), NOW)
        finally:
            shutil.rmtree(probe_root, ignore_errors=True)


class DailySeamTests(DailyWorkflowTests):
    def test_captures_observation_completion_and_bounds_worker_checked_through(self):
        from watchdog.cli import run_watchdog
        # A worker stamping its own inspection wall-time is pinned to
        # checked_through <= the supplied trusted now: a whole run must never
        # abort with source_cutoff_future, and a worker claiming a future
        # inspection is a typed per-source gap, never a cutoff.
        def slow_broker():
            time.sleep(0.2)
            return broker_snapshot(extra_symbol=None)
        result = run_watchdog('daily', self.root, self.output_root,
                              self.adapters(broker=slow_broker,
                                            thesis=self.thesis_adapters(checked_offset_seconds=3600)),
                              DAILY_NOW)
        self.assertEqual(result['status'], 'ok')
        report = read_report(self.db)
        row = next(t for t in report['thesis'] if t['position_id'] == 'parent')
        # checked_through an hour past completion is rejected per source.
        self.assertTrue(all(v['status'] == 'coverage_incomplete' for v in row['coverage'].values()))
        # Coverage is stamped at observation completion, not run start.
        self.assertGreater(report['coverage']['captured_at'], '2026-10-07T20:15:00+00:00')
        state = read_source_state(self.db)
        self.assertEqual(state.get('ABC', {}), {})

    def test_daily_retry_detection_is_mode_aware(self):
        from watchdog.cli import run_watchdog
        from watchdog.store import commit_observation
        from watchdog.types import RunObservation
        first = run_watchdog('daily', self.root, self.output_root,
                             self.adapters(thesis=self.thesis_adapters()), DAILY_NOW)
        self.assertEqual(first['status'], 'ok')
        # A later inter-mode (mechanical) run lands on the same monitoring db
        # (clock override / cron lag scenario). The daily retry check must key
        # on the latest daily run, not the absolute latest run of any mode.
        commit_observation(self.db, RunObservation(
            run_id='mechanical:20261007T203500Z', session_date='2026-10-07', mode='mechanical',
            positions=[], portfolio={}, attribution={}, thesis=[],
            coverage={'status': 'unknown', 'captured_at': '2026-10-07T20:35:00+00:00'}, reasons=[]))
        later = datetime(2026, 10, 7, 20, 45, tzinfo=UTC)
        second = run_watchdog('daily', self.root, self.output_root, self.adapters(), later)
        self.assertEqual(second['status'], 'ok')
        self.assertTrue(second.get('reporting_retry'))
        self.assertFalse(second.get('committed_now', True))
        self.assertEqual(second['run_id'], first['run_id'])
        self.assertEqual(self._outbox_digest_count(), 1)

    def test_daily_wires_candidate_baselines_for_exactly_linked_positions(self):
        from watchdog.cli import run_watchdog
        result = run_watchdog('daily', self.root, self.output_root,
                              self.adapters(thesis=self.thesis_adapters()), DAILY_NOW)
        self.assertEqual(result['status'], 'ok')
        report = read_report(self.db)
        row = next(t for t in report['thesis'] if t['position_id'] == 'parent')
        # The exactly linked candidate's dossier drives the baseline.
        self.assertEqual(row['baseline_status'], 'complete')
        self.assertEqual(row['status'], 'no_material_change_observed')
        import sqlite3
        with sqlite3.connect(self.db) as conn:
            supplied = conn.execute(
                "SELECT payload FROM thesis_versions WHERE kind='supplied'").fetchall()
        self.assertTrue(supplied)

    def test_candidate_string_catalyst_without_event_date_is_typed_baseline_gap(self):
        import shutil
        from watchdog.cli import run_watchdog
        # Lineage projects the candidate catalyst verbatim; a plain-string
        # catalyst carries no event_date the baseline can date, so the lane
        # records an explicit baseline_incomplete gap, never a guessed date.
        base = self.artifacts / 'string-catalyst'
        base.mkdir()
        root = build_operational_root(base, candidate_overrides={'catalyst': 'earnings'})
        output = self.artifacts / 'string-catalyst-out'
        output.mkdir()
        db = output / 'private/watchdog/monitoring.sqlite3'
        try:
            result = run_watchdog('daily', root, output,
                                  self.adapters(thesis=self.thesis_adapters()), DAILY_NOW)
            self.assertEqual(result['status'], 'ok')
            report = read_report(db)
            row = next(t for t in report['thesis'] if t['position_id'] == 'parent')
            self.assertEqual(row['baseline_status'], 'baseline_incomplete')
            self.assertEqual(row['status'], 'baseline_incomplete')
            self.assertFalse(result['all_clear'])
        finally:
            shutil.rmtree(base, ignore_errors=True)
            shutil.rmtree(output, ignore_errors=True)


class TransportBucketTests(WorkflowCase):
    def adapters(self, broker=None, **overrides):
        return super().adapters(broker or (lambda: broker_snapshot(stop_status='canceled')), **overrides)

    def test_transport_exception_is_a_distinct_typed_bucket(self):
        from watchdog.cli import run_watchdog
        def exploding(alert, rendered):
            raise RuntimeError('transport socket down')
        result = run_watchdog('mechanical', self.root, self.output_root,
                              self.adapters(transport=exploding), NOW)
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(pending_alerts(self.db))
        self.assertEqual(result['delivery']['reasons'], ['transport_exception_delivery_pending'])
        self.assertEqual(result['delivery']['delivered'], 0)

    def test_no_readback_transport_stays_ambiguous(self):
        from watchdog.cli import run_watchdog
        result = run_watchdog('mechanical', self.root, self.output_root,
                              self.adapters(transport=lambda a, r: None), NOW)
        self.assertTrue(pending_alerts(self.db))
        self.assertEqual(result['delivery']['reasons'], ['ambiguous_delivery_possible_duplicates'])
