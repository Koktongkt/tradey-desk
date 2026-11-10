# Radar Identity Handoff — Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore verifiable earnings-event admission from authentic acquisition evidence, with truthful private diagnostics and unchanged event spending/trading protections.

**Architecture:** Keep investment article evidence and identity evidence separate. An application-owned acquisition adapter supplies bounded original SEC evidence; pure deterministic resolution creates the existing earnings event identity. The active baseline, allowances and final entry lock remain authoritative; diagnostics describe failures without authorizing anything.

**Tech Stack:** Existing Python standard library, urllib safe transport/deadline utilities, unittest, existing SQLite/JSONL ledger APIs; no new package, MCP, model or provider.

**Spec:** `docs/superpowers/specs/2026-11-10-radar-identity-handoff-design.md` (approved staged scope).

## Global Constraints

- Stage 1 only: earnings plus diagnostics. Contracts, acquisitions, regulatory events and standalone-guidance identities remain Stage 2.
- Preserve policy v2's existing prospective baseline and manual-only reopening. No reset, legacy-binding import, historical rewrite, allowance grant or automatic reopening.
- Keep paper-only mode, current exposure/position/submission limits, held/pending-entry exclusions, source-quality and freshness gates, earnings blackout, independent reviewers, attached protections and deterministic order validation unchanged.
- Unknown/conflicting event identity continues to fail closed. Do not label it as an already-spent event.
- No shared Hermes edits, gateway restart, new provider/key, cron change or larger research budget.
- Keep the 85,000-byte article capture contract unchanged; identity captures use an explicit separate contract.
- Work outside the deployed checkout; one implementation writer. No operational databases or production policy records become test fixtures.
- Observe RED before runtime fixes. Default-on offline model/network/process guards must cover new subprocess paths if any are introduced; none is planned.
- Production mutation, live research, source publication, source deployment and scheduled success are separate stages with separate receipts. No implementation-plan test places orders.

## Review Focus

1. Missing full raw source despite readable Markdown: a candidate must stay unknown, never gain identity from generated prose (Tasks 1–3).
2. Non-calendar fiscal year and future/prior-quarter language in a release: never guess the reported fiscal period from report date (Task 3).
3. Old v2 activation plus old evidence captures: retain exact baseline and allowance semantics; reject unsupported capture kinds safely (Tasks 2 and 5).
4. Additional I/O consuming evidence time: enforce the existing absolute deadline before request/open/body/handoff and keep downstream reservation (Task 4).
5. Identity failure coexisting with publisher errors: preserve both causes and truthful final severity without reviving a spent event (Task 5).

## File and interface map

- New `earnings_identity_evidence.py`: bounded acquisition, original-source capture envelope, source-linked issuer/report parsing helpers; no ledger access or investment judgment.
- Existing `opportunity_identity.py`: consume typed trusted evidence; unchanged earnings key and strict existing binding/issuer conflict checks; retention adapter.
- Existing `alpha_radar.py`: supply acquisition-owned identity evidence inside existing evidence budget; record detailed policy diagnostics and final outcome.
- Existing `retained_article.py`: recognize observed provider truncation without expanding article retention.
- Existing `opportunity_state.py` and any discovered capture validators: compatibility for explicitly versioned identity evidence only; no baseline/allowance algorithm changes.
- Existing `run_cycle.py`, `tests/test_cycle.py`, monitoring strict readers: exact new diagnostic/output compatibility, if required by Task 5.
- Tests: new `tests/test_earnings_identity_evidence.py`; extend identity, radar, workflow, retained-article and watchdog tests; register new test module in `tests/test_manifest.json`.
- Source-only fixtures: ignored `test_artifacts/identity_handoff/`, with private 0700 directories, 0600 files and hash/provenance manifest. No operational DB snapshots.

## Task 1: Establish authentic earnings evidence contracts and baseline reproductions

**Files:** new source-only fixture manifest and `tests/test_earnings_identity_evidence.py`; existing `tests/test_opportunity_identity.py` and `tests/test_retained_article.py`.

**Interfaces:** consumes existing `resolve_event(symbol, pages, known_resolutions=())`, `_cover(raw, symbol, cik, legal_name=None)` and `retain_article(page, text, ...)`; produces frozen real-evidence positive/negative fixtures plus a table of which document contracts can be proven without inference.

