"""Offline boundary/coverage tests. Schemas captured by list_tools, not invented."""
import copy
import json
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from types import SimpleNamespace
import io
import subprocess
import sys
from watchdog.types import BrokerSnapshot
from watchdog.broker import ReadOnlyAlpaca, collect_broker

START = '2026-10-06T00:00:00Z'
END = '2026-10-07T10:00:00Z'
NOW = datetime(2026, 10, 7, 10, tzinfo=timezone.utc)


def order(ref='owned', **changes):
    return {'id': 'broker-' + ref, 'client_order_id': ref, 'symbol': 'AAPL',
            'side': 'buy', 'type': 'limit', 'status': 'partially_filled',
            'time_in_force': 'gtc', 'order_class': 'simple', 'qty': '4',
            'filled_qty': '2', 'filled_avg_price': '101.25',
            'filled_at': '2026-10-06T14:01:00Z', 'limit_price': '102',
            'submitted_at': '2026-10-06T14:00:00Z', 'legs': [], **changes}


def responses():
    return {'get_account_info': {'cash': '1000', 'equity': '1405', 'id': 'private-account'},
            'get_all_positions': [{'symbol': 'AAPL', 'side': 'long', 'qty': '4',
                                   'avg_entry_price': '100', 'current_price': '101.25',
                                   'market_value': '405', 'cost_basis': '400', 'unrealized_pl': '5'}],
            'get_orders': [order()], 'get_order_by_client_id': order(),
            'get_calendar': [{'date': '2026-10-06', 'open': '09:30', 'close': '16:00'}],
            'get_account_activities': []}

SCHEMAS = json.loads((Path(__file__).parent / 'fixtures/watchdog_broker_schemas.json').read_text())


