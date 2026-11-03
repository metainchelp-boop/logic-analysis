import importlib.util
import contextlib
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('backup_bundle', Path(__file__).parents[1] / 'backup_bundle.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)


class ClosedPlanTests(unittest.TestCase):
    def plan(self):
        row = dict(size=17, sha256='1' * 64, gzip_size=37, gzip_sha256='2' * 64)
        return dict(version=1, scope=B.SCOPE, codec=B.codec(),
                    source_identity_sha256='3' * 64, producer_sha256='4' * 64,
                    protected_sha256='5' * 64,
                    files=dict(deployment=dict(row), snapshot=dict(row)))

    def test_closed_plan_roundtrip_and_hash(self):
        plan = self.plan()
        raw = B.A.canonical(plan)
        self.assertEqual(B.parse_plan(raw, B.A.digest(raw.encode())), plan)
        for bad in (dict(plan, path='/tmp/anything'), dict(plan, version=True),
                    dict(plan, scope='another-profile')):
            with self.subTest(bad=bad), self.assertRaises(B.Refused):
                B.validate_plan(bad)

    def test_plan_rejects_wrong_hash_duplicate_keys_and_nonfinite_values(self):
        raw = B.A.canonical(self.plan())
        for value, digest in ((raw, 'f' * 64), ('{"version":1,"version":1}', 'f' * 64),
                              ('NaN', 'f' * 64), ('x' * 8193, 'f' * 64)):
            with self.subTest(length=len(value)), self.assertRaises(B.Refused):
                B.parse_plan(value, digest)

    def test_off_host_plan_observation_parses_but_apply_requires_matching_codec(self):
        plan = self.plan()
        plan['codec']['python'] = '3.10.22'
        plan['codec']['zlib'] = '1.2.11'
        raw = B.A.canonical(plan)
        self.assertEqual(B.parse_plan(raw, B.hash_object(plan)), plan)
        with mock.patch.object(B, 'codec', return_value=dict(level=6, mtime=0, python='3.12.9', zlib='1.3')):
            result = B.execute('apply', B.hash_object(plan), B.CONFIRM, raw)
        self.assertEqual(result['reason'], 'PLAN_MISMATCH')
        self.assertFalse(result['archive_started'])


class BundleFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='naver-bundle-test-', dir=Path.home())
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.backups, self.archives, self.regular = (self.base / name for name in ('backups', 'archives', 'regular'))
        for path in (self.backups, self.archives, self.regular):
            path.mkdir(mode=0o700)
        self.cold = self.backups / B.A.profile_for(B.DEPLOYMENT_SCOPE).backup
        self.cold.mkdir(mode=0o700)
        self.local = self.regular / 'local'
        self.local.mkdir(mode=0o700)
        self.building = self.local / '.building-abcdefgh'
        self.building.mkdir(mode=0o700)
        self.payload = b'backup-fixture\x00!' * 2048
        self.assertEqual(len(self.payload), 32768)
        for path in (self.cold / 'engine.db', self.building / 'snapshot.sqlite'):
            path.write_bytes(self.payload)
            path.chmod(0o600)
        self.raw = json.dumps({'engine.db': dict(size=len(self.payload), sha256=B.A.digest(self.payload))}, indent=2).encode() + b'\n'
        (self.cold / 'manifest.json').write_bytes(self.raw)
        (self.cold / 'manifest.json').chmod(0o600)
        for i in range(3):
            path = self.local / ('naver-20261101T000000Z-%032x.zip' % i)
            path.write_bytes(b'protected-completed-backup')
            path.chmod(0o600)
        os.utime(self.building, ns=(1792594892360859000, 1792594892360859000))
        self.patches = [mock.patch.multiple(B.A, BACKUP_PARENT=str(self.backups), ARCHIVE_PARENT=str(self.archives),
                                           ROOT_UID=os.getuid(), ROOT_GID=os.getgid()),
                        mock.patch.multiple(B, BACKUP_ROOT=str(self.regular), ENGINE_UID=os.getuid(),
                                            ENGINE_GID=os.getgid(), CANDIDATE_BYTES=len(self.payload))]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.free = lambda: 10 * 1024 ** 3
        self.producer = lambda *args: {'generation': 'fixture'}
        self.ref_calls = []
        def reference(*args):
            self.ref_calls.append(True)
        self.reference = reference

    def runner(self, command):
        self.assertEqual(command[:2], B.A.DOCKER)
        args = command[2:]
        ids = ['%064x' % value for value in range(1, 6)]
        images = ['sha256:%064x' % value for value in range(11, 16)]
        if args == ('ps', '-aq', '--no-trunc'):
            output = '\n'.join(ids)
        elif args == ('image', 'ls', '-aq', '--no-trunc'):
            output = '\n'.join(images)
        else:
            self.assertEqual(args[:4], ('inspect', '--type=container', '--format', B.A.INSPECT_FORMAT))
            self.assertEqual(list(args[4:]), ids)
            output = '\n'.join(B.A.canonical(dict(id=cid, image=image, running=True, pid=i + 1,
                started='2026-11-03T01:00:00Z', restarts=0)) for i, (cid, image) in enumerate(zip(ids, images)))
        return types.SimpleNamespace(returncode=0, stdout=output.encode(), stderr=b'')

    def execute(self, mode='plan', plan=None, **kwargs):
        kwargs.setdefault('runner', self.runner)
        kwargs.setdefault('free', self.free)
        kwargs.setdefault('producer_probe', self.producer)
        kwargs.setdefault('reference_probe', self.reference)
        return B.execute(mode, plan['plan_sha256'] if plan else '', B.CONFIRM if mode == 'apply' else '',
                         B.A.canonical(plan['plan']) if plan else '', **kwargs)

    def plan(self):
        result = self.execute()
        self.assertEqual(result['status'], 'planned', result)
        return result

    def source_bytes(self):
        return {(str(p.relative_to(self.base))): (B.A.identity(p.stat()), p.read_bytes())
                for folder in (self.local, self.cold) for p in folder.rglob('*') if p.is_file()}


