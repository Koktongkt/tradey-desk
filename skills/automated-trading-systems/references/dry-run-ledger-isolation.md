# Dry-run ledger isolation and dashboard truth

## Failure pattern

A simulated AAPL fixture used a fixed bid/ask and deterministic limit price. Replaying it twice created two `proposed` rows plus two `rejected: dry_run_no_execution` rows in the operational order ledger. No broker order existed and the confirmed-fill journal was empty, but the dashboard interpreted the two proposals as reviewer agreements and displayed them in an order log.

The execution blocker worked; the reporting boundary failed.

## Root cause

The dry-run branch changed its input source but reused production output paths. Test and production execution shared:

- the operational order ledger;
- private production reviews;
- public disagreement/order data;
- dashboard aggregation rules that counted every `proposed` row as agreement.

A final `dry_run_no_execution` rejection cannot undo an earlier operational append.

## Durable design

Choose paths before any append:

```python
def output_paths(root, dry_run):
    if dry_run:
        artifacts = root / "test_artifacts"
        return (
            artifacts / "dry_run_order_ledger.jsonl",
            artifacts / "dry_run_reviews.jsonl",
            artifacts / "dry_run_disagreements.jsonl",
        )
    return (
        root / "order_ledger.jsonl",
        root / "private" / "reviews.jsonl",
        root / "public" / "disagreements.jsonl",
    )
```

Apply this to every non-executing mode, including fixture replay and live-data dry review. The scheduler should invoke only the production command without dry-run flags.

## Regression test

Use a temporary root, copy only the minimum fixture/config, run the simulated path, and assert:

1. the run is deterministically blocked;
2. operational order and review files do not exist or are byte-identical;
3. test-artifact ledgers contain the expected proposed/rejected lifecycle;
4. no broker placement function was called.

Observe the test fail against the old shared-path implementation before changing production code.

## Cleaning existing contamination

1. Identify rows using stable evidence/test IDs, not price alone.
2. Archive exact matching rows under `test_artifacts/`.
3. Assert the expected number of removals before rewriting any source ledger.
4. Remove matching private fixture reviews as well as public order rows.
5. Confirm the trade journal remains broker-fill-only.
6. Rebuild the dashboard and run its public-output scan.
7. Verify semantic counts: zero dry-run rows, zero simulated proposals/agreements, and broker-confirmed trade count unchanged.
8. Deploy and compare local versus remote artifact checksums.

## Dashboard semantics

- `confirmed_trades` comes only from the broker-confirmed fill journal.
- `agreements` must exclude fixtures and dry runs; path isolation is the primary control.
- A proposal is not a trade, and a rejected dry run is not an order attempt at the broker.
- Research candidates and blocked reviews may remain visible, but labels must not imply broker execution.
