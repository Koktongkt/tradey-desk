# Task 5 — accounting and benchmark implementation report

## Scope and result

Base: `70be673`. Only Task 5 source, its two unit-test modules, fast-manifest registration and this report changed. No runner, broker writes, operational-history repairs, live probes, pushes, services, schedules, credentials or trading-control changes. Independent frozen-diff review is reserved for the parent.

Created `watchdog/accounting.py`, `watchdog/benchmark.py`, `tests/test_watchdog_accounting.py`, `tests/test_watchdog_benchmark.py`. Modified `tests/test_manifest.json` to register both modules in fast. All amounts/ratios/returns calculated in memory are Decimal; timestamps and sample counts remain integers/strings. Inputs are not mutated.

## RED / GREEN evidence

Focused command throughout:

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_accounting test_watchdog_benchmark -v
```

- Initial module absence produced import errors. Converted the module-presence checks to assertions and reran before production implementation: **2 tests, 2 expected failures**, accounting/benchmark not implemented. First tracer bullets then **2 PASS**.
- Coverage/execution slice: **11 tests, 8 failures and 1 missing-output-field error** before implementation; then **11 PASS**.
- Prospective baseline/adjustment/account-view slice: **18 tests, 7 failures** before implementation; then **18 PASS**.
- Benchmark validation/comparison slice: **25 tests, 5 failures and 2 missing-behavior errors** before implementation; then **25 PASS**.
- Self-review cash chronology/cumulative validation/supplemental split evidence: **31 tests, 3 failures**; fixes produced **31 PASS**.
- Self-review event-shape isolation, independent planned geometry, required opening inventory, publication clock and intraday comparison: **37 tests, 5 failures**; then **37 PASS**.
- Raw-account observation preservation and repeating split-basis regression: targeted two-test command (`test_watchdog_accounting.AccountingTests.test_split_retains_total_cost_without_repeating_unit_price_drift` and `test_watchdog_accounting.AccountingTests.test_account_observations_retained_without_cashflow_performance`, same dependency wrapper): **2 failures**, including Decimal `99.99999999999999999999999999` versus exact `100`; fixed by retaining total lot basis, not repeating unit prices.
- Prior-mark provenance / New York date regressions: full focused run **42 tests, 1 failure and 2 fixture errors**. Corrected missing order-status fixture and an exclusive interval boundary before changing product behavior. Targeted New York date test then failed on UTC date `2026-10-07` versus session date `2026-10-06`. Both behaviors fixed. Real `build_lineage` output is exercised by a pure unit fixture.
- Extended independent-account-flow test with stale/incomplete broker snapshot: targeted test **1 failure** (wrongly returned `.01`); added snapshot completeness/reason gating.
- Final focused: **42 PASS** (32 accounting, 10 benchmark), 0 failures/errors/skips.

Fixture expectations were checked using `python3 -c` with Decimal: cash `9910`, equity `10015`, realized `10`, unrealized `5`, return `.0015`; dividend `3` minus fee `2` gives cash `9911`/equity `10016`; prospective opening gives `10005`; account net-flow-adjusted return `(51500-1000-50000)/50000 = .01`; sample drawdown `10015/10100-1`.

Final regression commands (temporary unit-test files confined to this worktree):

```sh
mkdir -p .task5-tmp
PYTHONPATH=.:tests TMPDIR="$PWD/.task5-tmp" uv run --with 'fastmcp<4' python -m unittest test_watchdog_accounting test_watchdog_benchmark -v
TMPDIR="$PWD/.task5-tmp" uv run --with 'fastmcp<4' python tests/run_tests.py fast
TMPDIR="$PWD/.task5-tmp" uv run --with 'fastmcp<4' python tests/run_tests.py full
rmdir .task5-tmp
```

Results: focused **42 PASS**; fast **24 modules / 370 PASS**; full **35 modules / 650 PASS**; no failures/errors/skips. Full includes the scenario modules. Expected pre-existing fixture diagnostic prints (`BLOCKER`, `SYSTEM_FAILURE`) are not test failures.

An initial fast run using `TMPDIR=$PWD/test_artifacts/watchdog_task5/tmp` produced **2 failures / 7 errors**, all in existing SQLite-ledger tests. Inspected `_storage_root`: a `test_artifacts` ancestor makes all temporary roots share one database, invalidating those tests' isolation. Changed only the test-command environment to an ephemeral worktree `.task5-tmp` directory, not ledger code: targeted SQLite **16 PASS**, then fast/full green. No operational source was modified. Test artifact outputs stayed isolated in the worktree.

Static AST parse/security scan over all four new Python files found no shell execution, eval/exec, unsafe deserialization or credential assignments. `git diff --cached --check` clean. Self-review is not independent review.

## Reusable interface schema for Task 8

### `account_strategy(lineage: LineageResult, broker: BrokerSnapshot, baseline: dict, prior_snapshots: list[dict]) -> dict`

Consumes the actual Task 3 position fields: `position_id`, `symbol`, `ownership`, `remaining_quantity`, `fills` and `fill_observations`; `stop` is trusted immutable intent geometry. Only `fills` represent executions: `activity_id`, `broker_order_id`, `side`, `quantity`, `notional`, aware `timestamp`. Each execution is cross-checked against exact broker activity identity, symbol, side, quantity, price, timestamp and normalized field provenance. Duplicate identical activity IDs count once; conflicts fail. Cumulative observations validate inception totals but are never replayed. No journal or operational writes.

Baseline required fields:

```text
version: nonempty immutable version identifier
mode: inception | prospective
at: aware ISO timestamp
initial_capital: "10000"
provenance: independently verified allocation/baseline evidence reference
opening_positions: [] or exact dated prospective opening rows
inception_at: required for inception, identical to at
coverage: executions/fees/distribution/corporate_actions ->
          {start: aware ISO, end: aware ISO, provenance: evidence reference}
