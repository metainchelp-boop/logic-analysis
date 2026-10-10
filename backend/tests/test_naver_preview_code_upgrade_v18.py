"""V18 closed source/route/schema contracts; only temporary synthetic files and adapters."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared


MODULE = 'naver_preview_code_upgrade_v18'
TARGET = '7f32d70d97876b806cc5bc44a7cc0f9688caeada'
TARGET_ARCHIVE = 'd6a2d1fe521287c9cedfba1132e5a81164ed2e2745ddea7ea01d74c2beb80a13'
TARGET_STORE = 'b01a1e21cc87df1ef5a3935a30cc25d96b0ec3ced0fcc42a2bc9999685ef7d95'
OLD = '7c99e18e29e6cb4d3f32eb41b6983529126d8f3a'
OLD_ARCHIVE = '874ea72edfef7c5a375f26cf8bdb103aa487779bd06e208aada7b1a5184dcee2'
OLD_STORE = 'cc050c8c3d8c0d2a8e4977ec0e8e5b271ff7fc932a8d35a6c0f10dadc11ddb56'
HOST = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
COMPOSE = '62e33c3d2815579a28031973b956cd36031171f26ead4e21ad2d72adfe2a5ef7'
EXISTING = {'naver_engine/report_views.py', 'naver_engine/store.py', 'backend/naver_page/report-ui.js'}
ADDED = frozenset({'naver_engine/report_refresh.py'})
PATHS = EXISTING | ADDED


def pins(code):
    return (code.OLD_COMMIT, code.TARGET_COMMIT, code.OLD_SOURCE_SHA256, code.TARGET_SOURCE_SHA256,
            code.STORE_SHA256['old'], code.STORE_SHA256['target'], code.EXPECTED_BASELINE)


def configured():
    code, policy = shared.sealed_code(MODULE), shared.load('naver_preview_code_only')
    policy.REVIEWED_TRANSITION_V18 = pins(code)
    policy.REVIEWED_OLD_REPORT_UI_V18 = code.OLD_REPORT_UI
    return code, policy


class V18PinsTest(unittest.TestCase):
    def test_closed_registry_has_no_selector_prepare_apply_rollback_or_passive_authority(self):
        code, policy = shared.load(MODULE), shared.load('naver_preview_code_only')
        rollback, status = shared.load('naver_preview_code_rollback'), shared.load('naver_preview_collection_status')
        reviewed = (OLD, TARGET, OLD_ARCHIVE, TARGET_ARCHIVE, OLD_STORE, TARGET_STORE, HOST)
        self.assertEqual(pins(code), reviewed)
        self.assertEqual(policy.REVIEWED_TRANSITION_V18, reviewed)
        self.assertEqual(rollback.REVIEWED_ROLLBACK_V18, reviewed+(frozenset(PATHS),))
        if TARGET_ARCHIVE is not None:
            policy.require_review(code)
            rollback.require_review(policy, code)
            self.assertEqual(policy.code_module_name(TARGET), MODULE)
            self.assertEqual(status.PASSIVE_RELEASES[TARGET], (TARGET_ARCHIVE, TARGET_STORE, HOST))
            self.assertNotIn(TARGET, status.PROFILE_RELEASES)
        else:
            with self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
                policy.require_review(code)
            self.assertNotIn(TARGET, status.PASSIVE_RELEASES)
        # Pending authority remains closed even after the final tuple is reviewed.
        expected = (OLD, None, OLD_ARCHIVE, None, OLD_STORE, None, HOST)
        code.TARGET_COMMIT = code.TARGET_SOURCE_SHA256 = None
        code.STORE_SHA256['target'] = None
        policy.REVIEWED_TRANSITION_V18 = expected
        rollback.REVIEWED_ROLLBACKS -= frozenset({rollback.REVIEWED_ROLLBACK_V18})
        rollback.REVIEWED_ROLLBACK_V18 = expected+(frozenset(PATHS),)
        status.PASSIVE_COMMIT_V18 = None
        self.assertEqual(pins(code), expected)
        self.assertEqual(policy.REVIEWED_TRANSITION_V18, expected)
        self.assertEqual(rollback.REVIEWED_ROLLBACK_V18, expected+(frozenset(PATHS),))
        self.assertNotIn(rollback.REVIEWED_ROLLBACK_V18, rollback.REVIEWED_ROLLBACKS)
        self.assertIsNone(status.PASSIVE_COMMIT_V18)
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
                         'STORE_OLD', 'STORE_TARGET', 'EXPECTED_BASELINE', 'scope', 'added', 'route', 'owner_route', 'closed_route', 'tests', 'old_asset'):
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
        for version in range(5, 18):
            code = shared.load('naver_preview_code_upgrade_v'+str(version))
            with self.subTest(version=version):
                self.assertEqual(getattr(policy, 'REVIEWED_TRANSITION_V'+str(version)), pins(code))
                self.assertIn(rollback.transition(code), rollback.REVIEWED_ROLLBACKS)
                self.assertEqual(policy.code_module_name(code.TARGET_COMMIT), 'naver_preview_code_upgrade_v'+str(version))
                policy.require_review(code)
                rollback.require_review(policy, code)
                self.assertEqual(status.PASSIVE_RELEASES[code.TARGET_COMMIT],
                                 (code.TARGET_SOURCE_SHA256, code.STORE_SHA256['target'], HOST))


class V18ScopeTest(unittest.TestCase):
    def setUp(self):
        self.code, _ = configured()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.old, self.new = (Path(folder.name).resolve()/name for name in ('old', 'new'))
        self.before = shared.StoreScopeTest.SOURCE
        self.after = self.before+b"\n# V18 read projection adapter\n"
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
            (root/'naver_engine').mkdir(exist_ok=True)
            (root/'naver_engine/store.py').write_bytes(self.before if root == self.old else self.after)
            for name in ('engine', 'relay'):
                original = ('image: '+self.code.OLD_COMMIT).encode()
                (root/('preview-'+name+'.override.yml')).write_bytes(original if root == self.old else self.code.target_override(original, name))
        self.upgrade = Mock()
        self.upgrade.read_file.side_effect = lambda path, **kwargs: Path(path).read_bytes()

    def test_exact_three_existing_paths_one_added_path_and_inverse_are_accepted(self):
        self.code.compatible_source(self.old, self.new, self.upgrade)
        self.code.compatible_inverse_source(self.new, self.old, self.upgrade)

    def test_no_production_path_can_be_added_or_removed(self):
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
        removed = self.new/'backend/naver_page/report-ui.js'
        removed.unlink()
        with self.assertRaisesRegex(ValueError, '^CODE_SOURCE_REMOVED$'):
            self.code.compatible_source(self.old, self.new, self.upgrade)

    def test_symlinks_modes_and_other_changed_paths_are_closed(self):
        added = self.new/'naver_engine/report_refresh.py'
        added.chmod(0o755)
        with self.assertRaisesRegex(ValueError, '^CODE_SOURCE_MODE_CHANGED$'):
            self.code.compatible_source(self.old, self.new, self.upgrade)
        added.chmod(0o644)
        added.unlink()
        added.symlink_to(self.new/'naver_engine/store.py')
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


class V18RouteTest(unittest.TestCase):
    def test_notes_post_stays_401_on_both_sides_and_any_other_reply_refuses(self):
        for target, notes_status, accepted in ((True, 401, True), (False, 401, True),
                                               (True, 200, False), (True, 403, False), (False, 403, False), (False, 200, False)):
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


class V18SourceAssetTest(unittest.TestCase):
    def fixture(self, source, served_body):
        code, _ = configured()
        old_body, target_body = b'old reviewed UI', b'new reviewed UI refresh'
        code.OLD_REPORT_UI = (len(old_body), hashlib.sha256(old_body).hexdigest(), 'text/javascript; charset=utf-8')
        code.REPORT_ASSETS['/naver/report-ui.js'] = (len(target_body), hashlib.sha256(target_body).hexdigest(), 'text/javascript; charset=utf-8')
        release = Mock()
        def read(path, route, method='GET'):
            if route == '/naver/report-ui.js':
                return 200, {'content-type':'text/javascript; charset=utf-8','cache-control':'no-store',
                    'x-content-type-options':'nosniff','referrer-policy':'no-referrer'}, served_body
            if route in code.REPORT_ASSETS:
                return shared.asset_response(code, route)
            if route == '/naver/dashboard':
                return 200, {'referrer-policy':'no-referrer','cache-control':'no-store'}, b'id="s-dashboard"'
            key = route.removeprefix('/api/naver-auto')
            return (403 if key in code.CLOSED_LINK_ROUTES else 401), {}, b''
        release.unix_request.side_effect = read
        return code, release, code.OLD_COMMIT if source == 'old' else code.TARGET_COMMIT, old_body, target_body

    def test_old_and_target_probes_accept_only_their_own_bytes(self):
        for source, body in (('old', b'old reviewed UI'), ('target', b'new reviewed UI refresh')):
            code, release, commit, _, _ = self.fixture(source, body)
            with self.subTest(source=source):
                code.probe(release, commit, Mock())

    def test_crossed_old_and_target_bytes_refuse_and_cannot_claim_rollback_ready(self):
        for source, body in (('old', b'new reviewed UI refresh'), ('target', b'old reviewed UI')):
            code, release, commit, _, _ = self.fixture(source, body)
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, '^REPORT_ASSET_NOT_READY$'):
                code.probe(release, commit, Mock())


class V18ApplyTest(unittest.TestCase):
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


class V18PrepareTest(unittest.TestCase):
    def test_prepare_builds_in_isolation_without_start_or_database_actions(self):
        with patch.object(shared.sqlite3, 'connect', side_effect=AssertionError('DB forbidden')):
            result, commands, writes, restored, state = shared.ContractTest().scenario(
                mode='prepare', code_only=True, code_module=MODULE)
        self.assertTrue(result['ok'])
        self.assertFalse(result['services_started'])
        self.assertFalse(result['database_opened_by_controller'])
        self.assertEqual(set(state.values()), {OLD})
        self.assertFalse(any(args[:2] == ['/usr/bin/systemctl', 'start'] for args in commands))
        self.assertTrue(any(args[:2] == ['docker', 'build'] for args in commands))
        self.assertFalse(any(path.name == 'bootstrap-request.json' or path.parent.name == 'secrets'
                             for path, _ in writes))


class V18PassiveTest(unittest.TestCase):
    def test_exact_v18_passive_path_never_opens_database_or_active_profile(self):
        import test_naver_preview_collection_status as passive
        code, _ = configured()
        case = passive.CollectionTest()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.run_log_results = []
        reviewed = dict(passive.M.PASSIVE_RELEASES)
        reviewed[code.TARGET_COMMIT] = (code.TARGET_SOURCE_SHA256, code.STORE_SHA256['target'], HOST)
        with patch.object(passive.M, 'PASSIVE_RELEASES', reviewed), \
             patch.object(passive.M.sqlite3, 'connect', side_effect=AssertionError('DB forbidden')), \
             patch.object(passive.M, 'collect_login_audit', side_effect=AssertionError('DB read forbidden')), \
             patch.object(passive.M, 'script', side_effect=AssertionError('reader script forbidden')):
            case.check_run_diagnostics(code.TARGET_COMMIT, passive=True, logs={'d'*64:b'', '7'*64:b''})
        self.assertEqual(len(case.run_log_results), 1)
        self.assertFalse(case.run_log_results[0]['database_opened'])
        self.assertNotIn(code.TARGET_COMMIT, passive.M.PROFILE_RELEASES)

    def test_v18_pin_mismatch_or_active_mode_refuses_before_host_and_process(self):
        status = shared.load('naver_preview_collection_status')
        code, _ = configured()
        status.PASSIVE_RELEASES[code.TARGET_COMMIT] = (code.TARGET_SOURCE_SHA256, code.STORE_SHA256['target'], HOST)
        good = dict(source_commit=code.TARGET_COMMIT, source_tar_gz_sha256=code.TARGET_SOURCE_SHA256,
                    baseline=HOST, passive_runtime_only=True)
        for field in ('source_tar_gz_sha256', 'baseline'):
            host, release = Mock(), Mock()
            with self.subTest(field=field), patch.object(status, 'capture_process') as process:
                with self.assertRaisesRegex(ValueError, '^PASSIVE_SOURCE_PIN_CHANGED$'):
                    status.run(dict(good, **{field:'0'*64}), host, release)
                process.assert_not_called()
            self.assertFalse(host.mock_calls or release.mock_calls)
        for mode in (None, 'latency_profile_only', 'dashboard_profile_only'):
            package = {key:value for key,value in good.items() if key != 'passive_runtime_only'}
            if mode:
                package[mode] = True
            host, release = Mock(), Mock()
            with self.subTest(mode=mode), patch.object(status, 'capture_process') as process:
                with self.assertRaisesRegex(ValueError, '^(PASSIVE_RUNTIME_ONLY|PROFILE_SOURCE_UNREVIEWED)$'):
                    status.run(package, host, release)
                process.assert_not_called()
            self.assertFalse(host.mock_calls or release.mock_calls)


class V18TransportTest(unittest.TestCase):
    def actual_bundles(self):
        tools = Path(__file__).parents[1]/'tools'
        source = lambda name: (tools/(name+'.py')).read_text()
        release = dict(baseline=HOST, source_commit=TARGET, source_tar_gz_sha256=TARGET_ARCHIVE,
                       ciphertext_sha256='c'*64, run_id='12345678901', operation='code-prepare')
        prepare = dict(package=release, source=source('naver_preview_release'),
                       host_source=source('naver_erp_tunnel_service_install'),
                       upgrade_source=source('naver_preview_upgrade'),
                       lifecycle_source=source('naver_preview_lifecycle'), code_source=source(MODULE),
                       operation='preview-code-only-prepare', code_only_source=source('naver_preview_code_only'))
        def operation(reverse=False):
            package = dict(release=release, operation_id='8'*32 if reverse else '9'*32)
            if reverse:
                package['apply_operation_id'] = '9'*32
            bundle = dict(package=package, operation='preview-code-only-rollback' if reverse else 'preview-code-only-upgrade',
                          function='run' if reverse else 'apply',
                          source=source('naver_preview_code_rollback' if reverse else 'naver_preview_code_only'),
                          release_source=source('naver_preview_release'), host_source=source('naver_erp_tunnel_service_install'),
                          lifecycle_source=source('naver_preview_lifecycle'), upgrade_source=source('naver_preview_upgrade'),
                          code_source=source(MODULE))
            if reverse:
                bundle['code_only_source'] = source('naver_preview_code_only')
            return bundle
        passive = dict(package=dict(baseline=HOST, source_commit=TARGET, source_tar_gz_sha256=TARGET_ARCHIVE,
                                    passive_runtime_only=True), operation='preview-collection-status', function='run',
                       source=source('naver_preview_collection_status'), release_source=source('naver_preview_release'),
                       host_source=source('naver_erp_tunnel_service_install'))
        return {'prepare':prepare, 'forward':operation(), 'reverse':operation(True), 'passive':passive}

    def test_final_pin_four_actual_bundles_roundtrip_with_original_limits(self):
        import base64, gzip, zlib
        encode, decode, _ = shared.ContractTest().workflow_transport()
        for kind, bundle in self.actual_bundles().items():
            with self.subTest(kind=kind):
                raw = json.dumps(bundle).encode()
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

    def bundles(self):
        tools = Path(__file__).parents[1]/'tools'
        common = {key: (tools/(name+'.py')).read_text() for key, name in {
            'code_source': MODULE, 'release_source': 'naver_preview_release',
            'host_source': 'naver_erp_tunnel_service_install', 'lifecycle_source': 'naver_preview_lifecycle',
            'upgrade_source': 'naver_preview_upgrade'}.items()}
        release = dict(baseline=HOST, source_commit='b'*40, source_tar_gz_sha256='d'*64,
                       ciphertext_sha256='c'*64, run_id='12345678901', operation='code-prepare')
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
                self.assertLessEqual(len(json.dumps(bundle).encode()), 229376)
                wire = encode(bundle)
                self.assertLessEqual(len(wire), 73728)
                self.assertEqual(decode(wire), bundle)
        forward = self.bundles()[0]
        prepare = dict(forward, operation='preview-code-only-prepare', function='prepare',
                       code_only_source=forward['source'], source=forward['code_source'], package=forward['package']['release'])
        prepare.pop('code_source')
        self.assertLessEqual(len(json.dumps(prepare).encode()), 229376)

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

class V18InvariantTest(unittest.TestCase):
    def test_v18_business_functions_are_ast_identical_to_immutable_v17(self):
        import ast
        tools = Path(__file__).parents[1]/'tools'
        def functions(version):
            return {node.name:ast.dump(node, include_attributes=False)
                    for node in ast.parse((tools/('naver_preview_code_upgrade_v'+version+'.py')).read_text()).body
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        before,after=functions('17'),functions('18')
        self.assertEqual({k:v for k,v in after.items() if k!='probe'},
                         {k:v for k,v in before.items() if k!='probe'})

    def test_read_projection_is_the_only_added_path_and_inverse_removes_it(self):
        fixture = V18ScopeTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.assertFalse((fixture.old/'naver_engine/report_refresh.py').exists())
        self.assertTrue((fixture.new/'naver_engine/report_refresh.py').is_file())
        fixture.code.compatible_inverse_source(fixture.new, fixture.old, fixture.upgrade)
        (fixture.old/'naver_engine/report_refresh.py').write_bytes(b'unreviewed old projection')
        with self.assertRaisesRegex(ValueError, '^CODE_SCOPE_CHANGED$'):
            fixture.code.compatible_source(fixture.old, fixture.new, fixture.upgrade)


if __name__ == '__main__':
    unittest.main()
