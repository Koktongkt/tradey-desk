"""Evidence-readiness contracts; retained real captures are source-only fixtures."""
import hashlib
import html
import json
import os
from pathlib import Path
import unittest

import opportunity_identity as identity
from retained_article import retain_article

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT/'test_artifacts'/'identity_handoff'
PERIODIC_URL = 'https://www.sec.gov/Archives/edgar/data/1446847/000110465926123319/irwd-20260930x10q.htm'
COVER_URL = 'https://www.sec.gov/Archives/edgar/data/1420520/000168316826008161/atomera_8k.htm'
EXHIBIT_URL = COVER_URL.replace('atomera_8k.htm', 'atomera_ex9901.htm')


def original(name):
    path = FIXTURES/name
    if not path.exists():
        raise unittest.SkipTest('source-only identity fixture not provisioned: '+name)
    return path.read_bytes()


def retained(url):
    for path in FIXTURES.glob('*.json'):
        value = json.loads(path.read_text())
        if isinstance(value, dict) and value.get('url') == url:
            return value
    raise unittest.SkipTest('source-only retained identity fixture not provisioned')


class EvidenceReadinessTests(unittest.TestCase):
    def test_flattened_filing_cannot_bootstrap_identity(self):
        page = retain_article({'url':PERIODIC_URL, 'title':'Results', 'text':'Readable quarterly report'},
                              'Readable quarterly report')
        self.assertEqual(identity.resolve_event('IRWD', [page], known_resolutions=()).status, 'unknown')

    def test_authentic_periodic_source_has_explicit_fiscal_facts(self):
        raw = original('irwd-original.html')
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '4ccde4d55477d895a35a06c8eb2f7131ed4f695e3b3e7988c1a62b7cce0e26af')
        parser = identity._Cover(); parser.feed(raw.decode('utf-8')); parser.close()
        self.assertFalse(parser.bad_structure)
        facts = [f for f in parser.facts.values() if f.get('dei:TradingSymbol') == ['IRWD']]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['dei:DocumentFiscalPeriodFocus'], ['Q3'])
        self.assertEqual(facts[0]['dei:DocumentFiscalYearFocus'], ['2026'])
        self.assertEqual(facts[0]['dei:EntityCentralIndexKey'], ['0001446847'])
        # This is authentic formatted source text, not a manufactured ISO cover.
        self.assertEqual(facts[0]['dei:DocumentPeriodEndDate'], ['September 30, 2026'])

    def test_authenticated_results_source_has_literal_exhibit_link(self):
        cover = retained(COVER_URL); exhibit = retained(EXHIBIT_URL)
        self.assertEqual(hashlib.sha256(cover['text'].encode()).hexdigest(), cover['sha256'])
        self.assertEqual(hashlib.sha256(exhibit['text'].encode()).hexdigest(), exhibit['sha256'])
        from html.parser import HTMLParser
        class Links(HTMLParser):
            def __init__(self): super().__init__(); self.links=[]
            def handle_starttag(self, tag, attrs):
                if tag == 'a': self.links.extend(v for k,v in attrs if k == 'href')
        parser=Links(); parser.feed(cover['text'])
        from urllib.parse import urljoin
        self.assertIn(EXHIBIT_URL, [urljoin(COVER_URL, link) for link in parser.links])
        p=identity._Cover(); p.feed(cover['text']); p.close()
        subjects=[f for f in p.facts.values() if f.get('dei:TradingSymbol') == ['ATOM']]
        self.assertEqual(subjects[0]['dei:EntityCentralIndexKey'], ['0001420520'])
        self.assertEqual(subjects[0]['dei:DocumentType'], ['8-K'])

    def test_actual_oversize_transport_did_not_create_cropped_fixture(self):
        receipt=FIXTURES/'sbac-acquisition.json'
        if not receipt.exists(): self.skipTest('source-only capacity receipt not provisioned')
        value=json.loads(receipt.read_text())
        self.assertEqual(value['reason'], 'source_capacity')
        self.assertFalse((FIXTURES/'sbac-original.html').exists())


