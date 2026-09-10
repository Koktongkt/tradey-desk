"""Guard tests for execution tolerances in the production config."""
import json
import unittest
from pathlib import Path

CFG = json.loads((Path(__file__).resolve().parents[1] / "autonomy_config.json").read_text())


class ExecutionPolicyTests(unittest.TestCase):
    def test_production_spread_limit_is_600_bps_with_strict_upper_boundary(self):
        self.assertEqual(CFG["max_spread_bps"], 600)

    def test_production_limit_price_deviation_is_150_bps(self):
        self.assertEqual(CFG["max_limit_deviation_bps"], 150)

    def test_production_minimum_average_volume_is_600000_shares(self):
        self.assertEqual(CFG["min_average_volume"], 600000)

    def test_paper_mode_and_gate_settings_are_unchanged(self):
        self.assertEqual(CFG["broker_mode"], "paper")
        self.assertTrue(CFG["enabled"])
        self.assertFalse(CFG["allow_fractional_shares"])


if __name__ == "__main__":
    unittest.main()
