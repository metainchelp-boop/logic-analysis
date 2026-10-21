"""Pure attacks against test-fixture decoding; synthetic archive pins only."""
import ast
import copy
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('_daily_current_fixture_v3_attacks', HERE / 'source_fixture.py')
SF = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SF)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


class FixtureBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical_raw = (SF.ASSETS / 'canonical-source.json').read_bytes()
        cls.packed = (SF.ASSETS / 'source-4d.tar.gz').read_bytes()
        cls.canonical, cls.bodies = SF.validate_bundle(cls.canonical_raw, cls.packed)

    def synthetic(self, mutate=None, *, global_pax=None, trailing=b''):
        bodies = {f'naver_engine/fixture_{i:03}.py': b'pass\n' for i in range(163)}
        canonical = copy.deepcopy(self.canonical)
        canonical['files'] = {name: {'mode': 0o644, 'bytes': len(body), 'sha256': SF.digest(body)}
            for name, body in bodies.items()}
        members = [('naver_engine', tarfile.DIRTYPE, 0o775, b'', '')]
        members.extend((name, tarfile.REGTYPE, 0o664, body, '') for name, body in bodies.items())
        if mutate:
            mutate(canonical, members)
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w', format=tarfile.PAX_FORMAT,
                pax_headers={'comment': SF.SOURCE} if global_pax is None else global_pax) as archive:
            for name, kind, mode, body, link in members:
                info = tarfile.TarInfo(name)
                info.type, info.mode, info.size, info.linkname = kind, mode, len(body), link
                archive.addfile(info, io.BytesIO(body) if kind == tarfile.REGTYPE else None)
        raw = stream.getvalue() + trailing
        packed = gzip.compress(raw, mtime=0)
        canonical.update(raw_bytes=len(raw), raw_sha256=SF.digest(raw),
            gzip_bytes=len(packed), gzip_sha256=SF.digest(packed))
        return encoded(canonical), packed, raw

    def pins(self, canonical_raw, packed, raw):
        return patch.multiple(SF, CANONICAL_SHA=SF.digest(canonical_raw), ARCHIVE_SHA=SF.digest(packed),
            ARCHIVE_BYTES=len(packed), RAW_SHA=SF.digest(raw), RAW_BYTES=len(raw))

    def test_actual_native_canonical_archive_and_frozen_seven_files_are_exact(self):
        self.assertEqual(SF.CANONICAL_SHA, 'b1ce7e10044552e9d50427ba15f1e201836d88747fd0d16476a917cf72dab5c8')
        self.assertEqual(SF.ARCHIVE_SHA, '1db45b8e54e562bd83c12b4cf53c791426ea45fccd85162bfb0e5f27179873fe')
        self.assertEqual(SF.RAW_SHA, '574ae4183d89b2059104f788ed75524507cf5cacd7c653dc4518ebd54e37c43d')
        self.assertEqual((len(self.bodies), len(self.packed), SF.RAW_BYTES), (163, 2131064, 5519360))
        frozen = SF.frozen_bytes()
        self.assertEqual(len(frozen), 7)
        tree = ast.parse(frozen['test_reader.py'])
        methods = [node.name for owner in tree.body if isinstance(owner, ast.ClassDef)
            and owner.name == 'ReaderTests' for node in owner.body if isinstance(node, ast.FunctionDef)
            and node.name.startswith('test_')]
        self.assertEqual((len(methods), len(set(methods))), (45, 45))

    def test_canonical_and_gzip_digests_are_authenticated_before_tar_or_bodies(self):
        with patch.object(SF.tarfile, 'open') as opening:
            for canonical_raw, packed in ((self.canonical_raw + b' ', self.packed),
                    (self.canonical_raw, self.packed[:-1] + b'X')):
                with self.assertRaisesRegex(ValueError, 'D3_FIXTURE_REFUSED'):
                    SF.validate_bundle(canonical_raw, packed)
            opening.assert_not_called()

    def test_duplicate_json_and_nonfinite_values_refuse_without_normalizing(self):
        for body in (b'{"same":1,"same":1}', b'{"number":NaN}', b'{"number":Infinity}'):
            with self.assertRaisesRegex(ValueError, 'D3_FIXTURE_REFUSED'):
                SF.strict_json(body)

    def test_missing_file_count_schema_and_forbidden_canonical_paths_refuse(self):
        for mode in ('count', 'source', 'row_bool', 'oversize', 'forbidden'):
            def mutate(canonical, members):
                first = next(iter(canonical['files']))
                if mode == 'count':
                    canonical['files'].pop(first)
                elif mode == 'source':
                    canonical['source_commit'] = '0' * 40
                elif mode == 'row_bool':
                    canonical['files'][first]['mode'] = True
                elif mode == 'oversize':
                    canonical['files'][first]['bytes'] = SF.MAX_FILE + 1
                else:
                    canonical['files']['naver_engine/store 2.py'] = canonical['files'].pop(first)
            c, g, raw = self.synthetic(mutate)
            with self.subTest(mode=mode), self.pins(c, g, raw), patch.object(SF.tarfile, 'open') as opening:
                with self.assertRaisesRegex(ValueError, 'D3_FIXTURE_REFUSED'):
                    SF.validate_bundle(c, g)
                opening.assert_not_called()

    def test_all_tar_headers_are_checked_before_any_member_body_reads(self):
        for mode in ('symlink', 'hardlink', 'traversal', 'absolute', 'duplicate', 'forbidden',
                'unknown', 'directory', 'mode', 'size', 'missing', 'missing_directory'):
            def mutate(canonical, members):
                name, kind, perm, body, link = members[1]
                if mode in ('symlink', 'hardlink'):
                    members[1] = (name, tarfile.SYMTYPE if mode == 'symlink' else tarfile.LNKTYPE, perm, b'', 'outside')
                elif mode in ('traversal', 'absolute', 'forbidden', 'unknown'):
                    changed = {'traversal': '../outside', 'absolute': '/outside',
                        'forbidden': 'naver_engine/HANDOVER.md', 'unknown': 'naver_engine/not_in_manifest.py'}[mode]
                    members[1] = (changed, kind, perm, body, link)
                elif mode == 'duplicate':
                    members[-1] = members[1]
                elif mode == 'directory':
                    members[0] = ('outside', tarfile.DIRTYPE, 0o775, b'', '')
                elif mode == 'mode':
                    members[1] = (name, kind, 0o666, body, link)
                elif mode == 'size':
                    members[1] = (name, kind, perm, b'x', link)
                elif mode == 'missing':
                    members.pop()
                else:
                    members.pop(0)
            c, g, raw = self.synthetic(mutate)
            with self.subTest(mode=mode), self.pins(c, g, raw), patch.object(SF.tarfile.TarFile, 'extractfile') as read:
                with self.assertRaisesRegex(ValueError, 'D3_FIXTURE_REFUSED'):
                    SF.validate_bundle(c, g)
                read.assert_not_called()

    def test_valid_shape_wrong_file_digest_refuses_before_extraction(self):
        def mutate(canonical, members):
            first = next(iter(canonical['files']))
            canonical['files'][first]['sha256'] = '0' * 64
        c, g, raw = self.synthetic(mutate)
        with self.pins(c, g, raw), self.assertRaisesRegex(ValueError, 'D3_FIXTURE_REFUSED'):
            SF.validate_bundle(c, g)

    def test_extra_gzip_member_tar_trailing_bytes_and_wrong_pax_refuse(self):
        for mode in ('gzip_member', 'trailing', 'pax'):
            c, g, raw = self.synthetic(global_pax={'comment': '0' * 40} if mode == 'pax' else None,
                trailing=b'NOT_TAR_PADDING' if mode == 'trailing' else b'')
            if mode == 'gzip_member':
                g += gzip.compress(b'SECOND_MEMBER', mtime=0)
                value = json.loads(c)
                value.update(gzip_bytes=len(g), gzip_sha256=SF.digest(g))
                c = encoded(value)
            with self.subTest(mode=mode), self.pins(c, g, raw), self.assertRaisesRegex(ValueError, 'D3_FIXTURE_REFUSED'):
                SF.validate_bundle(c, g)

    def test_gzip_expansion_is_bounded_even_when_synthetic_packed_hash_matches(self):
        value = copy.deepcopy(self.canonical)
        raw = b'x' * (SF.MAX_RAW + 4096)
        packed = gzip.compress(raw, mtime=0)
        value.update(raw_bytes=SF.MAX_RAW, raw_sha256=SF.digest(raw),
            gzip_bytes=len(packed), gzip_sha256=SF.digest(packed))
        c = encoded(value)
        with self.pins(c, packed, raw), patch.object(SF, 'RAW_BYTES', SF.MAX_RAW), \
                patch.object(SF.tarfile, 'open') as opening:
            with self.assertRaisesRegex(ValueError, 'D3_FIXTURE_REFUSED'):
                SF.validate_bundle(c, packed)
            opening.assert_not_called()

    def test_extracts_only_new_private_temp_with_canonical_modes_and_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / 'source4d'
            self.assertEqual(SF.extract_source(root), root)
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            actual = {str(p.relative_to(root)): p for p in root.rglob('*') if p.is_file()}
            self.assertEqual(set(actual), set(self.canonical['files']))
            for name, path in actual.items():
                SF.allowed_name(name)
                row = self.canonical['files'][name]
                self.assertEqual((stat.S_IMODE(path.stat().st_mode), path.stat().st_size, SF.digest(path.read_bytes())),
                    (row['mode'], row['bytes'], row['sha256']))

    def test_existing_directory_and_symlink_targets_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve()
            root = parent / 'existing'
            root.mkdir()
            sentinel = root / 'sentinel'
            sentinel.write_bytes(b'PRESERVE')
            alias = parent / 'alias'
            alias.symlink_to(root, target_is_directory=True)
            for destination in (root, alias):
                with self.assertRaisesRegex(ValueError, 'D3_FIXTURE_REFUSED'):
                    SF.extract_source(destination)
            self.assertEqual(sentinel.read_bytes(), b'PRESERVE')

    def test_asset_reader_rejects_symlink_fifo_and_oversize_without_following(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            file = root / 'bounded'
            file.write_bytes(b'abc')
            self.assertEqual(SF.checked_file(file, 3), b'abc')
            alias = root / 'alias'
            alias.symlink_to(file)
            fifo = root / 'fifo'
            os.mkfifo(fifo, 0o600)
            for path, cap in ((file, 2), (alias, 3), (fifo, 3)):
                with self.assertRaisesRegex(ValueError, 'D3_FIXTURE_REFUSED'):
                    SF.checked_file(path, cap)

    def test_midwrite_failure_removes_only_its_owned_new_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve()
            sentinel = parent / 'sentinel'
            sentinel.write_bytes(b'PRESERVE')
            root = parent / 'new'
            original_open = SF.os.open
            attempts = []
            def deny_write(path, flags, *args, **kwargs):
                if flags & os.O_WRONLY and str(path).startswith(str(root) + os.sep):
                    attempts.append(root.is_dir())
                    raise OSError('SYNTHETIC_WRITE_DENIAL')
                return original_open(path, flags, *args, **kwargs)
            with patch.object(SF, 'read_bundle', return_value=(self.canonical, self.bodies)), \
                    patch.object(SF.os, 'open', side_effect=deny_write):
                with self.assertRaises(OSError):
                    SF.extract_source(root)
            self.assertEqual(attempts, [True])
            self.assertFalse(root.exists())
            self.assertEqual(sentinel.read_bytes(), b'PRESERVE')