class Transport:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    async def call_tool(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        return self.responses.get(name, {})


class PaginatedTransport(Transport):
    async def call_tool(self, name, args):
        if callable(self.responses.get(name)):
            self.calls.append((name, copy.deepcopy(args)))
            return self.responses[name](args)
        return await super().call_tool(name, args)


class BrokerSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_declared_totals_and_error_envelopes_cannot_claim_completeness(self):
        for extra in ({'total': 1}, {'count': 1}, {'isError': True}, {'is_error': True}):
            data = responses()
            data['get_orders'] = {'orders': [], **extra}
            result, _ = await self.collect(data)
            self.assertFalse(result.complete)
            self.assertEqual(result.coverage['orders'], 'unknown')

    async def test_nested_partial_fill_readback_deduplicates_exact_leg_without_provenance_conflict(self):
        data = responses()
        leg = order('protect', side='sell', type='stop', stop_price='90', filled_qty='1')
        data['get_orders'] = [order(legs=[leg], order_class='bracket')]
        data['get_order_by_client_id'] = leg
        result, _ = await self.collect(data, refs=['protect'])
        self.assertTrue(result.complete, result.coverage)
        self.assertEqual(len(result.orders), 1)
        self.assertEqual(result.orders[0]['legs'][0]['filled_qty'], Decimal('1'))

    async def test_corporate_action_without_adjustment_evidence_does_not_claim_complete_accounting(self):
        data = responses()
        data['get_account_activities'] = [{'id': 'split', 'activity_type': 'SPLIT', 'date': '2026-10-06',
                                           'symbol': 'AAPL', 'qty': '4'}]
        result, _ = await self.collect(data)
        self.assertEqual(result.coverage['activities'], 'complete')
        self.assertEqual(result.coverage['corporate_actions'], 'unknown')
        self.assertFalse(result.complete)

    async def test_structured_mcp_content_and_error_flag_are_respected(self):
        for flag in (False, True):
            data = responses()
            data['get_all_positions'] = SimpleNamespace(structured_content={'positions': data['get_all_positions']},
                                                        content=[], is_error=flag)
            result, _ = await self.collect(data)
            self.assertEqual(result.complete, not flag)
            self.assertEqual(result.coverage['positions'], 'unknown' if flag else 'complete')

    async def test_orders_and_activities_paginate_with_exact_validated_cursors(self):
        from watchdog.broker import ReadOnlyAlpaca, collect_broker
        data = responses()
        data['get_orders'] = lambda args: ([] if 'before_order_id' in args else
                                          [order(str(i)) for i in range(500)])
        data['get_account_activities'] = lambda args: ([] if 'page_token' in args else
            [{'id': str(i), 'activity_type': 'DIV', 'date': '2026-10-06', 'net_amount': '1.25',
              'symbol': 'AAPL', 'secret': 'never-persist'} for i in range(100)])
        client = PaginatedTransport(data)
        with patch('watchdog.broker.utc_now', return_value=NOW):
            result = await collect_broker(ReadOnlyAlpaca(client, SCHEMAS), [], START, END)
        self.assertTrue(result.complete, result.coverage)
        self.assertEqual(len(result.orders), 500)
        self.assertEqual(len(result.activities), 100)
        self.assertEqual(result.activities[0]['net_amount'], Decimal('1.25'))
        self.assertNotIn('never-persist', str(result))
        self.assertIn(('get_orders', {'status': 'open', 'nested': True, 'limit': 500,
                                     'direction': 'desc', 'before_order_id': 'broker-499'}), client.calls)
        self.assertIn(('get_account_activities', {'after': START, 'until': END, 'direction': 'asc',
                                                 'page_size': 100, 'page_token': '99'}), client.calls)

    async def test_missing_cursor_schema_repeated_pages_or_partial_flags_are_unknown(self):
        from watchdog.broker import ReadOnlyAlpaca, collect_broker
        for name, count, cursor, collection in (('get_orders', 500, 'before_order_id', 'orders'),
                                               ('get_account_activities', 100, 'page_token', 'activities')):
            page = ([order(str(i)) for i in range(count)] if collection == 'orders' else
                    [{'id': str(i), 'activity_type': 'DIV', 'date': '2026-10-06', 'net_amount': '1'} for i in range(count)])
            for case in ('schema', 'repeat', 'partial'):
                schemas = copy.deepcopy(SCHEMAS)
                data = responses()
                data[name] = page
                if case == 'schema':
                    del schemas[name]['properties'][cursor]
                elif case == 'partial':
                    data[name] = {collection: [], 'has_more': True}
                client = Transport(data)
                with self.subTest(name=name, case=case), patch('watchdog.broker.utc_now', return_value=NOW):
                    result = await collect_broker(ReadOnlyAlpaca(client, schemas), [], START, END)
                    self.assertFalse(result.complete)
                    self.assertEqual(result.coverage[collection], 'unknown')
                    self.assertLessEqual(len(client.calls), 8)

    async def test_activity_invalid_numeric_timestamp_or_missing_amount_is_unknown(self):
        for row in ({'id': 'a', 'activity_type': 'DIV', 'net_amount': True, 'date': '2026-10-06'},
                    {'id': 'a', 'activity_type': 'DIV', 'date': '2026-10-06'},
                    {'id': 'a', 'activity_type': 'FILL', 'transaction_time': 123, 'qty': '1', 'price': '5'},
                    {'id': 'a', 'activity_type': 'FILL', 'transaction_time': START, 'qty': '-1', 'price': '5'},
                    {'id': 'a', 'activity_type': 'UNKNOWN', 'date': '2026-10-06', 'net_amount': '1'}):
            data = responses()
            data['get_account_activities'] = [row]
            with self.subTest(row=row):
                result, _ = await self.collect(data)
                self.assertFalse(result.complete)
                self.assertEqual(result.coverage['distribution'], 'unknown')

    async def collect(self, data=None, schemas=None, refs=None):
        from watchdog.broker import ReadOnlyAlpaca, collect_broker
        client = Transport(responses() if data is None else data)
        with patch('watchdog.broker.utc_now', return_value=NOW):
            result = await collect_broker(ReadOnlyAlpaca(client, SCHEMAS if schemas is None else schemas),
                                          ['owned'] if refs is None else refs, START, END)
        return result, client

    async def test_missing_capability_is_typed_unknown_not_fabricated_zero(self):
        schemas = copy.deepcopy(SCHEMAS)
        del schemas['get_account_activities']
        result, client = await self.collect(schemas=schemas)
        self.assertFalse(result.complete)
        self.assertEqual(result.activities, [])
        self.assertEqual(result.coverage['account_cashflows'], 'unknown')
        self.assertEqual(result.coverage['distribution'], 'unknown')
        self.assertIn('account_cashflows_unknown', result.coverage['reasons'])
        self.assertIn('distribution_coverage_unknown', result.coverage['reasons'])
        self.assertFalse(any(name == 'get_account_activities' for name, _ in client.calls))

    async def test_malformed_or_error_response_is_not_empty_complete(self):
        for name in ('get_account_info', 'get_all_positions', 'get_orders', 'get_calendar', 'get_account_activities'):
            for payload in ({'error': 'secret-value'}, {'text': 'secret-value'}, None, [False]):
                data = responses()
                data[name] = payload
                with self.subTest(name=name, payload=payload):
                    result, _ = await self.collect(data)
                    self.assertFalse(result.complete)
                    self.assertNotIn('secret-value', str(result))

    async def test_invalid_numeric_domains_or_missing_order_fields_are_unknown(self):
        for changes in ({'qty': True}, {'qty': '-1'}, {'filled_qty': 'NaN'},
                        {'filled_qty': '5'}, {'filled_avg_price': '0'},
                        {'filled_at': None}, {'side': None}, {'time_in_force': None}):
            data = responses()
            data['get_orders'] = [order(**changes)]
            with self.subTest(changes=changes):
                result, _ = await self.collect(data)
                self.assertFalse(result.complete)
                self.assertEqual(result.coverage['orders'], 'unknown')

    async def test_exact_readback_identity_and_concurrent_fill_conflict_are_unknown(self):
        for row in (order('unrequested'), order(filled_qty='3')):
            data = responses()
            data['get_order_by_client_id'] = row
            result, _ = await self.collect(data)
            self.assertFalse(result.complete)
            self.assertEqual(result.coverage['references'], 'unknown')

    async def test_snapshot_timestamp_numeric_stale_future_and_slow_are_unknown(self):
        for timestamp in (12345, True, '2026-10-07T09:00:00Z', '2026-10-07T11:00:00Z'):
            data = responses()
            data['get_all_positions'] = {'positions': data['get_all_positions'], 'captured_at': timestamp}
            with self.subTest(timestamp=timestamp):
                result, _ = await self.collect(data)
                self.assertFalse(result.complete)
                self.assertEqual(result.coverage['positions'], 'unknown')
        from watchdog.broker import ReadOnlyAlpaca, collect_broker
        later = datetime(2026, 10, 7, 10, 2, tzinfo=timezone.utc)
        with patch('watchdog.broker.utc_now', side_effect=[NOW, later]):
            result = await collect_broker(ReadOnlyAlpaca(Transport(responses()), SCHEMAS), [], START, END)
        self.assertFalse(result.complete)
        self.assertIn('broker_snapshot_stale', result.coverage['reasons'])

    async def test_model_fields_and_numeric_reference_or_interval_never_reach_transport(self):
        from watchdog.broker import ReadOnlyAlpaca, collect_broker
        for refs, start, end in ([{'action': 'SELL'}], START, END), ([42], START, END), ([], 123, END), ([], END, START):
            client = Transport(responses())
            with self.subTest(refs=refs, start=start), self.assertRaises(ValueError):
                await collect_broker(ReadOnlyAlpaca(client, SCHEMAS), refs, start, end)
            self.assertEqual(client.calls, [])

    async def test_normalized_snapshot_has_cumulative_fill_and_no_raw_account(self):
        from watchdog.broker import ReadOnlyAlpaca, collect_broker
        client = Transport(responses())
        reader = ReadOnlyAlpaca(client, SCHEMAS)
        with patch('watchdog.broker.utc_now', return_value=NOW):
            result = await collect_broker(reader, ['owned'], START, END)
        self.assertTrue(result.complete, result.coverage)
        self.assertEqual(result.orders[0]['filled_qty'], Decimal('2'))
        self.assertEqual(result.orders[0]['filled_avg_price'], Decimal('101.25'))
        self.assertEqual(result.orders[0]['filled_at'], '2026-10-06T14:01:00+00:00')
        self.assertEqual(result.orders[0]['provenance']['filled_qty'], 'get_orders.filled_qty')
        self.assertEqual(result.account['equity'], Decimal('1405'))
        self.assertNotIn('id', result.account)
        self.assertEqual(result.coverage['account_cashflows'], 'complete')
        self.assertEqual(result.coverage['interval'], {'start': START, 'end': END})
        self.assertEqual([args for name, args in client.calls if name == 'get_order_by_client_id'],
                         [{'client_order_id': 'owned'}])


class BrokerWorkerTests(unittest.TestCase):
    def test_worker_serializes_only_normalized_snapshot_and_sanitizes_failure(self):
        from watchdog.broker import main
        snapshot = BrokerSnapshot({'cash': Decimal('1.25')}, [], [], [], [], END, False,
                                  {'reasons': ['distribution_coverage_unknown']})
        for result in (snapshot, RuntimeError('credential-or-raw-response')):
            worker = AsyncMock(return_value=result) if isinstance(result, BrokerSnapshot) else AsyncMock(side_effect=result)
            output, errors = io.StringIO(), io.StringIO()
            with patch('watchdog.broker.collect_configured', worker), \
                 patch('sys.stdin', io.StringIO(json.dumps({'refs': [], 'start': START, 'end': END}))), \
                 patch('sys.stdout', output), patch('sys.stderr', errors):
                code = main()
            self.assertNotIn('credential-or-raw-response', output.getvalue() + errors.getvalue())
            self.assertEqual(code, 0 if isinstance(result, BrokerSnapshot) else 3)
            if code == 0:
                self.assertEqual(json.loads(output.getvalue())['account']['cash'], '1.25')
            else:
                self.assertEqual(json.loads(errors.getvalue()), {'error': 'broker_read_failed'})
                self.assertEqual(output.getvalue(), '')

    def test_module_worker_rejects_arbitrary_operation_without_live_calls(self):
        result = subprocess.run([sys.executable, '-m', 'watchdog.broker'], input='{"operation":"place"}',
                                text=True, capture_output=True, timeout=30,
                                cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, '')
        self.assertEqual(json.loads(result.stderr), {'error': 'broker_read_failed'})


class ConfiguredBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_configured_reader_uses_existing_config_and_only_exact_reads(self):
        from watchdog.broker import collect_configured
        client = Transport(responses())
        client.list_tools = AsyncMock(return_value=[SimpleNamespace(name=name, inputSchema=schema)
                                                    for name, schema in SCHEMAS.items()])
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)
        with patch('watchdog.broker.alpaca_mcp_config', return_value={'opaque': 'config'}) as config, \
             patch('watchdog.broker.Client', return_value=context) as factory, \
             patch('watchdog.broker.utc_now', return_value=NOW):
            result = await collect_configured({'refs': ['owned'], 'start': START, 'end': END})
        self.assertTrue(result.complete)
        config.assert_called_once_with()
        factory.assert_called_once_with({'opaque': 'config'})
        self.assertEqual(set(name for name, _ in client.calls), set(SCHEMAS))

    async def test_nonpaper_mode_rejected_before_client_construction(self):
        from watchdog.broker import collect_configured
        completed = SimpleNamespace(returncode=0, stdout=json.dumps({
            'ALPACA_API_KEY': 'fixture-key', 'ALPACA_SECRET_KEY': 'fixture-secret', 'ALPACA_PAPER_TRADE': 'false'}))
        with patch('broker_credentials.read_mcp_env_process', return_value=completed), \
             patch('watchdog.broker.Client') as factory:
            with self.assertRaisesRegex(RuntimeError, 'non_paper_alpaca_config_forbidden'):
                await collect_configured({'refs': [], 'start': START, 'end': END})
        factory.assert_not_called()

    async def test_untrusted_payload_is_rejected_before_credentials(self):
        from watchdog.broker import collect_configured
        with patch('watchdog.broker.alpaca_mcp_config') as config:
            with self.assertRaises(ValueError):
                await collect_configured({'refs': [], 'start': START, 'end': END, 'operation': 'place'})
        config.assert_not_called()


class BrokerBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_schema_pattern_changes_fail_closed(self):
        schemas = copy.deepcopy(SCHEMAS)
        schemas['get_order_by_client_id']['properties']['client_order_id']['pattern'] = '^verified-'
        client = Transport()
        with self.assertRaises(ValueError):
            await ReadOnlyAlpaca(client, schemas).call('get_order_by_client_id', {'client_order_id': 'owned'})
        self.assertEqual(client.calls, [])

    async def test_write_tool_rejected_before_invocation(self):
        from watchdog.broker import ReadOnlyAlpaca
        client = Transport()
        schemas = {**SCHEMAS, 'place_stock_order': {'properties': {}}}
        reader = ReadOnlyAlpaca(client, schemas)
        for name in ('place_stock_order', 'cancel_order', 'protect', 'get_unknown'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                await reader.call(name, {})
        self.assertEqual(client.calls, [])

    async def test_remote_schema_references_rejected_before_transport(self):
        schemas = copy.deepcopy(SCHEMAS)
        schemas['get_account_info']['allOf'] = [{'$ref': 'https://untrusted.invalid/schema'}]
        client = Transport()
        with patch('urllib.request.urlopen', side_effect=AssertionError('network_forbidden')), self.assertRaises(ValueError):
            await ReadOnlyAlpaca(client, schemas).call('get_account_info', {})
        self.assertEqual(client.calls, [])

    async def test_schema_and_logical_parameters_validated_before_transport(self):
        from watchdog.broker import ReadOnlyAlpaca
        client = Transport()
        reader = ReadOnlyAlpaca(client, SCHEMAS)
        valid = {'status': 'open', 'nested': True, 'limit': 500, 'direction': 'desc'}
        for args in ({**valid, 'action': 'SELL'}, {**valid, 'status': 'closed'},
                     {**valid, 'nested': False}, {**valid, 'limit': True},
                     {'status': 'open'}, {'client_order_id': 5}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                await reader.call('get_orders', args)
        altered = copy.deepcopy(SCHEMAS)
        del altered['get_orders']['properties']['nested']
        with self.assertRaises(ValueError):
            await ReadOnlyAlpaca(client, altered).call('get_orders', valid)
        self.assertEqual(client.calls, [])
        await reader.call('get_orders', valid)
        self.assertEqual(client.calls, [('get_orders', valid)])
        with self.assertRaises(ValueError):
            await reader.call('get_account_activities', {'after': '2026-10-06T00:00:00Z'})

    async def test_required_live_parameters_and_schema_enums_are_not_dropped(self):
        from watchdog.broker import ReadOnlyAlpaca
        client = Transport()
        for mutate in ('required', 'enum', 'type'):
            altered = copy.deepcopy(SCHEMAS)
            if mutate == 'required':
                altered['get_orders']['required'] = ['symbols']
            elif mutate == 'enum':
                altered['get_orders']['properties']['status']['enum'] = ['closed']
            else:
                altered['get_orders']['properties']['nested']['type'] = 'string'
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                await ReadOnlyAlpaca(client, altered).call('get_orders',
                    {'status': 'open', 'nested': True, 'limit': 500, 'direction': 'desc'})
        self.assertEqual(client.calls, [])
