# Task 7 — monitoring persistence, reports and alert outbox

Base: `019065b9cc4538074edeb2ca3c0520360ace2324`, isolated position-watchdog worktree. This is offline implementation and self-review, not release approval or independent review.

## Delivered / scope

- Created `watchdog/store.py`, `watchdog/reports.py`, `tests/test_watchdog_store.py` (20 tests), and `tests/test_watchdog_reports.py` (14 tests).
- Changed only the watchdog private-input/public-projection boundary and one monitoring section in `public_dashboard.py`; retained its actual `public/dashboard.json` / `public/index.html` output path and existing sanitizers.
- Registered storage in fast and report/dashboard vertical workflows in scenario in `tests/test_manifest.json`.
- Added this report; no progress, earlier reports, trading controls, credentials, scheduler or operational code changed. No subagents, live services, pushes, schedules or worktree publication.

## RED / GREEN evidence

Commands used `PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest ... -v` or `-q`. Feature slices were implemented after the observed failure below; subsequent boundary/audit tests are not falsely claimed as independently RED.

| Slice / self-review repair | Actual observed RED | Subsequent GREEN |
|---|---|---|
| Transactional/idempotent snapshot | 1 test / 1 intentional assertion failure: `monitoring store missing` | 1 PASS |
| Durable transitions, overlapping stale runs, acknowledgment | Initial 4-test run: 2 failures (partial condition absent; stale run added alert), 1 missing-ack import error. Revised ack-existence assertion and reran: 3 intentional failures | 4 PASS |
| Compact evidence/version/source persistence | 7-test run: 1 failure, `evidence_events` count 0 rather than 1 | 7 PASS |
| Private/public projections | 1 intentional failure: `report projections missing` | 3 PASS |
| Atomic reports/dashboard/actual comparator interface | 6-test run: 2 failures (install absent; watchdog dashboard key absent), 1 missing `return_kind` KeyError (product interface missing, not fixture typo) | Combined 13 PASS |
| Dynamic private mark provenance, unapproved snapshot, new underlying material events | 10 storage tests: 2 failures, mark provenance erased to `{}` and only 1 alert instead of thesis+event alerts | Combined 16 PASS |
| Independent thesis coverage/history/malformed public identity | Combined 19: 2 failures (history reader absent; no source deterioration transition), 1 genuine unhashable-position-ID TypeError | 19 PASS |
| Schema/path/ack safety, actual mechanical diagnostics, owned-symbol and capital isolation | Combined 24: 3 failures (ack created missing DB; unexpected exit had no quantity alert; unowned thesis ticker published), 1 actual SQLite missing-table error instead of schema rejection | 24 PASS |
| Microsecond chronology, permissions/null identities, typed evidence alert, report retention/output path safety | Combined 29: 4 failures (stale report selected; mode 0644; effect rendered unknown; 5 generations retained). Re-ran expanded permission/path subtests: 2 tests / 5 failures (file+directory modes, accepted NULL identity, retention, escaped symlink output) | 29 PASS |
| Attribution-category and versioned accounting input retention, exact schema shape | 2 focused tests: 1 failure (attribution erased), 1 genuine SQLite missing-column error | Combined 31 PASS |

Additional audit tests passed without introducing product behavior: actual abrupt subprocess exit and SQLite reopen/integrity check; reader visibility during uncommitted transaction; report-generation failure before publication; pointer/public-install interruption recovery; actual offline Node execution of dashboard JavaScript; recursive private-canary injection into every nested fixture object. These verify existing transactional/sanitizer behavior, not claimed new RED cycles.

Initial fixture database context managers emitted ResourceWarnings because SQLite connection context managers commit but do not close. Tests were corrected to `contextlib.closing` plus transaction contexts; final executions had no such warnings. A transient missing parenthesis while adding a guarded reporting comprehension was caught by patch syntax validation and corrected before test execution.

## Final exact verification

