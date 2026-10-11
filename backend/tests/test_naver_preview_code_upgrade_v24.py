"""V24 scoped telemetry and the one committed environment-preservation proof."""
import ast
import base64
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import io
import os
import re
import sys
import textwrap
from types import ModuleType
from contextlib import redirect_stdout
import unittest
from unittest.mock import Mock, patch
import test_naver_preview_code_upgrade as shared

MODULE = 'naver_preview_code_upgrade_v24'
TOOLS = Path(__file__).parents[1] / 'tools'


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def sha(body):
    return hashlib.sha256(body).hexdigest()


def pins(code):
    return (code.OLD_COMMIT, code.TARGET_COMMIT, code.OLD_SOURCE_SHA256, code.TARGET_SOURCE_SHA256,
            code.STORE_SHA256['old'], code.STORE_SHA256['target'], code.EXPECTED_BASELINE)


class ConfigFixture:
    def __init__(self, root):
        self.code = shared.load(MODULE)
        self.release, self.upgrade = Mock(), Mock()
        self.release.ROOT, self.release.SECRET_ROOT = root, root / 'secrets'
        self.release.unique = shared.load('naver_preview_release').unique
        self.upgrade.read_file.side_effect = lambda path, **kwargs: Path(path).read_bytes()
        self.paths = [self.release.SECRET_ROOT / 'runtime.env'] + [root / 'receipts' / ('preview-' + source + '.json')
            for source in (self.code.CONFIG_SOURCE_COMMIT, self.code.CONFIG_ROLLBACK_COMMIT)]
        self.folder = root / 'claude-config' / self.code.APPROVED_CONFIG_OPERATION_ID
        self.folder.mkdir(parents=True)
        self.images = {'engine': 'sha256:' + 'a' * 64, 'relay': 'sha256:' + 'b' * 64}
        self.old = [b'UNCHANGED_SETTING=preserve-me\n']
        self.new = [self.old[0] + b''.join(key.encode() + b'=' + value.encode() + b'\n'
            for key, value in self.code.CONFIG_SETTINGS.items()) + b'ANTHROPIC_API_KEY=synthetic-test-key\n']
        for source in (self.code.CONFIG_SOURCE_COMMIT, self.code.CONFIG_ROLLBACK_COMMIT):
            old = dict(ok=True, stage='prepared', source_commit=source, files={str(self.paths[0]): sha(self.old[0]),
                       str(root / ('unchanged-' + source)): 'c' * 64}, images=self.images,
                       package={'source_commit': source})
            new = deepcopy(old); new['files'][str(self.paths[0])] = sha(self.new[0])
            self.old.append(encoded(old)); self.new.append(encoded(new))
        self.journal = dict(schema=1, operation_id=self.code.APPROVED_CONFIG_OPERATION_ID,
            source_commit=self.code.CONFIG_SOURCE_COMMIT, rollback_commit=self.code.CONFIG_ROLLBACK_COMMIT,
            baseline=self.code.EXPECTED_BASELINE, state='committed', images=self.images,
            before={name: dict(id=letter * 64, image=image, running=True, started='2026-10-11T00:00:00Z',
                              restarts=0, project='naver-' + name, service='naver-' + name)
                    for name, image, letter in (('engine', self.images['engine'], 'd'), ('relay', self.images['relay'], 'e'))})
        self.files = [dict(path=str(self.paths[0]), mode=0o600, uid=0, gid=0, content=self.old[0].decode())]
        for name in ('backup-recipient.pem', 'backup-upload-key', 'backup-known-hosts'):
            path = self.release.SECRET_ROOT / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic-' + name.encode())
            self.files.append(dict(path=str(path), mode=0o600, uid=10001, gid=10001, content=path.read_text()))
        self.sync()
        self.active = {'images': self.images}

    def sync(self):
        self.journal['files'] = [dict(path=str(path), old=sha(self.old[index]), new=sha(self.new[index]))
                                 for index, path in enumerate(self.paths)]
        for index, path in enumerate(self.paths):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.new[index])
            (self.folder / ('old-' + str(index))).write_bytes(self.old[index])
            (self.folder / ('new-' + str(index))).write_bytes(self.new[index])
        (self.folder / 'journal.json').write_bytes(encoded(self.journal))

    def resolve(self, identity=None):
        return self.code.preserve_approved_config(self.files, identity or self.code.APPROVED_CONFIG_OPERATION_ID,
                                                 self.active, self.release, self.upgrade)


