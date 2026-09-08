"""Blocker-diagnostics tests.

Every deterministic rejection must persist a private structured diagnostics
row (timestamp, stage, symbol, action, reason, measured values, configured
threshold) under private/blocker_diagnostics.jsonl for real paper cycles and
test_artifacts/ for dry runs, so questions like "how wide was the spread"
are answerable without exposing sanitized public output. The public
dashboard gains a sanitized projection of those rows (no ids, no paths).
"""
import contextlib
import datetime as dt
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autotrader


def _cfg():
    cfg = json.loads(Path("/opt/data/tradey-desk/autonomy_config.json").read_text())
    cfg["min_price_usd"] = 10
    return cfg


def _bars():
    return [
        {"open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i,
         "volume": 1_000_000 + i, "timestamp": 1700000000 + i * 86400}
        for i in range(25)
    ]


def _quote(bid=99.98, ask=100.02):
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    return {"bid": bid, "ask": ask, "timestamp": now}


def _snapshot(quote=None, cash=10000.0):
    now = dt.datetime.now(dt.timezone.utc)
    return {
        "captured_at": now.isoformat().replace("+00:00", "Z"),
        "buying_power": 10000.0,
        "cash": cash,
        "positions": [],
        "open_orders": [],
        "asset": {"symbol": "DELL", "tradable": True, "class": "us_equity",
                  "exchange": "NASDAQ", "name": "Dell Technologies Inc.",
                  "fractionable": True, "leveraged": False, "inverse": False},
        "quote": quote or _quote(),
        "quote_feed": "alpaca_iex",
        "average_volume": 5_000_000.0,
        "volume_feed": "massive_consolidated",
        "technical_bars": _bars(),
        "technical_bars_feed": "massive_consolidated_completed_daily",
        "earnings_status": "upcoming",
        "earnings_sessions_away": 9,
        "trading_sessions": [(now.date() + dt.timedelta(days=i)).isoformat() for i in range(31)],
    }


def _order():
    return {
        "action": "BUY", "symbol": "DELL", "quantity": 5, "order_type": "limit",
        "limit_price": 100.02, "stop": 95.0, "target": 108.0, "confidence": 0.9,
        "horizon": "3 sessions",
    }


class ValidateOrderDetailsTests(unittest.TestCase):
    def test_errors_identical_between_plain_and_details_variants(self):
        snap = _snapshot(quote=_quote(99.0, 104.0))  # wide spread
        errors = autotrader.validate_order(_order(), snap, _cfg(), 0, 0.0, set())
        errors2, details = autotrader.validate_order_with_details(_order(), snap, _cfg(), 0, 0.0, set())
        self.assertEqual(errors, errors2)
        self.assertTrue(errors)

    def test_spread_too_wide_records_measured_and_threshold(self):
        snap = _snapshot(quote=_quote(99.0, 104.0))
        _, details = autotrader.validate_order_with_details(_order(), snap, _cfg(), 0, 0.0, set())
        d = details["spread_too_wide"]
        self.assertEqual(d["bid"], 99.0)
        self.assertEqual(d["ask"], 104.0)
        self.assertAlmostEqual(d["midpoint"], 101.5)
        self.assertAlmostEqual(d["spread_bps"], (104.0 - 99.0) / 101.5 * 10000, places=4)
        self.assertEqual(d["max_spread_bps"], 250)
        self.assertEqual(d["quote_feed"], "alpaca_iex")

    def test_limit_deviation_records_reference_and_threshold(self):
        snap = _snapshot()
        order = _order()
        order["limit_price"] = 100.02 + 3.0  # BUY measured against ask
        errors, details = autotrader.validate_order_with_details(order, snap, _cfg(), 0, 0.0, set())
        self.assertIn("limit_price_too_far_from_quote", errors)
        d = details["limit_price_too_far_from_quote"]
        self.assertEqual(d["limit_price"], 103.02)
        self.assertEqual(d["reference_price"], 100.02)
        self.assertEqual(d["reference_side"], "ask")
        self.assertAlmostEqual(d["deviation_bps"], 3.0 / 100.02 * 10000, places=4)
        self.assertEqual(d["max_limit_deviation_bps"], 150)

    def test_weak_reward_to_risk_records_ratio_and_threshold(self):
        order = _order()
        order["target"] = 100.5
        errors, details = autotrader.validate_order_with_details(order, _snapshot(), _cfg(), 0, 0.0, set())
        self.assertIn("weak_reward_to_risk", errors)
        d = details["weak_reward_to_risk"]
        self.assertAlmostEqual(d["risk_reward"], (100.5 - 100.02) / (100.02 - 95.0), places=6)
        self.assertEqual(d["min_reward_risk"], 1.6)

    def test_near_term_earnings_records_state_and_blackout(self):
        snap = _snapshot()
        snap["earnings_sessions_away"] = 1
        errors, details = autotrader.validate_order_with_details(_order(), snap, _cfg(), 0, 0.0, set())
        self.assertIn("near_term_earnings", errors)
        d = details["near_term_earnings"]
        self.assertEqual(d["earnings_status"], "upcoming")
        self.assertEqual(d["earnings_sessions_away"], 1)
        self.assertEqual(d["earnings_blackout_sessions"], 2)

    def test_insufficient_cash_records_basis_and_cash(self):
        errors, details = autotrader.validate_order_with_details(
            _order(), _snapshot(cash=10.0), _cfg(), 0, 0.0, set())
        self.assertIn("insufficient_cash", errors)
        d = details["insufficient_cash"]
        self.assertEqual(d["cash"], 10.0)
        self.assertAlmostEqual(d["dollar_basis"], 100.02 * 5, places=2)

    def test_unknown_reasons_carry_context(self):
        snap = _snapshot(quote={})
        snap["quote_feed"] = "unknown_feed"
        errors, details = autotrader.validate_order_with_details(_order(), snap, _cfg(), 0, 0.0, set())
        self.assertIn("quote_feed_unavailable", errors)
        self.assertEqual(details["quote_feed_unavailable"]["quote_feed"], "unknown_feed")
        self.assertEqual(details["quote_feed_unavailable"]["allowed_quote_feeds"], ["alpaca_iex"])


