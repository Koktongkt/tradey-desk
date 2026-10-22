# Discovery quality first: offline evaluation and review package

Status: implemented opt-in on the isolated design/discovery-quality-first branch; no production configuration/cron or research activation changed. This is not a claim of improved market coverage or live qualification reliability.

## What is implemented

- A bounded, six-concurrent-lane code-owned search worker using the existing configured search dispatcher, with typed lane errors and provider receipts.
- One tool-free selector, source-ID/quote binding, provisional event-state labels, explicit per-row exclusions/rejections and a bounded64KiB model projection.
- Safe private cross-scan observed-story context (not a ticker blacklist or qualified-dossier reuse rule).
- An opt-in `discovery_v2_enabled` branch in existing research. Default legacy behavior and all evidence, qualification and execution gates are unchanged.
- A reproducible offline historical replay and whole-funnel synthetic fixture runner. No `--live` mode exists.

The LLM body/publication fallback remains the follow-up increment in spec section3F; it is not implemented here. Existing flattened-publication/context and corroboration limitations remain potential end-to-end blockers.

## Actual historical replay

Private source inventory: `test_artifacts/six-lane-historical-audit-20261022T005728Z/`. Hash-bound labels: `test_artifacts/discovery-quality-first/frozen-labels.json`. Every six-lane session ID and returned record is accounted for:

-37 sessions:34 production/three diagnostics;225 searches/2250 records.
-57 original provisional candidate instances;46 historically admitted.
-40 survive the new structural handoff under each historical cohort's original event floor:40 admitted, nine overlength rejections, five index/newsroom refusals, one future-event-date refusal and two retained historical partial-scout failures.
-All57 have an explicit disposition; silent losses=0. The nine overlength catalysts remain rejected, not recovered. A later concise selector may reduce these, but that model behavior has not been tested.
-The separate retrospective current-seven-day diagnostic admits25; it is NOT a like-for-like improvement claim or a reason to rewrite historical qualification outcomes.
-Ten known event-state mismatch cases remain review labels. Their original catalyst claims are replayed as unverified; substring support validation does NOT repair semantic mistakes or establish actual new-selector accuracy.

This replay adapts the OLD selector outputs into the new protocol solely to test structural admission. It never generates a new model selection and cannot prove new queries would find different historical articles. Live coverage, actual selector accuracy and new real final-qualified candidates remain UNEXERCISED/unknown.

## Actual whole-funnel fixtures

The disposable evaluator invokes the real `alpha_radar.live_research`, real intake/preflight/qualification, real publisher/receipt verification and an isolated spending-ledger path. Only external search/extraction/model/market responses are mocked. Network/process audit guards reject unexpected external operations, and operational paths outside the evaluator output are blocked.

1. Supported two-publisher fixture reaches a qualified dossier, has two accepted domains and verifies immutable source receipts. The dossier is a private `qualified-fixture.json`, not a market recommendation or an operational candidate.
2. Near-term earnings fixture returns a real policy blocker rather than system failure or executable candidate.
3. Missing-second-publisher fixture remains an evidence failure and never qualifies.

Proof: `test_artifacts/discovery-quality-first/evaluation-reviewed/summary.json`, `session-replay.jsonl`, and `integration/*/test_artifacts/`. Evaluator exited0; no model/provider/broker/research network calls were made. This demonstrates interface correctness, not a higher live qualification rate.

## Reproduction

Use the existing no-install dependency setup. Prepend the existing Tradey bridge dependency site ahead of PM packages for tests: FastMCP3.4.9 expects its matching MCP SDK, whereas the current Hermes PM environment has a newer incompatible MCP API. This is test-environment ordering, not a new installation, source patch or production provider change. Original failed baseline logs are retained.

Install `tests/offline_test_guard.py` before any test imports. Private helpers and logs are under `test_artifacts/discovery-quality-first/`; immutable prior publication corpus, retained incident captures, pinned baseline sources and the native-MCP replay fixture are test prerequisites. Missing private evidence fails; tests must not silently skip.

Run targeted tests through `focused.sh`, full/raw through `suite.sh`, and actual offline evaluation through `evaluate.sh`. The evaluator CLI accepts `--inventory`, `--results`, `--labels`, `--out` and optional `--integration-fixtures`; output must be under a private test_artifacts directory and never overwrites existing proof files.

## Decisions and limits for final review

- The isolated search worker flushes its result and exits without waiting for executor atexit joins; the pidfd/subreaper guardian reaps descendants. Real local blocked-stdin/detached-child tests cover the cleanup boundary. It is not an OS-level network sandbox or a hard-real-time scheduling guarantee.
- A separate explicit65536-byte selector input allowance shares the same supervisor; collection remains32768 bytes. Publication-model8KiB and all research recovery caps remain unchanged.
- Auxiliary history/archive errors are explicit unavailable diagnostics; the existing mandatory scout diagnostic persists fail-closed. History currently represents observed provisional stories, not inferred final qualification feedback. No production ledger read/blacklist is introduced.
- Six-lane query templates are newly code-owned and have not been live compared. Date/domain operators remain hints until actual provider enforcement/coverage is measured.
- Full end-to-end improvement requires a separately bounded live comparison and successful unchanged qualification, not more snippets or mocked tests. No deployment/push/merge is part of this results-review step.
