"""Closed diagnostic transport only: synthetic payloads, no host or provider calls."""
import ast
import base64
import copy
import hashlib
import importlib.util
import json
import lzma
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

TOOLS=Path(__file__).parents[1]/'tools'


def load():
    spec=importlib.util.spec_from_file_location('source_diagnostics_transport_test',TOOLS/'naver_current_inspection_diagnostics_transport.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def fixture():
    t=load();sources={name:'value='+repr(name)+'\n' for name in t.SOURCE_FILES}
    t.SOURCE_SHA256=t.COMPACT_SHA256={name:hashlib.sha256(body.encode()).hexdigest() for name,body in sources.items()}
    return t,dict(version=1,operation=t.OPERATION,package=dict(t.PACKAGE),sources=sources)


def section(text,name):
    lines=text.splitlines(keepends=True);start=lines.index('  '+name+':\n')
    end=next((i for i in range(start+1,len(lines)) if lines[i].startswith('  ') and not lines[i].startswith('   ') and lines[i].strip().endswith(':')),len(lines))
    return ''.join(lines[start:end])


def pressure():
    workflow=(TOOLS.parents[1]/'.github/workflows/debug-rank.yml').read_text();part=section(workflow,'current-inspection-diagnostics')
    first=part.index('          def current_inspection_ssh_scripts(');last=part.index('          T.require_pins()',first)
    source=''.join(line[10:] if line.startswith('          ') else line for line in part[first:last].splitlines(keepends=True));scope={};exec(compile(ast.parse(source),'<actual-source-diagnostics-pressure>','exec'),scope)
    return workflow,scope['require_current_inspection_ssh_pressure']


def failure_value(t):
    return dict(ok=False,mode=t.MODE,source_commit=t.SOURCE,mutations=0,collection_completion_verified=False,
                failure=dict(primary_code='SOURCE_DIAGNOSTICS_READ_FAILED',post_engine_code=None,post_legacy_baseline_code=None))


class PinsAndCodecTests(unittest.TestCase):
    def test_missing_pin_refuses_before_sources_modules_or_host(self):
        t=load()
        with patch.object(t,'SOURCE_SHA256',None),patch.object(Path,'read_bytes',side_effect=AssertionError('NO_READ')) as read,patch.object(t.types,'ModuleType',side_effect=AssertionError('NO_EXEC')) as module:
            with self.assertRaisesRegex(ValueError,'^SOURCE_DIAGNOSTICS_NOT_PINNED$'):t.bundle(t.PACKAGE,TOOLS)
            result=t.execute({})
        self.assertFalse(result['ok']);self.assertEqual(result['error_code'],'SOURCE_DIAGNOSTICS_NOT_PINNED');read.assert_not_called();module.assert_not_called()

    def test_fixed_four_field_package_rejects_pid_sql_mode_source_and_archive_changes(self):
        t=load();self.assertEqual(t.validate_package(dict(t.PACKAGE)),t.PACKAGE)
        for key,value in [('mode','sql'),('source_commit','0'*40),('source_tar_gz_sha256','0'*64),('baseline','0'*64),('pid',1),('sql','SELECT *')]:
            changed=dict(t.PACKAGE,**{key:value})
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'^SOURCE_DIAGNOSTICS_PACKAGE$'):t.validate_package(changed)

    def test_dispatch_inputs_require_exact_operation_all_off_and_no_unknown_input(self):
        t=load();inputs=dict(ad_prepare=t.OPERATION,ad_expected_baseline=json.dumps(t.PACKAGE),**t.DEFAULTS)
        self.assertEqual(t.validate_dispatch_inputs(inputs),t.PACKAGE)
        for kind in ('operation','active','unknown','missing','sql','duplicate'):
            changed=dict(inputs)
            if kind=='operation':changed['ad_prepare']='preview-completion-apply'
            if kind=='active':changed['collector']='on'
            if kind=='unknown':changed['extra']='off'
            if kind=='missing':changed.pop('collector')
            if kind=='sql':changed['ad_expected_baseline']=json.dumps(dict(t.PACKAGE,sql='SELECT *'))
            if kind=='duplicate':changed['ad_expected_baseline']='{"mode":"x","mode":"y"}'
            with self.subTest(kind=kind),self.assertRaises(ValueError):t.validate_dispatch_inputs(changed)

    def test_codec_roundtrip_uses_only_three_sources_and_narrow_bounds(self):
        t,v=fixture();wire=t.encode(v);self.assertEqual(t.decode(wire),v)
        self.assertEqual(set(t.SOURCE_FILES),{'diagnostic','host','release'})
        self.assertEqual((t.MAX_JSON,t.MAX_WIRE,t.MAX_SOURCE,t.MAX_RESULT),(196608,65536,98304,20480))
        for kind in ('source','extra','boolean','operation','package'):
            changed=copy.deepcopy(v)
            if kind=='source':changed['sources']['diagnostic']+='secret'
            if kind=='extra':changed['sources']['sql']='SELECT'
            if kind=='boolean':changed['version']=True
            if kind=='operation':changed['operation']='preview-completion-apply'
            if kind=='package':changed['package']['mode']='sql'
            with self.subTest(kind=kind),self.assertRaises(ValueError):t.encode(changed)

    def test_truncated_trailing_duplicate_and_oversize_encoding_reject(self):
        t,v=fixture();wire=t.encode(v)
        duplicate=json.dumps(v).replace('"version": 1','"version": 1, "version": 1').encode()
        bad=t.PREFIX+base64.b64encode(lzma.compress(duplicate)).decode()
        for value in (wire[:-5],wire+'AAAA',bad,wire+'A'*t.MAX_WIRE):
            with self.assertRaises(ValueError):t.decode(value)

    def test_package_refuses_before_any_module_is_compiled(self):
        t,v=fixture();v['package']['sql']='UPDATE'
        with patch.object(t.types,'ModuleType',side_effect=AssertionError('NO_EXEC')) as module:
            result=t.execute(v)
        self.assertFalse(result['ok']);module.assert_not_called()

    def test_wrong_compiled_source_or_targets_refuses_before_host_module(self):
        for expression in ("SOURCE='0'*40","TARGETS=(('other',1,2),)","SCHEMA=11","TARGET_NAMESPACE=\'customer_id\'","MODE=\'inspection-source-diagnostics-v1\'"):
            t,v=fixture();diagnostic='\n'.join(('SOURCE='+repr(t.SOURCE),'ARCHIVE='+repr(t.ARCHIVE),'BASELINE='+repr(t.BASELINE),'SCHEMA=21','MODE='+repr(t.MODE),'TARGET_NAMESPACE='+repr(t.IDENTIFIER_NAMESPACE),'TARGETS='+repr(t.TARGETS),'def validate_package(value): pass',expression))+'\n'
            v['sources']['diagnostic']=diagnostic;t.COMPACT_SHA256['diagnostic']=hashlib.sha256(diagnostic.encode()).hexdigest()
            v['sources']['host']='raise AssertionError("HOST MODULE MUST NOT LOAD")\n';t.COMPACT_SHA256['host']=hashlib.sha256(v['sources']['host'].encode()).hexdigest()
            with self.subTest(expression=expression),self.assertRaisesRegex(ValueError,'^SOURCE_DIAGNOSTICS_MODULE$'):t.modules(v)

    def test_compactor_preserves_ast_and_string_literals(self):
        t=load();source='''# commentary\ndef value():\n    text = "literal # content"\n    return text\n''';result=t.compact(source)
        self.assertEqual(ast.dump(ast.parse(source)),ast.dump(ast.parse(result)));self.assertIn('literal # content',result)


