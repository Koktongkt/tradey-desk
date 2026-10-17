"""Offline path contracts; no CLI execution, credentials or provider requests."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class RuntimePathTests(unittest.TestCase):
    def helper(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime_paths'), 'portable resolver missing')
        import runtime_paths
        return runtime_paths

    def executable(self, root, name, body='#!/bin/sh\nexit 0\n'):
        path = root / name
        path.write_text(body)
        path.chmod(0o700)
        return str(path)

    def test_cli_override_then_path_then_home_and_bad_override_fails_closed(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            explicit = self.executable(root, 'explicit')
            found = self.executable(root, 'found')
            fallback = root / '.local/bin/hermes'
            fallback.parent.mkdir(parents=True)
            fallback.write_text('#!/bin/sh\nexit 0\n')
            fallback.chmod(0o700)
            with patch.dict(os.environ, {'HOME': str(root)}, clear=True), patch('shutil.which', return_value=found):
                self.assertEqual(helper.hermes_cli(), found)
                with patch.dict(os.environ, {'HERMES_BIN': explicit}):
                    self.assertEqual(helper.hermes_cli(), explicit)
                for bad in ('', str(root / 'missing'), str(root)):
                    with patch.dict(os.environ, {'HERMES_BIN': bad}):
                        with self.assertRaises(ValueError):
                            helper.hermes_cli()
                Path(explicit).chmod(0o600)
                with patch.dict(os.environ, {'HERMES_BIN': explicit}):
                    with self.assertRaises(ValueError):
                        helper.hermes_cli()
            with patch.dict(os.environ, {'HOME': str(root)}, clear=True), patch('shutil.which', return_value=None):
                self.assertEqual(helper.hermes_cli(), str(fallback))
                fallback.unlink()
                with self.assertRaises(ValueError):
                    helper.hermes_cli()

    def test_gateway_loads_managed_dependency_bootstrap_before_provider_import(self):
        source = (Path(__file__).resolve().parents[1] / 'watchdog/provider_gateway.py').read_text()
        self.assertIn('import hermes_bootstrap', source)
        self.assertLess(source.index('import hermes_bootstrap'), source.index('from hermes_cli.runtime_provider'))

    def test_production_consumers_have_no_legacy_install_paths(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('alpha_radar.py', 'autotrader.py', 'mcp_config_process.py',
                     'watchdog/runtime.py', 'watchdog/provider_gateway.py', 'watchdog/operational.py'):
            with self.subTest(name=name):
                self.assertNotIn('/opt/hermes', (root / name).read_text())
                self.assertNotIn('/opt/data/cache/scratch', (root / name).read_text())

    def test_provider_session_uses_discovered_interpreter_and_source(self):
        from watchdog.runtime import ProviderSession
        session = ProviderSession()
        try:
            with patch('runtime_paths.hermes_runtime', return_value=('/chosen/python', Path('/chosen/source'))), patch(
                    'watchdog.runtime.subprocess.Popen') as popen, patch('pathlib.Path.exists', return_value=True):
                session.start()
            self.assertEqual(popen.call_args.args[0][0], '/chosen/python')
            self.assertEqual(popen.call_args.kwargs['env']['HERMES_SOURCE_ROOT'], '/chosen/source')
            self.assertEqual(popen.call_args.kwargs['env']['HERMES_PYTHON'], '/chosen/python')
        finally:
            # No child actually spawned by this test.
            session.process = None
            session.close()

    def test_runtime_unwraps_shell_launchers_without_executing_them(self):
        helper = self.helper()
        self.assertTrue(callable(getattr(helper, 'hermes_runtime', None)), 'runtime resolver missing')
        import shlex
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            (source / 'hermes_cli').mkdir(parents=True)
            (source / 'hermes_cli/runtime_provider.py').write_text('')
            python = self.executable(root, 'python', '#!/bin/sh\nexit 99\n')
            code = f'import sys; sys.path.insert(0, {str(source)!r})'
            inner = self.executable(root, 'inner', f'#!/bin/sh\nexec {shlex.quote(python)} -I -c {shlex.quote(code)} "$@"\n')
            outer = self.executable(root, 'hermes', f'#!/bin/sh\nexec {shlex.quote(inner)} "$@"\n')
            with patch.dict(os.environ, {'HERMES_BIN': outer}, clear=True):
                self.assertEqual(helper.hermes_runtime(), (python, source))
                for key in ('HERMES_PYTHON', 'HERMES_SOURCE_ROOT'):
                    with patch.dict(os.environ, {key: str(root / 'missing')}):
                        with self.assertRaises(ValueError):
                            helper.hermes_runtime()
                    with patch.dict(os.environ, {key: ''}):
                        with self.assertRaises(ValueError):
                            helper.hermes_runtime()
            with patch.dict(os.environ, {'HERMES_BIN': str(root / 'missing'),
                                         'HERMES_PYTHON': python,
                                         'HERMES_SOURCE_ROOT': str(source)}, clear=True):
                with self.assertRaises(ValueError):
                    helper.hermes_runtime()
            Path(inner).write_text(f'#!/bin/sh\nexec {shlex.quote(outer)} "$@"\n')
            with patch.dict(os.environ, {'HERMES_BIN': outer}, clear=True):
                with self.assertRaises(ValueError):
                    helper.hermes_runtime()


if __name__ == '__main__':
    unittest.main()
