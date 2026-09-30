"""S14 OS 관문. 고정 OpenSSL 암호화와 회사 수신 서버 SSH 표준입력만 허용한다.

복호화키를 받는 인자/환경값은 없다. 공개 인증서와 업로드 전용 SSH 키는 별개이다.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import threading

from naver_engine.backup import BackupError, MAX_BYTES, file_digest, private_file

OPENSSL = "/usr/bin/openssl"
SSH = "/usr/bin/ssh"
RECEIVER = "naver-backup@api.metainc.co.kr"
COMMAND_ENV = {"PATH": "/usr/bin:/bin", "OPENSSL_CONF": "/dev/null"}


def _config_file(path, *, secret=False):
    p = pathlib.Path(path)
    if not p.is_absolute() or p != p.resolve():
        raise BackupError("UNSAFE_CONFIG_FILE")
    s = p.lstat()
    forbidden = 0o077 if secret else 0o022
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_mode & forbidden:
        raise BackupError("UNSAFE_CONFIG_FILE")
    return p


class OpenSslEncryptor:
    """CMS AuthEnvelopedData(AES-256-GCM), RSA-OAEP SHA-256로 공개 인증서에만 잠근다."""
    def __init__(self, recipient_certificate):
        self.certificate = _config_file(recipient_certificate)
        body = self.certificate.read_bytes()
        if b"-----BEGIN CERTIFICATE-----" not in body or b"PRIVATE KEY" in body:
            raise BackupError("PUBLIC_CERTIFICATE_REQUIRED")

    def __call__(self, source, destination):
        path = private_file(source)
        target = pathlib.Path(destination)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                subprocess.run([OPENSSL, "cms", "-encrypt", "-binary", "-aes-256-gcm", "-stream",
                                "-outform", "DER", "-in", str(path), "-recip", str(self.certificate),
                                "-keyopt", "rsa_padding_mode:oaep", "-keyopt", "rsa_oaep_md:sha256",
                                "-keyopt", "rsa_mgf1_md:sha256"],
                               stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                               env=COMMAND_ENV, shell=False, check=True, timeout=120)
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            target.unlink(missing_ok=True)
            raise BackupError("ENCRYPTION_FAILED") from None


class SshSender:
    """강제 명령 계정에 프레임만 전달한다. 원격 경로·명령·호스트를 입력받지 않는다."""
    def __init__(self, identity_file, known_hosts):
        self.identity = _config_file(identity_file, secret=True)
        self.known_hosts = _config_file(known_hosts)

    def __call__(self, ciphertext):
        path = private_file(ciphertext)
        size = path.stat().st_size
        if not 0 < size <= MAX_BYTES:
            raise BackupError("INVALID_UPLOAD_SIZE")
        header = {"version": 1, "size": size, "sha256": file_digest(path)}
        try:
            # /tmp는 컨테이너에서 64 MiB이다. 큰 암호문 프레임은 백업 전용 볼륨 안
            # 이름 없는 600 파일에 두며, 성공/실패와 관계없이 닫을 때 사라진다.
            with tempfile.TemporaryFile(dir=path.parent) as framed, path.open("rb") as source:
                framed.write(json.dumps(header, sort_keys=True).encode("ascii") + b"\n")
                shutil.copyfileobj(source, framed)
                framed.seek(0)
                reply = _ssh_reply([SSH, "-F", "/dev/null", "-T", "-o", "BatchMode=yes",
                                        "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
                                        "-o", "UserKnownHostsFile=" + str(self.known_hosts),
                                        "-o", "GlobalKnownHostsFile=/dev/null", "-o", "ConnectTimeout=10",
                                        "-o", "ConnectionAttempts=1", "-o", "ServerAliveInterval=15",
                                        "-o", "ServerAliveCountMax=2", "-o", "ClearAllForwardings=yes",
                                        "-o", "PermitLocalCommand=no", "-i", str(self.identity), RECEIVER], framed)
            return json.loads(reply)
        except Exception:
            raise BackupError("UPLOAD_FAILED") from None


def _ssh_reply(command, framed):
    """stdout 2048바이트 초과는 읽는 즉시 중단. stderr는 저장/노출하지 않는다."""
    process = subprocess.Popen(command, stdin=framed, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env=COMMAND_ENV, shell=False)
    replies = []
    def read_reply():
        try:
            reply = process.stdout.read(2049)
            replies.append(reply)
            if len(reply) > 2048:
                process.kill()
        except OSError:
            replies.append(b"")
    reader = threading.Thread(target=read_reply, daemon=True, name="backup-receipt")
    reader.start()
    try:
        result = process.wait(timeout=300)
    except BaseException:
        process.kill()
        process.wait(timeout=5)
        raise
    finally:
        reader.join(5)
        process.stdout.close()
    if result != 0 or not replies or not 0 < len(replies[0]) <= 2048:
        raise BackupError("INVALID_RECEIPT")
    return replies[0]
