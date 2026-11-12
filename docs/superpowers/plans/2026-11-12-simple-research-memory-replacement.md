# Simple Research Memory Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace formal event/allowance research admission with exact-document completed-work reuse without weakening independent execution safeguards.

**Architecture:** One small private research-memory component owns complete-content keys, completed-result reuse and transient URL cooldowns. A one-time validated v3 transition retires event admission, while shared entry/history helpers retain exact-attempt and operational safeguards independently of event allowances. All consumers switch together; intermediate commits are not production releases.

**Tech Stack:** Existing Python, unittest, canonical SQLite/JSONL storage, immutable capture utilities and standard library only.

**Spec:** `docs/superpowers/specs/2026-11-12-simple-research-memory-replacement-design.md`, approved in chat after documentation commit `72ee7664570ceedb4e432ea9e80872240af9dcfe`.

## Global Constraints

- Runtime baseline `0cad12b8860938035f839ffb3f46d0b6b2db5533`; documentation baseline `72ee7664570ceedb4e432ea9e80872240af9dcfe`. Recheck HEAD before execution; do not overwrite unrelated changes.
- `policy_version=3`, mode `exact_document_research_dedup`; this is a retirement transition, not a new event/allowance system. No implicit version-0 escape.
- Research result reuse is at most 24 hours from original completion and always constrained by stricter existing freshness/TTL rules. Exact issuer/URL/transient-reason cooldown is 20 minutes.
- Complete content, verified issuer, representation kind, rule version and stage determine document identity. A sorted set of all admitted document keys determines a synthesis bundle; a shared document alone cannot suppress new evidence.
- No transaction matching, model-declared materiality, permanent ticker/publisher ban, new provider/package, expanded research budget, Hermes edit/restart or cadence change.
- Paper-only authority, configuration, held/pending exclusion, dual approval, risk/earnings/source checks, order ownership/idempotency and lifecycle remain intact. Never change `enabled` or `broker_mode`.
- Existing operational and policy history is append-only. No clearing reviews, restoring an old DB, rehashing historical dossiers or removing activation to enable entry.
- TDD is mandatory: retain behavioral RED, minimal implementation, GREEN and unique receipts for each task. Loader/fixture/environment failures do not establish behavioral RED.
- Implementation is isolated; production cutover needs separate exact-manifest approval. No orders or paid/live research canaries during implementation.

## Review Focus

1. Same bytes from two providers may have different representation contracts; they must not cross-hit. Pin in Task 1.
2. Redirected URLs, document-reference symlinks and conflicting issuer attribution cannot borrow trusted cached results. Pin in Tasks 1–2.
3. A result write may fail after captures persist; inert captures must not become completed work, and concurrent duplicate writes must be idempotent. Pin in Task 2.
4. A HOLD can race a cache lookup or a fill can arrive during dual review; subsequent boundaries must reject, not trust old in-memory approval. Pin in Tasks 4–6.
5. A successful commit with lost acknowledgement or crash between SQLite/projection operations cannot create a second transition/order or bypass integrity handling. Pin in Tasks 3, 5 and 8.

## Execution setup and test convention

Before feature edits, use `superpowers:using-git-worktrees` and obtain consent for an isolated worktree if no applicable consent exists. Preserve deployed main. Resolve a supported interpreter using current runtime helpers and existing suite environment; do not guess a former host path or install into Hermes. Set an execution-local shell function `tpy` to that verified interpreter, record its absolute path/version, and keep that environment through the run. `tpy` below denotes that recorded executable, not an assumed command already installed.

Read `AGENTS.md`, `tests/run_tests.py`, `tests/offline_test_guard.py`, the production-root write guards used by the last accepted release, and pinned fixture requirements before running tests. Use ignored `test_artifacts/simple_memory/` within the isolated worktree for private logs and inner fixture roots; no fixture root may resolve to production. All new test modules import/install the offline guard before application imports and are classified exactly once in `tests/test_manifest.json`.

