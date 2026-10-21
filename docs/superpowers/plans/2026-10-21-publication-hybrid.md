# Recovery-first Publication Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (preserved user preference) to implement this plan task-by-task. A fresh reviewer gates each task, followed by a whole-branch review. Steps use checkbox syntax for tracking.

**Goal:** Recover supported publication dates across publishers using precision-aware evidence and one bounded LLM fallback, without formatting-based false rejections or relaxed trading protections.

**Architecture:** Put publication-observation validation/freshness in a pure leaf module, model interpretation and its deadline in a separate application-owned adapter, and run-level selection/cache recovery in one coordinator. Existing extraction, evidence and dossier code carry trusted observations end-to-end; interpretation never approves a trade. Increase only active research and the research wrapper by 120 seconds.

**Tech Stack:** Existing Python stdlib/unittest, project extraction adapters, configured Hermes tool-free CLI, existing no-install dependency environment. No packages or credentials added.

**Spec:** `docs/superpowers/specs/2026-10-21-publication-hybrid-design.md` (approved by the user). Base runtime `adf8fd677d0e0a122d7d09f2c9c622c63aa6a89b`; design-only commit `4cc8624dec305e86c9616a45b76abda47a89cefb`.

## Global Constraints

- Work only in `.worktrees/publication-hybrid`, branch `design/publication-hybrid`, until separately approved rollout. Production main, runtime/config, schedules and operational state remain untouched during implementation/testing.
- Preserve paper-only operation, trading limits, stop/target/earnings protection, two accepted distinct publishers, discovery freshness 7 calendar days, five candidates/25 unique focused URLs/five bindings each, singleton extraction/concurrency three and unchanged discovery/focused limits.
- New active budget 690 seconds; research-only `run_cycle.execute` timeout 720 seconds. Autotrader remains 600 seconds; cadence unchanged. Nominal paired slot margin 180 seconds is not a dispatch guarantee.
- Publication recovery: one batch invocation maximum, 90 seconds cumulative wall time including any scoped refetch, preparation/model/startup/I/O/validation, ten pages maximum, 6,000 content characters per page/60,000 total plus bounded fixed schema. Advisory model run budget 45 seconds, one turn, no tools, existing provider/model.
- Validated day-only dates use UTC calendar-day age in inclusive [-1,180]. Exact timezone-bearing timestamp comparisons remain unchanged. No fabricated timezone/midnight; seven-day event freshness is a separate control.
- No shared Hermes edits, global cache disable, provider pins, dependency installs, new keys, scheduler changes, broker calls, replayed candidates, diagnostic orders or extra model retries.
- Keep existing issuer contracts and legacy receipts compatible. Provider-supplied claims are not trusted merely because they match the new internal observation schema.
- Private experiment/diagnostic directories 0700, files 0600; real model/source evidence private. Commit only code/tests/docs and sanitized fixtures, never private state or raw vendor/error prose in public reason fields.

## Review Focus

1. Valid day recovered but discarded by focused reuse, cache, receipts or reviewer projection: prove the same precision/basis reaches final source verification (Tasks 2/4).
2. Model gives a plausible but unsupported date or other page's quote: verify wrong proposals, mismatched bindings, material conflicts and prompt injection—not just a correct model (Tasks 1/3).
3. Time expires during command preparation, pipe writes, refetch or cleanup: test real supervised children and advancing clocks; preserve downstream reservations (Tasks 3/4).
4. One candidate monopolizes fallback or one malformed row invalidates healthy peers: test stable two-pass allocation and partial member recovery without a retry (Tasks 3/4).
5. Cache replay or a legacy receipt becomes a provenance bypass: bind URL/content/version, preserve checked_at, prevent new schema downgrade while accepting authentic old receipts (Tasks 1/2/4).

## File Map

- Create `publication_observation.py`: pure observation construction, binding/normalization, precision and freshness decisions.
- Create `publication_interpreter.py`: bounded prompt/response, tool-free supervised model invocation, no networking except the model CLI.
- Create `publication_recovery.py`: per-run one-shot state, fair candidate/page selection, scoped cache refresh and interpretation cache.
- Modify `alpha_radar.py`: direct/structured/gateway normalized page handling, cache annotations, filtering, live orchestration, receipts/synthesis canonical source projection and diagnostics.
- Modify `research_extraction.py` only where needed to retain actual standard/header context through its existing normalized projection; do not accept invented provider extensions.
- Modify `autotrader.py` only for source precision/basis reviewer projection; no risk/execution predicate changes.
- Modify `run_cycle.py`: research timeout 720 only.
- Add `tests/test_publication_observation.py`, `tests/test_publication_interpreter.py`, `tests/test_publication_recovery.py`, `tests/test_publication_integration.py`; extend existing focused/cache/source/dossier/budget/pipeline suites and `tests/run_tests.py` if tier registration requires it.
- Add `scripts/probe_publication_recovery.py`: opt-in isolated evaluation command, default offline scoring, no radar/broker entrypoint. Runtime evaluation artifacts remain ignored/private.

