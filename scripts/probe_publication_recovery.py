#!/usr/bin/env python3
"""Private, offline-first publication evaluation. No research/ledger entrypoint.

Dataset v1: cohorts map names to fixed aware ISO as-of clocks; rows contain id,
kind (real/synthetic), url, event, cohort, class, label (value/precision or null),
page (authentic canonical capture), legacy (full applicable legacy parse), and
separate fetch_error/parsing_error. Labels never enter the interpreter request.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def same_claim(claim, label):
    if not isinstance(claim, dict) or not isinstance(label, dict):
        return False
    if claim.get('precision') == 'day' and label.get('precision') == 'instant':
        # A supported civil publication day is useful but is NOT an instant.
        # Separate precision-loss counts below keep this from claiming exact
        # timestamp recovery, UTC conversion, or invented midnight.
        return claim.get('value') == label.get('value', '')[:10]
    if claim.get('precision') != label.get('precision'):
        return False
    if label['precision'] == 'instant':
        try:
            a = datetime.fromisoformat(claim['value'].replace('Z', '+00:00'))
            b = datetime.fromisoformat(label['value'].replace('Z', '+00:00'))
            return a.utcoffset() is not None and b.utcoffset() is not None and a == b
        except (ValueError, KeyError, TypeError):
            return False
    return claim.get('value') == label.get('value')


def score_claims(rows, claims, *, accepted_ids):
    """Count representations, not misleadingly independent repeated URLs/events."""
    output = {}
    for kind in ('real', 'synthetic'):
        group = [r for r in rows if r['kind'] == kind]
        counts = Counter(independent_urls=len({r['url'] for r in group}),
                         independent_events=len({r['event'] for r in group}),
                         representations=len(group), scored_representations=0,
                         fetch_errors=0, parsing_errors=0, known=0, correct=0,
                         missed_known=0, wrong_claims=0, wrong_accepted=0,
                         unknown_falsely_accepted=0, abstention=0, accepted=0)
        for row in group:
            if row.get('fetch_error'):
                counts['fetch_errors'] += 1
                continue
            if row.get('parsing_error'):
                counts['parsing_errors'] += 1
                continue
            counts['scored_representations'] += 1
            claim = claims.get(row['id'])
            known = row.get('label') is not None
            correct = same_claim(claim, row.get('label'))
            accepted = row['id'] in accepted_ids
            counts['accepted'] += accepted
            counts['known'] += known
            counts['correct'] += correct
            counts['missed_known'] += known and not correct
            counts['wrong_claims'] += bool(claim) and known and not correct
            counts['wrong_accepted'] += accepted and known and not correct
            counts['unknown_falsely_accepted'] += accepted and not known
            counts['abstention'] += not bool(claim)
        output[kind] = dict(counts)
    return output


def evaluate(dataset, results=None):
    """Offline replay through the reviewed interpreter and actual source filter.

    results is {origin: live_model|synthetic_control, page_ids: [...], stdout: str,
    returncode: int}. Strict JSON is validated again; an unvalidated result never
    supplies an observation. No subprocess/network path is reachable here.
    """
    import subprocess
    from time import monotonic
    from publication_interpreter import interpret_publications
    from publication_observation import validate_observation, build_observation, evaluate_publication
    from alpha_radar import filter_evidence
    from extraction_contract import strict_json_loads
    rows = dataset['rows']
    if dataset.get('version') != 1 or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('invalid_dataset')
    clocks = {k: datetime.fromisoformat(v.replace('Z', '+00:00'))
              for k, v in dataset['cohorts'].items()}
    if any(v.utcoffset() is None for v in clocks.values()):
        raise ValueError('invalid_clock')
    by_id = {r['id']: r for r in rows}
    raw, found, diagnostics = {}, {}, []
    results = results or {'origin':'none','page_ids':[],'stdout':''}
    if results['origin'] not in ('none', 'live_model', 'synthetic_control'):
        raise ValueError('invalid_origin')
    ids = results['page_ids']
    if len(ids) > 10 or len(ids) != len(set(ids)) or any(i not in by_id for i in ids):
        raise ValueError('invalid_results_binding')
    selected = [by_id[i] for i in ids]
    if results['origin'] == 'synthetic_control' and any(r['kind'] != 'synthetic' for r in selected):
        raise ValueError('synthetic_real_mix')
    if results['origin'] == 'live_model' and any(r['kind'] != 'real' for r in selected):
        raise ValueError('synthetic_real_mix')
    if selected:
        if len({r['cohort'] for r in selected}) != 1:
            raise ValueError('mixed_clock_batch')
        pages = [r['page'] for r in selected]
        # Retain duplicate/forged/unknown keys in the raw capture; count a unique
        # correctly-bound proposal only, never let duplicate IDs win last-write.
        try:
            payload = strict_json_loads(results['stdout'])
            members = payload['results']
            counts = Counter(r.get('id') for r in members if isinstance(r, dict) and isinstance(r.get('id'), str))
            for i, row in enumerate(selected):
                matches = [r for r in members if isinstance(r, dict) and r.get('id') == f'p{i}']
                if counts[f'p{i}'] == 1 and matches and 'value' in matches[0]:
                    raw[row['id']] = matches[0]
        except (ValueError, KeyError, TypeError):
            pass
        def replay(command, *, input, deadline):
            return subprocess.CompletedProcess(command, results.get('returncode', 0), results['stdout'], b'')
        observations, diagnostics = interpret_publications(pages, deadline=monotonic()+90,
            command_factory=lambda:['offline-replay'], runner=replay,
            now=clocks[selected[0]['cohort']])
        found = {r['id']: observations[r['url']] for r in selected if r['url'] in observations}
    baseline, standard, hybrid = {}, {}, {}
    accepted = {stage:set() for stage in ('baseline', 'standard', 'hybrid')}
    decisions = []
    for row in rows:
        if row.get('fetch_error') or row.get('parsing_error'):
            continue
        page = row['page']; id = row['id']; now = clocks[row['cohort']]
        if row.get('legacy'):
            baseline[id] = row['legacy']
        o = page.get('publication_observation')
        if validate_observation(page, o):
            standard[id] = o
        elif 'publication_observation' not in page and row.get('legacy'):
            standard[id] = row['legacy']
        observation = found.get(id)
        updated = {**page, 'publication_observation':observation} if observation else page
        hybrid[id] = observation or standard.get(id)
        # Baseline filter uses actual legacy value as captured, including any
        # historical midnight convention; scorer NEVER manufactures one.
        legacy_page = {k:v for k,v in page.items() if k != 'publication_observation'}
        legacy_page['published_at'] = (row.get('legacy') or {}).get('original_value')
        stage_decisions = {}
        for stage, candidate in [('baseline', legacy_page), ('standard', page), ('hybrid', updated)]:
            ok, why = filter_evidence([candidate], now=now)
            if ok:
                accepted[stage].add(id)
            stage_decisions[stage] = {'accepted':bool(ok),'reasons':[x['reason'] for x in why]}
        decisions.append({'id':id, **stage_decisions})
    scored = {name:score_claims(rows, claims, accepted_ids=accepted[name])
              for name, claims in [('baseline',baseline), ('standard',standard), ('hybrid',hybrid)]}
    scored['raw'] = score_claims(selected, raw, accepted_ids=set())
    scored['model_evaluated'] = {k:sum(r['kind']==k for r in selected) for k in ('real','synthetic')}
    grounded, expired = {}, set()
    for row in selected:
        proposal = raw.get(row['id'], {})
        if (set(proposal) == {'id','value','precision','support','location'}
                and 'publication_observation' not in row['page']):
            candidate = build_observation(row['page'], value=proposal['value'], precision=proposal['precision'],
                support=proposal['support'], location=proposal['location'], basis='llm_grounded')
            if candidate:
                grounded[row['id']] = candidate
                valid, reason = evaluate_publication({**row['page'],'publication_observation':candidate},
                    now=clocks[row['cohort']])
                if not valid:
                    expired.add(row['id'])
    scored['grounded_recovery'] = {k:sum(r['kind']==k and same_claim(grounded.get(r['id']),r.get('label'))
        for r in selected) for k in ('real','synthetic')}
    scored['freshness_rejection'] = {k:sum(r['kind']==k and r['id'] in expired
        for r in selected) for k in ('real','synthetic')}
    scored['validator_induced_rejection'] = {k:sum(r['kind']==k and same_claim(raw.get(r['id']),r.get('label'))
        and r['id'] not in found and r['id'] not in expired for r in selected) for k in ('real','synthetic')}
    scored['grounded_observations'] = grounded
    scored.update(origin=results['origin'], diagnostics=diagnostics, decisions=decisions,
                  raw_proposals=raw, validated_observations=found)
    return scored


def private_json(path, value, *, exclusive=False):
    """Create private parents/files; never follow a final-component symlink."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.stat().st_mode & 0o077:
        raise ValueError('insecure_artifact_directory')
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
    flags |= os.O_EXCL if exclusive else os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'w') as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write('\n')


