"""Offline same-schema patch protocol and preserve-in-place lifecycle."""
import ast
import base64
import copy
import hashlib
import importlib.util
import json
import lzma
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

TOOLS = Path(__file__).parents[1] / 'tools'


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pinned():
    p=load('naver_claude_quality_patch');c=load('naver_preview_completion_release')
    p.TARGET_COMMIT='f'*40;p.TARGET_SOURCE_SHA256='e'*64
    p.TARGET_PROVIDER_ROW=(0o644,p.DADB_PROVIDER_ROW[1]+1,'a'*64)
    p.CI_PROOF=dict(source_commit=p.TARGET_COMMIT,tooling_head='d'*40,run_id='12345678901',receipt_sha256='b'*64)
    p.bind_base(c);return p,c


def package(p):
    return dict(operation='code-prepare', baseline=p.EXPECTED_BASELINE,
                source_commit=p.TARGET_COMMIT, source_tar_gz_sha256=p.TARGET_SOURCE_SHA256,
                ciphertext_sha256='d' * 64, run_id='12345678901')


class PatchPinsTests(unittest.TestCase):
    def test_pending_target_refuses_before_any_adapter_or_file_access(self):
        p = load('naver_claude_quality_patch')
        # Deliberately absent in this negative fixture, independent of release pins.
        p.TARGET_COMMIT = None
        for method in ('prepare', 'apply', 'rollback'):
            adapters = [Mock() for _ in range(4)]
            with self.subTest(method=method), self.assertRaisesRegex(ValueError, '^PATCH_NOT_PINNED$'):
                getattr(p, method)({}, *adapters)
            self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_static_workflow_pin_check_and_bound_runtime_check_are_distinct(self):
        p, _ = pinned()
        p.BASE = None
        p.require_pins()
        adapters = [Mock() for _ in range(4)]
        with self.assertRaisesRegex(ValueError, '^PATCH_NOT_PINNED$'):
            p.prepare(package(p), *adapters)
        self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_exact_provider_path_and_fixed_dadb_delta_are_closed(self):
        for kind in ('extra','missing','scope','store_hash','old_hash','asset','ci','same_target','baseline_delta'):
            p,_=pinned()
            if kind=='extra':p.TARGET_MANIFEST['naver_engine/foreign.py']=(0o644,1,'a'*64)
            if kind=='missing':p.TARGET_MANIFEST.pop('naver_engine/store.py')
            if kind=='scope':p.CODE_PATHS|={'naver_engine/web.py'}
            if kind=='store_hash':p.STORE_SHA256['target']='1'*64
            if kind=='old_hash':p.OLD_SOURCE_SHA256='1'*64
            if kind=='asset':p.REPORT_ASSETS['/naver/report-ui.js']=(1,'b'*64,'text/javascript; charset=utf-8')
            if kind=='ci':p.CI_PROOF['source_commit']='0'*40
            if kind=='same_target':p.TARGET_COMMIT=p.OLD_COMMIT
            if kind=='baseline_delta':p.DADB_DELTA['naver_engine/store.py']=(0o644,1,'a'*64)
            with self.subTest(kind=kind),self.assertRaises(ValueError):p.require_pins()

    def test_store_bytes_and_schema_are_unchanged_for_provider_only_transition(self):
        p,_=pinned();body=b"SCHEMA_VERSION=21\n_SCHEMA='x'\n_REVISION_COLUMNS={}\ndef _migrate(c):\n return 21\ndef work():\n return 1\n"
        p.STORE_SHA256={role:hashlib.sha256(body).hexdigest() for role in ('old','target')}
        self.assertIsNone(p.migration_contract(body,body))
        for changed in (body.replace(b'return 1',b'return 2'),body.replace(b"_SCHEMA='x'",b"_SCHEMA='y'"),body.replace(b'SCHEMA_VERSION=21',b'SCHEMA_VERSION=22')):
            with self.assertRaises(ValueError):p.migration_contract(body,changed)

    def test_forbidden_source_is_rejected_before_reading_or_hashing(self):
        p, _ = pinned()
        for name in ('naver_engine/store 2.py', 'HANDOVER.md', 'deploy/runtime.env', 'naver_engine/../secret', '/tmp/x'):
            self.assertFalse(p.safe_source_path(name))

    def test_original_completion_controller_and_dadb_manifest_are_immutable(self):
        p,c=pinned();self.assertEqual(c.OLD_SCHEMA,11);self.assertEqual(c.TARGET_SCHEMA,21)
        self.assertEqual(c.OLD_COMMIT,p.BASE_PREVIOUS_COMMIT);self.assertEqual(c.TARGET_COMMIT,p.HISTORICAL_TARGET)
        self.assertEqual(p.OLD_COMMIT,'dadb4e89bb28021db50f1c5bb3682a6c81398003')
        self.assertEqual(p.OLD_MANIFEST,{**c.TARGET_MANIFEST,**p.DADB_DELTA})
        self.assertEqual({k for k in p.OLD_MANIFEST if p.OLD_MANIFEST[k]!=c.TARGET_MANIFEST[k]},set(p.DADB_DELTA))
        self.assertEqual(p.STORE_SHA256['old'],p.STORE_SHA256['target'])


