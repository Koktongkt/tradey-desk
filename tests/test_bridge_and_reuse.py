"""W3 bridge reliability + W1 radar reuse-first tests.

W3: the broker bridge must pin the client fastmcp major version to match the
server's fastmcp<4 pin, resolve uv by absolute path, record typed private
diagnostics (with captured stderr) on failure, and retry only read-only
operations. Execution operations must never be retried.

W1: the radar must reuse a fresh verified, not-yet-reviewed candidate instead
of paying for a full scout+synthesis research cycle.
"""
import datetime as dt
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import alpha_radar
import autotrader


def _ok_process(stdout="{}"):
    return subprocess.CompletedProcess([], 0, stdout, "")


def _fail_process(stderr="boom"):
    return subprocess.CompletedProcess([], 3, "", stderr)


class BridgeCommandTests(unittest.TestCase):
    def test_bridge_command_pins_fastmcp_below_4(self):
        cmd = autotrader.bridge_command("snapshot")
        index = cmd.index("--with")
        self.assertEqual(cmd[index + 1], "fastmcp<4")

    def test_bridge_command_uses_absolute_uv_path(self):
        cmd = autotrader.bridge_command("snapshot")
        self.assertTrue(cmd[0].startswith("/"), cmd[0])

    def test_bridge_command_targets_repo_bridge_script(self):
        cmd = autotrader.bridge_command("snapshot")
        self.assertIn("broker_mcp_bridge.py", cmd[-2])
        self.assertEqual(cmd[-1], "snapshot")


class BridgeFailureDiagnosticsTests(unittest.TestCase):
    def test_failure_raises_typed_error_and_records_private_diagnostics(self):
        with tempfile.TemporaryDirectory() as td:
            fake_private = Path(td)
            with patch.object(autotrader, "PRIVATE_DIR", fake_private), patch(
                "autotrader.subprocess.run", return_value=_fail_process("server crashed\n")
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    autotrader._broker_bridge("snapshot", {"symbol": "AAPL"})
            self.assertIn("broker_mcp_failure", str(ctx.exception))
            rows = [json.loads(line) for line in (fake_private / "bridge_diagnostics.jsonl").read_text().splitlines() if line.strip()]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["operation"], "snapshot")
            self.assertEqual(row["returncode"], 3)
            self.assertIn("server crashed", row["stderr_tail"])
            self.assertTrue(row["attempts_made"] >= 1)
            self.assertIn("duration_ms", row)

    def test_diagnostics_never_reach_public_stdout_path(self):
        with tempfile.TemporaryDirectory() as td:
            fake_private = Path(td)
            with patch.object(autotrader, "PRIVATE_DIR", fake_private), patch(
                "autotrader.subprocess.run", return_value=_fail_process("secret-ish stderr")
            ):
                with self.assertRaises(RuntimeError):
                    autotrader._broker_bridge("snapshot", {"symbol": "AAPL"})
            self.assertTrue((fake_private / "bridge_diagnostics.jsonl").exists())

    def test_unparseable_success_stdout_is_typed_failure_with_diagnostics(self):
        with tempfile.TemporaryDirectory() as td:
            fake_private = Path(td)
            with patch.object(autotrader, "PRIVATE_DIR", fake_private), patch(
                "autotrader.subprocess.run", return_value=_ok_process("not json at all")
            ):
                with self.assertRaises(RuntimeError):
                    autotrader._broker_bridge("snapshot", {"symbol": "AAPL"})
            rows = [json.loads(line) for line in (fake_private / "bridge_diagnostics.jsonl").read_text().splitlines() if line.strip()]
            self.assertEqual(rows[0]["failure_class"], "unparseable_output")


class BridgeRetryTests(unittest.TestCase):
    def test_read_operation_retries_once_on_transient_failure(self):
        with tempfile.TemporaryDirectory() as td, patch.object(autotrader, "PRIVATE_DIR", Path(td)), patch(
            "autotrader.subprocess.run", side_effect=[_fail_process("transient"), _ok_process('{"cash":1}')]
        ) as run:
            result = autotrader._broker_bridge("snapshot", {"symbol": "AAPL"})
        self.assertEqual(result, {"cash": 1})
        self.assertEqual(run.call_count, 2)

    def test_place_operation_is_never_retried(self):
        with tempfile.TemporaryDirectory() as td, patch.object(autotrader, "PRIVATE_DIR", Path(td)), patch(
            "autotrader.subprocess.run", side_effect=[_fail_process("transient"), _ok_process("{}")]
        ) as run:
            with self.assertRaises(RuntimeError):
                autotrader._broker_bridge("place", {"order": {}})
        self.assertEqual(run.call_count, 1)


