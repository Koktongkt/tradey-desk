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
    def test_focused_contract_bounds_historical_limits_and_restores_schema(self):
        # Catch retained stock schemas and pre-network refusals of historical
        # 10k-18k requests. Keep real registry, dispatcher, projection and receipts;
        # replace only CLI/model startup and provider/network boundaries.
        cap = capture_module()
        command = cap.focused_command(['hermes', 'chat'])
        prefix = command[3].split('runpy.run_path(')[0]
        probe = r'''
import asyncio, json, logging, os
from contextlib import ExitStack
from unittest.mock import patch, AsyncMock
import hermes_cli.main as cli
import tools.web_tools as web
from tools.registry import registry
import focused_wrapper as wrapper
import extraction_compat as compat
import focused_capture as cap
entry = registry.get_entry('web_extract')
stock_schema, stock_handler = entry.schema, entry.handler
stock_copy = json.loads(json.dumps(stock_schema))
class Provider:
    name = 'fixture'
seen, events = [], []
class Events(logging.Handler):
    def emit(self, record): events.append(record.getMessage())
handler = Events()
logging.getLogger('focused_wrapper').addHandler(handler)
async def primary(provider, urls, **kwargs):
    seen.extend(urls)
    return [{'url': u, 'title': 'Bounded release', 'content': 'Company revenue increased. ' * 600} for u in urls]
def main():
    schema = registry.get_schema('web_extract')
    limits = schema['parameters']['properties']['char_limit']
    assert limits.get('minimum') == 2000, limits
    assert limits.get('maximum') == 6000, limits
    assert limits.get('default') == 6000, limits
    assert schema['parameters']['properties']['urls']['maxItems'] == 5
    assert '15000' not in json.dumps(schema) and '15,000' not in json.dumps(schema)
    assert 'not stored' in schema['description'].lower(), schema
    for value, want in [(None, 6000), (2000, 2000), (6000, 6000),
                        (10000, 6000), (12000, 6000), (14000, 6000),
                        (15000, 6000), (16000, 6000), (18000, 6000)]:
        url = 'https://news.example/limit-' + str(value)
        args = {'urls': [url]}
        if value is not None: args['char_limit'] = value
        row = json.loads(registry.dispatch('web_extract', args))['results'][0]
        assert row['error'] is None, (value, row)
        assert row['url'] == url and len(row['content']) <= want, (value, row)
        assert row['content'].startswith('Company revenue increased.'), row
    assert len(seen) == 9, seen
    assert len(events) == 6, events
    assert all('focused_extract_limit_capped' in e and 'https://' not in e for e in events), events
    # Wrong types and lower bounds are not silently repaired. Dispatcher remains
    # strict even for upper limits when bypassing this wrapper.
    for value in [True, False, '6000', 6000.0, 1999, 0, -1]:
        row = json.loads(registry.dispatch('web_extract', {'urls':['https://news.example/bad'], 'char_limit':value}))['results'][0]
        assert row['reason'] == 'invalid_request', (value, row)
    import research_extraction as project
    row = json.loads(asyncio.run(project.extract_tool(['https://news.example/strict'], char_limit=18000)))['results'][0]
    assert row['reason'] == 'invalid_request', row
    assert len(seen) == 9, seen
    # Exercise real URL admission: a cap cannot authorize an unsafe URL.
    with patch.object(compat, 'check_url', AsyncMock(side_effect=compat.CompatibilityError('unsafe_url'))):
        row = json.loads(registry.dispatch('web_extract', {'urls':['http://127.0.0.1/private'], 'char_limit':18000}))['results'][0]
        assert row['reason'] == 'unsafe_url' and row['url'] == '', row
    assert len(seen) == 9, seen
    print('focused-contract-ok')
with ExitStack() as stack:
    stack.enter_context(patch.object(cli, 'main', main))
    stack.enter_context(patch.object(compat, 'check_url', AsyncMock(side_effect=lambda u:u)))
    stack.enter_context(patch.object(compat, 'resolve', return_value=Provider()))
    stack.enter_context(patch.object(compat, 'uses_keyless', return_value=False))
    stack.enter_context(patch.object(compat, 'primary', primary))
    try: wrapper.main()
    finally:
        assert entry.schema is stock_schema and entry.schema == stock_copy
        assert entry.handler is stock_handler
logging.getLogger('focused_wrapper').removeHandler(handler)
'''
        done = subprocess.run(command[:3]+[prefix+probe]+command[4:], text=True,
                              capture_output=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr[-6000:])
        self.assertEqual(done.stdout.strip(), 'focused-contract-ok')

    def test_registered_extract_uses_project_and_records_receipt(self):
        cap = capture_module()
        command = cap.focused_command(['hermes', 'chat'])
        prefix = command[3].split('runpy.run_path(')[0]
        probe = r'''
import asyncio, os, subprocess, sys
from unittest.mock import patch, AsyncMock
from contextlib import ExitStack
import hermes_cli.main as cli
import tools.web_tools as web
import tools.web_result_cache as cache
from tools.registry import registry
import focused_wrapper as wrapper
import research_extraction as project
import extraction_compat as compat
import focused_capture as cap
original = registry.get_entry('web_extract').handler
# A stored reference must work too, not only today's module-global lambda.
async def stock(args, **kw): raise AssertionError('stock handler called')
registry.get_entry('web_extract').handler = stock
class Provider:
    name='fixture'
async def primary(provider, urls, **kw):
    return [{'url': urls[0], 'title': 'Project receipt', 'content': 'Verified factual body ' * 30}]
def main():
    assert cap.FD_ENV not in os.environ and cap.NONCE_ENV not in os.environ
    child = subprocess.check_output([sys.executable, '-c', 'import os; print(dict(os.environ))'], text=True)
    assert 'TRADEY_FOCUSED_CAPTURE' not in child
    got = registry.dispatch('web_extract', {'urls':['https://news.example/story'], 'char_limit':18000})
    assert __import__('json').loads(got)['results'][0]['title'] == 'Project receipt', got
    print('registry-project-ok')
with ExitStack() as stack:
    stack.enter_context(patch.object(cli, 'main', main))
    stack.enter_context(patch.object(web, 'web_extract_tool', side_effect=AssertionError('stock')))
    stack.enter_context(patch.object(cache, 'extract_cache_get', side_effect=AssertionError('cache read')))
    stack.enter_context(patch.object(cache, 'extract_cache_put', side_effect=AssertionError('cache write')))
    stack.enter_context(patch.object(compat, 'check_url', AsyncMock(side_effect=lambda u:u)))
    stack.enter_context(patch.object(compat, 'resolve', return_value=Provider()))
    stack.enter_context(patch.object(compat, 'uses_keyless', return_value=False))
    stack.enter_context(patch.object(compat, 'primary', primary))
    wrapper.main()
    assert registry.get_entry('web_extract').handler is stock
registry.get_entry('web_extract').handler = original
'''
        with tempfile.TemporaryFile() as channel:
            env = dict(os.environ, **{cap.FD_ENV:str(channel.fileno()), cap.NONCE_ENV:'b'*64})
            done = subprocess.run(command[:3]+[prefix+probe]+command[4:], env=env,
                                  pass_fds=(channel.fileno(),), text=True, capture_output=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr[-4000:])
            self.assertEqual(done.stdout, 'registry-project-ok\n')
            self.assertNotIn('b'*64, done.stdout + done.stderr)
            receipt = json.loads(os.pread(channel.fileno(), 100000, 0))
            self.assertEqual(receipt['calls'][0]['request']['char_limit'], 6000)
            pages = cap.read_capture(channel.fileno(), 'b'*64)
            self.assertEqual(pages[URL]['page']['title'], 'Project receipt')
            self.assertEqual(pages[URL]['page']['location_provenance'], 'uncached_dispatch')

    def test_over_cap_returned_row_count_is_not_reusable(self):
        cap=capture_module()
        rows=[{'url':URL,'content':BODY}]+[{'url':f'https://unrequested.example/{i}','content':'body'} for i in range(5)]
        with tempfile.TemporaryFile() as channel:
            recorder=cap.Recorder(channel.fileno(),'a'*64)
            recorder.record({'urls':[URL],'format':'markdown','char_limit':6000},raw(rows))
            recorder.complete()
            self.assertEqual(cap.read_capture(channel.fileno(),'a'*64),{})

    def test_focused_parent_bounds_pipes_and_input(self):
        cap = capture_module()
        with patch.object(cap, 'focused_command', side_effect=lambda c:c):
            for stream, size in [('stdout', 100001), ('stderr', 16385)]:
                script = f'import sys; sys.{stream}.write("x"*{size}); sys.{stream}.flush()'
                with self.subTest(stream=stream), self.assertRaises(OSError):
                    cap.run_focused([sys.executable, '-c', script], input='', capture_output=True,
                                    text=True, timeout=3, cwd=Path(radar.__file__).parent)
            with self.assertRaises(OSError):
                cap.run_focused([sys.executable, '-c', 'print("no")'], input='x'*8193,
                                capture_output=True, text=True, timeout=3, cwd=Path(radar.__file__).parent)

    def test_input_backpressure_keeps_hard_deadline_and_kills_owned_group(self):
        from task4_probe import assert_dead
        from time import monotonic
        cap = capture_module()
        script = '''
import json, os, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
Path(sys.argv[1]).write_text(json.dumps([os.getpid(), child.pid]))
time.sleep(1)
'''
        launch = subprocess.Popen
        with tempfile.TemporaryDirectory() as td, patch.object(cap, 'focused_command', side_effect=lambda c:c), patch.object(
            subprocess, 'Popen', side_effect=lambda *a, **kw:launch(*a, **dict(kw, pipesize=4096))
        ):
            pidfile = Path(td)/'pids'
            started = monotonic()
            caught = None
            try:
                cap.run_focused([sys.executable, '-c', script, str(pidfile)], input='x'*8192,
                                capture_output=True, text=True, timeout=.2, cwd=td)
            except Exception as error:
                caught = error
            elapsed = monotonic() - started
            assert_dead(self, pidfile)
            self.assertIsInstance(caught, subprocess.TimeoutExpired, f'{caught!r}, elapsed={elapsed:.3f}')
            self.assertEqual(caught.timeout, .2)
            self.assertLess(elapsed, .8, 'stdin backpressure escaped the parent deadline')

    def test_input_backpressure_still_monitors_both_output_caps(self):
        from time import monotonic
        cap = capture_module()
        launch = subprocess.Popen
        with patch.object(cap, 'focused_command', side_effect=lambda c:c), patch.object(
            subprocess, 'Popen', side_effect=lambda *a, **kw:launch(*a, **dict(kw, pipesize=4096))
        ):
            for stream, size in [('stdout', 100001), ('stderr', 16385)]:
                script = f'import signal, sys, time; signal.alarm(1); sys.{stream}.write("x"*{size}); sys.{stream}.flush(); time.sleep(1)'
                with self.subTest(stream=stream):
                    started = monotonic()
                    with self.assertRaisesRegex(OSError, 'focused output limit'):
                        cap.run_focused([sys.executable, '-c', script], input=b'x'*8192,
                                        capture_output=True, text=False, timeout=.5, cwd=Path(radar.__file__).parent)
                    self.assertLess(monotonic() - started, .8)

    def test_oversized_encoded_input_is_rejected_before_spawn(self):
        cap = capture_module()
        with patch.object(cap, 'focused_command', side_effect=lambda c:c), patch.object(
            subprocess, 'Popen', side_effect=OSError('spawn forbidden')
        ) as launch:
            for value in ('x'*8193, 'é'*4097, b'x'*8193):
                with self.subTest(kind=type(value).__name__), self.assertRaisesRegex(OSError, 'focused input limit'):
                    cap.run_focused(['offline'], input=value, capture_output=True, text=True,
                                    timeout=1, cwd=Path(radar.__file__).parent)
            self.assertEqual(launch.call_count, 0, 'oversized input must not spawn')

    def test_multiplexed_input_delivers_all_bytes_and_eof_without_changing_output(self):
        cap = capture_module()
        launch = subprocess.Popen
        script = '''
import signal, sys
signal.alarm(1)  # Bound the intentionally deadlocking pre-fix implementation.
sys.stdout.buffer.write(b'o'*8192); sys.stdout.buffer.flush()
sys.stderr.buffer.write(b'e'*8192); sys.stderr.buffer.flush()
sys.stdout.buffer.write(sys.stdin.buffer.read()); sys.stdout.buffer.flush()
'''
        with patch.object(cap, 'focused_command', side_effect=lambda c:c), patch.object(
            subprocess, 'Popen', side_effect=lambda *a, **kw:launch(*a, **dict(kw, pipesize=4096))
        ):
            for text, payload in [(True, 'é'*4096), (False, b'x'*8192)]:
                with self.subTest(text=text):
                    done = cap.run_focused([sys.executable, '-c', script], input=payload,
                                           capture_output=True, text=text, timeout=.5, cwd=Path(radar.__file__).parent)
                    self.assertEqual(done.returncode, 0)
                    self.assertEqual(done.stdout, ('o'*8192 if text else b'o'*8192) + payload)
                    self.assertEqual(done.stderr, 'e'*8192 if text else b'e'*8192)

    def test_early_stdin_close_does_not_bypass_remaining_deadline(self):
        cap = capture_module()
        launch = subprocess.Popen
        script = 'import os, time; os.close(0); time.sleep(1)'
        with patch.object(cap, 'focused_command', side_effect=lambda c:c), patch.object(
            subprocess, 'Popen', side_effect=lambda *a, **kw:launch(*a, **dict(kw, pipesize=4096))
        ), self.assertRaises(subprocess.TimeoutExpired):
            cap.run_focused([sys.executable, '-c', script], input='x'*8192,
                            capture_output=True, text=True, timeout=.2, cwd=Path(radar.__file__).parent)

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
import research_extraction as project
from tools.registry import registry
import focused_capture as cap
async def original(*a,**kw):
    return '{"results":[{"url":"https://news.example/story","content":"article"}]}'
