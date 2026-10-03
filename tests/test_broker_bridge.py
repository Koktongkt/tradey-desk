import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import broker_mcp_bridge


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 1, 14, 0, tzinfo=tz or timezone.utc)


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
    async def test_portfolio_returns_sanitized_holdings_and_spy_relative_day_return(self):
        class PortfolioAlpaca:
            async def call(self, name, values=None):
                responses = {
                    "get_account_info": {
                        "id": "private-account-id", "account_number": "private-number",
                        "equity": "10100", "last_equity": "10000",
                    },
                    "get_all_positions": [{
                        "asset_id": "private-asset-id", "symbol": "AAPL", "side": "long",
                        "qty": "2", "avg_entry_price": "100", "current_price": "110",
                        "market_value": "220", "cost_basis": "200", "unrealized_pl": "20",
                        "unrealized_plpc": "0.10", "unrealized_intraday_pl": "4",
                        "change_today": "0.02",
                    }],
                    "get_stock_snapshot": {"AAPL": {}, "SPY": {
                        "dailyBar": {"c": 505}, "prevDailyBar": {"c": 500},
                    }},
                }
                return responses[name]

        with patch("broker_mcp_bridge.datetime", _FixedDateTime):
            result = await broker_mcp_bridge.operation(PortfolioAlpaca(), "portfolio", {})

        self.assertEqual(result["summary"]["day_return_pct"], 1.0)
        self.assertEqual(result["summary"]["spy_day_return_pct"], 1.0)
        self.assertEqual(result["summary"]["day_excess_pct"], 0.0)
        self.assertEqual(result["summary"]["day_pl_usd"], 100.0)
        self.assertEqual(result["holdings"], [{
            "symbol": "AAPL", "quantity": 2.0, "average_entry_price": 100.0,
            "current_price": 110.0, "market_value": 220.0, "cost_basis": 200.0,
            "unrealized_pl_usd": 20.0, "unrealized_return_pct": 10.0,
            "day_pl_usd": 4.0, "day_return_pct": 2.0,
        }])
        self.assertNotIn("private", str(result).lower())

    async def test_portfolio_ignores_invalid_positions_and_keeps_empty_holdings(self):
        class InvalidPortfolioAlpaca:
            async def call(self, name, values=None):
                return {
                    "get_account_info": {"equity": "10000", "last_equity": "10000"},
                    "get_all_positions": [{"symbol": "../AAPL", "qty": "nan"}],
                    "get_stock_snapshot": {"SPY": {"dailyBar": {"c": 0}, "prevDailyBar": {"c": 500}}},
                }[name]

        result = await broker_mcp_bridge.operation(InvalidPortfolioAlpaca(), "portfolio", {})
        self.assertEqual(result["holdings"], [])
        self.assertIsNone(result["summary"]["spy_day_return_pct"])
        self.assertIsNone(result["summary"]["day_excess_pct"])

    async def test_portfolio_balance_uses_account_fields_independently_of_day_baseline(self):
        cases = (
            ("nested_no_baseline", {"equity": "10100.12", "cash": "9800.12", "long_market_value": "320", "short_market_value": "-20", "buying_power": "90000"}, (10100.12, 9800.12, 300.0, 0.0)),
            ("zero", {"equity": 0, "cash": 0, "long_market_value": 0, "short_market_value": 0}, (0.0, 0.0, 0.0, 0.0)),
            ("difference", {"equity": 100, "cash": 50, "long_market_value": 40, "short_market_value": 0}, (100.0, 50.0, 40.0, 10.0)),
            ("cash_only", {"cash": "25"}, (None, 25.0, None, None)),
            ("missing", {}, (None, None, None, None)),
            ("missing_short", {"equity": 100, "cash": 50, "long_market_value": 50}, (100.0, 50.0, None, None)),
            ("unsigned_short", {"equity": 100, "cash": 50, "long_market_value": 60, "short_market_value": 10}, (100.0, 50.0, None, None)),
            ("overflow_sum", {"long_market_value": "1e308", "short_market_value": 0, "cash": "1e308", "equity": 100}, (100.0, 1e308, 1e308, None)),
        ) + tuple((f"invalid_{value!r}", {key: value for key in ("equity", "cash", "long_market_value", "short_market_value")}, (None, None, None, None)) for value in (None, "", "bad", "nan", "inf", "-inf", True, False, [], {}))
        for label, account, expected in cases:
            with self.subTest(case=label):
                class BalanceAlpaca:
                    async def call(self, name, values=None):
                        return {"get_account_info": {"data": {"account": {"id": "private-id", **account}}},
                                "get_all_positions": [{"symbol": "FILTERED", "market_value": "999999"}],
                                "get_stock_snapshot": {}}[name]
                result = await broker_mcp_bridge.operation(BalanceAlpaca(), "portfolio", {})
                summary = result["summary"]
                self.assertIn("total_balance_usd", summary)
                self.assertEqual(tuple(summary[key] for key in ("total_balance_usd", "cash_usd", "positions_value_usd", "balance_reconciliation_difference_usd")), expected)
                self.assertIsNone(summary["day_return_pct"])
                self.assertEqual(result["holdings"], [])
                self.assertNotIn("private", str(result))

    async def test_snapshot_projection_cases(self):
        technical = [{"open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0, "volume": 1_000_000.0, "timestamp": 1}]
        cases = (
            ("test_snapshot_uses_massive_volume_and_explicit_provenance", {"symbol": "AAPL", "earnings_sessions_away": 8}, [{"volume": 12_000_000}], False,
             {"average_volume": 12_000_000, "volume_feed": "massive_consolidated", "quote_feed": "alpaca_iex"}),
            ("test_snapshot_returns_completed_consolidated_technical_bars", {"symbol": "AAPL"}, technical, False,
             {"technical_bars": technical, "average_volume": 1_000_000.0, "technical_bars_feed": "massive_consolidated_completed_daily"}),
            ("test_snapshot_returns_exchange_sessions_through_planned_exit", {"symbol": "AAPL", "planned_exit_at": "2026-09-03T20:00:00Z", "earnings_event_at": "2026-09-01T20:05:00Z"}, [{"volume": 12_000_000}], True,
             {"trading_sessions": ["2026-09-01", "2026-09-02", "2026-09-03"]}),
            ("test_snapshot_accepts_date_only_earnings_and_counts_exchange_sessions", {"symbol": "AAPL", "earnings_event_at": "2026-09-03"}, [{"volume": 12_000_000}], True,
             {"earnings_status": "upcoming", "earnings_sessions_away": 2}),
        )
        from contextlib import nullcontext
        from copy import deepcopy
        for name, payload, bars, fixed, expected in cases:
            with self.subTest(case=name), patch("broker_mcp_bridge.consolidated_daily_bars", return_value=deepcopy(bars)), (
                patch("broker_mcp_bridge.datetime", _FixedDateTime) if fixed else nullcontext()
            ):
                result = await broker_mcp_bridge.operation(_FakeAlpaca(), "snapshot", deepcopy(payload))
                for field, value in expected.items():
                    self.assertEqual(result[field], value)

    def test_earnings_state_distinguishes_reported_same_day_and_upcoming(self):
        cases = (
            ("reported_timestamp", "2026-09-01T20:05:00Z", (), ("reported", None)),
            ("reported_date_only", "2026-09-01", (), ("reported", None)),
            ("same_day_date_only", "2026-09-02", (), ("upcoming", 0)),
            ("upcoming_broker_sessions", "2026-09-04T20:05:00Z",
             ("2026-09-02", "2026-09-03", "2026-09-04"), ("upcoming", 2)),
        )
        for label, event, dates, expected in cases:
            with self.subTest(case=label):
                now = datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc)
                calendar = [{"date": date} for date in dates]
                self.assertEqual(broker_mcp_bridge.earnings_state(event, calendar, now), expected)

    async def test_reconcile_many_fetches_all_parent_brackets_in_one_session(self):
        class OrdersAlpaca:
            def __init__(self):
                self.calls = []

            async def call(self, name, values=None):
                self.calls.append((name, values))
                return {"client_order_id": values["client_order_id"], "status": "filled", "legs": []}

        alpaca = OrdersAlpaca()
        result = await broker_mcp_bridge.operation(
            alpaca, "reconcile_many", {"client_order_ids": ["tradey-a", "tradey-b"]},
        )

        self.assertEqual(result, {"orders": [
            {"client_order_id": "tradey-a", "status": "filled", "legs": []},
            {"client_order_id": "tradey-b", "status": "filled", "legs": []},
        ]})
        self.assertEqual(alpaca.calls, [
            ("get_order_by_client_id", {"client_order_id": "tradey-a"}),
            ("get_order_by_client_id", {"client_order_id": "tradey-b"}),
        ])

    async def test_shadow_outcome_read_supports_thirty_sessions(self):
        rows = await broker_mcp_bridge.operation(_FakeAlpaca(), "outcomes", {"candidates": [{
            "candidate_id": "shadow-a", "symbol": "AAPL", "researched_at": "2026-09-01T14:00:00Z",
            "price": 100.0, "spy_price": 500.0, "traded": False,
        }]})
        self.assertIn("30", rows[0]["prices"])
        self.assertIn("30", rows[0]["spy_prices"])


if __name__ == "__main__":
    unittest.main()
