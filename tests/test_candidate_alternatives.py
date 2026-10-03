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
            radar.configured_default_model.cache_clear()
            stack.callback(radar.configured_default_model.cache_clear)
            stack.enter_context(patch.object(radar,'load_configured_default_model',return_value=('fixture-provider','fixture-model')))
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

    def test_research_fixture_isolates_model_cache_without_process_launches(self):
        with patch.object(subprocess,'Popen',side_effect=AssertionError('REAL_PROCESS_BOUNDARY_BLOCKED')) as launch:
            for warm in (False,True):
                with self.subTest(warm=warm):
                    radar.configured_default_model.cache_clear()
                    if warm:
                        with patch.object(radar,'load_configured_default_model',return_value=('other-provider','other-model')):
                            radar.configured_default_model()
                    with self.assertRaisesRegex(RuntimeError,'fixture exit'):
                        with self.research_fixture([]) as (_,_,calls,_,_):
                            command=radar.discovery_command()
                            self.assertEqual(command[command.index('--provider')+1],'fixture-provider')
                            self.assertEqual(command[command.index('-m')+1],'fixture-model')
                            calls.assert_not_called()
                            raise RuntimeError('fixture exit')
                    self.assertEqual(radar.configured_default_model.cache_info().currsize,0)
            launch.assert_not_called()

    def candidate(self,symbol='BBB',**changes):
        now=dt.datetime.now(dt.timezone.utc)
        return dict({'symbol':symbol,'instrument_type':'cash_equity','setup_type':'event_momentum',
                     'planned_exit_at':(now+dt.timedelta(days=10)).isoformat(),
                     'earnings_event_at':(now-dt.timedelta(days=2)).date().isoformat(),
                     'horizon_rationale':'Post event follow-through','sources':[{'url':f'https://{d}.example/{symbol}'} for d in ('one','two')]},**changes)

    def test_oct2_replay_borrows_for_second_synthesis_without_burning_enrichment(self):
        for upstream,expected_timeouts in ((0,[60,52]),(400,[60,35])):
            clock=[0.0]
            with self.subTest(upstream=upstream), self.research_fixture([self.candidate('AAA'),self.candidate('BBB')]) as (cfg,root,calls,fetch,market):
                original=calls.side_effect
                def model(*args,**kwargs):
                    response=next(original)
                    if calls.call_count>1:clock[0]+=30
                    return response
                calls.side_effect=model
                pages=fetch.return_value
                def evidence(*args,**kwargs):
                    clock[0]=upstream
                    return pages
                fetch.side_effect=evidence
                def prices(symbol):
                    clock[0]+=8
                    return {'price':100,'spy_price':500}
                market.side_effect=prices
                prepare=radar.prepare_candidate
                def intake(candidate,cfg):
                    if candidate['symbol']=='AAA':raise radar.CandidateRejection('candidate_failed_qualification')
                    return prepare(candidate,cfg)
                with patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch('research_budget.monotonic',side_effect=lambda:clock[0]), patch.object(radar,'prepare_candidate',side_effect=intake):
                    result=radar.live_research(cfg)
                self.assertEqual(result['symbol'],'BBB')
                self.assertEqual([c.kwargs['timeout'] for c in calls.call_args_list[1:]],expected_timeouts)
                self.assertEqual(clock[0],upstream+76)
                fetch.assert_called_once()
                self.assertEqual(calls.call_count,3)
                self.assertFalse((root/'candidates.jsonl').exists())

    def test_prompt_preparation_exhaustion_preserves_rejection_but_model_timeout_does_not(self):
        for prompt_exhausts,expected in ((True,'candidate_failed_qualification'),(False,'research_synthesis_timeout')):
            clock=[0.0]
            with self.subTest(prompt_exhausts=prompt_exhausts), self.research_fixture([self.candidate('AAA'),subprocess.TimeoutExpired('synthesis',30)],symbols=('AAA','BBB')) as (cfg,root,calls,_,_):
                prompt=radar.synthesis_prompt
                def prepare_prompt(*args,**kwargs):
                    if kwargs.get('candidate_hint',{}).get('symbol')=='BBB' and prompt_exhausts:
                        clock[0]+=0.01
                    return prompt(*args,**kwargs)
                def reject_first(candidate,cfg):
                    clock[0]=60.0
                    raise radar.CandidateRejection('candidate_failed_qualification')
                with patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch('research_budget.monotonic',side_effect=lambda:clock[0]), patch.object(radar,'synthesis_prompt',side_effect=prepare_prompt), patch.object(radar,'prepare_candidate',side_effect=reject_first):
                    with self.assertRaises(radar.ResearchFailure) as caught:
                        radar.live_research(cfg)
                self.assertEqual(caught.exception.code,expected)
                self.assertEqual(calls.call_count,2 if prompt_exhausts else 3)
                self.assertFalse((root/'candidates.jsonl').exists())

    def test_near_global_cap_reserves_all_remaining_enrichment(self):
        clock=[0.0]
        none={'status':'none','none_reason':'no_fresh_setup'}
        with self.research_fixture([none],symbols=('AAA',)) as (cfg,_,calls,fetch,_):
            pages=fetch.return_value
            def delayed_fetch(*args,**kwargs):
                clock[0]=435.0
                return pages
            fetch.side_effect=delayed_fetch
            with patch.object(radar,'monotonic',side_effect=lambda:clock[0]):
                self.assertEqual(radar.live_research(cfg)['status'],'none')
            self.assertEqual(calls.call_args_list[-1].kwargs['timeout'],30)
            self.assertEqual(calls.call_count,2)

    def test_subminimum_window_never_launches_initial_or_alternative(self):
        none={'status':'none','none_reason':'no_fresh_setup'}
        for initial,first in ((436,None),(0,none),(0,self.candidate('AAA'))):
            with self.subTest(initial=initial,first=first), self.research_fixture([first or none,none],symbols=('AAA','BBB')) as (cfg,root,calls,fetch,_):
                clock=[0.0]
                pages=fetch.return_value
                def fetch_late(*args,**kwargs):
                    clock[0]=initial
                    return pages
                fetch.side_effect=fetch_late
                responses=calls.side_effect
                def model(*args,**kwargs):
                    result=next(responses)
                    if calls.call_count>1 and not initial:clock[0]=61
                    return result
                calls.side_effect=model
                with patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch('research_budget.monotonic',side_effect=lambda:clock[0]), patch.object(radar,'prepare_candidate',side_effect=radar.CandidateRejection('candidate_failed_qualification')):
                    with self.assertRaises(radar.ResearchFailure) as caught:radar.live_research(cfg)
                self.assertEqual(caught.exception.code,'candidate_failed_qualification' if first and first.get('symbol') else 'research_synthesis_timeout')
                self.assertEqual(calls.call_count,1 if initial else 2)
                self.assertFalse((root/'candidates.jsonl').exists())

    def test_deferred_rescue_reserves_enrichment_and_original_phase_window(self):
        clock=[0.0]
        none={'status':'none','none_reason':'no_fresh_setup'}
        with self.research_fixture([],symbols=('AAA','BBB')) as (cfg,_,calls,fetch,_):
            pages=fetch.return_value
            fetch.return_value=pages[:3]
            def late_focused(*args,**kwargs):
                clock[0]=400
                return {s:[f'https://two.example/{s}'] for s in ('AAA','BBB')}
            deadlines=[]
            def synth(cfg,selected,evidence,deadline,**kwargs):
                deadlines.append(deadline)
                clock[0]+=15
                return none
            def rescue(selected,accepted,**kwargs):
                self.assertEqual(kwargs['deadline'],435)
                clock[0]=435
                return accepted+[pages[3]]
            with patch.object(radar,'focused_retrieval',side_effect=late_focused), patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch.object(radar,'synthesize_candidate',side_effect=synth), patch.object(radar,'post_fetch_rescue_candidate',side_effect=rescue) as rescued:
                self.assertEqual(radar.live_research(cfg)['status'],'none')
            self.assertEqual(deadlines,[490,490])
            rescued.assert_called_once()
            self.assertEqual(calls.call_count,1)

    def test_cumulative_enrichment_is_45_active_seconds_even_after_rejected_io(self):
        clock=[0.0]
        with self.research_fixture([self.candidate('AAA'),self.candidate('BBB')],symbols=('AAA','BBB')) as (cfg,root,calls,_,market):
            responses=calls.side_effect
            def model(*args,**kwargs):
                result=next(responses)
                if calls.call_count>1:clock[0]+=10
                return result
            calls.side_effect=model
            def prices(symbol):
                clock[0]+=20 if symbol=='AAA' else 26
                if symbol=='AAA':raise ValueError('invalid_symbol')
                return {'price':100,'spy_price':500}
            market.side_effect=prices
            with patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch('research_budget.monotonic',side_effect=lambda:clock[0]), patch.object(radar,'active_deadline',wraps=radar.active_deadline) as deadlines:
                with self.assertRaises(radar.ResearchFailure) as caught:radar.live_research(cfg)
            self.assertEqual(caught.exception.code,'research_enrichment_timeout')
            self.assertEqual([call.args[0] for call in deadlines.call_args_list],[55,65])
            self.assertEqual(clock[0],66)
            self.assertEqual(calls.call_count,3)
            self.assertEqual(market.call_count,2)
            self.assertFalse((root/'candidates.jsonl').exists())

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

    def test_shared_enrichment_active_budget_stops_next_candidate_before_network(self):
        with self.research_fixture([self.candidate('AAA'),self.candidate('BBB')]) as (cfg,root,calls,_,market):
            clock=[0.0]
            def expired_prices(symbol):
                clock[0]=46.0
                return {'price':100,'spy_price':500}
            market.side_effect=expired_prices
            with patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch('research_budget.monotonic',side_effect=lambda:clock[0]):
                with self.assertRaises(radar.ResearchFailure) as caught:
                    radar.live_research(cfg)
            self.assertEqual(caught.exception.code,'research_enrichment_timeout')
            self.assertEqual(market.call_count,1)
            self.assertFalse((root/'candidates.jsonl').exists())

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

    def test_alternatives_share_one_monotonic_90_second_budget(self):
        none={'status':'none','none_reason':'no_fresh_setup'}
        with self.research_fixture([none]*3) as (cfg,_,calls,_,_), patch.object(radar,'monotonic',side_effect=lambda: {1:0,2:30,3:55}.get(calls.call_count,0)):
            radar.live_research(cfg)
            self.assertEqual([c.kwargs['timeout'] for c in calls.call_args_list[1:]],[60,60,35])

    def test_exhausted_budget_never_starts_another_subprocess(self):
        none={'status':'none','none_reason':'no_fresh_setup'}
        with self.research_fixture([none]*3) as (cfg,_,calls,_,_), patch.object(radar,'monotonic',side_effect=lambda:61 if calls.call_count>=2 else 0):
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

    def test_trickling_market_response_deadline_is_typed_and_cannot_append(self):
        from research_budget import ResearchDeadlineExceeded
        with self.research_fixture([self.candidate('AAA'),self.candidate()]) as (_,root,calls,_,market):
            market.side_effect=ResearchDeadlineExceeded('stream deadline')
            self.assertEqual(self.run_main(),(3,'SYSTEM_FAILURE research_enrichment_timeout'))
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
        with self.research_fixture([]) as (_,root,calls,fetch,_), patch.object(radar,'post_fetch_rescue_candidate') as rescue:
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
            with self.subTest(reason=reason), self.research_fixture([]) as (_,root,calls,fetch,_), patch.object(radar,'post_fetch_rescue_candidate') as rescue, patch.object(radar,'focused_retrieval',side_effect=self.real_focused_retrieval):
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
