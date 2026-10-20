# Focused extraction body reuse

Focused retrieval still uses the same public Hermes CLI, configured model/provider,
web toolset, arguments, prompts, turn limits and stage/overall deadlines. Only its
entrypoint is wrapped by `focused_wrapper.py`, through the installed isolated
Python and `hermes_bootstrap`. Discovery, synthesis and rescue orchestration are
unchanged.

## Trust and lifecycle

`focused_capture.run_focused` owns a new process group and an ephemeral regular
file in a private directory beneath the configured Python scratch directory
(`TMPDIR`). Directory/file permissions are explicitly 0700/0600. The parent opens
the file exclusively with `O_NOFOLLOW` and passes only its descriptor plus a
random 256-bit run nonce in the child environment. The wrapper consumes/removes
those variables and makes the descriptor non-inheritable before CLI startup.
Neither value is added to prompts, tool results, stdout or diagnostics.

The wrapper imports the public CLI before web tools, then replaces the actual
stored async registry handler for `web_extract` with the project dispatcher
`research_extraction.extract_tool`. It replaces the model-visible schema with a
child-local deep copy as well, and restores both exact references in `finally`.
Receipts wrap this controlled project path, not a provider or model assertion.
This avoids the retired assumption that the registry dynamically resolves
`tools.web_tools.web_extract_tool` after registration. Captures precede downstream
Hermes result-transform hooks; they are not a claim about the final model-visible
result after those hooks.

All shared Hermes extraction-cache reads/writes, full-text spills and
publication follow-up requests are absent on this path, for every publisher.
Only the wrapper's guarded recorder can authorize `uncached_dispatch` provenance;
a provider row or model-authored receipt cannot attest to it. This does not
promise fresh publisher HTTP or bypass provider-internal caches.

Capture limits are optional reuse limits, **not** model/tool budget changes:
15 invocations, 15 requested URLs overall, five requested/returned rows per call,
4096 characters per URL, 24,000 UTF-8 request bytes, 100,000 raw UTF-8 response
bytes per call, and 1,600,000 artifact bytes. A thread lock protects accounting and
completion; it never spans the provider await. The complete strict-JSON artifact
is written only on successful CLI return/exit. Any unrecordable invocation
(invalid request, non-string response, or oversized response) discards the whole
optional artifact, so dropped duplicate requests cannot leave earlier receipts
reusable. Recording failure cannot alter the tool response or fail an otherwise
successful focused run.

The parent consumes only its preopened descriptor, after successful completion
and process-group cleanup. It checks type/ownership/mode/size, exact schema,
version, nonce, completion, timestamps and all capture bounds; duplicate JSON
keys and nonstandard constants are rejected. Missing, partial or invalid artifacts
mean ordinary fetch. Nonzero, launch error and timeout remain fatal focused-stage
errors even if otherwise usable captures exist. The group is signalled on every
exit, and the parent closes/removes its channel on all paths. This is process
provenance, not a sandbox against same-UID processes or descendants escaping the
owned process group.

## Binding and evidence

### Focused tool character contract

The focused child's tool schema and dispatcher share the extraction constants:
2,000–6,000 characters per page, default 6,000, at most five URLs per call.
The description accurately states that long pages return bounded head/tail text
and full text is not stored. The stock Hermes schema is not changed globally.

For compatibility with historical model requests, only this focused wrapper
caps integer limits above 6,000 before dispatch and receipt capture. Omitted or
null limits use the default; booleans, other types and values below 2,000 retain
strict dispatcher rejection. The dispatcher itself still rejects oversized
limits when called directly. A cap emits the sanitized private CLI log event
`focused_extract_limit_capped effective_char_limit=6000`, never raw arguments,
URLs, bodies or requested values. Receipts describe the effective request.
URL safety, provenance, provider routing, total-envelope limits and deadlines
are unchanged. Capping is not a source-quality or trading-gate exception.

The model's symbol-to-URL dictionary and trusted captures are separate fields on
`FocusedURLs`. No URLs are recovered from receipts or malformed final stdout.
Batch rows bind only by exact requested URL string, independent of order;
omissions are allowed. Duplicate requested keys (also across calls) or duplicate
rows disqualify that key. Only a singleton request/singleton result may bind a
redirect, subject to the existing safe same-publisher and Reuters date checks.
There is no positional, publisher-only, fuzzy or normalized matching. A selected
redirect URL never itself requested takes the normal fetch path.

The worker and capture reader share `extraction_worker.provider_rows` and
`project_row`. Fallback and reuse share `alpha_radar.validate_structured_page`.
`gather_evidence` consults captures only for its actual post-merge, health-selected
exact URL list. Every reuse hit must additionally pass the unchanged substantive
body, publication date, future-date and freshness filter before suppressing both
direct fetch and fallback. Any miss/rejection uses normal fetching. Results stay
in selected URL order and are exact-key deduplicated. Existing persistent-cache
precedence and original `checked_at` remain unchanged. Reused pages retain their
original capture check time and are never seeded into the persistent source cache.
Undated SEC captures conservatively miss reuse; normal SEC enrichment stays intact.
Rescue URLs continue on the existing path (no new rescue-selection input).

Private attempt telemetry records `direct_reason=focused_reuse_hit`,
`focused_reuse=hit|miss`, enclosing run/source hashes and
`network_attempted=false` on hits. It never records raw URLs, bodies, prompts,
channel paths, raw provider errors or a new network verification claim. Final
filtering, source receipts, ranking, two-publisher qualification, synthesis,
consensus and trading/execution gates are unchanged.

## Offline verification

`tests/test_focused_reuse.py` covers real installed-bootstrap async registry
routing, controlled project dispatch and receipts, restoration/exit semantics,
strict artifacts, binding, deadlines and reuse quality gates. Task 5 adds
`tests/test_extraction_unpatched.py` for actual selected-root module assertions,
private probe boundaries, duplicate refusal, exact row accounting and forbidden
journal/execution guards. Two custom-provider publication fixtures now declare
their own typed reports instead of depending on a stock Hermes local patch.

For bounded live verification use `scripts/probe_project_extraction.py --mode
focused` with the same frozen cohort/time as worker mode. The driver replaces
only CLI main with one deterministic registry invocation; it runs no model and
trusts only the actual host recorder/parent receipt. This verifies the focused
tool path, not an end-to-end agent handoff. See structured-extraction.md for
runtime selection, limits, sinks and the observed release blockers. In the single
corrected frozen-cohort comparison, both focused paths accepted 2/12 with 24 HTTP
starts each and no lost baseline successes or timeouts. The required nonsecret
Keenable app header and worker plugin registration are now covered by regressions;
primary HTTP 401 and ten unknown-date rejections remain. This does not authorize
handoff, cutover or scheduler restoration.

Run with the installed project environment:

```sh
$HOME/.local/share/tradey/venv-linux/bin/python tests/run_tests.py full
$HOME/.local/share/tradey/venv-linux/bin/python -m unittest discover -s tests -p 'test_*.py' -q
```

No live model/provider handoff is claimed by these offline tests. Release and
scheduler restoration remain gated on the parent's handoff smoke and independent
adversarial review.
