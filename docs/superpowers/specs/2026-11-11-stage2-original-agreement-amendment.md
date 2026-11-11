# Stage 2 amendment A: authenticated original-agreement roots

Status: written source-contract amendment for owner review, not a tested production capability.
Parent: `2026-11-11-stage2-agreement-identity-design.md`, commit `2b7ce8aaf23eaf340181f4b754e8279c89cc33f9`, SHA-256 `ac2ba1b4aaee1a0c5b03a8d7f6b79a2834c9350f641942c16c5cac1950f1acb5`.
Authority: the owner approved developing this amendment after source readiness failed. Existing native implementation and conditional deployment authority carry forward after written-amendment review; no new operational or administrative authority is created.

## 1. Exact change and retained safeguards

Add a third root kind, `sec_original_agreement`, alongside unchanged `authority_identifier` and separately authorized `reviewed_root`. Supersede the parent section 3 requirement that automatic admission must use an authority-issued identifier, including its contracts-only restriction. Adjust parent sections 6–7 readiness/acceptance accordingly. Preserve all other requirements: existing earnings IDs, baseline/spending/manual reopening, investment and execution gates, trusted complete evidence, bounded resources, independent same-byte SPEC/QUALITY reviews, full/raw compatibility and safe rollback.

A source-bound original agreement can establish a root without a government-style agreement number. A URL, title, parties/date tuple, body digest or model description alone still cannot. This is not an automatic reviewed binding or a reopening mechanism.

## 2. Initial automatic source scope

Support only text-native SEC Form 8-K original disclosures and their literal linked executed definitive agreements, using source-specific structures demonstrated on authentic retained examples before coding. No general model extractor or keyword-only classifier.

- Acquisitions: an authenticated issuer/current-report item explicitly describes entry into a definitive acquisition/merger/purchase agreement and links the executed agreement.
- Contracts: equivalent material definitive commercial-agreement disclosure and linked executed agreement, with explicit counterparty, subject and roles.
- Unsupported automatically: 6-K/20-F/10-K summaries, issuer-site releases, agency APIs, OCR/image-only agreements, completed-acquisition-only descriptions, press releases without agreements, and stand-alone billing/performance/service-order milestones. A subsidiary signatory needs explicit authenticated issuer/subsidiary association.

MNDO/WYFI are not promised positives. This scope is narrower than all acquisitions/contracts; additional source forms require another proven source contract, not generic fallback.

## 3. Required original-root evidence

A complete bundle must establish all five predicates:

1. **Issuer:** context-bound registrant CIK, legal name and symbol from authenticated cover facts or an independently validated issuer binding. Directory association must agree. The accession prefix is not registrant identity; mentioning a counterparty ticker does not bind that issuer.
2. **Original entry:** the admitted report item explicitly describes entering the underlying executed agreement. The disclosed event/entry date and agreement execution/effective-date relationship must agree under the source-specific contract. Publication date cannot supply execution authority. Retain both dates if execution and effectiveness differ; never guess one from the other.
3. **Linked agreement:** authenticated item/exhibit-table association and literal SEC link to this specific agreement. Its operative opening/definitions and execution material establish agreement type, parties, roles and dates. Item 1.01 or an exhibit number alone is insufficient.
4. **Continuity classification:** complete relevant item, exhibit entry and agreement structure distinguish original entry from amendment, restatement, replacement, extension, option exercise or contract/order child. “Entered into” alone is not originality proof. Updates must resolve their predecessor; ambiguous/unrecognized structures remain unknown.
5. **Unambiguous subject:** exactly one supported agreement is selected by the authenticated item-to-exhibit association. Multiple agreements require separate explicit associations; an ambiguous whole-filing subject fails closed. Required unavailable/conflicting documents cannot be discarded.

Every fact/relationship needs acquisition-owned references and reproducible spans in retained complete raw sources through a fixed HTML decoding/normalization contract. Model-authored spans, extracted Markdown, cropped originals and manufactured closing markup cannot satisfy these predicates. Hashes prove integrity, not semantic authenticity.

## 4. Root identity, duplicates and lifecycle

The root's closed identity fields are `kind=sec_original_agreement`, `issuer_cik`, `original_report_document_id` and `original_agreement_document_id`. Use the existing strict SEC document-ID/locator grammar. The event key additionally binds version and family. Exclude execution dates, party text, lifecycle state, article URL, capture time and source digest from the key. Those facts corroborate identity or trigger ambiguity refusal; they do not supply uniqueness.

Document IDs become canonical original anchors only after section 3 is proved. Alternative representations cannot bootstrap another root:

