"""Single-response, anonymous Keenable transport; no cache, retries or redirects.

The caller owns URL safety, website policy and provider-routing authorization.
Returned locations and timestamps are provider reports, not authenticated facts.
Synchronous network work belongs in the parent's hard-deadline research child.
"""
import http.client
import io
import socket
import time
from urllib.parse import urlencode

from extraction_contract import strict_json_loads, is_error_document
from extraction_worker import declaration_failure, error
from publication_provenance import provider_publication

MAX_RAW_BYTES = 100_000


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining


def _deadline_tcp(address, *, deadline, source_address=None):
    """Resolve once, then budget each TCP candidate against one deadline.

    DNS itself is not cancellable here; the Task 4 parent must hard-kill the
    research child. No TCP work may start with a stale pre-resolution budget.
    """
    _remaining(deadline)
    host, port = address
    addresses = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    _remaining(deadline)
    last_error = OSError('getaddrinfo returns an empty list')
    for family, kind, protocol, _, sockaddr in addresses:
        _remaining(deadline)
        sock = None
        connected = False
        try:
            sock = socket.socket(family, kind, protocol)
            if source_address:
                sock.bind(source_address)
            sock.settimeout(_remaining(deadline))
            sock.connect(sockaddr)
            _remaining(deadline)
            connected = True
            return sock
        except OSError as exc:
            last_error = exc
        finally:
            if sock is not None and not connected:
                sock.close()
        _remaining(deadline)
    raise last_error


class _DeadlineTLS:
    """Refresh TLS's total handshake timeout after DNS/TCP consumed time."""
    def __init__(self, context, deadline):
        self.context = context
        self.deadline = deadline

    def wrap_socket(self, sock, **kwargs):
        sock.settimeout(_remaining(self.deadline))
        wrapped = self.context.wrap_socket(sock, **kwargs)
        try:
            _remaining(self.deadline)
        except TimeoutError:
            wrapped.close()
            raise
        return wrapped


class _DeadlineReader(io.RawIOBase):
    """Renew the *remaining* budget on every socket read, including headers."""
    def __init__(self, sock, deadline):
        super().__init__()
        self.sock = sock
        self.deadline = deadline
        # SocketIO retains the descriptor if http.client closes its connection
        # after headers (Connection: close) but before the response is consumed.
        self.raw = sock.makefile('rb', buffering=0)

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(_remaining(self.deadline))
        size = self.raw.readinto(buffer)
        _remaining(self.deadline)
        return size


class _DeadlineSocket:
    """Keep HTTPResponse's buffered/header reads inside the caller's deadline."""
    def __init__(self, sock, deadline):
        self.sock = sock
        self.deadline = deadline

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def makefile(self, mode, buffering=None):
        # http.client only requests 'rb'. Connection owns/closes the socket;
        # the response independently owns/closes this buffered reader.
        return io.BufferedReader(_DeadlineReader(self.sock, self.deadline))


def fetch(url: str, *, deadline: float) -> dict:
    """Fetch one raw page, or a version-1 typed error without private details."""
    connection = response = None
    try:
        if not isinstance(url, str) or not 1 <= len(url) <= 4096:
            return error('invalid_request')
        connection = http.client.HTTPSConnection('api.keenable.ai', timeout=_remaining(deadline))
        # The fixed endpoint has no proxy tunnel. stdlib HTTPSConnection uses
        # its context only to wrap this connected socket, preserving cert checks.
        # HTTPConnection's private TCP factory hook is stdlib coupling, like
        # _context below. Ignore its stale timeout; retain the absolute deadline.
        connection._create_connection = lambda address, timeout, source_address: _deadline_tcp(
            address, deadline=deadline, source_address=source_address)
        connection._context = _DeadlineTLS(connection._context, deadline)
        connection.connect()
        sock = connection.sock
        sock.settimeout(_remaining(deadline))
        connection.sock = _DeadlineSocket(sock, deadline)
        connection.request('GET', '/v1/fetch/public?' + urlencode({'url': url}),
                           headers={'Accept': 'application/json', 'Connection': 'close'})
        sock.settimeout(_remaining(deadline))
        response = connection.getresponse()
        _remaining(deadline)
        if response.status != 200:
            return error('provider_error')
        raw = bytearray()
        while True:
            sock.settimeout(_remaining(deadline))
            chunk = response.read1(min(8192, MAX_RAW_BYTES + 1 - len(raw)))
            _remaining(deadline)
            raw.extend(chunk)
            if len(raw) > MAX_RAW_BYTES:
                return error('output_limit')
            if not chunk or response.isclosed():
                break
        payload = strict_json_loads(raw)
        if not isinstance(payload, dict):
            return error('malformed_response')
        reason = declaration_failure(payload)
        if reason:
            return error(reason)
        returned, title, content = payload.get('url'), payload.get('title', ''), payload.get('content')
        if (not isinstance(returned, str) or not 1 <= len(returned) <= 4096
                or not isinstance(title, str) or not isinstance(content, str)):
            return error('malformed_response')
        if not content.strip() or is_error_document(content, title):
            return error('empty_content')
        row = {'url': returned, 'title': title, 'content': content, 'error': None,
               'extraction_location': {'version': 1, 'requested_url': url, 'returned_url': returned}}
        publication = provider_publication(payload.get('published_at'))
        if publication is not None:
            row['publication'] = publication
        _remaining(deadline)
        return row
    except TimeoutError:
        return error('timeout')
    except (ValueError, UnicodeError, RecursionError):
        return error('malformed_response')
    except (OSError, http.client.HTTPException):
        return error('provider_error')
    finally:
        try:
            if response is not None:
                response.close()
        finally:
            if connection is not None:
                connection.close()
