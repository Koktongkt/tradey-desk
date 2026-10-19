"""Offline compatibility contracts; doubles replace config/network boundaries only."""
import asyncio
import ast
import builtins
import importlib
import importlib.util
import time
import types
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch


def source_definitions(path, names, **state):
    """Execute installed definitions in private globals, not live module state."""
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    if {node.name for node in selected} != set(names):
        raise AssertionError(f'missing compatibility definitions in {path}')
    namespace = {'__name__': 'offline_characterization', **state}
    code = 'from __future__ import annotations\n' + '\n'.join(ast.unparse(node) for node in selected)
    exec(compile(code, str(path), 'exec'), namespace)
    return types.SimpleNamespace(**namespace)


# Use deployed runtime source, not the generated environment workspace.
RUNTIME_SOURCE = Path.home() / '.hermes/hermes-agent'
BASELINE_SOURCE = Path.home() / '.hermes/cache/scratch/project-extraction-unpatched'
# The review baseline is optional after the task's scratch snapshot is pruned.
FIRECRAWL_SOURCES = [RUNTIME_SOURCE] + ([BASELINE_SOURCE] if BASELINE_SOURCE.is_dir() else [])


class CompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('extraction_compat'), 'compatibility interface is not implemented')
        self.c = importlib.import_module('extraction_compat')
        self.config = {'web': {}}
        self.calls = []
        self.providers = {}
        self.active = None
        self.modules: dict[str, Any] = {
            'tools.web_tools': types.SimpleNamespace(_ensure_web_plugins_loaded=lambda: None),
            'hermes_cli.config': types.SimpleNamespace(load_config=lambda: self.config),
            'agent.web_search_registry': types.SimpleNamespace(
                get_provider=lambda name: self.providers.get(name),
                get_active_extract_provider=lambda: self.active),
            'agent.web_search_provider': types.SimpleNamespace(get_provider_env=lambda name: 'key'),
            'agent.redact': types.SimpleNamespace(_PREFIX_RE=__import__('re').compile(r'sk-secret')),
            'tools.url_safety': types.SimpleNamespace(
                normalize_url_for_request=lambda u: u.strip().replace('ö', '%C3%B6'),
                sensitive_query_param_name=importlib.import_module('tools.url_safety').sensitive_query_param_name,
                is_safe_url=lambda u: '127.0.0.1' not in u),
        }
        # Actual stateless policy helpers, never the shared policy cache.
        policy = importlib.import_module('tools.website_policy')
        self.modules['tools.website_policy'] = policy
        self.modules['plugins.web.keyless_mcp'] = types.SimpleNamespace(
            use_keyless=lambda name, key: self.config['web'].get('provider_tier', {}).get(name) == 'free' or not key,
            _ring_order=lambda name: ['exa', 'parallel', 'firecrawl', 'keenable'],
            _is_rate_limitish=lambda error: any(x in error.lower() for x in ['429', 'rate limit', 'quota exceeded']))
        for vendor in ['exa', 'parallel', 'firecrawl']:
            def extract(urls, vendor=vendor):
                self.calls.append((vendor, urls))
                return [{'url': u, 'content': vendor, 'metadata': {'published_at': 'unverified'}} for u in urls]
            setattr(self.modules['plugins.web.keyless_mcp'], vendor + '_extract_keyless', extract)
        self.modules['plugins.web.firecrawl.provider'] = types.SimpleNamespace(
            _use_keyless_ring=lambda capability: capability != 'extract',
            is_managed_route=lambda capability: False,
            _get_direct_firecrawl_config=lambda: ('sdk', {'api_key': 'key'}, ('direct', None, 'key')))
        self.modules['keenable_extraction'] = types.SimpleNamespace(fetch=self.fetch)
        self.patcher = patch.object(self.c, '_module', side_effect=lambda name: self.modules[name])
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def fetch(self, url, *, deadline):
        self.calls.append(('keenable', url, deadline))
        return {'url': url, 'content': 'keenable', 'publication': {'verified': False}}

    def provider(self, name, *, asynchronous=False, custom=False):
        def extract(urls, *, format):
            self.calls.append((name, urls, format))
            return [{'url': u, 'content': name} for u in urls]
        async def async_extract(urls, *, format):
            return extract(urls, format=format)
        method = async_extract if asynchronous else extract
        method.__module__ = 'custom_backend' if custom else f'plugins.web.{name}.provider'
        return types.SimpleNamespace(name=name, supports_extract=lambda: True, extract=method)

    async def test_explicit_invalid_or_search_only_never_autodetects(self):
        self.active = self.provider('exa')
        for value in ['missing', 'search-only']:
            self.config['web']['extract_backend'] = value
            self.providers['search-only'] = types.SimpleNamespace(supports_extract=lambda: False)
            with self.assertRaises(self.c.CompatibilityError) as caught:
                self.c.resolve()
            self.assertEqual(caught.exception.reason, 'provider_error')
        self.assertEqual(self.calls, [])

    async def test_registration_failure_never_looks_up_or_falls_back(self):
        self.config['web']['extract_backend'] = 'firecrawl'
        self.providers['firecrawl'] = self.provider('firecrawl')
        def broken():
            raise RuntimeError('private startup error')
        self.modules['tools.web_tools']._ensure_web_plugins_loaded = broken
        with patch.object(self.modules['agent.web_search_registry'], 'get_provider') as lookup:
            with self.assertRaises(self.c.CompatibilityError) as caught:
                self.c.resolve()
            self.assertEqual(caught.exception.reason, 'provider_error')
            lookup.assert_not_called()

    async def test_resolution_preserves_selected_direct_provider_and_managed_alias(self):
        provider = self.provider('firecrawl')
        self.providers['firecrawl'] = provider
        self.config['web']['extract_backend'] = 'nous'
        self.assertIs(self.c.resolve(), provider)
        self.config['web']['extract_backend'] = 'firecrawl'
        self.assertIs(self.c.resolve(), provider)

    async def test_safety_refusals_make_no_vendor_calls(self):
        for url in ['https://example.org/sk-secret', 'http://127.0.0.1/a']:
            with self.assertRaises(self.c.CompatibilityError):
                await self.c.keyless('exa', [url], deadline=time.monotonic() + 1)
        self.assertEqual(self.calls, [])

    async def test_policy_failure_and_block_are_not_permission(self):
        for policy in [{'enabled': 'broken'}, {'domains': ['example.org']}]:
            self.config['security'] = {'website_blocklist': policy}
            with self.assertRaises(self.c.CompatibilityError) as caught:
                await self.c.keyless('exa', ['https://example.org/a'], deadline=time.monotonic() + 1)
            self.assertEqual(caught.exception.reason, 'policy_blocked')
        self.assertEqual(self.calls, [])

    async def test_failed_config_snapshots_never_authorize_settings(self):
        # Removing the read_error admission check would authorize defaults/LKG.
        marker = source_definitions(RUNTIME_SOURCE / 'hermes_cli/config_read_errors.py', ['FailedConfigRead']).FailedConfigRead
        for error in [ValueError('malformed YAML'), PermissionError('unreadable config')]:
            for fallback in [{}, {'web': {'extract_backend': 'exa'}, 'security': {'website_blocklist': {'enabled': False}}}]:
                with self.subTest(error=type(error).__name__, fallback=fallback):
                    self.config = marker(fallback, error=error)
                    self.active = self.providers['exa'] = self.provider('exa')
                    for action in [self.c.resolve, lambda: self.c.ring_order('exa'),
                                   lambda: self.c.uses_keyless(self.provider('exa'))]:
                        with self.subTest(action=action):
                            with self.assertRaises(self.c.CompatibilityError) as caught:
                                action()
                            self.assertEqual(caught.exception.reason, 'provider_error')
                    with self.subTest(action='rescue'):
                        self.assertFalse(self.c.rescue_allowed(self.provider('exa')))
                    for action in [lambda: self.c.check_url('https://example.org'),
                                   lambda: self.c.primary(self.provider('exa'), ['https://example.org'], format='markdown', deadline=time.monotonic() + 1),
                                   lambda: self.c.keyless('exa', ['https://example.org'], deadline=time.monotonic() + 1)]:
                        with self.subTest(action=action):
                            with self.assertRaises(self.c.CompatibilityError) as caught:
                                await action()
                            self.assertEqual(caught.exception.reason, 'provider_error')
        self.assertEqual(self.calls, [])

    async def test_falsey_malformed_policy_mapping_is_not_empty_policy(self):
        # `value or {}` must not turn explicit malformed settings into permission.
        for value in [False, None, 0, '', []]:
            with self.subTest(value=value):
                self.config['security'] = {'website_blocklist': value}
                with self.assertRaises(self.c.CompatibilityError) as caught:
                    await self.c.keyless('exa', ['https://example.org'], deadline=time.monotonic() + 1)
                self.assertEqual(caught.exception.reason, 'policy_blocked')
        self.assertEqual(self.calls, [])

    def firecrawl_runtime(self, root, *, key='', api_url='', selected='firecrawl', explicit=True, gateway=False):
        helpers = types.SimpleNamespace(
            NOUS_MANAGED_PROVIDER='nous', read_web_capability_selection=lambda capability: selected,
            selection_error=lambda *args: 'unavailable')
        keyless = source_definitions(root / 'plugins/web/keyless_mcp.py', ['use_keyless'],
            provider_tier=lambda name: self.config['web'].get('provider_tier', {}).get(name, 'auto'),
            keyless_enabled=lambda: self.config['web'].get('keyless_fallback', True))
        def importer(name, *args, **kwargs):
            return {'tools.tool_backend_helpers': helpers, 'plugins.web.keyless_mcp': keyless}.get(name) or builtins.__import__(name, *args, **kwargs)
        def post(url, **kwargs):
            self.calls.append(('anonymous', url, kwargs))
            return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'content': 'anonymous'})
        def sdk(**kwargs):
            def scrape(**payload):
                self.calls.append(('sdk', kwargs, payload))
                return {'content': 'sdk'}
            return types.SimpleNamespace(scrape=scrape)
        source = source_definitions(root / 'plugins/web/firecrawl/provider.py',
            ['_use_keyless_ring', '_get_direct_firecrawl_config', 'is_managed_route', '_get_firecrawl_client', '_KeylessFirecrawlClient'],
            _env=lambda name: key if name == 'FIRECRAWL_API_KEY' else api_url,
            _is_explicit_firecrawl_selection=lambda: explicit,
            _is_tool_gateway_ready=lambda: gateway,
            _FIRECRAWL_CLOUD_API_URL='https://api.firecrawl.dev',
            __builtins__={**vars(builtins), '__import__': importer},
            _wt=lambda: cache, Firecrawl=sdk, httpx=types.SimpleNamespace(post=post),
            _gateway=types.SimpleNamespace(
                read_nous_access_token=lambda: 'controlled-token',
                resolve_managed_tool_gateway=lambda *args, **kwargs: types.SimpleNamespace(
                    nous_user_token='controlled-token', gateway_origin='https://managed.example')))
        cache = types.SimpleNamespace()
        self.modules['plugins.web.firecrawl.provider'] = source
        provider = self.provider('firecrawl')
        def extract(urls, *, format):
            client = source._get_firecrawl_client('extract')
            return [client.scrape(url=url, formats=[format]) for url in urls]
        extract.__module__ = 'plugins.web.firecrawl.provider'
        provider.extract = extract
        return source, provider

    async def test_firecrawl_anonymous_primary_optout_or_paid_never_calls(self):
        # Actual predicate says no ring, but actual client would still free-call.
        for root in FIRECRAWL_SOURCES:
            for web in [{'keyless_fallback': False}, {'provider_tier': {'firecrawl': 'paid'}}]:
                with self.subTest(root=str(root), web=web):
                    self.config['web'] = {'extract_backend': 'firecrawl', **web}
                    source, provider = self.firecrawl_runtime(root)
                    self.assertFalse(source._use_keyless_ring('extract'))
                    self.assertEqual(source._get_direct_firecrawl_config()[0], 'keyless')
                    with self.assertRaises(self.c.CompatibilityError) as caught:
                        await self.c.primary(provider, ['https://example.org'], format='markdown', deadline=time.monotonic() + 1)
                    self.assertEqual(caught.exception.reason, 'provider_error')
        self.assertEqual(self.calls, [])

    async def test_firecrawl_keyed_selfhosted_and_configured_managed_primary_preserved(self):
        for root in FIRECRAWL_SOURCES:
            for settings in [dict(key='controlled-key'), dict(api_url='https://selfhosted.example'),
                             dict(selected='nous', explicit=True, gateway=True)]:
                with self.subTest(root=str(root), settings=settings):
                    self.config['web'] = {'keyless_fallback': False, 'provider_tier': {'firecrawl': 'paid'}}
                    source, provider = self.firecrawl_runtime(root, **settings)
                    self.assertFalse(source._use_keyless_ring('extract'))
                    self.assertFalse(self.c.uses_keyless(provider))
                    rows = await self.c.primary(provider, ['https://example.org'], format='html', deadline=time.monotonic() + 1)
                    self.assertEqual(rows, [{'content': 'sdk'}])
                    self.assertEqual(self.calls[-1][0], 'sdk')
        self.assertEqual(len(self.calls), 3 * len(FIRECRAWL_SOURCES))

    async def test_normalization_keeps_identity_outside_transport(self):
        original = ' https://example.org/Köln '
        transport = await self.c.check_url(original)
        self.assertEqual(transport, 'https://example.org/K%C3%B6ln')
        self.assertEqual(original, ' https://example.org/Köln ')
        rows = await self.c.keyless('exa', [original], deadline=time.monotonic() + 1)
        self.assertEqual(rows[0]['url'], transport)
        self.assertEqual(rows[0]['metadata'], {'published_at': 'unverified'})

    async def test_keyless_optout_and_paid_exclusion_zero_calls(self):
        for config in [{'keyless_fallback': False}, {'provider_tier': {v: 'paid' for v in ['exa', 'parallel', 'firecrawl', 'keenable']}}]:
            self.config['web'] = config
            self.assertEqual(self.c.ring_order('exa'), [])
            self.assertFalse(self.c.rescue_allowed(self.provider('exa')))
            with self.assertRaises(self.c.CompatibilityError):
                await self.c.keyless('exa', ['https://example.org'], deadline=time.monotonic() + 1)
        self.assertEqual(self.calls, [])

    async def test_direct_keyed_matrix_sync_and_async(self):
        for vendor in ['exa', 'parallel', 'keenable', 'firecrawl']:
            provider = self.provider(vendor, asynchronous=vendor in ['parallel', 'firecrawl'])
            self.assertFalse(self.c.uses_keyless(provider))
            rows = await self.c.primary(provider, ['https://example.org'], format='html', deadline=time.monotonic() + 1)
            self.assertEqual(rows[0]['content'], vendor)
            self.assertEqual(self.calls[-1], (vendor, ['https://example.org'], 'html'))
            self.assertTrue(self.c.rescue_allowed(provider))

    async def test_raw_transport_exceptions_are_normalized_at_invocation(self):
        provider = self.provider('tavily')
        for mode in ('sync', 'async', 'sync_awaitable'):
            for error_type in (OSError, RuntimeError):
                with self.subTest(mode=mode, error=error_type.__name__):
                    def fail(urls, *, format):
                        raise error_type('PRIVATE transport details')
                    async def async_fail(urls, *, format):
                        await asyncio.sleep(0)
                        fail(urls, format=format)
                    def awaitable(urls, *, format):
                        return async_fail(urls, format=format)
                    provider.extract = {'sync': fail, 'async': async_fail,
                                        'sync_awaitable': awaitable}[mode]
                    provider.uses_keyless = lambda: False
                    with self.assertRaises(Exception) as caught:
                        await self.c.primary(provider, ['https://example.org'],
                                             format='markdown', deadline=time.monotonic() + 1)
                    self.assertIsInstance(caught.exception, self.c.CompatibilityError)
                    self.assertEqual(getattr(caught.exception, 'reason', None), 'provider_error')
                    self.assertNotIn('PRIVATE', str(caught.exception))

    async def test_invocation_preserves_typed_failures_timeout_and_cancellation(self):
        provider = self.provider('custom', custom=True)
        provider.uses_keyless = lambda: False
        for error in (self.c.CompatibilityError('malformed_response'),
                      self.c.CompatibilityError('policy_blocked'),
                      self.c.CompatibilityError('unsafe_url'), TimeoutError(),
                      asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__, reason=str(error)):
                async def fail(urls, *, format):
                    raise error
                provider.extract = fail
                with self.assertRaises(type(error)) as caught:
                    await self.c.primary(provider, ['https://example.org'],
                                         format='markdown', deadline=time.monotonic() + 1)
                self.assertIs(caught.exception, error)

    async def test_malformed_transport_containers_are_postvalidation_not_transport_failure(self):
        provider = self.provider('exa')
        for malformed in ({'results': []}, [None], [{'url': 'https://example.org'}, 'bad']):
            with self.subTest(malformed=malformed):
                async def invoke(*args, **kwargs):
                    return malformed
                with patch.object(self.c, '_invoke', side_effect=invoke):
                    with self.assertRaises(self.c.CompatibilityError) as caught:
                        await self.c.primary(provider, ['https://example.org'],
                                             format='markdown', deadline=time.monotonic() + 1)
                self.assertEqual(caught.exception.reason, 'malformed_response')
        self.assertEqual(self.calls, [])

    async def test_free_matrix_never_calls_opaque_provider(self):
        deadline = time.monotonic() + 1
        for vendor in ['exa', 'parallel', 'firecrawl', 'keenable']:
            rows = await self.c.keyless(vendor, ['https://example.org'], deadline=deadline)
            self.assertEqual(rows[0]['content'], vendor)
        self.assertEqual(self.calls[-1], ('keenable', 'https://example.org', deadline))
        self.config['web']['provider_tier'] = {'exa': 'free'}
        with self.assertRaises(self.c.CompatibilityError):
            await self.c.primary(self.provider('exa'), ['https://example.org'], format='markdown', deadline=deadline)
        self.assertEqual(len(self.calls), 4)

    async def test_unknown_custom_ring_relationship_fails_closed(self):
        provider = self.provider('custom', custom=True)
        with self.assertRaises(self.c.CompatibilityError):
            self.c.uses_keyless(provider)
        self.assertFalse(self.c.rescue_allowed(provider))
        with self.assertRaises(self.c.CompatibilityError):
            await self.c.primary(provider, ['https://example.org'], format='markdown', deadline=time.monotonic() + 1)
        provider.uses_keyless = lambda: False
        rows = await self.c.primary(provider, ['https://example.org'], format='markdown', deadline=time.monotonic() + 1)
        self.assertEqual(rows[0]['content'], 'custom')

    async def test_missing_or_wrong_signature_helpers_fail_closed(self):
        self.modules['tools.url_safety'].is_safe_url = lambda: True
        with self.assertRaises(self.c.CompatibilityError) as caught:
            await self.c.check_url('https://example.org')
        self.assertEqual(caught.exception.reason, 'provider_error')
        self.modules['plugins.web.firecrawl.provider']._use_keyless_ring = lambda: False
        with self.assertRaises(self.c.CompatibilityError):
            self.c.uses_keyless(self.provider('firecrawl'))
        self.assertEqual(self.calls, [])

    async def test_missing_policy_api_is_provider_error_not_policy_permission(self):
        self.modules['tools.website_policy'] = types.SimpleNamespace()
        with self.assertRaises(self.c.CompatibilityError) as caught:
            await self.c.check_url('https://example.org')
        self.assertEqual(caught.exception.reason, 'provider_error')

    async def test_rate_limit_only_whole_batch_and_never_policy(self):
        for rows, expected in [([], False), ([{'error': '429'}], True), ([{'error': 'rate limit'}, {'error': 'quota exceeded'}], True), ([{'error': '403 forbidden'}], False), ([{'error': '429'}, {'content': 'ok'}], False), ([{'error': '429', 'blocked_by_policy': True}], False), ([{'error': 'Blocked by website policy: 429'}], False)]:
            self.assertEqual(self.c.rate_limited(rows), expected)

    async def test_malformed_ring_helper_return_is_typed_compatibility_failure(self):
        self.modules['plugins.web.keyless_mcp']._ring_order = lambda name: [[]]
        with self.assertRaises(Exception) as caught:
            self.c.ring_order('exa')
        self.assertIsInstance(caught.exception, self.c.CompatibilityError)
        self.assertEqual(getattr(caught.exception, 'reason', None), 'provider_error')

    async def test_installed_ring_pinning_paid_exclusion_and_cursor(self):
        # Clone the installed function with isolated state, never mutate its globals.
        import threading
        original = importlib.import_module('plugins.web.keyless_mcp')._ring_order
        state = dict(original.__globals__)
        state.update(_ring_cursor=0, _ring_lock=threading.Lock(),
                     _vendor_pinned=lambda name: self.config['web'].get('provider_tier', {}).get(name) == 'free',
                     provider_tier=lambda name: self.config['web'].get('provider_tier', {}).get(name, 'auto'))
        ring = types.FunctionType(original.__code__, state)
        self.modules['plugins.web.keyless_mcp']._ring_order = ring
        self.assertEqual(self.c.ring_order('exa'), ['exa', 'parallel', 'firecrawl', 'keenable'])
        self.assertEqual(self.c.ring_order('exa'), ['parallel', 'firecrawl', 'keenable', 'exa'])
        self.config['web']['provider_tier'] = {'firecrawl': 'free', 'parallel': 'paid'}
        self.assertEqual(self.c.ring_order('firecrawl'), ['firecrawl', 'keenable', 'exa'])
        self.assertEqual(self.c.ring_order('firecrawl'), ['firecrawl', 'keenable', 'exa'])
        self.assertEqual(state['_ring_cursor'], 2)

    async def test_installed_firecrawl_extract_predicate_managed_and_selfhosted(self):
        import builtins
        original = importlib.import_module('plugins.web.firecrawl.provider')._use_keyless_ring
        for key, api_url, selected, gateway, explicit, expected in [
            ('key', '', None, False, True, False),
            ('', 'https://selfhosted.example', None, False, True, False),
            ('', '', 'nous', False, True, False),
            ('', '', None, True, False, False),
            ('', '', None, True, True, True),
            ('', '', None, False, False, True),
        ]:
            helpers = types.SimpleNamespace(NOUS_MANAGED_PROVIDER='nous', read_web_capability_selection=lambda capability: selected if capability == 'extract' else None)
            keyless = types.SimpleNamespace(use_keyless=lambda name, key: True)
            def importer(name, *args, **kwargs):
                return {'tools.tool_backend_helpers': helpers, 'plugins.web.keyless_mcp': keyless}.get(name) or builtins.__import__(name, *args, **kwargs)
            state = dict(original.__globals__)
            state.update(_env=lambda name: key if name == 'FIRECRAWL_API_KEY' else api_url,
                         _is_tool_gateway_ready=lambda: gateway,
                         _is_explicit_firecrawl_selection=lambda: explicit,
                         __builtins__={**vars(builtins), '__import__': importer})
            predicate = types.FunctionType(original.__code__, state, argdefs=original.__defaults__)
            self.modules['plugins.web.firecrawl.provider']._use_keyless_ring = predicate
            self.assertEqual(self.c.uses_keyless(self.provider('firecrawl')), expected)
        self.assertEqual(self.calls, [])

    async def test_same_deadline_across_multiple_keenable_urls(self):
        def slow_fetch(url, *, deadline):
            result = self.fetch(url, deadline=deadline)
            time.sleep(0.03)
            return result
        self.modules['keenable_extraction'].fetch = slow_fetch
        deadline = time.monotonic() + 0.05
        with self.assertRaises(TimeoutError):
            await self.c.keyless('keenable', ['https://example.org/a', 'https://example.org/b'], deadline=deadline)
        self.assertTrue(self.calls)
        self.assertTrue(all(call[2] == deadline for call in self.calls))

    async def test_same_deadline_bounds_async_and_sync_primary_awaits(self):
        for asynchronous in [False, True]:
            provider = self.provider('custom', custom=True)
            provider.uses_keyless = lambda: False
            def sync_extract(urls, *, format):
                time.sleep(0.03)
                return [{'content': 'late'}]
            async def async_extract(urls, *, format):
                await asyncio.sleep(0.03)
                return [{'content': 'late'}]
            provider.extract = async_extract if asynchronous else sync_extract
            with self.assertRaises(TimeoutError):
                await self.c.primary(provider, ['https://example.org'], format='markdown', deadline=time.monotonic() + 0.01)

    async def test_expired_deadline_starts_no_transport(self):
        with self.assertRaises(TimeoutError):
            await self.c.keyless('keenable', ['https://example.org'], deadline=time.monotonic() - 1)
        with self.assertRaises(TimeoutError):
            await self.c.primary(self.provider('exa'), ['https://example.org'], format='markdown', deadline=time.monotonic() - 1)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
