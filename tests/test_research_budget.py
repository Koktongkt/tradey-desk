"""Guard tests pinning research subprocess timeouts, the outer cycle budget,
and scout-reliability hardening.

Timeouts must be calibrated against OBSERVED provider latency, and the outer cycle
budget must cover the serialized worst case of every research stage:

    model scout 360 + focused retrieval 240 + shared evidence pipeline 260
    + synthesis 120 + deterministic earnings SEC lookup 45 + 85-second margin
"""
import json
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import alpha_radar
import earnings_calendar


class ResearchBudgetGuardTests(unittest.TestCase):
    def test_scout_timeout_covers_bounded_discovery_call(self):
        source = (alpha_radar.ROOT / "alpha_radar.py").read_text()
        self.assertIn("input=discovery_prompt(cfg),capture_output=True,text=True,timeout=360", source)
        self.assertNotIn("input=SCOUT_PROMPT,capture_output=True,text=True,timeout=240", source)
        # synthesis timeout is unchanged
        self.assertIn("synthesis_deadline=monotonic()+120", source)
        self.assertIn("timeout=min(120,remaining),cwd=ROOT", source)

    def test_scout_run_budget_bounds_discovery(self):
        command = alpha_radar.discovery_command()
        budget_index = command.index("--run-budget") + 1
        self.assertEqual(command[budget_index], "180")
        self.assertEqual(command[command.index("--max-turns")+1],"2")
        self.assertEqual(command[command.index("-t")+1],"search")

    def test_focused_retrieval_has_bounded_tool_budget_and_timeout(self):
        command=alpha_radar.focused_retrieval_command()
        self.assertEqual(command[command.index("--max-turns")+1],"3")
        self.assertEqual(command[command.index("--run-budget")+1],"120")
        source=(alpha_radar.ROOT/"alpha_radar.py").read_text()
        self.assertIn("focused_retrieval_prompt(candidates),capture_output=True,text=True,timeout=240",source)

    def test_cycle_budget_covers_serialized_worst_case(self):
        # 360 scout + 240 focused retrieval + 260 shared rescue/fetch pipeline
        # + 120 synthesis + 45 earnings SEC lookup = 1025;
        # outer 1110 leaves 85 seconds.
        self.assertEqual(earnings_calendar.SEC_LOOKUP_BUDGET_SECONDS,45)
        self.assertEqual(alpha_radar.EVIDENCE_PIPELINE_BUDGET_SECONDS,260)
        source = (alpha_radar.ROOT / "run_cycle.py").read_text()
        self.assertIn(
            'if a.mode in {"premarket","radar"}:rc=execute([sys.executable,str(ROOT/"alpha_radar.py")],timeout_seconds=1110',
            source,
        )
        self.assertNotIn(
            'if a.mode in {"premarket","radar"}:rc=execute([sys.executable,str(ROOT/"alpha_radar.py")],timeout_seconds=960',
            source,
        )


