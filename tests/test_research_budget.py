"""Guard tests pinning research subprocess timeouts and the outer cycle budget.

Timeouts must be calibrated against OBSERVED provider latency (a measured scout
run took 88.0s against a 90s cap), and the outer cycle budget must cover the
serialized worst case of every research stage:

    scout 120 + fetch ~20 + synthesis 120 + source verification 60 + margin
"""
import unittest
from unittest.mock import patch

import alpha_radar


class ResearchBudgetGuardTests(unittest.TestCase):
    def test_scout_timeout_leaves_margin_over_observed_latency(self):
        source = (alpha_radar.ROOT / "alpha_radar.py").read_text()
        self.assertIn("timeout=120", source)
        self.assertNotIn("timeout=90", source)

    def test_cycle_budget_covers_serialized_worst_case(self):
        # scout 120 + gather ~20 + synthesis 120 + verify_sources 60 + margin 40
        source = (alpha_radar.ROOT / "run_cycle.py").read_text()
        self.assertIn("timeout_seconds=360", source)
        self.assertNotIn("timeout_seconds=200", source)


class ScoutReliabilityGuardTests(unittest.TestCase):
    """Guard tests from the 2026-09-09 3-run fetch-failure streak.

    Causes addressed: scout URL hallucination (ir.ionq.com NXDOMAIN),
    intermittent source timeouts (businesswire.com), and a too-thin URL
    surplus (5 candidates minus dedupe/walls/staleness left <2 usable).
    """

    def test_scout_prompt_forbids_unverified_url_construction(self):
        self.assertIn("Return only URLs you actually retrieved", alpha_radar.SCOUT_PROMPT)
        self.assertIn("never construct or guess", alpha_radar.SCOUT_PROMPT)

    def test_scout_returns_up_to_seven_candidate_urls(self):
        self.assertIn("Return ONLY 4-7 plain http(s) URLs", alpha_radar.SCOUT_PROMPT)

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

        with patch.object(alpha_radar, "fetch_source", side_effect=fetch):
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

        with patch.object(alpha_radar, "fetch_source", side_effect=fetch):
            pages = alpha_radar.gather_evidence(["https://bad.example/a"])

        self.assertEqual(attempts["n"], 1)
        self.assertEqual(pages, [])


if __name__ == "__main__":
    unittest.main()
