"""Completion release remains closed; synthetic paired DB/code recovery."""
import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch
from contextlib import redirect_stdout,closing

spec=importlib.util.spec_from_file_location('completion',Path(__file__).parents[1]/'tools/naver_preview_completion_release.py')
C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C)


def pins(root):
    assets={}
    manifest={'naver_engine/store.py':(0o644,1,'b'*64)}
    for route,(_,_,mime) in C.OLD_REPORT_ASSETS.items():
        assets[route]=(1,'c'*64,mime)
        manifest['backend/naver_page/'+route.removeprefix('/naver/')]=(0o644,1,'c'*64)
    return {'TARGET_COMMIT':'f'*40,'TARGET_SOURCE_SHA256':'e'*64,
        'STORE_SHA256':{'old':C.STORE_SHA256['old'],'target':'b'*64},
        'OLD_MANIFEST':{'naver_engine/store.py':(0o644,1,C.STORE_SHA256['old'])},
        'TARGET_MANIFEST':manifest,'REPORT_ASSETS':assets,'SCHEMA_SHA256':{'old':'d'*64,'target':'e'*64},
        'CI_PROOF':{'source_commit':'f'*40,'tooling_head':'d'*40,'run_id':'12345678901','receipt_sha256':'a'*64}}


def configuration(*, inventory=True, execution=False):
    switches = dict.fromkeys(C.CONFIG_SWITCHES, False)
    switches.update(inventory=inventory, execution=execution)
    return dict(command='check-config', configuration='valid', switches=switches,
        network_performed=False, storage_opened=False, credentials_verified=False,
        web_available=False, deployment_ready=False)


class CompletionFailureDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper_path=Path(__file__).parents[1]/'tools/naver_saved_exports.py'
        spec=importlib.util.spec_from_file_location('exports_diagnostics',cls.helper_path)
        cls.exports=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.exports)

    def test_every_fixed_export_failure_code_is_explicitly_reviewed_and_reported(self):
        calls=[node for node in ast.walk(ast.parse(self.helper_path.read_text()))
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='_fail']
        self.assertTrue(calls)
        codes=set()
        for call in calls:
            self.assertEqual(len(call.args),1);self.assertEqual(call.keywords,[])
            self.assertIsInstance(call.args[0],ast.Constant)
            self.assertIs(type(call.args[0].value),str)
            codes.add(call.args[0].value)
        self.assertEqual(C.EXPORT_FAILURE_CODES,codes)
        for code in codes:
            for stage in ('saved_exports_binding','saved_exports_prepare','saved_exports_install'):
                with self.subTest(code=code,stage=stage),patch.object(C,'STAGE',stage):
                    self.assertEqual(C.failure_report(self.exports.ExportInstallInvalid(code)),
                        {'stage':stage,'error_kind':'ExportInstallInvalid','error_code':code})

    def test_export_diagnostics_never_publish_opaque_messages_paths_or_prefixes(self):
        private='/synthetic/private-value/runtime.env'
        errors=[self.exports.ExportInstallInvalid(private),
            self.exports.ExportInstallInvalid('EXPORT_UNREVIEWED_PRIVATE'),
            self.exports.ExportInstallInvalid('EXPORT_PATH '+private),
            self.exports.ExportInstallInvalid('EXPORT_PATH',private),
            self.exports.ExportInstallInvalid({'EXPORT_PATH':private}),
            FileExistsError(17,'opaque private-value',private)]
        for error in errors:
            error.failure_details={'failed_stage':'saved_exports_prepare',
                'failed_error_kind':type(error).__name__,'failed_error_code':'EXPORT_UNREVIEWED_PRIVATE',
                'cleanup_stage':private,'cleanup_error_code':private,'rollback_operation':private}
            with self.subTest(kind=type(error).__name__),patch.object(C,'STAGE','saved_exports_prepare'):
                result=C.failure_report(error)
            self.assertEqual(result,{'stage':'saved_exports_prepare','error_kind':type(error).__name__,
                'error_code':'UNRECOGNIZED','failed_stage':'saved_exports_prepare',
                'failed_error_kind':type(error).__name__})
            self.assertNotIn('private',json.dumps(result));self.assertNotIn('runtime.env',json.dumps(result))
        with patch.object(C,'STAGE','saved_exports_private'):
            self.assertEqual(C.failure_report(RuntimeError(private)),
                {'stage':'unknown','error_kind':'RuntimeError','error_code':'UNRECOGNIZED'})

    def test_capture_and_nested_failure_details_preserve_only_closed_export_labels(self):
        with patch.object(C,'STAGE','saved_exports_install'),patch.object(C,'OPERATION','package'):
            details=C._capture_failure(self.exports.ExportInstallInvalid('EXPORT_COMMAND_FAILED'))
            error=RuntimeError('COMMAND_FAILED');error.failure_details=details
            self.assertEqual(C.failure_report(error),{'stage':'saved_exports_install',
                'error_kind':'RuntimeError','error_code':'COMMAND_FAILED',
                'failed_stage':'saved_exports_install','failed_operation':'package',
                'failed_error_kind':'ExportInstallInvalid','failed_error_code':'EXPORT_COMMAND_FAILED'})

    def test_static_prepare_stages_are_public_but_unreviewed_dynamic_names_are_not(self):
        stages={'code_prepare_preflight','code_build_engine','code_build_relay',
            'code_config_engine','code_config_relay','code_check_config','code_prepare_postflight'}
        for stage in stages:
            with self.subTest(stage=stage),patch.object(C,'STAGE',stage):
                self.assertEqual(C._capture_failure(ValueError('COMMAND_FAILED'))['failed_stage'],stage)
        for stage in ('code_build_private','code_config_other','code_prepare_private'):
            with self.subTest(stage=stage),patch.object(C,'STAGE',stage):
                self.assertEqual(C._capture_failure(ValueError('COMMAND_FAILED'))['failed_stage'],'unknown')

    def test_export_command_details_accept_only_closed_enums_and_strict_exit_status(self):
        for stage in C.EXPORT_COMMAND_STAGES:
            error=ValueError('EXPORT_COMMAND_FAILED');error.failure_details={'export_command_stage':stage}
            self.assertEqual(C.failure_report(error)['export_command_stage'],stage)
        for issue in C.EXPORT_COMMAND_ISSUES:
            error=ValueError('EXPORT_COMMAND_FAILED');error.failure_details={'export_command_issue':issue}
            self.assertEqual(C.failure_report(error)['export_command_issue'],issue)
        for status in (0,1,255):
            error=ValueError('EXPORT_COMMAND_FAILED');error.failure_details={'export_command_status':status}
            self.assertEqual(C.failure_report(error)['export_command_status'],status)
        for status in (True,False,-1,256,1.0,'1',None,[],{}):
            error=ValueError('EXPORT_COMMAND_FAILED');error.failure_details={'export_command_status':status}
            self.assertNotIn('export_command_status',C.failure_report(error))
        for value in ('private/runtime.env','product_start private-value','EXPORT_NEW',None,[],{}):
            error=ValueError('EXPORT_COMMAND_FAILED')
            error.failure_details={'export_command_stage':value,'export_command_issue':value,'raw':'private-value'}
            report=C.failure_report(error)
            self.assertNotIn('export_command_stage',report);self.assertNotIn('export_command_issue',report)
            self.assertNotIn('private',json.dumps(report))


