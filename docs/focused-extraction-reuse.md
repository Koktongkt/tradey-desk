# Focused coverage and trusted evidence reuse

## Production radar route

`alpha_radar.focused_retrieval(candidates, deadline=None)` remains the public
boundary. With focused retrieval enabled it calls the real
`focused_pipeline.run_focused_pipeline` through a local import (allocation shares
radar's publisher/provenance ranking; there is no top-level circular import).
Disabled focused retrieval retains the discovery/ordinary-fetch route.

Discovery is unchanged: six search lanes, at most five candidates and five seed
URLs total, two model turns and advisory `--run-budget 130`. Focused search retains
its three primary/independent/wire objectives, configured provider/model and
seven-turn/110 advisory model ceilings, but uses **search-only** tools. No model
article body, publication date or extraction claim becomes evidence. The strict
manifest allows up to five alternatives per symbol and 25 alternative bindings;
only exact URL keys attested by the mandatory private version-2 search receipt
survive. Invalid JSON/schema, unknown symbols, missing/invalid mandatory receipts,
nonzero exits and supervisor faults are typed focused-stage failures, not a
successful empty setup. An attested empty manifest is valid; scout seeds still
receive allocation consideration. Search output does not select final bindings.

The parent validates safety in owned isolated workers, loads recent source health
once, and allocates in five candidate-coverage rounds. Each symbol keeps its first
eligible scout seed first, even if that publisher is unhealthy. Other slots prefer
distinct publishers, healthy publishers, provenance rank, then stable pool order.
Unknown publishers remain eligible. Allocation retains **up to five initial URL
bindings per candidate and 25 unique extraction URLs**. A scarce or unsafe pool
need not fill every slot. Shared exact URLs are extracted once and bound only to
symbols that supplied them. The radar does not re-sort into the retired three-URL
merge or pass this route through the legacy global-15 parser/capture.

Extraction uses at most **five batches**, **five URLs per batch**, **three batches
concurrently in flight**, and no executor backlog. Dispatch is admission, not
proof of an HTTP request. Each supervisor recomputes its allowance immediately
before dispatch, capped at 30 seconds and the original focused deadline. The
project extraction request is 6,000 characters/page (the shared supported range
is 2,000–6,000); response/stderr caps remain 100,000/16,384 bytes per call.
Supervisors kill/reap their owned process group before returning; this is not a
sandbox against same-UID processes or descendants escaping that group.

One focused deadline is established **before command preparation**, and never
refreshed: `min(start + 150, active_deadline - 260)`, or `start + 150` standalone.
Search prompt construction, health loading, safety validation, scheduling and
extraction consume that deadline. The active research limit stays 570 seconds,
with the existing 260-second downstream reserve (180 evidence/rescue + 30 viable
synthesis + 45 cumulative enrichment + five transition headroom). Full discovery
leaves at most 145 focused seconds before local overhead. This is bounded
headroom, not a hard-real-time promise about arbitrary local work or SEC trickle
reads. The outer cycle's 600-second backstop is unchanged.

## Evidence boundary

`FocusedURLs` carries selected bindings separately from trusted version-1
`CapturedResult` page envelopes and their original parent receipt check times.
Its private `focused_result` metadata permits diagnostic accounting without
reconstructing allocation from model text. It is not serialized into a candidate
or public stdout. Workers and legacy capture share `provider_rows`/`project_row`;
reuse and fallback share `alpha_radar.validate_structured_page`. There is no new
lenient body/date validator.

`gather_evidence` consults only the actual selected exact keys. A hit must pass
requested/returned identity, publication provenance, substantive body, future-date
and freshness checks before it suppresses **both** direct and fallback fetches.
Results retain selected order, exact-key deduplication, original `checked_at` and
persistent-cache precedence. Reused pages never seed the persistent cache.
Undated/mismatched/error/stale pages are ordinary bounded misses. Undated SEC
pages still take ordinary fetching and the existing official SEC date enrichment;
no publication date is inferred from receipt/check time. Safe same-publisher
redirect and Reuters date-conflict rules are unchanged.

Two accepted fresh distinct-publisher sources remain mandatory. Synthesis bundles
remain at most four sources / 18,000 characters. Successful intake skips rescue;
otherwise at most three distinct candidates enter existing resumable rescue.
Five initial bindings leave room for three new URLs under the existing eight-URL
post-rescue binding cap. Already-selected keys cannot be recycled into alternate
rescue. Synthesis attempt ceilings, earnings, receipts, consensus, broker and all
execution gates remain unchanged.

## Private diagnostics

`record_focused_allocation(result, *, accepted_by_symbol, path)` writes only
strict private projections correlated to the enclosing research `run_id`:

- Per candidate: run-salted candidate token; available eligible pool bindings,
  selected bindings, actually submitted bindings, successful focused worker
  envelopes (`extracted`), and post-collection quality-accepted selected bindings.
- Per unique selected source: run-salted `url_id`, allowlisted outcome and observed
  submitted/extracted/accepted flags. Shared-URL binding counts and unique-source
  counts are intentionally different.
- `network_attempted=null`: focused supervisor admission does not establish
  provider HTTP accounting. Unknown is not zero. Separate downstream attempt rows
  may record `network_attempted=false` for a proven `focused_reuse_hit`; this says
  nothing about the earlier provider's network/cache use.

Accepted counts are measured before rescue and may include ordinary-fetch
recovery, so they are not a focused-provider success or reuse-rate claim. Model
counts and `candidate_counts` claims are not used. No raw symbols, URLs, bodies,
prompts, stderr, private artifact paths or arbitrary error strings enter these
rows. Rescue progress tokens are also run-salted. Required diagnostic persistence
failure stops research before synthesis/intake; it cannot turn absent evidence
into success. Candidate/public stdout contracts are unchanged.

## Legacy capture compatibility

`focused_capture.run_focused`, `focused_wrapper.py` and
`parse_focused_retrieval` remain available to their existing non-production
callers/probes. Legacy optional capture limits (15 invocations / 15 URLs,
1,600,000 artifact bytes) have **not** been widened. Legacy capture owns a private
0700 directory / 0600 preopened descriptor, nonce and strict completed artifact;
missing/invalid optional artifacts mean normal fetch. Only its guarded project
dispatch can attest `uncached_dispatch`; provider/model self-attestation cannot.
The wrapper restores registry schema/handler references, never changes the shared
Hermes installation, and caps historical integer extraction limits above 6,000.
This legacy compatibility path is not the production focused coordinator.

## Verification and release status

Offline tests exercise the real radar/coordinator/search-parser/allocation/shared
quality/receipt handoff, replacing external model/search/network/broker boundaries.
They cover all 25 initial bindings, zero duplicate fetches for accepted pages,
receipt times, misses, rescue caps, strict diagnostic allowlists and actual counts.
The installed-wrapper/worker suites retain runtime, process cleanup, schema and
provenance regressions. Use the approved existing environment (no dependency
installation) and compare `tests/run_tests.py full` with raw unittest discovery.

No live rollout, provider probe, broker call, scheduler change or improved
qualification rate is authorized or demonstrated by this implementation. Live
handoff smoke, independent adversarial review and any cutover remain separate
release gates owned by the parent.
