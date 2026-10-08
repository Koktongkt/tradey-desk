# Watchdog runtime readiness — partial release, not activation

## Implemented and exercised

- The CLI supplies a concrete isolated paper-only broker collector, not an
  empty adapter dictionary. Fixture CLI invocations remain unwired.
- Broker reads use the existing six-tool allowlist and never dispatch an
  execution, cancellation, liquidation or journal-repair operation.
- Required references come from submitted intents, protective references and
  confirmed/submission-started lifecycle rows. Rejected unsubmitted proposals
  are not broker orders. Missing submitted references remain unknown.
- Broker worker: 90-second deadline. Massive worker: 30-second deadline.
  Complete worker process groups are killed after success or timeout.
- Live smoke output defaults beneath `test_artifacts/watchdog`; production
  output is rejected. Dry-run commits cannot arm conditions or enqueue alerts.
- `--cron` emits rendered sanitized exceptions for the supported script-only
  Hermes relay route. No provider receipt is invented; alerts remain pending
  and possible duplicate notifications are disclosed.

## Verification evidence

Nine new regressions were observed failing before the corresponding behavior
was implemented (missing-function import errors are recorded as missing APIs,
not existing-feature assertion failures).

Validation on the runtime tree:

- fast: 451 tests, zero failures/errors/skips;
- scenario: 231 tests, zero failures/errors/skips;
- full: 800 tests, zero failures/errors/skips;
- raw unittest discovery: 800 tests, zero failures/errors; parity confirmed;
- `git diff --check`: clean.

Actual paper-broker read probe at 2026-10-08T08:06:54Z returned complete requested
account, position, open-order, submitted-reference, calendar and activity
coverage. The activity window is explicitly 90 days and does not establish
lifetime accounting completeness or strategy inception performance.

An actual Massive probe of 2026-10-06 through 2026-10-07 returned two completed
SPY closing-price samples and complete requested-range distribution source
coverage. Split-compatible distribution/reinvestment capability remains
unverified. Comparator label remains **price_return_only**; total-return alpha
is withheld.

Actual-clock CLI smoke returned expected premarket no-ops (`outside_session`
for mechanical, `not_scheduled_slot` for daily), with unchanged operational
inputs and no commit/delivery. A separate confined orchestration probe used a
real live broker snapshot with explicitly SIMULATED eligible slot clocks.
Those simulated clocks are not production portfolio observations. Both modes
wrote only ignored smoke evidence; `condition_state`, `alert_outbox`,
`source_state` and `thesis_versions` remained empty. No latest report generation,
public publication or completion marker was installed. Operational input
digests were unchanged across the confined probe.

The probe preserved incomplete coverage rather than an all-clear. Mechanical
exposure excluded a lineage-discrepant historical position; daily additionally
reported absent thesis workers. These are real readiness limitations, not
proof that a current holding lacks protection. No repair or trade was attempted.

## Uncompleted activation gates

1. Concrete reviewed SEC/issuer/earnings source-profile executables and a
   provider-only credential gateway for tool-free classification do not yet
   exist. General Hermes research subprocesses are not compliant substitutes:
   they may inherit host credentials, project context or memory. The daily
   lane retains `thesis_worker_blocker`; no fabricated no-change is emitted.
2. No independent adversarial review of the new runtime wiring was performed.
   Self-inspection and passing tests are not an independent review PASS.
3. Consequently no watchdog jobs were registered, enabled or triggered, no
   production watchdog report/outbox was established and no unattended
   delivery was verified. Existing scheduler jobs were read back only and
   their cadence/enabled state was not changed.

This document records a tested runtime increment, not completion of Task 9 or
an assurance of overnight monitoring. Scheduling must stay gated until the
source/classification probe and independent-review requirements pass.