adjustments: [] or exact allocated adjustment rows
```

Coverage intervals must encompass baseline through broker capture, independently of the adapter's complete/trusted flags. Broker activity query bounds must strictly enclose that interval because its creation-time bounds are exclusive. **The runner must supply genuinely audited history-inventory evidence; copying broker completeness or a requested interval into this object does not prove inception history.** Provenance references are trusted deterministic/private inputs, never model assertions, and are not remotely resolved by this pure function.

Prospective openings: `{position_id, symbol, quantity, price, at, provenance}`. `at` equals baseline timestamp; quantity and mark must be positive, ownership identity exact. Opening analytical FIFO basis uses these dated marks, cash starts as `10000 - opening value`. Earlier fills are not replayed. Inception return remains `None`; capital label is `10000 at baseline`. No automatic invented baseline/mark is created when evidence is missing.

Adjustment rows: `{activity_id, position_id, kind, timestamp, provenance, amount}` for `fee` / `distribution`, or `ratio` for `split`. Allocation/entitlement evidence must be exact, not a symbol join. Broker identity, date, symbol, type, field provenance and cash amount corroborate the row. Costs are negative cash movements; distributions positive. Splits change lot quantity while retaining total lot basis. Unknown/unallocated actions withhold accounting. A specifically identified broker `corporate_actions_coverage_unknown` can be resolved only with complete exact action evidence and independent coverage; no other broker failure or unknown lineage ownership is upgraded.

Output: `scope=actual_managed_strategy`, immutable `initial_capital=Decimal(10000)`, baseline version/mode/at and capital label, snapshot `at`, `cash`, `managed_market_value`, `marked_equity`, gross `realized_pnl` / `unrealized_pnl`, separate `costs` / `distributions`, `return`, `inception_return`, `return_kind`, `drawdown`, position quantities/basis/value/mark provenance/weight versus evolving sleeve equity, independent `conditional_planned_loss` and non-guarantee label, marked `observations`, `mark_provenance`, `valuation_basis=broker_snapshot`, `coverage` and typed `reasons`. Unsupported accounting totals are `None`, not zero. Coverage counts managed positions, distinct event IDs, valid mark samples and gaps. Negative cash (globally ordered across all positions), oversells and quantity discrepancies are errors, never clipped.

Prior snapshots are previously verified same-version output objects (or equivalent `{at, baseline_version, marked_equity, mark_provenance, coverage.status}` projections). Missing or unproven marks become gaps, not carried equity. Dates are New York session dates. Drawdown is observed peak-to-trough, not an estimate of unobserved intraday drawdown.

### `account_overview(broker: BrokerSnapshot, prior_snapshots: list[dict]) -> dict`

Publishes `scope=full_account_secondary`, broker `equity`, `cash`, field provenance, raw `equity_observations`, coverage/reasons even when performance cannot be calculated. Strategy allocation is never enlarged by account deposits or legacy gains.

Independent account baseline is supplied explicitly inside a prior object as:

```text
account_baseline: {version, at, equity, provenance,
                  flow_coverage: {start, end, provenance}}
