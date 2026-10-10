"""Forward-only entry deadlines. Protective GTC duration is never changed.

Cancellation activation is deliberately unavailable: Alpaca bracket cancellation
cascades, and no conditional zero-fill cancellation guarantee has been verified.
"""
import datetime as dt
import re
from zoneinfo import ZoneInfo
import managed_reconciliation as m

ET = ZoneInfo('America/New_York')
POLICY = 'new_intents_session_close_v1'
# This is a code capability, not a configuration permission the model can grant.
SAFE_PARENT_CANCEL_VERIFIED = False


def sessions(rows):
    m.require(isinstance(rows,list) and len(rows)>=2,'entry_calendar_unavailable')
    result=[]
    for row in rows:
        m.require(isinstance(row,dict),'entry_calendar_invalid')
        date=str(row.get('date') or '')
        m.require(re.fullmatch(r'\d{4}-\d{2}-\d{2}',date) is not None,'entry_calendar_invalid')
        bounds=[]
        for key in ('open','close'):
            raw=row.get(key)
            m.require(isinstance(raw,str),'entry_calendar_invalid')
            if re.fullmatch(r'\d{2}:\d{2}(:\d{2})?',raw):
                value=dt.datetime.fromisoformat(date+'T'+raw).replace(tzinfo=ET)
            else:
                value=m.timestamp(raw)
                m.require(value.astimezone(ET).date().isoformat()==date,'entry_calendar_invalid')
            bounds.append(value.astimezone(dt.timezone.utc))
        m.require(bounds[0]<bounds[1],'entry_calendar_invalid')
        result.append((date,*bounds))
    m.require([r[0] for r in result]==sorted(set(r[0] for r in result)),'entry_calendar_invalid')
    return result


def metadata(plan, rows, placement_at):
    parsed=m.timestamp(placement_at).astimezone(dt.timezone.utc)
    calendar=sessions(rows)
    found=[i for i,row in enumerate(calendar) if row[1]<=parsed<row[2]]
    m.require(len(found)==1,'entry_placement_outside_session')
    index=found[0]
    m.require(index+1<len(calendar),'entry_calendar_unavailable')
    count=plan.get('holding_sessions')
    m.require(type(count) is int and 1<=count<=30,'entry_expiry_invalid')
    rubric='short_1_5' if count<=5 else 'swing_6_30'
    m.require(plan.get('assigned_rubric')==rubric,'entry_expiry_invalid')
    deadline=calendar[index+(count>5)]
    return {'version':1,'policy':POLICY,'placement_at':parsed.isoformat().replace('+00:00','Z'),
            'placement_session':calendar[index][0],'rubric':rubric,
            'deadline_session':deadline[0],'expires_at':deadline[2].isoformat().replace('+00:00','Z')}


def validate_metadata(value,plan,rows):
    m.require(isinstance(value,dict),'entry_expiry_invalid')
    expected=metadata(plan,rows,value.get('placement_at'))
    m.require(value==expected,'entry_expiry_invalid')
    return expected


def process(root,cfg,broker,*,now=None):
    """Run ahead of candidate skips, without retrofitting any legacy intent.

    Observation-only until the broker guarantees zero-fill-conditional parent
    cancellation cannot remove protection during a fill race.
    """
    import entry_state
    from durable_jsonl import read_jsonl
    from pathlib import Path
    root=Path(root)
    if cfg.get('entry_expiry_policy') != POLICY:
        return []
    kill=Path(str(cfg.get('kill_switch_path','KILL_SWITCH')))
    if not kill.is_absolute():kill=root/kill
    if cfg.get('enabled') is not True or cfg.get('broker_mode') != 'paper' or kill.exists():
        return []
    with entry_state.lock(root):
        ledger=read_jsonl(root/'order_ledger.jsonl',strict=True)
        latest={r.get('client_order_id'):r.get('status') for r in ledger}
        current=now or dt.datetime.now(dt.timezone.utc)
        reasons=[]
        for intent in read_jsonl(root/'private/order_intents.jsonl',strict=True):
            plan=intent.get('plan') or {}
            value=plan.get('entry_expiry')
            if value is None:continue  # Legacy: never assign or infer deadlines.
            m.require(isinstance(value,dict) and value.get('version')==1 and value.get('policy')==POLICY,'entry_expiry_invalid')
            deadline=m.timestamp(value.get('expires_at'))
            if latest.get(intent.get('client_order_id')) not in m.PENDING_ENTRY | {'proposed','pending_cancel'}:
                continue
            if current<=deadline:continue
            if not SAFE_PARENT_CANCEL_VERIFIED:
                reasons.append('entry_cancel_capability_unverified')
                continue
            # There is deliberately no production activation path at present.
            # An independently reviewed conditional-cancel primitive is required.
            raise RuntimeError('entry_cancel_capability_unverified')
        return sorted(set(reasons))
