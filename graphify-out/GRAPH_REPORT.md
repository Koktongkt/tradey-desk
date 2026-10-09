# Graph Report - Tradey Desk — source-only snapshot  (2026-10-09)

## Corpus Check
- 90 files · ~85,328 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2152 nodes · 5104 edges · 110 communities (63 shown, 47 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 244 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Watchdog Position Lineage
- Read-only Broker Snapshots
- Trading Safety Tests
- Exchange Session Eligibility
- Durable Journals and Calibration
- Observation Commits and Reports
- Blocker Diagnostics Test Harness
- Candidate Alternatives Tests
- Pipeline Contract Tests
- Portfolio Accounting Tests
- Watchdog Workflow and Locks
- Earnings Sources and Budgets
- Gateway Fallback Tests
- Radar Qualification Tests
- Watchdog Runtime Adapters
- Exact Managed Order Reconciliation
- Research Discovery and Retrieval
- Research Evidence Rescue
- Pending Bracket Regression Tests
- Public Thesis Source Workers
- Autotrader Retry Regression Tests
- Candidate Intake and Reuse
- Thesis Monitoring Tests
- Isolated Provider Worker Wiring
- Sanitized Watchdog Reporting
- Deterministic Broker Bridge
- Tiered Regression Runner
- Concurrent Retrieval Tests
- Watchdog Observation Orchestration
- Research Pipeline Fixtures
- Earnings Calendar Tests
- Operational Snapshot Tests
- Canonical Proposals and Horizons
- Retrieval Hardening Tests
- Scheduled Cycle Tests
- Broker Bridge Contract Tests
- Thesis Classification Tests
- Fill Journaling and Diagnostics
- Market Data Normalization
- Deferred Research Rescue Tests
- Market Data Loader Tests
- Reconciliation Maintenance Tests
- Daily Reporting Workflow Tests
- Bounded Thesis Retrieval
- Candidate Spending and No-op Tests
- Broker Review and Evidence
- Alert Receipts and State
- Scheduled Desk Cycle
- Dashboard Verification Utilities
- SQLite Ledger Regression Tests
- Dual Review and Risk Gates
- Public Dashboard Projection
- Thin Evidence Rescue Tests
- Broker Snapshot Types
- Managed Strategy and Account Accounting
- SEC Rescue Cache Tests
- Candidate Qualification and Persistence
- Thesis Synthesis and Market Marks
- Safe Web Evidence Fetching
- Broker Subprocess Boundary
- Benchmark Coverage Tests
- Forward Lineage Regression Tests
- Pending Alert Retry Tests
- Autotrader Notifications and Reuse
- Shared Integration Test Fixtures
- Source Retrieval Test Fixtures
- Candidate Reranking Tests
- Durable Journal Write Tests
- Order Notification Tests
- Research Deadline Tests
- Benchmark Series and Coverage
- Research Failure Diagnostics
- Broker Retry Tests
- Broker Normalization Tests
- Read-only Operational Ledger Access
- Provider Gateway Classification
- Candidate Outcome Measurement
- Timestamp Normalization Tests
- Radar Dossier Reuse Tests
- Radar Notification Tests
- Research Budget Gate Tests
- Versioned Thesis Baselines
- Mechanical Protection Observations
- Managed Exit and Intent Selection
- Credential Resolver Process Boundary
- Read-only Reconciliation Snapshot Tests
- Shadow Calibration Tests
- Offline JSONL Salvage Utility
- Failed Response Test Fixture
- Empty Response Test Fixture
- Credential Boundary Tests
- Monitoring Deadline Budget
- Dashboard Deployment Script
- Exact Exposure Regression Tests
- Autotrader Cron Launcher
- Dashboard Cron Launcher
- Post-close Cron Launcher
- Premarket Cron Launcher
- Radar Cron Launcher
- Daily Watchdog Launcher
- Mechanical Watchdog Launcher
- Execution Policy Regression Tests
- Market Window Regression Tests
- JSONL Salvage Regression Tests
- Material Thesis Event Tests

## God Nodes (most connected - your core abstractions)
1. `TradeySafetyTests` - 66 edges
2. `build_lineage()` - 62 edges
3. `AlphaRadarTests` - 59 edges
4. `run_watchdog()` - 49 edges
5. `commit_observation()` - 46 edges
6. `AccountingTests` - 44 edges
7. `PipelineTests` - 43 edges
8. `fixture()` - 42 edges
9. `run()` - 39 edges
10. `observation()` - 38 edges

## Surprising Connections (you probably didn't know these)
- `read_http_response()` --indirect_call--> `settimeout()`  [INFERRED]
  research_budget.py → tests/test_research_budget.py
- `CandidateAlternativesTests` --uses--> `ResearchDeadlineExceeded`  [INFERRED]
  tests/test_candidate_alternatives.py → research_budget.py
- `gather()` --indirect_call--> `pages()`  [INFERRED]
  tests/test_alpha_radar.py → watchdog/broker.py
- `rescue_after_fetch()` --indirect_call--> `pages()`  [INFERRED]
  tests/test_alpha_radar.py → watchdog/broker.py
- `evidence()` --indirect_call--> `pages()`  [INFERRED]
  tests/test_candidate_alternatives.py → watchdog/broker.py

## Import Cycles
- None detected.

## Communities (110 total, 47 thin omitted)

### Community 0 - "Watchdog Position Lineage"
Cohesion: 0.07
Nodes (16): LineageTests, snapshots(), base_fixture(), MechanicalTests, observe(), stop_leg(), target_leg(), build_lineage() (+8 more)

### Community 1 - "Read-only Broker Snapshots"
Cohesion: 0.06
Nodes (37): rescue_after_fetch(), model(), delayed_fetch(), evidence(), fetch_late(), model(), BrokerBoundaryTests, BrokerSnapshotTests (+29 more)

### Community 3 - "Exchange Session Eligibility"
Cohesion: 0.07
Nodes (14): BrokerBridgeTests, _FakeAlpaca, _FixedDateTime, CalendarEdgeTests, CronContractTests, DailyEligibilityTests, MechanicalEligibilityTests, session() (+6 more)

### Community 4 - "Durable Journals and Calibration"
Cohesion: 0.11
Nodes (31): pre_submission_retryable(), _append(), _broker_outcomes(), calibration_report(), main(), measure_outcomes(), read_rows(), record_decision() (+23 more)

### Community 5 - "Observation Commits and Reports"
Cohesion: 0.10
Nodes (8): ReportTests, interrupt(), inject(), locked_read(), observation(), StoreTests, commit_observation(), read_report()

### Community 7 - "Blocker Diagnostics Test Harness"
Cohesion: 0.09
Nodes (13): _candidate(), DryRunDiagnosticsTests, _order(), _quote(), _run_in_root(), fake_bridge(), RunPrecheckDiagnosticsTests, _setup_root() (+5 more)

### Community 8 - "Candidate Alternatives Tests"
Cohesion: 0.11
Nodes (3): CandidateAlternativesTests, model(), prices()

### Community 10 - "Portfolio Accounting Tests"
Cohesion: 0.09
Nodes (3): AccountingTests, fixture(), rounded_fixture()

### Community 11 - "Watchdog Workflow and Locks"
Cohesion: 0.11
Nodes (9): broker_snapshot(), DeliveryAndLockTests, slow_broker(), MechanicalWorkflowTests, OperationalInputDigestTests, PathSafetyTests, WorkflowCase, run_budgets() (+1 more)

### Community 12 - "Earnings Sources and Budgets"
Cohesion: 0.09
Nodes (19): cached_sec_release_history(), default_trusted_date_loader(), estimate_next_window(), extract_release_date(), _get_json(), _get_text(), nasdaq_earnings_date(), _plain_text() (+11 more)

### Community 13 - "Gateway Fallback Tests"
Cohesion: 0.06
Nodes (6): GatewayFallbackGuardTests, direct(), fallback(), ScoutReliabilityGuardTests, gateway(), fetch()

### Community 14 - "Radar Qualification Tests"
Cohesion: 0.06
Nodes (3): AlphaRadarTests, _persistable_candidate(), _verified_sources()

### Community 15 - "Watchdog Runtime Adapters"
Cohesion: 0.08
Nodes (8): RuntimeAdapterTests, run(), main(), configured_benchmark(), configured_broker(), RelayOutput, _run_worker(), OperationalSnapshot

### Community 16 - "Exact Managed Order Reconciliation"
Cohesion: 0.14
Nodes (22): check_exact_open_lineage(), check_pending_entries(), check_protection(), check_quantities(), cli(), exact_order_lineage(), visit(), exit_legs() (+14 more)

### Community 17 - "Research Discovery and Retrieval"
Cohesion: 0.09
Nodes (18): configured_default_model(), discovery_command(), extract_candidate_urls(), extract_page_text(), extract_scout_candidates(), fetch_source_via_gateway(), focused_retrieval(), focused_retrieval_command() (+10 more)

### Community 18 - "Research Evidence Rescue"
Cohesion: 0.09
Nodes (20): attach_sec_filing_dates(), candidate_alternate_urls(), discovery_prompt(), evidence_failure_code(), filter_evidence(), is_sec_archive_filing_url(), live_research(), rescue_thin_candidates() (+12 more)

### Community 20 - "Public Thesis Source Workers"
Cohesion: 0.12
Nodes (14): ConcreteSourceTests, discover(), inspect(), earnings_coverage(), fetch(), gap(), main(), public_url() (+6 more)

### Community 21 - "Autotrader Retry Regression Tests"
Cohesion: 0.18
Nodes (3): _candidate_hash(), NarrowRetrySemanticsTests, RunIntegrationTests

### Community 22 - "Candidate Intake and Reuse"
Cohesion: 0.14
Nodes (15): candidate_preflight(), earnings_intake_blocker(), earnings_intake_eligible(), _evidence_rank_score(), fresh_verified_candidate(), merge_candidate_urls(), roles(), qualified() (+7 more)

### Community 24 - "Isolated Provider Worker Wiring"
Cohesion: 0.10
Nodes (7): ConfigTests, ProviderGatewayTests, provider_payload(), live_adapters(), ProviderSession, JSONCommand, _strict_json()

### Community 25 - "Sanitized Watchdog Reporting"
Cohesion: 0.16
Nodes (17): _amount(), _coverage(), dashboard_summary(), _dict(), _enum(), install_reports(), private_report(), public_summary() (+9 more)

### Community 26 - "Deterministic Broker Bridge"
Cohesion: 0.20
Nodes (18): Alpaca, alpaca_mcp_config(), earnings_state(), finite_number(), first_dict(), listish(), main(), named_mapping() (+10 more)

### Community 27 - "Tiered Regression Runner"
Cohesion: 0.14
Nodes (12): build_suite(), changed_operational_paths(), discover_modules(), _file_state(), load_manifest(), main(), modules_for_tier(), parse_args() (+4 more)

### Community 28 - "Concurrent Retrieval Tests"
Cohesion: 0.09
Nodes (3): RetrievalImprovements, direct(), slow()

### Community 29 - "Watchdog Observation Orchestration"
Cohesion: 0.15
Nodes (12): _allowed_root(), _default_install(), _deliver(), _failed(), _input_digests(), _input_unchanged(), _mark_complete(), _realpath_strict() (+4 more)

### Community 30 - "Research Pipeline Fixtures"
Cohesion: 0.14
Nodes (5): gather(), _dated_pair(), _research_none_result(), _research_run(), structured_scout()

### Community 32 - "Operational Snapshot Tests"
Cohesion: 0.18
Nodes (4): OperationalTests, local_connect(), connect(), read_operational()

### Community 33 - "Canonical Proposals and Horizons"
Cohesion: 0.17
Nodes (15): build_canonical_proposal(), classify_horizon(), consensus(), derive_technical_levels(), _levels_similar(), normalize_order_metrics(), pre_review_validation(), recomputed_reward_risk() (+7 more)

### Community 37 - "Thesis Classification Tests"
Cohesion: 0.25
Nodes (10): baseline(), ClassificationTests, model(), model(), model_output(), run(), run(), model() (+2 more)

### Community 38 - "Fill Journaling and Diagnostics"
Cohesion: 0.13
Nodes (10): blocker_diagnostics_rows(), broker_order_notification_line(), journal_confirmed_fill(), note_pre_submission_retryable(), note_reconciliation_blocked(), reconcile_pending_orders(), record_blocker_diagnostics(), utcnow() (+2 more)

### Community 39 - "Market Data Normalization"
Cohesion: 0.18
Nodes (11): average_volume(), completed_session_average_volume(), daily_bars_request(), find_mapping_with_keys(), latest_quote_request(), massive_daily_bars(), symbol_bars(), symbol_mapping() (+3 more)

### Community 40 - "Deferred Research Rescue Tests"
Cohesion: 0.16
Nodes (4): rescue(), synth(), _deferred_scout(), _event_pages()

### Community 41 - "Market Data Loader Tests"
Cohesion: 0.12
Nodes (4): _GroupedResponse, MarketDataTests, _PayloadResponse, _Response

### Community 43 - "Daily Reporting Workflow Tests"
Cohesion: 0.23
Nodes (5): DailySeamTests, slow_broker(), DailyWorkflowTests, broken_install(), read_source_state()

### Community 44 - "Bounded Thesis Retrieval"
Cohesion: 0.13
Nodes (7): AdapterFailure, _compact_receipts(), _criteria(), EvidenceConflict, monitor_theses(), _priority(), timestamp()

### Community 45 - "Candidate Spending and No-op Tests"
Cohesion: 0.25
Nodes (6): _candidate(), NoOpCycleSkipTests, _proposal(), _review_ts(), ReviewBundleStripTests, _snapshot_with_bars()

### Community 46 - "Broker Review and Evidence"
Cohesion: 0.13
Nodes (12): authoritative_bundle(), broker_review_validation(), build_review_bundle(), idempotency_ref(), main(), managed_exposure(), post_review_validation(), record_shadow_if_live() (+4 more)

### Community 47 - "Alert Receipts and State"
Cohesion: 0.21
Nodes (11): ack_alert(), _conditions(), _connection(), dumps(), _enqueue(), _path(), _persist_theses(), read_latest_report() (+3 more)

### Community 48 - "Scheduled Desk Cycle"
Cohesion: 0.25
Nodes (12): audit_result(), cli(), completed_today(), exact_line(), execute(), in_window(), main(), mark_completed() (+4 more)

### Community 49 - "Dashboard Verification Utilities"
Cohesion: 0.13
Nodes (4): check(), main(), shutil_which(), run()

### Community 51 - "Dual Review and Risk Gates"
Cohesion: 0.16
Nodes (11): aggregate_proposal_reviews(), _bounded_protective_exit(), _dossier_intact(), _extract_json(), has_blocking_active_order(), independent_reviews(), replace_broker_fields(), research_acceptable() (+3 more)

### Community 52 - "Public Dashboard Projection"
Cohesion: 0.27
Nodes (11): activity_summary(), build_data(), fetch_live_portfolio(), html_template(), main(), rows(), sanitize_audit_row(), sanitize_candidate_row() (+3 more)

### Community 54 - "Broker Snapshot Types"
Cohesion: 0.21
Nodes (5): BrokerWorkerTests, aware_timestamp(), BrokerSnapshot, LineageResult, snapshot_time_reasons()

### Community 55 - "Managed Strategy and Account Accounting"
Cohesion: 0.26
Nodes (11): account_overview(), account_strategy(), collect(), _covers(), _drawdown(), _interval(), _marked_curve(), _planned_geometry() (+3 more)

### Community 56 - "SEC Rescue Cache Tests"
Cohesion: 0.15
Nodes (5): fake_urlopen(), fake_urlopen(), fake_urlopen(), fake_urlopen(), _json_response()

### Community 57 - "Candidate Qualification and Persistence"
Cohesion: 0.15
Nodes (9): append(), decision_line(), ensure_researched_at(), main_with_args(), intake(), normalize_candidate(), prepare_candidate(), source_verification_result() (+1 more)

### Community 58 - "Thesis Synthesis and Market Marks"
Cohesion: 0.15
Nodes (8): build_source_receipts(), CandidateRejection, extract_json(), ResearchFailure, synthesis_prompt(), SynthesisWindowExhausted, synthesize_candidate(), synchronized_completed_close_prices()

### Community 59 - "Safe Web Evidence Fetching"
Cohesion: 0.18
Nodes (9): extract_published_at(), fetch_source(), gather_evidence(), publish_page(), worker(), is_safe_public_url(), safe_urlopen(), SafeRedirectHandler (+1 more)

### Community 60 - "Broker Subprocess Boundary"
Cohesion: 0.15
Nodes (8): bridge_command(), _broker_bridge(), _contains_provider_error(), _record_bridge_diagnostics(), _run_reviewer_process(), bridge_command(), run_bridge(), default_bridge()

### Community 62 - "Forward Lineage Regression Tests"
Cohesion: 0.18
Nodes (3): ForwardLineageTests, broker(), broker()

### Community 63 - "Pending Alert Retry Tests"
Cohesion: 0.20
Nodes (5): build_operational_root(), SmokeDryRunTests, TransportBucketTests, _pending(), pending_alerts()

### Community 64 - "Autotrader Notifications and Reuse"
Cohesion: 0.16
Nodes (9): _daily_order_count(), dossier_already_reviewed(), emit_placing_notification_once(), load_baseline_symbols(), load_json(), output_paths(), placing_notification_line(), reconcile_managed_protection() (+1 more)

### Community 65 - "Shared Integration Test Fixtures"
Cohesion: 0.20
Nodes (5): broker_snapshot(), policy_config(), technical_bars(), DashboardProjectionTests, SkipEventAuditTests

### Community 66 - "Source Retrieval Test Fixtures"
Cohesion: 0.18
Nodes (3): fetch(), fetch(), _body()

### Community 71 - "Benchmark Series and Coverage"
Cohesion: 0.22
Nodes (7): _day(), load_benchmark(), _rows(), _series(), _total_return_series(), utc_now(), main()

### Community 72 - "Research Failure Diagnostics"
Cohesion: 0.17
Nodes (5): record_research_diagnostics(), record_scout_diagnostic(), record_source_verification_diagnostic(), record_synthesis_none(), synthesis_none_reason()

### Community 73 - "Broker Retry Tests"
Cohesion: 0.26
Nodes (5): BridgeCommandTests, BridgeFailureDiagnosticsTests, BridgeRetryTests, _fail_process(), _ok_process()

### Community 75 - "Read-only Operational Ledger Access"
Cohesion: 0.27
Nodes (6): _canonical(), _copied_database(), _loads(), _metadata(), _read_operational(), _unique_object()

### Community 76 - "Provider Gateway Classification"
Cohesion: 0.25
Nodes (4): classify(), provider_client(), serve(), strict_json()

### Community 77 - "Candidate Outcome Measurement"
Cohesion: 0.36
Nodes (4): append(), main(), measure(), read_rows()

### Community 83 - "Mechanical Protection Observations"
Cohesion: 0.43
Nodes (5): _flatten_orders(), _horizon_status(), _leg_kind(), _protection_status(), _unexpected_exits()

### Community 84 - "Managed Exit and Intent Selection"
Cohesion: 0.40
Nodes (4): _latest_order_statuses(), managed_entry_intents(), pending_order_intents(), reconcile_managed_exits()

### Community 89 - "Offline JSONL Salvage Utility"
Cohesion: 0.60
Nodes (3): _constant(), _object(), recover()

## Knowledge Gaps
- **7 isolated node(s):** `autotrader.sh script`, `dashboard.sh script`, `postclose.sh script`, `premarket.sh script`, `radar.sh script` (+2 more)
  These have ≤1 connection - possible missing edges. (Counts symbols only; 734 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **47 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CandidateAlternativesTests` connect `Candidate Alternatives Tests` to `Earnings Sources and Budgets`, `Python Utilities and Test Infrastructure`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Why does `PipelineTests` connect `Pipeline Contract Tests` to `Python Utilities and Test Infrastructure`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Why does `TradeySafetyTests` connect `Trading Safety Tests` to `Concurrent Exit Regression Tests`, `Protective Stop Fill Tests`, `Python Utilities and Test Infrastructure`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `build_lineage()` (e.g. with `BrokerSnapshot` and `OperationalSnapshot`) actually correct?**
  _`build_lineage()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `autotrader.sh script`, `dashboard.sh script`, `postclose.sh script` to the rest of the system?**
  _7 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Watchdog Position Lineage` be split into smaller, more focused modules?**
  _Cohesion score 0.07226107226107226 - nodes in this community are weakly interconnected._
- **Should `Read-only Broker Snapshots` be split into smaller, more focused modules?**
  _Cohesion score 0.06322624743677376 - nodes in this community are weakly interconnected._
## Scope and integrity limitations

Source revision: bb88070b998d5a406c99de2b252867e4caebdc2b. Only tracked source code and tests were copied; no private ledger, credentials, account state or generated artifacts were read. Documentation semantics were deliberately excluded.

This is Graphify's default undirected structural graph, not a verified runtime call graph. Inferred symbol-resolution edges can be false positives, especially common callback names in tests. In particular, the reported test callbacks linked to broker pages() are candidates for inspection, not established production dependencies.

Raw extraction diagnostics: 468 dangling-endpoint edges, 19 self-loops and 190 same-endpoint relation collapses. The builder can materialize unresolved references, so exported node totals exceed explicit extraction-node totals. These are extraction/graph representation limitations, not demonstrated trading defects. See GRAPH_HEALTH.json and EXTRACTION_AUDIT.json for the audit evidence.

Structural extraction used zero model/API tokens. The host's community naming and this conversation are not included in that extraction-token counter. Nothing was pushed, no hook/server was installed, and no trading or scheduler state was changed.
