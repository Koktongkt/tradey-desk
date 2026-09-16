import contextlib
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import managed_reconciliation as mr
import broker_mcp_bridge


class ReconciliationSnapshotBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_is_read_only_and_requires_known_refs(self):
        class FakeAlpaca:
            def __init__(self):
                self.calls = []

            async def call(self, name, arguments=None):
                self.calls.append((name, arguments))
                if name == "get_order_by_client_id":
                    return {"client_order_id": arguments["client_order_id"], "status": "filled"}
                return [{"symbol": "ZS", "qty": "3"}] if name == "get_all_positions" else []

        alpaca = FakeAlpaca()
        snapshot = await broker_mcp_bridge.operation(
            alpaca, "reconciliation_snapshot", {"client_order_ids": ["tradey-x"]}
        )
        self.assertEqual(
            [name for name, _ in alpaca.calls],
            ["get_all_positions", "get_orders", "get_order_by_client_id"],
        )
        self.assertEqual(alpaca.calls[1][1], {"status": "open", "nested": True, "limit": 500})
        self.assertEqual(snapshot["orders"][0]["client_order_id"], "tradey-x")
        self.assertEqual(snapshot["positions"][0]["symbol"], "ZS")
        self.assertTrue(snapshot["captured_at"])

    async def test_snapshot_rejects_missing_or_invalid_refs(self):
        class FakeAlpaca:
            async def call(self, name, arguments=None):
                raise AssertionError("broker must not be called")

        for payload in ({}, {"client_order_ids": "x"}, {"client_order_ids": [1]}, {"client_order_ids": ["a" * 129]}):
            with self.assertRaises(RuntimeError):
                await broker_mcp_bridge.operation(FakeAlpaca(), "reconciliation_snapshot", payload)


class RegisterProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = Path(self.tmp.name) / "private" / "protection_orders.jsonl"
        self.row = {
            "parent_client_order_id": "tradey-f15cc1362440d53fe827627e",
            "protection_client_order_id": "tradey-protect-zs-20260908",
            "symbol": "ZS", "quantity": 3, "stop": 151.24, "target": 184.37,
            "registered_at": "2026-09-08T14:00:00Z",
        }
        self.order = {
            "client_order_id": self.row["protection_client_order_id"], "symbol": "ZS",
            "side": "sell", "position_intent": "sell_to_close", "order_class": "oco",
            "time_in_force": "gtc", "qty": "3",
        }

    def broker(self, orders=None, fail=False):
        def bridge(operation, payload):
            if fail:
                raise RuntimeError("broker_mcp_failure")
            refs = payload["client_order_ids"]
            return {"orders": [dict(self.order) for _ in refs] if orders is None else orders}
        return bridge

    def test_validated_registration_is_idempotent(self):
        mr.register_protection(self.registry, self.row, self.broker())
        mr.register_protection(self.registry, self.row, self.broker())
        self.assertEqual(mr.read_rows(self.registry), [self.row])

    def test_registration_requires_verified_broker_order(self):
        for orders in ([], [dict(self.order, client_order_id="other")], [dict(self.order, qty="4")],
                       [dict(self.order, order_class="simple")], [dict(self.order, side="buy")],
                       [dict(self.order, time_in_force="day")]):
            with self.subTest(orders=orders):
                with self.assertRaises(mr.ReconciliationBlocked):
                    mr.register_protection(self.registry, self.row, self.broker(orders=orders))
            self.assertFalse(self.registry.exists())
        with self.assertRaises(mr.ReconciliationBlocked):
            mr.register_protection(self.registry, self.row, self.broker(fail=True))
        self.assertFalse(self.registry.exists())

    def test_registration_rejects_conflicting_or_malformed_rows(self):
        mr.register_protection(self.registry, self.row, self.broker())
        for change in ({"quantity": 4}, {"symbol": "OTHER"}, {"stop": 999}):
            with self.subTest(change=change):
                with self.assertRaises(mr.ReconciliationBlocked):
                    mr.register_protection(self.registry, dict(self.row, **change), self.broker())
        second = dict(self.row, protection_client_order_id="other-ref")
        with self.assertRaises(mr.ReconciliationBlocked):
            mr.register_protection(self.registry, second, self.broker(
                orders=[dict(self.order, client_order_id="other-ref")]))
        for field in ("stop", "registered_at", "parent_client_order_id"):
            with self.subTest(field=field):
                broken = dict(self.row)
                del broken[field]
                with self.assertRaises(mr.ReconciliationBlocked):
                    mr.register_protection(Path(self.tmp.name) / "r2.jsonl", broken, self.broker())
        self.assertEqual(mr.read_rows(self.registry), [self.row])


class MarketWindowTests(unittest.TestCase):
    def test_market_window_boundaries_in_new_york_time(self):
        cases = [
            ("2026-09-14T13:34:00Z", False), ("2026-09-14T13:35:00Z", True),
            ("2026-09-14T20:15:00Z", True), ("2026-09-14T20:16:00Z", False),
            ("2026-09-12T15:00:00Z", False), ("2026-01-12T14:35:00Z", True),
        ]
        for stamp, expected in cases:
            with self.subTest(stamp=stamp):
                now = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                self.assertEqual(mr.market_window_open(now), expected)


class MaintenanceCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "private").mkdir(parents=True)
        (self.root / "private" / "broker_baseline.json").write_text(json.dumps({"preexisting_symbols": ["AAPL"]}))
        self.healthy = lambda operation, payload: {
            "positions": [], "open_orders": [], "orders": [], "captured_at": "2026-09-16T14:00:00Z"}

    def run_cli(self, argv, broker):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = mr.cli(argv, broker)
        return code, buffer.getvalue()

    def test_silent_healthy_default(self):
        code, out = self.run_cli(["--root", str(self.root)], self.healthy)
        self.assertEqual((code, out), (0, ""))

    def test_heartbeat_outputs_verified_summary(self):
        code, out = self.run_cli(["--root", str(self.root), "--heartbeat"], self.healthy)
        summary = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(summary["status"], "healthy")
        self.assertEqual(summary["verified"], True)
        self.assertIn("captured_at", summary)

    def test_blocker_output_and_exit_code_without_secrets(self):
        (self.root / "private" / "broker_baseline.json").write_text("{broken")
        code, out = self.run_cli(["--root", str(self.root)], self.healthy)
        self.assertEqual(code, 2)
        self.assertTrue(out.startswith("BLOCKER "))
        self.assertNotIn("broken", out.split("BLOCKER")[1])

    def test_system_failure_output_and_exit_code(self):
        def broker(operation, payload):
            raise RuntimeError("broker_mcp_failure")
        code, out = self.run_cli(["--root", str(self.root), "--heartbeat"], broker)
        self.assertEqual(code, 4)
        self.assertTrue(out.startswith("SYSTEM_FAILURE "))

    def test_scheduled_gate_skips_broker_outside_window(self):
        def broker(operation, payload):
            raise AssertionError("no broker access outside market window")
        with patch.object(mr, "market_window_open", return_value=False):
            code, out = self.run_cli(["--root", str(self.root), "--scheduled", "--heartbeat"], broker)
        self.assertEqual((code, out), (0, ""))

    def test_scheduled_gate_runs_broker_inside_window(self):
        with patch.object(mr, "market_window_open", return_value=True):
            code, out = self.run_cli(["--root", str(self.root), "--scheduled", "--heartbeat"], self.healthy)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["verified"], True)

    def test_repaired_line_printed_for_new_fill(self):
        plan = {"action": "BUY", "symbol": "ZS", "quantity": 3, "stop": 151.24, "target": 184.37}
        (self.root / "order_ledger.jsonl").write_text(json.dumps({"client_order_id": "p", "status": "filled"}) + "\n")
        (self.root / "trade_journal.jsonl").write_text(json.dumps({"action": "BUY", "symbol": "ZS", "quantity": 3, "status": "filled"}) + "\n")
        (self.root / "private" / "order_intents.jsonl").write_text(json.dumps({"client_order_id": "p", "plan": plan}) + "\n")
        (self.root / "private" / "protection_orders.jsonl").write_text(json.dumps({
            "parent_client_order_id": "p", "protection_client_order_id": "r", "symbol": "ZS",
            "quantity": 3, "stop": 151.24, "target": 184.37, "registered_at": "2026-09-08T14:00:00Z"}) + "\n")
        target = {"client_order_id": "r", "symbol": "ZS", "side": "sell", "position_intent": "sell_to_close",
                  "order_class": "oco", "type": "limit", "qty": "3", "filled_qty": "3",
                  "filled_avg_price": "184.44", "filled_at": "2026-09-14T14:48:15.061577Z",
                  "status": "filled", "limit_price": "184.37", "time_in_force": "gtc",
                  "legs": [{"client_order_id": "s", "status": "canceled", "type": "stop",
                            "stop_price": "151.24", "time_in_force": "gtc", "side": "sell",
                            "position_intent": "sell_to_close", "order_class": "oco", "symbol": "ZS",
                            "qty": "3", "filled_qty": "0"}]}
        parent = {"client_order_id": "p", "symbol": "ZS", "side": "buy", "position_intent": "buy_to_open",
                  "order_class": "bracket", "qty": "3", "filled_qty": "3", "filled_avg_price": "162.79",
                  "filled_at": "2026-09-08T13:40:00Z", "status": "filled",
                  "legs": [{"client_order_id": "o1", "status": "expired", "side": "sell",
                            "position_intent": "sell_to_close", "order_class": "bracket", "type": "limit",
                            "qty": "3", "filled_qty": "0", "limit_price": "184.37", "symbol": "ZS", "legs": []},
                           {"client_order_id": "o2", "status": "canceled", "side": "sell",
                            "position_intent": "sell_to_close", "order_class": "bracket", "type": "stop",
                            "qty": "3", "filled_qty": "0", "stop_price": "151.24", "symbol": "ZS", "legs": []}]}
        orders = {"p": parent, "r": target}

        def broker(operation, payload):
            return {"positions": [], "open_orders": [], "orders": [orders[ref] for ref in payload["client_order_ids"]],
                    "captured_at": "2026-09-16T14:00:00Z"}

        code, out = self.run_cli(["--root", str(self.root)], broker)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "RECONCILIATION repaired ZS r")
        journal = mr.read_rows(self.root / "trade_journal.jsonl")
        self.assertEqual(len(journal), 2)
        self.assertEqual(journal[-1]["entry"], 184.44)


if __name__ == "__main__":
    unittest.main()
