# Structured Extraction Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace only exact-URL model-mediated extraction fallback with a structured no-model worker and sanitized private attempt diagnostics.

**Architecture:** Keep discovery, focused retrieval, direct HTTP fetching, rescue searches, source gates and execution unchanged. A project-owned isolated subprocess uses the installed Hermes bootstrap and configured extraction-tool dispatcher, preserving provider selection and existing rescue paths. The parent validates a bounded structured success/error envelope, exact request binding, safe same-publisher redirects and publication provenance; existing evidence filters remain authoritative. Worker has no agent or broker invocation. Preserve the existing 30-second fallback allocation, clamped to the shared deadline.

**Tech Stack:** Python stdlib parent/supervisor and worker entrypoint; installed Hermes extraction tool/provider runtime; unittest.

**Spec:** User-approved step-4 replacement in this chat: same source reach and configured provider/rescue routing, unknown publishers eligible, no new whitelist, no evidence/trading gate relaxation, precise diagnostics.

## Global Constraints

- No model/provider config changes, new keys/MCPs, schedule cadence changes, order operations, broker calls or production research probes.
- No changes to enabled/broker_mode in autonomy configuration.
- Existing source body, date, future/stale, URL safety/redirect, independent registered-domain, cache and deadline rules remain.
- Tests and live-probe outputs use scratch/test_artifacts, never production ledgers.
- Premarket/radar/autotrader were enabled; temporarily pause those three only and restore after verified release. Other jobs remain unchanged.
- Commit explicit source/test/docs paths only; full suite green and independent adversarial PASS before commit/push; verify remote SHA before resume.

## Review Focus

- Configured extraction route and existing keyless rescue survive; no hardcoded Firecrawl-only path.
- Cross-publisher/private redirects or mismatched URLs cannot be rebound into valid evidence.
- Error prose, malformed envelopes and nonzero exits never become pages or manufactured dates.
- Timeout/startup/output/cleanup are bounded; no model handoff or owned process leak.
- Diagnostic persistence/privacy and legacy public failure semantics do not alter evidence outcomes.

### Task 1: Structured extraction contract, worker and parent integration

**Files:** Create focused worker/adapter modules and tests; modify `alpha_radar.py` exact-URL fallback only; add test file to manifest if required.

**Interfaces:** Retain `fetch_source_via_gateway(url, timeout_seconds=30, strict_provider=False)` legacy page-or-None/strict-error behavior. Add optional internal diagnostic handling without breaking injected legacy test fetchers. Worker consumes exact URL and bounded request; emits one versioned JSON success/error envelope with bounded page content and typed reason. Keep secrets/raw errors out of output and diagnostic persistence.

- [ ] Write behavioral tests for structured content success without a model, configured dispatcher/rescue use, malformed/error prose rejection, missing date, same-publisher redirects and cross-publisher/private rejection.
- [ ] Run new tests and record expected RED before production edits.
- [ ] Implement minimal worker/bootstrap, structured normalization and bounded process invocation using existing runtime conventions.
- [ ] Integrate fallback and sanitized two-dimensional direct/fallback attempt diagnostics; retain existing research source diagnostics and public failure behavior.
- [ ] Add/run tests for failures, shared deadlines, stderr/stdout bounds, cleanup, concurrent diagnostics and privacy; RED first per new behavior.
- [ ] Run focused suite and full project suite, preserving existing coverage rather than deleting assertions to hide regressions.

### Task 2: Real verification and release

**Files:** Add concise operator docs and reusable isolated probe if useful; no real article bodies/URLs or credentials published in reports.

- [ ] Exercise installed bootstrap/provider availability and the exact new fallback on representative real failed-source URLs plus successful control, with writes isolated. Record real returned status/date/body counts/duration; no claim of universal reach.
- [ ] Freeze diff; independent adversarial review of implementation/security/deadline/routing/tests. RED-test and fix findings then re-review until PASS.
- [ ] Run final full suite, `git diff --check`, private-data/explicit staging inspection and verify production ledger/config unchanged by probes.
- [ ] Commit reviewed paths, inspect commit, push, compare `git ls-remote origin refs/heads/main` to local SHA.
- [ ] Restore exactly prior three enabled cron states; read back scripts/workdirs/schedules/targets/state and report deployment separate from first scheduled recovery.
