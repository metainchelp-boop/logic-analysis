"""Local-only schema 10→11 release gates; never opens operational data."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_naver_preview_code_upgrade import load, StoreScopeTest


class AdditiveContractTest(unittest.TestCase):
    def test_actual_schema10_sql_and_initializer_are_preserved_before_schema11_additions(self):
        fixture = json.loads((Path(__file__).with_name('fixtures')/'naver_schema10_11_contract.json').read_text())
        code = load('naver_preview_code_upgrade')
        code.TARGET_COMMIT = 'b'*40
        sources = {}
        for version, contract in ((10, fixture['old']), (11, fixture['new_observed_unsealed'])):
            old_sql = tuple(fixture['old']['sql'])
            sql = tuple(contract['sql'])
            sources[version] = ('SCHEMA_VERSION='+str(version)+'\n_SCHEMA='+repr(old_sql)+'\n'+
                ('_SCHEMA += '+repr(sql[len(old_sql):])+'\n_REVISION_COLUMNS='+repr(code.REVISION_COLUMNS)+'\n'
                 if version == 11 else '')+contract['migrate']+'\n').encode()
        with tempfile.TemporaryDirectory() as directory:
            old, new = (Path(directory).resolve()/part for part in ('old', 'new'))
            for path, version in ((old, 10), (new, 11)):
                for name in ('compose.naver-engine.yml', 'compose.naver-relay.yml',
                             'deploy/naver-engine-backup.override.yml', 'Dockerfile.naver-engine',
                             'Dockerfile.naver-relay', 'backend/requirements.txt', 'naver_runtime/bootstrap.py'):
                    file = path/name; file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(b'unchanged')
                file = path/'naver_engine/store.py'; file.parent.mkdir(parents=True); file.write_bytes(sources[version])
                for role in ('engine', 'relay'):
                    (path/('preview-'+role+'.override.yml')).write_bytes(
                        ('image: '+(code.OLD_COMMIT if version == 10 else code.TARGET_COMMIT)).encode())
            upgrade = Mock(read_file=lambda path, **kwargs: Path(path).read_bytes())
            hashes = {version: hashlib.sha256(body).hexdigest() for version, body in sources.items()}
            with patch.object(code, 'STORE_SHA256', hashes):
                code.compatible_source(old, new, upgrade)
                self.assertEqual(code.store_contract(sources[11], 11)[:len(old_sql)], tuple(fixture['old']['sql']))

    def test_pending_commit_archive_or_store_hash_cannot_prepare(self):
        code = load('naver_preview_code_upgrade')
        release = load('naver_preview_release')
        package = dict(baseline=code.EXPECTED_BASELINE, source_commit='b'*40,
                       ciphertext_sha256='c'*64, source_tar_gz_sha256='d'*64,
                       run_id='123456', operation='code-prepare')
        for target, archive, store in ((None, 'd'*64, 'e'*64), ('b'*40, None, 'e'*64),
                                       ('b'*40, 'd'*64, None)):
            with self.subTest(target=target, archive=archive, store=store), \
                    patch.object(code, 'TARGET_COMMIT', target), \
                    patch.object(code, 'TARGET_SOURCE_SHA256', archive), \
                    patch.object(code, 'STORE_SHA256', {11: store}):
                with self.assertRaisesRegex(ValueError, 'CODE_TARGET_NOT_PINNED'):
                    code.validate_package(package, release)

    def test_literal_schema_append_is_included_in_the_reviewed_contract(self):
        code = load('naver_preview_code_upgrade')
        source = b'SCHEMA_VERSION=11\n_SCHEMA=("old SQL",)\n_SCHEMA += ("new SQL",)\n'
        with patch.object(code, 'STORE_SHA256', {11: hashlib.sha256(source).hexdigest()}):
            self.assertEqual(code.store_contract(source, 11), ('old SQL', 'new SQL'))

    def test_prior_schema9_to10_fixture_remains_available_and_unchanged(self):
        fixture = json.loads((Path(__file__).with_name('fixtures')/'naver_schema9_10_contract.json').read_text())
        self.assertEqual(fixture['old_commit'], '73b9fe39c36284e266eea874902608a4127b00bf')
        self.assertEqual(fixture['old']['migrate'], fixture['new_observed_unsealed']['migrate'])
        self.assertEqual(fixture['new_observed_unsealed']['sha256'],
                         'aa411970fd7f4ff230ffcd5b62e4448d4aae77ff57757a2bb62a880044f54212')

    def test_exact_additive_columns_and_initializer_only_are_accepted(self):
        code = load('naver_preview_code_upgrade')
        source = StoreScopeTest.TARGET_SOURCE
        code.revision_migration_contract(StoreScopeTest.SOURCE, source)
        self.assertEqual(sum(len(items) for items in code.REVISION_COLUMNS.values()), 8)
        for changed in (
                source.replace(b"source_wait_attempts", b"unreviewed_attempts"),
                source.replace(b"INTEGER NOT NULL DEFAULT 1", b"INTEGER NOT NULL DEFAULT 2"),
                source.replace(b"if column not in columns:", b"if column in columns:"),
                source.replace(b" ADD COLUMN ", b" DROP COLUMN "),
                source.replace(b"self._set_meta", b"self._other_meta")):
            self.assertNotEqual(changed, source)
            with self.assertRaisesRegex(ValueError, 'CODE_SCHEMA_CHANGED'):
                code.revision_migration_contract(StoreScopeTest.SOURCE, changed)

    def test_only_target_management_posts_require_401_and_old_ad_writes_stay_403(self):
        code = load('naver_preview_code_upgrade')
        code.TARGET_COMMIT = 'b'*40
        new_posts = ('/management/update', '/management/collect', '/reports/review')
        for source in (code.OLD_COMMIT, code.TARGET_COMMIT):
            calls = []
            def request(socket, route, method='GET'):
                calls.append((route, method))
                if route == '/_engine/health':
                    return 200, {}, b'{}'
                if route in ('/naver/', '/naver/dashboard'):
                    return 200, {'referrer-policy':'no-referrer', 'cache-control':'no-store'}, b'verificationNotice id="s-dashboard"'
                approved = ('/links/confirm', '/collection/request') + (new_posts if source == code.TARGET_COMMIT else ())
                status = 401 if method == 'GET' or route.removeprefix('/api/naver-auto') in approved else 403
                return status, {}, b''
            code.probe(Mock(unix_request=request), source, load('naver_preview_upgrade'))
            for route in new_posts:
                self.assertEqual(('/api/naver-auto'+route, 'POST') in calls, source == code.TARGET_COMMIT)
            self.assertIn(('/api/naver-auto/settings/thresholds', 'POST'), calls)
            self.assertEqual(('/api/naver-auto/reports', 'GET') in calls, source == code.TARGET_COMMIT)
            self.assertEqual(
                ('/api/naver-auto/accounts/reasons?ad_account_no=1&page=0&selection=all', 'GET') in calls,
                source == code.TARGET_COMMIT)



if __name__ == '__main__':
    unittest.main()
