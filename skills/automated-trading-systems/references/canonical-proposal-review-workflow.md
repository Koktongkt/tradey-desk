# Canonical proposal before independent review

Use this pattern when independent reviewers create avoidable blockers by independently restating executable prices, quantities, or arithmetic.

## Boundary

Research proposes the sourced thesis, catalyst, setup type, exact planned-exit timestamp, and rationale. It does **not** choose executable quantity, confidence, reward/risk, or the execution-reference limit. Stop/target may be retained from research only under an explicit policy; when deterministic technical levels are enabled, strip model-supplied levels and derive them from provenance-checked completed bars before hashing.

Deterministic code then:

1. Reads fresh broker state and an explicitly permitted quote feed.
2. Converts `planned_exit_at` to the exchange timezone before selecting the exit session date.
3. Counts authoritative exchange sessions and assigns one non-overlapping rubric (for example, 1–5 versus 6–30 sessions); missing/invalid/out-of-range calendars fail closed.
4. Sets the canonical BUY entry to the fresh permitted ask (SELL uses the permitted bid where selling is allowed).
5. Validates stop/target geometry and recomputes reward/risk from the exact entry.
6. Calculates whole-share quantity as the minimum allowed by stop-risk budget, position headroom, cash, buying power, and managed-exposure headroom. A result below one share is no trade.
7. Normalizes the complete proposal and hashes it before dispatch.

## Reviewer contract

Give isolated reviewers byte-equivalent evidence, the exact canonical proposal, its hash, and the assigned rubric weights. Require only:

- `proposal_hash`
- `decision` (`APPROVE` or `HOLD`)
- bounded component scores (for example integers 0–5)
- `fatal_flags`
- normalized `reason_codes`

Reviewers must not return or modify entry, quantity, stop, target, reward/risk, or horizon. Deterministic code validates the hash and schema, computes each weighted conviction score, requires both approvals, rejects any fatal flag, and uses the lower score as the operational gate. Conviction is not a calibrated win probability and must not increase position size.

## Formatting-only reviewer repair

A successful reviewer process that returns no parseable JSON may receive exactly one repair request in the same isolated model. Supply only its prior output and the required schema. The repair prompt must prohibit reconsidering, rescoring, adding evidence, or changing substantive judgment. Missing or ambiguous fields become a fail-closed HOLD with a normalized repair reason. Never retry process failures, timeouts, valid-but-malformed schemas, hash mismatches, low scores, or vetoes; those are substantive/unavailable outcomes rather than formatting faults.

## Deterministic technical levels

When stop and target subjectivity is a recurring blocker, derive them before review from a provenance-checked completed-bar series rather than model prose. A bounded implementation can use:

- at least 20 completed adjusted consolidated daily bars, excluding the current partial session;
- ATR(14) with finite OHLC-domain validation;
- momentum/breakout: stop at 1.25 ATR below entry and target at 2.25 ATR above;
- 6–30-session fundamental/industry swing: stop at 1.5 ATR below and target at 3 ATR above;
- pullback/mean reversion: stop below the 10-session low by 0.1 ATR and target the 20-session high.

These are explicit policy choices, not universal alpha. Preserve the method and ATR in the proposal hash, maintain a separate minimum reward/risk gate, and block unavailable bars, invalid geometry, unsupported setup/horizon combinations, or zero whole-share sizing. Do not move a derived level after review.

## Shadow calibration

Shadow mode records the exact canonical proposal, both deterministic reviewer scores, decision timestamp, and would-trade outcome without submitting an order. Keep decisions, measured outcomes, and reports under an isolated non-operational directory; fixture/live dry runs must not enter the sample, and shadow rows must never count as orders, fills, or public performance.

Measure from the canonical entry against a contemporaneous benchmark entry at fixed exchange-session horizons. Join outcomes by a stable shadow ID, deduplicate evolving snapshots, and report threshold ladders with sample counts and average benchmark-relative return. Empty samples remain null. Treat the results as decision-quality evidence—not proof of fills, calibrated win probability, or permission to change production thresholds without a separately reviewed policy update.

## Defense in depth

- Recalculate planned stop loss during proposal construction **and** final validation.
- Re-fetch broker state before submission and submit only the hashed executable fields.
- Keep reward/risk outside the confidence rubric so ambitious targets cannot manufacture conviction.
- Preserve reviewer component scores privately; publish only normalized blocker codes.
- Maintain distinct blockers such as `proposal_hash_mismatch`, `malformed_review`, `low_confidence`, `reviewer_veto`, `invalid_horizon`, `horizon_session_mismatch`, `trading_calendar_unavailable`, `technical_bars_unavailable`, `unsupported_technical_setup`, and `planned_risk_exceeded`.

## Rollout checklist

1. Pause the execution schedule.
2. Add failing tests for sizing, horizon/timezone boundaries, hash mismatch, malformed review, lower-score aggregation, and planned-risk revalidation.
3. Update fixtures and old candidates to the structured horizon/reviewer schema.
4. Run the full safety suite and a dry run whose operational ledgers remain byte-identical.
5. Perform an authenticated **read-only** broker snapshot including `planned_exit_at`; verify account fields, positions/orders shape, allowed quote provenance, two-sided quote when available, and returned exchange sessions. A transient missing quote for one symbol is not proof the bridge is broken—probe a small fixed list and fail honestly if none produce a usable quote.
6. Rebuild the public dashboard, add human-readable mappings for every new blocker, and run the artifact-only secret/identifier/path scan.
7. Read back paper-only config and kill-switch state, resume the scheduler, then list jobs again to verify the exact execution job is enabled and scheduled.

Do not submit a paper order merely to test connectivity.