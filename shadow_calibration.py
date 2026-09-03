#!/usr/bin/env python3
"""Isolated no-execution shadow decisions and calibration reports."""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

HORIZONS = (1, 3, 5, 10, 30)
ROOT = Path(__file__).resolve().parent


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except json.JSONDecodeError:
            continue
    return rows


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def record_decision(
    path: Path,
    candidate: dict[str, Any],
    proposal: dict[str, Any],
    aggregate: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    proposal_hash = str(proposal["proposal_hash"])
    candidate_id = str(candidate.get("candidate_id") or "unknown")
    confidences = aggregate.get("reviewer_confidences")
    confidences = [float(value) for value in confidences] if isinstance(confidences, list) else []
    conviction = min(confidences) if confidences else None
    row = {
        "shadow_id": f"{candidate_id}:{proposal_hash}",
        "candidate_id": candidate_id,
        "proposal_hash": proposal_hash,
        "decision_at": timestamp,
        "symbol": str(proposal["symbol"]),
        "entry_price": float(proposal["limit_price"]),
        "spy_entry": float(candidate["spy_price"]),
        "stop": float(proposal["stop"]),
        "target": float(proposal["target"]),
        "quantity": int(proposal["quantity"]),
        "assigned_rubric": str(proposal["assigned_rubric"]),
        "holding_sessions": int(proposal["holding_sessions"]),
        "level_method": str(proposal["level_method"]),
        "reviewer_confidences": confidences,
        "conviction": conviction,
        "review_result": str(aggregate.get("reason") or "unknown"),
        "would_trade": bool(aggregate.get("approved")),
    }
    _append(path, row)
    return row


def measure_outcomes(
    decisions: list[dict[str, Any]], broker_rows: list[dict[str, Any]], output_path: Path
) -> list[dict[str, Any]]:
    decisions_by_id = {str(row["shadow_id"]): row for row in decisions}
    measured = []
    for broker_row in broker_rows:
        shadow_id = str(broker_row.get("candidate_id") or "")
        decision = decisions_by_id.get(shadow_id)
        if decision is None:
            continue
        entry = float(decision["entry_price"])
        spy_entry = float(decision["spy_entry"])
        row = {
            "shadow_id": shadow_id,
            "candidate_id": decision.get("candidate_id"),
            "symbol": decision.get("symbol"),
            "decision_at": decision.get("decision_at"),
            "conviction": decision.get("conviction"),
            "assigned_rubric": decision.get("assigned_rubric"),
            "would_trade": decision.get("would_trade", False),
        }
        for horizon in HORIZONS:
            key = str(horizon)
            if key not in broker_row.get("prices", {}) or key not in broker_row.get("spy_prices", {}):
                continue
            stock_return = (float(broker_row["prices"][key]) / entry - 1) * 100
            spy_return = (float(broker_row["spy_prices"][key]) / spy_entry - 1) * 100
            row[f"return_{horizon}s_pct"] = round(stock_return, 6)
            row[f"spy_return_{horizon}s_pct"] = round(spy_return, 6)
            row[f"excess_{horizon}s_pct"] = round(stock_return - spy_return, 6)
        _append(output_path, row)
        measured.append(row)
    return measured


def calibration_report(
    decisions: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    thresholds: Iterable[float] = (0.40, 0.50, 0.55, 0.60, 0.70, 0.80),
) -> dict[str, Any]:
    latest_outcomes = {str(row.get("shadow_id")): row for row in outcomes if row.get("shadow_id")}
    joined = [
        (decision, latest_outcomes.get(str(decision.get("shadow_id"))))
        for decision in decisions
        if isinstance(decision.get("conviction"), (int, float))
    ]
    result: dict[str, Any] = {"thresholds": {}}
    for threshold in thresholds:
        threshold_rows = [outcome for decision, outcome in joined if float(decision["conviction"]) >= threshold and outcome]
        horizon_stats = {}
        for horizon in HORIZONS:
            key = f"excess_{horizon}s_pct"
            values = [float(row[key]) for row in threshold_rows if isinstance(row.get(key), (int, float))]
            horizon_stats[f"{horizon}s"] = {
                "sample": len(values),
                "avg_excess_pct": round(statistics.mean(values), 6) if values else None,
            }
        result["thresholds"][f"{threshold:.2f}"] = horizon_stats
    return result


def refresh(
    decisions_path: Path,
    outcomes_path: Path,
    report_path: Path,
    broker: Any,
) -> int:
    decisions = read_rows(decisions_path)
    candidates = [
        {
            "candidate_id": row["shadow_id"], "symbol": row["symbol"],
            "researched_at": row["decision_at"], "price": row["entry_price"],
            "spy_price": row["spy_entry"], "traded": bool(row.get("would_trade")),
        }
        for row in decisions
        if all(row.get(key) is not None for key in ("shadow_id", "symbol", "decision_at", "entry_price", "spy_entry"))
    ]
    if candidates:
        broker_rows = broker({"candidates": candidates})
        measure_outcomes(decisions, broker_rows, outcomes_path)
    report = calibration_report(decisions, read_rows(outcomes_path))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


def _broker_outcomes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["uv", "run", "--with", "fastmcp", "python", str(ROOT / "broker_mcp_bridge.py"), "outcomes"],
        input=json.dumps(payload), text=True, capture_output=True, timeout=180,
    )
    if completed.returncode != 0:
        raise RuntimeError("shadow_outcomes_unavailable")
    value = json.loads(completed.stdout)
    if not isinstance(value, list):
        raise RuntimeError("shadow_outcomes_invalid")
    return value


def main() -> int:
    shadow_root = ROOT / "test_artifacts" / "shadow"
    try:
        return refresh(
            shadow_root / "decisions.jsonl", shadow_root / "outcomes.jsonl",
            shadow_root / "calibration_report.json", _broker_outcomes,
        )
    except Exception:
        print("SYSTEM_FAILURE shadow_calibration")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
