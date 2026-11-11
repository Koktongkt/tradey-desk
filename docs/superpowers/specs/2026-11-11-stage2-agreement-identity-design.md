# Stage 2: acquisition and contract event identity

Status: written specification for owner review, not implementation or deployment approval.
Baseline: 0bdf9572653fa98469c3f7aa294601b9676dd4e9.
Authority: owner approved the acquisitions/contracts contract design in Telegram and requested implementation. The staged review process still requires this written specification and its subsequent implementation plan to be reviewed before product edits.
Parent: docs/superpowers/specs/2026-11-10-radar-identity-handoff-design.md.

## 1. Intent, boundaries and alternatives

Identify supported acquisition and contract events from authenticated primary evidence so genuinely different events can reach the existing investment pipeline. Do not target a candidate count or trade count. Identity verification is not investment qualification, review approval or execution permission.

Implement only acquisitions and contracts. Regulatory events, standalone guidance, discovery-model availability, general publisher recovery and earnings-coverage expansion are separate work. MNDO and WYFI are provisional source-readiness examples, not accepted identities or opportunities.

Use typed, narrow source adapters and a shared versioned identity boundary. Reject a generic headline/prose/URL fingerprint: it would create new events from paraphrases and updates. Reject delivering all catalyst families together: it enlarges the unproven compatibility boundary without addressing this increment's purpose.

### Standing invariants

- Preserve paper-only mode, enabled state, economic limits, independent reviewers, earnings blackout, source quality/freshness, position/pending exclusions, idempotency, attached protections and deterministic execution validation.
- Preserve policy v2's prospective baseline, existing spent generations and manual-only reopening. No policy reset, migration, legacy binding import, historical rewrite or administrative grant is authorized.
- No Hermes configuration, gateway restart, provider/key change, cron change or larger research budget.
- No broker access in identity acquisition/resolution; no production operational storage in tests or source probes.
- Hashes bind bytes/normalized facts; they do not authenticate a publisher or prove event semantics.

## 2. Trust and evidence contracts

Continue separating bounded investment articles from full identity captures. Reuse the existing trusted SEC exact-URL transport and durable evidence publication mechanics, without promoting a model/provider dictionary into an acquisition-owned capture.

Initial automatic source scope is SEC archive HTML/XHTML plus literal, authenticated filing-to-agreement/exhibit relationships. Retain requested/returned locators, full raw source digest, complete bytes, media and acquisition time under the existing capture contract. Bind the subject issuer via authenticated registrant facts or an existing validated issuer binding; the accession prefix is not registrant identity. A counterparty's ticker mentioned in a document does not establish the subject issuer.

Follow only admissible literal links within bounded acquisition. Do not guess exhibit names or treat a general SEC filing or exhibit number as an agreement identity. A filing may contain earnings, acquisition and contract events simultaneously.

An agreement fact set must retain exact supporting document references and bounded source spans for: subject issuer, agreement/award identity, parties and roles, and the relationship between the observed document and underlying agreement. Source spans must match the retained bytes through the specified decoding/normalization, not arbitrary body substrings selected by the model. Missing, contradictory, multiple or ambiguous subjects fail closed.

Issuer websites, agency award APIs and other primary formats are not implicitly enabled. A later adapter requires a separately reviewed publisher/issuer association, stable-key contract and retained real evidence. Secondary reporting may support investment analysis but cannot supply identity authority.

## 3. Stable keys and continuity

### Common identity rule

Use a versioned, family-tagged key over subject issuer CIK plus a validated canonical agreement root. Exclude acquisition time, publication date, lifecycle state, article URL, price, source-set digest, prose and model output. Preserve existing earnings key bytes exactly.

The canonical root has one of two tagged forms:

1. `authority_identifier`: an explicit stable agreement/award identifier with its authoritative namespace. Preserve identifier lexical meaning; do not case-fold, strip punctuation or merge identifiers without an authority-specific rule.
2. `reviewed_root`: the canonical original agreement reference established through the existing explicitly reviewed binding authority. A local URL or SEC document ID alone cannot establish originality or deduplicate republications. This form requires a genuine approved binding; the new resolver must not manufacture or automatically register one.

Automatic admission requires the source-specific adapter to prove the first form and its association with the subject issuer. If a transaction has no admissible stable identifier, retain its evidence and report an identity coverage limitation; an explicit reviewed root can be used only when separately authorized through the existing administrative process. This limitation is intentional, not evidence of broad acquisition coverage.

