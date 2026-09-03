#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_IDS = {"352a053efc6288e3", "cafe5e3ed11afa8d"}
TARGETS = (
    (ROOT / "order_ledger.jsonl", ROOT / "test_artifacts" / "archived_dry_run_order_rows_2026-09-01.jsonl", 4),
    (ROOT / "private" / "reviews.jsonl", ROOT / "test_artifacts" / "archived_dry_run_review_rows_2026-09-01.jsonl", 2),
)

result = {}
for source, archive, expected in TARGETS:
    lines = [line for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    removed = []
    kept = []
    for line in lines:
        row = json.loads(line)
        (removed if row.get("evidence_id") in EVIDENCE_IDS else kept).append(line)
    if len(removed) != expected:
        raise RuntimeError(f"Expected {expected} contaminated rows in {source}, found {len(removed)}")
    archive.write_text("\n".join(removed) + "\n", encoding="utf-8")
    source.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
    result[str(source.relative_to(ROOT))] = {"removed": len(removed), "remaining": len(kept)}

print(json.dumps(result, sort_keys=True))
