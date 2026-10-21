"""New receiver/registration cases only; synthetic metadata, zero host actions."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import delivery as D
import strict_receiver as R
import test_delivery as fixtures
import test_sources as portable_sources


class StrictReceiverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules, cls.sources, cls.host = fixtures.materials()
        cls.renderer = portable_sources.renderer_source()
        cls.registered = R.register_release(delivery_source=cls.host,
            renderer_source=cls.renderer, modules=cls.modules, sources=cls.sources)

    def setUp(self):
        self.req = dict(version=1, action='apply', apply_id='a'*32, rollback_id='b'*32)
        self.expected = dict(repository=R.REPOSITORY, ops_head='1'*40,
            native_run_id=101, native_attempt=1, native_workflow_id=201,
            native_workflow_path='.github/workflows/native.yml', native_event='push',
            workflow_run_id=102, workflow_attempt=1, workflow_id=202,
            workflow_path='.github/workflows/diagnostic.yml')
        self.native = dict(repository=R.REPOSITORY, id=101, run_attempt=1, head_sha='1'*40,
            workflow_id=201, path='.github/workflows/native.yml', event='push',
            status='completed', conclusion='success')
        self.workflow = dict(self.native, id=102, workflow_id=202,
            path='.github/workflows/diagnostic.yml', event='workflow_dispatch')
        self.refresh_input()

    def refresh_input(self):
        self.input = R.fixed_input_receipt(registration=self.registered,
            expected_request=self.req, expected=self.expected)

    def metadata(self):
        return dict(registration=self.registered, expected_request=self.req,
            expected=self.expected, input_receipt=self.input,
            observed_native=self.native, observed_workflow=self.workflow)

    def transport(self, action='apply', issue='rows', status='source_limit'):
        inner = (dict(plan_sha256='2'*64, rollback_required=True, product_export_verified=False,
            observation=dict(status=status, limit_issue=issue,
                             exit_status=1 if status=='source_limit' else 0)) if action=='apply'
            else dict(plan_sha256='2'*64, restored=True,
                      natural_timer_catchup_possible=True, product_export_verified=False))
        public = dict(self.req, action=action, preparation_sha256='3'*64, result=inner,
            original_export_success_verified=False, product_deployed=False, ads_written=False)
        return dict(version=1, transport=R.TRANSPORT, transport_ok=True, phase='complete',
            error_code=None, result=public, paired_cleanup_may_be_required=action=='apply')

    def raw(self, value): return R.MARKER + R.canonical(value) + b'\n'

    def receive(self, value, **changes):
        args = self.metadata(); args.update(changes)
        return R.receive(self.raw(value), **args)

    def refusal(self, phase='entrypoint', code='CURRENT_CHANGED'):
        return dict(version=1, transport=R.TRANSPORT, transport_ok=False, phase=phase,
                    error_code=code, result=None, paired_cleanup_may_be_required=True)

    def test_exact_registration_rejects_changed_host_renderer_each_module_source(self):
        base=dict(delivery_source=self.host, renderer_source=self.renderer,
                  modules=self.modules, sources=self.sources)
        for role in ('delivery_source','renderer_source'):
            changed=dict(base);changed[role]+=b'\n'
            with self.assertRaisesRegex(R.Invalid,'REGISTRATION_SOURCE'):R.register_release(**changed)
        for category in ('modules','sources'):
            for name in base[category]:
                changed=dict(base);changed[category]=dict(base[category]);changed[category][name]+=b'\n'
                with self.assertRaisesRegex(R.Invalid,'REGISTRATION_SOURCE'):R.register_release(**changed)
        changed=dict(base,modules=dict(self.modules,extra=b'x'))
        with self.assertRaisesRegex(R.Invalid,'REGISTRATION_SHAPE'):R.register_release(**changed)

    def test_fixed_registration_cannot_be_replaced_with_self_consistent_other_hashes(self):
        reg=copy.deepcopy(self.registered);reg['delivery_sha256']='9'*64
        with self.assertRaisesRegex(R.Invalid,'REGISTRATION_CHANGED'):
            self.receive(self.transport(),registration=reg)
        reg=copy.deepcopy(self.registered);reg['version']=True
        with self.assertRaises(R.Invalid):self.receive(self.transport(),registration=reg)

    def test_pre_dispatch_input_has_no_invented_run_or_completion_claim(self):
        fixed={k:v for k,v in self.expected.items() if k in R.FIXED_INPUT_KEYS}
        result=R.fixed_input_receipt(registration=self.registered,expected_request=self.req,expected=fixed)
        self.assertEqual(result,self.input)
        self.assertEqual(result['stage'],'fixed_input_only')
        self.assertNotIn('workflow_run_id',result['inputs'])
        self.assertNotIn('workflow_attempt',result['inputs'])
        with self.assertRaisesRegex(R.Invalid,'EXECUTION_EXPECTED'):
            self.receive(self.transport(),expected=fixed)

    def test_future_run_ids_without_completed_native_and_dispatch_metadata_refuse(self):
        for which in ('observed_native','observed_workflow'):
            for observed in (None,{},dict(self.native if which=='observed_native' else self.workflow,
                                         status='in_progress',conclusion=None)):
                with self.assertRaisesRegex(R.Invalid,'EXECUTION_METADATA'):
                    self.receive(self.transport(),**{which:observed})

    def test_every_selected_run_field_and_alias_mismatch_refuses(self):
        for which, original in (('observed_native',self.native),('observed_workflow',self.workflow)):
            for key in original:
                value=False if type(original[key]) is int else 'unmatched'
                changed=dict(original,**{key:value})
                with self.assertRaisesRegex(R.Invalid,'EXECUTION_METADATA'):
                    self.receive(self.transport(),**{which:changed})
            changed=dict(original,extra='rejected')
            with self.assertRaises(R.Invalid):self.receive(self.transport(),**{which:changed})

    def test_expected_wrong_repository_path_head_alias_duplicate_or_rerun_refuse(self):
        changes=({'repository':'other/repo'},{'workflow_path':'../diagnostic.yml'},
            {'ops_head':'A'*40},{'ops_head':'0'*40},{'native_run_id':True},
            {'native_attempt':1.0},{'workflow_run_id':101},{'workflow_attempt':2},
            {'native_event':'schedule'},{'extra':'no'})
        for change in changes:
            with self.assertRaisesRegex(R.Invalid,'EXECUTION_EXPECTED'):
                self.receive(self.transport(),expected=dict(self.expected,**change))

    def test_fixed_input_receipt_binds_request_source_native_and_workflow_selection(self):
        variants=[]
        for key in ('request_sha256','release_sha256'):
            value=copy.deepcopy(self.input);value[key]='4'*64;variants.append(value)
        for key in self.input['inputs']:
            value=copy.deepcopy(self.input);value['inputs'][key]='changed';variants.append(value)
        value=copy.deepcopy(self.input);value['version']=True;variants.append(value)
        value=copy.deepcopy(self.input);value['extra']=1;variants.append(value)
        for value in variants:
            with self.assertRaisesRegex(R.Invalid,'EXECUTION_INPUT'):
                self.receive(self.transport(),input_receipt=value)

    def test_all_six_source_limit_issues_are_diagnostic_only(self):
        for issue in D.ISSUES:
            receipt=self.receive(self.transport(issue=issue))
            self.assertEqual(receipt['diagnostic_status'],'source_limit')
            self.assertEqual(receipt['limit_issue'],issue)
            self.assertEqual(receipt['pair_provenance'],'result_and_fixed_input_receipt')
            self.assertTrue(receipt['paired_cleanup_may_be_required'])
            for key in ('original_export_success_verified','product_deployed','ads_written'):
                self.assertIs(receipt[key],False)

    def test_unavailable_and_paired_rollback_do_not_become_export_success(self):
        receipt=self.receive(self.transport(status='diagnostic_unavailable',issue=None))
        self.assertEqual(receipt['diagnostic_status'],'diagnostic_unavailable')
        self.assertIsNone(receipt['limit_issue']);self.assertFalse(receipt['original_export_success_verified'])
        self.req['action']='rollback';self.refresh_input()
        receipt=self.receive(self.transport(action='rollback'))
        self.assertEqual(receipt['diagnostic_status'],'diagnostic_restored')
        self.assertFalse(receipt['paired_cleanup_may_be_required'])
        self.assertFalse(receipt['original_export_success_verified'])

    def test_failure_has_fixed_input_only_pair_provenance_and_retains_cleanup_uncertainty(self):
        for phase,codes in (('decode',R.DECODE_ERRORS),('load',R.LOAD_ERRORS),
                            ('entrypoint',R.COMMON_ERRORS|R.DELIVERY_ERRORS|R.MODULE_REFUSALS)):
            for code in codes:
                receipt=self.receive(self.refusal(phase,code))
                self.assertEqual(receipt['diagnostic_status'],'transport_refused')
                self.assertEqual(receipt['pair_provenance'],'fixed_input_receipt_only')
                self.assertTrue(receipt['paired_cleanup_may_be_required'])
                self.assertIsNone(receipt['public_result']);self.assertIsNone(receipt['limit_issue'])

    def test_extra_lines_duplicate_results_crlf_marker_and_whitespace_refuse(self):
        raw=self.raw(self.transport())
        for bad in (raw+raw,b'prefix\n'+raw,raw+b'\n',raw.replace(b'\n',b'\r\n'),
                    b' '+raw,raw+b'trailing',raw[:-1]+b' \n'):
            with self.assertRaises(R.Invalid):R.receive(bad,**self.metadata())
        self.assertTrue(R.receive(raw[:-1],**self.metadata())['transport_ok'])

    def test_duplicate_keys_nonfinite_bad_utf8_and_nonobject_refuse_without_echo(self):
        for body in (b'{"version":1,"version":1}',b'{"private-marker":NaN}',
                     b'\xff',b'[]',b'null',b'"private-marker"'):
            with self.assertRaises(R.Invalid) as error:
                R.receive(R.MARKER+body+b'\n',**self.metadata())
            self.assertNotIn('private-marker',str(error.exception))

    def test_unknown_phase_error_status_extra_and_alias_types_refuse(self):
        variants=[]
        for key,value in (('version',True),('transport_ok',1),('phase','unknown'),
                          ('paired_cleanup_may_be_required',1),('extra','private-marker')):
            variants.append(dict(self.transport(),**{key:value}))
        variants.extend((self.refusal('complete','HOST_REFUSED'),
            self.refusal('decode','ENTRYPOINT_HOST'),self.refusal('entrypoint','PRIVATE_TEXT')))
        variants.append(dict(self.refusal(),result={}))
        variants.append(dict(self.refusal(),paired_cleanup_may_be_required=False))
        value=self.transport();value['result']['result']['observation']['status']='export_succeeded';variants.append(value)
        value=self.transport();value['result']['result']['observation']['exit_status']=True;variants.append(value)
        value=self.transport();value['result']['result']['observation']['invocation_id']='private-marker';variants.append(value)
        for value in variants:
            with self.assertRaisesRegex(R.Invalid,'RECEIVER_RESULT'):self.receive(value)

    def test_success_action_pair_and_false_success_flags_are_strict(self):
        variants=[]
        for key,value in (('apply_id','c'*32),('rollback_id','c'*32),('action','rollback'),
                          ('original_export_success_verified',True),('ads_written',True),('product_deployed',True)):
            changed=self.transport();changed['result'][key]=value;variants.append(changed)
        for changed in variants:
            with self.assertRaisesRegex(R.Invalid,'RECEIVER_RESULT'):self.receive(changed)

    def test_size_type_and_private_payload_are_never_retained(self):
        for raw in ('text',bytearray(b'x'),b'',R.MARKER+b'x'*(R.MAX_RESULT+1)):
            with self.assertRaisesRegex(R.Invalid,'RECEIVER_SIZE'):R.receive(raw,**self.metadata())
        receipt=self.receive(self.transport())
        self.assertNotIn('raw',receipt);self.assertNotIn('stdout',receipt)
        self.assertLessEqual(len(R.canonical(receipt)),R.MAX_RECEIPT)
        mutated=self.transport();mutated['result']['extra']='private-marker'
        with self.assertRaises(R.Invalid) as error:self.receive(mutated)
        self.assertNotIn('private-marker',str(error.exception))


if __name__=='__main__': unittest.main()
