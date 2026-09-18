import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autotrader


class PlacingNotificationTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "action": "BUY", "symbol": "ZS", "quantity": 3,
            "order_type": "limit", "limit_price": 162.79,
            "stop": 151.24, "target": 184.37,
            "horizon": "5 sessions", "confidence": 0.8, "thesis": "private thesis",
        }
        self.ref = "tradey-private-reference"
        self.accepted = {
            "client_order_id": self.ref, "status": "accepted", "symbol": "ZS",
            "side": "buy", "qty": "3", "type": "limit", "order_class": "bracket",
        }

    def test_placing_notification_emits_once_without_private_identifier(self):
        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / "notifications.jsonl"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertTrue(autotrader.emit_placing_notification_once(marker, self.ref, self.plan, "paper"))
                self.assertTrue(autotrader.emit_placing_notification_once(marker, self.ref, self.plan, "paper"))
        self.assertEqual(output.getvalue(), "ORDER placing BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 PAPER\n")
        self.assertNotIn(self.ref, output.getvalue())
        self.assertNotIn("accepted", output.getvalue())
        self.assertNotIn("filled", output.getvalue())

    def test_placing_notification_live_mode_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertFalse(autotrader.emit_placing_notification_once(
                    Path(td) / "notifications.jsonl", self.ref, self.plan, "live"))
        self.assertEqual(output.getvalue(), "")

    def test_placing_notification_invalid_plan_fails_closed(self):
        for plan in (
            dict(self.plan, order_type="market"),
            dict(self.plan, action="HOLD"),
            dict(self.plan, symbol="AAPL123"),
            dict(self.plan, quantity=0),
            dict(self.plan, stop=-1),
        ):
            with self.subTest(plan=plan), tempfile.TemporaryDirectory() as td:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertFalse(autotrader.emit_placing_notification_once(
                        Path(td) / "notifications.jsonl", self.ref, plan, "paper"))
                self.assertEqual(output.getvalue(), "")

    def test_placing_notification_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / "notifications.jsonl"
            marker.write_text("not-json\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertFalse(autotrader.emit_placing_notification_once(marker, self.ref, self.plan, "paper"))
        self.assertEqual(output.getvalue(), "")

    def test_placing_notification_print_failure_remains_retryable(self):
        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / "notifications.jsonl"
            with patch("builtins.print", side_effect=OSError("pipe")):
                with self.assertRaises(OSError):
                    autotrader.emit_placing_notification_once(marker, self.ref, self.plan, "paper")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertTrue(autotrader.emit_placing_notification_once(marker, self.ref, self.plan, "paper"))
        self.assertEqual(output.getvalue(), "ORDER placing BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 PAPER\n")

    def test_placement_emits_placing_notification_once_with_marker_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "private").mkdir()
            (root / "public").mkdir()
            (root / "autonomy_config.json").write_text(json.dumps({
                "enabled": True, "broker_mode": "paper", "kill_switch_path": "KILL_SWITCH",
            }))
            plan = self.plan
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertTrue(autotrader.emit_placing_notification_once(
                    root / "private" / "order_notifications.jsonl", self.ref, plan, "paper"))
            markers = [json.loads(line) for line in (root / "private" / "order_notifications.jsonl").read_text().splitlines()]
            self.assertEqual([row["state"] for row in markers], ["prepared", "emitted"])
            self.assertTrue(all("client_order_id" not in row for row in markers))
            self.assertEqual(output.getvalue(), "ORDER placing BUY 3 ZS LIMIT 162.79 STOP 151.24 TARGET 184.37 PAPER\n")

    def test_invalid_readback_does_not_mutate_ledger_or_journal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = root / "ledger.jsonl"
            intents = root / "intents.jsonl"
            journal = root / "journal.jsonl"
            ledger.write_text(json.dumps({"client_order_id": self.ref, "status": "placed"}) + "\n")
            intents.write_text(json.dumps({"client_order_id": self.ref, "plan": self.plan}) + "\n")
            before = ledger.read_text()
            wrong = dict(self.accepted, client_order_id="other", status="filled",
                         filled_qty="3", filled_avg_price="162.80")
            with self.assertRaises(RuntimeError):
                autotrader.reconcile_pending_orders(
                    ledger, intents, journal, lambda operation, payload: wrong)
            self.assertEqual(ledger.read_text(), before)
            self.assertFalse(journal.exists())

    def test_pending_order_recovery_does_not_renotify(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "private").mkdir()
            (root / "public").mkdir()
            (root / "autonomy_config.json").write_text(json.dumps({
                "enabled": True, "broker_mode": "paper", "kill_switch_path": "KILL_SWITCH",
            }))
            (root / "order_ledger.jsonl").write_text(json.dumps({
                "client_order_id": self.ref, "status": "placed",
            }) + "\n")
            (root / "private" / "order_intents.jsonl").write_text(json.dumps({
                "client_order_id": self.ref, "plan": self.plan,
            }) + "\n")
            calls = []
            def broker(operation, payload=None):
                calls.append(operation)
                self.assertEqual(operation, "reconcile")
                return self.accepted
            output = io.StringIO()
            with patch.object(autotrader, "ROOT", root), patch(
                "autotrader._broker_bridge", side_effect=broker
            ), contextlib.redirect_stdout(output):
                code = autotrader.run(autotrader.argparse.Namespace(
                    dry_run_fixture=False, live_dry_run=False))
            self.assertEqual(code, 0)
            self.assertEqual(calls, ["reconcile"])
            self.assertEqual(output.getvalue(), "")

    def test_multiple_pending_parents_recover_silently(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "private").mkdir()
            (root / "public").mkdir()
            (root / "autonomy_config.json").write_text(json.dumps({
                "enabled": True, "broker_mode": "paper", "kill_switch_path": "KILL_SWITCH",
            }))
            second_ref = "tradey-private-reference-two"
            second_plan = dict(self.plan, symbol="AAPL", quantity=2,
                               limit_price=100.00, stop=95.00, target=110.00)
            ledger_rows = [
                {"client_order_id": self.ref, "status": "placed"},
                {"client_order_id": second_ref, "status": "submission_unknown"},
            ]
            intent_rows = [
                {"client_order_id": self.ref, "plan": self.plan},
                {"client_order_id": second_ref, "plan": second_plan},
            ]
            (root / "order_ledger.jsonl").write_text(
                "\n".join(json.dumps(row) for row in ledger_rows) + "\n")
            (root / "private" / "order_intents.jsonl").write_text(
                "\n".join(json.dumps(row) for row in intent_rows) + "\n")
            orders = {
                self.ref: self.accepted,
                second_ref: {
                    "client_order_id": second_ref, "status": "new", "symbol": "AAPL",
                    "side": "buy", "qty": "2", "type": "limit", "order_class": "bracket",
                },
            }
            calls = []
            def broker(operation, payload=None):
                calls.append(operation)
                self.assertEqual(operation, "reconcile")
                return orders[payload["client_order_id"]]
            output = io.StringIO()
            with patch.object(autotrader, "ROOT", root), patch(
                "autotrader._broker_bridge", side_effect=broker
            ), contextlib.redirect_stdout(output):
                code = autotrader.run(autotrader.argparse.Namespace(
                    dry_run_fixture=False, live_dry_run=False))
            self.assertEqual(code, 0)
            self.assertEqual(calls, ["reconcile", "reconcile"])
            self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
