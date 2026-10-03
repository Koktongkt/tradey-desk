import asyncio
import unittest
from typing import Any
from unittest.mock import patch

import broker_mcp_bridge


class _AcceptingAlpaca:
    def __init__(self):
        self.calls = []

    async def call(self, name, arguments=None):
        self.calls.append((name, arguments))
        return {"status": "accepted"}


class BrokerMcpConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_readback_orders_normalizes_nested_status_and_fallback_in_reference_order(self):
        class ReadOnlyAlpaca:
            def __init__(self):
                self.calls = []

            async def call(self, name, values=None):
                self.calls.append((name, values))
                ref = values["client_order_id"]
                if ref == "first":
                    return {"data": {"order": {"status": "filled", "client_order_id": ref}}}
                return [{"client_order_id": ref}]

        alpaca = ReadOnlyAlpaca()
        orders = await broker_mcp_bridge.readback_orders(alpaca, ["first", "second"])
        self.assertEqual(orders, [
            {"status": "filled", "client_order_id": "first"},
            {"client_order_id": "second"},
        ])
        self.assertEqual(alpaca.calls, [
            ("get_order_by_client_id", {"client_order_id": "first"}),
            ("get_order_by_client_id", {"client_order_id": "second"}),
        ])

    async def test_batch_normalization_waits_for_all_readbacks(self):
        first_done = asyncio.Event()
        release_second = asyncio.Event()
        class FakeAlpaca:
            async def call(self, name, arguments):
                if arguments["client_order_id"] == "first":
                    first_done.set()
                else:
                    await release_second.wait()
                return {"status": "accepted"}
        original = broker_mcp_bridge.find_mapping_with_keys
        with patch("broker_mcp_bridge.find_mapping_with_keys", wraps=original) as normalize:
            task = asyncio.create_task(broker_mcp_bridge.readback_orders(FakeAlpaca(), ["first", "second"]))
            try:
                await first_done.wait()
                await asyncio.sleep(0)
                self.assertEqual(normalize.call_count, 0)
            finally:
                release_second.set()
                await task
            self.assertEqual(normalize.call_count, 2)

    async def test_single_reconcile_awaits_readback_in_same_task(self):
        seen = []
        class FakeAlpaca:
            async def call(self, name, arguments):
                seen.append(asyncio.current_task())
                return {"status": "filled"}
        current = asyncio.current_task()
        result = await broker_mcp_bridge.operation(FakeAlpaca(), "reconcile", {"client_order_id": "one"})
        self.assertEqual(result, {"status": "filled"})
        self.assertEqual(seen, [current])

    async def test_readback_operations_keep_distinct_limits_and_result_shapes(self):
        class FakeAlpaca:
            def __init__(self):
                self.calls = []

            async def call(self, name, arguments=None):
                self.calls.append((name, arguments))
                if name == "get_all_positions":
                    return []
                if name == "get_orders":
                    return []
                return {"data": {"order": {"status": "accepted", "client_order_id": (arguments or {})["client_order_id"]}}}

        alpaca: Any = FakeAlpaca()
        one = await broker_mcp_bridge.operation(alpaca, "reconcile", {"client_order_id": "first"})
        self.assertEqual(one, {"status": "accepted", "client_order_id": "first"})
        many = await broker_mcp_bridge.operation(alpaca, "reconcile_many", {"client_order_ids": ["second"]})
        self.assertEqual(many, {"orders": [{"status": "accepted", "client_order_id": "second"}]})
        snapshot = await broker_mcp_bridge.operation(alpaca, "reconciliation_snapshot", {"client_order_ids": []})
        self.assertEqual(snapshot["orders"], [])
        self.assertEqual(snapshot["positions"], [])
        self.assertEqual(snapshot["open_orders"], [])
        self.assertEqual([name for name, _ in alpaca.calls], [
            "get_order_by_client_id", "get_order_by_client_id", "get_all_positions", "get_orders",
        ])
        with self.assertRaisesRegex(RuntimeError, "client_order_ids required"):
            await broker_mcp_bridge.operation(alpaca, "reconcile_many", {"client_order_ids": []})
        with self.assertRaisesRegex(RuntimeError, "client_order_ids required"):
            await broker_mcp_bridge.operation(alpaca, "reconcile_many", {"client_order_ids": ["x"] * 101})
        with self.assertRaisesRegex(RuntimeError, "client_order_ids required"):
            await broker_mcp_bridge.operation(alpaca, "reconciliation_snapshot", {"client_order_ids": ["x"] * 501})

    def test_alpaca_server_pins_fastmcp_below_breaking_v4(self):
        with patch(
            "broker_mcp_bridge.configured_alpaca_env",
            return_value={
                "ALPACA_API_KEY": "api",
                "ALPACA_SECRET_KEY": "secret",
                "ALPACA_PAPER_TRADE": "true",
            },
        ):
            config = broker_mcp_bridge.alpaca_mcp_config()

        server = config["mcpServers"]["alpaca"]
        self.assertEqual(server["command"], "uvx")
        self.assertEqual(
            server["args"],
            ["--with", "fastmcp<4", "alpaca-mcp-server"],
        )

    async def test_fractional_quantity_is_forwarded_unchanged_to_paper_order_tool(self):
        alpaca = _AcceptingAlpaca()
        order = {
            "action": "BUY", "symbol": "NVDA", "quantity": 0.5,
            "limit_price": 200.0, "target": 220.0, "stop": 190.0,
        }
        await broker_mcp_bridge.operation(
            alpaca, "place", {"order": order, "client_order_id": "tradey-test"}
        )
        name, payload = alpaca.calls[0]
        self.assertEqual(name, "place_stock_order")
        self.assertEqual(payload["qty"], 0.5)
        self.assertEqual(payload["order_class"], "bracket")
        self.assertEqual(payload["time_in_force"], "gtc")

    async def test_existing_position_protection_uses_gtc_oco(self):
        alpaca = _AcceptingAlpaca()
        await broker_mcp_bridge.operation(alpaca, "protect", {
            "symbol": "ZS", "quantity": 3, "target": 184.37,
            "stop": 151.24, "client_order_id": "tradey-protect-test",
        })
        name, payload = alpaca.calls[0]
        self.assertEqual(name, "place_stock_order")
        self.assertEqual(payload, {
            "symbol": "ZS", "side": "sell", "type": "limit", "qty": 3,
            "time_in_force": "gtc", "take_profit_limit_price": 184.37,
            "client_order_id": "tradey-protect-test", "order_class": "oco",
            "stop_loss_stop_price": 151.24,
        })

    async def test_feed_provenance_fails_when_tool_cannot_accept_feed(self):
        class FakeSession:
            async def call_tool(self, name, arguments):
                raise AssertionError("provider must not be called")

        alpaca = broker_mcp_bridge.Alpaca(
            FakeSession(),
            {"get_stock_latest_quote": {"properties": {"symbols": {}}}},
        )
        with self.assertRaisesRegex(RuntimeError, "unsupported_tool_parameter:feed"):
            await alpaca.call("get_stock_latest_quote", {"symbol": "AAPL", "feed": "iex"})


if __name__ == "__main__":
    unittest.main()
