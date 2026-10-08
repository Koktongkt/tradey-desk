"""Monitoring-only SQLite snapshots and durable outbox; no transport or trading I/O.

Task8 supplies portfolio={strategy: account_strategy result, account: account_overview
result, benchmark: compare_benchmark result, exposure: aggregate_exposure result}.
coverage.captured_at is the trusted run timestamp (strategy.at is a fallback).
Thesis rows may add `baseline` from baseline_from_candidate for version retention.
read_report is a single coherent read transaction. pending_alerts returns ALL pending
rows, including older runs: a failed report/delivery must not strand prior alerts.
"""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, timezone
from decimal import Decimal
from typing import Any
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .types import RunObservation, aware_timestamp

SCHEMA = '''
CREATE TABLE thesis_versions(position_id TEXT NOT NULL, version TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(position_id,version,kind));
CREATE TABLE runs(run_id TEXT NOT NULL PRIMARY KEY, captured_at TEXT NOT NULL, session_date TEXT NOT NULL,
 mode TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE position_observations(run_id TEXT NOT NULL REFERENCES runs(run_id), position_id TEXT NOT NULL,
 payload TEXT NOT NULL, PRIMARY KEY(run_id,position_id));
CREATE TABLE portfolio_snapshots(run_id TEXT NOT NULL PRIMARY KEY REFERENCES runs(run_id), payload TEXT NOT NULL);
CREATE TABLE evidence_events(position_id TEXT NOT NULL, version TEXT NOT NULL, fingerprint TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(run_id),
 payload TEXT NOT NULL, PRIMARY KEY(position_id,version,fingerprint));
CREATE TABLE source_state(symbol TEXT NOT NULL, source TEXT NOT NULL, cutoff TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(run_id),
 PRIMARY KEY(symbol,source));
CREATE TABLE attribution_rows(run_id TEXT NOT NULL PRIMARY KEY REFERENCES runs(run_id), payload TEXT NOT NULL);
CREATE TABLE condition_state(condition_key TEXT NOT NULL PRIMARY KEY, status TEXT NOT NULL, severity INTEGER NOT NULL,
 generation INTEGER NOT NULL, last_alert_at TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(run_id));
CREATE TABLE alert_outbox(key TEXT NOT NULL PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id), payload TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','acknowledged')), receipt TEXT);
'''

# Compact, explicit private contract fields, never raw payloads/transcripts.
FIELDS = frozenset('''run_id session_date mode captured_at positions portfolio attribution thesis coverage reasons
position_id candidate_id symbol entry_quantity remaining_quantity ownership_status quantity_status protection_status
protection_coverage_quantity horizon_status entry_notional exit_notional status scope strategy account benchmark exposure
initial_capital capital_label costs distributions baseline_mode baseline_version baseline_at at cash marked_equity
realized_pnl unrealized_pnl managed_market_value return_kind inception_return drawdown conditional_planned_loss
planned_loss_basis return quantity market_value cost_basis weight_vs_sleeve_equity mark_provenance valuation_basis
valuation_provenance observations date value equity equity_observations net_external_flows performance_method
flow_adjusted_equity account_baseline_version provenance managed_positions execution_events valid_mark_samples mark_gaps
managed_invested_value denominators excluded_positions legacy_holdings attributed classification weight_within_managed
weight_denominator sleeve_denominator account_equity_secondary managed_value weight_vs_sleeve_equity sleeve_equity
strategy_return benchmark_return benchmark_equity strategy_drawdown benchmark_drawdown excess_total_return
excess_price_comparator comparator_kind comparison_kind sample_count pairs strategy_equity missing_strategy_dates
missing_benchmark_dates baseline_status coverage_status source_state cutoff events fingerprint criterion_id effect severity
confidence action fact urls published_at event_at retrieved_at primary kind baseline version summary catalyst description
assumptions breakers kpis risks proposed_enrichments approved id metric operator threshold dossier_hash coverage_url
checked_through sec issuer earnings exchange regulator executions fees distribution corporate_actions start end
actual research decisions shadow research_outcomes decision_outcomes shadow_outcomes count decision_id state
horizon_sessions dated_at forward_return excess traded return_1s_pct return_3s_pct return_5s_pct return_10s_pct
spy_return_1s_pct spy_return_3s_pct spy_return_5s_pct spy_return_10s_pct excess_1s_pct excess_3s_pct excess_5s_pct excess_10s_pct
strategy_baseline account_baseline opening_positions inception_at adjustments average_price_precision
activity_id broker_order_id side price timestamp amount ratio flow_coverage date_basis timezone quantum rounding mark_at
'''.split())


