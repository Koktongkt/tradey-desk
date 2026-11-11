"""Private acquisition observations. No event identity, allowance or broker authority."""
from __future__ import annotations
import datetime as dt
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urljoin

from earnings_identity_evidence import (identity_source_bytes, validate_identity_capture,
    retain_identity_captures, MAX_IDENTITY_CAPTURE_BYTES, _decode)
from opportunity_identity import _canonical, _locator, _Cover, _open_root, _private_child, _publish_capture

_KEYS=frozenset({'record_type','schema_version','observed_at','lead_id','symbol','issuer_cik',
                 'status','evidence_status','capture_refs','reason'})
_REF=re.compile(r'private/opportunity_evidence/[0-9a-f]{64}\.json')
_HINT=re.compile(r'\b(?:acquisition|merger|acquir(?:e[sd]?|ing)|buyout|tender offer)\b',re.I)
_MAX_LEAD_BYTES=32_768


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.text=[]; self.current=None
    def handle_starttag(self,tag,attrs):
        if tag=='a': self.current=[dict(attrs).get('href',''),[]]
    def handle_data(self,data):
        self.text.append(data)
        if self.current is not None:self.current[1].append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.current is not None:
            self.links.append((self.current[0],' '.join(self.current[1])));self.current=None


def literal_acquisition_links(raw: bytes, base_url: str) -> tuple[str,...]:
    """Literal investigation links only; labels never prove transaction continuity."""
    origin=_locator(base_url)
    if origin is None or not isinstance(raw,bytes):return ()
    try:
        parser=_Links();parser.feed(raw.decode('utf-8',errors='strict'));parser.close()
    except (UnicodeError,ValueError):return ()
    result=[]
    for href,label in parser.links:
        if not _HINT.search(label) and 'letter agreement' not in label.casefold():continue
        url=urljoin(base_url,href);loc=_locator(url)
        if loc and loc[0]==origin[0] and url!=base_url and url not in result:
            result.append(url)
            if len(result)==32:break
    return tuple(result)


def acquisition_hint(selected: dict, pages: list[dict], captures: tuple) -> bool:
    """Conservative routing hint, never a legal interpretation or permission."""
    if isinstance(selected,dict):
        for key in ('catalyst','event_family','family','event_type','title'):
            value=selected.get(key)
            if isinstance(value,str) and _HINT.search(value[:4096]):return True
    for page in pages if isinstance(pages,list) else ():
        if not isinstance(page,dict):continue
        if isinstance(page.get('title'),str) and _HINT.search(page['title'][:4096]):return True
        text=page.get('text')
        if isinstance(text,str) and 'agreement and plan of merger' in text.casefold():return True
    for capture in captures if isinstance(captures,tuple) else ():
        raw=identity_source_bytes(capture)
        if raw is None:continue
        try:text=raw.decode('utf-8').casefold()
        except UnicodeError:continue
        if ('agreement and plan of merger' in text or
                ('completion of acquisition or disposition of assets' in text and
                 any(word in text for word in ('merger','acquisition','acquired')))):
            return True
    return False


def is_research_only_input(value: object) -> bool:
    """Explicit unsupported acquisition/lead markers refuse BEFORE legacy fallback."""
    if isinstance(value,dict):
        if acquisition_hint(value,[],()):return True
        if any(key in value for key in ('lead_id','capture_refs','agreement')):return True
        if value.get('record_type')=='acquisition_research_lead' or value.get('status')=='research_only':return True
        if value.get('reason')=='explicit_binding_required':return True
        if value.get('family')=='acquisition' or value.get('event_family')=='acquisition':return True
        version=value.get('version')
        if type(version) is int and version>=3:return True
        eid=value.get('event_id')
        if isinstance(eid,str) and eid.startswith('oe3:'):return True
        nested=value.get('opportunity_identity')
        return isinstance(nested,dict) and is_research_only_input(nested)
    if getattr(value,'family',None)=='acquisition':return True
    version=getattr(value,'version',None)
    return type(version) is int and version>=3


def _directory(parent,name):
    fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
    info=os.fstat(fd)
    if info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700:
        os.close(fd);raise OSError('unsafe_research_directory')
    return fd


def _read_file(directory,name,limit):
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    try:
        before=os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid()
                or stat.S_IMODE(before.st_mode)!=0o600 or before.st_nlink!=1 or not 0<before.st_size<=limit):
            raise OSError('unsafe_research_file')
        with os.fdopen(fd,'rb',closefd=False) as handle:data=handle.read(limit+1)
        after=os.fstat(fd)
        stable=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode,s.st_uid,s.st_nlink)
        if stable(before)!=stable(after) or len(data)!=before.st_size:raise OSError('research_file_changed')
        return data
    finally:os.close(fd)


