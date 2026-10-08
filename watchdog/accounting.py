"""Pure FIFO accounting over exact activity events, never cumulative observations.

Evidence dictionaries are private trusted-adapter inputs, not model assertions.
Completeness flags describe a requested sweep, not lifetime accounting coverage.
"""
from decimal import Decimal
from zoneinfo import ZoneInfo
from .types import BrokerSnapshot, LineageResult, aware_timestamp, money

ZERO = Decimal(0)
CAPITAL = Decimal(10000)


def _proven(row, fields):
    evidence = row.get('provenance', {})
    return isinstance(evidence, dict) and all(isinstance(evidence.get(k), str) and evidence[k] for k in fields)


def _covers(evidence, start, end):
    try:
        return (isinstance(evidence.get('provenance'), str) and bool(evidence['provenance'])
                and aware_timestamp(evidence['start']) <= start and aware_timestamp(evidence['end']) >= end)
    except (KeyError, ValueError, AttributeError, TypeError):
        return False


def _interval(broker, start, end):
    try:
        interval = broker.coverage['interval']
        # Alpaca activity bounds are exclusive and creation-time based. The
        # independently supplied coverage inventory must bridge event-time gaps.
        return aware_timestamp(interval['start']) < start and aware_timestamp(interval['end']) > end
    except (KeyError, ValueError, TypeError):
        return False


