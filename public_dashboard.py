#!/usr/bin/env python3
"""Build the sanitized, public paper-trading dashboard."""
from __future__ import annotations
import json
import statistics
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parent
SAFE_LEDGER={"timestamp","status","reason","symbol","action","quantity","order_type","limit_price","evidence_id"}
SAFE_AUDIT={"timestamp","mode","stage","decision","reason","symbol","action"}
SAFE_STATUS={"enabled","broker_mode","account_cap_usd","max_position_usd","max_daily_orders","min_reward_risk"}
HORIZONS=(1,3,5,10)
SAFE_OUTCOME={"candidate_id","symbol","traded"}|{f"{prefix}_{h}s_pct" for prefix in ("return","spy_return","excess") for h in HORIZONS}
SAFE_DIAG_MEASURED={"bid","ask","midpoint","spread_bps","limit_price","reference_price","reference_side","deviation_bps","risk_reward","earnings_status","earnings_sessions_away","average_volume","quote_age_seconds","cash","buying_power","dollar_basis","planned_risk_usd","current_position_value","quote_feed","allowed_quote_feeds"}
SAFE_DIAG_THRESHOLD={"max_spread_bps","max_limit_deviation_bps","min_reward_risk","earnings_blackout_sessions","min_average_volume","max_quote_age_seconds","max_position_usd","max_planned_risk_per_trade_usd"}
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
    out=[]
    if not path.exists(): return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try: out.append(json.loads(line))
        except json.JSONDecodeError: pass
    return out

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