## Task 0: Freeze the execution environment and boundary evidence

**Files:** ignored `test_artifacts/publication-hybrid/{baseline,environment,scheduler-boundary}.json` and complete logs; no runtime changes.

- [ ] Verify worktree path, branch, HEAD, clean status and runtime hashes against production (docs-only difference). Capture source/config manifest without opening operational journals.
- [ ] Use existing `.worktrees/focused-coverage-25/test_artifacts/focused-coverage-25/tpy.sh`; remove old diagnostic PYTHONPATH hooks in a child-local environment; set `HERMES_DISABLE_LAZY_INSTALLS=1`, `PYTHONDONTWRITEBYTECODE=1` and the existing `TRADEY_UNPATCHED_ROOT`. Provision required ignored pinned source fixtures with 0700 parents, never production/private data.
- [ ] Run `tpy tests/run_tests.py full` and `tpy -m unittest discover -s tests`; retain complete stdout/stderr/exit codes. Expected clean baseline 1,335 tests, zero failures/errors/skips and operational-isolation success. A failure stops implementation until understood, not a reason to weaken a test.
- [ ] Verify scheduler boundary read-only. Inspected installed source: `cron/scheduler_script.py:_get_script_timeout` resolves module override, `HERMES_CRON_SCRIPT_TIMEOUT`, then `cron.script_timeout_seconds`; declared default 3600. `hermes config get cron.script_timeout_seconds` returned 3600 during planning. Check actual gateway environment/overrides and installed source path before treating 720 as admitted. Do not change shared configuration. If effective timeout is insufficient, stop and ask for the scoped remedy.
- [ ] Record existing run_cycle scheduled-slot predicates: radar :00/:20/:40, matched autotrader :15/:35/:55; premarket 09:00 versus 09:40 consumer. No cron mutation or gateway restart.

## Task 1: Precision-aware publication observations and minimal grounding

**Files:** create `publication_observation.py`, `tests/test_publication_observation.py`.

**Interfaces:**
- `normalize_support(text: str) -> str`: HTML-unescape, Unicode/whitespace/punctuation normalization for citation matching, not semantic rewriting or date invention.
- `build_observation(page: dict, *, value: str, precision: str, basis: str, support: str, location: str) -> dict | None`.
- `validate_observation(page: dict, observation: object) -> bool`.
- `evaluate_publication(page: dict, *, now: datetime, max_age_days: int = 180) -> tuple[bool, str | None]` returns accepted or existing `stale_source`/`source_freshness_unknown` reason.
- Observation v1 required keys: `version`, `value`, `precision` (`day`/`instant`), `basis` (`structured_metadata`/`visible_context`/`llm_grounded`), `url`, `returned_url`, `content_sha256`, `parser_version`, `support`, `location`. Location describes retained metadata/header/body context, never a model authorization flag. All grounding uses actual supplied/retained content. Existing page `publication_precision='second'` maps to observation instant; retain legacy representation externally.

- [ ] Write RED tests `test_day_precision_boundaries` asserting day ages -1/0/179/180 accepted and -2/181 unknown/stale respectively, no timezone manufactured; `test_exact_timestamp_behavior_unchanged`; `test_date_only_without_valid_observation_remains_unknown`; and `test_validated_timezone_less_clock_retains_day`.
- [ ] Add RED `test_binding_quote_and_role_checks`: altered content/URL/hash, another article's quote, unsupported date/year, event-only/update-only/copyright/crawl dates, material conflicting publication dates and injected instructions cannot establish publication. Normalized quoted header with no literal Published, HTML entities/punctuation and publication plus a separate update must pass. A real date embedded in an event sentence is not sufficient. Missing evidence stays unknown.
- [ ] Run `tpy -m unittest discover -s tests -p 'test_publication_observation.py'`; retain RED output.
- [ ] Implement pure leaf functions. Day-only values remain `YYYY-MM-DD`; preserve exact timestamp offsets. Treat a field's shape as a claim, not proof; only project-owned interpretation/metadata adapters construct trusted observations after validation. Never use model confidence as a validator.
- [ ] Run the targeted suite GREEN and `git diff --check`; commit `feat: add grounded precision-aware publication observations` after independent spec/quality review.