def account_strategy(lineage: LineageResult, broker: BrokerSnapshot, baseline: dict, prior_snapshots: list[dict]) -> dict:
    reasons, errors = [], []
    result: dict = dict(scope='actual_managed_strategy', initial_capital=CAPITAL, capital_label='10000 at baseline',
                  costs=None, distributions=None, baseline_mode=baseline.get('mode'), baseline_version=baseline.get('version'),
                  baseline_at=baseline.get('at'), at=broker.captured_at, cash=None, marked_equity=None,
                  realized_pnl=None, unrealized_pnl=None, managed_market_value=None, return_kind='unknown',
                  inception_return=None, drawdown=None, conditional_planned_loss=None,
                  planned_loss_basis='conditional_stop_geometry_not_guaranteed', positions=[], observations=[],
                  **{'return': None})
    try:
        start, end = aware_timestamp(baseline['at']), aware_timestamp(broker.captured_at)
        if (start > end or money(baseline['initial_capital']) != CAPITAL
                or not baseline.get('version') or not baseline.get('provenance')
                or baseline.get('mode') not in {'inception', 'prospective'}
                or not isinstance(baseline.get('opening_positions'), list)
                or (baseline.get('mode') == 'inception' and
                    (aware_timestamp(baseline['inception_at']) != start or baseline.get('opening_positions')))):
            raise ValueError('baseline_invalid')
    except (KeyError, ValueError, TypeError):
        reasons.append('baseline_invalid')
        start, end = None, None
    for key in ('executions', 'fees', 'distribution', 'corporate_actions'):
        if not start or not _covers(baseline.get('coverage', {}).get(key, {}), start, end):
            reasons.append(key + '_coverage_unknown')
        if key != 'executions' and broker.coverage.get(key) != 'complete':
            reasons.append(key + '_coverage_unknown')
    if not start or not _interval(broker, start, end):
        reasons.append('activity_interval_not_enclosing')
    if broker.coverage.get('activities') != 'complete' or not broker.complete:
        reasons.append('broker_coverage_unknown')
    if lineage.coverage.get('status') != 'complete':
        reasons.append('lineage_coverage_unknown')
    cash, realized, unrealized, value = CAPITAL, ZERO, ZERO, ZERO
    costs, distributions = ZERO, ZERO
    openings, adjustments, adjusted_ids = {}, {}, set()
    owners = {p['position_id']: p for p in lineage.positions}
    for opening in baseline.get('opening_positions', []):
        try:
            identity = opening['position_id']
            if (identity in openings or identity not in owners or not opening.get('provenance')
                    or opening['symbol'] != owners[identity]['symbol']
                    or aware_timestamp(opening['at']) != start
                    or money(opening['quantity']) <= 0 or money(opening['price']) <= 0):
                raise ValueError('opening_invalid')
            openings[identity] = [money(opening['quantity']), money(opening['price'])]
            cash -= money(opening['quantity']) * money(opening['price'])
        except (KeyError, ValueError, TypeError):
            reasons.append('opening_evidence_unknown')
    if cash < 0:
        errors.append('negative_virtual_cash')
    cash_moves = []
    opening_cash = cash
    for adjustment in baseline.get('adjustments', []):
        try:
            identity = adjustment['activity_id']
            owner = adjustment['position_id']
            when = aware_timestamp(adjustment['timestamp'])
            if (identity in adjusted_ids or owner not in owners or not adjustment.get('provenance')
                    or not start or not end or not start < when <= end):
                raise ValueError('adjustment_invalid')
            matches = [a for a in broker.activities if a.get('id') == identity]
            activity = matches[0] if len(matches) == 1 else {}
            if (not _proven(activity, ('id', 'symbol', 'date'))
                    or activity.get('symbol') != owners[owner]['symbol']
                    or activity.get('date') != when.date().isoformat()):
                raise ValueError('adjustment_invalid')
            kind = adjustment['kind']
            if kind == 'split':
                if activity.get('activity_type') != 'SPLIT' or money(adjustment['ratio']) <= 0:
                    raise ValueError('split_invalid')
            elif kind in {'distribution', 'fee'}:
                types = {'DIV', 'DIVCGL', 'DIVCGS', 'DIVROC', 'DIVTXEX'} if kind == 'distribution' else {'FEE', 'CFEE', 'DIVFEE'}
                amount = money(adjustment['amount'])
                if (activity.get('activity_type') not in types or not _proven(activity, ('net_amount',))
                        or money(activity['net_amount']) != amount
                        or (kind == 'fee' and amount > 0) or (kind == 'distribution' and amount < 0)):
                    raise ValueError('cash_adjustment_invalid')
            else:
                raise ValueError('adjustment_unsupported')
            adjusted_ids.add(identity)
            adjustments.setdefault(owner, []).append(adjustment)
        except (KeyError, ValueError, TypeError):
            reasons.append('adjustment_evidence_unknown')
    managed_symbols = {p['symbol'] for p in lineage.positions}
    # An account-wide fee cannot be attributed by ticker. Withhold until an
    # explicit exact allocation is supplied (including exclusions via inventory).
    for activity in broker.activities:
        kind = activity.get('activity_type', '')
        if kind == 'FILL' or kind in {'CSD', 'CSW', 'JNLC', 'ACATC'}:
            continue
        try:
            day = activity.get('date')
            in_period = bool(start and end and start.date().isoformat() <= day <= end.date().isoformat())
        except TypeError:
            in_period = True
        if in_period and (activity.get('symbol') in managed_symbols or kind in {'FEE', 'CFEE'}):
            if activity.get('id') not in adjusted_ids:
                reasons.append('adjustment_allocation_unknown')
    action_ids = {a.get('id') for a in broker.activities if a.get('activity_type') in
                  {'ACATS', 'JNLS', 'MA', 'NC', 'REO', 'REORG', 'SPIN', 'SPLIT', 'FOPT'}}
    if (action_ids and action_ids <= adjusted_ids and start and end
            and _covers(baseline.get('coverage', {}).get('corporate_actions', {}), start, end)
            and broker.coverage.get('activities') == 'complete'
            and set(broker.coverage.get('reasons', [])) == {'corporate_actions_coverage_unknown'}):
        # Resolve this specific adapter limitation only; stale/other failures,
        # unverified ownership and missing independent interval evidence remain.
        reasons = [r for r in reasons if r not in {'corporate_actions_coverage_unknown', 'broker_coverage_unknown'}]
    rows, seen, activities, totals = [], {}, {}, {}
    for activity in broker.activities:
        identity = activity.get('id')
        if identity in activities and activities[identity] != activity:
            errors.append('execution_identity_conflict')
        activities[identity] = activity
    for position in lineage.positions:
        if position.get('ownership') != 'verified':
            reasons.append('ownership_unknown')
            continue
        opening = openings.get(position['position_id'])
        lots = [[opening[0], opening[0] * opening[1]]] if opening else []
        raw_fills = position.get('fills', [])
        if any('kind' in f for f in raw_fills):
            reasons.append('execution_shape_invalid')
            continue
        fills = raw_fills + adjustments.get(position['position_id'], [])
        try:
            fills = sorted(fills, key=lambda f: (aware_timestamp(f['timestamp']), f.get('activity_id', '')))
            for fill in fills:
                when = aware_timestamp(fill['timestamp'])
                if baseline.get('mode') == 'prospective' and start and when <= start:
                    continue
                if fill.get('kind'):
                    if fill['kind'] == 'split':
                        ratio = money(fill['ratio'])
                        # Store remaining TOTAL lot cost, not a repeating
                        # per-share price. Splits change quantity, not basis.
                        for lot in lots:
                            lot[0] *= ratio
                    else:
                        amount = money(fill['amount'])
                        cash_moves.append((when, amount, fill['activity_id']))
                        if fill['kind'] == 'fee':
                            costs -= amount
                        else:
                            distributions += amount
                    continue
                identity = fill['activity_id']
                if identity in seen:
                    if seen[identity] != (position['position_id'], fill):
                        errors.append('execution_identity_conflict')
                    continue
                seen[identity] = (position['position_id'], fill)
                activity = activities.get(identity, {})
                fields = ('id', 'order_id', 'symbol', 'side', 'qty', 'price', 'transaction_time')
                qty, notional = money(fill['quantity']), money(fill['notional'])
                if (qty <= 0 or notional <= 0 or fill['side'] not in {'buy', 'sell'}
                        or activity.get('activity_type') != 'FILL' or not _proven(activity, fields)
                        or activity.get('order_id') != fill['broker_order_id']
                        or activity.get('symbol') != position['symbol'] or activity.get('side') != fill['side']
                        or money(activity['qty']) != qty or money(activity['price']) * qty != notional
                        or aware_timestamp(activity['transaction_time']) != aware_timestamp(fill['timestamp'])):
                    reasons.append('execution_evidence_unknown')
                    continue
                when = aware_timestamp(fill['timestamp'])
                if not start or not start <= when <= end:
                    reasons.append('execution_outside_baseline')
                    continue
                if fill['side'] == 'buy':
                    lots.append([qty, notional])
                    cash_moves.append((when, -notional, identity))
                else:
                    cash_moves.append((when, notional, identity))
                    basis, left = ZERO, qty
                    while left and lots:
                        take = min(left, lots[0][0])
                        allocated = lots[0][1] if take == lots[0][0] else lots[0][1] * take / lots[0][0]
                        basis += allocated
                        lots[0][1] -= allocated
                        left -= take
                        lots[0][0] -= take
                        if not lots[0][0]:
                            lots.pop(0)
                    if left:
                        errors.append('managed_exit_exceeds_entry')
                    realized += notional - basis
            qty = sum((lot[0] for lot in lots), ZERO)
            if position.get('remaining_quantity') is None or qty != money(position['remaining_quantity']):
                errors.append('managed_quantity_discrepancy')
            totals[position['symbol']] = totals.get(position['symbol'], ZERO) + qty
            matching = [p for p in broker.positions if p['symbol'] == position['symbol']]
            mark = matching[0] if len(matching) == 1 else {}
            if qty and (broker.coverage.get('positions') != 'complete' or not _proven(mark, ('current_price', 'qty'))
                        or money(mark.get('current_price', 0)) <= 0):
                reasons.append('mark_evidence_unknown')
                continue
            price = money(mark.get('current_price', 0))
            market_value = qty * price
            basis = sum((lot[1] for lot in lots), ZERO)
            value += market_value
            unrealized += market_value - basis
            rows.append(dict(position_id=position['position_id'], symbol=position['symbol'], quantity=qty,
                             market_value=market_value, cost_basis=basis, mark_at=broker.captured_at,
                             mark_provenance=mark.get('provenance', {}).get('current_price')))
        except (KeyError, ValueError, TypeError):
            reasons.append('accounting_input_invalid')
    cash = opening_cash
    # Shared virtual cash must follow execution time across every position.
    # Equal-time debits precede credits conservatively; no invented funding.
    for _, amount, _ in sorted(cash_moves):
        cash += amount
        if cash < 0:
            errors.append('negative_virtual_cash')
    if baseline.get('mode') == 'inception':
        for position in lineage.positions:
            for observation in position.get('fill_observations', []):
                try:
                    matches = [fill for owner, fill in seen.values() if owner == position['position_id']
                               and fill['broker_order_id'] == observation['broker_order_id']]
                    qty = sum((money(f['quantity']) for f in matches), ZERO)
                    notional = sum((money(f['notional']) for f in matches), ZERO)
                    if qty != money(observation['cumulative_quantity']) or notional != money(observation['cumulative_notional']):
                        errors.append('execution_totals_discrepancy')
                except (KeyError, ValueError, TypeError):
                    reasons.append('execution_totals_unknown')
    for symbol, qty in totals.items():
        matching = [p for p in broker.positions if p.get('symbol') == symbol]
        observed = money(matching[0]['qty']) if len(matching) == 1 else ZERO if not matching else None
        if qty != observed:
            errors.append('broker_quantity_discrepancy')
    reasons = sorted(set(reasons + errors))
    if not reasons:
        equity = cash + value
        if equity <= 0:
            errors.append('nonpositive_equity')
            reasons.append('nonpositive_equity')
        else:
            for row in rows:
                row['weight_vs_sleeve_equity'] = row['market_value'] / equity
            result.update(cash=cash, marked_equity=equity, realized_pnl=realized, unrealized_pnl=unrealized,
                          managed_market_value=value, positions=rows,
                          return_kind='total_return', costs=costs, distributions=distributions,
                          inception_return=(equity / CAPITAL - 1) if baseline.get('mode') == 'inception' else None,
                          **{'return': equity / CAPITAL - 1})
    result['conditional_planned_loss'] = _planned_geometry(lineage, broker)
    result['valuation_basis'] = 'broker_snapshot'
    result['mark_provenance'] = ({row['position_id']: row['mark_provenance'] for row in rows if row['quantity']}
                                  or {'cash_only_baseline': baseline.get('provenance')}) if result['marked_equity'] is not None else None
    observations, gaps = _marked_curve(prior_snapshots, result, CAPITAL)
    result['observations'] = observations
    result['drawdown'] = _drawdown(observations) if result['marked_equity'] is not None else None
    result.update(reasons=reasons, coverage=dict(status='error' if errors else 'unknown' if reasons else 'complete',
                  managed_positions=len(lineage.positions), execution_events=len(seen),
                  valid_mark_samples=len(observations), mark_gaps=gaps))
    return result


