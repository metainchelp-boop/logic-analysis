#!/usr/bin/env python3
"""회사 수신 서버 전용. 엔진 컨테이너에 넣지 않는다.

root 소유 스크립트를 authorized_keys의 restrict,command= 고정 명령으로 설치한다.
원격 명령/파일명/경로/삭제 지시는 받지 않는다. 같은 해시 재시도는 검증 후 같은
영수증만 돌려준다. --prune은 SSH가 아닌 수신 서버 root 타이머만 사용할 수 있다.
OS 계정·SSH 제한·용량 한도 구성은 배포 전에 ① 섹션이 따로 승인/검증한다.
"""
from __future__ import annotations

import hashlib
import fcntl
import json
import os
import pathlib
import pwd
import re
import signal
import stat
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from collections import namedtuple
from contextlib import contextmanager

ROOT = pathlib.Path("/var/backups/metainc/naver-engine-received")
LOCK_FILE = pathlib.Path("/run/metainc/naver-backup-receiver.lock")
TIMEOUT_SECONDS = 300
ORPHAN_MAX_AGE = timedelta(hours=1)
MAX_BYTES = 2 * 1024 * 1024 * 1024
Limits = namedtuple("Limits", "max_total_bytes max_files min_free_bytes min_free_inodes")
# 승인된 보수 상한. 30일 저장량 보장이 아니며, 먼저 차면 기존 사본을 지우지 않고 거절한다.
LIMITS = Limits(8 * 1024 ** 3, 128, 20 * 1024 ** 3, 65536)
FILE_NAME = re.compile(r"naver-received-([0-9a-f]{64})\.cms\Z")
TEMP_NAME = re.compile(r"\.receiving-[a-z0-9_]{8}\Z")


class ReceiverError(RuntimeError):
    pass


@contextmanager
def exclusive_lock(path, *, owner=0):
    """설치자가 미리 만든 root 소유 잠금. 계정이 생성/교체할 수 있는 경로는 금지한다."""
    path = pathlib.Path(path)
    parent = path.parent.lstat()
    if not path.is_absolute() or path != path.resolve() or not stat.S_ISDIR(parent.st_mode) \
            or parent.st_uid != owner or parent.st_mode & 0o022:
        raise ReceiverError("UNSAFE_LOCK")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_nlink != 1 \
                or info.st_mode & 0o022:
            raise ReceiverError("UNSAFE_LOCK")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReceiverError("BUSY") from None
        yield
    finally:
        os.close(fd)


@contextmanager
def deadline(seconds=TIMEOUT_SECONDS):
    """헤더/본문/EOF/파일 검사까지 포함한 단일 프로세스 전체 제한. main 스레드 전용."""
    if seconds <= 0 or signal.getitimer(signal.ITIMER_REAL)[0]:
        raise ReceiverError("INVALID_TIMEOUT")
    def expired(signum, frame):
        raise ReceiverError("TIMEOUT")
    previous = signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _limits(value):
    if not isinstance(value, Limits) or any(type(v) is not int or v < 0 for v in value) \
            or not value.max_total_bytes or not value.max_files:
        raise ReceiverError("LIMITS_REQUIRED")
    return value


