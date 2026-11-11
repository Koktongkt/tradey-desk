"""Pure, narrow original SEC merger-agreement identity and continuity.

No I/O, models, broker access, administrative binding or allowance authority.
Only text-native original 8-K / executed three-party merger agreements are
supported. Other acquisition structures remain an explicit coverage limitation.
"""
from __future__ import annotations
import datetime as dt
from hashlib import sha256
import re
from urllib.parse import urljoin

from opportunity_identity import (EventResolution, IssuerBinding, _Cover, _locator,
                                  _canonical, _valid_legal_name)
from earnings_identity_evidence import validate_identity_capture, identity_source_bytes
from earnings_identity_resolution import _Body, _document, _normal

ROOT_KEYS = {'kind','issuer_cik','original_report_document_id','original_agreement_document_id'}
AGREEMENT_KEYS = {'root','executed_on','parties','witnesses','independent_from'}
REASON = 'sec_original_acquisition'
_SOURCE_AUTHORITY = object()
DATE = r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+([0-9]{1,2}),\s+([0-9]{4})'
MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December']


def unknown(reason='acquisition_evidence_missing', status='unknown'):
    return EventResolution(status,None,None,None,None,(),(),reason)


def event_id(root):
    return 'oe3:' + sha256(_canonical({'version':3,'family':'acquisition','root':root})).hexdigest()


def seal_resolution(resolution):
    """Process-local proof of source validation; never serialized or restored from JSON."""
    from opportunity_identity import candidate_identity
    digest=sha256(_canonical(candidate_identity(resolution))).hexdigest()
    object.__setattr__(resolution,'_acquisition_source_seal',(_SOURCE_AUTHORITY,digest))
    return resolution


def source_validated(resolution):
    from opportunity_identity import candidate_identity
    seal=getattr(resolution,'_acquisition_source_seal',None)
    try:
        return (isinstance(seal,tuple) and len(seal)==2 and seal[0] is _SOURCE_AUTHORITY
                and seal[1]==sha256(_canonical(candidate_identity(resolution))).hexdigest())
    except (ValueError,TypeError,KeyError):return False


def validate_agreement(value, cik, documents, refs):
    """Closed wire shape, not source authenticity. Retention replays source proof."""
    if not isinstance(value,dict) or set(value)!=AGREEMENT_KEYS:raise ValueError('invalid_agreement')
    root=value['root']
    if (not isinstance(root,dict) or set(root)!=ROOT_KEYS or root['kind']!='sec_original_agreement'
            or root['issuer_cik']!=cik):raise ValueError('invalid_agreement_root')
    doc_ids={d.document_id for d in documents}
    for key in ('original_report_document_id','original_agreement_document_id'):
        if (not isinstance(root[key],str) or root[key] not in doc_ids
                or not re.fullmatch(r'sec:[0-9]{18}/[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:htm|html)',root[key])):
            raise ValueError('invalid_agreement_root')
    if root['original_report_document_id']==root['original_agreement_document_id']:raise ValueError('invalid_agreement_root')
    stamp=value['executed_on']
    if not isinstance(stamp,str) or dt.date.fromisoformat(stamp).isoformat()!=stamp:raise ValueError('invalid_agreement_date')
    parties=value['parties']
    if not isinstance(parties,list) or len(parties)!=3:raise ValueError('invalid_agreement_parties')
    if [p.get('role') if isinstance(p,dict) else None for p in parties]!=['Parent','Merger Sub','Company']:
        raise ValueError('invalid_agreement_parties')
    if any(set(p)!={'role','legal_name'} or not _valid_legal_name(p['legal_name']) for p in parties):
        raise ValueError('invalid_agreement_parties')
    if len({p['legal_name'].casefold() for p in parties})!=3:raise ValueError('invalid_agreement_parties')
    independent=value['independent_from']
    if (not isinstance(independent,list) or len(independent)>32 or len(set(independent))!=len(independent)
            or any(not isinstance(s,str) or not re.fullmatch(r'sec:[0-9]{18}/[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:htm|html)',s) for s in independent)):
        raise ValueError('invalid_agreement_independence')
    witnesses=value['witnesses']
    if not isinstance(witnesses,list) or not 3<=len(witnesses)<=32:raise ValueError('invalid_agreement_witnesses')
    for w in witnesses:
        if (not isinstance(w,dict) or set(w)!={'ref','start','end','text'} or w['ref'] not in refs
                or type(w['start']) is not int or type(w['end']) is not int
                or not 0<=w['start']<w['end']<=2_000_000 or not isinstance(w['text'],str)
                or not 1<=len(w['text'])<=4096 or w['end']-w['start']!=len(w['text'])):
            raise ValueError('invalid_agreement_witnesses')
    return value


