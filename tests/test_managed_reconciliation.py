import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autotrader


class ManagedReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = {'action': 'BUY', 'symbol': 'ZS', 'quantity': 3, 'stop': 151.24, 'target': 184.37}
        self.write('private/broker_baseline.json', {'preexisting_symbols': ['AAPL']}, json_file=True)
        self.write('order_ledger.jsonl', {'client_order_id': 'parent', 'status': 'filled'})
        self.write('private/order_intents.jsonl', {'client_order_id': 'parent', 'plan': self.plan})
        self.write('trade_journal.jsonl', {'action': 'BUY', 'symbol': 'ZS', 'quantity': 3, 'entry': 162.79, 'status': 'filled'})
        self.write('private/protection_orders.jsonl', {'parent_client_order_id': 'parent', 'protection_client_order_id': 'replacement', 'symbol': 'ZS', 'quantity': 3, 'stop': 151.24, 'target': 184.37, 'registered_at': '2026-09-08T14:00:00Z'})
        self.target = dict(client_order_id='replacement', symbol='ZS', side='sell', position_intent='sell_to_close', order_class='oco', type='limit', qty='3', filled_qty='3', filled_avg_price='184.44', filled_at='2026-09-14T14:48:15.061577Z', status='filled', limit_price='184.37', time_in_force='gtc')
        self.stop = dict(self.target, client_order_id='stop', type='stop', filled_qty='0', status='canceled', stop_price='151.24')
        self.target['legs'] = [self.stop]
        self.parent = dict(client_order_id='parent', symbol='ZS', side='buy', position_intent='buy_to_open', order_class='bracket', qty='3', filled_qty='3', filled_avg_price='162.79', filled_at='2026-09-08T13:40:00Z', status='filled', legs=[dict(self.stop, client_order_id='old-stop', order_class='bracket'), dict(self.target, client_order_id='old-target', order_class='bracket', status='expired', filled_qty='0', legs=[])])
        self.calls = []
        self.positions = []
        self.open_orders = []

    def write(self, name, row, json_file=False):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row) + ('\n' if not json_file else ''))

    def broker(self, operation, payload):
        self.calls.append((operation, payload))
        self.assertEqual(operation, 'reconciliation_snapshot')
        refs = payload.get('client_order_ids', [])
        orders = {'parent': self.parent, 'replacement': self.target}
        return copy.deepcopy({'positions': self.positions, 'open_orders': self.open_orders, 'orders': [orders[r] for r in refs], 'captured_at': '2026-09-16T14:00:00Z'})

    def reconcile(self):
        import managed_reconciliation as m
        return m.reconcile(self.root, self.broker)

    def test_invalid_protection_evidence_never_writes(self):
        import managed_reconciliation as m
        original = copy.deepcopy(self.target)
        for changes in ({'qty': '4'}, {'filled_qty': '2'}, {'filled_avg_price': 'NaN'}, {'filled_at': '2026-09-14'}, {'side': 'buy'}, {'order_class': 'simple'}, {'symbol': 'OTHER'}, {'limit_price': '185'}, {'client_order_id': 'unrelated'}, {'status': 'partially_filled'}, {'legs': None}):
            with self.subTest(changes=changes):
                self.target = dict(copy.deepcopy(original), **changes)
                with self.assertRaises(m.ReconciliationBlocked):
                    self.reconcile()
                self.assertEqual(len(autotrader.read_jsonl(self.root / 'trade_journal.jsonl')), 1)

    def test_fresh_positions_must_match_post_fill_journal_exactly(self):
        import managed_reconciliation as m
        for positions in ([{'symbol': 'ZS', 'qty': '1', 'market_value': '184.44'}], None, {}, [{'symbol': 'OTHER', 'qty': '1'}]):
            with self.subTest(positions=positions):
                self.positions = positions
                with self.assertRaises(m.ReconciliationBlocked):
                    self.reconcile()
                self.assertEqual(len(autotrader.read_jsonl(self.root / 'trade_journal.jsonl')), 1)
        self.positions = [{'symbol': 'AAPL', 'qty': '8'}]
        self.assertEqual(len(self.reconcile()), 1, 'baseline holdings stay separate')

    def test_open_managed_lot_requires_exact_linked_protection(self):
        import managed_reconciliation as m
        self.target.update(status='new', filled_qty='0')
        self.stop.update(status='held')
        self.positions = [{'symbol': 'ZS', 'qty': '3'}]
        with self.assertRaises(m.ReconciliationBlocked):
            self.reconcile()
        self.open_orders = [copy.deepcopy(self.target)]
        self.assertEqual(self.reconcile(), [])
        self.open_orders[0]['qty'] = '4'
        with self.assertRaises(m.ReconciliationBlocked):
            self.reconcile()

    def test_journal_lifecycle_contradictions_fail_closed(self):
        import managed_reconciliation as m
        original_target = copy.deepcopy(self.target)
        self.target.update(status='new', filled_qty='0')
        self.stop.update(status='held')
        self.positions = [{'symbol': 'ZS', 'qty': '3'}]
        # Legacy LH row: closed lifecycle without closure key survives alongside a fresh SELL.
        with open(self.root / 'order_ledger.jsonl', 'a') as stream:
            stream.write(json.dumps({'client_order_id': 'legacy', 'status': 'closed', 'symbol': 'LH'}) + '\n')
        journal = autotrader.read_jsonl(self.root / 'trade_journal.jsonl')
        key = hashlib.sha256('parent|replacement|2026-09-14T14:48:15.061577Z'.encode()).hexdigest()
        # closed without any linked fill journal row -> contradiction
        with open(self.root / 'order_ledger.jsonl', 'a') as stream:
            stream.write(json.dumps({'client_order_id': 'parent', 'status': 'closed'}) + '\n')
        with self.assertRaises(m.ReconciliationBlocked):
            self.reconcile()
        # torn replay: journal SELL exists but lifecycle row does not -> recover lifecycle only
        self.teardown_files()
        self.setUp()
        self.target = original_target
        self.stop['legs'] = []
        with open(self.root / 'trade_journal.jsonl', 'a') as stream:
            stream.write(json.dumps({'action': 'SELL', 'symbol': 'ZS', 'quantity': 3, 'entry': 184.44, 'status': 'filled', 'closure_key': key, 'parent_client_order_id': 'parent', 'exit_client_order_id': 'replacement', 'timestamp': '2026-09-14T14:48:15.061577Z'}) + '\n')
        updates = self.reconcile()
        self.assertEqual(updates, [], 'no duplicate SELL for torn replay')
        closed = [r for r in autotrader.read_jsonl(self.root / 'order_ledger.jsonl') if r.get('status') == 'closed']
        self.assertEqual(len(closed), 1)

    def teardown_files(self):
        for name in ('order_ledger.jsonl', 'trade_journal.jsonl'):
            (self.root / name).unlink()

    def test_replacement_root_full_fill_repaired_once(self):
        self.assertIsNotNone(__import__('importlib').util.find_spec('managed_reconciliation'), 'shared reconciler missing')
        result = self.reconcile()
        self.assertEqual(result[0]['exit_client_order_id'], 'replacement')
        self.assertEqual(result[0]['entry'], 184.44)
        self.assertEqual(len(self.calls), 2, 'must recheck fresh positions after new fills')
        self.assertEqual(self.reconcile(), [])
        rows = autotrader.read_jsonl(self.root / 'trade_journal.jsonl')
        self.assertEqual(len(rows), 2)
        closed = autotrader.read_jsonl(self.root / 'order_ledger.jsonl')[-1]
        self.assertEqual(closed['closure_key'], rows[-1]['closure_key'])
        self.assertEqual(closed['exit_client_order_id'], 'replacement')