class CompletionRuntimeFlagsTests(unittest.TestCase):
    def test_closed_config_preserves_actual_inventory_and_rejects_enabled_execution(self):
        for inventory in (True, False):
            self.assertEqual(C.runtime_flags(json.dumps(configuration(inventory=inventory)).encode()),
                {'inventory_enabled':inventory,'execution_enabled':False})
        with self.assertRaisesRegex(ValueError,'^EXECUTION_ENABLED$'):
            C.runtime_flags(json.dumps(configuration(execution=True)).encode())

    def test_malformed_missing_duplicate_numeric_and_private_fields_refuse_closed(self):
        good = configuration()
        mutations = [dict(good, switches={k:v for k,v in good['switches'].items() if k!='execution'}),
            dict(good, switches=dict(good['switches'],execution=0)),dict(good,storage_opened=0),
            dict(good,credentials_verified=True),dict(good,command='run'),dict(good,secret='never-output'),
            dict(good,switches=dict(good['switches'],extra=False))]
        for value in mutations:
            with self.subTest(value=list(value)),self.assertRaisesRegex(ValueError,'^RUNTIME_CONFIG_PROOF$'):
                C.runtime_flags(json.dumps(value).encode())
        raw = json.dumps(good).encode()
        for value in (b'',raw.decode(),raw+b' '*4096,b'{"x":NaN}',
                raw.replace(b'"execution": false',b'"execution": false, "execution": false'),
                raw[:-1]+b',"command":"check-config"}',b'[[[[[[[[[[[[[[[[[[[[[[['):
            with self.subTest(kind=type(value).__name__),self.assertRaisesRegex(ValueError,'^RUNTIME_CONFIG_PROOF$'):
                C.runtime_flags(value)

    def test_old_container_script_reads_only_two_flags_with_strict_default_false_grammar(self):
        for value in ('false','off','0','',' false ','OFF'):
            result = subprocess.run([sys.executable,'-I','-B','-c',C.ENV_FLAGS_SCRIPT],
                env={'NAVER_ENGINE_EXECUTION_ENABLED':value,'NAVER_ENGINE_INVENTORY_ENABLED':'true',
                     'SYNTHETIC_PRIVATE_VALUE':'never-output'},capture_output=True,check=True)
            self.assertEqual(C.runtime_flags(result.stdout,environment=True),
                {'inventory_enabled':True,'execution_enabled':False})
            self.assertNotIn(b'never-output',result.stdout+result.stderr)
        result = subprocess.run([sys.executable,'-I','-B','-c',C.ENV_FLAGS_SCRIPT],env={},capture_output=True,check=True)
        self.assertEqual(C.runtime_flags(result.stdout,environment=True),
            {'inventory_enabled':False,'execution_enabled':False})
        for value in ('true','on','1',' TRUE '):
            result = subprocess.run([sys.executable,'-I','-B','-c',C.ENV_FLAGS_SCRIPT],
                env={'NAVER_ENGINE_EXECUTION_ENABLED':value},capture_output=True,check=True)
            with self.assertRaisesRegex(ValueError,'^EXECUTION_ENABLED$'):C.runtime_flags(result.stdout,environment=True)
        result = subprocess.run([sys.executable,'-I','-B','-c',C.ENV_FLAGS_SCRIPT],
            env={'NAVER_ENGINE_EXECUTION_ENABLED':'private-invalid-value'},capture_output=True)
        self.assertEqual(result.returncode,2);self.assertEqual(result.stdout+result.stderr,b'')
        for value in ({'inventory_enabled':False,'execution_enabled':0},
                {'inventory_enabled':False}, {'inventory_enabled':False,'execution_enabled':False,'secret':'never-output'}):
            with self.assertRaisesRegex(ValueError,'^RUNTIME_CONFIG_PROOF$'):C.runtime_flags(json.dumps(value).encode(),environment=True)

    def test_target_check_is_network_none_same_compose_and_removes_own_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'receipts').mkdir();seen=[]
            def write(path,body):path.write_bytes(body)
            def command(args,**kwargs):
                seen.append(args)
                override=Path(args[args.index('run')-1])
                self.assertEqual(override.read_bytes(),b'services:\n  naver-engine:\n    network_mode: none\n')
                return json.dumps(configuration()).encode()
            release=SimpleNamespace(ROOT=root,write_new=write,command=command,
                compose=lambda path,name:['docker','compose','--project-name','naver-engine','-f','same-base','-f','same-preview','-f','same-exports'])
            with patch.object(C,'TARGET_COMMIT','f'*40):
                result=C.target_runtime_flags(root/'target',release,'a'*32)
            self.assertEqual(result,{'inventory_enabled':True,'execution_enabled':False})
            self.assertEqual(list((root/'receipts').iterdir()),[])
            self.assertEqual(seen[0][4:10],['-f','same-base','-f','same-preview','-f','same-exports'])
            self.assertEqual(seen[0][-11:],['run','--rm','--no-deps','--pull','never','naver-engine','python','-B','-m','naver_runtime','check-config'])

    def test_target_check_failure_cleans_override_and_does_not_return_raw_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'receipts').mkdir()
            release=SimpleNamespace(ROOT=root,write_new=lambda path,body:path.write_bytes(body),
                command=lambda *args,**kw:b'{"private":"never-output"}',
                compose=lambda *args:['docker','compose','--project-name','naver-engine'])
            with patch.object(C,'TARGET_COMMIT','f'*40),self.assertRaisesRegex(ValueError,'^RUNTIME_CONFIG_PROOF$'):
                C.target_runtime_flags(root/'target',release,'a'*32)
            self.assertEqual(list((root/'receipts').iterdir()),[])

    def test_exact_running_container_check_uses_verified_identity_and_rejects_drift(self):
        before={'engine':{'id':'a'*64},'relay':{'id':'b'*64}}
        life=SimpleNamespace(_snapshot=Mock(return_value=before))
        release=SimpleNamespace(command=Mock(return_value=json.dumps(configuration()).encode()))
        receipt={'images':{'engine':'synthetic-engine','relay':'synthetic-relay'}}
        self.assertEqual(C.container_runtime_flags(Path('/synthetic/target'),receipt,release,life,target=True),
            {'inventory_enabled':True,'execution_enabled':False})
        self.assertEqual(release.command.call_args.args[0],['docker','exec','a'*64,'python','-B','-m','naver_runtime','check-config'])
        life._snapshot=Mock(side_effect=[before,{'engine':{'id':'c'*64},'relay':before['relay']}])
        with self.assertRaisesRegex(ValueError,'^RUNTIME_CONFIG_DRIFT$'):
            C.container_runtime_flags(Path('/synthetic/target'),receipt,release,life,target=True)
        release.command.reset_mock();life._snapshot=Mock(return_value={'engine':{'id':'invalid'}})
        with self.assertRaisesRegex(ValueError,'^RUNTIME_CONFIG_PROOF$'):
            C.container_runtime_flags(Path('/synthetic/target'),receipt,release,life)
        release.command.assert_not_called()

    def test_immutable_environment_reduces_only_two_flags_and_rejects_duplicate_or_malformed_flags(self):
        private='SYNTHETIC_PRIVATE=never-output'
        for value in ('false','off','0','',' false ','OFF'):
            raw=json.dumps([private,'NAVER_ENGINE_INVENTORY_ENABLED=true','NAVER_ENGINE_EXECUTION_ENABLED='+value]).encode()
            self.assertEqual(C.container_environment_flags(raw),{'inventory_enabled':True,'execution_enabled':False})
        self.assertEqual(C.container_environment_flags(b'[]'),{'inventory_enabled':False,'execution_enabled':False})
        for value in ('true','on','1',' TRUE '):
            with self.assertRaisesRegex(ValueError,'^EXECUTION_ENABLED$'):
                C.container_environment_flags(json.dumps([private,'NAVER_ENGINE_EXECUTION_ENABLED='+value]).encode())
        invalid=[b'',b'null',b'{}',b'[0]',b'[NaN]',json.dumps([private]*257).encode(),
            json.dumps([private,'NAVER_ENGINE_EXECUTION_ENABLED=false','NAVER_ENGINE_EXECUTION_ENABLED=false']).encode(),
            json.dumps([private,'NAVER_ENGINE_EXECUTION_ENABLED=private-invalid']).encode(),
            json.dumps([private,'NAVER_ENGINE_EXECUTION_ENABLED']).encode(),
            json.dumps([private+'\x00']).encode(),json.dumps([private]).encode()+b' '*65536]
        for raw in invalid:
            with self.subTest(kind=len(raw)),self.assertRaisesRegex(ValueError,'^RUNTIME_CONFIG_PROOF$') as caught:
                C.container_environment_flags(raw)
            self.assertNotIn('never-output',str(caught.exception))

    def test_stopped_target_inspection_requires_exact_source_image_service_and_no_running_writer(self):
        row={'id':'a'*64,'image':'sha256:'+'b'*64,'source':'f'*40,'project':'naver-engine',
            'service':'naver-engine','running':False,'restarting':False,'pid':0}
        receipt={'source_commit':'f'*40,'images':{'engine':row['image']}}
        life=SimpleNamespace(UNITS=('engine.service',),_state=lambda rel,unit,key:
            {'ActiveState':'inactive','SubState':'dead','MainPID':'0'}[key])
        calls=[]
        def command(args,**kw):
            calls.append(args)
            if args[-3:]==['ps','--all','--quiet']:return ('a'*64+'\n').encode()
            return json.dumps(row).encode()
        release=SimpleNamespace(compose=lambda *args:['compose','exact-target'],command=command)
        path=Path('/synthetic/naver-'+'f'*40)
        with patch.object(C,'TARGET_COMMIT','f'*40):
            self.assertEqual(C.target_engine_snapshot(path,receipt,release,life,stopped=True),row)
            for key,value in (('id','c'*64),('source','e'*40),('image','sha256:'+'c'*64),
                    ('project','another'),('service','another'),('running',True),('restarting',True),('pid',False),('pid',1)):
                changed=dict(row);changed[key]=value
                with patch.object(release,'command',side_effect=lambda args,**kw:
                        ('a'*64+'\n').encode() if args[-3:]==['ps','--all','--quiet'] else json.dumps(changed).encode()),\
                        self.subTest(key=key),self.assertRaisesRegex(ValueError,'^RUNTIME_CONFIG_DRIFT$'):
                    C.target_engine_snapshot(path,receipt,release,life,stopped=True)
            release.command=Mock()
            life._state=lambda *args:'active'
            with self.assertRaisesRegex(ValueError,'^ACCOUNT_WRITER_NOT_STOPPED$'):
                C.target_engine_snapshot(path,receipt,release,life,stopped=True)
            release.command.assert_not_called()
        self.assertTrue(all('.Config.Env' not in ' '.join(args) for args in calls))

    def test_prestart_reads_private_env_only_for_exact_stopped_identity_and_requires_unchanged_snapshot(self):
        before={'id':'a'*64,'image':'sha256:'+'b'*64,'source':'f'*40,'project':'naver-engine',
            'service':'naver-engine','running':False,'restarting':False,'pid':0}
        release=SimpleNamespace(command=Mock(return_value=json.dumps([
            'PRIVATE=never-output','NAVER_ENGINE_INVENTORY_ENABLED=true','NAVER_ENGINE_EXECUTION_ENABLED=false']).encode()))
        with patch.object(C,'target_engine_snapshot',return_value=before):
            flags,proof=C.stopped_container_runtime_flags(Path('/synthetic'),{},release,Mock())
        self.assertEqual(flags,{'inventory_enabled':True,'execution_enabled':False});self.assertEqual(proof,before)
        self.assertNotIn('never-output',json.dumps((flags,proof)))
        self.assertEqual(release.command.call_args.args[0],['docker','inspect','--format','{{json .Config.Env}}','a'*64])
        with patch.object(C,'target_engine_snapshot',side_effect=[before,dict(before,id='c'*64)]),\
                self.assertRaisesRegex(ValueError,'^RUNTIME_CONFIG_DRIFT$'):
            C.stopped_container_runtime_flags(Path('/synthetic'),{},release,Mock())

    def test_actual_started_container_must_match_prestart_immutable_identity_before_exec(self):
        expected={'id':'a'*64,'image':'sha256:'+'b'*64,'source':'f'*40,'project':'naver-engine',
            'service':'naver-engine','running':False,'restarting':False,'pid':0}
        running=dict(expected,running=True,pid=123)
        life=SimpleNamespace(_snapshot=Mock(return_value={'engine':{'id':'a'*64}}))
        release=SimpleNamespace(command=Mock(return_value=json.dumps(configuration()).encode()))
        receipt={'images':{'engine':expected['image']}}
        with patch.object(C,'target_engine_snapshot',return_value=running):
            self.assertEqual(C.container_runtime_flags(Path('/synthetic'),receipt,release,life,target=True,expected=expected),
                {'inventory_enabled':True,'execution_enabled':False})
        for key,value in (('id','c'*64),('image','sha256:'+'c'*64),('source','e'*40),
                ('project','another'),('service','another')):
            release.command.reset_mock()
            with patch.object(C,'target_engine_snapshot',return_value=dict(running,**{key:value})),\
                    self.subTest(key=key),self.assertRaisesRegex(ValueError,'^RUNTIME_CONFIG_DRIFT$'):
                C.container_runtime_flags(Path('/synthetic'),receipt,release,life,target=True,expected=expected)
            release.command.assert_not_called()


