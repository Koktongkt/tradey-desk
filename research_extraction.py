"""Uncached project extraction: one primary and at most one anonymous ring.

Only extraction_compat may import Hermes helpers. This dispatcher never patches
providers, reads/writes result caches, spills full text, or makes date requests.
Await budgets share one monotonic deadline; synchronous provider/DNS lifetime
still requires the isolated research parent's hard deadline.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
from time import monotonic
from urllib.parse import urlsplit

import extraction_compat as compat
from extraction_contract import is_error_document, strip_tool_footer
from publication_provenance import extraction_extensions, publication_conflicts

MAX_ENVELOPE_BYTES = 100_000
MIN_EXTRACT_CHARS = 2000
MAX_EXTRACT_CHARS = 6000
DEFAULT_EXTRACT_CHARS = MAX_EXTRACT_CHARS
MAX_EXTRACT_URLS = 5


class _Failure(Exception):
    def __init__(self, reason):
        self.reason = reason


def _compat_reason(reason):
    # Compatibility vocabulary is not the worker's public vocabulary.
    return {'invalid_url': 'invalid_request', 'secret_url': 'unsafe_url',
            'policy_blocked': 'provider_error', 'unsafe_url': 'unsafe_url',
            'provider_error': 'provider_error', 'malformed_response': 'malformed_response'}.get(reason, 'provider_error')


def _remaining(deadline):
    left = deadline - monotonic()
    if left <= 0:
        raise TimeoutError
    return left


async def _bounded(call, deadline):
    # Accept a factory: no coroutine/network attempt is created after expiry.
    left = _remaining(deadline)
    value = await asyncio.wait_for(call(), timeout=left)
    _remaining(deadline)
    return value


def _error(url, reason):
    return {'url': url, 'title': '', 'content': '', 'error': reason, 'reason': reason}


def _envelope(rows):
    raw = json.dumps({'results': rows}, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
    if len(raw.encode('utf-8')) > MAX_ENVELOPE_BYTES:
        # Escaped Unicode request keys can themselves exhaust an error envelope.
        # Never truncate a key into a different identity; omit it on this failure.
        raw = json.dumps({'results': [_error('', 'output_limit') for _ in rows]},
                         separators=(',', ':'))
    return raw


def _size(rows):
    try:
        raw = json.dumps({'results': rows}, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
        if len(raw.encode('utf-8')) > MAX_ENVELOPE_BYTES:
            raise _Failure('output_limit')
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise _Failure('malformed_response') from None


async def _bind(rows, originals, normalized, deadline):
    """Bind identities before declarations/rescue. Never zip results to requests.

    A redirect in a multi-request batch needs an explicit location binding.
    A singleton can be unambiguous without it, but conflicting source claims
    remain invalid. sourceURL describes the returned page, not a substitute URL.
    """
    if (not isinstance(rows, list) or len(rows) != len(originals)
            or not all(isinstance(r, dict) for r in rows)):
        raise _Failure('malformed_response')
    _size(rows)  # Bound the full untrusted envelope before dropping extensions.
    bound = {}
    for row in rows:
        returned = row.get('url')
        if not isinstance(returned, str) or not 1 <= len(returned) <= 4096:
            raise _Failure('malformed_response')
        safe = await _bounded(lambda: compat.check_url(returned), deadline)
        for container in (row, row.get('metadata', {})):
            if isinstance(container, dict) and 'sourceURL' in container:
                claim = container['sourceURL']
                if not isinstance(claim, str) or not 1 <= len(claim) <= 4096:
                    raise _Failure('url_mismatch')
                identity = await _bounded(lambda: compat.check_url(claim), deadline)
                if identity != safe:
                    raise _Failure('url_mismatch')
        # Validate declared publication before any error can admit rescue/walking.
        # Its required transport location must exist, not be synthesized below.
        if 'publication' in row and extraction_extensions(row, returned) is None:
            raise _Failure('malformed_response')
        loc = row.get('extraction_location')
        if 'extraction_location' in row:
            if (not isinstance(loc, dict) or set(loc) != {'version', 'requested_url', 'returned_url'}
                    or type(loc['version']) is not int or loc['version'] != 1
                    or loc['returned_url'] != returned
                    or not isinstance(loc['requested_url'], str)
                    or not 1 <= len(loc['requested_url']) <= 4096):
                raise _Failure('url_mismatch')
            requested = await _bounded(lambda: compat.check_url(loc['requested_url']), deadline)
            if requested not in normalized:
                raise _Failure('url_mismatch')
            index = normalized.index(requested)
            # A result claiming another requested page's transport URL conflicts.
            if safe in normalized and normalized.index(safe) != index:
                raise _Failure('url_mismatch')
        elif safe in normalized:
            index = normalized.index(safe)
        elif len(originals) == 1:
            index = 0
        else:
            raise _Failure('malformed_response')
        if index in bound:
            raise _Failure('malformed_response')
        from alpha_radar import publisher_domain
        if publisher_domain(safe) != publisher_domain(normalized[index]):
            raise _Failure('url_mismatch')
        if publisher_domain(safe) == 'reuters.com':
            dates = [re.search(r'(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)', urlsplit(u).path)
                     for u in (normalized[index], safe)]
            if all(dates) and dates[0].group(1) != dates[1].group(1):
                raise _Failure('url_mismatch')
        bound[index] = row
    if len(bound) != len(originals):
        raise _Failure('malformed_response')
    return [bound[i] for i in range(len(originals))]


def _truncate(content, limit):
    if len(content) <= limit:
        return content
    marker = '\n[... middle omitted — see footer ...]\n'
    footer = '\n─── [TRUNCATED] Bounded head/tail; full text not stored.'
    available = limit - len(marker) - len(footer)
    head = (available * 2) // 3
    return content[:head] + marker + content[-(available - head):] + footer


def _project(row, original, limit):
    # Lazy import prevents the eventual worker -> dispatcher dependency cycling.
    from extraction_worker import declaration_failure
    if isinstance(row, compat._TransportFailure):
        # Already subjected to normal size and exact-request binding in _bind.
        return _error(original, row.reason)
    for field in ('error', 'success', 'status', 'blocked_by_policy'):
        if field in row and declaration_failure({field: row[field]}) == 'malformed_response':
            return _error(original, 'malformed_response')
    reason = declaration_failure(row)
    if reason:
        return _error(original, reason)
    content, title = row.get('content'), row.get('title', '')
    if not isinstance(content, str) or not isinstance(title, str):
        return _error(original, 'malformed_response')
    content = strip_tool_footer(content)
    if not content.strip() or is_error_document(content, title):
        return _error(original, 'empty_content')
    if (re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', content)
            or content.lstrip().startswith(('%PDF-', '\x89PNG', 'GIF87a', 'GIF89a', 'PK\x03\x04'))):
        return _error(original, 'empty_content')
    # Eliminate embedded image payloads before text bounding; no decoding/files.
    content = re.sub(r'!?\[[^\]\n]*\]\(data:image/[^)]*\)', '[image omitted]', content, flags=re.I)
    content = re.sub(r'''(["'])data:image/.*?\1''', r'\1[image omitted]\1', content, flags=re.I | re.S)
    content = re.sub(r'data:image/[^\s\"\'<>)]*', '[image omitted]', content, flags=re.I)
    if re.search(r'(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{256,}={0,2}(?![A-Za-z0-9+/])', content):
        return _error(original, 'empty_content')
    location = {'version': 1, 'requested_url': original, 'returned_url': row['url']}
    # The location was checked before rebinding to the exact original key.
    extensions = extraction_extensions({**row, 'extraction_location': location}, row['url'], original)
    if extensions is None:
        return _error(original, 'malformed_response')
    from alpha_radar import extract_published_at, extract_gateway_publication_date
    article, precision = extract_published_at(content, with_precision=True)
    visible = extract_gateway_publication_date(row['url'], content, allow_url_year=True)
    if (article and visible and publication_conflicts({'value': article}, visible, day_only=True)
            or publication_conflicts(extensions.get('publication'), article or visible,
                                     day_only=precision == 'day' if article else True)):
        return _error(original, 'malformed_response')
    return {'url': row['url'], 'title': title[:200], 'content': _truncate(content, limit),
            'error': None, **extensions}


def _policy_refusal(rows):
    return any(r.get('blocked_by_policy') is True
               or isinstance(r.get('error'), str) and 'blocked by website policy' in r['error'].lower()
               for r in rows)


async def extract_tool(urls: list, format: str | None = None, char_limit: int | None = None,
                       *, deadline: float | None = None) -> str:
    """Return a bounded JSON tool envelope, without shared caches or nested rescue."""
    format = 'markdown' if format is None else format
    char_limit = DEFAULT_EXTRACT_CHARS if char_limit is None else char_limit
    originals = urls if isinstance(urls, list) and 1 <= len(urls) <= MAX_EXTRACT_URLS else ['']
    admitted = False

    def fail(reason, *, redact_urls=False):
        # Unchecked identities may carry credentials, including when the
        # required secret detector is unsupported or admission times out.
        redact_urls = redact_urls or not admitted
        rows = [_error(u if isinstance(u, str) and len(u) <= 4096 else '', reason)
                for u in originals]
        if redact_urls:
            # Retain the existing encoded-envelope overflow classification even
            # when privacy requires omitting all unchecked request identities.
            try:
                _size(rows)
            except _Failure as exc:
                reason = exc.reason
            rows = [_error('', reason) for _ in originals]
        return _envelope(rows)
    if (not isinstance(urls, list) or not 1 <= len(urls) <= MAX_EXTRACT_URLS
            or any(not isinstance(u, str) or not 1 <= len(u) <= 4096 for u in urls)
            or not isinstance(format, str) or format not in ('markdown', 'html')
            or type(char_limit) is not int or not MIN_EXTRACT_CHARS <= char_limit <= MAX_EXTRACT_CHARS
            or (deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)))):
        return fail('invalid_request')
    deadline = monotonic() + 30 if deadline is None else deadline
    try:
        normalized = []
        for url in originals:
            normalized.append(await _bounded(lambda: compat.check_url(url), deadline))
        admitted = True
        if len(set(normalized)) != len(normalized):
            return fail('invalid_request')
        _remaining(deadline)
        provider = compat.resolve()
        anonymous = compat.uses_keyless(provider)

        async def consume(rows):
            rows = await _bind(rows, originals, normalized, deadline)
            projected = [_project(r, u, char_limit) for r, u in zip(rows, originals)]
            _remaining(deadline)
            _size(projected)
            return rows, projected

        if not anonymous:
            try:
                raw = await _bounded(lambda: compat.primary(
                    provider, normalized, format=format, deadline=deadline), deadline)
            except compat.CompatibilityError as exc:
                # Only transport failure admits rescue, never a safety/binding
                # failure raised while validating a successful response.
                if exc.reason != 'provider_error' or not compat.rescue_allowed(provider):
                    raise
            else:
                raw, projected = await consume(raw)
                # No partial-result replay, no malformed/policy/empty-body rescue.
                if (not all(r.get('reason') == 'provider_error' for r in projected)
                        or _policy_refusal(raw) or not compat.rescue_allowed(provider)):
                    return _envelope(projected)
            # A direct vendor and its anonymous endpoint count as one attempt.
        order = compat.ring_order(getattr(provider, 'name', ''))
        if not anonymous:
            order = [v for v in order if v != getattr(provider, 'name', '')]
        projected = [_error(u, 'provider_error') for u in originals]
        for vendor in order:
            raw = await _bounded(lambda: compat.keyless(vendor, normalized, deadline=deadline), deadline)
            raw, projected = await consume(raw)
            # Installed extraction semantics: EVERY row must be rate-limited.
            # Strict/malformed declarations never become a free-walk admission.
            if (any(r.get('reason') != 'provider_error' for r in projected)
                    or _policy_refusal(raw) or not compat.rate_limited(raw)):
                break
        return _envelope(projected)
    except _Failure as exc:
        return fail(exc.reason)
    except compat.CompatibilityError as exc:
        return fail(_compat_reason(exc.reason), redact_urls=exc.reason == 'secret_url')
    except TimeoutError:
        return fail('timeout')
    except Exception:
        return fail('provider_error')
