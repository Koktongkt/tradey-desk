"""Watchdog CLI: isolated monitoring workflows, bounded budgets, safe paths.

Monitoring only. This module never takes the trading writer/kill-switch lock,
never mutates operational inputs, and never manufactures delivery receipts.
Fail-closed rules:

- Paths: the operational root and output root must be the live checkout root
  or lie explicitly beneath <checkout>/test_artifacts. Fixture (--fixture) and
  smoke runs are confined beneath <checkout>/test_artifacts/watchdog. External
  roots, symlink escapes, and operational input/output overlap are rejected
  before any side effect.
- Locking: a single monitoring-only flock at
  <output_root>/private/watchdog/monitor.lock (LOCK_EX|LOCK_NB). Contention is
  a skipped no-op; the trading lock is never opened or created here, so a
  watchdog failure cannot block or kill the autotrader.
- Budgets: run_budgets(mode) — mechanical 120s outer; daily 900s outer wall
  clock with 840s active work and 60s report/persistence reserve. The trusted
  completion stamp is the caller-supplied aware `now`, never broker capture
  time or local start time.
- Daily completion: the marker file is written only after the observation is
  committed AND reports install successfully. A failed reporting attempt
  leaves alerts pending and the next eligible daily slot for the same session
  date retries reporting/delivery ONLY under the stable per-session-date run
  identity (`daily:<session_date>`): the committed observation is not
  recommitted and thesis retrieval is not re-run. Execution (retrieval) is
  never retried mid-run. Retry/identity checks key on the latest run of the
  SAME mode (`store.read_latest_report`), so a later inter-mode run cannot
  misroute them. Commit failures (`run_identity_conflict`,
  `source_cutoff_future`, ...) are typed failed results with the store reason
  in `reasons`, never raw exceptions escaping the run wrapper.
- Coverage stamping: `coverage.captured_at` is the observation-completion
  instant (trusted `now` + measured elapsed), per the recorded ruling
  "observation-completion captured_at >= source checked-through, not
  broker/start time". Thesis workers are additionally pinned to
  `checked_through <= supplied now` (a worker may never claim inspection in
  the future); a violating source is a typed per-source coverage gap.
- Daily thesis baselines: `baseline_from_candidate` is wired over the exactly
  lineage-linked candidate of every managed position, so the lane evaluates
  real criteria once workers exist. Candidates whose catalyst is a plain
  string without a separate event_date yield a typed `baseline_incomplete`
  gap (surfaced as the `thesis_baseline_incomplete` reason) — a date is never
  guessed.
- Smoke: a smoke run is a dry-run commit — run/portfolio/attribution evidence
  only, NO baselines/evidence events/source cutoffs, NO condition
  transitions and NO outbox rows — so a smoke probe can never arm the 24h
  condition quiet window, queue alerts, or suppress real ones. Smoke output
  may sit under <checkout>/test_artifacts/watchdog even when nested inside
  the operational root: test_artifacts is a documented non-operational
  exception to the overlap rule. This exception is smoke-only; real runs may
  never nest output inside the operational root.
- Delivery: every pending alert (including older runs) is rendered with
  reports.render_alert and handed to adapters['transport'](alert, rendered).
  Only a genuine provider receipt (validated by store.ack_alert) acknowledges.
  Ambiguous or absent receipts stay pending; where the transport cannot prove
  delivery (e.g. Hermes cron relay with no readback), duplicate-on-retry
  semantics are disclosed rather than claimed exactly-once. A transport that
  RAISES is reported as its own typed bucket
  (`transport_exception_delivery_pending`), distinct from an ambiguous
  no-readback receipt (`ambiguous_delivery_possible_duplicates`); both keep
  alerts pending.

Adapter keys (all fake in tests; no live defaults):
  broker:     () -> BrokerSnapshot                       (Task 2 collector)
  transport:  (alert, rendered_text) -> receipt|None|raise
  thesis:     {'discover','retrieve','classify'} JSONCommand trio + 'now'
              (concrete source-profile worker commands; absent => typed
              'thesis_worker_blocker' coverage gap, never a placeholder run)
  benchmark:  (strategy) -> compare_benchmark result (absent => typed gap)
  install_reports: override of watchdog.reports.install_reports (tests)
  clock:      () -> monotonic seconds (budget test seam)
"""
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time

