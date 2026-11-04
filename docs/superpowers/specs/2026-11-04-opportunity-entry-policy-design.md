# Stable opportunity identity and no-add-on entry policy

Status: DESIGN FOR USER REVIEW — no implementation, activation or publication.
Base: `67d372f8099fb05fab33b9fc537eaa986abb2f95`.

## 1. Intent and approved scope

Prevent repeated BUY consideration of an unchanged company event after a completed HOLD/disagreement, and prevent a new BUY for a symbol already held or carrying an unresolved entry obligation. Radar must skip ineligible opportunities and continue its existing research shortlist. Keep companies observable rather than permanently banning their tickers.

The user approved the scope in chat. This document makes the architectural choices and conservative limitations explicit for written review. Approval of this document permits writing the implementation plan; it does not itself authorize deployment or a broker mutation.

Preserve the existing discovery/evidence/synthesis/enrichment/intake/review/execution sequence, independent reviewers, paper-only mandate, protective exits, reconciliation, exact order/fill ownership, daily submissions including pending/unknown, pending capacity, risk/exposure/quote/earnings gates and source requirements. Do not change cadence, providers, model choices, time allowances, or broker call budgets. No add-on strategy is introduced.

## 2. Current failure and alternatives

A retained operational audit demonstrated multiple regenerated dossiers for unchanged report evidence, completed dissent, and subsequent rediscovery after entry. Specific issuers, trade/review details and historical binding manifests remain in private diagnostics, not this publishable design. Different dossier hashes do not establish different economic opportunities: current hashes include timestamps and regenerated content.

Current exact-dossier spending and narrow retry safeguards remain useful. They must not be replaced by a ticker cooldown. Current position sizing uses remaining dollar headroom and therefore is not a no-add-on rule. Broker positions and open orders already arrive at initial snapshot and final broker-review boundaries.

Alternatives:
- **Recommended:** deterministic, provenance-backed event resolution plus a local review-allowance index and shared BUY eligibility checks.
- Exact source-set deduplication alone: inexpensive but a new URL or omitted source can evade it; useful only as a lookup aid.
- Ticker cooldown or model/embedding similarity: the former blocks unrelated opportunities, while the latter is not dependable authorization and adds inference/cost. Neither is the first release.

## 3. Separate identities and decisions

### 3.1 Event identity

Keep existing dossier/proposal/evidence hashes for integrity and exact execution binding. Add a versioned event ID derived only from a validated event descriptor, never model-supplied IDs or prose hashes.

An event descriptor records verified issuer identity, event family, verified primary document anchors, supported event/period discriminators, resolution version and evidence references. SEC CIK is preferred when proven; do not guess issuer identity from a ticker substring or silently normalize malformed identifiers.

A SEC accession/document is a document identity, not automatic proof that every economic event in the filing is identical. Earnings additionally bind the supported reporting period/release relationship. Separate events in one filing must not collapse. Different filings, amendments or URLs are not automatically new economic events.

First-release automated earnings resolution requires mutually consistent issuer/primary-document/report-period support in retained acquisition evidence. A period is accepted from a defined structured primary field or an exact source-supported quarter/year or period-end extraction, not an unconstrained model assertion. Preserve original text, locations and precision used by that extraction. Conflicting periods resolve to conflict. Event-specific resolvers for other announcements can be admitted only with equally explicit, tested primary identifiers; until present, such cases require an evidence-backed explicit resolution record rather than a generic title/date heuristic.

This deliberately limits automatic coverage: an unresolved event is not BUY-eligible. It may consume bounded existing retrieval to seek resolution and remain observable; the system does not invent an identity, suppress the entire issuer or silently assume it is unspent. This coverage tradeoff is part of the requested written approval.

Use the actual historical report as the earnings catalyst anchor. Upcoming `earnings_event_at` remains blackout data; `planned_exit_at`, new research dates and next-report estimates never identify the past event.

### 3.2 Evidence observations and aliases

Retain the trusted receipt bindings currently removed before candidate persistence: requested/returned URL, publication value with precision/basis, content digest, retained representation reference and resolver-support references. Do not copy entire articles into multiple streams.

Attach issuer releases, filings and secondary coverage to an event through validated aliases. Original URLs remain intact. No generic query stripping or fuzzy title merging. New source membership, headline, checked time or content digest is an observation, not permission to review again. A content digest detects change; it does not establish materiality.