```

Contradictory account baselines, incomplete/stale snapshots, missing external-flow history and unclassified transfers withhold account return/drawdown. Supported verified CSD/CSW activity identities are deduplicated, sign checked and subtracted from marked equity. An opening-day date-only flow after a non-midnight baseline is ambiguous and fails closed. Return methodology is explicitly `net_flow_adjusted_pnl_over_initial_equity_not_time_weighted`; it is not TWR/IRR. Persist output's `flow_adjusted_equity`, `account_baseline_version`, provenance and coverage for its observed flow-adjusted curve.

### `load_benchmark(start: str, end: str) -> dict`

Canonical inclusive **completed trading-session date endpoints**, ordered and bounded range. Reads existing authenticated `market_data._massive_json` (therefore the already-configured Massive credentials), not broker MCP or a placeholder adapter. Fixed SPY aggregate-range read uses `adjusted=true`, ascending order and bounded limit; fixed dividend-reference read requests SPY ex-date facts. Does not follow arbitrary `next_url`; pagination/count/adjustment/date/value errors fail closed. No nearest-session fallback. Current-day publication is conservatively withheld before 16:15 New York (including early-close days until this conservative cutoff).

Outputs deterministic source/date/price fields, Decimal values and dividend facts with provenance; errors are sanitized reason codes. Default is always `return_kind=price_return_only`, `adjustment=split_adjusted`, distribution `status=unverified`. Successful raw dividend reads alone do not verify compatibility with split-adjusted bars or reinvestment.

### `compare_benchmark(strategy: dict, benchmark: dict) -> dict`

Requires actual managed strategy, complete accounting, same explicit `10000` starting capital and exact common endpoints. **Broker snapshot marks are not automatically completed-session-close marks.** A trusted synchronization adapter must supply `valuation_basis=completed_session_close`, `valuation_provenance`, and exact dated observation values/provenance; absent that, comparison is withheld. Do not merely relabel intraday snapshots. Multiple observations on one date must be deliberately projected to a verified close; ambiguous duplicate dates fail closed.

Computes returns and observed drawdowns on synchronized valid dates only, missing-date lists and sample counts; no interpolation. Default excess is explicitly `excess_price_comparator`, and `excess_total_return=None`.

A verified distribution input may enable total return only with exact range, `status=verified`, capability/basis `provenance`, `reinvestment=ex_date_close`, `expense_treatment=embedded_in_proxy_price` and `{date, amount, provenance}` observations already verified compatible with the split-adjusted price basis. Opening-date distributions are not earned after the starting close. Missing distribution-date prices or malformed evidence falls back to labeled price-only. Total-return excess requires verified strategy total-return coverage too. Research/shadow inputs never compare; outputs state descriptive observations, not statistically validated alpha.

## Requirement-to-test mapping

All names below are in the two new fast modules.

| Requirement | Tests |
|---|---|
| Exact 10000/B2@100/S1@110/mark105 arithmetic, idle cash, Decimal, no mutation, evolving weights | `test_fifo_partial_exit_and_idle_cash` |
| Partial exits, FIFO multiple entries, exact activity contracts | `test_fifo_multiple_entries_stays_with_exact_position`, `test_real_lineage_activity_contract_supplies_accounting_events` |
| Cumulative observations versus events, duplicates/conflicts, precise broker evidence | `test_cumulative_observations_never_become_events`, `test_broker_cumulative_totals_validate_but_never_replay_events`, `test_duplicate_activity_deduplicated_but_conflict_rejected`, `test_execution_needs_broker_activity_provenance`, `test_lineage_fill_cannot_masquerade_as_cash_adjustment` |
| Complete source flags do not prove inception; exclusive coverage boundaries | `test_source_flags_do_not_prove_inception_history`, `test_exclusive_broker_interval_must_enclose_baseline` |
| Explicit dated prospective basis, no inception claim, required opening inventory | `test_explicit_dated_prospective_opening_marks`, `test_prospective_requires_explicit_opening_inventory` |
| Initial capital separate from account/cap; legacy gain/deposit not alpha | `test_allocation_not_inferred_from_cap`, `test_legacy_gains_and_deposit_only_affect_account_view`, `test_empty_sleeve_retains_idle_cash_without_claiming_legacy_gains` |
| Negative cash/discrepancies not clipped; global cash chronology | `test_negative_cash_and_oversell_are_errors_not_clipped`, `test_cash_timeline_is_global_not_position_iteration_order` |
| Costs/distributions with provenance and exact entitlement; unknown costs withheld | `test_verified_dividend_and_fee_have_explicit_allocation`, `test_unallocated_symbol_dividend_cannot_be_inferred`, `test_unknown_fees_or_distributions_withhold_totals` |
| Split evidence, invariant total basis, unsupported corporate actions unknown | `test_verified_split_preserves_lot_basis`, `test_split_retains_total_cost_without_repeating_unit_price_drift`, `test_incomplete_broker_split_can_be_resolved_only_by_exact_evidence`, `test_unsupported_corporate_action_never_fabricates_adjustment` |
| Planned geometry separate from equity and guaranteed-loss language | `test_fifo_partial_exit_and_idle_cash`, `test_missing_stop_does_not_withhold_equity`, `test_geometry_does_not_depend_on_inception_accounting_coverage` |
| Account cash/equity observations retained; independent baseline/flow coverage required | `test_account_observations_retained_without_cashflow_performance`, `test_account_return_requires_independent_baseline_and_cashflow_inventory`, `test_legacy_gains_and_deposit_only_affect_account_view` |
| Mark provenance, missing-mark gaps, valid sample drawdown, session dates | `test_missing_mark_is_gap_not_carried_forward`, `test_prior_curve_needs_mark_provenance_not_only_complete_flag`, `test_equity_curve_filters_gaps_and_other_baselines`, `test_session_dates_use_new_york_not_utc_calendar_day` |
| Real existing Massive helper and fixed endpoints, price-only labels | `test_real_loader_uses_existing_massive_helper_price_only`, `test_loader_reads_distribution_facts_but_does_not_invent_capability` |
| Stale dates/pagination/invalid prices, bounded failures/no secret leakage/publication cutoff | `test_loader_rejects_stale_dates_pagination_and_bad_prices`, `test_loader_network_failure_is_sanitized_and_bad_range_never_reads`, `test_current_uncompleted_session_rejected_before_network` |
| Synchronized dates/equity, sample counts, no interpolation or intraday-close conflation | `test_synchronized_price_comparison_withholds_total_excess`, `test_date_gaps_and_stale_endpoint_are_not_interpolated`, `test_intraday_broker_marks_are_not_completed_close_comparison` |
| Verified reinvestment/expense treatment; otherwise no total-return excess | `test_verified_distribution_reinvestment_enables_total_excess`, `test_synchronized_price_comparison_withholds_total_excess` |
| Actual/research/shadow separation, no unsupported probability/alpha confidence claims | `test_research_shadow_unknown_and_conflicting_dates_do_not_compare`; comparator has no conviction/probability input and reports descriptive inference only |

## Rulings and remaining coverage limitations

- Pure accounting cannot autonomously select a defensible dated baseline without verified opening marks. It accepts an explicitly documented prospective baseline and otherwise fails closed. The exposure cap, source/trusted booleans, cumulative totals and current account equity are not history evidence.
- P&L fields are gross trading FIFO P&L, with verified costs/distributions separately reported and included in cash/equity. Prospective opening basis is analytical opening marked value, not an invented historical tax basis.
- Account net-flow-adjusted P&L over initial equity is disclosed, not called time-weighted return. Journal/security transfers (`JNLC`, `ACATC`, `ACATS`, `JNLS`) remain unclassified/unknown; no fabricated deposit amount or security valuation.
- Non-split reorganizations and uncertain entitlements remain unknown. A single aggregate dividend/fee across multiple ideas is not guessed into lots. Account-wide fees lacking exact symbol/position evidence remain a limitation. Split support needs exact independently verified lot ownership and adjusted remaining quantities; the current lineage builder may itself report unknown/discrepancy on a live split. This task never overrides that ownership result.
- Raw broker-mark observations stay broker snapshots. Task 8 must obtain verified completed-close synchronization evidence or retain an unavailable comparator rather than relabel those marks. Missing intermediate marks reduce observed drawdown coverage; no unseen-path claim is made.
- Loader dividend facts are useful evidence but remain unverified for total-return computation until release capability checks establish split-basis compatibility, ex-date reinvestment and proxy expense treatment. Pagination is deliberately a coverage blocker, not silently ignored.
- **Live Massive/broker capability probe explicitly deferred to Task 9.** No configured key read or live request was performed here; normal tests patch only the existing network helper and clock. Independent reviewer and release/live authorization remain with the parent. No scheduler or operational controls changed.

## Review repair round 1 — I1 / I2 / I3

Fix base: `b047d0f`. Scope: `watchdog/accounting.py`, `tests/test_watchdog_accounting.py`, append-only additions to this report. Task 3 lineage/broker/types contracts and source are unchanged. No progress file, manifest, controls, scheduler, live requests, credentials, subagents or pushes changed/performed. Read project AGENTS, Task 5 brief/review and design §7 before repair. Fresh frozen-diff re-review remains with the parent; self-review is not independent acceptance.

### Regression evidence (RED before each behavior repair)

All focused commands use `PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest ... -v` (or `-q` for the whole focused suite).

| Finding | Test names (`test_watchdog_accounting.AccountingTests`) | Observed RED | Observed GREEN |
|---|---|---|---|
| I1 broker mark evidence/reconciliation | `test_normalized_market_value_contradiction_withholds_performance`, `test_normalized_market_value_requires_provenance`, `test_market_value_reconciles_same_symbol_ideas_in_aggregate` | 3 tests / 3 failures: published 10015 despite broker 999, published return without value provenance, ignored a .00000001 aggregate contradiction | Accounting module 35 PASS after repair; final focused includes all 3 PASS |
| I2 verified date basis, equivalent offsets and both boundaries | `test_account_flow_equivalent_offsets_and_both_boundaries_are_unknown`, `test_account_flow_date_basis_must_be_verified`, `test_exact_proven_flow_time_resolves_boundaries` | 3 tests / 3 failures: UTC spelling reported .02; missing basis reported 0; exact proven opening flow unresolved | Accounting module 38 PASS after repair; final focused includes all 3 PASS |
| I3 rounded derived observation versus exact events | `test_real_lineage_rounded_average_preserves_exact_event_cash`, `test_rounded_average_without_verified_precision_is_unknown`, `test_rounded_average_rejects_material_difference_and_missing_events` | 3 tests / 2 failures: valid real lineage reported error; absent precision mislabeled contradiction. Material/missing-event guard already passed (preserved coverage, not claimed as new RED). | Focused 51 PASS after repair, then 52 PASS with rounding-cell audit test |
| Self-review I1 missing evidence must not invent contradiction | Extended `test_missing_mark_is_gap_not_carried_forward` | 1 test / 1 failure: missing mark incorrectly classified error by the new aggregate check | Final focused 52 PASS; aggregate comparison now runs only when marked quantity is complete |

Added `test_verified_rounding_cell_ties_and_invalid_precision` as an audit of the already-green Decimal rounding helper: HALF_EVEN inclusive even/exclusive odd ties, just-outside-cell rejection, absent provenance, unsupported rounding and invalid quantum. It passed without a product behavior change; not claimed as RED evidence.

### Precision decisions and downstream input schema

**I1:** Require normalized broker `market_value` provenance in addition to quantity/current price. Compare sum of exactly owned idea values for each symbol against its single broker position value, only after exact aggregate quantity reconciliation and complete marks. Do not compare each idea against the whole symbol value, do not attribute legacy holdings, and do not turn unavailable marks into discrepancies. Precision policy is **exact Decimal equality with zero tolerance**: no verified broker market-value rounding policy exists in this task. The fractional fixture uses normalized quantity 2, price 105.12345678, value 210.24691356; a one-unit last-place discrepancy is rejected. Existing mark fixtures now carry realistic market-value/provenance evidence and changed quantities carry consistent value. If real broker value rounding prevents equality, downstream must retain incomplete/error accounting until an independently verified policy is separately specified; no assumed cents tolerance.

**I2:** Add independently verified account baseline evidence:

```text
account_baseline.flow_coverage.date_basis:
  timezone: explicit IANA timezone identifier
  provenance: independently verified broker activity-date contract reference
