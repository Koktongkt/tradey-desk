# Project-Owned Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move bounded extraction provenance into Tradey, verify it against unpatched Hermes, and narrowly retire the local Hermes patch without weakening research or trading controls.

**Architecture:** A project-owned, uncached dispatcher owns safety checks, raw-response projection and one-shot rescue. Existing Hermes provider selection and direct vendor primitives sit behind one compatibility module; a project Keenable transport preserves its raw publication report. Both worker and focused CLI enter this same boundary; accepted publication evidence remains governed by existing validators.

**Tech Stack:** Python stdlib, asyncio, unittest, installed Hermes provider interfaces; existing supported runtime/dependencies only.

**Spec:** `docs/superpowers/specs/2026-10-18-project-owned-extraction-design.md` (approved by user in chat after commit `424899d`). Its historical approval-status line predates that approval.

## Global Constraints

- Paper only; no broker tools/credentials in research, no order submissions in tests or probes, no changes to mandate or execution gates.
- Keep the existing 540-second research outer budget and stage allocations unchanged.
- Standalone worker requests remain capped at 30 seconds or remaining stage time, whichever is smaller.
- Keep five URLs maximum per focused call and existing input/output limits: worker input 8192 bytes, output 100000 bytes, stderr 16384 bytes; accepted page text 6000 characters, title 200 characters.
- No new keys, MCP servers, providers, managed-gateway fallback or paid route. Preserve configured primary, tier selection, keyless opt-outs, existing ring order and rescue eligibility.
- Do not implement another persistent extraction cache in this migration. No shared extract-cache reads/writes on the replacement path; existing bounded in-run receipt reuse remains.
- Provider dates remain `provider_reported`; HTTP Last-Modified, HEAD, modified/crawl/retrieval times and metadata alone do not establish accepted publication time.
- Keep response body/location/publication from one fetch together. No date-only refetch or cross-response merge.
- Observe failing tests before behavior changes; fix reviewer findings with RED tests; independent review must reach PASS before deployment.
- Shared patch to retire: `9f8789d9714d147110138f90fab061cd7e9debda`; compatibility baseline: its parent `d923a5eb48` (resolve full SHA before execution).
- No shared Hermes source edits until final cutover. No `reset --hard`, broad file restore, forced push, private-state publication or unapproved dependency installation.

## Review Focus

1. Normalized URL aliases/duplicate requests must not allow one response to bind to another request; Task 3 tests reject ambiguous aliases and duplicate returned identities.
2. A provider's own hidden keyless walk must not multiply network attempts; Task 2 tests route free-ring calls directly and Task 3 tests exact attempt sequences.
3. Installed tool registration can retain a handler despite module reassignment; Task 4 invokes the real registry entrypoint and inspects host receipt output.
4. Response cancellation cannot terminate arbitrary sync network threads; Task 4 tests the actual parent's process-group timeout, not just coroutine cancellation.
5. Reverted source may remain loaded in a shared gateway; Task 7 separately verifies source, fresh-child imports and long-lived runtime retirement.

## File map and test conventions

Create:
- `keenable_extraction.py`: bounded anonymous raw HTTP transport and response-to-row normalization.
- `extraction_compat.py`: the only module that imports Hermes selection, policy, URL safety and raw/direct provider helpers; explicit compatibility failures.
- `research_extraction.py`: project orchestration, identity binding and public JSON projection, without persistent cache.
- `tests/test_keenable_extraction.py`, `tests/test_extraction_compat.py`, `tests/test_research_extraction.py`, `tests/test_extraction_unpatched.py`.
- `scripts/probe_project_extraction.py`: explicit network-only operator probe, never called by unattended trading.

Modify:
- `publication_provenance.py` (provider report construction), `extraction_worker.py`, `focused_wrapper.py`, `focused_capture.py` only where routing/binding requires it.
- Existing `tests/test_publication_provenance.py`, `tests/test_structured_extraction.py`, `tests/test_focused_reuse.py`, and `tests/test_manifest.json`.
- `docs/structured-extraction.md` and `docs/focused-extraction-reuse.md` for actual final behavior and compatibility/loaded-runtime limitations.
- `alpha_radar.py` only if a mechanical envelope integration is necessary; no new evidence acceptance rule.