class BaselineProofTests(unittest.TestCase):
    def fixture(self):
        p,c=pinned();secret=Path('/synthetic/secrets');files={str(secret/'runtime.env'):'a'*64,str(secret/'other'):'b'*64}
        r=SimpleNamespace(ROOT=Path('/synthetic/release'),unique=lambda pairs:dict(pairs),SECRET_ROOT=secret,SECRET_OWNERS={'runtime.env':(0,0),'other':(0,0)})
        def receipt(commit,source,run):
            return dict(source_commit=commit,package=dict(source_tar_gz_sha256=source,run_id=run,baseline=p.EXPECTED_BASELINE),runtime_environment_preserved=True,config_operation_id=p.APPROVED_CONFIG_OPERATION_ID,runtime_flags_verified=True,inventory_enabled=True,execution_enabled=False,files=dict(files))
        h=receipt(p.HISTORICAL_TARGET,c.TARGET_SOURCE_SHA256,p.HISTORICAL_PREPARE_RUN)
        d=receipt(p.OLD_COMMIT,p.OLD_SOURCE_SHA256,p.BASE_PREPARE_RUN)
        hs=dict(ok=True,stage='internal_ready',source_commit=p.HISTORICAL_TARGET,previous_commit=p.BASE_PREVIOUS_COMMIT,operation_id=p.HISTORICAL_APPLY_OPERATION,database_policy='paired-snapshot',database_schema=21,source_status=dict(ok=True,schema=21,old_schema=11,old_tables=36,old_rows=389163,preserved_rows=True,migration_repeatable=True,network_calls=0,randomized_tables=sorted(c.RANDOMIZED_TABLES),randomized_tables_empty=True),database_opened_by_controller=True,database_snapshot_verified=True,runtime_flags_verified=True,execution_enabled=False)
        ds=dict(ok=True,stage='internal_ready',source_commit=p.OLD_COMMIT,previous_commit=p.HISTORICAL_TARGET,operation_id=p.BASE_APPLY_OPERATION,database_policy='preserve-in-place',database_schema=21,database_opened_by_controller=False,database_snapshot_verified=False,source_warmup_performed=False,rollback_requires_matching_database=False,runtime_flags_verified=True,execution_enabled=False,saved_export_companion_preserved=True)
        receipts={p.HISTORICAL_TARGET:h,p.OLD_COMMIT:d,c.OLD_COMMIT:{'source_commit':c.OLD_COMMIT}}
        starts={p.HISTORICAL_TARGET:hs,p.OLD_COMMIT:ds}
        def read(path,**_):
            commit=Path(path).name.removeprefix('preview-start-').removesuffix('.json');return json.dumps(starts[commit]).encode()
        u=SimpleNamespace(manifest=Mock(side_effect=lambda _r,commit,**_:(Path('/synthetic/naver-'+commit),receipts[commit])),read_file=Mock(side_effect=read))
        return p,c,r,u,d,ds,h,hs

    def test_successful_dadb_code_only_chain_requires_original_paired_baseline(self):
        p,_,r,u,d,_,_,_=self.fixture();self.assertEqual(p.base_success(r,u)[1],d)
        self.assertEqual([call.args[0].name for call in u.read_file.call_args_list],['preview-start-'+p.HISTORICAL_TARGET+'.json','preview-start-'+p.OLD_COMMIT+'.json'])

    def test_wrong_operation_schema_policy_or_flags_cannot_be_baseline(self):
        for key,value in [('operation_id','a'*32),('database_schema',11),('database_policy','paired-snapshot'),('database_opened_by_controller',True),('database_snapshot_verified',True),('execution_enabled',True),('source_warmup_performed',True),('ok',False),('saved_export_companion_preserved',False)]:
            p,_,r,u,_,started,_,_=self.fixture();started[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'^PATCH_BASELINE$'):p.base_success(r,u)
        p,_,r,u,d,_,_,hs=self.fixture();d['package']['run_id']='38188877354'
        with self.assertRaisesRegex(ValueError,'^PATCH_BASELINE$'):p.base_success(r,u)
        d['package']['run_id']=p.BASE_PREPARE_RUN;hs['source_status']['preserved_rows']=False
        with self.assertRaisesRegex(ValueError,'^PATCH_BASELINE$'):p.base_success(r,u)

    def test_current_secret_hashes_must_match_historical_preserved_environment(self):
        for kind in ('different','missing'):
            p,_,r,u,d,_,_,_=self.fixture()
            if kind=='different':d['files'][str(r.SECRET_ROOT/'runtime.env')]='0'*64
            else:d['files'].pop(str(r.SECRET_ROOT/'runtime.env'))
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'^PATCH_CONFIG$'):p.base_success(r,u)

    def test_historical_config_chain_and_new_code_only_bridge_are_both_required(self):
        p,c,r,u,d,_,h,_=self.fixture()
        files=[dict(path=str(r.SECRET_ROOT/name),content=name) for name in r.SECRET_OWNERS]
        for receipt in (d,h):receipt['files']={v['path']:hashlib.sha256(v['content'].encode()).hexdigest() for v in files}
        historical=u.manifest(r,c.OLD_COMMIT,started=True)[1]
        with patch.object(c,'preserve_approved_config',return_value=(files,('historical-proof',))) as original:
            result,proof=p.preserve_approved_config(files,p.APPROVED_CONFIG_OPERATION_ID,d,r,u)
            self.assertEqual(result,files);self.assertEqual(proof[0],('historical-proof',));self.assertIs(original.call_args.args[2],historical)
            d['files'][files[0]['path']]='0'*64
            with self.assertRaisesRegex(ValueError,'^PATCH_CONFIG$'):p.preserve_approved_config(files,p.APPROVED_CONFIG_OPERATION_ID,d,r,u)

    def test_failure_projection_never_returns_untrusted_text_or_overrides_first_failure(self):
        p,_=pinned();p.STAGE='code_rollback';e=RuntimeError('PRIVATE /synthetic/runtime.env')
        e.failure_details=dict(failed_stage='code_start',failed_error_code='RUNTIME_CONFIG_DRIFT',failed_error_kind='ValueError',private='secret',rollback_stage=['untrusted'])
        result=p.failure_report(e);self.assertEqual(result['error_code'],'UNRECOGNIZED');self.assertEqual(result['failed_stage'],'code_start')
        self.assertNotIn('secret',json.dumps(result));self.assertNotIn('runtime.env',json.dumps(result))


