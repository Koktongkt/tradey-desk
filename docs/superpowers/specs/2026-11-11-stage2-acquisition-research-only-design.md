# Stage 2 replacement: acquisition research without admission authority

## Status and intent

Proposed written specification following the owner's selection: “Redesign acquisitions as research-only, with explicit reviewed event bindings before any allowance.” This approves the direction, not this previously unseen specification or a live-state operation.

Goal: retain useful acquisition leads and original primary evidence without allowing a legal-prose parser or model to mint a transaction identity, paid-review entitlement or trading allowance. Existing earnings discovery, policy memory, qualification, dual review and execution remain authoritative and unchanged.

## Release boundary

Build this replacement from deployed baseline `0bdf9572653fa98469c3f7aa294601b9676dd4e9`, not the prematurely published automatic-admission branch. Preserve that branch, its dirty repairs, failed reviews and proof privately; do not merge its runtime merely to reuse planning documents. Selectively reuse a source/evidence utility only after its own tests and full replacement review establish necessity and compatibility.

This release delivers **acquisition research leads only**. It does not deliver the explicit-binding authority producer/importer. Until a separately specified, reviewed and approved binding path exists, every acquisition remains ineligible for paid review and entry. This is intentional delivery scope, not a claim that an absent binding producer already works. Commercial contracts, other new event families and automatic acquisition admission are out of scope.

## Data and authority flow

1. Existing bounded discovery may propose an acquisition lead. A headline, model label, URL or agreement title is only a lead—not proof of originality, continuity, parties, economics or investment merit.
2. Use the existing trusted primary-source acquisition/retention boundary and inherited request queue, cache, absolute deadline and byte bounds. Follow literal admissible links only within that same allowance. Missing/inaccessible/oversized/incomplete sources remain typed evidence limitations. Do not fetch a second family-specific batch or manufacture a complete capture from excerpts.
3. Retain a bounded private lead record and its complete admissible primary captures. An observation identifier locates this research artifact only; it is explicitly not an event identity, agreement key or novelty proof.
4. Return a typed research-only result before normal candidate synthesis/qualification, paid reviewers, allowance registration or entry. Acquisition legal-language heuristics may annotate uncertainty for the operator, but no parsing outcome—including “original”—can authorize progression.
5. Existing earnings inputs continue down the unchanged earnings identity and policy path. Mixed/ambiguous acquisition-and-earnings input must not be relabeled to evade the acquisition boundary; independent supported earnings evidence may qualify only under the existing earnings contract.

### Private lead-record contract

Use a closed, versioned record with these fields: `record_type` (`acquisition_research_lead`), `schema_version` (1), `observed_at` (trusted UTC acquisition/run time), `lead_id` (content-addressed observation identifier), `symbol` (discovery hint), `issuer_cik` (authenticated source value or null), `status` (`research_only`), `evidence_status` (closed values `retained`, `partial`, `unavailable`), `capture_refs` (bounded references to verified retained primary captures), and `reason` (closed value `explicit_binding_required`).

The record must not carry `event_id`, `allowance_id`, a verified acquisition identity, an approval flag, model confidence-as-authority or a process-local admission seal. Bounds on symbols, timestamps, capture counts and reference syntax must use existing source contracts. Enforce owner-private/no-follow/no-clobber retained files using the existing evidence mechanism. Lead metadata is not added to the canonical opportunity policy/candidate/review/order streams. Missing lead persistence refuses successful lead publication; it never falls through into ordinary candidate generation. Repeated observations may be deduplicated by their evidence bytes; such deduplication is an observation/storage operation only.

Public diagnostics retain existing sanitized tokens. Keep source URLs, raw captures, legal prose, account identifiers and filesystem paths private. A concise operator-facing outcome may say “acquisition lead retained; explicit event binding required” without claiming qualification.

## Non-bypassable gates

