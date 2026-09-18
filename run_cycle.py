#!/usr/bin/env python3
"""Timezone-aware silent cron entry point."""
from __future__ import annotations
import argparse,datetime as dt,json,re,subprocess,sys
from pathlib import Path
from zoneinfo import ZoneInfo
from durable_jsonl import append_jsonl, DurableAppendError
ROOT=Path(__file__).resolve().parent
NY=ZoneInfo("America/New_York")
AUDIT_PATH=ROOT/"decision_audit.jsonl"

ORDER_EVENT_RE=re.compile(
    r"ORDER (?P<status>placing|new|accepted|pending_new|partially_filled|held|filled) "
    r"(?P<action>BUY|SELL) (?P<quantity>[1-9]\d*) (?P<symbol>[A-Z]{1,6}) "
    r"LIMIT (?P<limit>\d+\.\d{2}) STOP (?P<stop>\d+\.\d{2}) "
    r"TARGET (?P<target>\d+\.\d{2})(?: AVG (?P<average>\d+\.\d{2}))? PAPER"
)
FAILURE_EVENT_RE=re.compile(
    r"(?:BLOCKER|AUTH_FAILURE|SYSTEM_FAILURE) "
    r"[a-z][a-z0-9_]*(?:(?:[:,])[a-z][a-z0-9_]*)*"
)
TRADE_EVENT_RE=re.compile(
    r"TRADE (?P<action>BUY|SELL) (?P<quantity>[1-9]\d*(?:\.\d+)?) "
    r"(?P<symbol>[A-Z]{1,6}) @ (?P<price>\d+(?:\.\d+)?)"
)
DECISION_EVENT_RE=re.compile(
    r"DECISION (?:(?P<event>candidate_qualified|reused_fresh_candidate) "
    r"(?P<symbol>[A-Z]{1,6})|skipped (?P<reason>outside_window|already_completed|"
    r"already_reviewed|no_fresh_setup|no_valid_discovery_candidate))"
)
ALLOWED_FAILURE_TOKENS=frozenset({
    "account_cap_exceeded","active_broker_order","alpha_radar","asset_name_unknown",
    "asset_not_fractionable","audit_persistence_failure","autonomy_disabled",
    "broker_baseline_invalid","broker_baseline_missing","broker_mcp_failure",
    "broker_mcp_unavailable","broker_reconciliation_invalid","broker_review",
    "broker_tradability_unverified","candidate_failed_qualification","candidate_outcomes",
    "consolidated_volume_unavailable","consensus_hold","daily_order_limit",
    "dry_run_no_execution","earnings_blackout","earnings_timestamp_unverified",
    "earnings_unknown","evidence_insufficient","fractional_shares_disabled",
    "fund_or_etn_forbidden","horizon_session_mismatch","incomplete_trade_plan",
    "insufficient_buying_power","insufficient_cash","instrument_not_cash_equity",
    "invalid_horizon","invalid_quantity_or_price","invalid_stop_or_target","invalid_symbol",
    "kill_switch_active","leveraged_or_inverse_etf_forbidden","limit_order_required",
    "limit_price_too_far_from_quote","liquidity_failed","live_dry_run_no_execution",
    "low_confidence","malformed_or_low_confidence","malformed_review",
    "managed_baseline_overlap","managed_closed_without_fill","managed_evidence_invalid",
    "managed_exit_ambiguous","managed_exit_reconciliation","managed_exit_reconciliation_ambiguous",
    "managed_exit_reconciliation_invalid","managed_exit_reconciliation_missing",
    "managed_journal_invalid","managed_journal_negative","managed_open_order_unlinked",
    "managed_open_orders_ambiguous","managed_open_orders_unverified",
    "managed_partial_exit_unsupported","managed_position_reconciliation_failed",
    "managed_position_untracked","managed_positions_unverified","managed_protection_inconsistent",
    "managed_protection_missing","managed_protection_missing_or_oversized",
    "managed_protection_not_persistent","managed_reconciliation","managed_state_invalid",
    "model_disagreement","near_term_earnings","no_candidate","non_paper_mode_forbidden",
    "otc_forbidden","pending_order_reconciliation","planned_risk_exceeded",
    "planned_risk_policy_missing","policy_constraints_unmet","position_size_exceeded",
    "positions_unknown","preexisting_position_conflict","price_below_minimum",
    "proposal_hash_mismatch","quote_feed_unavailable","quote_timestamp_unknown",
    "registry_conflict","registry_row_invalid","registry_verification_invalid",
    "registry_verification_unavailable","research_candidate_mismatch",
    "research_catalyst_stale","research_earnings_blackout",
    "research_earnings_timestamp_unverified","research_evidence_insufficient",
    "research_focused_retrieval_timeout","research_focused_retrieval_unavailable",
    "research_market_data_unavailable","research_parse_failure","research_persistence_failure",
    "research_policy_constraints_unmet","research_rescue_unavailable",
    "research_scout_parse_failure","research_scout_schema_rejected","research_scout_timeout",
    "research_scout_unavailable","research_source_freshness_insufficient",
    "research_source_retrieval_failed","research_source_verification_failed",
    "research_synthesis_timeout","research_synthesis_unavailable","reviewer_unavailable",
    "reviewer_veto","scheduled_task","shadow_calibration","short_sale_forbidden",
    "sizing_state_unavailable","spread_too_wide","stale_or_unverified_research","stale_quote",
    "submission_notification_failed","technical_bars_unavailable","trading_calendar_unavailable","unknown_buying_power",
    "unknown_cash","unknown_spread","unsupported_action","unsupported_technical_setup",
    "weak_reward_to_risk","whole_share_unaffordable",
})


