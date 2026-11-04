"""Synthetic entry-locked execution enforcement tests (Task 6).

Every issuer, dossier, review and order below is explicitly fictional.
Only transport/model boundaries are replaced; the real gate functions,
storage and locks run. All dates are explicit aware clocks or the test's
own injected instants, never the operational day.
"""
import contextlib
import copy
import datetime as dt
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autotrader
import entry_eligibility
import opportunity_fixtures as fixtures
import opportunity_state as state
import sqlite_ledger as storage

NOW = dt.datetime(2026, 11, 4, 15, 0, tzinfo=dt.timezone.utc)


def _utc_text(stamp):
    return stamp.isoformat().replace('+00:00', 'Z')


def _dossier(candidate):
    body = {k: v for k, v in candidate.items() if k != 'dossier_hash'}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class ExecutionCase(unittest.TestCase):
    """One activated synthetic root with the ACME event bound at generation 0."""

    active = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        fixtures.make_root(self.root, active=self.active)
        (self.root / 'private/broker_baseline.json').write_text(
            json.dumps({'preexisting_symbols': []}))
        self.resolution = fixtures.synthetic_resolution()
        identity = state.allowance_identifier(self.resolution.event_id, 0)
        storage.append_jsonl(self.root / state.POLICY_STREAM, fixtures.policy_row(
            'identity_resolution', resolution=fixtures.synthetic_resolution_payload()))
        self.candidate = {
            'candidate_id': 'synthetic-candidate-1',
            'symbol': fixtures.SYMBOL,
            'price': 100.05,
            'spy_price': 500.0,
            'instrument_type': 'cash_equity',
            'catalyst': 'Synthetic catalyst',
            'thesis': 'Synthetic thesis for fixture only.',
            'setup_type': 'post_news_momentum',
            'planned_exit_at': '2026-11-20T20:00:00Z',
            'horizon_rationale': 'Synthetic window.',
            'earnings_event_at': '2026-10-21T20:00:00Z',
            'researched_at': _utc_text(NOW - dt.timedelta(hours=1)),
            'sources': [{'url': 'https://example.com/a', 'title': 'A'},
                        {'url': 'https://example.org/b', 'title': 'B'}],
            'sources_verified_at': _utc_text(NOW - dt.timedelta(minutes=5)),
            'opportunity_identity': fixtures.synthetic_resolution_payload(),
            'event_id': self.resolution.event_id,
            'allowance_id': identity,
        }
        self.candidate['dossier_hash'] = _dossier(self.candidate)
        self.dossier = self.candidate['dossier_hash']
        storage.append_jsonl(self.root / state.CANDIDATES_STREAM,
                             fixtures.candidate_link(self.dossier, self.resolution.event_id, identity))
        self.write_candidate()
        self.cfg = {
            'enabled': True, 'broker_mode': 'paper',
            'min_approval_confidence': 0.6, 'min_reward_risk': 1.5,
            'max_position_usd': 500, 'account_cap_usd': 10000,
            'max_planned_risk_per_trade_usd': 400, 'max_daily_orders': 3,
            'max_research_age_minutes': 600, 'min_price_usd': 10,
            'min_average_volume': 1000000, 'max_spread_bps': 500,
            'allowed_quote_feeds': ['alpaca_iex'], 'max_limit_deviation_bps': 3500,
            'max_quote_age_seconds': 120, 'earnings_blackout_sessions': 2,
            'pending_entry_policy': 'exact_owned_zero_fill_v1',
            'max_pending_entry_parents': 3,
            'research_model': {'provider': 'x', 'model': 'y'},
            'review_model': {'provider': 'x', 'model': 'z'},
        }
        (self.root / 'autonomy_config.json').write_text(json.dumps(self.cfg))
        self.reviewer_mock = None
        self.broker_operations = []
        self.placed = {}

    # ------------------------------------------------------------------ helpers
    def observation(self, positions=(), open_orders=(), *, started=None, finished=None):
        started = started or (NOW - dt.timedelta(seconds=2))
        finished = finished or (NOW - dt.timedelta(seconds=1))
        return entry_eligibility.entry_observation(
            started_at=started, finished_at=finished, duration_seconds=0.5,
            positions=list(positions), open_orders=list(open_orders))

    def snapshot(self, *, positions=(), open_orders=(), observation=None, quote_stamp=None):
        stamp = quote_stamp or _utc_text(NOW - dt.timedelta(seconds=1))
        return {
            'captured_at': _utc_text(NOW),
            'buying_power': 10000.0, 'cash': 10000.0,
            'cash_semantics': 'gross', 'buying_power_semantics': 'available_net',
            'positions': list(positions), 'open_orders': list(open_orders),
            'entry_observation': observation if observation is not None else self.observation(
                positions, open_orders),
            'asset': {'symbol': fixtures.SYMBOL, 'tradable': True, 'class': 'us_equity',
                      'exchange': 'NASDAQ', 'name': 'Fictional Acme Laboratory Inc.',
                      'fractionable': False, 'leveraged': False, 'inverse': False},
            'quote': {'bid': 99.95, 'ask': 100.05, 'timestamp': stamp},
            'quote_feed': 'alpaca_iex', 'average_volume': 5000000.0,
            'volume_feed': 'massive_consolidated',
            'technical_bars_feed': 'massive_consolidated_completed_daily',
            'technical_bars': [{'open': 100 + i, 'high': 101 + i, 'low': 99 + i,
                                'close': 100.5 + i, 'timestamp': 1700000000 + i * 86400}
                               for i in range(25)],
            'earnings_status': 'reported', 'earnings_sessions_away': None,
            'trading_sessions': ['2026-11-02', '2026-11-03', '2026-11-04',
                                 '2026-11-05', '2026-11-06', '2026-11-09',
                                 '2026-11-10', '2026-11-11', '2026-11-12',
                                 '2026-11-13', '2026-11-16', '2026-11-17',
                                 '2026-11-18', '2026-11-19', '2026-11-20'],
            'trading_calendar': [],
        }

    def held_row(self):
        return {'symbol': fixtures.SYMBOL, 'side': 'long', 'qty': 5,
                'avg_entry_price': 90.0, 'market_value': 500.0, 'asset_id': 'syn-1'}

    def bind_claim(self):
        """Durable, sealed, condition-backed reopening claim for the spent event."""
        from opportunity_admin import (make_reopening_claim, observe_completed_close,
                                       record_reopening_claim)
        self.spend()
        condition = {'metric': 'completed_close_usd', 'operator': '>=', 'threshold': '50',
                     'units': 'USD', 'source_kind': 'massive_consolidated_completed_daily',
                     'expires_at': '2030-01-01T00:00:00+00:00',
                     'observation_max_age_seconds': 86400,
                     'baseline_ref': 'synthetic-baseline',
                     'allowance_id': state.allowance_identifier(self.resolution.event_id, 0)}
        storage.append_jsonl(self.root / state.POLICY_STREAM, fixtures.policy_row(
            'condition_approval', condition_id='synthetic-condition',
            event_id=self.resolution.event_id, condition=condition))
        index = state.load_index(self.root)
        observation = observe_completed_close(
            {'metric': 'completed_close_usd', 'units': 'USD', 'value': '60.0',
             'source': 'massive_consolidated_completed_daily',
             'market_prices_at': _utc_text(NOW - dt.timedelta(minutes=10))},
            event_id=self.resolution.event_id, evidence_ref='completed-close:synthetic')
        claim = make_reopening_claim(index, self.resolution, observation, now=NOW)
        self.assertIsNotNone(claim)
        record_reopening_claim(self.root, claim)
        return claim

    def spend(self):
        storage.append_jsonl(self.root / state.REVIEWS_STREAM, fixtures.review_row(
            self.dossier, 'synthetic-review', [{'decision': 'HOLD'}]))

    def write_candidate(self, **changes):
        candidate = dict(self.candidate, **changes)
        candidate['dossier_hash'] = _dossier(candidate)
        storage.append_jsonl(self.root / 'candidates.jsonl', candidate)
        return candidate

    def ns(self):
        return autotrader.argparse.Namespace(dry_run_fixture=False, live_dry_run=False)

    def run_locked(self, *, snapshot=None, fresh=None, approvals=True, bridge_ops=None):
        """Run the real _run_locked with only transport/model boundaries replaced."""
        snapshot = snapshot if snapshot is not None else self.snapshot()
        fresh = fresh if fresh is not None else copy.deepcopy(snapshot)
        # Pre-existing baseline holdings are the legacy documented way a held
        # symbol reaches the entry gates without tripping untracked-position
        # reconciliation first; the BUY predicate still blocks them.
        # Only pre-existing (snapshot-time) holdings belong in the baseline;
        # a fill that appears only in fresh truth stays untracked and fails
        # closed inside reconciliation before any deterministic rejection.
        held = {row['symbol'] for row in snapshot.get('positions', [])}
        if held:
            (self.root / 'private/broker_baseline.json').write_text(
                json.dumps({'preexisting_symbols': sorted(held)}))
        captured = io.StringIO()
        self.broker_operations = []
        self.reviewer_calls = []

        def bridge(operation, payload=None):
            self.broker_operations.append(operation)
            if operation == 'snapshot':
                return copy.deepcopy(snapshot)
            if operation == 'review':
                return copy.deepcopy(fresh)
            if operation == 'place':
                self.placed = dict(payload or {})
                return {}
            if operation == 'reconcile':
                plan = self.placed['order']
                return {'status': 'new', 'client_order_id': (payload or {}).get('client_order_id'),
                        'symbol': plan['symbol'], 'side': 'buy', 'qty': plan['quantity'],
                        'type': 'limit', 'order_class': 'bracket',
                        'filled_qty': 0, 'filled_avg_price': 0}
            if operation == 'reconcile_many':
                return {'orders': []}
            raise AssertionError('unexpected bridge operation ' + operation)

        def reviews(bundle, cfg):
            self.reviewer_calls.append(copy.deepcopy(bundle))
            if not approvals:
                return []
            proposal_hash = bundle['proposal']['proposal_hash']
            scores = {key: 5 for key in autotrader.RUBRIC_WEIGHTS[
                bundle['proposal']['assigned_rubric']]}
            return [{'proposal_hash': proposal_hash, 'decision': 'APPROVE',
                     'component_scores': scores, 'fatal_flags': [], 'reason_codes': []},
                    {'proposal_hash': proposal_hash, 'decision': 'APPROVE',
                     'component_scores': scores, 'fatal_flags': [], 'reason_codes': []}]

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(autotrader, 'ROOT', self.root))
            stack.enter_context(patch.object(autotrader, 'runtime_blockers', return_value=[]))
            stack.enter_context(patch.object(autotrader, 'reconcile_pending_orders', return_value=[]))
            stack.enter_context(patch.object(autotrader, 'reconcile_managed_exits', return_value=[]))
            stack.enter_context(patch.object(autotrader, 'reconcile_managed_protection', return_value=[]))
            stack.enter_context(patch.object(autotrader, '_broker_bridge', side_effect=bridge))
            stack.enter_context(patch.object(autotrader, 'independent_reviews', side_effect=reviews))
            shim = _dt_shim()
            stack.enter_context(patch.object(autotrader, 'dt', shim))
            stack.enter_context(contextlib.redirect_stdout(captured))
            code = autotrader._run_locked(self.ns())
        return code, captured.getvalue()

    def grants(self):
        return state.load_index(self.root).grants

    def intents(self):
        path = self.root / 'private/order_intents.jsonl'
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _dt_shim():
    """Module shim so the fixed clock never leaks into other modules.

    Patching the datetime module attribute globally would break the strict
    isinstance clocks in entry_eligibility, opportunity_admin and state.
    """
    import types
    shim = types.ModuleType('autotrader_fixed_clock')
    for name in dir(dt):
        if not name.startswith('__'):
            setattr(shim, name, getattr(dt, name))
    shim.datetime = FixedDateTime
    return shim


