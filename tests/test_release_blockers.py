"""Real offline regression tests for reviewer R1/R2/R3."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
import broker_process
import entry_state
import sqlite_ledger as storage
import pending_policy
from unittest.mock import patch
import test_three_runtime as runtime_fixture
Clock = runtime_fixture.Clock
import broker_mcp_bridge as bridge
from support_fixtures import technical_bars


class ReadonlyQualificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = runtime_fixture.ThreeRuntimeTests('test_checked_in_config_third_cross_day_entry_through_actual_bridge')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        for item in (patch.object(bridge, 'consolidated_daily_bars', return_value=technical_bars()), patch.object(bridge, 'datetime', Clock)):
            item.start()
            self.addCleanup(item.stop)

    def snapshot(self):
        return self.fixture.broker('snapshot', {'symbol': 'DELL', 'planned_exit_at': '2026-12-01T21:00:00Z'})

    def bytes(self):
        return {str(p.relative_to(self.fixture.root)): p.read_bytes() for p in self.fixture.root.rglob('*') if p.is_file() and not p.name.endswith('.lock')}

    def test_actual_qualify_unimported_existing_database_blocks_without_business_writes(self):
        before = self.bytes()
        with self.assertRaisesRegex(pending_policy.m.ReconciliationBlocked, '^managed_repair_required$'):
            pending_policy.qualify(self.fixture.root, self.snapshot(), self.fixture.broker)
        self.assertEqual(self.bytes(), before)

    def test_divergent_projection_blocks_without_business_writes(self):
        storage.migrate_jsonl(self.fixture.root)
        path = self.fixture.root / 'order_ledger.jsonl'
        path.write_text('{}\n')
        before = self.bytes()
        with self.assertRaisesRegex(pending_policy.m.ReconciliationBlocked, '^managed_state_invalid$'):
            pending_policy.qualify(self.fixture.root, self.snapshot(), self.fixture.broker)
        self.assertEqual(self.bytes(), before)

    def test_malformed_database_blocks_without_business_writes(self):
        db = storage.database_path(self.fixture.root / 'order_ledger.jsonl')
        db.write_bytes(b'not sqlite')
        before = self.bytes()
        with self.assertRaisesRegex(pending_policy.m.ReconciliationBlocked, '^managed_state_invalid$'):
            pending_policy.qualify(self.fixture.root, self.snapshot(), self.fixture.broker)
        self.assertEqual(self.bytes(), before)

    def test_uncheckpointed_wal_requires_operational_repair_without_writes(self):
        import sqlite3
        db = storage.database_path(self.fixture.root / 'order_ledger.jsonl')
        conn = sqlite3.connect(db)
        self.addCleanup(conn.close)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('UPDATE ledger_entries SET appended_at=?', ('offline-wal',))
        conn.commit()
        before = self.bytes()
        with self.assertRaisesRegex(pending_policy.m.ReconciliationBlocked, '^managed_repair_required$'):
            pending_policy.qualify(self.fixture.root, self.snapshot(), self.fixture.broker)
        self.assertEqual(self.bytes(), before)

    def test_unrelated_malformed_projection_is_not_ignored(self):
        storage.migrate_jsonl(self.fixture.root)
        (self.fixture.root / 'private/reviews.jsonl').write_text('not-json\n')
        before = self.bytes()
        with self.assertRaisesRegex(pending_policy.m.ReconciliationBlocked, '^managed_state_invalid$'):
            pending_policy.qualify(self.fixture.root, self.snapshot(), self.fixture.broker)
        self.assertEqual(self.bytes(), before)

    def test_operational_startup_imports_then_readonly_qualification_preserves_all_bytes(self):
        pending_policy.m.reconcile_detailed(self.fixture.root, self.fixture.broker)
        before = self.bytes()
        snap = self.snapshot()
        proof = pending_policy.qualify(self.fixture.root, snap, self.fixture.broker)
        self.assertTrue(pending_policy.valid(proof, snap))
        self.assertEqual(self.bytes(), before)

    def test_legacy_without_database_qualifies_without_creating_database(self):
        storage.database_path(self.fixture.root / 'order_ledger.jsonl').unlink()
        before = self.bytes()
        snap = self.snapshot()
        self.assertTrue(pending_policy.valid(pending_policy.qualify(self.fixture.root, snap, self.fixture.broker), snap))
        self.assertEqual(self.bytes(), before)



class ProcessLifetimeTests(unittest.TestCase):
    def launch(self, inherit=False, wrapper_sleep=.15, timeout=1):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = root / 'child.pid'
            child = f"import os,time,pathlib; pathlib.Path({str(record)!r}).write_text(str(os.getpid())+' '+pathlib.Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19]); time.sleep(30)"
            streams = '' if inherit else ',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL'
            wrapper = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True{streams}); time.sleep({wrapper_sleep}); print('wrapper-output')"
            started = time.monotonic()
            try:
                with entry_state.lock(root):
                    if wrapper_sleep == 30:
                        with self.assertRaises(subprocess.TimeoutExpired):
                            broker_process.run_bridge([sys.executable, '-c', wrapper], input='', timeout=timeout, run=subprocess.run)
                    else:
                        result = broker_process.run_bridge([sys.executable, '-c', wrapper], input='', timeout=timeout, run=subprocess.run)
                        self.assertEqual(result.stdout, 'wrapper-output\n')
                        self.assertEqual(result.returncode, 0)
                self.assertLess(time.monotonic() - started, 2)
                self.assertTrue(record.exists())
                self.assertFalse((Path('/proc') / record.read_text().split()[0]).exists(), 'child must be terminated AND reaped')
                with entry_state.lock(root, attempts=1):
                    self.assertFalse((Path('/proc') / record.read_text().split()[0]).exists(), 'successor must not inherit surviving authority')
            finally:
                if record.exists():
                    import broker_supervisor
                    pid, start = record.read_text().split()
                    fd = None
                    try:
                        fd = os.pidfd_open(int(pid))
                        observed = broker_supervisor.identity(int(pid))
                        if observed and observed[1] == start:
                            broker_supervisor.signal.pidfd_send_signal(fd, 9)
                    except ProcessLookupError:
                        pass
                    finally:
                        if fd is not None:
                            os.close(fd)

    def test_normal_exit_reaps_detached_devnull_child_before_successor_lock(self):
        self.launch()

    def test_exited_wrapper_inherited_pipes_bounded_and_reaped(self):
        self.launch(inherit=True, timeout=.5)

    def test_running_wrapper_timeout_reaps_detached_child(self):
        self.launch(wrapper_sleep=30, timeout=.3)

    def test_supervisor_failure_after_launch_reaps_detached_child(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / 'child.pid'
            child = f"import os,time,pathlib; pathlib.Path({str(record)!r}).write_text(str(os.getpid())+' '+pathlib.Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19]); time.sleep(30)"
            wrapper = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True); time.sleep(30)"
            # Isolated supervisor process, fault at its selector initialization.
            probe = "import broker_supervisor as s,sys,time,json; from unittest.mock import patch; " + \
                "bad=lambda: (time.sleep(.2), (_ for _ in ()).throw(RuntimeError('fault')))[1]; " + \
                "patcher=patch.object(s.selectors,'DefaultSelector',side_effect=bad); patcher.start(); s.main()"
            request = dict(command=[sys.executable, '-c', wrapper], input='', timeout=1, options={})
            result = subprocess.run([sys.executable, '-c', probe], input=__import__('json').dumps(request), text=True, capture_output=True, timeout=2)
            self.assertEqual(__import__('json').loads(result.stdout), {'error': 'RuntimeError'})
            self.assertTrue(record.exists())
            self.assertFalse((Path('/proc') / record.read_text().split()[0]).exists())

    def test_disappeared_owned_process_during_pidfd_signal_is_safe(self):
        import broker_supervisor
        with patch.object(broker_supervisor.signal, 'pidfd_send_signal', side_effect=ProcessLookupError):
            broker_supervisor.freeze_kill_tree(os.getpid())

    def test_fast_spawn_exit_reaps_orphan_without_ppid_polling(self):
        wrapper = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); print(p.pid)"
        result = broker_process.run_bridge([sys.executable, '-c', wrapper], input='', timeout=1, run=subprocess.run)
        self.assertEqual(result.returncode, 0)
        self.assertFalse((Path('/proc') / result.stdout.strip()).exists())

    def test_failed_launch_is_honest_and_unrelated_child_survives(self):
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            with self.assertRaises(OSError):
                broker_process.run_bridge(['/nonexistent-offline-command'], input='', timeout=1, run=subprocess.run)
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.kill()
            unrelated.wait(timeout=1)

    def test_nonzero_and_stdin_stderr_are_preserved(self):
        result = broker_process.run_bridge([sys.executable, '-c', "import sys; print(sys.stdin.read()); print('err',file=sys.stderr); sys.exit(3)"], input='payload', timeout=2, run=subprocess.run)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (3, 'payload\n', 'err\n'))
        with self.assertRaises(subprocess.CalledProcessError):
            broker_process.run_bridge([sys.executable, '-c', 'raise SystemExit(3)'], input='', timeout=2, run=subprocess.run, check=True)


if __name__ == '__main__':
    unittest.main()
