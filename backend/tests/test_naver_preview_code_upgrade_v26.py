"""Exact provider-only V26, retaining committed config through V24 and V25."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import test_naver_preview_code_upgrade as shared
import test_naver_preview_code_upgrade_v24 as previous
import test_naver_preview_code_upgrade_v25 as prior
import test_naver_preview_code_upgrade_v23 as probe_base

MODULE = 'naver_preview_code_upgrade_v26'
TOOLS = Path(__file__).parents[1] / 'tools'
BASE = '6786c6bebe6cf2677286391342ac3dce42235d45'
encoded, sha = previous.encoded, previous.sha


def pin_synthetic(code):
    code.TARGET_COMMIT = 'f' * 40
    code.TARGET_SOURCE_SHA256 = 'e' * 64


class ConfigFixture(previous.ConfigFixture):
    def __init__(self, root):
        with patch.object(previous, 'MODULE', MODULE):
            super().__init__(root)
        pin_synthetic(self.code)
        self.bridges, self.starts, self.bridge_files, self.start_files = [], [], [], []
        for source, archive, run_id, parent in self.code.CONFIG_PRESERVATION_CHAIN:
            self.bridges.append(dict(ok=True, stage='prepared', source_commit=source,
                images={'engine':'sha256:'+'c'*64, 'relay':'sha256:'+'d'*64},
                files={str(self.paths[0]):sha(self.new[0])}, runtime_environment_preserved=True,
                config_operation_id=self.code.APPROVED_CONFIG_OPERATION_ID,
                package=dict(source_commit=source, source_tar_gz_sha256=archive,
                    baseline=self.code.EXPECTED_BASELINE, run_id=run_id)))
            self.starts.append(dict(ok=True, stage='internal_ready', source_commit=source,
                previous_commit=parent, database_policy='preserve-in-place', database_opened_by_controller=False))
            path=root/'receipts'/('preview-'+source+'.json')
            self.bridge_files.append(path);self.start_files.append(path.with_name('preview-start-'+source+'.json'))
        self.active=self.bridges[-1]
        self.sync_bridge()
        def manifest(release, source, *args, **kwargs):
            if source==self.code.CONFIG_SOURCE_COMMIT:return root/'historical-source',json.loads(self.new[1])
            if source==self.code.CONFIG_ROLLBACK_COMMIT:return root/'historical-rollback',json.loads(self.new[2])
            for value in self.bridges:
                if source==value['source_commit']:return root/'predecessor',value
            return root/'target',{}
        self.upgrade.manifest.side_effect=manifest

    def sync_bridge(self):
        for path, value in zip(self.bridge_files+self.start_files,self.bridges+self.starts):
            path.write_bytes(encoded(value))


class V26ConfigPreserveTest(previous.V24ConfigPreserveTest):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.fixture=ConfigFixture(Path(temp.name).resolve())

    def test_exact_committed_proof_preserves_current_bytes_and_original_payload(self):
        f=self.fixture;original=deepcopy(f.files)
        paths=f.paths+f.bridge_files+f.start_files
        before={path:path.read_bytes() for path in paths}
        resolved,proof=f.resolve()
        self.assertEqual(f.files,original);self.assertEqual(resolved[0]['content'].encode(),f.new[0])
        self.assertEqual(resolved[1:],f.files[1:]);self.assertEqual(len(proof[3]),4)
        self.assertEqual(before,{path:path.read_bytes() for path in paths})
        f.release.write_new.assert_not_called();f.release.command.assert_not_called()
        self.assertEqual(f.upgrade.manifest.call_count,5)

    def test_both_bridges_require_exact_source_archive_run_and_current_env_proof(self):
        f=self.fixture
        for index in range(2):
            for key,value in (('runtime_environment_preserved',False),('config_operation_id','f'*32),('source_commit','e'*40)):
                original=f.bridges[index][key];f.bridges[index][key]=value;f.sync_bridge()
                with self.subTest(index=index,key=key),self.assertRaisesRegex(ValueError,'CONFIG_PRESERVE_PROOF'):f.resolve()
                f.bridges[index][key]=original;f.sync_bridge()
            for key,value in (('run_id','12345678901'),('baseline','e'*64),('source_tar_gz_sha256','f'*64),('source_commit','e'*40)):
                original=f.bridges[index]['package'][key];f.bridges[index]['package'][key]=value;f.sync_bridge()
                with self.subTest(index=index,key=key),self.assertRaisesRegex(ValueError,'CONFIG_PRESERVE_PROOF'):f.resolve()
                f.bridges[index]['package'][key]=original;f.sync_bridge()
            key=str(f.paths[0]);original=f.bridges[index]['files'][key];f.bridges[index]['files'][key]=sha(f.old[0]);f.sync_bridge()
            with self.subTest(index=index,env=True),self.assertRaisesRegex(ValueError,'CONFIG_PRESERVE_PROOF'):f.resolve()
            f.bridges[index]['files'][key]=original;f.sync_bridge()

    def test_both_start_receipts_require_exact_predecessor_and_preserved_database(self):
        f=self.fixture
        for index in range(2):
            for key,value in (('previous_commit','f'*40),('database_policy','restore'),('database_opened_by_controller',True),('ok',False)):
                original=f.starts[index][key];f.starts[index][key]=value;f.sync_bridge()
                with self.subTest(index=index,key=key),self.assertRaisesRegex(ValueError,'CONFIG_PRESERVE_PROOF'):f.resolve()
                f.starts[index][key]=original;f.sync_bridge()

    def test_active_state_must_be_exact_last_bridge_and_each_proof_body_is_postflight_bound(self):
        f=self.fixture;original=f.active
        f.active=deepcopy(original);f.active['images']['engine']='sha256:'+'f'*64
        with self.assertRaisesRegex(ValueError,'CONFIG_PRESERVE_PROOF'):f.resolve()
        f.active=original
        _,before=f.resolve()
        f.starts[0]['operation_id']='c'*32;f.sync_bridge();_,after=f.resolve()
        self.assertNotEqual(before,after)


class V26PrepareTest(previous.V24PrepareTest):
    def setUp(self):
        with patch.object(previous,'ConfigFixture',ConfigFixture):super().setUp()

    def test_either_bridge_drift_during_build_refuses_without_writing_current_files(self):
        f=self.fixture;before={path:path.read_bytes() for path in f.paths}
        def mutate():f.starts[0]['operation_id']='d'*32;f.sync_bridge()
        self.mutate=mutate
        with self.assertRaisesRegex(ValueError,'CONFIG_PRESERVE_DRIFT'):self.prepare()
        self.assertEqual(before,{path:path.read_bytes() for path in f.paths})
        self.assertFalse((f.release.ROOT/'receipts'/('preview-'+f.code.TARGET_COMMIT+'.json')).exists())


class V26ScopeTest(unittest.TestCase):
    def setUp(self):
        with patch.object(previous,'MODULE',MODULE):
            fixture=previous.V24ScopeTest();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.code,self.old,self.new,self.adapter=fixture.code,fixture.old,fixture.new,fixture.adapter
        pin_synthetic(self.code)
        for name in ('engine','relay'):
            (self.new/('preview-'+name+'.override.yml')).write_bytes(('image: '+self.code.TARGET_COMMIT).encode())

    def test_only_provider_changes_with_exact_inverse_and_unchanged_store(self):
        self.code.compatible_source(self.old,self.new,self.adapter)
        self.code.compatible_inverse_source(self.new,self.old,self.adapter)
        self.assertEqual(self.code.CODE_PATHS,{'naver_runtime/claude_provider.py'})
        self.assertEqual(self.code.ADDED_SOURCE_PATHS,frozenset())

    def test_unrelated_changes_addition_removal_or_store_change_are_refused(self):
        for relative in ('naver_runtime/learning_jobs.py','naver_engine/web.py','backend/naver_page/report-ui.js'):
            path=self.new/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'rogue')
            with self.subTest(path=relative),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):self.code.compatible_source(self.old,self.new,self.adapter)
            path.unlink()
        path=self.new/'naver_runtime/claude_provider.py';before=path.read_bytes();path.unlink()
        with self.assertRaisesRegex(ValueError,'CODE_SOURCE_REMOVED'):self.code.compatible_source(self.old,self.new,self.adapter)
        path.write_bytes(before)
        path=self.new/'naver_engine/store.py';before=path.read_bytes();path.write_bytes(before+b'\n')
        with self.assertRaisesRegex(ValueError,'CODE_STORE_CHANGED'):self.code.compatible_source(self.old,self.new,self.adapter)


class V26ProfileTest(unittest.TestCase):
    def test_pending_pins_fail_before_host_actions(self):
        for name in ('TARGET_COMMIT','TARGET_SOURCE_SHA256'):
            code=shared.load(MODULE);policy=shared.load('naver_preview_code_only');adapters=[Mock() for _ in range(4)]
            setattr(code,name,None)
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'CODE_ONLY_RELEASE_NOT_REVIEWED'):
                policy.prepare({},*adapters,code,approved_config_operation_id=code.APPROVED_CONFIG_OPERATION_ID)
            self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_reviewed_selector_scope_config_chain_and_exact_inverse(self):
        code=shared.load(MODULE);pin_synthetic(code);policy=shared.load('naver_preview_code_only');rollback=shared.load('naver_preview_code_rollback')
        policy.REVIEWED_TRANSITION_V26=previous.pins(code)
        reverse=previous.pins(code)+(frozenset(code.CODE_PATHS),)
        rollback.REVIEWED_ROLLBACK_V26=reverse;rollback.REVIEWED_ROLLBACKS|=frozenset({reverse})
        policy.require_review(code);rollback.require_review(policy,code)
        self.assertEqual(policy.code_module_name(code.TARGET_COMMIT),MODULE)
        adapters=[Mock() for _ in range(4)];code.prepare=Mock(return_value={'ok':True})
        self.assertTrue(policy.prepare({},*adapters,code,approved_config_operation_id=code.APPROVED_CONFIG_OPERATION_ID)['ok'])
        for name,value in (('CONFIG_PREDECESSOR_PREPARE_RUN','12345678901'),('CONFIG_PRESERVATION_CHAIN',()),('ADDED_SOURCE_PATHS',frozenset({'rogue'})),('CONFIG_SETTINGS',{})):
            original=getattr(code,name);setattr(code,name,value)
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'CODE_ONLY_RELEASE_NOT_REVIEWED'):policy.require_review(code)
            setattr(code,name,original)
        with self.assertRaisesRegex(ValueError,'CONFIG_PRESERVE_NOT_APPROVED'):policy.prepare({},*adapters,code,approved_config_operation_id='f'*32)

    def test_old_profiles_and_live_config_assets_store_remain_unchanged(self):
        policy=shared.load('naver_preview_code_only');rollback=shared.load('naver_preview_code_rollback')
        for version in range(5,26):
            code=shared.load('naver_preview_code_upgrade_v'+str(version));policy.require_review(code)
            if version != 25:rollback.require_review(policy,code)
        code=shared.load(MODULE);old=shared.load('naver_preview_code_upgrade_v25')
        self.assertEqual(code.OLD_COMMIT,old.TARGET_COMMIT);self.assertEqual(code.OLD_SOURCE_SHA256,old.TARGET_SOURCE_SHA256)
        self.assertEqual(code.STORE_SHA256['old'],code.STORE_SHA256['target']);self.assertEqual(code.STORE_SHA256['old'],old.STORE_SHA256['target'])
        self.assertEqual(code.REPORT_ASSETS,old.REPORT_ASSETS);self.assertEqual(code.OLD_REPORT_ASSETS,old.REPORT_ASSETS)
        self.assertEqual(code.CONFIG_SETTINGS,old.CONFIG_SETTINGS);self.assertEqual(code.CONFIG_SETTINGS['NAVER_CLAUDE_MONTHLY_CAP_USD'],'unlimited')


class V26FrozenTest(unittest.TestCase):
    def test_entire_shared_controller_ast_and_v25_controller_bytes_are_preserved(self):
        from test_naver_preview_loading_v8_preservation import strip_v26_additions,canonical
        for name in ('naver_preview_code_only','naver_preview_code_rollback'):
            before=subprocess.check_output(['git','show',BASE+':backend/tools/'+name+'.py'],cwd=TOOLS)
            self.assertEqual(canonical(ast.parse(before)),canonical(strip_v26_additions(ast.parse((TOOLS/(name+'.py')).read_bytes()))),name)
        for version in (24,25):
            name='naver_preview_code_upgrade_v'+str(version)+'.py'
            self.assertEqual(subprocess.check_output(['git','show',BASE+':backend/tools/'+name],cwd=TOOLS),(TOOLS/name).read_bytes())

    def test_v26_scope_selector_config_and_inverse_mutations_do_not_normalize(self):
        from test_naver_preview_loading_v8_preservation import strip_v26_additions,canonical
        for name in ('naver_preview_code_only','naver_preview_code_rollback'):
            tree=ast.parse((TOOLS/(name+'.py')).read_bytes());changed=False
            for node in ast.walk(tree):
                if isinstance(node,ast.If) and '_V26' in ast.unparse(node.test):node.body=[ast.Pass()];changed=True;break
            self.assertTrue(changed)
            before=subprocess.check_output(['git','show',BASE+':backend/tools/'+name+'.py'],cwd=TOOLS)
            self.assertNotEqual(canonical(ast.parse(before)),canonical(strip_v26_additions(tree)))


class V26TransportTest(prior.V25TransportTest):
    def test_v24_v25_v26_full_bundle_roundtrip_retains_bounds_and_ast(self):
        import base64,gzip
        from test_naver_preview_loading_v8_preservation import canonical
        compact=self.compactor();encode,decode,_=shared.ContractTest().workflow_transport()
        for version in (24,25,26):
            for kind,original in self.bundles(version).items():
                bundle=compact(original)
                for key in original:
                    if key=='source' or key.endswith('_source'):self.assertEqual(canonical(ast.parse(original[key])),canonical(ast.parse(bundle[key])))
                    else:self.assertEqual(bundle[key],original[key])
                raw=json.dumps(bundle).encode()
                wire='prepare-gzip-v1:'+base64.b64encode(gzip.compress(raw,mtime=0)).decode() if kind=='prepare' else encode(bundle)
                with self.subTest(version=version,kind=kind):
                    self.assertLessEqual(len(raw),229376);self.assertLessEqual(len(wire),73728)
                    restored=json.loads(gzip.decompress(base64.b64decode(wire.removeprefix('prepare-gzip-v1:')))) if kind=='prepare' else decode(wire)
                    self.assertEqual(restored,bundle)


class V26ProbeTest(probe_base.V23ProbeTest):
    def setUp(self):
        with patch.object(probe_base,'MODULE',MODULE):super().setUp()
        pin_synthetic(self.code);self.source=self.code.TARGET_COMMIT
        self.job_status=401;self.jobs='/api/naver-auto/reports/strategy/jobs?job_id='+'0'*32
        original=self.release.unix_request.side_effect
        def request(path,route,method='GET'):
            if route==self.jobs:self.seen.append(route);return self.job_status,{},b''
            return original(path,route,method)
        self.release.unix_request.side_effect=request

    def test_both_target_and_exact_live_rollback_require_jobs_auth(self):
        for source in (self.code.OLD_COMMIT,self.code.TARGET_COMMIT):
            self.source=source;self.seen.clear();self.code.probe(self.release,source,self.upgrade);self.assertIn(self.jobs,self.seen)
            self.job_status=403
            with self.assertRaisesRegex(ValueError,'CODE_ROUTE_STATUS'):self.code.probe(self.release,source,self.upgrade)
            self.job_status=401


class V26WorkflowOptionTest(unittest.TestCase):
    def test_actual_builder_retains_original_package_and_exact_config_option(self):
        download,bundle,original=previous.V24WorkflowOptionTest().builder(MODULE,'74c912dddf824fae99012849bc4c19a5')
        self.assertIsNotNone(bundle);self.assertEqual(download.call_args.args[0],original)
        self.assertEqual(bundle['approved_config_operation_id'],'74c912dddf824fae99012849bc4c19a5')
        self.assertNotIn('approved_config_operation_id',bundle['package'])
        for source,identity in ((MODULE,'f'*32),('naver_preview_code_upgrade_v23','74c912dddf824fae99012849bc4c19a5')):
            download,bundle,_=previous.V24WorkflowOptionTest().builder(source,identity)
            download.assert_not_called();self.assertIsNone(bundle)


class V26IncomingReceiverTest(prior.V25IncomingReceiverTest):
    def test_actual_receiver_only_accepts_exact_v26_config_identity(self):
        status,output,calls=self.receiver(26,'74c912dddf824fae99012849bc4c19a5')
        self.assertEqual(status,0);self.assertEqual(output,'PREVIEW_INCOMING_READY\n');self.assertEqual(len(calls),3)
        status,output,calls=self.receiver(26,'f'*32)
        self.assertEqual(status,1);self.assertEqual(output,'PREVIEW_INCOMING_REFUSED\n');self.assertEqual(calls,[])


class V26StringTransportTest(unittest.TestCase):
    def test_literal_source_spelling_is_exact_even_with_multiline_raw_bytes_unicode_and_fstrings(self):
        import io,tokenize
        compact=prior.V25TransportTest().compactor()
        source='''# remove outside
if True:
    raw = r"# kept\\d"
    text = """# kept

  keep indent
"""
    value = b"\\x00#kept"
    korean = '숫자 근거'
    combined = f"""# literal {1 + 2}

  keep fstring line
"""
'''
        literal=lambda raw:tuple((token.type,token.string) for token in tokenize.generate_tokens(io.StringIO(raw).readline)
            if token.type==tokenize.STRING or tokenize.tok_name[token.type].startswith('FSTRING'))
        after=compact({'source':source})['source']
        self.assertEqual(literal(source),literal(after));self.assertNotIn('# remove outside',after)
        self.assertEqual(ast.dump(ast.parse(source),include_attributes=False),ast.dump(ast.parse(after),include_attributes=False))

    def test_quote_spelling_change_is_refused_even_when_entire_ast_is_identical(self):
        import tokenize
        compact=prior.V25TransportTest().compactor();original=tokenize.untokenize
        def changed(tokens):return original(tokens).replace("'same text'",'"same text"')
        with patch.object(tokenize,'untokenize',side_effect=changed),self.assertRaisesRegex(ValueError,'SOURCE_STRING_MISMATCH'):
            compact({'source':"value = 'same text'\n"})
