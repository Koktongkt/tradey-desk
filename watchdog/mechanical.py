"""Pure mechanical protection, horizon and exposure observation.

Consumes only the public Task 1-3 outputs (LineageResult, BrokerSnapshot).
No broker calls, no operational I/O, no mutation of inputs, no repair and no
execution authority: concurrent quantity changes and unexpected exits are
reported, never fixed.
"""
from datetime import datetime
from decimal import Decimal

from .types import BrokerSnapshot, LineageResult, aware_timestamp, money

ZERO = Decimal(0)
LIVE_ORDER_STATUSES = frozenset({'new', 'accepted', 'pending_new', 'pending_replace', 'held', 'open'})
STOP_TYPES = frozenset({'stop', 'stop_limit'})
TARGET_TYPES = frozenset({'limit', 'marketable_limit'})


TERMINAL_ORDER_STATUSES = {'canceled': 'protection_order_cancelled',
                           'expired': 'protection_order_expired',
                           'rejected': 'protection_order_rejected'}


def _flatten_orders(orders):
    flat, seen = [], set()
    stack = list(orders)
    while stack:
        order = stack.pop()
        identity = order.get('client_order_id')
        if identity not in seen:
            seen.add(identity)
            flat.append(order)
        stack.extend(order.get('legs') or [])
    return flat


def _leg_kind(order):
    kind = order.get('type')
    if kind in STOP_TYPES or 'stop_price' in order:
        return 'stop'
    if kind in TARGET_TYPES or 'limit_price' in order:
        return 'target'
    return 'unknown'


def _horizon_status(position, now, reasons):
    planned = position.get('planned_exit_at')
    if planned is None:
        if position.get('horizon') is not None:
            # Session-count horizons need a validated entry session; no exact
            # entry session evidence exists here, so the count stays unknown.
            reasons.append('horizon_session_entry_unknown')
        else:
            reasons.append('horizon_missing')
        return 'unknown'
    try:
        planned_at = aware_timestamp(planned)
    except ValueError:
        reasons.append('horizon_invalid')
        return 'unknown'
    return 'horizon_expired' if now > planned_at else 'active'


def _protection_status(position, broker, reasons):
    refs = position.get('protective_client_order_ids') or []
    remaining = position.get('remaining_quantity')
    if remaining is None:
        return 'unknown', None
    if remaining == 0:
        return 'not_required', ZERO
    flat = {order['client_order_id']: order for order in _flatten_orders(broker.orders)}
    live, unresolved, unrecognized = [], False, False
    for ref in dict.fromkeys(refs):
        order = flat.get(ref)
        if order is None:
            reasons.append('protection_ref_missing')
            unresolved = True
            continue
        status = order.get('status')
        if status in TERMINAL_ORDER_STATUSES:
            reasons.append(TERMINAL_ORDER_STATUSES[status])
        elif status in LIVE_ORDER_STATUSES:
            leg = dict(kind=_leg_kind(order),
                       remaining_quantity=money(order['qty']) - money(order.get('filled_qty', 0)),
                       stop_price=order.get('stop_price'), limit_price=order.get('limit_price'))
            if leg['remaining_quantity'] != remaining:
                reasons.append('protection_quantity_mismatch')
            live.append(leg)
        else:
            # A real broker status this module does not model: the protective
            # evidence is incomplete, so the state stays unknown instead of
            # being silently dropped as uncovered.
            reasons.append('protection_order_status_unknown')
            unrecognized = True
    # An unresolvable ref or an unrecognized status makes the protective set
    # incomplete: unknown stays unknown, no coverage claim may be combined
    # from the remaining legs.
    if unresolved or unrecognized:
        return 'unknown', None
    stops = [leg for leg in live if leg['kind'] == 'stop']
    targets = [leg for leg in live if leg['kind'] == 'target']
    if len(stops) > 1 and len({leg.get('stop_price') for leg in stops}) > 1:
        reasons.append('protection_replacement_conflict')
    if not stops:
        # 'protection_stop_missing' is only accurate when live evidence exists
        # but none of it is a stop. A resolved-but-not-live leg already carries
        # its terminal reason; the stop is not missing, it is dead.
        if refs and live:
            reasons.append('protection_stop_missing')
        return 'unprotected', ZERO
    stop_quantity = sum((leg['remaining_quantity'] for leg in stops), ZERO)
    # A matched stop/target OCO pair covering Q covers Q once: the target is
    # the same protective envelope, never an additional quantity. Duplicate
    # serialized legs were already deduplicated by client order identity.
    if targets:
        coverage = min(stop_quantity, sum((leg['remaining_quantity'] for leg in targets), ZERO))
    else:
        coverage = stop_quantity
    if coverage >= remaining:
        return 'covered', coverage
    if coverage > 0:
        return 'partial', coverage
    return 'unprotected', coverage


