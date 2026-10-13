"""Durable authoritative earnings rejections, independent of review/retry state."""
import datetime as dt
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from sqlite_ledger import read_jsonl_readonly as read_jsonl


def setup_key(candidate: dict) -> str | None:
    """Bind symbol and exchange-local earnings/exit dates, not freshness.

    The blackout uses sessions, so changing seconds within the same exchange
    date cannot revive a blocked setup. Date-only values retain their stated
    date; timezone-less timestamps are invalid and fall back to exact matching.
    """
    symbol = candidate.get('symbol')
    if not isinstance(symbol, str) or not symbol:
        return None
    dates = []
    for field in ('earnings_event_at', 'planned_exit_at'):
        value = candidate.get(field)
        if not isinstance(value, str) or not value:
            return None
        try:
            if len(value) == 10:
                dates.append(dt.date.fromisoformat(value).isoformat())
            else:
                parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    return None
                dates.append(parsed.astimezone(ZoneInfo('America/New_York')).date().isoformat())
        except ValueError:
            return None
    return hashlib.sha256(json.dumps([symbol.upper(), *dates], separators=(',', ':')).encode()).hexdigest()


class SpendingPersistenceError(RuntimeError):
    """A real earnings rejection could not be durably recorded."""


def persist_rejection(ledger_path: Path, row: dict, append) -> None:
    """Keep durability failures distinct from broker/reviewer failures."""
    try:
        append(ledger_path, row)
    except Exception as error:
        raise SpendingPersistenceError('earnings_spending_persistence') from error


class SpendingStateError(RuntimeError):
    """Durable spending cannot be proved safe to read."""


def spending_rows(ledger_path: Path) -> list[dict]:
    try:
        rows = read_jsonl(ledger_path)
        for row in rows:
            reasons = row.get('reason')
            near = reasons == 'near_term_earnings' or isinstance(reasons, list) and 'near_term_earnings' in reasons
            if 'earnings_setup_key' in row and (row.get('status') != 'rejected' or not near
                    or row.get('stage') not in {'precheck', 'final_validation', 'broker_review'}):
                raise ValueError('invalid earnings spending marker')
            if row.get('status') != 'rejected' or not near:
                continue
            if 'dossier_hash' not in row and 'earnings_setup_key' not in row and 'stage' not in row:
                # Pre-lineage order records are audit history, not new spending
                # markers. Preserve them without guessing a dossier or banning
                # a ticker. Modern markers always carry stage + dossier fields.
                legacy_fields = ('client_order_id', 'evidence_id', 'symbol', 'timestamp')
                if (all(isinstance(row.get(field), str) and row[field] for field in legacy_fields)
                        and row.get('action') == 'BUY' and row.get('order_type') == 'limit'):
                    recorded = dt.datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
                    if recorded.tzinfo is not None:
                        continue
            if not isinstance(row.get('dossier_hash'), str) or not row['dossier_hash']:
                raise ValueError('missing earnings rejection identity')
            key = row.get('earnings_setup_key')
            if key is not None and (not isinstance(key, str) or len(key) != 64 or any(c not in '0123456789abcdef' for c in key)):
                raise ValueError('invalid earnings setup key')
        return rows
    except Exception as error:
        raise SpendingStateError('earnings_spending_state') from error


def is_spent(candidate: dict, ledger_path: Path, *, rows: list[dict] | None = None) -> bool:
    """Strict ledger read; absence is normal on a fresh install."""
    expected = candidate.get('dossier_hash')
    key = setup_key(candidate)
    rows = spending_rows(ledger_path) if rows is None else rows
    return any(row.get('status') == 'rejected'
               and (row.get('reason') == 'near_term_earnings'
                    or isinstance(row.get('reason'), list) and 'near_term_earnings' in row['reason'])
               and ((isinstance(expected, str) and bool(expected) and row.get('dossier_hash') == expected)
                    or key is not None and row.get('earnings_setup_key') == key) for row in rows)


def rejection(candidate: dict, stage: str, timestamp: str) -> dict:
    """Evidence of a real gate rejection, not an order or a reviewer outcome."""
    return {'timestamp': timestamp, 'status': 'rejected', 'reason': 'near_term_earnings',
            'stage': stage, 'symbol': candidate.get('symbol'),
            'candidate_id': candidate.get('candidate_id'), 'dossier_hash': candidate.get('dossier_hash'),
            'earnings_setup_key': setup_key(candidate)}