class CompletionPinsTests(unittest.TestCase):
    def test_pending_profile_refuses_prepare_apply_before_any_host_file_or_db_action(self):
        host,release,life,upgrade=Mock(),Mock(),Mock(),Mock()
        for call in (lambda:C.prepare({},host,release,life,upgrade),lambda:C.apply({},host,release,life,upgrade),lambda:C.rollback({},host,release,life,upgrade)):
            with patch.object(C,'TARGET_COMMIT',None),self.assertRaisesRegex(ValueError,'CODE_TARGET_NOT_PINNED'):call()
        for adapter in (host,release,life,upgrade):self.assertEqual(adapter.mock_calls,[])
    def test_each_exact_pin_mandatory_and_oversized_or_forbidden_manifest_refused(self):
        base=pins(None)
        with patch.multiple(C,**base):C.require_pins()
        for name in ('TARGET_COMMIT','TARGET_SOURCE_SHA256','OLD_MANIFEST','TARGET_MANIFEST','CI_PROOF','REPORT_ASSETS','SCHEMA_SHA256'):
            with patch.multiple(C,**{**base,name:None}),self.subTest(name=name),self.assertRaises(ValueError):C.require_pins()
        for name in ('naver_engine/store 2.py','HANDOVER.md','deploy/runtime.env','naver_engine/../x.py','naver_engine/tests/test_x.py'):
            with patch.multiple(C,**{**base,'TARGET_MANIFEST':{**base['TARGET_MANIFEST'],name:(0o644,1,'a'*64)}}),self.subTest(name=name),self.assertRaises(ValueError):C.require_pins()
    def test_ci_source_or_asset_manifest_mismatch_cannot_be_approved_by_package(self):
        base=pins(None)
        for changed in ({'CI_PROOF':{**base['CI_PROOF'],'source_commit':'a'*40}},
            {'TARGET_MANIFEST':{**base['TARGET_MANIFEST'],'backend/naver_page/app.js':(0o644,2,'c'*64)}},
            {'STORE_SHA256':{'old':C.STORE_SHA256['old'],'target':'9'*64}}):
            with patch.multiple(C,**{**base,**changed}),self.assertRaises(ValueError):C.require_pins()
    def test_full_tree_manifest_refuses_unlisted_file_before_read_or_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=Path(tmp).resolve()/'old';new=Path(tmp).resolve()/'new';old.mkdir();new.mkdir()
            for path in (old,new):(path/'naver_engine').mkdir();(path/'naver_engine/store.py').write_bytes(b'x')
            forbidden=new/'naver_engine/store 2.py';forbidden.write_bytes(b'synthetic-never-read')
            adapter=SimpleNamespace(read_file=lambda path,**kw:path.read_bytes())
            seen=[]
            def read(path,**kwargs):seen.append(path);return path.read_bytes()
            adapter.read_file=read
            manifest={'naver_engine/store.py':(0o644,1,hashlib.sha256(b'x').hexdigest())}
            with patch.object(C,'require_pins'),patch.object(C,'OLD_MANIFEST',manifest),patch.object(C,'TARGET_MANIFEST',manifest):
                with self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):C.compatible_code_scope(old,new,adapter)
            self.assertNotIn(forbidden,seen)
    def test_network_none_migration_script_has_no_provider_erp_naver_or_startup(self):
        script=C.MIGRATION_SCRIPT
        self.assertIn('st._migrate();st._migrate()',script)
        self.assertNotIn('open_writer(',script)
        self.assertNotIn('dependencies(',script)
        self.assertNotIn('provider',script)
        self.assertNotIn('sync_org',script)
        self.assertIn('rows()!=before',script)
        self.assertIn("shape(c)!=PINS['target']",script)


