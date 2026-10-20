# Coverage-first focused retrieval: five candidates, 25 URLs

Status: proposed design; implementation and deployment not approved by this document.

## Intent and approved scope

The user approved designing discovery URLs as the coverage floor, deterministic round-based allocation and model-driven alternative discovery, with an increased limit of 25 focused extraction URLs and up to five per candidate. The outcome is fair opportunity to collect evidence for every shortlisted company-event pair, rather than more candidate volume or weaker evidence.

Retain up to five candidates. Preserve discovery's currently deployed search lanes and limits, research model selection, reviewer independence, source validation, synthesis limits, paper-only mandate and every execution control. Do not increase stage/overall deadlines, model turns or per-page output size. More capacity is a ceiling, not a requirement to fetch filler. Successful retrieval or qualification cannot be guaranteed.

## Current implementation and evidence

Inspected base: `835c56c`.

- `alpha_radar.focused_retrieval_prompt` supplies symbols, catalysts and event dates but omits discovery URLs. It instructs the model to perform three search calls, choose up to 15 extraction URLs in three calls and return at most three useful URLs per candidate.
- `parse_focused_retrieval` is called with a 15-URL global cap and computes a candidate-count-dependent per-symbol cap. It does not allocate extraction attempts.
- `live_research` merges discovery/focused URLs with `limit=3`, retaining two alternate URLs for later rescue. Increasing only the prompt would leave this downstream bottleneck.
- `focused_capture` has a 15-URL optional capture bound. Its trusted extraction receipts are separate from model output. The new parent-owned extraction route must preserve that trust separation rather than declaring model bodies trusted.
- `research_extraction.extract_tool` accepts at most five URLs per call and 2,000–6,000 characters per page. The dispatcher owns configured provider/rescue routing and existing URL/publication contracts; do not replace it with one vendor or plain HTTP.
- The focused wall-clock cap is 150 seconds and the overall active research cap is 570 seconds. Focused admission reserves the existing downstream budget. Both caps stay unchanged.
- The October 19 transcript sample showed unequal allocation and unused capacity, including a four-candidate session with allocations 1/3/3/0. This is a recorded-session sample, not a full historical census.
- Commit `59bcf97` subsequently aligned the focused tool schema and capped historical oversized integer character requests. Historical `invalid_request` responses do not establish an ongoing failure on the current revision.

## Options considered

1. Prompt-only coverage rounds: smallest change, but cannot guarantee allocation, submission caps or end-to-end retention. Not selected.
2. Parent-owned selection and extraction after one bounded model search session: selected. Makes fairness and caps testable without extra per-candidate model sessions.
3. Separate focused model session for each candidate: easier local instructions but adds model/process overhead, competing deadlines and a larger orchestration surface. Not selected.

## Proposed architecture

### A. Search-only focused child

Change the focused model's role to finding alternatives, not fetching bodies or deciding global allocation. Use the search-only toolset. Keep the three existing primary/independent/wire search objectives and the existing model turn/run-budget ceilings; do not add discovery lanes or one model call per candidate.

Supply each candidate's exact validated discovery URL alongside symbol, catalyst and event date. Ask for a strict symbol-bound URL manifest of up to five alternatives per requested symbol, copied from actual search results. The manifest may omit candidates with no alternatives; the parent still owns their discovery seeds. No model-authored article content, publication date or receipt is accepted.

Capture actual search-result URL keys through a child-local project wrapper and the existing parent-owned private FD/nonce/completion pattern, extended for bounded search provenance. This is not ordinary model stdout and is not a durable search/body log. Enforce at most three search invocations and retain only a bounded result set from those calls. Use the actual installed search handler; verify registration through the real bootstrap. Capture exact top-level search-result URLs, not arbitrary links embedded in snippets. A model alternative must exactly match a captured result URL. A search receipt proves that the URL was returned, not that the article is relevant, safe, dated or independent.

Strictly validate manifest JSON, requested symbols, URL syntax and global/per-symbol limits. Merge duplicate symbol rows without letting them consume slots. A valid manifest that omits a symbol must never erase its seed. Unattested/guessed alternative URLs are excluded with a typed reason. Provider nonzero/timeout, malformed final output or missing/invalid mandatory search provenance is a focused-stage failure; do not manufacture an empty successful search or silently weaken provenance. Search capture artifacts remain bounded, private and deleted after the run.

Review bounded input/output byte admission because supplying seeds increases the current 8,192-byte input. Select an explicit finite limit supported by the subprocess supervisor, test boundary values and reject oversized identities intact; never truncate a URL into a different identity. Preserve hard stdout/stderr/artifact bounds rather than allowing unbounded text.

### B. Deterministic candidate pools and allocation

