"""Exact-document research memory. Keys are work identities, not trade authority."""
from __future__ import annotations
import hashlib
import json
import re

_DOCUMENT_KEY = re.compile(r'rm1:[0-9a-f]{64}')


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('utf-8')


def _label(value) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > 256 or any(ord(c) < 32 for c in value)):
        raise ValueError('invalid_research_memory_label')
    return value


def document_key(*, issuer: str, representation: str, content: bytes,
                 rule_version: str, stage: str) -> str:
    if not isinstance(content, bytes) or not content:
        raise ValueError('complete_content_required')
    envelope = dict(version=1, issuer=_label(issuer), representation=_label(representation),
                    content_sha256=hashlib.sha256(content).hexdigest(),
                    rule_version=_label(rule_version), stage=_label(stage))
    return 'rm1:' + hashlib.sha256(_canonical(envelope)).hexdigest()


def bundle_key(*, issuer: str, document_keys: tuple[str, ...],
               rule_version: str, stage: str) -> str:
    if (not isinstance(document_keys, tuple) or not document_keys
            or any(not isinstance(k, str) or _DOCUMENT_KEY.fullmatch(k) is None
                   for k in document_keys)):
        raise ValueError('invalid_research_document_keys')
    envelope = dict(version=1, issuer=_label(issuer), documents=sorted(set(document_keys)),
                    rule_version=_label(rule_version), stage=_label(stage))
    return 'rb1:' + hashlib.sha256(_canonical(envelope)).hexdigest()


# This stream is an optimization only. Mandatory entry/review history has its
# own strict reader; cache damage must never authorize entry or claim success.
STREAM='private/research_memory.jsonl'
MAX_STREAM_BYTES=8_000_000
_KEY=re.compile(r'(?:rm1|rb1):[0-9a-f]{64}')
_TRANSIENT=frozenset({'source_fetch_timeout','source_http_forbidden','source_http_error',
                      'source_rate_limited','source_unavailable'})
_COMPLETE_FIELDS={'record_type','schema_version','key','stage','rule_version','capture_refs',
                  'result_ref','disposition','completed_at'}
_FAILURE_FIELDS={'record_type','schema_version','issuer','url','reason','failed_at'}


def _timestamp(value):
    import datetime as dt
    if not isinstance(value,str):raise ValueError('invalid_research_memory_time')
    stamp=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.utcoffset()!=dt.timedelta(0):raise ValueError('utc_research_memory_time_required')
    return stamp


def _valid_key(key):
    if not isinstance(key,str) or _KEY.fullmatch(key) is None:
        raise ValueError('invalid_research_memory_key')
    return key


def _validate(row):
    if not isinstance(row,dict) or type(row.get('schema_version')) is not int or row['schema_version']!=1:
        raise ValueError('invalid_research_memory_record')
    if row.get('record_type')=='complete':
        if set(row)!=_COMPLETE_FIELDS:raise ValueError('invalid_research_memory_record')
        _valid_key(row['key']);_label(row['stage']);_label(row['rule_version']);_timestamp(row['completed_at'])
        if (row['disposition'] not in {'document_processed','no_setup','rejected','qualified'}
                or not isinstance(row['capture_refs'],list) or not row['capture_refs']
                or len(row['capture_refs'])>32 or not isinstance(row['result_ref'],dict)):
            raise ValueError('invalid_research_memory_completion')
    elif row.get('record_type')=='failure':
        if set(row)!=_FAILURE_FIELDS or row['reason'] not in _TRANSIENT:raise ValueError('invalid_research_memory_failure')
        _label(row['issuer']);_url(row['url']);_timestamp(row['failed_at'])
    else:raise ValueError('invalid_research_memory_record')
    return row


def _url(value):
    from urllib.parse import urlsplit
    if not isinstance(value,str) or len(value)>4096:raise ValueError('invalid_research_memory_url')
    u=urlsplit(value)
    if u.scheme not in {'https','http'} or not u.hostname or u.username or u.password or u.fragment:
        raise ValueError('invalid_research_memory_url')
    return value