```

No timezone default is inferred from ISO spelling, exchange session dates, the query creation-time basis, or a completeness flag. Missing/invalid basis withholds performance with `account_flow_date_basis_unknown`, even if the inventory is empty. Convert both baseline and capture instants into that verified basis before interpreting activity dates. Date-only flows on **either boundary day** fail closed with `account_flow_boundary_unknown`, including midnight; date alone cannot order a flow relative to an instant. A genuine normalized `transaction_time` with its own provenance may resolve timing, must agree with the verified activity date basis, and uses the explicit `(baseline, capture]` interval. `created_at` is never a substitute. The fixture New York basis is explicit test evidence, **not a live-verified assertion about Alpaca**. Existing .01 account-return fixture moves its deposit to an unambiguous interior date; it does not invent a timestamp for a date-only row. Raw account observations remain available when performance is withheld.

**I3:** Task 3 output remains unchanged. Identify average-derived cumulative observations by exact order ID in the existing normalized broker order tree (including legs), corroborated filled quantity/average provenance, and `cumulative_notional == filled_qty * filled_avg_price`. Exact event notionals and quantities remain the only FIFO/cash inputs. Exact cumulative quantity must always match; uncorroborated/exact-notional discrepancies stay errors. For a differing **corroborated average-derived** notional, accept only an independently verified precision policy supplied in the versioned strategy baseline:

```text
baseline.average_price_precision[broker_order_id]:
  quantum: canonical positive power-of-ten Decimal string (e.g. "0.00000001")
  rounding: "ROUND_HALF_EVEN"
  provenance: independently verified broker average-price precision/rounding reference
