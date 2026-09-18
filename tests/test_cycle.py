import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import run_cycle

class CycleTests(unittest.TestCase):
    def test_market_window_accepts_weekday_open(self):
        now=dt.datetime(2026,8,31,10,0,tzinfo=ZoneInfo("America/New_York"))
        self.assertTrue(run_cycle.in_window("market",now))
    def test_market_window_rejects_weekend(self):
        now=dt.datetime(2026,8,29,10,0,tzinfo=ZoneInfo("America/New_York"))
        self.assertFalse(run_cycle.in_window("market",now))
    def test_postclose_is_narrow(self):
        ok=dt.datetime(2026,8,31,16,30,tzinfo=ZoneInfo("America/New_York"))
        late=dt.datetime(2026,8,31,18,30,tzinfo=ZoneInfo("America/New_York"))
        self.assertTrue(run_cycle.in_window("postclose",ok)); self.assertFalse(run_cycle.in_window("postclose",late))

    def test_dashboard_window_supports_intraday_live_refreshes(self):
        market=dt.datetime(2026,8,31,10,0,tzinfo=ZoneInfo("America/New_York"))
        after_close=dt.datetime(2026,8,31,17,30,tzinfo=ZoneInfo("America/New_York"))
        self.assertTrue(run_cycle.in_window("dashboard",market))
        self.assertTrue(run_cycle.in_window("dashboard",after_close))

    def test_execute_retries_safe_task_and_uses_explicit_timeout(self):
        failed=subprocess.CompletedProcess([],3,"","temporary")
        passed=subprocess.CompletedProcess([],0,"","")
        with patch("run_cycle.subprocess.run",side_effect=[failed,passed]) as call:
            self.assertEqual(run_cycle.execute(["safe"],timeout_seconds=600,attempts=2),0)
        self.assertEqual(call.call_count,2)
        self.assertEqual(call.call_args.kwargs["timeout"],600)

    def test_audit_result_records_only_a_concise_sanitized_decision(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"decision_audit.jsonl"
            run_cycle.audit_result("autotrader","execution",2,"BLOCKER consensus_hold\nprivate detail",path)
            row=json.loads(path.read_text())
        self.assertEqual(row["mode"],"autotrader")
        self.assertEqual(row["stage"],"execution")
        self.assertEqual(row["decision"],"blocked")
        self.assertEqual(row["reason"],"unspecified")
        self.assertNotIn("private detail",json.dumps(row))

    def test_audit_result_records_no_fresh_setup_as_healthy_skip(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"decision_audit.jsonl"
            run_cycle.audit_result("premarket","research",0,"DECISION skipped no_fresh_setup",path)
            row=json.loads(path.read_text())
        self.assertEqual(row["decision"],"skipped")
        self.assertEqual(row["reason"],"no_fresh_setup")

    def test_execute_audits_the_final_result_after_retries(self):
        failed=subprocess.CompletedProcess([],3,"BLOCKER temporary_failure","")
        passed=subprocess.CompletedProcess([],0,"","")
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"decision_audit.jsonl"
            with patch("run_cycle.subprocess.run",side_effect=[failed,passed]):
                rc=run_cycle.execute(["safe"],attempts=2,audit_mode="radar",audit_stage="research",audit_path=path)
            rows=[json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(rc,0)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["decision"],"completed")

    def test_audit_result_accepts_a_structured_success_decision(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"decision_audit.jsonl"
            run_cycle.audit_result("radar","research",0,"DECISION candidate_qualified AAPL",path)
            row=json.loads(path.read_text())
        self.assertEqual(row["decision"],"candidate_qualified")
        self.assertEqual(row["symbol"],"AAPL")

    def test_audit_result_keeps_safe_trade_identity(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"decision_audit.jsonl"
            run_cycle.audit_result("autotrader","execution",0,"TRADE BUY 1 AAPL @ 100.05",path)
            row=json.loads(path.read_text())
        self.assertEqual(row["decision"],"trade_filled")
        self.assertEqual(row["action"],"BUY")
        self.assertEqual(row["symbol"],"AAPL")

    def test_execute_relays_placing_notice_before_submission_confirmation(self):
        text="ORDER placing BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 PAPER\n"
        completed=subprocess.CompletedProcess([],0,text,"")
        with tempfile.TemporaryDirectory() as td:
            audit=Path(td)/"decision_audit.jsonl"
            output=__import__("io").StringIO()
            with patch("run_cycle.subprocess.run",return_value=completed), patch("sys.stdout",output):
                rc=run_cycle.execute(["fixture"],audit_mode="autotrader",audit_stage="execution",audit_path=audit)
            row=json.loads(audit.read_text())
        self.assertEqual(rc,0)
        self.assertEqual(output.getvalue(),"Tradey Autotrader: Placing paper bracket order to Alpaca — BUY 3 ZS at limit $162.79; stop $151.24; target $184.37. This is a placement notice, not confirmation of acceptance or fill.\n")
        self.assertEqual(row["decision"],"order_placed")
        self.assertEqual(row["action"],"BUY")
        self.assertEqual(row["symbol"],"ZS")

    def test_execute_rejects_avg_on_placing_notice(self):
        text="ORDER placing BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 AVG 162.80 PAPER\n"
        completed=subprocess.CompletedProcess([],0,text,"")
        with tempfile.TemporaryDirectory() as td:
            audit=Path(td)/"decision_audit.jsonl"
            output=__import__("io").StringIO()
            with patch("run_cycle.subprocess.run",return_value=completed), patch("sys.stdout",output):
                rc=run_cycle.execute(["fixture"],audit_mode="autotrader",audit_stage="execution",audit_path=audit)
        self.assertEqual(rc,0)
        self.assertEqual(output.getvalue(),"")

    def test_execute_notifies_on_broker_confirmed_accepted_paper_order(self):
        text="ORDER accepted BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 PAPER\n"
        completed=subprocess.CompletedProcess([],0,text,"")
        with tempfile.TemporaryDirectory() as td:
            audit=Path(td)/"decision_audit.jsonl"
            output=__import__("io").StringIO()
            with patch("run_cycle.subprocess.run",return_value=completed), patch("sys.stdout",output):
                rc=run_cycle.execute(["fixture"],audit_mode="autotrader",audit_stage="execution",audit_path=audit)
            row=json.loads(audit.read_text())
        self.assertEqual(rc,0)
        self.assertEqual(output.getvalue(),"Tradey Autotrader: Paper bracket order accepted — BUY 3 ZS at limit $162.79; stop $151.24; target $184.37. Broker status: accepted. This confirms order acceptance, not a fill.\n")
        self.assertEqual(row["decision"],"order_placed")
        self.assertEqual(row["action"],"BUY")
        self.assertEqual(row["symbol"],"ZS")

    def test_execute_notifies_on_broker_confirmed_immediate_fill_without_overclaim(self):
        text="ORDER filled BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 AVG 162.80 PAPER\n"
        completed=subprocess.CompletedProcess([],0,text,"")
        with tempfile.TemporaryDirectory() as td:
            audit=Path(td)/"decision_audit.jsonl"
            output=__import__("io").StringIO()
            with patch("run_cycle.subprocess.run",return_value=completed), patch("sys.stdout",output):
                rc=run_cycle.execute(["fixture"],audit_mode="autotrader",audit_stage="execution",audit_path=audit)
            row=json.loads(audit.read_text())
        self.assertEqual(rc,0)
        self.assertEqual(output.getvalue(),"Tradey Autotrader: Paper bracket order filled — BUY 3 ZS; average fill $162.80; limit $162.79; stop $151.24; target $184.37. Broker-confirmed fill.\n")
        self.assertEqual(row["decision"],"trade_filled")

    def test_execute_notifies_each_broker_confirmed_recovered_order(self):
        text=(
            "ORDER accepted BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 PAPER\n"
            "ORDER new BUY 2 AAPL LIMIT 100.00 STOP 95.00 TARGET 110.00 PAPER\n"
        )
        completed=subprocess.CompletedProcess([],0,text,"")
        with tempfile.TemporaryDirectory() as td:
            audit=Path(td)/"decision_audit.jsonl"
            output=__import__("io").StringIO()
            with patch("run_cycle.subprocess.run",return_value=completed), patch("sys.stdout",output):
                rc=run_cycle.execute(["fixture"],audit_mode="autotrader",audit_stage="execution",audit_path=audit)
        self.assertEqual(rc,0)
        self.assertEqual(output.getvalue().splitlines(), [
            "Tradey Autotrader: Paper bracket order accepted — BUY 3 ZS at limit $162.79; stop $151.24; target $184.37. Broker status: accepted. This confirms order acceptance, not a fill.",
            "Tradey Autotrader: Paper bracket order accepted — BUY 2 AAPL at limit $100.00; stop $95.00; target $110.00. Broker status: new. This confirms order acceptance, not a fill.",
        ])

    def test_execute_relays_every_valid_order_without_arbitrary_batch_cap(self):
        lines=[
            f"ORDER accepted BUY {index+1} AAPL LIMIT 100.00 STOP 95.00 TARGET 110.00 PAPER"
            for index in range(11)
        ]
        completed=subprocess.CompletedProcess([],0,"\n".join(lines)+"\n","")
        with tempfile.TemporaryDirectory() as td:
            audit=Path(td)/"decision_audit.jsonl"
            output=__import__("io").StringIO()
            with patch("run_cycle.subprocess.run",return_value=completed), patch("sys.stdout",output):
                self.assertEqual(run_cycle.execute(
                    ["fixture"],audit_mode="autotrader",audit_stage="execution",audit_path=audit),0)
        self.assertEqual(len(output.getvalue().splitlines()),11)

    def test_execute_keeps_malformed_or_private_order_output_silent(self):
        texts=[
            "ORDER accepted BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 PAPER private-id",
            "ORDER accepted BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 LIVE",
            "ORDER filled BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 PAPER",
            " ORDER accepted BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 PAPER",
        ]
        for text in texts:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as td:
                audit=Path(td)/"decision_audit.jsonl"
                output=__import__("io").StringIO()
                completed=subprocess.CompletedProcess([],0,text,"")
                with patch("run_cycle.subprocess.run",return_value=completed), patch("sys.stdout",output):
                    self.assertEqual(run_cycle.execute(["fixture"],audit_mode="autotrader",audit_stage="execution",audit_path=audit),0)
                self.assertEqual(output.getvalue(),"")

    def test_nonzero_private_output_is_replaced_with_generic_failure(self):
        private="BLOCKER consensus_hold\naccount_id=secret broker_order_id=private /opt/data/private raw_payload thesis review"
        completed=subprocess.CompletedProcess([],2,private,"")
        with tempfile.TemporaryDirectory() as td:
            audit=Path(td)/"decision_audit.jsonl"
            output=__import__("io").StringIO()
            with patch("run_cycle.subprocess.run",return_value=completed), patch("sys.stdout",output):
                self.assertEqual(run_cycle.execute(["fixture"],audit_mode="autotrader",audit_stage="execution",audit_path=audit),2)
        self.assertEqual(output.getvalue(),"SYSTEM_FAILURE scheduled_task\n")

    def test_single_token_private_failure_reason_is_not_allowlisted_or_audited(self):
        completed=subprocess.CompletedProcess([],4,"SYSTEM_FAILURE accountsecretabc123\n","")
        with tempfile.TemporaryDirectory() as td:
            audit=Path(td)/"decision_audit.jsonl"
            output=__import__("io").StringIO()
            with patch("run_cycle.subprocess.run",return_value=completed), patch("sys.stdout",output):
                self.assertEqual(run_cycle.execute(
                    ["fixture"],audit_mode="autotrader",audit_stage="execution",audit_path=audit),4)
            row=json.loads(audit.read_text())
        self.assertEqual(output.getvalue(),"SYSTEM_FAILURE scheduled_task\n")
        self.assertEqual(row["reason"],"unspecified")
        self.assertNotIn("accountsecretabc123",json.dumps(row))

    def test_malformed_nonzero_trade_does_not_project_identity_into_audit(self):
        completed=subprocess.CompletedProcess([],4,"TRADE BUY SECRET account_id=hidden\n","")
        with tempfile.TemporaryDirectory() as td:
            audit=Path(td)/"decision_audit.jsonl"
            output=__import__("io").StringIO()
            with patch("run_cycle.subprocess.run",return_value=completed), patch("sys.stdout",output):
                self.assertEqual(run_cycle.execute(
                    ["fixture"],audit_mode="autotrader",audit_stage="execution",audit_path=audit),4)
            row=json.loads(audit.read_text())
        self.assertEqual(output.getvalue(),"SYSTEM_FAILURE scheduled_task\n")
        self.assertEqual(row["decision"],"failed")
        self.assertNotIn("action",row)
        self.assertNotIn("symbol",row)

    def test_multiline_trade_or_order_output_never_projects_identity_into_audit(self):
        cases=[
            "TRADE BUY 1 AAPL @ 100.00\nPRIVATE account_id=hidden",
            "ORDER filled BUY 1 AAPL LIMIT 100.00 STOP 95.00 TARGET 110.00 AVG 100.00 PAPER\nPRIVATE account_id=hidden",
            "ORDER accepted BUY 1 AAPL LIMIT 100.00 STOP 95.00 TARGET 110.00 PAPER\nMALFORMED",
        ]
        for text in cases:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as td:
                path=Path(td)/"decision_audit.jsonl"
                run_cycle.audit_result("autotrader","execution",0,text,path)
                row=json.loads(path.read_text())
                self.assertEqual(row["decision"],"completed")
                self.assertNotIn("action",row)
                self.assertNotIn("symbol",row)

    def test_decision_output_requires_an_exact_single_allowed_schema(self):
        cases=[
            "DECISION candidate_qualified AAPL private_secret",
            "DECISION candidate_qualified AAPL\vPRIVATE account_id=hidden",
            "DECISION reused_fresh_candidate AAPL extra",
            "DECISION skipped no_fresh_setup extra",
        ]
        for text in cases:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as td:
                path=Path(td)/"decision_audit.jsonl"
                run_cycle.audit_result("radar","research",0,text,path)
                row=json.loads(path.read_text())
                self.assertEqual(row["decision"],"completed")
                self.assertNotIn("symbol",row)
                self.assertNotIn("reason",row)

    def test_nonzero_allowlisted_blocker_is_delivered_exactly(self):
        completed=subprocess.CompletedProcess([],2,"BLOCKER broker_review:insufficient_cash,spread_too_wide\n","")
        with tempfile.TemporaryDirectory() as td:
            audit=Path(td)/"decision_audit.jsonl"
            output=__import__("io").StringIO()
            with patch("run_cycle.subprocess.run",return_value=completed), patch("sys.stdout",output):
                self.assertEqual(run_cycle.execute(["fixture"],audit_mode="autotrader",audit_stage="execution",audit_path=audit),2)
        self.assertEqual(output.getvalue(),"BLOCKER broker_review:insufficient_cash,spread_too_wide\n")

    def test_audit_result_records_a_scheduled_skip_reason(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"decision_audit.jsonl"
            run_cycle.audit_result("radar","schedule",0,"DECISION skipped outside_window",path)
            row=json.loads(path.read_text())
        self.assertEqual(row["decision"],"skipped")
        self.assertEqual(row["reason"],"outside_window")

    def test_main_enables_auditing_for_an_autotrader_cycle(self):
        with patch.object(sys,"argv",["run_cycle.py","autotrader"]), patch("run_cycle.scheduled_slot",return_value=True), patch("run_cycle.in_window",return_value=True), patch("run_cycle.execute",return_value=0) as call:
            self.assertEqual(run_cycle.main(),0)
        self.assertEqual(call.call_args.kwargs["audit_mode"],"autotrader")
        self.assertEqual(call.call_args.kwargs["audit_stage"],"execution")

    def test_main_audits_a_cycle_skipped_outside_its_window(self):
        with patch.object(sys,"argv",["run_cycle.py","radar"]), patch("run_cycle.scheduled_slot",return_value=True), patch("run_cycle.in_window",return_value=False), patch("run_cycle.audit_result") as audit:
            self.assertEqual(run_cycle.main(),0)
        audit.assert_called_once_with("radar","schedule",0,"DECISION skipped outside_window")

    def test_postclose_refreshes_isolated_shadow_calibration(self):
        with patch.object(sys,"argv",["run_cycle.py","postclose"]), patch("run_cycle.in_window",return_value=True), patch("run_cycle.completed_today",return_value=False), patch("run_cycle.mark_completed"), patch("run_cycle.execute",return_value=0) as execute:
            self.assertEqual(run_cycle.main(),0)
        commands=[call.args[0] for call in execute.call_args_list]
        self.assertTrue(any(command[-1].endswith("candidate_outcomes.py") for command in commands))
        self.assertTrue(any(command[-1].endswith("shadow_calibration.py") for command in commands))
        self.assertTrue(any(command[-1].endswith("public_dashboard.py") for command in commands))

    def test_dashboard_refresh_is_not_suppressed_after_first_daily_deploy(self):
        with patch.object(sys,"argv",["run_cycle.py","dashboard"]), \
             patch("run_cycle.in_window",return_value=True), \
             patch("run_cycle.completed_today") as completed, \
             patch("run_cycle.mark_completed") as mark, \
             patch("run_cycle.execute",return_value=0) as execute:
            self.assertEqual(run_cycle.main(),0)
        completed.assert_not_called()
        mark.assert_not_called()
        self.assertTrue(execute.call_args.args[0][-1].endswith("deploy_dashboard.sh"))

    def test_daily_completion_is_written_only_after_success(self):
        with tempfile.TemporaryDirectory() as td:
            state=Path(td)
            self.assertFalse(run_cycle.completed_today("radar",state=state))
            self.assertFalse((state/"radar.date").exists())
            run_cycle.mark_completed("radar",state=state)
            self.assertTrue(run_cycle.completed_today("radar",state=state))

    def test_new_york_pairing_slots(self):
        ny=ZoneInfo("America/New_York")
        day=dt.date(2026,9,15)
        at=lambda h,m:dt.datetime.combine(day,dt.time(h,m),tzinfo=ny)
        self.assertTrue(run_cycle.scheduled_slot("premarket",at(9,0)))
        self.assertFalse(run_cycle.scheduled_slot("premarket",at(8,30)))
        for h,m in [(10,0),(10,30),(15,0),(15,30)]:
            self.assertTrue(run_cycle.scheduled_slot("radar",at(h,m)))
        for h,m in [(9,30),(9,40),(16,0)]:
            self.assertFalse(run_cycle.scheduled_slot("radar",at(h,m)))
        for h,m in [(9,40),(10,20),(10,50),(15,20),(15,50)]:
            self.assertTrue(run_cycle.scheduled_slot("autotrader",at(h,m)))
        for h,m in [(9,30),(9,45),(10,0),(16,20)]:
            self.assertFalse(run_cycle.scheduled_slot("autotrader",at(h,m)))

    def test_slot_classification_is_dst_safe(self):
        summer=dt.datetime(2026,9,15,13,0,tzinfo=dt.timezone.utc)
        winter=dt.datetime(2026,12,15,14,0,tzinfo=dt.timezone.utc)
        self.assertTrue(run_cycle.scheduled_slot("premarket",summer))
        self.assertTrue(run_cycle.scheduled_slot("premarket",winter))

    def test_main_silently_skips_broad_cron_fire_outside_exact_slot(self):
        with patch.object(sys,"argv",["run_cycle.py","radar"]), patch(
            "run_cycle.scheduled_slot",return_value=False
        ), patch("run_cycle.in_window") as window, patch("run_cycle.execute") as execute, patch(
            "run_cycle.audit_result"
        ) as audit:
            self.assertEqual(run_cycle.main(),0)
        window.assert_not_called();execute.assert_not_called();audit.assert_not_called()

    def test_radar_research_runs_under_a_1110_second_budget(self):
        with patch.object(sys,"argv",["run_cycle.py","radar"]), \
             patch("run_cycle.scheduled_slot",return_value=True), \
             patch("run_cycle.in_window",return_value=True), \
             patch.object(run_cycle,"execute",return_value=0) as call:
            run_cycle.main()
        self.assertEqual(call.call_args.kwargs["timeout_seconds"],1110)
if __name__=="__main__":unittest.main()
