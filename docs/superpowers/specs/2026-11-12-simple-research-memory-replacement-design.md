# Replace event-identity admission with simple research memory

Status: written specification approved by the operator's “Approved and proceed” after commit `72ee766`; implementation-plan review/execution selection and production cutover approval remain separate gates.

Source baseline: `0cad12b8860938035f839ffb3f46d0b6b2db5533`.

## 1. Intent and approved boundary

The operator wants Alpha Radar to become more reliable and waste less work on repeated candidates. Replace the current formal event-identity/allowance admission machinery, rather than layering another gate on top. A valid research lead must not require a canonical earnings period, acquisition agreement root, event ID, allowance generation or reopening grant merely to reach ordinary investment analysis.

The first measurable improvement is reduced duplicate research on unchanged evidence. Candidate yield is not a quota; a legitimate evidence rejection, HOLD or no-setup result remains valid. A document cache does not solve publisher failures, publication provenance, model availability or all source-quality problems.

Preserve independently: paper-only authority, current enabled/configuration state, held/pending-entry exclusion, exact-dossier completed-review protection, narrowly proven pre-submission retries, dual-model consensus, source/freshness and earnings checks, deterministic risk/price/liquidity checks, durable order intents, submission idempotency, ownership, reconciliation and protective exits.

This specification authorizes neither ledger deletion nor a database restore. The written specification must be approved before implementation planning; production activation requires a separate exact-cutover approval.

## 2. Chosen approach and alternatives

Chosen: a small exact-document research-result cache, with a coordinated, forward-only retirement of event/allowance admission in all consumers. The cache controls research cost, never execution authority.

Rejected: a blind historical Git revert. Existing policy rows and independent protections are coupled to the newer runtime; old compatible code intentionally blocks entry when seeing an unsupported activation. Older permissive code would discard protection semantics.

Rejected: keep formal event admission and add caching above it. That can reduce repeated processing but leaves the reported identity-admission bottleneck intact.

No transaction matching, semantic similarity, model-declared materiality, legal agreement continuity, permanent ticker ban, new source provider, expanded budgets or new package is included.

## 3. Research flow

1. Validate deployment mode/history integrity. Read normal discovery inputs without asking an event resolver for permission.
2. Discover and parse the bounded shortlist. Existing source collection and absolute research deadlines remain unchanged.
3. Retrieve evidence through existing bounded acquisition, URL validation and publication recovery. Validate source quality, integrity and freshness normally.
4. Compute trusted document identities from complete retained provider/source representations. Persist the captures independently of any event resolution.
5. Consult completed document-stage and exact-evidence-bundle results. Reuse only compatible results that remain valid under current rules and source freshness. Otherwise do ordinary processing and synthesis.
6. An unchanged, already-completed bundle is skipped or reused according to its disposition; proceed to another shortlist candidate within the existing budget. A cache hit is not a new research qualification.
7. A new or changed evidence bundle receives ordinary synthesis/enrichment and candidate validation. Persist successful terminal work only after its supporting captures/result are durable.
8. Reuse and research-failure fallback apply the same exact-dossier review/freshness checks. No stale or previously rejected dossier is resurrected merely because fresh research failed.

Unknown formal event identity ceases to be an admission reason. Unsupported provenance, conflicting source/company attribution, missing earnings evidence, stale evidence and infrastructure failures remain distinct normal outcomes. Remove identity-only acquisition calls from the hot path; retain reusable source-capture utilities where they serve ordinary evidence.

## 4. Cache identity, data and validity

### 4.1 Trusted keys

A document-stage key is `(verified issuer identifier, representation kind, exact content SHA-256, research rule version, stage identifier)`. Use a deterministic issuer mapping already supported by the desk; do not accept model-supplied issuer authority. Conflicting attribution cannot produce a reusable success.

The content digest covers complete retained source bytes/text under an explicit representation contract, not a projected excerpt, URL, generated summary, verification timestamp, capture-envelope digest, dossier hash or event ID. Different transport/provider representations are separate unless their exact representation contracts agree. Do not strip content to manufacture matches. Cosmetic page changes can cause cache misses; this is an accepted conservative limitation.

A synthesis/result key includes the issuer, rule version and deterministic sorted set of all admitted document-stage identities supplied to that synthesis stage. A matching individual document permits only that document's processing to be reused. It does not suppress the candidate if another admitted document is new or changed. Different source bundles are not claimed to be the same economic event.

### 4.2 Minimal private result records

Use the existing canonical SQLite/JSONL storage boundary for one private append-only research-memory stream; include it explicitly in registered streams and isolated tests. No separate uncoordinated mutable database. Each completed record carries schema/rule version, key, stage, original completion time, supporting immutable capture references, validated result reference/digest and terminal disposition. References must exist and validate before a result becomes reusable. Repeated identical completion writes are idempotent.

Eligible terminal dispositions are successful validated document processing, completed evidence-backed no-setup/rejection, or a completed qualified dossier. A saved raw lead, successful HTTP response, partial extraction, unresolved provenance, timed-out synthesis or mere attempt record is not completed research.

