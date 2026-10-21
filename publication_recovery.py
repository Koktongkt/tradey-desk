"""Run-local, one-shot publication recovery. Never owns source/trade admission.

Callbacks take (url, timeout_seconds) and (pages, *, deadline), respectively.
Optional policy injection reuses radar's exact publisher/body/freshness rules
without an import-time cycle or process-global recovery state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
import hashlib
import json
from pathlib import Path
from time import monotonic
from typing import Callable
from urllib.parse import urlsplit

from publication_observation import validate_observation, evaluate_publication

RECOVERY_BUDGET_SECONDS = 90
# M1 (fix round 6): candidate-recovery admissions share the same per-run
# ten-page fair-binding ceiling as model-path admissions.
RECOVERY_PAGE_LIMIT = 10
RECOVERY_REASONS = frozenset({'cache_hit','refetched','fetch_failed','invalid_page',
    'recovered_day','recovered_instant','recovered_page_limit','parser_unknown','hard_refusal','stale_source',
    'success','unknown','missing_member','duplicate_member','invalid_member',
    'inadmissible_publication','existing_observation','page_limit','duplicate_url',
    'input_limit','timeout','command_unavailable','worker_unavailable','worker_exit',
    'malformed_response','output_limit','cleanup_incomplete'})


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def preserve_cached_refusal(page: dict, cached: dict) -> dict:
    """Retain any invalid-present refusal only on the identical canonical capture.

    A proof miss on a different capture is not a current-stage refusal. Valid
    cached observations instead follow the ordinary replay/freshness checks.
    """
    if (isinstance(cached, dict) and 'publication_observation' in cached
            and not validate_observation(cached, cached['publication_observation'])
            and cached.get('url') == page.get('url')
            and cached.get('returned_url',cached.get('url')) == page.get('returned_url',page.get('url'))
            and cached.get('text') == page.get('text')):
        return dict(page, publication_observation=cached['publication_observation'])
    return page


@dataclass
class RecoveryState:
    attempted_model: bool = False
    started_at: float | None = None
    deadline: float | None = None
    refreshed_urls: set[str] = field(default_factory=set)
    observations: dict[str, dict] = field(default_factory=dict)


def _policy(publisher, filter_pages):
    if publisher is None or filter_pages is None:
        # Deferred only for standalone callers; live callers inject their policy.
        from alpha_radar import publisher_domain, filter_evidence
        publisher = publisher or publisher_domain
        filter_pages = filter_pages or filter_evidence
    return publisher, filter_pages


def _known_instant(page):
    try:
        value = dt.datetime.fromisoformat(str(page.get('published_at')).replace('Z','+00:00'))
        return value.tzinfo is not None
    except ValueError:
        return False


def candidate_recovery_page(page: dict, *, now, filter_pages: Callable,
                            budget: int = 8192) -> dict | None:
    """Deterministic bounded date-candidate recovery beyond the text bound.

    Pages whose captured text exceeds the 6000-char transport bound were
    previously unservable. The bounded candidate-context document (never a
    fixed header slice) is the canonical interpretation text; the original
    capture text remains the source of record on the unchanged page. I2 (fix
    round 6): the recovered observation's content_sha256 binds the ORIGINAL
    capture bytes (the hash/witness basis) via the `_capture_sha256` capture
    basis recorded here; the stitched candidate document is interpretation
    input only and is never the hash basis. Only a locally validated
    observation that passes the same publisher/freshness filter is returned —
    no model, no refetch, no fabricated dates.
    """
    from publication_observation import date_candidate_text, prepare_publication_evidence
    text = page.get('text')
    if not isinstance(text, str) or not text:
        return None
    try:
        candidate = date_candidate_text(text, budget=budget)
    except ValueError:
        return None
    if not candidate:
        return None
    candidate_page = {k: v for k, v in page.items()
                      if k not in ('publication_observation', '_publication_body_text',
                                   '_capture_sha256')}
    candidate_page['text'] = candidate
    # I2: provenance binding — the observation's hash basis is the original
    # capture bytes, computed here over locally held capture text (never
    # accepted from an external page field). N1 (final whole-branch review):
    # the digest reaches prepare_publication_evidence via the fail-closed
    # `capture_sha256` parameter, because a `_capture_sha256` key on an
    # incoming page dict is now always stripped as attacker-controllable.
    capture_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
    # Candidate contexts are the interpretation/binding text; a bounded slice
    # of the original capture is retained as body so the reviewed body-minimum
    # gate judges real captured content, never metadata alone.
    extracted = candidate
    if len(extracted) + 1 < 6000:
        extracted = candidate + '\n' + text[:6000 - len(candidate) - 1]
    try:
        prepared = prepare_publication_evidence(candidate_page,
                                                extracted_text=extracted,
                                                capture_sha256=capture_hash)
    except ValueError:
        return None
    if not isinstance(prepared.get('publication_observation'), dict):
        return None
    # The prepared page carries the locally computed capture digest so cache
    # persistence and later re-validation stay internally consistent (I2).
    prepared['_capture_sha256'] = capture_hash
    ok, _ = filter_pages([prepared], now=now)
    return prepared if ok else None


def choose_recovery_pages(candidates: list[dict], pages: list[dict], accepted: list[dict],
                          *, limit: int = 10, publisher: Callable | None = None,
                          filter_pages: Callable | None = None,
                          deadline: float | None = None) -> list[dict]:
    publisher, filter_pages = _policy(publisher, filter_pages)
    def expired():return deadline is not None and monotonic() >= deadline
    if expired():return []
    by_url = {p.get('url'): p for p in pages if isinstance(p, dict) and isinstance(p.get('url'), str)}
    admitted, _ = filter_pages(pages, now=utc_now())
    accepted_urls = {p['url'] for p in [*accepted, *admitted] if isinstance(p.get('url'),str)}
    pools = []
    for candidate in candidates:
        if expired():break
        urls = candidate.get('urls', [])
        domains = {publisher(u) for u in urls if u in accepted_urls}
        domains.discard('')
        if len(domains) >= 2:
            pools.append(([], domains)); continue
        useful = []
        for url in urls:
            if expired():break
            p = by_url.get(url)
            if p is None or url in accepted_urls or 'publication_observation' in p or _known_instant(p):
                continue  # Present-invalid is a non-overridable ingestion refusal.
            try:
                locations = [urlsplit(p.get(k, url)) for k in ('url', 'returned_url')]
                if any(u.scheme not in ('http','https') or not u.hostname for u in locations):continue
            except (ValueError, TypeError):continue
            if p.get('error'):continue
            _, notes = filter_pages([p], now=utc_now())
            if not notes or notes[0].get('reason') != 'source_freshness_unknown':
                continue
            if not isinstance(p.get('text'), str) or not 0 < len(p['text']) <= 6000:
                continue
            if publisher(url) and publisher(url) not in domains:
                useful.append(p)
        pools.append((useful, domains))
    selected = []; seen = set()
    # Fair allocation, not greedy per-candidate filling. Shared URL consumes one slot.
    for _ in range(2):
        for useful, domains in pools:
            if len(selected) >= min(10, max(0, limit)):
                return selected
            if len(domains) >= 2:
                continue
            for p in useful:
                url = p['url']; domain = publisher(url)
                if domain in domains:
                    continue
                if url in seen:
                    continue
                domains.add(domain)
                selected.append(p); seen.add(url)
                break
    return selected


def _attach(page, observation, *, now):
    if not validate_observation(page, observation):
        return None
    updated = dict(page, publication_observation=dict(observation),
                   published_at=observation['value'],
                   publication_precision='day' if observation['precision'] == 'day' else 'second',
                   publication_basis=observation['basis'])
    return updated if evaluate_publication(updated, now=now)[0] else None


def recover_publications(candidates: list[dict], pages: list[dict], accepted: list[dict], *,
                         state: RecoveryState, overall_deadline: float,
                         downstream_reserve: float, cache_path: Path | None,
                         fetcher: Callable, interpreter: Callable,
                         publisher: Callable | None = None,
                         filter_pages: Callable | None = None,
                         refetch_urls: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    started = monotonic()
    if state.started_at is None:
        state.started_at = started
        state.deadline = min(started + RECOVERY_BUDGET_SECONDS,
                             overall_deadline - max(0, downstream_reserve))
    deadline = min(state.deadline, overall_deadline - max(0, downstream_reserve))
    publisher, filter_pages = _policy(publisher, filter_pages)
    result = [dict(p) for p in pages]
    present = {p['url'] for p in result if isinstance(p.get('url'),str)}
    result.extend(dict(p) for p in accepted if isinstance(p.get('url'),str) and p['url'] not in present)
    notes = []
    def note(index, reason):
        notes.append({'id': f'p{index}', 'reason': reason})
    def expired():
        return monotonic() >= deadline
    if expired():
        return result, [{'id':'batch','reason':'timeout'}]
    cache = {}
    if cache_path is not None:
        try:
            loaded = json.loads(cache_path.read_text(encoding='utf-8'))
            if isinstance(loaded, dict): cache = loaded
        except (OSError, ValueError):
            pass
    if expired():
        return result, [{'id':'batch','reason':'timeout'}]
    accepted_urls = {p['url'] for p in accepted if isinstance(p.get('url'),str)}
    checked_updates = {}
    recovered_pages = 0
    for i, p in enumerate(result):
        if expired():
            note(i, 'timeout'); break
        url = p.get('url')
        if not isinstance(url,str):
            note(i,'invalid_page')
            continue
        if url in accepted_urls or 'publication_observation' in p or _known_instant(p):
            continue
        entry = cache.get(url)
        entry = entry if isinstance(entry, dict) else {}
        cached = entry.get('page')
        cached = cached if isinstance(cached, dict) else {}
        refused = preserve_cached_refusal(p, cached)
        if 'publication_observation' in refused:
            result[i] = refused; note(i,'hard_refusal'); continue
        try:
            checked = dt.datetime.fromisoformat(str(entry.get('checked_at')).replace('Z', '+00:00'))
            recent = checked.tzinfo is not None and dt.timedelta(0) <= utc_now()-checked <= dt.timedelta(hours=24)
        except (ValueError, TypeError):
            recent = False
        obs = state.observations.get(url)
        if (obs is None and recent and cached.get('url') == url
                and cached.get('text') == p.get('text')
                and validate_observation(cached,cached.get('publication_observation'))):
            obs = cached.get('publication_observation')
        updated = _attach(p, obs, now=utc_now())
        if updated is not None and filter_pages([updated], now=utc_now())[0]:
            if expired(): note(i, 'timeout'); break
            result[i] = updated; note(i, 'cache_hit'); continue
        text = p.get('text')
        if isinstance(text, str) and len(text) > 6000:
            # Beyond the transport text bound this page was previously
            # unservable; bounded date-candidate extraction recovers it
            # deterministically before any scoped transport work. M1 (fix
            # round 6): these deterministic admissions count against the same
            # per-run ten-page fair-binding ceiling as model-path admissions.
            if recovered_pages >= RECOVERY_PAGE_LIMIT:
                note(i, 'recovered_page_limit')
                continue
            prepared = candidate_recovery_page(p, now=utc_now(), filter_pages=filter_pages)
            if prepared is not None and not expired():
                result[i] = prepared
                recovered_pages += 1
                state.observations[url] = dict(prepared['publication_observation'])
                note(i, 'recovered_day' if prepared['publication_precision'] == 'day'
                     else 'recovered_instant')
                continue
    # Fairly bind at most ten pages BEFORE any scoped transport work.
    bound = choose_recovery_pages(candidates, result, accepted,
                                 publisher=publisher, filter_pages=filter_pages, deadline=deadline)
    indices = {p['url']:i for i,p in enumerate(result) if isinstance(p.get('url'),str)}
    for p in bound:
        i = indices[p['url']]; url = p['url']
        note(i,'parser_unknown')
        if state.attempted_model:break
        if expired():note(i,'timeout');break
        entry = cache.get(url, {})
        if not isinstance(entry, dict):continue
        cached = entry.get('page', {})
        if not isinstance(cached, dict):continue
        try:
            checked = dt.datetime.fromisoformat(str(entry.get('checked_at')).replace('Z','+00:00'))
            recent = checked.tzinfo is not None and dt.timedelta(0) <= utc_now()-checked <= dt.timedelta(hours=24)
        except (TypeError, ValueError):recent = False
        # Never duplicate fresh focused/direct extraction just for an unknown date.
        if (recent and cached.get('url') == url and cached.get('text') == p.get('text')
                and (refetch_urls is None or url in refetch_urls)
                and 'publication_observation' not in cached and url not in state.refreshed_urls):
            state.refreshed_urls.add(url)
            remaining = deadline - monotonic()
            if remaining <= 0: note(i, 'timeout'); break
            try:
                fresh = fetcher(url, remaining)
            except Exception:
                note(i, 'fetch_failed'); continue
            if expired(): note(i, 'timeout'); break
            if isinstance(fresh, dict) and fresh.get('url') == url:
                valid, quality = filter_pages([fresh], now=utc_now())
                if valid or (quality and quality[0].get('reason') == 'source_freshness_unknown'):
                    result[i] = dict(fresh)
                    checked_updates[url] = utc_now().isoformat().replace('+00:00', 'Z')
                    note(i, 'refetched')
                else: note(i, 'invalid_page')
            else: note(i, 'fetch_failed')
    selected = choose_recovery_pages(candidates, [result[indices[p['url']]] for p in bound], accepted,
                                     publisher=publisher, filter_pages=filter_pages, deadline=deadline)
    if expired():
        return result, [*notes, {'id':'batch','reason':'timeout'}]
    if selected and not state.attempted_model:
        state.attempted_model = True
        observations, diagnostics = interpreter(selected, deadline=deadline)
        allowed_reasons = {'success','unknown','missing_member','duplicate_member','invalid_member',
            'inadmissible_publication','existing_observation','page_limit','invalid_page','duplicate_url',
            'input_limit','timeout','command_unavailable','worker_unavailable','worker_exit',
            'malformed_response','output_limit','cleanup_incomplete'}
        for d in diagnostics:
            if isinstance(d, dict) and d.get('reason') in allowed_reasons:
                ident = d.get('id')
                if isinstance(ident, str) and ident in {f'p{i}' for i in range(10)}:
                    notes.append({'id':ident,'reason':d['reason']})
        selected_urls = {p['url'] for p in selected}
        for i, p in enumerate(result):
            if expired(): note(i, 'timeout'); break
            if not isinstance(p.get('url'),str) or p['url'] not in selected_urls or 'publication_observation' in p:
                continue
            updated = _attach(p, observations.get(p.get('url')), now=utc_now())
            if updated is not None and filter_pages([updated], now=utc_now())[0]:
                if expired(): note(i, 'timeout'); break
                result[i] = updated
                state.observations[p['url']] = dict(updated['publication_observation'])
                note(i, 'recovered_day' if updated['publication_precision']=='day' else 'recovered_instant')
    # Persist successes only on the exact cached capture, retaining its check time.
    # A failed/unknown model result never creates a negative cache entry.
    changed = False
    for p in result:
        if expired(): break
        url = p.get('url')
        if not isinstance(url,str):continue
        entry = cache.get(url)
        if url in state.observations and not isinstance(entry, dict):
            try:
                checked = dt.datetime.fromisoformat(str(p.get('checked_at')).replace('Z','+00:00'))
                if checked.tzinfo is not None and checked <= utc_now():
                    cache[url] = {'checked_at':p['checked_at'],'page':p};changed = True
            except (TypeError,ValueError):pass
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get('page'), dict): continue
        if url in checked_updates:
            cache[url] = {'checked_at':checked_updates[url], 'page':p}; changed = True
        elif (p.get('publication_observation') is not None
              and entry['page'].get('url') == url and entry['page'].get('text') == p.get('text')
              and validate_observation(p, p['publication_observation'])):
            cache[url] = {**entry, 'page':p}; changed = True
    if cache_path is not None and changed and not expired():
        # Persistence errors belong to the caller's existing infrastructure channel.
        cache = dict(sorted(cache.items(),key=lambda item:str(item[1].get('checked_at',''))
                            if isinstance(item[1],dict) else '',reverse=True)[:200])
        cache_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = cache_path.with_suffix(cache_path.suffix+'.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            temporary.chmod(0o600)
            json.dump(cache, stream, separators=(',', ':'), sort_keys=True)
        temporary.replace(cache_path)
    return result, notes