class ScoutReliabilityGuardTests(unittest.TestCase):
    """Guard tests from the 2026-09-09 3-run fetch-failure streak.

    Causes addressed: scout URL hallucination (ir.ionq.com NXDOMAIN),
    intermittent source timeouts (businesswire.com), and a too-thin URL
    surplus (5 candidates minus dedupe/walls/staleness left <2 usable).
    """

    def test_scout_prompt_forbids_unverified_url_construction(self):
        self.assertIn("confirmed article URL copied exactly from the web_search results", alpha_radar.SCOUT_PROMPT)
        self.assertIn("Never construct or guess", alpha_radar.SCOUT_PROMPT)

    def test_scout_returns_ranked_company_event_groups(self):
        self.assertIn('"candidates"', alpha_radar.SCOUT_PROMPT)
        self.assertIn("one to five candidates in ranked order", alpha_radar.SCOUT_PROMPT)

    def test_scout_defers_two_domain_bundle_to_focused_retrieval(self):
        self.assertIn("at least one confirmed article URL",alpha_radar.SCOUT_PROMPT)
        self.assertIn("focused retrieval stage",alpha_radar.SCOUT_PROMPT)
        self.assertIn("apply the final two-domain evidence gate",alpha_radar.SCOUT_PROMPT)

    def test_scout_uses_both_search_calls_in_only_tool_turn(self):
        self.assertIn(
            "call web_search exactly twice in parallel",
            alpha_radar.SCOUT_PROMPT,
        )

    def test_scout_does_not_extract_or_apply_focused_source_gate(self):
        self.assertNotIn("web_extract",alpha_radar.SCOUT_PROMPT)
        self.assertIn("Do not extract pages",alpha_radar.SCOUT_PROMPT)

    def test_live_research_enforces_five_total_discovery_urls(self):
        source = (alpha_radar.ROOT / "alpha_radar.py").read_text()
        self.assertIn("scout_parse_result(scout.stdout,max_candidates=5,max_urls=5)", source)

    def test_gather_evidence_retries_timeouts_once(self):
        attempts = {"n": 0}

        def fetch(url, _timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise TimeoutError("read timed out")
            return {"url": url, "title": "Recovered", "text": "usable evidence", "published_at": "2026-09-08T15:00:00Z"}

        with patch.object(alpha_radar, "fetch_source", side_effect=fetch):
            pages = alpha_radar.gather_evidence(["https://flaky.example/a"])

        self.assertEqual(attempts["n"], 2)
        self.assertEqual([page["title"] for page in pages], ["Recovered"])

    def test_gather_evidence_records_single_timeout_after_retry_exhausted(self):
        diagnostics = []

        def fetch(url, _timeout):
            raise TimeoutError("read timed out")

        with patch.object(alpha_radar, "fetch_source", side_effect=fetch), patch.object(
            alpha_radar, "fetch_source_via_gateway", return_value=None
        ):
            pages = alpha_radar.gather_evidence(
                ["https://down.example/a"], diagnostics=diagnostics
            )

        self.assertEqual(pages, [])
        self.assertEqual(
            diagnostics,
            [{"url":"https://down.example/a","domain": "down.example", "reason": "source_fetch_timeout"}],
        )

    def test_gather_evidence_retries_transient_connection_failure_once(self):
        attempts = {"n": 0}

        def fetch(url, _timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ConnectionResetError("reset")
            return {"url":url,"title":"Recovered","text":"usable evidence","published_at":"2026-09-08T15:00:00Z"}

        with patch.object(alpha_radar, "fetch_source", side_effect=fetch):
            pages = alpha_radar.gather_evidence(["https://bad.example/a"])

        self.assertEqual(attempts["n"], 2)
        self.assertEqual([page["title"] for page in pages],["Recovered"])

    def test_gather_evidence_retries_wrapped_urlerror_connection_failure(self):
        attempts={"n":0}
        def fetch(url,_timeout):
            attempts["n"]+=1
            if attempts["n"]==1:
                raise urllib.error.URLError(ConnectionResetError("reset"))
            return {"url":url,"title":"Recovered","text":"usable evidence","published_at":"2026-09-08T15:00:00Z"}
        with patch.object(alpha_radar,"fetch_source",side_effect=fetch):
            pages=alpha_radar.gather_evidence(["https://wrapped.example/a"])
        self.assertEqual(attempts["n"],2)
        self.assertEqual([page["title"] for page in pages],["Recovered"])

    def test_collection_budget_exhaustion_is_typed_without_starting_fetch(self):
        diagnostics=[]
        with patch.object(alpha_radar,"fetch_source") as direct:
            pages=alpha_radar.gather_evidence(
                ["https://late.example/a"],diagnostics=diagnostics,collection_budget_seconds=0
            )
        direct.assert_not_called()
        self.assertEqual(pages,[])
        self.assertEqual(diagnostics,[{
            "url":"https://late.example/a","domain":"late.example","reason":"source_deadline_exhausted"
        }])

    def test_fresh_source_cache_avoids_network_fetch(self):
        page={"url":"https://cached.example/a","title":"Cached","text":"usable cached evidence","published_at":"2026-09-08T15:00:00Z"}
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/"source_cache.json"
            with patch.object(alpha_radar,"fetch_source",return_value=page) as direct:
                first=alpha_radar.gather_evidence([page["url"]],cache_path=cache)
                original_checked_at=json.loads(cache.read_text())[page["url"]]["checked_at"]
                second=alpha_radar.gather_evidence([page["url"]],cache_path=cache)
                cached_checked_at=json.loads(cache.read_text())[page["url"]]["checked_at"]
        self.assertEqual(first,second)
        self.assertEqual(direct.call_count,1)
        self.assertEqual(cached_checked_at,original_checked_at)


class GatewayFallbackGuardTests(unittest.TestCase):
    """Bot-walled and timing-out primary sources (businesswire.com timeouts,
    investors.* 403s) get one bounded gateway-backed extraction fallback per
    URL. The fallback shells out to the hermes web toolset, which routes
    through the provider gateway and extracted pages direct fetching could
    not (verified 2026-09-09: businesswire.com article recovered)."""

    def test_gather_evidence_falls_back_on_timeout_after_retry(self):
        calls = []

        def direct(url, _timeout):
            calls.append("direct")
            raise TimeoutError("read timed out")

        def fallback(cmd, input=None, capture_output=None, text=None, timeout=None, cwd=None):
            calls.append("fallback")
            self.assertIn("web", cmd)
            return subprocess.CompletedProcess(
                cmd, 0, "Published 2026-09-08. Revenue rose 37 percent year over year.", ""
            )

        with patch.object(alpha_radar, "fetch_source", side_effect=direct), patch.object(
            alpha_radar.subprocess, "run", side_effect=fallback
        ):
            pages = alpha_radar.gather_evidence(["https://walled.example/a"])

        self.assertEqual(calls, ["direct", "direct", "fallback"])
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["url"], "https://walled.example/a")
        self.assertIn("37 percent", pages[0]["text"])

    def test_businesswire_forbidden_skips_direct_retry_and_uses_gateway(self):
        calls=[]
        def direct(url,_timeout):
            calls.append("direct")
            raise urllib.error.HTTPError(url,403,"forbidden",{},None)
        def gateway(url,timeout_seconds=60):
            calls.append("gateway")
            return {"url":url,"title":"Wire","text":"usable wire evidence","published_at":"2026-09-08T15:00:00Z"}
        with patch.object(alpha_radar,"fetch_source",side_effect=direct), patch.object(
            alpha_radar,"fetch_source_via_gateway",side_effect=gateway
        ):
            pages=alpha_radar.gather_evidence(["https://www.businesswire.com/news/home/1/en/Test"])
        self.assertEqual(calls,["direct","gateway"])
        self.assertEqual([page["title"] for page in pages],["Wire"])

    def test_gateway_fallback_failure_keeps_typed_timeout(self):
        diagnostics = []

        def direct(url, _timeout):
            raise TimeoutError("read timed out")

        with patch.object(alpha_radar, "fetch_source", side_effect=direct), patch.object(
            alpha_radar.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=30)
        ):
            pages = alpha_radar.gather_evidence(
                ["https://walled.example/a"], diagnostics=diagnostics
            )

        self.assertEqual(pages, [])
        self.assertEqual(diagnostics, [{"url":"https://walled.example/a","domain": "walled.example", "reason": "source_fetch_timeout"}])

    def test_gateway_fallback_only_invoked_for_failures_not_successes(self):
        def direct(url, _timeout):
            return {"url": url, "title": "Direct", "text": "fine", "published_at": "2026-09-08T15:00:00Z"}

        with patch.object(alpha_radar, "fetch_source", side_effect=direct), patch.object(
            alpha_radar.subprocess, "run"
        ) as boot:
            pages = alpha_radar.gather_evidence(["https://ok.example/a"])

        boot.assert_not_called()
        self.assertEqual([page["title"] for page in pages], ["Direct"])

    def test_gateway_fallback_output_is_empty_is_not_evidence(self):
        def direct(url, _timeout):
            raise TimeoutError("read timed out")

        with patch.object(alpha_radar, "fetch_source", side_effect=direct), patch.object(
            alpha_radar.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "   ", ""),
        ):
            pages = alpha_radar.gather_evidence(["https://walled.example/a"])

        self.assertEqual(pages, [])

    def test_gateway_fallback_has_bounded_timeout(self):
        captured = {}

        def direct(url, _timeout):
            raise TimeoutError("read timed out")

        def fallback(cmd, input=None, capture_output=None, text=None, timeout=None, cwd=None):
            captured["timeout"] = timeout
            return subprocess.CompletedProcess(cmd, 0, "body", "")

        with patch.object(alpha_radar, "fetch_source", side_effect=direct), patch.object(
            alpha_radar.subprocess, "run", side_effect=fallback
        ):
            alpha_radar.gather_evidence(["https://walled.example/a"])

        self.assertIsNotNone(captured.get("timeout"))
        self.assertLessEqual(captured["timeout"], 60)


if __name__ == "__main__":
    unittest.main()
