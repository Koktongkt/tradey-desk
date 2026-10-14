"""Monitoring-only notification decisions, independent of outbox receipts.

`prepared` is a durable emission reservation, not delivery. A crash after that
reservation is ambiguous and is never automatically replayed. `emitted` means
handed to the local transport (cron stdout can still be lost). Raised transports
are `failed` and may retry. Current conditions are rechecked from the newest
committed report, never from the historical pending outbox.
"""
import hashlib
import json

from .store import _connection, dumps, pending_alerts
from .reports import _amount, _symbol


def _conditions(report):
    from decimal import Decimal
    from .reports import _enum, _rows
    report_coverage = report.get('coverage')
    report_coverage = report_coverage if isinstance(report_coverage, dict) else {}
    sources = report_coverage.get('sources')
    # Overall report status includes thesis/accounting; only protection-source
    # evidence gates protection decisions. Older per-position reports omit sources.
    sources_verified = 'sources' not in report_coverage or (isinstance(sources, dict) and all(
        sources.get(key) == 'complete' for key in ('orders', 'references')) and
        ('positions' not in sources or sources.get('positions') == 'complete'))
    protection_observed = sources_verified
    position_rows = _rows(report.get('positions'))
    for position in position_rows:
        quantity = _amount(position.get('remaining_quantity'))
        coverage = _amount(position.get('protection_coverage_quantity'))
        ownership = _enum(position.get('ownership_status'), {'verified', 'discrepancy', 'unknown'})
        # A zero in the execution record is not a corroborated broker closure.
        closed = sources_verified and ownership == 'verified' and quantity is not None and Decimal(quantity) == 0
        quantity_unknown = quantity is None or Decimal(quantity) < 0
        status = _enum(position.get('protection_status'), {'covered', 'not_required', 'partial', 'unprotected'})
        covered = (sources_verified and ownership == 'verified' and status == 'covered' and quantity is not None and not quantity_unknown and coverage is not None
                   and Decimal(coverage) >= Decimal(quantity))
        protection_observed = protection_observed and ownership == 'verified' and not quantity_unknown and (
            closed or (status in ('covered', 'partial', 'unprotected') and coverage is not None))
        active = not closed and not covered
        identity = position.get('position_id')
        if not isinstance(identity, str) or not identity:
            identity = 'unidentified-position'
        symbol = _symbol(position.get('symbol'))
        yield dict(condition=identity + ':protection', signature=dumps([sources_verified, ownership, status, quantity, coverage]),
                   active=active, symbol=symbol, kind='protection',
                   text='Protection is missing or insufficient.' if status in ('unprotected', 'partial') and not quantity_unknown
                        else 'Protection could not be verified; review the current position.')
        reasons = position.get('reasons')
        reasons = reasons if isinstance(reasons, list) else []
        quantity_status = _enum(position.get('quantity_status'), {'consistent', 'discrepancy', 'concurrent_quantity_change'})
        mismatch = ownership == 'discrepancy' or quantity_status in ('discrepancy', 'concurrent_quantity_change') or any(
            reason in ('unexpected_exit', 'protection_quantity_mismatch') for reason in reasons if isinstance(reason, str))
        yield dict(condition=identity + ':quantity', signature=dumps([mismatch, quantity_status, quantity, coverage]),
                   active=not closed and mismatch, symbol=symbol, kind='quantity',
                   text='Current position quantity does not match the protection or execution record.')
        horizon = _enum(position.get('horizon_status'), {'active', 'horizon_expired'})
        yield dict(condition=identity + ':horizon', signature=dumps([horizon, closed]),
                   active=not closed and not quantity_unknown and horizon == 'horizon_expired', symbol=symbol, kind='horizon',
                   text='The planned exit horizon is overdue for an open position.')
    if protection_observed:
        yield dict(condition='runtime:protection-check', signature='observed', active=False,
                   symbol=None, kind='coverage', text='Protection observation resumed.')
    elif not position_rows:
        yield dict(condition='runtime:protection-check', signature='protection_sources_unverified', active=True,
                   symbol=None, kind='coverage',
                   text='Current position protection could not be checked; human review is needed.')
    positions = {p.get('position_id'): p for p in _rows(report.get('positions')) if isinstance(p.get('position_id'), str)}
    for thesis in _rows(report.get('thesis')):
        identity = thesis.get('position_id')
        if not isinstance(identity, str) or identity not in positions:
            continue
        quantity = _amount(positions[identity].get('remaining_quantity'))
        if quantity is None or Decimal(quantity) <= 0:
            continue
        for event in _rows(thesis.get('events')):
            if (event.get('effect') not in ('weakens', 'potential-break')
                    or (event.get('effect') == 'weakens' and (event.get('severity') not in ('medium', 'high', 'critical')
                        or event.get('confidence') not in ('medium', 'high')))
                    or event.get('primary') is not True or event.get('kind') != 'fundamental'
                    or not isinstance(event.get('fingerprint'), str) or not event['fingerprint']
                    or not isinstance(event.get('criterion_id'), str) or not event['criterion_id']
                    or not thesis.get('baseline_version') or event.get('baseline_version') != thesis['baseline_version']):
                continue
            yield dict(condition=dumps([identity, thesis['baseline_version'], event['fingerprint'], event['criterion_id']]),
                       signature=dumps([event['effect'], event['severity'], event['confidence']]), active=True,
                       symbol=_symbol(positions[identity].get('symbol')), kind='thesis',
                       text='Verified material evidence weakens the thesis; reassessment is needed.' if event['effect'] == 'weakens'
                            else 'Verified evidence indicates a potential thesis break; reassessment is needed.')


