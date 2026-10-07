# Read-only Position & Portfolio Watchdog with Attribution

Date: 2026-10-07
Status: Conversational design approved; written specification awaiting user review.
Source baseline: 89ac62764391c67f6a4248be473b9ff1f4e19455

## 1. Purpose and approved scope

Extend Tradey Desk with an observational plane that answers what the automation owns, why it owns it, whether protection and holding horizons remain valid, what collective exposures exist, and how actual activity differs from research and hypothetical decisions. The user approved hourly mechanical checks during the trading session and one after-close thesis/attribution report. This approval permits this design document, not implementation before written-spec and implementation-plan review.

Success means auditable, evidence-backed monitoring and accounting without acquiring trading authority. No performance improvement is claimed merely from deploying the watchdog.

## 2. Non-negotiable boundaries

- Paper-account reads only. Do not change enabled, broker mode, risk limits, execution gates, existing research cadence, or reviewer behavior.
- No placement, cancellation, replacement, liquidation, protection repair, automatic exits, rebalancing, or stop widening.
- Broker credentials remain in a deterministic read adapter; thesis models receive no broker tools or credentials.
- Enforce an exact broker-tool allowlist at the actual invocation boundary, not only at the CLI operation-name boundary. Reject any unknown operation before calling a tool. Do not import or dispatch the existing place/protect paths through an arbitrary-operation passthrough.
- Do not call managed_reconciliation.reconcile or reconcile_detailed: they can append operational fills and lifecycle records. Reuse only pure validation logic after separating it from side effects, with regression parity tests.
- Operational ledgers are inputs only. Watchdog outputs live in an isolated private monitoring store. Fixture/dry-run outputs remain under test_artifacts, never operational or public metrics.
- Retrieved evidence is untrusted data. A model cannot alter the thesis baseline, source coverage, accounting, exposure values, or order state.

## 3. Architecture and interfaces

Create small modules with explicit input/output contracts:

1. Read adapter: retrieves normalized positions, open/nested orders, exact referenced order readbacks, and account fields needed for reporting. Returns provenance, captured_at, completeness, and typed errors. No broker writes.
2. Lineage projection: joins operational candidates, immutable proposals/reviews, private intents, confirmed entry/exit fills, and protection registrations into stable managed position/decision identities.
3. Mechanical monitor: pure computations over validated lineage and broker snapshots for ownership, quantity, protection, horizon, and freshness.
4. Thesis monitor: bounded primary-source discovery/retrieval, event deduplication, and structured evidence classification against versioned baseline assumptions.
5. Attribution engine: deterministic actual-position accounting and separate research/decision metrics.
6. Monitoring store/report projection: atomic state transitions, compact evidence events, alert outbox, private report, sanitized public summary.
7. Independent CLI/scheduled wrapper: mechanical and daily modes; no dependency from the execution pipeline to watchdog success.

These names describe responsibilities, not a required file-per-function layout. Existing execution behavior must remain unchanged.

## 4. Read consistency and identity

Read a coherent operational history using the existing durable storage contract. A watchdog read must not invoke a reader that repairs or migrates projections as a hidden side effect; implementation must inspect that contract and provide a truly read-only snapshot if needed. Validate stream parity/completeness without changing source histories. Broker and local snapshot timestamps remain distinct.

Managed holdings are derived from confirmed automation fills and exact intent/protection relationships, not all holdings in the account. Pre-existing baseline holdings are excluded. A quantity mismatch or ambiguous ownership is a discrepancy, not permission to silently claim the full broker position. Concurrently changing state yields an incomplete/retryable observation rather than a false all-clear.

Join candidate_id/dossier_hash to proposal identity and parent order identity wherever an explicit durable relationship exists. Confirmed fills use broker-confirmed execution identities and quantities. Handle multiple ideas in one symbol independently. Do not infer lineage solely from symbol or timestamp proximity. Historical missing/ambiguous links remain unattributed, with coverage counts and reason codes. Do not rewrite historical records or invent identifiers that purport to prove a relationship.

Inspect existing production row shapes before implementation. If new forward-only linkage fields are required in execution persistence, present that narrow interface change in the implementation plan, keep order payloads and policy unchanged, and regression-test compatibility. The watchdog itself remains unable to append operational records.

## 5. Mechanical position monitoring

Each managed position contains original thesis reference, catalyst, setup/horizon, planned_exit_at, confirmed entry/remaining quantity, relevant protective references, and input verification timestamps.