class CompletionDatabaseTests(unittest.TestCase):
    def test_schema_identity_keeps_constraints_and_zero_null_distinct(self):
        first=sqlite3.connect(':memory:');second=sqlite3.connect(':memory:')
        self.addCleanup(first.close);self.addCleanup(second.close)
        for c in (first,second):c.execute('CREATE TABLE naver_auto_meta(key TEXT,value TEXT)');c.execute("INSERT INTO naver_auto_meta VALUES('schema_version','11')")
        first.execute('CREATE TABLE example(n INTEGER CHECK(n>0))');second.execute('CREATE TABLE example(n INTEGER CHECK(n>=0))')
        with patch.object(C,'SCHEMA_SHA256',{'old':C.schema_digest(first),'target':C.schema_digest(second)}):
            C.database_contract(first,C.OLD_COMMIT)
            with self.assertRaisesRegex(ValueError,'DB_OLD_SCHEMA'):C.database_contract(second,C.OLD_COMMIT)
    def fixture(self,root):
        data=root/'data';data.mkdir();(root/'receipts').mkdir()
        db=data/'engine.db';c=sqlite3.connect(db,isolation_level=None)
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE naver_auto_meta(key TEXT PRIMARY KEY,value TEXT)')
        c.execute("INSERT INTO naver_auto_meta VALUES('schema_version','11')")
        c.execute('CREATE TABLE t(owner INTEGER,zero INTEGER,missing REAL)')
        c.execute('INSERT INTO t VALUES(1,0,NULL)');os.chmod(db,0o600)
        old_shape=C.schema_digest(c)
        def new(path,body,**kw):
            with path.open('xb') as f:f.write(body)
            os.chmod(path,kw.get('mode',0o600))
        def trusted(path,**kw):
            if kw.get('new'):path.mkdir(mode=kw.get('mode',0o700))
            self.assertTrue(path.is_dir());self.assertFalse(path.is_symlink())
        def read(path,**kw):
            self.assertFalse(path.is_symlink())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),kw.get('mode',0o600))
            body=path.read_bytes();self.assertLessEqual(len(body),kw.get('maximum',1024**3))
            return body
        release=SimpleNamespace(ROOT=root,write_new=new,trusted_dir=trusted)
        upgrade=SimpleNamespace(read_file=read)
        original=C.os.fstat
        def virtual_owner(fd):
            row=original(fd)
            operating=any((p.stat().st_dev,p.stat().st_ino)==(row.st_dev,row.st_ino)
                for p in data.rglob('*') if p.is_file())
            owner=10001 if operating else 0
            return SimpleNamespace(st_mode=row.st_mode,st_nlink=row.st_nlink,st_uid=owner,st_gid=owner,
                st_dev=row.st_dev,st_ino=row.st_ino,st_size=row.st_size,st_mtime_ns=row.st_mtime_ns,st_ctime_ns=row.st_ctime_ns)
        return data,c,old_shape,release,upgrade,virtual_owner
    def test_actual_sqlite_backup_roundtrip_keeps_committed_wal_zero_null_and_quarantines_failed_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();data,c,shape,release,upgrade,owner=self.fixture(root)
            c.close()
            # A stopped writer leaves committed WAL and an uncommitted txn.
            # Unlike opening/closing read_bytes in this process, this fixture
            # does not accidentally release a live SQLite lock on macOS.
            script="import os,sqlite3,sys; c=sqlite3.connect(sys.argv[1],isolation_level=None); c.execute('PRAGMA journal_mode=WAL'); c.execute('UPDATE t SET owner=7'); c.execute('BEGIN'); c.execute('INSERT INTO t VALUES(2,0,0)'); os._exit(0)"
            subprocess.run([sys.executable,'-I','-B','-c',script,str(data/'engine.db')],check=True,capture_output=True,timeout=10)
            self.assertTrue((data/'engine.db-wal').exists());self.assertTrue((data/'engine.db-shm').exists())
            with patch.object(C,'DATA',data),patch.object(C,'SCHEMA_SHA256',{'old':shape,'target':'f'*64}),patch.object(C.os,'fstat',side_effect=owner):
                snapshot=C.db_snapshot('a'*32,release,upgrade)
                with closing(sqlite3.connect(snapshot[0])) as saved:self.assertEqual(saved.execute('SELECT * FROM t').fetchall(),[(7,0,None)])
                self.assertTrue(json.loads((root/'receipts'/('completion-snapshot-'+'a'*32+'.json')).read_text())['snapshot_restore_verified'])
                with closing(sqlite3.connect(data/'engine.db',isolation_level=None)) as current:
                    current.execute('UPDATE t SET owner=9');current.execute("UPDATE naver_auto_meta SET value='21'")
                C.restore_db(snapshot,'a'*32,release,upgrade)
                with closing(sqlite3.connect(data/'engine.db')) as restored:self.assertEqual(restored.execute('SELECT * FROM t').fetchall(),[(7,0,None)])
                with closing(sqlite3.connect(data/('.completion-failed-db-'+'a'*32)/'engine.db')) as failed:self.assertEqual(failed.execute('SELECT owner FROM t').fetchall(),[(9,)])
    def test_snapshot_digest_drift_refuses_before_any_current_database_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();data,c,shape,release,upgrade,owner=self.fixture(root)
            c.close()
            with patch.object(C,'DATA',data),patch.object(C,'SCHEMA_SHA256',{'old':shape,'target':'f'*64}),patch.object(C.os,'fstat',side_effect=owner):
                snapshot=C.db_snapshot('b'*32,release,upgrade)
                original=(data/'engine.db').read_bytes();snapshot[0].write_bytes(b'corrupt')
                with self.assertRaisesRegex(ValueError,'DB_SNAPSHOT_CHANGED'):C.restore_db(snapshot,'b'*32,release,upgrade)
                self.assertEqual((data/'engine.db').read_bytes(),original)
                self.assertFalse((data/('.completion-failed-db-'+'b'*32)).exists())

    def test_two_gib_boundary_and_exact_file_policy_are_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp).resolve()/'database.sqlite';path.write_bytes(b'x');path.chmod(0o600)
            original=os.fstat
            def metadata(size):
                def result(fd):
                    row=original(fd)
                    return SimpleNamespace(st_mode=row.st_mode,st_nlink=row.st_nlink,st_uid=0,st_gid=0,
                        st_dev=row.st_dev,st_ino=row.st_ino,st_size=size,st_mtime_ns=row.st_mtime_ns,st_ctime_ns=row.st_ctime_ns)
                return result
            with patch.object(C.os,'read',side_effect=AssertionError('BODY_READ')):
                with patch.object(C.os,'fstat',side_effect=metadata(2*1024**3)):
                    with C._database_file(path):pass
                for size in (0,2*1024**3+1):
                    with patch.object(C.os,'fstat',side_effect=metadata(size)),self.assertRaisesRegex(ValueError,'^DB_IDENTITY$'):
                        with C._database_file(path):pass
                path.chmod(0o644)
                with patch.object(C.os,'fstat',side_effect=metadata(1)),self.assertRaisesRegex(ValueError,'^DB_IDENTITY$'):
                    with C._database_file(path):pass
                path.chmod(0o600);os.link(path,path.with_name('hardlink'))
                with patch.object(C.os,'fstat',side_effect=metadata(1)),self.assertRaisesRegex(ValueError,'^DB_IDENTITY$'):
                    with C._database_file(path):pass
                link=path.with_name('symlink');link.symlink_to(path)
                with self.assertRaises(OSError):
                    with C._database_file(link):pass

    def test_sparse_over_one_gib_preflight_combines_disk_budget_before_any_body_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();data,c,shape,release,upgrade,owner=self.fixture(root);c.close()
            size=1024**3+1
            with (data/'engine.db').open('r+b') as output:output.truncate(size)
            need=3*size+C.DATABASE_RESERVE_BYTES
            with patch.object(C,'DATA',data),patch.object(C.os,'fstat',side_effect=owner),\
                    patch.object(C.os,'read',side_effect=AssertionError('BODY_READ')):
                with patch.object(C.os,'statvfs',return_value=SimpleNamespace(f_bavail=need,f_frsize=1)):
                    C.database_preflight(release)
                with patch.object(C.os,'statvfs',return_value=SimpleNamespace(f_bavail=need-1,f_frsize=1)),\
                        self.assertRaisesRegex(ValueError,'^DB_SPACE$'):C.database_preflight(release)
                with (data/'engine.db').open('r+b') as output:output.truncate(C.DATABASE_MAX_BYTES+1)
                with self.assertRaisesRegex(ValueError,'^DB_IDENTITY$'):C.database_preflight(release)

    def test_distinct_disk_budget_checks_receipts_and_data_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();data,c,shape,release,upgrade,owner=self.fixture(root);c.close()
            size=(data/'engine.db').stat().st_size;original=Path.stat
            def named(path,*args,**kwargs):
                info=original(path,*args,**kwargs)
                if path==root/'receipts':return SimpleNamespace(st_dev=info.st_dev+1)
                return info
            limits={root/'receipts':2*size+C.DATABASE_RESERVE_BYTES,data:size+C.DATABASE_RESERVE_BYTES}
            def capacity(path):return SimpleNamespace(f_bavail=limits[path],f_frsize=1)
            with patch.object(C,'DATA',data),patch.object(C.os,'fstat',side_effect=owner),\
                    patch.object(Path,'stat',new=named),patch.object(C.os,'statvfs',side_effect=capacity):
                C.database_preflight(release)
                for path in (data,root/'receipts'):
                    limits[path]-=1
                    with self.assertRaisesRegex(ValueError,'^DB_SPACE$'):C.database_preflight(release)
                    limits[path]+=1

    def test_live_metadata_preflight_does_not_require_unchanged_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();data,c,shape,release,upgrade,owner=self.fixture(root);c.close()
            original=C._database_metadata;calls=[]
            def metadata(path,fd,**kwargs):
                result=original(path,fd,**kwargs);calls.append(1)
                return (*result[:3],result[3]+len(calls),result[4])
            with patch.object(C,'DATA',data),patch.object(C.os,'fstat',side_effect=owner),\
                    patch.object(C,'_database_metadata',side_effect=metadata):C.database_preflight(release,space=False)
            self.assertGreaterEqual(len(calls),2)

    def test_private_restore_copy_and_digest_use_one_mib_reads_and_no_full_body_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();data,c,shape,release,upgrade,owner=self.fixture(root);c.close()
            source=root/'receipts'/'source.sqlite';body=b'x'*(3*1024**2+17);source.write_bytes(body);source.chmod(0o600)
            expected=hashlib.sha256(body).hexdigest();destination=data/'copy.sqlite';reads=[];original=os.read
            def read(fd,size):reads.append(size);return original(fd,size)
            with patch.object(C.os,'fstat',side_effect=owner),patch.object(C.os,'read',side_effect=read),\
                    patch.object(Path,'read_bytes',side_effect=AssertionError('FULL_BODY_READ')):
                self.assertEqual(C._database_digest(source),expected)
                C._database_copy(source,destination,expected,release)
                self.assertEqual(C._database_digest(destination,uid=10001,gid=10001),expected)
            self.assertGreater(len(reads),3);self.assertEqual(set(reads),{1024**2})
            self.assertEqual(destination.stat().st_mode&0o777,0o600)

    def test_backup_restore_never_call_upgrade_full_file_reader_or_path_read_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();data,c,shape,release,upgrade,owner=self.fixture(root)
            upgrade.read_file=Mock(side_effect=AssertionError('FULL_BODY_READ'))
            c.close()
            with patch.object(C,'DATA',data),patch.object(C,'SCHEMA_SHA256',{'old':shape,'target':'f'*64}),\
                    patch.object(C.os,'fstat',side_effect=owner),patch.object(Path,'read_bytes',side_effect=AssertionError('FULL_BODY_READ')):
                snapshot=C.db_snapshot('c'*32,release,upgrade)
                with closing(sqlite3.connect(data/'engine.db')) as current:current.execute('UPDATE t SET owner=9');current.commit()
                C.restore_db(snapshot,'c'*32,release,upgrade)
                C.verify_database_schema(C.OLD_COMMIT,release,upgrade)
            upgrade.read_file.assert_not_called()
            with closing(sqlite3.connect(data/'engine.db')) as restored:self.assertEqual(restored.execute('SELECT * FROM t').fetchall(),[(1,0,None)])

    def test_stopped_sidecar_free_wal_database_schema_uses_immutable_without_new_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();data,c,shape,release,upgrade,owner=self.fixture(root);c.close()
            db=data/'engine.db';original=sqlite3.connect;uris=[]
            def connect(filename,*args,**kwargs):uris.append(filename);return original(filename,*args,**kwargs)
            with patch.object(C,'DATA',data),patch.object(C,'SCHEMA_SHA256',{'old':shape,'target':'f'*64}),\
                    patch.object(C.os,'fstat',side_effect=owner),patch.object(C.sqlite3,'connect',side_effect=connect):
                C.verify_database_schema(C.OLD_COMMIT,release,upgrade)
            self.assertEqual(uris,[db.as_uri()+'?mode=ro&immutable=1'])
            self.assertFalse(any(os.path.lexists(str(db)+suffix) for suffix in ('-wal','-shm','-journal')))

    def test_held_inode_replacement_and_incomplete_wal_pair_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();data,c,shape,release,upgrade,owner=self.fixture(root);c.close();db=data/'engine.db'
            with patch.object(C.os,'fstat',side_effect=owner):
                with self.assertRaisesRegex(ValueError,'^DB_IDENTITY$'):
                    with C._database_file(db,uid=10001,gid=10001):
                        replacement=data/'replacement';replacement.write_bytes(b'x');replacement.chmod(0o600);os.replace(replacement,db)
                (data/'engine.db-wal').write_bytes(b'');(data/'engine.db-wal').chmod(0o600)
                with C._database_file(db,uid=10001,gid=10001) as (fd,_),patch.object(C.sqlite3,'connect',side_effect=AssertionError('SQLITE_OPEN')):
                    with self.assertRaisesRegex(ValueError,'^DB_IDENTITY$'):
                        with C._database_reader(db,fd,uid=10001,gid=10001):pass


