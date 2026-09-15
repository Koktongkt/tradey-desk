import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import run_cycle


class RadarNotifications(unittest.TestCase):
    def run_output(self, text, mode='radar', code=0):
        with tempfile.TemporaryDirectory() as td:
            audit = Path(td) / 'audit.jsonl'
            out = io.StringIO()
            with patch.object(run_cycle.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, text, '')), contextlib.redirect_stdout(out):
                rc = run_cycle.execute(['fixture'], audit_mode=mode, audit_stage='research', audit_path=audit)
            return rc, out.getvalue(), json.loads(audit.read_text())

    def test_qualified_and_reused_are_distinct(self):
        for event, label in [('candidate_qualified', 'Final qualified candidate: AAPL'), ('reused_fresh_candidate', 'Reusing existing fresh candidate: AAPL (not a new qualification)')]:
            with self.subTest(event=event):
                rc, out, row = self.run_output(f'DECISION {event} AAPL\n')
                self.assertEqual(rc, 0)
                self.assertEqual(out, f'Alpha Radar: {label}. Research only; not a trade approval or execution.\n')
                self.assertEqual(row['decision'], event)

    def test_unrelated_and_untrusted_output_remains_silent(self):
        for text in ['', 'DECISION skipped outside_window', 'DECISION skipped already_completed', 'DECISION candidate_qualified AAPL secret', 'DECISION candidate_qualified AAPL\nprivate data']:
            self.assertEqual(self.run_output(text)[1], '')
        for mode in ['premarket', 'autotrader', 'dashboard', 'postclose']:
            self.assertEqual(self.run_output('DECISION skipped no_fresh_setup', mode=mode)[1], '')

    def test_blocker_still_delivered(self):
        rc, out, row = self.run_output('BLOCKER research_source_freshness_insufficient', code=2)
        self.assertEqual(rc, 2)
        self.assertEqual(out, 'BLOCKER research_source_freshness_insufficient\n')
        self.assertEqual(row['decision'], 'blocked')

    def test_schema_rejection_notifies_as_no_candidate(self):
        rc, out, row = self.run_output('DECISION skipped no_valid_discovery_candidate\n')
        self.assertEqual(rc, 0)
        self.assertEqual(out, 'Alpha Radar: No new qualified candidate (none passed discovery format validation). Research only; no order placed by this scan.\n')
        self.assertEqual(row['decision'], 'skipped')
        self.assertEqual(row['reason'], 'no_valid_discovery_candidate')

    def test_no_candidate_notifies(self):
        rc, out, row = self.run_output('DECISION skipped no_fresh_setup\n')
        self.assertEqual(rc, 0)
        self.assertEqual(out, 'Alpha Radar: No new qualified candidate (no_fresh_setup). Research only; no order placed by this scan.\n')
        self.assertEqual(row['reason'], 'no_fresh_setup')
