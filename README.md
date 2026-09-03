# Tradey Desk

A fail-closed, paper-first Alpaca trading desk. It is **disabled by default** and cannot submit an order while `autonomy_config.json.enabled` is false or `KILL_SWITCH` exists.

## Safety boundary

- US listed common stocks only; funds/ETFs/ETNs, options, crypto, OTC, short sales, margin usage, penny stocks, and illiquid names are rejected.
- Aggregate managed-exposure cap: **$10,000**; per-position cap: **$500**; at most **2 orders/day**.
- Each new position is also capped at **$25 of planned stop loss**. Whole-share quantity is the minimum allowed by stop risk, the $500 position cap/headroom, available cash, buying power, and remaining managed-exposure headroom. If one protected whole share does not fit, the trade is blocked.
- Fractional-quantity validation is implemented but execution remains disabled because Alpaca currently rejects fractional bracket/OCO orders; it must not be enabled unless broker-attached stop/target protection is verified.
- Orders are DAY limit brackets with an attached stop and target.
- GPT-5.6-SOL gets only the read-only `mcp-alpaca` toolset. Its broker claims are overwritten field-by-field from a deterministic MCP snapshot, including explicit nulls and empty lists.
- DeepSeek V4 Flash 0731 (`deepseek/deepseek-v4-flash-0731`) and Z.ai GLM 5.3 Flash (`z-ai/glm-5.3-flash`) run through Nous Portal OAuth. They receive the same immutable evidence and canonical proposal in separate, concurrent, tool-free Hermes processes. Any unavailable, malformed, low-confidence, vetoing, hash-mismatched, or disagreeing review strips the order.
- The execution bridge is deterministic Python and exposes only stock limit bracket placement with a stable Alpaca `client_order_id`.
- Liquidity and technical levels use adjusted Massive consolidated daily aggregates and exclude the current partial session. The research model no longer supplies volume, stop, or target values.
- Every market-data value carries explicit provenance. By explicit paper-trading policy, Alpaca IEX is the permitted execution-reference quote and its one-venue spread is checked against the configured spread limit; it is never labeled or described as consolidated NBBO.
- Earnings timing uses an exact sourced event timestamp. The deterministic broker-calendar path classifies it as upcoming, reported, or unknown and applies the blackout only to upcoming events within the configured session window.
- Reward/risk is recomputed from the exact final limit, stop, and target. Model-stated ratios are overwritten, and final limit prices must remain close to the fresh permitted quote.
- Only confirmed fills enter `trade_journal.jsonl`; every proposal/rejection/placement/fill/failure enters `order_ledger.jsonl`.

## Simplified decision workflow

1. **Research:** the radar proposes a sourced thesis, catalyst, setup type, exact `planned_exit_at`, and horizon rationale. It does not choose an executable limit, stop, target, quantity, confidence, or reward/risk.
2. **Broker and market truth:** deterministic code retrieves the current Alpaca paper account, positions, open orders, common-stock eligibility, fresh two-sided IEX quote, completed Massive consolidated daily bars/volume, earnings state, and Alpaca exchange sessions through the planned exit.
3. **Horizon:** Python counts exchange sessions and assigns the rubric: **1–5 sessions = `short_1_5`**; **6–30 sessions = `swing_6_30`**. Missing calendars, invalid ranges, and any supplied session-count mismatch fail closed.
4. **Canonical proposal:** for a BUY, Python fixes the limit to the fresh IEX ask and derives stop/target from completed daily bars. Momentum/breakout setups use 1.25× ATR risk and a 2.25× ATR target; 6–30-session fundamental/industry setups use 1.5× ATR risk and a 3× ATR target; pullback/mean-reversion setups use the buffered 10-session low and 20-session high. The independent 1.6:1 reward/risk gate can still reject any geometry. Python computes a positive whole-share quantity under every risk/cash/exposure cap, then SHA-256 hashes the immutable proposal.
5. **Independent review:** both reviewers evaluate exactly that proposal hash. They return only `proposal_hash`, `decision`, 0–5 component scores, fatal flags, and normalized reason codes; they cannot alter the order.
6. **Deterministic aggregation:** Python applies fixed horizon-specific rubric weights, requires both approvals, rejects fatal flags or malformed/hash-mismatched responses, and uses the lower reviewer score. The current go/no-go threshold is **0.55**; it is an uncalibrated conviction score, not a win probability and not a sizing multiplier.
7. **Final safety and execution:** all quote, spread, reward/risk (**minimum 1.6:1**), planned-risk, cash, exposure, earnings, eligibility, order-count, and account-state checks run again against fresh broker data. Only the exact reviewed DAY limit bracket with attached stop and target may be submitted, followed by broker readback and reconciliation.

If a successful reviewer process returns no parseable JSON, the same isolated model receives exactly one **formatting-only** repair request. It may only reformat its prior answer; missing or ambiguous fields must become a fail-closed HOLD. Process failures, timeouts, valid-but-malformed schemas, and substantive vetoes are never retried.

### Reviewer rubric weights

- `short_1_5`: catalyst 30%, price/volume confirmation 25%, technical structure 20%, market regime 10%, fundamental trajectory 10%, valuation expectations 5%.
- `swing_6_30`: catalyst 20%, price/volume confirmation 20%, technical structure 20%, market regime 10%, fundamental trajectory 20%, valuation expectations 10%.

## Shadow calibration

Every real review cycle also writes a private, no-execution shadow decision under `test_artifacts/shadow/`. It records the exact hypothetical canonical entry, stop, target, quantity, proposal hash, rubric, both reviewer scores, and whether the proposal would have traded. Fixture and live dry runs do not enter this dataset.

The post-close routine measures shadow outcomes versus SPY and writes `calibration_report.json` for threshold ladders from 0.40 through 0.80. These files remain separate from `order_ledger.jsonl`, `trade_journal.jsonl`, operational candidate outcomes, and the public dashboard. Shadow results measure decision quality rather than guaranteed fill quality and must not be presented as actual performance.

## Credentials (not stored in this repo)

The configured Hermes MCP uses `${ALPACA_API_KEY}` and `${ALPACA_SECRET_KEY}` with `ALPACA_PAPER_TRADE=true`; consolidated volume uses `${MASSIVE_API_KEY}`. Decision reviews use the active Hermes Nous Portal OAuth session; no separate DeepSeek or Z.ai API keys are required. Dashboard deployment requires `VERCEL_TOKEN`. Put secrets in the active Hermes profile's secret store, never in prompts or source files.

## Local verification

```bash
uv run --with fastmcp python -m unittest discover -s tests -p 'test_*.py' -v
python3 alpha_radar.py --dry-run-fixture
python3 autotrader.py --dry-run-fixture
python3 candidate_outcomes.py --fixture fixtures/outcomes.json
python3 shadow_calibration.py
python3 public_dashboard.py
```

`autotrader.py --dry-run-fixture` must end with a blocker because autonomy is disabled and dry-run execution is forbidden.

## Enabling

Do not set `enabled=true` until paper credentials, both model credentials, source verification, Alpaca readback, and the dashboard have all passed. Live brokerage is additionally hard-blocked by `broker_mode != "paper"`; changing that requires a code/config review and explicit user approval.
