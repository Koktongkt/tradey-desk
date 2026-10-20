# Coverage-first Focused Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every shortlisted candidate coverage-first focused extraction opportunities, using discovery seeds and attested search alternatives, capped at 25 unique URLs and five bindings per candidate.

**Architecture:** One search-only model child returns symbol-bound alternatives attested by private search-tool receipts. The parent allocates in candidate rounds and extracts through isolated project workers, keeping real pages separate from model output. All stages share the original focused deadline and hand accepted pages into existing evidence validation without duplicate fetching.

**Tech Stack:** Python stdlib, unittest, the installed Hermes CLI/bootstrap and search registry, existing project extraction dispatcher/supervisors and private diagnostics.

**Spec:** `docs/superpowers/specs/2026-10-20-focused-coverage-25-design.md` (user approved for implementation planning).

## Global Constraints

- Retain up to five candidates; at most 25 unique focused extraction URLs and five selected URL bindings per candidate.
- User-approved 2026-10-20 amendment: at most 25 focused singleton extraction calls, one per selected unique URL, no duplicates/retries or hidden second allowance. At most three active extraction supervisors globally, each owning one provider request; logical allocation remains at most five groups of five. The general multi-URL worker protocol remains compatible. Raw 100,000-byte admission is per complete singleton response before binding/projection; projected worker envelopes stay bounded. All original deadline/reserve, search-attestation, qualification, SSRF/provenance and supervision gates remain unchanged.
- Keep the three existing primary/independent/wire focused-search objectives. Do not alter discovery's six deployed search lanes.
- Focused wall-clock cap: 150 seconds. Overall active research cap: 570 seconds. Preserve the existing downstream reservation, model turn ceilings and model effort ceiling.
- Keep 2,000–6,000 characters per page, effective focused extraction request 6,000; preserve 100,000-byte per-call response and 16,384-byte stderr limits.
- Two accepted fresh distinct-publisher sources remain mandatory; unknown publishers remain eligible. Preserve exact requested/returned identity and publication/body/freshness checks.
- Preserve four-source/18,000-character synthesis bundles, bounded synthesis attempts, three-candidate later rescue and eight-URL post-rescue binding capacity.
- No broker calls in feature development/probes; paper-only, position/order limits, consensus and all execution controls unchanged.
- Work in an isolated worktree; pause affected live writers only at live cutover. No shared Hermes platform patch, new MCP, provider change or dependency installation without the applicable separate approval.
- TDD and independent adversarial review are mandatory. Full/raw suites must be green before committing feature changes; no claims of improvement from allocation counts alone.

## Review Focus

- Search result URLs may appear inside snippet prose without being actual result keys: accept only exact top-level result URL keys (Task 2).
- One URL may be explicitly associated with multiple symbols: request once without silently assigning unrelated company evidence (Tasks 1 and 5).
- Slow search or extraction may leave selected URLs never submitted: preserve absolute deadlines and distinguish selection from submission (Tasks 3 and 4).
- Multi-byte URLs and escaped JSON may exhaust byte caps before count caps: reject intact identities rather than truncating or dropping accounting (Tasks 2 and 3).
- Later health merge or rescue may silently discard URLs 16–25 or re-fetch accepted pages: pin the actual production handoff, not only allocator output (Task 5).

---

## File responsibilities and sequence

Create `focused_allocation.py` for pure bounded pools, round allocation and batch packing; `focused_search.py` for manifest and search receipt validation; `focused_search_wrapper.py` for child-local search registration/capture; `focused_pipeline.py` for deadline-bound extraction scheduling and coordination. Extend `focused_capture.py` only to share private child supervision without changing legacy `run_focused` behavior. Extend `structured_extraction.py` and `extraction_worker.py` with a separate version-2 batch protocol while preserving version-1 exact-URL fallback. Integrate through narrow edits in `alpha_radar.py`; do not grow it with another whole subsystem.

Tests: new `test_focused_allocation`, `test_focused_search`, `test_focused_batch`, `test_focused_pipeline`; register each exactly once in `tests/test_manifest.json`. Extend existing radar/budget/reuse/rescue tests at their real caller boundaries. Update `docs/focused-extraction-reuse.md` and `docs/structured-extraction.md` with the shipped ownership/caps, not with anticipated success.