Protection checks validate broker-owned side, type, remaining coverage quantity, status, stop/target levels, parent/OCO association, and actual time-in-force. Open protection must not be inferred from a stored plan. Treat partial fills, expired/cancelled/rejected legs, replacement OCO registrations, overlapping exits, and ambiguous nested responses explicitly. Quantity coverage and planned-risk arithmetic use validated Decimal values; reject booleans and non-finite or invalid-domain numbers.

Holding horizon compares the immutable planned_exit_at with a timezone-aware observation time. Report remaining/expired status using exchange sessions where required; unavailable calendars remain unknown. Expiry requests human review, never submits an exit or extends the horizon.

Represent independent statuses rather than one misleading health flag:

- ownership/protection: verified, discrepancy, unknown;
- horizon: within_horizon, horizon_expired, unknown;
- thesis: baseline_incomplete, no_material_change_observed, review_required, potential_thesis_break, coverage_incomplete.

A completed source check with no material event is only no_material_change_observed within the documented coverage, not proof that a thesis is correct.

## 6. Thesis monitoring and source policy

Baseline fields: saved summary, dated catalyst, measurable assumptions/breakers, relevant KPIs and risks, and baseline provenance/version. Preserve supplied usable criteria; incomplete legacy baselines receive baseline_incomplete. No autonomous model-generated breaker becomes an authoritative original assumption. A proposed baseline enrichment is separately reviewable and versioned; do not block mechanical monitoring while thesis criteria are incomplete.

Use SEC/issuer IR, exchange and regulator publications first. Reuse trusted deterministic earnings sources for upcoming-report risk and keep previous-report evidence distinct. General news may discover an event, but retain precise verification/primary-source coverage. Do not add keys or MCP servers.

Bound daily work to currently owned managed symbols, with a stable priority ordering, per-name caps, and one shared monotonic run deadline. Reuse established provider configuration and bounded source fetchers only after checking they do not create candidates or touch operational state. The implementation plan must specify concrete budgets and demonstrate they fit the chosen scheduler envelope; unfinished names remain coverage_incomplete.

Deduplicate underlying events, not URLs. Store concise sourced facts, publication/event times, retrieval times, source URLs, event fingerprints, baseline version and mapped assumption, severity, and classification. Do not retain full articles, filings, raw model transcripts or hidden reasoning in monitoring storage. Advance each source cutoff only after successful documented coverage; failures preserve the previous cutoff. Use a small documented overlap for late publications.

Model output is strict structured classification only. Source failure, unverifiable dates, stale evidence, or malformed classification produce typed coverage gaps. Price decline alone cannot establish thesis failure. A possible breaker produces a review alert, not trading authority.

## 7. Portfolio and accounting methodology

Report managed market value, position weights, realized/unrealized P&L, and verified planned downside to stops. Stop-based downside is conditional geometry, not maximum loss: gaps, slippage and liquidity can exceed it. Unsupported sector/shared-driver classifications remain unknown; no optimizer or correlation gate is included.

Separate:

1. Actual activity: confirmed fills and managed position accounting.
2. Research outcomes: dated idea-specific forward outcomes.
3. Decision outcomes: approval, reviewer rejection, deterministic block, submitted/unfilled, and filled states.

FIFO allocation within an exactly linked managed position is the accounting convention for partial exits; never allocate across ambiguous legacy/managed lots. Split adjustments and cash distributions require verified corporate-action/activity evidence. Reconcile remaining quantities and mark value to broker truth. Never count repeated observations of cumulative fills as new executions. Unsupported fees, distributions, or corporate actions produce explicit coverage limitations rather than fabricated zeros or silently complete totals.

For prospectively measured sleeve performance, use a disclosed $10,000 analytical starting capital matching the current managed exposure cap, explicitly not the full broker account equity or buying power. The remaining virtual cash is starting capital less confirmed managed purchases plus confirmed sale proceeds and verified distributions, less verified costs. The capital basis does not change automatically if the trading cap later changes. A new basis/external sleeve cash flow requires explicit versioned documentation; do not infer sleeve cash flows from unrelated account deposits.

Start the equity curve only at a defensible complete baseline. If historical completeness is proven, earlier performance may be reconstructed with a visible methodology; otherwise report historical trade P&L separately and start prospective reporting at the first verified baseline. Unknown cost/distribution coverage means incomplete total-return coverage.

