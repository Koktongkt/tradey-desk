import json
import datetime as dt
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import alpha_radar
import candidate_outcomes
import public_dashboard
import run_cycle


class PipelineTests(unittest.TestCase):
    def test_publication_budget_reaches_research_child_only_with_audit_and_single_attempt(self):
        parent=Path(__file__).resolve().parents[1]/'test_artifacts/publication-hybrid/task4'
        parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with tempfile.TemporaryDirectory(dir=parent) as td:
            for mode,timeout,stage,child in [('premarket',720,'research','alpha_radar.py'),
                    ('radar',720,'research','alpha_radar.py'),('autotrader',600,'execution','autotrader.py')]:
                with self.subTest(mode=mode),patch.object(run_cycle,'ROOT',Path(td)),patch.object(sys,'argv',['offline',mode]),patch.object(run_cycle,'scheduled_slot',return_value=True),patch.object(run_cycle,'in_window',return_value=True),patch.object(run_cycle,'completed_today',return_value=False),patch.object(run_cycle,'mark_completed') as complete,patch.object(run_cycle,'execute',return_value=0) as execute:
                    self.assertEqual(run_cycle.main(),0)
                    execute.assert_called_once_with([sys.executable,str(Path(td)/child)],
                        timeout_seconds=timeout,attempts=1,audit_mode=mode,audit_stage=stage)
                    self.assertEqual(complete.call_count,1 if mode=='premarket' else 0)

    def test_radar_rejects_unknown_or_malformed_earnings_before_qualification(self):
        base={
            "symbol":"AAPL","price":100,"spy_price":500,"instrument_type":"cash_equity",
            "sources":[{"url":"https://one.example/a"},{"url":"https://two.example/b"}],
            "researched_at":"2026-09-05T14:00:00Z","setup_type":"post_news_momentum",
            "planned_exit_at":"2026-09-18T20:00:00Z","horizon_rationale":"repricing window",
        }
        cfg={"min_price_usd":10,"max_position_usd":500,"earnings_blackout_sessions":2}
        now=dt.datetime(2026,9,5,14,0,tzinfo=dt.timezone.utc)
        for event in (None,"unknown","2026-11-01T21:00:00"):
            self.assertFalse(alpha_radar.qualified({**base,"earnings_event_at":event},cfg,now=now))

    def test_radar_rejects_obvious_earnings_blackout_before_qualification(self):
        candidate={
            "symbol":"AAPL","price":100,"spy_price":500,"instrument_type":"cash_equity",
            "sources":[{"url":"https://one.example/a"},{"url":"https://two.example/b"}],
            "earnings_event_at":"2026-09-08T20:00:00Z","researched_at":"2026-09-04T14:00:00Z",
            "setup_type":"event_momentum","planned_exit_at":"2026-09-18T20:00:00Z",
            "horizon_rationale":"event repricing window",
        }
        cfg={"min_price_usd":10,"max_position_usd":500,"earnings_blackout_sessions":2}
        friday=dt.datetime(2026,9,4,14,0,tzinfo=dt.timezone.utc)
        self.assertFalse(alpha_radar.qualified(candidate,cfg,now=friday))

    def test_radar_accepts_verified_past_earnings_calendar_date(self):
        candidate={
            "symbol":"GME","price":25,"spy_price":500,"instrument_type":"cash_equity",
            "sources":[{"url":"https://www.sec.gov/a"},{"url":"https://news.example/b"}],
            "earnings_event_at":"2026-09-08","researched_at":"2026-09-10T12:32:00Z",
            "setup_type":"post_earnings_drift","planned_exit_at":"2026-09-18T20:00:00Z",
            "horizon_rationale":"post-report repricing window",
        }
        cfg={"min_price_usd":10,"max_position_usd":500,"earnings_blackout_sessions":2}
        now=dt.datetime(2026,9,10,12,32,tzinfo=dt.timezone.utc)
        self.assertTrue(alpha_radar.qualified(candidate,cfg,now=now))

    def test_candidate_preflight_types_earnings_dead_ends(self):
        cases = (
            ("unknown", {}, (2026, 9, 4, 14, 0), ["earnings_unknown"]),
            ("near_term_timestamp", {"earnings_event_at": "2026-09-08T20:00:00Z"},
             (2026, 9, 4, 14, 0), ["near_term_earnings"]),
            ("date_only_today", {"earnings_event_at": "2026-09-10"},
             (2026, 9, 10, 12, 32), ["near_term_earnings"]),
            ("holding_period_plus_blackout_buffer", {
                "planned_exit_at": "2026-09-25T20:00:00Z",
                "earnings_event_at": "2026-09-29", "earnings_date_status": "estimated",
             }, (2026, 9, 11, 14, 0), ["near_term_earnings"]),
        )
        for label, changes, clock, expected in cases:
            with self.subTest(case=label):
                candidate = {"price": 100, "setup_type": "breakout",
                             "planned_exit_at": "2026-09-18T20:00:00Z", **changes}
                cfg = {"max_position_usd": 500, "allow_fractional_shares": False,
                       "earnings_blackout_sessions": 2}
                now = dt.datetime(*clock, tzinfo=dt.timezone.utc)
                self.assertEqual(alpha_radar.candidate_preflight(candidate, cfg, now), expected)

    def test_research_prompt_prioritizes_evidence_backed_past_or_future_earnings_date(self):
        cfg={"max_position_usd":500,"allow_fractional_shares":False,"earnings_blackout_sessions":2}
        for prompt in (alpha_radar.research_prompt(cfg),alpha_radar.synthesis_prompt("",[],cfg)):
            prompt=prompt.lower()
            self.assertNotIn("pre- or post-earnings",prompt)
            self.assertNotIn('return {"status":"none","none_reason":"earnings_timestamp_unverified"}',prompt)
            self.assertIn("deterministic trusted sources recheck and override it",prompt)
            self.assertIn("deterministic code then resolves or estimates the date itself",prompt)
            self.assertNotIn("use that evidence-backed date directly",prompt)
            self.assertIn("do not decline solely because an earnings date is unavailable",prompt)

    def test_candidate_preflight_rejects_price_horizon_and_setup_dead_ends(self):
        base={
            "price":100,"setup_type":"breakout","planned_exit_at":"2026-09-18T20:00:00Z",
            "earnings_event_at":"2026-11-01T21:00:00Z",
        }
        cfg={"max_position_usd":500,"allow_fractional_shares":False}
        now=dt.datetime(2026,9,4,14,0,tzinfo=dt.timezone.utc)
        self.assertEqual(alpha_radar.candidate_preflight({**base,"price":500.01},cfg,now),["whole_share_unaffordable"])
        self.assertEqual(alpha_radar.candidate_preflight({**base,"planned_exit_at":"2026-10-30T20:00:00Z"},cfg,now),["invalid_horizon","near_term_earnings"])
        self.assertEqual(alpha_radar.candidate_preflight({**base,"setup_type":"strategic_rerating","planned_exit_at":"2026-09-08T20:00:00Z"},cfg,now),["unsupported_technical_setup"])
        self.assertEqual(alpha_radar.candidate_preflight(base,cfg,now),[])

    def test_candidate_preflight_classifies_exit_date_in_exchange_timezone(self):
        candidate={
            "price":100,"setup_type":"strategic_rerating",
            "planned_exit_at":"2026-09-14T00:30:00Z",
            "earnings_event_at":"2026-11-01T21:00:00Z",
        }
        cfg={"max_position_usd":500,"allow_fractional_shares":False}
        now=dt.datetime(2026,9,4,14,0,tzinfo=dt.timezone.utc)
        self.assertEqual(alpha_radar.candidate_preflight(candidate,cfg,now),["unsupported_technical_setup"])

    def test_research_prompt_exposes_whole_share_risk_and_setup_horizon_policy(self):
        prompt=alpha_radar.research_prompt({
            "max_position_usd":500,"allow_fractional_shares":False,
            "max_planned_risk_per_trade_usd":40,"earnings_blackout_sessions":2,
        }).lower()
        self.assertIn("$40",prompt)
        self.assertIn("estimate_revision",prompt)
        self.assertIn("6–30",prompt)

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

    def test_radar_rejects_candidate_when_one_share_exceeds_position_cap(self):
        candidate={
            "symbol":"COST","price":500.01,"spy_price":500,"instrument_type":"cash_equity",
            "sources":[{"url":"https://one.example/a"},{"url":"https://two.example/b"}],
            "earnings_event_at":"2026-11-01T21:00:00Z","researched_at":"2026-08-29T14:00:00Z",
            "setup_type":"post_news_momentum","planned_exit_at":"2026-09-04T20:00:00Z",
            "horizon_rationale":"short repricing window",
        }
        cfg={"min_price_usd":10,"max_position_usd":500,"allow_fractional_shares":False}
        self.assertFalse(alpha_radar.qualified(candidate,cfg))

    def test_research_prompt_does_not_request_unproven_average_volume(self):
        self.assertNotIn("average_volume", alpha_radar.research_prompt())

    def test_research_prompt_excludes_stocks_above_the_whole_share_cap(self):
        prompt = alpha_radar.research_prompt({"max_position_usd": 500, "allow_fractional_shares": False})
        self.assertIn("one whole share must cost no more than $500", prompt.lower())

    def test_research_prompt_requests_date_not_model_counted_sessions(self):
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

    def test_radar_uses_configured_default_model_with_web_only(self):
        with patch.object(alpha_radar,"configured_default_model",return_value=("future-provider","future/model")):
            cmd = alpha_radar.research_command()
        self.assertEqual(cmd[cmd.index("--provider") + 1], "future-provider")
        self.assertEqual(cmd[cmd.index("-m") + 1], "future/model")
        self.assertEqual(cmd[cmd.index("-t") + 1], "search")
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

    def test_dashboard_projects_live_portfolio_without_account_identifiers(self):
        snapshot = {
            "captured_at": "2026-09-14T14:00:00Z",
            "feed": "alpaca_paper_iex",
            "summary": {
                "day_pl_usd": 20.2, "day_return_pct": 0.2021,
                "spy_day_return_pct": -0.1, "day_excess_pct": 0.3021,
                "private_equity": 10014.87,
            },
            "holdings": [{
                "symbol": "ZS", "quantity": 3, "average_entry_price": 162.79,
                "current_price": 171.273, "market_value": 513.819,
                "cost_basis": 488.37, "unrealized_pl_usd": 25.449,
                "unrealized_return_pct": 5.211, "day_pl_usd": 20.199,
                "day_return_pct": 4.092, "asset_id": "private-id",
            }],
            "account_number": "private-number",
        }
        with tempfile.TemporaryDirectory() as td:
            data = public_dashboard.build_data(Path(td), portfolio_snapshot=snapshot)
        self.assertEqual(data["live_portfolio"]["summary"], {
            "total_balance_usd": None, "cash_usd": None, "positions_value_usd": None,
            "balance_reconciliation_difference_usd": None,
            "day_pl_usd": 20.2, "day_return_pct": 0.2021,
            "spy_day_return_pct": -0.1, "day_excess_pct": 0.3021,
        })
        self.assertEqual(data["live_portfolio"]["holdings"][0]["symbol"], "ZS")
        blob = json.dumps(data["live_portfolio"])
        self.assertNotIn("account_number", blob)
        self.assertNotIn("asset_id", blob)
        self.assertNotIn("private_equity", blob)

    def test_dashboard_balance_flows_from_broker_to_public_render(self):
        import asyncio
        import broker_mcp_bridge

        cases = (
            ("balance", {"equity": "10100.12", "cash": "9800.12", "long_market_value": "320", "short_market_value": "-20"}, (10100.12, 9800.12, 300.0, 0.0), ("$10,100.12", "$9,800.12", "$300.00")),
            ("difference", {"equity": 100, "cash": 50, "long_market_value": 40, "short_market_value": 0}, (100.0, 50.0, 40.0, 10.0), ("$100.00", "$50.00", "$40.00", "+$10.00")),
            ("zero", {"equity": 0, "cash": 0, "long_market_value": 0, "short_market_value": 0}, (0.0, 0.0, 0.0, 0.0), ("$0.00",)),
            ("missing", {}, (None, None, None, None), ("—", "Reconciliation unavailable")),
        )
        for label, account, expected, displayed in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as td:
                class BalanceAlpaca:
                    async def call(self, name, values=None):
                        return {"get_account_info": {"account": {"id": "private-account", "buying_power": "90000", **account}}, "get_all_positions": [{"symbol": "FILTERED", "market_value": 999999}], "get_stock_snapshot": {}}[name]
                snapshot = asyncio.run(broker_mcp_bridge.operation(BalanceAlpaca(), "portfolio", {}))
                snapshot["summary"]["private_prompt"] = "private-secret"
                root = Path(td)
                (root / "autonomy_config.json").write_text(json.dumps({"account_cap_usd": 500}))
                data = public_dashboard.build_data(root, portfolio_snapshot=snapshot)
                summary = data["live_portfolio"]["summary"]
                self.assertIn("total_balance_usd", summary)
                self.assertEqual(tuple(summary[key] for key in ("total_balance_usd", "cash_usd", "positions_value_usd", "balance_reconciliation_difference_usd")), expected)
                blob = json.dumps(data, allow_nan=False)
                self.assertNotIn("private", blob)
                self.assertNotIn("buying_power", blob)
                script = public_dashboard.html_template().split("<script>", 1)[1].split("</script>", 1)[0]
                harness = "const nodes={};global.document={querySelector:s=>nodes[s]||(nodes[s]={value:'today',innerHTML:'',addEventListener(){},insertAdjacentHTML(){}})};global.fetch=async()=>({ok:true,json:async()=>(" + blob + ")});\n" + script + "\nsetImmediate(()=>console.log(nodes['#app'].innerHTML));"
                rendered = subprocess.run(["node", "-e", harness], text=True, capture_output=True, check=True).stdout
                for text in ("Current balance", "Cash", "Positions value", "Broker account equity", "not the managed exposure cap", "Managed exposure cap", "Snapshot", *displayed):
                    self.assertIn(text, rendered)
                self.assertNotIn("private", rendered)
                self.assertLess(rendered.index("Current balance"), rendered.index("Live portfolio vs SPY"))
                self.assertIn("grid-template-columns:1fr", public_dashboard.html_template())
                self.assertIn(snapshot["captured_at"], rendered)

    def test_dashboard_balance_sanitization_rejects_non_numeric_payloads(self):
        keys = ("total_balance_usd", "cash_usd", "positions_value_usd", "balance_reconciliation_difference_usd")
        for value in (None, "", "100", "bad", float("nan"), float("inf"), float("-inf"), True, False, {"secret": "private-secret"}, ["private-secret"]):
            with self.subTest(value=value):
                safe = public_dashboard.sanitize_portfolio_snapshot({"summary": dict.fromkeys(keys, value)})
                for key in keys:
                    self.assertIsNone(safe["summary"][key])
                self.assertNotIn("private", json.dumps(safe, allow_nan=False))
        for snapshot in (None, {}, {"summary": []}):
            with self.subTest(snapshot=snapshot):
                safe = public_dashboard.sanitize_portfolio_snapshot(snapshot)
                self.assertEqual({key: safe["summary"].get(key, "missing") for key in keys}, dict.fromkeys(keys))

    def test_dashboard_html_shows_live_holdings_and_spy_comparison(self):
        html = public_dashboard.html_template()
        self.assertIn("Live portfolio vs SPY", html)
        self.assertIn("Current Alpaca holdings", html)
        self.assertIn("d.live_portfolio", html)
        self.assertIn("day_excess_pct", html)
        self.assertIn("portfolioRows", html)

    def test_dashboard_live_portfolio_uses_pinned_bridge_runtime(self):
        completed=subprocess.CompletedProcess([],0,json.dumps({"summary":{},"holdings":[]}),"")
        with patch.dict("os.environ", {"HOME": "/offline-home"}, clear=True), patch("public_dashboard.subprocess.run",return_value=completed) as run:
            public_dashboard.fetch_live_portfolio(Path("/desk"))
        command=run.call_args.args[0]
        self.assertEqual(command[:5],["/offline-home/.local/bin/uv","run","--with","fastmcp<4","python"])
        self.assertEqual(command[-2:], ["/desk/broker_mcp_bridge.py","portfolio"])

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

    def test_dashboard_nests_matching_diagnostics_in_rejected_order_events(self):
        html=public_dashboard.html_template()
        self.assertIn("const attachBlockerDiagnostics=",html)
        self.assertIn('class="event-diagnostics"',html)
        self.assertIn('<summary>Blocker details</summary>',html)
        self.assertIn("eventRows(orders)",html)
        self.assertNotIn('id="diagnostic-events"',html)
        self.assertNotIn('<h3>Blocker details</h3>',html)

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
        private="token=secret account_id=acct project_id=prj order_id=ord https://private.invalid /private/path"
        cases=(("cached",0,0,None,""),("token",0,0,"fixture-secret",""),
               ("build",1,0,None,"dashboard_build_failed"),
               ("deploy",0,1,None,"dashboard_deploy_failed"))
        for label,build_rc,deploy_rc,token,expected in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as td:
                root=Path(td)
                (root/"public").mkdir()
                (root/"public_dashboard.py").write_text(f"import sys\nprint({private!r},file=sys.stderr)\nraise SystemExit({build_rc})\n")
                source=Path(__file__).parents[1]
                for name in ("deploy_dashboard.sh","dashboard_deployment.py","dashboard_process.py","broker_supervisor.py","run_cycle.py","durable_jsonl.py"):
                    if (source/name).exists():(root/name).write_text((source/name).read_text())
                fake_bin=root/"bin"; fake_bin.mkdir()
                fake_npx=fake_bin/"npx"
                fake_npx.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > \"$NPX_LOG\"\nprintf '%s\\n' '{private}' >&2\nexit {deploy_rc}\n")
                fake_npx.chmod(0o755)
                env=os.environ.copy(); env.pop("VERCEL_TOKEN",None)
                if token:env["VERCEL_TOKEN"]=token
                env["PATH"]=f"{fake_bin}:{env['PATH']}"; env["NPX_LOG"]=str(root/"npx.log")
                result=subprocess.run(["bash",str(root/"deploy_dashboard.sh")],env=env,text=True,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,1 if expected else 0)
                self.assertEqual(result.stdout,f"SYSTEM_FAILURE {expected}\n" if expected else "")
                self.assertEqual(result.stderr,"")
                if build_rc==0:
                    args=(root/"npx.log").read_text()
                    self.assertIn("--package=vercel@63.1.2",args)
                    self.assertEqual("--token" in args,bool(token))
                diagnostics=root/"private"/"dashboard_deploy_diagnostics"
                self.assertEqual(diagnostics.stat().st_mode & 0o777,0o700)
                records=list(diagnostics.glob("attempt-*.json"))
                self.assertEqual(len(records),1 if build_rc else 2)
                for record in records:
                    self.assertEqual(record.stat().st_mode & 0o777,0o600)
                    text=record.read_text()
                    for unsafe in ("secret","acct","prj","ord","https://","/private/"):
                        self.assertNotIn(unsafe,text)
                    row=json.loads(text)
                    self.assertIn(row["stage"],("build","deploy"))
                    self.assertIn("duration_ms",row)
                    self.assertIn("classification",row)

    def test_dashboard_classified_retries_and_deadlines_are_offline(self):
        import dashboard_deployment as deployment
        cases=(
            ("auth","Error: invalid token",False,False,"dashboard_deploy_auth",1),
            ("auth over transient","Error: invalid token HTTP 503",False,False,"dashboard_deploy_auth",1),
            ("vercel token","Error: The specified token is not valid",False,False,"dashboard_deploy_auth",1),
            ("cached login absent","Error: No existing credentials found. Please run vercel login",False,False,"dashboard_deploy_auth",1),
            ("config","Error: project not found",False,False,"dashboard_deploy_config",1),
            ("vercel project","Error: The specified project does not exist",False,False,"dashboard_deploy_config",1),
            ("remote build","Error: build failed",False,False,"dashboard_deploy_build",1),
            ("unknown","private unknown",False,False,"dashboard_deploy_failed",1),
            ("network","Error: ECONNRESET",True,False,"",2),
            ("rate limit","Error: HTTP 429",True,False,"",2),
            ("service","Error: HTTP 503",False,False,"dashboard_deploy_service",3),
            ("deploy timeout","",False,True,"dashboard_deploy_timeout",3),
            ("build timeout","",False,True,"dashboard_build_timeout",0),
        )
        for label,message,recover,hang,expected,count in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as td:
                root=Path(td); (root/"public").mkdir()
                build="import time; time.sleep(2)" if label=="build timeout" else "raise SystemExit(0)"
                (root/"public_dashboard.py").write_text(build)
                fake_bin=root/"bin";fake_bin.mkdir()
                fake=fake_bin/"npx"
                fake.write_text("#!/usr/bin/env python3\nimport os,time\nfrom pathlib import Path\np=Path(os.environ['COUNT_FILE'])\nn=int(p.read_text())+1 if p.exists() else 1\np.write_text(str(n))\n"
                                +("time.sleep(2)\n" if hang else "")
                                +f"print({message!r})\nraise SystemExit(0 if {recover!r} and n>1 else 1)\n")
                fake.chmod(0o755)
                env={"PATH":f"{fake_bin}:{os.environ['PATH']}","COUNT_FILE":str(root/"count")}
                output=__import__("io").StringIO()
                with patch.dict(os.environ,env), patch.object(deployment,"ATTEMPT_TIMEOUT",0.15), patch.object(deployment,"TOTAL_BUDGET",2), patch.object(deployment,"BACKOFFS",(0.01,0.02),create=True), patch("sys.stdout",output):
                    rc=deployment.deploy(root)
                self.assertEqual(output.getvalue(),f"SYSTEM_FAILURE {expected}\n" if expected else "")
                self.assertEqual(rc,1 if expected else 0)
                self.assertEqual(int((root/"count").read_text()) if (root/"count").exists() else 0,count)
                rows=[json.loads(p.read_text()) for p in (root/"private"/"dashboard_deploy_diagnostics").glob("attempt-*.json")]
                self.assertEqual(len(rows),count+1)
                if expected:
                    self.assertTrue(any(row["classification"]!="success" for row in rows))
                    self.assertEqual(run_cycle.parse_failure_event(output.getvalue()),output.getvalue().rstrip("\n"))

    def test_dashboard_diagnostics_io_privacy_retention_and_subprocess_bounds(self):
        import dashboard_deployment as deployment
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);outside=root/"outside";outside.mkdir()
            (root/'private').mkdir()
            private=root/"private"/"dashboard_deploy_diagnostics"
            private.symlink_to(outside,target_is_directory=True)
            deployment.record_attempt(root,"deploy",1,1,0.1,"failed")
            self.assertEqual(list(outside.iterdir()),[])
            private.unlink()
            for attempt in range(45):deployment.record_attempt(root,"deploy",attempt,1,0.1,"failed")
            self.assertEqual(len(list(private.glob("attempt-*.json"))),30)
            sentinel=outside/"sentinel";sentinel.write_text("unchanged")

            (private/("attempt-0-"+"a"*32+".json")).symlink_to(sentinel)
            deployment.record_attempt(root,"deploy",1,1,0.1,"failed")
            self.assertEqual(sentinel.read_text(),"unchanged")
            (private/("attempt-0-"+"a"*32+".json")).unlink()
            for record in private.iterdir():record.unlink()
            private.rmdir();private.write_text("not a directory")
            deployment.record_attempt(root,"deploy",1,1,0.1,"failed")
            self.assertEqual(private.read_text(),"not a directory")
            private.unlink()
            for build_rc in (0,1):
                (root/"public_dashboard.py").write_text(f"raise SystemExit({build_rc})")
                output=__import__("io").StringIO()
                with patch.object(deployment,"record_attempt",side_effect=OSError("secret /private/path")), patch.object(deployment,"run_attempt",return_value=subprocess.CompletedProcess([],build_rc,"private", ""),create=True), patch("sys.stdout",output):
                    self.assertEqual(deployment.deploy(root),build_rc)
                self.assertEqual(output.getvalue(),"SYSTEM_FAILURE dashboard_build_failed\n" if build_rc else "")
            runner=getattr(deployment,"run_attempt",None)
            self.assertTrue(callable(runner),"deadline/output bounded helper subprocess runner missing")
            result=runner([sys.executable,"-c","print('x'*200000)"],root,1)
            self.assertEqual(result.returncode,0)
            self.assertLessEqual(len(result.stdout.encode()),65536)
            result=runner([sys.executable,"-c","import time;time.sleep(5)"],root,0.05)
            self.assertEqual(result.returncode,124)
            result=runner([sys.executable,"-c","import sys;print('Error: invalid token');print('x'*200000);print('Error: HTTP 503');sys.exit(1)"],root,1)
            self.assertEqual(deployment.classify("deploy",result),"auth")
            with patch.object(deployment,"TOTAL_BUDGET",0), patch.object(deployment,"run_attempt") as attempt, patch("sys.stdout",__import__("io").StringIO()) as output:
                self.assertEqual(deployment.deploy(root),1)
            attempt.assert_not_called()
            self.assertEqual(output.getvalue(),"SYSTEM_FAILURE dashboard_build_timeout\n")
            with patch.object(deployment,"TOTAL_BUDGET",1), patch.object(deployment,"run_attempt",side_effect=[subprocess.CompletedProcess([],0,"",""),subprocess.CompletedProcess([],1,"HTTP 503","")]) as attempt, patch("sys.stdout",__import__("io").StringIO()) as output:
                self.assertEqual(deployment.deploy(root),1)
            self.assertEqual(attempt.call_count,2)  # Build + deploy, no retry beyond shared budget.
            self.assertEqual(output.getvalue(),"SYSTEM_FAILURE dashboard_deploy_service\n")
            missing=runner([str(root/"missing-cli")],root,1)
            self.assertEqual(deployment.classify("deploy",missing),"cli_missing")
            child="import time;from pathlib import Path;time.sleep(0.3);Path('escaped-child').write_text('leaked')"
            parent=f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(5)"
            result=runner([sys.executable,"-c",parent],root,0.1)
            self.assertEqual(result.returncode,124)
            __import__("time").sleep(0.4)
            self.assertFalse((root/"escaped-child").exists())

    def test_dashboard_diagnostics_are_git_ignored_and_unpublished(self):
        import dashboard_deployment as deployment
        import shutil
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shutil.copy2(Path(__file__).parents[1]/'.gitignore', root/'.gitignore')
            subprocess.run(['git','init','-q',str(root)],check=True)
            deployment.record_attempt(root,'deploy',1,1,.1,'config')
            records=list((root/'private/dashboard_deploy_diagnostics').glob('*.json'))
            self.assertEqual(len(records),1)
            self.assertEqual(subprocess.run(['git','check-ignore',str(records[0].relative_to(root))],cwd=root,capture_output=True).returncode,0)
            self.assertNotIn('duration_ms',json.dumps(public_dashboard.build_data(root)))
            self.assertFalse((root/'public/private').exists())
            for directory in (root/'private',records[0].parent):
                self.assertEqual(directory.stat().st_mode & 0o777,0o700)
            self.assertEqual(records[0].stat().st_mode & 0o777,0o600)
            for directory in (root/'private',records[0].parent):
                with tempfile.TemporaryDirectory() as outside:
                    # Refuse each directory component, not just the leaf.
                    import shutil
                    if (root/'private').exists(): shutil.rmtree(root/'private')
                    if directory.name!='private': (root/'private').mkdir()
                    directory.symlink_to(outside,target_is_directory=True)
                    deployment.record_attempt(root,'deploy',1,1,.1,'config')
                    self.assertEqual(list(Path(outside).iterdir()),[])
                    directory.unlink()

    def test_dashboard_html_has_glanceable_sections_without_raw_json_dumps(self):
        html=public_dashboard.html_template()
        for label in ("Desk status","Decision funnel","Candidate outcomes","Recent activity","How to read this desk"):
            self.assertIn(label,html)
        self.assertNotIn("<pre>",html)
        self.assertIn("aria-label=\"Tradey Desk dashboard\"",html)

