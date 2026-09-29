"""Guard tests for execution tolerances in the production config."""
import json
import unittest
from pathlib import Path

CFG = json.loads((Path(__file__).resolve().parents[1] / "autonomy_config.json").read_text())


class ExecutionPolicyTests(unittest.TestCase):
    def test_production_volume_and_paper_gate_settings(self):
        self.assertEqual(CFG["min_average_volume"], 500000)
        self.assertEqual(CFG["broker_mode"], "paper")
        self.assertTrue(CFG["enabled"])
        self.assertFalse(CFG["allow_fractional_shares"])


if __name__ == "__main__":
    unittest.main()