class V24ConfigPreserveTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.fixture = ConfigFixture(Path(temp.name).resolve())

    def test_exact_committed_proof_preserves_current_bytes_and_original_payload(self):
        fixture = self.fixture; original = deepcopy(fixture.files)
        before = {path: path.read_bytes() for path in fixture.paths}
        resolved, proof = fixture.resolve()
        self.assertEqual(fixture.files, original)
        self.assertEqual(resolved[0]['content'].encode(), fixture.new[0])
        self.assertEqual(resolved[1:], fixture.files[1:])
        self.assertTrue(proof)
        self.assertEqual(before, {path: path.read_bytes() for path in fixture.paths})
        fixture.release.write_new.assert_not_called(); fixture.release.command.assert_not_called()
        self.assertEqual(fixture.upgrade.manifest.call_count, 2)

    def test_wrong_or_missing_operation_identity_is_refused(self):
        for identity in (None, '', 'f' * 32, False):
            with self.subTest(identity=identity), self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_NOT_APPROVED'):
                fixture = self.fixture
                fixture.code.preserve_approved_config(fixture.files, identity, fixture.active, fixture.release, fixture.upgrade)

    def test_only_committed_journal_exact_sources_and_baseline_are_accepted(self):
        fixture = self.fixture
        for field, values in {'state': ('prepared', 'recovered', 'rejected'), 'operation_id': ('f' * 32,),
                'source_commit': ('f' * 40,), 'rollback_commit': ('f' * 40,), 'baseline': ('f' * 64,), 'schema': (True, 2)}.items():
            original = fixture.journal[field]
            for value in values:
                fixture.journal[field] = value; fixture.sync()
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_PROOF'):
                    fixture.resolve()
            fixture.journal[field] = original; fixture.sync()

    def test_backup_bytes_current_env_and_both_manifests_are_independently_bound(self):
        fixture = self.fixture
        for path in [fixture.folder / ('old-' + str(i)) for i in range(3)] + [fixture.folder / ('new-' + str(i)) for i in range(3)] + fixture.paths:
            original = path.read_bytes(); path.write_bytes(original + b'CORRUPTED')
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_(PROOF|DRIFT)'):
                fixture.resolve()
            path.write_bytes(original)

    def test_incoming_env_must_equal_historical_backup_even_if_already_current(self):
        fixture = self.fixture
        for body in ('unrelated-env\n', fixture.new[0].decode()):
            fixture.files[0]['content'] = body
            with self.subTest(body=body[:3]), self.assertRaisesRegex(ValueError, 'RUNTIME_SECRET_CHANGED'):
                fixture.resolve()

    def test_resealed_candidate_cannot_change_unrelated_environment_settings(self):
        fixture = self.fixture
        fixture.new[0] += b'UNAPPROVED_SETTING=changed\n'
        for index in (1, 2):
            receipt = json.loads(fixture.new[index]); receipt['files'][str(fixture.paths[0])] = sha(fixture.new[0])
            fixture.new[index] = encoded(receipt)
        fixture.sync()
        with self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_PROOF'):
            fixture.resolve()

    def test_manifest_delta_is_only_runtime_env_digest(self):
        fixture = self.fixture
        receipt = json.loads(fixture.new[1]); receipt['images']['engine'] = 'sha256:' + 'f' * 64
        fixture.new[1] = encoded(receipt); fixture.sync()
        with self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_PROOF'):
            fixture.resolve()

    def test_journal_paths_and_image_identity_cannot_be_substituted(self):
        fixture = self.fixture
        fixture.journal['before']['engine']['image'] = 'sha256:' + 'f' * 64; fixture.sync()
        with self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_PROOF'):
            fixture.resolve()
        fixture.journal['before']['engine']['image'] = fixture.images['engine']; fixture.sync()
        fixture.journal['files'][0]['path'] = str(fixture.paths[1])
        (fixture.folder / 'journal.json').write_bytes(encoded(fixture.journal))
        with self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_PROOF'):
            fixture.resolve()

    def test_proof_can_be_rechecked_and_detects_postflight_mutation(self):
        fixture = self.fixture
        first, proof = fixture.resolve(); second, again = fixture.resolve()
        self.assertEqual(first, second); self.assertEqual(proof, again)
        fixture.paths[0].write_bytes(fixture.old[0])
        with self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_DRIFT'):
            fixture.resolve()

    def test_directories_and_private_files_use_existing_trust_policy(self):
        fixture = self.fixture; fixture.resolve()
        self.assertEqual(fixture.release.trusted_dir.call_args_list[0].kwargs, {'mode': 0o700})
        self.assertTrue(all(call.kwargs == {'mode': 0o600, 'maximum': 32768} for call in fixture.upgrade.read_file.call_args_list))
        fixture.release.trusted_dir.side_effect = ValueError('DIRECTORY_POLICY')
        with self.assertRaisesRegex(ValueError, 'DIRECTORY_POLICY'):
            fixture.resolve()


