# Layered deterministic test workflow

Use this workflow when changing automated-trading code, policy, or its operating skill. The goal is fast feedback without replacing precise capital-protection checks with a small, opaque end-to-end suite.

## Test layers

1. **Focused RED test** — add the smallest regression test, run it alone, and require the expected failure before changing production behavior.
2. **Fast contracts** — safety gates, broker/data normalization, durable storage, reconciliation primitives, and test-architecture checks. Target seconds, not minutes.
3. **Scenario workflows** — deterministic vertical workflows using real orchestration and persistence with only network, model, broker transport, and deployment boundaries replaced. These cover research/reuse, proposal review, placement/readback, ambiguous recovery, managed exits, diagnostics, notifications, and public projection.
4. **Full deterministic suite** — union of fast, scenario, and deeper research-path cases. Run before independent review and release.
5. **External smoke** — explicit, non-persisting checks for credentials, provider schemas, exact model commands, market-data entitlement, and broker reads. Run only when the changed boundary requires them.
6. **Paper-order canary** — never part of normal tests. If ever required, use a separately controlled paper account, unique identifiers, attached protection, cleanup/reconciliation, and an explicit release decision.

Do not replace safety predicates with scenario tests. Preserve direct deterministic coverage for paper-only mode, kill switch, instrument eligibility, no short/margin/market paths, exposure/order/risk limits, quote freshness/feed/spread/deviation, earnings state, reward/risk, attached protection, reviewer agreement/hash binding, idempotency, broker readback, ambiguous submission, ledger durability, and private/public isolation.

## Manifest rules

Keep every `tests/test_*.py` module in exactly one layer in `tests/test_manifest.json`:

- `fast`
- `scenario`
- `full_only`

The test runner must fail on an unclassified, unknown, or multiply classified module. `full` is the ordered union of all three layers. Keep raw `unittest discover` as a release cross-check and require the same test count as the manifest-driven full run.

## Isolation rules

Normal deterministic tiers must not:

- open live provider or broker connections;
- invoke real model or deployment commands;
- depend on credentials or a sibling checkout;
- write operational ledgers, databases, caches, or diagnostics;
- change operational-file metadata.

Use temporary roots selected before the first write. Snapshot root operational ledgers plus the private tree before and after each tier; content, creation/deletion, size, or metadata changes fail the tier. Dry-run output belongs under isolated test artifacts.

## Runtime rules

Never use production-scale sleeps to simulate a stuck worker. Use a short explicit collection deadline and an event-blocked worker released in `finally`; preserve the assertion that the worker was still alive at the deadline without making process shutdown wait for the production timeout.

Print per-module timing in every tier. Treat one module dominating runtime as a test-design defect, then remove real waits or uncontrolled external work without weakening the asserted behavior.

## Change sequence

1. Pause all producers, execution consumers, reconciliation writers, post-close writers, and dashboard deployers that use the tree.
2. Write and observe the focused RED test.
3. Implement the minimum change and make the focused test green.
4. Run the affected module and the relevant `fast` or `scenario` tier.
5. Update the manifest for every new, removed, or renamed test module.
6. Run `fast`, `scenario`, `full`, and raw discovery; require clean operational-isolation checks and equal full/raw counts.
7. Run only the external non-persisting smoke checks required by changed boundaries.
8. Obtain independent adversarial review of the frozen diff; fix blockers with new RED tests and re-review.
9. Synchronize production and mirror by hash, rerun production tests, commit/push, verify the remote ref, then resume the exact paused jobs.

## Consolidation rules

Consolidate duplicated setup with fixtures and parameterized cases, but delete a regression only when another test covers the same behavior and path with equal or stronger assertions. Preserve tests for previously observed failures, fail-closed branches, capital limits, idempotency/crash recovery, persistence, normalization, and privacy boundaries. Migrate useful tests from files outside canonical discovery before deleting those files; never leave a hidden second suite.
