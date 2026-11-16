# Test-suite reduction design

**Date:** 2026-11-16
**Status:** design approved in chat; awaiting written-spec review
**Base:** `main` at `bdb01dc`, isolated worktree `.worktrees/test-reduction`

## Goal

Reduce the amount of test code Tradey Desk maintains, measured in lines,
while keeping every behavioural guarantee the suite currently provides.

Success means the combined test footprint shrinks. The footprint is
`tests/*.py` plus the root `test_*.py` files plus any new shared helpers.
The suite stays green, and line/branch coverage of production code
shows no unexplained loss.

## Non-goals

- Not reducing test count for its own sake. A smaller count is a side effect.
- Not speeding up the suite. Runtime is reported, not optimised.
- No change to production code, trading gates, risk limits, schedules,
  `autonomy_config.json` or broker paths. If removing duplication would
  need a production refactor, work stops and the user is asked.
- No removal of a test for a retired experiment, one-off probe or
  completed migration without the user's explicit per-item decision.

## Baseline (observed at `bdb01dc`)

- 100 modules in `tests/`, 2,141 test methods, 38,257 lines.
- 8 helper files, 734 lines.
- 3 root-level test files, 507 lines.
- Production Python: 98 files, 25,182 lines.
- Manifest layers: fast 66, scenario 31, full_only 3.

Phase 1 re-measures all of this, with the canonical runner and coverage,
before any edit.

## Phase 1: read-only inventory

1. Provision the hash-pinned ignored fixtures and the dependency-visible
   invocation already proven for this host. Without those, about 40
   baseline tests fail for environmental reasons.
2. Run `tests/run_tests.py full` and raw discovery. Record counts, skips,
   per-module timings and the offline-boundary summary.
3. Capture line and branch coverage with coverage.py and export it as JSON.
   Store it, with logs and hashes, in private, immutable evidence.
4. Inventory every test method: inputs, assertions, mocked boundaries
   and the production call path. Identify:
   - repeated setup and fixture construction;
   - near-identical tests that differ only in input values;
   - tests asserting a subset of what another test on the same path asserts;
   - the three root-level `test_*.py` files and how they relate to
     the canonical `tests/` modules.
5. Build the **retired-experiment list**. Each entry gives the test,
   its origin (probe, migration, spike), what it guarantees, whether any
   production code it exercises is still reachable from a scheduled
   entrypoint, and its line count.
6. Report candidate savings per category. Phase 1 makes no edits.

The user reviews the retired-experiment list and decides each entry.

## Phase 2: consolidation

All edits happen in the isolated worktree.

**Allowed changes**

- Extract repeated construction into small factories that return fresh
  objects. Clock, deadline, feed and malformed-input overrides stay
  explicit in each test.
- Combine input variants of one behaviour into a table-driven test with
  labelled `subTest` cases. Every original input and expected result is
  kept, and each case gets fresh state.
- Delete a test only when a named surviving test covers the same code
  path with equal or stronger assertions. If a deleted test had any
  unique assertion, that assertion moves to the survivor.
- Fold the root-level test files into canonical modules, or delete them
  where an equivalent canonical test exists.
- Remove the retired tests the user approved, along with the fixtures
  only those tests used.

**Forbidden changes**

- Merging unrelated workflows into catch-all tests to lower the count.
- Hiding tests in helpers, loops or alternate suites.
- Weakening assertions, adding skips, or loosening clocks or thresholds.
- Expected values computed by the code under test.
- Bare `assert` as the only check in a shared helper. These are removed
  under `python -O`; use `unittest` assertions instead.

**Protected areas.** These are consolidated only with demonstrated
case-parity, never deleted for count:

- paper-only mode and the kill switch;
- instrument restrictions;
- exposure, position, order-count and risk limits;
- quote freshness, spread and limit deviation;
- the earnings blackout;
- reward/risk and attached protection;
- reviewer agreement and hash binding;
- idempotency, broker readback and ambiguous submission;
- ledger durability and operational isolation;
- private/public dashboard separation;
- the offline launch boundary.

Work proceeds module by module. Each changed module needs its own green
run and an original-to-survivor mapping before moving on.

## Verification

1. Full suite and raw discovery pass with the same invocation as the
   baseline, using equivalent counts from TestLoader/TestResult. Zero
   failures, errors and unexpected skips. The isolation and offline
   boundary checks must stay clean.
2. Compare line and branch coverage per production file, excluding tests.
   Every executed line or branch lost is investigated and either
   restored or explained.
3. For table-driven migrations, an executable parity probe outside the
   canonical suite runs the pre-edit tests and the survivors. It
   compares production-call arguments and assertion events, keeping
   multiplicity.
4. An independent adversarial reviewer checks the frozen diff, the
   mappings and the coverage comparison. The verdict is bound to source
   hashes.

## Release

- Report before and after for test lines, helper lines, the combined
  footprint, test methods, executed checks and coverage.
- Fewer methods and fewer executed checks are reported separately.
- Promotion to live Tradey and publication to GitHub happen only with
  the user's approval. Writers are paused, the live suite is verified,
  operational state is confirmed unchanged, and the exact same jobs are
  restored.

## Risks

- **Silent coverage loss from a deletion.** Mitigated by per-file
  coverage comparison, the parity probes and independent review.
- **Shared fixtures leaking state between cases.** Mitigated by fresh
  factories and mutation probes.
- **Concurrent commits to `main` during the work.** The candidate is
  rebased and fully re-verified before release; no force-push.
- **Retained fixtures pruned from scratch.** Evidence goes to a durable
  private location with a hash manifest.
