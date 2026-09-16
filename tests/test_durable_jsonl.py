import importlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class DurableJsonlTests(unittest.TestCase):
    def helper(self):
        self.assertIsNotNone(importlib.util.find_spec('durable_jsonl'), 'durable helper missing')
        return importlib.import_module('durable_jsonl')

    def test_missing_parent_is_created_durably(self):
        module = self.helper()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'private' / 'nested' / 'rows.jsonl'
            module.append_jsonl(path, {'ok': True})
            self.assertEqual(json.loads(path.read_text()), {'ok': True})

    def test_sync_errors_propagate_and_release_lock(self):
        module = self.helper()
        for fail_at in [1, 2]:
            with self.subTest(fail_at=fail_at), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'rows.jsonl'
                real_sync = os.fsync
                calls = []
                def sync(fd):
                    calls.append(fd)
                    if len(calls) == fail_at:
                        raise OSError('injected storage failure')
                    return real_sync(fd)
                with patch.object(module.os, 'fsync', side_effect=sync), self.assertRaises(module.DurableAppendError):
                    module.append_jsonl(path, {'uncertain': True})
                # No implicit retry; the uncertain row may already be visible.
                self.assertEqual(len(path.read_text().splitlines()), 1)
                module.append_jsonl(path, {'next': True})
                self.assertEqual(len(path.read_text().splitlines()), 2)

    def test_production_writers_use_durable_boundary(self):
        module = self.helper()
        import alpha_radar
        import run_cycle
        with tempfile.TemporaryDirectory() as td, patch.object(alpha_radar, 'ROOT', Path(td)):
            for writer in [
                lambda: alpha_radar.append({'symbol': 'TEST'}),
                lambda: alpha_radar.record_scout_diagnostic({'reason': 'no_discovered_candidate'}),
                lambda: alpha_radar.record_research_diagnostics([{'reason': 'fetched', 'domain': 'example.com'}]),
                lambda: alpha_radar.record_synthesis_none({'status': 'none', 'reason': 'no_fresh_setup'}, 'fixture'),
                lambda: alpha_radar.record_source_verification_diagnostic({'passed': False}),
                lambda: run_cycle.audit_result('radar', 'research', 0, 'DECISION candidate_qualified TEST', Path(td) / 'audit.jsonl'),
            ]:
                with self.subTest(writer=writer), patch.object(module.os, 'fsync', side_effect=OSError('injected')), self.assertRaises(module.DurableAppendError):
                    writer()

    def test_failed_candidate_persistence_cannot_reuse_visible_row(self):
        module = self.helper()
        import alpha_radar
        import argparse
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'autonomy_config.json').write_text('{}')
            out = io.StringIO()
            with patch.object(alpha_radar, 'ROOT', root), patch.object(alpha_radar, 'reusable_fresh_candidate', return_value=None), patch.object(alpha_radar, 'live_research', return_value={'symbol': 'TEST'}), patch.object(alpha_radar, 'normalize_candidate', side_effect=lambda x: x), patch.object(alpha_radar, 'ensure_researched_at', return_value={'symbol': 'TEST', 'researched_at': '2026-09-16T00:00:00Z'}), patch.object(alpha_radar, 'candidate_preflight', return_value=[]), patch.object(alpha_radar, 'qualified', return_value=True), patch.object(alpha_radar, 'source_verification_result', return_value={'passed': True}), patch.object(alpha_radar, 'append', side_effect=module.DurableAppendError('injected')), patch.object(alpha_radar, 'fresh_verified_candidate', return_value={'symbol': 'TEST'}) as fallback, contextlib.redirect_stdout(out):
                rc = alpha_radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
            self.assertEqual(rc, 3)
            self.assertEqual(out.getvalue(), 'SYSTEM_FAILURE research_persistence_failure\n')
            fallback.assert_not_called()

    def test_audit_failure_is_explicit_without_success_notice(self):
        module = self.helper()
        import run_cycle
        import contextlib
        import io
        self.assertTrue(hasattr(run_cycle, 'cli'), 'normalized CLI error boundary missing')
        out = io.StringIO()
        with patch.object(run_cycle, 'main', side_effect=module.DurableAppendError('private path')), contextlib.redirect_stdout(out):
            rc = run_cycle.cli()
        self.assertEqual(rc, 3)
        self.assertEqual(out.getvalue(), 'SYSTEM_FAILURE audit_persistence_failure\n')

    def test_lock_is_held_during_sync(self):
        module = self.helper()
        import fcntl
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'rows.jsonl'
            real_sync = os.fsync
            def sync(fd):
                with path.open('a') as other:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                real_sync(fd)
            with patch.object(module.os, 'fsync', side_effect=sync):
                module.append_jsonl(path, {'x': 1})

    def test_concurrent_process_appends_remain_complete_and_unique(self):
        self.helper()
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'rows.jsonl'
            code = 'from durable_jsonl import append_jsonl; import sys; [append_jsonl(sys.argv[1], {"worker":sys.argv[2],"i":i,"body":"x"*10000}) for i in range(25)]'
            children = [subprocess.Popen([sys.executable, '-c', code, str(path), str(i)], cwd=Path(__file__).resolve().parents[1]) for i in range(4)]
            for child in children:
                self.assertEqual(child.wait(timeout=30), 0)
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(rows), 100)
            self.assertEqual(len({(r['worker'], r['i']) for r in rows}), 100)
            self.assertTrue(all(r['body'] == 'x'*10000 for r in rows))

    def test_append_flushes_before_file_and_directory_sync(self):
        module = self.helper()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'rows.jsonl'
            seen = []
            real_sync = os.fsync
            def sync(fd):
                import stat
                kind = 'directory' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file'
                if kind == 'file':
                    self.assertEqual(path.read_bytes(), b'{"x":1}\n')
                seen.append(kind)
                real_sync(fd)
            with patch.object(module.os, 'fsync', side_effect=sync):
                module.append_jsonl(path, {'x': 1})
            self.assertEqual(seen, ['file', 'directory'])
            module.append_jsonl(path, {'x': 2})
            self.assertEqual([json.loads(l) for l in path.read_text().splitlines()], [{'x': 1}, {'x': 2}])