For each retained symbol, combine its seed and attested model alternatives. Deduplicate exact URLs and prefer distinct registered publisher domains. Use existing historical health/provenance ranking within the candidate, not as publisher bans. A valid seed reserves the first coverage slot even when its publisher is recently unhealthy; fetch failure is observable and is not proof to suppress an untested URL. Unsafe seeds are ineligible and produce an explicit reason.

Build one ordered selection list by rounds over the original retained candidate order:

1. First available URL for every candidate.
2. Second available URL for every candidate.
3. Third available URL for every candidate.
4. Fourth available URL for every candidate.
5. Fifth available URL for every candidate.

Within later rounds prefer new publishers before same-publisher alternatives. Distinct-publisher preference is not a new hard gate: a same-publisher alternative may be useful when another page is blocked. No symbol receives more than five selected URL bindings and the union contains at most 25 unique requested URLs. Unused candidate capacity is not transferred above another candidate's five-URL maximum.

If an exact URL legitimately belongs to multiple candidate manifests, request it once, preserve separate candidate bindings and count its extraction once. Do not infer relevance to other symbols. A candidate with no safe seed or attested alternative is recorded as uncovered, not assigned a guessed URL.

### C. Parent-owned bounded extraction

**User-approved transport amendment (2026-10-20):** logical coverage groups
remain at most five groups of five, but no longer define provider request units.
The parent flattens their deterministic round order into at most 25 singleton
extraction jobs, each selected unique URL admitted once, without retry or a second
hidden 25-call allowance. Exactly three global coordinator threads own at most
one active supervised singleton each; there is no nested extraction executor.
`provider.extract` receives one URL through the existing dispatcher. Existing
configured rescue/ring behavior is unchanged, not expanded by this amendment.
Each complete raw singleton response (including extensions) must pass the unchanged
100,000-byte validation **before** binding/projection. One oversized page receives
`output_limit` without erasing independent sibling jobs. The projected version-2
worker envelope remains capped at 100,000 bytes and each page at 6,000 characters;
the parent retains at most 25 such bounded pages, not an unbounded aggregate raw
response. Request identity, mandatory model-search attestation, safety, provenance,
qualification, downstream trusted reuse, original shared deadline, minimum reserve
and owned-group kill/reap gates remain unchanged. No late launch or cap increase.
The following original multi-URL protocol remains supported for other callers;
its multi-row transport packing is superseded for the focused coordinator only.

The allocator packs the round-ordered unique URL list into at most five logical groups of at most five URLs. The focused coordinator admits one singleton per unique URL in that order, at most three concurrently, with no empty calls. With five candidates, the first five singleton admissions cover all five seeds before extras.

Execute the existing project dispatcher in owned isolated worker process groups, extending the worker/supervisor contract for bounded multi-URL requests rather than importing network code into an uncontained parent. Preserve runtime/bootstrap/provider routing, URL safety, per-hop identity checks, five-row and 100,000-byte per-call response limits, 6,000-character page limit, private error projections and process cleanup. Every operation is clamped to the remaining focused deadline. Do not start a queued batch after expiry. No unbounded retry or extra focused search is added.

One focused deadline covers search startup, model search/manifest, allocation, extraction, collection and cleanup: the earlier of the current 150-second focused cap and existing overall-deadline downstream reservation. It is established once, not restarted after search. Preserve the model's current effort ceiling; the supervisor must clamp its actual available wall time. No guarantee of all 25 submissions under a short remaining budget is made.

Provider extraction errors are per-URL/batch typed outcomes that do not erase successful sibling pages. Supervisor/protocol corruption or persistence errors retain fail-closed system handling; never relabel them as market absence. An ordinary bad page does not fail unrelated candidates. All child groups are killed/reaped on completion, error or timeout.

The parent's selected manifest establishes URL discovery identity. Actual worker responses establish extraction provenance. Do not rely on model final prose to return successful bodies or decide which selected URLs survive. Keep the existing optional focused-extraction recorder available for its other callers/probes until deliberately migrated; the new production route must not pass 25 URLs through an unchanged 15-URL artifact limit. Where shared capture paths remain used, update both writer and reader bounds together or bypass them using the new trusted worker results, with tests proving no silent loss beyond URL 15.

### D. Downstream handoff and no duplicate work

Retain up to five selected URLs on each candidate through the initial evidence collection. Do not reapply the old three-URL merge or candidate-count-derived parser cap. This is an initial extraction pool expansion, not an increase in synthesis body size.

Pass the parent's real worker page objects into the existing structured/body/publication/freshness validation path. Accepted pages suppress duplicate direct/fallback fetching. Extraction errors or invalid/undated pages remain ordinary misses for existing bounded evidence gathering; the unchanged later fallback may try them, under its own existing shared deadline. Report these later attempts separately from the focused 25-URL ceiling.

Preserve exact requested/returned identity, source receipt times and current SEC publication enrichment. No model date/body becomes authoritative. Keep the synthesis bundle cap of four sources and current character limit, reranking, two-fresh-distinct-publisher gate, synthesis attempt limits and downstream gates unchanged.