- [ ] Inventory production acquisition/capture consumers and test environment read-only. Read AGENTS.md, offline-test isolation reference and current full/raw suite entrypoints. Preserve baseline source hashes and first test results.
- [ ] Freeze retained November 9 flattened SEC examples and the exact observed provider truncation footer. Record that cache timestamps do not establish complete historical bundles.
- [ ] Obtain or locate authentic source-only raw evidence for a periodic filing and a results 8-K plus its literal linked exhibit. Existing retained authentic captures first; any necessary external fetch is a bounded exact-URL research-only acquisition, never a radar/main/broker run. Record requested/returned URL, transport, timestamp, bytes and SHA-256; no fabricated HTML or fixture metadata.
- [ ] Freeze labels before product code: issuer, form, reported fiscal year/period, result state, exact source anchors and unresolved fields. A results exhibit without authoritative fiscal-year/period support is a negative, not a guessed positive.
- [ ] Write RED cases `test_flattened_filing_cannot_bootstrap_identity`, `test_provider_truncation_is_incomplete`, `test_authentic_periodic_filing_handoff`, `test_authenticated_results_exhibit_handoff`. Preserve baseline failures and classify expected old rejection versus unintended failure.
- [ ] Contract readiness gate: at least one real new earnings event must have sufficient primary evidence and a bounded acquisition path. If this cannot be demonstrated, STOP with the exact source-contract blocker; do not deploy a diagnostics-only patch as restored earnings support. Any materially different acquisition/identity contract returns to design review.
- [ ] Commit only the source-only fixture recipe/manifests and test changes permitted for publication; keep raw/private captures out of Git.

## Task 2: Add bounded, separately versioned identity-source capture

**Files:** new `earnings_identity_evidence.py`; modify `opportunity_identity.py` retention helpers and any actual strict capture consumer found in Task 1; extend new evidence tests and existing durability tests.

**Interfaces:** produces `IdentityCapture` (frozen acquisition-owned value), `capture_identity_source(url: str, raw: bytes, *, returned_url: str, content_type: str) -> IdentityCapture`, `validate_identity_capture(value: IdentityCapture) -> bool`, and `identity_source_bytes(value: IdentityCapture) -> bytes | None`. Constructors are trusted acquisition code, not model/provider envelope decoders.

- [ ] Write RED tests for full-byte digest/locator binding, capacity, incomplete body, invalid encoding, duplicate JSON keys, nonstandard constants, forged capture injection, changed projection and unsafe retention paths.
- [ ] Set `MAX_IDENTITY_SOURCE_BYTES=2_000_000` (same maximum body size already used by direct research fetching). Read one extra byte to detect oversize; require EOF and reject over-limit/truncated body. Do not infer EOF from Content-Length alone.
- [ ] Encode raw bytes as base64 in a separate strict capture envelope with `kind='sec_identity_source'`, `version=1`, requested/returned URL, content type, source digest and explicit completeness. Maximum canonical encoded envelope `3_000_000` bytes; metadata bounded to fit. No arbitrary source metadata or proposed identity fields accepted.
- [ ] Keep existing retained-article envelopes valid under their current 85,000-byte ceiling. New envelope dispatch must be explicit, hash-addressed and bounded before full parsing; unknown kinds/versions reject. Never rewrite existing captures.
- [ ] Preserve dirfd/no-follow/owner/0600/0700/fsync/no-clobber rules. Test collisions, symlinks, oversized files and partial publication. Persist every required capture before publishing any resolution/candidate link.
- [ ] Run evidence and identity durability tests through the verified environment; commit the tested unit.

## Task 3: Resolve supported earnings identities from authentic source facts

**Files:** new evidence module; modify `opportunity_identity.py`; extend `tests/test_opportunity_identity.py` and new adapter tests.

**Interfaces:** produces `resolve_earnings_capture(symbol: str, captures: tuple[IdentityCapture, ...]) -> EventResolution`; integrate with `resolve_event` through a trusted argument that defaults to empty and is never read from model candidate JSON. Existing `candidate_identity()` remains the canonical serializer.

