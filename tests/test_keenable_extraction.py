"""Offline boundary tests; no publisher or service network calls."""
import importlib
import io
import json
import socket
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

URL = 'https://unknown.example/story?a=1&b=two words'
RETURNED = 'https://news.unknown.example/story'
BODY = 'Company revenue guidance increased after strong demand. ' * 10


def payload(**updates):
    return {'url': RETURNED, 'title': 'Article', 'content': BODY,
            'published_at': 946684800, **updates}


class Response:
    def __init__(self, raw, status=200):
        self.data = io.BytesIO(raw)
        self.status = status
        self.closed = False
        self.read_sizes = []

    def read1(self, size):
        self.read_sizes.append(size)
        return self.data.read(size)

    def isclosed(self):
        return self.closed

    def close(self):
        self.closed = True


class KeenableTests(unittest.TestCase):
    def setUp(self):
        self.transport = importlib.import_module('keenable_extraction')
        self.clock = 10.0
        self.conn = Mock()
        self.conn.sock = Mock()
        self.factory = patch.object(self.transport.http.client, 'HTTPSConnection', return_value=self.conn)
        self.factory.start()
        self.addCleanup(self.factory.stop)
        timer = patch.object(self.transport.time, 'monotonic', side_effect=lambda: self.clock)
        timer.start()
        self.addCleanup(timer.stop)

    def fetch(self, data=None, *, raw=None, status=200):
        self.response = Response(json.dumps(payload() if data is None else data).encode() if raw is None else raw, status)
        self.conn.getresponse.return_value = self.response
        return self.transport.fetch(URL, deadline=20.0)

    def assert_failure(self, result, reason):
        self.assertEqual(result, {'version': 1, 'status': 'error', 'reason': reason})
        self.assertTrue(self.response.closed)
        self.conn.close.assert_called_once()

    def test_stream_limit_before_decode(self):
        with patch.object(self.transport, 'strict_json_loads', side_effect=AssertionError('must not decode')):
            result = self.fetch(raw=b'x' * 100001)
        self.assert_failure(result, 'output_limit')
        self.assertLessEqual(sum(self.response.read_sizes), 100001)

    def test_exact_stream_boundary_is_allowed(self):
        raw = json.dumps(payload()).encode()
        result = self.fetch(raw=raw + b' ' * (100000 - len(raw)))
        self.assertEqual(result['content'], BODY)

    def test_no_follow_service_redirect(self):
        self.assert_failure(self.fetch(status=302), 'provider_error')
        self.conn.request.assert_called_once()
        self.conn.getresponse.assert_called_once()
        self.assertEqual(self.response.read_sizes, [])

    def test_deadline_covers_reads(self):
        response = Response(json.dumps(payload()).encode())
        read = response.read1
        def delayed(size):
            data = read(size)
            self.clock = 21.0
            return data
        response.read1 = delayed
        self.conn.getresponse.return_value = response
        result = self.transport.fetch(URL, deadline=20.0)
        self.assertEqual(result['reason'], 'timeout')
        self.assertTrue(response.closed)
        self.conn.close.assert_called_once()

    def test_expired_budget_opens_no_connection(self):
        with patch.object(self.transport.http.client, 'HTTPSConnection') as factory:
            result = self.transport.fetch(URL, deadline=9.0)
        self.assertEqual(result['reason'], 'timeout')
        factory.assert_not_called()

    def test_response_closed_on_decode_failure(self):
        for raw in (b'not json', b'\xff', b'{"url":"a","url":"b"}',
                    b'{"value":NaN}', b'{"value":Infinity}', b'[]'):
            with self.subTest(raw=raw):
                self.conn.reset_mock()
                self.assert_failure(self.fetch(raw=raw), 'malformed_response')

    def test_error_declarations_never_become_pages(self):
        cases = [('error', value, 'malformed_response') for value in (False, 0, [], {})]
        cases += [('error', 'unavailable', 'provider_error'), ('success', False, 'provider_error'),
                  ('success', 0, 'malformed_response'), ('status', False, 'malformed_response'),
                  ('status', '', 'malformed_response'), ('status', 'unknown', 'malformed_response'),
                  ('status', 'failed', 'provider_error'), ('blocked_by_policy', True, 'provider_error'),
                  ('blocked_by_policy', 0, 'malformed_response')]
        for key, value, reason in cases:
            with self.subTest(key=key, value=value):
                self.conn.reset_mock()
                self.assert_failure(self.fetch(payload(**{key: value})), reason)

    def test_body_and_publication_from_same_response(self):
        result = self.fetch(payload(requested_url='https://forged.example', location_provenance='uncached_dispatch'))
        self.assertEqual(result, {'url': RETURNED, 'title': 'Article', 'content': BODY, 'error': None,
            'extraction_location': {'version': 1, 'requested_url': URL, 'returned_url': RETURNED},
            'publication': {'version': 1, 'basis': 'provider_reported', 'provider': 'keenable',
                            'field': 'published_at', 'value': '2000-01-01T00:00:00Z', 'precision': 'second'}})
        self.conn.request.assert_called_once()
        args, kwargs = self.conn.request.call_args
        self.assertEqual(args[0], 'GET')
        parts = urlsplit(args[1])
        self.assertEqual(parts.path, '/v1/fetch/public')
        self.assertEqual(parse_qs(parts.query), {'url': [URL]})
        self.assertFalse(any(k.lower() == 'authorization' for k in kwargs.get('headers', {})))
        self.transport.http.client.HTTPSConnection.assert_called_once_with('api.keenable.ai', timeout=10.0)
        self.assertTrue(self.response.closed)
        self.conn.close.assert_called_once()

    def test_bad_timestamp_omits_only_report(self):
        for stamp in (None, True, 946684800.0, 946684800000, '946684800'):
            with self.subTest(stamp=stamp):
                result = self.fetch(payload(published_at=stamp))
                self.assertEqual(result['content'], BODY)
                self.assertNotIn('publication', result)

    def test_missing_or_invalid_page_fields_fail_closed(self):
        for field, value in (('url', None), ('url', ''), ('url', 'x'*4097),
                             ('title', False), ('content', None), ('content', ''),
                             ('content', 'Access denied.')):
            with self.subTest(field=field, value=value):
                result = self.fetch(payload(**{field: value}))
                self.assertEqual(result['status'], 'error')
        data = payload(); del data['url']
        self.assertEqual(self.fetch(data)['reason'], 'malformed_response')

    def test_network_failure_is_typed_and_not_retried(self):
        for exc, reason in ((socket.timeout('private detail'), 'timeout'), (OSError('private detail'), 'provider_error')):
            with self.subTest(reason=reason):
                self.conn.reset_mock()
                self.conn.connect.side_effect = exc
                result = self.transport.fetch(URL, deadline=20.0)
                self.assertEqual(result, {'version': 1, 'status': 'error', 'reason': reason})
                self.conn.connect.assert_called_once()
                self.conn.close.assert_called_once()

    def test_tls_handshake_uses_remaining_connection_budget(self):
        context = self.conn._context
        sock = self.conn.sock
        def handshake(*args, **kwargs):
            self.assertTrue(sock.settimeout.called, 'TLS must not reuse TCP timeout')
            self.assertEqual(sock.settimeout.call_args.args, (2.0,))
            return sock
        context.wrap_socket.side_effect = handshake
        def connect():
            self.clock = 18.0
            self.conn.sock = self.conn._context.wrap_socket(sock, server_hostname='api.keenable.ai')
        self.conn.connect.side_effect = connect
        result = self.fetch()
        self.assertEqual(result['content'], BODY)
        context.wrap_socket.assert_called_once_with(sock, server_hostname='api.keenable.ai')
        self.assertEqual(sock.settimeout.call_args_list[0].args, (2.0,))

    def test_real_http_response_handles_connection_close_and_chunked_body(self):
        import http.client
        for chunked in (False, True):
            with self.subTest(chunked=chunked):
                client, server = socket.socketpair()
                self.addCleanup(client.close)
                self.addCleanup(server.close)
                raw = json.dumps(payload()).encode()
                if chunked:
                    headers = b'Transfer-Encoding: chunked\r\n'
                    body = format(len(raw), 'x').encode() + b'\r\n' + raw + b'\r\n0\r\n\r\n'
                else:
                    headers = b'Content-Length: ' + str(len(raw)).encode() + b'\r\n'
                    body = raw
                server.sendall(b'HTTP/1.1 200 OK\r\nConnection: close\r\n' + headers + b'\r\n' + body)
                conn = http.client.HTTPConnection('fixture')
                conn._context = Mock()  # TLS is replaced by the socketpair fixture.
                conn.connect = lambda: setattr(conn, 'sock', client)
                with patch.object(self.transport.http.client, 'HTTPSConnection', return_value=conn):
                    result = self.transport.fetch(URL, deadline=20.0)
                self.assertEqual(result.get('content'), BODY, result)
                self.assertTrue(client._closed)

    def test_each_socket_read_uses_same_absolute_deadline(self):
        sock = Mock()
        def receive(buffer):
            self.clock += 3
            buffer[0] = 120
            return 1
        sock.makefile.return_value.readinto.side_effect = receive
        reader = self.transport._DeadlineReader(sock, 20.0)
        self.assertEqual(reader.readinto(bytearray(1)), 1)
        self.assertEqual(reader.readinto(bytearray(1)), 1)
        self.assertEqual([call.args[0] for call in sock.settimeout.call_args_list], [10.0, 7.0])
        self.clock = 21
        with self.assertRaises(TimeoutError):
            reader.readinto(bytearray(1))
        self.assertEqual(sock.makefile.return_value.readinto.call_count, 2)
        reader.close()

    def test_timeouts_shrink_between_transport_phases(self):
        self.conn.connect.side_effect = lambda: setattr(self, 'clock', 12.0)
        self.conn.request.side_effect = lambda *a, **k: setattr(self, 'clock', 14.0)
        result = self.fetch()
        self.assertEqual(result['content'], BODY)
        timeouts = [call.args[0] for call in self.conn.sock.settimeout.call_args_list]
        self.assertIn(8.0, timeouts)
        self.assertIn(6.0, timeouts)
        self.assertTrue(all(0 < timeout <= 10 for timeout in timeouts))


if __name__ == '__main__':
    unittest.main()
