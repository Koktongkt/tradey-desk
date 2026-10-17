# Structured exact-URL fallback operations

## Scope

This release replaces only the exact-URL fallback after the deterministic direct HTTP fetch fails. It does not replace discovery, focused retrieval, candidate rescue searches, synthesis, independent review, or paper-order controls.

The worker invokes the installed Hermes configured `web_extract` dispatcher without an agent/model handoff. Provider selection, website policy, URL safety, supported extraction rescue, and unknown-publisher eligibility remain under the same dispatcher. No new publisher allowlist, provider pin, API key, or model setting is introduced.

## Evidence versus extraction

A successful structured extraction means content was returned, not that an investment source qualified. Parent validation binds the request and returned location; normal body, publication provenance, stale/future, independent-publisher and candidate gates remain authoritative. Missing publication dates must not be replaced by cache, crawl, modification or event timestamps. SEC filing-date enrichment remains separate.

The public Hermes tool projection does not retain all provider metadata. Supported visible publication markup/datelines may establish publication dates; unsupported or absent provenance remains unknown. Cache hits are not proof of current network health. A fast extraction does not establish universal publisher reach or a qualifying two-source candidate.

## Narrow legacy extraction-cache handling

The installed Hermes extraction cache stores content under the requested URL and discards the returned article location. Its public tool projection also strips the cache flag. Replaying a redirected Reuters article could therefore supply the requested URL's year to a yearless Reuters dateline. Rejecting the first conflicting redirect alone does not fix this replay.

Inside the isolated, single-request worker only, a scoped cache-read guard treats legacy Hermes extraction-cache reads for `reuters.com` and its subdomains as misses. All installed entries for those hosts lack final-location annotation, including old entries and newly written ones; none can establish final-location provenance. The guard is restored in `finally`, including dispatch failures/timeouts. It does not change persistent configuration, installed Hermes source, cache writes, TTLs, provider selection, policy/URL controls or rescue. Other hosts retain their ordinary cache reads. This is not a publisher eligibility list.

A guarded dispatcher result carries `page.location_provenance="uncached_dispatch"` in the private worker envelope. Parent validation accepts only that explicit marker and permits Reuters URL-assisted year inference only with it; missing provenance leaves the yearless dateline undated, and invalid provenance is malformed. The marker means the legacy Hermes cache could not rebind that location, **not** a verified fresh HTTP fetch, independently authenticated final URL, or visibility into provider-internal caching. Safe returned same-publisher locations and explicit visible full-year publication dates remain supported. Conflicting requested/returned Reuters path dates still fail closed.

The separate parent project source cache, including its validated `returned_url`, publication timestamp, and existing TTL, is unchanged. Repeated Reuters fallbacks may cost an additional provider call and fail if a new extraction cannot be obtained; validated parent-cache reuse avoids that call. No budgets or evidence/trading gates are widened. Revisit this compatibility guard if the installed dispatcher/cache API changes; a future metadata-preserving cache contract would need explicit validation before enabling those reads.

Leading HTML denial bodies are checked after excluding head/title/script/style material, including paragraph/div wrappers. Later incidental error mentions in otherwise substantive articles are not scanned as leading denial blocks.

## Failure handling and deadlines

The existing exact-URL fallback allocation is at most 30 seconds, clamped to the remaining shared evidence deadline. The worker uses bounded request/response/stderr channels. Ordinary fallback failures retain the legacy None return; strict rescue retains `research_rescue_unavailable`. Public research decision reasons are not replaced by arbitrary provider prose.

The supervisor kills the launched process group on completion/failure. This does not promise hard real-time scheduling or containment of arbitrary processes that deliberately escape that group. Existing synchronous parent DNS validation can consume time before the worker is launched. Do not widen budgets or claim provider recovery from the mere presence of this implementation.

## Private diagnostics

The separate private source-attempt ledger distinguishes direct transport from fallback outcome and elapsed/budget measurements. Opaque identifiers correlate collection/source activity without persisting raw URLs, content, prompts, credentials or exception prose. Keep these records private; do not publish them to the dashboard or register them as public views. Use the accompanying research diagnostics for source quality/acceptance, rather than interpreting extraction success as source acceptance.

## Verification

Run the installed project environment's full test suite, not only the extraction tests:

```sh
$HOME/.local/share/tradey/venv-linux/bin/python -m unittest discover -s tests -p 'test_*.py' -q
```

Live verification uses an isolated harness with scratch-only output and no research cycle, broker calls, candidate persistence or order operations. Exercise representative original blocked URLs and a successful control. Record returned status, body size, supported publication date, binding and elapsed time; distinguish cache-served/provider output from fresh network proof where provider telemetry is unavailable.

Before rollout: independent adversarial review, all blocking fixes RED-tested, full suite green, explicit source/test/doc staging, pushed remote SHA readback, and restoration/readback of exactly the previously paused producer/consumer cron states. A verified release is not proof of the next scheduled scan's recovery.