from . import operational, schedule
from .lineage import build_lineage
from .mechanical import aggregate_exposure, observe_positions
from .reports import render_alert
from .store import (ack_alert, commit_observation, pending_alerts, read_latest_report,
                    read_portfolio_history, read_source_state)
from .types import RunObservation, aware_timestamp

CHECKOUT = Path(__file__).resolve().parents[1]
TEST_ARTIFACTS = CHECKOUT / 'test_artifacts'
MODES = ('mechanical', 'daily')

BUDGETS = {
    'mechanical': {'outer': 120, 'active': 120, 'reserve': 0},
    'daily': {'outer': 900, 'active': 840, 'reserve': 60},
}


def run_budgets(mode: str) -> dict:
    """Trusted hard deadlines per Task 6: 900/840/60 daily, 120 mechanical."""
    if mode not in BUDGETS:
        raise ValueError('unknown_watchdog_mode')
    return dict(BUDGETS[mode])


def _realpath_strict(path: Path) -> Path:
    """Reject paths whose literal form already travels through a symlink."""
    literal = Path(os.path.abspath(path))
    probe = Path(literal.anchor)
    for part in literal.parts[1:]:
        probe = probe / part
        if probe.is_symlink():
            raise ValueError('symlink_escape_rejected')
    return Path(os.path.realpath(path))


def _allowed_root(resolved: Path) -> bool:
    return resolved == CHECKOUT or resolved == TEST_ARTIFACTS or TEST_ARTIFACTS in resolved.parents


def resolve_paths(root, output_root, fixture: bool = False, smoke: bool = False) -> tuple[Path, Path]:
    """Fail-closed path contract (fixture confinement, escapes, overlap).

    Smoke-only exception: output under <checkout>/test_artifacts/watchdog is a
    documented non-operational location, so it may nest inside the operational
    root for a confined real-broker smoke probe. Never for real runs, and
    never output inside root/private or root inside output.
    """
    if not fixture:
        root_r, out_r = _realpath_strict(Path(root)), _realpath_strict(Path(output_root))
        if not _allowed_root(root_r) or not _allowed_root(out_r):
            raise ValueError('external_root_rejected')
    else:
        # Fixture/smoke runs may only touch test_artifacts/watchdog.
        root_r, out_r = _realpath_strict(Path(root)), _realpath_strict(Path(output_root))
        watchdog_root = TEST_ARTIFACTS / 'watchdog'
        for resolved in (root_r, out_r):
            if resolved != watchdog_root and watchdog_root not in resolved.parents:
                raise ValueError('fixture_output_confined')
    if root_r != out_r:
        private = root_r / 'private'
        smoke_artifacts_out = smoke and (
            out_r == TEST_ARTIFACTS / 'watchdog' or (TEST_ARTIFACTS / 'watchdog') in out_r.parents)
        if (out_r == private or private in out_r.parents or out_r in root_r.parents
                or (root_r in out_r.parents and not smoke_artifacts_out)):
            raise ValueError('path_overlap_rejected')
    return root_r, out_r


def _input_digests(root: Path) -> dict:
    """Stat + content identity of operational inputs, taken before the run.

    The ledger is WAL-mode, so the sqlite `-wal`/`-shm` sidecars are covered
    whenever they exist: an autotrader write landing in `-wal` without a
    main-db checkpoint would otherwise change neither the db's sha256 nor its
    mtime. Sidecars created (or removed) between the before/after snapshots
    are detected as a change because the key set itself differs.
    """
    digests = {}
    db = root / 'private/trading_journal.sqlite3'
    paths = [db, root / 'private/broker_baseline.json'] + [
        root / name for name in (
            'candidates.jsonl', 'candidate_outcomes.jsonl', 'decision_audit.jsonl',
            'order_ledger.jsonl', 'trade_journal.jsonl', 'private/order_intents.jsonl',
            'private/reviews.jsonl', 'private/protection_orders.jsonl')]
    paths += [Path(str(db) + suffix) for suffix in ('-wal', '-shm')
              if Path(str(db) + suffix).exists()]
    for path in paths:
        try:
            stat = path.stat()
            entry = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
            if path.is_file():
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1 << 20), b''):
                        digest.update(chunk)
                entry['sha256'] = digest.hexdigest()
            digests[str(path)] = entry
        except OSError:
            digests[str(path)] = None
    return digests


