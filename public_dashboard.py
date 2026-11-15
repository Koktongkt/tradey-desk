#!/usr/bin/env python3
"""Build the sanitized, public paper-trading dashboard."""
from __future__ import annotations
import json
import math
import statistics
import subprocess
from broker_process import bridge_command, broker_executable, run_bridge
from pathlib import Path
from typing import Any
from durable_jsonl import read_jsonl
from watchdog.reports import dashboard_summary
ROOT=Path(__file__).resolve().parent
SAFE_LEDGER={"timestamp","status","reason","symbol","action","quantity","order_type","limit_price","evidence_id"}
SAFE_AUDIT={"timestamp","mode","stage","decision","reason","symbol","action"}
SAFE_STATUS={"enabled","broker_mode","account_cap_usd","max_position_usd","max_daily_orders","min_reward_risk"}
HORIZONS=(1,3,5,10)
SAFE_OUTCOME={"candidate_id","symbol","traded"}|{f"{prefix}_{h}s_pct" for prefix in ("return","spy_return","excess") for h in HORIZONS}
SAFE_DIAG_MEASURED={"bid","ask","midpoint","spread_bps","limit_price","reference_price","reference_side","deviation_bps","risk_reward","earnings_status","earnings_sessions_away","average_volume","quote_age_seconds","cash","buying_power","dollar_basis","planned_risk_usd","current_position_value","quote_feed","allowed_quote_feeds"}
SAFE_DIAG_THRESHOLD={"max_spread_bps","max_limit_deviation_bps","min_reward_risk","earnings_blackout_sessions","min_average_volume","max_quote_age_seconds","max_position_usd","max_planned_risk_per_trade_usd"}
SAFE_PORTFOLIO_SUMMARY={"total_balance_usd","cash_usd","positions_value_usd","balance_reconciliation_difference_usd","day_pl_usd","day_return_pct","spy_day_return_pct","day_excess_pct"}
SAFE_HOLDING={"symbol","quantity","average_entry_price","current_price","market_value","cost_basis","unrealized_pl_usd","unrealized_return_pct","day_pl_usd","day_return_pct"}
DIAG_STAGE_SUMMARIES={
    "precheck":"A deterministic desk gate blocked the candidate before independent review.",
    "final_validation":"A deterministic desk gate blocked the approved plan before submission.",
    "broker_review":"A fresh broker state check just before submission blocked the order.",
}
ACTIVITY_SUMMARIES={
    "outside_window":"The scheduled cycle was outside its permitted market window, so no review or order ran.",
    "already_completed":"This scheduled cycle had already completed for the day, so the duplicate run was skipped.",
    "candidate_qualified":"The candidate passed the desk's initial research-quality checks and advanced to independent review.",
    "consensus_hold":"Both reviewers independently chose to hold, so the desk submitted no order.",
    "model_disagreement":"The independent reviewers did not agree on the same action, so the idea was blocked.",
    "reviewer_unavailable":"At least one independent reviewer was unavailable, so the desk failed closed and submitted no order.",
    "malformed_or_low_confidence":"At least one review was malformed or below the required confidence threshold, so no order was allowed.",
    "proposal_hash_mismatch":"A reviewer response did not match the immutable proposal hash, so it was rejected rather than applied to a different order.",
    "malformed_review":"At least one reviewer response did not satisfy the required immutable approval schema, so no order was allowed.",
    "low_confidence":"At least one reviewer's deterministic rubric score was below the required conviction threshold, so no order was allowed.",
    "reviewer_veto":"At least one independent reviewer raised a fatal flag and vetoed the immutable proposal.",
    "invalid_horizon":"The planned exit did not map to a permitted 1–30 exchange-session holding period, so the candidate was blocked.",
    "horizon_session_mismatch":"The claimed holding period disagreed with the broker exchange calendar, so the candidate was blocked.",
    "trading_calendar_unavailable":"The exchange-session calendar was unavailable, so the desk could not assign a trading horizon and failed closed.",
    "planned_risk_policy_missing":"The fixed planned-loss policy was unavailable, so deterministic position sizing failed closed.",
    "planned_risk_exceeded":"The exact entry, stop, and whole-share quantity exceeded the fixed planned-loss limit, so no order was allowed.",
    "technical_bars_unavailable":"Completed consolidated daily bars were unavailable or invalid, so deterministic stop and target levels could not be created.",
    "unsupported_technical_setup":"The setup type and assigned horizon did not map to an approved deterministic level method, so the candidate was blocked.",
    "level_disagreement":"The reviewers disagreed on required price or risk levels, so no order was allowed.",
    "order_detail_disagreement":"The reviewers disagreed on one or more order details, so no order was allowed.",
    "stale_or_unverified_research":"The research evidence was stale or could not be verified, so the candidate did not advance.",
    "broker_mcp_unavailable":"The broker read-only connection was unavailable, so the desk could not validate account state and failed closed.",
    "candidate_outcomes":"Candidate outcome measurements were refreshed for benchmark-relative tracking.",
    "trade_filled":"The broker confirmed the fill; only this confirmed activity counts as a trade.",
    "completed":"The scheduled cycle completed without an order or reportable blocker.",
    "auth_failure":"Required authentication was unavailable, so the cycle stopped without placing an order.",
    "system_failure":"A system step failed, so the cycle stopped without placing an order.",
    "proposed":"Both reviewers agreed on an executable plan that advanced to deterministic risk validation.",
    "placed":"The paper broker accepted the protected limit order; fill status still required broker readback.",
    "pending":"The paper order remained open or pending at the latest broker readback.",
    "partial":"The paper order was only partially filled at the latest broker readback.",
    "filled":"The broker confirmed the paper order fill.",
    "failed":"The order lifecycle failed safely and did not produce a confirmed fill.",
    "rejected":"The idea did not clear all required review and deterministic safety gates, so no order was submitted.",
    "skipped":"The scheduled cycle was intentionally skipped without placing an order.",
    "blocked":"A required desk gate blocked the cycle before an order could be placed.",
    "blocker_diagnostics":"Measured values and configured thresholds behind a blocked cycle, recorded for troubleshooting.",
}

def rows(path:Path)->list[dict[str,Any]]:
    return read_jsonl(path)

OVERLAY_DIRNAMES={"audit":"decision_audit.jsonl","ledger":"order_ledger.jsonl","candidates":"candidates.jsonl"}

def _overlay_identity(row:dict[str,Any],kind:str)->tuple[str,...]|None:
    timestamp=row.get("timestamp") if kind!="candidates" else row.get("researched_at")
    if not isinstance(timestamp,str): return None
    if kind=="audit": return (timestamp,str(row.get("mode") or ""),str(row.get("decision") or ""))
    if kind=="ledger": return (timestamp,str(row.get("status") or ""),str(row.get("action") or ""),str(row.get("symbol") or ""))
    return (timestamp,str(row.get("symbol") or ""))

