"""Read-only Hermes boundary for project-owned extraction.

No cache, rescue, ring walking, publication inference, or provider monkeypatches.
Deadlines bound awaits, NOT the lifetime of synchronous worker threads/DNS: the
research subprocess's parent must enforce the hard deadline (Task 4).
Custom providers must explicitly declare ``uses_keyless() -> bool``; an absent
relationship declaration is unsupported rather than assumed safe to rescue.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import ipaddress
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

_RING = ('exa', 'parallel', 'firecrawl', 'keenable')
_KEYS = {'exa': 'EXA_API_KEY', 'parallel': 'PARALLEL_API_KEY',
         'keenable': 'KEENABLE_API_KEY'}
_DIRECT = (*_RING, 'tavily')


class CompatibilityError(RuntimeError):
    """Stable project reason; do not expose upstream exceptions/secrets."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _module(name) -> Any:
    return importlib.import_module(name)


def _function(module, name, *args, **kwargs) -> Callable[..., Any]:
    try:
        fn = getattr(_module(module), name)
        inspect.signature(fn).bind(*args, **kwargs)
        if not callable(fn):
            raise TypeError
        return fn
    except Exception as exc:
        raise CompatibilityError('provider_error') from exc


def _call(module, name, *args, **kwargs) -> Any:
    fn = _function(module, name, *args, **kwargs)
    try:
        return fn(*args, **kwargs)
    except CompatibilityError:
        raise
    except Exception as exc:
        raise CompatibilityError('provider_error') from exc


def _config():
    config = _call('hermes_cli.config', 'load_config')
    # Hermes serves defaults/LKG as a dict subclass on read/parse failure.
    # Those settings are not authority for provider, policy, or free admission.
    if not isinstance(config, dict) or hasattr(config, 'read_error'):
        raise CompatibilityError('provider_error')
    return config


def _web():
    web = _config().get('web') or {}
    if not isinstance(web, dict):
        raise CompatibilityError('provider_error')
    return web


def _enabled(key):
    value = _web().get(key, True)
    if not isinstance(value, bool):
        raise CompatibilityError('provider_error')
    return value


def _tier(name):
    tiers = _web().get('provider_tier') or {}
    if not isinstance(tiers, dict):
        raise CompatibilityError('provider_error')
    tier = str(tiers.get(name) or '').strip().lower()
    return tier if tier in ('free', 'paid') else 'auto'


def resolve() -> object:
    """Honor explicit extract/shared selection, including managed ``nous``.

    Only when no selection exists may Hermes perform its normal availability walk.
    """
    web = _web()
    selected = web.get('extract_backend') or web.get('backend')
    if selected:
        if not isinstance(selected, str):
            raise CompatibilityError('provider_error')
        name = selected.strip().lower()
        provider = _call('agent.web_search_registry', 'get_provider',
                         'firecrawl' if name == 'nous' else name)
    else:
        provider = _call('agent.web_search_registry', 'get_active_extract_provider')
    try:
        if provider is None or not getattr(provider, 'supports_extract')():
            raise CompatibilityError('provider_error')
        inspect.signature(getattr(provider, 'extract')).bind([], format='markdown')
    except Exception as exc:
        raise CompatibilityError('provider_error') from exc
    return provider


def _policy(url):
    """Evaluate policy uncached. Hermes's public helper fails open internally.

    Use only its stateless rule parsing/matching, never its global cached loader.
    Shared-file read/parse failures are intentional refusals, not permission.
    """
    module = 'tools.website_policy'

    def call(name, *args):
        # Signature/import errors are compatibility failures; policy evaluation
        # exceptions below remain policy refusals.
        return _function(module, name, *args)(*args)

    try:
        security = _config().get('security', {})
        if not isinstance(security, dict):
            raise ValueError
        policy = security.get('website_blocklist', {})
        if not isinstance(policy, dict):
            raise ValueError
        enabled = call('_require_type', policy, 'enabled', bool, True)
        domains = call('_require_type', policy, 'domains', list, [])
        files = call('_require_type', policy, 'shared_files', list, [])
        if not enabled:
            return
        rules = [call('_normalize_rule', rule) for rule in domains]
        for file in files:
            if not isinstance(file, str) or not file.strip():
                raise ValueError
            path = Path(file).expanduser()
            if not path.is_absolute():
                home = call('get_hermes_home')
                path = home / path
            rules.extend(call('_normalize_rule', line)
                         for line in path.read_text(encoding='utf-8-sig').splitlines())
        host = call('_extract_host_from_urlish', url)
        if not host:
            raise ValueError
        if any(call('_match_host_against_rule', host, rule)
               for rule in rules if rule):
            raise CompatibilityError('policy_blocked')
    except CompatibilityError:
        raise
    except Exception as exc:
        raise CompatibilityError('policy_blocked') from exc


async def check_url(url: str) -> str:
    """Return only transport identity; callers retain the original request string."""
    if not isinstance(url, str) or not url.strip():
        raise CompatibilityError('invalid_url')
    normalized = _call('tools.url_safety', 'normalize_url_for_request', url)
    if not isinstance(normalized, str):
        raise CompatibilityError('provider_error')
    try:
        pattern = getattr(_module('agent.redact'), '_PREFIX_RE')
        if any(pattern.search(item) for item in (url, unquote(url), normalized, unquote(normalized))):
            raise CompatibilityError('secret_url')
        parsed = urlsplit(normalized)
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise CompatibilityError('invalid_url')
        # Literal private targets remain refused even if Hermes permits private URLs.
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise CompatibilityError('unsafe_url')
    except CompatibilityError:
        raise
    except Exception as exc:
        raise CompatibilityError('provider_error') from exc
    safe = await asyncio.to_thread(_call, 'tools.url_safety', 'is_safe_url', normalized)
    if safe is not True:
        raise CompatibilityError('unsafe_url')
    await asyncio.to_thread(_policy, normalized)
    return normalized