Run focused modules as `tpy -B -m unittest discover -s tests -p 'test_<name>.py' -v`; each command passes only on exit 0, all intended tests executed, expected skip inventory and zero unexpected guard attempts. Full gate: `tpy -B tests/run_tests.py full -v`. Raw gate: `tpy -B -m unittest discover -s tests -p 'test_*.py' -v`, with pre-import guard and production-write protection equivalent to the canonical harness. The direct-Hermes audit hook is not a general network sandbox: stub all provider/model/broker I/O at owning boundaries and preserve subprocess containment tests.

Baseline focused/full/raw gates precede behavior changes. If prerequisites or baseline fail, reproduce and report; do not weaken assertions or silently skip safety coverage. Long runs use tracked terminal jobs with completion notification, never fabricated counts. Each task ends with focused GREEN and a narrowly staged conventional commit; full/raw must also pass before release.

## File and interface map

Create:
- `research_memory.py`: keys, strict completed-result/cooldown records and lookup, no broker permissions.
- `evidence_capture_store.py`: event-independent private immutable capture/result persistence using existing formats.
- `research_mode.py`: coherent version dispatch and trusted current transition context, no legal event resolution.
- `research_memory_transition.py`: one-time root/prefix-bound prepare/validate/apply/status CLI.
- `review_history.py`: strict exact-dossier historical completion and safe-retry decision.
- `entry_authority.py`: sealed current-dossier binding and exact dual-approved attempt proof, no allowance generation.
- `tests/test_research_memory_keys.py`, `test_research_memory_store.py`, `test_research_memory_transition.py`, `test_review_history.py`, `test_entry_authority.py`, `test_research_memory_radar.py`, `test_research_memory_workflow.py`.

Modify only owning integration points in `sqlite_ledger.py`, `opportunity_activation.py`, `opportunity_cutover.py`, `opportunity_state.py`, `opportunity_admin.py`, `opportunity_identity.py`, `alpha_radar.py`, `autotrader.py`, `entry_eligibility.py`, `candidate_retry.py`, `acquisition_research.py`, relevant sanitized reporting, test manifest and affected fixtures. Preserve existing utility contracts unless a task explicitly replaces them; no general refactor of large Radar/autotrader files. Historical event readers remain available for old history but leave the v3 admission hot path.

---

### Task 1: Deterministic complete-document and bundle keys

**Files:** Create `research_memory.py`, `tests/test_research_memory_keys.py`; modify `tests/test_manifest.json`. Read `retained_article.py::original_text` and complete-source capture validators.

**Interfaces:**
- `document_key(*, issuer: str, representation: str, content: bytes, rule_version: str, stage: str) -> str` returns `rm1:` plus SHA-256 of a canonical closed envelope containing content SHA-256 and the other exact fields.
- `bundle_key(*, issuer: str, document_keys: tuple[str, ...], rule_version: str, stage: str) -> str` sorts/deduplicates validated keys and hashes the closed envelope as `rb1:` plus SHA-256. Reject empty bundles.
- No network/storage or source-authentication permission is implied by these pure functions. Trusted integration supplies verified issuer/content.

- [ ] **Step 1: Write failing tests.** Assert identical complete content has equal keys despite changed external observation timestamps/URLs; same excerpt with different unseen content differs; issuer, representation, rule version and stage changes differ. Assert `bundle_key(A,B)==bundle_key(B,A,A)` and `bundle_key(A,B)!=bundle_key(A,C)`. Reject blank issuer, malformed key, empty content/bundle and invalid field types. Assert provider representations do not cross-hit.
- [ ] **Step 2: Run focused RED.** Run `tpy -B -m unittest discover -s tests -p test_research_memory_keys.py -v`; record missing API or intended assertion failures after fixtures load.
- [ ] **Step 3: Implement the two pure functions.** Canonical UTF-8 JSON uses sorted keys, compact separators and rejects non-finite values; content bytes are hashed exactly, with no text trimming or semantic normalization. Use explicit version prefixes above.
- [ ] **Step 4: Run focused GREEN.** Repeat Step 2; all key cases pass, no I/O counters increment.
- [ ] **Step 5: Commit.** Stage the named files only; commit `feat: define exact-document research memory keys`.

### Task 2: Durable completed-result lookup and bounded cooldown

