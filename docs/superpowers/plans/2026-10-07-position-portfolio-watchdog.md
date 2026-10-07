# Position & Portfolio Watchdog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an independently scheduled, read-only position/portfolio watchdog with evidence-backed alerts and exact-lineage attribution, a $10,000 initial strategy scorecard, and a separate full-account overview.

**Architecture:** Deterministic readers produce a validated observation without operational repairs. Pure lineage, protection and accounting functions feed an isolated monitoring SQLite database, private reports and sanitized public summaries. A bounded thesis lane observes owned managed names without broker access; no watchdog result feeds trading authorization.

**Tech Stack:** Existing Python/uv toolchain, unittest, stdlib SQLite/Decimal/zoneinfo, existing fastmcp<4 transport, established research provider configuration, Massive structured market data, Alpaca broker reads.

**Spec:** `docs/superpowers/specs/2026-10-07-position-portfolio-watchdog-design.md` (approved with primary strategy/secondary account reporting).

## Global Constraints

- Paper-account reads only; do not change enabled, broker_mode, trading limits, reviewer policy or existing cadence.
- Initial strategy capital is $10,000; sleeve equity evolves. Full account equity is a separately labeled secondary view, not strategy alpha.
- No broker placement/cancellation/replacement/repair/exit and no operational writes by watchdog readers.
- Missing ownership, lineage, protection, thesis or cash-flow evidence stays unknown/incomplete, never inferred by ticker alone.
- Fixtures/live smoke use isolated test_artifacts outputs. Normal tests cannot call live services.
- Thesis models receive no broker credentials/tools; structured classification cannot overwrite trusted observations.
- No new keys, MCP servers or instrument types. No self-tuning, optimizer or execution-dependent monitoring gate.
- Tests RED before behavior changes; independent frozen-diff review before release; explicit-path commits and remote SHA verification.

## Review Focus

1. Existing read_jsonl opens SQLite for sync/repair: watchdog needs a genuinely read-only operational snapshot (Task 1).
2. Legacy BUY journal rows lack order identity; precise broker evidence must not be replaced with ticker/time guesses (Task 3).
3. Cumulative partial fills and simultaneous OCO legs must not double-count execution or protection (Tasks 2–4).
4. Deposits and legacy gains must not become Tradey alpha or change its $10,000 baseline (Task 5).
5. A interrupted source sweep or ambiguous alert delivery must not become an all-clear or lose a retriable alert (Tasks 6–8).

## Scope and dependency map

This is one observational plane, delivered in independently testable components: read boundary → lineage/protection → accounting/thesis → reporting → scheduler/release. Do not create a separate standalone watchlist app or run the investment-watchdog initializer against operational storage.

Create a `watchdog/` package:
- `types.py`: dataclasses/result contracts, Decimal/time validators and typed diagnostics.
- `operational.py`: truly read-only, coherent input history.
- `broker.py`: exact read-tool allowlist and normalized snapshots.
- `lineage.py`: explicit identity joins, fill identity and coverage.
- `mechanical.py`: pure protection/horizon/exposure computations.
- `accounting.py`: FIFO managed P&L, sleeve equity and separate account observations.
- `benchmark.py`: verified benchmark adjustments and return comparison.
- `thesis.py`: versioned supplied baseline and bounded evidence classification.
- `store.py`: monitoring-only schema, transactions, outbox and report state.
- `reports.py`: private/public projections and concise notification rendering.
- `cli.py`: mechanical/daily/fixture/smoke modes and run-level isolation.
- `schedule.py`: pure exchange-session eligibility.

Create `watchdog_cli.py` thin entrypoint and `watchdog_config.json` (monitoring settings only). Modify existing `autotrader.py` solely for forward-only private lineage metadata, `public_dashboard.py` for sanitized watchdog rendering, `tests/test_manifest.json` for new test classification, and README for usage. Existing broker_mcp_bridge operation dispatch and run_cycle execution flow remain unchanged.