class LifecycleFixture:
    def __init__(self, test, failure=None):
        self.test=test; self.p,self.c=pinned(); p=self.p
        self.temp=tempfile.TemporaryDirectory(); test.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve(); (self.root/'receipts').mkdir()
        self.db=self.root/'engine.db'; self.db.write_bytes(b'unchanged operating data')
        self.db_before=self.db.read_bytes(); self.commands=[]; self.export_checks=0
        self.failure=failure; self.failed=False
        self.units=('engine.service','relay.service'); self.state={u:'active' for u in self.units}
        self.version={u:p.OLD_COMMIT for u in self.units}
        self.old=self.root/('naver-'+p.OLD_COMMIT); self.new=self.root/('naver-'+p.TARGET_COMMIT)
        self.unitdir=self.root/'units'; self.unitdir.mkdir(); self.tmp=self.root/'tmpfiles'
        self.oldfiles={self.unitdir/u:('old-'+u).encode() for u in self.units}; self.oldfiles[self.tmp]=b'fixed'
        self.newfiles={self.unitdir/u:('new-'+u).encode() for u in self.units}; self.newfiles[self.tmp]=b'fixed'
        self.files=dict(self.oldfiles)
        self.oldreceipt=dict(source_commit=p.OLD_COMMIT, inventory_enabled=True,execution_enabled=False,
                             images={'engine':'sha256:'+'1'*64,'relay':'sha256:'+'2'*64},
                             package=dict(baseline=p.EXPECTED_BASELINE,source_tar_gz_sha256=p.OLD_SOURCE_SHA256))
        self.newreceipt=dict(source_commit=p.TARGET_COMMIT,inventory_enabled=True,execution_enabled=False,
                             images={'engine':'sha256:'+'3'*64,'relay':'sha256:'+'4'*64},
                             package={k:v for k,v in package(p).items() if k!='operation'})
        self.r=SimpleNamespace(ROOT=self.root,command=self.command,compose=lambda path,name:['compose',str(path),name],
                               write_new=self.write_new,trusted_dir=Mock(),unique=lambda pairs:dict(pairs),
                               verify_exports=self.verify_exports,validate_package=Mock())
        self.u=SimpleNamespace(manifest=self.manifest,read_file=self.read_file,replace_unit=self.replace_unit)
        self.l=SimpleNamespace(UNITS=self.units,TUNNEL='tunnel.service',TMPFILES=self.tmp,UNIT_DIR=self.unitdir,
                               unit_files=lambda path,*_:self.oldfiles if path==self.old else self.newfiles,
                               _snapshot=lambda *_:{},_state=self.unit_state)
        self.h=SimpleNamespace(baseline=lambda:p.EXPECTED_BASELINE)
        self.patches=[patch.object(p,'current_state',return_value=(self.old,self.oldreceipt,self.oldfiles,{},None)),
                      patch.object(p,'base_success',return_value=(self.old,self.oldreceipt,b'exact-original-start')),
                      patch.object(p,'bootstrap_state',return_value=None),patch.object(p,'compatible_source',side_effect=self.compatible),
                      patch.object(p,'container_runtime_flags',return_value={'inventory_enabled':True,'execution_enabled':False}),
                      patch.object(p,'stopped_container_runtime_flags',side_effect=self.stopped_flags),
                      patch.object(p,'stopped_writer',side_effect=self.stopped),patch.object(p,'probe',side_effect=self.probe),
                      patch.object(p.pwd,'getpwnam',return_value=SimpleNamespace(pw_gid=33)),patch.object(p.os,'geteuid',return_value=0)]
        for item in self.patches: item.start(); test.addCleanup(item.stop)

    def write_new(self,path,body):
        if path.exists():raise ValueError('existing')
        path.write_bytes(body)
    def read_file(self,path,**_):return self.files[path] if path in self.files else path.read_bytes()
    def manifest(self,_release,commit,*_,**__):return (self.old,self.oldreceipt) if commit==self.p.OLD_COMMIT else (self.new,self.newreceipt)
    def replace_unit(self,path,before,after,*_):
        if self.files[path]!=before:raise ValueError('CODE_ROLLBACK_UNIT')
        self.files[path]=after
    def unit_state(self,_r,unit,field):
        if field=='UnitFileState':return 'enabled'
        return self.state.get(unit,'active')
    def verify_exports(self):self.export_checks+=1
    def compatible(self,*_):
        if self.failure=='scope':raise ValueError('PATCH_SCOPE')
    def stopped(self,_r,_l,_path,_images,unit):
        if self.state[unit]!='inactive' or self.failure=='stop_unproved':raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
    def stopped_flags(self,path,*_):
        if self.failure=='target_execution' and path==self.new:raise ValueError('EXECUTION_ENABLED')
        if self.failure=='rollback_execution' and path==self.old:raise ValueError('EXECUTION_ENABLED')
        return {'inventory_enabled':True,'execution_enabled':False},{'source':path.name.removeprefix('naver-')}
    def probe(self,*_):
        if self.failure in ('probe','rollback_execution') and not self.failed:self.failed=True;raise ValueError('PAGE_NOT_READY')
    def command(self,args,**_):
        self.commands.append(args)
        if args[:2]==['/usr/bin/systemctl','stop']:self.state[args[2]]='inactive'
        elif args[:2]==['/usr/bin/systemctl','start']:
            if self.failure=='start' and not self.failed:self.failed=True;raise ValueError('COMMAND_FAILED')
            self.state[args[2]]='active'
        elif args[0]=='compose':
            if self.failure=='recreate' and not self.failed:self.failed=True;raise ValueError('COMMAND_FAILED')
            self.version[args[2]+'.service']=Path(args[1]).name.removeprefix('naver-')
        return b''
    def apply(self):return self.p.apply(dict(release=package(self.p),operation_id='a'*32),self.h,self.r,self.l,self.u)
    def assert_preserved(self):
        self.test.assertEqual(self.db.read_bytes(),self.db_before)
        self.test.assertFalse(any('exec' in cmd or 'run' in cmd or 'backup' in cmd for cmd in self.commands))
        self.test.assertFalse(any('export' in str(path) or 'snapshot' in str(path) for path in self.root.rglob('*')))


