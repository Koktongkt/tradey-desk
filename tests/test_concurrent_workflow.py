"""Real orchestration and persistence with offline broker/model boundaries."""
import copy
import contextlib
import datetime as dt
import hashlib
import io
import json
import unittest
from unittest.mock import patch
import autotrader as a
import test_pending_capacity as helpers


class ConcurrentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.f=helpers.PendingCapacityTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root=self.f.root
        self.cfg=dict(self.f.cfg,enabled=True,broker_mode='paper')
        now=dt.datetime.now(dt.timezone.utc)
        self.snapshot=self.f.snapshot
        day=now.astimezone(a.ZoneInfo('America/New_York')).date()
        # Authoritative synthetic calendar; no fixed market-hour inference in production.
        start=now-dt.timedelta(hours=1); end=now+dt.timedelta(hours=1)
        self.snapshot.update(trading_calendar=[{'date':day.isoformat(),'open':start.isoformat(),'close':end.isoformat()},
            {'date':(day+dt.timedelta(days=1)).isoformat(),'open':(start+dt.timedelta(days=1)).isoformat(),'close':(end+dt.timedelta(days=1)).isoformat()}])
        self.cfg.update(entry_expiry_policy='new_intents_session_close_v1')
        (self.root/'autonomy_config.json').write_text(json.dumps(self.cfg))
        self.candidate={'symbol':'DELL','sources_verified_at':now.isoformat(),'researched_at':now.isoformat(),
            'sources':[{'url':'https://a.example/1'},{'url':'https://b.example/2'}],
            'setup_type':'breakout','planned_exit_at':self.snapshot['trading_sessions'][2]+'T20:00:00Z','thesis':'supported'}
        self.candidate['dossier_hash']=hashlib.sha256(json.dumps(self.candidate,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        (self.root/'candidates.jsonl').write_text(json.dumps(self.candidate)+'\n')
        self.calls=[]

    def broker(self,op,p=None):
        self.calls.append((op,p))
        if op=='reconcile':
            return copy.deepcopy(next(o for o in self.f.parents if o['client_order_id']==p['client_order_id']))
        if op in {'reconcile_many','reconciliation_snapshot'}:
            orders=[o for o in self.f.parents if o['client_order_id'] in p['client_order_ids']]
            return dict(copy.deepcopy(self.snapshot),orders=copy.deepcopy(orders))
        if op in {'snapshot','review'}:return copy.deepcopy(self.snapshot)
        if op=='place':
            intent,order=helpers.pending(p['client_order_id'],p['order']['symbol'])
            plan=p['order'];order.update(qty=str(plan['quantity']),limit_price=str(plan['limit_price']))
            for child in order['legs']:
                child['qty']=str(plan['quantity'])
                child['limit_price' if child['type']=='limit' else 'stop_price']=str(plan['target' if child['type']=='limit' else 'stop'])
            self.f.parents.append(order)
            self.snapshot['open_orders']=copy.deepcopy(self.f.parents)
            return order
        raise AssertionError(op)

    def reviewers(self,bundle,cfg):
        self.review_bundle=copy.deepcopy(bundle)
        proposal=bundle['proposal']
        return [{'proposal_hash':proposal['proposal_hash'],'decision':'APPROVE','fatal_flags':[],'reason_codes':[],
            'component_scores':{k:5 for k in a.RUBRIC_WEIGHTS[proposal['assigned_rubric']]}} for _ in range(2)]

    def execute(self):
        out=io.StringIO()
        with patch.object(a,'ROOT',self.root),patch.object(a,'_broker_bridge',side_effect=self.broker),patch.object(a,'independent_reviews',side_effect=self.reviewers),contextlib.redirect_stdout(out):
            code=a.run(a.argparse.Namespace(dry_run_fixture=False,live_dry_run=False))
        return code,out.getvalue()

    def test_run_honors_cross_process_entry_lock_before_any_broker_call(self):
        import entry_state
        import multiprocessing
        ctx=multiprocessing.get_context('fork')
        ready,release=ctx.Event(),ctx.Event()
        def holder():
            with entry_state.lock(self.root):
                ready.set();release.wait(5)
        process=ctx.Process(target=holder);process.start()
        self.addCleanup(lambda: process.kill() if process.is_alive() else None)
        try:
            self.assertTrue(ready.wait(3))
            code,out=self.execute()
            self.assertEqual(code,2,out)
            self.assertIn('entry_state_busy',out)
            self.assertEqual(self.calls,[])
        finally:
            release.set();process.join(5)
        self.assertEqual(process.exitcode,0)

    def test_unknown_submission_consumes_daily_quota_on_original_session(self):
        today=dt.datetime.now(a.ZoneInfo('America/New_York')).date().isoformat()
        for ref in ('unknown-a','unknown-b'):
            a.append_jsonl(self.root/'private/order_intents.jsonl',{'client_order_id':ref,'submission_date':today,'plan':{}})
            a.append_jsonl(self.root/'order_ledger.jsonl',{'timestamp':a.utcnow(),'client_order_id':ref,'status':'submission_unknown'})
        self.assertEqual(a._daily_order_count(self.root/'order_ledger.jsonl'),2)

    def test_confirmed_fill_is_journaled_once_across_recovery(self):
        intent,order=helpers.pending()
        order.update(status='filled',filled_qty='2',filled_avg_price='100',filled_at=a.utcnow())
        path=self.root/'trade_journal.jsonl'
        a.journal_confirmed_fill(path,intent['plan'],order)
        a.journal_confirmed_fill(path,intent['plan'],order)
        self.assertEqual(len(a.read_jsonl(path)),1)

    def test_second_entry_passes_all_stages_and_repeat_cycle_never_resubmits(self):
        code,out=self.execute()
        self.assertEqual((code,[op for op,_ in self.calls].count('place')),(0,1),out)
        intent=a.read_jsonl(self.root/'private/order_intents.jsonl')[-1]
        self.assertIn('entry_expiry',intent['plan'])
        self.assertEqual(self.review_bundle['qualification']['pending_entry_parents'],1)
        self.assertNotIn('one',json.dumps(self.review_bundle))
        self.execute()
        self.assertEqual([op for op,_ in self.calls].count('place'),1)

    def test_fresh_final_snapshot_capacity_change_blocks_submission(self):
        original=self.broker
        def broker(op,p=None):
            if op=='review':
                intent,parent=helpers.pending('two','MSFT')
                self.f.parents.append(parent)
                a.append_jsonl(self.root/'private/order_intents.jsonl',intent)
                a.append_jsonl(self.root/'order_ledger.jsonl',{'client_order_id':'two','status':'new'})
                self.snapshot['open_orders']=copy.deepcopy(self.f.parents)
            return original(op,p)
        self.broker=broker
        code,out=self.execute()
        self.assertEqual(code,2,out)
        self.assertFalse(any(op=='place' for op,_ in self.calls))
        self.assertIn('pending_entry_limit',out)
