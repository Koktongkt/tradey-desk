# Task 6 implementation report

Base: `f253ee1` on `feat/position-watchdog`, isolated position-watchdog worktree.
Scope: thesis monitoring contracts/config only. No activation or independent-review claim.

## Delivered

- `watchdog/thesis.py`: supplied versioned baselines, strict evidence classification, bounded owned-symbol orchestration and actual killable JSON worker transport.
- `tests/test_watchdog_thesis.py`: 27 offline tests, including real sleeping-worker deadline tests.
- `watchdog_config.json`: monitoring-only approved budget values; no trading enablement, broker mode or schedule changes.
- `tests/test_manifest.json`: thesis tests registered in fast.
- This report. No prior reports/progress files changed.

## RED/GREEN evidence

All commands ran in this worktree with `PYTHONPATH=.:tests uv run --with 'fastmcp<4' python ...`.

| Slice / regression | Observed RED before implementation/fix | GREEN |
|---|---|---|
| Supplied baseline | Initial missing import error; revised existence assertion then 1 intentional failure, `thesis module missing` | 1 test passed |
| Strict classifier | `ClassificationTests.test_verified_breaker_is_review_not_execution`: 1 failure, `classification missing` | 5 focused tests passed |
| Bounded orchestration | `MonitorTests.test_completed_coverage_has_compact_events_and_advances_cutoffs`: 1 failure, `bounded monitor missing` | Initial 13-test run exposed priority regression; corrected oldest-successful-cutoff ordering, then all 13 passed |
| Monitoring config | `ConfigTests`: 1 failure, `monitoring configuration missing` | Included in final focused run |
| Malformed legacy criteria/version | 1 test: 3 assertion failures and 1 genuine None-list runtime error | Baseline tests subsequently passed |
| Unapproved enrichment separation | `BaselineTests.test_proposals_are_separate_unapproved_never_activated`: 1 failure, proposals absent | Separate proposal versions retained, always unapproved; active criteria unchanged |
| Old initial publication / unknown event kind | 1 test, 2 failing subtests (incorrect potential-break/review instead of gap) | Both fail closed in final run |
| Duplicate JSON object keys | 1 failure, duplicate root accepted | Strict JSON parser rejects duplicates/nonfinite constants |
| Timestamp after phase start | 1 failure, valid response marked incomplete | Receipt-time validation uses trusted phase timestamp plus elapsed monotonic time |
| Lineage baseline provenance | 1 failure, version None instead of exact dossier identity | Exact position candidate/dossier provenance restored in fallback |
| Literal event identity | 1 failure, payload silently truncated fingerprint | Identifiers preserved exactly; only fact prose clipped |
| Existing candidate catalyst shape | 1 failure, string catalyst plus supplied event_date incorrectly incomplete | Supports existing candidate string/date and structured catalyst shape |

Core feature slices had tests written before their production behavior; additional boundary tests verify established guards. No claim that every additional verification test individually had an initial RED run.

Final sequential verification (no concurrent SQLite suites):

- `python -m unittest test_watchdog_thesis -v`: **27 passed**, 2.100s.
- `python tests/run_tests.py fast`: **407 passed**, 25 modules, 7.800s; zero failures/errors/skips.
- `python tests/run_tests.py full`: **687 passed**, 36 modules, 15.184s; zero failures/errors/skips.
- `git diff --check`: clean.
- Runner operational isolation audit passed. Default scratch TMPDIR retained; no test_artifacts-as-temp override and no SQLite collision occurred.
- Existing tests emit fixture `BLOCKER` / `SYSTEM_FAILURE alpha_radar` messages; these are expected test output, not live source calls or watchdog intake.

## Interfaces and trusted/untrusted boundaries

Public signatures match the brief:

- `baseline_from_candidate(candidate: dict) -> dict`
- `monitor_theses(positions: list[dict], baselines: dict, source_state: dict, adapters: dict, deadline: float) -> list[dict]`
- `classify_events(baseline: dict, receipts: list[dict], run_model) -> dict`

Baseline contract: `version`, compact candidate/dossier `provenance`, `summary`, dated `catalyst`, `assumptions`, `breakers`, `kpis`, `risks`, `status`, separate `proposed_enrichments`. Criteria must supply `id`, `metric`, comparison `operator` and finite numeric `threshold`. Unique active IDs required. Supplied `baseline_version` is preserved; without one, an existing dossier/candidate identity is a provenance reference, not an invented criteria revision. Missing criteria/date/version remains baseline_incomplete. Enrichments retain supplied proposal versions separately and are forcibly unapproved; no enrichment generator exists.

`baselines` is keyed by exact **position_id**, never ticker. Verified owned positive remaining quantities only; repeated symbols share a source sweep and one classification batch but retain distinct position/version mappings. Lineage fallback uses the position's exact candidate/dossier provenance. Mechanical code is untouched and independent. Existing lineage projects string catalysts without event_date: Task8 should construct baselines from the exactly linked candidate when the original event_date is needed, rather than infer a date or alter Task3 here.

Adapter/schema details are in `JSONCommand`, `monitor_theses`, `MODEL_POLICY`, `MODEL_SCHEMA` docstrings/constants:

