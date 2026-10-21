"""Subprocess-only probe for tests that must not read the operational journal.

Run against a source-only disposable copy, never an operational checkout.
The caller seeds an independent empty SQLite fixture before starting this file.
"""
import os
from pathlib import Path
import sys
import traceback
import unittest


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "private/trading_journal.sqlite3"
ATTEMPTS = []


def audit(event, args):
    if event not in {"open", "sqlite3.connect"}:
        return
    value = args[0]
    if not isinstance(value, (str, bytes, os.PathLike)):
        return
    raw = os.fsdecode(value)
    if raw.startswith("file:"):
        raw = raw[5:].split("?", 1)[0]
    path = Path(raw).resolve()
    if path != DATABASE and not str(path).startswith(str(DATABASE) + ".") and not str(path).startswith(str(DATABASE) + "-"):
        return
    if event == "open" and not args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        return
    ATTEMPTS.append(event)
    print("OPERATIONAL_JOURNAL_ACCESS", event, file=sys.stderr)
    traceback.print_stack(limit=15, file=sys.stderr)
    raise RuntimeError("test attempted operational journal access")


if __name__ == "__main__":
    # Before importing any application or test module. Attempts are counted even
    # if an application boundary catches the exception and the test stays green.
    sys.addaudithook(audit)
    sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
    methods = [
        "test_research_budget.ResearchBudgetGuardTests." + name
        for name in (
            "test_bounded_focused_stage_preserves_attestation_and_fault_semantics",
            "test_focused_allowance_accounts_for_command_and_prompt_preparation",
            "test_focused_stage_has_150_second_ceiling_with_ample_time",
            "test_focused_stage_obeys_remaining_global_budget",
        )
    ] + ["test_focused_reuse.FocusedReuseTests.test_focused_boundary_keeps_capture_map_separate_and_faults_fatal"]
    suite = unittest.defaultTestLoader.loadTestsFromNames(methods)
    result = unittest.TextTestRunner().run(suite)
    print("OPERATIONAL_JOURNAL_ATTEMPTS", len(ATTEMPTS), file=sys.stderr)
    raise SystemExit(0 if result.wasSuccessful() and not ATTEMPTS else 1)
