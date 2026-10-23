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
- Synthesis/intake may attempt up to **five distinct ranked evidence-eligible
  candidates**, stopping at first success, shared-budget exhaustion or an
  infrastructure failure. There is no per-candidate time cap: each receives
  only the unspent shared allowance, bounded by the absolute deadline.
- Discovery remains at most five candidates; focused retrieval allocations,
  three-candidate later rescue, at least two publisher-domain eligibility,
  retry classifications, trading gates and process containment are unchanged.
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
absolute deadline clipping, deferred rescue, the then-current three-attempt cap, infrastructure
failure termination, invalid date preservation/rejection and valid short/swing
intake, including New York midnight and DST prompt anchors.

## Cadence / five-candidate follow-up verification

On isolated baseline `b70f1d3`, the full manifest runner passed 1640 tests
(zero failures/errors, four pre-existing skips, exit 0) after provisioning frozen
ignored fixtures and the pinned unpatched-runtime source snapshot. Initial runs
without those prerequisites failed and remain in ignored test evidence.

Observed RED: real `run_cycle.main()` never reached the mocked execution boundary
at approved :18/:38/:58 fires; the synthesis loop stopped after three local
rejections and never reached a qualified fifth candidate. Both ranked-batch cap
tests also stopped at three. GREEN: manifest full and raw discovery each ran
**1643 tests, zero failures/errors, four pre-existing skips, exit 0**. Operational
isolation passed; both reported zero unexpected actual Hermes launches and zero
unexpected local controls. No live research, broker calls or deployment ran.

Coverage includes EDT/EST and both DST-transition Mondays, weekend/open/close
fences, first-four intake rejections followed by fifth success, no sixth attempt,
distinct-symbol deduplication across deferred batches, shared synthesis/enrichment
exhaustion, absolute deadline clipping and unchanged infrastructure aborts. The
loop audit found only the two changed synthesis caps; the separate three-candidate
rescue cap remains unchanged. Budgets remain exactly 270 synthesis / 90 enrichment /
960 overall / 990 wrapper seconds, without per-candidate caps.

## Wrapper inspection and limits

Application cron shell entrypoints and read-only inspected Hermes shell shims
only exec their targets; none adds a shorter timeout. Read-only inspected cron
records have no per-job script timeout; config has no script-timeout override;
installed scheduler source defaults to 3600 seconds and the inspection process
had no `HERMES_CRON_SCRIPT_TIMEOUT` environment override. A separately configured
service environment is not established by that inspection.

The approved consumer grid is now `18,38,58 13-20 * * 1-5` UTC, with the
unchanged weekday market window accepting 09:38/09:58 and 10:18–15:58 ET.
The application predicate and versioned schedule agree; this source change does
not mutate installed jobs. Nominal spacing is not a non-overlap guarantee.
Prior `invalid_horizon` root cause is
not established; prompt regression success is not live model-output acceptance
or a guarantee of candidate qualification.
