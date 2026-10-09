# Pending bracket reconciliation release

## Scope

Recognize exactly verified pending paper BUY/limit bracket entries and their two held protective children. Do not infer ownership from symbol membership or create journal fills for unfilled entries. No broker write path, execution gate, position limit, or scheduler cadence is changed.

## Validation boundaries

- Validate historical ledger rows before building latest lifecycle state. Only absent-ID, zero/absent-fill never-submitted rejection records are exempt from order obligations.
- Pending/filled ledger entries require saved intents; saved intents require ledger lineage. A saved intent with only a proposed lifecycle remains an uncertain submission requiring exact broker verification.
- Reject unsupported local lifecycle states, partial-fill contradictions, and positive pending fill evidence.
- Require exact saved parent identity, symbol, side, position intent, class, quantity, limit, GTC policy, zero fill, and valid stop/entry/target geometry.
- Require two distinct held bracket closing children, exact quantities and stop/target prices, consistent type aliases, and no nested descendants or incompatible price fields.
- Enforce unique ownership across all lookup parents/children, including terminal children and closing positions, before any local fill/lifecycle writes.
- Bind every returned open order to exact known evidence regardless of status; unsupported or unknown orders remain fail-closed.
- Recheck pending/open evidence after a confirmed exit triggers the fresh snapshot. Pending entries produce no fill-journal records.
- Preserve typed blockers through cycle diagnostics.

## Verification (2026-10-09)

- Permanent regression tests observed RED before behavioral changes, then GREEN.
- Parent production checkout: fast 481, scenario 239, full 838, raw discovery 838; no failures/errors/skips in canonical tiers. Operational-isolation guard passed.
- Independent final frozen v4 review: PASS. Full/raw each 838; original adversarial suites 17/17, 40/40, 19/19; additional independent probes 101/101. Three candidate hashes unchanged. Probe journal/lifecycle files byte-identical; no pending journal entries.
- Independent harness used an external scratch-path relocation to honor its write confinement; no candidate edits or skipped assertions. Initial harness failures were retained. Parent production suites passed without that accommodation.
- Parent fresh production read-only snapshot through the complete reconciler on isolated ledger copies: healthy/verified at 2026-10-09T01:11:58.145862Z, zero newly journaled rows, original operational state and confined journal projections unchanged.
- Non-failing SQLite ResourceWarnings remain a test-harness observation.

## Operational evidence limits

A confined substantive broker probe proves the changed runtime path, not an eligible unattended cron fire or an alert-delivery receipt. Out-of-window scheduled success is a no-op, not broker reconciliation recovery. Preserve this distinction after resuming existing jobs.
