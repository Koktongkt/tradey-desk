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

The wrapper imports the public CLI entrypoint before web tools. It saves and
wraps `tools.web_tools.web_extract_tool`, which the installed async registry
handler resolves dynamically. Each invocation awaits the saved original once
with the identical argument objects, then returns its exact original result.
Captures precede downstream Hermes result-transform hooks; they are not a claim
about the final model-visible result after those hooks.

One `final_location_cache_guard` spans the whole focused CLI lifetime, including
parallel calls. It bypasses legacy Reuters extraction-cache reads, leaving other
publishers, cache writes, configured dispatch/rescue and safety policy unchanged.
Only the wrapper's outer attestation can authorize returned-location provenance;
a provider row or model-authored receipt cannot attest to it. This does not
promise network freshness or bypass provider-internal caches.

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

`tests/test_focused_reuse.py` includes installed-bootstrap tests executing the
actual installed async registry dispatch across parallel threads with an offline
original extraction function. It checks original argument/result identity, one
lifetime guard, normal non-Reuters cache reads, restoration and exit semantics.
Other tests cover strict artifacts/provider declarations, bounds, binding,
permissions, optional failures, process-group cleanup, selected-subset reuse,
quality misses, cache timestamps, deadlines, telemetry and the two-publisher gate.
Existing step4 extraction/security/date regressions remain in the full suite.

Run with the installed project environment:

```sh
$HOME/.local/share/tradey/venv-linux/bin/python tests/run_tests.py full
$HOME/.local/share/tradey/venv-linux/bin/python -m unittest discover -s tests -p 'test_*.py' -q
```

No live model/provider handoff is claimed by these offline tests. Release and
scheduler restoration remain gated on the parent's handoff smoke and independent
adversarial review.
