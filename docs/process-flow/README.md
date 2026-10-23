# Tradey Desk process flow

[Interactive workflow](tradey-desk.workflow.html) · [Editable JSON](tradey-desk.workflow.json) · [PNG preview](tradey-desk-preview.png) · [SVG export](tradey-desk-preview.svg) · [Source evidence](SOURCE_EVIDENCE.json) · [Validation summary](VALIDATION.json)

Download and open the HTML locally; GitHub does not execute HTML. The standalone viewer retains light/dark themes, zoom, source inspection, focus/search, route exploration and native exports. The newly generated PNG is **4026×3456**. Native PNG/SVG exports exclude viewer controls and source badges; the decorative grid remains. `tradey-desk.html` is an unchanged **historical artifact**, not the current workflow.

## Frozen source, not operational readback

This refresh describes committed main source **`237b8251e027c5469263a4afbb6688a0789388fd`**, inspected from an isolated worktree. It does not establish current account state, installed schedules, policy activation, live model/broker execution, alert delivery or deployment. No deploy or push was performed. Runtime tests were not rerun by this documentation worker.

The diagram has **80 source citations** bound to committed blobs and valid inclusive ranges. `SOURCE_EVIDENCE.json` records their SHA-256 identities and **10 supplemental ranges** supporting overview cards. SRC markers remain local-only, without implying remote publication or access. `VALIDATION.json` is a portable summary of real local receipts, not an Archify delivery sidecar. Machine-specific delivery/browser receipts and screenshots are intentionally not committed.

## Research and current cadence

- Enabled checked-in path: six-lane discovery (broad, SEC, issuer IR, reporting, undercovered wire, rotating sector), followed by a one-turn tool-free selector admitting at most five source-bound company/event pairs. Discovery itself does not require a two-source bundle.
- Focused search, safety validation and fair allocation select at most five URLs per candidate / 25 unique URLs, using at most three singleton extraction supervisors. Actual extraction envelopes establish content. Trusted focused pages can be reused by ordinary evidence collection; cache, SEC dates and publication recovery retain their own contracts.
- Evidence eligibility requires **at least two distinct accepted publisher domains**. Ranking considers provenance, corroboration, primary sources, completeness and freshness; scout order breaks ties. Thin-bundle rescue preserves accepted evidence and resumes bounded operations across up to three candidates: retained alternatives, SEC primary lookup, then independent/wire gap searches using actual result URLs. With initial eligible bundles, deferred rescue follows their local rejections; deadlines and spent recovery allowances never reset.
- Up to **five distinct ranked evidence-eligible candidates** receive **sequential synthesis plus shared intake**. Explicit none or candidate-local policy rejection continues. First intake success returns immediately. Infrastructure, parse, containment, ambiguous market-data and persistence failures abort instead of trying another candidate.
- **270 cumulative synthesis seconds**, with **no per-candidate cap**; **90 separately cumulative enrichment seconds**. Enrichment pauses synthesis charging but still consumes the **960-second absolute active deadline**. The research wrapper is **990 seconds**. Launch/reserve minimums remain enforced.
- Synthesis receives actual UTC/New York as-of anchors and must supply a future timezone-aware UTC ISO exit and 1–30 entry-inclusive holding sessions. No dates are repaired. Intake is exit-aware through planned exit plus weekday blackout; the existing broker actual-session earnings gate remains authoritative and unchanged.
- Enrichment resolves trusted earnings and synchronized completed stock/SPY prices. **Massive REST** supplies prices and completed daily technical bars/volume; its credential is read from Massive MCP configuration, not fetched through a Massive market-data MCP call. Alpaca MCP supplies account/orders/calendar and IEX quote truth. **FRED is not integrated into the candidate flow.**
- Premarket: **09:00 ET**. Radar: **10:00–15:40 ET at :00/:20/:40**. Autotrader versioned UTC grid: **`18,38,58 13-20 * * 1-5`**. The NY slot and weekday 09:30–16:00 window jointly accept **09:38/09:58**, then **10:18–15:58 at :18/:38/:58**. 09:18, obsolete slots and off-window fires do not execute. These cheap launch fences do not infer holidays/early closes; broker regular-session checks still gate entry.
- Eighteen-minute producer/consumer spacing leaves a nominal 90 seconds after the 990-second wrapper, **not a guarantee of non-overlap**. Separate reconciliation uses `2,12,22,32,42,52 * * * 1-5`, with its own NY maintenance fence and the shared nonblocking entry lock. Versioned schedules are not installed-job readback.

## Preserved execution and storage boundaries

