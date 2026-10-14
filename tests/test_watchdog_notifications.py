"""Offline notification policy regressions; never open the live monitoring DB."""
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from watchdog import store
from watchdog.cli import _deliver
from watchdog.types import RunObservation


def observation(run='mechanical:1', at='2026-10-07T14:00:00Z', mode='mechanical', **position):
    row = dict(position_id='p1', symbol='ABC', remaining_quantity='2',
               ownership_status='verified', quantity_status='consistent',
               protection_status='covered', protection_coverage_quantity='2', horizon_status='active', reasons=[])
    row.update(position)
    return RunObservation(run, at[:10], mode, [row], {}, {}, [],
                          dict(status='incomplete', captured_at=at), ['thesis_worker_blocker'])


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'test_artifacts/private/watchdog/monitoring.sqlite3'

    def apply(self):
        self.assertTrue(hasattr(store, 'apply_notification_policy'), 'explicit notification activation missing')
        return store.apply_notification_policy(self.db)

    def test_current_critical_survives_backlog_switch_without_receipt_replay(self):
        store.commit_observation(self.db, observation(protection_status='unprotected'))
        self.apply()
        sent = []
        result = _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(1, len(sent), 'current open missing protection must survive backlog suppression')
        self.assertIn('protection', sent[0].lower())
        self.assertEqual(1, result['emitted'])
        self.assertEqual(0, result['delivered'])
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(1, len(sent), 'receiptless emission is not an outbox replay trigger')
        self.assertTrue(store.pending_alerts(self.db))

    def test_malformed_quantity_never_silences_a_current_safety_gap(self):
        self.apply()
        store.commit_observation(self.db, observation(remaining_quantity='private SECRET', protection_status='covered'))
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(1, len(sent))
        self.assertIn('could not be verified', sent[0])
        self.assertNotIn('SECRET', sent[0])

    def test_current_quantity_mismatch_and_open_horizon_notify_but_closed_do_not(self):
        self.apply()
        store.commit_observation(self.db, observation(quantity_status='discrepancy', horizon_status='horizon_expired'))
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(2, len(sent))
        self.assertTrue(any('quantity' in text.lower() for text in sent))
        self.assertTrue(any('overdue' in text.lower() for text in sent))
        store.commit_observation(self.db, observation('mechanical:2', '2026-10-07T15:00:00Z', remaining_quantity='0',
                                                    quantity_status='discrepancy', horizon_status='horizon_expired'))
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(2, len(sent))

    def test_daily_summary_once_groups_gaps_and_withholds_unverified_performance(self):
        self.apply()
        current = observation('daily:2026-10-07', mode='daily')
        current.thesis = [dict(position_id='p1', symbol='ABC', status='baseline_incomplete', coverage_status='coverage_incomplete')]
        current.portfolio = dict(strategy=dict(marked_equity='SECRET_PERFORMANCE', coverage=dict(status='incomplete')))
        store.commit_observation(self.db, current)
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(1, len(sent), 'one daily summary instead of individual source/setup/digest messages')
        self.assertIn('ABC', sent[0])
        self.assertIn('covered', sent[0])
        self.assertIn('thesis', sent[0].lower())
        self.assertIn('accounting', sent[0].lower())
        self.assertNotIn('SECRET_PERFORMANCE', sent[0])
        self.assertNotIn('digest', sent[0])
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(1, len(sent))

    def test_verified_material_event_not_generic_review_or_unclear_is_immediate(self):
        self.apply()
        current = observation()
        event = dict(fingerprint='f1', baseline_version='v1', criterion_id='c1', effect='unclear', severity='critical',
                     confidence='high', primary=True, kind='fundamental', fact='PRIVATE FACT', urls=['https://private.test/SECRET'])
        current.thesis = [dict(position_id='p1', symbol='ABC', baseline_version='v1', status='review_required', events=[event])]
        store.commit_observation(self.db, current)
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual([], sent)
        current.run_id = 'mechanical:2'
        current.coverage['captured_at'] = '2026-10-07T15:00:00Z'
        event.update(fingerprint='f2', effect='weakens')
        store.commit_observation(self.db, current)
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(1, len(sent))
        self.assertIn('thesis', sent[0].lower())
        self.assertNotIn('PRIVATE', sent[0])
        self.assertNotIn('private.test', sent[0])

    def test_reminder_is_bounded_changes_and_reopen_are_prompt_without_recovery_spam(self):
        self.apply()
        sent = []
        def run(identity, at, **position):
            store.commit_observation(self.db, observation(identity, at, **position))
            _deliver(self.db, lambda alert, text: sent.append(text))
        run('mechanical:1', '2026-10-07T14:00:00Z', protection_status='partial', protection_coverage_quantity='1')
        self.assertEqual(1, len(sent))
        run('mechanical:2', '2026-10-08T13:59:59Z', protection_status='partial', protection_coverage_quantity='1')
        self.assertEqual(1, len(sent))
        run('mechanical:3', '2026-10-08T14:00:00Z', protection_status='partial', protection_coverage_quantity='1')
        self.assertEqual(2, len(sent))
        run('mechanical:4', '2026-10-08T14:05:00Z', protection_status='unprotected', protection_coverage_quantity='0')
        self.assertEqual(3, len(sent))
        run('mechanical:5', '2026-10-08T14:10:00Z', remaining_quantity='0', protection_status='not_required', protection_coverage_quantity='0')
        self.assertEqual(3, len(sent))
        run('mechanical:6', '2026-10-08T14:15:00Z', protection_status='unprotected', protection_coverage_quantity='0')
        self.assertEqual(4, len(sent))

    def test_failed_transport_retries_without_marking_emitted_or_delivered(self):
        self.apply()
        store.commit_observation(self.db, observation(protection_status='unprotected'))
        def fail(alert, text):
            raise RuntimeError('private SECRET failure')
        result = _deliver(self.db, fail)
        self.assertEqual(0, result['emitted'])
        self.assertIn('notification_transport_failed', result['reasons'])
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(1, conn.execute("SELECT count(*) FROM notification_emissions WHERE state='failed'").fetchone()[0])
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(1, len(sent))
        self.assertTrue(store.pending_alerts(self.db))

    def test_prepared_reservation_survives_crash_without_forged_receipt_or_replay(self):
        self.apply()
        store.commit_observation(self.db, observation(protection_status='unprotected'))
        def crash(alert, text):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            _deliver(self.db, crash)
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual([], sent)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(1, conn.execute("SELECT count(*) FROM notification_emissions WHERE state='prepared'").fetchone()[0])
            self.assertEqual(0, conn.execute('SELECT count(*) FROM alert_outbox WHERE receipt IS NOT NULL').fetchone()[0])

    def test_current_check_failure_is_bounded_and_plain_english_even_without_baseline(self):
        self.apply()
        from watchdog import notifications
        self.assertTrue(hasattr(notifications, 'emit_check_failure'), 'protection-check failure notification path missing')
        sent = []
        transport = lambda alert, text: sent.append(text)
        notifications.emit_check_failure(self.db, transport, '2026-10-07T14:00:00Z', 'broker_adapter_failed')
        notifications.emit_check_failure(self.db, transport, '2026-10-07T14:05:00Z', 'broker_adapter_failed')
        self.assertEqual(1, len(sent))
        self.assertIn('protection', sent[0].lower())
        self.assertIn('could not', sent[0].lower())
        self.assertEqual({}, store.read_report(self.db), 'failure must not manufacture an observation')

    def test_valid_receipt_is_retained_separately_from_emission_and_legacy_outbox(self):
        self.apply()
        store.commit_observation(self.db, observation(protection_status='unprotected'))
        receipt = dict(provider='test', message_id='m1', status='delivered', verification='provider_readback', verified_at='2026-10-07T14:01:00Z')
        result = _deliver(self.db, lambda alert, text: receipt)
        self.assertEqual(1, result['delivered'])
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(1, conn.execute('SELECT count(*) FROM notification_receipts').fetchone()[0])
        self.assertTrue(store.pending_alerts(self.db), 'notification receipt is not a fabricated legacy acknowledgment')

    def test_malformed_state_is_a_protection_gap_not_a_crash(self):
        self.apply()
        current = observation(protection_status={'SECRET': 'state'})
        store.commit_observation(self.db, current)
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(1, len(sent))
        self.assertIn('could not be verified', sent[0])
        self.assertNotIn('SECRET', sent[0])

    def test_migration_respects_monitor_lock_and_rejects_foreign_schema_without_db_write(self):
        import fcntl
        store.commit_observation(self.db, observation())
        before = self.db.read_bytes()
        with (self.db.parent / 'monitor.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'monitoring_lock_busy'):
                self.apply()
        self.assertEqual(before, self.db.read_bytes())
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE foreign_table(secret TEXT)')
        before = self.db.read_bytes()
        with self.assertRaisesRegex(ValueError, 'unsupported_monitoring_schema'):
            self.apply()
        self.assertEqual(before, self.db.read_bytes())

    def test_relay_footer_does_not_offer_historical_pending_replay(self):
        from watchdog.runtime import RelayOutput
        relay = RelayOutput()
        relay({}, 'Current protection needs review.')
        self.assertIn('Delivery unverified', relay.text())
        self.assertNotIn('pending alerts may repeat', relay.text())

    def test_covered_status_with_insufficient_quantity_is_not_quiet(self):
        self.apply()
        store.commit_observation(self.db, observation(protection_coverage_quantity='1'))
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(1, len(sent))

    def test_ownership_evidence_loss_after_verified_observation_is_prompt(self):
        self.apply()
        sent = []
        for run, at, owner in [('mechanical:1', '2026-10-07T14:00:00Z', 'unknown'),
                               ('mechanical:2', '2026-10-07T14:05:00Z', 'verified'),
                               ('mechanical:3', '2026-10-07T14:10:00Z', 'unknown')]:
            store.commit_observation(self.db, observation(run, at, ownership_status=owner))
            _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(2, len(sent), 'renewed evidence loss must not stay quiet after recovery')
        self.assertTrue(all('could not be verified' in text for text in sent))

    def test_incomplete_position_evidence_does_not_reset_check_failure_quiet_window(self):
        from watchdog.notifications import emit_check_failure
        self.apply()
        sent = []
        transport = lambda alert, text: sent.append(text)
        emit_check_failure(self.db, transport, '2026-10-07T14:00:00Z', 'broker_adapter_failed')
        store.commit_observation(self.db, observation('mechanical:2', '2026-10-07T14:05:00Z', ownership_status='unknown'))
        _deliver(self.db, transport)
        before = len(sent)
        emit_check_failure(self.db, transport, '2026-10-07T14:10:00Z', 'broker_adapter_failed')
        self.assertEqual(before, len(sent), 'unverified evidence must not record protection-check recovery')

    def test_unverified_broker_protection_sources_cannot_be_overridden_by_nominal_coverage(self):
        self.apply()
        current = observation()
        current.coverage['sources'] = dict(orders='complete', references='unknown', account='complete')
        store.commit_observation(self.db, current)
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertTrue(any('could not be verified' in text for text in sent))

    def test_empty_managed_snapshot_with_unknown_protection_sources_is_not_recovery(self):
        self.apply()
        current = observation()
        current.positions = []
        current.coverage['sources'] = dict(orders='unknown', references='unknown')
        store.commit_observation(self.db, current)
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(1, len(sent))
        self.assertIn('could not be checked', sent[0])

    def test_accounting_source_gaps_do_not_make_verified_protection_urgent(self):
        self.apply()
        current = observation()
        current.coverage['sources'] = dict(orders='complete', references='complete', account='unknown', activities='unknown')
        store.commit_observation(self.db, current)
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual([], sent)

    def test_unknown_horizon_and_source_gaps_are_daily_only_when_protection_is_verified(self):
        self.apply()
        store.commit_observation(self.db, observation(horizon_status='unknown'))
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual([], sent)

    def test_old_report_retry_does_not_clear_newer_check_failure(self):
        from watchdog.notifications import emit_check_failure
        self.apply()
        store.commit_observation(self.db, observation())
        sent = []
        emit_check_failure(self.db, lambda alert, text: sent.append(text), '2026-10-07T15:00:00Z', 'broker_adapter_failed')
        _deliver(self.db, lambda alert, text: sent.append(text))
        emit_check_failure(self.db, lambda alert, text: sent.append(text), '2026-10-07T15:05:00Z', 'broker_adapter_failed')
        self.assertEqual(1, len(sent))

    def test_malformed_thesis_and_coverage_enums_remain_grouped_gaps(self):
        self.apply()
        current = observation('daily:2026-10-07', mode='daily')
        current.thesis = [dict(position_id='p1', symbol='ABC', status={'SECRET': 'bad'}, coverage_status=['SECRET'])]
        current.coverage['status'] = {'SECRET': 'bad'}
        store.commit_observation(self.db, current)
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(1, len(sent))
        self.assertIn('Limitations', sent[0])
        self.assertNotIn('SECRET', sent[0])

    def test_verified_break_cannot_be_silenced_by_low_model_severity(self):
        self.apply()
        current = observation()
        current.thesis = [dict(position_id='p1', symbol='ABC', baseline_version='v1', status='potential_thesis_break', events=[
            dict(fingerprint='break1', baseline_version='v1', criterion_id='b1', effect='potential-break', severity='low',
                 confidence='low', primary=True, kind='fundamental', fact='sourced breach')])]
        store.commit_observation(self.db, current)
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(1, len(sent), 'deterministically verified breaker must survive model severity/confidence labels')
        self.assertIn('potential thesis break', sent[0])

    def test_failed_worsening_notification_retries_on_next_observation_not_only_same_run(self):
        self.apply()
        store.commit_observation(self.db, observation(protection_status='partial', protection_coverage_quantity='1'))
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        store.commit_observation(self.db, observation('mechanical:2', '2026-10-07T14:05:00Z', protection_status='unprotected', protection_coverage_quantity='0'))
        def fail(alert, text):
            raise OSError('transport unavailable')
        _deliver(self.db, fail)
        store.commit_observation(self.db, observation('mechanical:3', '2026-10-07T14:10:00Z', protection_status='unprotected', protection_coverage_quantity='0'))
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual(2, len(sent), 'failed escalation is not a successful notification quiet window')

    def test_activation_preserves_pending_audit_but_does_not_replay_closed_horizon(self):
        store.commit_observation(self.db, observation(horizon_status='horizon_expired', remaining_quantity='0', protection_status='not_required'))
        before = store.pending_alerts(self.db)
        self.assertTrue(before)
        self.apply()
        self.apply()  # idempotent switch; never resets suppression
        sent = []
        _deliver(self.db, lambda alert, text: sent.append(text))
        self.assertEqual([], sent)
        self.assertEqual(before, store.pending_alerts(self.db))
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(2, conn.execute('PRAGMA user_version').fetchone()[0])
            self.assertEqual(len(before), conn.execute("SELECT count(*) FROM notification_emissions WHERE state='suppressed' AND condition_key='legacy'").fetchone()[0])
            self.assertEqual(0, conn.execute('SELECT count(*) FROM alert_outbox WHERE receipt IS NOT NULL').fetchone()[0])


class NotificationWorkflowTests(unittest.TestCase):
    def test_explicit_apply_cli_is_offline_and_confined(self):
        import contextlib
        import io
        from unittest.mock import patch
        from test_watchdog_workflow import WorkflowCase
        from watchdog.cli import main
        case = WorkflowCase()
        case.setUp()
        self.addCleanup(case.tearDown)
        with patch('watchdog.runtime.live_adapters', side_effect=AssertionError('must not contact broker')), contextlib.redirect_stdout(io.StringIO()):
            result = main(['apply-notification-policy', '--root', str(case.root), '--output-root', str(case.output_root), '--fixture'])
        self.assertEqual(0, result)
        self.assertTrue(store.notification_policy_enabled(case.db))

    def test_cron_success_is_only_the_concise_message_not_install_status_spam(self):
        import contextlib
        import io
        from unittest.mock import patch
        from watchdog.cli import main
        out = io.StringIO()
        with patch('watchdog.runtime.live_adapters') as adapters, patch('watchdog.cli.run_watchdog', return_value={'status': 'ok'}), contextlib.redirect_stdout(out):
            adapters.return_value.__enter__.return_value = {}
            self.assertEqual(0, main(['daily', '--cron']))
        self.assertEqual('', out.getvalue(), 'routine report-installed line must not be emitted')

    def test_daily_reporting_retry_after_intervening_mechanical_is_once(self):
        from test_watchdog_workflow import WorkflowCase, DAILY_NOW, NOW
        from watchdog.cli import run_watchdog
        case = WorkflowCase()
        case.setUp()
        self.addCleanup(case.tearDown)
        store.apply_notification_policy(case.db)
        calls = []
        def fail_install(db):
            raise OSError('report failure')
        first = run_watchdog('daily', case.root, case.output_root,
                             case.adapters(install_reports=fail_install, transport=lambda alert, text: calls.append(text)), DAILY_NOW)
        self.assertEqual('failed', first['status'])
        self.assertEqual([], calls)
        mechanical = NOW.replace(hour=20, minute=16)  # outside mechanical gate; commit directly for inter-mode ordering
        store.commit_observation(case.db, observation('mechanical:later', mechanical.isoformat()))
        for second in (0, 5):
            result = run_watchdog('daily', case.root, case.output_root,
                                 case.adapters(transport=lambda alert, text: calls.append(text)), DAILY_NOW.replace(minute=45, second=second))
            self.assertEqual('ok', result['status'])
        self.assertEqual(1, len(calls))
        self.assertIn('daily summary', calls[0])
        self.assertTrue(store.pending_alerts(case.db))

    def test_operational_read_failure_notifies_that_current_protection_cannot_be_checked(self):
        from test_watchdog_workflow import WorkflowCase, NOW
        from unittest.mock import patch
        from watchdog.cli import run_watchdog
        case = WorkflowCase()
        case.setUp()
        self.addCleanup(case.tearDown)
        store.apply_notification_policy(case.db)
        calls = []
        with patch('watchdog.cli.operational.read_operational', side_effect=OSError('SECRET')):
            result = run_watchdog('mechanical', case.root, case.output_root,
                                 case.adapters(transport=lambda alert, text: calls.append(text)), NOW)
        self.assertEqual('failed', result['status'])
        self.assertEqual(1, len(calls))
        self.assertIn('protection could not be checked', calls[0])

    def test_commit_failure_notifies_without_fabricating_run_or_receipt(self):
        from test_watchdog_workflow import WorkflowCase, NOW
        from unittest.mock import patch
        from watchdog.cli import run_watchdog
        case = WorkflowCase()
        case.setUp()
        self.addCleanup(case.tearDown)
        store.apply_notification_policy(case.db)
        calls = []
        with patch('watchdog.cli.commit_observation', side_effect=ValueError('run_identity_conflict')):
            result = run_watchdog('mechanical', case.root, case.output_root,
                                 case.adapters(transport=lambda alert, text: calls.append(text)), NOW)
        self.assertEqual('failed', result['status'])
        self.assertEqual(1, len(calls))
        self.assertEqual({}, store.read_report(case.db))

    def test_budget_failure_does_not_silence_current_protection_check_failure(self):
        from test_watchdog_workflow import WorkflowCase, NOW
        from watchdog.cli import run_watchdog
        case = WorkflowCase()
        case.setUp()
        self.addCleanup(case.tearDown)
        store.apply_notification_policy(case.db)
        calls = []
        ticks = iter((0, 1000))
        result = run_watchdog('mechanical', case.root, case.output_root,
                             case.adapters(clock=lambda: next(ticks, 1000), transport=lambda alert, text: calls.append(text)), NOW)
        self.assertEqual('budget_exceeded', result['status'])
        self.assertEqual(1, len(calls))
        self.assertIn('protection could not be checked', calls[0])

    def test_real_run_broker_failure_notifies_once_under_policy_without_observation(self):
        from test_watchdog_workflow import WorkflowCase, NOW
        from watchdog.cli import run_watchdog
        case = WorkflowCase()
        case.setUp()
        self.addCleanup(case.tearDown)
        store.apply_notification_policy(case.db)
        calls = []
        def broken():
            raise OSError('PRIVATE SECRET')
        for minute in (5, 10):
            result = run_watchdog('mechanical', case.root, case.output_root,
                                 case.adapters(broker=broken, transport=lambda alert, text: calls.append(text)), NOW.replace(minute=minute))
            self.assertEqual('failed', result['status'])
        self.assertEqual(1, len(calls))
        self.assertIn('protection could not be checked', calls[0])
        self.assertNotIn('SECRET', calls[0])
        self.assertEqual({}, store.read_report(case.db))


class AdversarialNotificationTests(unittest.TestCase):
    """Real lineage/broker reproductions from independent release review."""
    def setUp(self):
        from unittest.mock import patch
        from test_watchdog_workflow import build_operational_root
        from watchdog import cli
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.artifacts = Path(self.tmp.name) / 'test_artifacts'
        self.base = self.artifacts / 'watchdog'
        self.base.mkdir(parents=True)
        self.root = build_operational_root(self.base)
        self.output = self.base / 'output'
        self.output.mkdir()
        self.db = self.output / 'private/watchdog/monitoring.sqlite3'
        self.sent = []
        store.apply_notification_policy(self.db)
        paths = patch.object(cli, 'TEST_ARTIFACTS', self.artifacts)
        paths.start()
        self.addCleanup(paths.stop)

    def run_snapshot(self, snapshot, mode='mechanical', now=None, **extra):
        from test_watchdog_workflow import NOW
        from watchdog.cli import run_watchdog
        adapters = dict(broker=lambda: snapshot, transport=lambda message, text: self.sent.append(text))
        adapters.update(extra)
        result = run_watchdog(mode, self.root, self.output, adapters, now or NOW)
        return result, store.read_report(self.db)

    def daily_summary(self, snapshot):
        from test_watchdog_workflow import DAILY_NOW
        result, report = self.run_snapshot(snapshot, mode='daily', now=DAILY_NOW)
        self.assertEqual('ok', result['status'])
        summaries = [text for text in self.sent if text.startswith('Watchdog daily summary')]
        self.assertEqual(1, len(summaries))
        return report, summaries[0]

    def test_daily_summary_does_not_call_discrepant_broker_quantity_covered(self):
        from decimal import Decimal
        from test_watchdog_workflow import broker_snapshot
        snapshot = broker_snapshot(extra_symbol=None)
        snapshot.positions[0]['qty'] = Decimal('3')
        report, summary = self.daily_summary(snapshot)
        self.assertEqual('discrepancy', report['positions'][0]['ownership_status'])
        self.assertNotIn('ABC: covered', summary)
        self.assertIn('ABC: protection unverified', summary)

    def test_daily_summary_does_not_call_unknown_reference_coverage_protected(self):
        from test_watchdog_workflow import broker_snapshot
        snapshot = broker_snapshot(complete=False, extra_symbol=None)
        snapshot.coverage['references'] = 'unknown'
        report, summary = self.daily_summary(snapshot)
        self.assertEqual('unknown', report['positions'][0]['ownership_status'])
        self.assertNotIn('ABC: covered', summary)
        self.assertIn('ABC: protection unverified', summary)

    def test_daily_summary_keeps_uncorroborated_zero_quantity_visible(self):
        from decimal import Decimal
        from test_watchdog_workflow import broker_snapshot
        snapshot = broker_snapshot(extra_symbol=None)
        snapshot.orders[0]['legs'][0].update(status='filled', filled_qty=Decimal('2'), filled_avg_price=Decimal('9'))
        report, summary = self.daily_summary(snapshot)
        self.assertEqual('0', report['positions'][0]['remaining_quantity'])
        self.assertEqual('discrepancy', report['positions'][0]['ownership_status'])
        self.assertNotIn('Open positions: none observed.', summary)
        self.assertIn('ABC: protection unverified', summary)
        self.assertIn('position ownership', summary)

    def test_broker_quantity_mismatch_is_immediate(self):
        from decimal import Decimal
        from test_watchdog_workflow import broker_snapshot
        snapshot = broker_snapshot(extra_symbol=None)
        snapshot.positions[0]['qty'] = Decimal('3')
        _, report = self.run_snapshot(snapshot)
        self.assertEqual('discrepancy', report['positions'][0]['ownership_status'])
        self.assertEqual('consistent', report['positions'][0]['quantity_status'])
        self.assertTrue(any('quantity' in text.lower() for text in self.sent),
                        'current broker quantity mismatch was silenced')

    def test_zero_lineage_quantity_is_not_closed_when_broker_disagrees(self):
        from decimal import Decimal
        from test_watchdog_workflow import broker_snapshot
        snapshot = broker_snapshot(extra_symbol=None)
        snapshot.orders[0]['legs'][0].update(status='filled', filled_qty=Decimal('2'), filled_avg_price=Decimal('9'))
        _, report = self.run_snapshot(snapshot)
        self.assertEqual('0', report['positions'][0]['remaining_quantity'])
        self.assertEqual('discrepancy', report['positions'][0]['ownership_status'])
        self.assertTrue(self.sent, 'unverified closure silenced open broker holding')

    def test_incomplete_protection_observation_is_immediate(self):
        from test_watchdog_workflow import broker_snapshot
        snapshot = broker_snapshot(complete=False, extra_symbol=None)
        snapshot.coverage['references'] = 'unknown'
        _, report = self.run_snapshot(snapshot)
        self.assertEqual('unknown', report['positions'][0]['ownership_status'])
        self.assertTrue(self.sent, 'incomplete current protection check was silenced')

    def test_failed_daily_reporting_retry_checks_latest_conditions_but_defers_summary(self):
        from test_watchdog_workflow import broker_snapshot, DAILY_NOW
        def fail_install(db):
            raise OSError('offline report failure')
        result, _ = self.run_snapshot(broker_snapshot(extra_symbol=None), mode='daily', now=DAILY_NOW,
                                      install_reports=fail_install)
        self.assertEqual('failed', result['status'])
        self.assertEqual([], self.sent)
        store.commit_observation(self.db, observation('mechanical:later', '2026-10-07T20:16:00Z',
                                                     protection_status='unprotected', protection_coverage_quantity='0'))
        result, _ = self.run_snapshot(broker_snapshot(extra_symbol=None), mode='daily',
                                      now=DAILY_NOW.replace(minute=45), install_reports=fail_install)
        self.assertEqual('failed', result['status'])
        self.assertEqual(1, len(self.sent), 'failed reporting retry must check newer urgent conditions')
        self.assertIn('Protection is missing', self.sent[0])
        self.assertEqual(1, result['delivery']['emitted'])
        self.assertFalse((self.output / 'private/watchdog/completions/2026-10-07.json').exists())
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(0, conn.execute("SELECT count(*) FROM notification_emissions WHERE condition_key='daily'").fetchone()[0])
        for second in (1, 5):
            result, _ = self.run_snapshot(broker_snapshot(extra_symbol=None), mode='daily',
                                          now=DAILY_NOW.replace(minute=45, second=second))
            self.assertEqual('ok', result['status'])
        self.assertEqual(2, len(self.sent))
        self.assertIn('daily summary', self.sent[1])
        self.assertIn('covered', self.sent[1], 'summary retains the exact daily run, not the later mechanical snapshot')
        self.assertEqual('mechanical:later', store.read_report(self.db)['run_id'])

    def test_report_install_failure_cannot_hide_detected_missing_stop(self):
        from test_watchdog_workflow import broker_snapshot
        snapshot = broker_snapshot(extra_symbol=None, stop_status='canceled')
        def fail_install(db):
            raise OSError('offline simulated report failure')
        result, report = self.run_snapshot(snapshot, install_reports=fail_install)
        self.assertEqual('failed', result['status'])
        self.assertEqual('unprotected', report['positions'][0]['protection_status'])
        self.assertTrue(self.sent, 'committed missing protection hidden by report installation failure')


if __name__ == '__main__':
    unittest.main()