class CompletionMigrationScriptTests(unittest.TestCase):
    def scene(self,mutant=False):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'synthetic.sqlite';real_connect=sqlite3.connect
            c=real_connect(db,isolation_level=None)
            c.execute('CREATE TABLE naver_auto_meta(key TEXT,value TEXT)')
            c.execute("INSERT INTO naver_auto_meta VALUES('schema_version','11')")
            c.execute('CREATE TABLE t(owner INTEGER,zero INTEGER,missing REAL)')
            c.execute('INSERT INTO t VALUES(1,0,NULL)');old=C.schema_digest(c)
            c.execute('CREATE TABLE new_t(n INTEGER)')
            for table in C.RANDOMIZED_TABLES:c.execute('CREATE TABLE '+table+'(n INTEGER)')
            c.execute("UPDATE naver_auto_meta SET value='21'");target=C.schema_digest(c)
            c.execute('DROP TABLE new_t')
            for table in C.RANDOMIZED_TABLES:c.execute('DROP TABLE '+table)
            c.execute("UPDATE naver_auto_meta SET value='11'");c.close()
            class Store:
                def _migrate(self):
                    self._conn.execute('CREATE TABLE IF NOT EXISTS new_t(n INTEGER)')
                    for table in C.RANDOMIZED_TABLES:self._conn.execute('CREATE TABLE IF NOT EXISTS '+table+'(n INTEGER)')
                    self._conn.execute("UPDATE naver_auto_meta SET value='21'")
                    if mutant:self._conn.execute('UPDATE t SET missing=0')
            module=SimpleNamespace(store=SimpleNamespace(Store=Store,SCHEMA_VERSION=21))
            def connect(path,*args,**kwargs):
                self.assertEqual(path,'/var/lib/naver-engine/engine.db')
                result=real_connect(db,*args,**kwargs);self.addCleanup(result.close);return result
            output=io.StringIO()
            with patch.dict(sys.modules,{'naver_engine':module}),patch.object(sqlite3,'connect',side_effect=connect),patch.object(sys,'path',list(sys.path)),redirect_stdout(output):
                try:exec(C.MIGRATION_SCRIPT,{'PINS':{'old':old,'target':target}})
                except SystemExit as e:self.assertEqual(e.code,1)
            return json.loads(output.getvalue())
    def test_exact_server_script_reports_only_closed_aggregate_and_repeats(self):
        result=self.scene();self.assertEqual(result,{'ok':True,'schema':21,'old_schema':11,'old_tables':2,'old_rows':1,'preserved_rows':True,'migration_repeatable':True,'network_calls':0,'randomized_tables':sorted(C.RANDOMIZED_TABLES),'randomized_tables_empty':True})
    def test_exact_server_script_refuses_null_to_zero_existing_data_mutation(self):
        self.assertEqual(self.scene(True),{'ok':False,'step':'migration_apply','code':'DB_ROWS_CHANGED'})