class FixedDateTime(dt.datetime):
    """Fixed UTC instant for deterministic timestamps inside execution."""

    @classmethod
    def now(cls, tz=None):
        return NOW if tz is None else NOW.astimezone(tz)


class EntryBoundaryTests(ExecutionCase):
    def test_held_candidate_never_reaches_review_or_placement(self):
        code, out = self.run_locked(snapshot=self.snapshot(positions=[self.held_row()]))
        self.assertEqual(code, 2)
        self.assertEqual(self.reviewer_calls, [])
        self.assertNotIn('place', self.broker_operations)

    def test_held_blocker_is_deterministic_before_sizing(self):
        code, out = self.run_locked(snapshot=self.snapshot(positions=[self.held_row()]))
        self.assertEqual(code, 2, out)
        self.assertIn('BLOCKER position_already_held', out)
        self.assertEqual(self.broker_operations, ['snapshot'])

    def test_pending_qualification_blocks_before_paid_review(self):
        cfg = dict(self.cfg)
        cfg.pop('pending_entry_policy')
        cfg.pop('max_pending_entry_parents')
        (self.root / 'autonomy_config.json').write_text(json.dumps(cfg))
        code, out = self.run_locked()
        self.assertEqual(code, 2, out)
        self.assertIn('BLOCKER pending_qualification_required', out)
        self.assertEqual(self.reviewer_calls, [])
        self.assertNotIn('place', self.broker_operations)

    def test_unknown_entry_observation_blocks(self):
        snapshot = self.snapshot()
        snapshot['entry_observation'] = dict(snapshot['entry_observation'], version=2)
        code, out = self.run_locked(snapshot=snapshot)
        self.assertEqual(code, 2, out)
        self.assertIn('BLOCKER entry_evidence_unverified', out)
        self.assertEqual(self.reviewer_calls, [])
        self.assertNotIn('place', self.broker_operations)

    def test_stale_previously_qualified_candidate_cannot_bypass_guard(self):
        self.spend()
        code, out = self.run_locked()
        self.assertEqual(code, 2, out)
        self.assertIn('BLOCKER unchanged_opportunity', out)
        self.assertEqual(self.broker_operations, [])

    def test_unknown_or_absent_binding_is_never_entry_permission(self):
        candidate = self.write_candidate(opportunity_identity={'version': 1, 'status': 'unknown'},
                                         event_id=None, allowance_id=None)
        code, out = self.run_locked()
        self.assertEqual(code, 2, out)
        self.assertIn('BLOCKER', out)
        self.assertEqual(self.broker_operations, [])

    def test_malformed_policy_state_fails_closed(self):
        storage.append_jsonl(self.root / state.POLICY_STREAM, {'record_type': 'unknown'})
        code, out = self.run_locked()
        self.assertEqual(code, 2, out)
        self.assertIn('BLOCKER', out)
        self.assertEqual(self.broker_operations, [])

    def test_current_exact_attempt_submits_once(self):
        code, out = self.run_locked()
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.reviewer_calls), 1)
        self.assertIn('place', self.broker_operations)
        self.assertEqual(len(self.intents()), 1)

    def test_competing_execution_after_spend_is_blocked(self):
        code, out = self.run_locked()
        self.assertEqual(code, 0, out)
        self.assertIn('place', self.broker_operations)
        # A second competing execution for the same spent generation stops
        # at the entry boundary without any broker snapshot.
        operations_before = list(self.broker_operations)
        code2, out2 = self.run_locked()
        self.assertEqual(code2, 2, out2)
        self.assertIn('BLOCKER unchanged_opportunity', out2)
        self.assertEqual(self.broker_operations, [])

    def test_other_proposal_or_evidence_id_cannot_borrow_the_approval(self):
        import opportunity_state
        code, out = self.run_locked()
        self.assertEqual(code, 0, out)
        rows = [json.loads(line) for line in
                (self.root / 'private/reviews.jsonl').read_text().splitlines()]
        approved = [row for row in rows if any(
            isinstance(r, dict) and r.get('decision') == 'APPROVE' for r in row.get('reviews', []))]
        self.assertEqual(len(approved), 1)
        row = approved[0]
        with self.assertRaises(opportunity_state.OpportunityStateError):
            opportunity_state.authorize_current_attempt(
                state.load_index(self.root), dossier_hash=row['dossier_hash'],
                proposal_hash='f' * 64, evidence_id=row['evidence_id'])
        with self.assertRaises(opportunity_state.OpportunityStateError):
            opportunity_state.authorize_current_attempt(
                state.load_index(self.root), dossier_hash=row['dossier_hash'],
                proposal_hash=row['proposal_hash'], evidence_id='borrowed-evidence')

    def test_exact_ref_replay_after_lost_ack(self):
        code, out = self.run_locked()
        self.assertEqual(code, 0, out)
        intents = self.intents()
        self.assertEqual(len(intents), 1)
        # Reconciliation replay of the same intent is idempotent on refs.
        rows = autotrader.read_jsonl(self.root / 'order_ledger.jsonl')
        self.assertEqual(autotrader.pending_order_intents(rows, intents), intents)


