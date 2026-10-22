"""Deterministic search worker: no agent, MCP discovery, broker or model calls."""
from __future__ import annotations
import contextlib
import json
import os
import sys
from time import monotonic
from discovery_collection import collect_lanes
from extraction_contract import strict_json_loads


def execute(request,*,search):
    if not isinstance(request,dict) or request.get('version')!=1 or type(request.get('deadline')) not in (int,float):raise ValueError('invalid request')
    deadline=request['deadline']
    import math
    if not math.isfinite(deadline):raise ValueError('invalid deadline')
    return collect_lanes(request.get('requests'),deadline=min(deadline,monotonic()+60),search=search)


def main():
    try:
        body=sys.stdin.buffer.read(32769)
        if len(body)>32768:raise ValueError('request limit')
        request=strict_json_loads(body.decode())
        with contextlib.redirect_stdout(sys.stderr):
            from tools.web_tools import web_search_tool,_ensure_web_plugins_loaded
            _ensure_web_plugins_loaded()
            result=execute(request,search=web_search_tool)
    except Exception:result={'version':1,'status':'error','reason':'worker_unavailable'}
    sys.stdout.write(json.dumps(result,ensure_ascii=False));sys.stdout.flush()
    # Partial lane deadlines must not block on ThreadPoolExecutor's atexit
    # join. This isolated process owns no operational state; its guardian
    # reaps any descendants before acknowledging the completed protocol.
    os._exit(0)


if __name__=='__main__':main()
