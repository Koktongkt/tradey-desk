# Acquisition Research-Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the preserved native execution method. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retain useful private acquisition observations while giving them no event, paid-review or entry authority, then deploy only the accepted replacement.

**Architecture:** Start from deployed Stage 1 plus the approved replacement document, not the rejected automatic-admission branch. One small research module owns lead recognition, closed records and private retention; the existing Radar transport supplies complete captures under its existing budget. Shared policy and saved-candidate boundaries explicitly refuse research-lead/unsupported acquisition inputs even on inactive-policy roots.

**Tech Stack:** Existing Python standard-library code, unittest, trusted SEC capture transport, content-addressed private evidence helpers; no dependency, provider, configuration or database-schema change.

**Spec:** `docs/superpowers/specs/2026-11-11-stage2-acquisition-research-only-design.md`, SHA-256 `435f05f35f13ace8ab0cbe95efcaf667b07a6f17a8f2f8755d8c315cc6794224`, approved by the owner's “Approve and proceed”.

## Global Constraints

- Base `0bdf9572653fa98469c3f7aa294601b9676dd4e9`; current isolated docs commit `b63c55e8c6cf2c656c8fa2e4d9804f60386e5339`.
- Preserve the rejected branch, eight dirty repairs, failed reviews and frozen evidence. Do not merge its runtime or rewrite shared remote history.
- This release has no acquisition identity version, admission seal, binding importer, allowance grant or activation. Explicit-binding authority is a later separately specified release.
- Preserve `autonomy_config.json` byte-for-byte, old earnings v1/v2 wire/event keys, policy memory/spending/manual reopening and all paper/execution/protection gates.
- Reuse the current acquisition queue/cache/deadline: at most 32 queued locators, existing per-fetch ceiling, `MAX_IDENTITY_SOURCE_BYTES = 2_000_000`, `MAX_IDENTITY_CAPTURE_BYTES = 3_000_000`. Do not introduce a second family fetch or reset elapsed time.
- Closed observation schema is exactly the approved spec's ten fields. Never persist lead records to canonical policy/candidate/review/order streams.
- No production state/config/schedule changes during implementation or review. No Hermes modifications/restart, dependency installation or order canary during release.
- Native implementation is one dependency-complete package with one final frozen SPEC/QUALITY acceptance pair, not a review cycle per helper.

## Review Focus

1. Inactive-policy compatibility must not let a research-lead candidate bypass final refusal; test both inactive and real prepare/activate roots.
2. Unranked/source-unavailable leads must remain observable rather than vanishing before the ranked-candidate loop; test no-primary and failed-primary discovery.
3. A model-supplied earnings label must not turn a recognized acquisition bundle into an earnings permission; test relabeling, mixed evidence and an independent earnings positive.
4. Capture or metadata persistence failure must never fall through to synthesis/review or claim retained success; test both failure points with unchanged authority streams.
5. New inert observations must not break rollback or old earnings/protection paths; test old-reader disregard, incompatible-identity refusal and a meaningful protective-exit fixture.

---

### Task 1: Complete acquisition observation and authority-refusal package

**Files:**
- Create `acquisition_research.py` and `tests/test_acquisition_research.py`.
- Modify `earnings_identity_acquisition.py:98–126` to add research-only literal-link traversal inside the existing queue.
- Modify `alpha_radar.py` around `_strip_policy_metadata`, `_final_policy_check`, `prepare_candidate`, `live_research` admission/ranking and the pre-synthesis identity handoff.
- Modify `opportunity_state.py` at `candidate_policy`, `event_decision` and `require_current_allowance`; preserve ordinary earnings/legacy behavior.
- Modify `autotrader.py` at saved-candidate acceptance (`research_acceptable`) and its shared policy boundary only as needed to reject lead markers before reviewer calls.
- Modify `tests/test_manifest.json`; extend `tests/test_opportunity_radar.py` and `tests/test_opportunity_execution.py` only where those existing fixture contracts own the boundary.
- Selectively extend `earnings_identity_evidence.py` only if a safe retained-capture reader is necessary for exact readback; retain/publish using existing no-follow private evidence primitives, not the rejected legal classifier.
- Exact new regression-fixture plumbing may modify `tests/test_broker_bridge.py`, `tests/test_safety.py`, `tests/test_research_budget.py`, `tests/test_enrichment_diagnostics.py`, `enrichment_diagnostics.py` and Radar timing append only if the already-demonstrated baseline privacy/isolation failures recur. Preserve assertions, reproduce unchanged baseline, make the smallest shared fix, and disclose it in the final diff.

