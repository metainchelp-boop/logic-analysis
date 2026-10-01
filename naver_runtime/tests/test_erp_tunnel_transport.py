"""전용 Unix socket 전송 시험 — 합성 자료·로컬 socket만, DNS/TCP/운영 키 없음."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import traceback
import unittest
import urllib.parse
import urllib.request
from unittest.mock import patch

from naver_engine import erp_read as E
from naver_engine import erp_profile as EP
from naver_engine.credentials import Secret
from naver_runtime.erp_tunnel_transport import ErpTunnelError, ErpTunnelTransport


KEY = "TEST-ONLY-ERP-KEY-" + "x" * 32
SSO_KEY = "a1" * 32
CODE, VERIFIER = "C" * 42 + "A", "V" * 42 + "A"


@contextlib.contextmanager
def unix_erp(response, count=1):
    """정해진 횟수만 응답하는 합성 ERP. 바깥 네트워크 시도는 즉시 실패한다."""
    with tempfile.TemporaryDirectory(prefix="erp-", dir="/tmp") as temp:
        path = str(Path(temp).resolve() / "erp.sock")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(path)
        os.chmod(path, 0o600)
        listener.listen(1)
        listener.settimeout(2)
        received = []
        errors = []

        def serve():
            try:
                for _ in range(count):
                    conn, _ = listener.accept()
                    with conn:
                        conn.settimeout(2)
                        stream = conn.makefile("rb")
                        with stream:
                            first = stream.readline().decode("ascii").rstrip("\r\n")
                            headers = {}
                            while True:
                                line = stream.readline()
                                if line == b"\r\n":
                                    break
                                name, value = line.decode("ascii").split(":", 1)
                                headers[name.lower()] = value.strip()
                            body = stream.read(int(headers.get("content-length", "0")))
                            received.append((first, headers, body))
                            if callable(response):
                                response(conn)
                            else:
                                conn.sendall(response)
            except (BrokenPipeError, ConnectionResetError):
                pass  # 거절/마감 시험은 응답을 기다리지 않고 닫을 수 있다.
            except Exception as error:
                errors.append((type(error).__name__, getattr(error, "errno", None)))

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        real_socket = socket.socket

        def unix_only(family=socket.AF_INET, *args, **kwargs):
            if family != socket.AF_UNIX:
                raise AssertionError("TCP 금지")
            return real_socket(family, *args, **kwargs)

        try:
            with patch("socket.socket", side_effect=unix_only), \
                    patch("socket.getaddrinfo", side_effect=AssertionError("DNS 금지")):
                yield path, received
        finally:
            thread.join(3)
            listener.close()
        if errors:
            raise AssertionError(errors)
        if thread.is_alive():
            raise AssertionError("합성 서버 종료 실패")


def reply(body, status=200, headers=b""):
    return (f"HTTP/1.1 {status} Test\r\nContent-Length: {len(body)}\r\n".encode()
            + headers + b"\r\n" + body)


def request(path=E.PATH_ORG_SNAPSHOT, *, method="GET", url=None, headers=None, body=None):
    return urllib.request.Request(url or E.BASE_URL + path, method=method, data=body,
                                  headers=headers or {"Accept": "application/json", "X-Api-Key": KEY})


def exchange_request():
    return request(method="POST", url=EP.BASE_URL + EP.PATH_EXCHANGE,
                   headers={"Accept": "application/json", "Content-Type": "application/json",
                            "X-Sso-Client-Key": SSO_KEY},
                   body=json.dumps({"destination": "NAVER_CONTROL", "code": CODE,
                                    "codeVerifier": VERIFIER}).encode())


class ErpTunnelTests(unittest.TestCase):
    def test_real_contract_and_customer_readers_keep_exact_query_under_proxy_environment(self):
        stages = [s for spellings in E.STAGE_SPELLINGS.values() for s in spellings]
        proxy = {name: "http://outside.invalid:8000" for name in
                 ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")}
        with patch.dict(os.environ, proxy):
            with unix_erp(reply(b'{"status":200,"result":{"items":[],"total":0}}'),
                          count=len(stages)) as (path, received):
                reader = E.ErpReader(Secret(KEY), transport=ErpTunnelTransport(path))
                self.assertEqual({}, reader.read_stages().rows)
            self.assertEqual(stages, [urllib.parse.parse_qs(first.split(" ")[1].split("?", 1)[1])["stage"][0]
                                      for first, _, _ in received])
            self.assertTrue(all("has_contract=true" in first for first, _, _ in received))
            with unix_erp(reply(b'{"status":200,"result":{"items":[]}}')) as (path, received):
                reader = E.ErpReader(Secret(KEY), transport=ErpTunnelTransport(path))
                self.assertEqual((), reader.read_naver_customer_ids())
            self.assertEqual("GET /api/ad-sync/naver-customer-ids HTTP/1.1", received[0][0])
        self.assertEqual("http://api.metainc.co.kr", E.BASE_URL)

    def test_chunked_response_is_bounded_and_truncation_is_not_success(self):
        prefix = b"HTTP/1.1 200 Test\r\nTransfer-Encoding: chunked\r\n\r\n"
        with unix_erp(prefix + b"2\r\n{}\r\n0\r\n\r\n") as (path, _):
            self.assertEqual((200, b"{}"), ErpTunnelTransport(path).send(request(), 1))
        for response in (prefix + b"5\r\n{}", prefix + b"40001\r\n" + b"x" * (EP.MAX_BODY + 1)
                         + b"\r\n0\r\n\r\n"):
            with unix_erp(response) as (path, _):
                with self.assertRaises(ErpTunnelError):
                    ErpTunnelTransport(path).send(exchange_request(), 1)

    def test_error_bodies_are_discarded_and_sso_denial_keeps_401_without_retry(self):
        marker = b"TEST-ONLY-PRIVATE-ERROR-BODY"
        with unix_erp(reply(marker, 401)) as (path, received):
            self.assertEqual((401, b""), ErpTunnelTransport(path).send(exchange_request(), 1))
            self.assertEqual(1, len(received))
        with unix_erp(reply(marker, 401)) as (path, received):
            reader = EP.ErpProfileReader(transport=ErpTunnelTransport(path),
                                         env={"SSO_NAVER_CONTROL_CLIENT_KEY": SSO_KEY})
            with self.assertRaises(EP.ProfileError) as error:
                reader.read_profile(Secret(CODE), Secret(VERIFIER))
            self.assertEqual(EP.KIND_REJECTED, error.exception.kind)
            self.assertEqual(401, error.exception.status)
            self.assertEqual(1, len(received))

    def test_failure_has_no_path_key_response_or_raw_exception_in_output(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with unix_erp(b"TEST-ONLY-PRIVATE-RESPONSE\r\n\r\n") as (path, _):
                try:
                    ErpTunnelTransport(path).send(exchange_request(), 1)
                except ErpTunnelError as error:
                    rendered = str(error) + repr(error) + traceback.format_exc()
                else:
                    self.fail("실패해야 합니다")
        self.assertEqual("", stdout.getvalue() + stderr.getvalue())
        for marker in (path, KEY, SSO_KEY, CODE, VERIFIER, "TEST-ONLY-PRIVATE-RESPONSE"):
            self.assertNotIn(marker, rendered)

    def test_writable_nonsticky_ancestor_cannot_replace_a_private_socket_directory(self):
        with tempfile.TemporaryDirectory(prefix="erp-", dir="/tmp") as temp:
            ancestor = Path(temp).resolve()
            directory = ancestor / "private"
            directory.mkdir(mode=0o700)
            path = directory / "erp.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(path))
                os.chmod(path, 0o600)
                os.chmod(ancestor, 0o777)
                with patch("socket.socket", side_effect=AssertionError("연결 전 거절 필요")):
                    with self.assertRaises(ErpTunnelError):
                        ErpTunnelTransport(str(path)).send(request(), 1)

    def test_json_array_and_invalid_timeout_are_rejected_before_filesystem(self):
        array = exchange_request()
        array.data = json.dumps([["destination", "NAVER_CONTROL"], ["code", CODE],
                                 ["codeVerifier", VERIFIER]]).encode()
        cases = [(array, 1)] + [(request(), timeout) for timeout in
                               (0, -1, True, None, "1", float("inf"), float("nan"), 31)]
        cases.append((exchange_request(), 9))
        for candidate, timeout in cases:
            with self.subTest(timeout=timeout):
                with patch("os.lstat", side_effect=AssertionError("요청부터 검증 필요")):
                    with self.assertRaises(ErpTunnelError):
                        ErpTunnelTransport("/does-not-exist/erp.sock").send(candidate, timeout)

    def test_unsafe_socket_paths_fail_before_connect_without_path_disclosure(self):
        with tempfile.TemporaryDirectory(prefix="erp-", dir="/tmp") as temp:
            directory = Path(temp).resolve()
            path = directory / "test-only-private-socket.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(path))
                os.chmod(path, 0o600)
                link = directory / "link.sock"
                link.symlink_to(path)
                regular = directory / "regular"
                regular.touch()
                cases = ("relative.sock", "", "\x00abstract", str(directory / "missing"),
                         str(regular), str(link), str(directory / ".." / directory.name / path.name))
                for candidate in cases:
                    with self.subTest(case=cases.index(candidate)):
                        with patch("socket.socket", side_effect=AssertionError("연결 전 거절 필요")) as factory:
                            with self.assertRaises(ErpTunnelError) as error:
                                ErpTunnelTransport(candidate).send(request(), 1)
                            factory.assert_not_called()
                        self.assertEqual("erp-tunnel-unavailable", str(error.exception))
                os.chmod(path, 0o666)
                with patch("socket.socket", side_effect=AssertionError("연결 전 거절 필요")) as factory:
                    with self.assertRaises(ErpTunnelError):
                        ErpTunnelTransport(str(path)).send(request(), 1)
                    factory.assert_not_called()
                os.chmod(path, 0o600)
                os.chmod(directory, 0o770)
                with patch("socket.socket", side_effect=AssertionError("연결 전 거절 필요")) as factory:
                    with self.assertRaises(ErpTunnelError):
                        ErpTunnelTransport(str(path)).send(request(), 1)
                    factory.assert_not_called()

    def test_timeout_is_total_including_slow_headers_not_reset_per_byte(self):
        def slow(conn):
            for byte in reply(b"{}"):
                conn.sendall(bytes([byte]))
                time.sleep(0.015)

        start = time.monotonic()
        with unix_erp(slow) as (path, received):
            with self.assertRaises(ErpTunnelError):
                ErpTunnelTransport(path).send(request(), 0.06)
        self.assertLess(time.monotonic() - start, 0.5)
        self.assertEqual(1, len(received))

    def test_oversize_truncated_ambiguous_or_redirect_response_never_succeeds(self):
        candidates = (
            reply(b"x" * (EP.MAX_BODY + 1)),
            b"HTTP/1.1 200 Test\r\nContent-Length: 100\r\n\r\n{}",
            b"HTTP/1.1 200 Test\r\nContent-Length: 2\r\nContent-Length: 3\r\n\r\n{}",
            b"HTTP/1.1 200 Test\r\nContent-Length: 2\r\nTransfer-Encoding: chunked\r\n\r\n{}",
            reply(b"", 302, b"Location: http://outside.invalid/\r\n"),
            b"PRIVATE-RESPONSE-MARK\r\n\r\n",
        )
        for candidate in candidates:
            with self.subTest(case=candidates.index(candidate)):
                with unix_erp(candidate) as (path, received):
                    with self.assertRaises(ErpTunnelError):
                        ErpTunnelTransport(path).send(exchange_request(), 1)
                    self.assertEqual(1, len(received))

    def test_query_headers_and_exchange_body_are_closed_before_connect(self):
        candidates = [request(E.PATH_CONTRACTS + "?" + query) for query in (
            "", "stage=x&has_contract=true", "stage=%EC%A7%84%ED%96%89%EC%A4%91&has_contract=false",
            "stage=%EC%A7%84%ED%96%89%EC%A4%91&has_contract=true&has_contract=true",
            "stage=%EC%A7%84%ED%96%89%EC%A4%91&has_contract=true&extra=x",
        )]
        candidates += [request(E.PATH_ORG_SNAPSHOT + "?stage=x"), request(body=b"{}")]
        for name, value in (("Host", "attacker.invalid"), ("Authorization", "Bearer test"),
                            ("X-Forwarded-For", "127.0.0.1"), ("Cookie", "x=y"),
                            ("Content-Length", "0"), ("Transfer-Encoding", "chunked"),
                            ("X-Api-Key", KEY + "\r\nHost: bad"), ("Accept", "*/*")):
            candidates.append(request(headers={"Accept": "application/json", "X-Api-Key": KEY, name: value}))
        duplicate = request()
        duplicate.unredirected_hdrs["x-api-key"] = KEY
        candidates.append(duplicate)
        for body in (
            b'{"destination":"AD_CENTER","code":"x","codeVerifier":"x"}',
            b'{"destination":"NAVER_CONTROL","destination":"NAVER_CONTROL","code":"x","codeVerifier":"x"}',
            json.dumps({"destination": "NAVER_CONTROL", "code": CODE, "codeVerifier": VERIFIER,
                        "extra": "x"}).encode(),
            b"x" * 1025,
        ):
            candidates.append(request(method="POST", url=EP.BASE_URL + EP.PATH_EXCHANGE,
                                      headers={"Accept": "application/json", "Content-Type": "application/json",
                                               "X-Sso-Client-Key": SSO_KEY}, body=body))
        with patch("socket.socket", side_effect=AssertionError("연결 전 거절 필요")), \
                patch("os.lstat", side_effect=AssertionError("요청부터 검증 필요")):
            for index, candidate in enumerate(candidates):
                with self.subTest(case=index):
                    with self.assertRaises(ErpTunnelError):
                        ErpTunnelTransport("/does-not-exist/erp.sock").send(candidate, 1)

    def test_wrong_method_origin_or_path_is_rejected_before_any_socket(self):
        candidates = [request(method=m) for m in ("HEAD", "POST", "PUT", "DELETE", "CONNECT")]
        candidates += [request(url=url) for url in (
            "http://other.invalid" + E.PATH_ORG_SNAPSHOT,
            "http://api.metainc.co.kr:80" + E.PATH_ORG_SNAPSHOT,
            "http://user@api.metainc.co.kr" + E.PATH_ORG_SNAPSHOT,
            "https://api.metainc.co.kr" + E.PATH_ORG_SNAPSHOT,
            E.BASE_URL + E.PATH_ORG_SNAPSHOT + "#fragment",
            E.BASE_URL + "/api/sso/code",
            E.BASE_URL + "/api/ad-sync/../ad-sync/org-snapshot",
            E.BASE_URL + "/api/ad-sync/%6frg-snapshot",
            E.BASE_URL + "/api/ad-sync/org-snapshot/",
        )]
        with patch("socket.socket", side_effect=AssertionError("연결 전 거절 필요")), \
                patch("os.lstat", side_effect=AssertionError("요청부터 검증 필요")):
            for candidate in candidates:
                with self.subTest(url=candidate.full_url, method=candidate.get_method()):
                    with self.assertRaises(ErpTunnelError):
                        ErpTunnelTransport("/does-not-exist/erp.sock").send(candidate, 1)

    def test_real_profile_reader_keeps_logical_https_and_naver_control_body(self):
        body = b'{"status":200,"result":{"idx":0,"isManager":true,"teamList":[]}}'
        with unix_erp(reply(body)) as (path, received):
            reader = EP.ErpProfileReader(transport=ErpTunnelTransport(path),
                                         env={"SSO_NAVER_CONTROL_CLIENT_KEY": SSO_KEY})
            profile = reader.read_profile(Secret(CODE), Secret(VERIFIER))
            self.assertEqual(0, profile.idx)
        self.assertEqual("https://api.metainc.co.kr", EP.BASE_URL)
        self.assertEqual("POST /api/sso/exchange HTTP/1.1", received[0][0])
        self.assertEqual(SSO_KEY, received[0][1]["x-sso-client-key"])
        self.assertEqual({"destination": "NAVER_CONTROL", "code": CODE, "codeVerifier": VERIFIER},
                         json.loads(received[0][2]))

    def test_real_org_reader_uses_only_unix_socket_and_fixed_host(self):
        result = {"generated_at": "synthetic", "teams": [], "employees": [], "owners": []}
        body = json.dumps({"status": 200, "result": result}).encode()
        with unix_erp(reply(body)) as (path, received):
            reader = E.ErpReader(Secret(KEY), transport=ErpTunnelTransport(path))
            self.assertEqual(result, reader.read_org_snapshot())
        self.assertEqual("GET /api/ad-sync/org-snapshot HTTP/1.1", received[0][0])
        self.assertEqual("api.metainc.co.kr", received[0][1]["host"])
        self.assertEqual(KEY, received[0][1]["x-api-key"])
        self.assertEqual(b"", received[0][2])


if __name__ == "__main__":
    unittest.main()
