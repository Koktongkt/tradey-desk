"""A shared monotonic deadline for bounded research enrichment I/O."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from typing import Any, Iterator
import subprocess


class ResearchDeadlineExceeded(BaseException):
    """Deadline cancellation must not be swallowed as an ordinary source error."""


_active_deadline: ContextVar[float | None] = ContextVar("research_deadline", default=None)


@contextmanager
def active_deadline(deadline: float) -> Iterator[None]:
    prior = _active_deadline.get()
    token = _active_deadline.set(min(deadline, prior) if prior is not None else deadline)
    try:
        yield
    finally:
        _active_deadline.reset(token)


def remaining(max_seconds: float) -> float:
    deadline = _active_deadline.get()
    if deadline is None:
        return max_seconds
    seconds = deadline - monotonic()
    if seconds <= 0:
        raise ResearchDeadlineExceeded("research deadline exhausted")
    return min(max_seconds, seconds)


def raise_if_expired_timeout(error: BaseException) -> None:
    """Distinguish an exhausted research deadline from an earlier I/O outage."""
    deadline = _active_deadline.get()
    timed_out = isinstance(error, TimeoutError) or isinstance(getattr(error,"reason",None),TimeoutError)
    # subprocess.TimeoutExpired is not a subclass of the built-in TimeoutError.
    timed_out = timed_out or isinstance(error,subprocess.TimeoutExpired)
    if timed_out and deadline is not None and monotonic() >= deadline:
        raise ResearchDeadlineExceeded("research deadline exhausted during I/O") from error


def read_http_response(response: Any, max_bytes: int | None = None) -> bytes:
    """Bound each network recv by the live deadline, not just the first byte.

    HTTPResponse.read() may wait indefinitely on a trickling peer because the
    socket timeout restarts per recv. read1() makes at most one recv per call;
    refresh its socket timeout and check the monotonic deadline per chunk.
    Without an active research deadline preserve the adapter's prior read().
    """
    if _active_deadline.get() is None:
        return response.read() if max_bytes is None else response.read(max_bytes)
    limit = max_bytes if max_bytes is not None else 32_000_000
    chunks: list[bytes] = []
    total = 0
    while total < limit:
        seconds = remaining(30)
        if getattr(response, "isclosed", lambda: False)():
            break
        reader = getattr(response, "read1", None)
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if not callable(reader) or sock is None or not callable(getattr(sock, "settimeout", None)):
            raise ResearchDeadlineExceeded("HTTP response cannot be deadline-bounded")
        sock.settimeout(seconds)
        try:
            chunk = reader(min(65_536, limit - total))
        except OSError as error:
            raise_if_expired_timeout(error)
            raise
        if not isinstance(chunk, bytes):
            raise ResearchDeadlineExceeded("HTTP response yielded non-byte content")
        remaining(30)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)
