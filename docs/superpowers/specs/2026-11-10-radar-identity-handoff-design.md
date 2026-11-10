# Radar → event-memory correction: design for review

Status: User-approved staged design (Telegram: “Confirm and proceed”, 2026-11-10). Stage 1 is earnings handoff plus diagnostics; Stage 2 family expansion remains a subsequent reviewed increment. Written implementation-plan review and execution-method selection precede implementation. This document does not authorize a policy reset, durable migration or trading-control change.
Source baseline: Tradey Desk 81c60f9e44c9f4fa9a00d3acc91171cd229db5f5, inspected 2026-11-10 UTC.

## Intent and success

Repair the trusted evidence-to-event-memory handoff so a genuinely identifiable new event can reach investment analysis while unchanged reviewed events remain blocked. Candidate yield is not a quota. Identity admission, investment qualification, reviewer approval and order placement remain separate outcomes.

The user approved the correction's scope: compatible evidence, broader catalyst identification, accurate diagnostics and end-to-end verification. This draft makes the architecture and delivery trade-off explicit before implementation.

## Alternatives

1. RECOMMENDED: staged, typed evidence adapters. First restore a verifiable earnings path and diagnostics; then add non-earnings families as separately reviewed contracts. This isolates the observed compatibility defect and avoids inventing a generic event fingerprint.
2. Deliver all catalyst families together. Broader initial coverage, but requires more schema/compatibility work and creates a larger unproven release.
3. Use a model-generated event summary or URL hash as identity. Rejected: paraphrases, syndicated URLs and event updates could revive the same event. Disabling memory is also rejected.

## Non-negotiable invariants

- Keep paper-only mode, current exposure/position/submission limits, held/pending-entry exclusions, source-quality and freshness gates, earnings blackout, independent reviewers, attached protections and deterministic order validation unchanged.
- Preserve policy v2's existing prospective baseline and manual-only reopening. No reset, legacy-binding import, historical rewrite, allowance grant or automatic reopening.
- Do not treat a local hash, model assertion or matching text fragment as publisher authenticity or sufficient semantic identity.
- Unknown/conflicting event identity continues to fail closed. Do not label it as an already-spent event.
- No shared Hermes edits, gateway restart, new provider/key, cron change or larger research budget is part of this correction.

## Architecture

### 1. Separate investment evidence from identity evidence

Keep the existing normalized, bounded article representation for synthesis and source-quality checks. Introduce an acquisition-owned identity-evidence envelope rather than requiring the normalized article body itself to be a complete filing.

The envelope must bind the requested and returned document locators, acquisition provenance, source digest, typed extracted facts, and exact retained supporting material. The authoritative issuer/document association must be established by trusted acquisition, not by discovery/model JSON.

Primary pages that were unavailable or contradictory must remain distinguishable. A supporting article must not be mistaken for an unresolved authoritative primary document solely because a model selected its URL. Conversely, a missing or contradictory required primary document cannot be silently discarded to obtain admission.

### 2. Earnings adapter: first production increment

Retain the existing earnings event key semantics (issuer CIK + fiscal year/period) and known-binding validation. Add an acquisition path that can actually supply authentic structured issuer/report facts within bounded resources.

Two evidence contracts must be distinguished:
- Periodic filings: validated SEC document locator plus context-bound issuer and fiscal-report facts from authentic raw structured evidence.
- Results announcements/8-K exhibits: verified SEC/issuer association and explicit reported fiscal period, with an authenticated filing-to-exhibit or issuer-release relationship. An 8-K filing date alone is not the earnings period, and a release announcing a future report is not completed results.

Do not resolve earnings merely by calendar quarter, a URL slug, article date, publication timestamp or model-inferred period. Fiscal-year differences, amendments, guidance attached to a results announcement, and multiple issuers in a filing require explicit tests.

Before implementation, select the minimal authoritative acquisition contract using retained real source fixtures and the current SEC client. If the required structured evidence cannot be obtained within the existing budgets, keep that candidate unknown and disclose the source-coverage limitation rather than truncating or guessing. A proposed bounded receipt format must prove equivalence to retained source facts; it cannot become an unauthenticated substitute for a complete filing.

### 3. Capture and truncation integrity

Recognize actual provider truncation declarations, including the observed 50,000-character footer. Provider-representation completeness and whole-document completeness must be separate states.

