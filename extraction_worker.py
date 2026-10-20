"""Bounded worker using project extraction; injected dispatch remains untrusted."""
from __future__ import annotations
import asyncio
from contextlib import redirect_stdout
from time import monotonic
import math
import json
import sys
from typing import Callable
from extraction_contract import is_error_document, strict_json_loads, strip_tool_footer

MAX_INPUT = 8192
MAX_BATCH_INPUT = 131_072
MAX_PROVIDER_RESPONSE = 100_000


def error(reason):
    return {'version': 1, 'status': 'error', 'reason': reason}


def declaration_failure(obj):
    """Public tool extension contract: absent declarations, or explicit success.

    Unknown informational extensions (e.g. metadata/policy markers) are ignored;
    success/status/error are never silently projected away. Only null/empty
    string mean no error, not Python's broader falsey values.
    """
    if 'blocked_by_policy' in obj:
        if type(obj['blocked_by_policy']) is not bool:
            return 'malformed_response'
        if obj['blocked_by_policy']:
            return 'provider_error'
    if 'error' in obj:
        value = obj['error']
        if value is not None and not isinstance(value, str):
            return 'malformed_response'
        if value:
            return 'provider_error'
    if 'success' in obj:
        if type(obj['success']) is not bool:
            return 'malformed_response'
        if not obj['success']:
            return 'provider_error'
    if 'status' in obj:
        if not isinstance(obj['status'], str) or obj['status'] not in {'ok', 'success', 'error', 'failed'}:
            return 'malformed_response'
        if obj['status'] in {'error', 'failed'}:
            return 'provider_error'
    return None


def provider_rows(raw):
    """Pure strict top-level projection shared by worker and focused receipts."""
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_PROVIDER_RESPONSE:
        return None, 'output_limit'
    try:
        payload = strict_json_loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        return None, 'malformed_response'
    if not isinstance(payload, dict):
        return None, 'malformed_response'
    reason = declaration_failure(payload)
    if reason:
        return None, reason
    rows = payload.get('results')
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return None, 'malformed_response'
    return rows, None


def project_row(row, guarded_location=False):
    """Project untrusted provider content; provenance is caller-owned only."""
    reason = declaration_failure(row)
    if reason:
        return error(reason)
    url, content, title = row.get('url'), row.get('content'), row.get('title', '')
    if not isinstance(url, str) or not 1 <= len(url) <= 4096 or not isinstance(content, str) or not isinstance(title, str):
        return error('malformed_response')
    content = strip_tool_footer(content)
    if not content.strip() or is_error_document(content, title):
        return error('empty_content')
    from publication_provenance import extraction_extensions
    extensions = extraction_extensions(row, url)
    if extensions is None:
        return error('malformed_response')
    page = {'url': url, 'title': title[:200], 'text': content[:6000], **extensions}
    if guarded_location:
        page['location_provenance'] = 'uncached_dispatch'
    return {'version': 1, 'status': 'ok', 'page': page}


async def extract(request, dispatch=None):
    if (not isinstance(request, dict) or type(request.get('version')) is not int
            or request['version'] != 1 or not isinstance(request.get('url'), str)
            or not 1 <= len(request['url']) <= 4096):
        return error('invalid_request')
    try:
        controlled = dispatch is None
        if controlled:
            from research_extraction import extract_tool
            timeout = request.get('timeout_seconds', 30)
            if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
                return error('invalid_request')
            raw = await extract_tool([request['url']], format='markdown', char_limit=6000,
                                     deadline=monotonic() + min(timeout, 30))
        else:
            raw = await dispatch([request['url']], format='markdown', char_limit=6000)
        rows, reason = provider_rows(raw)
        if reason:
            return error(reason)
        if rows is None or len(rows) != 1:
            return error('malformed_response')
        if controlled and rows[0].get('error'):
            from structured_extraction import ERROR_REASONS
            reason = rows[0].get('reason')
            return error(reason if isinstance(reason, str) and reason in ERROR_REASONS else 'provider_error')
        return project_row(rows[0], controlled)
    except asyncio.TimeoutError:
        return error('timeout')
    except Exception:
        return error('provider_error')


def batch_error(reason):
    return {'version': 2, 'status': 'error', 'reason': reason}


def valid_batch_request(request):
    """Shared admission, including serialized byte size (not character count)."""
    if (not isinstance(request, dict) or type(request.get('version')) is not int
            or request['version'] != 2 or not isinstance(request.get('urls'), list)
            or not 1 <= len(request['urls']) <= 5
            or any(not isinstance(u, str) or not 1 <= len(u) <= 4096 for u in request['urls'])):
        return False
    urls = request['urls']
    timeout = request.get('timeout_seconds', 30)
    if (len(set(urls)) != len(urls) or type(timeout) not in (int, float)
            or not math.isfinite(timeout) or timeout <= 0):
        return False
    try:
        if len(json.dumps(request, ensure_ascii=True, allow_nan=False).encode('utf-8')) > MAX_BATCH_INPUT:
            return False
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return False
    return True