Sequential commands, normal scratch TMPDIR (not a test_artifacts ancestor for unrelated SQLite suites):

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_store test_watchdog_reports -q
uv run --with 'fastmcp<4' python tests/run_tests.py fast
uv run --with 'fastmcp<4' python tests/run_tests.py scenario
uv run --with 'fastmcp<4' python tests/run_tests.py full
git diff --check
```

Actual results: **focused 34 PASS** (20 storage + 14 reports), **fast 26 modules / 433 PASS**, **scenario 10 modules / 176 PASS**, **full 38 modules / 727 PASS**, all failures/errors/skips = 0. Recorded runtimes: 0.367s / 8.260s / 2.749s / 15.857s. Manifest/discovery parity and runner operational-file isolation checks passed. Expected existing fixture `BLOCKER`, `SYSTEM_FAILURE alpha_radar`, and `DECISION` diagnostics are not live calls or failures. Diff whitespace check passed.

## Storage and Task 8 input contract

Required interfaces:

- `commit_observation(db: Path, observation: RunObservation) -> list[dict]`
- `read_report(db: Path) -> dict`
- `ack_alert(db: Path, key: str, receipt: dict) -> None`
- `private_report(report: dict) -> str`
- `public_summary(report: dict) -> dict`
- `render_alert(alert: dict) -> str`

Additional wrapper helpers: `pending_alerts(db) -> list[dict]`, `read_source_state(db) -> dict`, `read_portfolio_history(db) -> list[dict]`, `install_reports(db) -> dict`, `dashboard_summary(db) -> dict`.

`db` must end exactly `private/watchdog/monitoring.sqlite3`. Non-fixture writes/reads are limited to this module's checkout root; arbitrary external locations must explicitly be under `test_artifacts`. Symlink-resolved aliases and hardlinked database files are rejected. New monitoring DB is 0600 and watchdog directory 0700. Missing read/history/outbox operations do not mkdir/create a database. A valid-looking acknowledgment of an absent store also cannot initialize it.

Schema version 1 has exactly nine tables: `thesis_versions`, `runs`, `position_observations`, `portfolio_snapshots`, `evidence_events`, `source_state`, `attribution_rows`, `condition_state`, `alert_outbox`. Keys are explicitly NOT NULL; foreign keys to runs are enabled, synchronous=FULL. Initialization, run payload, per-position/portfolio/attribution rows, immutable versions, event deduplication, monotonic cutoffs, transitions and outbox insertions share one BEGIN IMMEDIATE transaction. Unknown user_version, nonempty unversioned DB, or nonmatching table definitions are rejected without migration. All values use parameterized SQL. Tables/columns are not guessed from operational schemas.

Task 8 constructs the existing `RunObservation` without changing its dataclass:

```text
coverage.captured_at: trusted aware ISO run timestamp
portfolio.strategy: exact account_strategy result
portfolio.account: exact account_overview result
portfolio.benchmark: exact compare_benchmark result (return_kind, NOT comparator_kind)
portfolio.exposure: exact aggregate_exposure result, when available
portfolio.strategy_baseline: optional supplied immutable Task5 strategy-baseline input
portfolio.account_baseline: optional supplied immutable Task5 account-baseline input
thesis: exact monitor_theses returned rows, optionally with baseline_from_candidate result in row.baseline
attribution: separate actual/research/decisions/shadow projections, never merged into actual returns
```

If coverage.captured_at is absent, strategy.at is the timestamp fallback; absent/naive/invalid time rejects the commit. Storage chronology is fixed-width UTC microseconds, while private input timestamps are preserved. SQL julianday was removed after a real microsecond-ordering failure. Stale observations may remain as history but cannot regress the latest report/condition state or lower source cutoffs. Same run identity with different compact payload is rejected, not silently overwritten.

`read_report` returns the latest complete committed run payload in one read transaction. It does not combine independent latest-position and latest-account queries. `read_portfolio_history` returns chronological portfolio dictionaries: Task8 extracts each `strategy` and `account` object for Task5 prior_snapshots, preserving dynamic mark-provenance maps. The optional accounting baseline inputs are immutable `thesis_versions` entries under private `__strategy__` / `__account__` namespaces and separate kinds; changing a documented version rejects the whole run. Independently verified average-price quantum/rounding/provenance maps and flow date-basis evidence remain private, not invented by storage.

Thesis versions are keyed by exact position, supplied version and kind. Supplied criteria exclude proposal lists; proposal revisions have their own version/kind and `approved=False` in both snapshots and version rows, regardless of an incoming true flag. No active baseline is synthesized from a proposal. Evidence deduplication uses position+baseline version+underlying fingerprint, not URL/run; conflicting facts/event time/kind reject rather than silently merge. Full compact provenance URLs are retained/merged privately; fact/summary prose is bounded, article/prompt/transcript/raw payload keys are excluded. Source-state input/output matches `source_state[symbol][source].cutoff`; a returned source cutoff can advance only with that source's documented `coverage.status == complete`, valid time not beyond the run, and monotonic progress. Failed/incomplete sources retain prior stored cutoffs; no reconstruction from run success flags.

## Pending-alert wrapper / acknowledgment contract

`commit_observation` returns **all pending alerts**, not only alerts produced by this run. `pending_alerts` supplies the same durable retry queue even after a duplicate run, absent new conditions, daily completion, report failure, or a prior delivery interruption. Task8 must drain this queue independently of its equivalent-run skip/completion decision:

1. Commit a validated observation under its monitoring-only outer lock.
2. Install/retry reports from the coherent DB snapshot; report failure must not acknowledge alerts.
3. Load pending alerts, render each with `render_alert`, and perform notification transport outside accounting/thesis/mechanical computations.
4. Call `ack_alert` only after genuine transport receipt/readback evidence. Never manufacture a provider acknowledgment or treat a local send boolean as one.

Accepted receipt fields are exactly `provider`, `message_id`, `status='delivered'`, aware `verified_at`, and `verification='provider_readback'|'idempotent_receipt'`. Other receipt fields are discarded privately. Invalid/ambiguous receipts leave pending rows untouched. Repeating the same acknowledgment is idempotent; conflicting acknowledged receipts reject. This API validates the contract, **does not independently call a provider to verify the caller's claim**. Task8 owns verifiable evidence acquisition. No-ack transports must leave ambiguous deliveries pending and disclose possible duplicate notifications; exactly-once transport delivery is not claimed.

Conditions cover actual mechanical independent statuses, the typed `unexpected_exit` / `protection_quantity_mismatch` diagnostics, horizon, ownership, thesis, per-thesis source coverage, overall coverage, and mapped material event effects. Unknown/missing statuses remain gaps, never implicit recovery. Stable condition generation fingerprints create durable transition keys. An unchanged active condition repeats only after 24h; changed validated status/severity, critical escalation and recovery create distinct transitions. Mapped underlying material events dedupe independently and do not repeat merely because a different run re-observes them. Daily digest identity is exactly once per supplied exchange session date. Task8 still owns exchange-session eligibility and run-level completion policy.

## Atomic files, public privacy and dashboard rulings

- `install_reports` renders **every** projection before publication, writes/fsyncs a private generation, and atomically changes `.reports/current` once for the JSON/Markdown pair. `private/watchdog/latest.json` and `latest.md` are stable relative aliases to that generation. Three private generations are retained; failed pre-pointer generations/staged files are cleaned up.
- `public/watchdog.json` is a separately fsynced, atomic replacement containing only `public_summary`; it never points into private storage. There is deliberately **no claim of one cross-directory transaction**. A crash after private publication may leave an older safe public summary; the tested retry repairs it, and pending alerts remain pending. Readers needing both private files across concurrent installs should resolve the generation once. Dashboard itself projects the coherent DB snapshot, not these aliases.
- Output-directory/lock symlinks are rejected. Non-test worktree publication is explicitly forbidden; all actual artifact generation in this task was under temporary `test_artifacts` roots.
- Public projection allowlists keys and values at every nesting level: validated ticker grammar, enum statuses/reasons, finite decimal amounts, canonical timestamps/session dates, bounded coverage counts. Unknown diagnostics become `unknown_diagnostic`; raw exceptions, URLs, IDs/hashes, prompts, buying power/trading limits, source evidence and filesystem paths cannot pass through free-form status/reason fields.
- Market-symbol rows require verified position ownership and exact position-ID+symbol agreement for thesis/accounting joins. Full-account view publishes observations (equity/cash/time/coverage) but intentionally withholds all account return/drawdown claims, even when private accounting has verified performance. This is conservative and meets the approved secondary observation scope.
- Primary scorecard is explicitly $10,000 initial analytical allocation with **evolving marked sleeve equity**. Unsupported/unknown accounting or wrong scope/capital withholds totals. Conditional stop geometry is not maximum loss. SPY comparator uses the actual Task5 return_kind; price-only comparison cannot claim total-return excess. Shadow/research metrics remain private/separate and are labeled not actual protected-trade returns.
- Missing/corrupt/unsupported monitoring data returns sanitized unavailable state without creating/repairing a DB or breaking the existing dashboard. Existing dashboard operational readers were not reused by watchdog; their legacy behavior elsewhere is unchanged.

## Requirement-to-test mapping / self-review

| Requirement | Tests |
|---|---|
| Transaction/idempotency/overlap/crash | transactional_idempotent_snapshot; overlapping_duplicate_and_stale_runs; pending_delivery_requires_receipt_and_survives_rollback; process_crash_rolls_back_uncommitted_run |
| Strict schema/FK/FULL/private-path identity | schema_identity_and_hardlink_rejected; same_table_names_wrong_schema_rejected; private_store_permissions_and_nonnull_identity; history_and_settings_read_without_mutation |
| Coherent latest/history/source state | reader_sees_only_committed_coherent_report; microsecond_and_offset_ordering_never_regresses_snapshot; evidence_versions_cutoffs_compact_and_monotonic |
| Versioned criteria/enrichment/accounting provenance | evidence_versions_cutoffs_compact_and_monotonic; private_provenance_and_unapproved_snapshot_retained; attribution_categories_and_versioned_accounting_inputs |
| Transition cooldown/escalation/recovery/digest/material dedup | cooldown_escalation_recovery_and_digest; unchanged_condition_reminder_after_24_hours; new_material_events_alert_even_same_thesis_status; thesis_source_coverage_deterioration_is_independent; real_mechanical_discrepancy_reason_produces_condition |
| Pending delivery/absent-store safety | pending_delivery_requires_receipt_and_survives_rollback; ack_missing_store_does_not_create_database |
| Atomic reports/interruption/retry/bounded output | atomic_private_pair_and_public_install_failure; install_interrupt_at_pointer_keeps_previous_pair; public_install_failure_is_atomic_and_retryable_after_private_publish; generations_bounded_and_output_symlinks_rejected |
| Exact public value/key privacy / unknown evidence | public_nested_projection_private_compact_report; unknown_and_malicious_allowlisted_strings_withheld; private_injection_into_every_nested_object_is_removed; public_summary_malformed_identity_is_safe |
| Distinct scorecards and ownership/benchmark constraints | unknown_ownership_and_shadow_are_not_actual; unowned_thesis_symbol_and_wrong_capital_withheld; real_comparator_labels_and_verified_accounting_exposure |
| Actual offline publication/render boundary | built_and_rendered_fixture_artifacts_are_private_free; dashboard_missing_and_incomplete_store_is_read_only; evidence_alert_render_keeps_typed_effect |

Self-reviewed entire new store/report sources, touched dashboard diff, and privacy artifacts. The fixture builds actual dashboard JSON/HTML and runs the existing JavaScript offline with Node's VM and an explicit DOM/fetch harness; rendered values were `$10,020` sleeve and `$50,000` secondary account, with shadow disclaimer and no PRIVATE_CANARY in any public artifact. Recursive injection checks every nested fixture dictionary while retaining legitimate accounting values; it is not just a test that everything was dropped. Actual SQLite crash subprocess returned exit 23, reopened integrity_check returned `ok`, and no uncommitted run/outbox rows survived. Concurrent duplicate commits returned one logical pending condition alert.

Precommit static verification: AST parsing passed for all five affected Python files. Full new-file and full added-line checks found no shell injection, eval/exec, unsafe deserialization, interpolated SQL execution or credential assignment patterns. Explicit staged scope was exactly seven files. The ignored SDD report required explicit `git add -f` for that single file; staged whitespace validation caught and removed one trailing blank line in reports.py. No behavioral edit followed the final test run.

No watchdog import reaches autotrader, reconciliation/repair, broker adapters, research intake, notification transport or live loaders. All fixture outputs are isolated. Parent owns independent frozen-diff review and Tasks8/9 runtime receipt capability, concrete worker wiring, read-only smoke and release. A reusable review reference was recorded in the active local requesting-code-review skill; no repository configuration or other profile was changed.

## R1 fix round 1 — report-lock hardlink isolation

Fix base: `9ffa5f037ea7b6828333940a0d616e25321e3637`. Scope is R1 only; R2 (large finite Decimal browser rendering) remains a non-blocking deferred follow-up. No progress or earlier reports were changed.

Root cause confirmed: the existing append-mode pathname open accepted a hardlinked `.reports.lock`, then pathname `chmod` changed the unrelated inode before flock. Replaced only report-lock acquisition with a descriptor-based context manager: `os.open(O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK, 0o600)`, `fstat` regular-file/single-link checks, no-follow pathname `lstat` regular-file/single-link and device/inode identity checks **before** `fchmod` or `flock`. FIFO opens cannot hang awaiting a peer. Permission repair uses `fchmod` on the validated descriptor; an additional identity validation after acquiring flock rejects pathname replacement during a wait. The descriptor is closed on every exit. Existing report rendering/publication logic is unchanged.

### Exact RED / GREEN

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_reports.ReportTests.test_report_lock_hardlink_rejected_without_touching_sentinel -v
```