class AcquisitionBody(_Body):
    def __init__(self):super().__init__();self.all_links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a' and not self.blocked:self.all_links.extend(v for k,v in attrs if k=='href')
        super().handle_starttag(tag,attrs)


def parse(capture):
    raw=identity_source_bytes(capture)
    if raw is None:raise ValueError('trusted_identity_capture_required')
    text=raw.decode('utf-8',errors='strict')
    cover=_Cover();cover.feed(text);cover.close()
    if cover.bad_structure or cover.stack or not cover.closed_html:raise ValueError('acquisition_incomplete_structure')
    body=AcquisitionBody();body.feed(text);body.close()
    return cover,body,_normal(' '.join(body.text))


def subject(cover,symbol,cik):
    names={_normal(value) for facts in cover.facts.values()
           for value in facts.get('dei:EntityRegistrantName',[])}
    if len(names)>1 or any(not _valid_legal_name(name) for name in names):raise ValueError('issuer_conflict')
    found=[]
    for context,facts in cover.facts.items():
        for key,expected in [('dei:TradingSymbol',symbol),('dei:EntityCentralIndexKey',cik)]:
            if key in facts and set(facts[key])!={expected}:raise ValueError('issuer_conflict')
        keys=['dei:TradingSymbol','dei:EntityCentralIndexKey','dei:EntityRegistrantName','dei:DocumentType']
        if not all(k in facts for k in keys):continue
        if any(len(set(facts[k]))!=1 for k in keys):raise ValueError('issuer_conflict')
        legal=_normal(facts['dei:EntityRegistrantName'][0])
        if not _valid_legal_name(legal) or cover.contexts.get(context,{}).get('xbrli:identifier')!=[cik]:
            raise ValueError('issuer_conflict')
        found.append((legal,context,facts['dei:DocumentType'][0]))
    if len(set(found))>1:raise ValueError('issuer_conflict')
    return found[0] if found else None


def section(text,item):
    headings={'1.01':'Entry into a Material Definitive Agreement.',
              '2.01':'Completion of Acquisition or Disposition of Assets.'}
    if item not in headings:return None
    # Match a complete supported heading, not later cross-references to Item 2.01.
    pattern=r'\bItem\s+'+re.escape(item)+r'\s+'+re.escape(headings[item])+r'(.*?)(?=\bItem\s+[0-9]+\.[0-9]+\s+[A-Z][a-z]|$)'
    matches=list(re.finditer(pattern,text))
    if len(matches)!=1:return None
    return matches[0][1]


def original_links(body,base,text):
    item=section(text,'1.01')
    if not item or not re.search(r'\bentered into an Agreement and Plan of Merger\b',item):return ()
    numbers=set(re.findall(r'\bExhibit\s+(2\.[0-9]+)\b',item))
    found=[]
    for label,hrefs in body.rows:
        if 'Agreement and Plan of Merger' not in label or not numbers.intersection(re.findall(r'\b2\.[0-9]+\b',label)):
            continue
        for href in hrefs:
            url=urljoin(base,href);loc=_locator(url);parent=_locator(base)
            if loc and loc[0]==parent[0] and loc[1].split('/')[0]==parent[1].split('/')[0]:
                found.append(url)
    return tuple(dict.fromkeys(found))


def acquisition_links(raw,base):
    """Bounded literal links only; never guess original filings/exhibit filenames."""
    if _locator(base) is None:return ()
    from earnings_identity_evidence import capture_identity_source
    try:
        cap=capture_identity_source(base,raw,returned_url=base,content_type='text/html')
        cover,body,text=parse(cap)
    except (ValueError,UnicodeError):return ()
    result=list(original_links(body,base,text))
    # Closing evidence may literally incorporate the original agreement/report
    # and executed merger letter. It cannot create an original itself.
    if section(text,'2.01') and 'completed the previously announced transaction' in text:
        for label,hrefs in body.rows:
            if not any(s in label for s in ('Agreement and Plan of Merger','Letter Agreement')):continue
            for href in hrefs:
                url=urljoin(base,href);loc=_locator(url)
                if loc and loc[0]==_locator(base)[0] and url not in result:result.append(url)
        # The report text's literal original-report link is needed to reconstruct origin.
        from html.parser import HTMLParser
        class Links(HTMLParser):
            def __init__(self):super().__init__();self.hrefs=[]
            def handle_starttag(self,tag,attrs):
                if tag=='a':self.hrefs.extend(v for k,v in attrs if k=='href')
        links=Links();links.feed(raw.decode('utf-8'))
        for href in links.hrefs:
            url=urljoin(base,href);loc=_locator(url)
            if loc and loc[0]==_locator(base)[0] and re.search(r'(?:_|-)8k\.htm[l]?$',url,re.I) and url not in result:
                result.append(url)
    return tuple(result[:32])