Do not raise the 85,000-byte article capture ceiling blindly, manufacture closing HTML, or keep an arbitrary filing prefix as a complete document. Identity retention needs its own explicit bounded contract, full-source integrity evidence and complete supporting facts. Capacity exhaustion remains typed and fail-closed.

Do not relabel old cached captures as valid. Any new receipt format must be versioned and revalidated; unavailable old evidence becomes an explicit miss, not newly acquired truth.

### 4. Non-earnings support: second increment

Keep the resolver extensible with typed family adapters, but do not enable a generic free-text fallback.

Each family must define issuer identity, event identity, authoritative evidence, event state, alias/update relationships and negative cases before production admission:
- Contracts: authoritative award/agreement identity; distinguish announcement from amendment, extension and a genuinely different award.
- Acquisitions: authenticated transaction/parties and agreement identity; distinguish signing, shareholder/regulatory steps, completion and termination without granting automatic reopening.
- Regulatory: authoritative agency/application or proceeding identity and explicit decision/milestone; distinguish application acceptance from approval.
- Standalone guidance: explicit issuer/reporting-period/revision relationship; avoid giving a second allowance to guidance already belonging to the same earnings event.

When no reliable machine-verifiable stable key exists, use the existing explicitly reviewed binding process, not invented IDs. Unsupported families remain visible as coverage limitations. Adding family serialization or new persistent schemas requires compatibility and rollback review; it is not included in an earnings-only release by implication.

### 5. Diagnostics and operator output

Use the existing private research-policy diagnostic stream, not a new global ledger registry member. Preserve compatibility with reason/timestamp-only historical rows.

New bounded fields: schema version, opaque run/candidate correlation, stage, normalized policy outcome, resolver status/subreason, adapter/family when established, capture kind/status and bounded counts. No raw URLs, articles, prompts, arbitrary error text or secrets in public output. Private correlation is not identity authority.

Separate these final outcomes: transport failure; insufficient source quality; identity unavailable/unsupported; identity conflict; verified event already spent; held/pending exclusion; candidate qualification failure; qualified dossier. Keep actual source errors in the private record even when identity is the terminal boundary. Do not turn a real infrastructure failure into exit-zero success to improve alerts.

Test error precedence, CLI token admission, decision-audit classification, notification rendering and monitoring compatibility together.

## Verification and release gates

1. Reproduce the observed flattened/truncated-SEC failure before product edits, with retained source-only fixtures and no live ledger imports.
2. Test actual acquisition representation → validated identity envelope → resolver → policy admission → synthesis/qualification orchestration. Mock investment judgment where appropriate, but prove real evidence parsing separately.
3. Negative cases include wrong ticker/CIK/period, conflicting primary documents, redirect mismatch, missing provenance, forged model receipt, same event at new URLs, truncated/capacity captures, stale evidence, unsupported family, spent event, held/pending issuer and baseline mismatch.
4. Freeze pre-existing policy v2 baseline fixtures independently. Prove existing index/allowance/dossier validation, manual reopening and rollback remain valid; do not regenerate all fixtures with the new code and call that backward compatibility.
5. Use isolated source and source-only captures; operational DBs/ledgers are not test fixtures. Protect production reads as well as writes. Default-on external-model launch guards must cover all suite entrypoints.
6. Require the established full and raw test suites, explicit skip inventory, unchanged operational content/metadata and independent review of frozen code bytes.
7. Any real-network validation is research-only, isolated from production operational storage and broker tools, with bounded attempts agreed in the implementation plan. A successful mock does not prove current-host acquisition coverage; a successful identity does not prove an investment qualifies.
8. Production activation/deployment and the first meaningful scheduled outcome are separate verification claims. Do not promise restored yield before an eligible-window scheduled run reaches qualification under unchanged gates.

## Expected code surfaces

Existing: alpha_radar.py, opportunity_identity.py, retained_article.py, research_extraction.py, source acquisition/cache adapters, run_cycle.py and affected tests/monitoring readers. Prefer a small dedicated identity-evidence adapter module rather than expanding the radar monolith. The implementation plan must inventory every strict persistent-schema consumer before introducing any new identity representation.

## Approval requested

Approve the staged approach: earnings handoff + truthful diagnostics first, followed by family-specific non-earnings support after those contracts are reviewed. This is not a request to disable memory, reset history or relax execution protections. The next artifact is the written implementation plan; implementation starts after its review and execution-method selection.
