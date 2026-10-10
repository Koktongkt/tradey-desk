"""Fresh, test-only config and trusted broker scaffolding."""
import json
from pathlib import Path


def policy_config():
    cfg_path = Path(__file__).resolve().parents[1] / "autonomy_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    # Legacy safety fixtures retain the pre-activation all-active-order gate.
    # Runtime activation is exercised separately using the untouched checked-in config.
    for key in ('pending_entry_policy','max_pending_entry_parents','entry_expiry_policy'):
        cfg.pop(key,None)
    cfg["min_price_usd"] = 10
    return cfg


def technical_bars():
    return [
        {"open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i,
         "volume": 1_000_000 + i, "timestamp": 1700000000 + i * 86400}
        for i in range(25)
    ]


def broker_snapshot(*, captured_at, quote, cash, earnings_status,
                    earnings_sessions_away, trading_sessions):
    return {
        "captured_at": captured_at,
        "buying_power": 10000.0,
        "cash": cash,
        "positions": [],
        "open_orders": [],
        "asset": {"symbol": "DELL", "tradable": True, "class": "us_equity",
                  "exchange": "NASDAQ", "name": "Dell Technologies Inc.",
                  "fractionable": True, "leveraged": False, "inverse": False},
        "quote": quote,
        "quote_feed": "alpaca_iex",
        "average_volume": 5_000_000.0,
        "volume_feed": "massive_consolidated",
        "technical_bars": technical_bars(),
        "technical_bars_feed": "massive_consolidated_completed_daily",
        "earnings_status": earnings_status,
        "earnings_sessions_away": earnings_sessions_away,
        "trading_sessions": trading_sessions,
    }