class V24PrepareTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.fixture = ConfigFixture(Path(temp.name).resolve())
        fixture = self.fixture; code, release = fixture.code, fixture.release
        self.code = code
        self.package = dict(baseline=code.EXPECTED_BASELINE, source_commit=code.TARGET_COMMIT,
            source_tar_gz_sha256=code.TARGET_SOURCE_SHA256, ciphertext_sha256='c' * 64, run_id='12345678901', operation='code-prepare')
        (release.ROOT / 'incoming' / self.package['run_id']).mkdir(parents=True)
        release.validate_package = shared.load('naver_preview_release').validate_package
        release.sha = sha
        release.decode_payload.return_value = (b'synthetic-source', fixture.files)
        release.source_members.return_value = (Mock(), [])
        release.received_ciphertext.return_value = b'synthetic-ciphertext'
        fixture.upgrade.ENVELOPE_KEY = fixture.release.ROOT / 'envelope/private.pem'
        old = fixture.release.ROOT / 'releases' / ('naver-' + code.OLD_COMMIT)
        old.mkdir(parents=True)
        for name in ('engine', 'relay'):
            (old / ('preview-' + name + '.override.yml')).write_bytes(('image: ' + code.OLD_COMMIT).encode())
        self.old_state = (old, fixture.active, {}, {'engine': 'unchanged', 'relay': 'unchanged'}, b'unchanged-bootstrap')
        code.current_state = Mock(return_value=self.old_state)
        code.compatible_source = Mock()
        def extract(source, destination):
            for name in ('compose.naver-engine.yml', 'compose.naver-relay.yml', 'deploy/naver-engine-backup.override.yml'):
                path = destination / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'unchanged')
        release.extract_source.side_effect = extract
        release.write_new.side_effect = lambda path, body, **kwargs: Path(path).write_bytes(body)
        release.compose.side_effect = lambda path, name: ['docker', 'compose', '--project-name', 'naver-' + name]
        self.mutate = None
        def command(args, **kwargs):
            if args[:3] == ['openssl', 'cms', '-decrypt']: return b'synthetic-plaintext'
            if args[:3] == ['docker', 'image', 'inspect']: return encoded(fixture.images['engine' if 'engine' in args[-1] else 'relay'])
            if 'check-config' in args and self.mutate is not None: self.mutate()
            return b''
        release.command.side_effect = command

    def prepare(self, preserve=True):
        fixture = self.fixture
        options = dict(approved_config_operation_id=fixture.code.APPROVED_CONFIG_OPERATION_ID) if preserve else {}
        return fixture.code.prepare(self.package, Mock(), fixture.release, Mock(), fixture.upgrade, **options)

    def test_no_option_keeps_normal_stale_envelope_guard_and_builds_nothing(self):
        with self.assertRaisesRegex(ValueError, 'RUNTIME_SECRET_CHANGED'):
            self.prepare(False)
        self.fixture.release.extract_source.assert_not_called()
        self.assertEqual(len(self.fixture.release.command.call_args_list), 1)

    def test_explicit_prepare_preserves_live_environment_without_touching_three_other_secrets(self):
        fixture = self.fixture
        before = {Path(row['path']): Path(row['path']).read_bytes() for row in fixture.files}
        original_package, original_payload = deepcopy(self.package), deepcopy(fixture.files)
        result = self.prepare()
        self.assertTrue(result['runtime_environment_preserved'])
        self.assertEqual(result['config_operation_id'], fixture.code.APPROVED_CONFIG_OPERATION_ID)
        self.assertFalse(result['services_started'])
        self.assertEqual(self.package, original_package); self.assertEqual(fixture.files, original_payload)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertTrue(all(call.args[0] not in before for call in fixture.release.write_new.call_args_list))
        self.assertFalse(any('systemctl' in str(call.args[0]) for call in fixture.release.command.call_args_list))
        self.assertEqual(fixture.code.current_state.call_count, 2)
        receipt = json.loads((fixture.release.ROOT / 'receipts' / ('preview-' + fixture.code.TARGET_COMMIT + '.json')).read_bytes())
        self.assertEqual(receipt['files'][str(fixture.paths[0])], sha(fixture.new[0]))
        self.assertEqual(receipt['package'], {key: value for key, value in self.package.items() if key != 'operation'})

    def test_any_of_three_original_secret_mismatches_is_refused_before_build(self):
        fixture = self.fixture
        for row in fixture.files[1:]:
            original = row['content']; row['content'] = 'different-synthetic-value'
            with self.subTest(name=Path(row['path']).name), self.assertRaisesRegex(ValueError, 'RUNTIME_SECRET_CHANGED'):
                self.prepare()
            row['content'] = original
        fixture.release.extract_source.assert_not_called()

    def test_current_env_drift_during_build_is_refused_without_rewriting_environment(self):
        fixture = self.fixture
        self.mutate = lambda: fixture.paths[0].write_bytes(b'drift-must-not-be-repaired\n')
        with self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_DRIFT'):
            self.prepare()
        self.assertEqual(fixture.paths[0].read_bytes(), b'drift-must-not-be-repaired\n')
        self.assertFalse((fixture.release.ROOT / 'receipts' / ('preview-' + fixture.code.TARGET_COMMIT + '.json')).exists())

    def test_other_secret_drift_during_build_is_refused_before_prepared_receipt(self):
        fixture = self.fixture; path = Path(fixture.files[1]['path'])
        self.mutate = lambda: path.write_bytes(b'drift-must-not-be-repaired')
        with self.assertRaisesRegex(ValueError, 'RUNTIME_SECRET_CHANGED'):
            self.prepare()
        self.assertFalse((fixture.release.ROOT / 'receipts' / ('preview-' + fixture.code.TARGET_COMMIT + '.json')).exists())


