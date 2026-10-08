"""Shared observation contracts. Completeness never grants execution authority."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation


def money(value: object) -> Decimal:
    """Parse finite amounts; domain-specific sign/quantity rules belong to consumers."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('invalid monetary value')
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError('invalid monetary value') from error
    if not result.is_finite():
        raise ValueError('nonfinite monetary value')
    digits, exponent = result.as_tuple().digits, result.as_tuple().exponent
    # Finite Decimals may still carry absurd exponents/digit counts that would
    # later render as unrepresentable public amounts; bound the magnitude.
    if abs(exponent) > 999 or len(digits) + max(exponent, 0) > 200:
        raise ValueError('monetary magnitude out of range')
    return result


def aware_timestamp(value: object) -> datetime:
    """Validate ISO syntax and timezone, not freshness against an implicit clock."""
    if not isinstance(value, str):
        raise ValueError('invalid timestamp')
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('timestamp requires timezone')
    return result


def snapshot_time_reasons(value: object, *, now: datetime, max_age_seconds: float | None = None) -> list[str]:
    """Validate snapshot freshness relative to an explicitly supplied aware clock."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now requires timezone')
    if max_age_seconds is not None and (not money(max_age_seconds).is_finite() or max_age_seconds < 0):
        raise ValueError('invalid maximum age')
    try:
        age = (now - aware_timestamp(value)).total_seconds()
    except (ValueError, OverflowError):
        return ['snapshot_timestamp_invalid']
    if age < 0:
        return ['snapshot_timestamp_future']
    if max_age_seconds is not None and age > max_age_seconds:
        return ['snapshot_timestamp_stale']
    return []


@dataclass
class BrokerSnapshot:
    account: dict
    positions: list[dict]
    orders: list[dict]
    activities: list[dict]
    sessions: list[dict]
    captured_at: str
    complete: bool
    coverage: dict


@dataclass
class LineageResult:
    positions: list[dict]
    decisions: list[dict]
    coverage: dict
    reasons: list[str]


@dataclass
class RunObservation:
    run_id: str
    session_date: str
    mode: str
    positions: list[dict]
    portfolio: dict
    attribution: dict
    thesis: list[dict]
    coverage: dict
    reasons: list[str]


@dataclass
class OperationalSnapshot:
    streams: dict[str, list[dict]]
    baseline_symbols: frozenset[str]
    captured_at: str
    complete: bool
    reasons: list[str]