def compact(value: Any) -> Any:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError('nonfinite value')
        return str(value)
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            if k not in FIELDS:
                continue
            if k == 'mark_provenance' and isinstance(v, dict):
                result[k] = {identity: ref for identity, ref in v.items()
                             if isinstance(identity, str) and isinstance(ref, str)}
            elif k == 'average_price_precision' and isinstance(v, dict):
                result[k] = {identity: {field: compact(row[field]) for field in ('quantum', 'rounding', 'provenance') if field in row}
                    for identity, row in v.items() if isinstance(identity, str) and isinstance(row, dict)}
            elif k == 'approved':
                result[k] = False  # proposals never acquire authority on persistence
            elif k in {'fact', 'summary', 'description'} and isinstance(v, str):
                result[k] = v[:2000 if k == 'summary' else 1000]
            else:
                result[k] = compact(v)
        return result
    if isinstance(value, list):
        return [compact(v) for v in value]
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError('invalid observation value')


def dumps(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _path(db):
    db = Path(db)
    resolved = db.resolve()
    if resolved.name != 'monitoring.sqlite3' or resolved.parent.name != 'watchdog' or resolved.parent.parent.name != 'private':
        raise ValueError('monitoring_path_required')
    # Fixture paths must be explicit, not the live repository's private store.
    if 'test_artifacts' not in resolved.parts and resolved != Path(__file__).resolve().parents[1] / 'private/watchdog/monitoring.sqlite3':
        raise ValueError('isolated_monitoring_path_required')
    if resolved.exists() and resolved.stat().st_nlink != 1:
        raise ValueError('monitoring_hardlink_rejected')
    if db.absolute() != resolved:
        raise ValueError('monitoring_symlink_rejected')
    return resolved


@contextmanager
def _connection(db, write=False):
    path = _path(db)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
    conn = sqlite3.connect(str(path) if write else path.as_uri() + '?mode=ro', uri=not write, timeout=30)
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        tables = conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table'").fetchall()
        if version == 0 and not tables and write:
            for statement in SCHEMA.split(';'):
                if statement.strip():
                    conn.execute(statement)
            conn.execute('PRAGMA user_version=1')
        elif version != 1:
            raise ValueError('unsupported_monitoring_schema')
        elif {name: ' '.join(sql.split()) for name, sql in tables} != {
                statement.strip().split()[2].split('(')[0]: ' '.join(statement.split())
                for statement in SCHEMA.split(';') if statement.strip()}:
            raise ValueError('unsupported_monitoring_schema')
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _pending(conn):
    return [json.loads(row[0]) for row in conn.execute("SELECT payload FROM alert_outbox WHERE state='pending' ORDER BY rowid")]


def pending_alerts(db: Path) -> list[dict]:
    if not _path(db).exists():
        return []
    with _connection(db) as conn:
        return _pending(conn)


def commit_observation(db: Path, observation: RunObservation) -> list[dict]:
    report = compact(asdict(observation))
    at = report['coverage'].get('captured_at') or report['portfolio'].get('strategy', {}).get('at')
    at = aware_timestamp(at).astimezone(timezone.utc).isoformat(timespec='microseconds')
    date.fromisoformat(observation.session_date)
    if observation.mode not in {'mechanical', 'daily', 'fixture', 'smoke'} or not observation.run_id:
        raise ValueError('invalid run identity')
    ids = [p.get('position_id') for p in report['positions']]
    if any(not isinstance(p, str) or not p for p in ids) or len(ids) != len(set(ids)):
        raise ValueError('duplicate_or_missing_position_identity')
    payload = dumps(report)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    with _connection(db, True) as conn:
        previous = conn.execute('SELECT digest FROM runs WHERE run_id=?', (observation.run_id,)).fetchone()
        if previous:
            if previous[0] != digest:
                raise ValueError('run_identity_conflict')
            return _pending(conn)
        conn.execute('INSERT INTO runs VALUES (?,?,?,?,?,?)', (observation.run_id, at, observation.session_date, observation.mode, digest, payload))
        for p in report['positions']:
            conn.execute('INSERT INTO position_observations VALUES (?,?,?)', (observation.run_id, p['position_id'], dumps(p)))
        conn.execute('INSERT INTO portfolio_snapshots VALUES (?,?)', (observation.run_id, dumps(report['portfolio'])))
        conn.execute('INSERT INTO attribution_rows VALUES (?,?)', (observation.run_id, dumps(report['attribution'])))
        for field, identity in (('strategy_baseline', '__strategy__'), ('account_baseline', '__account__')):
            baseline = report['portfolio'].get(field)
            if baseline is not None:
                if not isinstance(baseline, dict) or not isinstance(baseline.get('version'), str) or not baseline['version']:
                    raise ValueError('accounting_baseline_version_required')
                _version(conn, identity, baseline['version'], field, baseline)
        _persist_theses(conn, report, at)
        latest = conn.execute('SELECT captured_at FROM runs WHERE run_id != ? ORDER BY captured_at DESC, rowid DESC LIMIT 1', (observation.run_id,)).fetchone()
        if not latest or aware_timestamp(at) >= aware_timestamp(latest[0]):
            for identity, kind, status, severity, symbol in _conditions(report):
                _transition(conn, observation.run_id, at, identity, kind, status, severity, symbol)
            if observation.mode == 'daily':
                _enqueue(conn, observation.run_id, dict(key='digest:' + observation.session_date,
                    kind='digest', status='complete' if report['coverage'].get('status') == 'complete' else 'unknown',
                    severity='info', at=at))
        return _pending(conn)


def _version(conn, position, version, kind, value):
    payload = dumps(value)
    old = conn.execute('SELECT payload FROM thesis_versions WHERE position_id=? AND version=? AND kind=?', (position, version, kind)).fetchone()
    if old and old[0] != payload:
        raise ValueError('thesis_version_conflict')
    conn.execute('INSERT OR IGNORE INTO thesis_versions VALUES (?,?,?,?)', (position, version, kind, payload))


def _persist_theses(conn, report, at):
    for t in report['thesis']:
        position, version = t.get('position_id'), t.get('baseline_version')
        if not isinstance(position, str) or not position:
            raise ValueError('thesis_position_required')
        baseline = t.get('baseline')
        if isinstance(baseline, dict) and version:
            if baseline.get('version') != version:
                raise ValueError('baseline_version_mismatch')
            proposals = baseline.pop('proposed_enrichments', [])
            _version(conn, position, version, 'supplied', baseline)
            for proposed in proposals:
                proposed['approved'] = False
                _version(conn, position, proposed['version'], 'proposal', proposed)
            baseline['proposed_enrichments'] = proposals
        for event in t.get('events', []):
            if not version or not event.get('fingerprint') or event.get('baseline_version') != version:
                raise ValueError('event_identity_required')
            # Identity is the underlying event, not URL or run; retained compact
            # provenance is private. Repeated classifications do not duplicate it.
            old = conn.execute('SELECT payload FROM evidence_events WHERE position_id=? AND version=? AND fingerprint=?',
                (position, version, event['fingerprint'])).fetchone()
            if old:
                prior = json.loads(old[0])
                if any(prior.get(k) != event.get(k) for k in ('fact', 'event_at', 'kind')):
                    raise ValueError('event_identity_conflict')
                event['urls'] = sorted(set(prior.get('urls', []) + event.get('urls', [])))
                conn.execute('UPDATE evidence_events SET payload=? WHERE position_id=? AND version=? AND fingerprint=?',
                    (dumps(event), position, version, event['fingerprint']))
            else:
                conn.execute('INSERT INTO evidence_events VALUES (?,?,?,?,?)',
                    (position, version, event['fingerprint'], report['run_id'], dumps(event)))
        for source, state in t.get('source_state', {}).items():
            if t.get('coverage', {}).get(source, {}).get('status') != 'complete':
                continue
            cutoff = state.get('cutoff')
            try:
                when = aware_timestamp(cutoff)
            except ValueError:
                continue
            if when > aware_timestamp(at):
                raise ValueError('source_cutoff_future')
            old = conn.execute('SELECT cutoff FROM source_state WHERE symbol=? AND source=?', (t['symbol'], source)).fetchone()
            if not old or when > aware_timestamp(old[0]):
                conn.execute('INSERT OR REPLACE INTO source_state VALUES (?,?,?,?)', (t['symbol'], source, cutoff, report['run_id']))


def read_source_state(db: Path) -> dict:
    """Task8 passes this exact symbol/source/cutoff mapping to monitor_theses."""
    if not _path(db).exists():
        return {}
    with _connection(db) as conn:
        result = {}
        for symbol, source, cutoff in conn.execute('SELECT symbol,source,cutoff FROM source_state'):
            result.setdefault(symbol, {})[source] = dict(cutoff=cutoff)
        return result


def _conditions(report):
    mappings = {
        'protection': ('protection_status', {'covered': 0, 'not_required': 0, 'partial': 2, 'unprotected': 3, 'unknown': 1}),
        'quantity': ('quantity_status', {'consistent': 0, 'concurrent_quantity_change': 2, 'discrepancy': 2}),
        'ownership': ('ownership_status', {'verified': 0, 'discrepancy': 2, 'unknown': 1}),
        'horizon': ('horizon_status', {'active': 0, 'horizon_expired': 2, 'unknown': 1}),
    }
    for p in report['positions']:
        for kind, (field, states) in mappings.items():
            status = p.get(field)
            if kind == 'quantity' and any(r in {'unexpected_exit', 'protection_quantity_mismatch'}
                    for r in p.get('reasons', []) if isinstance(r, str)):
                status = 'discrepancy'
            # Invalid/missing state is a gap, never an implicit recovery.
            status = status if status in states else 'unknown'
            yield p['position_id'] + ':' + kind, kind, status, states.get(status, 1), p.get('symbol')
    for t in report['thesis']:
        if not t.get('position_id'):
            continue
        status = t.get('status')
        states = {'no_material_change_observed': 0, 'baseline_incomplete': 1,
                  'coverage_incomplete': 1, 'review_required': 2, 'potential_thesis_break': 3}
        status = status if status in states else 'coverage_incomplete'
        yield t['position_id'] + ':thesis', 'thesis', status, states[status], t.get('symbol')
        if 'coverage_status' in t:
            coverage = t.get('coverage_status')
            coverage = coverage if coverage in {'complete', 'coverage_incomplete'} else 'coverage_incomplete'
            yield t['position_id'] + ':sources', 'coverage', coverage, 0 if coverage == 'complete' else 1, t.get('symbol')
        for event in t.get('events', []):
            if event.get('effect') not in {'weakens', 'unclear', 'potential-break'}:
                continue
            severity = {'low': 1, 'medium': 2, 'high': 2, 'critical': 3}.get(event.get('severity'), 1)
            identity = dumps([t['position_id'], t.get('baseline_version'), event['fingerprint'], event.get('criterion_id')])
            yield identity + ':evidence', 'evidence', event['effect'], severity, t.get('symbol')
    status = report['coverage'].get('status')
    status = status if status in {'complete', 'unknown', 'incomplete', 'error'} else 'unknown'
    yield 'run:coverage', 'coverage', status, 0 if status == 'complete' else 1, None


def _enqueue(conn, run, alert):
    conn.execute("INSERT OR IGNORE INTO alert_outbox VALUES (?,?,?,'pending',NULL)", (alert['key'], run, dumps(alert)))


def _transition(conn, run, at, identity, kind, status, severity, symbol):
    previous = conn.execute('SELECT status,severity,generation,last_alert_at FROM condition_state WHERE condition_key=?', (identity,)).fetchone()
    generation = previous[2] if previous else 0
    last = previous[3] if previous else at
    changed = previous is None or previous[0] != status or previous[1] != severity
    recovery = bool(previous and previous[1] > 0 and severity == 0)
    due = not previous or (aware_timestamp(at) - aware_timestamp(last)).total_seconds() >= 86400
    notify = recovery or (severity > 0 and (changed or (due and kind != 'evidence')))
    if notify:
        generation += 1
        last = at
        key = hashlib.sha256(dumps([identity, generation, status]).encode()).hexdigest()
        _enqueue(conn, run, dict(key=key, kind='recovery' if recovery else kind, condition=kind,
            status=status, severity=('info','warning','high','critical')[severity], symbol=symbol, at=at))
    conn.execute('INSERT OR REPLACE INTO condition_state VALUES (?,?,?,?,?,?)', (identity, status, severity, generation, last, run))


def ack_alert(db: Path, key: str, receipt: dict) -> None:
    """Caller must obtain real transport evidence; this validates, never invents it.

    No-ack transports MUST leave rows pending after ambiguous delivery and disclose
    possible duplicates. A local send-success boolean is not provider readback.
    """
    if (not isinstance(receipt, dict) or receipt.get('status') != 'delivered'
            or receipt.get('verification') not in {'provider_readback', 'idempotent_receipt'}
            or not all(isinstance(receipt.get(k), str) and receipt[k] for k in ('provider', 'message_id', 'verified_at'))):
        raise ValueError('verifiable_delivery_receipt_required')
    aware_timestamp(receipt['verified_at'])
    if not _path(db).exists():
        raise ValueError('unknown_alert_key')
    safe = {k: receipt[k] for k in ('provider', 'message_id', 'verified_at', 'status', 'verification')}
    with _connection(db, True) as conn:
        row = conn.execute('SELECT state,receipt FROM alert_outbox WHERE key=?', (key,)).fetchone()
        if not row:
            raise ValueError('unknown_alert_key')
        if row[0] == 'acknowledged' and row[1] != dumps(safe):
            raise ValueError('receipt_conflict')
        conn.execute("UPDATE alert_outbox SET state='acknowledged',receipt=? WHERE key=?", (dumps(safe), key))


def read_portfolio_history(db: Path) -> list[dict]:
    """Coherent compact Task5 prior snapshots, oldest first. No repair/migration."""
    if not _path(db).exists():
        return []
    with _connection(db) as conn:
        return [json.loads(row[0]) for row in conn.execute(
            'SELECT p.payload FROM portfolio_snapshots p JOIN runs r USING(run_id) ORDER BY r.captured_at,r.rowid')]


def read_report(db: Path) -> dict:
    if not _path(db).exists():
        return {}
    with _connection(db) as conn:
        row = conn.execute('SELECT payload FROM runs ORDER BY captured_at DESC, rowid DESC LIMIT 1').fetchone()
        return json.loads(row[0]) if row else {}
