"""V12 diagnostics scope and fail-closed pins; synthetic fixtures, no operating DB."""
import ast
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared
import test_naver_preview_code_upgrade_v8 as previous

MODULE = 'naver_preview_code_upgrade_v12'
OLD = '9bfcace1c6ba2a49807c5ec8feb69fde11de73bf'
OLD_ARCHIVE = '1acf8f5d9f54d075655ed263026a77745b75548bbee8fd66a2286aeee404628e'
OLD_STORE = 'de9d1fe5886055d07261bc41687666cfe5f800fe582a02057910026ef564ca53'
TARGET_STORE = '055106d6811a998b1265b893f4150c2590a3fbaea4b7a48d8fd48d1a78462431'
HOST = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
COMPOSE = '62e33c3d2815579a28031973b956cd36031171f26ead4e21ad2d72adfe2a5ef7'
PATHS = {'naver_engine/store.py', 'naver_engine/web.py', 'naver_engine/views.py', 'backend/naver_page/app.js', 'naver_runtime/writer.py', 'naver_runtime/__main__.py', 'naver_engine/collection_diagnostics.py'}
TARGET = '3145da9e3021aed0c06d17f2e51525fc866f8799'
TARGET_ARCHIVE = '14a72af0ee951d54ea05a0c176bb3c2ffdd5e14fdd4380aafd8ba6ad5e31ee7d'


def pins(code):
    return (code.OLD_COMMIT, code.TARGET_COMMIT, code.OLD_SOURCE_SHA256,
        code.TARGET_SOURCE_SHA256, code.STORE_SHA256['old'], code.STORE_SHA256['target'], code.EXPECTED_BASELINE)


def configured():
    code, policy = shared.load(MODULE), shared.load('naver_preview_code_only')
    # Deliberately synthetic values held only in the isolated in-memory fixture.
    code.TARGET_COMMIT, code.TARGET_SOURCE_SHA256 = 'b'*40, 'd'*64
    code.STORE_SHA256['target'] = 'e'*64
    policy.REVIEWED_TRANSITION_V12 = pins(code)
    return code, policy


def package(code):
    return dict(baseline=code.EXPECTED_BASELINE, source_commit=code.TARGET_COMMIT,
        ciphertext_sha256='c'*64, source_tar_gz_sha256=code.TARGET_SOURCE_SHA256,
        run_id='999999', operation='code-prepare')


