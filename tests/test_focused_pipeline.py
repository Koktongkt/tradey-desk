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
    def test_individually_bounded_raw_responses_survive_large_logical_group(self):
        import focused_pipeline as pipeline
        import research_extraction as research
        from extraction_worker import extract_batch
        from types import SimpleNamespace
        calls = []
        plan = allocation(candidates(1, 5))
        import json
        raw_rows = [{'url': u, 'title': 'Article',
                     'content': 'Company revenue increased. ' * 1300} for u in plan.unique_urls]
        size = lambda rows: len(json.dumps({'results': rows}, separators=(',', ':')).encode())
        self.assertGreater(size(raw_rows), 100_000)
        self.assertTrue(all(size([row]) < 100_000 for row in raw_rows))
        async def provider(provider, urls, **kwargs):
            calls.append(list(urls))
            return [{'url': u, 'title': 'Article',
                     'content': 'Company revenue increased. ' * 1300} for u in urls]
        async def safe(url):
            return url
        def run(urls, timeout_seconds):
            return asyncio.run(extract_batch({'version': 2, 'urls': urls,
                                             'timeout_seconds': timeout_seconds}))
        with patch.object(research.compat, 'check_url', side_effect=safe), \
             patch.object(research.compat, 'resolve', return_value=SimpleNamespace(name='fixture')), \
             patch.object(research.compat, 'uses_keyless', return_value=False), \
             patch.object(research.compat, 'primary', side_effect=provider), \
             patch.object(research.compat, 'rescue_allowed', return_value=False):
            result = pipeline.extract_allocated(plan, deadline=pipeline.monotonic()+10, run_batch=run)
        self.assertEqual(len(result.pages), 5)
        self.assertCountEqual(calls, [[u] for u in plan.unique_urls])

    def test_bad_singleton_retains_independent_siblings_without_retry(self):
        import focused_pipeline as pipeline
        import research_extraction as research
        from extraction_worker import extract_batch
        from types import SimpleNamespace
        plan = allocation(candidates(1, 5))
        for failure in ('output_limit', 'url_mismatch'):
            with self.subTest(failure=failure):
                calls = []
                async def provider(provider, urls, **kwargs):
                    calls.append(list(urls))
                    row = {'url': urls[0], 'title': 'Article',
                           'content': 'Company revenue increased. ' * 80}
                    if urls[0] == plan.unique_urls[0]:
                        if failure == 'output_limit':
                            # Ignorable extensions still count BEFORE projection.
                            row['opaque_extension'] = 'x' * 100_001
                        else:
                            row['extraction_location'] = {'version': 1,
                                'requested_url': plan.unique_urls[1], 'returned_url': urls[0]}
                    return [row] + [{'url': u, 'title': 'Article',
                        'content': 'Company revenue increased. ' * 80} for u in urls[1:]]
                async def safe(url):
                    return url
                def run(urls, timeout_seconds):
                    return asyncio.run(extract_batch({'version': 2, 'urls': urls,
                                                     'timeout_seconds': timeout_seconds}))
                with patch.object(research.compat, 'check_url', side_effect=safe), \
                     patch.object(research.compat, 'resolve', return_value=SimpleNamespace(name='fixture')), \
                     patch.object(research.compat, 'uses_keyless', return_value=False), \
                     patch.object(research.compat, 'primary', side_effect=provider), \
                     patch.object(research.compat, 'rescue_allowed', return_value=False):
                    result = pipeline.extract_allocated(plan, deadline=pipeline.monotonic()+10, run_batch=run)
                self.assertEqual(result.outcomes[plan.unique_urls[0]], failure)
                self.assertEqual(set(result.pages), set(plan.unique_urls[1:]))
                self.assertCountEqual(calls, [[u] for u in plan.unique_urls])

    def test_at_most_three_singletons_in_flight_with_first_round_first(self):
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
        # Delay callback zero after FIFO admission, forcing callback one first.
        # Callback start order is not dispatcher admission order.
        second = threading.Event()
        admitted = []
        real_condition = threading.Condition
        class OrderedCondition:
            def __init__(self):
                self.inner = real_condition()
                self.local = threading.local()
            def __enter__(self):
                return self.inner.__enter__()
            def wait_for(self, predicate):
                return self.inner.wait_for(predicate)
            def notify_all(self):
                self.local.index = len(admitted)
                admitted.append([plan.unique_urls[len(admitted)]])
                self.inner.notify_all()
            def __exit__(self, *args):
                result = self.inner.__exit__(*args)
                if self.local.index == 0:
                    if not second.wait(2):
                        raise AssertionError('second admission did not overtake callback zero')
                else:
                    second.set()
                return result
        with ThreadPoolExecutor(1) as outer, patch.object(pipeline, 'ThreadPoolExecutor', ThreadPoolExecutor):
            # Patch only the coordinator condition, not executor internals.
            original_condition = threading.Condition
            def condition_factory(*args, **kwargs):
                import inspect
                if inspect.currentframe().f_back.f_code.co_name == 'extract_allocated':
                    return OrderedCondition()
                return original_condition(*args, **kwargs)
            with patch.object(threading, 'Condition', new=condition_factory):
                future = outer.submit(pipeline.extract_allocated, plan, deadline=pipeline.monotonic()+5, run_batch=run)
                self.assertTrue(ready.wait(2))
            try:
                self.assertTrue(ready.wait(2))
                self.assertEqual(len(launched), 3)
                self.assertEqual(admitted[:3], [[u] for u in plan.unique_urls[:3]])
            finally:
                release.set()
            result = future.result(3)
        self.assertEqual(peak, 3)
        self.assertEqual(admitted, [[u] for u in plan.unique_urls])
        self.assertCountEqual(launched, [[u] for u in plan.unique_urls])
        self.assertEqual(len(launched), 25)
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
            self.assertEqual(len(result.submitted_urls), 3)
            self.assertEqual(list(result.outcomes.values()).count('focused_deadline_exhausted'), 22)
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
            if urls[0] == plan.unique_urls[-1]:
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


