"""Bounded research alternatives; all I/O uses fixtures or temporary roots."""
import argparse
import contextlib
import datetime as dt
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import alpha_radar as radar


class CandidateAlternativesTests(unittest.TestCase):
    @contextlib.contextmanager
    def research_fixture(self, responses, symbols=('AAA','BBB','CCC','DDD','EEE')):
        now=dt.datetime.now(dt.timezone.utc)
        candidates=[{'symbol':s,'catalyst':'dated change','event_date':now.date().isoformat(),
                     'urls':[f'https://one.example/{s}']} for s in symbols]
        focused={s:[f'https://two.example/{s}'] for s in symbols}
        pages=[{'url':f'https://{domain}.example/{s}','title':'Verified article',
                'published_at':now.isoformat(),'text':'Substantive earnings and cash flow evidence. '*20}
               for s in symbols for domain in ('one','two')]
        def response(value):
            return subprocess.CompletedProcess([],0,json.dumps(value),'')
        with tempfile.TemporaryDirectory() as td, contextlib.ExitStack() as stack:
            root=Path(td)
            cfg={'min_price_usd':1,'max_position_usd':500,'focused_retrieval_enabled':True}
            (root/'autonomy_config.json').write_text(json.dumps(cfg))
            stack.enter_context(patch.object(radar,'ROOT',root))
            stack.enter_context(patch.object(radar,'reusable_fresh_candidate',return_value=None))
            stack.enter_context(patch.object(radar,'fresh_verified_candidate',return_value=None))
            stack.enter_context(patch.object(radar,'focused_retrieval',return_value=focused))
            stack.enter_context(patch.object(radar,'resolve_candidate_earnings',side_effect=lambda c,**kw:c))
            market=stack.enter_context(patch.object(radar,'synchronized_completed_close_prices',return_value={'price':100,'spy_price':500}))
            fetch=stack.enter_context(patch.object(radar,'gather_evidence',return_value=pages))
            calls=stack.enter_context(patch.object(radar.subprocess,'run',side_effect=[response({'candidates':candidates})]+[response(r) if isinstance(r,dict) else r for r in responses]))
            yield cfg, root, calls, fetch, market

    def candidate(self,symbol='BBB',**changes):
        now=dt.datetime.now(dt.timezone.utc)
        return dict({'symbol':symbol,'instrument_type':'cash_equity','setup_type':'event_momentum',
                     'planned_exit_at':(now+dt.timedelta(days=10)).isoformat(),
                     'earnings_event_at':(now-dt.timedelta(days=1)).date().isoformat(),
                     'horizon_rationale':'Post event follow-through','sources':[{'url':f'https://{d}.example/{symbol}'} for d in ('one','two')]},**changes)

    def test_none_advances_to_second_candidate_and_persists_once(self):
        with self.research_fixture([{'status':'none','none_reason':'no_fresh_setup'},self.candidate()]) as (_,root,calls,fetch,market):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                rc=radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
            self.assertEqual(output.getvalue().strip(),'DECISION candidate_qualified BBB')
            self.assertEqual(rc,0)
            rows=[json.loads(line) for line in (root/'candidates.jsonl').read_text().splitlines()]
            self.assertEqual([r['symbol'] for r in rows],['BBB'])
            self.assertEqual(calls.call_count,3)
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(market.call_count,1)

    def test_preflight_rejection_advances_to_qualified_alternative(self):
        with self.research_fixture([self.candidate('AAA',earnings_event_at=None),self.candidate()]) as (_,root,calls,_,market):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                rc=radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
            self.assertEqual((rc,output.getvalue().strip()),(0,'DECISION candidate_qualified BBB'))
            self.assertEqual(calls.call_count,3)
            self.assertEqual(len((root/'candidates.jsonl').read_text().splitlines()),1)

    def test_at_most_three_distinct_symbols_are_attempted(self):
        none={'status':'none','none_reason':'no_fresh_setup'}
        with self.research_fixture([none]*5,symbols=('AAA','AAA','BBB','CCC','DDD')) as (cfg,_,calls,fetch,_):
            result=radar.live_research(cfg)
            self.assertEqual(result['status'],'none')
            self.assertEqual(calls.call_count,4)
            prompts=[c.kwargs['input'] for c in calls.call_args_list[1:]]
            self.assertEqual([p.split('SELECTED SYMBOL: ')[1].split('.')[0] for p in prompts],['AAA','BBB','CCC'])
            fetch.assert_called_once()

    def test_alternatives_share_one_monotonic_120_second_budget(self):
        none={'status':'none','none_reason':'no_fresh_setup'}
        with self.research_fixture([none]*3) as (cfg,_,calls,_,_), patch.object(radar,'monotonic',create=True,side_effect=[100,100,145,190]):
            radar.live_research(cfg)
            self.assertEqual([c.kwargs['timeout'] for c in calls.call_args_list[1:]],[120,75,30])

    def test_exhausted_budget_never_starts_another_subprocess(self):
        none={'status':'none','none_reason':'no_fresh_setup'}
        with self.research_fixture([none]*3) as (cfg,_,calls,_,_), patch.object(radar,'monotonic',create=True,side_effect=[100,100,220,230]):
            with self.assertRaises(radar.ResearchFailure) as caught:
                radar.live_research(cfg)
            self.assertEqual(caught.exception.code,'research_synthesis_timeout')
            self.assertEqual(calls.call_count,2)

    def test_market_persistence_fault_is_never_renamed_or_reused(self):
        with self.research_fixture([self.candidate('AAA'),self.candidate()]) as (_,root,calls,_,market), patch.object(radar,'fresh_verified_candidate',return_value={'symbol':'OLD'}) as reuse:
            market.side_effect=radar.DurableAppendError('private persistence fault')
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                rc=radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
            self.assertEqual((rc,output.getvalue().strip()),(3,'SYSTEM_FAILURE research_persistence_failure'))
            self.assertEqual(calls.call_count,2)
            reuse.assert_not_called()
            self.assertFalse((root/'candidates.jsonl').exists())

    def test_symbol_local_market_failure_advances_but_provider_fault_stops(self):
        with self.research_fixture([self.candidate('AAA'),self.candidate()]) as (_,root,calls,_,market):
            market.side_effect=[ValueError('invalid_symbol'),{'price':100,'spy_price':500}]
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                rc=radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
            self.assertEqual((rc,output.getvalue().strip()),(0,'DECISION candidate_qualified BBB'))
            self.assertEqual(calls.call_count,3)

    def run_main(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            rc=radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        return rc,output.getvalue().strip()

    def test_qualification_and_receipt_rejections_reach_third_candidate(self):
        bad_receipts=self.candidate('BBB',sources=[{'url':'https://invented.example/a'},{'url':'https://invented-other.example/b'}],
                                    _source_receipts=[{'url':'https://invented.example/a'}])
        with self.research_fixture([self.candidate('AAA',instrument_type='etf'),bad_receipts,self.candidate('CCC')]) as (_,root,calls,fetch,_), patch.object(radar,'ranked_candidate_evidence',wraps=radar.ranked_candidate_evidence) as rank:
            self.assertEqual(self.run_main(),(0,'DECISION candidate_qualified CCC'))
            self.assertEqual(calls.call_count,4)
            rank.assert_called_once();fetch.assert_called_once()
            rows=[json.loads(line) for line in (root/'candidates.jsonl').read_text().splitlines()]
            self.assertEqual([r['symbol'] for r in rows],['CCC'])
            self.assertNotIn('_source_receipts',rows[0])

    def test_first_success_runs_each_intake_gate_and_append_once(self):
        with self.research_fixture([self.candidate('AAA')]) as (_,root,calls,_,_), contextlib.ExitStack() as stack:
            checks=[stack.enter_context(patch.object(radar,name,wraps=getattr(radar,name))) for name in ('candidate_preflight','qualified','source_verification_result','append')]
            self.assertEqual(self.run_main(),(0,'DECISION candidate_qualified AAA'))
            for check in checks:check.assert_called_once()
            self.assertEqual(calls.call_count,2)

    def test_global_synthesis_faults_stop_without_candidate_or_new_discovery(self):
        failures=[(subprocess.TimeoutExpired('synthesis',120),'research_synthesis_timeout'),
                  (subprocess.CompletedProcess([],1,'','private provider error'),'research_synthesis_unavailable'),
                  (subprocess.CompletedProcess([],0,'not JSON',''),'research_parse_failure')]
        for fault,reason in failures:
            with self.subTest(reason=reason), self.research_fixture([fault,self.candidate()]) as (_,root,calls,fetch,market):
                self.assertEqual(self.run_main(),(3,'SYSTEM_FAILURE '+reason))
                self.assertEqual(calls.call_count,2);fetch.assert_called_once();market.assert_not_called()
                self.assertFalse((root/'candidates.jsonl').exists())

    def test_global_market_faults_stop_without_alternatives(self):
        for fault in (RuntimeError('massive_credentials_unavailable'),RuntimeError('massive_synchronized_prices_unavailable'),ValueError('unrecognized adapter failure'),OSError('network unavailable')):
            with self.subTest(fault=type(fault)), self.research_fixture([self.candidate('AAA'),self.candidate()]) as (_,root,calls,_,market):
                market.side_effect=fault
                self.assertEqual(self.run_main(),(3,'SYSTEM_FAILURE research_market_data_unavailable'))
                self.assertEqual(calls.call_count,2)
                self.assertFalse((root/'candidates.jsonl').exists())

    def test_earnings_persistence_fault_stops_without_fallback(self):
        with self.research_fixture([self.candidate('AAA'),self.candidate()]) as (_,root,calls,_,market), patch.object(radar,'resolve_candidate_earnings',side_effect=radar.DurableAppendError('private')):
            self.assertEqual(self.run_main(),(3,'SYSTEM_FAILURE research_persistence_failure'))
            self.assertEqual(calls.call_count,2);market.assert_not_called()
            self.assertFalse((root/'candidates.jsonl').exists())

    def test_candidate_append_failure_is_never_retried(self):
        with self.research_fixture([self.candidate('AAA'),self.candidate()]) as (_,root,calls,_,_), patch.object(radar,'append',side_effect=radar.DurableAppendError('private')) as append:
            self.assertEqual(self.run_main(),(3,'SYSTEM_FAILURE research_persistence_failure'))
            self.assertEqual(calls.call_count,2);append.assert_called_once()

    def test_exhaustion_preserves_single_attempt_downstream_blocker(self):
        cases=[(self.candidate('AAA',earnings_event_at=None),(2,'BLOCKER earnings_unknown')),
               (self.candidate('AAA',instrument_type='etf'),(2,'BLOCKER candidate_failed_qualification')),
               (self.candidate('AAA',sources=[{'url':'https://invented.example/a'},{'url':'https://other.example/b'}]),(3,'SYSTEM_FAILURE research_source_verification_failed')),
               ({'status':'none','none_reason':'no_fresh_setup'},(0,'DECISION skipped no_fresh_setup'))]
        for candidate,expected in cases:
            with self.subTest(expected=expected), self.research_fixture([candidate],symbols=('AAA',)) as (_,root,calls,_,_):
                self.assertEqual(self.run_main(),expected)
                self.assertEqual(calls.call_count,2)
                self.assertFalse((root/'candidates.jsonl').exists())

    def test_dry_fixture_uses_shared_intake_without_receipt_or_model_call(self):
        with self.research_fixture([]) as (_,root,calls,_,_), patch.object(radar,'source_verification_result') as verify:
            (root/'fixtures').mkdir()
            (root/'fixtures'/'candidate.json').write_text(json.dumps(self.candidate('AAA',price=100,spy_price=500)))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(radar.main_with_args(argparse.Namespace(dry_run_fixture=True)),0)
            calls.assert_not_called();verify.assert_not_called()
            self.assertEqual(len((root/'candidates.jsonl').read_text().splitlines()),1)

    def test_direct_live_research_also_returns_only_fully_qualified_candidate(self):
        with self.research_fixture([self.candidate('AAA',earnings_event_at=None),self.candidate()]) as (cfg,root,calls,_,_):
            candidate=radar.live_research(cfg)
            self.assertEqual(candidate['symbol'],'BBB')
            self.assertEqual(calls.call_count,3)
            self.assertFalse((root/'candidates.jsonl').exists())

    def test_discovery_parser_defaults_share_the_five_url_budget(self):
        raw={'candidates':[{'symbol':'AAA','event_date':'2026-09-15','catalyst':'dated event',
                            'urls':[f'https://source{i}.example/a' for i in range(6)]}]}
        text=json.dumps(raw)
        self.assertEqual(radar.extract_scout_candidates(text),[])
        self.assertEqual(radar.scout_parse_result(text)[0],[])

    def test_focused_provider_failure_stops_before_rescue_or_fetch(self):
        with self.research_fixture([]) as (_,root,calls,fetch,_), patch.object(radar,'rescue_candidate_bundle') as rescue:
            # Exercise the real focused stage rather than the fixture's URL map.
            with patch.object(radar,'focused_retrieval',side_effect=self.real_focused_retrieval):
                calls.side_effect=[subprocess.CompletedProcess([],0,json.dumps({'candidates':[{'symbol':'AAA','event_date':'2026-09-15','catalyst':'dated event','urls':['https://one.example/AAA']}]}),''),
                                   subprocess.CompletedProcess([],1,'','private provider error')]
                self.assertEqual(self.run_main(),(3,'SYSTEM_FAILURE research_focused_retrieval_unavailable'))
            self.assertEqual(calls.call_count,2);rescue.assert_not_called();fetch.assert_not_called()

    def test_focused_timeout_or_io_fault_is_not_a_thin_candidate(self):
        for fault,reason in [(subprocess.TimeoutExpired('focused',240),'research_focused_retrieval_timeout'),
                             (OSError('private'),'research_focused_retrieval_unavailable'),
                             (radar.DurableAppendError('private'),'research_persistence_failure')]:
            with self.subTest(reason=reason), self.research_fixture([]) as (_,root,calls,fetch,_), patch.object(radar,'rescue_candidate_bundle') as rescue, patch.object(radar,'focused_retrieval',side_effect=self.real_focused_retrieval):
                calls.side_effect=[subprocess.CompletedProcess([],0,json.dumps({'candidates':[{'symbol':'AAA','event_date':'2026-09-15','catalyst':'dated event','urls':['https://one.example/AAA']}]}),''),fault]
                self.assertEqual(self.run_main(),(3,'SYSTEM_FAILURE '+reason))
                self.assertEqual(calls.call_count,2);rescue.assert_not_called();fetch.assert_not_called()

    real_focused_retrieval=staticmethod(radar.focused_retrieval)

    def test_malformed_candidate_sources_advance_without_market_lookup(self):
        with self.research_fixture([self.candidate('AAA',sources=None),self.candidate()]) as (_,root,calls,_,market):
            self.assertEqual(self.run_main(),(0,'DECISION candidate_qualified BBB'))
            self.assertEqual(calls.call_count,3)
            market.assert_called_once_with('BBB')

    def test_five_discovery_candidates_reach_focused_retrieval(self):
        candidates=[{'symbol':s,'catalyst':'dated change','event_date':'2026-09-15',
                     'urls':[f'https://{s.lower()}.example/story']} for s in ('AAA','BBB','CCC','DDD','EEE','FFF')]
        parsed, diagnostic=radar.scout_parse_result(json.dumps({'candidates':candidates}))
        self.assertEqual(len(parsed),5)
        self.assertEqual(diagnostic['parsed_candidate_count'],5)
        self.assertEqual(diagnostic['raw_candidate_count'],6)
        targets=json.loads(radar.focused_retrieval_prompt(parsed).split('TARGETS:\n')[1])
        self.assertEqual(len(targets),5)
        output={'candidates':[{'symbol':c['symbol'],'urls':[f'https://{d}.example/{c["symbol"]}' for d in ('one','two','three','four')]} for c in parsed]}
        focused=radar.parse_focused_retrieval(json.dumps(output),{c['symbol'] for c in parsed})
        self.assertEqual([len(focused[c['symbol']]) for c in parsed],[3]*5)
        self.assertIn('up to five',radar.discovery_prompt({'max_position_usd':500}))
        self.assertIn('up to fifteen URLs total',radar.focused_retrieval_prompt(parsed))
