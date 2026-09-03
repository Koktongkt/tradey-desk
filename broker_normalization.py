"""Pure normalization helpers for nested Alpaca MCP responses."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any
from zoneinfo import ZoneInfo


def tool_arguments(properties: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "symbol": ["symbol", "symbol_or_asset_id", "symbols", "symbol_or_symbols"],
        "type": ["type", "order_type"],
    }
    numeric_strings = {"qty", "limit_price", "take_profit_limit_price", "stop_loss_stop_price"}
    arguments: dict[str, Any] = {}
    for logical, value in values.items():
        supported = False
        for parameter in aliases.get(logical, [logical]):
            if parameter in properties:
                arguments[parameter] = str(value) if logical in numeric_strings else value
                supported = True
                break
        if not supported:
            raise RuntimeError(f"unsupported_tool_parameter:{logical}")
    return arguments


def find_mapping_with_keys(value: Any, keys: set[str]) -> dict[str, Any]:
    if isinstance(value, dict):
        if keys.issubset(value):
            return value
        for nested in value.values():
            found = find_mapping_with_keys(nested, keys)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = find_mapping_with_keys(nested, keys)
            if found:
                return found
    return {}


def symbol_mapping(value: Any, symbol: str) -> dict[str, Any]:
    target = symbol.upper()
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).upper() == target and isinstance(nested, dict):
                return nested
        if any(key in value for key in ("bid_price", "ask_price", "bp", "ap", "tradable", "asset_class")):
            return value
        for nested in value.values():
            found = symbol_mapping(nested, target)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = symbol_mapping(nested, target)
            if found:
                return found
    return {}


def symbol_bars(value: Any, symbol: str) -> list[dict[str, Any]]:
    target = symbol.upper()
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).upper() == target and isinstance(nested, list):
                return [bar for bar in nested if isinstance(bar, dict)]
        for nested in value.values():
            found = symbol_bars(nested, target)
            if found:
                return found
    return []


def daily_bars_request(symbol: str, start: str, end: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "timeframe": "1Day",
        "start": start,
        "end": end,
        "limit": 40,
        "feed": "iex",
    }


def latest_quote_request(symbol: str) -> dict[str, Any]:
    """Request the account-compatible execution reference explicitly."""
    return {"symbol": symbol, "feed": "iex"}


def massive_daily_bars(value: Any) -> list[dict[str, Any]]:
    """Extract Massive's consolidated daily aggregate rows."""
    if not isinstance(value, dict) or value.get("status") not in {"OK", "DELAYED"}:
        return []
    results = value.get("results")
    return [bar for bar in results if isinstance(bar, dict)] if isinstance(results, list) else []


def completed_session_average_volume(bars: list[dict[str, Any]], now_ms: int | None = None) -> float | None:
    """Average only completed sessions, excluding today's partial daily bar."""
    current_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    market_tz = ZoneInfo("America/New_York")
    market_now = datetime.fromtimestamp(current_ms / 1000, timezone.utc).astimezone(market_tz)
    current_session_complete = market_now.weekday() < 5 and (market_now.hour, market_now.minute) >= (16, 15)
    completed = []
    for bar in bars:
        timestamp = bar.get("t")
        if not isinstance(timestamp, (int, float)):
            continue
        bar_date = datetime.fromtimestamp(timestamp / 1000, timezone.utc).astimezone(market_tz).date()
        if bar_date < market_now.date() or (bar_date == market_now.date() and current_session_complete):
            completed.append(bar)
    return average_volume(completed)


def average_volume(bars: list[dict[str, Any]]) -> float | None:
    volumes = []
    for bar in bars:
        volume = bar.get("v") if bar.get("v") is not None else bar.get("volume")
        if volume is None:
            continue
        try:
            normalized = float(volume)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(normalized) or normalized < 0:
            return None
        volumes.append(normalized)
    return sum(volumes) / len(volumes) if volumes else None
