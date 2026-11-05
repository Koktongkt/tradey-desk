# Real-copy migration rehearsal receipts (Task 8)

Validate-only rehearsal of the missing-history migration against the
disposable authenticated real-history copy. No import, apply, digest
production, or activation was performed; production and the copy were
verified byte/mtime/mode unchanged pre/post.

- Evidence (private, 0600/0700):
  `/home/hermes/.hermes/diagnostics/tradey-opportunity-activation-20261105/migration-impl-evidence/`
  - `t8-rehearsal-receipt.json`, `t8-rehearsal.stdout`, `t8-rehearsal.stderr`
  - harness: `harness/t8-rehearsal.py` (runs under the offline guard)
- Canonical refs cross-checked against copy bytes: 0 mismatches.
- Gap census: 67 nested-symbol review gaps, 5 hint rows (no symbol), 6
  hashless filled BUY trade rows → 78 `missing_history` records.
- 124 unresolved-with-source records carried verbatim from the retained
  INCOMPLETE proposal; zero invented scopes.
- `validate_manifest` on the copy: valid, 202 records.
- Gated activation validation (same manifest + activation payload): invalid
  with exactly `activation_incomplete_history` — the remaining gate.
- Pre-migration audit on the copy: blocked, 78 `missing_dossier_sources`.
