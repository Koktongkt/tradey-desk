# Tradey Desk process flow

[Download / open the interactive Archify diagram](tradey-desk.html) · [Editable workflow specification](tradey-desk.workflow.json)

GitHub displays HTML as source, not as an interactive page. The root README embeds [a static PNG preview](tradey-desk-preview.png) rendered from the delivered HTML's SVG using Chromium and system fonts (decorative grid and Viewer controls omitted). Download `tradey-desk.html` and open it in a browser for interaction; the page is standalone and has no external script dependencies. The preview was visually inspected for legibility and clipping; it is separate from the interactive browser evidence.

## Scope and evidence

This is a source-backed snapshot of the process at commit `d2bb7ee67c4bc0651a379eb59ae718f7df8f32d4`, not an account-status audit or a statement that every scheduled job is currently active. Diagram nodes link to pinned source ranges. Existing source references were refreshed against this revision, including the exact pending-bracket reconciliation release.

The flow covers scheduled research, verified candidate dossiers, existing-order/protection reconciliation, deterministic market/broker inputs, immutable BUY proposals, parallel independent review, fresh risk checks, protected paper execution, broker readback, durable journals, the **portfolio watchdog**, post-close measurement, separate shadow calibration, and sanitized dashboard publication. Research qualification is not trade approval; order acceptance is not a confirmed fill.

The post-close sequence is a scheduled reporting routine, not an automatic consequence of each fill. Candidate outcomes also include untraded ideas; shadow results are not actual performance. Every required pre-submission gate fails closed. The HOLD branch illustrates review rejection; other failed safety gates also stop new submission.

## Portfolio watchdog: monitoring only

The watchdog lane contains two independently scheduled tracks, not extra approval gates for the trader:

- **Mechanical:** UTC `5 14-21 * * 1-5`, filtered to :05 inside the verified actual market session. Reads exact paper-broker references and operational ledgers; observes protection, quantity, exits, holding horizon and exposure. Hard outer bound: 120 seconds.
- **Daily:** UTC `15,45 17-22 * * 1-5`, filtered to close+15 / close+45, including DST and early closes. Adds managed-strategy versus account accounting, benchmark coverage, versioned-thesis source retrieval and tool-free classification. Hard outer bound: 900 seconds.
- **Read-only trading boundary:** no placement, cancellation, liquidation, operational-journal repair or kill-switch change. A separate monitoring lock cannot block the trader. Both tracks write monitoring state/reports/outbox under `private/watchdog/`; the two store nodes summarize the same monitoring subsystem, not separate databases.
- **Visible gaps:** missing lineage, legacy baselines, incomplete financial contents, unknown exact earnings timestamps and missing benchmark evidence cannot become all-clear. SEC filing metadata is not financial-content extraction. A fully observed cancelled stop or expired holding horizon is still an exception.
- **Isolation:** public-source workers and the classifier client are credential-free; classification reaches only an ephemeral provider-only gateway with no tools, broker, web or memory access. The daily track also includes the mechanical observations; the overview compresses those shared checks.
- **Outputs:** private observations and reports, field/value-allowlisted public projections, sanitized cron stdout and a pending alert outbox. Successful mechanical runs without exceptions are silent; daily runs emit a report/coverage summary. Outside-slot launches are no-ops, not successful observations.
- **Retry and receipts:** after a daily observation is committed, the later slot retries reporting, outbox delivery and the completion marker only—not thesis retrieval. Relay stdout provides no provider receipt, so alerts remain pending and may repeat. Completion does not prove delivery; neither silence nor a retry alone proves all-clear.

See [watchdog operations](../watchdog-operations.md) and [runtime readiness](../watchdog-runtime-readiness.md) for implementation boundaries and known coverage limitations. This diagram does not establish that an eligible unattended observation or confirmed alert delivery has occurred.

## Documentation drift observed in the snapshot

- The bridge sends **GTC** brackets, although the root README describes DAY brackets.
- Configuration specifies **$40** planned stop risk, although the root README describes $25.
- The configured IEX spread cap is **600 bps**. This is a single-venue execution-reference spread, not consolidated NBBO.

These are descriptions of inspected code/configuration, not approval of those settings or changes to the trading mandate. This documentation change does not alter orders, schedules, credentials, or risk controls.

## Regeneration

With Archify 3.0.1 installed, run from the repository root, replacing `ARCHIFY_CLI` with its installed absolute path and `EVIDENCE_DIR` with a fresh local evidence directory:

```sh
node "$ARCHIFY_CLI" finalize workflow \
  docs/process-flow/tradey-desk.workflow.json \
  docs/process-flow/tradey-desk.html \
  --repo-root "$PWD" --quality showcase --out-dir "$EVIDENCE_DIR" --json

node "$ARCHIFY_CLI" visual-check docs/process-flow/tradey-desk.html \
  --out-dir "$EVIDENCE_DIR" --summary --require-provenance
```

The specification intentionally pins the inspected source commit. Refresh source evidence before changing that revision. Keep machine-generated local receipts, browser profiles, captures and diagnostic paths out of Git. Re-export the static preview from the newly delivered SVG, not an older HTML or browser screenshot.

## Validation status — 2026-10-09

- **Showcase validation:** 9/9 checks, zero errors, zero warnings; pinned source evidence verified.
- **Delivery and strict provenance/artifact checks:** passed.
- **Automated Chromium browser evidence:** passed at 1440×900, 1600×1000, 1920×1080 and 2048×1320; light/dark theme and READ/Still state checks passed.
- **Visual inspection:** light and dark captures inspected at both endpoint sizes, including the long dossier-to-reconciliation and journal-to-outcomes routes. Both monitoring tracks are distinct; no visible node/label clipping. Exported PNG also inspected.
- **Regression suite:** canonical `full` tier passed: 838 tests, zero failures/errors/skips.
- **Specification SHA-256:** `793471093a78b836ad8559fc14a02091d9c4b5a94edb15390211aa32dad884b2`.
- **HTML artifact SHA-256:** `68fabbcf57f7838d9a18d5b1a2e0135462d88aefb152e05ba5685e50dc98bf51`.
- **PNG preview:** 2448×1992; SHA-256 `8a579dad2c58a96711d0c2af68c0feec54c8474d0947d65485c854eefb6640ec`.

These are diagram-validation results, not portfolio safety, performance, scheduler activation or delivery-receipt claims.
