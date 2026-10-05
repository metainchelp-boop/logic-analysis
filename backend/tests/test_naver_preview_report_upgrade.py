"""Report release contracts use synthetic files/SQLite only; never operating services."""
import hashlib
from contextlib import closing
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_naver_preview_code_upgrade as legacy


class ReportUpgradeTest(unittest.TestCase):
    def probe_case(self, source, changed=None, replacement=None):
        code = legacy.sealed_code()
        calls = []
        assets = {'/naver/report-ui.js': b'synthetic-ui', '/naver/report-pdf.js': b'synthetic-pdf',
                  '/naver/vendor/report-pdf/NanumGothic-Regular.ttf.gz': b'fixed-gzip-font'}
        def response(path, route, method='GET'):
            calls.append((route, method))
            if route == changed:
                return replacement
            if route in assets:
                return 200, {'content-type':'application/gzip' if route.endswith('.gz') else 'text/javascript; charset=utf-8',
                             'cache-control':'no-store','x-content-type-options':'nosniff','referrer-policy':'no-referrer'}, assets[route]
            if route == '/_engine/health':
                return 200, {}, b'{}'
            if route in ('/naver/', '/naver/dashboard'):
                return 200, {'referrer-policy':'no-referrer','cache-control':'no-store'}, b'verificationNotice id="s-dashboard"'
            approved = ('/links/confirm','/collection/request','/management/update','/management/collect','/reports/review')
            return (401 if method == 'GET' or route.removeprefix('/api/naver-auto') in approved else 403), {}, b''
        with patch.object(code, 'REPORT_ASSETS', {route:(len(body),hashlib.sha256(body).hexdigest(),
                'application/gzip' if route.endswith('.gz') else 'text/javascript; charset=utf-8') for route,body in assets.items()}):
            code.probe(SimpleNamespace(unix_request=response), code.OLD_COMMIT if source == 'old' else code.TARGET_COMMIT,
                       legacy.load('naver_preview_upgrade'))
        return calls

    def test_new_report_auth_and_assets_are_required_only_for_target(self):
        target = self.probe_case('target')
        old = self.probe_case('old')
        additions = {('/api/naver-auto/reports/accounts?selection=all&kind=weekly&page=0','GET'),
                     ('/api/naver-auto/reports/detail?report_id=1&account_key=company','GET'),
                     ('/naver/report-ui.js','GET'), ('/naver/report-pdf.js','GET'),
                     ('/naver/vendor/report-pdf/NanumGothic-Regular.ttf.gz','GET')}
        self.assertTrue(additions <= set(target))
        self.assertFalse(additions & set(old))

    def test_report_probe_rejects_route_bypass_and_corrupt_or_cacheable_assets(self):
        routes = ('/api/naver-auto/reports/accounts?selection=all&kind=weekly&page=0',
                  '/api/naver-auto/reports/detail?report_id=1&account_key=company')
        for route in routes:
            for status in (200,403,404):
                with self.subTest(route=route,status=status), self.assertRaisesRegex(ValueError,'CODE_ROUTE_STATUS'):
                    self.probe_case('target',route,(status,{},b''))
        headers = {'content-type':'text/javascript; charset=utf-8','cache-control':'no-store',
                   'x-content-type-options':'nosniff','referrer-policy':'no-referrer'}
        cases = [(404,headers,b'synthetic-ui'), (200,headers,b'SYNTHETIC-UI'),
                 (200,headers,b'synthetic-ui-tail'), (200,headers,b'synthetic-u')]
        cases += [(200,{**headers,key:value},b'synthetic-ui') for key,value in
                  (('content-type','text/html'),('cache-control','public'),('x-content-type-options',''),
                   ('referrer-policy','unsafe-url'),('content-encoding','gzip'))]
        for response in cases:
            with self.subTest(response=response), self.assertRaisesRegex(ValueError,'REPORT_ASSET_NOT_READY'):
                self.probe_case('target','/naver/report-ui.js',response)

    def test_static_asset_allowlist_is_exact_and_contains_the_reviewed_bytes(self):
        code = legacy.load('naver_preview_code_upgrade')
        self.assertEqual(code.REPORT_ASSETS, {
            '/naver/report-ui.js':(30281,'c82ff66d8a5df8403c7717d3ef13df890fa29902622ae93cd94aa90876d69a60','text/javascript; charset=utf-8'),
            '/naver/report-pdf.js':(19961,'755972a68408b5424171f9160da172e783bb8189ca466d674663201c0bf6e9db','text/javascript; charset=utf-8'),
            '/naver/vendor/report-pdf/NanumGothic-Regular.ttf.gz':(697020,'72d1bf88a642ede8ff7da422031106fc697ea4c79b1cfd2994bffc57df4dab07','application/gzip'),
            '/naver/vendor/report-pdf/pdf-lib-1.17.1.min.js':(525099,'0f9a5cad07941f0826586c94e089d89b918c46e5c17cf2d5a3c6f666e3bc694f','text/javascript; charset=utf-8'),
            '/naver/vendor/report-pdf/fontkit-1.1.1.umd.min.js':(758440,'d8df561b9fba98e24f2e5130e40948809281bbbc55a20c412359f1a0a5eb35a6','text/javascript; charset=utf-8'),
            '/naver/vendor/report-pdf/sha256-1.0.0.min.js':(8156,'a050d794e170699bd1a69d33908d0942c68901cb88347016064b60b240f0067e','text/javascript; charset=utf-8')})

    def test_pending_linux_digest_refuses_before_prepare_actions(self):
        code = legacy.load('naver_preview_code_upgrade')
        # The report release (a38c537) is now the old side of the SHM-lock fix release.
        self.assertEqual(code.OLD_COMMIT, 'a38c53775c112cdf5db420f979093d6bee9e5376')
        self.assertEqual(code.TARGET_COMMIT, 'c21f5f05f610abf89df0c24e85c00b1bec23d01c')
        for pending in (None, 'PENDING_SEAL'):
            with self.subTest(pending=pending), patch.object(code, 'TARGET_SOURCE_SHA256', pending):
                with self.assertRaisesRegex(ValueError, 'CODE_TARGET_NOT_PINNED'):
                    code.prepare({}, None, None, None, None)

    def test_both_images_require_the_existing_monitoring_shape_and_keep_rows(self):
        code = legacy.load('naver_preview_code_upgrade')
        with closing(sqlite3.connect(':memory:')) as connection:
            legacy.DatabaseRollbackTest().initialize_schema(connection, 11, monitoring=True)
            connection.execute("INSERT INTO naver_auto_morning_progress VALUES (1,11,'day','binding','campaign',1,'reading','later',2)")
            before = connection.execute('SELECT * FROM naver_auto_morning_progress').fetchall()
            for source in (code.OLD_COMMIT, code.TARGET_COMMIT):
                code.database_contract(connection, source)
                self.assertEqual(connection.execute('SELECT * FROM naver_auto_morning_progress').fetchall(), before)
            connection.set_authorizer(None)  # Deliberately corrupt the isolated fixture, not the engine path.
            connection.execute('DROP TABLE naver_auto_morning_chunk')
            for source, error in ((code.OLD_COMMIT, 'DB_OLD_SCHEMA'), (code.TARGET_COMMIT, 'DB_TARGET_SCHEMA')):
                with self.subTest(source=source), self.assertRaisesRegex(ValueError, error):
                    code.database_contract(connection, source)

    def test_report_json_only_transition_requires_identical_full_schema_contract(self):
        code = legacy.load('naver_preview_code_upgrade')
        before = legacy.StoreScopeTest.TARGET_SOURCE
        after = before + b'\n# New report JSON aggregation, no schema change.\n'
        with patch.object(code, 'STORE_SHA256', {
                'old': hashlib.sha256(before).hexdigest(), 'target': hashlib.sha256(after).hexdigest()}):
            code.migration_contract(before, after)
        for changed in (after.replace(b'SCHEMA_VERSION=11', b'SCHEMA_VERSION=12'),
                        after.replace(b'checksum TEXT', b'checksum BLOB'),
                        after.replace(b'auto_identity_fingerprint', b'unreviewed_identity'),
                        after.replace(b'if column not in columns:', b'if column in columns:'),
                        after + b'\n_SCHEMA += ("CREATE TABLE unexpected(id INTEGER)",)\n'):
            with self.subTest(change=changed), patch.object(code, 'STORE_SHA256', {
                    'old': hashlib.sha256(before).hexdigest(), 'target': hashlib.sha256(changed).hexdigest()}):
                with self.assertRaisesRegex(ValueError, 'CODE_SCHEMA_CHANGED'):
                    code.migration_contract(before, changed)


if __name__ == '__main__':
    unittest.main()
