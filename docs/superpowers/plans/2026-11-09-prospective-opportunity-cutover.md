# Prospective opportunity-policy cutover implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline; no subagent development. Steps use checkbox tracking.

**Goal:** Enforce event-level review spending prospectively while preserving all legacy operational obligations.
**Architecture:** Add one atomic policy-v2 activation row containing an approved immutable baseline descriptor. Validate full history for integrity, then derive opportunity allowances only from post-boundary records; never filter operational trading readers.
**Tech Stack:** Python, unittest, existing SQLite/JSONL ledger and entry lock.
**Spec:** `docs/superpowers/specs/2026-11-09-prospective-opportunity-cutover-design.md`.

## Global constraints
- Paper-only; no risk/config/model/cadence changes and no order canary.
- Preserve positions, protection, unknown/pending obligations, daily counts, accounting and original history.
- Explicit manifest digest/apply; no implicit reset or second baseline.
- One activation append contains its baseline, avoiding a separate preparation state or partial activation interval.
- Inline implementation; separate final independent release review only, not subagent development.

## Review focus
- An old worker completes after cutover: reject its stale policy context before persistence.
- A post-boundary hashless/unbound review: fail closed, never classify it as legacy.
- Prefix changes/root moves: refuse baseline rather than silently reset spending.
- Existing incomplete legacy records: validate integrity but do not impose legacy opportunity bans.
- Crash/unsupported rollback: no partial permission; lifecycle/protection must remain available.

### Task 1: Baseline contract and indexed prospective view
**Files:** create `opportunity_cutover.py`, `tests/test_opportunity_cutover.py`; modify `opportunity_activation.py`, `opportunity_state.py`, affected version assertions and `tests/test_manifest.json`.
**Interfaces:** `baseline_for_snapshot(snapshot) -> dict`; `validate_baseline(snapshot, descriptor) -> dict`; `active_baseline(snapshot) -> dict | None`. Descriptor binds root, per-stream count and canonical prefix digest, manual reopening mode and deterministic baseline ID. Policy version 2 supports the atomic descriptor-bearing activation; version 1 remains unchanged.
- [ ] Write synthetic activation/view tests: excluded legacy dissent/gaps, exact prefix/root integrity, double reset refusal, post-boundary missing links, unchanged-event spending/new event allowance.
- [ ] Run guarded focused unittest discovery; observe missing-feature RED.
- [ ] Implement strict contract and two-pass state derivation: full original integrity validation then baseline-scoped event view, retaining original snapshot for exact source refs.
- [ ] Run focused suite and existing activation/state/migration tests; expect all green; commit owned files.

### Task 2: Research admission and administrative activation
**Files:** modify `alpha_radar.py`, `opportunity_state.py`; add admin CLI to `opportunity_cutover.py`; extend `tests/test_opportunity_cutover.py` and Radar regressions.
**Interfaces:** `prepare_manifest(root) -> dict`, `activate_prospective(root, manifest, approved_manifest_sha256=...) -> dict`; candidate `opportunity_baseline_id` is trusted/hash-bound metadata. Activation verifies unchanged full watermark under existing entry lock; rejects previous activation except exact idempotent replay. CLI prepare/validate default read-only; apply explicit.
- [ ] Write RED tests for old cache/reuse/fallback, stale worker contexts, spoofed baseline metadata, atomic apply/readback/idempotence/stale manifest refusal and manual-only mode.
- [ ] Implement trusted metadata binding at intake and final append; reject old candidates at authoritative entry boundary; preserve legacy-floor behavior.
- [ ] Run focused plus fast/scenario suites and commit.

### Task 3: Complete gates and read-only real-history rehearsal
**Files:** docs/test fixtures only as needed; private evidence outside operational root.
**Interfaces:** same manifest/apply API tested on an authenticated disposable copy whose baseline is generated for that copy's root; production descriptor is generated separately.
- [ ] Provision exact pinned compatibility fixture and verified no-install test runtime; record actual source/interpreter identities.
- [ ] Full and raw suites must exit zero, have equal counts and preserve operational bytes/metadata.
- [ ] Rehearse atomic activation on disposable real-history copy, fresh readback, repeat spending, old-candidate exclusion and compatible rollback entry refusal with lifecycle intact.
- [ ] Freeze and obtain one independent release review; remediate important findings RED/GREEN; no subagent implementation.

### Task 4: Controlled paper-production rollout
**Files:** only reviewed source/tests/docs; preserve config and all operational data except exact approved activation append.
- [ ] Save installed Tradey jobs and exact stable settings; pause initially enabled affected writers; verify no in-flight workers.
- [ ] Verify current broker positions/orders through existing read-only transport; do not mutate orders or protection. Generate exact production baseline/manifest and present digest for required exact-state approval before apply if not already supplied.
- [ ] Fast-forward reviewed source; run production full/raw with persisted isolation inventory; rollback source if gates fail before activation.
- [ ] Apply approved manifest via atomic append; read back SQLite/projection, policy version/baseline, unchanged history prefixes/config and operational preservation. Never restore an old DB.
- [ ] Publish only sanitized owned source and verify remote ref; resume exactly paused jobs and read back settings. Distinguish active enforcement from first subsequent successful scheduled scan.

## Execution ruling
The user's latest instruction explicitly requests implementation and production rollout using the already selected inline method. Proceed with implementation without another generic plan-approval round. Exact durable-state approval and independent release gates from the approved spec remain binding; prepare that evidence rather than inventing consent to an unseen digest.
