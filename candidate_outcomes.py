#!/usr/bin/env python3
"""Read-only candidate measurement versus SPY; never changes risk or orders."""
from __future__ import annotations
import argparse,hashlib,json,subprocess
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parent
H=(1,3,5,10)

def measure(x:dict[str,Any])->dict[str,Any]:
    out=dict(x); ep=float(x["entry_price"]); sp=float(x["spy_entry"])
    for h in H:
        k=str(h)
        if k in x.get("prices",{}) and k in x.get("spy_prices",{}):
            r=(float(x["prices"][k])/ep-1)*100; sr=(float(x["spy_prices"][k])/sp-1)*100
            out[f"return_{h}s_pct"]=round(r,6); out[f"spy_return_{h}s_pct"]=round(sr,6); out[f"excess_{h}s_pct"]=round(r-sr,6)
    return out

def append(row:dict[str,Any])->None:
    with (ROOT/"candidate_outcomes.jsonl").open("a",encoding="utf-8") as f:f.write(json.dumps(row,sort_keys=True,separators=(",",":"))+"\n")

def read_rows(path:Path)->list[dict[str,Any]]:
    out=[]
    if not path.exists():return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:out.append(json.loads(line))
        except json.JSONDecodeError:pass
    return out

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--fixture"); a=ap.parse_args()
    try:
        if a.fixture: data=json.loads(Path(a.fixture).read_text())
        else:
            candidates=read_rows(ROOT/"candidates.jsonl"); trades=read_rows(ROOT/"trade_journal.jsonl")
            traded_symbols={str(t.get("symbol","")).upper() for t in trades if t.get("status")=="filled"}
            for c in candidates:
                c.setdefault("candidate_id",hashlib.sha256(f"{c.get('symbol')}|{c.get('researched_at')}".encode()).hexdigest()[:20])
                c["traded"]=str(c.get("symbol","")).upper() in traded_symbols
            p=subprocess.run(["uv","run","--with","fastmcp","python",str(ROOT/"broker_mcp_bridge.py"),"outcomes"],input=json.dumps({"candidates":candidates}),text=True,capture_output=True,timeout=180)
            if p.returncode: raise RuntimeError
            data=json.loads(p.stdout)
        for row in data: append(measure(row))
        return 0
    except Exception:
        print("SYSTEM_FAILURE candidate_outcomes"); return 4
if __name__=="__main__":raise SystemExit(main())
