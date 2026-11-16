"""One synthetic namespace only: no SSH, live key, Docker, or backup access."""
import contextlib
import fcntl
import gc
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import time
import types
import unittest
import warnings
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    'naver_archive_receiver', Path(__file__).resolve().parents[1] / 'naver_archive_receiver.py')
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
CANARY = b'PRIVATE_SYNTHETIC_PAYLOAD_NOT_A_REAL_KEY'


def framed(payload, chunk=None, terminal=True):
    chunk = min(subject.BLOCK_BYTES, subject.FRAME_BYTES) if chunk is None else chunk
    wire = bytearray(subject.WIRE_MAGIC)
    for start in range(0, len(payload), chunk):
        block = payload[start:start + chunk]
        wire.extend(struct.pack('>I', len(block)))
        wire.extend(block)
    if terminal:
        wire.extend(struct.pack('>IQ', 0, len(payload)))
        wire.extend(hashlib.sha256(payload).digest())
    return bytes(wire)


@contextlib.contextmanager
def record_resource_warnings():
    """Separate delayed fixture finalizers from the receiver's stderr protocol.

    Other warnings and direct stderr writes remain visible and must still fail
    strict JSON checks. No production receiver warning behavior is changed.
    """
    recorded = []
    with warnings.catch_warnings():
        original_showwarning = warnings.showwarning
        warnings.simplefilter('always', ResourceWarning)
        def showwarning(message, category, *args, **kwargs):
            if issubclass(category, ResourceWarning):
                recorded.append((str(message), category))
            else:
                original_showwarning(message, category, *args, **kwargs)
        warnings.showwarning = showwarning
        yield recorded


class ArchiveReceiverTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='naver-archive-receiver-fixture-')
        self.base = Path(self.temp.name).resolve()
        self.folder = self.base.joinpath(*subject.PARENTS)
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

    def call(self, payload=CANARY, stream=None, command=None, argv=(), uid=0):
        stream = io.BytesIO(framed(payload)) if stream is None else stream
        output = io.StringIO()
        original_mask = os.umask(0o077)
        try:
            with mock.patch.object(subject.sys, 'argv', ['receiver'] + list(argv)), \
                    mock.patch.object(subject.sys, 'stdin', types.SimpleNamespace(buffer=stream)), \
                    mock.patch.object(subject.os, 'geteuid', return_value=uid), \
                    mock.patch.dict(subject.os.environ, {'SSH_ORIGINAL_COMMAND': subject.COMMAND if command is None else command}, clear=True), \
                    mock.patch.object(subject, 'receive', side_effect=lambda source, state: subject.receive_into(source, self.root, state)) as receiver, \
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

    def test_raw_ciphertext_and_normal_eof_prefix_cannot_publish(self):
        for wire in (CANARY, framed(CANARY, terminal=False)):
            with self.subTest(framed=wire.startswith(subject.WIRE_MAGIC)):
                answer, code, _ = self.call(stream=io.BytesIO(wire))
                self.assertEqual(code, 2)
                self.assertIn(answer['status'], ('frame_invalid', 'frame_truncated'))
                self.assertFalse(self.pending().exists())
                self.assertTrue(self.partial().exists())
                self.partial().unlink()

    def test_every_truncated_header_body_and_terminal_is_incomplete(self):
        wire = framed(CANARY)
        for length in range(len(wire)):
            with self.subTest(length=length):
                self.failed('frame_truncated', stream=io.BytesIO(wire[:length]))
                self.assertFalse(self.pending().exists())
                self.assertTrue(self.partial().exists())
                self.partial().unlink()

    def test_fragmented_reads_accept_one_byte_at_a_time_including_terminal(self):
        class Fragmented(io.BytesIO):
            def read(self, count):
                return super().read(min(count, 1))
        answer, code, _ = self.call(stream=Fragmented(framed(CANARY, chunk=7)))
        self.assertEqual((code, answer['bytes']), (0, len(CANARY)))
        self.assertEqual(self.pending().read_bytes(), CANARY)

    def test_frame_count_and_length_are_bounded_before_payload_read(self):
        oversized = subject.WIRE_MAGIC + struct.pack('>I', subject.FRAME_BYTES + 1)
        self.failed('frame_limit', stream=io.BytesIO(oversized))
        self.assertEqual(self.partial().read_bytes(), b'')
        self.partial().unlink()
        with mock.patch.object(subject, 'MAX_FRAMES', 1):
            self.failed('frame_limit', stream=io.BytesIO(framed(CANARY, chunk=8)))
        self.assertEqual(self.partial().read_bytes(), CANARY[:8])
        self.assertFalse(self.pending().exists())

    def test_terminal_size_and_digest_must_match_all_ciphertext(self):
        good = framed(CANARY)
        bad_count = good[:-40] + struct.pack('>Q', len(CANARY) + 1) + good[-32:]
        bad_hash = good[:-32] + bytes(32)
        for wire in (bad_count, bad_hash):
            with self.subTest(count=wire == bad_count):
                self.failed('frame_mismatch', stream=io.BytesIO(wire))
                self.assertEqual(self.partial().read_bytes(), CANARY)
                self.assertFalse(self.pending().exists())
                self.partial().unlink()

    def test_terminal_followed_by_data_or_another_terminal_is_refused(self):
        good = framed(CANARY)
        for suffix in (b'x', struct.pack('>IQ', 0, len(CANARY)) + hashlib.sha256(CANARY).digest()):
            with self.subTest(length=len(suffix)):
                self.failed('frame_trailing_data', stream=io.BytesIO(good + suffix))
                self.assertEqual(self.partial().read_bytes(), CANARY)
                self.assertFalse(self.pending().exists())
                self.partial().unlink()

    def test_nonbytes_or_overlong_read_is_invalid_and_preserved(self):
        for answer in ('not bytes', b'x' * (len(subject.WIRE_MAGIC) + 1)):
            class Invalid:
                def read(self, count):
                    return answer
            self.failed('frame_invalid', stream=Invalid())
            self.assertEqual(self.partial().read_bytes(), b'')
            self.assertFalse(self.pending().exists())
            self.partial().unlink()

    def test_terminal_requires_eof_before_publication_and_has_deadline(self):
        wire = framed(CANARY)
        class HeldOpen(io.BytesIO):
            def read(self, count):
                if self.tell() == len(wire):
                    time.sleep(5)
                return super().read(count)
        with mock.patch.object(subject, 'TIMEOUT', .02):
            self.failed('deadline_exceeded', stream=HeldOpen(wire))
        self.assertEqual(self.partial().read_bytes(), CANARY)
        self.assertFalse(self.pending().exists())

    def test_archive_policy_is_fixed_and_image_command_is_refused(self):
        self.assertEqual(subject.PARENTS, ('var', 'backups', 'metainc-app-retirement',
                                           'naver-archives-20261106-v1'))
        self.assertEqual(subject.COMMAND, 'receive-naver-archives-20261106-v1')
        self.assertEqual(subject.DESTINATION, 'archives.gpg')
        self.assertEqual(subject.PARTIAL, 'archives.gpg.partial')
        self.assertEqual(subject.MAX_CIPHER, 12 * 1024 ** 3)
        self.assertEqual(subject.MIN_FREE, 15 * 1024 ** 3)
        self.assertEqual(subject.TIMEOUT, 3600)
        self.failed('command_refused', command='receive-ad-image-20261102-v1')
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_actual_ciphertext_cap_rejects_one_extra_byte(self):
        with mock.patch.object(subject, 'MAX_CIPHER', 1024 * 1024):
            answer = self.failed('size_limit', payload=b'x' * (1024 * 1024 + 1))
        self.assertEqual(answer['bytes'], 1024 * 1024)
        self.assertEqual(self.partial().stat().st_size, 1024 * 1024)
        self.assertFalse(self.pending().exists())

    def test_existing_image_namespace_is_untouched(self):
        other = self.folder.parent / 'ad-image-20261102-v1'
        other.mkdir(mode=0o700)
        old = other / 'image.gpg.pending'
        old.write_bytes(b'EARLIER_IMAGE_CIPHERTEXT')
        old.chmod(0o600)
        before = old.stat()
        _, code, _ = self.call()
        after = old.stat()
        self.assertEqual(code, 0)
        self.assertEqual(old.read_bytes(), b'EARLIER_IMAGE_CIPHERTEXT')
        self.assertEqual((before.st_ino, before.st_mtime_ns, before.st_size),
                         (after.st_ino, after.st_mtime_ns, after.st_size))
        self.assertEqual(list(other.iterdir()), [old])

    def test_all_invalid_commands_are_rejected_without_reading_or_creating_a_file(self):
        for command in ('', 'receive', subject.COMMAND + ' ', subject.COMMAND + '\n', CANARY.decode()):
            with self.subTest(command=command):
                answer, code, receiver = self.call(command=command)
                self.assertEqual((code, answer['status']), (2, 'command_refused'))
                receiver.assert_not_called()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_arbitrary_arguments_and_nonroot_are_rejected_before_receiver(self):
        for kwargs, status in (({'argv': ['--path', CANARY.decode()]}, 'arguments_refused'),
                               ({'uid': 501}, 'root_required')):
            answer, code, receiver = self.call(**kwargs)
            self.assertEqual((code, answer['status']), (2, status))
            receiver.assert_not_called()

    def test_each_parent_symlink_is_refused_without_following(self):
        for index in range(len(subject.PARENTS)):
            target = self.base.joinpath(*subject.PARENTS[:index + 1])
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

    def test_final_filesystem_allocation_must_leave_full_three_gib_reserve(self):
        ample = types.SimpleNamespace(f_bavail=subject.MIN_FREE + 4096, f_frsize=1)
        low = types.SimpleNamespace(f_bavail=subject.RESERVE_BYTES - 1, f_frsize=1)
        with mock.patch.object(subject.os, 'fstatvfs', side_effect=[ample, ample, low]):
            answer = self.failed('insufficient_space')
        self.assertEqual(answer['bytes'], len(CANARY))
        self.assertEqual(self.partial().read_bytes(), CANARY)
        self.assertFalse(self.pending().exists())

    def test_size_limit_preserves_only_bounded_received_prefix(self):
        with mock.patch.object(subject, 'MAX_CIPHER', 16), mock.patch.object(subject, 'BLOCK_BYTES', 8):
            answer = self.failed('size_limit', payload=b'x' * 17)
        self.assertEqual(answer['bytes'], 16)
        self.assertEqual(self.partial().read_bytes(), b'x' * 16)
        self.assertFalse(self.pending().exists())

    def test_exact_size_limit_requires_eof_and_can_complete(self):
        with mock.patch.object(subject, 'MAX_CIPHER', 16), mock.patch.object(subject, 'BLOCK_BYTES', 8):
            answer, code, _ = self.call(payload=b'x' * 16)
        self.assertEqual((code, answer['bytes']), (0, 16))

    def test_empty_input_preserves_empty_partial_without_pending(self):
        self.failed('empty_stream', payload=b'')
        self.assertEqual(self.partial().stat().st_size, 0)
        self.assertFalse(self.pending().exists())

    def test_interrupted_stream_preserves_received_prefix_and_sanitizes_exception(self):
        class Broken(io.BytesIO):
            def read(self, count):
                if self.tell() >= len(subject.WIRE_MAGIC) + 4 + 8:
                    raise OSError(CANARY.decode())
                return super().read(count)
        answer = self.failed('receive_failed', stream=Broken(framed(CANARY, chunk=8)))
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
        with mock.patch.object(subject, 'TIMEOUT', 0.02):
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
            if name == subject.PARENTS[-1]:
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
        self.failed('partial_changed', stream=Replacing(framed(CANARY)))
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
                if not self.tell():
                    folder.rename(folder.with_name('detached-original'))
                    folder.mkdir(mode=0o700)
                return super().read(count)
        self.failed('namespace_changed', stream=Replacing(framed(CANARY)))
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertTrue((self.folder.with_name('detached-original') / subject.PARTIAL).exists())

    def test_partial_name_replacement_is_refused_without_touching_replacement(self):
        partial = self.partial()
        class Replacing(io.BytesIO):
            def read(self, count):
                if not self.tell():
                    partial.rename(partial.with_name('detached-original'))
                    partial.write_bytes(b'replacement-must-stay')
                    partial.chmod(0o600)
                return super().read(count)
        self.failed('partial_changed', stream=Replacing(framed(CANARY)))
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
            if name == subject.PARENTS[-1]:
                self.folder.rename(self.folder.with_name('detached-original'))
                self.folder.mkdir(mode=0o700)
            return actual_open(name, flags, *args, **kwargs)
        with mock.patch.object(subject.os, 'open', side_effect=opened):
            self.failed('namespace_changed')
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_no_other_files_paths_or_commands_are_accessed(self):
        actual_open, actual_stat = os.open, os.stat
        allowed = set(subject.PARENTS) | {subject.LOCK, subject.PARTIAL, subject.DESTINATION}
        def opened(name, flags, *args, **kwargs):
            self.assertIn(name, set(subject.PARENTS) | {subject.LOCK, subject.PARTIAL})
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


    def fetched(self, output=None, command=None, argv=(), uid=0):
        output = io.BytesIO() if output is None else output
        errors = io.StringIO()
        with mock.patch.object(subject.sys, 'argv', ['receiver'] + list(argv)), \
                mock.patch.object(subject.sys, 'stdout', types.SimpleNamespace(buffer=output)), \
                mock.patch.object(subject.sys, 'stderr', errors), \
                mock.patch.object(subject.os, 'geteuid', return_value=uid), \
                mock.patch.dict(subject.os.environ, {'SSH_ORIGINAL_COMMAND': subject.FETCH_COMMAND if command is None else command}, clear=True), \
                mock.patch.object(subject, 'fetch', side_effect=lambda sink, state: subject.fetch_from(sink, self.root, state)) as fetcher, \
                record_resource_warnings() as resource_warnings:
            code = subject.main()
        self.resource_warnings = resource_warnings
        public = errors.getvalue()
        self.assertLessEqual(len(public.encode()), 1024)
        for forbidden in (CANARY.decode(), str(self.base), '/var/backups/', 'Traceback'):
            self.assertNotIn(forbidden, public)
        if code:
            self.assertEqual(code, 2)
            self.assertTrue(public.startswith('{'), 'Unexpected synthetic receiver stderr: ' + repr(public))
            try:
                answer = json.loads(public)
            except json.JSONDecodeError as error:
                self.fail('Invalid synthetic receiver stderr: ' + repr(public) + '; ' + str(error))
            self.assertEqual(public, json.dumps(answer, separators=(',', ':')) + '\n')
            self.assertEqual(set(answer), {'status', 'bytes', 'sha256'})
            self.assertIsNone(answer['sha256'])
        else:
            self.assertEqual(public, '')
            answer = None
        return code, output.getvalue(), answer, fetcher

    def completed(self, payload=CANARY):
        self.pending().write_bytes(payload)
        self.pending().chmod(0o600)

    def test_receive_then_fetch_roundtrip_binary_only(self):
        payload = bytes(range(256)) * 1000
        answer, code, _ = self.call(payload=payload)
        self.assertEqual(code, 0)
        before = self.pending().stat()
        fetched_code, actual, errors, _ = self.fetched()
        self.assertEqual(fetched_code, 0)
        self.assertEqual(actual, payload)
        self.assertEqual(hashlib.sha256(actual).hexdigest(), answer['sha256'])
        after = self.pending().stat()
        self.assertEqual(subject.content_identity(before), subject.content_identity(after))
        self.assertIsNone(errors)
        self.assertEqual(subject.FETCH_COMMAND, 'fetch-naver-archives-20261106-v1')

    def test_fetch_requires_fixed_command_no_args_and_root(self):
        self.completed()
        for kwargs, status in (({'argv': ['anything']}, 'arguments_refused'), ({'uid': 501}, 'root_required')):
            with self.subTest(kwargs=kwargs):
                code, data, error, fetcher = self.fetched(**kwargs)
                self.assertEqual((code, data, error['status']), (2, b'', status))
                fetcher.assert_not_called()
        for command in (subject.FETCH_COMMAND + ' ', subject.FETCH_COMMAND + ' arg', subject.FETCH_COMMAND + '\n'):
            self.failed('command_refused', command=command)

    def test_fetch_missing_destination_and_retained_partial_are_refused(self):
        code, data, error, _ = self.fetched()
        self.assertEqual((code, data, error['status']), (2, b'', 'destination_missing'))
        self.completed()
        self.partial().write_bytes(b'partial')
        code, data, error, _ = self.fetched()
        self.assertEqual((code, data, error['status']), (2, b'', 'partial_exists'))
        self.assertEqual(self.partial().read_bytes(), b'partial')
        self.assertEqual(self.pending().read_bytes(), CANARY)

    def test_fetch_refuses_nonregular_symlink_hardlink_permissions_empty_and_oversize(self):
        self.completed()
        victim = self.base / 'victim'
        self.pending().rename(victim)
        arrangements = (
            lambda: self.pending().symlink_to(victim),
            lambda: os.link(victim, self.pending()),
            lambda: self.pending().mkdir(mode=0o600),
            lambda: os.mkfifo(self.pending(), 0o600),
            lambda: self.completed(b''),
            lambda: self.completed(b'x' * (len(CANARY) + 1)),
        )
        with mock.patch.object(subject, 'MAX_CIPHER', len(CANARY)):
            for arrange in arrangements:
                arrange()
                try:
                    code, data, error, _ = self.fetched()
                    self.assertEqual((code, data, error['status']), (2, b'', 'destination_unsafe'))
                finally:
                    if self.pending().is_dir():
                        self.pending().rmdir()
                    else:
                        self.pending().unlink()
        self.completed()
        self.pending().chmod(0o640)
        code, data, error, _ = self.fetched()
        self.assertEqual((code, data, error['status']), (2, b'', 'destination_unsafe'))
        self.assertEqual(victim.read_bytes(), CANARY)

    def test_fetch_refuses_unsafe_namespace_and_lock(self):
        self.completed()
        self.folder.chmod(0o750)
        code, data, error, _ = self.fetched()
        self.assertEqual((code, data, error['status']), (2, b'', 'namespace_unsafe'))
        self.folder.chmod(0o700)
        fd = os.open(self.folder / subject.LOCK, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code, data, error, _ = self.fetched()
            self.assertEqual((code, data, error['status']), (2, b'', 'busy'))
        finally:
            os.close(fd)

    def test_fetch_changed_path_between_stat_and_open_is_refused(self):
        self.completed()
        actual_open = os.open
        def changed(name, flags, *args, **kwargs):
            if name == subject.DESTINATION:
                self.pending().rename(self.folder / 'detached')
                self.completed(b'replacement')
            return actual_open(name, flags, *args, **kwargs)
        with mock.patch.object(subject.os, 'open', side_effect=changed):
            code, data, error, _ = self.fetched()
        self.assertEqual((code, data, error['status']), (2, b'', 'destination_changed'))
        self.assertEqual(self.pending().read_bytes(), b'replacement')

    def test_fetch_reread_digest_mismatch_is_nonzero_even_after_data_output(self):
        self.completed()
        actual_read = os.read
        passes = 0
        def changed(fd, count):
            nonlocal passes
            block = actual_read(fd, count)
            if not block:
                passes += 1
            return b'!' * len(block) if passes >= 1 and block else block
        with mock.patch.object(subject.os, 'read', side_effect=changed):
            code, data, error, _ = self.fetched()
        self.assertEqual(code, 2)
        self.assertEqual(data, b'!' * len(CANARY))
        self.assertEqual(error['status'], 'fetch_reread_mismatch')
        self.assertEqual(error['bytes'], len(data))
        self.assertEqual(self.pending().read_bytes(), CANARY)

    def test_fetch_same_inode_modified_midstream_returns_nonzero_and_preserves_source(self):
        self.completed()
        target = self.pending()
        class Changing(io.BytesIO):
            def write(self, data):
                count = super().write(data)
                target.write_bytes(b'!' * len(CANARY))
                target.chmod(0o600)
                return count
        code, data, error, _ = self.fetched(output=Changing())
        self.assertEqual(code, 2)
        self.assertEqual(data, CANARY)
        self.assertEqual(error['status'], 'destination_changed')
        self.assertEqual(target.read_bytes(), b'!' * len(CANARY))

    def test_fetch_parent_changed_after_stream_returns_nonzero(self):
        self.completed()
        folder = self.folder
        class Changing(io.BytesIO):
            def flush(self):
                folder.rename(folder.with_name('detached-original'))
                folder.mkdir(mode=0o700)
        code, data, error, _ = self.fetched(output=Changing())
        self.assertEqual(code, 2)
        self.assertEqual(data, CANARY)
        self.assertEqual(error['status'], 'namespace_changed')
        self.assertEqual((folder.with_name('detached-original') / subject.DESTINATION).read_bytes(), CANARY)

    def test_fetch_partial_created_after_pin_returns_nonzero(self):
        self.completed()
        partial = self.partial()
        class Changing(io.BytesIO):
            def write(self, data):
                result = super().write(data)
                partial.write_bytes(b'new-partial')
                return result
        code, data, error, _ = self.fetched(output=Changing())
        self.assertEqual(code, 2)
        self.assertEqual(error['status'], 'partial_exists')
        self.assertEqual(partial.read_bytes(), b'new-partial')

    def test_fetch_short_writes_can_finish_and_zero_progress_refuses(self):
        self.completed()
        class Short(io.BytesIO):
            def write(self, data):
                return super().write(data[:3])
        code, data, error, _ = self.fetched(output=Short())
        self.assertEqual((code, data, error), (0, CANARY, None))
        for result in (0, None, True, len(CANARY) + 1):
            class Broken(io.BytesIO):
                def write(self, data):
                    return result
            code, data, error, _ = self.fetched(output=Broken())
            self.assertEqual((code, data, error['status']), (2, b'', 'fetch_write_failed'))

    def test_fetch_output_exception_is_sanitized_and_source_remains(self):
        self.completed()
        class Broken(io.BytesIO):
            def write(self, data):
                raise BrokenPipeError(CANARY.decode())
        code, data, error, _ = self.fetched(output=Broken())
        self.assertEqual((code, data, error['status']), (2, b'', 'fetch_failed'))
        self.assertEqual(self.pending().read_bytes(), CANARY)

    def test_fetch_deadline_closes_all_fds_and_has_no_json_on_stdout(self):
        self.completed()
        actual_open, actual_close = os.open, os.close
        opened, closed = [], []
        def opening(*args, **kwargs):
            fd = actual_open(*args, **kwargs)
            opened.append(fd)
            return fd
        def closing(fd):
            closed.append(fd)
            actual_close(fd)
        class Slow(io.BytesIO):
            def write(self, data):
                time.sleep(5)
                return super().write(data)
        with mock.patch.object(subject.os, 'open', side_effect=opening), \
                mock.patch.object(subject.os, 'close', side_effect=closing), \
                mock.patch.object(subject, 'TIMEOUT', .02):
            code, data, error, _ = self.fetched(output=Slow())
        self.assertEqual((code, data, error['status']), (2, b'', 'deadline_exceeded'))
        self.assertEqual(sorted(opened), sorted(closed))
        self.assertNotIn(self.root, closed)
        self.assertEqual(self.pending().read_bytes(), CANARY)

    def test_fetch_read_failure_is_sanitized(self):
        self.completed()
        with mock.patch.object(subject.os, 'read', side_effect=OSError(CANARY.decode())):
            code, data, error, _ = self.fetched()
        self.assertEqual((code, data, error['status']), (2, b'', 'fetch_failed'))

    def test_delayed_external_finalizer_resource_warning_is_recorded_separately(self):
        self.completed()
        message = 'synthetic external fixture finalized during receiver read'
        class ExternalFixture:
            def __del__(self):
                warnings.warn(message, ResourceWarning)
        orphan = ExternalFixture()
        orphan.cycle = orphan
        retained = [orphan]
        del orphan
        def fail_read(*_):
            retained.clear()
            gc.collect()
            raise OSError(CANARY.decode())
        with mock.patch.object(subject.os, 'read', side_effect=fail_read):
            code, data, error, _ = self.fetched()
        self.assertEqual((code, data, error['status']), (2, b'', 'fetch_failed'))
        self.assertIn((message, ResourceWarning), self.resource_warnings)

    def test_other_warnings_and_direct_stderr_remain_strict_failures(self):
        self.completed()
        for mode in ('warning', 'direct'):
            def fail_read(*_):
                if mode == 'warning':
                    warnings.warn('synthetic non-resource warning', UserWarning)
                else:
                    sys.stderr.write('synthetic unexpected product stderr\n')
                raise OSError(CANARY.decode())
            with self.subTest(mode=mode), warnings.catch_warnings():
                warnings.simplefilter('always', UserWarning)
                with mock.patch.object(subject.os, 'read', side_effect=fail_read), \
                        self.assertRaisesRegex(AssertionError, 'Unexpected synthetic receiver stderr'):
                    self.fetched()

    def test_fetch_truncated_read_is_refused_before_output(self):
        self.completed()
        with mock.patch.object(subject.os, 'read', return_value=b''):
            code, data, error, _ = self.fetched()
        self.assertEqual((code, data, error['status']), (2, b'', 'destination_changed'))

    def test_fetch_flush_failure_and_final_file_change_do_not_succeed(self):
        self.completed()
        target = self.pending()
        class Broken(io.BytesIO):
            def flush(self):
                raise OSError(CANARY.decode())
        code, data, error, _ = self.fetched(output=Broken())
        self.assertEqual((code, data, error['status']), (2, CANARY, 'fetch_failed'))
        class Changed(io.BytesIO):
            def flush(self):
                target.chmod(0o644)
        code, data, error, _ = self.fetched(output=Changed())
        self.assertEqual((code, data, error['status']), (2, CANARY, 'destination_changed'))

    def test_fetch_never_uses_plaintext_or_any_other_path(self):
        self.completed()
        actual_open, actual_stat = os.open, os.stat
        allowed = set(subject.PARENTS) | {subject.LOCK, subject.PARTIAL, subject.DESTINATION}
        def opened(name, flags, *args, **kwargs):
            self.assertIn(name, allowed - {subject.PARTIAL})
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
            code, data, error, _ = self.fetched()
        self.assertEqual((code, data, error), (0, CANARY, None))


if __name__ == '__main__':
    unittest.main()
