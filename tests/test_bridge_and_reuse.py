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


def _reusable_candidate(now):
    return {
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


class BridgeCommandTests(unittest.TestCase):
    def test_bridge_command_pins_runtime_and_targets_canonical_script(self):
        cmd = autotrader.bridge_command("snapshot")
        index = cmd.index("--with")
        self.assertEqual(cmd[index + 1], "fastmcp<4")
        self.assertTrue(cmd[0].startswith("/"), cmd[0])
        self.assertIn("broker_mcp_bridge.py", cmd[-2])
        self.assertEqual(cmd[-1], "snapshot")


class BridgeFailureDiagnosticsTests(unittest.TestCase):
    def test_bridge_failure_diagnostics_cases(self):
        cases = (
            ("test_failure_raises_typed_error_and_records_private_diagnostics", _fail_process("server crashed\n"), "snapshot", {"symbol": "AAPL"}, "rich"),
            ("test_diagnostics_never_reach_public_stdout_path", _fail_process("secret-ish stderr"), "snapshot", {"symbol": "AAPL"}, "exists"),
            ("test_unparseable_success_stdout_is_typed_failure_with_diagnostics", _ok_process("not json at all"), "snapshot", {"symbol": "AAPL"}, "unparseable_output"),
            ("test_zero_exit_provider_rejection_is_typed_failure", _ok_process(json.dumps({"data": {"error": {"message": "API rejected the order"}}})), "place", {"order": {}}, "provider_error"),
        )
        for name, response, operation, payload, checks in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as td:
                path = Path(td) / "bridge_diagnostics.jsonl"
                with patch.object(autotrader, "PRIVATE_DIR", Path(td)), patch("autotrader.subprocess.run", return_value=response):
                    context = self.assertRaisesRegex(RuntimeError, "broker_mcp_failure") if checks == "provider_error" else self.assertRaises(RuntimeError)
                    with context as ctx:
                        autotrader._broker_bridge(operation, payload)
                if checks == "exists":
                    self.assertTrue(path.exists())
                    continue
                rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
                if checks == "rich":
                    self.assertIn("broker_mcp_failure", str(ctx.exception))
                    self.assertEqual(len(rows), 1)
                    row = rows[0]
                    self.assertEqual(row["operation"], "snapshot")
                    self.assertEqual(row["returncode"], 3)
                    self.assertIn("server crashed", row["stderr_tail"])
                    self.assertTrue(row["attempts_made"] >= 1)
                    self.assertIn("duration_ms", row)
                else:
                    self.assertEqual(rows[0]["failure_class"], checks)


class BridgeRetryTests(unittest.TestCase):
    def test_read_operation_retries_once_on_transient_failure(self):
        with tempfile.TemporaryDirectory() as td, patch.object(autotrader, "PRIVATE_DIR", Path(td)), patch(
            "autotrader.subprocess.run", side_effect=[_fail_process("transient"), _ok_process('{"cash":1}')]
        ) as run:
            result = autotrader._broker_bridge("snapshot", {"symbol": "AAPL"})
        self.assertEqual(result, {"cash": 1})
        self.assertEqual(run.call_count, 2)

    def test_mutating_operations_are_never_retried(self):
        for operation, payload in (("place", {"order": {}}), ("protect", {"symbol": "ZS"})):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as td, patch.object(
                autotrader, "PRIVATE_DIR", Path(td)
            ), patch(
                "autotrader.subprocess.run", side_effect=[_fail_process("transient"), _ok_process("{}")]
            ) as run:
                with self.assertRaises(RuntimeError):
                    autotrader._broker_bridge(operation, payload)
                self.assertEqual(run.call_count, 1)

    def test_transport_preserves_exact_invocation_and_single_attempt_exception(self):
        import broker_process
        for error in (OSError("launch"), ValueError("unexpected"), subprocess.TimeoutExpired(["fixture"], 17)):
            with self.subTest(error=type(error).__name__), patch("subprocess.run", side_effect=error) as run:
                with self.assertRaises(type(error)):
                    broker_process.run_bridge(["fixture"], input="raw stdin\n", timeout=17, cwd=None, check=False, run=run)
                run.assert_called_once_with(["fixture"], input="raw stdin\n", text=True, capture_output=True, timeout=17, cwd=None, check=False)


class RadarReuseFirstTests(unittest.TestCase):
    def test_research_failure_does_not_reuse_reviewed_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            now = dt.datetime.now(dt.timezone.utc)
            candidate = {"symbol": "METC", "sources_verified_at": (now - dt.timedelta(minutes=1)).isoformat().replace("+00:00", "Z")}
            (root / "candidates.jsonl").write_text(json.dumps(candidate) + "\n", encoding="utf-8")
            (root / "autonomy_config.json").write_text("{}", encoding="utf-8")
            reviews = root / "private" / "reviews.jsonl"
            reviews.parent.mkdir()
            reviews.write_text(json.dumps({"timestamp": now.isoformat().replace("+00:00", "Z"), "reviews": [{"decision": "HOLD"}]}) + "\n", encoding="utf-8")
            import contextlib
            import io
            output = io.StringIO()
            with patch.object(alpha_radar, "ROOT", root), patch.object(alpha_radar, "candidate_preflight", return_value=[]), patch.object(alpha_radar, "qualified", return_value=True), patch.object(alpha_radar, "live_research", side_effect=alpha_radar.ResearchFailure("research_source_retrieval_failed")), contextlib.redirect_stdout(output):
                code = alpha_radar.main_with_args(alpha_radar.argparse.Namespace(dry_run_fixture=False))
            self.assertEqual(code, 3)
            self.assertEqual(output.getvalue().strip(), "SYSTEM_FAILURE research_source_retrieval_failed")

    def test_approved_but_pre_submission_blocked_dossier_is_reusable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            now = dt.datetime.now(dt.timezone.utc)
            candidate = {"symbol": "METC", "dossier_hash": "dossier-a", "sources_verified_at": (now - dt.timedelta(minutes=2)).isoformat().replace("+00:00", "Z")}
            candidates = root / "candidates.jsonl"
            candidates.write_text(json.dumps(candidate) + "\n")
            (root / "autonomy_config.json").write_text("{}")
            reviews = root / "private" / "reviews.jsonl"
            reviews.parent.mkdir()
            reviews.write_text("".join(json.dumps(row) + "\n" for row in [
                {"timestamp": (now - dt.timedelta(minutes=1)).isoformat().replace("+00:00", "Z"), "dossier_hash": "dossier-a", "evidence_id": "evidence-a", "reviews": [{"decision": "APPROVE"}, {"decision": "APPROVE"}]},
                {"timestamp": now.isoformat().replace("+00:00", "Z"), "dossier_hash": "dossier-a", "evidence_id": "evidence-a", "reviews": [{"decision": "execution_retryable"}]},
            ]))
            (root / "order_ledger.jsonl").write_text(json.dumps({"evidence_id": "evidence-a", "status": "rejected", "reason": ["spread_too_wide"]}) + "\n")
            with patch.object(alpha_radar, "candidate_preflight", return_value=[]), patch.object(alpha_radar, "qualified", return_value=True):
                self.assertEqual(alpha_radar.reusable_fresh_candidate(candidates, reviews, now=now), candidate)

    def test_shared_fresh_selection_keeps_review_gate_optional(self):
        now = dt.datetime(2026, 9, 5, 14, 30, tzinfo=dt.timezone.utc)
        row = {"sources_verified_at": "2026-09-05T14:29:00Z"}
        with patch.object(alpha_radar, "candidate_preflight", return_value=[]), patch.object(alpha_radar, "qualified", return_value=True):
            self.assertIsNone(alpha_radar._select_fresh_candidate(
                [row], {}, now, 60, latest_review="2026-09-05T14:29:00Z",
            ))
            self.assertIs(alpha_radar._select_fresh_candidate([row], {}, now, 60), row)

    def test_live_research_path_reuses_fresh_unreviewed_candidate_without_model_calls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidates = root / "candidates.jsonl"
            now = dt.datetime.now(dt.timezone.utc)
            candidate = _reusable_candidate(now)
            candidates.write_text(json.dumps(candidate) + "\n")
            (root / "autonomy_config.json").write_text(json.dumps({"min_price_usd": 10, "max_position_usd": 500}))
            with patch.object(alpha_radar, "ROOT", root), patch(
                "alpha_radar.subprocess.run", side_effect=AssertionError("model calls must not run")
            ):
                reused = alpha_radar.reusable_fresh_candidate(root / "candidates.jsonl", root / "private" / "reviews.jsonl")
            self.assertIsNotNone(reused)
            self.assertEqual(reused["symbol"], "DELL")

    def test_reusable_candidate_rejection_cases(self):
        cases = (
            ("test_reuse_is_blocked_once_a_later_review_exists", "2026-09-05T13:00:00Z", "2026-09-05T13:01:00Z", True, {}),
            ("test_stale_candidate_is_not_reused", "2026-09-05T13:00:00Z", "2026-09-05T13:01:00Z", False, {}),
            ("test_candidate_that_will_expire_before_consumer_is_not_reused", "2026-09-05T13:35:00Z", "2026-09-05T13:35:00Z", False, {"max_research_age_minutes": 60}),
        )
        for name, researched, verified, reviewed, config in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                candidate = {
                    "symbol": "DELL", "researched_at": researched, "sources_verified_at": verified,
                    "sources": [{"url": "https://a.example/1"}, {"url": "https://b.example/2"}],
                    "price": 100.0, "spy_price": 500.0, "instrument_type": "cash_equity",
                    "setup_type": "breakout", "earnings_event_at": "2026-09-10T20:00:00Z",
                    "planned_exit_at": "2026-09-18T20:00:00Z", "horizon_rationale": "swing",
                }
                (root / "candidates.jsonl").write_text(json.dumps(candidate) + "\n")
                (root / "autonomy_config.json").write_text(json.dumps({"min_price_usd": 10, "max_position_usd": 500, **config}))
                reviews = root / "private" / "reviews.jsonl"
                if reviewed:
                    reviews.parent.mkdir(parents=True)
                    reviews.write_text(json.dumps({"timestamp": "2026-09-05T13:20:00Z", "reviews": [None, None]}) + "\n")
                clock = {} if reviewed else {"now": dt.datetime(2026, 9, 5, 14, 30, tzinfo=dt.timezone.utc)}
                with patch.object(alpha_radar, "ROOT", root):
                    self.assertIsNone(alpha_radar.reusable_fresh_candidate(root / "candidates.jsonl", reviews, **clock))

    def test_main_reuses_before_running_research(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            now = dt.datetime.now(dt.timezone.utc)
            candidate = _reusable_candidate(now)
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
