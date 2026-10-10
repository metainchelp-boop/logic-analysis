"""V21 pending/exact sales read release; local synthetic files, adapters and transport only."""
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import test_naver_preview_code_upgrade as shared

MODULE = 'naver_preview_code_upgrade_v21'
OLD = '27ed22b1e77213912db3750ddeb91d046fa770f5'
OLD_ARCHIVE = '3dd748de6c2f737af6c5cdf9e8b94a073329f0dcc2a2bf91ff7e180e35da80fd'
OLD_STORE = 'aa39afff20c48225d70e80a899234c68b862aeaa53fae43c2e0769346f3b6d62'
TARGET = '83ec2d34ad1d06471f638671c283bccd58533f08'
ARCHIVE = 'bc369f7c5cf7da96ffe33175efd6284247888786c8a769a878694f2050c785fc'
STORE = 'fe85c4df66addd727298e0b1406876c43bd84b727368203c791570590deefa4c'
HOST = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
PATHS = frozenset({'backend/app/naver_auto/org_snapshot.py','backend/app/naver_auto/scope.py',
    'backend/naver_page/app.js','backend/naver_page/index.html','backend/naver_page/sales-ui.js',
    'backend/naver_page/sales.css','naver_engine/fields.py','naver_engine/store.py','naver_engine/web.py','naver_engine/sales_views.py'})
ADDED = frozenset({'backend/naver_page/sales-ui.js','backend/naver_page/sales.css','naver_engine/sales_views.py'})
TOOLS = Path(__file__).parents[1]/'tools'

def pins(code):
    return (code.OLD_COMMIT, code.TARGET_COMMIT, code.OLD_SOURCE_SHA256, code.TARGET_SOURCE_SHA256,
            code.STORE_SHA256['old'], code.STORE_SHA256['target'], code.EXPECTED_BASELINE)

def configured():
    code, policy = shared.sealed_code(MODULE), shared.load('naver_preview_code_only')
    policy.REVIEWED_TRANSITION_V21 = pins(code)
    policy.REVIEWED_OLD_APP_V21 = code.OLD_APP
    policy.REVIEWED_ASSETS_V21 = dict(code.REPORT_ASSETS)
    policy.REVIEWED_REPORT_UI_V21 = code.OLD_REPORT_UI
    return code, policy

