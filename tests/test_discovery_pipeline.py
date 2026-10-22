import contextlib
import datetime as dt
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from test_discovery_selection import collection,proposal,NOW


class PipelineTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('discovery_pipeline'),'pipeline implementation missing')
        import discovery_pipeline as m
        return m

    def invoke(self,m,root,*,result=None,runner=None,clock=None):
        row=collection() if result is None else result
        cm=patch.object(m,'run_collection',return_value=row)
        with cm:
            return m.discover({},now=NOW,deadline=(clock[0]+165 if clock else time.monotonic()+165),history_path=root/'private/history.json',artifact_dir=root/'private/runs',command_factory=lambda:['not-a-live-model'],selector_runner=runner or (lambda *a,**kw:subprocess.CompletedProcess([],0,proposal(),'')))

    def test_one_tool_free_selector_no_search_turns(self):
        m=self.api();calls=[]
        with tempfile.TemporaryDirectory() as d:
            c,a=self.invoke(m,Path(d),runner=lambda *args,**kw:(calls.append((args,kw)) or subprocess.CompletedProcess([],0,proposal(),'')))
            self.assertEqual(len(c),1);self.assertEqual(len(calls),1)
            self.assertIn('NO tools',calls[0][1]['input'].decode())
            self.assertEqual(len(list((Path(d)/'private/runs').glob('*.json'))),1)
            self.assertEqual(next((Path(d)/'private/runs').glob('*.json')).stat().st_mode&0o777,0o600)

    def test_shared_deadline_includes_preparation(self):
        m=self.api();clock=[100.0];calls=[]
        def prompt(*a,**kw):clock[0]=266;return 'late'
        with tempfile.TemporaryDirectory() as d,patch.object(m,'monotonic',side_effect=lambda:clock[0]),patch.object(m,'selector_prompt',side_effect=prompt):
            with self.assertRaises(m.DiscoveryFailure) as err:self.invoke(m,Path(d),clock=clock,runner=lambda *a,**kw:calls.append(1))
            self.assertEqual(err.exception.reason,'selector_timeout');self.assertEqual(calls,[])

    def test_partial_collection_explicit(self):
        m=self.api();x=collection();x['coverage_complete']=False
        with tempfile.TemporaryDirectory() as d:
            c,a=self.invoke(m,Path(d),result=x)
            self.assertEqual(len(c),1);self.assertFalse(a['coverage_complete'])
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(m.DiscoveryFailure) as err:self.invoke(m,Path(d),result={'version':1,'status':'error','reason':'timeout'})
            self.assertEqual(err.exception.reason,'collection_timeout')

    def test_incomplete_empty_selection_is_not_healthy_no_setup(self):
        m=self.api();x=collection();x['coverage_complete']=False
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(m.DiscoveryFailure) as err:
                self.invoke(m,Path(d),result=x,runner=lambda *a,**kw:subprocess.CompletedProcess([],0,'{"candidates":[],"exclusions":[]}',''))
            self.assertEqual(err.exception.reason,'collection_incomplete')

    def test_post_collection_preparation_expiry_never_launches_selector(self):
        m=self.api();clock=[100.0];calls=[]
        def collect(*a,**kw):clock[0]=266;return collection()
        with tempfile.TemporaryDirectory() as d,patch.object(m,'monotonic',side_effect=lambda:clock[0]),patch.object(m,'run_collection',side_effect=collect):
            with self.assertRaises(m.DiscoveryFailure):
                m.discover({},now=NOW,deadline=265,history_path=Path(d)/'history.json',artifact_dir=Path(d)/'runs',command_factory=lambda:['fake'],selector_runner=lambda *a,**kw:calls.append(1))
            self.assertEqual(calls,[])

    def test_no_silent_candidate_losses(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            c,a=self.invoke(m,Path(d),runner=lambda *a,**kw:subprocess.CompletedProcess([],0,proposal(catalyst='x'*501),''))
            self.assertEqual(c,[]);self.assertIn('catalyst_too_long',str(a['row_outcomes']))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(m.DiscoveryFailure) as err:self.invoke(m,Path(d),runner=lambda *a,**kw:subprocess.CompletedProcess([],2,'partial',''))
            self.assertEqual(err.exception.reason,'selector_unavailable')

    def test_selector_transport_accepts_64k_and_enforces_tools(self):
        m=self.api()
        import discovery_process
        with patch.object(discovery_process,'run_process',return_value=subprocess.CompletedProcess([],0,'{}','')) as run:
            m.run_selector(['fake','-t','bot_room','--max-turns','1'],input=b'x'*60000,deadline=time.monotonic()+2,cwd=Path.cwd())
            self.assertEqual(run.call_args.kwargs['max_input_bytes'],65536)
        with self.assertRaises(ValueError):m.run_selector(['fake','-t','search','--max-turns','2'],input=b'{}',deadline=time.monotonic()+2,cwd=Path.cwd())

    def test_legacy_default_unchanged(self):
        m=self.api();import alpha_radar as r
        with tempfile.TemporaryDirectory() as d,patch.object(r,'ROOT',Path(d)),patch.object(r,'configured_default_model',return_value=('fake','fake')),patch.object(r.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'{"candidates":[]}','')) as legacy,patch.object(m,'discover',side_effect=AssertionError('opt-in only')):
            self.assertEqual(r.live_research({'min_price_usd':1})['status'],'none')
            self.assertEqual(len(legacy.call_args_list),1)

    @contextlib.contextmanager
    def integrated(self,*,one_domain=False,earnings=False):
        m=self.api();import alpha_radar as r
        now=dt.datetime.now(dt.timezone.utc);date=now.date().isoformat()
        seed=collection(description=f'{date} company results');seed['lanes'][0]['records'][0]['url']='https://a.example/article'
        select=proposal(event_date=date,support=f'{date} company results')
        pages=[{'url':u,'title':'Company results','text':'Material company result and updated guidance. '*30,'published_at':now.isoformat()} for u in ['https://a.example/article','https://b.example/article'][:1 if one_domain else 2]]
        candidate={'symbol':'ABC','instrument_type':'cash_equity','setup_type':'event_momentum','horizon_rationale':'Post-result repricing','planned_exit_at':(now+dt.timedelta(days=8)).isoformat(),'earnings_event_at':(now+dt.timedelta(days=0 if earnings else 50)).date().isoformat(),'earnings_date_status':'confirmed','thesis':'A supported operating change','catalyst':'Results','sources':[{'url':p['url']} for p in pages]}
        cfg={'discovery_v2_enabled':True,'min_price_usd':1,'max_position_usd':500,'focused_retrieval_enabled':True}
        with tempfile.TemporaryDirectory() as d,contextlib.ExitStack() as stack:
            root=Path(d);stack.enter_context(patch.object(r,'ROOT',root))
            stack.enter_context(patch.object(r,'configured_default_model',return_value=('fake','fake')))
            stack.enter_context(patch.object(m,'run_collection',return_value=seed))
            stack.enter_context(patch.object(m,'run_selector',return_value=subprocess.CompletedProcess([],0,select,'')))
            stack.enter_context(patch.object(r,'focused_retrieval',return_value={'ABC':[p['url'] for p in pages]}))
            stack.enter_context(patch.object(r,'gather_evidence',return_value=pages))
            stack.enter_context(patch.object(r,'post_fetch_rescue_candidate',return_value=[]))
            stack.enter_context(patch.object(r.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(candidate),'')))
            stack.enter_context(patch.object(r,'resolve_candidate_earnings',side_effect=lambda c,**kw:c))
            stack.enter_context(patch.object(r,'synchronized_completed_close_prices',return_value={'price':100.,'spy_price':500.}))
            # The intake, preflight, qualification and receipt verifier below
            # are REAL. Only external acquisition/model/market responses mocked.
            yield r,cfg,root

    def test_two_publishers_reach_real_intake(self):
        self.api()
        with self.integrated() as (r,cfg,root):
            c=r.live_research(cfg,intake=lambda c:r.prepare_candidate(c,cfg,ledger_path=None))
            self.assertEqual(c['symbol'],'ABC');self.assertTrue(r.verify_sources(c));self.assertTrue(r.qualified(c,cfg))
            self.assertEqual(len(c['_source_receipts']),2)
            f=root/'qualified-fixture.json';f.write_text(json.dumps(c));self.assertTrue(f.exists())

    def test_policy_rejection_not_system_failure(self):
        self.api()
        with self.integrated(earnings=True) as (r,cfg,root):
            with self.assertRaises(r.CandidateRejection) as err:r.live_research(cfg,intake=lambda c:r.prepare_candidate(c,cfg,ledger_path=None))
            self.assertIn('near_term_earnings',err.exception.code)

    def test_missing_publisher_never_qualified(self):
        self.api()
        with self.integrated(one_domain=True) as (r,cfg,root):
            with self.assertRaises(r.ResearchFailure):r.live_research(cfg,intake=lambda c:r.prepare_candidate(c,cfg,ledger_path=None))