class PinnedSourceTests(unittest.TestCase):
    def test_actual_three_source_bundle_has_exact_raw_and_compact_pins(self):
        t=load();value=t.bundle(dict(t.PACKAGE),TOOLS)
        self.assertEqual(t.decode(t.encode(value)),value)
        for name,filename in t.SOURCE_FILES.items():
            raw=(TOOLS/filename).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),t.SOURCE_SHA256[name])
            self.assertEqual(hashlib.sha256(t.compact(raw.decode()).encode()).hexdigest(),t.COMPACT_SHA256[name])
        modules=t.modules(value)
        self.assertEqual(modules['diagnostic'].TARGETS,t.TARGETS)
        self.assertEqual(modules['diagnostic'].SCHEMA,21)

    def test_actual_three_source_packet_ssh_pressure_is_bounded(self):
        t=load();value=t.bundle(dict(t.PACKAGE),TOOLS);wire=t.encode(value)
        raw=(TOOLS/'naver_current_inspection_diagnostics_transport.py').read_bytes()
        transport=base64.b64encode(raw).decode();workflow,check=pressure()
        self.assertLessEqual(len(json.dumps(value,separators=(',',':')).encode()),t.MAX_JSON)
        self.assertLessEqual(len(wire),t.MAX_WIRE)
        self.assertLessEqual(len(transport),t.MAX_TRANSPORT_BASE64)
        self.assertLess(max(check(wire,transport,workflow)),131072)

    def test_previous_transport_and_release_modules_are_unchanged(self):
        expected={
            'naver_strategy_validation_patch.py':'2e2ae80647791319a668a33f31439027f1e9d63d5965ae4e7c3e53ad99343cc7',
            'naver_strategy_validation_transport.py':'775da749e4990cd78e41ee6e7db88dab4c48e6d9eb0c74769b2d99d482491d6a',
            'naver_claude_quality_patch.py':'801bc80b1a682233c72afc5e8915b2493a6dc4470bea2b4137055547aab355c3',
            'naver_claude_quality_transport.py':'a3e6257a0f81268e644a779ac206b3d2201ee8ce771d3c59f382a9f29c8d4f1f'}
        for name,pin in expected.items():
            with self.subTest(name=name):self.assertEqual(hashlib.sha256((TOOLS/name).read_bytes()).hexdigest(),pin)

    def test_every_previous_workflow_job_and_native_test_step_is_unchanged(self):
        workflow=(TOOLS.parents[1]/'.github/workflows/debug-rank.yml').read_text()
        # Strip only the independently tested exact-dc168 diagnostic registration.
        workflow=workflow.replace(section(workflow,'setup-stale-diagnostics'),'').replace(', preview-setup-stale-diagnostics','')
        # P5 has independent checks; remove only its registration from prior projections.
        workflow=workflow.replace(section(workflow,'budget-draft-patch'),'')
        for budget_operation in ('prepare','apply','rollback'):
            budget_option=', preview-budget-draft-patch-'+budget_operation
            self.assertEqual(workflow.count(budget_option),1)
            workflow=workflow.replace(budget_option,'')
        prior=workflow.replace(section(workflow,'current-inspection-diagnostics'),'').replace(', preview-current-inspection-diagnostics','')
        self.assertEqual(hashlib.sha256(prior.encode()).hexdigest(),'4c14d09d5398ee1ac61162c88ace81a2b4222e36ee01fa6fc39c509554619930')
        native=(TOOLS.parents[1]/'.github/workflows/naver-product-export-tests.yml').read_text()
        setup_start=native.index('      - name: 현재 dc168 설정 원천·scope·읽기 전용 진단 검사\n')
        setup_end=native.index('      - name:',setup_start+1)
        native=native[:setup_start]+native[setup_end:]
        budget_start=native.index('      - name: 기존 예산 초안·상품 가설 패치·15f 복구 경계 검사\n')
        budget_end=native.index('      - name:',budget_start+1)
        native=native[:budget_start]+native[budget_end:]
        start=native.index('      - name: 현재 15f 점검 진척·증명·읽기 전용 진단 검사\n')
        end=native.index('      - name:',start+1)
        prior=native[:start]+native[end:]
        self.assertEqual(hashlib.sha256(prior.encode()).hexdigest(),'378086ecf269b518d1b6fabca2982aacba40f53fc45afdb3a24f1e3e1ee64edf')



