"""Public-history continuity overlay for public_dashboard.build_data.

The live Vercel production payload contains newer decision/order events
than the migrated local operational journals. build_data must be able to
merge a sanitized public-history overlay (JSONL files derived from the
public production artifacts) into the dashboard data, gated by an explicit
config flag, with deduplication and no private-field leakage.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import public_dashboard


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _seed_root(root: Path, *, audit_rows: list[dict], ledger_rows: list[dict],
               candidate_rows: list[dict] | None = None) -> None:
    _write(root / "decision_audit.jsonl", audit_rows)
    _write(root / "order_ledger.jsonl", ledger_rows)
    if candidate_rows is not None:
        _write(root / "candidates.jsonl", candidate_rows)


CANONICAL_AUDIT = [{"timestamp": "2026-10-15T19:00:00Z", "mode": "autotrader",
                    "stage": "execution", "decision": "skipped", "reason": "already_reviewed"}]
CANONICAL_LEDGER = [{"timestamp": "2026-10-15T19:00:00Z", "status": "filled",
                     "symbol": "SNOW", "action": "BUY"}]
CANONICAL_CANDIDATE = [{"researched_at": "2026-10-15T18:00:00Z", "symbol": "SNOW"}]

# Public-derived overlay rows (same shape as the live-only production events).
OVERLAY_AUDIT = [
    {"timestamp": "2026-10-16T15:26:45.700175Z", "mode": "radar", "stage": "research",
     "decision": "candidate_qualified", "symbol": "IONQ"},
    {"timestamp": "2026-10-16T15:32:24.338065Z", "mode": "dashboard",
     "stage": "deployment", "decision": "completed"},
    {"timestamp": "2026-10-16T15:32:25.691773Z", "mode": "autotrader",
     "stage": "execution", "decision": "blocked", "reason": "consensus_hold"},
    {"timestamp": "2026-10-16T15:43:39.492846Z", "mode": "radar", "stage": "research",
     "decision": "system_failure", "reason": "research_source_retrieval_failed"},
    {"timestamp": "2026-10-16T15:50:25.432871Z", "mode": "autotrader",
     "stage": "execution", "decision": "skipped", "reason": "already_reviewed"},
]
OVERLAY_LEDGER = [
    {"timestamp": "2026-10-16T15:30:09.693428Z", "status": "new", "action": "BUY",
     "symbol": "UBER"},
    {"timestamp": "2026-10-16T15:32:25.651880Z", "status": "rejected", "action": "BUY",
     "symbol": "IONQ", "reason": "consensus_hold", "evidence_id": "954e28bbcb365641"},
    {"timestamp": "2026-10-16T15:50:08.952562Z", "status": "new", "action": "BUY",
     "symbol": "UBER"},
]
OVERLAY_CANDIDATE = [{"researched_at": "2026-10-16T15:26:34.223817Z", "symbol": "IONQ"}]


def _write_overlay(root: Path, *, audit=None, ledger=None, candidates=None) -> None:
    if audit is not None:
        _write(root / "public" / "overlay" / "decision_audit.jsonl", audit)
    if ledger is not None:
        _write(root / "public" / "overlay" / "order_ledger.jsonl", ledger)
    if candidates is not None:
        _write(root / "public" / "overlay" / "candidates.jsonl", candidates)


def _enable_flag(root: Path) -> None:
    (root / "autonomy_config.json").write_text(
        json.dumps({"public_history_overlay": True}), encoding="utf-8")


class PublicHistoryOverlayTests(unittest.TestCase):
    def test_overlay_events_reach_dashboard_when_enabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _seed_root(root, audit_rows=CANONICAL_AUDIT, ledger_rows=CANONICAL_LEDGER,
                       candidate_rows=CANONICAL_CANDIDATE)
            _write_overlay(root, audit=OVERLAY_AUDIT, ledger=OVERLAY_LEDGER,
                           candidates=OVERLAY_CANDIDATE)
            _enable_flag(root)
            data = public_dashboard.build_data(root)
        self.assertEqual(len(data["decision_audit"]), 6)
        self.assertEqual(len(data["recent_orders"]), 4)
        self.assertEqual(data["last_activity_at"], "2026-10-16T15:50:25.432871Z")
        # IONQ rejection lands in blocked_disagreements and review counts.
        self.assertTrue(any(r["symbol"] == "IONQ" and r["status"] == "rejected"
                            for r in data["blocked_disagreements"]))
        self.assertEqual(data["reviews"]["total_dual_model_reviews"], 1)
        self.assertEqual(data["performance"]["qualified_candidates"], 2)
        self.assertTrue(any(r["symbol"] == "IONQ" for r in data["researched_candidates"]))

    def test_overlay_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _seed_root(root, audit_rows=CANONICAL_AUDIT, ledger_rows=CANONICAL_LEDGER,
                       candidate_rows=CANONICAL_CANDIDATE)
            _write_overlay(root, audit=OVERLAY_AUDIT, ledger=OVERLAY_LEDGER,
                           candidates=OVERLAY_CANDIDATE)
            data = public_dashboard.build_data(root)
        self.assertEqual(len(data["decision_audit"]), 1)
        self.assertEqual(len(data["recent_orders"]), 1)
        self.assertEqual(len(data["researched_candidates"]), 1)

    def test_overlay_dedupes_events_already_in_journals(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Journals have caught up and already contain the overlay events.
            _seed_root(root, audit_rows=CANONICAL_AUDIT + OVERLAY_AUDIT,
                       ledger_rows=CANONICAL_LEDGER + OVERLAY_LEDGER,
                       candidate_rows=CANONICAL_CANDIDATE + OVERLAY_CANDIDATE)
            _write_overlay(root, audit=OVERLAY_AUDIT, ledger=OVERLAY_LEDGER,
                           candidates=OVERLAY_CANDIDATE)
            _enable_flag(root)
            data = public_dashboard.build_data(root)
        self.assertEqual(len(data["decision_audit"]), 6)
        self.assertEqual(len(data["recent_orders"]), 4)
        keys = [(r["timestamp"], r.get("decision")) for r in data["decision_audit"]]
        self.assertEqual(len(keys), len(set(keys)))
        order_keys = [(r["timestamp"], r.get("status"), r.get("symbol"))
                      for r in data["recent_orders"]]
        self.assertEqual(len(order_keys), len(set(order_keys)))

    def test_overlay_drops_private_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _seed_root(root, audit_rows=CANONICAL_AUDIT, ledger_rows=CANONICAL_LEDGER)
            _write_overlay(root, ledger=[dict(OVERLAY_LEDGER[1],
                                              secret_field="should-not-publish",
                                              account_number="123456")])
            _enable_flag(root)
            data = public_dashboard.build_data(root)
        row = next(r for r in data["recent_orders"] if r["symbol"] == "IONQ")
        for forbidden in ("secret_field", "account_number"):
            self.assertNotIn(forbidden, row)

    def test_overlay_tolerates_missing_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _seed_root(root, audit_rows=CANONICAL_AUDIT, ledger_rows=CANONICAL_LEDGER)
            _enable_flag(root)
            data = public_dashboard.build_data(root)
        self.assertEqual(len(data["decision_audit"]), 1)
        self.assertEqual(len(data["recent_orders"]), 1)


if __name__ == "__main__":
    unittest.main()
