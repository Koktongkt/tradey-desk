"""Offline dispatcher contracts: fake transport, real projection/evidence checks."""
import copy
import importlib
import importlib.util
import json
import time
import types
import unittest
from unittest.mock import patch

import extraction_compat as compat
import extraction_worker as worker
import alpha_radar as radar
from extraction_contract import strip_tool_footer
from publication_provenance import provider_publication

URL = 'https://unknown.example/news/story'
OTHER = 'https://unknown.example/news/other'
BODY = 'The company raised revenue guidance following stronger customer demand. ' * 12
RING = ['exa', 'parallel', 'firecrawl', 'keenable']
REAL_PRIMARY = compat.primary


def row(url=URL, **extra):
    return {'url': url, 'title': 'Article', 'content': BODY, 'error': None, **extra}


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # An assertion (rather than an import error) records the missing behavior.
        self.assertIsNotNone(importlib.util.find_spec('research_extraction'), 'project dispatcher is missing')
        self.d = importlib.import_module('research_extraction')
        self.calls = []
        self.clock = 100.0
        self.provider = types.SimpleNamespace(name='tavily')
        self.anonymous = False
        self.rescue = True
        self.responses = {'primary': [row()]}
        self.checked = []
        patches = [
            patch.object(compat, 'resolve', side_effect=lambda: self.provider),
            patch.object(compat, 'uses_keyless', side_effect=lambda p: self.anonymous),
            patch.object(compat, 'rescue_allowed', side_effect=lambda p: self.rescue),
            patch.object(compat, 'ring_order', side_effect=lambda n: list(RING)),
            patch.object(compat, 'primary', side_effect=self.primary),
            patch.object(compat, 'keyless', side_effect=self.keyless),
            patch.object(compat, 'check_url', side_effect=self.check),
            patch.object(self.d, 'monotonic', side_effect=lambda: self.clock),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)

    async def check(self, url):
        self.checked.append(url)
        if '127.0.0.1' in url:
            raise compat.CompatibilityError('unsafe_url')
        if 'blocked.' in url:
            raise compat.CompatibilityError('policy_blocked')
        return url.strip().replace('ö', '%C3%B6')

    async def attempt(self, name, urls, deadline, format=None):
        self.calls.append((name, list(urls), deadline, format))
        result = self.responses.get(name, [dict(url=u, error='429 Too many requests') for u in urls])
        if callable(result): result = result()
        if isinstance(result, Exception): raise result
        return copy.deepcopy(result)

    async def primary(self, provider, urls, *, format, deadline):
        return await self.attempt('primary', urls, deadline, format)

    async def keyless(self, vendor, urls, *, deadline):
        return await self.attempt(vendor, urls, deadline)

    async def extract(self, urls=None, **kwargs):
        return json.loads(await self.d.extract_tool([URL] if urls is None else urls, **kwargs))

    def errors(self, out, reason):
        self.assertTrue(out['results'])
        for r in out['results']:
            self.assertEqual(r.get('reason'), reason)
            self.assertIsInstance(r['error'], str)
            self.assertFalse(r.get('content'))

    async def test_malformed_declarations_never_hide_behind_rate_limit_errors(self):
        for field, value in [('success', 0), ('status', None), ('blocked_by_policy', 0)]:
            self.anonymous = True; self.calls.clear()
            self.responses['exa'] = [dict(url=URL, error='429 Too many requests', **{field: value})]
            self.errors(await self.extract(), 'malformed_response')
            self.assertEqual([c[0] for c in self.calls], ['exa'])

    async def test_real_primary_malformed_containers_are_terminal_without_rescue(self):
        # Keep primary/_safe_urls/_rows real; only transport and admission are fake.
        self.provider.extract = lambda urls, *, format: None
        async def invoke(fn, urls, *, format, deadline):
            return await self.attempt('primary', urls, deadline, format)
        for malformed in ({'results': []}, [None], [row(), 'not a row']):
            with self.subTest(malformed=malformed):
                self.calls.clear()
                self.responses['primary'] = malformed
                self.responses['exa'] = [row()]
                with patch.object(compat, 'primary', new=REAL_PRIMARY), \
                     patch.object(compat, '_invoke', side_effect=invoke):
                    out = await self.extract(deadline=time.monotonic() + 10)
                self.errors(out, 'malformed_response')
                self.assertEqual([c[0] for c in self.calls], ['primary'])

    async def test_publication_malformation_cannot_admit_primary_rescue_or_ring_walk(self):
        self.provider.extract = lambda urls, *, format: None
        async def invoke(fn, urls, *, format, deadline):
            return await self.attempt('primary', urls, deadline, format)
        location = {'version': 1, 'requested_url': URL, 'returned_url': URL}
        for anonymous in (False, True):
            for error in ('429 Too many requests', 'upstream unavailable'):
                for extension in (
                    {'publication': {}, 'extraction_location': location},
                    {'publication': None, 'extraction_location': location},
                    {'publication': provider_publication(1791979200)},
                    {'publication': provider_publication(1791979200), 'extraction_location': {}},
                ):
                    with self.subTest(anonymous=anonymous, error=error, extension=extension):
                        self.anonymous = anonymous
                        self.calls.clear()
                        malformed = [row(error=error, **extension)]
                        self.responses.update(primary=malformed, exa=malformed, parallel=[row()])
                        with patch.object(compat, 'primary', new=REAL_PRIMARY), \
                             patch.object(compat, '_invoke', side_effect=invoke):
                            out = await self.extract(deadline=time.monotonic() + 10)
                        self.errors(out, 'malformed_response')
                        self.assertEqual([c[0] for c in self.calls], ['exa'] if anonymous else ['primary'])

    async def test_valid_publication_does_not_promote_declared_error_to_success(self):
        self.responses['primary'] = [row(error='upstream unavailable',
            publication=provider_publication(1791979200),
            extraction_location={'version': 1, 'requested_url': URL, 'returned_url': URL})]
        self.rescue = False
        self.errors(await self.extract(), 'provider_error')
        self.assertEqual([c[0] for c in self.calls], ['primary'])

    async def test_error_envelopes_remain_bounded_for_maximum_unicode_urls(self):
        urls = ['https://unknown.example/' + '\U0001f600' * 4000 + str(i) for i in range(5)]
        out = await self.d.extract_tool(urls, format='unsupported')
        self.assertLessEqual(len(out.encode('utf-8')), 100000)
        self.errors(json.loads(out), 'output_limit')

    async def test_installed_ring_order_and_rate_limit_walk_contract(self):
        # Private copies of installed pure definitions avoid changing its cursor,
        # config, providers, caches or normalizers in this shared interpreter.
        import ast
        import threading
        from pathlib import Path
        import plugins.web.keyless_mcp as installed
        tree = ast.parse(Path(installed.__file__).read_text())
        names = {'_ring_order', '_walk_ring'}
        definitions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual(len(definitions), 2)
        ns = {'_KEYLESS_RING': tuple(installed._KEYLESS_RING),
              '_vendor_pinned': lambda name: True, 'provider_tier': lambda name: 'auto',
              '_ring_lock': threading.Lock(), '_ring_cursor': 0,
              'logger': types.SimpleNamespace(info=lambda *args: None)}
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(installed.__file__), 'exec'), ns)
        attempted = []
        def invoke(vendor):
            attempted.append(vendor)
            return [dict(url=URL, error='429 Too many requests')]
        order, _, _, exhausted = ns['_walk_ring']('parallel', 'extract', invoke, compat.rate_limited)
        self.assertTrue(exhausted)
        self.assertEqual(order, ['parallel', 'firecrawl', 'keenable', 'exa'])
        self.assertEqual(attempted, order)
        self.anonymous = True; self.provider.name = 'parallel'
        with patch.object(compat, 'ring_order', side_effect=ns['_ring_order']):
            self.errors(await self.extract(), 'provider_error')
        self.assertEqual([c[0] for c in self.calls], attempted)

    async def test_returned_url_compatibility_failure_never_rescues_successful_transport(self):
        checks = 0
        async def unavailable_check(url):
            nonlocal checks
            checks += 1
            if checks > 1:
                raise compat.CompatibilityError('provider_error')
            return url
        with patch.object(compat, 'check_url', side_effect=unavailable_check):
            self.errors(await self.extract(), 'provider_error')
        self.assertEqual([c[0] for c in self.calls], ['primary'])

    async def test_primary_exception_can_rescue_once(self):
        self.responses['primary'] = compat.CompatibilityError('provider_error')
        self.responses['exa'] = [row()]
        out = await self.extract()
        self.assertEqual(out['results'][0]['content'], BODY)
        self.assertEqual([c[0] for c in self.calls], ['primary', 'exa'])

    async def test_success_never_rescues(self):
        out = await self.extract()
        self.assertEqual(out['results'][0]['content'], BODY)
        self.assertEqual(self.calls, [('primary', [URL], 130.0, 'markdown')])

    async def test_reordered_rows_bind_by_identity(self):
        self.responses['primary'] = [row(OTHER, content='Second article'), row()]
        out = await self.extract([URL, OTHER])
        self.assertEqual([r['content'] for r in out['results']], [BODY, 'Second article'])
        self.assertEqual([r['extraction_location']['requested_url'] for r in out['results']], [URL, OTHER])

    async def test_missing_duplicate_and_malformed_rows_fail_closed_without_rescue(self):
        for rows in ([row()], [row(), row()], [row(), None], [], {'results': [row()]}):
            self.calls.clear(); self.responses['primary'] = rows
            self.errors(await self.extract([URL, OTHER]), 'malformed_response')
            self.assertEqual(len(self.calls), 1)

    async def test_duplicate_requests_and_normalized_aliases_are_invalid(self):
        for urls in ([URL, URL], [URL, ' ' + URL], ['https://unknown.example/ö', 'https://unknown.example/%C3%B6']):
            self.errors(await self.extract(urls), 'invalid_request')
        self.assertEqual(self.calls, [])

    async def test_original_request_key_survives_normalized_transport(self):
        original = ' https://unknown.example/ö '
        normalized = 'https://unknown.example/%C3%B6'
        self.responses['primary'] = [row(normalized)]
        r = (await self.extract([original]))['results'][0]
        self.assertEqual(self.calls[0][1], [normalized])
        self.assertEqual(r['url'], normalized)
        self.assertEqual(r['extraction_location']['requested_url'], original)

    async def test_conflicting_source_identities_rejected_even_for_one_request(self):
        for extra in ({'sourceURL': OTHER}, {'metadata': {'sourceURL': OTHER}},
                      {'extraction_location': {'version': 1, 'requested_url': OTHER, 'returned_url': URL}},
                      {'sourceURL': False}, {'metadata': {'sourceURL': None}}):
            self.responses['primary'] = [row(**extra)]
            self.errors(await self.extract(), 'url_mismatch')

    async def test_same_publisher_redirect_validated_without_substituting_request(self):
        returned = 'https://news.unknown.example/redirect'
        self.responses['primary'] = [row(returned, metadata={'sourceURL': returned})]
        r = (await self.extract())['results'][0]
        self.assertEqual(r['url'], returned)
        self.assertEqual(r['extraction_location'], {'version': 1, 'requested_url': URL, 'returned_url': returned})
        self.assertIn(returned, self.checked)

    async def test_batch_redirect_requires_explicit_request_binding(self):
        returned = 'https://unknown.example/redirect'
        self.responses['primary'] = [row(OTHER), row(returned)]
        self.errors(await self.extract([URL, OTHER]), 'malformed_response')
        self.responses['primary'][1]['extraction_location'] = {'version': 1, 'requested_url': URL, 'returned_url': returned}
        out = await self.extract([URL, OTHER])
        self.assertEqual([r['url'] for r in out['results']], [returned, OTHER])

    async def test_unsafe_blocked_cross_publisher_and_reuters_dates(self):
        for returned, reason in [('http://127.0.0.1/private', 'unsafe_url'),
                                 ('https://blocked.unknown.example/story', 'provider_error'),
                                 ('https://other.example/story', 'url_mismatch')]:
            self.responses['primary'] = [row(returned)]
            self.errors(await self.extract(), reason)
        requested = 'https://www.reuters.com/a-2026-10-17/'
        self.responses['primary'] = [row('https://news.reuters.com/b-2025-10-17/')]
        self.errors(await self.extract([requested]), 'url_mismatch')

    async def test_rescue_at_most_one_ring(self):
        self.responses['primary'] = [dict(url=URL, error='upstream unavailable')]
        self.errors(await self.extract(), 'provider_error')
        self.assertEqual([c[0] for c in self.calls], ['primary', *RING])
        self.assertEqual(len(set(c[0] for c in self.calls)), 5)

    async def test_primary_vendor_skipped_in_rescue_preserving_remaining_order(self):
        self.provider.name = 'exa'
        self.responses['primary'] = [dict(url=URL, error='outage')]
        await self.extract()
        self.assertEqual([c[0] for c in self.calls], ['primary', 'parallel', 'firecrawl', 'keenable'])

    async def test_anonymous_ring_rate_limit_walk_and_success_stop(self):
        self.anonymous = True; self.provider.name = 'exa'
        self.responses['parallel'] = [row()]
        out = await self.extract()
        self.assertEqual(out['results'][0]['content'], BODY)
        self.assertEqual([c[0] for c in self.calls], ['exa', 'parallel'])

    async def test_partial_failure_stops_free_walk(self):
        for anonymous in (True, False):
            self.anonymous = anonymous; self.calls.clear()
            self.responses['primary'] = [dict(url=URL, error='outage'), dict(url=OTHER, error='outage')]
            self.responses['exa'] = [row(), dict(url=OTHER, error='429 Too many requests')]
            out = await self.extract([URL, OTHER])
            self.assertEqual(out['results'][0]['content'], BODY)
            self.assertEqual(out['results'][1]['reason'], 'provider_error')
            self.assertEqual([c[0] for c in self.calls], ['exa'] if anonymous else ['primary', 'exa'])

    async def test_partial_primary_success_never_rescues(self):
        self.responses['primary'] = [row(), dict(url=OTHER, error='outage')]
        out = await self.extract([URL, OTHER])
        self.assertEqual(out['results'][0]['content'], BODY)
        self.assertEqual(len(self.calls), 1)

    async def test_policy_refusal_never_rescues(self):
        for anonymous in (True, False):
            self.anonymous = anonymous; self.calls.clear()
            refused = [dict(url=URL, error='Blocked by website policy', blocked_by_policy=True)]
            self.responses['primary'] = self.responses['exa'] = refused
            self.errors(await self.extract(), 'provider_error')
            self.assertEqual(len(self.calls), 1)
        self.calls.clear()
        self.errors(await self.extract(['https://blocked.unknown.example/a']), 'provider_error')
        self.assertEqual(self.calls, [])

    async def test_rescue_gate_and_empty_ring_are_respected(self):
        self.rescue = False; self.responses['primary'] = [dict(url=URL, error='outage')]
        self.errors(await self.extract(), 'provider_error'); self.assertEqual(len(self.calls), 1)
        self.anonymous = True; self.calls.clear()
        with patch.object(compat, 'ring_order', return_value=[]):
            self.errors(await self.extract(), 'provider_error')
        self.assertEqual(self.calls, [])

    async def test_one_absolute_deadline(self):
        self.responses['primary'] = [dict(url=URL, error='outage')]
        def expire():
            self.clock = 104.0
            return [dict(url=URL, error='429 Too many requests')]
        self.responses['parallel'] = expire
        self.errors(await self.extract(deadline=104.0), 'timeout')
        self.assertEqual([c[0] for c in self.calls], ['primary', 'exa', 'parallel'])
        self.assertEqual([c[2] for c in self.calls], [104.0, 104.0, 104.0])
        self.calls.clear()
        self.errors(await self.extract(deadline=104.0), 'timeout')
        self.assertEqual(self.calls, [])

    async def test_default_and_explicit_format_limit_bounds(self):
        for format in ('markdown', 'html'):
            for limit in (2000, 6000):
                out = await self.extract(format=format, char_limit=limit)
                self.assertEqual(out['results'][0]['content'], BODY)
                self.assertEqual(self.calls[-1][3], format)
        self.calls.clear()
        for kwargs in ({'format': 'text'}, {'format': 1}, {'format': False},
                       {'char_limit': True}, {'char_limit': 1999}, {'char_limit': 6001},
                       {'char_limit': 3000.0}, {'deadline': True}, {'deadline': float('nan')}):
            self.errors(await self.extract(**kwargs), 'invalid_request')
        for urls in ([], [URL] * 6, ['x' * 4097], 'not-a-list', [None]):
            self.errors(await self.extract(urls), 'invalid_request')
        self.assertEqual(self.calls, [])

    async def test_compat_reasons_mapped_not_passed_through(self):
        for incoming, want in [('invalid_url', 'invalid_request'), ('secret_url', 'unsafe_url'),
                               ('policy_blocked', 'provider_error'), ('invented', 'provider_error')]:
            with patch.object(compat, 'check_url', side_effect=compat.CompatibilityError(incoming)):
                self.errors(await self.extract(), want)
        self.assertEqual(self.calls, [])

    async def test_no_shared_cache(self):
        from tools import web_result_cache
        with patch.object(web_result_cache, 'extract_cache_get', side_effect=AssertionError('cache read forbidden')), \
             patch.object(web_result_cache, 'extract_cache_put', side_effect=AssertionError('cache write forbidden')), \
             patch('builtins.open', side_effect=AssertionError('spill forbidden')), \
             patch('pathlib.Path.write_text', side_effect=AssertionError('spill forbidden')):
            out = await self.extract()
        self.assertEqual(out['results'][0]['content'], BODY)

    async def test_no_provider_provenance_or_metadata_leaks(self):
        self.responses['primary'] = [row(location_provenance='uncached_dispatch',
            metadata={'secret': 'PRIVATE', 'published_at': '2026-10-17'},
            raw_content='PRIVATE', published_at='2026-10-17', last_modified='2026-10-17', crawl_timestamp='2026-10-17')]
        r = (await self.extract())['results'][0]
        self.assertEqual(set(r), {'url', 'title', 'content', 'error', 'extraction_location'})
        self.assertNotIn('PRIVATE', json.dumps(r))
        page = radar.validate_structured_page(URL, worker.project_row(r))
        self.assertIsNone(page['published_at'])

    async def test_provider_only_publication_stays_unverified_and_conflicts_fail(self):
        report = provider_publication(1791979200)
        self.responses['primary'] = [row(publication=report,
            extraction_location={'version': 1, 'requested_url': URL, 'returned_url': URL})]
        r = (await self.extract())['results'][0]
        self.assertEqual(r['publication'], report)
        page = radar.validate_structured_page(URL, worker.project_row(r))
        self.assertIsNone(page['published_at'])
        accepted, _ = radar.filter_evidence([page])
        self.assertEqual(accepted, [])
        self.responses['primary'][0]['content'] = 'Published: October 13, 2026\n' + BODY
        self.errors(await self.extract(), 'malformed_response')

    async def test_strict_declarations_checked_before_projection_and_truncation(self):
        for field, value in [('error', False), ('success', 0), ('status', None),
                             ('blocked_by_policy', 0), ('publication', {}), ('title', False)]:
            self.responses['primary'] = [row(**{field: value})]
            self.errors(await self.extract(), 'malformed_response')
        self.responses['primary'] = [row(error='PRIVATE failure', reason='unsafe_url')]
        self.errors(await self.extract(), 'provider_error')
        self.assertNotIn('PRIVATE', json.dumps(await self.extract()))

    async def test_oversized_envelope_rejected_before_projection(self):
        self.responses['primary'] = [row(metadata={'large': 'x' * 100001})]
        self.errors(await self.extract(), 'output_limit')
        self.assertEqual(len(self.calls), 1)

    async def test_base64_images_replaced_and_binary_error_bodies_rejected(self):
        self.responses['primary'] = [row(content=BODY + '\n![image](data:image/png;base64,' + 'A' * 10000 + ')')]
        content = (await self.extract())['results'][0]['content']
        self.assertIn('[image omitted]', content); self.assertNotIn('base64', content)
        for body in ('%PDF-1.7 binary', '\x89PNG\r\n\x1a\n', 'abc\x00def', '# Access denied\n' + BODY, b'bytes', 'A' * 10000):
            self.responses['primary'] = [row(content=body)]
            self.assertTrue((await self.extract())['results'][0]['error'])

    async def test_multiline_image_data_is_removed_as_one_bounded_placeholder(self):
        payload = ('A' * 80 + '\n') * 20
        for image in ('![figure](data:image/png;base64,' + payload + ')',
                      '<img src="data:image/png;base64,' + payload + '">'):
            self.responses['primary'] = [row(content=BODY + '\n' + image)]
            r = (await self.extract())['results'][0]
            self.assertIsNone(r['error'])
            self.assertIn('[image omitted]', r['content'])
            self.assertNotIn('A' * 80, r['content'])

    async def test_head_tail_footer_is_recognized_without_spill(self):
        self.responses['primary'] = [row(content='HEAD\n' + 'a ' * 3000 + '\nTAIL')]
        r = (await self.extract(char_limit=2000))['results'][0]
        self.assertLessEqual(len(r['content']), 2000)
        self.assertTrue(r['content'].startswith('HEAD'))
        self.assertIn('TAIL', strip_tool_footer(r['content']))
        self.assertIn('─── [TRUNCATED]', r['content'])
        self.assertNotIn('read_file', r['content'])
        self.assertEqual(worker.project_row(r)['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