async def extract_batch(request: dict, dispatch: Callable | None = None) -> dict:
    """Bind the entire set before projecting individual page/error envelopes.

    Only our dispatcher performs uncached location checks. Injected transports
    can supply content, never trusted provenance.
    """
    if not valid_batch_request(request):
        return batch_error('invalid_request')
    urls = request['urls']
    controlled = dispatch is None
    try:
        if controlled:
            from research_extraction import extract_tool
            raw = await extract_tool(urls, format='markdown', char_limit=6000,
                                     deadline=monotonic() + min(request.get('timeout_seconds', 30), 30))
        else:
            raw = await dispatch(urls, format='markdown', char_limit=6000)
        rows, reason = provider_rows(raw)
        if reason:
            return batch_error(reason)
        if rows is None or len(rows) != len(urls):
            return batch_error('malformed_response')
        if controlled and all(r.get('url') == '' and r.get('error') for r in rows):
            # Dispatcher admission errors deliberately redact unchecked identities.
            from structured_extraction import ERROR_REASONS
            reasons = [r.get('reason') for r in rows]
            if isinstance(reasons[0], str) and reasons[0] in ERROR_REASONS and all(r == reasons[0] for r in reasons):
                return batch_error(reasons[0])
        bound = {}
        for row in rows:
            loc = row.get('extraction_location')
            key = loc.get('requested_url') if isinstance(loc, dict) else row.get('url')
            if not isinstance(key, str) or key not in urls or key in bound:
                return batch_error('url_mismatch')
            if 'extraction_location' in row:
                from publication_provenance import extraction_extensions
                # Validate just transport identity here; bad page metadata stays
                # a row error and cannot erase independently successful siblings.
                if extraction_extensions({'extraction_location': loc}, row.get('url'), key) is None:
                    return batch_error('url_mismatch')
            if row.get('url') in urls and row['url'] != key:
                return batch_error('url_mismatch')
            bound[key] = row
        results = []
        for key in urls:
            row = bound[key]
            if controlled and row.get('error'):
                from structured_extraction import ERROR_REASONS
                reason = row.get('reason')
                result = error(reason if isinstance(reason, str) and reason in ERROR_REASONS else 'provider_error')
            else:
                result = project_row(row, controlled)
            results.append({'requested_url': key, 'result': result})
        # The dispatcher encodes fatal protocol refusals as one error per key.
        # Collapse only an all-error protocol refusal, never a mixed batch or
        # ordinary per-page provider failures.
        if controlled:
            reason = results[0]['result'].get('reason')
            if (reason in ('invalid_request', 'malformed_response', 'url_mismatch', 'output_limit')
                    and all(r['result'].get('reason') == reason for r in results)):
                return batch_error(reason)
        out = {'version': 2, 'status': 'ok', 'results': results}
        if len(json.dumps(out, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('utf-8')) > MAX_PROVIDER_RESPONSE:
            return batch_error('output_limit')
        return out
    except asyncio.TimeoutError:
        return batch_error('timeout')
    except Exception:
        return batch_error('provider_error')


def main():
    out = error('invalid_request')
    fail = error
    try:
        raw = sys.stdin.buffer.read(MAX_BATCH_INPUT + 1)
        if len(raw) <= MAX_BATCH_INPUT:
            try:
                request = strict_json_loads(raw)
            except (ValueError, UnicodeError, RecursionError):
                # Preserve v1's byte admission, even for unparseable input.
                out = error('invalid_request' if len(raw) > MAX_INPUT else 'malformed_response')
            else:
                batch = isinstance(request, dict) and type(request.get('version')) is int and request['version'] == 2
                fail = batch_error if batch else error
                out = fail('invalid_request')
                timeout = request.get('timeout_seconds', 30) if isinstance(request, dict) else 30
                admitted = valid_batch_request(request) if batch else len(raw) <= MAX_INPUT
                if (admitted and type(timeout) in (int, float) and math.isfinite(timeout)
                        and timeout > 0 and (batch or timeout <= 30)):
                    async def bounded():
                        return await asyncio.wait_for(extract_batch(request) if batch else extract(request),
                                                      timeout=min(timeout, 30))
                    # Provider chatter cannot become an envelope. Parent caps stderr.
                    with redirect_stdout(sys.stderr):
                        out = asyncio.run(bounded())
    except asyncio.TimeoutError:
        out = fail('timeout')
    except Exception:
        pass
    sys.stdout.write(json.dumps(out, ensure_ascii=True, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    main()
