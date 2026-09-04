# Unattended heartbeats and notification-delivery audits

Case study from 2026-09-03 (Tradey Desk, hosted Hermes + Telegram relay): the user asked why scheduled automation was "not sending Telegram notifications" while every job was in fact firing on schedule.

## Symptom taxonomy for exception-only scheduler jobs

`no_agent` script jobs deliver stdout to the user only when stdout is non-empty (trades, blockers, auth/system failures). Silence therefore has four distinct causes; separate them before attempting any fix:

1. **Healthy no-event silence** — cycles ran, printed nothing, nothing to say. Expected.
2. **No trades happened** — the autotrader failed closed on every candidate (e.g. `broker_mcp_unavailable`, `whole_share_unaffordable` under a whole-share position cap). Blockers printed, but they are routine operating output, not an actionable failure.
3. **Delivery-side loss** — stdout was produced but never reached the user (`last_delivery_error` set, or send/delivery errors in gateway logs).
4. **Dormant/bursty host** — on scale-to-zero hosted deployments the gateway suspends after ~5 minutes idle; scheduled fires cluster around wake-ups, so delivery timing looks broken even when it is not.

## Audit order (worked example)

1. **Scheduler state first.** The cron list or the scheduler's jobs store (`/opt/data/cron/jobs.json` on hosted installs) gave ground truth: all five Tradey jobs `enabled` with correct expressions, ~311 completed autotrader fires since creation, and for the autotrader `last_status: error`, `last_error: "Script exited with code 3 / AUTH_FAILURE broker_mcp_unavailable"`, `failure_streak: 3`, `last_delivery_error: None`.
   - Field map: `last_status` = last exit classification; `last_error` = full stdout/stderr of the failure (often the only place the actual blocker text survives); `failure_streak` = consecutive failures (a growing streak means systemic, not transient); `last_delivery_error: None` means the scheduler *believes* delivery succeeded, not that the user saw anything; `repeat.completed` proves the schedule has been firing at all.
2. **Decision ledger second.** Tail `decision_audit.jsonl`: earlier cycles showed `broker_mcp_unavailable` blocks and later `whole_share_unaffordable` — fail-closed behavior, no fills, hence legitimately little to notify about.
3. **Gateway logs third.** Confirmed (a) the silent-on-success design, (b) scale-to-zero dormancy lines (`gateway idle for >= 300s — going dormant`), (c) relay send lines with no send errors in the affected window — consistent with `last_delivery_error: None`.

## Cron-versus-shell differential test

The autotrader failed with `AUTH_FAILURE broker_mcp_unavailable` under the scheduler but ran (different blocker: `whole_share_unaffordable`) when invoked interactively from the same workdir. Same code, same workdir, different outcome ⇒ the difference is the environment the scheduler runs the script in (env/PATH/credential/session state), not the trading logic. Reproduce both ways before touching code; remediate the cron-context environment or make the bridge fail with a clearer reason — do not loosen gates to make the failure disappear.

## Remediation pattern: daily heartbeat

- A separate tiny `no_agent` job at a fixed wall-clock time outside market hours; prints one line summarizing yesterday's cycle count, blockers by reason, orders placed, and current job failure streaks, derived read-only from the decision ledger and jobs store.
- The heartbeat must not share execution code with the autotrader — its own failure must never block trading.
- Purpose: convert "quiet = ?" into "quiet = yesterday's rollup said healthy".

## Related gaps noted

- The bundled `hermes-messaging-diagnostics` skill covers inbound relay failure only; outbound/cron-delivery silence on `no_agent` jobs is this file's territory.
- Gateway log access: `/opt/hermes/.venv/bin/hermes logs gateway -n N` (binary often off PATH on hosted installs); grep for `deliver`, `Sending`, `inbound`, `self-provision`.