class LifecycleTests(unittest.TestCase):
    def test_apply_and_explicit_rollback_preserve_live_database_and_exports(self):
        f=LifecycleFixture(self)
        with patch.object(sqlite3,'connect',side_effect=AssertionError('DB forbidden')):
            result=f.apply()
            self.assertTrue(result['ok']);self.assertFalse(result['database_opened_by_controller'])
            self.assertEqual(result['database_policy'],'preserve-in-place')
            self.assertEqual(set(f.version.values()),{f.p.TARGET_COMMIT})
            restored=f.p.rollback(dict(release=package(f.p),apply_operation_id='a'*32,operation_id='b'*32),f.h,f.r,f.l,f.u)
        self.assertTrue(restored['ok']);self.assertFalse(restored['execution_enabled'])
        self.assertEqual(set(f.version.values()),{f.p.OLD_COMMIT});self.assertGreater(f.export_checks,2)
        f.assert_preserved()

    def test_failures_after_stop_restore_only_old_code_and_preserve_data(self):
        for failure in ('start','recreate','probe','target_execution'):
            f=LifecycleFixture(self,failure)
            with self.subTest(failure=failure),patch.object(sqlite3,'connect',side_effect=AssertionError('DB forbidden')):
                with self.assertRaisesRegex(RuntimeError,'^CODE_ONLY_FAILED_ROLLED_BACK$'):f.apply()
                self.assertEqual(set(f.version.values()),{f.p.OLD_COMMIT})
                self.assertEqual(set(f.state.values()),{'active'});f.assert_preserved()

    def test_unverified_writer_or_execution_on_rollback_never_restarts_any_service(self):
        for failure in ('stop_unproved','rollback_execution'):
            f=LifecycleFixture(self,failure)
            with self.subTest(failure=failure),self.assertRaisesRegex(RuntimeError,'^CODE_ROLLBACK_FAILED$'):f.apply()
            self.assertEqual(set(f.state.values()),{'inactive'});f.assert_preserved()

    def test_scope_and_replayed_apply_are_rejected_before_service_stop(self):
        f=LifecycleFixture(self,'scope')
        with self.assertRaisesRegex(ValueError,'^PATCH_SCOPE$'):f.apply()
        self.assertEqual(f.commands,[])
        f.failure=None;f.apply();before=list(f.commands)
        with self.assertRaisesRegex(ValueError,'^CODE_ALREADY_ATTEMPTED$'):f.apply()
        self.assertEqual(f.commands,before);f.assert_preserved()

    def test_wrong_explicit_rollback_receipt_never_stops_running_patch(self):
        f=LifecycleFixture(self);f.apply();before=list(f.commands)
        with self.assertRaises(FileNotFoundError):
            f.p.rollback(dict(release=package(f.p),apply_operation_id='c'*32,operation_id='b'*32),f.h,f.r,f.l,f.u)
        self.assertEqual(f.commands,before);self.assertEqual(set(f.state.values()),{'active'})

    def test_prestart_execution_drift_is_detected_before_target_service_start(self):
        f=LifecycleFixture(self,'target_execution')
        with self.assertRaisesRegex(RuntimeError,'^CODE_ONLY_FAILED_ROLLED_BACK$'):f.apply()
        starts=[cmd for cmd in f.commands if cmd[:2]==['/usr/bin/systemctl','start']]
        # Only the two original services are restarted after rollback.
        self.assertEqual(len(starts),2);self.assertEqual(set(f.version.values()),{f.p.OLD_COMMIT})
        f.assert_preserved()

    def test_target_identity_is_bound_across_start_and_final_runtime_check(self):
        f=LifecycleFixture(self)
        with patch.object(f.p,'container_runtime_flags',return_value={'inventory_enabled':True,'execution_enabled':False}) as flags:
            f.apply()
        self.assertEqual(flags.call_args.kwargs,dict(target=True,expected={'source':f.p.TARGET_COMMIT}))

    def test_explicit_rollback_execution_drift_never_restarts_old_code(self):
        f=LifecycleFixture(self);f.apply();f.failure='rollback_execution';f.failed=True;before=len(f.commands)
        with self.assertRaisesRegex(RuntimeError,'^CODE_POST_ROLLBACK_FAILED$'):
            f.p.rollback(dict(release=package(f.p),apply_operation_id='a'*32,operation_id='b'*32),f.h,f.r,f.l,f.u)
        self.assertFalse(any(cmd[:2]==['/usr/bin/systemctl','start'] for cmd in f.commands[before:]))
        self.assertEqual(set(f.state.values()),{'inactive'});f.assert_preserved()

    def test_broken_target_http_does_not_prevent_exact_identity_code_rollback(self):
        f=LifecycleFixture(self);f.apply()
        def probe(_release,source,_upgrade):
            if source==f.p.TARGET_COMMIT:raise ValueError('PAGE_NOT_READY')
        with patch.object(f.p,'probe',side_effect=probe):
            result=f.p.rollback(dict(release=package(f.p),apply_operation_id='a'*32,operation_id='b'*32),f.h,f.r,f.l,f.u)
        self.assertTrue(result['ok']);self.assertEqual(set(f.version.values()),{f.p.OLD_COMMIT})

    def test_prepare_validates_config_and_builds_without_stopping_services(self):
        f=LifecycleFixture(self);p=f.p
        (f.root/'incoming'/package(p)['run_id']).mkdir(parents=True)
        secret=f.root/'secrets';secret.mkdir();secret_path=secret/'runtime.env';secret_path.write_bytes(b'preserved')
        key=f.root/'envelope'/'private.pem';key.parent.mkdir();key.write_bytes(b'synthetic')
        f.u.ENVELOPE_KEY=key
        f.r.SECRET_ROOT=secret;f.r.SECRET_OWNERS={'runtime.env':(0,0)}
        f.r.trusted_private_file=Mock();f.r.received_ciphertext=Mock(return_value=b'cipher')
        f.r.decode_payload=Mock(return_value=(b'source',[dict(path=str(secret_path),uid=0,gid=0,content='preserved')]))
        f.r.source_members=Mock(return_value=(Mock(),[]));f.r.sha=lambda raw:hashlib.sha256(raw).hexdigest()
        def extract(_raw,destination):
            destination.mkdir(parents=True)
            for name in ('compose.naver-engine.yml','compose.naver-relay.yml','deploy/naver-engine-backup.override.yml'):
                path=destination/name;path.parent.mkdir(exist_ok=True);path.write_bytes(b'fixed')
        f.r.extract_source=extract
        def read(path,**_):
            path=Path(path)
            if path.name.startswith('preview-') and path.parent==f.old:return b'image: '+p.OLD_COMMIT.encode()
            return f.read_file(path)
        f.u.read_file=read
        def command(args,**_):
            f.commands.append(args)
            if args[:3]==['docker','image','inspect']:return json.dumps('sha256:'+'3'*64).encode()
            return b'plain'
        f.r.command=command
        with patch.object(p,'preserve_approved_config',side_effect=lambda files,*_:(files,('proof',))), \
             patch.object(p,'target_runtime_flags',return_value={'inventory_enabled':True,'execution_enabled':False}), \
             patch.object(sqlite3,'connect',side_effect=AssertionError('DB forbidden')):
            result=p.prepare(package(p),f.h,f.r,f.l,f.u,approved_config_operation_id=p.APPROVED_CONFIG_OPERATION_ID)
        self.assertFalse(result['services_started']);self.assertFalse(result['database_opened_by_controller'])
        self.assertEqual(sum(cmd[:2]==['docker','build'] for cmd in f.commands),2)
        self.assertFalse(any(cmd[:2] in (['/usr/bin/systemctl','stop'],['/usr/bin/systemctl','start']) for cmd in f.commands))
        self.assertEqual(secret_path.read_bytes(),b'preserved');f.assert_preserved()


