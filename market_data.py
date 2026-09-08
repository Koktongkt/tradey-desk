"""Deterministic consolidated market-data reads for risk validation."""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import subprocess
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from broker_normalization import average_volume, massive_daily_bars


def configured_massive_key() -> str:
    completed = subprocess.run(
        [
            "/opt/hermes/bin/hermes",
            "config",
            "get",
            "--json",
            "mcp_servers.massive.env",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError("massive_mcp_config_unavailable")
    value = json.loads(completed.stdout)
    key = value.get("MASSIVE_API_KEY") if isinstance(value, dict) else None
    if not key:
        raise RuntimeError("massive_credentials_unavailable")
    return str(key)


def synchronized_completed_close_prices(symbol: str, now_ms: int | None = None) -> dict[str, float | str]:
    """Return stock and SPY closes from one consolidated completed-session response."""
    normalized = symbol.upper()
    if not re.fullmatch(r"[A-Z]{1,6}", normalized) or normalized == "SPY":
        raise ValueError("invalid_symbol")
    now = (
        dt.datetime.fromtimestamp(now_ms / 1000, dt.timezone.utc)
        if now_ms is not None
        else dt.datetime.now(dt.timezone.utc)
    )
    market_now = now.astimezone(ZoneInfo("America/New_York"))
    session_date = market_now.date()
    if (market_now.hour, market_now.minute) < (16, 15):
        session_date -= dt.timedelta(days=1)

    for _ in range(10):
        if session_date.weekday() >= 5:
            session_date -= dt.timedelta(days=1)
            continue
        query = urllib.parse.urlencode({"adjusted": "true"})
        url = f"https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/{session_date.isoformat()}?{query}"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {configured_massive_key()}", "User-Agent": "TradeyDesk/1.0"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
        rows = {
            row.get("T"): row
            for row in payload.get("results", [])
            if isinstance(row, dict) and row.get("T") in {normalized, "SPY"}
        }
        if set(rows) == {normalized, "SPY"} and payload.get("status") in {"OK", "DELAYED"}:
            stock_close, spy_close = rows[normalized].get("c"), rows["SPY"].get("c")
            stock_time, spy_time = rows[normalized].get("t"), rows["SPY"].get("t")
            if (
                isinstance(stock_close, (int, float)) and not isinstance(stock_close, bool)
                and math.isfinite(stock_close) and stock_close > 0
                and isinstance(spy_close, (int, float)) and not isinstance(spy_close, bool)
                and math.isfinite(spy_close) and spy_close > 0
                and isinstance(stock_time, (int, float)) and not isinstance(stock_time, bool)
                and math.isfinite(stock_time) and stock_time >= 0 and stock_time == spy_time
            ):
                captured_at = dt.datetime.fromtimestamp(stock_time / 1000, dt.timezone.utc)
                if captured_at.astimezone(ZoneInfo("America/New_York")).date() != session_date:
                    session_date -= dt.timedelta(days=1)
                    continue
                return {
                    "price": float(stock_close),
                    "spy_price": float(spy_close),
                    "market_prices_at": captured_at.isoformat().replace("+00:00", "Z"),
                    "market_price_feed": "massive_consolidated_completed_daily",
                }
        session_date -= dt.timedelta(days=1)
    raise RuntimeError("massive_synchronized_prices_unavailable")


def consolidated_daily_bars(symbol: str, now_ms: int | None = None) -> list[dict[str, float | int]]:
    normalized = symbol.upper()
    if not re.fullmatch(r"[A-Z]{1,6}", normalized):
        raise ValueError("invalid_symbol")
    now = (
        dt.datetime.fromtimestamp(now_ms / 1000, dt.timezone.utc)
        if now_ms is not None
        else dt.datetime.now(dt.timezone.utc)
    )
    start = (now.date() - dt.timedelta(days=60)).isoformat()
    end = now.date().isoformat()
    query = urllib.parse.urlencode({"adjusted": "true", "sort": "desc", "limit": 40})
    url = f"https://api.massive.com/v2/aggs/ticker/{normalized}/range/1/day/{start}/{end}?{query}"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {configured_massive_key()}", "User-Agent": "TradeyDesk/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())
    market_now = now.astimezone(ZoneInfo("America/New_York"))
    current_complete = market_now.weekday() < 5 and (market_now.hour, market_now.minute) >= (16, 15)
    completed = []
    for bar in massive_daily_bars(payload):
        values = [bar.get(key) for key in ("o", "h", "l", "c", "v", "t")]
        if not all(not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            continue
        timestamp = int(bar["t"])
        bar_date = dt.datetime.fromtimestamp(timestamp / 1000, dt.timezone.utc).astimezone(ZoneInfo("America/New_York")).date()
        if bar_date > market_now.date() or (bar_date == market_now.date() and not current_complete):
            continue
        completed.append({
            "open": float(bar["o"]), "high": float(bar["h"]), "low": float(bar["l"]),
            "close": float(bar["c"]), "volume": float(bar["v"]), "timestamp": timestamp,
        })
    return sorted(completed, key=lambda bar: bar["timestamp"])


def consolidated_average_volume(symbol: str, now_ms: int | None = None) -> float | None:
    return average_volume(consolidated_daily_bars(symbol, now_ms=now_ms))
