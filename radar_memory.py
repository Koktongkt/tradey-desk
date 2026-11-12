"""Small Radar adapter: exact completed bundles, not economic-event identity."""
from dataclasses import dataclass
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import research_memory as memory
import evidence_capture_store as captures
from retained_article import original_text


def _subjects(symbol,raw,url):
    # Reuse the complete-source cover parser only for explicit issuer fields.
    # No fiscal-period, transaction, event or allowance resolver is invoked.
    from opportunity_identity import _Cover,_locator
    locator=_locator(url)
    if locator is None:return set()
    parser=_Cover();parser.feed(raw);parser.close()
    found=set()
    if parser.bad_structure:return found
    for facts in parser.facts.values():
        symbols=facts.get('dei:TradingSymbol',[]);ciks=facts.get('dei:EntityCentralIndexKey',[])
        if symbols==[symbol] and len(ciks)==1:
            cik=str(ciks[0]).strip()
            if re.fullmatch(r'[0-9]{1,10}',cik) and int(cik)==int(locator[0]):
                found.add('CIK:'+cik.zfill(10))
    return found


def issuer_for_pages(symbol,pages):
    found=set()
    for page in pages:
        raw=original_text(page)
        if raw is not None:found.update(_subjects(symbol,raw,page['url']))
    return next(iter(found)) if len(found)==1 else None


def cached_issuer(root,symbol,now):
    try:
        found=set();clock=memory._timestamp(now)
        for row in memory._rows(Path(root))[-256:]:
            if row['record_type']!='complete' or not 0<=(clock-memory._timestamp(row['completed_at'])).total_seconds()<86400:continue
            for ref in row['capture_refs']:
                raw=captures.read_capture(root,ref).decode('utf-8')
                envelope=captures._read(root,ref)
                found.update(_subjects(symbol,raw,envelope['capture']['url']))
        return next(iter(found)) if len(found)==1 else None
    except Exception:return None


def resource_issuers(root,urls,now,deadline):
    from time import monotonic
    found={url:set() for url in urls};clock=memory._timestamp(now)
    try:
        for row in reversed(memory._rows(Path(root))[-256:]):
            if monotonic()>=deadline:break
            if row['record_type']!='complete' or not 0<=(clock-memory._timestamp(row['completed_at'])).total_seconds()<86400:continue
            result=captures.read_result(root,row['result_ref']);issuer=result.get('issuer')
            if not isinstance(issuer,str) or not re.fullmatch(r'CIK:[0-9]{10}',issuer):continue
            owned=[];proven=set()
            for ref in row['capture_refs']:
                if monotonic()>=deadline:return {}
                raw=captures.read_capture(root,ref).decode('utf-8');c=captures._read(root,ref)['capture']
                owned.append(c['url'])
                from opportunity_identity import _Cover
                parser=_Cover();parser.feed(raw);parser.close()
                for facts in parser.facts.values():
                    for symbol in facts.get('dei:TradingSymbol',[]):proven.update(_subjects(symbol,raw,c['url']))
            if proven=={issuer}:
                for url in owned:
                    if url in found:found[url].add(issuer)
        return {url:next(iter(values)) for url,values in found.items() if len(values)==1}
    except Exception:return {}


def rule_version(root):
    import sqlite_ledger as storage
    rows=storage.read_jsonl_stream_readonly(Path(root)/'private/opportunity_policy.jsonl')
    return memory._label(rows[-1]['research_transition']['rule_version'])


def _publication_fingerprint(pages):
    fields=('url','title','published_at','publication_precision','publication_basis')
    return hashlib.sha256(memory._canonical(sorted(
        [{k:p.get(k) for k in fields} for p in pages],key=lambda p:p['url']))).hexdigest()


def research_memory_for_bundle(root:Path,*,issuer:str,pages:list[dict],now:str,rule_version:str)->dict:
    from opportunity_state import OpportunityStateError
    info=dict(status='unusable',reason='research_memory_unusable',record=None,key=None,capture_refs=[],
              publication_fingerprint=None,issuer=issuer,candidate=None)
    fatal=[]
    try:
        if not re.fullmatch(r'CIK:[0-9]{10}',issuer) or not pages or len(pages)>32:return info
        refs=tuple(captures.retain_page(root,p) for p in pages)
        keys=tuple(memory.document_key(issuer=issuer,representation=r['representation'],
            content=captures.read_capture(root,r),rule_version=rule_version,stage='document') for r in refs)
        key=memory.bundle_key(issuer=issuer,document_keys=keys,rule_version=rule_version,stage='synthesis')
        fingerprint=_publication_fingerprint(pages)
        def fresh(row,result):
            if row['rule_version']!=rule_version or result.get('publication_fingerprint')!=fingerprint:return False
            if row['disposition']!='qualified':return True
            # Mandatory history/authority failures are not cache failures. The
            # generic lookup deliberately catches callbacks, so carry typed
            # integrity failures out explicitly and re-raise after lookup.
            try:
                import sqlite_ledger as storage
                from review_history import dossier_status
                import alpha_radar as radar
                stored=next((c for c in storage.read_jsonl_stream_readonly(Path(root)/'candidates.jsonl')
                             if c.get('dossier_hash')==result.get('dossier_hash')),None)
                if stored is None:return False
                context=radar._run_policy_context(root)
                # This call checks binding and strict history before freshness.
                eligible=radar._stored_policy_eligible(stored,context)
                if not eligible:
                    return dossier_status(root,stored['dossier_hash'])=='completed'
                cfg=json.loads((Path(root)/'autonomy_config.json').read_text())
                if not radar._fresh_stored_candidate(stored,cfg,memory._timestamp(now),60,
                        root=Path(root),context=context):
                    return dossier_status(root,stored['dossier_hash'])=='completed'
                info['candidate']=stored
                return True
            except Exception as error:
                fatal.append(OpportunityStateError('opportunity_policy_state_unavailable'))
                raise fatal[-1] from error
        info.update(memory.lookup(root,key=key,now=now,freshness_check=fresh))
        if fatal:raise fatal[0]
        info.update(key=key,capture_refs=list(refs),publication_fingerprint=fingerprint)
        return info
    except OpportunityStateError:raise
    except Exception:return info


@dataclass(frozen=True)
class MemoryWork:
    root:Path
    info:dict
    rule_version:str


def complete_work(work,result,disposition,now):
    if not isinstance(work,MemoryWork) or not work.info.get('key'):return None
    return memory.complete(work.root,key=work.info['key'],stage='synthesis',rule_version=work.rule_version,
        capture_refs=tuple(work.info['capture_refs']),
        result={**result,'publication_fingerprint':work.info['publication_fingerprint'],'issuer':work.info['issuer']},
        disposition=disposition,completed_at=now)


def retry_allowed(root,issuer,url,now):
    return all(memory.retry_allowed(root,issuer=issuer,url=url,reason=reason,now=now)
               for reason in memory._TRANSIENT)