class IdentityCaptureTests(unittest.TestCase):
    def api(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('earnings_identity_evidence'),
                             'identity capture contract is not implemented')
        import earnings_identity_evidence
        return earnings_identity_evidence

    def capture(self, raw=b'<html><body>Complete source</body></html>'):
        return self.api().capture_identity_source(PERIODIC_URL, raw,
            returned_url=PERIODIC_URL, content_type='text/html')

    def test_complete_wire_bytes_round_trip_without_article_limit(self):
        api=self.api(); raw=original('irwd-original.html'); capture=self.capture(raw)
        self.assertTrue(api.validate_identity_capture(capture))
        self.assertEqual(api.identity_source_bytes(capture), raw)
        self.assertEqual(capture.source_sha256, '4ccde4d55477d895a35a06c8eb2f7131ed4f695e3b3e7988c1a62b7cce0e26af')
        self.assertGreater(len(capture.canonical), 85000)
        self.assertLessEqual(len(capture.canonical), 3000000)
        self.assertFalse(api.validate_identity_capture(json.loads(capture.canonical)))

    def test_capture_rejects_capacity_encoding_and_locator_mismatch(self):
        api=self.api()
        for raw in [b'x'*2000001, b'\xff', b'']:
            with self.subTest(size=len(raw)), self.assertRaises(ValueError): self.capture(raw)
        for returned in [EXHIBIT_URL, PERIODIC_URL+'?changed=1', 'https://attacker.test/report.htm']:
            with self.subTest(returned=returned), self.assertRaises(ValueError):
                api.capture_identity_source(PERIODIC_URL, b'<html></html>',returned_url=returned,content_type='text/html')
        with self.assertRaises(ValueError):
            api.capture_identity_source(PERIODIC_URL,b'<html></html>',returned_url=PERIODIC_URL,content_type='text/plain')

    def test_capture_metadata_and_duplicate_json_tampering_rejected(self):
        from dataclasses import replace
        api=self.api(); capture=self.capture()
        value=json.loads(capture.canonical);value['url']=EXHIBIT_URL
        for raw in [json.dumps(value).encode(), capture.canonical[:-1]+b',"complete":true}', b'{"complete":NaN}']:
            changed=replace(capture, canonical=raw)
            self.assertFalse(api.validate_identity_capture(changed))
            self.assertIsNone(api.identity_source_bytes(changed))

    def test_retention_is_private_idempotent_and_rejects_symlink_or_collision(self):
        api=self.api()
        self.assertTrue(hasattr(api,'retain_identity_captures'), 'durable identity retention is missing')
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);capture=self.capture()
            api.retain_identity_captures(root,(capture,))
            target=root/capture.retained_ref
            self.assertEqual(target.read_bytes(),capture.canonical)
            self.assertEqual(target.stat().st_mode&0o777,0o600)
            self.assertEqual(target.parent.stat().st_mode&0o777,0o700)
            before=target.stat().st_mtime_ns
            api.retain_identity_captures(root,(capture,))
            self.assertEqual(target.stat().st_mtime_ns,before)
            target.write_bytes(b'changed')
            with self.assertRaises((ValueError,OSError)): api.retain_identity_captures(root,(capture,))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);outside=root/'outside';outside.mkdir()
            (root/'private').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(OSError): api.retain_identity_captures(root,(self.capture(),))
            self.assertFalse((outside/'opportunity_evidence').exists())

    def test_actual_provider_truncation_footer_is_not_complete_evidence(self):
        value=retain_article({'url':PERIODIC_URL,'title':'Report','text':'Readable report'},
            'Readable report\nThis content has been truncated to stay below 50000 characters')
        self.assertEqual(value.get('_capture_status'), 'incomplete')


