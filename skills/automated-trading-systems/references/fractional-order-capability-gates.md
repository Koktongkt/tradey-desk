# Fractional-order capability gates

## Why this reference exists

Broker features that are supported separately may not be supported in combination. A system can correctly serialize a fractional quantity and correctly serialize a bracket order while the broker rejects `fractional + bracket/OCO` as an unsupported complex order. Treat payload/unit tests as interface tests, not lifecycle verification.

## Dated Alpaca case study (checked 2026-09-01)

- Alpaca's official fractional-trading page documented fractional `qty` for DAY market/limit/stop/stop-limit orders, up to 9 decimal places, and required `asset.fractionable=true`.
- Alpaca's generic order schema separately listed equity bracket/OCO/OTO order classes.
- Those two statements did **not** establish that a fractional parent can carry bracket/OCO legs.
- Current Alpaca community evidence, including an August 2026 report and broker error `42210000: fractional orders must be simple orders`, indicated the combined shape remained unsupported.
- Safe resolution: retain the fractional validation code if useful, but keep fractional execution disabled while broker-attached stop/target protection is mandatory. Do not silently replace attached protection with journal-only or delayed exit orders.

This provider capability is time-sensitive. Re-check current official documentation and authenticated paper behavior before relying on it.

## Reusable capability-verification checklist

1. Write the exact required order tuple: asset class, side, fractional/whole quantity, parent type, time-in-force, order class, take-profit, stop-loss, and extended-hours flag.
2. Check official documentation for the **combined tuple**, not each feature separately.
3. Inspect the live MCP/API schema to verify exact field names and decimal/string coercion.
4. Fetch the asset through the production broker-read path and require `tradable=true`, expected asset class, and `fractionable=true`.
5. Keep the production feature flag false until broker behavior is proven.
6. If a synthetic paper order is needed, obtain explicit authorization because it bypasses the normal thesis/consensus path and may consume the daily-order allowance. Pause the recurring executor, use a stable test client ID and non-marketable limit, read back the parent and protection legs, cancel, and reconcile terminal state before resuming.
7. Verify atomic failure behavior: an unsupported bracket must reject the parent rather than leave an unprotected fill.
8. Activate only after an authenticated paper lifecycle confirms acceptance, attached-leg creation, reconciliation, cancellation, and no contamination of operational performance records.

## Numeric validation for fractional quantities

- Reject booleans, zero/negative values, NaN, infinity, and unsupported numeric types.
- Avoid calling `math.isfinite()` or converting to `float` on arbitrary-size integers; branch by numeric type first.
- Enforce the broker's documented quantity precision (Alpaca: at most 9 decimal places at the check date).
- Enforce price tick precision and finite, positive entry/stop/target values.
- Use `Decimal(str(value))` for dollar basis, cash, buying-power, position-cap, aggregate-cap, and reward/risk boundary arithmetic.
- Test exact-cap, just-over-cap, fractional SELL/no-short, non-fractionable asset, disabled policy, overprecision, NaN/infinity, bool, and oversized-integer cases.

## Reporting language

Distinguish:

- payload serialization verified;
- broker schema verified;
- authenticated asset eligibility verified;
- paper order accepted;
- protection legs attached;
- complete fractional bracket lifecycle verified.

Never collapse these into “fractional trading works.”
