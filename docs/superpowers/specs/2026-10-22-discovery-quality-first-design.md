# Discovery quality first: measured six-lane research improvement

Status: updated design for user review, including a bounded LLM extraction-fallback contract; no implementation, live probe or rollout approved by this document itself.
Base: `19ca9522c387ea55c5a1ddd1c32623ad303a08e5`; research behavior at `2694236`.

## 1. Agreed intent and first increment

The user approved following the historical audit's recommendations and measuring improvement before committing to a full research overhaul. Start with discovery/search selection and its existing focused-retrieval handoff. Preserve all six lanes and existing configured providers. Do not claim search coverage or qualifications improve merely because control moves into code.

This is an architectural change to discovery ownership, not permission to rewrite execution, introduce a new feed or change safety policy. Discovery remains the first increment. The user also requested an LLM fallback when deterministic extraction fails; section3F now specifies that follow-up extraction/publication increment. It is part of this design direction, not silently included in discovery implementation or treated as already deployed. Broad rescue redesign remains separate. Known downstream failures stay visible; discovery work alone cannot establish end-to-end recovery.

### Alternatives

1. Prompt-only repair: cheapest, but does not guarantee search phase completion or stable query/result ownership.
2. Code-owned six-lane collection plus a tool-free selector: recommended first increment; directly tests search targeting and handoff without replacing evidence/synthesis/execution.
3. Rewrite the entire research pipeline: defer; expands attribution and rollout risk before measuring this increment.

## 2. Evidence motivating the design

Private audit: `test_artifacts/six-lane-historical-audit-20261022T005728Z/` in production. It contains every returned record from 37 retained sessions across October20–21: 34 production and three diagnostics. These are not interchangeable denominators.

Observed: stale/background date matches, weak intended issuer targeting, concentrated reporting, repeated stories across scans, two incomplete scout phases, nine overlength drops, five index/newsroom bindings and ten unsupported stronger event-state claims. Candidate/source association and publication freshness are different questions. A matched URL alone did not establish a completed event.

The 34 production discovery-bearing fires produced 15 system failures, 11 empty selections, seven policy/qualification rejections and one new dossier. This mixed-release two-day sample is a baseline, not a causal performance estimate or independent market inventory. Exact dates and detailed private examples must stay out of public candidate/reporting streams.

## 3. Proposed flow

### A. Code-owned bounded collection

- Construct one query for each existing lane: broad catalysts, SEC, issuer IR, independent reporting, undercovered/wires, rotating sector. Retain the existing sector rotation and as-of UTC/NY date context.
- Run exactly six searches with limit ten per call, under one inherited discovery deadline and bounded concurrency. No supplemental live searches in this first increment. An incomplete lane yields a typed result; it cannot silently become a successful empty set.
- Call the existing configured search dispatcher in a project-owned worker; reuse existing credentials, provider routing and fallback policy. Do not call broker APIs or change Hermes/core/configuration.
- Bind query, lane, result position, exact returned URL/title/description, provider receipt and run clock to immutable result IDs. Treat result content as untrusted data.
- Capture raw bounded provider results privately once, independently of the smaller selector projection. Reject malformed envelopes and unsupported arguments; do not reinterpret provider prose as a successful result set.
- No assumed structured date filtering: current receipts expose query and limit only. Use supported arguments only. Date terms and domain operators are targeting hints until provider enforcement is verified.

### B. Improve targeting without pretending queries enforce truth

- SEC queries target SEC-hosted filings. Independently classify the returned hostname and record mirror/other results; query syntax does not replace response validation.
- Reporting queries use the existing configured reporting-source set rather than repeatedly defaulting to Reuters alone. Source diversity is a search objective, not an evidence quota or new allowlist.
- Wire queries focus on company operating developments; identify legal-solicitation results for explicit exclusion from operating-catalyst ranking. Do not blanket-ban a publisher hosting both.
- Issuer IR targeting is honestly classified: issuer-hosted, company-origin syndicated, intermediary/index, or unverified. An 'investor relations' phrase or investor subdomain does not establish ownership. Unknown ownership stays unknown; no fabricated issuer-domain map.
- Relevant freshness is the announcement/event's role and date, not every date mentioned in its description. Remove the blanket 'discard any result mentioning an older date' instruction. Retain the seven-calendar-day candidate event gate unchanged.
- Keep lane templates/version identifiers stable during each evaluation cohort. Do not retune queries between runs until a favorable sample appears.

### C. Tool-free provisional selection

