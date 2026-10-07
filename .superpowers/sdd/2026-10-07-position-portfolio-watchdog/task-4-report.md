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

## Fix round 1/5 — Important #1, #2, #3 and Minors #1, #2 (review of 11b7939)

Scope: only `watchdog/mechanical.py`, `tests/test_watchdog_mechanical.py`, this report. TDD: all new assertions observed RED before any behavior change; reason codes unchanged except the new stable `protection_order_status_unknown`; no fabricated identity/totals; module stays pure (no I/O, inputs deep-compared unchanged).

### Important #1 — missing protective ref forces unknown regardless of live stops
`_protection_status` now returns `('unknown', None)` as soon as any ref fails to resolve (or any leg status is unrecognized), before any coverage combination. Coverage is omitted (`None`), not fabricated from the remaining legs. The report's earlier overstated claim ("missing refs force 'unknown'" implying live-stop combinations were covered) is corrected by this section: previously live stops plus a missing ref returned `covered` with combined coverage; that is no longer possible.

### Important #2 — unrecognized protective-leg status yields unknown with a stable reason
Any resolved leg whose broker status is neither live (`new/accepted/pending_new/pending_replace/held/open`) nor terminal (`canceled/expired/rejected`) now appends the new stable reason `protection_order_status_unknown` and forces `('unknown', None)` — even when another live stop exists. It is never silently dropped as `unprotected`, and `protection_stop_missing` is no longer emitted for a leg that resolved but is not live (terminal legs already carry their own reason; `protection_stop_missing` now means live evidence exists but none of it is a stop). Reason codes `protection_order_cancelled/expired/rejected`, `protection_ref_missing`, `protection_quantity_mismatch`, `protection_replacement_conflict` are unchanged.

### Important #3 — unexpected_exit narrowed to unattributed exits
`_unexpected_exits` cross-checks each filled sell against the broker order identities Task 3 attributed to the position (`position['fill_observations'][*]['broker_order_id']`). A lineage-attributed but non-protective exit (e.g. a replacement/manual flow Task 3 attributed) is managed activity and no longer reported `unexpected_exit`; only sells on the symbol that are neither protective nor lineage-attributed for the position are reported.

### Minors
1. Dead `ownership == 'discrepancy'` conditional in `observe_positions` flattened to `if remaining is None:`.
2. `aggregate_exposure` `excluded_positions[].reason='ownership_not_verified'` is now part of the documented stable reason set: observation reasons are the protection/horizon/quantity/exit codes above plus `concurrent_quantity_change`, `horizon_missing`, `horizon_invalid`, `horizon_session_entry_unknown`, `lineage_coverage_unknown`, `unexpected_exit`; aggregate reasons are `aggregate_excluded_positions` and `ownership_not_verified`.

### RED (before any mechanical.py change)
```
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_mechanical
# Ran 20 tests in 0.007s
# FAILED (failures=5), exactly:
#  test_cancelled_stop_reports_unprotected_without_repair          (protection_stop_missing emitted for resolved-but-not-live leg)
#  test_lineage_attributed_nonprotective_exit_is_not_unexpected    (attributed exit reported unexpected_exit)
#  test_missing_ref_forces_unknown_even_with_live_stops            ('covered' != 'unknown')
#  test_unrecognized_protection_leg_status_yields_unknown_with_stable_reason ('unprotected' != 'unknown')
#  test_unrecognized_status_forces_unknown_even_with_other_live_stop ('covered' != 'unknown')
```

### GREEN (after the fixes above)
```
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_mechanical -v
# Ran 20 tests in 0.008s; OK
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python tests/run_tests.py fast
# TIER_RESULT fast tests=328 failures=0 errors=0 skipped=0
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python tests/run_tests.py scenario
# TIER_RESULT scenario tests=162 failures=0 errors=0 skipped=0
python3 -m py_compile watchdog/mechanical.py tests/test_watchdog_mechanical.py
# Exit 0.
```

No live reads/calls; no autotrader/reconciliation edits; worktree-only.

## Fix round 1/5 (review 7946a40..11b7939)

Scope: three Important protection-status findings plus two specified minors (dead
conditional, undocumented `ownership_not_verified` code). No subagents; worktree
only; no control or writer changes.

RED first (tests written and observed failing before behavior changes):

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_mechanical
# Ran 20 tests; FAILED (failures=5) — exactly the new/extended assertions:
#   test_cancelled_stop_reports_unprotected_without_repair (stop_missing assertion)
#   test_missing_ref_forces_unknown_even_with_live_stops
#   test_unrecognized_protection_leg_status_yields_unknown_with_stable_reason
#   test_unrecognized_status_forces_unknown_even_with_other_live_stop
#   test_lineage_attributed_nonprotective_exit_is_not_unexpected
```

Fixes (watchdog/mechanical.py):

1. Important #1: an unresolvable protective ref now forces
   `('unknown', None)` unconditionally — no live-stop coverage may be combined
   from an incomplete protective set. This corrects the earlier report claim
   "missing refs force 'unknown'": previously `unknown` applied only when no
   live stop existed; now it applies in every missing-ref case.
2. Important #2: any resolved protective leg whose broker status is neither a
   known live status nor a known terminal status yields
   `protection_order_status_unknown` and forces `('unknown', None)` instead of
   being silently dropped with a factually wrong `protection_stop_missing`.
   `protection_stop_missing` is now emitted only when live evidence exists but
   none of it is a stop; resolved-but-not-live legs carry their own terminal
   reason.
3. Important #3: `_unexpected_exits` cross-checks the broker order identity of
   exits Task 3 attributed to the position (`fill_observations[].broker_order_id`);
   attributed-but-nonprotective managed exits no longer fire `unexpected_exit`,
   while genuinely unattributed filled sells still do (covered by a new test —
   `unexpected_exit` previously had none).
4. Minor #1: the dead `discrepancy` arm of the `remaining is None` conditional
   in `observe_positions` was flattened.
5. Minor #2: `aggregate_exposure.excluded_positions[].reason='ownership_not_verified'`
   is now part of the documented stable reason-code set (added here; codes are
   `protection_*`, `horizon_*`, `concurrent_quantity_change`, `unexpected_exit`,
   `lineage_coverage_unknown`, `aggregate_excluded_positions`,
   `ownership_not_verified`).

GREEN and verification:

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_mechanical -v
# Ran 20 tests in 0.008s; OK
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python tests/run_tests.py fast
# TIER_RESULT fast tests=328 failures=0 errors=0 skipped=0  (22 modules)
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python tests/run_tests.py scenario
# TIER_RESULT scenario tests=162 failures=0 errors=0 skipped=0  (9 modules)
python3 -m py_compile watchdog/mechanical.py tests/test_watchdog_mechanical.py  # exit 0
git diff --check  # clean
```

No live service called; no operational isolation failure. Remaining review
minors (flatten-order shadow comment, unknown-leg-kind reason, manifest
re-indent, multi-position aggregate test) are not in this round's scope.