def uses_keyless(provider: object) -> bool:
    """Mirror known providers' EXTRACT predicate; unknown routing fails closed."""
    _config()  # Reject failed snapshots before upstream predicates consume them.
    name = getattr(provider, 'name', '')
    extract = getattr(provider, 'extract', None)
    known = name in _DIRECT and getattr(extract, '__module__', '') == f'plugins.web.{name}.provider'
    if not known:
        try:
            predicate = getattr(provider, 'uses_keyless')
            inspect.signature(predicate).bind()
            result = predicate()
        except Exception as exc:
            raise CompatibilityError('provider_error') from exc
    elif name == 'firecrawl':
        result = _call('plugins.web.firecrawl.provider', '_use_keyless_ring', 'extract')
        if result is False:
            managed = _call('plugins.web.firecrawl.provider', 'is_managed_route', 'extract')
            if not isinstance(managed, bool):
                raise CompatibilityError('provider_error')
            if not managed:
                direct = _call('plugins.web.firecrawl.provider', '_get_direct_firecrawl_config')
                if (not isinstance(direct, tuple) or len(direct) != 3
                        or direct[0] not in ('sdk', 'keyless')):
                    raise CompatibilityError('provider_error')
                # No ring does not mean keyed: explicit no-key Firecrawl can
                # construct an anonymous cloud client even when free is off.
                # Primary is direct keyed/managed only; never add a fallback.
                result = direct[0] == 'keyless'
    elif name in _KEYS:
        key = _call('agent.web_search_provider', 'get_provider_env', _KEYS[name])
        result = _call('plugins.web.keyless_mcp', 'use_keyless', name, key)
    else:  # Tavily has no anonymous ring path.
        result = False
    if not isinstance(result, bool):
        raise CompatibilityError('provider_error')
    return result


def rescue_allowed(provider: object) -> bool:
    try:
        return (provider is not None and _enabled('keyless_rescue')
                and bool(_available()) and not uses_keyless(provider))
    except CompatibilityError:
        return False


def _available():
    return [v for v in _RING if _tier(v) != 'paid'] if _enabled('keyless_fallback') else []


def ring_order(name: str) -> list[str]:
    available = _available()
    if not available:
        return []
    order = _call('plugins.web.keyless_mcp', '_ring_order', name)
    if (not isinstance(order, list) or any(not isinstance(v, str) or v not in _RING for v in order)
            or len(order) != len(set(order)) or set(order) != set(available)):
        raise CompatibilityError('provider_error')
    return order


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining


async def _invoke(fn, *args, deadline, **kwargs):
    """One absolute monotonic budget, even when sync returns an awaitable."""
    _remaining(deadline)
    try:
        inspect.signature(fn).bind(*args, **kwargs)
    except Exception as exc:
        raise CompatibilityError('provider_error') from exc

    async def run():
        _remaining(deadline)
        try:
            if inspect.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            def call():
                _remaining(deadline)
                return fn(*args, **kwargs)
            value = await asyncio.to_thread(call)
            return await value if inspect.isawaitable(value) else value
        except (CompatibilityError, TimeoutError):
            # Deliberate refusals and deadlines keep their terminal meaning.
            raise
        except Exception as exc:
            # Normalize only actual invocation/await failures, never URL checks
            # or response validation. CancelledError (BaseException) propagates.
            raise CompatibilityError('provider_error') from exc
    value = await asyncio.wait_for(run(), timeout=_remaining(deadline))
    _remaining(deadline)
    return value


async def _safe_urls(urls, deadline):
    safe = []
    for url in urls:
        _remaining(deadline)
        safe.append(await asyncio.wait_for(check_url(url), timeout=_remaining(deadline)))
    return safe


def _rows(value):
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise CompatibilityError('malformed_response')
    return value


async def primary(provider: object, urls: list[str], *, format: str, deadline: float) -> list[dict]:
    _remaining(deadline)
    if uses_keyless(provider):
        raise CompatibilityError('provider_error')
    safe = await _safe_urls(urls, deadline)
    return _rows(await _invoke(getattr(provider, 'extract'), safe, format=format, deadline=deadline))


async def keyless(vendor: str, urls: list[str], *, deadline: float) -> list[dict]:
    _remaining(deadline)
    if vendor not in _available():
        raise CompatibilityError('provider_error')
    safe = await _safe_urls(urls, deadline)
    if vendor == 'keenable':
        # Task 1's deadline is a transport argument, not a fresh per-URL budget.
        fn = _function('keenable_extraction', 'fetch', '', deadline=deadline)
        async def fetch(url):
            return await asyncio.to_thread(fn, url, deadline=deadline)
        return _rows([await _invoke(fetch, url, deadline=deadline) for url in safe])
    fn = _function('plugins.web.keyless_mcp', vendor + '_extract_keyless', safe)
    return _rows(await _invoke(fn, safe, deadline=deadline))


def rate_limited(rows: list[dict]) -> bool:
    if not rows:
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        error = row.get('error')
        if (not isinstance(error, str) or not error or row.get('blocked_by_policy')
                or 'blocked by website policy' in error.lower()):
            return False
        if _call('plugins.web.keyless_mcp', '_is_rate_limitish', error) is not True:
            return False
    return True
