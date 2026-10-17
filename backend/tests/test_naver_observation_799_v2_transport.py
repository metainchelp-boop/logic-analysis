"""Fixed799 v2 transport: invented payloads and authenticated local source only."""
import ast,base64,copy,hashlib,importlib.util,json,lzma,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from test_naver_observation_799_v2_diagnostics import D,result_fixture

TOOLS=Path(__file__).resolve().parents[1]/'tools'
def load():
    spec=importlib.util.spec_from_file_location('observation799_v2_transport_test',TOOLS/'naver_observation_799_transport_v2.py')
    t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t);return t
def fixture():
    t=load();sources={name:'value='+repr(name)+'\n'for name in t.SOURCE_FILES}
    t.SOURCE_SHA256=t.COMPACT_SHA256={name:hashlib.sha256(body.encode()).hexdigest()for name,body in sources.items()}
    t.P6_CONTROLLER_SHA256=t.SOURCE_SHA256['p6']
    return t,dict(version=1,operation=t.OPERATION,package=dict(t.PACKAGE),sources=sources)
def success(t):
    return dict(ok=True,mode=t.MODE,source_commit=t.SOURCE,mutations=0,collection_completion_verified=False,
        reader_mode='sqlite-mode-ro-query-only-authorizer',database_opened_by_controller=False,
        existing_app_baseline_unchanged=True,diagnostics=result_fixture())
def failure(t):
    return dict(ok=False,mode=t.MODE,source_commit=t.SOURCE,mutations=0,collection_completion_verified=False,
        failure=dict(primary_code='SOURCE_DIAGNOSTICS_READ_FAILED',post_engine_code=None,post_legacy_baseline_code=None))

class CodecTests(unittest.TestCase):
    def test_missing_pins_refuse_before_source_read_or_module_exec(self):
        t=load()
        with patch.object(t,'SOURCE_SHA256',None),patch.object(Path,'read_bytes',side_effect=AssertionError('NO_READ'))as read,patch.object(t.types,'ModuleType',side_effect=AssertionError('NO_EXEC'))as module:
            with self.assertRaisesRegex(ValueError,'^SOURCE_DIAGNOSTICS_NOT_PINNED$'):t.bundle(t.PACKAGE,TOOLS)
            result=t.execute({})
        self.assertEqual(result['error_code'],'SOURCE_DIAGNOSTICS_NOT_PINNED');read.assert_not_called();module.assert_not_called()
    def test_fixed_new_operation_mode_prefix_and_old_v1_refuse(self):
        t=load();self.assertEqual((t.OPERATION,t.MODE,t.PREFIX),('preview-observation-799-diagnostics-v2','observation-diagnostics-ad-account-799-v2','observation-diagnostics-ad-account-799-xz-v2:'))
        for key,value in (('mode','observation-diagnostics-ad-account-799-v1'),('source_commit','0'*40),('source_tar_gz_sha256','0'*64),('sql','SELECT'),('event_selector',None)):
            with self.subTest(key=key),self.assertRaises(ValueError):t.validate_package(dict(t.PACKAGE,**{key:value}))
        old='observation-diagnostics-ad-account-799-xz-v1:'
        with self.assertRaises(ValueError):t.decode(old+'AAAA')
    def test_exact_dispatch_inputs_only_one_operation_and_all_others_off(self):
        t=load();inputs=dict(ad_prepare=t.OPERATION,ad_expected_baseline=json.dumps(t.PACKAGE),**t.DEFAULTS)
        self.assertEqual(t.validate_dispatch_inputs(inputs),t.PACKAGE)
        for kind in ('old','active','extra','missing','duplicate'):
            bad=dict(inputs)
            if kind=='old':bad['ad_prepare']='preview-observation-799-diagnostics'
            if kind=='active':bad['collector']='on'
            if kind=='extra':bad['sql']='SELECT'
            if kind=='missing':bad.pop('queue')
            if kind=='duplicate':bad['ad_expected_baseline']='{"mode":"a","mode":"b"}'
            with self.subTest(kind=kind),self.assertRaises(ValueError):t.validate_dispatch_inputs(bad)
    def test_synthetic_roundtrip_and_exact_four_sources(self):
        t,v=fixture();self.assertEqual(t.decode(t.encode(v)),v)
        self.assertEqual(set(t.SOURCE_FILES),{'diagnostic','host','release','p6'})
        self.assertEqual(t.SOURCE_FILES['diagnostic'],'naver_observation_799_diagnostics_v2.py')
    def test_source_tamper_unknown_fields_and_boolean_version_refuse(self):
        t,v=fixture()
        for kind in ('body','extra','version','operation'):
            bad=copy.deepcopy(v)
            if kind=='body':bad['sources']['diagnostic']+='PRIVATE'
            if kind=='extra':bad['sources']['sql']='PRIVATE'
            if kind=='version':bad['version']=True
            if kind=='operation':bad['operation']='preview-observation-799-diagnostics'
            with self.subTest(kind=kind),self.assertRaises(ValueError):t.encode(bad)
    def test_bounded_decode_rejects_duplicate_truncated_trailing_and_oversize(self):
        t,v=fixture();wire=t.encode(v)
        duplicate=json.dumps(v).replace('"version": 1','"version": 1, "version": 1').encode()
        bad=t.PREFIX+base64.b64encode(lzma.compress(duplicate)).decode()
        for value in (wire[:-5],wire+'AAAA',bad,wire+'A'*t.MAX_WIRE):
            with self.assertRaises(ValueError):t.decode(value)
    def test_actual_sources_raw_compact_pins_and_packaged_module_identity(self):
        t=load();value=t.bundle(t.PACKAGE,TOOLS)
        self.assertEqual(t.decode(t.encode(value)),value)
        for name,filename in t.SOURCE_FILES.items():
            raw=(TOOLS/filename).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),t.SOURCE_SHA256[name])
            self.assertEqual(hashlib.sha256(t.compact(raw.decode()).encode()).hexdigest(),t.COMPACT_SHA256[name])
        modules=t.modules(value);self.assertEqual(set(modules),{'diagnostic','host','release'})
        packaged=modules['diagnostic'];self.assertEqual(packaged.CODE_PINS,D.CODE_PINS);self.assertEqual(packaged.EVENT_SELECTOR,D.EVENT_SELECTOR)
        self.assertEqual(packaged.MODE,t.MODE);self.assertEqual(packaged.TARGETS,D.TARGETS)
        self.assertEqual(packaged.PROJECTION_SOURCE,D.PROJECTION_SOURCE)
    def test_actual_bundle_stays_inside_existing_json_wire_and_base64_caps(self):
        t=load();value=t.bundle(t.PACKAGE,TOOLS)
        self.assertEqual((t.MAX_JSON,t.MAX_WIRE,t.MAX_SOURCE,t.MAX_RESULT,t.MAX_TRANSPORT_BASE64),(196608,65536,98304,20480,32768))
        self.assertLessEqual(len(json.dumps(value,allow_nan=False,separators=(',',':')).encode()),t.MAX_JSON)
        self.assertLessEqual(len(t.encode(value)),t.MAX_WIRE)
        self.assertLessEqual(len(base64.b64encode((TOOLS/'naver_observation_799_transport_v2.py').read_bytes())),t.MAX_TRANSPORT_BASE64)
    def test_compactor_preserves_full_ast_and_string_literals(self):
        t=load();source='''# comment\ndef value():\n    text="literal # source"\n    return text\n''';compact=t.compact(source)
        self.assertEqual(ast.dump(ast.parse(source)),ast.dump(ast.parse(compact)));self.assertIn('literal # source',compact)
    def test_bad_package_rejected_before_module_compile(self):
        t,v=fixture();v['package']['sql']='PRIVATE'
        with patch.object(t.types,'ModuleType',side_effect=AssertionError('NO_EXEC'))as module:
            out=t.execute(v)
        self.assertFalse(out['ok']);module.assert_not_called()

