# Tradey Desk process flow

[Interactive workflow](tradey-desk.workflow.html) · [Editable JSON](tradey-desk.workflow.json) · [PNG preview](tradey-desk-preview.png) · [SVG export](tradey-desk-preview.svg) · [Source evidence](SOURCE_EVIDENCE.json) · [Validation summary](VALIDATION.json)

Download and open the HTML locally; GitHub does not execute HTML. The standalone viewer retains light/dark themes, zoom, source inspection, focus/search, route exploration and native exports. The newly generated PNG is **4026×3456**. Native PNG/SVG exports exclude viewer controls and source badges; the decorative grid remains. `tradey-desk.html` is an unchanged **historical artifact**, not the current workflow.

## Frozen source, not operational readback

This refresh describes committed main source **`69587777f1d7f41b76f41f686cf21d67d6a0b92b`**, inspected from an isolated detached worktree. It does not establish current account state, installed schedules, **opportunity-policy or research-memory activation**, live model/broker execution, alert delivery or deployment. No deploy or push was performed. Runtime tests were not rerun by this documentation worker.

The diagram has **85 source citations** (at most three per node) bound to committed blobs and valid inclusive ranges. `SOURCE_EVIDENCE.json` records their SHA-256 identities and **27 supplemental ranges** supporting overview cards. SRC markers remain local-only, without implying remote publication or access. `VALIDATION.json` is a portable summary of real local receipts, not an Archify delivery sidecar. Machine-specific delivery/browser receipts and screenshots are intentionally not committed.

## What changed since the 237b825 diagram

- **Scheduler folded into discovery.** The research lane now starts at *Scheduled discovery*; cadence detail lives in the cadence card.
- **New *Admission gate* (research).** Runs after evidence ranking and before synthesis. Without activation it only diverts acquisition-hinted leads; activated policies add identity/allowance or research-memory admission (below).
- **New *Entry authority* (decision)** replaces *Broker + market truth*: activation-gated allowance / exact-dossier checks, the bounded broker observation and the no-add-on rule. New exception node **No new entry** (held / spent / already reviewed).
- **Reconcile first** now journals exact broker full fills of saved pending entries; partial accounting stays unsupported.
- **Reviewers** persist only exact `APPROVE`/`HOLD` outputs.
- Node labels were shortened after visual review; the dashboard node reflects the dark/light redesign.

## Activation-gated admission and entry authority

All of the following depends on a record in the private opportunity-policy stream. Absent activation keeps the **legacy floor**: exact-dossier review protection, no event allowance and no strict no-add-on gate (existing position-size limits still apply). Activation requires an explicit approved-digest administrative apply; **activation state was not inspected**.

- **Policy v1/v2 (event identity).** Radar resolves trusted SEC issuer/event identity from acquisition-owned captures, skips spent generations (`unchanged_opportunity`), held symbols and same-symbol pending entries, and fails closed on unknown or conflicting identity. v2 binds every new candidate to one approved prospective baseline. SEC identity capture uses bounded exact-URL fetches inside the remaining evidence deadline, with no model, broker or new budget.
- **Policy v3 (exact-document research memory)** retires event admission. Keys hash verified issuer, representation contract, complete content digest, rules and stage. Completed work is reusable for under 24 hours; failed exact resources cool down 20 minutes. A hit reuses a still-fresh, unreviewed dossier or skips a duplicate bundle. Cache damage runs uncached and never relaxes history or execution checks.
- **Acquisition leads.** Outside v3 memory mode, acquisition-hinted leads are stored privately as `research_only` records and never become candidates; autotrader also refuses research-only input.
- When every remaining lead is policy-skipped or research-only, Radar reports `no_new_eligible_opportunity` (exit 0).
- **Entry authority (activated).** Any positive broker position blocks a new BUY **before sizing and paid review**, whatever the caps (no add-on). Broker evidence must be under 120 seconds old and read within 120 seconds. The exact approved attempt is re-proven and rechecked under the entry lock immediately before durable intent. Unsupported/corrupt policy state blocks entry while reconciliation and protection still run first.

## Research and current cadence

- Enabled checked-in path: six-lane discovery (broad, SEC, issuer IR, reporting, undercovered wire, rotating sector), followed by a one-turn tool-free selector admitting at most five source-bound company/event pairs. Policy skips never admit a sixth lead.
- Focused search, safety validation and fair allocation select at most five URLs per candidate / 25 unique URLs, using at most three singleton extraction supervisors. Actual extraction envelopes establish content.
- Evidence eligibility requires **at least two distinct accepted publisher domains**. Thin-bundle rescue covers up to three candidates; proven spent/held facts can prune it, while unknown thin bundles still receive it. Deadlines and spent recovery allowances never reset.
- Up to **five distinct ranked evidence-eligible candidates** receive **sequential synthesis plus shared intake**. First intake success returns immediately. Infrastructure, parse, containment, ambiguous market-data and persistence failures abort.
- **270 cumulative synthesis seconds**, no per-candidate cap; **90 separately cumulative enrichment seconds** inside the **960-second absolute active deadline**; the research wrapper is **990 seconds**. Radar CLI runs also write a private, best-effort enrichment trace (at most 124 rows per attempt). It changes no budget, routing or gate.
- Synthesis must supply a future timezone-aware UTC exit and 1–30 entry-inclusive holding sessions; no dates are repaired. Massive REST supplies prices and completed daily bars; Alpaca MCP supplies account/orders/calendar and IEX quote truth. **FRED is not integrated.**
- Premarket: **09:00 ET**. Radar: **10:00–15:40 ET at :00/:20/:40**. Autotrader UTC grid **`18,38,58 13-20 * * 1-5`**; the NY slot and weekday 09:30–16:00 window accept **09:38/09:58**, then **10:18–15:58 at :18/:38/:58**. Reconciliation: `2,12,22,32,42,52 * * * 1-5`. The nominal 90 seconds between the 990-second wrapper and the 18-minute spacing is **not a guarantee of non-overlap**. Versioned schedules are not installed-job readback.
- A cron-shaped **pre-open URL-admission compatibility check** (`cron/url_safety_check.sh`) is validation-only: it may read configuration and resolve DNS, but it fetches no articles and calls no model or broker. It is silent on pass and prints one `SYSTEM_FAILURE` line (exit 3) on failure. No schedule time is committed. Passing proves URL-admission compatibility only, not research health.

