"""Deadline-bound focused collection; submission is admission, not network proof.

No model text or search receipts become pages. Detailed network accounting is
unknown here; only the extraction worker's real envelopes establish content.
"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass
import datetime as dt
from pathlib import Path
from time import monotonic
from typing import Callable

from focused_allocation import Allocation, allocate_urls
from focused_search import search_alternatives
from structured_extraction import (run_batch_worker, run_validation_worker,
                                   SupervisorFailure, _valid_batch_response,
                                   _valid_validation_response)


class FocusedFailure(RuntimeError):
    """Sanitized supervisor/protocol failure, never an ordinary empty setup."""


@dataclass(frozen=True)
class FocusedResult:
    allocation: Allocation
    pages: dict[str, dict]
    checked_at: dict[str, str]
    submitted_urls: set[str]
    outcomes: dict[str, str]
    candidate_counts: dict[str, dict[str, int]]


def _check(out, urls, validator):
    if not validator(out, urls):
        raise FocusedFailure('focused_protocol_failure')
    if isinstance(out, SupervisorFailure) and out.get('reason') != 'timeout':
        raise FocusedFailure('focused_supervisor_failure')


def validate_pool_urls(urls: list[str], *, deadline: float) -> set[str]:
    """At most 30 preselection identities, safety-only isolated groups of five.

    Validation consumes the original deadline; extraction rechecks all safety.
    No network/DNS code runs in the parent or allocator.
    """
    return _validate_pool(urls, deadline=deadline)[0]


def _validate_pool(urls, *, deadline):
    unique = list(dict.fromkeys(urls))
    if len(unique) > 30:
        raise FocusedFailure('focused_pool_limit')
    eligible = set()
    outcomes = {url: 'focused_deadline_exhausted' for url in unique}
    for i in range(0, len(unique), 5):
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        batch = unique[i:i+5]
        out = run_validation_worker(batch, timeout_seconds=min(30, remaining))
        _check(out, batch, _valid_validation_response)
        if out['status'] == 'ok':
            eligible.update(row['requested_url'] for row in out['results'] if row['eligible'])
            outcomes.update({row['requested_url']: row['reason'] for row in out['results'] if not row['eligible']})
        elif out['reason'] not in {'timeout', 'unsafe_url', 'provider_error'}:
            raise FocusedFailure('focused_safety_failure')
        else:
            outcomes.update({url: out['reason'] for url in batch})
    return eligible, {url: reason for url, reason in outcomes.items() if url not in eligible}


def extract_allocated(allocation: Allocation, *, deadline: float,
                      run_batch: Callable = run_batch_worker) -> FocusedResult:
    """FIFO singleton admission, at most three owned extraction supervisors.

    No executor backlog is admitted: refill only after a supervised call returns.
    The call wrapper recomputes allowance on its own thread immediately before
    dispatch, so thread startup cannot refresh or extend the absolute deadline.
    """
    import threading
    pages, checked_at, submitted = {}, {}, set()
    outcomes = {url: 'focused_deadline_exhausted' for url in allocation.unique_urls}
    # Allocation is a public dataclass: reject a forged over-budget plan before
    # it can become an extraction dispatch.
    flat = [url for batch in allocation.batches for url in batch]
    if (len(allocation.unique_urls) > 25 or len(set(flat)) != len(flat)
            or flat != allocation.unique_urls or len(allocation.batches) > 5
            or any(not 1 <= len(b) <= 5 for b in allocation.batches)
            or any(len(urls) > 5 or not set(urls) <= set(flat) for urls in allocation.by_symbol.values())):
        raise FocusedFailure('focused_allocation_failure')
    # Logical batches retain allocator order; transport owns one URL per job.
    # Exactly three supervisors globally, with no nested provider concurrency.
    jobs = [[url] for url in flat]
    condition = threading.Condition()
    next_admission = 0

    def dispatch(index, batch):
        nonlocal next_admission
        with condition:
            condition.wait_for(lambda: index == next_admission)
            next_admission += 1
            remaining = deadline - monotonic()
            condition.notify_all()
            if remaining <= 0:
                return None, None
            submitted.update(batch)
        out = run_batch(batch, timeout_seconds=min(30, remaining))
        completed = dt.datetime.now(dt.timezone.utc).isoformat()
        return out, completed

    pending, index = {}, 0
    # Supervised operations kill/reap their owned group before returning. Waiting
    # here is intentional: returning with running supervisors leaks ownership.
    with ThreadPoolExecutor(max_workers=3) as executor:
        while pending or index < len(jobs):
            while len(pending) < 3 and index < len(jobs) and monotonic() < deadline:
                batch = jobs[index]
                pending[executor.submit(dispatch, index, batch)] = batch
                index += 1
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                batch = pending.pop(future)
                try:
                    out, completed = future.result()
                except Exception as exc:
                    raise FocusedFailure('focused_supervisor_failure') from exc
                if out is None:
                    continue
                _check(out, batch, _valid_batch_response)
                if out['status'] == 'error':
                    for url in batch:
                        outcomes[url] = out['reason']
                    continue
                for row in out['results']:
                    url, result = row['requested_url'], row['result']
                    if result['status'] == 'ok':
                        pages[url] = result['page']
                        checked_at[url] = completed
                        outcomes[url] = 'success'
                    else:
                        outcomes[url] = result['reason']
    counts = {symbol: {'selected': len(urls),
                       'submitted': sum(u in submitted for u in urls),
                       'successful': sum(u in pages for u in urls)}
              for symbol, urls in allocation.by_symbol.items()}
    return FocusedResult(allocation, pages, checked_at, submitted, outcomes, counts)


def run_focused_pipeline(candidates: list[dict], *, deadline: float, command: list[str],
                         cwd: Path, unhealthy_domains: set[str]) -> FocusedResult:
    search = search_alternatives(candidates, deadline=deadline, command=command, cwd=cwd)
    pool = [url for candidate in candidates[:5]
            for url in candidate.get('urls', []) + search.alternatives.get(candidate['symbol'], [])]
    eligible, safety_outcomes = _validate_pool(pool, deadline=deadline)
    allocation = allocate_urls(candidates, search.alternatives, eligible_urls=eligible,
                               unhealthy_domains=unhealthy_domains)
    result = extract_allocated(allocation, deadline=deadline, run_batch=run_batch_worker)
    result.outcomes.update(safety_outcomes)
    return result
