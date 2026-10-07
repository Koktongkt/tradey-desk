import copy
from datetime import datetime, timezone
from decimal import Decimal as D
import unittest

from watchdog.types import OperationalSnapshot, BrokerSnapshot


def base_fixture(legs=(), broker_positions=None, planned='2026-10-09T20:00:00Z',
                 now='2026-10-07T16:00:00Z'):
    op = OperationalSnapshot({
        'candidates.jsonl': [dict(candidate_id='idea-a', dossier_hash='da', symbol='ABC')],
        'private/reviews.jsonl': [dict(dossier_hash='da', proposal_hash='pa', evidence_id='ea',
                                       reviews=[dict(decision='APPROVE')])],
        'private/order_intents.jsonl': [dict(client_order_id='parent',
            plan=dict(proposal_hash='pa', symbol='ABC', action='BUY',
                      planned_exit_at=planned, stop=9, target=12))],
    }, frozenset(), '2026-10-07T15:00:00Z', True, [])
    order = dict(id='broker-parent', client_order_id='parent', symbol='ABC', side='buy',
                 type='market', status='filled', qty=D('2'), filled_qty=D('2'),
                 filled_avg_price=D('10'), legs=list(legs))
    broker = BrokerSnapshot(dict(equity=D('50000')),
                            broker_positions
                            if broker_positions is not None
                            else [dict(symbol='ABC', qty=D('2'))],
                            [order], [], [], '2026-10-07T15:00:00Z', True,
                            dict(orders='complete', references='complete', activities='complete'))
    return op, broker, datetime.fromisoformat(now)


def stop_leg(ref='stop-1', leg_id='leg-stop', status='open', qty=D('2'), filled=D('0'),
             stop=D('9')):
    return dict(id=leg_id, client_order_id=ref, symbol='ABC', side='sell', type='stop',
                status=status, qty=qty, filled_qty=filled, stop_price=stop)


def target_leg(ref='target-1', leg_id='leg-target', status='open', qty=D('2'), filled=D('0'),
               limit=D('12')):
    return dict(id=leg_id, client_order_id=ref, symbol='ABC', side='sell', type='limit',
                status=status, qty=qty, filled_qty=filled, limit_price=limit)


def observe(op, broker, now):
    from watchdog.lineage import build_lineage
    from watchdog.mechanical import observe_positions
    return observe_positions(build_lineage(op, broker), broker, now)


