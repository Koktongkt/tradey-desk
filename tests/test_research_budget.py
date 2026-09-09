"""Guard tests pinning research subprocess timeouts and the outer cycle budget.

Timeouts must be calibrated against OBSERVED provider latency (a measured scout
run took 88.0s against a 90s cap), and the outer cycle budget must cover the
serialized worst case of every research stage:

    scout 120 + fetch ~20 + synthesis 120 + source verification 60 + margin
"""
import unittest

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


if __name__ == "__main__":
    unittest.main()