class V21PinsTest(unittest.TestCase):
    def test_final_exact_source_archive_store_and_assets_are_reviewed(self):
        code,policy=shared.load(MODULE),shared.load('naver_preview_code_only')
        rollback=shared.load('naver_preview_code_rollback')
        expected=(OLD,TARGET,OLD_ARCHIVE,ARCHIVE,OLD_STORE,STORE,HOST)
        self.assertEqual(pins(code),expected);self.assertEqual(policy.REVIEWED_TRANSITION_V21,expected)
        self.assertEqual(rollback.REVIEWED_ROLLBACK_V21,expected+(PATHS,))
        self.assertIn(rollback.REVIEWED_ROLLBACK_V21,rollback.REVIEWED_ROLLBACKS)
        self.assertEqual(policy.REVIEWED_ASSETS_V21,code.REPORT_ASSETS)
        self.assertEqual(code.CODE_PATHS,PATHS);self.assertEqual(code.ADDED_SOURCE_PATHS,ADDED)
        policy.require_review(code);rollback.require_review(policy,code)
        self.assertEqual(policy.code_module_name(TARGET),MODULE)

    def test_pending_pins_and_exact_ten_runtime_paths_have_no_authority(self):
        code, policy = shared.load(MODULE), shared.load('naver_preview_code_only')
        rollback = shared.load('naver_preview_code_rollback')
        final = pins(code)
        code.TARGET_COMMIT = code.TARGET_SOURCE_SHA256 = code.STORE_SHA256['target'] = None
        policy.REVIEWED_TRANSITION_V21 = pins(code)
        rollback.REVIEWED_ROLLBACKS -= frozenset({rollback.REVIEWED_ROLLBACK_V21})
        rollback.REVIEWED_ROLLBACK_V21 = pins(code)+(PATHS,)
        for route in ('/naver/app.js','/naver/sales-ui.js','/naver/sales.css'):
            code.REPORT_ASSETS[route] = (None,None,code.REPORT_ASSETS[route][2])
        policy.REVIEWED_ASSETS_V21 = dict(code.REPORT_ASSETS)
        self.assertEqual(final, (OLD,TARGET,OLD_ARCHIVE,ARCHIVE,OLD_STORE,STORE,HOST))
        self.assertEqual(pins(code), (OLD,None,OLD_ARCHIVE,None,OLD_STORE,None,HOST))
        self.assertEqual(policy.REVIEWED_TRANSITION_V21, pins(code))
        self.assertEqual(rollback.REVIEWED_ROLLBACK_V21, pins(code)+(PATHS,))
        self.assertNotIn(rollback.REVIEWED_ROLLBACK_V21, rollback.REVIEWED_ROLLBACKS)
        self.assertEqual(code.CODE_PATHS, PATHS); self.assertEqual(code.ADDED_SOURCE_PATHS, ADDED)
        self.assertEqual(code.TEST_PATHS, frozenset())
        self.assertEqual(policy.REVIEWED_ASSETS_V21, code.REPORT_ASSETS)
        for route in ('/naver/app.js','/naver/sales-ui.js','/naver/sales.css'):
            self.assertEqual(code.REPORT_ASSETS[route][:2], (None,None))
        for operation in ('prepare','apply'):
            adapters = [Mock() for _ in range(4)]
            with self.assertRaisesRegex(ValueError,'^CODE_ONLY_RELEASE_NOT_REVIEWED$'):
                getattr(policy,operation)({},*adapters,code)
            self.assertTrue(all(not adapter.mock_calls for adapter in adapters))
        for source in (None,True,[],'b'*40,'refs/heads/'+'b'*40):
            with self.assertRaisesRegex(ValueError,'NOT_REVIEWED'): policy.code_module_name(source)
        with self.assertRaisesRegex(ValueError,'NOT_REVIEWED'): rollback.require_review(policy,code)
        with self.assertRaisesRegex(ValueError,'^CODE_TARGET_NOT_PINNED$'):code.validate_package({},Mock())
        with self.assertRaisesRegex(ValueError,'^CODE_ONLY_REQUIRED$'):code.apply({},*[Mock() for _ in range(4)])

    def test_synthetic_exact_review_and_all_prior_profiles_still_work(self):
        code, policy = configured(); rollback=shared.load('naver_preview_code_rollback')
        policy.require_review(code)
        self.assertEqual(policy.code_module_name(code.TARGET_COMMIT),MODULE)
        rollback.REVIEWED_ROLLBACK_V21=pins(code)+(PATHS,)
        rollback.REVIEWED_ROLLBACKS |= frozenset({rollback.REVIEWED_ROLLBACK_V21})
        rollback.require_review(policy,code)
        policy=shared.load('naver_preview_code_only')
        rollback=shared.load('naver_preview_code_rollback')
        for version in range(5,21):
            prior=shared.load('naver_preview_code_upgrade_v'+str(version))
            policy.require_review(prior);rollback.require_review(policy,prior)
            self.assertEqual(getattr(policy,'REVIEWED_TRANSITION_V'+str(version)),pins(prior))
        status=shared.load('naver_preview_collection_status')
        self.assertNotIn(None,status.PASSIVE_RELEASES)

    def test_pin_scope_asset_route_and_test_mutations_refuse_before_adapters(self):
        for mutation in ('OLD_COMMIT','TARGET_COMMIT','OLD_SOURCE_SHA256','TARGET_SOURCE_SHA256',
                         'old_store','new_store','EXPECTED_BASELINE','scope','added','tests','owner_routes',
                         'write_routes','closed_routes','sales_routes','old_app','new_app','sales_ui','sales_css','pdf'):
            code,policy=configured()
            if mutation in ('old_store','new_store'):code.STORE_SHA256['old' if mutation=='old_store' else 'target']='0'*64
            elif mutation=='scope':code.CODE_PATHS |= {'naver_runtime/scheduler.py'}
            elif mutation=='added':code.ADDED_SOURCE_PATHS |= {'naver_engine/unreviewed.py'}
            elif mutation=='tests':code.TEST_PATHS=frozenset({'naver_engine/tests/unreviewed.py'})
            elif mutation=='owner_routes':code.OWNER_ACTION_ROUTES += ('/spend/change',)
            elif mutation=='write_routes':code.TARGET_ACTION_ROUTES += ('/spend/change',)
            elif mutation=='closed_routes':code.CLOSED_LINK_ROUTES=()
            elif mutation=='sales_routes':code.SALES_GET_ROUTES += ('/reports/detail',)
            elif mutation=='old_app':code.OLD_APP=(1,'0'*64,'text/javascript; charset=utf-8')
            elif mutation in ('new_app','sales_ui','sales_css','pdf'):
                route={'new_app':'app.js','sales_ui':'sales-ui.js','sales_css':'sales.css','pdf':'report-pdf.js'}[mutation]
                code.REPORT_ASSETS['/naver/'+route]=(1,'0'*64,code.REPORT_ASSETS['/naver/'+route][2])
            else:setattr(code,mutation,'0'*len(getattr(code,mutation)))
            for operation in ('prepare','apply'):
                adapters=[Mock() for _ in range(4)]
                with self.subTest(mutation=mutation,operation=operation),self.assertRaisesRegex(ValueError,'NOT_REVIEWED'):
                    getattr(policy,operation)({},*adapters,code)
                self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_v20_control_functions_except_typed_assets_and_probe_are_unchanged(self):
        funcs=lambda name:{n.name:ast.dump(n,include_attributes=False) for n in ast.parse((TOOLS/(name+'.py')).read_bytes()).body
            if isinstance(n,ast.FunctionDef) and n.name not in ('validate_package','probe')}
        self.assertEqual(funcs(MODULE),funcs('naver_preview_code_upgrade_v20'))
        old=shared.load('naver_preview_code_upgrade_v20');code=shared.load(MODULE)
        self.assertEqual(code.OLD_APP,old.REPORT_ASSETS['/naver/app.js'])
        for route in old.REPORT_ASSETS:
            if route!='/naver/app.js':self.assertEqual(code.REPORT_ASSETS[route],old.REPORT_ASSETS[route])
        for name in ('OWNER_ACTION_ROUTES','TARGET_ACTION_ROUTES','CLOSED_LINK_ROUTES','MONITORING_SQL'):
            self.assertEqual(getattr(code,name),getattr(old,name))