class DashboardContainmentTests(unittest.TestCase):
    def _wait_ready(self, root):
        import time
        deadline=time.monotonic()+3
        while not (root/'ready').exists() and time.monotonic()<deadline: time.sleep(.01)
        self.assertTrue((root/'ready').exists())

    def _child(self):
        return "import os,signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path('ready').write_text(str(os.getpid()));time.sleep(1);Path('escaped').write_text('side effect')"

    def _assert_reaped(self, root):
        import time
        pid=int((root/'ready').read_text())
        deadline=time.monotonic()+1
        while Path(f'/proc/{pid}').exists() and time.monotonic()<deadline: time.sleep(.01)
        try:
            self.assertFalse(Path(f'/proc/{pid}').exists(),'owned child not reaped')
            time.sleep(1.1)
            self.assertFalse((root/'escaped').exists())
        finally:
            try: os.kill(pid,9)
            except ProcessLookupError: pass

    def _helper(self, root):
        import dashboard_deployment as deployment
        source=str(Path(deployment.__file__).parent)
        # Detached grandchild ignores TERM and closes every inherited pipe.
        parent=f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{self._child()!r}],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);time.sleep(5)"
        return [sys.executable,'-c',f"import sys;sys.path.insert(0,{source!r});from pathlib import Path;import dashboard_deployment as d;d.run_attempt([sys.executable,'-c',{parent!r}],Path({str(root)!r}),10)"]

    def test_real_execute_outer_timeout_reaps_tree_before_return(self):
        import io
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            # Arm the delayed side effect only after execute returns. A fixed
            # one-second timer from child startup races the execution budget and
            # bounded cleanup on busy workers; pre-return work is not an escape.
            child="import os,signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path('ready').write_text(str(os.getpid()))\nwhile not Path('release').exists(): time.sleep(.005)\ntime.sleep(1);Path('escaped').write_text('side effect')"
            with patch.object(self,'_child',return_value=child):
                command=self._helper(root)
            with patch.object(run_cycle,'ROOT',root),patch.object(run_cycle,'audit_result'),patch('sys.stdout',io.StringIO()) as output:
                rc=run_cycle.execute(command,timeout_seconds=.8,attempts=3,audit_mode='dashboard',audit_stage='deployment')
            self.assertEqual(rc,124)
            self.assertEqual(output.getvalue(),'SYSTEM_FAILURE dashboard_timeout\n')
            self._wait_ready(root)
            try:
                self.assertFalse(Path('/proc/'+(root/'ready').read_text()).exists(),'return preceded reap acknowledgement')
                self.assertFalse((root/'escaped').exists())
            finally:
                (root/'release').touch()
                self._assert_reaped(root)

    def test_helper_term_kill_and_caller_death_stop_detached_children(self):
        import signal
        for sig in (signal.SIGTERM,signal.SIGKILL):
            with self.subTest(signal=sig),tempfile.TemporaryDirectory() as td:
                root=Path(td)
                proc=subprocess.Popen(self._helper(root),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                try:
                    self._wait_ready(root)
                    proc.send_signal(sig);proc.wait(timeout=3)
                    self._assert_reaped(root)
                finally:
                    if proc.poll() is None: proc.kill();proc.wait()

    def test_normal_exit_reaps_closed_pipe_descendants_before_retry(self):
        import dashboard_deployment as deployment
        for detached in (False,True):
            for rc in (0,1):
                with self.subTest(detached=detached,rc=rc),tempfile.TemporaryDirectory() as td:
                    root=Path(td)
                    parent=f"import subprocess,sys,time;from pathlib import Path;subprocess.Popen([sys.executable,'-c',{self._child()!r}],start_new_session={detached!r},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);\nwhile not Path('ready').exists(): time.sleep(.005)\nprint('HTTP 503');sys.exit({rc})"
                    result=deployment.run_attempt([sys.executable,'-c',parent],root,2)
                    self.assertEqual(result.returncode,rc)
                    self.assertFalse(Path('/proc/'+(root/'ready').read_text()).exists(),'return preceded reap acknowledgement')
                    self._assert_reaped(root)
                    # A new attempt cannot overlap any surviving prior process.
                    result=deployment.run_attempt([sys.executable,'-c',f"from pathlib import Path;assert not Path('/proc/'+Path('ready').read_text()).exists()"],root,2)
                    self.assertEqual(result.returncode,0)

    def test_execute_caller_sigkill_stops_detached_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=str(Path(run_cycle.__file__).parent)
            script=f"import sys;sys.path.insert(0,{source!r});from pathlib import Path;import run_cycle as r;r.ROOT=Path({str(root)!r});r.audit_result=lambda *a:None;r.execute({self._helper(root)!r},timeout_seconds=10,audit_mode='dashboard',audit_stage='deployment')"
            proc=subprocess.Popen([sys.executable,'-c',script],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                self._wait_ready(root)
                proc.kill();proc.wait(timeout=3)
                self._assert_reaped(root)
            finally:
                if proc.poll() is None: proc.kill();proc.wait()

    def test_classified_retries_never_overlap_detached_attempts(self):
        import dashboard_deployment as deployment
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'public').mkdir();(root/'public_dashboard.py').write_text('')
            (root/'bin').mkdir()
            fake=root/'bin/npx'
            fake.write_text("#!/usr/bin/env python3\nimport subprocess,sys,time\nfrom pathlib import Path\np=Path('ready')\nif p.exists():\n assert not Path('/proc/'+p.read_text()).exists(), 'overlapping retries'\n p.unlink()\nn=Path('count');i=int(n.read_text())+1 if n.exists() else 1;n.write_text(str(i))\n"+f"subprocess.Popen([sys.executable,'-c',{self._child()!r}],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"+"while not p.exists(): time.sleep(.005)\nprint('HTTP 503')\nsys.exit(1 if i<3 else 0)\n")
            fake.chmod(0o700)
            with patch.dict(os.environ,{'PATH':str(root/'bin')+os.pathsep+os.environ['PATH']}),patch.object(deployment,'BACKOFFS',(.01,.01)):
                self.assertEqual(deployment.deploy(root),0)
            self.assertEqual((root/'count').read_text(),'3')
            self.assertFalse(Path('/proc/'+(root/'ready').read_text()).exists())
            self._assert_reaped(root)

    def test_permission_error_outranks_transient(self):
        import dashboard_deployment as deployment
        for text in ('permission denied HTTP 503','EACCES ECONNRESET'):
            self.assertEqual(deployment.classify('deploy',subprocess.CompletedProcess([],1,text,'')),'config')

if __name__ == "__main__": unittest.main()
