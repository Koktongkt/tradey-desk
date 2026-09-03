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
