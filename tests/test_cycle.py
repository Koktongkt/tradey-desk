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
    def test_market_postclose_and_dashboard_windows(self):
        eastern = ZoneInfo("America/New_York")
        cases = (
            ("market weekday", "market", dt.datetime(2026, 8, 31, 10, 0, tzinfo=eastern), True),
            ("market weekend", "market", dt.datetime(2026, 8, 29, 10, 0, tzinfo=eastern), False),
            ("postclose", "postclose", dt.datetime(2026, 8, 31, 16, 30, tzinfo=eastern), True),
            ("postclose late", "postclose", dt.datetime(2026, 8, 31, 18, 30, tzinfo=eastern), False),
            ("dashboard intraday", "dashboard", dt.datetime(2026, 8, 31, 10, 0, tzinfo=eastern), True),
            ("dashboard after close", "dashboard", dt.datetime(2026, 8, 31, 17, 30, tzinfo=eastern), True),
        )
        for label, window, now, expected in cases:
            with self.subTest(case=label):
                self.assertIs(run_cycle.in_window(window, now), expected)

    def test_execute_retries_safe_task_and_uses_explicit_timeout(self):
        failed=subprocess.CompletedProcess([],3,"","temporary")
        passed=subprocess.CompletedProcess([],0,"","")
        with patch("run_cycle.subprocess.run",side_effect=[failed,passed]) as call:
            self.assertEqual(run_cycle.execute(["safe"],timeout_seconds=600,attempts=2),0)
        self.assertEqual(call.call_count,2)
        self.assertEqual(call.call_args.kwargs["timeout"],600)

    def test_audit_result_sanitized_decision_schemas(self):
        cases = (
            ("private blocked", "autotrader", "execution", 2, "BLOCKER consensus_hold\nprivate detail",
             {"mode": "autotrader", "stage": "execution", "decision": "blocked", "reason": "unspecified"}, "private detail"),
            ("healthy research skip", "premarket", "research", 0, "DECISION skipped no_fresh_setup",
             {"decision": "skipped", "reason": "no_fresh_setup"}, None),
            ("qualified candidate", "radar", "research", 0, "DECISION candidate_qualified AAPL",
             {"decision": "candidate_qualified", "symbol": "AAPL"}, None),
            ("safe fill identity", "autotrader", "execution", 0, "TRADE BUY 1 AAPL @ 100.05",
             {"decision": "trade_filled", "action": "BUY", "symbol": "AAPL"}, None),
            ("scheduled skip", "radar", "schedule", 0, "DECISION skipped outside_window",
             {"decision": "skipped", "reason": "outside_window"}, None),
        )
        for label, mode, stage, rc, text, expected, private in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as td:
                path = Path(td) / "decision_audit.jsonl"
                run_cycle.audit_result(mode, stage, rc, text, path)
                row = json.loads(path.read_text())
                for field, value in expected.items():
                    self.assertEqual(row[field], value, field)
                if private is not None:
                    self.assertNotIn(private, json.dumps(row))


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


    def test_execute_order_lifecycle_notices_without_overclaim(self):
        cases = (
            ("placing", "ORDER placing BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 PAPER\n",
             "Tradey Autotrader: Placing paper bracket order to Alpaca — BUY 3 ZS at limit $162.79; stop $151.24; target $184.37. This is a placement notice, not confirmation of acceptance or fill.\n",
             {"decision": "order_placed", "action": "BUY", "symbol": "ZS"}),
            ("accepted", "ORDER accepted BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 PAPER\n",
             "Tradey Autotrader: Paper bracket order accepted — BUY 3 ZS at limit $162.79; stop $151.24; target $184.37. Broker status: accepted. This confirms order acceptance, not a fill.\n",
             {"decision": "order_placed", "action": "BUY", "symbol": "ZS"}),
            ("filled", "ORDER filled BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 AVG 162.80 PAPER\n",
             "Tradey Autotrader: Paper bracket order filled — BUY 3 ZS; average fill $162.80; limit $162.79; stop $151.24; target $184.37. Broker-confirmed fill.\n",
             {"decision": "trade_filled"}),
        )
        for label, text, expected_output, expected_row in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as td:
                audit = Path(td) / "decision_audit.jsonl"
                output = __import__("io").StringIO()
                completed = subprocess.CompletedProcess([], 0, text, "")
                with patch("run_cycle.subprocess.run", return_value=completed), patch("sys.stdout", output):
                    rc = run_cycle.execute(["fixture"], audit_mode="autotrader", audit_stage="execution", audit_path=audit)
                row = json.loads(audit.read_text())
                self.assertEqual(rc, 0)
                self.assertEqual(output.getvalue(), expected_output)
                for field, value in expected_row.items():
                    self.assertEqual(row[field], value, field)


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
            "ORDER placing BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 AVG 162.80 PAPER\n",
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

    def test_execute_nonzero_private_output_fails_without_identity_leaks(self):
        cases = (
            ("multiline private blocker", 2,
             "BLOCKER consensus_hold\naccount_id=secret broker_order_id=private /opt/data/private raw_payload thesis review",
             {}, (), None),
            ("private single token", 4, "SYSTEM_FAILURE accountsecretabc123\n",
             {"reason": "unspecified"}, (), "accountsecretabc123"),
            ("malformed trade", 4, "TRADE BUY SECRET account_id=hidden\n",
             {"decision": "failed"}, ("action", "symbol"), None),
        )
        for label, rc, text, expected, absent, private in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as td:
                audit = Path(td) / "decision_audit.jsonl"
                output = __import__("io").StringIO()
                completed = subprocess.CompletedProcess([], rc, text, "")
                with patch("run_cycle.subprocess.run", return_value=completed), patch("sys.stdout", output):
                    self.assertEqual(run_cycle.execute(
                        ["fixture"], audit_mode="autotrader", audit_stage="execution", audit_path=audit), rc)
                row = json.loads(audit.read_text())
                self.assertEqual(output.getvalue(), "SYSTEM_FAILURE scheduled_task\n")
                for field, value in expected.items():
                    self.assertEqual(row[field], value, field)
                for field in absent:
                    self.assertNotIn(field, row)
                if private is not None:
                    self.assertNotIn(private, json.dumps(row))


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

    def test_dashboard_failure_contract_and_single_retry_owner(self):
        cases = ["dashboard_build_failed", "dashboard_deploy_failed", "dashboard_timeout",
                 "dashboard_build_timeout", "dashboard_deploy_timeout", "dashboard_deploy_auth",
                 "dashboard_deploy_config", "dashboard_deploy_build", "dashboard_deploy_network",
                 "dashboard_deploy_rate_limit", "dashboard_deploy_service", "dashboard_cli_missing"]
        for token in cases:
            with self.subTest(token=token), tempfile.TemporaryDirectory() as td:
                audit=Path(td)/"audit.jsonl"
                output=__import__("io").StringIO()
                failure=subprocess.CompletedProcess([],1,f"SYSTEM_FAILURE {token}\n","private token URL /path")
                with patch("dashboard_process.run_owned",return_value=failure) as call, patch("sys.stdout",output):
                    rc=run_cycle.execute(["fixture"],attempts=2,audit_mode="dashboard",audit_stage="deployment",audit_path=audit)
                self.assertEqual(rc,1)
                self.assertEqual(output.getvalue(),f"SYSTEM_FAILURE {token}\n")
                self.assertEqual(call.call_count,1)
                self.assertEqual(json.loads(audit.read_text())["reason"],token)
                for unsafe in (f"SYSTEM_FAILURE {token} private",f"SYSTEM_FAILURE {token}\nprivate", "SYSTEM_FAILURE dashboard_unknown", f"SYSTEM_FAILURE {token}:scheduled_task"):
                    self.assertIsNone(run_cycle.parse_failure_event(unsafe))
        with tempfile.TemporaryDirectory() as td:
            output=__import__("io").StringIO()
            with patch("dashboard_process.run_owned",side_effect=subprocess.TimeoutExpired("fixture",300)) as call, patch("sys.stdout",output):
                self.assertEqual(run_cycle.execute(["fixture"],attempts=2,audit_mode="dashboard",audit_stage="deployment",audit_path=Path(td)/"audit"),124)
            self.assertEqual(output.getvalue(),"SYSTEM_FAILURE dashboard_timeout\n")
            self.assertEqual(call.call_count,1)

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
        self.assertEqual(execute.call_args.kwargs["attempts"],1)
        self.assertEqual(execute.call_args.kwargs["timeout_seconds"],300)

    def test_daily_completion_is_written_only_after_success(self):
        with tempfile.TemporaryDirectory() as td:
            state=Path(td)
            self.assertFalse(run_cycle.completed_today("radar",state=state))
            self.assertFalse((state/"radar.date").exists())
            run_cycle.mark_completed("radar",state=state)
            self.assertTrue(run_cycle.completed_today("radar",state=state))

    def test_approved_autotrader_fire_reaches_execution_without_slot_mock(self):
        real_datetime=dt.datetime
        for day in (dt.date(2026,3,9),dt.date(2026,10,12),dt.date(2026,11,2),dt.date(2026,12,15)):
            for hour,minute in ((9,38),(9,58),(10,18),(10,38),(10,58),(15,58)):
                fire=real_datetime.combine(day,dt.time(hour,minute),tzinfo=run_cycle.NY)
                with self.subTest(fire=fire), patch.object(run_cycle.dt,'datetime') as clock, patch.object(sys,'argv',['run_cycle.py','autotrader']), patch.object(run_cycle,'execute',return_value=0) as execute, patch.object(run_cycle,'audit_result') as audit:
                    clock.now.return_value=fire
                    self.assertEqual(run_cycle.main(),0)
                    execute.assert_called_once_with([sys.executable,str(run_cycle.ROOT/'autotrader.py')],timeout_seconds=600,attempts=1,audit_mode='autotrader',audit_stage='execution')
                    audit.assert_not_called()

    def test_autotrader_off_slot_and_market_fences_prevent_execution(self):
        real_datetime=dt.datetime
        for day,hour,minute in ((dt.date(2026,10,12),9,18),(dt.date(2026,10,12),9,40),(dt.date(2026,10,12),10,15),(dt.date(2026,10,12),16,18),(dt.date(2026,10,17),10,18)):
            fire=real_datetime.combine(day,dt.time(hour,minute),tzinfo=run_cycle.NY)
            with self.subTest(fire=fire), patch.object(run_cycle.dt,'datetime') as clock, patch.object(sys,'argv',['run_cycle.py','autotrader']), patch.object(run_cycle,'execute') as execute, patch.object(run_cycle,'audit_result'):
                clock.now.return_value=fire
                self.assertEqual(run_cycle.main(),0)
                execute.assert_not_called()

    def test_new_york_pairing_slots(self):
        ny=ZoneInfo("America/New_York")
        day=dt.date(2026,9,15)
        at=lambda h,m:dt.datetime.combine(day,dt.time(h,m),tzinfo=ny)
        self.assertTrue(run_cycle.scheduled_slot("premarket",at(9,0)))
        self.assertFalse(run_cycle.scheduled_slot("premarket",at(8,30)))
        for h,m in [(10,0),(10,20),(10,40),(15,0),(15,20),(15,40)]:
            self.assertTrue(run_cycle.scheduled_slot("radar",at(h,m)))
        for h,m in [(9,30),(9,40),(16,0),(10,10),(10,30),(10,50)]:
            self.assertFalse(run_cycle.scheduled_slot("radar",at(h,m)))
        for h,m in [(9,18),(9,38),(9,58),(10,18),(10,38),(10,58),(15,18),(15,38),(15,58)]:
            self.assertTrue(run_cycle.scheduled_slot("autotrader",at(h,m)))
        for h,m in [(9,15),(9,30),(9,35),(9,40),(9,45),(9,55),(10,0),(10,10),(10,15),(10,20),(10,30),(10,35),(10,40),(10,50),(10,55),(16,18),(16,38),(16,58)]:
            self.assertFalse(run_cycle.scheduled_slot("autotrader",at(h,m)))

    def test_market_open_and_close_fire_windows_exclude_edge_slots(self):
        ny=ZoneInfo("America/New_York")
        day=dt.date(2026,9,15)
        at=lambda h,m:dt.datetime.combine(day,dt.time(h,m),tzinfo=ny)
        for h,m in [(9,0),(9,20),(16,0),(16,20),(16,40)]:
            self.assertFalse(run_cycle.scheduled_slot("radar",at(h,m)))
            self.assertFalse(run_cycle.scheduled_slot("autotrader",at(h,m)))

    def test_autotrader_cron_contract_preserves_opening_and_intraday_slots(self):
        # Test the scheduler grid AND the real NY predicates, not either alone.
        expression=(Path(run_cycle.__file__).parent/"cron"/"autotrader.schedule").read_text().strip()
        minute_field,hour_field,dom,month,dow=expression.split()
        self.assertEqual((dom,month,dow),("*","*","1-5"))
        minutes={int(value) for value in minute_field.split(",")}
        self.assertEqual(minutes,{18,38,58})
        first_hour,last_hour=(int(value) for value in hour_field.split("-"))
        self.assertEqual((first_hour,last_hour),(13,20))
        ny=ZoneInfo("America/New_York")
        expected=[(9,38),(9,58)]+[(hour,minute) for hour in range(10,16) for minute in (18,38,58)]
        # EDT, EST, and the Mondays following both DST transitions.
        for day in (dt.date(2026,10,12),dt.date(2026,12,15),dt.date(2026,3,9),dt.date(2026,11,2),dt.date(2026,10,17),dt.date(2026,12,19)):
            accepted=[]
            for hour in range(first_hour,last_hour+1):
                for minute in sorted(minutes):
                    fire=dt.datetime.combine(day,dt.time(hour,minute),tzinfo=dt.timezone.utc)
                    if run_cycle.scheduled_slot("autotrader",fire) and run_cycle.in_window("market",fire):
                        local=fire.astimezone(ny)
                        accepted.append((local.hour,local.minute))
            with self.subTest(day=day):
                self.assertEqual(accepted,expected if day.weekday()<5 else [])

    def test_slot_classification_is_dst_safe(self):
        summer=dt.datetime(2026,9,15,13,0,tzinfo=dt.timezone.utc)
        winter=dt.datetime(2026,12,15,14,0,tzinfo=dt.timezone.utc)
        self.assertTrue(run_cycle.scheduled_slot("premarket",summer))
        self.assertTrue(run_cycle.scheduled_slot("premarket",winter))

    def test_intraday_consumer_follows_research_by_eighteen_minutes(self):
        ny=ZoneInfo('America/New_York')
        for day in (dt.date(2026,3,9),dt.date(2026,10,12),dt.date(2026,11,2),dt.date(2026,12,15)):
            for hour in range(10,16):
                for minute in (0,20,40):
                    producer=dt.datetime.combine(day,dt.time(hour,minute),tzinfo=ny)
                    consumer=producer+dt.timedelta(minutes=18)
                    with self.subTest(day=day,hour=hour,minute=minute):
                        self.assertTrue(run_cycle.scheduled_slot('radar',producer))
                        self.assertTrue(run_cycle.scheduled_slot('autotrader',consumer))
                        self.assertTrue(run_cycle.in_window('market',consumer))
                        self.assertEqual(consumer-(producer+dt.timedelta(seconds=990)),dt.timedelta(seconds=90))

    def test_reconciliation_grid_avoids_simultaneous_autotrader_starts(self):
        import managed_reconciliation as reconciliation
        root=Path(run_cycle.__file__).parent
        contract=root/'cron/reconcile.schedule'
        self.assertTrue(contract.is_file(),'versioned reconciliation cadence contract missing')
        minute_field,hour_field,dom,month,dow=contract.read_text().split()
        self.assertEqual((hour_field,dom,month,dow),('*','*','*','1-5'))
        minutes={int(x) for x in minute_field.split(',')}
        auto_minutes={int(x) for x in (root/'cron/autotrader.schedule').read_text().split()[0].split(',')}
        ny=ZoneInfo('America/New_York')
        # Preserve reconciliation's existing 09:35–16:15 fence. The shifted
        # 09:32 fire is a no-op; the first/last accepted fires are 09:42/16:12.
        expected=[(9,42),(9,52)]+[(h,m) for h in range(10,16) for m in (2,12,22,32,42,52)]+[(16,2),(16,12)]
        for day in (dt.date(2026,3,9),dt.date(2026,10,12),dt.date(2026,11,2),dt.date(2026,12,15),dt.date(2026,10,17)):
            accepted=[]; auto=[]
            for hour in range(24):
                for minute in range(60):
                    fire=dt.datetime.combine(day,dt.time(hour,minute),tzinfo=dt.timezone.utc)
                    local=fire.astimezone(ny)
                    if minute in minutes and reconciliation.market_window_open(fire):accepted.append((local.hour,local.minute))
                    if 13<=hour<=20 and minute in auto_minutes and run_cycle.scheduled_slot('autotrader',fire) and run_cycle.in_window('market',fire):auto.append((local.hour,local.minute))
            with self.subTest(day=day):
                self.assertEqual(accepted,expected if day.weekday()<5 else [])
                self.assertFalse(set(accepted)&set(auto))

    def test_main_silently_skips_broad_cron_fire_outside_exact_slot(self):
        with patch.object(sys,"argv",["run_cycle.py","radar"]), patch(
            "run_cycle.scheduled_slot",return_value=False
        ), patch("run_cycle.in_window") as window, patch("run_cycle.execute") as execute, patch(
            "run_cycle.audit_result"
        ) as audit:
            self.assertEqual(run_cycle.main(),0)
        window.assert_not_called();execute.assert_not_called();audit.assert_not_called()

    def test_research_uses_990_seconds_without_changing_execution_budget(self):
        for mode in ("radar","premarket","autotrader"):
            with self.subTest(mode=mode), patch.object(sys,"argv",["run_cycle.py",mode]), \
                 patch("run_cycle.scheduled_slot",return_value=True), \
                 patch("run_cycle.in_window",return_value=True), \
                 patch("run_cycle.completed_today",return_value=False), \
                 patch("run_cycle.mark_completed"), \
                 patch.object(run_cycle,"execute",return_value=0) as call:
                run_cycle.main()
                self.assertEqual(call.call_args.kwargs["timeout_seconds"],600 if mode=='autotrader' else 990)
                self.assertEqual(call.call_args.kwargs["attempts"],1)
