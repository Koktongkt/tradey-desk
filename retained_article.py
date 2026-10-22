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
KEYS={'version','url','returned_url','title','text','sha256','projection_sha256'}


def _digest(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()


def retain_article(page,text):
    result={k:v for k,v in page.items() if k not in ('_retained_article','_capture_status')}
    if not isinstance(text,str) or not text.strip():
        result['_capture_status']='missing';return result
    try:
        capture={'version':1,'url':page['url'],'returned_url':page.get('returned_url',page['url']),
                 'title':page.get('title',''),'text':text,'sha256':_digest(text),
                 'projection_sha256':_digest(page['text'])}
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
                or not all(isinstance(c[k],str) for k in KEYS-{'version'})
                or c['url']!=page['url'] or c['returned_url']!=page.get('returned_url',page['url'])
                or c['title']!=page.get('title','') or c['projection_sha256']!=_digest(page['text'])
                or c['sha256']!=_digest(c['text'])
                or len(json.dumps(c,ensure_ascii=True,allow_nan=False).encode())>MAX_CAPTURE_BYTES):return None
        return c['text']
    except (KeyError,TypeError,ValueError,UnicodeError):return None


def _normal(text):return ' '.join(html.unescape(text).split()).strip()


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
    article=_article(page)
    if article is None:return []
    # Header-only definition/table relations with an explicit publication role.
    # A body paragraph, nearby event date, update or related story never qualifies.
    header=re.split(r'\n\s*\n(?=[^\s|#])',article.strip(),maxsplit=1)[0]
    if len(header)>2000:return []
    result=[]
    for line in header.splitlines():
        if re.fullmatch(r'\s*\|\s*(?:published(?:\s+on)?|publication(?:\s+date)?)\s*\|\s*[^|\n]{4,150}\s*\|\s*',line,re.I):result.append(line.strip())
    return result


def valid_body_passage(page,quote):
    article=_article(page)
    if not isinstance(quote,str) or not 80<=len(quote)<=6000 or article is None:return False
    # Only body paragraphs following header separation, never header/table/nav.
    parts=re.split(r'\n\s*\n',article.strip())
    body='\n\n'.join(p for p in parts if not p.lstrip().startswith(('|','#','[','<')))
    return _normal(quote) in _normal(body)
