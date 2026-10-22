#!/usr/bin/env python3
"""Dashboard-only MCP publication. No CLI deployment or credential handling."""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import stat
import asyncio
import re
import time

PROJECT='prj_lZuUmWxjOB1VLHhx9xfh4ddiUGbB'
TEAM='team_3ihUC7pHQl7w5HBcwIKL1Wol'
MAX_BYTES=8*1024*1024
MAX_WIRE_BYTES=12*1024*1024

class Rejected(Exception):
    pass

def payload(root: Path) -> dict:
    public=root/'public'
    if public.is_symlink() or not public.is_dir():
        raise Rejected('config')
    for p in public.rglob('*'):
        if p.is_symlink():
            raise Rejected('config')
    identity=json.loads((public/'.vercel'/'project.json').read_text())
    if identity.get('projectId')!=PROJECT or identity.get('orgId')!=TEAM:
        raise Rejected('config')
    files=[];size=0
    for p in sorted(public.rglob('*')):
        rel=p.relative_to(public)
        if any(part.startswith('.') for part in rel.parts):
            continue
        if any(part.lower() in {'private','state','secrets','node_modules'} for part in rel.parts):
            raise Rejected('config')
        if p.is_dir():
            continue
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size>MAX_BYTES or info.st_nlink!=1:
                raise Rejected('config')
            with os.fdopen(fd,'rb',closefd=False) as f:
                raw=f.read(MAX_BYTES+1)
        finally:
            os.close(fd)
        size+=len(raw)
        if size>MAX_BYTES:
            raise Rejected('config')
        try:
            data=raw.decode('utf-8');encoding='utf-8'
        except UnicodeDecodeError:
            data=base64.b64encode(raw).decode('ascii');encoding='base64'
        files.append(dict(file=rel.as_posix(),data=data,encoding=encoding))
    if not {'index.html','dashboard.json'}.issubset({r['file'] for r in files}):
        raise Rejected('config')
    args=dict(teamId=TEAM,requestBody=dict(name='tradey-desk',project=PROJECT,target='production',files=files))
    if len(json.dumps(args).encode())>MAX_WIRE_BYTES:
        raise Rejected('config')
    return args

async def publish(call, args: dict, deadline: float, *, existing_id: str | None=None) -> dict:
    async def bounded(name, arguments):
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise Rejected('timeout')
        try:
            value=await asyncio.wait_for(call(name,arguments),min(25,remaining))
        except TimeoutError:
            raise Rejected('timeout') from None
        except Rejected:
            raise
        except Exception:
            raise Rejected('failed') from None
        if not isinstance(value,dict):
            raise Rejected('failed')
        return value
    projects=await bounded('list_projects',dict(teamId=TEAM,search='tradey-desk',limit=1))
    if not any(isinstance(p,dict) and p.get('id')==PROJECT for p in projects.get('projects',[])):
        raise Rejected('config')
    deployment_id=existing_id
    if deployment_id is None:
        created=await bounded('create_deployment',args)  # Exactly once, including ambiguous failure.
        deployment_id=created.get('id')
    if not isinstance(deployment_id,str) or not re.fullmatch(r'dpl_[A-Za-z0-9]+',deployment_id):
        raise Rejected('failed')
    while True:
        row=await bounded('get_deployment',dict(teamId=TEAM,idOrUrl=deployment_id))
        project_id=row.get('projectId')
        if project_id is None and isinstance(row.get('project'),dict):
            project_id=row['project'].get('id')
        if row.get('id')!=deployment_id or project_id!=PROJECT or row.get('target')!='production':
            raise Rejected('config')
        state=row.get('readyState',row.get('status'))
        if state in {'ERROR','CANCELED'}:
            raise Rejected('build')
        if state=='READY':
            aliases=await bounded('list_deployment_aliases',dict(teamId=TEAM,id=deployment_id))
            names=[a.get('alias') for a in aliases.get('aliases',[]) if isinstance(a,dict)]
            if 'tradey-desk-psi.vercel.app' in names:
                return dict(id=deployment_id,projectId=PROJECT,target='production',readyState='READY',alias='tradey-desk-psi.vercel.app')
        elif state not in {'QUEUED','INITIALIZING','BUILDING'}:
            raise Rejected('failed')
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise Rejected('timeout')
        await asyncio.sleep(min(2,remaining))