**Files:** Create `evidence_capture_store.py`, `tests/test_research_memory_store.py`; extend `research_memory.py`; modify `sqlite_ledger.py::DEFAULT_STREAMS`, `opportunity_identity.py` capture persistence adapter, test manifest and storage tests.

**Interfaces:**
- `evidence_capture_store.retain_page(root: Path, page: dict) -> dict` validates a trusted complete representation and returns a durable closed reference with representation/content digest; reuse existing no-follow/no-clobber private publisher.
- `evidence_capture_store.read_capture(root: Path, ref: dict) -> bytes` verifies containment, schema, modes, exact bytes and digest; never follows an untrusted ref outside the private evidence tree.
- `research_memory.complete(root: Path, *, key: str, stage: str, rule_version: str, capture_refs: tuple[dict, ...], result: dict, disposition: str, completed_at: str) -> dict` persists captures/result first, appends one closed completion to `private/research_memory.jsonl`, returns the record.
- `lookup(root: Path, *, key: str, now: str, freshness_check) -> dict` returns `{status: hit|miss|unusable, record: dict|null, reason: str}`. The supplied freshness callback receives the validated record/result and returns bool; a callback error is unusable, not a hit.
- `note_failure(root: Path, *, issuer: str, url: str, reason: str, failed_at: str) -> None`; `retry_allowed(root: Path, *, issuer: str, url: str, reason: str, now: str) -> bool`. Cooldown rows and completions share the one registered stream but have distinct schemas. Allowlisted transient transport failures only; malformed/unreadable cache yields retry-allowed plus diagnostic, not issuer permission.

- [ ] **Step 1: Write failing tests.** Assert durable complete readback; original timestamps unchanged on repeated hits; no hit at/after 24 hours or on freshness false; failed/partial work never completes; exact replay produces one completion; concurrent replay is idempotent. Missing/tampered captures, incompatible rules, redirected ownership, symlinks/hardlinks, oversize records and result-write failure produce no reusable success. Cooldown blocks the exact resource at 19 minutes, allows at 20, and never blocks a second issuer/URL/reason. Verify storage failure diagnostics and uncached fallback.
- [ ] **Step 2: Run store RED** with focused convention; retain intended failures.
- [ ] **Step 3: Implement event-independent retention and strict lookup.** Reuse complete article/SEC formats; do not require `EventResolution` to persist evidence. Enforce private directory/file modes 0700/0600. Use canonical storage transaction/locking for stream writes and duplicate detection. An acknowledgement failure requires readback before retry; never label uncertain writes as proven completion. Register the new stream without changing DB schema or importing production rows implicitly.
- [ ] **Step 4: Run store/storage/capture GREEN.** Run new module plus `test_sqlite_ledger.py`, `test_durable_jsonl.py`, `test_earnings_identity_evidence.py` and retained-article tests. Preserve crash tests and projection-parity assertions.
- [ ] **Step 5: Commit** as `feat: retain and reuse completed research safely`.

### Task 3: Explicit forward-only retirement transition and mode dispatch

**Files:** Create `research_mode.py`, `research_memory_transition.py`, `tests/test_research_memory_transition.py`; modify activation/historical cutover readers and old admin writers, storage tests and manifest.

**Interfaces:**
- `research_mode.context(root: Path) -> ModeContext`, immutable fields `policy_version: int`, `mode: str`, `transition_id: str|None`, `manifest_sha256: str|None`. Read one validated coherent snapshot; never initialize/repair storage. Versions 0/1/2 retain explicit pre-release compatibility; only a valid v3 transition selects the new mode. Unknown/corrupt history fails closed.
- `research_memory_transition.prepare_manifest(root: Path, *, source_revision: str, rule_version: str) -> dict`; `manifest_digest(manifest: dict) -> str`; `validate_manifest(root: Path, manifest: dict) -> None`; `apply(root: Path, manifest: dict, *, approved_manifest_sha256: str) -> dict`; `status(root: Path) -> dict`.
- CLI: `prepare --root PATH --source-revision SHA --rule-version VERSION`; `validate --root PATH --manifest PATH`; `apply --root PATH --manifest PATH --approved-manifest-sha256 DIGEST --apply`; `status --root PATH`. Prepare/validate/status are read-only and cannot authorize activation.

