"""Pure accounting contract fixtures: no operational I/O or network."""
import unittest
from decimal import Decimal as D
from copy import deepcopy
from watchdog import accounting
from watchdog.types import BrokerSnapshot, LineageResult

START = '2026-10-01T20:00:00+00:00'
END = '2026-10-06T20:00:00+00:00'


def fixture():
    activities = [dict(id='buy', activity_type='FILL', order_id='entry', symbol='AAA', side='buy', qty=D(2), price=D(100), transaction_time='2026-10-02T15:00:00+00:00'),
                  dict(id='sell', activity_type='FILL', order_id='exit', symbol='AAA', side='sell', qty=D(1), price=D(110), transaction_time='2026-10-05T15:00:00+00:00')]
    for row in activities:
        row['provenance'] = {k: 'get_account_activities.' + k for k in row}
    fills = [dict(activity_id=a['id'], broker_order_id=a['order_id'], side=a['side'], quantity=a['qty'], notional=a['qty']*a['price'], timestamp=a['transaction_time']) for a in activities]
    position = dict(position_id='idea', symbol='AAA', ownership='verified', remaining_quantity=D(1), stop=D(90), fills=fills,
                    fill_observations=[dict(broker_order_id='entry', cumulative_quantity=D(2), cumulative_notional=D(200), trusted=True)])
    mark = dict(symbol='AAA', qty=D(1), current_price=D(105), market_value=D(105), provenance=dict(current_price='get_all_positions.current_price', qty='get_all_positions.qty', market_value='get_all_positions.market_value'))
    coverage = {k: 'complete' for k in ('activities', 'fees', 'distribution', 'corporate_actions', 'account_cashflows', 'positions', 'account')}
    coverage['interval'] = dict(start='2026-09-30T00:00:00+00:00', end='2026-10-07T00:00:00+00:00')
    broker = BrokerSnapshot(dict(equity=D(50000), cash=D(40000), provenance=dict(equity='get_account_info.equity', cash='get_account_info.cash')), [mark], [], activities, [], END, True, coverage)
    lineage = LineageResult([position], [], dict(status='complete'), [])
    baseline = dict(version='v1', mode='inception', at=START, initial_capital='10000', inception_at=START, opening_positions=[],
                    provenance='approved_strategy_allocation', coverage={k: dict(start=START, end=END, provenance='verified_history_inventory') for k in ('executions', 'fees', 'distribution', 'corporate_actions')}, adjustments=[])
    return lineage, broker, baseline


def rounded_fixture():
    from watchdog.lineage import build_lineage
    from watchdog.types import OperationalSnapshot
    _, broker, baseline = fixture()
    op = OperationalSnapshot({'candidates.jsonl': [dict(candidate_id='idea', dossier_hash='dossier', symbol='AAA')],
          'private/reviews.jsonl': [dict(dossier_hash='dossier', proposal_hash='proposal', evidence_id='evidence')],
          'private/order_intents.jsonl': [dict(client_order_id='parent', plan=dict(action='BUY', symbol='AAA', proposal_hash='proposal', stop='90'))]}, frozenset(), END, True, [])
    broker.orders = [dict(id='entry', client_order_id='parent', status='filled', symbol='AAA', side='buy', filled_qty=D(3), filled_avg_price=D('100.66666667'), provenance=dict(filled_qty='get_orders.filled_qty', filled_avg_price='get_orders.filled_avg_price'), legs=[dict(id='exit', client_order_id='exit-client', status='partially_filled', symbol='AAA', side='sell', filled_qty=D(1), filled_avg_price=D(110), provenance=dict(filled_qty='get_orders.filled_qty', filled_avg_price='get_orders.filled_avg_price'), legs=[])])]
    broker.coverage.update(orders='complete', references='complete')
    broker.activities[0]['qty'] = D(1)
    another = deepcopy(broker.activities[0])
    another.update(id='buy2', qty=D(2), price=D(101), transaction_time='2026-10-03T15:00:00+00:00')
    broker.activities.append(another)
    broker.positions[0].update(qty=D(2), market_value=D(210))
    baseline['average_price_precision'] = {'entry': dict(quantum='0.00000001', rounding='ROUND_HALF_EVEN', provenance='independently_verified_broker_average_contract')}
    lineage = build_lineage(op, broker)
    assert lineage.coverage['status'] == 'complete'
    return lineage, broker, baseline


