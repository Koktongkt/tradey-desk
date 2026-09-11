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
        self.assertEqual(row["reason"],"consensus_hold")
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

    def test_audit_result_records_a_scheduled_skip_reason(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"decision_audit.jsonl"
            run_cycle.audit_result("radar","schedule",0,"DECISION skipped outside_window",path)
            row=json.loads(path.read_text())
        self.assertEqual(row["decision"],"skipped")
        self.assertEqual(row["reason"],"outside_window")

    def test_main_enables_auditing_for_an_autotrader_cycle(self):
        with patch.object(sys,"argv",["run_cycle.py","autotrader"]), patch("run_cycle.in_window",return_value=True), patch("run_cycle.execute",return_value=0) as call:
            self.assertEqual(run_cycle.main(),0)
        self.assertEqual(call.call_args.kwargs["audit_mode"],"autotrader")
        self.assertEqual(call.call_args.kwargs["audit_stage"],"execution")

    def test_main_audits_a_cycle_skipped_outside_its_window(self):
        with patch.object(sys,"argv",["run_cycle.py","radar"]), patch("run_cycle.in_window",return_value=False), patch("run_cycle.audit_result") as audit:
            self.assertEqual(run_cycle.main(),0)
        audit.assert_called_once_with("radar","schedule",0,"DECISION skipped outside_window")

    def test_postclose_refreshes_isolated_shadow_calibration(self):
        with patch.object(sys,"argv",["run_cycle.py","postclose"]), patch("run_cycle.in_window",return_value=True), patch("run_cycle.completed_today",return_value=False), patch("run_cycle.mark_completed"), patch("run_cycle.execute",return_value=0) as execute:
            self.assertEqual(run_cycle.main(),0)
        commands=[call.args[0] for call in execute.call_args_list]
        self.assertTrue(any(command[-1].endswith("candidate_outcomes.py") for command in commands))
        self.assertTrue(any(command[-1].endswith("shadow_calibration.py") for command in commands))
        self.assertTrue(any(command[-1].endswith("public_dashboard.py") for command in commands))

    def test_daily_completion_is_written_only_after_success(self):
        with tempfile.TemporaryDirectory() as td:
            state=Path(td)
            self.assertFalse(run_cycle.completed_today("radar",state=state))
            self.assertFalse((state/"radar.date").exists())
            run_cycle.mark_completed("radar",state=state)
            self.assertTrue(run_cycle.completed_today("radar",state=state))

    def test_radar_research_runs_under_a_720_second_budget(self):
        with patch.object(sys,"argv",["run_cycle.py","radar"]), \
             patch("run_cycle.in_window",return_value=True), \
             patch.object(run_cycle,"execute",return_value=0) as call:
            run_cycle.main()
        self.assertEqual(call.call_args.kwargs["timeout_seconds"],720)
if __name__=="__main__":unittest.main()