- `adapters`: exact `JSONCommand` instances for `discover`, `retrieve`, `classify`, plus trusted thesis-phase-start ISO `now`. Arbitrary runtime callbacks/subclasses are rejected. No live defaults.
- Discovery returns deterministic per-source `status`, `checked_through`, `coverage_url`, URL list. Complete empty results require actual successfully inspected dated listing/API coverage. A URL alone is not a model-authored coverage proof; concrete workers own deterministic verification.
- Retrieval returns a compact receipt: underlying event `fingerprint`, source/URL/fact/kind, deterministic primary/date_verified booleans, publication/event/retrieval ISO timestamps and numeric metrics. SEC accession/issuer-event/period identity must be normalized across reports by the concrete worker, not URL-hashed. The monitor combines URLs for matching identities and rejects conflicting event facts/metrics.
- Classification batch returns one strict `{events:[...]}` result per requested baseline. Each event permits only fingerprint, supplied criterion_id, enum effect/severity/confidence. Extra status, coverage, primary, baseline, order or action keys are rejected. Every retained event is mapped to a supplied active criterion.
- Facts are clipped to 1,000 characters. Document bodies, transcripts, prompts, unrelated candidate fields and raw stderr are excluded. Trusted dates/URLs/primary/baseline versions are copied from verified inputs, not model output.
- Potential break requires a mapped original breaker, primary verified dated fundamental receipt, and deterministic numeric threshold comparison. Price kind/price metrics alone cannot produce a break. Actions are only record/reassess, never execution.

## Budget and cutoff ownership

This module enforces a monotonic shared phase deadline clipped to 600 seconds; at most 20 distinct owned names; each name 60 seconds; discovery 15 seconds; each of at most three substantive URLs 15 seconds; one per-symbol classification batch 20 seconds. Every call is clipped to shared/name remaining time. Retrieval is deliberately sequential, so no parallel-worker oversubscription. Partial/truncated source lists cannot silently advance their source cutoff. No guarantee of complete 20-name coverage within the phase cap.

`JSONCommand.run` exercises an actual runtime boundary: sanitized explicit environment, fresh scratch HOME/cwd, no shell, closed inherited file descriptors, separate process group, nonblocking bounded stdin/stdout, absolute wall deadline through worker I/O and process exit, SIGKILL of the worker group on timeout and cleanup. Input/output byte caps are 65,536/131,072. Sleeping workers were actually killed; tests verify subsecond clipped timeout and no inherited APCA/PYTHONPATH environment. This is not merely a socket timeout or placeholder adapter timer.

Cutoff input/output is `source_state[symbol][source].cutoff`; critical_unresolved is trusted prior monitoring state. Fetch since cutoff minus 48 hours (or phase start minus 48 hours for initial documented scope). Successful documented sources may advance independently; failed source retrieval, invalid timestamps or truncated source lists preserve that source's prior cutoff. Classification/run failure keeps cutoffs retryable. Observations preserve both baseline status and separate coverage_status; no-material-change refers only to documented coverage, not thesis correctness.

Config records mechanical hard 120; daily hard 900, active 840, report/persistence reserve 60; reads/accounting active 120; cumulative thesis active 600. **Task8 owns actual outer mechanical/daily hard wall termination, the read/accounting cap and report/persistence reserve.** This module cannot enforce an outer run it does not own.

## Reuse inspection and self-review

Inspected existing `alpha_radar.source_profile`, configured-default-model loader/commands, and earnings helpers. source_profile itself is pure registry ranking, but no alpha_radar import/reuse was needed; never invoked its intake/live_research. The config loader invokes a subprocess and is not a pure helper. Existing SEC earnings history cache writes files; default earnings resolution can reach that cache. These helpers were deliberately not reused in this monitoring lane. StockAnalysis/Nasdaq parsers offer possible deterministic Task8 worker implementations, but their actual network I/O must be placed inside this killable boundary; their socket timeout alone is insufficient.

Self-review checked scope, imports, side effects, strict schema, literal identity preservation, false all-clear handling, budgets and exact baseline joins. AST inspection found only stdlib/types imports, no shell=True, no broker/intake/reconciliation dependencies and no operational write calls. Worker scratch creation and pipe writes are the only deliberate local transport side effects. No real credentials were read, inherited or committed. No independent review claimed; parent owns that review.

## Remaining runtime obligations / rulings

1. Task8 must supply **real**, reviewed read-only discovery/retrieval workers and tool-free provider API classification using the existing research provider/model identity. Do not use an empty Hermes toolset (defaults), alpha_radar intake, arbitrary operational readers or memory-enabled Hermes CLI. Provider/model configuration resolution itself must fit the outer hard deadline.
2. Classify must be a direct single-turn provider API request with tools=[] and no tool dispatch loop, broker MCP, private memory, conversation/prompt history or operational persistence. MODEL_POLICY is the input contract, not proof that a provider worker enforces it. Existing provider auth needs an explicitly provider-only credential gateway; subprocesses inherit no credentials.
3. JSONCommand is **process isolation, not a filesystem/network sandbox**. The trusted executable must not independently read host secrets/config/memory or write operational files. Task8 must verify this at concrete worker/API invocation and enforce source SSRF/redirect/domain rules. No claim of complete runtime isolation or release readiness is made by a transport-only test.
4. Task8 must use deterministic issuer/SEC dates, verified primary provenance and trusted next-earnings endpoints, with previous reports distinct from upcoming events. General news can discover events but cannot establish primary provenance via a model label.
5. Task7 owns monitoring-only transactional persistence of returned observations/cutoffs/proposals, sanitization and report delivery. These functions perform no operational or monitoring database writes.
6. No live source/broker smoke, push, schedules, trading config/secret edits, subagents, progress edits or prior-report edits occurred. Release/activation remains blocked pending concrete Task8 wiring, real isolated smoke and independent parent review.