def _claim(conn, report, item):
    from .types import aware_timestamp
    identity = item['condition']
    key = hashlib.sha256(dumps([report.get('notification_id', report['run_id']), identity, item['signature']]).encode()).hexdigest()
    existing = conn.execute('SELECT state FROM notification_emissions WHERE key=?', (key,)).fetchone()
    if existing and existing[0] != 'failed':
        return None
    prior = conn.execute('SELECT signature,state,at FROM notification_emissions WHERE condition_key=? ORDER BY rowid DESC LIMIT 1',
                         (identity,)).fetchone()
    last = conn.execute("SELECT at FROM notification_emissions WHERE condition_key=? AND state IN ('prepared','emitted') ORDER BY rowid DESC LIMIT 1",
                        (identity,)).fetchone()
    at = report['coverage']['captured_at']
    if prior and aware_timestamp(at) < aware_timestamp(prior[2]):
        return None  # A reporting retry cannot recover a newer failed check.
    due = not last or (aware_timestamp(at) - aware_timestamp(last[0])).total_seconds() >= 86400
    notify = item['active'] and (not prior or prior[0] != item['signature'] or prior[1] == 'failed' or due or bool(existing))
    payload = dict(key=key, kind=item['kind'], symbol=item['symbol'], text=item['text'])
    state = 'prepared' if notify else 'suppressed'
    conn.execute('INSERT OR REPLACE INTO notification_emissions VALUES (?,?,?,?,?,?,?)',
                 (key, report['run_id'], identity, item['signature'], state, at, dumps(payload)))
    return payload if notify else None


def _daily_claim(conn, report):
    from .reports import daily_notification
    key = 'daily:' + report['session_date']
    existing = conn.execute('SELECT state FROM notification_emissions WHERE key=?', (key,)).fetchone()
    if existing and existing[0] != 'failed':
        return None
    payload = dict(key=key, kind='daily', text=daily_notification(report), symbol=None)
    conn.execute('INSERT OR REPLACE INTO notification_emissions VALUES (?,?,?,?,?,?,?)',
                 (key, report['run_id'], 'daily', report['session_date'], 'prepared', report['coverage']['captured_at'], dumps(payload)))
    return payload


def emit_notifications(db, transport, daily_run_id=None, reports_installed=True):
    if transport is None:
        return dict(delivered=0, emitted=0, pending=len(pending_alerts(db)), keys=[])
    with _connection(db, True) as conn:
        row = conn.execute('SELECT payload FROM runs ORDER BY captured_at DESC,rowid DESC LIMIT 1').fetchone()
        if not row:
            return dict(delivered=0, emitted=0, pending=0, keys=[])
        report = json.loads(row[0])
        messages: list[dict] = [message for item in _conditions(report) if (message := _claim(conn, report, item))]
        daily = report if report.get('mode') == 'daily' else None
        if daily_run_id is not None:
            row = conn.execute("SELECT payload FROM runs WHERE run_id=? AND mode='daily'", (daily_run_id,)).fetchone()
            daily = json.loads(row[0]) if row else None
        if reports_installed and daily is not None and (message := _daily_claim(conn, daily)):
            messages.append(message)
    return _send(db, transport, messages)


def emit_check_failure(db, transport, at, reason):
    """Report a current protection-check failure without inventing a run."""
    from .store import notification_policy_enabled
    from .reports import _enum
    from .types import aware_timestamp
    if transport is None or not notification_policy_enabled(db):
        return dict(delivered=0, emitted=0, pending=0, keys=[])
    at = aware_timestamp(at).isoformat()
    reason = _enum(reason, {'broker_adapter_failed', 'operational_read_failed', 'outer_deadline_exceeded',
                            'observation_commit_failed'}, 'monitoring_failed')
    stamp = dict(run_id=None, notification_id='failure:' + at, coverage=dict(captured_at=at))
    item = dict(condition='runtime:protection-check', signature=reason, active=True, symbol=None,
                kind='coverage', text='Current position protection could not be checked; human review is needed.')
    with _connection(db, True) as conn:
        message = _claim(conn, stamp, item)
    return _send(db, transport, [message] if message else [])


def _send(db, transport, messages):
    from .store import validated_receipt
    emitted = failed = delivered = 0
    for message in messages:
        text = (message['text'] if message['kind'] == 'daily' else
                'Watchdog: ' + (message['symbol'] + ' — ' if message['symbol'] else '') + message['text']
                + ' Human review needed; no trading action taken.')
        state = 'emitted'
        receipt = None
        try:
            received = transport(message, text)
            emitted += 1
            try:
                receipt = validated_receipt(received)
            except (ValueError, TypeError):
                pass
        except Exception:
            state = 'failed'
            failed += 1
        with _connection(db, True) as conn:
            conn.execute('UPDATE notification_emissions SET state=? WHERE key=?', (state, message['key']))
            if receipt is not None:
                conn.execute('INSERT INTO notification_receipts VALUES (?,?)', (message['key'], dumps(receipt)))
                delivered += 1
    result = dict(delivered=delivered, emitted=emitted, pending=len(pending_alerts(db)), keys=[])
    if failed:
        result['reasons'] = ['notification_transport_failed']
    return result