- Give one bounded, tool-free selector the collected result IDs and date/source-role cues. No search, extraction, MCP, memory, broker, filesystem or execution tools in that child.
- Return zero to five ranked provisional company-event leads. Zero remains valid; there is no candidate quota.
- Each selected lead binds a result ID, symbol, claimed event date, concise catalyst, exact supporting excerpt, and provisional event status (announced/scheduled/completed/uncertain). Excerpts must occur in the retained search result; the model's label is never authoritative proof. Even a 'completed' label remains unverified until downstream evidence checks establish it; no new field may bypass that boundary.
- Do not strengthen an acceptance into an approval or a planned event into a completed outcome. Where the result does not establish completion, preserve the supported weaker state or uncertainty and defer verification to extraction.
- Require investigation-worthy company-specific information, not proof of a complete trade thesis from snippets. Unknown surprise, market confirmation, exact price/liquidity or earnings state may be marked for verification; existing deterministic qualification/execution checks still own final admissibility.
- Each nonselected result gets a bounded reason classification or a link to its duplicate group, so an empty selection has a usable audit trail. The selector may abstain with 'insufficient snippet evidence'; do not manufacture detailed explanations as historical facts.

### D. Deterministic handoff

- Resolve selected result IDs back to exact original URLs in code; never allow model-generated URLs to become authority.
- Reject known home/index/newsroom bindings with a typed reason. Ambiguous article identity is explicitly unverified, not magically confirmed by a literal URL match.
- Keep the existing candidate limits: at most five leads, five URLs total and 500 characters per catalyst. Prompt the new selector for concise summaries. Overlength/malformed rows receive explicit per-row rejection telemetry; no silent disappearance, truncation of meaning, or unbounded repair loop.
- Preserve the current `{symbol, catalyst, event_date, urls}` contract at the focused-retrieval boundary. Supporting result IDs, excerpts, uncertainty and rejection records remain in a separate private run record, not new trusted dossier fields.
- The existing event-date gate runs against the real run clock. Unsupported or missing dates are not invented from crawl/query timestamps.

### E. Cross-scan continuity without a blacklist

- Retain a bounded private discovery-history index of observed source identities, supported company-event groups and prior research outcomes. In the initial shadow, this is owned by the isolated shadow workspace, not operational storage.
- Exact URL duplicates can be merged deterministically. Company-event grouping must keep provenance and uncertainty; ticker/date equality alone does not establish one event.
- Annotate repeated unchanged stories so the selector can allocate attention elsewhere; do not ban the ticker or suppress an event solely because it was previously rejected. New disclosures/outcome changes must remain discoverable.
- Do not alter qualified-dossier reuse/spending rules. This history is research context, not execution permission or a new ticker cooldown.

### F. Bounded LLM extraction fallback (follow-up increment)

The fallback interprets content that was actually fetched. It is not another agent-controlled fetch or search path.

1. Code performs bounded acquisition and standard article-body/publication extraction first, preserving the original capture, requested/returned URL identity, header/metadata structure and a locally computed content hash before flattening.
2. If substantive content exists but standard parsing cannot interpret its layout, retain it in an unresolved-capture pool. It remains unaccepted evidence; an unfamiliar layout alone must not discard the capture before fallback admission.
3. One tool-free LLM interpretation pass may propose extracted body passages, publication value/precision and relevant event facts. Every proposed field includes support from the retained original and its article/header association. Body extraction is grounded passage selection, not generated article text or an investment summary. Retrieved instructions are untrusted data, never executable instructions.
4. No LLM fallback can replace a failed fetch, missing response bytes, login/CAPTCHA shell or provider error with recalled content. Those paths retain typed acquisition/body failures and use existing alternative routes or sources. If available content cannot fit the existing safe request limits, abstain with an explicit capacity reason rather than enlarge the limits or silently remove conflicting evidence.
5. Code validates capture/URL binding, supporting passages, article association, publication-versus-event/update roles, conflicts and precision against the original capture. Model confidence and a matching date string alone cannot establish publication. Retain day-only precision when that is all the evidence supports; never invent a timezone or weaken an established exact instant.
6. Validation must not require the old parser to have already recognized the same layout or date context. Use an independently specified evidence-witness contract over original header/metadata/body spans. The follow-up plan must define and adversarially test that contract before implementation; removing the old predicate without an equivalent grounding check is not an acceptable fix. Invalid-present provenance refusals remain non-overridable.
7. Interpret body and publication fields together within the existing run-level one-shot interpretation allowance, not an extra model batch layered on top of publication recovery. Preparation, startup, I/O, validation and persistence debit the same cumulative90-second recovery budget, the same overall deadline and existing page/input/output ceilings. If that opportunity is spent, remaining cases abstain or use deterministic alternatives; no recursive repair or model relay.
8. Only validated outputs enter the existing body/freshness/domain gates. Preserve exact original-capture provenance and immutable receipts; a bounded model-visible excerpt never becomes the authority. Unknown fields remain unknown and the two-publisher requirement stays unchanged.

This contract applies to the follow-up extraction/publication increment. Its sequencing and witness schema need their own implementation-plan detail; discovery's tool-free selector does not extract pages or acquire this fallback's authority.

## 4. Budgets and boundaries

