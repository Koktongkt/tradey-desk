# Pinned structural analysis

Revision: `0d3a5a554bf2c36b758f085ab46e56d2a317f7a8`. Local candidate under independent review, not deployed. Independent final review running; approval is parent-owned and separate.

Undirected AST/import/containment/reference discovery, NOT runtime-verified call chains. No model, broker or scheduler calls. Semantic extraction empty; zero extraction LLM tokens (host curated labels are not included in extraction cost). Test symbols are indexed, not proof tests were executed.

Raw health: 535 dangling endpoint edges, 20 self loops, 194 same-endpoint collapses. Raw extraction retained. Built graph contains 47 implicit endpoint nodes beyond 2252 raw nodes. Cohesion values are unaltered library numbers.

# Graph Report - pinned source-only snapshot  (2026-10-10)

## Corpus Check
- 91 files · ~90,490 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2299 nodes · 5544 edges · 110 communities (68 shown, 42 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 252 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Managed Reconciliation
- Watchdog Broker
- Test Watchdog Workflow
- TradeySafety Tests
- Accounting Types
- NarrowRetrySemantics Tests
- Accounting Tests
- Store Tests
- CandidateAlternatives Tests
- Pipeline Tests
- Test Watchdog Schedule
- ScoutReliabilityGuard Tests
- Lineage Tests
- Test Broker Bridge
- AlphaRadar Tests
- Alpha Radar
- ManagedReconciliation Tests
- RunPrecheckDiagnostics Tests
- Benchmark
- BundleRescue Tests
- Test Watchdog Mechanical
- Watchdog Cron
- Broker Mcp Bridge
- Source Worker
- Reports
- Monitor Tests
- Autotrader Shared
- Earnings Calendar
- Cli
- Autotrader Run Locked
- Public Dashboard
- Run Tests
- RetrievalImprovements
- Alpha Radar Helpers
- Market Data
- EarningsCalendar Tests
- ThreeRuntime Tests
- Operational Tests
- Autotrader
- RetrievalHardening Tests
- Cycle Tests
- Classification Tests
- Alpha Radar Live Research
- Test Watchdog Thesis
- Watchdog Store
- Alpha Radar Test Support
- MaintenanceCli Tests
- DailyWorkflow Tests
- Alpha Radar Fetch Source
- BrokerMcpConfig Tests
- NoOpCycleSkip Tests
- Run Cycle
- MarketData Tests
- SqliteLedger Tests
- Alpha Radar Research Run
- Alpha Radar Prepare Candidate
- Alpha Radar Publisher
- Broker Supervisor
- Test Alpha Radar
- Provider Gateway
- Blocker Diagnostics Fixtures
- Broker Normalization
- ForwardLineage Tests
- Autotrader Reconcile Pending
- PlacingNotification Tests
- ProcessLifetime Tests
- Pending Policy
- Alpha Radar Body Parsing
- FocusedRetrievalRerank Tests
- DurableJsonl Tests
- DeadlineContext Tests
- TestArchitecture Tests
- DeliveryAndLock Tests
- Alpha Radar Paths
- Shadow Calibration
- Operational
- Test Broker Normalization
- ConcurrentWorkflow Tests
- ReadonlyQualification Tests
- extract candidate urls
- Candidate Outcomes
- broker order notification line
- BridgeRetry Tests
- RadarReuseFirst Tests
- Baseline Tests
- Mechanical
- AdapterFailure
- Autotrader Managed Exits
- Alpha Radar Isolated Tests
- RadarNotifications
- ResearchBudgetGuard Tests
- Safety Protective Exit Tests
- ReconciliationSnapshotBridge Tests
- ShadowCalibration Tests
- RelayOutput
- Repair Nul Jsonl
- Deadline Tests
- ResearchTimestamp Tests
- Autotrader Blocker Recording
- Autotrader Post Review Validation
- BrokerCredential Tests
- Test Execution Policy
- ExactQuantityExposure Tests
- BridgeCommand Tests
- MarketWindow Tests
- Clock
- Watchdog Store Thesis Tests

## God Nodes (most connected - your core abstractions)
1. `TradeySafetyTests` - 66 edges
2. `build_lineage()` - 62 edges
3. `AlphaRadarTests` - 59 edges
4. `run_watchdog()` - 49 edges
5. `commit_observation()` - 46 edges
6. `AccountingTests` - 44 edges
7. `PipelineTests` - 43 edges
8. `_run_locked()` - 42 edges
9. `fixture()` - 42 edges
10. `observation()` - 38 edges

## Surprising Connections (you probably didn't know these)
- `substitute()` --indirect_call--> `lock()`  [INFERRED]
  tests/test_watchdog_reports.py → entry_state.py
- `read_http_response()` --indirect_call--> `settimeout()`  [INFERRED]
  research_budget.py → tests/test_research_budget.py
- `model()` --indirect_call--> `identity()`  [INFERRED]
  tests/test_watchdog_thesis.py → broker_supervisor.py
- `_get_text()` --indirect_call--> `response()`  [INFERRED]
  earnings_calendar.py → tests/test_candidate_alternatives.py
- `_run_locked()` --indirect_call--> `sessions()`  [INFERRED]
  watchdog/cli.py → entry_expiry.py

## Import Cycles
- None detected.

## Communities (110 total, 42 thin omitted)

### Community 0 - "Managed Reconciliation"
Cohesion: 0.06
Nodes (53): pre_submission_retryable(), metadata(), process(), sessions(), validate_metadata(), check_exact_open_lineage(), check_pending_entries(), check_protection() (+45 more)

### Community 1 - "Watchdog Broker"
Cohesion: 0.06
Nodes (36): rescue_after_fetch(), model(), delayed_fetch(), evidence(), fetch_late(), model(), BrokerBoundaryTests, BrokerSnapshotTests (+28 more)

### Community 2 - "Test Watchdog Workflow"
Cohesion: 0.06
Nodes (16): broker_snapshot(), build_operational_root(), MechanicalWorkflowTests, OperationalInputDigestTests, PathSafetyTests, RuntimeAdapterTests, run(), SmokeDryRunTests (+8 more)

### Community 4 - "Accounting Types"
Cohesion: 0.09
Nodes (23): BrokerWorkerTests, account_overview(), account_strategy(), collect(), _covers(), _drawdown(), _interval(), _marked_curve() (+15 more)

### Community 5 - "NarrowRetrySemantics Tests"
Cohesion: 0.11
Nodes (4): _candidate_hash(), NarrowRetrySemanticsTests, PendingObservationContinuationTests, RunIntegrationTests

### Community 6 - "Accounting Tests"
Cohesion: 0.08
Nodes (3): AccountingTests, fixture(), rounded_fixture()

### Community 7 - "Store Tests"
Cohesion: 0.11
Nodes (9): ReportTests, interrupt(), inject(), locked_read(), substitute(), observation(), StoreTests, commit_observation() (+1 more)

### Community 8 - "CandidateAlternatives Tests"
Cohesion: 0.11
Nodes (3): CandidateAlternativesTests, model(), prices()

### Community 10 - "Test Watchdog Schedule"
Cohesion: 0.12
Nodes (12): read(), CalendarEdgeTests, CronContractTests, DailyEligibilityTests, MechanicalEligibilityTests, session(), utc(), broker() (+4 more)

### Community 11 - "ScoutReliabilityGuard Tests"
Cohesion: 0.06
Nodes (6): GatewayFallbackGuardTests, direct(), fallback(), ScoutReliabilityGuardTests, gateway(), fetch()

### Community 12 - "Lineage Tests"
Cohesion: 0.12
Nodes (8): LineageTests, snapshots(), build_lineage(), candidate_key(), component(), index_order(), resolve(), tokens()

### Community 13 - "Test Broker Bridge"
Cohesion: 0.08
Nodes (5): BrokerBridgeTests, call(), _FakeAlpaca, _FixedDateTime, PendingCapacityTests

### Community 15 - "AlphaRadar Tests"
Cohesion: 0.06
Nodes (3): AlphaRadarTests, _persistable_candidate(), _verified_sources()

### Community 16 - "Alpha Radar"
Cohesion: 0.09
Nodes (20): build_source_receipts(), configured_default_model(), discovery_command(), extract_json(), focused_retrieval(), focused_retrieval_command(), focused_retrieval_prompt(), load_configured_default_model() (+12 more)

### Community 18 - "RunPrecheckDiagnostics Tests"
Cohesion: 0.14
Nodes (10): _candidate(), DryRunDiagnosticsTests, _order(), _quote(), _run_in_root(), fake_bridge(), RunPrecheckDiagnosticsTests, _setup_root() (+2 more)

### Community 19 - "Benchmark"
Cohesion: 0.10
Nodes (9): BenchmarkTests, compare_benchmark(), _day(), load_benchmark(), _rows(), _series(), _total_return_series(), utc_now() (+1 more)

### Community 20 - "BundleRescue Tests"
Cohesion: 0.09
Nodes (7): BundleRescueTests, rescue_url(), fake_urlopen(), fake_urlopen(), fake_urlopen(), fake_urlopen(), _json_response()

### Community 21 - "Test Watchdog Mechanical"
Cohesion: 0.21
Nodes (7): base_fixture(), MechanicalTests, observe(), stop_leg(), target_leg(), aggregate_exposure(), observe_positions()

### Community 23 - "Broker Mcp Bridge"
Cohesion: 0.18
Nodes (20): configured_alpaca_env(), Alpaca, alpaca_mcp_config(), complete_open_orders(), earnings_state(), finite_number(), first_dict(), listish() (+12 more)

### Community 24 - "Source Worker"
Cohesion: 0.12
Nodes (14): ConcreteSourceTests, discover(), inspect(), earnings_coverage(), fetch(), gap(), main(), public_url() (+6 more)

### Community 25 - "Reports"
Cohesion: 0.14
Nodes (17): _default_install(), _amount(), _coverage(), _dict(), _enum(), install_reports(), private_report(), public_summary() (+9 more)

### Community 27 - "Autotrader Shared"
Cohesion: 0.14
Nodes (19): aggregate_proposal_reviews(), _bounded_protective_exit(), build_canonical_proposal(), classify_horizon(), consensus(), derive_technical_levels(), has_blocking_active_order(), _levels_similar() (+11 more)

### Community 28 - "Earnings Calendar"
Cohesion: 0.13
Nodes (12): cached_sec_release_history(), default_trusted_date_loader(), estimate_next_window(), extract_release_date(), _get_json(), _get_text(), nasdaq_earnings_date(), _plain_text() (+4 more)

### Community 29 - "Cli"
Cohesion: 0.13
Nodes (11): _allowed_root(), _Budget, _deliver(), _failed(), _input_digests(), _input_unchanged(), _mark_complete(), _realpath_strict() (+3 more)

### Community 30 - "Autotrader Run Locked"
Cohesion: 0.12
Nodes (18): authoritative_bundle(), build_review_bundle(), _daily_order_count(), dossier_already_reviewed(), emit_placing_notification_once(), idempotency_ref(), load_baseline_symbols(), load_json() (+10 more)

### Community 31 - "Public Dashboard"
Cohesion: 0.16
Nodes (15): bridge_command(), run_bridge(), default_bridge(), activity_summary(), build_data(), fetch_live_portfolio(), html_template(), main() (+7 more)

### Community 32 - "Run Tests"
Cohesion: 0.15
Nodes (12): build_suite(), changed_operational_paths(), discover_modules(), _file_state(), load_manifest(), main(), modules_for_tier(), parse_args() (+4 more)

### Community 33 - "RetrievalImprovements"
Cohesion: 0.09
Nodes (3): RetrievalImprovements, direct(), slow()

### Community 34 - "Alpha Radar Helpers"
Cohesion: 0.16
Nodes (13): candidate_preflight(), earnings_intake_blocker(), earnings_intake_eligible(), _evidence_rank_score(), fresh_verified_candidate(), roles(), qualified(), ranked_candidate_evidence() (+5 more)

### Community 35 - "Market Data"
Cohesion: 0.14
Nodes (10): configured_massive_key(), consolidated_average_volume(), consolidated_daily_bars(), _massive_json(), synchronized_completed_close_prices(), read_mcp_env_process(), raise_if_expired_timeout(), read_http_response() (+2 more)

### Community 37 - "ThreeRuntime Tests"
Cohesion: 0.15
Nodes (3): pending(), ThreeRuntimeTests, broker()

### Community 38 - "Operational Tests"
Cohesion: 0.18
Nodes (4): OperationalTests, local_connect(), connect(), read_operational()

### Community 39 - "Autotrader"
Cohesion: 0.13
Nodes (13): bridge_command(), _broker_bridge(), _contains_provider_error(), _dossier_intact(), _extract_json(), independent_reviews(), _record_bridge_diagnostics(), replace_broker_fields() (+5 more)

### Community 42 - "Classification Tests"
Cohesion: 0.25
Nodes (10): baseline(), ClassificationTests, model(), model(), model_output(), run(), run(), model() (+2 more)

### Community 43 - "Alpha Radar Live Research"
Cohesion: 0.14
Nodes (12): attach_sec_filing_dates(), candidate_alternate_urls(), discovery_prompt(), evidence_failure_code(), filter_evidence(), is_sec_archive_filing_url(), live_research(), merge_candidate_urls() (+4 more)

### Community 44 - "Test Watchdog Thesis"
Cohesion: 0.12
Nodes (5): ConfigTests, ProviderGatewayTests, provider_payload(), live_adapters(), ProviderSession

### Community 45 - "Watchdog Store"
Cohesion: 0.20
Nodes (14): ack_alert(), _conditions(), _connection(), dumps(), _enqueue(), _path(), _pending(), pending_alerts() (+6 more)

### Community 46 - "Alpha Radar Test Support"
Cohesion: 0.16
Nodes (4): rescue(), synth(), _deferred_scout(), _event_pages()

### Community 48 - "DailyWorkflow Tests"
Cohesion: 0.23
Nodes (5): DailySeamTests, slow_broker(), DailyWorkflowTests, broken_install(), read_source_state()

### Community 49 - "Alpha Radar Fetch Source"
Cohesion: 0.14
Nodes (11): extract_page_text(), extract_published_at(), fetch_source(), fetch_source_via_gateway(), gather_evidence(), publish_page(), worker(), is_safe_public_url() (+3 more)

### Community 51 - "NoOpCycleSkip Tests"
Cohesion: 0.25
Nodes (6): _candidate(), NoOpCycleSkipTests, _proposal(), _review_ts(), ReviewBundleStripTests, _snapshot_with_bars()

### Community 52 - "Run Cycle"
Cohesion: 0.25
Nodes (12): audit_result(), cli(), completed_today(), exact_line(), execute(), in_window(), main(), mark_completed() (+4 more)

### Community 53 - "MarketData Tests"
Cohesion: 0.14
Nodes (4): _GroupedResponse, MarketDataTests, _PayloadResponse, _Response

### Community 55 - "Alpha Radar Research Run"
Cohesion: 0.22
Nodes (4): _dated_pair(), _research_none_result(), _research_run(), structured_scout()

### Community 56 - "Alpha Radar Prepare Candidate"
Cohesion: 0.15
Nodes (9): append(), CandidateRejection, decision_line(), ensure_researched_at(), main_with_args(), intake(), normalize_candidate(), prepare_candidate() (+1 more)

### Community 57 - "Alpha Radar Publisher"
Cohesion: 0.16
Nodes (10): rescue_thin_candidates(), post_fetch_rescue_candidate(), candidate_rescue_url(), domains(), note_local_rescue_failure(), prioritize_thin_candidates(), priority(), publisher_domain() (+2 more)

### Community 58 - "Broker Supervisor"
Cohesion: 0.20
Nodes (9): _group_run(), cleanup(), freeze_kill_tree(), visit(), guardian_main(), identity(), main(), reap_owned() (+1 more)

### Community 59 - "Test Alpha Radar"
Cohesion: 0.14
Nodes (4): _lock_once(), _bad_response(), _empty_response(), _RawResponse

### Community 60 - "Provider Gateway"
Cohesion: 0.17
Nodes (5): loads_strict(), classify(), provider_client(), serve(), strict_json()

### Community 61 - "Blocker Diagnostics Fixtures"
Cohesion: 0.17
Nodes (5): broker_snapshot(), policy_config(), technical_bars(), DashboardProjectionTests, SkipEventAuditTests

### Community 62 - "Broker Normalization"
Cohesion: 0.22
Nodes (9): average_volume(), completed_session_average_volume(), daily_bars_request(), find_mapping_with_keys(), latest_quote_request(), massive_daily_bars(), symbol_bars(), symbol_mapping() (+1 more)

### Community 63 - "ForwardLineage Tests"
Cohesion: 0.18
Nodes (3): ForwardLineageTests, broker(), broker()

### Community 64 - "Autotrader Reconcile Pending"
Cohesion: 0.19
Nodes (9): journal_confirmed_fill(), _journal_confirmed_fill_locked(), note_pre_submission_retryable(), note_reconciliation_blocked(), reconcile_pending_orders(), _reconcile_pending_orders_locked(), utcnow(), lock() (+1 more)

### Community 67 - "Pending Policy"
Cohesion: 0.26
Nodes (8): runtime_blockers(), constraints(), digest(), enabled(), Proof, qualify(), state_digest(), valid()

### Community 68 - "Alpha Radar Body Parsing"
Cohesion: 0.18
Nodes (3): fetch(), fetch(), _body()

### Community 73 - "DeliveryAndLock Tests"
Cohesion: 0.23
Nodes (3): DeliveryAndLockTests, slow_broker(), run_budgets()

### Community 74 - "Alpha Radar Paths"
Cohesion: 0.17
Nodes (4): record_research_diagnostics(), record_scout_diagnostic(), record_source_verification_diagnostic(), sec_edgar_filing_url()

### Community 75 - "Shadow Calibration"
Cohesion: 0.42
Nodes (8): _append(), _broker_outcomes(), calibration_report(), main(), measure_outcomes(), read_rows(), record_decision(), refresh()

### Community 76 - "Operational"
Cohesion: 0.24
Nodes (6): _canonical(), _copied_database(), _loads(), _metadata(), _read_operational(), _unique_object()

### Community 80 - "extract candidate urls"
Cohesion: 0.20
Nodes (6): extract_candidate_urls(), extract_scout_candidates(), _gateway_provider_failure(), gateway_rescue_url(), parse_focused_retrieval(), scout_parse_result()

### Community 81 - "Candidate Outcomes"
Cohesion: 0.36
Nodes (4): append(), main(), measure(), read_rows()

### Community 82 - "broker order notification line"
Cohesion: 0.29
Nodes (4): broker_order_notification_line(), exact_terminal_readback(), _notification_plan(), placing_notification_line()

### Community 83 - "BridgeRetry Tests"
Cohesion: 0.36
Nodes (4): BridgeFailureDiagnosticsTests, BridgeRetryTests, _fail_process(), _ok_process()

### Community 85 - "Baseline Tests"
Cohesion: 0.32
Nodes (3): BaselineTests, baseline_from_candidate(), _criteria()

### Community 86 - "Mechanical"
Cohesion: 0.36
Nodes (5): _flatten_orders(), _horizon_status(), _leg_kind(), _protection_status(), _unexpected_exits()

### Community 87 - "AdapterFailure"
Cohesion: 0.25
Nodes (3): AdapterFailure, EvidenceConflict, _strict_json()

### Community 88 - "Autotrader Managed Exits"
Cohesion: 0.33
Nodes (5): _latest_order_statuses(), managed_entry_intents(), pending_order_intents(), reconcile_managed_exits(), _reconcile_managed_exits_locked()

### Community 97 - "Repair Nul Jsonl"
Cohesion: 0.60
Nodes (3): _constant(), _object(), recover()

## Knowledge Gaps
- **42 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ManagedReconciliationTests` connect `ManagedReconciliation Tests` to `Test Watchdog Broker`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Why does `TradeySafetyTests` connect `TradeySafety Tests` to `Safety Protective Exit Tests`, `Test Watchdog Broker`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Why does `CandidateAlternativesTests` connect `CandidateAlternatives Tests` to `Market Data`, `Test Watchdog Broker`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `build_lineage()` (e.g. with `BrokerSnapshot` and `OperationalSnapshot`) actually correct?**
  _`build_lineage()` has 2 INFERRED edges - AST heuristic connections that need verification (no model used)._
- **Should `Managed Reconciliation` be split into smaller, more focused modules?**
  _Cohesion score 0.06241234221598878 - nodes in this community are weakly interconnected._
- **Should `Watchdog Broker` be split into smaller, more focused modules?**
  _Cohesion score 0.06421052631578947 - nodes in this community are weakly interconnected._
- **Should `Test Watchdog Workflow` be split into smaller, more focused modules?**
  _Cohesion score 0.06459627329192547 - nodes in this community are weakly interconnected._

## Interpretation limits

Surprising connections marked INFERRED are AST callback/name-resolution heuristics, not established execution relationships. The suggested questions are discovery prompts, not architectural conclusions. In particular watchdog `_run_locked` to expiry `sessions` and test `model` to supervisor `identity` may be name-resolution artifacts; no monitoring-to-trading/cancellation authorization is implied. The benchmark in BENCHMARK.txt is a CLI estimate using a graph-derived default word count, not measured savings.