class ProjectionTests(unittest.TestCase):
    def diagnostic(self):
        return SimpleNamespace(READ_FAILURE_CODES=frozenset({'SOURCE_DIAGNOSTICS_READ_FAILED','SOURCE_DIAGNOSTICS_TARGET_NOT_FOUND','SOURCE_DIAGNOSTICS_TARGET_AMBIGUOUS'}),validate_result=Mock())

    def test_reader_and_postflight_failures_are_preserved_together(self):
        t=load();d=self.diagnostic();value=failure_value(t);value['failure'].update(post_engine_code='POST_ENGINE_CHANGED',post_legacy_baseline_code='POST_LEGACY_BASELINE_UNVERIFIED')
        self.assertEqual(t.project_result(value,d),value)

    def test_arbitrary_failure_string_or_extra_raw_field_rejects(self):
        t=load();d=self.diagnostic()
        for kind in ('private','extra','empty','integer','post'):
            value=failure_value(t)
            if kind=='private':value['failure']['primary_code']='PRIVATE=secret'
            if kind=='extra':value['raw']='PRIVATE=secret'
            if kind=='empty':value['failure']['primary_code']=None
            if kind=='integer':value['mutations']=False
            if kind=='post':value['failure']['post_engine_code']='PRIVATE=secret'
            with self.subTest(kind=kind),self.assertRaises(ValueError):t.project_result(value,d)

    def test_success_requires_exact_outer_contract_and_delegates_nested_validation(self):
        t=load();d=self.diagnostic();value=dict(ok=True,mode=t.MODE,source_commit=t.SOURCE,mutations=0,collection_completion_verified=False,reader_mode='sqlite-mode-ro-query-only-authorizer',database_opened_by_controller=False,existing_app_baseline_unchanged=True,diagnostics={'closed':'fixture','target_identifier_namespace':'ad_account_no'})
        self.assertEqual(t.project_result(value,d),value);d.validate_result.assert_called_once_with(value['diagnostics'])
        for key,wrong in (('database_opened_by_controller',True),('existing_app_baseline_unchanged',False),('source_commit','0'*40),('raw','secret')):
            with self.subTest(key=key),self.assertRaises(ValueError):t.project_result(dict(value,**{key:wrong}),d)
        d.validate_result.side_effect=ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
        with self.assertRaises(ValueError):t.project_result(value,d)

    def test_old_customer_id_profile_or_ambiguous_namespace_cannot_be_accepted(self):
        t,v=fixture()
        for kind in ('mode','version','prefix'):
            changed=copy.deepcopy(v)
            if kind=='mode':changed['package']['mode']='inspection-source-diagnostics-v1'
            if kind=='version':changed['version']=2
            with self.subTest(kind=kind):
                if kind=='prefix':
                    with self.assertRaises(ValueError):t.decode('current-inspection-diagnostics-xz-v1:'+t.encode(v).split(':',1)[1])
                else:
                    with self.assertRaises(ValueError):t.encode(changed)

    def test_target_resolution_failures_are_closed_and_no_internal_ids_are_output(self):
        t=load();d=self.diagnostic()
        for code in ('SOURCE_DIAGNOSTICS_TARGET_NOT_FOUND','SOURCE_DIAGNOSTICS_TARGET_AMBIGUOUS'):
            value=failure_value(t);value['failure']['primary_code']=code
            self.assertEqual(t.project_result(value,d),value)
            with self.assertRaises(ValueError):t.project_result(dict(value,customer_id=1),d)

    def test_result_namespace_is_explicit_even_if_nested_validator_is_accidentally_loose(self):
        t=load();d=self.diagnostic();value=dict(ok=True,mode=t.MODE,source_commit=t.SOURCE,mutations=0,
            collection_completion_verified=False,reader_mode='sqlite-mode-ro-query-only-authorizer',
            database_opened_by_controller=False,existing_app_baseline_unchanged=True,
            diagnostics={'target_identifier_namespace':'ad_account_no'})
        self.assertEqual(t.project_result(value,d),value)
        for namespace in (None,'customer_id',123):
            value['diagnostics']['target_identifier_namespace']=namespace
            with self.subTest(namespace=namespace),self.assertRaises(ValueError):t.project_result(value,d)

    def test_untrusted_exception_text_never_leaks(self):
        t=load()
        for error in (RuntimeError('PRIVATE=secret'),ValueError('SOURCE_NOT_READY'),OSError('/private/file')):
            result=t.failure(error,'postflight');self.assertNotIn('secret',json.dumps(result));self.assertNotIn('/private',json.dumps(result))
            self.assertEqual(result['error_code'],'SOURCE_NOT_READY' if type(error) is ValueError else 'UNRECOGNIZED')

    def test_invalid_result_cannot_escape_execute(self):
        t,v=fixture();d=self.diagnostic();d.STAGE='postflight';d.run=Mock(return_value=dict(ok=True,private='secret'))
        host=Mock();m=dict(diagnostic=d,host=SimpleNamespace(NativeHost=Mock(return_value=host)),release=Mock())
        with patch.object(t,'modules',return_value=m):result=t.execute(v)
        self.assertFalse(result['ok']);self.assertEqual(result['error_code'],'SOURCE_DIAGNOSTICS_RESULT');self.assertNotIn('secret',json.dumps(result))

    def test_execute_only_invokes_fixed_run_and_never_runtime_collection_or_write_methods(self):
        t,v=fixture();d=self.diagnostic();d.STAGE='postflight';d.run=Mock(return_value=failure_value(t));host=Mock();release=Mock();native=Mock(return_value=host)
        with patch.object(t,'modules',return_value=dict(diagnostic=d,host=SimpleNamespace(NativeHost=native),release=release)):
            result=t.execute(v)
        self.assertFalse(result['ok']);d.run.assert_called_once_with(v['package'],host,release);release.assert_not_called()