class V21ScopeTest(unittest.TestCase):
    def setUp(self):
        self.code,_=configured();folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.old,self.new=(Path(folder.name).resolve()/n for n in ('old','new'))
        self.before=shared.StoreScopeTest.SOURCE;self.after=self.before+b'\n# reviewed sales snapshot field\n'
        self.code.STORE_SHA256={'old':hashlib.sha256(self.before).hexdigest(),'target':hashlib.sha256(self.after).hexdigest()}
        compose=json.loads((Path(__file__).parent/'fixtures/v9-engine-compose-old.json').read_text())['compose'].encode()
        compose=compose.replace(b'    cpus: "0.50"\n',b'    cpus: "1.00"\n').replace(b'    mem_limit: 512m\n',b'    mem_limit: 768m\n')
        for root in (self.old,self.new):
            names={'compose.naver-relay.yml','deploy/naver-engine-backup.override.yml','Dockerfile.naver-engine',
                'Dockerfile.naver-relay','backend/requirements.txt','naver_runtime/bootstrap.py','naver_runtime/scheduler.py',
                'backend/naver_page/report-ui.js','backend/naver_page/report-pdf.js'} | PATHS
            for name in names:
                if root==self.old and name in ADDED:continue
                file=root/name;file.parent.mkdir(parents=True,exist_ok=True)
                file.write_bytes((b'old reviewed code' if root==self.old else b'new reviewed code') if name in PATHS else b'unchanged')
            (root/'compose.naver-engine.yml').write_bytes(compose)
            (root/'naver_engine/store.py').write_bytes(self.before if root==self.old else self.after)
            for name in ('engine','relay'):
                body=('image: '+self.code.OLD_COMMIT).encode()
                (root/('preview-'+name+'.override.yml')).write_bytes(body if root==self.old else self.code.target_override(body,name))
        self.upgrade=Mock();self.upgrade.read_file.side_effect=lambda path,**kwargs:Path(path).read_bytes()

    def test_exact_ten_paths_three_additions_forward_and_inverse_accept(self):
        self.code.compatible_source(self.old,self.new,self.upgrade)
        self.code.compatible_inverse_source(self.new,self.old,self.upgrade)

    def test_missing_additions_extra_files_or_outside_changes_reject(self):
        for name in ADDED:
            file=self.new/name;body=file.read_bytes();file.unlink()
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):
                self.code.compatible_source(self.old,self.new,self.upgrade)
            file.write_bytes(body)
        extra=self.new/'naver_engine/unreviewed.py';extra.write_bytes(b'new')
        with self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):self.code.compatible_source(self.old,self.new,self.upgrade)
        extra.unlink()
        for name in ('naver_runtime/scheduler.py','backend/naver_page/report-ui.js','backend/naver_page/report-pdf.js'):
            file=self.new/name;file.write_bytes(b'bad')
            for fn,a,b in ((self.code.compatible_source,self.old,self.new),(self.code.compatible_inverse_source,self.new,self.old)):
                with self.subTest(name=name),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):fn(a,b,self.upgrade)
            file.write_bytes(b'unchanged')

    def test_modes_symlink_store_hash_schema_and_infrastructure_reject(self):
        file=self.new/'backend/naver_page/sales-ui.js';file.chmod(0o755)
        with self.assertRaisesRegex(ValueError,'CODE_SOURCE_MODE_CHANGED'):self.code.compatible_source(self.old,self.new,self.upgrade)
        file.chmod(0o644);body=file.read_bytes();file.unlink();file.symlink_to(self.new/'backend/naver_page/app.js')
        with self.assertRaisesRegex(ValueError,'CODE_SOURCE_PATH'):self.code.compatible_code_scope(self.old,self.new,self.upgrade)
        file.unlink();file.write_bytes(body)
        file=self.new/'naver_engine/store.py';file.write_bytes(self.after+b'bad')
        with self.assertRaisesRegex(ValueError,'CODE_STORE_CHANGED'):self.code.compatible_source(self.old,self.new,self.upgrade)
        body=self.after.replace(b'SCHEMA_VERSION=11',b'SCHEMA_VERSION=12');file.write_bytes(body)
        self.code.STORE_SHA256['target']=hashlib.sha256(body).hexdigest()
        with self.assertRaisesRegex(ValueError,'CODE_SCHEMA_CHANGED'):self.code.compatible_source(self.old,self.new,self.upgrade)
        file.write_bytes(self.after);self.code.STORE_SHA256['target']=hashlib.sha256(self.after).hexdigest()
        (self.new/'compose.naver-engine.yml').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'CODE_INFRASTRUCTURE_CHANGED'):self.code.compatible_source(self.old,self.new,self.upgrade)

