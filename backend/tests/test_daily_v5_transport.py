"""Actual authenticated five-source bundle; no SSH, DB or external operations."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from daily_v5_support import AUTH, SELF, TOOLS, failure, package, pin_transport, transport

class TransportTests(unittest.TestCase):
    def test_unknown_execution_and_native_identity_reject_before_file_io(self):
        t=transport()
        with patch.object(Path,'read_bytes',side_effect=AssertionError('IO')):
            with self.assertRaisesRegex(ValueError,'^D3_TRANSPORT_UNPINNED$'): t.bundle({},TOOLS)
        with self.assertRaisesRegex(ValueError,'^D3_TRANSPORT_UNPINNED$'):
            t.bootstrap(t.PREFIX,'',SELF,None)

    def test_actual_raw_compact_bundle_binding_and_roundtrip(self):
        t=pin_transport(transport());value=t.bundle(package(),TOOLS)
        self.assertEqual(t.decode(t.encode(value)),value)
        m=t.modules(value)
        self.assertEqual(m['controller'].EXECUTION_PINS,value['package']['evidence'])
        self.assertEqual((len(m['reader'].SOURCE_FILES),len(m['reader'].IMAGE_SOURCE_FILES)),(163,106))
        self.assertTrue(all(v is None for v in m['reader'].EXECUTION_PINS.values()))
        self.assertTrue(callable(m['reader'].verify_host_source))
        self.assertLessEqual(len(json.dumps(value,separators=(',',':')).encode()),t.MAX_JSON)

    def test_each_raw_body_is_checked_before_compaction_or_execution(self):
        t=pin_transport(transport())
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for key,name in t.SOURCE_FILES.items(): (root/name).write_bytes((TOOLS/name).read_bytes())
            for key,name in t.SOURCE_FILES.items():
                old=(root/name).read_bytes();(root/name).write_bytes(old+b'\n')
                with self.subTest(key=key),self.assertRaisesRegex(ValueError,'^D3_TRANSPORT_SOURCE$'): t.bundle(package(),root)
                (root/name).write_bytes(old)

    def test_closed_stage_shape_unknown_mismatch_and_raw_fields_rejected(self):
        t=pin_transport(transport())
        for stage in t.READER_STAGES: self.assertEqual(t.project_result(failure(stage=stage,reason='D3_UNCLASSIFIED'),None)['failure']['reader_stage'],stage)
        for change in [dict(reader_stage='private raw text'),dict(reader_stage=True),dict(primary_code='D3_READER_TIMEOUT',reader_stage='SOURCE'),dict(reader_reason='private SQL'),dict(reader_reason=[]),dict(reader_reason=None),dict(extra='private')]:
            row=failure(stage='DB_QUERY',reason='D3_UNCLASSIFIED');row['failure'].update(change)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'^D3_TRANSPORT_RESULT$'):t.project_result(row,None)
        for code in ('D3_HOST_SOURCE','D3_READER_TIMEOUT','D3_READER_COMMAND','D3_READER_JSON','D3_READER_VALIDATION'):
            self.assertEqual(t.project_result(failure(code),None)['failure']['primary_code'],code)

    def test_bootstrap_executes_the_verified_snapshot_without_reopening_path(self):
        t=pin_transport(transport());source=(TOOLS/'naver_daily_current_transport_v5.py').read_bytes()
        code=t.bootstrap(t.encode(t.bundle(package(),TOOLS)),base64.b64encode(source).decode(),hashlib.sha256(source).hexdigest(),AUTH)
        self.assertNotIn('read_bytes',code);self.assertNotIn('open(',code)
        self.assertIn('exec(compile(raw,',code)
        self.assertLessEqual(len(code.encode()),t.MAX_SSH)
        self.assertNotIn('.Config.Env',code)

    def test_envelope_exacttypes_event_and_oldmode_never_fall_back(self):
        t=pin_transport(transport())
        for key,value in [('mode','daily-current-source-4d-v4-fixed-0710'),('native_run_id',38307879311)]:
            bad=copy.deepcopy(package());bad[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'^D3_TRANSPORT_PACKAGE$'):t.validate_package(bad)
        bad=copy.deepcopy(package());bad['event_selector']['numeric_revision']=True
        with self.assertRaisesRegex(ValueError,'^D3_TRANSPORT_PACKAGE$'):t.validate_package(bad)

    def test_wire_extra_trailing_data_and_bad_prefix_rejected(self):
        t=pin_transport(transport());wire=t.encode(t.bundle(package(),TOOLS))
        for bad in ('daily-current-source-4d-v4-xz:'+wire[len(t.PREFIX):],wire+'secret'):
            with self.assertRaisesRegex(ValueError,'^D3_TRANSPORT_ENCODING$'):t.decode(bad)

    def test_transport_failed_outer_execution_has_fixed_null_stage_and_no_exception_text(self):
        t=pin_transport(transport());value=t.bundle(package(),TOOLS)
        original=t.modules
        def modules(v):
            m=original(v)
            def fail(*a,**k):raise RuntimeError('private exception')
            m['controller'].run=fail
            return m
        with patch.object(t,'modules',side_effect=modules):row=t.execute(value)
        self.assertEqual(row['failure'],dict(primary_code='D3_INTERNAL',post_engine_code=None,
            post_legacy_code=None,post_proof_code=None,reader_stage=None,reader_reason=None))
        self.assertNotIn('private',json.dumps(row))
