# Task 2 — broker read adapter report

Status: DONE_WITH_CONCERNS (implementation/tests complete; provider-payload smoke and independent parent review remain release gates).

## Scope and commits

- Worktree: `/opt/data/projects/tradey-desk/.worktrees/position-watchdog`, branch `feat/position-watchdog`.
- Starting commit: `99a1db15ea4ca5770cbfcb15f5914e568ccec549`.
- Implementation commit: `e232c106d671bf9f99e27e3dfee56a6a6176aeab` (`feat(watchdog): add strict paper broker read adapter`).
- Explicit implementation paths: `watchdog/broker.py`, `tests/test_watchdog_broker.py`, `tests/fixtures/watchdog_broker_schemas.json`, `tests/test_manifest.json`.
- This report is committed separately; obtain final task tip with `git rev-parse HEAD` rather than embedding a self-referential report commit hash.
- No push, no live checkout edits, no control/job/config changes, no operational appends, no subagents, no broker writes.

## Delivered interface and boundary

`ReadOnlyAlpaca(client, tool_schemas)` and async `call(name, values)` implement an exact actual-invocation allowlist. The allowlist is only:

1. `get_account_info`
2. `get_all_positions`
3. `get_orders`
4. `get_order_by_client_id`
5. `get_calendar`
6. `get_account_activities`

Unknown names and writes are rejected before transport, including a write tool explicitly present in the supplied catalog. No wildcard `get_*`, arbitrary operation dispatch, symbol-based historical lookup, or bridge placement/protection dispatch is used.

Each request checks the deterministic logical parameter set, fixed values, types (including bool/int distinction), supported live fields, required live fields, enums and numeric bounds, then full JSON Schema constraints before `client.call_tool`. Existing `tool_arguments` is reused and its result must equal the requested values: no dropped logical fields or false completeness/feed claims. Schema references are forbidden, avoiding secondary schema-fetch network calls. The discovered schema dictionary is copied, and validated schemas/validators are cached per reader.

`collect_broker(reader, refs, start, end)` returns the exact Task 1 `BrokerSnapshot` dataclass, with Decimal money/quantities in memory, allowlisted compact broker fields, source-field provenance, nested legs, cumulative fill quantity/average price and timezone-aware fill timestamps. Account IDs and raw errors/responses are discarded. Exact reference readback identities are verified; nested legs are not appended as duplicate standalone orders. Inconsistent repeated open/reference observations mark references unknown rather than selecting one as broker truth.

`collect_configured(payload)` is the deterministic credential-bearing worker. `python -m watchdog.broker` accepts only `{refs,start,end}` on stdin, emits normalized private snapshot JSON with Decimal strings, and emits only `{"error": "broker_read_failed"}` on stderr with exit 3 on outer failure. Existing `alpaca_mcp_config`/credential loader enforce paper mode before starting `Client`. Models/CLI thesis callers must use the worker subprocess rather than calling this credential-bearing function in a model process. The later Task 8 integration is responsible for that parent-side subprocess launch.

## Catalog provenance (real discovery, not live account reads)

Executed from this isolated worktree:

```sh
uv run --with 'fastmcp<4' python broker_mcp_bridge.py tools > test_artifacts/watchdog-tool-schemas.json
```

Exit 0. This inspected the already-read bridge's `tools` branch (`Client.list_tools` only), never `operation`. It returned 47 tool schemas. Startup banner reported FastMCP 3.4.7. No account, positions, orders, activities, credentials, or resolved config were queried/printed during this discovery.

- Full catalog SHA-256: `1a3065263a947af9985766a16ebdd9cfaf208e4ead975189a366c75af92ed74f`.
- Committed six-tool fixture SHA-256: `9cd1d6a39c785048b89731ced657d2cb58cfc8df10924c1ce22976feb9f0191d`.
- Fixture is the exact six selected schema objects from that actual catalog, not an authored approximation. Full discovery remains in ignored `test_artifacts`.
- `get_account_activities` is actually present. Its verified interval parameters are `after`/`until`; pagination is `page_size` (max 100) and `page_token` (last activity ID). No category/type filter is sent, so account activities are not narrowed to fills only.
- `get_orders` has `status`, `nested`, `limit`, `direction` and `before_order_id`. The ID cursor avoids timestamp-tie omissions inherent in exclusive `until` pagination.
- Calendar explicitly sends `date_type=TRADING` with both bounds.

