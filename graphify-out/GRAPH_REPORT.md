# Graph Report - pinned-source  (2026-11-19)

## Corpus Check
- 212 files · ~228,858 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 5649 nodes · 14592 edges · 228 communities (140 shown, 88 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 891 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Autotrader Order Proposals
- Extraction Parsing Utilities
- Cycle Dashboard Orchestration
- Managed Reconciliation Tests
- Opportunity State Tests
- Entry Authority Execution Tests
- Radar Candidate Policy
- Opportunity Admin Tests
- Publication Interpreter Tests
- Publication Recovery Tests
- Trading Safety Tests
- Watchdog Store Reports
- Extraction Compatibility Tests
- Watchdog Workflow Tests
- Public Dashboard Data
- SQLite Durable Journals
- Managed Exit Reconciliation
- Pending Reconciliation Tests
- Execution Blocker Diagnostics
- Entry Eligibility Tests
- Watchdog Persistence Reports
- Research Deadline Enrichment
- Research Extraction Tests
- Watchdog Thesis Accounting
- Radar Intake Tests
- Opportunity Admin Claims
- Focused Pipeline Tests
- Opportunity Index State
- Runtime Snapshot Locking
- Discovery Pipeline Modules
- Candidate Alternatives Tests
- Opportunity Radar Policy Tests
- Watchdog Accounting Tests
- Watchdog CLI Wiring
- Focused Reuse Tests
- Research Memory Store Tests
- Watchdog Lineage Tests
- Radar Source Validation
- Pipeline Dashboard Tests
- Pending Runtime Tests
- Publication Integration Tests
- Structured Extraction Tests
- Candidate Evidence Qualification
- Discovery Pipeline Tests
- Publication Recovery Probes
- Retained Recovery Tests
- Publisher URL Rescue
- Watchdog Broker Types
- Publication Observation Validation
- Read-Only Broker Snapshots
- Keenable Deadline Tests
- Radar Research Memory
- Focused Search Protocol
- Earnings Identity Resolution
- Runtime Credential Mechanics
- Focused Coverage Execution
- Watchdog Notification Tests
- Live Research Recovery
- Opportunity Identity Tests
- SQLite Ledger Tests
- Watchdog Schedule Eligibility
- Radar Research Tests
- Opportunity Cutover Tests
- Memory Radar Tests
- Entry Authority Validation
- Broker Bridge Tests
- Operational Snapshot Tests
- Broker MCP Bridge
- Thesis Monitoring Tests
- Extraction Provider Compatibility
- Opportunity State Validation
- Cycle Cadence Tests
- Mechanical Exposure Tests
- Broker Normalization Tests
- Publication Recovery Selection
- Focused Search Tests
- Entry Fill Reconciliation
- Broker Order Collection
- Batch Supervisor Tests
- Dashboard Publish Tests
- Batch Worker Tests
- Thesis Provider Adapters
- Identity Evidence Acquisition
- Broker Process Supervision
- Focused URL Allocation
- Publication Observation Tests
- Enrichment Diagnostics Tests
- Structured Batch Supervision
- Opportunity Retention Tests
- Opportunity Workflow Scenarios
- Acquisition Research Tests
- Deferred Rescue Tests
- Research Extraction Dispatch
- Layered Test Runner
- Earnings Calendar Tests
- Daily Watchdog Tests
- Thesis Classification Tests
- Opportunity Identity Binding
- Runtime Support Fixtures
- Research Memory Transition
- Retained Article Tests
- Watchdog Source Discovery
- Entry Buy Eligibility
- Ledger Policy Index
- Identity Acquisition Tests
- Retrieval Concurrency Tests
- Review History Tests
- Bridge Reuse Contracts
- Reopening Claim Observations
- Radar Evidence Rescue
- Extraction Boundary Tests
- Maintenance Reconciliation Tests
- Rescue Fairness Tests
- Offline Test Guards
- Activation Dossier Versions
- Scout Freshness Tests
- Broker MCP Tests
- Focused Pipeline Probes
- Gateway Fallback Tests
- Noop Cycle Tests
- Extraction Capacity Probe
- Focused Handoff Tests
- Publication Provenance Tests
- Benchmark Comparison Reports
- Research Budget Guards
- Real Transport Tests
- Opportunity Cutover Activation
- Publication Date Candidates
- Market Data Tests
- Opportunity Activation Tests
- Process Lifetime Tests
- Date Candidate Tests
- Forward Lineage Tests
- Operational Entry State
- Earnings Resolution Tests
- URL Allocation Tests
- Activation Ordering Tests
- Test Architecture Tests
- Fetch Fairness Tests
- Evidence Capture Store
- Project Extraction Probe
- SEC Rescue Tests
- Broker Security Tests
- Concurrent Execution Tests
- Durable JSONL Tests
- Research Budget Context
- Identity Cover Parsing
- Probe Child Diagnostics
- Acquisition Observation Tests
- Order Notification Tests
- Research Deadline Tests
- Probe Safety Guards
- Shadow Calibration Reports
- Offline Network Boundaries
- Discovery Collection Tests
- Dashboard Process Containment
- Readonly Qualification Tests
- Scout Reliability Guards
- Focused Capture Containers
- Retained Article Parsing
- Focused Retrieval Reranking
- Broker Calendar Tests
- Memory Key Tests
- Compat Extraction Invocation
- Focused Capture Wrappers
- Publication Interpreter
- Provider Publication Tests
- Discovery State Tests
- Protective Exit Tests
- Configured Broker Reader
- Issuer Publication Parsing
- Radar Reuse Tests
- Discovery Evaluation Tests
- Identity Capture Tests
- Gap Retrieval Tests
- Issuer Capture Tests
- Runtime Path Tests
- Watchdog Mechanical Exits
- Evidence Readiness Tests
- Radar Notification Tests
- Thesis Baseline Creation
- Acquisition Link Parser
- Discovery History Tests
- Discovery Process Tests
- Radar Identity Handoff
- Batch Entry Tests
- Primary Fetch Failure Tests
- Readonly Snapshot Tests
- Memory Workflow Tests
- Shadow Calibration Tests
- Supervisor Descendant Tests
- Provider Transport Failures
- JSONL NUL Repair
- Missing History Fixtures
- Synthetic Resolution Fixtures
- Radar Rescue Fallbacks
- Entry Expiry Tests
- Keenable Response Fake
- Gateway Retry Tests
- Research Timestamp Tests
- Synthesis Horizon Tests
- Candidate Outcome Measurement
- Earnings Rejection Identity
- Dashboard Theme Tests
- Capacity Probe Tests
- Radar Persistence Ordering
- Pathlike Launch Tests
- Exact Exposure Tests
- Reconciliation Clock Fixture
- Dashboard Diagnostics Tests
- Portable Cron Tests
- Identity Diagnostic Tests
- Fixed Execution Clock
- Concurrent Clock Fixture
- Execution Policy Tests
- Market Window Tests
- Rescue Clock Fixture

## God Nodes (most connected - your core abstractions)
1. `TradeySafetyTests` - 82 edges
2. `OpportunityStateTests` - 77 edges
3. `AlphaRadarTests` - 68 edges
4. `retain_article()` - 66 edges
5. `OpportunityAdminTests` - 62 edges
6. `RadarPolicyTests` - 62 edges
7. `build_lineage()` - 62 edges
8. `_run_locked()` - 61 edges
9. `live_research()` - 60 edges
10. `run_watchdog()` - 58 edges

## Surprising Connections (you probably didn't know these)
- `substitute()` --indirect_call--> `lock()`  [INFERRED]
  tests/test_watchdog_reports.py → entry_state.py
- `sleep()` --indirect_call--> `lock()`  [INFERRED]
  tests/test_watchdog_workflow.py → entry_state.py
- `read()` --calls--> `error()`  [INFERRED]
  tests/test_structured_extraction.py → extraction_worker.py
- `read_http_response()` --indirect_call--> `settimeout()`  [INFERRED]
  research_budget.py → tests/test_research_budget.py
- `rescued()` --indirect_call--> `target()`  [INFERRED]
  tests/test_acquisition_research.py → scripts/probe_focused_coverage.py

## Import Cycles
- 3-file cycle: `alpha_radar.py -> focused_pipeline.py -> focused_allocation.py -> alpha_radar.py`

## Communities (228 total, 88 thin omitted)

### Community 1 - "Autotrader Order Proposals"
Cohesion: 0.04
Nodes (81): _admissible_review(), aggregate_proposal_reviews(), _append_reviewer_diagnostic_row(), authoritative_bundle(), blocker_diagnostics_rows(), _bounded_protective_exit(), _broker_bridge(), broker_review_validation() (+73 more)

### Community 2 - "Extraction Parsing Utilities"
Cohesion: 0.04
Nodes (25): collect_lanes(), one(), _error(), _project(), execute(), main(), stockanalysis_earnings_date(), traced() (+17 more)

### Community 3 - "Cycle Dashboard Orchestration"
Cohesion: 0.05
Nodes (34): classify(), _collect_attempt(), deploy(), main(), record_attempt(), run_attempt(), decode_result(), helper() (+26 more)

### Community 4 - "Managed Reconciliation Tests"
Cohesion: 0.06
Nodes (7): acquire(), EntryFillReplayTests, ManagedReconciliationTests, reconcile_batch(), competitor(), run(), transport()

### Community 6 - "Entry Authority Execution Tests"
Cohesion: 0.06
Nodes (11): AuthorityTests, ProspectiveExecutionTests, _dossier(), _dt_shim(), EntryBoundaryTests, ExecutionCase, bridge(), FinalRecheckTests (+3 more)

### Community 7 - "Radar Candidate Policy"
Cohesion: 0.06
Nodes (42): is_observation_envelope(), is_research_only_input(), append(), _bind_policy_candidate(), CandidateRejection, correlated_research_run(), wrapped(), decision_line() (+34 more)

### Community 8 - "Opportunity Admin Tests"
Cohesion: 0.08
Nodes (3): canonical_bytes(), digest_of(), OpportunityAdminTests

### Community 9 - "Publication Interpreter Tests"
Cohesion: 0.07
Nodes (7): InterpreterTests, runner(), factory(), LocalSupervisorTests, spawn(), page(), proposal()

### Community 10 - "Publication Recovery Tests"
Cohesion: 0.06
Nodes (9): observation(), page(), RecoveryTests, slow(), model(), model(), RecoveryWiringTests, gather() (+1 more)

### Community 12 - "Watchdog Store Reports"
Cohesion: 0.08
Nodes (38): _claim(), _conditions(), _daily_claim(), emit_check_failure(), emit_notifications(), _send(), _amount(), _coverage() (+30 more)

### Community 13 - "Extraction Compatibility Tests"
Cohesion: 0.05
Nodes (15): AppOwnedQuerySafetyTests, module(), forbidden(), CompatibilityTests, importer(), sdk(), async_extract(), extract() (+7 more)

### Community 14 - "Watchdog Workflow Tests"
Cohesion: 0.07
Nodes (12): NotificationWorkflowTests, DeliveryAndLockTests, MechanicalWorkflowTests, OperationalInputDigestTests, PathSafetyTests, broker(), sleep(), SmokeDryRunTests (+4 more)

### Community 15 - "Public Dashboard Data"
Cohesion: 0.08
Nodes (28): bridge_command(), bridge_command(), broker_executable(), run_bridge(), default_bridge(), activity_summary(), build_data(), fetch_live_portfolio() (+20 more)

### Community 16 - "SQLite Durable Journals"
Cohesion: 0.13
Nodes (33): append_jsonl(), backup_database(), _canonical_lock(), check_deadline(), _connect(), database_path(), _database_rows(), _ensure_parent() (+25 more)

### Community 17 - "Managed Exit Reconciliation"
Cohesion: 0.09
Nodes (35): metadata(), process(), sessions(), validate_metadata(), check_exact_open_lineage(), check_pending_entries(), check_protection(), check_quantities() (+27 more)

### Community 18 - "Pending Reconciliation Tests"
Cohesion: 0.09
Nodes (5): _candidate_hash(), NarrowRetrySemanticsTests, PendingObservationContinuationTests, RunIntegrationTests, broker()

### Community 19 - "Execution Blocker Diagnostics"
Cohesion: 0.09
Nodes (12): _candidate(), DryRunDiagnosticsTests, EarningsSpendingTests, approve(), _order(), _quote(), _run_in_root(), fake_bridge() (+4 more)

### Community 20 - "Entry Eligibility Tests"
Cohesion: 0.08
Nodes (13): canonical_digest(), EntryFixtureBase, add(), broker(), write(), EvaluateBuyFailClosedTests, EvaluateBuyTests, LocalEntryExclusionsTests (+5 more)

### Community 21 - "Watchdog Persistence Reports"
Cohesion: 0.10
Nodes (12): ReportTests, interrupt(), inject(), locked_read(), substitute(), observation(), StoreTests, install_reports() (+4 more)

### Community 22 - "Research Deadline Enrichment"
Cohesion: 0.08
Nodes (30): _condition_enrichment(), synthesize_candidate(), cached_sec_release_history(), default_trusted_date_loader(), estimate_next_window(), extract_release_date(), _get_json(), _get_text() (+22 more)

### Community 24 - "Watchdog Thesis Accounting"
Cohesion: 0.07
Nodes (23): loads_strict(), account_overview(), account_strategy(), collect(), _covers(), _interval(), _marked_curve(), _planned_geometry() (+15 more)

### Community 25 - "Radar Intake Tests"
Cohesion: 0.05
Nodes (4): AlphaRadarTests, _isolate_main_root(), _persistable_candidate(), _verified_sources()

### Community 26 - "Opportunity Admin Claims"
Cohesion: 0.12
Nodes (30): lock(), _lock_once(), activate(), _append_grant(), audit_history(), _canonical(), canonical_manifest_digest(), _claim_store_rows() (+22 more)

### Community 27 - "Focused Pipeline Tests"
Cohesion: 0.08
Nodes (17): SearchResult, SupervisorFailure, allocation(), candidates(), PipelineTests, run(), run(), provider() (+9 more)

### Community 28 - "Opportunity Index State"
Cohesion: 0.09
Nodes (23): Condition, evaluate_condition(), make_reopening_claim(), restore_reopening_claim(), _verify_claim_against_index(), EventResolution, _attempt_authorized(), AttemptAuthorization (+15 more)

### Community 29 - "Runtime Snapshot Locking"
Cohesion: 0.08
Nodes (12): AdversarialNotificationTests, fail_install(), broker_snapshot(), RuntimeAdapterTests, run(), sleep(), configured(), broker() (+4 more)

### Community 30 - "Discovery Pipeline Modules"
Cohesion: 0.09
Nodes (23): make_queries(), _parent(), read_history(), record_history(), _safe_fd(), discover(), run_selector(), admit_selection() (+15 more)

### Community 31 - "Candidate Alternatives Tests"
Cohesion: 0.10
Nodes (7): CandidateAlternativesTests, model(), evidence(), model(), intake(), model(), prices()

### Community 32 - "Opportunity Radar Policy Tests"
Cohesion: 0.08
Nodes (4): RadarPolicyTests, discovery(), scout(), synth()

### Community 33 - "Watchdog Accounting Tests"
Cohesion: 0.09
Nodes (5): AccountingTests, fixture(), rounded_fixture(), normalize_position(), OperationalSnapshot

### Community 34 - "Watchdog CLI Wiring"
Cohesion: 0.07
Nodes (15): _allowed_root(), _Budget, _default_install(), _failed(), _input_digests(), _input_unchanged(), main(), _mark_complete() (+7 more)

### Community 35 - "Focused Reuse Tests"
Cohesion: 0.09
Nodes (10): result(), collected(), capture_module(), FocusedReuseTests, original(), row(), original(), original() (+2 more)

### Community 36 - "Research Memory Store Tests"
Cohesion: 0.11
Nodes (7): append(), fail_ack(), MemoryStoreTests, fail_ack(), MemoryTransitionTests, lost(), race()

### Community 37 - "Watchdog Lineage Tests"
Cohesion: 0.12
Nodes (8): LineageTests, snapshots(), build_lineage(), candidate_key(), component(), index_order(), resolve(), tokens()

### Community 38 - "Radar Source Validation"
Cohesion: 0.07
Nodes (24): extract_gateway_publication_date(), extract_page_text(), extract_published_at(), fetch_source(), fetch_source_via_gateway(), failed(), _gateway_provider_failure(), gather_evidence() (+16 more)

### Community 40 - "Pending Runtime Tests"
Cohesion: 0.09
Nodes (4): pending(), PendingCapacityTests, ThreeRuntimeTests, broker()

### Community 41 - "Publication Integration Tests"
Cohesion: 0.08
Nodes (8): envelope(), PublicationIntegrationTests, interpreting(), recover(), interpret(), rescue(), runner(), raw()

### Community 42 - "Structured Extraction Tests"
Cohesion: 0.10
Nodes (7): envelope(), module(), StructuredExtractionTests, dispatch(), dispatch(), dispatch(), dispatch()

### Community 43 - "Candidate Evidence Qualification"
Cohesion: 0.08
Nodes (24): build_source_receipts(), candidate_preflight(), discovery_max_event_age_days(), discovery_prompt(), earnings_intake_blocker(), earnings_intake_eligible(), ensure_researched_at(), _evidence_rank_score() (+16 more)

### Community 44 - "Discovery Pipeline Tests"
Cohesion: 0.13
Nodes (9): prepare_prompt(), PipelineTests, state(), save(), collect(), prompt(), collection(), proposal() (+1 more)

### Community 45 - "Publication Recovery Probes"
Cohesion: 0.07
Nodes (21): configured_default_model(), load_configured_default_model(), research_subprocess_command(), synthesis_command(), PublicationProcessError, run_publication_process(), admit(), evaluate() (+13 more)

### Community 46 - "Retained Recovery Tests"
Cohesion: 0.11
Nodes (11): _project(), _digest(), _markdown_header(), original_text(), publication_witnesses(), retain_article(), visible_header_text(), RetainedRecoveryTests (+3 more)

### Community 47 - "Publisher URL Rescue"
Cohesion: 0.08
Nodes (23): attach_sec_filing_dates(), candidate_alternate_urls(), extract_candidate_urls(), gateway_rescue_url(), is_sec_archive_filing_url(), merge_candidate_urls(), parse_focused_retrieval(), post_fetch_rescue_candidate() (+15 more)

### Community 48 - "Watchdog Broker Types"
Cohesion: 0.10
Nodes (9): BrokerWorkerTests, _drawdown(), load_benchmark(), _rows(), utc_now(), main(), BrokerSnapshot, LineageResult (+1 more)

### Community 49 - "Publication Observation Validation"
Cohesion: 0.11
Nodes (15): binding_contexts(), build_observation(), _contexts(), _current_article(), _dates(), _hash(), _instant_after(), normalize_support() (+7 more)

### Community 50 - "Read-Only Broker Snapshots"
Cohesion: 0.15
Nodes (9): model(), BrokerBoundaryTests, BrokerSnapshotTests, bracket(), order(), PaginatedTransport, responses(), Transport (+1 more)

### Community 51 - "Keenable Deadline Tests"
Cohesion: 0.09
Nodes (6): KeenableTests, connect(), payload(), TCPDeadlineTests, create(), dispatch()

### Community 52 - "Radar Research Memory"
Cohesion: 0.12
Nodes (28): _complete_memory(), _memory_note(), complete_work(), _document(), fresh(), issuer_for_pages(), IssuerConflict, MemoryWork (+20 more)

### Community 53 - "Focused Search Protocol"
Cohesion: 0.10
Nodes (14): run_private_child(), _parse_manifest(), parse_search_manifest(), read_search_capture(), search_alternatives(), _search_command(), search_prompt(), SearchProtocolError (+6 more)

### Community 54 - "Earnings Identity Resolution"
Cohesion: 0.11
Nodes (20): _issuer(), literal_acquisition_links(), acquire_identity_captures(), _note_handoff_deadline(), _State, identity_source_bytes(), _Body, earnings_exhibit_links() (+12 more)

### Community 55 - "Runtime Credential Mechanics"
Cohesion: 0.08
Nodes (10): configured_alpaca_env(), focused_command(), worker_command(), read_mcp_env_process(), _executable(), hermes_cli(), hermes_runtime(), isolated_runpy_command() (+2 more)

### Community 56 - "Focused Coverage Execution"
Cohesion: 0.08
Nodes (19): finish(), account(), child_state_redirect(), execute(), focus(), worker(), guarded_command(), main() (+11 more)

### Community 57 - "Watchdog Notification Tests"
Cohesion: 0.20
Nodes (5): NotificationTests, fail(), run(), observation(), _deliver()

### Community 58 - "Live Research Recovery"
Cohesion: 0.09
Nodes (19): acquisition_hint(), evidence_failure_code(), filter_evidence(), live_research(), policy_bundle(), publication_handler(), recover_stage(), rescue_thin_candidates() (+11 more)

### Community 59 - "Opportunity Identity Tests"
Cohesion: 0.17
Nodes (6): resolve_event(), unresolved(), earnings_pages(), edited(), IdentityTests, ReceiptProvenanceTests

### Community 61 - "Watchdog Schedule Eligibility"
Cohesion: 0.14
Nodes (10): CalendarEdgeTests, CronContractTests, DailyEligibilityTests, MechanicalEligibilityTests, session(), utc(), eligibility(), eligible() (+2 more)

### Community 62 - "Radar Research Tests"
Cohesion: 0.10
Nodes (8): gather(), run(), rescue_after_fetch(), gather(), _dated_pair(), _research_none_result(), _research_run(), structured_scout()

### Community 63 - "Opportunity Cutover Tests"
Cohesion: 0.12
Nodes (3): CutoverTests, checked_append(), competing_activation()

### Community 64 - "Memory Radar Tests"
Cohesion: 0.10
Nodes (5): MemoryRadarTests, failed(), hold(), fetch(), writer()

### Community 65 - "Entry Authority Validation"
Cohesion: 0.15
Nodes (20): _approval(), AttemptProof, AuthorityError, authorize_attempt(), bind_candidate(), _BoundCandidate, _candidate(), _hash() (+12 more)

### Community 68 - "Broker MCP Bridge"
Cohesion: 0.16
Nodes (21): Alpaca, alpaca_mcp_config(), complete_open_orders(), earnings_state(), finite_number(), first_dict(), listish(), main() (+13 more)

### Community 69 - "Thesis Monitoring Tests"
Cohesion: 0.15
Nodes (3): MonitorTests, run(), run()

### Community 70 - "Extraction Provider Compatibility"
Cohesion: 0.15
Nodes (18): _available(), _call(), check_url(), CompatibilityError, _config(), _enabled(), _function(), _module() (+10 more)

### Community 71 - "Opportunity State Validation"
Cohesion: 0.10
Nodes (16): _snapshot_dossier_hashes(), _validated_clearance_record(), _validated_identity_record(), _validated_missing_history_record(), _candidate_links(), _checked_source_row(), extract_row_symbol(), _gap_entry() (+8 more)

### Community 73 - "Mechanical Exposure Tests"
Cohesion: 0.21
Nodes (7): base_fixture(), MechanicalTests, observe(), stop_leg(), target_leg(), aggregate_exposure(), observe_positions()

### Community 74 - "Broker Normalization Tests"
Cohesion: 0.09
Nodes (13): average_volume(), completed_session_average_volume(), daily_bars_request(), latest_quote_request(), massive_daily_bars(), symbol_bars(), symbol_mapping(), tool_arguments() (+5 more)

### Community 75 - "Publication Recovery Selection"
Cohesion: 0.13
Nodes (17): body_repair_needed(), _attach(), candidate_recovery_page(), choose_recovery_pages(), _known_instant(), _policy(), preserve_cached_refusal(), recover_publications() (+9 more)

### Community 76 - "Focused Search Tests"
Cohesion: 0.12
Nodes (9): BoundaryTests, prepare(), run(), manifest(), ManifestTests, module(), QueryContractTests, ReceiptTests (+1 more)

### Community 77 - "Entry Fill Reconciliation"
Cohesion: 0.11
Nodes (12): _reconcile_pending_orders_locked(), broker_order_notification_line(), EntryFillConflict, exact_terminal_readback(), _execution_time(), _journal_confirmed_fill_locked(), _notification_plan(), placing_notification_line() (+4 more)

### Community 78 - "Broker Order Collection"
Cohesion: 0.14
Nodes (23): gather(), gather(), delayed_fetch(), fetch_late(), collect_broker(), pages(), read(), request() (+15 more)

### Community 79 - "Batch Supervisor Tests"
Cohesion: 0.10
Nodes (6): assert_dead(), blocked_probe(), BatchSupervisorTests, launch(), adopt(), process()

### Community 80 - "Dashboard Publish Tests"
Cohesion: 0.11
Nodes (8): EntryTests, run(), load(), NativeTests, connect(), PayloadTests, PublishTests, call()

### Community 81 - "Batch Worker Tests"
Cohesion: 0.15
Nodes (10): BatchWorkerTests, check(), primary(), rescue(), extract(), extract(), dispatch(), dispatch() (+2 more)

### Community 82 - "Thesis Provider Adapters"
Cohesion: 0.11
Nodes (9): ConfigTests, ProviderGatewayTests, classify(), provider_payload(), serve(), strict_json(), live_adapters(), ProviderSession (+1 more)

### Community 83 - "Identity Evidence Acquisition"
Cohesion: 0.16
Nodes (16): _directory(), publish_lead(), _read_file(), read_lead(), _validate(), capture_identity_source(), _constant(), _decode() (+8 more)

### Community 84 - "Broker Process Supervision"
Cohesion: 0.13
Nodes (15): _group_run(), cleanup(), freeze_kill_tree(), visit(), guardian_main(), identity(), main(), reap_owned() (+7 more)

### Community 85 - "Focused URL Allocation"
Cohesion: 0.13
Nodes (14): allocate_urls(), Allocation, _syntax_valid(), _check(), extract_allocated(), FocusedFailure, FocusedResult, run_focused_pipeline() (+6 more)

### Community 86 - "Publication Observation Tests"
Cohesion: 0.20
Nodes (5): evaluate_publication(), observe(), page_for(), PublicationObservationTests, article_page()

### Community 87 - "Enrichment Diagnostics Tests"
Cohesion: 0.08
Nodes (6): EnrichmentDiagnosticsTests, loader(), reason(), config(), __init__(), failure()

### Community 88 - "Structured Batch Supervision"
Cohesion: 0.14
Nodes (15): batch_error(), extract_batch(), main(), bounded(), valid_batch_request(), validate_batch_urls(), extraction_extensions(), publication_record() (+7 more)

### Community 89 - "Opportunity Retention Tests"
Cohesion: 0.09
Nodes (6): gap_review_row(), gap_trade_row(), make_gap_root(), make_root(), RetentionTests, fail()

### Community 90 - "Opportunity Workflow Scenarios"
Cohesion: 0.14
Nodes (3): OpportunityWorkflowScenario, discovery(), scout()

### Community 91 - "Acquisition Research Tests"
Cohesion: 0.23
Nodes (3): AcquisitionResearchTests, opened(), bundle()

### Community 92 - "Deferred Rescue Tests"
Cohesion: 0.14
Nodes (5): BundleRescueTests, rescue(), synth(), _deferred_scout(), _event_pages()

### Community 93 - "Research Extraction Dispatch"
Cohesion: 0.16
Nodes (16): extract(), _bind(), _bounded(), _compat_reason(), _envelope(), _error(), extract_owned_tool(), extract_tool() (+8 more)

### Community 94 - "Layered Test Runner"
Cohesion: 0.16
Nodes (12): build_suite(), changed_operational_paths(), discover_modules(), _file_state(), load_manifest(), main(), modules_for_tier(), parse_args() (+4 more)

### Community 96 - "Daily Watchdog Tests"
Cohesion: 0.16
Nodes (6): build_operational_root(), DailySeamTests, slow_broker(), DailyWorkflowTests, broken_install(), slow_broker()

### Community 97 - "Thesis Classification Tests"
Cohesion: 0.23
Nodes (10): thesis(), baseline(), ClassificationTests, model(), model(), model_output(), run(), model() (+2 more)

### Community 98 - "Opportunity Identity Binding"
Cohesion: 0.14
Nodes (11): _document(), _binding_agreement(), _capture_ref(), _document(), DocumentObservation, _load_binding(), _merged_binding(), observation_provenance() (+3 more)

### Community 99 - "Runtime Support Fixtures"
Cohesion: 0.14
Nodes (5): broker_snapshot(), policy_config(), technical_bars(), Clock, SkipEventAuditTests

### Community 100 - "Research Memory Transition"
Cohesion: 0.29
Nodes (15): _active(), apply(), _legacy(), main(), manifest_digest(), _predecessor(), _prefix(), prepare_manifest() (+7 more)

### Community 102 - "Watchdog Source Discovery"
Cohesion: 0.14
Nodes (14): ConcreteSourceTests, discover(), inspect(), earnings_coverage(), fetch(), gap(), main(), public_url() (+6 more)

### Community 103 - "Entry Buy Eligibility"
Cohesion: 0.16
Nodes (11): _aware_utc(), entry_observation(), EntryDecision, EntryStateError, evaluate_buy(), _evidence(), _finite_positive(), row_digest() (+3 more)

### Community 104 - "Ledger Policy Index"
Cohesion: 0.13
Nodes (10): _validation_index(), _baseline_exclusions(), _build(), HistoricalDossierHashMissing, _index_from_parts(), load_index(), load_policy_context(), local_entry_exclusions() (+2 more)

### Community 105 - "Identity Acquisition Tests"
Cohesion: 0.17
Nodes (4): opened(), IdentityAcquisitionTests, opened(), opened()

### Community 106 - "Retrieval Concurrency Tests"
Cohesion: 0.10
Nodes (4): RetrievalImprovements, verify(), blocked(), slow()

### Community 108 - "Bridge Reuse Contracts"
Cohesion: 0.13
Nodes (7): error_envelope(), BridgeCommandTests, BridgeFailureDiagnosticsTests, BridgeRetryTests, _fail_process(), _ok_process(), SnapshotErrorContractTests

### Community 109 - "Reopening Claim Observations"
Cohesion: 0.15
Nodes (13): _lineage(), observe_completed_close(), record_observation_evidence(), _restore_observation(), serialize_reopening_claim(), claim_digest(), claim_sealed(), ConditionObservation (+5 more)

### Community 110 - "Radar Evidence Rescue"
Cohesion: 0.12
Nodes (4): fetch(), fetch(), _body(), rescue_url()

### Community 111 - "Extraction Boundary Tests"
Cohesion: 0.15
Nodes (3): ProbeTests, broken(), worker()

### Community 113 - "Rescue Fairness Tests"
Cohesion: 0.17
Nodes (7): replay(), gateway(), gather(), run(), sec(), spend(), RescueFairnessTests

### Community 114 - "Offline Test Guards"
Cohesion: 0.15
Nodes (7): _audit(), expected_local_control(), _finish(), install(), successful(), summary(), _unexpected()

### Community 115 - "Activation Dossier Versions"
Cohesion: 0.13
Nodes (8): _authorize_current_attempt(), dossier_already_reviewed(), entry_policy_version(), pre_submission_retryable(), activation_version(), ActivationStateError, require_supported_activation(), dossier_status()

### Community 116 - "Scout Freshness Tests"
Cohesion: 0.11
Nodes (5): raw(), _bad_response(), _empty_response(), _RawResponse, RetrievalHardeningTests

### Community 119 - "Gateway Fallback Tests"
Cohesion: 0.14
Nodes (3): GatewayFallbackGuardTests, direct(), fallback()

### Community 120 - "Noop Cycle Tests"
Cohesion: 0.25
Nodes (6): _candidate(), NoOpCycleSkipTests, _proposal(), _review_ts(), ReviewBundleStripTests, _snapshot_with_bars()

### Community 121 - "Extraction Capacity Probe"
Cohesion: 0.22
Nodes (13): failed_urls(), main(), observe(), route(), save(), summarize(), wrapped_keyless(), wrapped_primary() (+5 more)

### Community 124 - "Benchmark Comparison Reports"
Cohesion: 0.17
Nodes (5): BenchmarkTests, compare_benchmark(), _day(), _series(), _total_return_series()

### Community 125 - "Research Budget Guards"
Cohesion: 0.15
Nodes (4): search_done(), ResearchBudgetGuardTests, focused(), gather()

### Community 126 - "Real Transport Tests"
Cohesion: 0.18
Nodes (3): RealTransportTests, vendor(), extract()

### Community 127 - "Opportunity Cutover Activation"
Cohesion: 0.35
Nodes (11): activate_prospective(), active_baseline(), baseline_for_snapshot(), CutoverError, main(), _manifest(), manifest_digest(), _prefix_digest() (+3 more)

### Community 128 - "Publication Date Candidates"
Cohesion: 0.14
Nodes (5): _attr_value(), date_candidate_text(), _ld_article_dates(), _publish_meta(), _RetainedHTML

### Community 129 - "Market Data Tests"
Cohesion: 0.17
Nodes (4): _daily_payload(), _grouped_payload(), MarketDataTests, _PayloadResponse

### Community 133 - "Forward Lineage Tests"
Cohesion: 0.18
Nodes (3): ForwardLineageTests, broker(), broker()

### Community 134 - "Operational Entry State"
Cohesion: 0.20
Nodes (6): _canonical(), _copied_database(), _loads(), _metadata(), _read_operational(), _unique_object()

### Community 135 - "Earnings Resolution Tests"
Cohesion: 0.36
Nodes (3): EarningsResolutionTests, original(), retained()

### Community 137 - "Activation Ordering Tests"
Cohesion: 0.29
Nodes (3): ActivationOrderingTests, reviewer(), reviews()

### Community 139 - "Fetch Fairness Tests"
Cohesion: 0.18
Nodes (6): tool_driver(), geturl(), page(), date(), fetch(), lookup()

### Community 140 - "Evidence Capture Store"
Cohesion: 0.31
Nodes (10): _directory(), _read(), read_capture(), read_result(), _retain(), retain_page(), retain_result(), _existing_capture() (+2 more)

### Community 141 - "Project Extraction Probe"
Cohesion: 0.26
Nodes (8): child(), observe(), profile(), main(), run_probe(), transport_start(), validate_cohort(), write_private()

### Community 142 - "SEC Rescue Tests"
Cohesion: 0.19
Nodes (5): fake_urlopen(), fake_urlopen(), fake_urlopen(), fake_urlopen(), _json_response()

### Community 143 - "Broker Security Tests"
Cohesion: 0.31
Nodes (3): BrokerSecurityEnvelopeTests, _FixtureSession, _security_envelope()

### Community 146 - "Research Budget Context"
Cohesion: 0.21
Nodes (3): diagnostic_remaining(), extraction_miss(), validation_done()

### Community 148 - "Probe Child Diagnostics"
Cohesion: 0.23
Nodes (7): child_diagnostics(), event(), measured_envelope(), measured_size(), save(), write(), child_sinks()

### Community 149 - "Acquisition Observation Tests"
Cohesion: 0.18
Nodes (4): gather(), rescued(), synth(), recovered()

### Community 152 - "Probe Safety Guards"
Cohesion: 0.27
Nodes (8): observed(), install_safety(), allowed(), audit(), guard_fd_write(), call(), guarded_open(), target()

### Community 153 - "Shadow Calibration Reports"
Cohesion: 0.36
Nodes (6): _broker_outcomes(), calibration_report(), main(), measure_outcomes(), record_decision(), refresh()

### Community 154 - "Offline Network Boundaries"
Cohesion: 0.25
Nodes (4): install(), guard(), local(), OfflineBoundaryTests

### Community 159 - "Focused Capture Containers"
Cohesion: 0.22
Nodes (4): focused_retrieval(), focused_retrieval_command(), CapturedResult, FocusedURLs

### Community 164 - "Compat Extraction Invocation"
Cohesion: 0.42
Nodes (8): _invoke(), run(), call(), keyless(), primary(), _remaining(), _rows(), _safe_urls()

### Community 165 - "Focused Capture Wrappers"
Cohesion: 0.25
Nodes (5): Recorder, captured(), dispatch(), main(), handler()

### Community 166 - "Publication Interpreter"
Cohesion: 0.25
Nodes (5): interpret_publications(), diagnostics(), fail(), _prepare_request(), _valid_page()

### Community 167 - "Provider Publication Tests"
Cohesion: 0.25
Nodes (3): provider_publication(), invoke(), invoke()

### Community 169 - "Protective Exit Tests"
Cohesion: 0.22
Nodes (3): _protective_exit_parent(), worker(), broker()

### Community 170 - "Configured Broker Reader"
Cohesion: 0.28
Nodes (3): ConfiguredBrokerTests, collect_configured(), main()

### Community 178 - "Watchdog Mechanical Exits"
Cohesion: 0.36
Nodes (5): _flatten_orders(), _horizon_status(), _leg_kind(), _protection_status(), _unexpected_exits()

### Community 195 - "JSONL NUL Repair"
Cohesion: 0.60
Nodes (3): _constant(), _object(), recover()

### Community 196 - "Missing History Fixtures"
Cohesion: 0.40
Nodes (3): missing_history_clearance_row(), missing_history_row(), policy_row()

### Community 197 - "Synthetic Resolution Fixtures"
Cohesion: 0.40
Nodes (3): synthetic_capture_ref(), synthetic_resolution(), synthetic_resolution_payload()

### Community 206 - "Candidate Outcome Measurement"
Cohesion: 0.67
Nodes (3): append(), main(), measure()

## Knowledge Gaps
- **88 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TradeySafetyTests` connect `Trading Safety Tests` to `Shared Test Imports`, `Daily Order Deduplication`, `Broker Calendar Tests`, `Broker Bridge Tests`, `Snapshot Failure Tests`, `Protective Exit Tests`, `Reviewer Diagnostics Tests`, `Runtime Credential Mechanics`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Why does `BrokerMcpConfigTests` connect `Broker MCP Tests` to `Extraction Parsing Utilities`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **Why does `AlphaRadarTests` connect `Radar Intake Tests` to `Shared Test Imports`, `Radar Rescue Fallbacks`, `Article Extraction Tests`, `Radar Evidence Rescue`, `Scout Freshness Tests`, `Radar Research Tests`?**
  _High betweenness centrality (0.025) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `OpportunityStateTests` (e.g. with `EventResolution` and `ConditionObservation`) actually correct?**
  _`OpportunityStateTests` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Should `Shared Test Imports` be split into smaller, more focused modules?**
  _Cohesion score 0.05827886710239651 - nodes in this community are weakly interconnected._
- **Should `Autotrader Order Proposals` be split into smaller, more focused modules?**
  _Cohesion score 0.037770669291338585 - nodes in this community are weakly interconnected._
- **Should `Extraction Parsing Utilities` be split into smaller, more focused modules?**
  _Cohesion score 0.0364977674238012 - nodes in this community are weakly interconnected._