def admit(dataset, *, deadline=None):
    """Diagnostic-only bundles, never real candidates or source qualification.

    At most five synthetic *group identifiers* each bind up to five real URLs;
    no event, trading symbol, source receipt or publish decision is manufactured.
    The actual reviewed coordinator and transport enforce refusal and caps.
    """
    from alpha_radar import publisher_domain, filter_evidence
    from publication_recovery import choose_recovery_pages
    from publication_interpreter import _prepare_request
    rows = [r for r in dataset['rows'] if r['kind'] == 'real'
            and not r.get('fetch_error') and not r.get('parsing_error')]
    pages = [r['page'] for r in rows]
    groups = [{'symbol':f'DIAGNOSTIC_{i//5}', 'urls':[r['url'] for r in rows[i:i+5]]}
              for i in range(0, min(len(rows),25),5)]
    chosen = choose_recovery_pages(groups, pages, [], publisher=publisher_domain,
                                  filter_pages=filter_evidence, deadline=deadline)
    reasons = {}
    admitted, _ = _prepare_request(chosen, reasons)
    # Stable transport admission may skip a long page; compact only whole pages,
    # preserving original contents, URL and hash witnesses, not truncating them.
    admitted_urls = {p['url'] for p in admitted.values()}
    selected = [r for page in chosen for r in rows if r['url']==page['url'] and r['url'] in admitted_urls]
    _, request = _prepare_request([r['page'] for r in selected], {})
    return selected, reasons, request


