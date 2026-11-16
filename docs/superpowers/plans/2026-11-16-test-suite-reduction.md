# Test-suite reduction implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink Tradey Desk's maintained test code, measured in lines, without losing any behavioural guarantee or production coverage.

**Architecture:** First, a read-only Phase 1 measures a coverage baseline and inventories duplication and retired-experiment tests. The user decides each retired entry. Phase 2 then consolidates module groups in an isolated worktree. Every change is backed by an original-to-survivor mapping, a green module run and a per-file coverage comparison. Release is gated on independent review and user approval.

**Tech Stack:** Python 3.14 `unittest`, the repository runner `tests/run_tests.py` with `tests/test_manifest.json`, and coverage.py (scratch-only, never in production environments).

**Spec:** `docs/superpowers/specs/2026-11-16-test-suite-reduction-design.md`

## Global Constraints

- Production code, `autonomy_config.json`, `watchdog_config.json`, schedules, broker paths and Hermes stay unchanged. If removing duplication needs a production refactor, stop and ask the user.
- Work only in `.worktrees/test-reduction`, on branch `refactor/test-suite-reduction`. The live checkout stays read-only until release is approved.
- No retired-experiment test is removed without the user's per-item decision.
- Protected areas are never deleted for count. They are paper-only mode and the kill switch; instrument limits; exposure, position, order-count and risk limits; quote freshness, spread and limit deviation; the earnings blackout; reward/risk and attached protection; reviewer agreement and hash binding; idempotency, readback and ambiguous submission; ledger durability and operational isolation; private/public separation; and the offline boundary. They may be consolidated only with demonstrated case-parity.
- Forbidden: catch-all tests, tests hidden in helpers or loops, weakened assertions, new skips, loosened clocks or thresholds, expected values computed by the code under test, and bare `assert` as a helper's only check.
- Footprint counts all of `tests/*.py`, the root `test_*.py` files and every new helper. Moved code is not a saving.
- Evidence lives in `$EVID=/home/hermes/.local/share/tradey/evidence/test-reduction-20261116`, with directories at mode 0700 and files at 0600. It is never placed under the repository's `private/`, because the isolation audit snapshots that tree.
- coverage.py installs only into `$EVID/tools`, through `pip install --target`. It is never installed into the Tradey or Hermes virtual environments.

## Review Focus

1. **Shared factories leaking mutated state between subTest cases.** Each case must get fresh nested objects. Task 5 adds a mutation probe for each factory introduced.
2. **A deleted test with one unique assertion hidden among duplicated ones.** Task 5 mappings list every assertion of a deleted test and where it now lives.
3. **Root-level `test_*.py` shadowing canonical modules under raw discovery.** Task 4 checks that canonical and raw counts match after folding them in.
4. **Fixture-gated tests silently skipping after fixture cleanup.** Task 6 requires zero skips and compares per-module time with the baseline.
5. **`main` advancing during the work.** Task 7 rebases onto the newest `main` and reruns every gate on the exact rebased tree.

---

### Task 1: Reproducible gate runner and fixture provisioning

**Files:**
- Create: `$EVID/run_gate.py`, `$EVID/provision.py`, `$EVID/fixture-manifest.json`, `$EVID/parity.py`, `$EVID/compare_coverage.py`
- No repository files change.

**Interfaces:**
- Produces: `python $EVID/run_gate.py <label> <root> full|raw|module:<name> [--coverage]`, which writes `$EVID/runs/<label>.{stdout,stderr,json}`. The JSON holds `exit_code`, `tests`, `failures`, `errors`, `skipped`, `argv`, `env_allowlist`, `source_tree_sha256` and `started_at`/`finished_at`.
- Produces: `python $EVID/provision.py <root>`, which copies hash-pinned ignored fixtures into `<root>` and fails on any digest mismatch.
- Produces: `python $EVID/parity.py <group>`. It runs the baseline bytes of the group's modules, taken from `baseline-source.json`, from a scratch copy, then the current modules. Each run uses `sys.setprofile`, which records calls into repository production modules as `(qualified name, repr of bound args)` with temporary paths and timestamps normalised, and patched `unittest.TestCase.assert*` methods, which record assertion events. It writes `$EVID/parity/<group>.json` with `missing` and `added` event multisets, and exits nonzero when `missing` is nonempty.
- Produces: `python $EVID/compare_coverage.py <base-label> <final-label>`. It writes `$EVID/coverage-diff.json`, which maps each production file to its `lost_lines` (baseline executed minus final executed) and `lost_branches` (arc tuples). Files edited by the candidate are flagged for statement alignment rather than raw line subtraction; under this plan's constraints no production file should change.

- [ ] **Step 1: Create `$EVID` at mode 0700 and install coverage into `$EVID/tools`**

Run: `umask 077; mkdir -p $EVID/tools && /home/hermes/.local/share/tradey/venv-linux/bin/python -m pip install --target $EVID/tools coverage`
Expected: `import coverage` succeeds only with `$EVID/tools` on `PYTHONPATH`. The Tradey venv's `pip list` is unchanged.