class ReopeningTransitionTests(ExecutionCase):
    def test_verified_claim_prechecks_commit_and_end_without_paid_review(self):
        self.bind_claim()
        code, out = self.run_locked()
        self.assertEqual(code, 0, out)
        self.assertIn('DECISION reopening_committed', out)
        self.assertEqual(self.reviewer_calls, [])
        self.assertNotIn('place', self.broker_operations)
        self.assertEqual(self.broker_operations, ['snapshot'])
        grants = self.grants()
        self.assertEqual(len(grants), 1)
        index = state.load_index(self.root)
        self.assertTrue(any(
            row.get('condition_id') == 'synthetic-condition' for row in grants.values()))
        # The claim is consumed; the original dossier keeps its prior binding.
        self.assertEqual(index.dossier_allowances[self.dossier],
                         state.allowance_identifier(self.resolution.event_id, 0))

    def test_held_symbol_presented_does_not_consume_claim(self):
        self.bind_claim()
        code, out = self.run_locked(snapshot=self.snapshot(positions=[self.held_row()]))
        self.assertEqual(code, 2, out)
        # A held symbol never consumes the claim: the deterministic precheck
        # or BUY gate blocks before any grant is committed.
        self.assertNotIn('reopening_committed', out)
        self.assertEqual(self.reviewer_calls, [])
        self.assertNotIn('place', self.broker_operations)
        self.assertEqual(self.grants(), {})

    def test_precheck_failure_does_not_commit_claim(self):
        self.bind_claim()
        snapshot = self.snapshot()
        snapshot['quote']['ask'] = 100.05
        snapshot['buying_power'] = 10.0
        code, out = self.run_locked(snapshot=snapshot)
        self.assertEqual(code, 2, out)
        self.assertNotIn('reopening_committed', out)
        self.assertEqual(self.grants(), {})