- [ ] **Step 1: Write transition REDs.** Synthetic valid legacy/v1/v2 roots produce a v3 proposal with exact registered-stream prefixes, prior activation identity and root binding; apply preserves every old prefix. Exact payload replay is idempotent. Wrong root/digest, malformed predecessor, stale watermark, changed historical prefix, divergent duplicate, second reset and unsupported future version fail without new authority. Test projection disagreement, concurrent writer and lost-ack readback. Assert old grant/activation APIs cannot add authority after v3.
- [ ] **Step 2: Run transition RED** with focused convention.
- [ ] **Step 3: Implement version dispatch and dedicated transition.** Keep historical v2 validation separate from final v3 selection; validate prefix snapshots under their own schema without imposing the old exactly-one-activation rule on the whole v3 history. Hold entry then canonical storage writer locks; compare approved manifest in the same append transaction. Derive `transition_id` from the canonical manifest digest. A matching already-applied manifest is recognized before attempting a fresh watermark comparison; mismatched replay is rejected. No history rewriting or automatic unactivation.
- [ ] **Step 4: Run transition GREEN** plus `test_opportunity_cutover.py`, `test_opportunity_admin.py`, `test_opportunity_state.py`, storage and concurrent workflow modules; legacy behavior remains tested, not treated as v3 permission.
- [ ] **Step 5: Commit** as `feat: add forward-only research memory retirement transition`.

### Task 4: Strict exact-dossier completion and safe retry

**Files:** Create `review_history.py`, `tests/test_review_history.py`; modify `autotrader.py::dossier_already_reviewed`, Radar reuse adapter and `candidate_retry.py` only where required; manifest.

**Interfaces:**
- `review_history.dossier_status(root: Path, dossier_hash: str) -> str` returns `unreviewed|completed|retryable`; malformed relevant history raises `ReviewHistoryError`. Validate hash format, strict full relevant review history and linked order/rejection proof. Hashless old records are retained but not fabricated associations.
- Existing callers retain their public signatures while using this strict shared reader; no reader turns an exception into false/not-reviewed.

- [ ] **Step 1: Write review REDs.** Modern HOLD/disagreement/veto and historical action-only BUY/HOLD complete the exact dossier. Later empty/reconciliation/retry markers do not erase completion. Only complete dual-approval plus each linked allowlisted pre-submission rejection yields retryable; submitted/unknown/partial fill, absent proof or earlier HOLD denies it. Malformed/unreadable review or order history raises. Hashless records do not ban an issuer. A review appended after lookup is caught by the next fresh boundary.
- [ ] **Step 2: Run review RED** with focused convention.
- [ ] **Step 3: Implement strict reader and adapters.** Preserve existing independent earnings spending checks. Do not use latest-review timestamp or dossier regeneration as a research-memory key; never skip prior completed rows when a later marker exists.
- [ ] **Step 4: Run review/retry/reuse GREEN** including `test_bridge_and_reuse.py`, `test_opportunity_execution.py`, `test_blocker_diagnostics.py` and new module.
- [ ] **Step 5: Commit** as `fix: preserve strict dossier review history without event allowances`.

### Task 5: Allowance-independent exact candidate and attempt authority

**Files:** Create `entry_authority.py`, `tests/test_entry_authority.py`; modify `autotrader.py` entry-mode dispatch, BUY/final rechecks, `entry_eligibility.py` as needed, manifest. Read `entry_state.py` locking and current authorization proof first.

**Interfaces:**
- `entry_authority.bind_candidate(root: Path, candidate: dict, *, context: ModeContext) -> dict` code-owned candidate binding, attaches current transition before dossier hashing; reject injected authority. Produce an immutable internal token/seal using the existing trusted-intake pattern, not a model field.
- `entry_authority.validate_candidate(root: Path, candidate: dict) -> None` verifies immutable hash, trusted persisted binding and current transition.
- `entry_authority.authorize_attempt(root: Path, *, candidate: dict, proposal: dict, evidence_id: str, review_ref: dict) -> AttemptProof` verifies durable exact dual approvals/current coherent state; proof is sealed, not a dict accepted from an input payload.
- `entry_authority.validate_attempt(root: Path, *, candidate: dict, proposal: dict, evidence_id: str, proof: AttemptProof) -> None` reloads current state and rejects stale/borrowed proof. Current `idempotency_ref` and intent formats remain unchanged except additive authenticated transition references if needed.

