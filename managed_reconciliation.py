"""Read-only broker reconciliation; only local journal/lifecycle writes are allowed."""
from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from decimal import Decimal
from zoneinfo import ZoneInfo

from durable_jsonl import append_jsonl, read_jsonl


class ReconciliationBlocked(RuntimeError):
    """Verified state cannot safely support another entry."""


ET = ZoneInfo("America/New_York")


def market_window_open(now: dt.datetime | None = None) -> bool:
    """Weekday 09:35-16:15 America/New_York, inclusive of the 16:15 close pass."""
    local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ET)
    if local.weekday() >= 5:
        return False
    minutes = local.hour * 60 + local.minute
    return 9 * 60 + 35 <= minutes <= 16 * 60 + 15


def read_rows(path):
    try:
        return read_jsonl(path, strict=True)
    except Exception as error:
        raise ReconciliationBlocked('managed_state_invalid') from error


def require(condition, code='managed_evidence_invalid'):
    if not condition:
        raise ReconciliationBlocked(code)


def number(value, zero=False):
    try:
        n = Decimal(str(value))
        require(n.is_finite() and (n >= 0 if zero else n > 0))
        return n
    except (ValueError, ArithmeticError) as error:
        raise ReconciliationBlocked('managed_evidence_invalid') from error


def timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        require(parsed.tzinfo is not None)
        return parsed
    except ValueError as error:
        raise ReconciliationBlocked('managed_evidence_invalid') from error


ACTIVE = {'new', 'accepted', 'pending_new', 'held'}
TERMINAL = {'canceled', 'expired', 'done_for_day', 'replaced', 'stopped', 'rejected', 'suspended', 'calculated'}


def validate_exit(order, plan, order_class):
    require(isinstance(order, dict))
    require(order.get('symbol') == plan['symbol'] and order.get('side') == 'sell'
            and order.get('position_intent') == 'sell_to_close'
            and order.get('order_class') == order_class
            and isinstance(order.get('client_order_id'), str) and bool(order['client_order_id']))
    require(number(order.get('qty')) == number(plan['quantity']))
    kind = order.get('type', order.get('order_type'))
    require(kind in {'limit', 'stop'})
    require(number(order.get('limit_price' if kind == 'limit' else 'stop_price')) == number(plan['target' if kind == 'limit' else 'stop']))
    status = order.get('status')
    require(status != 'partially_filled', 'managed_partial_exit_unsupported')
    require(status in ACTIVE | TERMINAL | {'filled'})
    filled = number(order.get('filled_qty'), zero=True)
    if status == 'filled':
        require(filled == number(plan['quantity']), 'managed_partial_exit_unsupported')
        number(order.get('filled_avg_price'))
        timestamp(order.get('filled_at'))
    else:
        require(filled == 0, 'managed_partial_exit_unsupported')


def exit_legs(intent, orders, registry):
    ref, plan = intent['client_order_id'], intent['plan']
    parent = orders[ref]
    require(parent.get('client_order_id') == ref and parent.get('symbol') == plan['symbol']
            and parent.get('side') == 'buy' and parent.get('position_intent') == 'buy_to_open'
            and parent.get('order_class') == 'bracket' and parent.get('status') == 'filled')
    require(number(parent.get('qty')) == number(plan['quantity']) == number(parent.get('filled_qty')))
    number(parent.get('filled_avg_price'))
    entered = timestamp(parent.get('filled_at'))
    legs = parent.get('legs')
    require(isinstance(legs, list) and len(legs) == 2)
    legs = list(legs)
    for leg in legs:
        validate_exit(leg, plan, 'bracket')
    for protection in registry:
        if protection['parent_client_order_id'] != ref:
            continue
        require(protection['symbol'] == plan['symbol'])
        for field in ('quantity', 'stop', 'target'):
            require(number(protection.get(field)) == number(plan[field]))
        timestamp(protection.get('registered_at'))
        replacement = orders[protection['protection_client_order_id']]
        require(replacement.get('client_order_id') == protection['protection_client_order_id'])
        require(replacement.get('time_in_force') == 'gtc')
        children = replacement.get('legs')
        require(isinstance(children, list) and len(children) == 1)
        require(replacement.get('type', replacement.get('order_type')) == 'limit')
        require(children[0].get('type', children[0].get('order_type')) == 'stop')
        for leg in [replacement] + children:
            validate_exit(leg, plan, 'oco')
            require(leg.get('time_in_force') == 'gtc')
        legs += [replacement] + children
    ids = [leg['client_order_id'] for leg in legs]
    require(len(set(ids)) == len(ids))
    for leg in legs:
        if leg['status'] == 'filled':
            require(timestamp(leg['filled_at']) >= entered)
    require(sum(leg['status'] == 'filled' for leg in legs) <= 1, 'managed_exit_ambiguous')
    return legs