class ActualFlagHelpersTests(unittest.TestCase):
    def test_exact_stopped_container_metadata_precedes_private_environment_projection(self):
        p,_=pinned();identity='a'*64
        receipt=dict(source_commit=p.TARGET_COMMIT,images={'engine':'sha256:'+'b'*64})
        row=dict(id=identity,image=receipt['images']['engine'],running=False,restarting=False,pid=0,
                 source=p.TARGET_COMMIT,project='naver-engine',service='naver-engine')
        calls=[]
        def command(args,**_):
            calls.append(args)
            if args[0]=='compose':return (identity+'\n').encode()
            if '.Config.Env' in args[3]:return json.dumps(['PRIVATE=never-published','NAVER_ENGINE_INVENTORY_ENABLED=true','NAVER_ENGINE_EXECUTION_ENABLED=false']).encode()
            return json.dumps(row).encode()
        r=SimpleNamespace(compose=lambda *_:['compose'],command=command)
        l=SimpleNamespace(UNITS=('engine','relay'),_state=lambda _r,_u,f:{'ActiveState':'inactive','SubState':'dead','MainPID':'0'}[f])
        flags,before=p.stopped_container_runtime_flags(Path('/synthetic/naver-'+p.TARGET_COMMIT),receipt,r,l)
        self.assertEqual(flags,{'inventory_enabled':True,'execution_enabled':False});self.assertEqual(before,row)
        self.assertEqual(len(calls),5)
        row['running']=True
        with self.assertRaisesRegex(ValueError,'^RUNTIME_CONFIG_DRIFT$'):
            p.stopped_container_runtime_flags(Path('/synthetic/naver-'+p.TARGET_COMMIT),receipt,r,l)

    def test_execution_on_and_duplicate_environment_flags_are_closed_failures(self):
        p,_=pinned()
        for values in (['NAVER_ENGINE_EXECUTION_ENABLED=true'],['NAVER_ENGINE_EXECUTION_ENABLED=false']*2):
            with self.assertRaises(ValueError):p.container_environment_flags(json.dumps(values).encode())
        self.assertFalse(p.container_environment_flags(b'["PRIVATE=hidden"]')['execution_enabled'])