Common contracts in types.py:
- `OperationalSnapshot(streams: dict[str, list[dict]], baseline_symbols: frozenset[str], captured_at: str, complete: bool, reasons: list[str])`.
- `BrokerSnapshot(account: dict, positions: list[dict], orders: list[dict], activities: list[dict], sessions: list[dict], captured_at: str, complete: bool, coverage: dict)`; store compact normalized fields, not raw transport payloads.
- `LineageResult(positions: list[dict], decisions: list[dict], coverage: dict, reasons: list[str])`.
- `RunObservation(run_id: str, session_date: str, mode: str, positions: list[dict], portfolio: dict, attribution: dict, thesis: list[dict], coverage: dict, reasons: list[str])`.
- Monetary values are Decimal in memory and canonical strings in persisted JSON. Model/network boundary objects are strictly validated before conversion.

New unittest modules are under tests; run focused modules with `PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest <module> -v`. Register pure contract modules in fast, vertical workflow modules in scenario. Before each commit run affected modules and fast; before release run scenario, full and discovery parity.

### Task 1: Read-only operational snapshot and monitoring contracts

**Files:** Create watchdog/__init__.py, types.py, operational.py; tests/test_watchdog_operational.py. Modify tests/test_manifest.json.
**Interfaces:** `read_operational(root: Path) -> OperationalSnapshot`; `money(value: object) -> Decimal`; `aware_timestamp(value: object) -> datetime`.

- [ ] Write `test_read_does_not_repair_or_create_files`: use an isolated SQLite fixture with ledger_entries and compatibility JSONL projections; assert content/mtime/size unchanged after reads and a divergent projection returns complete=False. Test missing DB does not create it, trailing partial rows, corrupt digest, invalid baseline JSON, bool/NaN money and future timestamps.
- [ ] Run focused tests and observe missing implementation/expected failure.
- [ ] Implement a readonly SQLite URI connection with query_only and a read transaction. Never call sqlite_ledger._connect, read_jsonl, verify_database or migrate_jsonl. Verify sequence/digests and compare strict JSONL canonical rows using pre/post file metadata checks. Do not use immutable=1 on a live WAL database. Use filesystem reads without creating operational lockfiles. Detect concurrent changes and return operational_snapshot_changed rather than repair. Missing required DB/history is incomplete, not a silently fabricated empty history. The broker_baseline JSON is read-only.
- [ ] Prove repeat-read parity and no newly created operational DB/WAL/SHM artifacts in fixtures; test active WAL state and read-only failure cases explicitly. A missing/unusable WAL/SHM prerequisite yields incomplete coverage rather than opening a write connection. Run focused + fast.
- [ ] Commit explicit files after fresh focused review.

### Task 2: Broker read adapter with actual invocation allowlist

**Files:** Create watchdog/broker.py; tests/test_watchdog_broker.py.
**Interfaces:** `ReadOnlyAlpaca(client, tool_schemas)` with async `call(name: str, values: dict) -> object`; `async collect_broker(reader: ReadOnlyAlpaca, refs: list[str], start: str, end: str) -> BrokerSnapshot`.

- [ ] Write `test_write_tool_rejected_before_invocation`: fake transport records calls; calling place_stock_order, cancel_order, protect, or unknown name raises and transport calls remain empty. Test model-authored action fields cannot change the read requests. Test paginated activities/orders, missing fields, partial fills and incomplete pagination.
- [ ] Run focused tests RED.
- [ ] Implement explicit logical-to-live-schema mappings for account info, positions, open nested orders, exact client-ID reads and exchange calendar using existing credential/config and normalization helpers only. Check the live schema during the later read-only smoke; do not guess read-method names. Activities/history support must be discovered and validated; if the broker MCP lacks a needed read capability, return account_cashflows_unknown or distribution_coverage_unknown without inventing data or adding a server/key. The allowlist contains exact validated tools, never wildcard get_*.
- [ ] Normalize broker field provenance, cumulative filled_qty/average price and filled_at; reject invalid numeric domains; enforce pagination completeness and snapshot time freshness. Collect only requested references and bounded activity interval. Reject non-paper configured mode.
- [ ] Run focused + fast, review, commit.

### Task 3: Exact lineage and forward-only metadata

