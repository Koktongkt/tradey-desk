# Stage 2 Agreement Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver supported acquisition and contract identities without reviving spent event allowances.

**Architecture:** Trusted bounded source acquisition feeds pure family adapters and a shared versioned identity loader. Preserve earnings serialization and all policy/economic rules. Source readiness is a prerequisite, not a test fixture invented during coding.

**Tech Stack:** Existing Python, unittest, urllib and existing evidence/state APIs; no dependencies or provider changes.

**Spec:** docs/superpowers/specs/2026-11-11-stage2-agreement-identity-design.md plus owner-approved amendment `docs/superpowers/specs/2026-11-11-stage2-original-agreement-amendment.md` (commit 87a603a, SHA-256 c01c70b66dfca2002229e200c3cb25a94ebb9f996c886c97df45152ea9270e3d). Amendment A controls any conflict about automatic original-agreement roots.

## Execution authority

Delivery scope amendment: the owner accepted the recommendation to implement acquisitions first and defer contracts after Amendment A established an authentic acquisition/update chain but no clean commercial positive. All references below to both-family delivery now mean acquisition-only delivery; contract enablement is explicitly excluded. Retain contract source negatives and the same acceptance/release gates. No further scope approval is needed for this package.

Wire contract: v3 adds only `agreement` to the existing resolution envelope, retains `period=null`, and uses family `acquisition`. `agreement` is a closed object containing `root`, `executed_on`, ordered Parent/Merger Sub/Company `parties`, retained normalized-span `witnesses`, and explicit source-linked `independent_from` document IDs. The root's four fields are those fixed by Amendment A. The v3 key hashes canonical JSON `{version:3,family:acquisition,root:<root>}` with prefix `oe3:`. Earnings v1/v2 payloads omit `agreement` entirely and keep their original IDs. Automatic prospective acquisition admission additionally requires a process-local source-validation seal that is never serialized; stored shape or a reason string cannot recreate it. Literal-link and raw-byte proof remain mandatory. Synthetic independence examples test the explicitly approved relationship contract and do not claim historical evidence or universal source-format coverage.

The owner explicitly requested direct implementation and conditional production rollout after approving the written spec. Execute natively without another plan-review round, as an explicit override of the default handoff gate. Retain source-readiness, TDD, independent SPEC/QUALITY acceptance and compatibility/rollback requirements. The production request authorizes application source promotion/publication only after those gates pass, not administrative binding grants, durable-state migration, configuration changes or weakened trading controls.

## Global Constraints

- Acquisitions and contracts only; no generic headline/prose/URL fingerprint.
- Preserve policy v2's prospective baseline, existing spent generations and manual-only reopening. No policy reset, migration, legacy binding import, historical rewrite or administrative grant is authorized.
- No broker access in identity acquisition/resolution; no production operational storage in tests or source probes.
- No Hermes configuration, gateway restart, provider/key change, cron change or larger research budget.
- Preserve existing earnings IDs and accepted v1/v2 payloads byte-for-byte.
- Use existing 32-URL invocation cache, 15-second fetch ceiling, 2,000,000-byte raw source and 3,000,000-byte capture limits with the inherited absolute deadline.
- Keep all paper-only mode, enabled state, economic, source/freshness, held/pending, review and execution gates unchanged.
- One source writer, native execution; independent final SPEC and QUALITY reviewers on identical final bytes. No new arbitrary per-task owner permission gates.

## Review Focus

1. A document ID masquerading as agreement identity must never create an automatic event (Task 1/2).
2. Amendments with new identifier spellings must not revive spent events (Task 2/3).
3. Mixed earnings/agreement history must replay without changing old identities (Task 3).
4. Separate family link traversals must not receive separate time/request allowances (Task 4).
5. Rollback after new-format records must not start an incompatible entry reader (Task 5).

## Task 1: Source-readiness and unchanged baseline

**Files:** private source-only evidence under `test_artifacts/stage2_agreements/`; no runtime edits. Approved spec and this plan are the source contract.