def _candidate(root):
    now = dt.datetime.now(dt.timezone.utc)
    cand = {
        "symbol": "DELL",
        "researched_at": (now - dt.timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "sources_verified_at": (now - dt.timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
        "sources": [{"url": "https://a.example/1", "title": "A"}, {"url": "https://b.example/2", "title": "B"}],
        "price": 100.0, "spy_price": 500.0, "instrument_type": "cash_equity",
        "setup_type": "breakout",
        "earnings_event_at": (now + dt.timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "planned_exit_at": (now + dt.timedelta(days=3)).isoformat().replace("+00:00", "Z"),
        "horizon_rationale": "short",
        "catalyst": "guidance raise", "thesis": "post-news drift",
    }
    body = {k: v for k, v in cand.items() if k != "dossier_hash"}
    cand["dossier_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return cand


def _setup_root(root, snapshot, quote=None):
    (root / "autonomy_config.json").write_text(json.dumps(_cfg()))
    (root / "candidates.jsonl").write_text(json.dumps(_candidate(root)) + "\n")
    (root / "private").mkdir(exist_ok=True)


def _run_in_root(root, snapshot, live_dry_run=False, review_snapshot=None):
    calls = []
    def fake_bridge(op, payload=None):
        calls.append(op)
        if op == "snapshot":
            return snapshot
        if op == "review":
            return review_snapshot or snapshot
        raise AssertionError(f"unexpected bridge op {op}")
    with patch.object(autotrader, "ROOT", root), patch(
        "autotrader._broker_bridge", side_effect=fake_bridge
    ), patch("autotrader.load_baseline_symbols", return_value=set()):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = autotrader.run(autotrader.argparse.Namespace(
                dry_run_fixture=False, live_dry_run=live_dry_run))
    return code, out.getvalue(), calls


class RunPrecheckDiagnosticsTests(unittest.TestCase):
    def test_precheck_block_writes_private_diagnostics_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot(quote=_quote(99.0, 104.0))  # wide spread + earnings far enough
            _setup_root(root, snap)
            snap["earnings_sessions_away"] = 9
            code, out, _ = _run_in_root(root, snap)
            self.assertEqual(code, 2)
            self.assertIn("spread_too_wide", out)
            path = root / "private" / "blocker_diagnostics.jsonl"
            self.assertTrue(path.exists())
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            reasons = {row["reason"] for row in rows}
            self.assertIn("spread_too_wide", reasons)
            spread_row = next(r for r in rows if r["reason"] == "spread_too_wide")
            self.assertEqual(spread_row["stage"], "precheck")
            self.assertEqual(spread_row["symbol"], "DELL")
            self.assertEqual(spread_row["action"], "BUY")
            self.assertIn("timestamp", spread_row)
            self.assertEqual(spread_row["measured"]["spread_bps"], spread_row["measured"]["spread_bps"])
            self.assertGreater(spread_row["measured"]["spread_bps"], 0)
            self.assertEqual(spread_row["threshold"]["max_spread_bps"], 250)

    def test_one_row_per_reason(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot(quote=_quote(99.0, 104.0))
            snap["earnings_sessions_away"] = 1  # adds near_term_earnings blocker
            _setup_root(root, snap)
            code, out, _ = _run_in_root(root, snap)
            self.assertEqual(code, 2)
            rows = [json.loads(line) for line in (root / "private" / "blocker_diagnostics.jsonl").read_text().splitlines()]
            reasons = [row["reason"] for row in rows]
            self.assertIn("spread_too_wide", reasons)
            self.assertIn("near_term_earnings", reasons)
            self.assertEqual(len(reasons), len(set(reasons)))

    def test_broker_review_block_tagged_stage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            good = _snapshot()
            _setup_root(root, good)
            fresh = _snapshot(cash=1.0)  # cash evaporates between precheck and placement
            proposal, errors = autotrader.build_canonical_proposal(
                json.loads((root / "candidates.jsonl").read_text().splitlines()[0]),
                autotrader.authoritative_bundle({}, good, good["captured_at"])["broker_snapshot"],
                _cfg(), 0.0)
            self.assertEqual(errors, [])
            reviews = [
                {"proposal_hash": proposal["proposal_hash"], "decision": "APPROVE", "fatal_flags": [],
                 "reason_codes": [], "component_scores": {k: 5 for k in autotrader.RUBRIC_WEIGHTS["short_1_5"]}},
            ] * 2
            with patch("autotrader.independent_reviews", return_value=reviews), patch(
                "autotrader.record_shadow_decision"
            ):
                code, out, _ = _run_in_root(root, good, review_snapshot=fresh)
            self.assertEqual(code, 2)
            self.assertIn("insufficient_cash", out)
            rows = [json.loads(line) for line in (root / "private" / "blocker_diagnostics.jsonl").read_text().splitlines()]
            row = next(r for r in rows if r["reason"] == "insufficient_cash")
            self.assertEqual(row["stage"], "broker_review")

    def test_passing_cycle_writes_no_diagnostics(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot()
            _setup_root(root, snap)
            reviews = [
                {"proposal_hash": "MATCH", "decision": "APPROVE", "fatal_flags": [],
                 "reason_codes": [], "component_scores": {k: 4 for k in autotrader.RUBRIC_WEIGHTS["short_1_5"]}},
            ] * 2
            def fake_bridge(op, payload=None):
                if op == "snapshot":
                    return snap
                if op == "review":
                    return snap
                if op == "place":
                    return {"status": "filled", "filled_qty": 5, "filled_avg_price": 100.02}
                if op == "reconcile":
                    return {"status": "filled", "filled_qty": 5, "filled_avg_price": 100.02}
                raise AssertionError(op)
            with patch.object(autotrader, "ROOT", root), patch(
                "autotrader._broker_bridge", side_effect=fake_bridge
            ), patch("autotrader.load_baseline_symbols", return_value=set()), patch(
                "autotrader.independent_reviews", return_value=reviews
            ):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    # proposal hash must match reviews; build it the same way run does
                    proposal, errors = autotrader.build_canonical_proposal(
                        json.loads((root / "candidates.jsonl").read_text().splitlines()[0]),
                        autotrader.authoritative_bundle({}, snap, snap["captured_at"])["broker_snapshot"],
                        _cfg(), 0.0)
                    self.assertEqual(errors, [])
                    reviews[0]["proposal_hash"] = proposal["proposal_hash"]
                    reviews[1]["proposal_hash"] = proposal["proposal_hash"]
                    code = autotrader.run(autotrader.argparse.Namespace(
                        dry_run_fixture=False, live_dry_run=False))
            self.assertEqual(code, 0)
            self.assertFalse((root / "private" / "blocker_diagnostics.jsonl").exists())


class DryRunDiagnosticsTests(unittest.TestCase):
    def test_live_dry_run_routes_diagnostics_to_test_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot(quote=_quote(99.0, 104.0))
            _setup_root(root, snap)
            code, out, _ = _run_in_root(root, snap, live_dry_run=True)
            self.assertEqual(code, 2)
            self.assertIn("spread_too_wide", out)
            self.assertFalse((root / "private" / "blocker_diagnostics.jsonl").exists())
            path = root / "test_artifacts" / "blocker_diagnostics.jsonl"
            self.assertTrue(path.exists())
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertTrue(any(r["reason"] == "spread_too_wide" for r in rows))


class DashboardProjectionTests(unittest.TestCase):
    def test_dashboard_projects_sanitized_blocker_diagnostics(self):
        import public_dashboard
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "private").mkdir()
            (root / "private" / "blocker_diagnostics.jsonl").write_text(json.dumps({
                "timestamp": "2026-09-05T14:00:00Z", "stage": "precheck",
                "symbol": "DELL", "action": "BUY", "reason": "spread_too_wide",
                "measured": {"bid": 99.0, "ask": 104.0, "midpoint": 101.5, "spread_bps": 492.61, "quote_feed": "alpaca_iex"},
                "threshold": {"max_spread_bps": 250},
                "secret_field": "should-not-publish", "evidence_id": "abc123", "path": "/opt/data/secret",
            }) + "\n")
            data = public_dashboard.build_data(root)
        diag = data["blocker_diagnostics"]
        self.assertEqual(len(diag), 1)
        row = diag[0]
        self.assertEqual(row["reason"], "spread_too_wide")
        self.assertEqual(row["measured"]["spread_bps"], 492.61)
        self.assertEqual(row["threshold"]["max_spread_bps"], 250)
        for forbidden in ("secret_field", "evidence_id", "path"):
            self.assertNotIn(forbidden, row)
        self.assertIn("blocker_diagnostics", public_dashboard.ACTIVITY_SUMMARIES)
        self.assertTrue(public_dashboard.ACTIVITY_SUMMARIES["blocker_diagnostics"])

    def test_dashboard_tolerates_missing_diagnostics_file(self):
        import public_dashboard
        with tempfile.TemporaryDirectory() as td:
            data = public_dashboard.build_data(Path(td))
        self.assertEqual(data["blocker_diagnostics"], [])


if __name__ == "__main__":
    unittest.main()