**Files:** Create watchdog/lineage.py; tests/test_watchdog_lineage.py; tests/test_watchdog_forward_lineage.py. Modify autotrader.py around review/proposed/intent/fill persistence and pending reconciliation append sites, without changing executable fields.
**Interfaces:** `build_lineage(op: OperationalSnapshot, broker: BrokerSnapshot) -> LineageResult`; execution-side private records add candidate_id/dossier_hash/proposal_hash/parent_client_order_id where authoritative values already exist.

- [ ] Write `test_two_ideas_same_symbol_are_not_both_traded`: two distinct candidate IDs with one explicit filled order → only that candidate filled. `test_legacy_buy_without_identity_is_unattributed` pins no ticker/time fallback. Assert unchanged proposal hash, broker order payload and reviewer bundle after linkage changes; dry-run metadata stays isolated.
- [ ] Run focused tests RED. Inventory all relevant pending-fill and immediate-fill persistence sites and serializers before edits. Inspect row shapes with keys/counts only, never dump account IDs or private theses.
- [ ] Implement explicit joins: candidates → dossier hash → reviews proposal hash → intent plan proposal hash/client ID → authoritative broker fills and exact journal references. Review evidence_id links proposed records where explicit. Legacy journal data can support aggregate accounting but cannot prove a candidate link. Unique/contradictory linkage is surfaced in coverage. Do not modify historical rows.
- [ ] Add forward-only private lineage fields at original execution persistence sites, including rejected/proposed events, intents and confirmed fill rows; propagate them through pending reconciliation. Keep public projections unchanged until explicit allowlisting. Watchdog never writes these streams.
- [ ] Detect duplicate cumulative observations using order identity plus cumulative quantity, not filled_at alone. Compare deltas in quantity and total notional for partial-fill accounting. Missing previous state yields coverage_unknown, not a replayed BUY.
- [ ] Run focused + fast + scenario, get independent review of this execution-adjacent metadata task, then explicit-path commit. Pause affected execution writers before deploying such code; do not perform this task against an actively edited production file while jobs run.

### Task 4: Mechanical protection, horizon and concentration

**Files:** Create watchdog/mechanical.py; tests/test_watchdog_mechanical.py.
**Interfaces:** `observe_positions(lineage: LineageResult, broker: BrokerSnapshot, now: datetime) -> list[dict]`; `aggregate_exposure(positions: list[dict], broker: BrokerSnapshot) -> dict`.

- [ ] Write tests for partial entry, partial exit, duplicate nested leg, valid OCO pair, cancelled stop, expired protection, mismatched quantity, concurrent quantity change, legacy holdings and horizon expiry. Example assertion: `assert observation['horizon_status'] == 'horizon_expired'` while recorded broker-write calls remain empty. Assert a matched stop/target OCO pair covering quantity Q covers Q, not 2Q; duplicate serialized legs do not add coverage.
- [ ] Run RED.
- [ ] Implement pure validation with independent ownership/protection/horizon statuses. Observe all nonzero managed exposures including partial fills; do not only select status=filled. Exact broker status and OCO grouping determine coverage. Report unexpected exits, conflicting replacements and quantity mismatch; never repair. Missing refs/calendars → unknown.
- [ ] Compare timezone-aware now with original planned_exit_at; exchange-session counts require validated sessions. Aggregate only verified managed value. Provide position weights both within managed invested assets and relative to marked sleeve equity once Task 5 supplies it, with denominators labeled. Classification not supported by structured evidence stays unknown.
- [ ] Run focused + fast, review, commit.

### Task 5: Actual accounting, benchmark and secondary account view

**Files:** Create watchdog/accounting.py, benchmark.py; tests/test_watchdog_accounting.py; tests/test_watchdog_benchmark.py.
**Interfaces:** `account_strategy(lineage: LineageResult, broker: BrokerSnapshot, baseline: dict, prior_snapshots: list[dict]) -> dict`; `account_overview(broker: BrokerSnapshot, prior_snapshots: list[dict]) -> dict`; `compare_benchmark(strategy: dict, benchmark: dict) -> dict`; `load_benchmark(start: str, end: str) -> dict`.

