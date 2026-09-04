# Execution Blocker Diagnostics

Use this when a proposed order reaches deterministic validation but is rejected by several normalized reason codes. Diagnose each blocker independently: one valid blocker is sufficient to prevent submission.

## Feed-provenance blockers

A code such as `consolidated_quote_unavailable` does not necessarily mean the broker returned no quote. It commonly means the available quote is single-venue (for example, IEX) while policy requires a consolidated SIP/NBBO quote before checking spread or setting an execution reference.

Diagnostic sequence:

1. Inspect the normalized quote object separately from its provenance field.
2. Report whether a two-sided quote exists.
3. Report the actual feed label and the policy-required feed label.
4. Do not calculate or characterize a single-venue spread as NBBO.
5. Resolve by obtaining the required entitlement/feed, or by an explicit policy change—not by relabeling the data.

If the user explicitly accepts IEX for a paper-only pilot, encode that as an allowlist such as `allowed_quote_feeds: [alpaca_iex]`; then calculate the spread from IEX while naming it a single-venue spread, never NBBO. Add a maximum final-limit deviation from the fresh permitted quote (BUY versus ask, SELL versus bid) so reviewers cannot carry a stale candidate price into an executable order. Reassess this exception before live-money activation.

An entitlement change alone may not work when the adapter hardcodes `feed=iex`. Verify the live tool schema supports `feed`, request the selected feed explicitly, and derive the provenance label from the successful request rather than account assumptions.

Keep quote and volume provenance separate: consolidated daily volume does not make an IEX quote consolidated.

## Earnings-blackout blockers

A scalar sessions-distance field is insufficient unless its direction is unambiguous. `0` may accidentally represent either “reports later today” or “reported earlier today,” which are materially different states.

Prefer a normalized event object:

```json
{
  "status": "upcoming",
  "scheduled_at": "...",
  "sessions_away": 0,
  "verified_at": "...",
  "source": "issuer_ir"
}
```

Allowed status values should be narrow, such as `upcoming`, `reported`, and `unknown`. Ask research for an exact sourced UTC event timestamp, not a model-counted number of sessions. Classify past timestamps as reported and future timestamps as upcoming in deterministic code; for future events, count sessions with the broker/exchange calendar. Apply the blackout only to verified upcoming events. Missing or malformed timestamps become unknown and fail closed. Old dossiers that lack the new event shape should also fail closed until refreshed rather than being guessed or silently migrated.

If the event timestamp conflicts with dossier language or current time, fail closed as unknown and repair normalization; do not weaken the blackout threshold to hide a state-model bug.

## Reward/risk blockers

The deterministic validator must recompute economics from the final exact order:

- BUY: `risk = entry - stop`, `reward = target - entry`
- SELL: `risk = stop - entry`, `reward = entry - target`
- reject non-positive risk;
- compare `reward / risk` with the configured minimum using decimal arithmetic.

A reviewer may state a ratio computed from the candidate reference price, then agree to a different executable limit without updating that ratio. Put the configured minimum and exact BUY/SELL formulas in the byte-identical reviewer policy, but still treat model arithmetic as untrusted. Normalize the agreed plan by overwriting its ratio from the final limit/stop/target before validation, idempotency hashing, intent persistence, and journaling. Preserve the stated value only for private diagnostics. It must never control execution.

Example pattern: a candidate near 443.90 with stop 408 and target 510 is roughly 1.84:1, but changing the executable entry to 450 changes the exact ratio to 60/42, about 1.43:1. A 1.6:1 policy must reject the latter even when both reviewers repeat 1.84.

## User-facing explanation

Lead with the outcome (“the order was blocked; nothing was submitted”), then explain each reason in plain language and show the exact governing values. Distinguish structural blockers from probable data bugs:

- structural: required SIP/NBBO entitlement absent;
- policy: computed ratio below the configured floor;
- likely normalization defect: already-reported earnings encoded as an upcoming event.

Do not imply that lowering a gate fixes a provenance or event-state defect.