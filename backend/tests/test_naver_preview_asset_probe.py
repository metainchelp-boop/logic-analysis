"""Only the pinned report assets may use the larger local response bound."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('asset_release', Path(__file__).parents[1]/'tools/naver_preview_release.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class AssetProbeTest(unittest.TestCase):
    def request(self, route, size, method='GET', path='/run/metainc/naver-relay/relay.sock'):
        response = Mock(status=200)
        response.read.side_effect = lambda n: b'x'*min(n, size)
        response.getheaders.return_value = []
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(M.http.client, 'HTTPConnection', return_value=connection), patch.object(M.socket, 'socket'):
            result = M.unix_request(path, route, method)
        return result, response, connection

    def test_exact_report_asset_uses_existing_member_bound(self):
        body, response, connection = self.request('/naver/vendor/report-pdf/NanumGothic-Regular.ttf.gz', 697020)
        self.assertEqual(len(body[2]), 697020)
        response.read.assert_called_once_with(1024*1024+1)
        connection.close.assert_called_once_with()

    def test_other_routes_methods_paths_and_queries_retain_original_small_bound(self):
        for route, method, path in (
                ('/api/naver-auto/reports/detail?report_id=1', 'GET', '/run/metainc/naver-relay/relay.sock'),
                ('/naver/vendor/report-pdf/unknown.js', 'GET', '/run/metainc/naver-relay/relay.sock'),
                ('/naver/report-ui.js?x=1', 'GET', '/run/metainc/naver-relay/relay.sock'),
                ('/naver/report-ui.js', 'POST', '/run/metainc/naver-relay/relay.sock'),
                ('/naver/report-ui.js', 'GET', '/run/metainc/naver-engine/engine.sock')):
            with self.subTest(route=route, method=method, path=path), self.assertRaisesRegex(ValueError, '^PROBE_RESPONSE_SIZE$'):
                self.request(route, 65537, method, path)

    def test_report_asset_cannot_exceed_one_mib(self):
        with self.assertRaisesRegex(ValueError, '^PROBE_RESPONSE_SIZE$'):
            self.request('/naver/report-pdf.js', 1024*1024+1)


if __name__ == '__main__':
    unittest.main()
