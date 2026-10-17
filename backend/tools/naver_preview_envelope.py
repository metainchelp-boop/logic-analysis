"""New-only deployment envelope; its private key never leaves the destination host."""
import hashlib
import os
from pathlib import Path
import stat
import subprocess


def create_envelope(folder):
    folder = Path(folder)
    # mkdir is intentionally exclusive; interrupted attempts require inspection, not replacement.
    folder.mkdir(mode=0o700)
    private = folder / 'private.pem'
    certificate = folder / 'recipient.pem'
    previous = os.umask(0o077)
    try:
        result = subprocess.run(['openssl', 'req', '-new', '-x509', '-newkey', 'rsa:4096',
            '-nodes', '-days', '30', '-subj', '/CN=metainc-naver-deploy-envelope',
            '-keyout', str(private), '-out', str(certificate)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
        if result.returncode:
            raise RuntimeError('ENVELOPE_GENERATION_FAILED')
    finally:
        os.umask(previous)
    for path in (private, certificate):
        value = path.lstat()
        if (not stat.S_ISREG(value.st_mode) or value.st_nlink != 1
                or value.st_uid != os.geteuid() or stat.S_IMODE(value.st_mode) != 0o600):
            raise RuntimeError('ENVELOPE_PERMISSIONS')
    body = certificate.read_bytes()
    if not 0 < len(body) <= 4096 or not body.startswith(b'-----BEGIN CERTIFICATE-----\n'):
        raise RuntimeError('ENVELOPE_CERTIFICATE')
    return {'certificate_pem': body.decode('ascii'),
            'certificate_sha256': hashlib.sha256(body).hexdigest(), 'private_key_exported': False}
