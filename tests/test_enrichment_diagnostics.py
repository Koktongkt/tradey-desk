"""Offline private enrichment tracing contracts."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import alpha_radar as a
import earnings_calendar as e


class EnrichmentDiagnosticsTests(unittest.TestCase):
    def synthesize(self, root, enabled=True, error=None):
        from contextlib import nullcontext
        candidate = {'symbol': 'AAPL', 'sources': []}
        with patch.object(a, 'ROOT', root), patch.object(a, 'synthesis_command', return_value=['fake']), patch.object(a.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(candidate))), patch.object(a, 'default_trusted_date_loader', return_value=None), patch.object(e, 'DEFAULT_CACHE_PATH', root/'cache.json'), patch.object(e, 'cached_sec_release_history', return_value=[]), patch.object(a, 'synchronized_completed_close_prices', side_effect=error, return_value={'price': 1, 'spy_price': 2}), (a.enable_timing() if enabled else nullcontext()):
            return a.synthesize_candidate(json.loads((Path(a.__file__).parent/'autonomy_config.json').read_text()), candidate, [], time.monotonic()+120)

    def test_real_orchestration_trace_and_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.synthesize(root, False)['price'], 1)
            self.assertFalse((root/'private').exists())
            self.assertEqual(self.synthesize(root)['price'], 1)
            rows = [json.loads(x) for x in (root/'private/enrichment_diagnostics.jsonl').read_text().splitlines()]
            self.assertEqual({r['operation'] for r in rows}, {'trusted_date', 'sec_history', 'prices', 'attempt'})
            self.assertEqual(len({r['attempt_id'] for r in rows}), 1)
            self.assertTrue(all(r['symbol']=='AAPL' for r in rows))
            self.assertEqual(rows[-1]['outcome'], 'completed')
            self.assertEqual((root/'private/enrichment_diagnostics.jsonl').stat().st_mode & 0o777, 0o600)

    def test_real_http_config_body_parse_and_cache_seams(self):
        import datetime as dt
        import market_data as m
        import enrichment_diagnostics as d
        import io
        from research_budget import ResearchDeadlineExceeded
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            class Response(io.BytesIO):
                def __enter__(self): return self
                def __exit__(self, *args): pass
            def rows():
                return [json.loads(x) for x in (root/'private/enrichment_diagnostics.jsonl').read_text().splitlines()]
            with d.attempt(True, root, 'a'*32, 'AAPL'):
                with patch.object(m, 'read_mcp_env_process', return_value=SimpleNamespace(returncode=0, stdout='{"MASSIVE_API_KEY":"secret"}')) as config, patch.object(m.urllib.request, 'urlopen', side_effect=lambda *args, **kw: Response(b'{"status":"OK"}')) as opened:
                    self.assertEqual(m._massive_json('https://example.invalid/?token=secret'), {'status':'OK'})
                    self.assertEqual(config.call_count, 1)
                    self.assertEqual(opened.call_count, 1)
                now = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
                calls=[]
                loader=lambda symbol: calls.append(symbol) or []
                self.assertEqual(e.cached_sec_release_history('AAPL', cache_path=root/'cache.json', now=now, history_loader=loader), [])
                self.assertEqual(e.cached_sec_release_history('AAPL', cache_path=root/'cache.json', now=now, history_loader=loader), [])
                self.assertEqual(calls, ['AAPL'])
            trace = rows()
            self.assertTrue({'config', 'open', 'body', 'json', 'cache'} <= {r['operation'] for r in trace})
            self.assertEqual([r['cache_reason'] for r in trace if r['operation']=='cache'], ['absent','cachehit'])
            self.assertNotIn('secret', json.dumps(trace))

    def test_earnings_real_transport_seams(self):
        import enrichment_diagnostics as d
        import io
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with d.attempt(True, root, 'a'*32, 'AAPL'), patch.object(e.urllib.request, 'urlopen', side_effect=lambda *args, **kwargs: io.BytesIO(b'{"ok":true}')):
                self.assertEqual(e._get_json('https://www.sec.gov/files/company_tickers.json'), {'ok':True})
                self.assertEqual(e._get_text('https://stockanalysis.com/stocks/aapl/'), '{"ok":true}')
            rows=[json.loads(x) for x in (root/'private/enrichment_diagnostics.jsonl').read_text().splitlines()]
            self.assertEqual([(r['provider'],r['operation']) for r in rows], [('sec','open'),('sec','body'),('sec','json'),('stockanalysis','open'),('stockanalysis','body'),('local','attempt')])

    def test_noisy_telemetry_does_not_replace_success_or_original_exception(self):
        import enrichment_diagnostics as d
        error=ValueError('https://secret.invalid/?apiKey=PRIVATE /secret/path')
        for hook in ('_emit', '_append'):
            with self.subTest(hook=hook), tempfile.TemporaryDirectory() as tmp, patch.object(d, hook, side_effect=RuntimeError('telemetry unavailable')):
                self.assertEqual(self.synthesize(Path(tmp))['price'], 1)
                with self.assertRaises(a.ResearchFailure) as caught:
                    self.synthesize(Path(tmp), error=error)
                self.assertIs(caught.exception.__cause__, error)
                self.assertEqual(caught.exception.code, 'research_market_data_unavailable')

    def test_typed_transport_failures_identity_and_privacy(self):
        import enrichment_diagnostics as d
        import market_data as m
        import io
        import urllib.error
        from email.message import Message
        from research_budget import ResearchDeadlineExceeded, active_deadline
        cases=[('config', RuntimeError('SECRET /private/key'), 'config_error'), ('open', urllib.error.HTTPError('https://x/?key=SECRET',403,'SECRET',Message(),None),'open_error'), ('body', OSError('SECRET'),'body_error'), ('json', ValueError('SECRET'),'parse_error'), ('body', ResearchDeadlineExceeded('SECRET unsupported reader'),'cancelled'), ('open', TimeoutError('SECRET'),'timeout')]
        for operation,error,outcome in cases:
            with self.subTest(operation=operation,outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                config=SimpleNamespace(returncode=0,stdout='{"MASSIVE_API_KEY":"SECRET"}')
                with d.attempt(True,root,'b'*32,'AAPL'), patch.object(m,'read_mcp_env_process',side_effect=error if operation=='config' else None,return_value=config), patch.object(m.urllib.request,'urlopen',side_effect=error if operation=='open' else None,return_value=io.BytesIO(b'{}')), patch.object(m,'read_http_response',side_effect=error if operation=='body' else None,return_value=b'{}'), patch.object(m.json,'loads',side_effect=lambda raw: (_ for _ in ()).throw(error) if operation=='json' and raw==b'{}' else json.JSONDecoder().decode(raw)):
                    with self.assertRaises(BaseException) as caught:
                        m._massive_json('https://example.invalid/?key=SECRET')
                    self.assertIs(caught.exception,error)
                text=(root/'private/enrichment_diagnostics.jsonl').read_text()
                rows=[json.loads(x) for x in text.splitlines()]
                record=next(r for r in rows if r['operation']==operation)
                self.assertEqual(record['outcome'],outcome)
                if operation=='open' and outcome=='open_error': self.assertEqual(record['http_status'],403)
                self.assertNotIn('SECRET',text)
                self.assertNotIn('https:',text)

    def test_hostile_exception_attributes_preserve_identity(self):
        import enrichment_diagnostics as d
        class Hostile(Exception):
            @property
            def reason(self): raise RuntimeError('unsafe attribute')
        error=Hostile('PRIVATE')
        with tempfile.TemporaryDirectory() as tmp, d.attempt(True,Path(tmp),'a'*32,'AAPL'):
            with self.assertRaises(Hostile) as caught:
                with d.span('body','sec'):
                    raise error
            self.assertIs(caught.exception,error)

    def test_context_reset_nested_concurrent_and_cancel(self):
        import enrichment_diagnostics as d
        import asyncio
        from research_budget import ResearchDeadlineExceeded, active_deadline
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            async def worker(symbol):
                with d.attempt(True,root,'c'*32,symbol):
                    await asyncio.sleep(0)
                    with d.span('body','sec'): pass
            async def run(): await asyncio.gather(worker('AAPL'),worker('MSFT'))
            asyncio.run(run())
            error=ResearchDeadlineExceeded('no raw message')
            with d.attempt(True,root,'d'*32,'AAPL'):
                outer=d._active.get()
                with self.assertRaises(ResearchDeadlineExceeded) as caught:
                    with d.attempt(True,root,'d'*32,'MSFT'), active_deadline(time.monotonic()-1):
                        with d.span('body','sec'): raise error
                self.assertIs(caught.exception,error)
                self.assertIs(d._active.get(),outer)
            self.assertIsNone(d._active.get())
            rows=[json.loads(x) for x in (root/'private/enrichment_diagnostics.jsonl').read_text().splitlines()]
            for identity in {r['attempt_id'] for r in rows}:
                self.assertEqual(len({r['symbol'] for r in rows if r['attempt_id']==identity}),1)
            self.assertTrue(any(r['outcome']=='deadline' for r in rows))

    def test_bound_retains_phase_and_terminal_records(self):
        import enrichment_diagnostics as d
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with d.attempt(True,root,'e'*32,'AAPL'):
                for _ in range(d.MAX_DETAIL_RECORDS+10):
                    with d.span('body','sec'): pass
                for operation in ('trusted_date','sec_history','prices'):
                    with d.span(operation): pass
            rows=[json.loads(x) for x in (root/'private/enrichment_diagnostics.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows),d.MAX_DETAIL_RECORDS+4)
            self.assertEqual(rows[-1]['dropped_records'],10)
            self.assertEqual({r['operation'] for r in rows[-4:]},d.PHASES)
            self.assertTrue(all(len(json.dumps(r).encode())<2048 for r in rows))

    def test_disabled_has_no_clocks_io_or_diagnostic_callbacks(self):
        import enrichment_diagnostics as d
        with patch.object(d.time,'time',side_effect=AssertionError('clock')), patch.object(d.time,'monotonic',side_effect=AssertionError('clock')), patch.object(d,'_append',side_effect=AssertionError('IO')), patch.object(d,'_snapshot',side_effect=AssertionError('snapshot')), patch.object(d,'_emit',side_effect=AssertionError('callback')):
            with d.attempt(False,None,None,'bad'):
                with d.span('body','sec'): pass
                self.assertEqual(d.traced('config','massive')(lambda: 3)(),3)

    def test_symlinks_and_hardlinks_do_not_reach_other_files(self):
        import enrichment_diagnostics as d
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            target=root/'ledger.jsonl'
            target.write_text('unchanged')
            private=root/'private'
            private.mkdir(mode=0o700)
            path=private/'enrichment_diagnostics.jsonl'
            for hard in (False,True):
                (os.link if hard else os.symlink)(target,path)
                with d.attempt(True,root,'f'*32,'AAPL'): pass
                self.assertEqual(target.read_text(),'unchanged')
                path.unlink()
            private.rmdir()
            other=root/'other'
            other.mkdir()
            private.symlink_to(other,target_is_directory=True)
            with d.attempt(True,root,'f'*32,'AAPL'): pass
            self.assertFalse((other/'enrichment_diagnostics.jsonl').exists())

    def test_offline_synthesis_uses_real_enrichment_orchestration_and_io_seams(self):
        import datetime as dt
        import enrichment_diagnostics as d
        import market_data as m
        import io
        import functools
        from zoneinfo import ZoneInfo
        from research_budget import ResearchDeadlineExceeded
        for failure in (None, OSError('SECRET body failure'), ResearchDeadlineExceeded('SECRET unsupported reader')):
            traces=[]
            for enabled in (False,True):
                with tempfile.TemporaryDirectory() as tmp:
                    root=Path(tmp)
                    calls=[]
                    config_calls=[]
                    class Response(io.BytesIO):
                        def __init__(self,body,broken=False):
                            super().__init__(body)
                            self.broken=broken
                            self.fp=SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=lambda seconds: None)))
                        def isclosed(self): return False
                        def read1(self,size: int | None=-1):
                            if self.broken:
                                assert failure is not None
                                raise failure
                            return self.read(size)
                    def opened(request,timeout):
                        url=request.full_url
                        calls.append(url.split('?')[0])
                        if 'stockanalysis' in url:
                            future=dt.date.today()+dt.timedelta(days=2)
                            body=('earningsDate:"'+future.strftime('%b %d, %Y')+'"').encode()
                        elif 'sec.gov' in url:
                            body=b'{}'
                        else:
                            date=dt.date.fromisoformat(url.split('?')[0].rsplit('/',1)[-1])
                            stamp=int(dt.datetime.combine(date,dt.time(16),ZoneInfo('America/New_York')).timestamp()*1000)
                            body=json.dumps({'status':'OK','results':[{'T':'AAPL','c':100,'t':stamp},{'T':'SPY','c':200,'t':stamp}]}).encode()
                        return Response(body,broken=failure is not None and 'massive' in url)
                    def config(*args,**kwargs):
                        config_calls.append('config')
                        return SimpleNamespace(returncode=0,stdout='{"MASSIVE_API_KEY":"SECRET"}')
                    candidate={'symbol':'AAPL','sources':[]}
                    from contextlib import nullcontext
                    with patch.object(a,'ROOT',root), patch.object(a,'synthesis_command',return_value=['synthetic']), patch.object(a.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(candidate))) as synthesis, patch.object(a,'resolve_candidate_earnings',functools.partial(e.resolve_candidate_earnings,cache_path=root/'cache.json')), patch.object(e.urllib.request,'urlopen',side_effect=opened), patch.object(m,'read_mcp_env_process',side_effect=config), (a.enable_timing() if enabled else nullcontext()):
                        cfg=json.loads((Path(a.__file__).parent/'autonomy_config.json').read_text())
                        if failure is None:
                            result=a.synthesize_candidate(cfg,candidate,[],time.monotonic()+120)
                            self.assertEqual(result['earnings_date_status'],'confirmed')
                            self.assertEqual(result['price'],100)
                        else:
                            with self.assertRaises(a.ResearchFailure) as caught:
                                a.synthesize_candidate(cfg,candidate,[],time.monotonic()+120)
                            self.assertIs(caught.exception.__cause__,failure)
                            self.assertEqual(caught.exception.code,'research_enrichment_timeout' if isinstance(failure,ResearchDeadlineExceeded) else 'research_market_data_unavailable')
                        self.assertEqual(synthesis.call_count,1)
                    traces.append((calls,config_calls))
                    if enabled:
                        text=(root/'private/enrichment_diagnostics.jsonl').read_text()
                        rows=[json.loads(x) for x in text.splitlines()]
                        self.assertTrue({'trusted_date','sec_history','cache','prices','config','open','body','json','attempt','stockanalysis'} <= {r['operation'] for r in rows})
                        self.assertNotIn('SECRET',text)
                        massive_body=next(r for r in rows if r['operation']=='body' and r['provider']=='massive')
                        self.assertEqual(massive_body['outcome'],'completed' if failure is None else 'cancelled' if isinstance(failure,ResearchDeadlineExceeded) else 'body_error')
                        self.assertEqual((root/'private').stat().st_mode&0o777,0o700)
                    else:
                        self.assertFalse((root/'private').exists())
            self.assertEqual(traces[0],traces[1])
            self.assertEqual(len(traces[0][0]),3)
            self.assertEqual(traces[0][1],['config'])

    def test_cache_negatives_bound_before_loader_and_original_checked_at(self):
        import datetime as dt
        import enrichment_diagnostics as d
        now=dt.datetime(2026,1,2,tzinfo=dt.timezone.utc)
        for raw,reason in (('nonsense','invalid'), ('[]','invalid'), ('{"AAPL":{"rows":[],"checked_at":"bad"}}','invalid'), ('{"AAPL":{"rows":[],"checked_at":"2025-01-01T00:00:00Z"}}','expired')):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                cache=root/'cache.json'
                cache.write_text(raw)
                def loader(symbol):
                    trace=[json.loads(x) for x in (root/'private/enrichment_diagnostics.jsonl').read_text().splitlines()]
                    self.assertEqual(trace[-1]['cache_reason'],reason)
                    return []
                with d.attempt(True,root,'a'*32,'AAPL'):
                    self.assertEqual(e.cached_sec_release_history('AAPL',cache_path=cache,now=now,history_loader=loader),[])
                self.assertEqual(json.loads(cache.read_text())['AAPL']['checked_at'],'2026-01-02T00:00:00Z')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with d.attempt(True,root,'a'*32,'AAPL'), patch.object(Path,'read_text',side_effect=PermissionError('SECRET')):
                e.cached_sec_release_history('AAPL',cache_path=root/'cache.json',now=now,history_loader=lambda symbol: [])
            rows=[json.loads(x) for x in (root/'private/enrichment_diagnostics.jsonl').read_text().splitlines()]
            self.assertEqual(rows[0]['cache_reason'],'unreadable')

    def test_research_timing_is_private_and_does_not_follow_file_links(self):
        import os
        import stat
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(a,'ROOT',root),a.enable_timing():
                with a.timed_research_stage('synthetic'):pass
            self.assertEqual(stat.S_IMODE((root/'private').stat().st_mode),0o700)
            target=root/'private/research_timings.jsonl'
            self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600)
            target.unlink();external=root/'untouched';external.write_text('unchanged')
            target.symlink_to(external)
            with patch.object(a,'ROOT',root),a.enable_timing():
                with a.timed_research_stage('synthetic'):pass
            self.assertEqual(external.read_text(),'unchanged')

if __name__ == '__main__':
    unittest.main()
