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
SCOUT_FRESH_EVENT_DATE=dt.datetime.now(dt.timezone.utc).date().isoformat()
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

    def test_earnings_spent_intake_moves_to_source_first_alternative(self):
        from durable_jsonl import append_jsonl
        from earnings_spending import rejection
        first, second = self.candidate('AAA'), self.candidate('BBB')
        with self.research_fixture([first, second], symbols=('AAA', 'BBB')) as (cfg, root, calls, fetch, market):
            append_jsonl(root / 'order_ledger.jsonl', rejection({**first, 'dossier_hash': 'previous'}, 'precheck', dt.datetime.now(dt.timezone.utc).isoformat()))
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
            self.assertEqual(code, 0, stdout.getvalue())
            published = [json.loads(line) for line in (root / 'candidates.jsonl').read_text().splitlines()]
            self.assertEqual([row['symbol'] for row in published], ['BBB'])
            self.assertEqual(calls.call_count, 3)
            fetch.assert_called_once()

    def test_separate_shared_allowances_allow_rejected_first_then_long_second(self):
        clock=[0.0]
        with self.research_fixture([self.candidate('AAA'),self.candidate('BBB')],symbols=('AAA','BBB')) as (cfg,root,calls,_,market):
            responses=calls.side_effect
            def model(*args,**kwargs):
                result=next(responses)
                if calls.call_count>1:
                    duration=100 if calls.call_count==2 else 160
                    self.assertGreaterEqual(kwargs['timeout'],duration)
                    clock[0]+=duration
                return result
            calls.side_effect=model
            def prices(symbol):
                clock[0]+=40
                return {'price':100,'spy_price':500}
            market.side_effect=prices
            def intake(candidate):
                if candidate['symbol']=='AAA':raise radar.CandidateRejection('candidate_failed_qualification')
                return candidate
            with patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch('research_budget.monotonic',side_effect=lambda:clock[0]):
                result=radar.live_research(cfg,intake=intake)
            self.assertEqual(result['symbol'],'BBB')
            self.assertEqual([c.kwargs['timeout'] for c in calls.call_args_list[1:]],[270,170])
            self.assertEqual(clock[0],340)  # 260 synthesis + 80 enrichment, not a 360s wall-clock pool.
            self.assertFalse((root/'candidates.jsonl').exists())

    def test_synthesis_preserves_invalid_exit_dates_and_real_intake_rejects_them(self):
        now=dt.datetime.now(dt.timezone.utc)
        values=('not-a-date',(now-dt.timedelta(days=2)).isoformat(),
                (now+dt.timedelta(days=3)).replace(tzinfo=None).isoformat(),
                (now+dt.timedelta(days=70)).isoformat())
        for raw_exit in values:
            with self.subTest(raw_exit=raw_exit), self.research_fixture([self.candidate('AAA',planned_exit_at=raw_exit)],symbols=('AAA',)) as (cfg,root,_,_,_):
                seen=[]
                def intake(candidate):
                    seen.append(candidate['planned_exit_at'])
                    return radar.prepare_candidate(candidate,cfg,ledger_path=root/'order_ledger.jsonl')
                with self.assertRaises(radar.CandidateRejection) as caught:
                    radar.live_research(cfg,intake=intake)
                self.assertIn('invalid_horizon',caught.exception.code)
                self.assertEqual(seen,[raw_exit])
                self.assertFalse((root/'candidates.jsonl').exists())

    def test_supported_short_and_swing_exit_dates_pass_real_intake_unchanged(self):
        now=dt.datetime.now(dt.timezone.utc)
        for days,setup in ((3,'event_momentum'),(12,'strategic_rerating')):
            raw_exit=(now+dt.timedelta(days=days)).isoformat()
            with self.subTest(setup=setup), self.research_fixture([self.candidate('AAA',planned_exit_at=raw_exit,setup_type=setup)],symbols=('AAA',)) as (cfg,_,_,_,_):
                result=radar.live_research(cfg)
                self.assertEqual(result['planned_exit_at'],raw_exit)
                self.assertEqual(result['setup_type'],setup)

    def test_oct2_replay_borrows_for_second_synthesis_without_burning_enrichment(self):
        # Retain the historical 400-second replay, plus its shifted near-global
        # equivalent under the 960-second active envelope.
        for upstream,expected_timeouts in ((0,[270,240]),(400,[270,240]),(790,[80,50])):
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
                def intake(candidate,cfg,**kwargs):
                    if candidate['symbol']=='AAA':raise radar.CandidateRejection('candidate_failed_qualification')
                    return prepare(candidate,cfg,**kwargs)
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
                responses=calls.side_effect
                def model(*args,**kwargs):
                    response=next(responses)
                    if calls.call_count==2:clock[0]=240.0
                    if isinstance(response,BaseException):raise response
                    return response
                calls.side_effect=model
                prompt=radar.synthesis_prompt
                def prepare_prompt(*args,**kwargs):
                    if kwargs.get('candidate_hint',{}).get('symbol')=='BBB' and prompt_exhausts:
                        clock[0]+=0.01
                    return prompt(*args,**kwargs)
                def reject_first(candidate,cfg,**kwargs):
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
                clock[0]=840.0
                return pages
            fetch.side_effect=delayed_fetch
            with patch.object(radar,'monotonic',side_effect=lambda:clock[0]):
                self.assertEqual(radar.live_research(cfg)['status'],'none')
            self.assertEqual(calls.call_args_list[-1].kwargs['timeout'],30)
            self.assertEqual(calls.call_count,2)

    def test_subminimum_window_never_launches_initial_or_alternative(self):
        none={'status':'none','none_reason':'no_fresh_setup'}
        for initial,first in ((841,None),(0,none),(0,self.candidate('AAA'))):
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
                    if calls.call_count>1 and not initial:clock[0]=241
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
                clock[0]=790
                return {s:[f'https://two.example/{s}'] for s in ('AAA','BBB')}
            deadlines=[]
            def synth(cfg,selected,evidence,deadline,**kwargs):
                deadlines.append(deadline)
                clock[0]+=15
                return none
            def rescue(selected,accepted,**kwargs):
                self.assertEqual(kwargs['deadline'],835)  # Preserve 30 synthesis + 90 enrichment + 5 transition.
                clock[0]=835
                return accepted+[pages[3]]
            with patch.object(radar,'focused_retrieval',side_effect=late_focused), patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch.object(radar,'synthesize_candidate',side_effect=synth), patch.object(radar,'post_fetch_rescue_candidate',side_effect=rescue) as rescued:
                self.assertEqual(radar.live_research(cfg)['status'],'none')
            self.assertEqual(deadlines,[960,960])
            rescued.assert_called_once()
            self.assertEqual(calls.call_count,1)

    def test_cumulative_enrichment_is_90_active_seconds_even_after_rejected_io(self):
        clock=[0.0]
        with self.research_fixture([self.candidate('AAA'),self.candidate('BBB')],symbols=('AAA','BBB')) as (cfg,root,calls,_,market):
            responses=calls.side_effect
            def model(*args,**kwargs):
                result=next(responses)
                if calls.call_count>1:clock[0]+=10
                return result
            calls.side_effect=model
            def prices(symbol):
                clock[0]+=40 if symbol=='AAA' else 51
                if symbol=='AAA':raise ValueError('invalid_symbol')
                return {'price':100,'spy_price':500}
            market.side_effect=prices
            with patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch('research_budget.monotonic',side_effect=lambda:clock[0]), patch.object(radar,'active_deadline',wraps=radar.active_deadline) as deadlines:
                with self.assertRaises(radar.ResearchFailure) as caught:radar.live_research(cfg)
            self.assertEqual(caught.exception.code,'research_enrichment_timeout')
            self.assertEqual([call.args[0] for call in deadlines.call_args_list],[100,110])
            self.assertEqual(clock[0],111)
            self.assertEqual(calls.call_count,3)
            self.assertEqual(market.call_count,2)
            self.assertFalse((root/'candidates.jsonl').exists())

    def test_rejected_or_none_first_candidate_advances_to_next_qualified(self):
        prices={'price':100,'spy_price':500}
        cases = (
            ('synthesis_none_advances_and_persists_once', lambda:[{'status':'none','none_reason':'no_fresh_setup'},self.candidate()], None, 'main',
             {'rows_symbols':['BBB'],'fetch_count':1,'market_count':1}),
            ('preflight_rejection_advances', lambda:[self.candidate('AAA',earnings_event_at=None), self.candidate()], None, 'main',
             {'rows_len':1}),
            ('malformed_sources_advance_without_market_lookup', lambda:[self.candidate('AAA',sources=None), self.candidate()], None, 'main',
             {'market_called_with':'BBB'}),
            ('symbol_local_market_failure_advances', lambda:[self.candidate('AAA'), self.candidate()],
             [ValueError('invalid_symbol'), prices], 'main', {}),
            ('direct_live_research_returns_only_fully_qualified', lambda:[self.candidate('AAA',earnings_event_at=None), self.candidate()], None, 'direct',
             {}),
        )
        for label, responses, market_side, mode, checks in cases:
            with self.subTest(case=label), self.research_fixture(responses()) as (cfg,root,calls,fetch,market):
                if market_side is not None:
                    market.side_effect=list(market_side)
                if mode=='main':
                    self.assertEqual(self.run_main(),(0,'DECISION candidate_qualified BBB'))
                    self.assertEqual(calls.call_count,3)
                    if 'rows_symbols' in checks or 'rows_len' in checks:
                        rows=[json.loads(line)['symbol'] for line in (root/'candidates.jsonl').read_text().splitlines()]
                        if 'rows_symbols' in checks:
                            self.assertEqual(rows,checks['rows_symbols'])
                        if 'rows_len' in checks:
                            self.assertEqual(len(rows),checks['rows_len'])
                    if 'fetch_count' in checks:
                        self.assertEqual(fetch.call_count,checks['fetch_count'])
                    if 'market_count' in checks:
                        self.assertEqual(market.call_count,checks['market_count'])
                    if 'market_called_with' in checks:
                        market.assert_called_once_with(checks['market_called_with'])
                else:
                    self.assertEqual(radar.live_research(cfg)['symbol'],'BBB')
                    self.assertEqual(calls.call_count,3)
                    self.assertFalse((root/'candidates.jsonl').exists())

    def test_shared_enrichment_active_budget_stops_next_candidate_before_network(self):
        with self.research_fixture([self.candidate('AAA'),self.candidate('BBB')]) as (cfg,root,calls,_,market):
            clock=[0.0]
            def expired_prices(symbol):
                clock[0]=91.0
                return {'price':100,'spy_price':500}
            market.side_effect=expired_prices
            with patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch('research_budget.monotonic',side_effect=lambda:clock[0]):
                with self.assertRaises(radar.ResearchFailure) as caught:
                    radar.live_research(cfg)
            self.assertEqual(caught.exception.code,'research_enrichment_timeout')
            self.assertEqual(market.call_count,1)
            self.assertFalse((root/'candidates.jsonl').exists())

    def test_at_most_three_distinct_symbols_are_attempted(self):
        none={'status':'none','none_reason':'no_fresh_setup'}
        with self.research_fixture([none]*5,symbols=('AAA','AAA','BBB','CCC','DDD')) as (cfg,_,calls,fetch,_):
            result=radar.live_research(cfg)
            self.assertEqual(result['status'],'none')
            self.assertEqual(calls.call_count,4)
            prompts=[c.kwargs['input'] for c in calls.call_args_list[1:]]
            self.assertEqual([p.split('SELECTED SYMBOL: ')[1].split('.')[0] for p in prompts],['AAA','BBB','CCC'])
            fetch.assert_called_once()

    def test_alternatives_share_270_cumulative_synthesis_seconds(self):
        none={'status':'none','none_reason':'no_fresh_setup'}
        with self.research_fixture([none]*3) as (cfg,_,calls,_,_), patch.object(radar,'monotonic',side_effect=lambda: {1:0,2:30,3:55}.get(calls.call_count,0)):
            radar.live_research(cfg)
            self.assertEqual([c.kwargs['timeout'] for c in calls.call_args_list[1:]],[270,240,215])

    def test_exhausted_budget_never_starts_another_subprocess(self):
        none={'status':'none','none_reason':'no_fresh_setup'}
        with self.research_fixture([none]*3) as (cfg,_,calls,_,_), patch.object(radar,'monotonic',side_effect=lambda:241 if calls.call_count>=2 else 0):
            with self.assertRaises(radar.ResearchFailure) as caught:
                radar.live_research(cfg)
            self.assertEqual(caught.exception.code,'research_synthesis_timeout')
            self.assertEqual(calls.call_count,2)

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

    def test_global_faults_stop_without_candidate_or_new_discovery(self):
        from research_budget import ResearchDeadlineExceeded
        cases = (
            ('synthesis_timeout', 'responses', subprocess.TimeoutExpired('synthesis',120), 'SYSTEM_FAILURE research_synthesis_timeout'),
            ('synthesis_unavailable', 'responses', subprocess.CompletedProcess([],1,'','private provider error'), 'SYSTEM_FAILURE research_synthesis_unavailable'),
            ('synthesis_parse_failure', 'responses', subprocess.CompletedProcess([],0,'not JSON',''), 'SYSTEM_FAILURE research_parse_failure'),
            ('market_credentials_unavailable', 'market', RuntimeError('massive_credentials_unavailable'), 'SYSTEM_FAILURE research_market_data_unavailable'),
            ('market_prices_unavailable', 'market', RuntimeError('massive_synchronized_prices_unavailable'), 'SYSTEM_FAILURE research_market_data_unavailable'),
            ('market_adapter_fault', 'market', ValueError('unrecognized adapter failure'), 'SYSTEM_FAILURE research_market_data_unavailable'),
            ('market_network_fault', 'market', OSError('network unavailable'), 'SYSTEM_FAILURE research_market_data_unavailable'),
            ('market_trickling_deadline', 'market', ResearchDeadlineExceeded('stream deadline'), 'SYSTEM_FAILURE research_enrichment_timeout'),
        )
        for label, seam, fault, expected_output in cases:
            with self.subTest(case=label):
                if seam == 'responses':
                    with self.research_fixture([fault,self.candidate()]) as (_,root,calls,fetch,market):
                        self.assertEqual(self.run_main(),(3,expected_output))
                        self.assertEqual(calls.call_count,2);fetch.assert_called_once();market.assert_not_called()
                        self.assertFalse((root/'candidates.jsonl').exists())
                else:
                    with self.research_fixture([self.candidate('AAA'),self.candidate()]) as (_,root,calls,_,market):
                        market.side_effect=fault
                        self.assertEqual(self.run_main(),(3,expected_output))
                        self.assertEqual(calls.call_count,2)
                        self.assertFalse((root/'candidates.jsonl').exists())

    def test_persistence_faults_surface_typed_failure_without_retry_or_reuse(self):
        cases = (('earnings', 'resolve_candidate_earnings', 'private'),
                 ('append', 'append', 'private'),
                 ('market', 'synchronized_completed_close_prices', 'private persistence fault'))
        for label, seam, message in cases:
            with self.subTest(case=label), self.research_fixture([self.candidate('AAA'),self.candidate()]) as (_,root,calls,_,market), contextlib.ExitStack() as stack:
                fault=stack.enter_context(patch.object(radar,seam,side_effect=radar.DurableAppendError(message)))
                if label=='market':
                    reuse=stack.enter_context(patch.object(radar,'fresh_verified_candidate',return_value={'symbol':'OLD'}))
                self.assertEqual(self.run_main(),(3,'SYSTEM_FAILURE research_persistence_failure'))
                self.assertEqual(calls.call_count,2)
                if label=='earnings':market.assert_not_called()
                if label=='append':fault.assert_called_once()
                else:self.assertFalse((root/'candidates.jsonl').exists())
                if label=='market':reuse.assert_not_called()

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

    def test_discovery_budget_caps_five_candidates_and_five_urls_at_both_parser_entries(self):
        raw={'candidates':[{'symbol':'AAA','event_date':SCOUT_FRESH_EVENT_DATE,'catalyst':'dated event',
                            'urls':[f'https://source{i}.example/a' for i in range(6)]}]}
        with self.subTest(case='six_url_candidate_rejected_by_both_parser_entries'):
            text=json.dumps(raw)
            self.assertEqual(radar.extract_scout_candidates(text),[])
            self.assertEqual(radar.scout_parse_result(text)[0],[])
        with self.subTest(case='six_candidates_ranked_to_five_with_focused_budget'):
            candidates=[{'symbol':s,'catalyst':'dated change','event_date':SCOUT_FRESH_EVENT_DATE,
                         'urls':[f'https://{s.lower()}.example/story']} for s in ('AAA','BBB','CCC','DDD','EEE','FFF')]
            parsed, diagnostic=radar.scout_parse_result(json.dumps({'candidates':candidates}))
            self.assertEqual(len(parsed),5)
            self.assertEqual(diagnostic['parsed_candidate_count'],5)
            self.assertEqual(diagnostic['raw_candidate_count'],6)
            targets=json.loads(radar.focused_retrieval_prompt(parsed).split('TARGETS:\n')[1])
            self.assertEqual(len(targets),5)
            output={'candidates':[{'symbol':c['symbol'],'urls':[f'https://{d}.example/{c["symbol"]}' for d in ('one','two','three','four')]} for c in parsed]}
            from focused_search import parse_search_manifest
            focused=parse_search_manifest(json.dumps(output),allowed_symbols={c['symbol'] for c in parsed},
                                          attested_urls={u for c in output['candidates'] for u in c['urls']})
            self.assertEqual([len(focused[c['symbol']]) for c in parsed],[4]*5)
            self.assertIn('up to five',radar.discovery_prompt({'max_position_usd':500}))
            self.assertIn('25 bindings total',radar.focused_retrieval_prompt(parsed))

    def test_focused_stage_faults_stop_before_rescue_or_fetch(self):
        faults=[('provider_exit_1',subprocess.CompletedProcess([],1,'','private provider error'),'research_focused_retrieval_unavailable'),
                ('timeout',subprocess.TimeoutExpired('focused',240),'research_focused_retrieval_timeout'),
                ('io_error',OSError('private'),'research_focused_retrieval_unavailable'),
                ('durable_append_error',radar.DurableAppendError('private'),'research_persistence_failure')]
        for label, fault, reason in faults:
            with self.subTest(case=label), self.research_fixture([]) as (_,root,calls,fetch,_), patch.object(radar,'post_fetch_rescue_candidate') as rescue, patch.object(radar,'focused_retrieval',side_effect=self.real_focused_retrieval), patch('focused_capture.run_private_child',side_effect=lambda *a,**kw:calls(*a,**kw)), patch.object(subprocess,'Popen',side_effect=AssertionError('unexpected process boundary')):
                calls.side_effect=[subprocess.CompletedProcess([],0,json.dumps({'candidates':[{'symbol':'AAA','event_date':SCOUT_FRESH_EVENT_DATE,'catalyst':'dated event','urls':['https://one.example/AAA']}]}),''),fault]
                self.assertEqual(self.run_main(),(3,'SYSTEM_FAILURE '+reason))
                self.assertEqual(calls.call_count,2);rescue.assert_not_called();fetch.assert_not_called()

    real_focused_retrieval=staticmethod(radar.focused_retrieval)


if __name__ == "__main__":
    unittest.main()
