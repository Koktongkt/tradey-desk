# Research budget / horizon verification

Scope: application source, offline tests and documentation only. No deployment,
Hermes core/configuration edits, schedule edits, live research, broker calls or
production ledger writes.

## Contract

- Active research deadline: 690 → 960 seconds.
- Application research wrapper: 720 → 990 seconds; 30 seconds overhead retained.
- Synthesis: shared 90-second wall-clock phase (including enrichment) and
  60-second subprocess / advisory 45-second model limit replaced by **270
  cumulative synthesis seconds**, with each subprocess bounded by the remaining
  shared allowance and absolute deadline. Tool-free, one-turn posture retained.
- Enrichment: **45 → 90 cumulative seconds**, separately charged across candidates.
- Discovery, focused retrieval, evidence/recovery caps, maximum three synthesis
  attempts, retry classifications, trading gates and process containment retained.
- Horizon changes are prompt-only: actual UTC/New York as-of anchors, future
  timezone-aware UTC ISO 8601 exit, 1–30 entry-inclusive holding sessions,
  setup-appropriate short/swing. No date repair or calendar/gate changes.

## Offline evidence

Baseline revision: `16e3f9a` on an isolated worktree. Initial baseline failed on
missing ignored fixture inventories/source snapshots; the existing frozen inputs
were copied into the worktree, not regenerated or committed. With
`TRADEY_UNPATCHED_ROOT` pointing to that worktree's existing pinned comparison
snapshot, baseline discovery ran **1635 tests, zero failures/errors, four skips**
(exit 0). Baseline emitted pre-existing SQLite ResourceWarnings.

Observed RED tests demonstrated:

1. A controlled 100-second synthesis could not run with the old 60-second cap.
2. Both radar/premarket wrappers still supplied 720 rather than required 990.
3. The synthesis prompt lacked exact current as-of anchors and horizon contract.

GREEN full-suite command (run from the worktree; no output pipeline):

```bash
TRADEY_UNPATCHED_ROOT="$PWD/test_artifacts/focused-coverage-25/task6-unpatched-runtime" \
  python tests/run_tests.py full > /path/to/private/full.log 2>&1
result=$?
printf 'FULL_RUNNER_EXIT=%s\n' "$result"
exit "$result"
```

The full manifest-aware offline suite ran **1640 tests, zero failures/errors,
four pre-existing skips**, exit 0. Offline-boundary readback reported zero
unexpected actual Hermes launches and zero unexpected local controls; the
operational-state isolation audit passed. Existing real-child lifecycle tests
also passed, including outer-timeout reaping before a successor.

New/updated regression coverage includes 100-second rejected candidate synthesis
plus 40-second enrichment, then 160-second successful alternative synthesis plus
40-second enrichment; exact subprocess allowances are 270 then 170, proving the
shared synthesis clock is not a renamed 360-second wall-clock pool. Other cases
cover cumulative enrichment exhaustion, minimum launch and preparation windows,
absolute deadline clipping, deferred rescue, three attempts, infrastructure
failure termination, invalid date preservation/rejection and valid short/swing
intake, including New York midnight and DST prompt anchors.

## Wrapper inspection and limits

Application cron shell entrypoints and read-only inspected Hermes shell shims
only exec their targets; none adds a shorter timeout. Read-only inspected cron
records have no per-job script timeout; config has no script-timeout override;
installed scheduler source defaults to 3600 seconds and the inspection process
had no `HERMES_CRON_SCRIPT_TIMEOUT` environment override. A separately configured
service environment is not established by that inspection.

The current consumer grid can overlap the longer research envelope. Scheduling
review/rollout remains the parent's task. Prior `invalid_horizon` root cause is
not established; prompt regression success is not live model-output acceptance
or a guarantee of candidate qualification.
