"""V22 exact learning-assets release: synthetic scope, probe, and closed transport."""
import ast
import base64
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import test_naver_preview_code_upgrade as shared

MODULE = 'naver_preview_code_upgrade_v22'
TOOLS = Path(__file__).parents[1]/'tools'

def pins(code):
    return (code.OLD_COMMIT,code.TARGET_COMMIT,code.OLD_SOURCE_SHA256,code.TARGET_SOURCE_SHA256,
        code.STORE_SHA256['old'],code.STORE_SHA256['target'],code.EXPECTED_BASELINE)

class V22ReviewTest(unittest.TestCase):
    def test_exact_reviewed_source_schema_scope_and_assets(self):
        code=shared.load(MODULE);policy=shared.load('naver_preview_code_only');rollback=shared.load('naver_preview_code_rollback')
        self.assertEqual(code.OLD_COMMIT,'83ec2d34ad1d06471f638671c283bccd58533f08')
        self.assertEqual(code.TARGET_COMMIT,'09b216f26509fed97179114ee97cb0d4169ce5f8')
        self.assertEqual(code.TARGET_SOURCE_SHA256,'92ff305fca89a636834f039676f742fc9d0d06b3ad598297102864fdc9157481')
        self.assertEqual(code.STORE_SHA256['target'],'d3f06fd855c3f3c490e09fc777bd92109fb176b7fb167c2f5f7063253cba3786')
        self.assertEqual(policy.REVIEWED_TRANSITION_V22,pins(code))
        self.assertEqual(rollback.REVIEWED_ROLLBACK_V22,pins(code)+(frozenset(code.CODE_PATHS),))
        self.assertEqual(len(code.CODE_PATHS),20);self.assertEqual(len(code.ADDED_SOURCE_PATHS),10)
        self.assertEqual(len(code.REPORT_ASSETS),13);self.assertEqual(len(code.OLD_REPORT_ASSETS),11)
        policy.require_review(code);rollback.require_review(policy,code)
        self.assertEqual(policy.code_module_name(code.TARGET_COMMIT),MODULE)

    def test_pending_or_mutated_metadata_cannot_reach_any_adapter(self):
        for change in ('OLD_COMMIT','TARGET_COMMIT','OLD_SOURCE_SHA256','TARGET_SOURCE_SHA256','EXPECTED_BASELINE',
                'store','paths','added','test','new_asset','old_asset','owner_routes','write_routes','closed_routes','sales_routes','old_app'):
            code=shared.load(MODULE);policy=shared.load('naver_preview_code_only')
            if change=='store':code.STORE_SHA256['target']='0'*64
            elif change=='paths':code.CODE_PATHS.add('naver_runtime/scheduler.py')
            elif change=='added':code.ADDED_SOURCE_PATHS|={'naver_engine/rogue.py'}
            elif change=='test':code.TEST_PATHS=frozenset({'naver_engine/tests/rogue.py'})
            elif change=='new_asset':code.REPORT_ASSETS['/naver/learning-ui.js']=(1,'0'*64,'text/javascript; charset=utf-8')
            elif change=='old_asset':code.OLD_REPORT_ASSETS['/naver/app.css']=(1,'0'*64,'text/css; charset=utf-8')
            elif change=='owner_routes':code.OWNER_ACTION_ROUTES+=('/spend/change',)
            elif change=='write_routes':code.TARGET_ACTION_ROUTES+=('/spend/change',)
            elif change=='closed_routes':code.CLOSED_LINK_ROUTES=()
            elif change=='sales_routes':code.SALES_GET_ROUTES+=('/reports/detail',)
            elif change=='old_app':code.OLD_APP=(1,'0'*64,'text/javascript; charset=utf-8')
            else:setattr(code,change,None)
            for operation in ('prepare','apply'):
                adapters=[Mock() for _ in range(4)]
                with self.subTest(change=change,operation=operation),self.assertRaisesRegex(ValueError,'NOT_REVIEWED'):
                    getattr(policy,operation)({},*adapters,code)
                self.assertTrue(all(not item.mock_calls for item in adapters))

    def test_all_previous_profiles_are_still_reviewed(self):
        policy=shared.load('naver_preview_code_only');rollback=shared.load('naver_preview_code_rollback')
        for version in range(5,22):
            code=shared.load('naver_preview_code_upgrade_v'+str(version))
            policy.require_review(code);rollback.require_review(policy,code)
            self.assertEqual(policy.code_module_name(code.TARGET_COMMIT),code.__name__)

    def test_v21_controller_functions_are_unchanged_except_new_probe_and_asset_validation(self):
        def functions(name):
            return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse((TOOLS/(name+'.py')).read_bytes()).body
                if isinstance(n,ast.FunctionDef) and n.name not in ('validate_package','probe')}
        self.assertEqual(functions(MODULE),functions('naver_preview_code_upgrade_v21'))

