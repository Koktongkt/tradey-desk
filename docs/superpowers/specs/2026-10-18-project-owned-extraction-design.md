# Project-owned extraction and Hermes patch retirement

Status: proposed concrete design; user approved migration scope, not this written specification or implementation plan.
Date: 2026-10-18 (UTC).

## Intent and success

Move Tradey's bounded publication/location preservation out of the shared Hermes source tree, then retire Hermes commit `9f8789d9714d147110138f90fab061cd7e9debda` using a history-preserving revert. Preserve evidence gates, research deadlines, paper-only restrictions, source safety and diagnostics. No acceptance-rate target is a release gate: legitimately unverifiable sources must remain rejected.

The migration is not a new publication-authentication system. A provider report remains unverified and may detect conflicts; it cannot alone populate accepted `published_at`. HTTP Last-Modified, HTTP HEAD, retrieval/crawl times and URL structure alone are not newly approved publication evidence. Keep existing article-evidence rules unchanged.

## Observed baseline

Read-only inspection on 2026-10-18 found clean working trees:

- Tradey HEAD `aa583ef`; recent provenance change `9fbe0ad`.
- Hermes HEAD `9f8789d9714d147110138f90fab061cd7e9debda`; parent `d923a5eb48`.
- The Hermes patch modifies six paths: `plugins/web/keyless_mcp.py`, `tools/web_publication.py`, `tools/web_tools_extract.py`, `tools/web_tools_truncate.py`, `tools/web_result_cache.py`, and its provenance tests.
- `extraction_worker.extract()` uses Hermes `web_extract_tool`; `project_row()` and project `publication_provenance.py` already validate bounded extensions.
- `focused_wrapper.py` wraps that tool in an isolated CLI child; `focused_capture.bind_calls()` binds host-recorded results to requests. Both focused reuse and standalone fallback must migrate, not just one.
- The current Reuters cache guard changes a cache function only inside an isolated child. It cannot restore metadata removed by upstream normalization.
- The shared patch includes cache integrity and URL-binding changes, not only date preservation. A replacement must avoid depending on that shared cache rather than copying only a date parser.

These observations are repository facts, not a fresh live-source acceptance measurement. The historical 3/6 result is not re-established by this design work.

## Alternatives

### A. Upstream-only preservation

Smallest project code footprint, but release timing/acceptance belongs upstream and provenance validation still belongs to Tradey. Does not meet the immediate goal of running uncustomized Hermes without waiting for an upstream release.

### B. Project-owned, uncached extraction boundary (recommended)

Own the research-specific orchestration and projection in Tradey. Reuse unchanged Hermes provider registration/selection and URL/policy primitives where suitable, with an explicit compatibility contract. Consume provider responses before generic public-tool trimming. Own the Keenable raw response adapter because its existing normalizer removes `published_at`. Avoid the shared extraction disk cache entirely on this path.

This adds project maintenance, but removes the shared source patch and keeps ownership with the evidence consumer. It does not make Tradey independent of all Hermes APIs. Internal helper imports must be isolated and tested against the actual unpatched installation; unsupported changes fail closed rather than silently selecting a different backend.

### C. Child-local interception of normalizers/cache internals

Fewer initial code changes, but moves the same coupling into runtime monkeypatches and can miss registry-held function references. Rejected as the core strategy. A child-local tool entrypoint substitution is allowed only to route the existing focused CLI to the project adapter, as the wrapper already routes recording; no provider/cache/normalizer monkeypatching.

## Components and data flow

### 1. `research_extraction.py` — project dispatcher

Expose an async `extract_tool(urls, format=None, char_limit=None)` compatible with the focused tool's JSON envelope. Standalone requests still use the existing version-1 worker protocol. Keep five URLs maximum per focused call and existing input/output limits; reject unsupported formats/limits rather than expanding resource use.

Flow:

