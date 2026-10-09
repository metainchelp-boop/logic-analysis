"""V10 diagnostics scope and fail-closed pins; synthetic fixtures, no operating DB."""
import ast
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared
import test_naver_preview_code_upgrade_v8 as previous

MODULE = 'naver_preview_code_upgrade_v10'
OLD = 'bd08fd07281ae5448bffb3de3d7c405887bfecd9'
OLD_ARCHIVE = '6b1618ab9dd47eca6030d1092bdbce1d451d30ce8fdf103e448a96f3ac9da3f1'
STORE = 'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862'
HOST = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
COMPOSE = '62e33c3d2815579a28031973b956cd36031171f26ead4e21ad2d72adfe2a5ef7'
PATHS = {'naver_engine/web.py'}
TARGET = '3fa096d3d383123fdd3469c5dc68404171a6f076'
TARGET_ARCHIVE = '1a528165dae3f2e896d98e950f1b92369f997af2ce4e2d823febb7b18c86a6de'


def pins(code):
    return (code.OLD_COMMIT, code.TARGET_COMMIT, code.OLD_SOURCE_SHA256,
        code.TARGET_SOURCE_SHA256, code.STORE_SHA256['old'], code.STORE_SHA256['target'], code.EXPECTED_BASELINE)


def configured():
    code, policy = shared.load(MODULE), shared.load('naver_preview_code_only')
    # Deliberately synthetic values held only in the isolated in-memory fixture.
    code.TARGET_COMMIT, code.TARGET_SOURCE_SHA256 = 'b'*40, 'd'*64
    policy.REVIEWED_TRANSITION_V10 = pins(code)
    return code, policy


def package(code):
    return dict(baseline=code.EXPECTED_BASELINE, source_commit=code.TARGET_COMMIT,
        ciphertext_sha256='c'*64, source_tar_gz_sha256=code.TARGET_SOURCE_SHA256,
        run_id='999999', operation='code-prepare')


class V10ContractTest(unittest.TestCase):
    def test_exact_reviewed_source_previous_store_and_scope_are_fixed(self):
        code, policy, rollback, status = (shared.load(name) for name in
            (MODULE, 'naver_preview_code_only', 'naver_preview_code_rollback', 'naver_preview_collection_status'))
        expected=(OLD,TARGET,OLD_ARCHIVE,TARGET_ARCHIVE,STORE,STORE,HOST)
        self.assertEqual(pins(code),expected)
        self.assertEqual(policy.REVIEWED_TRANSITION_V10,expected)
        self.assertEqual(rollback.REVIEWED_ROLLBACK_V10,expected+(frozenset(PATHS),))
        self.assertIn(rollback.REVIEWED_ROLLBACK_V10,rollback.REVIEWED_ROLLBACKS)
        self.assertEqual(status.PASSIVE_COMMIT_V10,TARGET)
        self.assertEqual(status.PASSIVE_SOURCE_SHA256_V10,TARGET_ARCHIVE)
        self.assertEqual(status.PASSIVE_RELEASES[TARGET],(TARGET_ARCHIVE,STORE,HOST))
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
            policy.REVIEWED_TRANSITION_V10=pins(code)
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

    def test_actual_bd08_compose_is_identical_and_every_resource_drift_is_rejected(self):
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

    def test_partial_literal_registry_pins_never_register_or_dispatch(self):
        root=Path(__file__).parents[1]/'tools'
        for target,archive in ((None,None),('b'*40,None),(None,'d'*64),
                (True,'d'*64),('b'*40,True),('b'*39,'d'*64),('b'*40,'d'*63)):
            with self.subTest(target_type=type(target).__name__,archive_type=type(archive).__name__):
                for name in ('naver_preview_code_only','naver_preview_code_rollback'):
                    body=(root/(name+'.py')).read_text()
                    old=f"'{OLD}', '{TARGET}', '{OLD_ARCHIVE}', '{TARGET_ARCHIVE}',"
                    new=f"'{OLD}', {target!r}, '{OLD_ARCHIVE}', {archive!r},"
                    self.assertEqual(body.count(old),1)
                    namespace={};exec(compile(body.replace(old,new),name,'exec'),namespace)
                    if name.endswith('only'):
                        with self.assertRaisesRegex(ValueError,'NOT_REVIEWED'):
                            namespace['code_module_name'](target)
                    else:
                        self.assertNotIn(namespace['REVIEWED_ROLLBACK_V10'],namespace['REVIEWED_ROLLBACKS'])
                body=(root/'naver_preview_collection_status.py').read_text()
                body=body.replace(f"PASSIVE_COMMIT_V10 = '{TARGET}'",f'PASSIVE_COMMIT_V10 = {target!r}')
                body=body.replace(f"PASSIVE_SOURCE_SHA256_V10 = '{TARGET_ARCHIVE}'",f'PASSIVE_SOURCE_SHA256_V10 = {archive!r}')
                namespace={};exec(compile(body,'status','exec'),namespace)
                self.assertNotIn(target,namespace['PASSIVE_RELEASES'])
                self.assertNotIn(target,namespace['PROFILE_RELEASES'])


class V10StoreScopeTest(previous.V8StoreScopeTest):
    def setUp(self):
        # Reuse the tested V8 real file/mode guard with a fresh isolated directory.
        previous.V8StoreScopeTest.setUp(self)
        self.code=shared.load(MODULE)
        self.code.TARGET_COMMIT='b'*40
        self.code.TARGET_SOURCE_SHA256='d'*64
        self.code.STORE_SHA256={'old':hashlib.sha256(self.before).hexdigest(),'target':hashlib.sha256(self.after).hexdigest()}
        body=json.loads((Path(__file__).parent/'fixtures/v9-engine-compose-old.json').read_text())['compose'].encode()
        body=body.replace(b'    cpus: "0.50"\n',b'    cpus: "1.00"\n').replace(b'    mem_limit: 512m\n',b'    mem_limit: 768m\n')
        for root in (self.old,self.new):
            (root/'compose.naver-engine.yml').write_bytes(body)
            for name in ('backend/naver_page/app.js','naver_engine/views.py'):
                (root/name).write_bytes(b'unchanged')
            for name in ('engine','relay'):
                original=('image: '+self.code.OLD_COMMIT).encode()
                (root/('preview-'+name+'.override.yml')).write_bytes(original if root==self.old else self.code.target_override(original,name))

    def test_web_only_source_change_with_identical_store_and_compose_is_accepted(self):
        self.code.compatible_source(self.old,self.new,self.upgrade)

    def test_any_second_product_path_change_is_rejected(self):
        for name in ('backend/naver_page/app.js','naver_engine/views.py','naver_engine/inventory.py','naver_engine/management_store.py'):
            target=self.new/name;target.parent.mkdir(parents=True,exist_ok=True)
            previous=target.read_bytes() if target.exists() else None
            target.write_bytes(b'unreviewed change')
            with self.subTest(path=name),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):
                self.code.compatible_source(self.old,self.new,self.upgrade)
            if previous is None:target.unlink()
            else:target.write_bytes(previous)


if __name__=='__main__':unittest.main()
