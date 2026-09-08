import unittest
from unittest.mock import patch

import broker_mcp_bridge


class BrokerMcpConfigTests(unittest.IsolatedAsyncioTestCase):
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
        class FakeAlpaca:
            def __init__(self):
                self.calls = []

            async def call(self, name, arguments=None):
                self.calls.append((name, arguments))
                return {"status": "accepted"}

        alpaca = FakeAlpaca()
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
        class FakeAlpaca:
            def __init__(self):
                self.calls = []

            async def call(self, name, arguments=None):
                self.calls.append((name, arguments))
                return {"status": "accepted"}

        alpaca = FakeAlpaca()
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