- An update must follow authenticated explicit references back to an established original. Prove the original from retained trusted records or acquire its original bundle within unchanged bounds.
- An amendment encountered first either reconstructs that chain or stays unknown. It cannot use its own accession as a new root.
- Refilings, co-filed copies and republications are observations/aliases only when authenticated explicit references establish continuity. Same text/digest, same parties/date or accession proximity alone is insufficient.
- An 8-K amendment, later periodic filing, secondary article or stand-alone milestone cannot create a first root under this original-8-K contract.
- Signing, amendment, approval, completion and termination remain the same underlying event when continuity is proved; otherwise identity remains unknown. A replacement with unresolved predecessor cannot create an allowance.

Before new-event eligibility, compare the proposed bundle against all validated roots/observations available for that issuer in one coherent policy context, including spent and separately reviewed roots. The implementation must expose that complete comparison set, not only URL-matching bindings. Reconcile duplicates across root kinds before claiming novelty. Derive collision facts from validated retained evidence; shape-valid stored metadata is not source authority. Missing/inaccessible known-root evidence is not proof of independence and remains a typed limitation within the existing budget.

A collision on agreement type/parties/execution relationship requires explicit primary continuity or independence proof. Never merge automatically or mint another root from a mismatch alone. Two agreements between the same parties on the same day may have distinct roots only with explicit evidence of independent subjects and resolved relation to the known event; otherwise refuse ambiguity. Test both the legitimate positive and the conservative negative. This is candidate-local ambiguity handling, not a permanent ticker ban.

Conflicting alias witnesses, competing roots and conflicting issuer/party facts return conflict/unknown independent of source order. No root rewrite, dossier rebinding, allowance migration or administrative grant.

## 5. Consumer closure

The shared loader must recompute the key and strictly validate root shape, version and evidence-reference associations. Shape validation does not replace trusted acquisition or policy authority. Preserve durable retention before publishing references.

Extend the actual policy path as well as parsing: `opportunity_state.candidate_policy` currently permits prospective events only for earnings reasons. A new exact original-agreement reason may enter that path only with the validated source producer and trusted serializer/handoff; an arbitrary caller-supplied reason string cannot confer authority. Exercise registration, persistence/reload, saved-dossier reuse, cross-root-kind continuity and final entry checks on mixed histories. Preserve every existing earnings record/ID and generation-spending rule.

No new global journal stream, baseline migration or automatic reviewed-binding authority is intended. If existing storage cannot retain the required provenance/continuity without such a change, surface that dependency before coding around it.

## 6. Readiness, tests and bounded research

Before runtime edits, retain one authentic original-disclosure-plus-executed-agreement bundle per delivered family, plus an authentic explicit update-to-original chain. Demonstrate deterministic issuer, original subject and relation/span extraction. Historical examples prove parsing, not current trade eligibility. Preserve the failed original-spec evidence; synthetic fixtures cannot invent production authority.

For amendment-readiness only, allow at most four discovery searches and twelve exact public document acquisition attempts, with at most sixteen HTTP requests including redirects, cumulative across helpers. This is a new finite allowance, not repetition until success. Record exact counters/failures. No broker tools, Radar/main run, model/provider subprocess, production storage, broad crawl or evasion of publisher controls. Search/extraction may locate evidence but cannot prove trusted complete bytes.

Runtime bounds remain unchanged: one inherited deadline, shared 32-URL cache, 15-second fetch ceiling, 2,000,000-byte raw source and 3,000,000-byte capture limits. If authentic supported positives cannot be established, report the precise blocker rather than implement blanket rejection or silently expand scope.

Add behavioral RED -> GREEN tests for:

- Original acquisition and contract captures through resolution, policy and immutable dossier registration.
- Same-event new URLs/filings, amendment-first, closing/termination, restatement/replacement and master/order histories: no new allowance from an update.
- Independent same-issuer agreements, including same-party/same-day positive with explicit independence proof; unresolved collisions blocked.
- Cross-root-kind duplicates, spent roots and incomplete known-root evidence: none imply novelty.
- Misleading “entered into” wording, multiple subjects/exhibits, wrong issuer/subsidiary roles, forged captures/spans/reason/root, altered bytes, missing predecessor and alias conflicts.
- Existing earnings compatibility, baseline, manual reopening, held/pending exclusions, deadline/durability and all strict consumers.

Recover missing retained earnings fixtures before final compatibility acceptance. Full/raw tests, production isolation, independent matching-byte SPEC/QUALITY verdicts and compatible rollback remain mandatory. Writing this amendment passes none of those gates.

## 7. Approval and continued execution

Review this written original-root/continuity contract as one amendment. On owner approval, update affected plan tasks and continue under the already selected native implementation and conditional deployment mandate without another general plan-approval round. Stop for demonstrated source/security/contract/release blockers or materially different design changes, not routine task boundaries.

No production-state migration, historical import, operational fence, configuration change or administrative grant is authorized. Publication, deployment, schedule restoration and first substantive scheduled outcome remain separate verified claims.