### Task 0: Establish a trustworthy unchanged baseline

**Files:** Read `runtime_paths.py`, `tests/run_tests.py`, `tests/subprocess_probe_helpers.py` if present, the process-lifetime helpers actually imported by `tests/test_structured_extraction.py` and `tests/test_focused_reuse.py`. No feature code edits.

**Interfaces:** Produces a verified test invocation and unchanged-baseline full/raw results in ignored `test_artifacts/focused-coverage-25/`. Subsequent commands use the shell function `tpy` below.

- [ ] Load using-git-worktrees and the selected execution skill. Create an isolated feature worktree from the recorded base; carry only the approved spec and this plan into it. Record base SHA, active tree paths and exact recovery scope. Do not copy private operational journals or secrets.
- [ ] Verify the installed runtime/source via `runtime_paths.hermes_runtime()` and its bootstrap; verify `/usr/bin/python3` has `os.pidfd_open` and `signal.pidfd_send_signal`. Inspect dependency-committed environment resolution before choosing an interpreter; never confuse bare launcher Python with bootstrapped dependencies.
- [ ] Start with the skill's documented wrapper, with the selected Hermes source on `PYTHONPATH` and the supported worker interpreter explicitly selected:

```sh
export HERMES_SOURCE_ROOT="$(python -c 'from runtime_paths import hermes_runtime; print(hermes_runtime()[1])')"
export HERMES_PYTHON=/usr/bin/python3
export PYTHONPATH="$HERMES_SOURCE_ROOT${PYTHONPATH:+:$PYTHONPATH}"
tpy() { uv run --python /usr/bin/python3 --with 'fastmcp<4' python "$@"; }
tpy -c "import os,signal,requests,httpx; assert hasattr(os,'pidfd_open') and hasattr(signal,'pidfd_send_signal')"
tpy tests/run_tests.py full
tpy -m unittest discover -s tests -p 'test_*.py' -q
```

The wrapper is a baseline candidate, not a claim that it already passes on this host. If imports fail, reproduce installed bootstrap/dependency paths without installing ad hoc packages. Record the final exact successful invocation and redefine `tpy` consistently for full/raw and every task.
- [ ] Reproduce the prior three process-lifetime errors. First test runtime/startup and `/proc` disappearance races; do not weaken kill/reap assertions or extend production deadlines. A necessary test-harness correction requires its own focused regression, review and separated diff. Stop feature execution if the baseline cannot be made green within authorized project scope.
- [ ] Verify equal full/raw counts and clean operational isolation. Only after a green baseline, commit the reviewed spec/plan as docs, then proceed. The earlier 1,212-test result with three errors is not acceptance evidence.

### Task 1: Pure deterministic allocation

**Files:** Create `focused_allocation.py`, `tests/test_focused_allocation.py`; modify `tests/test_manifest.json` (fast).

**Interfaces:**
- `Allocation` frozen dataclass: `by_symbol: dict[str,list[str]]`, `unique_urls: list[str]`, `batches: list[list[str]]`, `available_counts: dict[str,int]`, `uncovered: dict[str,str]`.
- `allocate_urls(candidates: list[dict], alternatives: dict[str,list[str]], *, eligible_urls: set[str], unhealthy_domains: set[str]) -> Allocation`.
- Consumes only syntax-valid seeds and attested alternatives; `eligible_urls` is the prevalidated safe subset produced by Task 4. No network calls inside this module.

