import argparse
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import autotrader as a
import test_order_notifications as notifications


class ForwardLineageTests(unittest.TestCase):
    def test_confirmed_fill_carries_identity_without_changing_plan(self):
        fixture = notifications.PlacingNotificationTests()
        fixture.setUp()
        plan = copy.deepcopy(fixture.plan)
        order = dict(fixture.accepted, id='broker-id', status='filled', filled_qty='3', filled_avg_price='162.80')
        metadata = dict(candidate_id='cid', dossier_hash='dh', proposal_hash='ph', parent_client_order_id=fixture.ref)
        with tempfile.TemporaryDirectory(dir='/opt/data/cache/scratch') as td:
            path = Path(td) / 'trade_journal.jsonl'
            a.journal_confirmed_fill(path, plan, order, metadata)
            row = a.read_jsonl(path)[0]
        for key, value in metadata.items():
            self.assertEqual(row[key], value)
        self.assertEqual(row['broker_order_id'], 'broker-id')
        self.assertEqual(row['client_order_id'], fixture.ref)
        self.assertEqual(row['cumulative_filled_quantity'], '3')
        self.assertEqual(row['cumulative_filled_notional'], '488.40')
        self.assertEqual(plan, fixture.plan)

    def run_isolated(self, root, *, dry=False, reject=False):
        fixture = json.loads((Path(a.__file__).parent / 'fixtures/dry_run_bundle.json').read_text())
        fixture['candidate']['dossier_hash'] = 'dossier-exact'
        cfg = dict(enabled=True, broker_mode='paper', max_position_usd=500,
                   max_planned_risk_per_trade_usd=40, account_cap_usd=10000, min_approval_confidence=0.7)
        fixed_time = fixture['snapshot']['captured_at']
        root.joinpath('fixtures').mkdir()
        root.joinpath('fixtures/dry_run_bundle.json').write_text(json.dumps(fixture))
        root.joinpath('autonomy_config.json').write_text(json.dumps(cfg))
        root.joinpath('candidates.jsonl').write_text(json.dumps(fixture['candidate']) + '\n')
        proposal, errors = a.build_canonical_proposal(fixture['candidate'], fixture['snapshot'], cfg, 0)
        self.assertEqual(errors, [])
        assert proposal is not None
        for key in ('review_a', 'review_b'):
            fixture[key].update(decision='APPROVE', fatal_flags=[], reason_codes=[],
                                component_scores={name: 5 for name in a.RUBRIC_WEIGHTS[proposal['assigned_rubric']]})
        root.joinpath('fixtures/dry_run_bundle.json').write_text(json.dumps(fixture))
        reviews = [dict(fixture[x], proposal_hash=proposal['proposal_hash']) for x in ('review_a', 'review_b')]
        if reject:
            reviews[0]['decision'] = 'HOLD'
        expected_bundle = a.build_review_bundle(fixture['candidate'], fixture['snapshot'], proposal)
        expected_plan = a.normalize_order_metrics(a.aggregate_proposal_reviews(proposal, reviews, cfg)['order']) if not reject else None
        calls, bundles = [], []
        def review(bundle, config):
            bundles.append(copy.deepcopy(bundle))
            return reviews
        def broker(operation, payload):
            calls.append((operation, copy.deepcopy(payload)))
            if operation in ('snapshot', 'review'):
                return fixture['snapshot']
            if operation == 'place':
                return {}
            if operation == 'reconcile':
                return dict(id='broker-id', client_order_id=payload['client_order_id'], status='filled',
                            symbol=expected_plan['symbol'], side='buy', type='limit', order_class='bracket',
                            qty=str(expected_plan['quantity']), filled_qty=str(expected_plan['quantity']),
                            filled_avg_price=str(expected_plan['limit_price']))
            raise AssertionError(operation)
        with contextlib.ExitStack() as stack:
            for name, value in dict(ROOT=root, utcnow=lambda: fixed_time, runtime_blockers=lambda *x, **kw: [],
                                    research_acceptable=lambda *x, **kw: True, research_age_minutes=lambda *x: 0,
                                    load_baseline_symbols=lambda *x: set(), reconcile_pending_orders=lambda *x, **kw: [],
                                    reconcile_managed_exits=lambda *x: [], reconcile_managed_protection=lambda *x: [],
                                    pre_review_validation=lambda *x: ([], {}), post_review_validation=lambda *x: ([], {}),
                                    broker_review_validation=lambda *x: ([], {}), independent_reviews=review,
                                    _broker_bridge=broker, record_shadow_if_live=lambda *x: None,
                                    emit_placing_notification_once=lambda *x: True).items():
                stack.enter_context(patch.object(a, name, value))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            status = a.run(argparse.Namespace(dry_run_fixture=dry, live_dry_run=False))
        return status, fixture, proposal, expected_plan, expected_bundle, calls, bundles

    def test_submission_metadata_leaves_payload_hash_and_reviewer_bundle_unchanged(self):
        with tempfile.TemporaryDirectory(dir='/opt/data/cache/scratch') as td:
            root = Path(td)
            status, fixture, proposal, plan, bundle, calls, bundles = self.run_isolated(root)
            self.assertEqual(status, 0)
            intent = a.read_jsonl(root / 'private/order_intents.jsonl')[0]
            self.assertEqual(intent['candidate_id'], fixture['candidate']['candidate_id'])
            self.assertEqual(intent['dossier_hash'], 'dossier-exact')
            self.assertEqual(intent['proposal_hash'], proposal['proposal_hash'])
            self.assertEqual(intent['parent_client_order_id'], intent['client_order_id'])
            self.assertEqual(intent['plan'], plan)
            self.assertEqual(bundles, [bundle])
            self.assertEqual([p for op, p in calls if op == 'place'],
                             [dict(order=plan, client_order_id=intent['client_order_id'])])
            self.assertEqual(a.read_jsonl(root / 'trade_journal.jsonl')[0]['candidate_id'], intent['candidate_id'])
            self.assertTrue(all(r['proposal_hash'] == proposal['proposal_hash'] for r in a.read_jsonl(root / 'order_ledger.jsonl')))

    def test_dry_run_linkage_stays_in_test_artifacts(self):
        with tempfile.TemporaryDirectory(dir='/opt/data/cache/scratch') as td:
            root = Path(td)
            status, fixture, proposal, *rest = self.run_isolated(root, dry=True)
            self.assertEqual(status, 2)
            rows = a.read_jsonl(root / 'test_artifacts/dry_run_order_ledger.jsonl')
            self.assertEqual(rows[0]['candidate_id'], fixture['candidate']['candidate_id'])
            self.assertEqual(rows[-1]['proposal_hash'], proposal['proposal_hash'])
            self.assertEqual(a.read_jsonl(root / 'test_artifacts/dry_run_reviews.jsonl')[0]['candidate_id'], fixture['candidate']['candidate_id'])
            self.assertFalse((root / 'order_ledger.jsonl').exists())
            self.assertFalse((root / 'private/order_intents.jsonl').exists())
            self.assertFalse((root / 'trade_journal.jsonl').exists())

    def test_reviewer_rejection_private_metadata_not_public_disagreement(self):
        with tempfile.TemporaryDirectory(dir='/opt/data/cache/scratch') as td:
            root = Path(td)
            status, fixture, proposal, *rest = self.run_isolated(root, reject=True)
            self.assertEqual(status, 2)
            private = a.read_jsonl(root / 'order_ledger.jsonl')[0]
            public = a.read_jsonl(root / 'public/disagreements.jsonl')[0]
            self.assertEqual(private['candidate_id'], fixture['candidate']['candidate_id'])
            self.assertEqual(private['proposal_hash'], proposal['proposal_hash'])
            for key in ('candidate_id', 'dossier_hash', 'proposal_hash', 'parent_client_order_id'):
                self.assertNotIn(key, public)

    def test_both_protective_exit_writers_copy_lineage_from_intent(self):
        import test_managed_reconciliation as existing
        import managed_reconciliation as m
        for shared in (False, True):
            fixture = existing.ManagedReconciliationTests()
            fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            meta = dict(candidate_id='cid', dossier_hash='dh', proposal_hash='ph', parent_client_order_id='wrong-parent')
            fixture.write('private/order_intents.jsonl', dict(client_order_id='parent', plan=fixture.plan, **meta))
            fixture.target['id'] = 'exit-broker-id'
            if shared:
                updates = m.reconcile(fixture.root, fixture.broker)
            else:
                target = dict(fixture.target, order_class='bracket', legs=[])
                stop = dict(fixture.stop, order_class='bracket')
                parent = dict(fixture.parent, legs=[target, stop])
                updates = a.reconcile_managed_exits(fixture.root / 'order_ledger.jsonl',
                    fixture.root / 'private/order_intents.jsonl', fixture.root / 'trade_journal.jsonl',
                    lambda operation, payload: {'orders': [parent]})
            self.assertEqual(updates[0]['candidate_id'], 'cid')
            self.assertEqual(updates[0]['broker_order_id'], 'exit-broker-id')
            self.assertEqual(updates[0]['client_order_id'], 'replacement')
            self.assertEqual(updates[0]['parent_client_order_id'], 'parent')
            self.assertEqual(a.read_jsonl(fixture.root / 'order_ledger.jsonl')[-1]['parent_client_order_id'], 'parent')
            self.assertEqual(updates[0]['cumulative_filled_quantity'], '3')
            self.assertEqual(a.read_jsonl(fixture.root / 'order_ledger.jsonl')[-1]['proposal_hash'], 'ph')

    def test_retry_review_metadata_has_candidate_identity(self):
        with tempfile.TemporaryDirectory(dir='/opt/data/cache/scratch') as td:
            path = Path(td) / 'reviews.jsonl'
            a.note_pre_submission_retryable(path, dict(candidate_id='cid', dossier_hash='dh'), 'evidence')
            self.assertEqual(a.read_jsonl(path)[0]['candidate_id'], 'cid')

    def test_candidate_retry_cannot_supply_an_order_parent_or_proposal_hash(self):
        with tempfile.TemporaryDirectory(dir='/opt/data/cache/scratch') as td:
            path = Path(td) / 'reviews.jsonl'
            a.note_pre_submission_retryable(path, dict(candidate_id='cid', dossier_hash='dh',
                                            proposal_hash='untrusted', parent_client_order_id='untrusted'), 'evidence')
            row = a.read_jsonl(path)[0]
            self.assertNotIn('proposal_hash', row)
            self.assertNotIn('parent_client_order_id', row)

    def test_reconciliation_block_review_has_candidate_id(self):
        with tempfile.TemporaryDirectory(dir='/opt/data/cache/scratch') as td:
            root = Path(td)
            root.joinpath('candidates.jsonl').write_text(json.dumps(dict(candidate_id='cid', dossier_hash='dh')) + '\n')
            path = root / 'private/reviews.jsonl'
            with patch.object(a, 'ROOT', root):
                a.note_reconciliation_blocked(path)
            self.assertEqual(a.read_jsonl(path)[0]['candidate_id'], 'cid')

    def test_pending_fill_propagates_intent_top_level_metadata(self):
        fixture = notifications.PlacingNotificationTests()
        fixture.setUp()
        meta = dict(candidate_id='cid', dossier_hash='dh', proposal_hash='ph', parent_client_order_id=fixture.ref)
        order = dict(fixture.accepted, id='broker-id', status='filled', filled_qty='3', filled_avg_price='162.80')
        with tempfile.TemporaryDirectory(dir='/opt/data/cache/scratch') as td:
            root = Path(td)
            ledger, intents, journal = [root / x for x in ('ledger.jsonl', 'intents.jsonl', 'journal.jsonl')]
            ledger.write_text(json.dumps(dict(client_order_id=fixture.ref, status='placed')) + '\n')
            intents.write_text(json.dumps(dict(client_order_id=fixture.ref, plan=fixture.plan, **meta)) + '\n')
            calls = []
            def broker(operation, payload):
                calls.append((operation, payload))
                return order
            updates = a.reconcile_pending_orders(ledger, intents, journal, broker)
            self.assertEqual(updates[0]['candidate_id'], 'cid')
            self.assertEqual(a.read_jsonl(journal)[0]['proposal_hash'], 'ph')
            self.assertEqual(calls, [('reconcile', {'client_order_id': fixture.ref})])
            self.assertNotIn('candidate_id', updates[0]['_plan'])


if __name__ == '__main__':
    unittest.main()
