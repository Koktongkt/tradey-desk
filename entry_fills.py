"""Lightweight validated broker readback and idempotent entry-fill accounting.

Callers validate evidence before journaling; no broker authority lives here.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from durable_jsonl import append_jsonl, read_jsonl
from private_lineage import confirmed_fill_metadata

class EntryFillConflict(ValueError):
    """Persisted complete execution disagrees with current entry evidence."""


def _execution_time(value):
    # datetime truncates beyond microseconds; broker nanoseconds must not alias.
    match = re.fullmatch(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})', value)
    if match is None:
        raise ValueError('execution timestamp requires exact time and timezone')
    whole = dt.datetime.fromisoformat(match[1] + match[3].replace('Z', '+00:00'))
    return whole.astimezone(dt.timezone.utc), Decimal(match[2] or '0')


def validate_entry_replay(rows, plan, order, lineage=None):
    """Return whether this full entry exists; reject ambiguous/conflicting reuse.

    Observation metadata alone is not a complete entry. Historical raw keys stay
    authoritative when no execution timestamp was saved; changed keys in that
    legacy state cannot prove equivalence and must fail closed.
    """
    qty, price = float(order.get('filled_qty') or 0), float(order.get('filled_avg_price') or 0)
    ref = order.get('client_order_id')
    key = hashlib.sha256(json.dumps({'ref': ref, 'filled_at': order.get('filled_at'),
                                    'qty': str(qty), 'price': str(price)}, sort_keys=True).encode()).hexdigest() if ref else None
    metadata = confirmed_fill_metadata(order, lineage)
    matches = []
    for row in rows:
        keyed = bool(key and row.get('entry_fill_key') == key)
        complete = row.get('status') == 'filled' and bool(row.get('entry_fill_key'))
        linked = (bool(ref) and ref in (row.get('client_order_id'), row.get('parent_client_order_id'))
                  or bool(order.get('id')) and row.get('broker_order_id') == order['id'])
        if not keyed and not (complete and linked):
            continue
        try:
            valid = (complete and row.get('symbol') == plan['symbol']
                     and row.get('action') == plan['action']
                     and Decimal(str(row.get('quantity'))) == Decimal(str(qty))
                     and Decimal(str(row.get('entry'))) == Decimal(str(price)))
            for field, expected in (('symbol', plan['symbol']), ('side', plan['action'].lower())):
                if field in order:
                    valid = valid and order[field] == expected
            for field in ('client_order_id', 'broker_order_id'):
                if row.get(field) is not None:
                    valid = valid and row[field] == metadata.get(field)
            for field in ('parent_client_order_id', 'candidate_id', 'dossier_hash', 'proposal_hash'):
                if row.get(field) is not None and metadata.get(field) is not None:
                    valid = valid and row[field] == metadata[field]
            for field in ('cumulative_filled_quantity', 'cumulative_filled_notional'):
                if field in row:
                    valid = valid and Decimal(str(row[field])) == Decimal(metadata[field])
            if row.get('broker_filled_at') is not None:
                valid = valid and _execution_time(row['broker_filled_at']) == _execution_time(order.get('filled_at'))
            else:
                valid = valid and keyed
        except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
            valid = False
        if not valid:
            raise EntryFillConflict('entry_fill_identity_conflict')
        matches.append(row)
    if len(matches) > 1:
        raise EntryFillConflict('entry_fill_identity_ambiguous')
    return bool(matches)


def validate_batch_execution_ownership(orders):
    """Reject one execution claimed by multiple parents before any batch write.

    Legacy readbacks may omit a broker ID; an explicitly supplied ID still
    belongs to exactly one saved client parent, regardless of symbol or status.
    """
    parents, executions = set(), set()
    for order in orders:
        ref = order.get('client_order_id')
        if not isinstance(ref, str) or not ref or ref in parents:
            raise EntryFillConflict('entry_fill_identity_ambiguous')
        parents.add(ref)
        execution = order.get('id')
        if execution is None:
            continue
        if not isinstance(execution, str) or not execution or execution in executions:
            raise EntryFillConflict('entry_fill_identity_ambiguous')
        executions.add(execution)


def _journal_confirmed_fill_locked(path, plan, broker_order, lineage=None, *, now=None):
    if broker_order.get("status") != "filled":
        return
    qty = float(broker_order.get("filled_qty") or 0)
    entry = float(broker_order.get("filled_avg_price") or 0)
    if qty <= 0 or entry <= 0:
        return
    ref = broker_order.get("client_order_id")
    fill_key = hashlib.sha256(json.dumps({"ref": ref, "filled_at": broker_order.get("filled_at"), "qty": str(qty), "price": str(entry)}, sort_keys=True).encode()).hexdigest() if ref else None
    if validate_entry_replay(read_jsonl(path, strict=True), plan, broker_order, lineage):
        return
    append_jsonl(path, {"entry_fill_key": fill_key, "timestamp": now or dt.datetime.now(dt.timezone.utc).isoformat(), "symbol": plan["symbol"], "action": plan["action"], "entry": entry, "quantity": qty, "dollar_basis": round(entry * qty, 2), "stop": plan["stop"], "target": plan["target"], "horizon": plan["horizon"], "confidence": plan["confidence"], "thesis": plan["thesis"], "status": "filled", "broker_filled_at": broker_order.get("filled_at"), **confirmed_fill_metadata(broker_order, lineage)})


BROKER_CONFIRMED_ORDER_STATUSES = {"new", "accepted", "pending_new", "partially_filled", "held", "filled"}
NOTIFICATION_STATUSES = BROKER_CONFIRMED_ORDER_STATUSES | {"placing"}


def _notification_plan(plan, *, validate=True):
    """Pure common projection; broker binding and fill checks stay with readback."""
    action = str(plan.get("action") or "").upper()
    symbol = str(plan.get("symbol") or "").upper()
    try:
        quantity, limit_price, stop, target = (
            Decimal(str(plan.get(field))) for field in ("quantity", "limit_price", "stop", "target")
        )
    except Exception:
        return None
    if validate and (plan.get("order_type") != "limit" or action not in {"BUY", "SELL"}
            or not symbol.isalpha() or len(symbol) > 6
            or not quantity.is_finite() or quantity <= 0 or quantity != quantity.to_integral_value()
            or any(not value.is_finite() or value <= 0 for value in (limit_price, stop, target))):
        return None
    return action, symbol, quantity, limit_price, stop, target


def placing_notification_line(plan: dict[str, Any], broker_mode: str) -> str | None:
    """Return a safe pre-submission line for a validated paper limit plan."""
    if broker_mode != "paper" or not isinstance(plan, dict):
        return None
    fields = _notification_plan(plan)
    if fields is None:
        return None
    action, symbol, quantity, limit_price, stop, target = fields
    return (
        f"ORDER placing {action} {int(quantity)} {symbol} LIMIT {limit_price:.2f} "
        f"STOP {stop:.2f} TARGET {target:.2f} PAPER"
    )


TERMINAL_ENTRY_STATUSES = {"canceled", "expired"}


def exact_terminal_readback(ref, plan, broker_order):
    """Validated zero-fill terminal cancellation; never claims a fill."""
    if not isinstance(ref, str) or not ref or not isinstance(broker_order, dict):
        return False
    status = str(broker_order.get("status") or "").lower()
    fields = _notification_plan(plan, validate=False)
    if fields is None or status not in TERMINAL_ENTRY_STATUSES:
        return False
    action, symbol, quantity, limit_price, stop, target = fields
    try:
        broker_quantity = Decimal(str(broker_order.get("qty")))
        filled = Decimal(str(broker_order.get("filled_qty") or 0))
    except Exception:
        return False
    return (
        str(broker_order.get("client_order_id") or "") == ref
        and str(broker_order.get("symbol") or "").upper() == symbol
        and str(broker_order.get("side") or "").lower() == action.lower()
        and str(broker_order.get("type") or broker_order.get("order_type") or "").lower() == "limit"
        and str(broker_order.get("order_class") or "").lower() == "bracket"
        and broker_quantity == quantity and filled == 0
    )


def broker_order_notification_line(
    ref: str, plan: dict[str, Any], broker_order: dict[str, Any], broker_mode: str,
) -> tuple[str, str] | None:
    """Return a safe line and status only for an exactly bound paper readback."""
    if broker_mode != "paper" or not isinstance(ref, str) or not ref or not isinstance(broker_order, dict):
        return None
    status = str(broker_order.get("status") or "").lower()
    if status in TERMINAL_ENTRY_STATUSES and not exact_terminal_readback(ref, plan, broker_order):
        return None
    fields = _notification_plan(plan, validate=False)
    if fields is None:
        return None
    action, symbol, quantity, limit_price, stop, target = fields
    try:
        broker_quantity = Decimal(str(broker_order.get("qty")))
    except Exception:
        return None
    if (
        status not in BROKER_CONFIRMED_ORDER_STATUSES
        or plan.get("order_type") != "limit"
        or action not in {"BUY", "SELL"}
        or not symbol.isalpha() or len(symbol) > 6
        or str(broker_order.get("client_order_id") or "") != ref
        or str(broker_order.get("symbol") or "").upper() != symbol
        or str(broker_order.get("side") or "").lower() != action.lower()
        or str(broker_order.get("type") or broker_order.get("order_type") or "").lower() != "limit"
        or str(broker_order.get("order_class") or "").lower() != "bracket"
        or not quantity.is_finite() or quantity <= 0 or quantity != quantity.to_integral_value()
        or not broker_quantity.is_finite() or broker_quantity != quantity
        or any(not value.is_finite() or value <= 0 for value in (limit_price, stop, target))
    ):
        return None
    average_fill = None
    if status == "filled":
        try:
            filled_quantity = Decimal(str(broker_order.get("filled_qty")))
            average_fill = Decimal(str(broker_order.get("filled_avg_price")))
        except Exception:
            return None
        if (
            not filled_quantity.is_finite() or filled_quantity != quantity
            or not average_fill.is_finite() or average_fill <= 0
        ):
            return None
    line = (
        f"ORDER {status} {action} {int(quantity)} {symbol} LIMIT {limit_price:.2f} "
        f"STOP {stop:.2f} TARGET {target:.2f}"
    )
    if average_fill is not None:
        line += f" AVG {average_fill:.2f}"
    return line + " PAPER", status