- [ ] Write `test_five_candidates_receive_five_in_round_order`: five ordered seed-plus-alternative pools yield `list(map(len, result.by_symbol.values())) == [5]*5`, `len(result.unique_urls) == 25`, batch lengths `[5]*5`, and the first batch equals the five exact seeds in candidate order.
- [ ] Write `test_starved_fourth_candidate_gets_seed_before_extras`: a 1/3/3/0 alternative fixture with four seeds gives the fourth candidate its seed in batch one. Assert no URL repeats, scarce pools underfill, and one candidate cannot exceed five even when another has no alternatives.
- [ ] Add `test_shared_url_preserves_only_explicit_bindings`, `test_publisher_diversity_then_health_then_provenance`, and `test_unhealthy_seed_keeps_first_slot`: check stable ordering, same-publisher fallback eligibility, unknown publishers and unsafe seeds producing `no_eligible_url`.
- [ ] Observe RED: `tpy -m unittest discover -s tests -p test_focused_allocation.py -v`.
- [ ] Implement the dataclass and allocator with five candidate rounds, stable exact-key deduplication and sequential chunks of five unique URLs. Use existing publisher/source-profile helpers without triggering provider/model config lookup.
- [ ] Run the focused tests and full tier; require green isolation before committing only the allocator, its tests and manifest entry: `feat: allocate focused URLs in candidate coverage rounds`.

### Task 2: Search provenance and bounded manifest

**Files:** Create `focused_search.py`, `focused_search_wrapper.py`, `tests/test_focused_search.py`; modify `focused_capture.py` and test manifest (fast).

**Interfaces:**
- `SearchResult` frozen dataclass: `alternatives: dict[str,list[str]]`, `checked_at: str`, `excluded_counts: dict[str,int]`.
- `search_alternatives(candidates: list[dict], *, deadline: float, command: list[str], cwd: Path) -> SearchResult`.
- `parse_search_manifest(text: str, *, allowed_symbols: set[str], attested_urls: set[str]) -> dict[str,list[str]]` raises a typed protocol failure on malformed manifests; excludes unattested alternative URLs with counts.
- `run_private_child(command: list[str], *, input: str, timeout: float, cwd: Path, wrapper: Path, input_limit: int, read_artifact: Callable) -> CompletedProcess` lives in focused_capture. Existing `run_focused` delegates with its original input cap, wrapper, receipt reader and `.focused_pages` result semantics.

- [ ] Write `test_search_manifest_cannot_erase_seed_or_attest_snippet_link`: valid omitted symbols remain absent only from alternatives; only exact result keys are attested, never links inside prose. Seeds are parent-owned, not reconstructed from artifacts.
- [ ] Write tests for duplicate symbol rows, duplicate JSON keys, NaN, unknown symbols, over-five alternatives per symbol, over-25 retained bindings, Unicode URLs, oversized input/stdout/artifact, invalid nonce/completion, nonzero/timeout and legitimate empty results.
- [ ] Add real bootstrap/registry tests: enforce at most three search invocations, preserve underlying arguments/results, restore handler identity, reject a fourth call before dispatch, remove FD/nonce inheritance before model startup, and confirm no extraction tool in the child toolset.
- [ ] Observe RED using `tpy -m unittest discover -s tests -p test_focused_search.py -v`.
- [ ] Implement private receipt version 2 for search: at most three invocations, at most the first 15 top-level result entries per invocation, exact URL keys only, URL length at most 4,096 characters, maximum 1,048,576 artifact bytes. Use 131,072 input bytes for the new search child; keep legacy focused input 8,192 and stdout/stderr caps unchanged. Reject oversize identities intact. Successful completion with missing/invalid mandatory receipt fails closed.
- [ ] Build the search-only prompt with each exact seed, symbol, catalyst and event date; request existing three lane searches and alternatives only. Preserve seven-turn/110-second model ceilings while the supervisor clamps actual remaining wall time.
- [ ] Run new tests, legacy focused reuse tests and full tier. Commit the independently testable search boundary only when green: `feat: attest focused search alternatives through private receipts`.

### Task 3: Isolated multi-URL extraction protocol

**Files:** Modify `extraction_worker.py`, `structured_extraction.py`; create `tests/test_focused_batch.py`; update manifest (fast).

**Interfaces:**
- `run_batch_worker(urls: list[str], timeout_seconds: float = 30) -> dict` in structured_extraction.
- `extract_batch(request: dict, dispatch: Callable | None = None) -> dict` in extraction_worker.
- Batch request: `{'version':2,'urls':[...],'timeout_seconds':...}`. Successful batch response: `{'version':2,'status':'ok','results':[{'requested_url': exact_key, 'result': version_1_page_or_error_envelope}, ...]}`. Fatal protocol/supervisor response: `{'version':2,'status':'error','reason': typed_reason}`. Row errors do not turn sibling successes into failure.
- Existing `run_worker(url, timeout_seconds)` and worker version-1 protocol stay compatible.