def _planned_geometry(lineage, broker):
    if lineage.coverage.get('status') != 'complete' or broker.coverage.get('positions') != 'complete':
        return None
    total, quantities = ZERO, {}
    try:
        for position in lineage.positions:
            if position.get('ownership') != 'verified' or position.get('remaining_quantity') is None:
                return None
            qty = money(position['remaining_quantity'])
            if qty < 0:
                return None
            quantities[position['symbol']] = quantities.get(position['symbol'], ZERO) + qty
            if not qty:
                continue
            marks = [m for m in broker.positions if m['symbol'] == position['symbol']]
            if len(marks) != 1 or not _proven(marks[0], ('qty', 'current_price')):
                return None
            price, stop = money(marks[0]['current_price']), money(position.get('stop'))
            if price <= 0 or stop <= 0:
                return None
            total += qty * max(price - stop, ZERO)
        for symbol, qty in quantities.items():
            marks = [m for m in broker.positions if m['symbol'] == symbol]
            observed = money(marks[0]['qty']) if len(marks) == 1 else ZERO if not marks else None
            if qty != observed:
                return None
        return total
    except (ValueError, KeyError, TypeError):
        return None


def _marked_curve(prior, current, initial):
    """Do not interpolate. Same-baseline valid observations only."""
    observations, gaps, seen = [], 0, {}
    start = current.get('baseline_at')
    if not start:
        return [], 0
    try:
        start_time, end_time = aware_timestamp(start), aware_timestamp(current['at'])
    except (ValueError, TypeError, KeyError):
        return [], 0
    for row in prior + [current]:
        if row.get('baseline_version') != current.get('baseline_version'):
            continue
        try:
            at = aware_timestamp(row['at'])
            if not start_time <= at <= end_time:
                continue
            value = row.get('marked_equity')
            valid = ((row is current and value is not None) or
                     (row.get('coverage', {}).get('status') == 'complete' and value is not None and bool(row.get('mark_provenance'))))
            if not valid or money(value) <= 0:
                gaps += 1
                continue
            if at in seen and seen[at]['value'] != money(value):
                gaps += 1
                seen[at] = dict(at=row['at'], value=None)
                continue
            seen[at] = dict(at=row['at'], date=at.astimezone(ZoneInfo('America/New_York')).date().isoformat(), value=money(value), provenance='verified_marked_sleeve_snapshot')
        except (ValueError, KeyError, TypeError):
            gaps += 1
    # The dated analytical baseline is valid by construction, not a historical
    # account cap or reconstructed mark. Do not create intermediate values.
    if current.get('marked_equity') is not None and start_time not in seen:
        seen[start_time] = dict(at=start, date=start_time.astimezone(ZoneInfo('America/New_York')).date().isoformat(), value=initial, provenance='explicit_analytical_baseline')
    observations = [row for _, row in sorted(seen.items()) if row['value'] is not None]
    return observations, gaps


