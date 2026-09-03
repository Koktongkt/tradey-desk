import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import broker_mcp_bridge


class _FakeAlpaca:
    async def call(self, name, values=None):
        responses = {
            "get_account_info": {"cash": "1000", "buying_power": "1000"},
            "get_all_positions": [],
            "get_orders": [],
            "get_asset": {"symbol": "AAPL", "tradable": True, "asset_class": "us_equity", "exchange": "NASDAQ", "name": "Apple Inc.", "fractionable": True},
            "get_stock_latest_quote": {"AAPL": {"bp": 100.0, "ap": 100.1, "t": "2026-09-01T14:00:00Z"}},
            "get_calendar": [{"date": "2026-09-01"}, {"date": "2026-09-02"}, {"date": "2026-09-03"}],
            "get_stock_bars": {
                "AAPL": [{"t": f"2026-09-{index:02d}", "c": 100 + index} for index in range(1, 31)],
                "SPY": [{"t": f"2026-09-{index:02d}", "c": 500 + index} for index in range(1, 31)],
            },
        }
        return responses[name]


class BrokerBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_uses_massive_volume_and_explicit_provenance(self):
        bars = [{"volume": 12_000_000}]
        with patch("broker_mcp_bridge.consolidated_daily_bars", return_value=bars):
            result = await broker_mcp_bridge.operation(_FakeAlpaca(), "snapshot", {"symbol": "AAPL", "earnings_sessions_away": 8})
        self.assertEqual(result["average_volume"], 12_000_000)
        self.assertEqual(result["volume_feed"], "massive_consolidated")
        self.assertEqual(result["quote_feed"], "alpaca_iex")

    async def test_snapshot_returns_completed_consolidated_technical_bars(self):
        bars = [
            {"open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0, "volume": 1_000_000.0, "timestamp": 1}
        ]
        with patch("broker_mcp_bridge.consolidated_daily_bars", return_value=bars):
            result = await broker_mcp_bridge.operation(_FakeAlpaca(), "snapshot", {"symbol": "AAPL"})
        self.assertEqual(result["technical_bars"], bars)
        self.assertEqual(result["average_volume"], 1_000_000.0)
        self.assertEqual(result["technical_bars_feed"], "massive_consolidated_completed_daily")

    async def test_snapshot_returns_exchange_sessions_through_planned_exit(self):
        with patch("broker_mcp_bridge.consolidated_daily_bars", return_value=[{"volume": 12_000_000}]):
            result = await broker_mcp_bridge.operation(
                _FakeAlpaca(), "snapshot", {
                    "symbol": "AAPL", "planned_exit_at": "2026-09-03T20:00:00Z",
                    "earnings_event_at": "2026-09-01T20:05:00Z",
                },
            )
        self.assertEqual(result["trading_sessions"], ["2026-09-01", "2026-09-02", "2026-09-03"])

    def test_reported_earnings_event_is_not_treated_as_upcoming(self):
        status, sessions = broker_mcp_bridge.earnings_state(
            "2026-09-01T20:05:00Z", [], datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc)
        )
        self.assertEqual((status, sessions), ("reported", None))

    def test_upcoming_earnings_sessions_are_counted_from_broker_calendar(self):
        calendar = [{"date": "2026-09-02"}, {"date": "2026-09-03"}, {"date": "2026-09-04"}]
        status, sessions = broker_mcp_bridge.earnings_state(
            "2026-09-04T20:05:00Z", calendar, datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc)
        )
        self.assertEqual((status, sessions), ("upcoming", 2))

    async def test_shadow_outcome_read_supports_thirty_sessions(self):
        rows = await broker_mcp_bridge.operation(_FakeAlpaca(), "outcomes", {"candidates": [{
            "candidate_id": "shadow-a", "symbol": "AAPL", "researched_at": "2026-09-01T14:00:00Z",
            "price": 100.0, "spy_price": 500.0, "traded": False,
        }]})
        self.assertIn("30", rows[0]["prices"])
        self.assertIn("30", rows[0]["spy_prices"])


if __name__ == "__main__":
    unittest.main()
