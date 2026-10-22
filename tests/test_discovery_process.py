import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest


class ProcessTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('discovery_process'),'process implementation missing')
        import discovery_process as m
        return m

    def test_local_worker_protocol_and_deadline(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            p=m.run_process([sys.executable,'-c','import sys;sys.stdin.read();print("{\\\"version\\\":1}")'],b'{}',deadline=time.monotonic()+3,cwd=Path(d))
        self.assertEqual(p.returncode,0);self.assertEqual(json.loads(p.stdout),{'version':1})

    def test_no_spawn_after_deadline_or_request_limit(self):
        m=self.api()
        from unittest.mock import patch
        with patch.object(m.subprocess,'Popen',side_effect=AssertionError('must not spawn')):
            for body,deadline in [(b'{}',time.monotonic()-1),(b'x'*(32768+1),time.monotonic()+2)]:
                p=m.run_process(['not-launched'],body,deadline=deadline,cwd=Path.cwd())
                self.assertNotEqual(p.returncode,0)

    def test_blocked_stdin_and_child_cleanup(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'child.pid'
            code='import subprocess,time,pathlib,sys; p=subprocess.Popen([sys.executable,"-c","import os,time;os.setsid();time.sleep(60)"]);pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(60)'
            started=time.monotonic();p=m.run_process([sys.executable,'-c',code,str(f)],b'x'*32000,deadline=started+.8,cwd=Path(d))
            self.assertEqual(p.returncode,124);self.assertLess(time.monotonic()-started,3)
            self.assertTrue(f.exists());self.assertFalse(Path('/proc',f.read_text()).exists())

    def test_output_and_stderr_limits_are_explicit(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            for stream,size in [('stdout',2*1024*1024+1),('stderr',16385)]:
                p=m.run_process([sys.executable,'-c',f'import sys;sys.{stream}.write("x"*{size});sys.{stream}.flush()'],b'',deadline=time.monotonic()+3,cwd=Path(d))
                self.assertNotEqual(p.returncode,0);self.assertLess(len(p.stdout.encode()),1000)