class EarningsResolutionTests(IdentityCaptureTests):
    def resolve(self, symbol, captures):
        api=self.api()
        self.assertTrue(hasattr(api,'resolve_earnings_capture'), 'trusted earnings resolver is missing')
        return api.resolve_earnings_capture(symbol,tuple(captures))

    def periodic(self, raw=None):
        return self.capture(original('irwd-original.html') if raw is None else raw)

    def results(self, cover_raw=None, exhibit_raw=None):
        api=self.api()
        return tuple(api.capture_identity_source(url,raw,returned_url=url,content_type='text/html')
                     for url,raw in [(COVER_URL, cover_raw if cover_raw is not None else retained(COVER_URL)['text'].encode()),
                                     (EXHIBIT_URL, exhibit_raw if exhibit_raw is not None else retained(EXHIBIT_URL)['text'].encode())])

    def test_authentic_periodic_filing_handoff(self):
        capture=self.periodic(); result=self.resolve('IRWD',[capture])
        self.assertEqual((result.status,result.family,result.period),('verified','earnings','2026-Q3'))
        self.assertEqual((result.issuer.symbol,result.issuer.cik),('IRWD','0001446847'))
        wire=identity.candidate_identity(result)
        self.assertEqual(wire['version'],2)
        self.assertEqual(identity._load_binding(wire).event_id,result.event_id)
        self.assertEqual(result.documents[0].content_sha256,capture.source_sha256)
        self.assertEqual(result.documents[0].retained_ref,capture.retained_ref)

    def test_authenticated_results_exhibit_handoff(self):
        captures=self.results(); result=self.resolve('ATOM',captures)
        self.assertEqual((result.status,result.period,result.reason),('verified','2026-Q3','sec_results_exhibit'))
        self.assertEqual(result.issuer.cik,'0001420520')
        self.assertEqual(len(result.documents),2)
        self.assertEqual(identity._load_binding(identity.candidate_identity(result)).event_id,result.event_id)
        self.assertEqual(self.resolve('ATOM',tuple(reversed(captures))).event_id,result.event_id)

    def test_missing_link_future_results_and_wrong_issuer_fail_closed(self):
        cover=retained(COVER_URL)['text'];exhibit=retained(EXHIBIT_URL)['text']
        import re
        future=re.sub(r'Provides\s+Third Quarter 2026 Results','Will Report Third Quarter 2026 Results',exhibit)
        self.assertNotEqual(future,exhibit,'negative fixture must modify the actual header')
        for symbol,captures in [
            ('OTHER',self.results()),
            ('ATOM',self.results(cover_raw=cover.replace('atomera_ex9901.htm','not-the-exhibit.htm').encode())),
            ('ATOM',self.results(exhibit_raw=future.encode())),
            ('ATOM',self.results()[:1]),
            ('ATOM',self.results()[1:]),
        ]:
            with self.subTest(symbol=symbol, count=len(captures)):
                self.assertNotEqual(self.resolve(symbol,captures).status,'verified')

    def test_explicit_noncalendar_fiscal_year_and_representation_stability(self):
        import re
        raw=original('irwd-original.html')
        changed=re.sub(rb'(name="dei:DocumentFiscalYearFocus"[^>]*>(?:<[^>]+>)*)2026',rb'\g<1>2027',raw)
        self.assertNotEqual(changed,raw)
        fiscal=self.resolve('IRWD',[self.periodic(changed)])
        self.assertEqual((fiscal.status,fiscal.period),('verified','2027-Q3'))
        normal=self.resolve('IRWD',[self.periodic()])
        self.assertNotEqual(fiscal.event_id,normal.event_id)
        another=self.api().capture_identity_source(PERIODIC_URL.replace('irwd-20260930x10q.htm','another.htm'),raw,
            returned_url=PERIODIC_URL.replace('irwd-20260930x10q.htm','another.htm'),content_type='text/html')
        self.assertEqual(self.resolve('IRWD',[another]).event_id,normal.event_id)
        page={'url':PERIODIC_URL,'text':'Readable model text','_identity_captures':[json.loads(another.canonical)]}
        self.assertEqual(identity.resolve_event('IRWD',[page],known_resolutions=()).status,'unknown')

    def test_fourth_quarter_release_cannot_create_second_annual_allowance(self):
        import re
        text=retained(EXHIBIT_URL)['text']
        fourth=re.sub(r'Provides\s+Third Quarter 2026 Results','Provides Fourth Quarter 2026 Results',text)
        self.assertNotEqual(fourth,text)
        result=self.resolve('ATOM',self.results(exhibit_raw=fourth.encode()))
        self.assertEqual((result.status,result.period),('verified','2026-FY'))

    def test_known_primary_cannot_be_repointed_to_a_new_period(self):
        import re
        cap=self.periodic();current=self.resolve('IRWD',[cap]);wire=identity.candidate_identity(current)
        raw=original('irwd-original.html')
        changed=re.sub(rb'(name="dei:DocumentFiscalYearFocus"[^>]*>(?:<[^>]+>)*)2026',rb'\g<1>2027',raw)
        result=identity.resolve_event('IRWD',[{'url':PERIODIC_URL}],known_resolutions=(wire,),identity_captures=(self.periodic(changed),))
        self.assertEqual((result.status,result.reason),('conflict','known_binding_disagrees'))

    def test_real_policy_input_keeps_article_and_identity_evidence_separate(self):
        import inspect,tempfile
        self.assertIn('identity_captures',inspect.signature(identity.resolve_event).parameters)
        capture=self.periodic()
        page={'url':PERIODIC_URL,'title':'Report','text':'Unchanged readable article'}
        result=identity.resolve_event('IRWD',[page],known_resolutions=(),identity_captures=(capture,))
        self.assertEqual(result.status,'verified')
        with tempfile.TemporaryDirectory() as tmp:
            identity.retain_observations(Path(tmp),result,[page],identity_captures=(capture,))
            self.assertEqual((Path(tmp)/result.documents[0].retained_ref).read_bytes(),capture.canonical)
        self.assertEqual(page['text'],'Unchanged readable article')
        missing={'url':PERIODIC_URL.replace('irwd-20260930x10q.htm','unavailable.htm')}
        blocked=identity.resolve_event('IRWD',[page,missing],known_resolutions=(),identity_captures=(capture,))
        self.assertEqual(blocked.status,'unknown')

    def test_wrong_date_context_truncation_and_comparative_facts_do_not_bind(self):
        raw=original('irwd-original.html')
        for changed in [raw.replace(b'September 30, 2026',b'September 29, 2026'),
                        raw.replace(b'</html>',b''),
                        raw.replace(b'>IRWD<',b'>OTHER<')]:
            with self.subTest(size=len(changed)):
                self.assertNotEqual(self.resolve('IRWD',[self.periodic(changed)]).status,'verified')
        # A different issuer's full capture cannot be used to cure missing ATOM evidence.
        self.assertNotEqual(self.resolve('ATOM',[self.periodic()]).status,'verified')


