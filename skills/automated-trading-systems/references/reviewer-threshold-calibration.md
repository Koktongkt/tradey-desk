# Reviewer Threshold Calibration by Ledger Replay

## Why

A dual-reviewer gate with a fixed `min_approval_confidence` can silently disable an otherwise healthy desk. In one 46-cycle production sample, 0 cycles reached order validation: 20 were dual-HOLD (`consensus_hold`), 25 were rejected as `malformed_or_low_confidence`, and 1 was `reviewer_unavailable`. The root cause was calibration, not thesis quality — across all 46 cycles neither reviewer model ever emitted a BUY above 0.62 confidence, so a 0.75 gate made approval mathematically near-impossible while producing plausible-looking "blocked" audit rows.

## Calibration method: replay, don't guess

Never tune the threshold by intuition or by reading a few theses. Replay the entire private review ledger through the **actual production consensus function** (import the real `consensus()`/gate code, not a reimplementation) at a ladder of candidate thresholds, and read off the decision-reason distribution:

```python
import json
from collections import Counter
from pathlib import Path
import autotrader  # the real production module

cfg = json.loads(Path("autonomy_config.json").read_text())
rows = [json.loads(x) for x in Path("private/reviews.jsonl").read_text().splitlines() if x.strip()]

for threshold in (0.75, 0.65, 0.60, 0.55, 0.45, 0.40):
    c = dict(cfg, min_approval_confidence=threshold)
    outcomes = [autotrader.consensus(r["reviews"][0], r["reviews"][1], c) for r in rows]
    reasons = Counter(o["reason"] for o in outcomes)
    approved = [(o["order"]["symbol"], o["order"]["confidence"],
                 # recompute reward/risk deterministically — never trust the model's stated value
                 float(o["order"]["target"] - o["order"]["limit_price"]) /
                 float(o["order"]["limit_price"] - o["order"]["stop"]))
                for o in outcomes if o["approved"]]
    print(threshold, dict(sorted(reasons.items())), approved)
```

Interpret the ladder as a marginal-utility curve: moving from 0.75 → 0.60 admitted 2 historically-clean cycles (both with deterministically recomputed reward/risk ≥ 2.2 and integer sizing under the position cap); 0.55 admitted 5, one of which failed the deterministic 2:1 reward/risk gate anyway; 0.40 admitted a binary pre-event trade — exactly the speculation class the gate exists to block.

## Confidence semantics before threshold tuning

First inspect how the score is produced. If the prompt merely requests `confidence 0..1` without anchors, components, or a deterministic formula, the value is model-assigned conviction—not a calculated or calibrated probability. Round-number clustering such as 0.40/0.45/0.50/0.55 is a warning that threshold changes may be tuning to model style rather than predictive edge.

Use a defined rubric before further threshold reductions. Require reviewers to return component scores and short evidence for at least evidence consistency, catalyst certainty, fundamental/valuation support, market confirmation, execution quality, and event/gap risk. Validate domains and compute the aggregate in deterministic code. Preserve both reviewers’ raw components and scores; if a scalar pair score is needed, use an explicitly documented conservative aggregation rather than silently copying one reviewer or averaging disagreement away.

Keep confidence and reward/risk analytically separate:

- reward/risk describes proposed payoff geometry from exact executable levels;
- confidence describes setup/evidence reliability and, only after calibration, may have probabilistic meaning;
- a high nominal ratio does not imply high confidence, especially around earnings or binary catalysts where gaps can defeat the planned stop;
- the theoretical break-even win rate `1 / (1 + R)` is not evidence that the model’s confidence equals that probability.

Before reporting “many low-confidence blockers,” replay and classify each review twice: structural validity with the threshold disabled, then validity at the production threshold. A row that fails both has a malformed component; a structurally valid executable recommendation that fails only at the production threshold is genuinely low-confidence. Also evaluate secondary reasons after confidence classification: mixed BUY/HOLD is still model disagreement, and differing executable levels are still order-detail disagreement even if a confidence check runs first.

## Choosing the value

- Prefer the **highest threshold that admits a small but nonzero flow** of cycles that also pass all deterministic gates when replayed.
- Treat the lowered value as a **calibration experiment, not validated edge**: commit to a review point (e.g. 20–30 eligible decisions) comparing traded vs. skipped outcomes vs. the benchmark before moving again.
- Record the decision and its replay evidence for the user; do not silently re-tune repeatedly.

## Audit hygiene: separate the reasons

`malformed_or_low_confidence` conflates two very different failure classes:

- **low confidence** — structurally valid decision, below threshold (a calibration signal);
- **malformed** — missing fields, bad types, invalid JSON (a reviewer-model reliability signal).

When these are merged, threshold calibration reads noise. Split the reason codes in the consensus layer so future replays can distinguish "the gate is too strict" from "the reviewer models are unreliable." In the sample above, most `malformed_or_low_confidence` rows were actually pure low-confidence rejections.

## Change-management for policy parameters

Any gate-value change (not just the autonomy flag) follows the same safe sequence:

1. Pause the recurring execution job and read it back with `state: paused`.
2. Change the production-config regression test to the requested value **before** editing config; run that single test and observe the expected old-value/new-value assertion failure.
3. Change exactly one production config field, then rerun the focused test to green.
4. Run the full safety suite using the project's real dependency/runtime wrapper. If broker-bridge tests intentionally execute through an ephemeral dependency command such as `uv run --with <package>`, run discovery under that same wrapper rather than declaring the suite broken from a bare system-Python import failure.
5. Replay the current private review ledger through the production consensus function at both old and new thresholds. Report the sample size, decision-reason distribution, and marginal approvals; never write replay rows into operational ledgers.
6. Read back the effective gate-relevant config subset and verify all unrelated risk limits remain unchanged.
7. Resume the execution job and read it back with `state: scheduled` and a next-fire time.
8. State explicitly that the configuration change itself submitted no order.

A scheduler may label a completed cycle `error` when the fail-closed executable intentionally returns nonzero for a policy blocker. Before calling this an infrastructure failure, inspect the sanitized decision event and scheduler transport fields: a recent normalized `blocked` event with no `last_fire_error` or delivery error is a policy rejection, not evidence that the scheduler or broker bridge failed.

## Pitfalls

- Do not calibrate from reviewer `confidence` numbers alone; models calibrate confidence differently. Let the deterministic gates (reward/risk, sizing, spread, freshness) do the final filtering after consensus.
- Do not count replay-approved historical cycles as trades or outcomes; the replay is read-only analysis over private review files.
- Replay must import the production consensus/gate code. A hand-rolled reimplementation will drift from the real threshold semantics (per-field validation, HOLD classification, exact-order-field equality) and produce misleading counts.
