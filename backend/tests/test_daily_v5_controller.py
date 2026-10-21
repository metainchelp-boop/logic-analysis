"""Source-layout and fixed failure boundaries; no host, DB or API operations."""
import ast
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import unittest
from unittest.mock import Mock, patch
from daily_v5_support import TOOLS, controller, package, pin_controller

class ControllerTests(unittest.TestCase):
    def runtime(self, command=None):
        c=pin_controller(controller())
        release=Mock();release.command=Mock(return_value=b'{}') if command is None else command
        release.unique=lambda pairs:dict(pairs)
        life=Mock();before={'engine':{'id':'e'*64},'relay':{'id':'f'*64}}
        life._snapshot.side_effect=[before,copy.deepcopy(before)]
        host=Mock();host.baseline.return_value=c.BASELINE
        reader=Mock()
        contexts=[patch.object(c.os,'geteuid',return_value=0),
            patch.object(c,'read_receipts',return_value=(Path('/fixed-prepared'),{'images':{'engine':'x','relay':'y'}},{Path('/proof'):b'fixed'})),
            patch.object(c,'safe_runtime_files',return_value={Path('/unit'):b'fixed'}),
            patch.object(c,'engine_details',return_value={'fixed':True}),
            patch.object(c,'script',return_value=b'fixed child')]
        for context in contexts: context.start()
        self.addCleanup(lambda:[context.stop() for context in reversed(contexts)])
        return c,release,life,host,reader

    def test_pending_before_any_host_source_or_child_io(self):
        c=controller();h=Mock();r=Mock();reader=Mock()
        with patch.object(Path,'read_bytes',side_effect=AssertionError('IO')):
            with self.assertRaisesRegex(ValueError,'^D3_PINS_PENDING$'):
                c.run({},h,r,Mock(),'',reader)
        h.baseline.assert_not_called();reader.verify_host_source.assert_not_called();r.command.assert_not_called()

    def test_exact_full_host_verification_happens_before_and_after_one_bounded_child(self):
        c,r,l,h,reader=self.runtime();order=[]
        reader.verify_host_source.side_effect=lambda p:order.append('host163')
        r.command.side_effect=lambda *a,**k:(order.append('child106') or b'{}')
        value=c.run(package(),h,r,l,'',reader)
        self.assertTrue(value['ok']);self.assertEqual(order,['host163','child106','host163'])
        self.assertEqual(reader.verify_host_source.call_args_list,[( (Path('/fixed-prepared'),), {}),((Path('/fixed-prepared'),),{})])
        r.command.assert_called_once_with(['docker','exec','-i','--user','10001:10001','e'*64,'python','-I','-B','-'],data=b'fixed child',timeout=30)
        self.assertFalse(value['database_opened_by_controller']);self.assertEqual(value['mutations'],0)

    def test_host_full_source_rejection_prevents_child_before_database(self):
        c,r,l,h,reader=self.runtime();reader.verify_host_source.side_effect=ValueError('private path')
        with self.assertRaisesRegex(ValueError,'^D3_HOST_SOURCE$'):
            c.run(package(),h,r,l,'',reader)
        r.command.assert_not_called()

    def test_post_host_source_drift_preserves_primary_stage(self):
        raw=json.dumps({'error_code':'D3_READER_FAILED','reader_stage':'IMPORT','reader_reason':'D3_SOURCE_IMPORT'}).encode()
        c,r,l,h,reader=self.runtime(Mock(return_value=raw))
        reader.verify_host_source.side_effect=[None,ValueError('not emitted')]
        value=c.run(package(),h,r,l,'',reader)
        self.assertEqual(value['failure']['primary_code'],'D3_READER_FAILED')
        self.assertEqual(value['failure']['reader_stage'],'IMPORT')
        self.assertEqual(value['failure']['post_proof_code'],'D3_POST_PROOF')
        self.assertNotIn('not emitted',json.dumps(value))

    def test_transport_timeout_and_command_error_are_fixed_separate_classes(self):
        for error,code in [(subprocess.TimeoutExpired(['secret'],30,output=b'secret'),'D3_READER_TIMEOUT'),(RuntimeError('secret'),'D3_READER_COMMAND')]:
            with self.subTest(code=code):
                c,r,l,h,reader=self.runtime(Mock(side_effect=error));value=c.run(package(),h,r,l,'',reader)
                self.assertEqual(value['failure']['primary_code'],code)
                self.assertIsNone(value['failure']['reader_stage'])
                self.assertNotIn('secret',json.dumps(value))
                self.doCleanups()

    def test_output_json_and_result_validation_have_distinct_fixed_codes(self):
        for raw,code,validate_error in [(b'x'*16385,'D3_OUTPUT',False),(b'not-json','D3_READER_JSON',False),(b'{}','D3_READER_VALIDATION',True)]:
            with self.subTest(code=code):
                c,r,l,h,reader=self.runtime(Mock(return_value=raw))
                if validate_error:reader.validate_result.side_effect=ValueError('raw row')
                value=c.run(package(),h,r,l,'',reader)
                self.assertEqual(value['failure']['primary_code'],code)
                self.assertNotIn('raw row',json.dumps(value));self.doCleanups()

    def test_child_error_stage_allowlist_and_shape_are_enforced(self):
        for stage in ('SOURCE','IMPORT','DB_OPEN','DB_QUERY','VALIDATE','CLEANUP'):
            c,r,l,h,reader=self.runtime(Mock(return_value=json.dumps({'error_code':'D3_READER_FAILED','reader_stage':stage,'reader_reason':'D3_UNCLASSIFIED'}).encode()))
            value=c.run(package(),h,r,l,'',reader)
            self.assertEqual(value['failure']['reader_stage'],stage);self.doCleanups()
        for row in [{'error_code':'D3_READER_FAILED','reader_stage':'secret','reader_reason':'D3_UNCLASSIFIED'},
                    {'error_code':'D3_READER_FAILED','reader_stage':None,'reader_reason':'D3_UNCLASSIFIED'},
                    {'error_code':'D3_READER_FAILED','reader_stage':'SOURCE','reader_reason':'private row'},
                    {'error_code':'D3_READER_FAILED','reader_stage':'SOURCE','reader_reason':[]},
                    {'error_code':'D3_READER_FAILED','reader_stage':'SOURCE','reader_reason':'D3_UNCLASSIFIED','raw':'no'},
                    {'error_code':'D3_READ_FAILED','reader_stage':'SOURCE','reader_reason':'D3_UNCLASSIFIED'}]:
            c,r,l,h,reader=self.runtime(Mock(return_value=json.dumps(row).encode()))
            value=c.run(package(),h,r,l,'',reader)
            self.assertEqual(value['failure']['primary_code'],'D3_OUTPUT')
            self.assertIsNone(value['failure']['reader_stage']);self.doCleanups()

    def test_generated_child_executes_exact_reader_namespace_pins_and_image_proof(self):
        c=pin_controller(controller());raw=(TOOLS/'naver_daily_current_reader_v5.py').read_text()
        tree=ast.parse(c.script(raw));node=next(n for n in tree.body if isinstance(n,ast.Try))
        cutoff=next(i for i,n in enumerate(node.body) if isinstance(n,ast.Assign) and any(isinstance(v,ast.Name) and v.id=='result' for v in n.targets))
        prefix=ast.Module(body=tree.body[:tree.body.index(node)]+node.body[:cutoff],type_ignores=[]);scope={}
        with patch.object(os,'geteuid',return_value=10001),patch.dict(os.environ,{},clear=True),patch.object(socket.socket,'connect'),patch.object(socket.socket,'connect_ex'),patch.object(socket,'create_connection'):
            exec(compile(prefix,'<actual-v5-child-prefix>','exec'),scope)
        actual=scope['scope'];self.assertEqual(actual['EXECUTION_PINS'],c.EXECUTION_PINS)
        self.assertEqual((len(actual['SOURCE_FILES']),len(actual['IMAGE_SOURCE_FILES'])),(163,106))
        self.assertEqual(actual['IMAGE_SOURCE_MAP_SHA256'],'69d77f2c2ede33f35d8d424665dfd85b4a710fcf3ff5fc88a85b281ce564332f')
        self.assertEqual((actual['PID'],actual['ADNO']),(51952,1030001))
        self.assertEqual(actual['EVENT_FROM'].isoformat(),'2026-10-13T07:10:00+09:00')
        self.assertEqual(actual['EVENT_UNTIL'].isoformat(),'2026-10-13T07:11:00+09:00')

    def test_child_source_preamble_failure_emits_only_fixed_stage(self):
        c=pin_controller(controller());raw=(TOOLS/'naver_daily_current_reader_v5.py').read_text();code=c.script(raw)
        import contextlib,io
        out=io.StringIO()
        with patch.object(os,'geteuid',return_value=0),contextlib.redirect_stdout(out):exec(compile(code,'<actual-v5-child>','exec'),{})
        self.assertEqual(json.loads(out.getvalue()),{'error_code':'D3_READER_FAILED','reader_stage':'SOURCE','reader_reason':'D3_UNCLASSIFIED'})

    def test_child_body_mutation_never_executes(self):
        c=pin_controller(controller())
        with self.assertRaisesRegex(ValueError,'^D3_READER_SOURCE$'):
            c.script((TOOLS/'naver_daily_current_reader_v5.py').read_text()+'\n')

    def test_controller_has_no_database_provider_writer_or_environment_read(self):
        tree=ast.parse((TOOLS/'naver_daily_current_diagnostics_v5.py').read_text())
        imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{v.name for n in ast.walk(tree) if isinstance(n,ast.Import) for v in n.names}
        self.assertFalse(imports & {'sqlite3','requests','http','naver_engine.store'})
        attrs={n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}
        self.assertFalse(attrs & {'write_bytes','write_text','synchronize_management','inspection_work','performance_work','getenv'})