- [ ] Write RED tests using Task 1's real positive sources and independently frozen wrong-issuer/period/missing-source negatives. Include filing-agent accession versus registrant CIK, non-calendar fiscal year, amended/duplicate representation, changed URL and source ordering.
- [ ] For 10-Q/10-K, validate complete raw document structure and context-bound DEI facts using existing cover semantics; retain existing CIK+earnings+fiscal-period key, not a document/date hash.
- [ ] For results 8-K/exhibit, require authenticated registrant cover, a literal same-accession filing-to-exhibit relationship tied to reported results, and explicit reported fiscal-year/period support from the exact exhibit/report header. No inferred year/quarter from filing date, quarter-end, URL or comparative tables. Unresolved fiscal-period mapping stays unknown. The Task 1 readiness table determines admitted representations; no generic text classifier is authorized.
- [ ] Preserve complete-bundle issuer/period conflict behavior. Do not silently discard an unavailable required primary. Treat unregistered secondary corroboration as investment evidence, not a fabricated primary identity anchor.
- [ ] Preserve the canonical earnings key. Add defaulted `version: int = 1` to `EventResolution`; existing constructors and v1 records retain their current meaning. New identity-capture-backed resolutions serialize version 2 with the same top-level/document keys, reason `sec_periodic_filing` or `sec_results_exhibit`, and explicit v2 capture validation. `_load_binding` accepts exactly versions 1 and 2 with version-specific reason/capture contracts; `candidate_identity` round-trips that version. Merging agrees on issuer/period and preserves the maximum required evidence version. No automatic result is relabeled as reviewed `explicit_binding`. Test old-reader rejection of v2 records and continued protection/lifecycle; evidence format v2 is distinct from the unchanged policy activation version 2.
- [ ] Assert same results event across releases/filing representations yields one key; another fiscal period yields a different key; future earnings announcements and guidance-only text cannot create reported-results identity.
- [ ] Run all identity/adapter tests, commit the tested unit. Publish an exact supported/unsupported earnings-contract list; coverage is not universal earnings support.

## Task 4: Wire identity acquisition into Radar without new deadline allowances

**Files:** `alpha_radar.py`, new evidence adapter, affected focused/source-capture code only if proven necessary; `tests/test_opportunity_radar.py`, `tests/test_alpha_radar.py`, new adapter tests.

**Interfaces:** produces `acquire_identity_captures(symbol: str, pages: list[dict], *, deadline: float) -> tuple[IdentityCapture, ...]`; consumes existing safe URL admission and shared HTTP-body deadline helpers via injected trusted transport. No new model subprocess.

- [ ] Write RED orchestration test where provider Markdown remains unchanged for synthesis but authoritative SEC evidence resolves identity and launches synthesis once.
- [ ] Reuse raw acquisition evidence already available. Only for missing identity evidence fetch an owned exact SEC locator or literally authenticated same-accession exhibit link. Deduplicate per-run document requests; no new broad search or latest-filing substitution.
- [ ] Charge acquisition to the existing 180-second evidence allowance and overall/downstream reservations; no constant increases. Check deadline before preparation, open, each bounded body read and handoff; no second independent allowance.
- [ ] Strip incoming `_identity_*` fields from untrusted discovery/model/provider payloads. Supply typed capture objects through code-owned context, not serialized model fields or a caller-controlled hash.
- [ ] Preserve normal ranking, candidate attempt limits, thin-bundle rescue admission and source-quality gates. Identity recovery does not turn an insufficient investment-evidence bundle into a qualified one.
- [ ] Test advancing clocks, zero remaining time, unsafe redirect, oversized source, transport denial, duplicate request and per-candidate failure followed by a healthy alternative. Assert no broker/model execution tools are added.
- [ ] Run focused, evidence and radar suites; commit the tested integration.

## Task 5: Add correlated diagnostics and truthful final outcomes

**Files:** `alpha_radar.py`, `run_cycle.py`, relevant watchdog strict readers if needed; existing cycle/radar/watchdog tests.

**Interfaces:** extend `_record_policy_skip` with keyword-only bounded context; append existing stream `private/research_policy_diagnostics.jsonl`, not a new DEFAULT_STREAMS member. Diagnostic fields: `schema_version`, aware timestamp, opaque `run_id` and `candidate_token`, stage, policy reason, resolver status/subreason, capture kind/status and bounded counts.