def date_value(match):
    return dt.date(int(match[3]),MONTHS.index(match[1])+1,int(match[2])).isoformat()


def witness(capture,text,needle,kind):
    start=text.index(needle)
    return {'ref':capture.retained_ref+'#'+kind,'start':start,'end':start+len(needle),'text':needle}


def agreement_facts(text):
    if re.search(r'\b(?:This|The) (?:Agreement|Merger Agreement) (?:amends(?: and restates)?|replaces|supersedes) (?:that certain|the|an?) [^.]{0,300}dated as of\b',text):
        raise ValueError('acquisition_continuity_unknown')
    openings=list(re.finditer(r'THIS AGREEMENT AND PLAN OF MERGER\s*\(this\s*[“"]\s*Agreement\s*[”"]\s*\)\s*is made and entered into as of\s+'+DATE+r',\s+by and among\s+',text))
    if len(openings)!=1:raise ValueError('acquisition_agreement_ambiguous')
    opening=openings[0];tail=text[opening.end():opening.end()+1600]
    parties=[]
    for role in ('Parent','Merger Sub','Company'):
        pattern=r'([^()]{1,300}?),\s+a\s+[^()]{1,220}\(\s*(?:the\s+)?[“"]\s*'+re.escape(role)+r'\s*[”"]\s*\)'
        matches=list(re.finditer(pattern,tail))
        if len(matches)!=1:raise ValueError('acquisition_parties_ambiguous')
        name=matches[0][1].strip(', ').removeprefix('and ').strip()
        # A previous role declaration cannot be swallowed into the next name.
        if not _valid_legal_name(name):raise ValueError('acquisition_parties_ambiguous')
        parties.append({'role':role,'legal_name':name})
    signatures=text[text.index('IN WITNESS WHEREOF'):] if 'IN WITNESS WHEREOF' in text else ''
    if 'as of the date first written above' not in signatures:raise ValueError('acquisition_execution_missing')
    for p in parties:
        if not re.search(re.escape(p['legal_name'].upper())+r'\s+By:\s*/s/\s+\S',signatures):
            raise ValueError('acquisition_execution_missing')
    return date_value(opening),parties,text[opening.start():opening.end()+len(tail.split(' RECITALS ')[0])],signatures[:1000]