class CodecTests(unittest.TestCase):
    def fixture(self):
        t=load('naver_claude_quality_transport')
        sources={name:'value='+repr(name)+'\n' for name in t.SOURCE_FILES}
        t.SOURCE_SHA256=t.COMPACT_SHA256={name:hashlib.sha256(value.encode()).hexdigest() for name,value in sources.items()}
        value=dict(version=1,operation='preview-claude-quality-patch-apply',package={},sources=sources)
        return t,value

    def test_pending_transport_refuses_before_any_source_read(self):
        t=load('naver_claude_quality_transport')
        # This negative fixture must remain pending after real pins are registered.
        with patch.object(t,'SOURCE_SHA256',None), patch.object(Path,'read_bytes',side_effect=AssertionError('read forbidden')):
            with self.assertRaisesRegex(ValueError,'^PATCH_NOT_PINNED$'):t.bundle('preview-claude-quality-patch-apply',{},TOOLS)

    def test_codec_roundtrip_bounds_and_closed_source_catalog(self):
        t,v=self.fixture();wire=t.encode(v);self.assertEqual(t.decode(wire),v)
        self.assertEqual((t.MAX_JSON,t.MAX_WIRE,t.MAX_SOURCE),(393216,98304,160000))
        for mutate in ('source','foreign','operation','boolean_version'):
            changed=copy.deepcopy(v)
            if mutate=='source':changed['sources']['patch']+='private'
            if mutate=='foreign':changed['sources']['foreign']='x'
            if mutate=='operation':changed['operation']='preview-completion-apply'
            if mutate=='boolean_version':changed['version']=True
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):t.encode(changed)

    def test_truncated_trailing_duplicate_and_oversized_wire_reject(self):
        t,v=self.fixture();wire=t.encode(v)
        raw=json.dumps(v).replace('"version": 1','"version": 1, "version": 1').encode()
        duplicate=t.PREFIX+base64.b64encode(lzma.compress(raw)).decode()
        for invalid in (wire[:-5],wire+'AAAA',duplicate,wire+'A'*t.MAX_WIRE):
            with self.assertRaises(ValueError):t.decode(invalid)

    def test_export_proxy_preserves_both_engine_mounts_and_never_reinstalls(self):
        t,_=self.fixture();p,_=pinned();h=SimpleNamespace(COMPANION='saved.yml',_prepared=Mock(return_value=(None,Path('/synthetic/staging'),None)),verify=Mock(return_value=True))
        binding=SimpleNamespace(h=h,receipt={'bound':True},command=Mock(),operation=lambda callback:callback(),install=Mock(),rollback=Mock())
        r=SimpleNamespace(compose=lambda path,name:['compose',str(path),name])
        proxy=t.ExportProxy(r,binding,p)
        for commit in (p.OLD_COMMIT,p.TARGET_COMMIT):
            self.assertEqual(proxy.compose(Path('/synthetic/naver-'+commit),'engine')[-2:],['-f','/synthetic/staging/saved.yml'])
        self.assertNotIn('-f',proxy.compose(Path('/synthetic/naver-'+'0'*40),'engine'))
        self.assertNotIn('-f',proxy.compose(Path('/synthetic/naver-'+p.TARGET_COMMIT),'relay'))
        proxy.verify_exports();binding.install.assert_not_called();binding.rollback.assert_not_called()

    def test_no_migration_snapshot_export_mutation_or_legacy_dispatch_symbols(self):
        p_tree=ast.parse((TOOLS/'naver_claude_quality_patch.py').read_text())
        t_tree=ast.parse((TOOLS/'naver_claude_quality_transport.py').read_text())
        forbidden={'connect','db_snapshot','restore_db','migrate_database','warm_sources','install','cleanup','rollback'}
        for tree in (p_tree,t_tree):
            calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
            self.assertFalse([n.func.attr for n in calls if n.func.attr in forbidden])
        self.assertNotIn('import naver_completion_transport',ast.unparse(t_tree))

    def test_execute_transports_first_failure_across_pristine_reporter_module(self):
        t,v=self.fixture();p,_=pinned();r=Mock();r.unique=lambda pairs:dict(pairs)
        base_receipt={'package':{'run_id':p.BASE_PREPARE_RUN}}
        historical_receipt={'package':{'run_id':p.HISTORICAL_PREPARE_RUN,'source_commit':p.HISTORICAL_TARGET}}
        binding=Mock();e=SimpleNamespace(Binding=Mock(return_value=binding))
        modules=dict(patch=p,release=r,host=SimpleNamespace(NativeHost=Mock(return_value=Mock())),
                     controller=Mock(),exports_binding=e,exports_helper=Mock(),lifecycle=Mock(),upgrade=Mock())
        error=RuntimeError('CODE_ONLY_FAILED_ROLLED_BACK')
        error.failure_details={'failed_stage':'code_start','failed_error_code':'RUNTIME_CONFIG_DRIFT','failed_error_kind':'ValueError'}
        def fail(*_):p.STAGE='code_rollback';raise error
        v['package']={'release':package(p),'operation_id':'a'*32}
        with patch.object(t,'modules',return_value=modules),patch.object(p,'base_success',return_value=(Path('/old'),base_receipt,b'proof')),patch.object(p,'historical_success',return_value=(Path('/historical'),historical_receipt,b'historical-proof')),patch.object(p,'apply',side_effect=fail):
            with self.assertRaises(RuntimeError):t.execute(v)
        reporter=load('naver_claude_quality_patch');report=reporter.failure_report(error)
        self.assertEqual(report['failed_stage'],'code_start')
        self.assertEqual(report['failed_error_code'],'RUNTIME_CONFIG_DRIFT')
        binding.install.assert_not_called();binding.rollback.assert_not_called()
        binding.load.assert_called_once_with(dict(historical_receipt['package'],operation='code-prepare'))


