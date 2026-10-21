"""Bounded local asset probes using the V14 sealed sizes and synthetic HTTP bodies."""
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared


RELAY = '/run/metainc/naver-relay/relay.sock'


class V14AssetProbeTest(unittest.TestCase):
    def setUp(self):
        self.release = shared.load('naver_preview_release')
        self.code = shared.load('naver_preview_code_upgrade_v14')

    def request(self, body, route='/naver/app.js', method='GET', path=RELAY):
        response = Mock(status=200)
        response.read.side_effect = lambda count: body[:count]
        response.getheaders.return_value = [('Content-Type', 'text/javascript; charset=utf-8')]
        connection = Mock()
        connection.getresponse.return_value = response
        self.addCleanup(lambda: connection.close.assert_called_once_with())
        with patch.object(self.release.http.client, 'HTTPConnection', return_value=connection), \
             patch.object(self.release.socket, 'socket'):
            result = self.release.unix_request(path, route, method)
        return result, response

    def test_sealed_app_js_and_css_probe_returns_every_byte(self):
        self.assertEqual(self.code.REPORT_ASSETS['/naver/app.js'][0], 218303)
        self.assertEqual(self.code.REPORT_ASSETS['/naver/app.css'][0], 44268)
        for route in ('/naver/app.js', '/naver/app.css'):
            body = b'x'*self.code.REPORT_ASSETS[route][0]
            with self.subTest(route=route):
                result, response = self.request(body, route)
                self.assertEqual(result[2], body)
                response.read.assert_called_once_with(1024*1024+1)

    def test_exact_new_assets_keep_the_existing_one_mib_upper_bound(self):
        for route in ('/naver/app.js', '/naver/app.css'):
            with self.subTest(route=route):
                result, _ = self.request(b'x'*(1024*1024), route)
                self.assertEqual(len(result[2]), 1024*1024)
                with self.assertRaisesRegex(ValueError, '^PROBE_RESPONSE_SIZE$'):
                    self.request(b'x'*(1024*1024+1), route)

    def test_api_unlisted_route_query_method_and_other_socket_keep_64_kib(self):
        for route, method, path in (
            ('/api/naver-auto/reports/detail?report_id=1', 'GET', RELAY),
            ('/api/naver-auto/reports/notes', 'POST', RELAY),
            ('/naver/other.js', 'GET', RELAY),
            ('/naver/app.js?cache=1', 'GET', RELAY),
            ('/naver/app.css', 'POST', RELAY),
            ('/naver/app.js', 'GET', '/run/metainc/naver-engine/engine.sock')):
            with self.subTest(route=route, method=method, path=path):
                result, response = self.request(b'x'*65536, route, method, path)
                self.assertEqual(len(result[2]), 65536)
                response.read.assert_called_once_with(65537)
                with self.assertRaisesRegex(ValueError, '^PROBE_RESPONSE_SIZE$'):
                    self.request(b'x'*65537, route, method, path)

    def test_response_size_failure_is_recognized_only_by_v14_without_freeform_output(self):
        self.code.STAGE, self.code.OPERATION = 'code_verify', 'verify_running'
        failure = self.code._capture_failure(ValueError('PROBE_RESPONSE_SIZE'))
        self.assertEqual(failure, dict(failed_stage='code_verify', failed_operation='verify_running',
                                      failed_error_kind='ValueError', failed_error_code='PROBE_RESPONSE_SIZE'))
        self.assertEqual(self.code._error_labels(ValueError('PROBE_RESPONSE_SIZE private payload')),
                         dict(error_kind='ValueError', error_code='UNRECOGNIZED'))
        self.assertEqual(shared.load('naver_preview_code_upgrade_v13')._error_labels(ValueError('PROBE_RESPONSE_SIZE')),
                         dict(error_kind='ValueError', error_code='UNRECOGNIZED'))


if __name__ == '__main__':
    unittest.main()
