# Discovery Quality First Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve reliable production of qualified, evidence-backed dossiers for the unchanged autotrader; do not optimize candidate counts or bypass legitimate HOLD/policy decisions.

**Architecture:** Deliver discovery-first: a supervised code-owned six-lane collector feeds one tool-free selector, a deterministic legacy-contract handoff, and bounded private cross-run history. Keep extraction, publication recovery, synthesis and qualification intact for this increment. Evaluate the whole funnel before claiming operational improvement; the approved LLM extraction-fallback direction remains a separately planned follow-up with an original-capture witness contract.

**Tech Stack:** Existing Python stdlib, installed Hermes runtime/search dispatcher, current configured providers, existing supervisor/test infrastructure. No dependency installation.

**Spec:** `docs/superpowers/specs/2026-10-22-discovery-quality-first-design.md` (updated user-goal clarification included).

## Global Constraints

- Work only in `.worktrees/discovery-quality-first`, branch `design/discovery-quality-first`; production main remains authoritative and untouched. One implementation writer.
- Six lanes, limit10 each; maximum five candidates/five URLs total/500 characters per catalyst; seven-calendar-day event gate unchanged.
- Discovery165 seconds maximum, including collection, selector startup/I/O, admission and persistence. Proposed internal allocation: collection at most60 seconds, then selector/admission use only the remaining original deadline; no fixed new selector window or clock reset. Clamp to the overall research/downstream reserve before launch.
- Research active690s/outer720s; execution freshness600s; evidence180s; publication recovery90s; minimum synthesis30s/enrichment45s/transition5s preserved. Deterministic10/model10/combined20 recovery ceiling preserved.
- Providers/routing/keys, source-age180 days, body/URL safety, two accepted publisher domains, all earnings/horizon/liquidity/pricing/risk/review/execution gates unchanged.
- No Hermes/core/configuration/gateway modifications/restarts; no broker/trading/research-network calls during implementation or offline tests. Network/model evaluation has a separate gate below.
- Private artifacts0700 directories/0600 files; raw queries/results/excerpts/history never enter public dashboard or operational dossiers as trusted fields.
- Discovery is provisional. Exact quotation does not prove event semantics, publication date, source ownership or investment eligibility. Model labels cannot become verified truth.
- Implement opt-in only: `cfg.get('discovery_v2_enabled', False)` remains false in production configuration. A default-disabled complete implementation plus a runnable isolated evaluator is the deliverable, not an empty stub.

## Review Focus

1. A lane hangs or returns a malformed/error envelope: partial coverage must remain visible; no healthy empty-scan classification.
2. Untrusted result IDs/URLs/excerpts, event-state claims or prompt injection: no invented binding or model-authorized evidence.
3. History conflates ticker/date with event identity: annotate repeats without permanent exclusion or changed dossier-spending policy.
4. Startup/serialization/deadline overhead and escaped descendants: the same absolute deadline must bound collection and selection.
5. Better provisional selection still yields zero accepted bundles: report downstream failure and withhold an end-to-end improvement claim.

---

## Preparation: isolated baseline and frozen evidence

- [ ] Verify workdir/branch/HEAD and source hashes. Provision only byte-identical immutable corpus, prior incident and native-MCP replay fixtures used by the current1532-test baseline. No operational DBs, credentials or source cache copies.
- [ ] Install tracked default-on offline launch guard before test imports; reuse existing no-install `tpy.sh` and correct `TRADEY_UNPATCHED_ROOT`. Retain original failures and distinguish fixture/environment corrections from code changes.
- [ ] Run guarded baseline full/raw once, expecting1532 each and zero skips/failures/errors. Stop on unexplained failure.
- [ ] Freeze private historical inventory and audited calls/records/outcomes from production `test_artifacts/six-lane-historical-audit-20261022T005728Z/`; verify37 sessions,225 calls,2250 records,34 production/three diagnostic IDs. Preserve their original role/date uncertainty and cohort boundaries.

### Task1: Six-lane collector and supervised worker

**Files:** create `discovery_collection.py`, `discovery_worker.py`, `discovery_process.py`; create `tests/test_discovery_collection.py`, `tests/test_discovery_process.py`; classify tests in `tests/test_manifest.json`.

**Interfaces:** `make_queries(cfg: dict, *, now: datetime) -> list[dict]` produces six versioned `{lane, query, limit:10}` requests using the existing sector rotation. `collect_lanes(requests: list[dict], *, deadline: float, search: Callable) -> dict` returns strict version1 `{lanes:[{lane,status,reason,records,receipt}],coverage_complete:bool}`. `run_collection(requests: list[dict], *, deadline: float, cwd: Path) -> dict` owns worker lifecycle and deadline.

