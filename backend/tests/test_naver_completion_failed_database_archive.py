import hashlib
import gzip
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import naver_completion_failed_database_archive as A


class FailedDatabaseArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.data = root / 'data'; self.data.mkdir(mode=0o750)
        self.receipts = root / 'receipts'; self.receipts.mkdir(mode=0o700)
        self.quarantine = self.data / ('.completion-failed-db-' + A.OPERATION_ID)
        self.quarantine.mkdir(mode=0o700)
        self.snapshot = self.receipts / ('completion-db-' + A.OPERATION_ID + '.sqlite')
        self.body = b'SQLite format 3\x00' + b'payload\x00' * 20000
        self.snapshot.write_bytes(self.body); self.snapshot.chmod(0o600)
        (self.quarantine / 'engine.db').write_bytes(self.body + b'failed migration')
        (self.quarantine / 'engine.db').chmod(0o600)
        (self.data / 'engine.db').write_bytes(b'operating database is outside archive scope')
        (self.data / 'engine.db').chmod(0o600)
        self.proof = dict(source_commit=A.OLD_COMMIT, target_commit=A.TARGET_COMMIT,
            operation_id=A.OPERATION_ID, database_sha256=hashlib.sha256(self.body).hexdigest(),
            schema=11, snapshot_restore_verified=True)
        self.proof_path = self.receipts / ('completion-snapshot-' + A.OPERATION_ID + '.json')
        self.proof_path.write_text(json.dumps(self.proof)); self.proof_path.chmod(0o600)
        for key, value in dict(DATA=self.data, RECEIPTS=self.receipts,
                CONTROL_UID=os.getuid(), CONTROL_GID=os.getgid(),
                DATA_UID=os.getuid(), DATA_GID=os.getgid()).items():
            p=patch.object(A,key,value); p.start(); self.addCleanup(p.stop)
        p=patch.object(A.os,'geteuid',return_value=0); p.start(); self.addCleanup(p.stop)

    def test_inspect_uses_only_fixed_metadata_and_preserves_operating_database(self):
        before=(self.data/'engine.db').read_bytes()
        with patch.object(A.os,'read',side_effect=AssertionError('BODY_READ')):
            result=A.inspect_host()
        self.assertEqual(result['operation_id'],A.OPERATION_ID)
        self.assertEqual([r['role'] for r in result['files']],
            ['canonical_snapshot','quarantine_database','quarantine_wal','quarantine_shm','quarantine_journal'])
        self.assertEqual(result['files'][0]['size'],len(self.body))
        self.assertFalse(result['operating_database_modified'])
        self.assertNotIn(str(self.temp.name),json.dumps(result))
        self.assertEqual((self.data/'engine.db').read_bytes(),before)

    def test_canonical_archive_is_separate_reversible_bytes_and_repeat_is_verified_noop(self):
        before=(self.data/'engine.db').read_bytes()
        self.assertEqual(A.execute('archive_canonical_snapshot')['status'],'archived')
        self.assertFalse(self.snapshot.exists())
        folder=self.receipts/('completion-failed-archive-'+A.OPERATION_ID)
        compressed=folder/'canonical_snapshot.gz'
        self.assertEqual(gzip.decompress(compressed.read_bytes()),self.body)
        self.assertTrue((folder/'canonical_snapshot.json').is_file())
        self.assertEqual(A.execute('archive_canonical_snapshot')['status'],'already_archived')
        self.assertEqual((self.data/'engine.db').read_bytes(),before)
        self.assertTrue((self.quarantine/'engine.db').exists())

    def test_restore_uses_new_inode_original_owner_and_mode_without_touching_live_database(self):
        # Hold the removed original inode so the filesystem cannot reuse its number.
        original_fd=os.open(self.snapshot,os.O_RDONLY|os.O_NOFOLLOW)
        self.addCleanup(os.close,original_fd)
        original=os.fstat(original_fd);before=(self.data/'engine.db').read_bytes()
        A.execute('archive_canonical_snapshot')
        result=A.execute('restore_canonical_snapshot')
        restored=self.snapshot.stat()
        self.assertEqual(result['status'],'restored')
        self.assertEqual(self.snapshot.read_bytes(),self.body)
        self.assertNotEqual((restored.st_dev,restored.st_ino),(original.st_dev,original.st_ino))
        self.assertEqual((restored.st_uid,restored.st_gid,stat.S_IMODE(restored.st_mode)),
            (original.st_uid,original.st_gid,0o600))
        self.assertEqual(A.execute('restore_canonical_snapshot')['status'],'already_restored')
        self.assertEqual((self.data/'engine.db').read_bytes(),before)

    def test_quarantine_all_fixed_files_roundtrip_preserves_independent_original_bytes(self):
        originals={}
        for suffix in ('','-wal','-shm','-journal'):
            path=self.quarantine/('engine.db'+suffix)
            if not path.exists():path.write_bytes(('opaque'+suffix).encode()*4000);path.chmod(0o600)
            originals[path.name]=path.read_bytes()
        self.assertEqual(A.execute('archive_quarantine')['files_changed'],4)
        self.assertEqual(list(self.quarantine.iterdir()),[])
        self.assertTrue(self.snapshot.exists())
        self.assertEqual(A.execute('archive_quarantine')['status'],'already_archived')
        self.assertEqual(A.execute('restore_quarantine')['files_changed'],4)
        for name,body in originals.items():
            path=self.quarantine/name
            self.assertEqual(path.read_bytes(),body)
            self.assertEqual((path.stat().st_uid,path.stat().st_gid,stat.S_IMODE(path.stat().st_mode)),
                (os.getuid(),os.getgid(),0o600))
        self.assertEqual(A.execute('restore_quarantine')['status'],'already_restored')

    def test_snapshot_proof_exact_keys_hash_and_target_started_absence_are_required(self):
        for mutant in ({**self.proof,'schema':True},{**self.proof,'unexpected':'private'},
                       {**self.proof,'operation_id':'a'*32},{**self.proof,'database_sha256':'0'*64}):
            self.proof_path.write_text(json.dumps(mutant))
            with self.assertRaises(A.ArchiveInvalid):A.execute('archive_canonical_snapshot')
            self.assertEqual(self.snapshot.read_bytes(),self.body)
        self.proof_path.write_text(json.dumps(self.proof))
        started=self.receipts/('preview-start-'+A.TARGET_COMMIT+'.json');started.write_text('{}')
        with self.assertRaisesRegex(A.ArchiveInvalid,'ARCHIVE_RECEIPT'):A.execute('archive_canonical_snapshot')
        self.assertTrue(self.snapshot.exists())

    def test_receipt_fsync_failure_preserves_source_and_cleans_only_own_partial_files(self):
        fsync=os.fsync
        def fail_receipt(fd):
            path=self.receipts/('completion-failed-archive-'+A.OPERATION_ID)/'canonical_snapshot.json'
            if path.exists() and (os.fstat(fd).st_dev,os.fstat(fd).st_ino)==(path.stat().st_dev,path.stat().st_ino):
                raise OSError('secret path and value must never be exposed')
            return fsync(fd)
        with patch.object(A.os,'fsync',side_effect=fail_receipt),self.assertRaises(OSError):
            A.execute('archive_canonical_snapshot')
        folder=self.receipts/('completion-failed-archive-'+A.OPERATION_ID)
        self.assertEqual(self.snapshot.read_bytes(),self.body)
        self.assertFalse((folder/'canonical_snapshot.gz').exists())
        self.assertFalse((folder/'canonical_snapshot.json').exists())

    def test_foreign_source_inode_after_verified_archive_is_not_unlinked(self):
        remove=A._remove_original;foreign_identity=[]
        def replace(path,fd,identity,role,proof):
            foreign=path.with_name('foreign-test.sqlite');foreign.write_bytes(b'foreign bytes');foreign.chmod(0o600)
            foreign_identity.append((foreign.stat().st_dev,foreign.stat().st_ino));os.replace(foreign,path)
            return remove(path,fd,identity,role,proof)
        with patch.object(A,'_remove_original',side_effect=replace),self.assertRaises(A.ArchiveInvalid):
            A.execute('archive_canonical_snapshot')
        self.assertEqual(self.snapshot.read_bytes(),b'foreign bytes')
        self.assertEqual((self.snapshot.stat().st_dev,self.snapshot.stat().st_ino),foreign_identity[0])
        folder=self.receipts/('completion-failed-archive-'+A.OPERATION_ID)
        self.assertTrue((folder/'canonical_snapshot.gz').exists());self.assertTrue((folder/'canonical_snapshot.json').exists())

    def test_failed_decompression_verification_does_not_remove_original(self):
        decompress=A._decompress
        def corrupt(path,row,**kwargs):
            with path.open('r+b') as output:output.seek(-1,os.SEEK_END);output.write(b'x')
            return decompress(path,row,**kwargs)
        with patch.object(A,'_decompress',side_effect=corrupt),self.assertRaises(A.ArchiveInvalid):
            A.execute('archive_canonical_snapshot')
        self.assertEqual(self.snapshot.read_bytes(),self.body)
        folder=self.receipts/('completion-failed-archive-'+A.OPERATION_ID)
        self.assertFalse((folder/'canonical_snapshot.gz').exists())

    def test_dry_run_capacity_boundary_refuses_without_source_change_and_exact_boundary_works(self):
        amount=len(gzip.compress(self.body,compresslevel=6,mtime=0))
        # GzipFile used by the product has no filename and the same 10-byte header.
        needed=amount+A.RESERVE+A.RECEIPT_ALLOWANCE
        with patch.object(A,'_capacity',return_value=needed-1),self.assertRaisesRegex(A.ArchiveInvalid,'ARCHIVE_SPACE'):
            A.execute('archive_canonical_snapshot')
        self.assertTrue(self.snapshot.exists())
        with patch.object(A,'_capacity',return_value=needed):
            self.assertEqual(A.execute('archive_canonical_snapshot')['status'],'archived')

    def test_during_write_new_external_disk_use_is_detected_and_partial_removed(self):
        space=A._space
        def shrink(path,amount):
            if A.STAGE=='compress':raise A.ArchiveInvalid('ARCHIVE_SPACE')
            return space(path,amount)
        with patch.object(A,'_space',side_effect=shrink),self.assertRaisesRegex(A.ArchiveInvalid,'ARCHIVE_SPACE'):
            A.execute('archive_canonical_snapshot')
        self.assertEqual(self.snapshot.read_bytes(),self.body)
        folder=self.receipts/('completion-failed-archive-'+A.OPERATION_ID)
        self.assertFalse((folder/'canonical_snapshot.gz').exists())

    def test_interrupt_during_compression_preserves_source_and_cleans_created_partial(self):
        write=A._Sink.write
        def interrupted(sink,body):
            result=write(sink,body)
            if sink.fd is not None:raise KeyboardInterrupt()
            return result
        with patch.object(A._Sink,'write',new=interrupted),self.assertRaises(KeyboardInterrupt):
            A.execute('archive_canonical_snapshot')
        self.assertEqual(self.snapshot.read_bytes(),self.body)
        folder=self.receipts/('completion-failed-archive-'+A.OPERATION_ID)
        self.assertFalse((folder/'canonical_snapshot.gz').exists())

    def test_interrupt_after_durable_archive_receipt_can_finish_same_file_without_recompressing(self):
        with patch.object(A,'_remove_original',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
            A.execute('archive_canonical_snapshot')
        self.assertTrue(self.snapshot.exists())
        with patch.object(A,'_compress',side_effect=AssertionError('RECOMPRESS')):
            self.assertEqual(A.execute('archive_canonical_snapshot')['status'],'archived')
        self.assertFalse(self.snapshot.exists())

    def test_restore_after_publish_receipt_interruption_resumes_only_its_sealed_new_inode(self):
        A.execute('archive_canonical_snapshot');record=A._json_new
        def interrupted(path,value):
            if path.name.endswith('.restored.json'):raise KeyboardInterrupt()
            return record(path,value)
        with patch.object(A,'_json_new',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):
            A.execute('restore_canonical_snapshot')
        inode=(self.snapshot.stat().st_dev,self.snapshot.stat().st_ino)
        self.assertEqual(self.snapshot.read_bytes(),self.body)
        self.assertEqual(A.execute('restore_canonical_snapshot')['status'],'restored')
        self.assertEqual((self.snapshot.stat().st_dev,self.snapshot.stat().st_ino),inode)
        self.assertEqual(A.execute('restore_canonical_snapshot')['status'],'already_restored')

    def interrupted_quarantine_restore(self):
        A.execute('archive_quarantine')
        with patch.object(A,'_finish_restore',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
            A.execute('restore_quarantine')
        folder=self.receipts/('completion-failed-archive-'+A.OPERATION_ID)
        temporary=self.quarantine/('engine.db.restore-'+A.OPERATION_ID+'.part')
        return temporary,folder/'quarantine_database.restore-intent.json'

    def test_quarantine_restore_resumes_verified_temporary_before_publish(self):
        temporary,_=self.interrupted_quarantine_restore()
        identity=(temporary.stat().st_dev,temporary.stat().st_ino)
        self.assertFalse((self.quarantine/'engine.db').exists())
        with self.assertRaisesRegex(A.ArchiveInvalid,'ARCHIVE_POLICY'):A.execute('archive_quarantine')
        self.assertEqual(A.execute('restore_quarantine')['status'],'restored')
        restored=self.quarantine/'engine.db'
        self.assertEqual((restored.stat().st_dev,restored.stat().st_ino),identity)
        self.assertEqual(restored.read_bytes(),self.body+b'failed migration')
        self.assertFalse(temporary.exists())

    def test_quarantine_restore_resumes_own_two_links_after_publish(self):
        A.execute('archive_quarantine');remove=A._created_unlink
        def interrupted(path,fd,identity):
            if path.name.endswith('.part'):raise KeyboardInterrupt()
            return remove(path,fd,identity)
        with patch.object(A,'_created_unlink',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):
            A.execute('restore_quarantine')
        restored=self.quarantine/'engine.db'
        self.assertEqual(restored.stat().st_nlink,2)
        identity=(restored.stat().st_dev,restored.stat().st_ino)
        self.assertEqual(A.execute('restore_quarantine')['status'],'restored')
        self.assertEqual((restored.stat().st_dev,restored.stat().st_ino),identity)
        self.assertEqual(restored.stat().st_nlink,1)

    def test_quarantine_restore_rejects_temporary_without_intent_and_arbitrary_role(self):
        temporary,intent=self.interrupted_quarantine_restore();body=intent.read_bytes();intent.unlink()
        with self.assertRaises(A.ArchiveInvalid):A.execute('restore_quarantine')
        self.assertTrue(temporary.exists());self.assertFalse((self.quarantine/'engine.db').exists())
        intent.write_bytes(body);intent.chmod(0o600)
        foreign=self.quarantine/('unapproved.restore-'+A.OPERATION_ID+'.part')
        foreign.write_bytes(b'foreign');foreign.chmod(0o600)
        with self.assertRaisesRegex(A.ArchiveInvalid,'ARCHIVE_POLICY'):A.execute('restore_quarantine')
        self.assertEqual(foreign.read_bytes(),b'foreign');self.assertTrue(temporary.exists())

    def test_quarantine_restore_rejects_changed_sealed_identity_fields(self):
        temporary,intent=self.interrupted_quarantine_restore();original=json.loads(intent.read_text())
        for field in ('device','inode','size','mtime_ns','ctime_ns','uid','gid','mode'):
            changed=json.loads(json.dumps(original));changed['identity'][field]+=1
            intent.write_text(json.dumps(changed))
            with self.subTest(field=field),self.assertRaises(A.ArchiveInvalid):A.execute('restore_quarantine')
            self.assertTrue(temporary.exists());self.assertFalse((self.quarantine/'engine.db').exists())
        intent.write_text(json.dumps(original));temporary.chmod(0o640)
        with self.assertRaises(A.ArchiveInvalid):A.execute('restore_quarantine')
        self.assertTrue(temporary.exists())

    def test_quarantine_restore_rejects_changed_temporary_bytes_even_with_updated_identity(self):
        temporary,intent=self.interrupted_quarantine_restore();value=json.loads(intent.read_text())
        modified=bytearray(temporary.read_bytes());modified[-1]^=1;temporary.write_bytes(modified)
        stamp=value['identity']['mtime_ns'];os.utime(temporary,ns=(stamp,stamp))
        value['identity']=A._identity(temporary.stat());intent.write_text(json.dumps(value))
        with self.assertRaisesRegex(A.ArchiveInvalid,'ARCHIVE_VERIFY'):A.execute('restore_quarantine')
        self.assertTrue(temporary.exists());self.assertFalse((self.quarantine/'engine.db').exists())

    def test_restore_never_overwrites_foreign_existing_file_even_with_identical_content(self):
        A.execute('archive_canonical_snapshot')
        self.snapshot.write_bytes(self.body);self.snapshot.chmod(0o600)
        inode=(self.snapshot.stat().st_dev,self.snapshot.stat().st_ino)
        with self.assertRaisesRegex(A.ArchiveInvalid,'ARCHIVE_SOURCE_CHANGED'):
            A.execute('restore_canonical_snapshot')
        self.assertEqual((self.snapshot.stat().st_dev,self.snapshot.stat().st_ino),inode)
        self.assertEqual(self.snapshot.read_bytes(),self.body)

    def test_restoration_hash_mismatch_refuses_before_any_original_path_is_created(self):
        A.execute('archive_quarantine')
        folder=self.receipts/('completion-failed-archive-'+A.OPERATION_ID)
        manifest=folder/'quarantine_database.json';value=json.loads(manifest.read_text())
        value['source_sha256']='0'*64;manifest.write_text(json.dumps(value))
        with self.assertRaisesRegex(A.ArchiveInvalid,'ARCHIVE_VERIFY'):A.execute('restore_quarantine')
        self.assertFalse((self.quarantine/'engine.db').exists())
        self.assertTrue((folder/'quarantine_database.gz').exists())

    def test_restore_free_space_failure_preserves_archive_and_absent_original(self):
        A.execute('archive_canonical_snapshot')
        with patch.object(A,'_capacity',return_value=A.RESERVE+len(self.body)-1),\
                self.assertRaisesRegex(A.ArchiveInvalid,'ARCHIVE_SPACE'):
            A.execute('restore_canonical_snapshot')
        self.assertFalse(self.snapshot.exists())
        folder=self.receipts/('completion-failed-archive-'+A.OPERATION_ID)
        self.assertTrue((folder/'canonical_snapshot.gz').is_file())

    def test_quarantine_replacement_after_inventory_is_refused_and_other_operation_untouched(self):
        other=self.data/('.completion-failed-db-'+'a'*32);other.mkdir()
        untouched=other/'engine.db';untouched.write_bytes(b'never touch another operation')
        archive=A._archive_one
        def replace(role,folder,proof,expected_identity=None):
            if role=='quarantine_database':
                path=self.quarantine/'engine.db';foreign=self.quarantine/'foreign.tmp'
                foreign.write_bytes(b'foreign');foreign.chmod(0o600);os.replace(foreign,path)
            return archive(role,folder,proof,expected_identity)
        with patch.object(A,'_archive_one',side_effect=replace),self.assertRaisesRegex(A.ArchiveInvalid,'ARCHIVE_SOURCE_CHANGED'):
            A.execute('archive_quarantine')
        self.assertEqual((self.quarantine/'engine.db').read_bytes(),b'foreign')
        self.assertEqual(untouched.read_bytes(),b'never touch another operation')

    def test_symlink_parent_and_duplicate_receipt_are_refused(self):
        destination=self.data/'another';destination.mkdir()
        self.quarantine.rmdir() if not list(self.quarantine.iterdir()) else None
        (self.quarantine/'engine.db').unlink();self.quarantine.rmdir();self.quarantine.symlink_to(destination,target_is_directory=True)
        with patch.object(A.os,'read',side_effect=AssertionError('BODY_READ')),self.assertRaises(OSError):A.inspect_host()
        self.quarantine.unlink();self.quarantine.mkdir(mode=0o700)
        self.proof_path.write_text('{"schema":11,"schema":11}')
        with self.assertRaisesRegex(A.ArchiveInvalid,'ARCHIVE_RECEIPT'):A.execute('archive_canonical_snapshot')

    def test_closed_failure_diagnostics_never_include_exception_text_paths_or_hashes(self):
        error=OSError('private path /root/example.db account=secret')
        report=A.failure_report(error)
        self.assertEqual(set(report),{'ok','status','stage','code'})
        self.assertFalse(report['ok']);self.assertEqual(report['code'],'ARCHIVE_IO')
        self.assertNotIn('secret',json.dumps(report))
        with self.assertRaisesRegex(A.ArchiveInvalid,'ARCHIVE_ACTION'):A.execute('other-operation')


if __name__ == '__main__':
    unittest.main()