class V24WorkflowOptionTest(unittest.TestCase):
    def builder(self, source, operation_id=None):
        workflow = (TOOLS.parents[1] / '.github/workflows/debug-rank.yml').read_text()
        script = next(textwrap.dedent(body) for body in re.findall(r"python3[^\n]*<<'PY'\n([\s\S]*?)\n[ \t]*PY", workflow)
                      if 'fields=download(package' in body)
        code = shared.load(source)
        package = dict(baseline=code.EXPECTED_BASELINE, source_commit=code.TARGET_COMMIT,
            source_tar_gz_sha256=code.TARGET_SOURCE_SHA256, ciphertext_sha256='c' * 64,
            artifact_sha256='d' * 64, download_url='https://invalid.test/synthetic-only')
        original = deepcopy(package)
        if operation_id is not None: package['approved_config_operation_id'] = operation_id
        inputs = dict(ad_prepare='preview-code-only-prepare', ad_expected_baseline=json.dumps(package), collector='off')
        downloader = ModuleType('naver_preview_download')
        downloader.download = Mock(side_effect=lambda package, output: {key: package[key] for key in
            ('baseline', 'source_commit', 'source_tar_gz_sha256', 'ciphertext_sha256')})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'github-env'
            with patch.dict(sys.modules, {'naver_preview_download': downloader}), patch.dict(os.environ,
                    INPUTS_JSON=json.dumps(inputs), RUN_ID='12345678901', GITHUB_ENV=str(path)), redirect_stdout(io.StringIO()):
                try:
                    exec(compile(script, '<reviewed-workflow-builder>', 'exec'), {})
                except SystemExit:
                    return downloader.download, None, original
            body = path.read_text().removeprefix('PREVIEW_RELEASE_B64=').strip()
            bundle = json.loads(gzip.decompress(base64.b64decode(body.removeprefix('prepare-gzip-v1:'))))
        return downloader.download, bundle, original

    def test_actual_workflow_separates_option_and_keeps_original_download_and_release_package(self):
        download, bundle, original = self.builder(MODULE, '74c912dddf824fae99012849bc4c19a5')
        self.assertIsNotNone(bundle)
        self.assertEqual(download.call_args.args[0], original)
        self.assertEqual(bundle['approved_config_operation_id'], '74c912dddf824fae99012849bc4c19a5')
        self.assertEqual(set(bundle['package']), {'baseline', 'source_commit', 'source_tar_gz_sha256', 'ciphertext_sha256', 'run_id', 'operation'})
        self.assertNotIn('approved_config_operation_id', bundle['package'])
        download, old, original = self.builder('naver_preview_code_upgrade_v23')
        self.assertIsNotNone(old); self.assertNotIn('approved_config_operation_id', old)
        self.assertEqual(download.call_args.args[0], original)

    def test_actual_workflow_rejects_wrong_identity_or_old_source_before_download(self):
        for source, operation in ((MODULE, 'f' * 32), ('naver_preview_code_upgrade_v23', '74c912dddf824fae99012849bc4c19a5')):
            download, bundle, _ = self.builder(source, operation)
            with self.subTest(source=source):
                download.assert_not_called(); self.assertIsNone(bundle)