Tests use unittest and existing fixture patterns. Run a single new module with `python -m unittest discover -s tests -p 'test_<module>.py' -v`; record RED and GREEN output under ignored `test_artifacts/project-extraction/`. Register new test modules in `tests/test_manifest.json` using the existing manifest schema, so canonical `python tests/run_tests.py full` includes every new case. Before using `python` for runtime integration, obtain the supported interpreter/source via `runtime_paths.hermes_runtime()`; bootstrap Hermes exactly as `structured_extraction.worker_command()` does. Never conclude compatibility from tests run against accidentally installed patched modules.

## Execution isolation prerequisite

Before product edits, load `superpowers:using-git-worktrees` and create an isolated Tradey implementation worktree/branch from the reviewed plan commit. Tasks 1–6 run there; the live authoritative checkout and its scheduled consumers remain unchanged until Task 7. Use the corresponding executing skill for the user-selected method. Discover the supported interpreter/source and snapshot a same-cohort live-path baseline before changing any deployment route. All tests use temporary operational state, and network probes write only to ignored test artifacts. Task 7 is the only point that merges/publishes the reviewed implementation into the live checkout. Native execution means the parent implements in that isolated worktree, not live-editing production.

## Task 1: Own publication report creation and bounded Keenable transport

**Files:** create `keenable_extraction.py`, `tests/test_keenable_extraction.py`; modify `publication_provenance.py`, `tests/test_publication_provenance.py`, `tests/test_manifest.json`.

**Interfaces:**
- Produce `publication_provenance.provider_publication(epoch: object) -> dict | None`, matching the exact existing version-1 schema and seconds range 946684800..4102444799.
- Produce `keenable_extraction.fetch(url: str, *, deadline: float) -> dict`, one raw normalized extraction row or a typed error row. `deadline` is absolute monotonic time. Transport constant `MAX_RAW_BYTES = 100_000`.
- Successful row has `url`, `title`, `content`, `error=None`, explicit `extraction_location`, and optional `publication`. Requested identity comes from the controlled single-URL HTTP request, returned identity from the response. Never add a caller-origin marker from provider fields.

- [ ] **Step 1: Write failing conversion tests.** Assert `provider_publication(946684800)['value'] == '2000-01-01T00:00:00Z'`; assert basis is `provider_reported`. Assert `None` for `True`, `946684800.0`, a milliseconds value, strings, null and out-of-range integers. Existing evidence tests must still show metadata-only reports cannot produce accepted `published_at`.
- [ ] **Step 2: Run `python -m unittest discover -s tests -p 'test_publication_provenance.py' -v` and record the missing-function/behavior failure.**
- [ ] **Step 3: Implement `provider_publication` and rerun to GREEN.** Use exact integer type, UTC second precision, no guessed units.
- [ ] **Step 4: Write failing transport tests using an injected/mock stdlib HTTP response.** Named tests: `test_stream_limit_before_decode` (100001 bytes -> output-limit failure), `test_no_follow_service_redirect` (302 -> failure and one request), `test_deadline_covers_reads` (expired budget -> timeout), `test_response_closed_on_decode_failure`, `test_error_declarations_never_become_pages` (including falsey non-string errors/false success/invalid status), and `test_body_and_publication_from_same_response`. Assert requested endpoint is exactly `https://api.keenable.ai/v1/fetch/public`, URL is query-encoded, no authorization header, and no retries.
- [ ] **Step 5: Run the new transport module, record RED, then implement `fetch`.** Use stdlib HTTP with redirect refusal, response close in all paths, bounded incremental reads and strict JSON. All blocking calls/read timeouts use the remaining deadline. Return errors from the existing worker reason vocabulary, not exception strings.
- [ ] **Step 6: Run both modules to GREEN; add the new module to the manifest and commit only these paths.** Commit: `feat: own bounded Keenable extraction reports`.

## Task 2: Isolate Hermes compatibility and expose direct vendor routes

**Files:** create `extraction_compat.py`, `tests/test_extraction_compat.py`; update manifest.

