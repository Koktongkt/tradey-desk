"""Bounded research context only; never a dossier-spending rule or ticker ban."""
from __future__ import annotations
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from urllib.parse import urlsplit
from extraction_contract import strict_json_loads

MAX_BYTES=2*1024*1024


def _parent(path):
    for p in path.parents:
        if p.is_symlink():raise ValueError('unsafe history directory')
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.parent.stat().st_uid!=os.getuid():raise ValueError('unowned history directory')
    path.parent.chmod(0o700)


def _safe_fd(path,flags,mode=0o600):
    fd=os.open(path,flags|os.O_NOFOLLOW,mode)
    st=os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_uid!=os.getuid():os.close(fd);raise ValueError('unsafe history file')
    return fd


def read_history(path:Path,*,now:dt.datetime)->dict:
    if now.tzinfo is None or now.utcoffset() is None:raise ValueError('aware clock')
    path=Path(path)
    if path.is_symlink():raise ValueError('unsafe history file')
    for p in path.parents:
        if p.is_symlink():raise ValueError('unsafe history directory')
    try:fd=_safe_fd(path,os.O_RDONLY)
    except FileNotFoundError:return {'version':1,'entries':[]}
    with os.fdopen(fd,'rb') as f:raw=f.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('history limit')
    try:data=strict_json_loads(raw.decode())
    except (ValueError,UnicodeError) as e:raise ValueError('malformed history') from e
    if not isinstance(data,dict) or data.get('version')!=1 or not isinstance(data.get('entries'),list):raise ValueError('history schema')
    cutoff=now.astimezone(dt.timezone.utc)-dt.timedelta(days=7);out={}
    for row in data['entries']:
        if not isinstance(row,dict) or not isinstance(row.get('url'),str) or not isinstance(row.get('last_seen'),str):raise ValueError('history row')
        try:seen=dt.datetime.fromisoformat(row['last_seen'].replace('Z','+00:00'))
        except ValueError:raise ValueError('history timestamp')
        if seen.tzinfo is None:raise ValueError('history timestamp')
        if cutoff<=seen<=now:out[row['url']]=row
    return {'version':1,'entries':sorted(out.values(),key=lambda r:r['last_seen'])[-1000:]}


def record_history(path:Path,entry:dict,*,now:dt.datetime)->None:
    path=Path(path);_parent(path)
    if not isinstance(entry,dict) or not isinstance(entry.get('url'),str):raise ValueError('history entry')
    parsed=urlsplit(entry['url'])
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or len(entry['url'])>4096:raise ValueError('history url')
    lock=_safe_fd(path.with_name(path.name+'.lock'),os.O_CREAT|os.O_RDWR)
    temp=None
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('history busy')
        data=read_history(path,now=now)
        row={k:entry[k] for k in ('url','symbol','event_date','catalyst') if isinstance(entry.get(k),str)}
        if any(len(v)>4096 for v in row.values()):raise ValueError('history field limit')
        row.update(last_seen=now.astimezone(dt.timezone.utc).isoformat(),identity=hashlib.sha256(entry['url'].encode()).hexdigest())
        data['entries']=[x for x in data['entries'] if x['url']!=row['url']]+[row]
        data['entries']=data['entries'][-1000:]
        raw=json.dumps(data,ensure_ascii=False).encode()
        if len(raw)>MAX_BYTES:raise ValueError('history limit')
        fd,temp=tempfile.mkstemp(prefix='.history-',dir=path.parent)
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.chmod(temp,0o600);os.replace(temp,path);temp=None
    finally:
        if temp:os.unlink(temp)
        os.close(lock)