class MechanicalTests(unittest.TestCase):
    def test_horizon_expiry_reported_without_any_input_mutation(self):
        op, broker, now = base_fixture(planned='2026-10-07T15:30:00Z')
        before = copy.deepcopy((op, broker))
        observations = observe(op, broker, now)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]['horizon_status'], 'horizon_expired')
        self.assertEqual((op, broker), before)

    def test_partial_entry_and_partial_exit_are_observed(self):
        entry = dict(id='broker-parent', client_order_id='parent', symbol='ABC', side='buy',
                     type='market', status='partially_filled', qty=D('3'), filled_qty=D('2'),
                     filled_avg_price=D('10'))
        legs = [stop_leg(qty=D('2'))]
        op, broker, now = base_fixture(legs=legs)
        op.streams['private/order_intents.jsonl'][0]['plan']['qty'] = 3
        # Replace the parent order with the partial-fill version.
        broker.orders[0] = entry
        observations = observe(op, broker, now)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]['entry_quantity'], D('2'))
        self.assertEqual(observations[0]['remaining_quantity'], D('2'))
        # Partial exit: stop leg already filled 1 of 2.
        legs[0]['filled_qty'] = D('1')
        broker.orders[0]['legs'] = [legs[0]]
        observations = observe(op, broker, now)
        self.assertEqual(observations[0]['remaining_quantity'], D('1'))

    def test_valid_oco_pair_covers_quantity_once_not_twice(self):
        op, broker, now = base_fixture(legs=[stop_leg(), target_leg()])
        observations = observe(op, broker, now)
        self.assertEqual(observations[0]['protection_status'], 'covered')
        self.assertEqual(observations[0]['protection_coverage_quantity'], D('2'))

    def test_duplicate_nested_leg_does_not_add_coverage(self):
        legs = [stop_leg(), stop_leg(leg_id='leg-stop-dup')]
        op, broker, now = base_fixture(legs=legs)
        observations = observe(op, broker, now)
        self.assertEqual(observations[0]['protection_status'], 'covered')
        self.assertEqual(observations[0]['protection_coverage_quantity'], D('2'))

    def test_cancelled_stop_reports_unprotected_without_repair(self):
        op, broker, now = base_fixture(legs=[stop_leg(status='canceled')])
        before = copy.deepcopy((op, broker))
        observations = observe(op, broker, now)
        self.assertEqual(observations[0]['protection_status'], 'unprotected')
        self.assertEqual(observations[0]['protection_coverage_quantity'], D('0'))
        self.assertIn('protection_order_cancelled', observations[0]['reasons'])
        self.assertEqual((op, broker), before)

    def test_expired_protection_is_reported(self):
        op, broker, now = base_fixture(legs=[stop_leg(status='expired')])
        observations = observe(op, broker, now)
        self.assertEqual(observations[0]['protection_status'], 'unprotected')
        self.assertIn('protection_order_expired', observations[0]['reasons'])

    def test_mismatched_protection_quantity_is_reported(self):
        op, broker, now = base_fixture(legs=[stop_leg(qty=D('1'))])
        observations = observe(op, broker, now)
        self.assertEqual(observations[0]['protection_status'], 'partial')
        self.assertEqual(observations[0]['protection_coverage_quantity'], D('1'))
        self.assertIn('protection_quantity_mismatch', observations[0]['reasons'])

    def test_concurrent_quantity_change_reported_never_repaired(self):
        legs = [stop_leg(qty=D('2'), filled=D('2')), target_leg(qty=D('2'), filled=D('2')),
                stop_leg(ref='stop-x', leg_id='leg-x', qty=D('2'), filled=D('2'))]
        op, broker, now = base_fixture(legs=legs)
        before = copy.deepcopy((op, broker))
        observations = observe(op, broker, now)
        self.assertEqual(observations[0]['quantity_status'], 'concurrent_quantity_change')
        self.assertIn('concurrent_quantity_change', observations[0]['reasons'])
        self.assertEqual((op, broker), before)

    def test_legacy_holdings_are_reported_and_excluded_from_managed_totals(self):
        op, broker, now = base_fixture(
            broker_positions=[dict(symbol='ABC', qty=D('2')), dict(symbol='XYZ', qty=D('5'))])
        from watchdog.lineage import build_lineage
        from watchdog.mechanical import aggregate_exposure, observe_positions
        lineage = build_lineage(op, broker)
        observations = observe_positions(lineage, broker, now)
        aggregate = aggregate_exposure(observations, broker)
        self.assertEqual(aggregate['managed_invested_value'], D('20'))
        self.assertEqual([h['symbol'] for h in aggregate['legacy_holdings']], ['XYZ'])
        self.assertTrue(all(h['attributed'] is False for h in aggregate['legacy_holdings']))

    def test_missing_protection_ref_and_invalid_horizon_stay_unknown(self):
        op, broker, now = base_fixture(legs=[stop_leg()], planned='not-a-time')
        from watchdog.lineage import build_lineage
        lineage = build_lineage(op, broker)
        lineage.positions[0]['protective_client_order_ids'] = ['gone']
        from watchdog.mechanical import observe_positions
        observations = observe_positions(lineage, broker, now)
        self.assertEqual(observations[0]['protection_status'], 'unknown')
        self.assertIn('protection_ref_missing', observations[0]['reasons'])
        self.assertEqual(observations[0]['horizon_status'], 'unknown')
        self.assertIn('horizon_invalid', observations[0]['reasons'])

    def test_missing_planned_exit_without_session_evidence_stays_unknown(self):
        op, broker, now = base_fixture()
        del op.streams['private/order_intents.jsonl'][0]['plan']['planned_exit_at']
        observations = observe(op, broker, now)
        self.assertEqual(observations[0]['horizon_status'], 'unknown')
        self.assertIn('horizon_missing', observations[0]['reasons'])

    def test_naive_now_is_rejected(self):
        op, broker, _ = base_fixture()
        with self.assertRaises(ValueError):
            observe(op, broker, datetime(2026, 10, 7, 16))

    def test_aggregate_uses_only_verified_value_with_labeled_denominators(self):
        from watchdog.mechanical import aggregate_exposure
        from watchdog.lineage import build_lineage
        from watchdog.mechanical import observe_positions
        # Discrepancy: broker shows 3 shares, managed owns 2.
        op, broker, now = base_fixture(legs=[stop_leg()],
                                       broker_positions=[dict(symbol='ABC', qty=D('3'))])
        lineage = build_lineage(op, broker)
        observations = observe_positions(lineage, broker, now)
        aggregate = aggregate_exposure(observations, broker)
        self.assertEqual(aggregate['managed_invested_value'], D('0'))
        self.assertEqual([p['position_id'] for p in aggregate['excluded_positions']], ['parent'])
        self.assertEqual(aggregate['denominators']['sleeve_equity'], None)
        self.assertEqual(aggregate['classification'], 'unknown')

    def test_aggregate_weights_use_labeled_managed_denominator(self):
        from watchdog.mechanical import aggregate_exposure
        from watchdog.lineage import build_lineage
        from watchdog.mechanical import observe_positions
        op, broker, now = base_fixture(legs=[stop_leg()])
        lineage = build_lineage(op, broker)
        observations = observe_positions(lineage, broker, now)
        aggregate = aggregate_exposure(observations, broker)
        self.assertEqual(aggregate['denominators']['managed_invested_value'], D('20'))
        self.assertEqual(aggregate['positions'][0]['weight_within_managed'], D('1'))
        self.assertEqual(aggregate['positions'][0]['weight_denominator'], 'managed_invested_value')
        self.assertEqual(aggregate['positions'][0]['weight_vs_sleeve_equity'], None)
        self.assertEqual(aggregate['positions'][0]['sleeve_denominator'], 'sleeve_equity_pending')

    def test_account_equity_is_secondary_and_separately_labeled(self):
        from watchdog.mechanical import aggregate_exposure
        from watchdog.lineage import build_lineage
        from watchdog.mechanical import observe_positions
        op, broker, now = base_fixture(legs=[stop_leg()])
        lineage = build_lineage(op, broker)
        observations = observe_positions(lineage, broker, now)
        aggregate = aggregate_exposure(observations, broker)
        self.assertEqual(aggregate['account_equity_secondary'], D('50000'))
        self.assertNotIn('equity', aggregate)


if __name__ == '__main__':
    unittest.main()
