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
            evidence=[],
            history_loader=lambda _symbol: history,
            now=dt.datetime(2026, 9, 11, 14, 0, tzinfo=dt.timezone.utc),
        )

        self.assertEqual(resolved["previous_earnings_date"], "2026-09-08")
        self.assertEqual(resolved["earnings_event_at"], "2026-11-30")
        self.assertEqual(resolved["earnings_date_status"], "estimated")
        self.assertEqual(resolved["earnings_history_count"], 2)

    def test_resolver_prefers_future_date_confirmed_by_accepted_evidence(self):
        candidate = {
            "symbol": "XYZ", "earnings_event_at": "2026-12-10",
            "planned_exit_at": "2026-09-25T20:00:00Z",
        }
        evidence = [
            {
                "url": "https://issuer.example/release",
                "text": "The Company will report its third-quarter financial results on December 10, 2026.",
            },
            {
                "url": "https://news.example/story",
                "text": "The Company will report quarterly results on December 10, 2026.",
            },
        ]

        resolved = earnings_calendar.resolve_candidate_earnings(
            candidate, evidence=evidence, history_loader=lambda _symbol: [],
            now=dt.datetime(2026, 9, 11, 14, 0, tzinfo=dt.timezone.utc),
        )

        self.assertEqual(resolved["earnings_event_at"], "2026-12-10")
        self.assertEqual(resolved["earnings_date_status"], "confirmed")
        self.assertEqual(resolved["earnings_confirmation_url"], "https://issuer.example/release")

    def test_single_non_sec_page_cannot_confirm_future_date(self):
        resolved=earnings_calendar.resolve_candidate_earnings(
            {"symbol":"XYZ","earnings_event_at":"2026-12-10"},
            evidence=[{
                "url":"https://calendar.example/xyz",
                "text":"The Company will report quarterly results on December 10, 2026.",
            }],
            history_loader=lambda _symbol:[],
            now=dt.datetime(2026,9,11,14,0,tzinfo=dt.timezone.utc),
        )

        self.assertNotIn("earnings_event_at",resolved)
        self.assertEqual(resolved["earnings_date_status"],"unknown")

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
                {"symbol":"XYZ"}, evidence=[], history_loader=None,
                cache_path=Path(td)/"private"/"earnings_cache.json",
                now=dt.datetime(2026,9,11,14,0,tzinfo=dt.timezone.utc),
            )

        loader.assert_called_once_with("XYZ")
        self.assertEqual(resolved["earnings_date_status"],"estimated")

    def test_resolver_ignores_malformed_history_rows_and_fails_closed(self):
        resolved=earnings_calendar.resolve_candidate_earnings(
            {"symbol":"XYZ","earnings_event_at":"2026-09-08"}, evidence=[],
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
            {"symbol":"XYZ","earnings_event_at":"2026-03-01"}, evidence=[],
            history_loader=lambda _symbol:history,
            now=dt.datetime(2026,9,11,14,0,tzinfo=dt.timezone.utc),
        )

        self.assertNotIn("earnings_event_at",resolved)
        self.assertEqual(resolved["earnings_date_status"],"unknown")

    def test_two_dates_with_nonquarterly_gap_do_not_create_estimate(self):
        self.assertIsNone(earnings_calendar.estimate_next_window([
            "2026-08-31","2024-05-17",
        ]))

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