Party names, agreement title and agreement date are corroborating facts, not sufficient unique keys. Two agreements between the same parties on the same day must not collapse. Conversely, distinct identifiers do not prove distinct events when primary evidence says one supersedes or amends the other. An unresolved predecessor/successor relationship blocks new-event admission.

### Acquisitions

Bind the authenticated transaction/agreement root, parties and roles to the subject issuer. Signing, shareholder/regulatory steps, amended terms, closing and termination reference the same root. A new filing, renamed transaction, amended-and-restated agreement or different publication date cannot independently create a new allowance.

A genuinely separate acquisition requires evidence of an independent agreement identity and no unresolved continuity with a prior event. Asset purchases, mergers and tender offers are admitted only when the implemented adapter supports their exact evidence contract; their labels alone do not establish a root.

### Contracts

Bind an authoritative agreement/award identifier and namespace to the subject issuer and counterparty/awarding authority. Announcement, amendment, extension, exercised option and performance/delivery milestone reference the original agreement root.

Do not automatically treat task orders, call-offs, purchase orders or renewals as separate reviewable events. Admit them as separate only when the source-specific contract proves an independent underlying award/agreement and resolves the parent relationship. Otherwise preserve parent continuity or refuse ambiguity. A newly reported value or revenue estimate does not establish a new contract.

### Alias and conflict behavior

New document locators are observations of a root, not root aliases by default. Admit alias/update relationships only from authenticated explicit references or validated reviewed bindings. Relations must be deterministic, order-independent and issuer-consistent. Alias collisions, competing roots, conflicting parties or unresolved replacement relations return conflict/unknown rather than choosing whichever document arrived first. Updating observations cannot rewrite a spent allowance or rebind a dossier.

Lifecycle state is evidence, not permission. Completion or termination may resolve identity while the unchanged investment gates still reject the setup. This increment does not implement lifecycle-driven reopening or automatic trade actions.

## 4. Representation and consumer closure

Add a strict non-earnings identity representation with an explicit new version, closed fields and family-specific validation; do not overload earnings `period` with an agreement string. The implementation plan must freeze its exact wire schema, key serialization and reference grammar before product edits. Preserve accepted v1/v2 earnings round trips and event IDs. Reject unknown versions/fields, malformed roots, contradictory issuer fields and unsupported families.

Separate event identity fields from supporting observations and lifecycle facts. Validate recomputed key, admissible root type and evidence-reference consistency at the shared loader boundary. Shape-valid candidate JSON is never authority; preserve acquisition ownership, policy authority and retained-evidence checks along the whole call chain.

The observed strict consumers include:

- opportunity_identity.py: EventResolution, resolve_event, candidate_identity, _load_binding, known-binding merges and evidence retention.
- alpha_radar.py: acquisition/policy precheck, trusted handoff, candidate preparation, reuse and saved-dossier validation.
- opportunity_state.py: canonical-state reconstruction, event indexing, policy decisions and dossier/allowance validation.
- opportunity_admin.py: existing reviewed binding validation; no new automatic authority producer.
- policy_diagnostics.py and existing monitoring/CLI consumers: family/status classification and truthful error precedence.
- earnings_identity_acquisition.py, earnings_identity_evidence.py and earnings_identity_resolution.py: preserve earnings behavior; share only necessary acquisition primitives.

Inventory additional transitive serializers, dossier readers and runtime consumers before fixing the implementation allowlist. An unchanged wrapper does not prove its shared loader supports the new family. Prefer dedicated pure agreement adapters over expanding the Radar monolith. No new global journal stream or database schema is intended. Existing persisted resolution payloads and their strict readers still form a compatibility boundary.

## 5. Acquisition bounds, orchestration and diagnostics

Use the existing inherited absolute research deadline, attempt caps, candidate shortlist limit, exact-URL deduplication and source-capture bounds. Current identity acquisition has at most 32 cached URLs, a 15-second per-fetch ceiling, a 2,000,000-byte raw-source bound and 3,000,000-byte capture bound. Stage 2 must not increase these or restart a parent's elapsed budget. Agreement and earnings link traversal share the same invocation budget rather than each receiving a new allowance.

Fetch only when the candidate needs identity evidence. Do not invoke a model to classify or construct an authoritative key. Proven spent events stop before expensive synthesis. Unknown events continue only within the existing shortlist and budget; no sixth candidate, rediscovery loop or extra broker polling.

Retain captures durably before publishing dossier/policy references. Preserve incomplete-body, redirect, transport, forbidden, capacity and deadline reasons. Required contradictory or unavailable primary evidence cannot simply be removed to obtain admission.

