#!/usr/bin/env python3
"""Minimal MCP client for Alpaca's official stdio server.

Only this process receives Alpaca credentials. It emits broker data/order
responses as JSON. It never calls a decision model.
"""
from __future__ import annotations
import asyncio,json,sys
from datetime import datetime,timezone
from typing import Any
from zoneinfo import ZoneInfo
from fastmcp import Client
from broker_credentials import configured_alpaca_env
from broker_normalization import average_volume, find_mapping_with_keys, latest_quote_request, symbol_mapping, tool_arguments
from market_data import consolidated_daily_bars

def text_result(result:Any)->Any:
    parts=[]
    for c in getattr(result,"content",[]):
        if hasattr(c,"text"): parts.append(c.text)
    raw="\n".join(parts)
    try:return json.loads(raw)
    except Exception:return {"text":raw}

def unwrap(x:Any)->Any:
    if isinstance(x,dict):
        for k in ("data","result","orders","positions","assets","bars","quotes"):
            if k in x and len(x)==1:return x[k]
    return x

class Alpaca:
    def __init__(self,s:Client,tools:dict[str,dict[str,Any]]):self.s=s;self.tools=tools
    async def call(self,name:str,values:dict[str,Any]|None=None)->Any:
        if name not in self.tools:raise RuntimeError(f"missing tool {name}")
        props=self.tools[name].get("properties",{}); vals=values or {}; args=tool_arguments(props,vals)
        return unwrap(text_result(await self.s.call_tool(name,args)))

def first_dict(x:Any)->dict[str,Any]:
    if isinstance(x,dict):return x
    if isinstance(x,list) and x and isinstance(x[0],dict):return x[0]
    return {}

def listish(x:Any)->list[Any]:
    if isinstance(x,list):return x
    if isinstance(x,dict):
        for k in ("data","orders","positions","bars"):
            if isinstance(x.get(k),list):return x[k]
            if isinstance(x.get(k),dict):
                vals=list(x[k].values());return vals[0] if vals and isinstance(vals[0],list) else vals
    return []

def symbol_dict(x:Any,symbol:str)->dict[str,Any]:
    if isinstance(x,dict):
        if symbol in x and isinstance(x[symbol],dict):return x[symbol]
        for v in x.values():
            found=symbol_dict(v,symbol)
            if found:return found
        if any(k in x for k in ("bid_price","ask_price","bp","ap","tradable","asset_class")):return x
    return {}

def symbol_bars(x:Any,symbol:str)->list[dict[str,Any]]:
    if isinstance(x,dict):
        if symbol in x and isinstance(x[symbol],list):return [b for b in x[symbol] if isinstance(b,dict)]
        for v in x.values():
            found=symbol_bars(v,symbol)
            if found:return found
    return []

def earnings_state(event_at:Any,calendar:Any,now:datetime|None=None)->tuple[str,int|None]:
    """Classify a sourced earnings timestamp and count broker-calendar sessions."""
    try:
        event=datetime.fromisoformat(str(event_at).replace("Z","+00:00"))
        if event.tzinfo is None:raise ValueError
        current=now or datetime.now(timezone.utc)
        if event<=current:return "reported",None
        ny=ZoneInfo("America/New_York")
        current_date=current.astimezone(ny).date()
        event_date=event.astimezone(ny).date()
        if event_date==current_date:return "upcoming",0
        rows=listish(calendar)
        session_dates=set()
        for row in rows:
            if not isinstance(row,dict):continue
            raw=row.get("date") or row.get("session")
            try:session_dates.add(datetime.fromisoformat(str(raw)[:10]).date())
            except Exception:continue
        if not session_dates:return "unknown",None
        return "upcoming",sum(current_date<d<=event_date for d in session_dates)
    except Exception:
        return "unknown",None

