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

## Pending-entry full-fill maintenance recovery

Maintenance now accounts for a saved pending BUY/limit bracket when exact broker
readback confirms its complete fill. The shared entry-state lock covers readback,
fill-key-idempotent journal accounting, lifecycle persistence, reload and the
existing quantity/protection checks. The notification/readback contract and entry
journal implementation live in lightweight `entry_fills.py`; autotrader retains
its public helper interfaces. Maintenance never imports execution orchestration.

Only exactly bound saved order IDs are queried. Pending snapshot inconsistencies
can trigger one additional read-only snapshot of those same IDs; a first full-fill
observation may not regress on refresh. There is no retry loop or symbol-only
adoption. Fully filled pending entries receive one refresh to avoid a stale
position read. Local/broker partial fills remain unsupported and fail closed.
No baseline symbols, risk limits, execution gates or schedules change.

Entry recovery is silent and is not returned as an exit-repair notification.
`verify_only` reports `managed_repair_required` instead of recording entry fills.
The journal is written before the filled lifecycle row so an interrupted lifecycle
append replays against persisted full-entry parent/execution identity as well as
its historical raw fill key. New entry rows retain `broker_filled_at` separately
from their accounting timestamp: equivalent timezone/precision representations
of the same instant reuse the original row and key. Conflicting execution IDs,
time, quantity, price, symbol or supplied lineage fail closed before any batch
entry journal/lifecycle append. Both maintenance and autotrader prevalidate the
persisted evidence under the existing shared entry lock. Before either path
appends, batch ownership validation also rejects duplicate saved parent references
or one supplied broker execution ID claimed by multiple parents. Missing legacy
broker IDs do not invent ownership or bypass persisted-reference checks. Cumulative partial
observations and symbol-only rows are not full-entry identities.

Legacy full-entry rows without `broker_filled_at` can prove only an exact raw-key
repeat; changed keys with the same parent/execution are ambiguous and block
without rewriting historical rows. A confirmed execution may remain
recorded even if subsequent protection/quantity checks block; accounting a fill
does not claim the holding is protected. Broker snapshots are not transactional:
a change after the bounded final read is handled on a later pass, not by an
unbounded convergence loop.

## Operational evidence limits

A confined substantive broker probe proves the changed runtime path, not an eligible unattended cron fire or an alert-delivery receipt. Out-of-window scheduled success is a no-op, not broker reconciliation recovery. Preserve this distinction after resuming existing jobs.