class FinalRecheckTests(ExecutionCase):
    def test_fill_during_review_aborts_before_intent(self):
        fresh = self.snapshot(positions=[self.held_row()])
        code, out = self.run_locked(fresh=fresh)
        # A fill during reviewers is untracked broker truth: fail closed
        # before intent, with no placement and no retryable marker.
        self.assertEqual(code, 4, out)
        self.assertIn('SYSTEM_FAILURE', out)
        self.assertEqual(self.intents(), [])
        self.assertNotIn('place', self.broker_operations)

    def test_fill_is_not_a_retryable_market_condition(self):
        fresh = self.snapshot(positions=[self.held_row()])
        self.run_locked(fresh=fresh)
        reviews = [json.loads(line) for line in
                   (self.root / 'private/reviews.jsonl').read_text().splitlines()]
        self.assertFalse(any(
            row.get('reviews') == [{'decision': 'execution_retryable'}] for row in reviews))

    def test_torn_state_during_final_read_blocks(self):
        fresh = self.snapshot(positions=[self.held_row()])
        # Torn read: the observation still claims flat while positions moved.
        fresh['entry_observation'] = self.observation()
        code, out = self.run_locked(fresh=fresh)
        self.assertEqual(code, 4, out)
        self.assertEqual(self.intents(), [])
        self.assertNotIn('place', self.broker_operations)

    def test_stale_final_evidence_bounds_block(self):
        fresh = self.snapshot()
        fresh['entry_observation'] = self.observation(
            started=NOW - dt.timedelta(seconds=400),
            finished=NOW - dt.timedelta(seconds=390))
        code, out = self.run_locked(fresh=fresh)
        self.assertEqual(code, 2, out)
        self.assertIn('entry_evidence_stale', out)
        self.assertEqual(self.intents(), [])

    def test_exact_dossier_retry_works_while_flat(self):
        code, out = self.run_locked()
        self.assertEqual(code, 0, out)
        rows = autotrader.read_jsonl(self.root / 'order_ledger.jsonl')
        self.assertIn('placed', [row['status'] for row in rows])
        self.assertEqual(len(self.intents()), 1)

    def test_retry_denied_after_new_holdings(self):
        # Dual approval exists but a deterministic spread rejection follows,
        # and the symbol is now held: the exact-dossier retry must not run.
        snapshot = self.snapshot()
        snapshot['quote'] = {'bid': 99.95, 'ask': 130.0,
                             'timestamp': _utc_text(NOW - dt.timedelta(seconds=1))}
        snapshot['entry_observation'] = self.observation()
        fresh = self.snapshot(positions=[self.held_row()])
        code, out = self.run_locked(snapshot=snapshot, fresh=fresh)
        self.assertEqual(code, 2, out)
        self.assertEqual(self.intents(), [])