Store qualified-dossier references without rewriting/re-hashing the dossier. Reuse must still pass existing candidate freshness and exact-dossier review rules. Cached no-setup results apply only to the exact bundle/rules while source freshness remains valid; they do not establish a permanent event or ticker ban.

### 4.3 Freshness and retries

Memory does not extend evidence age, candidate TTL, current quote validity, earnings-calendar validity or the configured verified-fallback limit. Original completion/check times remain unchanged on hits. A result is reusable for at most 24 hours from its original completion and only for as long as every applicable existing freshness rule permits. A previously qualified dossier additionally remains subject to the existing candidate/fallback limits; 24 hours is not a new dossier TTL.

Keep one transient-failure retry cooldown of 20 minutes for the exact issuer/URL/failure category when that resource is unavailable. It suppresses that retry only, not the issuer or its other sources. A new independently available source may proceed. Incomplete attempts are never success-cache hits. No persistent publisher-wide blacklist or immediate retry loop. Retry and cache reads consume the existing shared deadline.

If cache metadata/results are absent, incompatible, corrupt or unavailable, treat them as unusable and continue uncached if the existing budget permits; otherwise emit the ordinary deadline/failure outcome. Record a typed cache diagnostic. Never infer a prior successful result from a broken reference. Cache failure cannot bypass a mandatory execution/history integrity check.

## 5. Acquisition routing and other catalyst families

Remove the memory-era blanket acquisition diversion from discovery, recovery, rescue and direct intake. Historical merger wording in a filing must not divert a current earnings thesis. Acquisition observation retention may remain as private diagnostic evidence, but cannot independently grant or deny ordinary research admission.

Acquisition and other non-earnings leads can enter normal evidence-backed investment analysis without a formal transaction identity. They receive no exemption from source corroboration, freshness, earnings blackout, valuation/thesis quality, instrument, mandate or risk controls. A document merely mentioning a transaction is not sufficient evidence for an acquisition thesis. Research output is not trade approval.

The design intentionally gives up cross-document event-level suppression. Signing, amendment and closing documents may be separately researched. Do not silently rebuild transaction identity with a model or claim the cache prevents every repeat of the same deal.

## 6. Execution protection independent of event allowances

Replace event-bound candidate authority with code-owned deployment-mode/transition binding. Bind the trusted transition identifier before hashing each new dossier. Models and injected payloads cannot supply authority. Historical dossiers remain immutable; do not rehash them into new candidates to evade review history.

Entry must retain a fresh, coherent proof for the exact current dossier, proposal, evidence, dual approvals and deployment transition under the canonical entry lock. This is exact-attempt authorization, not an event allowance. Revalidate before paid review, after review and immediately before durable submission as appropriate. Borrowed or stale proof cannot authorize another dossier/order. Preserve existing intent/client-order-reference algorithms and ledger ownership.

Held/pending exclusion and final BUY rechecks must run in the new mode, not only when the old event policy reports a nonzero activation. Any positive holding, including dust, blocks an add-on. Unresolved, stale, missing or incoherent broker/order state is not flatness. Daily limits, reservations, exposure, quantity and funding still count all operational history.

The exact-dossier review reader must recognize both modern decision outcomes and historical action-only BUY/HOLD completions. HOLD/disagreement cannot be erased by later reconciliation/retry markers. Relevant unreadable/malformed history fails closed for entry/review reuse; it must not return not-reviewed on read failure. Hashless reviews remain preserved and explicitly unattributable, never fabricated links or blanket symbol exclusions.

The existing narrow retry exception remains: durable dual approval plus linked allowlisted deterministic pre-submission rejection, complete proof and no submission-started/uncertain/fill state. An orphan retry marker does not reopen a dossier. Independent authoritative earnings/setup rejection history remains enforced; it is not the event/allowance machinery being removed.

Expiry, pending-order reconciliation, protective exits, position protection and fills run before new-entry mode rejection and remain functional under corrupt/unsupported mode and compatible rollback.

## 7. Forward-only policy retirement, not a reset

Proposed compatibility version: 3, mode `exact_document_research_dedup`. This version describes a one-time deployment transition; it does not introduce new event identities or allowance generations.

Retain all old activations, identities, aliases, grants, missing-history records, clearances, candidates, reviews, intents, orders, fills and protection history unchanged. Validate retained history using its historical schema and authenticated prefixes; old event spending is historical, not new research admission authority. No legacy grant/admin path may authorize new-mode entry.

Append one explicitly approved root-bound transition activation to the canonical existing policy stream. The manifest binds the validated predecessor policy/activation identity, old policy prefix, exact registered-stream prefix counts/digests, source/rule version, new mode and historical interpretation. Only the known valid legacy predecessor or activated v1/v2 predecessor can transition. Reject unknown/malformed predecessor chains, version regression, divergent duplicates or a second reset. A no-activation root requires an explicit transition too; do not silently enter version 0.

Verify the exact approved manifest under entry and canonical storage writer locks, then append atomically. Exact same-payload reapplication is idempotent. Register the new research-memory stream before manifest preparation; its empty/nonempty prefix is explicit. Concurrent changes invalidate preparation and require a fresh proposal/approval, not a watermark bypass.