**Interfaces:**
- `acquisition_research.acquisition_hint(selected: dict, pages: list[dict], captures: tuple) -> bool`: conservative investigation routing only. Inspect bounded discovery catalyst/type hints and relevant primary event/item/exhibit descriptions. Labels/prose establish no original/continuation/party fact. Do not classify ordinary earnings as acquisition merely because a financial statement mentions acquisition expenses; no new model call.
- `acquisition_research.literal_acquisition_links(raw: bytes, base_url: str) -> tuple[str, ...]`: bounded literal same-issuer SEC report/exhibit links associated with acquisition/merger/closing descriptions. No guessed locators, continuity inference or automatic event identity. The current queue remains the sole request/capture owner.
- `acquisition_research.publish_lead(root: Path, *, symbol: str, captures: tuple, evidence_status: str, observed_at: str) -> dict`: strict closed lead envelope. Authenticate capture objects, durably retain complete captures first, then publish an owner-private no-clobber record under `private/acquisition_research/`.
- `acquisition_research.read_lead(root: Path, lead_id: str) -> dict`: bounded private no-follow readback with exact record digest/schema and verified referenced captures; returns observation data, never an identity or policy decision.
- `acquisition_research.is_research_only_input(value: object) -> bool`: identify lead envelopes/markers and explicitly unsupported acquisition-family/version fields without stripping them into a legacy candidate. Shared callers reject such input before any legacy-floor permission or model-paid boundary.
- Store a lead as `<digest>.json`; `lead_id = al1:<digest>` where digest covers the complete canonical closed envelope excluding `lead_id`, including the trusted observation timestamp. Same observation bytes replay idempotently; fresh observations may differ. This is not an agreement key. `issuer_cik` is authenticated from supported primary cover facts or null, never filled from the hint alone. `capture_refs` are unique sorted verified references, at most 32. `retained` means the attempted admitted primary transport set is retained, not that transaction facts are complete; `partial` means usable captures plus unresolved attempted/discovered primary sources; `unavailable` means no usable capture.
- Radar keeps its existing public success/none/failure schema and sanitized tokens. A persisted acquisition-only observation produces no eligible candidate and uses the existing normalized no-eligible-opportunity outcome; private lead reason stays `explicit_binding_required`. Persistence errors map to `research_persistence_failure`.

- [ ] **Step 1: Verify isolated origin and fixture baseline.** Check path/branch/HEAD; admit the existing source-only pinned fixtures needed by Stage 1 tests, plus the authentic acquisition original/exhibit/closing/letter corpus from preserved evidence. Hash and copy only immutable fixture inputs into ignored `test_artifacts/`; never operational state or the rejected runtime. Run the tight unchanged policy/evidence/Radar baseline with pre-import offline and production-path guards. Record actual exits/skips. No dependency setup/install is needed.

- [ ] **Step 2: Write storage/transport behavioral REDs.** Tests assert closed ten-field records, no authority fields, complete authentic capture equality/readback, private modes, repeated same-record replay, strict invalid/unhashable schema refusal, and partial/unavailable outcomes. Exercise symlink/ancestor/hardlink/permissive-mode/tampered-record/tampered-capture/oversize/missing-reference cases. Transport tests assert exact attempted literal URLs and one shared deadline/queue/cache; no transport for forged model capture dictionaries. Run `python -B <guarded-runner> <unique-red-label> test_acquisition_research` and retain the expected failures, not loader/fixture errors.

- [ ] **Step 3: Implement observation module and literal-link integration.** Preserve capture limits and existing exact-URL transport. No class/function may return a verified acquisition `EventResolution` or admission seal. Publish verified capture bytes before the closed observation file; read back exact bytes. Failure after capture persistence may leave inert evidence but must not claim a published lead or mutate policy. Do not build a new general storage framework.

- [ ] **Step 4: Write complete-consumer behavioral REDs.** For authentic original/closing and representative compound/nominal predecessor, competing-role and conditional-boilerplate variants, assert useful research-only retention regardless of legal semantics. Exercise real `live_research` before synthesis, including no-ranked/failed-source leads and both policy-context-present/absent cases. Assert synthesis, enrichment for investment qualification, paid review and broker mutation are not invoked; authoritative stream bytes and assignments remain identical. Run direct `candidate_policy`, `event_decision`, saved-candidate acceptance, `_final_policy_check` and `require_current_allowance` with lead objects, acquisition EventResolution-like inputs, forged v3 wire identities, planted shape-valid rows, model approval fields and false earnings labels. Test inactive and real synthetic activated roots, malformed future versions, and a normal independent earnings positive. Preserve existing typed error/result contracts rather than inventing permissive fallback.

- [ ] **Step 5: Implement one non-admitting route and shared refusals.** Route recognized acquisitions before generic metadata stripping/normalization and before all normal synthesis paths, not only inside the active-policy loop. Reuse captures already obtained; unavailable/unranked lead handling consumes only the original unspent evidence allowance. Ambiguous mixed acquisition/earnings setups stay research-only; a separate strictly supported earnings setup retains the original route. Policy/event/final and saved-candidate gates refuse lead/acquisition fields before legacy-floor eligibility. Do not widen `opportunity_identity._load_binding` to v3 or add acquisition identity rows. A manually inserted acquisition row remains unsupported, never a permission.

