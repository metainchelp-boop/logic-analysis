"""Exact new package/import/closed-output boundaries; zero host actions."""
import base64
import copy
import hashlib
import json
import lzma
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import delivery as D

import test_sources as portable_sources


def materials():
    return portable_sources.delivery_materials()


class DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.modules, cls.sources, cls.host = materials()
    def setUp(self):
        self.req = dict(version=1, action='apply', apply_id='a'*32, rollback_id='b'*32)
        self.package = dict(version=1, host=self.host.decode(), modules={k:v.decode() for k,v in self.modules.items()},
                            sources={k:v.decode() for k,v in self.sources.items()}, request=self.req)
    def result(self, action='apply'):
        req = dict(self.req, action=action)
        inner = (dict(plan_sha256='1'*64, rollback_required=True, product_export_verified=False,
                    observation=dict(status='source_limit', limit_issue='cell', exit_status=1)) if action=='apply'
                 else dict(plan_sha256='1'*64, restored=True, natural_timer_catchup_possible=True, product_export_verified=False))
        return dict(req, preparation_sha256='2'*64, result=inner,
                    original_export_success_verified=False, product_deployed=False, ads_written=False)

    def test_exact_packages_roundtrip_both_actions_with_preserved_caps(self):
        self.assertEqual((D.MAX_WIRE,D.MAX_JSON,D.MAX_BOOT,D.MAX_SSH,D.DECODER_MEMORY),
                         (102400,393216,32768,131072,33554432))
        for action in ('apply','rollback'):
            req = dict(self.req, action=action)
            wire = D.encode(self.modules,self.sources,self.host,req)
            decoded = D.decode(wire)
            self.assertEqual(decoded['request'],req)
            self.assertLessEqual(len(D.canonical(decoded)),D.MAX_JSON)
            self.assertLessEqual(len(wire),D.MAX_WIRE)
            self.assertEqual(D.validate(decoded)[1],self.modules)

    def test_request_aliases_and_overrides_refuse_before_module_loading(self):
        for changes in ({'version':True},{'action':'prepare'},{'apply_id':'0'*32},
                        {'rollback_id':'a'*32},{'apply_id':'A'*32},{'callback':'always_true'},{'path':'/tmp'}):
            value=dict(self.package,request=dict(self.req,**changes))
            with self.assertRaises(ValueError): D.run(value)

    def test_every_module_pin_refuses_tampering_before_any_exec(self):
        for name in self.modules:
            changed=copy.deepcopy(self.package);changed['modules'][name]+='\n'
            with patch('delivery.exec',create=True) as execute, self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):
                D.run(changed)
            execute.assert_not_called()

    def test_every_source_pin_and_extra_role_refuse_before_exec(self):
        for name in self.sources:
            changed=copy.deepcopy(self.package);changed['sources'][name]+='\n'
            with patch('delivery.exec',create=True) as execute, self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):
                D.run(changed)
            execute.assert_not_called()
        changed=copy.deepcopy(self.package);changed['sources']['extra']='code'
        with self.assertRaisesRegex(ValueError,'SOURCE_SHAPE'): D.validate(changed)

    def test_existing_runtime_module_cannot_be_reused_or_overwritten(self):
        sentinel=types.ModuleType('transition')
        with patch.dict(sys.modules,{'transition':sentinel}), self.assertRaisesRegex(ValueError,'MODULE_COLLISION'):
            D.run(self.package)
        self.assertNotIn('transition',sys.modules)

    def test_all_exact_modules_load_then_nonlinux_gate_refuses_without_host_calls(self):
        with patch.object(sys,'platform','darwin'), self.assertRaisesRegex(ValueError,'ENTRYPOINT_HOST'):
            D.run(self.package)
        self.assertFalse(set(D.MODULE_PINS)&set(sys.modules))

    def test_module_failure_discards_prints_and_removes_only_own_modules(self):
        import io
        output=io.StringIO()
        def broken(*args):
            print('synthetic private text'); raise RuntimeError('synthetic exception')
        with patch('delivery.exec',side_effect=broken,create=True), D.contextlib.redirect_stdout(output):
            with self.assertRaises(RuntimeError): D.run(self.package)
        self.assertEqual(output.getvalue(),'')
        self.assertFalse(set(D.MODULE_PINS)&set(sys.modules))

    def test_exact_apply_rollback_results_and_all_issues(self):
        for action in ('apply','rollback'):
            result=self.result(action)
            self.assertEqual(D.closed_result(result,dict(self.req,action=action)),result)
        for issue in D.ISSUES:
            result=self.result();result['result']['observation']['limit_issue']=issue
            D.closed_result(result,self.req)

    def test_result_provenance_extra_fields_and_false_success_rejected(self):
        variants=[]
        for key in ('invocation_id','reader','extra'):
            v=self.result();v['result']['observation'][key]='synthetic';variants.append(v)
        for key in ('original_export_success_verified','product_deployed','ads_written'):
            v=self.result();v[key]=True;variants.append(v)
        v=self.result();v['result']['observation']=dict(status='export_succeeded',limit_issue=None,exit_status=0);variants.append(v)
        v=self.result();v['result']['observation']['exit_status']=True;variants.append(v)
        v=self.result();v['result']['observation']['limit_issue']='unregistered';variants.append(v)
        v=self.result();v['rollback_id']='c'*32;variants.append(v)
        for v in variants:
            with self.assertRaises(ValueError): D.closed_result(v,self.req)

    def test_unavailable_is_not_original_export_success(self):
        result=self.result();result['result']['observation']=dict(status='diagnostic_unavailable',limit_issue=None,exit_status=0)
        self.assertFalse(D.closed_result(result,self.req)['original_export_success_verified'])

    def test_duplicate_keys_nonfinite_and_boolean_version_refused(self):
        for raw in (b'{"version":1,"version":1}',b'{"x":NaN}'):
            wire=base64.b85encode(lzma.compress(raw)).decode()
            with self.assertRaises(ValueError): D.decode(wire)
        for key in ('version','request'):
            changed=copy.deepcopy(self.package)
            if key=='version': changed[key]=True
            else:changed[key]['version']=True
            with self.assertRaises(ValueError):D.validate(changed)

    def test_compressed_trailing_truncated_and_expansion_limit_refused(self):
        encoded=lzma.compress(D.canonical(self.package))
        for body in (encoded+b'extra',encoded[:-1],lzma.compress(b'x'*(D.MAX_JSON+1))):
            with self.assertRaises(ValueError):D.decode(base64.b85encode(body).decode())
        with self.assertRaisesRegex(ValueError,'WIRE_SIZE'):D.decode('x'*(D.MAX_WIRE+1))


if __name__=='__main__':unittest.main()