- [ ] Write deterministic tests: initial capital '10000', BUY 2 at '100', SELL 1 at '110', remaining mark '105' → cash '9910', marked equity '10015', realized '10', unrealized '5', assuming verified zero costs/distributions and complete opening history. Assert legacy/manual gain affects account_overview but not strategy. Deposit '1000' cannot count as profit or enlarge strategy allocation. Test dividends, split, missing cashflows, unknown fees, gap in marks, partial exits and stale benchmark dates. Require pure Decimal values.
- [ ] Run RED; use tools, not mental arithmetic, to validate fixture expected values before implementation.
- [ ] Implement FIFO only for exactly owned managed quantities; structured broker execution evidence fills journal coverage gaps without persisting operational fills. A verified complete history from strategy inception permits a '10000' allocation baseline. If earlier activity is incomplete, choose a dated prospective baseline with opening managed holdings valued consistently and analytical equity explicitly labeled '10000 at baseline'; do not pretend the historical account cap proves historical equity. Withhold inception-return claims. Negative cash/discrepancies are errors, not silently clipped.
- [ ] Report conditional planned loss separately from equity and guaranteed-loss language. Account overview uses broker equity/cash; full-account return/drawdown requires independently verified account baseline and deposits/withdrawals. Without flow coverage, retain account equity observations and no performance claim.
- [ ] Implement synchronized Massive benchmark price reads using configured credentials and deterministic publication fields; verify total-return adjustment/distribution capability live at release. Split-adjusted-only data yields price_return_only, never total_return. No broker MCP market-history research lane. Read verified distributions when available; otherwise withhold excess total-return. No new credentials.
- [ ] Compute comparable marked return/drawdown only on valid dates. No interpolated equity through missing marks. Keep actual/research/shadow results separate; conviction is not probability. Report coverage and sample counts rather than unsupported confidence claims.
- [ ] Run focused + fast, review, commit.

### Task 6: Bounded thesis monitoring with versioned baselines

**Files:** Create watchdog/thesis.py; tests/test_watchdog_thesis.py; watchdog_config.json.
**Interfaces:** `baseline_from_candidate(candidate: dict) -> dict`; `monitor_theses(positions: list[dict], baselines: dict, source_state: dict, adapters: dict, deadline: float) -> list[dict]`; `classify_events(baseline: dict, receipts: list[dict], run_model) -> dict`.

- [ ] Write tests asserting absent measurable breakers → baseline_incomplete; failed issuer coverage → coverage_incomplete and unchanged cutoff; two URLs for one event → one event; lower price alone cannot yield potential_thesis_break. A mapped verified breaker can produce review_required/potential_thesis_break but no executable action. Inject instructions in evidence and prove ignored fields cannot modify trusted data. Malformed model output and resolved-catalyst dates stay typed.
- [ ] Run RED.
- [ ] Preserve supplied baseline version and compact provenance. Maintain mechanical checks even when legacy thesis baseline is incomplete. Proposed enrichments are stored separately as unapproved proposals, never activated silently.
- [ ] Configure mechanical hard timeout 120 seconds; daily hard timeout 900 seconds with active deadline 840 seconds and 60-second report/persistence reserve. Daily reads/accounting get at most 120 active seconds, thesis phase at most 600 cumulative seconds. At most 20 owned distinct symbols, each capped at 60 active seconds; stop at shared deadline and mark unfinished coverage explicitly. Priority order: prior critical unresolved event, nearest/expired horizon, oldest successful coverage, symbol tie-break. No guaranteed full coverage when the sleeve contains many names.
- [ ] Source cutoff overlap is 48 hours. Fetch at most three substantive URLs per name with at most 15-second absolute wall time each; classification at most 20 seconds, all clipped to shared/per-name remaining time. Use one isolated safe-mode, tool-free classification call with existing research model configuration; retrieval has read-only source tools and no broker MCP/operational persistence. Calls inherit neither private memory nor write tools. Enforce hard I/O deadlines rather than relying solely on socket timeouts. Parallel retrieval stays within global bounds.
- [ ] Reuse existing source-quality helpers only if inspection proves side-effect-free; never call alpha_radar.live_research or its intake. Prefer primary event records, issuer/SEC document dates and trusted earnings endpoints; retain per-source typed coverage. Store facts/URLs only, discard document bodies after classification. No raw transcripts in monitoring storage.
- [ ] Run focused + fast, review, commit.

