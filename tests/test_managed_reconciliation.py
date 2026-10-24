import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import autotrader
import entry_fills
import managed_reconciliation as maintenance


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
        self.parent: dict[str, Any] = dict(client_order_id='parent', symbol='ZS', side='buy', position_intent='buy_to_open', order_class='bracket', qty='3', filled_qty='3', filled_avg_price='162.79', filled_at='2026-09-08T13:40:00Z', status='filled', legs=[dict(self.stop, client_order_id='old-stop', order_class='bracket'), dict(self.target, client_order_id='old-target', order_class='bracket', status='expired', filled_qty='0', legs=[])])
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

    def prepare_pending_fill(self):
        self.prepare_pending()
        self.plan.update(horizon='3 sessions', confidence=0.9, thesis='saved intent')
        self.write('private/order_intents.jsonl', {
            'client_order_id': 'parent', 'plan': self.plan,
            'candidate_id': 'candidate-a', 'proposal_hash': 'proposal-a'})
        self.parent.update(status='filled', filled_qty='3', filled_avg_price='162.70',
                           filled_at='2026-10-23T19:40:11Z', id='broker-parent')
        self.parent['legs'][0]['status'] = 'new'
        self.open_orders = copy.deepcopy(self.parent['legs'])
        self.positions = [{'symbol': 'ZS', 'qty': '3'}]

    def test_pending_full_fill_is_silently_ingested_once_before_position_checks(self):
        import managed_reconciliation as m
        import contextlib
        import io
        self.prepare_pending_fill()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(m.cli(['--root', str(self.root)], broker=self.broker), 0)
        self.assertEqual(out.getvalue(), '')
        written, summary = m.reconcile_detailed(self.root, self.broker)
        self.assertEqual(written, [])  # Entry accounting is not an exit notification.
        self.assertEqual(summary['status'], 'healthy')
        self.assertEqual(summary['pending'], [])
        rows = autotrader.read_jsonl(self.root / 'trade_journal.jsonl')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['action'], rows[0]['quantity'], rows[0]['entry']),
                         ('BUY', 3, 162.70))
        self.assertEqual(rows[0]['candidate_id'], 'candidate-a')
        self.assertEqual(rows[0]['broker_order_id'], 'broker-parent')
        self.assertTrue(rows[0]['entry_fill_key'])
        ledger = autotrader.read_jsonl(self.root / 'order_ledger.jsonl')
        self.assertEqual([r['status'] for r in ledger], ['new', 'filled'])
        self.assertEqual(autotrader.reconcile_pending_orders(
            self.root / 'order_ledger.jsonl', self.root / 'private/order_intents.jsonl',
            self.root / 'trade_journal.jsonl', broker=lambda *a: self.fail('already ingested')), [])
        autotrader.journal_confirmed_fill(self.root / 'trade_journal.jsonl', self.plan, self.parent)
        self.assertEqual(len(autotrader.read_jsonl(self.root / 'trade_journal.jsonl')), 1)

    def test_pending_fill_between_snapshot_reads_gets_one_bounded_refresh(self):
        import managed_reconciliation as m
        self.prepare_pending()
        old_parent = copy.deepcopy(self.parent)
        self.prepare_pending_fill()
        real_broker = self.broker
        def raced_broker(operation, payload):
            snapshot = real_broker(operation, payload)
            if len(self.calls) == 1:
                # Position/open-order reads happened after the exact parent read.
                snapshot['orders'] = [old_parent]
            return snapshot
        _, summary = m.reconcile_detailed(self.root, raced_broker)
        self.assertTrue(summary['verified'])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual([p for _, p in self.calls], [{'client_order_ids': ['parent']}] * 2)
        self.assertEqual(len(autotrader.read_jsonl(self.root / 'trade_journal.jsonl')), 1)

    def test_filled_pending_contract_mutations_fail_without_accounting(self):
        for changes in ({'symbol': 'OTHER'}, {'client_order_id': 'other'}, {'qty': '4'},
                        {'filled_qty': '2'}, {'filled_avg_price': 'NaN'},
                        {'filled_avg_price': '0'}, {'filled_avg_price': '163'},
                        {'filled_at': None}, {'filled_at': '2026-10-23'},
                        {'status': 'partially_filled'}, {'position_intent': 'sell_to_close'},
                        {'side': 'sell'}, {'time_in_force': 'day'}, {'limit_price': '163'},
                        {'extended_hours': True}, {'extended_hours': 0}, {'notional': '500'},
                        {'order_type': 'market'}, {'stop_price': '150'}):
            with self.subTest(changes=changes):
                self.setUp()
                self.prepare_pending_fill()
                self.parent.update(changes)
                self.assert_pending_blocked_without_writes()

    def test_pending_fill_verify_only_requires_repair_without_mutating_storage(self):
        import managed_reconciliation as m
        from sqlite_ledger import migrate_jsonl
        self.prepare_pending_fill()
        migrate_jsonl(self.root)
        # Materialize only the existing coordination locks before the audit.
        with __import__('entry_state').lock(self.root):
            pass
        (self.root / '.managed_exit_reconciliation.lock').touch()
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(m.ReconciliationBlocked, 'managed_repair_required'):
            m.reconcile_detailed(self.root, self.broker, verify_only=True)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns)
                                  for p in self.root.rglob('*') if p.is_file()})

    def test_unknown_holding_is_not_adopted_by_pending_entry_recovery(self):
        import managed_reconciliation as m
        self.prepare_pending()
        self.positions = [{'symbol': 'UNKNOWN', 'qty': '3'}]
        with self.assertRaisesRegex(m.ReconciliationBlocked, 'managed_position_untracked'):
            self.reconcile()
        self.assertEqual(autotrader.read_jsonl(self.root / 'trade_journal.jsonl'), [])
        self.assertEqual(len(self.calls), 1)

    def test_same_symbol_unconfirmed_holding_stays_blocked_after_bounded_refresh(self):
        import managed_reconciliation as m
        self.prepare_pending()
        self.positions = [{'symbol': 'ZS', 'qty': '3'}]
        self.assert_pending_blocked_without_writes()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(autotrader.read_jsonl(self.root / 'trade_journal.jsonl'), [])

    def test_pending_fill_refresh_broker_error_never_writes(self):
        self.prepare_pending_fill()
        real_broker = self.broker
        def broker(operation, payload):
            if self.calls:
                raise RuntimeError('offline broker error')
            return real_broker(operation, payload)
        import managed_reconciliation as m
        before = {p: p.read_bytes() for p in self.root.rglob('*.jsonl')}
        with self.assertRaisesRegex(RuntimeError, 'offline broker error'):
            m.reconcile(self.root, broker)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.jsonl')})

    def test_filled_pending_missing_open_protection_still_blocks(self):
        import managed_reconciliation as m
        self.prepare_pending_fill()
        self.open_orders = []
        with self.assertRaisesRegex(m.ReconciliationBlocked, 'managed_protection_missing'):
            self.reconcile()
        # True execution is accounted for, not mistaken for healthy protection.
        self.assertEqual(len(autotrader.read_jsonl(self.root / 'trade_journal.jsonl')), 1)

    def test_pending_fill_torn_lifecycle_append_replays_without_duplicate_journal(self):
        import managed_reconciliation as m
        self.prepare_pending_fill()
        with patch.object(m, 'append_jsonl', side_effect=OSError('offline ledger failure')):
            with self.assertRaisesRegex(OSError, 'offline ledger failure'):
                self.reconcile()
        self.assertEqual(len(autotrader.read_jsonl(self.root / 'trade_journal.jsonl')), 1)
        self.assertEqual(autotrader.read_jsonl(self.root / 'order_ledger.jsonl')[-1]['status'], 'new')
        self.assertEqual(self.reconcile(), [])
        self.assertEqual(len(autotrader.read_jsonl(self.root / 'trade_journal.jsonl')), 1)
        self.assertEqual(autotrader.read_jsonl(self.root / 'order_ledger.jsonl')[-1]['status'], 'filled')

    def test_torn_entry_equivalent_execution_time_preserves_original_key(self):
        import managed_reconciliation as m
        self.prepare_pending_fill()
        with patch.object(m, 'append_jsonl', side_effect=OSError('interrupted lifecycle')):
            with self.assertRaises(OSError):
                self.reconcile()
        before = (self.root / 'trade_journal.jsonl').read_bytes()
        self.parent['filled_at'] = '2026-10-23T19:40:11+00:00'
        _, summary = m.reconcile_detailed(self.root, self.broker)
        self.assertTrue(summary['verified'])
        self.assertEqual((self.root / 'trade_journal.jsonl').read_bytes(), before)
        autotrader.journal_confirmed_fill(self.root / 'trade_journal.jsonl', self.plan, self.parent)
        self.assertEqual((self.root / 'trade_journal.jsonl').read_bytes(), before)

    def test_persisted_entry_conflict_blocks_entire_batch_before_any_append(self):
        import managed_reconciliation as m
        self.prepare_pending_fill()
        earlier = copy.deepcopy(self.parent)
        earlier.update(client_order_id='earlier', id='broker-earlier', symbol='NET')
        for leg in earlier['legs']:
            leg.update(client_order_id='earlier-' + leg['type'], symbol='NET')
        intent = {'client_order_id': 'earlier', 'plan': dict(self.plan, symbol='NET')}
        # Explicitly place the fresh fill before the conflicting persisted fill.
        saved = json.loads((self.root / 'private/order_intents.jsonl').read_text())
        (self.root / 'private/order_intents.jsonl').write_text(
            ''.join(json.dumps(r) + '\n' for r in (intent, saved)))
        autotrader.append_jsonl(self.root / 'order_ledger.jsonl',
                               {'client_order_id': 'earlier', 'status': 'new'})
        autotrader.journal_confirmed_fill(self.root / 'trade_journal.jsonl', self.plan, self.parent)
        self.parent['filled_at'] = '2026-10-23T19:40:12Z'
        def broker(operation, payload):
            self.assertEqual(operation, 'reconciliation_snapshot')
            by_ref = {'parent': self.parent, 'earlier': earlier}
            return copy.deepcopy({'orders': [by_ref[r] for r in payload['client_order_ids']],
                                  'positions': self.positions + [{'symbol': 'NET', 'qty': '3'}],
                                  'open_orders': self.open_orders + earlier['legs']})
        before = {p: p.read_bytes() for p in self.root.rglob('*.jsonl')}
        with patch.object(m, 'append_jsonl', wraps=m.append_jsonl) as lifecycle, \
             patch('entry_fills.append_jsonl', wraps=autotrader.append_jsonl) as journal:
            with self.assertRaisesRegex(m.ReconciliationBlocked, 'managed_pending_entry_identity_conflict'):
                m.reconcile_detailed(self.root, broker)
            self.assertEqual((journal.call_count, lifecycle.call_count), (0, 0))
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.jsonl')})

    def test_batch_execution_collision_blocks_before_any_accounting_write(self):
        import entry_fills
        import managed_reconciliation as m
        for mode, ownership in ((mode, ownership) for mode in ('maintenance', 'autotrader')
                                for ownership in ('collision', 'distinct', 'legacy_missing')):
            with self.subTest(mode=mode, ownership=ownership):
                self.setUp()
                self.prepare_pending_fill()
                other = copy.deepcopy(self.parent)
                other.update(client_order_id='second', symbol='NET')
                if ownership == 'distinct':
                    other['id'] = 'broker-second'
                elif ownership == 'legacy_missing':
                    self.parent.pop('id')
                    other.pop('id')
                for leg in other['legs']:
                    leg.update(client_order_id='second-' + leg['type'], symbol='NET')
                saved = json.loads((self.root / 'private/order_intents.jsonl').read_text())
                second = dict(saved, client_order_id='second', plan=dict(self.plan, symbol='NET'))
                (self.root / 'private/order_intents.jsonl').write_text(
                    ''.join(json.dumps(r) + '\n' for r in (saved, second)))
                autotrader.append_jsonl(self.root / 'order_ledger.jsonl',
                                       {'client_order_id': 'second', 'status': 'new'})
                by_ref = {'parent': self.parent, 'second': other}
                def broker(operation, payload):
                    if operation == 'reconcile':
                        return copy.deepcopy(by_ref[payload['client_order_id']])
                    self.assertEqual(operation, 'reconciliation_snapshot')
                    return copy.deepcopy({'orders': [by_ref[r] for r in payload['client_order_ids']],
                        'positions': self.positions + [{'symbol': 'NET', 'qty': '3'}],
                        'open_orders': self.open_orders + other['legs']})
                before = {p: p.read_bytes() for p in self.root.rglob('*.jsonl')}
                def reconcile_batch():
                    if mode == 'maintenance':
                        return m.reconcile_detailed(self.root, broker)
                    return autotrader.reconcile_pending_orders(
                        self.root / 'order_ledger.jsonl', self.root / 'private/order_intents.jsonl',
                        self.root / 'trade_journal.jsonl', broker=broker)
                if ownership == 'collision':
                    with self.assertRaises((m.ReconciliationBlocked, entry_fills.EntryFillConflict)):
                        reconcile_batch()
                    self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.jsonl')})
                    self.assertEqual(autotrader.read_jsonl(self.root / 'trade_journal.jsonl'), [])
                else:
                    reconcile_batch()
                    rows = autotrader.read_jsonl(self.root / 'trade_journal.jsonl')
                    self.assertEqual([(r['symbol'], r['quantity']) for r in rows], [('ZS', 3), ('NET', 3)])
                    ledger = autotrader.read_jsonl(self.root / 'order_ledger.jsonl')
                    self.assertEqual([r['status'] for r in ledger], ['new', 'new', 'filled', 'filled'])

    def test_maintenance_autotrader_overlap_serializes_real_entry_accounting(self):
        import concurrent.futures
        import threading
        import managed_reconciliation as m
        for first in ('maintenance', 'autotrader'):
            with self.subTest(first=first):
                self.setUp()
                self.prepare_pending_fill()
                observed, release, competing = threading.Event(), threading.Event(), threading.Event()
                real_broker = self.broker
                def transport(operation, payload):
                    if not observed.is_set():
                        observed.set()
                        if not release.wait(2):
                            raise AssertionError('fixture release deadline')
                    if operation == 'reconcile':
                        self.assertEqual(payload, {'client_order_id': 'parent'})
                        return copy.deepcopy(self.parent)
                    return real_broker(operation, payload)
                def run(which):
                    if which == 'maintenance':
                        return m.reconcile_detailed(self.root, transport)
                    return autotrader.reconcile_pending_orders(
                        self.root / 'order_ledger.jsonl', self.root / 'private/order_intents.jsonl',
                        self.root / 'trade_journal.jsonl', broker=transport)
                def competitor():
                    competing.set()
                    return run('autotrader' if first == 'maintenance' else 'maintenance')
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    owner = pool.submit(run, first)
                    try:
                        self.assertTrue(observed.wait(2))
                        peer = pool.submit(competitor)
                        self.assertTrue(competing.wait(2))
                    finally:
                        release.set()
                    owner.result(timeout=5)
                    peer.result(timeout=5)
                self.assertEqual(len(autotrader.read_jsonl(self.root / 'trade_journal.jsonl')), 1)
                ledger = autotrader.read_jsonl(self.root / 'order_ledger.jsonl')
                self.assertEqual([r['status'] for r in ledger], ['new', 'filled'])

    def test_full_fill_observation_cannot_regress_to_unfilled_on_refresh(self):
        self.prepare_pending()
        old_parent = copy.deepcopy(self.parent)
        self.prepare_pending_fill()
        real_broker = self.broker
        def regressed_broker(operation, payload):
            snapshot = real_broker(operation, payload)
            if len(self.calls) == 2:
                snapshot.update(orders=[old_parent], positions=[], open_orders=[old_parent])
            return snapshot
        import managed_reconciliation as m
        with self.assertRaises(m.ReconciliationBlocked):
            m.reconcile(self.root, regressed_broker)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(autotrader.read_jsonl(self.root / 'trade_journal.jsonl'), [])

    def test_tngx_maintenance_ingests_the_delayed_full_entry_fill(self):
        import managed_reconciliation as m
        self.prepare_pending_fill()
        self.plan.update(symbol='TNGX', quantity=19, limit_price=23.50, stop=21, target=29)
        self.write('private/order_intents.jsonl', {'client_order_id': 'parent', 'plan': self.plan})
        self.write('order_ledger.jsonl', {'client_order_id': 'parent', 'status': 'new',
                                        'timestamp': '2026-10-23T19:39:58Z'})
        self.parent.update(symbol='TNGX', qty='19', filled_qty='19',
                           filled_avg_price='23.46', limit_price='23.50')
        for leg in self.parent['legs']:
            leg.update(symbol='TNGX', qty='19')
            leg['limit_price' if leg['type'] == 'limit' else 'stop_price'] = (
                '29' if leg['type'] == 'limit' else '21')
        self.open_orders = copy.deepcopy(self.parent['legs'])
        self.positions = [{'symbol': 'TNGX', 'qty': '19'}]
        _, summary = m.reconcile_detailed(self.root, self.broker)
        self.assertTrue(summary['verified'])
        rows = autotrader.read_jsonl(self.root / 'trade_journal.jsonl')
        self.assertEqual([(r['symbol'], r['quantity'], r['entry']) for r in rows], [('TNGX', 19, 23.46)])
        self.assertEqual(self.reconcile(), [])
        self.assertEqual(len(autotrader.read_jsonl(self.root / 'trade_journal.jsonl')), 1)

    def test_full_fill_with_stale_position_read_uses_fresh_snapshot(self):
        import managed_reconciliation as m
        self.prepare_pending_fill()
        real_broker = self.broker
        def broker(operation, payload):
            snapshot = real_broker(operation, payload)
            if len(self.calls) == 1:
                snapshot['positions'] = []
            return snapshot
        _, summary = m.reconcile_detailed(self.root, broker)
        self.assertTrue(summary['verified'])
        self.assertEqual(len(self.calls), 2)

    def prepare_legacy_failure(self):
        self.prepare_pending()
        self.open_orders = []
        (self.root / 'private/order_intents.jsonl').write_text('')
        proposed: dict[str, Any] = dict(timestamp='2026-10-08T15:00:00Z', status='proposed',
                        client_order_id='parent', parent_client_order_id='parent',
                        symbol='ZS', action='BUY', quantity=3, order_type='limit',
                        limit_price=162.79, evidence_id='evidence-a')
        failed = dict(proposed, status='failed', reason='broker_mcp_failure')
        self.write_legacy_rows([proposed, failed])
        return proposed, failed

    def write_legacy_rows(self, rows):
        (self.root / 'order_ledger.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))

    def test_legacy_never_submitted_failure_is_healthy_without_history_rewrite(self):
        import managed_reconciliation as m
        self.prepare_legacy_failure()
        before = {p: p.read_bytes() for p in self.root.rglob('*.jsonl')}
        for verify_only in (False, True):
            with self.subTest(verify_only=verify_only):
                written, summary = m.reconcile_detailed(self.root, self.broker, verify_only=verify_only)
                self.assertEqual(written, [])
                self.assertTrue(summary['verified'])
                self.assertEqual(summary['pending'], [])
                self.assertEqual(self.calls[-1][1], {'client_order_ids': []})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.jsonl')})

    def test_failed_rows_with_submission_or_intent_evidence_fail_before_broker_reads(self):
        import managed_reconciliation as m
        cases = ('intent', 'journal', 'registry', 'submission_started', 'submission_unknown',
                 'placed', 'new', 'filled', 'closed', 'canceled', 'later_submission')
        for case in cases:
            with self.subTest(case=case):
                self.setUp()
                proposed, failed = self.prepare_legacy_failure()
                if case == 'intent':
                    self.write('private/order_intents.jsonl', {'client_order_id': 'parent', 'plan': self.plan})
                elif case == 'journal':
                    self.write('trade_journal.jsonl', {'parent_client_order_id': 'parent', 'action': 'BUY',
                                                      'symbol': 'ZS', 'quantity': 3, 'status': 'filled'})
                elif case == 'registry':
                    self.write('private/protection_orders.jsonl', {'parent_client_order_id': 'parent'})
                elif case == 'later_submission':
                    self.write_legacy_rows([proposed, failed, dict(proposed, status='submission_started')])
                else:
                    self.write_legacy_rows([proposed, dict(proposed, status=case), failed])
                before = {p: p.read_bytes() for p in self.root.rglob('*.jsonl')}
                for verify_only in (False, True):
                    with self.assertRaises(m.ReconciliationBlocked):
                        m.reconcile_detailed(self.root, self.broker, verify_only=verify_only)
                self.assertEqual(self.calls, [])
                self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.jsonl')})

    def test_malformed_failed_history_cannot_be_rescued_by_later_valid_status(self):
        import managed_reconciliation as m
        cases = ('bare', 'no_proposal', 'wrong_reason', 'wrong_identity', 'invalid_symbol',
                 'invalid_quantity', 'invalid_price', 'filled_qty', 'filled_at',
                 'broker_order_id', 'parent_mismatch', 'missing_ref', 'invalid_ref', 'unhashable_failed_ref')
        for case in cases:
            with self.subTest(case=case):
                self.setUp()
                proposed, failed = self.prepare_legacy_failure()
                rows = [proposed, failed]
                if case == 'bare':
                    rows = [{'status': 'failed', 'client_order_id': 'parent'}]
                elif case == 'no_proposal':
                    rows = [failed]
                elif case == 'wrong_reason':
                    failed['reason'] = 'arbitrary_failure'
                elif case == 'wrong_identity':
                    failed['evidence_id'] = 'different'
                elif case == 'unhashable_failed_ref':
                    failed['client_order_id'] = []
                else:
                    field, value = {
                        'invalid_symbol': ('symbol', 'bad symbol'),
                        'invalid_quantity': ('quantity', -1), 'invalid_price': ('limit_price', 'NaN'),
                        'filled_qty': ('filled_qty', '1'), 'filled_at': ('filled_at', '2026-10-08T15:00:00Z'),
                        'broker_order_id': ('broker_order_id', 'unexpected'),
                        'parent_mismatch': ('parent_client_order_id', 'different'),
                        'missing_ref': ('client_order_id', None), 'invalid_ref': ('client_order_id', 'bad ref'),
                    }[case]
                    proposed[field] = failed[field] = value
                rows.append(dict(proposed, status='rejected'))
                self.write_legacy_rows(rows)
                with self.assertRaises(m.ReconciliationBlocked):
                    m.reconcile_detailed(self.root, self.broker)
                self.assertEqual(self.calls, [])

    def test_legacy_failure_does_not_release_an_unrelated_pending_reservation(self):
        import managed_reconciliation as m
        self.prepare_pending()
        _, failed = self.prepare_legacy_failure()
        proposed = dict(failed, status='proposed')
        proposed.pop('reason')
        proposed['client_order_id'] = proposed['parent_client_order_id'] = 'never-submitted'
        failed = dict(proposed, status='failed', reason='broker_mcp_failure')
        # Restore a real separate pending obligation and exact broker proof.
        self.prepare_pending()
        self.write_legacy_rows([proposed, failed, {'client_order_id': 'parent', 'status': 'new'}])
        _, summary = m.reconcile_detailed(self.root, self.broker)
        self.assertEqual([p['client_order_id'] for p in summary['pending']], ['parent'])
        self.assertEqual(summary['pending'][0]['remaining_notional'], '488.37')
        self.assertEqual(self.calls[-1][1], {'client_order_ids': ['parent']})

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


class EntryFillReplayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ManagedReconciliationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.prepare_pending_fill()
        self.path = self.fixture.root / 'trade_journal.jsonl'

    def interrupt(self):
        with patch.object(maintenance, 'append_jsonl', side_effect=OSError('torn lifecycle')):
            with self.assertRaises(OSError):
                self.fixture.reconcile()

    def test_conflicting_torn_full_entry_never_writes_journal_or_lifecycle(self):
        self.interrupt()
        original = copy.deepcopy(self.fixture.parent)
        before = {p: p.read_bytes() for p in self.fixture.root.rglob('*.jsonl')}
        for changes in ({'filled_at': '2026-10-23T19:40:12Z'},
                        {'filled_at': '2026-10-23T19:40:11.000000001Z'},
                        {'filled_avg_price': '162.60'}, {'filled_qty': '4', 'qty': '4'},
                        {'id': 'different-execution'}, {'id': None}, {'symbol': 'NET'}):
            with self.subTest(changes=changes):
                self.fixture.parent = dict(original, **changes)
                with self.assertRaises(maintenance.ReconciliationBlocked):
                    self.fixture.reconcile()
                self.assertEqual(before, {p: p.read_bytes() for p in self.fixture.root.rglob('*.jsonl')})

    def test_autotrader_wrapper_rejects_changed_identity_even_when_raw_key_matches(self):
        self.interrupt()
        before = self.path.read_bytes()
        for changes in ({'id': 'different-execution'}, {'id': None}, {'symbol': 'NET'}, {'side': 'sell'}):
            with self.subTest(changes=changes):
                with self.assertRaises(entry_fills.EntryFillConflict):
                    autotrader.journal_confirmed_fill(self.path, self.fixture.plan,
                                                     dict(self.fixture.parent, **changes))
                self.assertEqual(before, self.path.read_bytes())

    def test_autotrader_pending_conflict_cannot_write_lifecycle_before_validation(self):
        self.interrupt()
        self.fixture.parent['filled_avg_price'] = '162.60'
        before = {p: p.read_bytes() for p in self.fixture.root.rglob('*.jsonl')}
        with self.assertRaises(entry_fills.EntryFillConflict):
            autotrader.reconcile_pending_orders(
                self.fixture.root / 'order_ledger.jsonl',
                self.fixture.root / 'private/order_intents.jsonl', self.path,
                broker=lambda *args: copy.deepcopy(self.fixture.parent))
        self.assertEqual(before, {p: p.read_bytes() for p in self.fixture.root.rglob('*.jsonl')})

    def test_historical_key_is_unchanged_and_legacy_exact_repeat_is_read_only(self):
        order, plan = self.fixture.parent, self.fixture.plan
        qty, price = float(order['filled_qty']), float(order['filled_avg_price'])
        key = hashlib.sha256(json.dumps({'ref': order['client_order_id'],
            'filled_at': order['filled_at'], 'qty': str(qty), 'price': str(price)},
            sort_keys=True).encode()).hexdigest()
        row = dict(entry_fill_key=key, status='filled', symbol=plan['symbol'], action='BUY',
                   quantity=qty, entry=price, client_order_id='parent', broker_order_id=order['id'])
        self.path.write_text(json.dumps(row) + '\n')
        before = self.path.read_bytes()
        autotrader.journal_confirmed_fill(self.path, plan, order)
        self.assertEqual(before, self.path.read_bytes())
        with self.assertRaises(entry_fills.EntryFillConflict):
            autotrader.journal_confirmed_fill(self.path, plan,
                dict(order, filled_at='2026-10-23T19:40:11+00:00'))
        self.assertEqual(before, self.path.read_bytes())

    def test_partial_observation_and_symbol_only_row_are_not_full_entry_replays(self):
        order, plan = self.fixture.parent, self.fixture.plan
        rows = [dict(client_order_id='parent', broker_order_id=order['id'],
                     cumulative_filled_quantity='1', cumulative_filled_notional='162.7'),
                dict(status='filled', symbol='ZS', action='BUY', quantity=3, entry=162.7)]
        self.assertFalse(entry_fills.validate_entry_replay(rows, plan, order))

    def test_equivalent_offsets_and_numeric_representations_preserve_original_row(self):
        self.interrupt()
        before = self.path.read_bytes()
        for stamp in ('2026-10-23T15:40:11-04:00', '2026-10-23T19:40:11.000000Z'):
            autotrader.journal_confirmed_fill(self.path, self.fixture.plan,
                dict(self.fixture.parent, filled_at=stamp, filled_qty='3.000', filled_avg_price='162.700'))
            self.assertEqual(before, self.path.read_bytes())

    def test_ambiguous_duplicate_full_rows_fail_closed(self):
        self.interrupt()
        row = autotrader.read_jsonl(self.path)[0]
        with self.assertRaisesRegex(entry_fills.EntryFillConflict, 'ambiguous'):
            entry_fills.validate_entry_replay([row, row], self.fixture.plan, self.fixture.parent)
