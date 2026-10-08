# Task 8 — CLI, scheduling and isolated vertical workflow

Base: `98eefe9` ("fix(watchdog): validate report-lock inode before mutation"), isolated `position-watchdog` worktree. Offline implementation and self-review only: no subagents, no live network/broker calls, no schedule registration, no pushes, no operational writes.

## Delivered / scope

- Created `watchdog/schedule.py` (pure session/cron eligibility), `watchdog/cli.py` (`run_watchdog`, `run_budgets`, `main`, delivery wrapper, path/lock/budget contract), and `watchdog_cli.py` (thin entry point).
- Created `tests/test_watchdog_workflow.py` (23 scenario tests) and `tests/test_watchdog_schedule.py` (18 fast tests). Real pure modules/store plus only fake external adapters (fake broker snapshot callable, fake benchmark, fake transport, real `JSONCommand` worker subprocess with canned responses).
- Added `docs/watchdog-operations.md`; README watchdog section; manifest registration (`test_watchdog_schedule` → fast, `test_watchdog_workflow` → scenario).
- All test artifacts confined to `test_artifacts/` and cleaned; no fixture artifacts committed. Only the explicit source/test/docs/manifest paths above are staged.

## RED / GREEN evidence

Initial run of both new modules (before any `watchdog/schedule.py` or `watchdog/cli.py` existed): `Ran 24 tests ... FAILED (errors=24)` — all `ModuleNotFoundError`/import errors, genuine RED for every new interface. Product slices were then implemented; per-slice failures during bring-up (fixture and expectation defects corrected on the test side only where the defect was mine, e.g. daily slot is close+15..close+45 = 20:15..20:45 UTC for an EDT 16:00 close, cron union must filter in UTC, empty `DEFAULT_STREAMS` projection files required for a complete operational snapshot, digest `LIKE` on compact JSON requiring `instr()`):

| Slice | Observed failure → GREEN |
|---|---|
| schedule eligibility, DST/early-close/holiday, cron union | RED 18 errors (missing module) → intermediate failures (slot ordering, test-side UTC conversion bug) → 18 PASS |
| mechanical workflow (commit, reports, delivery, input immutability) | RED import errors → failures: no protection alert with covered stop (test switched to canceled stop), `exposure` missing from mechanical portfolio, empty-stream snapshot gap → PASS |
| daily workflow (partitions, source cutoffs, digest outbox, completion marker) | failures: digest query 0 rows (SQLite `LIKE` vs compact JSON — replaced with `instr()`), marker stamp expectation used the wrong slot time → PASS |
| path safety (fixture confinement, external root, overlap, symlink escape, unknown CLI action) | failures: overlap rule missing "root inside output root" direction, argparse `SystemExit` not converted to exit 2 → PASS |
| delivery/lock/budget (receipt-only ack, equivalent-run drain, monitoring lock isolation, outer wall-clock kill, digest identity, smoke) | failures: report failure must not acknowledge alerts (wrapper delivered on failure path), pending-protection fixture → PASS |