- [ ] Write RED tests `test_exact_six_lanes_and_rotation`, `test_partial_lane_is_not_empty_success`, `test_untrusted_envelope_rejected`, `test_no_network_after_deadline`, `test_blocked_stdin_and_child_cleanup`: assert six calls/limit10, typed failures, no fabricated metadata, no launch after preparation exhausts deadline, no surviving supervised descendants.
- [ ] Run the two targeted unittest modules with guard installed; retain intended RED.
- [ ] Implement lane templates using the same as-of day/window. Target SEC hosts, diversify reporting, distinguish issuer-origin syndication, and identify legal-solicitation results. Treat domain/date query operators as hints, never proof. Do not add unsupported search arguments or exclusion allowlists.
- [ ] Implement a no-agent installed-runtime worker calling configured `tools.web_tools.web_search_tool(query, limit=10)` after normal web-plugin bootstrap; do not discover MCP/broker tools. Use at most six concurrent lane calls; worker lifetime bounds any blocked provider threads. Reuse existing supervisor/cleanup primitives, not a new process-group-only containment claim.
- [ ] Strict JSON/request-response bounds: request32KiB, provider response256KiB per lane, aggregate response2MiB, stderr16KiB. Validate encoded bytes before spawn, multiplex stdin/stdout under one deadline, classify overflow explicitly. Retain original bounded records privately; cap admission at ten per lane. No output truncation silently becoming success.
- [ ] Run targeted tests GREEN and `git diff --check`; commit only code/tests/manifest.

### Task2: Tool-free selector, source binding and continuity

**Files:** create `discovery_selection.py`, `discovery_history.py`; create `tests/test_discovery_selection.py`, `tests/test_discovery_history.py`.

**Interfaces:** `selector_prompt(collection: dict, history: dict, *, now: datetime) -> str`; `admit_selection(text: str, collection: dict, *, now: datetime) -> tuple[list[dict],dict]`; `read_history(path: Path, *, now: datetime) -> dict`; `record_history(path: Path, entry: dict, *, now: datetime) -> None`.

- [ ] RED tests `test_fresh_release_with_old_quarter_end`, `test_future_deadline_is_not_fresh_announcement`, `test_result_id_url_excerpt_binding`, `test_index_and_overlength_are_typed_rejections`, `test_event_state_never_authoritative`, `test_history_does_not_blacklist_ticker`, `test_history_retention_and_permissions`.
- [ ] Run targeted RED. Implement one strict tool-free response `{candidates:[{result_id,symbol,event_date,catalyst,support,event_status}],exclusions:[{result_id,reason}]}`. Resolve URLs from retained IDs in code. Return the existing legacy candidate shape and private per-row outcomes; do not add trusted fields to dossiers.
- [ ] Every collected result must have a selected/duplicate/excluded/unknown-or-unaccounted audit disposition. Missing explanation is unknown, not invented. Incomplete provider coverage and malformed selector output remain distinct from normal empty discovery.
- [ ] Validate support against the retained record, keep event status provisional, and score known semantic errors with frozen labels. Do not claim substring checking adjudicates all event states. No broad lexical rule rejects every result mentioning an older date.
- [ ] Maintain a private history index capped at1000 groups/entries and seven calendar days, atomic replacement under a bounded lock. Exact URLs bind source identity; uncertain company-event grouping remains uncertain. Do not suppress tickers or change qualified-dossier reuse. Retention pruning cannot erase raw evaluation artifacts.
- [ ] Fit all result IDs into a selector projection capped64KiB encoded; bound per-record visible title/excerpt and mark clipping/context-limit explicitly. Preserve originals for binding and evaluation. Do not manufacture omitted result content.
- [ ] Run targeted tests GREEN, register manifest entries and commit.

### Task3: Integrate opt-in discovery and the unchanged research funnel

**Files:** create `discovery_pipeline.py`; modify only discovery dispatch in `alpha_radar.live_research`; create `tests/test_discovery_pipeline.py`; update existing discovery tests only where the opt-in contract requires it.

**Interfaces:** `discover(cfg: dict, *, now: datetime, deadline: float, history_path: Path, artifact_dir: Path, command_factory: Callable, selector_runner: Callable) -> tuple[list[dict],dict]` composes Tasks1–2. Production uses existing model/provider identity resolution, tool-free process supervision and typed public error allowlist; private reasons retain the precise component failure.