- Overall research active690s / outer720s; execution freshness600s; publication recovery90s and approved deterministic10/model10 combined20 ceiling unchanged.
- Inherit the current discovery-stage allocation, downstream reservations and monotonic absolute deadline. Command preparation, search collection, result projection, selector startup/I/O, validation and persistence all count. No hidden deadline reset or timeout increase.
- Six calls of ten results remain the initial acquisition allowance. No new feed/key/MCP server/provider pin; no wider scheduler cadence or extra recurring LLM job.
- Shared extraction, source-age180 days, body/URL safety, two accepted publisher-domain gate, earnings controls, horizon classification, liquidity/pricing, sizing, dual review and paper-only mandate remain unchanged.
- All detailed source material, prompts, provider metadata and history are private with 0700 directories and0600 files. Operational ledgers and public dashboard contain only their existing sanitized schemas.

## 5. Evaluation: three distinct claims

### Historical replay, no network

Use the complete frozen37-session inventory and all2250 records. Pre-register labels for a bounded reviewed subset: fresh announcements with older quarter-ends, future legal deadlines in old releases, index/newsroom URLs, acceptance vs approval, scheduled vs completed events, duplicates and all nine overlength cases. Labels retain unknowns and source roles; do not relabel to improve acceptance.

Run deterministic admission/role-binding and mocked-selector boundary tests over this corpus. Replay can prove loss accounting and rejection integrity. It cannot prove a new query would have found different historical results or prove current model performance without a separately authorized bounded model evaluation.

For the follow-up fallback, freeze a separate original-capture corpus with ordinary parser successes, unfamiliar but valid layouts and adversarial cases. Require a positive case where deterministic parsing fails but a grounded interpretation validates without the original layout recognizer. Negative cases include wrong-article metadata, update/event dates, conflicting publication claims, exact-to-day loss, invented timezone/body text, navigation/login shells, forged capture hashes and prior hard refusals. Measure body recovery, publication interpretation, false acceptance, precision loss and final two-publisher bundle completion separately. Wire-only captures without originals cannot establish full-original validation success. Use mocked model proposals for offline boundary tests; real model accuracy requires its separately budgeted evaluation.

Require: every input accounted for, exact source binding, no silent loss, no model event label promoted to verified truth by the handoff, ordinary empty outcomes distinct from incomplete transport/phase failures, no clock/limit regressions, no network/provider calls during offline tests. Separately score unsupported event-state claims against the pre-labelled subset; exact excerpt matching alone cannot prove semantic correctness.

### Contemporary coverage comparison, separately authorized probe

Compare frozen old/new lane templates over matching as-of windows and the same provider settings. Keep total request/time allowances explicit before execution; do not silently double scheduled work or add extra recurring scans. Reuse exact search receipts when comparing selectors, so selector effects are not confused with different search results.

Primary measurements: independently supported fresh company-event leads per lane, role/issuer targeting precision, repeated-story share, source-boundary errors, phase-completion rate and p50/p95 elapsed time. Structured-timestamp absence and unclassified leads remain reported rather than assigned favorable labels. No independent-feed market-coverage claim until a separately approved reference inventory is available.

### Shadow integration before replacement

Run the proposed discovery into isolated research-only artifacts; do not append operational candidates/reviews/order ledgers or invoke autotrader/broker tools. Keep production research unchanged during comparison. A live shadow has an explicit bounded evaluation allowance and start/stop condition before activation; it is not authorized as an unbounded extra cron by this spec.

Track whether provisional leads can form unchanged valid two-publisher bundles and reach existing synthesis. Maintain separate discovery gains and downstream publication/rescue failures. A better shortlist without accepted evidence is not operational recovery; a valid policy rejection is not a system failure.

## 6. Acceptance and rollout decision

Before any promotion: guarded full/raw suites with zero failures/errors/skips, immutable private fixture provisioning, source/operational isolation, independent final-diff review and rollback readiness. Preserve first failures and compare identical tested bytes. All actual live controls require verified readback.

Promote only if the bounded comparison shows fewer phase/schema losses and improved supported fresh-lead yield without higher event-state/source errors or violated budgets. Report exact sample sizes and uncertainty; do not infer causal gains from unrelated days/releases or optimize against a candidate quota. If novelty improves but corroboration still fails, hold replacement and address the separate provenance/rescue increment.

No production rollout, scheduler change, live search/model evaluation or new recurring job occurs at the design stage. Implementation planning must specify numeric live-evaluation allowances and a stopping rule for user review before those calls are spent.

## 7. Explicitly deferred

- Broad new feed acquisition/provider migration or full market-inventory integration.
- Extraction/publication fallback implementation is deferred to the follow-up increment defined in section3F; its witness schema and integration plan are not approved by a discovery-only implementation plan. Broader rescue-phase replacement remains outside this first increment.
- Execution/reviewer/risk changes, dossier-spending/cooldown changes, or enlarged budgets.
- Shared Hermes modifications, instrumentation or gateway restart.

## Review requested

Review this updated discovery-first scope, the section3F follow-up fallback contract and evaluation boundaries before implementation planning. Plans must keep the two increments explicit and separate historical replay, implementation validation and optional bounded live comparison; deployment approval is not implied by design approval.