**Interfaces:** consumes existing SEC exact-URL capture and locator contracts; produces a source-readiness table binding an actual issuer, admitted root kind, original entry/parties/roles, authenticated item-to-executed-agreement relationship, independent continuity proof, exact supporting spans and raw-byte digest. For `sec_original_agreement`, identity fields are exactly `kind`, `issuer_cik`, `original_report_document_id`, `original_agreement_document_id`; source proof, not locator shape alone, establishes originality. A reviewed-root positive still requires genuinely approved binding authority, not a proposed record.

- [ ] Preserve the original failed investigation (four searches/eight document fetches) without reclassifying it as successful. Amendment-readiness has a new cumulative cap: four searches, twelve exact public document attempts and sixteen HTTP requests including redirects. No Radar run, broker calls, production ledger access, model subprocess, broad crawl, unsafe redirect or acquisition-until-success. Search/extraction locates evidence but is not trusted full-capture authority. Count actual requests/failures.
- [ ] Require one authentic automatic acquisition original-disclosure/linked-executed-agreement positive and one contract positive, plus an authentic explicit update-to-original chain. Apply all five Amendment A evidence predicates. Use supported text-native original 8-K bundles; MNDO/WYFI and periodic summaries are not promised positives.
- [ ] Before product edits, freeze the exact supported source structures and normalization/span contract from authentic full-byte captures. If required originals, issuer facts, executed agreement or continuity proof remain missing, return the precise blocker. No v3 skeleton, blanket-rejection adapter, synthetic authority or deployment satisfies readiness. No further general design/plan approval is needed for the already approved root contract.
- [ ] Verify the existing linked worktree, protected-main HEAD/status and interpreter. Inspect tests' actual guards before running unchanged targeted identity baselines. Preserve real logs/exits; dependency/import failures are harness failures, not behavioral RED.

Expected: authentic source-readiness table plus unchanged targeted baseline proof, or an explicit source-contract blocker. No claimed implementation completion from readiness alone.

## Task 2: Freeze wire contract and implement pure family resolution with TDD

**Files:** create `agreement_identity_resolution.py`, `tests/test_agreement_identity.py`; modify `opportunity_identity.py`; register the test in `tests/test_manifest.json`.

**Interfaces:** `resolve_agreement_captures(symbol: str, captures: tuple, *, known_resolutions: tuple[dict, ...]) -> EventResolution`; pure, no I/O. Exact root and payload grammar must be recorded from Task 1's admitted source contract before writing tests; no unsupported authority or default root is permitted.

- [ ] Add behavioral RED tests for authentic original acquisition/contract bundles, all five source predicates, misleading 'entered into' amendment wording, multiple exhibits/subjects, subsidiary roles, same event/new URL, amendment-first, distinct same-party/day agreements with independence proof, and unresolved replacement chains.
- [ ] Extend the strict identity representation with a new non-earnings version, closed family/root grammar and recomputed event key. Do not overload earnings `period`; preserve old payloads and IDs. Bind supporting spans to retained bytes and authenticated relations. Reject shape-valid forged model authority.
- [ ] Implement only Task 1's admitted source formats. Resolve updates to the original root. Require complete coherent known-root comparison across root kinds, including spent events; missing known evidence cannot establish novelty. Unknown identifier/namespace, ambiguous issuer/subject, conflicting aliases and unresolved continuity fail closed; no generic text classifier.
- [ ] Run actual identity and new agreement test modules RED then GREEN, retaining both receipts and the independent frozen old earnings fixtures.

Expected: both real positive families pass the pure boundary and every continuity/authority negative is blocked. A source contract absent in Task 1 cannot be invented here.

## Task 3: Close persistence, state and administrative readers

**Files:** `opportunity_identity.py`, `opportunity_state.py`, `opportunity_admin.py`, `tests/test_opportunity_identity.py`, `tests/test_opportunity_state.py`, `tests/test_opportunity_admin.py`, `tests/test_opportunity_workflow.py` and actual strict consumers discovered before edits.

**Interfaces:** existing `candidate_identity`, `_load_binding`, state reconstruction, dossier validation and reviewed binding paths consume the exact Task 2 representation. No new authority producer or allowance algorithm.

