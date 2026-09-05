import unittest

import alpha_radar


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


if __name__ == "__main__":
    unittest.main()