class V24ScopeTest(unittest.TestCase):
    def setUp(self):
        self.code = shared.load(MODULE)
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.old, self.new = (Path(temp.name).resolve() / name for name in ('old', 'new'))
        store = shared.StoreScopeTest.SOURCE
        self.code.STORE_SHA256 = {'old': sha(store), 'target': sha(store)}
        compose = json.loads((Path(__file__).parent / 'fixtures/v9-engine-compose-old.json').read_text())['compose'].encode()
        compose = compose.replace(b'    cpus: "0.50"\n', b'    cpus: "1.00"\n').replace(b'    mem_limit: 512m\n', b'    mem_limit: 768m\n')
        for root in (self.old, self.new):
            names = {'compose.naver-relay.yml', 'deploy/naver-engine-backup.override.yml', 'Dockerfile.naver-engine',
                     'Dockerfile.naver-relay', 'backend/requirements.txt', 'naver_runtime/bootstrap.py',
                     'naver_runtime/scheduler.py', 'naver_engine/learning_retrieval.py', 'backend/naver_page/automation-ui.js'} | self.code.CODE_PATHS
            for name in names:
                file = root / name; file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes((b'old' if root == self.old else b'new') if name in self.code.CODE_PATHS else b'unchanged')
            (root / 'compose.naver-engine.yml').write_bytes(compose)
            (root / 'naver_engine/store.py').write_bytes(store)
            for name in ('engine', 'relay'):
                body = ('image: ' + self.code.OLD_COMMIT).encode()
                (root / ('preview-' + name + '.override.yml')).write_bytes(body if root == self.old else self.code.target_override(body, name))
        self.adapter = Mock(); self.adapter.read_file.side_effect = lambda path, **kwargs: Path(path).read_bytes()

    def test_four_existing_paths_and_unchanged_store_work_forward_and_inverse(self):
        self.code.compatible_source(self.old, self.new, self.adapter)
        self.code.compatible_inverse_source(self.new, self.old, self.adapter)
        self.assertEqual((self.old / 'naver_engine/store.py').read_bytes(), (self.new / 'naver_engine/store.py').read_bytes())

    def test_neighboring_automation_retrieval_scheduler_and_store_changes_are_refused(self):
        for name in ('backend/naver_page/automation-ui.js', 'naver_engine/learning_retrieval.py', 'naver_runtime/scheduler.py', 'naver_engine/store.py'):
            file = self.new / name; original = file.read_bytes(); file.write_bytes(original + b'rogue-change')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'CODE_(SCOPE|STORE)_CHANGED'):
                self.code.compatible_source(self.old, self.new, self.adapter)
            file.write_bytes(original)

    def test_source_additions_removals_and_mode_changes_are_refused(self):
        file = self.new / 'naver_runtime/claude_provider.py'; original = file.read_bytes(); file.unlink()
        with self.assertRaisesRegex(ValueError, 'CODE_SOURCE_REMOVED'):
            self.code.compatible_source(self.old, self.new, self.adapter)
        file.write_bytes(original); file.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'CODE_SOURCE_MODE_CHANGED'):
            self.code.compatible_source(self.old, self.new, self.adapter)
        file.chmod(0o644); extra = self.new / 'naver_runtime/rogue.py'; extra.write_bytes(b'rogue')
        with self.assertRaisesRegex(ValueError, 'CODE_SCOPE_CHANGED'):
            self.code.compatible_inverse_source(self.new, self.old, self.adapter)