class V22ScopeTest(unittest.TestCase):
    def setUp(self):
        self.code=shared.load(MODULE)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.old,self.new=(Path(temp.name).resolve()/n for n in ('old','new'))
        before=shared.StoreScopeTest.SOURCE;after=before+b'\n# reviewed history capture\n'
        self.code.STORE_SHA256={'old':hashlib.sha256(before).hexdigest(),'target':hashlib.sha256(after).hexdigest()}
        compose=json.loads((Path(__file__).parent/'fixtures/v9-engine-compose-old.json').read_text())['compose'].encode()
        compose=compose.replace(b'    cpus: "0.50"\n',b'    cpus: "1.00"\n').replace(b'    mem_limit: 512m\n',b'    mem_limit: 768m\n')
        for root in (self.old,self.new):
            names={'compose.naver-relay.yml','deploy/naver-engine-backup.override.yml','Dockerfile.naver-engine',
                'Dockerfile.naver-relay','backend/requirements.txt','naver_runtime/bootstrap.py','naver_runtime/scheduler.py',
                'backend/naver_page/sales-ui.js','backend/naver_page/sales.css'}|self.code.CODE_PATHS
            for name in names:
                if root==self.old and name in self.code.ADDED_SOURCE_PATHS:continue
                file=root/name;file.parent.mkdir(parents=True,exist_ok=True)
                file.write_bytes((b'old' if root==self.old else b'new') if name in self.code.CODE_PATHS else b'unchanged')
            (root/'compose.naver-engine.yml').write_bytes(compose)
            (root/'naver_engine/store.py').write_bytes(before if root==self.old else after)
            for name in ('engine','relay'):
                body=('image: '+self.code.OLD_COMMIT).encode()
                (root/('preview-'+name+'.override.yml')).write_bytes(body if root==self.old else self.code.target_override(body,name))
        self.adapter=Mock();self.adapter.read_file.side_effect=lambda p,**kwargs:Path(p).read_bytes()

    def test_exact_twenty_paths_ten_additions_forward_and_inverse(self):
        self.code.compatible_source(self.old,self.new,self.adapter)
        self.code.compatible_inverse_source(self.new,self.old,self.adapter)

    def test_missing_or_extra_source_is_refused(self):
        for name in self.code.ADDED_SOURCE_PATHS:
            file=self.new/name;body=file.read_bytes();file.unlink()
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):
                self.code.compatible_source(self.old,self.new,self.adapter)
            file.write_bytes(body)
        extra=self.new/'naver_engine/rogue.py';extra.write_bytes(b'rogue')
        with self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):self.code.compatible_source(self.old,self.new,self.adapter)

    def test_unreviewed_sales_scheduler_schema_mode_and_secrets_changes_refuse(self):
        for name in ('backend/naver_page/sales-ui.js','backend/naver_page/sales.css','naver_runtime/scheduler.py'):
            file=self.new/name;body=file.read_bytes();file.write_bytes(b'changed')
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):
                self.code.compatible_source(self.old,self.new,self.adapter)
            file.write_bytes(body)
        file=self.new/'backend/naver_page/learning-ui.js';file.chmod(0o755)
        with self.assertRaisesRegex(ValueError,'CODE_SOURCE_MODE_CHANGED'):self.code.compatible_source(self.old,self.new,self.adapter)
        file.chmod(0o644)
        file=self.new/'naver_engine/store.py';file.write_bytes(file.read_bytes()+b'corrupt')
        with self.assertRaisesRegex(ValueError,'CODE_STORE_CHANGED'):self.code.compatible_source(self.old,self.new,self.adapter)

