"""합성 HTTPResponse와 시계만 사용한다. 실제 소켓·외부 네이버·운영 자격은 없다."""
import http.client
import io
import socket
import ssl
import unittest
import urllib.request
from unittest.mock import Mock, patch

from naver_engine import naver_read as N


class DripSocket:
    def __init__(self, body, clock):
        self.timeout = 0.2
        self.clock = clock
        self.bytes = [b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n",
                      *(bytes([value]) for value in body)]
        self.headers_read = False

    def settimeout(self, seconds):
        self.timeout = seconds

    def makefile(self, mode):
        return io.BufferedReader(socket.SocketIO(self, mode))

    def recv_into(self, target):
        if not self.bytes:
            return 0
        if self.headers_read:
            if self.timeout < 0.05:
                self.clock[0] += self.timeout
                raise TimeoutError("PRIVATE_RESPONSE_BODY")
            self.clock[0] += 0.05
        chunk = self.bytes.pop(0)
        target[:len(chunk)] = chunk
        self.headers_read = True
        return len(chunk)

    def _decref_socketios(self):
        pass


class NetworkDeadlineDiagnosticsTests(unittest.TestCase):
    def test_drip_body_cannot_extend_the_total_transport_timeout(self):
        clock = [0.0]
        sock = DripSocket(b"{" + b" " * 22 + b"}", clock)
        response = http.client.HTTPResponse(sock)
        response.begin()
        transport = N.UrllibTransport.__new__(N.UrllibTransport)
        transport._opener = Mock()
        transport._opener.open.return_value = response
        request = urllib.request.Request("https://api.searchad.naver.com/ncc/campaigns", method="GET")
        with patch.object(N.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(N.TransportNetworkError) as raised:
                transport.send(request, 0.2)
        self.assertLessEqual(clock[0], 0.2)
        self.assertEqual((raised.exception.diagnostic.phase, raised.exception.diagnostic.elapsed_ms,
                          raised.exception.diagnostic.remaining_ms), ("BODY", 200, 0))
        self.assertEqual(raised.exception.diagnostic.kind, "DEADLINE")

    def test_http_error_body_has_the_same_total_deadline(self):
        clock = [0.0]
        response = http.client.HTTPResponse(DripSocket(b"PRIVATE_BODY" * 2, clock))
        response.begin()
        transport = N.UrllibTransport.__new__(N.UrllibTransport)
        transport._opener = Mock()
        request = urllib.request.Request("https://api.searchad.naver.com/ncc/campaigns", method="GET")
        transport._opener.open.side_effect = urllib.error.HTTPError(request.full_url, 503, "PRIVATE", {}, response)
        with patch.object(N.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(N.TransportNetworkError) as raised:
                transport.send(request, 0.2)
        self.assertLessEqual(clock[0], 0.2)
        self.assertEqual(raised.exception.diagnostic.phase, "BODY")
        self.assertTrue(response.isclosed())

    def test_body_buffer_before_deadline_and_size_limit_are_preserved(self):
        transport = N.UrllibTransport.__new__(N.UrllibTransport)
        transport._opener = Mock()
        request = urllib.request.Request("https://api.searchad.naver.com/ncc/campaigns", method="GET")
        for body in (b"", b'{"ok":true}', b"0123456789"):
            response = Mock(status=200)
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.side_effect = lambda limit: body[:limit]
            transport._opener.open.return_value = response
            with patch.object(N, "MAX_BODY", 8), patch.object(N.time, "monotonic", return_value=0):
                self.assertEqual(transport.send(request, 0.2), (200, body[:9]))
            response.read.assert_called_once_with(9)

    def test_open_failure_kind_and_private_reason_are_sanitized(self):
        transport = N.UrllibTransport.__new__(N.UrllibTransport)
        transport._opener = Mock()
        request = urllib.request.Request("https://api.searchad.naver.com/ncc/campaigns?private=PRIVATE_URL", method="GET")
        failures = ((socket.gaierror(-2, "PRIVATE_DNS"), "DNS"),
                    (ssl.SSLCertVerificationError(1, "PRIVATE_CERT"), "TLS_CERT"),
                    (ssl.SSLError(1, "PRIVATE_TLS"), "TLS"),
                    (TimeoutError("PRIVATE_TIMEOUT"), "TIMEOUT"),
                    (ConnectionResetError("PRIVATE_RESET"), "RESET"),
                    (ConnectionRefusedError("PRIVATE_REFUSED"), "REFUSED"),
                    (http.client.IncompleteRead(b"PRIVATE_BODY"), "HTTP_INCOMPLETE"),
                    (http.client.RemoteDisconnected("PRIVATE_DISCONNECT"), "HTTP_DISCONNECTED"),
                    (urllib.error.URLError("PRIVATE_REASON"), "OTHER"))
        for failure, kind in failures:
            with self.subTest(kind=kind):
                transport._opener.open.side_effect = urllib.error.URLError(failure)
                with patch.object(N.time, "monotonic", side_effect=[0, 0.05]):
                    with self.assertRaises(N.TransportNetworkError) as raised:
                        transport.send(request, 0.2)
                self.assertEqual(raised.exception.diagnostic, N.NetworkDiagnostic(kind, "OPEN", "NONE", 50, 150))
                self.assertNotIn("PRIVATE", str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(raised.exception.__suppress_context__)

    def test_chunked_body_headers_cannot_extend_the_total_deadline(self):
        clock = [0.0]
        sock = DripSocket(b"", clock)
        sock.bytes = [b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n",
                      *(bytes([value]) for value in b"1\r\nx\r\n0\r\n\r\n")]
        response = http.client.HTTPResponse(sock)
        response.begin()
        transport = N.UrllibTransport.__new__(N.UrllibTransport)
        transport._opener = Mock()
        transport._opener.open.return_value = response
        request = urllib.request.Request("https://api.searchad.naver.com/ncc/campaigns", method="GET")
        with patch.object(N.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(N.TransportNetworkError) as raised:
                transport.send(request, 0.2)
        self.assertLessEqual(clock[0], 0.2)
        self.assertEqual(raised.exception.diagnostic.phase, "BODY")

    def test_open_overrun_is_detected_before_body_read_and_preserves_open_phase(self):
        for http_error in (False, True):
            with self.subTest(http_error=http_error):
                clock = [0.0]
                response = http.client.HTTPResponse(DripSocket(b"PRIVATE_BODY", clock))
                response.begin()
                transport = N.UrllibTransport.__new__(N.UrllibTransport)
                transport._opener = Mock()
                request = urllib.request.Request("https://api.searchad.naver.com/ncc/campaigns", method="GET")

                def slow_open(*args, **kwargs):
                    clock[0] = 0.5
                    if http_error:
                        raise urllib.error.HTTPError(request.full_url, 503, "PRIVATE", {}, response)
                    return response

                transport._opener.open.side_effect = slow_open
                with patch.object(N.time, "monotonic", side_effect=lambda: clock[0]), \
                        patch.object(response, "read", side_effect=AssertionError("must not read body")):
                    with self.assertRaises(N.TransportNetworkError) as raised:
                        transport.send(request, 0.2)
                self.assertEqual(raised.exception.diagnostic, N.NetworkDiagnostic("DEADLINE", "OPEN", "NONE", 500, 0))
                self.assertTrue(response.isclosed())

    def test_request_step_never_includes_an_account_number_or_unknown_path(self):
        self.assertEqual(N._request_step("/manager-accounts/123456/child-ad-accounts"), "CHILD_ACCOUNTS")
        self.assertEqual(N._request_step("/billing/bizmoney"), "BIZMONEY")
        self.assertEqual(N._request_step("/PRIVATE_ACCOUNT?token=PRIVATE"), "NONE")

    def test_diagnostic_timing_cannot_overflow_or_accept_non_finite_values(self):
        for value, expected in ((1e308, 3_600_000), (-1e308, 0), (float("inf"), 0),
                                (float("nan"), 0), (True, 0), ("PRIVATE", 0)):
            with self.subTest(value_type=type(value).__name__):
                self.assertEqual(N._milliseconds(value), expected)


if __name__ == "__main__":
    unittest.main()
