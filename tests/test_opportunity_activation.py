"""Synthetic activation history; never activates an operational root."""
import contextlib
import copy
import io
from unittest.mock import patch

import autotrader
import json
import tempfile
import unittest
from pathlib import Path

import opportunity_activation as activation
import sqlite_ledger as storage


class ActivationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'private/opportunity_policy.jsonl'

    def record(self, version=1, **changes):
        return dict(record_type='activation', schema_version=1, policy_version=version,
                    manifest_sha256='a' * 64, timestamp='2026-10-15T14:00:00Z', **changes)

    def write(self, rows):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(''.join(json.dumps(row) + '\n' for row in rows))

    def test_absent_and_empty_history_allow_legacy_without_activation_writes(self):
        self.assertEqual(activation.SUPPORTED_POLICY_VERSION, 0)
        self.assertEqual(activation.POLICY_STREAM, 'private/opportunity_policy.jsonl')
        for rows in (None, []):
            with self.subTest(rows=rows):
                if rows is not None:
                    self.write(rows)
                self.assertEqual(activation.activation_version(self.root), 0)
                activation.require_supported_activation(self.root, supported=0)
                self.assertEqual(self.path.read_text() if self.path.exists() else None,
                                 '' if rows == [] else None)
                self.assertFalse(storage.database_path(self.path).exists())

    def test_floor_denies_activated_v1(self):
        self.write([self.record()])
        with self.assertRaisesRegex(activation.ActivationStateError,
                                    '^opportunity_policy_version_unsupported$'):
            activation.require_supported_activation(self.root, supported=0)

    def test_unknown_positive_versions_are_not_ignored_or_reset(self):
        self.write([self.record(7), self.record(1)])
        self.assertEqual(activation.activation_version(self.root), 7)
        with self.assertRaises(activation.ActivationStateError):
            activation.require_supported_activation(self.root, supported=1)
        activation.require_supported_activation(self.root, supported=7)

    def test_malformed_records_fail_closed(self):
        good = self.record()
        bad_rows = [None, [], {}, {**good, 'record_type': 'unknown'},
                    {**good, 'schema_version': True}, {**good, 'schema_version': 2}]
        for key in good:
            bad_rows.append({k: v for k, v in good.items() if k != key})
        for value in (True, 0, -1, 1.0, '1', None):
            bad_rows.append({**good, 'policy_version': value})
        for value in ('', 'g' * 64, 'a' * 63, None, 1):
            bad_rows.append({**good, 'manifest_sha256': value})
        for value in ('2026-10-15', '2026-10-15T14:00:00',
                      '2026-10-15T14:00:00+01:00', 'invalid', None, 1):
            bad_rows.append({**good, 'timestamp': value})
        for row in bad_rows:
            with self.subTest(row=row):
                self.write([good, row])
                with self.assertRaises(activation.ActivationStateError):
                    activation.activation_version(self.root)
        self.path.write_text('{broken\n')
        with self.assertRaises(activation.ActivationStateError):
            activation.activation_version(self.root)

    def test_read_failure_is_not_absent_state(self):
        self.path.mkdir(parents=True)
        with self.assertRaises(activation.ActivationStateError):
            activation.activation_version(self.root)

    def test_database_projection_gap_blocks_without_repair(self):
        self.write([self.record()])
        storage.migrate_jsonl(self.root)
        self.path.write_text('')
        db = storage.database_path(self.path)
        before = (db.read_bytes(), db.stat().st_mtime_ns, self.path.read_bytes())
        with self.assertRaises(activation.ActivationStateError):
            activation.activation_version(self.root)
        self.assertEqual(before, (db.read_bytes(), db.stat().st_mtime_ns, self.path.read_bytes()))

    def test_unimported_projection_blocks_without_initializing_database(self):
        storage.migrate_jsonl(self.root)
        self.write([self.record()])
        with self.assertRaises(activation.ActivationStateError):
            activation.activation_version(self.root)

    def test_known_future_envelopes_preserve_highest_activation(self):
        envelopes = [dict(record_type=kind, schema_version=1, timestamp='2026-10-15T14:00:00Z')
                     for kind in ('identity_resolution', 'document_alias', 'reopen_grant', 'condition_approval')]
        self.write(envelopes)
        self.assertEqual(activation.activation_version(self.root), 0)
        for rows in (envelopes + [self.record(7), self.record(1)] + envelopes,
                     [self.record(7)] + envelopes + [self.record(1)]):
            self.write(rows)
            self.assertEqual(activation.activation_version(self.root), 7)
            with self.assertRaisesRegex(activation.ActivationStateError,
                                        '^opportunity_policy_version_unsupported$'):
                activation.require_supported_activation(self.root, supported=0)
        for changes in ({'record_type': 'unknown'}, {'schema_version': 2},
                        {'schema_version': True}, {'timestamp': '2026-10-15T14:00:00'}):
            self.write([self.record(), {**envelopes[0], **changes}])
            with self.assertRaisesRegex(activation.ActivationStateError,
                                        '^opportunity_policy_state_unavailable$'):
                activation.activation_version(self.root)

    def test_missing_canonical_activation_projection_cannot_be_absent(self):
        storage.append_jsonl(self.path, self.record())
        self.path.unlink()
        with self.assertRaisesRegex(activation.ActivationStateError,
                                    '^opportunity_policy_state_unavailable$'):
            activation.require_supported_activation(self.root, supported=0)
        self.assertFalse(self.path.exists())

    def test_absent_policy_does_not_audit_unrelated_projection(self):
        unrelated = self.root / 'order_ledger.jsonl'
        for migrated in (False, True):
            if migrated:
                unrelated.write_text('')
                storage.migrate_jsonl(self.root)
            for text in ('not-json\n', '{"status":"new"}\n'):
                unrelated.write_text(text)
                self.assertEqual(activation.activation_version(self.root), 0)

    def test_canonical_registry_includes_policy_exactly_once(self):
        self.assertEqual(storage.DEFAULT_STREAMS.count(activation.POLICY_STREAM), 1)


class ActivationOrderingTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing all-gates-valid synthetic trading scenario, including
        # its explicit aware clock and owned pending parent. No lifecycle mocks.
        import test_concurrent_workflow as workflow
        self.fixture = workflow.ConcurrentWorkflowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def activate(self):
        path = self.root / activation.POLICY_STREAM
        path.write_text(json.dumps(dict(record_type='activation', schema_version=1,
            policy_version=1, manifest_sha256='a' * 64,
            timestamp='2026-10-15T14:00:00Z')) + '\n')

    def run_entry(self, broker=None, reviewer=None):
        output = io.StringIO()
        if reviewer is None:
            reviewer = lambda *args: self.fail('unexpected paid review after activation')
        with patch.object(autotrader, 'ROOT', self.root), \
                patch.object(autotrader, '_broker_bridge', side_effect=broker or self.fixture.broker), \
                patch.object(autotrader, 'independent_reviews', side_effect=reviewer), \
                contextlib.redirect_stdout(output):
            code = autotrader.run(autotrader.argparse.Namespace(
                dry_run_fixture=False, live_dry_run=False))
        return code, output.getvalue()

    def test_inactive_negative_control_reaches_reviewer_with_real_gates(self):
        class ReachedReviewer(Exception):
            pass
        def reviewer(*args):
            raise ReachedReviewer()
        with self.assertRaises(ReachedReviewer):
            self.run_entry(reviewer=reviewer)
        self.assertIn('snapshot', [op for op, _ in self.fixture.calls])

    def test_activated_floor_blocks_before_candidate_snapshot_or_review(self):
        self.activate()
        code, output = self.run_entry()
        self.assertEqual((code, output),
                         (2, 'BLOCKER opportunity_policy_version_unsupported\n'))
        self.assertNotIn('snapshot', [op for op, _ in self.fixture.calls])
        self.assertFalse((self.root / 'private/reviews.jsonl').exists())

    def test_known_envelopes_around_activation_keep_cli_version_blocker(self):
        self.activate()
        path = self.root / activation.POLICY_STREAM
        active = path.read_text()
        envelope = json.dumps(dict(record_type='identity_resolution', schema_version=1,
                                   timestamp='2026-10-15T14:00:00Z')) + '\n'
        path.write_text(envelope + active + envelope)
        code, output = self.run_entry()
        self.assertEqual((code, output),
                         (2, 'BLOCKER opportunity_policy_version_unsupported\n'))
        self.assertNotIn('snapshot', [op for op, _ in self.fixture.calls])

    def test_canonical_activation_projection_loss_blocks_actual_entry(self):
        self.activate()
        path = self.root / activation.POLICY_STREAM
        storage.migrate_jsonl(self.root)
        path.unlink()
        code, output = self.run_entry()
        self.assertEqual((code, output),
                         (2, 'BLOCKER opportunity_policy_state_unavailable\n'))
        self.assertNotIn('snapshot', [op for op, _ in self.fixture.calls])
        self.assertFalse(path.exists())

    def test_corrupt_policy_maps_to_stable_cli_blocker_after_lifecycle(self):
        self.activate()
        path = self.root / activation.POLICY_STREAM
        row = json.loads(path.read_text())
        row['schema_version'] = 2
        path.write_text(json.dumps(row) + '\n')
        code, output = self.run_entry()
        self.assertEqual((code, output),
                         (2, 'BLOCKER opportunity_policy_state_unavailable\n'))
        self.assertNotIn('snapshot', [op for op, _ in self.fixture.calls])

    def test_real_protective_sell_accounting_survives_activated_floor(self):
        import test_managed_reconciliation as managed
        fixture = managed.ManagedReconciliationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root
        (self.root / 'autonomy_config.json').write_text(json.dumps(self.fixture.cfg))
        self.activate()
        calls = []
        def broker(operation, payload):
            calls.append(operation)
            if operation == 'reconciliation_snapshot':
                return fixture.broker(operation, payload)
            if operation == 'reconcile_many':
                orders = {'parent': fixture.parent, 'replacement': fixture.target}
                return {'orders': copy.deepcopy([orders[ref] for ref in payload['client_order_ids']])}
            self.fail('unexpected broker operation: ' + operation)
        code, output = self.run_entry(broker=broker)
        self.assertEqual(code, 0, output)
        self.assertIn('TRADE SELL 3', output)
        rows = autotrader.read_jsonl(self.root / 'trade_journal.jsonl')
        sells = [row for row in rows if row['action'] == 'SELL']
        self.assertEqual(len(sells), 1)
        self.assertEqual((sells[0]['quantity'], sells[0]['parent_client_order_id']),
                         (3, 'parent'))
        self.assertIn('reconciliation_snapshot', calls)
        self.assertNotIn('snapshot', calls)
        # The direct guard remains blocked even though SELL accounting succeeded.
        with self.assertRaises(activation.ActivationStateError):
            activation.require_supported_activation(self.root, supported=0)

    def test_real_pending_continuation_precedes_activation_block(self):
        self.activate()
        code, output = self.run_entry()
        self.assertEqual((code, output),
                         (2, 'BLOCKER opportunity_policy_version_unsupported\n'))
        # Existing exact-parent continuation must still read its own parent.
        self.assertTrue(any('one' in payload.get('client_order_ids', [])
                            or payload.get('client_order_id') == 'one'
                            for _, payload in self.fixture.calls))
        rows = autotrader.read_jsonl(self.root / 'order_ledger.jsonl')
        self.assertEqual(rows[0], {'client_order_id': 'one', 'status': 'new'})
        self.assertEqual(rows[1:], [dict(action='BUY', client_order_id='one',
            status='new', symbol='AAPL', timestamp='2026-10-16T00:30:00Z')])