- [ ] **Step 2: Write `provision.py`**

It copies regular-file fixtures from the live checkout's `test_artifacts/` into the target. It covers:
- `stage2_acquisitions/*.response.raw`;
- `discovery-quality-first/frozen-labels.json` and the six `six-lane-historical-audit-20261022T005728Z` inputs;
- `dashboard-mcp/fix1-native-envelopes.json`;
- `identity_handoff/`;
- `publication-hybrid-validation/{dataset.json,captures/}`;
- `recovery-fair-handoff/incident-*.json`.

It creates `test_artifacts/project-extraction/` at 0700. It materialises tracked `.py` files of revision `835c56c` into `test_artifacts/focused-coverage-25/task6-baseline-835c56c/`. Every copy is recorded with its sha256 in `fixture-manifest.json`. It refuses to overwrite differing bytes and never copies journals, SQLite files or configuration.

- [ ] **Step 3: Write `run_gate.py`**

The interpreter is `/home/hermes/.local/share/tradey/venv-linux/bin/python`. The per-process `PYTHONPATH` is, in order:
1. Tradey site-packages;
2. `/home/hermes/.hermes/hermes-agent`;
3. the installed Hermes venv site-packages, resolved at run time from `runtime_paths.hermes_runtime()`;
4. `$EVID/tools`, only with `--coverage`.

Set `PYTHONDONTWRITEBYTECODE=1`, `HERMES_DISABLE_LAZY_INSTALLS=1`, `TRADEY_UNPATCHED_ROOT`, `TRADEY_OPPORTUNITY_FLOOR_SOURCE` and `TRADEY_MEMORY_ROLLBACK_SOURCE`. The last three point at the live checkout's retained `test_artifacts` paths.
- `full` runs `tests/run_tests.py full`.
- `raw` runs `-m unittest discover -s tests`.
- `--coverage` wraps the run in `coverage run --branch --parallel-mode --source=<root> --omit='tests/*,test_*.py,test_artifacts/*'`, then `coverage combine` and `coverage json -o $EVID/runs/<label>.coverage.json`.
- Parse the counts from the runner's `TIER_RESULT` and unittest's `Ran N tests` lines.

- [ ] **Step 4: Verify on an unchanged copy**

Run: `python $EVID/provision.py <worktree> && python $EVID/run_gate.py smoke <worktree> module:test_safety`
Expected: exit 0 and 69 tests. Then `git -C <worktree> status --short` shows only ignored paths, with no tracked changes.

- [ ] **Step 5: Self-test `parity.py` and `compare_coverage.py`, writing `parity.py` and `compare_coverage.py` first to the interfaces above**

Plant a loss in a scratch copy of `tests/test_safety.py`, never in the worktree: delete one assertion, then separately delete one test.
Expected: `parity.py` reports a missing event for the deleted assertion, and `compare_coverage.py` reports a lost line or branch for the deleted test. A tool that misses a planted loss is fixed before Task 2.

---

### Task 2: Baseline

**Files:** evidence only.

**Interfaces:**
- Produces: `$EVID/runs/baseline-full.*`, `$EVID/runs/baseline-raw.*`, `$EVID/runs/baseline-full.coverage.json` and `$EVID/baseline-source.json`. The last records the worktree HEAD and the sha256 of every `tests/*.py` and root `test_*.py` file.

- [ ] **Step 1: Run `run_gate.py baseline-full <worktree> full --coverage`**

Expected: exit 0; 2,141 or more tests; 0 failures, 0 errors, 0 skipped; `unexpected_actual_hermes_attempts: 0`.

- [ ] **Step 2: Run `run_gate.py baseline-raw <worktree> raw`**

Expected: exit 0, with a test count equal to the full tier.

- [ ] **Step 3: Freeze the baseline**

Write `baseline-source.json` and set the baseline files read-only (chmod 0400). If either gate is not clean, stop and report: a dirty baseline voids every later comparison.

---

### Task 3: Inventory and retired-experiment list (read-only)

**Files:**
- Create: `$EVID/inventory.py`, `$EVID/inventory.json`, `$EVID/retired-candidates.md`, `$EVID/consolidation-candidates.md`

**Interfaces:**
- Produces: `inventory.json`, with one entry per test method: `module`, `class`, `name`, `lines`, `asserts` (count), `patched_targets`, `production_calls` (resolved names), `fixtures_read` (paths) and `setup_hash` (the normalised AST of setUp and inline construction).

- [ ] **Step 1: Write `inventory.py` with `ast`**

Group methods by identical `setup_hash` (repeated setup) and by identical body after replacing literals with placeholders (input-variant clusters). Flag subset pairs: same `production_calls`, and one method's normalised assertions contained in another's. Flag modules or methods whose imports or fixture paths name probe, spike, migration, cutover or historical-audit artefacts.

- [ ] **Step 2: Classify each retired candidate**

