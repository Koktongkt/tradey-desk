"""Bounded pending qualification against exact broker and durable state."""
import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
import autotrader as a
from support_fixtures import broker_snapshot, policy_config


def pending(ref='one', symbol='AAPL'):
    plan = dict(action='BUY', symbol=symbol, quantity=2, order_type='limit', limit_price=100,
                stop=95, target=110, horizon='3 sessions', confidence=.9, thesis='saved', risk_reward=2)
    child = dict(symbol=symbol, side='sell', position_intent='sell_to_close',
                 order_class='bracket', time_in_force='gtc', qty='2', filled_qty='0', status='held')
    parent = dict(client_order_id=ref, symbol=symbol, side='buy', position_intent='buy_to_open',
                  order_class='bracket', time_in_force='gtc', type='limit', qty='2', filled_qty='0',
                  limit_price='100', status='new', legs=[
                      dict(child, client_order_id=ref+'-target', type='limit', limit_price='110'),
                      dict(child, client_order_id=ref+'-stop', type='stop', stop_price='95')])
    return {'client_order_id':ref, 'plan':plan}, parent


class PendingCapacityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='pc-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'private').mkdir()
        (self.root/'private/broker_baseline.json').write_text(json.dumps({'preexisting_symbols':[]}))
        self.cfg = policy_config()
        self.cfg.update(max_pending_entry_parents=2, pending_entry_policy='exact_owned_zero_fill_v1')
        now = dt.datetime.now(dt.timezone.utc)
        self.snapshot = broker_snapshot(captured_at=now.isoformat(),
            quote={'bid':99.98,'ask':100,'timestamp':now.isoformat()}, cash=10000,
            earnings_status='reported',earnings_sessions_away=None,
            trading_sessions=[(now.date()+dt.timedelta(days=i)).isoformat() for i in range(31)])
        self.snapshot.update(cash_semantics='gross',buying_power_semantics='available_net')
        self.intents, self.parents = [], []
        self.add_pending()
        self.order = dict(self.intents[0]['plan'],symbol='DELL')

    def add_pending(self, ref='one', symbol='AAPL'):
        intent, parent = pending(ref,symbol)
        self.intents.append(intent); self.parents.append(parent)
        self.rows('private/order_intents.jsonl',self.intents)
        self.rows('order_ledger.jsonl',[{'client_order_id':i['client_order_id'],'status':'new'} for i in self.intents])
        self.snapshot['open_orders']=copy.deepcopy(self.parents)

    def rows(self,name,rows):
        (self.root/name).write_text(''.join(json.dumps(r)+'\n' for r in rows))

    def broker(self,op,payload):
        self.assertEqual(op,'reconcile_many')
        return {'orders':copy.deepcopy([p for p in self.parents if p['client_order_id'] in payload['client_order_ids']])}

    def proof(self):
        import pending_policy as p
        return p.qualify(self.root,self.snapshot,self.broker)

    def errors(self, proof, exposure=0):
        return a.validate_order(self.order,self.snapshot,self.cfg,0,exposure,set(),pending_proof=proof)

    def test_exact_owned_pending_permits_second_different_entry(self):
        self.assertEqual(self.errors(self.proof()),[])
        self.assertIn('active_broker_order',a.validate_order(self.order,self.snapshot,self.cfg,0))

    def test_unknown_funding_semantics_and_invalid_numbers_block(self):
        import pending_policy as p
        for cash_tag,bp_tag in ((None,'available_net'),('gross',None),('unknown','available_net')):
            with self.subTest(cash=cash_tag,bp=bp_tag):
                self.snapshot['cash_semantics']=cash_tag
                self.snapshot['buying_power_semantics']=bp_tag
                self.assertIn('funding_semantics_unverified',self.errors(self.proof()))
        self.snapshot.update(cash_semantics='gross',buying_power_semantics='available_net')
        for value in (True,float('nan'),float('inf'),None,-1):
            with self.subTest(value=value),self.assertRaises(RuntimeError):
                self.snapshot['cash']=value
                self.proof()

    def test_sizing_uses_same_reservation_and_blocks_overrisk_pending(self):
        self.snapshot.update(cash=300,buying_power=200)
        candidate={'symbol':'DELL','planned_exit_at':self.snapshot['trading_sessions'][2]+'T20:00:00Z','setup_type':'breakout'}
        proposal,errors=a.build_canonical_proposal(candidate,self.snapshot,self.cfg,0,pending_proof=self.proof())
        self.assertEqual(errors,[])
        self.assertEqual(proposal['quantity'],1)
        self.intents[0]['plan']['stop']=50
        self.parents[0]['legs'][1]['stop_price']='50'
        self.rows('private/order_intents.jsonl',self.intents)
        self.snapshot['open_orders']=copy.deepcopy(self.parents)
        self.assertIn('pending_planned_risk_exceeded',self.errors(self.proof()))

    def test_pending_reservation_applies_to_cash_and_aggregate_not_bp_twice(self):
        self.snapshot.update(cash=300, buying_power=200)
        proof = self.proof()
        self.assertIn('insufficient_cash',self.errors(proof))
        self.assertNotIn('insufficient_buying_power',self.errors(proof))
        self.snapshot.update(cash=10000,buying_power=10000)
        proof = self.proof()
        self.assertIn('account_cap_exceeded',self.errors(proof,9700))

    def test_capacity_duplicate_and_stale_proof_fail_closed(self):
        proof = self.proof()
        self.order['symbol']='AAPL'
        self.assertIn('same_symbol_pending_entry',self.errors(proof))
        self.order['symbol']='DELL'
        self.add_pending('two','MSFT')
        self.assertIn('pending_qualification_required',self.errors(proof))
        self.assertIn('pending_entry_limit',self.errors(self.proof()))
        proof = self.proof()
        self.snapshot['cash']-=1
        self.assertIn('pending_qualification_required',self.errors(proof))
