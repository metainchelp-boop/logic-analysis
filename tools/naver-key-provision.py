#!/usr/bin/env python3
"""승인된 신규 키만 발급한다. 기존 값 조회/교체, 서버 변경, 앱 실행은 하지 않는다.

기본 실행은 이름/보관 권한만 확인한다. --provision은 운영 변경이다.
키는 메모리에서 생성해 gh의 표준입력으로만 전달하며 오류에도 값을 출력하지 않는다.
중간 실패 시 이미 보관한 이름만 영수증에 남기고 중단한다. 자동 재발급/덮어쓰기 없음.
"""
import argparse
import fcntl
import hashlib
import json
import os
import pathlib
import re
import secrets
import subprocess
import stat
import sys
import tempfile
from datetime import datetime, timedelta, timezone

AD = "metainchelp-boop/metainc-ad-dashboard"
BE = "metainchelp-boop/metainc-web-backend"
LOGIC = "metainchelp-boop/logic-analysis"
RECOVERY = "naver-backup-recovery"
BRANCH = "codex/naver-backup-recovery-20261001"
PRIVATE = "NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM"
NAMES = {
    (AD, None): ["SSO_AD_CENTER_CLIENT_KEY", "SSO_NAVER_CONTROL_CLIENT_KEY",
                 "NAVER_ENGINE_ERP_KEY", "NAVER_AUTO_TOKEN_SECRET",
                 "NAVER_BACKUP_RECIPIENT_CERT_PEM", "NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY",
                 "NAVER_BACKUP_KNOWN_HOSTS"],
    (BE, None): ["SSO_AD_CENTER_KEY_SHA256", "SSO_LOGIC_ANALYSIS_KEY_SHA256",
                 "SSO_NAVER_CONTROL_KEY_SHA256", "NAVER_ENGINE_KEY_SHA256",
                 "NAVER_BACKUP_UPLOAD_SSH_PUBLIC_KEY"],
    (LOGIC, None): ["SSO_EXCHANGE_CLIENT_KEY"],
    (AD, RECOVERY): [PRIVATE],
}


