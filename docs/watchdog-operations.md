# Watchdog operations (monitoring only)

The position/portfolio watchdog is a read-only monitoring lane. It never holds
trading authority, never repairs operational data, and never blocks the
autotrader: its lock, outputs, and completion markers live solely under its
selected output root.

## Running

```bash
python3 watchdog_cli.py mechanical            # :05 in-session protection sweep
python3 watchdog_cli.py daily                 # close+15..close+45 reporting run
python3 watchdog_cli.py eligibility           # print the proposed cron expressions
```

**Concrete read/source/classification adapters are wired for bounded monitoring.**
Non-fixture CLI invocations use `watchdog.runtime.configured_broker`: an isolated
paper-only collector subprocess, with at most a 90-second timeout clamped to
the remaining run active/outer deadline, and process-group cleanup on normal
exit or timeout. Submitted intents, confirmed lifecycle rows
and protective references are obligations; unsubmitted rejected proposals are
not broker orders. A missing submitted reference still makes coverage unknown.
The requested activity interval is 90 days, explicitly not lifetime accounting.
The benchmark adapter runs the existing Massive loader in a separate 30-second
worker and never manufactures missing strategy marks or total-return capability.

`--cron` emits sanitized alert text for supported Hermes script-only cron delivery.
It returns no receipt. Schema 1 retains the legacy pending-outbox replay described
below; after explicit `apply-notification-policy`, schema 2 uses independent
emission/suppression bookkeeping and does **not** replay historical pending alerts.
The concise policy is documented in [watchdog-notifications.md](watchdog-notifications.md):
current urgent conditions remain immediate, closed verified positions are omitted,
and one plain-English daily summary replaces individual setup/coverage warnings
and routine report-installed lines. No acknowledgment is fabricated; pending
outbox rows remain audit evidence. The schema-1 delivery notes below are retained
for rollback/legacy context, not the activated policy.
Mechanical successful no-exception runs and out-of-slot runs are silent. No job registration
is performed by the CLI. Concrete workers are now configured; reviewed source
profiles, provider isolation, and known earnings/financial-content limitations
are documented in `watchdog-runtime-readiness.md`. Gaps remain visible and never
become an all-clear. The user approved scheduling with these explicit gaps.

Offline and confined verification:

- `--fixture` CLI invocations remain broker-unwired and fail closed. Inject
  fake adapters into `run_watchdog` for full offline read/commit/report tests.
- `--smoke` is a DRY-RUN commit: run/portfolio/attribution evidence only — no
  condition transitions, no outbox rows, no source cutoffs, no baselines —
  and no alert send or report/publication (asserted: no `latest.json`, no
  `public/`, empty `condition_state`/`alert_outbox`). A smoke probe can
  therefore never arm the 24h condition quiet window or suppress a real
  alert. Its output may sit under `test_artifacts/watchdog` even when nested
  inside the operational root (`test_artifacts` is a documented
  non-operational exception to the overlap rule; smoke-only — real runs may
  never nest output inside the operational root). Task 9 smoke expectation:
  a wired transport/broker still sends and publishes nothing under `--smoke`,
  and unconfigured adapters keep failing closed.

Options:

- `--root PATH` — operational storage root (default: the checkout root).
- `--output-root PATH` — where `private/watchdog/` is created (default: `--root`).
- `--fixture` — confine both roots beneath `test_artifacts/watchdog`; any
  operational output choice is rejected (`fixture_output_confined`).
- `--smoke` — live smoke: dry-run commit (no condition state, no outbox, no
  source cutoffs), no alert send, no report/publication. Defaults output to
  `test_artifacts/watchdog/smoke`; explicit output outside
  `test_artifacts/watchdog` is rejected before any broker read.
- `--cron` — sanitized exception-only output for script-only cron relay delivery.
- `--now ISO` — trusted aware clock override (ops/testing). Completion is
  this trusted `now` plus measured elapsed time, never broker capture time.

Unknown actions fail closed with exit code 2 and no side effects.

## Modes and budgets