def journal_quantities(journal):
    quantities = {}
    for row in journal:
        if row.get('status') != 'filled':
            continue
        require(row.get('action') in {'BUY', 'SELL'}, 'managed_journal_invalid')
        symbol = row.get('symbol')
        require(isinstance(symbol, str) and bool(symbol), 'managed_journal_invalid')
        q = number(row.get('quantity'))
        quantities[symbol] = quantities.get(symbol, Decimal(0)) + (q if row['action'] == 'BUY' else -q)
        require(quantities[symbol] >= 0, 'managed_journal_negative')
    return quantities


def check_quantities(positions, journal, baseline=()):
    require(isinstance(positions, list), 'managed_positions_unverified')
    expected = journal_quantities(journal)
    require(not (set(expected) & set(baseline)), 'managed_baseline_overlap')
    actual = {}
    for position in positions:
        require(isinstance(position, dict), 'managed_positions_unverified')
        symbol = position.get('symbol')
        require(isinstance(symbol, str) and bool(symbol) and symbol not in actual, 'managed_positions_unverified')
        require(position.get('side', 'long') == 'long', 'managed_position_reconciliation_failed')
        actual[symbol] = number(position.get('qty'))
    require(all(actual.get(s, Decimal(0)) == q for s, q in expected.items()), 'managed_position_reconciliation_failed')
    require(not (set(actual) - set(expected) - set(baseline)), 'managed_position_untracked')
    return expected


def flatten_open(orders):
    require(isinstance(orders, list) and len(orders) < 500, 'managed_open_orders_unverified')
    found = {}
    def visit(order):
        require(isinstance(order, dict), 'managed_open_orders_unverified')
        ref = order.get('client_order_id')
        require(isinstance(ref, str) and bool(ref), 'managed_open_orders_unverified')
        if ref in found:
            require(found[ref] == order, 'managed_open_orders_ambiguous')
        found[ref] = order
        children = order.get('legs', [])
        require(children is None or isinstance(children, list), 'managed_open_orders_unverified')
        for child in children or []:
            visit(child)
    for order in orders:
        visit(order)
    return found


def check_protection(snapshot, active, legs_by_parent, closing):
    opened = flatten_open(snapshot.get('open_orders'))
    allowed = set()
    for intent in active:
        ref = intent['client_order_id']
        if ref in closing:
            continue
        current = []
        represented = False
        for leg in legs_by_parent[ref]:
            if leg['status'] not in ACTIVE:
                continue
            leg_ref = leg['client_order_id']
            require(leg.get('time_in_force') == 'gtc', 'managed_protection_not_persistent')
            observed = opened.get(leg_ref)
            if observed is not None:
                require(observed.get('type', observed.get('order_type')) ==
                        leg.get('type', leg.get('order_type')), 'managed_protection_inconsistent')
                validate_exit(observed, intent['plan'], leg['order_class'])
                require(observed.get('status') in ACTIVE, 'managed_protection_missing')
                require(observed.get('time_in_force') == 'gtc', 'managed_protection_not_persistent')
                represented = True
            current.append(leg.get('type', leg.get('order_type')))
            allowed.add(leg_ref)
        require(represented, 'managed_protection_missing')
        require(sorted(current) == ['limit', 'stop'], 'managed_protection_missing_or_oversized')
    # No symbol-only exemption: every active exit must be a known linked leg.
    require(all(ref in allowed for ref, order in opened.items() if order.get('status') in ACTIVE), 'managed_open_order_unlinked')


