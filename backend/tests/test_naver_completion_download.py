"""Synthetic encrypted transfer boundaries; no network or credentials."""
import hashlib,io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch,Mock
import naver_completion_download as D

class CompletionDownloadTests(unittest.TestCase):
    def fixture(self,cipher=b'synthetic-cipher',receipt_extra=None,extra=None):
        p=dict(baseline='a'*64,source_commit='b'*40,ciphertext_sha256=hashlib.sha256(cipher).hexdigest(),source_tar_gz_sha256='c'*64,download_url='https://productionresultssa1.blob.core.windows.net/fake?token=synthetic')
        receipt={k:p[k] for k in ('source_commit','source_tar_gz_sha256','ciphertext_sha256')};receipt.update(public_certificate_sha256='d'*64,ciphertext_size=len(cipher));receipt.update(receipt_extra or {})
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:
            z.writestr('runtime-secrets.cms',cipher);z.writestr('receipt.json',json.dumps(receipt))
            if extra:z.writestr(*extra)
        body=buf.getvalue();p['artifact_sha256']=hashlib.sha256(body).hexdigest();return p,body
    def receive(self,p,body,path):
        response=Mock();response.status=200;response.read.return_value=body;response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=response
        with patch.object(D.urllib.request,'build_opener',return_value=opener):
            result=D.download(p,path)
        response.read.assert_called_once_with(D.MAX_ZIP+1);return result
    def test_new_only_cipher_above_old_two_mib_bound_roundtrips(self):
        p,body=self.fixture(b'x'*(2*1024*1024+1))
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'cipher';r=self.receive(p,body,out)
            self.assertEqual(r['source_commit'],p['source_commit']);self.assertEqual((out/'runtime-secrets.cms').stat().st_mode&0o777,0o600);self.assertEqual(out.stat().st_mode&0o777,0o700)
    def test_oversize_or_foreign_receipt_and_extra_archive_entry_refuse_before_write(self):
        for args in ((b'x'*(D.MAX_CIPHER+1),None,None),(b'x',{'ciphertext_size':True},None),(b'x',None,('other','x'))):
            p,body=self.fixture(*args)
            with tempfile.TemporaryDirectory() as folder:
                out=Path(folder)/'cipher'
                with self.assertRaises(ValueError):self.receive(p,body,out)
                self.assertFalse(out.exists())
    def test_foreign_host_and_existing_output_never_request(self):
        p,body=self.fixture()
        with tempfile.TemporaryDirectory() as folder,patch.object(D.urllib.request,'build_opener') as network:
            with self.assertRaises(ValueError):D.download(p,Path(folder))
            p['download_url']='https://example.com/fake?token=synthetic'
            with self.assertRaises(ValueError):D.download(p,Path(folder)/'new')
            network.assert_not_called()

if __name__=='__main__':unittest.main()
