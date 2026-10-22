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
    'recovered_day','recovered_instant','recovered_body','body_recovery_pending','recovered_page_limit','parser_unknown','hard_refusal','stale_source',
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
    remaining_seconds: float = RECOVERY_BUDGET_SECONDS
    deterministic_urls: set[str] = field(default_factory=set)


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
    """Deterministic recovery for bounded or oversized original captures.

    Bounded originals keep their canonical text unchanged. For oversized pages
    the bounded candidate-context document is interpretation input only: the
    ORIGINAL capture remains the validation/hash authority, including claims
    absent from that document. No model, refetch, guessed timezone or removal
    of a present observation marker is permitted here.
    """
    from publication_observation import date_candidate_text, prepare_publication_evidence
    text = page.get('text')
    if not isinstance(text, str) or not text or 'publication_observation' in page:
        return None
    if len(text) <= 6000:
        # All original claims are construction authority. A bounded original
        # needs no replacement text or synthetic capture-hash authority.
        from publication_observation import build_observation
        parsed = prepare_publication_evidence(page, extracted_text=text)
        obs = parsed.get('publication_observation')
        if not isinstance(obs, dict):
            return None
        # A bounded original needs no projection: retain its exact canonical
        # bytes, cache identity and ordinary receipt validation contract.
        original = {k:v for k,v in page.items() if k != '_capture_sha256'}
        obs = build_observation(original, value=obs['value'], precision=obs['precision'],
            basis=obs['basis'], support=obs['support'], location=obs['location'])
        prepared = _attach(original, obs, now=now)
        return prepared if prepared and filter_pages([prepared], now=now)[0] else None
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
    original = {k:v for k,v in page.items() if k != '_capture_sha256'}
    if not validate_observation(original, prepared['publication_observation']):
        return None  # Candidate extraction is never authority to hide a claim.
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
            if p is None or url in accepted_urls:continue
            from publication_interpreter import body_repair_needed
            body_only=body_repair_needed(p) and evaluate_publication(p,now=utc_now())[0]
            if 'publication_observation' in p and not validate_observation(p,p['publication_observation']):continue
            if ('publication_observation' in p or _known_instant(p)) and not body_only:continue
            try:
                locations = [urlsplit(p.get(k, url)) for k in ('url', 'returned_url')]
                if any(u.scheme not in ('http','https') or not u.hostname for u in locations):continue
            except (ValueError, TypeError):continue
            if p.get('error'):continue
            _, notes = filter_pages([p], now=utc_now())
            from retained_article import body_context
            body_recoverable=(notes and notes[0].get('reason')=='article_body_missing' and len(body_context(p).strip())>=80)
            if not notes or (notes[0].get('reason') != 'source_freshness_unknown' and not body_recoverable):
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
    from retained_article import valid_body_passage,original_text,rebind_article
    body=None
    body_only=isinstance(observation,dict) and set(observation)=={'body_support'}
    if body_only:
        from publication_interpreter import body_repair_needed
        body=observation['body_support']
        if not body_repair_needed(page) or not evaluate_publication(page,now=now)[0] or not valid_body_passage(page,body):return None
        observation=page.get('publication_observation')
    elif isinstance(observation,dict) and set(observation)=={'observation','body_support'}:
        body=observation['body_support']
        if not valid_body_passage(page,body):return None
        observation=observation['observation']
    if 'publication_observation' in page and not validate_observation(page,page['publication_observation']):return None
    if not (body_only and observation is None) and not validate_observation(page, observation):
        return None
    updated = dict(page) if body_only else dict(page, publication_observation=dict(observation),
                   published_at=observation['value'],
                   publication_precision='day' if observation['precision'] == 'day' else 'second',
                   publication_basis=observation['basis'])
    if body is not None:
        raw=original_text(page)
        updated.update(text=body,_publication_body_text=body)
        updated=rebind_article(page,updated)
        from publication_observation import build_observation
        if observation is not None:
            rebuilt=build_observation(updated,**{k:observation[k] for k in ('value','precision','basis','support','location')})
            if rebuilt is None:return None
            updated['publication_observation']=rebuilt
    return updated if evaluate_publication(updated, now=now)[0] else None


