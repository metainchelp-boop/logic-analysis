"""Synthetic pipes/files plus optional isolated GPG; no SSH or company keys."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

PATH = Path(__file__).resolve().parents[1] / 'naver_archive_transport.py'
SPEC = importlib.util.spec_from_file_location('naver_transport', PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)

CANARY = 'SYNTHETIC_PLAINTEXT_NOT_FOR_RECEIPTS'
PAYLOAD = (CANARY.encode() + b'\0') * 17003


def child(code):
    return [sys.executable, '-I', '-B', '-c', code]


SOURCE = child('import os; os.write(1, (' + repr(CANARY.encode() + b'\0') + ')*17003)')
PASSTHROUGH = child('import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data[::-1])')
# Independent protocol consumer, not the production framing parser.
REMOTE_CODE = """import sys,hashlib,json,struct
stream = sys.stdin.buffer
magic = b'NAVER-ARCHIVE-CIPHER-FRAMES-V1\\n'
assert stream.read(len(magic)) == magic
payload = bytearray()
while True:
    size = struct.unpack('>I', stream.read(4))[0]
    if not size:
        total = struct.unpack('>Q', stream.read(8))[0]
        digest = stream.read(32)
        assert total == len(payload) and digest == hashlib.sha256(payload).digest()
        assert stream.read(1) == b''
        break
    assert 0 < size <= 65536
    data = stream.read(size)
    assert len(data) == size
    payload.extend(data)
print(json.dumps({'status':'received_unverified','bytes':len(payload),
                  'sha256':hashlib.sha256(payload).hexdigest()}))
