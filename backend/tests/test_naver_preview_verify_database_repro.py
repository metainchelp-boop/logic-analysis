"""Offline deployment DB verification replay; fixed labels only, no operating DB."""
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import test_naver_preview_code_upgrade as shared


PRODUCT = Path(__file__).resolve().parents[3]/'naver-ad-account-matching-ad-20261001'


def actual_store(commit):
    # No checkout or file writes; only the pinned repository blob is executed.
    if not PRODUCT.is_dir() or not shutil.which('git'):
        raise unittest.SkipTest('local pinned Store replay requires the sibling product checkout and git')
    available = subprocess.run(['git','-C',str(PRODUCT),'cat-file','-e',commit+':naver_engine/store.py'],
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    if available.returncode:
        raise unittest.SkipTest('local pinned Store replay requires both approved git blobs')
    body = subprocess.check_output(['git','-C',str(PRODUCT),'show',commit+':naver_engine/store.py'],
                                   stderr=subprocess.DEVNULL)
    if str(PRODUCT) not in sys.path:
        sys.path.insert(0,str(PRODUCT))
    name = 'naver_engine._verify_repro_'+commit[:8]
    module = ModuleType(name)
    module.__package__ = 'naver_engine'
    module.__file__ = str(PRODUCT/'naver_engine/store.py')
    sys.modules[name] = module
    exec(compile(body,module.__file__,'exec'),module.__dict__)
    return module


class VerifyDatabaseReplay(unittest.TestCase):
    def setUp(self):
        self.code = shared.load('naver_preview_code_upgrade')
        self.temporary = tempfile.TemporaryDirectory(prefix='report-verify-offline-')
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name).resolve()
        self.db = self.data/'engine.db'
        self.release = SimpleNamespace(trusted_dir=lambda *_args,**_kwargs:None)
        self.upgrade = SimpleNamespace(read_file=lambda path,**_kwargs:Path(path).read_bytes())
        changed = patch.object(self.code,'DATA',self.data)
        changed.start(); self.addCleanup(changed.stop)

    def initialize(self, commit, journal='wal', *, actual=False):
        store = actual_store(commit) if actual else None
        connection = sqlite3.connect(self.db,isolation_level=None,timeout=0.05)
        connection.execute('PRAGMA journal_mode='+journal)
        connection.execute('PRAGMA trusted_schema=OFF')
        if store:
            owner = store.Store(connection,str(self.db),None,writer=True)
            owner._migrate()
            self.assertFalse(any('json_' in sql.lower() for sql in store._SCHEMA))
        else:
            shared.DatabaseRollbackTest().initialize_schema(connection,11,monitoring=True)
        connection.set_authorizer(None)
        connection.execute("""INSERT INTO naver_auto_report_snapshot
            (possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
            VALUES (11,'weekly:2026-09-21:2026-09-27','synthetic-fingerprint','synthetic-time',
                    'partial','not_required','{"format_version":2,"totals":{"spend":0}}')""")
        self.db.chmod(0o600)
        return connection

    def verify(self, commit):
        try:
            self.code.verify_database_schema(commit,self.release,self.upgrade)
        except sqlite3.Error as error:
            self.fail('VERIFY_SQLITE:'+str(error.sqlite_errorcode)+':'+error.sqlite_errorname)

    def test_actual_old_and_new_store_with_closed_report_fixture(self):
        for commit in (self.code.OLD_COMMIT,self.code.TARGET_COMMIT):
            with self.subTest(commit=commit):
                with closing(self.initialize(commit,actual=True)):
                    pass
                for _ in range(20):
                    self.verify(commit)
                self.db.unlink()  # Only the closed synthetic fixture.

    def test_actual_new_store_with_live_wal_writer_and_report_transaction(self):
        with closing(self.initialize(self.code.TARGET_COMMIT,actual=True)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            writer.execute("UPDATE naver_auto_report_snapshot SET generated_at='synthetic-new'")
            try:
                for _ in range(20):
                    self.verify(self.code.TARGET_COMMIT)
            finally:
                writer.rollback()

    def test_delete_journal_exclusive_writer_has_fixed_busy_code_then_recovers(self):
        with closing(self.initialize(self.code.TARGET_COMMIT,'delete')) as writer:
            writer.execute('BEGIN EXCLUSIVE')
            connect = sqlite3.connect
            def short_timeout(*args,**kwargs):
                return connect(*args,**dict(kwargs,timeout=0.02))
            try:
                with patch.object(sqlite3,'connect',side_effect=short_timeout):
                    with self.assertRaises(sqlite3.OperationalError) as failed:
                        self.code.verify_database_schema(self.code.TARGET_COMMIT,self.release,self.upgrade)
                self.assertEqual((failed.exception.sqlite_errorcode,failed.exception.sqlite_errorname),(5,'SQLITE_BUSY'))
            finally:
                writer.rollback()
            self.verify(self.code.TARGET_COMMIT)

    @unittest.skipUnless(os.name=='posix','POSIX permission fixture')
    def test_wal_reader_accepts_existing_readonly_sidecars_and_trusted_schema_off(self):
        with closing(self.initialize(self.code.TARGET_COMMIT)) as writer:
            sidecars = [Path(str(self.db)+suffix) for suffix in ('-wal','-shm')]
            self.assertTrue(all(path.exists() for path in sidecars))
            for path in [self.db,*sidecars]:
                path.chmod(0o400)
            self.data.chmod(0o500)
            try:
                self.verify(self.code.TARGET_COMMIT)
            finally:
                self.data.chmod(0o700)
                for path in [self.db,*sidecars]:
                    path.chmod(0o600)

    @unittest.skipUnless(os.name=='posix','POSIX permission fixture')
    def test_wal_without_shm_in_unwritable_copy_has_fixed_open_error_then_recovers(self):
        if os.geteuid()==0:
            self.skipTest('root bypasses this synthetic filesystem permission condition')
        with closing(self.initialize(self.code.TARGET_COMMIT)) as writer:
            writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            writer.execute("UPDATE naver_auto_report_snapshot SET generated_at='new-wal-value'")
            copy = self.data/'copy'; copy.mkdir()
            for suffix in ('','-wal'):
                shutil.copyfile(str(self.db)+suffix,copy/('engine.db'+suffix))
                (copy/('engine.db'+suffix)).chmod(0o400)
            self.assertFalse((copy/'engine.db-shm').exists())
            copy.chmod(0o500)
            try:
                with patch.object(self.code,'DATA',copy), self.assertRaises(sqlite3.OperationalError) as failed:
                    self.code.verify_database_schema(self.code.TARGET_COMMIT,self.release,self.upgrade)
                # SQLite versions differ: CANTOPEN or a READONLY extended result.
                self.assertIn(failed.exception.sqlite_errorcode & 255,(8,14))
                self.assertTrue(failed.exception.sqlite_errorname.startswith(('SQLITE_CANTOPEN','SQLITE_READONLY')))
            finally:
                copy.chmod(0o700)
            with patch.object(self.code,'DATA',copy):
                self.verify(self.code.TARGET_COMMIT)


if __name__ == '__main__':
    unittest.main()