class ActualPinnedBundleTests(unittest.TestCase):
    def test_ten_source_candidate_pressure_and_loader_with_synthetic_ci_only(self):
        import sys,types
        psource=(TOOLS/'naver_claude_quality_patch.py').read_text();tree=ast.parse(psource);lines=psource.splitlines(keepends=True)
        ci=dict(source_commit='faa0df6225aa5fff5c4e4884245a4884c0b5f77a',tooling_head='d'*40,run_id='9'*20,receipt_sha256='b'*64)
        node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='CI_PROOF' for x in n.targets))
        lines[node.lineno-1:node.end_lineno]=['CI_PROOF = '+repr(ci)+'\n'];psource=''.join(lines)
        p=SimpleNamespace();exec(psource,p.__dict__);t=load('naver_claude_quality_transport')
        raw={name:(psource if name=='patch' else (TOOLS/filename).read_text()) for name,filename in t.SOURCE_FILES.items()}
        t.SOURCE_SHA256={k:hashlib.sha256(v.encode()).hexdigest() for k,v in raw.items()}
        t.COMPACT_SHA256={k:hashlib.sha256((v if k in ('exports_helper','product_exporter','market_exporter') else t.compact(v)).encode()).hexdigest() for k,v in raw.items()}
        transport_source=(TOOLS/'naver_claude_quality_transport.py').read_text();lines=transport_source.splitlines(keepends=True)
        for n in reversed(ast.parse(transport_source).body):
            if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('SOURCE_SHA256','COMPACT_SHA256'):
                name=n.targets[0].id;lines[n.lineno-1:n.end_lineno]=[name+' = '+repr(getattr(t,name))+'\n']
        transport_b64=base64.b64encode(''.join(lines).encode()).decode();self.assertLessEqual(len(transport_b64),32768)
        workflow,pressure=quality_pressure()
        release=dict(source_commit=p.TARGET_COMMIT,source_tar_gz_sha256=p.TARGET_SOURCE_SHA256,ciphertext_sha256='a'*64,baseline=p.EXPECTED_BASELINE,run_id=ci['run_id'],operation='code-prepare')
        real_read=Path.read_bytes
        def read(path):return psource.encode() if path==TOOLS/'naver_claude_quality_patch.py' else real_read(path)
        measured={}
        with patch.dict(sys.modules,{'naver_claude_quality_patch':p}),patch.object(Path,'read_bytes',read):
            for operation,method in t.FUNCTIONS.items():
                package=release if method=='prepare' else dict(release=release,operation_id='b'*32)
                if method=='rollback':package['apply_operation_id']='c'*32
                packet=t.bundle(operation,package,TOOLS);wire=t.encode(packet);decoded=t.decode(wire);self.assertEqual(decoded,packet)
                modules=t.modules(decoded);approved=modules['patch'];approved.require_bound_pins()
                self.assertEqual(approved.OLD_COMMIT,'dadb4e89bb28021db50f1c5bb3682a6c81398003');self.assertEqual(approved.CODE_PATHS,frozenset({'naver_runtime/claude_provider.py'}))
                self.assertEqual(approved.STORE_SHA256['old'],approved.STORE_SHA256['target'])
                measured[method]=dict(raw_bytes=len(json.dumps(packet,separators=(',',':')).encode()),wire_bytes=len(wire),ssh_bytes=pressure(wire,transport_b64,workflow))
        print(json.dumps({'claude_quality_pressure_fixture':True,'synthetic_ci_placeholder':True,'actual_credentials':False,'source_commit':p.TARGET_COMMIT,'operations':measured},sort_keys=True))


def quality_section(text,name):
    lines=text.splitlines(keepends=True);start=lines.index('  '+name+':\n')
    end=next((i for i in range(start+1,len(lines)) if lines[i].startswith('  ') and not lines[i].startswith('   ') and lines[i].strip().endswith(':')),len(lines))
    return ''.join(lines[start:end])


def quality_pressure():
    workflow=(TOOLS.parents[1]/'.github/workflows/debug-rank.yml').read_text();part=quality_section(workflow,'claude-quality-patch')
    first=part.index('          def quality_ssh_scripts(');last=part.index('          P.require_pins()',first)
    source=''.join(line[10:] if line.startswith('          ') else line for line in part[first:last].splitlines(keepends=True));scope={};exec(compile(ast.parse(source),'<actual-quality-workflow-pressure>','exec'),scope)
    return workflow,scope['require_quality_ssh_pressure']