class IdentityAcquisitionTests(unittest.TestCase):
    def api(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('earnings_identity_acquisition'), 'bounded identity acquisition is missing')
        import earnings_identity_acquisition
        return earnings_identity_acquisition

    def response(self,raw,url=PERIODIC_URL,declared=None,on_read=None):
        from types import SimpleNamespace
        import io
        source=io.BytesIO(raw)
        class Response:
            status=200
            headers={'Content-Type':'text/html','Content-Length':str(len(raw) if declared is None else declared)}
            fp=SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=lambda seconds:None)))
            def geturl(self):return url
            def read1(self,size):
                if on_read:on_read()
                return source.read(size)
            def isclosed(self):return False
            def __enter__(self):return self
            def __exit__(self,*args):source.close()
        return Response()

    def test_exact_url_acquisition_deduplicates_and_preserves_wire_bytes(self):
        api=self.api();raw=original('irwd-original.html');calls=[]
        def opened(request,timeout):
            calls.append((request.full_url,timeout));return self.response(raw)
        import time
        with api.identity_acquisition():
            a=api.acquire_identity_captures('IRWD',[{'url':PERIODIC_URL}]*2,deadline=time.monotonic()+20,opener=opened)
            b=api.acquire_identity_captures('IRWD',[{'url':PERIODIC_URL}],deadline=time.monotonic()+20,opener=opened)
        from earnings_identity_evidence import identity_source_bytes
        self.assertEqual(len(a),1);self.assertEqual(a,b);self.assertEqual(identity_source_bytes(a[0]),raw)
        self.assertEqual(len(calls),1);self.assertEqual(calls[0][0],PERIODIC_URL)
        self.assertLessEqual(calls[0][1],15)

    def test_zero_deadline_never_opens_and_dictionary_capture_is_not_authority(self):
        api=self.api();calls=[]
        def opened(*args,**kwargs):calls.append(1);raise AssertionError('must not open')
        import time
        result=api.acquire_identity_captures('IRWD',[{'url':PERIODIC_URL,'_identity_capture':{'complete':True}}],
                                             deadline=time.monotonic()-1,opener=opened)
        self.assertEqual(result,());self.assertEqual(calls,[])

    def test_oversized_incomplete_and_redirected_responses_are_not_captures(self):
        api=self.api();import time
        for response in [self.response(b'x'*2000001),self.response(b'<html></html>',declared=1000),
                         self.response(b'<html></html>',url=EXHIBIT_URL)]:
            with self.subTest(response=response),api.identity_acquisition():
                out=api.acquire_identity_captures('IRWD',[{'url':PERIODIC_URL}],deadline=time.monotonic()+20,
                                                  opener=lambda *a,**k:response)
                self.assertEqual(out,())

    def test_body_elapsed_time_is_inside_shared_deadline(self):
        api=self.api();from unittest.mock import patch
        clock=[0.0]
        def read():clock[0]=6.0
        with patch.object(api,'monotonic',side_effect=lambda:clock[0]),patch('research_budget.monotonic',side_effect=lambda:clock[0]):
            out=api.acquire_identity_captures('IRWD',[{'url':PERIODIC_URL}],deadline=5.0,
                opener=lambda *a,**k:self.response(b'<html></html>',on_read=read))
        self.assertEqual(out,())

    def test_identity_handoff_preparation_cannot_escape_deadline(self):
        api=self.api();from unittest.mock import patch
        clock=[0.0]
        def slow_links(*args):clock[0]=6.0;return ()
        with api.identity_acquisition(),patch.object(api,'monotonic',side_effect=lambda:clock[0]),patch('research_budget.monotonic',side_effect=lambda:clock[0]),patch.object(api,'earnings_exhibit_links',side_effect=slow_links):
            out=api.acquire_identity_captures('IRWD',[{'url':PERIODIC_URL}],deadline=5.0,
                opener=lambda *a,**k:self.response(b'<html></html>'))
            reasons={note['reason'] for note in api.acquisition_notes([PERIODIC_URL])}
        self.assertEqual(out,())
        self.assertIn('identity_handoff_deadline',reasons)

    def test_deadline_exhausted_before_first_fetch_records_handoff_reason(self):
        api=self.api();from unittest.mock import patch
        def opened(*args,**kwargs):raise AssertionError('must not open')
        with api.identity_acquisition(),patch.object(api,'monotonic',return_value=10**12):
            out=api.acquire_identity_captures('IRWD',[{'url':PERIODIC_URL}],deadline=5.0,opener=opened)
            reasons={note['reason'] for note in api.acquisition_notes([PERIODIC_URL])}
        self.assertEqual(out,())
        self.assertIn('identity_handoff_deadline',reasons)

    def test_results_acquisition_follows_only_literal_linked_exhibit(self):
        api=self.api();import time
        sources={url:retained(url)['text'].encode() for url in (COVER_URL,EXHIBIT_URL)};calls=[]
        def opened(request,timeout):
            calls.append(request.full_url)
            return self.response(sources[request.full_url],url=request.full_url)
        with api.identity_acquisition():
            out=api.acquire_identity_captures('ATOM',[{'url':COVER_URL}],deadline=time.monotonic()+30,opener=opened)
        self.assertEqual(calls,[COVER_URL,EXHIBIT_URL])
        self.assertEqual(len(out),2)
        from earnings_identity_evidence import resolve_earnings_capture
        self.assertEqual(resolve_earnings_capture('ATOM',out).status,'verified')


