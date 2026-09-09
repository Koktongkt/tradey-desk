#!/usr/bin/env python3
"""Timezone-aware silent cron entry point."""
from __future__ import annotations
import argparse,datetime as dt,json,re,subprocess,sys
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent
NY=ZoneInfo("America/New_York")
AUDIT_PATH=ROOT/"decision_audit.jsonl"

def audit_result(mode:str,stage:str,returncode:int,stdout:str,path:Path=AUDIT_PATH)->None:
    first=(stdout.strip().splitlines() or [""])[0]
    prefix=first.split(maxsplit=1)[0] if first else ""
    decisions={"BLOCKER":"blocked","AUTH_FAILURE":"auth_failure","SYSTEM_FAILURE":"system_failure","TRADE":"trade_filled"}
    decision=decisions.get(prefix,"completed" if returncode==0 else "failed")
    row={"timestamp":dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00","Z"),"mode":mode,"stage":stage,"decision":decision}
    if prefix=="TRADE":
        parts=first.split()
        if len(parts)>=2 and parts[1] in {"BUY","SELL"}:row["action"]=parts[1]
        symbol=next((part for part in parts[2:] if re.fullmatch(r"[A-Z]{1,6}",part)),None)
        if symbol:row["symbol"]=symbol
    if prefix=="DECISION":
        parts=first.split()
        if len(parts)>=2 and parts[1] in {"candidate_qualified"}:
            row["decision"]=parts[1]
            if len(parts)>=3 and re.fullmatch(r"[A-Z]{1,6}",parts[2]):row["symbol"]=parts[2]
        elif len(parts)>=2 and parts[1]=="skipped" and len(parts)>=3 and parts[2] in {"outside_window","already_completed","already_reviewed","no_fresh_setup"}:
            row["decision"]="skipped";row["reason"]=parts[2]
        elif len(parts)>=2 and parts[1]=="reused_fresh_candidate":
            row["decision"]="reused_fresh_candidate"
            if len(parts)>=3 and re.fullmatch(r"[A-Z]{1,6}",parts[2]):row["symbol"]=parts[2]
    if prefix in {"BLOCKER","AUTH_FAILURE","SYSTEM_FAILURE"}:
        detail=first[len(prefix):].strip()
        tokens=re.findall(r"[A-Za-z][A-Za-z0-9_:-]{0,63}",detail)
        row["reason"]=",".join(tokens[:8]) or "unspecified"
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as f:f.write(json.dumps(row,sort_keys=True,separators=(",",":"))+"\n")

def in_window(mode:str,now:dt.datetime|None=None)->bool:
    n=(now or dt.datetime.now(NY)).astimezone(NY)
    if n.weekday()>4:return False
    t=n.time()
    windows={"premarket":(dt.time(7,0),dt.time(9,25)),"market":(dt.time(9,30),dt.time(16,0)),"postclose":(dt.time(16,10),dt.time(17,30)),"dashboard":(dt.time(16,15),dt.time(18,0))}
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
            return 0
    if result and result.stdout.strip():print(result.stdout.strip())
    elif result:print("SYSTEM_FAILURE scheduled_task")
    if result and audit_mode:audit_result(audit_mode,audit_stage,result.returncode,result.stdout,audit_path)
    return result.returncode if result else 4

def completed_today(mode:str,state:Path|None=None)->bool:
    directory=state or ROOT/"state";p=directory/f"{mode}.date";today=dt.datetime.now(NY).date().isoformat()
    return p.exists() and p.read_text().strip()==today

def mark_completed(mode:str,state:Path|None=None)->None:
    directory=state or ROOT/"state";directory.mkdir(exist_ok=True);p=directory/f"{mode}.date"
    p.write_text(dt.datetime.now(NY).date().isoformat())

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("mode",choices=["premarket","radar","autotrader","postclose","dashboard"]);a=ap.parse_args()
    window="market" if a.mode in {"radar","autotrader"} else a.mode
    if not in_window(window):audit_result(a.mode,"schedule",0,"DECISION skipped outside_window");return 0
    daily=a.mode in {"premarket","postclose","dashboard"}
    if daily and completed_today(a.mode):audit_result(a.mode,"schedule",0,"DECISION skipped already_completed");return 0
    if a.mode in {"premarket","radar"}:rc=execute([sys.executable,str(ROOT/"alpha_radar.py")],timeout_seconds=360,attempts=1,audit_mode=a.mode,audit_stage="research")
    elif a.mode=="autotrader":rc=execute([sys.executable,str(ROOT/"autotrader.py")],timeout_seconds=600,attempts=1,audit_mode=a.mode,audit_stage="execution")
    elif a.mode=="postclose":
        rc=execute([sys.executable,str(ROOT/"candidate_outcomes.py")],timeout_seconds=300,attempts=2,audit_mode=a.mode,audit_stage="outcome_measurement")
        if not rc:
            execute([sys.executable,str(ROOT/"shadow_calibration.py")],timeout_seconds=300,attempts=1)
            rc=execute([sys.executable,str(ROOT/"public_dashboard.py")],timeout_seconds=120,attempts=2,audit_mode=a.mode,audit_stage="dashboard_build")
    else:rc=execute(["bash",str(ROOT/"deploy_dashboard.sh")],timeout_seconds=300,attempts=2,audit_mode=a.mode,audit_stage="deployment")
    if daily and rc==0:mark_completed(a.mode)
    return rc
if __name__=="__main__":raise SystemExit(main())
