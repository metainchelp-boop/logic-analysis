"""Synthetic post-success rollback only; no server, DB or operating credentials.

The future OLD=49 / TARGET=b fixture is enabled solely in in-memory test modules;
the production helper admits only the separate final74, V6 and V7 tuples.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared


class PostSuccessRollbackTest(unittest.TestCase):
    def fixture(self, fault=None, code_module='naver_preview_code_upgrade_v4'):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        helper = shared.load('naver_preview_code_rollback')
        policy = shared.load('naver_preview_code_only')
        code = shared.load(code_module)
        # V6/V7 retain their reviewed commit/archive pins. Older fixtures
        # preserve their original test-only later release returning to source 49.
        if code_module not in ('naver_preview_code_upgrade_v6', 'naver_preview_code_upgrade_v7'):
            code.OLD_COMMIT = '49c42d645b90732071d0c61b8f9aaf7660e8b765'
            code.OLD_SOURCE_SHA256 = '69b9f79ab243eac6d3d32fe67ce267b96bdd923323997fd2661934bc6a5459d4'
            if code_module != 'naver_preview_code_upgrade_v5':
                code.TARGET_COMMIT = 'b' * 40
                code.TARGET_SOURCE_SHA256 = 'd' * 64
        store = shared.StoreScopeTest.SOURCE
        digest = hashlib.sha256(store).hexdigest()
        code.STORE_SHA256 = {'old': digest, 'target': digest}
        # Existing forward review validation is real, with synthetic in-memory pins.
        setattr(policy, 'REVIEWED_TRANSITION_V7' if code_module.endswith('v7')
                else 'REVIEWED_TRANSITION_V6' if code_module.endswith('v6')
                else 'REVIEWED_TRANSITION_V5' if code_module.endswith('v5')
                else 'REVIEWED_TRANSITION_V4', helper.transition(code)[:-1])
        helper.REVIEWED_ROLLBACKS = frozenset({helper.transition(code)})
        release = Mock()
        original_release = shared.load('naver_preview_release')
        release.ROOT = root
        release.unique = original_release.unique
        release.validate_package = original_release.validate_package
        receipts = root / 'receipts'
        receipts.mkdir()
        old, new = (root / 'releases' / ('naver-' + source)
                    for source in (code.OLD_COMMIT, code.TARGET_COMMIT))
        infrastructure = ('compose.naver-engine.yml', 'compose.naver-relay.yml',
            'deploy/naver-engine-backup.override.yml', 'Dockerfile.naver-engine',
            'Dockerfile.naver-relay', 'backend/requirements.txt', 'naver_runtime/bootstrap.py')
        for path in (old, new):
            for name in infrastructure:
                file = path / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b'unchanged')
            (path / 'naver_engine').mkdir(exist_ok=True)
            (path / 'naver_engine/store.py').write_bytes(store)
            for name in code.CODE_PATHS:
                file = path / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b'old' if path == old else b'new')
            for name in ('engine', 'relay'):
                source = code.OLD_COMMIT if path == old else code.TARGET_COMMIT
                (path / ('preview-' + name + '.override.yml')).write_bytes(source.encode())
        release.compose.side_effect = lambda path, name: ['docker', 'compose',
            '--project-name', 'naver-' + name, '--file', str(path)]
        lifecycle = shared.load('naver_preview_lifecycle')
        lifecycle.UNIT_DIR = root / 'units'
        lifecycle.TMPFILES = root / 'tmpfiles' / 'naver.conf'
        lifecycle.UNIT_DIR.mkdir()
        lifecycle.TMPFILES.parent.mkdir()
        files = lifecycle.unit_files(new, 33, release)
        old_files = lifecycle.unit_files(old, 33, release)
        for file, body in files.items():
            file.write_bytes(body)
        images = {'engine': 'sha256:' + '1' * 64, 'relay': 'sha256:' + '2' * 64}
        target_images = {'engine': 'sha256:' + '3' * 64, 'relay': 'sha256:' + '4' * 64}
        prepared = dict(baseline=code.EXPECTED_BASELINE, source_commit=code.TARGET_COMMIT,
            source_tar_gz_sha256=code.TARGET_SOURCE_SHA256, ciphertext_sha256='c' * 64,
            run_id='123456', operation='code-prepare')
        old_receipt = dict(source_commit=code.OLD_COMMIT, images=images,
            package=dict(baseline=code.EXPECTED_BASELINE,
                         source_tar_gz_sha256=code.OLD_SOURCE_SHA256))
        new_receipt = dict(source_commit=code.TARGET_COMMIT, images=target_images,
            package={k: v for k, v in prepared.items() if k != 'operation'})
        original, identity = '9' * 32, '8' * 32
        saved_path = receipts / ('code-upgrade-' + original + '.json')
        saved = dict(source_commit=code.OLD_COMMIT, target_commit=code.TARGET_COMMIT,
            database_policy='preserve-in-place', images=dict(images),
            units={str(p): b.decode() for p, b in old_files.items() if p != lifecycle.TMPFILES})
        saved_path.write_text(json.dumps(saved))
        started_path = receipts / ('preview-start-' + code.TARGET_COMMIT + '.json')
        started = dict(ok=True, stage='internal_ready', source_commit=code.TARGET_COMMIT,
            previous_commit=code.OLD_COMMIT, operation_id=original,
            database_policy='preserve-in-place', database_opened_by_controller=False,
            source_warmup_performed=False)
        started_path.write_text(json.dumps(started))
        old_started_path = receipts / ('preview-start-' + code.OLD_COMMIT + '.json')
        old_started_path.write_bytes(b'original historical ready receipt')
        historical_bytes = {p: p.read_bytes() for p in (saved_path, started_path, old_started_path)}
        state = {'engine': code.TARGET_COMMIT, 'relay': code.TARGET_COMMIT}
        active = {unit: 'active' for unit in ('docker.service', lifecycle.TUNNEL, *lifecycle.UNITS)}
        commands, events, writes = [], [], []
        host = Mock()
        host.baseline.return_value = code.EXPECTED_BASELINE
        lifecycle._state = Mock(side_effect=lambda _, unit, field:
            active[unit] if field == 'ActiveState' else 'enabled')
        def snapshot(_, path, expected_images):
            for name, unit in zip(('engine', 'relay'), lifecycle.UNITS):
                self.assertEqual(state[name], path.name.removeprefix('naver-'))
                self.assertEqual(active[unit], 'active')
            self.assertEqual(expected_images, images if path == old else target_images)
            events.append(('snapshot', path.name))
            return {}
        lifecycle._snapshot = Mock(side_effect=snapshot)
        def probe(_, source, adapter):
            if fault == 'probe_old' and source == code.OLD_COMMIT:
                raise ValueError('CODE_ROUTE_STATUS')
        code.probe = Mock(side_effect=probe)
        code.bootstrap_state = Mock(return_value=None)
        def stopped(_, life, path, allowed, unit):
            events.append(('stopped', unit))
            self.assertEqual(active[unit], 'inactive')
            self.assertEqual(path, new)
            self.assertIn(code.TARGET_COMMIT, allowed)
            self.assertEqual(allowed[code.TARGET_COMMIT], target_images)
            if code.OLD_COMMIT in allowed:
                self.assertEqual(allowed[code.OLD_COMMIT], images)
            if fault == 'writer':
                raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
        code.stopped_writer = Mock(side_effect=stopped)
        def command(args, **kwargs):
            commands.append(args)
            if args[:2] == ['/usr/bin/systemctl', 'stop']:
                if fault == 'stop_error':
                    raise OSError('PRIVATE_ERROR_SENTINEL')
                active[args[2]] = 'inactive'
                if fault == 'bootstrap':
                    code.bootstrap_state.return_value = {'changed': True}
                if fault == 'source_after_stop':
                    (new / 'naver_engine/store.py').write_bytes(b'changed')
            if '--force-recreate' in args:
                name = args[3].removeprefix('naver-')
                events.append(('recreate', name))
                self.assertTrue(all(active[u] == 'inactive' for u in lifecycle.UNITS))
                if fault == 'recreate':
                    raise RuntimeError('PRIVATE_ERROR_SENTINEL')
                if fault == 'unknown_kind':
                    raise type('PRIVATE_EXCEPTION_CLASS', (Exception,), {})('PRIVATE_ERROR_SENTINEL')
                state[name] = code.OLD_COMMIT
            if args[:2] == ['/usr/bin/systemctl', 'start']:
                if fault == 'start':
                    raise RuntimeError('PRIVATE_ERROR_SENTINEL')
                active[args[2]] = 'active'
            return b''
        release.command.side_effect = command
        def write_new(path, body, **kwargs):
            if fault == 'write_result' and path.name.endswith('.result.json'):
                raise OSError('PRIVATE_ERROR_SENTINEL')
            writes.append((path, body))
            with path.open('xb') as file:
                file.write(body)
        release.write_new.side_effect = write_new
        upgrade = Mock()
        upgrade.read_file.side_effect = lambda path, **kwargs: Path(path).read_bytes()
        def manifest(_, commit, package=None, started=False):
            self.assertTrue(started)
            if fault == 'image':
                raise ValueError('PREPARED_IMAGE_CHANGED')
            return (old, old_receipt) if commit == code.OLD_COMMIT else (new, new_receipt)
        upgrade.manifest.side_effect = manifest
        def replace_unit(path, expected, body, request_id, _):
            self.assertEqual(path.read_bytes(), expected)
            self.assertEqual(request_id, identity)
            path.write_bytes(body)
        upgrade.replace_unit.side_effect = replace_unit
        package = dict(release=prepared, apply_operation_id=original, operation_id=identity)
        return dict(helper=helper, policy=policy, code=code, host=host, release=release,
            lifecycle=lifecycle, upgrade=upgrade, package=package, commands=commands,
            writes=writes, events=events, state=state, active=active, old=old, new=new,
            old_files=old_files, saved=saved, saved_path=saved_path, started=started,
            started_path=started_path, historical_bytes=historical_bytes)

    def run_fixture(self, f):
        with patch.object(f['helper'].os, 'geteuid', return_value=0), \
                patch.object(f['helper'].pwd, 'getpwnam', return_value=SimpleNamespace(pw_gid=33)), \
                patch.object(sqlite3, 'connect', side_effect=AssertionError('DB forbidden')):
            return f['helper'].run(f['package'], f['host'], f['release'],
                f['lifecycle'], f['upgrade'], f['policy'], f['code'])

    def test_only_final74_transition_is_enabled_and_prior_release_refuses_before_any_adapter(self):
        helper = shared.load('naver_preview_code_rollback')
        self.assertEqual(helper.REVIEWED_ROLLBACKS,frozenset(
            helper.transition(shared.load(name)) for name in
            ('naver_preview_code_upgrade_v5','naver_preview_code_upgrade_v6','naver_preview_code_upgrade_v7')))
        for code_name in ('naver_preview_code_upgrade', 'naver_preview_code_upgrade_v3',
                          'naver_preview_code_upgrade_v4'):
            adapters = [Mock() for _ in range(4)]
            with self.subTest(code=code_name), self.assertRaisesRegex(ValueError, 'CODE_ROLLBACK_NOT_REVIEWED'):
                helper.run({}, *adapters, shared.load('naver_preview_code_only'), shared.load(code_name))
            self.assertTrue(all(not a.mock_calls for a in adapters))

    def test_success_returns_to_49_with_existing_old_start_receipt_and_no_db_access(self):
        f = self.fixture()
        result = self.run_fixture(f)
        self.assertTrue(result['ok'])
        self.assertEqual(result['source_commit'], '49c42d645b90732071d0c61b8f9aaf7660e8b765')
        self.assertEqual(set(f['state'].values()), {f['code'].OLD_COMMIT})
        self.assertEqual(result['database_policy'], 'preserve-in-place')
        self.assertFalse(result['database_opened_by_controller'])
        self.assertFalse(result['source_warmup_performed'])
        self.assertFalse(result['nginx_changed'])
        self.assertEqual(len(f['writes']), 2)
        for path, body in f['historical_bytes'].items():
            self.assertEqual(path.read_bytes(), body)
        for path, body in f['old_files'].items():
            self.assertEqual(path.read_bytes(), body)
        self.assertFalse(any('build' in args or 'pull' in args or 'exec' in args or 'run' in args
                             or 'nginx' in ' '.join(args) for args in f['commands']))
        self.assertEqual(f['commands'][:2], [['/usr/bin/systemctl', 'stop', u]
                         for u in reversed(f['lifecycle'].UNITS)])
        self.assertEqual([a[2] for a in f['commands'] if a[:2] == ['/usr/bin/systemctl', 'start']],
                         list(f['lifecycle'].UNITS))
        self.assertEqual([e[0] for e in f['events'] if e[0] in ('stopped', 'recreate')],
                         ['stopped', 'stopped', 'recreate', 'recreate'])

    def test_current_apply_refuses_when_target_49_historical_start_already_exists(self):
        policy, code = shared.load('naver_preview_code_only'), shared.load('naver_preview_code_upgrade_v4')
        host, release, life, upgrade = (Mock() for _ in range(4))
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        release.ROOT = Path(temp.name)
        (release.ROOT / 'receipts').mkdir()
        (release.ROOT / 'receipts' / ('preview-start-' + code.TARGET_COMMIT + '.json')).write_text('{}')
        old_files = {Path('/unit'): b'x', Path('/tmp'): b't'}
        life.TMPFILES = Path('/tmp')
        life.unit_files.return_value = old_files
        upgrade.manifest.return_value = (Path('/prepared'), {})
        prepared = dict(baseline=code.EXPECTED_BASELINE, source_commit=code.TARGET_COMMIT,
            ciphertext_sha256='c' * 64, source_tar_gz_sha256=code.TARGET_SOURCE_SHA256,
            run_id='123456', operation='code-prepare')
        with patch.object(code, 'validate_package', return_value=prepared), \
                patch.object(policy.pwd, 'getpwnam', return_value=SimpleNamespace(pw_gid=33)), \
                patch.object(code, 'current_state', return_value=(Path('/old'), {}, old_files, {}, None)), \
                patch.object(code, 'compatible_source'):
            with self.assertRaisesRegex(ValueError, '^CODE_ALREADY_ATTEMPTED$'):
                policy.apply(dict(release=prepared, operation_id='8' * 32), host, release, life, upgrade, code)
        release.command.assert_not_called()
        release.write_new.assert_not_called()

    def test_final_v5_seven_file_scope_returns_to_49_preserving_all_history(self):
        f = self.fixture(code_module='naver_preview_code_upgrade_v5')
        self.assertEqual(len(f['code'].CODE_PATHS), 7)
        self.assertEqual(f['code'].TARGET_COMMIT, '74b79ce6381178abf9b74fff43b0fcb03c5aa60b')
        result = self.run_fixture(f)
        self.assertTrue(result['ok'])
        self.assertEqual(result['source_commit'], '49c42d645b90732071d0c61b8f9aaf7660e8b765')
        for path, body in f['historical_bytes'].items():
            self.assertEqual(path.read_bytes(), body)

    def test_release_or_scope_mutation_and_changed_store_review_refuse_before_stop(self):
        for change in ('target', 'archive', 'scope', 'store'):
            f = self.fixture()
            if change == 'target': f['code'].TARGET_COMMIT = '0' * 40
            if change == 'archive': f['code'].TARGET_SOURCE_SHA256 = '0' * 64
            if change == 'scope': f['code'].CODE_PATHS |= {'naver_runtime/writer.py'}
            if change == 'store': f['code'].STORE_SHA256['target'] = '0' * 64
            with self.subTest(change=change), self.assertRaises(ValueError): self.run_fixture(f)
            self.assertEqual(f['commands'], [])
            self.assertEqual(f['writes'], [])

    def test_wrong_fields_ids_and_forward_operation_are_rejected_before_host(self):
        for mutation in ('extra', 'same_id', 'bad_id', 'release'):
            f = self.fixture()
            if mutation == 'extra': f['package']['bypass'] = True
            if mutation == 'same_id': f['package']['operation_id'] = f['package']['apply_operation_id']
            if mutation == 'bad_id': f['package']['apply_operation_id'] = '../escape'
            if mutation == 'release': f['package']['release']['operation'] = 'upgrade-prepare'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.run_fixture(f)
            f['host'].baseline.assert_not_called()

    def test_recovery_image_unit_source_or_started_apply_identity_tamper_refuses_before_stop(self):
        for mutation in ('image', 'unit', 'source', 'operation', 'db_policy', 'warmup'):
            f = self.fixture()
            if mutation == 'image': f['saved']['images']['engine'] = 'sha256:' + '0' * 64
            if mutation == 'unit': f['saved']['units'][next(iter(f['saved']['units']))] = 'wrong'
            if mutation == 'source': f['saved']['source_commit'] = '0' * 40
            if mutation == 'operation': f['started']['operation_id'] = '0' * 32
            if mutation == 'db_policy': f['started']['database_opened_by_controller'] = True
            if mutation == 'warmup': f['started']['source_warmup_performed'] = True
            f['saved_path'].write_text(json.dumps(f['saved']))
            f['started_path'].write_text(json.dumps(f['started']))
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'CODE_ROLLBACK_(RECOVERY|STARTED)'):
                self.run_fixture(f)
            self.assertEqual(f['commands'], [])
            self.assertEqual(f['writes'], [])

    def test_source_unit_host_image_or_infrastructure_drift_refuses_before_stop(self):
        for mutation in ('store', 'infrastructure', 'unit', 'host', 'image'):
            f = self.fixture('image' if mutation == 'image' else None)
            if mutation == 'store': (f['new'] / 'naver_engine/store.py').write_bytes(b'drift')
            if mutation == 'infrastructure': (f['new'] / 'Dockerfile.naver-engine').write_bytes(b'drift')
            if mutation == 'unit': (f['lifecycle'].UNIT_DIR / f['lifecycle'].UNITS[0]).write_bytes(b'drift')
            if mutation == 'host': f['host'].baseline.return_value = '0' * 64
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.run_fixture(f)
            self.assertEqual(f['commands'], [])
            self.assertEqual(f['writes'], [])

    def test_repeated_operation_does_not_touch_running_services(self):
        f = self.fixture()
        p = f['release'].ROOT / 'receipts' / ('code-post-rollback-' + f['package']['operation_id'] + '.json')
        p.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'CODE_ROLLBACK_ALREADY_ATTEMPTED'): self.run_fixture(f)
        self.assertEqual(f['commands'], [])
        self.assertEqual(f['writes'], [])

    def test_failed_stop_recreate_start_or_state_proof_keeps_both_services_stopped(self):
        for fault in ('writer', 'recreate', 'start', 'bootstrap', 'source_after_stop', 'probe_old', 'write_result'):
            f = self.fixture(fault)
            with self.subTest(fault=fault), self.assertRaisesRegex(RuntimeError, '^CODE_POST_ROLLBACK_FAILED$') as raised:
                self.run_fixture(f)
            self.assertNotIn('PRIVATE', str(raised.exception))
            self.assertEqual(f['commands'][-2:], [['/usr/bin/systemctl', 'stop', u]
                             for u in reversed(f['lifecycle'].UNITS)])
            self.assertTrue(all(f['active'][u] == 'inactive' for u in f['lifecycle'].UNITS))
            if fault in ('writer', 'bootstrap', 'source_after_stop'):
                self.assertFalse(any('--force-recreate' in args for args in f['commands']))

    def test_stop_failure_is_reported_as_unverified_and_never_starts_a_writer(self):
        f = self.fixture('stop_error')
        with self.assertRaisesRegex(RuntimeError, '^CODE_POST_ROLLBACK_FAILED$') as raised:
            self.run_fixture(f)
        self.assertFalse(raised.exception.failure_details['isolated_stop_verified'])
        self.assertFalse(any('--force-recreate' in a or a[:2] == ['/usr/bin/systemctl', 'start']
                             for a in f['commands']))

    def test_untrusted_exception_kind_is_never_in_failure_report(self):
        f = self.fixture('unknown_kind')
        with self.assertRaisesRegex(RuntimeError, '^CODE_POST_ROLLBACK_FAILED$') as raised:
            self.run_fixture(f)
        self.assertEqual(raised.exception.failure_details['failed_error_kind'], 'UNRECOGNIZED')
        self.assertNotIn('PRIVATE', json.dumps(raised.exception.failure_details))


if __name__ == '__main__':
    unittest.main()
