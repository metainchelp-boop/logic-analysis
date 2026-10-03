#!/usr/bin/env python3
"""승인된 대표 검증판 소스·실행 자격을 목적 서버 공개 인증서로만 봉인한다.

원격 접속·설치·복호화 없음. 평문은 메모리와 OpenSSL 표준입력에만 존재하며,
새 출력 폴더에는 인증 암호문과 비밀값 없는 영수증만 쓴다. 암호화는 출처 인증이
아니므로 설치자는 별도로 승인한 GitHub 실행/커밋/암호문 지문을 확인해야 한다.
"""
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from naver_engine.credentials import load_manager_credentials
from naver_engine.erp_read import load_erp_key
from naver_engine.session import load_token_secret

OPENSSL = "/usr/bin/openssl"
BRANCH = "refs/heads/codex/naver-ad-account-matching-20261001"
ACCOUNT_FIRST_BRANCH = "refs/heads/codex/naver-account-first-20261002"
ACCOUNT_FIRST_COMMIT = "1b790b864ce27766251a205259fa6a332f60f72b"
# 승인된 관리 경로 생성 영수증 36806904207. 입력값으로 이 지문을 바꿀 수 없다.
SERVER_CERT_PEM_SHA256 = "8edff7ceaa6538bc91df7ebd1723bc6889dbebb232e1955d8dfa4131c4a5acc7"
MAX_BUNDLE = 2 * 1024 * 1024
SECRET_NAMES = (
    "SSO_NAVER_CONTROL_CLIENT_KEY", "NAVER_ENGINE_ERP_KEY", "NAVER_AUTO_TOKEN_SECRET",
    "NAVER_MGR_CUSTOMER_ID", "NAVER_MGR_API_KEY", "NAVER_MGR_SECRET_KEY",
    "NAVER_BACKUP_RECIPIENT_CERT_PEM", "NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY", "NAVER_BACKUP_KNOWN_HOSTS",
)
SOURCE_PATHS = (
    "naver_engine", "naver_runtime", "backend/requirements.txt", "backend/app/__init__.py",
    "backend/app/naver_auto", "backend/app/naver_relay.py", "backend/app/routers/__init__.py",
    "backend/app/routers/naver.py", "backend/naver_page", "backend/app/naver_entry.py",
    ".dockerignore", "Dockerfile.naver-engine", "Dockerfile.naver-engine.dockerignore",
    "Dockerfile.naver-relay", "Dockerfile.naver-relay.dockerignore", "compose.naver-engine.yml",
    "compose.naver-relay.yml", "deploy",
)
COMMAND_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "OPENSSL_CONF": "/dev/null"}
RUNTIME_FIXED = {
    "NAVER_ENGINE_DB": "/var/lib/naver-engine/engine.db",
    "NAVER_ENGINE_SOCKET": "/run/naver-engine/engine.sock",
    "NAVER_ENGINE_ERP_TUNNEL_SOCKET": "/run/naver-erp-tunnel/erp.sock",
    "NAVER_ENGINE_BACKUP_DIR": "/var/backups/naver-engine",
    "NAVER_BACKUP_CERT": "/run/secrets/naver-backup-recipient.pem",
    "NAVER_BACKUP_SSH_KEY": "/run/secrets/naver-backup-upload-key",
    "NAVER_BACKUP_KNOWN_HOSTS": "/run/secrets/naver-backup-known-hosts",
    **{"NAVER_ENGINE_" + flag + "_ENABLED": "true" for flag in ("SYNC", "LINKS", "MORNING", "WEB", "BACKUP")},
    **{"NAVER_ENGINE_" + flag + "_ENABLED": "false" for flag in ("ALERTS", "METRICS", "ISSUE_ALERTS")},
}


class SealError(ValueError):
    pass


def public_certificate(value):
    if (not isinstance(value, str) or not 0 < len(value.encode("utf-8")) <= 4096
            or not re.fullmatch(r"-----BEGIN CERTIFICATE-----\n[A-Za-z0-9+/=\n]+\n-----END CERTIFICATE-----\n?", value)):
        raise SealError("INVALID_PUBLIC_CERTIFICATE")
    cert = x509.load_pem_x509_certificate(value.encode("ascii"))
    key = cert.public_key()
    now = datetime.now(timezone.utc)
    if (not isinstance(key, rsa.RSAPublicKey) or not 2048 <= key.key_size <= 4096
            or not cert.not_valid_before_utc <= now < cert.not_valid_after_utc):
        raise SealError("INVALID_PUBLIC_CERTIFICATE")
    return cert, value.rstrip("\n") + "\n"