def build_data(root:Path=ROOT)->dict[str,Any]:
    ledger=rows(root/"order_ledger.jsonl"); raw_outcomes=rows(root/"candidate_outcomes.jsonl"); trades=rows(root/"trade_journal.jsonl"); candidates=rows(root/"candidates.jsonl"); audit=rows(root/"decision_audit.jsonl"); diagnostics=rows(root/"private"/"blocker_diagnostics.jsonl")
    latest={str(r.get("candidate_id") or i):r for i,r in enumerate(raw_outcomes)}; outcomes=list(latest.values())
    rejected=[r for r in ledger if r.get("status")=="rejected"]
    disagreements=[r for r in rejected if r.get("reason")=="model_disagreement" or "model_disagreement" in (r.get("reason") or [])]
    unavailable=[r for r in rejected if r.get("reason")=="reviewer_unavailable" or "reviewer_unavailable" in (r.get("reason") or [])]
    review_block_reasons={"model_disagreement","reviewer_unavailable","malformed_or_low_confidence","proposal_hash_mismatch","malformed_review","low_confidence","reviewer_veto","level_disagreement","order_detail_disagreement","consensus_hold"}
    review_rows=[r for r in rejected if (r.get("reason") in review_block_reasons if isinstance(r.get("reason"),str) else any(x in review_block_reasons for x in (r.get("reason") or [])))]
    agreements=sum(1 for r in ledger if r.get("status")=="proposed")
    vals=[float(r["excess_5s_pct"]) for r in outcomes if isinstance(r.get("excess_5s_pct"),(int,float))]
    traded=[r for r in outcomes if r.get("traded")]; skipped=[r for r in outcomes if not r.get("traded")]
    def summary(group:list[dict[str,Any]],horizon:int)->dict[str,Any]:
        key=f"excess_{horizon}s_pct"
        numbers=[float(r[key]) for r in group if isinstance(r.get(key),(int,float))]
        return {"count":len(numbers),"avg_excess_pct":round(statistics.mean(numbers),4) if numbers else None}
    config={}
    config_path=root/"autonomy_config.json"
    if config_path.exists():
        try: config=json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError,OSError): pass
    timestamps=[str(r["timestamp"]) for r in ledger+audit if r.get("timestamp")]
    return {
        "desk_status":{k:config[k] for k in SAFE_STATUS if k in config},
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
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tradey Desk — Paper trading monitor</title>
<style>
:root{--paper:#f4f1e8;--surface:#fffdf7;--ink:#16211d;--muted:#68726c;--line:#d8d7cd;--green:#177a55;--green-soft:#dcecdf;--amber:#a16412;--red:#a23a2b;--mono:"IBM Plex Mono","SFMono-Regular",Consolas,monospace;--sans:"Aptos","Segoe UI Variable","Helvetica Neue",sans-serif}
*{box-sizing:border-box}html{background:var(--paper);color:var(--ink);font-family:var(--sans)}body{margin:0}.shell{max-width:1180px;margin:auto;padding:24px 28px 64px}
header{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:8px 0 24px;border-bottom:1px solid var(--line)}.brand{font-weight:750;font-size:20px;letter-spacing:-.025em}.eyebrow{font:700 11px var(--mono);letter-spacing:.11em;text-transform:uppercase;color:var(--muted)}.status-line{display:flex;align-items:center;gap:9px;font-size:13px}.dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px var(--green-soft)}
.lede{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(280px,.55fr);gap:44px;padding:34px 0 28px}.lede h1{font-size:clamp(30px,4vw,42px);line-height:1;letter-spacing:-.05em;margin:7px 0 15px;max-width:750px}.lede p{font-size:16px;line-height:1.55;color:var(--muted);max-width:660px;margin:0}.status-panel{border-top:2px solid var(--ink);padding-top:14px}.status-row{display:flex;justify-content:space-between;gap:24px;padding:11px 0;border-bottom:1px solid var(--line);font-size:13px}.status-row b{font:700 13px var(--mono)}
.metric-strip{display:grid;grid-template-columns:repeat(4,1fr);border-block:1px solid var(--line);margin-bottom:48px}.metric{padding:20px 20px 20px 0}.metric+.metric{border-left:1px solid var(--line);padding-left:20px}.metric strong{display:block;font:700 clamp(27px,4vw,40px) var(--mono);letter-spacing:-.055em;margin:9px 0 6px}.metric small{color:var(--muted);line-height:1.4}
.section{margin-top:52px}.section-head{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:18px}.section h2{font-size:24px;letter-spacing:-.035em;margin:0}.section-head p{margin:0;color:var(--muted);font-size:13px}.panel{background:var(--surface);border:1px solid var(--line);border-radius:4px}
.funnel{display:grid;grid-template-columns:repeat(5,1fr)}.funnel-step{padding:22px;min-height:124px}.funnel-step+.funnel-step{border-left:1px solid var(--line)}.funnel-step span{font-size:12px;color:var(--muted)}.funnel-step b{display:block;font:700 28px var(--mono);margin:12px 0 4px}.funnel-step small{font-size:12px;color:var(--muted)}.candidate-card{margin-top:12px}.candidate-card>summary{display:flex;justify-content:space-between;align-items:center;cursor:pointer;padding:17px 22px;font-size:13px;font-weight:700;list-style-position:inside}.candidate-card>summary em{font:11px var(--mono);font-style:normal;color:var(--muted)}.candidate-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));max-height:360px;overflow-y:auto;border-top:1px solid var(--line);padding:8px 22px 18px}.candidate-event{display:grid;grid-template-columns:105px 60px minmax(0,1fr);gap:12px;padding:13px 10px 13px 0;border-bottom:1px solid var(--line);align-items:center}.candidate-event time{font:11px var(--mono);color:var(--muted)}.candidate-event b{font:700 11px var(--mono)}.candidate-event span{font-size:12px;color:var(--muted);line-height:1.4}
.outcomes{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:right;padding:15px 18px;border-bottom:1px solid var(--line)}th:first-child,td:first-child{text-align:left}th{font:700 11px var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}tbody tr:last-child td{border-bottom:0}.positive{color:var(--green)}.negative{color:var(--red)}
.activity-controls{display:flex;align-items:end;flex-wrap:wrap;gap:12px;margin:0 0 12px}.activity-controls label,.order-filters label{display:grid;gap:5px;font:700 10px var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}.activity-controls select,.activity-controls input,.order-filters select{min-height:38px;border:1px solid var(--line);border-radius:3px;background:var(--surface);color:var(--ink);font:12px var(--mono);padding:8px 10px}.custom-dates{display:flex;align-items:end;gap:12px}.custom-dates[hidden]{display:none}.activity-range-note{margin-left:auto;color:var(--muted);font-size:12px;padding-bottom:10px}.activity{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.activity-col{padding:22px;min-width:0}.activity-col+.activity-col{border-left:1px solid var(--line)}.activity h3{font-size:14px;margin:0 0 6px}.activity-note{color:var(--muted);font-size:12px;margin-bottom:10px}.order-filters{display:grid;grid-template-columns:minmax(110px,.7fr) minmax(160px,1.3fr);gap:8px;margin:12px 0}.activity-list{max-height:720px;overflow-y:auto;padding-right:5px}.event{display:grid;grid-template-columns:92px auto minmax(0,1fr) auto;gap:10px 12px;padding:13px 0;border-top:1px solid var(--line);align-items:center}.event time{font:11px var(--mono);color:var(--muted)}.event .ticker{font:700 11px var(--mono);letter-spacing:.06em;background:var(--surface);border:1px solid var(--line);border-radius:3px;padding:2px 7px;white-space:nowrap}.event b.desc{font-size:13px;line-height:1.4;text-transform:capitalize}.event em{font:700 10px var(--mono);font-style:normal;text-transform:uppercase;color:var(--muted)}.event-reason,.event-diagnostics{grid-column:1/-1;margin-left:104px}.event-reason summary,.event-diagnostics>summary{width:max-content;cursor:pointer;color:var(--green);font:700 11px var(--mono)}.event-reason p{margin:8px 0 2px;color:var(--muted);font-size:12px;line-height:1.5}.event-diagnostics{margin-top:2px}.diagnostic-detail{padding:9px 0 3px;border-top:1px dashed var(--line)}.diagnostic-detail>span{font:700 10px var(--mono);text-transform:uppercase;color:var(--muted)}.diag-grid{display:flex;flex-wrap:wrap;gap:4px 14px;padding-top:6px}.diag-pair{font:11px var(--mono);color:var(--muted)}.diag-pair em{font-style:normal;font-weight:700;color:var(--ink);margin-right:4px}.empty{padding:26px 0;color:var(--muted);font-size:13px}
.method{display:grid;grid-template-columns:.7fr 1.3fr;gap:50px;padding:30px}.method p{margin:0;color:var(--muted);line-height:1.55}.method-list{display:grid;grid-template-columns:1fr 1fr;gap:24px}.method-list b{display:block;font-size:13px;margin-bottom:6px}.method-list span{color:var(--muted);font-size:13px;line-height:1.45;display:block}
footer{display:flex;justify-content:space-between;gap:20px;border-top:1px solid var(--line);margin-top:56px;padding-top:18px;color:var(--muted);font-size:12px}
@media(max-width:800px){.shell{padding:18px 18px 44px}.lede{grid-template-columns:1fr;gap:30px;padding-top:32px}.metric-strip{grid-template-columns:1fr 1fr}.metric:nth-child(3){border-left:0;padding-left:0}.metric:nth-child(n+3){border-top:1px solid var(--line)}.funnel{grid-template-columns:1fr 1fr}.funnel-step{border-bottom:1px solid var(--line)}.funnel-step:nth-child(odd){border-left:0}.candidate-list,.activity,.method{grid-template-columns:1fr}.activity-col+.activity-col{border-left:0;border-top:1px solid var(--line)}.method-list{grid-template-columns:1fr}.section-head{align-items:start;flex-direction:column;gap:6px}.activity-range-note{width:100%;margin-left:0;padding:0}}
@media(max-width:480px){header{align-items:flex-start}.status-line{font-size:0}.metric-strip{grid-template-columns:1fr}.metric+.metric,.metric:nth-child(3){border-left:0;padding-left:0}.metric:nth-child(n+2){border-top:1px solid var(--line)}.funnel{grid-template-columns:1fr}.funnel-step+.funnel-step{border-left:0}.candidate-event{grid-template-columns:90px 50px minmax(0,1fr)}.custom-dates{width:100%;flex-wrap:wrap}.order-filters{grid-template-columns:1fr}.event{grid-template-columns:76px auto 1fr}.event em{grid-column:3}.event-reason,.event-diagnostics{margin-left:88px}.method{padding:22px}footer{flex-direction:column}}
</style></head>
<body><main class="shell" id="app" aria-label="Tradey Desk dashboard"><header><div class="brand">Tradey Desk</div><div class="status-line"><i class="dot"></i><span>Autonomous paper desk</span></div></header><div class="empty">Loading public desk data…</div></main>
<script>
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=value=>Number(value??0).toLocaleString('en-US');
const money=value=>value==null?'—':`$${Number(value).toLocaleString('en-US')}`;
const excess=value=>value==null?'—':`${value>0?'+':''}${Number(value).toFixed(2)}%`;
const tone=value=>value==null?'':value>=0?'positive':'negative';
const shortTime=value=>{if(!value)return 'No activity yet';const date=new Date(value);return Number.isNaN(date.valueOf())?esc(value):date.toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'})};
const activityMatchesRange=(row,range,now=new Date(),from='',to='')=>{const date=new Date(row.timestamp);if(range==='all')return true;if(Number.isNaN(date.valueOf()))return false;let start,end=now;if(range==='today'){start=new Date(now.getFullYear(),now.getMonth(),now.getDate());end=new Date(start);end.setDate(end.getDate()+1)}else if(range==='custom'){if(!from&&!to)return true;start=from?new Date(`${from}T00:00:00`):new Date(0);end=to?new Date(`${to}T00:00:00`):now;if(to)end.setDate(end.getDate()+1)}else{const days={"24h":1,"5d":5,"week":7,"month":30,"year":365}[range]||1;start=new Date(now.valueOf()-days*86400000)}return date>=start&&date<end};
const reasonCodes=row=>Array.isArray(row.reason)?row.reason:typeof row.reason==='string'?[row.reason]:[];
const humanize=value=>String(value||'Update').replaceAll('_',' ');
const orderMatchesFilters=(row,status,reason)=>{const approved=['proposed','placed','pending','partial','filled'].includes(row.status);const statusMatch=status==='all'||(status==='approved'&&approved)||(status==='rejected'&&row.status==='rejected');return statusMatch&&(reason==='all'||reasonCodes(row).includes(reason))};
const fmtVal=value=>value==null?'—':(typeof value==='number'?Number(value).toLocaleString('en-US',{maximumFractionDigits:2}):esc(String(value)));
const diagnosticDetails=rows=>rows.map(row=>{const pairs=[...Object.entries(row.measured||{}).map(([k,v])=>[humanize(k),v]),...Object.entries(row.threshold||{}).map(([k,v])=>['limit: '+humanize(k),v])];const detail=pairs.length?pairs.map(([k,v])=>`<span class="diag-pair"><em>${esc(k)}</em> ${fmtVal(v)}</span>`).join(''):'<span class="diag-pair"><em>context unavailable</em></span>';return `<div class="diagnostic-detail"><span>${esc(row.stage||'validation')}</span><div class="diag-grid">${detail}</div></div>`}).join('');
const attachBlockerDiagnostics=(orders,diagnostics)=>orders.map(row=>{if(row.status!=='rejected')return row;const orderTime=new Date(row.timestamp).valueOf();const matches=diagnostics.filter(diag=>{const diagnosticTime=new Date(diag.timestamp).valueOf(),gap=orderTime-diagnosticTime;return Number.isFinite(gap)&&gap>=0&&gap<=60000&&reasonCodes(row).includes(diag.reason)&&(!row.symbol||!diag.symbol||row.symbol===diag.symbol)&&(!row.action||!diag.action||row.action===diag.action)});return matches.length?{...row,blockerDetails:matches}:row});
const eventRows=rows=>rows.length?[...rows].reverse().map(row=>`<div class="event"><time>${shortTime(row.timestamp)}</time>${row.symbol?`<span class="ticker">${esc(row.symbol)}</span>`:''}<b class="desc">${esc(humanize(reasonCodes(row)[0]||row.decision||row.status))}</b><em>${esc(row.action||row.mode||row.stage||row.status||'logged')}</em><details class="event-reason"><summary>Why?</summary><p>${esc(row.summary||'A sanitized desk lifecycle event was recorded.')}</p></details>${row.blockerDetails?.length?`<details class="event-diagnostics"><summary>Blocker details</summary>${diagnosticDetails(row.blockerDetails)}</details>`:''}</div>`).join(''):'<div class="empty">Nothing logged for these filters. Patience is a valid decision.</div>';
const candidateRows=rows=>rows.length?[...rows].reverse().map(row=>`<div class="candidate-event"><time>${shortTime(row.timestamp)}</time><b>${esc(row.symbol||'—')}</b><span>${esc(row.summary)}</span></div>`).join(''):'<div class="empty">No qualified candidates logged yet.</div>';
fetch('dashboard.json').then(response=>{if(!response.ok)throw new Error('Dashboard data unavailable');return response.json()}).then(d=>{
 const p=d.performance,v=d.reviews,s=d.desk_status||{}, horizons=d.outcome_horizons||{};
 const horizonRows=[1,3,5,10].map(h=>{const row=horizons[String(h)]||{},t=row.traded||{},k=row.skipped||{};return `<tr><td>${h} session${h===1?'':'s'}</td><td class="${tone(t.avg_excess_pct)}">${excess(t.avg_excess_pct)}</td><td>${number(t.count)}</td><td class="${tone(k.avg_excess_pct)}">${excess(k.avg_excess_pct)}</td><td>${number(k.count)}</td></tr>`}).join('');
 document.querySelector('#app').innerHTML=`
 <header><div class="brand">Tradey Desk</div><div class="status-line"><i class="dot"></i><span>${s.enabled?'Autonomous':'Paused'} · ${esc(s.broker_mode||'paper')} mode</span></div></header>
 <section class="lede"><div><div class="eyebrow">Paper trading · public audit</div><h1>Paper desk overview</h1><p>What the desk considered, what independent reviewers agreed on, and whether those choices added value versus the S&amp;P 500.</p></div><aside class="status-panel" aria-label="Desk status"><div class="eyebrow">Desk status</div><div class="status-row"><span>Operating mode</span><b>${s.enabled?'RUNNING':'PAUSED'} / ${esc((s.broker_mode||'paper').toUpperCase())}</b></div><div class="status-row"><span>Managed exposure cap</span><b>${money(s.account_cap_usd)}</b></div><div class="status-row"><span>Maximum position</span><b>${money(s.max_position_usd)}</b></div><div class="status-row"><span>Daily order limit</span><b>${number(s.max_daily_orders)}</b></div><div class="status-row"><span>Last public activity</span><b>${shortTime(d.last_activity_at)}</b></div></aside></section>
 <section class="metric-strip" aria-label="Top metrics"><div class="metric"><div class="eyebrow">5-session excess</div><strong class="${tone(p.avg_excess_5s_pct)}">${excess(p.avg_excess_5s_pct)}</strong><small>Average candidate return minus SPY. Not portfolio return.</small></div><div class="metric"><div class="eyebrow">Qualified</div><strong>${number(p.qualified_candidates)}</strong><small>Candidates that passed initial research quality.</small></div><div class="metric"><div class="eyebrow">Confirmed trades</div><strong>${number(p.confirmed_trades)}</strong><small>Broker-confirmed fills only.</small></div><div class="metric"><div class="eyebrow">Review blocks</div><strong>${number(v.total_dual_model_reviews-v.agreements)}</strong><small>Ideas stopped by independent review.</small></div></section>
 <section class="section"><div class="section-head"><div><div class="eyebrow">From signal to fill</div><h2>Decision funnel</h2></div><p>More rejection is expected; the desk is not paid for activity.</p></div><div class="panel funnel"><div class="funnel-step"><span>01 · researched</span><b>${number(p.qualified_candidates)}</b><small>qualified candidates</small></div><div class="funnel-step"><span>02 · dual reviewed</span><b>${number(v.total_dual_model_reviews)}</b><small>independent review pairs</small></div><div class="funnel-step"><span>03 · agreed</span><b>${number(v.agreements)}</b><small>matching executable plans</small></div><div class="funnel-step"><span>04 · disagreed</span><b>${number(v.disagreements)}</b><small>safely blocked</small></div><div class="funnel-step"><span>05 · filled</span><b>${number(p.confirmed_trades)}</b><small>broker-confirmed trades</small></div></div><details class="panel candidate-card"><summary><span>View researched candidates</span><em>${number((d.researched_candidates||[]).length)} sanitized records</em></summary><div class="candidate-list" id="candidate-events">${candidateRows(d.researched_candidates||[])}</div></details></section>
 <section class="section"><div class="section-head"><div><div class="eyebrow">Selection quality vs SPY</div><h2>Candidate outcomes</h2></div><p>Average excess return; traded and skipped names are kept separate.</p></div><div class="panel outcomes"><table><thead><tr><th>Horizon</th><th>Traded excess</th><th>Sample</th><th>Skipped excess</th><th>Sample</th></tr></thead><tbody>${horizonRows}</tbody></table></div></section>
 <section class="section"><div class="section-head"><div><div class="eyebrow">Sanitized public record</div><h2>Recent activity</h2></div><p>Private prompts, account details, and broker identifiers are never published.</p></div><div class="activity-controls"><label>Date range<select id="activity-range"><option value="today" selected>Today</option><option value="24h">Last 24 hours</option><option value="5d">Last 5 days</option><option value="week">Last week</option><option value="month">Last month</option><option value="year">Last year</option><option value="all">All</option><option value="custom">Custom dates</option></select></label><div class="custom-dates" id="custom-dates" hidden><label>From<input type="date" id="activity-from"></label><label>To<input type="date" id="activity-to"></label></div><div class="activity-range-note" id="activity-range-note" aria-live="polite"></div></div><div class="panel activity"><div class="activity-col"><h3>Decision log</h3><div class="activity-note">Every scheduled cycle, including no-trade decisions.</div><div class="activity-list" id="decision-events"></div></div><div class="activity-col"><h3>Review and order log</h3><div class="activity-note">Every safe lifecycle event from the order ledger. Matching validation measurements expand inside rejected entries.</div><div class="order-filters"><label>Outcome<select id="order-status-filter"><option value="all">All outcomes</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select></label><label>Blocker reason<select id="order-reason-filter"><option value="all">All blocker reasons</option></select></label></div><div class="activity-list" id="order-events"></div></div></div></section>
 <section class="section"><div class="section-head"><div><div class="eyebrow">Method, not marketing</div><h2>How to read this desk</h2></div></div><div class="panel method"><p>The goal is benchmark-relative, risk-adjusted compounding—not the largest number of trades. Empty periods are normal when evidence, reviewer consensus, liquidity, or deterministic risk checks do not clear the bar.</p><div class="method-list"><div><b>Independent agreement</b><span>Two isolated models must approve the same immutable proposal hash. One unavailable, malformed, low-scoring, or dissenting review means no trade.</span></div><div><b>Deterministic validation</b><span>Entry, whole-share size, planned loss, horizon, spread, liquidity, reward-to-risk, cash, concentration, and eligibility are recalculated in code.</span></div><div><b>Broker truth</b><span>Only broker-readback-confirmed fills count as trades. Proposals and reviews are not performance.</span></div><div><b>Honest benchmark</b><span>Candidate outcomes are compared with SPY over matching 1, 3, 5, and 10-session windows.</span></div></div></div></section>
 <footer><span>Tradey Desk · paper mode only</span><span>Public data is allowlist-sanitized · returns are not guaranteed</span></footer>`;
 const range=document.querySelector('#activity-range'),from=document.querySelector('#activity-from'),to=document.querySelector('#activity-to'),customDates=document.querySelector('#custom-dates'),orderStatus=document.querySelector('#order-status-filter'),orderReason=document.querySelector('#order-reason-filter');
 const populateOrderReasonFilter=()=>{const reasons=[...new Set((d.recent_orders||[]).flatMap(reasonCodes))].sort();orderReason.insertAdjacentHTML('beforeend',reasons.map(reason=>`<option value="${esc(reason)}">${esc(humanize(reason))}</option>`).join(''))};
 const renderActivity=()=>{const selected=range.value,fromValue=from.value,toValue=to.value;customDates.hidden=selected!=='custom';const decisions=(d.decision_audit||[]).filter(row=>activityMatchesRange(row,selected,new Date(),fromValue,toValue));const diagnostics=(d.blocker_diagnostics||[]).filter(row=>activityMatchesRange(row,selected,new Date(),fromValue,toValue));const orders=attachBlockerDiagnostics((d.recent_orders||[]).filter(row=>activityMatchesRange(row,selected,new Date(),fromValue,toValue)&&orderMatchesFilters(row,orderStatus.value,orderReason.value)),diagnostics);const detailCount=orders.reduce((count,row)=>count+(row.blockerDetails?.length||0),0);document.querySelector('#decision-events').innerHTML=eventRows(decisions);document.querySelector('#order-events').innerHTML=eventRows(orders);document.querySelector('#activity-range-note').textContent=`Showing ${number(decisions.length)} decision${decisions.length===1?'':'s'}, ${number(orders.length)} review/order event${orders.length===1?'':'s'}, and ${number(detailCount)} matched blocker detail${detailCount===1?'':'s'}.`};
 populateOrderReasonFilter();range.addEventListener('change',renderActivity);from.addEventListener('change',renderActivity);to.addEventListener('change',renderActivity);orderStatus.addEventListener('change',renderActivity);orderReason.addEventListener('change',renderActivity);renderActivity();
}).catch(error=>{document.querySelector('#app').innerHTML=`<header><div class="brand">Tradey Desk</div></header><div class="empty">${esc(error.message)}. Try refreshing shortly.</div>`});
</script></body></html>'''

def main()->int:
    out=ROOT/"public"; out.mkdir(exist_ok=True)
    data=build_data(); (out/"dashboard.json").write_text(json.dumps(data,indent=2,sort_keys=True),encoding="utf-8")
    (out/"index.html").write_text(html_template(),encoding="utf-8"); return 0
if __name__=="__main__":raise SystemExit(main())
