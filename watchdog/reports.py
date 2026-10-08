"""Private compact reporting and fail-closed public field AND value allowlists.

Public projection never passes through prose, identifiers, source URLs or dynamic
keys. No model/source text can be made public merely by putting it in `status`.
"""
from datetime import date
import json
import re

from .store import compact
from .types import aware_timestamp, money

REASONS = frozenset('''source_coverage_incomplete lineage_coverage_unknown broker_coverage_unknown
baseline_invalid baseline_incomplete classification_failed source_retrieval_failed event_conflicting
account_evidence_unknown account_flow_coverage_unknown account_flow_date_basis_unknown
execution_precision_unknown broker_market_value_discrepancy horizon_missing horizon_invalid
horizon_session_entry_unknown protection_ref_missing protection_quantity_mismatch
protection_order_cancelled protection_order_expired protection_order_rejected protection_order_status_unknown
protection_stop_missing protection_replacement_conflict unexpected_exit concurrent_quantity_change
executions_coverage_unknown fees_coverage_unknown distribution_coverage_unknown corporate_actions_coverage_unknown
activity_interval_not_enclosing comparison_coverage_unknown valuation_basis_unsynchronized benchmark_endpoint_missing
monitoring_unavailable unknown_diagnostic'''.split())
STATUSES = frozenset('''complete incomplete unknown error coverage_incomplete baseline_incomplete
no_material_change_observed review_required potential_thesis_break verified discrepancy consistent
concurrent_quantity_change covered not_required partial unprotected active horizon_expired weakens unclear potential-break'''.split())


def _dict(value):
    return value if isinstance(value, dict) else {}