def reconcile_detailed(root: Path, broker):
    """Shared reconciler core: read-only broker, local journal/lifecycle repair.

    Returns (newly_journaled_rows, verified_summary). Raises
    ReconciliationBlocked whenever state could not be verified.
    """
    root = Path(root)
    lock = root / '.managed_exit_reconciliation.lock'
    root.mkdir(parents=True, exist_ok=True)
    with lock.open('a+') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        ledger = read_rows(root / 'order_ledger.jsonl')
        journal = read_rows(root / 'trade_journal.jsonl')
        intents = read_rows(root / 'private/order_intents.jsonl')
        registry = read_rows(root / 'private/protection_orders.jsonl')
        latest = {r['client_order_id']: r for r in ledger if r.get('client_order_id')}
        for row in latest.values():
            if row.get('status') == 'closed':
                require(any(r.get('parent_client_order_id') == row['client_order_id'] and r.get('action') == 'SELL' for r in journal), 'managed_closed_without_fill')
        active = [i for i in intents if latest.get(i['client_order_id'], {}).get('status') == 'filled']
        refs = [i['client_order_id'] for i in active]
        refs += [r['protection_client_order_id'] for r in registry if r['parent_client_order_id'] in refs]
        snapshot = broker('reconciliation_snapshot', {'client_order_ids': refs})
        require(isinstance(snapshot.get('orders'), list) and len(snapshot['orders']) == len(refs))
        require(all(isinstance(o, dict) for o in snapshot['orders']))
        orders = {o.get('client_order_id'): o for o in snapshot['orders']}
        require(set(orders) == set(refs) and len(orders) == len(refs))
        updates = []
        legs_by_parent = {}
        for intent in active:
            ref = intent['client_order_id']
            plan = intent['plan']
            legs = exit_legs(intent, orders, registry)
            legs_by_parent[ref] = legs
            fills = [leg for leg in legs if leg['status'] == 'filled']
            if not fills:
                continue
            fill = fills[0]
            key = hashlib.sha256(f"{ref}|{fill['client_order_id']}|{fill['filled_at']}".encode()).hexdigest()
            updates.append(dict(timestamp=fill['filled_at'], symbol=plan['symbol'], action='SELL', entry=float(fill['filled_avg_price']), quantity=float(fill['filled_qty']), dollar_basis=float(Decimal(fill['filled_avg_price']) * Decimal(fill['filled_qty'])), stop=plan['stop'], target=plan['target'], status='filled', parent_client_order_id=ref, exit_client_order_id=fill['client_order_id'], closure_key=key, exit_reason='protective_stop' if fill['type'] == 'stop' else 'take_profit'))
        known = {r.get('closure_key') for r in journal}
        if updates:
            snapshot = broker('reconciliation_snapshot', {'client_order_ids': []})
        try:
            baseline = json.loads((root / 'private/broker_baseline.json').read_text())['preexisting_symbols']
            require(isinstance(baseline, list) and all(isinstance(s, str) and s for s in baseline), 'broker_baseline_invalid')
        except (OSError, ValueError, KeyError) as error:
            raise ReconciliationBlocked('broker_baseline_invalid') from error
        proposed_journal = journal + [row for row in updates if row['closure_key'] not in known]
        check_quantities(snapshot.get('positions'), proposed_journal, baseline)
        check_protection(snapshot, active, legs_by_parent, {r['parent_client_order_id'] for r in updates})
        written = []
        for row in updates:
            if row['closure_key'] not in known:
                append_jsonl(root / 'trade_journal.jsonl', row)
                written.append(row)
            append_jsonl(root / 'order_ledger.jsonl', dict(timestamp=row['timestamp'], client_order_id=row['parent_client_order_id'], status='closed', symbol=row['symbol'], action='SELL', quantity=row['quantity'], closure_key=row['closure_key'], exit_client_order_id=row['exit_client_order_id']))
        positions = {}
        for position in (snapshot.get('positions') or []):
            if isinstance(position, dict):
                positions[str(position.get('symbol'))] = str(position.get('qty'))
        summary = {
            'status': 'healthy',
            'verified': True,
            'captured_at': snapshot.get('captured_at'),
            'positions': positions,
            'open_orders': len(snapshot.get('open_orders') or []),
            'repaired': [row['exit_client_order_id'] for row in written],
        }
        return written, summary


def reconcile(root: Path, broker) -> list[dict]:
    return reconcile_detailed(root, broker)[0]


