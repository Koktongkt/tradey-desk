"""Guard tests pinning research subprocess timeouts, the outer cycle budget,
and scout-reliability hardening.

Timeouts must be calibrated against OBSERVED provider latency, and the outer cycle
budget must cover the serialized worst case of every research stage:

    model scout 360 + deterministic fetch/fallback 110 + synthesis 120
    + deterministic SEC lookup 45 + 85-second outer margin
"""
import json
import subprocess
import unittest
from unittest.mock import patch

import alpha_radar
import earnings_calendar


class ResearchBudgetGuardTests(unittest.TestCase):
    def test_scout_timeout_covers_two_search_and_two_extract_calls(self):
        source = (alpha_radar.ROOT / "alpha_radar.py").read_text()
        self.assertIn("input=SCOUT_PROMPT,capture_output=True,text=True,timeout=360", source)
        self.assertNotIn("input=SCOUT_PROMPT,capture_output=True,text=True,timeout=240", source)
        # synthesis timeout is unchanged
        self.assertIn("timeout=120,cwd=ROOT", source)

    def test_scout_run_budget_allows_both_tool_turns(self):
        command = alpha_radar.discovery_command()
        budget_index = command.index("--run-budget") + 1
        self.assertEqual(command[budget_index], "180")

    def test_cycle_budget_covers_serialized_worst_case(self):
        # 360 + 110 + 120 + SEC 45 = 635; outer 720 leaves 85 seconds.
        self.assertEqual(earnings_calendar.SEC_LOOKUP_BUDGET_SECONDS,45)
        source = (alpha_radar.ROOT / "run_cycle.py").read_text()
        self.assertIn(
            'if a.mode in {"premarket","radar"}:rc=execute([sys.executable,str(ROOT/"alpha_radar.py")],timeout_seconds=720',
            source,
        )
        self.assertNotIn(
            'if a.mode in {"premarket","radar"}:rc=execute([sys.executable,str(ROOT/"alpha_radar.py")],timeout_seconds=660',
            source,
        )


class ScoutReliabilityGuardTests(unittest.TestCase):
    """Guard tests from the 2026-09-09 3-run fetch-failure streak.

    Causes addressed: scout URL hallucination (ir.ionq.com NXDOMAIN),
    intermittent source timeouts (businesswire.com), and a too-thin URL
    surplus (5 candidates minus dedupe/walls/staleness left <2 usable).
    """

    def test_scout_prompt_forbids_unverified_url_construction(self):
        self.assertIn("Return only URLs you actually retrieved", alpha_radar.SCOUT_PROMPT)
        self.assertIn("never construct or guess", alpha_radar.SCOUT_PROMPT)

    def test_scout_returns_verified_urls_for_one_selected_setup(self):
        self.assertIn("Return ONLY 2-7 plain http(s) URLs", alpha_radar.SCOUT_PROMPT)

    def test_scout_uses_both_search_calls_in_first_tool_turn(self):
        self.assertIn(
            "first tool-using turn, call web_search exactly twice in parallel",
            alpha_radar.SCOUT_PROMPT,
        )

    def test_scout_uses_both_extract_calls_in_second_tool_turn(self):
        self.assertIn(
            "second tool-using turn, call web_extract exactly twice in parallel",
            alpha_radar.SCOUT_PROMPT,
        )
        self.assertIn(
            "five URLs in the first web_extract call and two in the second",
            alpha_radar.SCOUT_PROMPT,
        )
        self.assertIn(
            "seven different registered domains",
            alpha_radar.SCOUT_PROMPT,
        )
        self.assertIn(
            "across up to three candidate companies",
            alpha_radar.SCOUT_PROMPT,
        )

    def test_live_research_requests_seven_candidate_urls(self):
        source = (alpha_radar.ROOT / "alpha_radar.py").read_text()
        self.assertIn("extract_candidate_urls(scout.stdout,limit=7)", source)

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
            [{"domain": "down.example", "reason": "source_fetch_timeout"}],
        )

    def test_gather_evidence_does_not_retry_non_timeout_failures(self):
        attempts = {"n": 0}

        def fetch(url, _timeout):
            attempts["n"] += 1
            raise ConnectionResetError("reset")

        with patch.object(alpha_radar, "fetch_source", side_effect=fetch), patch.object(
            alpha_radar, "fetch_source_via_gateway", return_value=None
        ):
            pages = alpha_radar.gather_evidence(["https://bad.example/a"])

        self.assertEqual(attempts["n"], 1)
        self.assertEqual(pages, [])


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
        self.assertEqual(diagnostics, [{"domain": "walled.example", "reason": "source_fetch_timeout"}])

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
