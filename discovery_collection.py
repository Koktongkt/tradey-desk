"""Pure six-lane queries and strict search-envelope projection. No model or storage."""
from __future__ import annotations
import concurrent.futures
import datetime as dt
import hashlib
import json
import re
from time import monotonic
from urllib.parse import urlsplit
from extraction_contract import strict_json_loads

LANES=('broad','sec','issuer_ir','reporting','undercovered_wire','rotating')
SECTORS=('Energy','Materials','Industrials','Consumer Discretionary','Consumer Staples','Health Care','Financials','Information Technology','Communication Services','Utilities','Real Estate')
MAX_PROVIDER_BYTES=256*1024
MAX_RESPONSE_BYTES=2*1024*1024


def make_queries(cfg:dict, *, now:dt.datetime)->list[dict]:
    if now.tzinfo is None or now.utcoffset() is None:raise ValueError('aware clock required')
    now=now.astimezone(dt.timezone.utc)
    try:days=int(cfg.get('discovery_max_event_age_days',7))
    except (TypeError,ValueError):days=7
    if days<0:days=7
    cutoff=now.date()-dt.timedelta(days=days)
    context=f'{now:%B %d %Y} recent company announcements since {cutoff.isoformat()}'
    sector=SECTORS[(int(now.timestamp())//1200)%len(SECTORS)]
    queries=[f'US listed companies material earnings guidance contract acquisition {context}',
             f'site:sec.gov/Archives/edgar "8-K" "Date of Report" {context}',
             f'company investor relations press release earnings guidance contract {context}',
             f'(Reuters OR Bloomberg OR CNBC OR WSJ OR AP OR FT OR Barrons) company material news {context}',
             f'(site:businesswire.com OR site:prnewswire.com OR site:globenewswire.com) company contract product regulatory results {context} -"class action" -"shareholder alert"',
             f'US listed {sector} company material announcement earnings guidance contract {context}']
    return [{'lane':lane,'query':q,'limit':10,'query_version':1,'as_of':now.isoformat(),'event_cutoff':cutoff.isoformat(),'sector':sector} for lane,q in zip(LANES,queries)]


def _error(lane,reason):return {'lane':lane,'status':'error','reason':reason,'records':[],'receipt':{}}


def _project(request,raw):
    lane=request['lane']
    if not isinstance(raw,str):return _error(lane,'malformed_response')
    if len(raw.encode('utf-8'))>MAX_PROVIDER_BYTES:return _error(lane,'output_limit')
    try:x=strict_json_loads(raw)
    except (ValueError,RecursionError):return _error(lane,'malformed_response')
    if not isinstance(x,dict):return _error(lane,'malformed_response')
    if 'success' in x and type(x['success']) is not bool:return _error(lane,'malformed_response')
    if x.get('success') is False or x.get('error') or x.get('status') in ('error','failed'):return _error(lane,'provider_error')
    if 'status' in x and x['status'] not in ('ok','success'):return _error(lane,'malformed_response')
    data=x.get('data');rows=data.get('web') if isinstance(data,dict) else None
    if not isinstance(rows,list) or len(rows)>10:return _error(lane,'malformed_response')
    records=[]
    for rank,row in enumerate(rows,1):
        if not isinstance(row,dict):return _error(lane,'malformed_response')
        url,title,description=(row.get(k) for k in ('url','title','description'))
        if not all(isinstance(v,str) for v in (url,title,description)):return _error(lane,'malformed_response')
        try:
            p=urlsplit(url)
            if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or any(c.isspace() for c in url):raise ValueError
        except ValueError:return _error(lane,'malformed_response')
        host=p.hostname.lower()
        role='sec_hosted' if host=='sec.gov' or host.endswith('.sec.gov') else 'wire_hosted' if host in ('www.globenewswire.com','www.businesswire.com','www.prnewswire.com','globenewswire.com','businesswire.com','prnewswire.com') else 'unverified'
        identity=hashlib.sha256(json.dumps([lane,request['query'],rank,url],ensure_ascii=False).encode()).hexdigest()[:24]
        records.append({'id':identity,'lane':lane,'rank':rank,'url':url,'title':title,'description':description,'source_role':role,'legal_solicitation':bool(re.search(r'class.action|shareholder.alert|securities.fraud|investor.*lawsuit',title,re.I))})
    meta=x.get('metadata',x.get('_meta',{}));receipt={}
    if isinstance(meta,dict):
        for k in ('backend','provider'):
            if isinstance(meta.get(k),str) and re.fullmatch(r'[A-Za-z0-9_-]{1,40}',meta[k]):receipt[k]=meta[k]
        for k in ('requested_limit','effective_limit'):
            if type(meta.get(k)) is int and 0<=meta[k]<=10:receipt[k]=meta[k]
    return {'lane':lane,'status':'ok','reason':'completed','records':records,'receipt':receipt}


def collect_lanes(requests:list[dict], *, deadline:float, search)->dict:
    valid=(isinstance(requests,list) and len(requests)==6 and [x.get('lane') for x in requests if isinstance(x,dict)]==list(LANES)
           and all(x.get('limit')==10 and type(x.get('limit')) is int and isinstance(x.get('query'),str) and 0<len(x['query'])<=4096 for x in requests))
    if not valid:raise ValueError('invalid six-lane request')
    if monotonic()>=deadline:return {'version':1,'lanes':[_error(x['lane'],'timeout') for x in requests],'coverage_complete':False}
    def one(req):
        if monotonic()>=deadline:return _error(req['lane'],'timeout')
        try:return _project(req,search(query=req['query'],limit=10))
        except Exception:return _error(req['lane'],'provider_error')
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=6)
    futures={pool.submit(one,x):x['lane'] for x in requests};done={}
    try:
        for f in concurrent.futures.as_completed(futures,timeout=max(.001,deadline-monotonic())):done[futures[f]]=f.result()
    except concurrent.futures.TimeoutError:pass
    finally:pool.shutdown(wait=False,cancel_futures=True)
    lanes=[done.get(x['lane'],_error(x['lane'],'timeout')) for x in requests]
    result={'version':1,'lanes':lanes,'coverage_complete':all(x['status']=='ok' for x in lanes)}
    if len(json.dumps(result,ensure_ascii=False).encode())>MAX_RESPONSE_BYTES:
        return {'version':1,'lanes':[_error(x['lane'],'output_limit') for x in requests],'coverage_complete':False}
    return result