class V21AssetProbeTest(unittest.TestCase):
    def test_old_new_app_and_new_sales_assets_are_source_bound(self):
        code,_=configured();oldapp,newapp=b'old immutable app',b'new sales entry app';mime='text/javascript; charset=utf-8'
        code.OLD_APP=(len(oldapp),hashlib.sha256(oldapp).hexdigest(),mime)
        code.REPORT_ASSETS['/naver/app.js']=(len(newapp),hashlib.sha256(newapp).hexdigest(),mime)
        current={'source':code.OLD_COMMIT,'corrupt':None};release,upgrade=Mock(),Mock()
        seen=[]
        def request(path,route,method):
            seen.append(route)
            if route.startswith('/api/naver-auto'):return (403 if route.removeprefix('/api/naver-auto') in code.CLOSED_LINK_ROUTES else 401),{},b''
            if route=='/naver/dashboard':return 200,{'referrer-policy':'no-referrer','cache-control':'no-store'},b'id="s-dashboard"'
            body=route.encode()
            if route=='/naver/app.js':body=oldapp if current['source']==code.OLD_COMMIT else newapp
            if current['corrupt']==route:body+=b'corrupt'
            if current['corrupt']=='cross-app' and route=='/naver/app.js':body=newapp if current['source']==code.OLD_COMMIT else oldapp
            return 200,{'content-type':code.REPORT_ASSETS[route][2],'cache-control':'no-store','x-content-type-options':'nosniff','referrer-policy':'no-referrer'},body
        release.unix_request.side_effect=request
        for source in (code.OLD_COMMIT,code.TARGET_COMMIT):
            current.update(source=source,corrupt=None);seen.clear();code.probe(release,source,upgrade)
            for route in ('/naver/sales-ui.js','/naver/sales.css'):
                self.assertEqual(route in seen,source==code.TARGET_COMMIT)
            for corrupt in ('cross-app','/naver/report-ui.js','/naver/report-pdf.js')+(() if source==code.OLD_COMMIT else ('/naver/sales-ui.js','/naver/sales.css')):
                current['corrupt']=corrupt
                with self.subTest(source=source,corrupt=corrupt),self.assertRaisesRegex(ValueError,'REPORT_ASSET_NOT_READY'):code.probe(release,source,upgrade)
        current.update(source=code.TARGET_COMMIT,corrupt=None)
        original=request
        release.unix_request.side_effect=lambda path,route,method: (200,{},b'') if route=='/api/naver-auto/sales/clients' else original(path,route,method)
        with self.assertRaisesRegex(ValueError,'CODE_ROUTE_STATUS'):code.probe(release,code.TARGET_COMMIT,upgrade)

