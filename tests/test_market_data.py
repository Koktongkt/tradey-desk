import json
import unittest
from unittest.mock import patch

import market_data


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({
            "status": "OK",
            "results": [
                {"o": 103, "h": 104, "l": 102, "c": 103.5, "v": 50, "t": 1788264000000},
                {"o": 102, "h": 103, "l": 101, "c": 102.5, "v": 100, "t": 1788177600000},
                {"o": 101, "h": 102, "l": 100, "c": 101.5, "v": 300, "t": 1788091200000},
            ],
        }).encode()


class _GroupedResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({
            "status": "OK",
            "results": [
                {"T": "SPY", "c": 770.19, "t": 1788552000000},
                {"T": "SNOW", "c": 337.18, "t": 1788552000000},
            ],
        }).encode()


class _PayloadResponse(_GroupedResponse):
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()


class MarketDataTests(unittest.TestCase):
    def test_synchronized_completed_close_prices_use_one_grouped_response(self):
        with patch("market_data.configured_massive_key", return_value="secret"), patch(
            "market_data.urllib.request.urlopen", return_value=_GroupedResponse()
        ) as open_url:
            value = market_data.synchronized_completed_close_prices(
                "SNOW", now_ms=1788609600000
            )

        self.assertEqual(value, {
            "price": 337.18,
            "spy_price": 770.19,
            "market_prices_at": "2026-09-04T20:00:00Z",
            "market_price_feed": "massive_consolidated_completed_daily",
        })
        self.assertEqual(open_url.call_count, 1)
        request = open_url.call_args.args[0]
        self.assertIn("/v2/aggs/grouped/locale/us/market/stocks/2026-09-04", request.full_url)
        self.assertEqual(request.headers["Authorization"], "Bearer secret")
        self.assertNotIn("secret", request.full_url)

    def test_synchronized_prices_use_a_strictly_prior_session_after_close(self):
        prior_session = _PayloadResponse({"status":"OK","results":[
            {"T":"SPY","c":769.1,"t":1788465600000},
            {"T":"SNOW","c":330.2,"t":1788465600000},
        ]})
        with patch("market_data.configured_massive_key", return_value="secret"), patch(
            "market_data.urllib.request.urlopen", return_value=prior_session
        ) as open_url:
            value = market_data.synchronized_completed_close_prices(
                "SNOW", now_ms=1788552000000
            )

        self.assertEqual(open_url.call_count, 1)
        self.assertIn("/2026-09-03", open_url.call_args.args[0].full_url)
        self.assertEqual(value["market_prices_at"], "2026-09-03T20:00:00Z")
        self.assertEqual(value["price"], 330.2)
        self.assertEqual(value["spy_price"], 769.1)

    def test_synchronized_prices_reject_rows_from_the_wrong_session_date(self):
        wrong_date = _PayloadResponse({"status":"OK","results":[
            {"T":"SPY","c":999.0,"t":1788465600000},
            {"T":"SNOW","c":999.0,"t":1788465600000},
        ]})
        prior_session = _PayloadResponse({"status":"OK","results":[
            {"T":"SPY","c":769.1,"t":1788465600000},
            {"T":"SNOW","c":330.2,"t":1788465600000},
        ]})
        with patch("market_data.configured_massive_key", return_value="secret"), patch(
            "market_data.urllib.request.urlopen", side_effect=[wrong_date, prior_session]
        ) as open_url:
            value = market_data.synchronized_completed_close_prices(
                "SNOW", now_ms=1788609600000
            )

        self.assertEqual(open_url.call_count, 2)
        self.assertEqual(value["price"], 330.2)
        self.assertEqual(value["spy_price"], 769.1)
        self.assertEqual(value["market_prices_at"], "2026-09-03T20:00:00Z")

    def test_synchronized_prices_reject_non_ok_payload_status(self):
        invalid = _PayloadResponse({"status":"ERROR","results":[
            {"T":"SPY","c":999.0,"t":1788552000000},
            {"T":"SNOW","c":999.0,"t":1788552000000},
        ]})
        prior_session = _PayloadResponse({"status":"OK","results":[
            {"T":"SPY","c":769.1,"t":1788465600000},
            {"T":"SNOW","c":330.2,"t":1788465600000},
        ]})
        with patch("market_data.configured_massive_key", return_value="secret"), patch(
            "market_data.urllib.request.urlopen", side_effect=[invalid, prior_session]
        ) as open_url:
            value = market_data.synchronized_completed_close_prices(
                "SNOW", now_ms=1788609600000
            )

        self.assertEqual(open_url.call_count, 2)
        self.assertEqual(value["price"], 330.2)

    def test_massive_volume_uses_header_and_completed_sessions(self):
        with patch("market_data.configured_massive_key", return_value="secret"), patch(
            "market_data.urllib.request.urlopen", return_value=_Response()
        ) as open_url:
            value = market_data.consolidated_average_volume(
                "AAPL", now_ms=1788267600000
            )
        self.assertEqual(value, 200.0)
        request = open_url.call_args.args[0]
        self.assertEqual(request.headers["Authorization"], "Bearer secret")
        self.assertNotIn("secret", request.full_url)
        self.assertIn("adjusted=true", request.full_url)

    def test_massive_volume_rejects_invalid_symbols_before_network(self):
        with patch("market_data.urllib.request.urlopen") as open_url:
            with self.assertRaises(ValueError):
                market_data.consolidated_average_volume("AAPL/../SPY")
        open_url.assert_not_called()

    def test_massive_daily_bars_are_completed_normalized_and_chronological(self):
        with patch("market_data.configured_massive_key", return_value="secret"), patch(
            "market_data.urllib.request.urlopen", return_value=_Response()
        ):
            bars = market_data.consolidated_daily_bars("AAPL", now_ms=1788267600000)
        self.assertEqual(bars, [
            {"open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 300.0, "timestamp": 1788091200000},
            {"open": 102.0, "high": 103.0, "low": 101.0, "close": 102.5, "volume": 100.0, "timestamp": 1788177600000},
        ])


if __name__ == "__main__":
    unittest.main()