An early unchanged decision requires sufficient proof. Known immutable filing identity or a previously verified unchanged observation can support an early skip; a mutable issuer URL alone cannot prove unchanged contents. Let bounded existing retrieval inspect ambiguous/mixed/new evidence before the authoritative event decision. Do not discard a genuine new event merely because its bundle also cites an old report.

### 3.3 Review allowance

Maintain an allowance linked to event, evidence resolution and any explicitly authorized reopening generation. Completed substantive HOLD/disagreement spends that allowance across dossiers, clocks, prices, rewritten theses and setup labels. Later reconciliation/retry markers or a later approval cannot erase earlier dissent for that same allowance.

A dual approval is bound to its exact current attempt/dossier/proposal and may complete that attempt's normal validation/submission. The post-review check must not block its own current approval merely because the approval was just persisted. Other attempts cannot inherit it. Existing `candidate_retry.pre_submission_retryable` remains the sole narrow exception for a previously approved exact dossier with every required linked pre-submission rejection and marker; do not broaden it to a regenerated dossier.

A missing/empty reviewer response or a reconciliation-only marker does not spend a previously untouched allowance. Neither grants a new allowance after an earlier completed review.

## 4. Reopening: first-release policy

No generic automatic semantic-materiality detector and no automatic conversion of reviewer free text into conditions.

A spent event can receive one new generation through either:
1. An explicit evidence-backed reopening authorization referencing the old allowance, exact verified observation and changed fact; or
2. A previously approved structured condition becoming satisfied by its specified authoritative observation.

A structured condition specifies event/allowance, metric, source/field, comparison, threshold, units, baseline, freshness, expiry and one-shot consumption. Unsupported metrics/sources and ambiguous values remain unsatisfied. Initial release has no invented default numerical materiality thresholds and no automatically generated conditions. Activation can start with no conditions; same-event automatic reopening then remains disabled until a condition is expressly approved.

An amended filing or changed release triggers inspection, not automatic reopening. New article, paraphrase, passage of time, a new next-report estimate, or price movement alone does not qualify. Price can count only under an expressly authorized condition. A new verified reporting period is a distinct event, not reopening of the old one. A different chart/setup label cannot erase an unresolved fundamental objection; carry relevant historical objections into the new assessment without exposing one current reviewer's answer to the other.

Monitoring and fresh event discovery continue. No fixed TTL silently deletes dissent. Exact closure/flatness can remove a position exclusion but cannot erase opportunity spending.

## 5. No-additional-BUY rule

For a NEW BUY, block the symbol if there is any positive held quantity, including fractional dust, or an unresolved/pending entry obligation. Remaining dollars under the position cap, a new day, a new event or an approved retry cannot override this. No add-ons or averaging down.

This rule does not cancel an already-authorized parent, stop its remaining fill, change its exits or adopt an external holding. Pending readback, expiry, fill ingestion, managed exits and protective reconciliation retain their existing precedence before candidate entry decisions. SELL/protection follows existing ownership/quantity rules, not a blanket ticker exclusion.

### 5.1 Early Radar evidence

Build one coherent run-local context from non-repairing canonical readers: confirmed identity-linked entry/exit state, unresolved saved intents/latest lifecycle state and existing baseline exclusions. Positive known remaining shares or pending entry can cheaply exclude a symbol. Missing/old local positive evidence is not proof of broker flatness. Historical closed parents must not create permanent exclusions.

Corrupt/incoherent durable policy state is a typed state failure, not an empty eligibility set or permission to try fallback. Mere lack of fresh broker observations does not create a research-wide ban: preliminary research can proceed, but it cannot assert verified flatness or authorize BUY. Do not call reconciliation/qualification from Radar; those paths can perform broker lookups and writes. No new Radar broker polling.

### 5.2 Authoritative entry boundaries

Reuse the existing initial snapshot and final broker-review reads, including complete positions and open orders. Strengthen position normalization so malformed unwrapped responses cannot become `[]`. Explicit successful empty positions is distinct from missing/error/unsupported shape. Validate every row: supported symbol/side, finite positive Decimal quantity, no bool/null/NaN/infinity, no duplicate/conflicting positions or unsupported short state. Do not erase dust through epsilon, value-based sizing or netting. Preserve existing strict zero-row/lineage contracts.

Use the existing exact saved-parent pending proof, local intent obligations and reconciliation checks. Same-symbol zero-fill, partial-fill, submission-started and submission-unknown entries block NEW BUY. Terminal status alone does not prove flatness after a fill. Other-symbol, exact owned zero-fill parents may still use existing qualified capacity/reservation semantics. Protective SELL children are not standalone BUY entries; unlinked/manual orders continue to fail the existing authority policy.

