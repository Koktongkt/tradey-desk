"""Pure schedule eligibility for the monitoring watchdog.

The proposed cron registrations are the brief's exact UTC expressions; this
module filters every firing against the actual Alpaca session calendar rows
(normalized by watchdog.broker.normalize_session), so scheduler firings outside
eligibility are silent no-ops. A missing or invalid calendar is a typed
coverage gap: market-session eligibility is never guessed.

Mechanical: UTC '5 14-21 * * 1-5', only inside a live session.
Daily:      UTC '15,45 17-22 * * 1-5', only in the close+15..close+45 window
            (first slot at close+15 minutes). Early closes and DST shifts are
            handled by comparing aware timestamps in America/New_York.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
UTC = ZoneInfo('UTC')

MECHANICAL_CRON = '5 14-21 * * 1-5'
DAILY_CRON = '15,45 17-22 * * 1-5'

CRON_MINUTES = {'mechanical': (5,), 'daily': (15, 45)}
CRON_HOURS = {'mechanical': range(14, 22), 'daily': range(17, 23)}


def fired_by_cron(mode: str, now: datetime) -> bool:
    """Does the proposed UTC cron expression fire at this aware instant?"""
    if mode not in CRON_MINUTES:
        raise ValueError('unknown_watchdog_mode')
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now requires timezone')
    utc_now = now.astimezone(UTC)
    return (utc_now.minute in CRON_MINUTES[mode]
            and utc_now.hour in CRON_HOURS[mode]
            and utc_now.weekday() <= 4)


def _session_for(sessions, day):
    for row in sessions if isinstance(sessions, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get('date'), str):
            continue
        if row['date'] == day:
            return row
    return None


def eligibility(mode: str, now: datetime, sessions) -> tuple[bool, list[str], str | None]:
    """Typed eligibility: (eligible, reasons, session_date).

    reasons is empty only for an eligible slot. Missing/invalid calendar rows
    produce 'schedule_calendar_missing'; dates without a session produce
    'no_session_for_run_date'; in-session/cron mismatches are typed separately.
    """
    if mode not in CRON_MINUTES:
        raise ValueError('unknown_watchdog_mode')
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return False, ['now_requires_timezone'], None
    try:
        local = now.astimezone(NY)
    except (ValueError, OSError):
        return False, ['schedule_calendar_missing'], None
    day = local.date().isoformat()
    row = _session_for(sessions, day)
    if row is None:
        if sessions is None or (isinstance(sessions, list) and not sessions) or not isinstance(sessions, list):
            return False, ['schedule_calendar_missing'], None
        return False, ['no_session_for_run_date'], None
    try:
        open_at = datetime.fromisoformat(row['open_at'])
        close_at = datetime.fromisoformat(row['close_at'])
        if open_at.tzinfo is None or close_at.tzinfo is None or not open_at < close_at:
            raise ValueError('invalid session row')
    except (KeyError, TypeError, ValueError):
        return False, ['schedule_calendar_missing'], None
    if mode == 'mechanical':
        # Session membership dominates: a :05 firing outside the live session
        # is an out-of-session no-op, and an in-session minute outside the
        # cron grid is simply not a scheduled slot.
        if open_at > now or now >= close_at:
            return False, ['outside_session'], None
        if not fired_by_cron(mode, now):
            return False, ['not_scheduled_slot'], None
        return True, [], day
    if not fired_by_cron(mode, now):
        return False, ['not_scheduled_slot'], None
    window_start = close_at + timedelta(minutes=15)
    window_end = close_at + timedelta(minutes=45)
    if window_start <= now <= window_end:
        return True, [], day
    return False, ['not_scheduled_slot'], None


def eligible(mode: str, now: datetime, sessions) -> bool:
    """Session/cron eligibility gate; see eligibility for typed reasons."""
    ok, _reasons, _day = eligibility(mode, now, sessions)
    return ok