def _issuer(symbol,captures):
    """Only context-bound primary cover facts; directory/hint alone is insufficient."""
    found=set()
    for cap in captures:
        cover=_Cover();cover.feed(identity_source_bytes(cap).decode('utf-8'));cover.close()
        for context,facts in cover.facts.items():
            symbols=facts.get('dei:TradingSymbol',[]);ciks=facts.get('dei:EntityCentralIndexKey',[])
            if set(symbols)=={symbol} and len(set(ciks))==1:
                cik=ciks[0]
                if (isinstance(cik,str) and re.fullmatch(r'[0-9]{10}',cik) and int(cik)>0
                        and _locator(cap.url)[0]==cik
                        and cover.contexts.get(context,{}).get('xbrli:identifier')==[cik]):found.add(cik)
    return next(iter(found)) if len(found)==1 else None


def _validate(record):
    if not isinstance(record,dict) or set(record)!=_KEYS:raise ValueError('invalid_research_lead')
    if (record['record_type']!='acquisition_research_lead' or type(record['schema_version']) is not int
            or record['schema_version']!=1 or record['status']!='research_only'
            or record['reason']!='explicit_binding_required'):raise ValueError('invalid_research_lead')
    symbol=record['symbol'];stamp=record['observed_at'];cik=record['issuer_cik']
    if not isinstance(symbol,str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,9}',symbol):raise ValueError('invalid_lead_symbol')
    if not isinstance(stamp,str) or len(stamp)>64:raise ValueError('invalid_lead_time')
    when=dt.datetime.fromisoformat(stamp)
    if when.utcoffset()!=dt.timedelta(0):raise ValueError('invalid_lead_time')
    if cik is not None and (not isinstance(cik,str) or not re.fullmatch(r'[0-9]{10}',cik) or int(cik)==0):raise ValueError('invalid_lead_cik')
    refs=record['capture_refs'];status=record['evidence_status']
    if (not isinstance(refs,list) or len(refs)>32 or any(not isinstance(r,str) or not _REF.fullmatch(r) for r in refs)
            or refs!=sorted(set(refs))):raise ValueError('invalid_lead_refs')
    if status not in ('retained','partial','unavailable') or (bool(refs)==(status=='unavailable')):raise ValueError('invalid_lead_evidence')
    identity=record['lead_id']
    expected='al1:'+sha256(_canonical({k:v for k,v in record.items() if k!='lead_id'})).hexdigest()
    if not isinstance(identity,str) or identity!=expected:raise ValueError('invalid_lead_digest')
    if len(_canonical(record))>_MAX_LEAD_BYTES:raise ValueError('lead_capacity')
    return record


def publish_lead(root:Path,*,symbol:str,captures:tuple,evidence_status:str,observed_at:str)->dict:
    if not isinstance(symbol,str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,9}',symbol):raise ValueError('invalid_lead_symbol')
    if (not isinstance(captures,tuple) or len(captures)>32
            or not all(validate_identity_capture(c) for c in captures)):raise ValueError('trusted_identity_capture_required')
    record={'record_type':'acquisition_research_lead','schema_version':1,'observed_at':observed_at,
        'symbol':symbol,'issuer_cik':_issuer(symbol,captures),'status':'research_only',
        'evidence_status':evidence_status,'capture_refs':sorted({c.retained_ref for c in captures}),
        'reason':'explicit_binding_required'}
    record['lead_id']='al1:'+sha256(_canonical(record)).hexdigest();_validate(record)
    if captures:retain_identity_captures(root,captures)
    root_fd=_open_root(root);private=leads=None
    try:
        private=_private_child(root_fd,'private');leads=_private_child(private,'acquisition_research')
        _publish_capture(leads,record['lead_id'][4:]+'.json',_canonical(record),max_bytes=_MAX_LEAD_BYTES)
    finally:
        for fd in (leads,private,root_fd):
            if fd is not None:os.close(fd)
    return read_lead(root,record['lead_id'])


def read_lead(root:Path,lead_id:str)->dict:
    if not isinstance(lead_id,str) or not re.fullmatch(r'al1:[0-9a-f]{64}',lead_id):raise ValueError('invalid_lead_id')
    root_fd=_open_root(root);private=leads=evidence=None
    try:
        private=_directory(root_fd,'private');leads=_directory(private,'acquisition_research')
        raw=_read_file(leads,lead_id[4:]+'.json',_MAX_LEAD_BYTES)
        record=json.loads(raw);_validate(record)
        if record['lead_id']!=lead_id or _canonical(record)!=raw:raise ValueError('lead_digest_mismatch')
        if record['capture_refs']:
            evidence=_directory(private,'opportunity_evidence')
            for ref in record['capture_refs']:
                capture=_read_file(evidence,Path(ref).name,MAX_IDENTITY_CAPTURE_BYTES)
                if sha256(capture).hexdigest()+'.json'!=Path(ref).name:raise ValueError('capture_digest_mismatch')
                _decode(capture)
        return record
    finally:
        for fd in (evidence,leads,private,root_fd):
            if fd is not None:os.close(fd)
