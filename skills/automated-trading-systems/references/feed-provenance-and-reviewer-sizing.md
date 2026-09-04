# Feed provenance and reviewer quantity policy

Use this reference when a trading system mixes research data, consolidated historical data, and a broker execution feed, or when broker capabilities force integer-only sizing.

## Normalize by semantic provenance

- Treat model-supplied `average_volume`, `volume_feed`, `quote`, and `quote_feed` as untrusted. Strip them before dossier persistence and again before constructing reviewer evidence so legacy dossiers cannot reintroduce them.
- Source deterministic liquidity from one declared consolidated dataset. Carry an explicit field such as `volume_feed: massive_consolidated` and require that provenance before applying a consolidated-volume threshold.
- Never compare IEX-only volume with consolidated volume or interpret an IEX top-of-book spread as SIP/NBBO. Label the execution quote explicitly (for example, `quote_feed: alpaca_iex`) and block with a precise reason such as `consolidated_quote_unavailable` when the strategy requires current NBBO.
- Do not silently omit a requested `feed` argument when adapting logical parameters to an MCP schema. If the live schema cannot accept a required parameter, fail before the provider call rather than asserting provenance that was never enforced.

## Validate market-data numeric domains

- Broker/provider data needs the same domain checks as model order fields. Reject booleans, conversion errors, negative volume, NaN, and infinity.
- Remember that comparisons with NaN are false in both directions; `NaN < minimum` and `NaN > maximum` can accidentally pass a gate. Check `isfinite` before threshold arithmetic.
- Exclude an in-progress daily aggregate using the exchange timezone, not UTC date alone. A conservative post-close buffer is acceptable; early-close days may remain conservatively excluded unless an exchange calendar is integrated.

## Integer-only reviewer policy

If fractional advanced orders are unsupported or disabled:

1. Put the effective execution policy in the byte-identical reviewer bundle, including `max_position_usd` and `allow_fractional_shares=false`.
2. Tell reviewers that BUY/SELL quantity must be a positive integer even when the asset is fractionable.
3. Require `quantity × limit_price <= max_position_usd`; if no positive whole share fits, require HOLD.
4. Do not auto-round a fractional consensus order. Exact-order consensus means rounding would create an unreviewed order. A fractional proposal must block, while future reviews should propose the valid integer quantity directly.
5. Keep deterministic validation as the final authority; reviewer instructions reduce avoidable blockers but never replace risk checks.

## Verification pattern

- Probe provider entitlements read-only and report only status/capability metadata, never secrets or identifying account data.
- Test consolidated volume availability separately from current consolidated quote entitlement; one does not imply the other.
- Add red/green tests for: stripping model-owned feed claims, explicit provenance, unsupported feed parameters, current-session exclusion, non-finite broker values, integer-only reviewer wording, and policy fields being identical for both reviewers.
- Run an authenticated normalized snapshot and confirm the expected feed-specific blocker without placing an order.
