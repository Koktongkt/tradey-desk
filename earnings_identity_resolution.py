"""Pure SEC earnings identity adapters; no acquisition, ledger or model I/O."""
from __future__ import annotations
import datetime as dt
import re
from html.parser import HTMLParser
from urllib.parse import urljoin
from opportunity_identity import (_Cover, _locator, _valid_legal_name, _event_id,
                                  EventResolution, IssuerBinding, DocumentObservation)
from earnings_identity_evidence import validate_identity_capture, identity_source_bytes

_DATE_FORMATS = {'ixt:date-monthname-day-year-en', 'ixt:datemonthdayyearen'}
_MONTHS = {name:index for index,name in enumerate(
    ['January','February','March','April','May','June','July','August','September','October','November','December'],1)}
_QUARTERS = {'first':'Q1','second':'Q2','third':'Q3','fourth':'FY'}


def _unknown(reason, status='unknown'):
    return EventResolution(status,None,None,None,None,(),(),reason)


def _normal(text): return ' '.join(text.split())


def _name(text): return ' '.join(re.findall(r'[A-Z0-9]+',text.upper()))


class IdentityCover(_Cover):
    """Apply only declared, supported inline-XBRL date transformations."""
    def __init__(self): super().__init__(); self._date_format=None; self.invalid_date=False
    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag,attrs)
        if tag=='ix:nonnumeric' and self.fact is not None and self.fact[1]=='dei:DocumentPeriodEndDate':
            self._date_format=dict(attrs).get('format')
    def handle_endtag(self, tag):
        if tag=='ix:nonnumeric' and self.fact is not None and self.fact[1]=='dei:DocumentPeriodEndDate':
            value=''.join(self.buffer)
            try:
                if self._date_format in _DATE_FORMATS:
                    match=re.fullmatch(r'([A-Za-z]+) ([0-9]{1,2}), ([0-9]{4})',_normal(value))
                    if not match or match[1] not in _MONTHS:raise ValueError('date_transform')
                    value=dt.date(int(match[3]),_MONTHS[match[1]],int(match[2])).isoformat()
                elif self._date_format is not None:raise ValueError('date_transform')
                else:value=dt.date.fromisoformat(value).isoformat()
                self.buffer=[value]
            except ValueError:self.invalid_date=True
            self._date_format=None
        super().handle_endtag(tag)