def _input_unchanged(before: dict, root: Path) -> bool:
    return before == _input_digests(root)


class _Budget:
    def __init__(self, budgets, clock):
        self.budgets, self.clock = budgets, clock
        self.start = clock()

    def left(self, key: str) -> float:
        return self.budgets[key] - (self.clock() - self.start)

    def check(self, key: str) -> None:
        if self.left(key) <= 0:
            raise TimeoutError(key + '_deadline_exceeded')


def _mark_complete(output_root: Path, session_date: str, run_id: str, now: datetime) -> Path:
    """Completion marker lives solely under the output root; atomic 0600."""
    directory = output_root / 'private/watchdog/completions'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    marker = directory / (session_date + '.json')
    payload = json.dumps({'session_date': session_date, 'run_id': run_id,
                          'mode': 'daily', 'completed_at': now.astimezone(timezone.utc).isoformat()},
                         sort_keys=True)
    staged = directory / ('.marker-' + str(os.getpid()))
    with staged.open('w', encoding='utf-8') as stream:
        os.chmod(staged, 0o600)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(staged, marker)
    return marker


def _deliver(db: Path, transport) -> dict:
    """Drain ALL pending alerts (prior runs included) through the transport.

    Receipts are validated by ack_alert; anything ambiguous stays pending and
    is reported as such. Outbox retries therefore remain until genuine
    provider acknowledgment exists.
    """
    delivered, ambiguous, transport_failed = [], [], 0
    for alert in pending_alerts(db):
        key = alert.get('key')
        if not isinstance(key, str) or not key:
            ambiguous.append(key)
            continue
        rendered = render_alert(alert)
        receipt = None
        if transport is not None:
            try:
                receipt = transport(alert, rendered)
            except Exception:
                # A raising transport is its own typed bucket: distinct from an
                # ambiguous no-readback receipt, both keep alerts pending.
                transport_failed += 1
                receipt = None
        if receipt is not None:
            try:
                ack_alert(db, key, receipt)
                delivered.append(key)
                continue
            except ValueError:
                pass
        ambiguous.append(key)
    result = {'delivered': len(delivered), 'pending': len(ambiguous), 'keys': delivered}
    if transport_failed:
        result['reasons'] = ['transport_exception_delivery_pending']
    elif ambiguous and transport is not None:
        result['reasons'] = ['ambiguous_delivery_possible_duplicates']
    return result


def run_watchdog(mode: str, root, output_root, adapters: dict, now: datetime,
                 budgets: dict | None = None, fixture: bool = False,
                 smoke: bool = False) -> dict:
    """One isolated monitoring run. See module docstring for the contract."""
    if mode not in MODES:
        raise ValueError('unknown_watchdog_mode')
    if not isinstance(adapters, dict):
        raise ValueError('adapters_required')
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now requires timezone')
    if 'broker' not in adapters or not callable(adapters['broker']):
        # Fail closed: no placeholder broker snapshot.
        return {'status': 'failed', 'mode': mode, 'reasons': ['adapter_missing_broker'],
                'all_clear': False, 'input_unchanged': True, 'committed': False,
                'delivered': 0, 'pending': 0, 'run_id': None}
    root, output_root = resolve_paths(root, output_root, fixture=fixture, smoke=smoke)
    clock = adapters.get('clock', time.monotonic)
    budget = _Budget(budgets or run_budgets(mode), clock)
    before = _input_digests(root)

    # Monitoring-only lock, separate from any trading lock or kill switch.
    watchdog_dir = output_root / 'private/watchdog'
    watchdog_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    watchdog_dir.chmod(0o700)
    lock_path = watchdog_dir / 'monitor.lock'
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'skipped', 'mode': mode, 'reasons': ['monitoring_lock_busy'],
                    'all_clear': False, 'input_unchanged': True, 'committed': False,
                    'delivered': 0, 'pending': 0, 'run_id': None}
        try:
            return _run_locked(mode, root, output_root, adapters, now, budget,
                               before, smoke, clock)
        except TimeoutError as deadline:
            return {'status': 'budget_exceeded', 'mode': mode, 'run_id': None,
                    'reasons': [str(deadline)], 'all_clear': False,
                    'input_unchanged': _input_unchanged(before, root),
                    'committed': False, 'delivered': 0, 'pending': 0,
                    'coverage_status': 'unknown'}
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