def decode_result(envelope: dict) -> dict:
    value=envelope.get('structuredContent')
    if not isinstance(value,dict):
        text=''.join(c.get('text','') for c in envelope.get('content',[]) if c.get('type')=='text')
        if len(text)>1024*1024:
            raise Rejected('failed')
        try:
            value=json.loads(text)
        except (ValueError,TypeError):
            raise Rejected('failed') from None
    # Vercel's native MCP API tools wrap REST-shaped data in result/deployment.
    # Unwrap only these known containers, never arbitrary provider keys.
    for key in ('result','deployment'):
        if isinstance(value,dict) and set(value)=={key} and isinstance(value[key],dict):
            value=value[key]
    if envelope.get('isError') or (isinstance(value,dict) and 'error' in value):
        status=value.get('statusCode') if isinstance(value,dict) else None
        raise Rejected({401:'auth',403:'auth',429:'rate_limit',500:'service',502:'service',503:'service',504:'service'}.get(status,'failed'))
    if not isinstance(value,dict):
        raise Rejected('failed')
    return value

async def native_publish(args: dict | None, deadline: float, *, existing_id: str | None=None) -> dict:
    """Use the installed Hermes lifecycle and OAuth manager without reading tokens.

    This installed release has MCPServerTask, not the former MCPClient facade.
    Connect only the explicitly selected server; sampling is forcibly disabled.
    """
    from hermes_cli.config import load_config
    from tools.mcp_tool_discovery import _connect_server
    cfg=dict(load_config().get('mcp_servers',{}).get('vercel',{}))
    from urllib.parse import urlsplit
    parsed=urlsplit(cfg.get('url',''))
    if parsed.scheme!='https' or parsed.netloc!='mcp.vercel.com' or cfg.get('auth')!='oauth' or cfg.get('enabled') is False or any(cfg.get(k) for k in ('headers','env','command')):
        raise Rejected('config')
    cfg.update(sampling={'enabled':False},connect_timeout=25,timeout=25)
    server=await asyncio.wait_for(_connect_server('vercel',cfg),min(30,max(.001,deadline-time.monotonic())))
    try:
        tools={t.name:t.model_dump(by_alias=True) for t in server._tools}
        required={'list_projects','create_deployment','get_deployment','list_deployment_aliases'}
        if not required.issubset(tools):
            raise Rejected('config')
        file_schema=tools['create_deployment']['inputSchema']['properties']['requestBody']['properties']['files']
        if 'data' not in json.dumps(file_schema) or 'encoding' not in json.dumps(file_schema):
            raise Rejected('config')
        async def call(name,arguments):
            if name not in required or arguments.get('teamId')!=TEAM:
                raise Rejected('config')
            result=await server.session.call_tool(name,arguments)
            return decode_result(result.model_dump(by_alias=True))
        if args is None and existing_id is None:
            result=await asyncio.wait_for(call('list_projects',dict(teamId=TEAM,search='tradey-desk',limit=1)),min(25,max(.001,deadline-time.monotonic())))
            if not any(p.get('id')==PROJECT for p in result.get('projects',[]) if isinstance(p,dict)):
                raise Rejected('config')
            return dict(control='authenticated',projectId=PROJECT,inline_files=True,tools=len(tools))
        return await publish(call,args or {},deadline,existing_id=existing_id)
    finally:
        await server.shutdown()

def worker_main(control: bool=False) -> int:
    import logging
    logging.disable(logging.CRITICAL)
    try:
        from tools.mcp_tool_loop import _ensure_mcp_loop, _run_on_mcp_loop
        from tools.mcp_tool_lifecycle import shutdown_mcp_servers
        _ensure_mcp_loop()
        deadline=time.monotonic()+85
        try:
            args=None if control else payload(Path(__file__).resolve().parent)
            result=_run_on_mcp_loop(native_publish(args,deadline),timeout=max(.001,deadline-time.monotonic()))
            print(json.dumps(result,sort_keys=True))
            return 0
        finally:
            shutdown_mcp_servers(timeout=2)
    except BaseException as exc:
        category=str(exc) if isinstance(exc,Rejected) else 'timeout' if isinstance(exc,TimeoutError) else 'failed'
        if category not in {'auth','config','build','network','rate_limit','service','timeout','failed'}:
            category='failed'
        print('SYSTEM_FAILURE dashboard_deploy_'+category)
        return 1

if __name__=='__main__':
    import sys
    raise SystemExit(worker_main(sys.argv[1:]==['--control']))
