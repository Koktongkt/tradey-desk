import unittest

import broker_normalization as norm


class BrokerNormalizationTests(unittest.TestCase):
    def test_finds_nested_account_mapping(self):
        raw = {"result": {"account": {"buying_power": "1000.50", "cash": "900.25"}}}
        account = norm.find_mapping_with_keys(raw, {"buying_power", "cash"})
        self.assertEqual(account["buying_power"], "1000.50")
        self.assertEqual(account["cash"], "900.25")

    def test_extracts_symbol_bars_from_nested_response(self):
        raw = {"result": {"bars": {"AAPL": [{"v": 100}, {"volume": 300}]}}}
        bars = norm.symbol_bars(raw, "AAPL")
        self.assertEqual(len(bars), 2)
        self.assertEqual(norm.average_volume(bars), 200.0)

    def test_extracts_massive_aggregate_results(self):
        raw = {"status": "OK", "ticker": "AAPL", "results": [{"v": 100}, {"v": 300}]}
        bars = norm.massive_daily_bars(raw)
        self.assertEqual(bars, [{"v": 100}, {"v": 300}])

    def test_average_volume_ignores_incomplete_current_session(self):
        bars = [
            {"v": 50, "t": 1788264000000},
            {"v": 100, "t": 1788177600000},
            {"v": 300, "t": 1788091200000},
        ]
        self.assertEqual(norm.completed_session_average_volume(bars, now_ms=1788267600000), 200.0)
        self.assertEqual(norm.completed_session_average_volume(bars, now_ms=1788296400000), 150.0)

    def test_average_volume_rejects_non_finite_values(self):
        self.assertIsNone(norm.average_volume([{"v": float("nan")}, {"v": float("inf")}]))

    def test_stock_order_arguments_include_bracket_risk_controls(self):
        properties = {key: {} for key in (
            "symbol", "side", "type", "qty", "time_in_force", "limit_price",
            "client_order_id", "order_class", "take_profit_limit_price", "stop_loss_stop_price",
        )}
        values = {
            "symbol": "NVDA", "side": "buy", "type": "limit", "qty": 1,
            "time_in_force": "day", "limit_price": 100, "client_order_id": "tradey-x",
            "order_class": "bracket", "take_profit_limit_price": 110,
            "stop_loss_stop_price": 95,
        }
        args = norm.tool_arguments(properties, values)
        self.assertEqual(args["order_class"], "bracket")
        self.assertEqual(args["take_profit_limit_price"], "110")
        self.assertEqual(args["stop_loss_stop_price"], "95")

    def test_daily_bars_request_uses_free_iex_feed(self):
        request = norm.daily_bars_request("AAPL", "start", "end")
        self.assertEqual(request["feed"], "iex")
        self.assertEqual(request["symbol"], "AAPL")
        self.assertEqual(request["timeframe"], "1Day")

    def test_quote_request_explicitly_uses_iex_execution_feed(self):
        self.assertEqual(norm.latest_quote_request("AAPL"), {"symbol": "AAPL", "feed": "iex"})

    def test_extracts_nested_symbol_quote(self):
        raw = {"data": {"quotes": {"AAPL": {"bp": 100.0, "ap": 100.1, "t": "2026-08-29T14:00:00Z"}}}}
        quote = norm.symbol_mapping(raw, "AAPL")
        self.assertEqual(quote["bp"], 100.0)
        self.assertEqual(quote["ap"], 100.1)


if __name__ == "__main__":
    unittest.main()
