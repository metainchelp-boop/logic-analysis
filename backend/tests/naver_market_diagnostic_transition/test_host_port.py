import os
from pathlib import Path
import stat
import types
import unittest
from unittest.mock import patch
import host_port as H
import journal as J
import transition as T
import test_publication as fixtures


class FakeManager:
    """Command-state model only. Never a claim of Linux/systemd validation."""
    def __init__(self, plan):
        self.plan, self.started, self.timer, self.active = plan, 0, True, False
        self.ambiguous = False
    def original_preflight(self):
        if not self.timer: T.fail('TIMER')
    def timer_stop(self): self.timer = False
    def mask_search_path(self): return None
    def reload(self): return None
    def masked_idle(self):
        if self.timer: T.fail('TIMER')
    def verify_units(self): return None
    def new_idle(self):
        if self.active: T.fail('ACTIVE')
    def cleanup_idle(self): self.new_idle()
    def start_once(self):
        self.started += 1
        if self.ambiguous: T.fail('AMBIGUOUS')
    def observe(self):
        return dict(reader=self.plan['reader'], invocation_id='f' * 32,
            status='source_limit', limit_issue='rows', exit_status=1)
    def timer_restore(self): self.timer = True
    def show(self, unit):
        if unit != T.OLD_TIMER: T.fail('UNIT')
        return dict(LoadState='loaded', UnitFileState='enabled',
            FragmentPath=T.UNIT_ROOT + '/' + T.OLD_TIMER, DropInPaths='',
            ActiveState='active' if self.timer else 'inactive')


