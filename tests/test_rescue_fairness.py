"""Offline actual-orchestration rescue scheduling regressions.

Only transport/model boundaries are replaced. Filtering, rescue, ranking, synthesis
launch gates and diagnostics execute unchanged, with all streams under scratch.
"""
import datetime as dt
import json
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import alpha_radar as radar

NOW = dt.datetime(2026, 10, 18, 12, tzinfo=dt.timezone.utc)
BODY = 'The company disclosed a definitive supply agreement, committed volumes, financial terms and regulatory conditions. ' * 8

class ClockDate(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

def page(url, spec):
    return {'url':url, 'title':'Company agreement', 'text':'' if spec.get('empty_body') else BODY,
            'published_at': None if spec.get('undated') else ('2020-01-01T12:00:00Z' if spec.get('stale') else '2026-10-17T12:00:00Z')}

def replay(spec=None, ar=radar) -> dict:

    spec = spec or {}
    clock = [0.0]
    events, ready = [], []
    symbols = ['AAA','BBB','CCC','DDD','EEE'][:spec.get('count',2)]
    candidates = [{'symbol':s,'catalyst':s+' supply agreement','event_date':'2026-10-17',
                   'urls':['https://'+s.lower()+'.example/event']} for s in symbols]
    if spec.get('alternates'):
        candidates[0]['urls'] += ['https://a2.example/event','https://a3.example/event','https://a4.example/event']
    if spec.get('initial_pair'):
        candidates.insert(0, {'symbol':'ZZZ','catalyst':'ZZZ agreement','event_date':'2026-10-17',
                             'urls':['https://z.example/event','https://z2.example/event']})
    if spec.get('none'): candidates=[]
    def spend(kind, symbol, seconds, deadline, **fields):
        assert clock[0] < deadline, (kind, symbol, clock, deadline)
        start=clock[0]
        clock[0]+=min(seconds,deadline-start)
        events.append(dict(kind=kind,symbol=symbol,start=start,end=clock[0],deadline=deadline,**fields))
        return clock[0]-start >= seconds
    def run(cmd, **kw):
        if cmd==['discovery']:
            return subprocess.CompletedProcess(cmd,0,json.dumps({'candidates':candidates}),'')
        if cmd==['synthesis']:
            s=ready[-1]['symbol']
            spend('synthesis',s,spec.get('synth_cost',1) if s=='ZZZ' else 1,clock[0]+kw['timeout'])
            return subprocess.CompletedProcess(cmd,0,json.dumps({'status':'none','none_reason':'no_fresh_setup'}),'')
        assert cmd==['search']
        s=next(s for s in symbols if s in kw['input'])
        role='wire' if 'wire domains only' in kw['input'] else 'independent'
        ok=spend('search',s,30 if s=='AAA' and spec.get('slow',True) else 1,clock[0]+kw['timeout'],role=role)
        if not ok: raise subprocess.TimeoutExpired(cmd,kw['timeout'])
        if spec.get('provider_fault'): return subprocess.CompletedProcess(cmd,1,'','')
        url=('https://reuters.com/' if role=='independent' else 'https://businesswire.com/')+s
        return subprocess.CompletedProcess(cmd,0,json.dumps({'urls':[url]}),'')
    real_gateway=ar.gateway_rescue_url
    def gateway(*args,**kw): return real_gateway(*args,run=run,**kw)
    def sec(symbol, event_date, *, deadline, **kw):
        spend('lookup',symbol,30 if symbol=='AAA' and spec.get('slow',True) else 1,deadline)
        return None
    first=[True]
    def gather(urls, *, collection_deadline, diagnostics, **kw):
        for k in ('cache_path','attempt_path'): assert Path(kw[k]).is_relative_to(root)
        if first[0]:
            first[0]=False
            spend('initial','all',spec.get('initial_cost',10),collection_deadline)
            return [page(u,spec) for u in urls if not spec.get('no_evidence') and ('a2.' not in u and 'a3.' not in u and 'a4.' not in u)]
        assert len(urls)==1
        u=urls[0]
        s=next((s for s in symbols if s in u),'AAA')
        a=s=='AAA'
        cost=(10 if spec.get('a_sourceable') else 45) if a and spec.get('slow',True) else 1
        ok=spend('fetch',s,cost,collection_deadline,url=u)
        if not ok or spec.get('no_evidence') or (a and not spec.get('a_sourceable')) or (not a and spec.get('b_missing')):
            diagnostics.append({'url':u,'domain':ar.publisher_domain(u),'reason':'source_http_forbidden'})
            return []
        p=page(u,spec)
        if spec.get('mismatch'):p['url']='https://unbound.example/other'
        if spec.get('sibling'):p['url']=u # gateway domains remain exact bound; direct helper covers siblings
        return [p]
    real_synth=ar.synthesize_candidate
    def synth(cfg,selected,evidence,deadline,**kw):
        assert len({ar.publisher_domain(p['url']) for p in evidence})>=2
        assert all(p['url'] in selected['urls'] for p in evidence)
        assert len(ar.filter_evidence(evidence)[0])==len(evidence)
        ready.append({'symbol':selected['symbol'],'at':clock[0],'deadline':deadline})
        return real_synth(cfg,selected,evidence,deadline,**kw)
    with tempfile.TemporaryDirectory() as td, ExitStack() as st:
        root=Path(td)
        replacements={'ROOT':root,'monotonic':lambda:clock[0],'perf_counter':lambda:clock[0],
                      'discovery_command':lambda:['discovery'],'synthesis_command':lambda:['synthesis'],
                      'research_subprocess_command':lambda *a,**k:['search'],
                      'gather_evidence':gather,'sec_edgar_filing_url':sec,'gateway_rescue_url':gateway,
                      'synthesize_candidate':synth,'focused_retrieval':lambda rows,deadline:{r['symbol']:[] for r in rows}}
        for k,v in replacements.items():st.enter_context(patch.object(ar,k,v))
        st.enter_context(patch.object(ar.subprocess,'run',run))
        st.enter_context(patch.object(ar.dt,'datetime',ClockDate))
        try:
            result=ar.live_research({'max_position_usd':500,'focused_retrieval_enabled':bool(spec.get('alternates'))},intake=lambda _: (_ for _ in ()).throw(AssertionError('no intake')))
            outcome={'result':result}
        except ar.ResearchFailure as exc:outcome={'code':exc.code}
        diagnostics=[]
        for p in (root/'private').glob('research_diagnostics*'):
            if p.suffix=='.jsonl':diagnostics.extend(json.loads(line) for line in p.read_text().splitlines())
    return dict(spec=spec,events=events,ready=ready,elapsed=clock[0],outcome=outcome,diagnostics=diagnostics)

class RescueFairnessTests(unittest.TestCase):
    def test_extra_evidence_minute_can_complete_bundle_after_old_deadline(self):
        # Real orchestration must consume >120 seconds and still reach synthesis,
        # not merely expose a larger constant that is clipped by an old deadline.
        r=replay({'initial_cost':130,'slow':False})
        self.assertEqual(r['events'][0]['end'],130)
        self.assertIn('BBB',[x['symbol'] for x in r['ready']])
        self.assertTrue(all(e['deadline']==180 for e in r['events'] if e['kind'] in ('initial','lookup','fetch')))
        self.assertTrue(all(e['start']<e['deadline'] and e['end']<=e['deadline'] for e in r['events']))

    def test_starved_later_bundle_recovers_without_slicing_first(self):
        r=replay()
        self.assertIn('BBB',[x['symbol'] for x in r['ready']])
        operations=[(e['kind'],e['symbol']) for e in r['events'] if e['kind'] not in ('initial','synthesis')]
        self.assertEqual(operations[:4],[('lookup','AAA'),('lookup','BBB'),('search','AAA'),('search','BBB')])
        self.assertTrue(all(e['deadline']==180 for e in r['events'] if e['kind'] in ('lookup','fetch')))

    def test_slow_sourceable_first_is_not_lost_to_equal_share(self):
        for count in (2,3):
            with self.subTest(count=count):
                r=replay({'a_sourceable':True,'b_missing':True,'count':count})
                self.assertEqual([x['symbol'] for x in r['ready']],['AAA'])
                self.assertLess(r['elapsed'],180)
                self.assertEqual(sum(e['kind']=='search' and e['symbol']=='AAA' for e in r['events']),1)
                self.assertEqual(sum(e['kind']=='fetch' and e['symbol']=='AAA' for e in r['events']),1)

    def test_retained_alternate_and_search_to_fetch_resume_do_not_restart(self):
        for spec in ({},{'alternates':True},{'count':3}):
            with self.subTest(spec=spec):
                r=replay(spec)
                self.assertTrue(r['ready'])
                keys=[(e['kind'],e['symbol'],e.get('role'),e.get('url')) for e in r['events'] if e['kind'] in ('lookup','search','fetch')]
                self.assertEqual(len(keys),len(set(keys)))
                bsearch=next(e for e in r['events'] if e['kind']=='search' and e['symbol']=='BBB')
                bfetch=next(e for e in r['events'] if e['kind']=='fetch' and e['symbol']=='BBB')
                self.assertGreaterEqual(bfetch['start'],bsearch['end'])

    def test_three_distinct_admission_cap_and_deferred_cap(self):
        for initial in (False,True):
            r=replay({'count':4,'initial_pair':initial,'slow':False,'b_missing':True})
            admitted={e['symbol'] for e in r['events'] if e['kind']=='lookup'}
            self.assertEqual(admitted,{'AAA','BBB','CCC'})
            self.assertNotIn('DDD',admitted)

    def test_expired_and_short_windows_never_launch_after_deadline(self):
        for initial in (180,179,178,150):
            r=replay({'initial_cost':initial})
            for e in r['events']:
                self.assertLess(e['start'],e['deadline'])
            if initial==180:self.assertEqual([e['kind'] for e in r['events']],['initial'])
            self.assertFalse(r['ready'])

    def test_failure_controls_and_no_candidate(self):
        cases=[({'undated':True},'research_source_freshness_insufficient'),
               ({'stale':True},'research_source_freshness_insufficient'),
               ({'provider_fault':True},'research_source_retrieval_failed'),
               ({'empty_body':True},'research_source_retrieval_failed'),
               ({'no_evidence':True},'research_source_retrieval_failed'),
               ({'mismatch':True},'research_source_retrieval_failed')]
        for spec,code in cases:
            with self.subTest(spec=spec):
                r=replay(spec)
                self.assertFalse(r['ready'])
                self.assertEqual(r['outcome'],{'code':code})
        self.assertEqual(replay({'none':True})['outcome'],{'result':{'status':'none','none_reason':'no_fresh_setup'}})

    def test_deferred_synthesis_reserve_and_successful_fastpath(self):
        r=replay({'initial_pair':True,'synth_cost':50,'slow':False})
        self.assertEqual([x['symbol'] for x in r['ready']],['ZZZ','BBB'])
        self.assertEqual([x['deadline'] for x in r['ready']],[280,288])
        self.assertTrue(all(e['deadline']==180 for e in r['events'] if e['kind'] in ('lookup','fetch')))
        for cost in (180,270):
            r=replay({'initial_pair':True,'synth_cost':cost})
            self.assertEqual([e['kind'] for e in r['events']],['initial','synthesis'])
            self.assertEqual(r['outcome']['result']['status'],'none')

    def test_sec_fetch_and_official_date_are_separate_resumable_operations(self):
        url='https://www.sec.gov/Archives/edgar/data/123/000000012326000001/report.htm'
        candidate={'symbol':'AAA','event_date':'2026-10-17','urls':['https://issuer.example/news']}
        accepted=[page(candidate['urls'][0],{})]
        calls=[]
        def lookup(*a,**kw):calls.append('lookup');return url
        def fetch(*a,**kw):calls.append('fetch');return [page(url,{'undated':True})]
        def date(*a,**kw):calls.append('date');return '2026-10-17'
        with patch.object(radar,'monotonic',return_value=0), patch.object(radar.dt,'datetime',ClockDate), patch.object(radar,'sec_edgar_filing_url',side_effect=lookup), patch.object(radar,'gather_evidence',side_effect=fetch), patch.object(radar,'sec_filing_date_for_url',side_effect=date):
            state=iter(radar.post_fetch_rescue_candidate(candidate,accepted,diagnostics=[],deadline=120,resumable=True))
            self.assertEqual(len(next(state)),1)
            self.assertEqual(calls,['lookup'])
            self.assertEqual(len(next(state)),1)
            self.assertEqual(calls,['lookup','fetch'])
            self.assertEqual(len(next(state)),2)
            self.assertEqual(calls,['lookup','fetch','date'])
            with self.assertRaises(StopIteration):next(state)
        self.assertEqual(set(candidate),{'symbol','event_date','urls'})

    def test_pending_search_result_does_not_fetch_after_expiry(self):
        clock=[0]
        candidate={'symbol':'AAA','urls':['https://issuer.example/news']}
        with patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch.object(radar,'sec_edgar_filing_url',return_value=None) as sec, patch.object(radar,'gateway_rescue_url',return_value='https://reuters.com/AAA') as search, patch.object(radar,'gather_evidence',side_effect=AssertionError('late fetch')):
            state=iter(radar.post_fetch_rescue_candidate(candidate,[],diagnostics=[],deadline=120,resumable=True))
            next(state)
            next(state)
            clock[0]=120
            self.assertEqual(list(state),[])
            self.assertEqual(sec.call_count,1)
            self.assertEqual(search.call_count,1)

    def test_progress_projection_rejects_unbounded_or_non_ascii_counts(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'progress.jsonl'
            rows=[{'reason':'bundle_rescue_progress','candidate_token':'a'*16,'outcome':'completed','turns':v}
                  for v in ('²','9'*5000,'-1','1.0')]
            try:radar.record_research_diagnostics(rows,path=target)
            except ValueError:self.fail('malformed progress must be ignored, not break diagnostics')
            self.assertFalse(target.exists())

    def test_private_rescue_tokens_are_salted_per_run(self):
        first=replay(); second=replay()
        tokens=lambda r:{row['candidate_token'] for row in r['diagnostics'] if row.get('stage')=='evidence_rescue'}
        self.assertTrue(tokens(first))
        self.assertFalse(tokens(first) & tokens(second))

    def test_private_progress_is_bounded_and_opaque(self):
        r=replay()
        rows=[d for d in r['diagnostics'] if d.get('stage')=='evidence_rescue']
        self.assertEqual(len(rows),2)
        for row in rows:
            self.assertRegex(row['candidate_token'],r'^[0-9a-f]{16}$')
            self.assertGreater(row['turns'],0)
            self.assertIn(row['outcome'],('completed','deadline'))
            text=json.dumps(row)
            self.assertNotIn('AAA',text)
            self.assertNotIn('BBB',text)
            self.assertNotIn('https:',text)
            self.assertNotIn(BODY,text)

if __name__=='__main__':unittest.main()
