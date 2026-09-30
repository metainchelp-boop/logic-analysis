#!/usr/bin/env python3
"""승인된 합성 자료만 사용한다. 전송 job과 복호화 job의 비밀값을 분리한다."""
import base64
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from naver_engine import backup as B
from naver_runtime import backup_transport as T
from naver_runtime.restore_check import check_restore

STAGE = "initial"


def stage(value):
    global STAGE
    STAGE = value
    print(json.dumps({"status": "checking", "stage": value}), flush=True)


def connection_precheck(key, hosts):
    stage("offline_upload_key_parse")
    parsed = subprocess.run(["/usr/bin/ssh-keygen", "-y", "-f", str(key)],
                            capture_output=True, timeout=10, env=T.COMMAND_ENV)
    if parsed.returncode:
        raise ValueError("private key format rejected")
    stage("read_only_forced_command_probe")
    result = subprocess.run([*ssh_command(key, hosts), T.RECEIVER, "true"],
                            input=b"", capture_output=True, timeout=30, env=T.COMMAND_ENV)
    if result.returncode == 1 and "백업 수신 실패".encode() in result.stderr:
        return
    classes = [(b"Permission denied", "authentication_refused"),
               (b"Host key verification failed", "host_key_refused"),
               (b"REMOTE HOST IDENTIFICATION HAS CHANGED", "host_key_refused"),
               (b"Connection timed out", "connection_timeout"),
               (b"Connection refused", "connection_refused")]
    for marker, label in classes:
        if marker in result.stderr:
            stage(label)
            break
    raise ValueError("read only connection probe failed")


def new_file(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)
    return path


def environment_file(root, name, filename):
    value = os.environ.pop(name, "")
    if not value:
        raise ValueError("missing dedicated key")
    # Secret 입력 경로가 마지막 줄바꿈을 제거할 수 있다. OpenSSH 텍스트 형식의
    # 종결 줄바꿈만 복원하며 키 본문/서버 키/보관 Secret은 바꾸지 않는다.
    if name == "NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY" and not value.endswith("\n"):
        value += "\n"
    return new_file(root / filename, value.encode())


def openssl(*args, output=None):
    return subprocess.run([T.OPENSSL, *args], stdin=subprocess.DEVNULL,
        stdout=output if output is not None else subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=60, env=T.COMMAND_ENV, check=False)


def decrypt(root, cipher, cert, key, name):
    path = root / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        result = openssl("cms", "-decrypt", "-binary", "-inform", "DER", "-in", str(cipher),
                         "-recip", str(cert), "-inkey", str(key), output=stream)
    if result.returncode:
        path.unlink()
        raise ValueError("decryption rejected")
    return path


def snapshot(path):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE synthetic_leads (id INTEGER PRIMARY KEY, score INTEGER)")
        connection.executemany("INSERT INTO synthetic_leads VALUES (?, ?)", [(1, 10), (2, 20), (3, 30)])
        connection.execute("CREATE TABLE synthetic_events (id INTEGER PRIMARY KEY, label TEXT)")
        connection.executemany("INSERT INTO synthetic_events VALUES (?, ?)", [(1, "test-only"), (2, "not-operating-data")])
    return {"synthetic_leads": 3, "synthetic_events": 2}


def synthetic_archive(root):
    now = datetime.now(timezone.utc)
    result = B.create_local_backup(snapshot, root / "local", now=now)
    return result.local_path, now.astimezone(timezone(timedelta(hours=9))).date().isoformat()


def ssh_command(key, hosts, *, clear_forwardings=True):
    return [T.SSH, "-F", "/dev/null", "-T", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + str(hosts),
        "-o", "GlobalKnownHostsFile=/dev/null", "-o", "ConnectTimeout=10", "-o", "ConnectionAttempts=1",
        "-o", "ClearAllForwardings=" + ("yes" if clear_forwardings else "no"),
        "-o", "PermitLocalCommand=no", "-i", str(key)]


def ssh_check(command, data=b""):
    result = subprocess.run(command, input=data, capture_output=True, timeout=30, env=T.COMMAND_ENV)
    # 인증 실패(255)를 기능 차단 성공으로 오인하지 않는다. 강제 수신기 1만 허용한다.
    if result.returncode != 1 or b"\"sha256\"" in result.stdout:
        raise ValueError("expected receiver refusal missing")
    return True