- [ ] Write RED tests for reason/timestamp-only legacy rows plus new rows; verify one candidate's resolver result can be joined to one run without raw symbol/URL/body/prompt leakage.
- [ ] Keep a normalized allowlist of subreasons; bound text/counts, reject nonfinite/boolean numeric substitutions, and never persist arbitrary exception text. Diagnostics cannot change event identity or allowance state.
- [ ] Separate verified spent/held/pending exhaustion from unresolved identity. An identity-unavailable run must not present as proven no-new-opportunity merely because every admitted lead was rejected. Keep real transport failures nonzero and preserve identity/source causes separately; public severity follows the exercised terminal boundary.
- [ ] Add exact CLI tokens to scheduler parser and audit classifier together when needed. Test mixed transport+identity failures, unrelated source errors, candidate-local transport errors, unsupported earnings contracts, later successful candidates and persistence errors. No global notifier/cron formatting changes.
- [ ] Test the new records against the watchdog local allowlist and an independently frozen old policy v2 descriptor. Do not change global stream membership or migrate the activation.
- [ ] Run cycle/radar/watchdog tests and commit the tested diagnostic unit.

## Task 6: End-to-end safety, compatibility and independent review

**Files:** workflow/activation/entry/reuse tests; `tests/test_manifest.json`; release evidence outside protected operational roots.

- [ ] Register the new test module in the correct explicit tier. Ensure direct unittest discovery installs the existing offline guard before new test imports. No unexpected external model/network operation may be swallowed.
- [ ] Observe end-to-end RED then GREEN with real source-only earnings evidence, isolated policy v2 activation fixture, candidate append, index reload and synthesis seam. Prove changing prose/URL cannot restore a spent HOLD/disagreement event; a genuinely new reported period remains eligible subject to unchanged checks.
- [ ] Exercise legacy captures, immutable frozen old baseline, stale reuse/fallback, malformed binding, held/pending exclusion, manual reopening, concurrent activation/final append and rollback with lifecycle/protection continuing.
- [ ] Run `python tests/run_tests.py full` and `python -m unittest discover -s tests -p 'test_*.py' -q` in the verified dependency environment with guards on. Retain exact commands/exits/counts/skip reasons plus source hashes and operational content/metadata isolation.
- [ ] Obtain fresh independent review of frozen runtime/test bytes and the supported-contract claim. Resolve findings with observed failing regression tests, rerun affected suites and full gates, and preserve reviewed-byte attribution.

## Task 7: Bounded live readiness and controlled release handoff

**Files:** private readiness/release receipts; public operating documentation only after verified changes.

- [ ] Before publication/deployment, report tested commit, supported earnings contracts, unsupported cases, capture format compatibility and rollback behavior. No production policy payload or baseline is rewritten by this repair.
- [ ] For an approved real-network readiness check, use one isolated research-only run from pinned source with production operational reads/writes and all broker entrypoints denied. Preserve actual source acquisition/identity/synthesis/qualification outcomes; do not rerun until success or count seeded output as market discovery.
- [ ] If current-host authoritative acquisition cannot supply identity, stop rollout and report the precise blocker. Green offline tests are not source-provider readiness.
- [ ] Publication/deployment must use the existing live-refactor release workflow: frozen reviewed source, compatible rollback, preserved job settings, paused affected writers only during promotion, drain, exact source/config hashes, production verification and readback. No automatic policy activation/reset or job reslotting.
- [ ] After release, measure the first substantive scheduled scan separately. Report evidence-ready → identity-admitted → synthesis → qualified counts, plus real candidate-level failures. A valid no-trade result remains valid; do not weaken gates to hit a yield target.

## Self-review and handoff

The approved Stage 1 requirements map to Tasks 1–7. Stage 2 is explicitly not implemented here. Capture bounds, provenance, deadlines, old-baseline compatibility, duplicate suppression and failure reporting each have an owning test unit. Task 1 is a deliberate evidence-readiness gate: unsupported source contracts are blockers, never an excuse to invent identity.

Execution selection is pending user review: Native (one writer implements in this session, fresh independent whole-change review) or Subagent-driven (fresh implementer and reviewer per unit). Native is recommended because acquisition/capture/resolver interfaces are tightly coupled and a single writer makes tested-byte attribution clearer.