def _rows(root):
    import sqlite_ledger as storage
    storage.check_deadline()
    path=root/STREAM
    if path.exists() and path.stat().st_size>MAX_STREAM_BYTES:raise ValueError('research_memory_capacity')
    return [_validate(row) for row in storage.read_jsonl_stream_readonly(path)]


def complete(root, *, key: str, stage: str, rule_version: str, capture_refs: tuple[dict,...],
             result: dict, disposition: str, completed_at: str) -> dict:
    from pathlib import Path
    import entry_state
    import sqlite_ledger as storage
    import evidence_capture_store as captures
    root=Path(root)
    _valid_key(key);_label(stage);_label(rule_version);_timestamp(completed_at)
    if (not isinstance(capture_refs,tuple) or not capture_refs or len(capture_refs)>32
            or not isinstance(result,dict) or disposition not in {'document_processed','no_setup','rejected','qualified'}):
        raise ValueError('completed_research_required')
    for ref in capture_refs:captures.read_capture(root,ref)
    result_ref=captures.retain_result(root,result)
    row=dict(record_type='complete',schema_version=1,key=key,stage=stage,rule_version=rule_version,
             capture_refs=list(capture_refs),result_ref=result_ref,disposition=disposition,completed_at=completed_at)
    _validate(row)
    storage.check_deadline()
    with entry_state.lock(root,attempts=20 if storage._operation_deadline.get() is None else 1):
        for old in reversed(_rows(root)):
            if old['record_type']=='complete' and old['key']==key:
                same_work=all(old[k]==row[k] for k in ('stage','rule_version','result_ref','disposition'))
                age=(_timestamp(completed_at)-_timestamp(old['completed_at'])).total_seconds()
                if same_work and 0<=age<86400:
                    for ref in old['capture_refs']:captures.read_capture(root,ref)
                    captures.read_result(root,old['result_ref'])
                    return old
                if old['completed_at']==completed_at:
                    if old!=row:raise ValueError('research_memory_completion_conflict')
                    return old
        storage.append_jsonl(root/STREAM,row)
    # Exact readback after append; an unacknowledged write never becomes a
    # fabricated success. Callers may reuse a subsequently verified completion.
    if row not in _rows(root):raise OSError('research_memory_readback_failed')
    return row


def lookup(root, *, key: str, now: str, freshness_check) -> dict:
    from pathlib import Path
    import evidence_capture_store as captures
    root=Path(root)
    def answer(status,reason,record=None):return dict(status=status,reason=reason,record=record)
    try:
        _valid_key(key);clock=_timestamp(now)
        matches=[r for r in _rows(root) if r['record_type']=='complete' and r['key']==key]
        if not matches:return answer('miss','research_memory_miss')
        row=max(matches,key=lambda r:_timestamp(r['completed_at']))
        age=(clock-_timestamp(row['completed_at'])).total_seconds()
        if age<0 or age>=86400:return answer('miss','research_memory_expired')
        for ref in row['capture_refs']:captures.read_capture(root,ref)
        result=captures.read_result(root,row['result_ref'])
        if freshness_check(row,result) is not True:return answer('miss','research_memory_stale')
        return answer('hit','research_memory_hit',row)
    except Exception:
        return answer('unusable','research_memory_unusable')


def note_failure(root, *, issuer: str, url: str, reason: str, failed_at: str) -> None:
    from pathlib import Path
    import sqlite_ledger as storage
    row=_validate(dict(record_type='failure',schema_version=1,issuer=issuer,url=url,
                       reason=reason,failed_at=failed_at))
    storage.append_jsonl(Path(root)/STREAM,row)


def retry_allowed(root, *, issuer: str, url: str, reason: str, now: str) -> bool:
    from pathlib import Path
    try:
        _label(issuer);_url(url);clock=_timestamp(now)
        for row in _rows(Path(root)):
            if (row['record_type']=='failure' and (row['issuer'],row['url'],row['reason'])==(issuer,url,reason)
                    and 0<=(clock-_timestamp(row['failed_at'])).total_seconds()<1200):return False
        return True
    except Exception:
        # Optimization failure is no permanent retry/issuer ban. The caller
        # still owns the normal transport budget and typed cache diagnostic.
        return True

