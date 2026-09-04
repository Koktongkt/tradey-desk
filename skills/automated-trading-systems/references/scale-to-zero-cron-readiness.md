# Scale-to-zero and cron readiness for trading automation

Use this note when an intraday trading job appears enabled but fires late, clusters after user messages, or misses market-monitoring intervals.

## Core failure mode

A hosted agent can have all of the following simultaneously:

- durable enabled cron definitions;
- a healthy gateway and fresh scheduler heartbeat while awake;
- an in-process (`builtin`) scheduler provider;
- host-level scale-to-zero enabled.

This is not a wake-capable design. Suspending the machine freezes the gateway process and its ticker. The next inbound message can wake the host and cause an overdue occurrence to run, but recurring jobs should not be assumed to replay every missed interval. For trading systems, this creates unobserved market windows and can make runs appear causally tied to chat activity.

## Evidence checklist

Collect all layers before changing trading logic:

1. **Host opt-in and actual suspension**
   - Inspect the platform-provided scale-to-zero enable signal without printing unrelated secrets.
   - Read gateway logs for `armed`, `going dormant`, suspend accepted, reconnect, and wake timestamps.
2. **Resolved scheduler provider**
   - Inspect cron configuration and provider resolution.
   - `builtin` means the trigger lives inside the process; an external managed provider must explicitly identify itself.
3. **Job state**
   - Confirm enabled/state/schedule, `next_run_at`, `last_run_at`, `last_status`, `last_fire_error`, and delivery errors.
   - A healthy ticker heartbeat proves only that the currently awake process is ticking.
4. **Execution history**
   - Read timestamps and the recorded execution `source`.
   - Programmatically calculate gaps and compare them with the declared cadence.
   - Correlate gaps with suspend-to-wake windows and user-message wakeups.
5. **Separate failures**
   - Distinguish scheduling coverage loss from failures inside a run, such as broker authentication or unavailable MCP bridges. Fixing wakeability does not fix a broker error, and fixing the broker does not restore missed cron intervals.

## Safe readiness rule

Do not activate intraday automated execution unless one of these paths is verified end to end:

### Path A — external wake-capable scheduler

- Treat hosting-portal copy (for example, “cron now wakes sleeping agents”) as a product claim, not proof that an existing instance was migrated.
- The resolved provider is the intended managed scheduler, not a blank/default fallback.
- Callback URL, expected audience, signature/JWKS verification, and provider availability are provisioned. A plugin merely being installed in the image is insufficient.
- Query the managed scheduler’s read-only registration/list endpoint with the agent’s normal credential when available. An authorization response saying the caller is not a provisioned agent is direct evidence of control-plane provisioning failure; do not compensate by switching the local provider name.
- Confirm new execution-history rows record the managed provider as their `source`; old and current rows marked `builtin` prove the in-process ticker still owns dispatch.
- A scheduled fire wakes a sleeping instance without a user message.
- Late retries and local catch-up are de-duplicated.
- A controlled sleep test shows the expected occurrence in execution history with the external provider source.

If provider availability is false or the control plane rejects the agent identity, keep the known-good built-in fallback while escalating the exact missing fields and authorization response. Setting `cron.provider` to the managed provider before callback/auth provisioning is complete does not create wakeability and can obscure the real fault.

### Path B — keep the host awake

- Disable the platform-owned scale-to-zero feature through the hosting control plane.
- Restart/redeploy if required for the platform-provided enable signal to change.
- Verify the watcher no longer arms after restart.
- Observe at least two consecutive unattended intervals during the intended market window.

Changing only an idle-timeout value is a temporary delay, not a true disable and not a substitute for a wake-capable trigger. If the user explicitly accepts the additional hosting cost, a bounded timeout covering one trading session can preserve near-term cadence after a deliberate daily wake; state that it still needs a new wake after the timeout and verify the effective seconds from loaded configuration.

On relay-fronted hosting, diagnose delivery independently from dispatch. If an explicit platform target is rejected as an unapproved egress destination while `origin` deliveries work, change only the affected job to `origin` with user approval, read the job back, and wait for a later scheduled delivery to clear the historical error. Do not interpret a delivery failure as evidence that the job did not execute.

## Acceptance test

1. Pause order placement or keep the system paper-only and fail-closed.
2. Choose a harmless script-only probe cadence.
3. Let the host become idle long enough that it would previously suspend.
4. Do not send chat messages during the test.
5. Verify every expected occurrence exists, at the expected cadence and with the intended trigger source.
6. Re-run cron health checks and inspect delivery separately.
7. Resume execution only after the probe passes and broker connectivity is independently healthy.

## Reporting

State separately:

- **schedule configured**;
- **scheduler awake now**;
- **host can be woken by scheduled fire**;
- **cadence coverage verified while unattended**;
- **job body succeeded**;
- **broker execution path authenticated**.

Never compress these into a generic “cron is working.”