class V24ProfileTest(unittest.TestCase):
    def test_exact_four_file_scope_schema_and_rollback_keep_unlimited_source(self):
        code = shared.load(MODULE); policy = shared.load('naver_preview_code_only'); rollback = shared.load('naver_preview_code_rollback')
        self.assertEqual(code.OLD_COMMIT, '9ddb0a30e16e4177e8d419318a6f23eb6c206e2f')
        self.assertEqual(code.CODE_PATHS, {'naver_runtime/claude_provider.py', 'naver_runtime/learning_provider.py', 'naver_engine/web.py', 'backend/naver_page/report-ui.js'})
        self.assertEqual(code.STORE_SHA256['old'], code.STORE_SHA256['target'])
        self.assertEqual(policy.REVIEWED_TRANSITION_V24, pins(code))
        self.assertEqual(rollback.REVIEWED_ROLLBACK_V24, pins(code) + (frozenset(code.CODE_PATHS),))
        policy.require_review(code); rollback.require_review(policy, code)
        self.assertEqual(policy.code_module_name(code.TARGET_COMMIT), MODULE)

    def test_pending_source_archive_or_extra_scope_refused_before_host_actions(self):
        for change in ('TARGET_COMMIT', 'TARGET_SOURCE_SHA256', 'extra_path', 'config_identity', 'config_settings'):
            code = shared.load(MODULE); policy = shared.load('naver_preview_code_only')
            if change == 'extra_path': code.CODE_PATHS.add('naver_engine/store.py')
            elif change == 'config_identity': code.APPROVED_CONFIG_OPERATION_ID = 'f' * 32
            elif change == 'config_settings': code.CONFIG_SETTINGS['NAVER_CLAUDE_MONTHLY_CAP_USD'] = '10'
            else: setattr(code, change, None)
            adapters = [Mock() for _ in range(4)]
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
                policy.prepare({}, *adapters, code, approved_config_operation_id='74c912dddf824fae99012849bc4c19a5')
            self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_preserve_option_cannot_be_used_with_v23_or_other_identity(self):
        for module, identity in (('naver_preview_code_upgrade_v23', '74c912dddf824fae99012849bc4c19a5'), (MODULE, 'f' * 32)):
            code = shared.load(module); policy = shared.load('naver_preview_code_only'); adapters = [Mock() for _ in range(4)]
            with self.subTest(module=module), self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_NOT_APPROVED'):
                policy.prepare({}, *adapters, code, approved_config_operation_id=identity)
            self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_v23_controller_functions_unchanged_except_explicit_prepare_extension(self):
        functions = lambda name: {n.name: ast.dump(n, include_attributes=False)
            for n in ast.parse((TOOLS / (name + '.py')).read_text()).body if isinstance(n, ast.FunctionDef) and n.name != 'prepare'}
        old, new = functions('naver_preview_code_upgrade_v23'), functions(MODULE)
        new.pop('preserve_approved_config')
        self.assertEqual(old, new)

    def test_original_release_and_sealer_payload_contract_remain_six_fields_four_files(self):
        release = shared.load('naver_preview_release'); code = shared.load(MODULE)
        package = dict(baseline=code.EXPECTED_BASELINE, source_commit=code.TARGET_COMMIT,
            source_tar_gz_sha256=code.TARGET_SOURCE_SHA256, ciphertext_sha256='c' * 64, run_id='12345678901', operation='upgrade-prepare')
        self.assertEqual(release.validate_package(package), package)
        with self.assertRaisesRegex(ValueError, 'PACKAGE_FIELDS'):
            release.validate_package(dict(package, approved_config_operation_id=code.APPROVED_CONFIG_OPERATION_ID))

    def test_all_prior_profiles_and_rollback_remain_reviewed(self):
        policy = shared.load('naver_preview_code_only'); rollback = shared.load('naver_preview_code_rollback')
        for version in range(5, 24):
            code = shared.load('naver_preview_code_upgrade_v' + str(version))
            policy.require_review(code); rollback.require_review(policy, code)

    def test_whole_legacy_controller_ast_is_unchanged_after_exact_v24_additions(self):
        for name in ('naver_preview_code_only', 'naver_preview_code_rollback'):
            base = subprocess.run(['git', 'show', 'fdf9055b11434c9b04ec7ef4808eab589e5152da:backend/tools/' + name + '.py'],
                                  capture_output=True, check=True, cwd=TOOLS).stdout
            before, after = ast.parse(base), ast.parse((TOOLS / (name + '.py')).read_bytes())
            def has_v24(node):
                return any(isinstance(child, ast.Name) and child.id.endswith('_V24') for child in ast.walk(node))
            body = []
            for node in after.body:
                if isinstance(node, (ast.Assign, ast.AugAssign, ast.If)) and has_v24(node):
                    continue
                if isinstance(node, ast.FunctionDef):
                    node.body = [part for part in node.body if not (isinstance(part, ast.If) and has_v24(part.test))]
                    if name == 'naver_preview_code_only' and node.name == 'prepare':
                        self.assertEqual([item.arg for item in node.args.kwonlyargs], ['approved_config_operation_id'])
                        node.args.kwonlyargs = []; node.args.kw_defaults = []
                        candidates = [part for part in node.body if isinstance(part, ast.If)
                                      and isinstance(part.test, ast.Compare) and isinstance(part.test.left, ast.Name)
                                      and part.test.left.id == 'approved_config_operation_id']
                        self.assertEqual(len(candidates), 1)
                        candidate = candidates[0]; self.assertEqual(len(candidate.orelse), 1)
                        node.body = [candidate.orelse[0] if part is candidate else part for part in node.body]
                    if name == 'naver_preview_code_rollback' and node.name == 'run':
                        unchanged = next(part for part in node.body if isinstance(part, ast.FunctionDef) and part.name == 'unchanged')
                        unchanged.body = [part for part in unchanged.body if not (isinstance(part, ast.If) and has_v24(part.test))]
                body.append(node)
            after.body = body
            with self.subTest(module=name):
                self.assertEqual(ast.dump(before, include_attributes=False), ast.dump(after, include_attributes=False))

    def test_transport_actual_bundles_fit_existing_symmetric_bounds(self):
        code = shared.load(MODULE); source = lambda name: (TOOLS / (name + '.py')).read_text()
        release = dict(baseline=code.EXPECTED_BASELINE, source_commit=code.TARGET_COMMIT,
            source_tar_gz_sha256=code.TARGET_SOURCE_SHA256, ciphertext_sha256='c' * 64, run_id='12345678901', operation='code-prepare')
        common = dict(host_source=source('naver_erp_tunnel_service_install'), upgrade_source=source('naver_preview_upgrade'),
                      lifecycle_source=source('naver_preview_lifecycle'), code_source=source(MODULE))
        bundles = {
            'prepare': dict(common, package=release, source=source('naver_preview_release'), operation='preview-code-only-prepare',
                            code_only_source=source('naver_preview_code_only'), approved_config_operation_id=code.APPROVED_CONFIG_OPERATION_ID),
            'forward': dict(common, package=dict(release=release, operation_id='9' * 32), source=source('naver_preview_code_only'),
                            release_source=source('naver_preview_release'), operation='preview-code-only-upgrade', function='apply'),
            'reverse': dict(common, package=dict(release=release, operation_id='8' * 32, apply_operation_id='9' * 32),
                            source=source('naver_preview_code_rollback'), code_only_source=source('naver_preview_code_only'),
                            release_source=source('naver_preview_release'), operation='preview-code-only-rollback', function='run')}
        encode, decode, _ = shared.ContractTest().workflow_transport()
        for kind, bundle in bundles.items():
            raw = json.dumps(bundle).encode()
            with self.subTest(kind=kind):
                self.assertLessEqual(len(raw), 229376)
                wire = 'prepare-gzip-v1:' + base64.b64encode(gzip.compress(raw, mtime=0)).decode() if kind == 'prepare' else encode(bundle)
                self.assertLessEqual(len(wire), 73728)
                if kind != 'prepare': self.assertEqual(decode(wire), bundle)


if __name__ == '__main__':
    unittest.main()
