# Prospective opportunity-policy cutover

Status: proposed written design for user review; not implemented or activated.
Base: `91ea84e`.
Execution preference: inline development; no subagent development.

## Intent and acceptance

Start the event-based repeat-review policy prospectively for paper testing, without reconstructing every legacy review/event association. Preserve all operational trading obligations and truthful performance history. A completed prospective HOLD/disagreement must prevent another paid review of that unchanged event even if research generates a different dossier. A genuinely new verified event may advance. The user knowingly accepts one fresh assessment of a previously rejected event after cutover.

This is an explicit approved policy baseline, not a claim that legacy history was recovered, cleared as factually attributable, or never existed. Preserve the old exact-dossier guard unless a separate change is approved: old cached dossiers are not made retryable by this baseline.

## Recommended scope

Extend the existing opportunity-policy ledger, coherent snapshot reader and shared eligibility checks. Do not introduce another database, model, service, ticker cooldown, similarity engine, discovery loop or automatic materiality detector. Initial reopening is manual and evidence-backed only; no new automatic reopening conditions are configured.

Use an explicitly versioned prospective activation understood by every entry-policy reader. Older policy readers must reject it rather than silently enforcing an incomplete interpretation. Missing activation continues to mean the existing legacy floor, not implicit cutover. Once activated, missing/corrupt/unsupported cutover state fails closed for new entries.

## Durable cutover contract

Record one append-only prospective-cutover baseline, referenced by activation, in the existing private policy stream. Its approved manifest binds the operational root, baseline identity, exact canonical per-stream sequence/digest watermarks, policy compatibility version and explicit exclusion of pre-baseline review decisions from event-allowance spending. Capture all canonical streams needed by the policy and existing operational eligibility/protection readers; name them explicitly during implementation planning. Use canonical row/sequence identity, not timestamps alone, to distinguish history from new writes.

Capture and validate the baseline under the existing entry/storage coordination discipline while affected writers are paused. Do not hold an entry lock across research or broker subprocess calls. Use the existing paper-only read-only broker snapshot/qualification path for current positions and orders, after checking its persistence behavior. If current operational state cannot be authoritatively reconciled, activation does not complete. No new order, cancellation or protection mutation is part of baseline creation.

Import/activation requires an explicit approved canonical manifest digest and apply flag. Revalidate the exact snapshot under the existing lock before appending; changed watermarks require regenerating and reapproving the manifest, not silently updating the approved payload. Baseline/activation must be idempotent and resumable after partial writes without opening a permissive interval. Never infer approval from model output. A second cutover or changed baseline must be rejected by this initial implementation rather than resetting post-cutover dissent.

## Prospective research and review rules

Only fresh candidates durably admitted after the recorded boundary and bound to this baseline, a verified event and its allowance may enter new paid review. Do not reinterpret old cached candidates, old policy bindings or pre-cutover in-flight dossiers as new work. Pause and drain affected workers before activation; reject a stale worker's candidate at the authoritative intake boundary. Candidate, reuse-first, failure-fallback and execution paths all use the same shared policy.

Ignore pre-baseline review decisions only for the new event-memory calculation and its legacy binding-completeness requirement. Existing historical missing-history/identity records remain intact but cannot create a legacy-only global or issuer-level research ban under this explicit prospective mode. Malformed ledger envelopes, corrupted storage and contradictory prospective state remain integrity failures; the cutover is not a parser/integrity bypass.

Every post-baseline substantive review is authoritative. HOLD/disagreement spends the linked event allowance across regenerated dossiers; empty/reconciliation-only markers do not manufacture permission or erase dissent. A missing or malformed prospective event/baseline link blocks new review rather than being treated as excluded legacy history. The current approved attempt and narrow proven exact-dossier pre-submission retry retain their existing semantics; neither can authorize a new dossier or override held/pending exclusions.

New URLs, prose, prices and time do not reopen an event. New verified reporting periods/events may be eligible; unresolved event identities remain blocked. Existing conservative resolver coverage is unchanged. A spent event may reopen only through an explicit evidence-backed manual grant. Do not automatically generate conditions from reviewer reasons.

## Operational state is not reset

All existing positions, fractional residuals, saved intents, pending/partial/unknown submissions, entry ownership, protection registrations, fills, reconciliation obligations, daily submission accounting and cash/exposure reservations continue across the baseline, irrespective of their dates. Historical filled BUY rows without dossier hashes remain operational facts, not flatness evidence and not synthetic event bindings.

Require current authoritative positions/open orders and existing ownership proof at normal entry boundaries. Any held quantity or same-symbol unresolved entry blocks a new BUY. Missing ownership or ambiguous broker state remains fail-closed. Protective exits, pending-parent continuation and lifecycle reconciliation run before entry decisions and remain available when entry-policy checks block.

Do not change paper mode, enablement, capital/risk limits, spread/earnings/source gates, order types, model providers, schedules, broker call budgets or performance calculations. Never delete, rewrite or fabricate historical candidate/review/order/trade rows. Public reporting remains sanitized; distinguish the policy-testing period from full strategy history without erasing losses.

## Failure, compatibility and rollback

Post-activation incompatible code must block new entries while preserving lifecycle/protection. Test the actual supported rollback floor against prospective activation, including the new baseline record type. Do not use a rollback to permissive pre-policy code. Missing/divergent projections, nonempty recovery state requiring repair, partial activation, invalid baseline digest and root mismatch must never downgrade to legacy permission. Retain current storage durability and explicit repair requirements.

## Test and release evidence

Observe failing tests before product changes. Run isolated tests using synthetic data and an authenticated disposable real-history copy where necessary; no paid research or order canary is required for development.

Required regression cases:
- Incomplete legacy review associations do not prevent an explicitly approved prospective activation; without that activation, existing migration behavior is unchanged.
- Legacy gaps do not become prospective issuer bans; malformed/corrupt records still fail closed.
- Old cached candidates and pre-cutover workers cannot bypass the baseline; both reuse and failure fallback reject them.
- Post-cutover HOLD/disagreement blocks regenerated dossiers for the same event; later markers cannot reset spending; a new verified event still advances.
- Post-cutover unlinked/malformed reviews block rather than disappearing into legacy exclusions.
- Existing holdings, pending/partial/unknown entries and daily submissions remain binding; no add-ons, double reservations or phantom fills.
- Protection, exact-parent continuation and reconciliation remain functional when entry is blocked.
- Changed snapshot between approval and apply, cross-root input, repeated activation, rollback/version skew, crash after baseline append and crash after review append fail safely.
- All prior exact-dossier retry, source, earnings, risk and portfolio-accounting regressions remain green.

Before operational apply, verify a frozen diff, full supported offline suites and a disposable-copy activation/readback/rollback rehearsal. Honor the user's no-subagent-development preference: execute inline; do not silently introduce subagent development or substitute self-review for any separately required independent release review. If independent release review cannot be obtained within the authorized workflow, report that release gate explicitly rather than activating anyway.

## Approval and execution boundary

Approval of this written spec permits a concise implementation plan and selection of inline execution, followed by TDD implementation. Production cutover/apply is a separate consequential state transition: present the exact manifest, preservation checks, pause/resume scope and rollback evidence for approval before applying. No broker mutations are authorized by the cutover design.
