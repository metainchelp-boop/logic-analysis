"""Synthetic transport evidence only; no live host/auth/network/DB access."""
import base64
import copy
import io
import json
import lzma
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from d3_support import AUTH, SELF, TOOLS, failed, package, pin_transport, transport

class TransportTests(unittest.TestCase):
    def setUp(self):
        self.t=transport()

    def value(self):
        pin_transport(self.t)
        return self.t.bundle(package(),TOOLS)

    def test_unpinned_bundle_rejects_before_path_io(self):
        with patch.object(Path,'read_bytes',side_effect=AssertionError('IO')):
            with self.assertRaisesRegex(ValueError,'^D3_TRANSPORT_UNPINNED$'):
                self.t.bundle({},'/must-not-open')

    def test_unpinned_modules_and_execute_reject_before_compile_or_host(self):
        for fn in (self.t.modules,self.t.execute,self.t.decode):
            with patch('builtins.compile',side_effect=AssertionError('COMPILE')):
                with self.assertRaisesRegex(ValueError,'^D3_TRANSPORT_UNPINNED$'):fn({})

    def test_native_auth_cannot_come_from_package(self):
        self.t.__verified_self_sha__=SELF
        with self.assertRaises(ValueError):self.t.authorize(SELF,None)
        with self.assertRaises(ValueError):self.t.authorize('d'*64,AUTH)
        with self.assertRaises(ValueError):self.t.authorize(SELF,dict(AUTH,run_id=True))
        self.assertIsNone(self.t.VERIFIED_NATIVE_AUTHORIZATION)

    def test_package_native_proof_mismatch_and_boolean_revision_rejected(self):
        pin_transport(self.t)
        for changed in ('diagnostic_native','event_selector','evidence'):
            wrong=copy.deepcopy(package())
            if changed=='diagnostic_native':wrong[changed]['run_id']+=1
            elif changed=='event_selector':wrong[changed]['strategy_revision']=False
            else:wrong[changed]['controller_transport_identity']='d'*64
            with self.subTest(changed=changed),self.assertRaises(ValueError):self.t.validate_package(wrong)

    def test_duplicate_package_json_and_old_options_rejected(self):
        pin_transport(self.t)
        inputs=dict(self.t.DEFAULTS,ad_prepare=self.t.OPERATION,ad_expected_baseline=json.dumps(package()))
        self.assertEqual(self.t.validate_dispatch_inputs(inputs),package())
        for key in self.t.DEFAULTS:
            bad=dict(inputs);bad[key]='on'
            with self.subTest(key=key),self.assertRaises(ValueError):self.t.validate_dispatch_inputs(bad)
        bad=dict(inputs);bad['ad_expected_baseline']='{"mode":"x","mode":"y"}'
        with self.assertRaises(ValueError):self.t.validate_dispatch_inputs(bad)

    def test_bundle_roundtrip_preserves_raw_reader_and_all_five_sources(self):
        value=self.value()
        self.assertEqual(self.t.decode(self.t.encode(value)),value)
        self.assertEqual(value['sources']['reader'],(TOOLS/'naver_daily_current_reader_v3.py').read_text())
        self.assertEqual(set(value['sources']),set(self.t.SOURCE_FILES))

    def test_real_modules_bind_approved_evidence_in_memory_only(self):
        value=self.value();m=self.t.modules(value)
        self.assertEqual(m['controller'].EXECUTION_PINS,package()['evidence'])
        self.assertTrue(all(v is None for v in m['reader'].EXECUTION_PINS.values()))
        self.assertEqual(m['controller'].NATIVE_AUTHORIZATION,AUTH)
        self.assertEqual(m['reader'].PID,51952)
        self.assertEqual(m['reader'].ADNO,1030001)

    def test_raw_source_mutation_and_symlink_rejected(self):
        pin_transport(self.t)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for key,name in self.t.SOURCE_FILES.items():(root/name).write_bytes((TOOLS/name).read_bytes())
            target=root/self.t.SOURCE_FILES['controller'];target.write_bytes(target.read_bytes()+b'\n')
            with self.assertRaises(ValueError):self.t.bundle(package(),root)
            target.unlink();target.symlink_to(TOOLS/self.t.SOURCE_FILES['controller'])
            with self.assertRaises(ValueError):self.t.bundle(package(),root)

    def test_compact_source_mutation_or_extra_module_rejected_before_exec(self):
        value=self.value()
        for kind in ('mutate','extra','missing'):
            bad=copy.deepcopy(value)
            if kind=='mutate':bad['sources']['controller']+='\n'
            elif kind=='extra':bad['sources']['unapproved']='pass'
            else:del bad['sources']['reader']
            with self.subTest(kind=kind),patch('builtins.exec',side_effect=AssertionError('EXEC')):
                with self.assertRaises(ValueError):self.t.modules(bad)

    def test_decoder_rejects_duplicate_eof_trailing_and_oversize(self):
        value=self.value();wire=self.t.encode(value)
        trailing=wire+base64.b64encode(b'x').decode()
        huge=self.t.PREFIX+base64.b64encode(lzma.compress(b'x'*(self.t.MAX_JSON+1))).decode()
        duplicate=self.t.PREFIX+base64.b64encode(lzma.compress(b'{"version":1,"version":1}')).decode()
        for bad in (trailing,huge,duplicate,wire[:-4],self.t.PREFIX+'A'*(self.t.MAX_WIRE+1)):
            with self.subTest(length=len(bad)),self.assertRaises(ValueError):self.t.decode(bad)

    def test_compaction_preserves_ast_empty_fields_and_literal_bytes(self):
        source='''# removable\ndef example(a,*,b=1):\n    value = "# literal\\n"\n    return [x for x in [a,b] if x]\n'''
        compact=self.t.compact(source)
        self.assertNotIn('# removable',compact)
        self.assertIn('"# literal\\n"',compact)
        compile(compact,'<synthetic>','exec')

    def test_result_failure_codes_never_include_raw_error_or_extra_field(self):
        pin_transport(self.t);reader=Mock()
        for bad in (dict(failed(),raw='secret'),dict(failed(),mutations=True),dict(failed(),source_commit='x')):
            with self.assertRaises(ValueError):self.t.project_result(bad,reader)
        for key in failed()['failure']:
            bad=failed();bad['failure'][key]='secret'
            with self.assertRaises(ValueError):self.t.project_result(bad,reader)
        self.assertEqual(self.t.project_result(failed('D3_BASELINE'),reader),failed('D3_BASELINE'))

    def test_result_success_runs_frozen_closed_validator(self):
        pin_transport(self.t);reader=Mock();reader.validate_result.side_effect=ValueError('closed')
        value=dict(failed(),ok=True,existing_app_baseline_unchanged=True,reader_mode='sqlite-mode-ro-query-only-authorizer',diagnostics={'unapproved':'raw'})
        del value['failure']
        with self.assertRaises(ValueError):self.t.project_result(value,reader)
        reader.validate_result.assert_called_once_with({'unapproved':'raw'})

    def test_execute_preflight_exception_closed_without_raw_repr(self):
        value=self.value();m=self.t.modules(value)
        m['controller'].run=Mock(side_effect=RuntimeError('do-not-output-secret'))
        m['host'].NativeHost=Mock()
        with patch.object(self.t,'modules',return_value=m):result=self.t.execute(value)
        self.assertEqual(result['failure']['primary_code'],'D3_INTERNAL')
        self.assertNotIn('do-not-output',json.dumps(result))

    def test_bootstrap_pending_native_or_self_never_reads_path(self):
        body=base64.b64encode((TOOLS/'naver_daily_current_transport_v3.py').read_bytes()).decode()
        with patch.object(Path,'read_bytes',side_effect=AssertionError('IO')):
            with self.assertRaises(ValueError):self.t.bootstrap(self.t.PREFIX+'AA==',body,SELF)
            with self.assertRaises(ValueError):self.t.bootstrap(self.t.PREFIX+'AA==',body,None,AUTH)

    def test_actual_bootstrap_authenticates_raw_before_exec_and_has_closed_failure(self):
        raw=(TOOLS/'naver_daily_current_transport_v3.py').read_bytes();sha=self.t.digest(raw)
        code=self.t.bootstrap(self.t.PREFIX+'AA==',base64.b64encode(raw).decode(),sha,AUTH)
        stream=io.StringIO()
        # The unpopulated source map rejects; no host module can execute.
        with patch('sys.stdout',stream):exec(compile(code,'<actual-unpinned-bootstrap>','exec'),{})
        lines=stream.getvalue().splitlines();self.assertEqual(len(lines),1)
        self.assertTrue(lines[0].startswith(self.t.MARKER))
        result=json.loads(lines[0][len(self.t.MARKER):])
        self.assertEqual(result['failure']['primary_code'],'D3_TRANSPORT_REJECTED')
        self.assertNotIn('Traceback',lines[0])
        self.assertLessEqual(len(code.encode()),self.t.MAX_SSH)

    def test_bootstrap_wrong_raw_hash_and_all_caps_rejected(self):
        raw=(TOOLS/'naver_daily_current_transport_v3.py').read_bytes();body=base64.b64encode(raw).decode();sha=self.t.digest(raw)
        for wire,encoded,digest in ((self.t.PREFIX+'AA==',body,'d'*64),(self.t.PREFIX+'A'*(self.t.MAX_WIRE+1),body,sha),(self.t.PREFIX+'AA==','A'*(self.t.MAX_TRANSPORT_BASE64+1),sha)):
            with self.assertRaises(ValueError):self.t.bootstrap(wire,encoded,digest,AUTH)

    def test_actual_five_source_package_pressure_stays_within_original_caps(self):
        value=self.value();wire=self.t.encode(value)
        raw=(TOOLS/'naver_daily_current_transport_v3.py').read_bytes();body=base64.b64encode(raw).decode()
        code=self.t.bootstrap(wire,body,self.t.digest(raw),AUTH)
        self.assertLessEqual(len(json.dumps(value,separators=(',',':')).encode()),196608)
        self.assertLessEqual(len(wire.encode()),65536)
        self.assertLessEqual(len(body),32768)
        self.assertLessEqual(len(code.encode()),131072)