class V12ContractTest(unittest.TestCase):
    def test_exact_reviewed_source_previous_store_and_scope_are_fixed(self):
        code, policy, rollback, status = (shared.load(name) for name in
            (MODULE, 'naver_preview_code_only', 'naver_preview_code_rollback', 'naver_preview_collection_status'))
        expected=(OLD,TARGET,OLD_ARCHIVE,TARGET_ARCHIVE,OLD_STORE,TARGET_STORE,HOST)
        self.assertEqual(pins(code),expected)
        self.assertEqual(policy.REVIEWED_TRANSITION_V12,expected)
        self.assertEqual(rollback.REVIEWED_ROLLBACK_V12,expected+(frozenset(PATHS),))
        if TARGET is None:
            self.assertNotIn(rollback.REVIEWED_ROLLBACK_V12,rollback.REVIEWED_ROLLBACKS)
            with self.assertRaisesRegex(ValueError,'NOT_REVIEWED'):policy.require_review(code)
            return
        self.assertIn(rollback.REVIEWED_ROLLBACK_V12,rollback.REVIEWED_ROLLBACKS)
        self.assertEqual(status.PASSIVE_COMMIT_V12,TARGET)
        self.assertEqual(status.PASSIVE_SOURCE_SHA256_V12,TARGET_ARCHIVE)
        self.assertEqual(status.PASSIVE_RELEASES[TARGET],(TARGET_ARCHIVE,TARGET_STORE,HOST))
        self.assertNotIn(TARGET,status.PROFILE_RELEASES)
        self.assertNotIn(None,status.PASSIVE_RELEASES)
        self.assertEqual(code.CODE_PATHS,PATHS)
        self.assertEqual(code.TEST_PATHS,frozenset())
        self.assertEqual(code.ENGINE_COMPOSE_SHA256,COMPOSE)
        self.assertFalse(hasattr(code,'RESOURCE_LIMITS_APPROVED'))
        policy.require_review(code)
        rollback.require_review(policy,code)

    def test_pending_or_partial_pins_refuse_before_every_adapter(self):
        for target, archive in ((None,None),('b'*40,None),(None,'d'*64),('', 'd'*64),
            ('b'*40,''),(True,'d'*64),('b'*40,True),('b'*40,'PENDING_REVIEW')):
            code,policy=shared.load(MODULE),shared.load('naver_preview_code_only')
            code.TARGET_COMMIT,code.TARGET_SOURCE_SHA256=target,archive
            policy.REVIEWED_TRANSITION_V12=pins(code)
            with self.subTest(target_type=type(target).__name__,archive_type=type(archive).__name__):
                for operation in ('prepare','apply'):
                    adapters=[Mock() for _ in range(4)]
                    with self.assertRaisesRegex(ValueError,'^CODE_ONLY_RELEASE_NOT_REVIEWED$'):
                        getattr(policy,operation)({},*adapters,code)
                    self.assertTrue(all(not adapter.mock_calls for adapter in adapters))
                release=shared.load('naver_preview_release'); adapters=[Mock() for _ in range(3)]
                with self.assertRaisesRegex(ValueError,'^CODE_TARGET_NOT_PINNED$'):
                    code.prepare(package(code),adapters[0],release,adapters[1],adapters[2])
                self.assertTrue(all(not adapter.mock_calls for adapter in adapters))
                with self.assertRaisesRegex(ValueError,'^CODE_ONLY_RELEASE_NOT_REVIEWED$'):
                    policy.code_module_name(target)

    def test_exact_synthetic_selection_rejects_similar_refs_and_types(self):
        code,policy=configured()
        policy.require_review(code)
        self.assertEqual(policy.code_module_name(code.TARGET_COMMIT),MODULE)
        for value in (None,True,[],{},'b'*39,'b'*40+'x','B'*40,'refs/heads/'+'b'*40,'0'*40):
            with self.subTest(kind=type(value).__name__),self.assertRaisesRegex(ValueError,'NOT_REVIEWED'):
                policy.code_module_name(value)
        previous=shared.load('naver_preview_code_upgrade_v9')
        self.assertEqual(policy.code_module_name(previous.TARGET_COMMIT),'naver_preview_code_upgrade_v9')
        policy.require_review(previous)

    def test_each_pin_and_scope_mutation_refuses_before_host(self):
        for field in ('OLD_COMMIT','TARGET_COMMIT','OLD_SOURCE_SHA256','TARGET_SOURCE_SHA256',
            'STORE_OLD','STORE_TARGET','EXPECTED_BASELINE','extra_scope','missing_scope','tests'):
            code,policy=configured()
            if field.startswith('STORE_'):code.STORE_SHA256[field[6:].lower()]='0'*64
            elif field=='extra_scope':code.CODE_PATHS|={'compose.naver-engine.yml'}
            elif field=='missing_scope':code.CODE_PATHS=set()
            elif field=='tests':code.TEST_PATHS=frozenset({'naver_engine/tests/test_web.py'})
            else:setattr(code,field,'0'*len(getattr(code,field)))
            for operation in ('prepare','apply'):
                adapters=[Mock() for _ in range(4)]
                with self.subTest(field=field,operation=operation),self.assertRaisesRegex(ValueError,'NOT_REVIEWED'):
                    getattr(policy,operation)({},*adapters,code)
                self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_v8_control_functions_and_authority_routes_remain_unchanged(self):
        root=Path(__file__).parents[1]/'tools'
        def functions(name):
            return {node.name:ast.dump(node,include_attributes=False)
                for node in ast.parse((root/(name+'.py')).read_text()).body
                if isinstance(node,(ast.FunctionDef,ast.ClassDef))
                    and node.name not in ('compatible_source','compatible_engine_compose')}
        self.assertEqual(functions(MODULE),functions('naver_preview_code_upgrade_v8'))
        code,previous=shared.load(MODULE),shared.load('naver_preview_code_upgrade_v8')
        for name in ('OWNER_ACTION_ROUTES','TARGET_ACTION_ROUTES','CLOSED_LINK_ROUTES',
            'REPORT_ASSETS','REMOVABLE_SOURCE_PREFIXES','MONITORING_SQL','FAILURE_CODES'):
            self.assertEqual(getattr(code,name),getattr(previous,name))
        adapters=[Mock() for _ in range(4)]
        with self.assertRaisesRegex(ValueError,'^CODE_ONLY_REQUIRED$'):code.apply({},*adapters)
        self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_actual_9bfc_compose_is_identical_and_every_resource_drift_is_rejected(self):
        code=shared.load(MODULE)
        body=json.loads((Path(__file__).parent/'fixtures/v9-engine-compose-old.json').read_text())['compose'].encode()
        body=body.replace(b'    cpus: "0.50"\n',b'    cpus: "1.00"\n').replace(b'    mem_limit: 512m\n',b'    mem_limit: 768m\n')
        self.assertEqual(hashlib.sha256(body).hexdigest(),COMPOSE)
        code.compatible_engine_compose(body,body)
        for old,new in ((body,body+b'\n'),(body+b'\n',body+b'\n'),
            (body,body.replace(b'1.00',b'0.50')),(body,body.replace(b'768m',b'512m')),
            (body,body+b'\nnetworks: {unreviewed: {external: true}}\n'),
            (body,body.decode()),(None,body)):
            with self.subTest(old_type=type(old).__name__,new_type=type(new).__name__),self.assertRaisesRegex(ValueError,'CODE_INFRASTRUCTURE_CHANGED'):
                code.compatible_engine_compose(old,new)

    def test_forward_success_and_failure_keep_database_and_warmup_closed(self):
        for failure in (None,'recreate','start','stop','probe'):
            with self.subTest(failure=failure),patch.object(shared.sqlite3,'connect',side_effect=AssertionError('DB forbidden')):
                result,commands,writes,restored,state=shared.ContractTest().scenario(
                    failure,code_only=True,code_module=MODULE)
            if failure is None:
                self.assertTrue(result['ok'])
                self.assertEqual(set(state.values()),{'b'*40})
                self.assertFalse(result['database_opened_by_controller'])
                self.assertFalse(result['source_warmup_performed'])
            else:
                self.assertEqual(str(result),'CODE_ONLY_FAILED_ROLLED_BACK')
                self.assertEqual(set(state.values()),{OLD})
                self.assertTrue(restored)
            self.assertFalse(any('exec' in args or 'run' in args for args in commands))
            self.assertFalse(any('nginx' in ' '.join(args) for args in commands))
            self.assertFalse(any(p.name=='bootstrap-request.json' or p.parent.name=='secrets' for p,_ in writes))

    def test_unsafe_failure_keeps_writers_stopped(self):
        for failure in ('stop_writer_running','rollback_writer_running','rollback_recreate','bootstrap_changed'):
            with self.subTest(failure=failure):
                result,commands,_,_,_=shared.ContractTest().scenario(failure,code_only=True,code_module=MODULE)
                self.assertEqual(str(result),'CODE_ROLLBACK_FAILED')
                self.assertEqual(commands[-2:],[['/usr/bin/systemctl','stop','metainc-naver-relay.service'],
                    ['/usr/bin/systemctl','stop','metainc-naver-engine.service']])

    def test_pending_rollback_and_passive_registry_do_not_grant_profile(self):
        code,policy=configured(); helper=shared.load('naver_preview_code_rollback')
        with self.assertRaisesRegex(ValueError,'^CODE_ROLLBACK_NOT_REVIEWED$'):
            helper.require_review(policy,code)
        status=shared.load('naver_preview_collection_status')
        self.assertNotIn(code.TARGET_COMMIT,status.PASSIVE_RELEASES)
        self.assertNotIn(code.TARGET_COMMIT,status.PROFILE_RELEASES)