- **RED before production edits:** 1 test, 1 assertion failure at the complete sentinel metadata comparison: `st_mode` changed from `33188` (regular 0644) to `33152` (regular 0600). The actual installer operated on an isolated temporary `test_artifacts` monitoring DB and a two-link unrelated sentinel, not any operational file.
- **GREEN after the narrow fix:** same command, 1 PASS, 0 failures/errors (0.041s). The test requires rejection, identical bytes and every available `st_*` metadata field (including nanosecond timestamps, link count, permissions, identity/ownership), no flock call, preserved hardlink identity, and no report/public directory publication.
- Added three supplemental audit tests (not claimed independently RED): directory/FIFO/socket/symlink rejection before `fchmod` or flock; deterministic replacement between descriptor open and pathname identity validation; real flock serialization of two concurrent installers and subsequent reuse of the same existing single-link inode/bytes, with mode 0600 and coherent successful report publication.

### Final verification and self-review

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_store test_watchdog_reports -q
uv run --with 'fastmcp<4' python tests/run_tests.py fast
uv run --with 'fastmcp<4' python tests/run_tests.py scenario
uv run --with 'fastmcp<4' python tests/run_tests.py full
git diff --check
```

Actual sequential results: **focused 38 PASS** (20 store + 18 reports, 0.528s), **fast 26 modules / 433 PASS** (8.345s), **scenario 10 modules / 180 PASS** (2.894s), **full 38 modules / 731 PASS** (16.051s); all failures/errors/skips = 0. Manifest/discovery parity and runner operational-file isolation checks passed. Expected existing fixture BLOCKER/SYSTEM_FAILURE/DECISION messages were not live calls or test failures. Whitespace check passed.

Self-reviewed the full source/test diff, acquisition ordering, descriptor lifetime, rejection-without-publication paths, existing lock reuse and concurrent publication. AST parsing passed for both changed Python files. Added-line static scans found no credential assignments, shell injection, eval/exec, unsafe pickle loading or interpolated SQL execution. No production edits followed these suite runs. Explicit commit scope is only `watchdog/reports.py`, `tests/test_watchdog_reports.py`, and this report. No subagents, live calls, operational writes, pushes, schedules or configuration changes. This is implementation/self-review evidence only; parent owns independent frozen-diff rereview and release approval.
