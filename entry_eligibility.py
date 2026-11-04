"""Strict broker position observations and shared BUY eligibility.

Entry authorization is independent of economic sizing and of the dashboard/
portfolio projections: those consumers keep their original filtering and
never see this module's strictness. Every ambiguous or malformed fact is a
typed failure, never an empty portfolio or a flat permission. Evidence is
bounded: maximum 120 seconds of observation age from read start and maximum
120 seconds of monotonic read duration; future, naive and missing times fail
closed even when the quote is fresh.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from typing import Any

import pending_policy

SYMBOL = re.compile(r'[A-Z]{1,6}')


class EntryStateError(RuntimeError):
    """Broker entry evidence is malformed, incoherent or unverifiable."""


@dataclass(frozen=True)
class EntryDecision:
    outcome: str
    reason: str

    _OUTCOMES = frozenset({'eligible', 'held', 'pending', 'unknown'})

    def __post_init__(self):
        if self.outcome not in self._OUTCOMES:
            raise ValueError('invalid_entry_outcome')


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode()


def row_digest(row: dict) -> str:
    return sha256(_canonical(row)).hexdigest()


def _finite_positive(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(number) and number > 0


def _aware_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as error:
            raise EntryStateError('entry_evidence_invalid') from error
    else:
        raise EntryStateError('entry_evidence_invalid')
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        raise EntryStateError('entry_evidence_invalid')
    return stamp.astimezone(timezone.utc)


def strict_positions(normalized: Any) -> list[dict]:
    """Only the explicit successful normalized list is valid.

    Rows keep their original supported values. Malformed transport payloads
    and rows (wrong shape, unknown symbol, unsupported side, zero/negative/
    non-finite quantity, duplicates) raise instead of becoming [] — the old
    malformed-to-empty projection behavior never enters entry authorization.
    """
    if not isinstance(normalized, list) or any(not isinstance(row, dict)
                                               for row in normalized):
        raise EntryStateError('positions_unverified')
    validated: list[dict] = []
    seen: set[str] = set()
    for row in normalized:
        symbol = row.get('symbol')
        if not isinstance(symbol, str) or SYMBOL.fullmatch(symbol) is None:
            raise EntryStateError('positions_unverified')
        if row.get('side') != 'long':
            raise EntryStateError('positions_unverified')
        if not _finite_positive(row.get('qty')):
            raise EntryStateError('positions_unverified')
        try:
            digest = row_digest(row)
        except (ValueError, TypeError, OverflowError) as error:
            raise EntryStateError('positions_unverified') from error
        if digest in seen:
            raise EntryStateError('positions_unverified')
        seen.add(digest)
        validated.append(dict(row))
    return validated


def entry_observation(*, started_at: datetime, finished_at: datetime,
                      duration_seconds: float, positions: list[dict],
                      open_orders: list[dict]) -> dict:
    """Versioned bounded evidence over one trusted acquisition window."""
    started = _aware_utc(started_at)
    finished = _aware_utc(finished_at)
    if finished < started:
        raise EntryStateError('entry_evidence_invalid')
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (int, float)) \
            or not math.isfinite(duration_seconds) or duration_seconds < 0:
        raise EntryStateError('entry_evidence_invalid')
    if not isinstance(open_orders, list) or any(not isinstance(row, dict)
                                                for row in open_orders):
        raise EntryStateError('positions_unverified')
    validated = strict_positions(positions)
    return {
        'version': 1,
        'started_at': started.isoformat().replace('+00:00', 'Z'),
        'finished_at': finished.isoformat().replace('+00:00', 'Z'),
        'duration_seconds': float(duration_seconds),
        'positions_complete': True,
        'open_orders_complete': True,
        'position_count': len(validated),
        'open_order_count': len(open_orders),
        'position_digests': [row_digest(row) for row in validated],
        'open_order_digests': [row_digest(row) for row in open_orders],
        'positions': validated,
        'open_orders': [dict(row) for row in open_orders],
    }


def _unknown(reason: str) -> EntryDecision:
    return EntryDecision('unknown', reason)


def _evidence(observation: Any, *, now: datetime, max_age_seconds: int,
              max_read_seconds: int) -> dict:
    """Bounded, coherent evidence window or a typed unknown decision."""
    if not isinstance(observation, dict) or observation.get('version') != 1 \
            or observation.get('positions_complete') is not True \
            or observation.get('open_orders_complete') is not True \
            or not isinstance(observation.get('positions'), list) \
            or not isinstance(observation.get('open_orders'), list):
        raise EntryStateError('entry_evidence_unverified')
    started = _aware_utc(observation.get('started_at'))
    finished = _aware_utc(observation.get('finished_at'))
    if finished < started:
        raise EntryStateError('entry_evidence_invalid')
    if not isinstance(now, datetime) or now.tzinfo is None \
            or now.utcoffset() != timedelta(0):
        raise EntryStateError('entry_evidence_invalid')
    now = now.astimezone(timezone.utc)
    age = now - started
    if age < timedelta(0):
        raise EntryStateError('entry_evidence_future')
    if age > timedelta(seconds=max_age_seconds):
        raise EntryStateError('entry_evidence_stale')
    duration = observation.get('duration_seconds')
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) \
            or not math.isfinite(duration) or duration < 0:
        raise EntryStateError('entry_evidence_invalid')
    if duration > max_read_seconds:
        raise EntryStateError('entry_evidence_overlong')
    window = (finished - started).total_seconds()
    if window > max_read_seconds:
        raise EntryStateError('entry_evidence_stale')
    return observation


def evaluate_buy(symbol: str, snapshot: dict, *, pending_proof: pending_policy.Proof | None,
                 now: datetime, max_age_seconds: int = 120,
                 max_read_seconds: int = 120) -> EntryDecision:
    """Fail-closed BUY eligibility over one bounded broker observation.

    Order of authority: coherent bounded evidence, positive shares, unresolved
    entry obligations, then flat-complete permission. Quote freshness is never
    sufficient; missing or mismatched pending proof never authorizes entry.
    """
    if not isinstance(symbol, str) or SYMBOL.fullmatch(symbol.upper() or '') is None:
        return _unknown('entry_symbol_invalid')
    symbol = symbol.upper()
    if not isinstance(snapshot, dict):
        return _unknown('entry_evidence_unverified')
    try:
        observation = _evidence(snapshot.get('entry_observation'), now=now,
                                max_age_seconds=max_age_seconds,
                                max_read_seconds=max_read_seconds)
        positions = strict_positions(observation.get('positions'))
        if strict_positions(snapshot.get('positions')) != positions:
            raise EntryStateError('positions_unverified')
    except EntryStateError as error:
        return _unknown(str(error))
    # Any positive position, dust or not, and regardless of market value,
    # position cap or account cap, already blocks a new BUY.
    if any(row['symbol'] == symbol for row in positions):
        return EntryDecision('held', 'position_already_held')
    if pending_proof is None or not pending_policy.valid(pending_proof, snapshot):
        return EntryDecision('pending', 'pending_qualification_required')
    if any(row[1] == symbol for row in pending_proof.pending):
        return EntryDecision('pending', 'same_symbol_pending_entry')
    return EntryDecision('eligible', 'flat_complete')