class ClosedResultTests(unittest.TestCase):
    def test_safe_success_preserves_reason_and_no_call_cost_claim(self):
        t=load();value=success(t);self.assertIs(t.project_result(value,D),value)
        payload=json.dumps(value)
        for private in ('actor','proof_hash','job_id','reserved_microusd','raw','PRIVATE'):self.assertNotIn(private,payload)
        self.assertFalse(value['collection_completion_verified'])
    def test_unknown_reason_or_extra_raw_field_is_rejected(self):
        t=load()
        for field,item in (('learning_failure_reason','PRIVATE'),('raw','PRIVATE')):
            value=success(t);value['diagnostics']['targets']['foodin'][field]=item
            with self.subTest(field=field),self.assertRaises(ValueError):t.project_result(value,D)
    def test_primary_and_both_postflight_errors_are_preserved(self):
        t=load();value=failure(t);value['failure'].update(post_engine_code='POST_ENGINE_CHANGED',post_legacy_baseline_code='POST_LEGACY_BASELINE_CHANGED')
        self.assertEqual(t.project_result(value,D),value)
        value['failure_detail']=dict(stage='learning-failure',kind='sqlite-busy');self.assertEqual(t.project_result(value,D),value)
    def test_unknown_error_text_is_closed_not_exposed(self):
        t=load();value=t.failure(RuntimeError('PRIVATE_EXCEPTION_BODY'))
        self.assertEqual(value['error_code'],'UNRECOGNIZED');self.assertNotIn('PRIVATE',json.dumps(value));self.assertEqual(t.project_result(value,D),value)
    def test_execute_calls_only_readonly_controller_after_authenticated_modules(self):
        t,v=fixture();diagnostic=SimpleNamespace(STAGE='postflight',READ_FAILURE_CODES=D.READ_FAILURE_CODES,validate_result=D.validate_result,validate_failure_detail=D.validate_failure_detail,run=Mock(return_value=success(t)))
        host=Mock();native=Mock(return_value=host);release=Mock()
        with patch.object(t,'modules',return_value=dict(diagnostic=diagnostic,host=SimpleNamespace(NativeHost=native),release=release)):
            out=t.execute(v)
        diagnostic.run.assert_called_once_with(v['package'],host,release);self.assertTrue(out['ok']);release.assert_not_called()
    def test_tampered_current_prepare_or_failed_postflight_never_returns_partial_success(self):
        t=load();value=failure(t);value['failure']['primary_code']=None;value['failure']['post_engine_code']='POST_ENGINE_CHANGED'
        self.assertEqual(t.project_result(value,D),value)
        for extra in ('diagnostics','tokens','actor'):
            bad=dict(value);bad[extra]='PRIVATE'
            with self.subTest(extra=extra),self.assertRaises(ValueError):t.project_result(bad,D)

if __name__=='__main__':unittest.main()