**Interfaces:**
- `resolve() -> object`: configured extraction provider or `CompatibilityError(reason)`; no config writes.
- `async check_url(url: str) -> str`: apply secret refusal, normalization, SSRF and website policy; return normalized safe transport URL or `CompatibilityError(reason)`.
- `uses_keyless(provider: object) -> bool`, `rescue_allowed(provider: object) -> bool`, `ring_order(name: str) -> list[str]`.
- `async primary(provider: object, urls: list[str], *, format: str, deadline: float) -> list[dict]`: direct keyed/custom provider path only, never an opaque ring.
- `async keyless(vendor: str, urls: list[str], *, deadline: float) -> list[dict]`: direct vendor only; Keenable calls Task 1 `fetch` for each URL within the same deadline.
- `rate_limited(rows: list[dict]) -> bool`: true only if every row is a rate-limit-shaped error, matching installed extraction failover behavior. Website-policy errors are never rescuable.

- [ ] **Step 1: Write failing selection/safety tests.** Explicit invalid/search-only provider -> typed error, no fallback; secret/private URL -> zero vendor calls; policy exception -> failure; keyless disabled/all vendors paid -> zero free calls. Normalization retains separate caller identity. Unknown required Hermes APIs -> `provider_error`, not guessed routing.
- [ ] **Step 2: Write a routing matrix test.** Keyed Exa/Parallel/Keenable use the provider's direct keyed method; Firecrawl uses `_use_keyless_ring('extract')` rather than the broader capability-free predicate. Free routes call direct `exa_extract_keyless`, `parallel_extract_keyless`, `firecrawl_extract_keyless`, and Task 1 Keenable transport, never `extract_with_failover` or `keyless_extract`. Preserve `_ring_order` semantics (free pin, paid exclusion and cursor advance). Check managed/self-hosted Firecrawl predicates without enabling a new route.
- [ ] **Step 3: Run `python -m unittest discover -s tests -p 'test_extraction_compat.py' -v` and record RED.**
- [ ] **Step 4: Implement the interfaces, importing Hermes helpers only in this module.** Installed reference points: `tools/web_tools_extract.py` validation/resolution, `tools/url_safety.py`, `tools/website_policy.py`, `plugins/web/keyless_mcp.py` direct extractors/ring predicates and `tools/web_tools_rescue.py` eligibility. Do not import `_dispatch_extract`, `_extract_safe_urls`, shared cache or patched publication helpers. Check helper signatures; missing/incompatible behavior fails closed. Custom providers are allowed only through their explicit resolved direct method; an unknown ring relationship is unsupported rather than automatically rescued.
- [ ] **Step 5: Run selection/routing matrix to GREEN and commit.** Commit: `feat: isolate research extraction provider compatibility`.

## Task 3: Build the uncached bounded project dispatcher

**Files:** create `research_extraction.py`, `tests/test_research_extraction.py`; update manifest.

**Interfaces:**
- Consume Task 2 compatibility functions and Task 1 publication records.
- Produce `async extract_tool(urls: list, format: str | None = None, char_limit: int | None = None, *, deadline: float | None = None) -> str` (JSON tool envelope).
- Defaults: markdown, 6000 characters, deadline `monotonic()+30` when absent. Accept `markdown`/`html` and integer limits 2000..6000; unsupported formats/types/limits fail as invalid request. At most five URLs, each at most 4096 characters. Empty batches fail. Worker calls carry their tighter outer deadline.
- Error rows retain existing basic tool fields plus a controlled `reason` from worker vocabulary; this optional reason is for project projection only. Never pass a provider-supplied reason through unchecked.