- Research policy, direct event decisions, saved-candidate loading and final entry must refuse unsupported acquisition identities and research-lead records, including fabricated v3 JSON or an existing shape-valid row. A forged record or manual insertion is not explicit reviewed binding authority.
- Acquisition observations must never append automatic `identity_resolution` records, spend or replenish allowances, reopen reviewed events, clear unknown history, change the prospective baseline or reset memory.
- Models cannot generate an approval or convert acquisition evidence into earnings identity. Neither a trusted transport receipt nor exact retained-byte replay supplies missing transaction authority.
- All current account/position/order caps, paper mode, stop/target requirements, timing, source quality and dual-review/execution controls remain unchanged. No configuration toggle may enable the rejected automatic parser in this release.

## Explicit reviewed bindings: required later authority

A later acquisition-admission release must specify and test the actual producer and consumer before implementation. It must identify the reviewer/owner's independent approval of an exact canonical manifest digest and source associations; distinguish original agreement, continuation/alias, amendment/replacement and genuinely independent transaction; compare all validated same-issuer roots including spent and pre-baseline roots; refuse unresolved/contradictory evidence; and preserve all existing allowances and manual-reopening rules.

A file carrying its own approval flag/hash, a parser's verdict, model output or an unauthenticated manually inserted policy row is not that approval. Evidence persistence, binding import and policy activation remain separate exact operations. This research-only release performs none of them for acquisition authority. No live journal migration, new policy activation, historical rewrite or allowance grant is authorized by approving this document.

## Acceptance criteria

1. An authentic acquisition original and closing/amendment chain produce useful private research-only observations with retained admissible sources, never a verified trading event.
2. Every previous review bypass—compound/nominal predecessor relations, source placement, competing role definitions and conditional boilerplate—remains research-only regardless of wording. Correct boilerplate must not prevent evidence retention merely because semantic classification is uncertain.
3. Exercise discovery transport → lead retention/readback → typed research-only result, and separately direct research/event/saved-candidate/final-entry refusal. Assert no paid reviewer/model synthesis call, no allowance/policy/candidate/order append, no broker mutation, and preserved original policy bytes.
4. Fabricated identities, lead records supplied as candidates, attempted family relabeling, unknown capture authority, missing/unsafe/tampered retained files and persistence failure all refuse without authority-bearing side effects.
5. Existing earnings v1/v2 wire bytes and event keys, spent allowances, manual reopening, pending-entry checks, protection/reconciliation and economic controls retain their behavior. No source-budget restart occurs.
6. Test the observation storage schema/permissions/bounds and same-capture replay without claiming observation deduplication proves transaction continuity.
7. Pass affected, canonical full and raw suites on exact frozen bytes; report unavailable private-corpus skips explicitly. Obtain separate definitive SPEC and QUALITY acceptance bound to the same source/test/driver manifest. Passing counts alone are not acceptance.

## Deployment and rollback

After written-spec/plan authority, implementation and matching-byte acceptance, promote only the reviewed replacement commit into the clean live application checkout. Verify the intended remote transition without rewriting shared history. Preserve operational state and exact autonomy configuration; quiesce affected application jobs, verify no in-flight writers, snapshot operational bytes/metadata, run live-tree full/raw verification using the accepted test interpreter, separately verify cron-runtime imports, then restore only originally enabled schedules with readback.

The deployed predecessor has no acquisition v3 history from this failed project: verify actual compatibility before cutover rather than infer a clean root from a missing index. The replacement must never create new acquisition authority; rollback may preserve inert research observations without treating them as policy records. Rehearse existing earnings/protection behavior and entry refusal of incompatible identities. Do not restore a production database, erase policy history or restart/modify Hermes. Source deployment, publication, restored schedules and first actual successful scheduled execution are separate reported results.

## What this supersedes

For the replacement release only, supersede the automatic `sec_original_agreement` admission path and legal-prose originality/role classifier proposed in the earlier Stage 2 specification and Amendment A. Preserve their failed implementation and evidence as historical material, not runtime authority. Keep earnings support, source-authenticity/retention standards, history/allowance protection, owner approval and release gates. Any later explicit-binding implementation requires its own complete authority contract; it is not silently enabled by this research-only change.