def load_overlay_rows(root:Path,config:dict[str,Any],kind:str)->list[dict[str,Any]]:
    """Load optional public-history continuity overlay rows for one stream.

    Overlay files live under public/overlay/ and are derived only from
    sanitized public production artifacts; they are consumed only when the
    explicit public_history_overlay config flag is enabled.
    """
    if not isinstance(config.get("public_history_overlay"),bool) or not config["public_history_overlay"]:
        return []
    return rows(root/"public"/"overlay"/OVERLAY_DIRNAMES[kind])

def merge_overlay(canonical:list[dict[str,Any]],overlay:list[dict[str,Any]],kind:str)->list[dict[str,Any]]:
    """Append overlay rows that are not already present in the canonical stream."""
    seen={_overlay_identity(r,kind) for r in canonical}
    merged=list(canonical)
    for row in overlay:
        identity=_overlay_identity(row,kind)
        if identity is None or identity in seen: continue
        seen.add(identity); merged.append(row)
    return merged

def sanitize_ledger_row(row:dict[str,Any])->dict[str,Any]:
    out={k:row[k] for k in SAFE_LEDGER if k in row}
    if "symbol" not in out:
        reviews=row.get("reviews") or []
        for review in reviews:
            if isinstance(review,dict) and review.get("symbol"):
                out["symbol"]=str(review["symbol"]); break
    out["summary"]=activity_summary(out)
    return out

def activity_summary(row:dict[str,Any])->str:
    reason=row.get("reason")
    reason_codes=[reason] if isinstance(reason,str) else reason if isinstance(reason,list) else []
    for code in reason_codes:
        if code in ACTIVITY_SUMMARIES: return ACTIVITY_SUMMARIES[code]
    for key in ("decision","status"):
        code=row.get(key)
        if code in ACTIVITY_SUMMARIES: return ACTIVITY_SUMMARIES[code]
    return "A sanitized desk lifecycle event was recorded; private operational details remain withheld."

def sanitize_audit_row(row:dict[str,Any])->dict[str,Any]:
    out={k:row[k] for k in SAFE_AUDIT if k in row}
    out["summary"]=activity_summary(out)
    return out

def sanitize_candidate_row(row:dict[str,Any])->dict[str,Any]:
    out={}
    if isinstance(row.get("researched_at"),str): out["timestamp"]=row["researched_at"]
    if isinstance(row.get("symbol"),str): out["symbol"]=row["symbol"]
    out["summary"]="Passed the desk's initial research-quality and source-verification checks."
    return out

def sanitize_diagnostics_row(row:dict[str,Any])->dict[str,Any]:
    """Allowlist projection of a private blocker-diagnostics row.

    Only measured market/policy values and configured thresholds are
    published; identifiers, hashes, and any extra field are dropped.
    """
    measured={k:row.get("measured",{}).get(k) for k in SAFE_DIAG_MEASURED if row.get("measured",{}).get(k) is not None}
    threshold={k:row.get("threshold",{}).get(k) for k in SAFE_DIAG_THRESHOLD if row.get("threshold",{}).get(k) is not None}
    out={"timestamp":row.get("timestamp"),"reason":row.get("reason"),"stage":row.get("stage")}
    if isinstance(row.get("symbol"),str) and row["symbol"].isalpha(): out["symbol"]=row["symbol"]
    if isinstance(row.get("action"),str) and row["action"] in {"BUY","SELL"}: out["action"]=row["action"]
    out["measured"]=measured; out["threshold"]=threshold
    out["summary"]=DIAG_STAGE_SUMMARIES.get(row.get("stage"),ACTIVITY_SUMMARIES["blocked"])
    return out

def sanitize_portfolio_snapshot(snapshot:dict[str,Any]|None)->dict[str,Any]:
    source=snapshot if isinstance(snapshot,dict) else {}
    summary=source.get("summary") if isinstance(source.get("summary"),dict) else {}
    safe_summary={k:summary[k] for k in SAFE_PORTFOLIO_SUMMARY if k in summary}
    for key in ("total_balance_usd","cash_usd","positions_value_usd","balance_reconciliation_difference_usd"):
        value=summary.get(key)
        try:safe_summary[key]=value if type(value) in (int,float) and math.isfinite(value) else None
        except OverflowError:safe_summary[key]=None
    holdings=[]
    for row in source.get("holdings") or []:
        if not isinstance(row,dict):continue
        safe={k:row[k] for k in SAFE_HOLDING if k in row}
        if isinstance(safe.get("symbol"),str) and safe["symbol"].isalpha():holdings.append(safe)
    return {
        "captured_at":source.get("captured_at") if isinstance(source.get("captured_at"),str) else None,
        "feed":"alpaca_paper_iex" if source.get("feed")=="alpaca_paper_iex" else None,
        "summary":safe_summary,
        "holdings":holdings,
    }

def fetch_live_portfolio(root:Path=ROOT)->dict[str,Any]:
    completed=run_bridge(bridge_command(root,"portfolio",executable=broker_executable()),
                         input="{}",timeout=90,cwd=root,run=subprocess.run)
    if completed.returncode!=0:raise RuntimeError("broker_portfolio_unavailable")
    payload=json.loads(completed.stdout)
    if not isinstance(payload,dict):raise RuntimeError("broker_portfolio_invalid")
    return payload