### Task 7: Monitoring persistence, reports and alert outbox

**Files:** Create watchdog/store.py, reports.py; tests/test_watchdog_store.py; tests/test_watchdog_reports.py. Modify public_dashboard.py at its private-input/public-projection boundary.
**Interfaces:** `commit_observation(db: Path, observation: RunObservation) -> list[dict]`; `read_report(db: Path) -> dict`; `private_report(report: dict) -> str`; `public_summary(report: dict) -> dict`; `render_alert(alert: dict) -> str`; `ack_alert(db: Path, key: str, receipt: dict) -> None`.

- [ ] Write crash/rollback, duplicate run/event, overlapping runs and condition-transition tests. Example: identical observation twice creates one pending condition alert; changed severity creates a new transition; recovery gets a distinct recovery record. A failed delivery leaves the outbox pending. Inject private keys/URLs/IDs/raw exceptions into every nested object and assert none survive public_summary. Test missing watchdog DB does not break the existing dashboard.
- [ ] Run RED.
- [ ] Implement monitoring SQLite only at private/watchdog/monitoring.sqlite3 with schema user_version=1, foreign_keys=ON, synchronous=FULL and transactions. Tables: thesis_versions, runs, position_observations, portfolio_snapshots, evidence_events, source_state, attribution_rows, condition_state, alert_outbox. Primary/unique keys bind version/run/event/condition identities; reject unsupported schema without migration-by-surprise.
- [ ] Persist compact observations and report snapshots, not broker payloads. Alert cooldown 24 hours for an unchanged condition; critical severity escalation and recovery bypass cooldown. Daily digest unique per session. Quantitative thresholds use validated status transitions, not price-triggered generic alerts. Notification transport remains outside data computations.
- [ ] Atomically install private latest.json/latest.md and public watchdog summary using explicit allowlists. Public account view may show equity/cash/timestamp, never account identifiers, buying power or trading limits. Public strategy view may show exposure/accounting only with coverage labels. Keep full source URLs and thesis evidence private.
- [ ] Add dashboard section that tolerates absent/incomplete monitoring data, displays both scorecard bases distinctly, and cannot relabel shadow outcomes as actual returns.
- [ ] Run focused + fast + scenario, review, commit.

### Task 8: CLI, scheduling and isolated vertical workflow

**Files:** Create watchdog/cli.py, schedule.py, watchdog_cli.py; tests/test_watchdog_workflow.py; tests/test_watchdog_schedule.py. Modify README, tests/test_manifest.json; add docs/watchdog-operations.md.
**Interfaces:** `run_watchdog(mode: str, root: Path, output_root: Path, adapters: dict, now: datetime) -> dict`; `eligible(mode: str, now: datetime, sessions: list[dict]) -> bool`; `main(argv: list[str] | None = None) -> int`.

- [ ] Write vertical workflow tests using real pure modules/store and only fake external adapters. Assert mechanical run handles managed/legacy holdings, missing thesis baseline and pending protection correctly; daily run produces actual/research/decision partitions, source cutoff and outbox. Hash/stat operational inputs before/after. Test fixture mode cannot choose operational output; live smoke cannot send alerts/publish dashboard; unknown CLI action fails closed. Test daily completion only after successful report commit; partial source coverage is successful-with-gaps, not all-clear.
- [ ] Run RED.
- [ ] Implement modes mechanical/daily, --root, --output-root, --fixture and --smoke. Default outputs private/watchdog; fixture/smoke must resolve beneath test_artifacts/watchdog. Reject operational input/output path overlap and symlink escapes. Use monitoring-only flock, no trading lock/kill-switch. Monitoring locks/completion markers live solely under the selected output root.
- [ ] Schedule eligibility uses actual Alpaca session calendar, aware UTC → America/New_York; mechanical :05 only inside session, daily first slot at close+15 minutes. Tests cover DST, holidays, weekends and 13:00 NY early close. Missing calendar means typed coverage gap and no guessed market-session eligibility.
- [ ] For proposed cron registration, mechanical UTC '5 14-21 * * 1-5', daily UTC '15,45 17-22 * * 1-5'; code filters actual sessions and daily completion. Verify the union with calendar fixtures before registering; scheduler firings outside eligibility are silent no-ops. There is one safe bounded reporting retry next eligible daily slot; never retry execution.
- [ ] Use Hermes's supported delivery mechanism with an outbox consumption wrapper. Inspect exact cron/message schemas and authoritative docs before transport code; do not invent send-message helpers. Transport callback takes pending alert payload, returns receipt/ambiguous result; ack only confirmed delivery. If automatic cron relay delivery provides no trustworthy acknowledgment, retain ambiguity and document possible duplicate-on-retry semantics. Exception-only mechanical output, once-daily digest; no routine all-clear spam.
- [ ] Run all new modules, scenario and fast; inspect fixture JSON/Markdown and built public artifact; verify sanitizer against rendered output, review, commit.

