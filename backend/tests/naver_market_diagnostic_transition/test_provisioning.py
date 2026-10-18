"""New preparation tests on a private temporary filesystem only.

Linux root/nobody chown is not exercised: the production UID check runs with a
fixed mocked account and the test-only owner adapter maps GID to current GID.
No service, DB, original output, namespace or network is accessed.
"""
import copy
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import transition as T
import publication as P
import provisioning as Q
import test_transition as compiler_fixture


class PreparationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.uid, self.gid = os.getuid(), os.getgid()
        for parent in ('install', 'data', 'run', 'etc', 'etc/system'):
            (self.root / parent).mkdir(mode=0o755, exist_ok=True)
        pairs = [(T, 'INSTALL', str(self.root / 'install/diagnostic')),
            (T, 'OUTPUT', str(self.root / 'data/diagnostic')),
            (T, 'UNIT_ROOT', str(self.root / 'etc/system')),
            (P, 'MASK_ROOT', str(self.root / 'run/system.control')),
            (Q, 'MASK_ROOT', str(self.root / 'run/system.control')),
            (Q, 'CONTROL', self.root / 'data/control'), (Q, 'ROOT_UID', self.uid),
            (Q, 'ROOT_GID', self.gid), (Q, 'TRUST_ANCHOR', self.root)]
        for module, key, value in pairs:
            context = patch.object(module, key, value)
            context.start(); self.addCleanup(context.stop)
        account = patch.object(Q.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_uid=self.uid))
        account.start(); self.addCleanup(account.stop)
        self.original_runtime_owner = Q._runtime_owner
        def test_owner(uid, gid):
            checked_uid, checked_gid = self.original_runtime_owner(uid, gid)
            assert checked_gid == 10001
            return checked_uid, self.gid
        owner = patch.object(Q, '_runtime_owner', side_effect=test_owner)
        owner.start(); self.addCleanup(owner.stop)
        self.sources = compiler_fixture.sources()
        self.plan, self.files = T.compile_plan(apply_id='7' * 32, rollback_id='8' * 32,
            sources=self.sources, previous={key:T.sha(key.encode()) for key in T.PROOF_KEYS})
        self.guard = dict(source='21cd', invocation='a' * 32, verified=True)

    def prepare(self, **changes):
        args = dict(sources=self.sources, runtime_uid=self.uid, guard_proof=self.guard)
        args.update(changes)
        return Q.prepare(self.plan, self.files, **args)

    def load(self):
        return Q.load(self.plan, self.files, sources=self.sources, runtime_uid=self.uid)

    def operation(self): return Q.CONTROL / 'preparations' / self.plan['apply_id']

    def test_prepare_load_and_publication_contract_without_public_links(self):
        old = self.root / 'data/original.bundle'; old.write_bytes(b'unrelated original evidence')
        context = self.prepare()
        self.assertEqual(context.guard_proof, self.guard)
        self.assertEqual(self.load().prepared_sha256, context.prepared_sha256)
        self.assertEqual(context.output_identity, P.inode(Path(self.plan['output_root']).lstat()))
        publication = P.Publication(context.ownership_root, self.plan, self.files,
            sources=self.sources, owner=self.uid, group=self.gid)
        publication.prepare()
        self.assertEqual(len(publication.validate()['entries']), 7)
        self.assertEqual(self.load().prepared_sha256, context.prepared_sha256)
        self.assertTrue(all(not Path(p).exists() and not Path(p).is_symlink() for p in self.files))
        self.assertEqual(old.read_bytes(), b'unrelated original evidence')

    def test_same_id_cannot_prepare_twice_even_after_completed_receipt(self):
        context = self.prepare(); before = (self.operation() / 'prepared.json').read_bytes()
        with self.assertRaisesRegex(T.Invalid, 'PROVISION_EXISTS'): self.prepare()
        self.assertEqual((self.operation() / 'prepared.json').read_bytes(), before)
        self.assertEqual(self.load().prepared_sha256, context.prepared_sha256)

    def test_invalid_uid_gid_and_nonroot_refuse_before_filesystem_changes(self):
        for uid, gid in ((True, 10001), (0, 10001), (self.uid + 1, 10001), (self.uid, True), (self.uid, 0)):
            with self.assertRaisesRegex(T.Invalid, 'PROVISION_RUNTIME'): self.original_runtime_owner(uid, gid)
        with patch.object(Q.os, 'geteuid', return_value=self.uid + 1), self.assertRaisesRegex(T.Invalid, 'PROVISION_ROOT'):
            self.prepare()
        self.assertFalse(Q.CONTROL.exists())

    def test_guard_json_bounds_and_types_are_validated_before_claim(self):
        for guard in ([], dict(value=b'raw'), dict(value=(1, 2)), dict(value=float('nan')),
                      dict(value='x' * 4096), {1:'nonstring key'}):
            with self.assertRaisesRegex(T.Invalid, 'PROVISION_GUARD'): self.prepare(guard_proof=guard)
        self.assertFalse(Q.CONTROL.exists())
        changed = copy.deepcopy(self.sources); changed['market'] += b'changed'
        with self.assertRaises(T.Invalid): self.prepare(sources=changed)
        self.assertFalse(Q.CONTROL.exists())

    def test_existing_code_destination_is_not_adopted_or_modified(self):
        code = Path(self.plan['code_root']); code.mkdir(mode=0o755, parents=True)
        sentinel = code / 'keep'; sentinel.write_bytes(b'untouched')
        with self.assertRaisesRegex(T.Invalid, 'PROVISION_EXISTS'): self.prepare()
        self.assertEqual(sentinel.read_bytes(), b'untouched')
        self.assertFalse(self.operation().exists())

    def test_existing_shared_roots_preserve_contents_mode_and_inode(self):
        shared = Path(T.INSTALL); shared.mkdir(mode=0o755)
        sentinel = shared / 'old'; sentinel.write_bytes(b'untouched')
        before = P.inode(shared.lstat())
        self.prepare()
        self.assertEqual(P.inode(shared.lstat()), before)
        self.assertEqual(sentinel.read_bytes(), b'untouched')

    def test_writable_or_symlink_shared_root_is_rejected_not_repaired(self):
        shared = Path(T.INSTALL); shared.mkdir(mode=0o755); shared.chmod(0o777)
        with self.assertRaisesRegex(T.Invalid, 'PROVISION_DIRECTORY'): self.prepare()
        self.assertEqual(shared.stat().st_mode & 0o777, 0o777)
        shared.rmdir(); shared.symlink_to(self.root / 'install')
        with self.assertRaisesRegex(T.Invalid, 'PROVISION_PATH'): self.prepare()
        self.assertTrue(shared.is_symlink())
        self.assertFalse(self.operation().exists())

    def test_interrupted_claim_is_private_and_same_id_cannot_restart(self):
        original = Q._new_directory
        def interrupted(path, *args):
            value = original(path, *args)
            if path == Path(self.plan['code_root']): raise KeyboardInterrupt('synthetic preparation interruption')
            return value
        with patch.object(Q, '_new_directory', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt): self.prepare()
        self.assertTrue(self.operation().is_dir())
        self.assertFalse((self.operation() / 'prepared.json').exists())
        with self.assertRaisesRegex(T.Invalid, 'PROVISION_EXISTS'): self.prepare()
        with self.assertRaises((T.Invalid, FileNotFoundError)): self.load()
        self.assertTrue(all(not Path(p).exists() for p in self.files))

    def test_link_interruption_load_fsyncs_before_return_and_refuses_reprepare(self):
        original = Q.os.link
        def interrupt(source, target, **kwargs):
            original(source, target, **kwargs)
            if Path(target).name == 'prepared.json': raise KeyboardInterrupt('synthetic commit boundary')
        with patch.object(Q.os, 'link', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt): self.prepare()
        self.assertTrue((self.operation() / 'prepared.pending').exists())
        sync = Q._sync
        with patch.object(Q, '_sync', wraps=sync) as barrier:
            self.load()
            barrier.assert_called_once_with(self.operation())
        with patch.object(Q, '_sync', side_effect=OSError('synthetic fsync failure')):
            with self.assertRaises(OSError): self.load()
        with self.assertRaisesRegex(T.Invalid, 'PROVISION_EXISTS'): self.prepare()

    def test_receipt_type_tamper_extra_inventory_and_link_alias_are_rejected(self):
        self.prepare(); path = self.operation() / 'prepared.json'; original = path.read_bytes()
        receipt = Q.J.decode(original); receipt['version'] = True; path.write_bytes(T.canonical(receipt))
        with self.assertRaisesRegex(T.Invalid, 'PROVISION_CHANGED'): self.load()
        path.write_bytes(original)
        unexpected = self.operation() / 'unexpected'; unexpected.write_bytes(b'private')
        with self.assertRaisesRegex(T.Invalid, 'PROVISION_INVENTORY'): self.load()
        unexpected.unlink()
        os.link(path, self.root / 'external.alias')
        with self.assertRaises((T.Invalid, FileNotFoundError)): self.load()

    def test_replaced_ownership_inode_is_rejected_and_output_evidence_is_preserved(self):
        context = self.prepare()
        evidence = Path(self.plan['output_root']) / 'unverified.bundle'
        evidence.write_bytes(b'unverified fixture output')
        self.assertEqual(self.load().prepared_sha256, context.prepared_sha256)
        self.assertEqual(evidence.read_bytes(), b'unverified fixture output')
        owned = context.ownership_root; owned.rename(owned.with_name('old-ownership')); owned.mkdir(mode=0o700)
        # Remove no evidence: the additional private name is independently invalid.
        with self.assertRaises(T.Invalid): self.load()

    def test_ready_receipt_is_private_bounded_canonical_and_inodes_are_exact_types(self):
        context = self.prepare()
        raw = (self.operation() / 'prepared.json').read_bytes()
        self.assertLessEqual(len(raw), 32768)
        self.assertEqual(raw, T.canonical(context.receipt))
        self.assertEqual((self.operation() / 'prepared.json').stat().st_mode & 0o777, 0o600)
        self.assertTrue(all(type(v) is int for identity in context.receipt['directories'].values() for v in identity))
        self.assertEqual(context.ledger_root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(Path(self.plan['output_root']).stat().st_mode & 0o777, 0o750)


if __name__ == '__main__': unittest.main()