def build_data(root:Path=ROOT,portfolio_snapshot:dict[str,Any]|None=None)->dict[str,Any]:
    config={}
    config_path=root/"autonomy_config.json"
    if config_path.exists():
        try: config=json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError,OSError): pass
    ledger=rows(root/"order_ledger.jsonl"); raw_outcomes=rows(root/"candidate_outcomes.jsonl"); trades=rows(root/"trade_journal.jsonl"); candidates=rows(root/"candidates.jsonl"); audit=rows(root/"decision_audit.jsonl"); diagnostics=rows(root/"private"/"blocker_diagnostics.jsonl")
    ledger=merge_overlay(ledger,load_overlay_rows(root,config,"ledger"),"ledger")
    candidates=merge_overlay(candidates,load_overlay_rows(root,config,"candidates"),"candidates")
    audit=merge_overlay(audit,load_overlay_rows(root,config,"audit"),"audit")
    latest={str(r.get("candidate_id") or i):r for i,r in enumerate(raw_outcomes)}; outcomes=list(latest.values())
    rejected=[r for r in ledger if r.get("status")=="rejected"]
    disagreements=[r for r in rejected if r.get("reason")=="model_disagreement" or "model_disagreement" in (r.get("reason") or [])]
    unavailable=[r for r in rejected if r.get("reason")=="reviewer_unavailable" or "reviewer_unavailable" in (r.get("reason") or [])]
    review_block_reasons={"model_disagreement","reviewer_unavailable","malformed_or_low_confidence","proposal_hash_mismatch","malformed_review","low_confidence","reviewer_veto","level_disagreement","order_detail_disagreement","consensus_hold"}
    review_rows=[r for r in rejected if (r.get("reason") in review_block_reasons if isinstance(r.get("reason"),str) else any(x in review_block_reasons for x in (r.get("reason") or [])))]
    agreements=sum(1 for r in ledger if r.get("status")=="proposed")
    vals=[float(r["excess_5s_pct"]) for r in outcomes if isinstance(r.get("excess_5s_pct"),(int,float))]
    traded=[r for r in outcomes if r.get("traded")];    skipped=[r for r in outcomes if not r.get("traded")]
    def summary(group:list[dict[str,Any]],horizon:int)->dict[str,Any]:
        key=f"excess_{horizon}s_pct"
        numbers=[float(r[key]) for r in group if isinstance(r.get(key),(int,float))]
        return {"count":len(numbers),"avg_excess_pct":round(statistics.mean(numbers),4) if numbers else None}
    timestamps=[str(r["timestamp"]) for r in ledger+audit if r.get("timestamp")]
    return {
        "desk_status":{k:config[k] for k in SAFE_STATUS if k in config},
        "live_portfolio":sanitize_portfolio_snapshot(portfolio_snapshot),
        "watchdog":dashboard_summary(root/"private/watchdog/monitoring.sqlite3"),
        "last_activity_at":max(timestamps) if timestamps else None,
        "performance":{"avg_excess_5s_pct":round(statistics.mean(vals),4) if vals else None,"confirmed_trades":len(trades),"qualified_candidates":len(candidates) if candidates else len(outcomes),"traded_candidates":len(traded),"skipped_candidates":len(skipped)},
        "reviews":{"total_dual_model_reviews":len(review_rows)+agreements,"agreements":agreements,"disagreements":len(disagreements),"unavailable":len(unavailable)},
        "outcome_horizons":{str(h):{"traded":summary(traded,h),"skipped":summary(skipped,h)} for h in HORIZONS},
        "researched_candidates":[sanitize_candidate_row(r) for r in candidates],
        "decision_audit":[sanitize_audit_row(r) for r in audit],
        "blocker_diagnostics":[sanitize_diagnostics_row(r) for r in diagnostics],
        "blocked_disagreements":[sanitize_ledger_row(r) for r in review_rows],
        "recent_orders":[sanitize_ledger_row(r) for r in ledger],
        "outcomes":[{k:r[k] for k in SAFE_OUTCOME if k in r} for r in outcomes[-100:]]
    }

