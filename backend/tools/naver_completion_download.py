"""Bounded ciphertext-only download for the reviewed completion release."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import urllib.parse
import urllib.request
import zipfile

MAX_CIPHER=3*1024*1024
MAX_ZIP=4*1024*1024

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):return None

def unique(pairs):
    out={}
    for key,value in pairs:
        if key in out:raise ValueError('RECEIPT_DUPLICATE')
        out[key]=value
    return out

def download(package,output):
    fields={'baseline','source_commit','ciphertext_sha256','source_tar_gz_sha256','download_url','artifact_sha256'}
    if type(package) is not dict or set(package)!=fields:raise ValueError('INPUT_FIELDS')
    for key in fields-{'download_url'}:
        if type(package[key]) is not str or not re.fullmatch('[0-9a-f]{40}' if key=='source_commit' else '[0-9a-f]{64}',package[key]):raise ValueError('INPUT_DIGEST')
    url=package['download_url']
    if type(url) is not str or not 0<len(url)<=8192 or re.search(r'[\s\x00-\x1f\x7f]',url):raise ValueError('INPUT_URL')
    u=urllib.parse.urlsplit(url)
    if u.scheme!='https' or not re.fullmatch(r'productionresultssa[0-9]+\.blob\.core\.windows\.net',u.hostname or '') or u.username or u.password or u.port not in (None,443) or not u.path.startswith('/') or not u.query or u.fragment:raise ValueError('DOWNLOAD_HOST')
    output=Path(output)
    if output.exists() or output.is_symlink():raise ValueError('OUTPUT_EXISTS')
    with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect).open(url,timeout=20) as response:
        if response.status!=200:raise ValueError('DOWNLOAD_STATUS')
        body=response.read(MAX_ZIP+1)
    if not 0<len(body)<=MAX_ZIP or hashlib.sha256(body).hexdigest()!=package['artifact_sha256']:raise ValueError('ARTIFACT_HASH')
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        entries=archive.infolist()
        if len(entries)!=2 or {e.filename for e in entries}!={'runtime-secrets.cms','receipt.json'}:raise ValueError('ARTIFACT_FILES')
        if any(e.is_dir() or stat.S_IFMT(e.external_attr>>16) not in (0,stat.S_IFREG) or e.flag_bits&1 for e in entries):raise ValueError('ARTIFACT_TYPE')
        if not 0<archive.getinfo('runtime-secrets.cms').file_size<=MAX_CIPHER or not 0<archive.getinfo('receipt.json').file_size<=16384:raise ValueError('ARTIFACT_SIZE')
        encrypted=archive.read('runtime-secrets.cms');receipt=json.loads(archive.read('receipt.json'),object_pairs_hook=unique)
    if not 0<len(encrypted)<=MAX_CIPHER or hashlib.sha256(encrypted).hexdigest()!=package['ciphertext_sha256']:raise ValueError('CIPHERTEXT_HASH')
    if type(receipt) is not dict or set(receipt)!={'source_commit','source_tar_gz_sha256','public_certificate_sha256','ciphertext_sha256','ciphertext_size'}:raise ValueError('RECEIPT_FIELDS')
    if type(receipt['ciphertext_size']) is not int or receipt['ciphertext_size']!=len(encrypted) or not re.fullmatch('[0-9a-f]{64}',receipt['public_certificate_sha256']):raise ValueError('RECEIPT_SIZE')
    if any(receipt[k]!=package[k] for k in ('source_commit','source_tar_gz_sha256','ciphertext_sha256')):raise ValueError('RECEIPT_MISMATCH')
    output.mkdir(mode=0o700)
    fd=os.open(output/'runtime-secrets.cms',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(encrypted)
    return {key:package[key] for key in ('baseline','source_commit','ciphertext_sha256','source_tar_gz_sha256')}
