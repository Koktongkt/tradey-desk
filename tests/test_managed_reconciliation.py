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

    def prepare_pending(self):
        self.plan = dict(self.plan, limit_price=162.79, order_type='limit')
        self.write('order_ledger.jsonl', {'client_order_id': 'parent', 'status': 'new'})
        self.write('private/order_intents.jsonl', {'client_order_id': 'parent', 'plan': self.plan})
        self.write('private/protection_orders.jsonl', {})
        (self.root / 'private/protection_orders.jsonl').write_text('')
        (self.root / 'trade_journal.jsonl').write_text('')
        target = dict(client_order_id='pending-target', symbol='ZS', side='sell',
                      position_intent='sell_to_close', order_class='bracket', type='limit',
                      qty='3', filled_qty='0', status='held', limit_price='184.37',
                      time_in_force='gtc', legs=None)
        stop = dict(target, client_order_id='pending-stop', type='stop',
                    limit_price=None, stop_price='151.24')
        self.parent = dict(client_order_id='parent', symbol='ZS', side='buy',
                           position_intent='buy_to_open', order_class='bracket', type='limit',
                           qty='3', filled_qty='0', status='new', limit_price='162.79',
                           time_in_force='gtc', legs=[target, stop])
        self.open_orders = [copy.deepcopy(self.parent)]

    def test_known_unfilled_bracket_is_verified_without_journaling(self):
        self.prepare_pending()
        before = {p: p.read_bytes() for p in self.root.rglob('*.jsonl')}
        self.assertEqual(self.reconcile(), [])
        self.assertEqual(self.calls, [('reconciliation_snapshot', {'client_order_ids': ['parent']})])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.jsonl')})

    def assert_pending_blocked_without_writes(self):
        import managed_reconciliation as m
        before = {p: p.read_bytes() for p in self.root.rglob('*.jsonl')}
        with self.assertRaises(m.ReconciliationBlocked):
            self.reconcile()
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.jsonl')})

    def test_pending_parent_contract_mutations_fail_closed(self):
        for changes in ({'symbol': 'OTHER'}, {'qty': '4'}, {'filled_qty': '1'},
                        {'status': 'partially_filled'}, {'status': 'filled'},
                        {'status': 'canceled'}, {'type': 'market'}, {'side': 'sell'},
                        {'order_class': 'simple'}, {'position_intent': 'sell_to_close'},
                        {'limit_price': '163'}, {'limit_price': 'NaN'},
                        {'time_in_force': 'day'}, {'extended_hours': True},
                        {'notional': '500'}, {'order_type': 'market'},
                        {'filled_at': '2026-10-08T15:00:00Z'}, {'filled_avg_price': '162.79'}):
            with self.subTest(changes=changes):
                self.prepare_pending()
                self.parent.update(changes)
                self.open_orders = [copy.deepcopy(self.parent)]
                self.assert_pending_blocked_without_writes()

    def test_pending_child_contract_mutations_fail_closed(self):
        for changes in ({'symbol': 'OTHER'}, {'qty': '4'}, {'filled_qty': '1'},
                        {'status': 'new'}, {'status': 'partially_filled'},
                        {'side': 'buy'}, {'order_class': 'oco'},
                        {'position_intent': 'buy_to_open'}, {'limit_price': '185'},
                        {'time_in_force': 'day'}, {'extended_hours': True},
                        {'notional': '500'}, {'order_type': 'stop'},
                        {'filled_at': '2026-10-08T15:00:00Z'}):
            with self.subTest(changes=changes):
                self.prepare_pending()
                self.parent['legs'][0].update(changes)
                self.open_orders = [copy.deepcopy(self.parent)]
                self.assert_pending_blocked_without_writes()

    def test_pending_missing_duplicate_or_unrelated_linkage_fails_closed(self):
        for case in ('missing_child', 'duplicate_child', 'parent_child_collision',
                     'missing_parent', 'different_child_id', 'open_qty_conflict',
                     'unknown_same_symbol', 'unknown_partial_same_symbol'):
            with self.subTest(case=case):
                self.prepare_pending()
                if case == 'missing_child':
                    self.parent['legs'].pop()
                    self.open_orders = [copy.deepcopy(self.parent)]
                elif case == 'duplicate_child':
                    self.parent['legs'][1] = copy.deepcopy(self.parent['legs'][0])
                    self.open_orders = [copy.deepcopy(self.parent)]
                elif case == 'parent_child_collision':
                    self.parent['legs'][0]['client_order_id'] = 'parent'
                    self.open_orders = [copy.deepcopy(self.parent)]
                elif case == 'missing_parent':
                    self.open_orders = copy.deepcopy(self.parent['legs'])
                elif case == 'different_child_id':
                    self.open_orders[0]['legs'][0]['client_order_id'] = 'unrelated'
                elif case == 'open_qty_conflict':
                    self.open_orders[0]['legs'][0]['qty'] = '4'
                else:
                    extra = dict(copy.deepcopy(self.parent['legs'][0]), client_order_id='unrelated')
                    extra['status'] = 'partially_filled' if case.startswith('unknown_partial') else 'new'
                    self.open_orders.append(extra)
                self.assert_pending_blocked_without_writes()

    def test_pending_submission_lifecycle_states_require_fresh_exact_readback(self):
        for status in ('submission_started', 'submission_unknown', 'placed', 'new',
                       'accepted', 'pending_new', 'held'):
            with self.subTest(status=status):
                self.prepare_pending()
                self.write('order_ledger.jsonl', {'client_order_id': 'parent', 'status': status})
                self.assertEqual(self.reconcile(), [])
                self.assertEqual(self.calls[-1][1], {'client_order_ids': ['parent']})

    def test_pending_entry_coexists_with_confirmed_exit_repair(self):
        pending_plan = dict(self.plan, symbol='UBER', limit_price=162.79, order_type='limit')
        pending_intent = {'client_order_id': 'pending', 'plan': pending_plan}
        target = dict(client_order_id='pending-target', symbol='UBER', side='sell',
                      position_intent='sell_to_close', order_class='bracket', type='limit',
                      qty='3', filled_qty='0', status='held', limit_price='184.37',
                      time_in_force='gtc', legs=None)
        parent = dict(client_order_id='pending', symbol='UBER', side='buy',
                      position_intent='buy_to_open', order_class='bracket', type='limit',
                      qty='3', filled_qty='0', status='new', limit_price='162.79',
                      time_in_force='gtc', legs=[target, dict(target, client_order_id='pending-stop',
                                                          type='stop', limit_price=None, stop_price='151.24')])
        for name, row in (('order_ledger.jsonl', {'client_order_id': 'pending', 'status': 'new'}),
                          ('private/order_intents.jsonl', pending_intent)):
            with (self.root / name).open('a') as stream:
                stream.write(json.dumps(row) + '\n')
        self.open_orders = [parent]
        original = self.broker
        def broker(operation, payload):
            refs = payload['client_order_ids']
            snapshot = original(operation, {'client_order_ids': [r for r in refs if r != 'pending']})
            if 'pending' in refs:
                snapshot['orders'].append(copy.deepcopy(parent))
            return snapshot
        import managed_reconciliation as m
        self.assertEqual(len(m.reconcile(self.root, broker)), 1)
        self.assertEqual(m.reconcile(self.root, broker), [])
        self.assertFalse(any(r.get('symbol') == 'UBER' for r in autotrader.read_jsonl(self.root / 'trade_journal.jsonl')))

    def test_cross_parent_child_ownership_collisions_block_before_writes(self):
        for closing in (False, True):
            with self.subTest(closing=closing):
                if closing:
                    self.teardown_files()
                    self.setUp()
                    plan = dict(self.plan, order_type='limit', limit_price=162.79)
                    target = dict(client_order_id='collision-target', symbol='ZS', side='sell',
                                  position_intent='sell_to_close', order_class='bracket', type='limit',
                                  qty='3', filled_qty='0', status='held', limit_price='184.37',
                                  time_in_force='gtc', legs=None)
                    pending = dict(client_order_id='pending', symbol='ZS', side='buy',
                                   position_intent='buy_to_open', order_class='bracket', type='limit',
                                   qty='3', filled_qty='0', status='new', limit_price='162.79',
                                   time_in_force='gtc', legs=[target, dict(target, client_order_id='collision-stop',
                                                                       type='stop', limit_price=None, stop_price='151.24')])
                    self.parent['legs'][0]['client_order_id'] = 'collision-stop'
                    self.parent['legs'][1]['client_order_id'] = 'collision-target'
                    ref = 'pending'
                    extra = pending
                    mapping = {'parent': self.parent, 'replacement': self.target, ref: extra}
                    self.open_orders = [pending]
                else:
                    self.prepare_pending()
                    extra = copy.deepcopy(self.parent)
                    extra.update(client_order_id='filled-parent', status='filled', filled_qty='3',
                                 filled_avg_price='162.79', filled_at='2026-09-08T13:40:00Z')
                    plan, ref = self.plan, 'filled-parent'
                    self.write('trade_journal.jsonl', {'action': 'BUY', 'symbol': 'ZS', 'quantity': 3,
                                                      'entry': 162.79, 'status': 'filled'})
                    self.positions = [{'symbol': 'ZS', 'qty': '3'}]
                    mapping = {'parent': self.parent, ref: extra}
                for name, row in (('order_ledger.jsonl', {'client_order_id': ref, 'status': 'new' if closing else 'filled'}),
                                  ('private/order_intents.jsonl', {'client_order_id': ref, 'plan': plan})):
                    with (self.root / name).open('a') as stream:
                        stream.write(json.dumps(row) + '\n')
                def broker(operation, payload):
                    self.assertEqual(operation, 'reconciliation_snapshot')
                    return copy.deepcopy({'positions': self.positions, 'open_orders': self.open_orders,
                                          'orders': [mapping[r] for r in payload['client_order_ids']]})
                import managed_reconciliation as m
                before = {p: p.read_bytes() for p in self.root.rglob('*.jsonl')}
                with self.assertRaises(m.ReconciliationBlocked):
                    m.reconcile(self.root, broker)
                self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.jsonl')})

    def test_unsupported_unknown_open_states_fail_closed(self):
        for status in ('pending_cancel', 'pending_replace', 'accepted_for_bidding', 'unknown-state'):
            with self.subTest(status=status):
                self.prepare_pending()
                self.open_orders.append(dict(copy.deepcopy(self.parent['legs'][0]),
                                             client_order_id='unknown', status=status))
                self.assert_pending_blocked_without_writes()

    def test_local_partial_fill_cannot_be_overridden_by_zero_fill_readback(self):
        for row in ({'status': 'partially_filled', 'filled_qty': '1'},
                    {'status': 'new', 'filled_qty': '1'}):
            with self.subTest(row=row):
                self.prepare_pending()
                self.write('order_ledger.jsonl', dict(row, client_order_id='parent'))
                self.assert_pending_blocked_without_writes()

    def test_pending_blocker_codes_are_preserved_by_cycle_diagnostics(self):
        import run_cycle
        for code in ('managed_pending_entry_invalid', 'managed_pending_entry_not_unfilled',
                     'managed_pending_entry_missing', 'managed_pending_entry_inconsistent',
                     'managed_order_ownership_ambiguous', 'managed_open_order_inconsistent'):
            with self.subTest(code=code):
                self.assertIn(code, run_cycle.ALLOWED_FAILURE_TOKENS)

    def test_local_selection_gaps_cannot_claim_empty_broker_health(self):
        for case in ('pending_cancel', 'pending_replace', 'accepted_for_bidding',
                     'unknown-state', 'missing_pending_intent', 'missing_filled_intent'):
            with self.subTest(case=case):
                self.prepare_pending()
                if case.startswith('missing_'):
                    (self.root / 'private/order_intents.jsonl').write_text('')
                    if case == 'missing_filled_intent':
                        self.write('order_ledger.jsonl', {'client_order_id': 'parent', 'status': 'filled'})
                else:
                    self.write('order_ledger.jsonl', {'client_order_id': 'parent', 'status': case, 'filled_qty': '1'})
                self.open_orders = []
                self.assert_pending_blocked_without_writes()

    def test_pending_incompatible_price_fields_and_boolean_types_fail_closed(self):
        for location, field, value in (('parent', 'stop_price', '999'),
                                       ('target', 'stop_price', '999'),
                                       ('stop', 'limit_price', '999'),
                                       ('parent', 'extended_hours', 0),
                                       ('target', 'extended_hours', 0)):
            with self.subTest(location=location, field=field):
                self.prepare_pending()
                order = self.parent if location == 'parent' else self.parent['legs'][0 if location == 'target' else 1]
                order[field] = value
                self.open_orders = [copy.deepcopy(self.parent)]
                self.assert_pending_blocked_without_writes()

    def test_unidentified_lifecycle_or_fill_rows_cannot_disappear(self):
        for status in ('new', 'filled', 'unknown-state', 'submission_started', 'rejected'):
            for ref in (None, '', False):
                with self.subTest(status=status, ref=ref):
                    self.prepare_pending()
                    with (self.root / 'order_ledger.jsonl').open('a') as stream:
                        stream.write(json.dumps({'status': status, 'client_order_id': ref, 'filled_qty': '1'}) + '\n')
                    self.assert_pending_blocked_without_writes()

    def test_orphan_saved_intent_cannot_be_omitted(self):
        self.prepare_pending()
        (self.root / 'order_ledger.jsonl').write_text('')
        self.open_orders = []
        self.assert_pending_blocked_without_writes()

    def test_saved_intent_with_proposed_lifecycle_is_still_verified(self):
        self.prepare_pending()
        self.write('order_ledger.jsonl', {'client_order_id': 'parent', 'status': 'proposed'})
        self.assertEqual(self.reconcile(), [])
        self.assertEqual(self.calls[-1][1], {'client_order_ids': ['parent']})

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

    def test_original_bracket_accepts_parent_verified_held_stop_omitted_from_open_orders(self):
        (self.root / 'private/protection_orders.jsonl').write_text('')
        target = dict(client_order_id='target', symbol='ZS', side='sell',
                      position_intent='sell_to_close', order_class='bracket',
                      type='limit', qty='3', filled_qty='0', status='new',
                      limit_price='184.37', time_in_force='gtc', legs=None)
        stop = dict(client_order_id='stop', symbol='ZS', side='sell',
                    position_intent='sell_to_close', order_class='bracket',
                    type='stop', qty='3', filled_qty='0', status='held',
                    stop_price='151.24', time_in_force='gtc', legs=None)
        self.parent['legs'] = [stop, target]
        self.positions = [{'symbol': 'ZS', 'qty': '3'}]
        self.open_orders = [copy.deepcopy(target)]

        self.assertEqual(self.reconcile(), [])

    def test_open_order_representation_must_match_the_same_parent_leg_type(self):
        (self.root / 'private/protection_orders.jsonl').write_text('')
        target = dict(client_order_id='target', symbol='ZS', side='sell',
                      position_intent='sell_to_close', order_class='bracket',
                      type='limit', qty='3', filled_qty='0', status='new',
                      limit_price='184.37', time_in_force='gtc', legs=None)
        stop = dict(client_order_id='stop', symbol='ZS', side='sell',
                    position_intent='sell_to_close', order_class='bracket',
                    type='stop', qty='3', filled_qty='0', status='held',
                    stop_price='151.24', time_in_force='gtc', legs=None)
        self.parent['legs'] = [stop, target]
        self.positions = [{'symbol': 'ZS', 'qty': '3'}]
        self.open_orders = [dict(stop, client_order_id='target', status='new')]

        import managed_reconciliation as m
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