## Coverage and normalization decisions

- Per-domain coverage values are `complete` or `unknown`: account, positions, orders, references, calendar, activities, account_cashflows, distribution, fees, corporate_actions. `coverage.reasons` supplies sanitized typed codes; global `complete` is false if any reason remains.
- Activities coverage is only the requested exclusive broker-creation-time interval, not settlement dates, account lifetime, or total-return proof. `coverage.interval`, `activity_time_basis`, and `accounting_scope` disclose this. Late-posted fees/distributions require the later accounting/source-cutoff overlap policy; this adapter does not fabricate missing activity.
- Missing/invalid activities capability sets `account_cashflows_unknown`, `distribution_coverage_unknown`, fees/corporate-action unknown, and an incomplete snapshot. An empty successful activities list is distinct from an unavailable/malformed list.
- Orders page at 500, activities at 100, using their exact schema-validated cursor fields. A short valid page is terminal under the verified list API contract. Missing cursor support on a full page, duplicates/repeated cursors, oversized pages, page-cap exhaustion, malformed next pages, explicit partial flags, ambiguous envelopes, and declared-count mismatches cannot produce complete coverage. Already validated partial pages may be retained only with unknown coverage.
- Maximum 20 pages per collection, 15 seconds per read, one shared 60-second collection deadline. References are bounded to 500 and deduplicated exactly; no invented client IDs or ticker/time joins. Outer catalog discovery has a 30-second timeout.
- Numeric timestamps are rejected rather than guessing seconds/milliseconds. Supplied snapshot timestamps must be aware, not future, and at most 60 seconds old; the collection itself is also freshness checked. Historical filled_at remains an execution timestamp, not a current-snapshot age check.
- Required monetary/quantity fields, finite values, positive order quantity/prices, cumulative fills in `[0,qty]`, side domains and fill metadata are validated. Missing filled_at for a positive cumulative fill stays unknown; no invented execution time. Signed short holdings are account observations, never new trading authorization.
- Calendar date/open/close fields are compactly normalized to America/New_York aware open_at/close_at, preserving original field provenance.
- Text and structured MCP content are supported; error flags, raw text errors and invalid envelopes stay unknown. Raw transport exception strings never enter the snapshot or worker error JSON.
- Corporate-action activity existence does not prove split ratios/lot adjustments: security/corporate-action observations without adjustment evidence explicitly make corporate_actions unknown. Unsupported activity types cannot silently become zero cashflows. Concrete activity types came from the catalog enum.

## TDD execution record

All commands below were run in the isolated worktree. Missing-module/import errors in the initial RED slices were the expected absence of the new implementation, not dependency-install failures. Later REDs fail specific assertions. Normal tests use offline fixture transports/mocked configuration; the invalid-payload subprocess test rejects input before credentials or server startup. No normal test calls live services.

### 1. Invocation boundary

RED command:

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker -v
```

Observed output: `ModuleNotFoundError: No module named 'watchdog.broker'`; `Ran 1 test in 0.008s`; `FAILED (errors=1)`; exit 1.

Same command GREEN after exact allowlist implementation: `Ran 1 test in 0.007s`; `OK`; exit 0.

### 2. Required logical/schema arguments

Same focused command RED: `ValueError not raised` for injected action, changed status/nested, numeric bool, missing logical fields, removed nested schema, new live required field, altered enum/type; `Ran 3 tests in 0.028s`; `FAILED (failures=11)`; exit 1.

Same command GREEN: `Ran 3 tests in 0.026s`; `OK`; exit 0.

### 3. Normalized cumulative-fill snapshot

Same focused command RED: `ImportError: cannot import name 'collect_broker'`; `Ran 4 tests in 0.025s`; `FAILED (errors=1)`; exit 1.

Same command GREEN: `Ran 4 tests in 0.046s`; `OK`; exit 0.

### 4. Unknown/incomplete and validation slice

Command (test output captured independently of the log-display shell status):

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker -v > test_artifacts/task-2-red-coverage.log 2>&1
```

