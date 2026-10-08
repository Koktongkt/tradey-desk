from contextlib import closing
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from watchdog.types import RunObservation


def observation(run='r1', at='2026-10-07T20:30:00Z', status='unprotected', mode='mechanical'):
    return RunObservation(run, at[:10], mode,
        [dict(position_id='p1', symbol='ABC', ownership_status='verified',
              protection_status=status, quantity_status='consistent', horizon_status='active')],
        dict(strategy=dict(at=at, scope='actual_managed_strategy', initial_capital='10000',
                           marked_equity='10020', coverage=dict(status='complete')),
             account=dict(at=at, scope='full_account_secondary', equity='50000', cash='40000')),
        {}, [], dict(status='complete', captured_at=at), [])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'test_artifacts/private/watchdog/monitoring.sqlite3'

    def test_transactional_idempotent_snapshot(self):
        self.assertIsNotNone(importlib.util.find_spec('watchdog.store'), 'monitoring store missing')
        from watchdog.store import commit_observation, read_report
        first = commit_observation(self.db, observation())
        self.assertEqual(1, len(first))
        self.assertEqual(first, commit_observation(self.db, observation()))
        self.assertEqual('r1', read_report(self.db)['run_id'])
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertEqual(1, conn.execute('PRAGMA user_version').fetchone()[0])
            self.assertEqual(1, conn.execute('SELECT count(*) FROM runs').fetchone()[0])
            self.assertEqual(9, conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0])
        bad = observation('bad')
        bad.positions.append(dict(position_id='p1'))
        with self.assertRaises(ValueError):
            commit_observation(self.db, bad)
        self.assertEqual('r1', read_report(self.db)['run_id'])

    def test_cooldown_escalation_recovery_and_digest(self):
        from watchdog.store import commit_observation
        partial = observation(status='partial')
        self.assertEqual(1, len(commit_observation(self.db, partial)))
        self.assertEqual(1, len(commit_observation(self.db, observation('r2', '2026-10-07T21:30:00Z', 'partial'))))
        rows = commit_observation(self.db, observation('r3', '2026-10-07T22:30:00Z'))
        self.assertEqual(2, len(rows))
        self.assertEqual('critical', rows[-1]['severity'])
        rows = commit_observation(self.db, observation('r4', '2026-10-07T23:30:00Z', 'covered'))
        self.assertEqual('recovery', rows[-1]['kind'])
        self.assertEqual(3, len(rows))
        self.assertEqual(4, len(commit_observation(self.db, observation('r5', '2026-10-08T00:30:00Z'))))
        daily = observation('d1', '2026-10-08T01:00:00Z', mode='daily')
        rows = commit_observation(self.db, daily)
        daily.run_id = 'd2'
        self.assertEqual(rows, commit_observation(self.db, daily))
        self.assertEqual(1, sum(r['kind'] == 'digest' for r in rows))

    def test_pending_delivery_requires_receipt_and_survives_rollback(self):
        from watchdog import store
        self.assertTrue(hasattr(store, 'ack_alert'), 'receipt acknowledgment missing')
        from watchdog.store import commit_observation, pending_alerts, ack_alert, read_report
        rows = commit_observation(self.db, observation())
        for receipt in ({}, {'delivered': True}, {'status': 'ambiguous', 'message_id': 'm1'}):
            with self.assertRaises(ValueError):
                ack_alert(self.db, rows[0]['key'], receipt)
            self.assertEqual(rows, pending_alerts(self.db))
        # Actual SQLite trigger aborts after runs/positions inserted: entire run rolls back.
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("CREATE TRIGGER crash BEFORE INSERT ON portfolio_snapshots BEGIN SELECT RAISE(ABORT, 'crash'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            commit_observation(self.db, observation('r2'))
        self.assertEqual('r1', read_report(self.db)['run_id'])
        self.assertEqual(rows, pending_alerts(self.db))
        ack_alert(self.db, rows[0]['key'], dict(provider='test_transport', message_id='m1',
            status='delivered', verified_at='2026-10-07T21:00:00Z', verification='provider_readback'))
        self.assertEqual([], pending_alerts(self.db))

    def test_overlapping_duplicate_and_stale_runs(self):
        from concurrent.futures import ThreadPoolExecutor
        from watchdog.store import commit_observation, pending_alerts, read_report
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: commit_observation(self.db, observation()), range(4)))
        self.assertTrue(all(r == results[0] for r in results))
        commit_observation(self.db, observation('new', '2026-10-08T20:30:00Z', 'covered'))
        count = len(pending_alerts(self.db))
        commit_observation(self.db, observation('old', '2026-10-06T20:30:00Z'))
        self.assertEqual(count, len(pending_alerts(self.db)))
        self.assertEqual('new', read_report(self.db)['run_id'])
        with self.assertRaises(ValueError):
            commit_observation(self.db, observation(status='covered'))

    def test_evidence_versions_cutoffs_compact_and_monotonic(self):
        from watchdog.store import commit_observation, read_report
        o = observation()
        baseline = dict(version='v1', summary='supplied', breakers=[dict(id='b', metric='sales', operator='<', threshold='5')],
                        proposed_enrichments=[dict(version='p1', approved=True, breakers=[])])
        event = dict(fingerprint='event1', baseline_version='v1', fact='compact sourced fact',
                     urls=['https://issuer.test/full?reference=1'], published_at=o.coverage['captured_at'],
                     raw_article='NEVERSTORE', prompt='NEVERSTORE')
        o.thesis = [dict(position_id='p1', symbol='ABC', baseline_version='v1', baseline=baseline,
                        status='review_required', coverage={'issuer': {'status': 'complete'}},
                        source_state={'issuer': {'cutoff': o.coverage['captured_at']}}, events=[event])]
        commit_observation(self.db, o)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertEqual(1, conn.execute('SELECT count(*) FROM evidence_events').fetchone()[0])
            self.assertEqual(2, conn.execute('SELECT count(*) FROM thesis_versions').fetchone()[0])
            proposed = conn.execute("SELECT payload FROM thesis_versions WHERE kind='proposal'").fetchone()[0]
            self.assertIn('"approved":false', proposed)
        o.run_id = 'r2'
        o.coverage['captured_at'] = '2026-10-08T20:30:00Z'
        o.thesis[0]['coverage']['issuer']['status'] = 'coverage_incomplete'
        o.thesis[0]['source_state']['issuer']['cutoff'] = o.coverage['captured_at']
        commit_observation(self.db, o)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertEqual(1, conn.execute('SELECT count(*) FROM evidence_events').fetchone()[0])
            self.assertEqual('2026-10-07T20:30:00Z', conn.execute('SELECT cutoff FROM source_state').fetchone()[0])
        import json
        text = json.dumps(read_report(self.db))
        self.assertNotIn('NEVERSTORE', text)
        self.assertIn('https://issuer.test/full?reference=1', text)
        o.run_id = 'r3'
        o.thesis[0]['baseline']['summary'] = 'silently changed'
        with self.assertRaises(ValueError):
            commit_observation(self.db, o)

    def test_missing_read_and_schema_path_rejection_no_side_effects(self):
        from watchdog.store import commit_observation, read_report
        self.assertEqual({}, read_report(self.db))
        self.assertFalse(self.db.parent.exists())
        for name in ('trading_journal.sqlite3', 'monitoring.db'):
            with self.assertRaises(ValueError):
                commit_observation(self.db.with_name(name), observation())
        self.db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('PRAGMA user_version=77')
        before = self.db.read_bytes()
        with self.assertRaises(ValueError):
            commit_observation(self.db, observation())
        self.assertEqual(before, self.db.read_bytes())

    def test_private_provenance_and_unapproved_snapshot_retained(self):
        from watchdog.store import commit_observation, read_report
        o = observation()
        o.portfolio['strategy']['mark_provenance'] = {'p1':'https://verified.test/mark?date=2026-10-07'}
        o.thesis = [dict(position_id='p1', symbol='ABC', baseline_version='v', baseline={
            'version':'v', 'proposed_enrichments':[{'version':'proposal', 'approved':True, 'breakers':[]} ]})]
        commit_observation(self.db, o)
        report = read_report(self.db)
        self.assertEqual(o.portfolio['strategy']['mark_provenance'], report['portfolio']['strategy']['mark_provenance'])
        self.assertFalse(report['thesis'][0]['baseline']['proposed_enrichments'][0]['approved'])
        self.assertTrue(o.thesis[0]['baseline']['proposed_enrichments'][0]['approved'])

    def test_new_material_events_alert_even_same_thesis_status(self):
        from watchdog.store import commit_observation
        o = observation(status='covered')
        def thesis(fp):
            return dict(position_id='p1', symbol='ABC', baseline_version='v1', status='review_required',
                events=[dict(fingerprint=fp, baseline_version='v1', effect='weakens', severity='high', fact='event fact')])
        o.thesis = [thesis('e1')]
        first = commit_observation(self.db, o)
        self.assertEqual(2, len(first))  # thesis status + underlying evidence alert
        o.run_id = 'r2'
        self.assertEqual(first, commit_observation(self.db, o))
        o.run_id = 'r3'
        o.thesis = [thesis('e2')]
        rows = commit_observation(self.db, o)
        self.assertEqual(3, len(rows))
        self.assertEqual('evidence', rows[-1]['kind'])

    def test_thesis_source_coverage_deterioration_is_independent(self):
        from watchdog.store import commit_observation
        o = observation(status='covered')
        o.thesis = [dict(position_id='p1', symbol='ABC', status='baseline_incomplete', coverage_status='complete')]
        first = commit_observation(self.db, o)
        o.run_id = 'r2'
        o.thesis[0]['coverage_status'] = 'coverage_incomplete'
        rows = commit_observation(self.db, o)
        self.assertEqual(len(first)+1, len(rows))
        self.assertEqual('coverage', rows[-1]['kind'])

    def test_history_and_settings_read_without_mutation(self):
        from watchdog import store
        self.assertTrue(hasattr(store, 'read_portfolio_history'), 'accounting history reader missing')
        o = observation()
        store.commit_observation(self.db, o)
        store.commit_observation(self.db, observation('r2', '2026-10-08T20:30:00Z'))
        before = self.db.read_bytes()
        history = store.read_portfolio_history(self.db)
        self.assertEqual(2, len(history))
        self.assertEqual(o.portfolio, history[0])
        self.assertEqual(before, self.db.read_bytes())
        with store._connection(self.db) as c:
            self.assertEqual(1, c.execute('PRAGMA foreign_keys').fetchone()[0])
            self.assertEqual(2, c.execute('PRAGMA synchronous').fetchone()[0])

    def test_schema_identity_and_hardlink_rejected(self):
        from watchdog.store import commit_observation
        self.db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('CREATE TABLE operational_data(secret TEXT)')
            c.execute('PRAGMA user_version=1')
        with self.assertRaisesRegex(ValueError, 'schema'):
            commit_observation(self.db, observation())
        self.db.unlink()
        import os
        other = self.db.parent/'operational.sqlite3'
        with closing(sqlite3.connect(other)) as c, c:
            c.execute('CREATE TABLE private_data(secret TEXT)')
        os.link(other, self.db)
        with self.assertRaisesRegex(ValueError, 'hardlink'):
            commit_observation(self.db, observation())

    def test_ack_missing_store_does_not_create_database(self):
        from watchdog.store import ack_alert
        with self.assertRaises(ValueError):
            ack_alert(self.db, 'missing', dict(provider='test', message_id='m', status='delivered',
                verification='provider_readback', verified_at='2026-10-07T21:00:00Z'))
        self.assertFalse(self.db.parent.exists())

    def test_real_mechanical_discrepancy_reason_produces_condition(self):
        from watchdog.store import commit_observation
        o = observation(status='covered')
        o.positions[0]['reasons'] = ['unexpected_exit']
        rows = commit_observation(self.db, o)
        self.assertEqual(1, len(rows))
        self.assertEqual('quantity', rows[0]['kind'])
        self.assertEqual('discrepancy', rows[0]['status'])

    def test_microsecond_and_offset_ordering_never_regresses_snapshot(self):
        from watchdog.store import commit_observation, read_report, pending_alerts
        commit_observation(self.db, observation('r1', '2026-10-07T20:30:00.000002Z'))
        commit_observation(self.db, observation('new', '2026-10-07T16:30:00.000003-04:00', 'covered'))
        count = len(pending_alerts(self.db))
        commit_observation(self.db, observation('old', '2026-10-07T20:30:00.000001Z'))
        self.assertEqual('new', read_report(self.db)['run_id'])
        self.assertEqual(count, len(pending_alerts(self.db)))

    def test_private_store_permissions_and_nonnull_identity(self):
        from watchdog.store import commit_observation, _connection
        commit_observation(self.db, observation())
        with self.subTest('file_permission'):
            self.assertEqual(0o600, self.db.stat().st_mode & 0o777)
        with self.subTest('directory_permission'):
            self.assertEqual(0o700, self.db.parent.stat().st_mode & 0o777)
        with _connection(self.db, True) as c:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO position_observations VALUES (NULL,NULL,'{}')")
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO position_observations VALUES ('missing','p2','{}')")

    def test_attribution_categories_and_versioned_accounting_inputs(self):
        from watchdog.store import commit_observation, read_report
        o = observation()
        o.attribution = dict(actual={'realized_pnl':'10'}, research=[{'symbol':'ABC','forward_return':'0.1'}],
            decisions=[{'decision_id':'d1','state':'blocked'}], shadow=[{'symbol':'XYZ','return_5s_pct':'1.2'}])
        o.portfolio['strategy_baseline'] = dict(version='allocation-v1', at=o.coverage['captured_at'], initial_capital='10000',
            provenance='documented allocation', opening_positions=[], average_price_precision={
                'exact-order': {'quantum':'0.00000001', 'rounding':'ROUND_HALF_EVEN', 'provenance':'verified precision contract'}})
        commit_observation(self.db, o)
        report = read_report(self.db)
        self.assertEqual(o.attribution, report['attribution'])
        self.assertEqual(o.portfolio['strategy_baseline'], report['portfolio']['strategy_baseline'])
        o.run_id = 'r2'
        o.portfolio['strategy_baseline']['initial_capital'] = '20000'
        with self.assertRaisesRegex(ValueError, 'version_conflict'):
            commit_observation(self.db, o)

    def test_same_table_names_wrong_schema_rejected(self):
        from watchdog.store import commit_observation, SCHEMA
        self.db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.db)) as c, c:
            for statement in SCHEMA.split(';'):
                if statement.strip():
                    name = statement.strip().split()[2].split('(')[0]
                    c.execute('CREATE TABLE ' + name + '(wrong TEXT)')
            c.execute('PRAGMA user_version=1')
        before = self.db.read_bytes()
        with self.assertRaisesRegex(ValueError, 'schema'):
            commit_observation(self.db, observation())
        self.assertEqual(before, self.db.read_bytes())

    def test_reader_sees_only_committed_coherent_report(self):
        from watchdog.store import commit_observation, read_report, _connection
        import json
        commit_observation(self.db, observation())
        with _connection(self.db, True) as c:
            new = read_report(self.db)
            new['portfolio']['strategy']['marked_equity'] = '99999'
            c.execute('UPDATE runs SET payload=? WHERE run_id=?', (json.dumps(new), 'r1'))
            self.assertEqual('10020', read_report(self.db)['portfolio']['strategy']['marked_equity'])
        self.assertEqual('99999', read_report(self.db)['portfolio']['strategy']['marked_equity'])

    def test_process_crash_rolls_back_uncommitted_run(self):
        from watchdog.store import commit_observation, read_report, pending_alerts
        import subprocess
        import sys
        commit_observation(self.db, observation())
        before = pending_alerts(self.db)
        script = """import os, sys
from watchdog.store import _connection
with _connection(sys.argv[1], True) as c:
 c.execute("INSERT INTO runs VALUES ('crash','2026-10-08T20:30:00Z','2026-10-08','mechanical','x','{}')")
 os._exit(23)
"""
        result = subprocess.run([sys.executable, '-c', script, str(self.db)], capture_output=True)
        self.assertEqual(23, result.returncode, result.stderr)
        self.assertEqual('r1', read_report(self.db)['run_id'])
        self.assertEqual(before, pending_alerts(self.db))
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual('ok', conn.execute('PRAGMA integrity_check').fetchone()[0])
            self.assertEqual(1, conn.execute('SELECT count(*) FROM runs').fetchone()[0])

    def test_unchanged_condition_reminder_after_24_hours(self):
        from watchdog.store import commit_observation
        commit_observation(self.db, observation())
        self.assertEqual(1, len(commit_observation(self.db, observation('early', '2026-10-08T20:29:59Z'))))
        self.assertEqual(2, len(commit_observation(self.db, observation('due', '2026-10-08T20:30:00Z'))))
