"""Offline coordinator and isolated URL admission contracts."""
import asyncio
import unittest
from unittest.mock import patch, AsyncMock


def candidates(n=5, width=5):
    return [{'symbol': f'S{i}', 'urls': [f'https://p{j}.example/{i}' for j in range(width)]} for i in range(n)]


def allocation(rows):
    from focused_allocation import allocate_urls
    return allocate_urls(rows, {}, eligible_urls={u for c in rows for u in c['urls']}, unhealthy_domains=set())


def success(urls):
    return {'version': 2, 'status': 'ok', 'results': [
        {'requested_url': u, 'result': {'version': 1, 'status': 'ok',
         'page': {'url': u, 'title': 'Article', 'text': 'Evidence'}}} for u in urls]}


class PipelineTests(unittest.TestCase):
    def test_at_most_three_batches_in_flight_with_first_round_first(self):
        import focused_pipeline as pipeline
        import threading
        from concurrent.futures import ThreadPoolExecutor
        rows = candidates()
        plan = allocation(rows)
        lock = threading.Lock()
        release = threading.Event()
        ready = threading.Event()
        launched, active, peak = [], 0, 0
        def run(urls, timeout_seconds):
            nonlocal active, peak
            with lock:
                launched.append(urls)
                active += 1
                peak = max(peak, active)
                if active == 3:
                    ready.set()
            if not release.wait(2):
                raise AssertionError('coordinator did not overlap three batches')
            with lock:
                active -= 1
            return success(urls)
        with ThreadPoolExecutor(1) as outer:
            future = outer.submit(pipeline.extract_allocated, plan, deadline=pipeline.monotonic()+5, run_batch=run)
            try:
                self.assertTrue(ready.wait(2))
                self.assertEqual(len(launched), 3)
                self.assertEqual(launched[0], [r['urls'][0] for r in rows])
            finally:
                release.set()
            result = future.result(3)
        self.assertEqual(peak, 3)
        self.assertEqual(launched, plan.batches)
        self.assertEqual(len(launched), 5)
        self.assertEqual(result.submitted_urls, set(plan.unique_urls))
        self.assertEqual(len(result.pages), 25)
        for count in result.candidate_counts.values():
            self.assertEqual(count, {'selected': 5, 'submitted': 5, 'successful': 5})

    def test_selected_but_unsubmitted_is_not_transport_failure(self):
        import focused_pipeline as pipeline
        clock = [0.0]
        calls = []
        def run(urls, timeout_seconds):
            calls.append(urls)
            clock[0] = 11
            return success(urls)
        plan = allocation(candidates())
        with patch.object(pipeline, 'monotonic', side_effect=lambda: clock[0]):
            result = pipeline.extract_allocated(plan, deadline=10, run_batch=run)
        self.assertTrue(result.pages)
        self.assertLess(len(result.submitted_urls), 25)
        queued = set(plan.unique_urls)-result.submitted_urls
        self.assertTrue(queued)
        self.assertTrue(all(result.outcomes[u] == 'focused_deadline_exhausted' for u in queued))
        self.assertEqual(sum(c['selected'] for c in result.candidate_counts.values()), 25)
        self.assertEqual(sum(c['submitted'] for c in result.candidate_counts.values()), len(result.submitted_urls))

    def test_provider_errors_local_protocol_supervisor_errors_raise(self):
        import focused_pipeline as pipeline
        from structured_extraction import SupervisorFailure
        plan = allocation(candidates(1, 1))
        error = {'version': 2, 'status': 'error', 'reason': 'provider_error'}
        result = pipeline.extract_allocated(plan, deadline=pipeline.monotonic()+3, run_batch=lambda *a, **k: error)
        self.assertEqual(result.outcomes[plan.unique_urls[0]], 'provider_error')
        for out in ({}, SupervisorFailure(error)):
            with self.assertRaises(pipeline.FocusedFailure):
                pipeline.extract_allocated(plan, deadline=pipeline.monotonic()+3, run_batch=lambda *a, **k: out)

    def test_search_and_extract_share_absolute_deadline(self):
        import focused_pipeline as pipeline
        from focused_search import SearchResult
        clock = [0.0]
        allowances = []
        def search(rows, **kwargs):
            self.assertEqual(kwargs['deadline'], 12)
            clock[0] = 7
            return SearchResult({}, '2026-10-20T00:00:00+00:00', {})
        def validate(urls, timeout_seconds):
            allowances.append(timeout_seconds)
            self.assertLessEqual(timeout_seconds, min(30, 12-clock[0]))
            clock[0] += 1
            return {'version': 2, 'status': 'ok', 'results': [
                {'requested_url': u, 'eligible': True, 'reason': 'success'} for u in urls]}
        def run(urls, timeout_seconds):
            self.assertLessEqual(timeout_seconds, min(30, 12-clock[0]))
            return success(urls)
        with patch.object(pipeline, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(pipeline, 'search_alternatives', side_effect=search), \
             patch.object(pipeline, 'run_validation_worker', side_effect=validate), \
             patch.object(pipeline, 'run_batch_worker', side_effect=run):
            result = pipeline.run_focused_pipeline(candidates(5, 1), deadline=12, command=['fixture'], cwd=__import__('pathlib').Path('.'), unhealthy_domains=set())
        self.assertEqual(len(result.pages), 5)  # empty alternatives preserve all seeds
        self.assertEqual(allowances, [5])

    def test_real_extraction_supervisors_expire_without_late_refill_or_children(self):
        import focused_pipeline as pipeline
        import structured_extraction as supervisor
        import tempfile, sys, time
        from pathlib import Path
        from task4_probe import assert_dead
        script = '''
import sys, os, json, subprocess, time
from pathlib import Path
sys.stdin.buffer.read()
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
Path(DIRECTORY, str(os.getpid())+'.json').write_text(json.dumps([os.getpid(), child.pid]))
time.sleep(30)
'''
        with tempfile.TemporaryDirectory() as tmp:
            command = [sys.executable, '-c', script.replace('DIRECTORY', repr(tmp))]
            start = time.monotonic()
            with patch.object(supervisor, 'worker_command', return_value=command):
                result = pipeline.extract_allocated(allocation(candidates()), deadline=start+.5)
            self.assertLess(time.monotonic()-start, 2)
            self.assertEqual(len(result.submitted_urls), 15)
            self.assertEqual(list(result.outcomes.values()).count('focused_deadline_exhausted'), 10)
            files = list(Path(tmp).glob('*.json'))
            self.assertEqual(len(files), 3)
            for pidfile in files:
                assert_dead(self, pidfile)

    def test_shared_url_keeps_explicit_bindings_and_mixed_row_failure(self):
        import focused_pipeline as pipeline
        rows = candidates(2, 1)
        rows[1]['urls'].append(rows[0]['urls'][0])
        plan = allocation(rows)
        def run(urls, **kwargs):
            out = success(list(reversed(urls)))
            out['results'][0]['result'] = {'version': 1, 'status': 'error', 'reason': 'empty_content'}
            return out
        result = pipeline.extract_allocated(plan, deadline=pipeline.monotonic()+3, run_batch=run)
        self.assertEqual(len(result.submitted_urls), 2)
        self.assertEqual(len(result.pages), 1)
        self.assertEqual(result.candidate_counts['S0'], {'selected': 1, 'submitted': 1, 'successful': 1})
        self.assertEqual(result.candidate_counts['S1'], {'selected': 2, 'submitted': 2, 'successful': 1})
        self.assertEqual(set(result.checked_at), set(result.pages))

    def test_expired_and_small_pools_do_not_submit_empty_batches(self):
        import focused_pipeline as pipeline
        for rows in ([], candidates(1, 1)):
            calls = []
            plan = allocation(rows)
            result = pipeline.extract_allocated(plan, deadline=0, run_batch=lambda *a, **k: calls.append(a))
            self.assertEqual(calls, [])
            self.assertEqual(result.submitted_urls, set())
        calls = []
        pipeline.extract_allocated(allocation(candidates(1, 1)), deadline=pipeline.monotonic()+2,
                                   run_batch=lambda urls, **k: calls.append(urls) or success(urls))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), 1)


