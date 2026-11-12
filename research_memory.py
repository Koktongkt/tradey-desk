"""Exact-document research memory. Keys are work identities, not trade authority."""
from __future__ import annotations
import hashlib
import json
import re

_DOCUMENT_KEY = re.compile(r'rm1:[0-9a-f]{64}')


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('utf-8')


def _label(value) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > 256 or any(ord(c) < 32 for c in value)):
        raise ValueError('invalid_research_memory_label')
    return value


def document_key(*, issuer: str, representation: str, content: bytes,
                 rule_version: str, stage: str) -> str:
    if not isinstance(content, bytes) or not content:
        raise ValueError('complete_content_required')
    envelope = dict(version=1, issuer=_label(issuer), representation=_label(representation),
                    content_sha256=hashlib.sha256(content).hexdigest(),
                    rule_version=_label(rule_version), stage=_label(stage))
    return 'rm1:' + hashlib.sha256(_canonical(envelope)).hexdigest()


def bundle_key(*, issuer: str, document_keys: tuple[str, ...],
               rule_version: str, stage: str) -> str:
    if (not isinstance(document_keys, tuple) or not document_keys
            or any(not isinstance(k, str) or _DOCUMENT_KEY.fullmatch(k) is None
                   for k in document_keys)):
        raise ValueError('invalid_research_document_keys')
    envelope = dict(version=1, issuer=_label(issuer), documents=sorted(set(document_keys)),
                    rule_version=_label(rule_version), stage=_label(stage))
    return 'rb1:' + hashlib.sha256(_canonical(envelope)).hexdigest()
