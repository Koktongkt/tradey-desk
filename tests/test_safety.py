import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import autotrader


class TradeySafetyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "enabled": False,
            "broker_mode": "paper",
            "account_cap_usd": 500,
            "max_daily_orders": 2,
            "max_position_usd": 100,
            "min_price_usd": 10,
            "min_average_volume": 1000000,
            "max_spread_bps": 35,
            "allowed_quote_feeds": ["alpaca_iex"],
            "max_limit_deviation_bps": 35,
            "max_planned_risk_per_trade_usd": 25,
            "min_reward_risk": 2.0,
            "min_approval_confidence": 0.75,
            "max_research_age_minutes": 60,
            "earnings_blackout_sessions": 2,
            "allowed_instruments": ["cash_equity"],
            "banned_instruments": ["options", "margin", "crypto", "otc", "penny_stock", "illiquid_stock", "leveraged_etf", "inverse_etf"],
            "kill_switch_path": "KILL_SWITCH",
        }
        self.snapshot = {
            "buying_power": 1000.0,
            "cash": 1000.0,
            "positions": [],
            "open_orders": [],
            "asset": {"symbol": "AAPL", "tradable": True, "class": "us_equity", "exchange": "NASDAQ", "name":"Apple Inc.", "fractionable": False},
            "quote": {"bid": 99.95, "ask": 100.05, "timestamp": "2026-08-29T14:00:00Z"},
            "quote_feed": "alpaca_iex",
            "average_volume": 10_000_000,
            "volume_feed": "massive_consolidated",
            "earnings_status": "upcoming",
            "earnings_sessions_away": 8,
        }
        self.decision = {"action":"BUY","symbol":"AAPL","quantity":1,"order_type":"limit","limit_price":100.05,"stop":98.0,"target":104.2,"horizon":"5 sessions","confidence":0.82,"thesis":"Catalyst with liquid tape","risk_reward":2.075}

    def test_disagreement_blocks_and_strips_order(self):
        other = dict(self.decision, action="HOLD")
        result = autotrader.consensus(self.decision, other, self.cfg)
        self.assertFalse(result["approved"])
        self.assertIsNone(result["order"])
        self.assertEqual(result["reason"], "model_disagreement")

    def test_fractional_quantity_can_reach_consensus(self):
        fractional = dict(self.decision, quantity=0.5)
        result = autotrader.consensus(fractional, fractional, self.cfg)
        self.assertTrue(result["approved"])
        self.assertEqual(result["order"]["quantity"], 0.5)

    def test_non_finite_fractional_quantity_is_rejected(self):
        invalid = dict(self.decision, quantity=float("inf"))
        result = autotrader.consensus(invalid, invalid, self.cfg)
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "malformed_or_low_confidence")

    def test_fractional_quantity_over_alpaca_precision_limit_is_rejected(self):
        invalid = dict(self.decision, quantity=0.1234567891)
        result = autotrader.consensus(invalid, invalid, self.cfg)
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "malformed_or_low_confidence")

    def test_oversized_integer_quantity_fails_closed_without_crashing(self):
        invalid = dict(self.decision, quantity=10**1000)
        result = autotrader.consensus(invalid, invalid, self.cfg)
        self.assertTrue(result["approved"])
        errors = autotrader.validate_order(invalid, self.snapshot, self.cfg, daily_orders=0)
        self.assertIn("position_size_exceeded", errors)

    def test_non_finite_trade_price_is_rejected(self):
        invalid = dict(self.decision, limit_price=float("nan"))
        result = autotrader.consensus(invalid, invalid, self.cfg)
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "malformed_or_low_confidence")

    def test_non_finite_stop_is_rejected(self):
        invalid = dict(self.decision, stop=float("nan"))
        result = autotrader.consensus(invalid, invalid, self.cfg)
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "level_disagreement")

    def test_low_confidence_dual_hold_is_classified_as_consensus_hold(self):
        hold = dict(self.decision, action="HOLD", confidence=0.1)
        result = autotrader.consensus(hold, hold, self.cfg)
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "consensus_hold")

    def test_unavailable_or_malformed_reviewer_blocks(self):
        result = autotrader.consensus(self.decision, None, self.cfg)
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "reviewer_unavailable")
        self.assertIsNone(result["order"])

    def test_materially_different_levels_block_update(self):
        other = dict(self.decision, stop=90.0, target=120.0)
        result = autotrader.consensus(self.decision, other, self.cfg)
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "level_disagreement")

    def test_fractional_buy_is_valid_for_fractionable_asset_under_position_cap(self):
        order = dict(self.decision, quantity=0.5)
        snap = dict(
            self.snapshot,
            asset={**self.snapshot["asset"], "fractionable": True},
            quote={**self.snapshot["quote"], "timestamp": autotrader.utcnow()},
        )
        cfg = dict(self.cfg, allow_fractional_shares=True)
        errors = autotrader.validate_order(order, snap, cfg, daily_orders=0)
        self.assertEqual(errors, [])

    def test_fractional_buy_requires_broker_fractionable_asset(self):
        order = dict(self.decision, quantity=0.5)
        cfg = dict(self.cfg, allow_fractional_shares=True)
        errors = autotrader.validate_order(order, self.snapshot, cfg, daily_orders=0)
        self.assertIn("asset_not_fractionable", errors)

    def test_fractional_buy_still_obeys_position_cap(self):
        order = dict(self.decision, quantity=1.01)
        snap = dict(self.snapshot, asset={**self.snapshot["asset"], "fractionable": True})
        cfg = dict(self.cfg, allow_fractional_shares=True)
        errors = autotrader.validate_order(order, snap, cfg, daily_orders=0)
        self.assertIn("position_size_exceeded", errors)

    def test_fractional_buy_is_blocked_when_policy_is_disabled(self):
        order = dict(self.decision, quantity=0.5)
        snap = dict(self.snapshot, asset={**self.snapshot["asset"], "fractionable": True})
        errors = autotrader.validate_order(order, snap, self.cfg, daily_orders=0)
        self.assertIn("fractional_shares_disabled", errors)

    def test_unknown_buying_power_fails_closed(self):
        snap = dict(self.snapshot, buying_power=None)
        errors = autotrader.validate_order(self.decision, snap, self.cfg, daily_orders=0)
        self.assertIn("unknown_buying_power", errors)

    def test_unknown_cash_and_etf_are_rejected(self):
        snap=dict(self.snapshot,cash=None,asset={**self.snapshot["asset"],"name":"Example 3x Bull ETF"})
        errors=autotrader.validate_order(self.decision,snap,self.cfg,daily_orders=0)
        self.assertIn("unknown_cash",errors)
        self.assertIn("fund_or_etn_forbidden",errors)

    def test_any_active_broker_order_blocks_new_order(self):
        snap=dict(self.snapshot,open_orders=[{"symbol":"MSFT","status":"accepted"}])
        self.assertIn("active_broker_order",autotrader.validate_order(self.decision,snap,self.cfg,daily_orders=0))

    def test_preexisting_position_symbol_is_not_tradeable(self):
        errors = autotrader.validate_order(
            self.decision, self.snapshot, self.cfg, daily_orders=0,
            managed_exposure_usd=0.0, preexisting_symbols={"AAPL"},
        )
        self.assertIn("preexisting_position_conflict", errors)

    def test_account_cap_includes_existing_tradey_exposure(self):
        errors = autotrader.validate_order(
            self.decision, self.snapshot, self.cfg, daily_orders=0,
            managed_exposure_usd=450.0, preexisting_symbols=set(),
        )
        self.assertIn("account_cap_exceeded", errors)

    def test_baseline_is_required_and_returns_uppercase_symbols(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "baseline.json"
            with self.assertRaises(RuntimeError):
                autotrader.load_baseline_symbols(path)
            path.write_text('{"preexisting_symbols":["aapl","MSFT"]}')
            self.assertEqual(autotrader.load_baseline_symbols(path), {"AAPL", "MSFT"})

    def test_managed_exposure_uses_only_net_open_tradey_symbols(self):
        positions = [
            {"symbol": "NEW", "market_value": "120"},
            {"symbol": "OLD", "market_value": "5000"},
        ]
        journal = [
            {"symbol": "NEW", "action": "BUY", "quantity": 2, "status": "filled"},
            {"symbol": "CLOSED", "action": "BUY", "quantity": 1, "status": "filled"},
            {"symbol": "CLOSED", "action": "SELL", "quantity": 1, "status": "filled"},
        ]
        exposure, errors = autotrader.managed_exposure(positions, journal)
        self.assertEqual(exposure, 120.0)
        self.assertEqual(errors, [])

    def test_managed_exposure_fails_closed_when_journal_position_missing_at_broker(self):
        journal = [{"symbol": "NEW", "action": "BUY", "quantity": 1, "status": "filled"}]
        exposure, errors = autotrader.managed_exposure([], journal)
        self.assertEqual(exposure, 0.0)
        self.assertIn("managed_position_reconciliation_failed", errors)

    def test_sell_cannot_open_short(self):
        sell=dict(self.decision,action="SELL",stop=102.0,target=96.0,risk_reward=2.0)
        self.assertIn("short_sale_forbidden",autotrader.validate_order(sell,self.snapshot,self.cfg,daily_orders=0))

    def test_live_dry_run_may_review_stale_but_intact_research(self):
        candidate = {"sources": [{}, {}], "sources_verified_at": "now"}
        with patch("autotrader._dossier_intact", return_value=True):
            self.assertFalse(autotrader.research_acceptable(candidate, self.cfg, age_minutes=90, allow_stale=False))
            self.assertTrue(autotrader.research_acceptable(candidate, self.cfg, age_minutes=90, allow_stale=True))

    def test_live_dry_run_can_reach_reviews_but_never_enables_execution(self):
        cfg = dict(self.cfg, enabled=False)
        self.assertEqual(autotrader.runtime_blockers(cfg, ignore_disabled=True), [])
        self.assertIn("autonomy_disabled", autotrader.runtime_blockers(cfg))

    def test_fixture_dry_run_writes_only_test_artifacts(self):
        source_root = autotrader.ROOT
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "fixtures").mkdir()
            (root / "fixtures" / "dry_run_bundle.json").write_text(
                (source_root / "fixtures" / "dry_run_bundle.json").read_text()
            )
            cfg = autotrader.load_json(source_root / "autonomy_config.json")
            cfg["kill_switch_path"] = str(root / "KILL_SWITCH")
            (root / "autonomy_config.json").write_text(json.dumps(cfg))

            with patch.object(autotrader, "ROOT", root):
                rc = autotrader.run(SimpleNamespace(dry_run_fixture=True, live_dry_run=False))

            self.assertEqual(rc, 2)
            self.assertFalse((root / "order_ledger.jsonl").exists())
            self.assertFalse((root / "private" / "reviews.jsonl").exists())
            fixture_rows = [
                json.loads(line)
                for line in (root / "test_artifacts" / "dry_run_order_ledger.jsonl").read_text().splitlines()
            ]
            self.assertEqual([row["status"] for row in fixture_rows], ["proposed", "rejected"])
            self.assertEqual(fixture_rows[-1]["reason"], ["dry_run_no_execution"])
            self.assertTrue((root / "test_artifacts" / "dry_run_reviews.jsonl").exists())

    def test_any_dry_run_uses_test_artifact_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger, reviews, disagreements = autotrader.output_paths(root, dry_run=True)
            self.assertEqual(ledger, root / "test_artifacts" / "dry_run_order_ledger.jsonl")
            self.assertEqual(reviews, root / "test_artifacts" / "dry_run_reviews.jsonl")
            self.assertEqual(disagreements, root / "test_artifacts" / "dry_run_disagreements.jsonl")

    def test_kill_switch_blocks_even_when_disabled_flag_changes(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "KILL_SWITCH"
            p.touch()
            cfg = dict(self.cfg, enabled=True, kill_switch_path=str(p))
            self.assertIn("kill_switch_active", autotrader.runtime_blockers(cfg))

    def test_active_order_for_symbol_is_rejected(self):
        snap = dict(self.snapshot, open_orders=[{"symbol":"AAPL","status":"new"}])
        errors = autotrader.validate_order(self.decision, snap, self.cfg, daily_orders=0)
        self.assertIn("active_broker_order", errors)

    def test_reward_risk_and_spread_are_deterministic(self):
        bad = dict(self.decision, target=101.0)
        snap = dict(self.snapshot, quote={"bid":99.0,"ask":101.0,"timestamp":"2026-08-29T14:00:00Z"})
        errors = autotrader.validate_order(bad, snap, self.cfg, daily_orders=0)
        self.assertIn("weak_reward_to_risk", errors)
        self.assertIn("spread_too_wide", errors)

    def test_order_metric_normalization_overwrites_stale_model_ratio(self):
        order = dict(self.decision, limit_price=450.0, stop=408.0, target=510.0, risk_reward=1.84)
        normalized = autotrader.normalize_order_metrics(order)
        self.assertAlmostEqual(normalized["risk_reward"], 60 / 42)

    def test_horizon_classifier_uses_verified_exchange_sessions(self):
        candidate = {
            "planned_exit_at": "2026-09-08T20:00:00Z",
            "claimed_holding_sessions": 5,
        }
        snapshot = {
            "trading_sessions": [
                "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-08",
            ],
        }
        result, errors = autotrader.classify_horizon(candidate, snapshot)
        self.assertEqual(errors, [])
        self.assertEqual(result, {"holding_sessions": 5, "assigned_rubric": "short_1_5"})

    def test_horizon_classifier_fails_closed_on_claim_mismatch(self):
        candidate = {
            "planned_exit_at": "2026-09-09T20:00:00Z",
            "claimed_holding_sessions": 5,
        }
        snapshot = {
            "trading_sessions": [
                "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-08", "2026-09-09",
            ],
        }
        result, errors = autotrader.classify_horizon(candidate, snapshot)
        self.assertIsNone(result)
        self.assertEqual(errors, ["horizon_session_mismatch"])

    def test_horizon_exit_date_is_interpreted_in_new_york(self):
        candidate = {"planned_exit_at": "2026-09-09T00:30:00Z"}
        snapshot = {"trading_sessions": ["2026-09-08", "2026-09-09"]}
        result, errors = autotrader.classify_horizon(candidate, snapshot)
        self.assertEqual(errors, [])
        self.assertEqual(result["holding_sessions"], 1)

    def test_deterministic_levels_use_atr_and_setup_family(self):
        bars = [
            {"open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0, "timestamp": f"2026-08-{day:02d}"}
            for day in range(1, 21)
        ]
        momentum, errors = autotrader.derive_technical_levels(100.0, bars, "breakout", "short_1_5")
        self.assertEqual(errors, [])
        self.assertEqual(momentum, {"stop": 95.0, "target": 109.0, "atr_14": 4.0, "level_method": "atr_momentum"})
        swing, errors = autotrader.derive_technical_levels(100.0, bars, "strategic_rerating", "swing_6_30")
        self.assertEqual(errors, [])
        self.assertEqual(swing, {"stop": 94.0, "target": 112.0, "atr_14": 4.0, "level_method": "atr_swing"})

    def test_deterministic_pullback_levels_use_recent_structure(self):
        bars = [
            {"open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0, "timestamp": f"2026-08-{day:02d}"}
            for day in range(1, 21)
        ]
        levels, errors = autotrader.derive_technical_levels(100.0, bars, "pullback_to_support", "short_1_5")
        self.assertEqual(errors, [])
        self.assertEqual(levels, {"stop": 97.6, "target": 102.0, "atr_14": 4.0, "level_method": "recent_structure"})

    def test_deterministic_levels_fail_closed_on_bad_bars(self):
        levels, errors = autotrader.derive_technical_levels(100.0, [{"high": 1}], "breakout", "short_1_5")
        self.assertIsNone(levels)
        self.assertEqual(errors, ["technical_bars_unavailable"])

    def test_canonical_proposal_uses_ask_and_stop_risk_for_integer_quantity(self):
        candidate = {
            "symbol": "AAPL", "stop": 1.0, "target": 1000.0,
            "planned_exit_at": "2026-09-04T20:00:00Z",
            "setup_type": "post_news_momentum", "thesis": "verified catalyst",
        }
        snapshot = dict(
            self.snapshot,
            quote={**self.snapshot["quote"], "ask": 100.0},
            trading_sessions=["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"],
            technical_bars=[
                {"open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0, "timestamp": f"2026-08-{day:02d}"}
                for day in range(1, 21)
            ],
            technical_bars_feed="massive_consolidated_completed_daily",
        )
        cfg = dict(self.cfg, max_position_usd=500, account_cap_usd=10_000)
        proposal, errors = autotrader.build_canonical_proposal(candidate, snapshot, cfg, managed_exposure_usd=0)
        self.assertEqual(errors, [])
        self.assertEqual(proposal["limit_price"], 100.0)
        self.assertEqual(proposal["stop"], 95.0)
        self.assertEqual(proposal["target"], 109.0)
        self.assertEqual(proposal["quantity"], 5)
        self.assertEqual(proposal["planned_risk_usd"], 25.0)
        self.assertEqual(proposal["position_value_usd"], 500.0)
        self.assertEqual(proposal["level_method"], "atr_momentum")
        self.assertEqual(proposal["assigned_rubric"], "short_1_5")
        self.assertEqual(len(proposal["proposal_hash"]), 64)

    def test_rubric_score_is_deterministic_and_horizon_specific(self):
        scores = {
            "catalyst": 5, "price_volume_confirmation": 4, "technical_structure": 3,
            "market_regime": 2, "fundamental_trajectory": 1, "valuation_expectations": 0,
        }
        self.assertAlmostEqual(autotrader.rubric_confidence("short_1_5", scores), 0.68)
        self.assertAlmostEqual(autotrader.rubric_confidence("swing_6_30", scores), 0.56)

    def test_immutable_review_aggregation_uses_lower_deterministic_score(self):
        proposal = {"proposal_hash": "abc", "symbol": "AAPL", "assigned_rubric": "short_1_5"}
        first = {
            "proposal_hash": "abc", "decision": "APPROVE", "component_scores": {
                "catalyst": 4, "price_volume_confirmation": 4, "technical_structure": 4,
                "market_regime": 4, "fundamental_trajectory": 4, "valuation_expectations": 4,
            }, "fatal_flags": [], "reason_codes": ["supported"],
        }
        second = {**first, "component_scores": {key: 3 for key in first["component_scores"]}}
        result = autotrader.aggregate_proposal_reviews(proposal, [first, second], {"min_approval_confidence": 0.55})
        self.assertTrue(result["approved"])
        self.assertEqual(result["order"]["confidence"], 0.6)
        self.assertEqual(result["reviewer_confidences"], [0.8, 0.6])

    def test_immutable_review_hash_mismatch_fails_closed(self):
        proposal = {"proposal_hash": "abc", "symbol": "AAPL", "assigned_rubric": "short_1_5"}
        review = {
            "proposal_hash": "wrong", "decision": "APPROVE", "component_scores": {
                "catalyst": 5, "price_volume_confirmation": 5, "technical_structure": 5,
                "market_regime": 5, "fundamental_trajectory": 5, "valuation_expectations": 5,
            }, "fatal_flags": [], "reason_codes": [],
        }
        result = autotrader.aggregate_proposal_reviews(proposal, [review, review], {"min_approval_confidence": 0.55})
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "proposal_hash_mismatch")

    def test_limit_price_must_remain_close_to_execution_quote(self):
        order = dict(self.decision, limit_price=101.0)
        snap = dict(self.snapshot, quote={"bid":99.95,"ask":100.05,"timestamp":autotrader.utcnow()})
        self.assertIn("limit_price_too_far_from_quote", autotrader.validate_order(order, snap, self.cfg, daily_orders=0))

    def test_planned_stop_loss_cannot_exceed_fixed_risk_budget(self):
        order = dict(self.decision, quantity=3, limit_price=100.0, stop=90.0, target=120.0)
        snap = dict(self.snapshot, quote={"bid":99.95,"ask":100.0,"timestamp":autotrader.utcnow()})
        cfg = dict(self.cfg, max_position_usd=500, min_reward_risk=1.6)
        errors = autotrader.validate_order(order, snap, cfg, daily_orders=0)
        self.assertIn("planned_risk_exceeded", errors)

    def test_explicitly_allowed_iex_quote_enforces_spread_gate(self):
        snap = dict(
            self.snapshot,
            quote={"bid":99.0,"ask":101.0,"timestamp":autotrader.utcnow()},
            quote_feed="alpaca_iex",
        )
        errors = autotrader.validate_order(self.decision, snap, self.cfg, daily_orders=0)
        self.assertNotIn("quote_feed_unavailable", errors)
        self.assertIn("spread_too_wide", errors)

    def test_unapproved_quote_feed_fails_closed(self):
        snap = dict(self.snapshot, quote_feed="unknown_feed")
        errors = autotrader.validate_order(self.decision, snap, self.cfg, daily_orders=0)
        self.assertIn("quote_feed_unavailable", errors)

    def test_liquidity_requires_consolidated_volume_provenance(self):
        snap = dict(self.snapshot, volume_feed="alpaca_iex")
        errors = autotrader.validate_order(self.decision, snap, self.cfg, daily_orders=0)
        self.assertIn("consolidated_volume_unavailable", errors)
        self.assertNotIn("liquidity_failed", errors)

    def test_non_finite_broker_market_data_fails_closed(self):
        snap = dict(
            self.snapshot,
            average_volume=float("nan"),
            quote={"bid":float("nan"),"ask":100.05,"timestamp":autotrader.utcnow()},
        )
        errors = autotrader.validate_order(self.decision, snap, self.cfg, daily_orders=0)
        self.assertIn("liquidity_failed", errors)
        self.assertIn("unknown_spread", errors)

    def test_stale_quote_is_rejected(self):
        snap=dict(self.snapshot,quote={"bid":99.95,"ask":100.05,"timestamp":"2020-01-01T00:00:00Z"})
        cfg=dict(self.cfg,max_quote_age_seconds=120)
        self.assertIn("stale_quote",autotrader.validate_order(self.decision,snap,cfg,daily_orders=0))

    def test_reported_earnings_do_not_trigger_upcoming_blackout(self):
        snap = dict(self.snapshot, earnings_status="reported", earnings_sessions_away=None)
        errors = autotrader.validate_order(self.decision, snap, self.cfg, daily_orders=0)
        self.assertNotIn("near_term_earnings", errors)
        self.assertNotIn("earnings_unknown", errors)

    def test_upcoming_earnings_inside_blackout_are_rejected(self):
        snap = dict(self.snapshot, earnings_status="upcoming", earnings_sessions_away=2)
        self.assertIn("near_term_earnings", autotrader.validate_order(self.decision, snap, self.cfg, daily_orders=0))

    def test_unknown_earnings_status_fails_closed(self):
        snap = dict(self.snapshot, earnings_status="unknown", earnings_sessions_away=None)
        self.assertIn("earnings_unknown", autotrader.validate_order(self.decision, snap, self.cfg, daily_orders=0))

    def test_broker_nulls_replace_model_values(self):
        model_claim = {"buying_power":999999,"positions":[{"symbol":"FAKE"}],"asset":{"tradable":True}}
        snap = {"buying_power":None,"positions":[],"asset":None}
        merged = autotrader.replace_broker_fields(model_claim, snap)
        self.assertIsNone(merged["buying_power"])
        self.assertEqual(merged["positions"], [])
        self.assertIsNone(merged["asset"])

    def test_pending_order_intents_use_latest_ledger_status(self):
        intents = [
            {"client_order_id": "tradey-open", "plan": self.decision},
            {"client_order_id": "tradey-done", "plan": self.decision},
        ]
        ledger = [
            {"client_order_id": "tradey-open", "status": "placed"},
            {"client_order_id": "tradey-open", "status": "new"},
            {"client_order_id": "tradey-done", "status": "placed"},
            {"client_order_id": "tradey-done", "status": "filled"},
        ]
        self.assertEqual(autotrader.pending_order_intents(ledger, intents), [intents[0]])

    def test_daily_order_count_deduplicates_order_lifecycle_rows(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            today = autotrader.utcnow()[:10]
            rows = [
                {"timestamp": today + "T10:00:00Z", "status": "placed", "client_order_id": "same"},
                {"timestamp": today + "T10:01:00Z", "status": "filled", "client_order_id": "same"},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            self.assertEqual(autotrader._daily_order_count(path), 1)

    def test_pending_fill_is_reconciled_and_journaled_on_later_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = root / "ledger.jsonl"
            intents = root / "intents.jsonl"
            journal = root / "journal.jsonl"
            ref = "tradey-pending"
            ledger.write_text(json.dumps({"client_order_id": ref, "status": "new"}) + "\n")
            intents.write_text(json.dumps({"client_order_id": ref, "plan": self.decision}) + "\n")
            broker = lambda operation, payload: {
                "status": "filled", "filled_qty": "1", "filled_avg_price": "100.01"
            }
            autotrader.reconcile_pending_orders(ledger, intents, journal, broker)
            self.assertEqual(json.loads(journal.read_text())["status"], "filled")
            self.assertEqual(json.loads(ledger.read_text().splitlines()[-1])["status"], "filled")

    def test_idempotency_reference_is_stable(self):
        a = autotrader.idempotency_ref(self.decision, "2026-08-29")
        b = autotrader.idempotency_ref(dict(reversed(list(self.decision.items()))), "2026-08-29")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("tradey-"))

    def test_fill_journal_requires_confirmed_fill(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"trade_journal.jsonl"
            autotrader.journal_confirmed_fill(path, self.decision, {"status":"partially_filled","filled_qty":"0.5"})
            self.assertFalse(path.exists())
            autotrader.journal_confirmed_fill(path, self.decision, {"status":"filled","filled_qty":"1","filled_avg_price":"100.02"})
            row=json.loads(path.read_text().strip())
            self.assertEqual(row["status"], "filled")
            self.assertEqual(row["entry"], 100.02)
    def test_authoritative_bundle_contains_only_deterministic_broker_snapshot(self):
        snapshot = dict(self.snapshot, account_id="secret", invented="value")
        bundle = autotrader.authoritative_bundle({"symbol": "AAPL", "average_volume": 99, "volume_feed": "claimed"}, snapshot, "2026-08-29T14:00:00Z")
        self.assertEqual(set(bundle["broker_snapshot"]), set(autotrader.BROKER_FIELDS) | {"captured_at"})
        self.assertNotIn("account_id", bundle["broker_snapshot"])
        self.assertNotIn("invented", bundle["broker_snapshot"])
        self.assertNotIn("average_volume", bundle["candidate"])
        self.assertNotIn("volume_feed", bundle["candidate"])

    def test_nous_reviewer_uses_explicit_model_and_no_tools(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"proposal_hash":"abc","decision":"HOLD","component_scores":{"catalyst":2,"price_volume_confirmation":2,"technical_structure":2,"market_regime":2,"fundamental_trajectory":2,"valuation_expectations":2},"fatal_flags":["weak_setup"],"reason_codes":["insufficient_confirmation"]}\n\nsession_id: test',
            stderr="",
        )
        proposal = {"proposal_hash": "abc", "assigned_rubric": "short_1_5", "symbol": "AAPL"}
        with patch("autotrader.subprocess.run", return_value=completed) as run:
            result = autotrader._review_via_hermes(
                {"proposal": proposal, "rubric_weights": autotrader.RUBRIC_WEIGHTS["short_1_5"]},
                "nous",
                "deepseek/deepseek-v4-flash-0731",
            )
        self.assertEqual(result["decision"], "HOLD")
        self.assertEqual(result["proposal_hash"], "abc")
        cmd = run.call_args.args[0]
        self.assertIn("--provider", cmd)
        self.assertEqual(cmd[cmd.index("--provider") + 1], "nous")
        self.assertEqual(cmd[cmd.index("-m") + 1], "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(cmd[cmd.index("-t") + 1], "")
        self.assertIn("--safe-mode", cmd)
        prompt = run.call_args.kwargs["input"]
        self.assertIn("Fail closed with HOLD when evidence is incomplete", prompt)
        self.assertIn("Do not alter or repeat executable order fields", prompt)
        self.assertIn("component_scores", prompt)
        self.assertIn("integer from 0 through 5", prompt)
        self.assertIn("proposal_hash", prompt)
        self.assertNotIn("choose a whole-share quantity", prompt)

    def test_reviewer_retries_once_only_to_reformat_unparseable_output(self):
        malformed = subprocess.CompletedProcess(args=[], returncode=0, stdout="APPROVE; scores catalyst five", stderr="")
        repaired = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"proposal_hash":"abc","decision":"HOLD","component_scores":{"catalyst":2,"price_volume_confirmation":2,"technical_structure":2,"market_regime":2,"fundamental_trajectory":2,"valuation_expectations":2},"fatal_flags":["original_not_machine_readable"],"reason_codes":["format_repaired"]}',
            stderr="",
        )
        bundle = {"proposal": {"proposal_hash": "abc"}}
        with patch("autotrader.subprocess.run", side_effect=[malformed, repaired]) as run:
            result = autotrader._review_via_hermes(bundle, "nous", "z-ai/glm-5.3-flash")
        self.assertEqual(result["decision"], "HOLD")
        self.assertEqual(run.call_count, 2)
        repair_prompt = run.call_args_list[1].kwargs["input"]
        self.assertIn("formatting repair only", repair_prompt.lower())
        self.assertIn("Do not reconsider", repair_prompt)
        self.assertIn("APPROVE; scores catalyst five", repair_prompt)

    def test_reviewer_does_not_retry_model_or_process_failure(self):
        failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="failure")
        with patch("autotrader.subprocess.run", return_value=failed) as run:
            result = autotrader._review_via_hermes({"proposal": {"proposal_hash": "abc"}}, "nous", "z-ai/glm-5.3-flash")
        self.assertIsNone(result)
        self.assertEqual(run.call_count, 1)

    def test_shadow_recording_runs_only_for_real_cycles_and_uses_isolated_path(self):
        candidate = {"candidate_id": "cand", "spy_price": 500.0}
        proposal = {"proposal_hash": "hash"}
        aggregate = {"approved": False}
        with tempfile.TemporaryDirectory() as td, patch.object(autotrader, "ROOT", Path(td)), patch("autotrader.record_shadow_decision") as record:
            autotrader.record_shadow_if_live(SimpleNamespace(dry_run_fixture=True, live_dry_run=False), candidate, proposal, aggregate, "now")
            autotrader.record_shadow_if_live(SimpleNamespace(dry_run_fixture=False, live_dry_run=True), candidate, proposal, aggregate, "now")
            self.assertEqual(record.call_count, 0)
            autotrader.record_shadow_if_live(SimpleNamespace(dry_run_fixture=False, live_dry_run=False), candidate, proposal, aggregate, "now")
            self.assertEqual(record.call_count, 1)
            self.assertEqual(record.call_args.args[0], Path(td) / "test_artifacts" / "shadow" / "decisions.jsonl")

    def test_config_pins_two_distinct_nous_reviewer_models(self):
        cfg = autotrader.load_json(autotrader.ROOT / "autonomy_config.json")
        self.assertIs(cfg["allow_fractional_shares"], False)
        self.assertEqual(cfg["max_position_usd"], 500)
        self.assertEqual(cfg["allowed_quote_feeds"], ["alpaca_iex"])
        self.assertEqual(cfg["max_limit_deviation_bps"], 150)
        self.assertEqual(cfg["max_spread_bps"], 250)
        self.assertEqual(cfg["max_planned_risk_per_trade_usd"], 25)
        self.assertEqual(cfg["min_reward_risk"], 1.6)
        self.assertEqual(cfg["min_approval_confidence"], 0.55)
        self.assertEqual(
            cfg["research_model"],
            {"provider": "nous", "model": "deepseek/deepseek-v4-flash-0731", "checkpoint": "DeepSeek-V4-Flash-0731"},
        )
        self.assertEqual(
            cfg["review_model"],
            {"provider": "nous", "model": "z-ai/glm-5.3-flash", "checkpoint": "GLM-5.3-Flash"},
        )

    def test_independent_reviews_dispatch_both_configured_models(self):
        cfg = {
            "research_model": {"provider": "nous", "model": "deepseek/deepseek-v4-flash-0731"},
            "review_model": {"provider": "nous", "model": "z-ai/glm-5.3-flash"},
            "max_position_usd": 500,
            "allow_fractional_shares": False,
            "min_reward_risk": 1.6,
            "max_limit_deviation_bps": 35,
        }
        bundle = {"candidate": {"symbol": "AAPL"}}
        with patch("autotrader._review_via_hermes", side_effect=[{"reviewer": "A"}, {"reviewer": "B"}]) as review:
            results = autotrader.independent_reviews(bundle, cfg)
        self.assertEqual(results, [{"reviewer": "A"}, {"reviewer": "B"}])
        for call in review.call_args_list:
            self.assertEqual(
                call.args[0]["execution_policy"],
                {"max_position_usd": 500, "allow_fractional_shares": False, "min_reward_risk": 1.6, "max_limit_deviation_bps": 35},
            )
        calls = {(call.args[1], call.args[2]) for call in review.call_args_list}
        self.assertEqual(calls, {
            ("nous", "deepseek/deepseek-v4-flash-0731"),
            ("nous", "z-ai/glm-5.3-flash"),
        })


if __name__ == "__main__":
    unittest.main()
