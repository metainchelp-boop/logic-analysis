import io
from threading import Event
from unittest import TestCase
from unittest.mock import patch, MagicMock

from naver_runtime import __main__ as M
from naver_runtime.config import Config


class WebWiringTest(TestCase):
    def test_runtime_always_assembles_owner_verification_web(self):
        stop = Event()
        stop.set()
        env = {'SSO_NAVER_CONTROL_CLIENT_KEY': '0123456789abcdef' * 4,
               'NAVER_AUTO_TOKEN_SECRET': 'local-test-token-signing-value-000000000000'}
        with patch.object(M, 'Writer', return_value=MagicMock()), \
             patch.object(M, 'UnixServer', return_value=MagicMock()) as server:
            self.assertEqual(M.run(Config('/tmp/synthetic/data/db', '/tmp/synthetic/socket/api',
                                          web_enabled=True), env, stop=stop), 0)
        app = server.call_args.args[1]
        status = []
        app({'PATH_INFO': '/api/naver-auto/links/preview', 'REQUEST_METHOD': 'POST',
             'wsgi.input': io.BytesIO()}, lambda s, h: status.append(int(s[:3])))
        self.assertEqual(status, [403])

    def test_switch_can_be_configured_but_default_is_off(self):
        self.assertFalse(Config.from_env({}).web_enabled)
        self.assertTrue(Config.from_env({'NAVER_ENGINE_WEB_ENABLED':'true'}).web_enabled)

    def test_missing_exchange_key_fails_before_writer(self):
        with patch.object(M, 'Writer') as writer:
            with self.assertRaises(M.EP.ProfileError):
                M.run(Config('/tmp/synthetic/data/db','/tmp/synthetic/socket/api',web_enabled=True),
                      {'NAVER_AUTO_TOKEN_SECRET':'local-test-token-signing-value-000000000000'}, stop=Event())
            writer.assert_not_called()

    def test_exact_health_and_web_dispatch(self):
        web_calls=[]
        def web(env,reply): web_calls.append(env['PATH_INFO']); reply('401 Unauthorized',[]); return [b'{}']
        app=M.combine_web(lambda:{'state':'running'},web)
        for path,wanted in (('/_engine/health',200),('/api/naver-auto/session',401),('/other',404)):
            status=[]
            app({'PATH_INFO':path,'REQUEST_METHOD':'GET','wsgi.input':io.BytesIO()},lambda s,h:status.append(int(s[:3])))
            self.assertEqual(status,[wanted])
        self.assertEqual(web_calls,['/api/naver-auto/session'])
