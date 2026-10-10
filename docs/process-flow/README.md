# Tradey Desk process flow

[Interactive workflow](tradey-desk.workflow.html) · [Editable JSON](tradey-desk.workflow.json) · [PNG preview](tradey-desk-preview.png) · [SVG export](tradey-desk-preview.svg)

The actual generated name is `tradey-desk.workflow.html`, matching `meta.output`. GitHub cannot execute HTML: download and open it locally. The standalone viewer has no external script dependency. Both static exports were freshly generated using the native Archify exporter from the delivered HTML; PNG is 4011×3450. Viewer controls and source badges are omitted from the export; its decorative grid remains. `tradey-desk.html` is an untouched historical artifact, not this refresh.

## Current policy amendment

The user authorized `max_daily_orders=3` (previously 2). This counts submissions, including pending/unknown submissions, not just fills. All other controls remain unchanged. The frozen diagram and source graph below describe the earlier `0d3a5a5` source pin and its daily cap of 2; they are historical artifacts, not a current configuration readback. The config-only amendment has focused pipeline coverage plus full/raw offline suites passing at 898 tests each.

## Frozen source and release status

Source pin: `0d3a5a554bf2c36b758f085ab46e56d2a317f7a8`. This is a **frozen candidate-only local pin, NOT deployed**. The final independent offline review returned **PASS**, with all 16 reviewed source hashes verified against this pin. The user authorized commit and push of the reviewed code and finalized artifacts. This publication approval is separate from artifact checks and does not authorize or demonstrate live deployment, scheduler activation, model calls or broker execution. Changed runtime bytes require a new pin and artifact regeneration. The diagram establishes no account state, current broker capability, scheduler activation, eligible-run observation, performance, or alert delivery.

Every source citation was re-read from this isolated pin (71 diagram citations bound to committed blobs; two supplemental inspected excerpts retained separately), including both independent watchdog tracks. Local-only SRC markers intentionally avoid suggesting that the unpublished pin is available on GitHub. The isolated clone's stored origin is a local clone path; validation used a process-local Git `url.<public identity>.insteadOf` mapping to the inherited credential-free repository identity. No Git config, remote, commit, index, live checkout, or source file was changed. Verification still read the exact local committed blobs and line ranges, not network content.

## Trading conditions represented

- Checked-in settings: enabled=true, paper, `exact_owned_zero_fill_v1`, pending parents=3, `new_intents_session_close_v1`. Unchanged: daily submissions=2, $10,000 managed exposure, $500 position, $40 planned risk, IEX spread≤600 bps, whole shares, no margin. GTC and $40 correct the prior DAY/$25 narrative; they are observed implementation/configuration, not newly authorized policy.
- Pending observations happen before candidate freshness/no-candidate/already-reviewed skips and do **not** stop a later eligible candidate. Confirmed-exit return paths remain distinct. Acceptance is not fill; lifecycle updates do not create phantom trade-journal fills.
- Exact zero-fill saved parent/held-child ownership is required. Unknown/manual/unlinked orders, partial fills, same-symbol pending entries, stale or forged proof, exhausted capacity, invalid funding and other safety gates fail closed. Three parents across sessions is not three submissions/day: unique submission identities, including unknown submissions, retain their original New York submission date.
- Sealed proof is bound to current snapshot and local state. Initial qualification feeds sizing and pre-review validation; post-review validation rechecks it; independently requalified fresh broker-review proof gates the unchanged reviewed plan immediately before durable intent. Canonical `.entry_state.lock` serializes the complete entry cycle across processes and operational reconciliation; no force-unlock/inode rotation.
- Gross cash subtracts verified pending notional once; available-net buying power remains a separate cap and is not subtracted again. Pending notional also reserves managed-exposure headroom. The mapping's source records a 2023 Alpaca developer-relations note and orders documentation, not a newly verified live account contract.
- Immutable forward-only new-intent deadlines are included in the proposal/hash: short 1–5 sessions at placement-session **regular** close; swing 6–30 at next **actual** session regular close. Authoritative New York open/close rows cover early close, DST and holidays. This is an entry deadline, not the investment holding deadline.
- Expiry is **OBSERVATION ONLY**, `SAFE_PARENT_CANCEL_VERIFIED=False`: no automatic cancellation/activation path. Legacy intents without metadata, including legacy UBER, are not retrofitted; no actual UBER order was inspected. Passing a deadline never releases a slot, cash/exposure reservation or daily quota. Release requires exact broker-confirmed terminal/fill lifecycle reconciliation.

## Storage and process boundaries

Operational reconciliation explicitly imports JSONL projections **only when an existing SQLite database is present**. Qualification uses `verify_only`: read-only immutable SQLite under the cooperating storage lock, with business JSONL/SQLite bytes preserved. Unsynchronized projections/lifecycle repair produce typed `managed_repair_required`; corrupt/divergent state fails closed. Nonempty WAL/recovery journals block rather than being ignored or checkpointed by the reader. Coordination locks may be created; this is not a claim of zero filesystem effects.

Native bridge launches use an isolated Linux subreaper, pidfd-bound process identity, a stable outer per-launch subreaper custodian plus an inner supervisor, with bounded kill/reap cleanup preceding return and entry-lock release. Offline probes found no living or zombie owned process before lock release, including forced escalation. Detached orphans are included. External custodian SIGKILL/OOM, container destruction and uninterruptible tasks are explicitly outside the internally controlled reaping guarantee. This is not a filesystem/network sandbox, and there is no unconditional OOM/SIGKILL/container-death guarantee or rollback of a broker request already accepted.