class _Body(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.text=[];self.blocks=[];self.rows=[]
        self.block=None;self.row=None;self.links=[];self.blocked=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','nav','aside','footer'):self.blocked.append(tag)
        if self.blocked:return
        if tag in ('p','h1','h2','h3','h4','h5','h6','title') and self.block is None:self.block=(tag,[])
        if tag=='tr':self.row=[];self.links=[]
        if tag=='a' and self.row is not None:
            self.links.extend(v for k,v in attrs if k=='href' and isinstance(v,str))
    def handle_data(self,data):
        if self.blocked:return
        self.text.append(data)
        if self.block is not None:self.block[1].append(data)
        if self.row is not None:self.row.append(data)
    def handle_endtag(self,tag):
        if self.blocked:
            if tag==self.blocked[-1]:self.blocked.pop()
            return
        if self.block is not None and tag==self.block[0]:
            self.blocks.append(_normal(' '.join(self.block[1])));self.block=None
        if tag=='tr' and self.row is not None:
            self.rows.append((_normal(' '.join(self.row)),tuple(self.links)));self.row=None;self.links=[]


def _parse(raw):
    text=raw.decode('utf-8',errors='strict');cover=IdentityCover();cover.feed(text);cover.close()
    body=_Body();body.feed(text);body.close()
    return cover,body


def _subjects(cover,symbol,cik):
    if cover.bad_structure or cover.stack or not cover.closed_html:return 'incomplete',[]
    subjects=[]
    for context,facts in cover.facts.items():
        for key,expected in [('dei:TradingSymbol',symbol),('dei:EntityCentralIndexKey',cik)]:
            if key in facts and set(facts[key])!={expected}:return 'issuer_conflict',[]
        keys=['dei:TradingSymbol','dei:EntityCentralIndexKey','dei:EntityRegistrantName','dei:DocumentType']
        if not all(key in facts for key in keys):continue
        if any(len(set(facts[key]))!=1 for key in keys):return 'issuer_conflict',[]
        if not _valid_legal_name(facts['dei:EntityRegistrantName'][0]):return 'issuer_conflict',[]
        if cover.contexts.get(context,{}).get('xbrli:identifier')!=[cik]:return 'issuer_conflict',[]
        subjects.append((context,facts))
    if len({f['dei:EntityRegistrantName'][0] for _,f in subjects})>1:return 'issuer_conflict',[]
    return ('ready' if subjects else 'missing'),subjects


def _links(body,base):
    text=_normal(' '.join(body.text))
    section=re.search(r'(?is)\bItem\s+2\.02\b(.*?)(?=\bItem\s+[0-9]+\.[0-9]+\b|$)',text)
    if not section or not re.search(r'(?is)\b(?:issued|released|announced)\b.{0,250}\bfinancial results\b',section[1]):return ()
    referenced=set(re.findall(r'(?i)\bExhibit\s+(99\.[0-9]+)\b',section[1]))
    result=[];locator=_locator(base)
    for label,hrefs in body.rows:
        if not re.search(r'(?i)\b(?:press|earnings) release\b',label):continue
        numbers=set(re.findall(r'\b99\.[0-9]+\b',label))
        if not numbers.intersection(referenced):continue
        for href in hrefs:
            url=urljoin(base,href);other=_locator(url)
            if (other and locator and other[0]==locator[0]
                    and other[1].split('/',1)[0]==locator[1].split('/',1)[0] and url not in result):result.append(url)
    return tuple(result)


def earnings_exhibit_links(raw: bytes, base_url: str) -> tuple[str,...]:
    """Only literal release links in the current filing's results/exhibit chain."""
    if _locator(base_url) is None:return ()
    try:cover,body=_parse(raw)
    except (ValueError,UnicodeError):return ()
    if cover.bad_structure or cover.stack or not cover.closed_html:return ()
    return _links(body,base_url)


def _release_period(body,legal,symbol):
    # Scope to opening article blocks; no comparative tables or later paragraphs.
    header=[];length=0
    for block in body.blocks:
        if length+len(block)>4000:break
        header.append(block);length+=len(block)
    text=' '.join(header)
    if _name(legal) not in _name(text):return None
    tickers=re.findall(r'(?i)\b(?:NASDAQ|NYSE(?:\s+AMERICAN)?)\s*:\s*([A-Z][A-Z0-9.-]{0,9})\b',text)
    if tickers and {t.upper() for t in tickers}!={symbol}:return None
    # Published declarative results headline, not "will report", meeting, or outlook.
    patterns=[r'\b(?:reports|provides|announces)\s+(first|second|third|fourth)\s+quarter\s+(?:fiscal\s+)?([0-9]{4})\s+(?:financial\s+)?results\b',
              r'\b(?:reports|provides|announces)\s+(?:fiscal\s+)?([0-9]{4})\s+(first|second|third|fourth)\s+quarter\s+(?:financial\s+)?results\b']
    found=set()
    for index,pattern in enumerate(patterns):
        for match in re.finditer(pattern,text,re.I):
            quarter,year=match.groups() if index==0 else (match[2],match[1])
            found.add(year+'-'+_QUARTERS[quarter.lower()])
    return next(iter(found)) if len(found)==1 else None


def _document(capture):
    return DocumentObservation(_locator(capture.url)[1],capture.url,capture.returned_url,
                               capture.source_sha256,'','',capture.retained_ref)


def resolve_earnings_capture(symbol: str, captures: tuple) -> EventResolution:
    if not isinstance(symbol,str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,9}',symbol):return _unknown('invalid_symbol')
    if (not isinstance(captures,tuple) or not 1<=len(captures)<=32
            or not all(validate_identity_capture(c) for c in captures)):return _unknown('identity_capture_invalid')
    if len({c.url for c in captures})!=len(captures):return _unknown('identity_capture_duplicate')
    by_url={c.url:c for c in captures};parsed={}
    try:
        for capture in captures:parsed[capture.url]=_parse(identity_source_bytes(capture))
    except (ValueError,UnicodeError):return _unknown('identity_capture_invalid')
    resolutions=[];used=set()
    for capture in captures:
        cover,body=parsed[capture.url];cik=_locator(capture.url)[0]
        status,subjects=_subjects(cover,symbol,cik)
        if status=='issuer_conflict':return _unknown('issuer_conflict','conflict')
        if status!='ready':continue
        for context,facts in subjects:
            kind=facts['dei:DocumentType'][0];legal=facts['dei:EntityRegistrantName'][0]
            period=None;support=[];documents=[]
            if kind in ('10-Q','10-K'):
                names=['dei:DocumentFiscalYearFocus','dei:DocumentFiscalPeriodFocus','dei:DocumentPeriodEndDate']
                if cover.invalid_date or not all(k in facts and len(set(facts[k]))==1 for k in names):continue
                year,quarter,end=[facts[k][0] for k in names]
                if not re.fullmatch(r'[0-9]{4}',year) or int(year)==0 or quarter not in ('Q1','Q2','Q3','Q4','FY'):continue
                try:end_date=dt.date.fromisoformat(end)
                except ValueError:continue
                if abs(int(year)-end_date.year)>1 or (kind=='10-K')!=(quarter=='FY'):continue
                ctx=cover.contexts.get(context,{})
                if ctx.get('xbrli:enddate',ctx.get('xbrli:instant'))!=[end]:continue
                period=year+'-'+quarter;reason='sec_periodic_filing';documents=[_document(capture)]
                support=[capture.retained_ref+'#dei:'+context];used.add(capture.url)
            elif kind in ('8-K','8-K/A'):
                links=_links(body,capture.url)
                if not links or any(url not in by_url for url in links):continue
                periods=[]
                for url in links:
                    exhibit=by_url[url];ec,eb=parsed[url]
                    if ec.bad_structure or ec.stack or not ec.closed_html:continue
                    reported=_release_period(eb,legal,symbol)
                    if reported is not None:periods.append(reported)
                if len(periods)!=len(links) or len(set(periods))!=1:continue
                period=periods[0];reason='sec_results_exhibit'
                documents=[_document(capture)]+[_document(by_url[url]) for url in links]
                support=[capture.retained_ref+'#dei:'+context]+[by_url[url].retained_ref+'#results-report' for url in links]
                used.update((capture.url,*links))
            if period:
                issuer=IssuerBinding(symbol,cik,legal,support[0])
                resolutions.append(EventResolution('verified',_event_id(cik,period),issuer,'earnings',period,
                                                   tuple(documents),tuple(support),reason,version=2))
    if not resolutions:return _unknown('unsupported_or_missing_primary_support')
    if len({(r.event_id,r.issuer.legal_name) for r in resolutions})!=1:return _unknown('multiple_report_subjects','conflict')
    if used!=set(by_url):return _unknown('unresolved_primary_evidence')
    anchor=min(resolutions,key=lambda r:r.issuer.support_ref)
    documents=tuple(sorted({d for r in resolutions for d in r.documents},key=lambda d:(d.document_id,d.retained_ref)))
    support=tuple(sorted({ref for r in resolutions for ref in r.support_refs}))
    return EventResolution('verified',anchor.event_id,anchor.issuer,'earnings',anchor.period,
                           documents,support,anchor.reason,version=2)
