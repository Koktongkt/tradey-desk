"""Executable contracts for the layered unittest architecture."""

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sqlite_ledger

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "tests" / "run_tests.py"
MANIFEST_PATH = ROOT / "tests" / "test_manifest.json"


def load_runner():
    spec = importlib.util.spec_from_file_location("tradey_test_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load layered test runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestArchitectureTests(unittest.TestCase):
    def test_manifest_classifies_every_discovered_module_exactly_once(self):
        runner = load_runner()
        manifest = runner.load_manifest(MANIFEST_PATH)
        discovered = runner.discover_modules(ROOT / "tests")

        runner.validate_manifest(manifest, discovered)

        classified = [
            module
            for layer in ("fast", "scenario", "full_only")
            for module in manifest["layers"][layer]
        ]
        self.assertEqual(set(classified), discovered)
        self.assertEqual(len(classified), len(set(classified)))

    def test_tiers_are_explicit_unions(self):
        runner = load_runner()
        manifest = runner.load_manifest(MANIFEST_PATH)

        fast = runner.modules_for_tier(manifest, "fast")
        scenario = runner.modules_for_tier(manifest, "scenario")
        full = runner.modules_for_tier(manifest, "full")

        self.assertEqual(fast, manifest["layers"]["fast"])
        self.assertEqual(scenario, manifest["layers"]["scenario"])
        self.assertEqual(
            full,
            manifest["layers"]["fast"]
            + manifest["layers"]["scenario"]
            + manifest["layers"]["full_only"],
        )

    def test_manifest_declares_safety_and_vertical_workflow_layers(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        self.assertIn("test_safety", manifest["layers"]["fast"])
        self.assertIn("test_sqlite_ledger", manifest["layers"]["fast"])
        self.assertIn("test_pipeline", manifest["layers"]["scenario"])
        self.assertIn("test_autotrader_reconciliation", manifest["layers"]["scenario"])
        self.assertIn("test_alpha_radar", manifest["layers"]["full_only"])

    def test_operational_guard_matches_canonical_sqlite_streams(self):
        runner = load_runner()

        self.assertIs(runner.OPERATIONAL_ROOT_FILES, sqlite_ledger.DEFAULT_STREAMS)
        self.assertEqual(
            set(runner.OPERATIONAL_ROOT_FILES),
            set(sqlite_ledger.DEFAULT_STREAMS),
        )

    def test_operational_snapshot_detects_content_and_timestamp_changes(self):
        runner = load_runner()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = root / "candidates.jsonl"
            candidate.write_text("{}\n", encoding="utf-8")
            private = root / "private"
            private.mkdir()
            database = private / "trading_journal.sqlite3"
            database.write_bytes(b"sqlite")

            before = runner.snapshot_operational_state(root)
            initial_stat = candidate.stat()
            os.utime(
                candidate,
                ns=(initial_stat.st_atime_ns, initial_stat.st_mtime_ns + 1_000_000_000),
            )
            after_touch = runner.snapshot_operational_state(root)
            self.assertEqual(
                runner.changed_operational_paths(before, after_touch),
                ["candidates.jsonl"],
            )

            database.write_bytes(b"changed")
            after_write = runner.snapshot_operational_state(root)
            self.assertEqual(
                runner.changed_operational_paths(after_touch, after_write),
                ["private/trading_journal.sqlite3"],
            )

    def test_operational_snapshot_detects_candidate_outcomes_creation(self):
        runner = load_runner()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            before = runner.snapshot_operational_state(root)
            (root / "candidate_outcomes.jsonl").write_text("{}\n", encoding="utf-8")
            after = runner.snapshot_operational_state(root)

        self.assertEqual(
            runner.changed_operational_paths(before, after),
            ["candidate_outcomes.jsonl"],
        )

    def test_operational_snapshot_detects_permission_changes(self):
        runner = load_runner()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = root / "candidates.jsonl"
            candidate.write_text("{}\n", encoding="utf-8")
            candidate.chmod(0o600)
            before = runner.snapshot_operational_state(root)
            candidate.chmod(0o644)
            after = runner.snapshot_operational_state(root)

        self.assertEqual(
            runner.changed_operational_paths(before, after),
            ["candidates.jsonl"],
        )

    def test_tier_detects_operational_mutation_during_test_import(self):
        runner = load_runner()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            test_dir = root / "tests"
            test_dir.mkdir()
            stream = root / "candidate_outcomes.jsonl"
            module = test_dir / "test_import_mutation.py"
            module.write_text(
                "from pathlib import Path\n"
                "import unittest\n"
                f"Path({str(stream)!r}).write_text('{{}}\\n', encoding='utf-8')\n"
                "class ImportMutationTest(unittest.TestCase):\n"
                "    def test_placeholder(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            manifest = {
                "version": 1,
                "layers": {
                    "fast": ["test_import_mutation"],
                    "scenario": [],
                    "full_only": [],
                },
            }

            def build_suite(_modules):
                return unittest.defaultTestLoader.discover(
                    str(test_dir), pattern="test_import_mutation.py"
                )

            original_snapshot = runner.snapshot_operational_state

            def snapshot():
                return original_snapshot(root)

            with patch.object(runner, "load_manifest", return_value=manifest), patch.object(
                runner, "discover_modules", return_value={"test_import_mutation"}
            ), patch.object(runner, "build_suite", side_effect=build_suite), patch.object(
                runner, "snapshot_operational_state", side_effect=snapshot
            ), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                passed = runner.run_tier("fast")

        self.assertFalse(passed)

    def test_build_suite_prefers_canonical_tests_directory_over_root_duplicate(self):
        runner = load_runner()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            test_dir = root / "tests"
            test_dir.mkdir()
            module_name = "test_layer_collision"
            (root / f"{module_name}.py").write_text(
                "import unittest\n"
                "class RootDuplicateTest(unittest.TestCase):\n"
                "    def test_wrong_module(self):\n"
                "        self.fail('root duplicate imported')\n",
                encoding="utf-8",
            )
            (test_dir / f"{module_name}.py").write_text(
                "import unittest\n"
                "class CanonicalTest(unittest.TestCase):\n"
                "    def test_canonical(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            original_path = list(sys.path)
            sys.path[:0] = [str(root), str(test_dir)]
            try:
                importlib.import_module(module_name)
                suite = runner.build_suite([module_name], test_dir=test_dir)
            finally:
                sys.path[:] = original_path
                sys.modules.pop(module_name, None)

        self.assertEqual(suite.countTestCases(), 1)


if __name__ == "__main__":
    unittest.main()
