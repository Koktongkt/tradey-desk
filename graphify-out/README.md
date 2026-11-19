# Tradey pinned structural graph

Source revision: `69587777f1d7f41b76f41f686cf21d67d6a0b92b` (local `main` HEAD, clean tree, when this rebuild started). Offline source analysis only; **not deployed, not runtime approval evidence**.

## Scope and results

Fresh full Graphify **0.9.75** rebuild: **212 Git-tree Python source/test files, 228,858 whitespace words; 5,649 graph nodes, 14,592 undirected edges, 228 inspected/labeled communities**. Scope is unchanged from the prior pin (`237b825`, 172 files): root `*.py`, recursive `tests/`, `watchdog/`, `scripts/`. The 40 extra files are new source in those categories (e.g. `opportunity_identity/activation/cutover/state/admin`, `entry_authority/eligibility/fills`, `research_memory(_transition)`, `research_mode`, `radar_memory`, `earnings_identity_*`, `acquisition_research`, `enrichment_diagnostics`, `policy_diagnostics`, `review_history`, `evidence_capture_store`, `scripts/check_url_safety_compatibility.py`). Generated documentation is not indexed.

Every selected byte was copied with `git show REV:path` into a dedicated non-deployed scratch analysis directory. SOURCE_SCOPE.json records exact revision, paths, bytes, SHA-256 and the 119 excluded tracked paths. No entire-checkout scan, source execution, ledger/state reads, credentials, configs, private outputs, `test_artifacts`, worktrees, or generated docs entered the corpus. Credential-, ledger- and lineage-named modules (`broker_credentials.py`, `durable_jsonl.py`, `private_lineage.py`, `scripts/repair_nul_jsonl.py`) are code mechanics, not credential stores or ledgers.

Raw AST extraction: **5,586 nodes / 15,177 edges**, including **935 INFERRED** callback/heuristic edges and 14,242 EXTRACTED edges. Builder creates 63 implicit endpoint nodes. Raw diagnostics (GRAPH_HEALTH.json) disclose **1,321 dangling-endpoint edges, 26 self-loop edges, zero missing-endpoint edges, 582 directed / 583 undirected same-endpoint collapses among 13,856 valid candidate edges**. These collapse counts exclude dangling endpoints; they are not a subtraction formula for final edge count. No edges were manually authored or repaired. Cohesion range: **0.03076923076923077–1.0**. An independent second extraction+clustering from a fresh snapshot copy produced identical raw output and identical community membership.

**Undirected structural connectivity is not a runtime execution chain.** Static calls do not establish successful execution, chronology, scheduler activation, or broker authorization. Runtime tests were not run by this analysis worker. Semantic extraction is empty and extraction token counts are zero; host-assisted community labels are outside that count. Labels: 129 communities reuse the prior name where membership overlaps ≥50% (Jaccard); 99 were named fresh from member labels/sources.

## Contents and checks

- `graph.html`, `graph.json`: searchable visual and structural graph.
- `GRAPH_REPORT.md`: raw cohesion, high-degree nodes, inferred connections and suggested questions.
- `EXTRACTION_AUDIT.json`, `GRAPH_HEALTH.json`: all raw extraction and unfiltered health diagnostics (package path made portable).
- `SOURCE_SCOPE.json`, `manifest.json`: pinned source SHA-256 inventory and portable AST incremental manifest.
- `STRUCTURAL_QUERY.txt`: three real Graphify BFS queries plus raw outgoing call edges (direction, confidence, source locations) for 11 symbols; call-site lines re-checked against `git show REV:file`.
- `BROWSER_VERIFICATION.json`, `graph-preview.png`: actual Chromium render and visually inspected preview, bound to HTML and preview hashes.
- `READONLY_VERIFICATION.json`: source (Git blob, snapshot, worktree) and artifact integrity checks; no operational-state read or runtime activation claim.
- `BENCHMARK.txt`, `cost.json`: real CLI estimate-only benchmark and zero extraction LLM token accounting; not measured savings.
- `rebuild.py`: reproducible source-only snapshot/extract/cluster/render recipe.
- `ARTIFACT_MANIFEST.json`: exact byte/SHA-256 inventory of every other payload file; excludes itself and caches.

**HTML node limit:** 5,649 nodes exceeds graphify's default 5,000-node HTML limit, so the `--render` step raises `ValueError` unless `GRAPHIFY_VIZ_NODE_LIMIT` is raised. This build used `GRAPHIFY_VIZ_NODE_LIMIT=6000` to keep the full-node searchable view instead of the aggregated community-only view. The browser loaded it fine, but the overview is dense: use search, zoom and community filters.

Browser verified **5,649 loaded nodes, 14,592 edges, 228 legend communities, a 1240×980 viewport**; graph, sidebar and legend text visibly render. Keyboard-typed search for `synthesize_candidate`, `gather_evidence`, `authorize_attempt`, `resolve_event`, `research_memory`, `scheduled_slot` returns actual node results. No page errors, console errors or failed requests. HTML requires internet for the integrity-checked **unpkg vis-network 9.1.6** dependency; it is not vendored. Missing Chromium shared libraries were extracted into isolated scratch storage (no system/app dependency changes).

Query checks retain exact AST links: `live_research` (`alpha_radar.py:L2173`) calls `focused_retrieval` (`L2234`), `gather_evidence` (`L2263`) and `synthesize_candidate` (`L2543`). `run_cycle.main` (`run_cycle.py:L271`) calls `scheduled_slot` (`L273`), `in_window` (`L275`) and `execute` (`L278`). New-module queries cover `entry_authority.authorize_attempt` (`L137`), `opportunity_identity.resolve_event` (`L309`), `research_memory.complete`/`lookup` and `research_memory_transition.apply` (`L143`). These are raw EXTRACTED call-site facts, not inferred runtime chains. Enrichment is represented by evidence/retrieval vocabulary rather than a fabricated `enrich` symbol.

## Rebuild recipe

Use an **absent**, dedicated scratch analysis directory. Never run `graphify extract .` in the operational checkout.

```sh
uv tool run --from graphifyy==0.9.75 python graphify-out/rebuild.py \
  69587777f1d7f41b76f41f686cf21d67d6a0b92b /dedicated/non-deployed/analysis
# Inspect analysis/community-review.json and write 2–5 word names for every
# clustered community into graphify-out/.graphify_labels.json.
GRAPHIFY_VIZ_NODE_LIMIT=6000 uv tool run --from graphifyy==0.9.75 python graphify-out/rebuild.py \
  69587777f1d7f41b76f41f686cf21d67d6a0b92b /dedicated/non-deployed/analysis --render
uv tool run --from graphifyy==0.9.75 graphify query \
  'alpha_radar live_research synthesize_candidate gather_evidence focused_retrieval'
uv tool run --from graphifyy==0.9.75 graphify query \
  'run_cycle scheduled_slot in_window main execute'
uv tool run --from graphifyy==0.9.75 graphify query \
  'opportunity_identity entry_authority research_memory'
```

Run queries against a scratch copy of `graph.json`. Then refresh query/benchmark/browser/read-only receipts and the artifact manifest; verify all hashes and the source inventory. Labels may change when community membership changes. Retain raw health warnings. Never carry forward stale browser receipts or claim approval/deployment. Analysis cache, copied source and installed dependencies are intentionally not committed. This refresh was left uncommitted: no commit, push or deploy.