## Final exact verification

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_schedule test_watchdog_workflow -q   # 41 PASS
uv run --with 'fastmcp<4' python tests/run_tests.py fast        # 45 modules / 451 PASS, 0 fail/error/skip
uv run --with 'fastmcp<4' python tests/run_tests.py scenario    # 12 modules / 203 PASS
uv run --with 'fastmcp<4' python tests/run_tests.py full        # 40 modules / 772 PASS
uv run --with 'fastmcp<4' python -m unittest discover -s tests -p 'test_*.py'   # 772 OK (discovery parity)
git diff --check
```

Runner operational-file isolation checks passed. Artifact inspection: a daily fixture run under `test_artifacts/watchdog/artifact-check` produced `private/watchdog/latest.{json,md}`, an atomically installed `public/watchdog.json` (keys: account/available/benchmark/coverage/outcomes_label/positions/reasons/session_date/strategy/thesis) with a regex sweep finding no filesystem paths, hashes, URLs, order IDs, credentials, or buying-power fields; ambiguous transport (returns `None`) left 2 alerts pending; completion marker written with the trusted `now`. Fixture roots were removed afterward. `watchdog_cli.py explode` exits 2 with no side effects; default mechanical invocation without a broker adapter fails closed (`adapter_missing_broker`, exit 1, nothing created under `private/`).

## Contract rulings

- **Modes/interfaces**: `run_watchdog(mode, root, output_root, adapters, now) -> dict` exactly as briefed; optional keyword-only extensions (`fixture`, `smoke`, `budgets`) used by CLI/tests. `eligible(mode, now, sessions) -> bool` plus typed `eligibility()` returning `(bool, reasons, session_date)`. `main(argv) -> int` with actions `mechanical|daily|eligibility`; anything else exits 2 with no writes.
- **Paths**: roots must be the checkout root or explicitly under `test_artifacts`; `--fixture`/`--smoke` confine both roots beneath `test_artifacts/watchdog` (`fixture_output_confined`). External roots rejected; literal-path symlink-component walk plus realpath identity rejects escapes; overlap rejects output inside root/private, root inside output, and output containing root. Lock, completion markers, reports and the monitoring DB live solely under the selected output root (`private/watchdog/...`), satisfying the Task 7 path contract.
- **Locks**: monitoring-only `flock` (`monitor.lock`, `LOCK_EX|LOCK_NB`, `O_NOFOLLOW`, 0600). The trading writer lock is never opened or created; a busy monitoring lock is a typed skipped no-op, so watchdog failure cannot affect the autotrader. Verified by holding the lock in-test and separately acquiring the trading lock exclusively afterwards.
- **Budgets**: `run_budgets` — mechanical `{'outer':120,'active':120,'reserve':0}`; daily `{'outer':900,'active':840,'reserve':60}`. Checkpoints between phases; exhaustion returns `budget_exceeded` (`outer_deadline_exceeded`) with no commit. Thesis phase clipped to ≤600 s via `monitor_theses`' own cap.
- **Eligibility/no-op**: mechanical :05 only inside a live session (session membership dominates the cron-minute check, so out-of-session firings report `outside_session`); daily in close+15..close+45 on a session day. Missing/invalid calendar → `schedule_calendar_missing`, dates without a session → `no_session_for_run_date`; no guessed eligibility. Cron union with DST/early-close calendar fixtures verified; scheduler registration itself deliberately not performed (operational change, out of scope).
- **Operational inputs**: sha256+stat digests of ledger/streams/baseline before and after every run; mid-run change yields `operational_input_changed_after_run` and the run is never all-clear. `read_operational` retains its own shared-lock stat before/after; fixture workarounds (hand-built ledger in the fixture root) exist only because `sqlite_ledger._storage_root` hoists `test_artifacts` subtrees to the shared artifacts root.
- **Daily completion**: marker `private/watchdog/completions/<session_date>.json` (atomic 0600 replace) written only after `commit_observation` succeeds AND `install_reports` succeeds; report failure leaves alerts pending (`delivered=0`), next eligible slot retries reporting only. Completion stamp is the caller-supplied trusted `now`, never broker `captured_at` or start time (asserted).
- **Delivery/outbox**: `_deliver` drains ALL pending alerts (prior runs included), renders via `render_alert`, and acknowledges only receipts accepted by `store.ack_alert` (provider/message_id/status='delivered'/aware verified_at/verification). Ambiguous receipts keep rows pending and surface `ambiguous_delivery_possible_duplicates`. Equivalent-run (same slot/digest) still drains; conflicting digest for the same run identity raises `run_identity_conflict`.
- **Coverage honesty**: legacy holdings (`legacy_holdings_unattributed`), unverified ownership, incomplete operational snapshot, missing benchmark (`benchmark_unavailable`), missing thesis workers (`thesis_worker_blocker`) are explicit reasons; `all_clear` is true only with zero reasons and complete coverage. Partial coverage is successful-with-gaps, never an all-clear.
- **Typed blockers (no placeholder runtime)**: no reviewed concrete source-profile worker executable exists in this offline task, so daily runs without configured `JSONCommand` worker commands record `thesis_worker_blocker` and complete with explicit gaps; tests exercise the real `JSONCommand` process boundary with a canned worker script under `test_artifacts`. Concrete production workers (primary SEC/issuer/earnings listings with documented inspected-listing proof, SSRF/domain rules, provider-only credential gateway) remain a prerequisite before enabling daily thesis monitoring; noted in docs.
- **Smoke**: smoke mode performs the full read path with no transport call and no report/publication; asserted no `latest.json`, no `public/`.

## Requirement-to-test mapping

| Requirement | Tests |
|---|---|
| Mechanical managed/legacy/missing-baseline/pending protection | mechanical_run_commits…, legacy_holdings…, pending_protection…, incomplete_broker_snapshot… |
| Daily partitions/cutoff/outbox/marker | daily_partitions_source_cutoffs_outbox_and_marker; completion_marker_only_after… |
| Hash/stat inputs before/after | input digests asserted unchanged; operational_input_change_after_run_is_typed |
| Fixture/output confinement, external root, overlap, escapes, fail-closed CLI | PathSafetyTests (5) |
| DST/holiday/weekend/early close/missing calendar/cron union | test_watchdog_schedule (18) |
| Receipt-only ack, equivalent-run drain, ambiguous semantics | ack_only_on_genuine_receipt…, equivalent_run_skip_still_drains… |
| Lock isolation, outer wall-clock kill, budget constants, digest identity, smoke | monitoring_lock…, outer_wall_clock_budget…, run_budget_constants, digest_identity_conflict…, smoke_sends_nothing… |

## Concerns / not done

- Cron expressions are proposed and code-verified against fixture calendars only; actual scheduler registration is an operational change deliberately not made.
- Daily thesis monitoring is blocked on concrete reviewed worker executables (typed `thesis_worker_blocker`); no live retrieval or model calls exist in this lane.
- Delivery remains ambiguous for any transport without provider readback (including a Hermes cron relay); duplicate-on-retry semantics documented rather than exactly-once claimed.
- `run_watchdog` creates `private/watchdog/` (lock directory) even for out-of-session no-ops under the selected output root; the monitoring DB itself is created only by a real commit.