class V12StoreScopeTest(previous.V8StoreScopeTest):
    def setUp(self):
        # Reuse the tested V8 real file/mode guard with a fresh isolated directory.
        previous.V8StoreScopeTest.setUp(self)
        self.code=shared.load(MODULE)
        self.code.TARGET_COMMIT='b'*40
        self.code.TARGET_SOURCE_SHA256='d'*64
        self.after=self.before+b'\n# synthetic V12 read performance change\n'
        (self.new/'naver_engine/store.py').write_bytes(self.after)
        self.code.STORE_SHA256={'old':hashlib.sha256(self.before).hexdigest(),'target':hashlib.sha256(self.after).hexdigest()}
        body=json.loads((Path(__file__).parent/'fixtures/v9-engine-compose-old.json').read_text())['compose'].encode()
        body=body.replace(b'    cpus: "0.50"\n',b'    cpus: "1.00"\n').replace(b'    mem_limit: 512m\n',b'    mem_limit: 768m\n')
        for root in (self.old,self.new):
            (root/'compose.naver-engine.yml').write_bytes(body)
            for name in ('backend/naver_page/app.js','naver_engine/views.py','naver_engine/management_store.py'):
                (root/name).write_bytes(b'unchanged')
            for name in ('naver_engine/web.py','naver_runtime/writer.py','naver_runtime/__main__.py'):
                file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'old' if root==self.old else b'new')
            if root==self.new:
                (root/'naver_engine/collection_diagnostics.py').write_bytes(b'new manual diagnostics')
            for name in ('engine','relay'):
                original=('image: '+self.code.OLD_COMMIT).encode()
                (root/('preview-'+name+'.override.yml')).write_bytes(original if root==self.old else self.code.target_override(original,name))

    def test_repinning_cannot_authorize_store_bytes_or_infrastructure_changes(self):
        store=self.new/'naver_engine/store.py'
        store.write_bytes(self.after+b'\n# unpinned change\n')
        with self.assertRaisesRegex(ValueError,'^CODE_STORE_CHANGED$'):
            self.code.compatible_source(self.old,self.new,self.upgrade)
        store.write_bytes(self.after)
        for name in ('compose.naver-engine.yml','compose.naver-relay.yml',
            'deploy/naver-engine-backup.override.yml','Dockerfile.naver-engine',
            'Dockerfile.naver-relay','backend/requirements.txt','naver_runtime/bootstrap.py'):
            file=self.new/name;before=file.read_bytes();file.write_bytes(before+b' changed')
            with self.subTest(path=name),self.assertRaisesRegex(ValueError,'^CODE_INFRASTRUCTURE_CHANGED$'):
                self.code.compatible_source(self.old,self.new,self.upgrade)
            file.write_bytes(before)

    def test_seven_exact_paths_with_distinct_store_same_schema_and_compose_are_accepted(self):
        self.code.compatible_source(self.old,self.new,self.upgrade)

    def test_any_eighth_product_path_change_is_rejected(self):
        for name in ('naver_engine/inventory.py','naver_engine/dashboard.py','naver_runtime/scheduler.py','naver_engine/management_store.py'):
            target=self.new/name;target.parent.mkdir(parents=True,exist_ok=True)
            previous=target.read_bytes() if target.exists() else None
            target.write_bytes(b'unreviewed change')
            with self.subTest(path=name),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):
                self.code.compatible_source(self.old,self.new,self.upgrade)
            if previous is None:target.unlink()
            else:target.write_bytes(previous)


    def test_every_file_outside_v8_scope_refuses_before_service_control(self):
        # V12 intentionally allows __main__; the unchanged V8 test retains its old complement.
        for name in ('backend/app/naver_auto/scope.py','backend/naver_page/report-ui.js',
                     'backend/naver_page/report-pdf.js','deploy/unapproved.conf',
                     'naver_engine/inventory.py','naver_engine/dashboard.py','naver_runtime/scheduler.py'):
            target=self.new/name;target.parent.mkdir(parents=True,exist_ok=True)
            before=target.read_bytes() if target.exists() else None
            target.write_bytes(b'unreviewed')
            try:
                with self.subTest(path=name),self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):
                    self.code.compatible_source(self.old,self.new,self.upgrade)
            finally:
                if before is None:target.unlink()
                else:target.write_bytes(before)

