"""Unverified publication is preserved, not laundered into dated evidence."""
import asyncio
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import alpha_radar as radar
import extraction_worker as worker
import structured_extraction as adapter
import focused_capture
import publication_provenance as provenance


class CapturedIssuerPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.captures=json.loads((Path(__file__).parent/'fixtures/issuer_publication_captures.json').read_text())

    def test_real_full_markdown_and_worker_publication_formats(self):
        import datetime as dt
        expected={'original-1':'2026-10-09T00:00:00Z','original-2':'2026-10-14T00:00:00Z','control':'2026-09-02T00:00:00Z'}
        for name,stamp in expected.items():
            item=self.captures[name]
            with self.subTest(name=name), patch('socket.getaddrinfo',side_effect=AssertionError('offline DNS')):
                self.assertEqual(radar.extract_gateway_publication_date(item['url'],item['content']),stamp)
                page=radar.validate_structured_page(item['url'],item['worker'])
                self.assertEqual(page['published_at'],stamp)
                self.assertEqual(page['publication_precision'],'day')
                accepted,reasons=radar.filter_evidence([page],now=dt.datetime(2026,10,20,tzinfo=dt.timezone.utc))
                self.assertEqual(len(accepted),1,reasons)

    def test_real_nested_html_fetch_path_publication(self):
        import io
        for name,stamp in (('original-1','2026-10-09T00:00:00Z'),('original-2','2026-10-14T00:00:00Z')):
            item=self.captures[name]
            response=io.BytesIO(item['html'].encode()); response.geturl=lambda:item['url']
            with self.subTest(name=name), patch.object(radar,'safe_urlopen',return_value=response), patch('socket.getaddrinfo',side_effect=AssertionError('offline DNS')):
                page=radar.fetch_source(item['url'])
            self.assertEqual(page['published_at'],stamp)
            self.assertEqual(page['publication_precision'],'day')

    def test_header_contract_rejects_adversarial_dates_and_identity(self):
        from issuer_publication import issuer_publication_date as parse
        for name in ('original-1','original-2'):
            item=self.captures[name]; url=item['url']; md=item['content']; source=item['html']
            raw='October 9, 2026' if name=='original-1' else '10/14/2026'
            date_class='evergreen-news-date-text' if name=='original-1' else 'module_date-text'
            wrapper='evergreen-news-date-time' if name=='original-1' else 'module_date-time'
            for bad_url in (url.replace('https://','https://evil.'), url.replace('/2026/','/2025/'), url.replace('/default.aspx','/other.aspx'),url.replace('/2026/','/2026/Wrong-')):
                for body in (md,source):
                    with self.subTest(name=name,url=bad_url): self.assertIsNone(parse(bad_url,body))
            for prefix in ('Updated ', 'Event date: ', 'Copyright ', 'Recommended '):
                with self.subTest(name=name,prefix=prefix):
                    self.assertIsNone(parse(url,md.replace(raw,prefix+raw)))
                    self.assertIsNone(parse(url,source.replace(raw,prefix+raw)))
            for body in (raw, 'The event will occur on '+raw, md.replace('### Teva Announces','### Other Announces').replace('## Vir Biotechnology Enters','## Other Enters')):
                self.assertIsNone(parse(url,body))
            self.assertIsNone(parse(url,source.replace(wrapper,'wrong-date-context')))
            self.assertIsNone(parse(url,source.replace(date_class,'updated-date')))
            # A real title plus a date only in a recommendation region is not publication.
            import re
            nested=re.sub(r'(<span[^>]*class="'+date_class+r'"[^>]*>)(.*?)(</span>)',r'\1<div class="related-stories">\2</div>\3',source,flags=re.S)
            self.assertIsNone(parse(url,nested))
            self.assertIsNone(radar.extract_gateway_publication_date(url,'# Related stories\n'+md))
        vir=self.captures['original-2']
        for numeric in ('10/09/2026','14/10/2026','02/30/2026','10/14/2025'):
            self.assertIsNone(parse(vir['url'],vir['content'].replace('10/14/2026',numeric)))

    def test_existing_conflicts_and_freshness_still_fail_closed(self):
        import datetime as dt
        item=self.captures['original-2']; url=item['url']
        for date,reason in (('01/14/2026','stale_source'),('10/22/2026','source_freshness_unknown')):
            envelope=copy.deepcopy(item['worker']); envelope['page']['text']=envelope['page']['text'].replace('10/14/2026',date)
            page=radar.validate_structured_page(url,envelope)
            self.assertIsNotNone(page)
            accepted,reasons=radar.filter_evidence([page],now=dt.datetime(2026,10,20,tzinfo=dt.timezone.utc))
            self.assertFalse(accepted)
            self.assertIn(reason,[r['reason'] for r in reasons])
        self.assertIsNone(radar.extract_gateway_publication_date(url,'Published: 2026-10-13\n'+item['content']))
        envelope=copy.deepcopy(item['worker'])
        envelope['page']['publication']={**PUB,'value':'2026-10-13T12:21:33Z'}
        self.assertIsNone(radar.validate_structured_page(url,envelope))
        envelope=copy.deepcopy(item['worker'])
        envelope['page']['url']=url.replace('/2026/','/2026/Wrong-')
        with patch.object(radar,'is_safe_public_url',return_value=True):
            page=radar.validate_structured_page(url,envelope)
        self.assertIsNone(page, 'returned-location conflict remains a refusal')
        import io
        source='<meta property="article:published_time" content="2026-10-13">'+item['html']
        response=io.BytesIO(source.encode()); response.geturl=lambda:url
        with patch.object(radar,'safe_urlopen',return_value=response):
            self.assertIsNone(radar.fetch_source(url)['published_at'])
        wire=self.captures['control']
        line='TEL AVIV, Israel, Sept. 02, 2026 (GLOBE NEWSWIRE) -- Article'
        for token in ('Sept.','Sep.','September'):
            self.assertEqual(radar.extract_gateway_publication_date(wire['url'],line.replace('Sept.',token)),'2026-09-02T00:00:00Z')
        self.assertIsNone(radar.extract_gateway_publication_date('https://issuer.example/news',line))
        self.assertIsNone(radar.extract_gateway_publication_date(wire['url'],'# Related stories\n'+line))

    def test_issuer_header_day_precision_survives_cache_without_fetch(self):
        item=self.captures['original-1']; url=item['url']
        page=radar.validate_structured_page(url,item['worker'])
        checked=radar.dt.datetime.now(radar.dt.timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/'private-cache.json'
            cache.write_text(json.dumps({url:{'checked_at':checked,'page':page}}))
            with patch.object(radar,'fetch_source',side_effect=AssertionError('network')), patch.object(radar,'fetch_source_via_gateway',side_effect=AssertionError('network')), patch('socket.getaddrinfo',side_effect=AssertionError('network')):
                found=radar.gather_evidence([url],cache_path=cache,attempt_path=None)
            self.assertEqual(found[0]['publication_precision'],'day')
            self.assertEqual(found[0]['published_at'],'2026-10-09T00:00:00Z')
            self.assertEqual(json.loads(cache.read_text())[url]['checked_at'],checked)

    def test_original_vir_plus_existing_exact_sec_authority(self):
        import datetime as dt
        vir=self.captures['original-2']; sec=self.captures['original-3']
        a=radar.validate_structured_page(vir['url'],vir['worker'])
        b=radar.validate_structured_page(sec['url'],sec['worker'])
        self.assertIsNone(b['published_at'],'filename/report date is not authority')
        # Persisted actual diagnostic authority result; not a fabricated HTTP response.
        enriched=radar.attach_sec_filing_dates([a,b],{sec['url']:'2026-10-14'})
        accepted,reasons=radar.filter_evidence(enriched,now=dt.datetime(2026,10,20,tzinfo=dt.timezone.utc))
        self.assertEqual(len(accepted),2,reasons)
        self.assertEqual({radar.publisher_domain(p['url']) for p in accepted},{'vir.bio','sec.gov'})


class ProviderPublicationTests(unittest.TestCase):
    def test_integer_seconds_create_provider_report(self):
        self.assertEqual(provenance.provider_publication(946684800), {
            'version': 1, 'basis': 'provider_reported', 'provider': 'keenable',
            'field': 'published_at', 'value': '2000-01-01T00:00:00Z', 'precision': 'second'})
        self.assertEqual(provenance.provider_publication(4102444799)['value'],
                         '2099-12-31T23:59:59Z')

    def test_invalid_timestamp_never_guesses_units_or_type(self):
        for value in (True, False, 946684800.0, 946684800000, '946684800',
                      None, 946684799, 4102444800, -1, {}, []):
            with self.subTest(value=value):
                self.assertIsNone(provenance.provider_publication(value))

URL = 'https://unknown.example/news/story'
BODY = 'The company raised its revenue guidance after stronger customer demand. ' * 10
PUB = {'version': 1, 'basis': 'provider_reported', 'provider': 'keenable',
       'field': 'published_at', 'value': '2026-10-14T12:21:33Z', 'precision': 'second'}
LOC = {'version': 1, 'requested_url': URL, 'returned_url': URL}


def row():
    return {'url': URL, 'title': 'Article', 'content': BODY,
            'publication': copy.deepcopy(PUB), 'extraction_location': dict(LOC)}


class PublicationTests(unittest.TestCase):
    def test_worker_validator_preserves_report_but_does_not_authenticate(self):
        projected = worker.project_row(row())
        self.assertEqual(projected['page']['publication'], PUB)
        page = radar.validate_structured_page(URL, projected)
        self.assertEqual(page['publication'], PUB)
        self.assertIsNone(page['published_at'])
        accepted, _ = radar.filter_evidence([page])
        self.assertEqual(accepted, [])

    def test_malformed_typed_fields_fail_closed(self):
        for key, value in [('value', True), ('value', '2026-10-14T05:21:33'),
                           ('value', '2026-10-14T12:21:33+00:00'), ('precision', 'millisecond'),
                           ('basis', 'publisher_verified'), ('extra', 'arbitrary')]:
            bad = row(); bad['publication'][key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(worker.project_row(bad)['status'], 'error')
                envelope = {'version': 1, 'status': 'ok', 'page': {
                    'url': URL, 'title': 'Article', 'text': BODY,
                    'publication': bad['publication'], 'extraction_location': LOC}}
                self.assertIsNone(radar.validate_structured_page(URL, envelope))

    def test_wrong_request_location_and_conflicting_day_fail_closed(self):
        bad = row(); bad['extraction_location']['requested_url'] = URL + '-other'
        self.assertIsNone(radar.validate_structured_page(URL, worker.project_row(bad)))
        bad = row(); bad['content'] = 'Published: October 13, 2026\n' + BODY
        self.assertIsNone(radar.validate_structured_page(URL, worker.project_row(bad)))
        good = row(); good['content'] = 'Published: October 14, 2026\n' + BODY
        page = radar.validate_structured_page(URL, worker.project_row(good))
        self.assertEqual(page['published_at'], '2026-10-14T00:00:00Z')
        self.assertEqual(page['publication_precision'], 'day')

    def test_visible_html_day_keeps_day_precision(self):
        data = row()
        data['content'] = '<span class="publication-date">October 14, 2026</span>' + BODY
        page = radar.validate_structured_page(URL, worker.project_row(data))
        self.assertIsNotNone(page, 'day-only publication must not conflict with same-day provider instant')
        self.assertEqual(page['publication_precision'], 'day')

    def test_exact_midnight_is_not_day_precision(self):
        data = row()
        data['publication']['value'] = '2026-10-14T00:00:00Z'
        data['content'] = '<meta property="article:published_time" content="2026-10-14T00:00:00Z">' + BODY
        page = radar.validate_structured_page(URL, worker.project_row(data))
        self.assertEqual(page['publication_precision'], 'second')

    def test_related_story_date_does_not_authenticate_current_article(self):
        data = row(); data['content'] += '\nRelated stories\nDate: October 14, 2026\nEarlier story.'
        page = radar.validate_structured_page(URL, worker.project_row(data))
        self.assertIsNone(page['published_at'])

    def test_formatted_related_headings_do_not_date_current_article(self):
        headings = ('Related stories', '## Related stories', '**Related stories**',
                    'Related Stories:', '[Related stories](https://unknown.example/related)',
                    '**Related stories:**', '**Related stories**:',
                    '## **[Related stories](https://unknown.example/related):**',
                    '### [**Related articles:**](https://unknown.example/related) ###',
                    '__Related articles__:', '*Related stories:*',
                    '**More News From Example Corp:**',
                    '[Related stories](https://unknown.example/related "Related stories")',
                    '## **[Related stories](https://unknown.example/related "More")**:',
                    "[Related stories](https://unknown.example/related 'More')",
                    '[Related stories](https://unknown.example/related (More))',
                    '[Related stories](<https://unknown.example/related> "More")',
                    '[Related stories](https://unknown.example/related_(news) "More")')
        for heading in headings:
            with self.subTest(heading=heading):
                data = row(); data['content'] = BODY + '\n' + heading + '\nDate: October 14, 2026\nEarlier story.'
                page = radar.validate_structured_page(URL, worker.project_row(data))
                self.assertIsNotNone(page)
                self.assertIsNone(page['published_at'])
                self.assertEqual(radar.filter_evidence([page])[0], [])
                # The section barrier must not discard a real current-article date/body.
                data['content'] = 'Published: October 14, 2026\n' + data['content']
                page = radar.validate_structured_page(URL, worker.project_row(data))
                self.assertEqual(page['published_at'], '2026-10-14T00:00:00Z')
                self.assertTrue(radar.filter_evidence([page])[0])

    def test_related_stories_reporting_prose_is_not_a_section_barrier(self):
        for prose in ('The editor mentioned related stories in the briefing.',
                      'Related stories about demand reinforced the company outlook.',
                      '**Related stories** were discussed during the results call.',
                      '[Related stories](https://unknown.example/related) illustrate the trend.'):
            with self.subTest(prose=prose):
                data = row(); data['content'] = BODY + '\n' + prose + '\nPublished: October 14, 2026'
                page = radar.validate_structured_page(URL, worker.project_row(data))
                self.assertEqual(page['published_at'], '2026-10-14T00:00:00Z')
                self.assertTrue(radar.filter_evidence([page])[0])

    def test_conflicting_visible_and_structured_day_rejected(self):
        data = row()
        data.pop('publication')
        data['content'] = '<meta property="article:published_time" content="2026-10-14T12:21:33Z">\nPublished: October 13, 2026\n' + BODY
        self.assertIsNone(radar.validate_structured_page(URL, worker.project_row(data)))

    def test_focused_receipt_preserves_unverified_report(self):
        call = {'request': {'urls': [URL]}, 'guarded': False,
                'checked_at': '2026-10-14T13:00:00Z',
                'raw': json.dumps({'results': [row()]})}
        receipts = focused_capture.bind_calls([call])
        self.assertEqual(receipts[URL]['page']['publication'], PUB)

    def test_focused_multi_redirects_use_explicit_requested_binding(self):
        first = row()
        first['url'] = 'https://news.unknown.example/redirect'
        first['extraction_location']['returned_url'] = first['url']
        other = URL + '-other'
        second = row(); second['url'] = other
        second['extraction_location'] = {'version': 1, 'requested_url': other, 'returned_url': other}
        call = {'request': {'urls': [URL, other]}, 'guarded': False,
                'checked_at': '2026-10-14T13:00:00Z', 'raw': json.dumps({'results': [first, second]})}
        receipts = focused_capture.bind_calls([call])
        self.assertEqual(set(receipts), {URL, other})
        self.assertEqual(receipts[URL]['page']['url'], first['url'])

    def test_typed_report_cannot_date_error_footer_related_or_truncated_body(self):
        for text in ('Access denied. ' * 100,
                     BODY + '\nRelated stories\nDate: October 14, 2026\nOld article.',
                     BODY + '\n[Content truncated. Full text saved to: /private/2026-10-14.txt]',
                     BODY + '\nEvent date: October 14, 2026\nCopyright 2026'):
            data = row(); data['content'] = text
            projected = worker.project_row(data)
            page = radar.validate_structured_page(URL, projected)
            accepted, _ = radar.filter_evidence([page] if page else [])
            self.assertEqual(accepted, [])
        for instant in ('2027-10-14T12:21:33Z', '2020-10-14T12:21:33Z'):
            data = row(); data['publication']['value'] = instant
            page = radar.validate_structured_page(URL, worker.project_row(data))
            self.assertIsNone(page['published_at'])

    def test_visible_timezone_instant_is_preserved_and_conflicts_rejected(self):
        for stamp, expected in [('2026-10-14T05:21:33-07:00', True),
                                ('2026-10-14T05:21:34-07:00', False)]:
            data = row()
            data['content'] = '<meta property="article:published_time" content="'+stamp+'">'+BODY
            page = radar.validate_structured_page(URL, worker.project_row(data))
            self.assertEqual(page is not None, expected)
            if page:
                self.assertEqual(page['published_at'], stamp)
                self.assertEqual(page['publication_precision'], 'second')

    def test_source_cache_preserves_report_and_checked_at_without_network(self):
        data = row(); data['content'] = 'Published: October 14, 2026\n' + BODY
        page = radar.validate_structured_page(URL, worker.project_row(data))
        # Visible dates remain the authority; provider-only captures are not reusable evidence.
        checked = radar.dt.datetime.now(radar.dt.timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td)/'cache.json'
            cache.write_text(json.dumps({URL: {'checked_at': checked, 'page': page}}))
            with patch.object(radar,'fetch_source',side_effect=AssertionError('network')), patch.object(radar,'fetch_source_via_gateway',side_effect=AssertionError('network')):
                found=radar.gather_evidence([URL],cache_path=cache)
            self.assertEqual(found[0]['publication'], PUB)
            self.assertEqual(json.loads(cache.read_text())[URL]['checked_at'], checked)

    def test_installed_dispatch_cache_and_rescue_matrix(self):
        prefix = adapter.worker_command()[-1].split('runpy.run_path(')[0]
        code = r'''
import asyncio, json, tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock
from contextlib import ExitStack
import extraction_worker as worker
import extraction_compat as compat
import alpha_radar as radar
from plugins.web import keyless_mcp as k
from tools import web_tools as web, web_result_cache as cache
URL='https://unknown.example/news/story'
BODY='The company raised its revenue guidance after stronger customer demand. '*100
def fixture_rows(urls):
    rows = k.keenable_extract_keyless(urls)
    # The fake provider follows the project's returned-page sourceURL contract,
    # rather than the retired stock dispatcher's requested-page metadata alias.
    for row in rows:
        row['metadata']['sourceURL'] = row['url']
        # Custom-provider fixture owns the typed report. Stock unpatched Hermes
        # intentionally does not emit this project extension.
        from publication_provenance import provider_publication
        row['publication'] = provider_publication(1791980493)
        row['extraction_location'] = {'version': 1, 'requested_url': urls[0], 'returned_url': row['url']}
    return rows
class Provider:
    name='nondefault-fixture'
    calls=0
    def uses_keyless(self): return False
    def extract(self, urls, format=None):
        self.calls+=1
        return fixture_rows(urls)
async def main():
    cases=[]
    for returned in [URL, 'https://news.unknown.example/redirect', 'https://other.example/redirect']:
        with tempfile.TemporaryDirectory() as td, ExitStack() as s:
            p=Provider()
            s.enter_context(patch.object(compat, 'resolve', return_value=p))
            s.enter_context(patch('hermes_cli.config.load_config', return_value={'web':{}}))
            s.enter_context(patch.object(compat, 'check_url', AsyncMock(side_effect=lambda u:u)))
            s.enter_context(patch.object(radar, 'is_safe_public_url', return_value=True))
            s.enter_context(patch.object(cache, '_cache_dir', return_value=Path(td)))
            s.enter_context(patch.object(k, '_keenable_request', return_value={
                'url':returned,'title':'Article','content':BODY,'published_at':1791980493}))
            first=await worker.extract({'version':1,'url':URL})
            second=await worker.extract({'version':1,'url':URL})
            assert p.calls==2, p.calls
            assert first==second
            if 'other.example' in returned:
                assert first['reason']=='url_mismatch'
                cases.append(returned)
                continue
            assert 'page' in first, first
            assert first['page']['url']==returned
            assert first['page']['publication']['value']=='2026-10-14T12:21:33Z'
            page=radar.validate_structured_page(URL,second)
            if 'other.example' in returned: assert page is None
            else: assert page['published_at'] is None and page['publication']['basis']=='provider_reported'
            # Legacy cache entries are ignored; provider-only reports still cannot date evidence.
            cache.extract_cache_put(URL, BODY, 'Legacy', format='markdown', provider=p.name)
            legacy=await worker.extract({'version':1,'url':URL})
            assert legacy['page']['publication']==first['page']['publication']
            assert radar.validate_structured_page(URL,legacy)['published_at'] is None
            # Preserve typed coverage and restore actual sync/async exception rescue.
            def sync_fail(*args, **kwargs): raise OSError('PRIVATE fixture primary unavailable')
            async def async_fail(*args, **kwargs): raise RuntimeError('PRIVATE fixture primary unavailable')
            async def typed_fail(*args, **kwargs): raise compat.CompatibilityError('provider_error')
            cache.extract_cache_put(URL, '', provider=p.name)
            async def rescue_transport(name, urls, *, deadline):
                return fixture_rows(urls)
            for fail in (sync_fail, async_fail, typed_fail):
                with patch.object(cache,'extract_cache_get',side_effect=AssertionError('cache read')), patch.object(p,'extract',fail), patch.object(compat,'rescue_allowed',return_value=True), patch.object(compat,'ring_order',return_value=['keenable']), patch.object(compat,'keyless',side_effect=rescue_transport) as rescue:
                    rescued=await worker.extract({'version':1,'url':URL})
                    assert rescued['status']=='ok', rescued
                    assert rescued['page']['publication']==first['page']['publication'], rescued
                    assert radar.validate_structured_page(URL,rescued)['published_at'] is None
                    assert rescue.call_count==1
                    assert 'PRIVATE' not in json.dumps(rescued)
            cases.append(returned)
    assert len(cases)==3
asyncio.run(main())
print('CACHE_RESCUE_MATRIX_OK')
'''
        result = subprocess.run(adapter.worker_command()[:-1] + [prefix + code],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('CACHE_RESCUE_MATRIX_OK', result.stdout)

    def test_real_supervised_installed_dispatcher_roundtrip(self):
        # Replace only provider selection/HTTP transport and scratch sinks, not
        # dispatcher, normalizer, projection, worker, supervisor or validator.
        prefix = adapter.worker_command()[-1].split('runpy.run_path(')[0]
        script = r'''
from pathlib import Path
from unittest.mock import patch, AsyncMock
from contextlib import ExitStack
import tempfile
import extraction_worker as worker
import extraction_compat as compat
from plugins.web import keyless_mcp as k
from tools import web_tools as web, web_result_cache as cache
class Provider:
    name='keenable'
    display_name='Keenable'
    def supports_extract(self): return True
    def uses_keyless(self): return False
    def extract(self, urls, format=None):
        from publication_provenance import provider_publication
        rows = k.keenable_extract_keyless(urls)
        for row in rows:
            row['publication'] = provider_publication(1791980493)
            row['extraction_location'] = {'version': 1, 'requested_url': urls[0], 'returned_url': row['url']}
        return rows
with tempfile.TemporaryDirectory() as td, ExitStack() as s:
    s.enter_context(patch('hermes_cli.config.load_config', return_value={'web':{'extract_backend':'fixture'}}))
    s.enter_context(patch('agent.web_search_registry.get_provider', return_value=Provider()))
    s.enter_context(patch.object(compat, 'check_url', AsyncMock(side_effect=lambda u:u)))
    s.enter_context(patch.object(cache, 'extract_cache_get', side_effect=AssertionError('cache read')))
    s.enter_context(patch.object(cache, 'extract_cache_put', side_effect=AssertionError('cache write')))
    s.enter_context(patch.object(k, '_keenable_request', return_value={
        'url':'https://unknown.example/news/story', 'title':'Article',
        'content':'The company raised its revenue guidance after stronger customer demand. '*10,
        'published_at':1791980493}))
    worker.main()
'''
        command = adapter.worker_command()
        command[-1] = prefix + script
        with patch.object(adapter, 'worker_command', return_value=command):
            result = adapter.run_worker(URL, 15)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['page']['publication'], PUB)
        page = radar.validate_structured_page(URL, result)
        self.assertIsNone(page['published_at'])
        self.assertEqual(page['publication'], PUB)


if __name__ == '__main__': unittest.main()
