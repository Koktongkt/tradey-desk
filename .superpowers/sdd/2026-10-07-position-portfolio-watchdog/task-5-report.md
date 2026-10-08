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
