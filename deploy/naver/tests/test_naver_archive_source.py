"""Real synthetic files only; no server, keys, Docker, SQLite, or crypto attestation."""
import contextlib
import copy
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import stat
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    'naver_archive_source_under_test', Path(__file__).resolve().parents[1] / 'naver_archive_source.py')
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
c = subject.c
CANARY = b'SYNTHETIC_ARCHIVE_BYTES_NOT_A_REAL_DATABASE'


class Output:
    def __init__(self):
        self.buffer = io.BytesIO()

    def write(self, value):
        return self.buffer.write(value.encode())

    def flush(self):
        self.buffer.flush()


class ArchiveSourceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='naver-archive-source-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.parent = self.base.joinpath(*subject.PARENT)
        self.parent.mkdir(parents=True, mode=0o700)
        for folder in (self.base, self.base / 'var', self.base / 'var/backups', self.parent):
            folder.chmod(0o700)
        self.root = os.open(self.base, subject.FLAGS)
        self.addCleanup(os.close, self.root)
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(mock.patch.object(subject, 'OWNER_UID', os.getuid()))
        self.patches.enter_context(mock.patch.object(subject, 'OWNER_GID', os.getgid()))
        self.profile = c.cold.profile_for('8c13-cold-backup-lossless-v1')
        self.cold_parent = self.parent / subject.COLD_PARENT
        self.cold_folder = self.cold_parent / self.profile.archive
        self.cold_folder.mkdir(parents=True, mode=0o700)
        self.cold_parent.chmod(0o700)
        self.interrupted = self.parent / c.INTERRUPTED
        self.interrupted.mkdir(mode=0o700)
        self.make_cold()
        self.raw = CANARY * 173
        self.zipped = gzip.compress(self.raw, compresslevel=1, mtime=0)
        self.interrupted_manifest = {
            'source': c.INTERRUPTED_SOURCE, 'sha256': c.digest(self.raw),
            'bytes': len(self.raw), 'gzip_bytes': len(self.zipped), 'gzip_level': 1,
        }
        for name, value in {
            'snapshot.sqlite.json': c.canonical(self.interrupted_manifest),
            'snapshot.sqlite.gz': self.zipped,
            'packed.zip.broken': b'PK\x03\x04synthetic-incomplete-zip',
        }.items():
            self.put(self.interrupted / name, value)

    @staticmethod
    def put(path, data, mode=0o600):
        path.write_bytes(data)
        path.chmod(mode)

    @staticmethod
    def historical_meta(size=0, mode=0o600):
        return dict(device=1, inode=2, mode=mode, uid=0, gid=0, size=size,
                    links=1, mtime_ns=1, ctime_ns=2, allocated_bytes=((size + 511) // 512) * 512)

    def make_cold(self):
        # Independent fixture for the historical manifest schema, not the writer.
        payloads = {'engine.db': CANARY * 89, 'engine.db-wal': b'wal-fixture\0' * 3}
        compressed = {name: gzip.compress(raw, compresslevel=1, mtime=0) for name, raw in payloads.items()}
        original = json.dumps({name: {'size': len(raw), 'sha256': c.digest(raw)}
                               for name, raw in payloads.items()}, indent=2).encode() + b'\n'
        rows = {name: dict(size=len(raw), sha256=c.digest(raw), gzip_size=len(compressed[name]),
                           gzip_sha256=c.digest(compressed[name]), source=self.historical_meta(len(raw)))
                for name, raw in payloads.items()}
        self.cold_manifest = dict(
            version=1, scope=self.profile.scope, backup=self.profile.backup, archive=self.profile.archive,
            gzip=dict(level=1, mtime=0, zlib='1.2.13', python='3.10.4'),
            source_folder=self.historical_meta(mode=0o700),
            source_manifest=self.historical_meta(len(original)), source_manifest_sha256=c.digest(original),
            files=rows, protected={'containers': [], 'images': []}, reserve_bytes=512 * 1024 ** 2,
            minimum_free_after_bytes=5 * 1024 ** 3, overhead_bytes=1024 * 1024)
        c.cold.validate_archive_plan(self.cold_manifest, self.profile.scope)
        for name, value in {**{n + '.gz': data for n, data in compressed.items()},
                            'source-manifest.json': original,
                            'archive-manifest.json': c.canonical(self.cold_manifest)}.items():
            self.put(self.cold_folder / name, value)

    def make_fixed_bundle_layout(self):
        # These bytes test source membership/identity only. This deliberately
        # does not claim a verified backup_bundle manifest or recovery receipt.
        self.fixed_bundle = self.cold_parent / c.BUNDLE
        self.fixed_bundle.mkdir(mode=0o700)
        for child in ('deployment', 'snapshot'):
            (self.fixed_bundle / child).mkdir(mode=0o700)
        for name in ('archive-manifest.json', 'deployment/archive-manifest.json',
                     'deployment/source-manifest.json', 'deployment/engine.db.gz',
                     'snapshot/archive-manifest.json', 'snapshot/snapshot.sqlite.gz'):
            self.put(self.fixed_bundle / name, b'{}' if name.endswith('.json') else b'fixed-fixture-payload')

    def make_verified_fixed_bundle(self):
        spec = importlib.util.spec_from_file_location(
            'fixed_archive_bundle_fixture', Path(__file__).with_name('test_naver_archive_bundle.py'))
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        _, payloads, raw = fixture.make_fixture(c)
        helper = c.bundle_helper()
        self.patches.enter_context(mock.patch.object(c, 'bundle_helper', return_value=helper))
        self.patches.enter_context(mock.patch.object(helper, 'CANDIDATE_BYTES', len(raw['snapshot'])))
        self.fixed_bundle = self.cold_parent / c.BUNDLE
        self.fixed_bundle.mkdir(mode=0o700)
        for child in ('deployment', 'snapshot'):
            (self.fixed_bundle / child).mkdir(mode=0o700)
        prefix = 'bundle/' + c.BUNDLE + '/'
        for path, data in payloads.items():
            self.assertTrue(path.startswith(prefix))
            self.put(self.fixed_bundle / path[len(prefix):], data)

    def bundle_cleanup_paths(self):
        base = 'bundle/' + c.BUNDLE + '/'
        return ([base + 'deployment/engine.db.gz', base + 'snapshot/snapshot.sqlite.gz']
                + self.cleanup_paths()[:4]
                + [base + 'deployment/archive-manifest.json', base + 'deployment/source-manifest.json',
                   base + 'snapshot/archive-manifest.json']
                + self.cleanup_paths()[4:]
                + [base + 'archive-manifest.json'])

    @contextlib.contextmanager
    def sources(self, exclusive=False):
        with subject.namespace(self.root, exclusive) as (parent, validate):
            with subject.Sources(parent, validate) as sources:
                yield parent, sources

    def plan(self):
        with self.sources() as (_, sources):
            return copy.deepcopy(sources.plan)

    def bundle(self):
        with self.sources() as (_, sources):
            plan = copy.deepcopy(sources.plan)
            data = b''.join(sources.blocks())
        return plan, data

    def snapshot(self):
        folders = [self.cold_folder, self.interrupted]
        if hasattr(self, 'fixed_bundle'):
            folders.append(self.fixed_bundle)
        return {str(path.relative_to(self.parent)): (subject.identity(path.stat()), path.read_bytes())
                for folder in folders for path in folder.rglob('*') if path.is_file()}

    def journal_records(self):
        # A failed append may leave an incomplete final line. Keep prior records.
        raw = (self.parent / subject.JOURNAL).read_bytes()
        return [c.strict_json(line) for line in raw.splitlines(keepends=True) if line.endswith(b'\n')]

    def recovery(self, plan):
        # Operator-trusted fixture only; this does not claim an actual GPG result.
        return dict(version=1, status='recovery_verified', session=c.SESSION,
                    plan_sha256=c.digest(c.canonical(plan)), cipher={'bytes': 123, 'sha256': 'a' * 64},
                    files=c.file_rows(plan), verification='gpg-authenticated-and-inner-gzip-v1')

    def cleanup_paths(self):
        # Independent fixture order: payloads from every group precede metadata.
        cold = 'cold/' + self.profile.archive + '/'
        interrupted = 'interrupted/' + c.INTERRUPTED + '/'
        return [cold + 'engine.db-wal.gz', cold + 'engine.db.gz',
                interrupted + 'snapshot.sqlite.gz', interrupted + 'packed.zip.broken',
                cold + 'archive-manifest.json', cold + 'source-manifest.json',
                interrupted + 'snapshot.sqlite.json']

    def cleanup(self, receipt=None, state=None):
        state = {} if state is None else state
        with self.sources(True) as (parent, sources):
            receipt = self.recovery(sources.plan) if receipt is None else receipt
            subject.cleanup(parent, sources, receipt, c.digest(c.canonical(receipt)), state)
        return state

    def run_cli(self, argv):
        output, errors = Output(), io.StringIO()
        actual_open = os.open
        handler = signal.getsignal(signal.SIGALRM)
        mask = os.umask(0o077)
        def opening(path, flags, *args, **kwargs):
            if path == '/' and 'dir_fd' not in kwargs:
                return os.dup(self.root)
            return actual_open(path, flags, *args, **kwargs)
        try:
            with mock.patch.object(subject.os, 'open', side_effect=opening), \
                    mock.patch.object(subject.os, 'geteuid', return_value=0), \
                    mock.patch.object(subject.sys, 'stdout', output), \
                    mock.patch.object(subject.sys, 'stderr', errors):
                code = subject.main(argv)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, handler)
            os.umask(mask)
        public = errors.getvalue()
        for forbidden in (CANARY.decode(), str(self.base), 'Traceback'):
            self.assertNotIn(forbidden, public)
        return code, output.buffer.getvalue(), public

    def evidence(self, name, value):
        raw = c.canonical(value)
        self.put(self.parent / name, raw)
        return '/var/backups/metainc/' + name, c.digest(raw)

    def test_full_plan_bundle_verification_cleanup_cycle_preserves_other_backups_and_directories(self):
        protected = self.parent / 'naver-engine'
        protected.mkdir(mode=0o700)
        self.put(protected / 'daily.zip', b'untouched-daily')
        before = self.snapshot()
        code, raw_plan, errors = self.run_cli(['plan'])
        self.assertEqual((code, errors), (0, ''))
        plan = c.strict_json(raw_plan)
        self.assertEqual(raw_plan, c.canonical(plan))
        self.assertEqual(plan['total_bytes'], sum(len(data) for _, data in before.values()))
        plan_path, plan_sha = self.evidence('reviewed-plan.json', plan)
        code, bundle, errors = self.run_cli(['stream', '--plan', plan_path, '--plan-sha256', plan_sha])
        self.assertEqual((code, errors), (0, ''))
        self.assertEqual(c.verify_bundle(io.BytesIO(bundle), plan), {'files': c.file_rows(plan)})
        self.assertEqual(self.snapshot(), before)
        receipt = self.recovery(plan)
        receipt_path, receipt_sha = self.evidence('reviewed-recovery.json', receipt)
        code, raw_status, errors = self.run_cli(['cleanup', '--plan', plan_path, '--plan-sha256', plan_sha,
            '--recovery-receipt', receipt_path, '--recovery-sha256', receipt_sha, '--confirm', subject.CONFIRM])
        self.assertEqual((code, errors), (0, ''))
        status = c.strict_json(raw_status)
        self.assertEqual(status['status'], 'cleaned')
        self.assertEqual(status['removed_files'], self.cleanup_paths())
        self.assertNotEqual(status['removed_files'], [f['path'] for f in c.file_rows(plan)])
        self.assertIsNone(status['pending'])
        self.assertTrue(self.cold_folder.is_dir())
        self.assertTrue(self.interrupted.is_dir())
        self.assertEqual(list(self.cold_folder.iterdir()), [])
        self.assertEqual(list(self.interrupted.iterdir()), [])
        self.assertEqual((protected / 'daily.zip').read_bytes(), b'untouched-daily')
        journal = self.parent / subject.JOURNAL
        self.assertEqual(self.journal_records()[-1], status)
        self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)

    def test_corrupt_last_inner_gzip_prevents_any_journal_or_deletion(self):
        # A fresh outer plan binds the corrupt file hash; inner verification still fails.
        self.put(self.interrupted / 'snapshot.sqlite.gz', b'!' * len(self.zipped))
        before = self.snapshot()
        with self.assertRaises(c.Refused):
            self.cleanup()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.parent / subject.JOURNAL).exists())

    def test_inner_gzip_raw_hash_mismatch_prevents_deletion(self):
        changed = dict(self.interrupted_manifest, sha256='0' * 64)
        self.put(self.interrupted / 'snapshot.sqlite.json', c.canonical(changed))
        before = self.snapshot()
        with self.assertRaisesRegex(c.Refused, 'gzip_hash'):
            self.cleanup()
        self.assertEqual(self.snapshot(), before)

    def test_cold_original_manifest_mismatch_prevents_deletion(self):
        self.put(self.cold_folder / 'source-manifest.json', b'{}')
        before = self.snapshot()
        with self.assertRaisesRegex(c.Refused, 'source_manifest_hash'):
            self.cleanup()
        self.assertEqual(self.snapshot(), before)

    def test_cold_gzip_descriptor_mismatch_prevents_deletion(self):
        changed = copy.deepcopy(self.cold_manifest)
        changed['files']['engine.db']['gzip_sha256'] = '0' * 64
        self.put(self.cold_folder / 'archive-manifest.json', c.canonical(changed))
        before = self.snapshot()
        with self.assertRaises(c.Refused):
            self.cleanup()
        self.assertEqual(self.snapshot(), before)

    def test_stream_requires_same_reviewed_plan_after_source_change(self):
        plan_path, plan_sha = self.evidence('reviewed-plan.json', self.plan())
        self.put(self.interrupted / 'packed.zip.broken', b'changed-broken-zip')
        code, output, errors = self.run_cli(['stream', '--plan', plan_path, '--plan-sha256', plan_sha])
        self.assertEqual((code, output), (2, b''))
        self.assertEqual(c.strict_json(errors)['reason'], 'plan_changed')

    def test_still_open_source_modified_after_pin_is_refused(self):
        with self.sources() as (_, sources):
            path = self.interrupted / 'packed.zip.broken'
            path.write_bytes(b'!' * path.stat().st_size)
            with self.assertRaisesRegex(c.Refused, 'source_changed'):
                sources.recheck()

    def test_pinned_source_path_replacement_is_refused_without_deleting_replacement(self):
        with self.sources() as (_, sources):
            path = self.interrupted / 'packed.zip.broken'
            path.rename(path.with_name('detached'))
            self.put(path, b'replacement')
            with self.assertRaisesRegex(c.Refused, 'source_changed'):
                sources.recheck()
            self.assertEqual(path.read_bytes(), b'replacement')

    def test_file_symlink_hardlink_and_special_file_are_refused(self):
        path = self.interrupted / 'packed.zip.broken'
        original = path.read_bytes()
        path.unlink()
        victim = self.parent / 'unrelated'
        self.put(victim, original)
        for make in (lambda: path.symlink_to(victim), lambda: os.link(victim, path),
                     lambda: os.mkfifo(path, 0o600)):
            make()
            try:
                with self.assertRaises((c.Refused, OSError)):
                    self.plan()
                self.assertEqual(victim.read_bytes(), original)
            finally:
                path.unlink()

    def test_existing_shared_backup_ancestor_can_be_0755_without_chmod(self):
        self.parent.chmod(0o755)
        self.assertEqual(len(self.plan()['groups']), 2)
        self.assertEqual(stat.S_IMODE(self.parent.stat().st_mode), 0o755)

    def test_writable_shared_ancestor_and_nonprivate_payload_folder_are_refused(self):
        self.parent.chmod(0o775)
        with self.assertRaisesRegex(c.Refused, 'unsafe_directory'):
            self.plan()
        self.parent.chmod(0o755)
        self.cold_parent.chmod(0o755)
        with self.assertRaisesRegex(c.Refused, 'unsafe_directory'):
            self.plan()

    def test_group_directory_symlink_and_path_swap_are_refused(self):
        original = self.interrupted.with_name('saved-interrupted')
        self.interrupted.rename(original)
        self.interrupted.symlink_to(original, target_is_directory=True)
        with self.assertRaisesRegex(c.Refused, 'unsafe_directory'):
            self.plan()
        self.interrupted.unlink()
        original.rename(self.interrupted)
        with self.sources() as (_, sources):
            self.interrupted.rename(original)
            self.interrupted.mkdir(mode=0o700)
            with self.assertRaisesRegex(c.Refused, 'namespace_changed'):
                sources.recheck()

    def test_unexpected_group_and_member_names_are_refused(self):
        unknown = self.cold_parent / 'unknown-generation'
        unknown.mkdir(mode=0o700)
        with self.assertRaisesRegex(c.Refused, 'unknown_cold_directory'):
            self.plan()
        unknown.rmdir()
        extra = self.interrupted / 'do-not-delete'
        self.put(extra, b'separate-data')
        with self.assertRaisesRegex(c.Refused, 'unexpected_files'):
            self.plan()
        self.assertEqual(extra.read_bytes(), b'separate-data')

    def test_fixed_bundle_plan_has_three_bound_groups_and_six_closed_nested_paths(self):
        self.make_fixed_bundle_layout()
        before = self.snapshot()
        plan = self.plan()
        groups = [g for g in plan['groups'] if g['kind'].startswith('bundle')]
        self.assertEqual([g['kind'] for g in groups], ['bundle', 'bundle-deployment', 'bundle-snapshot'])
        self.assertEqual([g['name'] for g in groups], [c.BUNDLE] * 3)
        self.assertEqual([len(g['files']) for g in groups], [1, 3, 2])
        base = 'bundle/' + c.BUNDLE + '/'
        self.assertEqual([r['path'] for r in c.file_rows(plan) if r['path'].startswith(base)], [
            base + 'archive-manifest.json', base + 'deployment/archive-manifest.json',
            base + 'deployment/source-manifest.json', base + 'deployment/engine.db.gz',
            base + 'snapshot/archive-manifest.json', base + 'snapshot/snapshot.sqlite.gz'])
        for group, path in zip(groups, (self.fixed_bundle, self.fixed_bundle / 'deployment',
                                       self.fixed_bundle / 'snapshot')):
            self.assertEqual(group['identity'], subject.identity(path.stat()))
        self.assertEqual(self.snapshot(), before)

    def test_fixed_bundle_missing_or_pending_root_and_child_members_are_refused(self):
        self.make_fixed_bundle_layout()
        for parent, name in ((self.fixed_bundle, '.manifest.pending'),
                             (self.fixed_bundle / 'deployment', '.manifest.pending'),
                             (self.fixed_bundle / 'snapshot', 'unknown.gz')):
            with self.subTest(parent=parent.name, name=name):
                extra = parent / name
                self.put(extra, b'preserve-unknown')
                with self.assertRaisesRegex(c.Refused, 'unexpected_files'):
                    self.plan()
                self.assertEqual(extra.read_bytes(), b'preserve-unknown')
                extra.unlink()
        for path in (self.fixed_bundle / 'archive-manifest.json',
                     self.fixed_bundle / 'deployment/source-manifest.json',
                     self.fixed_bundle / 'snapshot/snapshot.sqlite.gz'):
            with self.subTest(missing=str(path.relative_to(self.fixed_bundle))):
                saved = path.read_bytes()
                path.unlink()
                with self.assertRaisesRegex(c.Refused, 'unexpected_files'):
                    self.plan()
                self.put(path, saved)

    def test_fixed_bundle_child_directory_missing_symlink_or_nonprivate_is_refused(self):
        self.make_fixed_bundle_layout()
        for name in ('deployment', 'snapshot'):
            child = self.fixed_bundle / name
            saved = self.parent / ('saved-' + name)
            child.rename(saved)
            with self.subTest(child=name, case='missing'), self.assertRaisesRegex(c.Refused, 'unexpected_files'):
                self.plan()
            child.symlink_to(saved, target_is_directory=True)
            with self.subTest(child=name, case='symlink'), self.assertRaisesRegex(c.Refused, 'unsafe_directory'):
                self.plan()
            child.unlink()
            saved.rename(child)
            child.chmod(0o755)
            with self.subTest(child=name, case='mode'), self.assertRaisesRegex(c.Refused, 'unsafe_directory'):
                self.plan()
            child.chmod(0o700)

    def test_fixed_bundle_file_symlink_hardlink_and_fifo_are_refused(self):
        self.make_fixed_bundle_layout()
        victim = self.parent / 'bundle-victim'
        self.put(victim, b'never-delete-this')
        for relative in ('archive-manifest.json', 'deployment/engine.db.gz', 'snapshot/archive-manifest.json'):
            path = self.fixed_bundle / relative
            original = path.read_bytes()
            path.unlink()
            for make in (lambda: path.symlink_to(victim), lambda: os.link(victim, path),
                         lambda: os.mkfifo(path, 0o600)):
                make()
                try:
                    with self.subTest(path=relative), self.assertRaises((c.Refused, OSError)):
                        self.plan()
                    self.assertEqual(victim.read_bytes(), b'never-delete-this')
                finally:
                    path.unlink()
            self.put(path, original)

    def test_new_cold_group_or_nested_member_after_pin_is_refused(self):
        self.make_fixed_bundle_layout()
        for folder, name in ((self.cold_parent, 'unknown-generation'),
                             (self.fixed_bundle, '.manifest.pending'),
                             (self.fixed_bundle / 'snapshot', '.manifest.pending')):
            with self.subTest(folder=folder.name), self.sources() as (_, sources):
                extra = folder / name
                self.put(extra, b'new-unreviewed-data')
                try:
                    with self.assertRaisesRegex(c.Refused, 'source_members_changed'):
                        sources.recheck()
                    self.assertEqual(extra.read_bytes(), b'new-unreviewed-data')
                finally:
                    extra.unlink()

    def test_fixed_bundle_child_path_replacement_after_pin_is_refused(self):
        self.make_fixed_bundle_layout()
        with self.sources() as (_, sources):
            child = self.fixed_bundle / 'deployment'
            saved = self.parent / 'detached-deployment'
            child.rename(saved)
            child.mkdir(mode=0o700)
            with self.assertRaisesRegex(c.Refused, 'namespace_changed'):
                sources.recheck()
            self.assertTrue((saved / 'engine.db.gz').is_file())

    def test_fixed_bundle_child_file_change_after_pin_is_refused(self):
        self.make_fixed_bundle_layout()
        with self.sources() as (_, sources):
            path = self.fixed_bundle / 'snapshot/snapshot.sqlite.gz'
            path.write_bytes(b'!' * path.stat().st_size)
            with self.assertRaisesRegex(c.Refused, 'source_changed'):
                sources.recheck()
            self.assertTrue(path.is_file())

    def test_fixed_bundle_full_verify_restore_cleanup_cycle_keeps_exact_bytes_and_root_manifest_last(self):
        self.make_verified_fixed_bundle()
        before = self.snapshot()
        plan, bundle = self.bundle()
        canonical_plan = c.canonical(plan)
        self.assertEqual(c.verify_bundle(io.BytesIO(bundle), plan), {'files': c.file_rows(plan)})
        output = self.base / 'fixed-bundle-restore'
        output.mkdir(mode=0o700)
        restored = c.restore_bundle(io.BytesIO(bundle), plan, str(output))
        self.assertEqual(restored, {'files': c.file_rows(plan)})
        for path in self.fixed_bundle.rglob('*'):
            if path.is_file():
                relative = Path('bundle') / c.BUNDLE / path.relative_to(self.fixed_bundle)
                self.assertEqual((output / relative).read_bytes(), path.read_bytes())
        self.assertEqual(self.snapshot(), before)
        with self.sources(True) as (parent, sources):
            receipt, state = self.recovery(plan), {}
            subject.cleanup(parent, sources, receipt, c.digest(c.canonical(receipt)), state)
            self.assertEqual(c.canonical(sources.plan), canonical_plan)
            sources.recheck(state['removed_files'])
        self.assertEqual(state['status'], 'cleaned')
        self.assertEqual(state['removed_files'], self.bundle_cleanup_paths())
        self.assertEqual(self.journal_records()[-1], state)
        self.assertEqual(self.snapshot(), {})
        self.assertEqual(set(path.name for path in self.fixed_bundle.iterdir()), {'deployment', 'snapshot'})
        self.assertTrue(all(path.is_dir() for path in self.fixed_bundle.iterdir()))

    def test_fixed_bundle_corrupt_inner_payload_is_held_without_journal_or_deletion(self):
        self.make_verified_fixed_bundle()
        target = self.fixed_bundle / 'snapshot/snapshot.sqlite.gz'
        self.put(target, b'!' * target.stat().st_size)
        before = self.snapshot()
        with self.assertRaises(c.Refused):
            self.cleanup()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.parent / subject.JOURNAL).exists())

    def test_fixed_bundle_first_child_manifest_failure_keeps_all_metadata_and_pending_nested_path(self):
        self.make_verified_fixed_bundle()
        before = {path: value for path, value in self.snapshot().items() if path.endswith('.json')}
        plan = self.plan()
        actual_unlink, state = os.unlink, {}
        def refuse_child_manifest(name, *args, **kwargs):
            if name == 'archive-manifest.json' and kwargs.get('dir_fd') is not None:
                raise OSError('synthetic first child manifest failure')
            return actual_unlink(name, *args, **kwargs)
        with mock.patch.object(subject.os, 'unlink', side_effect=refuse_child_manifest), self.assertRaises(OSError):
            self.cleanup(state=state)
        self.assertEqual(self.snapshot(), before)
        durable = self.journal_records()[-1]
        self.assertEqual(durable['removed_files'], self.bundle_cleanup_paths()[:6])
        self.assertEqual(durable['pending'], self.bundle_cleanup_paths()[6])
        self.assertEqual(durable['plan_sha256'], c.digest(c.canonical(plan)))
        self.assertEqual(durable['status'], 'cleanup_started')

    def test_fixed_bundle_root_manifest_unlink_failure_occurs_after_all_child_metadata(self):
        self.make_verified_fixed_bundle()
        root_manifest = self.fixed_bundle / 'archive-manifest.json'
        original = (subject.identity(root_manifest.stat()), root_manifest.read_bytes())
        actual_unlink, state = os.unlink, {}
        root_inode = self.fixed_bundle.stat().st_ino
        def refuse_root_manifest(name, *args, **kwargs):
            folder = kwargs.get('dir_fd')
            if name == 'archive-manifest.json' and folder is not None and os.fstat(folder).st_ino == root_inode:
                raise OSError('synthetic final root manifest failure')
            return actual_unlink(name, *args, **kwargs)
        with mock.patch.object(subject.os, 'unlink', side_effect=refuse_root_manifest), self.assertRaises(OSError):
            self.cleanup(state=state)
        self.assertEqual((subject.identity(root_manifest.stat()), root_manifest.read_bytes()), original)
        self.assertEqual(len(self.snapshot()), 1)
        self.assertEqual(list((self.fixed_bundle / 'deployment').iterdir()), [])
        self.assertEqual(list((self.fixed_bundle / 'snapshot').iterdir()), [])
        durable = self.journal_records()[-1]
        self.assertEqual(durable['removed_files'], self.bundle_cleanup_paths()[:-1])
        self.assertEqual(durable['pending'], self.bundle_cleanup_paths()[-1])
        self.assertEqual(durable['status'], 'cleanup_started')

    def test_fixed_bundle_root_manifest_replacement_before_unlink_preserves_all_payloads(self):
        self.make_verified_fixed_bundle()
        root_manifest = self.fixed_bundle / 'archive-manifest.json'
        saved = self.parent / 'detached-root-manifest.json'
        actual_hash, changed, state = subject.Sources.hash_fd, False, {}
        original = root_manifest.read_bytes()
        def replace_after_hash(fd, expected):
            nonlocal changed
            digest = actual_hash(fd, expected)
            if (self.parent / subject.JOURNAL).exists() and not changed:
                changed = True
                root_manifest.rename(saved)
                self.put(root_manifest, original)
            return digest
        with mock.patch.object(subject.Sources, 'hash_fd', staticmethod(replace_after_hash)), \
                self.assertRaisesRegex(c.Refused, 'source_changed'):
            self.cleanup(state=state)
        self.assertTrue(changed)
        self.assertEqual(state['removed_files'], [])
        self.assertEqual(root_manifest.read_bytes(), original)
        self.assertEqual(saved.read_bytes(), original)
        self.assertTrue((self.fixed_bundle / 'deployment/engine.db.gz').is_file())
        self.assertTrue((self.fixed_bundle / 'snapshot/snapshot.sqlite.gz').is_file())

    def test_recovery_receipt_is_bound_to_plan_files_and_fixed_status(self):
        plan = self.plan()
        changes = [dict(plan_sha256='0' * 64), dict(status='transferred_unverified'),
                   dict(session='wrong-session'), dict(verification='not-verified'),
                   dict(files=list(reversed(c.file_rows(plan)))), dict(cipher={'bytes': 1, 'sha256': 'bad'})]
        before = self.snapshot()
        for change in changes:
            receipt = self.recovery(plan)
            receipt.update(change)
            with self.subTest(change=change), self.assertRaisesRegex(c.Refused, 'recovery_receipt'):
                self.cleanup(receipt)
            self.assertEqual(self.snapshot(), before)
            self.assertFalse((self.parent / subject.JOURNAL).exists())

    def test_preexisting_journal_is_preserved_and_blocks_cleanup(self):
        self.put(self.parent / subject.JOURNAL, b'existing-human-review-needed')
        before = self.snapshot()
        with self.assertRaises(FileExistsError):
            self.cleanup()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((self.parent / subject.JOURNAL).read_bytes(), b'existing-human-review-needed')

    def test_unlink_failure_preserves_prior_progress_and_pending_target(self):
        original_unlink = os.unlink
        count, state = 0, {}
        def fail_second(name, *args, **kwargs):
            nonlocal count
            if kwargs.get('dir_fd') is not None:
                count += 1
                if count == 2:
                    raise OSError('synthetic_unlink_failure')
            return original_unlink(name, *args, **kwargs)
        with mock.patch.object(subject.os, 'unlink', side_effect=fail_second), self.assertRaises(OSError):
            self.cleanup(state=state)
        journal = self.journal_records()[-1]
        expected_paths = self.cleanup_paths()
        self.assertEqual(journal['removed_files'], expected_paths[:1])
        self.assertEqual(journal['pending'], expected_paths[1])
        self.assertEqual(journal['status'], 'cleanup_started')
        self.assertFalse((self.cold_folder / 'engine.db-wal.gz').exists())
        self.assertTrue((self.cold_folder / 'engine.db.gz').exists())
        self.assertTrue((self.cold_folder / 'archive-manifest.json').exists())
        self.assertTrue((self.cold_folder / 'source-manifest.json').exists())
        self.assertTrue((self.interrupted / 'snapshot.sqlite.json').exists())
        self.assertEqual(len(self.snapshot()), len(expected_paths) - 1)

    def test_last_payload_unlink_failure_retains_all_manifests_and_plan_binding(self):
        original_unlink = os.unlink
        plan, bundle = self.bundle()
        canonical_plan = c.canonical(plan)
        receipt = self.recovery(plan)
        metadata = {path: (subject.identity(path.stat()), path.read_bytes()) for path in (
            self.cold_folder / 'archive-manifest.json', self.cold_folder / 'source-manifest.json',
            self.interrupted / 'snapshot.sqlite.json')}
        state = {}
        def refuse_broken_zip(name, *args, **kwargs):
            if name == 'packed.zip.broken' and kwargs.get('dir_fd') is not None:
                raise OSError('synthetic last payload failure')
            return original_unlink(name, *args, **kwargs)
        with self.sources(True) as (parent, sources):
            with mock.patch.object(subject.os, 'unlink', side_effect=refuse_broken_zip), self.assertRaises(OSError):
                subject.cleanup(parent, sources, receipt, c.digest(c.canonical(receipt)), state)
            # Cleanup order never mutates the manifest-first wire plan or its hash.
            self.assertEqual(c.canonical(sources.plan), canonical_plan)
        self.assertEqual(c.verify_bundle(io.BytesIO(bundle), plan), {'files': receipt['files']})
        self.assertEqual({path: (subject.identity(path.stat()), path.read_bytes()) for path in metadata}, metadata)
        journal = self.journal_records()[-1]
        self.assertEqual(journal['removed_files'], self.cleanup_paths()[:3])
        self.assertEqual(journal['pending'], self.cleanup_paths()[3])
        self.assertEqual(journal['plan_sha256'], c.digest(canonical_plan))
        self.assertTrue((self.interrupted / 'packed.zip.broken').exists())
        self.assertEqual(len(self.snapshot()), 4)

    def test_first_manifest_unlink_failure_occurs_only_after_all_payloads_removed(self):
        original_unlink = os.unlink
        state = {}
        def refuse_manifest(name, *args, **kwargs):
            if name == 'archive-manifest.json' and kwargs.get('dir_fd') is not None:
                raise OSError('synthetic first manifest failure')
            return original_unlink(name, *args, **kwargs)
        with mock.patch.object(subject.os, 'unlink', side_effect=refuse_manifest), self.assertRaises(OSError):
            self.cleanup(state=state)
        journal = self.journal_records()[-1]
        self.assertEqual(journal['removed_files'], self.cleanup_paths()[:4])
        self.assertEqual(journal['pending'], self.cleanup_paths()[4])
        self.assertEqual(set(path.name for folder in (self.cold_folder, self.interrupted)
                             for path in folder.iterdir()),
                         {'archive-manifest.json', 'source-manifest.json', 'snapshot.sqlite.json'})

    def test_journal_write_failure_after_unlink_retains_last_durable_progress(self):
        original_write = os.write
        first = self.cold_folder / 'engine.db-wal.gz'
        plan = self.plan()
        state = {}
        def failed_after_unlink(fd, data):
            if not first.exists():
                raise OSError('synthetic journal write failure')
            return original_write(fd, data)
        with mock.patch.object(subject.os, 'write', side_effect=failed_after_unlink), self.assertRaises(OSError):
            self.cleanup(state=state)
        self.assertFalse(first.exists())
        raw = (self.parent / subject.JOURNAL).read_bytes()
        self.assertGreater(len(raw), 0, 'The last durable pending target must survive a journal rewrite failure')
        journal = self.journal_records()[-1]
        first_path = self.cleanup_paths()[0]
        self.assertTrue(first_path in journal['removed_files'] or journal['pending'] == first_path)
        self.assertEqual(len(self.snapshot()), len(c.file_rows(plan)) - 1)

    def test_partial_journal_append_keeps_previous_complete_pending_record(self):
        original_write = os.write
        first = self.cold_folder / 'engine.db-wal.gz'
        plan, state = self.plan(), {}
        after_unlink_writes = 0
        def partial_then_fail(fd, data):
            nonlocal after_unlink_writes
            if not first.exists():
                after_unlink_writes += 1
                if after_unlink_writes == 1:
                    return original_write(fd, data[:5])
                raise OSError('synthetic partial journal append')
            return original_write(fd, data)
        with mock.patch.object(subject.os, 'write', side_effect=partial_then_fail), self.assertRaises(OSError):
            self.cleanup(state=state)
        raw = (self.parent / subject.JOURNAL).read_bytes()
        self.assertFalse(raw.endswith(b'\n'))
        records = self.journal_records()
        self.assertGreaterEqual(len(records), 2)
        self.assertEqual(records[-1]['pending'], self.cleanup_paths()[0])
        self.assertEqual(records[-1]['removed_files'], [])
        self.assertFalse(first.exists())
        self.assertEqual(len(self.snapshot()), len(c.file_rows(plan)) - 1)

    def test_source_changed_after_recovery_check_is_not_unlinked(self):
        original_hash = subject.Sources.hash_fd
        state, changed = {}, False
        target = self.cold_folder / 'archive-manifest.json'
        before = target.read_bytes()
        def mutate_after_hash(fd, expected):
            nonlocal changed
            result = original_hash(fd, expected)
            if (self.parent / subject.JOURNAL).exists() and not changed:
                changed = True
                self.put(target, b'!' * len(before))
            return result
        with mock.patch.object(subject.Sources, 'hash_fd', staticmethod(mutate_after_hash)), self.assertRaisesRegex(c.Refused, 'source_changed'):
            self.cleanup(state=state)
        self.assertTrue(changed)
        self.assertEqual(target.read_bytes(), b'!' * len(before))
        self.assertEqual(state['removed_files'], [])

    def test_plan_canonical_bytes_hash_and_evidence_permissions_are_required(self):
        plan = self.plan()
        path, expected = self.evidence('reviewed-plan.json', plan)
        plan_file = self.parent / 'reviewed-plan.json'
        for raw, digest, mode, reason in (
            (c.canonical(plan), '0' * 64, 0o600, 'evidence_hash'),
            (json.dumps(plan, indent=2).encode(), None, 0o600, 'noncanonical_plan'),
            (c.canonical(plan), expected, 0o644, 'unsafe_evidence'),
        ):
            self.put(plan_file, raw, mode)
            code, output, errors = self.run_cli(['stream', '--plan', path, '--plan-sha256', digest or c.digest(raw)])
            self.assertEqual((code, output), (2, b''))
            self.assertEqual(c.strict_json(errors)['reason'], reason)

    def test_total_plan_limit_is_eleven_gib_and_rejects_overflow(self):
        plan = self.plan()
        self.assertEqual(c.MAX_TOTAL, 11 * 1024 ** 3)
        changed = copy.deepcopy(plan)
        row = changed['groups'][-1]['files'][-1]
        increment = c.MAX_TOTAL + 1 - changed['total_bytes']
        row['size'] += increment
        row['identity']['size'] = row['size']
        changed['total_bytes'] += increment
        with self.assertRaises(c.Refused):
            c.validate_plan(changed)

    def test_duplicate_plan_json_and_extra_bundle_bytes_are_refused(self):
        with self.assertRaisesRegex(c.Refused, 'duplicate_key'):
            c.strict_json(b'{"version":1,"version":1}')
        plan, data = self.bundle()
        with self.assertRaisesRegex(c.Refused, 'bundle_trailing_data'):
            c.verify_bundle(io.BytesIO(data + b'extra'), plan)
        with self.assertRaisesRegex(c.Refused, 'truncated_bundle'):
            c.verify_bundle(io.BytesIO(data[:-1]), plan)

    def test_bundle_plan_mismatch_is_rejected_before_payload(self):
        plan, data = self.bundle()
        other = copy.deepcopy(plan)
        other['groups'][0]['files'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(c.Refused, 'plan_mismatch'):
            c.verify_bundle(io.BytesIO(data), other)

    def test_gzip_extra_member_trailing_data_and_expansion_are_refused(self):
        for data, size, error in (
            (self.zipped + self.zipped, len(self.raw), 'gzip_trailing_data'),
            (self.zipped + b'garbage', len(self.raw), 'gzip_trailing_data'),
            (self.zipped, len(self.raw) - 1, 'gzip_size'),
            (self.zipped[:-1], len(self.raw), 'gzip_incomplete'),
        ):
            check = c.GzipCheck(size, c.digest(self.raw))
            with self.subTest(error=error), self.assertRaisesRegex(c.Refused, error):
                check.write(data)
                check.finish()

    def test_isolated_restore_reconstructs_exact_compressed_files_without_opening_database(self):
        plan, bundle = self.bundle()
        output = self.base / 'isolated-restore'
        output.mkdir(mode=0o700)
        result = c.restore_bundle(io.BytesIO(bundle), plan, str(output))
        self.assertEqual(result, {'files': c.file_rows(plan)})
        for row in result['files']:
            target = output / row['path']
            self.assertEqual(target.stat().st_size, row['size'])
            self.assertEqual(c.digest(target.read_bytes()), row['sha256'])
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(target.stat().st_nlink, 1)
        self.assertFalse(any(path.name in ('engine.db', 'snapshot.sqlite') for path in output.rglob('*')))
        self.assertTrue((output / 'interrupted' / c.INTERRUPTED / 'packed.zip.broken').exists())
        before = {str(path.relative_to(output)): path.read_bytes() for path in output.rglob('*') if path.is_file()}
        with self.assertRaisesRegex(c.Refused, 'restore_directory'):
            c.restore_bundle(io.BytesIO(bundle), plan, str(output))
        self.assertEqual(before, {str(path.relative_to(output)): path.read_bytes()
                                  for path in output.rglob('*') if path.is_file()})

    def test_same_inode_same_size_restore_corruption_is_refused_and_retained(self):
        plan, bundle = self.bundle()
        output = self.base / 'corrupted-restore'
        output.mkdir(mode=0o700)
        target = output / 'interrupted' / c.INTERRUPTED / 'snapshot.sqlite.gz'
        original_write = os.write
        def corrupt_after_write(fd, data):
            count = original_write(fd, data)
            if target.exists() and os.fstat(fd).st_ino == target.stat().st_ino:
                os.pwrite(fd, b'!', 0)
            return count
        with mock.patch.object(c.os, 'write', side_effect=corrupt_after_write), self.assertRaises(c.Refused):
            c.restore_bundle(io.BytesIO(bundle), plan, str(output))
        self.assertTrue(target.exists())
        self.assertEqual(target.stat().st_size, len(self.zipped))
        self.assertNotEqual(c.digest(target.read_bytes()), c.digest(self.zipped))

    def test_restore_capacity_loss_keeps_partial_output_for_inspection(self):
        plan, bundle = self.bundle()
        output = self.base / 'space-limited-restore'
        output.mkdir(mode=0o700)
        class NoSpace:
            f_bavail, f_frsize = 0, 4096
        with mock.patch.object(c.os, 'fstatvfs', return_value=NoSpace()), self.assertRaisesRegex(c.Refused, 'restore_space'):
            c.restore_bundle(io.BytesIO(bundle), plan, str(output))
        self.assertTrue(output.exists())
        self.assertTrue(any(path.is_file() for path in output.rglob('*')))
        self.assertEqual(len(self.snapshot()), len(c.file_rows(plan)))


if __name__ == '__main__':
    unittest.main()
