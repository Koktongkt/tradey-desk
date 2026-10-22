#!/usr/bin/env python3
"""Offline structural replay. No new search, selector inference or live mode."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from discovery_collection import _project
from discovery_selection import admit_selection


def _json(path):return json.loads(Path(path).read_text())

def _lines(path):
    with Path(path).open() as f:
        for line in f:
            if line.strip():yield json.loads(line)


def evaluate(inventory:Path,results:Path,labels:Path)->dict:
    results=Path(results);labels=_json(labels);expected=labels['expected']
    for name,h in labels['hashes'].items():
        p=results/name
        if p.parent!=results or hashlib.sha256(p.read_bytes()).hexdigest()!=h:raise ValueError('frozen input hash mismatch')
    if hashlib.sha256(Path(inventory).read_bytes()).hexdigest()!=labels['hashes']['discovery-inventory.json']:raise ValueError('inventory hash mismatch')
    inv=[x for x in _json(inventory) if x.get('six_lane_instruction') is True]
    sessions=_json(results/'outcome-sessions.json');ids={x['id'] for x in sessions}
    if ids!={x['id'] for x in inv} or len(sessions)!=len(ids):raise ValueError('session identity mismatch')
    calls=list(_lines(results/'audited-search-calls.jsonl'));rows=list(_lines(results/'audited-search-records.jsonl'))
    production=[x for x in sessions if x['context'].startswith('production_')]
    counts={'sessions':len(sessions),'production_sessions':len(production),'diagnostic_sessions':len(sessions)-len(production),'calls':len(calls),'records':len(rows)}
    if any(counts[k]!=expected[k] for k in ('sessions','production_sessions','calls','records')):raise ValueError('frozen count mismatch')
    by_session=defaultdict(list)
    for call in calls:
        if call['session_id'] not in ids or call['missing_return'] or not call['result_parsed']:raise ValueError('missing receipt')
        by_session[call['session_id']].append(call)
    replay=[];reasons=Counter();admitted=0;current_admitted=0;raw_count=0;old_admitted=0
    for session in sessions:
        now=dt.datetime.fromisoformat(session['utc']);collected=[]
        for call in sorted(by_session[session['id']],key=lambda x:x['call_index'])[:6]:
            request={'lane':call['audited_lane'],'query':call['arguments']['query']}
            collected.append(_project(request,json.dumps(call['raw_result'],ensure_ascii=False)))
        collection={'version':1,'lanes':collected,'coverage_complete':all(x['status']=='ok' for x in collected),
                    'event_cutoff':session.get('event_floor') or dt.date.min.isoformat()}
        # Preserve the historical cohort's actual event gate for like-for-like
        # handoff replay. A separate diagnostic applies today's seven-day rule.
        source={r['url']:r for lane in collected for r in lane['records']};proposals=[];unbound=[]
        raw=session['raw_candidates'];raw_count+=len(raw);old_admitted+=sum(x['admitted_reconstructed'] for x in session['candidate_admissions'])
        if session['final_status']!='normal_final':
            outcomes=[{'symbol':r.get('symbol'),'reason':'historical_partial_scout'} for r in raw];reasons.update(x['reason'] for x in outcomes)
            replay.append({'session_id':session['id'],'context':session['context'],'raw':len(raw),'old_admitted':0,'new_admitted':0,'row_outcomes':outcomes,'selector_rerun':False});continue
        for i,row in enumerate(raw):
            url=(row.get('urls') or [None])[0];record=source.get(url)
            if record is None:unbound.append({'index':i,'reason':'record_not_admitted'});continue
            # Compatibility projection of OLD output only, not a new selector
            # decision or a claim that its catalyst/date is semantically true.
            support=(record['description'] or record['title'])[:160]
            proposals.append({'result_id':record['id'],'symbol':row.get('symbol'),'event_date':row.get('event_date'),'catalyst':row.get('catalyst'),'support':support,'event_status':'uncertain'})
        text=json.dumps({'candidates':proposals,'exclusions':[]},ensure_ascii=False)
        c,a=admit_selection(text,collection,now=now);admitted+=len(c)
        all_outcomes=a['row_outcomes']+unbound;reasons.update(x['reason'] for x in all_outcomes)
        current={**collection,'event_cutoff':(now.date()-dt.timedelta(days=7)).isoformat()}
        c2,_=admit_selection(text,current,now=now);current_admitted+=len(c2)
        replay.append({'session_id':session['id'],'context':session['context'],'raw':len(raw),'old_admitted':sum(x['admitted_reconstructed'] for x in session['candidate_admissions']),'new_admitted':len(c),'current_policy_admitted':len(c2),'historical_event_floor':session.get('event_floor'),'row_outcomes':all_outcomes,'coverage_complete':collection['coverage_complete'],'selector_rerun':False})
    summary=_json(results/'selection-summary.json')
    if raw_count!=expected['raw_candidates'] or sum(reasons.values())!=raw_count:raise ValueError('candidate accounting mismatch')
    outcome_map={'system_failure':'system_failure','zero_discovery':'zero_discovery','policy_or_qualification_rejection':'policy_or_qualification_rejection','qualified':'new_qualification','new_qualification':'new_qualification','policy_blocker':'policy_or_qualification_rejection'}
    prod_counts=Counter()
    for s in production:
        key=s['outcome']
        if key not in outcome_map:raise ValueError('unknown historical outcome')
        prod_counts[outcome_map[key]]+=1
    semantic=[{'session_id':x['session_id'],'symbol':x['symbol'],'historical_mismatch':x['mismatch'],'new_semantic_adjudication':'UNEXERCISED'} for x in summary['selected_event_state_mismatches']]
    original_urls={u for x in sessions if x['id']=='20261021_150030_6c8975' for c in x['raw_candidates'] for u in c.get('urls',[])}
    examples=[];seen_examples=set()
    for row in rows:
        if row['session_id']!='20261021_150030_6c8975':continue
        record=row['record'];title=record.get('title','').lower()
        symbol='IART' if 'integra' in title else 'TMO' if 'thermo fisher' in title else None
        if symbol and record['url'] not in seen_examples:
            seen_examples.add(record['url']);examples.append({'symbol':symbol,'url':record['url'],'selected_in_original_run':record['url'] in original_urls,'trade_eligibility_established':False})
    return {'version':1,'inventory':counts,'historical_production_outcomes':dict(prod_counts),
            'semantic_review_cases':semantic,'fresh_lead_omission_examples':examples,
            'handoff':{'raw_candidates':raw_count,'old_admitted':old_admitted,'new_structural_admitted':admitted,'current_policy_diagnostic_admitted':current_admitted,'new_row_reasons':dict(reasons),'silent_losses':0,
                       'known_overlength_cases':summary['schema_drops']['catalyst_length'],'known_event_state_cases':len(summary['selected_event_state_mismatches']),'known_index_cases':len(summary['selected_index_url_prompt_violations'])},
            'mode':'historical_output_structural_replay','selector_accuracy':'UNEXERCISED','live_coverage':'UNEXERCISED','new_final_qualified_candidates':None,'integration_status':'UNEXERCISED',
            'semantic_limit':'Legacy claims are replayed as unverified; matching snippets do not validate event state. Nine overlength cases remain explicit rejections, not recovered leads.',
            'sessions':replay,'input_hashes':labels['hashes']}


def _private_write(path:Path,obj):
    from discovery_history import _parent
    _parent(path)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(obj,f,ensure_ascii=False,indent=2)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('inventory','results','labels','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--integration-fixtures',type=Path)
    args=p.parse_args(argv);started=perf_counter()
    if 'test_artifacts' not in args.out.absolute().parts:raise ValueError('isolated test_artifacts output required')
    result=evaluate(args.inventory,args.results,args.labels)
    if args.integration_fixtures:
        from scripts.discovery_fixture_runner import run_cases
        result['integration_cases']=run_cases(_json(args.integration_fixtures),args.out)
        result['integration_status']='SYNTHETIC_FIXTURES_ONLY'
    sessions=result.pop('sessions');result['offline_elapsed_seconds']=perf_counter()-started
    args.out.mkdir(parents=True,exist_ok=True,mode=0o700);args.out.chmod(0o700)
    _private_write(args.out/'summary.json',result)
    path=args.out/'session-replay.jsonl';fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:
        for row in sessions:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(json.dumps({'status':'offline_evaluation_complete','inventory':result['inventory'],'handoff':result['handoff'],'integration_status':result['integration_status'],'live_coverage':'UNEXERCISED'}))
    return 0


if __name__=='__main__':raise SystemExit(main())
