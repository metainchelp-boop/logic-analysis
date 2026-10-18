import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import journal as J
import transition as T
import test_transition as fixture


class JournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TransitionTests.setUpClass()
        cls.plan = fixture.TransitionTests.plan
        cls.plan_hash = T.sha(T.canonical(cls.plan))
        cls.initial = dict(action='apply', state='intent',
                           apply_id=cls.plan['apply_id'], rollback_id=cls.plan['rollback_id'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        os.chmod(self.root, 0o700)
        self.ledger = J.Ledger(self.root, self.plan, owner=os.getuid())

    def tearDown(self): self.temp.cleanup()

    def begin(self): self.ledger.append(self.plan_hash, self.initial)

    def test_requires_lock_and_retains_immutable_chain_across_reopen(self):
        with self.assertRaises(T.Invalid): self.ledger.read(self.plan_hash)
        with self.ledger.lock():
            self.assertEqual(self.ledger.read(self.plan_hash), [])
            self.begin()
            before = (self.ledger.folder / '000001.json').read_bytes()
            self.ledger.append(self.plan_hash, dict(action='timer_stop', state='intent'))
            self.assertEqual((self.ledger.folder / '000001.json').read_bytes(), before)
        again = J.Ledger(self.root, self.plan, owner=os.getuid())
        with again.lock():
            self.assertEqual(len(again.read(self.plan_hash)), 2)

    def test_cross_process_contention_rejects_without_waiting(self):
        # Real flock against another Python process, no simulated mutex.
        script = ('import json,os,sys;from pathlib import Path;import journal as J;'
                  'import transition as T; p=json.loads(sys.argv[2]);'
                  'x=J.Ledger(Path(sys.argv[1]),p,owner=os.getuid());\n'
                  'try:\n with x.lock(): print("unexpected")\n'
                  'except T.Invalid as e:\n print(e.args[0])\n')
        with self.ledger.lock():
            result = subprocess.run([sys.executable, '-B', '-c', script,
                str(self.root), T.canonical(self.plan).decode()], cwd=Path(__file__).parent,
                capture_output=True, timeout=5, check=True)
            self.assertEqual(result.stdout.strip(), b'JOURNAL_BUSY')

    def test_lock_symlink_rejected_without_target_write(self):
        target = self.root / 'protected'
        target.write_bytes(b'protected')
        (self.root / 'transition.lock').symlink_to(target)
        with self.assertRaises(T.Invalid):
            with self.ledger.lock(): pass
        self.assertEqual(target.read_bytes(), b'protected')

    def test_no_clobber_and_interrupted_uncommitted_file_is_not_an_action(self):
        with self.ledger.lock():
            self.begin()
            event = dict(action='timer_stop', state='intent')
            with patch.object(J.os, 'link', side_effect=InterruptedError):
                with self.assertRaises(InterruptedError): self.ledger.append(self.plan_hash, event)
            self.assertEqual(self.ledger.read(self.plan_hash), [self.initial])
            self.assertEqual(len(list(self.ledger.folder.glob('.pending-*'))), 1)
            self.ledger.append(self.plan_hash, dict(action='rollback', state='intent'))
            self.assertEqual(self.ledger.read(self.plan_hash)[-1]['action'], 'rollback')
            before = (self.ledger.folder / '000001.json').read_bytes()
            with self.assertRaises(FileExistsError):
                self.ledger._atomic_new(self.ledger.folder / '000001.json', b'{}')
            self.assertEqual((self.ledger.folder / '000001.json').read_bytes(), before)

    def test_crash_after_atomic_link_keeps_exact_two_link_commit(self):
        with self.ledger.lock():
            self.begin()
            original_unlink = Path.unlink
            def interrupted(path, *args, **kwargs):
                if path.name.startswith('.pending-'): raise InterruptedError()
                return original_unlink(path, *args, **kwargs)
            with patch.object(Path, 'unlink', interrupted):
                with self.assertRaises(InterruptedError):
                    self.ledger.append(self.plan_hash, dict(action='timer_stop', state='intent'))
            self.assertEqual(len(self.ledger.read(self.plan_hash)), 2)
            self.ledger.append(self.plan_hash, dict(action='rollback', state='intent'))
            self.assertEqual(len(self.ledger.read(self.plan_hash)), 3)

    def test_initial_plan_without_apply_intent_fails_closed(self):
        with self.ledger.lock():
            self.ledger.folder.mkdir(mode=0o700)
            self.ledger._atomic_new(self.ledger.folder / 'plan.json', T.canonical(self.plan))
            with self.assertRaisesRegex(T.Invalid, 'JOURNAL_INITIAL_INCOMPLETE'):
                self.ledger.read(self.plan_hash)

    def test_wrong_pair_wrong_hash_and_extra_event_fields_rejected(self):
        with self.ledger.lock():
            with self.assertRaises(T.Invalid): self.ledger.append('f'*64, self.initial)
            self.begin()
            for event in (dict(action='run_once', state='intent'),
                          dict(action='timer_stop',state='intent',secret='x')):
                with self.assertRaises(T.Invalid): self.ledger.append(self.plan_hash, event)
            self.assertEqual(len(self.ledger.read(self.plan_hash)), 1)

    def test_same_operation_different_plan_hash_cannot_reset_history(self):
        with self.ledger.lock(): self.begin()
        changed = json.loads(T.canonical(self.plan))
        changed['previous']['operating_receipt_sha256'] = 'f'*64
        other = J.Ledger(self.root, changed, owner=os.getuid())
        with other.lock():
            with self.assertRaisesRegex(T.Invalid, 'JOURNAL_BINDING'):
                other.read(other.plan_hash)
            with self.assertRaisesRegex(T.Invalid, 'JOURNAL_BINDING'):
                other.append(other.plan_hash, self.initial)

    def test_both_operation_ids_are_reserved_across_roles_and_plans(self):
        with self.ledger.lock(): self.begin()
        variants = [('3'*32, self.plan['rollback_id']),
                    (self.plan['rollback_id'], '4'*32),
                    ('5'*32, self.plan['apply_id'])]
        for apply_id, rollback_id in variants:
            with self.subTest(apply_id=apply_id, rollback_id=rollback_id):
                p = dict(self.plan, apply_id=apply_id, rollback_id=rollback_id)
                other = J.Ledger(self.root, p, owner=os.getuid())
                initial = dict(action='apply', state='intent', apply_id=apply_id, rollback_id=rollback_id)
                with other.lock(), self.assertRaisesRegex(T.Invalid, 'JOURNAL_OPERATION_RESERVED'):
                    other.append(other.plan_hash, initial)
                self.assertFalse(other.folder.exists())

    def test_reserved_plan_type_drift_is_not_python_equal(self):
        with self.ledger.lock():
            self.begin()
            path = self.ledger.folder / 'plan.json'
            value = json.loads(path.read_bytes()); value['version'] = True
            self.assertEqual(value, self.plan)
            path.write_bytes(T.canonical(value))
            with self.assertRaisesRegex(T.Invalid, 'JOURNAL_BINDING'):
                self.ledger.read(self.plan_hash)

    def test_pair_commit_interruption_reserves_both_ids_before_any_host_action(self):
        original_mkdir = Path.mkdir
        def interrupted(path, *args, **kwargs):
            if path == self.ledger.folder: raise InterruptedError()
            return original_mkdir(path, *args, **kwargs)
        with self.ledger.lock(), patch.object(Path, 'mkdir', interrupted):
            with self.assertRaises(InterruptedError): self.begin()
        self.assertFalse(self.ledger.folder.exists())
        for apply_id, rollback_id in [('3'*32,self.plan['rollback_id']),
                                     (self.plan['rollback_id'],'4'*32),
                                     ('5'*32,self.plan['apply_id'])]:
            p = dict(self.plan, apply_id=apply_id, rollback_id=rollback_id)
            other = J.Ledger(self.root, p, owner=os.getuid())
            initial = dict(action='apply', state='intent', apply_id=apply_id, rollback_id=rollback_id)
            with other.lock(), self.assertRaisesRegex(T.Invalid, 'JOURNAL_OPERATION_RESERVED'):
                other.append(other.plan_hash, initial)

    def test_journal_corruption_and_external_hardlink_are_rejected(self):
        with self.ledger.lock():
            self.begin()
            path = self.ledger.folder / '000001.json'
            original = path.read_bytes()
            value = json.loads(original); value['previous'] = 'f'*64
            path.write_bytes(T.canonical(value))
            with self.assertRaises(T.Invalid): self.ledger.read(self.plan_hash)
            path.write_bytes(original)
            alias = self.root / 'external-link'
            os.link(path, alias)
            with self.assertRaisesRegex(T.Invalid, 'JOURNAL_LINK'): self.ledger.read(self.plan_hash)

    def test_event_sequence_gap_and_unknown_files_fail_closed(self):
        with self.ledger.lock():
            self.begin()
            path = self.ledger.folder / '000001.json'
            path.rename(self.ledger.folder / '000003.json')
            with self.assertRaisesRegex(T.Invalid, 'JOURNAL_SEQUENCE'): self.ledger.read(self.plan_hash)
            (self.ledger.folder / '000003.json').rename(path)
            (self.ledger.folder / 'unexpected').write_bytes(b'')
            with self.assertRaisesRegex(T.Invalid, 'JOURNAL_INVENTORY'): self.ledger.read(self.plan_hash)

    def test_lock_replacement_and_permissions_drift_are_rejected(self):
        with self.ledger.lock():
            path = self.root / 'transition.lock'
            path.unlink(); path.write_bytes(b''); path.chmod(0o600)
            with self.assertRaisesRegex(T.Invalid, 'JOURNAL_CHANGED'):
                self.ledger.read(self.plan_hash)
        self.root.chmod(0o755)
        with self.assertRaises(T.Invalid):
            with self.ledger.lock(): pass


if __name__ == '__main__': unittest.main()