- [ ] **Step 1: Write authority REDs.** Valid v3 exact approvals yield proof; wrong dossier/proposal/evidence/transition, forged seal, stale worker, altered payload, concurrent competing attempt and changed history deny. Positive dust, pending/unknown obligation, missing baseline/proof, stale observation and fill during review prevent calls at the applicable pre-review/pre-intent/pre-place boundary. Missing or dissenting approvals never authorize. Test independent earnings rejection and all daily-limit/reservation accounting. Assert unsupported mode still executes meaningful expiry/reconciliation/protection first.
- [ ] **Step 2: Run authority RED** with focused convention.
- [ ] **Step 3: Implement mode dispatch and preserve safety.** V3 replaces only allowance authority. Pre-review, post-review, broker validation and final entry checks still enforce held/pending/risk rules regardless of old activation predicates. Fresh proof generation occurs under canonical entry lock. Do not copy legacy `policy_version=0` behavior into v3. Keep old-mode paths for historical compatibility and controlled rollout.
- [ ] **Step 4: Run authority/execution GREEN** plus entry eligibility, execution policy, pending, safety, expiry, managed reconciliation and existing opportunity execution modules. Assert unchanged order refs and zero duplicate intents/fills in lost-ack fixtures.
- [ ] **Step 5: Commit** as `refactor: decouple exact entry authority from event allowances`.

### Task 6: Integrate Radar memory and retire identity/acquisition admission

**Files:** Create `tests/test_research_memory_radar.py`; modify `alpha_radar.py` startup policy context, pre-fetch skip, pre-synthesis identity acquisition, claim enrichment, binding, append, reuse and failure fallback; acquisition routing adapters, affected tests and manifest.

**Interfaces:** Consume Tasks 1–5 without renaming. Add a small v3 adapter `research_memory_for_bundle(root: Path, *, issuer: str, pages: list[dict], now: str, rule_version: str) -> dict` at the Radar/module boundary, returning lookup status and validated bundle key/capture refs. The issuer comes from deterministic supported issuer mapping, never discovery/model labels as authority. If mapping/complete captures cannot be established, proceed uncached through ordinary quality gates; do not create a new identity-admission blocker. Conflicting source attribution still rejects evidence.

- [ ] **Step 1: Write Radar REDs.** Formal identity unknown with otherwise valid evidence reaches ordinary synthesis in v3. Exact completed bundle avoids duplicate synthesis and advances shortlist within original deadline. New second source, changed content/rule version and different provider representation trigger fresh work. Completed qualified result is reused only if still fresh/unreviewed; HOLD racing reuse/fallback blocks it. Failed work and broken cache run uncached within budget, never become hit. All-duplicate scans report no new eligible work, not infrastructure failure. No additional discovery or reset deadline is allowed.
- [ ] **Step 2: Add routing REDs.** Earnings with historical M&A language reaches its ordinary earnings path; authentic acquisitions and non-earnings leads may reach normal synthesis without event keys but cannot bypass source/corroboration/earnings/thesis/mandate checks. Direct, focused, recovery, rescue and saved-intake paths obey identical v3 authority. Raw research-only envelopes remain non-candidates; removing diversion must not turn storage records into executable dossiers.
- [ ] **Step 3: Run Radar/routing RED** using new module and affected `test_acquisition_research.py` tests; distinguish intended v3 changes from unchanged legacy-mode assertions.
- [ ] **Step 4: Implement coordinated v3 flow.** No v3 `EventResolution`, allowance, reopening grant or identity-only source acquisition is needed for research/synthesis/append. Retain ordinary receipts, original deadlines and source/earnings validation. Persist captures/results before completion records; cache write failure emits diagnostic and does not fabricate success. Apply one shared history/freshness policy to normal reuse and research-failure fallback; old cached candidates are not rehashed or silently promoted. Populate transition authority before new dossier hash. Exact URL cooldown affects only that fetch, never the issuer's alternate evidence.
- [ ] **Step 5: Run Radar GREEN** plus receipt/freshness, research budget, acquisition, focused handoff/reuse, rescue fairness, publication recovery, source extraction, pipeline and authority tests. Measure mock synthesis/fetch counts and deadline consumption in assertions.
- [ ] **Step 6: Commit** as `feat: replace radar event admission with simple completed-work memory`.

