import hashlib
import io
import json
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autotrader
import managed_reconciliation


def _candidate_hash(root, symbol="AAPL"):
    candidate = {"symbol": symbol, "price": 100.0, "spy_price": 400.0, "researched_at": "2026-09-16T10:00:00Z"}
    body = {k: v for k, v in candidate.items() if k != "dossier_hash"}
    candidate["dossier_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (root / "candidates.jsonl").write_text(json.dumps(candidate) + "\n")
    return candidate


class NarrowRetrySemanticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reviews = self.root / "private" / "reviews.jsonl"
        self.reviews.parent.mkdir(parents=True)
        self.candidate = _candidate_hash(self.root)
        self.h = self.candidate["dossier_hash"]

    def write_reviews(self, rows):
        self.reviews.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def blocked(self):
        return {"timestamp": "2026-09-16T11:00:00Z", "dossier_hash": self.h,
                "reviews": [{"decision": "reconciliation_blocked"}]}

    def completed(self, decision="HOLD"):
        return {"timestamp": "2026-09-16T12:00:00Z", "dossier_hash": self.h,
                "reviews": [{"decision": decision}, {"decision": decision}]}

    def test_latest_row_governs_retry(self):
        for rows, expected in (
            ([], False),
            ([self.completed()], True),
            ([self.completed(), self.blocked()], False),
            ([self.blocked(), self.completed()], True),
            ([self.blocked()], False),
            ([{"timestamp": "t", "dossier_hash": self.h, "reviews": [None, None]}], False),
        ):
            with self.subTest(rows=len(rows), expected=expected):
                self.write_reviews(rows)
                self.assertEqual(autotrader.dossier_already_reviewed(self.candidate, self.reviews), expected)

    def test_block_row_mixed_with_real_decisions_still_counts_completed(self):
        self.write_reviews([{"timestamp": "t", "dossier_hash": self.h,
                             "reviews": [{"decision": "reconciliation_blocked"}, {"decision": "HOLD"}]}])
        self.assertTrue(autotrader.dossier_already_reviewed(self.candidate, self.reviews))

    def test_note_reconciliation_blocked_writes_narrow_row(self):
        with patch.object(autotrader, "ROOT", self.root):
            autotrader.note_reconciliation_blocked(self.reviews)
        rows = [json.loads(line) for line in self.reviews.read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dossier_hash"], self.h)
        self.assertEqual([r["decision"] for r in rows[0]["reviews"]], ["reconciliation_blocked"])
        self.assertFalse(autotrader.dossier_already_reviewed(self.candidate, self.reviews))


class ExactQuantityExposureTests(unittest.TestCase):
    def test_journal_net_must_match_broker_quantity_exactly(self):
        journal = [{"symbol": "ZS", "action": "BUY", "quantity": 3, "status": "filled"}]
        exposure, errors = autotrader.managed_exposure(
            [{"symbol": "ZS", "qty": "3", "market_value": "553.32"}], journal)
        self.assertEqual((exposure, errors), (553.32, []))
        for positions in (
            [{"symbol": "ZS", "qty": "2", "market_value": "368.88"}],
            [{"symbol": "ZS", "market_value": "553.32"}],
            [],
        ):
            with self.subTest(positions=positions):
                exposure, errors = autotrader.managed_exposure(positions, journal)
                self.assertIn("managed_position_reconciliation_failed", errors)
                self.assertEqual(exposure, 0.0)

    def test_baseline_symbols_are_separate_from_managed_net(self):
        journal = [{"symbol": "AAPL", "action": "BUY", "quantity": 3, "status": "filled"}]
        exposure, errors = autotrader.managed_exposure(
            [{"symbol": "AAPL", "qty": "3", "market_value": "600"}, {"symbol": "OLD", "qty": "9", "market_value": "900"}],
            journal)
        self.assertEqual(errors, [])


class RunIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "autonomy_config.json").write_text(json.dumps({
            "min_approval_confidence": 0.6, "min_reward_risk": 1.5, "max_position_usd": 500,
            "max_research_age_minutes": 60, "level_tolerance_pct": 1.0, "max_daily_orders": 3,
            "research_model": {"provider": "x", "model": "y"}, "review_model": {"provider": "x", "model": "z"},
        }))
        (self.root / "private").mkdir()
        self.candidate = _candidate_hash(self.root)
        self.reviews = self.root / "private" / "reviews.jsonl"

    def ns(self):
        return autotrader.argparse.Namespace(dry_run_fixture=False, live_dry_run=False)

    def execute(self, patches):
        captured = io.StringIO()
        with patch.object(autotrader, "ROOT", self.root), patch(
            "autotrader.runtime_blockers", return_value=[]
        ), contextlib.redirect_stdout(captured):
            code = autotrader.run(self.ns())
        return code, captured.getvalue()

    def test_reconciliation_blocker_stops_cycle_and_allows_narrow_retry(self):
        self.reviews.write_text(json.dumps({
            "timestamp": "t", "dossier_hash": self.candidate["dossier_hash"],
            "reviews": [{"decision": "HOLD"}, {"decision": "HOLD"}]}) + "\n")
        with patch("autotrader.reconcile_pending_orders", return_value=[]), patch(
            "autotrader.reconcile_managed_exits", return_value=[]
        ), patch("autotrader.reconcile_managed_protection",
                 side_effect=managed_reconciliation.ReconciliationBlocked("managed_position_reconciliation_failed")), patch(
            "autotrader._broker_bridge", side_effect=AssertionError("must not reach snapshot")
        ):
            code, out = self.execute(patches=None)
        self.assertEqual(code, 2)
        self.assertIn("BLOCKER managed_reconciliation:managed_position_reconciliation_failed", out)
        rows = [json.loads(line) for line in self.reviews.read_text().splitlines()]
        self.assertEqual(rows[-1]["reviews"][0]["decision"], "reconciliation_blocked")
        self.assertFalse(autotrader.dossier_already_reviewed(self.candidate, self.reviews))

    def test_recovered_replacement_exit_is_reported_and_cycle_ends(self):
        update = {"quantity": 3, "symbol": "ZS", "entry": 184.44}
        with patch("autotrader.reconcile_pending_orders", return_value=[]), patch(
            "autotrader.reconcile_managed_exits", return_value=[]
        ), patch("autotrader.reconcile_managed_protection", return_value=[update]), patch(
            "autotrader._broker_bridge", side_effect=AssertionError("must not reach snapshot")
        ):
            code, out = self.execute(patches=None)
        self.assertEqual(code, 0)
        self.assertIn("TRADE SELL 3 ZS @ 184.44", out)

    def test_shared_reconciliation_runs_after_bracket_reconciliation(self):
        calls = []
        with patch("autotrader.reconcile_pending_orders", return_value=[]), patch(
            "autotrader.reconcile_managed_exits",
            side_effect=lambda *a: (calls.append("bracket"), [])[1],
        ), patch(
            "autotrader.reconcile_managed_protection",
            side_effect=lambda *a: (calls.append("shared"), [])[1],
        ), patch(
            "autotrader._broker_bridge", side_effect=AssertionError("must not reach snapshot")
        ):
            code, out = self.execute(patches=None)
        self.assertEqual(calls, ["bracket", "shared"])


if __name__ == "__main__":
    unittest.main()
