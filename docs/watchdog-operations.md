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

Options:

- `--root PATH` — operational storage root (default: the checkout root).
- `--output-root PATH` — where `private/watchdog/` is created (default: `--root`).
- `--fixture` — confine both roots beneath `test_artifacts/watchdog`; any
  operational output choice is rejected (`fixture_output_confined`).
- `--smoke` — live smoke: no alert send, no report/publication; used to verify
  path/adapter/lock wiring without side effects.
- `--now ISO` — trusted aware clock override (ops/testing). The completion
  stamp is always this trusted `now`, never broker capture time.

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
slot; execution (retrieval) is never retried mid-run.

## Paths, locks and failure isolation

- Default outputs: `<output_root>/private/watchdog/` (monitoring.sqlite3,
  latest.json/latest.md generations, `completions/<session_date>.json`).
- External roots are rejected; non-fixture roots must be the checkout root or
  explicitly beneath `test_artifacts`. Operational input/output overlap and
  symlink escapes are rejected before any side effect.
- Locking is a monitoring-only `flock` on `private/watchdog/monitor.lock`
  (LOCK_EX|LOCK_NB). The trading writer lock and kill switch are never opened
  here; a watchdog failure cannot prevent the autotrader.
- Operational inputs are hashed/ stat-ed before and after every run; a change
  mid-run yields the typed `operational_input_changed_after_run` reason and
  the run is never all-clear.

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
  `ambiguous_delivery_possible_duplicates`.

### Hermes relay deployment note

If alerts are relayed through Hermes cron delivery and the relay provides no
trustworthy provider readback, delivery must remain **ambiguous**: rows stay
pending and retries may produce duplicate notifications. Exactly-once
delivery is not claimed for any transport that cannot prove it. Do not
manufacture receipts; a local send boolean is not provider evidence.

## Known blockers (typed, not placeholders)

- `thesis_worker_blocker`: daily thesis monitoring requires concrete reviewed
  source-profile worker commands (`discover`/`retrieve`/`classify` as
  `watchdog.thesis.JSONCommand`) wired through configuration. No reviewed
  worker executable exists yet, so daily runs record the typed coverage gap
  and complete with explicit gaps; no fabricated thesis pass is produced.
- `benchmark_unavailable`: daily runs without a benchmark adapter record the
  gap instead of inventing comparator data.

## Partial coverage is not all-clear

Any legacy holding, unverified ownership, incomplete operational snapshot,
missing calendar, blocked thesis phase, or adapter failure appears in
`reasons`/`coverage` and sets `all_clear=false`. Silence means "no exceptions
observed", never "verified safe".
