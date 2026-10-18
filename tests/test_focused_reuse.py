"""Offline trusted focused captures; no models, providers or operational writes."""
import asyncio
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import alpha_radar as radar

URL = 'https://news.example/story'
OTHER = 'https://other.example/article'
BODY = '<meta property="article:published_time" content="2026-10-18T00:00:00Z">' + ('The company raised revenue guidance after stronger customer demand. ' * 8)


def capture_module():
    assert importlib.util.find_spec('focused_capture'), 'trusted focused capture boundary missing'
    return importlib.import_module('focused_capture')


def raw(rows=None, **declarations):
    return json.dumps(dict(results=rows if rows is not None else [{'url': URL, 'content': BODY}], **declarations))


class FocusedReuseTests(unittest.TestCase):
    def test_over_cap_returned_row_count_is_not_reusable(self):
        cap=capture_module()
        rows=[{'url':URL,'content':BODY}]+[{'url':f'https://unrequested.example/{i}','content':'body'} for i in range(5)]
        with tempfile.TemporaryFile() as channel:
            recorder=cap.Recorder(channel.fileno(),'a'*64)
            recorder.record({'urls':[URL],'format':'markdown','char_limit':6000},raw(rows))
            recorder.complete()
            self.assertEqual(cap.read_capture(channel.fileno(),'a'*64),{})

    def test_parent_channel_permissions_are_explicit_even_with_restrictive_umask(self):
        cap=capture_module()
        script='''
import os, stat
from pathlib import Path
from focused_capture import FD_ENV
fd=int(os.environ[FD_ENV])
assert stat.S_IMODE(os.fstat(fd).st_mode)==0o600
assert stat.S_IMODE(Path(os.readlink('/proc/self/fd/'+str(fd))).parent.stat().st_mode)==0o700
print('private-channel')
'''
        mask=os.umask(0o777)
        try:
            with patch.object(cap,'focused_command',side_effect=lambda c:c):
                done=cap.run_focused([sys.executable,'-c',script],input='',capture_output=True,text=True,
                                     timeout=3,cwd=Path(radar.__file__).parent)
            self.assertEqual(done.returncode,0,done.stderr)
            self.assertEqual(done.stdout,'private-channel\n')
        finally:os.umask(mask)

    def test_wrapper_restores_guard_and_only_completes_on_success(self):
        cap = capture_module()
        command = cap.focused_command(['hermes','chat'])
        prefix = command[3].split('runpy.run_path(')[0]
        probe = r'''
import asyncio, os, tempfile
from unittest.mock import patch
import hermes_cli.main as cli
import tools.web_tools as web
import tools.web_result_cache as cache
import focused_wrapper as wrapper
import focused_capture as cap
async def original(*a,**kw):
    return '{"results":[{"url":"https://news.example/story","content":"article"}]}'
for fault, wanted in [(None,True),(SystemExit(0),True),(SystemExit(7),False),(RuntimeError('offline'),False)]:
    with tempfile.TemporaryFile() as channel:
        os.environ[cap.FD_ENV]=str(channel.fileno())
        os.environ[cap.NONCE_ENV]='a'*64
        old_cache=cache.extract_cache_get
        def main():
            asyncio.run(web.web_extract_tool(['https://news.example/story']))
            if fault is not None:raise fault
        with patch.object(web,'web_extract_tool',original), patch.object(cli,'main',main):
            try:wrapper.main()
            except (RuntimeError,SystemExit) as got:assert got is fault
            assert web.web_extract_tool is original
            assert cache.extract_cache_get is old_cache
            assert bool(cap.read_capture(channel.fileno(),'a'*64)) is wanted
print('wrapper-exit-semantics-ok')
'''
        done = subprocess.run(command[:3]+[prefix+probe]+command[4:],capture_output=True,text=True,timeout=30)
        self.assertEqual(done.returncode,0,done.stderr[-4000:])
        self.assertEqual(done.stdout.strip(),'wrapper-exit-semantics-ok')

    def test_parent_reaps_owned_group_after_success_and_timeout(self):
        cap = capture_module()
        script = '''
import subprocess, sys, time
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
Path(sys.argv[1]).write_text(str(child.pid))
if sys.argv[2]=='timeout':time.sleep(30)
print('complete')
'''
        with tempfile.TemporaryDirectory() as td, patch.object(cap,'focused_command',side_effect=lambda c:c):
            for mode in ('success','timeout'):
                pidfile=Path(td)/mode
                argv=[sys.executable,'-c',script,str(pidfile),mode]
                if mode=='timeout':
                    with self.assertRaises(subprocess.TimeoutExpired):
                        cap.run_focused(argv,input='',capture_output=True,text=True,timeout=.3,cwd=td)
                else:
                    self.assertEqual(cap.run_focused(argv,input='',capture_output=True,text=True,timeout=3,cwd=td).returncode,0)
                pid=int(pidfile.read_text())
                for _ in range(100):
                    status=Path(f'/proc/{pid}/stat')
                    if not status.exists() or status.read_text().split()[2]=='Z':break
                    __import__('time').sleep(.01)
                else:self.fail('owned descendant still running')

    def test_unsupported_runtime_fails_without_launch_and_channel_unavailability_is_optional(self):
        cap = capture_module()
        with patch('runtime_paths.hermes_runtime',side_effect=ValueError('unsupported')), patch.object(subprocess,'Popen') as launch:
            with self.assertRaises(OSError):
                cap.run_focused(['offline','chat'],input='',capture_output=True,text=True,timeout=1,cwd=Path(radar.__file__).parent)
            launch.assert_not_called()
        with patch.object(cap,'focused_command',side_effect=lambda c:c), patch.object(tempfile,'TemporaryDirectory',side_effect=OSError('no capture')):
            done=cap.run_focused([sys.executable,'-c','print("successful stage")'],input='',capture_output=True,text=True,timeout=3,cwd=Path(radar.__file__).parent)
        self.assertEqual(done.returncode,0)
        self.assertEqual(done.stdout,'successful stage\n')
        self.assertEqual(done.focused_pages,{})

    def test_reuse_does_not_relax_two_publisher_gate_or_extend_deadline(self):
        worker=importlib.import_module('extraction_worker')
        urls=['https://news.publisher.example/one','https://ir.publisher.example/two']
        focused={u:worker.project_row({'url':u,'content':BODY}) for u in urls}
        with patch.object(radar,'is_safe_public_url',return_value=True), patch.object(radar,'fetch_source') as direct:
            pages=radar.gather_evidence(urls,focused_pages=focused)
            self.assertEqual(len(pages),2)
            direct.assert_not_called()
            selected,evidence=radar.select_candidate_evidence([{'symbol':'AAA','urls':urls}],pages)
            self.assertIsNone(selected)
            self.assertEqual(evidence,[])
            diagnostics=[]
            self.assertEqual(radar.gather_evidence(urls,focused_pages=focused,collection_deadline=radar.monotonic()-1,diagnostics=diagnostics),[])
            direct.assert_not_called()
            self.assertEqual({d['reason'] for d in diagnostics},{'source_deadline_exhausted'})

    def test_capture_cannot_normalize_or_inject_a_new_exact_key(self):
        cap=capture_module()
        normalized=URL+'/'
        with tempfile.TemporaryFile() as channel:
            recorder=cap.Recorder(channel.fileno(),'a'*64)
            recorder.record({'urls':[URL,OTHER],'format':'markdown','char_limit':6000},raw([{'url':normalized,'content':BODY}]))
            recorder.complete()
            self.assertEqual(cap.read_capture(channel.fileno(),'a'*64),{})

    def test_artifact_strict_schema_nonce_completion_bounds_and_permissions(self):
        cap = capture_module()
        with tempfile.TemporaryFile() as channel:
            recorder = cap.Recorder(channel.fileno(), 'a' * 64)
            recorder.record({'urls':[URL], 'format':'markdown', 'char_limit':6000}, raw())
            recorder.complete()
            channel.seek(0)
            original = channel.read()
            artifact = json.loads(original)
            bad = [original[:-1], original.replace(b'"version":1', b'"version":1,"version":1'),
                   original.replace(b'"complete":true', b'"complete":NaN'),
                   b'x' * (cap.MAX_ARTIFACT_BYTES + 1)]
            for key, value in [('nonce','b' * 64), ('complete',False), ('version',True), ('extra','bad')]:
                bad.append(json.dumps(dict(artifact, **{key:value})).encode())
            for data in bad:
                with self.subTest(kind=data[:60]):
                    channel.seek(0); channel.truncate(); channel.write(data); channel.flush()
                    self.assertEqual(cap.read_capture(channel.fileno(), 'a' * 64), {})
            channel.seek(0); channel.truncate(); channel.write(original); channel.flush()
            self.assertEqual(set(cap.read_capture(channel.fileno(), 'a' * 64)), {URL})
            self.assertEqual(cap.read_capture(channel.fileno(), 'b' * 64), {})
            os.fchmod(channel.fileno(), 0o644)
            self.assertEqual(cap.read_capture(channel.fileno(), 'a' * 64), {})
        read_fd, write_fd = os.pipe()
        try:
            self.assertEqual(cap.read_capture(read_fd, 'a' * 64), {})
        finally:
            os.close(read_fd); os.close(write_fd)

    def test_per_call_utf8_cap_and_recording_failure_leave_response_unchanged(self):
        cap = capture_module()
        for result in (raw(), 'é' * (cap.MAX_RAW_BYTES // 2 + 1)):
            async def original(*args, **kwargs): return result
            with tempfile.TemporaryFile() as channel:
                recorder = cap.Recorder(channel.fileno(), 'a' * 64)
                self.assertIs(asyncio.run(recorder.wrap(original)([URL], 'markdown', char_limit=6000)), result)
                if len(result.encode()) > cap.MAX_RAW_BYTES:
                    self.assertEqual(recorder.calls, [])
                with patch.object(cap.os, 'pwrite', side_effect=OSError('optional recording failed')):
                    recorder.complete()
                self.assertEqual(cap.read_capture(channel.fileno(), 'a' * 64), {})
        with tempfile.TemporaryFile() as channel:
            recorder = cap.Recorder(channel.fileno(), 'a' * 64)
            async def original(*args, **kwargs): return result
            with patch.object(recorder, 'record', side_effect=RuntimeError('capture failure')):
                self.assertIs(asyncio.run(recorder.wrap(original)([URL])), result)
            self.assertTrue(recorder.disabled)

    def test_unrecordable_invocation_discards_capture_in_either_completion_order(self):
        cap = capture_module()
        valid = raw()
        cases = [
            ('oversized', raw([{'url': URL, 'content': 'Conflicting revised article ' * 5000}]), 'markdown'),
            ('nonstring', {'results': [{'url': URL, 'content': 'Conflicting article'}]}, 'markdown'),
            ('invalid_request', raw(), 'unsupported-format'),
        ]
        for kind, conflict, conflict_format in cases:
            for order in ((0, 1), (1, 0)):
                with self.subTest(kind=kind, completion_order=order), tempfile.TemporaryFile() as channel:
                    recorder = cap.Recorder(channel.fileno(), 'a' * 64)
                    requests = [[URL], [URL]]
                    responses = [valid, conflict]
                    formats = ['markdown', conflict_format]
                    calls, completed = [], []

                    async def exercise():
                        release = [asyncio.Event(), asyncio.Event()]
                        async def original(urls, format, *, char_limit):
                            index = len(calls)
                            calls.append((urls, format, char_limit))
                            await release[index].wait()
                            completed.append(index)
                            return responses[index]
                        wrapped = recorder.wrap(original)
                        tasks = [asyncio.create_task(wrapped(requests[i], formats[i], char_limit=6000))
                                 for i in range(2)]
                        await asyncio.sleep(0)
                        for index in order:
                            release[index].set()
                            self.assertIs(await tasks[index], responses[index])

                    asyncio.run(exercise())
                    self.assertEqual(completed, list(order))
                    self.assertEqual(len(calls), 2)
                    self.assertEqual(recorder.invocations, 2)
                    for i, (urls, format, limit) in enumerate(calls):
                        self.assertIs(urls, requests[i])
                        self.assertEqual((format, limit), (formats[i], 6000))
                    recorder.complete()
                    captures = cap.read_capture(channel.fileno(), 'a' * 64)
                    self.assertEqual(captures, {})
                    self.assertTrue(recorder.disabled)

                    # Exercise the real direct fetch/parser; only HTTP transport
                    # is stubbed, so no accepted receipt is invented for the miss.
                    fetched_body = '<title>Ordinary fetch</title>' + BODY.replace('raised revenue', 'confirmed revenue')
                    with patch.object(radar, 'is_safe_public_url', return_value=True), patch.object(
                        radar, 'safe_urlopen'
                    ) as transport, patch.object(radar, 'fetch_source', wraps=radar.fetch_source) as direct, patch.object(
                        radar, 'fetch_source_via_gateway', side_effect=AssertionError('unnecessary fallback')
                    ) as fallback:
                        response = transport.return_value.__enter__.return_value
                        response.geturl.return_value = URL
                        response.read.return_value = fetched_body.encode('utf-8')
                        pages = radar.gather_evidence([URL, URL], focused_pages=captures)
                    direct.assert_called_once()
                    transport.assert_called_once()
                    self.assertEqual(transport.call_args.args[0].full_url, URL)
                    response.read.assert_called_once_with(2_000_000)
                    fallback.assert_not_called()
                    self.assertEqual(len(pages), 1)
                    self.assertEqual(pages[0]['url'], URL)
                    self.assertEqual(pages[0]['title'], 'Ordinary fetch')
                    self.assertIn('confirmed revenue guidance', pages[0]['text'])
                    self.assertIsNotNone(pages[0]['published_at'])
                    self.assertNotIn('checked_at', pages[0])

    def test_capture_caps_do_not_change_tool_arguments_or_calls(self):
        cap = capture_module()
        request = {'urls':[URL], 'format':'markdown', 'char_limit':6000}
        for limit, value in [('MAX_ARTIFACT_BYTES',1200), ('MAX_URLS',1), ('MAX_CALLS',1)]:
            with self.subTest(limit=limit), tempfile.TemporaryFile() as channel, patch.object(cap, limit, value):
                recorder = cap.Recorder(channel.fileno(), 'a' * 64)
                calls = []
                async def original(*args, **kwargs):
                    calls.append(args[0])
                    return raw()
                for _ in range(3):
                    self.assertEqual(asyncio.run(recorder.wrap(original)(request['urls'])), raw())
                self.assertEqual(len(calls),3)
                self.assertTrue(recorder.disabled)
                recorder.complete()
                self.assertEqual(cap.read_capture(channel.fileno(), 'a' * 64), {})
        for urls in ([URL, 1], [{'href':URL}], [URL] * 6, ['x' * (cap.MAX_URL_LENGTH+1)], [(URL+'é'*3000)]*5):
            with self.subTest(urls=str(urls)[:80]), tempfile.TemporaryFile() as channel:
                recorder = cap.Recorder(channel.fileno(), 'a' * 64)
                async def original(*args, **kwargs):
                    self.assertIs(args[0],urls)
                    return raw()
                self.assertEqual(asyncio.run(recorder.wrap(original)(urls)),raw())
                self.assertEqual(recorder.calls, [])

    def test_strict_provider_declarations_and_untrusted_self_attestation(self):
        cap = capture_module()
        invalid = ['{"results":[],"results":[]}', '{"results":NaN}', raw(success=False), raw(status='error'),
                   raw(error=False), raw(error=[]), raw(blocked_by_policy=True),
                   raw([{'url':URL,'content':BODY,'error':0}]), raw([{'url':URL,'content':BODY,'status':'failed'}])]
        for result in invalid:
            with self.subTest(raw=result[:80]), tempfile.TemporaryFile() as channel:
                recorder = cap.Recorder(channel.fileno(), 'a' * 64)
                recorder.record({'urls':[URL],'format':'markdown','char_limit':6000},result)
                recorder.complete()
                self.assertEqual(cap.read_capture(channel.fileno(), 'a' * 64), {})
        requested = 'https://www.reuters.com/business/article-2026-10-18/'
        body = 'Oct 18 (Reuters) - ' + ('The company raised its revenue forecast. ' * 15)
        forged = raw([{'url':requested,'content':body,'location_provenance':'uncached_dispatch'}])
        for guarded in (False,True):
            with self.subTest(guarded=guarded), tempfile.TemporaryFile() as channel:
                recorder = cap.Recorder(channel.fileno(), 'a' * 64)
                recorder.guarded = guarded
                recorder.record({'urls':[requested],'format':'markdown','char_limit':6000},forged)
                recorder.complete()
                captures = cap.read_capture(channel.fileno(), 'a' * 64)
                with patch.object(radar,'is_safe_public_url',return_value=True):
                    page = radar.validate_structured_page(requested,captures[requested])
                self.assertEqual(bool(page['published_at']),guarded)

    def test_redirect_validation_and_selected_unrequested_redirect_normal_fetch(self):
        cap = capture_module()
        redirect = 'https://news.example/redirect'
        request = {'urls':[URL],'format':'markdown','char_limit':6000}
        for returned, expected in [(redirect,True), ('https://attacker.example/story',False), ('http://127.0.0.1/',False)]:
            with self.subTest(returned=returned), tempfile.TemporaryFile() as channel:
                recorder = cap.Recorder(channel.fileno(), 'a' * 64)
                recorder.record(request,raw([{'url':returned,'content':BODY}]))
                recorder.complete()
                captures = cap.read_capture(channel.fileno(), 'a' * 64)
                with patch.object(radar,'is_safe_public_url',side_effect=lambda u:'127.0.0.1' not in u):
                    page=radar.validate_structured_page(URL,captures[URL])
                self.assertEqual(page is not None,expected)
                if expected:
                    with patch.object(radar,'fetch_source',return_value={'url':redirect,'text':'normal'}) as direct:
                        self.assertEqual(radar.gather_evidence([redirect],focused_pages=captures),[{'url':redirect,'text':'normal'}])
                    direct.assert_called_once()

    def test_persistent_cache_time_and_result_order_unchanged(self):
        cap = capture_module()
        worker = importlib.import_module('extraction_worker')
        stamp = radar.dt.datetime.now(radar.dt.timezone.utc).isoformat()
        cached = {'url':URL,'text':'old immutable body','published_at':stamp}
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td)/'cache.json'
            cache.write_text(json.dumps({URL:{'checked_at':stamp,'page':cached}}))
            focused={OTHER:worker.project_row({'url':OTHER,'content':BODY})}
            with patch.object(radar,'is_safe_public_url',return_value=True), patch.object(radar,'fetch_source') as direct:
                pages=radar.gather_evidence([OTHER, URL, OTHER],cache_path=cache,focused_pages=focused)
            direct.assert_not_called()
            self.assertEqual([p['url'] for p in pages],[OTHER,URL])
            self.assertEqual(json.loads(cache.read_text())[URL],{'checked_at':stamp,'page':cached})
            self.assertNotIn(OTHER,json.loads(cache.read_text()))

    def test_receipt_check_time_is_preserved_not_replaced_by_gather_time(self):
        cap = capture_module()
        with tempfile.TemporaryFile() as channel:
            recorder = cap.Recorder(channel.fileno(), 'a' * 64)
            recorder.record({'urls':[URL], 'format':'markdown', 'char_limit':6000}, raw())
            stamp = recorder.calls[0]['checked_at']
            recorder.complete()
            captures = cap.read_capture(channel.fileno(), 'a' * 64)
        with patch.object(radar, 'is_safe_public_url', return_value=True), patch.object(radar, 'fetch_source') as direct:
            pages = radar.gather_evidence([URL], focused_pages=captures)
        self.assertEqual(pages[0].get('checked_at'), stamp)
        direct.assert_not_called()

    def test_focused_boundary_keeps_capture_map_separate_and_faults_fatal(self):
        cap = capture_module()
        choice = {'symbol':'AAA','urls':[URL]}
        done = subprocess.CompletedProcess([], 0, json.dumps({'candidates':[choice], 'focused_pages':{'forged':'body'}}), '')
        done.focused_pages = {URL: {'actual':'tool capture'}}
        with patch.object(cap, 'run_focused', return_value=done) as launch, patch.object(
            radar.subprocess, 'run', side_effect=AssertionError('unwrapped launch')
        ), patch.object(radar, 'focused_retrieval_command', return_value=['offline']):
            result = radar.focused_retrieval([{'symbol':'AAA'}])
            self.assertEqual(result, {'AAA':[URL]})
            self.assertEqual(result.focused_pages, done.focused_pages)
            self.assertNotIn('focused_pages', result)
            self.assertEqual(launch.call_args.kwargs['input'], radar.focused_retrieval_prompt([{'symbol':'AAA'}]))
            for fault, expected in ((subprocess.CompletedProcess([],1,'',''), 'research_focused_retrieval_unavailable'),
                                    (subprocess.TimeoutExpired('offline',1), 'research_focused_retrieval_timeout'),
                                    (OSError('offline'), 'research_focused_retrieval_unavailable')):
                launch.side_effect = fault if isinstance(fault, Exception) else None
                launch.return_value = fault
                with self.assertRaises(radar.ResearchFailure) as caught:
                    radar.focused_retrieval([{'symbol':'AAA'}])
                self.assertEqual(caught.exception.code, expected)
            launch.side_effect = None
            done.stdout = 'malformed final output'
            launch.return_value = done
            result = radar.focused_retrieval([{'symbol':'AAA'}])
            self.assertEqual(result, {})
            self.assertEqual(result.focused_pages, {})

    def test_live_merge_intersects_actual_selected_urls_before_reuse(self):
        cap = capture_module()
        worker = importlib.import_module('extraction_worker')
        unused = 'https://unused.example/never-selected'
        captures = {u:worker.project_row({'url':u,'content':BODY}) for u in (URL, OTHER, unused)}
        focused = cap.FocusedURLs({'AAA':[OTHER]}, captures)
        scout = subprocess.CompletedProcess([],0,json.dumps({'candidates':[{'symbol':'AAA','catalyst':'guidance raised',
                    'event_date':'2026-10-18','urls':[URL]}]}),'')
        with tempfile.TemporaryDirectory() as td, patch.object(radar, 'ROOT', Path(td)), patch.object(
            radar, 'discovery_command', return_value=['offline']
        ), patch.object(radar.subprocess, 'run', return_value=scout), patch.object(
            radar, 'focused_retrieval', return_value=focused
        ), patch.object(radar, 'is_safe_public_url', return_value=True), patch.object(
            radar, 'fetch_source', side_effect=AssertionError('unnecessary fetch')
        ) as direct, patch.object(radar, 'fetch_source_via_gateway', side_effect=AssertionError('unnecessary fallback')) as fallback, patch.object(
            radar, 'post_fetch_rescue_candidate', side_effect=AssertionError('already two publishers')
        ), patch.object(radar, 'synthesize_candidate', return_value={'status':'none'}) as synth:
            self.assertEqual(radar.live_research({'focused_retrieval_enabled':True,'max_position_usd':500})['status'], 'none')
            self.assertEqual({p['url'] for p in synth.call_args.args[2]}, {URL, OTHER})
            direct.assert_not_called()
            fallback.assert_not_called()

    def test_parent_channel_success_nonzero_timeout_and_cleanup(self):
        cap = capture_module()
        self.assertTrue(callable(getattr(cap, 'run_focused', None)), 'owned focused supervisor missing')
        script = '''
import os, sys, time
from focused_capture import Recorder, FD_ENV, NONCE_ENV
r=Recorder(int(os.environ[FD_ENV]), os.environ[NONCE_ENV])
r.record({'urls':['https://news.example/story'],'format':'markdown','char_limit':6000}, '{"results":[{"url":"https://news.example/story","content":"body"}]}')
r.complete()
print('final-output',flush=True)
if sys.argv[1]=='sleep': time.sleep(30)
sys.exit(int(sys.argv[1]) if sys.argv[1]!='sleep' else 0)
'''
        with tempfile.TemporaryDirectory() as td, patch.object(cap, 'focused_command', side_effect=lambda c:c), patch.dict(os.environ, {'TMPDIR':td}):
            # tempfile caches its root; pass the scratch root explicitly here.
            with patch.object(tempfile, 'tempdir', td):
                for code in ('0', '7'):
                    done = cap.run_focused([sys.executable, '-c', script, code], input='prompt', capture_output=True,
                                           text=True, timeout=5, cwd=Path(radar.__file__).parent)
                    self.assertEqual(done.stdout, 'final-output\n')
                    self.assertEqual(done.returncode, int(code))
                    self.assertEqual(len(done.focused_pages), 1 if code == '0' else 0)
                    self.assertEqual(list(Path(td).iterdir()), [])
                with self.assertRaises(subprocess.TimeoutExpired):
                    cap.run_focused([sys.executable, '-c', script, 'sleep'], input='prompt', capture_output=True,
                                    text=True, timeout=.2, cwd=Path(radar.__file__).parent)
                self.assertEqual(list(Path(td).iterdir()), [])
                with self.assertRaises(OSError):
                    cap.run_focused(['/missing-offline-executable'], input='', capture_output=True, text=True,
                                    timeout=1, cwd=Path(radar.__file__).parent)
                self.assertEqual(list(Path(td).iterdir()), [])

    def test_accepted_reuse_suppresses_both_fetches_and_never_seeds_cache(self):
        cap = capture_module()
        self.assertIn('focused_pages', __import__('inspect').signature(radar.gather_evidence).parameters,
                      'post-selection focused evidence reuse missing')
        with tempfile.TemporaryFile() as channel:
            recorder = cap.Recorder(channel.fileno(), 'a' * 64)
            recorder.record({'urls': [URL, OTHER], 'format': 'markdown', 'char_limit': 6000},
                            raw([{'url': URL, 'content': BODY}, {'url': OTHER, 'content': BODY}]))
            recorder.complete()
            captures = cap.read_capture(channel.fileno(), 'a' * 64)
        with tempfile.TemporaryDirectory() as td, patch.object(radar, 'is_safe_public_url', return_value=True), patch.object(
            radar, 'fetch_source', side_effect=AssertionError('no direct network')
        ) as direct, patch.object(radar, 'fetch_source_via_gateway', side_effect=AssertionError('no fallback')) as fallback:
            cache, attempts = Path(td) / 'cache.json', Path(td) / 'attempts.jsonl'
            pages = radar.gather_evidence([URL, URL], focused_pages=captures, cache_path=cache, attempt_path=attempts)
            self.assertEqual([p['url'] for p in pages], [URL])
            direct.assert_not_called()
            fallback.assert_not_called()
            self.assertNotIn(URL, json.loads(cache.read_text()))
            row = json.loads(attempts.read_text())
            self.assertEqual(row['direct_reason'], 'focused_reuse_hit')
            self.assertFalse(row['network_attempted'])
            self.assertNotIn(URL, attempts.read_text())

    def test_rejected_reuse_uses_normal_selected_fetch_once(self):
        self.assertIn('focused_pages', __import__('inspect').signature(radar.gather_evidence).parameters,
                      'post-selection focused evidence reuse missing')
        worker = importlib.import_module('extraction_worker')
        cases = [BODY.replace('2026-10-18', '2024-01-01'), BODY.replace('2026-10-18', '2028-01-01'),
                 'Undated ' * 70, 'short', '<p>Access denied</p>' + BODY]
        for body in cases:
            receipt = worker.project_row({'url': URL, 'content': body})
            expected = {'url': URL, 'text': 'normal direct'}
            with self.subTest(body=body[:80]), patch.object(radar, 'is_safe_public_url', return_value=True), patch.object(
                radar, 'fetch_source', return_value=expected
            ) as direct, patch.object(radar, 'fetch_source_via_gateway') as fallback:
                self.assertEqual(radar.gather_evidence([URL, URL], focused_pages={URL: receipt}), [expected])
                direct.assert_called_once()
                fallback.assert_not_called()

    def test_installed_runtime_registry_hook_and_lifetime_guard(self):
        cap = capture_module()
        self.assertTrue(callable(getattr(cap, 'focused_command', None)), 'focused runtime wrapper missing')
        command = cap.focused_command(['hermes', 'chat', '-Q', '--max-turns', '4'])
        # Execute the real bootstrap and wrapper with only the public CLI main
        # replaced. The installed async registry lambda and guard are real.
        prefix = command[3].split('runpy.run_path(')[0]
        probe = r'''
import asyncio, os, sys
from unittest.mock import patch
import hermes_cli.main as cli
import tools.web_tools as web
import tools.web_result_cache as cache
from tools.registry import registry
import focused_wrapper as wrapper
import focused_capture as cap
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import extraction_worker as worker
original_cache = cache.extract_cache_get
real_guard = worker.final_location_cache_guard
guards = []
@contextmanager
def counted_guard():
    guards.append('enter')
    try:
        with real_guard(): yield
    finally:
        guards.append('exit')
original_calls = []
responses = ['{"results":[{"url":"https://news.example/%s","content":"body"}]}' % i for i in range(3)]
async def original(*args, **kwargs):
    original_calls.append((args,kwargs))
    guard = cache.extract_cache_get
    assert guard is not original_cache
    assert guard('https://www.reuters.com/article') is None
    assert guard('https://other.example/article') == 'ordinary-cache'
    await asyncio.sleep(0.001)
    assert cache.extract_cache_get is guard
    return responses[int(args[0][0].rsplit('/',1)[1])]
def main():
    assert cap.FD_ENV not in os.environ and cap.NONCE_ENV not in os.environ
    assert sys.argv[1:] == ['chat','-Q','--max-turns','4']
    with ThreadPoolExecutor(max_workers=3) as pool:
        got = list(pool.map(lambda i:registry.dispatch('web_extract', {'urls':['https://news.example/%s' % i], 'char_limit':6000}),range(3)))
    assert all(got[i] is responses[i] for i in range(3))
    assert len(original_calls) == 3
    assert all(a[1] == 'markdown' and kw == {'char_limit':6000} for a,kw in original_calls)
    print('{"candidates":[]}')
with patch.object(cache,'extract_cache_get',return_value='ordinary-cache') as normal_cache:
    original_cache = normal_cache
    with patch.object(web, 'web_extract_tool', original), patch.object(cli, 'main', main), patch.object(worker,'final_location_cache_guard',counted_guard):
        wrapper.main()
        assert web.web_extract_tool is original
        assert cache.extract_cache_get is original_cache
        assert guards == ['enter','exit']
    assert normal_cache.call_count == 3
'''
        with tempfile.TemporaryFile() as channel:
            env = dict(os.environ, **{cap.FD_ENV: str(channel.fileno()), cap.NONCE_ENV: 'b' * 64})
            result = subprocess.run(command[:3] + [prefix + probe] + command[4:], env=env,
                                    pass_fds=(channel.fileno(),), capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr[-4000:])
            self.assertEqual(result.stdout.strip(), '{"candidates":[]}')
            self.assertEqual(len(cap.read_capture(channel.fileno(), 'b' * 64)), 3)

    def test_batch_binding_uses_exact_request_not_position_or_publisher(self):
        cap = capture_module()
        row = lambda u: {'url': u, 'content': BODY}
        cases = [
            ([URL, OTHER], [row(OTHER), row(URL)], {URL, OTHER}),
            ([URL, OTHER], [row(OTHER)], {OTHER}),
            ([URL, OTHER], [row(URL), row(URL), row(OTHER)], {OTHER}),
            ([URL, OTHER], [row('https://news.example/redirect')], set()),
            ([URL], [row('https://news.example/redirect')], {URL}),
            ([URL, URL], [row(URL)], set()),
        ]
        for requested, rows, expected in cases:
            with self.subTest(requested=requested, rows=rows), tempfile.TemporaryFile() as channel:
                recorder = cap.Recorder(channel.fileno(), 'a' * 64)
                recorder.guarded = True
                recorder.record({'urls': requested, 'format': 'markdown', 'char_limit': 6000}, raw(rows))
                recorder.complete()
                result = cap.read_capture(channel.fileno(), 'a' * 64)
                self.assertEqual(set(result), expected)
                for u, receipt in result.items():
                    self.assertEqual(receipt['version'], 1)
                    self.assertEqual(receipt['page']['location_provenance'], 'uncached_dispatch')
                    self.assertNotIn('checked_at', receipt['page'])

    def test_original_response_identity_parallel_capture_completion(self):
        cap = capture_module()
        calls = []
        result = raw()
        async def original(*args, **kwargs):
            calls.append((args, kwargs))
            await asyncio.sleep(0)
            return result
        with tempfile.TemporaryFile() as channel:
            recorder = cap.Recorder(channel.fileno(), 'a' * 64)
            wrapped = recorder.wrap(original)
            args = [URL]
            async def parallel():
                return await asyncio.gather(*(wrapped(args, 'markdown', char_limit=6000) for _ in range(3)))
            values = asyncio.run(parallel())
            self.assertTrue(all(v is result for v in values))
            self.assertTrue(all(c[0][0] is args and c[0][1] == 'markdown' and c[1] == {'char_limit': 6000} for c in calls))
            self.assertEqual(len(calls), 3)
            self.assertEqual(cap.read_capture(channel.fileno(), 'a' * 64), {})
            recorder.complete()
            # Duplicate invocations for an exact URL are conservatively ambiguous.
            self.assertEqual(cap.read_capture(channel.fileno(), 'a' * 64), {})
            channel.seek(0)
            artifact = json.load(channel)
            self.assertEqual(len(artifact['calls']), 3)
            self.assertTrue(artifact['complete'])
            self.assertEqual([c['raw'] for c in artifact['calls']], [result] * 3)


if __name__ == '__main__':
    unittest.main()
