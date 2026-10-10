import hashlib
import io
import json
import contextlib
import copy
import datetime as dt

from support_fixtures import broker_snapshot, policy_config
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

    def retry_marker(self, evidence_id="evidence-a"):
        return {"timestamp": "2026-09-16T12:01:00Z", "dossier_hash": self.h,
                "evidence_id": evidence_id, "reviews": [{"decision": "execution_retryable"}]}

    def retry_reviews(self, decision="APPROVE"):
        return [{**self.completed(decision), "evidence_id": "evidence-a"}, self.retry_marker()]

    def write_ledger(self, rows):
        (self.root / "order_ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def blocked(self):
        return {"timestamp": "2026-09-16T11:00:00Z", "dossier_hash": self.h,
                "reviews": [{"decision": "reconciliation_blocked"}]}

    def completed(self, decision="HOLD"):
        return {"timestamp": "2026-09-16T12:00:00Z", "dossier_hash": self.h,
                "reviews": [{"decision": decision}, {"decision": decision}]}

    def test_completed_review_survives_later_reconciliation_marker(self):
        for rows, expected in (
            ([], False),
            ([self.completed()], True),
            ([self.completed(), self.blocked()], True),
            ([self.blocked(), self.completed()], True),
            ([self.blocked()], False),
            ([{"timestamp": "t", "dossier_hash": self.h, "reviews": [None, None]}], False),
        ):
            with self.subTest(rows=len(rows), expected=expected):
                self.write_reviews(rows)
                self.assertEqual(autotrader.dossier_already_reviewed(self.candidate, self.reviews), expected)

    def test_pre_submission_block_after_approval_allows_retry(self):
        self.write_reviews(self.retry_reviews())
        self.write_ledger([{"evidence_id": "evidence-a", "status": "rejected", "reason": ["spread_too_wide"]}])
        self.assertFalse(autotrader.dossier_already_reviewed(self.candidate, self.reviews))

    def test_prior_hold_remains_spent_even_after_later_approval_marker(self):
        self.write_reviews([
            {**self.completed("HOLD"), "evidence_id": "old"},
            self.blocked(),
            {**self.completed("APPROVE"), "evidence_id": "evidence-a"},
            self.retry_marker(),
        ])
        self.write_ledger([{"evidence_id": "evidence-a", "status": "rejected", "reason": ["spread_too_wide"]}])
        self.assertTrue(autotrader.dossier_already_reviewed(self.candidate, self.reviews))

    def test_disagreement_reason_cannot_authorize_execution_retry(self):
        self.write_reviews(self.retry_reviews())
        self.write_ledger([{"evidence_id": "evidence-a", "status": "rejected", "reason": "model_disagreement"}])
        self.assertTrue(autotrader.dossier_already_reviewed(self.candidate, self.reviews))

    def test_fatal_flagged_approval_cannot_be_reenabled(self):
        self.write_reviews([
            {**self.completed("APPROVE"), "evidence_id": "old", "reviews": [
                {"decision": "APPROVE", "fatal_flags": ["risk"]},
                {"decision": "APPROVE", "fatal_flags": []}]},
            self.blocked(),
            {**self.completed("APPROVE"), "evidence_id": "evidence-a"},
            self.retry_marker(),
        ])
        self.write_ledger([{"evidence_id": "evidence-a", "status": "rejected", "reason": ["spread_too_wide"]}])
        self.assertTrue(autotrader.dossier_already_reviewed(self.candidate, self.reviews))

    def test_broker_failure_is_not_pre_submission_validation_proof(self):
        self.write_reviews(self.retry_reviews())
        self.write_ledger([{"evidence_id": "evidence-a", "status": "rejected", "reason": ["broker_mcp_failure"]}])
        self.assertTrue(autotrader.dossier_already_reviewed(self.candidate, self.reviews))

    def test_prior_low_confidence_approval_cannot_be_reenabled(self):
        self.write_reviews([
            {**self.completed("APPROVE"), "evidence_id": "old"},
            self.blocked(),
            {**self.completed("APPROVE"), "evidence_id": "evidence-a"},
            self.retry_marker(),
        ])
        self.write_ledger([
            {"evidence_id": "old", "status": "rejected", "reason": "low_confidence"},
            {"evidence_id": "evidence-a", "status": "rejected", "reason": ["spread_too_wide"]},
        ])
        self.assertTrue(autotrader.dossier_already_reviewed(self.candidate, self.reviews))

    def test_non_market_broker_blockers_do_not_authorize_reuse(self):
        self.write_reviews(self.retry_reviews())
        for reason in ("active_broker_order", "positions_unknown"):
            with self.subTest(reason=reason):
                self.write_ledger([{"evidence_id": "evidence-a", "status": "rejected", "reason": [reason]}])
                self.assertTrue(autotrader.dossier_already_reviewed(self.candidate, self.reviews))

    def test_retry_marker_without_proof_remains_spent(self):
        self.write_reviews(self.retry_reviews())
        self.assertTrue(autotrader.dossier_already_reviewed(self.candidate, self.reviews))

    def test_submitted_order_cannot_reuse_retry_marker(self):
        self.write_reviews(self.retry_reviews())
        for status in ("submission_started", "placed", "submission_unknown"):
            with self.subTest(status=status):
                self.write_ledger([
                    {"evidence_id": "evidence-a", "status": "rejected", "reason": ["spread_too_wide"]},
                    {"evidence_id": "evidence-a", "status": status},
                ])
                self.assertTrue(autotrader.dossier_already_reviewed(self.candidate, self.reviews))

    def test_hold_cannot_be_reenabled_by_retry_marker(self):
        self.write_reviews(self.retry_reviews(decision="HOLD"))
        self.write_ledger([{"evidence_id": "evidence-a", "status": "rejected", "reason": ["spread_too_wide"]}])
        self.assertTrue(autotrader.dossier_already_reviewed(self.candidate, self.reviews))

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

    def test_reconciliation_blocker_does_not_erase_completed_hold(self):
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
        self.assertTrue(autotrader.dossier_already_reviewed(self.candidate, self.reviews))

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


class PendingObservationContinuationTests(unittest.TestCase):
    """Real saved-intent reconciliation and deterministic entry gates, offline."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "private").mkdir()
        self.cfg = policy_config()
        self.cfg["broker_mode"] = "paper"
        (self.root / "autonomy_config.json").write_text(json.dumps(self.cfg))
        (self.root / "private/broker_baseline.json").write_text(
            json.dumps({"preexisting_symbols": []}))
        now = dt.datetime.now(dt.timezone.utc)
        self.now = now.isoformat()
        self.candidate = {
            "symbol": "DELL", "instrument_type": "cash_equity",
            "researched_at": self.now, "sources_verified_at": self.now,
            "sources": [{"url": "https://a.example/1", "title": "A"},
                        {"url": "https://b.example/2", "title": "B"}],
            "setup_type": "breakout", "horizon_rationale": "short",
            "planned_exit_at": (now + dt.timedelta(days=3)).isoformat(),
            "earnings_event_at": (now + dt.timedelta(days=30)).isoformat(),
            "catalyst": "guidance raise", "thesis": "post-news drift",
        }
        self.candidate["dossier_hash"] = hashlib.sha256(json.dumps(
            self.candidate, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        # The last dossier, not the older pending symbol, must be evaluated.
        self.write_rows("candidates.jsonl", [_candidate_hash(self.root, "AAPL"), self.candidate])
        self.plan = {"action": "BUY", "symbol": "AAPL", "quantity": 2,
                     "order_type": "limit", "limit_price": 100, "stop": 95,
                     "target": 110, "horizon": "3 sessions", "confidence": 0.9,
                     "thesis": "saved intent"}
        self.snapshot = broker_snapshot(
            captured_at=self.now, quote={"bid": 99.98, "ask": 100.02, "timestamp": self.now},
            cash=10000, earnings_status="reported", earnings_sessions_away=30,
            trading_sessions=[(now.date() + dt.timedelta(days=i)).isoformat() for i in range(31)])
        self.calls = []

    def write_rows(self, name, rows):
        (self.root / name).write_text("".join(json.dumps(row) + "\n" for row in rows))

    def seed_pending(self, status="new"):
        self.write_rows("order_ledger.jsonl", [{"client_order_id": "pending-parent", "status": "placed"}])
        self.write_rows("private/order_intents.jsonl", [
            {"client_order_id": "pending-parent", "plan": self.plan}])
        self.order = {"client_order_id": "pending-parent", "symbol": "AAPL",
                      "side": "buy", "position_intent": "buy_to_open", "type": "limit",
                      "order_class": "bracket", "time_in_force": "gtc", "qty": "2",
                      "limit_price": "100", "status": status,
                      "filled_qty": "2" if status == "filled" else "1" if status == "partially_filled" else "0",
                      "filled_avg_price": "100" if status == "filled" else None,
                      "filled_at": self.now if status == "filled" else None,
                      "legs": []}
        for kind, price in (("stop", "95"), ("limit", "110")):
            self.order["legs"].append({
                "client_order_id": "pending-" + kind, "symbol": "AAPL", "side": "sell",
                "position_intent": "sell_to_close", "order_class": "bracket", "type": kind,
                "time_in_force": "gtc", "qty": "2", "filled_qty": "0", "status": "held",
                "stop_price" if kind == "stop" else "limit_price": price})
        self.snapshot["positions"] = ([{"symbol": "AAPL", "qty": "2", "market_value": "200"}]
                                      if status == "filled" else [])
        self.snapshot["open_orders"] = (copy.deepcopy(self.order["legs"]) if status == "filled"
                                        else [copy.deepcopy(self.order)])
        # A filled parent no longer blocks, so a real spread rejection keeps this
        # test tool-free while exercising the unchanged pre-review validator.
        if status == "filled":
            self.snapshot["quote"]["bid"] = 80

    def bridge(self, operation, payload=None):
        self.calls.append((operation, payload))
        if operation == "reconcile":
            self.assertEqual(payload, {"client_order_id": "pending-parent"})
            return copy.deepcopy(self.order)
        if operation == "reconcile_many":
            return {"orders": [copy.deepcopy(self.order)]}
        if operation == "reconciliation_snapshot":
            return {**copy.deepcopy(self.snapshot), "orders": [copy.deepcopy(self.order)]}
        if operation == "snapshot":
            self.assertEqual(payload["symbol"], "DELL")
            return copy.deepcopy(self.snapshot)
        raise AssertionError("unexpected broker authority: " + operation)

    def execute(self):
        out = io.StringIO()
        with patch.object(autotrader, "ROOT", self.root), patch(
            "autotrader.runtime_blockers", return_value=[]
        ), patch("autotrader._broker_bridge", side_effect=self.bridge), patch(
            "autotrader.reconcile_managed_exits", wraps=autotrader.reconcile_managed_exits
        ) as exits, patch(
            "autotrader.reconcile_managed_protection", wraps=autotrader.reconcile_managed_protection
        ) as protection, patch(
            "autotrader.pre_review_validation", wraps=autotrader.pre_review_validation
        ) as precheck, patch(
            "autotrader.independent_reviews", side_effect=AssertionError("must not review")
        ) as reviewers, contextlib.redirect_stdout(out):
            code = autotrader.run(autotrader.argparse.Namespace(dry_run_fixture=False, live_dry_run=False))
        reviewers.assert_not_called()
        self.assertFalse(any(op in {"place", "review", "cancel"} for op, _ in self.calls))
        return code, out.getvalue(), exits, protection, precheck

    def test_valid_pending_observations_reach_fresh_candidate_and_real_precheck(self):
        for status in ("new", "accepted", "pending_new", "held", "filled"):
            with self.subTest(status=status):
                self.setUp()  # Fresh storage root; JSONL projections must not rewrite prior SQLite history.
                self.seed_pending(status)
                code, out, exits, protection, precheck = self.execute()
                self.assertEqual(code, 2, out)
                exits.assert_called_once()
                protection.assert_called_once()
                precheck.assert_called_once()
                self.assertEqual(precheck.call_args.args[0]["symbol"], "DELL")
                expected = "spread_too_wide" if status == "filled" else "active_broker_order"
                self.assertIn(expected, out)
                rows = autotrader.read_jsonl(self.root / "trade_journal.jsonl")
                self.assertEqual(len(rows), int(status == "filled"))
                if rows:
                    self.assertEqual((rows[0]["symbol"], rows[0]["quantity"], rows[0]["entry"]),
                                     ("AAPL", 2, 100))

    def test_partial_fill_observation_reaches_existing_fail_closed_protection_gate(self):
        self.seed_pending("partially_filled")
        code, out, exits, protection, precheck = self.execute()
        self.assertEqual(code, 2)
        self.assertIn("managed_pending_entry_not_unfilled", out)
        exits.assert_called_once()
        protection.assert_called_once()
        precheck.assert_not_called()
        self.assertEqual(autotrader.read_jsonl(self.root / "trade_journal.jsonl"), [])

    def test_malformed_or_inconsistent_readback_stops_before_managed_checks(self):
        for field, value in (("client_order_id", "wrong"), ("symbol", "MSFT"),
                             ("side", "sell"), ("qty", "3"), ("qty", "NaN"),
                             ("order_class", "simple"), ("type", "market"),
                             ("status", "unknown")):
            with self.subTest(field=field, value=value):
                self.setUp()
                self.seed_pending()
                self.order[field] = value
                code, out, exits, protection, precheck = self.execute()
                self.assertEqual(code, 4)
                self.assertIn("pending_order_reconciliation", out)
                exits.assert_not_called()
                protection.assert_not_called()
                precheck.assert_not_called()
                self.assertEqual(autotrader.read_jsonl(self.root / "order_ledger.jsonl")[-1]["status"], "placed")

    def test_invalid_update_from_pending_seam_retains_exact_second_readback_check(self):
        self.seed_pending()
        with patch("autotrader.reconcile_pending_orders", return_value=[{
            "client_order_id": "wrong", "_plan": self.plan, "_broker_order": self.order}]):
            code, out, exits, protection, precheck = self.execute()
        self.assertEqual(code, 4)
        self.assertIn("broker_reconciliation_invalid", out)
        exits.assert_not_called()
        protection.assert_not_called()
        precheck.assert_not_called()

    def test_managed_protection_failure_after_pending_stops_before_candidate(self):
        self.seed_pending()
        self.snapshot["open_orders"] = []
        code, out, exits, protection, precheck = self.execute()
        self.assertEqual(code, 2)
        self.assertIn("managed_pending_entry_missing", out)
        exits.assert_called_once()
        protection.assert_called_once()
        precheck.assert_not_called()
        self.assertFalse(any(op == "snapshot" for op, _ in self.calls))

    def test_managed_exit_failure_after_pending_remains_system_failure(self):
        self.seed_pending("filled")
        self.order["legs"] = []
        code, out, exits, protection, precheck = self.execute()
        self.assertEqual(code, 4)
        self.assertIn("managed_exit_reconciliation", out)
        exits.assert_called_once()
        protection.assert_not_called()
        precheck.assert_not_called()

    def test_managed_bridge_exception_after_pending_remains_system_failure(self):
        self.seed_pending()
        real_bridge = self.bridge
        def failing_bridge(operation, payload=None):
            if operation == "reconciliation_snapshot":
                raise RuntimeError("offline read failure")
            return real_bridge(operation, payload)
        self.bridge = failing_bridge
        code, out, exits, protection, precheck = self.execute()
        self.assertEqual(code, 4)
        self.assertIn("SYSTEM_FAILURE managed_reconciliation", out)
        protection.assert_called_once()
        precheck.assert_not_called()

    def test_already_reviewed_latest_dossier_stays_skipped_after_pending(self):
        self.seed_pending()
        self.write_rows("private/reviews.jsonl", [{
            "dossier_hash": self.candidate["dossier_hash"], "reviews": [{"decision": "HOLD"}]}])
        code, out, exits, protection, precheck = self.execute()
        self.assertEqual(code, 0)
        self.assertIn("DECISION skipped already_reviewed", out)
        exits.assert_called_once()
        protection.assert_called_once()
        precheck.assert_not_called()
        self.assertFalse(any(op == "snapshot" for op, _ in self.calls))


if __name__ == "__main__":
    unittest.main()