Make broker completeness/read-window provenance broker-owned and propagate it through `authoritative_bundle`; candidate/model fields cannot provide it. Add independently measured aware read-start/read-end and monotonic duration. Proposed new entry-evidence bounds are **120 seconds maximum age from read start, 120 seconds maximum read duration, and no future/naive timestamps accepted**. These are separate entry-evidence bounds, not substitutes for the existing 120-second quote-age check or extra broker time. They need explicit written approval here and validation in offline boundary tests; no live latency sufficiency is claimed.

Evaluate the shared rule before sizing/review, in direct deterministic validation/pre/post-review wrappers, against the final fresh snapshot/proof, and immediately before intent persistence. Revalidate state binding and bounded age under the existing entry lock. If evidence is stale, changes or requires repair, abort the new attempt rather than adding fetch/retry loops. Do not use a snapshot hash as proof of freshness or treat repeated exact-parent reads over old positions as a refreshed portfolio.

Residual limitation: broker reads are not atomic and the local lock does not lock manual/external account writers. Own same-symbol pending exclusion and final fresh checks address owned races, but a later external fill can still race submission. Do not claim absolute broker-side exclusion; never compensate with an unapproved extra call/cancel or weaker ownership rules.

## 6. Shared policy flow and outcomes

Keep issuer/event eligibility separate from position eligibility; both must pass where their required evidence is available.

Radar:
1. Run the existing one bounded discovery. Give it only bounded exclusion hints; prompts are not enforcement.
2. Before focused work, skip proved spent unchanged anchors and known held/pending symbols; record candidate-specific policy reasons.
3. Re-resolve accepted evidence before expensive synthesis/rescue where possible. Unknown/mixed evidence can use the remaining existing resolution allowance.
4. Recheck before synthesis, shared intake and final append; if local state advanced, reload the context and reassess, not silently trust the start-of-run cache.
5. Apply the same policy in `_select_fresh_candidate`, reusable/fresh helpers and error fallback, with explicit root-scoped state. Preserve existing freshness and strict retry requirements. Do not broaden legacy timestamp-based reuse rules as an incidental cleanup.
6. A candidate-specific spent/held/pending/unresolved-identity decision continues the shortlist. No deadline resets, sixth candidate, rediscovery loop or expanded provider calls. Preserve original failures separately from policy skips.
7. A healthy pool exhausted by policy returns `DECISION skipped no_new_eligible_opportunity` with a normal exit and explicit audit classification, not a provider failure. Add corresponding `run_cycle` notification/audit handling. No uninitialized candidate fall-through. Genuine state corruption, retrieval or timeouts retain typed failure outcomes.

Autotrader:
- Keep lifecycle/protection first and latest-candidate consumption; this change does not start scanning cached candidates or recursive research from inside execution.
- Before paid reviews, require current event allowance and authoritative initial BUY eligibility.
- After review, respect the current attempt's exact approval capability; HOLD/disagreement cannot be re-entered with a new hash.
- Recheck fresh broker truth/local proof/policy before intent. A policy-blocked attempt ends normally with its deterministic blocker/skip; the next Radar run can advance research. A completed HOLD does not immediately launch a second trade-review loop.
- Keep all existing daily/risk/source/earnings/consensus/idempotency/readback controls, submission-unknown obligations and narrow legitimate retry proof.

Proposed normalized candidate reasons: `unchanged_opportunity`, `opportunity_identity_unknown`, `opportunity_identity_conflict`, `position_already_held`, and existing `same_symbol_pending_entry`. Structural state/read/provenance/freshness failures remain typed unknown/state-unavailable blockers and are not added to the market-condition retry allowlist. Unknown/corrupt state must never fall through to main or fallback reuse as eligible.

## 7. Storage, concurrency and historical activation

Use the existing authoritative SQLite/JSONL-compatible ledger API. Add one private canonical stream, `private/opportunity_policy.jsonl`, to store versioned identity resolutions, aliases, explicit reopening authorizations/condition consumption and activation provenance. Existing candidate/review/order/fill streams remain authoritative for their existing facts. New candidates carry trusted event/allowance links before their integrity hash is computed. Never rewrite old candidates, hashes, reviews or fills.

Initially build local indexed dictionaries once from a coherent read-only ledger snapshot over relevant streams; lookup is local and does not require a new model/network call. No vector database, external service or second writable state database. A later persisted performance index is optional, rebuildable, root/version/watermark-bound and cannot replace ledger truth. Do not add it before measurement justifies it.

