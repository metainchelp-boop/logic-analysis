"""Offline failed-rollout diagnostic tests; no production SSH or Docker calls."""
import ast
import copy
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch


SPEC=importlib.util.spec_from_file_location('diagnose',Path(__file__).parents[1]/'tools/naver_preview_code_diagnose.py')
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def database(conn):
    conn.executescript('''
        CREATE TABLE naver_auto_meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE naver_auto_org(slot TEXT,body TEXT,generated_at TEXT,accepted_at TEXT);
        CREATE TABLE naver_auto_sync_log(sync_id INTEGER,kind TEXT,outcome TEXT,codes TEXT,row_count INTEGER);
        CREATE TABLE naver_auto_account(customer_id INTEGER,account_name TEXT,present INTEGER);
    ''')
    stamp='2026-10-02T15:00:00+09:00'
    conn.executemany('INSERT INTO naver_auto_meta VALUES(?,?)',[
        ('schema_version','8'),('accounts_read_at',stamp),
        ('account_catalog_status',json.dumps({'state':'failed','at':stamp,'code':'PRIVATE'})),
        ('account_catalog',json.dumps({'generated_at':stamp,'total':1798,'items':[{'company_name':'PRIVATE'}]}))])
    conn.execute('INSERT INTO naver_auto_org VALUES(?,?,?,?)',('current',json.dumps({'employees':[
        {'name':'PRIVATE','is_management':True},{'name':'PRIVATE','is_management':False},{'name':'PRIVATE'}]}),stamp,stamp))
    conn.executemany('INSERT INTO naver_auto_sync_log VALUES(?,?,?,?,?)',[
        (1,'org','accepted','[]',3),(2,'org','braked','["BRAKE","PRIVATE"]',3),
        (3,'accounts','accepted','[]',1798)])
    conn.executemany('INSERT INTO naver_auto_account VALUES(?,?,?)',[(1,'PRIVATE',1),(2,'PRIVATE',1),(3,'PRIVATE',0)])
    conn.commit()


def projected():
    with closing(sqlite3.connect(':memory:')) as conn:
        database(conn)
        return M.projection(conn)