For each flagged item, determine:
- whether the exercised production function is still reachable from a scheduled entrypoint (`run_cycle.py`, the `cron/*.sh` targets, `watchdog_cli.py`), using the existing `graphify-out` call edges plus a grep check;
- its origin commit, via `git log -S`;
- its line count.

Write one row per item to `retired-candidates.md`: test, origin, guarantee in one sentence, reachable yes/no, lines, recommendation. Protected-area tests are listed as "keep".

- [ ] **Step 3: Write `consolidation-candidates.md`**

Give each module's estimated saving by category: setup extraction, table-driven merge, subset deletion and root-file fold. Sort by saving, largest first.

- [ ] **Step 4: Stop for user decisions**

Send the user the totals and a link to the retired list. Do not start Task 4 until each retired item has a recorded decision in `$EVID/decisions.json`.

---

### Task 4: Root-level test files

**Files:**
- Modify or delete: `test_reconciliation_cli.py`, `test_managed_reconciliation.py` and `test_autotrader_reconciliation.py` at the repository root; their canonical counterparts in `tests/`; `tests/test_manifest.json`.

- [ ] **Step 1: Map each root method to a canonical method with equal or stronger assertions, or mark it unique**

Write the mapping to `$EVID/mappings/root-files.json`.

- [ ] **Step 2: Move unique methods into the canonical module, delete the root files, and update the manifest only if module names changed**

- [ ] **Step 3: Verify**

Run `run_gate.py root-module <worktree> module:<each affected>`, then `raw`.
Expected: green. Raw count equals full count. No test in the mapping is lost.

- [ ] **Step 4: Commit**

`git commit -m "test: fold root-level reconciliation tests into canonical modules"`

---

### Task 5: Module-group consolidation (repeat per group)

Groups are taken from `consolidation-candidates.md`, in order of saving. One commit per group. A group is a single module, or modules sharing one fixture file.

**Files:**
- Modify: the group's `tests/test_*.py`.
- Create only when two or more modules share the construction: `tests/<area>_factories.py`.

**Interfaces:**
- Factories are named `make_<object>(**overrides) -> <fresh object>`. They return new nested dicts and lists on every call, and never take a clock implicitly; tests pass `now=` explicitly.

- [ ] **Step 1: Write the mapping before editing**

`$EVID/mappings/<group>.json` lists every original method → survivor and subTest label, its assertions, its inputs and its expected values.

- [ ] **Step 2: Edit**

Apply only the allowed changes from the spec. Apply the user's retired decisions for this group, deleting fixtures used only by removed tests.

- [ ] **Step 3: Add a factory mutation probe for each new factory**

The probe is a test that mutates one result and asserts a second call is unaffected.

- [ ] **Step 4: Run the parity probe**

`$EVID/parity.py <group>` loads the pre-edit module from `baseline-source.json` bytes outside the checkout, runs the originals and survivors with production calls traced, and compares calls and assertion events with multiplicity preserved. Only temporary paths and wall-clock timestamps may be normalised.
Expected: no missing events.

- [ ] **Step 5: Run `run_gate.py <group> <worktree> module:<each>`**

Expected: green, with zero skips.

- [ ] **Step 6: Record the line delta and commit**

Record test, helper and net lines in `$EVID/ledger.json`. Commit with `git commit -m "test: consolidate <group>"`.

---

### Task 6: Final verification and review

- [ ] **Step 1: Run `run_gate.py final-full <worktree> full --coverage` and `run_gate.py final-raw <worktree> raw`**

Expected: both exit 0, with zero failures, errors and skips, clean isolation and equal counts.

- [ ] **Step 2: Compare coverage**

`$EVID/compare_coverage.py baseline-full final-full` writes per-file lost lines and branches to `$EVID/coverage-diff.json`.
Expected: an empty loss list, or every entry restored or explained.

- [ ] **Step 3: Compare skips and per-module time with the baseline**

A fixture-gated module running in a fraction of its baseline time is investigated as a silent skip.

- [ ] **Step 4: Independent review**

A fresh reviewer receives the frozen diff, all mappings, the parity results, the coverage diff and a sha256 manifest of the changed files. Blocking findings are fixed and re-reviewed. The verdict must match the current hashes.

- [ ] **Step 5: Write `$EVID/report.md`**

It gives before and after for test lines, helper lines, combined footprint, test methods, executed checks and coverage, plus the retired decisions applied.

---

### Task 7: Release (only after user approval)

- [ ] **Step 1: Rebase onto the latest `main` if it has advanced**

Reverify the reviewed hashes, and rerun Task 6 Steps 1–3 on the exact rebased tree.

- [ ] **Step 2: Promote**

Promote with the established procedure:
1. persist the job states;
2. pause the eight live Tradey jobs and confirm no worker is running;
3. snapshot operational state;
4. `git merge --ff-only` in the live checkout, keeping a recovery ref;
5. run the full and raw gates on the live tree;
6. compare operational state;
7. push and verify `ls-remote`;
8. resume exactly the paused jobs and read back their settings unchanged.

- [ ] **Step 3: Report**

Report deployment, publication, schedule restoration and the first observed scheduled run as separate states.
