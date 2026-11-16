"""Offline safety and real isolated-runtime compatibility checks for the probe."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProbeTests(unittest.TestCase):
    def test_url_safety_update_check_reports_contract_results_without_urls(self):
        import json
        path = ROOT / 'scripts/check_url_safety_compatibility.py'
        self.assertTrue(path.is_file(), 'application-owned post-update check missing')
        spec = importlib.util.spec_from_file_location('url_safety_check', path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        def worker(urls, timeout_seconds):
            self.assertEqual(timeout_seconds, 20)
            return {'version': 2, 'status': 'ok', 'results': [
                {'requested_url': url, 'eligible': index < 2,
                 'reason': 'success' if index < 2 else 'unsafe_url'}
                for index, url in enumerate(urls)]}
        report = module.check(runner=worker)
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['checks']), 5)
        self.assertNotIn('https://', json.dumps(report))
        self.assertNotIn('http://', json.dumps(report))
        def broken(urls, timeout_seconds):
            return {'version': 2, 'status': 'error', 'reason': 'worker_exit'}
        self.assertFalse(module.check(runner=broken)['passed'])

    def test_url_safety_scheduled_mode_is_silent_on_pass_and_one_line_on_failure(self):
        import contextlib, io
        path = ROOT / 'scripts/check_url_safety_compatibility.py'
        spec = importlib.util.spec_from_file_location('url_safety_check_scheduled', path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        def healthy(urls, timeout_seconds):
            return {'version': 2, 'status': 'ok', 'results': [
                {'requested_url': url, 'eligible': index < 2,
                 'reason': 'success' if index < 2 else 'unsafe_url'}
                for index, url in enumerate(urls)]}
        def drifted(urls, timeout_seconds):
            # Friday 2026-11-13 signature: every URL refused with provider_error.
            return {'version': 2, 'status': 'ok', 'results': [
                {'requested_url': url, 'eligible': False, 'reason': 'provider_error'} for url in urls]}
        def broken(urls, timeout_seconds):
            return {'version': 2, 'status': 'error', 'reason': 'worker_exit'}
        cases = ((healthy, 0, ''),
                 (drifted, 3, 'SYSTEM_FAILURE url_safety_compatibility_failed sec_public,issuer_public,'
                              'credential_query,encoded_credential,private_address\n'),
                 (broken, 3, 'SYSTEM_FAILURE url_safety_compatibility_failed validation_worker_failed\n'))
        for runner, code, text in cases:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(module.main(['--scheduled'], runner=runner), code)
            self.assertEqual(out.getvalue(), text)
            self.assertNotIn('://', out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(module.main([], runner=healthy), 0)
        self.assertTrue(__import__('json').loads(out.getvalue())['passed'])

    def probe(self):
        path = ROOT / 'scripts/probe_project_extraction.py'
        self.assertTrue(path.is_file(), 'bounded network-only probe is missing')
        spec = importlib.util.spec_from_file_location('extraction_probe', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_real_supervisors_require_final_file_and_normal_exit(self):
        # Replace only the child launch command: real PIDs, pipes, deadlines and
        # group cleanup remain owned by the actual worker/focused supervisors.
        import json
        import sys
        import subprocess
        from unittest.mock import patch
        import structured_extraction as worker
        import focused_capture as capture
        probe = self.probe()
        original_popen = subprocess.Popen
        cases = [('partial', False), ('abnormal', True), ('missing', None),
                 ('invalid', None), ('normal', True), ('timeout', False)]
        for mode in ('worker', 'focused'):
            for case, finalized in cases:
                with self.subTest(mode=mode, case=case):
                    def launch(command, *args, **kwargs):
                        telemetry = command[-3]
                        detail = {'attempts': [{'transport': 'offline'}],
                                  'telemetry_version': 3, 'finalized': finalized,
                                  'supervisor_completed': True}  # untrusted child claim
                        code = 'import pathlib,sys,time; sys.stdin.read(); '
                        if case == 'invalid':
                            code += f'pathlib.Path({telemetry!r}).write_text("{{"); '
                        elif case != 'missing':
                            code += f'pathlib.Path({telemetry!r}).write_text({json.dumps(detail)!r}); '
                        code += 'print(\'{"version":1,"status":"error","reason":"provider_error"}\', flush=True); '
                        if case == 'abnormal':
                            code += 'sys.exit(7)'
                        elif case == 'timeout':
                            code += 'time.sleep(10)'
                        return original_popen([sys.executable, '-I', '-c', code], *args, **kwargs)
                    real_worker, real_focused = worker.run_worker, capture.run_focused
                    def bounded_worker(url, timeout):
                        return real_worker(url, 0.5)
                    def bounded_focused(command, **kwargs):
                        return real_focused(command, **{**kwargs, 'timeout': 0.5})
                    with patch('subprocess.Popen', side_effect=launch), \
                         patch.object(worker, 'run_worker', side_effect=bounded_worker), \
                         patch.object(capture, 'run_focused', side_effect=bounded_focused):
                        report = probe.run_probe(['https://example.com/a'], mode)
                    row = report['rows'][0]
                    self.assertEqual(row['request_count_complete'], case == 'normal')
                    self.assertEqual(row['supervisor_completed'], case not in ('abnormal', 'timeout'))
                    self.assertEqual(report['request_count'], 1 if case == 'normal' else None)
                    self.assertEqual(len(row['attempts']), 0 if case in ('missing', 'invalid') else 1)
                    if case == 'timeout':
                        self.assertEqual(row['transport_status'], 'error')

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
# Bootstrap dependencies under the owning default home, then switch routing
# to the disposable test home, exactly as guarded production-worker probes do.
# The launcher pin does not override an explicit private HERMES_HOME.
os.environ.pop('HERMES_HOME', None)
sys._hermes_pin_default_home = True
import hermes_bootstrap
os.environ['HERMES_HOME'] = sys.argv[3]
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
                   'FIRECRAWL_API_URL': 'https://fixture.example', 'FIRECRAWL_API_KEY': '',
                   'HERMES_DISABLE_LAZY_INSTALLS': '1'}
            completed = subprocess.run([python, '-I', '-c', code, str(source), str(ROOT), home],
                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {'status': 'ok', 'requests': 1})

    def run_boundary_script(self, body):
        import os
        import subprocess
        from runtime_paths import hermes_runtime
        python, source = hermes_runtime()
        bootstrap = '''
import sys, json, asyncio, socket
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
source, project = map(Path, sys.argv[1:3])
sys.path.insert(0, str(source))
import hermes_bootstrap
sys.path.insert(0, str(project))
import extraction_compat as compat
import extraction_worker as worker
import tools.url_safety as safety
assert Path(safety.__file__).resolve().is_relative_to(source)
assert not (source / 'tools/web_publication.py').exists()
'''
        completed = subprocess.run([python, '-I', '-c', bootstrap + body, str(source), str(ROOT)],
                                   env=os.environ.copy(), capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_real_secret_query_gate_before_safety_and_both_entrypoints(self):
        self.run_boundary_script(r'''
import hermes_cli.main as cli
from tools.registry import registry
import tools.web_tools
import focused_wrapper as wrapper
opaque = ''.join(chr(n) for n in [100,117,109,109,121,45,111,112,97,113,117,101])
urls = ['https://example.com/a?' + key + '=' + opaque
        for key in ['access_token', 'password', '%61ccess%5ftoken', '%2570assword']]
urls += ['https://' + opaque + '@example.com/a',
         'https://example.com/sk-' + 'x' * 48]
with ExitStack() as stack:
    safe = stack.enter_context(patch.object(safety, 'is_safe_url', return_value=True))
    policy = stack.enter_context(patch.object(compat, '_policy', return_value=None))
    resolve = stack.enter_context(patch.object(compat, 'resolve', side_effect=AssertionError('vendor admission')))
    for url in urls:
        try:
            asyncio.run(compat.check_url(url))
        except compat.CompatibilityError as exc:
            assert exc.reason in ('secret_url', 'invalid_url'), 'wrong refusal'
        else:
            raise AssertionError('secret admitted')
        result = asyncio.run(worker.extract({'version':1, 'url':url}))
        assert result['status'] == 'error', 'secret admitted'
        assert opaque not in json.dumps(result), 'credential echo'
        def main():
            raw = registry.dispatch('web_extract', {'urls':[url], 'char_limit':6000})
            result = json.loads(raw)
            assert result['results'][0]['error'], 'secret admitted'
            assert opaque not in raw and url not in raw, 'credential echo'
        with patch.object(cli, 'main', main):
            wrapper.main()
    assert safe.call_count == policy.call_count == resolve.call_count == 0, 'secret reached I/O'
''')

    def test_real_query_helper_benign_facets_and_unsupported_contract(self):
        self.run_boundary_script(r'''
url = 'https://example.com/a?code=blue&key=price&auth=type&session=summer&sig=sign'
with patch.object(safety, 'is_safe_url', return_value=True), patch.object(compat, '_policy', return_value=None):
    assert asyncio.run(compat.check_url(url)) == url
    for helper in [None, lambda: None, lambda url: False, lambda url: 3]:
        with patch.object(compat, 'sensitive_query_param_name', helper):
            try:
                asyncio.run(compat.check_url(url))
            except compat.CompatibilityError as exc:
                assert exc.reason == 'provider_error'
            else:
                raise AssertionError('unsupported helper admitted')
            from research_extraction import extract_tool
            opaque = ''.join(chr(n) for n in [100,117,109,109,121,45,111,112,97,113,117,101])
            raw = asyncio.run(extract_tool(['https://example.com/a?access_token=' + opaque]))
            assert opaque not in raw, 'unsupported helper credential echo'
''')

    def test_real_keenable_errors_through_worker_and_registered_mixed_batch(self):
        self.run_boundary_script(r'''
import io
from types import SimpleNamespace
from unittest.mock import Mock
import keenable_extraction as transport
import hermes_cli.main as cli
from tools.registry import registry
import tools.web_tools
import focused_wrapper as wrapper
from time import monotonic
url = 'https://example.com/a'
other = 'https://example.com/b'
provider = SimpleNamespace(name='keenable', uses_keyless=lambda: True)
calls = []
case = None
class Response:
    status = 200
    def __init__(self, raw): self.raw = io.BytesIO(raw)
    def read1(self, size): return self.raw.read(size)
    def isclosed(self): return False
    def close(self): pass
def connect(*args, **kwargs):
    conn = Mock()
    def request(method, path, **kwargs):
        calls.append(path)
    conn.request.side_effect = request
    def response():
        # Second member succeeds, proving a failure never poisons/replays it.
        success = len(calls) == 2
        if case == 'timeout' and not success:
            raise TimeoutError
        payload = {'url': other if success else url, 'title':'Article',
                   'content':'Company revenue increased. ' * 40}
        if not success and case == 'empty_content': payload['content'] = ''
        if not success and case == 'forged_reason':
            payload.update(status='error', reason='timeout')
        raw = json.dumps(payload).encode()
        if not success and case == 'output_limit': raw = b'x' * 100001
        result = Response(raw)
        if not success and case == 'provider_error': result.status = 503
        return result
    conn.getresponse.side_effect = response
    return conn
with ExitStack() as stack:
    stack.enter_context(patch.object(safety, 'is_safe_url', return_value=True))
    stack.enter_context(patch.object(compat, '_policy', return_value=None))
    stack.enter_context(patch.object(compat, 'resolve', return_value=provider))
    stack.enter_context(patch.object(compat, '_available', return_value=['keenable', 'exa']))
    stack.enter_context(patch.object(compat, 'ring_order', return_value=['keenable', 'exa']))
    stack.enter_context(patch.object(transport.http.client, 'HTTPSConnection', side_effect=connect))
    ring = stack.enter_context(patch.object(compat, 'keyless', wraps=compat.keyless))
    for case in ['timeout', 'output_limit', 'provider_error', 'empty_content', 'forged_reason']:
        expected = 'provider_error' if case == 'forged_reason' else case
        calls.clear(); ring.reset_mock()
        result = asyncio.run(worker.extract({'version':1, 'url':url}))
        assert result == worker.error(expected), (case, result)
        assert len(calls) == ring.call_count == 1, 'extra attempt'
        for urls in [[url], [url, other]]:
            calls.clear(); ring.reset_mock()
            def main():
                rows = json.loads(registry.dispatch('web_extract', {'urls':urls}))['results']
                assert rows[0]['reason'] == expected, (case, rows[0]['reason'])
                assert rows[0]['url'] == url and not rows[0]['content']
                assert 'publication' not in rows[0] and 'extraction_location' not in rows[0]
                if len(urls) == 2:
                    assert rows[1]['error'] is None and rows[1]['url'] == other
            with patch.object(cli, 'main', main): wrapper.main()
            assert len(calls) == len(urls) and ring.call_count == 1, 'batch replay'
''')

    def test_external_reason_and_envelope_extensions_never_gain_internal_trust(self):
        self.run_boundary_script(r'''
from types import SimpleNamespace
url = 'https://example.com/a'
base = {'url':url, 'title':'Article', 'content':'Company release. ' * 80,
        'error':'service failed', 'reason':'timeout', 'version':1, 'status':'error'}
provider = SimpleNamespace(name='fixture', uses_keyless=lambda: False,
                           extract=lambda urls, format: [row])
with ExitStack() as stack:
    stack.enter_context(patch.object(safety, 'is_safe_url', return_value=True))
    stack.enter_context(patch.object(compat, '_policy', return_value=None))
    stack.enter_context(patch.object(compat, 'resolve', return_value=provider))
    rescue = stack.enter_context(patch.object(compat, 'rescue_allowed', return_value=False))
    for row, expected in [(base, 'provider_error'),
        ({**base, 'publication':False}, 'malformed_response'),
        ({**base, 'extraction_location':False}, 'url_mismatch')]:
        result = asyncio.run(worker.extract({'version':1, 'url':url}))
        assert result == worker.error(expected), result
    # A malformed transport envelope must not be translated as a typed error.
    provider = SimpleNamespace(name='keenable', uses_keyless=lambda: True)
    stack.enter_context(patch.object(compat, 'resolve', return_value=provider))
    stack.enter_context(patch.object(compat, '_available', return_value=['keenable']))
    stack.enter_context(patch.object(compat, 'ring_order', return_value=['keenable']))
    for extension in ['publication', 'extraction_location']:
        raw = {**worker.error('timeout'), extension:False}
        with patch('keenable_extraction.fetch', return_value=raw):
            result = asyncio.run(worker.extract({'version':1, 'url':url}))
        assert result == worker.error('malformed_response'), result
''')

    def test_imports_from_selected_unpatched_root(self):
        import os
        import runtime_paths
        probe = self.probe()
        source = Path(os.environ.get('TRADEY_UNPATCHED_ROOT',
            '/home/hermes/.hermes/cache/scratch/project-extraction-unpatched'))
        self.assertTrue(source.is_dir(), 'explicit unpatched checkout required')
        # A disposable source snapshot need not own a PM dependency selection.
        # Borrow the installed venv only for this comparison; a global override
        # changes sys.executable in unrelated short-deadline process fixtures.
        from pm.environments import committed_venv
        _, installed_source = runtime_paths.hermes_runtime()
        environment = committed_venv(installed_source)
        self.assertIsNotNone(environment, 'installed dependency environment required')
        assert environment is not None
        python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        with __import__('unittest.mock', fromlist=['patch']).patch.dict(os.environ, {
            'HERMES_SOURCE_ROOT': str(source), 'HERMES_PYTHON': str(python),
        }):
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
                    self.assertEqual(detail['telemetry_version'], 3)
                    self.assertIs(detail['finalized'], True)
                    self.assertIs(detail['supervisor_completed'], True)


if __name__ == '__main__':
    unittest.main()