## Task 2: Carry supported precision through existing page and dossier boundaries

**Files:** modify `alpha_radar.py` functions `fetch_source`, `validate_structured_page`, `fetch_source_via_gateway`, `filter_evidence`, `build_source_receipts`, `source_verification_result`, `synthesis_prompt`, `synthesize_candidate`; `research_extraction.py:_project` only as required; `autotrader.py:REVIEW_SOURCE_FIELDS`; create `tests/test_publication_integration.py`, extend existing publication/focused/structured/review tests.

**Interfaces:** page key `publication_observation` holds Task 1 internal proof. Retain `published_at`; add/retain `publication_precision` (`day`/`second`) and `publication_basis` in canonical sources/receipts. Model sources are replaced by exact trusted receipt fields, not allowed to author provenance. Existing receipts without new fields retain legacy validation; newly observation-bearing receipts must not silently downgrade when fields are omitted or altered.

- [ ] Write RED integration tests proving day-only supported metadata/header survives direct fetch, normalized extraction, focused reuse and source filtering; timezone-less exact-clock attributes can establish only a supported day, not an instant. Include sanitized Tradeweb-style header and Equifax HTML/text witness, labeled synthetic when constructed.
- [ ] Add RED `test_day_observation_survives_receipt_synthesis_and_review_projection`, `test_source_model_cannot_replace_precision_or_basis`, `test_new_receipt_precision_mismatch_fails`, `test_genuine_legacy_receipt_compatible`, and `test_provider_cannot_inject_internal_observation`. Assert existing two-publisher checks unchanged. Include a date-only path through shared intake using mocked non-network enrichment, not a standalone parser test only.
- [ ] Run the new/extended suites RED. Implement adaptation at the actual ingestion owners before metadata is dropped; retain bounded header context only where needed. Do not modify shared Hermes output schemas or claim absent metadata is available.
- [ ] Route `filter_evidence` through Task 1's policy only for supported observation-bearing pages; keep body/error/navigation/refusal checks and legacy exact timestamp behavior intact. Do not broadly change `valid_publication_timestamp` to accept every bare date, and do not reinterpret SEC event dates as publication. Keep approved legacy SEC/issuer paths compatible.
- [ ] Reconstruct canonical source fields from receipts after synthesis, carry precision/basis into reviewer projection, keep private witness data out of public errors. Run targeted suites GREEN and existing publication/focused/source-verification/reviewer tests. Commit after review `feat: preserve publication precision through evidence and source receipts`.

## Task 3: One supervised tool-free interpretation batch

**Files:** create `publication_interpreter.py`, `tests/test_publication_interpreter.py`; reuse `extraction_contract.strict_json_loads`, existing configured command builder and process supervisor. Modify a supervisor only if a real bounded-I/O test proves a missing guarantee; any shared caller change requires full regression tests and separate review.

**Interfaces:** `interpret_publications(pages: list[dict], *, deadline: float, command_factory: Callable[[], list[str]], runner: Callable, now: datetime) -> tuple[dict[str, dict], list[dict]]`. Returns only Task 1-validated observations keyed by bound URL and sanitized per-member diagnostics. No page mutation, cache writes, source fetches or retries. Command factory must resolve the existing default provider/model with `research_subprocess_command('bot_room', max_turns=1, run_budget=45)`; timeout is live remaining time, never fresh 90 seconds.

- [ ] Write RED batch tests: valid day/instant, unknown, malformed/duplicate envelope keys, duplicate IDs, forged/wrong-page proposal, missing members, mixed valid/bad members, material conflicts, normalization and injection. One invalid member cannot erase independent valid members when the enclosing schema is safe; an invalid enclosing envelope yields no new observations without discarding existing sources.
- [ ] Write RED deadline tests with an advancing monotonic clock during command/prompt preparation. Test expiry before spawn, exit nonzero, timeout, oversized input, bounded output and no hidden second invocation.
- [ ] Exercise the actual supervisor with synthetic local children: child refuses stdin, pipe backpressure, output overflow and hanging child/group cleanup. Require a single absolute deadline covering preparation/I/O/cleanup; do not infer detached-descendant containment from group-kill alone. No model/network calls in these tests.
- [ ] Implement bounded excerpt/prompt and response admission: <=10 pages, <=6,000 content chars each/60,000 total; include a bounded ID and actual page context but no labels. Validate encoded-input bytes against supervisor admission and lower page/excerpt count before launch if necessary. No input/output-cap increases. Preserve raw response only in approved private diagnostic artifacts, never public errors.
- [ ] Run interpreter + observation suites GREEN; prove model has zero tools via command/toolset assertions. Commit after review `feat: add bounded tool-free publication interpreter`.