- [ ] RED tests `test_legacy_default_unchanged`, `test_one_tool_free_selector_no_search_turns`, `test_shared_deadline_includes_preparation`, `test_partial_collection_explicit`, `test_no_silent_candidate_losses`, `test_two_publishers_reach_real_intake`, `test_policy_rejection_not_system_failure`, `test_missing_publisher_never_qualified`.
- [ ] Run RED. Implement opt-in dispatch without restructuring focused retrieval, recovery, synthesis, enrichment or qualification. Leave production configuration false; normal legacy prompt/parser behavior remains unchanged unless explicitly opted in.
- [ ] Run one selector attempt only, using existing provider/model fallback inside the same deadline. No new output-repair retry, supplemental searches or added publication-model batch. Capture phase failure separately from a normal empty list.
- [ ] Integration fixtures must exercise actual downstream source receipt validation and `prepare_candidate`, with network/model outputs mocked and state isolated before imports. A valid fixture must reach a final qualified dossier artifact; failed source, earnings or intake fixtures must remain blocked. A callback returning its input is not sufficient proof.
- [ ] Ensure new diagnostics are private and best-effort except the existing mandatory research-persistence contract; output/error tokens remain compatible with scheduler parsing. Commit GREEN stable bytes.

### Task4: Reproducible offline comparison and results review

**Files:** create `scripts/evaluate_discovery_quality.py`, `tests/test_discovery_evaluation.py`; create `docs/discovery-quality-evaluation.md`.

**Interfaces:** CLI `--inventory PATH --results PATH --labels PATH --out PRIVATE_DIR` performs historical deterministic replay with no network; `--integration-fixtures PATH` additionally exercises isolated whole-funnel fixtures. Missing hashes/fixtures fail, never silently skip. No default live mode.

- [ ] RED tests assert exact37-session/225-call/2250-record inventory parity, production/diagnostic separation, explicit unknown labels, no operational path access, and correct counts for raw/admitted/focused/accepted-domain/synthesis/qualified/HOLD-policy/error outcomes.
- [ ] Implement frozen-label evaluation covering all nine overlength rows, all known index bindings, acceptance/approval and planned/completed cases, IART/TMO snippet limitations, repeat/new-disclosure distinctions and date ambiguity. Preserve originals/first outputs; no label retuning to obtain a target count.
- [ ] Compute matched before/after handoff losses from the same saved records; mocked-selector fixtures prove contracts only. Label new-query coverage, real-selector accuracy and natural scheduled qualification as UNEXERCISED. Historical results cannot prove counterfactual search coverage.
- [ ] Run actual evaluator and save machine summary plus concise results: final-qualified fixtures, policy rejections, unresolved downstream blockers, latency, source/semantic error counts, and sample/retention limits. Do not call a higher provisional-lead count operational improvement.
- [ ] Run guarded final focused/full/raw once on final bytes, zero skips/errors/failures; verify source and operational isolation. Independent whole-branch review then report results to user. No push/merge/rollout automatically follows this implementation/results-review request.

## Next gates: live evaluation and follow-up extraction

- Live comparison is NOT performed during the above offline implementation. Proposed cap for separate approval: two discovery-only matched probes in one eligible market window; each at most165s, two six-query sets at limit10 (old/new), two tool-free selector attempts over retained receipts, no retries or extra probes. Stop after two probes or any isolation/credential/safety failure. Record both provider costs and whole-funnel unexercised status. This is an explicit proposed allowance, not a hidden doubling of scheduled work.
- Any full research shadow also needs a separately reviewed allowance and strict isolated storage/read/write guards before launch. It must use the unchanged qualification path and produce research artifacts only, with no operational candidate append or execution. Paper orders are not a required proof of research recovery.
- Section3F's LLM extraction/publication fallback is not dropped: prepare a separate witness-contract design/implementation plan after examining the isolated funnel results, or earlier if the results confirm it is the blocking path. It must permit grounded unfamiliar layouts without the old parser circularity, preserve original refusals/conflicts/precision and fit the same recovery90s/one-shot/page ceilings. Do not improvise that validator inside this discovery patch.

## Self-review and execution handoff

Spec sections3A–E map to Tasks1–3; section5 to Task4; section3F is explicitly a follow-up, not an omitted implementation claim. All five Review Focus conditions have named tests. Exact request/response/model/history boundaries are defined above; the feature remains disabled outside explicit isolated evaluation.

Recommended execution: **Native**, one implementation owner in this session, targeted TDD per task and one independent final reviewer. It avoids repeated context/setup overhead across these closely coupled interfaces. User review of this plan and execution approach is the remaining prerequisite before product code.
