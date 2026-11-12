"""v3 Radar exercises existing shortlist flow, not an alternate research stub."""
import argparse
import copy
import importlib.util
import io
import json
import unittest
from unittest.mock import patch
from offline_test_guard import install
install()
import test_opportunity_radar as radar_fixtures
from retained_article import original_text,retain_article
import alpha_radar as radar
import research_memory as memory
import research_memory_transition as transition


class MemoryRadarTests(unittest.TestCase):
    run_research=radar_fixtures.RadarPolicyTests.run_research
    def setUp(self):
        radar_fixtures.RadarPolicyTests.setUp(self)
        for bundle in self.bundles:
            for i,p in enumerate(bundle):
                bundle[i]=retain_article(p,original_text(p) or p['text'],representation='fixture:complete-text:v1')
        self.cfg={'broker_mode':'paper','max_research_age_minutes':60}
        (self.root/'autonomy_config.json').write_text(json.dumps(self.cfg))
        m=transition.prepare_manifest(self.root,source_revision='f'*40,rule_version='r1')
        transition.apply(self.root,m,approved_manifest_sha256=transition.manifest_digest(m))

    def api(self):
        self.assertTrue(hasattr(radar,'research_memory_for_bundle'),'Radar exact-bundle adapter missing')
        return radar.research_memory_for_bundle

    def seed_first_no_setup(self):
        info=self.api()(self.root,issuer='CIK:0001999999',pages=self.bundles[0],
                        now=radar.dt.datetime.now(radar.dt.timezone.utc).isoformat(),rule_version='r1')
        memory.complete(self.root,key=info['key'],stage='synthesis',rule_version='r1',
            capture_refs=tuple(info['capture_refs']),
            result={'none_reason':'no_fresh_setup','publication_fingerprint':info['publication_fingerprint']},
            disposition='no_setup',completed_at=radar.dt.datetime.now(radar.dt.timezone.utc).isoformat())

    def test_unknown_formal_period_reaches_normal_synthesis(self):
        p=self.bundles[0][0];raw=original_text(p).replace('DocumentFiscalPeriodFocus','UnsupportedPeriodFocus')
        self.bundles[0][0]=retain_article(p,raw)
        result=self.run_research()
        self.assertEqual(result['symbol'],'ACME')
        self.assertEqual(self.synthesized,['ACME'])
        self.assertNotIn('opportunity_identity',result)

    def test_exact_completed_bundle_advances_shortlist_without_more_discovery(self):
        self.seed_first_no_setup()
        result=self.run_research()
        self.assertEqual(result['symbol'],'NEXT')
        self.assertEqual(self.synthesized,['NEXT'])
        self.assertEqual(self.discovery_calls,1)

    def test_new_second_document_is_not_suppressed_by_shared_primary(self):
        self.seed_first_no_setup();p=self.bundles[0][1]
        self.bundles[0][1]=retain_article(p,original_text(p)+' New independently reported information.')
        self.assertEqual(self.run_research()['symbol'],'ACME')
        self.assertEqual(self.synthesized,['ACME'])

    def test_acquisition_and_historical_merger_language_do_not_divert_v3(self):
        self.scouts[0]['catalyst']='Acquisition announcement and new results'
        p=self.bundles[0][0]
        self.bundles[0][0]=retain_article(p,original_text(p)+' Historical agreement and plan of merger.')
        self.assertEqual(self.run_research()['symbol'],'ACME')
        self.assertEqual(self.synthesized,['ACME'])

    def test_all_duplicate_is_healthy_no_new_work(self):
        self.seed_first_no_setup();self.scouts=self.scouts[:1];self.bundles=self.bundles[:1]
        result=self.run_research()
        self.assertEqual(result,{'status':'none','none_reason':'no_new_eligible_opportunity'})
        self.assertEqual(self.synthesized,[])

    def test_broken_cache_runs_uncached_without_identity_permission(self):
        (self.root/'private/research_memory.jsonl').write_text('broken-cache\n')
        self.assertEqual(self.run_research()['symbol'],'ACME')
        self.assertEqual(self.synthesized,['ACME'])

    def test_persisted_v3_candidate_reuse_and_fallback_share_completed_review_guard(self):
        import entry_authority
        import research_mode
        import sqlite_ledger as storage
        from test_opportunity_execution import _dossier
        prepared=self.run_research();work=prepared.pop('_memory_work')
        prepared['candidate_id']='synthetic-v3-radar'
        prepared['sources_verified_at']=radar.dt.datetime.now(radar.dt.timezone.utc).isoformat()
        radar._final_policy_check(prepared)
        bound=entry_authority.bind_candidate(self.root,prepared,context=research_mode.context(self.root))
        bound['dossier_hash']=_dossier(bound);radar.append(bound)
        radar._complete_memory(work,{'dossier_hash':bound['dossier_hash']},'qualified')
        entry_authority.validate_candidate(self.root,bound)
        with patch.object(radar,'candidate_preflight',return_value=[]),patch.object(radar,'qualified',return_value=True):
            self.assertEqual(radar.reusable_fresh_candidate(self.root/'candidates.jsonl',self.root/'private/reviews.jsonl'),dict(bound))
            notes=storage.read_jsonl_stream_readonly(self.root/'private/research_diagnostics.jsonl')
            self.assertEqual(sum(r.get('outcome')=='new_dossier_qualified' for r in notes),1)
            self.assertEqual(sum(r.get('outcome')=='completed_dossier_reused' for r in notes),1)
            storage.append_jsonl(self.root/'private/reviews.jsonl',{'dossier_hash':bound['dossier_hash'],'reviews':[{'action':'HOLD'}]})
            self.assertIsNone(radar.reusable_fresh_candidate(self.root/'candidates.jsonl',self.root/'private/reviews.jsonl'))
            self.assertIsNone(radar.fresh_verified_candidate(self.root/'candidates.jsonl'))

    def stored_qualified(self,*,verified_minutes_ago=0):
        import entry_authority,research_mode
        from test_opportunity_execution import _dossier
        prepared=self.run_research();work=prepared.pop('_memory_work')
        prepared['candidate_id']='synthetic-v3-cache'
        prepared['sources_verified_at']=(radar.dt.datetime.now(radar.dt.timezone.utc)-radar.dt.timedelta(minutes=verified_minutes_ago)).isoformat()
        radar._final_policy_check(prepared)
        bound=entry_authority.bind_candidate(self.root,prepared,context=research_mode.context(self.root))
        bound['dossier_hash']=_dossier(bound);radar.append(bound)
        radar._complete_memory(work,{'dossier_hash':bound['dossier_hash']},'qualified')
        self.synthesized.clear()
        return bound,work

    def test_malformed_completed_review_is_not_uncached_research_permission(self):
        import sqlite_ledger as storage
        bound,work=self.stored_qualified()
        storage.append_jsonl(self.root/'private/reviews.jsonl',{'dossier_hash':bound['dossier_hash'],'reviews':'malformed'})
        from opportunity_state import OpportunityStateError
        with self.assertRaises(OpportunityStateError):self.run_research()
        self.assertEqual(self.synthesized,[])

    def test_qualified_hit_returns_exact_dossier_without_synthesis_or_restamping(self):
        bound,work=self.stored_qualified()
        result=self.run_research()
        self.assertEqual(dict(result),dict(bound))
        self.assertEqual(self.synthesized,[])

    def test_qualified_hit_respects_execution_reserve_and_current_preflight(self):
        bound,work=self.stored_qualified(verified_minutes_ago=60-radar.EXECUTION_FRESHNESS_RESERVE_MINUTES+1)
        with patch.object(radar,'candidate_preflight',return_value=[]),patch.object(radar,'qualified',return_value=True):
            info=self.api()(self.root,issuer='CIK:0001999999',pages=self.bundles[0],
                now=radar.dt.datetime.now(radar.dt.timezone.utc).isoformat(),rule_version='r1')
        self.assertNotEqual(info['status'],'hit')

    def test_cached_dossier_cli_never_rehashes_or_appends_and_catches_late_hold(self):
        import sqlite_ledger as storage
        bound,work=self.stored_qualified()
        raw=radar._MemoryReusedCandidate(bound)
        before=storage.read_jsonl_stream_readonly(self.root/'candidates.jsonl')
        with patch.object(radar,'reusable_fresh_candidate',return_value=None),patch.object(radar,'live_research',return_value=raw),patch.object(radar,'candidate_preflight',return_value=[]),patch.object(radar,'qualified',return_value=True),patch('sys.stdout',new_callable=io.StringIO) as out:
            self.assertEqual(radar.main_with_args(argparse.Namespace(dry_run_fixture=False)),0)
            self.assertIn('reused_fresh_candidate ACME',out.getvalue())
            storage.append_jsonl(self.root/'private/reviews.jsonl',{'dossier_hash':bound['dossier_hash'],'reviews':[{'action':'HOLD'}]})
            out.truncate(0);out.seek(0)
            self.assertEqual(radar.main_with_args(argparse.Namespace(dry_run_fixture=False)),0)
            self.assertIn('no_new_eligible_opportunity',out.getvalue())
        self.assertEqual(storage.read_jsonl_stream_readonly(self.root/'candidates.jsonl'),before)

    def test_qualified_hit_respects_current_preflight_refusal(self):
        bound,work=self.stored_qualified()
        with patch.object(radar,'candidate_preflight',return_value=['source_stale']),patch.object(radar,'qualified',return_value=True):
            info=self.api()(self.root,issuer='CIK:0001999999',pages=self.bundles[0],
                now=radar.dt.datetime.now(radar.dt.timezone.utc).isoformat(),rule_version='r1')
        self.assertNotEqual(info['status'],'hit')

    def test_real_gather_recovery_and_rescue_deliver_acquisition_to_ordinary_intake(self):
        real_gather=radar.gather_evidence;real_recovery=radar.recover_publications
        real_filter=radar.filter_evidence;real_rescue=radar.post_fetch_rescue_candidate
        self.scouts=self.scouts[:1];self.bundles=self.bundles[:1]
        secondary=self.bundles[0][1]
        self.scouts[0]['catalyst']='Acquisition and current results'
        primary=self.bundles[0][0]
        primary['text']=original_text(primary)
        primary['published_at']='2026-10-21T12:00:00Z'
        pages={p['url']:p for p in self.bundles[0]};calls=[]
        def fetch(url,*args):calls.append(url);return copy.deepcopy(pages[url])
        self.scouts[0]['urls']=self.scouts[0]['urls'][:1]
        with patch.object(radar,'fetch_source',side_effect=fetch),patch.object(radar,'gateway_rescue_url',return_value=secondary['url']):
            result=self.run_research(overrides=[(radar,'gather_evidence',{'side_effect':real_gather}),
                (radar,'recover_publications',{'side_effect':real_recovery}),
                (radar,'filter_evidence',{'side_effect':real_filter}),
                (radar,'post_fetch_rescue_candidate',{'side_effect':real_rescue})])
        self.assertEqual(result['symbol'],'ACME')
        self.assertEqual(self.synthesized,['ACME'])
        self.assertEqual(set(calls),set(pages))
        self.assertEqual(self.discovery_calls,1)

    def test_direct_and_saved_intake_keep_ordinary_gates_and_reject_raw_envelopes(self):
        c={'symbol':'ACME','catalyst':'Acquisition announcement','event_id':'forged','research_transition_id':'forged'}
        with patch.object(radar,'candidate_preflight',return_value=[]),patch.object(radar,'qualified',return_value=True),patch.object(radar,'source_verification_result',return_value={'passed':True}):
            prepared=radar.prepare_candidate(c,self.cfg,ledger_path=self.root/'order_ledger.jsonl')
            self.assertNotIn('research_transition_id',prepared)
            self.assertNotIn('event_id',prepared)
            radar._final_policy_check(prepared)
            with self.assertRaises(radar.CandidateRejection):radar.prepare_candidate({**c,'status':'research_only'},self.cfg,ledger_path=self.root/'order_ledger.jsonl')
        with patch.object(radar,'candidate_preflight',return_value=['near_term_earnings']):
            with self.assertRaisesRegex(radar.CandidateRejection,'near_term_earnings'):radar.prepare_candidate(c,self.cfg,ledger_path=self.root/'order_ledger.jsonl')
        with patch.object(radar,'candidate_preflight',return_value=[]),patch.object(radar,'qualified',return_value=True),patch.object(radar,'source_verification_result',return_value={'passed':False}):
            with self.assertRaisesRegex(radar.CandidateRejection,'research_source_verification_failed'):radar.prepare_candidate(c,self.cfg,ledger_path=self.root/'order_ledger.jsonl')

    def test_expired_qualified_cache_hit_cannot_return_success(self):
        bound,work=self.stored_qualified();adapter=radar.research_memory_for_bundle
        import time
        clock=[time.monotonic()]
        def delayed(*args,**kwargs):
            result=adapter(*args,**kwargs);self.assertEqual(result['status'],'hit');clock[0]+=10000.0;return result
        with patch.object(radar,'monotonic',side_effect=lambda:clock[0]),patch.object(radar,'research_memory_for_bundle',side_effect=delayed):
            with self.assertRaises(radar.ResearchFailure):self.run_research()
        self.assertEqual(self.synthesized,[])

    def test_conflicting_explicit_cik_never_produces_cache_identity(self):
        import radar_memory
        original=self.bundles[0][0];raw=original_text(original)
        conflict=retain_article(original,raw.replace('>1999999<','>1888888<').replace('>0001999999<','>0001888888<'),representation='fixture:complete-text:v1')
        self.assertNotEqual(original_text(conflict),raw)
        with self.assertRaises(ValueError):radar_memory.issuer_for_pages('ACME',[original,conflict])
        with self.assertRaises(ValueError):self.api()(self.root,issuer='CIK:0001999999',pages=[original,conflict],
            now=radar.dt.datetime.now(radar.dt.timezone.utc).isoformat(),rule_version='r1')

    def test_changed_bundle_reuses_completed_document_stage_but_runs_new_synthesis(self):
        import radar_memory
        self.seed_first_no_setup()
        p=self.bundles[0][1]
        self.bundles[0][1]=retain_article(p,original_text(p)+' Newly published facts.',representation='fixture:complete-text:v1')
        self.assertTrue(hasattr(radar_memory,'_process_document'),'document-stage producer/consumer missing')
        process=radar_memory._process_document
        with patch.object(radar_memory,'_process_document',wraps=process) as calls:
            result=self.run_research()
        self.assertEqual(result['symbol'],'ACME')
        self.assertEqual(self.synthesized,['ACME'])
        self.assertEqual(calls.call_count,1)
        import sqlite_ledger as storage
        rows=storage.read_jsonl_stream_readonly(self.root/'private/research_diagnostics.jsonl')
        self.assertEqual(sum(r.get('count',0) for r in rows if r.get('outcome')=='document_stage_reused'),1)

    def test_retry_resource_discovery_never_waits_past_cache_deadline_on_writer_lock(self):
        import fcntl,threading,time,sqlite_ledger as storage,radar_memory
        self.seed_first_no_setup()
        held=threading.Event()
        def writer():
            with storage._lock_path(storage.database_path(self.root/'order_ledger.jsonl')).open('a+') as lock:
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX);held.set();time.sleep(1.0)
        thread=threading.Thread(target=writer);thread.start();held.wait(2)
        start=time.monotonic()
        try:
            result=radar_memory.resource_issuers(self.root,self.scouts[0]['urls'],
                radar.dt.datetime.now(radar.dt.timezone.utc).isoformat(),start+0.05)
            elapsed=time.monotonic()-start
        finally:thread.join(2)
        self.assertLess(elapsed,0.6)
        self.assertEqual(result,{})

    def test_warm_cache_rechecks_current_redirect_ownership(self):
        self.seed_first_no_setup();p=self.bundles[0][0]
        for returned in ('https://other.example/unrelated',p['url']+'?redirected=1'):
            with self.subTest(returned=returned):
                changed=retain_article({**p,'returned_url':returned},original_text(p),representation=p['_retained_article']['representation'])
                self.assertIsNotNone(original_text(changed))
                info=self.api()(self.root,issuer='CIK:0001999999',pages=[changed,self.bundles[0][1]],
                    now=radar.dt.datetime.now(radar.dt.timezone.utc).isoformat(),rule_version='r1')
                self.assertNotEqual(info['status'],'hit');self.assertIsNone(info.get('key'))

    def test_mixed_proposed_sources_are_deduplicated_before_synthesis_but_adapter_conflict_refuses(self):
        import radar_memory
        self.bundles[0].append(copy.deepcopy(self.bundles[1][0]));self.bundles=self.bundles[:1]
        self.scouts=self.scouts[:1];self.scouts[0]['urls']=[p['url'] for p in self.bundles[0]]
        _,selected=radar.select_candidate_evidence(self.scouts,self.bundles[0])
        self.assertEqual([p['url'] for p in selected],[p['url'] for p in self.bundles[0][:2]])
        with patch.object(radar,'gateway_rescue_url',return_value=None):result=self.run_research()
        self.assertEqual(result['symbol'],'ACME');self.assertEqual(self.synthesized,['ACME'])
        with self.assertRaises(radar_memory.IssuerConflict):
            self.api()(self.root,issuer='CIK:0001999999',pages=self.bundles[0],
                now=radar.dt.datetime.now(radar.dt.timezone.utc).isoformat(),rule_version='r1')

    def test_live_adapter_conflict_has_typed_refusal_before_synthesis(self):
        import radar_memory
        with patch.object(radar,'research_memory_for_bundle',side_effect=radar_memory.IssuerConflict('conflicting_explicit_issuer')):
            with self.assertRaisesRegex(radar.CandidateRejection,'research_source_attribution_conflict'):self.run_research()
        self.assertEqual(self.synthesized,[])

    def test_failure_cache_write_and_complete_diagnostic_inherit_original_deadline(self):
        import fcntl,threading,time,sqlite_ledger as storage,radar_memory
        self.seed_first_no_setup();issuer='CIK:0001999999';url='https://news.example/terminal-deadline'
        threads=[]
        def hold():
            ready=threading.Event()
            def writer():
                with storage._lock_path(storage.database_path(self.root/'order_ledger.jsonl')).open('a+') as lock:
                    fcntl.flock(lock.fileno(),fcntl.LOCK_EX);ready.set();time.sleep(0.8)
            thread=threading.Thread(target=writer);threads.append(thread);thread.start();self.assertTrue(ready.wait(2))
        def failed(*args,**kwargs):hold();raise TimeoutError('synthetic source timeout')
        try:
            start=time.monotonic()
            with patch.object(radar,'fetch_source',side_effect=failed),patch.object(radar,'fetch_source_via_gateway',return_value=None):
                self.assertEqual(radar.gather_evidence([url],memory_issuers={url:issuer},collection_deadline=start+0.1),[])
            write_elapsed=time.monotonic()-start
        finally:
            for thread in threads:thread.join(2)
        info=self.api()(self.root,issuer=issuer,pages=self.bundles[0],
            now=radar.dt.datetime.now(radar.dt.timezone.utc).isoformat(),rule_version='r1')
        hold();start=time.monotonic()
        try:
            radar._complete_memory(radar_memory.MemoryWork(self.root,info,'r1',start+0.1),{'none_reason':'no_fresh_setup'},'no_setup')
            diagnostic_elapsed=time.monotonic()-start
        finally:
            for thread in threads:thread.join(2)
        with self.subTest(path='failure_write'):self.assertLess(write_elapsed,0.5)
        with self.subTest(path='completion_diagnostic'):self.assertLess(diagnostic_elapsed,0.5)

    def test_source_cooldown_skips_only_that_exact_transport(self):
        issuer='CIK:0001999999';url=self.bundles[0][0]['url'];alternate='https://news.example/alternate'
        now=radar.dt.datetime.now(radar.dt.timezone.utc).isoformat()
        memory.note_failure(self.root,issuer=issuer,url=url,reason='source_fetch_timeout',failed_at=now)
        calls=[];diagnostics=[]
        def fetch(value,*args):
            calls.append(value)
            return {'url':value,'title':'Synthetic source','text':'Synthetic report '*80}
        with patch.object(radar,'fetch_source',side_effect=fetch):
            pages=radar.gather_evidence([url,alternate],diagnostics=diagnostics,
                collection_budget_seconds=2,memory_issuers={url:issuer,alternate:issuer})
        self.assertEqual(calls,[alternate])
        self.assertEqual([p['url'] for p in pages],[alternate])
        self.assertIn('source_retry_cooldown',[d['reason'] for d in diagnostics])

    def test_transport_failure_is_recorded_and_next_exact_fetch_cools_down(self):
        issuer='CIK:0001999999';url=self.bundles[0][0]['url']
        calls=[]
        def fail(value,*args):
            calls.append(value)
            raise TimeoutError('synthetic transport timeout')
        diagnostics=[]
        with patch.object(radar,'fetch_source',side_effect=fail),patch.object(radar,'fetch_source_via_gateway',return_value=None):
            self.assertEqual(radar.gather_evidence([url],diagnostics=diagnostics,collection_budget_seconds=2,memory_issuers={url:issuer}),[])
            self.assertEqual(radar.gather_evidence([url],diagnostics=diagnostics,collection_budget_seconds=2,memory_issuers={url:issuer}),[])
        self.assertEqual(calls,[url])
        rows=memory._rows(self.root)
        self.assertTrue(any(r.get('record_type')=='failure' and r.get('url')==url for r in rows))
        self.assertIn('source_retry_cooldown',[d['reason'] for d in diagnostics])

    def test_raw_observation_envelope_is_not_a_v3_candidate(self):
        radar._run_policy_context(self.root)
        with self.assertRaises(radar.CandidateRejection):
            radar._strip_policy_metadata({'status':'research_only','lead_id':'al1:'+'a'*64})


if __name__=='__main__':unittest.main()