class PortableCronEntrypointTests(unittest.TestCase):
    def test_wrappers_resolve_their_project_and_preserve_arguments(self):
        import os
        import shutil
        root = Path(__file__).resolve().parents[1]
        entries = [(f"cron/{mode}.sh", "run_cycle.py", mode)
                   for mode in ("premarket", "radar", "autotrader", "postclose", "dashboard")]
        entries += [("cron/reconcile.sh", "managed_reconciliation.py", "--scheduled"),
                    ("scripts/tradey_watchdog_mechanical.sh", "watchdog_cron.py", "mechanical"),
                    ("scripts/tradey_watchdog_daily.sh", "watchdog_cron.py", "daily")]
        with tempfile.TemporaryDirectory() as td:
            relocated = Path(td) / "project with spaces"
            fakebin = Path(td) / "bin"
            fakebin.mkdir()
            fake = fakebin / "python3"
            fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
            fake.chmod(0o755)
            env = {**os.environ, "PATH": str(fakebin) + os.pathsep + os.environ.get("PATH", ""),
                   "TRADEY_PYTHON": str(fake)}
            for relative, target, mode in entries:
                with self.subTest(wrapper=relative):
                    self.assertTrue((root / relative).is_file(), relative)
                    copied = relocated / relative
                    copied.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(root / relative, copied)
                    result = subprocess.run(["/bin/bash", str(copied), "--probe"], env=env,
                                            cwd=td, text=True, capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.splitlines(),
                                     [str(relocated / target), mode, "--probe"])

    def test_explicit_bad_python_override_fails_without_fallback(self):
        import os
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            wrapper = Path(td) / "project/cron/radar.sh"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_bytes((root / "cron/radar.sh").read_bytes())
            env = {**os.environ, "TRADEY_PYTHON": str(Path(td) / "missing-python")}
            result = subprocess.run(["/bin/bash", str(wrapper)], env=env, cwd=td,
                                    text=True, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing-python", result.stderr)

if __name__=="__main__":unittest.main()