"""
REMOTE = child(REMOTE_CODE)



class TransportTests(unittest.TestCase):
    def refuse(self, code, fn, *args, **kwargs):
        with self.assertRaises(subject.Refused) as caught:
            fn(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(CANARY, str(caught.exception))

    def test_send_streams_bounded_cipher_and_matching_remote_receipt(self):
        result = subject.stream_send(SOURCE, PASSTHROUGH, REMOTE, timeout=5)
        self.assertEqual(result, {'bytes': len(PAYLOAD),
                                 'sha256': hashlib.sha256(PAYLOAD[::-1]).hexdigest()})
        self.assertNotIn(CANARY, json.dumps(result))

    def test_producer_exit_failure_rejects_matching_cipher_receipt(self):
        source = child('import os; os.write(1,b"partial"); raise SystemExit(7)')
        self.refuse('pipeline_failed', subject.stream_send, source, PASSTHROUGH, REMOTE, timeout=5)

    def test_encryptor_exit_failure_rejects_matching_cipher_receipt(self):
        gpg = child('import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b"partial"); raise SystemExit(7)')
        self.refuse('pipeline_failed', subject.stream_send, SOURCE, gpg, REMOTE, timeout=5)

    def test_ssh_nonzero_rejects_matching_receipt(self):
        remote = child(REMOTE[-1] + '\nraise SystemExit(8)')
        self.refuse('pipeline_failed', subject.stream_send, SOURCE, PASSTHROUGH, remote, timeout=5)

    def test_ssh_early_exit_cleans_up_pipeline(self):
        started = time.monotonic()
        with self.assertRaises(subject.Refused):
            subject.stream_send(SOURCE, PASSTHROUGH, child('pass'), timeout=2)
        self.assertLess(time.monotonic() - started, 4)

    def test_cipher_limit_aborts_before_acknowledgement(self):
        self.refuse('cipher_limit', subject.stream_send, SOURCE, PASSTHROUGH, REMOTE,
                    timeout=5, max_cipher=100)

    def test_terminal_waits_for_source_exit_after_cipher_eof(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = str(Path(folder) / 'source-exited')
            source = child('import os,time,pathlib; os.write(1,b"payload"); os.close(1); '
                           'time.sleep(.15); pathlib.Path(' + repr(marker) + ').write_text("done")')
            remote = child(REMOTE_CODE.replace("print(json.dumps", 'assert __import__("os").path.exists('
                           + repr(marker) + ')\nprint(json.dumps'))
            result = subject.stream_send(source, PASSTHROUGH, remote, timeout=5)
            self.assertEqual(result['sha256'], hashlib.sha256(b'payload'[::-1]).hexdigest())

    def test_source_failure_after_gpg_success_cannot_send_terminal(self):
        with tempfile.TemporaryDirectory() as folder:
            captured = Path(folder) / 'wire'
            source = child('import os,time; os.write(1,b"payload"); os.close(1); '
                           'time.sleep(.25); raise SystemExit(7)')
            capture = child('import os; f=open(' + repr(str(captured)) + ',"wb",buffering=0)\n'
                            'while True:\n d=os.read(0,65536)\n if not d: break\n f.write(d)')
            self.refuse('pipeline_failed', subject.stream_send, source, PASSTHROUGH, capture, timeout=5)
            wire = captured.read_bytes()
            self.assertEqual(wire, subject.WIRE_MAGIC + struct.pack('>I', 7) + b'payload'[::-1])

    def test_terminal_waits_for_inherited_upstream_stderr_eof(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = str(Path(folder) / 'stderr-released')
            source = child('import os,time,pathlib; os.write(1,b"payload"); os.close(1); pid=os.fork()\n'
                           'if pid == 0:\n time.sleep(.15)\n pathlib.Path(' + repr(marker)
                           + ').write_text("done")\n os._exit(0)\nos._exit(0)')
            remote = child(REMOTE_CODE.replace("print(json.dumps", 'assert __import__("os").path.exists('
                           + repr(marker) + ')\nprint(json.dumps'))
            result = subject.stream_send(source, PASSTHROUGH, remote, timeout=5)
            self.assertEqual(result['bytes'], 7)

    def test_combined_upstream_stderr_limit_blocks_terminal(self):
        source = child('import os; os.write(2,b"x"*40000); os.write(1,b"payload")')
        encryptor = child('import sys,os; d=sys.stdin.buffer.read(); '
                          'os.write(1,d); os.write(2,b"x"*40000)')
        self.refuse('output_limit', subject.stream_send, source, encryptor, REMOTE, timeout=5)

    def test_small_cipher_reads_are_coalesced_into_bounded_full_frames(self):
        length = 2 * subject.FRAME_BYTES + 13
        source = child('import os; os.write(1,b"x"*' + str(length) + ')')
        encryptor = child('import os\nwhile True:\n d=os.read(0,97)\n if not d: break\n os.write(1,d)')
        remote_code = REMOTE_CODE.replace('payload = bytearray()', 'payload = bytearray(); sizes = []')
        remote_code = remote_code.replace('data = stream.read(size)', 'sizes.append(size)\n    data = stream.read(size)')
        remote_code = remote_code.replace('print(json.dumps', 'assert sizes == [65536,65536,13]\nprint(json.dumps')
        result = subject.stream_send(source, encryptor, child(remote_code), timeout=5)
        self.assertEqual(result['bytes'], length)

    def test_wrong_receipt_hash_rejected(self):
        remote = child('import sys,json; d=sys.stdin.buffer.read(); '
                       'print(json.dumps({"status":"received_unverified","bytes":len(d),"sha256":"0"*64}))')
        self.refuse('receipt_invalid', subject.stream_send, SOURCE, PASSTHROUGH, remote, timeout=5)

    def test_duplicate_receipt_fields_rejected(self):
        remote = child('import sys; sys.stdin.buffer.read(); print(\'{"status":"received_unverified","bytes":1,"bytes":2,"sha256":"a"}\')')
        self.refuse('receipt_invalid', subject.stream_send, SOURCE, PASSTHROUGH, remote, timeout=5)

    def test_stderr_is_bounded_and_not_returned(self):
        source = child('import sys; sys.stderr.write("' + CANARY + '"*10000)')
        self.refuse('output_limit', subject.stream_send, source, PASSTHROUGH, REMOTE, timeout=5)

    def test_empty_cipher_never_succeeds(self):
        self.refuse('pipeline_failed', subject.stream_send, child('pass'), PASSTHROUGH, REMOTE, timeout=5)

    def test_deadline_terminates_children_including_held_pipe(self):
        source = child('import os,time; pid=os.fork(); time.sleep(60) if pid == 0 else None')
        started = time.monotonic()
        self.refuse('deadline_exceeded', subject.stream_send, source, PASSTHROUGH, REMOTE, timeout=.2)
        self.assertLess(time.monotonic() - started, 4)

    def test_spawn_failure_reaps_previously_started_producer(self):
        real = subject.subprocess.Popen
        children = []
        def fail_second(*args, **kwargs):
            if children:
                raise OSError('synthetic spawn failure')
            process = real(*args, **kwargs)
            children.append(process)
            return process
        with mock.patch.object(subject.subprocess, 'Popen', side_effect=fail_second):
            with self.assertRaises(OSError):
                subject.stream_send(child('import time; time.sleep(60)'), PASSTHROUGH, REMOTE, timeout=5)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(children[0].stdout.closed)
        self.assertTrue(children[0].stderr.closed)

    def test_command_limits_and_discards_stderr(self):
        self.assertEqual(subject.command(child('print("safe")')), b'safe\n')
        self.refuse('output_limit', subject.command, child('print("x"*100)'), limit=3)
        self.refuse('command_failed', subject.command,
                    child('import sys; sys.stderr.write("' + CANARY + '"); raise SystemExit(4)'))

    def test_new_fixed_ssh_commands_and_host_validation(self):
        for action in (subject.RECEIVE, subject.FETCH):
            argv = subject.ssh_args('/key', '/knownhosts', action)
            self.assertEqual(argv[-2:], ['root@139.162.109.181', action])
            for value in ('BatchMode=yes', 'StrictHostKeyChecking=yes', 'ForwardAgent=no',
                          'GlobalKnownHostsFile=/dev/null', 'ControlPath=none', 'UpdateHostKeys=no'):
                self.assertIn(value, argv)
            self.assertEqual(argv[1:4], ['-F', '/dev/null', '-T'])
        self.refuse('internal_failure', subject.ssh_args, '/key', '/hosts', 'receive-data-snapshot-20261102-v1')
        quoted = subject.ssh_args('/key', '/secure/a space/hosts', subject.FETCH)
        self.assertIn('UserKnownHostsFile="/secure/a space/hosts"', quoted)
        self.refuse('unsafe_path', subject.ssh_args, '/key', '/hosts\nother', subject.FETCH)


class FramedGpgIntegrationTests(unittest.TestCase):
    def setUp(self):
        candidates = ('/usr/bin/gpg', '/opt/homebrew/bin/gpg', '/usr/local/bin/gpg')
        self.binary = next((path for path in candidates if os.path.isfile(path)), None)
        if self.binary is None:
            self.skipTest('GPG is not installed in the fixed executable locations')
        temp = tempfile.TemporaryDirectory(prefix='nac-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / 'gpg'
        self.home.mkdir(mode=0o700)
        resolved = Path(self.binary).resolve()
        gpgconf = resolved.with_name('gpgconf')
        if gpgconf.is_file():
            self.addCleanup(lambda: subprocess.run([str(gpgconf), '--homedir', str(self.home),
                '--kill', 'gpg-agent'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10, check=False))
        # This public fixture phrase has no relationship to a company recovery key.
        self.gpg = [self.binary, '--no-options', '--homedir', str(self.home), '--batch',
                    '--no-tty', '--pinentry-mode', 'loopback', '--passphrase', 'synthetic-test-only',
                    '--compress-algo', 'none', '--cipher-algo', 'AES256', '--s2k-count', '1024']

    def receiver(self, name):
        root = self.root / name
        folder = root / 'var/backups/metainc-app-retirement/naver-archives-20261106-v1'
        folder.mkdir(parents=True, mode=0o700)
        folder.parent.chmod(0o700)
        receiver_path = str(PATH.with_name('naver_archive_receiver.py'))
        code = """import importlib.util,json,os,sys,types
