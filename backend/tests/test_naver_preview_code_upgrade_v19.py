"""V19 Store-only recovery gate; synthetic files, adapters and transport only."""
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared

MODULE = 'naver_preview_code_upgrade_v19'
OLD = '7f32d70d97876b806cc5bc44a7cc0f9688caeada'
OLD_ARCHIVE = 'd6a2d1fe521287c9cedfba1132e5a81164ed2e2745ddea7ea01d74c2beb80a13'
OLD_STORE = 'b01a1e21cc87df1ef5a3935a30cc25d96b0ec3ced0fcc42a2bc9999685ef7d95'
TARGET = '00701771c0583477357010e9ac731263770f1da5'
ARCHIVE = '5c77d0197fb088600e11234660f3bf3013c03eafd8e3b756b8be7b91f34fc0e3'
STORE = 'aa39afff20c48225d70e80a899234c68b862aeaa53fae43c2e0769346f3b6d62'
HOST = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
UI = (62666, '3f5ba0938c922ce8fbcaae59a8893d2b031b22d335554f0befd8dfd477d5d6c2', 'text/javascript; charset=utf-8')
PDF = (35168, '45d15c2862cd83a223e52cf85c1feb9327ffe6cc5753d558a8f6d67e1cd8f6bc', 'text/javascript; charset=utf-8')
PATHS = frozenset({'naver_engine/store.py'})
TOOLS = Path(__file__).parents[1]/'tools'


def pins(code):
    return (code.OLD_COMMIT, code.TARGET_COMMIT, code.OLD_SOURCE_SHA256, code.TARGET_SOURCE_SHA256,
            code.STORE_SHA256['old'], code.STORE_SHA256['target'], code.EXPECTED_BASELINE)


def configured():
    code, policy = shared.sealed_code(MODULE), shared.load('naver_preview_code_only')
    policy.REVIEWED_TRANSITION_V19 = pins(code)
    policy.REVIEWED_OLD_REPORT_UI_V19 = code.OLD_REPORT_UI
    return code, policy


