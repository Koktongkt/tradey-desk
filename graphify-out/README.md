# Tradey pinned structural graph

Source revision: `0d3a5a554bf2c36b758f085ab46e56d2a317f7a8`. **Local candidate under independent review; not deployed. Independent final review running; approval is parent-owned and separate.**

READY pending independent final review (running, not approved). Frozen offline candidate; parent owns runtime approval separately; no live claim.

Fresh full rebuild: **91 Git-tree Python source/test files, 90,490 whitespace words; 2,299 graph nodes, 5,544 undirected edges, 110 freshly inspected and labeled communities.** Raw extraction: 2,252 nodes / 5,740 edges; builder adds 47 implicit endpoint nodes. No entire-checkout scan. Exact inventory, SHA-256 and excluded tracked paths: SOURCE_SCOPE.json. All source bytes come from `git show` at the pin; selected frozen worktree/snapshot bytes and Git index verified unchanged.

## Contents

- graph.html / graph.json: searchable visual and structural graph.
- GRAPH_REPORT.md: raw cohesion, god nodes, inferred surprises and questions.
- EXTRACTION_AUDIT.json / GRAPH_HEALTH.json: unfiltered extraction and diagnostics.
- SOURCE_SCOPE.json / manifest.json: pinned complete selected-source hashes and portable incremental AST manifest.
- BROWSER_VERIFICATION.json / graph-preview.png: actual HTML-bound Chromium receipt and inspected preview.
- READONLY_VERIFICATION.json: confined-source/index read-only checks; not runtime activation evidence.
- STRUCTURAL_QUERY.txt: vocabulary-expanded BFS and qualification-to-proposal/placing-notification paths with source locations.
- BENCHMARK.txt / cost.json: estimate-only CLI benchmark and zero extraction LLM token accounting.
- ARTIFACT_MANIFEST.json: exact byte hashes for every other payload file; deliberately does not hash itself.

## Limits and warnings

Undirected AST/import/containment discovery is **not a runtime-verified call graph**. No broker/model/scheduler actions, credentials or operational state were accessed. Credential-loading modules are code mechanics, not credential stores. Tests are indexed symbols; this worker did not execute runtime tests. Scope excludes configs, docs, generated/private/public/state trees and test_artifacts; explicit included source `public_dashboard.py` is code, not public output data. Source-only AST extraction has empty semantics and zero extraction tokens; host-assisted community labels are outside that cost count.

Raw graph-health warnings: **535 dangling-endpoint edges, 20 self loops, 194 same-endpoint edge collapses** (both diagnostic directed and undirected counts). Missing endpoints: 0. Do not hide heuristic false links or treat them as runtime authority. Raw cohesion range: 0.031746031746031744–1.0.

Browser PASS: canvas 1220×950, 2299 loaded nodes; searches qualify, supervisor, readonly, metadata, run_watchdog all returned actual node results; no page errors or console errors. Actual preview inspected: network and sidebar rendered; dense overview requires search/zoom for labels. HTML requires internet to load **integrity-checked unpkg vis-network 9.1.6**; dependency was loaded in this browser check, not vendored.

Real benchmark stdout retained in BENCHMARK.txt. Actual scoped source count is 90490 words. CLI graph-derived corpus defaults are estimates, not measured token or runtime savings.

Qualification paths with fresh source locations and exact edge confidence are in STRUCTURAL_QUERY.txt. This demonstrates structural co-connectivity, **not chronological placement**, approval, live activation or cancellation. No automatic cancellation edge has been authored.

Refresh later only from another explicitly pinned, vetted code-only snapshot; full rebuild chosen here because historical source coverage was stale. No Git staging, commits or pushes occurred. Portable artifacts omit absolute host paths and analysis caches/source snapshots.