- [ ] **Step 1: Write failing safety/identity tests.** Cases: reordered rows, omitted rows, duplicate requested URLs, normalized aliases, mismatched `sourceURL`, same-publisher redirect, unsafe returned address, blocked returned publisher, cross-publisher return and Reuters contradictory URL dates. Assert no positional batch binding; reject ambiguous identities, not substitute the request URL for a returned URL.
- [ ] **Step 2: Write failing routing/bounds tests.** `test_success_never_rescues`; `test_rescue_at_most_one_ring` asserts exact vendor sequence and no duplicate vendor calls; `test_partial_failure_stops_free_walk`; `test_policy_refusal_never_rescues`; `test_one_absolute_deadline` asserts later attempts receive the identical deadline and none begin after expiry; `test_no_shared_cache` patches shared cache functions to raise and still obtains the expected result. If a keyed primary and anonymous endpoint share a vendor, skip the already attempted vendor during rescue, preserving relative order of remaining vendors.
- [ ] **Step 3: Write failing output tests.** Provider `location_provenance` cannot enter output; oversized envelope -> output-limit failure; base64 images become bounded placeholders; binary bodies/error documents are rejected. Keep existing head/tail truncation behavior with a recognized footer, but do not create full-text/cache files on this private path. No provider-only, Last-Modified or crawl timestamp generates accepted `published_at`; conflicts remain failures.
- [ ] **Step 4: Run `python -m unittest discover -s tests -p 'test_research_extraction.py' -v` and record RED.**
- [ ] **Step 5: Implement dispatcher.** One shared monotonic deadline, deterministic direct/one-ring state machine, explicit identity mapping and bounded projection. Reuse project strict JSON/error-document helpers and unchanged Hermes text-cleaning primitives only behind compatibility wrappers if needed. Skip unavailable time rather than granting a fresh vendor timeout. No new cache or raw metadata exposure.
- [ ] **Step 6: Run Tasks 1–3 tests to GREEN and commit.** Commit: `feat: add uncached project research extraction dispatcher`.

## Task 4: Wire both real entrypoints and remove cache interception

**Files:** modify `extraction_worker.py`, `focused_wrapper.py`, `focused_capture.py`, `tests/test_structured_extraction.py`, `tests/test_focused_reuse.py`; modify `alpha_radar.py` only for a mechanically necessary envelope change.

**Interfaces:** retain `extraction_worker.extract(request, dispatch=None)`, `project_row(row, guarded_location=False)` and version-1 worker result shape. The default dispatcher becomes Task 3. Project-generated typed row reasons map to the existing worker reasons; untrusted provider text never controls this mapping. Preserve injected dispatch tests and existing accepted page fields.

- [ ] **Step 1: Write failing worker test `test_default_dispatch_is_project_owned`.** Patch stock `web_extract_tool` and cache operations to raise; inject a project provider result and assert worker success from the project path. Assert timeout passed down is no greater than request time, capped at 30 seconds.
- [ ] **Step 2: Write failing focused test `test_registered_extract_uses_project_and_records_receipt`.** In a disposable isolated CLI child, run the real registered `web_extract` handler with fake transport, not a model/network call. Assert exact project row appears in the host receipt, nonce is not in model text/stdout/environment descendants, and a module-only reassignment that fails to change the real handler is detected. Verify handler restoration in exception/normal-exit paths.
- [ ] **Step 3: Write failing reuse/termination tests.** Existing duplicates, stale receipts, forged model marker and partial capture fail closed; explicit original/normalized/returned bindings do not cross-associate. Run the real supervisor with a sleeping transport child and assert timeout response, process-group termination, bounded stdout/stderr and unchanged private operational files. Do not equate cancellation of a thread future with termination.
- [ ] **Step 4: Run both modules, record RED, then wire default calls and real focused tool registration.** Remove `final_location_cache_guard` and its imports only once neither route uses the shared cache. Keep the controlled uncached marker and current URL-year/date rules; it is not a claim of provider freshness. Preserve recorder lifetime and actual registered handler references.
- [ ] **Step 5: Run `python -m unittest discover -s tests -p 'test_structured_extraction.py' -v`, the equivalent focused-reuse command, and `python tests/run_tests.py full`.** Require zero failures/errors and no `OPERATIONAL_ISOLATION_FAILURE`; record actual counts. Commit: `refactor: route research entrypoints through project extraction`.

## Task 5: Prove unpatched compatibility and add bounded live probe

**Files:** create `tests/test_extraction_unpatched.py`, `scripts/probe_project_extraction.py`; update manifest and both extraction docs. Private outputs only in `test_artifacts/project-extraction/`.

**Interfaces:** probe CLI `python scripts/probe_project_extraction.py --cohort <private-json> --output <private-json> --mode worker|focused`; input is a list of at most 12 explicit public URLs. It prints a sanitized summary and writes detailed rows privately. The focused mode uses the actual CLI tool/recorder path and network tools only; it cannot enter synthesis/review/order paths.