def _unexpected_exits(position, all_protective, broker, reasons):
    flat = _flatten_orders(broker.orders)
    protective = set(position.get('protective_client_order_ids') or [])
    # Exits Task 3 attributed to this position (fill_observations carry the
    # broker order identity) are managed activity, even when a replacement or
    # manual flow left them outside the protective ref list.
    attributed = {fo.get('broker_order_id') for fo in position.get('fill_observations') or []}
    for order in flat:
        if (order.get('side') == 'sell' and money(order.get('filled_qty', 0)) > 0
                and order['client_order_id'] not in protective
                and order['client_order_id'] not in all_protective
                and order.get('id') not in attributed
                and order.get('symbol') == position.get('symbol')):
            reasons.append('unexpected_exit')
            return


def observe_positions(lineage: LineageResult, broker: BrokerSnapshot, now: datetime) -> list[dict]:
    """Independent ownership/protection/horizon observation of managed positions."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now requires timezone')
    all_protective = {ref for position in lineage.positions
                      for ref in (position.get('protective_client_order_ids') or [])}
    observations = []
    for position in lineage.positions:
        reasons = [] if lineage.coverage.get('status') == 'complete' else ['lineage_coverage_unknown']
        quantity_status = 'consistent'
        remaining = position.get('remaining_quantity')
        if remaining is None:
            quantity_status = 'concurrent_quantity_change'
            reasons.append('concurrent_quantity_change')
        _unexpected_exits(position, all_protective, broker, reasons)
        protection_status, coverage = _protection_status(position, broker, reasons)
        horizon_status = _horizon_status(position, now, reasons)
        observations.append(dict(
            position_id=position.get('position_id'), candidate_id=position.get('candidate_id'),
            symbol=position.get('symbol'), entry_quantity=position.get('entry_quantity'),
            remaining_quantity=remaining, ownership_status=position.get('ownership'),
            quantity_status=quantity_status, protection_status=protection_status,
            protection_coverage_quantity=coverage, horizon_status=horizon_status,
            entry_notional=position.get('entry_notional'), exit_notional=position.get('exit_notional'),
            reasons=sorted(set(reasons))))
    return observations


def aggregate_exposure(positions: list[dict], broker: BrokerSnapshot) -> dict:
    """Aggregate only verified managed value; classifications stay unknown.

    Weights carry explicit denominator labels. Sleeve equity is supplied by a
    later task; until then that weight is None and labeled pending. Full
    account equity is a separately labeled secondary view, never strategy value.
    """
    verified = [p for p in positions if p.get('ownership_status') == 'verified']
    excluded = [dict(position_id=p.get('position_id'), symbol=p.get('symbol'),
                     reason='ownership_not_verified')
                for p in positions if p.get('ownership_status') != 'verified']
    managed_values = {p['position_id']: p.get('entry_notional', ZERO) - p.get('exit_notional', ZERO)
                      for p in verified}
    managed_total = sum(managed_values.values(), ZERO)
    rows = []
    for position in verified:
        value = managed_values[position['position_id']]
        rows.append(dict(position_id=position['position_id'], symbol=position.get('symbol'),
                         managed_value=value,
                         weight_within_managed=(value / managed_total) if managed_total else None,
                         weight_denominator='managed_invested_value',
                         weight_vs_sleeve_equity=None,
                         sleeve_denominator='sleeve_equity_pending'))
    managed_symbols = {p['symbol'] for p in verified if p.get('symbol')}
    observed = {}
    for row in broker.positions:
        symbol = row.get('symbol')
        observed[symbol] = observed.get(symbol, ZERO) + money(row.get('qty', 0))
    legacy = [dict(symbol=symbol, qty=qty, attributed=False)
              for symbol, qty in sorted(observed.items()) if symbol not in managed_symbols]
    return dict(
        managed_invested_value=managed_total,
        denominators=dict(managed_invested_value=managed_total, sleeve_equity=None),
        positions=rows, excluded_positions=excluded, legacy_holdings=legacy,
        account_equity_secondary=broker.account.get('equity'),
        classification='unknown',
        coverage=dict(status='unknown' if excluded or legacy else 'complete',
                      reasons=sorted({'aggregate_excluded_positions'} if excluded else set())))
