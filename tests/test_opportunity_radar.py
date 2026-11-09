"""Synthetic Radar policy integration; all writes use owned temporary roots."""
import argparse
from contextlib import ExitStack
import copy
import datetime as dt
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import alpha_radar as radar
import opportunity_identity as identity
import opportunity_state as state
import opportunity_fixtures as fixtures
import sqlite_ledger as storage
from retained_article import original_text, retain_article

NOW = dt.datetime(2026, 11, 4, 14, tzinfo=dt.timezone.utc)


class RadarPolicyTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'socket.socket.connect_ex',
                       'socket.socket.sendto', 'socket.socket.sendmsg',
                       'socket.getaddrinfo', 'socket.gethostbyname',
                       'socket.gethostbyname_ex', 'socket.gethostbyaddr'):
            self.enterContext(patch(target, side_effect=AssertionError('synthetic network forbidden')))
        self.stack = self.enterContext(ExitStack())
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        fixtures.make_root(self.root, active=True)
        (self.root/'private/broker_baseline.json').write_text(json.dumps({'preexisting_symbols':[]}))
        self.enterContext(patch.object(radar, 'ROOT', self.root))
        self.enterContext(patch('urllib.request.urlopen',side_effect=AssertionError('synthetic test network forbidden')))
        self.pages = fixtures.earnings_pages()
        first = self.pages[0]
        url = first['url'].replace('1999999','1888888')
        raw = original_text(first).replace('ACME','NEXT').replace('1999999','1888888')
        second = {k:v for k,v in first.items() if not k.startswith('_')}
        second.update(url=url, returned_url=url)
        self.pages += [retain_article(second, raw)]
        self.resolutions = [identity.resolve_event(s, [p], known_resolutions=()) for s,p in zip(('ACME','NEXT'),self.pages)]
        for resolution in self.resolutions:
            identity.retain_observations(self.root, resolution, self.pages)
            storage.append_jsonl(self.root/state.POLICY_STREAM, fixtures.policy_row('identity_resolution', resolution=identity.candidate_identity(resolution)))
        self.scouts = []
        self.bundles = []
        for symbol, page in zip(('ACME','NEXT'),self.pages):
            secondary = {'url':f'https://news.example/{symbol}', 'title':'Synthetic news', 'text':'Synthetic results '*80,'published_at':'2026-11-04T12:00:00Z'}
            self.scouts.append({'symbol':symbol,'urls':[page['url'],secondary['url']],'event_date':'2026-11-04','catalyst':'synthetic results'})
            self.bundles.append([page, secondary])
        self.synthesized = []
        self.discovery_calls = 0

    def spend(self):
        r = self.resolutions[0]
        storage.append_jsonl(self.root/state.CANDIDATES_STREAM, fixtures.candidate_link('a'*64,r.event_id,state.allowance_identifier(r.event_id,0)))
        storage.append_jsonl(self.root/state.REVIEWS_STREAM, fixtures.review_row('a'*64,'synthetic-review',[{'decision':'HOLD'}]))

    def run_research(self, *, v2=False, legacy=False, intake=None, focused=False, overrides=()):
        def discovery(*args, **kwargs):
            self.discovery_calls += 1
            return copy.deepcopy(self.scouts), {'reason':'ok'}
        def scout(*args, **kwargs):
            candidates, _ = discovery()
            return subprocess.CompletedProcess([],0,json.dumps({'candidates':candidates}),'')
        def synthesis(cfg, selected, evidence, deadline, **kwargs):
            self.synthesized.append(selected['symbol'])
            return {'symbol':selected['symbol'], 'sources':[{'url':p['url']} for p in evidence]}
        with ExitStack() as s:
            s.enter_context(patch.object(radar.subprocess,'run',side_effect=scout))
            s.enter_context(patch('discovery_pipeline.discover',side_effect=discovery))
            s.enter_context(patch.object(radar,'scout_parse_result',side_effect=lambda *a,**k:(copy.deepcopy(self.scouts),{'reason':'ok'})))
            s.enter_context(patch.object(radar,'discovery_command',return_value=['synthetic']))
            s.enter_context(patch.object(radar,'sec_filing_date_for_url',return_value=None))
            s.enter_context(patch.object(radar,'gather_evidence',return_value=sum(self.bundles,[])))
            s.enter_context(patch.object(radar,'filter_evidence',side_effect=lambda p:(p,[])))
            s.enter_context(patch.object(radar,'recover_publications',side_effect=lambda c,p,*a,**k:(p,[])))
            s.enter_context(patch.object(radar,'synthesize_candidate',side_effect=synthesis))
            s.enter_context(patch.object(radar,'candidate_preflight',return_value=[]))
            s.enter_context(patch.object(radar,'qualified',return_value=True))
            s.enter_context(patch.object(radar,'source_verification_result',return_value={'passed':True}))
            if legacy:s.enter_context(patch.object(radar,'_run_policy_context',return_value=None,create=True))
            for module,name,options in overrides:s.enter_context(patch.object(module,name,**options))
            return radar.live_research({'discovery_v2_enabled':v2,'focused_retrieval_enabled':focused}, intake=intake)

    def prospective_with_history(self):
        self.scouts = self.scouts[:1]
        pages = fixtures.earnings_pages(period='2026-Q2')
        raw = original_text(pages[0])
        page = {k: v for k, v in pages[0].items() if not k.startswith('_')}
        page['url'] = page['returned_url'] = page['url'].replace('000001', '000003')
        pages = [retain_article(page, raw)]
        self.bundles = [pages + self.bundles[0][1:]]
        self.scouts[0]['urls'][0] = pages[0]['url']
        source = fixtures.review_row('b' * 64, 'unresolved', [{'decision': 'HOLD'}])
        storage.append_jsonl(self.root/state.REVIEWS_STREAM, source)
        unresolved = {'dossier_hash': 'b' * 64, 'status': 'unknown', 'reason': 'missing history'}
        storage.append_jsonl(self.root/state.POLICY_STREAM, fixtures.policy_row('identity_resolution', unresolved=unresolved))
        return source, unresolved

    def test_unscoped_prospective_history_is_failure_not_healthy_exhaustion(self):
        self.prospective_with_history()
        with self.assertRaisesRegex(state.OpportunityStateError, 'opportunity_policy_state_unavailable') as caught:
            self.run_research()
        self.assertEqual(self.synthesized, [])
        import run_cycle
        with patch.object(radar, 'reusable_fresh_candidate', return_value=None), patch.object(
                radar, 'live_research', side_effect=caught.exception), patch('sys.stdout', new_callable=io.StringIO) as out:
            code = radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual((code, out.getvalue()), (3, 'SYSTEM_FAILURE opportunity_policy_state_unavailable\n'))
        audit = self.root / 'private/scoped-history-cycle.jsonl'
        with patch.object(run_cycle.subprocess, 'run', return_value=subprocess.CompletedProcess(
                [], code, out.getvalue(), '')), patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(run_cycle.execute(['synthetic'], audit_mode='radar', audit_stage='research', audit_path=audit), 3)
        self.assertEqual(storage.read_jsonl(audit)[0]['reason'], 'opportunity_policy_state_unavailable')

    def test_explicit_other_issuer_scope_allows_prospective_radar_only(self):
        import opportunity_admin as admin
        import hashlib
        source, unresolved = self.prospective_with_history()
        other = self.resolutions[1]
        record = fixtures.policy_row('identity_resolution', unresolved={**unresolved, 'issuer_scope': {
            'binding_event_id': other.event_id, 'issuer_cik': other.issuer.cik}}, source={
                'stream': state.REVIEWS_STREAM, 'sequence': 1,
                'row_sha256': hashlib.sha256(admin._canonical(source)).hexdigest()})
        manifest = {'manifest_version': 1, 'records': [record]}
        admin.import_manifest(self.root, manifest, approved_manifest_sha256=admin.canonical_manifest_digest(manifest))
        self.assertEqual(self.run_research()['symbol'], 'ACME')
        self.assertEqual(self.synthesized, ['ACME'])
        self.assertEqual(self.discovery_calls, 1)

    def test_old_runtime_control_repeated_first_lead_wins_with_valid_second(self):
        self.spend()
        self.assertEqual(self.run_research(legacy=True)['symbol'],'ACME')
        self.assertEqual(self.synthesized,['ACME'])
        self.assertEqual(self.resolutions[1].status,'verified')

    def test_spent_first_lead_advances_to_second_without_extra_discovery(self):
        self.spend()
        for v2 in (False,True):
            with self.subTest(v2=v2):
                self.synthesized.clear(); self.discovery_calls=0
                result=self.run_research(v2=v2)
                self.assertEqual(result['symbol'],'NEXT')
                self.assertEqual(self.synthesized,['NEXT'])
                self.assertEqual(self.discovery_calls,1)
                self.assertEqual(result['opportunity_identity']['event_id'],self.resolutions[1].event_id)

    def test_held_first_advances_and_empty_baseline_does_not_ban_spent_ticker(self):
        (self.root/'private/broker_baseline.json').write_text(json.dumps({'preexisting_symbols':['ACME']}))
        self.assertEqual(self.run_research()['symbol'],'NEXT')
        self.assertEqual(self.synthesized,['NEXT'])

    def test_all_policy_skipped_returns_healthy_without_synthesis(self):
        self.spend(); self.scouts=self.scouts[:1]; self.bundles=self.bundles[:1]
        result=self.run_research()
        self.assertEqual(result,{'status':'none','none_reason':'no_new_eligible_opportunity'})
        self.assertEqual(self.synthesized,[])

    def test_unknown_after_retrieval_continues_shortlist(self):
        self.bundles[0][0]={k:v for k,v in self.bundles[0][0].items() if not k.startswith('_')}
        # An unseen immutable anchor forces retrieval; after retrieval its
        # missing retained body stays unknown. The old runtime still chose it.
        self.scouts[0]['urls'][0]=self.bundles[0][0]['url']=self.bundles[0][0]['url'].replace('000001','000003')
        self.bundles[0][0]['returned_url']=self.bundles[0][0]['url']
        self.assertEqual(self.run_research(legacy=True)['symbol'],'ACME')
        self.synthesized.clear();self.discovery_calls=0
        self.assertEqual(self.run_research()['symbol'],'NEXT')
        self.assertEqual(self.synthesized,['NEXT'])
        self.assertEqual(self.discovery_calls,1)

    def test_context_refresh_detects_corruption_and_wrong_root(self):
        context=state.load_policy_context(self.root)
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as td:
            wrong=replace(context,root=Path(td))
            with self.assertRaises(state.OpportunityStateError):state.refresh_policy_context(wrong)
        storage.append_jsonl(self.root/state.POLICY_STREAM,{'record_type':'unknown'})
        with self.assertRaises(state.OpportunityStateError):state.refresh_policy_context(context)

    def test_healthy_cli_exhaustion_and_cycle_audit_notice(self):
        import run_cycle
        with patch.object(radar,'reusable_fresh_candidate',return_value=None), patch.object(radar,'live_research',return_value={'status':'none','none_reason':'no_new_eligible_opportunity'}), patch('sys.stdout',new_callable=io.StringIO) as out:
            code=radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual((code,out.getvalue()),(0,'DECISION skipped no_new_eligible_opportunity\n'))
        audit=self.root/'private/cycle-audit.jsonl'
        with patch.object(run_cycle.subprocess,'run',return_value=subprocess.CompletedProcess([],0,out.getvalue(),'')), patch('sys.stdout',new_callable=io.StringIO) as notice:
            self.assertEqual(run_cycle.execute(['synthetic'],audit_mode='radar',audit_stage='research',audit_path=audit),0)
        self.assertIn('no_new_eligible_opportunity',notice.getvalue())
        self.assertEqual(storage.read_jsonl(audit)[0]['reason'],'no_new_eligible_opportunity')

    def test_invalid_active_policy_cannot_enter_main_reuse_fallback(self):
        storage.append_jsonl(self.root/state.POLICY_STREAM,{'record_type':'unknown'})
        with patch.object(radar,'live_research') as live, patch('sys.stdout',new_callable=io.StringIO) as out:
            code=radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual((code,out.getvalue()),(3,'SYSTEM_FAILURE opportunity_policy_state_unavailable\n'))
        live.assert_not_called()

    def test_unknown_policy_version_is_typed_failure(self):
        storage.append_jsonl(self.root/state.POLICY_STREAM,fixtures.policy_row('activation',policy_version=7,manifest_sha256='b'*64))
        with self.assertRaises(state.OpportunityStateError):self.run_research()

    def stored_candidate(self, *, symbol='ACME'):
        index=('ACME','NEXT').index(symbol)
        r=self.resolutions[index]
        row={'symbol':symbol,'sources_verified_at':NOW.isoformat(),'researched_at':NOW.isoformat(),
             'dossier_hash':('a' if index==0 else 'b')*64,
             'opportunity_identity':identity.candidate_identity(r),'event_id':r.event_id,
             'allowance_id':state.allowance_identifier(r.event_id,0)}
        storage.append_jsonl(self.root/state.CANDIDATES_STREAM,row)
        return row

    def test_reuse_fresh_helper_and_selector_all_filter_spent_and_held(self):
        first=self.stored_candidate()
        second=self.stored_candidate(symbol='NEXT')
        storage.append_jsonl(self.root/state.REVIEWS_STREAM,fixtures.review_row(first['dossier_hash'],'review',[{'decision':'HOLD'}],timestamp='2026-11-04T13:00:00+00:00'))
        # More recent spent ACME must not eclipse older eligible NEXT.
        storage.append_jsonl(self.root/state.CANDIDATES_STREAM,first)
        with patch.object(radar,'candidate_preflight',return_value=[]),patch.object(radar,'qualified',return_value=True):
            for helper in (radar.fresh_verified_candidate, lambda p,**k:radar.reusable_fresh_candidate(p,self.root/state.REVIEWS_STREAM,**k)):
                with self.subTest(helper=helper):
                    self.assertEqual(helper(self.root/state.CANDIDATES_STREAM,now=NOW)['symbol'],'NEXT')
            (self.root/'private/broker_baseline.json').write_text(json.dumps({'preexisting_symbols':['NEXT']}))
            self.assertIsNone(radar.fresh_verified_candidate(self.root/state.CANDIDATES_STREAM,now=NOW))

    def test_mixed_unseen_primary_is_not_cheap_skipped(self):
        self.spend()
        self.scouts[0]['urls'].append(self.pages[0]['url'].replace('000001','000002'))
        context=state.load_policy_context(self.root)
        self.assertIsNone(radar._policy_reason(context,self.scouts[0]))

    def test_new_current_cover_round_trips_into_canonical_index(self):
        pages=fixtures.earnings_pages(period='2026-Q2')
        page=pages[0];url=page['url'].replace('000001','000005')
        pages=[retain_article({**{k:v for k,v in page.items() if not k.startswith('_')},'url':url,'returned_url':url},original_text(page))]
        resolution=identity.resolve_event('ACME',pages,known_resolutions=())
        context=state.load_policy_context(self.root)
        self.assertEqual(state.candidate_policy(context,resolution,symbol='ACME').outcome,'eligible')
        token=radar._policy_acquisition.set((self.root,resolution,pages,None))
        try:
            with patch.object(radar,'candidate_preflight',return_value=[]),patch.object(radar,'qualified',return_value=True):
                row=radar.prepare_candidate({'symbol':'ACME'}, {},verify_sources=False,ledger_path=self.root/'order_ledger.jsonl')
        finally:radar._policy_acquisition.reset(token)
        row.pop('_radar_authority',None)
        row['dossier_hash']='d'*64
        storage.append_jsonl(self.root/state.CANDIDATES_STREAM,row)
        self.assertIn(resolution.event_id,state.load_index(self.root).resolutions)
        registered=storage.read_jsonl_stream_readonly(self.root/state.POLICY_STREAM)
        self.assertTrue(any(p.get('resolution',{}).get('event_id')==resolution.event_id for p in registered))

    def test_absent_policy_legacy_canonical_dossiers_remain_reusable(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fixtures.make_root(root)
            row={'symbol':'NEXT','dossier_hash':'f'*64,'sources_verified_at':NOW.isoformat()}
            storage.append_jsonl(root/state.CANDIDATES_STREAM,row)
            with patch.object(radar,'candidate_preflight',return_value=[]),patch.object(radar,'qualified',return_value=True):
                self.assertEqual(radar.fresh_verified_candidate(root/state.CANDIDATES_STREAM,now=NOW),row)

    def test_preappend_watermark_change_blocks_durable_candidate(self):
        def fake_live(cfg, intake):
            r=self.resolutions[1]
            token=radar._policy_acquisition.set((self.root,r,self.pages,None))
            try:prepared=intake({'symbol':'NEXT'})
            finally:radar._policy_acquisition.reset(token)
            storage.append_jsonl(self.root/state.CANDIDATES_STREAM,fixtures.candidate_link('c'*64,r.event_id,state.allowance_identifier(r.event_id,0)))
            storage.append_jsonl(self.root/state.REVIEWS_STREAM,fixtures.review_row('c'*64,'late-review',[{'decision':'HOLD'}]))
            return prepared
        with patch.object(radar,'reusable_fresh_candidate',return_value=None),patch.object(radar,'live_research',side_effect=fake_live),patch.object(radar,'candidate_preflight',return_value=[]),patch.object(radar,'qualified',return_value=True),patch.object(radar,'source_verification_result',return_value={'passed':True}),patch('sys.stdout',new_callable=io.StringIO) as out:
            result=radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual((result,out.getvalue()),(0,'DECISION skipped no_new_eligible_opportunity\n'))
        self.assertEqual(len(storage.read_jsonl_stream_readonly(self.root/state.CANDIDATES_STREAM)),1)

    def approve_condition(self):
        self.spend()
        r=self.resolutions[0]
        condition={'metric':'completed_close_usd','operator':'>=','threshold':'50','units':'USD',
            'source_kind':'massive_consolidated_completed_daily','expires_at':'2030-01-01T00:00:00+00:00',
            'observation_max_age_seconds':86400,'baseline_ref':'synthetic-baseline',
            'allowance_id':state.allowance_identifier(r.event_id,0)}
        storage.append_jsonl(self.root/state.POLICY_STREAM,fixtures.policy_row('condition_approval',condition_id='synthetic-condition',event_id=r.event_id,condition=condition))

    def test_approved_condition_uses_original_adapter_time_and_stays_research_only(self):
        from opportunity_admin import restore_reopening_claim
        self.approve_condition()
        class Clock(dt.datetime):
            @classmethod
            def now(cls,tz=None):return cls.fromtimestamp(NOW.timestamp(),tz=tz)
        prices={'price':60.0,'spy_price':500.0,'market_price_feed':'massive_consolidated_completed_daily','market_prices_at':'2026-11-04T13:00:00Z'}
        with patch.object(radar.dt,'datetime',Clock),patch.object(radar,'synchronized_completed_close_prices',return_value=prices) as load:
            result=self.run_research()
        self.assertEqual(result['symbol'],'ACME')
        self.assertEqual(load.call_count,1)
        self.assertIn('reopening_claim',result)
        self.assertEqual(result['reopening_claim']['observation']['observed_at'],'2026-11-04T13:00:00+00:00')
        self.assertFalse(state.load_index(self.root).grants)
        result.pop('_radar_authority',None)
        result['dossier_hash']='e'*64
        storage.append_jsonl(self.root/state.CANDIDATES_STREAM,result)
        restored=restore_reopening_claim(state.load_index(self.root),'e'*64,now=NOW)
        self.assertEqual(restored.condition_id,'synthetic-condition')
        with patch.object(radar.dt, 'datetime', Clock):
            self.assertTrue(radar._stored_policy_eligible(result,state.load_policy_context(self.root)))

    def test_stale_condition_price_cannot_reopen_at_new_verification_time(self):
        self.approve_condition()
        prices={'price':60.0,'spy_price':500.0,'market_price_feed':'massive_consolidated_completed_daily','market_prices_at':'2026-10-01T13:00:00Z'}
        with patch.object(radar,'synchronized_completed_close_prices',return_value=prices) as load:
            result=self.run_research()
        self.assertEqual(result['symbol'],'NEXT')
        self.assertEqual(self.synthesized,['NEXT'])
        self.assertEqual(load.call_count,1)
        self.assertFalse(state.load_index(self.root).grants)

    def test_no_sixth_candidate_after_five_cheap_policy_skips(self):
        self.spend()
        self.scouts=[copy.deepcopy(self.scouts[0]) for _ in range(5)]+[self.scouts[1]]
        result=self.run_research()
        self.assertEqual(result,{'status':'none','none_reason':'no_new_eligible_opportunity'})
        self.assertEqual(self.synthesized,[])
        self.assertEqual(self.discovery_calls,1)

    def test_spent_lead_removed_before_focused_and_no_extra_rescue(self):
        self.spend();seen=[]
        def focused(candidates,**kwargs):
            seen.extend(c['symbol'] for c in candidates)
            return {c['symbol']:c['urls'] for c in candidates}
        with patch.object(radar,'post_fetch_rescue_candidate',side_effect=AssertionError('unexpected rescue')):
            result=self.run_research(focused=True,overrides=[(radar,'focused_retrieval',{'side_effect':focused})])
        self.assertEqual(result['symbol'],'NEXT')
        self.assertEqual(seen,['NEXT'])
        self.assertEqual(self.synthesized,['NEXT'])

    def test_known_filing_recognition_adds_no_metadata_provider_call(self):
        self.spend()
        self.scouts=self.scouts[:1]
        with patch.object(radar,'gather_evidence',side_effect=AssertionError('no fetch allowed')):
            # Applied after the harness's network mocks.
            result=self.run_research(overrides=[(radar,'gather_evidence',{'side_effect':AssertionError('no fetch allowed')})])
        self.assertEqual(result['none_reason'],'no_new_eligible_opportunity')
        self.assertEqual(self.discovery_calls,1)

    def test_scout_and_storage_failures_are_not_healthy_exhaustion(self):
        for target,error,code in (
            ('subprocess',None,None),
            ('record_scout_diagnostic',OSError('synthetic disk'),'research_persistence_failure'),
            ('gather_evidence',radar.ResearchFailure('research_source_retrieval_failed'),'research_source_retrieval_failed'),
            ('synthesize_candidate',radar.ResearchFailure('research_synthesis_timeout'),'research_synthesis_timeout'),
        ):
            if target=='subprocess':
                overrides=[(radar.subprocess,'run',{'side_effect':subprocess.TimeoutExpired(['synthetic'],1)})]
                code='research_scout_timeout'
            else:overrides=[(radar,target,{'side_effect':error})]
            with self.subTest(target=target),self.assertRaises(radar.ResearchFailure) as caught:
                self.run_research(overrides=overrides)
            self.assertEqual(caught.exception.code,code)

    def test_retention_failure_cannot_publish_candidate_authority(self):
        with patch.object(identity,'retain_observations',side_effect=OSError('synthetic disk')):
            with self.assertRaises(radar.ResearchFailure) as caught:self.run_research()
        self.assertEqual(caught.exception.code,'research_persistence_failure')

    def test_error_fallback_does_not_reuse_spent_candidate(self):
        self.stored_candidate();self.spend()
        with patch.object(radar,'live_research',side_effect=radar.ResearchFailure('research_scout_unavailable')),patch.object(radar,'candidate_preflight',return_value=[]),patch.object(radar,'qualified',return_value=True),patch('sys.stdout',new_callable=io.StringIO) as out:
            code=radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual((code,out.getvalue()),(3,'SYSTEM_FAILURE research_scout_unavailable\n'))

    def test_mutable_registered_url_defers_until_current_bytes(self):
        from dataclasses import replace
        page=self.pages[0]
        mutable_url='https://issuer.example/earnings'
        mutable=retain_article({**{k:v for k,v in page.items() if not k.startswith('_')},'url':mutable_url,'returned_url':mutable_url},original_text(page))
        document=identity._document(mutable,'url:'+mutable_url)
        r=replace(self.resolutions[0],documents=(document,),support_refs=(document.retained_ref+'#dei:current',),issuer=replace(self.resolutions[0].issuer,support_ref=document.retained_ref+'#dei:current'),reason='explicit_binding')
        identity.retain_observations(self.root,r,[mutable])
        storage.append_jsonl(self.root/state.POLICY_STREAM,fixtures.policy_row('identity_resolution',resolution=identity.candidate_identity(r)))
        self.spend()
        self.scouts[0]['urls'][0]=mutable_url
        self.bundles[0][0]=retain_article({k:v for k,v in mutable.items() if not k.startswith('_')},original_text(mutable)+' changed')
        self.assertIsNone(radar._policy_reason(state.load_policy_context(self.root),self.scouts[0]))
        result=self.run_research()
        self.assertEqual(result['symbol'],'NEXT')
        self.assertEqual(self.synthesized,['NEXT'])

    def test_unresolved_identity_from_failed_primary_fetch_keeps_transport_failure(self):
        (self.root/'private/broker_baseline.json').write_text(json.dumps({'preexisting_symbols':['NEXT']}))
        missing=self.scouts[0]['urls'][0].replace('000001','000004')
        secondaries=[self.bundles[0][1],dict(self.bundles[0][1],url='https://other.example/confirmation')]
        self.scouts[0]['urls']=[missing]+[p['url'] for p in secondaries]
        def gather(urls,*,diagnostics,**kwargs):
            diagnostics.append({'url':missing,'reason':'source_fetch_failed','domain':'www.sec.gov'})
            return secondaries
        with self.assertRaises(radar.ResearchFailure) as caught:
            self.run_research(overrides=[(radar,'gather_evidence',{'side_effect':gather})])
        self.assertEqual(caught.exception.code,'research_source_retrieval_failed')

    def test_rescue_eligible_second_lead_without_reviving_spent_first(self):
        self.spend();secondary=self.bundles[1].pop();rescued=[]
        def rescue(selected,*args,**kwargs):
            rescued.append(selected['symbol']);return [secondary]
        result=self.run_research(overrides=[(radar,'post_fetch_rescue_candidate',{'side_effect':rescue})])
        self.assertEqual(result['symbol'],'NEXT')
        self.assertEqual(rescued,['NEXT'])
        self.assertEqual(self.synthesized,['NEXT'])
        self.assertEqual(self.discovery_calls,1)

    def test_late_policy_skip_charges_elapsed_synthesis_and_does_not_refill(self):
        ticks=[100.0];seen=[]
        def synth(cfg,selected,evidence,deadline,enrichment_budget):
            seen.append((selected['symbol'],deadline,ticks[0],enrichment_budget['remaining']))
            if selected['symbol']=='ACME':
                ticks[0]+=40.0
                self.spend()
            return {'symbol':selected['symbol']}
        with patch.object(radar,'monotonic',side_effect=lambda:ticks[0]):
            result=self.run_research(overrides=[(radar,'synthesize_candidate',{'side_effect':synth})])
        self.assertEqual(result['symbol'],'NEXT')
        self.assertEqual([row[0] for row in seen],['ACME','NEXT'])
        self.assertEqual(seen[0][1],seen[1][1])
        self.assertEqual(seen[1][2]-seen[0][2],40.0)
        self.assertEqual(seen[1][3],seen[0][3])
        self.assertEqual(self.discovery_calls,1)

    def test_main_persists_trusted_observations_before_integrity_hash(self):
        def fake_live(cfg,intake):
            r=self.resolutions[1]
            token=radar._policy_acquisition.set((self.root,r,self.pages,None))
            try:return intake({'symbol':'NEXT','_source_receipts':radar.build_source_receipts(self.bundles[1]),'event_id':'forged','reopening_claim':{'approved':True}})
            finally:radar._policy_acquisition.reset(token)
        with patch.object(radar,'reusable_fresh_candidate',return_value=None),patch.object(radar,'live_research',side_effect=fake_live),patch.object(radar,'candidate_preflight',return_value=[]),patch.object(radar,'qualified',return_value=True),patch.object(radar,'source_verification_result',return_value={'passed':True}),patch('sys.stdout',new_callable=io.StringIO) as out:
            self.assertEqual(radar.main_with_args(argparse.Namespace(dry_run_fixture=False)),0)
        rows=storage.read_jsonl_stream_readonly(self.root/state.CANDIDATES_STREAM)
        self.assertEqual(len(rows),1)
        row=rows[0]
        self.assertNotIn('_radar_authority',row)
        self.assertNotIn('reopening_claim',row)
        self.assertEqual(row['event_id'],self.resolutions[1].event_id)
        self.assertTrue(row['_source_receipts'])
        self.assertEqual(row['opportunity_observations'],row['opportunity_identity']['documents'])
        for document in row['opportunity_observations']:self.assertTrue((self.root/document['retained_ref']).is_file())
        import hashlib
        digest=row.pop('dossier_hash')
        self.assertEqual(digest,hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest())
        self.assertEqual(out.getvalue(),'DECISION candidate_qualified NEXT\n')

    def test_policy_floor_and_baseline_failures_never_use_legacy(self):
        import opportunity_activation
        self.assertEqual(opportunity_activation.SUPPORTED_POLICY_VERSION,2)
        baseline=self.root/'private/broker_baseline.json'
        for payload in (None,'{broken',json.dumps({'preexisting_symbols':[False]})):
            with self.subTest(payload=payload):
                if payload is None:baseline.unlink(missing_ok=True)
                else:baseline.write_text(payload)
                with self.assertRaises(state.OpportunityStateError):self.run_research()

    def test_healthy_late_held_exhaustion_without_sourceable_bundle(self):
        self.scouts=self.scouts[:1]
        def gather(*args,**kwargs):
            (self.root/'private/broker_baseline.json').write_text(json.dumps({'preexisting_symbols':['ACME']}))
            return self.bundles[0][:1]
        result=self.run_research(overrides=[(radar,'gather_evidence',{'side_effect':gather})])
        self.assertEqual(result,{'status':'none','none_reason':'no_new_eligible_opportunity'})
        self.assertEqual(self.synthesized,[])

    def test_actual_synthesis_reuses_one_trusted_close_and_strips_model_claims(self):
        prices={'price':60.0,'spy_price':500.0,'market_price_feed':'massive_consolidated_completed_daily','market_prices_at':'2026-11-04T13:00:00Z'}
        model={'symbol':'ACME','sources':[{'url':p['url']} for p in self.bundles[0]],'opportunity_identity':{'approved':True},'condition_id':'forged','reopening_claim':{'approved':True},'market_prices_at':'2099-01-01T00:00:00Z'}
        token=radar._trusted_market_prices.set(('ACME',prices))
        try:
            with patch.object(radar,'synthesis_command',return_value=['synthetic']),patch.object(radar.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(model),'')),patch.object(radar,'resolve_candidate_earnings',side_effect=lambda c,**kwargs:c),patch.object(radar,'synchronized_completed_close_prices',side_effect=AssertionError('duplicate adapter call')),patch.object(radar,'monotonic',return_value=100.0),patch('research_budget.monotonic',return_value=100.0):
                result=radar.synthesize_candidate({'max_position_usd':500},self.scouts[0],self.bundles[0],500.0,enrichment_budget={'overall':900.0,'remaining':90.0})
        finally:radar._trusted_market_prices.reset(token)
        self.assertEqual(result['market_prices_at'],prices['market_prices_at'])
        for field in ('condition_id','opportunity_identity','reopening_claim'):self.assertNotIn(field,result)

    def test_stored_projection_cannot_borrow_canonical_dossier_identity(self):
        row=self.stored_candidate()
        modified={**row,'symbol':'NEXT'}
        self.assertFalse(radar._stored_policy_eligible(modified,state.load_policy_context(self.root)))

    def test_non_policy_synthesis_none_is_not_relabelled_policy_exhaustion(self):
        self.spend()
        expected={'status':'none','none_reason':'evidence_insufficient'}
        result=self.run_research(overrides=[(radar,'synthesize_candidate',{'return_value':expected})])
        self.assertEqual(result,expected)

    def test_malformed_primary_locator_in_mixed_bundle_cannot_cheap_skip(self):
        self.spend()
        selected=copy.deepcopy(self.scouts[0])
        selected['urls'].append('https://www.sec.gov/Archives/edgar/data/1999999/malformed/report.htm')
        self.assertIsNone(radar._policy_reason(state.load_policy_context(self.root),selected))

    def test_active_reuse_rejects_foreign_review_root_before_read(self):
        self.stored_candidate()
        with tempfile.TemporaryDirectory() as td:
            foreign=Path(td)/'private/reviews.jsonl'
            with self.assertRaises(state.OpportunityStateError):
                radar.reusable_fresh_candidate(self.root/state.CANDIDATES_STREAM,foreign,now=NOW)

    def test_claim_storage_failure_is_typed_not_healthy(self):
        from opportunity_admin import OpportunityAdminError
        self.approve_condition()
        prices={'price':60.0,'spy_price':500.0,'market_price_feed':'massive_consolidated_completed_daily','market_prices_at':'2026-11-04T13:00:00Z'}
        class Clock(dt.datetime):
            @classmethod
            def now(cls,tz=None):return cls.fromtimestamp(NOW.timestamp(),tz=tz)
        with patch.object(radar.dt,'datetime',Clock),patch.object(radar,'synchronized_completed_close_prices',return_value=prices),patch('opportunity_admin.record_reopening_claim',side_effect=OpportunityAdminError('claim_append_failed')):
            with self.assertRaises(radar.ResearchFailure) as caught:self.run_research()
        self.assertEqual(caught.exception.code,'research_persistence_failure')

    def test_exact_safe_retry_survives_but_cannot_authorize_regenerated_or_held(self):
        row=self.stored_candidate()
        storage.append_jsonl(self.root/state.REVIEWS_STREAM,fixtures.review_row(row['dossier_hash'],'synthetic-retry',[{'decision':'APPROVE'},{'decision':'APPROVE'}],timestamp=NOW.isoformat()))
        storage.append_jsonl(self.root/state.REVIEWS_STREAM,fixtures.review_row(row['dossier_hash'],'synthetic-retry',[{'decision':'execution_retryable'}],timestamp=NOW.isoformat()))
        storage.append_jsonl(self.root/'order_ledger.jsonl',{'evidence_id':'synthetic-retry','status':'rejected','reason':['spread_too_wide']})
        regenerated={**row,'dossier_hash':'b'*64}
        storage.append_jsonl(self.root/state.CANDIDATES_STREAM,regenerated)
        with patch.object(radar,'candidate_preflight',return_value=[]),patch.object(radar,'qualified',return_value=True):
            result=radar.reusable_fresh_candidate(self.root/state.CANDIDATES_STREAM,self.root/state.REVIEWS_STREAM,now=NOW)
            self.assertIsNotNone(result)
            self.assertEqual(result['dossier_hash'],row['dossier_hash'])
            (self.root/'private/broker_baseline.json').write_text(json.dumps({'preexisting_symbols':['ACME']}))
            self.assertIsNone(radar.reusable_fresh_candidate(self.root/state.CANDIDATES_STREAM,self.root/state.REVIEWS_STREAM,now=NOW))

    def test_mixed_missing_new_primary_does_not_hide_its_transport_failure(self):
        self.spend()
        (self.root/'private/broker_baseline.json').write_text(json.dumps({'preexisting_symbols':['NEXT']}))
        missing=self.scouts[0]['urls'][0].replace('000001','000006')
        self.scouts[0]['urls'].append(missing)
        def gather(urls,*,diagnostics,**kwargs):
            diagnostics.append({'url':missing,'domain':'www.sec.gov','reason':'source_fetch_failed'})
            return self.bundles[0]
        with self.assertRaises(radar.ResearchFailure) as caught:
            self.run_research(overrides=[(radar,'gather_evidence',{'side_effect':gather})])
        self.assertEqual(caught.exception.code,'research_source_retrieval_failed')
        self.assertEqual(self.synthesized,[])

    def test_active_context_cannot_regress_to_empty_legacy_state(self):
        context=state.load_policy_context(self.root)
        for path in (self.root/'private').glob('trading_journal.sqlite3*'):path.unlink()
        (self.root/state.POLICY_STREAM).unlink()
        with self.assertRaises(state.OpportunityStateError):state.refresh_policy_context(context)

    def test_current_resolution_cannot_disagree_with_index_issuer(self):
        from dataclasses import replace
        r=self.resolutions[0]
        changed=replace(r,issuer=replace(r.issuer,legal_name='Different Fictional Issuer Inc.'))
        result=state.candidate_policy(state.load_policy_context(self.root),changed,symbol='ACME')
        self.assertEqual((result.outcome,result.reason),('unknown','opportunity_identity_conflict'))

    def test_direct_intake_strips_forged_authority_and_blocks_unknown(self):
        forged={'symbol':'NEXT','opportunity_identity':identity.candidate_identity(self.resolutions[1]),'event_id':self.resolutions[1].event_id,'allowance_id':'forged','reopening_claim':{'approved':True}}
        with self.assertRaises(radar.CandidateRejection) as caught:
            radar.prepare_candidate(forged,{},verify_sources=False,ledger_path=self.root/'order_ledger.jsonl')
        self.assertEqual(caught.exception.code,'opportunity_identity_unknown')


if __name__=='__main__':unittest.main()
