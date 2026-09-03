import json
import tempfile
import unittest
from pathlib import Path

import shadow_calibration


class ShadowCalibrationTests(unittest.TestCase):
    def test_shadow_decision_is_isolated_and_contains_exact_hypothetical_plan(self):
        candidate = {"candidate_id": "cand-1", "symbol": "AAPL", "spy_price": 500.0, "thesis": "private"}
        proposal = {
            "proposal_hash": "abc", "symbol": "AAPL", "limit_price": 100.0, "stop": 95.0,
            "target": 109.0, "quantity": 5, "assigned_rubric": "short_1_5", "holding_sessions": 4,
            "level_method": "atr_momentum",
        }
        aggregate = {"approved": True, "reviewer_confidences": [0.8, 0.6], "order": {"confidence": 0.6}}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test_artifacts" / "shadow" / "decisions.jsonl"
            operational = Path(td) / "order_ledger.jsonl"
            row = shadow_calibration.record_decision(path, candidate, proposal, aggregate, "2026-09-03T14:00:00Z")
            self.assertFalse(operational.exists())
            self.assertEqual(json.loads(path.read_text()), row)
        self.assertEqual(row["shadow_id"], "cand-1:abc")
        self.assertEqual(row["entry_price"], 100.0)
        self.assertEqual(row["reviewer_confidences"], [0.8, 0.6])
        self.assertEqual(row["conviction"], 0.6)
        self.assertTrue(row["would_trade"])
        self.assertNotIn("thesis", row)

    def test_calibration_report_compares_thresholds_and_spy(self):
        decisions = [
            {"shadow_id": "a", "conviction": 0.50},
            {"shadow_id": "b", "conviction": 0.70},
            {"shadow_id": "c", "conviction": None},
        ]
        outcomes = [
            {"shadow_id": "a", "excess_5s_pct": -1.0},
            {"shadow_id": "b", "excess_5s_pct": 3.0},
            {"shadow_id": "c", "excess_5s_pct": 10.0},
        ]
        report = shadow_calibration.calibration_report(decisions, outcomes, thresholds=(0.50, 0.60))
        self.assertEqual(report["thresholds"]["0.50"]["5s"], {"sample": 2, "avg_excess_pct": 1.0})
        self.assertEqual(report["thresholds"]["0.60"]["5s"], {"sample": 1, "avg_excess_pct": 3.0})

    def test_refresh_builds_broker_payload_from_shadow_decisions(self):
        decision = {
            "shadow_id": "a", "candidate_id": "cand-1", "symbol": "AAPL",
            "decision_at": "2026-09-03T14:00:00Z", "entry_price": 100.0,
            "spy_entry": 500.0, "would_trade": False, "conviction": 0.7,
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decisions_path = root / "decisions.jsonl"
            outcomes_path = root / "outcomes.jsonl"
            report_path = root / "report.json"
            decisions_path.write_text(json.dumps(decision) + "\n")
            payloads = []
            def broker(payload):
                payloads.append(payload)
                return [{
                    "candidate_id": "a", "symbol": "AAPL", "entry_price": 100.0, "spy_entry": 500.0,
                    "prices": {"5": 110.0}, "spy_prices": {"5": 500.0}, "traded": False,
                }]
            rc = shadow_calibration.refresh(decisions_path, outcomes_path, report_path, broker)
            self.assertEqual(rc, 0)
            self.assertEqual(payloads[0]["candidates"][0]["price"], 100.0)
            self.assertEqual(payloads[0]["candidates"][0]["candidate_id"], "a")
            report = json.loads(report_path.read_text())
            self.assertEqual(report["thresholds"]["0.70"]["5s"]["avg_excess_pct"], 10.0)

    def test_shadow_outcome_measurement_uses_canonical_entry_and_stays_isolated(self):
        decision = {
            "shadow_id": "a", "candidate_id": "cand-1", "symbol": "AAPL",
            "decision_at": "2026-09-03T14:00:00Z", "entry_price": 100.0,
            "spy_entry": 500.0, "would_trade": False,
        }
        broker_rows = [{
            "candidate_id": "a", "symbol": "AAPL", "entry_price": 100.0, "spy_entry": 500.0,
            "prices": {"5": 110.0}, "spy_prices": {"5": 525.0}, "traded": False,
        }]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "test_artifacts" / "shadow" / "outcomes.jsonl"
            rows = shadow_calibration.measure_outcomes([decision], broker_rows, output)
            self.assertFalse((root / "candidate_outcomes.jsonl").exists())
            self.assertEqual(rows[0]["shadow_id"], "a")
            self.assertEqual(rows[0]["return_5s_pct"], 10.0)
            self.assertEqual(rows[0]["spy_return_5s_pct"], 5.0)
            self.assertEqual(rows[0]["excess_5s_pct"], 5.0)
            self.assertEqual(json.loads(output.read_text())["shadow_id"], "a")


if __name__ == "__main__":
    unittest.main()