### Task 7: Sanitized outcomes and offline comparative replay

**Files:** Extend `tests/test_research_memory_workflow.py`, `tests/test_radar_notifications.py`, `tests/test_pipeline.py`; modify owning diagnostic/public allowlists only; add `docs/simple-research-memory.md`; manifest.

**Interfaces:** Private diagnostics use bounded reason tokens `research_memory_hit`, `research_memory_miss`, `research_memory_unusable`, `research_memory_cooldown`; no raw exceptions. Existing public candidate/no-setup/failure envelopes remain compatible. Report counters separately for duplicate stages skipped, completed result reused and newly qualified dossier; do not label hits as fresh qualifications.

- [ ] **Step 1: Write reporting/replay REDs.** Private diagnostics retain typed reason and stage while public outputs exclude captures, hashes, filesystem/account/broker IDs and private reviews. Replay a pinned synthetic sequence: same bundle twice, changed bundle, failed fetch then exact retry cooldown, ordinary source failure and downstream HOLD. Assert fewer duplicate synthesis calls than uncached replay, unchanged independent decisions/order mutations and no claim of market-wide coverage. Cached hits do not renew TTL or qualified counts.
- [ ] **Step 2: Run reporting RED** with focused new and notification modules.
- [ ] **Step 3: Implement allowlists/counters and runbook.** Document exact key/TTL/cooldown semantics, fallback/history integrity distinction, transition CLI, no implicit activation, interpretation of historic event rows and compatible rollback. Document real limitations, not guaranteed yield. No live market/model/broker fetch for replay.
- [ ] **Step 4: Run reporting/replay GREEN.** Save actual call counts, outcomes and timing receipts under isolated test artifacts. Use code to count all replay instances; report comparison scope as offline functional evidence, not production improvement.
- [ ] **Step 5: Commit** as `test: verify simple memory savings and sanitized outcomes`.

### Task 8: Complete safety, transition and rollback release proof

**Files:** Extend `tests/test_research_memory_workflow.py` and affected lifecycle/storage concurrency tests; release receipts under ignored `test_artifacts/simple_memory/`; docs runbook.

**Interfaces:** Consumes frozen candidate source commit, exact fixtures and real receipts. Produces independently reviewed implementation acceptance, compatible rollback source pin and explicit ready/not-ready cutover report, not activation.

- [ ] **Step 1: Write remaining workflow REDs.** Transition plus live-style synthetic candidate/review/intent lifecycle succeeds only for exact v3 proof. Crash/ack loss during transition or intent append is reconciled by exact readback without duplicate authority/order/fill. Modified prefix, projection disagreement, stale worker, review race, pending order and unsupported mode fail closed while meaningful lifecycle protection runs. Compatible predecessor reader refuses v3 entry with lifecycle intact.
- [ ] **Step 2: Run workflow RED**, then make minimal owning fixes and repeat GREEN; retain one causal test per discovered failure.
- [ ] **Step 3: Run canonical full and raw offline gates.** Same frozen runtime, guards, supported interpreter and pinned fixtures; compare actual test inventories/counts/skips, require zero unexpected model/broker/Hermes I/O and unchanged protected paths. A raw/full mismatch is investigated, not waved away. Snapshot private-safe file metadata/hashes before/after tests through existing release isolation helpers.
- [ ] **Step 4: Rehearse retained-history compatibility.** On a separately scoped disposable authenticated read-only-derived history copy, use SQLite backup API for a WAL database, not an ad hoc live file copy. No production repair/activation. Prepare/apply/read back the test root's own manifest and test compatible rollback. Do not reuse the disposable manifest for production; preserve all predecessor prefix receipts. If real-history access or fixture provenance cannot be established, report that acceptance gate blocked.
- [ ] **Step 5: Freeze and independently review.** Record Git/source/test/fixture hashes and actual command exits. Fresh reviewer checks approved spec, staged diff, all acceptance receipts, transition and broker-safety boundaries. Fix Important/Critical findings via RED→GREEN; rerun affected and full/raw gates on changed bytes, then obtain final review on the exact accepted tree. Native execution uses one final fresh whole-branch review; subagent execution additionally reviews each task.
- [ ] **Step 6: Commit accepted release evidence/runbook only.** Exclude private fixtures/ledgers/secrets. Verify staged/committed blobs and clean worktree. Report implementation/tests/review complete separately from production deployment. Stop for production-cutover approval.