| Mode      | Outer wall clock | Active work | Report/persistence reserve |
|-----------|------------------|-------------|----------------------------|
| mechanical| 120 s            | 120 s       | 0                          |
| daily     | 900 s            | 840 s       | 60 s                       |

Outer-deadline exhaustion returns a typed `budget_exceeded` result with no
commit. Daily thesis retrieval is additionally bounded (Task 6: 600 s shared
phase cap, 60 s per name, 15 s per URL/fetch, 20 s classification).

## Scheduling (registration is a separate operational change)

Proposed UTC crons (verified against actual session calendars by
`tests/test_watchdog_schedule.py`, including DST transitions, weekends,
holidays and 13:00 NY early closes):

- mechanical: `5 14-21 * * 1-5`
- daily:      `15,45 17-22 * * 1-5`

The code filters every firing against the actual Alpaca session calendar:
mechanical fires only :05 inside a live session; daily only in the
close+15..close+45 window. Scheduler firings outside eligibility are silent
no-ops (`status=no_op`). A missing/invalid calendar is a typed
`schedule_calendar_missing` coverage gap — market-session eligibility is never
guessed. There is one safe bounded reporting retry at the next eligible daily
slot for the same session date, under the stable per-session-date run identity
(`daily:<session_date>`): the retry performs report installation, outbox
delivery and the completion marker ONLY — the committed observation is not
recommitted and thesis retrieval is not re-run (the retry result carries
`reporting_retry=true`, `committed_now=false`, and never claims all-clear on
its own). Execution (retrieval) is never retried mid-run. Retry/identity
checks key on the latest run of the SAME mode, so a later inter-mode run
(clock override or cron lag) cannot misroute them. Commit rejections
(`run_identity_conflict`, `source_cutoff_future`, ...) are typed failed
results with the store reason in `reasons` — never raw exceptions; nothing is
committed and all alerts stay pending. The daily thesis lane evaluates real
criteria: baselines are built (`baseline_from_candidate`) from the exactly
lineage-linked candidate of every managed position; a candidate whose
catalyst is a plain string without a separate event_date records a typed
`baseline_incomplete` gap (reason `thesis_baseline_incomplete`) — a date is
never guessed.

Observation timing: `coverage.captured_at` is the observation-COMPLETION
instant (trusted `now` + measured elapsed), per the recorded ruling
"observation-completion captured_at >= source checked-through, not broker/
start time". Thesis workers are pinned to `checked_through <= supplied now`
(a worker may never claim a future inspection); a violating source is a
typed per-source coverage gap, never a whole-run abort. The run-content
digest excludes the completion
stamp, so repeated runs of the same slot with identical content still
dedupe (equivalent-run skip) despite millisecond completion jitter.

## Paths, locks and failure isolation

- Default outputs: `<output_root>/private/watchdog/` (monitoring.sqlite3,
  latest.json/latest.md generations, `completions/<session_date>.json`).
- External roots are rejected; non-fixture roots must be the checkout root or
  explicitly beneath `test_artifacts`. Operational input/output overlap and
  symlink escapes are rejected before any side effect.
- Locking is a monitoring-only `flock` on `private/watchdog/monitor.lock`
  (LOCK_EX|LOCK_NB). Operational snapshots separately open the **existing**
  ledger lock read-only and acquire a nonblocking shared lock while copying
  and validating authority. No writer lock is acquired, no lock is created or
  repaired, and no ledger lock is held during broker network calls. The kill
  switch is never opened; the watchdog has no trading authority.
- Before worker startup, pure `operational_lock_busy` contention alone is
  retried every at most 100 ms, for at most 5 seconds of monotonic retry window
  and 51 reads. The window is further clamped to the existing active/outer
  deadline (120 s mechanical; 840 s active within 900 s daily). Each attempt
  reacquires a fresh read-only snapshot and repeats digest, sequence, canonical
  JSON, projection parity and metadata gates. Corruption, mutation and missing
  inputs are not contention and are never retried. An oversleep stops further
  reads; measured wait/elapsed includes the oversleep, not just requested sleep.
  No worker is launched at an exhausted deadline and no broker call is retried.