- [ ] **Step 1: Add failing integration/probe tests.** `test_imports_from_selected_unpatched_root` asserts loaded Hermes modules reside under the explicit compatibility checkout, patched publication module is absent, both entrypoints work and no shared cache is called. `test_probe_never_calls_trading` patches execution/research-journal writes to raise; fixtures assert per-source accepted/rejected counts sum exactly to cohort size, no silent skips, elapsed/call counts recorded and duplicate URLs rejected.
- [ ] **Step 2: Run the new module to RED, then implement the probe and controlled subprocess import harness.** Restrict output paths to the designated test-artifacts directory and mode 0600 for detail files. Track transport, requested/returned URL, publication basis, acceptance/rejection, typed failure, attempts and elapsed time per source. Use actual validators; never invent a success or translate unreachable to verified.
- [ ] **Step 3: Create a disposable unpatched Hermes checkout under `$TMPDIR` during execution.** Load `superpowers:using-git-worktrees` before creating worktrees. Resolve `9f8789d971^`, require it matches `d923a5eb48`, and use `git worktree add --detach "$UNPATCHED" "$PARENT"`. Set child-only `HERMES_SOURCE_ROOT` to it with the supported interpreter; verify `__file__` paths and source SHA inside the children. Do not modify global config or live source. If supported dependencies cannot exercise this checkout, stop and report the environment blocker; do not install ad hoc packages.
- [ ] **Step 4: Run full Tradey tests with the selected unpatched root.** Use `HERMES_SOURCE_ROOT="$UNPATCHED" HERMES_PYTHON="$SUPPORTED_PYTHON" python tests/run_tests.py full` for child discovery plus the explicit subprocess integration module. Require actual module-location assertions, not environment variables alone.
- [ ] **Step 5: Recover the historical six-source cohort from private session/diagnostic artifacts without publishing private content.** Add exactly six current issuer URLs, two per large/mid/small-cap category, across at least three publisher domains; preserve the historical cohort separately even if some URLs are now unavailable. Record current cap-category source/time without using broker MCP for research. If historical URLs cannot be recovered, mark the comparative check blocked; no claim of reproducing 3/6. Run both probe modes on the same frozen cohort against unpatched Hermes within existing per-call bounds.
- [ ] **Step 6: Compare counts, elapsed time and attempts with a same-cohort current-path baseline captured before production routing changes.** A route adding retries, exceeding any deadline/cap, accepting unverified evidence, or losing an entry is a blocker. New timeouts on previously passing baseline URLs due to cache bypass require diagnosis and user review before cutover; do not silently extend budgets. Record provider-side failures separately from adapter failures. Update docs with actual observed limits and commit: `test: verify project extraction against unpatched Hermes`.

## Task 6: Independent adversarial release review

**Files:** review the complete implementation diff and private verification outputs; corrective changes only in the task-owned files/tests.

- [ ] **Step 1: Give a fresh independent reviewer the approved spec, this plan, full diff and actual RED/GREEN/probe evidence.** Ask specifically for safety bypasses, provider hidden rings, batch identity, stale/cache origin, registered handler reachability, resource limits, metadata trust, loaded-runtime retirement and regression risk. Require a PASS/BLOCKED verdict with concrete findings; a claimed test run is not evidence without its command/output artifact.
- [ ] **Step 2: For each finding, add a reproducing test, observe RED, implement the minimal fix and rerun affected plus full tests.** Do not relax requirements to remove findings.
- [ ] **Step 3: Repeat independent review until PASS.** Verify returned artifacts/paths and relevant claims yourself. No deployment on a qualified or unverified PASS. Check final `git diff --check`, manifest inclusion and clean committed implementation state. Preserve all private live data outside source publication.

## Task 7: Quiesced, reversible cutover and loaded-runtime verification

**Files:** no new production features; narrow Hermes revert and private deployment report. Update extraction docs only if actual deployment differs from the reviewed instructions.

