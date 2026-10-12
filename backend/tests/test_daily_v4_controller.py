"""No host/DB/API calls: pin gates, actual child prefix and fixed postflight codes."""
import ast
import copy
import io
import json
import os
from pathlib import Path
import socket
import types
import unittest
from unittest.mock import Mock, patch

from daily_v4_support import AUTH, SELF, TOOLS, controller, package, pin_controller

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.c = controller()

    def test_pending_rejects_before_any_host_or_file_io(self):
        host = Mock()
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('IO')):
            with self.assertRaisesRegex(ValueError, '^D3_PINS_PENDING$'):
                self.c.run({}, host, Mock(), Mock(), '', Mock())
        host.baseline.assert_not_called()

    def test_disk_reader_slots_remain_none_after_controller_memory_binding(self):
        r = __import__('daily_v4_support').load('naver_daily_current_reader_v3.py')
        pin_controller(self.c)
        self.assertTrue(all(v is None for v in r.EXECUTION_PINS.values()))
        self.assertEqual(set(self.c.EXECUTION_PINS), {*self.c.APPROVED_RECEIPTS,'controller_transport_identity'})

    def test_binding_rejects_any_evidence_or_native_auth_mutation(self):
        evidence = dict(self.c.APPROVED_RECEIPTS, controller_transport_identity=SELF)
        for field in evidence:
            wrong = dict(evidence); wrong[field] = 'd'*64
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.c.bind_verified_evidence(wrong, SELF, AUTH)
        for field,value in [('head','x'),('run_id',True),('receipt_sha256','x')]:
            wrong = dict(AUTH); wrong[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.c.bind_verified_evidence(evidence,SELF,wrong)

    def test_package_exact_nested_types_and_event_no_fallback(self):
        pin_controller(self.c)
        for field,value in [('numeric_revision',True),('strategy_revision',False),('reserved_from','2026-10-13T07:09:00+09:00'),('possibility_id',51953),('ad_account_no',51952)]:
            wrong=copy.deepcopy(package());wrong['event_selector'][field]=value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError,'^D3_PACKAGE$'):
                self.c.validate_package(wrong)
        wrong=copy.deepcopy(package());wrong['diagnostic_native']['run_id']=True
        with self.assertRaises(ValueError):self.c.validate_package(wrong)

    def test_actual_generated_child_namespace_has_exact_pins_and_selector(self):
        pin_controller(self.c)
        raw = (TOOLS/'naver_daily_current_reader_v3.py').read_text()
        tree=ast.parse(self.c.script(raw))
        body=next(n for n in tree.body if isinstance(n,ast.Try)).body
        cutoff=next(i for i,n in enumerate(body) if isinstance(n,ast.Assign) and any(isinstance(v,ast.Name) and v.id=='result' for v in n.targets))
        prefix=ast.Module(body=tree.body[:next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Try))]+body[:cutoff],type_ignores=[])
        scope={}
        with patch.object(os,'geteuid',return_value=10001),patch.dict(os.environ,{},clear=True),patch.object(socket.socket,'connect'),patch.object(socket.socket,'connect_ex'),patch.object(socket,'create_connection'):
            exec(compile(prefix,'<actual-generated-child-prefix>','exec'),scope)
        reader=scope['scope']
        self.assertEqual(reader['EXECUTION_PINS'],self.c.EXECUTION_PINS)
        self.assertEqual(reader['EVENT_FROM'].isoformat(),'2026-10-13T07:10:00+09:00')
        self.assertEqual(reader['EVENT_UNTIL'].isoformat(),'2026-10-13T07:11:00+09:00')
        self.assertEqual((reader['PID'],reader['ADNO']),(51952,1030001))
        self.assertEqual(len(reader['SOURCE_FILES']),163)
        self.assertTrue(callable(reader['read_database']))

    def test_generated_child_rejects_reader_raw_mutation(self):
        pin_controller(self.c)
        with self.assertRaisesRegex(ValueError,'^D3_READER_SOURCE$'):
            self.c.script((TOOLS/'naver_daily_current_reader_v3.py').read_text()+'\n')

    def runtime(self,command=None,after=None,baseline=None):
        c=pin_controller(self.c)
        release=Mock(); release.command=Mock(return_value=b'{}') if command is None else command
        release.unique=lambda pairs:dict(pairs)
        life=Mock();before={'engine':{'id':'e'*64},'relay':{'id':'f'*64}}
        life._snapshot.side_effect=[before,copy.deepcopy(before) if after is None else after]
        host=Mock();host.baseline.side_effect=[c.BASELINE,c.BASELINE if baseline is None else baseline]
        reader=Mock();reader.validate_result=Mock()
        contexts=[patch.object(c.os,'geteuid',return_value=0),patch.object(c,'read_receipts',return_value=(Path('/closed'),{'images':{'engine':'sha256:'+'1'*64,'relay':'sha256:'+'2'*64}},{Path('/proof'):b'fixed'})),patch.object(c,'safe_runtime_files',return_value={Path('/unit'):b'fixed'}),patch.object(c,'engine_details',return_value={'closed':True}),patch.object(c,'script',return_value=b'fixed child')]
        for x in contexts:x.start()
        self.addCleanup(lambda:[x.stop() for x in reversed(contexts)])
        return c,release,life,host,reader

    def test_runtime_runs_one_exact_docker_exec_with_no_restart(self):
        c,r,l,h,reader=self.runtime()
        result=c.run(package(),h,r,l,'',reader)
        self.assertTrue(result['ok'])
        r.command.assert_called_once_with(['docker','exec','-i','--user','10001:10001','e'*64,'python','-I','-B','-'],data=b'fixed child',timeout=30)
        reader.validate_result.assert_called_once_with({})
        self.assertEqual(result['mutations'],0)
        self.assertFalse(result['database_opened_by_controller'])

    def test_runtime_reader_and_postflight_failures_both_preserved(self):
        command=Mock(side_effect=RuntimeError('raw-secret-do-not-show'))
        c,r,l,h,reader=self.runtime(command,after={'engine':{'id':'a'*64}},baseline='wrong')
        result=c.run(package(),h,r,l,'',reader)
        self.assertEqual(result['failure'],dict(primary_code='D3_READER_FAILED',post_engine_code='D3_POST_ENGINE',post_legacy_code='D3_POST_LEGACY',post_proof_code=None))
        self.assertNotIn('raw-secret',json.dumps(result))

    def test_unhashable_exception_argument_still_closed(self):
        c,r,l,h,reader=self.runtime(Mock(side_effect=ValueError({'raw':'secret'})))
        result=c.run(package(),h,r,l,'',reader)
        self.assertEqual(result['failure']['primary_code'],'D3_READER_FAILED')

    def test_result_size_and_child_error_are_closed(self):
        for raw in (b'x'*(self.c.MAX_OUTPUT+1),b'{"error_code":"raw"}',b'not-json'):
            with self.subTest(size=len(raw)):
                c,r,l,h,reader=self.runtime(Mock(return_value=raw))
                result=c.run(package(),h,r,l,'',reader)
                self.assertFalse(result['ok'])
                self.assertIn(result['failure']['primary_code'],('D3_OUTPUT','D3_READER_FAILED'))
                for cleanup in self._cleanups[:]: pass
                # Every context is isolated manually between subcases.
                while self._cleanups:
                    fn,args,kwargs=self._cleanups.pop();fn(*args,**kwargs)

    def test_preflight_wrong_uid_never_executes_reader(self):
        c=pin_controller(self.c);r=Mock()
        with patch.object(c.os,'geteuid',return_value=10001),self.assertRaisesRegex(ValueError,'^D3_ROOT$'):
            c.run(package(),Mock(),r,Mock(),'',Mock())
        r.command.assert_not_called()

    def test_controller_has_no_db_writer_provider_or_environment_read(self):
        tree=ast.parse((TOOLS/'naver_daily_current_diagnostics_v4.py').read_text())
        imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{v.name for n in ast.walk(tree) if isinstance(n,ast.Import) for v in n.names}
        self.assertFalse(imports & {'sqlite3','requests','http','naver_engine.store'})
        names={n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}
        self.assertFalse(names & {'write_bytes','write_text','synchronize_management','inspection_work','performance_work','getenv'})

    def test_prepared_and_started_receipts_bind_live_source_and_off_flags(self):
        import tempfile
        c=pin_controller(self.c)
        prepared=dict(ok=True,stage='prepared',source_commit=c.SOURCE,
            package=dict(baseline=c.BASELINE,source_commit=c.SOURCE,source_tar_gz_sha256=c.ARCHIVE,run_id=c.PREPARE_RUN),
            config_operation_id=c.CONFIG_OPERATION,runtime_environment_preserved=True,
            inventory_enabled=True,execution_enabled=False,runtime_flags_verified=True,
            images={'engine':'sha256:'+'1'*64,'relay':'sha256:'+'2'*64})
        started=dict(ok=True,stage='internal_ready',source_commit=c.SOURCE,previous_commit=c.PREVIOUS,
            operation_id=c.APPLY_OPERATION,database_schema=21,database_policy='preserve-in-place',
            database_opened_by_controller=False,source_warmup_performed=False,database_snapshot_verified=False,
            rollback_requires_matching_database=False,saved_export_companion_preserved=True,execution_enabled=False,runtime_flags_verified=True)
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);receipt=folder/'preview.json';start=folder/('preview-start-'+c.SOURCE+'.json')
            release=Mock();release.prepared_paths.return_value=(folder,receipt);release.unique=lambda pairs:dict(pairs)
            receipt.write_text(json.dumps(prepared));start.write_text(json.dumps(started))
            path,row,proof=c.read_receipts(release)
            self.assertEqual(row,prepared);self.assertEqual(len(proof),2)
            for key,value in [('source_commit',c.PREVIOUS),('operation_id','a'*32),('database_schema',20),('execution_enabled',True),('database_opened_by_controller',True)]:
                bad=dict(started);bad[key]=value;start.write_text(json.dumps(bad))
                with self.subTest(key=key),self.assertRaisesRegex(ValueError,'^D3_SOURCE_NOT_READY$'):c.read_receipts(release)
            start.write_text(json.dumps(started))
            bad=dict(prepared);bad['runtime_environment_preserved']=False;receipt.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):c.read_receipts(release)

    def test_engine_source_user_data_mount_and_state_are_all_closed(self):
        c=pin_controller(self.c);identity='e'*64;image='sha256:'+'1'*64
        value=dict(id=identity,image=image,user='10001:10001',running=True,restarting=False,pid=42,
            started='fixed-time',restarts=0,source=c.SOURCE,project='naver-engine',service='naver-engine',readonly=True,
            data=[dict(Type='bind',Source='/var/lib/metainc/naver-engine',Destination='/var/lib/naver-engine',RW=True)])
        release=Mock();release.unique=lambda pairs:dict(pairs);release.command.return_value=json.dumps(value).encode()
        self.assertEqual(c.engine_details(identity,image,release),value)
        for key,new in [('source',c.PREVIOUS),('user','0:0'),('running',False),('restarting',True),('readonly',False),('pid',True),('restarts',1),('data',[])]:
            bad=copy.deepcopy(value);bad[key]=new;release.command.return_value=json.dumps(bad).encode()
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'^D3_CONTAINER$'):c.engine_details(identity,image,release)
        fmt=release.command.call_args.args[0][3]
        self.assertNotIn('.Config.Env',fmt)

    def test_source_proof_recheck_failure_does_not_hide_reader_error(self):
        c,r,l,h,reader=self.runtime(Mock(side_effect=RuntimeError('raw-error')))
        c.read_receipts.side_effect=[(Path('/closed'),{'images':{'engine':'x','relay':'y'}},{Path('/proof'):b'fixed'}),ValueError('changed')]
        value=c.run(package(),h,r,l,'',reader)
        self.assertEqual(value['failure']['primary_code'],'D3_READER_FAILED')
        self.assertEqual(value['failure']['post_proof_code'],'D3_POST_PROOF')
        self.assertNotIn('raw-error',json.dumps(value))

    def test_authenticated_companion_bytes_are_rechecked_after_reader(self):
        c,r,l,h,reader=self.runtime()
        c.safe_runtime_files.side_effect=[
            {Path('/unit'):b'fixed',Path('/companion-proof'):b'approved'},
            {Path('/unit'):b'fixed',Path('/companion-proof'):b'changed'}]
        value=c.run(package(),h,r,l,'',reader)
        self.assertFalse(value['ok'])
        self.assertEqual(value['failure'],dict(primary_code=None,post_engine_code=None,
            post_legacy_code=None,post_proof_code='D3_POST_PROOF'))
        self.assertEqual(c.safe_runtime_files.call_count,2)
        r.command.assert_called_once()
