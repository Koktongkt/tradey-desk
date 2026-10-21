"""Discovery bootstrap and offline launch-boundary regression controls.

Unittest discovery imports modules before running tests. The sorted first module
also installs before the existing modules' imports; the explicit tier runner
installs independently before building its suite. No production import uses this.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import offline_test_guard as guard

guard.install()

ROOT = Path(__file__).resolve().parents[1]


class OfflineBoundaryTests(unittest.TestCase):
    def test_default_discovery_installs_boundary(self):
        self.assertIsNotNone(guard, 'ordinary discovery lacks external Hermes boundary')
        self.assertTrue(guard.installed())

    def test_real_local_python_process_remains_real(self):
        result = subprocess.run([sys.executable, '-c', 'print("LOCAL_PYTHON_OK")'],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, 'LOCAL_PYTHON_OK\n')

    def test_expected_local_control_is_blocked_and_records_are_scoped(self):
        self.assertIsNotNone(guard)
        before = guard.summary()
        with guard.expected_local_control():
            with self.assertRaisesRegex(RuntimeError, 'TEST_OFFLINE_HERMES_BLOCKED'):
                subprocess.Popen(['hermes', '-c', 'pass'], executable=sys.executable)
        after = guard.summary()
        self.assertEqual(after['unexpected_actual_hermes_attempts'], before['unexpected_actual_hermes_attempts'])
        self.assertEqual(after['unexpected_local_controls'], before['unexpected_local_controls'])
        self.assertEqual(after['expected_blocked_local_controls'], before['expected_blocked_local_controls']+1)

    def _ordinary_entrypoint_caught_control(self, entrypoint):
        # Keep the real entrypoint, manifest checks and module import path. Reduce
        # execution to this module's probe to avoid recursive whole-suite runs.
        script = '''import json, os, runpy, sys, unittest
os.environ['TRADEY_TEST_BOUNDARY_PROBE']='1'
original=unittest.TestLoader.loadTestsFromModule
def probe_only(self,module,*args,**kwargs):
    if module.__name__.split('.')[-1]=='test_000_offline_boundary':
        return original(self,module,*args,**kwargs)
    return unittest.TestSuite()
unittest.TestLoader.loadTestsFromModule=probe_only
sys.path.insert(0,str(__import__('pathlib').Path('tests').resolve()))
sys.argv=ARGV
if ENTRY == 'raw':
    runpy.run_module('unittest',run_name='__main__')
else:
    runpy.run_path('tests/run_tests.py',run_name='__main__')
'''
        argv=['tests/run_tests.py','full'] if entrypoint == 'full' else ['unittest','discover','-s','tests']
        script=script.replace('ARGV',repr(argv)).replace('ENTRY',repr(entrypoint))
        outer=os.environ.get('TRADEY_TEST_OUTER_GUARD')
        command=[sys.executable, *([outer] if outer else []), '-c', script]
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        summaries=[json.loads(line.split(' ',1)[1]) for line in result.stdout.splitlines()
                   if line.startswith('TEST_OFFLINE_BOUNDARY ')]
        self.assertTrue(summaries,result.stdout+result.stderr)
        self.assertEqual(summaries[-1]['unexpected_local_controls'],1)
        self.assertEqual(summaries[-1]['unexpected_actual_hermes_attempts'],0)
        self.assertIn('CAUGHT_ORDINARY_EXCEPTION',result.stdout)
        self.assertNotIn('LOCAL_CONTROL_ESCAPED',result.stdout)
        print('OFFLINE_CONTROL_ENTRYPOINT '+json.dumps(dict(entrypoint=entrypoint,
            exit_code=result.returncode, **summaries[-1]),sort_keys=True),flush=True)

    def test_full_entrypoint_fails_even_when_application_catches_launch_error(self):
        self._ordinary_entrypoint_caught_control('full')

    def test_raw_entrypoint_fails_even_when_application_catches_launch_error(self):
        self._ordinary_entrypoint_caught_control('raw')


def load_tests(loader, tests, pattern):
    if os.environ.get('TRADEY_TEST_BOUNDARY_PROBE') != '1':
        return tests
    class CaughtLaunchProbe(unittest.TestCase):
        def runTest(self):
            try:
                child=subprocess.Popen(['hermes','-c','pass'], executable=sys.executable)
            except Exception:
                print('CAUGHT_ORDINARY_EXCEPTION',flush=True)
            else:
                child.wait(timeout=10)
                print('LOCAL_CONTROL_ESCAPED',flush=True)
    return unittest.TestSuite([CaughtLaunchProbe()])
