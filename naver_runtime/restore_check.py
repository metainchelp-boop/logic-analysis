"""복호화 완료 ZIP의 로컬 복원 검증. 키·환경 설정·네트워크를 사용하지 않는다."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from datetime import date, datetime
import zipfile

from naver_engine import backup as B
from naver_engine.store import inspect_snapshot


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse 기본 오류는 사용자가 넣은 경로/값을 그대로 출력한다.
        raise B.BackupError("INVALID_ARGUMENTS")


def check_restore(archive_path, expected_kst_date, output_dir):
    """새 검증 폴더에만 복원하고 날짜·해시·건수를 반환한다. 원본은 읽기만 한다."""
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", expected_kst_date):
        raise B.BackupError("INVALID_DATE")
    expected = date.fromisoformat(expected_kst_date)
    source, output = Path(archive_path), Path(output_dir)
    if not source.is_absolute() or source != source.resolve():
        raise B.BackupError("INVALID_ARCHIVE_PATH")
    checked = B.private_file(source).lstat()
    if (not output.is_absolute() or output != output.resolve() or output.exists()
            or output.is_symlink() or not output.parent.is_dir() or output.parent == Path("/")):
        raise B.BackupError("INVALID_OUTPUT")
    B.private_directory(output.parent)
    output.mkdir(mode=0o700, exist_ok=False)
    complete = False
    try:
        # 날짜 검사와 기존 복원 함수가 반드시 같은 사본을 읽는다. 원본 경로를 재사용하지 않는다.
        with tempfile.TemporaryDirectory(prefix=".checking-", dir=output) as work:
            copied = Path(work) / "archive.zip"
            # A swapped FIFO must not block before fstat can reject its type.
            with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as incoming:
                opened = os.fstat(incoming.fileno())
                if ((opened.st_dev, opened.st_ino) != (checked.st_dev, checked.st_ino)
                        or not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.geteuid()
                        or opened.st_nlink != 1 or opened.st_mode & 0o077):
                    raise B.BackupError("UNSAFE_ARCHIVE_FILE")
                fd = os.open(copied, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as outgoing:
                    total = 0
                    while block := incoming.read(1024 * 1024):
                        total += len(block)
                        if total > B.MAX_BYTES + 2 * 1024 * 1024:
                            raise B.BackupError("INVALID_ARCHIVE_SIZE")
                        outgoing.write(block)
            with zipfile.ZipFile(copied) as archive:
                if sorted(archive.namelist()) != ["manifest.json", "snapshot.sqlite"] \
                        or archive.getinfo("manifest.json").file_size > 1024 * 1024:
                    raise B.BackupError("INVALID_ARCHIVE")
                manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict) or type(manifest.get("version")) is not int \
                    or manifest["version"] != 1:
                raise B.BackupError("INVALID_MANIFEST")
            created_text = manifest.get("created_at")
            # create_local_backup은 UTC datetime.isoformat()을 기록한다. 암묵적 지역 시각은 금지한다.
            if not isinstance(created_text, str) or not re.fullmatch(
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{6})?\+00:00",
                    created_text):
                raise B.BackupError("INVALID_CREATED_AT")
            created = datetime.fromisoformat(created_text)
            if created.astimezone(B.KST).date() != expected:
                raise B.BackupError("DATE_MISMATCH")
            archive_digest = B.file_digest(copied)
            counts = B.restore_archive(copied, output / "snapshot.sqlite", inspect_snapshot)
            report = {"status": "verified", "created_at": manifest["created_at"],
                      "backup_kst_date": expected.isoformat(), "archive_sha256": archive_digest,
                      "snapshot_sha256": manifest["sha256"], "row_counts": counts}
        complete = True
        return report
    finally:
        if not complete:
            # 발행 뒤 fsync 등이 실패해도 검증 실패를 성공 사본으로 오해하지 않게 한다.
            # 이번에 배타적으로 만든 폴더의 정확한 private 출력만 제거한다.
            restored = output / "snapshot.sqlite"
            if restored.exists() or restored.is_symlink():
                B.private_file(restored).unlink()
            # 기존 데이터는 재귀 삭제하지 않는다.
            output.rmdir()


def main(argv=None):
    try:
        parser = _Parser(prog="naver-restore-check", description="복호화 완료 백업의 격리 검증")
        parser.add_argument("--archive", required=True)
        parser.add_argument("--expected-kst-date", required=True)
        parser.add_argument("--output-dir", required=True)
        args = parser.parse_args(argv)
        report = check_restore(args.archive, args.expected_kst_date, args.output_dir)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"status": "failed", "message": "복원 검증에 실패했습니다."}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