Use the existing private research-policy diagnostics, with bounded family/adapter/status/subreason fields. Distinguish unsupported family, missing stable identifier, unresolved continuity, primary conflict, source failure, spent event and investment rejection. Public output retains the existing sanitized token contract unless the reviewed plan demonstrates a necessary compatible addition. No URLs, raw source spans, prompts, arbitrary exception text or secrets in public diagnostics. Best-effort diagnostic failure must not change the primary result.

## 6. Source-readiness prerequisite

Before implementing an automatic adapter, retain authentic source-only positive examples and near-negative examples that exercise its exact identifier and continuity contract. Demonstrate the root's independent authority, issuer association and producer-to-consumer path. Synthetic fixtures may test an approved contract but cannot invent a production identifier or authority lookup.

Attempt to source-check the MNDO/WYFI examples in an isolated research-only harness. If they lack authoritative identifiers or accessible complete evidence, record those precise misses and use other authentic examples for supported adapter readiness. Do not promise that those specific candidates will pass.

If no authentic acquisition or contract example satisfies the approved key contract, report that family's readiness blocker and request the smallest specific source-contract amendment. Do not silently replace the root with a hash of prose/date/parties or claim completion from blanket rejection. Acceptance requires a real positive for each delivered automatic family.

## 7. Verification and acceptance

Observe behavioral RED before product changes and then exercise the real affected path: trusted acquisition -> full capture -> fact/relationship validation -> identity loader -> policy decision -> immutable dossier binding -> existing synthesis/qualification boundary. Mock investment judgment as necessary; do not mock away the identity proof under test.

Required matrix:

- One authentic supported acquisition and one authentic supported contract resolve; synthetic orchestration fixtures reach the existing qualification boundary with an unspent event.
- A genuinely independent agreement for the same issuer has a different event ID and can pass identity admission.
- Syndicated/reposted documents and new locators for a supported same event retain its identity.
- Signing/amendment/approval/completion/termination; contract extension/option/milestone; amended-and-restated and predecessor/successor histories do not create automatic reopening.
- Separate same-party/same-date agreements do not collapse; parent/task-order ambiguity cannot mint new events.
- Wrong issuer/roles, conflicting authoritative documents, alias collisions, multiple agreement subjects, misleading exhibit numbers and missing stable identifiers fail closed.
- Forged model captures/keys/relations, redirect mismatch, truncated bytes, bad media/digests, failed durable publication, capacity and deadline exhaustion fail closed with truthful diagnostics.
- Existing spent event, held issuer, pending entry, baseline mismatch and manual reopening retain their original decisions.
- Freeze old v1/v2 earnings fixtures independently; verify old IDs, serialization, state replay, dossier validation and administrative binding behavior without regenerating expected records using new code.
- Exercise all actual strict consumers on mixed earnings/acquisition/contract records; retain malformed/unsupported-version negatives.
- Run established wrapped full and raw test suites with explicit skip inventory and default-on external-model launch guards. Prove production operational storage isolation; do not use real journals as fixtures.

Independent fresh SPEC and QUALITY reviews must bind the same frozen final source/tests and actual test receipts. Resolve findings before committing the accepted source package. Report genuine test exits, logs and omissions; do not substitute a passing wrapper or reviewer summary for executed proof.

The implementation plan must bound live acquisition attempts and provide no-broker/no-production-storage controls before running probes. A successful mock is not current-host source coverage; successful identity is not a qualified trade.

## 8. Release and rollback boundary

Keep the new code on an isolated development branch until acceptance. Documentation approval, source acceptance, integration, deployment and operational activation are distinct claims. No production cutover is authorized by this specification.

Once new-version resolutions are persisted, the current earnings-only loader cannot be assumed to read the resulting state. Therefore an old-binary rollback after such writes is unsafe unless a compatible reader is explicitly delivered and tested. Never repair rollback by deleting new policy rows or restoring an old database over intervening activity. A deployment plan must resolve forward-compatible rollback or a fail-closed recovery procedure before production enrollment. This limitation must remain visible even if no SQL schema changes are necessary.

## 9. Next review gate

Owner reviews this written specification. On approval, create the implementation plan, including source-readiness checks, the exact new wire contract, bounded probes, TDD tasks, consumer closure and independent acceptance. Obtain written-plan approval and execution-method selection before product edits. Preserve the already approved scope and standing safeguards without treating them as deployment permission.