def gh(*arguments, body=None):
    result = subprocess.run(["gh", *arguments], input=body, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError("GITHUB_OPERATION_FAILED")
    return result.stdout


def api(path):
    return json.loads(gh("api", "-H", "Cache-Control: no-cache", path))


def names(repo, environment):
    args = ["secret", "list", "-R", repo, "--json", "name"]
    if environment:
        args += ["--env", environment]
    return {item["name"] for item in json.loads(gh(*args))}


def preflight():
    for repo in (AD, BE, LOGIC):
        metadata = api("repos/" + repo)
        # 로직 저장소는 공개 저장소이지만 승인된 Actions Secret 보관 위치다.
        # 공개 코드와 암호화된 Secret은 다르다. 현재 유일한 관리 계정을 별도 확인한다.
        if (repo != LOGIC and metadata.get("private") is not True) or metadata.get("permissions", {}).get("admin") is not True:
            raise RuntimeError("REPOSITORY_CUSTODY_NOT_CONFIRMED")
        collaborators = api(f"repos/{repo}/collaborators?affiliation=all&per_page=100")
        # BE에는 지문/공개키만 저장한다. 확인된 기존 개발자 쓰기 권한은 변경하지 않는다.
        expected_collaborators = [("metainchelp-boop", "admin")]
        if repo == BE:
            expected_collaborators.append(("jjhud1000-bit", "write"))
        if sorted((c["login"], c["role_name"]) for c in collaborators) != sorted(expected_collaborators):
            raise RuntimeError("REPOSITORY_CUSTODIAN_CHANGED")
    environment = api(f"repos/{AD}/environments/{RECOVERY}")
    if environment.get("deployment_branch_policy") != {
            "protected_branches": False, "custom_branch_policies": True}:
        raise RuntimeError("RECOVERY_NOT_SEPARATED")
    policies = api(f"repos/{AD}/environments/{RECOVERY}/deployment-branch-policies")["branch_policies"]
    if [(p["name"], p["type"]) for p in policies] != [(BRANCH, "branch")]:
        raise RuntimeError("RECOVERY_BRANCH_NOT_EXCLUSIVE")
    for (repo, environment), requested in NAMES.items():
        if names(repo, environment).intersection(requested):
            raise RuntimeError("SECRET_NAME_ALREADY_EXISTS")


def write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def provision(output, known_hosts):
    # 같은 사용자의 도구 동시 실행만 차단한다. GitHub 외부 관리자의 동시 쓰기를
    # 원자적으로 차단하는 기능은 아니다. 기존 이름을 매 저장 직전에 다시 조회한다.
    lock = pathlib.Path(tempfile.gettempdir()) / ("metainc-naver-key-provision-" + str(os.geteuid()) + ".lock")
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() \
                or metadata.st_nlink != 1 or metadata.st_mode & 0o077:
            raise RuntimeError("UNSAFE_PROVISION_LOCK")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _provision_unlocked(output, known_hosts)
    finally:
        os.close(fd)


def _provision_unlocked(output, known_hosts):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
    from cryptography.x509.oid import NameOID

    # 공개 호스트키는 기존 관리 접속으로 읽은 값만 받는다. TOFU/keyscan 사용 없음.
    host_line = known_hosts.read_text().strip()
    parts = host_line.split()
    if len(parts) != 3 or parts[:2] != ["api.metainc.co.kr", "ssh-ed25519"]:
        raise RuntimeError("INVALID_PINNED_HOST_KEY")
    if not isinstance(serialization.load_ssh_public_key(" ".join(parts[1:]).encode()), ed25519.Ed25519PublicKey):
        raise RuntimeError("INVALID_PINNED_HOST_KEY")
    output = output.absolute()
    if output != output.resolve() or output.exists():
        raise RuntimeError("OUTPUT_MUST_BE_NEW")
    preflight()
    output.mkdir(mode=0o700)
    values = [secrets.token_hex(32) for _ in range(5)]
    if len(set(values)) != 5:
        raise RuntimeError("KEY_COLLISION")
    sso_ad, sso_logic, sso_control, engine, signing = values
    recovery = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MetaInc Naver backup recovery 20261001")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(recovery.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1095))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                key_encipherment=True, data_encipherment=False, key_agreement=False,
                key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .sign(recovery, hashes.SHA256()).public_bytes(serialization.Encoding.PEM))
    private = recovery.private_bytes(serialization.Encoding.PEM,
                                     serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    upload = ed25519.Ed25519PrivateKey.generate()
    upload_private = upload.private_bytes(serialization.Encoding.PEM,
                    serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())
    upload_public = upload.public_key().public_bytes(serialization.Encoding.OpenSSH,
                    serialization.PublicFormat.OpenSSH) + b" naver-backup-upload-20261001\n"
    sha = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest().encode()
    entries = [(AD, RECOVERY, PRIVATE, private),
        (AD, None, "NAVER_BACKUP_RECIPIENT_CERT_PEM", cert),
        (AD, None, "NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY", upload_private),
        (AD, None, "NAVER_BACKUP_KNOWN_HOSTS", (host_line + "\n").encode()),
        (BE, None, "NAVER_BACKUP_UPLOAD_SSH_PUBLIC_KEY", upload_public),
        (AD, None, "SSO_AD_CENTER_CLIENT_KEY", sso_ad.encode()),
        (BE, None, "SSO_AD_CENTER_KEY_SHA256", sha(sso_ad)),
        (LOGIC, None, "SSO_EXCHANGE_CLIENT_KEY", sso_logic.encode()),
        (BE, None, "SSO_LOGIC_ANALYSIS_KEY_SHA256", sha(sso_logic)),
        (AD, None, "SSO_NAVER_CONTROL_CLIENT_KEY", sso_control.encode()),
        (BE, None, "SSO_NAVER_CONTROL_KEY_SHA256", sha(sso_control)),
        (AD, None, "NAVER_ENGINE_ERP_KEY", engine.encode()),
        (BE, None, "NAVER_ENGINE_KEY_SHA256", sha(engine)),
        (AD, None, "NAVER_AUTO_TOKEN_SECRET", signing.encode())]
    # 공개 자료만 저장한다. 개인키나 앱 키의 로컬 파일은 만들지 않는다.
    write_new(output / "recipient.pem", cert)
    write_new(output / "upload-key.pub", upload_public)
    write_new(output / "known-hosts", (host_line + "\n").encode())
    created, verified_count = [], 0
    try:
        for repo, environment, key_name, value in entries:
            if key_name in names(repo, environment):
                raise RuntimeError("SECRET_NAME_COLLISION_DURING_PROVISION")
            args = ["secret", "set", key_name, "-R", repo]
            if environment:
                args += ["--env", environment]
            gh(*args, body=value)
            created.append({"repository": repo, "environment": environment, "name": key_name})
            if key_name not in names(repo, environment):
                raise RuntimeError("SECRET_METADATA_NOT_FOUND")
            verified_count += 1
    finally:
        # 부분 실패도 덮어쓰지 않는다. 값/지문 없는 이름 목록만 남긴다.
        write_new(output / "receipt.json", json.dumps({
            "created_at": now.isoformat(), "created": created, "expected_count": 14,
            "complete": verified_count == 14, "metadata_verified_count": verified_count,
            "runtime_injection": False,
            "consumer_readback_verified": False,
            "recovery_certificate_expires": (now + timedelta(days=1095)).date().isoformat(),
        }, ensure_ascii=False, indent=2).encode())
    print(json.dumps({"status": "stored", "new_secret_count": len(created),
                      "runtime_injection": False, "values_or_fingerprints_printed": False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--public-output", type=pathlib.Path)
    parser.add_argument("--pinned-known-hosts", type=pathlib.Path)
    args = parser.parse_args()
    try:
        if args.provision:
            if not args.public_output or not args.pinned_known_hosts:
                raise RuntimeError("PUBLIC_PATHS_REQUIRED")
            provision(args.public_output, args.pinned_known_hosts)
        else:
            preflight()
            print(json.dumps({"status": "preflight_passed", "keys_generated": False}))
        return 0
    except Exception as exc:
        # 오류 메시지에 subprocess/인증 정보가 섞이지 않도록 유형만 출력한다.
        reason = str(exc) if type(exc) is RuntimeError and re.fullmatch(r"[A-Z_]{4,60}", str(exc)) else "DETAILS_WITHHELD"
        print(json.dumps({"status": "stopped", "error_type": type(exc).__name__, "reason": reason}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
