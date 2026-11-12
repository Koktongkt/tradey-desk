"""Event-independent immutable private evidence/results; no admission authority."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from retained_article import original_text
from opportunity_identity import _open_root, _private_child, _publish_capture

MAX_BYTES=3_000_000
_DIRECTORY='research_evidence'
_DIGEST=re.compile(r'[0-9a-f]{64}')


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',', ':'),ensure_ascii=True,
                      allow_nan=False).encode('utf-8')


@contextmanager
def _directory(root, *, create):
    fds=[]
    try:
        fds.append(_open_root(root))
        for name in ('private',_DIRECTORY):
            if create:fd=_private_child(fds[-1],name)
            else:
                fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fds[-1])
                st=os.fstat(fd)
                if st.st_uid!=os.geteuid() or stat.S_IMODE(st.st_mode)!=0o700:
                    os.close(fd);raise OSError('unsafe_research_evidence_directory')
            fds.append(fd)
        yield fds[-1]
    finally:
        for fd in reversed(fds):os.close(fd)


def _retain(root, payload, *, representation, content_sha256):
    data=_canonical(payload)
    if len(data)>MAX_BYTES:raise ValueError('research_evidence_capacity')
    digest=hashlib.sha256(data).hexdigest();name=digest+'.json'
    with _directory(root,create=True) as fd:
        _publish_capture(fd,name,data,max_bytes=MAX_BYTES)
    return dict(path='private/'+_DIRECTORY+'/'+name,sha256=digest,
                representation=representation,content_sha256=content_sha256)


def retain_page(root: Path, page: dict) -> dict:
    text=original_text(page)
    if text is None or page.get('returned_url',page.get('url'))!=page.get('url'):
        raise ValueError('complete_owned_representation_required')
    return _retain(root,dict(version=1,kind='article',capture=page['_retained_article']),
                   representation='provider:text:v1',content_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())


def retain_result(root: Path, result: dict) -> dict:
    if not isinstance(result,dict):raise ValueError('research_result_required')
    content=_canonical(result)
    return _retain(root,dict(version=1,kind='result',result=result),representation='research:result:v1',
                   content_sha256=hashlib.sha256(content).hexdigest())


def _read(root, ref):
    if (not isinstance(ref,dict) or set(ref)!={'path','sha256','representation','content_sha256'}
        or any(not isinstance(ref[k],str) for k in ref)
        or _DIGEST.fullmatch(ref['sha256']) is None
        or _DIGEST.fullmatch(ref['content_sha256']) is None
        or ref['path']!='private/'+_DIRECTORY+'/'+ref['sha256']+'.json'):
        raise ValueError('invalid_research_evidence_reference')
    with _directory(root,create=False) as directory:
        fd=os.open(ref['sha256']+'.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
        try:
            st=os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode)!=0o600
                    or st.st_uid!=os.geteuid() or st.st_nlink!=1 or st.st_size>MAX_BYTES):
                raise OSError('unsafe_research_evidence_file')
            with os.fdopen(fd,'rb',closefd=False) as f:data=f.read(MAX_BYTES+1)
        finally:os.close(fd)
    if len(data)>MAX_BYTES or hashlib.sha256(data).hexdigest()!=ref['sha256']:
        raise ValueError('research_evidence_digest_mismatch')
    obj=json.loads(data)
    if not isinstance(obj,dict) or obj.get('version')!=1 or _canonical(obj)!=data:
        raise ValueError('invalid_research_evidence')
    return obj


def read_capture(root: Path, ref: dict) -> bytes:
    value=_read(root,ref)
    if set(value)!={'version','kind','capture'} or value['kind']!='article' or ref['representation']!='provider:text:v1':
        raise ValueError('research_capture_kind_mismatch')
    c=value['capture']
    if not isinstance(c,dict):raise ValueError('invalid_research_capture')
    page=dict(url=c.get('url'),returned_url=c.get('returned_url'),title=c.get('title'),
              text='',_retained_article=c)
    # Verify the complete representation using its saved projection digest, not
    # manufacture a projected text to satisfy original_text's binding check.
    from retained_article import KEYS
    if (set(c)!=KEYS or type(c['version']) is not int or c['version']!=1
        or not isinstance(c['text'],str) or not c['text'].strip()
        or c['url']!=c['returned_url'] or type(c['metadata_omitted']) is not bool
        or not isinstance(c['reported_metadata'],dict)
        or hashlib.sha256(json.dumps(c['reported_metadata'],sort_keys=True,ensure_ascii=True,allow_nan=False).encode()).hexdigest()!=c['metadata_sha256']):
        raise ValueError('invalid_research_capture')
    data=c['text'].encode('utf-8')
    if hashlib.sha256(data).hexdigest()!=ref['content_sha256'] or c['sha256']!=ref['content_sha256']:
        raise ValueError('research_content_digest_mismatch')
    return data


def read_result(root: Path, ref: dict) -> dict:
    value=_read(root,ref)
    if (set(value)!={'version','kind','result'} or value['kind']!='result'
        or ref['representation']!='research:result:v1' or not isinstance(value['result'],dict)
        or hashlib.sha256(_canonical(value['result'])).hexdigest()!=ref['content_sha256']):
        raise ValueError('invalid_research_result')
    return value['result']