def _rows(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _enum(value, allowed, default='unknown'):
    return value if isinstance(value, str) and value in allowed else default


def _amount(value):
    # Bound parser inputs. A finite canonical decimal is data, arbitrary numeric
    # strings with embedded prose/URLs are not. Booleans are never amounts.
    if isinstance(value, str) and (len(value) > 100 or not re.fullmatch(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', value)):
        return None
    try:
        return str(money(value))
    except (ValueError, TypeError, OverflowError):
        return None


def _timestamp(value):
    try:
        return aware_timestamp(value).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def _symbol(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Z]{1,5}(?:[.-][A-Z])?', value) else None


def _reasons(value):
    rows = value if isinstance(value, list) else []
    safe = sorted({v for v in rows if isinstance(v, str) and v in REASONS})
    if any(not isinstance(v, str) or v not in REASONS for v in rows):
        safe.append('unknown_diagnostic')
    return safe


def _coverage(value):
    value = _dict(value)
    out: dict = dict(status=_enum(value.get('status'), {'complete', 'incomplete', 'unknown', 'error', 'coverage_incomplete'}),
               reasons=_reasons(value.get('reasons')))
    for key in ('managed_positions', 'execution_events', 'valid_mark_samples', 'mark_gaps'):
        number = value.get(key)
        if type(number) is int and 0 <= number <= 100000000:
            out[key] = number
    return out


def public_summary(report: dict) -> dict:
    report = _dict(report)
    portfolio = _dict(report.get('portfolio'))
    strategy = _dict(portfolio.get('strategy'))
    account = _dict(portfolio.get('account'))
    actual = strategy.get('scope') == 'actual_managed_strategy' and _amount(strategy.get('initial_capital')) == '10000'
    complete = actual and _coverage(strategy.get('coverage'))['status'] == 'complete'
    out_strategy = dict(label='Primary managed strategy — $10,000 initial capital', initial_capital='10000',
        at=_timestamp(strategy.get('at')), coverage=_coverage(strategy.get('coverage')),
        return_kind=_enum(strategy.get('return_kind'), {'total_return', 'price_return'}),
        planned_loss_basis='conditional_stop_geometry_not_guaranteed')
    for key in ('cash', 'marked_equity', 'managed_market_value', 'realized_pnl', 'unrealized_pnl',
                'costs', 'distributions', 'return', 'inception_return', 'drawdown', 'conditional_planned_loss'):
        out_strategy[key] = _amount(strategy.get(key)) if complete else None
    if not actual:
        out_strategy['coverage'] = _coverage({})
        out_strategy['return_kind'] = 'unknown'
    out_account = dict(label='Secondary full account — includes legacy/manual holdings',
        at=_timestamp(account.get('at')), coverage=_coverage(account.get('coverage')))
    for key in ('equity', 'cash'):
        out_account[key] = _amount(account.get(key)) if account.get('scope') == 'full_account_secondary' else None
    # Account performance is deliberately withheld: reporting observations is not
    # proof of a baseline/flow inventory, and account gains are not strategy alpha.
    positions = []
    owned = {}
    for p in _rows(report.get('positions')):
        symbol = _symbol(p.get('symbol'))
        if p.get('ownership_status') != 'verified' or not symbol or not isinstance(p.get('position_id'), str):
            continue
        owned[p['position_id']] = symbol
        row: dict = dict(symbol=symbol, ownership_status='verified', reasons=_reasons(p.get('reasons')))
        for key, allowed in (
            ('quantity_status', {'consistent', 'concurrent_quantity_change'}),
            ('protection_status', {'covered', 'not_required', 'partial', 'unprotected', 'unknown'}),
            ('horizon_status', {'active', 'horizon_expired', 'unknown'})):
            row[key] = _enum(p.get(key), allowed)
        for key in ('remaining_quantity', 'protection_coverage_quantity'):
            row[key] = _amount(p.get(key))
        positions.append(row)
    accounting = {p.get('position_id'): p for p in _rows(strategy.get('positions')) if isinstance(p.get('position_id'), str)}
    for public_row, private_row in zip(positions, [p for p in _rows(report.get('positions'))
            if p.get('ownership_status') == 'verified' and _symbol(p.get('symbol')) and isinstance(p.get('position_id'), str)]):
        amounts = accounting.get(private_row.get('position_id'), {})
        public_row['accounting_coverage'] = 'complete' if complete else 'unknown'
        for key in ('market_value', 'cost_basis', 'weight_vs_sleeve_equity', 'realized_pnl', 'unrealized_pnl'):
            public_row[key] = _amount(amounts.get(key)) if complete and amounts.get('symbol') == public_row['symbol'] else None
    thesis = [dict(symbol=_symbol(t.get('symbol')), status=_enum(t.get('status'),
        {'baseline_incomplete', 'no_material_change_observed', 'review_required', 'potential_thesis_break', 'coverage_incomplete'}),
        coverage_status=_enum(t.get('coverage_status'), {'complete', 'coverage_incomplete'}))
        for t in _rows(report.get('thesis')) if isinstance(t.get('position_id'), str) and owned.get(t['position_id']) == _symbol(t.get('symbol')) and _symbol(t.get('symbol'))]
    # Only the pure comparator's synchronized complete result may publish numbers.
    benchmark = _dict(portfolio.get('benchmark'))
    bcoverage = _coverage(benchmark.get('coverage'))
    out_benchmark: dict = dict(symbol='SPY', coverage=bcoverage,
        return_kind=_enum(benchmark.get('return_kind'), {'price_return_only', 'total_return'}))
    for key in ('benchmark_return', 'benchmark_equity', 'strategy_return', 'excess_total_return', 'excess_price_comparator'):
        allowed = complete and bcoverage['status'] == 'complete'
        if key == 'excess_total_return':
            allowed = allowed and benchmark.get('return_kind') == 'total_return' and strategy.get('return_kind') == 'total_return'
        out_benchmark[key] = _amount(benchmark.get(key)) if allowed else None
    session = report.get('session_date')
    try:
        if not isinstance(session, str):
            raise ValueError('invalid session date')
        session = date.fromisoformat(session).isoformat()
    except (ValueError, TypeError):
        session = None
    return dict(available=bool(report), session_date=session, coverage=_coverage(report.get('coverage')),
        reasons=_reasons(report.get('reasons')), strategy=out_strategy, account=out_account,
        benchmark=out_benchmark, positions=positions, thesis=thesis,
        outcomes_label='Research and shadow outcomes are not actual protected-trade returns')


def private_report(report: dict) -> str:
    """Compact private provenance, never full articles/model transcripts."""
    safe = compact(report)
    public = public_summary(report)
    return ('# Position and portfolio watchdog\n\nMonitoring only; no execution or repair authority.\n\n'
        '## Primary strategy: $10,000 initial allocation, evolving sleeve equity\n\n'
        + 'Marked equity: ' + str(public['strategy']['marked_equity']) + '\n\n'
        + '## Secondary full account: not strategy alpha\n\nEquity: ' + str(public['account']['equity']) + '\n\n'
        + 'Research/shadow horizon outcomes are not actual protected-trade returns.\n'
        + 'Stop geometry is conditional, not maximum loss. Unknown evidence remains withheld.\n\n'
        + '## Private compact observations and sourced provenance\n\n```json\n'
        + json.dumps(safe, indent=2, sort_keys=True, allow_nan=False) + '\n```\n')


def render_alert(alert: dict) -> str:
    alert = _dict(alert)
    kind = _enum(alert.get('kind'), {'protection', 'ownership', 'quantity', 'horizon', 'thesis', 'evidence', 'coverage', 'recovery', 'digest'})
    status = _enum(alert.get('status'), STATUSES)
    severity = _enum(alert.get('severity'), {'info', 'warning', 'high', 'critical'})
    symbol = _symbol(alert.get('symbol'))
    return f"Watchdog {kind}: {symbol + ' ' if symbol else ''}{status} ({severity}). Human review only; no trading action taken."


def dashboard_summary(db) -> dict:
    """Private DB input only, no sync/repair/mkdir; sanitize on EVERY read."""
    import sqlite3
    from .store import read_report
    try:
        return public_summary(read_report(db))
    except (OSError, ValueError, sqlite3.Error, TypeError, KeyError):
        return public_summary({'reasons': ['monitoring_unavailable']}) | {'available': False}


def _sync_dir(path):
    import os
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_sync(path, text):
    import os
    with path.open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def install_reports(db) -> dict:
    """Install one coherent private JSON/Markdown generation, public file atomic.

    latest.json/latest.md are stable relative aliases to .reports/current, whose
    pointer is replaced ONCE after both files are fsynced. Public watchdog.json
    is independently atomically replaced; no cross-directory atomicity claimed.
    A crash may leave an older safe public summary, never a partial/private one.
    Task8 retries this from read_report after commit before delivering alerts.
    Dashboard always projects the coherent DB snapshot, not these file aliases.
    """
    import fcntl
    import os
    from pathlib import Path
    import tempfile
    from uuid import uuid4
    from .store import _path, read_report
    db = _path(db)
    root = db.parents[2]
    if '.worktrees' in root.parts and 'test_artifacts' not in root.parts:
        raise ValueError('worktree_publication_forbidden')
    if not db.exists():
        raise ValueError('monitoring_report_missing')
    private = db.parent
    for path in (private/'.reports', root/'public', private/'.reports.lock'):
        if path.is_symlink():
            raise ValueError('report_output_symlink_rejected')
    with (private/'.reports.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        report = read_report(db)
        if not report:
            raise ValueError('monitoring_report_missing')
        # Prepare every projection before ANY published replacement.
        private_json = json.dumps(compact(report), indent=2, sort_keys=True, allow_nan=False)
        markdown = private_report(report)
        public = public_summary(report)
        public_json = json.dumps(public, indent=2, sort_keys=True, allow_nan=False)
        generations = private/'.reports'
        generations.mkdir(exist_ok=True, mode=0o700)
        generation = Path(tempfile.mkdtemp(prefix='generation-', dir=generations))
        public_dir = root/'public'
        public_dir.mkdir(exist_ok=True)
        staged_public = public_dir/('.watchdog-' + uuid4().hex)
        pointer = generations/('.current-' + uuid4().hex)
        try:
            _write_sync(generation/'latest.json', private_json)
            _write_sync(generation/'latest.md', markdown)
            _sync_dir(generation)
            _write_sync(staged_public, public_json)
            os.chmod(staged_public, 0o644)
            for name in ('latest.json', 'latest.md'):
                alias = private/name
                if not alias.is_symlink():
                    if alias.exists():
                        raise ValueError('report_alias_conflict')
                    alias.symlink_to('.reports/current/' + name)
                elif os.readlink(alias) != '.reports/current/' + name:
                    raise ValueError('report_alias_conflict')
            pointer.symlink_to(generation.name)
            os.replace(pointer, generations/'current')
            _sync_dir(generations)
            _sync_dir(private)
            os.replace(staged_public, public_dir/'watchdog.json')
            _sync_dir(public_dir)
            import shutil
            old = sorted((p for p in generations.glob('generation-*') if p.is_dir() and not p.is_symlink() and p != generation),
                         key=lambda p: p.stat().st_mtime_ns, reverse=True)
            for path in old[2:]:
                shutil.rmtree(path)
            return public
        finally:
            pointer.unlink(missing_ok=True)
            staged_public.unlink(missing_ok=True)
            if (generations/'current').resolve() != generation:
                import shutil
                shutil.rmtree(generation)