- [ ] Write RED tests for mixed v1/v2/new-version replay, cross-root-kind duplicate handling, serializer round trips, durable evidence references, immutable dossier attribution, spent HOLD/disagreement/fill, held/pending exclusions and unchanged manual reopening. Exercise the real prospective-reason allowlist in `candidate_policy`; a model/caller reason string is not trusted producer authority.
- [ ] Wire all real consumers to the shared strict loader; preserve version-specific validation. No rewriting existing records or baseline fixtures.
- [ ] Run all affected full modules GREEN. Inventory the actual producer-consumer closure, including saved-dossier reuse, before claiming compatibility.

Expected: new records can be retained and read back under supported code without changing old event/allowance semantics.

## Task 4: Radar acquisition integration and truthful diagnostics

**Files:** `alpha_radar.py`, `earnings_identity_acquisition.py` or a minimal shared acquisition helper, `policy_diagnostics.py`, `tests/test_opportunity_radar.py`, `tests/test_earnings_identity_evidence.py`, new agreement tests and monitoring tests only where a strict schema requires compatibility.

**Interfaces:** reuse trusted `IdentityCapture`, the code-owned per-run acquisition context, shared absolute deadline and safe injected transport. Family resolution receives trusted captures, never model fields.

- [ ] Write RED tests through real capture -> family resolution -> policy -> trusted dossier -> synthesis seam, with isolated synthetic state and mocked investment judgment only.
- [ ] Add only the authenticated literal-link traversal admitted in Task 1; share dedupe, request and elapsed-time budgets with earnings. Check deadline before fetch/read/parse/handoff; retain captures before references.
- [ ] Preserve transport, capacity, incomplete-body, unknown-identity and conflicting-identity precedence and bounded private diagnostics. Add no public URL/body/prompt leakage or arbitrary error text.
- [ ] Prove spent same-event updates invoke no synthesis; independent new events can reach existing qualification. Run affected Radar, diagnostics, earnings and agreement modules GREEN.

Expected: both families exercise the actual orchestration, with truthful source failures and unchanged downstream gates.

## Task 5: Acceptance and conditional production release

**Files:** immutable private acceptance/release receipts, source/test changes from Tasks 2–4 only and necessary documented compatibility target. No operational-state migration is implied.

- [ ] Freeze final runtime/test hashes. Run `python tests/run_tests.py full` and raw `python -m unittest discover -s tests -p 'test_*.py' -q` with the verified accepted interpreter, offline guards and explicit skip/isolation evidence.
- [ ] Run at most one isolated live acquisition canary per delivered family (two total, each using only the readiness-established exact source chain, with a shared 32-URL cap per invocation). Deny broker access and production storage; record exact capture/identity outcomes. No order canary or model research launch.
- [ ] Obtain fresh independent SPEC and QUALITY verdicts against the same frozen bytes and real receipts. Reproduce findings RED -> GREEN; any changed bytes require affected proof and final matching acceptance.
- [ ] Resolve rollback before deployment: demonstrate a compatible reader/entry refusal with protection/reconciliation continuing after new-version persistence. Do not silently create an operational fence or amend policy. If existing mechanisms cannot supply the required rollback, stop with the exact release blocker and smallest proposed operational package.
- [ ] After acceptance, follow the existing live-refactor deployment workflow: verify Git authentication, newly publishable ancestry, actual scheduled workdir/interpreter, unchanged config, necessary writer quiescence/drain, reviewed source promotion, production full/raw gates, remote push/readback and restoration of only release-paused jobs. No reset/activation/admin grants.
- [ ] Report source acceptance, publication, runtime deployment, schedule restoration and first substantive scheduled result separately. Never wait-loop for a future scan or describe resumed scheduling as a successful scan.

Expected: accepted and verified production deployment, or exact unresolved source/release blocker with production unchanged.

## Self-review

Spec sections 1–3 map to Tasks 1–2, representation/consumer closure to Tasks 2–3, bounded orchestration/diagnostics to Task 4 and verification/release to Task 5. All five review-focus conditions have owning tests. Task 1 intentionally stops before a speculative wire contract when independent source authority is missing; later tasks are not executable until that producer dependency is established. The owner's direct-execution request removes the default plan-review round, not these safety and completeness gates.