- [ ] **Step 1: Inventory before any live source publication/revert.** Record full SHAs/status for both repositories, actual interpreter/import paths, current research child processes and exact enabled state/IDs of affected producers/consumers. Use Hermes scheduler tools, not hand-edited cron JSON. Create local recovery refs `recovery/project-extraction-pre-cutover` in Tradey and `recovery/publication-patch-pre-revert` in Hermes if absent; never overwrite an existing ref. Save recovery data privately. Confirm open-position protection jobs remain untouched.
- [ ] **Step 2: Pause only affected enabled research producers and execution consumers and read back each exact job.** Drain or safely stop their existing research children; do not submit/cancel/alter broker orders. If a protection job shares an inseparable execution schedule, stop and resolve that deployment conflict rather than disabling protection.
- [ ] **Step 3: Integrate reviewed implementation into authoritative live main, rerun final canonical tests, push Tradey main and compare `git rev-parse HEAD` to `git ls-remote origin refs/heads/main`.** Do not resume yet. The remote SHA must match exactly and the tree must be clean; failed pushes/readback are blockers.
- [ ] **Step 4: Confirm Hermes HEAD/ancestry/clean state still match the captured patch.** Run `git revert --no-edit 9f8789d9714d147110138f90fab061cd7e9debda` in the shared Hermes checkout. On unexpected conflicts, stop and do not reset. Compare every path from `git diff-tree --no-commit-id --name-only -r 9f8789d971` with the parent tree: removed publication module/test must be absent and other patch paths must match, unless a separately reviewed intervening change explicitly explains the difference. Do not push Hermes upstream.
- [ ] **Step 5: Run affected upstream tests using the supported wrapper.** From Hermes: `scripts/run_tests.sh tests/tools/test_web_extract_robustness.py tests/tools/test_web_extract_timeout.py tests/tools/test_web_tools_dict_urls.py tests/tools/test_web_keyless_rescue.py tests/tools/test_web_keyless_fallback.py tests/tools/test_web_result_cache.py tests/tools/test_web_tools_truncate.py`. Confirm wrapper accepts multiple paths via its help/source before execution; if it does not, invoke the same wrapper separately per named file. The reverted custom provenance test is intentionally absent, not counted as a passed test. Record actual output and any environmental blockers.
- [ ] **Step 6: Run final actual-runtime worker and focused smoke probes without orders.** Assert imported sources point to the reverted shared tree, tool handler reaches the project adapter, cache operations are not used, and output/identity/date gates match the verified cases. Source diff alone is not runtime verification.
- [ ] **Step 7: Determine whether any long-lived gateway/agent loaded patched modules.** Follow the official Hermes restart documentation and loaded-runtime diagnostics. If needed, announce a delivery-safe supported restart and verify a fresh process/start identity plus messaging health afterward. Do not claim shared-patch retirement complete while old code remains loaded; inability to verify it is a named incomplete gate.
- [ ] **Step 8: Restore only the previously enabled affected jobs and read back each exact target.** Verify cadence, gates, broker mode and enabled state equal the pre-cutover inventory. Record local/remote SHAs, upstream tests, both smoke routes, source-vs-loaded-runtime status, source results and scheduler readback in the private release report. Report no orders submitted by this migration only after auditing its invoked paths; do not infer that unrelated schedules placed no orders.

### Rollback (trigger on any cutover safety/functional gate failure)

- [ ] Keep affected producers/consumers paused; preserve protection jobs and all failure evidence.
- [ ] If Hermes revert was committed and no intervening changes exist, reverse that exact revert with `git revert --no-edit "$HERMES_REVERT_SHA"`; verify restored six-path content against the recovery patch revision. If state differs, stop for conflict review, never reset the repository.
- [ ] Restore Tradey by reverting the reviewed migration commits in reverse order (excluding unrelated changes), using recorded SHAs and ancestry checks; run tests and non-order entrypoint probes, then push and verify the remote SHA. Do not restore private state from source control or broad backups.
- [ ] Verify loaded runtime and exact scheduler states before resuming previously enabled consumers. If restoration cannot be verified, remain paused and report the blocker.

## Plan self-review and handoff

Coverage: Tasks 1–3 own report creation/raw transport/safety/routing/bounds; Task 4 covers worker, real focused dispatch and receipts; Task 5 proves uncached unpatched execution and source accounting; Task 6 enforces independent review; Task 7 owns narrow revert, remote/source/runtime verification, protection-safe scheduler readback and rollback. Review Focus cases are assigned to Tasks 2–4 and 7. No success criterion depends on source acceptance increasing.

This file is a plan, not evidence of implementation, test success, live probes or reverted Hermes. User review and selection of execution method precede implementation.
