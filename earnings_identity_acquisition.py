"""Bounded exact-URL identity acquisition; no models, broker or ledger writes."""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass,field
import http.client
from time import monotonic
import urllib.error
import urllib.request
from earnings_calendar import SEC_USER_AGENT
from earnings_identity_evidence import capture_identity_source, identity_source_bytes, MAX_IDENTITY_SOURCE_BYTES
from earnings_identity_resolution import earnings_exhibit_links
from opportunity_identity import _locator
from research_budget import active_deadline, remaining, read_http_response, ResearchDeadlineExceeded


@dataclass
class _State:
    cache: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)
    links: dict = field(default_factory=dict)


_state:ContextVar[_State|None]=ContextVar('earnings_identity_acquisition',default=None)


@contextmanager
def identity_acquisition():
    token=_state.set(_State())
    try:yield
    finally:_state.reset(token)


def acquisition_notes(urls):
    state=_state.get()
    if state is None:return ()
    queue=list(dict.fromkeys(urls));seen=set()
    for url in queue:
        seen.add(url)
        for linked in state.links.get(url,()):
            if linked not in queue and len(queue)<32:queue.append(linked)
    return tuple(state.notes[url] for url in queue if url in state.notes)


def _fetch(url,deadline,opener,state):
    if url in state.cache:return state.cache[url]
    if len(state.cache)>=32:return None
    state.cache[url]=None
    reason='identity_source_unavailable';start=monotonic()
    try:
        with active_deadline(min(deadline,start+15)):
            remaining(15)
            if opener is None:raise ValueError('identity_transport_unavailable')
            request=urllib.request.Request(url,headers={'User-Agent':SEC_USER_AGENT,'Accept':'text/html',
                                                        'Accept-Encoding':'identity'})
            with opener(request,timeout=remaining(15)) as response:
                remaining(15)
                if getattr(response,'status',None)!=200:raise ValueError('identity_http_status')
                returned=response.geturl()
                if _locator(returned)!=_locator(url):raise ValueError('identity_redirect_mismatch')
                headers=response.headers
                media=headers.get('Content-Type','')
                encoding=headers.get('Content-Encoding','identity').strip().lower()
                if encoding not in ('','identity'):raise ValueError('identity_encoding_unsupported')
                declared=headers.get('Content-Length')
                if declared is not None and (not isinstance(declared,str) or len(declared)>12
                        or not declared.isascii() or not declared.isdecimal()):
                    raise ValueError('identity_content_length_invalid')
                raw=read_http_response(response,max_bytes=MAX_IDENTITY_SOURCE_BYTES+1)
                remaining(15)
                if len(raw)>MAX_IDENTITY_SOURCE_BYTES:raise ValueError('identity_source_capacity')
                if declared is not None and len(raw)!=int(declared):raise ValueError('identity_body_incomplete')
                capture=capture_identity_source(url,raw,returned_url=returned,content_type=media)
                remaining(15)
            state.cache[url]=capture;reason='identity_source_acquired'
    except ResearchDeadlineExceeded:reason='identity_source_deadline'
    except urllib.error.HTTPError as error:
        reason='identity_source_forbidden' if error.code in (401,403) else 'identity_source_http_error'
    except (OSError,http.client.HTTPException):reason='identity_source_transport_failed'
    except (ValueError,UnicodeError) as error:
        fixed={'identity_transport_unavailable','identity_http_status','identity_redirect_mismatch',
               'identity_encoding_unsupported','identity_content_length_invalid','identity_source_capacity',
               'identity_body_incomplete','identity_capture_media','identity_capture_locator'}
        reason=str(error) if str(error) in fixed else 'identity_source_invalid'
    state.notes[url]={'reason':reason,'elapsed_ms':max(0,round((monotonic()-start)*1000)),
                      'capture_status':'complete' if state.cache[url] is not None else 'unavailable'}
    return state.cache[url]


def _note_handoff_deadline(state, urls):
    pending=list(urls)
    for url in list(pending):
        pending.extend(state.links.get(url,()))
    for url in dict.fromkeys(pending):
        state.notes.setdefault(url,{'reason':'identity_handoff_deadline','capture_status':'unavailable','elapsed_ms':0})


def acquire_identity_captures(symbol: str, pages: list[dict], *, deadline: float,
                              opener=None) -> tuple:
    """Caller supplies reviewed safe transport. Never promote a page field to authority."""
    if not isinstance(pages,list):return ()
    state=_state.get() or _State();queue=[]
    for page in pages:
        url=page.get('url') if isinstance(page,dict) else None
        if _locator(url) is not None and url not in queue:queue.append(url)
    captures=[];seen=set()
    for url in queue:
        if url in seen:continue
        seen.add(url)
        if monotonic()>=deadline:
            _note_handoff_deadline(state,queue)
            break
        capture=_fetch(url,deadline,opener,state)
        if capture is None:continue
        captures.append(capture)
        # A newly discovered href is a current-source literal, never a guessed filename.
        linked_urls=earnings_exhibit_links(identity_source_bytes(capture),url)
        state.links[url]=linked_urls
        for linked in linked_urls:
            if linked not in queue and len(queue)<32:queue.append(linked)
    if monotonic()>=deadline:
        for capture in captures:
            state.notes[capture.url]={**state.notes.get(capture.url,{}),
                'reason':'identity_handoff_deadline','capture_status':'unavailable'}
        _note_handoff_deadline(state,queue)
    return tuple(captures) if monotonic()<deadline else ()