def transfer(root, evidence):
    if "NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM" in os.environ:
        raise ValueError("recovery key must not enter upload job")
    cert = environment_file(root, "NAVER_BACKUP_RECIPIENT_CERT_PEM", "recipient.pem")
    key = environment_file(root, "NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY", "upload-key")
    hosts = environment_file(root, "NAVER_BACKUP_KNOWN_HOSTS", "known-hosts")
    connection_precheck(key, hosts)
    stage("synthetic_encryption")
    archive, day = synthetic_archive(root)
    cipher = root / "synthetic.cms"
    T.OpenSslEncryptor(cert)(archive, cipher)
    payload = cipher.read_bytes()
    expected = {"sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
    if len(payload) > 32768:
        raise ValueError("synthetic fixture unexpectedly large")
    sender = T.SshSender(key, hosts)
    print(json.dumps({"status": "synthetic_fixture", "ciphertext": expected, "expected_kst_date": day}), flush=True)
    stage("first_upload")
    if sender(cipher) != expected:
        raise ValueError("receipt mismatch")
    stage("same_content_retry")
    if sender(cipher) != expected:
        raise ValueError("receipt mismatch")
    command = ssh_command(key, hosts)
    changed = bytearray(payload)
    changed[-5] ^= 1
    frame = json.dumps({"version": 1, **expected}).encode() + b"\n" + changed
    stage("tampered_transport_refusal")
    tamper = ssh_check([*command, T.RECEIVER], frame)
    stage("remote_command_refusal")
    arbitrary = ssh_check([*command, T.RECEIVER, "true"])
    stage("remote_prune_refusal")
    remote_prune = ssh_check([*command, T.RECEIVER, "--prune"])
    stage("sftp_refusal")
    sftp = ssh_check([*command, "-s", T.RECEIVER, "sftp"])
    # 원격 listen 요청은 서버에서 거절되어야 한다. 일반 shell은 절대 실행하지 않는다.
    stage("forwarding_refusal")
    forwarding = subprocess.run([*ssh_command(key, hosts, clear_forwardings=False), "-o",
        "ExitOnForwardFailure=yes", "-R", "0:127.0.0.1:9", "-N", T.RECEIVER],
        input=b"", capture_output=True, timeout=20, env=T.COMMAND_ENV)
    denied = forwarding.returncode == 255 and b"remote port forwarding failed" in forwarding.stderr
    if not denied:
        raise ValueError("forwarding restriction not verified")
    report = {"status": "synthetic_transfer_verified", "ciphertext": expected,
        "expected_kst_date": day, "expected_row_counts": {"synthetic_leads": 3, "synthetic_events": 2},
        "same_content_retry": True, "tamper_refused": tamper, "remote_command_refused": arbitrary,
        "remote_prune_refused": remote_prune, "sftp_refused": sftp, "forwarding_refused": denied,
        "sender": "isolated_github_runner", "engine_host_sender_verified": False,
        "operating_data_used": False}
    new_file(evidence / "synthetic-transfer.json", json.dumps(report, indent=2).encode())
    print(json.dumps(report, sort_keys=True))


def recover(root, evidence, mode):
    if "NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY" in os.environ:
        raise ValueError("upload key must not enter recovery job")
    cert = environment_file(root, "NAVER_BACKUP_RECIPIENT_CERT_PEM", "recipient.pem")
    key = environment_file(root, "NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM", "recovery.pem")
    cipher = root / "received.cms"
    if mode == "keys":
        values = [os.environ.pop(name, "") for name in ("SSO_AD_CENTER_CLIENT_KEY",
                  "SSO_NAVER_CONTROL_CLIENT_KEY", "NAVER_ENGINE_ERP_KEY", "NAVER_AUTO_TOKEN_SECRET")]
        if len(set(values)) != 4 or not all(re.fullmatch(r"[0-9a-f]{64}", v) for v in values):
            raise ValueError("new dedicated key shapes invalid")
        archive, day = synthetic_archive(root)
        T.OpenSslEncryptor(cert)(archive, cipher)
        report = {"status": "stored_ad_keys_verified", "new_key_shapes_distinct": True,
                  "certificate_private_key_pair_verified": True, "operating_data_used": False}
    else:
        supplied = json.loads(os.environ.pop("RECEIVED_SYNTHETIC_JSON", ""))
        if set(supplied) != {"ciphertext_b64", "sha256", "size", "expected_kst_date"}:
            raise ValueError("unexpected readback receipt")
        raw = base64.b64decode(supplied["ciphertext_b64"], validate=True)
        if len(raw) > 32768 or type(supplied["size"]) is not int or len(raw) != supplied["size"] \
                or hashlib.sha256(raw).hexdigest() != supplied["sha256"]:
            raise ValueError("received ciphertext mismatch")
        new_file(cipher, raw)
        day = supplied["expected_kst_date"]
        report = {"status": "received_synthetic_restore_verified", "ciphertext_sha256": supplied["sha256"],
                  "ciphertext_size": len(raw), "source": "receiver_admin_readback", "operating_data_used": False}
    plain = decrypt(root, cipher, cert, key, "decrypted.zip")
    restored = check_restore(plain, expected_kst_date=day, output_dir=root / "restored")
    if restored["row_counts"] != {"synthetic_leads": 3, "synthetic_events": 2}:
        raise ValueError("synthetic row count mismatch")
    changed = bytearray(cipher.read_bytes())
    changed[-5] ^= 1
    bad = new_file(root / "tampered.cms", changed)
    try:
        decrypt(root, bad, cert, key, "rejected.zip")
    except ValueError:
        report["aead_tamper_refused"] = True
    else:
        raise ValueError("aead integrity was not enforced")
    report["restored"] = restored
    new_file(evidence / (mode + "-verification.json"), json.dumps(report, indent=2).encode())
    print(json.dumps(report, sort_keys=True))


def main():
    global STAGE
    STAGE = "initial"
    try:
        mode = os.environ["ACCEPTANCE_MODE"]
        evidence = pathlib.Path(os.environ["ACCEPTANCE_EVIDENCE"]).resolve()
        evidence.mkdir(mode=0o700, exist_ok=False)
        with tempfile.TemporaryDirectory(prefix="naver-backup-acceptance-") as temporary:
            root = pathlib.Path(temporary).resolve()
            os.chmod(root, 0o700)
            if mode == "transfer":
                transfer(root, evidence)
            elif mode in ("keys", "restore"):
                recover(root, evidence, mode)
            else:
                raise ValueError("unsupported acceptance mode")
        return 0
    except Exception:
        # 오류 원문/traceback에 비밀값이 포함될 수 있어 진단 결과만 기록한다.
        print(json.dumps({"status": "acceptance_failed", "stage": STAGE, "secrets_printed": False}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
