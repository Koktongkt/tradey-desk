"""W2 (pure-strip review bundle) + W4 (no-op cycle skip) tests.

W2: the reviewer evidence bundle must exclude raw broker arrays that
deterministic code already consumed (technical_bars, trading_sessions,
positions, open_orders) while retaining every field reviewers judge on
(candidate dossier, derived levels, sizing, spread, earnings state, feeds).

W4: an autotrader cycle whose newest candidate's dossier_hash already
received a completed review outcome (hold/low_confidence/disagreement/
reviewer_veto) and whose proposal hash would be unchanged must skip before
any broker snapshot or reviewer call, emitting a normalized schedule skip.
A stale/system-failure exit on that candidate must NOT set the skip flag;
pending-intent reconciliation must always run regardless.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autotrader


def _proposal():
    immutable, cfg, _ = ReviewBundleStripTests()._build(_snapshot_with_bars(), _candidate())
    proposal, errors = autotrader.build_canonical_proposal(_candidate(), immutable["broker_snapshot"], cfg, 0.0)
    assert errors == [] and proposal is not None
    return proposal


def _review_ts():
    import datetime as _dt
    return (_dt.datetime.now(_dt.timezone.utc)+_dt.timedelta(minutes=1)).isoformat().replace("+00:00","Z")


def _snapshot_with_bars():
    bars = [
        {"open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i,
         "volume": 1_000_000 + i, "timestamp": 1700000000 + i * 86400}
        for i in range(25)
    ]
    return {
        "captured_at": "2026-09-05T14:00:00Z",
        "buying_power": 10000.0,
        "cash": 10000.0,
        "positions": [],
        "open_orders": [],
        "asset": {"symbol": "DELL", "tradable": True, "class": "us_equity",
                  "exchange": "NASDAQ", "name": "Dell Technologies Inc.",
                  "fractionable": True, "leveraged": False, "inverse": False},
        "quote": {"bid": 99.98, "ask": 100.02, "timestamp": "2026-09-05T14:00:00Z"},
        "quote_feed": "alpaca_iex",
        "average_volume": 5_000_000.0,
        "volume_feed": "massive_consolidated",
        "technical_bars": bars,
        "technical_bars_feed": "massive_consolidated_completed_daily",
        "earnings_status": "unknown",
        "earnings_sessions_away": None,
        "trading_sessions": ["2026-09-05", "2026-09-08", "2026-09-09"],
    }


def _candidate():
    import datetime as _dt
    now=_dt.datetime.now(_dt.timezone.utc)
    r_at=(now-_dt.timedelta(minutes=5)).isoformat().replace("+00:00","Z")
    v_at=(now-_dt.timedelta(minutes=4)).isoformat().replace("+00:00","Z")
    return {
        "symbol": "DELL",
        "researched_at": r_at,
        "sources_verified_at": v_at,
        "sources": [{"url": "https://a.example/1", "title": "A"}, {"url": "https://b.example/2", "title": "B"}],
        "price": 100.0,
        "spy_price": 500.0,
        "instrument_type": "cash_equity",
        "setup_type": "breakout",
        "earnings_event_at": "2026-09-10T20:00:00Z",
        "planned_exit_at": "2026-09-18T20:00:00Z",
        "horizon_rationale": "swing",
        "catalyst": "guidance raise",
        "thesis": "post-news drift",
    }


def _cfg():
    cfg = json.loads(Path("/opt/data/tradey-desk/autonomy_config.json").read_text())
    cfg["min_price_usd"] = 10
    return cfg


class ReviewBundleStripTests(unittest.TestCase):
    def _build(self, snapshot, candidate):
        exposure = 0.0
        return autotrader.authoritative_bundle(candidate, snapshot, snapshot["captured_at"]), _cfg(), exposure

    def test_review_bundle_excludes_raw_bars_and_arrays(self):
        bundle = autotrader.build_review_bundle(_candidate(), _snapshot_with_bars(), _proposal())
        evidence = bundle["evidence"]
        snapshot = evidence["broker_snapshot"]
        self.assertNotIn("technical_bars", snapshot)
        self.assertNotIn("trading_sessions", snapshot)
        self.assertNotIn("positions", snapshot)
        self.assertNotIn("open_orders", snapshot)

    def test_review_bundle_retains_derived_levels_and_judgment_fields(self):
        bundle = autotrader.build_review_bundle(_candidate(), _snapshot_with_bars(), _proposal())
        proposal = bundle["proposal"]
        for key in ("stop", "target", "atr_14", "level_method", "limit_price", "quantity",
                    "risk_reward", "holding_sessions", "assigned_rubric", "thesis", "setup_type"):
            self.assertIn(key, proposal)
        snapshot = bundle["evidence"]["broker_snapshot"]
        for key in ("quote", "quote_feed", "volume_feed", "average_volume",
                    "earnings_status", "earnings_sessions_away", "buying_power", "cash", "asset"):
            self.assertIn(key, snapshot)
        self.assertIn("technical_bars_feed", snapshot)  # provenance stays
        self.assertIn("candidate", bundle["evidence"])
        self.assertIn("rubric_weights", bundle)

    def test_build_canonical_proposal_still_needs_full_snapshot(self):
        # The full snapshot (with bars) must still produce a proposal: strip
        # applies only to the reviewer bundle, not the deterministic path.
        immutable, cfg, _ = self._build(_snapshot_with_bars(), _candidate())
        proposal, errors = autotrader.build_canonical_proposal(
            _candidate(), immutable["broker_snapshot"], cfg, 0.0)
        self.assertEqual(errors, [])
        self.assertIsNotNone(proposal)

    def test_stripped_bundle_is_smaller_than_full(self):
        full = autotrader.authoritative_bundle(_candidate(), _snapshot_with_bars(), "2026-09-05T14:00:00Z")
        stripped = autotrader.build_review_bundle(_candidate(), _snapshot_with_bars(), _cfg())
        self.assertLess(len(json.dumps(stripped)), len(json.dumps(full)))

    def test_strip_is_pure_function_of_hashed_fields(self):
        cand = _candidate()
        snap = _snapshot_with_bars()
        prop = _proposal()
        a = autotrader.build_review_bundle(cand, snap, prop)
        b = autotrader.build_review_bundle(cand, snap, prop)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))


class NoOpCycleSkipTests(unittest.TestCase):
    def _write_dossier(self, root, candidate):
        body = {k: v for k, v in candidate.items() if k != "dossier_hash"}
        import hashlib
        candidate = dict(candidate)
        candidate["dossier_hash"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        (root / "candidates.jsonl").write_text(json.dumps(candidate) + "\n")
        return candidate

    def test_same_dossier_after_hold_review_skips_before_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "autonomy_config.json").write_text(json.dumps(_cfg()))
            candidate = self._write_dossier(root, _candidate())
            (root / "private").mkdir()
            (root / "private" / "reviews.jsonl").write_text(
                json.dumps({"timestamp": _review_ts(), "dossier_hash": candidate["dossier_hash"], "reviews": [{"decision": "HOLD"}, {"decision": "HOLD"}]}) + "\n")
            with patch.object(autotrader, "ROOT", root), patch(
                "autotrader._broker_bridge", side_effect=AssertionError("snapshot must not run")
            ), patch("autotrader.independent_reviews", side_effect=AssertionError("reviews must not run")):
                captured_out = __import__("io").StringIO()
                import contextlib
                with contextlib.redirect_stdout(captured_out):
                    code = autotrader.run(autotrader.argparse.Namespace(dry_run_fixture=False, live_dry_run=False))
            self.assertEqual(code, 0)
            self.assertIn("DECISION skipped already_reviewed", captured_out.getvalue())

    def test_completed_outcomes_mark_dossier_spent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = self._write_dossier(root, _candidate())
            reviews = root / "private" / "reviews.jsonl"
            reviews.parent.mkdir(parents=True)
            reviews.write_text("")
            self.assertFalse(autotrader.dossier_already_reviewed(candidate, reviews))
            reviews.write_text(json.dumps({"timestamp": _review_ts(), "dossier_hash": candidate["dossier_hash"], "reviews": [{"decision": "HOLD"}, {"decision": "APPROVE"}]}) + "\n")
            self.assertTrue(autotrader.dossier_already_reviewed(candidate, reviews))

    def test_missing_or_malformed_review_rows_do_not_mark_spent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = self._write_dossier(root, _candidate())
            reviews = root / "private" / "reviews.jsonl"
            reviews.parent.mkdir(parents=True)
            reviews.write_text("not-json\n{\"timestamp\":\"2020-01-01T00:00:00Z\"}\n")
            self.assertFalse(autotrader.dossier_already_reviewed(candidate, reviews))

    def test_reconcile_runs_before_skip_decision(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "autonomy_config.json").write_text(json.dumps(_cfg()))
            spent = self._write_dossier(root, _candidate())
            (root / "private").mkdir()
            (root / "private" / "reviews.jsonl").write_text(
                json.dumps({"timestamp": _review_ts(), "dossier_hash": spent["dossier_hash"], "reviews": [{"decision": "HOLD"}, {"decision": "HOLD"}]}) + "\n")
            calls = []
            def fake_reconcile(*a, **k):
                calls.append("reconcile")
                return []
            with patch.object(autotrader, "ROOT", root), patch(
                "autotrader.reconcile_pending_orders", side_effect=fake_reconcile
            ), patch("autotrader._broker_bridge", side_effect=AssertionError("snapshot must not run")):
                import contextlib
                with contextlib.redirect_stdout(__import__("io").StringIO()):
                    autotrader.run(autotrader.argparse.Namespace(dry_run_fixture=False, live_dry_run=False))
            self.assertEqual(calls, ["reconcile"])


class SkipEventAuditTests(unittest.TestCase):
    def test_run_cycle_parses_already_reviewed_skip(self):
        import run_cycle
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "decision_audit.jsonl"
            run_cycle.audit_result("autotrader", "schedule", 0, "DECISION skipped already_reviewed", path)
            row = json.loads(path.read_text())
        self.assertEqual(row["decision"], "skipped")
        self.assertEqual(row["reason"], "already_reviewed")


if __name__ == "__main__":
    unittest.main()