class V19PinsTest(unittest.TestCase):
    def test_exact_final_tuple_has_only_store_authority(self):
        code, policy = shared.load(MODULE), shared.load('naver_preview_code_only')
        rollback = shared.load('naver_preview_code_rollback')
        expected = (OLD, TARGET, OLD_ARCHIVE, ARCHIVE, OLD_STORE, STORE, HOST)
        self.assertEqual(pins(code), expected)
        self.assertEqual(policy.REVIEWED_TRANSITION_V19, expected)
        self.assertEqual(rollback.REVIEWED_ROLLBACK_V19, expected+(PATHS,))
        self.assertIn(rollback.REVIEWED_ROLLBACK_V19, rollback.REVIEWED_ROLLBACKS)
        policy.require_review(code)
        rollback.require_review(policy, code)
        self.assertEqual(policy.code_module_name(TARGET), MODULE)

    def test_pending_target_has_no_selector_prepare_apply_or_rollback_authority(self):
        code, policy = shared.load(MODULE), shared.load('naver_preview_code_only')
        rollback, status = shared.load('naver_preview_code_rollback'), shared.load('naver_preview_collection_status')
        expected = (OLD, None, OLD_ARCHIVE, None, OLD_STORE, None, HOST)
        code.TARGET_COMMIT = code.TARGET_SOURCE_SHA256 = code.STORE_SHA256['target'] = None
        policy.REVIEWED_TRANSITION_V19 = expected
        rollback.REVIEWED_ROLLBACKS -= frozenset({rollback.REVIEWED_ROLLBACK_V19})
        rollback.REVIEWED_ROLLBACK_V19 = expected+(PATHS,)
        self.assertEqual(pins(code), expected)
        self.assertEqual(policy.REVIEWED_TRANSITION_V19, expected)
        self.assertEqual(rollback.REVIEWED_ROLLBACK_V19, expected+(PATHS,))
        self.assertNotIn(rollback.REVIEWED_ROLLBACK_V19, rollback.REVIEWED_ROLLBACKS)
        self.assertEqual(code.CODE_PATHS, PATHS)
        self.assertEqual(code.ADDED_SOURCE_PATHS, frozenset())
        self.assertEqual(code.OLD_REPORT_UI, UI)
        self.assertEqual(code.REPORT_ASSETS['/naver/report-ui.js'], UI)
        self.assertEqual(code.REPORT_ASSETS['/naver/report-pdf.js'], PDF)
        self.assertNotIn(None, status.PASSIVE_RELEASES)
        for operation in ('prepare', 'apply'):
            adapters = [Mock() for _ in range(4)]
            with self.assertRaisesRegex(ValueError, '^CODE_ONLY_RELEASE_NOT_REVIEWED$'):
                getattr(policy, operation)({}, *adapters, code)
            self.assertTrue(all(not adapter.mock_calls for adapter in adapters))
        with self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
            rollback.require_review(policy, code)
        with self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
            policy.code_module_name(None)
        with self.assertRaisesRegex(ValueError, '^CODE_TARGET_NOT_PINNED$'):
            code.validate_package({}, Mock())
        with self.assertRaisesRegex(ValueError, '^CODE_ONLY_REQUIRED$'):
            code.apply({}, *[Mock() for _ in range(4)])

    def test_synthetic_review_selects_only_exact_target_and_inverse_scope(self):
        code, policy = configured()
        policy.require_review(code)
        self.assertEqual(policy.code_module_name(code.TARGET_COMMIT), MODULE)
        for value in (None, True, [], 'B'*40, 'refs/heads/'+'b'*40, 'b'*39, '0'*40):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
                policy.code_module_name(value)
        rollback = shared.load('naver_preview_code_rollback')
        with self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
            rollback.require_review(policy, code)
        rollback.REVIEWED_ROLLBACK_V19 = pins(code)+(PATHS,)
        rollback.REVIEWED_ROLLBACKS |= frozenset({rollback.REVIEWED_ROLLBACK_V19})
        rollback.require_review(policy, code)

    def test_all_pin_scope_asset_addition_and_route_mutations_close_before_host(self):
        for mutation in ('OLD_COMMIT', 'TARGET_COMMIT', 'OLD_SOURCE_SHA256', 'TARGET_SOURCE_SHA256',
                         'STORE_OLD', 'STORE_TARGET', 'EXPECTED_BASELINE', 'scope', 'added', 'route',
                         'owner_route', 'closed_route', 'tests', 'old_asset', 'new_asset'):
            code, policy = configured()
            if mutation.startswith('STORE_'):
                code.STORE_SHA256[mutation[6:].lower()] = '0'*64
            elif mutation == 'scope':
                code.CODE_PATHS |= {'naver_runtime/scheduler.py'}
            elif mutation == 'added':
                code.ADDED_SOURCE_PATHS |= {'naver_engine/unreviewed.py'}
            elif mutation == 'route':
                code.TARGET_ACTION_ROUTES += ('/spend/change',)
            elif mutation == 'owner_route':
                code.OWNER_ACTION_ROUTES += ('/spend/change',)
            elif mutation == 'closed_route':
                code.CLOSED_LINK_ROUTES = ()
            elif mutation == 'old_asset':
                code.OLD_REPORT_UI = (1, '0'*64, 'text/javascript; charset=utf-8')
            elif mutation == 'new_asset':
                code.REPORT_ASSETS['/naver/report-ui.js'] = (1, '0'*64, 'text/javascript; charset=utf-8')
            elif mutation == 'tests':
                code.TEST_PATHS = frozenset({'naver_engine/tests/unreviewed.py'})
            else:
                setattr(code, mutation, '0'*len(getattr(code, mutation)))
            for operation in ('prepare', 'apply'):
                adapters = [Mock() for _ in range(4)]
                with self.subTest(mutation=mutation, operation=operation), self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
                    getattr(policy, operation)({}, *adapters, code)
                self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_frozen_v18_functions_and_prior_asset_contracts_are_preserved(self):
        before, after = (ast.parse((TOOLS/(name+'.py')).read_bytes()) for name in ('naver_preview_code_upgrade_v18', MODULE))
        functions = lambda tree: {node.name: ast.dump(node, include_attributes=False) for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertEqual(functions(before), functions(after))
        previous = shared.load('naver_preview_code_upgrade_v18')
        code = shared.load(MODULE)
        self.assertEqual(previous.REPORT_ASSETS, code.REPORT_ASSETS)
        self.assertEqual(previous.TARGET_ACTION_ROUTES, code.TARGET_ACTION_ROUTES)
        self.assertEqual(previous.OWNER_ACTION_ROUTES, code.OWNER_ACTION_ROUTES)
        self.assertEqual(previous.CLOSED_LINK_ROUTES, code.CLOSED_LINK_ROUTES)
        policy, rollback = shared.load('naver_preview_code_only'), shared.load('naver_preview_code_rollback')
        for version in range(5, 19):
            previous = shared.load('naver_preview_code_upgrade_v'+str(version))
            self.assertEqual(getattr(policy, 'REVIEWED_TRANSITION_V'+str(version)), pins(previous))
            self.assertIn(rollback.transition(previous), rollback.REVIEWED_ROLLBACKS)
            policy.require_review(previous)
            rollback.require_review(policy, previous)


class V19ScopeTest(unittest.TestCase):
    def setUp(self):
        self.code, _ = configured()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.old, self.new = (Path(folder.name).resolve()/name for name in ('old', 'new'))
        self.before, self.after = shared.StoreScopeTest.SOURCE, shared.StoreScopeTest.SOURCE+b'\n# V19 recovery\n'
        self.code.STORE_SHA256 = {'old': hashlib.sha256(self.before).hexdigest(), 'target': hashlib.sha256(self.after).hexdigest()}
        compose = json.loads((Path(__file__).parent/'fixtures/v9-engine-compose-old.json').read_text())['compose'].encode()
        compose = compose.replace(b'    cpus: "0.50"\n', b'    cpus: "1.00"\n').replace(b'    mem_limit: 512m\n', b'    mem_limit: 768m\n')
        for root in (self.old, self.new):
            for name in ('compose.naver-relay.yml', 'deploy/naver-engine-backup.override.yml',
                         'Dockerfile.naver-engine', 'Dockerfile.naver-relay', 'backend/requirements.txt',
                         'naver_runtime/bootstrap.py', 'naver_runtime/scheduler.py', 'naver_engine/report_refresh.py',
                         'naver_engine/report_views.py', 'backend/naver_page/report-ui.js', 'backend/naver_page/report-pdf.js'):
                file = root/name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b'unchanged')
            (root/'compose.naver-engine.yml').write_bytes(compose)
            (root/'naver_engine/store.py').write_bytes(self.before if root == self.old else self.after)
            for name in ('engine', 'relay'):
                body = ('image: '+self.code.OLD_COMMIT).encode()
                (root/('preview-'+name+'.override.yml')).write_bytes(body if root == self.old else self.code.target_override(body, name))
        self.upgrade = Mock()
        self.upgrade.read_file.side_effect = lambda path, **kwargs: Path(path).read_bytes()

    def test_exact_store_only_forward_and_inverse_are_accepted(self):
        self.code.compatible_source(self.old, self.new, self.upgrade)
        self.code.compatible_inverse_source(self.new, self.old, self.upgrade)

    def test_added_removed_or_changed_non_store_files_are_closed_in_both_directions(self):
        added = self.new/'naver_engine/unreviewed.py'
        added.write_bytes(b'new')
        with self.assertRaisesRegex(ValueError, 'CODE_SCOPE_CHANGED'):
            self.code.compatible_source(self.old, self.new, self.upgrade)
        added.unlink()
        for name in ('backend/naver_page/report-ui.js', 'backend/naver_page/report-pdf.js',
                     'naver_engine/report_refresh.py', 'naver_runtime/scheduler.py'):
            file = self.new/name
            file.write_bytes(b'unreviewed')
            for method, roots in ((self.code.compatible_source, (self.old, self.new)),
                                  (self.code.compatible_inverse_source, (self.new, self.old))):
                with self.subTest(name=name, method=method.__name__), self.assertRaisesRegex(ValueError, 'CODE_SCOPE_CHANGED'):
                    method(*roots, self.upgrade)
            file.write_bytes(b'unchanged')
            file.unlink()
            with self.assertRaisesRegex(ValueError, 'CODE_SOURCE_REMOVED'):
                self.code.compatible_source(self.old, self.new, self.upgrade)
            file.write_bytes(b'unchanged')

    def test_store_symlink_mode_schema_and_infrastructure_changes_are_closed(self):
        file = self.new/'naver_engine/store.py'
        file.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'CODE_SOURCE_MODE_CHANGED'):
            self.code.compatible_source(self.old, self.new, self.upgrade)
        file.chmod(0o644)
        file.unlink()
        file.symlink_to(self.old/'naver_engine/store.py')
        with self.assertRaisesRegex(ValueError, 'CODE_SOURCE_PATH'):
            self.code.compatible_code_scope(self.old, self.new, self.upgrade)
        file.unlink()
        for body in (self.after.replace(b'SCHEMA_VERSION=11', b'SCHEMA_VERSION=12'),
                     self.after+b'\n_SCHEMA += ("CREATE TABLE bad(id INTEGER)",)\n'):
            file.write_bytes(body)
            self.code.STORE_SHA256['target'] = hashlib.sha256(body).hexdigest()
            with self.assertRaisesRegex(ValueError, 'CODE_SCHEMA_CHANGED'):
                self.code.compatible_source(self.old, self.new, self.upgrade)
        file.write_bytes(self.after)
        self.code.STORE_SHA256['target'] = hashlib.sha256(self.after).hexdigest()
        (self.new/'compose.naver-engine.yml').write_bytes(b'unreviewed')
        with self.assertRaisesRegex(ValueError, 'CODE_INFRASTRUCTURE_CHANGED'):
            self.code.compatible_source(self.old, self.new, self.upgrade)


