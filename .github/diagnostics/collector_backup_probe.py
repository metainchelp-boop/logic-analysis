"""Create a new on-server SQLite backup and verify a separate restored copy.

Stdlib only. No application imports, original restore, pruning, or row output.
The caller must encrypt stdout. SQLite's read-only online backup preserves WAL
commits; SQLite may use its normal source WAL/SHM coordination files.
"""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import stat
import sys
import time
import uuid


MAX_SOURCE_BYTES = 4 * 1024**3
MAX_RETAINED_BYTES = 8 * 1024**3
RESERVE_BYTES = 512 * 1024**2
MAX_TIMEOUT_SECONDS = 180
JOB_PATTERN = re.compile(r"collector-validation-[A-Za-z0-9_-]{1,100}")
KNOWN_TABLES = frozenset({
    "tracked_products", "tracked_keywords", "rankings", "competitor_snapshots",
    "notification_settings", "notification_logs", "api_usage_logs",
    "shopping_search_cache", "place_rank_history", "place_track_target",
    "collected_serp", "collector_blocks", "collect_requests", "collector_control",
})
ARTIFACT_NAMES = ("backup.sqlite", "restored-copy.sqlite")


class ProbeError(Exception):
    """Only fixed, non-sensitive error codes may be passed here."""


def _ordinary(path, kind):
    if path.resolve() != path or path.is_symlink():
        raise ProbeError("PATH_ALIAS_FORBIDDEN")
    try:
        info = path.stat()
    except OSError as exc:
        raise ProbeError("REQUIRED_PATH_UNAVAILABLE") from exc
    expected = stat.S_ISDIR if kind == "directory" else stat.S_ISREG
    if not expected(info.st_mode):
        raise ProbeError("ORDINARY_PATH_REQUIRED")
    if kind == "file" and info.st_nlink != 1:
        raise ProbeError("FILE_ALIAS_FORBIDDEN")
    return info


def _sidecar_bytes(source, suffix):
    path = Path(str(source) + suffix)
    if path.is_symlink():
        raise ProbeError("PATH_ALIAS_FORBIDDEN")
    try:
        return _ordinary(path, "file").st_size
    except ProbeError as exc:
        # A WAL may disappear normally between these checks.
        if str(exc) == "REQUIRED_PATH_UNAVAILABLE" and not path.exists():
            return 0
        raise


def _identity(info):
    return info.st_dev, info.st_ino


def _new_file(path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ProbeError("OUTPUT_ALREADY_EXISTS") from exc
    os.fchmod(descriptor, 0o600)
    return os.fdopen(descriptor, "wb")


def _digest(path, check):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            check()
            digest.update(block)
    return digest.hexdigest()


def _metadata(path, check):
    """Inspect only a newly created artifact. Never return unknown schema names."""
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
        conn.set_progress_handler(lambda: int(time.monotonic() >= check.deadline), 1000)
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ProbeError("ARTIFACT_INTEGRITY_FAILED")
        if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
            raise ProbeError("STANDALONE_ARTIFACT_REQUIRED")
        counts = {}
        for schema, name, kind, *_ in conn.execute("PRAGMA table_list"):
            check()
            if schema == "main" and kind == "table" and not name.startswith("sqlite_"):
                quoted = '"' + name.replace('"', '""') + '"'
                counts[name] = conn.execute("SELECT COUNT(*) FROM " + quoted).fetchone()[0]
        schema = conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_schema").fetchall()
        schema.sort(key=lambda row: tuple("" if cell is None else cell for cell in row))
        encode = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=True,
                                           separators=(",", ":")).encode("utf-8")
        result = {
            "integrity_check": "ok", "journal_mode": "delete",
            "ordinary_table_count": len(counts),
            "known_table_counts": {name: counts[name] for name in sorted(KNOWN_TABLES & counts.keys())},
            "all_ordinary_table_counts_sha256": hashlib.sha256(encode(counts)).hexdigest(),
            "schema_sha256": hashlib.sha256(encode(schema)).hexdigest(),
        }
    check()
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            raise ProbeError("STANDALONE_ARTIFACT_REQUIRED")
    return result