class V21ControllerTest(unittest.TestCase):
    def test_forward_and_failed_return_preserve_database_without_warmup(self):
        for failure in (None,'recreate','start','stop','probe'):
            with self.subTest(failure=failure),patch.object(shared.sqlite3,'connect',side_effect=AssertionError('DB forbidden')):
                result,commands,writes,restored,state=shared.ContractTest().scenario(failure,code_only=True,code_module=MODULE)
            if failure is None:
                self.assertTrue(result['ok']);self.assertFalse(result['database_opened_by_controller']);self.assertFalse(result['source_warmup_performed'])
            else:self.assertEqual(str(result),'CODE_ONLY_FAILED_ROLLED_BACK');self.assertEqual(set(state.values()),{OLD});self.assertTrue(restored)
            self.assertFalse(any('exec' in args or 'run' in args or 'nginx' in ' '.join(args) for args in commands))
            self.assertFalse(any(path.name=='bootstrap-request.json' or path.parent.name=='secrets' for path,_ in writes))

    def test_prepare_builds_without_start_database_or_secret_change(self):
        with patch.object(shared.sqlite3,'connect',side_effect=AssertionError('DB forbidden')):
            result,commands,writes,restored,state=shared.ContractTest().scenario(mode='prepare',code_only=True,code_module=MODULE)
        self.assertTrue(result['ok']);self.assertFalse(result['services_started']);self.assertFalse(result['database_opened_by_controller'])
        self.assertEqual(set(state.values()),{OLD});self.assertTrue(any(args[:2]==['docker','build'] for args in commands))
        self.assertFalse(any(args[:2]==['/usr/bin/systemctl','start'] for args in commands))

    def test_post_success_inverse_preserves_history_and_stops_on_failure(self):
        import test_naver_preview_code_rollback as reverse
        case=reverse.PostSuccessRollbackTest();self.addCleanup(case.doCleanups)
        for fault in (None,'writer','source_after_stop','recreate','start','probe_old'):
            fixture=case.fixture(fault,code_module=MODULE)
            with self.subTest(fault=fault):
                if fault is None:
                    result=case.run_fixture(fixture);self.assertTrue(result['ok']);self.assertEqual(result['source_commit'],OLD)
                    self.assertFalse(result['database_opened_by_controller'])
                else:
                    with self.assertRaisesRegex(RuntimeError,'^CODE_POST_ROLLBACK_FAILED$'):case.run_fixture(fixture)
                    self.assertTrue(all(fixture['active'][unit]=='inactive' for unit in fixture['lifecycle'].UNITS))
                for path,body in fixture['historical_bytes'].items():self.assertEqual(path.read_bytes(),body)