class WorkflowTests(unittest.TestCase):
    def _actual_transport_bootstrap_prefixes(self):
        import re
        text,_=quality_pressure();part=quality_section(text,'claude-quality-patch')
        scripts=re.findall(r"(?ms)^            /usr/bin/python3 -I -B - <<'PYCODE'\n(.*?)^            PYCODE$",part)
        self.assertEqual(len(scripts),2)
        prefixes=[]
        for source in scripts:
            source=''.join(line[12:] if line.startswith('            ') else line for line in source.splitlines(keepends=True))
            tree=ast.parse(source);attempt=next(node for node in tree.body if isinstance(node,ast.Try))
            stop=next(i for i,node in enumerate(attempt.body) if isinstance(node,ast.Expr)
                      and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name)
                      and node.value.func.id=='exec')+1
            # Run the actual imports, bound decoding and digest guard, then the
            # first exec only. Nothing after transport loading may reach a host.
            prefix=ast.Module(body=tree.body[:tree.body.index(attempt)]+attempt.body[:stop],type_ignores=[])
            prefixes.append(compile(ast.fix_missing_locations(prefix),'<actual-quality-ssh-bootstrap>','exec'))
        return prefixes

    def test_both_actual_ssh_bootstraps_reject_tampered_transport_before_exec(self):
        import builtins,os
        original_exec=builtins.exec;raw=(TOOLS/'naver_claude_quality_transport.py').read_bytes()+b'\n# synthetic tamper\n'
        env={'CLAUDE_QUALITY_PATCH_B64':'synthetic-wire','CLAUDE_QUALITY_PATCH_TRANSPORT_B64':base64.b64encode(raw).decode()}
        for index,prefix in enumerate(self._actual_transport_bootstrap_prefixes()):
            with self.subTest(bootstrap=index),patch.object(os,'environ',dict(env)),patch.object(builtins,'exec') as execute:
                with self.assertRaisesRegex(ValueError,'^COMPLETION_TRANSPORT_SOURCE$'):original_exec(prefix,{})
                execute.assert_not_called()

    def test_both_actual_ssh_bootstraps_reach_exec_only_with_exact_transport_bytes(self):
        import builtins,os
        original_exec=builtins.exec;raw=(TOOLS/'naver_claude_quality_transport.py').read_bytes()
        env={'CLAUDE_QUALITY_PATCH_B64':'synthetic-wire','CLAUDE_QUALITY_PATCH_TRANSPORT_B64':base64.b64encode(raw).decode()}
        for index,prefix in enumerate(self._actual_transport_bootstrap_prefixes()):
            scope={}
            with self.subTest(bootstrap=index),patch.object(os,'environ',dict(env)),patch.object(builtins,'exec') as execute:
                original_exec(prefix,scope)
                execute.assert_called_once_with(raw,scope['transport'].__dict__)
                self.assertEqual(scope['raw'],raw)

    def test_historical_fixed_jobs_and_controllers_are_unchanged(self):
        text,_=quality_pressure()
        jobs={'completion-postcompletion-patch': '28be0b6f1287fda8f95685ad99911894366fa6905bd196ec7f010ca8c771d5dd', 'completion-release': 'c26dad9ef6ee5d6df56bf65b5f48c0febc91c4bcd4687b6f8c0424ec85649001'}
        for name,digest in jobs.items():self.assertEqual(hashlib.sha256(quality_section(text,name).encode()).hexdigest(),digest)
        p=load('naver_completion_postcompletion_patch');t=load('naver_completion_postcompletion_transport')
        self.assertEqual(p.TARGET_COMMIT,'dadb4e89bb28021db50f1c5bb3682a6c81398003')
        for name,filename in t.SOURCE_FILES.items():
            self.assertEqual(hashlib.sha256((TOOLS/filename).read_bytes()).hexdigest(),t.SOURCE_SHA256[name])

    def test_three_new_choices_and_isolated_branch_concurrency_guard(self):
        text,pressure=quality_pressure();part=quality_section(text,'claude-quality-patch')
        for suffix in ('prepare','apply','rollback'):self.assertIn('preview-claude-quality-patch-'+suffix,text.split('jobs:',1)[0])
        self.assertIn("github.ref == 'refs/heads/codex/ad-deploy-prep-20261001'",part)
        self.assertIn('group: deploy-logic-analysis',part);self.assertIn('cancel-in-progress: false',part)
        self.assertIn("all(v=='off' for v in inputs.values())",part);self.assertIn('persist-credentials: false',part)
        self.assertIn('NAVER_CLAUDE_QUALITY_PATCH_RELEASE=',part)
        self.assertIn('bundle[\'sources\'][\'patch\']',part)
        self.assertNotIn('naver_completion_postcompletion_transport',part)
        self.assertEqual(len(pressure('wire','transport',text)),2)

    def test_actual_ssh_utf8_limit_and_unsafe_export_mutants(self):
        text,pressure=quality_pressure();wire='claude-quality-patch-xz-v1:AA==';transport='AA=='
        size=max(pressure(wire,transport,text));bounded=wire+'A'*(131071-size)
        self.assertEqual(max(pressure(bounded,transport,text)),131071)
        with self.assertRaisesRegex(ValueError,'COMPLETION_SSH_SIZE'):pressure(bounded+'A',transport,text)
        for char in ("'",'\n','\x00','가'):
            with self.assertRaisesRegex(ValueError,'COMPLETION_SSH_ENV'):pressure(wire+char,transport,text)
        # No execute(), NativeHost(), service or HTTP operation is invoked here.


if __name__=='__main__':unittest.main()
