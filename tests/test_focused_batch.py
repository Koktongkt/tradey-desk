"""Bounded v2 extraction, offline transport and real owned-process supervision."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

import extraction_compat as compat
import extraction_worker as worker
import structured_extraction as supervisor
from publication_provenance import provider_publication

URLS = [f'https://unknown.example/news/{i}' for i in range(5)]
BODY = 'The company raised revenue guidance following stronger customer demand. ' * 12


def request(urls=None, timeout=1):
    return {'version': 2, 'urls': URLS if urls is None else urls, 'timeout_seconds': timeout}


def row(url, **extra):
    return {'url': url, 'title': 'Article', 'content': BODY, 'error': None, **extra}


class BatchWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_admission_never_dispatches(self):
        invalid = [None, {}, {'version': True, 'urls': URLS},
                   request([]), request(URLS + ['https://other.example/']),
                   request([URLS[0], URLS[0]]), request(['x' * 4097]),
                   request([1]), request('not a list')]
        invalid += [request(timeout=t) for t in (True, False, float('nan'), float('inf'), -1, 0, '1')]
        async def forbidden(*args, **kwargs):
            self.fail('invalid request dispatched')
        for value in invalid:
            with self.subTest(value=repr(value)[:80]):
                self.assertEqual(await worker.extract_batch(value, forbidden),
                                 {'version': 2, 'status': 'error', 'reason': 'invalid_request'})

    async def test_exact_binding_rejects_duplicates_conflicts_and_forged_location(self):
        variants = [
            [row(URLS[0]), row(URLS[0])],
            [row(URLS[0]), row('https://unknown.example/unbound')],
            [row(URLS[0]), row(URLS[1], extraction_location={'version': 1, 'requested_url': URLS[0], 'returned_url': URLS[1]})],
            [row(URLS[0]), row(URLS[0], extraction_location={'version': 1, 'requested_url': URLS[1], 'returned_url': URLS[0]})],
            [row(URLS[0]), row(URLS[1], extraction_location={'version': True, 'requested_url': URLS[1], 'returned_url': URLS[1]})],
        ]
        for rows in variants:
            async def dispatch(*args, **kwargs): return json.dumps({'results': rows})
            with self.subTest(rows=rows):
                self.assertEqual(await worker.extract_batch(request(URLS[:2]), dispatch),
                                 {'version': 2, 'status': 'error', 'reason': 'url_mismatch'})

    async def test_injected_dispatch_cannot_attest_location(self):
        returned = 'https://unknown.example/new'
        rows = [row(returned, extraction_location={'version': 1, 'requested_url': URLS[0], 'returned_url': returned},
                    location_provenance='uncached_dispatch')]
        async def dispatch(urls, **kwargs):
            self.assertEqual(kwargs, {'format': 'markdown', 'char_limit': 6000})
            return json.dumps({'results': rows})
        out = await worker.extract_batch(request(URLS[:1]), dispatch)
        self.assertEqual(out['status'], 'ok')
        page = out['results'][0]['result']['page']
        self.assertEqual(page['url'], returned)
        self.assertNotIn('location_provenance', page)

    async def test_protocol_failure_distinct_from_page_error(self):
        for raw, reason in [('{"results":[],"results":[]}', 'malformed_response'),
                            ('{"results":[NaN]}', 'malformed_response'),
                            ('[', 'malformed_response'), ('x' * 100001, 'output_limit')]:
            async def dispatch(*args, **kwargs): return raw
            self.assertEqual(await worker.extract_batch(request(), dispatch),
                             {'version': 2, 'status': 'error', 'reason': reason})

    async def test_serialized_response_limit_rejects_intact_envelope(self):
        urls = ['https://unknown.example/' + str(i) + '☃' * 3000 for i in range(5)]
        async def dispatch(*args, **kwargs):
            raw = json.dumps({'results': [row(u, content='Article body') for u in urls]})
            self.assertLess(len(raw.encode()), 100000)
            return raw
        self.assertEqual(await worker.extract_batch(request(urls), dispatch),
                         {'version': 2, 'status': 'error', 'reason': 'output_limit'})

    async def test_controlled_dispatch_gets_one_shared_clamped_deadline(self):
        async def extract(urls, **kwargs):
            self.assertEqual(urls, URLS)
            self.assertEqual(kwargs, {'format': 'markdown', 'char_limit': 6000, 'deadline': 130.0})
            return json.dumps({'results': [row(u) for u in urls]})
        with patch('research_extraction.extract_owned_tool', side_effect=extract) as dispatch, \
             patch.object(worker, 'monotonic', return_value=100.0):
            out = await worker.extract_batch(request(timeout=90))
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(dispatch.call_count, 1)

    async def test_controlled_redacted_admission_failure_keeps_typed_reason(self):
        async def extract(*args, **kwargs):
            return json.dumps({'results': [row('', content='', error='unsafe_url', reason='unsafe_url') for _ in URLS]})
        with patch('research_extraction.extract_owned_tool', side_effect=extract):
            self.assertEqual(await worker.extract_batch(request()),
                             {'version': 2, 'status': 'error', 'reason': 'unsafe_url'})

    async def controlled_rows(self, rows, urls=None, *, rescue=None):
        checked = []
        async def check(url):
            checked.append(url)
            if '127.0.0.1' in url:
                raise compat.CompatibilityError('unsafe_url')
            return url
        async def primary(*args, **kwargs): return rows
        with patch.object(compat, 'check_url', side_effect=check), \
             patch.object(compat, 'resolve', return_value=types.SimpleNamespace(name='tavily')), \
             patch.object(compat, 'uses_keyless', return_value=False), \
             patch.object(compat, 'rescue_allowed', return_value=rescue is not None), \
             patch.object(compat, 'primary', side_effect=primary), \
             patch.object(compat, 'ring_order', return_value=['exa']), \
             patch.object(compat, 'keyless', side_effect=rescue) as ring:
            out = await worker.extract_batch(request(URLS[:2] if urls is None else urls))
        return out, checked, ring.call_count

    async def test_controlled_redirect_keeps_exact_request_and_checks_unsafe_hops(self):
        returned = 'https://news.unknown.example/new'
        loc = {'version': 1, 'requested_url': URLS[0], 'returned_url': returned}
        out, checked, _ = await self.controlled_rows([row(URLS[1]), row(returned, extraction_location=loc)])
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['results'][0]['requested_url'], URLS[0])
        self.assertEqual(out['results'][0]['result']['page']['url'], returned)
        self.assertIn(returned, checked)
        for unsafe in (row('https://127.0.0.1/private', extraction_location={**loc, 'returned_url': 'https://127.0.0.1/private'}),
                       row(returned, extraction_location=loc, metadata={'sourceURL': 'https://127.0.0.1/hop'})):
            out, checked, count = await self.controlled_rows([unsafe, row(URLS[1])])
            self.assertEqual(out['status'], 'ok')
            self.assertTrue(all(r['result']['reason'] == 'unsafe_url' for r in out['results']))
            self.assertTrue(any('127.0.0.1' in u for u in checked))
            self.assertEqual(count, 0)

    async def test_conflicting_date_is_row_error_and_future_report_not_publication_evidence(self):
        loc = {'version': 1, 'requested_url': URLS[0], 'returned_url': URLS[0]}
        # Fixed report dates, no clock dependency. Future reports remain unverified;
        # freshness admission is downstream, not a date inferred by this worker.
        for value, expected in ((1792195200, 'error'), (4102444799, 'ok')):
            body = 'Published: October 18, 2026\n' + BODY if expected == 'error' else BODY
            out, _, _ = await self.controlled_rows([row(URLS[0], publication=provider_publication(value),
                                                       extraction_location=loc, content=body), row(URLS[1])])
            self.assertEqual(out['status'], 'ok')
            first, sibling = [r['result'] for r in out['results']]
            self.assertEqual(first['status'], expected)
            self.assertEqual(sibling['status'], 'ok')
            if expected == 'error': self.assertEqual(first['reason'], 'malformed_response')
            else:
                self.assertNotIn('published_at', first['page'])
                self.assertEqual(first['page']['publication']['basis'], 'provider_reported')

    async def test_controlled_duplicate_identities_are_fatal_protocol_failure(self):
        out, _, _ = await self.controlled_rows([row(URLS[0]), row(URLS[0])])
        self.assertEqual(out, {'version': 2, 'status': 'error', 'reason': 'malformed_response'})

    async def test_controlled_configured_primary_and_anonymous_rescue_stay_in_dispatcher(self):
        rows = [row(u, error='upstream unavailable') for u in URLS[:2]]
        async def rescue(vendor, urls, *, deadline):
            self.assertEqual(vendor, 'exa')
            self.assertEqual(urls, URLS[:2])
            return [row(u, title='Rescued') for u in reversed(urls)]
        out, _, count = await self.controlled_rows(rows, rescue=rescue)
        self.assertEqual(count, 1)
        self.assertTrue(all(r['result']['page']['title'] == 'Rescued' for r in out['results']))

    async def test_batch_preserves_mixed_success_and_error_exact_keys(self):
        self.assertTrue(callable(getattr(worker, 'extract_batch', None)), 'batch worker missing')
        rows = [row(u) for u in URLS]
        rows[0]['content'] += '\n─── [TRUNCATED] ignored spill path'
        rows[1].update(error='upstream unavailable', content='')
        rows[2]['content'] = '# Access denied\nNot an article'
        rows[3].update(publication=provider_publication(1792195200),
                       extraction_location={'version': 1, 'requested_url': URLS[3], 'returned_url': URLS[3]})
        rows[3]['content'] = 'Published: October 17, 2026\n' + BODY
        rows[4]['content'] = 'Published: October 17, 2026\n' + BODY
        async def primary(provider, urls, *, format, deadline):
            self.assertEqual(urls, URLS)
            self.assertEqual(format, 'markdown')
            self.assertGreater(deadline, time.monotonic())
            return list(reversed(rows))
        async def check(url): return url
        with patch.object(compat, 'check_url', side_effect=check), \
             patch.object(compat, 'resolve', return_value=types.SimpleNamespace(name='tavily')), \
             patch.object(compat, 'uses_keyless', return_value=False), \
             patch.object(compat, 'primary', side_effect=primary):
            out = await worker.extract_batch(request())
        self.assertEqual(out['status'], 'ok')
        self.assertEqual([r['requested_url'] for r in out['results']], URLS)
        results = [r['result'] for r in out['results']]
        self.assertEqual([r['status'] for r in results], ['ok', 'error', 'error', 'ok', 'ok'])
        self.assertEqual(results[1]['reason'], 'provider_error')
        self.assertEqual(results[2]['reason'], 'empty_content')
        self.assertNotIn('TRUNCATED', results[0]['page']['text'])
        self.assertIn('publication', results[3]['page'])
        self.assertEqual(results[0]['page']['location_provenance'], 'uncached_dispatch')


class BatchEntryTests(unittest.TestCase):
    def invoke(self, payload):
        # Keep installed bootstrap and real stdin/main; only transport is offline.
        command = supervisor.worker_command()
        prefix = command[-1].split('runpy.run_path(')[0]
        probe = '''
import json, research_extraction as d
async def offline(urls, **kwargs):
    return json.dumps({'results':[{'url':u,'title':'Article','content':'Article body','error':None} for u in urls]})
d.extract_owned_tool = offline
'''
        command[-1] = prefix + probe + '\n' + command[-1][len(prefix):]
        out = subprocess.run(command, input=payload, capture_output=True, timeout=10)
        self.assertEqual(out.returncode, 0)
        return json.loads(out.stdout)

    def test_installed_batch_entry_accepts_more_than_legacy_input_cap(self):
        urls = [u + '☃'*4000 for u in URLS]
        raw = json.dumps(request(urls)).encode()
        self.assertGreater(len(raw), 8192)
        self.assertLess(len(raw), 131072)
        self.assertEqual(self.invoke(raw), {'version': 2, 'status': 'error', 'reason': 'output_limit'})

    def test_entry_preserves_version_one_byte_cap(self):
        raw = json.dumps({'version': 1, 'url': URLS[0] + '☃'*4000, 'timeout_seconds': 1}).encode()
        self.assertEqual(self.invoke(raw), {'version': 1, 'status': 'error', 'reason': 'invalid_request'})

    def test_installed_batch_entry_runs_real_protocol(self):
        out = self.invoke(json.dumps(request()).encode())
        self.assertEqual(out['version'], 2)
        self.assertEqual(out['status'], 'ok')
        self.assertEqual([r['requested_url'] for r in out['results']], URLS)
        self.assertTrue(all(r['result']['page']['location_provenance'] == 'uncached_dispatch' for r in out['results']))

    def test_entry_rejects_bad_batch_requests(self):
        for payload in (request([]), request(timeout=True), request(timeout=float('inf')),
                        request(URLS + ['six'])):
            raw = json.dumps(payload).encode()
            out = self.invoke(raw)
            self.assertEqual(out['status'], 'error')
            # Nonstandard Infinity is rejected by the strict loader before version discovery.
            self.assertEqual(out['reason'], 'malformed_response' if b'Infinity' in raw else 'invalid_request')


class BatchSupervisorTests(unittest.TestCase):
    def test_invalid_input_is_rejected_before_spawn(self):
        inputs = [(u, 1) for u in (None, [], 'not a list', URLS + ['six'], [URLS[0], URLS[0]], ['x'*4097], [1])]
        inputs += [(URLS, t) for t in (True, False, 0, -1, float('nan'), float('inf'), '1')]
        with patch.object(supervisor, 'worker_command', side_effect=AssertionError('spawned')):
            for urls, timeout in inputs:
                with self.subTest(urls=repr(urls)[:50], timeout=timeout):
                    self.assertEqual(supervisor.run_batch_worker(urls, timeout),
                                     {'version': 2, 'status': 'error', 'reason': 'invalid_request'})

    def test_malformed_worker_envelopes_are_fatal_not_page_errors(self):
        good = {'version': 2, 'status': 'ok', 'results': [
            {'requested_url': u, 'result': {'version': 1, 'status': 'error', 'reason': 'provider_error'}} for u in URLS]}
        malformed = [{}, {'version': 1, 'status': 'error', 'reason': 'timeout'},
                     {'version': 2, 'status': 'error', 'reason': 'unknown'},
                     {'version': True, 'status': 'ok', 'results': []},
                     {**good, 'results': good['results'][:-1]},
                     {**good, 'results': [good['results'][0]] * 5},
                     {**good, 'results': [{'requested_url': u, 'result': {}} for u in URLS]},
                     {**good, 'results': [{'requested_url': u, 'result': {'version': 1, 'status': 'ok', 'page': {'url': u, 'title': 'X', 'text': 1}}} for u in URLS]}]
        raws = [json.dumps(value) for value in malformed] + ['{"version":2,"version":2}', '[NaN]', '['*2000+'0'+']'*2000]
        for raw in raws:
            code = 'import os; os.close(0); print(' + repr(raw) + ', flush=True)'
            with self.subTest(raw=raw[:70]), patch.object(supervisor, 'worker_command', return_value=[sys.executable, '-c', code]):
                self.assertEqual(supervisor.run_batch_worker(URLS, 1),
                                 {'version': 2, 'status': 'error', 'reason': 'malformed_response'})

    def run_owned(self, code, timeout=.3, urls=None, command=None):
        """Only replace the spawn command; all pipes, PIDs and signals are real."""
        real_popen = subprocess.Popen
        processes = []
        def launch(*args, **kwargs):
            p = real_popen(*args, **{**kwargs, 'pipesize': 4096})
            processes.append(p)
            return p
        started = time.monotonic()
        with patch.object(supervisor, 'worker_command', return_value=command or [sys.executable, '-c', code]), \
             patch.object(supervisor.subprocess, 'Popen', side_effect=launch):
            out = supervisor.run_batch_worker(URLS if urls is None else urls, timeout)
        self.assertEqual(len(processes), 1)
        p = processes[0]
        self.assertIsNotNone(p.returncode)
        self.assertTrue(all(pipe.closed for pipe in (p.stdin, p.stdout, p.stderr)))
        with self.assertRaises(ChildProcessError): os.waitpid(p.pid, os.WNOHANG)
        return out, time.monotonic() - started

    def test_nonreading_worker_and_backpressure_share_deadline(self):
        urls = [u + '☃'*4000 for u in URLS]
        out, elapsed = self.run_owned('import time; time.sleep(.7)', timeout=.1, urls=urls)
        self.assertEqual(out, {'version': 2, 'status': 'error', 'reason': 'timeout'})
        self.assertLess(elapsed, .6)

    def test_stdout_and_stderr_overflow_while_input_pending(self):
        urls = [u + '☃'*4000 for u in URLS]
        for fd, size in ((1, 100001), (2, 16385)):
            code = ('import os,threading; threading.Timer(.7, lambda: os._exit(0)).start(); '
                    f'os.write({fd}, b"x" * {size})')
            out, elapsed = self.run_owned(code, timeout=.4, urls=urls)
            self.assertEqual(out, {'version': 2, 'status': 'error', 'reason': 'output_limit'})
            self.assertLess(elapsed, .6)

    def test_early_stdin_close_still_drains_valid_output(self):
        raw = json.dumps({'version': 2, 'status': 'error', 'reason': 'provider_error'})
        out, _ = self.run_owned('import os; os.close(0); print(' + repr(raw) + ', flush=True)',
                                urls=[u + '☃'*4000 for u in URLS])
        self.assertEqual(out, json.loads(raw))

    def test_large_unicode_input_is_fully_written_and_timeout_clamped(self):
        urls = [u + '☃'*4000 for u in URLS]
        code = ('import sys,json; q=json.load(sys.stdin); '
                'assert q["version"]==2 and len(q["urls"])==5 and len(q["urls"][0])==4030; '
                'assert q["timeout_seconds"]==30; '
                'print(json.dumps({"version":2,"status":"error","reason":"provider_error"}))')
        out, _ = self.run_owned(code, timeout=90, urls=urls)
        self.assertEqual(out, {'version': 2, 'status': 'error', 'reason': 'provider_error'})

    def test_startup_time_is_charged_to_deadline(self):
        def prepare():
            time.sleep(.04)
            return [sys.executable, '-c', 'import time; time.sleep(.7)']
        started = time.monotonic()
        with patch.object(supervisor, 'worker_command', side_effect=prepare):
            out = supervisor.run_batch_worker(URLS, .02)
        self.assertEqual(out, {'version': 2, 'status': 'error', 'reason': 'timeout'})
        self.assertLess(time.monotonic() - started, .5)

    def test_success_timeout_and_nonzero_kill_owned_descendants(self):
        from task4_probe import assert_dead
        with tempfile.TemporaryDirectory() as td:
            for mode in ('success', 'timeout', 'exit'):
                pidfile = Path(td)/mode
                tail = {'success': 'print(\'{"version":2,"status":"error","reason":"provider_error"}\',flush=True)',
                        'timeout': 'time.sleep(.7)', 'exit': 'sys.exit(3)'}[mode]
                code = ('import os,sys,subprocess,time,json; from pathlib import Path; '
                        'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"],'
                        'stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); '
                        f'Path({str(pidfile)!r}).write_text(json.dumps([os.getpid(),p.pid])); ' + tail)
                out, elapsed = self.run_owned(code)
                reason = {'success': 'provider_error', 'timeout': 'timeout', 'exit': 'worker_exit'}[mode]
                self.assertEqual(out, {'version': 2, 'status': 'error', 'reason': reason})
                self.assertLess(elapsed, .7)
                assert_dead(self, pidfile)

    def test_real_batch_kills_blocked_provider_and_dns_executor(self):
        from task4_probe import blocked_probe, assert_dead
        command = supervisor.worker_command()
        prefix = command[-1].split('runpy.run_path(')[0]
        with tempfile.TemporaryDirectory() as td:
            for mode in ('provider', 'dns'):
                pidfile = Path(td)/mode
                probe = blocked_probe(pidfile, mode).replace(
                    "worker.extract({'version':1,'url':'https://news.example/story'}, short_dispatch)",
                    "worker.extract_batch({'version':2,'urls':['https://news.example/story','https://news.example/other']}, short_dispatch)")
                probe_command = command[:-1] + [prefix + probe]
                out, elapsed = self.run_owned('', timeout=2, command=probe_command)
                self.assertEqual(out, {'version': 2, 'status': 'error', 'reason': 'timeout'})
                self.assertLess(elapsed, 3)
                assert_dead(self, pidfile)

    def test_spawn_failure_is_typed(self):
        with patch.object(supervisor, 'worker_command', side_effect=OSError('offline')):
            self.assertEqual(supervisor.run_batch_worker(URLS, 1),
                             {'version': 2, 'status': 'error', 'reason': 'worker_unavailable'})

    def test_real_owned_worker_protocol(self):
        self.assertTrue(callable(getattr(supervisor, 'run_batch_worker', None)), 'batch supervisor missing')
        code = ('import sys,json; q=json.load(sys.stdin); '
                'assert q["version"]==2 and len(q["urls"])==5; '
                'print(json.dumps({"version":2,"status":"ok","results":'
                '[{"requested_url":u,"result":{"version":1,"status":"error","reason":"provider_error"}} for u in q["urls"]]}))')
        real_popen = subprocess.Popen
        processes = []
        def launch(*args, **kwargs):
            p = real_popen(*args, **kwargs)
            processes.append(p)
            return p
        with patch.object(supervisor, 'worker_command', return_value=[sys.executable, '-c', code]), \
             patch.object(supervisor.subprocess, 'Popen', side_effect=launch):
            out = supervisor.run_batch_worker(URLS, 1)
        self.assertEqual(out['status'], 'ok')
        self.assertEqual([r['requested_url'] for r in out['results']], URLS)
        self.assertEqual(len(processes), 1)
        p = processes[0]
        self.assertIsNotNone(p.returncode)
        self.assertTrue(all(pipe.closed for pipe in (p.stdin, p.stdout, p.stderr)))
        with self.assertRaises(ChildProcessError): os.waitpid(p.pid, os.WNOHANG)


if __name__ == '__main__':
    unittest.main()
