import unittest
import datetime as dt

import alpha_radar
import autotrader


class ResearchTimestampTests(unittest.TestCase):
    """Researched_at is model-authored, so intake must sanitize it."""

    def test_intake_timestamp_sanitizes_missing_future_stale_and_malformed_values(self):
        now = "2026-09-04T19:00:00Z"
        cases = (
            ("missing", {}, now),
            ("future", {"researched_at": "2026-09-05T00:00:00Z"}, now),
            ("stale", {"researched_at": "2026-09-04T12:00:00Z"}, now),
            ("recent", {"researched_at": "2026-09-04T18:55:00Z"}, "2026-09-04T18:55:00Z"),
            ("malformed", {"researched_at": "September fourth"}, now),
            ("naive UTC", {"researched_at": "2026-09-04T18:56:00"}, "2026-09-04T18:56:00"),
        )
        for label, candidate, expected in cases:
            with self.subTest(case=label):
                self.assertEqual(alpha_radar.ensure_researched_at(candidate, now=now)["researched_at"], expected)

    def test_execution_age_uses_deterministic_source_verification_timestamp(self):
        candidate={
            "researched_at":"2026-09-04T12:00:00Z",
            "sources_verified_at":"2026-09-04T19:00:00Z",
        }
        now=dt.datetime(2026,9,4,19,5,tzinfo=dt.timezone.utc)
        self.assertEqual(autotrader.research_age_minutes(candidate,now=now),5.0)

    def test_execution_age_fails_closed_without_valid_source_verification_timestamp(self):
        now=dt.datetime(2026,9,4,19,5,tzinfo=dt.timezone.utc)
        for value in (None,"bad","2026-09-04T19:00:00"):
            self.assertIsNone(autotrader.research_age_minutes({"sources_verified_at":value},now=now))


if __name__ == "__main__":
    unittest.main()
