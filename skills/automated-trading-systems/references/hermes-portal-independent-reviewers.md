# Hermes Portal: isolated multi-model reviewers

Use this pattern when a safety-critical decision requires two different models behind one Nous Portal OAuth subscription.

## Why not delegation or MoA

- `delegate_task` has one global `delegation.model` pin for a batch, so it cannot assign a different model to each child.
- Mixture of Agents is advisory synthesis: the aggregator sees reference outputs, and a failed reference does not necessarily abort. That is unsuitable for strict independent consensus.

## Process boundary

Launch one Hermes process per reviewer with an explicit provider/model pair. Keep the calls concurrent but independent. A safe command shape is:

```text
/opt/hermes/bin/hermes chat -Q \
  --source tool \
  --provider nous \
  -m <canonical-model-id> \
  -t '' \
  --safe-mode \
  --max-turns 1 \
  --run-budget 120 \
  --query-file -
```

Send the complete review prompt and normalized evidence on stdin. `--safe-mode` prevents inherited configuration, project rules, plugins, MCP servers, memory, and skills from contaminating the decision. The empty toolset is defense in depth. `--source tool` keeps these implementation calls out of ordinary user session lists.

## Implementation invariants

1. Serialize the immutable evidence once with deterministic key ordering; pass byte-equivalent content to both processes.
2. Never put evidence in command-line arguments: it leaks into process listings and can exceed argument-length limits.
3. Parse only a strict JSON object and validate it against the decision schema.
4. Convert timeout, nonzero exit, malformed output, missing fields, or low confidence to reviewer-unavailable/no-consensus.
5. Never average differing orders. Require exact equality of executable fields.
6. Keep reviewer processes free of broker credentials and execution tools.

## Migration verification

- Confirm the canonical model IDs in the live Portal catalog.
- Smoke-test each model with a harmless exact-JSON prompt.
- Add failing tests before changing production routing.
- Remove legacy direct-provider HTTP code and API-key requirements.
- Scan the repository for stale provider endpoints, key names, old model IDs, and fallback functions.
- Run the full safety suite.
- Invoke the exact production review helper with synthetic incomplete evidence and verify both reviewers return `HOLD` or otherwise block consensus.
- Run the normal desk entry point and verify `enabled=false` still produces the expected autonomy blocker.

A successful model response verifies inference connectivity only. It does not verify broker authorization, paper-order lifecycle, or live trading.
