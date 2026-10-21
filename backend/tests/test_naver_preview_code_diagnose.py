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
    # Exact queried table definitions from pinned e1c4b35 schema 8, including constraints.
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS naver_auto_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS naver_auto_org (
            slot TEXT PRIMARY KEY CHECK (slot = 'current'),
            generated_at TEXT NOT NULL,
            received_at TEXT NOT NULL,
            accepted_at TEXT NOT NULL,
            confirmed_by INTEGER CHECK (confirmed_by IS NULL OR confirmed_by >= 0),
            body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS naver_auto_sync_log (
            sync_id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK (kind IN ('org', 'stages', 'accounts')),
            at TEXT NOT NULL,
            outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'refused', 'braked', 'failed')),
            codes TEXT NOT NULL,
            row_count INTEGER CHECK (row_count IS NULL OR row_count >= 0),
            manager_count INTEGER CHECK (manager_count IS NULL OR manager_count >= 0),
            absent_count INTEGER CHECK (absent_count IS NULL OR absent_count >= 0),
            detail TEXT,
            confirmed_by INTEGER CHECK (confirmed_by IS NULL OR confirmed_by >= 0));
        CREATE TABLE IF NOT EXISTS naver_auto_account (
            customer_id INTEGER PRIMARY KEY CHECK (customer_id > 0),
            ad_account_no INTEGER,
            account_name TEXT,
            present INTEGER NOT NULL CHECK (present IN (0, 1)),
            first_seen_on TEXT NOT NULL,
            last_seen_on TEXT,
            absent_days INTEGER NOT NULL DEFAULT 0 CHECK (absent_days >= 0),
            last_absent_on TEXT);
        CREATE TABLE IF NOT EXISTS naver_auto_inventory_check (
            customer_id INTEGER NOT NULL CHECK (customer_id > 0),
            day TEXT NOT NULL,
            snapshot_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('reading', 'partial', 'ok', 'retry', 'reauth_required', 'limited')),
            checked_at TEXT NOT NULL,
            error_code TEXT,
            bizmoney REAL,
            yday_spend REAL,
            yday_imp REAL,
            yday_clk REAL,
            campaigns_json TEXT,
            progress_json TEXT,
            progress_hash TEXT,
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0 AND attempts <= 4),
            next_try_at TEXT NOT NULL,
            PRIMARY KEY (customer_id, day));
    ''')
    stamp='2026-10-02T15:00:00+09:00'
    conn.executemany('INSERT INTO naver_auto_meta VALUES(?,?)',[
        ('schema_version','8'),('accounts_read_at',stamp),
        ('account_catalog_status',json.dumps({'state':'failed','at':stamp,'code':'PRIVATE'})),
        ('account_catalog',json.dumps({'generated_at':stamp,'total':1798,'items':[{'company_name':'PRIVATE'}]}))])
    conn.execute('INSERT INTO naver_auto_org(slot,body,generated_at,accepted_at,received_at) VALUES(?,?,?,?,?)',('current',json.dumps({'employees':[
        {'name':'PRIVATE','is_management':True},{'name':'PRIVATE','is_management':False},{'name':'PRIVATE'}]}),stamp,stamp,stamp))
    conn.executemany('INSERT INTO naver_auto_sync_log(sync_id,kind,outcome,codes,row_count,at) VALUES(?,?,?,?,?,?)',[
        (1,'org','accepted','[]',3,stamp),(2,'org','braked','["BRAKE","PRIVATE"]',3,stamp),
        (3,'accounts','accepted','[]',1798,stamp)])
    conn.executemany('INSERT INTO naver_auto_account(customer_id,account_name,present,first_seen_on) VALUES(?,?,?,?)',
                     [(1,'PRIVATE',1,'2026-10-02'),(2,'PRIVATE',1,'2026-10-02'),(3,'PRIVATE',0,'2026-10-02')])
    rows=[('retry','NETWORK'),('retry','NETWORK'),('reauth_required','KEY_REJECTED'),
          ('limited','CHECKPOINT_INVALID'),('partial','CHECKPOINT_PENDING'),('ok',None),
          ('retry','PRIVATE_CREDENTIAL'),('reading',None)]
    conn.executemany('''INSERT INTO naver_auto_inventory_check
        (customer_id,day,snapshot_at,status,checked_at,error_code,bizmoney,yday_spend,campaigns_json,next_try_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)''',[(1000+i,'2026-10-02',stamp,status,stamp,code,123456.75,98765.5,
                                     '{"PRIVATE":"PRIVATE"}',stamp) for i,(status,code) in enumerate(rows,1)]+
                                    [(2001,'2026-10-01',stamp,'retry',stamp,'RATE',0,0,'[]',stamp)])
    conn.commit()


def projected():
    with closing(sqlite3.connect(':memory:')) as conn:
        database(conn)
        return M.projection(conn)


class ProjectionTest(unittest.TestCase):
    def test_schema9_preserves_existing_aggregate_contract_without_reading_monthly_rows(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            database(conn)
            previous=M.validate_result(M.projection(conn))
            conn.execute("UPDATE naver_auto_meta SET value='9' WHERE key='schema_version'")
            value=M.validate_result(M.projection(conn))
            self.assertEqual(value,dict(previous,schema_version=9))
            self.assertTrue(value['inventory_check']['available'])
            self.assertNotIn('PRIVATE',json.dumps(value))

    def test_schema9_real_readonly_database_stays_unchanged_without_sidecars(self):
        with tempfile.TemporaryDirectory(prefix='schema9-diagnostic-') as folder:
            db=Path(folder)/'engine.db'
            with closing(sqlite3.connect(db)) as conn:
                database(conn)
                conn.execute("UPDATE naver_auto_meta SET value='9' WHERE key='schema_version'")
                conn.commit()
            db.chmod(0o400)
            before=hashlib.sha256(db.read_bytes()).hexdigest()
            value=M.validate_result(M.read_projection(str(db)))
            self.assertEqual(value['schema_version'],9)
            self.assertEqual(value['inventory_check']['rows'],8)
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(),before)
            self.assertEqual({p.name for p in Path(folder).iterdir()},{'engine.db'})

    def test_only_exact_schema7_8_9_are_accepted(self):
        for schema in ('6','10','09','9.0','PRIVATE'):
            with self.subTest(schema=schema),closing(sqlite3.connect(':memory:')) as conn:
                database(conn)
                conn.execute("UPDATE naver_auto_meta SET value=? WHERE key='schema_version'",(schema,))
                with self.assertRaisesRegex(ValueError,'DIAG_SCHEMA'):
                    M.projection(conn)
        for schema in (6,10,'9',True):
            value=projected()
            value['schema_version']=schema
            with self.subTest(result_schema=schema),self.assertRaisesRegex(ValueError,'DIAG_SCHEMA'):
                M.validate_result(value)

    def test_inventory_counts_use_latest_pinned_operation_day_and_only_safe_codes(self):
        self.assertEqual(M.OPERATION_ID,'a49a7ccfe32840298914f121883caee5')
        value=M.validate_result(projected())
        inventory=value['inventory_check']
        self.assertEqual(inventory['available'],True)
        self.assertEqual(inventory['day'],'2026-10-02')
        self.assertEqual(inventory['rows'],8)
        self.assertEqual(inventory['groups'],[
            {'status':'limited','error_code':'CHECKPOINT_INVALID','count':1},
            {'status':'ok','error_code':'NONE','count':1},
            {'status':'partial','error_code':'CHECKPOINT_PENDING','count':1},
            {'status':'reading','error_code':'NONE','count':1},
            {'status':'reauth_required','error_code':'KEY_REJECTED','count':1},
            {'status':'retry','error_code':'NETWORK','count':2},
            {'status':'retry','error_code':'UNRECOGNIZED','count':1}])
        for forbidden in ('PRIVATE','1001','123456.75','98765.5','customer_id','bizmoney','yday_spend','campaigns_json'):
            self.assertNotIn(forbidden,json.dumps(value))

    def test_schema7_inventory_is_unavailable_but_missing_schema8_table_is_not_empty_success(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            database(conn)
            conn.execute('DROP TABLE naver_auto_inventory_check')
            conn.execute("UPDATE naver_auto_meta SET value='7' WHERE key='schema_version'")
            value=M.validate_result(M.projection(conn))
            self.assertEqual(value['inventory_check'],{'available':False,'day':'2026-10-02','rows':0,'groups':[]})
            for schema in ('8','9'):
                conn.execute("UPDATE naver_auto_meta SET value=? WHERE key='schema_version'",(schema,))
                with self.subTest(schema=schema),self.assertRaises(sqlite3.OperationalError):
                    M.projection(conn)

    def test_unknown_inventory_values_are_collapsed_before_leaving_sql(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            database(conn)
            conn.execute('PRAGMA ignore_check_constraints=ON')
            conn.execute("UPDATE naver_auto_inventory_check SET status='PRIVATE_STATUS',error_code='PRIVATE_CODE' WHERE day='2026-10-02'")
            value=M.validate_result(M.projection(conn))
            self.assertEqual(value['inventory_check']['groups'],
                             [{'status':'UNRECOGNIZED','error_code':'UNRECOGNIZED','count':8}])
            self.assertNotIn('PRIVATE',json.dumps(value))

    def test_inventory_output_rejects_raw_values_duplicates_false_counts_and_wrong_day(self):
        for mutate in (
                lambda i:i.update(day='PRIVATE'),lambda i:i.update(available=1),lambda i:i.update(rows=99),
                lambda i:i['groups'][0].update(error_code='PRIVATE'),lambda i:i['groups'][0].update(status='PRIVATE'),
                lambda i:i['groups'][0].update(customer_id=1001),lambda i:i['groups'][0].update(count=True),
                lambda i:i['groups'].append(dict(i['groups'][0]))):
            value=projected()
            mutate(value['inventory_check'])
            with self.assertRaises(ValueError):
                M.validate_result(value)

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

    def test_real_schema8_db_only_after_wal_writer_close_never_creates_sidecars(self):
        with tempfile.TemporaryDirectory(prefix='failed-code-db-only-') as folder:
            db=Path(folder)/'engine.db'
            with closing(sqlite3.connect(db)) as writer:
                self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0],'wal')
                database(writer)
            self.assertEqual({p.name for p in Path(folder).iterdir()},{'engine.db'})
            db.chmod(0o400)
            Path(folder).chmod(0o500)
            try:
                before=hashlib.sha256(db.read_bytes()).hexdigest()
                program='import importlib.util,json; s=importlib.util.spec_from_file_location("d",'+repr(SPEC.origin)+'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(json.dumps(m.read_projection('+repr(str(db))+')))'
                child=subprocess.run([sys.executable,'-B','-c',program],capture_output=True,text=True)
                self.assertEqual(child.returncode,0,child.stderr)
                result=M.validate_result(json.loads(child.stdout))
                self.assertEqual(result['schema_version'],8)
                self.assertEqual(result['catalog']['total'],1798)
                self.assertEqual(result['accounts']['present_count'],2)
                self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(),before)
                self.assertEqual({p.name for p in Path(folder).iterdir()},{'engine.db'})
            finally:
                Path(folder).chmod(0o700)
                db.chmod(0o600)

    def test_script_uses_no_writer_or_network_and_clears_environment(self):
        source=M.script().decode()
        ast.parse(source)
        self.assertIn('?mode=ro',source)
        self.assertIn('PRAGMA query_only=ON',source)
        self.assertIn('set_authorizer',source)
        self.assertIn('os.environ.clear()',source)
        for forbidden in ('open_writer','urllib','requests','load_erp_key','printenv','executescript'):
            self.assertNotIn(forbidden,source)

    def test_immutable_is_used_only_when_both_sidecars_are_absent(self):
        for present in (set(),{'-wal'},{'-shm'},{'-wal','-shm'}):
            with self.subTest(present=present),patch.object(M.os.path,'lexists',side_effect=lambda p:p.removeprefix('/db') in present),\
                    patch.object(M.sqlite3,'connect') as connect,patch.object(M,'projection',return_value={}):
                M.read_projection('/db')
                self.assertEqual(connect.call_args.args[0],
                                 'file:/db?mode=ro'+('' if present else '&immutable=1'))
                self.assertTrue(connect.call_args.kwargs['uri'])
                connect.return_value.close.assert_called_once()

    def test_reader_rejects_even_dangling_journal_before_opening_database(self):
        with tempfile.TemporaryDirectory(prefix='failed-code-journal-') as folder:
            db=Path(folder)/'engine.db'
            Path(str(db)+'-journal').symlink_to(Path(folder)/'missing')
            with patch.object(M.sqlite3,'connect') as connect:
                with self.assertRaisesRegex(ValueError,'DIAG_JOURNAL_PRESENT'):
                    M.read_projection(str(db))
                connect.assert_not_called()

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


class JournalTest(unittest.TestCase):
    def release(self,messages):
        rows=[dict(UNIT='metainc-naver-relay.service',_PID='1',MESSAGE=message) for message in messages]
        raw=b'\n'.join(json.dumps(row).encode() for row in rows)
        return SimpleNamespace(command=Mock(side_effect=lambda args,**kwargs:raw if 'UNIT=metainc-naver-relay.service' in args else b''),
                               unique=lambda pairs:dict(pairs))

    def test_latest_runtime_window_outputs_only_fixed_exception_kinds_and_sources(self):
        messages={('engine','app'):[
            'ERROR naver_runtime 예약 회차 실패: AttributeError',
            'ERROR naver_runtime 예약 회차 실패: AttributeError',
            'ERROR naver_runtime.scheduler 예약 작업 실패: inventory KeyError',
            '{"error":"startup-refused","kind":"ValueError"}',
            '{"error":"startup-refused","kind":"PRIVATE_SECRET"}',
            'ERROR naver_runtime 예약 회차 실패: PRIVATE_SECRET',
            'PRIVATE customer=123 path=/secret token=SECRET'],
            ('relay','systemd'):['metainc-naver-relay.service: Main process exited, code=exited, status=130/n/a']}
        def command(args,**kwargs):
            source='app' if any(x.startswith('_SYSTEMD_UNIT=') for x in args) else 'systemd'
            field='_SYSTEMD_UNIT' if source=='app' else 'UNIT'
            unit=next(x.split('=',1)[1] for x in args if x.startswith(field+'='))
            name='engine' if unit=='metainc-naver-engine.service' else 'relay'
            self.assertIn('2026-10-02 04:25:00 UTC',args)
            self.assertIn('2026-10-02 04:26:35 UTC',args)
            self.assertIn('--lines=513',args)
            return b'\n'.join(json.dumps({field:unit,'_PID':'22' if source=='app' else '1','MESSAGE':m}).encode()
                              for m in messages.get((name,source),[]))
        release=SimpleNamespace(command=Mock(side_effect=command),unique=lambda pairs:dict(pairs))
        value=M.runtime_journal(release)
        self.assertEqual(release.command.call_count,4)
        self.assertEqual(value['scope'],'journal_only')
        self.assertEqual(value['entries_inspected'],8)
        self.assertEqual(value['unrecognized_event_count'],1)
        self.assertIn({'unit':'engine','source':'app','event':'scheduler_tick','kind':'AttributeError','count':2},value['exceptions'])
        self.assertIn({'unit':'engine','source':'app','event':'startup_refused','kind':'UNRECOGNIZED','count':1},value['exceptions'])
        self.assertEqual(value['exits'],[{'unit':'relay','source':'systemd','exit_type':'exited','exit_status':130,'status_label':'n/a','count':1}])
        for forbidden in ('PRIVATE','SECRET','/secret','customer'):
            self.assertNotIn(forbidden,json.dumps(value))

    def test_fixed_host_window_outputs_only_allowlisted_aggregates(self):
        release=self.release([
            'metainc-naver-relay.service: Main process exited, code=exited, status=143/n/a',
            'metainc-naver-relay.service: Main process exited, code=exited, status=143/n/a',
            'metainc-naver-relay.service: Main process exited, code=killed, status=15/TERM',
            "metainc-naver-relay.service: Failed with result 'exit-code'.",
            'metainc-naver-relay.service: Deactivated successfully.',
            'PRIVATE argv=/secret token=SECRET'])
        result=M.runtime_journal(release)
        self.assertEqual(result['entries_inspected'],6)
        self.assertEqual(result['main_process_exit_count'],3)
        self.assertEqual(result['unrecognized_event_count'],1)
        self.assertEqual(result['exits'],[
            {'unit':'relay','source':'systemd','exit_type':'exited','exit_status':143,'status_label':'n/a','count':2},
            {'unit':'relay','source':'systemd','exit_type':'killed','exit_status':15,'status_label':'TERM','count':1}])
        self.assertEqual(result['results'],[{'unit':'relay','source':'systemd','result':'exit-code','count':1},
                                          {'unit':'relay','source':'systemd','result':'success','count':1}])
        self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertNotIn('SECRET',json.dumps(result))
        args=release.command.call_args_list[2].args[0]
        self.assertEqual(args[0],'/usr/bin/journalctl')
        self.assertIn('UNIT=metainc-naver-relay.service',args)
        self.assertIn('_PID=1',args)
        self.assertEqual(args[args.index('--since')+1],'2026-10-02 04:25:00 UTC')
        self.assertEqual(args[args.index('--until')+1],'2026-10-02 04:26:35 UTC')
        self.assertIn('--output-fields=UNIT,_SYSTEMD_UNIT,_PID,MESSAGE',args)

    def test_unknown_exit_labels_and_results_never_pass_through(self):
        release=self.release([
            'metainc-naver-relay.service: Main process exited, code=private, status=1/SECRET',
            "metainc-naver-relay.service: Failed with result 'SECRET'."])
        result=M.runtime_journal(release)
        self.assertEqual(result['exits'][0]['exit_type'],'UNRECOGNIZED')
        self.assertEqual(result['exits'][0]['status_label'],'UNRECOGNIZED')
        self.assertEqual(result['results'][0]['result'],'UNRECOGNIZED')
        self.assertNotIn('SECRET',json.dumps(result))

    def test_foreign_identity_shape_size_and_truncation_fail_closed(self):
        row=dict(UNIT='metainc-naver-relay.service',_PID='1',MESSAGE='unrecognized')
        for raw in (json.dumps(dict(row,UNIT='PRIVATE')).encode(),json.dumps(dict(row,_PID='99')).encode(),
                    b'[]',b'x'*1048577,b'\n'.join([json.dumps(row).encode()]*513)):
            with self.subTest(length=len(raw)),self.assertRaises(ValueError):
                M.runtime_journal(SimpleNamespace(command=Mock(return_value=raw),unique=lambda pairs:dict(pairs)))

    def test_app_source_requires_exact_service_and_non_manager_pid(self):
        valid={'_SYSTEMD_UNIT':'metainc-naver-engine.service','_PID':'22','MESSAGE':'예약 회차 실패: AttributeError'}
        for change in ({'_SYSTEMD_UNIT':'PRIVATE'},{'_PID':'1'},{'_PID':22},{'MESSAGE':['PRIVATE']}):
            raw=json.dumps(dict(valid,**change)).encode()
            def command(args,**kwargs):
                return raw if '_SYSTEMD_UNIT=metainc-naver-engine.service' in args else b''
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'DIAG_JOURNAL_FIELDS'):
                M.runtime_journal(SimpleNamespace(command=command,unique=lambda pairs:dict(pairs)))

    def test_four_exact_sources_are_bounded_to_2048_records_total(self):
        def command(args,**kwargs):
            app=any(a.startswith('_SYSTEMD_UNIT=') for a in args)
            field='_SYSTEMD_UNIT' if app else 'UNIT'
            unit=next(a.split('=',1)[1] for a in args if a.startswith(field+'='))
            row=json.dumps({field:unit,'_PID':'22' if app else '1','MESSAGE':'PRIVATE'}).encode()
            return b'\n'.join([row]*512)
        value=M.runtime_journal(SimpleNamespace(command=command,unique=lambda pairs:dict(pairs)))
        self.assertEqual(value['entries_inspected'],2048)
        self.assertEqual(value['unrecognized_event_count'],2048)
        self.assertEqual([row['count'] for row in value['sources']],[512]*4)
        self.assertNotIn('PRIVATE',json.dumps(value))


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
            if args[0]=='/usr/bin/journalctl':
                return b''
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
        with patch.object(M,'files_snapshot',return_value=files),patch.object(M.os.path,'lexists',return_value=True):
            try:
                result=M.run(package,Mock(),release,Mock(),upgrade,code)
            except Exception as error:
                result=error
        return result,commands,code,package

    def test_absent_quarantine_reads_fixed_journal_only_and_rechecks_pins(self):
        package={'operation_id':M.OPERATION_ID,'release':{'fixture':True}}
        code=SimpleNamespace(TARGET_COMMIT=M.TARGET_COMMIT,DATA=Path('/synthetic/data'),
            validate_package=Mock(return_value=package['release']),current_state=Mock(return_value=('old',)))
        release=JournalTest().release([])
        release.trusted_dir=Mock()
        upgrade=SimpleNamespace(manifest=Mock(return_value=(Path('/synthetic/release'),{'fixture':True})),read_file=Mock())
        with patch.object(M.os.path,'lexists',return_value=False),patch.object(M,'files_snapshot') as snapshot:
            result=M.run(package,Mock(),release,Mock(),upgrade,code)
        self.assertEqual(result['mode'],'failed-code-runtime-journal')
        self.assertFalse(result['database_read'])
        self.assertEqual(result['runtime_journal']['entries_inspected'],0)
        self.assertEqual(code.current_state.call_count,2)
        self.assertEqual(upgrade.manifest.call_count,2)
        self.assertEqual(release.command.call_count,4)
        snapshot.assert_not_called()
        upgrade.read_file.assert_not_called()
        release.trusted_dir.assert_called_once_with(code.DATA,uid=10001,gid=10001,mode=0o750)
        for changed in ('quarantine','manifest','baseline'):
            code.current_state.reset_mock(side_effect=True)
            code.current_state.side_effect=[('old',),('changed',) if changed=='baseline' else ('old',)]
            upgrade.manifest.reset_mock(side_effect=True)
            upgrade.manifest.side_effect=[(Path('/synthetic/release'),{'fixture':True}),
                (Path('/synthetic/release'),{'fixture':changed!='manifest'})]
            with self.subTest(changed=changed),patch.object(M.os.path,'lexists',side_effect=[False,changed=='quarantine']):
                with self.assertRaisesRegex(ValueError,'DIAG_POST_BASELINE'):
                    M.run(package,Mock(),release,Mock(),upgrade,code)

    def test_run_mounts_only_failed_files_without_keys_network_or_service_changes(self):
        result,commands,code,_=self.scenario()
        self.assertTrue(result['ok'])
        self.assertTrue(result['database_files_unchanged'])
        self.assertFalse(result['diagnostic_container_secrets_mounted'])
        self.assertEqual(result['runtime_journal']['scope'],'journal_only')
        self.assertEqual(len([args for args,_ in commands if args[0]=='/usr/bin/journalctl']),4)
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
