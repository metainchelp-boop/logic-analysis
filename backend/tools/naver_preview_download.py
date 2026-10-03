"""Receive a short-lived GitHub ciphertext artifact, never plaintext or credentials."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request
import zipfile


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def download(package, output):
    fields={'baseline','source_commit','ciphertext_sha256','source_tar_gz_sha256','download_url','artifact_sha256'}
    if not isinstance(package,dict) or set(package)!=fields:
        raise ValueError('INPUT_FIELDS')
    for key in fields-{'download_url'}:
        if not isinstance(package[key],str) or not re.fullmatch('[0-9a-f]{40}' if key=='source_commit' else '[0-9a-f]{64}',package[key]):
            raise ValueError('INPUT_DIGEST')
    url=package['download_url']
    if not isinstance(url,str) or not 0<len(url)<=8192:
        raise ValueError('INPUT_URL')
    parsed=urllib.parse.urlsplit(url)
    if (parsed.scheme!='https' or not re.fullmatch(r'productionresultssa[0-9]+\.blob\.core\.windows\.net',parsed.hostname or '')
            or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.fragment):
        raise ValueError('DOWNLOAD_HOST')
    with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect).open(url,timeout=20) as response:
        if response.status!=200:
            raise ValueError('DOWNLOAD_STATUS')
        body=response.read(3*1024*1024+1)
    if len(body)>3*1024*1024 or hashlib.sha256(body).hexdigest()!=package['artifact_sha256']:
        raise ValueError('ARTIFACT_HASH')
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names=archive.namelist()
        if set(names)!={'runtime-secrets.cms','receipt.json'} or len(names)!=2:
            raise ValueError('ARTIFACT_FILES')
        if any(item.file_size>2*1024*1024 for item in archive.infolist()):
            raise ValueError('ARTIFACT_SIZE')
        encrypted=archive.read('runtime-secrets.cms')
        receipt=json.loads(archive.read('receipt.json'))
    if not 0<len(encrypted)<=2*1024*1024 or hashlib.sha256(encrypted).hexdigest()!=package['ciphertext_sha256']:
        raise ValueError('CIPHERTEXT_HASH')
    for key in ('source_commit','ciphertext_sha256','source_tar_gz_sha256'):
        if receipt.get(key)!=package[key]:
            raise ValueError('RECEIPT_MISMATCH')
    output=Path(output)
    output.mkdir(mode=0o700)
    with (output/'runtime-secrets.cms').open('xb') as stream:
        stream.write(encrypted)
    (output/'runtime-secrets.cms').chmod(0o600)
    return {key:package[key] for key in ('baseline','source_commit','ciphertext_sha256','source_tar_gz_sha256')}
