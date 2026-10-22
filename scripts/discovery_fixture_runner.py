"""Offline whole-funnel fixtures. Called only by the disposable evaluator process."""
from __future__ import annotations
import contextlib
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def run_cases(spec,out):
    if not isinstance(spec,dict) or set(spec)!={'cases'} or spec['cases']!=['supported','earnings_block','missing_publisher']:raise ValueError('fixed integration cases required')
    out=Path(out).absolute();out.mkdir(parents=True,exist_ok=True,mode=0o700);out.chmod(0o700)
    if 'test_artifacts' not in out.parts:raise ValueError('isolated root required')
    roots=[ROOT]
    if ROOT.parent.name=='.worktrees':roots.append(ROOT.parent.parent)
    names={'candidates.jsonl','order_ledger.jsonl','reviews.jsonl','order_intents.jsonl','decision_audit.jsonl','trading_journal.sqlite3','source_cache.json'}
    def guard(event,args):
        if event in ('socket.connect','socket.getaddrinfo','socket.sendto','subprocess.Popen'):raise RuntimeError('offline fixture external operation blocked')
        if event not in ('open','sqlite3.connect'):return
        value=args[0]
        if not isinstance(value,(str,bytes,os.PathLike)):return
        raw=os.fsdecode(value)
        if raw==':memory:':return
        if raw.startswith('file:'):raw=raw[5:].split('?',1)[0]
        p=Path(raw).absolute()
        if p.is_relative_to(out):return
        if event=='sqlite3.connect' or p.name in names or any(p.is_relative_to(r/'private') for r in roots):raise RuntimeError('offline fixture operational access blocked')
    # This hook is deliberately process-lifetime. The CLI exits after the
    # evaluation; unit tests invoke integration only in a disposable child.
    sys.addaudithook(guard)
    import alpha_radar as r
    import discovery_pipeline as discovery
    result={}
    for case in spec['cases']:
        root=out/'integration'/case/'test_artifacts';root.mkdir(parents=True,exist_ok=True,mode=0o700)
        now=dt.datetime.now(dt.timezone.utc);date=now.date().isoformat()
        record={'id':'fixture-result','url':'https://a.example/article','title':'Company results','description':f'{date} company results','source_role':'unverified','legal_solicitation':False}
        collection={'version':1,'coverage_complete':True,'lanes':[{'lane':'issuer_ir','status':'ok','records':[record]}]}
        select=json.dumps({'candidates':[{'result_id':record['id'],'symbol':'ABC','event_date':date,'catalyst':'Reported company results','support':record['description'],'event_status':'announced'}],'exclusions':[]})
        urls=['https://a.example/article','https://b.example/article'][:1 if case=='missing_publisher' else 2]
        pages=[{'url':u,'title':'Company results','text':'Material company results and updated guidance. '*30,'published_at':now.isoformat()} for u in urls]
        model={'symbol':'ABC','instrument_type':'cash_equity','setup_type':'event_momentum','horizon_rationale':'Post-result repricing','planned_exit_at':(now+dt.timedelta(days=8)).isoformat(),'earnings_event_at':(now+dt.timedelta(days=0 if case=='earnings_block' else 50)).date().isoformat(),'earnings_date_status':'confirmed','thesis':'Fixture-supported operating development','catalyst':'Fixture results','sources':[{'url':u} for u in urls]}
        cfg={'discovery_v2_enabled':True,'min_price_usd':1,'max_position_usd':500,'focused_retrieval_enabled':True}
        with contextlib.ExitStack() as stack:
            for target,name,value in [(r,'ROOT',root),(r,'configured_default_model',lambda:('offline','offline'))]:stack.enter_context(patch.object(target,name,value))
            stack.enter_context(patch.object(discovery,'run_collection',return_value=collection))
            stack.enter_context(patch.object(discovery,'run_selector',return_value=subprocess.CompletedProcess([],0,select,'')))
            stack.enter_context(patch.object(r,'focused_retrieval',return_value={'ABC':urls}))
            stack.enter_context(patch.object(r,'gather_evidence',return_value=pages))
            stack.enter_context(patch.object(r,'post_fetch_rescue_candidate',return_value=[]))
            stack.enter_context(patch.object(r.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(model),'')))
            stack.enter_context(patch.object(r,'resolve_candidate_earnings',side_effect=lambda c,**kw:c))
            stack.enter_context(patch.object(r,'synchronized_completed_close_prices',return_value={'price':100.,'spy_price':500.}))
            try:
                candidate=r.live_research(cfg,intake=lambda c:r.prepare_candidate(c,cfg,ledger_path=root/'order_ledger.jsonl'))
                receipt_ok=r.verify_sources(candidate);qualified=r.qualified(candidate,cfg)
                if case!='supported' or not receipt_ok or not qualified:raise AssertionError('fixture gate bypass')
                path=root/'qualified-fixture.json';fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as f:json.dump(candidate,f)
                result[case]={'outcome':'qualified_fixture','receipts_verified':receipt_ok,'accepted_domains':len({r.publisher_domain(s['url']) for s in candidate['sources']}),'candidate_artifact':str(path.relative_to(out))}
            except r.CandidateRejection as error:
                if case!='earnings_block' or 'near_term_earnings' not in error.code:raise
                result[case]={'outcome':'policy_block','reason':error.code}
            except r.ResearchFailure as error:
                if case!='missing_publisher':raise
                result[case]={'outcome':'evidence_block','reason':error.code}
    for p in out.rglob('*'):
        if p.is_dir():p.chmod(0o700)
        elif p.is_file():p.chmod(0o600)
    return result
