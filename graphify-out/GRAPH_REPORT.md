# Graph Report - pinned-source  (2026-10-23)

## Corpus Check
- 172 files · ~177,327 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 4269 nodes · 10541 edges · 180 communities (103 shown, 77 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 673 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Shared Test Imports
- Autotrader Reconciliation Core
- Broker Snapshot Alternatives
- Discovery Runtime Orchestration
- Research Extraction Tests
- Capture Parsing Utilities
- Publication Interpreter Tests
- Publication Recovery Tests
- Broker Bridge Normalization
- Trading Safety Tests
- Structured Extraction Tests
- Watchdog Store Notifications
- Watchdog Workflow Tests
- Cycle Dashboard Orchestration
- Runtime Snapshot Locking
- Pending Reconciliation Tests
- Execution Blocker Diagnostics
- Watchdog Accounting Types
- Extraction Compatibility Tests
- Watchdog Persistence Reports
- Focused Reuse Tests
- Radar Intake Tests
- Pipeline Dashboard Tests
- Live Evidence Retrieval
- Managed Exit Reconciliation
- Watchdog Accounting Tests
- Public Dashboard Data
- SQLite Durable Journals
- Radar Source Validation
- Watchdog Lineage Tests
- Earnings Deadline Utilities
- Watchdog Schedule Eligibility
- Discovery Pipeline Tests
- Publication Integration Tests
- Publication Recovery Probes
- Managed Reconciliation Tests
- Extraction Provider Compatibility
- Keenable Deadline Tests
- Publication Observation Validation
- Gateway Fallback Tests
- Watchdog Notification Tests
- Operational Snapshot Tests
- Thesis Provider Adapters
- Candidate Intake Persistence
- Candidate Evidence Qualification
- Publication Observation Tests
- Benchmark Comparison Reports
- Canonical Proposal Validation
- Mechanical Exposure Tests
- Thesis Monitoring Tests
- Cycle Cadence Tests
- Focused Search Tests
- Pending Runtime Tests
- Research Extraction Dispatch
- Search Budget Receipts
- Radar Research Tests
- Watchdog Report Rendering
- Retained Article Parsing
- Retrieval Concurrency Tests
- Candidate Synthesis Commands
- Focused Search Protocol
- Deferred Rescue Tests
- Daily Watchdog Tests
- Retained Recovery Tests
- Broker Bridge Tests
- Earnings Calendar Tests
- Publication Probe Tests
- Rescue Fairness Tests
- Structured Batch Supervision
- Focused Pipeline Probes
- Runtime Credential Mechanics
- Watchdog Source Discovery
- Deadline HTTP Transport
- Layered Test Runner
- Retained Article Tests
- SQLite Ledger Tests
- Thesis Classification Tests
- Focused URL Allocation
- Dashboard Publish Tests
- Broker Process Supervision
- Publication Recovery Selection
- Radar Evidence Rescue
- Extraction Boundary Tests
- Maintenance Reconciliation Tests
- Bridge Reuse Contracts
- Broker MCP Tests
- Batch Worker Tests
- Noop Cycle Tests
- Publication Date Candidates
- Extraction Capacity Probe
- Retrieval Redirect Tests
- Focused Handoff Tests
- Market Data Tests
- Publication Provenance Tests
- Offline Test Guards
- Focused Coverage Execution
- Batch Supervisor Tests
- Process Lifetime Tests
- Offline Network Boundaries
- Issuer Publication Parsing
- Forward Lineage Tests
- Focused Safety Tests
- Project Extraction Probe
- Focused Retrieval Reranking
- URL Allocation Tests
- Singleton Transport Tests
- Order Notification Tests
- Test Architecture Tests
- Focused Coverage Cohorts
- Shadow Calibration Reports
- SEC Rescue Tests
- Broker Security Tests
- Concurrent Execution Tests
- Durable JSONL Tests
- Watchdog CLI Wiring
- Probe Child Diagnostics
- Pending Capacity Tests
- Date Candidate Tests
- Research Deadline Tests
- Gateway Gap Retrieval
- Source Worker Completion
- Broker Normalization Tests
- Discovery Collection Tests
- Dashboard Process Containment
- Readonly Qualification Tests
- Broker Calendar Tests
- Focused Capture Wrappers
- Probe Safety Guards
- Scout Freshness Tests
- Discovery State Tests
- Batch Entry Tests
- Mixed Batch Responses
- Radar Reuse Tests
- Discovery Evaluation Tests
- Gap Retrieval Tests
- Issuer Capture Tests
- Thesis Baseline Creation
- Focused Capture Containers
- Focused Supervisor Errors
- Dashboard Worker Tests
- Radar Notification Tests
- Runtime Path Tests
- Broker Snapshot Projection
- Thesis Adapter Failures
- Candidate Outcome Measurement
- Batch URL Validation
- Discovery History Tests
- Discovery Process Tests
- Singleton Isolation Tests
- Readonly Snapshot Tests
- Protective Exit Tests
- Shadow Calibration Tests
- Candidate Retry Eligibility
- Earnings Rejection Persistence
- Provider Transport Failures
- JSONL NUL Repair
- Radar Rescue Fallbacks
- Entry Expiry Tests
- Research Timestamp Tests
- Synthesis Horizon Tests
- Blocking Order Recognition
- Earnings Rejection Identity
- Capacity Probe Tests
- Pathlike Launch Tests
- Discovery Failure Types
- Exact Exposure Tests
- Reconciliation Clock Fixture
- Dashboard Diagnostics Tests
- Portable Cron Tests
- Provider Publication Tests
- Offline Suite Entrypoints
- Concurrent Clock Fixture
- Execution Policy Tests
- Market Window Tests
- NUL Repair Tests
- Rescue Clock Fixture
- Thesis Store Fixtures

## God Nodes (most connected - your core abstractions)
1. `TradeySafetyTests` - 74 edges
2. `AlphaRadarTests` - 67 edges
3. `build_lineage()` - 62 edges
4. `run_watchdog()` - 60 edges
5. `DispatcherTests` - 50 edges
6. `_run_locked()` - 49 edges
7. `PipelineTests` - 47 edges
8. `commit_observation()` - 46 edges
9. `AccountingTests` - 44 edges
10. `StructuredExtractionTests` - 43 edges

## Surprising Connections (you probably didn't know these)
- `read()` --calls--> `error()`  [INFERRED]
  tests/test_structured_extraction.py → extraction_worker.py
- `read_http_response()` --indirect_call--> `settimeout()`  [INFERRED]
  research_budget.py → tests/test_research_budget.py
- `rescue_after_fetch()` --indirect_call--> `pages()`  [INFERRED]
  tests/test_alpha_radar.py → watchdog/broker.py
- `gather()` --indirect_call--> `pages()`  [INFERRED]
  tests/test_publication_recovery.py → watchdog/broker.py
- `gather()` --indirect_call--> `pages()`  [INFERRED]
  tests/test_research_budget.py → watchdog/broker.py

## Import Cycles
- 3-file cycle: `alpha_radar.py -> focused_pipeline.py -> focused_allocation.py -> alpha_radar.py`

## Communities (180 total, 77 thin omitted)

### Community 0 - "Shared Test Imports"
Cohesion: 0.06
Nodes (7): broker_snapshot(), policy_config(), technical_bars(), assert_dead(), blocked_probe(), Clock, SkipEventAuditTests

### Community 1 - "Autotrader Reconciliation Core"
Cohesion: 0.05
Nodes (60): aggregate_proposal_reviews(), authoritative_bundle(), blocker_diagnostics_rows(), _broker_bridge(), broker_order_notification_line(), broker_review_validation(), build_review_bundle(), _contains_provider_error() (+52 more)

### Community 2 - "Broker Snapshot Alternatives"
Cohesion: 0.05
Nodes (27): CandidateAlternativesTests, model(), delayed_fetch(), evidence(), model(), intake(), model(), prices() (+19 more)

### Community 3 - "Discovery Runtime Orchestration"
Cohesion: 0.05
Nodes (32): collect_lanes(), one(), _error(), make_queries(), _project(), discover(), run_selector(), failed() (+24 more)

### Community 4 - "Research Extraction Tests"
Cohesion: 0.07
Nodes (8): provider_publication(), DispatcherTests, invoke(), invoke(), RealTransportTests, vendor(), extract(), row()

### Community 5 - "Capture Parsing Utilities"
Cohesion: 0.05
Nodes (19): _parent(), read_history(), record_history(), _safe_fd(), execute(), main(), request_state(), _save() (+11 more)

### Community 6 - "Publication Interpreter Tests"
Cohesion: 0.07
Nodes (9): InterpreterTests, runner(), factory(), slow_build(), LocalSupervisorTests, spawn(), page(), proposal() (+1 more)

### Community 7 - "Publication Recovery Tests"
Cohesion: 0.06
Nodes (9): observation(), page(), RecoveryTests, slow(), model(), model(), RecoveryWiringTests, gather() (+1 more)

### Community 8 - "Broker Bridge Normalization"
Cohesion: 0.07
Nodes (37): error_envelope(), Alpaca, alpaca_mcp_config(), complete_open_orders(), earnings_state(), finite_number(), first_dict(), listish() (+29 more)

### Community 10 - "Structured Extraction Tests"
Cohesion: 0.06
Nodes (9): envelope(), module(), StructuredExtractionTests, dispatch(), dispatch(), dispatch(), read(), read() (+1 more)

### Community 11 - "Watchdog Store Notifications"
Cohesion: 0.07
Nodes (33): _allowed_root(), _default_install(), _failed(), _input_digests(), _input_unchanged(), _mark_complete(), _realpath_strict(), _reporting_retry() (+25 more)

### Community 12 - "Watchdog Workflow Tests"
Cohesion: 0.07
Nodes (11): NotificationWorkflowTests, DeliveryAndLockTests, MechanicalWorkflowTests, OperationalInputDigestTests, PathSafetyTests, SmokeDryRunTests, TransportBucketTests, WorkflowCase (+3 more)

### Community 13 - "Cycle Dashboard Orchestration"
Cohesion: 0.07
Nodes (32): classify(), _collect_attempt(), deploy(), main(), record_attempt(), run_attempt(), decode_result(), helper() (+24 more)

### Community 14 - "Runtime Snapshot Locking"
Cohesion: 0.06
Nodes (18): lock(), _lock_once(), AdversarialNotificationTests, fail_install(), substitute(), broker_snapshot(), RuntimeAdapterTests, run() (+10 more)

### Community 15 - "Pending Reconciliation Tests"
Cohesion: 0.09
Nodes (5): _candidate_hash(), NarrowRetrySemanticsTests, PendingObservationContinuationTests, RunIntegrationTests, broker()

### Community 16 - "Execution Blocker Diagnostics"
Cohesion: 0.09
Nodes (12): _candidate(), DryRunDiagnosticsTests, EarningsSpendingTests, approve(), _order(), _quote(), _run_in_root(), fake_bridge() (+4 more)

### Community 17 - "Watchdog Accounting Types"
Cohesion: 0.09
Nodes (26): BrokerWorkerTests, account_overview(), account_strategy(), collect(), _covers(), _drawdown(), _interval(), _marked_curve() (+18 more)

### Community 18 - "Extraction Compatibility Tests"
Cohesion: 0.06
Nodes (12): CompatibilityTests, importer(), sdk(), async_extract(), extract(), extract(), importer(), async_fail() (+4 more)

### Community 19 - "Watchdog Persistence Reports"
Cohesion: 0.11
Nodes (11): ReportTests, interrupt(), inject(), locked_read(), observation(), StoreTests, install_reports(), commit_observation() (+3 more)

### Community 20 - "Focused Reuse Tests"
Cohesion: 0.08
Nodes (16): wrapped(), result(), collected(), capture_module(), FocusedReuseTests, original(), row(), original() (+8 more)

### Community 21 - "Radar Intake Tests"
Cohesion: 0.05
Nodes (4): AlphaRadarTests, _isolate_main_root(), _persistable_candidate(), _verified_sources()

### Community 23 - "Live Evidence Retrieval"
Cohesion: 0.07
Nodes (27): attach_sec_filing_dates(), candidate_alternate_urls(), correlated_research_run(), evidence_failure_code(), filter_evidence(), focused_retrieval(), is_sec_archive_filing_url(), live_research() (+19 more)

### Community 24 - "Managed Exit Reconciliation"
Cohesion: 0.11
Nodes (28): metadata(), process(), sessions(), validate_metadata(), check_exact_open_lineage(), check_pending_entries(), check_protection(), check_quantities() (+20 more)

### Community 25 - "Watchdog Accounting Tests"
Cohesion: 0.08
Nodes (3): AccountingTests, fixture(), rounded_fixture()

### Community 26 - "Public Dashboard Data"
Cohesion: 0.10
Nodes (24): bridge_command(), bridge_command(), broker_executable(), run_bridge(), default_bridge(), activity_summary(), build_data(), fetch_live_portfolio() (+16 more)

### Community 27 - "SQLite Durable Journals"
Cohesion: 0.15
Nodes (24): append_jsonl(), backup_database(), _canonical(), _connect(), database_path(), _database_rows(), _ensure_parent(), _insert() (+16 more)

### Community 28 - "Radar Source Validation"
Cohesion: 0.08
Nodes (21): extract_gateway_publication_date(), extract_page_text(), extract_published_at(), fetch_source(), fetch_source_via_gateway(), failed(), _gateway_provider_failure(), gather_evidence() (+13 more)

### Community 29 - "Watchdog Lineage Tests"
Cohesion: 0.12
Nodes (8): LineageTests, snapshots(), build_lineage(), candidate_key(), component(), index_order(), resolve(), tokens()

### Community 30 - "Earnings Deadline Utilities"
Cohesion: 0.07
Nodes (21): cached_sec_release_history(), default_trusted_date_loader(), estimate_next_window(), extract_release_date(), _get_json(), _get_text(), nasdaq_earnings_date(), _plain_text() (+13 more)

### Community 31 - "Watchdog Schedule Eligibility"
Cohesion: 0.12
Nodes (12): read(), CalendarEdgeTests, CronContractTests, DailyEligibilityTests, MechanicalEligibilityTests, session(), utc(), broker() (+4 more)

### Community 32 - "Discovery Pipeline Tests"
Cohesion: 0.13
Nodes (9): prepare_prompt(), PipelineTests, state(), save(), collect(), prompt(), collection(), proposal() (+1 more)

### Community 33 - "Publication Integration Tests"
Cohesion: 0.09
Nodes (6): envelope(), PublicationIntegrationTests, interpret(), rescue(), runner(), raw()

### Community 34 - "Publication Recovery Probes"
Cohesion: 0.08
Nodes (20): interpret_publications(), diagnostics(), fail(), _prepare_request(), PublicationProcessError, run_publication_process(), _valid_page(), evaluate() (+12 more)

### Community 36 - "Extraction Provider Compatibility"
Cohesion: 0.14
Nodes (25): _available(), _call(), check_url(), CompatibilityError, _config(), _enabled(), _function(), _invoke() (+17 more)

### Community 37 - "Keenable Deadline Tests"
Cohesion: 0.09
Nodes (6): KeenableTests, connect(), payload(), TCPDeadlineTests, create(), dispatch()

### Community 38 - "Publication Observation Validation"
Cohesion: 0.13
Nodes (15): binding_contexts(), build_observation(), _contexts(), _current_article(), _dates(), _hash(), _instant_after(), normalize_support() (+7 more)

### Community 39 - "Gateway Fallback Tests"
Cohesion: 0.07
Nodes (6): GatewayFallbackGuardTests, direct(), fallback(), ScoutReliabilityGuardTests, gateway(), fetch()

### Community 40 - "Watchdog Notification Tests"
Cohesion: 0.20
Nodes (5): NotificationTests, fail(), run(), observation(), _deliver()

### Community 41 - "Operational Snapshot Tests"
Cohesion: 0.12
Nodes (8): OperationalTests, _canonical(), _copied_database(), _loads(), _metadata(), read_operational(), _read_operational(), _unique_object()

### Community 42 - "Thesis Provider Adapters"
Cohesion: 0.09
Nodes (11): ConcreteSourceTests, ConfigTests, ProviderGatewayTests, classify(), provider_payload(), serve(), strict_json(), live_adapters() (+3 more)

### Community 43 - "Candidate Intake Persistence"
Cohesion: 0.08
Nodes (18): append(), decision_line(), ensure_researched_at(), main_with_args(), intake(), normalize_candidate(), prepare_candidate(), record_focused_allocation() (+10 more)

### Community 44 - "Candidate Evidence Qualification"
Cohesion: 0.11
Nodes (19): build_source_receipts(), candidate_preflight(), discovery_max_event_age_days(), discovery_prompt(), earnings_intake_blocker(), earnings_intake_eligible(), _evidence_rank_score(), extract_scout_candidates() (+11 more)

### Community 45 - "Publication Observation Tests"
Cohesion: 0.16
Nodes (5): evaluate_publication(), observe(), page_for(), PublicationObservationTests, article_page()

### Community 46 - "Benchmark Comparison Reports"
Cohesion: 0.10
Nodes (9): BenchmarkTests, compare_benchmark(), _day(), load_benchmark(), _rows(), _series(), _total_return_series(), utc_now() (+1 more)

### Community 47 - "Canonical Proposal Validation"
Cohesion: 0.11
Nodes (21): build_canonical_proposal(), classify_horizon(), consensus(), derive_technical_levels(), _levels_similar(), recomputed_reward_risk(), _spread_bps(), _valid_decision() (+13 more)

### Community 48 - "Mechanical Exposure Tests"
Cohesion: 0.21
Nodes (7): base_fixture(), MechanicalTests, observe(), stop_leg(), target_leg(), aggregate_exposure(), observe_positions()

### Community 51 - "Focused Search Tests"
Cohesion: 0.12
Nodes (9): BoundaryTests, prepare(), run(), manifest(), ManifestTests, module(), QueryContractTests, ReceiptTests (+1 more)

### Community 52 - "Pending Runtime Tests"
Cohesion: 0.13
Nodes (3): pending(), ThreeRuntimeTests, broker()

### Community 53 - "Research Extraction Dispatch"
Cohesion: 0.14
Nodes (19): extract(), extraction_extensions(), publication_record(), _bind(), _bounded(), _compat_reason(), _envelope(), _error() (+11 more)

### Community 54 - "Search Budget Receipts"
Cohesion: 0.10
Nodes (6): parse_search_manifest(), SearchReceipt, extraction_miss(), search_done(), validation_done(), ResearchBudgetGuardTests

### Community 55 - "Radar Research Tests"
Cohesion: 0.12
Nodes (6): run(), rescue_after_fetch(), _dated_pair(), _research_none_result(), _research_run(), structured_scout()

### Community 56 - "Watchdog Report Rendering"
Cohesion: 0.15
Nodes (18): _conditions(), _amount(), _coverage(), daily_notification(), dashboard_summary(), _dict(), _enum(), private_report() (+10 more)

### Community 57 - "Retained Article Parsing"
Cohesion: 0.15
Nodes (12): _article(), _ArticleHTML, body_context(), _digest(), _html_parts(), _markdown_header(), _normal(), original_text() (+4 more)

### Community 59 - "Candidate Synthesis Commands"
Cohesion: 0.09
Nodes (15): CandidateRejection, configured_default_model(), discovery_command(), extract_json(), focused_retrieval_command(), load_configured_default_model(), research_command(), research_subprocess_command() (+7 more)

### Community 60 - "Focused Search Protocol"
Cohesion: 0.13
Nodes (12): focused_retrieval_prompt(), _parse_manifest(), read_search_capture(), search_alternatives(), _search_command(), search_prompt(), SearchProtocolError, SearchRecorder (+4 more)

### Community 61 - "Deferred Rescue Tests"
Cohesion: 0.14
Nodes (5): BundleRescueTests, rescue(), synth(), _deferred_scout(), _event_pages()

### Community 62 - "Daily Watchdog Tests"
Cohesion: 0.15
Nodes (6): build_operational_root(), DailySeamTests, slow_broker(), DailyWorkflowTests, broken_install(), slow_broker()

### Community 63 - "Retained Recovery Tests"
Cohesion: 0.19
Nodes (5): retain_article(), RetainedRecoveryTests, runner(), interpret(), interpret()

### Community 67 - "Rescue Fairness Tests"
Cohesion: 0.14
Nodes (9): page(), replay(), gateway(), gather(), run(), sec(), spend(), RescueFairnessTests (+1 more)

### Community 68 - "Structured Batch Supervision"
Cohesion: 0.16
Nodes (13): batch_error(), extract_batch(), valid_batch_request(), _batch_supervisor_failure(), failure(), run_batch_worker(), _run_process(), run_validation_worker() (+5 more)

### Community 69 - "Focused Pipeline Probes"
Cohesion: 0.16
Nodes (3): allocation(), candidates(), ProbeTests

### Community 70 - "Runtime Credential Mechanics"
Cohesion: 0.13
Nodes (5): configured_alpaca_env(), read_mcp_env_process(), _executable(), hermes_cli(), BrokerCredentialTests

### Community 71 - "Watchdog Source Discovery"
Cohesion: 0.16
Nodes (12): discover(), inspect(), earnings_coverage(), fetch(), gap(), main(), public_url(), retrieve() (+4 more)

### Community 72 - "Deadline HTTP Transport"
Cohesion: 0.10
Nodes (7): is_error_document(), _deadline_tcp(), _DeadlineReader, _DeadlineSocket, _DeadlineTLS, fetch(), _remaining()

### Community 73 - "Layered Test Runner"
Cohesion: 0.13
Nodes (12): build_suite(), changed_operational_paths(), discover_modules(), _file_state(), load_manifest(), main(), modules_for_tier(), parse_args() (+4 more)

### Community 76 - "Thesis Classification Tests"
Cohesion: 0.25
Nodes (10): baseline(), ClassificationTests, model(), model(), model_output(), run(), run(), model() (+2 more)

### Community 77 - "Focused URL Allocation"
Cohesion: 0.18
Nodes (10): allocate_urls(), Allocation, _syntax_valid(), _check(), extract_allocated(), FocusedFailure, FocusedResult, run_focused_pipeline() (+2 more)

### Community 78 - "Dashboard Publish Tests"
Cohesion: 0.15
Nodes (7): load(), NativeTests, connect(), call(), PayloadTests, PublishTests, call()

### Community 79 - "Broker Process Supervision"
Cohesion: 0.17
Nodes (11): _group_run(), cleanup(), freeze_kill_tree(), visit(), guardian_main(), identity(), main(), reap_owned() (+3 more)

### Community 80 - "Publication Recovery Selection"
Cohesion: 0.20
Nodes (11): body_repair_needed(), _attach(), candidate_recovery_page(), choose_recovery_pages(), _known_instant(), _policy(), recover_publications(), _recover_publications() (+3 more)

### Community 81 - "Radar Evidence Rescue"
Cohesion: 0.12
Nodes (4): fetch(), fetch(), _body(), rescue_url()

### Community 84 - "Bridge Reuse Contracts"
Cohesion: 0.13
Nodes (6): BridgeCommandTests, BridgeFailureDiagnosticsTests, BridgeRetryTests, _fail_process(), _ok_process(), SnapshotErrorContractTests

### Community 86 - "Batch Worker Tests"
Cohesion: 0.20
Nodes (7): BatchWorkerTests, rescue(), extract(), extract(), dispatch(), dispatch(), row()

### Community 87 - "Noop Cycle Tests"
Cohesion: 0.25
Nodes (6): _candidate(), NoOpCycleSkipTests, _proposal(), _review_ts(), ReviewBundleStripTests, _snapshot_with_bars()

### Community 88 - "Publication Date Candidates"
Cohesion: 0.12
Nodes (6): _attr_value(), date_candidate_text(), _ld_article_dates(), _publish_meta(), _RetainedHTML, evaluate_date_candidates()

### Community 89 - "Extraction Capacity Probe"
Cohesion: 0.22
Nodes (13): failed_urls(), main(), observe(), route(), save(), summarize(), wrapped_keyless(), wrapped_primary() (+5 more)

### Community 92 - "Market Data Tests"
Cohesion: 0.14
Nodes (4): _GroupedResponse, MarketDataTests, _PayloadResponse, _Response

### Community 94 - "Offline Test Guards"
Cohesion: 0.16
Nodes (7): _audit(), expected_local_control(), _finish(), install(), successful(), summary(), _unexpected()

### Community 95 - "Focused Coverage Execution"
Cohesion: 0.12
Nodes (7): account(), execute(), focus(), observed(), guarded_command(), qualify_owned(), command()

### Community 98 - "Offline Network Boundaries"
Cohesion: 0.17
Nodes (4): install(), guard(), local(), OfflineBoundaryTests

### Community 99 - "Issuer Publication Parsing"
Cohesion: 0.18
Nodes (3): _ArticleHeader, _identity(), issuer_publication_date()

### Community 100 - "Forward Lineage Tests"
Cohesion: 0.18
Nodes (3): ForwardLineageTests, broker(), broker()

### Community 101 - "Focused Safety Tests"
Cohesion: 0.19
Nodes (5): SearchResult, run(), search(), validate(), SafetyTests

### Community 102 - "Project Extraction Probe"
Cohesion: 0.23
Nodes (8): child(), observe(), profile(), main(), run_probe(), transport_start(), validate_cohort(), write_private()

### Community 103 - "Focused Retrieval Reranking"
Cohesion: 0.14
Nodes (3): gather(), gather(), FocusedRetrievalRerankTests

### Community 105 - "Singleton Transport Tests"
Cohesion: 0.16
Nodes (5): run(), run(), run(), run(), success()

### Community 108 - "Focused Coverage Cohorts"
Cohesion: 0.24
Nodes (8): child_state_redirect(), main(), parse_as_of(), private_path(), qualify_pages(), run_probe(), validate_cohort(), write_private()

### Community 109 - "Shadow Calibration Reports"
Cohesion: 0.37
Nodes (8): _append(), _broker_outcomes(), calibration_report(), main(), measure_outcomes(), read_rows(), record_decision(), refresh()

### Community 110 - "SEC Rescue Tests"
Cohesion: 0.19
Nodes (5): fake_urlopen(), fake_urlopen(), fake_urlopen(), fake_urlopen(), _json_response()

### Community 111 - "Broker Security Tests"
Cohesion: 0.31
Nodes (3): BrokerSecurityEnvelopeTests, _FixtureSession, _security_envelope()

### Community 115 - "Probe Child Diagnostics"
Cohesion: 0.23
Nodes (7): child_diagnostics(), event(), measured_envelope(), measured_size(), save(), write(), child_sinks()

### Community 119 - "Gateway Gap Retrieval"
Cohesion: 0.22
Nodes (7): extract_candidate_urls(), gateway_rescue_url(), parse_focused_retrieval(), roles(), source_profile(), GapContainmentError, search_gap()

### Community 120 - "Source Worker Completion"
Cohesion: 0.18
Nodes (5): finish(), worker(), run_source(), failed(), capture()

### Community 125 - "Broker Calendar Tests"
Cohesion: 0.22
Nodes (3): call(), _FakeAlpaca, _FixedDateTime

### Community 126 - "Focused Capture Wrappers"
Cohesion: 0.25
Nodes (5): Recorder, captured(), dispatch(), main(), handler()

### Community 127 - "Probe Safety Guards"
Cohesion: 0.36
Nodes (7): install_safety(), allowed(), audit(), guard_fd_write(), call(), guarded_open(), target()

### Community 128 - "Scout Freshness Tests"
Cohesion: 0.22
Nodes (4): raw(), _bad_response(), _empty_response(), _RawResponse

### Community 131 - "Mixed Batch Responses"
Cohesion: 0.25
Nodes (5): check(), primary(), primary(), dispatch(), worker()

### Community 136 - "Thesis Baseline Creation"
Cohesion: 0.32
Nodes (3): BaselineTests, baseline_from_candidate(), _criteria()

### Community 142 - "Broker Snapshot Projection"
Cohesion: 0.48
Nodes (7): normalize_account(), normalize_activity(), normalize_order(), normalize_position(), normalize_session(), project(), require()

### Community 144 - "Candidate Outcome Measurement"
Cohesion: 0.47
Nodes (4): append(), main(), measure(), read_rows()

### Community 145 - "Batch URL Validation"
Cohesion: 0.33
Nodes (3): main(), bounded(), validate_batch_urls()

### Community 155 - "JSONL NUL Repair"
Cohesion: 0.60
Nodes (3): _constant(), _object(), recover()

## Knowledge Gaps
- **77 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AlphaRadarTests` connect `Radar Intake Tests` to `Shared Test Imports`, `Scout Freshness Tests`, `Focused Retrieval Reranking`, `Radar Evidence Rescue`, `Radar Research Tests`, `Radar Rescue Fallbacks`, `Article Extraction Tests`?**
  _High betweenness centrality (0.044) - this node is a cross-community bridge._
- **Why does `CompatibilityTests` connect `Extraction Compatibility Tests` to `Runtime Credential Mechanics`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Why does `StructuredExtractionTests` connect `Structured Extraction Tests` to `Shared Test Imports`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **Should `Shared Test Imports` be split into smaller, more focused modules?**
  _Cohesion score 0.060143418922044875 - nodes in this community are weakly interconnected._
- **Should `Autotrader Reconciliation Core` be split into smaller, more focused modules?**
  _Cohesion score 0.04923206395960446 - nodes in this community are weakly interconnected._
- **Should `Broker Snapshot Alternatives` be split into smaller, more focused modules?**
  _Cohesion score 0.05263157894736842 - nodes in this community are weakly interconnected._
- **Should `Discovery Runtime Orchestration` be split into smaller, more focused modules?**
  _Cohesion score 0.04887218045112782 - nodes in this community are weakly interconnected._