class ProjectionTest(unittest.TestCase):
    def test_projection_returns_only_approved_counts_markers_and_states(self):
        value=M.validate_result(projected())
        self.assertEqual(value['org']['latest']['outcome'],'braked')
        self.assertEqual(value['org']['latest']['codes'],['BRAKE'])
        self.assertEqual(value['org']['latest']['unrecognized_code_count'],1)
        self.assertEqual(value['org']['management_marker_missing_count'],1)
        self.assertEqual(value['org']['management_count'],1)
        self.assertEqual(value['accounts']['present_count'],2)
        self.assertEqual(value['catalog']['total'],1798)
        self.assertNotIn('PRIVATE',json.dumps(value))

    def test_result_rejects_extra_fields_private_codes_bool_counts_and_raw_errors(self):
        for mutate in (lambda v:v.update(private='SECRET'),lambda v:v['org'].update(employee_count=True),
                       lambda v:v['org']['latest'].update(codes=['SECRET']),lambda v:v['catalog'].update(total=-1),
                       lambda v:v['catalog'].update(state='SECRET')):
            value=projected()
            mutate(value)
            with self.assertRaises(ValueError):
                M.validate_result(value)
        with self.assertRaisesRegex(ValueError,'DIAG_READ_FAILED'):
            M.validate_result({'diagnostic_error':'READ_FAILED'})

    def test_real_mode_ro_reads_wal_not_immutable_and_preserves_db_and_sidecars(self):
        with tempfile.TemporaryDirectory(prefix='failed-code-diagnostic-') as folder:
            db=Path(folder)/'engine.db'
            writer=sqlite3.connect(db)
            try:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('PRAGMA wal_autocheckpoint=0')
                database(writer)
                files=[Path(str(db)+suffix) for suffix in ('','-wal','-shm')]
                self.assertTrue(all(path.exists() for path in files))
                for path in files:
                    path.chmod(0o400)
                before={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
                # A fresh process avoids reusing the writer's writable SHM mapping.
                program='import importlib.util,json; s=importlib.util.spec_from_file_location("d",'+repr(SPEC.origin)+'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(json.dumps(m.read_projection('+repr(str(db))+')))'
                child=subprocess.run([sys.executable,'-B','-c',program],capture_output=True,text=True,check=True)
                result=json.loads(child.stdout)
                after={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
                self.assertEqual(before,after)
                self.assertEqual(result['catalog']['total'],1798)
                # Main DB alone has no tables yet: success above requires the retained WAL.
                with closing(sqlite3.connect(db.as_uri()+'?immutable=1',uri=True)) as without_wal:
                    self.assertEqual(without_wal.execute('SELECT COUNT(*) FROM sqlite_master WHERE type="table"').fetchone()[0],0)
            finally:
                writer.close()

    def test_script_uses_no_writer_or_network_and_clears_environment(self):
        source=M.script().decode()
        ast.parse(source)
        self.assertIn('?mode=ro',source)
        self.assertIn('PRAGMA query_only=ON',source)
        self.assertIn('set_authorizer',source)
        self.assertIn('os.environ.clear()',source)
        for forbidden in ('immutable=','open_writer','urllib','requests','load_erp_key','printenv','executescript'):
            self.assertNotIn(forbidden,source)

    def test_rollback_journal_presence_refuses_before_reading_database(self):
        upgrade=Mock()
        with patch.object(M.os.path,'lexists',return_value=True):
            with self.assertRaisesRegex(ValueError,'DIAG_JOURNAL_PRESENT'):
                M.files_snapshot(Path('/synthetic'),upgrade)
        upgrade.read_file.assert_not_called()

    def test_failure_report_is_strict_allowlist_never_regex_private_passthrough(self):
        M.STAGE='diagnose_readonly'
        for error in (ValueError('PRIVATE'),RuntimeError('ACCOUNT_PRIVATE'),ValueError('token=SECRET')):
            result=M.failure_report(error)
            self.assertEqual(result['error_code'],'UNRECOGNIZED')
            self.assertNotIn('PRIVATE',json.dumps(result))
            self.assertNotIn('SECRET',json.dumps(result))
        self.assertEqual(M.failure_report(ValueError('DIAG_SOURCE'))['error_code'],'DIAG_SOURCE')


class RunTest(unittest.TestCase):
    def scenario(self,failure=None,post_drift=False,absent_after_create=False):
        commands=[]
        cid='c'*64
        image='sha256:'+'d'*64
        package={'operation_id':M.OPERATION_ID,'release':{'fixture':True}}
        code=SimpleNamespace(TARGET_COMMIT=M.TARGET_COMMIT,DATA=Path('/synthetic/data'),
            validate_package=Mock(return_value=package['release']),
            current_state=Mock(side_effect=[('old',),('changed',) if post_drift else ('old',)]))
        release=SimpleNamespace(trusted_dir=Mock(),unique=lambda pairs:dict(pairs))
        upgrade=SimpleNamespace(manifest=Mock(return_value=(Path('/synthetic/release'),{'images':{'engine':image}})))
        checks=0
        def command(args,**kwargs):
            nonlocal checks
            commands.append((args,kwargs))
            if args[:3]==['docker','image','inspect']:
                return json.dumps({'id':image,'user':'10001:10001','source':M.TARGET_COMMIT}).encode()
            if args[:2]==['docker','run']:
                if failure=='create':
                    raise TimeoutError('SECRET')
                return cid.encode()
            if args[:2]==['docker','inspect']:
                return json.dumps({'id':cid,'image':image,'user':'10001:10001',
                    'source':'WRONG' if failure=='foreign' else M.TARGET_COMMIT,
                    'operation':M.OPERATION_ID,'network':'none','readonly':True}).encode()
            if args[:2]==['docker','exec']:
                if failure=='exec':
                    raise TimeoutError('SECRET')
                return json.dumps(projected()).encode()
            if args[:2]==['docker','ps']:
                checks+=1
                return (cid if checks==1 and not absent_after_create else '').encode()
            if args[:2]==['docker','rm']:
                return b''
            raise AssertionError(args)
        release.command=command
        files={'/synthetic/data/.account-failed-db-'+M.OPERATION_ID+'/engine.db':{'sha256':'e'*64},
               '/synthetic/data/.account-failed-db-'+M.OPERATION_ID+'/engine.db-wal':{'sha256':'f'*64}}
        with patch.object(M,'files_snapshot',return_value=files):
            try:
                result=M.run(package,Mock(),release,Mock(),upgrade,code)
            except Exception as error:
                result=error
        return result,commands,code,package

    def test_run_mounts_only_failed_files_without_keys_network_or_service_changes(self):
        result,commands,code,_=self.scenario()
        self.assertTrue(result['ok'])
        self.assertTrue(result['database_files_unchanged'])
        self.assertFalse(result['diagnostic_container_secrets_mounted'])
        run=next(args for args,_ in commands if args[:2]==['docker','run'])
        for flag in ('--read-only','--cap-drop','--security-opt','--network','--user','--log-driver'):
            self.assertIn(flag,run)
        self.assertEqual(run[run.index('--network')+1],'none')
        self.assertEqual(run[run.index('--log-driver')+1],'none')
        mounts=[run[index+1] for index,item in enumerate(run) if item=='--mount']
        self.assertEqual(len(mounts),2)
        self.assertTrue(all(item.endswith(',readonly') and 'dst=/diag/engine.db' in item for item in mounts))
        for args,_ in commands:
            self.assertNotIn('systemctl',args)
            self.assertNotIn('--env-file',args)
            self.assertNotIn('logs',args)
        self.assertEqual(code.current_state.call_count,2)

    def test_source_or_operation_mismatch_refuses_before_container_create(self):
        for operation,target in (('a'*32,M.TARGET_COMMIT),(M.OPERATION_ID,'b'*40)):
            release=Mock()
            code=SimpleNamespace(TARGET_COMMIT=target)
            with self.assertRaises(ValueError):
                M.run({'release':{},'operation_id':operation},Mock(),release,Mock(),Mock(),code)
            release.command.assert_not_called()

    def test_exec_timeout_removes_exact_diag_container_not_old_services(self):
        result,commands,_,_=self.scenario('exec')
        self.assertIsInstance(result,TimeoutError)
        self.assertIn(['docker','rm','--force','c'*64],[args for args,_ in commands])
        self.assertFalse(any('systemctl' in args for args,_ in commands))

    def test_foreign_labels_or_uncertain_create_keep_fixed_cleanup_error(self):
        for failure,absent in (('foreign',False),('create',True)):
            result,commands,_,_=self.scenario(failure,absent_after_create=absent)
            self.assertEqual(str(result),'DIAG_CLEANUP_FAILED')
            self.assertFalse(any(args[:2]==['docker','rm'] for args,_ in commands))

    def test_postflight_old_state_change_refuses_success(self):
        result,_,_,_=self.scenario(post_drift=True)
        self.assertEqual(str(result),'DIAG_POST_BASELINE')


if __name__=='__main__':
    unittest.main()
