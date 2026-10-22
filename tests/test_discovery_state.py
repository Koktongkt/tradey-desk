import datetime as dt
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

NOW=dt.datetime(2026,10,21,15,tzinfo=dt.timezone.utc)
ROOT=Path(__file__).resolve().parents[1]


class StateTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('discovery_state'),'bounded state worker missing')
        import discovery_state as m
        return m

    def test_blocked_history_fifo_is_bounded_and_reaped(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'private/history.json';p.parent.mkdir();os.mkfifo(p)
            started=time.monotonic();r=m.request_state('read',history_path=p,artifact_dir=p.parent/'runs',now=NOW,deadline=started+.4)
            self.assertEqual(r['reason'],'timeout');self.assertLess(time.monotonic()-started,3)
            self.assertFalse((p.parent/'runs').exists())

    def test_blocked_archive_operation_is_bounded(self):
        m=self.api()
        bootstrap=f'import sys,time;sys.path.insert(0,{str(ROOT)!r});import discovery_state as s;s._save=lambda *a,**kw:time.sleep(60);s.main()'
        with tempfile.TemporaryDirectory() as d,patch.object(m,'worker_command',return_value=[sys.executable,'-I','-c',bootstrap]):
            p=Path(d)/'private/history.json';started=time.monotonic()
            r=m.request_state('persist',history_path=p,artifact_dir=p.parent/'runs',now=NOW,deadline=started+.4,candidates=[],capture={'version':1})
            self.assertEqual(r['reason'],'timeout');self.assertLess(time.monotonic()-started,3)

    def test_each_history_write_is_supervised(self):
        m=self.api()
        for blocked in range(1,6):
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'private/history.json';marker=Path(d)/'entered'
                bootstrap=(f'import sys,time,os;sys.path.insert(0,{str(ROOT)!r});import discovery_state as s;original=s.record_history;count=[0];'
                    f'exec("def slow(*a,**kw):\\n count[0]+=1\\n if count[0]=={blocked}:\\n  fd=os.open({str(marker)!r},os.O_WRONLY|os.O_CREAT,0o600);os.write(fd,b\'entered\');os.close(fd);time.sleep(60)\\n return original(*a,**kw)");s.record_history=slow;s.main()')
                candidates=[{'symbol':'ABC','urls':[f'https://example.com/{i}'],'catalyst':'change','event_date':'2026-10-21'} for i in range(5)]
                with patch.object(m,'worker_command',return_value=[sys.executable,'-I','-c',bootstrap]):
                    started=time.monotonic();result=m.request_state('persist',history_path=p,artifact_dir=p.parent/'runs',now=NOW,deadline=started+.6,candidates=candidates,capture={})
                self.assertEqual(result['reason'],'timeout');self.assertLess(time.monotonic()-started,3)
                self.assertTrue(marker.exists(),'blocked history call not exercised')

    def test_actual_state_round_trip_permissions(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'private/history.json';r=m.request_state('persist',history_path=p,artifact_dir=p.parent/'runs',now=NOW,deadline=time.monotonic()+3,candidates=[{'symbol':'ABC','urls':['https://example.com/article'],'catalyst':'change','event_date':'2026-10-21'}],capture={'version':1})
            self.assertEqual(r['artifact_status'],'persisted');self.assertEqual(p.stat().st_mode&0o777,0o600)
            r=m.request_state('read',history_path=p,artifact_dir=p.parent/'runs',now=NOW,deadline=time.monotonic()+3)
            self.assertEqual(len(r['history']['entries']),1)

    def test_unconfirmed_containment_is_not_benign_state_failure(self):
        m=self.api()
        import subprocess
        failure=subprocess.CompletedProcess([],1,'{"reason":"containment_unconfirmed"}','')
        with tempfile.TemporaryDirectory() as d,patch.object(m,'run_process',return_value=failure):
            p=Path(d)/'private/history.json'
            result=m.request_state('read',history_path=p,artifact_dir=p.parent/'runs',now=NOW,deadline=time.monotonic()+1)
            self.assertEqual(result['reason'],'containment_unconfirmed')

    def test_worker_unavailable_is_explicit_auxiliary_failure(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d,patch.object(m,'run_process',side_effect=OSError('unavailable')):
            p=Path(d)/'private/history.json'
            result=m.request_state('read',history_path=p,artifact_dir=p.parent/'runs',now=NOW,deadline=time.monotonic()+1)
            self.assertEqual(result,{'status':'error','reason':'state_unavailable'})

    def test_expired_failure_archive_never_launches(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d,patch.object(m,'run_process',side_effect=AssertionError('no launch')):
            p=Path(d)/'private/history.json';r=m.request_state('persist',history_path=p,artifact_dir=p.parent/'runs',now=NOW,deadline=time.monotonic()-1,candidates=[],capture={'reason':'collection_unavailable'})
            self.assertEqual(r['reason'],'timeout')