def html_template()->str:
    return '''<!doctype html>
<html lang="en" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>Tradey Desk — Paper trading monitor</title>
<script data-theme-init>(function(){var r=document.documentElement;try{var t=localStorage.getItem('tradey-theme');if(t==='light'||t==='dark')r.setAttribute('data-theme',t)}catch(e){}document.addEventListener('click',function(e){var b=e.target&&e.target.closest&&e.target.closest('[data-theme-toggle]');if(!b)return;var n=r.getAttribute('data-theme')==='light'?'dark':'light';r.setAttribute('data-theme',n);try{localStorage.setItem('tradey-theme',n)}catch(err){}})})();</script>
<style>
:root,[data-theme="dark"]{--bg:#0a0c0f;--surface:#111419;--surface-2:#161a21;--hover:#1a1f27;--line:#20262e;--line-2:#2b323c;--ink:#e7ebf0;--muted:#8a94a2;--faint:#5c6673;--accent:#38d3c3;--accent-soft:rgba(56,211,195,.12);--pos:#2fcf8a;--pos-soft:rgba(47,207,138,.12);--neg:#ff6161;--neg-soft:rgba(255,97,97,.12);--warn:#f0b54a;--warn-soft:rgba(240,181,74,.12);--shadow:0 1px 0 rgba(255,255,255,.03) inset,0 10px 30px -18px rgba(0,0,0,.8)}
[data-theme="light"]{--bg:#f4f5f7;--surface:#ffffff;--surface-2:#f8f9fb;--hover:#f1f3f6;--line:#e4e7ec;--line-2:#d4d9e0;--ink:#0e1621;--muted:#586373;--faint:#8b94a1;--accent:#0b8a80;--accent-soft:rgba(11,138,128,.10);--pos:#0d8656;--pos-soft:rgba(13,134,86,.10);--neg:#cf3434;--neg-soft:rgba(207,52,52,.09);--warn:#a86b0c;--warn-soft:rgba(168,107,12,.10);--shadow:0 1px 2px rgba(16,24,40,.04),0 8px 24px -16px rgba(16,24,40,.18)}
:root{--mono:ui-monospace,"JetBrains Mono","SF Mono","IBM Plex Mono",Menlo,Consolas,monospace;--sans:"Inter Tight","Geist",-apple-system,"Segoe UI Variable","Segoe UI",system-ui,sans-serif;--r:8px}
*{box-sizing:border-box}html{background:var(--bg);color:var(--ink);font-family:var(--sans);-webkit-font-smoothing:antialiased;transition:background .2s,color .2s}body{margin:0;font-size:14px;line-height:1.45}
.num,.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.shell{max-width:1320px;margin:0 auto;padding:0 28px 56px}
.topbar{position:sticky;top:0;z-index:5;display:flex;align-items:center;justify-content:space-between;gap:16px;margin:0 -28px 22px;padding:14px 28px;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:saturate(1.4) blur(8px);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:11px;font-weight:650;font-size:15px;letter-spacing:-.01em}.brand small{display:block;font-weight:500;font-size:11px;color:var(--muted);letter-spacing:0}
.mark{width:26px;height:26px;border-radius:7px;background:var(--ink);position:relative;flex:none}.mark:before,.mark:after{content:"";position:absolute;bottom:6px;width:4px;border-radius:1px;background:var(--bg)}.mark:before{left:7px;height:9px}.mark:after{left:14px;height:14px;background:var(--accent)}
.top-right{display:flex;align-items:center;gap:10px}
.pill{display:inline-flex;align-items:center;gap:7px;height:28px;padding:0 11px;border:1px solid var(--line-2);border-radius:999px;font:600 11px var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--ink);white-space:nowrap}
.dot{width:7px;height:7px;border-radius:50%;background:var(--pos);box-shadow:0 0 0 3px var(--pos-soft);animation:pulse 2.4s ease-in-out infinite}.dot.off{background:var(--warn);box-shadow:0 0 0 3px var(--warn-soft);animation:none}
@keyframes pulse{50%{box-shadow:0 0 0 6px transparent}}
.stamp{font:11px var(--mono);color:var(--muted);white-space:nowrap}
.icon-btn{display:inline-grid;place-items:center;width:32px;height:32px;border-radius:8px;border:1px solid var(--line-2);background:var(--surface);color:var(--ink);cursor:pointer;transition:background .15s,border-color .15s}.icon-btn:hover{background:var(--hover);border-color:var(--faint)}.icon-btn svg{width:15px;height:15px}
[data-theme="dark"] .i-sun{display:none}[data-theme="light"] .i-moon{display:none}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.eyebrow{font:600 10.5px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow)}
.kpis{display:grid;grid-template-columns:1.5fr repeat(4,minmax(0,1fr));gap:12px;margin-bottom:22px}
.kpi{padding:18px 18px 16px;min-width:0}.kpi strong{display:block;font:600 26px/1.1 var(--mono);font-variant-numeric:tabular-nums;letter-spacing:-.03em;margin:12px 0 8px;overflow-wrap:anywhere}.kpi small{display:block;color:var(--muted);font-size:12px;line-height:1.4}
.kpi.balance strong{font-size:34px}.kpi-split{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px;padding-top:10px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}.kpi-split b{display:block;color:var(--ink);font:600 13px var(--mono);font-variant-numeric:tabular-nums;margin-top:2px}
.kpi .stampline{margin-top:8px;font:11px var(--mono);color:var(--faint)}
.positive{color:var(--pos)}.negative{color:var(--neg)}
.chg{display:inline-block;padding:2px 7px;border-radius:5px;font:600 12px var(--mono);font-variant-numeric:tabular-nums}.chg.positive{background:var(--pos-soft)}.chg.negative{background:var(--neg-soft)}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:22px;align-items:start}
.rail{display:grid;gap:14px;min-width:0}.main-col{min-width:0}
.section{margin-top:30px}.layout .section:first-child{margin-top:0}
.section-head{display:flex;align-items:end;justify-content:space-between;gap:20px;margin-bottom:12px}.section h2{font-size:17px;font-weight:650;letter-spacing:-.015em;margin:4px 0 0}.section-head p{margin:0;color:var(--muted);font-size:12px;text-align:right}
.card{padding:16px 18px}.card h2{font-size:14px;font-weight:650;margin:0;display:flex;justify-content:space-between;align-items:center;gap:10px}
.badge{display:inline-flex;align-items:center;flex:none;white-space:nowrap;height:20px;padding:0 7px;border-radius:5px;font:600 10px var(--mono);letter-spacing:.06em;text-transform:uppercase;background:var(--hover);color:var(--muted);border:1px solid var(--line)}.badge.ok{color:var(--pos);background:var(--pos-soft);border-color:transparent}.badge.warn{color:var(--warn);background:var(--warn-soft);border-color:transparent}.badge.bad{color:var(--neg);background:var(--neg-soft);border-color:transparent}
.spec{margin:12px 0 0;padding:0;list-style:none}.spec li{display:flex;justify-content:space-between;gap:16px;padding:9px 0;border-top:1px solid var(--line);font-size:12.5px;color:var(--muted)}.spec li b{color:var(--ink);font:600 12.5px var(--mono);font-variant-numeric:tabular-nums;text-align:right}
.wd-row{padding:12px 0;border-top:1px solid var(--line)}.wd-row:first-of-type{margin-top:12px}.wd-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px}.wd-head span{font-size:12.5px;color:var(--muted)}.wd-head b{font:600 15px var(--mono);font-variant-numeric:tabular-nums}.wd-meta{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;margin-top:7px;font-size:11.5px;color:var(--muted)}
.fine{margin:12px 0 0;color:var(--faint);font-size:11.5px;line-height:1.5}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:right;padding:12px 16px;border-bottom:1px solid var(--line);white-space:nowrap}th:first-child,td:first-child{text-align:left}th{font:600 10.5px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted);background:var(--surface-2)}td{font-family:var(--mono);font-variant-numeric:tabular-nums}tbody tr{transition:background .12s}tbody tr:hover{background:var(--hover)}tbody tr:last-child td{border-bottom:0}
.table-wrap{overflow-x:auto;border-radius:var(--r) var(--r) 0 0}.holding-symbol{font-weight:700;letter-spacing:.03em}.holding-symbol:before{content:"";display:inline-block;width:6px;height:6px;border-radius:2px;background:var(--accent);margin-right:9px;vertical-align:middle}
.portfolio-note{padding:12px 16px;border-top:1px solid var(--line);color:var(--faint);font-size:11.5px;line-height:1.55}.portfolio-panel .empty{padding:28px 16px}
.funnel{padding:8px 18px}.f-row{display:grid;grid-template-columns:190px minmax(0,1fr) 120px;gap:18px;align-items:center;padding:12px 0;border-bottom:1px solid var(--line)}.f-row:last-child{border-bottom:0}.f-label span{font:600 10.5px var(--mono);color:var(--faint);margin-right:8px}.f-label b{font-size:13px;font-weight:600}.f-label small{display:block;color:var(--muted);font-size:11.5px;margin-top:2px}
.f-track{height:8px;border-radius:999px;background:var(--hover);overflow:hidden}.f-bar{height:100%;border-radius:inherit;background:var(--accent);transition:width .6s cubic-bezier(.2,.7,.2,1)}.f-bar.neg{background:var(--neg)}.f-bar.pos{background:var(--pos)}
.f-val{text-align:right}.f-val b{display:block;font:600 18px var(--mono);font-variant-numeric:tabular-nums}.f-val small{font-size:11px;color:var(--muted)}
.candidate-card{margin-top:10px}.candidate-card>summary{display:flex;justify-content:space-between;align-items:center;cursor:pointer;padding:13px 18px;font-size:13px;font-weight:600;list-style:none}.candidate-card>summary::-webkit-details-marker{display:none}.candidate-card>summary:before{content:"";width:6px;height:6px;border-right:1.5px solid var(--muted);border-bottom:1.5px solid var(--muted);transform:rotate(-45deg);margin-right:12px;transition:transform .15s}.candidate-card[open]>summary:before{transform:rotate(45deg)}.candidate-card>summary span{margin-right:auto}.candidate-card>summary em{font:11px var(--mono);font-style:normal;color:var(--muted)}.candidate-card>summary:hover{color:var(--accent)}
.candidate-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:28px;max-height:380px;overflow-y:auto;border-top:1px solid var(--line);padding:4px 18px 14px}.candidate-event{display:grid;grid-template-columns:118px 64px minmax(0,1fr);gap:12px;padding:10px 0;border-bottom:1px solid var(--line);align-items:center}.candidate-event time{font:11px var(--mono);color:var(--muted)}.candidate-event b{font:700 11.5px var(--mono);letter-spacing:.04em}.candidate-event span{font-size:12px;color:var(--muted);line-height:1.4}
.outcomes{overflow-x:auto}.outcomes-empty{display:flex;align-items:center;gap:14px;padding:16px 18px;color:var(--muted);font-size:13px}.outcomes-empty b{color:var(--ink);font-weight:600}
.activity-controls{display:flex;align-items:end;flex-wrap:wrap;gap:10px;margin:0 0 12px}.activity-controls label,.order-filters label{display:grid;gap:5px;font:600 10px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}.activity-controls select,.activity-controls input,.order-filters select{min-height:36px;border:1px solid var(--line-2);border-radius:7px;background:var(--surface);color:var(--ink);font:12px var(--mono);padding:7px 10px;color-scheme:inherit}.activity-controls select:hover,.order-filters select:hover{border-color:var(--faint)}.custom-dates{display:flex;align-items:end;gap:10px}.custom-dates[hidden]{display:none}.activity-range-note{margin-left:auto;color:var(--muted);font:11.5px var(--mono);padding-bottom:9px}
.tabs{display:flex;gap:2px;padding:6px;border-bottom:1px solid var(--line);background:var(--surface-2);border-radius:var(--r) var(--r) 0 0}.tab{display:inline-flex;align-items:center;gap:8px;height:34px;padding:0 14px;border:0;border-radius:6px;background:transparent;color:var(--muted);font:600 13px var(--sans);cursor:pointer;transition:background .12s,color .12s}.tab:hover{color:var(--ink)}.tab.active{background:var(--surface);color:var(--ink);box-shadow:0 0 0 1px var(--line-2)}.tab .count{font:600 10.5px var(--mono);padding:1px 6px;border-radius:4px;background:var(--hover);color:var(--muted)}.tab.active .count{background:var(--accent-soft);color:var(--accent)}
.tab-panel{padding:14px 18px 6px}.tab-panel[hidden]{display:none}.activity-note{color:var(--faint);font-size:12px;margin-bottom:8px}.order-filters{display:grid;grid-template-columns:minmax(140px,220px) minmax(180px,320px);gap:10px;margin:6px 0 10px}
.activity-list{max-height:640px;overflow-y:auto;padding-right:6px}
.event{display:grid;grid-template-columns:128px 64px minmax(0,1fr) auto;gap:6px 14px;padding:10px 6px;border-top:1px solid var(--line);align-items:center;border-radius:4px}.event:hover{background:var(--hover)}.event:first-child{border-top:0}.event time{font:11px var(--mono);color:var(--muted)}.event .ticker{justify-self:start;font:700 10.5px var(--mono);letter-spacing:.05em;background:var(--surface-2);border:1px solid var(--line-2);border-radius:4px;padding:2px 6px;white-space:nowrap}.event .no-ticker{color:var(--faint);font:11px var(--mono)}.event b.desc{font-size:13px;font-weight:550;line-height:1.4}.event em{font:600 10px var(--mono);font-style:normal;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);padding:2px 6px;border-radius:4px;background:var(--hover)}.event b.desc:before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;margin:0 8px 1px 0;background:var(--faint);vertical-align:middle}.event.rej b.desc:before{background:var(--neg)}.event.ok b.desc:before{background:var(--pos)}
.event-reason,.event-diagnostics{grid-column:3/-1}.event-reason summary,.event-diagnostics>summary{width:max-content;cursor:pointer;color:var(--accent);font:600 11px var(--mono);list-style:none}.event-reason summary::-webkit-details-marker,.event-diagnostics>summary::-webkit-details-marker{display:none}.event-reason summary:after,.event-diagnostics>summary:after{content:" +"}.event-reason[open] summary:after,.event-diagnostics[open]>summary:after{content:" −"}.event-reason p{margin:6px 0 2px;color:var(--muted);font-size:12px;line-height:1.5}
.diagnostic-detail{margin-top:6px;padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:var(--surface-2)}.diagnostic-detail>span{font:600 10px var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}.diag-grid{display:flex;flex-wrap:wrap;gap:4px 14px;padding-top:6px}.diag-pair{font:11px var(--mono);color:var(--muted)}.diag-pair em{font-style:normal;font-weight:700;color:var(--ink);margin-right:4px}
.empty{padding:26px 0;color:var(--muted);font-size:13px}
.method{display:grid;grid-template-columns:.8fr 1.2fr;gap:40px;padding:24px}.method>p{margin:0;color:var(--muted);line-height:1.6;font-size:13.5px}.method-list{display:grid;grid-template-columns:1fr 1fr;gap:20px 28px}.method-list b{display:block;font-size:13px;font-weight:600;margin-bottom:5px}.method-list span{color:var(--muted);font-size:12.5px;line-height:1.5;display:block}
footer{display:flex;justify-content:space-between;gap:20px;border-top:1px solid var(--line);margin-top:40px;padding-top:16px;color:var(--faint);font:11px var(--mono)}
.loading{display:grid;gap:12px}.skel{height:96px;border-radius:var(--r);background:linear-gradient(90deg,var(--surface) 0,var(--hover) 50%,var(--surface) 100%);background-size:200% 100%;animation:sk 1.4s linear infinite;border:1px solid var(--line)}@keyframes sk{to{background-position:-200% 0}}
@media(max-width:1100px){.kpis{grid-template-columns:repeat(3,minmax(0,1fr))}.kpi.balance{grid-column:1/-1}.layout{grid-template-columns:minmax(0,1fr)}.rail{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
@media(max-width:800px){.shell{padding:0 16px 40px}.topbar{margin:0 -16px 16px;padding:12px 16px}.stamp{display:none}.kpis{grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px}.kpi strong{font-size:22px}.kpi.balance strong{font-size:30px}.rail{grid-template-columns:minmax(0,1fr)}.f-row{grid-template-columns:1fr 90px;gap:8px 14px}.f-track{grid-column:1/-1;grid-row:2}.candidate-list,.method,.method-list{grid-template-columns:1fr}.section-head{align-items:start;flex-direction:column;gap:4px}.section-head p{text-align:left}.activity-range-note{width:100%;margin-left:0;padding:0}.order-filters{grid-template-columns:1fr 1fr}.event{grid-template-columns:104px auto minmax(0,1fr)}.event em{grid-column:3;justify-self:start}.event-reason,.event-diagnostics{grid-column:1/-1}}
@media(max-width:520px){.kpi{padding:14px}.kpi strong{font-size:20px}.pill .pill-mode{display:none}.custom-dates{width:100%;flex-wrap:wrap}.order-filters{grid-template-columns:1fr}.candidate-event{grid-template-columns:96px 52px minmax(0,1fr)}.tab{padding:0 10px;font-size:12px}footer{flex-direction:column}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head>
<body><main class="shell" id="app" aria-label="Tradey Desk dashboard"><header class="topbar"><div class="brand"><span class="mark" aria-hidden="true"></span><div>Tradey Desk<small>Autonomous paper desk</small></div></div></header><div class="loading" aria-label="Loading public desk data…"><div class="skel"></div><div class="skel"></div><div class="skel" style="height:280px"></div></div></main>
<script>
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=value=>Number(value??0).toLocaleString('en-US');
const money=value=>value==null?'—':`$${Number(value).toLocaleString('en-US')}`;
const balanceMoney=value=>typeof value!=='number'||!Number.isFinite(value)?'—':`$${value.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
const excess=value=>value==null?'—':`${value>0?'+':''}${Number(value).toFixed(2)}%`;
const signedMoney=value=>value==null?'—':`${value>0?'+':''}$${Number(value).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
const tone=value=>value==null?'':value>=0?'positive':'negative';
const shortTime=value=>{if(!value)return 'No activity yet';const date=new Date(value);return Number.isNaN(date.valueOf())?esc(value):date.toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'})};
const activityMatchesRange=(row,range,now=new Date(),from='',to='')=>{const date=new Date(row.timestamp);if(range==='all')return true;if(Number.isNaN(date.valueOf()))return false;let start,end=now;if(range==='today'){start=new Date(now.getFullYear(),now.getMonth(),now.getDate());end=new Date(start);end.setDate(end.getDate()+1)}else if(range==='custom'){if(!from&&!to)return true;start=from?new Date(`${from}T00:00:00`):new Date(0);end=to?new Date(`${to}T00:00:00`):now;if(to)end.setDate(end.getDate()+1)}else{const days={"24h":1,"5d":5,"week":7,"month":30,"year":365}[range]||1;start=new Date(now.valueOf()-days*86400000)}return date>=start&&date<end};
const reasonCodes=row=>Array.isArray(row.reason)?row.reason:typeof row.reason==='string'?[row.reason]:[];
const humanize=value=>String(value||'Update').replaceAll('_',' ');
const capFirst=value=>value.charAt(0).toUpperCase()+value.slice(1);
const orderMatchesFilters=(row,status,reason)=>{const approved=['proposed','placed','pending','partial','filled'].includes(row.status);const statusMatch=status==='all'||(status==='approved'&&approved)||(status==='rejected'&&row.status==='rejected');return statusMatch&&(reason==='all'||reasonCodes(row).includes(reason))};
const fmtVal=value=>value==null?'—':(typeof value==='number'?Number(value).toLocaleString('en-US',{maximumFractionDigits:2}):esc(String(value)));
const diagnosticDetails=rows=>rows.map(row=>{const pairs=[...Object.entries(row.measured||{}).map(([k,v])=>[humanize(k),v]),...Object.entries(row.threshold||{}).map(([k,v])=>['limit: '+humanize(k),v])];const detail=pairs.length?pairs.map(([k,v])=>`<span class="diag-pair"><em>${esc(k)}</em> ${fmtVal(v)}</span>`).join(''):'<span class="diag-pair"><em>context unavailable</em></span>';return `<div class="diagnostic-detail"><span>${esc(row.stage||'validation')}</span><div class="diag-grid">${detail}</div></div>`}).join('');
const attachBlockerDiagnostics=(orders,diagnostics)=>orders.map(row=>{if(row.status!=='rejected')return row;const orderTime=new Date(row.timestamp).valueOf();const matches=diagnostics.filter(diag=>{const diagnosticTime=new Date(diag.timestamp).valueOf(),gap=orderTime-diagnosticTime;return Number.isFinite(gap)&&gap>=0&&gap<=60000&&reasonCodes(row).includes(diag.reason)&&(!row.symbol||!diag.symbol||row.symbol===diag.symbol)&&(!row.action||!diag.action||row.action===diag.action)});return matches.length?{...row,blockerDetails:matches}:row});
const eventTone=row=>row.status==='rejected'||row.decision==='rejected'?'rej':['filled','placed','partial'].includes(row.status)||row.decision==='candidate_qualified'?'ok':'';
const eventRows=rows=>rows.length?[...rows].reverse().map(row=>`<div class="event ${eventTone(row)}"><time>${shortTime(row.timestamp)}</time>${row.symbol?`<span class="ticker">${esc(row.symbol)}</span>`:'<span class="no-ticker">—</span>'}<b class="desc">${esc(capFirst(humanize(reasonCodes(row)[0]||row.decision||row.status)))}</b><em>${esc(row.action||row.mode||row.stage||row.status||'logged')}</em><details class="event-reason"><summary>Why?</summary><p>${esc(row.summary||'A sanitized desk lifecycle event was recorded.')}</p></details>${row.blockerDetails?.length?`<details class="event-diagnostics"><summary>Blocker details</summary>${diagnosticDetails(row.blockerDetails)}</details>`:''}</div>`).join(''):'<div class="empty">Nothing logged for these filters. Patience is a valid decision.</div>';
const candidateRows=rows=>rows.length?[...rows].reverse().map(row=>`<div class="candidate-event"><time>${shortTime(row.timestamp)}</time><b>${esc(row.symbol||'—')}</b><span>${esc(row.summary)}</span></div>`).join(''):'<div class="empty">No qualified candidates logged yet.</div>';
const portfolioRows=rows=>rows.length?`<div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Qty</th><th>Avg entry</th><th>Current</th><th>Market value</th><th>Total gain</th><th>Today</th></tr></thead><tbody>${rows.map(row=>`<tr><td class="holding-symbol">${esc(row.symbol)}</td><td>${number(row.quantity)}</td><td>${money(row.average_entry_price)}</td><td>${money(row.current_price)}</td><td>${money(row.market_value)}</td><td class="${tone(row.unrealized_return_pct)}">${signedMoney(row.unrealized_pl_usd)} <span class="chg ${tone(row.unrealized_return_pct)}">${excess(row.unrealized_return_pct)}</span></td><td class="${tone(row.day_return_pct)}">${signedMoney(row.day_pl_usd)} <span class="chg ${tone(row.day_return_pct)}">${excess(row.day_return_pct)}</span></td></tr>`).join('')}</tbody></table></div>`:'<div class="empty">No open Alpaca paper positions.</div>';
const coverageBadge=status=>{const s=String(status||'unknown');const cls={complete:'ok',ok:'ok',verified:'ok',incomplete:'warn',unknown:'',error:'bad',failed:'bad'}[s]??'';return `<span class="badge ${cls}">${esc(s)}</span>`};
const share=(part,whole)=>whole?`${(100*Number(part||0)/Number(whole)).toFixed(0)}% of reviews`:'';
const funnelRows=steps=>{const max=Math.max(1,...steps.map(s=>Number(s.n||0)));return steps.map((s,i)=>`<div class="f-row"><div class="f-label"><span>0${i+1}</span><b>${s.label}</b><small>${s.caption}</small></div><div class="f-track" aria-hidden="true"><div class="f-bar ${s.cls||''}" style="width:${(100*Number(s.n||0)/max).toFixed(1)}%"></div></div><div class="f-val"><b>${number(s.n)}</b><small>${s.note||'&nbsp;'}</small></div></div>`).join('')};
fetch('dashboard.json').then(response=>{if(!response.ok)throw new Error('Dashboard data unavailable');return response.json()}).then(d=>{
 const p=d.performance,v=d.reviews,s=d.desk_status||{}, horizons=d.outcome_horizons||{},portfolio=d.live_portfolio||{},live=portfolio.summary||{},holdings=portfolio.holdings||[],wd=d.watchdog||{};
 const horizonRows=[1,3,5,10].map(h=>{const row=horizons[String(h)]||{},t=row.traded||{},k=row.skipped||{};return `<tr><td>${h} session${h===1?'':'s'}</td><td class="${tone(t.avg_excess_pct)}">${excess(t.avg_excess_pct)}</td><td>${number(t.count)}</td><td class="${tone(k.avg_excess_pct)}">${excess(k.avg_excess_pct)}</td><td>${number(k.count)}</td></tr>`}).join('');
 const outcomeSamples=[1,3,5,10].reduce((n,h)=>{const row=horizons[String(h)]||{};return n+Number(row.traded?.count||0)+Number(row.skipped?.count||0)},0);
 const outcomesBody=outcomeSamples?`<div class="panel outcomes"><table><thead><tr><th>Horizon</th><th>Traded excess</th><th>Sample</th><th>Skipped excess</th><th>Sample</th></tr></thead><tbody>${horizonRows}</tbody></table></div>`:`<div class="panel outcomes-empty"><span class="badge">n = 0</span><span><b>No matured outcome samples yet.</b> Traded and skipped candidates are scored against SPY once their 1, 3, 5, and 10-session windows close.</span></div>`;
 const funnel=funnelRows([{label:'Researched',caption:'qualified candidates',n:p.qualified_candidates},{label:'Dual reviewed',caption:'independent review pairs',n:v.total_dual_model_reviews},{label:'Agreed',caption:'matching executable plans',n:v.agreements,cls:'pos',note:share(v.agreements,v.total_dual_model_reviews)},{label:'Disagreed',caption:'safely blocked',n:v.disagreements,cls:'neg',note:share(v.disagreements,v.total_dual_model_reviews)},{label:'Filled',caption:'broker-confirmed trades',n:p.confirmed_trades}]);
 document.querySelector('#app').innerHTML=`
 <header class="topbar"><div class="brand"><span class="mark" aria-hidden="true"></span><div>Tradey Desk<small>Paper trading · public audit</small></div></div><div class="top-right"><span class="stamp">Snapshot ${portfolio.captured_at?shortTime(portfolio.captured_at):'unavailable'}</span><span class="pill"><i class="dot ${s.enabled?'':'off'}"></i>${s.enabled?'Running':'Paused'}<span class="pill-mode"> · ${esc(s.broker_mode||'paper')}</span></span><button class="icon-btn" type="button" data-theme-toggle aria-label="Toggle light and dark theme" title="Toggle theme"><svg class="i-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg><svg class="i-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg></button></div></header>
 <section class="kpis" aria-label="Top metrics">
  <div class="panel kpi balance" aria-label="Current balance"><div class="eyebrow">Current balance</div><strong>${balanceMoney(live.total_balance_usd)}</strong><small>Broker account equity · USD · not the managed exposure cap or buying power.</small><div class="kpi-split"><div>Cash<b>${balanceMoney(live.cash_usd)}</b></div><div>Positions value<b>${balanceMoney(live.positions_value_usd)}</b></div></div><div class="stampline">Snapshot <time datetime="${esc(portfolio.captured_at||'')}">${portfolio.captured_at?shortTime(portfolio.captured_at):'Unavailable'}</time></div></div>
  <div class="panel kpi"><div class="eyebrow">Live portfolio vs SPY</div><strong class="${tone(live.day_excess_pct)}">${excess(live.day_excess_pct)}</strong><small>Today's whole-account return minus SPY; cash drag included.</small></div>
  <div class="panel kpi"><div class="eyebrow">Portfolio today</div><strong class="${tone(live.day_return_pct)}">${excess(live.day_return_pct)}</strong><small>${signedMoney(live.day_pl_usd)} across the paper account.</small></div>
  <div class="panel kpi"><div class="eyebrow">SPY today</div><strong class="${tone(live.spy_day_return_pct)}">${excess(live.spy_day_return_pct)}</strong><small>IEX benchmark snapshot.</small></div>
  <div class="panel kpi"><div class="eyebrow">Open positions</div><strong>${number(holdings.length)}</strong><small>Broker-confirmed Alpaca holdings.</small></div>
 </section>
 <div class="layout"><div class="main-col">
 <section class="section"><div class="section-head"><div><div class="eyebrow">Broker-confirmed exposure</div><h2>Current Alpaca holdings</h2></div><p>Snapshot ${shortTime(portfolio.captured_at)} · paper account · IEX marks</p></div><div class="panel portfolio-panel">${portfolioRows(holdings)}<div class="portfolio-note">Total gain is measured from each position's average entry. “Today” is intraday unrealized P&amp;L. The headline benchmark compares the whole paper account—including cash—with SPY for the current session; it is not a since-inception comparison. Positions value is account-wide net market value (long plus signed short); not a sum of displayed holdings. ${live.balance_reconciliation_difference_usd==null?'Reconciliation unavailable.':`Equity less cash and positions: ${signedMoney(live.balance_reconciliation_difference_usd)}. Broker adjustments may differ; equity remains authoritative.`}</div></div></section>
 <section class="section"><div class="section-head"><div><div class="eyebrow">From signal to fill</div><h2>Decision funnel</h2></div><p>More rejection is expected; the desk is not paid for activity.</p></div><div class="panel funnel">${funnel}</div><details class="panel candidate-card"><summary><span>View researched candidates</span><em>${number((d.researched_candidates||[]).length)} sanitized records</em></summary><div class="candidate-list" id="candidate-events">${candidateRows(d.researched_candidates||[])}</div></details></section>
 <section class="section"><div class="section-head"><div><div class="eyebrow">Selection quality vs SPY</div><h2>Candidate outcomes</h2></div><p>Average excess return; traded and skipped names are kept separate.</p></div>${outcomesBody}</section>
 </div>
 <aside class="rail">
  <section class="panel card" aria-label="Desk status"><h2>Desk status <span class="badge ${s.enabled?'ok':'warn'}">${s.enabled?'Running':'Paused'} / ${esc((s.broker_mode||'paper').toUpperCase())}</span></h2><ul class="spec"><li><span>Managed exposure cap</span><b>${money(s.account_cap_usd)}</b></li><li><span>Maximum position</span><b>${money(s.max_position_usd)}</b></li><li><span>Daily order limit</span><b>${number(s.max_daily_orders)}</b></li>${s.min_reward_risk==null?'':`<li><span>Minimum reward / risk</span><b>${esc(s.min_reward_risk)} : 1</b></li>`}<li><span>Last public activity</span><b>${shortTime(d.last_activity_at)}</b></li></ul></section>
  <section class="panel card" aria-label="Position watchdog"><h2>Position watchdog <span class="badge">Monitoring only</span></h2>
   <div class="wd-row"><div class="wd-head"><span>Primary managed strategy · $10,000 initial capital</span><b>${money(wd.strategy?.marked_equity)}</b></div><div class="wd-meta">Return <b class="mono ${wd.strategy?.return==null?'':tone(Number(wd.strategy.return))}">${wd.strategy?.return==null?'—':excess(Number(wd.strategy.return)*100)}</b> · Accounting coverage ${coverageBadge(wd.strategy?.coverage?.status)}</div></div>
   <div class="wd-row"><div class="wd-head"><span>Secondary full account · includes legacy/manual holdings</span><b>${money(wd.account?.equity)}</b></div><div class="wd-meta">Cash <b class="mono">${money(wd.account?.cash)}</b> · account gains are not strategy alpha</div></div>
   <p class="fine">Evolving sleeve equity, not a fixed current denominator. Research and shadow outcomes are not actual protected-trade returns. ${wd.available?'Unknown evidence is withheld; protection alerts request human review, never repair.':'Monitoring data unavailable.'}</p></section>
 </aside></div>
 <section class="section"><div class="section-head"><div><div class="eyebrow">Sanitized public record</div><h2>Recent activity</h2></div><p>Private prompts, account details, and broker identifiers are never published.</p></div><div class="activity-controls"><label>Date range<select id="activity-range"><option value="today" selected>Today</option><option value="24h">Last 24 hours</option><option value="5d">Last 5 days</option><option value="week">Last week</option><option value="month">Last month</option><option value="year">Last year</option><option value="all">All</option><option value="custom">Custom dates</option></select></label><div class="custom-dates" id="custom-dates" hidden><label>From<input type="date" id="activity-from"></label><label>To<input type="date" id="activity-to"></label></div><div class="activity-range-note" id="activity-range-note" aria-live="polite"></div></div>
 <div class="panel activity"><div class="tabs" role="tablist"><button class="tab active" type="button" role="tab" id="tab-decisions" aria-controls="panel-decisions">Decision log <span class="count" id="count-decisions">0</span></button><button class="tab" type="button" role="tab" id="tab-orders" aria-controls="panel-orders">Review and order log <span class="count" id="count-orders">0</span></button></div>
 <div class="tab-panel" role="tabpanel" id="panel-decisions"><div class="activity-note">Every scheduled cycle, including no-trade decisions.</div><div class="activity-list" id="decision-events"></div></div>
 <div class="tab-panel" role="tabpanel" id="panel-orders" hidden><div class="activity-note">Every safe lifecycle event from the order ledger. Matching validation measurements expand inside rejected entries.</div><div class="order-filters"><label>Outcome<select id="order-status-filter"><option value="all">All outcomes</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select></label><label>Blocker reason<select id="order-reason-filter"><option value="all">All blocker reasons</option></select></label></div><div class="activity-list" id="order-events"></div></div></div></section>
 <section class="section"><div class="section-head"><div><div class="eyebrow">Method, not marketing</div><h2>How to read this desk</h2></div></div><div class="panel method"><p>The goal is benchmark-relative, risk-adjusted compounding—not the largest number of trades. Empty periods are normal when evidence, reviewer consensus, liquidity, or deterministic risk checks do not clear the bar.</p><div class="method-list"><div><b>Independent agreement</b><span>Two isolated models must approve the same immutable proposal hash. One unavailable, malformed, low-scoring, or dissenting review means no trade.</span></div><div><b>Deterministic validation</b><span>Entry, whole-share size, planned loss, horizon, spread, liquidity, reward-to-risk, cash, concentration, and eligibility are recalculated in code.</span></div><div><b>Broker truth</b><span>Only broker-readback-confirmed fills count as trades. Proposals and reviews are not performance.</span></div><div><b>Honest benchmark</b><span>Candidate outcomes are compared with SPY over matching 1, 3, 5, and 10-session windows.</span></div></div></div></section>
 <footer><span>Tradey Desk · paper mode only</span><span>Public data is allowlist-sanitized · returns are not guaranteed</span></footer>`;
 const range=document.querySelector('#activity-range'),from=document.querySelector('#activity-from'),to=document.querySelector('#activity-to'),customDates=document.querySelector('#custom-dates'),orderStatus=document.querySelector('#order-status-filter'),orderReason=document.querySelector('#order-reason-filter');
 const tabs={decisions:[document.querySelector('#tab-decisions'),document.querySelector('#panel-decisions')],orders:[document.querySelector('#tab-orders'),document.querySelector('#panel-orders')]};
 const selectTab=name=>Object.entries(tabs).forEach(([key,[tab,panel]])=>{const on=key===name;tab.className=on?'tab active':'tab';tab.ariaSelected=String(on);panel.hidden=!on});
 Object.entries(tabs).forEach(([key,[tab]])=>tab.addEventListener('click',()=>selectTab(key)));
 const populateOrderReasonFilter=()=>{const reasons=[...new Set((d.recent_orders||[]).flatMap(reasonCodes))].sort();orderReason.insertAdjacentHTML('beforeend',reasons.map(reason=>`<option value="${esc(reason)}">${esc(humanize(reason))}</option>`).join(''))};
 const renderActivity=()=>{const selected=range.value,fromValue=from.value,toValue=to.value;customDates.hidden=selected!=='custom';const decisions=(d.decision_audit||[]).filter(row=>activityMatchesRange(row,selected,new Date(),fromValue,toValue));const diagnostics=(d.blocker_diagnostics||[]).filter(row=>activityMatchesRange(row,selected,new Date(),fromValue,toValue));const orders=attachBlockerDiagnostics((d.recent_orders||[]).filter(row=>activityMatchesRange(row,selected,new Date(),fromValue,toValue)&&orderMatchesFilters(row,orderStatus.value,orderReason.value)),diagnostics);const detailCount=orders.reduce((count,row)=>count+(row.blockerDetails?.length||0),0);document.querySelector('#decision-events').innerHTML=eventRows(decisions);document.querySelector('#order-events').innerHTML=eventRows(orders);document.querySelector('#count-decisions').textContent=number(decisions.length);document.querySelector('#count-orders').textContent=number(orders.length);document.querySelector('#activity-range-note').textContent=`Showing ${number(decisions.length)} decision${decisions.length===1?'':'s'}, ${number(orders.length)} review/order event${orders.length===1?'':'s'}, and ${number(detailCount)} matched blocker detail${detailCount===1?'':'s'}.`};
 populateOrderReasonFilter();range.addEventListener('change',renderActivity);from.addEventListener('change',renderActivity);to.addEventListener('change',renderActivity);orderStatus.addEventListener('change',renderActivity);orderReason.addEventListener('change',renderActivity);renderActivity();
}).catch(error=>{document.querySelector('#app').innerHTML=`<header class="topbar"><div class="brand"><span class="mark" aria-hidden="true"></span><div>Tradey Desk<small>Autonomous paper desk</small></div></div></header><div class="panel card"><div class="eyebrow">Data unavailable</div><p>${esc(error.message)}. Try refreshing shortly.</p></div>`});
</script></body></html>'''

def main()->int:
    out=ROOT/"public"; out.mkdir(exist_ok=True)
    data=build_data(portfolio_snapshot=fetch_live_portfolio()); (out/"dashboard.json").write_text(json.dumps(data,indent=2,sort_keys=True),encoding="utf-8")
    (out/"index.html").write_text(html_template(),encoding="utf-8"); return 0
if __name__=="__main__":raise SystemExit(main())