- Checked-in configuration is enabled/paper with **three daily submissions**, including unknown submissions by their original New York submission date; **three qualified pending parents** is a different, cross-session limit. `exact_owned_zero_fill_v1` and `new_intents_session_close_v1` remain in force. Other observed limits: $10,000 managed exposure, $500 per position, $40 planned risk, IEX spread ≤600 bps, whole shares and no margin.
- Pending observations precede no-candidate/freshness/already-reviewed skips and do not themselves stop a later eligible candidate. Confirmed-exit returns remain distinct. Acceptance is not fill; lifecycle observations do not invent journal fills.
- Exact saved zero-fill parent/held-child ownership is required. Unknown/manual/unlinked orders, partial fills, same-symbol pending entries, invalid/stale proof, capacity and funding failures block. Gross cash reserves pending notional once; available-net buying power is a separate cap, not subtracted twice. Pending notional reserves exposure headroom too.
- Initial sealed snapshot/local-state qualification feeds sizing and pre-review validation. Post-review checks revalidate it; fresh broker-review truth is independently requalified before durable intent. Canonical `.entry_state.lock` serializes the complete entry cycle and operational reconciliation. Python fixes executable fields before hashing; independent tool-free DeepSeek/GLM reviewers cannot replace them. Both must approve; lower score ≥0.55 and reward/risk ≥1.6.
- New short 1–5-session entry deadlines use placement-session regular close; swing 6–30 uses next actual session regular close. Entry deadline is not investment holding deadline. Expiry remains **observation-only**, `SAFE_PARENT_CANCEL_VERIFIED=False`; legacy intents are not retrofitted. Expiry alone releases no slot, reservation or daily quota.
- Operational reconciliation imports JSONL projections only when an existing SQLite database is present. `verify_only` qualification uses immutable read-only SQLite under the cooperating storage lock; business bytes remain preserved. Unsynchronized projections/lifecycle repair, corrupt/divergent state and nonempty WAL/recovery journals fail closed. Coordination locks may still be created.
- Stable outer Linux subreaper owns the inner supervisor, wrapper and detached orphans. Caller pidfd and inherited entry-lock descriptions preserve authority through caller death until descendants are reaped. External custodian SIGKILL/OOM, container death and uninterruptible tasks are outside the internally controlled cleanup guarantee. This is not a sandbox or a rollback of an accepted broker request.

## Independent watchdog and reporting

Mechanical (:05 inside an actual session, 120-second hard bound) and daily (close+15 / close+45, 900-second hard bound) remain separate read-only monitoring tracks, never trading approvals. Reporting-only retry after committed daily observation does not repeat retrieval. Monitoring cannot place/cancel/liquidate orders, repair operational journals or change kill switches.

Credential-free public-source/classifier workers use an ephemeral provider-only gateway; the classifier has no broker, web/tools, memory or agent loop. Missing lineage/baselines, incomplete financial content, exact earnings-time and benchmark gaps remain explicit. SEC metadata is not extracted financial content. Cancelled protection or an expired horizon still forbids all-clear.

Public reports are allowlisted. Relay stdout is not a provider receipt. Schema 1 retains the legacy pending-outbox policy. **Only explicit schema-2 activation** enables concise latest-condition notifications, historical suppression, separate emission bookkeeping, 24-hour persistent-urgent reminders and one daily summary after report installation. Prepared/emitted/suppressed is not acknowledged delivery; crashes can lose messages and a transport that sends then raises can duplicate. Activation was not inspected. See [watchdog operations](../watchdog-operations.md) and [notification policy](../watchdog-notifications.md).

Post-close outcomes include untraded candidate ideas. Shadow calibration is separate from actual fills/performance. Dashboard publication is a separately scheduled mode, not an operation performed by this refresh.

## Verification and regeneration

- Archify **3.0.1**: **9/9 showcase checks, zero errors/warnings**; delivery, strict provenance check and real Chromium browser-check **passed**.
- Browser: light at 1440×900, 1600×1000, 1920×1080 and 2048×1320; dark at both endpoints; READ/Still states. Containment, readability, theme and chrome checks passed. Reader-declared page scrolling is expected for detailed cards.
- Perceptual inspection: font-ready 1440px light and 2048px dark captures, native PNG and scrolled cards. No clipped nodes or overlapping labels observed. Supporting diagram text is small at laptop scale; use zoom/cards. Advisory detours remain on dossier/reconciliation, journal/outcomes and expiry paths; they are not machine failures.
- The host initially had no usable default fonts and incomplete browser libraries. Those initial captures omitted text despite geometry checks. Browser-only dependencies/fonts were supplied in isolated scratch paths; finalization, captures and native exports were rerun. No application/runtime configuration was changed.
- Artifact hashes, source counts, PNG dimensions and native export cleanliness receipts are recorded in `VALIDATION.json`. Source evidence is pinned, not evidence that every modeled path has executed.

Run from the repository root with a matching origin and the pinned source blobs available. Set `ARCHIFY_CLI`, `EVIDENCE_DIR` and, if needed, `ARCHIFY_CHROME` to local tool locations. A restricted/fontless host also needs browser libraries/fonts and may need the tool's explicit local-inspection sandbox opt-out. Do not change application configuration for browser setup.

```sh
node "$ARCHIFY_CLI" finalize workflow \
  docs/process-flow/tradey-desk.workflow.json \
  docs/process-flow/tradey-desk.workflow.html \
  --repo-root "$PWD" --quality showcase --out-dir "$EVIDENCE_DIR" --json

node "$ARCHIFY_CLI" visual-check docs/process-flow/tradey-desk.workflow.html \
  --out-dir "$EVIDENCE_DIR/visual" --summary --require-provenance
```

Generate PNG and dual-theme SVG through the delivered viewer's native **Export** menu; do not hand-edit generated HTML/SVG. Use a fresh evidence directory after candidate changes. Refresh source ranges before changing revision. Regenerate local delivery provenance at the final artifact location when strict local rechecking is needed; portable validation summaries are not substitutes for that provenance.