def _space(folder, limits, remaining, new_files=0):
    available = os.statvfs(folder)
    required = ((remaining + available.f_frsize - 1) // available.f_frsize) * available.f_frsize
    if available.f_bavail * available.f_frsize < limits.min_free_bytes + required \
            or available.f_favail < limits.min_free_inodes + new_files:
        raise ReceiverError("INSUFFICIENT_SPACE")


def _capacity(folder, limits, size):
    total, count, seen = 0, 0, set()
    for path in folder.iterdir():
        info = path.lstat()
        # 임시·이름 불명 파일도 계산한다. 하위 폴더/링크는 따라가지 않고 새 수신을 거절한다.
        if not stat.S_ISREG(info.st_mode):
            raise ReceiverError("UNEXPECTED_ENTRY")
        count += 1
        identity = (info.st_dev, info.st_ino)
        if identity not in seen:
            total += info.st_size
            seen.add(identity)
    if total + size > limits.max_total_bytes or count + 1 > limits.max_files:
        raise ReceiverError("QUOTA_EXCEEDED")
    _space(folder, limits, size, new_files=1)


def _consume(stream, expected, target=None, before_write=None):
    left, digest = expected["size"], hashlib.sha256()
    while left:
        block = stream.read(min(left, 1024 * 1024))
        if not block or len(block) > left:
            raise ReceiverError("TRUNCATED")
        if target is not None:
            before_write(left)
            pending = memoryview(block)
            while pending:
                written = target.write(pending)
                if not written:
                    raise ReceiverError("WRITE_FAILED")
                pending = pending[written:]
        left -= len(block)
        digest.update(block)
    if stream.read(1) or digest.hexdigest() != expected["sha256"]:
        raise ReceiverError("CONTENT_MISMATCH")


def _sync(folder):
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _directory(root, owner):
    p = pathlib.Path(root)
    s = p.lstat()
    if not p.is_absolute() or p != p.resolve() or not stat.S_ISDIR(s.st_mode) \
            or s.st_uid != owner or s.st_mode & 0o077:
        raise ReceiverError("UNSAFE_DIRECTORY")
    return p


def _receipt(path, owner, expected):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        s = os.fstat(source.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_uid != owner or s.st_nlink not in (1, 2) or s.st_mode & 0o077:
            raise ReceiverError("UNSAFE_FILE")
        digest = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
        receipt = {"sha256": digest.hexdigest(), "size": s.st_size}
        if receipt != expected:
            raise ReceiverError("EXISTING_FILE_MISMATCH")
        if s.st_nlink == 2:
            # link 발행 직후 죽으면 우리 mkstemp 이름과 최종 이름 두 개가 남는다.
            # 같은 내용임을 먼저 확인하고, 같은 private 폴더의 정확히 한 임시 별칭만
            # 회수한다. 임의 하드링크를 허용하거나 원본 사본을 덮는 복구는 아니다.
            aliases = []
            for candidate in path.parent.iterdir():
                if not TEMP_NAME.fullmatch(candidate.name):
                    continue
                try:
                    other = candidate.lstat()
                except FileNotFoundError:
                    continue
                if (other.st_dev, other.st_ino) == (s.st_dev, s.st_ino) \
                        and stat.S_ISREG(other.st_mode) and other.st_uid == owner \
                        and other.st_nlink == 2 and not other.st_mode & 0o077:
                    aliases.append(candidate)
            if len(aliases) != 1:
                raise ReceiverError("UNSAFE_FILE")
            aliases[0].unlink(missing_ok=True)
        if os.fstat(source.fileno()).st_nlink != 1:
            raise ReceiverError("UNSAFE_FILE")
        return receipt


def receive(root, stream, *, limits=None):
    """프레임을 끝까지 검증하고 fsync한 뒤에만 최종 파일/영수증을 만든다."""
    owner = os.geteuid()
    folder = _directory(root, owner)
    limits = _limits(LIMITS if limits is None else limits)
    try:
        line = stream.readline(513)
        if len(line) > 512 or not line.endswith(b"\n"):
            raise ReceiverError("INVALID_HEADER")
        header = json.loads(line)
        if not isinstance(header, dict) or set(header) != {"version", "size", "sha256"} \
                or type(header["version"]) is not int or header["version"] != 1 \
                or type(header["size"]) is not int or not 0 < header["size"] <= MAX_BYTES \
                or not isinstance(header["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", header["sha256"]):
            raise ReceiverError("INVALID_HEADER")
        expected = {"size": header["size"], "sha256": header["sha256"]}
        destination = folder / ("naver-received-" + header["sha256"] + ".cms")
        if os.path.lexists(destination):
            # 총량/디스크가 가득 차도 같은 사본 확인은 새 임시 파일 없이 수행한다.
            _consume(stream, expected)
            receipt = _receipt(destination, owner, expected)
            _sync(folder)
            return receipt
        _capacity(folder, limits, header["size"])
        fd, temporary = tempfile.mkstemp(prefix=".receiving-", dir=folder)
        temporary = pathlib.Path(temporary)
        try:
            with os.fdopen(fd, "wb", buffering=0) as target:
                _consume(stream, expected, target, lambda left: _space(folder, limits, left))
                target.flush()
                os.fsync(target.fileno())
            try:
                os.link(temporary, destination, follow_symlinks=False)
            except FileExistsError:
                _receipt(destination, owner, expected)
            # 겹친 동일 사본 재전송이 위의 발행 복구를 먼저 끝냈을 수도 있다.
            temporary.unlink(missing_ok=True)
            _sync(folder)
            return expected
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError):
        raise ReceiverError("RECEIVE_FAILED") from None


def prune(root, *, now, owner):
    """main의 root 전용·공유 잠금 안에서만 실행. 최종 30일, 고아 임시 1시간."""
    folder = _directory(root, owner)
    if now.tzinfo is None:
        raise ReceiverError("INVALID_TIME")
    cutoff, removed = (now - timedelta(days=30)).timestamp(), 0
    orphan_cutoff = (now - ORPHAN_MAX_AGE).timestamp()
    for path in folder.iterdir():
        is_final, is_temporary = FILE_NAME.fullmatch(path.name), TEMP_NAME.fullmatch(path.name)
        if not is_final and not is_temporary:
            continue
        s = path.lstat()
        if stat.S_ISREG(s.st_mode) and s.st_uid == owner and s.st_nlink == 1 \
                and not s.st_mode & 0o077 and s.st_mtime < (cutoff if is_final else orphan_cutoff):
            path.unlink()
            removed += 1
    if removed:
        _sync(folder)
    return removed


def main():
    try:
        is_prune = sys.argv[1:] == ["--prune"] and not os.environ.get("SSH_CONNECTION") \
            and not os.environ.get("SSH_ORIGINAL_COMMAND") and os.geteuid() == 0
        if not is_prune and (sys.argv[1:] or os.environ.get("SSH_ORIGINAL_COMMAND")):
            raise ReceiverError("COMMAND_REFUSED")
        with deadline(TIMEOUT_SECONDS), exclusive_lock(LOCK_FILE):
            if is_prune:
                owner = pwd.getpwnam("naver-backup").pw_uid
                print(json.dumps({"removed": prune(ROOT, now=datetime.now(timezone.utc), owner=owner)}))
            else:
                print(json.dumps(receive(ROOT, sys.stdin.buffer), sort_keys=True), flush=True)
        return 0
    except Exception:
        print("백업 수신 실패", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