class V19ControllerTest(unittest.TestCase):
    def test_synthetic_forward_and_failure_return_preserve_database_and_source_history(self):
        for failure in (None, 'recreate', 'start', 'stop', 'probe'):
            with self.subTest(failure=failure), patch.object(shared.sqlite3, 'connect', side_effect=AssertionError('DB forbidden')):
                result, commands, writes, restored, state = shared.ContractTest().scenario(failure, code_only=True, code_module=MODULE)
            if failure is None:
                self.assertTrue(result['ok'])
                self.assertEqual(set(state.values()), {'b'*40})
                self.assertFalse(result['database_opened_by_controller'])
                self.assertFalse(result['source_warmup_performed'])
            else:
                self.assertEqual(str(result), 'CODE_ONLY_FAILED_ROLLED_BACK')
                self.assertEqual(set(state.values()), {OLD})
                self.assertTrue(restored)
            self.assertFalse(any('exec' in args or 'run' in args for args in commands))
            self.assertFalse(any('nginx' in ' '.join(args) for args in commands))
            self.assertFalse(any(path.name == 'bootstrap-request.json' or path.parent.name == 'secrets' for path, _ in writes))

    def test_prepare_never_starts_services_opens_database_or_changes_secrets(self):
        with patch.object(shared.sqlite3, 'connect', side_effect=AssertionError('DB forbidden')):
            result, commands, writes, restored, state = shared.ContractTest().scenario(mode='prepare', code_only=True, code_module=MODULE)
        self.assertTrue(result['ok'])
        self.assertFalse(result['services_started'])
        self.assertFalse(result['database_opened_by_controller'])
        self.assertEqual(set(state.values()), {OLD})
        self.assertFalse(any(args[:2] == ['/usr/bin/systemctl', 'start'] for args in commands))
        self.assertTrue(any(args[:2] == ['docker', 'build'] for args in commands))
        self.assertFalse(any(path.name == 'bootstrap-request.json' or path.parent.name == 'secrets' for path, _ in writes))

    def test_post_success_rollback_preserves_database_history_and_stops_on_failure(self):
        import test_naver_preview_code_rollback as reverse
        case = reverse.PostSuccessRollbackTest()
        self.addCleanup(case.doCleanups)
        for fault in (None, 'writer', 'source_after_stop', 'recreate', 'start', 'probe_old'):
            fixture = case.fixture(fault, code_module=MODULE)
            with self.subTest(fault=fault):
                if fault is None:
                    result = case.run_fixture(fixture)
                    self.assertTrue(result['ok'])
                    self.assertEqual(result['source_commit'], OLD)
                    self.assertFalse(result['database_opened_by_controller'])
                    self.assertEqual(set(fixture['state'].values()), {OLD})
                else:
                    with self.assertRaisesRegex(RuntimeError, '^CODE_POST_ROLLBACK_FAILED$'):
                        case.run_fixture(fixture)
                    self.assertTrue(all(fixture['active'][unit] == 'inactive' for unit in fixture['lifecycle'].UNITS))
                for path, body in fixture['historical_bytes'].items():
                    self.assertEqual(path.read_bytes(), body)
                self.assertFalse(any('exec' in args or 'run' in args for args in fixture['commands']))


class V19TransportTest(unittest.TestCase):
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

    def test_three_actual_bundles_roundtrip_with_original_limits(self):
        import base64, gzip, zlib
        encode, decode, _ = shared.ContractTest().workflow_transport()
        for kind, bundle in self.bundles().items():
            raw = json.dumps(bundle).encode()
            with self.subTest(kind=kind):
                self.assertLessEqual(len(raw), 229376 if kind == 'prepare' else 229376)
                if kind == 'prepare':
                    wire = 'prepare-gzip-v1:'+base64.b64encode(gzip.compress(raw, mtime=0)).decode()
                    self.assertLessEqual(len(wire), 73728)
                    decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
                    unpacked = decoder.decompress(base64.b64decode(wire[len('prepare-gzip-v1:'):], validate=True), 229377)
                    self.assertLessEqual(len(unpacked), 229376)
                    self.assertTrue(decoder.eof)
                    self.assertFalse(decoder.unused_data or decoder.unconsumed_tail)
                    self.assertEqual(json.loads(unpacked), bundle)
                else:
                    wire = encode(bundle)
                    self.assertLessEqual(len(wire), 73728)
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
