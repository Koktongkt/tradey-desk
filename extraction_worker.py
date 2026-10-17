"""Project-owned worker. Imports only the configured Hermes extraction dispatcher.

Public web_extract intentionally trims metadata. Keep that routing/rescue/safety
contract intact: publication provenance is recovered from visible content by the
parent, never from cache/crawl timestamps or guessed provider metadata. A local
legacy-cache read guard prevents Reuters URL-year inference from cache-rebound
locations; it does not attest to network freshness or provider-internal caches.
"""
from __future__ import annotations
import asyncio
from contextlib import contextmanager, redirect_stdout
from urllib.parse import urlparse
import json
import sys
from extraction_contract import is_error_document, strict_json_loads, strip_tool_footer

MAX_INPUT = 8192
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


@contextmanager
def final_location_cache_guard():
    """Isolated-worker-only compatibility guard for the legacy Hermes cache.

    Its Reuters entries have no final-location provenance (even when newly
    written). Treat those reads as misses; leave writes and every other host
    alone. The dispatcher still owns routing, policy, URL safety and rescue.
    One request runs per worker process; this is not a shared-server hook.
    """
    from tools import web_result_cache
    original = web_result_cache.extract_cache_get

    def guarded(url, *args, **kwargs):
        host = (urlparse(url).hostname or '').lower()
        if host == 'reuters.com' or host.endswith('.reuters.com'):
            return None
        return original(url, *args, **kwargs)

    web_result_cache.extract_cache_get = guarded
    try:
        yield
    finally:
        web_result_cache.extract_cache_get = original


async def extract(request, dispatch=None):
    if (not isinstance(request, dict) or type(request.get('version')) is not int
            or request['version'] != 1 or not isinstance(request.get('url'), str)
            or not 1 <= len(request['url']) <= 4096):
        return error('invalid_request')
    try:
        guarded_location = False
        if dispatch is None:
            from tools.web_tools import web_extract_tool
            host = (urlparse(request['url']).hostname or '').lower()
            guarded_location = host == 'reuters.com' or host.endswith('.reuters.com')
            with final_location_cache_guard():
                raw = await web_extract_tool([request['url']], format='markdown', char_limit=6000)
        else:
            raw = await dispatch([request['url']], format='markdown', char_limit=6000)
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_PROVIDER_RESPONSE:
            return error('output_limit')
        try:
            payload = strict_json_loads(raw)
        except ValueError:
            return error('malformed_response')
        if not isinstance(payload, dict):
            return error('malformed_response')
        reason = declaration_failure(payload)
        if reason:
            return error(reason)
        rows = payload.get('results')
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            return error('malformed_response')
        row = rows[0]
        reason = declaration_failure(row)
        if reason:
            return error(reason)
        url, content, title = row.get('url'), row.get('content'), row.get('title', '')
        if not isinstance(url, str) or not 1 <= len(url) <= 4096 or not isinstance(content, str) or not isinstance(title, str):
            return error('malformed_response')
        content = strip_tool_footer(content)
        if not content.strip() or is_error_document(content, title):
            return error('empty_content')
        page = {'url': url, 'title': title[:200], 'text': content[:6000]}
        if guarded_location:
            page['location_provenance'] = 'uncached_dispatch'
        return {'version': 1, 'status': 'ok', 'page': page}
    except asyncio.TimeoutError:
        return error('timeout')
    except Exception:
        return error('provider_error')


def main():
    out = error('invalid_request')
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) <= MAX_INPUT:
            try:
                request = strict_json_loads(raw)
            except (ValueError, UnicodeError, RecursionError):
                sys.stdout.write(json.dumps(error('malformed_response')) + '\n')
                return
            timeout = request.get('timeout_seconds', 30) if isinstance(request, dict) else 30
            if type(timeout) in (int, float) and 0 < timeout <= 30:
                async def bounded():
                    return await asyncio.wait_for(extract(request), timeout=timeout)
                # Provider chatter cannot become an envelope. Parent separately caps stderr.
                with redirect_stdout(sys.stderr):
                    out = asyncio.run(bounded())
    except asyncio.TimeoutError:
        out = error('timeout')
    except Exception:
        pass
    sys.stdout.write(json.dumps(out, ensure_ascii=True, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    main()