def runtime_files(env):
    forbidden = {"NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM", "VPS_SSH_KEY", "SSO_AD_CENTER_CLIENT_KEY"}
    if forbidden.intersection(env):
        raise SealError("UNEXPECTED_CREDENTIAL")
    values = {name: env.get(name, "") for name in SECRET_NAMES}
    for name in SECRET_NAMES[:6]:
        value = values[name]
        if not isinstance(value, str) or not re.fullmatch(r"[\x21-\x7e]{1,512}", value):
            raise SealError("INVALID_RUNTIME_CREDENTIAL")
    load_manager_credentials(values)
    load_erp_key(values)
    load_token_secret(values)
    if not re.fullmatch(r"[a-fA-F0-9]{64}", values["SSO_NAVER_CONTROL_CLIENT_KEY"]):
        raise SealError("INVALID_RUNTIME_CREDENTIAL")
    _, backup_cert = public_certificate(values["NAVER_BACKUP_RECIPIENT_CERT_PEM"])
    private = values["NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY"]
    if (not isinstance(private, str) or not 0 < len(private) <= 4096
            or not re.fullmatch(r"-----BEGIN OPENSSH PRIVATE KEY-----\n[A-Za-z0-9+/=\n]+\n-----END OPENSSH PRIVATE KEY-----\n?", private)):
        raise SealError("INVALID_UPLOAD_KEY")
    key = serialization.load_ssh_private_key(private.encode("ascii"), password=None)
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise SealError("INVALID_UPLOAD_KEY")
    hosts = values["NAVER_BACKUP_KNOWN_HOSTS"]
    # This is the already verified ECDSA host pin, not the Ed25519 upload identity.
    if not isinstance(hosts, str) or not re.fullmatch(r"api\.metainc\.co\.kr ecdsa-sha2-nistp256 [A-Za-z0-9+/]+={0,2}\n?", hosts):
        raise SealError("INVALID_BACKUP_HOST_KEY")
    public = serialization.load_ssh_public_key(" ".join(hosts.strip().split()[1:]).encode("ascii"))
    if not isinstance(public, ec.EllipticCurvePublicKey) or not isinstance(public.curve, ec.SECP256R1):
        raise SealError("INVALID_BACKUP_HOST_KEY")
    runtime = {**RUNTIME_FIXED, **{name: values[name] for name in SECRET_NAMES[:6]}}
    content = "".join(name + "=" + value + "\n" for name, value in runtime.items())
    folder = "/etc/metainc/naver-engine/"
    return [
        {"path": folder + "runtime.env", "mode": 0o600, "uid": 0, "gid": 0, "content": content},
        *({"path": folder + name, "mode": 0o600, "uid": 10001, "gid": 10001, "content": value}
          for name, value in (("backup-recipient.pem", backup_cert),
                              ("backup-upload-key", private.rstrip("\n") + "\n"),
                              ("backup-known-hosts", hosts.rstrip("\n") + "\n"))),
    ]


