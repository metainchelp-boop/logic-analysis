import base64
import gzip
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('release', Path(__file__).parents[1] / 'tools/naver_preview_release.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def archive(name='naver_engine/web.py', kind=tarfile.REGTYPE):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as stream:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.size = 4 if kind == tarfile.REGTYPE else 0
        stream.addfile(member, io.BytesIO(b'test') if member.size else None)
    return out.getvalue()


class ReleaseTest(unittest.TestCase):
    def test_plain_regular_source_extracts_only_into_new_release(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'new'
            M.extract_source(archive(), path)
            self.assertEqual((path / 'naver_engine/web.py').read_bytes(), b'test')
            with self.assertRaises(FileExistsError):
                M.extract_source(archive(), path)

    def test_traversal_links_unknown_files_and_duplicates_are_rejected(self):
        for name, kind in (('../outside', tarfile.REGTYPE), ('/etc/passwd', tarfile.REGTYPE),
                           ('naver_engine/link', tarfile.SYMTYPE), ('README.md', tarfile.REGTYPE),
                           ('naver_engine/../../bad', tarfile.REGTYPE)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'new'
                with self.assertRaises(ValueError):
                    M.extract_source(archive(name, kind), path)
                self.assertFalse(path.exists())

    def test_manifest_rejects_source_mismatch_before_writing(self):
        with self.assertRaises(ValueError):
            M.validate_payload({'schema': 1}, 'a' * 40, 'b' * 64)

    def test_ciphertext_and_source_identifiers_are_fixed_shape(self):
        good = {'baseline': 'a'*64, 'source_commit':'b'*40, 'ciphertext_sha256':'c'*64,
                'source_tar_gz_sha256':'d'*64, 'run_id':'123456', 'operation':'prepare'}
        self.assertEqual(M.validate_package(good), good)
        for key in ('baseline','source_commit','ciphertext_sha256','source_tar_gz_sha256','run_id','operation'):
            value = dict(good, **{key:'../wrong'})
            with self.assertRaises(ValueError):
                M.validate_package(value)

    def test_failed_private_probe_stops_only_the_new_services(self):
        package={'baseline':'a'*64,'source_commit':'b'*40,'ciphertext_sha256':'c'*64,
                 'source_tar_gz_sha256':'d'*64,'run_id':'123456','operation':'start'}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'receipts').mkdir()
            (root/'receipts'/('preview-'+package['source_commit']+'.json')).write_text(
                '{"ok":true,"stage":"prepared","source_commit":"'+package['source_commit']+'"}')
            calls=[]
            def process(args,**kwargs):
                calls.append(args)
                return (package['source_commit']+'\n').encode() if args[:3]==['docker','image','inspect'] else b''
            host=Mock();host.baseline.return_value=package['baseline']
            with patch.object(M,'ROOT',root),patch.object(M.os,'geteuid',return_value=0), \
                 patch.object(M.subprocess,'run') as run,patch.object(M.time,'sleep'), \
                 patch.object(M.time,'monotonic',side_effect=[0,46]), \
                 patch.object(M.socket.socket,'connect',side_effect=OSError('synthetic unavailable')):
                def execute(args,**kwargs):
                    return subprocess.CompletedProcess(args,0,process(args),b'')
                import subprocess
                run.side_effect=execute
                with self.assertRaisesRegex(ValueError,'ENGINE_NOT_READY'):
                    M.start(package,host)
            stops=[args for args in calls if 'stop' in args]
            self.assertEqual(len(stops),2)
            self.assertEqual({args[3] for args in stops},{'naver-engine','naver-relay'})
            self.assertTrue(all('ad-api' not in args and 'down' not in args for args in calls))