1. Validate shape, normalize URLs consistently with the existing Hermes request path, and reject secret-bearing URLs before network work. Retain original request identity separately from normalized transport identity.
2. Apply public-network/SSRF validation and website policy to every requested URL. A policy lookup exception is a typed failure, not permission. Refusal never enters rescue.
3. Resolve the configured extraction provider without changing global configuration. Preserve explicit backend selection and keyless opt-out/tier behavior. No managed-gateway or new paid fallback is introduced.
4. Dispatch raw provider extraction through a small transport boundary. For existing providers, reuse their installed provider interfaces. For Keenable's anonymous endpoint, use the project-owned transport below, not its lossy Hermes normalizer.
5. Preserve the existing one-shot rescue eligibility and configured keyless-ring order, with each eligible vendor attempted at most once and no nested rescue. Project routing must substitute its own Keenable adapter whenever that ring reaches Keenable. Do not call a provider method known to run an opaque nested ring and then run the ring again; establish direct-vendor routes in the compatibility layer. Unrecognized routing contracts fail closed.
6. Validate each raw response, including explicit provider error/status/success and policy markers. Bind output by explicit requested identity or an unambiguous single-request transport response, never batch list position. Reject ambiguous/missing/duplicate bindings. A vendor-reported returned location is a report, not proof that every remote redirect hop was safe.
7. Check returned URLs for public-network safety and website policy and apply existing same-publisher/article-identity rules before admitting them to research. No new direct publisher fetch/redirect-following client is introduced in this migration. Third-party fetch internals remain a provider limitation, not a claimed verified redirect chain.
8. Return bounded text plus strictly validated publication and location records. Do not expose arbitrary metadata or raw provider diagnostics to models/public outputs. Preserve base64/binary rejection and truncation semantics without importing patched Hermes functions.

Keep credentials out of new files, logs and diagnostics. The research child receives no broker credentials/tools. This dispatcher does not access or write execution state.

### 2. `keenable_extraction.py` — narrow raw-response transport

Use the existing anonymous endpoint contract (`https://api.keenable.ai/v1/fetch/public`, URL parameter) without adding keys, servers or new providers. Honor keyless opt-outs, website policy and the same outer deadline before invoking it. A direct vendor adapter is not authorization to bypass routing policy.

The transport must cap bytes while streaming before JSON decoding, validate HTTP status, enforce a timeout no greater than remaining caller time, close responses, and avoid unbounded redirects/retries. Its own service endpoint redirects are refused unless explicitly validated; credentials are never sent. No automatic retry budget is added.

Project normalization owns the exact documented integer Unix-seconds conversion currently in Hermes. Reject booleans/floats/milliseconds/out-of-range values as publication claims; malformed declared envelopes fail closed. Preserve whole-response requested URL, returned URL, body and publication report together. Never join a timestamp from a second fetch onto the first fetch's body.

### 3. Existing worker, focused wrapper and evidence validator

- `extraction_worker.py`: call the project dispatcher by default; retain injected-dispatch testing, strict protocol, stderr isolation and parent hard timeout/kill behavior.
- `focused_wrapper.py`: route `web_extract` to the project adapter in the existing isolated research CLI child, then wrap it in the existing recorder. Prove that actual registered tool invocation reaches that handler, not merely an assignment to a module attribute. Restore local entrypoints on exit; do not alter the shared Hermes checkout or other sessions.
- `focused_capture.py`: continue consuming host-recorded request/result receipts. Bind original requested identity explicitly; preserve duplicate rejection, nonce/channel isolation and capture-age limits. Do not trust a model-supplied `location_provenance` marker.
- `publication_provenance.py`: own provider report creation as well as existing validation/conflict logic. Keep report basis `provider_reported`; no promotion to publisher attestation.
- `alpha_radar.validate_structured_page()`: keep current source/publication/conflict gates. Any change is limited to mechanically accepting the same trusted project-produced envelope, not broadening date inference.
- Remove the legacy Hermes disk-cache monkeypatch once both project entrypoints bypass that cache. Only set the existing uncached-dispatch marker from the controlled project path; it means no shared local cache was used, not that a vendor has no internal cache.

### 4. Cache policy

Do not implement another persistent extraction cache in this migration. Both standalone and focused project extraction bypass Hermes extract cache reads and writes. Already existing in-run focused receipts remain eligible for reuse under their current freshness/identity controls. No cross-fetch metadata/body pairing is possible because the adapter projects one validated raw response as a unit.

Trade-off: cold network calls can increase compared with shared-cache hits. Preserve current per-run caps and fairness/deadline controls; availability can degrade to typed timeout/unverified results. Measure calls and elapsed time in the probe. If this materially harms the existing workflow, stop the cutover and return a separate cache design for approval rather than silently extending budgets or shipping an unsafe cache.

## Timing, errors and operational boundaries

Keep the existing 540-second research outer budget and stage allocations unchanged. Standalone worker requests remain capped at 30 seconds or remaining stage time, whichever is smaller. Rescue consumes the same deadline, not a fresh deadline per vendor. Focused requests consume the existing focused-process budget; no extra fetch is performed solely to obtain a date. Synchronous transport work is confined to the killable research child; cancellation alone is not claimed to terminate a network thread.

Map new adapter errors into the existing structured extraction reason vocabulary and private per-domain diagnostics. Keep stale, unknown-freshness, fetch-timeout, malformed response and URL mismatch distinctions where the current ledger supports them; no invented successful evidence. Do not put live probes in production research/trade journals.