RED output: `Ran 10 tests in 0.125s`; `FAILED (failures=19, errors=18)`. Missing capabilities raised rather than normalizing unknown; malformed collections errored; invalid numeric domains/identity/time inputs could falsely claim complete or reach transport. GREEN with same focused command: `Ran 10 tests in 2.919s`; `OK`; exit 0.

### 5. Paginated bounded activities/orders

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker -v > test_artifacts/task-2-red-pagination.log 2>&1
```

RED: `Ran 13 tests in 2.427s`; `FAILED (failures=12)` (full/repeated/partial pages falsely complete and amount still raw string). GREEN same focused command: `Ran 13 tests in 1.897s`; `OK`; exit 0.

### 6. Configured worker/schema-pattern/structured-content slice

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker -v > test_artifacts/task-2-red-process.log 2>&1
```

RED: `Ran 18 tests in 0.233s`; `FAILED (failures=2, errors=3)` (missing configured worker; ignored schema pattern; ignored structured content). GREEN: `Ran 18 tests in 1.139s`; `OK`; exit 0.

### 7. Worker entrypoint/serialization

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker.BrokerWorkerTests -v
```

RED: worker module exited 0 instead of 3, `main` missing; `Ran 2 tests in 2.850s`; `FAILED (failures=1, errors=1)`; exit 1. Full module GREEN after implementation: `Ran 20 tests in 4.396s`; `OK`; exit 0.

### 8. Self-review fixes: exact nested deduplication and corporate-action accounting limitations

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker.BrokerSnapshotTests.test_nested_partial_fill_readback_deduplicates_exact_leg_without_provenance_conflict test_watchdog_broker.BrokerSnapshotTests.test_corporate_action_without_adjustment_evidence_does_not_claim_complete_accounting -v
```

RED: `2 != 1` duplicate nested leg and `'complete' != 'unknown'` corporate-action evidence; `Ran 2 tests in 0.040s`; `FAILED (failures=2)`; exit 1.

GREEN same command: `Ran 2 tests in 0.030s`; `OK`; exit 0.

### 9. Self-review fix: prohibit schema-reference network retrieval

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker.BrokerBoundaryTests.test_remote_schema_references_rejected_before_transport -v
```

RED: blocked mock `urlopen` raised `AssertionError: network_forbidden`, wrapped as `_WrappedReferencingError`, not ValueError; `Ran 1 test in 0.022s`; `FAILED (errors=1)`; exit 1. Network was mocked; no request escaped. GREEN same command: `Ran 1 test in 0.006s`; `OK`; exit 0.

### 10. Self-review fix: declared totals and error envelopes

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker.BrokerSnapshotTests.test_declared_totals_and_error_envelopes_cannot_claim_completeness -v
```

RED: `AssertionError: True is not false`; `Ran 1 test in 0.030s`; `FAILED (failures=1)`; exit 1.
GREEN: `Ran 1 test in 0.059s`; `OK`; exit 0.