```

Never derive the quantum from the number of displayed decimal places. This release supports only the explicitly named HALF_EVEN policy, not arbitrary tolerance. Validate the exact notional against the rounding cell of the reported average in **notional space**: `abs(exact_notional - quantity * average) < quantity * quantum / 2`; equality at either endpoint is valid only for an even average/quantum integer. The helper uses an operand-sized local Decimal context for finite products/endpoints, never floats or a rounded division of exact event totals. Absent/unverified policy returns `execution_precision_unknown` (unknown, not a false exact contradiction), withholds totals, and never invents a precision contract. Real-lineage fixture 1@100 + 2@101 retains exact buy notional 302 despite derived 302.00000001; sale 1@110 gives cash 9808, remaining basis 202, value 210, equity 10018 and realized 10. Verified 1e-8 quantum rejects averages 100.66666668 and 100.67 and missing execution events. The test policy is a hypothetical verified input, **not live Alpaca capability evidence**.

No Task 3 additive fields were needed. Existing result shapes remain unchanged; new typed reasons are `broker_market_value_discrepancy`, `account_flow_date_basis_unknown`, and `execution_precision_unknown`. Task 8 must persist/audit these versioned baseline inputs and keep unavailable evidence unknown, rather than fill them from formatting or defaults.

### Final verification / self-review

Executed after the missing-mark self-review repair:

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_accounting test_watchdog_benchmark -q
uv run --with 'fastmcp<4' python tests/run_tests.py fast
uv run --with 'fastmcp<4' python tests/run_tests.py full
git diff --check
```

Actual results: **focused 52 PASS** (42 accounting + 10 benchmark), **fast 24 modules / 380 PASS**, **full 35 modules / 660 PASS**; failures=0, errors=0, skipped=0. Used the configured persistent scratch TMPDIR, not a `test_artifacts` temporary ancestor; no SQLite fixture isolation failures. Existing expected `BLOCKER`, `SYSTEM_FAILURE` and `DECISION` fixture diagnostic prints are not test failures. AST parsing passed for both changed Python files; added-line static security scan found no shell injection, eval/exec, unsafe deserialization or credential assignments. Inspected the full source diff for coverage downgrades, quantity/event conservation, source identity, rounding boundaries, date-basis assumptions and absent-mark classification. `git diff --check` was clean.

Remaining integration concerns are explicit, not papered over: verified activity-date basis and average-price rounding capability must be supplied by audited runtime evidence; exact market-value reconciliation may conservatively withhold genuinely rounded broker values until a separately reviewed policy exists; live capability checks and independent re-review remain deferred. No timestamp, precision, cutoff, baseline or zero-cost evidence was synthesized to force completeness.