def _drawdown(observations):
    peak, worst = ZERO, ZERO
    for row in observations:
        value = money(row['value'])
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst if observations else None


def account_overview(broker: BrokerSnapshot, prior_snapshots: list[dict]) -> dict:
    """Secondary whole-account observations; explicitly non-time-weighted P&L.

    Independent account_baseline input lives in prior snapshots, never inferred
    from broker.last_equity or sleeve allocation. Unknown transfers fail closed.
    """
    reasons = []
    result: dict = dict(scope='full_account_secondary', at=broker.captured_at,
                       equity=None, cash=None, equity_observations=[], observations=[], drawdown=None,
                       net_external_flows=None, **{'return': None},
                       performance_method='net_flow_adjusted_pnl_over_initial_equity_not_time_weighted')
    try:
        if not _proven(broker.account, ('equity', 'cash')) or broker.coverage.get('account') != 'complete':
            raise ValueError('account_evidence_unknown')
        result.update(equity=money(broker.account['equity']), cash=money(broker.account['cash']),
                      provenance=dict(broker.account['provenance']))
    except (ValueError, KeyError, TypeError):
        reasons.append('account_evidence_unknown')
    raw = {}
    for row in prior_snapshots + [result]:
        if row.get('scope') != 'full_account_secondary' or not _proven(row, ('equity', 'cash')):
            continue
        try:
            at = aware_timestamp(row['at'])
            if at <= aware_timestamp(broker.captured_at):
                raw[at] = dict(at=row['at'], equity=money(row['equity']), cash=money(row['cash']), provenance=dict(row['provenance']))
        except (ValueError, KeyError, TypeError):
            continue
    result['equity_observations'] = [row for _, row in sorted(raw.items())]
    baselines = [row['account_baseline'] for row in prior_snapshots if isinstance(row.get('account_baseline'), dict)]
    try:
        if not baselines or any(row != baselines[0] for row in baselines):
            raise ValueError('account_baseline_unknown')
        baseline = baselines[0]
        start, end = aware_timestamp(baseline['at']), aware_timestamp(broker.captured_at)
        initial = money(baseline['equity'])
        if not baseline.get('version') or not baseline.get('provenance') or initial <= 0 or start > end:
            raise ValueError('account_baseline_unknown')
        if (not broker.complete or broker.coverage.get('reasons')
                or not _covers(baseline.get('flow_coverage', {}), start, end) or not _interval(broker, start, end)
                or broker.coverage.get('account_cashflows') != 'complete' or broker.coverage.get('activities') != 'complete'):
            raise ValueError('account_cashflows_unknown')
        flows, seen = ZERO, {}
        for activity in broker.activities:
            kind = activity.get('activity_type')
            if kind not in {'CSD', 'CSW', 'JNLC', 'ACATC', 'ACATS', 'JNLS'}:
                continue
            if kind not in {'CSD', 'CSW'}:
                raise ValueError('account_transfer_classification_unknown')
            if not _proven(activity, ('id', 'date', 'net_amount')):
                raise ValueError('account_cashflows_unknown')
            day = activity['date']
            if not start.date().isoformat() <= day <= end.date().isoformat():
                continue
            # A date-only flow on the opening day is ambiguous unless baseline
            # starts at midnight. No guessed before/after allocation.
            if day == start.date().isoformat() and (start.hour or start.minute or start.second):
                raise ValueError('account_flow_boundary_unknown')
            identity, amount = activity['id'], money(activity['net_amount'])
            if (kind == 'CSD' and amount < 0) or (kind == 'CSW' and amount > 0):
                raise ValueError('account_cashflow_sign_invalid')
            if identity in seen:
                if seen[identity] != activity:
                    raise ValueError('account_cashflow_conflict')
                continue
            seen[identity] = activity
            flows += amount
        if result['equity'] is not None:
            adjusted = result['equity'] - flows
            result.update(net_external_flows=flows, baseline_version=baseline['version'], baseline_at=baseline['at'],
                          **{'return': (adjusted - initial) / initial})
            current = dict(at=result['at'], baseline_at=baseline['at'], baseline_version=baseline['version'], marked_equity=adjusted)
            prior = [dict(at=r.get('at'), baseline_version=r.get('account_baseline_version'), marked_equity=r.get('flow_adjusted_equity'), mark_provenance=r.get('provenance', {}).get('equity'), coverage=r.get('coverage', {})) for r in prior_snapshots]
            curve, gaps = _marked_curve(prior, current, initial)
            result.update(flow_adjusted_equity=adjusted, account_baseline_version=baseline['version'], observations=curve, drawdown=_drawdown(curve), mark_gaps=gaps)
    except (ValueError, KeyError, TypeError) as error:
        reason = str(error)
        reasons.append(reason if reason in {'account_baseline_unknown', 'account_cashflows_unknown', 'account_transfer_classification_unknown', 'account_flow_boundary_unknown', 'account_cashflow_sign_invalid', 'account_cashflow_conflict'} else 'account_input_invalid')
    result.update(reasons=sorted(set(reasons)), coverage=dict(status='unknown' if reasons else 'complete',
                  valid_mark_samples=len(result['observations'])))
    return result
