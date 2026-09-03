"""Load Alpaca credentials from Hermes MCP configuration."""
from __future__ import annotations

import json
import subprocess
from typing import Any


def configured_alpaca_env() -> dict[str, str]:
    completed = subprocess.run(
        [
            "/opt/hermes/bin/hermes",
            "config",
            "get",
            "--json",
            "mcp_servers.alpaca.env",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError("alpaca_mcp_config_unavailable")
    value: Any = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("alpaca_mcp_config_invalid")
    api_key = value.get("ALPACA_API_KEY")
    secret_key = value.get("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise RuntimeError("alpaca_credentials_unavailable")
    if str(value.get("ALPACA_PAPER_TRADE", "")).lower() != "true":
        raise RuntimeError("non_paper_alpaca_config_forbidden")
    return {
        "ALPACA_API_KEY": str(api_key),
        "ALPACA_SECRET_KEY": str(secret_key),
        "ALPACA_PAPER_TRADE": "true",
        "ALPACA_TOOLSETS": "account,trading,assets,stock-data,news",
    }
