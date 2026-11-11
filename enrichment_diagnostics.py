"""Best-effort private enrichment spans. No policy, credentials, or durable ledger."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import math
import os
import re
import stat
import subprocess
import time
import uuid
from research_budget import ResearchDeadlineExceeded, diagnostic_remaining

_active: ContextVar[dict | None] = ContextVar('enrichment_diagnostic_attempt', default=None)
MAX_DETAIL_RECORDS = 120
PHASES = {'attempt', 'trusted_date', 'sec_history', 'prices'}
OPERATIONS = PHASES | {'config', 'open', 'body', 'json', 'cache', 'stockanalysis', 'nasdaq'}
PROVIDERS = {'local', 'trusted', 'sec', 'massive', 'stockanalysis', 'nasdaq'}
OUTCOMES = {'completed', 'confirmed', 'no_date', 'empty', 'fetched', 'error', 'config_error', 'open_error', 'body_error', 'parse_error', 'timeout', 'deadline', 'cancelled', 'hit', 'miss'}
REASONS = {'absent', 'expired', 'unreadable', 'invalid', 'cachehit'}


def provider_for_url(url):
    """Classify only fixed provider names; never retain transport inputs."""
    if _active.get() is None:
        return 'local'
    try:
        from urllib.parse import urlsplit
        host = urlsplit(url).hostname
        return {'www.sec.gov': 'sec', 'data.sec.gov': 'sec', 'stockanalysis.com': 'stockanalysis', 'api.nasdaq.com': 'nasdaq'}.get(host, 'local')
    except BaseException:
        return 'local'


def _number(value, maximum):
    return round(min(maximum, max(0., value)), 6) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _snapshot():
    try:
        return diagnostic_remaining()
    except BaseException:
        return None


def _append(root, row, *, name='enrichment_diagnostics.jsonl'):
    """Open only the named private regular file; never follow final symlinks."""
    if name not in {'enrichment_diagnostics.jsonl','research_timings.jsonl'}:
        raise ValueError('unknown_private_telemetry')
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            os.mkdir('private', mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        directory = os.open('private', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            directory_info = os.fstat(directory)
            if directory_info.st_uid != os.geteuid() or stat.S_IMODE(directory_info.st_mode) != 0o700:
                return
            fd = os.open(name, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
                    return
                os.fchmod(fd, 0o600)
                data = (json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
                if len(data) <= 2048:
                    os.write(fd, data)
            finally:
                os.close(fd)
        finally:
            os.close(directory)
    finally:
        os.close(root_fd)


def _emit(state, operation, provider, outcome, start, before, error=None, reason=None):
    try:
        if operation not in OPERATIONS or provider not in PROVIDERS or outcome not in OUTCOMES:
            return
        if operation in PHASES:
            if operation in state['phases']:
                return
            state['phases'].add(operation)
        else:
            if state['details'] >= MAX_DETAIL_RECORDS:
                state['dropped'] += 1
                return
            state['details'] += 1
        end = time.time()
        row = {key: state[key] for key in ('run_id', 'attempt_id', 'symbol')}
        row.update(stage='enrichment', provider=provider, operation=operation, outcome=outcome,
                   started_at=_number(start[0], 1e12), ended_at=_number(end, 1e12),
                   duration_seconds=_number(time.monotonic()-start[1], 1e9),
                   remaining_before=_number(before, 1e9), remaining_after=_number(_snapshot(), 1e9))
        if reason in REASONS:
            row['cache_reason'] = reason
        if error is not None:
            code = getattr(error, 'code', None)
            if type(code) is int and 100 <= code <= 599:
                row['http_status'] = code
        if operation == 'attempt':
            row['dropped_records'] = min(state['dropped'], 1_000_000)
        _append(state['root'], row)
    except BaseException:
        pass


@contextmanager
def span(operation, provider='local'):
    state = _active.get()
    if state is None:
        yield None
        return
    try:
        start = (time.time(), time.monotonic())
        before = _snapshot()
    except BaseException:
        yield None
        return
    result = {'outcome': 'completed'}
    error = None
    try:
        yield result
    except BaseException as caught:
        error = caught
        result['outcome'] = 'error'
        try:
            if isinstance(caught, ResearchDeadlineExceeded):
                result['outcome'] = 'deadline' if _snapshot() == 0 else 'cancelled'
            elif isinstance(caught, (TimeoutError, subprocess.TimeoutExpired)) or isinstance(getattr(caught, 'reason', None), TimeoutError):
                result['outcome'] = 'timeout'
            elif not isinstance(caught, Exception):
                result['outcome'] = 'cancelled'
            else:
                result['outcome'] = {'config': 'config_error', 'open': 'open_error', 'body': 'body_error', 'json': 'parse_error'}.get(operation, 'error')
        except BaseException:
            pass
        raise
    finally:
        try:
            _emit(state, operation, provider, result['outcome'], start, before, error, result.get('reason'))
        except BaseException:
            pass


@contextmanager
def attempt(enabled, root, run_id, symbol):
    if not enabled:
        yield
        return
    try:
        state = {'root': root, 'run_id': run_id if isinstance(run_id, str) and re.fullmatch('[a-f0-9]{32}', run_id) else uuid.uuid4().hex,
                 'attempt_id': uuid.uuid4().hex, 'symbol': symbol if isinstance(symbol, str) and re.fullmatch('[A-Z]{1,6}', symbol) else 'INVALID',
                 'details': 0, 'dropped': 0, 'phases': set()}
        token = _active.set(state)
    except BaseException:
        yield
        return
    try:
        with span('attempt'):
            yield
    finally:
        _active.reset(token)


def traced(operation, provider, result_kind=None):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if _active.get() is None:
                return function(*args, **kwargs)
            with span(operation, provider) as record:
                value = function(*args, **kwargs)
                if record is not None:
                    record['outcome'] = ('confirmed' if value is not None else 'no_date') if result_kind == 'date' else ('fetched' if value else 'empty') if result_kind == 'collection' else 'completed'
                return value
        return wrapped
    return decorate