### Task 9: Independent review, real read-only probes and release

**Files:** Documentation and explicit reviewed source paths only; generated outputs remain ignored/private.
**Interfaces:** Prior tasks' CLI; supported scheduler job registration and readback.

- [ ] Freeze diff, obtain independent adversarial whole-branch review against approved spec and plan. For each finding add a RED regression, fix, rerun affected/full suites and obtain fresh review until PASS. Do not change diff during review.
- [ ] Run `uv run --with 'fastmcp<4' python tests/run_tests.py fast`, then scenario, then full. Run `uv run --with 'fastmcp<4' python -m unittest discover -s tests -p 'test_*.py' -v`; parse counts and require parity with full. Save actual results, not expected counts.
- [ ] Run `uv run --with 'fastmcp<4' python watchdog_cli.py mechanical --smoke` against the real paper broker with outputs confined to test_artifacts/watchdog. Verify tool catalog mappings, timestamp/protection/quantity coverage and separate full-account equity. No alert delivery, operational appends or broker writes.
- [ ] Run daily --smoke with real bounded source/benchmark reads and inspect report. An unsupported distribution or account-activity capability must be reported as incomplete; it need not fabricate total return to pass. A unavailable broker/data path blocks activation. For absent managed names, exercise live source/classification capability separately with a fixed read-only sample and label it a transport probe, not a portfolio observation.
- [ ] Inspect real private report and sanitizer output; if dashboard is changed, build isolated artifact and verify rendered fields and absence of private data. Do not publish smoke observations.
- [ ] Verify no order was touched by tool allowlist logs and operational input checks. With concurrent legitimate writers, record before/after histories and attribute changes by existing execution IDs rather than falsely claiming byte-identical production inputs. Strong unchanged-file assertions belong to isolated deterministic tests.
- [ ] Commit reviewed explicit files; inspect git show --stat/diff and git status. Push from /opt/data/projects/tradey-desk and verify git ls-remote matches local SHA. No hidden second checkout or mirror deployment.
- [ ] Read back existing scheduler state before any pause/install. Restore paused execution writers only after their reviewed metadata release is verified. Register the two new watchdog jobs with exact paper/read-only scope, workdir, command timeout and origin delivery. Read back exact job IDs, enabled state, cron expression and payload. Do not edit old cadences.
- [ ] Exercise one production monitoring run and read back its exact database/report/outbox target; inspect actual result and once-only digest behavior. Report monitoring coverage limitations and the baseline date. No paper test order. Keep schedules disabled if required runtime probes fail.

## Self-review and handoff

Coverage mapping: spec boundaries/read consistency → Tasks 1–2; identity → Task 3; protection/horizon/exposure → Task 4; accounting/benchmark/account overview → Task 5; thesis → Task 6; storage/privacy/alerts → Task 7; cadence/budgets/isolation → Tasks 6/8; real verification/release → Task 9. No required function interface is left undefined. Missing provider capabilities are explicit coverage outcomes, not guessed schemas.

Recommended execution: subagent-driven, sequential implementation across dependencies, fresh task reviewers, then independent whole-branch review. Native execution with independent final review is an acceptable faster alternative. User must review this plan and select the execution approach before product changes.