def register_protection(registry_path: Path, row: dict, broker) -> None:
    """Validate against a fresh broker readback, then durably register once.

    Every protective repair must flow through here: an unregistered replacement
    order cannot be reconciled later (no symbol-only recovery), so registration
    is mandatory audit. Idempotent for identical rows; conflicts fail closed.
    """
    require(isinstance(row, dict))
    for field in ('parent_client_order_id', 'protection_client_order_id', 'symbol', 'quantity', 'stop', 'target', 'registered_at'):
        require(field in row, 'registry_row_invalid')
    require(isinstance(row['parent_client_order_id'], str) and row['parent_client_order_id']
            and isinstance(row['protection_client_order_id'], str) and row['protection_client_order_id'])
    require(str(row['symbol']).isalpha())
    number(row['quantity'])
    number(row['stop'])
    number(row['target'])
    timestamp(row['registered_at'])
    try:
        snapshot = broker('reconciliation_snapshot', {'client_order_ids': [row['protection_client_order_id']]})
    except Exception as error:
        raise ReconciliationBlocked('registry_verification_unavailable') from error
    orders = snapshot.get('orders') if isinstance(snapshot, dict) else None
    require(isinstance(orders, list) and len(orders) == 1 and isinstance(orders[0], dict), 'registry_verification_invalid')
    order = orders[0]
    require(order.get('client_order_id') == row['protection_client_order_id'], 'registry_verification_invalid')
    require(order.get('symbol') == str(row['symbol']).upper()
            and order.get('side') == 'sell' and order.get('position_intent') == 'sell_to_close'
            and order.get('order_class') == 'oco' and order.get('time_in_force') == 'gtc', 'registry_verification_invalid')
    require(number(order.get('qty')) == number(row['quantity']), 'registry_verification_invalid')
    existing = read_rows(registry_path)
    for prior in existing:
        if prior.get('protection_client_order_id') == row['protection_client_order_id']:
            require(prior == row, 'registry_conflict')
            return
    require(not any(p.get('parent_client_order_id') == row['parent_client_order_id'] for p in existing), 'registry_conflict')
    append_jsonl(registry_path, row)


def default_bridge(operation: str, payload: dict | None = None) -> dict:
    """Read-only subprocess bridge to broker_mcp_bridge.py; retries reads only."""
    cmd = [os.environ.get('UV_BIN', '/usr/local/bin/uv'), 'run', '--with', 'fastmcp<4', 'python',
           str(Path(__file__).resolve().parent / 'broker_mcp_bridge.py'), operation]
    attempts = 2 if operation == 'reconciliation_snapshot' else 1
    result = None
    for attempt in range(1, attempts + 1):
        try:
            result = subprocess.run(cmd, input=json.dumps(payload or {}), text=True,
                                    capture_output=True, timeout=180, check=False)
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(cmd, 124, '', 'timeout')
        except OSError:
            result = subprocess.CompletedProcess(cmd, 127, '', 'launch_failure')
        if result.returncode != 0:
            continue
        try:
            decoded = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict) and decoded.get('error') in (None, '', False, {}):
            return decoded
    raise RuntimeError('broker_mcp_failure')


def cli(argv: list[str] | None = None, broker=None) -> int:
    """Reconciliation-only maintenance entry point. Never places orders."""
    import argparse
    parser = argparse.ArgumentParser(
        description='Read-only managed-position reconciliation with local journal/lifecycle repair. '
                    'Scheduled runs gate to weekdays 09:35-16:15 America/New_York; the single 16:15 '
                    'close pass is included, so the :05/:15/:25/:35/:45/:55 offsets at 16:05 is '
                    'intentionally excluded (no post-close pass).')
    parser.add_argument('--root', default=os.environ.get('TRADEY_ROOT', str(Path(__file__).resolve().parent)))
    parser.add_argument('--heartbeat', action='store_true', help='print a verified summary even when healthy')
    parser.add_argument('--scheduled', action='store_true', help='gate to the maintenance market window')
    args = parser.parse_args(argv)
    if args.scheduled and not market_window_open():
        return 0
    bridge = broker or default_bridge
    try:
        updates, summary = reconcile_detailed(Path(args.root), bridge)
    except ReconciliationBlocked as error:
        print(f"BLOCKER {error}")
        return 2
    except Exception:
        print("SYSTEM_FAILURE managed_reconciliation")
        return 4
    for row in updates:
        print(f"RECONCILIATION repaired {row['symbol']} {row['exit_client_order_id']}")
    if args.heartbeat:
        print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(cli())