Existing later rescue remains separately bounded to three distinct admitted candidates, its original absolute/deferred deadlines and the eight-URL post-rescue candidate binding capacity. Five initial URLs plus three rescue additions fit that binding capacity. Selected focused URLs must not reappear as unattempted alternates; preserve no-duplicate-rescue-work accounting. Do not spend extra rescue work after successful intake.

## Observability

Write sanitized private diagnostics correlated with the enclosing research run and run-salted candidate tokens. Record per candidate: available seed/attested alternatives, selected count, actual focused submissions, extraction success count, accepted source count, accepted publisher count and uncovered/deadline reason. Record batch admission/terminal state, unique URL total, deadline exhaustion and elapsed stage time. Reuse existing private source tokens to correlate quality outcomes; no raw URLs, prompts, article bodies or raw provider exceptions enter diagnostics or public dashboard output.

Use separate reason classes for no eligible URL, allocation omission (an invariant failure), submission prevented by deadline, extraction failure and source-quality rejection. A selected URL is not an attempted request; a successful envelope is not accepted evidence. Unknown/incomplete network accounting is not zero network activity.

## Acceptance and verification

Write and observe failing regressions before implementation. Required cases:

- Five seeds plus plentiful alternatives select exactly five per symbol and at most 25 unique URLs; a four-candidate 1/3/3/0 historical-style pool covers all four seeds before extras.
- Candidate omissions, duplicate rows, unknown symbols, guessed result URLs, malformed/unsafe URLs, invalid mandatory search artifacts and oversized manifests cannot erase coverage or launder provenance.
- Source pools with scarce alternatives underfill honestly; publisher diversity is preferred; unhealthy but valid seeds receive their reserved first attempt; unknown publishers remain eligible.
- Shared URLs fetch once while preserving explicit candidate bindings. Duplicate requests do not consume slots. Candidate symbol binding is not inferred from the body or request order.
- Batch sizes 1 through 5 and global pools 1 through 25 obey packing, at most three in flight and round-order admission. URL 16 through 25 survive the full worker-to-candidate handoff.
- Fake-clock tests cover search consuming most of the budget, deadline before launch, queued batches, partial completion, timeout cleanup and retained downstream reserve. No per-batch fresh focused budget or increased outer budget is allowed.
- Real isolated worker/bootstrap tests preserve configured provider routing, extraction schema limits, effective 6,000-character requests, row identity, redirects, publication precision/conflict rejection and trusted parent results. No model-authored body or receipt is accepted.
- Gathering accepted focused pages with direct and fallback transports forbidden makes zero duplicate calls; invalid pages still use unchanged bounded normal fetching. Preserve SEC enrichment and first/repeated cache tests.
- Five initial URLs integrate with existing rescue caps, no repeated selected-URL rescue, unchanged successful fast path and two-publisher final gate. A long source list does not widen synthesis/reviewer/trading permissions.
- Test private diagnostic field allowlists and exact selected/submitted/success/accepted totals. Ensure no raw identities are written to public artifacts.

Use the project's supported runtime and dependency-wrapped full suite plus raw discovery. Freeze the final implementation diff for independent adversarial review. Before deployment, run a bounded isolated real model-search-to-parent-extraction handoff with all sinks redirected to test_artifacts, no intake/journal/broker calls, and exact per-candidate accounting. Compare runtime, coverage, accepted bundles and failure types with the existing route using a fixed cohort/as-of time. This smoke proves the handoff only, not improved investment performance or scheduled recovery.

## Deployment and rollback

This document changes no production code, schedules, orders or policy. For implementation, use an isolated worktree. Before live-tree cutover, pause affected research producers and execution consumers, retain exact schedule/config state and recovery refs, and follow the trading-system release gates. Restore only after tests, independent review, real handoff evidence and publication/remote verification. Roll back code rather than weakening evidence gates or extending deadlines if latency/coverage regresses. Keep monitoring/protection responsibilities intact.

## Design-stage checks

The document-only diff passed whitespace and placeholder checks. No product code has changed. An initial full-suite invocation through the project venv lacked Hermes imports/dependencies and is not a valid production regression result. A rerun through the installed dependency-committed environment with the selected Hermes source completed 1,212 tests with zero assertion failures and three errors in process-lifetime tests (missing child PID marker files and a disappearing `/proc/.../stat` entry). This baseline is not green and does not validate the proposed feature. Do not commit or release implementation on this evidence; reproduce under the supported supervision-test interpreter before attributing these errors or changing tests. The design remains uncommitted pending a green baseline, honoring the user's tests-before-commit convention.

## Review request

Approve or amend this written design before implementation planning. The architectural workflow requires a separate written implementation plan and execution-method selection after design approval. In particular, confirm the intended tradeoff: more available extraction URLs within the same focused deadline can improve redundancy but does not promise that every available URL is attempted or every candidate qualifies.
