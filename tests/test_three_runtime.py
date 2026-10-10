"""Checked-in policy, real bridge + shared reconciler + all execution stages.

Only external MCP transport, consolidated bars transport and reviewer requests
are fake. Funding/calendar authority is projected by the actual bridge, never
injected as model-authored normalized snapshot fields.
"""
import asyncio
import contextlib
import copy
import datetime as dt
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import autotrader as a
import broker_mcp_bridge as bridge
import pending_policy
from test_pending_capacity import pending
from support_fixtures import technical_bars


class Clock(dt.datetime):
    instant=dt.datetime(2026,11,27,15,0,tzinfo=dt.timezone.utc)
    @classmethod
    def now(cls,tz=None):
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


class ThreeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='three-runtime-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'private').mkdir()
        self.cfg=json.loads((Path(a.__file__).parent/'autonomy_config.json').read_text())
        (self.root/'autonomy_config.json').write_text(json.dumps(self.cfg))
        (self.root/'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
        self.intents=[]; self.parents=[]; self.calls=[]; self.operations=[]; self.bundles=[]
        self.cash='10000'; self.bp='38400'
        self.calendar=[dict(date=date,open='09:30',close='13:00' if date=='2026-11-27' else '16:00',session_close='1700' if date=='2026-11-27' else '2000')
            for date in ('2026-11-27','2026-11-30','2026-12-01','2026-12-02','2026-12-03','2026-12-04')]
        self.add_pending('legacy-uber','UBER','2026-11-25')
        self.add_pending('second-msft','MSFT','2026-11-27')
        self.candidate('DELL')
        fields={
            'get_account_info':(), 'get_all_positions':(), 'get_orders':('status','limit','nested'),
            'get_asset':('symbol',), 'get_stock_latest_quote':('symbol_or_symbols','feed'),
            'get_calendar':('start','end','date_type'), 'get_order_by_client_id':('client_order_id',),
            'place_stock_order':('symbol','side','type','qty','time_in_force','limit_price','client_order_id','order_class','take_profit_limit_price','stop_loss_stop_price'),
        }
        self.tools={name:{'properties':{key:{} for key in keys}} for name,keys in fields.items()}
        self.alpaca=bridge.Alpaca(self,self.tools)

    def add_pending(self,ref,symbol,day):
        intent,parent=pending(ref,symbol)
        intent['submission_date']=day
        self.intents.append(intent); self.parents.append(parent)
        self.write_state()

    def write_state(self):
        for name,rows in (('private/order_intents.jsonl',self.intents),('order_ledger.jsonl',
                [dict(client_order_id=i['client_order_id'],status='new',timestamp=i['submission_date']+'T15:00:00Z') for i in self.intents])):
            (self.root/name).write_text(''.join(json.dumps(row)+'\n' for row in rows))

    def candidate(self,symbol):
        candidate=dict(symbol=symbol,sources_verified_at=Clock.instant.isoformat(),researched_at=Clock.instant.isoformat(),
            sources=[{'url':'https://a.example/1'},{'url':'https://b.example/2'}],
            setup_type='breakout',planned_exit_at='2026-12-01T21:00:00Z',earnings_event_at='2026-11-20',thesis='supported')
        candidate['dossier_hash']=hashlib.sha256(json.dumps(candidate,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        a.append_jsonl(self.root/'candidates.jsonl',candidate)

    async def call_tool(self,name,values):
        self.calls.append((name,copy.deepcopy(values)))
        if name=='get_account_info':raw=dict(cash=self.cash,buying_power=self.bp,multiplier='4')
        elif name=='get_all_positions':raw=[]
        elif name=='get_orders':raw=copy.deepcopy(self.parents)
        elif name=='get_asset':raw=dict(symbol=values['symbol'],tradable=True,asset_class='us_equity',exchange='NASDAQ',name='Dell Technologies Inc.',fractionable=True)
        elif name=='get_stock_latest_quote':raw={'DELL':dict(bp=99.98,ap=100,t=Clock.instant.isoformat())}
        elif name=='get_calendar':raw=copy.deepcopy(self.calendar)
        elif name=='get_order_by_client_id':raw=copy.deepcopy(next(parent for parent in self.parents if parent['client_order_id']==values['client_order_id']))
        elif name=='place_stock_order':
            _,raw=pending(values['client_order_id'],values['symbol'])
            raw.update(qty=str(values['qty']),limit_price=str(values['limit_price']))
            for child in raw['legs']:
                child['qty']=str(values['qty'])
                child['limit_price' if child['type']=='limit' else 'stop_price']=str(values['take_profit_limit_price' if child['type']=='limit' else 'stop_loss_stop_price'])
            self.parents.append(copy.deepcopy(raw))
        else:raise AssertionError('forbidden MCP tool '+name)
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(raw))])

    def broker(self,op,payload=None):
        self.operations.append(op)
        return asyncio.run(bridge.operation(self.alpaca,op,payload or {}))

    def reviewers(self,bundle,cfg):
        self.bundles.append(copy.deepcopy(bundle))
        proposal=bundle['proposal']
        return [dict(proposal_hash=proposal['proposal_hash'],decision='APPROVE',fatal_flags=[],reason_codes=[],
            component_scores={key:5 for key in a.RUBRIC_WEIGHTS[proposal['assigned_rubric']]}) for _ in range(2)]

    def execute(self):
        out=io.StringIO()
        with patch.object(a,'ROOT',self.root),patch.object(a,'PRIVATE_DIR',self.root/'private'),patch.object(a.dt,'datetime',Clock),patch.object(bridge,'datetime',Clock),patch.object(bridge,'consolidated_daily_bars',return_value=technical_bars()),patch.object(a,'_broker_bridge',side_effect=self.broker),patch.object(a,'independent_reviews',side_effect=self.reviewers),contextlib.redirect_stdout(out):
            code=a.run(a.argparse.Namespace(dry_run_fixture=False,live_dry_run=False))
        return code,out.getvalue()

    def test_expired_new_intent_observation_written_to_runtime_root_without_freeing_slot(self):
        import entry_expiry
        self.add_pending('third-nvda','NVDA','2026-11-25')
        self.intents[-1]['plan'].update(holding_sessions=1,assigned_rubric='short_1_5')
        self.intents[-1]['plan']['entry_expiry']=entry_expiry.metadata(self.intents[-1]['plan'],[
            dict(date='2026-11-25',open='09:30',close='16:00'),dict(date='2026-11-27',open='09:30',close='13:00')],
            '2026-11-25T15:00:00Z')
        self.write_state()
        # Deliberately stale module-level PRIVATE_DIR must never redirect runtime evidence.
        decoy=self.root/'decoy'
        with patch.object(a,'PRIVATE_DIR',decoy):
            out=io.StringIO()
            with patch.object(a,'ROOT',self.root),patch.object(a.dt,'datetime',Clock),patch.object(bridge,'datetime',Clock),patch.object(bridge,'consolidated_daily_bars',return_value=technical_bars()),patch.object(a,'_broker_bridge',side_effect=self.broker),contextlib.redirect_stdout(out):
                code=a.run(a.argparse.Namespace(dry_run_fixture=False,live_dry_run=False))
        self.assertEqual(code,2,out.getvalue())
        self.assertIn('pending_entry_limit',out.getvalue())
        rows=a.read_jsonl(self.root/'private/blocker_diagnostics.jsonl')
        self.assertTrue(any(row.get('stage')=='entry_expiry' and row.get('reason')=='entry_cancel_capability_unverified' for row in rows))
        self.assertFalse(decoy.exists())
        self.assertFalse(any(name=='place_stock_order' for name,_ in self.calls))
        self.assertFalse(entry_expiry.SAFE_PARENT_CANCEL_VERIFIED)
        self.assertEqual(len(a.read_jsonl(self.root/'private/order_intents.jsonl')),3)
        self.assertNotIn('entry_expiry',a.read_jsonl(self.root/'private/order_intents.jsonl')[0]['plan'])

    def test_runtime_failure_tokens_remain_bounded_and_public_safe(self):
        import run_cycle
        tokens=('pending_entry_policy_invalid','pending_entry_limit','same_symbol_pending_entry','pending_qualification_required',
                'pending_position_size_exceeded','pending_planned_risk_exceeded','funding_semantics_unverified',
                'funding_state_invalid','managed_repair_required','entry_state_busy','entry_state_invalid',
                'entry_calendar_unavailable','entry_calendar_invalid','entry_placement_outside_session',
                'entry_expiry_invalid','entry_cancel_capability_unverified')
        for token in tokens:
            line='BLOCKER '+token
            self.assertEqual(run_cycle.parse_failure_event(line),line,token)
            self.assertIsNone(run_cycle.parse_failure_event(line+':legacy-uber'))

    def test_all_three_validation_stages_receive_exact_snapshot_bound_proofs(self):
        stages=[]
        patches=[]
        for name in ('pre_review_validation','post_review_validation','broker_review_validation'):
            original=getattr(a,name)
            def check(plan,snapshot,*args,_original=original,_name=name,**kwargs):
                proof=kwargs.get('pending_proof')
                self.assertIsNotNone(proof)
                self.assertEqual(proof.root,self.root)
                self.assertTrue(pending_policy.valid(proof,snapshot))
                stages.append(_name)
                return _original(plan,snapshot,*args,**kwargs)
            patches.append(patch.object(a,name,side_effect=check))
        with contextlib.ExitStack() as stack:
            for item in patches:stack.enter_context(item)
            code,out=self.execute()
        self.assertEqual(code,0,out)
        self.assertIn('pre_review_validation',stages)
        self.assertIn('post_review_validation',stages)
        self.assertIn('broker_review_validation',stages)

    def test_checked_in_daily_three_allows_third_current_session_submission(self):
        self.intents[0]['submission_date']='2026-11-27'
        self.write_state()
        code,out=self.execute()
        self.assertEqual(code,0,out)
        self.assertEqual(self.cfg['max_daily_orders'],3)
        self.assertEqual(sum(name=='place_stock_order' for name,_ in self.calls),1)
        self.assertEqual(len(self.bundles),1)

    def test_checked_in_daily_three_blocks_fourth_after_counting_submissions(self):
        self.intents[0]['submission_date']='2026-11-27'
        self.write_state()
        code,out=self.execute()
        self.assertEqual(code,0,out)
        with patch.object(a.dt,'datetime',Clock):
            daily=a._daily_order_count(self.root/'order_ledger.jsonl')
        self.assertEqual(daily,3)
        proposal=self.bundles[0]['proposal']
        snapshot=self.bundles[0]['evidence']['broker_snapshot']
        errors,_=a.validate_order_with_details(proposal,snapshot,self.cfg,daily)
        self.assertIn('daily_order_limit',errors)
        below,_=a.validate_order_with_details(proposal,snapshot,self.cfg,2)
        self.assertNotIn('daily_order_limit',below)

    def test_daily_two_current_session_submissions_block_third_before_review(self):
        # Preserve coverage of the stricter configurable two-submission policy.
        self.cfg['max_daily_orders']=2
        (self.root/'autonomy_config.json').write_text(json.dumps(self.cfg))
        self.intents[0]['submission_date']='2026-11-27'
        self.write_state()
        code,out=self.execute()
        self.assertEqual(code,2,out);self.assertIn('daily_order_limit',out)
        self.assertEqual(self.bundles,[])
        self.assertFalse(any(name=='place_stock_order' for name,_ in self.calls))

    def test_unknown_manual_and_partial_pending_globally_block(self):
        for defect in ('manual','partial','unlinked'):
            with self.subTest(defect=defect):
                original=copy.deepcopy(self.parents)
                if defect=='manual':self.parents.append(pending('manual','NVDA')[1])
                elif defect=='partial':self.parents[0].update(status='partially_filled',filled_qty='1')
                else:self.parents.append(dict(self.parents[0]['legs'][0],client_order_id='foreign-target'))
                code,out=self.execute()
                self.assertEqual(code,2,out)
                self.assertFalse(any(name=='place_stock_order' for name,_ in self.calls))
                self.assertEqual(self.bundles,[])
                self.parents=original

    def test_fresh_broker_review_fourth_parent_blocks_after_independent_reviews(self):
        original=self.broker
        def broker(op,payload=None):
            if op=='review':
                intent,parent=pending('third-race','NVDA')
                intent['submission_date']='2026-11-25'
                self.parents.append(parent)
                a.append_jsonl(self.root/'private/order_intents.jsonl',intent)
                a.append_jsonl(self.root/'order_ledger.jsonl',dict(client_order_id='third-race',status='new'))
            return original(op,payload)
        self.broker=broker
        code,out=self.execute()
        self.assertEqual(code,2,out);self.assertIn('pending_entry_limit',out)
        self.assertEqual(len(self.bundles),1)
        self.assertFalse(any(name=='place_stock_order' for name,_ in self.calls))

    def test_margin_multiplier_never_replaces_gross_cash_and_net_bp_not_double_reserved(self):
        self.cash='500';self.bp='100'
        code,out=self.execute()
        self.assertEqual(code,0,out)
        placed=next(values for name,values in self.calls if name=='place_stock_order')
        self.assertEqual(placed['qty'],'1')
        self.assertEqual(self.bundles[0]['qualification']['cash_headroom_usd'],'100.0')

    def test_native_bridge_timeout_kills_descendant_before_entry_lock_release(self):
        import broker_process
        import entry_state
        import os
        import signal
        import subprocess
        import sys
        import time
        pid_path=self.root/'descendant.pid'
        child="import os,pathlib,time; pathlib.Path(%r).write_text(str(os.getpid())); time.sleep(30)" % str(pid_path)
        parent="import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',%r],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); time.sleep(30)" % child
        pid=None
        try:
            with entry_state.lock(self.root):
                with self.assertRaises(subprocess.TimeoutExpired):
                    broker_process.run_bridge([sys.executable,'-c',parent],input='',timeout=.25,run=subprocess.run)
                self.assertTrue(pid_path.exists())
                pid=int(pid_path.read_text())
                state=Path('/proc')/str(pid)/'stat'
                if state.exists():self.assertEqual(state.read_text().split()[2],'Z','network-capable descendant survived timeout')
        finally:
            if pid is None and pid_path.exists():pid=int(pid_path.read_text())
            if pid is not None:
                try:os.kill(pid,signal.SIGKILL)
                except ProcessLookupError:pass

    def test_runtime_rejects_truthy_enable_and_invalid_explicit_policy_domains(self):
        for enabled in (1,'true',[True],{'enabled':True}):
            with self.subTest(enabled=enabled):
                self.assertIn('autonomy_disabled',a.runtime_blockers(dict(self.cfg,enabled=enabled)))
        for cap in (True,False,'3',0,-1,4,None,3.0):
            with self.subTest(cap=cap):
                self.assertIn('pending_entry_policy_invalid',a.runtime_blockers(dict(self.cfg,max_pending_entry_parents=cap)))
        for policy in ('unapproved',None,True):
            self.assertIn('pending_entry_policy_invalid',a.runtime_blockers(dict(self.cfg,pending_entry_policy=policy)))
        legacy=dict(self.cfg)
        legacy.pop('pending_entry_policy');legacy.pop('max_pending_entry_parents');legacy.pop('entry_expiry_policy')
        self.assertEqual(a.runtime_blockers(legacy),[])
        self.assertEqual(a.runtime_blockers(dict(self.cfg,max_pending_entry_parents=2)),[])
        self.assertEqual(a.runtime_blockers(self.cfg),[])

    def test_native_bridge_success_returns_real_stdout_and_nonzero_status(self):
        import broker_process
        import subprocess
        import sys
        result=broker_process.run_bridge([sys.executable,'-c','import sys; print(sys.stdin.read()); sys.exit(3)'],input='offline fixture',timeout=3,run=subprocess.run,check=False)
        self.assertEqual(result.returncode,3)
        self.assertEqual(result.stdout,'offline fixture\n')

    def test_same_symbol_pending_blocks_real_config_before_review(self):
        self.candidate('UBER')
        code,out=self.execute()
        self.assertEqual(code,2,out);self.assertIn('same_symbol_pending_entry',out)
        self.assertEqual(self.bundles,[])
        self.assertFalse(any(name=='place_stock_order' for name,_ in self.calls))

    def test_checked_in_config_third_cross_day_entry_through_actual_bridge(self):
        code,out=self.execute()
        self.assertEqual(code,0,out)
        self.assertEqual(sum(name=='place_stock_order' for name,_ in self.calls),1)
        self.assertEqual(self.bundles[0]['qualification']['max_pending_entry_parents'],3)
        self.assertEqual(self.bundles[0]['qualification']['pending_entry_parents'],2)
        self.assertEqual(self.bundles[0]['qualification']['pending_reserved_notional_usd'],'400')
        self.assertEqual(self.bundles[0]['qualification']['cash_headroom_usd'],'9600.0')
        self.assertGreaterEqual(self.operations.count('reconcile_many'),2)
        self.assertIn('snapshot',self.operations);self.assertIn('review',self.operations)
        intent=a.read_jsonl(self.root/'private/order_intents.jsonl')[-1]
        self.assertEqual(intent['plan']['entry_expiry']['expires_at'],'2026-11-27T18:00:00Z')
        self.assertEqual(intent['submission_date'],'2026-11-27')
        self.assertNotIn('entry_expiry',a.read_jsonl(self.root/'private/order_intents.jsonl')[0]['plan'])
        placed=next(values for name,values in self.calls if name=='place_stock_order')
        self.assertEqual(placed['time_in_force'],'gtc');self.assertEqual(placed['order_class'],'bracket')
        self.assertNotIn('legacy-uber',out);self.assertNotIn('second-msft',out)
        self.assertEqual(self.execute()[0],0)
        self.assertEqual(sum(name=='place_stock_order' for name,_ in self.calls),1)
        self.candidate('NVDA')
        code,out=self.execute()
        self.assertEqual(code,2,out);self.assertIn('pending_entry_limit',out)
        self.assertEqual(len(self.bundles),1)
        self.assertEqual(sum(name=='place_stock_order' for name,_ in self.calls),1)