class BundleExecutionTests(BundleFixture):
    def test_plan_preserves_every_original_and_apply_roundtrips_both_before_cleanup(self):
        before = self.source_bytes()
        plan = self.plan()
        self.assertEqual(self.source_bytes(), before)
        self.assertEqual(list(self.archives.iterdir()), [])
        self.assertEqual(plan['reference_checks'], 2)
        with mock.patch.object(B.A, 'compress', wraps=B.A.compress) as compressed:
            result = self.execute('apply', plan)
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual(compressed.call_count, 2, 'APPLY compresses each source only once')
        self.assertEqual(result['removed_files'], 3)
        self.assertFalse(self.cold.exists())
        self.assertFalse(self.building.exists())
        self.assertEqual(len(list(self.local.iterdir())), 3)
        bundle = self.archives / B.ARCHIVE_NAME
        manifest = json.loads((bundle / 'archive-manifest.json').read_text())
        B.A.restore_isolated(str(bundle / 'deployment'), str(self.base), 'restore-check-1111111111111111',
            manifest['deployment_archive_sha256'], B.DEPLOYMENT_SCOPE)
        B.restore_snapshot_isolated(str(bundle / 'snapshot'), str(self.base), 'restore-check-2222222222222222',
            manifest['snapshot_archive_sha256'])
        self.assertEqual((self.base / 'restore-check-1111111111111111/engine.db').read_bytes(), self.payload)
        self.assertEqual((self.base / 'restore-check-1111111111111111/manifest.json').read_bytes(), self.raw)
        self.assertEqual((self.base / 'restore-check-2222222222222222/snapshot.sqlite').read_bytes(), self.payload)

    def test_space_refusal_preserves_all_sources_and_creates_no_archive(self):
        plan = self.plan()
        before = self.source_bytes()
        result = self.execute('apply', plan, free=lambda: B.A.RESERVE)
        self.assertEqual(result['reason'], 'SPACE_REFUSED')
        self.assertFalse(result['archive_started'])
        self.assertEqual(before, self.source_bytes())
        self.assertEqual(list(self.archives.iterdir()), [])

    def test_late_reference_or_changed_source_never_authorizes_unlink(self):
        plan = self.plan()
        before = self.source_bytes()
        count = 0
        def late(*args):
            nonlocal count
            count += 1
            if count == 3:
                raise B.Refused('SOURCE_IN_USE')
        result = self.execute('apply', plan, reference_probe=late)
        self.assertEqual(result['reason'], 'SOURCE_IN_USE')
        self.assertTrue(result['archive_verified'])
        self.assertFalse(result['cleanup_started'])
        self.assertEqual(before, self.source_bytes())

    def test_plan_hash_binds_source_generation_and_codec_without_paths(self):
        plan = self.plan()
        result = self.execute('apply', plan, producer_probe=lambda *args: {'generation': 'new'})
        self.assertEqual(result['reason'], 'PLAN_MISMATCH')
        self.assertFalse(result['archive_started'])
        self.assertNotIn(str(self.base), B.A.canonical(plan))
        self.assertNotIn(self.building.name, B.A.canonical(plan))