- [ ] Write `test_batch_preserves_mixed_success_and_error_exact_keys`: five requested URLs with reordered provider rows produce five exactly keyed envelopes; shared provider/body/date normalization remains exercised.
- [ ] Add duplicate/conflicting identities, same-publisher redirects, unsafe redirect hops, future/conflicting dates, booleans/nonfinite timeouts, six URLs, empty URL list, Unicode byte admission, malformed output and stdout/stderr overflow tests.
- [ ] Add real owned-process tests for startup, early stdin close, blocked DNS/provider, success/timeout/nonzero cleanup and no descendant left running. Use short event-driven probes rather than production-length sleeps.
- [ ] Observe RED: `tpy -m unittest discover -s tests -p test_focused_batch.py -v`.
- [ ] Implement batch input at most 131,072 bytes, response 100,000 bytes and stderr 16,384 bytes; five unique URLs at most 4,096 characters each. Keep legacy input cap 8,192 by admitting version 1 under its original byte limit. Preserve hard 30-second per-worker cap, clamped by the caller. Dispatcher request uses 6,000 characters and a single shared worker deadline, never a new deadline per URL.
- [ ] Bind rows by exact request keys before projection. Only controlled real dispatch may mark trusted location provenance. Reject over-limit serialized batch envelopes intact; never turn truncated JSON into a successful page. Preserve configured provider and existing anonymous rescue routing.
- [ ] Run batch, structured extraction, publication provenance and existing unpatched extraction tests, then full tier. Commit: `feat: supervise bounded focused extraction batches`.

### Task 4: Deadline-bound focused coordinator

**Files:** Create `focused_pipeline.py`, `tests/test_focused_pipeline.py`; modify `extraction_worker.py` and `structured_extraction.py` for bounded safety-only operation dispatch; update test manifest (scenario).

**Interfaces:**
- `FocusedResult` dataclass: `allocation: Allocation`, `pages: dict[str,dict]`, `checked_at: dict[str,str]`, `submitted_urls: set[str]`, `outcomes: dict[str,str]`, `candidate_counts: dict[str,dict[str,int]]`.
- `run_focused_pipeline(candidates: list[dict], *, deadline: float, command: list[str], cwd: Path, unhealthy_domains: set[str]) -> FocusedResult`.
- `extract_allocated(allocation: Allocation, *, deadline: float, run_batch: Callable = run_batch_worker) -> FocusedResult`.
- `validate_pool_urls(urls: list[str], *, deadline: float) -> set[str]` uses current project safety through an owned isolated worker, not unbounded parent DNS. Define `validate_batch_urls(request: dict) -> dict` in extraction_worker with request `{'version':2,'operation':'validate_urls','urls':[...],'timeout_seconds':...}` and response `{'version':2,'status':'ok','results':[{'requested_url':exact_key,'eligible':bool,'reason':typed_reason},...]}`. Admit at most five URLs per validation batch, use the same owned-process/byte/deadline limits as extraction and pack these safety operations under the original focused deadline. No safety operation fetches page bodies. Extraction still repeats its existing DNS/URL/redirect safety checks to avoid time-of-check/time-of-use bypasses.