class CompletionMigrationControllerTests(unittest.TestCase):
    def test_success_requires_exact_twelve_empty_randomized_tables_proof(self):
        valid={'ok':True,'schema':21,'old_schema':11,'old_tables':2,'old_rows':1,
            'preserved_rows':True,'migration_repeatable':True,'network_calls':0,
            'randomized_tables':sorted(C.RANDOMIZED_TABLES),'randomized_tables_empty':True}
        invalid=[]
        for field in ('randomized_tables','randomized_tables_empty'):
            row=dict(valid);row.pop(field);invalid.append(row)
        invalid.extend([{**valid,'randomized_tables':valid['randomized_tables'][:-1]},
            {**valid,'randomized_tables':list(reversed(valid['randomized_tables']))},
            {**valid,'randomized_tables':valid['randomized_tables']+['naver_randomized_extra']},
            {**valid,'randomized_tables_empty':False},{**valid,'randomized_tables_empty':1}])
        for result in [valid,*invalid]:
            with self.subTest(result=result):
                release=Mock();release.ROOT=Path('/synthetic');release.compose.return_value=['compose']
                def command(args,**kwargs):
                    if args[:2]==['docker','wait']:return b'0'
                    if args[:2]==['docker','logs']:return json.dumps(result).encode()
                    if args[:2]==['docker','ps']:return b''
                    if args[0]=='compose':return b'a'*64
                    raise AssertionError('UNEXPECTED_LOCAL_COMMAND')
                release.command.side_effect=command
                with patch.object(C,'TARGET_COMMIT','f'*40):
                    if result is valid:self.assertEqual(C.migrate_database(Path('/synthetic/target'),release),valid)
                    else:
                        with self.assertRaisesRegex(ValueError,'SOURCE_WARM_FAILED'):C.migrate_database(Path('/synthetic/target'),release)

    def test_closed_migration_failure_keeps_exact_reason_and_does_not_return_raw_log(self):
        for code in ('DB_ROWS_CHANGED','DB_TARGET_SCHEMA'):
            release=Mock();release.ROOT=Path('/synthetic');release.compose.return_value=['compose','--project-name','naver-engine']
            def command(args,**kwargs):
                if args[:2]==['docker','wait']:return b'1'
                if args[:2]==['docker','logs']:return json.dumps({'ok':False,'step':'migration_apply','code':code}).encode()
                if args[:2]==['docker','ps']:return b''
                if args[0]=='compose':return b'a'*64
                raise AssertionError('UNEXPECTED_LOCAL_COMMAND')
            release.command.side_effect=command
            with patch.object(C,'TARGET_COMMIT','f'*40),self.assertRaisesRegex(ValueError,code) as caught:
                C.migrate_database(Path('/synthetic/naver-'+'f'*40),release)
            self.assertEqual(caught.exception.failure_details['failed_operation'],'migration_apply')
            self.assertEqual(caught.exception.failure_details['failed_error_code'],code)


