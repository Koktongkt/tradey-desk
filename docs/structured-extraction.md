# Structured exact-URL extraction operations

## Scope and ownership

The exact-URL fallback uses the project dispatcher `research_extraction.extract_tool`,
through `extraction_worker.py` and the isolated runtime discovered by
`runtime_paths.hermes_runtime()`. `extraction_compat.py` is the read-only Hermes
boundary for configuration, provider routing, website policy and URL safety.
Discovery, synthesis, independent review and execution are outside this path.

Both worker and focused extraction bypass **all shared Hermes result-cache
reads/writes**, full-text spills and publication follow-up requests. The project
source cache is unchanged. Anonymous Keenable uses the project single-response
transport; other eligible providers retain their installed transports. One primary
and at most one eligible anonymous ring are allowed, with no extra retries.
This ownership does not guarantee reachability or provider-internal freshness.

## Evidence is not transport

`status=ok` only means a bounded page envelope was returned. The parent still
requires safe same-publisher binding, substantive body, supported publication
provenance, freshness/future checks and normal candidate gates. Provider-reported
publication is explicitly unverified. Crawl/cache/modification/event times cannot
date evidence. SEC enrichment is separate. Neither the model nor probe overrides
these validators. The host's `uncached_dispatch` marker is not proof of fresh
publisher HTTP or absence of provider-side caching.

## Bounds and containment

The supervisor allows at most 30 seconds per URL, including runtime startup and
output, clamped to the caller's remaining evidence deadline. Request/stdout/stderr
caps are 8192/100000/16384 bytes. Page text/title limits are 6000/200 characters.
The parent owns, kills and reaps the child process group on every exit. This is
not a sandbox against descendants escaping the group or a hard-real-time claim.
Blocking DNS/provider threads require that hard parent boundary, not only an
async timeout. Failures remain typed; unreachable sources never become verified.

## Offline compatibility verification

A clean checkout of the parent of the local shared publication patch is required.
Reuse the existing detached checkout; do not change live Hermes or install ad hoc
packages. The bare store interpreter cannot bootstrap a checkout with no PM
selection. Use the **existing PM-committed dependency venv interpreter**, via
`HERMES_PYTHON`, without installing/copying dependencies. Then run:

```sh
export HERMES_SOURCE_ROOT="$UNPATCHED"
export HERMES_PYTHON="$SUPPORTED_PYTHON"
PYTHONPATH="$UNPATCHED" "$SUPPORTED_PYTHON" tests/run_tests.py full
"$PROJECT_PYTHON" -m unittest discover -s tests -p test_extraction_unpatched.py -v
```

The integration module asserts actual loaded `__file__` paths and exact source
SHA inside real isolated worker/focused children, and absence of
`tools/web_publication.py`. Environment variables alone are not evidence.
Legacy custom-provider test fixtures must supply their own explicit typed
publication reports; they cannot rely on stock unpatched Hermes emitting a local
patch's extension. Publication/evidence assertions remain unchanged.

## Bounded public-network probe

```sh
"$PROJECT_PYTHON" scripts/probe_project_extraction.py \
  --cohort test_artifacts/project-extraction/cohort.json \
  --output test_artifacts/project-extraction/worker.json --mode worker
# Repeat with --mode focused, the identical frozen cohort and --as-of UTC timestamp.
```

Input is a JSON list of 1–12 explicit public URLs; duplicates and invalid schemes
are refused. Output must remain under this worktree's ignored
`test_artifacts/project-extraction/` (0700); detailed files are 0600. Stdout contains
only counts, elapsed time and instrumented HTTP starts. The probe does not call a
research cycle, model, synthesis, review, journal or broker. Focused mode runs the
actual wrapper, registered async tool and authenticated parent receipt; its CLI
main callback deterministically dispatches exactly one extraction, rather than
letting an LLM choose calls. Providers and validators are not replaced.

Each source has a terminal row, requested/returned URL, transport result,
publication basis/date, acceptance/reason, elapsed time and observed transport
starts. Null request totals mean unavailable telemetry, **not zero requests**.
Provider calls include async coroutine resumes and are diagnostic events, not
retry counts. Provider-internal HTTP/cache activity is not observable here.

For baseline comparison, `--project-root <live-project>` selects the unmodified
old routing in a separate child, with old cache/spill/debug sinks redirected to
private scratch. It does not compare the feature to itself. Config fingerprints,
project/Hermes SHAs, actual module paths, evidence clock and ring origin are
recorded. The child-local initial ring cursor is aligned to zero; this is a
controlled comparison, not production's random initial rotation. No persistent
provider pin or settings are changed.

## Task 5 corrected controls (2026-10-19 UTC; no deployment)

The initial controls accepted 2/12 on baseline and 0/12 on project paths; that
blocked result is preserved in the private task report. The authorized narrow
scope extension fixes worker startup by calling the installed idempotent
`tools.web_tools._ensure_web_plugins_loaded` through compatibility before provider
lookup (after strict config admission). Missing/unsupported providers and helper
exceptions still fail closed. Keenable now sends the stock nonsecret app header
`X-Keenable-Title: hermes-agent`; it adds no authentication or payload.

The unpatched canonical full suite now passes **1189 tests**. A fresh-process
regression starts with an empty real registry, uses actual plugin discovery and
worker extraction, and fakes only network boundaries. Header and local-server
transport-accounting regressions also pass. The probe counts requests Session
send, httpx single requests and standalone stdlib requests once, excluding nested
stdlib calls and async resumes; profiling covers child threads.

One corrected four-run comparison used the unchanged frozen 12 URLs, evidence
clock, config fingerprint and initial ring cursor. Baseline and project, worker
and focused, each accepted **2/12**, rejected 10 for `source_freshness_unknown`,
and made **24 HTTP request starts** (two per source). No timeouts or lost baseline
successes occurred; project shared-cache calls remained zero. Every row observed
primary HTTP 401 followed by rescue HTTP 200. The prior rescue 400 did not recur
with the required header; this supports the contract diagnosis, not a claim that
all possible 400 causes are excluded. Primary authentication failure remains.

The historical six and initial blocked evidence remain intact. This does not
reproduce the old 3/6 claim or establish end-to-end model handoff or release
readiness. Delayed/conflicting cap snapshots remain provisional category controls,
not verified same-day caps. The unknown-date gate is unchanged. No deployment,
Task 7, patch retirement, schedules, keys, model changes or trading calls occurred.
See `task-5-report.md` and private `task5-corrected-*.json` artifacts.
