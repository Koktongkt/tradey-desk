"""Bounded auxiliary history/archive I/O, isolated behind discovery's guardian."""
from __future__ import annotations
import datetime as dt
import json
import math
import os
from pathlib import Path
import sys
from time import monotonic
import uuid
from discovery_history import read_history,record_history,_parent
from discovery_process import run_process
from extraction_contract import strict_json_loads

MAX_STATE_BYTES=4*1024*1024


def worker_command():
    source=Path(__file__).resolve()
    return [sys.executable,'-I','-c',f'import sys,runpy;sys.path.insert(0,{str(source.parent)!r});runpy.run_path({str(source)!r},run_name="__main__")']


def _save(directory,row):
    path=Path(directory)/(uuid.uuid4().hex+'.json');_parent(path)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(row,f,ensure_ascii=False,allow_nan=False)


def execute(request):
    if not isinstance(request,dict) or request.get('version')!=1 or request.get('action') not in ('read','persist'):raise ValueError('state request')
    deadline=request.get('deadline')
    if type(deadline) not in (int,float) or not math.isfinite(deadline):raise ValueError('state deadline')
    if monotonic()>=deadline:return {'status':'error','reason':'timeout'}
    now=dt.datetime.fromisoformat(request['now']);history=Path(request['history_path']);directory=Path(request['artifact_dir'])
    if now.tzinfo is None or not history.is_absolute() or not directory.is_absolute() or history.name!='history.json' or history.parent!=directory.parent:raise ValueError('state paths')
    if request['action']=='read':
        data=read_history(history,now=now)
        # Selector needs compact context, not the entire index or URL list.
        recent=[{k:r[k] for k in ('symbol','event_date','catalyst','last_seen') if k in r} for r in data['entries'][-30:]]
        return {'status':'ok','history':{'version':1,'entries':recent}}
    candidates=request.get('candidates');capture=request.get('capture')
    if not isinstance(candidates,list) or len(candidates)>5 or not isinstance(capture,dict):raise ValueError('state payload')
    result={'status':'ok','history_status':'unchanged','artifact_status':'unavailable'}
    for c in candidates:
        if monotonic()>=deadline:return {'status':'error','reason':'timeout'}
        try:
            record_history(history,{'url':c['urls'][0],'symbol':c['symbol'],'event_date':c['event_date'],'catalyst':c['catalyst']},now=now)
            if result['history_status']!='unavailable':result['history_status']='updated'
        except (ValueError,OSError,KeyError,IndexError,TypeError):result['history_status']='unavailable'
    if monotonic()>=deadline:return {'status':'error','reason':'timeout'}
    try:_save(directory,capture);result['artifact_status']='persisted'
    except (ValueError,OSError):pass
    if monotonic()>=deadline:return {'status':'error','reason':'timeout'}
    return result


def request_state(action,*,history_path:Path,artifact_dir:Path,now:dt.datetime,deadline:float,candidates=None,capture=None):
    if monotonic()>=deadline:return {'status':'error','reason':'timeout'}
    request={'version':1,'action':action,'history_path':str(Path(history_path).absolute()),'artifact_dir':str(Path(artifact_dir).absolute()),'now':now.isoformat(),'deadline':deadline}
    if action=='persist':request.update(candidates=candidates or [],capture=capture or {})
    try:body=json.dumps(request,ensure_ascii=False,allow_nan=False).encode()
    except (ValueError,TypeError,UnicodeError):return {'status':'error','reason':'state_unavailable'}
    if len(body)>MAX_STATE_BYTES:return {'status':'error','reason':'input_limit'}
    try:result=run_process(worker_command(),body,deadline=deadline,cwd=Path(__file__).resolve().parent,max_input_bytes=MAX_STATE_BYTES)
    except OSError:return {'status':'error','reason':'state_unavailable'}
    except Exception:return {'status':'error','reason':'containment_unconfirmed'}
    if result.returncode:
        try:reason=strict_json_loads(result.stdout).get('reason')
        except (ValueError,TypeError,AttributeError):reason=None
        return {'status':'error','reason':'containment_unconfirmed' if reason=='containment_unconfirmed' else 'timeout' if result.returncode==124 else 'state_unavailable'}
    try:row=strict_json_loads(result.stdout)
    except (ValueError,TypeError,UnicodeError):return {'status':'error','reason':'state_unavailable'}
    if monotonic()>=deadline:return {'status':'error','reason':'timeout'}
    return row if isinstance(row,dict) and row.get('status') in ('ok','error') else {'status':'error','reason':'state_unavailable'}


def main():
    try:
        raw=sys.stdin.buffer.read(MAX_STATE_BYTES+1)
        if len(raw)>MAX_STATE_BYTES:raise ValueError('state size')
        row=execute(strict_json_loads(raw.decode()))
    except Exception:row={'status':'error','reason':'state_unavailable'}
    print(json.dumps(row,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