class CompletionApplyTests(unittest.TestCase):
    def scenario(self,failure=None):
        events=[];state={'schema':11};old=Path('/synthetic/naver-'+C.OLD_COMMIT);target=Path('/synthetic/naver-'+'f'*40)
        units=('engine.service','relay.service');tmpfile=Path('/synthetic/tmpfiles');oldfiles={tmpfile:b'x',Path('/synthetic/engine.service'):b'old-engine',Path('/synthetic/relay.service'):b'old-relay'}
        newfiles={p:(b'new-'+b if p!=tmpfile else b) for p,b in oldfiles.items()}
        release=Mock();release.ROOT=Path('/synthetic');release.write_new.side_effect=lambda *args,**kwargs:events.append(('receipt',str(args[0])))
        release.compose.side_effect=lambda path,name:['compose',path.name,name]
        def command(args,**kwargs):
            events.append(tuple(args))
            if args[:2]==['/usr/bin/systemctl','start'] and state['schema']!= (21 if any(e[:2]==('migrate','done') for e in events) and not any(e[:1]==('restore-db',) for e in events) else 11):raise ValueError('DB_START_ORDER')
            return b''
        release.command.side_effect=command
        life=Mock();life.UNITS=units;life.UNIT_DIR=Path('/synthetic');life.TMPFILES=tmpfile;life.TUNNEL='tunnel.service'
        life.unit_files.return_value=newfiles
        upgrade=Mock();upgrade.manifest.return_value=(target,{'source_commit':'f'*40,'images':{'engine':'new','relay':'new'}})
        upgrade.read_file.side_effect=lambda path,**kwargs:oldfiles[path]
        upgrade.replace_unit.side_effect=lambda *args:events.append(('replace-unit',str(args[0])))
        def stopped(*args):
            events.append(('stopped',args[-1]))
            if failure=='rollback-writer' and len([e for e in events if e[:1]==('migrate',)])>0:raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
        def snapshot(*args):events.append(('snapshot',));return (Path('/synthetic-snapshot'),'a'*64)
        def migration(*args):
            state['schema']=21;events.append(('migrate','done'))
            if failure in ('migration','rollback-writer'):raise ValueError('DB_ROWS_CHANGED')
            return {'ok':True,'schema':21,'preserved_rows':True}
        def restore(*args):
            events.append(('restore-db',))
            if failure=='restore':raise ValueError('DB_SNAPSHOT_CHANGED')
            state['schema']=11
        def verified(path,*args):
            events.append(('verify',path.name))
            if failure in ('verify','restore') and path==target:raise ValueError('PAGE_NOT_READY')
        def target_flags(*args,**kwargs):
            events.append(('config','target-network-none'))
            if failure=='preflight-execution':raise ValueError('EXECUTION_ENABLED')
            if failure=='preflight-malformed':raise ValueError('RUNTIME_CONFIG_PROOF')
            return {'inventory_enabled':True,'execution_enabled':False}
        def container_flags(path,*args,**kwargs):
            current=kwargs.get('target',False)
            events.append(('config','target-container' if current else 'old-container'))
            if current:self.assertEqual(kwargs['expected'],{'id':'c'*64})
            if failure==('target-execution' if current else 'old-execution'):raise ValueError('EXECUTION_ENABLED')
            if failure=='target-malformed' and current:raise ValueError('RUNTIME_CONFIG_PROOF')
            return {'inventory_enabled':not (failure==('target-drift' if current else 'old-drift')),'execution_enabled':False}
        def stopped_flags(*args):
            events.append(('config','stopped-target-container'))
            if failure=='stopped-execution':raise ValueError('EXECUTION_ENABLED')
            if failure=='stopped-malformed':raise ValueError('RUNTIME_CONFIG_PROOF')
            if failure=='stopped-identity':raise ValueError('RUNTIME_CONFIG_DRIFT')
            return {'inventory_enabled':failure!='stopped-drift','execution_enabled':False},{'id':'c'*64}
        def db(source,*args):events.append(('db-schema',source));self.assertEqual(state['schema'],11 if source==C.OLD_COMMIT else 21)
        def preflight(*args):
            events.append(('db-preflight',))
            if failure=='database-policy':raise ValueError('DB_IDENTITY')
            if failure=='database-space':raise ValueError('DB_SPACE')
        host=Mock();host.baseline.return_value=C.EXPECTED_BASELINE
        package={'release':{'baseline':C.EXPECTED_BASELINE},'operation_id':'a'*32}
        patches={'TARGET_COMMIT':'f'*40}
        with patch.multiple(C,**patches),patch.object(C.pwd,'getpwnam',return_value=SimpleNamespace(pw_gid=33)),patch.object(C,'require_pins'),patch.object(C,'validate_package',return_value=package['release']),\
            patch.object(C,'current_state',return_value=(old,{'images':{'engine':'old','relay':'old'}},oldfiles,None,None)),\
            patch.object(C,'compatible_source'),patch.object(C,'bootstrap_state',return_value=None),patch.object(C,'stopped_writer',side_effect=stopped),\
            patch.object(C,'db_snapshot',side_effect=snapshot),patch.object(C,'migrate_database',side_effect=migration),\
            patch.object(C,'verify_database_schema',side_effect=db),patch.object(C,'restore_db',side_effect=restore),patch.object(C,'verify_running',side_effect=verified),\
            patch.object(C,'target_runtime_flags',side_effect=target_flags),patch.object(C,'container_runtime_flags',side_effect=container_flags),\
            patch.object(C,'stopped_container_runtime_flags',side_effect=stopped_flags),patch.object(C,'database_preflight',side_effect=preflight):
            try:result=C.apply(package,host,release,life,upgrade)
            except Exception as error:result=error
        return result,events,state
    def test_success_stops_snapshot_migrates_verifies_before_target_start(self):
        result,events,state=self.scenario()
        self.assertTrue(result['ok']);self.assertEqual(state['schema'],21)
        self.assertTrue(result['database_snapshot_verified']);self.assertTrue(result['rollback_requires_matching_database'])
        self.assertFalse(result['collection_completion_verified']);self.assertFalse(result['source_warmup_performed'])
        self.assertTrue(result['inventory_enabled']);self.assertFalse(result['execution_enabled']);self.assertTrue(result['runtime_flags_verified'])
        self.assertLess(events.index(('config','target-network-none')),events.index(('/usr/bin/systemctl','stop','relay.service')))
        self.assertLess(events.index(('db-preflight',)),events.index(('/usr/bin/systemctl','stop','relay.service')))
        self.assertLess(events.index(('config','old-container')),events.index(('snapshot',)))
        self.assertLess(events.index(('compose','naver-'+'f'*40,'relay','up','--no-start','--no-build','--force-recreate')),events.index(('config','stopped-target-container')))
        self.assertLess(events.index(('config','stopped-target-container')),events.index(('/usr/bin/systemctl','start','engine.service')))
        self.assertLess(events.index(('/usr/bin/systemctl','start','engine.service')),events.index(('config','target-container')))
        self.assertLess(events.index(('snapshot',)),events.index(('migrate','done')))
        self.assertLess(events.index(('db-schema','f'*40)),events.index(('/usr/bin/systemctl','start','engine.service')))
        self.assertNotIn(('restore-db',),events)
    def test_enabled_malformed_or_drifted_preflight_refuses_before_any_stop_snapshot_or_recovery_write(self):
        for kind,code in (('preflight-execution','EXECUTION_ENABLED'),('preflight-malformed','RUNTIME_CONFIG_PROOF'),
                ('old-execution','EXECUTION_ENABLED'),('old-drift','RUNTIME_CONFIG_DRIFT')):
            with self.subTest(kind=kind):
                result,events,state=self.scenario(kind)
                self.assertEqual(str(result),code);self.assertEqual(state['schema'],11)
                self.assertFalse(any(e[:2]==('/usr/bin/systemctl','stop') or e[:1] in (('snapshot',),('receipt',),('migrate',),('replace-unit',)) for e in events))
    def test_database_policy_failure_refuses_before_stop_or_recovery_receipt(self):
        for reason,code in (('database-policy','DB_IDENTITY'),('database-space','DB_SPACE')):
            result,events,state=self.scenario(reason)
            self.assertEqual(str(result),code);self.assertEqual(state['schema'],11)
            self.assertIn(('db-preflight',),events)
            self.assertFalse(any(e[:2]==('/usr/bin/systemctl','stop') or e[:1] in (('snapshot',),('receipt',),('migrate',),('replace-unit',)) for e in events))
    def test_enabled_malformed_or_drifted_actual_target_uses_paired_database_rollback(self):
        for kind in ('target-execution','target-malformed','target-drift'):
            with self.subTest(kind=kind):
                result,events,state=self.scenario(kind)
                self.assertEqual(str(result),'CODE_FAILED_ROLLED_BACK_DB_PRESERVED');self.assertEqual(state['schema'],11)
                self.assertLess(events.index(('config','target-container')),events.index(('restore-db',)))
                oldstart=events.index(('/usr/bin/systemctl','start','engine.service'),events.index(('restore-db',)))
                self.assertLess(events.index(('db-schema',C.OLD_COMMIT)),oldstart)
    def test_env_drift_during_recreate_is_refused_before_target_start_and_rolls_back_matching_database(self):
        for kind in ('stopped-execution','stopped-malformed','stopped-drift','stopped-identity'):
            with self.subTest(kind=kind):
                result,events,state=self.scenario(kind)
                self.assertEqual(str(result),'CODE_FAILED_ROLLED_BACK_DB_PRESERVED');self.assertEqual(state['schema'],11)
                checked=events.index(('config','stopped-target-container'));restored=events.index(('restore-db',))
                self.assertLess(checked,restored)
                self.assertFalse(any(e[:2]==('/usr/bin/systemctl','start') for e in events[:restored]))
                self.assertNotIn(('config','target-container'),events)
                self.assertLess(restored,events.index(('/usr/bin/systemctl','start','engine.service')))
    def test_failure_restores_matching_snapshot_before_old_code_start(self):
        for kind in ('migration','verify'):
            result,events,state=self.scenario(kind)
            self.assertEqual(str(result),'CODE_FAILED_ROLLED_BACK_DB_PRESERVED');self.assertEqual(state['schema'],11)
            self.assertLess(events.index(('restore-db',)),events.index(('db-schema',C.OLD_COMMIT)))
            oldstart=events.index(('/usr/bin/systemctl','start','engine.service'),events.index(('restore-db',)))
            self.assertLess(events.index(('db-schema',C.OLD_COMMIT)),oldstart)
    def test_unproven_writer_or_restore_failure_stays_stopped(self):
        for kind in ('rollback-writer','restore'):
            result,events,state=self.scenario(kind)
            self.assertEqual(str(result),'CODE_ROLLBACK_FAILED')
            if kind=='rollback-writer':self.assertNotIn(('restore-db',),events)
            tail=events[events.index(('migrate','done'))+1:]
            if kind=='restore':tail=tail[tail.index(('restore-db',))+1:]
            self.assertFalse(any(e[:2]==('/usr/bin/systemctl','start') for e in tail))