### Task 9: Separately approved production replacement

**Files:** Only exact accepted source; production policy stream gets the approved v3 transition. Configuration, operational history and protective orders stay unchanged.

**Interfaces:** Consumes independent acceptance, exact source/rollback pins, current production manifest and explicit cutover approval. Produces source promotion, activation, schedule restoration and scheduled-run evidence as distinct receipts.

- [ ] **Step 1: Prepare release without downtime.** Verify production/remote ancestry, current source/config, actual runtime interpreter/wrappers, fixture readiness and compatible rollback. No force-push/reset. Explicitly scope any approved remote publication and verify exact remote target by readback. Resolve scheduler tools through Hermes skill only when this approved release reaches scheduler operations; no Hermes config edits/restart.
- [ ] **Step 2: Quiesce affected entry/research writers.** Preserve prior settings, pause only approved jobs, drain active workers and verify. Protection/reconciliation remain available. Read broker positions/orders through approved broker-state interfaces only; do not modify orders.
- [ ] **Step 3: Prepare current manifest and request exact approval.** Use recorded source revision/rule version and current complete registered-stream watermarks. Present digest, predecessor, effects and principal risks. Do not apply from generic feature approval. Changes after preparation require a fresh manifest/approval.
- [ ] **Step 4: Promote accepted source and apply exact approved transition.** Preserve all ledgers/configuration. Verify real supported imports and isolation gates before apply. Apply atomically with writer locks; read back exact transition and unchanged prefix hashes from SQLite/JSONL. An error or lost acknowledgement triggers read-only determination of exact effect, never deletion/reset.
- [ ] **Step 5: Restore exact prior job state and verify.** Read back every affected job, source revision and mode. If rollout fails, block new entry and use compatible reviewed source rollback; do not restore historical databases or cancel protection. Report whether activation occurred even if source rollback was necessary.
- [ ] **Step 6: Observe normal scheduled runs.** No extra live trading/research canary. Join ordinary run diagnostics and dossiers to distinguish duplicates/reuse/new qualifications, valid rejections and system failures. Report real elapsed/call-count evidence and untouched/changed order state; no guaranteed yield or return claims.

## Self-review and coverage mapping

Spec sections 1–2: constraints and whole-consumer replacement across Tasks 3–6. Section 3: Radar Task 6. Section 4: keys/store Tasks 1–2 and integrated fallback Task 6. Section 5: routing Task 6. Section 6: history/attempt Tasks 4–5 and workflow Task 8. Section 7: transition Task 3 and approved release Task 9. Section 8: explicit file map. Section 9: focused RED/GREEN plus Task 8 release gates. Section 10: offline comparison Task 7 and distinct deployment/scheduled receipts Task 9. All five Review Focus items have named owning tests. No task grants event authority or production activation by default.

## Execution handoff

Written-spec approval is recorded; this plan still requires review and execution-method selection. Recommend Native execution because Tasks 3–6 share tightly coupled authority/mode interfaces and should be implemented in one coherent session, followed by a fresh independent whole-branch review. Subagent-driven execution is available if per-task implementation/review isolation is preferred. Both methods preserve the same TDD and production approval gates.
