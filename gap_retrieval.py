"""One code-owned search per missing-source lane; only actual result URLs return."""
from __future__ import annotations
import contextlib
import datetime as dt
import json
import math
from pathlib import Path
import re
import sys
from time import monotonic
from urllib.parse import urlsplit
from extraction_contract import strict_json_loads
from discovery_process import run_process


class GapContainmentError(RuntimeError):pass


def worker_command():
    from runtime_paths import hermes_runtime
    python,source=hermes_runtime();worker=Path(__file__).resolve()
    code=('import os,sys,runpy;os.environ.pop("PYTHONPATH",None);os.environ.pop("PYTHONHOME",None);os.environ.pop("VIRTUAL_ENV",None);'
          f'sys.path.insert(0,{str(source)!r});sys._hermes_pin_default_home=True;import hermes_bootstrap;'
          f'sys.path.insert(0,{str(worker.parent)!r});runpy.run_path({str(worker)!r},run_name="__main__")')
    return [python,'-I','-c',code]


def search_gap(symbol,catalyst,event_date,*,role,attempted,accepted_domains,deadline):
    if monotonic()>=deadline:return None
    if not isinstance(symbol,str) or not re.fullmatch(r'[A-Z]{1,6}',symbol) or role not in ('independent','wire'):return None
    try:dt.date.fromisoformat(event_date)
    except (ValueError,TypeError):return None
    terms=' '.join(re.findall(r'[A-Za-z0-9]+',str(catalyst))[:24])
    source='Reuters Bloomberg CNBC AP FT reporting' if role=='independent' else 'Business Wire PR Newswire GlobeNewswire release'
    query=f'{symbol} {event_date} {terms} {source}'
    request={'version':1,'query':query,'deadline':min(deadline,monotonic()+30)}
    try:result=run_process(worker_command(),json.dumps(request).encode(),deadline=request['deadline'],cwd=Path(__file__).resolve().parent)
    except OSError:raise
    except Exception as error:raise GapContainmentError('gap_containment_unconfirmed') from error
    try:
        x=strict_json_loads(result.stdout)
        if isinstance(x,dict) and x.get('reason')=='containment_unconfirmed':raise GapContainmentError('gap_containment_unconfirmed')
        if result.returncode or not isinstance(x,dict) or x.get('status')!='ok' or not isinstance(x.get('records'),list) or len(x['records'])>10:return None
        from alpha_radar import publisher_domain,source_profile
        eligible=[]
        for i,row in enumerate(x['records']):
            if not isinstance(row,dict) or not isinstance(row.get('url'),str):return None
            url=row['url'];parsed=urlsplit(url)
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:return None
            if url in attempted or publisher_domain(url) in accepted_domains:continue
            actual=source_profile(url)['role']
            eligible.append((0 if actual==role else 1 if actual=='unknown' else 2,i,url))
        return min(eligible)[2] if eligible else None
    except (ValueError,TypeError,KeyError,UnicodeError):return None


def main():
    try:
        raw=sys.stdin.buffer.read(32769)
        if len(raw)>32768:raise ValueError
        request=strict_json_loads(raw.decode())
        deadline=request.get('deadline')
        if (request.get('version')!=1 or not isinstance(request.get('query'),str) or not 0<len(request['query'])<=4096
                or type(deadline) not in (int,float) or not math.isfinite(deadline) or monotonic()>=deadline):raise ValueError
        from discovery_collection import _project
        with contextlib.redirect_stdout(sys.stderr):
            from tools.web_tools import web_search_tool,_ensure_web_plugins_loaded
            _ensure_web_plugins_loaded()
            if monotonic()>=deadline:raise ValueError
            response=web_search_tool(query=request['query'],limit=10)
        result=_project({'lane':'gap','query':request['query']},response)
    except Exception:result={'status':'error','reason':'search_unavailable','records':[]}
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
