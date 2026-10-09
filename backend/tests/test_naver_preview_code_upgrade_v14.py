"""V14 closed source/route/schema contracts; only temporary synthetic files and adapters."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared


MODULE = 'naver_preview_code_upgrade_v14'
TARGET = '153c9a3a89585b00f2973a694a963ae9227ce19d'
TARGET_ARCHIVE = 'd9be1b9e6225c856d06b8b6e2d5f1e91edfa46a2cb0aa94d4f17497877eceaf8'
TARGET_STORE = 'ccb0474dd764d06bb375cd298eb01b333a6503d8db06d3784f2f7599d19afe97'
OLD = 'ecb26ccee4aa8d85b0101e0d59aeafe48de1166b'
OLD_ARCHIVE = '6c0f7382676584a5d2c01fd0d54b169210293a58c654c70e5638e4fad2cbfcad'
OLD_STORE = 'be894a56d4b548700b14c2d8ffd95669ebfac73ead8e6521fb50a5bc9add14af'
HOST = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
COMPOSE = '62e33c3d2815579a28031973b956cd36031171f26ead4e21ad2d72adfe2a5ef7'
EXISTING = {'naver_engine/reporting.py', 'naver_engine/report_views.py', 'naver_engine/store.py',
            'naver_engine/web.py', 'backend/naver_page/report-ui.js', 'backend/naver_page/report-pdf.js',
            'backend/naver_page/app.css', 'backend/naver_page/app.js'}
ADDED = frozenset({'naver_engine/report_enrichment.py', 'naver_engine/report_notes.py'})
PATHS = EXISTING | ADDED


def pins(code):
    return (code.OLD_COMMIT, code.TARGET_COMMIT, code.OLD_SOURCE_SHA256, code.TARGET_SOURCE_SHA256,
            code.STORE_SHA256['old'], code.STORE_SHA256['target'], code.EXPECTED_BASELINE)


def configured():
    code, policy = shared.sealed_code(MODULE), shared.load('naver_preview_code_only')
    policy.REVIEWED_TRANSITION_V14 = pins(code)
    return code, policy


class V14PinsTest(unittest.TestCase):
    def test_closed_registry_has_no_selector_prepare_apply_rollback_or_passive_authority(self):
        code, policy = shared.load(MODULE), shared.load('naver_preview_code_only')
        rollback, status = shared.load('naver_preview_code_rollback'), shared.load('naver_preview_collection_status')
        reviewed = (OLD, TARGET, OLD_ARCHIVE, TARGET_ARCHIVE, OLD_STORE, TARGET_STORE, HOST)
        self.assertEqual(pins(code), reviewed)
        self.assertEqual(policy.REVIEWED_TRANSITION_V14, reviewed)
        self.assertEqual(rollback.REVIEWED_ROLLBACK_V14, reviewed+(frozenset(PATHS),))
        if TARGET is not None:
            policy.require_review(code)
            rollback.require_review(policy, code)
            self.assertEqual(policy.code_module_name(TARGET), MODULE)
            self.assertEqual(status.PASSIVE_RELEASES[TARGET], (TARGET_ARCHIVE, TARGET_STORE, HOST))
            self.assertNotIn(TARGET, status.PROFILE_RELEASES)
        # Pending authority remains closed even after the final tuple is reviewed.
        expected = (OLD, None, OLD_ARCHIVE, None, OLD_STORE, None, HOST)
        code.TARGET_COMMIT = code.TARGET_SOURCE_SHA256 = None
        code.STORE_SHA256['target'] = None
        policy.REVIEWED_TRANSITION_V14 = expected
        rollback.REVIEWED_ROLLBACKS -= frozenset({rollback.REVIEWED_ROLLBACK_V14})
        rollback.REVIEWED_ROLLBACK_V14 = expected+(frozenset(PATHS),)
        status.PASSIVE_COMMIT_V14 = None
        self.assertEqual(pins(code), expected)
        self.assertEqual(policy.REVIEWED_TRANSITION_V14, expected)
        self.assertEqual(rollback.REVIEWED_ROLLBACK_V14, expected+(frozenset(PATHS),))
        self.assertNotIn(rollback.REVIEWED_ROLLBACK_V14, rollback.REVIEWED_ROLLBACKS)
        self.assertIsNone(status.PASSIVE_COMMIT_V14)
        self.assertNotIn(None, status.PASSIVE_RELEASES)
        self.assertNotIn(None, status.PROFILE_RELEASES)
        self.assertEqual(code.CODE_PATHS, PATHS)
        self.assertEqual(code.ADDED_SOURCE_PATHS, ADDED)
        self.assertEqual(code.TARGET_ACTION_ROUTES, ('/reports/notes',))
        self.assertEqual(code.ENGINE_COMPOSE_SHA256, COMPOSE)
        for operation in ('prepare', 'apply'):
            adapters = [Mock() for _ in range(4)]
            with self.assertRaisesRegex(ValueError, '^CODE_ONLY_RELEASE_NOT_REVIEWED$'):
                getattr(policy, operation)({}, *adapters, code)
            self.assertTrue(all(not adapter.mock_calls for adapter in adapters))
        with self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
            policy.code_module_name(None)

    def test_all_new_pin_scope_addition_and_route_mutations_close_before_host(self):
        for mutation in ('OLD_COMMIT', 'TARGET_COMMIT', 'OLD_SOURCE_SHA256', 'TARGET_SOURCE_SHA256',
                         'STORE_OLD', 'STORE_TARGET', 'EXPECTED_BASELINE', 'scope', 'added', 'route', 'tests'):
            code, policy = configured()
            if mutation.startswith('STORE_'):
                code.STORE_SHA256[mutation[6:].lower()] = '0'*64
            elif mutation == 'scope':
                code.CODE_PATHS |= {'naver_runtime/scheduler.py'}
            elif mutation == 'added':
                code.ADDED_SOURCE_PATHS |= {'naver_engine/unreviewed.py'}
            elif mutation == 'route':
                code.TARGET_ACTION_ROUTES += ('/spend/change',)
            elif mutation == 'tests':
                code.TEST_PATHS = frozenset({'naver_engine/tests/unreviewed.py'})
            else:
                setattr(code, mutation, '0'*len(getattr(code, mutation)))
            for operation in ('prepare', 'apply'):
                adapters = [Mock() for _ in range(4)]
                with self.subTest(mutation=mutation, operation=operation), self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
                    getattr(policy, operation)({}, *adapters, code)
                self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_complete_synthetic_pin_selects_only_exact_target_and_assets_must_be_pinned(self):
        code, policy = configured()
        policy.require_review(code)
        self.assertEqual(policy.code_module_name(code.TARGET_COMMIT), MODULE)
        for value in (None, True, [], 'B'*40, 'refs/heads/'+'b'*40, 'b'*39, '0'*40):
            with self.subTest(kind=type(value).__name__), self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
                policy.code_module_name(value)
        code.REPORT_ASSETS['/naver/report-ui.js'] = (None, None, 'text/javascript; charset=utf-8')
        host, release, life, upgrade = Mock(), Mock(), Mock(), Mock()
        with self.assertRaisesRegex(ValueError, '^CODE_TARGET_NOT_PINNED$'):
            code.prepare({}, host, release, life, upgrade)
        self.assertTrue(all(not adapter.mock_calls for adapter in (host, life, upgrade)))

    def test_prior_releases_keep_exact_forward_reverse_and_passive_tuples(self):
        policy, rollback, status = (shared.load(name) for name in
                                   ('naver_preview_code_only', 'naver_preview_code_rollback', 'naver_preview_collection_status'))
        for version in range(5, 14):
            code = shared.load('naver_preview_code_upgrade_v'+str(version))
            with self.subTest(version=version):
                self.assertEqual(getattr(policy, 'REVIEWED_TRANSITION_V'+str(version)), pins(code))
                self.assertIn(rollback.transition(code), rollback.REVIEWED_ROLLBACKS)
                self.assertEqual(policy.code_module_name(code.TARGET_COMMIT), 'naver_preview_code_upgrade_v'+str(version))
                policy.require_review(code)
                rollback.require_review(policy, code)
                self.assertEqual(status.PASSIVE_RELEASES[code.TARGET_COMMIT],
                                 (code.TARGET_SOURCE_SHA256, code.STORE_SHA256['target'], HOST))


class V14ScopeTest(unittest.TestCase):
    def setUp(self):
        self.code, _ = configured()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.old, self.new = (Path(folder.name).resolve()/name for name in ('old', 'new'))
        self.before = shared.StoreScopeTest.SOURCE
        self.after = self.before+b'\n# synthetic V14 annotations methods only\n'
        self.code.STORE_SHA256 = {'old': hashlib.sha256(self.before).hexdigest(),
                                  'target': hashlib.sha256(self.after).hexdigest()}
        compose = json.loads((Path(__file__).parent/'fixtures/v9-engine-compose-old.json').read_text())['compose'].encode()
        compose = compose.replace(b'    cpus: "0.50"\n', b'    cpus: "1.00"\n').replace(b'    mem_limit: 512m\n', b'    mem_limit: 768m\n')
        self.assertEqual(hashlib.sha256(compose).hexdigest(), COMPOSE)
        for root in (self.old, self.new):
            for name in ('compose.naver-relay.yml', 'deploy/naver-engine-backup.override.yml',
                         'Dockerfile.naver-engine', 'Dockerfile.naver-relay', 'backend/requirements.txt',
                         'naver_runtime/bootstrap.py', 'naver_runtime/scheduler.py'):
                file = root/name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b'unchanged')
            (root/'compose.naver-engine.yml').write_bytes(compose)
            for name in EXISTING | (ADDED if root == self.new else set()):
                file = root/name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b'old' if root == self.old else b'new')
            (root/'naver_engine/store.py').write_bytes(self.before if root == self.old else self.after)
            for name in ('engine', 'relay'):
                original = ('image: '+self.code.OLD_COMMIT).encode()
                (root/('preview-'+name+'.override.yml')).write_bytes(original if root == self.old else self.code.target_override(original, name))
        self.upgrade = Mock()
        self.upgrade.read_file.side_effect = lambda path, **kwargs: Path(path).read_bytes()

    def test_eight_changes_two_added_modules_and_exact_inverse_are_accepted(self):
        self.code.compatible_source(self.old, self.new, self.upgrade)
        self.code.compatible_inverse_source(self.new, self.old, self.upgrade)
        old_helper = shared.load('naver_preview_code_upgrade_v13')
        with self.assertRaisesRegex(ValueError, '^CODE_SOURCE_REMOVED$'):
            old_helper.compatible_code_scope(self.new, self.old, self.upgrade)

    def test_only_exact_two_new_paths_can_be_added_removed_or_replaced(self):
        for name in ('naver_engine/report_other.py', 'naver_engine/web.py', 'naver_runtime/unreviewed.py'):
            file = self.new/name
            original = file.read_bytes() if file.exists() else None
            if original is not None:
                (self.old/name).unlink()
            file.write_bytes(b'added but unreviewed')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'CODE_SCOPE_CHANGED'):
                self.code.compatible_code_scope(self.old, self.new, self.upgrade)
            if original is None:
                file.unlink()
            else:
                file.write_bytes(original)
                (self.old/name).write_bytes(b'old')
        for name in ADDED:
            file = self.new/name
            file.unlink()
            with self.subTest(missing=name), self.assertRaisesRegex(ValueError, 'CODE_SCOPE_CHANGED'):
                self.code.compatible_source(self.old, self.new, self.upgrade)
            file.write_bytes(b'new')
        removed = self.new/'naver_engine/reporting.py'
        removed.unlink()
        with self.assertRaisesRegex(ValueError, '^CODE_SOURCE_REMOVED$'):
            self.code.compatible_source(self.old, self.new, self.upgrade)

    def test_new_module_symlinks_modes_and_other_changed_paths_are_closed(self):
        added = self.new/'naver_engine/report_notes.py'
        added.chmod(0o755)
        with self.assertRaisesRegex(ValueError, '^CODE_SOURCE_MODE_CHANGED$'):
            self.code.compatible_source(self.old, self.new, self.upgrade)
        added.chmod(0o644)
        added.unlink()
        added.symlink_to(self.new/'naver_engine/report_enrichment.py')
        with self.assertRaisesRegex(ValueError, '^CODE_SOURCE_PATH$'):
            self.code.compatible_source(self.old, self.new, self.upgrade)
        added.unlink()
        added.write_bytes(b'new')
        (self.new/'naver_runtime/scheduler.py').write_bytes(b'outside scope')
        with self.assertRaisesRegex(ValueError, '^CODE_SCOPE_CHANGED$'):
            self.code.compatible_source(self.old, self.new, self.upgrade)

    def test_schema_sql_and_compose_changes_are_closed_even_with_synthetic_store_repin(self):
        for body in (self.after.replace(b'SCHEMA_VERSION=11', b'SCHEMA_VERSION=12'),
                     self.after+b'\n_SCHEMA += ("CREATE TABLE unreviewed (id INTEGER)",)\n'):
            (self.new/'naver_engine/store.py').write_bytes(body)
            self.code.STORE_SHA256['target'] = hashlib.sha256(body).hexdigest()
            with self.assertRaisesRegex(ValueError, '^CODE_SCHEMA_CHANGED$'):
                self.code.compatible_source(self.old, self.new, self.upgrade)
        (self.new/'naver_engine/store.py').write_bytes(self.after)
        self.code.STORE_SHA256['target'] = hashlib.sha256(self.after).hexdigest()
        (self.new/'compose.naver-engine.yml').write_bytes(b'new infrastructure')
        with self.assertRaisesRegex(ValueError, '^CODE_INFRASTRUCTURE_CHANGED$'):
            self.code.compatible_source(self.old, self.new, self.upgrade)


class V14RouteTest(unittest.TestCase):
    def test_notes_post_is_401_only_on_target_and_any_other_reply_refuses(self):
        for target, notes_status, accepted in ((True, 401, True), (False, 403, True),
                                               (True, 200, False), (True, 403, False), (False, 401, False)):
            code, _ = configured()
            source = code.TARGET_COMMIT if target else code.OLD_COMMIT
            release = Mock()
            def read(path, route, method='GET'):
                if shared.asset_response(code, route):
                    return shared.asset_response(code, route)
                if route == '/_engine/health':
                    return 200, {}, b'{}'
                if route in ('/naver/', '/naver/dashboard'):
                    return 200, {'referrer-policy': 'no-referrer', 'cache-control': 'no-store'}, b'verificationNotice id="s-dashboard"'
                if route == '/api/naver-auto/reports/notes':
                    return notes_status, {}, b''
                verified = ('/links/confirm', '/collection/request', '/management/update', '/management/collect', '/reports/review',
                            *shared.opened_routes(code, source))
                return (401 if method == 'GET' or route.removeprefix('/api/naver-auto') in verified else 403), {}, b''
            release.unix_request.side_effect = read
            with self.subTest(target=target, notes_status=notes_status):
                if accepted:
                    code.probe(release, source, shared.load('naver_preview_upgrade'))
                else:
                    with self.assertRaisesRegex(ValueError, '^CODE_ROUTE_STATUS$'):
                        code.probe(release, source, shared.load('naver_preview_upgrade'))


class V14ApplyTest(unittest.TestCase):
    def test_synthetic_forward_apply_and_failure_return_preserve_database_and_source_history(self):
        for failure in (None, 'recreate', 'start', 'stop', 'probe'):
            with self.subTest(failure=failure), patch.object(shared.sqlite3, 'connect', side_effect=AssertionError('DB forbidden')):
                result, commands, writes, restored, state = shared.ContractTest().scenario(
                    failure, code_only=True, code_module=MODULE)
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


class V14TransportTest(unittest.TestCase):
    def bundles(self):
        tools = Path(__file__).parents[1]/'tools'
        common = {key: (tools/(name+'.py')).read_text() for key, name in {
            'code_source': MODULE, 'release_source': 'naver_preview_release',
            'host_source': 'naver_erp_tunnel_service_install', 'lifecycle_source': 'naver_preview_lifecycle',
            'upgrade_source': 'naver_preview_upgrade'}.items()}
        release = dict(baseline=HOST, source_commit='b'*40, source_tar_gz_sha256='d'*64,
                       ciphertext_sha256='c'*64, run_id='123456', operation='code-prepare')
        forward = dict(common, operation='preview-code-only-upgrade', function='apply',
                       source=(tools/'naver_preview_code_only.py').read_text(),
                       package={'release': release, 'operation_id': '9'*32})
        reverse = dict(common, operation='preview-code-only-rollback', function='run',
                       source=(tools/'naver_preview_code_rollback.py').read_text(),
                       code_only_source=(tools/'naver_preview_code_only.py').read_text(),
                       package={'release': release, 'apply_operation_id': '9'*32, 'operation_id': '8'*32})
        return forward, reverse

    def test_forward_and_inverse_bundle_fit_original_wire_limits(self):
        encode, decode, _ = shared.ContractTest().workflow_transport()
        for bundle in self.bundles():
            with self.subTest(operation=bundle['operation']):
                self.assertLessEqual(len(json.dumps(bundle).encode()), 196608)
                wire = encode(bundle)
                self.assertLessEqual(len(wire), 65536)
                self.assertEqual(decode(wire), bundle)
        forward = self.bundles()[0]
        prepare = dict(forward, operation='preview-code-only-prepare', function='prepare',
                       code_only_source=forward['source'], source=forward['code_source'], package=forward['package']['release'])
        prepare.pop('code_source')
        self.assertLessEqual(len(json.dumps(prepare).encode()), 180000)

    def test_unpinned_forward_and_inverse_remote_scripts_refuse_before_host_action(self):
        import test_naver_preview_code_only as legacy
        encode, _, remote = shared.ContractTest().workflow_transport()
        for bundle in self.bundles():
            # Execute an explicitly unpinned helper, irrespective of final source pins.
            import ast
            source = bundle['code_source']
            node = next(n for n in ast.parse(source).body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'TARGET_COMMIT' for t in n.targets))
            lines = source.splitlines(True)
            lines[node.lineno-1:node.end_lineno] = ['TARGET_COMMIT = None\n']
            bundle['code_source'] = ''.join(lines)
            bundle['host_source'] = 'class NativeHost:\n    def baseline(self): raise AssertionError("PRIVATE_HOST_ACTION")\n'
            status, result = legacy.CodeOnlyTest().run_remote_script(remote, 'PREVIEW_OPS_B64', encode(bundle), 'NAVER_PREVIEW_OPS=')
            self.assertEqual(status, 1)
            self.assertEqual(result['error_code'], 'CODE_ONLY_RELEASE_NOT_REVIEWED')
            self.assertNotIn('PRIVATE', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