class ProbeTests(unittest.TestCase):
    def probe(self):
        from scripts import probe_focused_coverage
        return probe_focused_coverage

    def test_pinned_baseline_guard_bootstraps_native_wsp_registration(self):
        import subprocess, sys, tempfile
        from pathlib import Path
        p = self.probe()
        baseline = p.ARTIFACTS / 'task6-baseline-835c56c'
        code = '''
import sys, runpy
from pathlib import Path
sys.path.insert(0, BASELINE)
import focused_capture as capture
assert Path(capture.__file__).resolve().parent == Path(BASELINE)
probe = runpy.run_path(PROBE)
command = probe['guarded_command'](capture.focused_command(['hermes','chat']), SINK)
prefix = command[3].rsplit('runpy.run_path(', 1)[0]
check = "import hermes_cli.main; from tools.web_tools import _ensure_web_plugins_loaded; _ensure_web_plugins_loaded(); from agent.web_search_registry import get_provider; assert get_provider('wsp') is not None, 'native_wsp_missing'; print('baseline-wsp-registered')"
done = __import__('subprocess').run(command[:3]+[prefix+check], capture_output=True, text=True, timeout=30)
assert done.returncode == 0, done.stderr[-3000:]
assert 'baseline-wsp-registered' in done.stdout
'''
        with tempfile.TemporaryDirectory() as tmp:
            code = code.replace('BASELINE', repr(str(baseline))).replace('PROBE', repr(str(Path(p.__file__)))).replace('SINK', repr(tmp))
            done = subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=40)
            self.assertEqual(done.returncode,0,done.stderr[-4000:])

    def test_probe_requires_private_sink_before_runner(self):
        p = self.probe()
        with patch.object(p, "execute", side_effect=AssertionError("network reached")) as run:
            with self.assertRaisesRegex(ValueError, "private_path"):
                p.run_probe([], output="/outside.json", as_of="2026-10-20T00:00:00+00:00")
        self.assertEqual(run.call_count, 0)

    def test_probe_rejects_symlinks_escape_and_hardlinks(self):
        import tempfile, os
        from pathlib import Path
        p = self.probe()
        with tempfile.TemporaryDirectory() as tmp, patch.object(p, "ARTIFACTS", Path(tmp)/"private"):
            p.ARTIFACTS.mkdir(mode=0o700)
            outside = Path(tmp)/"outside"
            outside.mkdir()
            (p.ARTIFACTS/"link").symlink_to(outside, target_is_directory=True)
            for path in (p.ARTIFACTS/"link"/"a", p.ARTIFACTS/".."/"outside"/"a", p.ARTIFACTS):
                with self.assertRaises(ValueError): p.private_path(path)
            target = p.ARTIFACTS/"existing"
            target.write_text("unchanged")
            os.link(target, p.ARTIFACTS/"hard")
            with self.assertRaises(ValueError): p.write_private(target, {})
            self.assertEqual(target.read_text(), "unchanged")
            p.write_private(p.ARTIFACTS/"nested"/"report.json", {})
            self.assertEqual((p.ARTIFACTS/"nested").stat().st_mode & 0o777, 0o700)
            self.assertEqual((p.ARTIFACTS/"nested"/"report.json").stat().st_mode & 0o777, 0o600)

    def test_probe_input_is_bounded_and_utc_explicit(self):
        p = self.probe()
        row = {"symbol":"TEVA", "catalyst":"provisional historical claim", "event_date":"2026-10-09", "urls":["https://example.com/article"]}
        self.assertEqual(p.validate_cohort([row]), [row])
        for rows in ([], [row]*6, [row,row], [{**row,"urls":[] }], [{**row,"urls":row["urls"]*2}], [{**row,"catalyst":"x"*2001}]):
            with self.assertRaises(ValueError): p.validate_cohort(rows)
        for stamp in (None, "2026-10-20", "2026-10-20T00:00:00+01:00"):
            with self.assertRaises(ValueError): p.parse_as_of(stamp)
        self.assertEqual(p.parse_as_of("2026-10-20T00:00:00Z").isoformat(), "2026-10-20T00:00:00+00:00")

    def test_probe_strict_binding_counts_not_global_duplicates(self):
        from focused_pipeline import extract_allocated, monotonic
        p = self.probe()
        rows = candidates(2,1)
        rows[1]["urls"].append(rows[0]["urls"][0])
        result = extract_allocated(allocation(rows), deadline=monotonic()+2, run_batch=lambda urls, **k:success(urls))
        counts = p.account(rows, result, {"S0":[rows[0]["urls"][0]], "S1":[]})
        self.assertEqual(counts["unique"], {"selected":2,"submitted":2,"extracted":2,"accepted":1})
        self.assertEqual(counts["candidates"]["S1"]["submitted"], 2)
        with self.assertRaisesRegex(ValueError,"accounting"):
            p.account(rows,result,{"S0":["https://not-selected.example/a"]})

    def test_probe_child_home_isolated_with_read_only_existing_routing(self):
        import subprocess, sys, tempfile
        from pathlib import Path
        self.probe()
        with tempfile.TemporaryDirectory() as tmp:
            code = ('import os; from pathlib import Path; from scripts.probe_focused_coverage import child_sinks; '
                    'from hermes_constants import get_hermes_home; before=get_hermes_home(); '
                    f'child_sinks({tmp!r}); '
                    'after=get_hermes_home(); assert after != before; '
                    'assert (after/"config.yaml").resolve() == (before/"config.yaml").resolve(); '
                    'assert (after/"plugins").resolve() == (before/"plugins").resolve(); '
                    '(after/"probe-owned").write_text("safe")')
            done = subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_probe_redirects_native_wsp_cache_before_import(self):
        import subprocess, sys, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            code = ('import os; from pathlib import Path; '
                    'from scripts.probe_focused_coverage import child_sinks; '
                    f'child_sinks({tmp!r}); '
                    f'assert os.environ.get("WSP_CACHE_DIR") == str(Path({tmp!r})/"wsp-cache"); '
                    'root=Path("/home/hermes/.hermes/plugins/web-search-plus"); '
                    'import sys; sys.path.insert(0,str(root)); '
                    'from wsp_core.cache import CACHE_DIR, _atomic_write_text; '
                    'assert CACHE_DIR == Path(os.environ["WSP_CACHE_DIR"]); '
                    '_atomic_write_text(CACHE_DIR/"probe.json", "{}"); '
                    'assert (CACHE_DIR/"probe.json").read_text() == "{}"')
            done = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_probe_guard_allows_pure_radar_helpers_but_blocks_ledger_calls(self):
        import subprocess, sys, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            code = r"""
from scripts.probe_focused_coverage import child_sinks
child_sinks(SINK)
import alpha_radar, durable_jsonl
assert alpha_radar.publisher_domain('https://example.com/a') == 'example.com'
for fn in (durable_jsonl.append_jsonl, durable_jsonl.read_jsonl,
           alpha_radar.append_jsonl, alpha_radar.read_jsonl):
    try:
        fn(SINK + '/forbidden-ledger')
    except PermissionError as exc:
        assert str(exc) == 'forbidden_probe_ledger'
    else:
        raise AssertionError('ledger callable')
from pathlib import Path
assert not Path(SINK, 'forbidden-ledger').exists()
""".replace('SINK', repr(tmp))
            done = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_probe_blocks_operational_modules_and_external_writes(self):
        import subprocess,sys,tempfile
        from pathlib import Path
        p = self.probe()
        with tempfile.TemporaryDirectory() as tmp:
            code = "from scripts.probe_focused_coverage import install_safety; install_safety(%r); %%s" % tmp
            for action in ("import autotrader", "open(\"/outside-probe-write\",\"w\")", "import sqlite3; sqlite3.connect(\"/outside-probe.db\")"):
                done=subprocess.run([sys.executable,"-c",code % action],capture_output=True,text=True)
                self.assertNotEqual(done.returncode,0)
                self.assertIn("forbidden_probe",done.stderr)