def exact_line(text:str)->str|None:
    line=text[:-1] if text.endswith("\n") else text
    parts=line.splitlines()
    return line if line and len(parts)==1 and parts[0]==line else None


def parse_order_event(text:str)->re.Match[str]|None:
    line=exact_line(text)
    match=ORDER_EVENT_RE.fullmatch(line) if line is not None else None
    if not match:return None
    status,average=match.group("status"),match.group("average")
    if (status=="filled") != (average is not None):return None
    if any(float(match.group(field))<=0 for field in ("limit","stop","target")):return None
    if average is not None and float(average)<=0:return None
    return match


def parse_order_events(text:str)->list[re.Match[str]]|None:
    body=text[:-1] if text.endswith("\n") else text
    if not body or "\r" in body:return None
    lines=body.split("\n")
    if not lines:return None
    events=[parse_order_event(line) for line in lines]
    return None if any(event is None for event in events) else events


def parse_failure_event(text:str)->str|None:
    line=exact_line(text)
    if line is None or not FAILURE_EVENT_RE.fullmatch(line):return None
    tokens=re.split(r"[:,]",line.split(maxsplit=1)[1])
    return line if tokens and all(token in ALLOWED_FAILURE_TOKENS for token in tokens) else None

def audit_result(mode:str,stage:str,returncode:int,stdout:str,path:Path=AUDIT_PATH)->None:
    first=(stdout.splitlines() or [""])[0]
    prefix=first.split(maxsplit=1)[0] if first else ""
    decisions={"BLOCKER":"blocked","AUTH_FAILURE":"auth_failure","SYSTEM_FAILURE":"system_failure"}
    decision=decisions.get(prefix,"completed" if returncode==0 else "failed")
    row={"timestamp":dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00","Z"),"mode":mode,"stage":stage,"decision":decision}
    if prefix=="TRADE" and returncode==0:
        trade_line=exact_line(stdout)
        trade_event=TRADE_EVENT_RE.fullmatch(trade_line) if trade_line is not None else None
        if trade_event and float(trade_event.group("price"))>0:
            row["decision"]="trade_filled";row["action"]=trade_event.group("action");row["symbol"]=trade_event.group("symbol")
    if prefix=="ORDER" and returncode==0:
        order_events=parse_order_events(stdout)
        if order_events:
            order_event=order_events[0]
            row["decision"]="trade_filled" if order_event.group("status")=="filled" else "order_placed"
            row["action"]=order_event.group("action");row["symbol"]=order_event.group("symbol")
    if prefix=="DECISION" and returncode==0:
        decision_line=exact_line(stdout)
        decision_event=DECISION_EVENT_RE.fullmatch(decision_line) if decision_line is not None else None
        if decision_event:
            if decision_event.group("event"):
                row["decision"]=decision_event.group("event");row["symbol"]=decision_event.group("symbol")
            else:
                row["decision"]="skipped";row["reason"]=decision_event.group("reason")
    if prefix in {"BLOCKER","AUTH_FAILURE","SYSTEM_FAILURE"}:
        safe_failure=parse_failure_event(stdout)
        if safe_failure:
            detail=safe_failure[len(prefix):].strip()
            tokens=re.findall(r"[A-Za-z][A-Za-z0-9_:-]{0,63}",detail)
            row["reason"]=",".join(tokens[:8]) or "unspecified"
        else:
            row["reason"]="unspecified"
    append_jsonl(path,row)

def in_window(mode:str,now:dt.datetime|None=None)->bool:
    n=(now or dt.datetime.now(NY)).astimezone(NY)
    if n.weekday()>4:return False
    t=n.time()
    windows={"premarket":(dt.time(7,0),dt.time(9,25)),"market":(dt.time(9,30),dt.time(16,0)),"postclose":(dt.time(16,10),dt.time(17,30)),"dashboard":(dt.time(9,30),dt.time(18,0))}
    lo,hi=windows[mode];return lo<=t<=hi

def execute(cmd:list[str],timeout_seconds:int=600,attempts:int=1,audit_mode:str|None=None,audit_stage:str="cycle",audit_path:Path=AUDIT_PATH)->int:
    result=None
    for _ in range(attempts):
        try:
            result=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            result=subprocess.CompletedProcess(cmd,124,"","timeout")
        if result.returncode==0:
            if audit_mode:audit_result(audit_mode,audit_stage,0,result.stdout,audit_path)
            if audit_mode in {"premarket","radar"} and audit_stage=="research":
                notice_name="Premarket Research" if audit_mode=="premarket" else "Alpha Radar"
                if result.stdout.strip()=="DECISION skipped no_fresh_setup":
                    print(f"{notice_name}: No new qualified candidate (no_fresh_setup). Research only; no order placed by this scan.")
                elif result.stdout.strip()=="DECISION skipped no_valid_discovery_candidate":
                    print(f"{notice_name}: No new qualified candidate (none passed discovery format validation). Research only; no order placed by this scan.")
                else:
                    match=re.fullmatch(r"DECISION (candidate_qualified|reused_fresh_candidate) ([A-Z]{1,6})",result.stdout.strip())
                    if match:
                        event,symbol=match.groups()
                        label=f"Final qualified candidate: {symbol}" if event=="candidate_qualified" else f"Reusing existing fresh candidate: {symbol} (not a new qualification)"
                        print(f"{notice_name}: {label}. Research only; not a trade approval or execution.")
            elif audit_mode=="autotrader" and audit_stage=="execution":
                order_events=parse_order_events(result.stdout)
                for order_event in order_events or []:
                    status=order_event.group("status");action=order_event.group("action")
                    quantity=order_event.group("quantity");symbol=order_event.group("symbol")
                    limit_price=order_event.group("limit");stop=order_event.group("stop");target=order_event.group("target")
                    if status=="placing":
                        print(f"Tradey Autotrader: Placing paper bracket order to Alpaca — {action} {quantity} {symbol} at limit ${limit_price}; stop ${stop}; target ${target}. This is a placement notice, not confirmation of acceptance or fill.")
                    elif status=="filled":
                        print(f"Tradey Autotrader: Paper bracket order filled — {action} {quantity} {symbol}; average fill ${order_event.group('average')}; limit ${limit_price}; stop ${stop}; target ${target}. Broker-confirmed fill.")
                    else:
                        print(f"Tradey Autotrader: Paper bracket order accepted — {action} {quantity} {symbol} at limit ${limit_price}; stop ${stop}; target ${target}. Broker status: {status}. This confirms order acceptance, not a fill.")
            return 0
    if result:
        safe_failure=parse_failure_event(result.stdout)
        print(safe_failure or "SYSTEM_FAILURE scheduled_task")
    if result and audit_mode:audit_result(audit_mode,audit_stage,result.returncode,result.stdout,audit_path)
    return result.returncode if result else 4

def completed_today(mode:str,state:Path|None=None)->bool:
    directory=state or ROOT/"state";p=directory/f"{mode}.date";today=dt.datetime.now(NY).date().isoformat()
    return p.exists() and p.read_text().strip()==today

def mark_completed(mode:str,state:Path|None=None)->None:
    directory=state or ROOT/"state";directory.mkdir(exist_ok=True);p=directory/f"{mode}.date"
    p.write_text(dt.datetime.now(NY).date().isoformat())

def scheduled_slot(mode:str,now:dt.datetime|None=None)->bool:
    """Return whether this fire matches the NY-time producer/consumer cadence."""
    n=(now or dt.datetime.now(NY)).astimezone(NY)
    if mode=="premarket":return n.hour==9 and n.minute==0
    if mode=="radar":return 10<=n.hour<=15 and n.minute in {0,30}
    if mode=="autotrader":
        return (n.hour==9 and n.minute==40) or (10<=n.hour<=15 and n.minute in {20,50})
    return True


def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("mode",choices=["premarket","radar","autotrader","postclose","dashboard"]);a=ap.parse_args()
    if not scheduled_slot(a.mode):return 0
    window="market" if a.mode in {"radar","autotrader"} else a.mode
    if not in_window(window):audit_result(a.mode,"schedule",0,"DECISION skipped outside_window");return 0
    daily=a.mode in {"premarket","postclose"}
    if daily and completed_today(a.mode):audit_result(a.mode,"schedule",0,"DECISION skipped already_completed");return 0
    if a.mode in {"premarket","radar"}:rc=execute([sys.executable,str(ROOT/"alpha_radar.py")],timeout_seconds=1110,attempts=1,audit_mode=a.mode,audit_stage="research")
    elif a.mode=="autotrader":rc=execute([sys.executable,str(ROOT/"autotrader.py")],timeout_seconds=600,attempts=1,audit_mode=a.mode,audit_stage="execution")
    elif a.mode=="postclose":
        rc=execute([sys.executable,str(ROOT/"candidate_outcomes.py")],timeout_seconds=300,attempts=2,audit_mode=a.mode,audit_stage="outcome_measurement")
        if not rc:
            execute([sys.executable,str(ROOT/"shadow_calibration.py")],timeout_seconds=300,attempts=1)
            rc=execute([sys.executable,str(ROOT/"public_dashboard.py")],timeout_seconds=120,attempts=2,audit_mode=a.mode,audit_stage="dashboard_build")
    else:rc=execute(["bash",str(ROOT/"deploy_dashboard.sh")],timeout_seconds=300,attempts=2,audit_mode=a.mode,audit_stage="deployment")
    if daily and rc==0:mark_completed(a.mode)
    return rc
def cli()->int:
    try:
        return main()
    except DurableAppendError:
        print("SYSTEM_FAILURE audit_persistence_failure")
        return 3

if __name__=="__main__":raise SystemExit(cli())