class CompletionRollbackTests(unittest.TestCase):
    def scene(self,mutation=None,failure=None):
        events=[];old=Path('/synthetic/naver-'+C.OLD_COMMIT);target=Path('/synthetic/naver-'+'f'*40)
        original='a'*32;identity='b'*32;units=('engine.service','relay.service');tmpfile=Path('/synthetic/tmpfiles')
        oldfiles={tmpfile:b'x',Path('/synthetic/engine.service'):b'old-engine',Path('/synthetic/relay.service'):b'old-relay'}
        files={p:(b'new-'+b if p!=tmpfile else b) for p,b in oldfiles.items()}
        state={'schema':21,'files':dict(files)}
        oldreceipt={'package':{'baseline':C.EXPECTED_BASELINE,'source_tar_gz_sha256':C.OLD_SOURCE_SHA256},'images':{'engine':'old','relay':'old'}}
        receipt={'package':{'baseline':C.EXPECTED_BASELINE,'source_tar_gz_sha256':'e'*64},'images':{'engine':'new','relay':'new'}}
        saved={'source_commit':C.OLD_COMMIT,'target_commit':'f'*40,'images':oldreceipt['images'],'units':{str(p):b.decode() for p,b in oldfiles.items() if p!=tmpfile}}
        started={'ok':True,'stage':'internal_ready','source_commit':'f'*40,'previous_commit':C.OLD_COMMIT,'operation_id':original,'database_policy':'paired-snapshot','database_snapshot_verified':True,'database_schema':21}
        snap={'source_commit':C.OLD_COMMIT,'target_commit':'f'*40,'operation_id':original,'database_sha256':'d'*64,'schema':11,'snapshot_restore_verified':True}
        if mutation=='snapshot':snap['operation_id']='c'*32
        if mutation=='started':started['operation_id']='c'*32
        if mutation=='images':saved['images']={'engine':'other','relay':'old'}
        data={'code-upgrade-'+original+'.json':saved,'preview-start-'+'f'*40+'.json':started,'completion-snapshot-'+original+'.json':snap}
        release=Mock();release.ROOT=Path('/synthetic');release.unique=lambda pairs:dict(pairs)
        release.write_new.side_effect=lambda path,body:events.append(('receipt',path.name))
        release.compose.side_effect=lambda path,name:['compose',path.name,name]
        def command(args,**kwargs):
            events.append(tuple(args))
            if args[:2]==['/usr/bin/systemctl','start']:self.assertEqual(state['schema'],11)
            return b''
        release.command.side_effect=command
        life=Mock();life.UNITS=units;life.UNIT_DIR=Path('/synthetic');life.TMPFILES=tmpfile
        life.unit_files.side_effect=lambda path,*args:oldfiles if path==old else files
        life._state.return_value='active'
        upgrade=Mock();upgrade.manifest.side_effect=lambda rel,source,*args,**kwargs:(old,oldreceipt) if source==C.OLD_COMMIT else (target,receipt)
        upgrade.read_file.side_effect=lambda path,**kwargs:state['files'][path] if path in files else json.dumps(data[path.name]).encode()
        def replace(path,before,after,*args):state['files'][path]=after;events.append(('unit',path.name))
        upgrade.replace_unit.side_effect=replace
        def stopped(*args):
            events.append(('stopped',args[-1]))
            if failure=='writer':raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
        def restore(snapshot,op,*args):
            self.assertEqual(op,original);self.assertEqual(snapshot,(Path('/synthetic/receipts/completion-db-'+original+'.sqlite'),'d'*64))
            events.append(('restore-db',));state['schema']=11
            if failure=='restore':raise ValueError('DB_SNAPSHOT_CHANGED')
        def schema(source,*args):events.append(('schema',source));self.assertEqual(state['schema'],11 if source==C.OLD_COMMIT else 21)
        host=Mock();host.baseline.return_value=C.EXPECTED_BASELINE
        package={'release':{'baseline':C.EXPECTED_BASELINE},'operation_id':identity,'apply_operation_id':original}
        with patch.object(C,'require_pins'),patch.object(C,'TARGET_COMMIT','f'*40),patch.object(C,'TARGET_SOURCE_SHA256','e'*64),patch.object(C.os,'geteuid',return_value=0),patch.object(C.pwd,'getpwnam',return_value=SimpleNamespace(pw_gid=33)),\
            patch.object(C,'validate_package',return_value=package['release']),patch.object(C,'compatible_inverse_source'),patch.object(C,'bootstrap_state',return_value=None),patch.object(C,'stopped_writer',side_effect=stopped),\
            patch.object(C,'restore_db',side_effect=restore),patch.object(C,'verify_database_schema',side_effect=schema),patch.object(C,'verify_running',side_effect=lambda path,*args:events.append(('running',path.name))),patch.object(C,'probe',side_effect=AssertionError('BROKEN_TARGET_HTTP')):
            try:result=C.rollback(package,host,release,life,upgrade)
            except Exception as e:result=e
        return result,events
    def test_same_apply_snapshot_restored_before_old_code_starts_even_if_target_http_is_broken(self):
        result,events=self.scene();self.assertTrue(result['ok']);self.assertTrue(result['new_database_quarantined'])
        self.assertLess(events.index(('restore-db',)),events.index(('/usr/bin/systemctl','start','engine.service')))
        self.assertIn(('schema',C.OLD_COMMIT),events)
        self.assertNotIn(('running','naver-'+'f'*40),events)
    def test_other_apply_receipts_or_images_refuse_before_stop_or_db(self):
        for mutation in ('snapshot','started','images'):
            result,events=self.scene(mutation)
            self.assertIsInstance(result,ValueError);self.assertFalse(any(e[:1] in (('restore-db',),('/usr/bin/systemctl',)) for e in events))
    def test_unproven_writer_or_restore_failure_stays_stopped(self):
        for failure in ('writer','restore'):
            result,events=self.scene(failure=failure);self.assertEqual(str(result),'CODE_POST_ROLLBACK_FAILED')
            self.assertFalse(any(e[:2]==('/usr/bin/systemctl','start') for e in events))

if __name__=='__main__':unittest.main()
