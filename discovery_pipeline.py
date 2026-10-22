"""Opt-in discovery composition; no operational persistence or execution authority."""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
from time import monotonic
import uuid
from discovery_collection import make_queries
from discovery_process import run_collection
from discovery_selection import records,selector_prompt,admit_selection
from discovery_history import read_history,record_history,_parent


class DiscoveryFailure(RuntimeError):
    def __init__(self,reason):self.reason=reason;super().__init__(reason)


def run_selector(command,*,input:bytes,deadline:float,cwd:Path):
    from discovery_process import run_process
    try:
        if command[command.index('-t')+1]!='bot_room' or command[command.index('--max-turns')+1]!='1':raise ValueError('tool-free command required')
    except (ValueError,IndexError):raise ValueError('tool-free command required')
    return run_process(command,input,deadline=deadline,cwd=cwd,max_input_bytes=65536)


def _save(directory:Path,row:dict):
    path=Path(directory)/(uuid.uuid4().hex+'.json');_parent(path)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(row,f,ensure_ascii=False,allow_nan=False)


def discover(cfg:dict,*,now:dt.datetime,deadline:float,history_path:Path,artifact_dir:Path,command_factory,selector_runner=None):
    if now.tzinfo is None or now.utcoffset() is None:raise ValueError('aware clock required')
    audit={'reason':'selector_unavailable','raw_candidate_count':0,'parsed_candidate_count':0,'valid_url_count':0,'stale_event_date_rejected':0}
    capture={'version':1,'as_of':now.isoformat(),'requests':[],'collection':None,'audit':audit}
    def finish(candidates):
        capture['audit']=audit
        try:_save(artifact_dir,capture);audit['artifact_status']='persisted'
        except (OSError,ValueError):audit['artifact_status']='unavailable'
        return candidates,audit
    try:
        if monotonic()>=deadline:raise DiscoveryFailure('collection_timeout')
        requests=make_queries(cfg,now=now);capture['requests']=requests
        collection=run_collection(requests,deadline=min(deadline,monotonic()+60),cwd=Path(__file__).resolve().parent)
        capture['collection']=collection
        if not isinstance(collection,dict) or collection.get('status')=='error':
            reason=collection.get('reason') if isinstance(collection,dict) else None
            raise DiscoveryFailure('collection_timeout' if reason=='timeout' else 'collection_unavailable')
        try:source=records(collection)
        except (ValueError,TypeError):raise DiscoveryFailure('collection_schema_rejected')
        collection['as_of']=now.isoformat();collection['event_cutoff']=requests[0]['event_cutoff']
        if not any(isinstance(l,dict) and l.get('status')=='ok' for l in collection['lanes']):raise DiscoveryFailure('collection_unavailable')
        if not source:
            if collection.get('coverage_complete') is not True:raise DiscoveryFailure('collection_incomplete')
            audit.update(reason='no_discovered_candidate',coverage_complete=True,row_outcomes=[],dispositions={});return finish([])
        try:history=read_history(history_path,now=now)
        except (ValueError,OSError):history={'version':1,'entries':[]};audit['history_status']='unavailable'
        prompt=selector_prompt(collection,history,now=now)
        command=command_factory()
        if monotonic()>=deadline:raise DiscoveryFailure('selector_timeout')
        runner=selector_runner or run_selector
        result=runner(command,input=prompt.encode(),deadline=deadline,cwd=Path(__file__).resolve().parent)
        if result.returncode:raise DiscoveryFailure('selector_timeout' if result.returncode==124 else 'selector_unavailable')
        if monotonic()>=deadline:raise DiscoveryFailure('selector_timeout')
        candidates,parsed=admit_selection(result.stdout,collection,now=now);audit.update(parsed)
        if not candidates and collection.get('coverage_complete') is not True:raise DiscoveryFailure('collection_incomplete')
        # Capture actual selection output privately; no text is forwarded as an
        # error. It remains untrusted, source-bound and strictly size-limited.
        capture['selector_output']=result.stdout
        for c in candidates:
            try:record_history(history_path,{'url':c['urls'][0],'symbol':c['symbol'],'event_date':c['event_date'],'catalyst':c['catalyst']},now=now)
            except (OSError,ValueError):audit['history_status']='unavailable'
        return finish(candidates)
    except DiscoveryFailure as error:
        audit['reason']=error.reason;finish([]);raise
