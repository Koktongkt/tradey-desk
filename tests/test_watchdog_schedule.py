"""Task 8 fast schedule tests: pure session eligibility, DST, early close, cron union.

No live calls: session fixtures are normalized broker calendar rows only.
"""
from datetime import datetime, timedelta
from unittest import TestCase
from zoneinfo import ZoneInfo

from watchdog.schedule import (
    DAILY_CRON,
    MECHANICAL_CRON,
    eligible,
    eligibility,
    fired_by_cron,
)

NY = ZoneInfo('America/New_York')
UTC = ZoneInfo('UTC')


def session(date_s, open_hm='09:30', close_hm='16:00'):
    """Normalized broker calendar row (watchdog.broker.normalize_session shape)."""
    open_at = datetime.fromisoformat(date_s + 'T' + open_hm).replace(tzinfo=NY)
    close_at = datetime.fromisoformat(date_s + 'T' + close_hm).replace(tzinfo=NY)
    return dict(date=date_s, open=open_hm, close=close_hm,
                open_at=open_at.isoformat(), close_at=close_at.isoformat())


def utc(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


class MechanicalEligibilityTests(TestCase):
    def test_inside_session_at_five_past_is_eligible(self):
        # 2026-10-07 is a Wednesday; 14:05 UTC = 10:05 EDT inside 09:30-16:00.
        ok, reasons, day = eligibility('mechanical', utc(2026, 10, 7, 14, 5), [session('2026-10-07')])
        self.assertTrue(ok)
        self.assertEqual(reasons, [])
        self.assertEqual(day, '2026-10-07')

    def test_outside_session_is_silent_no_op_with_typed_reason(self):
        # 21:05 UTC = 17:05 EDT is after the close.
        ok, reasons, _ = eligibility('mechanical', utc(2026, 10, 7, 21, 5), [session('2026-10-07')])
        self.assertFalse(ok)
        self.assertIn('outside_session', reasons)

    def test_wrong_minute_is_not_eligible_even_inside_session(self):
        ok, reasons, _ = eligibility('mechanical', utc(2026, 10, 7, 14, 6), [session('2026-10-07')])
        self.assertFalse(ok)
        self.assertIn('not_scheduled_slot', reasons)

    def test_mechanical_requires_in_session_not_just_calendar_day(self):
        # :05 slot before the 09:30 open must be a no-op.
        ok, reasons, _ = eligibility('mechanical', utc(2026, 10, 7, 13, 5), [session('2026-10-07')])
        self.assertFalse(ok)
        self.assertIn('outside_session', reasons)


class DailyEligibilityTests(TestCase):
    def test_actual_second_and_microsecond_clocks_are_eligible_in_both_slot_minutes(self):
        for minute in (15, 45):
            for seconds, micros in ((1, 0), (59, 999999)):
                with self.subTest(minute=minute, seconds=seconds):
                    now = utc(2026, 10, 7, 20, minute).replace(second=seconds, microsecond=micros)
                    self.assertTrue(eligibility('daily', now, [session('2026-10-07')])[0])
        self.assertFalse(eligibility('daily', utc(2026, 10, 7, 20, 46), [session('2026-10-07')])[0])

    def test_first_daily_slot_is_close_plus_fifteen(self):
        # 16:15 EDT = 20:15 UTC.
        ok, reasons, day = eligibility('daily', utc(2026, 10, 7, 20, 15), [session('2026-10-07')])
        self.assertTrue(ok)
        self.assertEqual(reasons, [])
        self.assertEqual(day, '2026-10-07')

    def test_daily_second_slot_and_window_end(self):
        # Window is close+15..close+45 = 20:15..20:45 UTC (EDT close).
        self.assertTrue(eligible('daily', utc(2026, 10, 7, 20, 45), [session('2026-10-07')]))
        ok, reasons, _ = eligibility('daily', utc(2026, 10, 7, 20, 46), [session('2026-10-07')])
        self.assertFalse(ok)
        self.assertEqual(reasons, ['not_scheduled_slot'])

    def test_daily_before_close_plus_fifteen_is_ineligible(self):
        ok, reasons, _ = eligibility('daily', utc(2026, 10, 7, 20, 14), [session('2026-10-07')])
        self.assertFalse(ok)
        self.assertIn('not_scheduled_slot', reasons)

    def test_daily_outside_any_session_day(self):
        ok, reasons, _ = eligibility('daily', utc(2026, 10, 7, 20, 15), [session('2026-10-06')])
        self.assertFalse(ok)
        self.assertIn('no_session_for_run_date', reasons)


class CalendarEdgeTests(TestCase):
    def test_early_close_1300_new_york_daily_slot(self):
        # Early close at 13:00 EST = 18:00 UTC; first slot 18:15 UTC.
        ok, reasons, day = eligibility('daily', utc(2026, 11, 27, 18, 15), [session('2026-11-27', close_hm='13:00')])
        self.assertTrue(ok)
        self.assertEqual(reasons, [])
        self.assertEqual(day, '2026-11-27')

    def test_dst_end_november_est_close_slot(self):
        # After DST ends, 16:00 EST = 21:00 UTC; slot 21:15 UTC.
        ok, reasons, _ = eligibility('daily', utc(2026, 11, 2, 21, 15), [session('2026-11-02')])
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_dst_start_march_edt_close_slot(self):
        # 16:00 EDT = 20:00 UTC; slot 20:15 UTC.
        ok, reasons, _ = eligibility('daily', utc(2026, 3, 9, 20, 15), [session('2026-03-09')])
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_weekend_has_no_session(self):
        # 2026-10-10 is a Saturday; the calendar has only the Friday session.
        ok, reasons, _ = eligibility('mechanical', utc(2026, 10, 10, 14, 5), [session('2026-10-09')])
        self.assertFalse(ok)
        self.assertIn('no_session_for_run_date', reasons)

    def test_holiday_absent_from_calendar_is_not_eligible(self):
        # Calendar provider simply omits the holiday row.
        ok, reasons, _ = eligibility('daily', utc(2026, 12, 25, 18, 15), [session('2026-12-24')])
        self.assertFalse(ok)
        self.assertIn('no_session_for_run_date', reasons)

    def test_missing_calendar_is_typed_coverage_gap_no_guess(self):
        for bad in (None, [], 'calendar', [dict(date='2026-10-07')]):
            ok, reasons, day = eligibility('mechanical', utc(2026, 10, 7, 14, 5), bad)
            self.assertFalse(ok)
            self.assertIn('schedule_calendar_missing', reasons)
            self.assertIsNone(day)

    def test_naive_now_is_rejected(self):
        ok, reasons, day = eligibility('mechanical', datetime(2026, 10, 7, 14, 5), [session('2026-10-07')])
        self.assertFalse(ok)
        self.assertIn('now_requires_timezone', reasons)
        self.assertIsNone(day)


class CronContractTests(TestCase):
    def test_cron_expressions_match_brief(self):
        self.assertEqual(MECHANICAL_CRON, '5 14-21 * * 1-5')
        self.assertEqual(DAILY_CRON, '15,45 17-22 * * 1-5')

    def test_fired_by_cron_matches_utc_expression(self):
        self.assertTrue(fired_by_cron('mechanical', utc(2026, 10, 7, 14, 5)))
        self.assertFalse(fired_by_cron('mechanical', utc(2026, 10, 7, 14, 6)))
        self.assertFalse(fired_by_cron('mechanical', utc(2026, 10, 7, 22, 5)))
        # Saturday 17:15 UTC: minute/hour inside window but weekday filtered.
        self.assertFalse(fired_by_cron('daily', utc(2026, 10, 10, 17, 15)))
        self.assertTrue(fired_by_cron('daily', utc(2026, 10, 7, 17, 15)))

    def test_cron_union_covers_dst_and_early_close_calendar_fixtures(self):
        # Every fixture session must have at least one mechanical :05 firing
        # inside the session and one daily firing within close+15..close+45.
        fixtures = [
            session('2026-03-09'),                          # DST start, EDT
            session('2026-07-15'),                          # mid-summer EDT
            session('2026-11-02'),                          # DST end, EST
            session('2026-11-27', close_hm='13:00'),        # early close
            session('2026-12-24'),                          # EST half-day-adjacent
        ]
        for row in fixtures:
            open_at = datetime.fromisoformat(row['open_at'])
            close_at = datetime.fromisoformat(row['close_at'])
            mechanical_fires = [
                minute for minute in (open_at + timedelta(minutes=n) for n in range(0, 7 * 60))
                if (lambda u: u.minute == 5 and 14 <= u.hour <= 21 and u.weekday() <= 4)(minute.astimezone(ZoneInfo('UTC')))
            ]
            self.assertTrue(any(open_at.astimezone(ZoneInfo('UTC')) <= f <= close_at.astimezone(ZoneInfo('UTC'))
                                for f in mechanical_fires),
                            'no mechanical cron firing inside ' + row['date'])
            daily_fires = [
                minute for minute in (close_at + timedelta(minutes=n) for n in range(0, 46))
                if (lambda u: u.minute in (15, 45) and 17 <= u.hour <= 22 and u.weekday() <= 4)(minute.astimezone(ZoneInfo('UTC')))
            ]
            self.assertTrue(any(close_at + timedelta(minutes=15) <= f <= close_at + timedelta(minutes=45)
                                for f in daily_fires),
                            'no daily cron firing in close+15..close+45 window on ' + row['date'])