class LegacyFloorTests(ExecutionCase):
    active = False

    def test_absent_activation_keeps_legacy_floor(self):
        # Legacy snapshots carry no entry observation at all.
        snapshot = self.snapshot()
        snapshot.pop('entry_observation')
        fresh = copy.deepcopy(snapshot)
        code, out = self.run_locked(snapshot=snapshot, fresh=fresh)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.reviewer_calls), 1)
        self.assertIn('place', self.broker_operations)

    def test_protective_sell_continuation_works(self):
        update = {'quantity': 3, 'symbol': 'ZSY', 'entry': 184.44}
        captured = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(autotrader, 'ROOT', self.root))
            stack.enter_context(patch.object(autotrader, 'runtime_blockers', return_value=[]))
            stack.enter_context(patch.object(autotrader, 'reconcile_pending_orders', return_value=[]))
            stack.enter_context(patch.object(autotrader, 'reconcile_managed_exits', return_value=[]))
            stack.enter_context(patch.object(autotrader, 'reconcile_managed_protection',
                                             return_value=[update]))
            stack.enter_context(patch.object(autotrader, '_broker_bridge',
                                             side_effect=AssertionError('must not reach snapshot')))
            stack.enter_context(contextlib.redirect_stdout(captured))
            code = autotrader._run_locked(self.ns())
        self.assertEqual(code, 0)
        self.assertIn('TRADE SELL 3 ZSY @ 184.44', captured.getvalue())


if __name__ == '__main__':
    unittest.main()
