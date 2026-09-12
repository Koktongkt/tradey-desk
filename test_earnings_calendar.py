"""Deterministic earnings-calendar resolution tests."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import earnings_calendar


class EarningsCalendarTests(unittest.TestCase):
    def test_extract_release_date_requires_explicit_results_action(self):
        text = (
            "Date of Report: September 9, 2026. Quarter ended June 30, 2026. "
            "On September 8, 2026, the Company issued a press release announcing "
            "its financial results for the quarter."
        )

        self.assertEqual(earnings_calendar.extract_release_date(text), "2026-09-08")

    def test_extract_release_date_allows_company_abbreviation_after_date(self):
        text=(
            "Date of Report: August 1, 2026. "
            "On July 31, 2026, Example Inc. issued a press release announcing "
            "financial results for its fiscal third quarter."
        )
        self.assertEqual(earnings_calendar.extract_release_date(text),"2026-07-31")

    def test_extract_release_date_accepts_dateline_before_release_language(self):
        text=(
            "BURLINGTON, N.C., July 30, 2026 - Labcorp Holdings Inc. (NYSE: LH), "
            "a global leader of innovative and comprehensive laboratory services, "
            "today announced results for the second quarter ended June 30, 2026 "
            "and updated its full-year financial guidance."
        )
        self.assertEqual(earnings_calendar.extract_release_date(text),"2026-07-30")

    def test_extract_release_date_accepts_date_following_reported_header(self):
        text=(
            "Date of Report (Date of earliest event reported): August 26, 2026. "
            "Item 2.02 Results of Operations and Financial Condition. "
            "The press release is attached as Exhibit 99.1."
        )
        self.assertEqual(earnings_calendar.extract_release_date(text),"2026-08-26")

    def test_extract_release_date_rejects_preliminary_duplicate_event(self):
        text=(
            "On August 31, 2026, the Company issued a press release announcing "
            "certain preliminary financial results for its second quarter."
        )
        self.assertIsNone(earnings_calendar.extract_release_date(text))

    def test_sec_history_resolves_ticker_and_returns_explicit_releases(self):
        json_payloads = {
            "https://www.sec.gov/files/company_tickers.json": {
                "0": {"ticker": "XYZ", "cik_str": 1234, "title": "Example Corp"},
            },
            "https://data.sec.gov/submissions/CIK0000001234.json": {
                "filings": {"recent": {
                    "form": ["8-K", "8-K"],
                    "items": ["2.02,9.01", "2.02"],
                    "accessionNumber": ["0000001234-26-000002", "0000001234-26-000001"],
                    "primaryDocument": ["new.htm", "old.htm"],
                }},
            },
        }
        text_payloads = {
            "https://www.sec.gov/Archives/edgar/data/1234/000000123426000002/new.htm":
                "On September 8, 2026, the Company issued a press release announcing its financial results.",
            "https://www.sec.gov/Archives/edgar/data/1234/000000123426000001/old.htm":
                "On June 3, 2026, the Company released earnings for its fiscal quarter.",
        }

        rows = earnings_calendar.sec_release_history(
            "xyz",
            get_json=lambda url: json_payloads[url],
            get_text=lambda url: text_payloads[url],
        )

        self.assertEqual([row["date"] for row in rows], ["2026-09-08", "2026-06-03"])
        self.assertTrue(all(row["source_type"] == "sec_8-k_item_2_02" for row in rows))

    def test_sec_history_reads_earnings_exhibit_when_primary_has_no_explicit_date(self):
        json_payloads = {
            "https://www.sec.gov/files/company_tickers.json": {
                "0": {"ticker": "XYZ", "cik_str": 1234},
            },
            "https://data.sec.gov/submissions/CIK0000001234.json": {
                "filings": {"recent": {
                    "form": ["8-K"], "items": ["2.02,9.01"],
                    "accessionNumber": ["0000001234-26-000003"],
                    "primaryDocument": ["form8k.htm"],
                }},
            },
            "https://www.sec.gov/Archives/edgar/data/1234/000000123426000003/index.json": {
                "directory": {"item": [
                    {"name": "form8k.htm"},
                    {"name": "ex99-1_earningsrelease.htm"},
                ]},
            },
        }
        text_payloads = {
            "https://www.sec.gov/Archives/edgar/data/1234/000000123426000003/form8k.htm":
                "Item 2.02. The earnings release is furnished as Exhibit 99.1.",
            "https://www.sec.gov/Archives/edgar/data/1234/000000123426000003/ex99-1_earningsrelease.htm":
                "On December 2, 2026, the Company announced its financial results.",
        }

        rows = earnings_calendar.sec_release_history(
            "XYZ", get_json=lambda url: json_payloads[url], get_text=lambda url: text_payloads[url]
        )

        self.assertEqual([row["date"] for row in rows], ["2026-12-02"])
        self.assertTrue(rows[0]["source_url"].endswith("ex99-1_earningsrelease.htm"))

    def test_sec_lookup_has_bounded_network_budget(self):
        self.assertEqual(earnings_calendar.SEC_LOOKUP_BUDGET_SECONDS,45)
        self.assertEqual(earnings_calendar.SEC_REQUEST_TIMEOUT_SECONDS,8)

    def test_sec_history_bounds_relevant_filings_scanned(self):
        count=20
        recent={
            "form":["8-K"]*count,
            "items":["2.02"]*count,
            "accessionNumber":[f"0000001234-26-{index:06d}" for index in range(count)],
            "primaryDocument":[f"f{index}.htm" for index in range(count)],
        }
        text_calls=[]
        def get_json(url):
            if url.endswith("company_tickers.json"):
                return {"0":{"ticker":"XYZ","cik_str":1234}}
            if "submissions" in url:
                return {"filings":{"recent":recent}}
            return {"directory":{"item":[]}}
        def get_text(url):
            text_calls.append(url)
            return "Item 2.02 without an explicit release date."

        rows=earnings_calendar.sec_release_history("XYZ",get_json=get_json,get_text=get_text)

        self.assertEqual(rows,[])
        self.assertLessEqual(len(text_calls),earnings_calendar.MAX_RELEVANT_FILINGS_SCANNED)

    def test_resolver_replaces_past_model_date_with_conservative_estimate(self):
        candidate = {
            "symbol": "XYZ",
            "earnings_event_at": "2026-09-08",
            "planned_exit_at": "2026-09-25T20:00:00Z",
        }
        history = [
            {"date": "2026-09-08", "source_url": "https://sec/a"},
            {"date": "2026-06-03", "source_url": "https://sec/b"},
        ]

        resolved = earnings_calendar.resolve_candidate_earnings(
            candidate,
            history_loader=lambda _symbol: history,
            now=dt.datetime(2026, 9, 11, 14, 0, tzinfo=dt.timezone.utc),
        )

        self.assertEqual(resolved["previous_earnings_date"], "2026-09-08")
        self.assertEqual(resolved["earnings_event_at"], "2026-11-30")
        self.assertEqual(resolved["earnings_date_status"], "estimated")
        self.assertEqual(resolved["earnings_history_count"], 2)

    def test_web_evidence_pages_cannot_confirm_earnings_date(self):
        resolved = earnings_calendar.resolve_candidate_earnings(
            {"symbol": "XYZ", "earnings_event_at": "2026-12-10"},
            trusted_date_loader=lambda _symbol: None,
            history_loader=lambda _symbol: [],
            now=dt.datetime(2026, 9, 11, 14, 0, tzinfo=dt.timezone.utc),
        )

        self.assertNotIn("earnings_event_at", resolved)
        self.assertEqual(resolved["earnings_date_status"], "unknown")

    def test_resolver_signature_has_no_evidence_parameter(self):
        import inspect
        parameters = inspect.signature(earnings_calendar.resolve_candidate_earnings).parameters
        self.assertNotIn("evidence", parameters)
        self.assertIn("trusted_date_loader", parameters)

    def test_cached_history_avoids_repeat_sec_fetch_within_ttl(self):
        calls=[]
        rows=[{"date":"2026-09-08","source_url":"https://sec/a"}]
        now=dt.datetime(2026,9,11,14,0,tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/"earnings_cache.json"
            first=earnings_calendar.cached_sec_release_history(
                "XYZ",cache_path=cache,now=now,history_loader=lambda symbol:(calls.append(symbol) or rows)
            )
            second=earnings_calendar.cached_sec_release_history(
                "XYZ",cache_path=cache,now=now+dt.timedelta(hours=12),
                history_loader=lambda _symbol:(_ for _ in ()).throw(AssertionError("network called")),
            )

        self.assertEqual(first,rows)
        self.assertEqual(second,rows)
        self.assertEqual(calls,["XYZ"])

    def test_resolver_uses_private_cache_for_default_sec_history(self):
        rows=[
            {"date":"2026-09-08","source_url":"https://sec/a"},
            {"date":"2026-06-03","source_url":"https://sec/b"},
        ]
        with tempfile.TemporaryDirectory() as td, patch.object(
            earnings_calendar,"sec_release_history",return_value=rows
        ) as loader:
            resolved=earnings_calendar.resolve_candidate_earnings(
                {"symbol":"XYZ"}, history_loader=None,
                cache_path=Path(td)/"private"/"earnings_cache.json",
                now=dt.datetime(2026,9,11,14,0,tzinfo=dt.timezone.utc),
            )

        loader.assert_called_once_with("XYZ")
        self.assertEqual(resolved["earnings_date_status"],"estimated")

    def test_resolver_ignores_malformed_history_rows_and_fails_closed(self):
        resolved=earnings_calendar.resolve_candidate_earnings(
            {"symbol":"XYZ","earnings_event_at":"2026-09-08"},
            history_loader=lambda _symbol:[{"date":"not-a-date"},{"unexpected":"value"}],
            now=dt.datetime(2026,9,11,14,0,tzinfo=dt.timezone.utc),
        )

        self.assertNotIn("earnings_event_at",resolved)
        self.assertEqual(resolved["earnings_date_status"],"unknown")
        self.assertEqual(resolved["earnings_history_count"],0)

    def test_expired_estimated_window_fails_closed_instead_of_looking_reported(self):
        history=[
            {"date":"2026-03-01"},
            {"date":"2025-12-01"},
        ]
        resolved=earnings_calendar.resolve_candidate_earnings(
            {"symbol":"XYZ","earnings_event_at":"2026-03-01"},
            history_loader=lambda _symbol:history,
            now=dt.datetime(2026,9,11,14,0,tzinfo=dt.timezone.utc),
        )

        self.assertNotIn("earnings_event_at",resolved)
        self.assertEqual(resolved["earnings_date_status"],"unknown")

    def test_two_dates_with_nonquarterly_gap_do_not_create_estimate(self):
        self.assertIsNone(earnings_calendar.estimate_next_window([
            "2026-08-31","2024-05-17",
        ]))

    def test_nasdaq_scan_tolerates_null_data_on_holidays(self):
        def get_json(url):
            if "2026-12-25" in url:
                return {"data": None}
            if "2026-12-24" in url:
                return {"data": {"rows": [{"symbol": "AAPL", "name": "Apple"}]}}
            return {"data": {"asOf": "x", "headers": None, "rows": None}}

        self.assertEqual(
            earnings_calendar.nasdaq_earnings_date(
                "AAPL", dt.date(2026, 12, 24), dt.date(2026, 12, 26),
                get_json=get_json, sleep=lambda _s: None,
            ),
            ("2026-12-24", "https://api.nasdaq.com/api/calendar/earnings?date=2026-12-24"),
        )

    def test_past_trusted_date_feeds_next_window_estimation(self):
        resolved = earnings_calendar.resolve_candidate_earnings(
            {"symbol": "NVDA", "earnings_event_at": "2026-08-26"},
            trusted_date_loader=lambda _s: ("2026-08-26", "https://stockanalysis.com/stocks/nvda/"),
            history_loader=lambda _s: [
                {"date": "2026-05-28", "source_url": "https://sec/b"},
            ],
            now=dt.datetime(2026, 9, 12, 3, 0, tzinfo=dt.timezone.utc),
        )

        self.assertEqual(resolved["previous_earnings_date"], "2026-08-26")
        self.assertEqual(resolved["earnings_date_status"], "estimated")
        self.assertEqual(resolved["earnings_history_count"], 2)
        self.assertEqual(resolved["estimated_next_earnings_window"], {
            "earliest": "2026-11-10", "latest": "2026-12-08",
        })
        self.assertEqual(resolved["earnings_event_at"], "2026-11-10")

    def test_estimate_window_uses_only_latest_two_dates(self):
        result = earnings_calendar.estimate_next_window([
            "2026-09-08",
            "2026-06-03",
            "2015-01-20",
        ])

        self.assertEqual(result, {
            "earliest": "2026-11-30",
            "latest": "2026-12-28",
            "history_count": 2,
        })

    def test_stockanalysis_page_provides_earnings_date(self):
        page = '<div>Apple</div><script>{"earningsDate":"Oct 29, 2026"}</script>'

        self.assertEqual(
            earnings_calendar.stockanalysis_earnings_date(
                "AAPL", get_text=lambda _url: page,
            ),
            ("2026-10-29", "https://stockanalysis.com/stocks/aapl/"),
        )

    def test_stockanalysis_page_without_date_returns_none(self):
        self.assertIsNone(earnings_calendar.stockanalysis_earnings_date(
            "AAPL", get_text=lambda _url: "<html>no date here</html>",
        ))

    def test_nasdaq_calendar_scan_finds_symbol_in_horizon(self):
        def get_json(url):
            if "2026-10-29" in url:
                return {"data": {"rows": [{
                    "symbol": "AAPL", "name": "Apple Inc.",
                    "fiscalQuarterEnding": "Sep/2026",
                }]}}
            return {"data": {"rows": []}}

        self.assertEqual(
            earnings_calendar.nasdaq_earnings_date(
                "AAPL", dt.date(2026, 10, 27), dt.date(2026, 10, 30),
                get_json=get_json, sleep=lambda _s: None,
            ),
            ("2026-10-29", "https://api.nasdaq.com/api/calendar/earnings?date=2026-10-29"),
        )

    def test_nasdaq_calendar_scan_ignores_other_symbols(self):
        def get_json(url):
            return {"data": {"rows": [{"symbol": "MSFT", "name": "Microsoft"}]}}

        self.assertIsNone(earnings_calendar.nasdaq_earnings_date(
            "AAPL", dt.date(2026, 10, 27), dt.date(2026, 10, 28),
            get_json=get_json, sleep=lambda _s: None,
        ))

    def test_resolver_confirms_from_stockanalysis_when_evidence_lacks_date(self):
        candidate = {
            "symbol": "AAPL", "earnings_event_at": "2026-10-29",
            "planned_exit_at": "2026-10-20T20:00:00Z",
        }
        resolved = earnings_calendar.resolve_candidate_earnings(
            candidate,
            history_loader=lambda _symbol: [],
            trusted_date_loader=lambda symbol: ("2026-10-29", "https://stockanalysis.com/stocks/aapl/"),
            now=dt.datetime(2026, 9, 11, 14, 0, tzinfo=dt.timezone.utc),
        )

        self.assertEqual(resolved["earnings_event_at"], "2026-10-29")
        self.assertEqual(resolved["earnings_date_status"], "confirmed")
        self.assertEqual(
            resolved["earnings_confirmation_url"],
            "https://stockanalysis.com/stocks/aapl/",
        )

    def test_resolver_confirms_from_trusted_source_with_different_date(self):
        resolved = earnings_calendar.resolve_candidate_earnings(
            {"symbol": "AAPL", "earnings_event_at": "2026-12-01"},
            history_loader=lambda _symbol: [],
            trusted_date_loader=lambda symbol: ("2026-10-29", "https://api.nasdaq.com/calendar"),
            now=dt.datetime(2026, 9, 11, 14, 0, tzinfo=dt.timezone.utc),
        )

        self.assertEqual(resolved["earnings_event_at"], "2026-10-29")
        self.assertEqual(resolved["earnings_date_status"], "confirmed")

    def test_resolver_confirms_past_trusted_date_as_previous(self):
        resolved = earnings_calendar.resolve_candidate_earnings(
            {"symbol": "AAPL"},
            history_loader=lambda _symbol: [],
            trusted_date_loader=lambda symbol: ("2026-08-01", "https://stockanalysis.com/stocks/aapl/"),
            now=dt.datetime(2026, 9, 11, 14, 0, tzinfo=dt.timezone.utc),
        )

        self.assertEqual(resolved["previous_earnings_date"], "2026-08-01")
        self.assertNotIn("earnings_event_at", resolved)
        self.assertEqual(resolved["earnings_date_status"], "unknown")

    def test_resolver_falls_back_to_estimate_when_trusted_source_misses(self):
        resolved = earnings_calendar.resolve_candidate_earnings(
            {"symbol": "XYZ", "earnings_event_at": "2026-09-08"},
            history_loader=lambda _symbol: [
                {"date": "2026-09-08", "source_url": "https://sec/a"},
                {"date": "2026-06-03", "source_url": "https://sec/b"},
            ],
            trusted_date_loader=lambda symbol: None,
            now=dt.datetime(2026, 9, 11, 14, 0, tzinfo=dt.timezone.utc),
        )

        self.assertEqual(resolved["earnings_event_at"], "2026-11-30")
        self.assertEqual(resolved["earnings_date_status"], "estimated")

    def test_default_trusted_loader_uses_network_sources(self):
        with tempfile.TemporaryDirectory() as td, patch.object(
            earnings_calendar, "stockanalysis_earnings_date", return_value=None
        ) as sa, patch.object(
            earnings_calendar, "nasdaq_earnings_date", return_value=None
        ) as nd:
            earnings_calendar.default_trusted_date_loader(
                "AAPL",
                dt.date(2026, 9, 12), dt.date(2026, 9, 25),
                cache_path=Path(td) / "cache.json",
            )

        sa.assert_called_once()
        nd.assert_called_once()
        args, kwargs = nd.call_args
        self.assertEqual(args[0], "AAPL")
        self.assertEqual(args[1], dt.date(2026, 9, 12))
        self.assertEqual(args[2], dt.date(2026, 9, 25))

    def test_two_confirmed_releases_are_enough_to_estimate_window(self):
        result = earnings_calendar.estimate_next_window([
            "2026-09-08",
            "2026-06-03",
        ])

        self.assertEqual(result, {
            "earliest": "2026-11-30",
            "latest": "2026-12-28",
            "history_count": 2,
        })


if __name__ == "__main__":
    unittest.main()
