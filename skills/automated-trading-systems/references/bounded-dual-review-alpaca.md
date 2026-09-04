# Bounded dual-review Alpaca implementation

This reference captures a concrete paper-trading pattern. Treat provider versions and MCP schemas as discoverable runtime facts; re-run schema discovery before adapting it.

## Broker separation

- Configure a model-facing Alpaca MCP server with an explicit allowlist of read tools: account, positions, open orders, asset lookup, market clock/calendar, stock bars/quotes/snapshots, movers, and news.
- Do not expose `place_stock_order`, crypto/options order tools, cancellation, replacement, liquidation, or close-position tools to models.
- Use a separate deterministic FastMCP client bridge for stock placement and reconciliation. The bridge should construct only the reviewed DAY limit bracket order.
- Force `ALPACA_PAPER_TRADE=true` in both configurations.

## Tool-schema discovery notes

The official server derives schemas from Alpaca specs. Discover them at runtime rather than hard-coding V1 assumptions. Common V2 parameter names observed in a verified discovery run:

- `get_asset`: `symbol_or_asset_id`
- `get_stock_latest_quote`: `symbols` (comma-separated)
- `get_stock_bars`: `symbols`, `timeframe`, `start`, `end`, `limit`
- `get_orders`: `status`, `limit`, optional `symbols`
- `place_stock_order`: `symbol`, `side`, `type`, `qty` as string, `time_in_force`, `limit_price` as string, `client_order_id`, `order_class`, `take_profit_limit_price`, `stop_loss_stop_price`
- `get_order_by_client_id`: `client_order_id`

The server may return symbol-keyed dictionaries nested under `quotes` or `bars`; normalize recursively and fail closed when expected values remain absent.

A successful MCP handshake and tool listing does not prove account credentials can read data. Verify a real read-only account call separately before reporting authenticated broker access.

## Consensus contract

Use a strict JSON decision schema containing:

- `action`, `symbol`, `quantity`, `order_type`, `limit_price`
- `stop`, `target`, `horizon`
- `confidence`, `thesis`, `risk_reward`

For orders, require exact equality on all execution and risk-plan fields. For a plan-only update, compare stop/target under a documented narrow tolerance. Any unavailable or malformed reviewer produces `order=null` and a public sanitized blocker.

## Paper-order gate checklist

Before placement, all must pass:

- autonomy enabled by explicit user decision;
- paper broker mode and absent kill switch;
- intact, source-verified, fresh dossier;
- two independent valid reviews with matching action/symbol/order details;
- positive common-stock classification; no fund/ETF/ETN/OTC;
- fresh bid/ask and acceptable spread;
- sufficient average volume and minimum price;
- known cash and buying power; basis fits both;
- projected position and account allocation within caps;
- known earnings distance outside blackout;
- no active broker orders when one-live-order policy is used;
- SELL quantity does not exceed held quantity;
- deterministic reward/risk meets threshold;
- fresh broker review returns the same clean state;
- idempotency key is stable and unused.

## Scheduler pattern

Hermes no-agent cron scripts must live under the active Hermes scripts directory and be referenced by filename. Put a small wrapper there that invokes the project’s timezone-aware cycle runner. Use broad UTC cron schedules, then gate with `zoneinfo.ZoneInfo("America/New_York")` inside the runner. Empty stdout means successful no-event; print only trade, blocker, authentication failure, or system failure.

## Honest verification labels

Report these separately:

1. Unit/safety tests passed.
2. MCP server discovery passed.
3. Authenticated account snapshot passed.
4. Fixture dual-review dry-run passed and remained blocked.
5. Paper order lifecycle passed (only if an explicitly authorized test order was placed and reconciled).
6. Local dashboard passed and public scan was clean.
7. External deployment passed (only with a verified public URL/readback).

Never infer a later gate from an earlier one.
