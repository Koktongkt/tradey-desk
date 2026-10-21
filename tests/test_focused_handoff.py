"""Offline end-to-end focused handoff; real allocation, manifests and quality gates."""
from contextlib import ExitStack
import datetime as dt
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import alpha_radar as radar
import focused_pipeline as pipeline
import focused_search as search
from extraction_worker import project_row


class FocusedHandoffTests(unittest.TestCase):
    def fixture(self, stack, root, *, bad=False, sec_seed=False):
        now = dt.datetime.now(dt.timezone.utc)
        candidates = [{'symbol':s, 'catalyst':'Guidance raised after new contracts',
                       'event_date':now.date().isoformat(), 'urls':[f'https://seed.example/{s}']}
                      for s in ('AAA','BBB','CCC','DDD','EEE')]
        if sec_seed:candidates[0]['urls']=['https://www.sec.gov/Archives/edgar/data/123/000000012326000001/event.htm']
        alternatives = {c['symbol']:[f'https://source{i}.example/{c["symbol"]}' for i in range(5)] for c in candidates}
        manifest = json.dumps({'candidates':[{'symbol':s,'urls':u} for s,u in alternatives.items()]})
        # Keep the real strict manifest parser and attested-channel type boundary.
        def child(*args, **kwargs):
            done = subprocess.CompletedProcess([], 0, manifest.encode(), b'')
            done.private_artifact = (search.SearchReceipt({u for urls in alternatives.values() for u in urls}, now.isoformat())
                                     if kwargs['wrapper'].name == 'focused_search_wrapper.py' else {})
            return done
        def validate(urls, **kwargs):
            return {'version':2, 'status':'ok', 'results':[{'requested_url':u,'eligible':True,'reason':'success'} for u in urls]}
        def batch(urls, **kwargs):
            return {'version':2,'status':'ok','results':[{'requested_url':u,'result':project_row({
                'url':u,'title':'Company revenue guidance raised',
                'content':('<meta property="article:published_time" content="'+now.isoformat()+'">' if not bad and not (sec_seed and radar.is_sec_archive_filing_url(u)) else '') +
                          'The company raised revenue guidance after stronger contract demand. '*25})} for u in urls]}
        stack.enter_context(patch.object(radar,'ROOT',root))
        stack.enter_context(patch.object(radar,'discovery_command',return_value=['offline']))
        stack.enter_context(patch.object(radar,'focused_retrieval_command',return_value=['offline']))
        stack.enter_context(patch.object(radar.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps({'candidates':candidates}),'')))
        # The new tool-free child is independent of subprocess.run. Keep the
        # real adapter/validation, but explicitly fake both child boundaries.
        stack.enter_context(patch.object(radar,'research_subprocess_command',return_value=['offline-publication']))
        def publication_child(command,*,input,deadline):
            return subprocess.CompletedProcess(command,0,json.dumps({'version':1,'results':[
                {'id':p['id'],'status':'unknown'} for p in json.loads(input)['pages']]}).encode(),b'')
        stack.enter_context(patch.object(radar,'run_publication_process',side_effect=publication_child))
        stack.enter_context(patch('focused_capture.run_private_child',side_effect=child))
        stack.enter_context(patch.object(pipeline,'run_validation_worker',side_effect=validate))
        stack.enter_context(patch.object(pipeline,'run_batch_worker',side_effect=batch))
        stack.enter_context(patch.object(radar,'is_safe_public_url',return_value=True))
        return candidates

    def test_live_radar_retains_urls_16_through_25(self):
        with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
            candidates = self.fixture(stack, Path(td))
            now=dt.datetime.now(dt.timezone.utc)
            history=[{'timestamp':(now-dt.timedelta(minutes=m)).isoformat(),'stage':'source_fetch',
                      'reason':'source_fetch_failed','domain':'seed.example'} for m in (1,2)]
            health=stack.enter_context(patch.object(radar,'read_jsonl',return_value=history))
            direct = stack.enter_context(patch.object(radar,'fetch_source',side_effect=AssertionError('duplicate direct')))
            fallback = stack.enter_context(patch.object(radar,'fetch_source_via_gateway',side_effect=AssertionError('duplicate fallback')))
            ranked = stack.enter_context(patch.object(radar,'ranked_candidate_evidence',wraps=radar.ranked_candidate_evidence))
            rescue = stack.enter_context(patch.object(radar,'post_fetch_rescue_candidate',side_effect=AssertionError('unnecessary rescue')))
            synth = stack.enter_context(patch.object(radar,'synthesize_candidate',return_value={'symbol':'AAA'}))
            self.assertEqual(radar.live_research({'focused_retrieval_enabled':True},intake=lambda c:c),{'symbol':'AAA'})
            selected, pages = ranked.call_args.args
            self.assertEqual([len(c['urls']) for c in selected],[5]*5)
            self.assertEqual(len(pages),25)
            for c in selected:
                self.assertEqual(c['urls'][0],f'https://seed.example/{c["symbol"]}')
                self.assertFalse(set(c.get('_alternate_urls',[])) & set(c['urls']))
            self.assertLessEqual(len(synth.call_args.args[2]),4)
            self.assertTrue(all(p.get('checked_at') for p in pages))
            health.assert_called_once_with(Path(td)/'private'/'research_diagnostics.jsonl')
            direct.assert_not_called(); fallback.assert_not_called(); rescue.assert_not_called()

    def test_accepted_parent_pages_avoid_both_fetch_paths(self):
        with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
            candidates = self.fixture(stack,Path(td))
            focused = radar.focused_retrieval(candidates)
            with patch.object(radar,'fetch_source',side_effect=AssertionError('duplicate direct')) as direct, patch.object(radar,'fetch_source_via_gateway',side_effect=AssertionError('duplicate fallback')) as fallback:
                pages = radar.gather_evidence(list(focused.focused_pages),focused_pages=focused.focused_pages)
            self.assertEqual(len(pages),25)
            for page in pages:
                self.assertEqual(page['checked_at'],focused.focused_pages[page['url']].checked_at)
            direct.assert_not_called(); fallback.assert_not_called()

    def test_invalid_coordinator_pages_are_ordinary_bounded_fetch_misses(self):
        from unittest.mock import MagicMock
        for kind in ('undated','mismatched','error'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td, ExitStack() as stack:
                candidates=self.fixture(stack,Path(td),bad=kind=='undated')
                external_batch=pipeline.run_batch_worker.side_effect
                def batch(urls, **kwargs):
                    response=external_batch(urls,**kwargs)
                    if kind=='mismatched':
                        for row in response['results']:
                            page=row['result']['page']
                            page['url']='https://unrelated.example/article'
                            page['extraction_location']={'version':1,'requested_url':row['requested_url'],'returned_url':page['url']}
                    if kind=='error':
                        for row in response['results']:row['result']={'version':1,'status':'error','reason':'provider_error'}
                    return response
                stack.enter_context(patch.object(pipeline,'run_batch_worker',side_effect=batch))
                focused=radar.focused_retrieval(candidates)
                url=focused['AAA'][0]
                response=MagicMock()
                response.__enter__.return_value=response
                response.geturl.return_value=url
                response.read.return_value=('<title>Ordinary bounded fetch</title><meta property="article:published_time" content="'+dt.datetime.now(dt.timezone.utc).isoformat()+'">'+'The company confirmed contractual revenue guidance. '*25).encode()
                http=stack.enter_context(patch.object(radar,'safe_urlopen',return_value=response))
                fallback=stack.enter_context(patch.object(radar,'fetch_source_via_gateway',side_effect=AssertionError('no fallback needed')))
                pages=radar.gather_evidence([url,url],focused_pages=focused.focused_pages,
                                            collection_deadline=radar.monotonic()+5)
                self.assertEqual(len(pages),1)
                if kind=='undated':
                    self.assertEqual(pages[0]['title'],'Company revenue guidance raised')
                    self.assertEqual(radar.filter_evidence(pages)[0],[])
                    http.assert_not_called()  # Retain useful unknown, without admission.
                else:
                    self.assertEqual(pages[0]['title'],'Ordinary bounded fetch')
                    self.assertEqual(http.call_count,1)
                    self.assertLessEqual(http.call_args.kwargs['timeout'],5)
                fallback.assert_not_called()

    def test_undated_sec_miss_keeps_official_date_enrichment_after_real_handoff(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
            candidates=self.fixture(stack,Path(td),sec_seed=True)
            sec_url=candidates[0]['urls'][0]
            response=MagicMock()
            response.__enter__.return_value=response
            response.geturl.return_value=sec_url
            response.read.return_value=('<title>Official filing</title>'+'The issuer disclosed material contractual terms and revenue details. '*25).encode()
            http=stack.enter_context(patch.object(radar,'safe_urlopen',return_value=response))
            fallback=stack.enter_context(patch.object(radar,'fetch_source_via_gateway',side_effect=AssertionError('no fallback')))
            official_date=dt.datetime.now(dt.timezone.utc).date().isoformat()
            official=stack.enter_context(patch.object(radar,'sec_filing_date_for_url',return_value=official_date))
            ranked=stack.enter_context(patch.object(radar,'ranked_candidate_evidence',wraps=radar.ranked_candidate_evidence))
            stack.enter_context(patch.object(radar,'synthesize_candidate',return_value={'symbol':'AAA'}))
            radar.live_research({'focused_retrieval_enabled':True},intake=lambda c:c)
            pages=ranked.call_args.args[1]
            self.assertEqual(len(pages),25)
            page=next(p for p in pages if p['url']==sec_url)
            self.assertEqual(page['published_at'],official_date+'T00:00:00Z')
            self.assertEqual(http.call_count,0)  # Reuse undated capture, then official date enrichment.
            official.assert_called_once()
            self.assertEqual(official.call_args.args[0],sec_url)
            fallback.assert_not_called()
            self.assertTrue(all(p.get('checked_at') for p in pages if p['url']!=sec_url))

    def test_five_initial_plus_three_rescue_bindings_stop_at_three_candidates(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
            self.fixture(stack,Path(td),bad=True)
            def http(request, **kwargs):
                response=MagicMock()
                response.__enter__.return_value=response
                response.geturl.return_value=request.full_url
                response.read.return_value=('Undated company contract facts and financial information. '*30).encode()
                return response
            transport=stack.enter_context(patch.object(radar,'safe_urlopen',side_effect=http))
            sec=stack.enter_context(patch.object(radar,'sec_edgar_filing_url',side_effect=lambda s,*a,**k:f'https://www.sec.gov/Archives/edgar/data/123/000000012326000001/{s}.htm'))
            stack.enter_context(patch.object(radar,'sec_filing_date_for_url',return_value=None))
            search=stack.enter_context(patch.object(radar,'gateway_rescue_url',side_effect=lambda s,*a,role,**k:f'https://{role}.example/{s}'))
            rescue=stack.enter_context(patch.object(radar,'post_fetch_rescue_candidate',wraps=radar.post_fetch_rescue_candidate))
            synth=stack.enter_context(patch.object(radar,'synthesize_candidate',side_effect=AssertionError('no quality evidence')))
            with self.assertRaises(radar.ResearchFailure):radar.live_research({'focused_retrieval_enabled':True})
            self.assertEqual(rescue.call_count,3)
            self.assertEqual(sec.call_count,3)
            self.assertEqual(search.call_count,6)
            self.assertEqual(sum(len(c.args[0]) for c in pipeline.run_batch_worker.call_args_list),25)
            self.assertEqual(transport.call_count,9)  # Reuse 25 undated captures; 3 rescue URLs on three candidates.
            self.assertEqual(radar.run_publication_process.call_count,1)
            for call in rescue.call_args_list:
                candidate=call.args[0]
                self.assertEqual(len(candidate['urls']),8)
                self.assertEqual(len(set(candidate['urls'])),8)
                self.assertFalse(set(candidate['_alternate_urls']) & set(candidate['urls'][:5]))
            synth.assert_not_called()

    def test_focused_diagnostic_failure_stops_before_synthesis(self):
        with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
            self.fixture(stack,Path(td))
            synth=stack.enter_context(patch.object(radar,'synthesize_candidate'))
            stack.enter_context(patch.object(radar,'record_focused_allocation',side_effect=OSError('private failure')))
            with self.assertRaises(radar.ResearchFailure) as caught:radar.live_research({'focused_retrieval_enabled':True})
            self.assertEqual(caught.exception.code,'research_persistence_failure')
            synth.assert_not_called()

    def test_private_allocation_counts_are_observed_sanitized_and_correlated(self):
        with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
            root=Path(td)
            candidates=self.fixture(stack,root)
            focused=radar.focused_retrieval(candidates)
            result=focused.focused_result
            result.candidate_counts['AAA']={'selected':999,'successful':999}
            selected=result.allocation.by_symbol
            # Distinguish actual submitted, extracted and quality-accepted sets.
            result.submitted_urls.remove(selected['AAA'][4])
            result.pages.pop(selected['AAA'][4])
            result.pages.pop(selected['AAA'][3])
            accepted={'AAA':[{'url':selected['AAA'][0],'body':'PRIVATE BODY'}]}
            path=root/'diagnostics.jsonl'
            for run_id in ('a'*32,'b'*32):
                token=radar._research_run_id.set(run_id)
                try:radar.record_focused_allocation(result,accepted_by_symbol=accepted,path=path)
                finally:radar._research_run_id.reset(token)
            rows=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len({r['run_id'] for r in rows}),2)
            for run_id in ('a'*32,'b'*32):
                current=[r for r in rows if r['run_id']==run_id]
                counts=[r for r in current if r['stage']=='focused_candidate']
                self.assertEqual(len(counts),5)
                self.assertEqual(sum(r['available'] for r in counts),30)
                self.assertEqual(sum(r['selected'] for r in counts),25)
                self.assertEqual(sum(r['submitted'] for r in counts),24)
                self.assertEqual(sum(r['extracted'] for r in counts),23)
                self.assertEqual(sum(r['accepted'] for r in counts),1)
                for row in counts:
                    self.assertEqual(set(row),{'timestamp','run_id','stage','candidate_token','available','selected','submitted','extracted','accepted','network_attempted'})
                    self.assertIsNone(row['network_attempted'])
                sources=[r for r in current if r['stage']=='focused_source']
                self.assertEqual(len(sources),25)
                for row in sources:
                    self.assertEqual(set(row),{'timestamp','run_id','stage','url_id','outcome','submitted','extracted','accepted','network_attempted'})
                    self.assertIsNone(row['network_attempted'])
            self.assertFalse({r['candidate_token'] for r in rows[:30] if 'candidate_token' in r} &
                             {r['candidate_token'] for r in rows[30:] if 'candidate_token' in r})
            text=path.read_text()
            for private in ('AAA','https://','PRIVATE BODY','prompt','stderr'):
                self.assertNotIn(private,text)
            with patch.object(radar,'append_jsonl',side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):radar.record_focused_allocation(result,accepted_by_symbol=accepted,path=path)

    def test_private_projection_does_not_serialize_malformed_available_counts_or_outcomes(self):
        with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
            candidates=self.fixture(stack,Path(td))
            result=radar.focused_retrieval(candidates).focused_result
            result.allocation.available_counts['AAA']='PRIVATE COUNT https://secret.example'
            result.outcomes[result.allocation.unique_urls[0]]='PRIVATE STDERR'
            path=Path(td)/'diagnostics.jsonl'
            radar.record_focused_allocation(result,accepted_by_symbol={},path=path)
            text=path.read_text()
            self.assertNotIn('PRIVATE',text)
            self.assertNotIn('https://',text)
            rows=[json.loads(line) for line in text.splitlines()]
            self.assertIsNone(rows[0]['available'])
            self.assertEqual(next(r for r in rows if r['stage']=='focused_source')['outcome'],'malformed_response')

    def test_focused_deadline_includes_command_preparation(self):
        clock=[100.0]
        def command():
            clock[0]+=10
            return ['offline']
        with tempfile.TemporaryDirectory() as td, patch.object(radar,'ROOT',Path(td)), patch.object(radar,'monotonic',side_effect=lambda:clock[0]), patch.object(radar,'focused_retrieval_command',side_effect=command), patch.object(pipeline,'run_focused_pipeline',side_effect=RuntimeError('stop')) as run:
            with self.assertRaisesRegex(RuntimeError,'stop'):
                radar.focused_retrieval([{'symbol':'AAA','urls':[]}],deadline=670)
            self.assertEqual(run.call_args.kwargs['deadline'],250)


if __name__ == '__main__':
    unittest.main()
