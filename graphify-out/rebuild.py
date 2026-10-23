#!/usr/bin/env python3
"""Offline source-only rebuild. Run with graphifyy==0.9.75's Python.

Usage: python graphify-out/rebuild.py REVISION /dedicated/analysis/directory
Source bytes are read with git show, never imported or executed. Labels are
reviewed separately after the first run, then --render regenerates outputs.
"""
import argparse
import collections
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess


def dump(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('revision')
    ap.add_argument('analysis', type=Path)
    ap.add_argument('--render', action='store_true')
    args = ap.parse_args()
    if importlib.metadata.version('graphifyy') != '0.9.75':
        raise SystemExit('Use graphifyy==0.9.75 to preserve the audited extraction recipe')
    repo = Path(__file__).resolve().parent.parent
    out = repo / 'graphify-out'
    def git(*cmd):
        return subprocess.check_output(['git', '-C', str(repo), *cmd])
    revision = git('rev-parse', args.revision + '^{commit}').decode().strip()
    if not args.render:
        if args.analysis.exists():
            raise SystemExit('Analysis directory must not already exist')
        args.analysis.mkdir(parents=True)
        root = args.analysis / 'source'
        root.mkdir()
        tracked = git('ls-tree', '-r', '--name-only', revision).decode().splitlines()
        def selected(p):
            parts = Path(p).parts
            return p.endswith('.py') and (len(parts) == 1 or parts[0] in ('tests', 'watchdog', 'scripts'))
        paths = [p for p in tracked if selected(p)]
        rows = []
        for p in paths:
            data = git('show', revision + ':' + p)
            dest = root / p
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            rows.append({'path': p, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
        from graphify.detect import detect, save_manifest
        detection = detect(root)
        assert detection['total_files'] == len(paths), (detection['total_files'], len(paths))
        assert not any(detection['files'].get(k) for k in ('document', 'paper', 'image', 'video'))
        dump(args.analysis / 'detection.json', detection)
        from graphify.extract import extract
        ast = extract([root / p for p in paths], cache_root=root)
        # Normalize machine-specific source paths, retaining all raw nodes/edges.
        def portable(obj):
            if isinstance(obj, dict):
                return {k: portable(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [portable(v) for v in obj]
            if isinstance(obj, str):
                return obj.replace(str(root) + '/', '')
            return obj
        ast = portable(ast)
        dump(out / 'EXTRACTION_AUDIT.json', ast)
        semantic = {'nodes': [], 'edges': [], 'hyperedges': [], 'input_tokens': 0, 'output_tokens': 0}
        dump(args.analysis / 'semantic.json', semantic)
        extraction = dict(ast, hyperedges=[], input_tokens=0, output_tokens=0)
        dump(args.analysis / 'extraction.json', extraction)
        dump(out / 'SOURCE_SCOPE.json', {
            'revision': revision,
            'scope': 'Git-tree Python source/tests only: root *.py plus tests/, watchdog/, scripts/ *.py. No source execution.',
            'source_files': rows, 'excluded_tracked_paths': [p for p in tracked if p not in paths],
            'total_files': len(paths), 'total_words': detection['total_words'],
            'graphify_version': importlib.metadata.version('graphifyy'), 'directed': False,
            'semantic_extraction': 'empty; AST only; no model API',
            'deployment': 'offline analysis; no deployment or runtime approval claim',
            'exclusions': 'No private ledger/state/credentials/config/docs/generated output/test_artifacts/worktrees scanned. Credential-named modules are source mechanics only.'})
        save_manifest(detection['files'], manifest_path=str(out / 'manifest.json'), root=root,
                      scan_corpus={str(root / p) for p in paths}, kind='ast')
    else:
        root = args.analysis / 'source'
        extraction = json.loads((args.analysis / 'extraction.json').read_text())
        detection = json.loads((args.analysis / 'detection.json').read_text())
    from graphify.build import build_from_json
    from graphify.cluster import cluster, score_all
    from graphify.diagnostics import diagnose_extraction
    from graphify.analyze import god_nodes, surprising_connections, suggest_questions
    from graphify.export import to_json, to_html
    from graphify.report import generate
    extraction = json.loads((args.analysis / 'extraction.json').read_text())
    G = build_from_json(extraction, root=root, directed=False)
    assert G.number_of_nodes() > 0
    if not args.render:
        communities = cluster(G)
        dump(args.analysis / 'communities.json', communities)
        dump(args.analysis / 'community-review.json', {cid: {
            'size': len(nodes),
            'sources': collections.Counter(G.nodes[n].get('source_file', '') for n in nodes).most_common(5),
            'labels': [G.nodes[n].get('label', n) for n in sorted(nodes, key=lambda n: -G.degree(n))[:8]]
            } for cid, nodes in communities.items()})
        health = diagnose_extraction(extraction, directed=False, root=root)
        health['producer_suppression']['path'] = 'graphify/extract.py (graphifyy==0.9.75)'
        dump(out / 'GRAPH_HEALTH.json', health)
        print(json.dumps({'files': detection['total_files'], 'words': detection['total_words'],
              'raw_nodes': len(extraction['nodes']), 'raw_edges': len(extraction['edges']),
              'nodes': G.number_of_nodes(), 'edges': G.number_of_edges(), 'communities': len(communities)}))
        return
    communities = {int(k): v for k, v in json.loads((args.analysis / 'communities.json').read_text()).items()}
    labels = {int(k): v for k, v in json.loads((out / '.graphify_labels.json').read_text()).items()}
    assert labels.keys() == communities.keys()
    cohesion = score_all(G, communities)
    questions = suggest_questions(G, communities, labels)
    assert to_json(G, communities, str(out / 'graph.json'), community_labels=labels)
    assert to_html(G, communities, str(out / 'graph.html'), community_labels=labels)
    # Report is deliberately portable; no host analysis root is published.
    report = generate(G, communities, cohesion, labels, god_nodes(G),
                      surprising_connections(G, communities), detection,
                      {'input': 0, 'output': 0}, 'pinned-source', suggested_questions=questions)
    report = report.replace(str(root) + '/', '').replace(str(root), 'pinned-source')
    (out / 'GRAPH_REPORT.md').write_text(report)
    dump(out / 'cost.json', {'revision': revision, 'input_tokens': 0, 'output_tokens': 0,
         'semantic_extraction': False, 'community_labeling': 'host-assisted; outside extraction token count'})
    print(f'Rendered {G.number_of_nodes()} nodes / {G.number_of_edges()} edges; cohesion {min(cohesion.values())}–{max(cohesion.values())}')


if __name__ == '__main__':
    main()
