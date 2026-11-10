"""Acquisition-owned SEC identity evidence, independent of article projections.

This module has no ledger or broker access. A hash authenticates retained bytes,
not a publisher: only the trusted exact-URL transport may construct captures.
Model/provider dictionaries cannot become IdentityCapture objects.
"""
from __future__ import annotations
import base64
from dataclasses import dataclass, field
import datetime as dt
from hashlib import sha256
import json

MAX_IDENTITY_SOURCE_BYTES = 2_000_000
MAX_IDENTITY_CAPTURE_BYTES = 3_000_000
_AUTHORITY = object()
_KEYS = frozenset({'kind','version','url','returned_url','content_type','source_sha256',
                   'body_b64','complete','acquired_at'})


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('duplicate_key')
        result[key]=value
    return result


def _constant(_): raise ValueError('invalid_constant')


@dataclass(frozen=True)
class IdentityCapture:
    canonical: bytes
    _seal: str = field(repr=False)
    _authority: object = field(repr=False,compare=False)

    @property
    def source_sha256(self): return _payload(self)['source_sha256']

    @property
    def url(self): return _payload(self)['url']

    @property
    def returned_url(self): return _payload(self)['returned_url']

    @property
    def retained_ref(self):
        return 'private/opportunity_evidence/'+sha256(self.canonical).hexdigest()+'.json'


def _decode(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_IDENTITY_CAPTURE_BYTES:
        raise ValueError('identity_capture_capacity')
    value=json.loads(raw,object_pairs_hook=_pairs,parse_constant=_constant)
    if not isinstance(value,dict) or set(value)!=_KEYS or _canonical(value)!=raw:
        raise ValueError('identity_capture_shape')
    if (value['kind']!='sec_identity_source' or type(value['version']) is not int
            or value['version']!=1 or value['complete'] is not True):
        raise ValueError('identity_capture_version')
    from opportunity_identity import _locator
    url,returned=value['url'],value['returned_url']
    if (not isinstance(url,str) or not isinstance(returned,str) or len(url)>4096
            or len(returned)>4096 or _locator(url) is None or _locator(url)!=_locator(returned)):
        raise ValueError('identity_capture_locator')
    if value['content_type'] not in ('text/html','application/xhtml+xml'):
        raise ValueError('identity_capture_media')
    if not isinstance(value['acquired_at'],str) or len(value['acquired_at'])>64:
        raise ValueError('identity_capture_time')
    if dt.datetime.fromisoformat(value['acquired_at']).utcoffset() is None:
        raise ValueError('identity_capture_time')
    if not isinstance(value['body_b64'],str): raise ValueError('identity_capture_body')
    body=base64.b64decode(value['body_b64'],validate=True)
    if (not 1<=len(body)<=MAX_IDENTITY_SOURCE_BYTES
            or base64.b64encode(body).decode('ascii')!=value['body_b64']
            or sha256(body).hexdigest()!=value['source_sha256']):
        raise ValueError('identity_capture_digest')
    body.decode('utf-8',errors='strict')
    return value,body


def _payload(value):
    if (not isinstance(value,IdentityCapture) or value._authority is not _AUTHORITY
            or type(value.canonical) is not bytes
            or sha256(value.canonical).hexdigest()!=value._seal):
        raise ValueError('trusted_identity_capture_required')
    return _decode(value.canonical)[0]


def capture_identity_source(url: str, raw: bytes, *, returned_url: str,
                            content_type: str) -> IdentityCapture:
    """Construct from a complete trusted transport response, never a model dict."""
    if type(raw) is not bytes or not 1<=len(raw)<=MAX_IDENTITY_SOURCE_BYTES:
        raise ValueError('identity_source_capacity')
    raw.decode('utf-8',errors='strict')
    if not isinstance(content_type,str): raise ValueError('identity_capture_media')
    value={'kind':'sec_identity_source','version':1,'url':url,'returned_url':returned_url,
           'content_type':content_type.split(';',1)[0].strip().lower(),
           'source_sha256':sha256(raw).hexdigest(),'body_b64':base64.b64encode(raw).decode('ascii'),
           'complete':True,'acquired_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    canonical=_canonical(value);_decode(canonical)
    return IdentityCapture(canonical,sha256(canonical).hexdigest(),_AUTHORITY)


def validate_identity_capture(value: IdentityCapture) -> bool:
    try: _payload(value); return True
    except (ValueError,TypeError,KeyError,UnicodeError,OverflowError): return False


def identity_source_bytes(value: IdentityCapture) -> bytes | None:
    if not validate_identity_capture(value): return None
    return _decode(value.canonical)[1]


def retain_identity_captures(root, captures: tuple[IdentityCapture, ...]) -> None:
    """Publish validated acquisition bytes privately before any ledger reference."""
    import os
    from pathlib import Path
    from opportunity_identity import _open_root, _private_child, _publish_capture
    if (not isinstance(captures,tuple) or not captures or len(captures)>32
            or not all(validate_identity_capture(c) for c in captures)):
        raise ValueError('trusted_identity_capture_required')
    payloads={Path(c.retained_ref).name:c.canonical for c in captures}
    root_fd=_open_root(root);private_fd=evidence_fd=None
    try:
        private_fd=_private_child(root_fd,'private')
        evidence_fd=_private_child(private_fd,'opportunity_evidence')
        for name,data in sorted(payloads.items()):
            _publish_capture(evidence_fd,name,data,max_bytes=MAX_IDENTITY_CAPTURE_BYTES)
    finally:
        for fd in (evidence_fd,private_fd,root_fd):
            if fd is not None:os.close(fd)


def resolve_earnings_capture(symbol: str, captures: tuple[IdentityCapture, ...]):
    from earnings_identity_resolution import resolve_earnings_capture as resolve
    return resolve(symbol,captures)
