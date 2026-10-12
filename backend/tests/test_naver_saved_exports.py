"""Synthetic filesystem/SQLite CLI only; no system units, remote host or APIs."""
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import os
from contextlib import redirect_stdout
import io
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'tools' / 'naver_saved_exports.py'
SPEC = importlib.util.spec_from_file_location('saved_exports_under_test', SOURCE)
M = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)


class SavedExportInstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source = self.root / 'saved-source'; self.source.mkdir()
        self.database = self.source / 'logic_data.db'
        conn = sqlite3.connect(self.database)
        conn.executescript('''
            CREATE TABLE clients(id INTEGER PRIMARY KEY,naver_store_url TEXT,main_keywords TEXT,role TEXT,vertical TEXT);
            CREATE TABLE client_analyses(id INTEGER PRIMARY KEY,client_id INTEGER,product_url TEXT,updated_at TEXT,analysis_json TEXT,advertiser_json TEXT);
            CREATE TABLE client_keyword_product(client_id INTEGER,keyword TEXT,product_url TEXT);
            CREATE TABLE client_keyword_mute(client_id INTEGER,keyword TEXT);
            CREATE TABLE collector_observations(observation_id TEXT,keyword TEXT,collected_date TEXT,status TEXT,kind TEXT,reason TEXT,payload_hash TEXT,products_json TEXT,meta_json TEXT,received_at TEXT);
            CREATE TABLE collected_serp(keyword TEXT,collected_date TEXT,total INTEGER,products_json TEXT,meta_json TEXT);
        '''); conn.commit(); conn.close()
        self.uid = os.getuid() or 10001; self.gid = os.getgid()
        self.staging = self.root / 'staging'; self.staging.mkdir(mode=0o700)
        self.install = self.root / 'installed-code'; self.install.mkdir(mode=0o755)
        self.units = self.root / 'units'; self.units.mkdir(mode=0o755)
        self.outputs = {kind: self.root / ('export-' + kind) for kind in M.KINDS}
        for name, value in {'STAGING':self.staging,'INSTALL':self.install,'UNITS':self.units,
                            'OUTPUTS':self.outputs,'ROOT_UID':os.getuid(),'READER_GID':self.gid}.items():
            item=patch.object(M,name,value);item.start();self.addCleanup(item.stop)
        item=patch.object(M.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=self.uid));item.start();self.addCleanup(item.stop)
        item=patch.object(M.grp,'getgrgid',return_value=SimpleNamespace(gr_gid=self.gid));item.start();self.addCleanup(item.stop)
        self.plan = M.build_plan(ops_commit='a'*40,source_directory=str(self.source),database_name='logic_data.db',
            exporter_user='synthetic-exporter',source_group=None,python_executable='/usr/bin/python3')
        # The fixture copies a fake ELF, never reads the host interpreter. The
        # systemctl stub below deliberately runs synthetic CLI tests using this
        # process's Python, so it is not target-namespace/stdlib execution proof.
        self.python = self.root / 'python3.10'
        self.python.write_bytes(b'\x7fELF' + b'synthetic-interpreter\0' * 20)
        self.python.chmod(0o700)
        item=patch.object(M,'_python_target',return_value=self.python);item.start();self.addCleanup(item.stop)
        self.python_target_patch=item
        self.scripts = {name:(SOURCE.parents[1]/name).read_bytes() for name in M.SCRIPTS}
        self.pins = {name:hashlib.sha256(body).hexdigest() for name,body in self.scripts.items()}
        self.calls = []

    def prepare(self):
        return M.prepare(self.plan,scripts=self.scripts,pins=self.pins,operation_id='b'*32)

    def coordinator(self):
        namespace={'__name__':'coordinator_synthetic_test'}
        exec(M._coordinator_source(self.plan,'product'),namespace)
        return namespace

    def test_coordinator_pins_wal_read_transaction_without_database_writes(self):
        writer=sqlite3.connect(self.database)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("INSERT INTO clients VALUES(1,NULL,NULL,NULL,NULL)")
        writer.commit();writer.close()
        self.assertFalse(Path(str(self.database)+'-wal').exists())
        before=(self.database.read_bytes(),self.database.stat().st_mode)
        namespace=self.coordinator();connections=[];calls=[]
        def connect(*args,**kwargs):
            connection=sqlite3.connect(*args,**kwargs);connections.append(connection)
            return connection
        def run(args,**kwargs):
            calls.append((args,kwargs))
            self.assertTrue(Path(str(self.database)+'-wal').exists())
            self.assertTrue(Path(str(self.database)+'-shm').exists())
            with self.assertRaises(sqlite3.DatabaseError):
                connections[0].execute('INSERT INTO clients VALUES(2,NULL,NULL,NULL,NULL)')
            reader=sqlite3.connect(self.database.as_uri()+'?mode=ro',uri=True)
            try:
                self.assertEqual(reader.execute('SELECT COUNT(*) FROM clients').fetchone()[0],1)
            finally:reader.close()
            return SimpleNamespace(returncode=0)
        # This synthetic test proves the SQLite transaction behavior; the kernel
        # nested mount is separately checked by the coordinator and host one-shot.
        with patch.object(namespace['os'],'statvfs',side_effect=lambda path:SimpleNamespace(
                f_flag=os.ST_RDONLY if path==str(self.database) else 0)):
            self.assertEqual(namespace['coordinate'](str(self.database),'naver-product-export-reader.service',
                                                    connect=connect,run=run),0)
        self.assertEqual(before,(self.database.read_bytes(),self.database.stat().st_mode))
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0],['/usr/bin/systemctl','start','naver-product-export-reader.service'])
        self.assertEqual(calls[0][1]['timeout'],50)
        self.assertIs(calls[0][1]['stdout'],subprocess.DEVNULL)
        self.assertIs(calls[0][1]['stderr'],subprocess.DEVNULL)
        with self.assertRaises(sqlite3.ProgrammingError):connections[0].execute('SELECT 1')

    def test_coordinator_timeout_stops_reader_before_releasing_source_transaction(self):
        namespace=self.coordinator();calls=[];closed=[]
        class Connection:
            def execute(self,sql):
                calls.append(('sql',sql));return self
            def fetchone(self):return (1,)
            def set_authorizer(self,callback):self.authorize=callback
            def close(self):closed.append(True)
        connection=Connection()
        def run(args,**kwargs):
            self.assertEqual(closed,[])
            calls.append((args,kwargs))
            if args[1]=='start':raise subprocess.TimeoutExpired(args,50,output=b'private source detail')
            self.assertEqual(kwargs['timeout'],8)
            return SimpleNamespace(returncode=0)
        output=io.StringIO()
        with patch.object(namespace['os'],'statvfs',side_effect=lambda path:SimpleNamespace(
                f_flag=os.ST_RDONLY if path==str(self.database) else 0)),redirect_stdout(output):
            result=namespace['coordinate'](str(self.database),'naver-product-export-reader.service',
                connect=lambda *args,**kwargs:connection,run=run)
        self.assertEqual(result,1);self.assertEqual(closed,[True])
        self.assertEqual(json.loads(output.getvalue()),{'status':'failed','code':'COORDINATION_TIMEOUT'})
        self.assertEqual([entry[0] for entry in calls if isinstance(entry[0],list)],
                         [['/usr/bin/systemctl','start','naver-product-export-reader.service'],
                          ['/usr/bin/systemctl','stop','naver-product-export-reader.service']])
        self.assertEqual(connection.authorize(sqlite3.SQLITE_PRAGMA,'schema_version',None,None,None),sqlite3.SQLITE_OK)
        for action,a,b in [(sqlite3.SQLITE_INSERT,'clients',None),(sqlite3.SQLITE_READ,'clients','id'),
                            (sqlite3.SQLITE_PRAGMA,'schema_version','1'),(sqlite3.SQLITE_PRAGMA,'journal_mode',None),
                            (sqlite3.SQLITE_TRANSACTION,'COMMIT',None)]:
            self.assertEqual(connection.authorize(action,a,b,None,None),sqlite3.SQLITE_DENY)
        self.assertNotIn('private',output.getvalue());self.assertNotIn(str(self.database),output.getvalue())

    def test_coordinator_rejects_missing_kernel_readonly_or_unreadable_sidecars_before_open(self):
        namespace=self.coordinator()
        for main_readonly,directory_readonly in ((False,False),(True,True)):
            opened=[];output=io.StringIO()
            with patch.object(namespace['os'],'statvfs',side_effect=lambda path:SimpleNamespace(
                    f_flag=os.ST_RDONLY if (main_readonly if path==str(self.database) else directory_readonly) else 0)),redirect_stdout(output):
                result=namespace['coordinate'](str(self.database),'naver-product-export-reader.service',
                    connect=lambda *a,**k:opened.append(True),run=lambda *a,**k:self.fail('must not start child'))
            self.assertEqual(result,1);self.assertEqual(opened,[])
            self.assertEqual(json.loads(output.getvalue())['code'],'COORDINATION_INVALID')
        wal=Path(str(self.database)+'-wal');wal.write_bytes(b'private sidecar');wal.chmod(0o600)
        opened=[];output=io.StringIO()
        with patch.object(namespace['os'],'statvfs',side_effect=lambda path:SimpleNamespace(
                f_flag=os.ST_RDONLY if path==str(self.database) else 0)),\
                patch.object(namespace['pwd'],'getpwnam',return_value=SimpleNamespace(pw_uid=self.uid+1)),redirect_stdout(output):
            result=namespace['coordinate'](str(self.database),'naver-product-export-reader.service',
                connect=lambda *a,**k:opened.append(True),run=lambda *a,**k:self.fail('must not start child'))
        self.assertEqual(result,1);self.assertEqual(opened,[])
        self.assertEqual(json.loads(output.getvalue())['code'],'COORDINATION_INVALID')
        self.assertEqual(wal.read_bytes(),b'private sidecar');self.assertEqual(wal.stat().st_mode&0o777,0o600)

    def test_coordinator_reader_failure_and_stop_failure_keep_closed_first_cause(self):
        namespace=self.coordinator();closed=[]
        connection=SimpleNamespace(execute=lambda sql:SimpleNamespace(fetchone=lambda:(1,)),
            set_authorizer=lambda callback:None,close=lambda:closed.append(True))
        output=io.StringIO()
        def run(args,**kwargs):
            if args[1]=='stop':raise OSError('private absolute path and credential')
            return SimpleNamespace(returncode=3)
        with patch.object(namespace['os'],'statvfs',side_effect=lambda path:SimpleNamespace(
                f_flag=os.ST_RDONLY if path==str(self.database) else 0)),redirect_stdout(output):
            result=namespace['coordinate'](str(self.database),'naver-product-export-reader.service',
                connect=lambda *a,**k:connection,run=run)
        self.assertEqual(result,1);self.assertEqual(closed,[True])
        self.assertEqual([json.loads(line) for line in output.getvalue().splitlines()],
            [{'status':'failed','code':'COORDINATION_READER_STOP_FAILED'},
             {'status':'failed','code':'COORDINATION_READER_FAILED'}])
        self.assertNotIn('private',output.getvalue())

    def test_coordinator_source_open_failure_is_closed_and_does_not_start_reader(self):
        namespace=self.coordinator();closed=[];output=io.StringIO()
        def execute(sql):raise sqlite3.OperationalError('unable to open private source database')
        connection=SimpleNamespace(execute=execute,close=lambda:closed.append(True))
        with patch.object(namespace['os'],'statvfs',side_effect=lambda path:SimpleNamespace(
                f_flag=os.ST_RDONLY if path==str(self.database) else 0)),redirect_stdout(output):
            result=namespace['coordinate'](str(self.database),'naver-product-export-reader.service',
                connect=lambda *a,**k:connection,run=lambda *a,**k:self.fail('must not start reader'))
        self.assertEqual(result,1);self.assertEqual(closed,[True])
        self.assertEqual(json.loads(output.getvalue()),{'status':'failed','code':'COORDINATION_SOURCE_OPEN'})
        self.assertNotIn('private',output.getvalue())

    def test_coordinator_inode_replacement_after_sqlite_open_blocks_reader(self):
        namespace=self.coordinator();closed=[];output=io.StringIO()
        before=self.database.read_bytes()
        def execute(sql):
            if sql=='PRAGMA schema_version':
                self.database.rename(self.source/'prior.db')
                self.database.write_bytes(before)
            return SimpleNamespace(fetchone=lambda:(1,))
        connection=SimpleNamespace(execute=execute,set_authorizer=lambda callback:None,
                                   close=lambda:closed.append(True))
        with patch.object(namespace['os'],'statvfs',side_effect=lambda path:SimpleNamespace(
                f_flag=os.ST_RDONLY if path==str(self.database) else 0)),redirect_stdout(output):
            result=namespace['coordinate'](str(self.database),'naver-product-export-reader.service',
                connect=lambda *a,**k:connection,run=lambda *a,**k:self.fail('must not start reader'))
        self.assertEqual(result,1);self.assertEqual(closed,[True])
        self.assertEqual(json.loads(output.getvalue())['code'],'COORDINATION_SOURCE_OPEN')

    def test_coordinator_created_unreadable_sidecar_is_not_repaired(self):
        namespace=self.coordinator();closed=[];output=io.StringIO()
        shm=Path(str(self.database)+'-shm')
        def execute(sql):
            if sql=='PRAGMA schema_version':
                shm.write_bytes(b'coordination fixture');shm.chmod(0o600)
            return SimpleNamespace(fetchone=lambda:(1,))
        connection=SimpleNamespace(execute=execute,set_authorizer=lambda callback:None,
                                   close=lambda:closed.append(True))
        with patch.object(namespace['os'],'statvfs',side_effect=lambda path:SimpleNamespace(
                f_flag=os.ST_RDONLY if path==str(self.database) else 0)),\
                patch.object(namespace['pwd'],'getpwnam',return_value=SimpleNamespace(pw_uid=self.uid+1)),redirect_stdout(output):
            result=namespace['coordinate'](str(self.database),'naver-product-export-reader.service',
                connect=lambda *a,**k:connection,run=lambda *a,**k:self.fail('must not start reader'))
        self.assertEqual(result,1);self.assertEqual(closed,[True])
        self.assertEqual(json.loads(output.getvalue())['code'],'COORDINATION_SOURCE_OPEN')
        self.assertEqual(shm.read_bytes(),b'coordination fixture');self.assertEqual(shm.stat().st_mode&0o777,0o600)

    def test_reader_failed_result_prevents_enable_and_rollback_stops_all_own_services(self):
        receipt=self.prepare()
        def command(args):
            if args[:3]==['systemctl','show','naver-product-export-reader.service']:
                self.calls.append(list(args));return b'Result=exit-code\nExecMainStatus=1\n'
            return self.command(args)
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_RUN_NOT_VERIFIED'):
            M.install(receipt,command=command)
        self.assertFalse(any(args[:2]==['systemctl','enable'] for args in self.calls))
        self.calls.clear();M.rollback(receipt,command=self.command)
        stopped={args[2] for args in self.calls if args[:2]==['systemctl','stop']}
        self.assertEqual(stopped,{f'naver-{kind}-export{suffix}.service' for kind in M.KINDS for suffix in ('','-reader')})
        self.assertEqual(list(self.units.iterdir()),[])

    def command(self,args):
        self.calls.append(list(args))
        if args[:2]==['systemctl','start']:
            kind = 'product' if 'product' in args[2] else 'market'
            target=self.outputs[kind]/'bundle.json'
            # Actual standalone CLI against synthetic SQLite. The fake systemctl
            # does not claim to exercise a real mount namespace or service user.
            result=subprocess.run([sys.executable,'-I','-B',str(self.install/self.plan['ops_commit']/('naver_'+kind+'_export.py')),
                '--database',str(self.database),'--output',str(target)],capture_output=True,check=True)
            self.assertEqual(json.loads(result.stdout)['status'],'ok')
            os.chown(target,self.uid,self.gid)
        if args[:2]==['systemctl','show']:
            return b'Result=success\nExecMainStatus=0\n'
        return b''

    def test_closed_plan_refuses_path_injection_broad_source_and_root(self):
        for key,value in [('source_directory','/root'),('source_directory','/tmp/a%h'),
                          ('source_directory',str(self.outputs['product'])),('database_name','../secret.db'),
                          ('exporter_user','root'),('source_group','root'),('python_executable','/tmp/python')]:
            with self.subTest(key=key,value=value),self.assertRaises(M.ExportInstallInvalid):
                M.build_plan(**{**self.plan,key:value})

    def test_pins_fail_before_host_source_access(self):
        with patch.object(M,'_source_identity',side_effect=AssertionError('Must not read host')) as source:
            with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_PIN'):
                M.prepare(self.plan,scripts=self.scripts,pins={**self.pins,M.SCRIPTS[0]:'0'*64},operation_id='b'*32)
            source.assert_not_called()

    def test_companion_and_units_bind_only_dedicated_directories_readonly(self):
        with patch.object(M,'_python_snapshot',side_effect=AssertionError('pure artifact rendering')):
            items=M.artifacts(self.plan,self.scripts,self.pins)
        self.assertEqual(len(items),9)
        engine=json.loads(items[M.COMPANION])['services']['naver-engine']
        self.assertEqual(set(engine),{'environment','volumes'});self.assertEqual(len(engine['volumes']),2)
        for row in engine['volumes']:
            self.assertIs(row['read_only'],True);self.assertIs(row['bind']['create_host_path'],False)
            self.assertNotIn(str(self.source),row['source'])
        for kind in M.KINDS:
            unit=items[f'naver-{kind}-export-reader.service'].decode()
            self.assertIn('ProtectHome=tmpfs\n',unit)
            self.assertIn(f'BindReadOnlyPaths={self.source}:/run/naver-saved-source:norbind\n',unit)
            self.assertIn('os.statvfs',unit);self.assertIn('os.ST_RDONLY',unit)
            self.assertNotIn('immutable=1',unit);self.assertNotIn('EnvironmentFile=',unit)
            self.assertIn('PrivateNetwork=true\n',unit);self.assertIn('CapabilityBoundingSet=\n',unit)
            binary=self.install/self.plan['ops_commit']/M.INTERPRETER
            self.assertIn(f'ExecStartPre={binary} -I -B -c ',unit)
            self.assertIn(f'ExecStart={binary} -I -B ',unit)
            self.assertIn('encodings,json,sqlite3,dataclasses,importlib,math',unit)
            self.assertNotIn('ExecStart=/usr/bin/python3 ',unit)
            self.assertIn(f'PartOf=naver-{kind}-export.service\n',unit)
            self.assertNotIn('After=naver-',unit)
            self.assertIn('TimeoutStartSec=45\n',unit)
            self.assertIn('TimeoutStopSec=5\n',unit)
            self.assertIn('KillMode=control-group\n',unit)
            self.assertIn('UMask=0027\n',unit)
            coordinator=items[f'naver-{kind}-export.service'].decode()
            self.assertIn('User=root\n',coordinator)
            self.assertIn('Group='+str(self.gid)+'\n',coordinator)
            self.assertIn(f'BindPaths={self.source}:/run/naver-saved-source:norbind\n',coordinator)
            self.assertIn('ReadWritePaths=/run/naver-saved-source\n',coordinator)
            self.assertIn('ReadOnlyPaths=/run/naver-saved-source/logic_data.db ',coordinator)
            self.assertIn('TimeoutStartSec=65\n',coordinator)
            self.assertIn('UMask=0022\n',coordinator)
            for guard in ('NoNewPrivileges=true','CapabilityBoundingSet=','PrivateNetwork=true',
                          'ProtectHome=tmpfs','ProtectSystem=strict','RestrictAddressFamilies=AF_UNIX'):
                self.assertIn(guard+'\n',coordinator)
            encoded=next(line for line in coordinator.splitlines() if line.startswith('ExecStart=')).split(' -c ',1)[1]
            source=json.loads(encoded)
            self.assertEqual(source,M._coordinator_source(self.plan,kind))
            compile(source,'embedded-coordinator','exec')
            self.assertNotIn('%',source);self.assertNotIn('$',source)
            self.assertNotIn('naver_'+kind+'_export.py',coordinator)

    def test_prepare_is_non_operational_and_source_change_blocks_install(self):
        receipt=self.prepare();self.assertEqual(self.calls,[]);self.assertEqual(list(self.units.iterdir()),[])
        old=self.database.with_suffix('.old');self.database.rename(old);self.database.write_bytes(old.read_bytes())
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_SOURCE_CHANGED'):
            M.install(receipt,command=self.command)
        self.assertEqual(self.calls,[])

    def test_actual_synthetic_cli_export_verify_then_rollback_preserves_source_and_bundles(self):
        before=(self.database.read_bytes(),self.database.stat().st_mtime_ns)
        receipt=self.prepare();result=M.install(receipt,command=self.command)
        self.assertEqual(result['state'],'installed');self.assertIs(result['engine_verified'],False)
        self.assertEqual(before,(self.database.read_bytes(),self.database.stat().st_mtime_ns))
        start=[i for i,args in enumerate(self.calls) if args[:2]==['systemctl','start']]
        enable=[i for i,args in enumerate(self.calls) if args[:2]==['systemctl','enable']]
        self.assertEqual(len(start),2);self.assertEqual(len(enable),2);self.assertLess(max(start),min(enable))
        summary=M.verify(receipt,command=self.command);self.assertEqual(summary['sources']['product']['products'],0)
        self.assertIs(summary['source_writes'],True);self.assertIs(summary['database_writes'],False)
        self.assertIs(summary['coordination_files_may_change'],True)
        output=json.dumps(summary);self.assertNotIn(str(self.database),output);self.assertNotIn('synthetic-exporter',output)
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_ALREADY_ATTEMPTED'):
            M.install(receipt,command=self.command)
        done=M.rollback(receipt,command=self.command);self.assertEqual(done['state'],'rolled_back')
        self.assertEqual(list(self.units.iterdir()),[])
        self.assertTrue(all((path/'bundle.json').exists() for path in self.outputs.values()))
        self.assertEqual(before,(self.database.read_bytes(),self.database.stat().st_mtime_ns))

    def test_live_wal_pair_is_read_and_later_commits_visible_without_source_repair(self):
        writer=sqlite3.connect(self.database);self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL');writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("INSERT INTO clients VALUES(1,'https://smartstore.naver.com/Synthetic/products/1','','advertiser','store')");writer.commit()
        self.assertTrue(Path(str(self.database)+'-wal').exists());self.assertTrue(Path(str(self.database)+'-shm').exists())
        receipt=self.prepare();M.install(receipt,command=self.command)
        first=json.loads((self.outputs['product']/'bundle.json').read_bytes());self.assertEqual(len(first['stores']),1)
        writer.execute("INSERT INTO clients VALUES(2,'https://smartstore.naver.com/Second/products/2','','advertiser','store')");writer.commit()
        stable={str(path):(path.read_bytes(),path.stat().st_mtime_ns) for path in (self.database,Path(str(self.database)+'-wal'))}
        self.command(['systemctl','start','naver-product-export.service'])
        second=json.loads((self.outputs['product']/'bundle.json').read_bytes());self.assertEqual(len(second['stores']),2)
        self.assertEqual(stable,{str(path):(path.read_bytes(),path.stat().st_mtime_ns) for path in (self.database,Path(str(self.database)+'-wal'))})

    def test_partial_failure_before_units_can_be_rolled_back_without_unknown_unit_calls(self):
        receipt=self.prepare();real=M._write_new
        def fail_script(path,*args):
            if path.parent.parent==self.install:raise OSError('synthetic')
            return real(path,*args)
        with patch.object(M,'_write_new',side_effect=fail_script):
            with self.assertRaises(OSError):M.install(receipt,command=self.command)
        self.assertEqual(M.rollback(receipt,command=self.command)['state'],'rolled_back')
        self.assertEqual(self.calls,[])

    def test_failed_one_shot_never_enables_timer_and_rollback_stops_only_own_units(self):
        receipt=self.prepare()
        def failed(args):
            self.calls.append(args)
            if args[:2]==['systemctl','start']:raise RuntimeError('private synthetic details')
            return b''
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_COMMAND_FAILED'):
            M.install(receipt,command=failed)
        self.assertFalse(any(args[:2]==['systemctl','enable'] for args in self.calls))
        M.rollback(receipt,command=self.command);self.assertEqual(list(self.units.iterdir()),[])

    def test_drift_and_symlink_block_verification_and_rollback_before_any_commands(self):
        receipt=self.prepare();M.install(receipt,command=self.command)
        path=self.units/'naver-product-export.service';path.write_bytes(b'foreign unit\n')
        self.calls.clear()
        with self.assertRaises(M.ExportInstallInvalid):M.verify(receipt,command=self.command)
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_ROLLBACK_DRIFT'):M.validate_rollback(receipt)
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_ROLLBACK_DRIFT'):M.rollback(receipt,command=self.command)
        self.assertEqual(self.calls,[])

    def test_validate_rollback_is_readonly_and_does_not_require_source_inode(self):
        receipt=self.prepare();M.install(receipt,command=self.command)
        self.calls.clear()
        files=list(self.units.iterdir())+list((self.install/self.plan['ops_commit']).iterdir())
        before={str(path):(path.read_bytes(),path.stat().st_mtime_ns) for path in files}
        self.database.rename(self.source/'old.db')
        self.database.write_bytes(b'changed source inode must not block rollback preflight')
        self.assertIsNone(M.validate_rollback(receipt))
        self.assertEqual(self.calls,[])
        self.assertEqual(before,{str(path):(path.read_bytes(),path.stat().st_mtime_ns) for path in files})

    def test_stale_or_malformed_bundle_is_not_successful_verification(self):
        receipt=self.prepare();M.install(receipt,command=self.command)
        path=self.outputs['product']/'bundle.json';value=json.loads(path.read_text())
        value['exported_at']=(datetime.now(timezone.utc)-timedelta(hours=31)).isoformat();path.write_text(json.dumps(value))
        with self.assertRaises(M.ExportInstallInvalid):M.verify(receipt,command=self.command)
        path.unlink();path.symlink_to(self.database)
        with self.assertRaises(M.ExportInstallInvalid):M.verify(receipt,command=self.command)

    def test_restrictive_umask_and_paired_rollback_allow_exact_new_operation(self):
        previous=os.umask(0o077)
        try:
            receipt=self.prepare();M.install(receipt,command=self.command)
            M.rollback(receipt,command=self.command)
            second=M.prepare(self.plan,scripts=self.scripts,pins=self.pins,operation_id='c'*32)
            result=M.install(second,command=self.command)
        finally:os.umask(previous)
        self.assertEqual(result['state'],'installed')
        self.assertEqual((self.install/self.plan['ops_commit']).stat().st_mode&0o777,0o755)
        self.assertTrue(all((self.units/f'naver-{kind}-export.service').stat().st_mode&0o777==0o644 for kind in M.KINDS))

    def test_partial_unit_creation_failure_does_not_stop_nonexistent_unit(self):
        receipt=self.prepare();real=M._write_new
        def fail_unit(path,*args):
            if path.parent==self.units:raise OSError('synthetic unit write failure')
            return real(path,*args)
        with patch.object(M,'_write_new',side_effect=fail_unit):
            with self.assertRaises(OSError):M.install(receipt,command=self.command)
        M.rollback(receipt,command=self.command)
        self.assertFalse(any(args[0]=='systemctl' and args[1] in ('stop','disable') for args in self.calls))

    def test_owner_only_system_binary_is_unchanged_and_copy_is_group_only(self):
        before=(self.python.read_bytes(),M._file_identity(self.python.stat()))
        receipt=self.prepare()
        self.assertEqual(receipt['version'],3)
        self.assertEqual(len(receipt['manifest']),10)
        staged=self.staging/receipt['operation_id']/M.INTERPRETER
        self.assertEqual(staged.stat().st_mode&0o777,0o600)
        M.install(receipt,command=self.command)
        binary=self.install/self.plan['ops_commit']/M.INTERPRETER
        info=binary.stat()
        self.assertEqual((info.st_uid,info.st_gid,info.st_mode&0o777),(M.ROOT_UID,self.gid,0o550))
        self.assertEqual(binary.read_bytes(),before[0])
        self.assertEqual(before,(self.python.read_bytes(),M._file_identity(self.python.stat())))
        M.validate_rollback(receipt);M.rollback(receipt,command=self.command)
        self.assertFalse(binary.exists())
        self.assertEqual(before,(self.python.read_bytes(),M._file_identity(self.python.stat())))

    def test_source_binary_drift_or_replacement_blocks_install_before_mutations(self):
        receipt=self.prepare()
        body=self.python.read_bytes()
        self.python.write_bytes(body+b'changed')
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_PREPARED_CHANGED'):
            M.install(receipt,command=self.command)
        self.assertEqual(self.calls,[]);self.assertEqual(list(self.install.iterdir()),[])

    def test_identical_source_binary_new_inode_blocks_install(self):
        receipt=self.prepare();body=self.python.read_bytes()
        self.python.rename(self.root/'old-python')
        self.python.write_bytes(body);self.python.chmod(0o700)
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_PREPARED_CHANGED'):
            M.install(receipt,command=self.command)
        self.assertEqual(self.calls,[])

    def test_staging_binary_replacement_even_identical_bytes_is_rejected(self):
        receipt=self.prepare();path=self.staging/receipt['operation_id']/M.INTERPRETER
        body=path.read_bytes();path.rename(path.with_name('foreign-old'))
        path.write_bytes(body);path.chmod(0o600)
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_PREPARED_CHANGED'):
            M.install(receipt,command=self.command)
        self.assertEqual(self.calls,[])

    def test_staging_reopen_does_not_bless_a_new_creation_inode(self):
        real=M._binary;staged=self.staging/('b'*32)/M.INTERPRETER
        def replace_staged(path,**kwargs):
            if path==staged:
                body=path.read_bytes();path.rename(path.with_name('foreign-old'))
                path.write_bytes(body);path.chmod(0o600)
            return real(path,**kwargs)
        with patch.object(M,'_binary',side_effect=replace_staged):
            with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_PREPARED_CHANGED'):
                self.prepare()
        self.assertFalse((staged.parent/'prepared.json').exists())
        self.assertEqual(self.calls,[])

    def test_installed_binary_drift_and_new_inode_are_not_deleted(self):
        receipt=self.prepare();M.install(receipt,command=self.command)
        path=self.install/self.plan['ops_commit']/M.INTERPRETER
        body=path.read_bytes();path.rename(path.with_name('foreign-old'))
        path.write_bytes(body);path.chmod(0o550);os.chown(path,M.ROOT_UID,self.gid)
        self.calls.clear()
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_INSTALLED_CHANGED'):
            M.verify(receipt,command=self.command)
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_ROLLBACK_DRIFT'):
            M.rollback(receipt,command=self.command)
        self.assertEqual(self.calls,[]);self.assertTrue(path.exists())

    def test_binary_size_policy_symlink_script_permissions_and_setuid_are_rejected(self):
        original=self.python.read_bytes()
        cases=('oversize','symlink','script','writable','setuid','hardlink')
        for case in cases:
            with self.subTest(case=case):
                self.python.unlink();self.python.write_bytes(original);self.python.chmod(0o700)
                if case=='oversize':
                    with self.python.open('r+b') as stream:stream.truncate(M.MAX_INTERPRETER+1)
                elif case=='symlink':
                    self.python.unlink();self.python.symlink_to(self.database)
                elif case=='script':self.python.write_bytes(b'#!/usr/bin/python3\nprint(1)\n')
                elif case=='writable':self.python.chmod(0o720)
                elif case=='setuid':self.python.chmod(0o4700)
                elif case=='hardlink':os.link(self.python,self.root/'python-hardlink')
                with self.assertRaises(M.ExportInstallInvalid):self.prepare()
                self.assertFalse((self.staging/('b'*32)).exists())
                if case=='hardlink':(self.root/'python-hardlink').unlink()
        self.assertEqual(self.calls,[])

    def test_binary_read_detects_fd_or_path_change(self):
        original=os.read; changed=False
        def change(fd,size):
            nonlocal changed
            chunk=original(fd,size)
            if not changed:
                changed=True
                with self.python.open('ab') as stream:stream.write(b'drift')
            return chunk
        with patch.object(M.os,'read',side_effect=change):
            with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_FILE_CHANGED'):
                self.prepare()
        self.assertFalse((self.staging/('b'*32)).exists())

    def test_same_parent_single_system_alias_only_and_final_symlink_rejected(self):
        # Exercise the real alias resolver against synthetic paths. Parent trust
        # is separately enforced by production _directory, not global chmod.
        self.python_target_patch.stop()
        alias=self.root/'python3';alias.symlink_to('python3.10')
        with patch.object(M,'_directory'):
            self.assertEqual(M._python_target({**self.plan,'python_executable':str(alias)}),self.python)
            alias.unlink();alias.symlink_to(self.database)
            with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_SYMLINK'):
                M._python_target({**self.plan,'python_executable':str(alias)})
            alias.unlink();alias.symlink_to('python3.10')
            self.python.unlink();self.python.symlink_to(self.database)
            with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_SYMLINK'):
                M._python_target({**self.plan,'python_executable':str(alias)})

    def test_binary_reopen_failure_retains_creation_proof_and_exact_rollback(self):
        receipt=self.prepare();real=M._binary
        binary=self.install/self.plan['ops_commit']/M.INTERPRETER
        def fail_installed(path,**kwargs):
            if path==binary:raise OSError('synthetic post-write reopen failure')
            return real(path,**kwargs)
        with patch.object(M,'_binary',side_effect=fail_installed):
            with self.assertRaisesRegex(OSError,'post-write reopen failure'):
                M.install(receipt,command=self.command)
        state=json.loads((self.staging/receipt['operation_id']/'installed.json').read_bytes())
        self.assertEqual(state['interpreter_identity'],M._file_identity(binary.stat()))
        self.assertEqual(self.calls,[])
        M.validate_rollback(receipt);M.rollback(receipt,command=self.command)
        self.assertFalse(binary.exists());self.assertEqual(self.calls,[])

    def test_binary_reopen_cannot_replace_creation_inode_proof(self):
        receipt=self.prepare();real=M._binary
        binary=self.install/self.plan['ops_commit']/M.INTERPRETER
        def replace_installed(path,**kwargs):
            if path==binary:
                body=path.read_bytes();path.rename(path.with_name('foreign-old'))
                path.write_bytes(body);path.chmod(0o550);os.chown(path,M.ROOT_UID,self.gid)
            return real(path,**kwargs)
        with patch.object(M,'_binary',side_effect=replace_installed):
            with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_INSTALLED_CHANGED'):
                M.install(receipt,command=self.command)
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_ROLLBACK_DRIFT'):
            M.rollback(receipt,command=self.command)
        self.assertTrue(binary.exists());self.assertEqual(self.calls,[])

    def test_failed_write_cleans_only_its_creation_inode_and_preserves_first_error(self):
        path=self.root/'new-copy';body=b'\x7fELFsynthetic'
        with patch.object(M,'_fsync_directory',side_effect=OSError('first write failure')):
            with self.assertRaisesRegex(OSError,'first write failure'):
                M._write_new(path,body,0o550,self.gid)
        self.assertFalse(path.exists())
        def replace_then_fail(directory):
            path.rename(self.root/'original-inode')
            path.write_bytes(b'foreign replacement')
            raise OSError('first write failure')
        with patch.object(M,'_fsync_directory',side_effect=replace_then_fail):
            with self.assertRaisesRegex(OSError,'first write failure'):
                M._write_new(path,body,0o550,self.gid)
        self.assertEqual(path.read_bytes(),b'foreign replacement')


if __name__=='__main__':unittest.main()