Use a synchronized S&P 500 total-return comparator, preferably a verified low-cost SPY total-return proxy with documented reinvestment and expense treatment, with identical starting capital, baseline and valuation dates. SPY is a benchmark only, not a tradable instrument in this release. Massive/issuer structured data are the research-data path; Alpaca is reserved for broker state. Verify what adjustment a price series actually includes: split-adjusted bars alone do not establish dividend-inclusive total return. If verified benchmark distributions/total-return data are unavailable, show a clearly labeled price-return comparator and withhold the total-return excess claim.

Report prospective equity/drawdown only from valid marked observations, including cash drag. Missing marks create gaps, not carried-forward fake current values. Never equate shadow horizon returns with realizable protected-trade P&L. Avoid claims of statistically validated alpha from small or dependent samples.

## 8. Storage, reports and delivery

Use a separate private SQLite monitoring database with schema version, foreign keys, transactional updates, and uniqueness constraints. Conceptual records: baseline versions, position observations, portfolio snapshots, lineage coverage, evidence events/source cutoffs, attribution projections, run results, alert transitions/outbox. Retain bounded compact facts and useful accounting snapshots, not raw routine broker payloads or no-change prose logs. Read operational history without migrating its backend.

Each run writes a run identity, source timestamps, coverage, and typed diagnostics. Private JSON/Markdown reports are installed atomically. Public summaries use explicit field allowlists and exclude account IDs, broker/order IDs, internal hashes, raw theses, private sources/reviews, secrets and filesystem paths. Public market-symbol/exposure aggregates are allowed only where ownership is verified. Public failure summaries contain sanitized reason codes, never raw exceptions.

Alert only on new/worsened protection or quantity discrepancies, horizon expiry, material evidence changes, or coverage deterioration; record recoveries distinctly. Use condition fingerprints, cooldowns and hysteresis to avoid repetitive alerts. Daily digest is once per exchange session. Durable outbox plus delivery acknowledgment/readback where supported; if the transport has no idempotency/ack capability, disclose possible duplicate delivery after an ambiguous failure rather than claiming exactly-once delivery.

## 9. Cadence and isolation

- Mechanical checks: once per hour at :05 within the actual NY regular session, clipped to exchange calendar close (including early closes).
- Daily thesis/attribution: first scheduled opportunity at least 15 minutes after the actual exchange-session close, with a bounded retry for read/report failures only and a completion marker after success.
- Scheduler UTC firing envelope must cover DST; code decides exchange-session eligibility. No existing producer/consumer cadence changes.
- Mechanical and daily modes acquire a monitoring-only lock. Avoid overlap; an in-progress equivalent run is a typed skip, not an operational trading blocker.
- A failed watchdog run cannot prevent the existing autotrader from operating or mutate its kill switch. Missing protection alerts do not imply the watchdog repaired it.
- Schedule installation follows implementation tests, read-only live smoke and independent review. Verify exact installed job state by readback.

## 10. Verification and release acceptance

Tests must be written and observed RED before product behavior is introduced. Cover:

- Actual broker invocation allowlist rejects every write and unknown operation; injected model content cannot reach broker calls.
- No operational file or database writes, including hidden repair side effects; no credentials in reports or model input.
- Empty managed sleeve, legacy baseline, ambiguous ownership, repeated ticker ideas, missing lineage and concurrently changing ledgers.
- Partial/cumulative fills, duplicate observations, partial exits, cancelled/expired legs, OCO replacements, over/under coverage and broker discrepancies.
- Timezones, DST, early closes, missing calendar, stale/future timestamps and horizon expiry.
- Baseline incompleteness, primary-source failure, event duplication, cutoff preservation and materiality mapping.
- Decimal arithmetic, corporate actions/distributions, accounting coverage limitations, marked equity, cash drag and benchmark adjustment provenance.
- Report sanitizer, alert deduplication, ambiguous delivery, idempotent reruns, crash recovery, run budgets and fixture isolation.

Run existing fast/scenario/full suites using the repository's actual dependency-wrapped commands. Obtain independent adversarial review of the frozen diff; RED-test and fix findings, then repeat review until PASS. Exercise a real read-only broker/report run against isolated watchdog output and inspect actual results. Do not place a test trade.

Commit explicit source paths, inspect committed diff, push from the live checkout and verify remote SHA. Install only the approved new schedules and read back their exact state. If existing writer changes require a pause, inventory and pause only affected jobs, verify states, and restore them after validated release. Documentation-only preparation does not require pausing trading.

## 11. Excluded work

No execution authority, automatic risk tuning, new instrument types, live rollout, arbitrary portfolio optimization, correlation admission gates, historical data fabrication, autonomous baseline rewriting, or full protected-trade simulation. Independent challenger experiments and any consequential exit policy are later separately approved work.