Check source watermarks again at safety boundaries. The existing entry lock serializes participating execution/reopening writers. Do not hold it during Radar network/model work or add an unreviewed new lock order. A durable review already spends the linked allowance even if an optional index update crashes. Rebuild or block before any renewed review. New policy writes use existing append durability/isolation; failed acknowledgement never means the opportunity is fresh. Missing activation/binding coverage for historical reviewed candidates is not a clean install.

Before activation, run a read-only migration audit over retained reviewed/purchased candidates. Produce a versioned manifest with exact source row identities/digests, verified resolutions and unresolved cases. Bind the privately audited repeated-report group explicitly to its supported historical report event and existing review rows; earliest substantive dissent remains spent despite later approval/fill. Keep actual issuer, row and trade identifiers in a private deployment manifest, not source documentation or public fixtures. Missing historical representation hashes remain unknown—never fabricate them from today's cache. Other historical bindings need the same evidence standard; unresolved history must not be silently dropped. Any ambiguous retained event for an issuer remains unresolved for prospective matching until evidence-backed resolution, not an automatic issuer-wide ban.

Activation is explicit, idempotent and append-only after written design/plan approval, tested implementation, independent review and separate deployment approval. It adds policy records, not fabricated trades, order operations or live-account adoption. Include the new canonical stream and any absent sidecars in the operational isolation registry. A proposed rollback must not merely deploy old permissive code while leaving new unresolved obligations; keep new BUY disabled if the old reader cannot enforce activated policy, while preserving protection/reconciliation. Define and rehearse that source/activation rollback in the later implementation plan before deployment.

## 8. Code ownership and acceptance

Expected seams: a small pure opportunity/BUY-policy module, provenance-backed resolver helpers, `alpha_radar.py`, `autotrader.py`, strict `broker_mcp_bridge.py` normalization/provenance, existing storage registry, and `run_cycle.py` outcome handling. Integrate with rather than replace `candidate_retry`, `earnings_spending`, `pending_policy`, reconciliation and lineage. No unrelated refactor, model/provider switch or broad core/Hermes edit.

Required RED/GREEN tests and review evidence:
- Synthetic repeated-report instances resolve to one supported event/allowance; new prose/time/price/setup/secondary URL/body digest does not reopen it. Separate report periods and same-filing distinct events do not collapse. Replay any real incident only from private authenticated evidence outside publishable fixtures.
- Unknown/conflicting identity and unsupported event families never fabricate IDs; retrieval can resolve them within the same deadline. Previous versus upcoming earnings/exit anchors remain distinct.
- Original HOLD/disagreement survives later markers/approvals; the current approved attempt can submit exactly its authorized payload; strict exact-dossier safe retry remains intact and is overridden by held/pending.
- Spent first candidate proceeds to an eligible second candidate without synthesis/review for a proved repeat; all-skipped yields the defined normal result; ambiguity/state errors cannot be laundered through reuse/fallback or an uninitialized return.
- New issuer or new verified event still faces every normal source/freshness/earnings/risk/consensus gate. Unauthorized/free-text reopening, stale/wrong-unit observations and generation replay fail closed.
- Any positive shares, fractional dust, zero/missing market value and pending/unknown/partial entry block new BUY across every route. Flat complete state permits normal consideration. Malformed envelope and unwrapped positions cannot become flat.
- Stale/future/naive timestamps, overlong reads, changed proof/state and fill-between-read cases block before intent; quote freshness alone is insufficient. No new broker calls or hidden retries.
- Existing protective SELLs, reconciliation, expiry, fill journaling and authorized pending-parent continuation still execute, with exact ownership and no ticker-only adoption.
- Crash after review append, concurrent research/review, stream/index recovery, idempotent migration/condition consumption, database-present fixtures and root isolation remain fail closed and private.
- Focused, fast, scenario, full and raw gates through the verified offline runtime; full/raw counts agree, no skipped safety regressions, operational bytes/metadata unchanged. Independent frozen-hash review and production-specific verification before any later release.

## 9. Review decisions and next stage

Approve or amend: (a) conservative unresolved-identity coverage limits; (b) no automatic semantic-materiality reopening and no default conditions; (c) the explicit 120-second entry-evidence bounds; (d) no-add-ons with protection/lifecycle preserved; (e) local Radar exclusions versus authoritative execution proof; and (f) historical binding/activation before enforcement.

After written-spec approval, write the implementation plan with exact modules, storage/bootstrap/rollback procedure, test sequence, source ownership and execution-method choice. No runtime implementation has started, no test suite result is claimed for this proposed feature, and production remains on the base commit.