class HostTests(unittest.TestCase):
    def setUp(self):
        # Reuse fixture setup only; none of its 12 tests are rerun here.
        self.f = fixtures.PublicationTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.pub.prepare()
        self.plan, self.files, self.src = self.f.plan, self.f.files, self.f.src
        ledger_root = self.f.root / 'ledger'
        ledger_root.mkdir(mode=0o700)
        self.ledger = J.Ledger(ledger_root, self.plan, owner=os.getuid())
        self.manager = FakeManager(self.plan)
        self.guards = []
        def current(*, require_failure):
            self.guards.append(require_failure)
            return dict(operating_source=self.plan['operating_source'],
                operating_operation=self.plan['operating_operation'], current_source_verified=True,
                source_limit_invocation_verified=require_failure)
        self.port = H.HostPort(self.plan, self.files, sources=self.src, baseline_sources={},
            ledger=self.ledger, publication=self.f.pub, systemd=self.manager,
            output_identity=[1, 2, 3, 4, 5], current_guard=current)
        self.context = types.SimpleNamespace(runtime_uid=os.getuid())
        baseline = patch.object(H.B, 'collect', return_value=(self.plan['previous'], self.context))
        baseline.start(); self.addCleanup(baseline.stop)
        # Real temp ledger/publication integration; output UID/GID preflight is
        # qualified separately below with metadata seams, not chown on this Mac.
        self.output_checks = []
        self.port._output = lambda context, *, empty: self.output_checks.append(empty)
        self.controller = T.Controller(self.port, sources=self.src)

    def apply(self): return self.controller.apply(self.plan, self.files)
    def rollback(self):
        return self.controller.rollback(self.plan, self.files,
            apply_id=self.plan['apply_id'], rollback_id=self.plan['rollback_id'])

    def test_full_local_transaction_restores_original_timer_and_owned_files(self):
        result = self.apply()
        self.assertEqual(result['observation']['limit_issue'], 'rows')
        self.assertFalse(result['product_export_verified'])
        self.assertEqual(self.manager.started, 1)
        self.rollback()
        self.assertTrue(self.manager.timer)
        self.assertFalse(any(Path(p).exists() or Path(p).is_symlink() for p in self.f.pub.expected))
        self.assertEqual(self.guards, [True, True, True, False, False])
        self.assertEqual(self.output_checks, [True, True, True, False])

    def test_baseline_drift_rejects_before_history_and_original_side_effects(self):
        wrong = dict(self.plan['previous']); wrong['source_identity_sha256'] = '0' * 64
        with patch.object(H.B, 'collect', return_value=(wrong, self.context)):
            with self.assertRaisesRegex(T.Invalid, 'HOST_BASELINE_CHANGED'): self.apply()
        self.assertTrue(self.manager.timer)
        with self.ledger.lock(): self.assertEqual(self.ledger.read(self.port.plan_hash), [])

    def test_current_source_and_current_failure_guard_cannot_be_omitted(self):
        self.port.current_guard = lambda **_: dict(operating_source=self.plan['operating_source'],
            operating_operation=self.plan['operating_operation'], current_source_verified=1,
            source_limit_invocation_verified=True)
        with self.assertRaisesRegex(T.Invalid, 'HOST_CURRENT_GUARD'): self.apply()
        self.assertTrue(self.manager.timer)

    def test_ambiguous_start_consumes_attempt_and_paired_rollback_restores(self):
        self.manager.ambiguous = True
        with self.assertRaisesRegex(T.Invalid, 'AMBIGUOUS'): self.apply()
        self.assertEqual(self.manager.started, 1)
        with self.assertRaises(T.Invalid): self.apply()
        self.rollback()
        self.assertTrue(self.manager.timer)
        self.assertEqual(self.manager.started, 1)

    def test_partial_file_publication_interrupt_rolls_back_without_restarting(self):
        original = os.link
        def interrupt(source, target, **kwargs):
            original(source, target, **kwargs)
            if str(target) in self.files: raise KeyboardInterrupt()
        with patch('publication.os.link', interrupt):
            with self.assertRaises(KeyboardInterrupt): self.apply()
        self.rollback()
        self.assertEqual(self.manager.started, 0)
        self.assertTrue(self.manager.timer)

    def test_partial_mask_publication_interrupt_is_paired_removable(self):
        original = os.link
        def interrupt(source, target, **kwargs):
            original(source, target, **kwargs)
            if str(target) in self.f.pub.expected and str(target) not in self.files:
                raise KeyboardInterrupt()
        with patch('publication.os.link', interrupt):
            with self.assertRaises(KeyboardInterrupt): self.apply()
        self.rollback()
        self.assertTrue(self.manager.timer)
        self.assertEqual(self.manager.started, 0)

    def test_active_new_unit_blocks_cleanup_until_external_idle_change(self):
        self.apply(); self.manager.active = True
        with self.assertRaisesRegex(T.Invalid, 'ACTIVE'): self.rollback()
        self.assertFalse(self.manager.timer)
        self.assertTrue(all(Path(p).exists() for p in self.files))
        self.manager.active = False
        self.rollback()
        self.assertTrue(self.manager.timer)
        self.assertEqual(self.manager.started, 1)

    def test_drifted_file_blocks_all_cleanup_and_timer_restore(self):
        self.apply()
        target = Path(next(iter(self.files)))
        target.unlink(); target.write_bytes(b'unrelated'); target.chmod(0o644)
        with self.assertRaisesRegex(T.Invalid, 'OWNED_TARGET_CHANGED'): self.rollback()
        self.assertEqual(target.read_bytes(), b'unrelated')
        self.assertFalse(self.manager.timer)

    def test_actions_require_held_lock_and_exact_durable_intent(self):
        with self.assertRaisesRegex(T.Invalid, 'JOURNAL_LOCK_REQUIRED'):
            self.port.perform('timer_stop', self.plan, self.files)
        with self.ledger.lock():
            with self.assertRaisesRegex(T.Invalid, 'HOST_ACTION_INTENT_REQUIRED'):
                self.port.perform('timer_stop', self.plan, self.files)
        self.assertTrue(self.manager.timer)

    def test_output_metadata_and_empty_before_run_preserved_evidence_after(self):
        mode = stat.S_IFDIR | 0o750
        info = types.SimpleNamespace(st_dev=10, st_ino=20, st_mode=mode,
            st_uid=os.getuid(), st_gid=10001)
        self.port.output_identity = H.inode(info)
        path = Path(self.plan['output_root'])
        with patch.object(H.Path, 'resolve', return_value=path), \
             patch.object(H.Path, 'lstat', return_value=info), \
             patch.object(H.Path, 'iterdir', return_value=iter(())):
            H.HostPort._output(self.port, self.context, empty=True)
        with patch.object(H.Path, 'resolve', return_value=path), \
             patch.object(H.Path, 'lstat', return_value=info), \
             patch.object(H.Path, 'iterdir', return_value=iter((path / 'bundle.json',))):
            with self.assertRaisesRegex(T.Invalid, 'HOST_OUTPUT_NOT_EMPTY'):
                H.HostPort._output(self.port, self.context, empty=True)
            H.HostPort._output(self.port, self.context, empty=False)
        info.st_gid = 0
        with patch.object(H.Path, 'resolve', return_value=path), patch.object(H.Path, 'lstat', return_value=info):
            with self.assertRaisesRegex(T.Invalid, 'HOST_OUTPUT'):
                H.HostPort._output(self.port, self.context, empty=False)


if __name__ == '__main__': unittest.main()