class RadarReuseFirstTests(unittest.TestCase):
    def test_live_research_path_reuses_fresh_unreviewed_candidate_without_model_calls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidates = root / "candidates.jsonl"
            now = dt.datetime.now(dt.timezone.utc)
            candidate = {
                "symbol": "DELL",
                "researched_at": (now - dt.timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                "sources_verified_at": (now - dt.timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "sources": [{"url": "https://a.example/1"}, {"url": "https://b.example/2"}],
                "price": 100.0,
                "spy_price": 500.0,
                "instrument_type": "cash_equity",
                "setup_type": "breakout",
                "earnings_event_at": (now + dt.timedelta(days=30)).isoformat().replace("+00:00", "Z"),
                "planned_exit_at": (now + dt.timedelta(days=7)).isoformat().replace("+00:00", "Z"),
                "horizon_rationale": "swing",
            }
            candidates.write_text(json.dumps(candidate) + "\n")
            (root / "autonomy_config.json").write_text(json.dumps({"min_price_usd": 10, "max_position_usd": 500}))
            with patch.object(alpha_radar, "ROOT", root), patch(
                "alpha_radar.subprocess.run", side_effect=AssertionError("model calls must not run")
            ):
                reused = alpha_radar.reusable_fresh_candidate(root / "candidates.jsonl", root / "private" / "reviews.jsonl")
            self.assertIsNotNone(reused)
            self.assertEqual(reused["symbol"], "DELL")

    def test_reuse_is_blocked_once_a_later_review_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = {
                "symbol": "DELL",
                "researched_at": "2026-09-05T13:00:00Z",
                "sources_verified_at": "2026-09-05T13:01:00Z",
                "sources": [{"url": "https://a.example/1"}, {"url": "https://b.example/2"}],
                "price": 100.0,
                "spy_price": 500.0,
                "instrument_type": "cash_equity",
                "setup_type": "breakout",
                "earnings_event_at": "2026-09-10T20:00:00Z",
                "planned_exit_at": "2026-09-18T20:00:00Z",
                "horizon_rationale": "swing",
            }
            (root / "candidates.jsonl").write_text(json.dumps(candidate) + "\n")
            (root / "autonomy_config.json").write_text(json.dumps({"min_price_usd": 10, "max_position_usd": 500}))
            reviews = root / "private" / "reviews.jsonl"
            reviews.parent.mkdir(parents=True)
            reviews.write_text(json.dumps({"timestamp": "2026-09-05T13:20:00Z", "reviews": [None, None]}) + "\n")
            with patch.object(alpha_radar, "ROOT", root):
                self.assertIsNone(
                    alpha_radar.reusable_fresh_candidate(root / "candidates.jsonl", reviews)
                )

    def test_stale_candidate_is_not_reused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = {
                "symbol": "DELL",
                "researched_at": "2026-09-05T13:00:00Z",
                "sources_verified_at": "2026-09-05T13:01:00Z",  # > 60 min old at 14:30
                "sources": [{"url": "https://a.example/1"}, {"url": "https://b.example/2"}],
                "price": 100.0,
                "spy_price": 500.0,
                "instrument_type": "cash_equity",
                "setup_type": "breakout",
                "earnings_event_at": "2026-09-10T20:00:00Z",
                "planned_exit_at": "2026-09-18T20:00:00Z",
                "horizon_rationale": "swing",
            }
            (root / "candidates.jsonl").write_text(json.dumps(candidate) + "\n")
            (root / "autonomy_config.json").write_text(json.dumps({"min_price_usd": 10, "max_position_usd": 500}))
            now = alpha_radar.dt.datetime(2026, 9, 5, 14, 30, tzinfo=alpha_radar.dt.timezone.utc)
            with patch.object(alpha_radar, "ROOT", root):
                self.assertIsNone(
                    alpha_radar.reusable_fresh_candidate(
                        root / "candidates.jsonl", root / "private" / "reviews.jsonl", now=now
                    )
                )

    def test_main_reuses_before_running_research(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            now = dt.datetime.now(dt.timezone.utc)
            candidate = {
                "symbol": "DELL",
                "researched_at": (now - dt.timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                "sources_verified_at": (now - dt.timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "sources": [{"url": "https://a.example/1"}, {"url": "https://b.example/2"}],
                "price": 100.0,
                "spy_price": 500.0,
                "instrument_type": "cash_equity",
                "setup_type": "breakout",
                "earnings_event_at": (now + dt.timedelta(days=30)).isoformat().replace("+00:00", "Z"),
                "planned_exit_at": (now + dt.timedelta(days=7)).isoformat().replace("+00:00", "Z"),
                "horizon_rationale": "swing",
            }
            (root / "candidates.jsonl").write_text(json.dumps(candidate) + "\n")
            (root / "autonomy_config.json").write_text(json.dumps({"min_price_usd": 10, "max_position_usd": 500}))
            args = alpha_radar.argparse.Namespace(dry_run_fixture=False)
            with patch.object(alpha_radar, "ROOT", root), patch(
                "alpha_radar.live_research", side_effect=AssertionError("research must not run")
            ):
                captured = __import__("io").StringIO()
                import contextlib
                with contextlib.redirect_stdout(captured):
                    code = alpha_radar.main_with_args(args)
            self.assertEqual(code, 0)
            self.assertIn("reused_fresh_candidate DELL", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