def validate_freeze(dataset, freeze, raw):
    """Refuse live use before independent corpus/label freeze and coverage."""
    from alpha_radar import publisher_domain
    if freeze.get('dataset_sha256') != hashlib.sha256(raw).hexdigest():
        raise ValueError('dataset_not_frozen')
    rows = [r for r in dataset['rows'] if r['kind']=='real' and not r.get('fetch_error')
            and not r.get('parsing_error') and 'page' in r]
    if (len({r['url'] for r in rows}) < 20 or len({r['event'] for r in rows}) < 20
            or len({publisher_domain(r['url']) for r in rows}) < 8
            or not {'issuer/official','wire','independent reporting'} <= {r['class'] for r in rows}
            or freeze.get('spike_disjoint') is not True
            or any('label' not in r or not r.get('label_rationale') or not r.get('label_witness') for r in rows)):
        raise ValueError('corpus_coverage_incomplete')
    for row in rows:
        if freeze['captures'].get(row['id']) != row['capture_sha256']:
            raise ValueError('capture_freeze_mismatch')


def run_live(dataset_path, output):
    """Explicit single bounded diagnostic. Record exists even after abort/failure.

    Reviewed supervisor discards stderr. A read-only tap captures the very same
    bounded pipes, without replacing transport, validation, timeout or cleanup.
    No provider/model override, retries, fresh fetches, or research entrypoint.
    """
    from time import monotonic
    import subprocess
    from unittest.mock import patch
    started = monotonic()
    deadline = started + 90
    dataset_path = Path(dataset_path)
    output = Path(output)
    record_path = dataset_path.with_name(dataset_path.name+'.invocation.json')
    record = {'status':'started','started_at':datetime.now().astimezone().isoformat(),
              'wall_cap_seconds':90,'max_invocations':1,'launches':0}
    private_json(record_path, record, exclusive=True)
    stdout, stderr = bytearray(), bytearray()
    process = None
    selected = []
    try:
        raw_dataset = dataset_path.read_bytes()
        sha = hashlib.sha256(raw_dataset).hexdigest()
        freeze = json.loads(dataset_path.with_name(dataset_path.name+'.freeze.json').read_text())
        dataset = json.loads(raw_dataset)
        validate_freeze(dataset, freeze, raw_dataset)
        selected, reasons, request = admit(dataset, deadline=deadline)
        record.update(dataset_sha256=sha, page_ids=[r['id'] for r in selected],
                      admission_reasons=reasons, input_bytes=len(request))
        if not selected:
            record['status'] = 'no_eligible_pages'
            return record
        if len({r['cohort'] for r in selected}) != 1:
            raise ValueError('mixed_clock_batch')
        from alpha_radar import research_subprocess_command
        from publication_interpreter import interpret_publications, run_publication_process
        real_popen, real_read = subprocess.Popen, os.read
        streams = {}
        def tapped_popen(*args, **kwargs):
            nonlocal process
            record['launches'] += 1
            if record['launches'] != 1 or monotonic() >= deadline:
                raise OSError('launch_refused')
            process = real_popen(*args, **kwargs)
            streams.update({process.stdout.fileno():stdout, process.stderr.fileno():stderr})
            return process
        def tapped_read(fd, size):
            chunk = real_read(fd, size)
            if fd in streams:
                streams[fd].extend(chunk)
            return chunk
        def command_factory():
            command = research_subprocess_command('bot_room', max_turns=1, run_budget=45)
            record['command'] = command
            record['provider'] = command[command.index('--provider')+1]
            record['model'] = command[command.index('-m')+1]
            return command
        def runner(command, *, input, deadline):
            # Private canonical prompt contains no labels; request is the exact
            # reviewed adapter output, not the diagnostic score representation.
            private_json(output/'request.json',json.loads(input),exclusive=True)
            with patch('subprocess.Popen',tapped_popen), patch('os.read',tapped_read):
                return run_publication_process(command,input=input,deadline=deadline)
        observations, diagnostics = interpret_publications([r['page'] for r in selected],
            deadline=deadline, command_factory=command_factory, runner=runner,
            now=datetime.fromisoformat(dataset['cohorts'][selected[0]['cohort']].replace('Z','+00:00')))
        record.update(status='completed', diagnostics=diagnostics,
                      validated_observations=observations)
        return record
    except Exception:
        record['status'] = 'probe_failed'
        raise
    finally:
        record.update(elapsed_seconds=monotonic()-started,
                      returncode=process.returncode if process else None,
                      usage='not_inferred; inspect private raw output/session records',
                      session='not_inferred; no session ID asserted')
        output.mkdir(parents=True,exist_ok=True,mode=0o700)
        for name, data in [('model.stdout',stdout),('model.stderr',stderr)]:
            path=output/name
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as handle:
                handle.write(data)
        private_json(output/'results.json',{'origin':'live_model','page_ids':[r['id'] for r in selected],
            'stdout':stdout.decode('utf-8','replace'),'returncode':record['returncode']},exclusive=True)
        private_json(record_path,record)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in ('run','score'):
        args.insert(0,'score')
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='mode',required=True)
    score=sub.add_parser('score',help='offline only (default)')
    score.add_argument('--dataset',required=True)
    score.add_argument('--results',required=True,help='private score output')
    score.add_argument('--proposals',help='private captured results.json to replay offline')
    live=sub.add_parser('run',help='explicit one-shot live model diagnostic')
    live.add_argument('--dataset',required=True)
    live.add_argument('--output',required=True)
    opts=parser.parse_args(args)
    try:
        if opts.mode == 'run':
            run_live(opts.dataset,opts.output)
        else:
            data=json.loads(Path(opts.dataset).read_text())
            proposals=json.loads(Path(opts.proposals).read_text()) if opts.proposals else None
            private_json(opts.results,evaluate(data,proposals),exclusive=True)
        return 0
    except Exception:
        print('publication_probe_refused',file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
