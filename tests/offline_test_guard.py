"""Test-only direct external-Hermes tripwire, not an OS/network sandbox.

The audit hook runs at the real subprocess.Popen launch boundary (including saved
Popen aliases), without replacing Popen or preventing real Python containment
children. Wrappers, grandchildren and non-Hermes network paths are not covered.
Unexpected refusals remain sticky even when application code catches Exception.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import atexit
import json
import os
from pathlib import Path
import sys
import unittest

_installed = False
_expect_local = ContextVar('expected_offline_local_control', default=False)
_counts = {'unexpected_actual_hermes_attempts': 0, 'unexpected_local_controls': 0,
           'expected_blocked_local_controls': 0}


def installed():
    return _installed


def summary():
    return dict(_counts)


def _unexpected():
    return bool(_counts['unexpected_actual_hermes_attempts'] or _counts['unexpected_local_controls'])


def _audit(event, args):
    if event != 'subprocess.Popen':
        return
    executable, command, _cwd, _env = args
    tokens = command if isinstance(command, (list, tuple)) else [command]
    names = [executable, tokens[0] if tokens else '']
    if not any(name is not None and Path(os.fsdecode(name)).name.lower() in ('hermes', 'hermes.exe')
               for name in names):
        return
    # Only this exact no-op Python command can be an expected self-test. Real
    # Hermes attempts can NEVER be acknowledged/reset by the control scope.
    local = (tokens == ['hermes', '-c', 'pass'] and executable == sys.executable)
    key = ('expected_blocked_local_controls' if _expect_local.get() else 'unexpected_local_controls') if local else 'unexpected_actual_hermes_attempts'
    _counts[key] += 1
    raise RuntimeError('TEST_OFFLINE_HERMES_BLOCKED')


@contextmanager
def expected_local_control():
    """Acknowledge exactly one safe no-op Python control, not arbitrary attempts."""
    before = _counts['expected_blocked_local_controls']
    token = _expect_local.set(True)
    try:
        yield
    finally:
        _expect_local.reset(token)
        if _counts['expected_blocked_local_controls'] != before + 1:
            raise AssertionError('expected exactly one blocked local Python control')


def _finish():
    print('TEST_OFFLINE_BOUNDARY '+json.dumps(summary(), sort_keys=True), flush=True)
    if _unexpected():
        # unittest and application exception handling cannot turn an unexpected
        # launch into exit 0. Flush diagnostics before the final fail-closed exit.
        sys.stderr.flush()
        os._exit(1)


def install():
    global _installed
    if _installed:
        return
    sys.addaudithook(_audit)
    original = unittest.TestResult.wasSuccessful
    def successful(self):
        return original(self) and not _unexpected()
    unittest.TestResult.wasSuccessful = successful
    atexit.register(_finish)
    _installed = True