class V12BoundaryTest(unittest.TestCase):
    def test_passive_only_active_modes_and_bad_source_pins_refuse_before_host(self):
        status=shared.load('naver_preview_collection_status')
        commit, archive, digest='b'*40,'d'*64,'e'*64
        status.PASSIVE_RELEASES=dict(status.PASSIVE_RELEASES,**{commit:(archive,digest,HOST)})
        base=dict(source_commit=commit,source_tar_gz_sha256=archive,baseline=HOST)
        for package, error in ((base,'PASSIVE_RUNTIME_ONLY'),
                (dict(base,latency_profile_only=True),'PROFILE_SOURCE_UNREVIEWED'),
                (dict(base,dashboard_profile_only=True),'PROFILE_SOURCE_UNREVIEWED'),
                (dict(base,passive_runtime_only=True,source_tar_gz_sha256='0'*64),'PASSIVE_SOURCE_PIN_CHANGED'),
                (dict(base,passive_runtime_only=True,baseline='0'*64),'PASSIVE_SOURCE_PIN_CHANGED')):
            host,release=Mock(),Mock()
            with patch.object(status,'capture_process') as capture, self.assertRaisesRegex(ValueError,'^'+error+'$'):
                status.run(package,host,release)
            self.assertFalse(host.mock_calls);self.assertFalse(release.mock_calls);capture.assert_not_called()
        self.assertNotIn(commit,status.PROFILE_RELEASES)

    def test_final_v12_passive_path_reuses_existing_no_database_no_http_fixture(self):
        if TARGET is None:
            return  # No target has authority until pinned; pending tests prove denial.
        import test_naver_preview_collection_status as existing
        existing.CollectionTest().check_run_diagnostics(TARGET,passive=True)

    def test_target_store_partial_pins_close_selector_prepare_apply_and_rollback(self):
        for value in (None, True, '', 'e'*63, 'E'*64, 'PENDING_REVIEW'):
            code, policy = configured()
            code.STORE_SHA256['target'] = value
            policy.REVIEWED_TRANSITION_V12 = pins(code)
            helper = shared.load('naver_preview_code_rollback')
            helper.REVIEWED_ROLLBACK_V12 = pins(code)+(frozenset(code.CODE_PATHS),)
            helper.REVIEWED_ROLLBACKS |= frozenset({helper.REVIEWED_ROLLBACK_V12})
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
                    policy.code_module_name(code.TARGET_COMMIT)
                for method in ('prepare', 'apply'):
                    adapters = [Mock() for _ in range(4)]
                    with self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
                        getattr(policy, method)({}, *adapters, code)
                    self.assertTrue(all(not a.mock_calls for a in adapters))
                adapters = [Mock() for _ in range(4)]
                with self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
                    helper.run({}, *adapters, policy, code)
                self.assertTrue(all(not a.mock_calls for a in adapters))

    def test_partial_literal_target_archive_or_store_never_registers(self):
        tools=Path(__file__).parents[1]/'tools'
        for target, archive, digest in ((None, None, None), ('b'*40, None, 'e'*64),
                ('b'*40, 'd'*64, None), (None, 'd'*64, 'e'*64),
                (True, 'd'*64, 'e'*64), ('b'*40, True, 'e'*64), ('b'*40, 'd'*64, True),
                ('b'*40, 'd'*64, 'e'*63)):
            for module, label in (('naver_preview_code_only','REVIEWED_TRANSITION_V12'),
                    ('naver_preview_code_rollback','REVIEWED_ROLLBACK_V12')):
                tree=ast.parse((tools/(module+'.py')).read_text())
                node=next(n for n in tree.body if isinstance(n,ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id==label for t in n.targets))
                for index,value in ((1,target),(3,archive),(5,digest)):
                    node.value.elts[index]=ast.Constant(value=value)
                namespace={};exec(compile(ast.fix_missing_locations(tree),module,'exec'),namespace)
                if module.endswith('only'):
                    with self.assertRaisesRegex(ValueError,'NOT_REVIEWED'):
                        namespace['code_module_name'](target)
                else:
                    self.assertNotIn(namespace[label],namespace['REVIEWED_ROLLBACKS'])
            tree=ast.parse((tools/'naver_preview_collection_status.py').read_text())
            values={'PASSIVE_COMMIT_V12':target,'PASSIVE_SOURCE_SHA256_V12':archive,'PASSIVE_STORE_SHA256_V12':digest}
            for n in tree.body:
                if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in values:
                    n.value=ast.Constant(value=values[n.targets[0].id])
            namespace={};exec(compile(ast.fix_missing_locations(tree),'status','exec'),namespace)
            self.assertNotIn(target,namespace['PASSIVE_RELEASES'])
            self.assertNotIn(target,namespace['PROFILE_RELEASES'])

    def test_distinct_store_exception_is_only_the_exact_registered_v12_tuple(self):
        code, policy=configured();helper=shared.load('naver_preview_code_rollback')
        exact=helper.transition(code)
        self.assertNotEqual(code.STORE_SHA256['old'],code.STORE_SHA256['target'])
        helper.REVIEWED_ROLLBACK_V12=exact
        helper.REVIEWED_ROLLBACKS|=frozenset({exact})
        helper.require_review(policy,code)
        helper.REVIEWED_ROLLBACK_V12=exact[:-1]+(frozenset({'naver_engine/web.py'}),)
        with self.assertRaisesRegex(ValueError,'^CODE_ROLLBACK_NOT_REVIEWED$'):
            helper.require_review(policy,code)
        for version in range(5,11):
            old=shared.load('naver_preview_code_upgrade_v'+str(version))
            old.STORE_SHA256=dict(old.STORE_SHA256,target='e'*64)
            helper.REVIEWED_ROLLBACKS|=frozenset({helper.transition(old)})
            with self.subTest(version=version),self.assertRaisesRegex(ValueError,'^CODE_ROLLBACK_NOT_REVIEWED$'):
                helper.require_review(Mock(),old)

    def test_v12_helper_only_six_pin_assignments_and_description_differ_from_v10(self):
        tools=Path(__file__).parents[1]/'tools'
        changes={'OLD_COMMIT','TARGET_COMMIT','OLD_SOURCE_SHA256','TARGET_SOURCE_SHA256','STORE_SHA256','CODE_PATHS'}
        def normalized(name):
            tree=ast.parse((tools/(name+'.py')).read_text())
            nodes=[n for n in tree.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str))
                and not (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in changes for t in n.targets))]
            return [ast.dump(n,include_attributes=False) for n in nodes]
        self.assertEqual(normalized(MODULE),normalized('naver_preview_code_upgrade_v10'))
        for version in range(5,11):
            code=shared.load('naver_preview_code_upgrade_v'+str(version))
            policy=shared.load('naver_preview_code_only');helper=shared.load('naver_preview_code_rollback')
            self.assertEqual(getattr(policy,'REVIEWED_TRANSITION_V'+str(version)),pins(code))
            self.assertIn(helper.transition(code),helper.REVIEWED_ROLLBACKS)
            policy.require_review(code);helper.require_review(policy,code)


if __name__=='__main__':unittest.main()

class V12PendingTransportTest(unittest.TestCase):
    def test_pending_source_never_encodes_controller_or_touches_any_host(self):
        import test_naver_preview_code_rollback_transport as existing
        fixture=existing.RollbackTransportTest()
        fixture.setUp()
        fixture.package['release'].update(source_commit=None,source_tar_gz_sha256=None)
        fixture.inputs['ad_expected_baseline']=json.dumps(fixture.package)
        with self.assertRaisesRegex(ValueError,'^PACKAGE_SHAPE$'):
            fixture.encoded()