Research selects search/web or text-only synthesis, not broker execution. Both independent tool-free DeepSeek/GLM reviewers receive the same immutable proposal/hash and effective qualification capacity; they cannot replace executable fields. Broker credentials stay at the deterministic broker boundary, not in research evidence/model prompts.

## Independent watchdog and reporting

The mechanical and daily tracks remain read-only monitoring, not trading approval gates. Mechanical eligibility is :05 inside an actual session; daily eligibility is close+15 / close+45, with reporting-only retry after committed observation. Code-defined cadence is not live scheduler readback. Their separate monitoring lock and monitoring state/outbox cannot authorize placement, cancellation, liquidation, operational journal repair or kill-switch changes.

Public-source and classifier workers are credential-free; classifier accesses only the ephemeral provider-only gateway, with no broker/web/tools/memory or agent loop. Missing lineage, legacy baselines, incomplete financial content, exact earnings-time and benchmark gaps remain explicit; filing metadata is not extracted financial contents. Fully observed cancelled protection or expired holding horizon still forbids all-clear.

Reports/public projections are allowlisted. Relay stdout is not a provider receipt: outbox stays pending and may repeat. Completion is not acknowledgment. Post-close candidate outcomes include untraded ideas; shadow calibration is separate from actual fills/performance. See [watchdog operations](../watchdog-operations.md) for the source-defined operational contract.

## Regeneration

Run from the isolated repository root, with Archify 3.0.1 and a fresh evidence directory. The process-local origin mapping below is required only for this local-path clone; a normal matching HTTPS/SSH origin does not need it.

```sh
GIT_CONFIG_COUNT=1 \
GIT_CONFIG_KEY_0=url.https://github.com/Koktongkt/tradey-desk.git.insteadOf \
GIT_CONFIG_VALUE_0=/opt/data/projects/tradey-desk \
node "$ARCHIFY_CLI" finalize workflow \
  docs/process-flow/tradey-desk.workflow.json \
  docs/process-flow/tradey-desk.workflow.html \
  --repo-root "$PWD" --quality showcase --out-dir "$EVIDENCE_DIR" --json

node "$ARCHIFY_CLI" visual-check docs/process-flow/tradey-desk.workflow.html \
  --out-dir "$EVIDENCE_DIR/visual" --summary --require-provenance
```

Refresh inspected source ranges before changing revision. Never hand-edit generated HTML. Local machine receipts/captures are not portable publication artifacts; regenerate delivery provenance at the final publication location if needed.

## Actual validation of this refresh

- Showcase: **9/9**, zero errors, zero warnings; all 71 pinned diagram source citations bound to committed blobs at `0d3a5a554bf2c36b758f085ab46e56d2a317f7a8`. Delivery, strict provenance check and real Chromium browser-check all **passed** (Archify 3.0.1).
- Browser evidence passed at 1440×900, 1600×1000, 1920×1080, 2048×1320; endpoint light/dark themes and READ/Still states checked.
- Automated containment/readability/theme checks passed on all four endpoint captures. All four captures, the native PNG export, SVG-rendered capture and cards capture were subsequently inspected: no clipped nodes or overlapping labels; both watchdog tracks and deadline-observation branch are distinct. Supporting text is small at 1440px; use zoom and the explanation cards for detail. Advisory route-review hints remain for long dossier/reconciliation, journal/outcomes and expiry paths; disclosed detours, not machine failures.
- Runtime tests were **not rerun by this artifact worker**. The runtime worker's offline remediation logs (SHA-256-frozen in `offline-log-evidence.json`) report fast=494, scenario=284, full=896 and raw=896 tests passing (raw retains 20 pre-existing SQLite ResourceWarning lines; the three canonical tiers have zero), plus the independent forced-escalation probe green with no living/zombie owned process before entry-lock release. These are offline candidate-source results awaiting parent independent review, not runtime activation or release evidence.
- Specification SHA-256: `796af4921a6eaa5dbaee877378b3f4bbf11c25f53442a6d75d88ad0b07330415`.
- HTML SHA-256: `7b973df42b103959bd0dece9f2496638def1d3b86a4d22e09d4c8f1395c933ce`.
- SVG SHA-256: `558d6fcc06094ab3ee150e9b7733c01c90230f131de8c3a3c2d6fefb7e8ad50e`.
- PNG SHA-256: `36cce47a8133fa07dfb0f1e9277d16289691e06806e9fb5b969c3f803e1b91e2`.

Local audit bundle: `/opt/data/analysis/tradey-three-evidence/archify/final-pin/`; finalize receipt: `tradey-desk.workflow.finalize.json`; compact receipt: `tradey-desk.workflow.finalize-summary.json`; browser receipt: `tradey-desk.workflow.browser-check.json`; screenshots/contact sheet and strict visual receipt under `visual/`; source citations/excerpts in `source-audit.json`; native exports in `export-receipt.json`; frozen offline test-log digests in `offline-log-evidence.json`; final confinement and changed-file hashes in the bundle's `completion.json`. These paths are local evidence pointers, not proof of publication.
