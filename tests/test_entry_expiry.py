import copy
import datetime as dt
import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
import autotrader as a
import test_pending_capacity as fixtures


class DeadlineTests(unittest.TestCase):
    def test_short_and_swing_deadlines_use_authoritative_early_close_and_holiday(self):
        import entry_expiry as e
        rows=[{'date':'2026-11-27','open':'09:30','close':'13:00'},
              {'date':'2026-11-30','open':'09:30','close':'16:00'}]
        short=e.metadata({'holding_sessions':5,'assigned_rubric':'short_1_5'},rows,'2026-11-27T15:00:00Z')
        swing=e.metadata({'holding_sessions':6,'assigned_rubric':'swing_6_30'},rows,'2026-11-27T15:00:00Z')
        self.assertEqual(short['expires_at'],'2026-11-27T18:00:00Z')
        self.assertEqual(swing['expires_at'],'2026-11-30T21:00:00Z')
        self.assertEqual(short,e.validate_metadata(short,{'holding_sessions':5,'assigned_rubric':'short_1_5'},rows))

    def test_dst_boundary_uses_session_close_not_utc_constant(self):
        import entry_expiry as e
        rows=[{'date':'2026-03-06','open':'09:30','close':'16:00'},
              {'date':'2026-03-09','open':'09:30','close':'16:00'}]
        meta=e.metadata({'holding_sessions':30,'assigned_rubric':'swing_6_30'},rows,'2026-03-06T15:00:00Z')
        self.assertEqual(meta['expires_at'],'2026-03-09T20:00:00Z')

    def test_expiry_process_is_legacy_safe_and_capability_disabled(self):
        import entry_expiry as e
        f=fixtures.PendingCapacityTests();f.setUp();self.addCleanup(f.doCleanups)
        f.cfg.update(enabled=True,broker_mode='paper',entry_expiry_policy=e.POLICY)
        calls=[]
        e.process(f.root,f.cfg,lambda op,p: calls.append(op))
        self.assertEqual(calls,[])
        plan=f.intents[0]['plan'];plan.update(holding_sessions=1,assigned_rubric='short_1_5')
        rows=[{'date':'2026-11-27','open':'09:30','close':'13:00'},{'date':'2026-11-30','open':'09:30','close':'16:00'}]
        plan['entry_expiry']=e.metadata(plan,rows,'2026-11-27T15:00:00Z')
        f.rows('private/order_intents.jsonl',f.intents)
        result=e.process(f.root,f.cfg,lambda op,p: calls.append(op),now=dt.datetime(2026,11,27,18,0,1,tzinfo=dt.timezone.utc))
        self.assertEqual(result,['entry_cancel_capability_unverified'])
        self.assertEqual(calls,[])
        self.assertEqual(a.read_jsonl(f.root/'order_ledger.jsonl')[-1]['status'],'new')

    def test_malformed_calendar_and_forged_metadata_fail_closed(self):
        import entry_expiry as e
        good=[{'date':'2026-11-27','open':'09:30','close':'13:00'},
              {'date':'2026-11-30','open':'09:30','close':'16:00'}]
        plan={'holding_sessions':1,'assigned_rubric':'short_1_5'}
        for rows in ([],good[:1],good+good[:1],list(reversed(good)),[dict(good[0],close=None),good[1]]):
            with self.subTest(rows=rows),self.assertRaises(RuntimeError):
                e.metadata(plan,rows,'2026-11-27T15:00:00Z')
        meta=e.metadata(plan,good,'2026-11-27T15:00:00Z')
        for field,value in [('expires_at','2026-11-30T21:00:00Z'),('version',2),('rubric','swing_6_30')]:
            with self.subTest(field=field),self.assertRaises(RuntimeError):
                e.validate_metadata(dict(meta,**{field:value}),plan,good)
