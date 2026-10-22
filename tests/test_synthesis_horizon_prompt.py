"""Prompt-only horizon clarification; validation and dates remain unmodified."""
import datetime as dt
import unittest

import alpha_radar as radar


class SynthesisHorizonPromptTests(unittest.TestCase):
    def test_prompt_anchors_exact_as_of_and_explicit_future_horizon_contract(self):
        now=dt.datetime(2026,10,22,14,17,23,tzinfo=dt.timezone.utc)
        from unittest.mock import patch
        with patch.object(radar.dt,'datetime',wraps=dt.datetime) as dates:
            dates.now.return_value=now
            prompt=radar.synthesis_prompt('',[],{'max_position_usd':500})
        for fragment in ('AS OF UTC: 2026-10-22T14:17:23Z',
                         'AS OF NEW YORK: 2026-10-22T10:17:23-04:00',
                         'timezone-aware ISO 8601', 'strictly later than the AS OF time',
                         '1–30 holding sessions', '1–5 sessions', '6–30 sessions',
                         'entry session counts', 'not calendar days',
                         'Do not copy historical dates', 'not auto-repaired',
                         'broker calendar remains authoritative'):
            self.assertIn(fragment,prompt)

    def test_as_of_anchor_tracks_new_york_date_and_dst(self):
        now=dt.datetime(2026,11,3,0,30,tzinfo=dt.timezone.utc)
        from unittest.mock import patch
        with patch.object(radar.dt,'datetime',wraps=dt.datetime) as dates:
            dates.now.return_value=now
            prompt=radar.synthesis_prompt('',[],{'max_position_usd':500})
        self.assertIn('AS OF UTC: 2026-11-03T00:30:00Z',prompt)
        self.assertIn('AS OF NEW YORK: 2026-11-02T19:30:00-05:00',prompt)