spec=importlib.util.spec_from_file_location('isolated_receiver',RECEIVER_PATH)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.OWNER_UID=os.getuid();m.OWNER_GID=os.getgid()
m.os.fstatvfs=lambda fd:types.SimpleNamespace(f_bavail=20*1024**3,f_frsize=1)
root=os.open(ROOT_PATH,m.DIRECTORY_FLAGS);state={'bytes':0}
try:
    answer=m.receive_into(sys.stdin.buffer,root,state);code=0
except m.ReceiverError as error:
    answer=m.receipt(error.code,state['bytes']);code=2
finally:
    os.close(root)
print(json.dumps(answer));raise SystemExit(code)
""".replace('RECEIVER_PATH', repr(receiver_path)).replace('ROOT_PATH', repr(str(root)))
        return child(code), folder

    def test_real_gpg_framed_roundtrip_and_valid_cipher_without_terminal_refused(self):
        payload = b'SYNTHETIC_ONLY\0' * 7001
        # Keep the generated subprocess code small while preserving exact expected bytes.
        source = child('import os; os.write(1,b"SYNTHETIC_ONLY\\0"*7001)')
        remote, folder = self.receiver('roundtrip')
        result = subject.stream_send(source, self.gpg + ['--output', '-', '--symmetric'], remote, timeout=20)
        cipher = (folder / 'archives.gpg').read_bytes()
        self.assertEqual(result, {'bytes': len(cipher), 'sha256': hashlib.sha256(cipher).hexdigest()})
        decrypted = subprocess.run(self.gpg + ['--output', '-', '--decrypt'], input=cipher,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
        self.assertEqual(decrypted.returncode, 0, 'Synthetic GPG decryption failed')
        self.assertEqual(decrypted.stdout, payload)
        self.assertFalse((folder / 'archives.gpg.partial').exists())
        remote, folder = self.receiver('missing-terminal')
        wire = bytearray(subject.WIRE_MAGIC)
        for offset in range(0, len(cipher), subject.FRAME_BYTES):
            block = cipher[offset:offset + subject.FRAME_BYTES]
            wire.extend(struct.pack('>I', len(block)))
            wire.extend(block)
        refused = subprocess.run(remote, input=wire, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, timeout=10, check=False)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(json.loads(refused.stdout)['status'], 'frame_truncated')
        self.assertEqual((folder / 'archives.gpg.partial').read_bytes(), cipher)
        self.assertFalse((folder / 'archives.gpg').exists())

    def test_real_gpg_success_cannot_commit_when_source_later_exits_nonzero(self):
        marker = self.root / 'gpg-exit'
        gpg = child('import subprocess,pathlib; result=subprocess.run(' + repr(self.gpg
                    + ['--output', '-', '--symmetric']) + '); pathlib.Path(' + repr(str(marker))
                    + ').write_text(str(result.returncode)); raise SystemExit(result.returncode)')
        source = child('import os,time,pathlib; os.write(1,b"synthetic prefix"); os.close(1); '
                       'deadline=time.monotonic()+10\nwhile not pathlib.Path(' + repr(str(marker))
                       + ').exists():\n assert time.monotonic()<deadline\n time.sleep(.01)\n'
                       'time.sleep(.15)\nraise SystemExit(7)')
        remote, folder = self.receiver('source-failed')
        with self.assertRaises(subject.Refused) as caught:
            subject.stream_send(source, gpg, remote, timeout=20)
        self.assertEqual(caught.exception.code, 'pipeline_failed')
        self.assertEqual(marker.read_text(), '0')
        self.assertFalse((folder / 'archives.gpg').exists())
        self.assertTrue((folder / 'archives.gpg.partial').exists())
        self.assertGreater((folder / 'archives.gpg.partial').stat().st_size, 0)


class FilesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(os.path.realpath(temp.name))
        self.files = subject.Files(str(self.root), os.geteuid())
        (self.root / 'secure').mkdir(mode=0o700)
        self.payload = b'SYNTHETIC_CIPHERTEXT' * 1000
        self.receipt = {'status': 'sent_unverified', 'session': subject.SESSION,
                        'plan_sha256': 'a' * 64, 'bytes': len(self.payload),
                        'sha256': hashlib.sha256(self.payload).hexdigest()}

    def fetch(self, payload=None, **kwargs):
        code = 'import os; os.write(1,' + repr(self.payload if payload is None else payload) + ')'
        return subject.stream_fetch(child(code), self.receipt, '/secure/cipher.gpg', self.files, timeout=5, **kwargs)

    def test_fetch_same_fd_verification_and_exclusive_publication(self):
        result = self.fetch()
        self.assertEqual(result['status'], 'fetched_unverified')
        self.assertEqual((self.root / 'secure/cipher.gpg').read_bytes(), self.payload)
        self.assertEqual((self.root / 'secure/cipher.gpg').stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.root / 'secure/cipher.gpg.partial').exists())
        with self.assertRaises(subject.Refused) as caught:
            self.fetch()
        self.assertEqual(caught.exception.code, 'file_exists')

    def test_fetch_truncation_keeps_partial_no_final(self):
        with self.assertRaises(subject.Refused) as caught:
            self.fetch(self.payload[:100])
        self.assertEqual(caught.exception.code, 'cipher_mismatch')
        self.assertEqual((self.root / 'secure/cipher.gpg.partial').read_bytes(), self.payload[:100])
        self.assertFalse((self.root / 'secure/cipher.gpg').exists())

    def test_fetch_oversize_keeps_partial_no_final(self):
        with self.assertRaises(subject.Refused) as caught:
            self.fetch(self.payload + b'extra')
        self.assertEqual(caught.exception.code, 'cipher_limit')
        self.assertTrue((self.root / 'secure/cipher.gpg.partial').exists())
        self.assertFalse((self.root / 'secure/cipher.gpg').exists())

    def test_fetch_matching_cipher_but_ssh_failure_is_not_success(self):
        argv = child('import os; os.write(1,' + repr(self.payload) + '); raise SystemExit(3)')
        with self.assertRaises(subject.Refused) as caught:
            subject.stream_fetch(argv, self.receipt, '/secure/cipher.gpg', self.files, timeout=5)
        self.assertEqual(caught.exception.code, 'pipeline_failed')
        self.assertFalse((self.root / 'secure/cipher.gpg').exists())
        self.assertEqual((self.root / 'secure/cipher.gpg.partial').read_bytes(), self.payload)

    def test_fetch_existing_partial_refused_not_overwritten(self):
        partial = self.root / 'secure/cipher.gpg.partial'
        partial.write_bytes(b'previous evidence')
        with self.assertRaises(FileExistsError):
            self.fetch()
        self.assertEqual(partial.read_bytes(), b'previous evidence')

    def test_fetch_path_swap_during_same_fd_rehash_refuses_publication(self):
        real_lseek = subject.os.lseek
        partial = self.root / 'secure/cipher.gpg.partial'
        def swap(fd, offset, whence):
            result = real_lseek(fd, offset, whence)
            partial.rename(partial.with_name('retained-original.partial'))
            partial.write_bytes(self.payload)
            partial.chmod(0o600)
            return result
        with mock.patch.object(subject.os, 'lseek', side_effect=swap):
            with self.assertRaises(subject.Refused) as caught:
                self.fetch()
        self.assertEqual(caught.exception.code, 'path_changed')
        self.assertFalse((self.root / 'secure/cipher.gpg').exists())

    def test_fetch_partial_replacement_after_final_link_is_preserved(self):
        real_stat = subject.os.stat
        partial = self.root / 'secure/cipher.gpg.partial'
        detached = partial.with_name('retained-original.partial')
        changed = False
        def swapped(name, *args, **kwargs):
            nonlocal changed
            result = real_stat(name, *args, **kwargs)
            if name == 'cipher.gpg' and kwargs.get('dir_fd') is not None and not changed:
                changed = True
                partial.rename(detached)
                partial.write_bytes(b'replacement-must-stay')
                partial.chmod(0o600)
            return result
        with mock.patch.object(subject.os, 'stat', side_effect=swapped):
            with self.assertRaises(subject.Refused) as caught:
                self.fetch()
        self.assertEqual(caught.exception.code, 'path_changed')
        self.assertEqual(partial.read_bytes(), b'replacement-must-stay')
        self.assertEqual(detached.read_bytes(), self.payload)
        self.assertEqual((self.root / 'secure/cipher.gpg').read_bytes(), self.payload)

    def test_fetch_postlink_mode_change_blocks_unlink(self):
        real_link = subject.os.link
        partial = self.root / 'secure/cipher.gpg.partial'
        def changed(*args, **kwargs):
            result = real_link(*args, **kwargs)
            partial.chmod(0o640)
            return result
        with mock.patch.object(subject.os, 'link', side_effect=changed):
            with self.assertRaises(subject.Refused) as caught:
                self.fetch()
        self.assertEqual(caught.exception.code, 'path_changed')
        self.assertTrue(partial.exists())
        self.assertTrue((self.root / 'secure/cipher.gpg').exists())

    def test_fetch_postlink_third_alias_blocks_unlink(self):
        real_link = subject.os.link
        partial = self.root / 'secure/cipher.gpg.partial'
        def changed(*args, **kwargs):
            result = real_link(*args, **kwargs)
            real_link(partial, partial.with_name('third-alias'))
            return result
        with mock.patch.object(subject.os, 'link', side_effect=changed):
            with self.assertRaises(subject.Refused) as caught:
                self.fetch()
        self.assertEqual(caught.exception.code, 'path_changed')
        self.assertEqual(partial.stat().st_nlink, 3)

    def test_fetch_postlink_partial_disappearance_is_path_changed(self):
        real_link = subject.os.link
        partial = self.root / 'secure/cipher.gpg.partial'
        def changed(*args, **kwargs):
            result = real_link(*args, **kwargs)
            partial.rename(partial.with_name('detached'))
            return result
        with mock.patch.object(subject.os, 'link', side_effect=changed):
            with self.assertRaises(subject.Refused) as caught:
                self.fetch()
        self.assertEqual(caught.exception.code, 'path_changed')
        self.assertEqual((self.root / 'secure/detached').read_bytes(), self.payload)
        self.assertEqual((self.root / 'secure/cipher.gpg').read_bytes(), self.payload)

    def test_fetch_capacity_checks_before_output_creation(self):
        small = types.SimpleNamespace(f_bavail=10, f_frsize=1)
        with mock.patch.object(subject.os, 'fstatvfs', return_value=small):
            with self.assertRaises(subject.Refused) as caught:
                self.fetch()
        self.assertEqual(caught.exception.code, 'space_insufficient')
        self.assertEqual(list((self.root / 'secure').iterdir()), [])

    def test_fetch_midstream_disk_pressure_keeps_evidence(self):
        ample = types.SimpleNamespace(f_bavail=10 ** 12, f_frsize=1)
        small = types.SimpleNamespace(f_bavail=10, f_frsize=1)
        with mock.patch.object(subject.os, 'fstatvfs', side_effect=[ample, small]):
            with self.assertRaises(subject.Refused) as caught:
                self.fetch()
        self.assertEqual(caught.exception.code, 'space_insufficient')
        self.assertTrue((self.root / 'secure/cipher.gpg.partial').exists())
        self.assertFalse((self.root / 'secure/cipher.gpg').exists())

    def test_symlink_parent_and_output_refused(self):
        (self.root / 'link').symlink_to(self.root / 'secure', target_is_directory=True)
        with self.assertRaises(subject.Refused):
            subject.stream_fetch(child('pass'), self.receipt, '/link/cipher', self.files, timeout=5)
        (self.root / 'secure/cipher.gpg').symlink_to(self.root / 'target')
        with self.assertRaises(subject.Refused) as caught:
            self.fetch()
        self.assertEqual(caught.exception.code, 'file_exists')

    def test_file_security_and_identity_revalidation(self):
        path = self.root / 'secure/plan.json'
        path.write_bytes(b'{}')
        path.chmod(0o600)
        self.assertEqual(self.files.read('/secure/plan.json', 100, 0o600), b'{}')
        with self.assertRaises(subject.Refused) as caught:
            with self.files.opened('/secure/plan.json', 0o600):
                path.rename(path.with_name('old.json'))
                path.write_bytes(b'{}')
                path.chmod(0o600)
        self.assertEqual(caught.exception.code, 'path_changed')
        path.chmod(0o644)
        with self.assertRaises(subject.Refused):
            self.files.read('/secure/plan.json', 100, 0o600)

    def test_one_shot_session_directory_cannot_be_reused(self):
        self.files.mkdir('/secure/new-session')
        self.files.create('/secure/new-session/attempt.json', b'{}')
        with self.assertRaises(subject.Refused) as caught:
            self.files.mkdir('/secure/new-session')
        self.assertEqual(caught.exception.code, 'session_exists')

    def test_receipt_rejects_bool_size_extra_field_and_wrong_session(self):
        for change in ({'bytes': True}, {'extra': True}, {'session': 'data-snapshot-20261102-v1'},
                       {'sha256': 'invalid'}, {'status': 'verified'}):
            with self.assertRaises(subject.Refused):
                subject.validate_sent({**self.receipt, **change})

    def test_pinned_public_assets_accepted_changed_asset_refused(self):
        folder = self.root / 'secure/assets'
        folder.mkdir()
        for name in ('recovery-public.asc', 'server-b-known-hosts'):
            (folder / name).write_bytes((PATH.parent / 'preservation' / name).read_bytes())
        subject.assets(self.files, '/secure/assets')
        (folder / 'server-b-known-hosts').write_bytes(b'untrusted host')
        with self.assertRaises(subject.Refused) as caught:
            subject.assets(self.files, '/secure/assets')
        self.assertEqual(caught.exception.code, 'asset_invalid')


class SendInterfaceTests(unittest.TestCase):
    def setUp(self):
        FilesTests.setUp(self)
        self.base = str(PATH.parent)
        source_dir = self.root / self.base.lstrip('/')
        source_dir.mkdir(parents=True)
        (source_dir / 'preservation').mkdir()
        for name in ('recovery-public.asc', 'server-b-known-hosts'):
            (source_dir / 'preservation' / name).write_bytes((PATH.parent / 'preservation' / name).read_bytes())
        (source_dir / 'naver_archive_source.py').write_bytes(b'# Synthetic source fixture')
        (self.root / 'usr/bin').mkdir(parents=True)
        for name in ('gpg', 'ssh'):
            (self.root / 'usr/bin' / name).write_bytes(b'# Synthetic dependency fixture')
        self.files.create('/secure/plan.json', b'{"version":1}')
        self.files.create('/secure/new-transport-key', CANARY.encode())
        self.args = types.SimpleNamespace(plan='/secure/plan.json',
            plan_sha256=hashlib.sha256(b'{"version":1}').hexdigest(),
            transport_key='/secure/new-transport-key', session_dir='/secure/session')

    def command(self, argv, **kwargs):
        self.assertEqual(argv[0], '/usr/bin/gpg')
        self.assertIn('--no-options', argv)
        self.assertIn('--no-autostart', argv)
        if '--list-keys' in argv:
            return ('pub:-:255:22:x:0:0:::::c:\nfpr:::::::::' + subject.RECIPIENT + ':\n').encode()
        self.assertIn('--import', argv)
        return b''

    def test_send_cli_uses_public_assets_and_fixed_source_interface(self):
        result = {'bytes': 111, 'sha256': 'c' * 64}
        with mock.patch.object(subject.os, 'geteuid', return_value=0), \
                mock.patch.object(subject, 'command', side_effect=self.command), \
                mock.patch.object(subject, 'stream_send', return_value=result) as sending, \
                mock.patch.object(self.files, 'read', wraps=self.files.read) as reading:
            receipt = subject.send(self.args, self.files)
        self.assertEqual(receipt, {'status': 'sent_unverified', 'session': subject.SESSION,
            'plan_sha256': self.args.plan_sha256, **result})
        source, gpg, ssh = sending.call_args.args
        self.assertEqual(source[1:], ['-I', '-B', self.base + '/naver_archive_source.py',
            'stream', '--plan', self.args.plan, '--plan-sha256', self.args.plan_sha256])
        self.assertIn('AES256', gpg)
        self.assertIn('none', gpg)
        self.assertEqual(ssh[-1], subject.RECEIVE)
        self.assertNotIn(self.args.transport_key, [call.args[0] for call in reading.call_args_list])
        saved = (self.root / 'secure/session/sent.json').read_bytes()
        self.assertEqual(saved, subject.canonical(receipt))
        self.assertNotIn(CANARY.encode(), saved)

    def test_failed_send_leaves_one_shot_attempt_and_refuses_retry(self):
        with mock.patch.object(subject.os, 'geteuid', return_value=0), \
                mock.patch.object(subject, 'command', side_effect=self.command), \
                mock.patch.object(subject, 'stream_send', side_effect=subject.Refused('pipeline_failed')):
            with self.assertRaises(subject.Refused) as caught:
                subject.send(self.args, self.files)
            self.assertEqual(caught.exception.code, 'pipeline_failed')
            self.assertTrue((self.root / 'secure/session/attempt.json').is_file())
            self.assertFalse((self.root / 'secure/session/sent.json').exists())
            with self.assertRaises(subject.Refused) as caught:
                subject.send(self.args, self.files)
            self.assertEqual(caught.exception.code, 'session_exists')

    def test_plan_hash_mismatch_refused_before_any_send_or_session_write(self):
        self.args.plan_sha256 = 'f' * 64
        with mock.patch.object(subject.os, 'geteuid', return_value=0):
            with self.assertRaises(subject.Refused) as caught:
                subject.send(self.args, self.files)
        self.assertEqual(caught.exception.code, 'plan_invalid')
        self.assertFalse((self.root / 'secure/session').exists())


if __name__ == '__main__':
    unittest.main()