class RadarIdentityHandoffTests(unittest.TestCase):
    def test_readable_pages_reach_synthesis_using_actual_identity_acquisition(self):
        import alpha_radar as radar
        import tempfile,time,subprocess,copy
        from contextlib import ExitStack
        from unittest.mock import patch
        import opportunity_fixtures as fixtures
        from earnings_identity_evidence import resolve_earnings_capture
        from earnings_identity_acquisition import acquire_identity_captures
        helper=IdentityAcquisitionTests()
        sources={url:retained(url)['text'].encode() for url in (COVER_URL,EXHIBIT_URL)}
        scouts=[{'symbol':'ATOM','urls':[COVER_URL,'https://news.example/atom'],'event_date':'2026-10-29','catalyst':'Results'}]
        pages=[{'url':COVER_URL,'title':'Results','text':'Readable primary'},
               {'url':'https://news.example/atom','title':'News','text':'Readable corroboration'}]
        def opened(request,timeout):return helper.response(sources[request.full_url],url=request.full_url)
        calls=[]
        def synthesize(cfg,selected,evidence,deadline,**kwargs):
            calls.append((selected['symbol'],[p['text'] for p in evidence]));return {'symbol':'ATOM'}
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            root=Path(tmp);fixtures.make_root(root,active=True)
            (root/'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
            for name,options in [
                ('ROOT',{'new':root}),('safe_urlopen',{'side_effect':opened}),
                ('scout_parse_result',{'return_value':(copy.deepcopy(scouts),{'reason':'ok'})}),
                ('discovery_command',{'return_value':['synthetic']}),
                ('gather_evidence',{'return_value':copy.deepcopy(pages)}),
                ('sec_filing_date_for_url',{'return_value':None}),
                ('filter_evidence',{'side_effect':lambda p:(p,[])}),
                ('recover_publications',{'side_effect':lambda c,p,*a,**k:(p,[])}),
                ('synthesize_candidate',{'side_effect':synthesize}),
            ]: stack.enter_context(patch.object(radar,name,**options))
            stack.enter_context(patch.object(radar.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'{}','')))
            result=radar.live_research({'focused_retrieval_enabled':False},intake=lambda c:c)
        self.assertEqual(result.get('symbol'),'ATOM','readable evidence should pass identity admission')
        self.assertEqual(calls,[('ATOM',['Readable primary','Readable corroboration'])])
        self.assertEqual(result['opportunity_identity']['version'],2)

    def test_exhausted_identity_deadline_is_transport_failure_not_coverage_blocker(self):
        import alpha_radar as radar
        import tempfile,subprocess,copy
        from contextlib import ExitStack
        from unittest.mock import patch
        import opportunity_fixtures as fixtures
        import earnings_identity_acquisition as acquisition
        scouts=[{'symbol':'ATOM','urls':[COVER_URL,'https://news.example/atom'],'event_date':'2026-10-29','catalyst':'Results'}]
        pages=[{'url':COVER_URL,'title':'Results','text':'Readable primary'},{'url':'https://news.example/atom','title':'News','text':'Readable corroboration'}]
        def opened(*args,**kwargs):raise AssertionError('deadline must stop identity acquisition')
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            root=Path(tmp);fixtures.make_root(root,active=True)
            (root/'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
            for name,options in [('ROOT',{'new':root}),('safe_urlopen',{'side_effect':opened}),
                ('scout_parse_result',{'return_value':(copy.deepcopy(scouts),{'reason':'ok'})}),
                ('discovery_command',{'return_value':['synthetic']}),('gather_evidence',{'return_value':pages}),
                ('sec_filing_date_for_url',{'return_value':None}),('filter_evidence',{'side_effect':lambda p:(p,[])}),
                ('recover_publications',{'side_effect':lambda c,p,*a,**k:(p,[])}),
                ('synthesize_candidate',{'side_effect':AssertionError('synthesis must not launch')})]:
                stack.enter_context(patch.object(radar,name,**options))
            stack.enter_context(patch.object(radar.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'{}','')))
            stack.enter_context(patch.object(acquisition,'monotonic',return_value=10**12))
            with self.assertRaises(radar.ResearchFailure) as caught:
                radar.live_research({'focused_retrieval_enabled':False})
            rows=[json.loads(x) for x in (root/'private/research_policy_diagnostics.jsonl').read_text().splitlines()]
        self.assertEqual(caught.exception.code,'research_source_retrieval_failed')
        self.assertNotIsInstance(caught.exception,radar.CandidateRejection)
        self.assertIn('identity_handoff_deadline',rows[-1]['source_failure_reasons'])


