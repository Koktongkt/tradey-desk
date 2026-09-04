# Broker normalization, legacy-account isolation, and safe scheduling

Use these notes when a bounded paper-trading system connects to a broker account that may contain pre-existing positions or when an MCP server wraps API responses.

## Normalize semantic shapes, not one expected envelope

Broker MCP tools may wrap payloads under security metadata plus nested `data`, `result`, `quotes`, `bars`, or symbol keys. Build pure, fixture-tested walkers that locate:

- account mappings containing both `cash` and `buying_power`;
- symbol-specific quote/asset mappings;
- symbol-specific bar arrays;
- positions and open-order lists.

Preserve explicit zero, `false`, empty lists, and `null`; never select broker fields with truthiness (`x or y`) when zero is meaningful. For every production tool call, inspect the live tool schema and map logical fields only to supported parameter names.

Some Alpaca paper/free market-data subscriptions reject recent SIP historical bars. Specify the permitted feed explicitly (commonly `iex`) for both quote and bar calls instead of relying on provider defaults. Treat a zero/missing ask outside regular hours as non-executable, not as a normalization success.

For bracket orders, verify the actual placement schema and assert that the final adapter payload includes `order_class=bracket`, `take_profit_limit_price`, and `stop_loss_stop_price`; a journal-only stop is not protection.

## Isolate automation from pre-existing positions

If a paper account is not clean, capture a private baseline before the first automated order:

- timestamp and explicit paper mode;
- symbols already held;
- no public account identifiers.

Never trade a baseline symbol because automated and legacy lots cannot be reconciled safely at symbol-level broker APIs. Derive managed exposure from broker market values only for symbols with positive net quantities in the automation's broker-confirmed fill journal. Fail closed when:

- the journal says a managed position is open but the broker does not show it;
- a confirmed fill lacks action, symbol, or positive quantity;
- the proposed symbol overlaps the baseline;
- current managed exposure plus proposed buy basis exceeds the allocation cap.

Record BUY/SELL action in every confirmed-fill journal row so net managed quantity can be reconstructed.

## Classify conservative reviews correctly

Approval confidence thresholds govern executable BUY/SELL/plan-change recommendations. A syntactically valid HOLD may have low confidence and should still be classified as `consensus_hold`, not `malformed_or_low_confidence`. This improves audit quality without relaxing execution: HOLD always remains non-executable.

## Delayed-fill reconciliation

An immediate post-submit read is insufficient for a limit order: it may be `new` or `partially_filled` and fill after the cycle exits. Before placement, persist a private order-intent row keyed by the stable client order ID and containing the exact reviewed plan (action, symbol, quantity, limit, stop, target, horizon, confidence, and thesis). Keep broker order IDs out of public output.

At the start of every later execution cycle:

1. Reduce the lifecycle ledger to the latest status per client order ID.
2. Select only non-terminal intents (`placed`, `new`, `accepted`, `pending_new`, `partially_filled`, or `held`).
3. Re-read each from the broker by client order ID before any new research or proposal.
4. Append the new lifecycle state; journal only a broker-confirmed fill with positive filled quantity and average price.
5. Block new orders while any prior intent remains pending or partial.

Deduplicate daily order counts by client order ID. Counting lifecycle rows incorrectly turns one `placed → filled` order into two daily orders.

## Standing paper-autonomy activation

When a user explicitly waives per-trade confirmation for paper trading, convert that request into a precise standing mandate rather than a blanket “paper means harmless” exception. Restate paper-only mode, eligible instruments/directions, limit-bracket requirements, size/allocation/daily caps, exact dual-model consensus, deterministic risk gates, and the separate-authorization requirement for live money. Run tests before activation, change only the autonomy flag, resume the execution schedule, remove obsolete proposal-only jobs, and read both config and scheduler state back afterward.

## Scheduler budgets and retries

The outer scheduler timeout must exceed the worst-case serialized phase budget, including broker snapshots, concurrent reviewer timeout, pre-placement recheck, placement, and reconciliation. Do not set the wrapper timeout equal to one inner model timeout.

Retry only safe read/research/reporting tasks. Do not blindly retry an execution cycle; if execution retry is required, use the exact same stable client order ID and reconcile before any resubmission. For once-daily tasks, write the completion marker only after successful exit so transient failure can be retried.

When launch is pending:

- keep application autonomy disabled;
- pause recurring execution jobs to avoid noise or accidental state drift;
- leave research/read-only jobs running if useful;
- schedule a market-hours proposal-only readiness run that cannot place an order and must return either NO TRADE or a fully specified proposal for user confirmation.
