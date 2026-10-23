# Tradey pinned structural graph

Source revision: `237b8251e027c5469263a4afbb6688a0789388fd` (latest local `main` when this rebuild started). Offline source analysis only; **not deployed, not runtime approval evidence**.

## Scope and results

Fresh full Graphify **0.9.75** rebuild: **172 Git-tree Python source/test files, 177,327 whitespace words; 4,269 graph nodes, 10,541 undirected edges, 180 inspected/labeled communities**. Scope preserves Python runtime/tests plus tracked Python source helpers: root `*.py`, recursive `tests/`, `watchdog/`, `scripts/`. This expands the previous 91-file snapshot to cover new source in the same categories; it does not index generated documentation.

Every selected byte was copied with `git show REV:path` into a dedicated non-deployed analysis directory. SOURCE_SCOPE.json records exact revision, paths, bytes, SHA-256 and excluded tracked paths. No entire-checkout scan, source execution, ledger/state reads, credentials, configs, private outputs, `test_artifacts`, worktrees, or generated docs entered the corpus. Credential-named modules are code mechanics, not credential stores.

Raw AST extraction: **4,207 nodes / 10,969 edges**, including **700 INFERRED** callback/heuristic edges and 10,269 EXTRACTED edges. Builder creates 62 implicit endpoint nodes. Raw diagnostics disclose **1,067 dangling-endpoint edges, 22 self-loop edges, zero missing-endpoint edges, 425 directed / 426 undirected same-endpoint collapses among valid candidate edges**. These diagnostic collapse counts exclude dangling endpoints; they are not a subtraction formula for final edge count. No edges were manually authored or repaired. Cohesion range: **0.03076923076923077–1.0**.

**Undirected structural connectivity is not a runtime execution chain.** Static calls do not establish successful execution, chronology, scheduler activation, or broker authorization. Runtime tests were not run by this analysis worker. Semantic extraction is empty and extraction token counts are zero; host-assisted community labels are outside that count.

## Contents and checks

- `graph.html`, `graph.json`: searchable visual and structural graph.
- `GRAPH_REPORT.md`: raw cohesion, high-degree nodes, inferred connections and suggested questions.
- `EXTRACTION_AUDIT.json`, `GRAPH_HEALTH.json`: all raw extraction and unfiltered health diagnostics (package path made portable).
- `SOURCE_SCOPE.json`, `manifest.json`: pinned source SHA-256 inventory and portable AST incremental manifest.
- `STRUCTURAL_QUERY.txt`: real Graphify BFS queries with expanded vocabulary plus raw outgoing call edges/direction/confidence and source locations.
- `BROWSER_VERIFICATION.json`, `graph-preview.png`: actual Chromium render and inspected preview, bound to HTML hash.
- `READONLY_VERIFICATION.json`: selected source/snapshot integrity and artifact checks; no operational-state read or runtime activation claim.
- `BENCHMARK.txt`, `cost.json`: real CLI estimate-only benchmark and zero extraction LLM token accounting; not measured savings.
- `rebuild.py`: reproducible source-only snapshot/extract/cluster/render recipe.
- `ARTIFACT_MANIFEST.json`: exact byte/SHA-256 inventory of every other payload file; excludes itself and caches.

Browser verified **4,269 loaded nodes, 10,541 edges, 180 communities and a 1240×980 canvas**; the graph and sidebar text visibly render. DOM input-event search checks for `synthesize_candidate`, `gather_evidence`, `scheduled_slot`, `run_cycle`, `focused_retrieval` return actual node results. No page errors, console errors or failed requests. The full overview is dense: use search/zoom and community filters. Below 5,000 nodes, so the full-node view is used. HTML requires internet for the integrity-checked **unpkg vis-network 9.1.6** dependency; not vendored. Browser dependencies/fonts were provisioned in isolated scratch storage after the normal browser tool could not access a supported local profile.

Query checks retain exact AST links: `live_research` calls `focused_retrieval` (`alpha_radar.py:L1868`), `gather_evidence` (`L1897`) and `synthesize_candidate` (`L2064`). `run_cycle.main` calls `scheduled_slot` (`run_cycle.py:L235`), `in_window` (`L237`) and `execute` (`L240`). These are raw EXTRACTED call-site facts, not inferred runtime chains. Enrichment is represented by evidence/retrieval vocabulary rather than a fabricated `enrich` symbol.

## Rebuild recipe

Use an isolated worktree at the chosen source revision and an **absent**, dedicated scratch analysis directory. Never run `graphify extract .` in the operational checkout.

```sh
uv tool run --from graphifyy==0.9.75 python graphify-out/rebuild.py \
  237b8251e027c5469263a4afbb6688a0789388fd /dedicated/non-deployed/analysis
# Inspect analysis/community-review.json and write 2–5 word names for every
# newly clustered community into graphify-out/.graphify_labels.json.
uv tool run --from graphifyy==0.9.75 python graphify-out/rebuild.py \
  237b8251e027c5469263a4afbb6688a0789388fd /dedicated/non-deployed/analysis --render
uv tool run --from graphifyy==0.9.75 graphify query \
  'alpha_radar live_research synthesize_candidate gather_evidence focused_retrieval'
uv tool run --from graphifyy==0.9.75 graphify query \
  'run_cycle scheduled_slot in_window main execute'
```

Then refresh query/benchmark/browser/read-only receipts and the artifact manifest; verify all hashes and source inventory. Labels may change when community membership changes. Retain raw health warnings. Never carry forward stale browser receipts or claim approval/deployment. Analysis cache, copied source and installed dependencies are intentionally not committed. This work commits graph artifacts only; no push or deploy.
