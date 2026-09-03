# Tradey Desk operating rules

- Paper mode only. Never change `enabled` or `broker_mode` without explicit user confirmation.
- Never add options, crypto, OTC, ETF/ETN/fund, short-sale, market-order, or margin paths.
- Every order path must stay dual-model consensus plus deterministic validation plus broker MCP readback.
- Tests must be written and observed failing before behavior changes.
- Dashboard output must remain sanitized; never expose account identifiers, broker order IDs, secrets, prompts, private reviews, or filesystem paths.