class SafetyTests(unittest.TestCase):
    def test_timeout_numeric_domain_is_typed_rejection(self):
        from extraction_worker import valid_batch_request, extract_batch
        from structured_extraction import run_batch_worker
        for timeout in (10**1000, True, float('nan'), float('inf'), -1):
            with self.subTest(kind=type(timeout).__name__):
                request = {'version': 2, 'urls': ['https://example.com/a'], 'timeout_seconds': timeout}
                self.assertFalse(valid_batch_request(request))
                self.assertEqual(asyncio.run(extract_batch(request))['reason'], 'invalid_request')
                self.assertEqual(run_batch_worker(request['urls'], timeout)['reason'], 'invalid_request')

    def test_supervisor_does_not_spawn_after_command_preparation_expiry(self):
        import structured_extraction as supervisor
        clock = [0.0]
        def command():
            clock[0] = 2
            return ['must-not-start']
        with patch.object(supervisor, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(supervisor, 'worker_command', side_effect=command), \
             patch.object(supervisor.subprocess, 'Popen', side_effect=AssertionError('late spawn')) as spawn:
            out = supervisor.run_validation_worker(['https://example.com/a'], timeout_seconds=1)
        self.assertEqual(out['reason'], 'timeout')
        self.assertEqual(spawn.call_count, 0)

    def test_safety_rejection_is_explicit_in_pipeline(self):
        import focused_pipeline as pipeline
        from focused_search import SearchResult
        rows = candidates(1, 1)
        url = rows[0]['urls'][0]
        out = {'version': 2, 'status': 'ok', 'results': [
            {'requested_url': url, 'eligible': False, 'reason': 'unsafe_url'}]}
        with patch.object(pipeline, 'search_alternatives', return_value=SearchResult({}, '', {})), \
             patch.object(pipeline, 'run_validation_worker', return_value=out):
            result = pipeline.run_focused_pipeline(rows, deadline=pipeline.monotonic()+2, command=[],
                       cwd=__import__('pathlib').Path('.'), unhealthy_domains=set())
        self.assertEqual(result.outcomes[url], 'unsafe_url')
        self.assertEqual(result.allocation.uncovered, {'S0': 'no_eligible_url'})

    def test_safety_worker_blocked_dns_is_killed_and_reaped(self):
        import structured_extraction as supervisor
        import tempfile, json, time
        from pathlib import Path
        from task4_probe import assert_dead
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp)/'pids.json'
            command = supervisor.worker_command()
            prefix = command[-1].split('runpy.run_path(')[0]
            probe = '''
import asyncio, json, os, socket, subprocess, sys, time
from pathlib import Path
import extraction_compat as compat

def blocked(*args, **kwargs):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Path(PIDFILE).write_text(json.dumps([os.getpid(), child.pid]))
    time.sleep(30)
async def check(url):
    await asyncio.to_thread(socket.getaddrinfo, 'offline.invalid', 443)
socket.getaddrinfo = blocked
compat.check_url = check
'''.replace('PIDFILE', repr(str(pidfile)))
            command[-1] = prefix + probe + '\n' + command[-1][len(prefix):]
            start = time.monotonic()
            with patch.object(supervisor, 'worker_command', return_value=command):
                out = supervisor.run_validation_worker(['https://example.com/a'], timeout_seconds=1)
            self.assertEqual(out['reason'], 'timeout')
            self.assertLess(time.monotonic()-start, 2.5)
            assert_dead(self, pidfile)

    def test_preselection_validates_thirty_without_raising_extraction_budget(self):
        import focused_pipeline as pipeline
        rows = candidates(5, 1)
        alternatives = {r['symbol']: [f'https://alt{j}.example/{r["symbol"]}' for j in range(5)] for r in rows}
        from focused_search import SearchResult
        calls = []
        def validate(urls, **kwargs):
            calls.append(urls)
            return {'version': 2, 'status': 'ok', 'results': [
                {'requested_url': u, 'eligible': True, 'reason': 'success'} for u in urls]}
        with patch.object(pipeline, 'search_alternatives', return_value=SearchResult(alternatives, '', {})), \
             patch.object(pipeline, 'run_validation_worker', side_effect=validate), \
             patch.object(pipeline, 'run_batch_worker', side_effect=lambda urls, **k: success(urls)):
            result = pipeline.run_focused_pipeline(rows, deadline=pipeline.monotonic()+3, command=[],
                       cwd=__import__('pathlib').Path('.'), unhealthy_domains=set())
        self.assertEqual(sum(map(len, calls)), 30)
        self.assertEqual(len(calls), 6)
        self.assertEqual(len(result.submitted_urls), 25)
        self.assertTrue(all(len(u) == 5 for u in result.allocation.by_symbol.values()))

    def test_validation_expiry_never_launches_next_batch(self):
        import focused_pipeline as pipeline
        clock = [0.0]
        calls = []
        def validate(urls, timeout_seconds):
            calls.append(urls)
            self.assertEqual(timeout_seconds, 1)
            clock[0] = 2
            return {'version': 2, 'status': 'error', 'reason': 'timeout'}
        with patch.object(pipeline, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(pipeline, 'run_validation_worker', side_effect=validate):
            eligible = pipeline.validate_pool_urls([f'https://a.example/{i}' for i in range(30)], deadline=1)
        self.assertEqual(eligible, set())
        self.assertEqual(len(calls), 1)

    def test_safety_only_exact_keys_and_no_body_fetch(self):
        from extraction_worker import validate_batch_urls
        import extraction_compat as compat
        async def check(url):
            if url.endswith('/bad'):
                raise compat.CompatibilityError('unsafe_url')
            return url.lower()
        urls = ['https://example.com/A', 'https://example.com/bad']
        with patch.object(compat, 'check_url', side_effect=check), patch.object(compat, 'resolve', side_effect=AssertionError('body provider called')):
            out = asyncio.run(validate_batch_urls({'version': 2, 'operation': 'validate_urls', 'urls': urls, 'timeout_seconds': 1}))
        self.assertEqual(out, {'version': 2, 'status': 'ok', 'results': [
            {'requested_url': urls[0], 'eligible': True, 'reason': 'success'},
            {'requested_url': urls[1], 'eligible': False, 'reason': 'unsafe_url'}]})