## Final verification and self-review

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker test_watchdog_operational -v > test_artifacts/task-2-focused.log 2>&1
uv run --with 'fastmcp<4' python tests/run_tests.py fast > test_artifacts/task-2-fast.log 2>&1
```

Final focused output: `Ran 41 tests in 3.346s`; `OK`; exit 0 (24 broker tests, 17 existing operational tests).

Final fast output: `Ran 270 tests in 10.415s`; `OK`; `TIER_RESULT fast tests=270 failures=0 errors=0 skipped=0`; exit 0. The fast runner includes manifest/discovery parity and operational mutation guards. Some aggregate fixture loops produce unittest asyncio debug slow-callback timing messages; no test failures, skipped tests or warnings indicating a provider call.

Static added-line scan reported empty findings for hardcoded secret assignments, shell injection, eval/exec, and unsafe deserialization. The full broker file and staged path list were self-reviewed. Checks addressed nested identity duplication, schema reference fetching, corporate-action overclaim, and declared-count/error-envelope overclaim via observed RED/GREEN fixes. Inputs remain bounded; cancellation propagates; broad ordinary-exception handling deliberately emits sanitized unknown coverage.

Initial staged diff check noted a blank line at EOF; removed and amended the implementation commit. Final `git diff HEAD^ HEAD --check` was clean. No behavior changed after the final focused/fast execution, only removal of that blank line. No unrelated paths were committed.

## Remaining concerns / parent handoff

1. Catalog discovery proves the actual tool surface and request schemas, not authenticated account-response payload compatibility. The approved later read-only smoke must validate real payload nesting/calendar/activity row shapes in isolated outputs, without printing raw account/orders/credentials. No live broker-data smoke was run here.
2. Provider partial-fill metadata or nested readback shape differences conservatively yield unknown rather than inventing timestamps/legs. This is intentional, but the later smoke may identify a supported normalization extension requiring a RED fixture before change.
3. Activity coverage is explicitly bounded by broker creation time, not proof of lifetime adjusted returns. Corporate actions require evidence beyond an activity row. Later accounting must obey these coverage limitations.
4. Independent fresh parent review remains required. No review agents were launched because this task explicitly forbids subagents.

## Fix round 1 — Important review findings

Status: DONE_WITH_CONCERNS; all three Important findings repaired offline. Parent frozen-diff re-review and later authenticated read-only payload smoke remain required.

- Fix base: `49ac2d8a91288da67c12bedcf4ccfa0a9038abbc`.
- Source/test commit: `bdb9b1ec3a3d642516cadc36ccc427e10ed9431b` (`fix(watchdog): reconcile order trees and receipt timestamps`). Explicit paths: `watchdog/broker.py`, `tests/test_watchdog_broker.py`.
- Report appended separately; final report commit is the task HEAD, avoiding a self-referential hash.
- No push, subagents, live calls, raw broker/secret output, live checkout/control/state/schedule changes, or progress-ledger edits.

### Repairs and self-review

1. Bidirectional broker-ID/client-ID mapping now covers every normalized node from open orders and exact-reference readbacks. Exact requested client identity remains mandatory. Conflicting identities, cumulative facts, child membership or parent assignment produce unknown coverage; a conflicting exact response is transactionally rejected rather than appended as an independent execution. Fixtures cover both mapping directions at roots and legs, contradictions nested under a new reference, and successive exact-reference observations.
2. A tree-wide canonical identity forest coalesces exact copies, ignoring only transport provenance, preserving the original nested parent and cumulative fill. Fixtures cover duplicate siblings, duplicate roots, root/nested overlap in both orders, standalone leg followed by exact parent readback, parent readback with repeated legs, conflicting repeated fills and conflicting parent relationships. Order-page duplicates within a response now pass only after tree-wide fact/relationship validation; repeated root IDs across pages remain pagination-unknown. Pagination cardinality/cursors still use original response rows, not coalesced counts. Activity duplicate gates, page limits, cursor/schema checks, deadlines, declared-total and partial-envelope checks are unchanged.
3. Every source-envelope timestamp now uses the UTC clock sampled immediately after that response is received. Sweep-start `captured_at` and final whole-sweep age validation remain separate. Source 10:00:01 with start 10:00:00 and receipt 10:00:02 is complete; source 10:00:03 is unknown. Existing numeric/stale/future and slow-sweep regressions remain passing.
4. Minor timing noise repaired narrowly: offline fixture transports cooperatively yield with `asyncio.sleep(0)` to model awaited I/O. No global logging/debug suppression. Final focused and fast logs contain zero asyncio slow-callback diagnostics.

Self-review checked the full base-to-source diff, transactionality, field/provenance comparison, parent preservation, both identity directions, and pagination/freshness semantics. Invocation allowlist, logical requests, schema checks, paper configuration boundary, coverage gates and manifest are otherwise unchanged. No ticker/time identity inference. `git diff --check` passed before the explicit-path source commit.

### Exact RED/GREEN evidence

All commands ran in this worktree. Test-only fixture additions preceded each corresponding behavior change. RED logs have assertion failures for the reviewed symptoms, not import/setup errors. The shell display helper returned 0 after displaying each RED log; the captured unittest output below is the authoritative failure result.

Identity RED:
```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker.BrokerSnapshotTests.test_reference_identity_mapping_is_bidirectional_over_nested_tree -v > test_artifacts/task-2-fix-red-identity.log 2>&1
```
Output: `AssertionError: True is not false`; `Ran 1 test in 0.134s`; `FAILED (failures=4)`.
Same test GREEN, redirected to `test_artifacts/task-2-fix-green-identity.log`: `Ran 1 test in 0.138s`; `OK`. This intermediate run still had one slow-callback diagnostic, resolved by the later cooperative fixture change.

Tree RED:
```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker.BrokerSnapshotTests.test_tree_duplicates_coalesce_at_parent_across_roots_and_observations test_watchdog_broker.BrokerSnapshotTests.test_conflicting_tree_duplicates_make_orders_unknown -v > test_artifacts/task-2-fix-red-tree.log 2>&1
```
Output: duplicate roots/legs or false completeness assertions; `Ran 2 tests in 0.157s`; `FAILED (failures=9)`.
Tree GREEN (also rechecking the identity slice):
```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker.BrokerSnapshotTests.test_tree_duplicates_coalesce_at_parent_across_roots_and_observations test_watchdog_broker.BrokerSnapshotTests.test_conflicting_tree_duplicates_make_orders_unknown test_watchdog_broker.BrokerSnapshotTests.test_reference_identity_mapping_is_bidirectional_over_nested_tree -v > test_artifacts/task-2-fix-green-tree.log 2>&1
```
Output: `Ran 3 tests in 0.363s`; `OK`. Two intermediate slow-callback diagnostics preceded the cooperative fixture change.

Receipt-clock RED:
```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker.BrokerSnapshotTests.test_source_timestamp_is_checked_at_response_receipt -v > test_artifacts/task-2-fix-red-clock.log 2>&1
```
Output: `AssertionError: 'unknown' != 'complete'`; `Ran 1 test in 0.042s`; `FAILED (failures=1)`.
Receipt-clock GREEN, including existing whole-sweep-age test:
```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker.BrokerSnapshotTests.test_source_timestamp_is_checked_at_response_receipt test_watchdog_broker.BrokerSnapshotTests.test_snapshot_timestamp_numeric_stale_future_and_slow_are_unknown -v > test_artifacts/task-2-fix-green-clock.log 2>&1
```
Output: `Ran 2 tests in 0.143s`; `OK`. One intermediate slow-callback diagnostic preceded the cooperative fixture change.

Additional exact duplicate-root tracer RED:
```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker.BrokerSnapshotTests.test_tree_duplicates_coalesce_at_parent_across_roots_and_observations -v > test_artifacts/task-2-fix-red-root.log 2>&1
```
Output: `AssertionError: False is not true` with `orders=unknown`; `Ran 1 test in 0.090s`; `FAILED (failures=1)`.
GREEN after within-response tree validation and cooperative fixtures:
```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker -v > test_artifacts/task-2-fix-green-root.log 2>&1
```
Output: `Ran 28 tests in 3.382s`; `OK`; exit 0; no slow-callback diagnostics.

### Final verification

After self-review added further passing conflict subcases and simplified one fixture, then ran:
```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_broker test_watchdog_operational -v > test_artifacts/task-2-fix-focused.log 2>&1
uv run --with 'fastmcp<4' python tests/run_tests.py fast > test_artifacts/task-2-fix-fast.log 2>&1
```
Focused: `Ran 45 tests in 5.379s`; `OK`; exit 0 (28 broker, 17 operational). Fast: `Ran 274 tests in 10.320s`; `OK`; `TIER_RESULT fast tests=274 failures=0 errors=0 skipped=0`; exit 0. Both final logs: `slow_callback_lines= 0`. Fast includes existing manifest/discovery parity and operational mutation guards. No source/test changes after these final executions.

Remaining concerns: real provider-payload compatibility is still not established by fixtures/catalog; later isolated authenticated read-only smoke remains a release gate. Contradictory open-order trees are conservatively discarded with orders unknown; contradictory exact readbacks leave the prior coherent forest unchanged with references unknown. Missing or changing nested-child membership is conservatively unknown rather than merged by inference. Independent parent re-review is pending.
