"""Pinned report failure diagnosis uses synthetic frozen SQLite files only."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as legacy


class ReportDiagnoseTest(unittest.TestCase):
    def setUp(self):
        self.diag = legacy.load('naver_preview_code_diagnose')
        self.code = legacy.load('naver_preview_code_upgrade')

    def reader(self, path, **policy):
        self.assertEqual(policy['maximum'], 1024**3)
        self.assertEqual((policy['uid'], policy['gid'], policy['mode']), (10001, 10001, 0o600))
        return Path(path).read_bytes()

    def test_frozen_wal_is_read_from_private_copy_without_changing_originals(self):
        with tempfile.TemporaryDirectory(prefix='report-diag-fixture-') as parent:
            folder = Path(parent).resolve()
            db = folder/'engine.db'
            with closing(sqlite3.connect(db)) as writer:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('PRAGMA wal_autocheckpoint=0')
                legacy.DatabaseRollbackTest().initialize_schema(writer, 11, monitoring=True)
                writer.commit()
                upgrade = SimpleNamespace(read_file=self.reader)
                before = self.diag.files_snapshot(folder, upgrade)
                self.assertEqual(len(before), 3)
                # This proves that ignoring WAL cannot pass this fixture.
                with closing(sqlite3.connect(db.as_uri()+'?immutable=1', uri=True)) as main_only:
                    self.assertEqual(main_only.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()[0], 0)
                opened = []
                connect = sqlite3.connect
                def observe(path, *args, **kwargs):
                    opened.append(str(path))
                    return connect(path, *args, **kwargs)
                with patch.object(self.diag.sqlite3, 'connect', side_effect=observe):
                    result = self.diag.report_schema_copy(folder, before, upgrade, self.code)
                self.assertEqual(result['schema_contract'], 'passed')
                self.assertEqual(self.diag.files_snapshot(folder, upgrade), before)
                self.assertFalse(any(str(db) in path for path in opened))
                copied = [path for path in opened if path.startswith('file:')]
                self.assertEqual(len(copied), 1)
                self.assertIn('?mode=ro', copied[0])
                self.assertNotIn('immutable', copied[0])
                self.assertFalse(Path(copied[0][5:].split('?')[0]).exists())
                self.assertNotIn(str(folder), json.dumps(result))

    def test_report_run_is_pinned_and_checks_only_frozen_copy_between_baselines(self):
        with tempfile.TemporaryDirectory(prefix='report-diag-run-') as parent:
            self.code.DATA = Path(parent).resolve()
            folder = self.code.DATA/('.account-failed-db-c33d41529d064cf68226e114707a3f8a')
            folder.mkdir(mode=0o700)
            with closing(sqlite3.connect(folder/'engine.db')) as writer:
                legacy.DatabaseRollbackTest().initialize_schema(writer, 11, monitoring=True)
            package = {'operation_id':'c33d41529d064cf68226e114707a3f8a','release':{'fixture':True}}
            # This diagnosis stays pinned to the failed report rollout (0a30285 -> a38c537).
            self.code.OLD_COMMIT = self.diag.REPORT_OLD
            self.code.TARGET_COMMIT = self.diag.REPORT_TARGET
            self.code.TARGET_SOURCE_SHA256 = self.diag.REPORT_SOURCE_SHA256
            self.code.validate_package = Mock(return_value=package['release'])
            self.code.current_state = Mock(return_value=('old-verified',))
            release = SimpleNamespace(trusted_dir=Mock(),command=Mock(side_effect=AssertionError('No command')))
            upgrade = SimpleNamespace(read_file=self.reader,manifest=Mock(return_value=('target',{'fixture':True})))
            before = self.diag.files_snapshot(folder, upgrade)
            result = self.diag.run(package, Mock(), release, Mock(), upgrade, self.code)
            self.assertEqual(result['mode'], 'report-failed-schema-copy')
            self.assertEqual(result['diagnosis']['schema_contract'], 'passed')
            self.assertEqual(result['database_mutations'], 0)
            self.assertFalse(result['live_database_opened'])
            self.assertFalse(result['services_changed'])
            self.assertEqual(self.diag.files_snapshot(folder, upgrade), before)
            self.assertEqual(self.code.current_state.call_count, 2)
            self.assertEqual(upgrade.manifest.call_count, 2)
            release.command.assert_not_called()
            self.assertNotIn(str(folder), json.dumps(result))
            self.assertRegex(result['host_sqlite_version'], r'^\d+\.\d+\.\d+$')
            self.assertRegex(result['host_python_version'], r'^\d+\.\d+\.\d+$')
            for changed in ('baseline','manifest','files'):
                self.code.current_state.side_effect = [('old-verified',), ('changed',) if changed=='baseline' else ('old-verified',)]
                upgrade.manifest.side_effect = [('target',{'fixture':True}), ('changed' if changed=='manifest' else 'target',{'fixture':True})]
                with self.subTest(changed=changed),patch.object(self.diag,'files_snapshot',side_effect=[before,{} if changed=='files' else before]):
                    with self.assertRaisesRegex(ValueError,'DIAG_POST_BASELINE'):
                        self.diag.run(package, Mock(), release, Mock(), upgrade, self.code)

    def test_sqlite_errors_are_fixed_labels_and_cleanup_never_leaks_private_text(self):
        for contents, expected in ((b'', (1,'SQLITE_ERROR')), (b'PRIVATE'*100, (26,'SQLITE_NOTADB'))):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory(prefix='report-diag-error-') as parent:
                folder = Path(parent).resolve()
                (folder/'engine.db').write_bytes(contents)
                upgrade = SimpleNamespace(read_file=self.reader)
                before = self.diag.files_snapshot(folder, upgrade)
                result = self.diag.report_schema_copy(folder, before, upgrade, self.code)
                self.assertEqual(result['schema_contract'], 'failed')
                self.assertEqual((result['sqlite_errorcode'],result['sqlite_errorname']), expected)
                self.assertEqual(self.diag.files_snapshot(folder, upgrade), before)
                self.assertNotIn('PRIVATE', json.dumps(result))
                self.assertNotIn(str(folder), json.dumps(result))

    def test_query_only_copy_denies_sql_writes_and_never_returns_private_error_message(self):
        with tempfile.TemporaryDirectory(prefix='report-diag-authorizer-') as parent:
            folder = Path(parent).resolve()
            with closing(sqlite3.connect(folder/'engine.db')) as writer:
                legacy.DatabaseRollbackTest().initialize_schema(writer, 11, monitoring=True)
            upgrade = SimpleNamespace(read_file=self.reader)
            before = self.diag.files_snapshot(folder, upgrade)
            for statement,expected in (("UPDATE naver_auto_meta SET value='PRIVATE'",(23,'SQLITE_AUTH')),
                                       ('SELECT * FROM PRIVATE_TABLE',(1,'SQLITE_ERROR'))):
                def contract(connection, source):
                    connection.execute(statement)
                with self.subTest(statement=statement),patch.object(self.code,'database_contract',side_effect=contract):
                    result = self.diag.report_schema_copy(folder, before, upgrade, self.code)
                    self.assertEqual((result['sqlite_errorcode'],result['sqlite_errorname']),expected)
                    self.assertEqual(self.diag.files_snapshot(folder, upgrade),before)
                    self.assertNotIn('PRIVATE', json.dumps(result))

    def test_report_pins_and_extra_fields_refuse_before_any_environment_access(self):
        good = {'operation_id':'c33d41529d064cf68226e114707a3f8a','release':{}}
        for change in ({'operation_id':'0'*32}, {'extra':'PRIVATE'}):
            release = Mock()
            with self.assertRaises(ValueError):
                self.diag.run(dict(good,**change),Mock(),release,Mock(),Mock(),self.code)
            release.assert_not_called()
            release.command.assert_not_called()
        report_pins = dict(TARGET_COMMIT=self.diag.REPORT_TARGET, OLD_COMMIT=self.diag.REPORT_OLD,
                           TARGET_SOURCE_SHA256=self.diag.REPORT_SOURCE_SHA256)
        for name in report_pins:
            with patch.multiple(self.code,**dict(report_pins,**{name:'0'*64})),\
                    patch.object(self.code,'current_state') as state:
                with self.assertRaisesRegex(ValueError,'DIAG_SOURCE'):
                    self.diag.run(good,Mock(),Mock(),Mock(),Mock(),self.code)
                state.assert_not_called()
        # The current SHM-lock release pins never reopen this historical report diagnosis.
        with patch.object(self.code,'current_state') as state:
            with self.assertRaisesRegex(ValueError,'DIAG_SOURCE'):
                self.diag.run(good,Mock(),Mock(),Mock(),Mock(),self.code)
            state.assert_not_called()


if __name__ == '__main__':
    unittest.main()