- [ ] Write `test_search_and_extract_share_absolute_deadline`: fake clock consumes search time; assert every worker allowance is `<= min(30, deadline-now)`, admission stops at expiry and no budget is reset.
- [ ] As amended in Task 6, `test_at_most_three_singletons_in_flight_with_first_round_first` uses controlled events to assert FIFO admission, max active three, the five initial seeds before extras, at most 25 singleton calls and no empty submissions for smaller pools. Logical allocation still retains five groups.
- [ ] Write `test_selected_but_unsubmitted_is_not_transport_failure`: expiry with queued batches retains exact selected/submitted counts, successful earlier pages and explicit `focused_deadline_exhausted` outcomes. Batch typed errors remain local; supervisor/protocol corruption raises focused failure.
- [ ] Add a safety-worker deadline/DNS failure test, no network call in the allocator, no late launch and no surviving owned children. Cover successful empty search alternatives with all valid seeds still extracted.
- [ ] Observe RED with `tpy -m unittest discover -s tests -p test_focused_pipeline.py -v`.
- [ ] Implement safe URL admission, Task 1 allocation and at most three concurrent supervised batch calls. Capture actual worker page envelopes and original completion times; no model text and no receipt-derived source invention. Search/provider/system failures remain typed. Do not claim individual network requests started from process launch alone: submissions mean dispatcher admission, with unavailable detailed transport accounting labeled unknown.
- [ ] Run focused pipeline, budget and full tiers; commit only green changes: `feat: coordinate focused coverage within the shared deadline`.

### Task 5: Radar handoff, evidence reuse and diagnostics

**Files:** Modify `alpha_radar.py` focused prompt/command/parser/live_research/gather handoff, `tests/test_alpha_radar.py`, `tests/test_research_budget.py`, `tests/test_focused_reuse.py`, `tests/test_candidate_alternatives.py`, `tests/test_rescue_fairness.py`; update documentation.

**Interfaces:**
- Existing `focused_retrieval(candidates, deadline=None)` remains the public radar boundary, now calls run_focused_pipeline and returns FocusedURLs with up to five selected bindings per candidate and trusted version-1 page envelopes with original check times.
- Preserve `CapturedResult`/`validate_structured_page` shared evidence contracts; do not introduce a second lenient date/body validator.
- `record_focused_allocation(result: FocusedResult, *, accepted_by_symbol: dict[str,list[dict]], path: Path) -> None` writes strict sanitized private projections correlated with the enclosing run.

- [ ] Write `test_live_radar_retains_urls_16_through_25`: exercise real focused coordinator-to-live_research handoff with mocked external search/extraction transports. Assert five initial bindings per symbol; no old 15-global or three-per-symbol truncation.
- [ ] Write `test_accepted_parent_pages_avoid_both_fetch_paths`: forbid direct and fallback transports when trusted pages pass shared quality checks; undated/mismatched/error pages still take unchanged bounded normal fetching. Preserve SEC enrichment and original receipt check times.
- [ ] Add five-initial-plus-three-rescue binding tests, no already-selected URL recycled into alternate rescue, three distinct rescue candidates max, successful intake skips rescue and unchanged four-source synthesis cap. Keep current health/provenance ranking without evicting the guaranteed seed slot.
- [ ] Add strict diagnostic allowlist/count tests: available/selected/submitted/extracted/accepted are distinct; candidate run-salted tokens only; no raw URL/body/prompt/stderr; unknown network accounting is not zero. Read exact temporary-ledger rows back and reconcile totals programmatically. Persistence failures cannot turn missing evidence into success.
- [ ] Observe RED through the actual radar/budget/reuse tests before implementation.
- [ ] Wire focused command to search-only; establish the single focused deadline before launching search, using the existing downstream reservation. Load source health once before allocation, rather than re-sorting into the old three-URL merge afterward. Preserve focused-disabled behavior and existing fallback CLI classification.
- [ ] Update the relevant legacy focused parser tests/callers for the new attested manifest path without removing strict schema/provenance regressions. Bypass legacy optional 15-URL extraction capture in this production route; keep its other callers/probes working.
- [ ] Run new modules, radar/budget/rescue/reuse modules, all tiers and raw discovery with equal counts and no operational state mutation. Update shipped docs with exact limits, ownership and qualified guarantees; commit: `feat: retain five focused sources per candidate end to end`.

### Task 6: Real handoff, independent review and controlled release

