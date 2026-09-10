"""Tests for the alpha_radar two-stage research pipeline and fallback."""
import argparse
import contextlib
import io
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import alpha_radar


class AlphaRadarTests(unittest.TestCase):
    def test_research_is_two_stage_with_bounded_scout_and_tool_free_synthesis(self):
        scout = alpha_radar.discovery_command()
        synthesis = alpha_radar.synthesis_command()

        self.assertEqual(scout[scout.index("-t") + 1], "web")
        self.assertEqual(scout[scout.index("--max-turns") + 1], "3")
        self.assertEqual(scout[scout.index("--run-budget") + 1], "180")
        self.assertIn("--safe-mode", synthesis)
        self.assertEqual(synthesis[synthesis.index("-t") + 1], "")
        self.assertEqual(synthesis[synthesis.index("--max-turns") + 1], "1")
        self.assertEqual(synthesis[synthesis.index("--run-budget") + 1], "45")

    def test_scout_prompt_bounded_and_url_only(self):
        self.assertIn("2-7 plain http(s) URLs", alpha_radar.SCOUT_PROMPT)
        self.assertIn("No commentary", alpha_radar.SCOUT_PROMPT)
        self.assertIn("web_extract exactly twice in parallel", alpha_radar.SCOUT_PROMPT)
        self.assertIn("Do not submit search-result pages", alpha_radar.SCOUT_PROMPT)
        self.assertIn("older than 180 days", alpha_radar.SCOUT_PROMPT)
        self.assertIn("web_search exactly twice in parallel", alpha_radar.SCOUT_PROMPT)
        self.assertIn("Use exactly two tool-using turns", alpha_radar.SCOUT_PROMPT)

    def test_extract_candidate_urls_dedupes_per_domain_and_caps_six(self):
        text = "https://a.com/1\nhttps://a.com/2\nhttps://b.com/x\nhttps://c.com/y"
        self.assertEqual(
            alpha_radar.extract_candidate_urls(text, limit=6),
            ["https://a.com/1", "https://b.com/x", "https://c.com/y"],
        )

    def test_fetch_source_prefers_article_over_navigation_prefix(self):
        html = (
            "<html><head><title>Current release</title></head><body>"
            + "<nav>" + ("navigation " * 900) + "</nav>"
            + "<article><time datetime='2026-09-02T20:05:00Z'>September 2, 2026</time>"
            + "<h1>Fiscal Q2 2027 results</h1>"
            + "<p>Revenue was $1.55 billion and full-year guidance was raised.</p></article>"
            + "</body></html>"
        ).encode()

        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, _limit): return html

        with patch.object(alpha_radar.urllib.request, "urlopen", return_value=Response()):
            page = alpha_radar.fetch_source("https://issuer.example/release")

        self.assertIn("September 2, 2026", page["text"])
        self.assertIn("$1.55 billion", page["text"])
        self.assertNotIn("navigation navigation", page["text"])

    def test_fetch_source_extracts_structured_publication_time(self):
        html = b"""<html><head><meta property='article:published_time' content='2026-09-02T20:05:00Z'></head><body><article>Current earnings release with enough evidence.</article></body></html>"""

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, _limit): return html

        with patch.object(alpha_radar.urllib.request, "urlopen", return_value=Response()):
            page = alpha_radar.fetch_source("https://issuer.example/release")

        self.assertEqual(page["published_at"], "2026-09-02T20:05:00Z")

    def test_filter_evidence_drops_explicitly_stale_articles(self):
        pages = [
            {"url": "https://old.example/story", "title": "Old", "text": "old event", "published_at": "2025-08-28T14:57:00Z"},
            {"url": "https://new.example/release", "title": "New", "text": "current event", "published_at": "2026-09-02T20:05:00Z"},
        ]
        accepted, diagnostics = alpha_radar.filter_evidence(
            pages,
            now=alpha_radar.dt.datetime(2026, 9, 9, tzinfo=alpha_radar.dt.timezone.utc),
        )

        self.assertEqual([page["url"] for page in accepted], ["https://new.example/release"])
        self.assertEqual(diagnostics, [{"domain": "old.example", "reason": "stale_source"}])

    def test_filter_evidence_applies_staleness_at_exact_timedelta_boundary(self):
        now=alpha_radar.dt.datetime(2026,9,9,12,0,tzinfo=alpha_radar.dt.timezone.utc)
        published=(now-alpha_radar.dt.timedelta(days=180,seconds=1)).isoformat()
        accepted,diagnostics=alpha_radar.filter_evidence([
            {"url":"https://old.example/story","title":"Old","text":"event","published_at":published}
        ],now=now,max_age_days=180)
        self.assertEqual(accepted,[])
        self.assertEqual(diagnostics,[{"domain":"old.example","reason":"stale_source"}])

    def test_filter_evidence_drops_navigation_only_body(self):
        pages = [{
            "url": "https://ir.example/quarterly-results",
            "title": "Quarterly Results",
            "text": "Investor Menu Site Search Investor Email Alerts Subscribe Unsubscribe Privacy Notice",
            "published_at": None,
        }]
        accepted, diagnostics = alpha_radar.filter_evidence(
            pages,
            now=alpha_radar.dt.datetime(2026, 9, 9, tzinfo=alpha_radar.dt.timezone.utc),
        )
        self.assertEqual(accepted, [])
        self.assertEqual(diagnostics, [{"domain": "ir.example", "reason": "article_body_missing"}])

    def test_filter_evidence_types_empty_body(self):
        accepted,diagnostics=alpha_radar.filter_evidence([
            {"url":"https://empty.example/story","title":"","text":"","published_at":None}
        ])
        self.assertEqual(accepted,[])
        self.assertEqual(diagnostics,[{"domain":"empty.example","reason":"article_body_missing"}])

    def test_filter_evidence_rejects_title_only_page_as_missing_body(self):
        accepted,diagnostics=alpha_radar.filter_evidence([
            {"url":"https://title.example/story","title":"Quarterly results","text":"   ","published_at":"2026-09-08T15:00:00Z"}
        ],now=alpha_radar.dt.datetime(2026,9,9,tzinfo=alpha_radar.dt.timezone.utc))
        self.assertEqual(accepted,[])
        self.assertEqual(diagnostics,[{"domain":"title.example","reason":"article_body_missing"}])

    def test_gather_evidence_records_typed_fetch_failures(self):
        diagnostics = []

        def fetch(url, _timeout):
            if "slow.example" in url:
                raise TimeoutError("read timed out")
            return {"url": url, "title": "Current", "text": "usable evidence", "published_at": None}

        with patch.object(alpha_radar, "fetch_source", side_effect=fetch), patch.object(
            alpha_radar, "fetch_source_via_gateway", return_value=None
        ):
            pages = alpha_radar.gather_evidence(
                ["https://slow.example/a", "https://ok.example/b"],
                diagnostics=diagnostics,
            )

        self.assertEqual([page["url"] for page in pages], ["https://ok.example/b"])
        self.assertEqual(diagnostics, [{"domain": "slow.example", "reason": "source_fetch_timeout"}])

    def test_filter_evidence_fails_closed_when_freshness_unknown(self):
        now=alpha_radar.dt.datetime(2026,9,9,12,0,tzinfo=alpha_radar.dt.timezone.utc)
        for published in (None,"not-a-date","2026-13-99T99:00:00Z","2026-09-08T15:00:00"):
            accepted,diagnostics=alpha_radar.filter_evidence([
                {"url":"https://u.example/story","title":"U","text":"event body","published_at":published}
            ],now=now)
            self.assertEqual(accepted,[],published)
            self.assertEqual(diagnostics,[{"domain":"u.example","reason":"source_freshness_unknown"}],published)

    def test_record_research_diagnostics_persists_freshness_unknown_reason(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"private"/"research_diagnostics.jsonl"
            alpha_radar.record_research_diagnostics(
                [{"domain":"u.example","reason":"source_freshness_unknown"}],
                path=path,
                now="2026-09-09T12:31:52Z",
            )
            row=json.loads(path.read_text())
        self.assertEqual(row["reason"],"source_freshness_unknown")
        self.assertEqual(row["stage"],"source_quality")

    def test_gather_evidence_types_still_alive_workers_and_is_deterministic(self):
        diagnostics = []

        def fetch(url, _timeout):
            if "hung.example" in url:
                time.sleep(95)
                return {"url": url, "title": "Late", "text": "late body", "published_at": None}
            return {"url": url, "title": "Current", "text": "usable evidence", "published_at": None}

        with patch.object(alpha_radar, "fetch_source", side_effect=fetch), patch.object(
            alpha_radar, "fetch_source_via_gateway", return_value=None
        ):
            pages = alpha_radar.gather_evidence(
                ["https://hung.example/a", "https://ok.example/b"],
                per_source_timeout=1,
                diagnostics=diagnostics,
            )

        self.assertEqual([page["url"] for page in pages], ["https://ok.example/b"])
        self.assertEqual(pages[0]["text"], "usable evidence")
        self.assertEqual(diagnostics, [{"domain": "hung.example", "reason": "source_fetch_timeout"}])

    def test_record_research_diagnostics_uses_strict_private_projection(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "private" / "research_diagnostics.jsonl"
            alpha_radar.record_research_diagnostics(
                [{"domain": "slow.example", "reason": "source_fetch_timeout", "raw_error": "secret traceback"}],
                path=path,
                now="2026-09-09T12:31:52Z",
            )
            row = json.loads(path.read_text())

        self.assertEqual(row, {
            "domain": "slow.example",
            "reason": "source_fetch_timeout",
            "stage": "source_fetch",
            "timestamp": "2026-09-09T12:31:52Z",
        })

    def test_record_synthesis_none_preserves_typed_reason_and_evidence_hash(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "private" / "research_diagnostics.jsonl"
            alpha_radar.record_synthesis_none(
                {"status": "none", "none_reason": "earnings_timestamp_unverified"},
                "bounded synthesis prompt",
                path=path,
                now="2026-09-09T12:31:00Z",
            )
            row = json.loads(path.read_text())
        self.assertEqual(row["stage"], "synthesis")
        self.assertEqual(row["reason"], "earnings_timestamp_unverified")
        self.assertEqual(len(row["evidence_sha256"]), 64)
        self.assertNotIn("bounded synthesis prompt", json.dumps(row))

    def test_synthesis_prompt_requires_citations_and_bans_tools(self):
        p = alpha_radar.synthesis_prompt(
            "",  # let the function build the evidence block from sources
            [
                {"title": "A", "url": "https://a.example/1", "text": "alpha body"},
                {"title": "B", "url": "https://b.example/2", "text": "beta body"},
            ],
            {"max_position_usd": 10000},
        )
        self.assertIn("Use ONLY the numbered evidence", p)
        self.assertIn("Do not browse, search, or call any tools", p)
        self.assertIn("cite the evidence index like [1]", p)
        self.assertIn("[1] A — https://a.example/1", p)
        self.assertIn("[2] B — https://b.example/2", p)
        self.assertIn("Do not return price or spy_price", p)
        self.assertIn("must not reject a setup because price, SPY price, stop, target, or technical levels are absent", p)
        self.assertIn("Use no_fresh_setup only when the evidence bundle is current and adequate", p)
        self.assertIn('"none_reason"', p)

    def test_live_research_raises_typed_timeout(self):
        calls = {"n": 0}

        def _raise(cmd, **k):
            calls["n"] += 1
            raise subprocess.TimeoutExpired(cmd="x", timeout=90)

        with patch.object(alpha_radar.subprocess, "run", side_effect=_raise):
            with patch.object(alpha_radar, "gather_evidence", return_value=[]):
                with self.assertRaises(RuntimeError) as ctx:
                    alpha_radar.live_research({"max_position_usd": 500})
        self.assertEqual(str(ctx.exception), "research_scout_timeout")

    def test_main_reports_scout_timeout_without_generic_fallback(self):
        out=io.StringIO()
        with patch.object(alpha_radar,"reusable_fresh_candidate",return_value=None), patch.object(
            alpha_radar,"fresh_verified_candidate",return_value=None
        ), patch.object(
            alpha_radar,"live_research",side_effect=alpha_radar.ResearchFailure("research_scout_timeout")
        ), contextlib.redirect_stdout(out):
            rc=alpha_radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual(rc,3)
        self.assertEqual(out.getvalue().strip(),"SYSTEM_FAILURE research_scout_timeout")

    def test_main_reports_normalized_synthesis_none_reason(self):
        out=io.StringIO()
        with patch.object(alpha_radar,"reusable_fresh_candidate",return_value=None), patch.object(
            alpha_radar,"live_research",return_value={"status":"none","none_reason":"earnings_timestamp_unverified"}
        ), contextlib.redirect_stdout(out):
            rc=alpha_radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual(rc,2)
        self.assertEqual(out.getvalue().strip(),"BLOCKER research_earnings_timestamp_unverified")

    def test_main_treats_supported_no_setup_as_healthy_noop(self):
        out=io.StringIO()
        with patch.object(alpha_radar,"reusable_fresh_candidate",return_value=None), patch.object(
            alpha_radar,"live_research",return_value={"status":"none","none_reason":"no_fresh_setup"}
        ), contextlib.redirect_stdout(out):
            rc=alpha_radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual(rc,0)
        self.assertEqual(out.getvalue().strip(),"DECISION skipped no_fresh_setup")

    def test_main_rejects_unrecognized_synthesis_none_reason(self):
        out=io.StringIO()
        with patch.object(alpha_radar,"reusable_fresh_candidate",return_value=None), patch.object(
            alpha_radar,"live_research",return_value={"status":"none","none_reason":"arbitrary model prose"}
        ), contextlib.redirect_stdout(out):
            rc=alpha_radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual(rc,2)
        self.assertEqual(out.getvalue().strip(),"BLOCKER research_evidence_insufficient")

    def test_live_research_types_source_fetch_and_parse_failures(self):
        scout=subprocess.CompletedProcess([],0,"https://a.example/1\nhttps://b.example/2\n","")
        synth=subprocess.CompletedProcess([],0,"not-json","")
        with patch.object(alpha_radar.subprocess,"run",side_effect=[scout,synth]), patch.object(
            alpha_radar,"gather_evidence",return_value=[
                {"url":"https://a.example/1","title":"A","text":"a","published_at":"2026-09-08T14:57:00Z"},
                {"url":"https://b.example/2","title":"B","text":"b","published_at":"2026-09-08T15:00:00Z"},
            ]
        ):
            with self.assertRaises(alpha_radar.ResearchFailure) as ctx:
                alpha_radar.live_research({"max_position_usd":500})
        self.assertEqual(ctx.exception.code,"research_parse_failure")
        with patch.object(alpha_radar.subprocess,"run",return_value=scout), patch.object(
            alpha_radar,"gather_evidence",return_value=[{"url":"https://a.example/1","text":"a"}]
        ):
            with self.assertRaises(alpha_radar.ResearchFailure) as ctx:
                alpha_radar.live_research({"max_position_usd":500})
        self.assertEqual(ctx.exception.code,"research_source_fetch_failed")

    def test_live_research_filters_stale_evidence_and_records_diagnostic(self):
        scout=subprocess.CompletedProcess([],0,"https://old.example/1\nhttps://a.example/2\nhttps://b.example/3\n","")
        synth=subprocess.CompletedProcess([],0,json.dumps({"status":"none","none_reason":"no_fresh_setup"}),"")
        pages=[
            {"url":"https://old.example/1","title":"Old","text":"stale event","published_at":"2025-08-28T14:57:00Z"},
            {"url":"https://a.example/2","title":"A","text":"current event","published_at":"2026-09-08T14:57:00Z"},
            {"url":"https://b.example/3","title":"B","text":"current confirmation","published_at":"2026-09-08T15:00:00Z"},
        ]
        calls=[]
        def run(_cmd, **kwargs):
            calls.append(kwargs.get("input", ""))
            return scout if len(calls)==1 else synth

        with tempfile.TemporaryDirectory() as td, patch.object(alpha_radar,"ROOT",Path(td)), patch.object(
            alpha_radar.subprocess,"run",side_effect=run
        ), patch.object(alpha_radar,"gather_evidence",return_value=pages):
            candidate=alpha_radar.live_research({"max_position_usd":500})
            diagnostics=[json.loads(line) for line in (Path(td)/"private"/"research_diagnostics.jsonl").read_text().splitlines()]

        self.assertEqual(candidate["none_reason"],"no_fresh_setup")
        self.assertNotIn("old.example",calls[1])
        self.assertEqual([row["reason"] for row in diagnostics[:3]],["stale_source","fetched","fetched"])
        self.assertEqual(diagnostics[3]["stage"],"synthesis")
        self.assertEqual(diagnostics[3]["reason"],"no_fresh_setup")
        self.assertEqual(len(diagnostics[3]["evidence_sha256"]),64)

    def test_live_research_types_diagnostic_persistence_failure(self):
        scout=subprocess.CompletedProcess([],0,"https://a.example/1\nhttps://b.example/2\n","")
        pages=[
            {"url":"https://a.example/1","title":"A","text":"current event","published_at":"2026-09-08T14:57:00Z"},
            {"url":"https://b.example/2","title":"B","text":"current confirmation","published_at":"2026-09-08T15:00:00Z"},
        ]
        with patch.object(alpha_radar.subprocess,"run",return_value=scout), patch.object(
            alpha_radar,"gather_evidence",return_value=pages
        ), patch.object(alpha_radar,"record_research_diagnostics",side_effect=OSError("disk")):
            with self.assertRaises(alpha_radar.ResearchFailure) as ctx:
                alpha_radar.live_research({"max_position_usd":500})
        self.assertEqual(ctx.exception.code,"research_persistence_failure")

    def test_live_research_types_synthesis_diagnostic_persistence_failure(self):
        scout=subprocess.CompletedProcess([],0,"https://a.example/1\nhttps://b.example/2\n","")
        synth=subprocess.CompletedProcess([],0,json.dumps({"status":"none","none_reason":"no_fresh_setup"}),"")
        pages=[
            {"url":"https://a.example/1","title":"A","text":"current event","published_at":"2026-09-08T14:57:00Z"},
            {"url":"https://b.example/2","title":"B","text":"current confirmation","published_at":"2026-09-08T15:00:00Z"},
        ]
        with patch.object(alpha_radar.subprocess,"run",side_effect=[scout,synth]), patch.object(
            alpha_radar,"gather_evidence",return_value=pages
        ), patch.object(alpha_radar,"record_synthesis_none",side_effect=OSError("disk")):
            with self.assertRaises(alpha_radar.ResearchFailure) as ctx:
                alpha_radar.live_research({"max_position_usd":500})
        self.assertEqual(ctx.exception.code,"research_persistence_failure")

    def test_live_research_replaces_model_prices_with_synchronized_market_data(self):
        scout=subprocess.CompletedProcess([],0,"https://a.example/1\nhttps://b.example/2\n","")
        model_candidate={
            "symbol":"SNOW","price":1.0,"spy_price":2.0,"instrument_type":"cash_equity",
            "sources":[{"url":"https://a.example/1"},{"url":"https://b.example/2"}],
        }
        synth=subprocess.CompletedProcess([],0,json.dumps(model_candidate),"")
        market_prices={
            "price":337.18,"spy_price":770.19,
            "market_prices_at":"2026-09-04T20:00:00Z",
            "market_price_feed":"massive_consolidated_completed_daily",
        }
        with patch.object(alpha_radar.subprocess,"run",side_effect=[scout,synth]), patch.object(
            alpha_radar,"gather_evidence",return_value=[
                {"url":"https://a.example/1","title":"A","text":"a","published_at":"2026-09-08T14:57:00Z"},
                {"url":"https://b.example/2","title":"B","text":"b","published_at":"2026-09-08T15:00:00Z"},
            ]
        ), patch.object(
            alpha_radar,"synchronized_completed_close_prices",return_value=market_prices
        ) as prices:
            candidate=alpha_radar.live_research({"max_position_usd":500})

        prices.assert_called_once_with("SNOW")
        self.assertEqual(candidate["price"],337.18)
        self.assertEqual(candidate["spy_price"],770.19)
        self.assertEqual(candidate["market_prices_at"],"2026-09-04T20:00:00Z")
        self.assertEqual(candidate["market_price_feed"],"massive_consolidated_completed_daily")
        self.assertEqual(candidate["sources"],[
            {"url":"https://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z"},
            {"url":"https://b.example/2","title":"B","published_at":"2026-09-08T15:00:00Z"},
        ])
        self.assertEqual(len(candidate["_source_receipts"]),2)
        self.assertTrue(all(len(receipt["content_sha256"])==64 for receipt in candidate["_source_receipts"]))
        self.assertTrue(alpha_radar.verify_sources(candidate))

    def test_source_verification_result_types_missing_receipt_with_counts(self):
        candidate={
            "sources":[
                {"url":"https://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z"},
                {"url":"https://b.example/2","title":"B","published_at":"2026-09-08T15:00:00Z"},
            ],
            "_source_receipts":[
                {"url":"https://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z","content_sha256":"a"*64},
            ],
        }

        self.assertEqual(alpha_radar.source_verification_result(candidate),{
            "passed":False,
            "reason":"receipt_missing",
            "domain":"b.example",
            "cited_sources":2,
            "matched_receipts":1,
            "independent_domains":1,
            "required_independent_domains":2,
        })

    def test_source_verification_preserves_legacy_acceptance_of_matching_non_http_url(self):
        candidate={
            "sources":[
                {"url":"ftp://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z"},
                {"url":"https://b.example/2","title":"B","published_at":"2026-09-08T15:00:00Z"},
            ],
            "_source_receipts":[
                {"url":"ftp://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z","content_sha256":"a"*64},
                {"url":"https://b.example/2","title":"B","published_at":"2026-09-08T15:00:00Z","content_sha256":"b"*64},
            ],
        }

        self.assertTrue(alpha_radar.source_verification_result(candidate)["passed"])
        self.assertTrue(alpha_radar.verify_sources(candidate))

    def test_record_source_verification_diagnostic_persists_strict_private_projection(self):
        result={
            "passed":False,"reason":"receipt_metadata_mismatch","domain":"news.example",
            "cited_sources":3,"matched_receipts":2,"independent_domains":1,
            "required_independent_domains":2,"url":"https://news.example/private",
            "content_sha256":"secret","raw_error":"secret traceback",
        }
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"private"/"research_diagnostics.jsonl"
            alpha_radar.record_source_verification_diagnostic(
                result,path=path,now="2026-09-10T13:30:00Z"
            )
            row=json.loads(path.read_text())

        self.assertEqual(row,{
            "timestamp":"2026-09-10T13:30:00Z","stage":"source_verification",
            "reason":"receipt_metadata_mismatch","domain":"news.example",
            "cited_sources":3,"matched_receipts":2,"independent_domains":1,
            "required_independent_domains":2,
        })

    def test_verify_sources_uses_immutable_receipts_without_network_refetch(self):
        candidate={
            "sources":[
                {"url":"https://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z"},
                {"url":"https://b.example/2","title":"B","published_at":"2026-09-08T15:00:00Z"},
            ],
            "_source_receipts":[
                {"url":"https://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z","content_sha256":"a"*64},
                {"url":"https://b.example/2","title":"B","published_at":"2026-09-08T15:00:00Z","content_sha256":"b"*64},
            ],
        }

        with patch.object(alpha_radar.urllib.request,"urlopen",side_effect=TimeoutError("transient")) as refetch:
            self.assertTrue(alpha_radar.verify_sources(candidate))
        refetch.assert_not_called()

    def test_live_research_types_synchronized_market_data_failure(self):
        scout=subprocess.CompletedProcess([],0,"https://a.example/1\nhttps://b.example/2\n","")
        synth=subprocess.CompletedProcess([],0,json.dumps({"symbol":"SNOW","status":"ok"}),"")
        with patch.object(alpha_radar.subprocess,"run",side_effect=[scout,synth]), patch.object(
            alpha_radar,"gather_evidence",return_value=[
                {"url":"https://a.example/1","title":"A","text":"a","published_at":"2026-09-08T14:57:00Z"},
                {"url":"https://b.example/2","title":"B","text":"b","published_at":"2026-09-08T15:00:00Z"},
            ]
        ), patch.object(
            alpha_radar,"synchronized_completed_close_prices",
            side_effect=RuntimeError("massive_synchronized_prices_unavailable"),
        ):
            with self.assertRaises(alpha_radar.ResearchFailure) as ctx:
                alpha_radar.live_research({"max_position_usd":500})
        self.assertEqual(ctx.exception.code,"research_market_data_unavailable")

    def test_main_strips_private_source_receipts_before_persisting(self):
        candidate={
            "symbol":"AAPL","price":100,"spy_price":500,"instrument_type":"cash_equity",
            "sources":[
                {"url":"https://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z"},
                {"url":"https://b.example/2","title":"B","published_at":"2026-09-08T15:00:00Z"},
            ],
            "_source_receipts":[
                {"url":"https://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z","content_sha256":"a"*64},
                {"url":"https://b.example/2","title":"B","published_at":"2026-09-08T15:00:00Z","content_sha256":"b"*64},
            ],
            "earnings_event_at":"2026-11-01T21:00:00Z","researched_at":"2026-09-09T14:00:00Z",
            "setup_type":"post_news_momentum","planned_exit_at":"2026-09-18T20:00:00Z",
            "horizon_rationale":"repricing","thesis":"x","catalyst":"y",
        }
        with patch.object(alpha_radar,"reusable_fresh_candidate",return_value=None), patch.object(
            alpha_radar,"fresh_verified_candidate",return_value=None
        ), patch.object(alpha_radar,"live_research",return_value=candidate), patch.object(
            alpha_radar,"candidate_preflight",return_value=[]
        ), patch.object(alpha_radar,"qualified",return_value=True), patch.object(
            alpha_radar,"append"
        ) as append:
            rc=alpha_radar.main_with_args(argparse.Namespace(dry_run_fixture=False))

        self.assertEqual(rc,0)
        persisted=append.call_args.args[0]
        self.assertNotIn("_source_receipts",persisted)
        self.assertIn("sources_verified_at",persisted)

    def test_main_records_typed_verification_detail_without_changing_public_failure(self):
        candidate={
            "symbol":"AAPL","price":100,"spy_price":500,"instrument_type":"cash_equity",
            "sources":[
                {"url":"https://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z"},
                {"url":"https://b.example/2","title":"B","published_at":"2026-09-08T15:00:00Z"},
            ],
            "_source_receipts":[
                {"url":"https://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z","content_sha256":"a"*64},
            ],
            "earnings_event_at":"2026-11-01T21:00:00Z","researched_at":"2026-09-09T14:00:00Z",
            "setup_type":"post_news_momentum","planned_exit_at":"2026-09-18T20:00:00Z",
            "horizon_rationale":"repricing","thesis":"x","catalyst":"y",
        }
        out=io.StringIO()
        with patch.object(alpha_radar,"reusable_fresh_candidate",return_value=None), patch.object(
            alpha_radar,"fresh_verified_candidate",return_value=None
        ), patch.object(alpha_radar,"live_research",return_value=candidate), patch.object(
            alpha_radar,"candidate_preflight",return_value=[]
        ), patch.object(alpha_radar,"qualified",return_value=True), patch.object(
            alpha_radar,"record_source_verification_diagnostic"
        ) as record, patch.object(alpha_radar,"append") as append, contextlib.redirect_stdout(out):
            rc=alpha_radar.main_with_args(argparse.Namespace(dry_run_fixture=False))

        self.assertEqual(rc,3)
        self.assertEqual(out.getvalue().strip(),"SYSTEM_FAILURE research_source_verification_failed")
        record.assert_called_once()
        self.assertEqual(record.call_args.args[0]["reason"],"receipt_missing")
        append.assert_not_called()

    def test_main_preserves_source_verification_failure_when_diagnostic_write_fails(self):
        candidate={
            "symbol":"AAPL","price":100,"spy_price":500,"instrument_type":"cash_equity",
            "sources":[
                {"url":"https://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z"},
                {"url":"https://b.example/2","title":"B","published_at":"2026-09-08T15:00:00Z"},
            ],
            "_source_receipts":[
                {"url":"https://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z","content_sha256":"a"*64},
            ],
            "earnings_event_at":"2026-11-01T21:00:00Z","researched_at":"2026-09-09T14:00:00Z",
            "setup_type":"post_news_momentum","planned_exit_at":"2026-09-18T20:00:00Z",
            "horizon_rationale":"repricing","thesis":"x","catalyst":"y",
        }
        out=io.StringIO()
        with patch.object(alpha_radar,"reusable_fresh_candidate",return_value=None), patch.object(
            alpha_radar,"fresh_verified_candidate",return_value=None
        ), patch.object(alpha_radar,"live_research",return_value=candidate), patch.object(
            alpha_radar,"candidate_preflight",return_value=[]
        ), patch.object(alpha_radar,"qualified",return_value=True), patch.object(
            alpha_radar,"record_source_verification_diagnostic",side_effect=OSError("disk")
        ), patch.object(alpha_radar,"append") as append, contextlib.redirect_stdout(out):
            rc=alpha_radar.main_with_args(argparse.Namespace(dry_run_fixture=False))

        self.assertEqual(rc,3)
        self.assertEqual(out.getvalue().strip(),"SYSTEM_FAILURE research_source_verification_failed")
        append.assert_not_called()

    def test_main_types_candidate_persistence_failure(self):
        candidate={
            "symbol":"AAPL","price":100,"spy_price":500,"instrument_type":"cash_equity",
            "sources":[
                {"url":"https://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z"},
                {"url":"https://b.example/2","title":"B","published_at":"2026-09-08T15:00:00Z"},
            ],
            "_source_receipts":[
                {"url":"https://a.example/1","title":"A","published_at":"2026-09-08T14:57:00Z","content_sha256":"a"*64},
                {"url":"https://b.example/2","title":"B","published_at":"2026-09-08T15:00:00Z","content_sha256":"b"*64},
            ],
            "earnings_event_at":"2026-11-01T21:00:00Z","researched_at":"2026-09-05T14:00:00Z",
            "setup_type":"post_news_momentum","planned_exit_at":"2026-09-18T20:00:00Z",
            "horizon_rationale":"repricing","thesis":"x","catalyst":"y",
        }
        out=io.StringIO()
        with patch.object(alpha_radar,"reusable_fresh_candidate",return_value=None), patch.object(
            alpha_radar,"fresh_verified_candidate",return_value=None
        ), patch.object(alpha_radar,"live_research",return_value=candidate), patch.object(
            alpha_radar,"append",side_effect=OSError("disk")
        ), contextlib.redirect_stdout(out):
            rc=alpha_radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual(rc,3)
        self.assertEqual(out.getvalue().strip(),"SYSTEM_FAILURE research_persistence_failure")

    def test_main_reports_typed_research_timeout(self):
        with tempfile.TemporaryDirectory() as td, patch.object(alpha_radar, "ROOT", alpha_radar.ROOT), \
             patch.object(alpha_radar, "fresh_verified_candidate", return_value=None):
            with patch.object(alpha_radar, "live_research", side_effect=RuntimeError("research_synthesis_timeout")):
                rc = alpha_radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual(rc, 3)

    def test_main_does_not_append_to_candidates_on_failure(self):
        alpha_radar.ROOT.joinpath("candidates.jsonl").touch(exist_ok=True)
        before = (alpha_radar.ROOT / "candidates.jsonl").read_text()
        with patch.object(alpha_radar, "fresh_verified_candidate", return_value=None):
            with patch.object(alpha_radar, "live_research", side_effect=RuntimeError("research_synthesis_timeout")):
                alpha_radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual((alpha_radar.ROOT / "candidates.jsonl").read_text(), before)

    def test_main_reuses_fresh_verified_candidate_instead_of_failing(self):
        reused = {
            "symbol": "AAPL", "price": 100.0, "spy_price": 500.0, "instrument_type": "cash_equity",
            "sources": [{"url": "https://one.example/a"}, {"url": "https://two.example/b"}],
            "earnings_event_at": "2026-11-01T21:00:00Z",
            "researched_at": "2026-09-04T13:00:00Z", "sources_verified_at": "2026-09-04T13:05:00Z",
            "setup_type": "post_news_momentum", "planned_exit_at": "2026-09-20T20:00:00Z",
            "horizon_rationale": "fresh drift window", "catalyst": "known", "thesis": "known",
        }
        with tempfile.TemporaryDirectory() as td:
            candidates = Path(td) / "candidates.jsonl"
            candidates.write_text(json.dumps(reused) + "\n")
            before = candidates.read_text()
            with patch.object(alpha_radar, "fresh_verified_candidate", return_value=reused) as lookup:
                with patch.object(alpha_radar, "live_research", side_effect=RuntimeError("research_synthesis_timeout")):
                    rc = alpha_radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
            lookup.assert_called_once()
            self.assertEqual(rc, 0)
            self.assertEqual(candidates.read_text(), before)

    def test_run_cycle_radar_runs_once_with_explicit_timeout(self):
        source = (alpha_radar.ROOT / "run_cycle.py").read_text()
        self.assertIn("timeout_seconds=660", source)
        self.assertIn("attempts=1", source)


if __name__ == "__main__":
    unittest.main()
