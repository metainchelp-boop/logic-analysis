import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location('download', Path(__file__).parents[1] / 'tools/naver_preview_download.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class DownloadTest(unittest.TestCase):
    def package(self):
        encrypted=b'opaque ciphertext fixture'
        packet={'baseline':'a'*64,'source_commit':'b'*40,'source_tar_gz_sha256':'c'*64,
                'ciphertext_sha256':hashlib.sha256(encrypted).hexdigest()}
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as archive:
            archive.writestr('runtime-secrets.cms',encrypted)
            archive.writestr('receipt.json',json.dumps(packet))
        raw=out.getvalue()
        packet.update(download_url='https://productionresultssa7.blob.core.windows.net/synthetic/file?sig=synthetic',
                      artifact_sha256=hashlib.sha256(raw).hexdigest())
        return packet,raw,encrypted

    def test_only_exact_verified_ciphertext_is_written(self):
        packet,raw,encrypted=self.package()
        response=io.BytesIO(raw)
        response.status=200
        with tempfile.TemporaryDirectory() as folder, patch.object(M.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=response
            output=Path(folder)/'output'
            result=M.download(packet,output)
            self.assertEqual((output/'runtime-secrets.cms').read_bytes(),encrypted)
            self.assertNotIn('download_url',result)

    def test_wrong_host_digest_and_plain_artifact_are_never_written(self):
        for change in ({'download_url':'http://productionresultssa7.blob.core.windows.net/file'},
                       {'download_url':'https://example.com/file'}, {'artifact_sha256':'d'*64}):
            packet,raw,_=self.package()
            packet.update(change)
            response=io.BytesIO(raw);response.status=200
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder, patch.object(M.urllib.request,'build_opener') as opener:
                opener.return_value.open.return_value=response
                output=Path(folder)/'output'
                with self.assertRaises(ValueError): M.download(packet,output)
                self.assertFalse(output.exists())