class ProducerBindingTests(BundleFixture):
    def test_exact_image_source_bind_generation_and_no_symlink_code(self):
        procroot = self.base / 'proc'
        (procroot / '101').mkdir(parents=True)
        container = self.base / 'container'
        code = container / 'opt/naver-engine/naver_engine'
        code.mkdir(parents=True)
        (procroot / '101/root').symlink_to(container, target_is_directory=True)
        source = code / 'backup.py'
        source.write_bytes(b'exact synthetic producer source')
        expected = B.A.digest(source.read_bytes())
        generation = (123, 1, 4, 5, 6, 7)
        proc = types.SimpleNamespace(root=procroot, identity=lambda *args: generation)
        engine = dict(id='1' * 64, image=B.ENGINE_IMAGE, running=True, pid=101,
                      started='2099-01-01T00:00:00.123456789Z', restarts=0)
        row = dict(id=engine['id'], user='10001:10001', readonly=True,
                   project='naver-engine', service='naver-engine',
                   mounts=[dict(Destination='/var/backups/naver-engine', Source=str(self.regular), Type='bind', RW=True)])
        runner = lambda command: types.SimpleNamespace(returncode=0, stdout=json.dumps(row).encode(), stderr=b'')
        original_beneath = B.beneath
        with B.snapshot_source() as snapshot:
            @contextlib.contextmanager
            def mounted(root, components):
                if tuple(components) == ('var', 'backups', 'naver-engine'):
                    yield snapshot['root']
                else:
                    with original_beneath(root, components) as fd:
                        yield fd
            with mock.patch.object(B, 'beneath', side_effect=mounted), \
                    mock.patch.object(B, 'SOURCE_PINS', {'naver_engine/backup.py': expected}):
                result = B.producer_state(dict(containers=[engine]), snapshot, B.A.Budget(), runner, proc)
                self.assertEqual(result['generation'], generation)
                source.write_bytes(b'tampered producer source')
                with self.assertRaisesRegex(B.Refused, 'PRODUCER_REFUSED'):
                    B.producer_state(dict(containers=[engine]), snapshot, B.A.Budget(), runner, proc)
                source.write_bytes(b'exact synthetic producer source')
                for field, wrong in (('image', 'sha256:' + 'f' * 64), ('started', '2020-01-01T00:00:00Z')):
                    with self.subTest(field=field), self.assertRaises(B.Refused):
                        B.producer_state(dict(containers=[dict(engine, **{field: wrong})]), snapshot, B.A.Budget(), runner, proc)
                row['mounts'][0]['Source'] = '/wrong/mount'
                with self.assertRaises(B.Refused):
                    B.producer_state(dict(containers=[engine]), snapshot, B.A.Budget(), runner, proc)
                row['mounts'][0]['Source'] = str(self.regular)
                source.unlink()
                source.symlink_to(self.cold / 'engine.db')
                with self.assertRaises(OSError):
                    B.producer_state(dict(containers=[engine]), snapshot, B.A.Budget(), runner, proc)

    def test_candidate_shape_age_and_completed_backups_are_required(self):
        before = self.source_bytes()
        with B.snapshot_source() as snapshot:
            self.assertEqual(snapshot['file']['size'], len(self.payload))
        self.assertEqual(self.source_bytes(), before)
        extra = self.building / 'packed.zip'
        extra.write_bytes(b'active work')
        extra.chmod(0o600)
        result = self.execute()
        self.assertEqual(result['reason'], 'SOURCE_REFUSED')
        self.assertFalse(result['archive_started'])
        self.assertEqual(list(self.archives.iterdir()), [])

    def test_timestamp_validation_keeps_nanoseconds_and_rejects_bad_calendar(self):
        self.assertEqual(B.timestamp_ns('2026-10-21T15:01:32.360859123Z'), 1792594892360859123)
        for value in ('2026-02-30T00:00:00Z', '2026-10-21T15:01:32.1234567890Z', '2026-10-21'):
            with self.subTest(value=value), self.assertRaises((B.Refused, ValueError)):
                B.timestamp_ns(value)


if __name__ == '__main__':
    unittest.main()