class AccountingTests(unittest.TestCase):
    def test_normalized_market_value_contradiction_withholds_performance(self):
        from watchdog.broker import normalize_position
        lineage, broker, baseline = fixture()
        broker.positions = [normalize_position(dict(symbol='AAA', side='long', qty='1', avg_entry_price='100', current_price='105', market_value='999', cost_basis='100'))]
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertIsNone(result['marked_equity'])
        self.assertIn('broker_market_value_discrepancy', result['reasons'])

    def test_normalized_market_value_requires_provenance(self):
        lineage, broker, baseline = fixture()
        broker.positions[0]['provenance'].pop('market_value')
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertIsNone(result['return'])
        self.assertIn('mark_evidence_unknown', result['reasons'])

    def test_market_value_reconciles_same_symbol_ideas_in_aggregate(self):
        from watchdog.broker import normalize_position
        lineage, broker, baseline = fixture()
        other = deepcopy(lineage.positions[0])
        other['position_id'] = 'idea2'
        for fill in other['fills']:
            fill['activity_id'] += '2'
            fill['broker_order_id'] += '2'
        other['fill_observations'][0]['broker_order_id'] += '2'
        for activity in deepcopy(broker.activities):
            activity['id'] += '2'
            activity['order_id'] += '2'
            broker.activities.append(activity)
        lineage.positions.append(other)
        broker.positions = [normalize_position(dict(symbol='AAA', side='long', qty='2', avg_entry_price='100', current_price='105.12345678', market_value='210.24691356', cost_basis='200'))]
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertEqual(result['coverage']['status'], 'complete')
        self.assertEqual(result['managed_market_value'], D('210.24691356'))
        self.assertEqual([p['market_value'] for p in result['positions']], [D('105.12345678')]*2)
        broker.positions[0]['market_value'] += D('.00000001')
        self.assertIn('broker_market_value_discrepancy', accounting.account_strategy(lineage, broker, baseline, [])['reasons'])

    def test_account_flow_equivalent_offsets_and_both_boundaries_are_unknown(self):
        for day, instants in [('2026-10-01', ['2026-10-02T00:00:00+00:00', '2026-10-01T20:00:00-04:00']), ('2026-10-06', [START, START])]:
            for at in instants:
                _, broker, _ = fixture()
                broker.account['equity'] = D(51000)
                broker.activities.append(dict(id='deposit', activity_type='CSD', date=day, net_amount=D(1000), provenance={k: 'get_account_activities.'+k for k in ('id', 'date', 'net_amount')}))
                prior = [dict(account_baseline=dict(at=at, equity='50000', version='a1', provenance='audited_baseline', flow_coverage=dict(start=START, end=END, provenance='audited_inventory', date_basis=dict(timezone='America/New_York', provenance='verified_activity_date_contract'))))]
                result = accounting.account_overview(broker, prior)
                self.assertIsNone(result['return'])
                self.assertIn('account_flow_boundary_unknown', result['reasons'])

    def test_account_flow_date_basis_must_be_verified(self):
        _, broker, _ = fixture()
        prior = [dict(account_baseline=dict(at=START, equity='50000', version='a1', provenance='audited_baseline', flow_coverage=dict(start=START, end=END, provenance='audited_inventory')))]
        result = accounting.account_overview(broker, prior)
        self.assertIsNone(result['return'])
        self.assertIn('account_flow_date_basis_unknown', result['reasons'])

    def test_exact_proven_flow_time_resolves_boundaries(self):
        for day, when, expected in [('2026-10-01', '2026-10-01T21:00:00+00:00', D(1000)), ('2026-10-06', '2026-10-06T19:00:00+00:00', D(1000)), ('2026-10-06', '2026-10-06T21:00:00+00:00', D(0))]:
            _, broker, _ = fixture()
            broker.activities.append(dict(id='flow', activity_type='CSD', date=day, transaction_time=when, net_amount=D(1000), provenance={k: 'verified_activity.'+k for k in ('id', 'date', 'net_amount', 'transaction_time')}))
            prior = [dict(account_baseline=dict(at=START, equity='50000', version='a1', provenance='audited_baseline', flow_coverage=dict(start=START, end=END, provenance='audited_inventory', date_basis=dict(timezone='America/New_York', provenance='verified_activity_date_contract'))))]
            result = accounting.account_overview(broker, prior)
            self.assertEqual(result['net_external_flows'], expected)

    def test_real_lineage_rounded_average_preserves_exact_event_cash(self):
        lineage, broker, baseline = rounded_fixture()
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertEqual(result['coverage']['status'], 'complete')
        self.assertEqual(result['cash'], D(9808))
        self.assertEqual(result['marked_equity'], D(10018))
        self.assertEqual(result['realized_pnl'], D(10))
        self.assertEqual(result['positions'][0]['cost_basis'], D(202))
        self.assertEqual(sum(f['notional'] for f in lineage.positions[0]['fills'] if f['side'] == 'buy'), D(302))
        self.assertEqual(lineage.positions[0]['fill_observations'][0]['cumulative_notional'], D('302.00000001'))

    def test_rounded_average_without_verified_precision_is_unknown(self):
        lineage, broker, baseline = rounded_fixture()
        baseline.pop('average_price_precision')
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertEqual(result['coverage']['status'], 'unknown')
        self.assertIn('execution_precision_unknown', result['reasons'])

    def test_rounded_average_rejects_material_difference_and_missing_events(self):
        lineage, broker, baseline = rounded_fixture()
        for average in ('100.66666668', '100.67'):
            broker.orders[0]['filled_avg_price'] = D(average)
            lineage.positions[0]['fill_observations'][0]['cumulative_notional'] = D(average)*3
            result = accounting.account_strategy(lineage, broker, baseline, [])
            self.assertIn('execution_totals_discrepancy', result['reasons'])
            self.assertIsNone(result['marked_equity'])
        lineage, broker, baseline = rounded_fixture()
        lineage.positions[0]['fills'].pop(0)
        self.assertIn('execution_totals_discrepancy', accounting.account_strategy(lineage, broker, baseline, [])['reasons'])

    def test_verified_rounding_cell_ties_and_invalid_precision(self):
        policy = dict(quantum='.01', rounding='ROUND_HALF_EVEN', provenance='verified_contract')
        for exact, average, expected in [('100.005', '100.00', True), ('100.005', '100.01', False), ('100.015', '100.02', True), ('100.015000001', '100.01', False)]:
            self.assertEqual(accounting._rounded_average_matches(D(exact)*3, D(3), D(average), policy), expected)
        for bad in [dict(quantum='.01', rounding='ROUND_HALF_EVEN'), dict(quantum='.02', rounding='ROUND_HALF_EVEN', provenance='verified_contract'), dict(quantum='.01', rounding='unspecified', provenance='verified_contract')]:
            self.assertIsNone(accounting._rounded_average_matches(D(302), D(3), D('100.66666667'), bad))

    def test_fifo_partial_exit_and_idle_cash(self):
        lineage, broker, baseline = fixture()
        original = deepcopy((lineage, broker, baseline))
        self.assertIsNotNone(accounting, 'accounting module not implemented')
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertEqual(result['cash'], D('9910'))
        self.assertEqual(result['marked_equity'], D('10015'))
        self.assertEqual(result['realized_pnl'], D('10'))
        self.assertEqual(result['unrealized_pnl'], D('5'))
        self.assertEqual(result['return'], D('.0015'))
        self.assertEqual(result['conditional_planned_loss'], D(15))
        self.assertEqual(result['planned_loss_basis'], 'conditional_stop_geometry_not_guaranteed')
        self.assertEqual(result['coverage']['status'], 'complete')
        self.assertEqual(result['positions'][0]['weight_vs_sleeve_equity'], D(105)/D(10015))
        self.assertEqual((lineage, broker, baseline), original)
        self.assertIsInstance(result['marked_equity'], D)

    def test_prior_curve_needs_mark_provenance_not_only_complete_flag(self):
        lineage, broker, baseline = fixture()
        prior = [dict(at='2026-10-02T20:00:00+00:00', baseline_version='v1', marked_equity=D(20000), coverage=dict(status='complete'))]
        result = accounting.account_strategy(lineage, broker, baseline, prior)
        self.assertEqual(result['drawdown'], D(0))
        self.assertEqual(result['coverage']['mark_gaps'], 1)

    def test_session_dates_use_new_york_not_utc_calendar_day(self):
        lineage, broker, baseline = fixture()
        broker.captured_at = '2026-10-07T00:00:00+00:00'
        broker.coverage['interval']['end'] = '2026-10-08T00:00:00+00:00'
        for evidence in baseline['coverage'].values():
            evidence['end'] = broker.captured_at
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertEqual(result['observations'][-1]['date'], '2026-10-06')

    def test_source_flags_do_not_prove_inception_history(self):
        lineage, broker, baseline = fixture()
        baseline.pop('coverage')
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertIsNone(result['return'])
        self.assertIsNone(result['marked_equity'])
        self.assertIn('executions_coverage_unknown', result['reasons'])

    def test_unknown_fees_or_distributions_withhold_totals(self):
        for key in ('fees', 'distribution', 'corporate_actions'):
            lineage, broker, baseline = fixture()
            broker.coverage[key] = 'unknown'
            result = accounting.account_strategy(lineage, broker, baseline, [])
            self.assertIsNone(result['return'])
            self.assertIsNone(result['marked_equity'])
            self.assertIn(key + '_coverage_unknown', result['reasons'])

    def test_exclusive_broker_interval_must_enclose_baseline(self):
        lineage, broker, baseline = fixture()
        broker.coverage['interval']['start'] = START
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertIsNone(result['marked_equity'])
        self.assertIn('activity_interval_not_enclosing', result['reasons'])

    def test_cumulative_observations_never_become_events(self):
        lineage, broker, baseline = fixture()
        lineage.positions[0]['fills'] = []
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertIsNone(result['marked_equity'])
        self.assertIn('managed_quantity_discrepancy', result['reasons'])

    def test_duplicate_activity_deduplicated_but_conflict_rejected(self):
        lineage, broker, baseline = fixture()
        lineage.positions[0]['fills'].append(deepcopy(lineage.positions[0]['fills'][0]))
        self.assertEqual(accounting.account_strategy(lineage, broker, baseline, [])['cash'], D(9910))
        lineage.positions[0]['fills'][-1]['notional'] = D(201)
        self.assertIn('execution_identity_conflict', accounting.account_strategy(lineage, broker, baseline, [])['reasons'])

    def test_execution_needs_broker_activity_provenance(self):
        lineage, broker, baseline = fixture()
        broker.activities[0].pop('provenance')
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertIsNone(result['marked_equity'])
        self.assertIn('execution_evidence_unknown', result['reasons'])

    def test_missing_mark_is_gap_not_carried_forward(self):
        lineage, broker, baseline = fixture()
        broker.positions[0]['provenance'].pop('current_price')
        result = accounting.account_strategy(lineage, broker, baseline, [dict(marked_equity=D(10010))])
        self.assertIsNone(result['marked_equity'])
        self.assertIsNone(result['drawdown'])
        self.assertIn('mark_evidence_unknown', result['reasons'])
        self.assertEqual(result['coverage']['status'], 'unknown')
        self.assertNotIn('broker_market_value_discrepancy', result['reasons'])

    def test_negative_cash_and_oversell_are_errors_not_clipped(self):
        for negative_cash in (True, False):
            lineage, broker, baseline = fixture()
            fill = lineage.positions[0]['fills'][0 if negative_cash else 1]
            activity = broker.activities[0 if negative_cash else 1]
            if negative_cash:
                fill['notional'] = D(20000)
                activity['price'] = D(10000)
            else:
                fill['quantity'], fill['notional'] = D(3), D(330)
                activity['qty'] = D(3)
            result = accounting.account_strategy(lineage, broker, baseline, [])
            self.assertEqual(result['coverage']['status'], 'error')
            self.assertIsNone(result['marked_equity'])
            self.assertIn('negative_virtual_cash' if negative_cash else 'managed_exit_exceeds_entry', result['reasons'])

    def test_allocation_not_inferred_from_cap(self):
        lineage, broker, baseline = fixture()
        baseline['initial_capital'] = '20000'
        baseline['exposure_cap'] = '20000'
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertEqual(result['initial_capital'], D(10000))
        self.assertIsNone(result['return'])
        self.assertIn('baseline_invalid', result['reasons'])

    def test_explicit_dated_prospective_opening_marks(self):
        lineage, broker, baseline = fixture()
        baseline.update(mode='prospective', at='2026-10-05T20:00:00+00:00', opening_positions=[dict(position_id='idea', symbol='AAA', quantity='1', price='100', at='2026-10-05T20:00:00+00:00', provenance='verified_opening_mark_inventory')])
        baseline.pop('inception_at')
        for row in baseline['coverage'].values():
            row['start'] = baseline['at']
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertEqual(result['cash'], D(9900))
        self.assertEqual(result['marked_equity'], D(10005))
        self.assertEqual(result['return'], D('.0005'))
        self.assertIsNone(result['inception_return'])
        self.assertEqual(result['capital_label'], '10000 at baseline')
        baseline['opening_positions'][0].pop('provenance')
        self.assertIsNone(accounting.account_strategy(lineage, broker, baseline, [])['return'])

    def test_verified_dividend_and_fee_have_explicit_allocation(self):
        lineage, broker, baseline = fixture()
        for identity, kind, amount in [('div', 'DIV', '3'), ('fee', 'FEE', '-2')]:
            activity = dict(id=identity, activity_type=kind, symbol='AAA', date='2026-10-06', net_amount=D(amount))
            activity['provenance'] = {k: 'get_account_activities.' + k for k in activity}
            broker.activities.append(activity)
            baseline['adjustments'].append(dict(activity_id=identity, position_id='idea', kind='distribution' if kind == 'DIV' else 'fee', amount=amount, timestamp='2026-10-06T15:00:00+00:00', provenance='verified_exact_entitlement_allocation'))
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertEqual(result['cash'], D(9911))
        self.assertEqual(result['marked_equity'], D(10016))
        self.assertEqual(result['costs'], D(2))
        self.assertEqual(result['distributions'], D(3))
        baseline['adjustments'][0].pop('provenance')
        self.assertIsNone(accounting.account_strategy(lineage, broker, baseline, [])['return'])

    def test_unallocated_symbol_dividend_cannot_be_inferred(self):
        lineage, broker, baseline = fixture()
        broker.activities.append(dict(id='div', activity_type='DIV', symbol='AAA', date='2026-10-06', net_amount=D(3), provenance=dict(net_amount='get_account_activities.net_amount')))
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertIsNone(result['marked_equity'])
        self.assertIn('adjustment_allocation_unknown', result['reasons'])

    def test_verified_split_preserves_lot_basis(self):
        lineage, broker, baseline = fixture()
        lineage.positions[0]['remaining_quantity'] = D(2)
        broker.positions[0].update(qty=D(2), current_price=D('52.5'))
        broker.activities.append(dict(id='split', activity_type='SPLIT', symbol='AAA', date='2026-10-06', provenance=dict(id='get_account_activities.id', symbol='get_account_activities.symbol', date='get_account_activities.date')))
        baseline['adjustments'] = [dict(activity_id='split', position_id='idea', kind='split', ratio='2', timestamp='2026-10-06T14:00:00+00:00', provenance='issuer_verified_split_ratio_and_exact_lots')]
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertEqual(result['marked_equity'], D(10015))
        self.assertEqual(result['unrealized_pnl'], D(5))
        baseline['adjustments'][0].pop('ratio')
        self.assertIsNone(accounting.account_strategy(lineage, broker, baseline, [])['return'])

    def test_equity_curve_filters_gaps_and_other_baselines(self):
        lineage, broker, baseline = fixture()
        prior = [dict(at=START, baseline_version='v1', marked_equity=D(10000), mark_provenance='verified_stored_marks', coverage=dict(status='complete')),
                 dict(at='2026-10-02T20:00:00+00:00', baseline_version='v1', marked_equity=D(10100), mark_provenance='verified_stored_marks', coverage=dict(status='complete')),
                 dict(at='2026-10-05T20:00:00+00:00', baseline_version='v1', marked_equity=None, coverage=dict(status='unknown')),
                 dict(at=START, baseline_version='other', marked_equity=D(99999), coverage=dict(status='complete'))]
        result = accounting.account_strategy(lineage, broker, baseline, prior)
        self.assertEqual(result['drawdown'], D(10015)/D(10100)-1)
        self.assertEqual(result['coverage']['valid_mark_samples'], 3)
        self.assertEqual(result['coverage']['mark_gaps'], 1)
        self.assertEqual(len(result['observations']), 3)

    def test_legacy_gains_and_deposit_only_affect_account_view(self):
        lineage, broker, baseline = fixture()
        self.assertTrue(callable(getattr(accounting, 'account_overview', None)), 'account overview missing')
        broker.account['equity'] += D(2500)
        broker.account['cash'] += D(1000)
        broker.activities.append(dict(id='deposit', activity_type='CSD', net_amount=D(1000), date='2026-10-06', provenance=dict(net_amount='get_account_activities.net_amount', id='get_account_activities.id', date='get_account_activities.date')))
        strategy = accounting.account_strategy(lineage, broker, baseline, [])
        overview = accounting.account_overview(broker, [])
        self.assertEqual(strategy['marked_equity'], D(10015))
        self.assertEqual(strategy['initial_capital'], D(10000))
        self.assertEqual(overview['equity'], D(52500))
        self.assertEqual(overview['cash'], D(41000))
        self.assertIsNone(overview['return'])
        self.assertIsNone(overview['drawdown'])

    def test_account_return_requires_independent_baseline_and_cashflow_inventory(self):
        lineage, broker, baseline = fixture()
        self.assertTrue(callable(getattr(accounting, 'account_overview', None)), 'account overview missing')
        broker.account['equity'] = D(51500)
        activity = dict(id='deposit', activity_type='CSD', net_amount=D(1000), date='2026-10-05')
        activity['provenance'] = {k: 'get_account_activities.' + k for k in activity}
        broker.activities.append(activity)
        prior = [dict(account_baseline=dict(at=START, equity='50000', version='account-v1', provenance='verified_independent_account_baseline', flow_coverage=dict(start=START, end=END, provenance='verified_external_flow_inventory', date_basis=dict(timezone='America/New_York', provenance='verified_activity_date_contract'))))]
        result = accounting.account_overview(broker, prior)
        self.assertEqual(result['return'], D('.01'))
        self.assertEqual(result['net_external_flows'], D(1000))
        self.assertEqual(result['performance_method'], 'net_flow_adjusted_pnl_over_initial_equity_not_time_weighted')
        broker.complete = False
        broker.coverage['reasons'] = ['broker_snapshot_stale']
        self.assertIsNone(accounting.account_overview(broker, prior)['return'])
        broker.complete = True
        broker.coverage['account_cashflows'] = 'unknown'
        result = accounting.account_overview(broker, prior)
        self.assertIsNone(result['return'])
        self.assertEqual(result['equity'], D(51500))

    def test_cash_timeline_is_global_not_position_iteration_order(self):
        for overlap in (True, False):
            lineage, broker, baseline = fixture()
            broker.activities = []
            lineage.positions = []
            broker.positions = []
            for identity, closed, buy_day, sell_day in [('a', True, '02', '05' if overlap else '03'), ('b', False, '03' if overlap else '04', None)]:
                fills = []
                for side, day in [('buy', buy_day)] + ([('sell', sell_day)] if closed else []):
                    activity = dict(id=identity+side, order_id=identity+side, activity_type='FILL', symbol=identity.upper(), side=side, qty=D(1), price=D(8000), transaction_time=f'2026-10-{day}T15:00:00+00:00')
                    activity['provenance'] = {k: 'get_account_activities.' + k for k in activity}
                    broker.activities.append(activity)
                    fills.append(dict(activity_id=activity['id'], broker_order_id=activity['order_id'], side=side, quantity=D(1), notional=D(8000), timestamp=activity['transaction_time']))
                lineage.positions.append(dict(position_id=identity, symbol=identity.upper(), ownership='verified', remaining_quantity=D(0 if closed else 1), stop=D(7000), fills=fills))
                if not closed:
                    broker.positions.append(dict(symbol=identity.upper(), qty=D(1), current_price=D(8000), market_value=D(8000), provenance=dict(qty='get_all_positions.qty', current_price='get_all_positions.current_price', market_value='get_all_positions.market_value')))
            for order in (lineage.positions, list(reversed(lineage.positions))):
                lineage.positions = order
                result = accounting.account_strategy(lineage, broker, baseline, [])
                if overlap:
                    self.assertIn('negative_virtual_cash', result['reasons'])
                    self.assertIsNone(result['marked_equity'])
                else:
                    self.assertEqual(result['cash'], D(2000))
                    self.assertEqual(result['marked_equity'], D(10000))

    def test_broker_cumulative_totals_validate_but_never_replay_events(self):
        lineage, broker, baseline = fixture()
        lineage.positions[0]['fill_observations'][0]['cumulative_notional'] = D(201)
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertIsNone(result['return'])
        self.assertIn('execution_totals_discrepancy', result['reasons'])

    def test_fifo_multiple_entries_stays_with_exact_position(self):
        lineage, broker, baseline = fixture()
        activity = dict(id='buy2', activity_type='FILL', order_id='entry2', symbol='AAA', side='buy', qty=D(1), price=D(120), transaction_time='2026-10-03T15:00:00+00:00')
        activity['provenance'] = {k: 'get_account_activities.' + k for k in activity}
        broker.activities.append(activity)
        lineage.positions[0]['fills'].append(dict(activity_id='buy2', broker_order_id='entry2', side='buy', quantity=D(1), notional=D(120), timestamp=activity['transaction_time']))
        lineage.positions[0]['remaining_quantity'] = D(2)
        broker.positions[0].update(qty=D(2), market_value=D(210))
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertEqual(result['realized_pnl'], D(10))
        self.assertEqual(result['unrealized_pnl'], D(-10))
        self.assertEqual(result['marked_equity'], D(10000))

    def test_unsupported_corporate_action_never_fabricates_adjustment(self):
        lineage, broker, baseline = fixture()
        broker.activities.append(dict(id='reorg', activity_type='REORG', symbol='AAA', date='2026-10-06'))
        self.assertIsNone(accounting.account_strategy(lineage, broker, baseline, [])['return'])

    def test_empty_sleeve_retains_idle_cash_without_claiming_legacy_gains(self):
        lineage, broker, baseline = fixture()
        lineage.positions = []
        self.assertEqual(accounting.account_strategy(lineage, broker, baseline, [])['marked_equity'], D(10000))

    def test_incomplete_broker_split_can_be_resolved_only_by_exact_evidence(self):
        lineage, broker, baseline = fixture()
        lineage.positions[0]['remaining_quantity'] = D(2)
        broker.positions[0].update(qty=D(2), current_price=D('52.5'))
        broker.activities.append(dict(id='split', activity_type='SPLIT', symbol='AAA', date='2026-10-06', provenance=dict(id='get_account_activities.id', symbol='get_account_activities.symbol', date='get_account_activities.date')))
        broker.complete = False
        broker.coverage.update(corporate_actions='unknown', reasons=['corporate_actions_coverage_unknown'])
        baseline['adjustments'] = [dict(activity_id='split', position_id='idea', kind='split', ratio='2', timestamp='2026-10-06T14:00:00+00:00', provenance='issuer_verified_split_ratio_and_exact_lots')]
        self.assertEqual(accounting.account_strategy(lineage, broker, baseline, [])['marked_equity'], D(10015))
        broker.coverage['reasons'].append('broker_snapshot_stale')
        self.assertIsNone(accounting.account_strategy(lineage, broker, baseline, [])['return'])

    def test_lineage_fill_cannot_masquerade_as_cash_adjustment(self):
        lineage, broker, baseline = fixture()
        lineage.positions[0]['fills'].append(dict(kind='distribution', activity_id='fake', amount='1000', timestamp='2026-10-06T15:00:00+00:00'))
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertIsNone(result['return'])
        self.assertIn('execution_shape_invalid', result['reasons'])

    def test_missing_stop_does_not_withhold_equity(self):
        lineage, broker, baseline = fixture()
        lineage.positions[0]['stop'] = None
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertEqual(result['marked_equity'], D(10015))
        self.assertIsNone(result['conditional_planned_loss'])

    def test_geometry_does_not_depend_on_inception_accounting_coverage(self):
        lineage, broker, baseline = fixture()
        baseline.pop('coverage')
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertIsNone(result['marked_equity'])
        self.assertEqual(result['conditional_planned_loss'], D(15))
        self.assertEqual(result['planned_loss_basis'], 'conditional_stop_geometry_not_guaranteed')

    def test_prospective_requires_explicit_opening_inventory(self):
        lineage, broker, baseline = fixture()
        baseline.update(mode='prospective')
        baseline.pop('opening_positions')
        self.assertIn('baseline_invalid', accounting.account_strategy(lineage, broker, baseline, [])['reasons'])

    def test_split_retains_total_cost_without_repeating_unit_price_drift(self):
        lineage, broker, baseline = fixture()
        lineage.positions[0]['fills'] = lineage.positions[0]['fills'][:1]
        lineage.positions[0]['fills'][0].update(quantity=D(1), notional=D(100))
        lineage.positions[0]['fill_observations'][0].update(cumulative_quantity=D(1), cumulative_notional=D(100))
        lineage.positions[0]['remaining_quantity'] = D(3)
        broker.activities = broker.activities[:1]
        broker.activities[0]['qty'] = D(1)
        broker.positions[0].update(qty=D(3), current_price=D(35))
        broker.activities.append(dict(id='split3', activity_type='SPLIT', symbol='AAA', date='2026-10-06', provenance=dict(id='get_account_activities.id', symbol='get_account_activities.symbol', date='get_account_activities.date')))
        baseline['adjustments'] = [dict(activity_id='split3', position_id='idea', kind='split', ratio='3', timestamp='2026-10-06T14:00:00+00:00', provenance='issuer_verified_ratio')]
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertEqual(result['positions'][0]['cost_basis'], D(100))
        self.assertEqual(result['unrealized_pnl'], D(5))

    def test_account_observations_retained_without_cashflow_performance(self):
        _, broker, _ = fixture()
        result = accounting.account_overview(broker, [])
        self.assertEqual(result.get('equity_observations'), [dict(at=END, equity=D(50000), cash=D(40000), provenance=broker.account['provenance'])])
        self.assertIsNone(result['return'])

    def test_real_lineage_activity_contract_supplies_accounting_events(self):
        from watchdog.lineage import build_lineage
        from watchdog.types import OperationalSnapshot
        _, broker, baseline = fixture()
        op = OperationalSnapshot({'candidates.jsonl': [dict(candidate_id='idea', dossier_hash='dossier', symbol='AAA')],
              'private/reviews.jsonl': [dict(dossier_hash='dossier', proposal_hash='proposal', evidence_id='evidence')],
              'private/order_intents.jsonl': [dict(client_order_id='parent', plan=dict(action='BUY', symbol='AAA', proposal_hash='proposal', stop='90'))]}, frozenset(), END, True, [])
        broker.orders = [dict(id='entry', client_order_id='parent', symbol='AAA', side='buy', filled_qty=D(2), filled_avg_price=D(100), legs=[dict(id='exit', client_order_id='exit-client', symbol='AAA', side='sell', filled_qty=D(1), filled_avg_price=D(110), legs=[])])]
        broker.coverage.update(orders='complete', references='complete')
        broker.orders[0]['status'] = 'filled'
        broker.orders[0]['legs'][0]['status'] = 'partially_filled'
        lineage = build_lineage(op, broker)
        self.assertEqual(lineage.coverage['status'], 'complete')
        result = accounting.account_strategy(lineage, broker, baseline, [])
        self.assertEqual(result['cash'], D(9910))
        self.assertEqual(result['marked_equity'], D(10015))
