"""One synthetic namespace only: no SSH, live key, Docker, or backup access."""
import contextlib
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
from dataclasses import replace

SPEC = importlib.util.spec_from_file_location(
    'retirement_images_receiver', Path(__file__).resolve().parents[1] / 'retirement_images_receiver.py')
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
CANARY = b'PRIVATE_SYNTHETIC_PAYLOAD_NOT_A_REAL_KEY'


class ImagesReceiverTest(unittest.TestCase):
    def setUp(self):
        self.profiles = subject.load_profiles()
        self.profile = self.profiles.lookup('autobid-web')
        self.parents = ('var', 'backups', 'metainc-app-retirement', self.profile.session)
        self.temp = tempfile.TemporaryDirectory(prefix='cipher-receiver-fixture-')
        self.base = Path(self.temp.name).resolve()
        self.folder = self.base.joinpath(*self.parents)
        self.folder.mkdir(parents=True)
        self.folder.chmod(0o700)
        self.folder.parent.chmod(0o700)
        self.root = os.open(self.base, subject.DIRECTORY_FLAGS)
        self.patches = contextlib.ExitStack()
        self.patches.enter_context(mock.patch.object(subject, 'OWNER_UID', os.getuid()))
        self.patches.enter_context(mock.patch.object(subject, 'OWNER_GID', os.getgid()))
        space = types.SimpleNamespace(f_bavail=4 * 1024 * 1024, f_frsize=4096)
        self.patches.enter_context(mock.patch.object(subject.os, 'fstatvfs', return_value=space))

    def tearDown(self):
        self.patches.close()
        os.close(self.root)
        self.temp.cleanup()

    @contextlib.contextmanager
    def override(self, **values):
        previous = self.profile
        self.profile = replace(self.profile, **values)
        try:
            yield
        finally:
            self.profile = previous

    def call(self, payload=CANARY, stream=None, command=None, argv=(), uid=0):
        stream = io.BytesIO(payload) if stream is None else stream
        output = io.StringIO()
        original_mask = os.umask(0o077)
        try:
            with mock.patch.object(subject.sys, 'argv', ['receiver', self.profile.name] + list(argv)), \
                    mock.patch.object(subject.sys, 'stdin', types.SimpleNamespace(buffer=stream)), \
                    mock.patch.object(subject.os, 'geteuid', return_value=uid), \
                    mock.patch.dict(subject.os.environ, {'SSH_ORIGINAL_COMMAND': self.profile.command if command is None else command}, clear=True), \
                    mock.patch.object(subject, 'load_profiles', return_value=types.SimpleNamespace(lookup=lambda name: self.profile if name == self.profile.name else self.profiles.lookup(name))), \
                    mock.patch.object(subject, 'receive', side_effect=lambda source, state, profile: subject.receive_into(source, self.root, state, profile)) as receiver, \
                    contextlib.redirect_stdout(output):
                code = subject.main()
        finally:
            os.umask(original_mask)
        public = output.getvalue()
        self.assertLessEqual(len(public.encode()), 1024)
        for forbidden in (CANARY.decode(), str(self.base), '/var/backups/', 'Traceback'):
            self.assertNotIn(forbidden, public)
        answer = json.loads(public)
        self.assertEqual(set(answer), {'status', 'bytes', 'sha256'})
        self.assertIs(type(answer['bytes']), int)
        self.assertGreaterEqual(answer['bytes'], 0)
        if code:
            self.assertEqual(code, 2)
            self.assertIsNone(answer['sha256'])
        return answer, code, receiver

    def failed(self, expected, **kwargs):
        answer, code, _ = self.call(**kwargs)
        self.assertEqual(code, 2)
        self.assertEqual(answer['status'], expected)
        return answer

    def pending(self):
        return self.folder / subject.DESTINATION

    def partial(self):
        return self.folder / subject.PARTIAL

    def test_receives_fsyncs_rereads_and_publishes_only_unverified_ciphertext(self):
        actual_fsync = os.fsync
        with mock.patch.object(subject.os, 'fsync', wraps=actual_fsync) as sync:
            answer, code, _ = self.call()
        self.assertEqual(code, 0)
        self.assertEqual(answer, {'status': 'received_unverified', 'bytes': len(CANARY),
                                  'sha256': hashlib.sha256(CANARY).hexdigest()})
        self.assertEqual(self.pending().read_bytes(), CANARY)
        self.assertEqual(stat.S_IMODE(self.pending().stat().st_mode), 0o600)
        self.assertEqual(self.pending().stat().st_nlink, 1)
        self.assertFalse(self.partial().exists())
        self.assertGreaterEqual(sync.call_count, 4)

    def test_all_invalid_commands_are_rejected_without_reading_or_creating_a_file(self):
        for command in ('', 'receive', self.profile.command + ' ', self.profile.command + '\n', CANARY.decode()):
            with self.subTest(command=command):
                answer, code, receiver = self.call(command=command)
                self.assertEqual((code, answer['status']), (2, 'command_refused'))
                receiver.assert_not_called()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_arbitrary_arguments_and_nonroot_are_rejected_before_receiver(self):
        for kwargs, status in (({'argv': ['--path', CANARY.decode()]}, 'profile_refused'),
                               ({'uid': 501}, 'root_required')):
            answer, code, receiver = self.call(**kwargs)
            self.assertEqual((code, answer['status']), (2, status))
            receiver.assert_not_called()

    def test_each_parent_symlink_is_refused_without_following(self):
        for index in range(len(self.parents)):
            target = self.base.joinpath(*self.parents[:index + 1])
            original = target.with_name(target.name + '-original')
            target.rename(original)
            target.symlink_to(original, target_is_directory=True)
            try:
                self.failed('namespace_unsafe')
            finally:
                target.unlink()
                original.rename(target)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_private_namespace_must_be_0700(self):
        for target in (self.folder, self.folder.parent):
            target.chmod(0o750)
            try:
                self.failed('namespace_unsafe')
            finally:
                target.chmod(0o700)

    def test_group_writable_ancestor_is_refused(self):
        target = self.base / 'var'
        target.chmod(0o775)
        self.failed('namespace_unsafe')

    def test_wrong_owner_and_group_are_refused(self):
        for name in ('OWNER_UID', 'OWNER_GID'):
            with mock.patch.object(subject, name, 987654):
                self.failed('namespace_unsafe')

    def test_existing_pending_is_never_opened_or_overwritten(self):
        self.pending().write_bytes(b'earlier-ciphertext')
        self.pending().chmod(0o600)
        self.failed('destination_exists')
        self.assertEqual(self.pending().read_bytes(), b'earlier-ciphertext')
        self.assertFalse(self.partial().exists())

    def test_pending_symlink_is_not_followed(self):
        victim = self.base / 'unrelated'
        victim.write_bytes(b'untouched')
        self.pending().symlink_to(victim)
        self.failed('destination_exists')
        self.assertEqual(victim.read_bytes(), b'untouched')

    def test_previous_partial_is_preserved_and_refuses_retry(self):
        self.partial().write_bytes(b'earlier-partial')
        self.failed('partial_exists')
        self.assertEqual(self.partial().read_bytes(), b'earlier-partial')
        self.assertFalse(self.pending().exists())

    def test_partial_symlink_is_not_opened(self):
        victim = self.base / 'unrelated'
        victim.write_bytes(b'untouched')
        self.partial().symlink_to(victim)
        self.failed('partial_exists')
        self.assertEqual(victim.read_bytes(), b'untouched')

    def test_lock_symlink_wrong_permissions_and_hardlink_are_refused(self):
        lock = self.folder / subject.LOCK
        victim = self.base / 'unrelated'
        victim.write_bytes(b'untouched')
        victim.chmod(0o600)
        lock.symlink_to(victim)
        self.failed('lock_unsafe')
        lock.unlink()
        lock.write_bytes(b'')
        lock.chmod(0o644)
        self.failed('lock_unsafe')
        lock.unlink()
        os.link(victim, lock)
        self.failed('lock_unsafe')
        self.assertEqual(victim.read_bytes(), b'untouched')

    def test_busy_lock_returns_immediately_without_creating_partial(self):
        fd = os.open(self.folder / subject.LOCK, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.failed('busy')
        finally:
            os.close(fd)
        self.assertFalse(self.partial().exists())

    def test_fresh_capacity_check_precedes_partial_creation(self):
        space = types.SimpleNamespace(f_bavail=1, f_frsize=4096)
        with mock.patch.object(subject.os, 'fstatvfs', return_value=space):
            self.failed('insufficient_space')
        self.assertFalse(self.partial().exists())

    def test_capacity_lost_midstream_preserves_partial_without_pending(self):
        ample = types.SimpleNamespace(f_bavail=4 * 1024 * 1024, f_frsize=4096)
        empty = types.SimpleNamespace(f_bavail=0, f_frsize=4096)
        with mock.patch.object(subject.os, 'fstatvfs', side_effect=[ample, ample, empty]), \
                mock.patch.object(subject, 'BLOCK_BYTES', 8):
            answer = self.failed('insufficient_space')
        self.assertEqual(answer['bytes'], 8)
        self.assertEqual(self.partial().read_bytes(), CANARY[:8])
        self.assertFalse(self.pending().exists())

    def test_size_limit_preserves_only_bounded_received_prefix(self):
        with self.override(max_cipher_bytes=16), mock.patch.object(subject, 'BLOCK_BYTES', 8):
            answer = self.failed('size_limit', payload=b'x' * 17)
        self.assertEqual(answer['bytes'], 16)
        self.assertEqual(self.partial().read_bytes(), b'x' * 16)
        self.assertFalse(self.pending().exists())

    def test_exact_size_limit_requires_eof_and_can_complete(self):
        with self.override(max_cipher_bytes=16), mock.patch.object(subject, 'BLOCK_BYTES', 8):
            answer, code, _ = self.call(payload=b'x' * 16)
        self.assertEqual((code, answer['bytes']), (0, 16))

    def test_empty_input_preserves_empty_partial_without_pending(self):
        self.failed('empty_stream', payload=b'')
        self.assertEqual(self.partial().stat().st_size, 0)
        self.assertFalse(self.pending().exists())

    def test_interrupted_stream_preserves_received_prefix_and_sanitizes_exception(self):
        class Broken(io.BytesIO):
            def read(self, count):
                if self.tell():
                    raise OSError(CANARY.decode())
                return super().read(min(count, 8))
        answer = self.failed('receive_failed', stream=Broken(CANARY))
        self.assertEqual(answer['bytes'], 8)
        self.assertEqual(self.partial().read_bytes(), CANARY[:8])
        self.assertFalse(self.pending().exists())

    def test_partial_write_and_zero_progress_are_not_reported_successful(self):
        actual_write = os.write
        writes = 0
        def write(fd, block):
            nonlocal writes
            writes += 1
            return actual_write(fd, block[:4]) if writes == 1 else 0
        with mock.patch.object(subject.os, 'write', side_effect=write):
            answer = self.failed('write_failed')
        self.assertEqual(answer['bytes'], 4)
        self.assertEqual(self.partial().read_bytes(), CANARY[:4])

    def test_real_absolute_deadline_interrupts_blocking_read_and_preserves_partial(self):
        class Slow(io.BytesIO):
            def read(self, count):
                time.sleep(5)
                return super().read(count)
        began = time.monotonic()
        with self.override(receiver_timeout_seconds=0.02):
            self.failed('deadline_exceeded', stream=Slow(CANARY))
        self.assertLess(time.monotonic() - began, 1)
        self.assertTrue(self.partial().exists())
        self.assertFalse(self.pending().exists())

    def test_ciphertext_fsync_failure_preserves_partial_without_publishing(self):
        actual_sync = os.fsync
        def sync(fd):
            if stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError(CANARY.decode())
            return actual_sync(fd)
        with mock.patch.object(subject.os, 'fsync', side_effect=sync):
            self.failed('receive_failed')
        self.assertEqual(self.partial().read_bytes(), CANARY)
        self.assertFalse(self.pending().exists())

    def test_failure_after_link_preserves_both_unverified_aliases(self):
        actual_sync = os.fsync
        def sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode) and self.pending().exists():
                raise OSError(CANARY.decode())
            return actual_sync(fd)
        with mock.patch.object(subject.os, 'fsync', side_effect=sync):
            self.failed('receive_failed')
        self.assertEqual(self.partial().read_bytes(), CANARY)
        self.assertEqual(self.pending().read_bytes(), CANARY)
        self.assertEqual(self.pending().stat().st_nlink, 2)

    def test_permission_failure_is_sanitized_without_creating_partial(self):
        actual_stat = os.stat
        def denied(name, *args, **kwargs):
            if name == self.parents[-1]:
                raise PermissionError(CANARY.decode())
            return actual_stat(name, *args, **kwargs)
        with mock.patch.object(subject.os, 'stat', side_effect=denied):
            self.failed('receive_failed')
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_changed_partial_permissions_are_refused(self):
        partial = self.partial()
        class Replacing(io.BytesIO):
            def read(self, count):
                partial.chmod(0o644)
                return super().read(count)
        self.failed('partial_changed', stream=Replacing(CANARY))
        self.assertFalse(self.pending().exists())

    def test_all_acquired_descriptors_close_after_interrupted_transfer(self):
        actual_open, actual_close = os.open, os.close
        opened, closed = [], []
        def opening(*args, **kwargs):
            fd = actual_open(*args, **kwargs)
            opened.append(fd)
            return fd
        def closing(fd):
            closed.append(fd)
            actual_close(fd)
        class Broken(io.BytesIO):
            def read(self, count):
                raise OSError(CANARY.decode())
        with mock.patch.object(subject.os, 'open', side_effect=opening), \
                mock.patch.object(subject.os, 'close', side_effect=closing):
            self.failed('receive_failed', stream=Broken(CANARY))
        self.assertEqual(sorted(opened), sorted(closed))
        self.assertNotIn(self.root, closed)

    def test_reread_digest_mismatch_never_publishes(self):
        actual_read = os.read
        def corrupt(fd, count):
            block = actual_read(fd, count)
            return b'!' * len(block) if block else block
        with mock.patch.object(subject.os, 'read', side_effect=corrupt):
            self.failed('reread_mismatch')
        self.assertEqual(self.partial().read_bytes(), CANARY)
        self.assertFalse(self.pending().exists())

    def test_parent_path_replacement_after_pin_is_refused(self):
        folder = self.folder
        class Replacing(io.BytesIO):
            def read(self, count):
                folder.rename(folder.with_name('detached-original'))
                folder.mkdir(mode=0o700)
                return super().read(count)
        self.failed('namespace_changed', stream=Replacing(CANARY))
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertTrue((self.folder.with_name('detached-original') / subject.PARTIAL).exists())

    def test_partial_name_replacement_is_refused_without_touching_replacement(self):
        partial = self.partial()
        class Replacing(io.BytesIO):
            def read(self, count):
                partial.rename(partial.with_name('detached-original'))
                partial.write_bytes(b'replacement-must-stay')
                partial.chmod(0o600)
                return super().read(count)
        self.failed('partial_changed', stream=Replacing(CANARY))
        self.assertEqual(self.partial().read_bytes(), b'replacement-must-stay')
        self.assertFalse(self.pending().exists())

    def test_destination_created_during_publication_is_never_overwritten(self):
        actual_link = os.link
        def publish(*args, **kwargs):
            self.pending().write_bytes(b'other-completed-file')
            return actual_link(*args, **kwargs)
        with mock.patch.object(subject.os, 'link', side_effect=publish):
            self.failed('destination_exists')
        self.assertEqual(self.pending().read_bytes(), b'other-completed-file')
        self.assertEqual(self.partial().read_bytes(), CANARY)

    def test_parent_changed_between_stat_and_open_is_refused(self):
        actual_open = os.open
        def opened(name, flags, *args, **kwargs):
            if name == self.parents[-1]:
                self.folder.rename(self.folder.with_name('detached-original'))
                self.folder.mkdir(mode=0o700)
            return actual_open(name, flags, *args, **kwargs)
        with mock.patch.object(subject.os, 'open', side_effect=opened):
            self.failed('namespace_changed')
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_no_other_files_paths_or_commands_are_accessed(self):
        actual_open, actual_stat = os.open, os.stat
        allowed = set(self.parents) | {subject.LOCK, subject.PARTIAL, subject.DESTINATION}
        def opened(name, flags, *args, **kwargs):
            self.assertIn(name, set(self.parents) | {subject.LOCK, subject.PARTIAL})
            self.assertIsInstance(kwargs.get('dir_fd'), int)
            return actual_open(name, flags, *args, **kwargs)
        def stated(name, *args, **kwargs):
            self.assertIn(name, allowed)
            self.assertFalse(kwargs.get('follow_symlinks', True))
            return actual_stat(name, *args, **kwargs)
        with mock.patch.object(subject.os, 'open', side_effect=opened), \
                mock.patch.object(subject.os, 'stat', side_effect=stated), \
                mock.patch.object(subject.os, 'listdir', side_effect=AssertionError(CANARY)), \
                mock.patch.object(subject.os, 'scandir', side_effect=AssertionError(CANARY)), \
                mock.patch('builtins.open', side_effect=AssertionError(CANARY)):
            _, code, _ = self.call()
        self.assertEqual(code, 0)

    def test_each_profile_receives_only_in_its_own_namespace_without_global_mutation(self):
        original = self.profile
        for name in self.profiles.ORDER:
            self.profile = self.profiles.lookup(name)
            self.parents = ('var', 'backups', 'metainc-app-retirement', self.profile.session)
            self.folder = self.base.joinpath(*self.parents)
            self.folder.mkdir(mode=0o700, exist_ok=True)
            payload = ('SYNTHETIC-' + name).encode()
            result, code, _ = self.call(payload=payload)
            self.assertEqual(code, 0)
            self.assertEqual(self.pending().read_bytes(), payload)
            self.assertEqual(result['bytes'], len(payload))
        self.assertEqual(original.name, 'autobid-web')
        for name in self.profiles.ORDER:
            path = self.base.joinpath('var', 'backups', 'metainc-app-retirement', self.profiles.lookup(name).session, subject.DESTINATION)
            self.assertEqual(path.read_bytes(), ('SYNTHETIC-' + name).encode())

    def test_another_profiles_ssh_command_cannot_write_selected_namespace(self):
        for name in self.profiles.ORDER[1:]:
            self.failed('command_refused', command=self.profiles.lookup(name).command)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_profile_cap_failure_does_not_change_other_profile_limits(self):
        before = {name: self.profiles.lookup(name).max_cipher_bytes for name in self.profiles.ORDER}
        with self.override(max_cipher_bytes=1):
            self.failed('size_limit')
        self.assertEqual({name: self.profiles.lookup(name).max_cipher_bytes for name in self.profiles.ORDER}, before)


if __name__ == '__main__':
    unittest.main()
