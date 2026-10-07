# Task 4 report — mechanical protection, horizon and concentration observation

## Status and scope

**DONE_WITH_CONCERNS: implemented RED-first, tested, self-reviewed and committed; independent parent review remains required before release.**

- Worktree: `/opt/data/projects/tradey-desk/.worktrees/position-watchdog`, branch `feat/position-watchdog`.
- Fix base verified: `ea1fd081a9df162109ba2c57f997ea577482d95f` (Task 3 fix round 2/5 head `7946a40`).
- Implementation commit: `1c1e0e4` (`feat(watchdog): observe mechanical protection, horizon and exposure`); this report is committed separately afterward.
- No subagents, no push, no live reads/calls, no operational writes, no schedule/control changes, no edits to autotrader/reconciliation/execution writers, no controller-ledger or whole-plan edits. Loaded the TDD skill before any code.

## Modified paths (explicit)

1. `watchdog/mechanical.py` — the two module-level pure functions plus helpers.
2. `tests/test_watchdog_mechanical.py` — 15 pure tests, registered fast.
3. `tests/test_manifest.json` — module classification only (fast tier).
4. `.superpowers/sdd/2026-10-07-position-portfolio-watchdog/task-4-report.md` — this handoff.

## Interface and behavior

Consumes only Task 1–3 public outputs: `LineageResult` positions and `BrokerSnapshot` normalized orders/positions/account. Pure functions; no broker calls, no I/O, no mutation (tests deep-compare all inputs before/after), no repair, no execution authority.

`observe_positions(lineage, broker, now) -> list[dict]` emits one observation per emitted lineage position (all nonzero managed exposures, including partial fills — it never filters on status=filled). Fields: identity (`position_id`, `candidate_id`, `symbol`), quantities (`entry_quantity`, `remaining_quantity`), and three independent statuses plus reasons:

- `ownership_status` — copied lineage observation, never upgraded.
- `protection_status` ∈ `covered` / `partial` / `unprotected` / `unknown` / `not_required`, with `protection_coverage_quantity`. Coverage is computed from exact broker order fields (actual `status`, `type`, `qty`/`filled_qty`, `stop_price`/`limit_price`), not from membership: live statuses `{new, accepted, pending_new, pending_replace, held, open}` only; canceled → `protection_order_cancelled`, expired → `protection_order_expired`, rejected → `protection_order_rejected`. A stop/target OCO pair covering quantity Q covers Q once (target legs take `min`, never add), not 2Q; duplicate serialized legs are deduplicated by client order identity and do not add coverage. Live leg quantity ≠ remaining → `protection_quantity_mismatch` (reported, not adjusted). Multiple live stops with differing stop prices → `protection_replacement_conflict`. Missing refs → `unknown` with `protection_ref_missing`; a target with no stop → `unprotected` + `protection_stop_missing`.
- `horizon_status` ∈ `active` / `horizon_expired` / `unknown`: timezone-aware `now` (naive `now` raises `ValueError`) compared with the original `planned_exit_at`; missing → `horizon_missing`; unparseable/non-aware → `horizon_invalid`. Session-count horizons stay `unknown` (`horizon_session_entry_unknown`) because no validated entry-session evidence exists in the Task 1–3 outputs; missing/invalid calendars can therefore never produce an expiry verdict.
- `quantity_status`: `concurrent_quantity_change` when `remaining_quantity is None` (exact exits exceed entry mid-observation) with reason `concurrent_quantity_change`; reported, never repaired. Filled sells on the symbol outside the position's protective set → `unexpected_exit` (report only).

`aggregate_exposure(positions, broker) -> dict` sums only verified managed value (`managed_invested_value` = entry − exit notional of `ownership_status == 'verified'` observations). Weights carry explicit denominators: `weight_within_managed` / `weight_denominator='managed_invested_value'`; `weight_vs_sleeve_equity=None` with `sleeve_denominator='sleeve_equity_pending'` until Task 5 supplies sleeve equity. Full account equity appears only as `account_equity_secondary` (separately labeled secondary view, never strategy value). Non-verified positions are listed in `excluded_positions`; broker positions without exact managed ownership are `legacy_holdings` with `attributed=False` (legacy/manual lots are never acquired). `classification='unknown'` — nothing is classified without structured evidence.

Reasons are stable private codes: `protection_ref_missing`, `protection_order_cancelled`, `protection_order_expired`, `protection_order_rejected`, `protection_stop_missing`, `protection_quantity_mismatch`, `protection_replacement_conflict`, `unexpected_exit`, `concurrent_quantity_change`, `horizon_missing`, `horizon_invalid`, `horizon_session_entry_unknown`, `lineage_coverage_unknown`, `aggregate_excluded_positions`.

## TDD evidence — exact commands and observed results

All commands ran from the worktree. RED was a genuine missing-feature failure (`ModuleNotFoundError: No module named 'watchdog.mechanical'`, 15 errors), not silently passing tests. Two intermediate fix rounds were observed failing before their fixes:

```sh
# RED: full module missing
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_mechanical -v
# Ran 15 tests; FAILED (errors=15) — ModuleNotFoundError watchdog.mechanical

# Fix 1 RED (duplicate legs): duplicate serialized nested leg added coverage
#   protection_coverage_quantity Decimal('4') != Decimal('2')  -> dedupe by client order id
# Fix 2 RED (missing ref): status 'covered' != 'unknown' for a ref absent from
#   the broker tree -> missing refs force 'unknown'
# GREEN after fixes:
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_mechanical -v
# Ran 15 tests in 0.006s; OK
```

Final verification commands/results:

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_mechanical -v
# Ran 15 tests in 0.006s; OK
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python tests/run_tests.py fast
# TIER_RESULT fast tests=323 failures=0 errors=0 skipped=0  (22 modules)
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python tests/run_tests.py scenario
# TIER_RESULT scenario tests=162 failures=0 errors=0 skipped=0  (9 modules)
git diff --check
# Clean.
python3 -m py_compile watchdog/mechanical.py tests/test_watchdog_mechanical.py
# Exit 0.
```

No `OPERATIONAL_ISOLATION_FAILURE` in either tier. No live service was called. Full-only suite and release smoke were not run for this task.

## Self-review, limitations and concerns

- Reviewed the full diff before the explicit-path commit: only the new pure module, its tests and the manifest classification changed. No execution writer, serializer, payload, hash or policy touched; mechanical imports only `watchdog.types` and stdlib.
- One test premise was corrected during the cycle: a protective ref whose leg still exists in the broker tree is not "missing" (the tree is the ref source); the missing-ref test now injects an absent ref into the lineage projection, which is the contract mechanical must defend.
- **Concern: fresh parent scoped re-review is still required; this is not release approval.**
- **Concern: session-count horizons and entry-session evidence.** `horizon` fields that are session counts stay `unknown` because Task 1–3 outputs carry no validated entry session date; a later task supplying that evidence must extend `_horizon_status`, keeping invalid sessions unknown.
- **Concern: stop-price-proximity exits.** `unexpected_exit` detects filled sells outside the protective set; an exit via a live protective leg is by construction expected. Filled exit legs reduce coverage to the unfilled remainder rather than being treated as protection.
- Consumers must still honor top-level lineage coverage (`lineage_coverage_unknown` reason) and Task 3's `delta_status='unknown'`; mechanical adds no completeness beyond its inputs.
