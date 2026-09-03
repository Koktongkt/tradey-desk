#!/usr/bin/env python3
"""Authenticated read-only normalized snapshot probe; emits safe metadata only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    planned_exit_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat().replace("+00:00", "Z")
    snapshot = None
    selected_symbol = None
    for symbol in ("AAPL", "NVDA", "MSFT"):
        completed = subprocess.run(
            ["uv", "run", "--with", "fastmcp", "python", "broker_mcp_bridge.py", "snapshot"],
            input=json.dumps({"symbol": symbol, "planned_exit_at": planned_exit_at}),
            text=True,
            capture_output=True,
            timeout=180,
        )
        if completed.returncode != 0:
            continue
        candidate = json.loads(completed.stdout)
        candidate_quote = candidate.get("quote") or {}
        snapshot, selected_symbol = candidate, symbol
        if candidate_quote.get("bid") is not None and candidate_quote.get("ask") is not None:
            break
    if snapshot is None:
        print("snapshot: failed")
        raise SystemExit(1)
    quote = snapshot.get("quote") or {}
    print("snapshot: ok")
    print(f"volume_feed: {snapshot.get('volume_feed')}")
    print(f"average_volume_present: {isinstance(snapshot.get('average_volume'), (int, float)) and snapshot.get('average_volume') > 0}")
    print(f"quote_feed: {snapshot.get('quote_feed')}")
    quote_two_sided = quote.get("bid") is not None and quote.get("ask") is not None
    print(f"quote_two_sided: {quote_two_sided}")
    print(f"quote_timestamp_present: {bool(quote.get('timestamp'))}")
    print(f"account_fields_present: {snapshot.get('cash') is not None and snapshot.get('buying_power') is not None}")
    print(f"positions_shape_valid: {isinstance(snapshot.get('positions'), list)}")
    print(f"orders_shape_valid: {isinstance(snapshot.get('open_orders'), list)}")
    print(f"trading_sessions_present: {bool(snapshot.get('trading_sessions'))}")
    print(f"technical_bars_feed: {snapshot.get('technical_bars_feed')}")
    print(f"technical_bars_sufficient: {isinstance(snapshot.get('technical_bars'), list) and len(snapshot.get('technical_bars')) >= 20}")

    import autotrader
    if not quote_two_sided:
        raise SystemExit(2)
    candidate = {
        "symbol": selected_symbol, "setup_type": "strategic_rerating",
        "planned_exit_at": planned_exit_at, "thesis": "read-only probe",
    }
    config = autotrader.load_json(autotrader.ROOT / "autonomy_config.json")
    proposal, errors = autotrader.build_canonical_proposal(candidate, snapshot, config, managed_exposure_usd=0)
    print(f"canonical_levels_derived: {proposal is not None and not errors}")
    print(f"level_method: {proposal.get('level_method') if proposal else 'none'}")


if __name__ == "__main__":
    main()