def _copy_new(source, output, check):
    with source.open("rb") as src, _new_file(output) as dst:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            check()
            dst.write(block)
        dst.flush()
        os.fsync(dst.fileno())
    check()


def create_verified_backup(source, job_dir, timeout_seconds=MAX_TIMEOUT_SECONDS):
    """Retain two NEW files below source.parent/backups; never overwrite anything.

    Failure leaves any files owned by this attempt in its private directory.
    They are explicitly unverified unless the final report says passed=true.
    Source transactions after the snapshot remain on the source, not this copy.
    """
    started = time.monotonic()
    report = {
        "probe_version": 1, "passed": False,
        "source_open_mode": "ro", "original_restore_performed": False,
        "isolated_restore_verified": False, "job_directory_created": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "sqlite_version": sqlite3.sqlite_version,
        "snapshot_scope": "consistent snapshot; subsequent source writes remain on the source",
        "count_scope": "ordinary main tables; excludes views, virtual and shadow tables",
        "limits": {"source_bytes": MAX_SOURCE_BYTES, "retained_bytes": MAX_RETAINED_BYTES,
                   "reserve_bytes": RESERVE_BYTES, "timeout_seconds": MAX_TIMEOUT_SECONDS},
    }
    try:
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS):
            raise ProbeError("INVALID_TIMEOUT")

        def check():
            if time.monotonic() >= check.deadline:
                raise ProbeError("PROBE_TIMEOUT")

        check.deadline = started + timeout_seconds
        source, job_dir = Path(source).absolute(), Path(job_dir).absolute()
        source_info = _ordinary(source, "file")
        identity = _identity(source_info)
        parent = source.parent / "backups"
        _ordinary(parent, "directory")
        if job_dir.parent != parent or not JOB_PATTERN.fullmatch(job_dir.name):
            raise ProbeError("OWNED_BACKUP_JOB_DIRECTORY_REQUIRED")
        if job_dir.resolve() != job_dir or job_dir.exists() or job_dir.is_symlink():
            raise ProbeError("JOB_DIRECTORY_ALREADY_EXISTS_OR_ALIASED")
        wal_bytes = _sidecar_bytes(source, "-wal")
        _sidecar_bytes(source, "-shm")
        _sidecar_bytes(source, "-journal")
        free = shutil.disk_usage(parent).free
        required_free = 3 * (source_info.st_size + wal_bytes) + RESERVE_BYTES
        report["preflight"] = {
            "source_bytes": source_info.st_size, "wal_bytes": wal_bytes,
            "free_bytes": free, "required_free_bytes": required_free,
        }
        if source_info.st_size + wal_bytes > MAX_SOURCE_BYTES:
            raise ProbeError("SOURCE_SIZE_LIMIT")
        if free < required_free:
            raise ProbeError("INSUFFICIENT_FREE_SPACE")
        if sqlite3.sqlite_version_info < (3, 37, 0):
            raise ProbeError("SQLITE_TABLE_LIST_REQUIRED")
        check()
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=1)) as original:
            # Read-only PRAGMAs only on the source; never change its journal mode.
            page_size = original.execute("PRAGMA page_size").fetchone()[0]
            page_count = original.execute("PRAGMA page_count").fetchone()[0]
            snapshot_bytes = page_size * page_count
            report["preflight"]["projected_snapshot_bytes"] = snapshot_bytes
            if 2 * snapshot_bytes > MAX_RETAINED_BYTES:
                raise ProbeError("RETAINED_SIZE_LIMIT")
            if free < max(required_free, 3 * (snapshot_bytes + wal_bytes) + RESERVE_BYTES):
                raise ProbeError("INSUFFICIENT_FREE_SPACE")
            if _identity(_ordinary(source, "file")) != identity:
                raise ProbeError("SOURCE_REPLACED")
            check()
            # mkdir and file creation both fail closed if a name appears meanwhile.
            job_dir.mkdir(mode=0o700)
            job_dir.chmod(0o700)
            report["job_directory_created"] = True
            report["job_directory_name"] = job_dir.name
            backup, restored = (job_dir / name for name in ARTIFACT_NAMES)
            with _new_file(backup):
                pass
            with closing(sqlite3.connect(backup.as_uri() + "?mode=rw", uri=True, timeout=1)) as copied:
                def progress(status, remaining, total):
                    check()
                    if 2 * total * page_size > MAX_RETAINED_BYTES:
                        raise ProbeError("RETAINED_SIZE_LIMIT")

                original.backup(copied, pages=128, progress=progress, sleep=0.01)
                check()
                if copied.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower() != "delete":
                    raise ProbeError("STANDALONE_ARTIFACT_REQUIRED")
        backup_info = _ordinary(backup, "file")
        if backup_info.st_size * 2 > MAX_RETAINED_BYTES:
            raise ProbeError("RETAINED_SIZE_LIMIT")
        with backup.open("rb") as handle:
            os.fsync(handle.fileno())
        backup_hash = _digest(backup, check)
        backup_meta = _metadata(backup, check)
        if _digest(backup, check) != backup_hash:
            raise ProbeError("BACKUP_CHANGED")
        report["backup"] = {"file_name": ARTIFACT_NAMES[0], "bytes": backup_info.st_size,
                            "sha256": backup_hash, **backup_meta}
        if shutil.disk_usage(parent).free < backup_info.st_size + RESERVE_BYTES:
            raise ProbeError("INSUFFICIENT_FREE_SPACE")
        _copy_new(backup, restored, check)
        restored_hash = _digest(restored, check)
        restored_meta = _metadata(restored, check)
        if (backup_hash != restored_hash or backup_meta != restored_meta
                or _digest(restored, check) != restored_hash):
            raise ProbeError("ISOLATED_RESTORE_MISMATCH")
        if _identity(_ordinary(source, "file")) != identity:
            raise ProbeError("SOURCE_REPLACED")
        descriptor = os.open(job_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        check()
        report.update({
            "passed": True, "isolated_restore_verified": True,
            "source_identity_unchanged": True,
            "restored_copy": {"file_name": ARTIFACT_NAMES[1], "bytes": restored.stat().st_size,
                              "sha256": restored_hash, **restored_meta},
            "retained_file_count": 2, "retained_total_bytes": backup_info.st_size * 2,
        })
    except ProbeError as exc:
        report["error_code"] = str(exc)
    except sqlite3.Error:
        report["error_code"] = "SQLITE_OPERATION_FAILED"
    except OSError:
        report["error_code"] = "FILESYSTEM_OPERATION_FAILED"
    except Exception:
        report["error_code"] = "UNEXPECTED_PROBE_FAILURE"
    report["artifact_state"] = "complete" if report["passed"] else "incomplete"
    if report["job_directory_created"]:
        retained = []
        for name in ARTIFACT_NAMES:
            try:
                info = (job_dir / name).lstat()
                if stat.S_ISREG(info.st_mode):
                    retained.append({"file_name": name, "bytes": info.st_size})
            except OSError:
                pass
        report["retained_files"] = retained
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path)
    args = parser.parse_args()
    source = Path("/app/data/logic_data.db")
    job_dir = args.job_dir or source.parent / "backups" / (
        "collector-validation-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-" + uuid.uuid4().hex[:12])
    priority_adjusted = False
    try:
        os.nice(10)
        priority_adjusted = True
    except OSError:
        pass

    def alarm_handler(signum, frame):
        raise ProbeError("PROBE_TIMEOUT")

    signal.signal(signal.SIGALRM, alarm_handler)
    signal.alarm(MAX_TIMEOUT_SECONDS)
    try:
        result = create_verified_backup(source, job_dir)
    finally:
        signal.alarm(0)
    result["priority_adjusted"] = priority_adjusted
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