def recover_publications(candidates: list[dict], pages: list[dict], accepted: list[dict], *,
                         state: RecoveryState, overall_deadline: float,
                         downstream_reserve: float, cache_path: Path | None,
                         fetcher: Callable, interpreter: Callable,
                         publisher: Callable | None = None,
                         filter_pages: Callable | None = None,
                         refetch_urls: set[str] | None = None,
                         allow_model: bool = True) -> tuple[list[dict], list[dict]]:
    """Charge actual recovery work, not evidence/rescue waiting between calls.

    `allow_model=False` prepares deterministic/cache/refetch evidence without
    spending the single model batch. All calls share the same 90s work allowance.
    """
    started = monotonic()
    if state.started_at is None:
        state.started_at = started
    state.deadline = min(started + state.remaining_seconds,
                         overall_deadline - max(0, downstream_reserve))
    try:
        return _recover_publications(candidates, pages, accepted, state=state,
            overall_deadline=overall_deadline, downstream_reserve=downstream_reserve,
            cache_path=cache_path, fetcher=fetcher, interpreter=interpreter,
            publisher=publisher, filter_pages=filter_pages, refetch_urls=refetch_urls,
            allow_model=allow_model)
    finally:
        state.remaining_seconds = max(0.0, state.remaining_seconds - max(0.0, monotonic()-started))


def _recover_publications(candidates: list[dict], pages: list[dict], accepted: list[dict], *,
                         state: RecoveryState, overall_deadline: float,
                         downstream_reserve: float, cache_path: Path | None,
                         fetcher: Callable, interpreter: Callable,
                         publisher: Callable | None = None,
                         filter_pages: Callable | None = None,
                         refetch_urls: set[str] | None = None,
                         allow_model: bool = True) -> tuple[list[dict], list[dict]]:
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
        if isinstance(text, str) and text:
            # Deterministic preparation applies to every delivered capture.
            # Separate deterministic/model ceilings stay ten each per run.
            if url not in state.deterministic_urls and len(state.deterministic_urls) >= RECOVERY_PAGE_LIMIT:
                note(i, 'recovered_page_limit')
                continue
            prepared = candidate_recovery_page(p, now=utc_now(), filter_pages=filter_pages)
            if prepared is not None and not expired():
                result[i] = prepared
                state.deterministic_urls.add(url)
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
        from publication_interpreter import body_repair_needed
        if body_repair_needed(p) and evaluate_publication(p,now=utc_now())[0]:
            note(i,'body_recovery_pending');continue
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
                    if (not valid and 'publication_observation' not in fresh
                            and len(state.deterministic_urls) < RECOVERY_PAGE_LIMIT):
                        prepared = candidate_recovery_page(fresh, now=utc_now(), filter_pages=filter_pages)
                        if prepared is not None and not expired():
                            result[i] = prepared
                            state.deterministic_urls.add(url)
                            state.observations[url] = dict(prepared['publication_observation'])
                    checked_updates[url] = utc_now().isoformat().replace('+00:00', 'Z')
                    note(i, 'refetched')
                else: note(i, 'invalid_page')
            else: note(i, 'fetch_failed')
    selected = choose_recovery_pages(candidates, [result[indices[p['url']]] for p in bound], accepted,
                                     publisher=publisher, filter_pages=filter_pages, deadline=deadline)
    if expired():
        return result, [*notes, {'id':'batch','reason':'timeout'}]
    if selected and allow_model and not state.attempted_model:
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
            if not isinstance(p.get('url'),str) or p['url'] not in selected_urls:
                continue
            updated = _attach(p, observations.get(p.get('url')), now=utc_now())
            if updated is not None and filter_pages([updated], now=utc_now())[0]:
                if expired(): note(i, 'timeout'); break
                result[i] = updated
                if isinstance(updated.get('publication_observation'),dict):state.observations[p['url']] = dict(updated['publication_observation'])
                body_only=isinstance(observations.get(p['url']),dict) and set(observations[p['url']])=={'body_support'}
                note(i, 'recovered_body' if body_only else 'recovered_day' if updated['publication_precision']=='day' else 'recovered_instant')
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
