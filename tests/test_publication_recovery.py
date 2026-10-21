"""Synthetic offline recovery tests; no network or live model invocation."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import alpha_radar as radar
import publication_observation as pub
import publication_recovery as recovery

NOW = dt.datetime(2026, 10, 21, 16, tzinfo=dt.timezone.utc)
BODY = 'The company reported revenue growth and raised its outlook. ' * 4


def page(url, **extra):
    return dict(url=url, title='Results', text='Results\nPublished: October 21, 2026\n'+BODY, **extra)


def observation(p):
    return pub.build_observation(p, value='2026-10-21',precision='day',
        support='Published: October 21, 2026',location='header', basis='llm_grounded')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]/'test_artifacts/publication-hybrid/task4'
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)/'cache.json'
        self.clock = [100.0]
        self.patch = patch.object(recovery, 'monotonic', side_effect=lambda:self.clock[0])
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.wall = patch.object(recovery, 'utc_now', return_value=NOW)
        self.wall.start(); self.addCleanup(self.wall.stop)
        self.candidates = [{'symbol':str(i), 'urls':[f'https://a{i}.example/x',f'https://b{i}.example/x']} for i in range(5)]
        self.pages = [page(u) for c in self.candidates for u in c['urls']]
        self.state = recovery.RecoveryState()
        self.fetch = Mock(side_effect=AssertionError('unexpected fetch'))
        self.model = Mock(side_effect=lambda pages, **kw:({p['url']:observation(p) for p in pages}, []))

    def run_recovery(self, pages=None, accepted=None, deterministic=False, **kwargs):
        # Existing tests isolate the MODEL/cache/refetch path. Deterministic
        # bounded preparation has its own real-path regressions below; large
        # capture regressions continue to use the real helper unchanged.
        real = recovery.candidate_recovery_page
        def prepare(p, **kw):
            return real(p, **kw) if deterministic or len(p.get('text','')) > 6000 else None
        with patch.object(recovery, 'candidate_recovery_page', side_effect=prepare):
            return recovery.recover_publications(self.candidates, self.pages if pages is None else pages,
                accepted or [], state=self.state, overall_deadline=690, downstream_reserve=80,
                cache_path=self.cache, fetcher=self.fetch, interpreter=self.model, **kwargs)

    def write_cache(self, p, stamp='2026-10-21T15:00:00Z'):
        self.cache.write_text(json.dumps({p['url']:{'checked_at':stamp,'page':p}}))

    def test_fresh_scoped_refetch_is_parsed_before_model(self):
        old = dict(self.pages[0],text='Results\n'+BODY)
        self.write_cache(old)
        self.fetch.side_effect=lambda *a:self.pages[0]
        updated, _ = self.run_recovery(pages=[old], deterministic=True)
        self.fetch.assert_called_once()
        self.model.assert_not_called()
        self.assertEqual(updated[0]['publication_precision'],'day')

    def test_preparation_defers_model_until_rescue_and_counts_only_active_work(self):
        unknown = dict(self.pages[0], text='Results\n' + BODY)
        delivered, _ = self.run_recovery(pages=[unknown], allow_model=False)
        self.model.assert_not_called()
        self.assertFalse(self.state.attempted_model)
        self.clock[0] += 93  # Rescue waiting is evidence work, NOT recovery work.
        late = dict(self.pages[1], text='Results\n' + BODY)
        seen = []
        def model(pages, **kw):
            seen.extend(p['url'] for p in pages)
            self.assertLessEqual(kw['deadline'] - self.clock[0], 90)
            return {}, []
        self.model.side_effect = model
        self.run_recovery(pages=[*delivered, late])
        self.assertEqual(seen, [unknown['url'], late['url']])
        self.assertEqual(self.model.call_count, 1)
        self.run_recovery(pages=[late])
        self.assertEqual(self.model.call_count, 1)

    def test_bounded_deterministic_page_preserves_original_hash_and_hard_refusal(self):
        p = self.pages[0]
        updated, _ = self.run_recovery(pages=[p], allow_model=False, deterministic=True)
        self.assertEqual(updated[0]['publication_precision'], 'day')
        import hashlib
        self.assertEqual(updated[0]['publication_observation']['content_sha256'], hashlib.sha256(p['text'].encode()).hexdigest())
        self.model.assert_not_called()
        refused = dict(p, publication_observation=None)
        updated, _ = self.run_recovery(pages=[refused], allow_model=False)
        self.assertIsNone(updated[0]['publication_observation'])

    def test_advancing_preparation_clock_debits_cumulative_allowance_across_rescue(self):
        p=dict(self.pages[0],text='No publication cue\n'+BODY)
        def slow(*a, **kw):self.clock[0]+=20;return None
        with patch.object(recovery,'candidate_recovery_page',side_effect=slow):
            self.run_recovery(pages=[p],allow_model=False,deterministic=True)
        self.assertEqual(self.state.remaining_seconds,70)
        self.clock[0]+=93
        def model(pages, *, deadline):
            self.assertEqual(deadline,self.clock[0]+70)
            self.clock[0]+=30
            return {}, []
        self.model.side_effect=model
        self.run_recovery(pages=[p])
        self.assertEqual(self.state.remaining_seconds,40)
        self.assertEqual(self.model.call_count,1)

    def test_empty_shortlist_and_empty_rescue_never_launch_model(self):
        self.candidates=[]
        self.run_recovery(pages=[])
        self.run_recovery(pages=[])
        self.model.assert_not_called()
        self.assertFalse(self.state.attempted_model)

    def test_late_deferred_deterministic_page_does_not_reopen_spent_batch(self):
        self.run_recovery(pages=[self.pages[0]])
        self.assertEqual(self.model.call_count,1)
        updated,_=self.run_recovery(pages=[self.pages[1]],deterministic=True)
        self.assertEqual(updated[0]['publication_precision'],'day')
        self.assertEqual(self.model.call_count,1)

    def test_known_legacy_instant_is_not_reinterpreted_even_when_future(self):
        p=dict(self.pages[0],published_at='2028-01-01T00:00:00Z')
        updated,_=self.run_recovery(pages=[p])
        self.assertEqual(updated,[p]);self.model.assert_not_called()
        self.assertEqual(radar.filter_evidence(updated,now=NOW)[0],[])

    def test_five_candidates_receive_one_page_before_any_second(self):
        selected = recovery.choose_recovery_pages(self.candidates,self.pages,[])
        self.assertEqual([p['url'] for p in selected],
            [c['urls'][0] for c in self.candidates]+[c['urls'][1] for c in self.candidates])
        self.assertEqual(len({p['url'] for p in selected}),10)

    def test_shared_urls_and_greedy_candidate_do_not_starve_later_candidates(self):
        shared=self.candidates[0]['urls'][0]
        self.candidates[1]['urls'].insert(0,shared)
        self.candidates[0]['urls'] += [f'https://extra{i}.example/x' for i in range(20)]
        selected=recovery.choose_recovery_pages(self.candidates,self.pages+[page(u) for u in self.candidates[0]['urls'][2:]],[])
        self.assertEqual([p['url'] for p in selected[:5]], [c['urls'][0 if i!=1 else 1] for i,c in enumerate(self.candidates)])
        self.assertEqual(len(selected),10)

    def test_complete_bundles_admissible_duplicates_and_errors_are_skipped(self):
        accepted=[dict(p,published_at='2026-10-21T10:00:00Z') for p in self.pages[:2]]
        bad=dict(self.pages[2],text='Access denied',title='Access denied')
        refused=dict(self.pages[4],publication_observation=None)
        selected=recovery.choose_recovery_pages(self.candidates,[*accepted,bad,self.pages[3],refused,*self.pages[5:]],accepted)
        urls=[p['url'] for p in selected]
        self.assertNotIn(bad['url'],urls);self.assertNotIn(refused['url'],urls)
        self.assertNotIn(accepted[0]['url'],urls);self.assertIn(self.pages[3]['url'],urls)

    def test_existing_publisher_identity_is_used_for_second_pass(self):
        self.candidates=[{'urls':['https://one.company.co.uk/x','https://two.company.co.uk/y','https://independent.co.uk/x']}]
        pages=[page(u) for u in self.candidates[0]['urls']]
        selected=recovery.choose_recovery_pages(self.candidates,pages,[])
        self.assertEqual([p['url'] for p in selected],[pages[0]['url'],pages[2]['url']])

    def test_one_model_batch_across_deferred_opportunities_and_no_mutation(self):
        original=copy.deepcopy(self.pages)
        updated, diagnostics=self.run_recovery()
        self.run_recovery(pages=[page('https://later.example/x')])
        self.assertEqual(self.model.call_count,1)
        self.assertTrue(self.state.attempted_model)
        self.assertEqual(self.pages,original)
        accepted,_=radar.filter_evidence(updated,now=NOW)
        self.assertEqual(len(accepted),10)
        self.assertTrue(all(p['publication_precision']=='day' for p in accepted))

    def test_success_cache_replays_bound_proof_without_refreshing_checked_at(self):
        p=self.pages[0];cached=dict(p,publication_observation=observation(p),published_at='2026-10-21',publication_precision='day',publication_basis='llm_grounded')
        self.write_cache(cached)
        updated,_=self.run_recovery(pages=[p])
        self.model.assert_not_called();self.fetch.assert_not_called()
        self.assertEqual(updated[0]['publication_observation'],cached['publication_observation'])
        self.assertEqual(json.loads(self.cache.read_text())[p['url']]['checked_at'],'2026-10-21T15:00:00Z')

    def test_different_capture_cache_proof_miss_remains_model_eligible(self):
        # Cache proof mismatch is not a refusal on a genuinely different capture.
        for mutation in ('text','url','returned_url'):
            with self.subTest(mutation=mutation):
                self.state=recovery.RecoveryState()
                p=self.pages[0];cached=dict(p,publication_observation=observation(p))
                if mutation in ('text','url'):cached[mutation]+='changed'
                else:cached[mutation]='https://tampered.example/x'
                self.write_cache(cached)
                updated,_=self.run_recovery(pages=[p])
                self.assertTrue(pub.validate_observation(updated[0],updated[0]['publication_observation']))
                self.assertEqual(self.model.call_args.args[0][0]['text'],p['text'])
        self.assertEqual(self.model.call_count,3)

    def test_invalid_cached_proof_on_identical_capture_is_a_hard_refusal(self):
        p=self.pages[0]
        for mutation in ('parser_version','support'):
            with self.subTest(mutation=mutation):
                self.state=recovery.RecoveryState()
                self.model.reset_mock()
                invalid=dict(observation(p),**{mutation:'tampered'})
                self.write_cache(dict(p,publication_observation=invalid))
                updated,notes=self.run_recovery(pages=[p])
                self.assertEqual(updated[0]['publication_observation'],invalid)
                self.model.assert_not_called();self.fetch.assert_not_called()
                self.assertEqual(radar.filter_evidence(updated,now=NOW)[0],[])
                self.assertIn('hard_refusal',[n['reason'] for n in notes])

    def test_unknown_is_not_durable_negative_cache(self):
        p=self.pages[0];self.write_cache(p)
        self.fetch.return_value=p;self.fetch.side_effect=None
        self.model.side_effect=lambda *a,**k:({},[{'id':'p0','reason':'unknown'}])
        updated,_=self.run_recovery(pages=[p])
        self.assertNotIn('publication_observation',updated[0])
        self.assertNotIn('publication_observation',json.loads(self.cache.read_text())[p['url']]['page'])
        self.assertEqual(self.fetch.call_count,1)
        self.run_recovery(pages=[p]);self.assertEqual(self.fetch.call_count,1)

    def test_focused_success_cache_uses_original_capture_check_time(self):
        p=dict(self.pages[0],checked_at='2026-10-21T15:00:00Z')
        updated,_=self.run_recovery(pages=[p])
        entry=json.loads(self.cache.read_text())[p['url']]
        self.assertEqual(entry['checked_at'],'2026-10-21T15:00:00Z')
        self.assertEqual(entry['page']['publication_observation'],updated[0]['publication_observation'])

    def test_invalid_present_marker_is_never_removed_to_force_recovery(self):
        p=dict(self.pages[0],publication_observation=None)
        self.write_cache(dict(self.pages[0],publication_observation=observation(self.pages[0])))
        updated,_=self.run_recovery(pages=[p])
        self.assertIsNone(updated[0]['publication_observation'])
        self.model.assert_not_called()

    def test_expired_cache_observation_is_rechecked_for_freshness(self):
        p=page(self.pages[0]['url']);p['text']=p['text'].replace('October 21, 2026','April 1, 2026')
        obs=pub.build_observation(p,value='2026-04-01',precision='day',support='Published: April 1, 2026',location='header',basis='llm_grounded')
        self.write_cache(dict(p,publication_observation=obs))
        self.model.side_effect=lambda *a,**k:({},[])
        updated,_=self.run_recovery(pages=[p])
        self.assertNotIn('publication_observation',updated[0])

    def test_cache_load_counts_against_original_ninety_second_deadline(self):
        p=self.pages[0];self.write_cache(p)
        read=Path.read_text
        def slow(path,*a,**k):
            value=read(path,*a,**k);self.clock[0]+=90;return value
        with patch.object(Path,'read_text',slow):updated,notes=self.run_recovery(pages=[p])
        self.model.assert_not_called();self.fetch.assert_not_called()
        self.assertEqual(self.state.deadline,190)
        self.assertEqual(updated,[p])
        self.assertIn('timeout',[d['reason'] for d in notes])

    def test_refetch_preparation_and_validation_share_same_deadline(self):
        p=self.pages[0];self.write_cache(p)
        def fetch(url,timeout):
            self.assertEqual(timeout,90);self.clock[0]+=35;return p
        def model(pages,*,deadline):
            self.assertEqual(deadline,190);self.assertEqual(self.clock[0],135)
            self.clock[0]=190;return ({p['url']:observation(p)},[])
        self.fetch.side_effect=fetch;self.model.side_effect=model
        updated,notes=self.run_recovery(pages=[p])
        self.assertNotIn('publication_observation',updated[0])
        self.assertIn('timeout',[d['reason'] for d in notes])
        self.assertEqual(self.state.refreshed_urls,{p['url']})

    def test_selection_preparation_exhaustion_prevents_model_launch(self):
        p=self.pages[0]
        def filtering(pages,**kw):
            self.clock[0]+=30
            return radar.filter_evidence(pages,**kw)
        updated,notes=self.run_recovery(pages=[p],filter_pages=filtering)
        self.model.assert_not_called();self.fetch.assert_not_called()
        self.assertEqual(self.state.deadline,190)
        self.assertEqual(self.clock[0],190)  # Stop between prep operations too.
        self.assertNotIn('publication_observation',updated[0])
        self.assertIn('timeout',[d['reason'] for d in notes])

    def test_persistence_failure_is_not_silently_downgraded_to_model_abstention(self):
        p=self.pages[0];self.write_cache(p)
        self.fetch.side_effect=lambda *a:p
        with patch.object(Path,'replace',side_effect=OSError('private failure')):
            with self.assertRaises(OSError):self.run_recovery(pages=[p])

    def test_outer_deadline_reserves_downstream_and_never_restarts(self):
        self.clock[0]=570
        self.run_recovery(pages=[self.pages[0]])
        self.assertEqual(self.model.call_args.kwargs['deadline'],610)
        self.assertEqual(self.state.started_at,570)
        self.clock[0]=620
        self.run_recovery(pages=self.pages[2:4])
        self.assertEqual(self.state.deadline,610);self.assertEqual(self.model.call_count,1)

    def test_scoped_refetches_are_fair_and_capped_not_greedy_page_order(self):
        self.candidates[0]['urls'] += [f'https://extra{i}.example/x' for i in range(15)]
        pages=[*self.pages[:2],*[page(u) for u in self.candidates[0]['urls'][2:]],*self.pages[2:]]
        self.cache.write_text(json.dumps({p['url']:{'checked_at':'2026-10-21T15:00:00Z','page':p} for p in pages}))
        self.fetch.side_effect=lambda url, timeout:next(p for p in pages if p['url']==url)
        self.run_recovery(pages=pages)
        self.assertEqual([c.args[0] for c in self.fetch.call_args_list],
                         [c['urls'][0] for c in self.candidates]+[c['urls'][1] for c in self.candidates])
        self.assertEqual(len(self.model.call_args.args[0]),10)

    def test_cached_hard_refusal_cannot_be_reversed_using_same_lossy_capture(self):
        p=self.pages[0];self.write_cache(dict(p,publication_observation=None))
        updated,_=self.run_recovery(pages=[p])
        self.assertIsNone(updated[0]['publication_observation'])
        self.model.assert_not_called();self.fetch.assert_not_called()

    def test_later_unknowns_do_not_get_another_refetch_phase_after_model_attempt(self):
        p=self.pages[0];self.run_recovery(pages=[p])
        q=self.pages[1];self.write_cache(q)
        self.fetch.side_effect=lambda *a:q
        self.run_recovery(pages=[q])
        self.assertEqual(self.model.call_count,1);self.fetch.assert_not_called()

    def test_refetched_unchanged_text_does_not_reverse_known_refusal(self):
        p=dict(self.pages[0],publication_observation=None)
        self.write_cache(p)
        updated,_=self.run_recovery(pages=[p])
        self.assertIsNone(updated[0]['publication_observation'])
        self.fetch.assert_not_called();self.model.assert_not_called()

    def test_accepted_sources_are_retained_even_if_input_list_omits_them(self):
        good=dict(self.pages[0],published_at='2026-10-21T10:00:00Z')
        updated,_=self.run_recovery(pages=[self.pages[1]],accepted=[good])
        self.assertIn(good,updated)
        candidate,bundle=radar.select_candidate_evidence(self.candidates,radar.filter_evidence(updated,now=NOW)[0])
        self.assertEqual(candidate,self.candidates[0]);self.assertEqual(len(bundle),2)

    def test_explicit_fetch_error_and_unsupported_urls_do_not_consume_batch(self):
        bad=dict(self.pages[0],error='SECRET')
        wrong=page('file:///etc/passwd')
        candidates=[{'urls':[bad['url'],wrong['url']]}]
        self.assertEqual(recovery.choose_recovery_pages(candidates,[bad,wrong],[]),[])

    def test_failure_of_one_page_preserves_healthy_bundle(self):
        good=[dict(p,published_at='2026-10-21T10:00:00Z') for p in self.pages[:2]]
        self.model.side_effect=lambda *a,**k:({},[{'id':'p0','reason':'timeout'}])
        updated,notes=self.run_recovery(pages=[*good,*self.pages[2:]],accepted=good)
        candidate,bundle=radar.select_candidate_evidence(self.candidates,radar.filter_evidence(updated,now=NOW)[0])
        self.assertEqual(candidate,self.candidates[0]);self.assertEqual(len(bundle),2)
        self.assertIn('timeout',[d['reason'] for d in notes])

    def test_fetch_failure_is_local_and_diagnostics_do_not_leak(self):
        p=self.pages[0];self.write_cache(p)
        self.fetch.side_effect=TimeoutError('SECRET vendor prose')
        updated,notes=self.run_recovery(pages=[p,self.pages[1]])
        self.assertEqual(len(radar.filter_evidence(updated,now=NOW)[0]),2)
        self.assertIn('fetch_failed',[d['reason'] for d in notes])
        self.assertNotIn('SECRET',json.dumps(notes));self.assertNotIn(p['url'],json.dumps(notes))

    def test_large_candidate_projection_cannot_hide_original_conflicting_claim(self):
        deep = ('<meta property="article:published_time" content="2026-10-21">'
                + '<p>Filler text.</p>'*400
                + '\nPublished: October 20, 2026\n' + BODY)
        p = dict(self.pages[0], text=deep)
        self.assertIsNone(recovery.candidate_recovery_page(p, now=NOW, filter_pages=radar.filter_evidence))

    def test_oversized_page_gets_deterministic_candidate_recovery_without_model(self):
        # Pages beyond the 6000-char transport bound were previously
        # unservable. Bounded date-candidate extraction recovers them
        # deterministically; the model is never invoked.
        deep = ('<html><head><title>Results</title></head><body>'
                + '<p>Filler paragraph with no dates at all.</p>' * 130
                + '<meta property="article:published_time" content="2026-10-01T08:00:00-04:00">'
                + '<p>Filler paragraph with no dates at all.</p>' * 130
                + '</body></html>')
        self.assertGreater(len(deep), 6000)
        p = dict(page('https://issuer.example/x'), text=deep)
        updated, notes = self.run_recovery(pages=[p])
        self.model.assert_not_called(); self.fetch.assert_not_called()
        obs = updated[0].get('publication_observation')
        self.assertIsInstance(obs, dict)
        self.assertEqual((obs['value'], obs['precision']),
                         ('2026-10-01T08:00:00-04:00', 'instant'))
        self.assertIn('recovered_instant', [d['reason'] for d in notes])
        # The bounded candidate text is the canonical interpretation basis.
        self.assertLessEqual(len(updated[0]['text'].encode('utf-8')), 8192)

    def test_oversized_page_without_date_signal_stays_unresolved(self):
        deep = ('<html><body>' + '<p>Filler prose without dates.</p>' * 300
                + '</body></html>')
        self.assertGreater(len(deep), 6000)
        p = dict(page('https://issuer.example/x'), text=deep)
        updated, notes = self.run_recovery(pages=[p])
        self.model.assert_not_called()
        self.assertNotIn('publication_observation', updated[0])

    def test_review_i2_recovered_observation_hash_binds_original_capture(self):
        # I2 (fix round 6): the recovered observation's content_sha256 commits
        # the ORIGINAL capture bytes (the hash/witness basis), never the
        # stitched candidate document, which is interpretation input only.
        deep = ('<html><head><title>Results</title></head><body>'
                + '<p>Filler paragraph with no dates at all.</p>' * 130
                + '<meta property="article:published_time" content="2026-10-01T08:00:00-04:00">'
                + '<p>Filler paragraph with no dates at all.</p>' * 130
                + '</body></html>')
        p = dict(page('https://issuer.example/x'), text=deep)
        prepared = recovery.candidate_recovery_page(
            p, now=NOW, filter_pages=radar.filter_evidence)
        self.assertIsNotNone(prepared)
        obs = prepared['publication_observation']  # type: ignore[index]
        import hashlib
        self.assertEqual(obs['content_sha256'],
                         hashlib.sha256(deep.encode('utf-8')).hexdigest())
        self.assertNotEqual(obs['content_sha256'],
                            hashlib.sha256(prepared['text'].encode('utf-8')).hexdigest())
        # The stored observation still validates against the recovered page and
        # freshness evaluation runs on the same text basis as before.
        self.assertTrue(pub.validate_observation(prepared, obs))
        ok, _ = radar.filter_evidence([prepared], now=NOW)
        self.assertTrue(ok)

    def test_review_n1_recovery_ignores_injected_capture_sha256_field(self):
        # N1 (final whole-branch review): an attacker-injected `_capture_sha256`
        # on the page dict is never inherited; the recovered observation's
        # provenance digest is recomputed locally over the original capture.
        deep = ('<html><head><title>Results</title></head><body>'
                + '<p>Filler paragraph with no dates at all.</p>' * 130
                + '<meta property="article:published_time" content="2026-10-01T08:00:00-04:00">'
                + '<p>Filler paragraph with no dates at all.</p>' * 130
                + '</body></html>')
        p = dict(page('https://issuer.example/x'), text=deep,
                 _capture_sha256='e' * 64)
        prepared = recovery.candidate_recovery_page(
            p, now=NOW, filter_pages=radar.filter_evidence)
        self.assertIsNotNone(prepared)
        obs = prepared['publication_observation']  # type: ignore[index]
        import hashlib
        self.assertNotEqual(obs['content_sha256'], 'e' * 64)
        self.assertEqual(obs['content_sha256'],
                         hashlib.sha256(deep.encode('utf-8')).hexdigest())
        self.assertEqual(prepared.get('_capture_sha256'),
                         hashlib.sha256(deep.encode('utf-8')).hexdigest())
        self.assertTrue(pub.validate_observation(prepared, obs))

    def test_review_m1_candidate_recovery_shares_ten_page_ceiling(self):
        # M1 (fix round 6): candidate-recovery admissions count against the same
        # per-run ten-page fair-binding ceiling as model-path admissions.
        deep = ('<html><head><title>Results</title></head><body>'
                + '<p>Filler paragraph with no dates at all.</p>' * 130
                + '<meta property="article:published_time" content="2026-10-01T08:00:00-04:00">'
                + '<p>Filler paragraph with no dates at all.</p>' * 130
                + '</body></html>')
        pages = [dict(page(f'https://issuer{i}.example/x'), text=deep)
                 for i in range(12)]
        updated, notes = self.run_recovery(pages=pages)
        self.model.assert_not_called(); self.fetch.assert_not_called()
        reasons = [d['reason'] for d in notes]
        recovered = reasons.count('recovered_instant') + reasons.count('recovered_day')
        self.assertEqual(recovered, 10)
        self.assertEqual(reasons.count('recovered_page_limit'), 2)
        self.assertEqual(sum(1 for p in updated if 'publication_observation' in p), 10)

class RecoveryWiringTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'test_artifacts/publication-hybrid/task4'
        root.mkdir(parents=True,exist_ok=True,mode=0o700)
        temp=tempfile.TemporaryDirectory(dir=root);self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        clock=patch.object(radar,'ROOT',self.root);clock.start();self.addCleanup(clock.stop)

    def test_live_recovery_runs_actual_adapter_once_and_uses_configured_command_contract(self):
        import subprocess
        urls=['https://issuer.example/x','https://independent.example/x']
        pages=[page(u) for u in urls]
        scout={'symbol':'ABC','urls':urls}
        clock=[100.0];calls=[]
        def child(command, **kw):
            self.assertEqual(command,['discovery']);clock[0]+=10
            return subprocess.CompletedProcess(command,0,'scout','')
        def gather(*a,**kw):clock[0]+=40;return pages
        def runner(command, *, input, deadline):
            self.assertEqual(command,['publication']);self.assertEqual(deadline,240)
            payload=json.loads(input);calls.append(payload)
            clock[0]+=50
            return subprocess.CompletedProcess(command,0,json.dumps({'version':1,'results':[
                {'id':p['id'],'value':'2026-10-21','precision':'day',
                 'support':'Published: October 21, 2026','location':'header'} for p in payload['pages']]}).encode(),b'')
        def synth(cfg,selected,evidence,deadline,**kw):
            self.assertEqual(len(evidence),2)
            self.assertTrue(all(p['publication_basis']=='llm_grounded' for p in evidence))
            self.assertEqual(kw['enrichment_budget']['overall'],790)
            return {'status':'none'}
        with patch.object(recovery,'candidate_recovery_page',return_value=None), patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch.object(recovery,'monotonic',side_effect=lambda:clock[0]), patch('publication_interpreter.monotonic',side_effect=lambda:clock[0]), patch.object(radar,'discovery_command',return_value=['discovery']), patch.object(radar.subprocess,'run',side_effect=child), patch.object(radar,'scout_parse_result',return_value=([scout],{})), patch.object(radar,'record_scout_diagnostic'), patch.object(radar,'gather_evidence',side_effect=gather), patch.object(radar,'research_subprocess_command',return_value=['publication']) as factory, patch.object(radar,'run_publication_process',side_effect=runner), patch.object(radar,'synthesize_candidate',side_effect=synth), patch.object(radar,'record_research_diagnostics'), patch.object(radar,'post_fetch_rescue_candidate',return_value=[]) as rescue:
            result=radar.live_research({},intake=lambda c:c)
        self.assertEqual(result,{'status':'none'});self.assertEqual(len(calls),1)
        factory.assert_called_once_with('bot_room',max_turns=1,run_budget=45)
        rescue.assert_called_once()  # Collection now precedes the one model batch.

    def test_recovery_pauses_unspent_evidence_not_an_expired_absolute_clock(self):
        import subprocess
        urls=['https://issuer.example/x','https://independent.example/x']
        pages=[dict(page(u),text='No publication cue\n'+BODY) for u in urls];scout={'symbol':'ABC','urls':urls}
        clock=[100.0];rescue_deadlines=[]
        def gather(*a,**kw):clock[0]+=40;return pages
        def interpret(pages,*,deadline,**kw):clock[0]+=50;return {},[]
        def rescue(candidate,accepted,*,deadline,**kw):
            rescue_deadlines.append(deadline)
            clock[0]+=30
            return [dict(p,published_at='2026-10-21T10:00:00Z') for p in pages]
        with patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch.object(recovery,'monotonic',side_effect=lambda:clock[0]), patch.object(radar,'discovery_command',return_value=['discovery']), patch.object(radar.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'scout','')), patch.object(radar,'scout_parse_result',return_value=([scout],{})), patch.object(radar,'record_scout_diagnostic'), patch.object(radar,'gather_evidence',side_effect=gather), patch.object(radar,'interpret_publications',side_effect=interpret), patch.object(radar,'synthesize_candidate',return_value={'status':'none'}), patch.object(radar,'record_research_diagnostics'), patch.object(radar,'post_fetch_rescue_candidate',side_effect=rescue):
            result=radar.live_research({},intake=lambda c:c)
        self.assertEqual(result,{'status':'none'})
        self.assertEqual(rescue_deadlines,[280])  # 100 + 40 normal + 140 unspent; model now AFTER rescue.

    def test_recovery_diagnostics_are_strict_private_typed_and_correlated(self):
        radar.correlated_research_run(lambda:radar.record_research_diagnostics([
            {'stage':'publication_recovery','id':'p0','reason':'recovered_day','text':'SECRET'},
            {'stage':'publication_recovery','id':'p1','reason':'timeout'},
            {'stage':'publication_recovery','id':'batch','reason':'raw SECRET'},
        ]))()
        rows=[json.loads(line) for line in (self.root/'private/research_diagnostics.jsonl').read_text().splitlines()]
        self.assertEqual([r['reason'] for r in rows],['recovered_day','timeout'])
        self.assertEqual(rows[0]['stage'],'publication_recovery')
        self.assertEqual(rows[0]['run_id'],rows[1]['run_id'])
        self.assertNotIn('SECRET',json.dumps(rows))

    def test_fresh_direct_capture_must_change_before_reversing_cached_refusal(self):
        p=page('https://issuer.example/x');cache=self.root/'cache.json'
        cache.write_text(json.dumps({p['url']:{'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'page':dict(p,publication_observation=None)}}))
        with patch.object(radar,'fetch_source',return_value=p) as fetch:
            got=radar.gather_evidence([p['url']],cache_path=cache)
        fetch.assert_called_once()
        self.assertIsNone(got[0]['publication_observation'])
        self.assertEqual(radar.filter_evidence(got)[0],[])

    def test_identical_refetch_preserves_every_invalid_present_refusal_through_recovery(self):
        p=page('https://issuer.example/x')
        valid=observation(p)
        self.assertIsNotNone(valid)
        assert valid is not None
        markers=[None, {'version':'invalid'}, dict(valid,support='tampered'),
                 dict(valid,parser_version='old'), 'malformed', [], False]
        for marker in markers:
            with self.subTest(marker=marker):
                cache=self.root/'cache.json'
                cache.write_text(json.dumps({p['url']:{'checked_at':NOW.isoformat(),
                    'page':dict(p,publication_observation=marker)}}))
                model=Mock(side_effect=lambda pages,**kw:({q['url']:observation(q) for q in pages},[]))
                with patch.object(radar,'fetch_source',return_value=p) as fetch:
                    got=radar.gather_evidence([p['url']],cache_path=cache)
                fetch.assert_called_once()
                with patch.object(recovery,'utc_now',return_value=NOW):
                    updated,_=recovery.recover_publications([{'urls':[p['url']]}],got,[],
                        state=recovery.RecoveryState(),overall_deadline=recovery.monotonic()+100,
                        downstream_reserve=0,cache_path=cache,fetcher=Mock(),interpreter=model)
                model.assert_not_called()
                self.assertIn('publication_observation',got[0])
                self.assertEqual(got[0]['publication_observation'],marker)
                self.assertEqual(updated[0]['publication_observation'],marker)
                self.assertEqual(radar.filter_evidence(updated,now=NOW)[0],[])
                self.assertEqual(json.loads(cache.read_text())[p['url']]['page']['publication_observation'],marker)

    def test_valid_cached_proof_gathers_without_refetch_or_model_and_keeps_check_time(self):
        p=page('https://issuer.example/x')
        cached=dict(p,publication_observation=observation(p))
        stamp=dt.datetime.now(dt.timezone.utc).isoformat()
        cache=self.root/'cache.json'
        cache.write_text(json.dumps({p['url']:{'checked_at':stamp,'page':cached}}))
        with patch.object(radar,'fetch_source') as fetch:
            got=radar.gather_evidence([p['url']],cache_path=cache)
        fetch.assert_not_called()
        model=Mock()
        with patch.object(recovery,'utc_now',return_value=NOW):
            updated,_=recovery.recover_publications([{'urls':[p['url']]}],got,[],
                state=recovery.RecoveryState(),overall_deadline=recovery.monotonic()+100,
                downstream_reserve=0,cache_path=cache,fetcher=Mock(),interpreter=model)
        model.assert_not_called()
        self.assertEqual(updated,[cached])
        self.assertTrue(pub.validate_observation(updated[0],updated[0]['publication_observation']))
        self.assertEqual(len(radar.filter_evidence(updated,now=NOW)[0]),1)
        self.assertEqual(json.loads(cache.read_text())[p['url']]['checked_at'],stamp)

    def test_changed_authentic_refetch_can_resolve_invalid_cached_provenance(self):
        p=page('https://issuer.example/x')
        fresh=dict(p,text=p['text']+' Authentic new capture.')
        cache=self.root/'cache.json'
        cache.write_text(json.dumps({p['url']:{'checked_at':NOW.isoformat(),
            'page':dict(p,publication_observation={'version':'invalid'})}}))
        with patch.object(radar,'fetch_source',return_value=fresh) as fetch:
            got=radar.gather_evidence([p['url']],cache_path=cache)
        fetch.assert_called_once()
        self.assertNotIn('publication_observation',got[0])
        model=Mock(side_effect=lambda pages,**kw:({q['url']:observation(q) for q in pages},[]))
        with patch.object(recovery,'utc_now',return_value=NOW):
            updated,_=recovery.recover_publications([{'urls':[p['url']]}],got,[],
                state=recovery.RecoveryState(),overall_deadline=recovery.monotonic()+100,
                downstream_reserve=0,cache_path=cache,fetcher=Mock(),interpreter=model,refetch_urls=set())
        model.assert_not_called()  # Changed authentic bounded capture parses locally.
        self.assertTrue(pub.validate_observation(updated[0],updated[0]['publication_observation']))
        self.assertEqual(len(radar.filter_evidence(updated,now=NOW)[0]),1)

    def test_direct_cache_checked_at_is_actual_completion_not_collection_start(self):
        class Clock(dt.datetime):
            ticks=0
            @classmethod
            def now(cls,tz=None):
                cls.ticks+=1
                return NOW+dt.timedelta(seconds=cls.ticks*10)
        p=page('https://issuer.example/x')
        cache=self.root/'cache.json'
        with patch.object(radar.dt,'datetime',Clock),patch.object(radar,'fetch_source',return_value=p):
            got=radar.gather_evidence([p['url']],cache_path=cache)
        self.assertEqual(got,[p])
        self.assertEqual(json.loads(cache.read_text())[p['url']]['checked_at'],'2026-10-21T16:00:20Z')

    def test_focused_useful_unknown_capture_does_not_duplicate_extraction(self):
        # Inject only at the already tested structured-ingestion boundary.
        p=page('https://issuer.example/x')
        with patch.object(radar,'validate_structured_page',return_value=p), patch.object(radar,'is_safe_public_url',return_value=True), patch.object(radar,'fetch_source') as direct, patch.object(radar,'fetch_source_via_gateway') as gateway:
            got=radar.gather_evidence([p['url']],focused_pages={p['url']:{'capture':'synthetic'}})
        self.assertEqual(got,[p]);direct.assert_not_called();gateway.assert_not_called()



if __name__=='__main__':unittest.main()
