"""Pinned installer against synthetic files/SQLite; no host units or network."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_naver_saved_exports as F

TOOLS = Path(__file__).resolve().parents[1] / 'tools'


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


M = load('naver_completion_exports_reinstall')
E = load('naver_completion_exports')


class ReinstallTests(unittest.TestCase):
    def setUp(self):
        self.fixture = F.SavedExportInstallTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.h = F.M; f = self.fixture
        for key, value in (('ROOT_UID', os.getuid()), ('ROOT_GID', os.getgid())):
            item = patch.object(M, key, value); item.start(); self.addCleanup(item.stop)
        self.root = f.root / 'release'; self.receipts = self.root / 'receipts'
        self.receipts.mkdir(parents=True, mode=0o700)
        self.target = self.root / 'releases' / ('naver-' + M.TARGET_COMMIT)
        self.target.mkdir(parents=True, mode=0o700)
        self.old = f.root / 'old-application'; self.old.mkdir()
        self.live = self.old / 'engine.db'; self.live.write_bytes(b'live-engine-sentinel')
        self.package = dict(source_commit=M.TARGET_COMMIT, run_id='123', baseline={'fixed': True},
                            source_tar_gz_sha256='1' * 64, operation='code-prepare')
        self.preview = dict(ok=True, stage='prepared', source_commit=M.TARGET_COMMIT,
                            package={k:v for k,v in self.package.items() if k != 'operation'},
                            files={}, images={})
        self.preview_path = self.receipts / ('preview-' + M.TARGET_COMMIT + '.json')
        self.h._write_new(self.preview_path, M._json(self.preview), 0o600)
        self.r = SimpleNamespace(ROOT=self.root, command=f.command, unique=M._unique,
            trusted_dir=lambda p, **kwargs:self.h._directory(p, mode=kwargs.get('mode')),
            trusted_private_file=lambda p:M._read(p, 'prepared', 'binding_receipt'),
            write_new=lambda p, body:self.h._write_new(p, body, 0o600))
        self.C = SimpleNamespace(OLD_COMMIT=M.OLD_COMMIT, TARGET_COMMIT=M.TARGET_COMMIT,
            require_pins=Mock(), validate_package=Mock(side_effect=lambda p,r:p),
            current_state=Mock(return_value=(self.old, {'ready':True}, {}, {'id':'same'}, None)),
            compatible_source=Mock(), STAGE='input')
        self.U = SimpleNamespace(manifest=Mock(return_value=(self.target, self.preview)))
        self.host = object(); self.lifecycle = object()
        companion = self.h.artifacts(f.plan, f.scripts, f.pins)[self.h.COMPANION]
        pins = dict(plan=f.plan, helper_sha256=hashlib.sha256(F.SOURCE.read_bytes()).hexdigest(),
                    scripts=f.pins, companion_sha256=hashlib.sha256(companion).hexdigest())
        item = patch.object(E, 'PINS', pins); item.start(); self.addCleanup(item.stop)
        self.binding = E.Binding(self.C, self.h, self.r, F.SOURCE.read_bytes(), f.scripts)
        self.binding.prepare(self.package)
        self.binding.install(); self.binding.save(self.package); self.binding.rollback()
        self.folder = self.h.STAGING / self.binding.receipt['operation_id']
        self.journal = self.folder / 'installed.json'
        self.original = self.journal.read_bytes()
        self.binding_original = self.binding.path.read_bytes()
        self.db_original = f.database.read_bytes()
        f.calls.clear()
        self.operation = 'd' * 32

    def invoke(self, operation=None):
        return M.reinstall(self.C, E, self.h, self.r, self.host, self.lifecycle, self.U,
            helper_source=F.SOURCE.read_bytes(), scripts=self.fixture.scripts,
            operation_id=operation or self.operation)

    def name(self, suffix):
        return self.folder / ('reinstall-' + self.operation + '.' + suffix + '.json')

    def starts(self):
        return [v for v in self.fixture.calls if v[:2] == ['systemctl','start']]

    def assert_unchanged(self):
        self.assertEqual(self.binding.path.read_bytes(), self.binding_original)
        self.assertEqual(self.preview_path.read_bytes(), M._json(self.preview))
        self.assertEqual(self.fixture.database.read_bytes(), self.db_original)
        self.assertEqual(self.live.read_bytes(), b'live-engine-sentinel')

    def test_exact_pinned_reinstall_keeps_previous_journal_and_application(self):
        original_identity = M._identity(self.journal.stat())
        result = self.invoke()
        self.assertEqual(set(result), {'ok','stage','status','operation_id','exports_verified',
            'previous_attempt_preserved','export_jobs_started','services_started','engine_changed',
            'database_writes','source_writes','coordination_files_may_change','network_calls'})
        self.assertEqual(result['status'], 'installed')
        self.assertTrue(result['source_writes']); self.assertTrue(result['coordination_files_may_change'])
        self.assertFalse(result['services_started']); self.assertFalse(result['database_writes'])
        self.assertEqual(self.name('previous').read_bytes(), self.original)
        intent = json.loads(self.name('intent').read_bytes())
        self.assertEqual(intent['original_identity'], original_identity)
        self.assertEqual(intent['previous_sha256'], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(self.name('previous').stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(self.starts()), 2)
        self.assertEqual(json.loads(self.journal.read_bytes())['state'], 'installed')
        self.assert_unchanged()

    def test_success_replay_verifies_only_without_restarting_exporters(self):
        self.invoke(); before = len(self.fixture.calls)
        result = self.invoke()
        self.assertEqual(result['status'], 'already_verified')
        self.assertFalse(result['export_jobs_started'])
        self.assertEqual(len(self.starts()), 2)
        self.assertTrue(len(self.fixture.calls) > before)  # real verification GET-equivalent commands
        self.assert_unchanged()

    def test_wrong_pin_refuses_before_manifest_or_current_host_access(self):
        with patch.object(E, 'PINS', {**E.PINS, 'helper_sha256':'0' * 64}):
            with self.assertRaises(M.ReinstallInvalid):self.invoke()
        self.C.current_state.assert_not_called(); self.U.manifest.assert_not_called()
        self.assertEqual(self.fixture.calls, [])

    def test_target_start_receipt_blocks_before_export_mutation(self):
        path = self.receipts / ('preview-start-' + M.TARGET_COMMIT + '.json')
        path.write_bytes(b'not even trusted'); path.chmod(0o600)
        with self.assertRaisesRegex(M.ReinstallInvalid, 'REINSTALL_ALREADY_STARTED'):self.invoke()
        self.assertEqual(self.journal.read_bytes(), self.original)
        self.assertFalse(self.name('previous').exists()); self.assertEqual(self.fixture.calls, [])

    def test_non_rolled_back_or_remaining_managed_file_refuses(self):
        state = json.loads(self.original); state['state'] = 'installed'
        self.journal.write_bytes(M._json(state))
        with self.assertRaisesRegex(M.ReinstallInvalid, 'REINSTALL_JOURNAL'):self.invoke()
        self.journal.write_bytes(self.original)
        path = self.fixture.units / 'naver-product-export.service'
        path.write_bytes(b'foreign'); path.chmod(0o644)
        with self.assertRaises(M.ReinstallInvalid):self.invoke()
        self.assertEqual(path.read_bytes(), b'foreign')
        self.assertEqual(self.fixture.calls, [])

    def test_previous_copy_and_intent_fsync_precede_original_unlink(self):
        original_create = M._create
        def create(path, *args):
            if path == self.name('intent'):
                self.assertEqual(self.journal.read_bytes(), self.original)
                self.assertEqual(self.name('previous').read_bytes(), self.original)
                raise OSError('private path must not escape')
            return original_create(path, *args)
        with patch.object(M, '_create', side_effect=create):
            with self.assertRaises(M.ReinstallInvalid) as caught:self.invoke()
        self.assertEqual(self.journal.read_bytes(), self.original)
        self.assertEqual(self.starts(), [])
        self.assertNotIn('private path', json.dumps(M.failure_report(caught.exception)))

    def test_original_inode_replacement_after_durable_intent_is_not_unlinked(self):
        create = M._create
        def replace(path, *args):
            result = create(path, *args)
            if path == self.name('intent'):
                self.journal.unlink(); self.journal.write_bytes(self.original); self.journal.chmod(0o600)
            return result
        with patch.object(M, '_create', side_effect=replace):
            with self.assertRaisesRegex(M.ReinstallInvalid, 'REINSTALL_CHANGED'):self.invoke()
        self.assertEqual(self.journal.read_bytes(), self.original)
        self.assertTrue(self.name('intent').exists()); self.assertEqual(self.starts(), [])

    def test_install_failure_rolls_back_only_new_attempt_and_keeps_previous(self):
        original = self.r.command
        def fail(args):
            if args == ['systemctl','start','naver-product-export.service']:
                raise RuntimeError('private host path/SQL must not escape')
            return original(args)
        with patch.object(self.r, 'command', side_effect=fail), patch.object(E, 'command_diagnostic',
                return_value={'export_command_stage':'product_start','export_command_issue':'command_failed'}):
            with self.assertRaises(M.ReinstallInvalid) as caught:self.invoke()
        report = M.failure_report(caught.exception)
        self.assertEqual(report['cleanup'], 'rolled_back')
        self.assertEqual(report['export_command_stage'], 'product_start')
        self.assertNotIn('private', json.dumps(report))
        self.assertEqual(self.name('previous').read_bytes(), self.original)
        self.assertEqual(json.loads(self.journal.read_bytes())['state'], 'rolled_back')
        self.assertFalse((self.fixture.install / self.fixture.plan['ops_commit']).exists())
        self.assert_unchanged()

    def test_rejection_before_installer_journal_restores_rolled_back_metadata(self):
        with patch.object(self.h, 'install', side_effect=RuntimeError('early refusal')):
            with self.assertRaises(M.ReinstallInvalid) as caught:self.invoke()
        self.assertEqual(M.failure_report(caught.exception)['cleanup'], 'rolled_back')
        self.assertEqual(self.journal.read_bytes(), self.original)
        self.assertEqual(self.name('previous').read_bytes(), self.original)
        self.assertEqual(self.starts(), [])

    def test_interrupted_after_install_same_attempt_only_verifies(self):
        create = M._create
        def interrupt(path, *args):
            if path == self.name('result'):raise KeyboardInterrupt()
            return create(path, *args)
        with patch.object(M, '_create', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):self.invoke()
        self.assertFalse(self.name('result').exists())
        with self.assertRaisesRegex(M.ReinstallInvalid, 'REINSTALL_PENDING'):self.invoke('e' * 32)
        self.assertEqual(len(self.starts()), 2)
        result = self.invoke()
        self.assertEqual(result['status'], 'already_verified')
        self.assertEqual(len(self.starts()), 2)

    def test_interrupted_before_install_pending_replay_never_starts(self):
        with patch.object(self.h, 'install', side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):self.invoke()
        with self.assertRaises(M.ReinstallInvalid):self.invoke()
        with self.assertRaisesRegex(M.ReinstallInvalid, 'REINSTALL_PENDING'):self.invoke('e' * 32)
        self.assertEqual(self.starts(), [])
        self.assertTrue(self.name('previous').exists())

    def test_failed_attempt_cannot_restart_same_uuid_but_next_explicit_attempt_can(self):
        with patch.object(self.h, 'install', side_effect=RuntimeError('early refusal')):
            with self.assertRaises(M.ReinstallInvalid):self.invoke()
        with self.assertRaisesRegex(M.ReinstallInvalid, 'REINSTALL_PREVIOUS_ATTEMPT'):self.invoke()
        result = self.invoke('e' * 32)
        self.assertEqual(result['status'], 'installed')
        self.assertEqual(len(self.starts()), 2)
        self.assertEqual(self.name('previous').read_bytes(), self.original)

    def test_previous_archive_drift_refuses_replay_before_systemd(self):
        self.invoke(); self.fixture.calls.clear()
        self.name('previous').write_bytes(b'foreign')
        with self.assertRaisesRegex(M.ReinstallInvalid, 'REINSTALL_CHANGED'):self.invoke()
        self.assertEqual(self.fixture.calls, [])

    def test_lock_is_single_exclusive_and_foreign_symlink_is_not_followed(self):
        import fcntl
        lock = self.folder / 'reinstall.lock'; lock.write_bytes(b''); lock.chmod(0o600)
        with lock.open('r+b') as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(M.ReinstallInvalid, 'REINSTALL_BUSY'):self.invoke()
        lock.unlink(); lock.symlink_to(self.live)
        with self.assertRaises(M.ReinstallInvalid):self.invoke()
        self.assertEqual(self.live.read_bytes(), b'live-engine-sentinel')
        self.assertEqual(self.fixture.calls, [])

    def test_changed_current_application_stops_before_install(self):
        self.C.current_state.side_effect = [(self.old, {'ready':True}, {}, {'id':'same'}, None),
                                           (self.old, {'ready':True}, {}, {'id':'changed'}, None)]
        with self.assertRaisesRegex(M.ReinstallInvalid, 'REINSTALL_CURRENT_STATE'):self.invoke()
        self.assertEqual(self.journal.read_bytes(), self.original)
        self.assertEqual(self.fixture.calls, [])

    def test_missing_receipt_has_closed_role_without_raw_path(self):
        self.binding.path.unlink()
        with self.assertRaises(M.ReinstallInvalid) as caught:self.invoke()
        report = M.failure_report(caught.exception)
        self.assertEqual(report['missing_role'], 'binding_receipt')
        self.assertEqual(report['error_kind'], 'FileNotFoundError')
        self.assertEqual(set(report), {'ok','stage','code','error_kind','missing_role','cleanup',
                                      'database_writes','engine_changed'})
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_opaque_or_malformed_failure_details_never_escape_or_break_report(self):
        for value in ([], 'private path', {'stage':[], 'code':{}, 'error_kind':[],
                'missing_role':{}, 'cleanup':[], 'export_command_stage':{},
                'export_command_issue':[], 'export_command_status':True}):
            with self.subTest(value=value):
                error = ValueError('private raw SQL')
                error.failure_details = value
                wrapped = M.ReinstallInvalid('REINSTALL_FAILED', cause=error)
                self.assertEqual(set(M.failure_report(wrapped)), {'ok','stage','code',
                    'error_kind','missing_role','cleanup','database_writes','engine_changed'})
                self.assertNotIn('private', json.dumps(M.failure_report(error)))


if __name__ == '__main__':
    unittest.main()