async def operation(a:Alpaca,op:str,p:dict[str,Any])->Any:
    if op in {"snapshot","review"}:
        symbol=str((p.get("order") or {}).get("symbol") or p.get("symbol") or "").upper()
        if not symbol:raise RuntimeError("symbol required")
        now=datetime.now(timezone.utc)
        account,positions,orders,asset,quote,technical_bars=await asyncio.gather(
            a.call("get_account_info"),
            a.call("get_all_positions"),
            a.call("get_orders",{"status":"open","limit":100}),
            a.call("get_asset",{"symbol":symbol}),
            a.call("get_stock_latest_quote",latest_quote_request(symbol)),
            asyncio.to_thread(consolidated_daily_bars,symbol),
        )
        calendar=[]
        event_at=p.get("earnings_event_at")
        planned_exit_at=p.get("planned_exit_at")
        calendar_end=None
        for raw in (event_at,planned_exit_at):
            try:
                parsed=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
                if parsed.tzinfo is not None and parsed.date()>=now.date():
                    calendar_end=max(calendar_end,parsed.date()) if calendar_end else parsed.date()
            except Exception:
                pass
        if calendar_end is not None:
            calendar=await a.call("get_calendar",{"start":now.date().isoformat(),"end":calendar_end.isoformat(),"date_type":"TRADING"})
        earnings_status,earnings_sessions_away=earnings_state(event_at,calendar,now)
        trading_sessions=[]
        for row in listish(calendar):
            value=row.get("date") or row.get("session") if isinstance(row,dict) else row
            if value:trading_sessions.append(str(value)[:10])
        ac=find_mapping_with_keys(account,{"buying_power","cash"})
        q=symbol_mapping(quote,symbol) or first_dict(quote)
        ar=symbol_mapping(asset,symbol) or first_dict(asset)
        return {
            "captured_at":now.isoformat().replace("+00:00","Z"),
            "buying_power":float(ac["buying_power"]) if ac.get("buying_power") not in (None,"") else None,
            "cash":float(ac["cash"]) if ac.get("cash") not in (None,"") else None,
            "positions":listish(positions),
            "open_orders":listish(orders),
            "asset":{"symbol":symbol,"tradable":ar.get("tradable"),"class":ar.get("class") or ar.get("asset_class"),"exchange":ar.get("exchange"),"name":ar.get("name"),"fractionable":ar.get("fractionable"),"leveraged":ar.get("leveraged",False),"inverse":ar.get("inverse",False)} if ar else None,
            "quote":{"bid":q.get("bid_price") or q.get("bp") or q.get("bid"),"ask":q.get("ask_price") or q.get("ap") or q.get("ask"),"timestamp":q.get("timestamp") or q.get("t")} if q else None,
            "quote_feed":"alpaca_iex",
            "average_volume":average_volume(technical_bars),
            "volume_feed":"massive_consolidated",
            "technical_bars":technical_bars,
            "technical_bars_feed":"massive_consolidated_completed_daily",
            "earnings_status":earnings_status,
            "earnings_sessions_away":earnings_sessions_away,
            "trading_sessions":trading_sessions,
        }
    if op=="place":
        o=p["order"]
        return await a.call("place_stock_order",{"symbol":o["symbol"],"side":"buy" if o["action"]=="BUY" else "sell","type":"limit","qty":o["quantity"],"time_in_force":"day","limit_price":o["limit_price"],"client_order_id":p["client_order_id"],"order_class":"bracket","take_profit_limit_price":o["target"],"stop_loss_stop_price":o["stop"]})
    if op=="reconcile":
        raw=await a.call("get_order_by_client_id",{"client_order_id":p["client_order_id"]})
        return find_mapping_with_keys(raw,{"status"}) or first_dict(raw)
    if op=="outcomes":
        out=[]; now=datetime.now(timezone.utc).isoformat()
        for c in p.get("candidates",[]):
            symbol=str(c.get("symbol","")).upper()
            if not symbol or not c.get("researched_at") or not c.get("spy_price"):continue
            raw=await a.call("get_stock_bars",{"symbol":f"{symbol},SPY","timeframe":"1Day","start":c["researched_at"],"end":now,"limit":100})
            sb=sorted(symbol_bars(raw,symbol),key=lambda b:str(b.get("t") or b.get("timestamp") or ""))
            pb=sorted(symbol_bars(raw,"SPY"),key=lambda b:str(b.get("t") or b.get("timestamp") or ""))
            prices={};spy_prices={}
            for h in (1,3,5,10,30):
                if len(sb)>=h and len(pb)>=h:
                    sc=sb[h-1].get("c") or sb[h-1].get("close");pc=pb[h-1].get("c") or pb[h-1].get("close")
                    if sc is not None and pc is not None:prices[str(h)]=float(sc);spy_prices[str(h)]=float(pc)
            if prices:out.append({"candidate_id":c.get("candidate_id"),"symbol":symbol,"researched_at":c["researched_at"],"entry_price":float(c["price"]),"spy_entry":float(c["spy_price"]),"prices":prices,"spy_prices":spy_prices,"traded":bool(c.get("traded"))})
        return out
    raise RuntimeError("unknown operation")

def alpaca_mcp_config()->dict[str,Any]:
    return {"mcpServers":{"alpaca":{"command":"uvx","args":["--with","fastmcp<4","alpaca-mcp-server"],"env":configured_alpaca_env()}}}

async def main()->int:
    op=sys.argv[1]; payload=json.loads(sys.stdin.read() or "{}")
    async with Client(alpaca_mcp_config()) as s:
        listing=await s.list_tools(); tools={t.name:t.inputSchema for t in listing}
        if op=="tools":
            print(json.dumps(tools,separators=(",",":"))); return 0
        a=Alpaca(s,tools); print(json.dumps(await operation(a,op,payload),separators=(",",":")))
    return 0
if __name__=="__main__":
    try:raise SystemExit(asyncio.run(main()))
    except Exception as e:
        print(json.dumps({"error":type(e).__name__}),file=sys.stderr);raise SystemExit(3)