## Task 4: Fair recovery/cache coordination and the 120-second extension

**Files:** create `publication_recovery.py`, `tests/test_publication_recovery.py`; modify `alpha_radar.py:gather_evidence, live_research, focused reserve/diagnostics`; `run_cycle.py:research execute call`; extend `tests/test_research_budget.py`, `tests/test_pipeline.py`, `tests/test_focused_reuse.py`, `tests/test_publication_integration.py`.

**Interfaces:**
- `RecoveryState` dataclass owns `attempted_model: bool`, `started_at: float | None`, `deadline: float | None`, `refreshed_urls: set[str]`, `observations: dict[str, dict]`. One instance per live_research run, never reset per candidate/rescue pass.
- `choose_recovery_pages(candidates: list[dict], pages: list[dict], accepted: list[dict], *, limit: int = 10) -> list[dict]`: stable one-per-candidate first pass, then second useful distinct-publisher page per candidate; skip complete bundles, already-admissible pages, duplicates and unsupported/error documents.
- `recover_publications(candidates: list[dict], pages: list[dict], accepted: list[dict], *, state: RecoveryState, overall_deadline: float, downstream_reserve: float, cache_path: Path | None, fetcher: Callable, interpreter: Callable) -> tuple[list[dict], list[dict]]`. Copies pages, preserves already accepted sources, emits sanitized typed recovery diagnostics; never qualifies a trade.

- [ ] Write RED fair-allocation/skip tests for five candidates, shared URLs, one candidate with many pages, already-complete two-publisher bundles and deterministic second pass. Assert max ten unique pages and one model batch across initial/deferred rescue opportunities.
- [ ] Write RED cache tests: URL/content/version-bound successful observation replay, changed content miss, tampered proof miss, original checked_at preserved; unknown model outcomes do not become durable negative cache entries. Undated cache entries may receive at most one direct scoped refetch per URL/run inside shared recovery time; no global bypass. Focused pages with useful undated content must be retained for interpretation instead of forcing duplicate extraction merely because pre-interpretation freshness is unknown.
- [ ] Write RED orchestration tests with fake elapsed time/nonzero transitions: active budget 690, research wrapper 720, execution wrapper still 600, scheduler expressions/slots unchanged; recovery <=90 cumulative seconds including preparation/refetch/model/validation and residual downstream reservations. One valid bundle remains usable when a different page/model fails. The extra 30 seconds is headroom, not another retry allowance.
- [ ] Implement a distinct recovery phase between normal evidence normalization/initial filter and expensive alternative-source rescue/synthesis. Keep original evidence-phase cap 180; publication recovery has its own <=90 deadline under the same outer 690 deadline. Retain the evidence phase's unused remainder for existing rescue using an explicit remaining-budget accounting, not an old absolute deadline that expires while recovery runs, and never replenish consumed evidence time. Extend focused downstream reservation by 90 only when fallback may be needed, within existing outer active time; do not let focused retrieval consume the new fallback allocation. Preserve minimum synthesis window/enrichment/headroom when choosing recovery launch timeout.
- [ ] Ensure no second LLM batch on deferred rescue: later pages may use cheap standard parsing or already matching cached observations; unknowns stay eligible for existing alternatives only within remaining time. Deadline/persistence errors retain their honest existing public classification; a model-page abstention is not a whole-run infrastructure error.
- [ ] Add typed private recovery diagnostics and stage timing using existing correlation/privacy patterns. Retain clear separation of fetch failure, parser unknown, recovered day, stale date and model timeout. Existing source/freshness/public gates and source verification remain the final admission owners.
- [ ] Run recovery/integration/budget/focused/cache/pipeline suites GREEN, followed by full/raw suites with operational-isolation success. Commit after review `feat: integrate fair publication recovery with 690-second research budget`.

## Task 5: Independent real-corpus check and whole-branch release gate