- [ ] **Step 6: Run GREEN and shared compatibility tests.** Run new tests plus affected identity/evidence/transport/state/admin/workflow/Radar/execution/reuse/pending/protection/reconciliation modules through the proven guarded invocation. Test observation-versus-event distinction, no source-budget restart, missing persistence, and each Review Focus condition. Preserve actual partial writes as inert artifacts; do not clean state to make assertions pass. Freeze only after the complete affected matrix passes.

- [ ] **Step 7: Rehearse source rollback on owned synthetic roots.** Leave inert observations present; run the deployed predecessor's earnings/protection behavior without importing them into policy. Prove replacement and rollback refuse unsupported acquisition candidates before entry, and execute a meaningful confirmed protective-exit accounting fixture. If predecessor refusal is not safe for an input shape, prepare a reviewed compatible rollback variant that explicitly denies it; never assume an old permissive reader is compatible. No production root copy or DB restore.

- [ ] **Step 8: Final proof and independent acceptance.** Freeze the exact base-to-candidate diff, runtime/tests/drivers/fixtures, actual argv, source origins, named skips, guard counters and rollback hashes. Run canonical `tests/run_tests.py full -v` and raw `python -m unittest discover -s tests -p 'test_*.py' -v` with the accepted suite interpreter, offline/production guards and explicit pinned fixture environments. Use tracked background execution for long tests and retain unique stdout/stderr/exit receipts. Obtain separate fresh SPEC/QUALITY verdicts on identical frozen bytes; independently verify all receipts and both definitive PASS verdicts. Do not relaunch legal-prose grammar repair loops: no admission classifier exists in this package.

- [ ] **Step 9: Commit only accepted bytes.** Compare staged paths/blobs to the frozen manifest, check staged diff, commit a conventional feature message, verify every committed blob, and record parent-owned acceptance binding the commit, real reviewer dispatch IDs and final proof. No failed branch merge or premature main publication.

### Task 2: Deploy the accepted research-only replacement

**Files:** Application-owned reviewed paths from Task 1 only. Release evidence lives outside production. Preserve `autonomy_config.json`, private journals, public operational outputs and secrets.

**Interfaces:** Consumes the exact accepted commit, matching independent verdicts, full/raw proof, source/fixture manifest and compatible rollback from Task 1. Produces separate verified source-deployment, remote-publication, schedule-restoration and first-scheduled-execution outcomes.

- [ ] **Step 1: Preflight release authority and ancestry.** Read current production HEAD/status and remote main. The remote already contains unaccepted `3840d60`, while production is still `0bdf957`; do not reset/force-push shared history or fast-forward production through rejected runtime. Prepare a forward-only reviewed reconciliation commit whose final runtime/test tree equals the accepted replacement, retaining prior history. Verify that reconciled exact bytes still match acceptance before publishing or promoting. Preserve a recovery ref and the compatible rollback source.
- [ ] **Step 2: Verify actual invocation and fixture readiness before downtime.** Resolve current cron workdirs/wrappers and Python. Test replacement runtime imports under cron Python, separately from the suite interpreter. Inventory immutable fixture inputs required in the live ignored area; verify hashes and absence of operational data. Check current publication authentication without printing credentials or changing helpers/remotes.
- [ ] **Step 3: Quiesce only affected application writers.** Save exact job settings/enabled states, pause affected research/entry/ledger/publication writers using supported job tools, read back every pause, and verify no relevant same-UID worker is in flight. Preserve unrelated monitoring where safe; do not restart Hermes.
- [ ] **Step 4: Persist pre-cutover operational byte/metadata inventory and promote reviewed source.** Do not overwrite unrelated dirty edits. Fast-forward or atomically promote only the exact reviewed tree according to the verified ancestry; config must remain identical. Never restore a broker database or erase policy history.
- [ ] **Step 5: Verify live tree before resuming.** Compare every deployed source hash with the accepted manifest. Run full/raw suites in the live tree under the accepted interpreter with the same immutable fixtures and offline controls; compare complete terminal statuses, counts/skips and persisted operational before/after bytes/metadata. Separately check cron-runtime imports. Any isolation or compatibility failure blocks restoration of entry until reviewed rollback succeeds.
- [ ] **Step 6: Publish/read back and restore schedules.** Publish only the reviewed forward-only source reconciliation when ready; independently compare remote main and intended commit. Resume only jobs paused for this cutover, read back stable settings and report first actual scheduled execution separately from resume. If a necessary final live operation still requires an exact state manifest approval, stop only for that operation; this release supplies no acquisition authority/state migration.

## Self-review and execution handoff

Each spec requirement maps to Task 1's storage/routing/refusal/compatibility proof or Task 2's release checks; the five Review Focus inputs have explicit Task 1 regressions. Observation IDs never serve as event authority. The later binding producer is explicitly absent, not a placeholder dependency. No broad code-generation framework, new parser grammar or guessed trust source is required.

Execution method remains native under `superpowers:executing-plans`; distinct final SPEC/QUALITY reviewers and production release verification remain mandatory. This plan is presented for the owner's review before product implementation. Existing conditional deployment authority applies after acceptance; it does not waive this written-plan review.