## Preserved execution and storage boundaries

- Checked-in configuration (unchanged): enabled/paper, **three daily submissions**, **three qualified pending parents**, `exact_owned_zero_fill_v1`, `new_intents_session_close_v1`, $10,000 managed exposure, $500 per position, $40 planned risk, IEX spread ≤600 bps, whole shares, no margin.
- Lifecycle runs first: expiry observation, pending-entry and exit reconciliation, managed protection. Only then do activation, freshness, already-reviewed and entry-authority checks run.
- **Partial fills.** Maintenance journals a saved pending entry only on an exact broker full fill, writing the journal before the lifecycle row with an idempotent fill key. A saved partial placement readback may advance only to that exact full fill; partial accounting remains unsupported and fails closed. `verify_only` reports `managed_repair_required` instead of writing.
- Python fixes executable fields before hashing. Both tool-free reviewers must approve; lower score ≥0.55 and reward/risk ≥1.6. Only exact `APPROVE`/`HOLD` reviewer outputs are persisted; anything else is recorded as reviewer-unavailable, which still cannot satisfy dual approval.
- New short 1–5-session entry deadlines use placement-session regular close; swing 6–30 uses the next actual session close. Expiry remains **observation-only** (`SAFE_PARENT_CANCEL_VERIFIED=False`) and frees no slot, reservation or daily quota.
- Operational reconciliation imports JSONL projections only when an existing SQLite database is present; `verify_only` preserves business bytes and fails closed on divergence or pending WAL/recovery state.
- Stable outer Linux subreaper custody of the inner supervisor, wrapper and detached orphans is unchanged; external SIGKILL/OOM, container death and uninterruptible tasks are outside the guarantee.

## Independent watchdog and reporting

Mechanical (:05 inside an actual session, 120-second hard bound) and daily (close+15 / close+45, 900-second hard bound) remain separate read-only monitoring tracks, never trading approvals. The research-memory stream is excluded from operational authority, so an absent or damaged cache cannot disable monitoring. Private policy diagnostics are admitted without changing baseline scope. Broker order coalescing tolerates only sub-microsecond timestamp rounding between endpoints. Monitoring cannot place, cancel or liquidate orders, repair journals or change kill switches.

Credential-free public-source/classifier workers, explicit coverage gaps and the schema-1/schema-2 notification contracts are unchanged; prepared/emitted/suppressed is not acknowledged delivery, and notification-policy activation was not inspected. See [watchdog operations](../watchdog-operations.md) and [notification policy](../watchdog-notifications.md).

Post-close outcomes include untraded candidate ideas. Shadow calibration is separate from actual fills/performance. The public dashboard has a dark/light monitor redesign with the same allowlisted data. Dashboard publication is a separately scheduled mode, not an operation performed by this refresh.

## Verification and regeneration

- Archify **3.0.1**: **9/9 showcase checks, zero errors/warnings**; delivery, strict provenance check and real Chromium browser-check **passed**. The receipt reported an available Archify update (3.2.0); the installed version was used unchanged.
- Browser: light at 1440×900, 1600×1000, 1920×1080 and 2048×1320; dark at both endpoints; READ/Still states. Reader-declared page scrolling is expected for detailed cards.
- Perceptual inspection: font-ready captures at 1440 and 2048 in both themes, native PNG and scrolled cards. One correction round shortened labels that touched node borders at 1440px; afterwards no clipped nodes or overlapping labels were observed. Supporting text is small at laptop scale. Advisory detours on dossier/reconciliation, journal/outcomes and reconciliation/expiry are not machine failures.
- Missing browser shared libraries were supplied from extracted packages in isolated scratch storage. No application, runtime or system configuration was changed.
- Artifact hashes, source counts, PNG dimensions and native export receipts are in `VALIDATION.json`. Source evidence is pinned; it does not show that every modeled path has executed.

Run from the repository root with a matching origin and the pinned source blobs available. Set `ARCHIFY_CLI`, `EVIDENCE_DIR` and, if needed, `ARCHIFY_CHROME` to local tool locations. A restricted host may also need browser libraries/fonts and the tool's explicit local-inspection sandbox opt-out. Do not change application configuration for browser setup.

```sh
node "$ARCHIFY_CLI" finalize workflow \
  docs/process-flow/tradey-desk.workflow.json \
  docs/process-flow/tradey-desk.workflow.html \
  --repo-root "$PWD" --quality showcase --out-dir "$EVIDENCE_DIR" --json

node "$ARCHIFY_CLI" visual-check docs/process-flow/tradey-desk.workflow.html \
  --out-dir "$EVIDENCE_DIR/visual" --summary --require-provenance
```

Generate PNG and dual-theme SVG through the delivered viewer's native **Export** menu; do not hand-edit generated HTML/SVG. Use a fresh evidence directory after candidate changes. Workflow nodes accept at most three source citations and six columns; put extra evidence in `SOURCE_EVIDENCE.json` supplemental ranges. Refresh source ranges before changing revision. Regenerate local delivery provenance at the final artifact location when strict local rechecking is needed; portable validation summaries are not substitutes for that provenance.