No changes to paper mandate, execution consensus, sizing, stops/targets, broker mode, cron cadence, model selection or evidence freshness thresholds. Deployment may temporarily pause affected research producers and execution consumers after scheduler inventory; record and restore only previously enabled jobs. Do not interrupt independent open-position protection monitoring. Actual job discovery and readback are implementation/deployment prerequisites, not claimed completed here.

## Verification and release gates

Write and observe failing tests before changing behavior. Required coverage:

- Unpatched Hermes compatibility, no imports of `tools.web_publication`, no calls to shared extract-cache get/put, no dependence on provenance keyword arguments added by the patch.
- Real focused registered-tool dispatch and standalone worker both use the same project adapter. Focused nonce/receipt isolation, duplicate rejection and bounded output remain intact.
- Exact provider timestamp conversion; unknown/provider-only dates stay unaccepted; visible date conflicts remain failures. HTTP Last-Modified/crawl/modified times do not supply publication evidence.
- Error envelopes, falsey/malformed declarations, oversized streamed payloads, missing fields and error-document bodies fail closed.
- Secret URLs, private addresses, policy refusals/errors, unsafe/cross-publisher returned URLs, Reuters contradictory dates, mismatched batch identities and reordered/omitted rows.
- Explicit backend/tier/keyless opt-outs, strict-selection failures, primary success, one-shot rescue and no repeated vendor/nested ring attempts.
- One outer timeout, parent kill behavior, no output mixing, no hidden extra fetch on metadata absence, no cache access. Existing focused reuse and rescue fairness tests remain green.

Test first against a disposable checkout of the exact Hermes parent `d923a5eb48` using the existing supported environment; no live shared-file edits for compatibility tests. Run the affected Tradey modules and its full canonical suite, plus the affected upstream extraction/keyless/cache tests on the reverted Hermes tree. Record exact commands, versions, counts and failures rather than assuming the historical suite size.

Run network-only probes through actual worker and focused CLI on the original six-source cohort recovered from prior private artifacts, plus a bounded mixed-domain/multi-cap issuer sample covering large/mid/small caps and requested/returned-location behavior. Use currently existing providers only; no new keys/MCPs. Record each URL, transport, returned location, publication basis, gate result, elapsed time and typed failure. Redact sensitive paths/prompts; store detailed results privately under `test_artifacts/`. Sample success is evidence for those routes, not a claim of universal source coverage. Unavailable original cohort members are explicit gaps, not silently replaced comparable results.

Acceptance: unchanged gates; actual unpatched execution verified; no shared-cache dependency; independently reviewed safety; bounded calls/runtime; complete accounting of accepted/rejected sources. Improvement beyond historical 3/6 is optional, not required.

## Cutover, rollback and audit

1. Inventory current repository SHAs, clean status, interpreter/source paths, running research children and affected scheduler jobs. Save a recovery ref/patch artifact for the exact Hermes commit. Do not print secrets/private journals.
2. After code/test/review gates pass, pause affected producers/consumers and drain their children. Keep protection monitoring intact. Use an isolated unpatched compatibility checkout for pre-cutover smoke probes.
3. Commit reviewed Tradey changes, push from the live authoritative checkout and verify remote SHA according to the release convention. Keep production private state out of source publication.
4. Apply `git revert 9f8789d9714d147110138f90fab061cd7e9debda` only after confirming ancestry and no unrelated edits. No hard reset and no broad checkout restore. Verify the six patch paths match the parent where expected, no remaining patched imports exist, and run affected Hermes tests. Do not push the local Hermes revert upstream without separate authorization.
5. Run final non-order worker/focused smoke probes from the actual deployment interpreter and source path. New children must import reverted files. Restart a long-lived Hermes gateway only if necessary and with a supported, separately announced delivery-safe procedure; source-file reversion alone does not establish the loaded runtime version.
6. Resume only previously enabled affected jobs after final verification; read back exact scheduler state. Report local source state separately from loaded shared-process state, and do not call retirement complete while a long-lived shared process still uses the patch.

If any safety or functional gate fails before revert, leave Hermes unchanged and keep migration out of production. If cutover fails after revert, keep affected consumers paused and restore the exact captured Tradey revision and Hermes patch with conflict/ancestry checks, then rerun smoke tests before restoring recorded scheduler states. Do not claim rollback by command success alone. Preserve all failed-probe evidence; no orders are submitted by migration verification.

## Review decision

This specification intentionally keeps provider-report preservation separate from publication verification and chooses no persistent cache. Approval of this written specification permits implementation planning, not immediate unreviewed implementation. The implementation plan must make the raw provider/ring compatibility mapping, RED tests, independent adversarial review, cutover checks and rollback commands explicit before execution.