**Files:** create `scripts/probe_publication_recovery.py`; sanitized adversarial tests; private ignored `test_artifacts/publication-hybrid-validation/` manifest/captures/labels/results/report. No production ledger or schedule calls.

**Interfaces:** probe supports `score --dataset PATH --results PATH` (offline/default) and explicit `run --dataset PATH --output DIR` using the reviewed interpreter, original caps and existing provider/model. One invocation per evaluation batch, <=90 seconds including startup, no hidden retry. Enforce private modes and refuse overwrite of an existing live invocation record.

- [ ] Write RED offline scoring tests distinguishing real versus synthetic, raw fetch errors versus parsing errors, independent URLs versus representation pairs, recovery versus actual filter acceptance, and deliberately wrong model proposals. Define one fixed as-of clock per labeled cohort; do not refresh old article years to improve scores.
- [ ] Freeze at least 20 new real article URLs not used in the spike, across at least eight publisher domains and three classes (issuer/official, wire, independent reporting). Collect exact representations with retained publication cues before invoking the model, label precision/date/unknown with exact witness/rationale; mark uncertain ground truth unknown. Include day-only/offset/exact timestamp/missing provenance in separate synthetic controls when real cases do not supply them. Fetch failures are separately recorded and not scored as date failures. Do not repeatedly replace hard pages with convenient successes; report actual coverage and any sample shortfall as a blocker to claims.
- [ ] Run default offline validation then one bounded model batch on a max-ten unresolved subset chosen by the reviewed admission logic, without labels. Retain actual stdout/stderr/exit/time/model/usage; no tuning or repeat for a green result. Compare the full applicable baseline, unvalidated proposals, validated hybrid and unchanged/precision-aware evidence decisions. A larger corpus can contain baseline-resolved pages; disclose exact model-evaluated count and untested remainder.
- [ ] Produce programmatically counted correct recovery, missed known dates, wrong accepted dates, unknown falsely accepted, abstention and validator-induced rejection; disclose sample correlation and confidence limits. Any observed unsupported acceptance or needless rejection requires investigation before release, not accepting a favorable aggregate percentage. No claim of zero-error guarantees.
- [ ] Whole-branch independent spec/quality/adversarial review. Full/raw suites must exit zero with complete counts and unchanged operational snapshots; inspect artifact-parent provisioning and existing-database isolation specifically. Verify out-of-scope production/config/bridge/scheduler files unchanged. Commit code/tests only after green; keep private evaluation evidence outside publication.
- [ ] Present exact implementation SHA, review verdicts, real evaluation results, test counts, added wall time and explicit paper rollout scope for user integration approval. This plan does not itself authorize a production cutover.

## Task 6: Controlled paper rollout after integration approval

**Files:** private release manifests/reports only; no unrelated code edits.

- [ ] Freeze exact reviewed SHA/dependency invocation and existing credential availability. Record affected jobs' stable configuration, initially enabled states, wrappers/config hashes and production operational before-state outside protected paths.
- [ ] Pause initially enabled affected producers/execution/writers, preserve protection where safe, read back pause states and verify no in-flight processes/writers. Recheck effective scheduler timeout >= full 720 envelope and actual schedule pairing. No broker/order canary.
- [ ] Fast-forward only reviewed source/docs; production full/raw verification through the same no-install runtime, persisted before/after snapshots and full exit codes. Failure means release-owned source rollback, never operational journal restoration; preserve evidence and restore schedules before investigation.
- [ ] Publish to GitHub using existing ephemeral authentication, read back exact remote SHA; restore exact saved schedules/settings and read every target back. No global Hermes change or gateway restart.
- [ ] Archive verified private evidence before cleaning the owned worktree. Report deployment, publication, schedule restoration and first observed successful scheduled market-hours run separately; do not call a parser-only or after-hours check end-to-end qualification proof.

## Plan Self-review

Coverage: all approved spec sections map to Tasks 0-6; day precision policy Task 1, metadata/provenance carriage Task 2, bounded interpretation Task 3, cache/fairness/budgets Task 4, larger disjoint evaluation Task 5, deployment/rollback Task 6. Five Review Focus conditions have explicit tests in their owning tasks. Source callers were inspected directly; the historical graph is not treated as an up-to-date runtime call graph (graphify CLI unavailable; no install). Exact interfaces use built-in types/defined RecoveryState; existing source fields remain compatible. No implementation, new model invocation, full-suite execution, runtime budget change or deployment is claimed by this planning commit.