class V22ProbeTest(unittest.TestCase):
    def setUp(self):
        self.code=shared.load(MODULE);self.release=Mock();self.upgrade=shared.load('naver_preview_upgrade')
        self.source=self.code.OLD_COMMIT;self.corrupt=None;self.wrong_auth=None;self.seen=[]
        self.old_bodies={route:(self.code.OLD_COMMIT+route).encode() for route in self.code.OLD_REPORT_ASSETS}
        self.new_bodies={route:(self.code.TARGET_COMMIT+route).encode() for route in self.code.REPORT_ASSETS}
        for attrs,bodies in (('OLD_REPORT_ASSETS',self.old_bodies),('REPORT_ASSETS',self.new_bodies)):
            setattr(self.code,attrs,{route:(len(body),hashlib.sha256(body).hexdigest(),getattr(self.code,attrs)[route][2]) for route,body in bodies.items()})
        def request(path,route,method='GET'):
            self.seen.append(route)
            if route==self.wrong_auth:return 200,{},b''
            if route=='/_engine/health':return 200,{},b'{}'
            if route in ('/naver/','/naver/dashboard'):return 200,{'referrer-policy':'no-referrer','cache-control':'no-store'},b'verificationNotice id="s-dashboard"'
            bodies=self.old_bodies if self.source==self.code.OLD_COMMIT else self.new_bodies
            if route in bodies:
                body=bodies[route]+(b'corrupt' if route==self.corrupt else b'')
                assets=self.code.OLD_REPORT_ASSETS if self.source==self.code.OLD_COMMIT else self.code.REPORT_ASSETS
                return 200,{'content-type':assets[route][2],'cache-control':'no-store','x-content-type-options':'nosniff','referrer-policy':'no-referrer'},body
            key=route.removeprefix('/api/naver-auto')
            if key in self.code.CLOSED_LINK_ROUTES:return 403,{},b''
            return 401,{},b''
        self.release.unix_request.side_effect=request

    def test_old_and_new_have_exact_typed_assets_and_auth(self):
        for source,bodies in ((self.code.OLD_COMMIT,self.old_bodies),(self.code.TARGET_COMMIT,self.new_bodies)):
            self.source=source;self.seen.clear();self.code.probe(self.release,source,self.upgrade)
            self.assertTrue(set(bodies)<=set(self.seen))
            self.assertIn('/naver/sales-ui.js',self.seen)
            self.assertEqual('/naver/learning-ui.js' in self.seen,source==self.code.TARGET_COMMIT)

    def test_every_old_and_new_asset_corruption_refuses(self):
        for source,bodies in ((self.code.OLD_COMMIT,self.old_bodies),(self.code.TARGET_COMMIT,self.new_bodies)):
            self.source=source
            for route in bodies:
                self.corrupt=route
                with self.subTest(source=source,route=route),self.assertRaisesRegex(ValueError,'REPORT_ASSET_NOT_READY'):
                    self.code.probe(self.release,source,self.upgrade)

    def test_new_learning_and_strategy_routes_must_require_auth(self):
        self.source=self.code.TARGET_COMMIT
        for route in ('/api/naver-auto/automation?possibility_id=1&account_key=customer-1',
                '/api/naver-auto/automation/learning','/api/naver-auto/automation/plans','/api/naver-auto/reports/strategy'):
            self.wrong_auth=route
            with self.subTest(route=route),self.assertRaisesRegex(ValueError,'CODE_ROUTE_STATUS'):
                self.code.probe(self.release,self.source,self.upgrade)

class V22TransportTest(unittest.TestCase):
    def bundles(self):
        code=shared.load(MODULE)
        source=lambda n:(TOOLS/(n+'.py')).read_text()
        release=dict(baseline=code.EXPECTED_BASELINE,source_commit=code.TARGET_COMMIT,
            source_tar_gz_sha256=code.TARGET_SOURCE_SHA256,ciphertext_sha256='c'*64,run_id='12345678901',operation='code-prepare')
        common=dict(host_source=source('naver_erp_tunnel_service_install'),upgrade_source=source('naver_preview_upgrade'),
            lifecycle_source=source('naver_preview_lifecycle'),code_source=source(MODULE))
        return {
            'prepare':dict(common,package=release,source=source('naver_preview_release'),operation='preview-code-only-prepare',code_only_source=source('naver_preview_code_only')),
            'forward':dict(common,package=dict(release=release,operation_id='9'*32),source=source('naver_preview_code_only'),release_source=source('naver_preview_release'),operation='preview-code-only-upgrade',function='apply'),
            'reverse':dict(common,package=dict(release=release,operation_id='8'*32,apply_operation_id='9'*32),source=source('naver_preview_code_rollback'),code_only_source=source('naver_preview_code_only'),release_source=source('naver_preview_release'),operation='preview-code-only-rollback',function='run')}

    def test_actual_three_bundles_fit_symmetric_closed_bounds_and_roundtrip(self):
        import shlex,zlib
        encode,decode,remote=shared.ContractTest().workflow_transport()
        for kind,bundle in self.bundles().items():
            with self.subTest(kind=kind):
                raw=json.dumps(bundle).encode();self.assertLessEqual(len(raw),229376)
                wire='prepare-gzip-v1:'+base64.b64encode(gzip.compress(raw,mtime=0)).decode() if kind=='prepare' else encode(bundle)
                self.assertLessEqual(len(wire),73728)
                if kind=='prepare':
                    decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
                    unpacked=decoder.decompress(base64.b64decode(wire[len('prepare-gzip-v1:'):],validate=True),229377)
                    self.assertLessEqual(len(unpacked),229376);self.assertTrue(decoder.eof)
                    self.assertFalse(decoder.unused_data or decoder.unconsumed_tail);self.assertEqual(json.loads(unpacked),bundle)
                else:self.assertEqual(decode(wire),bundle)
                shell="export PREVIEW_OPS_B64="+shlex.quote(wire)+";\nset -eu\n/usr/bin/python3 -I -B - <<'PY'\n"+remote+'\nPY\n'
                self.assertLess(len(('/bin/bash -c '+shlex.quote(shell)).encode()),120000)
