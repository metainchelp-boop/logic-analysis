"""실제 런타임 조립의 ERP 전송 검사. 합성 UNIX 소켓 외 연결은 금지한다."""
import io
import json
import urllib.parse
from threading import Event
from unittest import TestCase
from unittest.mock import MagicMock, patch

from naver_runtime import __main__ as M
from naver_runtime.config import Config
from naver_runtime.tests.test_erp_tunnel_transport import CODE, VERIFIER, KEY, SSO_KEY, reply, unix_erp


class TunnelWiringTest(TestCase):
    def test_runtime_erp_reader_uses_only_configured_unix_socket(self):
        with unix_erp(reply(b'{"status":200,"result":{}}')) as (path, received):
            env = {"NAVER_ENGINE_SYNC_ENABLED": "true", "NAVER_ENGINE_ERP_KEY": KEY,
                   "NAVER_ENGINE_ERP_TUNNEL_SOCKET": path}
            with patch.object(M.N, "UrllibTransport", side_effect=AssertionError("기존 HTTP 전송 금지")):
                options = M.dependencies(Config.from_env(env), env, M.InterruptibleClock(Event()))
                options["erp_factory"]().read_org_snapshot()
        self.assertEqual("GET /api/ad-sync/org-snapshot HTTP/1.1", received[0][0])

    def test_runtime_other_two_erp_reads_also_use_tunnel(self):
        stages = [s for spellings in M.E.STAGE_SPELLINGS.values() for s in spellings]
        for method, count, route in (("read_stages", len(stages), "/api/ad-sync/contracts"),
                                     ("read_naver_customer_ids", 1, "/api/ad-sync/naver-customer-ids")):
            with self.subTest(method=method), \
                 unix_erp(reply(b'{"status":200,"result":{"items":[],"total":0}}'), count=count) as (path, received):
                env = {"NAVER_ENGINE_SYNC_ENABLED": "true", "NAVER_ENGINE_ERP_KEY": KEY,
                       "NAVER_ENGINE_ERP_TUNNEL_SOCKET": path}
                with patch.object(M.N, "UrllibTransport", side_effect=AssertionError("기존 HTTP 전송 금지")):
                    options = M.dependencies(Config.from_env(env), env, M.InterruptibleClock(Event()))
                    getattr(options["erp_factory"](), method)()
            self.assertEqual(count, len(received))
            self.assertTrue(all(first.startswith("GET " + route) for first, _, _ in received))

    def test_missing_tunnel_never_falls_back_to_http_dns_or_tcp(self):
        env = {"NAVER_ENGINE_SYNC_ENABLED": "true", "NAVER_ENGINE_ERP_KEY": KEY,
               "NAVER_ENGINE_ERP_TUNNEL_SOCKET": "/synthetic/missing-tunnel/erp.sock"}
        with patch.object(M.N, "UrllibTransport", side_effect=AssertionError("기존 HTTP 전송 금지")), \
             patch("socket.socket", side_effect=AssertionError("소켓 생성 금지")), \
             patch("socket.getaddrinfo", side_effect=AssertionError("DNS 금지")):
            options = M.dependencies(Config.from_env(env), env, M.InterruptibleClock(Event()))
            with self.assertRaises(M.E.ErpError):
                options["erp_factory"]().read_org_snapshot()

    def test_stopped_runtime_never_starts_another_tunnel_send(self):
        env = {"NAVER_ENGINE_SYNC_ENABLED": "true", "NAVER_ENGINE_ERP_KEY": KEY}
        stop = Event()
        options = M.dependencies(Config.from_env(env), env, M.InterruptibleClock(stop))
        reader = options["erp_factory"]()
        stop.set()
        with patch.object(M.ErpTunnelTransport, "send", side_effect=AssertionError("중지 뒤 전송 금지")), \
             self.assertRaises(M.StopRequested):
            reader.read_org_snapshot()

    def test_naver_reader_keeps_existing_https_transport(self):
        env = {"NAVER_ENGINE_LINKS_ENABLED": "true", "NAVER_ENGINE_ERP_KEY": KEY,
               "NAVER_MGR_CUSTOMER_ID": "1234", "NAVER_MGR_API_KEY": "SYNTHETIC-manager-key",
               "NAVER_MGR_SECRET_KEY": "SYNTHETIC-manager-secret"}
        with patch.object(M.N.UrllibTransport, "send", return_value=(
                200, b'{"content":[],"totalElements":0,"last":true}')) as send, \
             patch.object(M.ErpTunnelTransport, "send", side_effect=AssertionError("네이버의 ERP 터널 사용 금지")):
            options = M.dependencies(Config.from_env(env), env, M.InterruptibleClock(Event()))
            reader = options["naver_factory"]()
            self.assertEqual([], reader.list_manager_accounts(reader.manager_handle()))
        request = send.call_args.args[0]
        url = urllib.parse.urlsplit(request.full_url)
        self.assertEqual(("https", "api.searchad.naver.com", "/manager-accounts"),
                         (url.scheme, url.hostname, url.path))

    def test_runtime_web_exchange_uses_tunnel_and_keeps_naver_control_destination(self):
        stop = Event()
        status = []
        body = json.dumps({"code": CODE, "codeVerifier": VERIFIER}).encode()
        writer = MagicMock()
        writer.__enter__.return_value = writer

        def server(_path, app):
            app({"PATH_INFO": "/api/naver-auto/session", "REQUEST_METHOD": "POST",
                 "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(body)),
                 "wsgi.input": io.BytesIO(body), "REMOTE_ADDR": "127.0.0.1"},
                lambda value, _headers: status.append(value))
            stop.set()
            return MagicMock()

        with unix_erp(reply(b"", status=401)) as (path, received):
            env = {"NAVER_ENGINE_WEB_ENABLED": "true", "NAVER_ENGINE_ERP_TUNNEL_SOCKET": path,
                   "SSO_NAVER_CONTROL_CLIENT_KEY": SSO_KEY,
                   "NAVER_AUTO_TOKEN_SECRET": "SYNTHETIC-token-signing-key-" + "x" * 40}
            with patch.object(M, "Writer", return_value=writer), patch.object(M, "UnixServer", side_effect=server), \
                    patch.object(M.N, "UrllibTransport", side_effect=AssertionError("기존 HTTP 전송 금지")):
                # 중지는 교환 뒤 적용한다. 소켓 요청은 실제 공개 WSGI 진입점을 통과한다.
                self.assertEqual(M.run(Config.from_env(env), env, stop=stop), 0)
        self.assertEqual(["401 Unauthorized"], status)
        self.assertEqual("POST /api/sso/exchange HTTP/1.1", received[0][0])
        self.assertEqual("NAVER_CONTROL", json.loads(received[0][2])["destination"])
