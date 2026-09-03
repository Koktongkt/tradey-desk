import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import alpha_radar
import candidate_outcomes
import public_dashboard


class PipelineTests(unittest.TestCase):
    def test_radar_rejects_single_source_candidate(self):
        bad={"symbol":"AAPL","price":100,"average_volume":2_000_000,"instrument_type":"cash_equity","sources":[{"url":"https://one.example"}],"researched_at":"2026-08-29T14:00:00Z"}
        self.assertFalse(alpha_radar.qualified(bad,{"min_price_usd":10,"min_average_volume":1_000_000}))

    def test_radar_does_not_require_model_supplied_volume(self):
        candidate={
            "symbol":"AAPL","price":100,"spy_price":500,"instrument_type":"cash_equity",
            "sources":[{"url":"https://one.example/a"},{"url":"https://two.example/b"}],
            "earnings_event_at":"2026-11-01T21:00:00Z","researched_at":"2026-08-29T14:00:00Z",
            "setup_type":"post_news_momentum","planned_exit_at":"2026-09-04T20:00:00Z",
            "horizon_rationale":"short repricing window",
        }
        self.assertTrue(alpha_radar.qualified(candidate,{"min_price_usd":10,"min_average_volume":1_000_000}))

    def test_research_prompt_does_not_request_unproven_average_volume(self):
        self.assertNotIn("average_volume", alpha_radar.research_prompt())

    def test_research_prompt_requests_timestamp_not_model_counted_sessions(self):
        prompt = alpha_radar.research_prompt()
        self.assertIn("earnings_event_at", prompt)
        self.assertNotIn("earnings_sessions_away", prompt)

    def test_radar_requires_structured_horizon_inputs(self):
        base = {
            "symbol":"AAPL","price":100,"spy_price":500,"instrument_type":"cash_equity",
            "sources":[{"url":"https://one.example/a"},{"url":"https://two.example/b"}],
            "earnings_event_at":"2026-11-01T21:00:00Z","researched_at":"2026-08-29T14:00:00Z",
        }
        self.assertFalse(alpha_radar.qualified(base,{"min_price_usd":10}))
        complete = dict(
            base, setup_type="post_news_momentum", planned_exit_at="2026-09-04T20:00:00Z",
            horizon_rationale="repricing window",
        )
        self.assertTrue(alpha_radar.qualified(complete,{"min_price_usd":10}))
        prompt = alpha_radar.research_prompt()
        for field in ("setup_type", "planned_exit_at", "horizon_rationale"):
            self.assertIn(field, prompt)
        self.assertNotIn("claimed_holding_sessions", prompt)
        self.assertNotIn("horizon_rationale, confidence", prompt)
        self.assertIn("do not select quantity, confidence, risk_reward, or an executable limit", prompt.lower())
        self.assertNotIn("thesis, stop, target, setup_type", prompt)
        self.assertIn("Do not propose stop or target", prompt)

    def test_radar_strips_model_supplied_feed_fields(self):
        candidate = {
            "symbol": "AAPL", "average_volume": 99, "volume_feed": "claimed_sip",
            "quote": {"bid": 1, "ask": 2}, "quote_feed": "claimed_sip", "stop": 90, "target": 120,
            "technical_bars": [{"close": 1}], "technical_bars_feed": "claimed", "thesis": "keep",
        }
        normalized = alpha_radar.normalize_candidate(candidate)
        self.assertEqual(normalized, {"symbol": "AAPL", "thesis": "keep"})

    def test_radar_uses_nous_deepseek_with_web_only(self):
        cmd = alpha_radar.research_command()
        self.assertEqual(cmd[cmd.index("--provider") + 1], "nous")
        self.assertEqual(cmd[cmd.index("-m") + 1], "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(cmd[cmd.index("-t") + 1], "web")
        self.assertNotIn("x_search", cmd)
        self.assertEqual(cmd[-2:], ["--query-file", "-"])

    def test_radar_emits_a_structured_sanitized_success_decision(self):
        self.assertEqual(alpha_radar.decision_line({"symbol":"AAPL","thesis":"private"}),"DECISION candidate_qualified AAPL")

    def test_outcomes_compute_excess_return(self):
        row=candidate_outcomes.measure({"entry_price":100,"spy_entry":500,"prices":{"1":102},"spy_prices":{"1":505}})
        self.assertAlmostEqual(row["return_1s_pct"],2.0)
        self.assertAlmostEqual(row["excess_1s_pct"],1.0)

    def test_dashboard_excludes_sensitive_fields_and_counts_reviews(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"public").mkdir()
            (root/"order_ledger.jsonl").write_text(json.dumps({"status":"rejected","reason":"model_disagreement","broker_order_id":"secret","timestamp":"x"})+"\n")
            (root/"trade_journal.jsonl").write_text("")
            (root/"candidate_outcomes.jsonl").write_text(json.dumps({"traded":False,"excess_5s_pct":1.2})+"\n")
            data=public_dashboard.build_data(root)
            blob=json.dumps(data)
            self.assertNotIn("broker_order_id",blob)
            self.assertEqual(data["reviews"]["disagreements"],1)
            self.assertEqual(data["performance"]["avg_excess_5s_pct"],1.2)

    def test_dashboard_explains_simplified_workflow_blockers(self):
        expected_codes = {
            "invalid_horizon",
            "horizon_session_mismatch",
            "trading_calendar_unavailable",
            "proposal_hash_mismatch",
            "malformed_review",
            "low_confidence",
            "reviewer_veto",
            "planned_risk_policy_missing",
            "planned_risk_exceeded",
            "technical_bars_unavailable",
            "unsupported_technical_setup",
        }
        self.assertTrue(expected_codes.issubset(public_dashboard.ACTIVITY_SUMMARIES))
        for code in expected_codes:
            self.assertNotIn("sanitized desk lifecycle event", public_dashboard.activity_summary({"reason": code}).lower())

    def test_dashboard_counts_current_immutable_review_blockers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [
                {"status": "rejected", "reason": reason, "timestamp": "x"}
                for reason in ("proposal_hash_mismatch", "malformed_review", "low_confidence", "reviewer_veto")
            ]
            (root / "order_ledger.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            data = public_dashboard.build_data(root)
        self.assertEqual(data["reviews"]["total_dual_model_reviews"], 4)
        self.assertEqual(len(data["blocked_disagreements"]), 4)

    def test_dashboard_exposes_only_sanitized_decision_audit_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"decision_audit.jsonl").write_text(json.dumps({"timestamp":"x","mode":"radar","stage":"research","decision":"candidate_qualified","symbol":"AAPL","reason":"ok","private_prompt":"secret"})+"\n")
            data=public_dashboard.build_data(root)
        self.assertEqual(data["decision_audit"],[{"timestamp":"x","mode":"radar","stage":"research","decision":"candidate_qualified","symbol":"AAPL","reason":"ok","summary":"The candidate passed the desk's initial research-quality checks and advanced to independent review."}])
        self.assertNotIn("private_prompt",json.dumps(data))

    def test_dashboard_html_renders_the_decision_audit(self):
        html=public_dashboard.html_template()
        self.assertIn("Decision log",html)
        self.assertIn("d.decision_audit",html)

    def test_dashboard_activity_has_today_default_and_requested_date_filters(self):
        html=public_dashboard.html_template()
        self.assertIn('id="activity-range"',html)
        self.assertIn('<option value="today" selected>Today</option>',html)
        for value,label in (("24h","Last 24 hours"),("5d","Last 5 days"),("week","Last week"),("month","Last month"),("year","Last year"),("all","All"),("custom","Custom dates")):
            self.assertIn(f'<option value="{value}">{label}</option>',html)
        self.assertIn('type="date" id="activity-from"',html)
        self.assertIn('type="date" id="activity-to"',html)
        self.assertIn("const activityMatchesRange=",html)
        self.assertNotIn("rows.slice(-6)",html)

    def test_dashboard_activity_reasons_are_expandable(self):
        html=public_dashboard.html_template()
        self.assertIn('<details class="event-reason">',html)
        self.assertIn('<summary>Why?</summary>',html)
        self.assertIn("row.summary",html)

    def test_dashboard_has_expandable_researched_candidate_card(self):
        html=public_dashboard.html_template()
        self.assertIn('class="panel candidate-card"',html)
        self.assertIn('<span>View researched candidates</span>',html)
        self.assertIn('id="candidate-events"',html)
        self.assertIn("candidateRows(d.researched_candidates||[])",html)

    def test_dashboard_has_separate_review_order_filters(self):
        html=public_dashboard.html_template()
        self.assertIn('id="order-status-filter"',html)
        self.assertIn('<option value="approved">Approved</option>',html)
        self.assertIn('<option value="rejected">Rejected</option>',html)
        self.assertIn('id="order-reason-filter"',html)
        self.assertIn("const orderMatchesFilters=",html)
        self.assertIn("populateOrderReasonFilter",html)

    def test_dashboard_summarizes_traded_and_skipped_outcomes_by_horizon(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            outcomes=[
                {"candidate_id":"a","traded":True,"excess_1s_pct":2.0,"excess_5s_pct":4.0},
                {"candidate_id":"b","traded":False,"excess_1s_pct":-1.0,"excess_5s_pct":2.0},
            ]
            (root/"candidate_outcomes.jsonl").write_text("\n".join(json.dumps(row) for row in outcomes)+"\n")
            data=public_dashboard.build_data(root)
        self.assertEqual(data["outcome_horizons"]["1"]["traded"],{"count":1,"avg_excess_pct":2.0})
        self.assertEqual(data["outcome_horizons"]["1"]["skipped"],{"count":1,"avg_excess_pct":-1.0})
        self.assertEqual(data["outcome_horizons"]["3"]["traded"],{"count":0,"avg_excess_pct":None})

    def test_dashboard_exposes_only_safe_researched_candidate_details(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            candidate={
                "candidate_id":"private-id","symbol":"AAPL","researched_at":"2026-09-02T14:00:00Z",
                "price":100,"thesis":"private thesis","catalyst":"private catalyst",
                "sources":[{"url":"https://private.example"}],"dossier_hash":"private-hash",
            }
            (root/"candidates.jsonl").write_text(json.dumps(candidate)+"\n")
            data=public_dashboard.build_data(root)
        self.assertEqual(data["researched_candidates"],[{
            "timestamp":"2026-09-02T14:00:00Z","symbol":"AAPL",
            "summary":"Passed the desk's initial research-quality and source-verification checks.",
        }])
        self.assertNotIn("private",json.dumps(data))

    def test_dashboard_exposes_only_safe_operating_limits(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            config={"enabled":True,"broker_mode":"paper","account_cap_usd":10000,"max_position_usd":125,"max_daily_orders":2,"min_reward_risk":2.0,"kill_switch_path":"/private/path","research_model":{"model":"private"}}
            (root/"autonomy_config.json").write_text(json.dumps(config))
            data=public_dashboard.build_data(root)
        self.assertEqual(data["desk_status"],{"enabled":True,"broker_mode":"paper","account_cap_usd":10000,"max_position_usd":125,"max_daily_orders":2,"min_reward_risk":2.0})
        self.assertNotIn("kill_switch",json.dumps(data))
        self.assertNotIn("research_model",json.dumps(data))

    def test_dashboard_drops_private_candidate_outcome_details(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            row={"candidate_id":"a","symbol":"AAPL","traded":False,"excess_5s_pct":1.2,"thesis":"private thesis","sources":[{"url":"private"}],"dossier_hash":"private"}
            (root/"candidate_outcomes.jsonl").write_text(json.dumps(row)+"\n")
            data=public_dashboard.build_data(root)
        self.assertEqual(data["outcomes"],[{"candidate_id":"a","symbol":"AAPL","traded":False,"excess_5s_pct":1.2}])
        self.assertNotIn("private thesis",json.dumps(data))

    def test_dashboard_surfaces_ticker_in_review_log_from_nested_reviews(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            row={"evidence_id":"x","status":"rejected","reason":"consensus_hold","timestamp":"t","reviews":[{"action":"HOLD","symbol":"NVDA"},{"action":"HOLD","symbol":"NVDA"}]}
            (root/"order_ledger.jsonl").write_text(json.dumps(row)+"\n")
            data=public_dashboard.build_data(root)
        self.assertEqual(data["recent_orders"],[{"evidence_id":"x","status":"rejected","reason":"consensus_hold","timestamp":"t","symbol":"NVDA","summary":"Both reviewers independently chose to hold, so the desk submitted no order."}])
        self.assertNotIn("reviews",json.dumps(data["recent_orders"]))

    def test_dashboard_publishes_all_activity_with_safe_summary_reasons(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            audit_rows=[
                {"timestamp":f"2026-09-01T00:{i:02d}:00Z","mode":"radar","stage":"schedule","decision":"skipped","reason":"outside_window"}
                for i in range(60)
            ] + [
                {"timestamp":f"2026-09-02T00:{i:02d}:00Z","mode":"radar","stage":"research","decision":"candidate_qualified","symbol":"AAPL"}
                for i in range(60)
            ]
            order_rows=[
                {"timestamp":f"2026-09-02T01:{i:02d}:00Z","status":"rejected","reason":"consensus_hold","reviews":[{"symbol":"NVDA","private":"secret"}]}
                for i in range(60)
            ]
            (root/"decision_audit.jsonl").write_text("\n".join(json.dumps(row) for row in audit_rows)+"\n")
            (root/"order_ledger.jsonl").write_text("\n".join(json.dumps(row) for row in order_rows)+"\n")
            data=public_dashboard.build_data(root)
        self.assertEqual(len(data["decision_audit"]),120)
        self.assertEqual(len(data["recent_orders"]),60)
        self.assertEqual(data["decision_audit"][0]["summary"],"The scheduled cycle was outside its permitted market window, so no review or order ran.")
        self.assertEqual(data["decision_audit"][-1]["summary"],"The candidate passed the desk's initial research-quality checks and advanced to independent review.")
        self.assertEqual(data["recent_orders"][0]["summary"],"Both reviewers independently chose to hold, so the desk submitted no order.")
        self.assertNotIn("private",json.dumps(data))

    def test_dashboard_deploy_supports_cached_vercel_cli_login(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"public").mkdir()
            (root/"public_dashboard.py").write_text("raise SystemExit(0)\n")
            (root/"deploy_dashboard.sh").write_text((Path(__file__).parents[1]/"deploy_dashboard.sh").read_text())
            fake_bin=root/"bin"; fake_bin.mkdir()
            fake_npx=fake_bin/"npx"
            fake_npx.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > \"$NPX_LOG\"\n")
            fake_npx.chmod(0o755)
            env=os.environ.copy(); env.pop("VERCEL_TOKEN",None)
            env["PATH"]=f"{fake_bin}:{env['PATH']}"; env["NPX_LOG"]=str(root/"npx.log")
            result=subprocess.run(["bash",str(root/"deploy_dashboard.sh")],env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn("--token",(root/"npx.log").read_text() if (root/"npx.log").exists() else "")

    def test_dashboard_html_has_glanceable_sections_without_raw_json_dumps(self):
        html=public_dashboard.html_template()
        for label in ("Desk status","Decision funnel","Candidate outcomes","Recent activity","How to read this desk"):
            self.assertIn(label,html)
        self.assertNotIn("<pre>",html)
        self.assertIn("aria-label=\"Tradey Desk dashboard\"",html)

if __name__ == "__main__": unittest.main()
