#!/usr/bin/env python3
"""회사 수신 서버 전용. 엔진 컨테이너에 넣지 않는다.

root 소유 스크립트를 authorized_keys의 restrict,command= 고정 명령으로 설치한다.
원격 명령/파일명/경로/삭제 지시는 받지 않는다. 같은 해시 재시도는 검증 후 같은
영수증만 돌려준다. --prune은 SSH가 아닌 수신 서버 root 타이머만 사용할 수 있다.
OS 계정·SSH 제한·용량 한도 구성은 배포 전에 ① 섹션이 따로 승인/검증한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import pwd
import re
import stat
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path("/var/backups/metainc/naver-engine-received")
MAX_BYTES = 2 * 1024 * 1024 * 1024
FILE_NAME = re.compile(r"naver-received-([0-9a-f]{64})\.cms\Z")
TEMP_NAME = re.compile(r"\.receiving-[a-z0-9_]{8}\Z")


class ReceiverError(RuntimeError):
    pass


def _directory(root, owner):
    p = pathlib.Path(root)
    s = p.lstat()
    if not p.is_absolute() or p != p.resolve() or not stat.S_ISDIR(s.st_mode) \
            or s.st_uid != owner or s.st_mode & 0o077:
        raise ReceiverError("UNSAFE_DIRECTORY")
    return p


def _receipt(path, owner, expected):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        s = os.fstat(source.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_uid != owner or s.st_nlink not in (1, 2) or s.st_mode & 0o077:
            raise ReceiverError("UNSAFE_FILE")
        receipt = {"sha256": hashlib.file_digest(source, "sha256").hexdigest(), "size": s.st_size}
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


def receive(root, stream):
    """프레임을 끝까지 검증하고 fsync한 뒤에만 최종 파일/영수증을 만든다."""
    owner = os.geteuid()
    folder = _directory(root, owner)
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
        fd, temporary = tempfile.mkstemp(prefix=".receiving-", dir=folder)
        temporary = pathlib.Path(temporary)
        try:
            with os.fdopen(fd, "wb") as target:
                left, digest = header["size"], hashlib.sha256()
                while left:
                    block = stream.read(min(left, 1024 * 1024))
                    if not block:
                        raise ReceiverError("TRUNCATED")
                    left -= len(block)
                    target.write(block)
                    digest.update(block)
                if stream.read(1) or digest.hexdigest() != header["sha256"]:
                    raise ReceiverError("CONTENT_MISMATCH")
                target.flush()
                os.fsync(target.fileno())
            try:
                os.link(temporary, destination, follow_symlinks=False)
            except FileExistsError:
                _receipt(destination, owner, expected)
            # 겹친 동일 사본 재전송이 위의 발행 복구를 먼저 끝냈을 수도 있다.
            temporary.unlink(missing_ok=True)
            directory_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return expected
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError):
        raise ReceiverError("RECEIVE_FAILED") from None


def prune(root, *, now, owner):
    """수신 서버 시각으로 30일. 파일명/일반 파일/소유자/단일 링크가 모두 맞는 것만."""
    folder = _directory(root, owner)
    if now.tzinfo is None:
        raise ReceiverError("INVALID_TIME")
    cutoff, removed = (now - timedelta(days=30)).timestamp(), 0
    for path in folder.iterdir():
        if not FILE_NAME.fullmatch(path.name):
            continue
        s = path.lstat()
        if stat.S_ISREG(s.st_mode) and s.st_uid == owner and s.st_nlink == 1 \
                and not s.st_mode & 0o077 and s.st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed


def main():
    try:
        if sys.argv[1:] == ["--prune"] and not os.environ.get("SSH_CONNECTION") \
                and not os.environ.get("SSH_ORIGINAL_COMMAND") and os.geteuid() == 0:
            owner = pwd.getpwnam("naver-backup").pw_uid
            print(json.dumps({"removed": prune(ROOT, now=datetime.now(timezone.utc), owner=owner)}))
        elif not sys.argv[1:] and not os.environ.get("SSH_ORIGINAL_COMMAND"):
            print(json.dumps(receive(ROOT, sys.stdin.buffer), sort_keys=True), flush=True)
        else:
            raise ReceiverError("COMMAND_REFUSED")
        return 0
    except Exception:
        print("백업 수신 실패", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