- Eligibility still requires the authoritative broker session calendar. Even
  an out-of-slot fire must first obtain that prerequisite; persistent contention
  or worker failure remains fail-closed, not a guessed silent no-op. Crons,
  source gates and budget constants are unchanged.
- Broker-adapter failures retain a bounded private projection at
  `<output_root>/private/watchdog/failure.json` (latest failure only, atomic
  replacement, directory 0700, file 0600). It includes mode, trusted slot,
  actual start/finish, normalized reason/stage, attempts, measured wait/elapsed,
  worker exit and worker elapsed when available. A strict allowlist excludes
  raw exceptions/stderr, credentials, identifiers, refs, payloads and paths.
  Worker spawn, nonzero exit, decoding, schema, timeout and deadline failures
  remain distinct privately; public failed results/cron text remain generic.
  Untyped broker exceptions never export their text. This writes neither the
  operational SQLite ledger nor a business stream, and fixture/smoke records
  stay in the selected confined output root. The post-eligibility operational
  coverage read retains its existing incomplete-snapshot semantics.
- Diagnostics are best-effort: one <=4096-byte local write, no locks, fsync,
  append stream or network, symlink-safe directory opens and replacement.
  Storage errors do not mask the primary result. Kernel filesystem stalls,
  abrupt termination and the cron hard alarm can still prevent a record;
  this is not a guaranteed durable failure audit or a disk-I/O wall deadline.
  Worker stderr is intentionally discarded, not recovered as historical truth.
- Operational inputs are hashed/ stat-ed before and after every run; a change
  mid-run yields the typed `operational_input_changed_after_run` reason and
  the run is never all-clear. The ledger is WAL-mode, so the sqlite `-wal`/
  `-shm` sidecars are covered whenever they exist — an autotrader write
  landing in `-wal` without a main-db checkpoint is still detected (including
  sidecars created or removed between the before/after snapshots).

## Daily completion and delivery

- The daily completion marker is written only after the observation commit and
  successful report installation. A reporting failure leaves alerts pending;
  the next eligible daily slot retries reporting/delivery only.
- Equivalent runs (same trusted slot, identical digest) skip duplicate work
  but still drain the outbox.
- Every pending alert — including alerts from older runs — is rendered with
  `render_alert` and handed to the configured transport callback. Only a
  genuine provider receipt (`provider`, `message_id`, `status='delivered'`,
  aware `verified_at`, `verification='provider_readback'|'idempotent_receipt'`)
  acknowledges. Ambiguous or absent receipts stay pending and the run reports
  `ambiguous_delivery_possible_duplicates`. A transport that RAISES is its own
  typed bucket, `transport_exception_delivery_pending` (also pending) —
  distinct from an ambiguous no-readback receipt.

### Hermes relay deployment note

If alerts are relayed through Hermes cron delivery and the relay provides no
trustworthy provider readback, delivery must remain **ambiguous**: rows stay
pending and retries may produce duplicate notifications. Exactly-once
delivery is not claimed for any transport that cannot prove it. Do not
manufacture receipts; a local send boolean is not provider evidence.

## Known blockers (typed, not placeholders)

- `thesis_worker_blocker`: daily thesis monitoring requires concrete reviewed
  source-profile worker commands (`discover`/`retrieve`/`classify` as
  `watchdog.thesis.JSONCommand`) wired through the runtime. The CLI now supplies
  those reviewed workers; callers that deliberately omit adapters still record
  this typed gap rather than a fabricated thesis pass.
- `benchmark_unavailable`: daily runs without a benchmark adapter record the
  gap instead of inventing comparator data.

## Partial coverage is not all-clear

Any legacy holding, unverified ownership, incomplete operational snapshot,
missing calendar, blocked thesis phase, or adapter failure appears in
`reasons`/`coverage` and sets `all_clear=false`. Silence means "no exceptions
observed", never "verified safe".
