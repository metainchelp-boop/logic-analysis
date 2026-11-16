"""Synthetic fixed backup_bundle archives; no server, keys, or database access."""
import copy
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    'naver_archive_bundle_common_test', Path(__file__).resolve().parents[1] / 'naver_archive_common.py')
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
B = subject.bundle_helper()


def historic_metadata(size=0, mode=0o600, uid=0, gid=0, inode=2):
    return dict(device=1, inode=inode, mode=mode, uid=uid, gid=gid, size=size,
                links=1, mtime_ns=1, ctime_ns=2, allocated_bytes=((size + 511) // 512) * 512)


def make_fixture(common=None):
    """Return (wire plan, path->bytes, raw child bytes), all independently synthetic.

    Verification of this small fixture must patch only B.CANDIDATE_BYTES to the
    synthetic snapshot size, and common.bundle_helper to B. Production retains
    its exact 2475552768 byte source condition, exercised separately below.
    """
    c = common or subject
    raw = {'deployment': b'synthetic historical deployment bytes\0' * 61,
           'snapshot': b'synthetic historical snapshot bytes\0' * 73}
    compressed = {kind: gzip.compress(data, compresslevel=6, mtime=0) for kind, data in raw.items()}
    rows = {kind: dict(size=len(data), sha256=c.digest(data), gzip_size=len(compressed[kind]),
                      gzip_sha256=c.digest(compressed[kind])) for kind, data in raw.items()}
    original = json.dumps({'engine.db': {k: rows['deployment'][k] for k in ('size', 'sha256')}},
                          indent=2).encode() + b'\n'
    codec = dict(level=6, mtime=0, zlib='1.2.13', python='3.10.4')
    protected = {'containers': [], 'images': []}
    source_plan = dict(version=1, scope=B.SCOPE, codec=codec,
        source_identity_sha256='1' * 64, producer_sha256='2' * 64,
        protected_sha256=c.digest(c.canonical(protected)), files=copy.deepcopy(rows))
    profile = c.cold.profile_for(B.DEPLOYMENT_SCOPE)
    deployment = dict(version=1, scope=profile.scope, backup=profile.backup, archive=profile.archive,
        gzip=codec, source_folder=historic_metadata(mode=0o700),
        source_manifest=historic_metadata(len(original)), source_manifest_sha256=c.digest(original),
        files={'engine.db': dict(rows['deployment'], source=historic_metadata(len(raw['deployment'])))},
        protected=protected, reserve_bytes=512 * 1024 ** 2,
        minimum_free_after_bytes=5 * 1024 ** 3, overhead_bytes=1024 * 1024)
    snapshot = dict(version=1, scope=B.SCOPE, kind='interrupted-snapshot-bytes', codec=codec,
        source_folder=historic_metadata(mode=0o700, uid=10001, gid=10001),
        source_file=historic_metadata(len(raw['snapshot']), uid=10001, gid=10001),
        file=copy.deepcopy(rows['snapshot']))
    root = dict(version=1, scope=B.SCOPE, plan=source_plan, plan_sha256=c.digest(c.canonical(source_plan)),
                deployment_archive_sha256=c.digest(c.canonical(deployment)),
                snapshot_archive_sha256=c.digest(c.canonical(snapshot)))
    members = {'bundle': {'archive-manifest.json': c.canonical(root)},
               'bundle-deployment': {'archive-manifest.json': c.canonical(deployment),
                   'source-manifest.json': original, 'engine.db.gz': compressed['deployment']},
               'bundle-snapshot': {'archive-manifest.json': c.canonical(snapshot),
                   'snapshot.sqlite.gz': compressed['snapshot']}}
    groups, payloads = [], {}
    for kind in ('bundle', 'bundle-deployment', 'bundle-snapshot'):
        files = []
        for name in c.names_for(kind, members[kind]):
            data = members[kind][name]
            payloads[c.path_for(kind, c.BUNDLE, name)] = data
            files.append(dict(name=name, size=len(data), sha256=c.digest(data),
                              identity=historic_metadata(len(data))))
        groups.append(dict(kind=kind, name=c.BUNDLE, identity=historic_metadata(mode=0o700), files=files))
    plan = dict(version=1, session=c.SESSION, groups=groups, total_bytes=sum(map(len, payloads.values())))
    return plan, payloads, raw


def wire(plan, payloads, common=None):
    c = common or subject
    return c.header(plan) + b''.join(payloads[row['path']] for row in c.file_rows(plan))


class BundleArchiveTest(unittest.TestCase):
    def setUp(self):
        self.plan, self.payloads, self.raw = make_fixture()
        self.patches = [mock.patch.object(subject, 'bundle_helper', return_value=B),
                        mock.patch.object(B, 'CANDIDATE_BYTES', len(self.raw['snapshot']))]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def path(self, kind, name='archive-manifest.json'):
        return subject.path_for(kind, subject.BUNDLE, name)

    def manifest(self, kind):
        return subject.strict_json(self.payloads[self.path(kind)])

    def replace(self, kind, name, data):
        self.payloads[self.path(kind, name)] = data
        group = next(g for g in self.plan['groups'] if g['kind'] == kind)
        row = next(r for r in group['files'] if r['name'] == name)
        row.update(size=len(data), sha256=subject.digest(data), identity=historic_metadata(len(data)))
        self.plan['total_bytes'] = sum(row['size'] for g in self.plan['groups'] for row in g['files'])

    def replace_manifest(self, kind, value, bind_child=False):
        self.replace(kind, 'archive-manifest.json', subject.canonical(value))
        if bind_child:
            root = self.manifest('bundle')
            root[kind[len('bundle-'):] + '_archive_sha256'] = subject.digest(subject.canonical(value))
            self.replace_manifest('bundle', root)

    def replace_compressed(self, kind, data):
        child = kind[len('bundle-'):]
        name = 'engine.db.gz' if child == 'deployment' else 'snapshot.sqlite.gz'
        self.replace(kind, name, data)
        manifest = self.manifest(kind)
        row = manifest['files']['engine.db'] if child == 'deployment' else manifest['file']
        row.update(gzip_size=len(data), gzip_sha256=subject.digest(data))
        self.replace_manifest(kind, manifest, bind_child=True)
        root = self.manifest('bundle')
        root['plan']['files'][child].update(gzip_size=len(data), gzip_sha256=subject.digest(data))
        root['plan_sha256'] = subject.digest(subject.canonical(root['plan']))
        self.replace_manifest('bundle', root)

    def verify(self, data=None):
        return subject.verify_bundle(io.BytesIO(wire(self.plan, self.payloads) if data is None else data), self.plan)

    def refuse(self, code=None):
        with self.assertRaises(subject.Refused) as caught:
            self.verify()
        if code:
            self.assertEqual(str(caught.exception), code)

    def test_complete_six_files_verify_with_nested_unique_recovery_paths(self):
        result = self.verify()
        self.assertEqual(result['files'], subject.file_rows(self.plan))
        self.assertEqual(len(result['files']), 6)
        self.assertEqual(len({r['path'] for r in result['files']}), 6)
        self.assertIn(self.path('bundle-snapshot', 'snapshot.sqlite.gz'), self.payloads)
        self.assertTrue(all('bundle-' not in row['path'] for row in result['files']))

    def test_production_exact_snapshot_size_remains_required(self):
        with mock.patch.object(B, 'CANDIDATE_BYTES', 2475552768):
            self.refuse('bundle_manifest')

    def test_each_partial_trio_is_rejected(self):
        original = copy.deepcopy(self.plan)
        for omitted in subject.BUNDLE_KINDS:
            self.plan = copy.deepcopy(original)
            self.plan['groups'] = [g for g in self.plan['groups'] if g['kind'] != omitted]
            self.plan['total_bytes'] = sum(r['size'] for g in self.plan['groups'] for r in g['files'])
            with self.subTest(omitted=omitted), self.assertRaisesRegex(subject.Refused, 'incomplete_bundle_groups'):
                subject.validate_plan(self.plan)

    def test_unknown_bundle_name_and_member_paths_are_rejected(self):
        for kind, name, member in (
                ('bundle', '../escape', 'archive-manifest.json'),
                ('bundle-deployment', subject.BUNDLE, '../../escape'),
                ('bundle-snapshot', subject.BUNDLE, 'engine.db.gz'),
                ('bundle-unknown', subject.BUNDLE, 'archive-manifest.json')):
            with self.subTest(kind=kind), self.assertRaises(subject.Refused):
                subject.path_for(kind, name, member)
        self.plan['groups'][0]['name'] = subject.BUNDLE + '-other'
        with self.assertRaises(subject.Refused):
            subject.validate_plan(self.plan)

    def test_pending_extra_or_missing_file_names_are_rejected(self):
        for kind in subject.BUNDLE_KINDS:
            names = subject.BUNDLE_FILES[kind]
            for changed in ((*names, '.manifest.pending'), (*names, 'extra'), names[1:]):
                with self.subTest(kind=kind, changed=changed), self.assertRaises(subject.Refused):
                    subject.names_for(kind, changed)

    def test_duplicate_reordered_groups_and_manifest_after_payload_are_rejected(self):
        original = copy.deepcopy(self.plan)
        cases = []
        p = copy.deepcopy(original)
        p['groups'].reverse()
        cases.append(p)
        p = copy.deepcopy(original)
        p['groups'].append(copy.deepcopy(p['groups'][0]))
        cases.append(p)
        p = copy.deepcopy(original)
        p['groups'][1]['files'].reverse()
        cases.append(p)
        for plan in cases:
            with self.subTest(plan=plan), self.assertRaises(subject.Refused):
                subject.validate_plan(plan)

    def test_root_plan_hash_must_match(self):
        root = self.manifest('bundle')
        root['plan_sha256'] = '0' * 64
        self.replace_manifest('bundle', root)
        self.refuse('bundle_manifest')

    def test_root_scope_and_closed_schema_are_enforced(self):
        for key, value in (('scope', 'other'), ('extra', True), ('version', True)):
            with self.subTest(key=key):
                self.plan, self.payloads, self.raw = make_fixture()
                root = self.manifest('bundle')
                root[key] = value
                self.replace_manifest('bundle', root)
                self.refuse('bundle_manifest')

    def test_root_plan_row_and_scope_are_validated_even_when_self_hash_matches(self):
        for key, value in (('scope', 'other'), ('version', True), ('files', {})):
            with self.subTest(key=key):
                self.plan, self.payloads, self.raw = make_fixture()
                root = self.manifest('bundle')
                root['plan'][key] = value
                root['plan_sha256'] = subject.digest(subject.canonical(root['plan']))
                self.replace_manifest('bundle', root)
                self.refuse('bundle_manifest')

    def test_both_child_hash_bindings_are_required(self):
        for child in ('deployment', 'snapshot'):
            with self.subTest(child=child):
                self.plan, self.payloads, self.raw = make_fixture()
                root = self.manifest('bundle')
                root[child + '_archive_sha256'] = 'a' * 64
                self.replace_manifest('bundle', root)
                self.refuse('bundle_manifest')

    def test_child_codec_must_match_root_plan(self):
        for kind, key in (('bundle-deployment', 'gzip'), ('bundle-snapshot', 'codec')):
            with self.subTest(kind=kind):
                self.plan, self.payloads, self.raw = make_fixture()
                child = self.manifest(kind)
                child[key]['python'] = '3.11.1'
                self.replace_manifest(kind, child, bind_child=True)
                self.refuse('bundle_manifest')

    def test_deployment_protected_claim_must_match_root_plan(self):
        child = self.manifest('bundle-deployment')
        child['protected'] = {'containers': ['different'], 'images': []}
        self.replace_manifest('bundle-deployment', child, bind_child=True)
        self.refuse('bundle_manifest')

    def test_deployment_cannot_add_an_untransferred_wal(self):
        child = self.manifest('bundle-deployment')
        child['files']['engine.db-wal'] = copy.deepcopy(child['files']['engine.db'])
        self.replace_manifest('bundle-deployment', child, bind_child=True)
        self.refuse('bundle_manifest')

    def test_source_manifest_raw_hash_binding_is_checked(self):
        original = self.payloads[self.path('bundle-deployment', 'source-manifest.json')]
        self.replace('bundle-deployment', 'source-manifest.json', original + b' ')
        self.refuse('source_manifest_hash')

    def test_source_manifest_claim_mismatch_is_rejected_even_if_raw_hash_bound(self):
        data = subject.canonical({'engine.db': {'size': len(self.raw['deployment']), 'sha256': 'e' * 64}})
        self.replace('bundle-deployment', 'source-manifest.json', data)
        child = self.manifest('bundle-deployment')
        child['source_manifest_sha256'] = subject.digest(data)
        self.replace_manifest('bundle-deployment', child, bind_child=True)
        self.refuse('source_manifest')

    def test_snapshot_source_owner_mode_size_and_links_are_strict(self):
        for key, value in (('uid', 0), ('gid', 0), ('mode', 0o644), ('links', 2), ('size', 1)):
            with self.subTest(key=key):
                self.plan, self.payloads, self.raw = make_fixture()
                child = self.manifest('bundle-snapshot')
                child['source_file'][key] = value
                self.replace_manifest('bundle-snapshot', child, bind_child=True)
                self.refuse('bundle_manifest')

    def test_compressed_row_hash_and_length_must_match_child(self):
        path = self.path('bundle-snapshot', 'snapshot.sqlite.gz')
        self.replace('bundle-snapshot', 'snapshot.sqlite.gz', self.payloads[path] + b'!')
        self.refuse()

    def test_each_compressed_payload_is_hashed_against_wire_plan(self):
        for kind, name in (('bundle-deployment', 'engine.db.gz'), ('bundle-snapshot', 'snapshot.sqlite.gz')):
            with self.subTest(kind=kind):
                self.plan, self.payloads, self.raw = make_fixture()
                path = self.path(kind, name)
                packed = bytearray(self.payloads[path])
                packed[4] ^= 1  # Valid gzip with different header, not matching the wire file hash.
                self.payloads[path] = bytes(packed)
                self.refuse('file_hash')

    def test_raw_payload_hash_mismatch_is_rejected_after_compressed_binding(self):
        changed = b'X' + self.raw['snapshot'][1:]
        self.replace_compressed('bundle-snapshot', gzip.compress(changed, compresslevel=6, mtime=0))
        self.refuse('gzip_hash')

    def test_raw_payload_length_overrun_is_rejected(self):
        self.replace_compressed('bundle-snapshot', gzip.compress(self.raw['snapshot'] + b'X', mtime=0))
        self.refuse('gzip_size')

    def test_gzip_truncation_trailing_and_concatenated_members_are_rejected(self):
        for change, code in ((lambda d: d[:-8], 'gzip_incomplete'),
                             (lambda d: d + b'x', 'gzip_trailing_data'),
                             (lambda d: d + gzip.compress(b'extra', mtime=0), 'gzip_trailing_data')):
            with self.subTest(code=code):
                self.plan, self.payloads, self.raw = make_fixture()
                data = self.payloads[self.path('bundle-snapshot', 'snapshot.sqlite.gz')]
                self.replace_compressed('bundle-snapshot', change(data))
                self.refuse(code)

    def test_duplicate_keys_and_nonfinite_manifest_values_are_rejected(self):
        for data in (b'{"plan":{},"plan":{}}', b'NaN'):
            with self.subTest(data=data):
                self.plan, self.payloads, self.raw = make_fixture()
                self.replace('bundle', 'archive-manifest.json', data)
                self.refuse()

    def test_wire_truncation_and_trailing_data_are_rejected(self):
        data = wire(self.plan, self.payloads)
        for bad, code in ((data[:-1], 'truncated_bundle'), (data + b'x', 'bundle_trailing_data')):
            with self.subTest(code=code), self.assertRaisesRegex(subject.Refused, code):
                self.verify(bad)

    def test_restore_creates_only_fixed_nested_compressed_files_with_private_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            result = subject.restore_bundle(io.BytesIO(wire(self.plan, self.payloads)), self.plan, root)
            self.assertEqual(result['files'], subject.file_rows(self.plan))
            found = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}
            self.assertEqual(found, self.payloads)
            for path in root.rglob('*'):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)
            self.assertFalse(any(path.name in ('engine.db', 'snapshot.sqlite') for path in root.rglob('*')))

    def test_restore_refuses_preexisting_or_nonprivate_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for mode, preexisting in ((0o755, False), (0o700, True)):
                root.chmod(mode)
                if preexisting:
                    (root / 'keep').write_bytes(b'existing')
                with self.subTest(mode=mode), self.assertRaisesRegex(subject.Refused, 'restore_directory'):
                    subject.restore_bundle(io.BytesIO(wire(self.plan, self.payloads)), self.plan, root)
            self.assertEqual((root / 'keep').read_bytes(), b'existing')

    def test_restore_invalid_nested_plan_does_not_create_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            self.plan['groups'][1]['files'][0]['name'] = '../archive-manifest.json'
            with self.assertRaises(subject.Refused):
                subject.restore_bundle(io.BytesIO(b''), self.plan, root)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
