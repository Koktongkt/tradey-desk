#!/usr/bin/env python3
"""Opt-in cron entrypoint; the existing CLI entrypoint remains unchanged."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid
from dashboard_process import run_owned
from dashboard_deployment import record_attempt, classify, TOTAL_BUDGET, ATTEMPT_TIMEOUT
from dashboard_mcp import PROJECT, TEAM, Rejected

ROOT=Path(__file__).resolve().parent

def runtime_command(root: Path, timeout: float=10, *, control=False) -> list[str]:
    """Obtain the installed runtime with its existing bootstrap, without installs."""
    result=run_owned(['hermes','--print-runtime-command'],root,min(10,timeout))
    if result.returncode:
        raise Rejected('config')
    command=json.loads(result.stdout)
    tail="runpy.run_module('hermes_cli.main', run_name='__main__', alter_sys=True)"
    if not isinstance(command,list) or len(command)!=4 or command[1:3]!=['-I','-c'] or not isinstance(command[-1],str) or not command[-1].endswith(tail):
        raise Rejected('config')
    target=str(root/'dashboard_mcp.py')
    command[-1]=command[-1][:-len(tail)]+f"sys.path.insert(0,{str(root)!r});sys.argv=[{target!r}]+{['--control'] if control else []!r};runpy.run_path({target!r},run_name='__main__')"
    return command

def save_receipt(root: Path, row: dict) -> None:
    # Parent and final opens refuse symlinks; receipts contain only allowlisted public identity.
    if not isinstance(row,dict) or not re.fullmatch(r'dpl_[A-Za-z0-9]+',row.get('id','')) or row.get('projectId')!=PROJECT or row.get('target')!='production' or row.get('readyState')!='READY' or row.get('alias')!='tradey-desk-psi.vercel.app':
        raise Rejected('failed')
    safe={key:row[key] for key in ('id','projectId','target','readyState','alias')}
    parent=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for name in ('private','dashboard_deploy_diagnostics'):
            try:os.mkdir(name,0o700,dir_fd=parent)
            except FileExistsError:pass
            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
            os.close(parent);parent=child
            if os.fstat(parent).st_uid!=os.getuid():raise Rejected('config')
            os.fchmod(parent,0o700)
        name='mcp-receipt-'+uuid.uuid4().hex+'.json'
        out=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
        with os.fdopen(out,'w') as stream:json.dump(safe,stream,sort_keys=True);stream.write('\n')
        records=[]
        for entry in os.listdir(parent):
            if not re.fullmatch(r'mcp-receipt-[0-9a-f]{32}\.json',entry):continue
            info=os.stat(entry,dir_fd=parent,follow_symlinks=False)
            if stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1:
                records.append((info.st_mtime_ns,entry))
        for _,entry in sorted(records)[:-30]:os.unlink(entry,dir_fd=parent)
    finally:
        os.close(parent)

def helper(root: Path=ROOT) -> int:
    deadline=time.monotonic()+TOTAL_BUDGET
    stage='build'
    try:
        for stage in ('build','deploy'):
            started=time.monotonic()
            remaining=deadline-started
            if remaining<=0:raise Rejected('timeout')
            command=([sys.executable,str(root/'public_dashboard.py')] if stage=='build'
                     else runtime_command(root,min(10,remaining)))
            remaining=deadline-time.monotonic()
            if remaining<=0:raise Rejected('timeout')
            result=run_owned(command,root,min(ATTEMPT_TIMEOUT,remaining))
            category=classify(stage,result)
            if stage=='deploy' and result.returncode:
                from run_cycle import parse_failure_event
                event=parse_failure_event(result.stdout)
                candidate=event.removeprefix('SYSTEM_FAILURE dashboard_deploy_') if event else ''
                if candidate in {'auth','config','build','network','rate_limit','service','timeout','failed'}:category=candidate
            record_attempt(root,stage,1,result.returncode,time.monotonic()-started,category)
            if category!='success':raise Rejected(category)
            if stage=='deploy':save_receipt(root,json.loads(result.stdout))
        return 0
    except BaseException as exc:
        category=str(exc) if isinstance(exc,Rejected) else 'failed'
        if category not in {'auth','config','build','network','rate_limit','service','timeout','failed'}:category='failed'
        print(f'SYSTEM_FAILURE dashboard_{stage}_{category}')
        return 1

def main() -> int:
    # Reuse only the existing predicate, never run_cycle's CLI deployment path.
    from run_cycle import in_window, parse_failure_event
    if not in_window('dashboard'):return 0
    try:
        result=run_owned([sys.executable,str(ROOT/'dashboard_mcp_entry.py'),'--helper'],ROOT,300,outer=True)
        if result.returncode:
            fallback=('SYSTEM_FAILURE dashboard_timeout' if result.returncode==124
                      else 'SYSTEM_FAILURE dashboard_deploy_failed')
            print(parse_failure_event(result.stdout) or fallback)
            return 1
        return 0
    except BaseException:
        print('SYSTEM_FAILURE dashboard_deploy_failed')
        return 1

if __name__=='__main__':
    raise SystemExit(helper() if sys.argv[1:]==['--helper'] else main())
