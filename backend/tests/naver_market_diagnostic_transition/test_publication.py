import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import publication as P
import transition as T
from test_transition import sources


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.src = sources()
        for module, key, value in (
            (T, 'INSTALL', str(self.root / 'code')),
            (T, 'OUTPUT', str(self.root / 'output')),
            (T, 'UNIT_ROOT', str(self.root / 'units')),
            (P, 'MASK_ROOT', str(self.root / 'control'))):
            context = patch.object(module, key, value)
            context.start(); self.addCleanup(context.stop)
        self.plan, self.files = T.compile_plan(apply_id='3' * 32, rollback_id='4' * 32,
            sources=self.src, previous={key: T.sha(key.encode()) for key in T.PROOF_KEYS})
        private = self.root / 'private'
        private.mkdir(mode=0o700)
        self.pub = P.Publication(private, self.plan, self.files, sources=self.src,
                                owner=os.getuid(), group=os.getgid())
        for target in self.pub.expected:
            parent = Path(target).parent
            parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        for folder in self.pub.stage_roots.values():
            folder.mkdir(mode=0o700, exist_ok=True)

    def test_seven_owned_links_are_removed_without_touching_original_files(self):
        original = self.root / 'original.bundle'
        original.write_bytes(b'not exported and not rewritten')
        receipt_sha = self.pub.prepare()
        self.assertEqual(len(receipt_sha), 64)
        self.pub.publish('mask'); self.pub.publish('file')
        record = self.pub.validate()
        self.assertEqual(len(record['entries']), 7)
        for target, item in record['entries'].items():
            self.assertEqual(P.inode(Path(target).lstat()), item['inode'])
        self.pub.remove('file'); self.pub.remove('mask')
        self.pub.remove('file'); self.pub.remove('mask')
        self.assertEqual(original.read_bytes(), b'not exported and not rewritten')
        self.assertTrue(all(not Path(p).exists() and not Path(p).is_symlink()
                            for p in self.pub.expected))
        self.assertEqual(len(self.pub.validate()['entries']), 7)

    def test_target_exists_before_prepare_is_never_overwritten(self):
        target = Path(next(iter(self.pub.expected)))
        target.write_bytes(b'unrelated')
        with self.assertRaisesRegex(T.Invalid, 'OWNED_TARGET_EXISTS'): self.pub.prepare()
        self.assertEqual(target.read_bytes(), b'unrelated')
        self.assertFalse((self.pub.root / 'ownership.json').exists())

    def test_identical_bytes_replacement_is_not_owned_inode(self):
        self.pub.prepare(); self.pub.publish('file')
        target = Path(next(iter(self.files)))
        raw = target.read_bytes()
        target.unlink(); target.write_bytes(raw); target.chmod(0o644)
        with self.assertRaisesRegex(T.Invalid, 'OWNED_TARGET_CHANGED'): self.pub.remove('file')
        self.assertEqual(target.read_bytes(), raw)

    def test_modified_staged_bytes_fail_before_publication(self):
        self.pub.prepare()
        record = self.pub.validate()
        item = next(v for v in record['entries'].values() if v['kind'] == 'file')
        stage = Path(item['stage'])
        stage.write_bytes(stage.read_bytes() + b' ')
        with self.assertRaisesRegex(T.Invalid, 'OWNED_STAGE_CHANGED'): self.pub.publish('file')
        self.assertFalse(any(Path(p).exists() for p in self.files))

    def test_unknown_hardlink_and_symlink_replacement_fail_closed(self):
        self.pub.prepare()
        record = self.pub.validate()
        item = next(v for v in record['entries'].values() if v['kind'] == 'file')
        extra = self.root / 'unknown-link'
        os.link(item['stage'], extra)
        with self.assertRaisesRegex(T.Invalid, 'OWNED_LINK'): self.pub.validate()
        extra.unlink()
        stage = Path(item['stage'])
        stage.unlink(); stage.symlink_to('/dev/null')
        with self.assertRaisesRegex(T.Invalid, 'OWNED_STAGE_CHANGED'): self.pub.validate()

    def test_parent_replacement_even_with_same_permissions_is_rejected(self):
        self.pub.prepare()
        parent = self.root / 'units'
        moved = self.root / 'units-before'
        parent.rename(moved); parent.mkdir(mode=0o755)
        with self.assertRaises((T.Invalid, FileNotFoundError)): self.pub.validate()

    def test_interrupted_publication_has_durable_ownership_before_first_effect(self):
        self.pub.prepare()
        real_link = os.link
        count = 0
        def interrupt(*args, **kwargs):
            nonlocal count
            real_link(*args, **kwargs)
            count += 1
            if count == 1: raise KeyboardInterrupt('after target link')
        with patch.object(P.os, 'link', interrupt):
            with self.assertRaises(KeyboardInterrupt): self.pub.publish('mask')
        self.assertEqual(sum(Path(p).is_symlink() for p in self.pub.expected), 1)
        self.pub.validate(); self.pub.remove('mask')
        self.assertFalse(any(Path(p).is_symlink() for p in self.pub.expected))

    def test_interrupted_unlink_can_resume_only_for_owned_remaining_links(self):
        self.pub.prepare(); self.pub.publish('file')
        original_sync = self.pub._sync
        def interrupt(path):
            original_sync(path)
            raise KeyboardInterrupt('after unlink')
        with patch.object(self.pub, '_sync', interrupt):
            with self.assertRaises(KeyboardInterrupt): self.pub.remove('file')
        self.pub.validate(); self.pub.remove('file')
        self.assertFalse(any(Path(p).exists() for p in self.files))

    def test_ownership_commit_interruption_keeps_valid_exact_pending_peer(self):
        real_link = os.link
        def interrupt(*args, **kwargs):
            real_link(*args, **kwargs)
            if Path(args[1]).name == 'ownership.json': raise KeyboardInterrupt()
        with patch.object(P.os, 'link', interrupt):
            with self.assertRaises(KeyboardInterrupt): self.pub.prepare()
        self.assertTrue((self.pub.root / 'ownership.pending').exists())
        self.pub.validate(); self.pub.publish('mask'); self.pub.remove('mask')

    def test_private_incomplete_preparation_cannot_publish_or_retry(self):
        real_write = self.pub._write
        def interrupt(*args, **kwargs):
            real_write(*args, **kwargs)
            raise KeyboardInterrupt()
        with patch.object(self.pub, '_write', interrupt):
            with self.assertRaises(KeyboardInterrupt): self.pub.prepare()
        with self.assertRaises(FileNotFoundError): self.pub.publish('file')
        with self.assertRaisesRegex(T.Invalid, 'OWNED_PREPARATION_EXISTS'): self.pub.prepare()
        self.assertFalse(any(Path(p).exists() for p in self.files))

    def test_unknown_private_inventory_and_numeric_alias_receipt_are_rejected(self):
        self.pub.prepare()
        extra = self.pub.root / 'unknown'
        extra.write_text('ignored?')
        with self.assertRaisesRegex(T.Invalid, 'OWNED_INVENTORY'): self.pub.validate()
        extra.unlink()
        path = self.pub.root / 'ownership.json'
        value = P.decode(path.read_bytes()); value['version'] = True
        path.write_bytes(T.canonical(value))
        with self.assertRaisesRegex(T.Invalid, 'OWNED_RECORD'): self.pub.validate()

    def test_parent_writable_or_stage_symlink_rejected_before_staging(self):
        parent = self.root / 'units'
        parent.chmod(0o777)
        with self.assertRaisesRegex(T.Invalid, 'OWNED_DIRECTORY'): self.pub.prepare()
        parent.chmod(0o755)
        stage = self.pub.stage_roots[str(parent)]
        stage.rmdir(); stage.symlink_to(self.pub.root, target_is_directory=True)
        with self.assertRaisesRegex(T.Invalid, 'OWNED_DIRECTORY'): self.pub.prepare()


if __name__ == '__main__': unittest.main()
