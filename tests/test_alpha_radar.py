"""Tests for the alpha_radar two-stage research pipeline and fallback."""
import argparse
import contextlib
import io
import json
import subprocess
import tempfile
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
        self.assertEqual(scout[scout.index("--run-budget") + 1], "60")
        self.assertIn("--safe-mode", synthesis)
        self.assertEqual(synthesis[synthesis.index("-t") + 1], "")
        self.assertEqual(synthesis[synthesis.index("--max-turns") + 1], "1")
        self.assertEqual(synthesis[synthesis.index("--run-budget") + 1], "45")

    def test_scout_prompt_bounded_and_url_only(self):
        self.assertIn("3-6 plain http(s) URLs", alpha_radar.SCOUT_PROMPT)
        self.assertIn("No commentary", alpha_radar.SCOUT_PROMPT)

    def test_extract_candidate_urls_dedupes_per_domain_and_caps_six(self):
        text = "https://a.com/1\nhttps://a.com/2\nhttps://b.com/x\nhttps://c.com/y"
        self.assertEqual(
            alpha_radar.extract_candidate_urls(text, limit=6),
            ["https://a.com/1", "https://b.com/x", "https://c.com/y"],
        )

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

    def test_live_research_types_source_fetch_and_parse_failures(self):
        scout=subprocess.CompletedProcess([],0,"https://a.example/1\nhttps://b.example/2\n","")
        synth=subprocess.CompletedProcess([],0,"not-json","")
        with patch.object(alpha_radar.subprocess,"run",side_effect=[scout,synth]), patch.object(
            alpha_radar,"gather_evidence",return_value=[
                {"url":"https://a.example/1","title":"A","text":"a"},
                {"url":"https://b.example/2","title":"B","text":"b"},
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

    def test_main_types_source_verification_and_persistence_failures(self):
        candidate={
            "symbol":"AAPL","price":100,"spy_price":500,"instrument_type":"cash_equity",
            "sources":[{"url":"https://a.example/1"},{"url":"https://b.example/2"}],
            "earnings_event_at":"2026-11-01T21:00:00Z","researched_at":"2026-09-05T14:00:00Z",
            "setup_type":"post_news_momentum","planned_exit_at":"2026-09-18T20:00:00Z",
            "horizon_rationale":"repricing","thesis":"x","catalyst":"y",
        }
        for verification,append_error,expected in (
            (False,None,"SYSTEM_FAILURE research_source_verification_failed"),
            (True,OSError("disk"),"SYSTEM_FAILURE research_persistence_failure"),
        ):
            out=io.StringIO()
            with patch.object(alpha_radar,"reusable_fresh_candidate",return_value=None), patch.object(
                alpha_radar,"fresh_verified_candidate",return_value=None
            ), patch.object(alpha_radar,"live_research",return_value=candidate), patch.object(
                alpha_radar,"verify_sources",return_value=verification
            ), patch.object(alpha_radar,"append",side_effect=append_error), contextlib.redirect_stdout(out):
                rc=alpha_radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
            self.assertEqual(rc,3)
            self.assertEqual(out.getvalue().strip(),expected)

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

    def test_run_cycle_radar_retries_once_with_short_timeout(self):
        source = (alpha_radar.ROOT / "run_cycle.py").read_text()
        self.assertIn("timeout_seconds=150", source)
        self.assertIn("attempts=1", source)


if __name__ == "__main__":
    unittest.main()