def _run_locked(mode, root, output_root, adapters, now, budget, before, smoke, clock) -> dict:
    db = output_root / 'private/watchdog/monitoring.sqlite3'
    try:
        broker = adapters['broker']()
    except TimeoutError:
        raise
    except Exception:
        return _failed(mode, before, root, ['broker_adapter_failed'], db)
    budget.check('outer')
    # Session/cron gate: silent no-op outside eligibility; a missing or
    # invalid calendar is a typed coverage gap, never a guessed session.
    ok, gate_reasons, session_date = schedule.eligibility(mode, now, getattr(broker, 'sessions', None))
    if not ok:
        return {'status': 'no_op', 'mode': mode, 'run_id': None, 'reasons': list(gate_reasons),
                'all_clear': False, 'input_unchanged': _input_unchanged(before, root),
                'committed': False, 'delivered': 0, 'pending': 0,
                'coverage_status': 'unknown'}
    run_id = mode + ':' + (session_date if mode == 'daily' and not smoke else
                           now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    # Bounded next-slot reporting/delivery retry for the same session date:
    # the stable per-session-date identity means a later daily slot for an
    # already-committed observation retries install + delivery ONLY (no
    # thesis retrieval, no recommit). Smoke never retries (no side effects).
    if mode == 'daily' and not smoke and db.exists() \
            and read_latest_report(db, 'daily').get('run_id') == run_id:
        return _reporting_retry(mode, run_id, session_date, root, output_root,
                                db, adapters, now, budget, before)

    reasons = []
    try:
        snapshot = operational.read_operational(root)
    except Exception:
        return _failed(mode, before, root, ['operational_read_failed'], db)
    reasons.extend(snapshot.reasons)
    budget.check('outer')
    lineage = build_lineage(snapshot, broker)
    positions = observe_positions(lineage, broker, now)
    exposure = aggregate_exposure(positions, broker)
    # Legacy/unverifiable holdings are explicit coverage gaps, never all-clear.
    reasons.extend(exposure['coverage'].get('reasons', []))
    if exposure.get('legacy_holdings'):
        reasons.append('legacy_holdings_unattributed')

    portfolio = {'exposure': exposure}
    thesis_rows = []
    if mode == 'daily':
        budget.check('active')
        prior = [dict(strategy=row.get('strategy'), account=row.get('account'))
                 for row in read_portfolio_history(db)]
        from .accounting import account_overview, account_strategy
        strategy_baseline = (prior[-1].get('strategy') or {}).get('strategy_baseline') if prior else None
        baseline_input = strategy_baseline if isinstance(strategy_baseline, dict) else {}
        portfolio['strategy'] = account_strategy(lineage, broker, baseline_input, prior)
        portfolio['account'] = account_overview(broker, prior)
        benchmark_adapter = adapters.get('benchmark')
        if callable(benchmark_adapter):
            try:
                budget.check('active')
                portfolio['benchmark'] = benchmark_adapter(portfolio['strategy'])
            except Exception:
                portfolio['benchmark'] = {}
                reasons.append('benchmark_adapter_failed')
        else:
            portfolio['benchmark'] = {}
            reasons.append('benchmark_unavailable')
        budget.check('active')
        thesis_adapters = adapters.get('thesis')
        if isinstance(thesis_adapters, dict) and thesis_adapters.get('now'):
            from .thesis import baseline_from_candidate, monitor_theses
            # Wire the exactly lineage-linked candidate of every managed
            # position into a real baseline: without this the thesis lane
            # would evaluate nothing once workers exist. A plain-string
            # candidate catalyst without an event_date yields a typed
            # baseline_incomplete gap; a date is never guessed.
            baselines = {}
            for position in lineage.positions:
                position_id = position.get('position_id')
                if not isinstance(position_id, str) or not position_id:
                    continue
                candidate = dict(position.get('thesis_baseline') or {})
                candidate.update({key: position[key] for key in ('candidate_id', 'dossier_hash')
                                  if isinstance(position.get(key), str) and position[key]})
                baselines[position_id] = baseline_from_candidate(candidate)
            deadline = min(budget.left('active'), 600.0)
            thesis_rows = monitor_theses(lineage.positions, baselines, read_source_state(db),
                                         thesis_adapters, time.monotonic() + max(deadline, 0.0))
            if any(t.get('status') == 'baseline_incomplete' for t in thesis_rows):
                reasons.append('thesis_baseline_incomplete')
        else:
            # No reviewed concrete worker commands configured: a typed
            # blocker, never a fabricated thesis pass.
            reasons.append('thesis_worker_blocker')
    try:
        budget.check('outer')
    except TimeoutError:
        return _failed(mode, before, root, ['outer_deadline_exceeded'], db)

    # Observation-completion captured_at (recorded ruling: captured_at must be
    # >= source checked-through, not broker/start time). Elapsed is measured on
    # the run's own monotonic clock seam.
    try:
        elapsed = max(clock() - budget.start, 0.0)
    except Exception:
        elapsed = 0.0
    captured_at = (now + timedelta(seconds=elapsed)).astimezone(timezone.utc).isoformat()
    coverage = {
        'status': 'complete' if snapshot.complete and broker.complete and not reasons else 'incomplete',
        'captured_at': captured_at,
        'sources': dict(getattr(broker, 'coverage', {}) or {}),
        'reasons': sorted(set(reasons)),
    }
    observation = RunObservation(
        run_id=run_id, session_date=session_date, mode=mode, positions=positions,
        portfolio=portfolio,
        attribution={'actual': {'observations': len(positions)},
                     'research': {'observations': len(thesis_rows)},
                     'decisions': {'observations': len(lineage.decisions)},
                     'shadow': {'observations': 0}},
        thesis=thesis_rows, coverage=coverage, reasons=sorted(set(reasons)))
    already_committed = read_latest_report(db, mode).get('run_id') == run_id
    # The store itself dedupes an identical digest for the same run identity
    # and raises `run_identity_conflict` on a same-identity content change.
    # Commit rejections are typed failed results with the store reason, never
    # raw exceptions escaping the run wrapper; nothing is committed and all
    # alerts stay pending.
    try:
        alerts = commit_observation(db, observation, smoke=smoke)
    except ValueError as error:
        code = (str(error) or 'observation_commit_failed').replace(' ', '_')
        return {'status': 'failed', 'mode': mode, 'run_id': run_id,
                'session_date': session_date,
                'reasons': ['observation_commit_failed', code], 'all_clear': False,
                'input_unchanged': _input_unchanged(before, root),
                'committed': False, 'committed_now': False, 'delivered': 0,
                'pending': len(pending_alerts(db)) if db.exists() else 0,
                'coverage_status': coverage['status'], 'completion_marker': False,
                'delivery': {}}
    committed_now = not already_committed

    if smoke:
        # Live smoke: dry-run commit (no condition state, no outbox rows), no
        # alert send, no dashboard/publication, no completion marker.
        delivery = {'delivered': 0, 'pending': len(pending_alerts(db)), 'keys': []}
        marker = False
    else:
        try:
            budget.check('outer')
            (adapters.get('install_reports') or _default_install)(db)
        except Exception:
            # Report/persistence failure must not acknowledge alerts; the next
            # eligible daily slot retries reporting only, never execution.
            return {'status': 'failed', 'mode': mode, 'run_id': run_id,
                    'reasons': ['report_install_failed'], 'all_clear': False,
                    'input_unchanged': _input_unchanged(before, root),
                    'committed': True, 'delivered': 0,
                    'pending': len(pending_alerts(db)), 'coverage_status': coverage['status']}
        delivery = _deliver(db, adapters.get('transport'))
        marker = False
        if mode == 'daily':
            # Trusted stamp is the caller-supplied `now`, not broker time.
            _mark_complete(output_root, session_date, run_id, now)
            marker = True

    unchanged = _input_unchanged(before, root)
    if not unchanged:
        coverage['reasons'] = sorted(set(coverage['reasons'] + ['operational_input_changed_after_run']))
        reasons.append('operational_input_changed_after_run')
    return {'status': 'ok', 'mode': mode, 'run_id': run_id, 'session_date': session_date,
            'reasons': sorted(set(reasons)), 'all_clear': not reasons and coverage['status'] == 'complete',
            'input_unchanged': unchanged, 'committed': committed_now,
            'committed_now': committed_now, 'delivered': delivery['delivered'],
            'pending': delivery['pending'], 'coverage_status': coverage['status'],
            'completion_marker': marker,
            'delivery': {k: v for k, v in delivery.items() if k != 'keys'}}


def _default_install(db):
    from .reports import install_reports
    install_reports(db)


def _reporting_retry(mode, run_id, session_date, root, output_root, db,
                     adapters, now, budget, before) -> dict:
    """Reporting/delivery-only retry for an already-committed session date.

    The observation and thesis retrieval are NOT redone: only report
    installation, outbox delivery and the completion marker are retried.
    Coverage is not re-measured here, so all_clear is never claimed from the
    retry alone; the committed observation's coverage stands in the store.
    """
    try:
        budget.check('outer')
        (adapters.get('install_reports') or _default_install)(db)
    except Exception:
        # Reporting failure keeps alerts pending for the following slot.
        return {'status': 'failed', 'mode': mode, 'run_id': run_id,
                'reasons': ['report_install_failed'], 'all_clear': False,
                'input_unchanged': _input_unchanged(before, root),
                'committed': True, 'committed_now': False,
                'reporting_retry': True, 'delivered': 0,
                'pending': len(pending_alerts(db)), 'coverage_status': 'unknown'}
    delivery = _deliver(db, adapters.get('transport'))
    # Trusted stamp is the caller-supplied `now` of the retrying slot.
    _mark_complete(output_root, session_date, run_id, now)
    unchanged = _input_unchanged(before, root)
    return {'status': 'ok', 'mode': mode, 'run_id': run_id, 'session_date': session_date,
            'reasons': ['reporting_retry_delivery_only'], 'all_clear': False,
            'input_unchanged': unchanged, 'committed': True, 'committed_now': False,
            'reporting_retry': True, 'delivered': delivery['delivered'],
            'pending': delivery['pending'], 'coverage_status': 'prior_run_committed',
            'completion_marker': True,
            'delivery': {k: v for k, v in delivery.items() if k != 'keys'}}


def _failed(mode, before, root, extra, db):
    reasons = list(extra)
    return {'status': 'failed', 'mode': mode, 'run_id': None, 'reasons': reasons,
            'all_clear': False, 'input_unchanged': _input_unchanged(before, root),
            'committed': False, 'delivered': 0, 'pending': 0,
            'coverage_status': 'unknown'}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Unknown actions fail closed with no side effects."""
    import argparse
    parser = argparse.ArgumentParser(prog='watchdog_cli.py', add_help=True,
                                     description='Monitoring-only position/portfolio watchdog CLI')
    parser.add_argument('action', choices=['mechanical', 'daily', 'eligibility'],
                        help='monitoring action (anything else fails closed)')
    parser.add_argument('--root', default=str(CHECKOUT), help='operational storage root')
    parser.add_argument('--output-root', default=None, help='output root (default: --root)')
    parser.add_argument('--fixture', action='store_true',
                        help='confine root and output beneath test_artifacts/watchdog')
    parser.add_argument('--smoke', action='store_true',
                        help='live smoke: dry-run commit, no alert send, no publication')
    parser.add_argument('--now', default=None, help='trusted aware ISO clock override (ops/testing)')
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_code:
        # Unknown actions fail closed: argparse usage error, no side effects.
        return int(exit_code.code or 2) if isinstance(exit_code.code, int) else 2
    if args.action == 'eligibility':
        print(json.dumps({'mechanical_cron': schedule.MECHANICAL_CRON,
                          'daily_cron': schedule.DAILY_CRON}))
        return 0
    try:
        now = aware_timestamp(args.now) if args.now else datetime.now(timezone.utc)
        output_root = args.output_root or args.root
        result = run_watchdog(args.action, Path(args.root), Path(output_root),
                              {}, now, fixture=args.fixture, smoke=args.smoke)
    except (ValueError, OSError, TimeoutError) as error:
        print('watchdog: rejected: ' + str(error))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('status') in {'ok', 'no_op', 'skipped'} else 1