class WorkflowTests(unittest.TestCase):
    def bootstrap(self,synthetic_pin=None):
        text,_=pressure();part=section(text,'current-inspection-diagnostics');scripts=re.findall(r"(?ms)^            /usr/bin/python3 -I -B - <<'PYCODE'\n(.*?)^            PYCODE$",part);self.assertEqual(len(scripts),1)
        source=''.join(line[12:] if line.startswith('            ') else line for line in scripts[0].splitlines(keepends=True));tree=ast.parse(source)
        guards=[node for node in ast.walk(tree) if isinstance(node,ast.Compare) and isinstance(node.left,ast.Call) and isinstance(node.left.func,ast.Attribute) and node.left.func.attr=='hexdigest'];self.assertEqual(len(guards),1)
        if synthetic_pin is not None:guards[0].comparators[0]=ast.Constant(value=synthetic_pin)
        attempt=next(node for node in tree.body if isinstance(node,ast.Try));stop=next(i for i,node in enumerate(attempt.body) if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='exec')+1
        return compile(ast.fix_missing_locations(ast.Module(body=tree.body[:tree.body.index(attempt)]+attempt.body[:stop],type_ignores=[])),'<actual-source-diagnostics-bootstrap>','exec')

    def test_transport_sha_precedes_exec_in_actual_bootstrap(self):
        import builtins,os
        t=load();raw=(TOOLS/'naver_current_inspection_diagnostics_transport.py').read_bytes();pin=hashlib.sha256(raw).hexdigest();original_exec=builtins.exec
        bootstrap=self.bootstrap(pin)
        for body,valid in ((raw,True),(raw+b'\n# synthetic tamper\n',False)):
            env={'CURRENT_INSPECTION_DIAGNOSTICS_B64':'synthetic','CURRENT_INSPECTION_DIAGNOSTICS_TRANSPORT_B64':base64.b64encode(body).decode()};scope={}
            with self.subTest(valid=valid),patch.object(os,'environ',env),patch.object(builtins,'exec') as execute:
                if valid:original_exec(bootstrap,scope);execute.assert_called_once_with(raw,scope['transport'].__dict__)
                else:
                    with self.assertRaisesRegex(ValueError,'^SOURCE_DIAGNOSTICS_TRANSPORT_SOURCE$'):original_exec(bootstrap,scope)
                    execute.assert_not_called()

    def test_one_fixed_branch_job_and_no_generic_legacy_dispatch(self):
        text,_=pressure();part=section(text,'current-inspection-diagnostics')
        self.assertIn('preview-current-inspection-diagnostics',text.split('jobs:',1)[0]);self.assertIn("github.ref == 'refs/heads/codex/ad-deploy-prep-20261001'",part)
        self.assertIn('group: deploy-logic-analysis',part);self.assertIn('cancel-in-progress: false',part);self.assertIn('persist-credentials: false',part)
        self.assertEqual(sum(line.strip().startswith('uses: appleboy/ssh-action@') for line in part.splitlines()),1)
        for forbidden in ('scp-action','naver_completion_transport','preview-conversion-diagnostics','nginx','systemctl','--log','debug_context'):
            self.assertNotIn(forbidden,part)
        self.assertIn('NAVER_CURRENT_INSPECTION_DIAGNOSTICS_AD_ACCOUNT_V1=',part)

    def test_ssh_size_and_environment_bounds_use_actual_script(self):
        text,check=pressure();size=max(check('wire','transport',text));value='wire'+'A'*(131071-size)
        self.assertEqual(max(check(value,'transport',text)),131071)
        with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_SSH_SIZE'):check(value+'A','transport',text)
        for char in ("'",'\n','\x00','한'):
            with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_SSH_ENV'):check('wire'+char,'transport',text)

    def test_actual_bootstrap_pin_is_closed_pending_or_exact(self):
        text,_=pressure();part=section(text,'current-inspection-diagnostics');pins=re.findall(r"hashlib\.sha256\(raw\)\.hexdigest\(\)!='([^']+)'",part);self.assertEqual(len(pins),1)
        if pins[0]!='UNPINNED_CURRENT_INSPECTION_DIAGNOSTICS_TRANSPORT':self.assertEqual(pins[0],hashlib.sha256((TOOLS/'naver_current_inspection_diagnostics_transport.py').read_bytes()).hexdigest())


if __name__=='__main__':unittest.main()
