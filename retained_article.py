"""Owned, complete provider-representation retention and independent witnesses.

A local digest binds bytes, not publisher authenticity. Only trusted acquisition
constructs records; models/provider fields cannot supply their own records.
"""
from __future__ import annotations
import hashlib
import html
from html.parser import HTMLParser
import json
import re

MAX_CAPTURE_BYTES=85000
KEYS={'version','url','returned_url','title','text','sha256','projection_sha256','reported_metadata','metadata_sha256','metadata_omitted'}
PUBLIC_METADATA={'sourceURL','source_url','title','description','datePublished','publishedTime','published_at','publication_date','article:published_time','og:title','og:url','content-type','last-modified'}
_UNSAFE_RELATION=re.compile(r'\b(?:event|meeting|conference|webcast|updated?|modified|copyright|related)\b|</?(?:nav|aside|footer|script|style)\b',re.I)


def _digest(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()


def retain_article(page,text,*,reported_metadata=None):
    result={k:v for k,v in page.items() if k not in ('_retained_article','_capture_status')}
    if not isinstance(text,str) or not text.strip():
        result['_capture_status']='missing';return result
    if re.search(r'(?m)^\s*─{3,}\s*\[TRUNCATED\]|^\[\.\.\. middle omitted',text):
        result['_capture_status']='incomplete';return result
    try:
        report=reported_metadata if isinstance(reported_metadata,dict) else {}
        metadata={k:v for k,v in report.items() if k in PUBLIC_METADATA and (v is None or isinstance(v,(str,int,float,bool)))}
        meta_json=json.dumps(metadata,sort_keys=True,ensure_ascii=True,allow_nan=False)
        capture={'version':1,'url':page['url'],'returned_url':page.get('returned_url',page['url']),
                 'title':page.get('title',''),'text':text,'sha256':_digest(text),
                 'projection_sha256':_digest(page['text']),'reported_metadata':metadata,
                 'metadata_sha256':_digest(meta_json),'metadata_omitted':len(metadata)!=len(report)}
        if len(json.dumps(capture,ensure_ascii=True,allow_nan=False).encode())>MAX_CAPTURE_BYTES:
            result['_capture_status']='capacity';return result
    except (KeyError,TypeError,ValueError,UnicodeError):
        result['_capture_status']='invalid';return result
    result['_retained_article']=capture;result['_capture_status']='complete'
    return result


def original_text(page):
    c=page.get('_retained_article') if isinstance(page,dict) else None
    try:
        if (not isinstance(c,dict) or set(c)!=KEYS or type(c['version']) is not int or c['version']!=1
                or not all(isinstance(c[k],str) for k in KEYS-{'version','reported_metadata','metadata_omitted'})
                or not isinstance(c['reported_metadata'],dict) or type(c['metadata_omitted']) is not bool
                or c['metadata_sha256']!=_digest(json.dumps(c['reported_metadata'],sort_keys=True,ensure_ascii=True,allow_nan=False))
                or c['url']!=page['url'] or c['returned_url']!=page.get('returned_url',page['url'])
                or c['title']!=page.get('title','') or c['projection_sha256']!=_digest(page['text'])
                or c['sha256']!=_digest(c['text'])
                or len(json.dumps(c,ensure_ascii=True,allow_nan=False).encode())>MAX_CAPTURE_BYTES):return None
        return c['text']
    except (KeyError,TypeError,ValueError,UnicodeError):return None


def rebind_article(source,projection):
    """Trusted normalizer rebind; hints never gain publication authority."""
    raw=original_text(source)
    if raw is None:return projection
    result=retain_article(projection,raw,reported_metadata=source['_retained_article']['reported_metadata'])
    if '_retained_article' in result:result['_retained_article']['metadata_omitted']=source['_retained_article']['metadata_omitted']
    return result


def _normal(text):return ' '.join(html.unescape(text).split()).strip()


class _ArticleHTML(HTMLParser):
    """Independent structural witness, not the legacy date/layout recognizer."""
    def __init__(self,raw,title):
        super().__init__(convert_charrefs=True)
        self.raw=raw;self.title=_normal(title);self.stack=[];self.articles=0
        self.h1=[];self.h1_count=0;self.heading=False;self.body_started=False
        self.label=[];self.dt_start=None;self.dt_end=None;self.pair=False
        self.paragraph=None;self.body=[];self.witnesses=[]
        self.lines=[0]
        for line in raw.splitlines(keepends=True):self.lines.append(self.lines[-1]+len(line))
    def _position(self):
        row,col=self.getpos();return self.lines[row-1]+col
    def eligible(self):return 'article' in self.stack and not any(t in self.stack for t in ('nav','aside','footer','script','style'))
    def handle_starttag(self,tag,attrs):
        if tag=='article':self.articles+=1
        self.stack.append(tag)
        if not self.eligible():return
        if tag=='h1':self.h1=[];self.h1_count+=1
        elif tag=='p' and self.heading:self.body_started=True;self.paragraph=[]
        elif tag=='dt' and self.heading and not self.body_started:
            self.dt_start=self._position();self.label=[];self.dt_end=None
        elif tag=='dd' and self.heading and not self.body_started:
            self.pair=(self.dt_end is not None and not self.raw[self.dt_end:self._position()].strip()
                       and bool(re.fullmatch(r'published(?:\s+on)?|publication(?:\s+date)?',_normal(''.join(self.label)),re.I)))
    def handle_data(self,data):
        if not self.eligible():return
        if 'h1' in self.stack:self.h1.append(data)
        if 'dt' in self.stack:self.label.append(data)
        if self.paragraph is not None and 'p' in self.stack:self.paragraph.append(data)
    def handle_endtag(self,tag):
        if self.eligible():
            if tag=='h1':self.heading=_normal(''.join(self.h1))==self.title
            elif tag=='dt':self.dt_end=self.raw.find('>',self._position())+1
            elif tag=='dd' and self.pair and self.dt_start is not None:
                end=self.raw.find('>',self._position())+1;span=self.raw[self.dt_start:end]
                if len(span)<=2000 and not _UNSAFE_RELATION.search(span):self.witnesses.append(span)
                self.pair=False
            elif tag=='p' and self.paragraph is not None:
                self.body.append(''.join(self.paragraph));self.paragraph=None
        if tag in self.stack:
            index=len(self.stack)-1-self.stack[::-1].index(tag);self.stack=self.stack[:index]


def _html_parts(page):
    raw=original_text(page)
    if raw is None or not re.search(r'<article\b',raw,re.I):return None
    parser=_ArticleHTML(raw,page.get('title',''))
    try:parser.feed(raw);parser.close()
    except Exception:return None
    if parser.articles!=1 or parser.h1_count!=1 or not parser.heading or 'article' in parser.stack:return None
    return parser.witnesses,'\n\n'.join(parser.body)


def _article(page):
    """Strict Markdown article structure; no inferred structure on flat text."""
    raw=original_text(page)
    if raw is None:return None
    title=_normal(page.get('title',''))
    headings=list(re.finditer(r'^#\s+([^\n]+)\n',raw,re.M))
    matching=[h for h in headings if _normal(h.group(1))==title]
    if len(matching)!=1:return None
    h=matching[0]
    stop=next((x.start() for x in headings if x.start()>h.start()),len(raw))
    article=raw[h.end():stop]
    # Explicit section boundaries are not publication or body authority.
    article=re.split(r'^#{1,6}\s+(?:related|recommended|navigation|more news|footer)\b',article,flags=re.M|re.I)[0]
    return article


def publication_witnesses(page):
    parts=_html_parts(page)
    if parts is not None:return parts[0]
    article=_article(page)
    if article is None:return []
    # Header-only definition/table relations with an explicit publication role.
    # A body paragraph, nearby event date, update or related story never qualifies.
    header=re.split(r'\n\s*\n(?=[^\s|#])',article.strip(),maxsplit=1)[0]
    if len(header)>2000:return []
    result=[]
    for line in header.splitlines():
        if (re.fullmatch(r'\s*\|\s*(?:published(?:\s+on)?|publication(?:\s+date)?)\s*\|\s*[^|\n]{4,150}\s*\|\s*',line,re.I)
                and not _UNSAFE_RELATION.search(line)):result.append(line.strip())
    return result


def body_context(page):
    parts=_html_parts(page)
    if parts is not None:return parts[1][:1800]
    article=_article(page)
    if article is None:return ''
    parts=re.split(r'\n\s*\n',article.strip())
    return '\n\n'.join(p for p in parts if not p.lstrip().startswith(('|','#','[','<')))[:1800]


def valid_body_passage(page,quote):
    parts=_html_parts(page)
    if parts is not None:
        return isinstance(quote,str) and 80<=len(quote)<=6000 and _normal(quote) in _normal(parts[1])
    article=_article(page)
    if not isinstance(quote,str) or not 80<=len(quote)<=6000 or article is None:return False
    # Only body paragraphs following header separation, never header/table/nav.
    parts=re.split(r'\n\s*\n',article.strip())
    body='\n\n'.join(p for p in parts if not p.lstrip().startswith(('|','#','[','<')))
    return _normal(quote) in _normal(body)
