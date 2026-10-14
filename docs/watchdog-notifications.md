# Watchdog concise notification policy

This changes monitoring notifications only. It does not change trading rules,
operational ledgers, source cutoffs, broker permissions, or execution authority.

## Explicit activation (review/deployment step, not automatic)

Back up the monitoring database and pause its writers first. From the checkout,
use its existing watchdog environment:

```
/opt/data/venvs/tradey-watchdog/bin/python watchdog_cli.py apply-notification-policy --root /opt/data/projects/tradey-desk
```

The action performs no broker/provider call. It acquires the same nonblocking
monitoring lock used by runtime, verifies the exact schema/path, and transactionally
migrates monitoring schema 1 to 2. Reapplication is idempotent. Unknown schemas,
symlink/hardlink database aliases, and monitor lock contention are rejected.
The implementation does not itself pause or edit any cron job.

**Until activation, schema 1 retains the legacy outbox policy.** Do not resume
notification cron jobs expecting concise output before explicit activation.
After activation, an older code revision that only understands schema 1 cannot
read this database. A rollback must preserve the new database/audit and use an
explicit backup/recovery decision, not an automatic downgrade or deletion.

## Policy

- Keep every observation, evidence event, condition generation, pending outbox
  row and existing receipt. Historical pending rows are recorded as suppressed
  for notification purposes, not delivered or acknowledged. Already committed
  daily sessions are historical at activation and are not replayed.
- Evaluate immediate notifications from the latest committed position snapshot,
  never historical alert payloads: open missing/partial/unverifiable protection,
  quantity mismatch, overdue open horizon, and accepted verified material
  fundamental thesis weakening/break. Unknown/malformed remaining quantity is
  an urgent inability to verify protection, not proof of a closed position.
  Broker-vs-managed ownership discrepancies are quantity alerts even when the
  mechanical quantity field is `consistent`. Zero remaining quantity suppresses
  alerts only with verified ownership and corroborated broker protection sources;
  a broker holding that disagrees with an exit record is not a verified closure.
  Nominal stop coverage cannot override unknown ownership or incomplete
  orders/reference (or explicitly supplied position) coverage. Only those typed
  protection-source states are persisted from the broker source map. Overall
  thesis/accounting report incompleteness alone does not make protection urgent.
  Unverified position evidence does not reset protection-check failure state.
- Failed current protection checks notify even without a prior observation.
  These failures never create a synthetic position snapshot or source cutoff.
- Identical persistent urgent conditions remind at most every 24 hours of fresh
  observations. Changed/worsened conditions and reopening notify promptly.
  Recovery is bookkeeping only; no independent recovery message.
- One sanitized plain-English daily summary per newly committed session, after
  report installation, with current snapshot protection, substantive review
  developments, grouped limitations, and only verified strategy performance.
  A reporting retry uses that exact daily run identity even if an intervening
  mechanical run exists. Lesser source/accounting/setup gaps have no independent
  immediate notification. Routine report-installed status lines are removed.
  A report installation failure still evaluates immediate conditions from the
  latest committed report, including during reporting-only retries; it neither
  reserves nor emits the daily summary and does not write the completion marker.
  After successful installation, retries emit the exact daily run's summary once,
  while immediate conditions continue to use the newest report across modes.
  This split applies only after policy activation; schema 1 is unchanged.

## Evidence and crash semantics

`notification_emissions` is separate from `alert_outbox` and from genuine
`notification_receipts`:

- `suppressed`: a policy decision; not delivery.
- `prepared`: durable local emission reservation; not an attempt or delivery.
- `emitted`: callback returned successfully, including receiptless cron relay
  collection; not proof of Telegram delivery.
- `failed`: callback raised; retry allowed without suppressing it as emitted.

Reservations are committed before transport. A crash can leave `prepared`
entries even if some reserved messages were never handed off. They are not
replayed automatically. A crash after collection but before stdout/Telegram can
lose the message; the daily summary is not guaranteed exactly-once delivery.
Normal completed runs/retries emit a daily summary once, and fresh unchanged
urgent conditions can remind after 24h. A transport that sends and then raises
can duplicate on retry. These ambiguities cannot be repaired by forging a
provider receipt. Genuine returned receipts are validated and retained separately;
no new notification receipt acknowledges an unrelated legacy alert.

All decisions/receipts stay private. Outward text uses fixed prose and allowlisted
symbols, enums, dates and verified numeric projections, never source facts,
private identifiers, URLs, error strings or filesystem paths.

## Offline verification

```
/opt/data/venvs/tradey-watchdog/bin/python -m unittest discover -s tests -p test_watchdog_notifications.py -v
/opt/data/venvs/tradey-watchdog/bin/python tests/run_tests.py full
```

Tests use isolated fixture databases and fake external adapters; do not run a
live broker/order canary as part of notification review.
