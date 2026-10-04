# Tradey Desk process flow

[Download / open the interactive Archify diagram](tradey-desk.html) · [Editable workflow specification](tradey-desk.workflow.json)

GitHub displays HTML as source, not as an interactive page. Download `tradey-desk.html` and open it in a browser; the page is standalone and has no external script dependencies.

## Scope and evidence

This is a source-backed snapshot of the process at commit `4e007c379e4adbdb8e816e2abe1786a371cda5ed`, not an account-status audit or a statement that every scheduled job is currently active. Diagram nodes link to pinned source ranges.

The flow covers scheduled research, verified candidate dossiers, existing-order/protection reconciliation, deterministic market/broker inputs, immutable BUY proposals, parallel independent review, fresh risk checks, protected paper execution, broker readback, durable journals, post-close measurement, separate shadow calibration, and sanitized dashboard publication. Research qualification is not trade approval; order acceptance is not a confirmed fill.

The post-close sequence is a scheduled reporting routine, not an automatic consequence of each fill. Candidate outcomes also include untraded ideas; shadow results are not actual performance. Every required pre-submission gate fails closed. The HOLD branch illustrates review rejection; other failed safety gates also stop new submission.

## Documentation drift observed in the snapshot

- The bridge sends **GTC** brackets, although the root README describes DAY brackets.
- Configuration specifies **$40** planned stop risk, although the root README describes $25.
- The configured IEX spread cap is **600 bps**. This is a single-venue execution-reference spread, not consolidated NBBO.

These are descriptions of inspected code/configuration, not approval of those settings or changes to the trading mandate. This documentation change does not alter orders, schedules, credentials, or risk controls.

## Regeneration

With Archify 3.0.1 installed, run from the repository root, replacing `ARCHIFY_CLI` with its installed absolute path:

```sh
node "$ARCHIFY_CLI" finalize workflow   docs/process-flow/tradey-desk.workflow.json   docs/process-flow/tradey-desk.html   --repo-root "$PWD" --quality showcase --json
```

The specification intentionally pins the inspected source commit. Refresh source evidence before changing that revision. Keep machine-generated local receipts, browser profiles, and diagnostic paths out of Git.

## Validation status

The original artifact passed source/specification validation, showcase layout checks, delivery, and strict artifact checks. Chromium browser inspection timed out twice in the hosted container; browser validation and perceptual visual inspection were not completed. A generated HTML file is not proof that the browser gate passed.