def source_archive(expected_commit, *, root=ROOT, checkout_commit=None):
    if not isinstance(expected_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise SealError("INVALID_SOURCE_COMMIT")
    checkout_commit = expected_commit if checkout_commit is None else checkout_commit
    if not isinstance(checkout_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", checkout_commit):
        raise SealError("INVALID_CHECKOUT_COMMIT")
    common = dict(cwd=root, env=COMMAND_ENV, capture_output=True, check=True, timeout=30)
    head = subprocess.run(["git", "rev-parse", "HEAD"], **common).stdout.decode("ascii").strip()
    if head != checkout_commit:
        raise SealError("SOURCE_COMMIT_MISMATCH")
    # New release tooling must archive the approved ancestor, never its newer HEAD.
    try:
        subprocess.run(["git", "merge-base", "--is-ancestor", expected_commit, checkout_commit], **common)
    except subprocess.CalledProcessError:
        raise SealError("SOURCE_NOT_IN_CHECKOUT_HISTORY") from None
    raw = subprocess.run(["git", "archive", "--format=tar", expected_commit, "--", *SOURCE_PATHS], **common).stdout
    if not 0 < len(raw) <= 8 * 1024 * 1024:
        raise SealError("SOURCE_TOO_LARGE")
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for entry in archive:
            name = entry.name.rstrip("/")
            if (name.startswith("/") or ".." in name.split("/") or not (entry.isfile() or entry.isdir())
                    or name in seen or not any(name == p or name.startswith(p + "/")
                        or (entry.isdir() and p.startswith(name + "/")) for p in SOURCE_PATHS)):
                raise SealError("UNSAFE_SOURCE_ARCHIVE")
            seen.add(name)
    if not set(SOURCE_PATHS) <= seen:
        raise SealError("MISSING_SOURCE_PATH")
    return gzip.compress(raw, mtime=0)


def new_file(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def seal_bundle(env, certificate, output, *, source_commit, source_tar_gz):
    cert, normalized = public_certificate(certificate)
    certificate_sha256 = hashlib.sha256(normalized.encode("ascii")).hexdigest()
    if certificate_sha256 != SERVER_CERT_PEM_SHA256:
        raise SealError("UNAPPROVED_SERVER_CERTIFICATE")
    files = runtime_files(env)
    if (not re.fullmatch(r"[0-9a-f]{40}", source_commit) or not isinstance(source_tar_gz, bytes)
            or not 0 < len(source_tar_gz) < MAX_BUNDLE):
        raise SealError("INVALID_SOURCE_ARCHIVE")
    payload = json.dumps({"schema": 1, "purpose": "naver-owner-verification-runtime", "files": files,
                          "source_commit": source_commit,
                          "source_tar_gz_b64": base64.b64encode(source_tar_gz).decode("ascii")},
                         ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(payload) >= MAX_BUNDLE - 4096:
        raise SealError("BUNDLE_TOO_LARGE")
    output = Path(output)
    if not output.is_absolute() or output != output.resolve() or output.exists() or output.is_symlink():
        raise SealError("UNSAFE_OUTPUT_PATH")
    info = output.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise SealError("UNSAFE_OUTPUT_PARENT")
    # 임시 파일에는 공개 인증서만. JSON·실행키·업로드 개인키는 디스크에 쓰지 않는다.
    with tempfile.TemporaryDirectory(prefix="preview-seal-public-", dir=output.parent) as temporary:
        public = Path(temporary) / "recipient.pem"
        new_file(public, normalized.encode("ascii"))
        encrypted = subprocess.run([OPENSSL, "cms", "-encrypt", "-binary", "-aes-256-gcm", "-stream",
            "-outform", "DER", "-recip", str(public), "-keyopt", "rsa_padding_mode:oaep",
            "-keyopt", "rsa_oaep_md:sha256", "-keyopt", "rsa_mgf1_md:sha256"], input=payload,
            capture_output=True, timeout=30, check=True, env=COMMAND_ENV).stdout
    if not 0 < len(encrypted) <= MAX_BUNDLE:
        raise SealError("CIPHERTEXT_TOO_LARGE")
    receipt = {"ciphertext_sha256": hashlib.sha256(encrypted).hexdigest(), "ciphertext_size": len(encrypted),
               "public_certificate_sha256": certificate_sha256,
               "source_commit": source_commit, "source_tar_gz_sha256": hashlib.sha256(source_tar_gz).hexdigest()}
    output.mkdir(mode=0o700)
    new_file(output / "runtime-secrets.cms", encrypted)
    new_file(output / "receipt.json", json.dumps(receipt, sort_keys=True).encode("ascii") + b"\n")
    return receipt


def validate_workflow_inputs(inputs):
    allowed = {"preview_seal", "server_envelope_cert_pem", "backup_acceptance", "received_synthetic_json"}
    # workflow_dispatch omits optional empty strings from inputs; absence is the same closed default.
    if (not isinstance(inputs, dict) or set(inputs) - allowed or inputs.get("preview_seal") is not True
            or inputs.get("backup_acceptance") != "none" or inputs.get("received_synthetic_json", "") != ""
            or not isinstance(inputs.get("server_envelope_cert_pem"), str)):
        raise SealError("INVALID_WORKFLOW_INPUTS")
    return inputs["server_envelope_cert_pem"]


def main():
    try:
        branch = os.environ.get("GITHUB_REF")
        if (len(sys.argv) != 1 or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
                or branch not in {BRANCH, ACCOUNT_FIRST_BRANCH}):
            raise SealError("INVALID_WORKFLOW_CONTEXT")
        inputs = json.loads(os.environ.get("PREVIEW_SEAL_INPUTS", "{}"))
        certificate = validate_workflow_inputs(inputs)
        source_commit = ACCOUNT_FIRST_COMMIT if branch == ACCOUNT_FIRST_BRANCH else os.environ.get("GITHUB_SHA", "")
        source = source_archive(source_commit, checkout_commit=os.environ.get("GITHUB_SHA", ""))
        receipt = seal_bundle(os.environ, certificate, os.environ.get("PREVIEW_SEAL_OUTPUT", ""),
                              source_commit=source_commit, source_tar_gz=source)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except SealError as error:
        # Only our fixed reason labels; never subprocess/cryptography messages or values.
        print("PREVIEW_SEAL_REFUSED:" + str(error), file=sys.stderr)
        return 1
    except Exception:
        print("PREVIEW_SEAL_REFUSED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
