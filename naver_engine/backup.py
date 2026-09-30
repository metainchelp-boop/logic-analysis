"""S14 백업 파일 처리. DB/암호화 실행/전송은 주입한 함수만 사용한다.

로컬 압축본과 보내는 암호문은 다른 private 폴더에 둔다. READY는 전송 성공이
아니다. 수신 영수증의 파일 해시와 길이가 맞아야 OFFSITE_OK가 된다.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Mapping, Optional

NAME = re.compile(r"naver-(\d{8}T\d{6}Z)-[0-9a-f]{32}\.(zip|cms)\Z")
MAX_BYTES = 2 * 1024 * 1024 * 1024
UTC = timezone.utc
KST = timezone(timedelta(hours=9))
STATUS_CODES = frozenset({"NEVER", "IN_PROGRESS", "LOCAL_FAILED", "ENCRYPTION_FAILED", "READY",
                          "LOCAL_READY", "UPLOAD_FAILED", "OFFSITE_OK", "RETENTION_FAILED"})


class BackupError(RuntimeError):
    """경로·데이터·외부 명령 오류 본문을 노출하지 않는 오류."""


@dataclass(frozen=True)
class BackupResult:
    code: str
    local_path: Optional[pathlib.Path] = field(default=None, repr=False)
    encrypted_path: Optional[pathlib.Path] = field(default=None, repr=False)
    offsite_verified: bool = False


def private_directory(path) -> pathlib.Path:
    """절대 경로 · 심볼릭 링크 없는 우리 소유 700 폴더만 받는다."""
    p = pathlib.Path(path)
    code_root = pathlib.Path(__file__).resolve().parents[1]
    if not p.is_absolute() or p != p.resolve() or p == code_root or code_root in p.parents:
        raise BackupError("UNSAFE_DIRECTORY")
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    s = p.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.geteuid() or s.st_mode & 0o077:
        raise BackupError("UNSAFE_DIRECTORY")
    return p


def private_file(path) -> pathlib.Path:
    p = pathlib.Path(path)
    s = p.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != os.geteuid() or s.st_nlink != 1 or s.st_mode & 0o077:
        raise BackupError("UNSAFE_FILE")
    return p


def file_digest(path) -> str:
    with private_file(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _counts(counts) -> dict:
    if not isinstance(counts, Mapping) or not counts or any(
            not isinstance(k, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k)
            or type(v) is not int or v < 0 for k, v in counts.items()):
        raise BackupError("INVALID_COUNTS")
    return dict(counts)


def _instant(now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise BackupError("INVALID_TIME")
    return now.astimezone(UTC)


def _publish(source: pathlib.Path, destination: pathlib.Path) -> None:
    # 같은 파일시스템에서 배타적으로 이름을 붙인다. 기존 파일은 절대 덮지 않는다.
    os.link(source, destination, follow_symlinks=False)
    source.unlink()
    fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create_local_backup(snapshot: Callable, local_dir, *, now: datetime) -> BackupResult:
    """전송 상태와 독립적으로 오늘의 검증된 스냅샷을 압축한다."""
    result = BackupResult("LOCAL_FAILED")
    try:
        local = private_directory(local_dir)
        instant = _instant(now)
        stem = "naver-" + instant.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix=".building-", dir=local) as work:
            root = pathlib.Path(work)
            db = root / "snapshot.sqlite"
            counts = _counts(snapshot(db))
            os.chmod(db, 0o600)
            manifest = {"version": 1, "created_at": instant.isoformat(), "row_counts": counts,
                        "sha256": file_digest(db)}
            packed = root / "packed.zip"
            fd = os.open(packed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(db, "snapshot.sqlite")
                    archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
                stream.flush()
                os.fsync(stream.fileno())
            destination = local / (stem + ".zip")
            _publish(packed, destination)
        return BackupResult("LOCAL_READY", local_path=destination)
    except Exception:
        return result


def encrypt_backup(result: BackupResult, outgoing_dir, encrypt: Optional[Callable]) -> BackupResult:
    """이미 보관한 일일 압축본을 암호화한다. 실패 재시도에도 스냅샷을 중복 생성하지 않는다."""
    if result.code != "LOCAL_READY" or result.local_path is None:
        return result
    result = replace(result, code="ENCRYPTION_FAILED")
    try:
        destination = private_file(result.local_path)
        outgoing = private_directory(outgoing_dir)
        local = destination.parent
        if local == outgoing or local in outgoing.parents or outgoing in local.parents:
            raise BackupError("DIRECTORIES_OVERLAP")
        if encrypt is None:
            return result
        with tempfile.TemporaryDirectory(prefix=".building-", dir=outgoing) as work:
            encrypted = pathlib.Path(work) / "encrypted.cms"
            encrypt(destination, encrypted)
            os.chmod(encrypted, 0o600)
            if private_file(encrypted).stat().st_size == 0:
                raise BackupError("EMPTY_CIPHERTEXT")
            with encrypted.open("rb") as stream:
                os.fsync(stream.fileno())
            ready = outgoing / (destination.stem + ".cms")
            _publish(encrypted, ready)
        return BackupResult("READY", destination, ready)
    except Exception:
        # 의존 함수 예외에 저장 경로·원문·인증값이 들어 있을 수 있다.
        return result


def create_backup(snapshot: Callable, local_dir, outgoing_dir, *, now: datetime,
                  encrypt: Optional[Callable] = None) -> BackupResult:
    """로컬 생성 + 암호화. snapshot만 writer 스레드에 전달하고 암호화는 그 밖에서 수행한다."""
    try:
        local, outgoing = private_directory(local_dir), private_directory(outgoing_dir)
        if local == outgoing or local in outgoing.parents or outgoing in local.parents:
            return BackupResult("LOCAL_FAILED")
    except Exception:
        return BackupResult("LOCAL_FAILED")
    return encrypt_backup(create_local_backup(snapshot, local_dir, now=now), outgoing_dir, encrypt)


def publish_backup(result: BackupResult, send: Callable) -> BackupResult:
    """서버가 디스크 동기화를 마친 영수증을 대조한 경우에만 서버 밖 성공이다."""
    if result.code != "READY" or result.encrypted_path is None:
        return result
    try:
        path = private_file(result.encrypted_path)
        digest, size = file_digest(path), path.stat().st_size
        receipt = send(path)
        if not isinstance(receipt, dict) or receipt.get("sha256") != digest \
                or type(receipt.get("size")) is not int or receipt["size"] != size:
            raise BackupError("RECEIPT_MISMATCH")
        return replace(result, code="OFFSITE_OK", offsite_verified=True)
    except Exception:
        return replace(result, code="UPLOAD_FAILED", offsite_verified=False)


def restore_archive(archive_path, destination, inspect_snapshot: Callable) -> dict:
    """이미 복호화된 압축본 검증. inspect_snapshot은 DB 무결성을 검사하고 줄 수를 반환한다.

    현재 DB 위 복원은 허용하지 않는다. 검사 통과한 새 파일만 배타적으로 발행한다.
    개인키 및 복호화 동작은 엔진이 아니라 별도 복원 작업자의 몫이다.
    """
    try:
        target = pathlib.Path(destination)
        private_directory(target.parent)
        if not target.is_absolute() or target.exists() or target.is_symlink():
            raise BackupError("RESTORE_DESTINATION_EXISTS")
        with zipfile.ZipFile(private_file(archive_path)) as archive:
            if sorted(archive.namelist()) != ["manifest.json", "snapshot.sqlite"]:
                raise BackupError("INVALID_ARCHIVE")
            if archive.getinfo("manifest.json").file_size > 1024 * 1024 \
                    or not 0 < archive.getinfo("snapshot.sqlite").file_size <= MAX_BYTES:
                raise BackupError("INVALID_ARCHIVE_SIZE")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("version") != 1:
                raise BackupError("INVALID_MANIFEST")
            expected = _counts(manifest["row_counts"])
            with tempfile.TemporaryDirectory(prefix=".restore-", dir=target.parent) as work:
                db = pathlib.Path(work) / "snapshot.sqlite"
                fd = os.open(db, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as output, archive.open("snapshot.sqlite") as source:
                    shutil.copyfileobj(source, output)
                    output.flush()
                    os.fsync(output.fileno())
                if file_digest(db) != manifest["sha256"] or _counts(inspect_snapshot(db)) != expected:
                    raise BackupError("RESTORE_MISMATCH")
                _publish(db, target)
        return expected
    except Exception:
        raise BackupError("RESTORE_FAILED") from None


def prune_local(directory, *, now: datetime) -> int:
    """7일 지난 엔진 백업만 정리한다. 코드/DB/임의 사용자 파일은 이름부터 대상이 아니다."""
    root = private_directory(directory)
    cutoff = _instant(now) - timedelta(days=7)
    removed = 0
    for p in root.iterdir():
        match = NAME.fullmatch(p.name)
        if match is None:
            continue
        try:
            created = datetime.strptime(match[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            s = private_file(p).stat()
            # 이름뿐 아니라 수신/생성 파일의 시각도 오래된 경우에만 정리한다.
            if created < cutoff and s.st_mtime < cutoff.timestamp():
                p.unlink()
                removed += 1
        except (BackupError, ValueError, FileNotFoundError):
            continue
    return removed


class BackupJob:
    """아침 종료 후 하루 한 사본, 실패는 1시간 간격. 상태는 재시작에도 유지한다.

    단일 scheduler가 호출한다. Store proxy는 snapshot_to만 writer 스레드로 보내며,
    암호화/전송을 기다리는 동안 writer를 붙잡지 않는다. 영수증 유실 재시도는 같은
    암호문을 쓰므로 수신 서버의 내용 해시 식별자와 함께 멱등이다.
    """
    def __init__(self, root, encrypt: Callable, send: Callable):
        self.root = private_directory(root)
        self.local, self.outgoing = self.root / "local", self.root / "outgoing"
        self.encrypt, self.send = encrypt, send
        self.state_path = self.root / "state.json"
        self.state = {"version": 2, "code": "NEVER", "last_attempt_at": None, "last_offsite_at": None,
                      "last_offsite_day": None, "pending": None, "pending_day": None,
                      "last_local_day": None, "last_local_file": None}
        if self.state_path.exists() or self.state_path.is_symlink():
            try:
                if private_file(self.state_path).stat().st_size > 8192:
                    raise BackupError("STATE_UNREADABLE")
                loaded = json.loads(self.state_path.read_text())
                if not isinstance(loaded, dict) or set(loaded) != set(self.state) or loaded["version"] != 2:
                    raise BackupError("STATE_UNREADABLE")
                if not isinstance(loaded["code"], str) or loaded["code"] not in STATUS_CODES:
                    raise BackupError("STATE_UNREADABLE")
                for key in ("last_attempt_at", "last_offsite_at"):
                    if loaded[key] is not None:
                        _instant(datetime.fromisoformat(loaded[key]))
                for key in ("last_offsite_day", "pending_day", "last_local_day"):
                    if loaded[key] is not None:
                        date.fromisoformat(loaded[key])
                pending = loaded["pending"]
                if pending is not None and (not isinstance(pending, str) or NAME.fullmatch(pending) is None
                                            or not pending.endswith(".cms")):
                    raise BackupError("STATE_UNREADABLE")
                if (pending is None) != (loaded["pending_day"] is None):
                    raise BackupError("STATE_UNREADABLE")
                local = loaded["last_local_file"]
                if local is not None and (not isinstance(local, str) or NAME.fullmatch(local) is None
                                          or not local.endswith(".zip")):
                    raise BackupError("STATE_UNREADABLE")
                if (local is None) != (loaded["last_local_day"] is None):
                    raise BackupError("STATE_UNREADABLE")
                self.state = loaded
            except Exception:
                raise BackupError("STATE_UNREADABLE") from None

    def status(self) -> dict:
        return {key: self.state[key] for key in ("code", "last_attempt_at", "last_offsite_at")}

    def _save(self):
        if self.state_path.exists() or self.state_path.is_symlink():
            private_file(self.state_path)
        fd, name = tempfile.mkstemp(prefix=".state-", dir=self.root)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(self.state, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.state_path)
            directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            pathlib.Path(name).unlink(missing_ok=True)

    def __call__(self, store, now: datetime) -> BackupResult:
        instant = _instant(now)
        today = instant.astimezone(KST).date()
        runs = store.runs_on(today)
        if not any(r["status"] in ("done", "failed") for r in runs) or any(r["status"] == "running" for r in runs):
            return BackupResult("WAITING_FOR_MORNING")
        if self.state["last_offsite_day"] == today.isoformat():
            return BackupResult("ALREADY_BACKED_UP", offsite_verified=True)
        last = self.state["last_attempt_at"]
        if last is not None and instant - datetime.fromisoformat(last) < timedelta(hours=1):
            return BackupResult("RETRY_WAIT")
        self.state.update(last_attempt_at=instant.isoformat(), code="IN_PROGRESS")
        self._save()
        if self.state["last_local_day"] != today.isoformat():
            local = create_local_backup(store.snapshot_to, self.local, now=instant)
            if local.code != "LOCAL_READY":
                self.state["code"] = local.code
                self._save()
                return local
            self.state.update(last_local_day=today.isoformat(), last_local_file=local.local_path.name)
            self._save()
        pending = self.state["pending"]
        if pending is None:
            local = BackupResult("LOCAL_READY", self.local / self.state["last_local_file"])
            result = encrypt_backup(local, self.outgoing, self.encrypt)
            if result.code == "READY":
                self.state.update(pending=result.encrypted_path.name, pending_day=today.isoformat())
                self._save()
        else:
            result = BackupResult("READY", self.local / (pending[:-4] + ".zip"), self.outgoing / pending)
        result = publish_backup(result, self.send)
        self.state["code"] = result.code
        if result.offsite_verified:
            self.state.update(last_offsite_at=instant.isoformat(), last_offsite_day=self.state["pending_day"],
                              pending=None, pending_day=None)
        self._save()
        # 서버 밖 검증 실패 때에는 사본을 정리하지 않는다.
        if result.offsite_verified:
            try:
                prune_local(self.local, now=instant)
                prune_local(self.outgoing, now=instant)
            except Exception:
                self.state["code"] = "RETENTION_FAILED"
                self._save()
                return replace(result, code="RETENTION_FAILED")
        return result