for fault, wanted in [(None,True),(SystemExit(0),True),(SystemExit(7),False),(RuntimeError('offline'),False)]:
    with tempfile.TemporaryFile() as channel:
        os.environ[cap.FD_ENV]=str(channel.fileno())
        os.environ[cap.NONCE_ENV]='a'*64
        old_cache=cache.extract_cache_get
        old_handler=registry.get_entry('web_extract').handler
        old_schema=registry.get_entry('web_extract').schema
        def main():
            assert registry.get_schema('web_extract')['parameters']['properties']['char_limit']['maximum']==6000
            registry.dispatch('web_extract', {'urls':['https://news.example/story']})
            if fault is not None:raise fault
        with patch.object(project,'extract_tool',original), patch.object(cli,'main',main):
            try:wrapper.main()
            except (RuntimeError,SystemExit) as got:assert got is fault
            assert registry.get_entry('web_extract').handler is old_handler
            assert registry.get_entry('web_extract').schema is old_schema
            assert cache.extract_cache_get is old_cache
            assert bool(cap.read_capture(channel.fileno(),'a'*64)) is wanted
print('wrapper-exit-semantics-ok')
'''
        done = subprocess.run(command[:3]+[prefix+probe]+command[4:],capture_output=True,text=True,timeout=30)
        self.assertEqual(done.returncode,0,done.stderr[-4000:])
        self.assertEqual(done.stdout.strip(),'wrapper-exit-semantics-ok')

    def test_real_focused_parent_kills_blocked_provider_and_dns_executor(self):
        from task4_probe import blocked_probe, assert_dead
        cap = capture_module()
        command = cap.focused_command(['hermes', 'chat'])
        prefix = command[3].split('runpy.run_path(')[0]
        with tempfile.TemporaryDirectory() as td:
            sentinel = Path(td)/'operational.json'
            sentinel.write_text('{"paper":true}')
            for mode in ('provider', 'dns'):
                pidfile = Path(td)/mode
                # Slow real bootstrap is outside the measured worker phase.
                # Popen below transfers this exact owned group to the supervisor;
                # it still performs the hard timeout, kill, wait and pipe cleanup.
                import time, signal
                ready, go = Path(td)/(mode+'-ready'), Path(td)/(mode+'-go')
                body = blocked_probe(pidfile, mode, focused=True)
                handshake = (f"    Path({str(ready)!r}).write_text(str(os.getpid()))\n"
                             f"    while not Path({str(go)!r}).exists(): time.sleep(.01)\n")
                body = body.replace('    wrapper.main()\n', handshake+'    wrapper.main()\n')
                probe = command[:3]+[prefix+'import time; time.sleep(2.2)\n'+body]
                process = subprocess.Popen(probe, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, bufsize=0, start_new_session=True, cwd=td)
                try:
                    until = time.monotonic()+20
                    while not ready.exists() and process.poll() is None and time.monotonic()<until:
                        time.sleep(.01)
                    self.assertTrue(ready.exists(), 'real bootstrap did not become ready')
                    self.assertEqual(int(ready.read_text()), process.pid)
                    def adopt(*args, **kwargs):
                        go.write_text('start')
                        return process
                    with patch.object(cap, 'focused_command', return_value=probe), \
                         patch.object(subprocess, 'Popen', side_effect=adopt):
                        with self.assertRaises(subprocess.TimeoutExpired):
                            cap.run_focused(['hermes','chat'], input='', capture_output=True, text=True, timeout=2, cwd=td)
                    assert_dead(self, pidfile)
                finally:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait()
                    for stream in (process.stdin, process.stdout, process.stderr): stream.close()
                self.assertEqual(sentinel.read_text(), '{"paper":true}')

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

    def test_explicit_original_alias_returned_bindings_do_not_cross_associate(self):
        cap = capture_module()
        alias = 'https://news.example/normalized'
        redirected = 'https://news.example/returned'
        def row(requested, returned):
            return {'url':returned, 'content':BODY, 'extraction_location':{
                'version':1, 'requested_url':requested, 'returned_url':returned}}
        for rows, expected in [
            ([row(URL, redirected), row(OTHER, OTHER)], {URL, OTHER}),
            ([row(alias, redirected), row(OTHER, OTHER)], set()),
            ([row(OTHER, URL), row(URL, OTHER)], set()),
            ([row(URL, redirected), row(URL, alias)], set()),
        ]:
            with self.subTest(rows=rows), tempfile.TemporaryFile() as channel:
                recorder = cap.Recorder(channel.fileno(), 'a'*64)
                recorder.guarded = True
                recorder.record({'urls':[URL,OTHER], 'format':'markdown', 'char_limit':6000}, raw(rows))
                recorder.complete()
                self.assertEqual(set(cap.read_capture(channel.fileno(), 'a'*64)), expected)

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
        from focused_fixture import search_done, validation_done
        import focused_pipeline
        worker=importlib.import_module('extraction_worker')
        done=search_done({'candidates':[{'symbol':'AAA','urls':[URL]}]},attested=[URL])
        def batch(urls, **kwargs):
            return {'version':2,'status':'ok','results':[{'requested_url':u,
                'result':worker.project_row({'url':u,'content':BODY})} for u in urls]}
        with patch('focused_capture.run_private_child',return_value=done) as launch, patch.object(
            focused_pipeline,'run_validation_worker',side_effect=validation_done
        ), patch.object(focused_pipeline,'run_batch_worker',side_effect=batch), patch.object(
            radar.subprocess,'run',side_effect=AssertionError('unwrapped launch')
        ), patch.object(radar,'focused_retrieval_command',return_value=['offline']):
            result=radar.focused_retrieval([{'symbol':'AAA'}])
            self.assertEqual(result,{'AAA':[URL]})
            self.assertEqual(result.focused_pages[URL]['page']['text'],BODY)
            self.assertNotIn('focused_pages',result)
            self.assertEqual(launch.call_args.kwargs['input'],radar.focused_retrieval_prompt([{'symbol':'AAA'}]))
            for fault,expected in ((subprocess.CompletedProcess([],1,b'',b''),'research_focused_retrieval_unavailable'),
                                   (subprocess.TimeoutExpired('offline',1),'research_focused_retrieval_timeout'),
                                   (OSError('offline'),'research_focused_retrieval_unavailable')):
                launch.side_effect=fault if isinstance(fault,Exception) else None
                launch.return_value=fault
                with self.assertRaises(radar.ResearchFailure) as caught:radar.focused_retrieval([{'symbol':'AAA'}])
                self.assertEqual(caught.exception.code,expected)
            launch.side_effect=None
            for stdout in (b'malformed final output',json.dumps({'candidates':[], 'focused_pages':{'forged':'body'}}).encode()):
                done.stdout=stdout
                launch.return_value=done
                with self.assertRaises(radar.ResearchFailure) as caught:radar.focused_retrieval([{'symbol':'AAA'}])
                self.assertEqual(caught.exception.code,'research_focused_retrieval_unavailable')

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
import research_extraction as project
original_cache = cache.extract_cache_get
original_handler = registry.get_entry('web_extract').handler
original_calls = []
responses = ['{"results":[{"url":"https://news.example/%s","content":"body"}]}' % i for i in range(3)]
async def original(*args, **kwargs):
    original_calls.append((args,kwargs))
    assert cache.extract_cache_get is original_cache
    await asyncio.sleep(0.001)
    assert cache.extract_cache_get is original_cache
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
with patch.object(cache,'extract_cache_get',side_effect=AssertionError('cache read')) as normal_cache:
    original_cache = normal_cache
    with patch.object(project, 'extract_tool', original), patch.object(cli, 'main', main):
        wrapper.main()
        assert registry.get_entry('web_extract').handler is original_handler
        assert cache.extract_cache_get is original_cache
    assert normal_cache.call_count == 0
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