def resolve_acquisition_captures(symbol,captures,*,known_resolutions=()):
    if (not isinstance(captures,tuple) or not 1<=len(captures)<=32
            or not all(validate_identity_capture(c) for c in captures)):
        return unknown('identity_capture_invalid')
    if len({c.url for c in captures})!=len(captures):return unknown('identity_capture_duplicate')
    by_url={c.url:c for c in captures};parsed={};originals=[];updates=[];used=set()
    try:
        for cap in captures:parsed[cap.url]=parse(cap)
        for cap in captures:
            cover,body,text=parsed[cap.url];cik=_locator(cap.url)[0]
            issuer=subject(cover,symbol,cik)
            if issuer is None:continue
            legal,context,kind=issuer
            if kind!='8-K':return unknown('acquisition_original_required')
            links=original_links(body,cap.url,text)
            if links:
                if len(links)!=1 or links[0] not in by_url:return unknown('acquisition_evidence_missing')
                agreement=by_url[links[0]];_,agreement_body,agreement_text=parsed[agreement.url]
                executed,parties,opening,signatures=agreement_facts(agreement_text)
                if parties[2]['legal_name']!=legal:return unknown('issuer_conflict','conflict')
                item=section(text,'1.01')
                entered=re.search(r'On\s+'+DATE+r',\s+'+re.escape(legal)+r',.{0,160}?entered into an Agreement and Plan of Merger',item)
                if not entered or date_value(entered)!=executed:return unknown('acquisition_date_conflict','conflict')
                if re.search(r'\b(?:amended|restated|replacement|replaces|supersedes)\b',item[:entered.end()+400],re.I):
                    return unknown('acquisition_continuity_unknown')
                if any(p['legal_name'] not in item[:1500] for p in parties):return unknown('acquisition_parties_ambiguous')
                root={'kind':'sec_original_agreement','issuer_cik':cik,
                      'original_report_document_id':_locator(cap.url)[1],
                      'original_agreement_document_id':_locator(agreement.url)[1]}
                witnesses=[witness(cap,text,entered[0],'original-entry'),
                           witness(agreement,agreement_text,opening,'operative-agreement'),
                           witness(agreement,agreement_text,signatures,'executed-signatures')]
                support=[cap.retained_ref+'#dei:'+context]+[w['ref'] for w in witnesses]
                independent=[]
                for block in agreement_body.blocks:
                    declaration=re.fullmatch(r'This Agreement is separate from and independent of the agreement incorporated by reference at (https://[^ ]+\.html?)\s*\.',block)
                    if declaration is None:continue
                    url=declaration[1];loc=_locator(url)
                    if (loc is None or loc[0]!=cik or url not in {urljoin(agreement.url,h) for h in agreement_body.all_links}
                            or loc[1]==root['original_agreement_document_id']):
                        return unknown('acquisition_continuity_unknown')
                    independent.append(loc[1]);witnesses.append(witness(agreement,agreement_text,block,'independence:'+str(len(independent))))
                support=[cap.retained_ref+'#dei:'+context]+[w['ref'] for w in witnesses]
                info={'root':root,'executed_on':executed,'parties':parties,'witnesses':witnesses,
                      'independent_from':sorted(set(independent))}
                originals.append((cap,agreement,IssuerBinding(symbol,cik,legal,support[0]),info,support))
                used.update((cap.url,agreement.url))
            elif section(text,'2.01') and 'completed the previously announced transaction' in text:
                updates.append(cap)
            else:return unknown('acquisition_original_required')
        if len(originals)!=1:return unknown('acquisition_original_required')
        report,agreement,issuer,info,support=originals[0]
        for update in updates:
            uc,ub,ut=parsed[update.url]
            if subject(uc,symbol,issuer.cik)[0]!=issuer.legal_name:return unknown('issuer_conflict','conflict')
            links=acquisition_links(identity_source_bytes(update),update.url)
            if agreement.url not in links:return unknown('acquisition_continuity_unknown')
            original_text=parsed[report.url][2]
            report_date=re.search(r'Date of Report \(Date of earliest event reported\):\s+'+DATE,original_text)
            associated=[label for label,hrefs in ub.rows if any(urljoin(update.url,h)==agreement.url for h in hrefs)]
            if len(associated)!=1 or report_date is None:return unknown('acquisition_continuity_unknown')
            incorporated=re.search(r'Current Report on Form 8-K filed with the SEC on\s+'+DATE,associated[0])
            if incorporated is None or date_value(incorporated)!=date_value(report_date):
                return unknown('acquisition_continuity_unknown')
            if any(url not in by_url for url in links):return unknown('acquisition_evidence_missing')
            # Any amendment letter must explicitly identify the predecessor and
            # parties; missing or contradictory supporting material is not discarded.
            for url in links:
                if url in (report.url,agreement.url):continue
                _,_,letter=parsed[url]
                if ('Merger Letter Agreement' not in letter or '5. Full Force and Effect' not in letter
                        or 'This Letter has been duly executed' not in letter
                        or any(p['legal_name'] not in letter[:1600] for p in info['parties'])):
                    return unknown('acquisition_continuity_unknown')
                predecessor=re.search(r'Agreement and Plan of Merger, dated as of\s+'+DATE,letter)
                if not predecessor or date_value(predecessor)!=info['executed_on']:return unknown('acquisition_continuity_unknown')
                used.add(url)
            used.add(update.url)
        if used!=set(by_url):return unknown('unresolved_primary_evidence')
        eid=event_id(info['root'])
        for prior in known_resolutions:
            if prior.issuer.cik!=issuer.cik or prior.family=='earnings':continue
            if prior.version!=3 or prior.agreement is None:return unknown('acquisition_continuity_unknown')
            if prior.event_id==eid:
                if (prior.agreement['root']!=info['root'] or prior.agreement['parties']!=info['parties']
                        or prior.agreement['executed_on']!=info['executed_on'] or prior.issuer.legal_name!=issuer.legal_name):
                    return unknown('known_binding_disagrees','conflict')
                continue
            old={p['legal_name'] for p in prior.agreement['parties'] if p['role']!='Company'}
            new={p['legal_name'] for p in info['parties'] if p['role']!='Company'}
            if old.intersection(new) or prior.agreement['executed_on']==info['executed_on']:
                if (prior.agreement['root']['original_agreement_document_id'] not in info['independent_from']
                        and info['root']['original_agreement_document_id'] not in prior.agreement['independent_from']):
                    return unknown('acquisition_continuity_unknown')
        documents=tuple(sorted((_document(by_url[url]) for url in used),key=lambda d:(d.document_id,d.retained_ref)))
        return seal_resolution(EventResolution('verified',eid,issuer,'acquisition',None,documents,tuple(sorted(set(support))),
                               REASON,version=3,agreement=info))
    except (ValueError,TypeError,KeyError,IndexError,UnicodeError) as error:
        reason=str(error) if str(error) in {'issuer_conflict','identity_capture_invalid','acquisition_incomplete_structure',
            'acquisition_agreement_ambiguous','acquisition_parties_ambiguous','acquisition_execution_missing'} else 'acquisition_evidence_invalid'
        return unknown(reason,'conflict' if reason=='issuer_conflict' else 'unknown')