**Approved transport repair within this task:** flatten logical coverage groups
into FIFO singleton jobs in the existing three-worker coordinator; retain the
existing singleton dispatcher/worker validation rather than projecting away raw
extensions or adding nested concurrency. Observe RED/GREEN on five individually
valid raw responses whose combined size exceeds 100,000 bytes, oversized-page
sibling retention, exact binding, no retries, at most 25 calls, global concurrency
three and original-deadline process cancellation. Diagnose the real startup test
without increasing its timeout or editing shared runtime/plugin code. Match the
production worker's committed-dependency bootstrap in the fixture. Preserve
Task 4's process fixture and the repaired focused-reuse readiness handshake.
Run final equal-count full/raw suites and at most one paired live comparison plus
one targeted real diagnosis; report actual quality acceptance, not just transport.
Zero acceptance requires exact typed reasons and remains a release blocker. Parent
owns independent Task 6/whole-branch review and any deployment; this repair grants
no production, schedule, broker or operational-ledger mutation authority.

**Files:** Create `scripts/probe_focused_coverage.py` and tests in `tests/test_focused_pipeline.py`; write private evidence only beneath ignored `test_artifacts/focused-coverage-25/`. Modify release documentation only after actual verification.

**Interfaces:** CLI `tpy scripts/probe_focused_coverage.py --cohort <private-json> --output <ignored-json> --as-of <aware-UTC-ISO>` accepts one to five explicit company-event pairs with original discovery URLs. No intake, broker, review, order or operational-journal calls are reachable from this script.

- [ ] RED-test sink validation, symlink/path escape rejection, deterministic as-of input, prohibition of operational journal/broker calls, bounded input and strict count accounting. Implement the probe with 0700 directory/0600 files.
- [ ] Run the exact installed model search-to-parent batch-extraction handoff on a fixed multi-candidate cohort. Save real per-candidate available/selected/submitted/extracted/accepted counts, failure reasons, provider/model identity, source revision and latency. Repeat baseline/new path on the same cohort/as-of for comparison; disclose network/cache/time-order effects. No fabricated responses or automatic fixture substitution.
- [ ] If provider/auth/date issues prevent useful evidence, report actual transport/acceptance outcomes and keep release blocked where the changed handoff is unverified. A green synthetic allocator test is not a live retrieval success. No production-scale research or paper-order canary is authorized by this probe.
- [ ] Freeze the complete tracked/untracked implementation plus dependency identities. Obtain independent adversarial review of provenance, byte bounds, fairness, deadlines, shutdown, five-URL downstream retention, rescue and diagnostic privacy. Reproduce findings as RED tests, fix, rerun, and re-review changed bytes.
- [ ] Verify full and raw suites green, exact count parity, reviewed file hashes and clean isolated operational state. Commit probe/review-driven final corrections only after this verification.
- [ ] Before live cutover, inventory and pause exact affected research/execution jobs, preserve configuration/enabled/schedule state and recovery refs; keep unrelated monitoring/protection active. No pause is needed while only the isolated worktree changes.
- [ ] Synchronize reviewed code, run production tests and the isolated handoff smoke with all sinks redirected. Publish only owned source/docs; verify local/remote SHA by readback. Restore the exact saved jobs and read their state back. Any failed gate leaves the release unactivated or rolled back, not silently bypassed.
- [ ] Report implemented caps versus observed coverage, successful/failed probes, acceptance gains if any, latency tradeoffs, baseline handling, final SHA and schedule restoration. Explicitly state no order was submitted by development/probes.

## Plan self-review and handoff

Spec coverage: search provenance/input limits → Task 2; safe pools/fair allocation → Tasks 1 and 4; batch containment/byte bounds → Task 3; one deadline/concurrency → Task 4; URL 16–25, quality/reuse/SEC/rescue/diagnostics → Task 5; real handoff/comparison/review/cutover → Task 6. Baseline errors are a prerequisite blocker in Task 0, not a feature regression or permission to weaken tests.

Task dependencies: 0 before all code; 1, 2 and 3 expose the declared interfaces; 4 consumes all three; 5 integrates the coordinator; 6 validates/reviews/releases the complete branch. Use sequential task implementation to keep the shared supervisor interfaces coherent; reviewers can remain fresh and independent.

Status: plan written for user review, not execution approval. No feature code, schedule or trading-policy changes are made by this document. Ask the user to approve the plan and choose subagent-driven or native execution before implementation. Recommend subagent-driven because private provenance, batch containment and deadline handoff have independently reviewable, safety-sensitive boundaries.