class V21TransportTest(unittest.TestCase):
    def bundles(self):
        source = lambda name: (TOOLS/(name+'.py')).read_text()
        release = dict(baseline=HOST, source_commit='b'*40, source_tar_gz_sha256='d'*64,
                       ciphertext_sha256='c'*64, run_id='12345678901', operation='code-prepare')
        prepare = dict(package=release, source=source('naver_preview_release'),
                       host_source=source('naver_erp_tunnel_service_install'),
                       upgrade_source=source('naver_preview_upgrade'), lifecycle_source=source('naver_preview_lifecycle'),
                       code_source=source(MODULE), operation='preview-code-only-prepare', code_only_source=source('naver_preview_code_only'))
        def operation(reverse=False):
            package = dict(release=release, operation_id='8'*32 if reverse else '9'*32)
            if reverse:
                package['apply_operation_id'] = '9'*32
            bundle = dict(package=package, operation='preview-code-only-rollback' if reverse else 'preview-code-only-upgrade',
                          function='run' if reverse else 'apply', source=source('naver_preview_code_rollback' if reverse else 'naver_preview_code_only'),
                          release_source=source('naver_preview_release'), host_source=source('naver_erp_tunnel_service_install'),
                          lifecycle_source=source('naver_preview_lifecycle'), upgrade_source=source('naver_preview_upgrade'), code_source=source(MODULE))
            if reverse:
                bundle['code_only_source'] = source('naver_preview_code_only')
            return bundle
        return {'prepare': prepare, 'forward': operation(), 'reverse': operation(True)}

    def test_three_pending_bundles_roundtrip_with_original_limits(self):
        import base64, gzip, zlib
        encode, decode, _ = shared.ContractTest().workflow_transport()
        for kind, bundle in self.bundles().items():
            raw = json.dumps(bundle).encode()
            with self.subTest(kind=kind):
                self.assertLessEqual(len(raw), 180000 if kind == 'prepare' else 196608)
                if kind == 'prepare':
                    wire = 'prepare-gzip-v1:'+base64.b64encode(gzip.compress(raw, mtime=0)).decode()
                    self.assertLessEqual(len(wire), 65536)
                    decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
                    unpacked = decoder.decompress(base64.b64decode(wire[len('prepare-gzip-v1:'):], validate=True), 180001)
                    self.assertLessEqual(len(unpacked), 180000)
                    self.assertTrue(decoder.eof)
                    self.assertFalse(decoder.unused_data or decoder.unconsumed_tail)
                    self.assertEqual(json.loads(unpacked), bundle)
                else:
                    wire = encode(bundle)
                    self.assertLessEqual(len(wire), 65536)
                    self.assertEqual(decode(wire), bundle)

    def test_pending_forward_and_inverse_scripts_refuse_before_any_host_action(self):
        import test_naver_preview_code_only as legacy
        encode, _, remote = shared.ContractTest().workflow_transport()
        for kind, bundle in self.bundles().items():
            if kind == 'prepare':
                continue
            bundle['code_source'] = bundle['code_source'].replace(repr(TARGET), 'None').replace(repr(ARCHIVE), 'None').replace(repr(STORE), 'None')
            bundle['host_source'] = 'class NativeHost:\n    def baseline(self): raise AssertionError("PRIVATE_HOST_ACTION")\n'
            status, result = legacy.CodeOnlyTest().run_remote_script(remote, 'PREVIEW_OPS_B64', encode(bundle), 'NAVER_PREVIEW_OPS=')
            self.assertEqual(status, 1)
            self.assertEqual(result['error_code'], 'CODE_ONLY_RELEASE_NOT_REVIEWED')
            self.assertNotIn('PRIVATE', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