Current `opportunity_cutover` assumes one activation and refuses already-activated roots. Implement explicit version dispatch and a dedicated replacement transition path; merely raising `SUPPORTED_POLICY_VERSION` or invoking the old activation command is insufficient.

Read back the exact transition plus unchanged predecessor prefixes in SQLite and the JSONL projections before claiming activation. New-mode candidate/review/attempt readers reject stale old workers/candidates for new admission; operational reconciliation continues to read all history. Old cached candidates are not silently promoted. A compatible rollback blocks v3 new entry while maintaining protection and reconciliation. Never restore an older ledger or delete activation to make old code enter.

## 8. Source boundaries

- `alpha_radar.py`: remove event admission/reopening checks and formal bindings; coordinate discovery, synthesis, intake, append, normal reuse and failure fallback; preserve source receipts and ordinary candidate validation.
- New small research-memory module: deterministic keys, strict completed-result schemas, validated lookup, cooldown and idempotent append. Keep this separate from broker/order authority.
- `retained_article.py`, existing complete-source capture utilities and immutable capture publisher: expose event-independent durable retention; avoid duplicating capture formats unnecessarily.
- `acquisition_research.py`: remove blanket admission authority; optional private observations remain non-authoritative.
- `autotrader.py`, `entry_eligibility.py`, `candidate_retry.py`, independent earnings spending: detach independent safety checks from event policy activation and preserve exact-attempt/review semantics.
- `opportunity_activation.py`, historical state readers, transition administration and canonical storage stream registration: support a strictly validated one-time retirement transition without rewriting history. Historical readers may remain; event resolution/admin paths leave the active new-mode hot path.
- Sanitized reporting: distinguish duplicate work skipped, completed result reused, fresh research qualified, ordinary policy/evidence rejection and infrastructure failure. Never expose document contents, raw private paths, account IDs, broker IDs or private reviews.

No Hermes configuration, gateway change, provider/key addition or scheduler-cadence change belongs to this feature.

## 9. Acceptance and tests

Write failing tests before runtime behavior changes; use isolated fixtures, never production state as writable test data.

Research cases: identical content under a changed acquisition/check timestamp still matches; changed complete bytes miss; excerpt-only match cannot hit; provider-representation mismatch cannot hit; shared document plus a new second document proceeds; same content under another issuer does not cross-match; rule-version change misses; corrupt/missing result/capture never counts as success; original TTL is not extended; transient failures permit retry after cooldown and alternative sources continue; duplicate first candidate advances the shortlist without added discovery or budget; unknown formal event identity reaches normal synthesis when ordinary evidence gates pass; genuine evidence/freshness/earnings failures remain rejected.

Routing cases: earnings with historical M&A language is not diverted; acquisitions reach ordinary analysis without granting automatic trade authority; direct, focused, recovery and rescue paths obey the same contract.

Review/entry cases: modern HOLD/disagreement and historical action-only completions block the exact dossier; marker and regenerated wrapper do not erase completion; history-read failure blocks review/entry reuse; narrow proven pre-submission retry is retained; missing proof/submission-started/unknown/partial fill deny retry; dust, pending entry, stale proof, altered dossier and fill-during-review prevent downstream action at the applicable boundary. Preserve independent earnings/setup rejection.

Transition cases: valid legacy/v1/v2 history, exact idempotent replay, wrong root/digest, stale watermark, modified historical prefix, divergent transition, unsupported future version, stale worker and SQLite/projection disagreement. Rejected transitions append no partial authority. Old lifecycle/protection survives both new-mode entry rejection and compatible rollback.

Execution cases: dual-model consensus, exact approved order proof, final recheck, daily submission counts, idempotent lost-ack reconciliation, unchanged order refs, no duplicate fill accounting and all existing risk limits.

Run focused, full isolated and raw/offline release gates through the project's existing proven test harness; report actual exits/counts and fixture provenance. Independently review changes and rehearse transition/rollback against a disposable authenticated retained-history copy.

## 10. Rollout and success evidence

After written-spec approval, produce a separate implementation plan and obtain execution-method selection. Implementation stays isolated from deployed source/state. Before production, obtain exact-cutover approval, pause only affected entry/research writers, drain workers, preserve job settings, read broker state without modifying orders, prepare/approve the current manifest, promote reviewed source and activate/read back the exact transition. Protection continues. Resume exactly the affected jobs and verify settings.

Do not run a separate live research/broker-execution experiment just to prove the cache. First prove functional safety with offline fixtures/replay. After separately approved activation, use normal scheduled scans for operational evidence.

Measure discovery lead appearances separately from exact evidence-bundle repeats, duplicate document stages avoided, synthesis calls avoided, fresh qualified dossiers, final rejections and source/provider failures. Compare original research durations and calls against offline replay where possible; report budget p50/p95 only from actual observations. A healthy scan does not require a candidate; cache hit counts do not prove broader coverage or profitability.

Report implementation, tests, deployment, activation and scheduled-run evidence as distinct states. No claim that repeated tickers or all same-event research are eliminated. No guarantee of qualification or returns.
