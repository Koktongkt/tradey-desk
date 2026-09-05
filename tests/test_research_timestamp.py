import unittest
import datetime as dt

import alpha_radar
import autotrader


class ResearchTimestampTests(unittest.TestCase):
    """Researched_at is model-authored, so intake must sanitize it."""

    def test_missing_researched_at_is_stamped_at_intake(self):
        c = alpha_radar.ensure_researched_at({}, now="2026-09-04T19:00:00Z")
        self.assertEqual(c["researched_at"], "2026-09-04T19:00:00Z")

    def test_future_researched_at_is_replaced_with_intake_time(self):
        c = alpha_radar.ensure_researched_at(
            {"researched_at": "2026-09-05T00:00:00Z"}, now="2026-09-04T19:00:00Z"
        )
        self.assertEqual(c["researched_at"], "2026-09-04T19:00:00Z")

    def test_researched_at_far_in_the_past_is_replaced_with_intake_time(self):
        c = alpha_radar.ensure_researched_at(
            {"researched_at": "2026-09-04T12:00:00Z"}, now="2026-09-04T19:00:00Z"
        )
        self.assertEqual(c["researched_at"], "2026-09-04T19:00:00Z")

    def test_recent_model_timestamp_within_tolerance_is_kept(self):
        c = alpha_radar.ensure_researched_at(
            {"researched_at": "2026-09-04T18:55:00Z"}, now="2026-09-04T19:00:00Z"
        )
        self.assertEqual(c["researched_at"], "2026-09-04T18:55:00Z")

    def test_unparseable_researched_at_is_replaced_with_intake_time(self):
        c = alpha_radar.ensure_researched_at(
            {"researched_at": "September fourth"}, now="2026-09-04T19:00:00Z"
        )
        self.assertEqual(c["researched_at"], "2026-09-04T19:00:00Z")

    def test_naive_timestamp_is_treated_as_utc(self):
        c = alpha_radar.ensure_researched_at(
            {"researched_at": "2026-09-04T18:56:00"}, now="2026-09-04T19:00:00Z"
        )
        self.assertEqual(c["researched_at"], "2026-09-04T18:56:00")

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
