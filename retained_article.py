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
        self.header_closed=False;self.body_closed=False;self.blocked_depths=[]
        self.h1_end=None;self.header_stop=None
        self.label=[];self.dt_start=None;self.dt_end=None;self.pair=False
        self.paragraph=None;self.body=[];self.witnesses=[]
        self.lines=[0]
        for line in raw.splitlines(keepends=True):self.lines.append(self.lines[-1]+len(line))
    def _position(self):
        row,col=self.getpos();return self.lines[row-1]+col
    def eligible(self):
        if 'article' not in self.stack or self.blocked_depths:return False
        inner=self.stack[len(self.stack)-1-self.stack[::-1].index('article')+1:]
        return not any(t in inner for t in ('nav','aside','footer','script','style','section','h2','h3','h4','h5','h6'))
    def handle_starttag(self,tag,attrs):
        nested='article' in self.stack
        if tag=='article':self.articles+=1
        self.stack.append(tag)
        if nested:
            if tag in ('p','section','h2','h3','h4','h5','h6') and self.heading and self.header_stop is None:self.header_stop=self._position()
            if tag in ('section','h2','h3','h4','h5','h6'):self.header_closed=True
            if tag in ('h2','h3','h4','h5','h6'):self.body_closed=True
            if any((k in ('class','id','aria-label') and isinstance(v,str) and re.search(r'related|recommended|event[-_ ]?detail|navigation|more[-_ ]news',v,re.I))
                    or (k=='role' and v in ('region','complementary','navigation','article')) for k,v in attrs):
                self.blocked_depths.append(len(self.stack));self.header_closed=True
                self.pair=False
                if self.header_stop is None:self.header_stop=self._position()
        if not self.eligible():return
        if tag=='h1':self.h1=[];self.h1_count+=1
        elif tag=='p' and self.heading and not self.body_closed:self.body_started=True;self.paragraph=[]
        elif tag=='dt' and self.heading and not self.body_started and not self.header_closed:
            self.dt_start=self._position();self.label=[];self.dt_end=None
        elif tag=='dd' and self.heading and not self.body_started and not self.header_closed:
            self.pair=(self.dt_end is not None and not self.raw[self.dt_end:self._position()].strip()
                       and bool(re.fullmatch(r'published(?:\s+on)?|publication(?:\s+date)?',_normal(''.join(self.label)),re.I)))
    def handle_data(self,data):
        if not self.eligible():return
        if 'h1' in self.stack:self.h1.append(data)
        if 'dt' in self.stack:self.label.append(data)
        if self.paragraph is not None and 'p' in self.stack and not self.body_closed:self.paragraph.append(data)
    def handle_endtag(self,tag):
        if self.eligible():
            if tag=='h1':
                self.heading=_normal(''.join(self.h1))==self.title
                self.h1_end=self.raw.find('>',self._position())+1
            elif tag=='dt':self.dt_end=self.raw.find('>',self._position())+1
            elif tag=='dd' and self.pair and self.dt_start is not None:
                end=self.raw.find('>',self._position())+1;span=self.raw[self.dt_start:end]
                if len(span)<=2000 and not _UNSAFE_RELATION.search(span):self.witnesses.append(span)
                self.pair=False
            elif tag=='p' and self.paragraph is not None:
                self.body.append(''.join(self.paragraph));self.paragraph=None
        if tag in self.stack:
            index=len(self.stack)-1-self.stack[::-1].index(tag);self.stack=self.stack[:index]
            self.blocked_depths=[depth for depth in self.blocked_depths if depth<=len(self.stack)]


def _html_parts(page):
    raw=original_text(page)
    if raw is None or not re.search(r'<article\b',raw,re.I):return None
    parser=_ArticleHTML(raw,page.get('title',''))
    try:parser.feed(raw);parser.close()
    except Exception:return None
    if parser.articles!=1 or parser.h1_count!=1 or not parser.heading or 'article' in parser.stack:return None
    end=parser.header_stop if parser.header_stop is not None else len(raw)
    return parser.witnesses,'\n\n'.join(parser.body),raw[parser.h1_end:end] if parser.h1_end is not None else ''


def _recommendation_boundary(line):
    """Recognize label families independently of nested Markdown containers."""
    plain=re.sub(r'<[^>]+>',' ',html.unescape(line))
    plain=re.sub(r'[*_~`]','',plain)
    # Inspect every table cell, not just a particular column/pipe count.
    for cell in plain.split('|'):
        label=cell.lstrip()
        # Each iteration consumes a nonempty token. Excessive nesting is
        # ambiguous ownership and terminates scope rather than gaining authority.
        for _ in range(32):
            token=re.match(r'(?:>\s*|[-+]\s*|\d+[.)]\s*|\[[ xX]?\]\s*|\[)',label)
            if token is None:break
            label=label[token.end():].lstrip()
        else:return True
        if re.match(r'(?:related|recommend(?:ed|ations?)|more\s+(?:news|stories|from)|you\s+may\s+also\s+like)\b',label,re.I):return True
    return False


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
    # Only the current article's direct header/intro scope is witnessed. A nested
    # section may describe a different event/article even if its date says Published.
    article=re.split(r'^#{1,6}\s+',article,flags=re.M)[0]
    # All body/header consumers share this owned scope; the full original stays
    # available separately for document-global conflict and refusal checks.
    offset=0
    for line in article.splitlines(keepends=True):
        if _recommendation_boundary(line):
            article=article[:offset];break
        offset+=len(line)
    return article


_PUBLICATION_ROW=re.compile(r'\s*\|\s*(?:published(?:\s+on)?|publication(?:\s+date)?)\s*\|\s*[^|\n]{4,150}\s*\|\s*',re.I)


def _markdown_header(page):
    """One positive-authority scope shared by legacy contexts and witnesses."""
    article=_article(page)
    if article is None:return ''
    header=re.split(r'\n\s*\n',article.strip(),maxsplit=1)[0]
    if len(header)>2000 or _UNSAFE_RELATION.search(header):return ''
    lines=[line.strip() for line in header.splitlines() if line.strip()]
    # Unknown table rows are not header authority: they may describe another
    # article or event. Do not infer publication ownership from an isolated row.
    separator=r'\|\s*:?-+:?\s*\|\s*:?-+:?\s*\|'
    if (lines and any(_PUBLICATION_ROW.fullmatch(line) for line in lines)
            and all(_PUBLICATION_ROW.fullmatch(line) or re.fullmatch(separator,line) for line in lines)):
        return header
    publication=r'(?:published(?:\s+on)?|publication(?:\s+date)?)\s*[:：]?\s+[^\n]+'
    if lines and all(re.fullmatch(publication,line,re.I) for line in lines):return header
    return ''


def publication_witnesses(page):
    parts=_html_parts(page)
    if parts is not None:return parts[0]
    header=_markdown_header(page)
    return [line.strip() for line in header.splitlines() if _PUBLICATION_ROW.fullmatch(line)]


def visible_header_text(page):
    parts=_html_parts(page)
    return parts[2] if parts is not None else _markdown_header(page)


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
