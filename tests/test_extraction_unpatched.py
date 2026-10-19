"""Offline safety and real isolated-runtime compatibility checks for the probe."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProbeTests(unittest.TestCase):
    def probe(self):
        path = ROOT / 'scripts/probe_project_extraction.py'
        self.assertTrue(path.is_file(), 'bounded network-only probe is missing')
        spec = importlib.util.spec_from_file_location('extraction_probe', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_duplicate_urls_rejected(self):
        probe = self.probe()
        with self.assertRaises(ValueError):
            probe.validate_cohort(['https://example.com/a'] * 2)
        for value in ([], ['file:///private'], ['https://example.com'] * 13):
            with self.assertRaises(ValueError):
                probe.validate_cohort(value)

    def test_probe_never_calls_trading(self):
        import alpha_radar
        import autotrader
        from unittest.mock import patch
        probe = self.probe()
        body = 'Company revenue increased following the announced transaction. ' * 20
        result = {'version': 1, 'status': 'ok', 'page': {
            'url': 'https://example.com/a', 'title': 'Release', 'text': body,
        }}
        with patch.object(alpha_radar, 'record_source_verification_diagnostic', side_effect=AssertionError('journal')), \
             patch.object(autotrader, 'journal_confirmed_fill', side_effect=AssertionError('execution')), \
             patch.object(autotrader, 'reconcile_pending_orders', side_effect=AssertionError('orders')):
            report = probe.run_probe(['https://example.com/a'], 'worker',
                                     runner=lambda *args: (result, {'attempts': [], 'module_paths': {}}))
        self.assertEqual(report['accepted'] + report['rejected'], 1)
        self.assertEqual(report['rows'][0]['reason'], 'source_freshness_unknown')
        self.assertGreaterEqual(report['rows'][0]['elapsed_seconds'], 0)
        self.assertIn('attempts', report['rows'][0])

    def test_unobserved_success_does_not_claim_zero_network_requests(self):
        probe = self.probe()
        result = {'version': 1, 'status': 'ok', 'page': {
            'url': 'https://example.com/a', 'title': 'Release', 'text': 'Company release. ' * 100}}
        report = probe.run_probe(['https://example.com/a'], 'worker',
            runner=lambda *args: (result, {'attempts': [], 'baseline': True}))
        self.assertIsNone(report['request_count'])
        self.assertFalse(report['rows'][0]['request_count_complete'])

    def test_private_output_boundary(self):
        probe = self.probe()
        with self.assertRaises(ValueError):
            probe.write_private(ROOT / 'outside-probe.json', {})
        import tempfile
        with tempfile.TemporaryDirectory(dir=probe.ARTIFACTS) as directory:
            target = Path(directory) / 'detail.json'
            probe.write_private(target, {'private': True})
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_transport_accounting_counts_real_starts_once_across_threads(self):
        import asyncio
        import http.client
        from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
        import sys
        import threading
        import requests
        import httpx
        probe = self.probe()
        received, starts = [], []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(self.path)
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'ok')
            def log_message(self, format, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}/'
        def profile(frame, event, arg):
            if probe.transport_start(frame, event):
                starts.append(frame.f_globals['__name__'])
        async def async_request():
            async with httpx.AsyncClient(trust_env=False) as client:
                await client.get(url)
        try:
            sys.setprofile(profile)
            threading.setprofile(profile)
            requests.get(url, timeout=2)
            worker = threading.Thread(target=lambda: requests.get(url, timeout=2))
            worker.start(); worker.join(3)
            with httpx.Client(trust_env=False) as client:
                client.get(url)
            asyncio.run(async_request())
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
            conn.request('GET', '/')
            conn.getresponse().read(); conn.close()
        finally:
            sys.setprofile(None)
            threading.setprofile(None)
            server.shutdown(); server.server_close(); thread.join(3)
        self.assertEqual(len(received), 5)
        self.assertEqual(starts.count('requests.sessions'), 2)
        self.assertEqual(starts.count('httpx._client'), 2)
        self.assertEqual(starts.count('http.client'), 1)
        self.assertEqual(len(starts), len(received))

    def test_fresh_worker_registers_real_plugins_before_lookup(self):
        import json
        import os
        import subprocess
        import tempfile
        from runtime_paths import hermes_runtime
        python, source = hermes_runtime()
        code = r'''
import sys, os, json, asyncio, socket
from pathlib import Path
source, project = map(Path, sys.argv[1:3])
sys.path.insert(0, str(source))
import hermes_bootstrap
sys.path.insert(0, str(project))
import extraction_worker
from agent import web_search_registry as registry
assert registry.get_provider('firecrawl') is None, 'startup preloaded registry'
import httpx
from unittest.mock import patch
url = 'https://example.com/release'
def post(endpoint, **kwargs):
    return httpx.Response(200, request=httpx.Request('POST', endpoint), json={
        'success': True, 'data': {'markdown': 'Company revenue increased. ' * 80,
        'metadata': {'title': 'Release', 'sourceURL': url}}})
import requests
def send(self, request, **kwargs):
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps({'success': True, 'data': {
        'markdown': 'Company revenue increased. ' * 80,
        'metadata': {'title': 'Release', 'sourceURL': url}}}).encode()
    response.request = request
    return response
with patch('socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]), patch('httpx.post', side_effect=post) as httpx_network, patch('requests.sessions.Session.send', autospec=True, side_effect=send) as network, patch('socket.socket.connect', side_effect=AssertionError('unfaked network')):
    result = asyncio.run(extraction_worker.extract({'version': 1, 'url': url}))
assert result['status'] == 'ok', result
assert network.call_count == 1, network.call_count
provider = registry.get_provider('firecrawl')
assert provider.__class__.__module__ == 'plugins.web.firecrawl.provider'
for name in ('agent.web_search_registry', 'tools.web_tools', 'plugins.web.firecrawl.provider'):
    assert Path(sys.modules[name].__file__).resolve().is_relative_to(source)
assert not (source / 'tools/web_publication.py').exists()
print(json.dumps({'status': result['status'], 'requests': network.call_count}))
'''
        with tempfile.TemporaryDirectory(dir=self.probe().ARTIFACTS) as home:
            Path(home, 'config.yaml').write_text('web:\n  extract_backend: firecrawl\n  keyless_fallback: false\n')
            env = {**os.environ, 'HERMES_HOME': home,
                   'FIRECRAWL_API_URL': 'https://fixture.example', 'FIRECRAWL_API_KEY': ''}
            completed = subprocess.run([python, '-I', '-c', code, str(source), str(ROOT)],
                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {'status': 'ok', 'requests': 1})

    def test_imports_from_selected_unpatched_root(self):
        import os
        import runtime_paths
        probe = self.probe()
        source = Path(os.environ.get('TRADEY_UNPATCHED_ROOT',
            '/home/hermes/.hermes/cache/scratch/project-extraction-unpatched'))
        self.assertTrue(source.is_dir(), 'explicit unpatched checkout required')
        with __import__('unittest.mock', fromlist=['patch']).patch.dict(os.environ, {'HERMES_SOURCE_ROOT': str(source)}):
            python, selected = runtime_paths.hermes_runtime()
            self.assertEqual(selected.resolve(), source.resolve())
            for mode in ('worker', 'focused'):
                with self.subTest(mode=mode):
                    result, detail = probe.run_source('http://127.0.0.1/probe', mode)
                    self.assertEqual(result['status'], 'error')
                    self.assertEqual(detail['source_sha'], 'd923a5eb487a17c0a68801bba9ef0f56c81040a8')
                    self.assertFalse(detail['patched_publication_module'])
                    self.assertEqual(detail['cache_calls'], 0)
                    self.assertTrue(detail['module_paths'])
                    for path in detail['module_paths'].values():
                        self.assertTrue(Path(path).is_relative_to(source))
                    self.assertEqual(detail['entrypoint'], mode)


if __name__ == '__main__':
    unittest.main()
