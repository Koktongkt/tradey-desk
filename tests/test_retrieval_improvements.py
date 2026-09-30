"""Regression tests for bounded, sourceable radar evidence selection."""
import json
import subprocess
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import alpha_radar as radar


class RetrievalImprovements(unittest.TestCase):
    def test_unhealthy_scout_url_kept_but_healthy_distinct_publishers_fetched_first(self):
        scout = ["https://www.globenewswire.com/a"]
        focused = ["https://www.reuters.com/a", "https://www.prnewswire.com/a", "https://www.cnbc.com/a"]
        merged = radar.merge_candidate_urls(scout, focused, limit=3, unhealthy_domains={"globenewswire.com"})
        self.assertEqual(merged, [focused[0], focused[2], focused[1]])
        self.assertEqual(len({radar.publisher_domain(u) for u in merged}), 3)

    def test_unhealthy_scout_remains_available_as_rescue_alternative(self):
        scout=["https://www.globenewswire.com/scout"]
        focused=[f"https://s{i}.example/story" for i in range(5)]
        selected=radar.merge_candidate_urls(scout,focused,limit=3,unhealthy_domains={"globenewswire.com"})
        alternates=radar.candidate_alternate_urls(scout,focused,selected,unhealthy_domains={"globenewswire.com"})
        self.assertNotIn(scout[0],selected)
        self.assertIn(scout[0],alternates)

    def test_one_forbidden_url_does_not_suppress_accessible_sibling(self):
        urls = ["https://www.sec.gov/a", "https://www.sec.gov/b"]
        calls = []
        def forbidden(url, timeout):
            calls.append(url)
            raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)
        diagnostics = []
        with patch.object(radar, "fetch_source", side_effect=forbidden), patch.object(
            radar, "fetch_source_via_gateway", return_value=None
        ):
            radar.gather_evidence(urls, diagnostics=diagnostics, collection_budget_seconds=3)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(diagnostics), 2)
        self.assertTrue(all(d["reason"] == "source_http_forbidden" for d in diagnostics))

    def test_timeout_on_one_url_does_not_suppress_distinct_sibling(self):
        urls = ["https://www.globenewswire.com/a", "https://www.globenewswire.com/b"]
        calls = []
        def timeout(url, seconds):
            calls.append(url)
            raise TimeoutError("timed out")
        diagnostics = []
        with patch.object(radar, "fetch_source", side_effect=timeout), patch.object(
            radar, "fetch_source_via_gateway", return_value=None
        ):
            radar.gather_evidence(urls, diagnostics=diagnostics, collection_budget_seconds=3)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(d["reason"] == "source_fetch_timeout" for d in diagnostics))

    def test_successful_same_publisher_urls_fetch_concurrently_within_budget(self):
        urls=["https://www.sec.gov/a","https://www.sec.gov/b"]
        def slow(url,timeout):
            time.sleep(0.12)
            return {"url":url,"text":"Material filing "*20,"published_at":"2026-09-29T00:00:00Z"}
        with patch.object(radar,"fetch_source",side_effect=slow):
            result=radar.gather_evidence(urls,collection_budget_seconds=0.2)
        self.assertEqual({p["url"] for p in result},set(urls))

    def test_one_forbidden_url_does_not_suppress_accessible_sibling_page(self):
        urls=["https://www.sec.gov/blocked","https://www.sec.gov/allowed"]
        def direct(url,timeout):
            if url==urls[0]:raise urllib.error.HTTPError(url,403,"forbidden",{},None)
            return {"url":url,"text":"Material filing "*20,"published_at":"2026-09-29T00:00:00Z"}
        with patch.object(radar,"fetch_source",side_effect=direct),patch.object(
            radar,"fetch_source_via_gateway",return_value=None
        ):
            result=radar.gather_evidence(urls,collection_budget_seconds=1)
        self.assertEqual([p["url"] for p in result],[urls[1]])

    def test_same_publisher_requests_launch_without_serial_wait(self):
        urls=["https://www.sec.gov/a","https://www.sec.gov/b"]
        calls=[]
        def slow(url,timeout):
            calls.append(url)
            if url==urls[0]:time.sleep(0.08)
            return {"url":url,"text":"Material filing "*20,"published_at":"2026-09-29T00:00:00Z"}
        with patch.object(radar,"fetch_source",side_effect=slow):
            radar.gather_evidence(urls,collection_budget_seconds=0.02)
        time.sleep(0.12)
        self.assertEqual(set(calls),set(urls))

    def test_second_same_publisher_url_still_tries_gateway_after_direct_block(self):
        urls=["https://www.sec.gov/a","https://www.sec.gov/b"]
        page={"url":urls[1],"text":"Material filing "*20,"published_at":"2026-09-29T00:00:00Z"}
        calls=[]
        def direct(url,timeout):
            raise urllib.error.HTTPError(url,403,"forbidden",{},None)
        def gateway(url,**kwargs):
            calls.append(url)
            return page if url==urls[1] else None
        diagnostics=[]
        with patch.object(radar,"fetch_source",side_effect=direct),patch.object(
            radar,"fetch_source_via_gateway",side_effect=gateway
        ):
            result=radar.gather_evidence(urls,diagnostics=diagnostics,collection_budget_seconds=5)
        self.assertEqual(result,[page])
        self.assertEqual(calls,urls)

    def test_sec_archive_url_rejects_malformed_port_without_crashing(self):
        url="https://www.sec.gov:bad/Archives/edgar/data/1045810/000104581026000001/report.htm"
        self.assertFalse(radar.is_sec_archive_filing_url(url))

    def test_sec_filing_metadata_repairs_date_only_value(self):
        url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/report.htm"
        page={"url":url,"text":"Material filing "*20,"published_at":"2026-09-29"}
        result=radar.attach_sec_filing_dates([page],{url:"2026-09-29"})
        self.assertEqual(result[0]["published_at"],"2026-09-29T00:00:00Z")

    def test_sec_filing_metadata_supplies_date_only_to_matching_fetched_document(self):
        url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/report.htm"
        page={"url":url,"text":"Material event filing "*20,"published_at":None}
        filings={url:"2026-09-29"}
        enriched=radar.attach_sec_filing_dates([page],filings)
        self.assertEqual(enriched[0]["published_at"],"2026-09-29T00:00:00Z")
        self.assertIsNone(page["published_at"])
        other={"url":"https://other.example/filing","text":"Material event "*20,"published_at":None}
        self.assertIsNone(radar.attach_sec_filing_dates([other],filings)[0]["published_at"])

    def test_initial_sec_page_uses_verified_submissions_date(self):
        url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/report.htm"
        scout=subprocess.CompletedProcess([],0,json.dumps({"candidates":[{
            "symbol":"NVDA","catalyst":"new event","event_date":"2026-09-29","urls":[url]
        }]}),"")
        page={"url":url,"title":"8-K","text":"Material event "*20,"published_at":None}
        observed=[]
        def verify(pages,**kwargs):
            observed.extend(pages)
            return [],[{"url":url,"domain":"www.sec.gov","reason":"source_freshness_unknown"}]
        with tempfile.TemporaryDirectory() as td, patch.object(radar,"ROOT",Path(td)), patch.object(
            radar.subprocess,"run",return_value=scout
        ), patch.object(radar,"gather_evidence",return_value=[page]), patch.object(
            radar,"sec_filing_date_for_url",return_value="2026-09-29"
        ), patch.object(radar,"filter_evidence",side_effect=verify), patch.object(
            radar,"post_fetch_rescue_candidate",return_value=[]
        ):
            with self.assertRaises(radar.ResearchFailure):
                radar.live_research({"max_position_usd":500})
        self.assertEqual(observed[0]["published_at"],"2026-09-29T00:00:00Z")

    def test_sec_rescue_uses_verified_filing_date_from_submission(self):
        url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/report.htm"
        candidate={"symbol":"NVDA","catalyst":"event","event_date":"2026-09-29","urls":["https://one.example/story"]}
        page={"url":url,"text":"Material event "*20,"published_at":None}
        diagnostics=[]
        with patch.object(radar,"sec_edgar_filing_url",return_value=url), patch.object(
            radar,"gather_evidence",return_value=[page]
        ), patch.object(radar,"sec_filing_date_for_url",return_value="2026-09-29"), patch.object(
            radar,"gateway_rescue_url",return_value=None
        ):
            result=radar.post_fetch_rescue_candidate(candidate,[],diagnostics=diagnostics,deadline=radar.monotonic()+20)
        self.assertEqual(result[0]["published_at"],"2026-09-29T00:00:00Z")

    def test_rescue_tries_unfetched_focused_alternative_before_model_search(self):
        candidate={"symbol":"AAA","catalyst":"event","event_date":"2026-09-29",
                   "urls":["https://www.globenewswire.com/a"],
                   "_alternate_urls":["https://www.reuters.com/a"]}
        accepted=[{"url":"https://www.globenewswire.com/a","text":"Material event "*20,
                   "published_at":"2026-09-29T12:00:00Z"}]
        independent={"url":"https://www.reuters.com/a","text":"Independent coverage "*20,
                     "published_at":"2026-09-29T13:00:00Z"}
        with patch.object(radar,"gather_evidence",return_value=[independent]) as fetch, patch.object(
            radar,"gateway_rescue_url",side_effect=AssertionError("model search not needed")
        ), patch.object(radar,"sec_edgar_filing_url",return_value=None):
            result=radar.post_fetch_rescue_candidate(candidate,accepted,diagnostics=[],deadline=radar.monotonic()+10)
        self.assertEqual(len(result),2)
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0],[independent["url"]])

    def test_rescue_prioritizes_one_accepted_domain_over_zero(self):
        a={"symbol":"AAA","urls":["https://a.example/a"]}
        b={"symbol":"BBB","urls":["https://b.example/b"]}
        pages=[{"url":"https://b.example/b","text":"valid story "*20,"published_at":"2026-09-29T12:00:00Z"}]
        ordered=radar.prioritize_thin_candidates([a,b],pages)
        self.assertEqual([c["symbol"] for c in ordered],["BBB","AAA"])

if __name__ == "__main__":
    unittest.main()