class IdentityDiagnosticTests(unittest.TestCase):
    def test_unknown_identity_is_a_blocker_not_healthy_policy_exhaustion(self):
        import alpha_radar as radar
        import tempfile,argparse,io
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp,patch.object(radar,'ROOT',Path(tmp)),patch.object(radar,'reusable_fresh_candidate',return_value=None),patch.object(radar,'live_research',side_effect=radar.CandidateRejection('opportunity_identity_unknown')),patch('sys.stdout',new_callable=io.StringIO) as out:
            (Path(tmp)/'autonomy_config.json').write_text('{}')
            code=radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual((code,out.getvalue()),(2,'BLOCKER opportunity_identity_unknown\n'))

    def test_policy_diagnostic_has_correlated_normalized_resolver_context(self):
        import alpha_radar as radar
        import tempfile,inspect
        from unittest.mock import patch
        self.assertIn('symbol',inspect.signature(radar._record_policy_skip).parameters)
        with tempfile.TemporaryDirectory() as tmp,patch.object(radar,'ROOT',Path(tmp)):
            token=radar._research_run_id.set('a'*32)
            try:
                resolver=identity.EventResolution('unknown',None,None,None,None,(),(),'unresolved_primary_evidence')
                radar._record_policy_skip('opportunity_identity_unknown',symbol='ATOM',resolution=resolver,
                    source_reasons=('source_http_forbidden',),capture_count=0,stage='pre_synthesis')
            finally:radar._research_run_id.reset(token)
            rows=[json.loads(x) for x in (Path(tmp)/'private/research_policy_diagnostics.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows),1);row=rows[0]
        self.assertEqual((row['run_id'],row['resolver_status'],row['resolver_reason']),('a'*32,'unknown','unresolved_primary_evidence'))
        self.assertEqual(len(row['candidate_token']),16)
        self.assertEqual(row['source_failure_reasons'],['source_http_forbidden'])
        self.assertNotIn('ATOM',json.dumps(row));self.assertNotIn('https://',json.dumps(row))
