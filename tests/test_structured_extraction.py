"""Exact-URL extraction boundary: no agents, bounded untrusted data and private telemetry."""
import asyncio
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import alpha_radar as radar

URL = 'https://unknown.example/news/story'
BODY = 'The company raised its full year revenue guidance after stronger customer demand. ' * 5


def module(name):
    assert importlib.util.find_spec(name) is not None, f'{name}: structured worker not implemented'
    return importlib.import_module(name)


def envelope(url=URL, text=BODY):
    return {'version': 1, 'status': 'ok', 'page': {'url': url, 'title': 'Release', 'text': text}}


class StructuredExtractionTests(unittest.TestCase):
    def test_b1_html_head_paragraph_denial_and_article_controls(self):
        worker = module('extraction_worker')
        adapter = module('structured_extraction')
        now = radar.dt.datetime(2026, 10, 17, tzinfo=radar.dt.timezone.utc)
        meta = '<meta property="article:published_time" content="2026-10-17T00:00:00Z">'
        for wrapper in ('p', 'div'):
            for denied in (True, False):
                body = ('Access denied' if denied else BODY) + '</' + wrapper + '><p>'
                text = '<html><head><title>News service</title></head><body>' + meta + '<' + wrapper + '>' + body + ('Access denied. Please retry later.' * 20) + '</p></body></html>'
                async def dispatch(*args, **kwargs):
                    return json.dumps({'results': [{'url': URL, 'content': text}]})
                with self.subTest(wrapper=wrapper, denied=denied):
                    result = asyncio.run(worker.extract({'version': 1, 'url': URL}, dispatch))
                    self.assertEqual(result['status'], 'error' if denied else 'ok')
                    with patch.object(adapter, 'run_worker', return_value=envelope(text=text)), patch.object(radar, 'is_safe_public_url', return_value=True):
                        page = radar.fetch_source_via_gateway(URL)
                    self.assertEqual(page is None, denied)
                    direct = {'url': URL, 'text': text, 'published_at': '2026-10-17T00:00:00Z'}
                    with tempfile.TemporaryDirectory() as td:
                        cache = Path(td)/'cache.json'
                        cache.write_text(json.dumps({URL: {'checked_at': radar.dt.datetime.now(radar.dt.timezone.utc).isoformat(), 'page': direct}}))
                        with patch.object(radar, 'fetch_source', side_effect=AssertionError('cache expected')):
                            cached = radar.gather_evidence([URL], cache_path=cache)
                    for pages in ([direct], cached, [page] if page else []):
                        accepted, _ = radar.filter_evidence(pages, now=now)
                        self.assertEqual(len(accepted), int(not denied))

    def test_b1_actual_direct_normalization_and_source_cache_replay(self):
        from io import BytesIO

        class Response(BytesIO):
            def geturl(self):
                return URL

        now = radar.dt.datetime(2026, 10, 17, tzinfo=radar.dt.timezone.utc)
        meta = '<meta property="article:published_time" content="2026-10-17T00:00:00Z">'
        for wrapper in ('p', 'div'):
            for denied in (True, False):
                leading = 'Access denied' if denied else BODY
                paragraphs = [leading] + ['Access denied. Please retry later.'] * 20
                raw = ('<html><head><title>News service</title></head><body>' + meta
                       + ''.join(f'<{wrapper}>{text}</{wrapper}>' for text in paragraphs)
                       + '</body></html>')
                with tempfile.TemporaryDirectory() as td, patch.object(
                    radar, 'safe_urlopen', return_value=Response(raw.encode())
                ) as transport:
                    direct = radar.fetch_source(URL)
                    self.assertEqual(direct['title'], 'News service')
                    self.assertTrue(direct['text'].startswith('News service ' + leading))
                    self.assertNotIn('<', direct['text'])
                    self.assertEqual(direct['published_at'], '2026-10-17T00:00:00Z')
                    cache = Path(td) / 'source_cache.json'
                    cache.write_text(json.dumps({URL: {
                        'checked_at': radar.dt.datetime.now(radar.dt.timezone.utc).isoformat(),
                        'page': direct,
                    }}))
                    cached = radar.gather_evidence([URL], cache_path=cache)
                    transport.assert_called_once()
                    self.assertEqual(cached, [direct])
                    for lane, pages in (('actual_direct', [direct]), ('normalized_cache', cached)):
                        with self.subTest(wrapper=wrapper, denied=denied, lane=lane):
                            accepted, quality = radar.filter_evidence(pages, now=now)
                            self.assertEqual(len(accepted), int(not denied))
                            self.assertEqual([q['reason'] for q in quality],
                                             ['article_body_missing'] if denied else [])

    def test_b1_normalized_title_error_validation_at_worker_and_parent(self):
        worker = module('extraction_worker')
        adapter = module('structured_extraction')
        for denied in (True, False):
            text = 'News service ' + ('Access denied. ' if denied else BODY)
            text += 'Access denied. Please retry later. ' * 20
            async def dispatch(*args, **kwargs):
                return json.dumps({'results': [{'url': URL, 'title': 'News service', 'content': text}]})
            with self.subTest(denied=denied, lane='worker'):
                result = asyncio.run(worker.extract({'version': 1, 'url': URL}, dispatch))
                self.assertEqual(result['status'], 'error' if denied else 'ok')
            out = envelope(text=text)
            out['page']['title'] = 'News service'
            with self.subTest(denied=denied, lane='parent'), patch.object(
                adapter, 'run_worker', return_value=out
            ), patch.object(radar, 'is_safe_public_url', return_value=True):
                self.assertEqual(radar.fetch_source_via_gateway(URL) is None, denied)

    def test_b2_installed_dispatcher_repeated_and_old_cache_provenance(self):
        adapter = module('structured_extraction')
        prefix = adapter.worker_command()[-1].split('runpy.run_path(')[0]
        probe = r'''
import asyncio, json, tempfile
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch, AsyncMock
import alpha_radar as radar
import extraction_worker as worker
import structured_extraction as adapter
import tools.web_tools as web
import tools.web_result_cache as cache
class Provider:
    name='fixture-not-firecrawl'
    display_name='Fixture'
    calls=0
    def supports_extract(self): return True
    async def extract(self, urls, format=None):
        self.calls+=1
        return [{'url':returned,'title':'Release','content':body,'error':None,'metadata':{'sourceURL':requested}}]
async def scenario():
    outputs=[]
    for kind, target, old, want_calls, want_accepted in [
        ('stale','https://www.reuters.com/business/archive-2025-10-17/',False,2,0),
        ('future','https://www.reuters.com/business/archive-2027-10-17/',False,2,0),
        ('redirect','https://news.reuters.com/business/redirect-2026-10-17/',False,2,1),
        ('old','https://www.reuters.com/business/archive-2025-10-17/',True,2,0),
        ('general','https://unknown.example/news/story',False,1,1),
    ]:
        global requested, returned, body
        requested = 'https://unknown.example/news/story' if kind=='general' else 'https://www.reuters.com/business/current-2026-10-17/'
        returned=target
        body=('Published: October 17, 2026\n' if kind=='general' else 'Oct 17 (Reuters) - ') + ('The company reported stronger sales and raised earnings guidance. '*10)
        provider=Provider()
        with tempfile.TemporaryDirectory(dir='/home/hermes/.hermes/cache/scratch') as td, ExitStack() as stack:
            stack.enter_context(patch.object(web,'_load_web_config',return_value={'extract_backend':provider.name,'cache_enabled':True}))
            stack.enter_context(patch.object(web,'_ensure_web_plugins_loaded'))
            stack.enter_context(patch('agent.web_search_registry.get_provider',return_value=provider))
            stack.enter_context(patch.object(web,'async_is_safe_url',AsyncMock(return_value=True)))
            stack.enter_context(patch('tools.website_policy.check_website_access',return_value=None))
            stack.enter_context(patch.object(web,'_finish_debug',return_value=None))
            stack.enter_context(patch.object(cache,'_cache_dir',return_value=Path(td)))
            original_get=cache.extract_cache_get
            if old:
                cache.extract_cache_put(requested,body,'Old unannotated',format='markdown',provider=provider.name)
                assert original_get(requested,format='markdown',provider=provider.name)['cached'] is True
            observations=[]
            for i in range(2):
                env=await worker.extract({'version':1,'url':requested})
                assert cache.extract_cache_get is original_get, 'guard leaked outside worker dispatch'
                assert original_get(requested,format='markdown',provider=provider.name)['cached'] is True, 'real dispatcher cache write missing'
                with patch.object(adapter,'run_worker',return_value=env),patch.object(radar,'is_safe_public_url',return_value=True):
                    page=radar.fetch_source_via_gateway(requested)
                accepted,quality=radar.filter_evidence([page] if page else [],now=radar.dt.datetime(2026,10,17,tzinfo=radar.dt.timezone.utc))
                observations.append({'accepted':len(accepted),'returned':env.get('page',{}).get('url'),'published':page.get('published_at') if page else None})
            outputs.append({'kind':kind,'calls':provider.calls,'observations':observations})
            assert [x['accepted'] for x in observations]==[want_accepted,want_accepted], outputs[-1]
            assert provider.calls==want_calls, outputs[-1]
            if kind=='redirect':
                assert all(x['published']=='2026-10-17T00:00:00Z' and x['returned']==target for x in observations)
                parent_cache=Path(td)/'source_cache.json'
                parent_cache.write_text(json.dumps({requested:{'checked_at':radar.dt.datetime.now(radar.dt.timezone.utc).isoformat(),'page':page}}))
                with patch.object(radar,'fetch_source',side_effect=AssertionError('parent cache must avoid fetch')),patch.object(radar,'fetch_source_via_gateway',side_effect=AssertionError('parent cache must avoid worker')):
                    reused=radar.gather_evidence([requested],cache_path=parent_cache)
                assert reused[0]['returned_url']==target and reused[0]['published_at']=='2026-10-17T00:00:00Z'
    return outputs
print(json.dumps(asyncio.run(scenario())))
'''
        result = subprocess.run(adapter.worker_command()[:-1] + [prefix + probe], capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr[-4000:])
        self.assertEqual(len(json.loads(result.stdout)), 5)

    def test_b2_unattested_reuters_url_cannot_supply_year(self):
        adapter = module('structured_extraction')
        url = 'https://www.reuters.com/business/current-2026-10-17/'
        for provenance in (None, 'legacy_cache', False):
            out = envelope(url, 'Oct 17 (Reuters) - ' + BODY)
            if provenance is not None:
                out['page']['location_provenance'] = provenance
            with self.subTest(provenance=provenance), patch.object(adapter, 'run_worker', return_value=out), patch.object(radar, 'is_safe_public_url', return_value=True):
                page = radar.fetch_source_via_gateway(url)
                self.assertTrue(page is None or page['published_at'] is None)

    def test_review_r5_concurrent_live_runs_correlate_initial_rescue_cache_and_quality(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        barrier = threading.Barrier(2)
        def scout(*args, **kwargs):
            barrier.wait(timeout=5)
            return subprocess.CompletedProcess([], 0, json.dumps({'candidates': [{'symbol': 'ABC', 'catalyst': 'current company event', 'event_date': '2026-10-17', 'urls': [URL]}]}), '')
        def direct(url, timeout):
            return {'url': url, 'title': 'Release', 'text': BODY, 'published_at': '2026-10-17T00:00:00Z'}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/'private').mkdir()
            (root/'private'/'source_cache.json').write_text(json.dumps({URL: {'checked_at': radar.dt.datetime.now(radar.dt.timezone.utc).isoformat(), 'page': {'url': URL, 'text': BODY, 'published_at': '2025-10-17T00:00:00Z'}}}))
            with patch.object(radar, 'ROOT', root), patch.object(radar, 'discovery_command', return_value=['offline']), patch.object(radar.subprocess, 'run', side_effect=scout), patch.object(radar, 'fetch_source', side_effect=direct), patch.object(radar, 'fetch_source_via_gateway', side_effect=AssertionError('no network fallback')), patch.object(radar, 'sec_edgar_filing_url', return_value=None), patch.object(radar, 'gateway_rescue_url', side_effect=lambda *a, role, **kw: 'https://' + role + '.example/news'), patch.object(radar, 'synthesize_candidate', return_value={'status': 'none'}):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: radar.live_research({}), range(2)))
            attempts = [json.loads(x) for x in (root/'private'/'source_attempts.jsonl').read_text().splitlines()]
            diagnostics = [json.loads(x) for x in (root/'private'/'research_diagnostics.jsonl').read_text().splitlines()]
        run_ids = {row['run_id'] for row in diagnostics if row['stage'] == 'discovery'}
        self.assertEqual(len(run_ids), 2)
        self.assertEqual({row['run_id'] for row in attempts}, run_ids)
        self.assertEqual({row['run_id'] for row in diagnostics}, run_ids)
        for run_id in run_ids:
            rows = [row for row in attempts if row['run_id'] == run_id]
            self.assertGreaterEqual(len({row['collection_id'] for row in rows}), 2)
            cached = [row for row in rows if row['direct_reason'] == 'cache_hit']
            self.assertEqual(len(cached), 1)
            self.assertIs(cached[0]['network_attempted'], False)
            quality = [row for row in diagnostics if row['run_id'] == run_id and row['reason'] == 'stale_source']
            self.assertEqual(len(quality), 1)
            self.assertEqual(quality[0]['url_id'], cached[0]['url_id'])
            self.assertEqual(quality[0]['domain'], 'unknown.example')
        for secret in (URL, BODY, 'secret'):
            self.assertNotIn(secret, json.dumps(attempts + diagnostics))

    def test_review_r5_attempt_persistence_failure_is_not_rescue_unavailable(self):
        adapter = module('structured_extraction')
        with tempfile.TemporaryDirectory() as td, patch.object(radar, 'fetch_source', return_value={'url': URL, 'text': BODY}), patch.object(adapter, 'record_attempts', side_effect=OSError('disk failed')):
            with self.assertRaises(radar.ResearchFailure) as caught:
                radar.gather_evidence([URL], attempt_path=Path(td)/'attempts.jsonl')
        self.assertEqual(caught.exception.code, 'research_persistence_failure')

    def test_review_r6_wire_datelines_remain_usable_and_source_bound(self):
        adapter = module('structured_extraction')
        now = radar.dt.datetime(2026, 10, 17, tzinfo=radar.dt.timezone.utc)
        for host, dateline, iso in [('www.globenewswire.com', 'RICHMOND, Va., Oct. 08, 2026 (GLOBE NEWSWIRE) --', '2026-10-08'), ('www.prnewswire.com', 'BURLINGTON, N.C., July 30, 2026 /PRNewswire/ --', '2026-07-30')]:
            url = 'https://' + host + '/news/story'
            for year, reason in [('2026', None), ('2025', 'stale_source'), ('2027', 'source_freshness_unknown')]:
                text = dateline.replace('2026', year) + '\n' + BODY
                with self.subTest(host=host, year=year), patch.object(adapter, 'run_worker', return_value=envelope(url, text)), patch.object(radar, 'is_safe_public_url', return_value=True):
                    page = radar.fetch_source_via_gateway(url)
                    self.assertEqual(page['published_at'], iso.replace('2026', year) + 'T00:00:00Z')
                    accepted, diagnostics = radar.filter_evidence([page], now=now)
                    self.assertEqual(len(accepted), int(reason is None))
                    if reason: self.assertEqual(diagnostics[0]['reason'], reason)
            for text in ['Upcoming event on July 30, 2026. Copyright 2026. ' + BODY, 'The conference will convene in ' + dateline + '\n' + BODY]:
                self.assertIsNone(radar.extract_gateway_publication_date(url, text))
            self.assertIsNone(radar.extract_gateway_publication_date(URL, dateline + BODY))
            # The requested publisher cannot select a parser for another returned publisher.
            with patch.object(adapter, 'run_worker', return_value=envelope(url, dateline + '\n' + BODY)), patch.object(radar, 'is_safe_public_url', return_value=True):
                page = radar.fetch_source_via_gateway(url)
            with tempfile.TemporaryDirectory() as td, patch.object(radar, 'fetch_source', side_effect=AssertionError('cache must avoid network')):
                cache = Path(td)/'cache.json'
                cache.write_text(json.dumps({url: {'checked_at': radar.dt.datetime.now(radar.dt.timezone.utc).isoformat(), 'page': page}}))
                self.assertEqual(radar.gather_evidence([url], cache_path=cache)[0]['published_at'], page['published_at'])

    def test_review_r6_public_tool_footer_is_not_article_or_date(self):
        worker = module('extraction_worker')
        adapter = module('structured_extraction')
        footer = '\n──────── [TRUNCATED] ────────\nShowing 10 chars (head) + 0 chars (tail) of 500 total clean characters.\nFull text saved to: /private/secret/article.txt\nPublished: October 17, 2026\nTo read the omitted middle: read_file path="/private/secret/article.txt" offset=2 limit=200\n─────────────────────────────'
        async def dispatch(*args, **kwargs): return json.dumps({'results': [{'url': URL, 'content': BODY + footer}]})
        result = asyncio.run(worker.extract({'version': 1, 'url': URL}, dispatch))
        self.assertNotIn('/private/', result['page']['text'])
        with patch.object(adapter, 'run_worker', return_value=envelope(text=BODY + footer)), patch.object(radar, 'is_safe_public_url', return_value=True):
            page = radar.fetch_source_via_gateway(URL)
            self.assertIsNone(page['published_at'])
            self.assertNotIn('TRUNCATED', page['text'])
        accepted, diagnostics = radar.filter_evidence([{'url': URL, 'text': BODY + footer, 'published_at': '2026-10-17T00:00:00Z'}], now=radar.dt.datetime(2026, 10, 17, tzinfo=radar.dt.timezone.utc))
        self.assertEqual(len(accepted), 1)
        self.assertNotIn('/private/', accepted[0]['text'])
        accepted, diagnostics = radar.filter_evidence([{'url': URL, 'text': 'Short' + footer, 'published_at': '2026-10-17T00:00:00Z'}], now=radar.dt.datetime(2026, 10, 17, tzinfo=radar.dt.timezone.utc))
        self.assertEqual(accepted, [])
        self.assertEqual(diagnostics[0]['reason'], 'article_body_missing')

    def test_review_r4_strict_json_at_all_three_boundaries(self):
        import io
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        worker = module('extraction_worker')
        adapter = module('structured_extraction')
        row = json.dumps({'url': URL, 'content': BODY})
        provider_cases = ['{"results":[],"results":[' + row + ']}', '{"results":[' + row[:-1] + ',"url":' + json.dumps(URL) + '}]}', '{"error":"failed","error":null,"results":[' + row + ']}']
        duplicates = [('status', '"ok"'), ('page', '{}'), ('url', json.dumps(URL)), ('error', 'null')]
        for key, value in duplicates:
            pair = json.dumps(key) + ':' + value
            provider_cases += ['{' + pair + ',' + pair + ',"results":[' + row + ']}', '{"results":[' + row[:-1] + ',' + pair + ',' + pair + '}]}']
        for constant in ('NaN', 'Infinity', '-Infinity'):
            provider_cases.append('{"extra":' + constant + ',"results":[' + row + ']}')
        for raw in provider_cases:
            async def dispatch(*args, **kwargs): return raw
            with self.subTest(boundary='provider', raw=raw[:80]):
                self.assertEqual(asyncio.run(worker.extract({'version': 1, 'url': URL}, dispatch))['reason'], 'malformed_response')
        supervisor_cases = ['{"version":1,"status":"error","status":"ok","page":' + json.dumps(envelope()['page']) + '}', json.dumps(envelope())[:-1] + ',"extra":NaN}', '{"version":1,"status":"ok","page":{},"page":' + json.dumps(envelope()['page']) + '}', json.dumps(envelope()).replace('"url":', '"url":"wrong","url":')]
        supervisor_cases += ['{' + json.dumps(key) + ':' + value + ',' + json.dumps(key) + ':' + value + '}' for key, value in duplicates]
        supervisor_cases += ['{"extra":' + constant + '}' for constant in ('NaN', 'Infinity', '-Infinity')]
        for raw in supervisor_cases:
            with self.subTest(boundary='supervisor'), patch.object(adapter, 'worker_command', return_value=[sys.executable, '-c', 'print(' + repr(raw) + ')']):
                self.assertEqual(adapter.run_worker(URL, 1), {'version': 1, 'status': 'error', 'reason': 'malformed_response'})
        request_cases = ['{"version":1,"version":1,"url":' + json.dumps(URL) + '}', '{"version":1,"url":"wrong","url":' + json.dumps(URL) + '}', '{"version":1,"url":' + json.dumps(URL) + ',"extra":NaN}']
        request_cases += ['{"version":1,"url":' + json.dumps(URL) + ',' + json.dumps(key) + ':' + value + ',' + json.dumps(key) + ':' + value + '}' for key, value in duplicates]
        request_cases += ['{"version":1,"url":' + json.dumps(URL) + ',"extra":' + constant + '}' for constant in ('NaN', 'Infinity', '-Infinity')]
        for raw in request_cases:
            output = io.StringIO()
            with self.subTest(boundary='request'), patch.object(worker.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(raw.encode()))), patch.object(worker.sys, 'stdout', output), patch.object(worker, 'extract', new=AsyncMock(return_value=envelope())) as extract:
                worker.main()
                self.assertEqual(json.loads(output.getvalue())['reason'], 'malformed_response')
                extract.assert_not_called()

    def test_review_r3_explicit_provider_declarations_and_types(self):
        worker = module('extraction_worker')
        for level in ('top', 'row'):
            for field, value in [('success', False), ('success', 0), ('success', ''), ('success', None), ('status', 'error'), ('status', False), ('status', 0), ('status', None), ('status', ''), ('error', False), ('error', 0), ('error', []), ('error', {}), ('title', False), ('blocked_by_policy', True), ('blocked_by_policy', 0), ('blocked_by_policy', None)]:
                row = {'url': URL, 'content': BODY, 'title': 'Release'}
                payload = {'results': [row]}
                (payload if level == 'top' else row)[field] = value
                # title is a documented row field only.
                if level == 'top' and field == 'title': continue
                async def dispatch(*args, **kwargs): return json.dumps(payload)
                with self.subTest(level=level, field=field, value=value):
                    self.assertEqual(asyncio.run(worker.extract({'version': 1, 'url': URL}, dispatch))['status'], 'error')
        async def good(*args, **kwargs):
            return json.dumps({'success': True, 'status': 'ok', 'error': None, 'results': [{'url': URL, 'content': BODY, 'error': '', 'success': True, 'status': 'success'}]})
        self.assertEqual(asyncio.run(worker.extract({'version': 1, 'url': URL}, good))['status'], 'ok')

    def test_review_r2_returned_reuters_provenance_not_requested_year(self):
        adapter = module('structured_extraction')
        requested = 'https://www.reuters.com/business/current-2026-10-17/'
        for date in ('2025-10-17', '2027-10-17'):
            returned = 'https://www.reuters.com/business/archive-' + date + '/'
            with self.subTest(date=date), patch.object(adapter, 'run_worker', return_value=envelope(returned, 'Oct 17 (Reuters) - ' + BODY)), patch.object(radar, 'is_safe_public_url', return_value=True):
                self.assertIsNone(radar.fetch_source_via_gateway(requested))
        returned = 'https://news.reuters.com/business/redirect-2026-10-17/'
        out = envelope(returned, 'Oct 17 (Reuters) - ' + BODY)
        # Match the guarded installed worker envelope; keep all original
        # returned URL/date/request-binding assertions below unchanged.
        out['page']['location_provenance'] = 'uncached_dispatch'
        with patch.object(adapter, 'run_worker', return_value=out), patch.object(radar, 'is_safe_public_url', return_value=True):
            page = radar.fetch_source_via_gateway(requested)
            self.assertEqual(page['url'], requested)
            self.assertEqual(page['published_at'], '2026-10-17T00:00:00Z')
            self.assertEqual(page['returned_url'], returned)

    def test_review_r1_normalized_error_documents_never_become_evidence(self):
        worker = module('extraction_worker')
        adapter = module('structured_extraction')
        for heading in ('# Error extracting content', '<div><h1>Access denied</h1></div>', '**Failed to extract content**', '# Forbidden', '<p>Content was inaccessible</p>', '<html><head><title>News service</title></head><body><h1>Access denied</h1></body></html>', 'Provider output follows:\n# Error extracting content'):
            text = heading + '\nPublished: October 17, 2026\n' + ('Access denied. Please retry later. ' * 20)
            async def dispatch(*args, **kwargs):
                return json.dumps({'results': [{'url': URL, 'content': text}]})
            with self.subTest(heading=heading):
                self.assertEqual(asyncio.run(worker.extract({'version': 1, 'url': URL}, dispatch))['status'], 'error')
                with patch.object(adapter, 'run_worker', return_value=envelope(text=text)), patch.object(radar, 'is_safe_public_url', return_value=True):
                    self.assertIsNone(radar.fetch_source_via_gateway(URL))
                pages, diagnostics = radar.filter_evidence([{'url': URL, 'text': text, 'published_at': '2026-10-17T00:00:00Z'}], now=radar.dt.datetime(2026, 10, 17, tzinfo=radar.dt.timezone.utc))
                self.assertEqual(pages, [])

    def test_gateway_uses_structured_result_without_model_or_manufactured_date(self):
        adapter = module('structured_extraction')
        with patch.object(adapter, 'run_worker', return_value=envelope()), patch.object(radar, 'is_safe_public_url', return_value=True), patch.object(radar, 'research_subprocess_command', side_effect=AssertionError('model forbidden')):
            page = radar.fetch_source_via_gateway(URL)
        self.assertEqual(page, {'url': URL, 'title': 'Release', 'text': BODY.strip(), 'published_at': None})

    def test_worker_dispatch_contract_and_untrusted_provider_response(self):
        worker = module('extraction_worker')
        async def dispatch(urls, format=None, char_limit=None):
            self.assertEqual((urls, format, char_limit), ([URL], 'markdown', 6000))
            return json.dumps({'results': [{'url': URL, 'title': 'Release', 'content': BODY, 'error': None, 'metadata': {'date': '2099-01-01'}}]})
        result = asyncio.run(worker.extract({'version': 1, 'url': URL}, dispatch))
        self.assertEqual(result, envelope())
        for raw, reason in [('plain error prose', 'malformed_response'), ('{}', 'malformed_response'), (json.dumps({'error': 'secret raw failure'}), 'provider_error'), (json.dumps({'results': [{'url': URL, 'content': BODY, 'error': 'secret'}]}), 'provider_error')]:
            async def bad(*a, **kw): return raw
            with self.subTest(raw=raw):
                out = asyncio.run(worker.extract({'version': 1, 'url': URL}, bad))
                self.assertEqual(out, {'version': 1, 'status': 'error', 'reason': reason})
                self.assertNotIn('secret', json.dumps(out))

    def test_parent_rejects_malformed_typed_errors_and_mismatched_urls(self):
        adapter = module('structured_extraction')
        cases = [{}, {'version': True, 'status': 'ok', 'page': {}}, {'version': 1, 'status': 'error', 'reason': 'provider_error'}, envelope('https://other.example/a'), envelope('http://127.0.0.1/a'), envelope(text='Error: extraction failed'), envelope(text=BODY * 100), envelope('https://unknown.example.attacker.com/a')]
        for out in cases:
            with self.subTest(out=str(out)[:60]), patch.object(adapter, 'run_worker', return_value=out), patch.object(radar, 'is_safe_public_url', side_effect=lambda u: '127.0.0.1' not in u):
                self.assertIsNone(radar.fetch_source_via_gateway(URL))
                with self.assertRaisesRegex(radar.ResearchFailure, 'research_rescue_unavailable'):
                    radar.fetch_source_via_gateway(URL, strict_provider=True)

    def test_safe_same_publisher_redirect_preserves_request_binding(self):
        adapter = module('structured_extraction')
        for returned in ['https://news.unknown.example/new-story', URL+'?output=1']:
            with patch.object(adapter, 'run_worker', return_value=envelope(returned)), patch.object(radar, 'is_safe_public_url', return_value=True):
                self.assertEqual(radar.fetch_source_via_gateway(URL)['url'], URL)
        with patch.object(adapter, 'run_worker') as run, patch.object(radar, 'is_safe_public_url', return_value=False):
            self.assertIsNone(radar.fetch_source_via_gateway(URL))
            run.assert_not_called()

    def test_publication_provenance_not_unrelated_body_or_crawl_dates(self):
        adapter = module('structured_extraction')
        cases = [('Copyright 2026-10-17. Forecast event 2026-11-01. ' + BODY, None), ('Published: October 16, 2026\n' + BODY, '2026-10-16T00:00:00Z')]
        for body, want in cases:
            with patch.object(adapter, 'run_worker', return_value=envelope(text=body)), patch.object(radar, 'is_safe_public_url', return_value=True):
                self.assertEqual(radar.fetch_source_via_gateway(URL)['published_at'], want)

    def test_supervisor_bounds_timeout_and_both_pipes_and_nonzero(self):
        adapter = module('structured_extraction')
        cases = [("import time; time.sleep(10)", 'timeout'), ("import sys; sys.stdout.write('x'*200000); sys.stdout.flush(); __import__('time').sleep(10)", 'output_limit'), ("import sys; sys.stderr.write('s'*200000); sys.stderr.flush(); __import__('time').sleep(10)", 'output_limit'), ("raise SystemExit(2)", 'worker_exit'), ("print('not json')", 'malformed_response')]
        for code, reason in cases:
            start = time.monotonic()
            with patch.object(adapter, 'worker_command', return_value=[sys.executable, '-c', code]):
                result = adapter.run_worker(URL, 0.25)
            self.assertEqual(result, {'version': 1, 'status': 'error', 'reason': reason})
            self.assertLess(time.monotonic() - start, 2)

    def test_runtime_bootstrap_supports_installed_dispatch_import_without_network(self):
        adapter = module('structured_extraction')
        command = adapter.worker_command()
        # Reuse exact bootstrap; replace only worker entry point with import-only probe.
        probe = command[-1].split('runpy.run_path(')[0] + "import tools.web_tools; import aiohttp; print('dispatcher-ready')"
        result = subprocess.run(command[:-1] + [probe], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertEqual(result.stdout.strip(), 'dispatcher-ready')

    def test_attempt_rows_keep_direct_failure_separate_from_fallback_success(self):
        module('structured_extraction')
        error=__import__('urllib.error', fromlist=['HTTPError']).HTTPError(URL,403,'secret',{},None)
        self.addCleanup(error.close)
        with tempfile.TemporaryDirectory() as td, patch.object(radar, 'ROOT', Path(td)), patch.object(radar, 'fetch_source', side_effect=error), patch.object(radar, 'fetch_source_via_gateway', side_effect=lambda url, **kw: {'url': url, 'title': 'Release', 'text': BODY, 'published_at': None}):
            diagnostics = []
            pages = radar.gather_evidence([URL, URL + '/two'], diagnostics=diagnostics, attempt_path=Path(td)/'private'/'source_attempts.jsonl')
            self.assertEqual(len(pages), 2)
            self.assertEqual(diagnostics, [])
            rows = [json.loads(line) for line in (Path(td)/'private'/'source_attempts.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({r['run_id'] for r in rows}), 1)
        self.assertEqual(len({r['url_id'] for r in rows}), 2)
        for row in rows:
            self.assertEqual(row['direct_reason'], 'source_http_forbidden')
            self.assertEqual(row['direct_status'], 403)
            self.assertEqual(row['fallback_result'], 'success')
            self.assertGreaterEqual(row['direct_elapsed_ms'], 0)
            self.assertGreaterEqual(row['fallback_elapsed_ms'], 0)
            self.assertGreater(row['remaining_ms'], 0)
        text = json.dumps(rows)
        for secret in [URL, 'unknown.example', BODY, 'secret']:
            self.assertNotIn(secret, text)

    def test_typed_fallback_failure_does_not_replace_legacy_direct_reason(self):
        adapter = module('structured_extraction')
        with tempfile.TemporaryDirectory() as td, patch.object(radar, 'ROOT', Path(td)), patch.object(radar, 'fetch_source', side_effect=TimeoutError('secret')), patch.object(radar, 'is_safe_public_url', return_value=True), patch.object(adapter, 'run_worker', return_value={'version': 1, 'status': 'error', 'reason': 'timeout'}):
            diagnostics = []
            self.assertEqual(radar.gather_evidence([URL], diagnostics=diagnostics, attempt_path=Path(td)/'private'/'source_attempts.jsonl'), [])
            self.assertEqual(diagnostics[0]['reason'], 'source_fetch_timeout')
            row = json.loads((Path(td)/'private'/'source_attempts.jsonl').read_text())
            self.assertEqual(row['fallback_result'], 'timeout')
            self.assertEqual(row['direct_reason'], 'source_fetch_timeout')
    def test_conflicting_error_and_success_envelope_is_not_evidence(self):
        adapter=module('structured_extraction')
        out=envelope()
        out['error']='provider failed'
        with patch.object(adapter,'run_worker',return_value=out), patch.object(radar,'is_safe_public_url',return_value=True):
            self.assertIsNone(radar.fetch_source_via_gateway(URL))

    def test_deadline_snapshot_reports_inflight_elapsed(self):
        import threading
        release=threading.Event()
        def blocked(url, timeout):
            release.wait(1)
            raise TimeoutError('fixture')
        try:
            with tempfile.TemporaryDirectory() as td, patch.object(radar,'fetch_source',side_effect=blocked), patch.object(radar,'fetch_source_via_gateway',return_value=None):
                path=Path(td)/'attempts.jsonl'
                pages=radar.gather_evidence([URL],collection_budget_seconds=0.03,attempt_path=path)
                row=json.loads(path.read_text())
                self.assertEqual(pages,[])
                self.assertEqual(row['direct_reason'],'source_deadline_exhausted')
                self.assertGreaterEqual(row['direct_elapsed_ms'],20)
                self.assertEqual(row['remaining_ms'],0)
        finally:
            release.set()

    def test_success_does_not_invent_direct_http_status(self):
        with tempfile.TemporaryDirectory() as td, patch.object(radar, 'fetch_source', return_value={'url':URL,'text':BODY,'title':'Release','published_at':None}):
            path=Path(td)/'attempts.jsonl'
            radar.gather_evidence([URL],attempt_path=path)
            row=json.loads(path.read_text())
            self.assertEqual(row['direct_reason'],'success')
            self.assertIsNone(row['direct_status'])
            self.assertEqual(row['fallback_result'],'not_attempted')

    def test_deeply_nested_worker_json_is_a_typed_failure(self):
        adapter=module('structured_extraction')
        code="print('['*2000+'0'+']'*2000)"
        with patch.object(adapter,'worker_command',return_value=[sys.executable,'-c',code]):
            self.assertEqual(adapter.run_worker(URL,1),{'version':1,'status':'error','reason':'malformed_response'})

    def test_malformed_redirect_is_failure_not_uncaught_parser_error(self):
        adapter = module('structured_extraction')
        with patch.object(adapter, 'run_worker', return_value=envelope('https://[broken')), patch.object(radar, 'is_safe_public_url', return_value=True):
            self.assertIsNone(radar.fetch_source_via_gateway(URL))

    def test_url_validation_time_is_charged_to_fallback_budget(self):
        adapter = module('structured_extraction')
        def delayed_safe(url):
            time.sleep(0.03)
            return True
        with patch.object(adapter, 'run_worker') as run, patch.object(radar, 'is_safe_public_url', side_effect=delayed_safe):
            self.assertIsNone(radar.fetch_source_via_gateway(URL, timeout_seconds=0.01))
            run.assert_not_called()

    def test_worker_standalone_entry_rejects_oversized_input(self):
        adapter = module('structured_extraction')
        result = subprocess.run(adapter.worker_command(), input='x'*9000, text=True, capture_output=True, timeout=20)
        self.assertEqual(json.loads(result.stdout), {'version':1, 'status':'error', 'reason':'invalid_request'})

    def test_supervisor_kills_descendants_on_timeout_and_success(self):
        adapter = module('structured_extraction')
        with tempfile.TemporaryDirectory() as td:
            for timeout_case in (True, False):
                pidfile = Path(td)/'pid'
                pidfile.unlink(missing_ok=True)
                code = ("import subprocess, sys, time, pathlib; "
                        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                        f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); "
                        + ("time.sleep(30)" if timeout_case else "print('{}'); sys.stdout.flush()"))
                with patch.object(adapter, 'worker_command', return_value=[sys.executable, '-c', code]):
                    out = adapter.run_worker(URL, 0.2)
                self.assertEqual(out, {'version':1, 'status':'error','reason':'timeout'} if timeout_case else {})
                pid = int(pidfile.read_text())
                for _ in range(50):
                    stat = Path(f'/proc/{pid}/stat')
                    if not stat.exists() or stat.read_text().split()[2] == 'Z':
                        break
                    time.sleep(0.01)
                else:
                    self.fail('owned descendant still running')

    def test_installed_dispatcher_preserves_configured_route_and_keyless_rescue(self):
        adapter = module('structured_extraction')
        prefix = adapter.worker_command()[-1].split('runpy.run_path(')[0]
        worker_path = str(Path(radar.__file__).with_name('extraction_worker.py'))
        probe = '''
import asyncio, json, runpy
from unittest.mock import patch, AsyncMock
from contextlib import ExitStack
import tools.web_tools as web
import tools.web_tools_extract as ext
class FixtureProvider:
    name='fixture-not-firecrawl'
    display_name='Fixture'
    def supports_extract(self): return True
    async def extract(self, urls, format=None):
        assert urls == ['https://unknown.example/news/story']
        assert format == 'markdown'
        if self.fail: raise OSError('fixture transport failure')
        return [{'url':urls[0], 'title':'Release', 'content':'Factual body '*30, 'error':None}]
provider=FixtureProvider()
worker=runpy.run_path(WORKER_PATH)
async def scenario():
    with ExitStack() as stack:
        stack.enter_context(patch.object(web, '_load_web_config', return_value={'extract_backend':'fixture-not-firecrawl','keyless_fallback':True}))
        stack.enter_context(patch.object(web, '_ensure_web_plugins_loaded'))
        stack.enter_context(patch('agent.web_search_registry.get_provider', side_effect=lambda name: provider if name=='fixture-not-firecrawl' else None))
        stack.enter_context(patch.object(web, 'async_is_safe_url', AsyncMock(return_value=True)))
        stack.enter_context(patch('tools.web_result_cache.extract_cache_get', return_value=None))
        stack.enter_context(patch('tools.web_result_cache.extract_cache_put'))
        stack.enter_context(patch('tools.website_policy.check_website_access', return_value=None))
        stack.enter_context(patch('tools.web_tools_rescue._keyless_rescue_enabled', return_value=True))
        def rescue(name, urls, results):
            assert name=='fixture-not-firecrawl'
            assert urls==['https://unknown.example/news/story']
            return [{'url':urls[0], 'title':'Rescue', 'content':'Rescued factual body '*30, 'error':None}]
        stack.enter_context(patch.object(ext, '_rescue_extract', side_effect=rescue))
        provider.fail=False
        first=await worker['extract']({'version':1,'url':'https://unknown.example/news/story'})
        provider.fail=True
        second=await worker['extract']({'version':1,'url':'https://unknown.example/news/story'})
        return [first,second]
print(json.dumps(asyncio.run(scenario())))
assert 'run_agent' not in sys.modules
assert 'broker_process' not in sys.modules
'''.replace('WORKER_PATH', repr(worker_path))
        result = subprocess.run(adapter.worker_command()[:-1] + [prefix + probe], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        first, second = json.loads(result.stdout)
        self.assertEqual(first['page']['title'], 'Release')
        self.assertEqual(second['page']['title'], 'Rescue')


if __name__ == '__main__':
    unittest.main()
