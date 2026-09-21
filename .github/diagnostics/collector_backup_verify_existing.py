"""Read-only continuation of the approved backup validation; no new artifacts.

Run as stdin to python3 with --phase digests or --phase restored_metadata. Both phases
inspect only the two retained artifacts from the stated baseline run. The caller
must encrypt stdout. Never open the operating DB or import application modules.
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
import signal
import sqlite3
import stat
import sys
import time


BASELINE_RUN_ID = "35574538134"
JOB_DIRECTORY = Path("/app/data/backups/collector-validation-20260921-op1")
ARTIFACT_NAMES = ("backup.sqlite", "restored-copy.sqlite")
MAX_TIMEOUT_SECONDS = 180
EXPECTED = {
    "bytes": 2717564928,
    "sha256": "8aaa008766cac18a3d1cd3541065530a82362f812cfc3bc12d0feb82a0622205",
    "ordinary_table_count": 42,
    "schema_sha256": "4203e3cbe1bc07a158d822034ac68b3e14d751139830f5ed004cb065c6e1c319",
    "all_ordinary_table_counts_sha256": "d96cd431ab4ff1102086c2cbb2ba210fcffa08f24cfd8f389001fba8e1d879cf",
}


class VerifyError(Exception):
    """Only fixed error codes; never wrap raw error messages."""


def _ordinary(path, directory=False):
    if path.resolve() != path or path.is_symlink():
        raise VerifyError("PATH_ALIAS_FORBIDDEN")
    info = path.stat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise VerifyError("ORDINARY_PATH_REQUIRED")
    if not directory and info.st_nlink != 1:
        raise VerifyError("FILE_ALIAS_FORBIDDEN")
    return info


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _standalone(path):
    for suffix in ("-wal", "-shm", "-journal"):
        candidate = Path(str(path) + suffix)
        if candidate.exists() or candidate.is_symlink():
            raise VerifyError("STANDALONE_ARTIFACT_REQUIRED")


def _hash_file(path, expected_stamp, check):
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as handle:
        if _stamp(os.fstat(handle.fileno())) != expected_stamp:
            raise VerifyError("ARTIFACT_CHANGED")
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            check()
            digest.update(block)
        if _stamp(os.fstat(handle.fileno())) != expected_stamp:
            raise VerifyError("ARTIFACT_CHANGED")
    check()
    return digest.hexdigest()


def _metadata(path, check):
    # These standalone, previously created artifacts are not live databases.
    # immutable=1 additionally prevents journal/SHM creation and locking writes.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1",
                                 uri=True, timeout=1)) as conn:
        conn.set_progress_handler(lambda: int(time.monotonic() >= check.deadline), 1000)
        conn.execute("PRAGMA temp_store=MEMORY")
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise VerifyError("RESTORED_INTEGRITY_FAILED")
        if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
            raise VerifyError("STANDALONE_ARTIFACT_REQUIRED")
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
            "schema_sha256": hashlib.sha256(encode(schema)).hexdigest(),
            "all_ordinary_table_counts_sha256": hashlib.sha256(encode(counts)).hexdigest(),
        }
    check()
    return result


def verify_existing(phase, job_dir=JOB_DIRECTORY, expected=None,
                    timeout_seconds=MAX_TIMEOUT_SECONDS):
    """Run one bounded, read-only phase; only both phases together prove success."""
    started = time.monotonic()
    report = {
        "probe_version": 1, "passed": False, "read_only": True,
        "source_database_opened": False, "files_created": 0,
        "baseline_run_id": BASELINE_RUN_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "sqlite_version": sqlite3.sqlite_version,
        "completion_scope": "this phase only; digests and restored_metadata must both pass",
    }
    try:
        if phase not in ("digests", "restored_metadata"):
            raise VerifyError("INVALID_PHASE")
        report["phase"] = phase
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS):
            raise VerifyError("INVALID_TIMEOUT")
        expected = dict(EXPECTED if expected is None else expected)
        if (set(expected) != set(EXPECTED) or type(expected["bytes"]) is not int
                or not 0 < expected["bytes"] <= 4 * 1024**3
                or type(expected["ordinary_table_count"]) is not int
                or expected["ordinary_table_count"] < 0
                or any(not isinstance(expected[key], str)
                       or not re.fullmatch(r"[0-9a-f]{64}", expected[key])
                       for key in ("sha256", "schema_sha256", "all_ordinary_table_counts_sha256"))):
            raise VerifyError("INVALID_EXPECTED_METADATA")

        def check():
            if time.monotonic() >= check.deadline:
                raise VerifyError("PHASE_TIMEOUT")

        check.deadline = started + timeout_seconds
        job_dir = Path(job_dir).absolute()
        _ordinary(job_dir, directory=True)
        paths = {name: job_dir / name for name in ARTIFACT_NAMES}
        stamps = {}
        for name, path in paths.items():
            info = _ordinary(path)
            _standalone(path)
            if info.st_size != expected["bytes"]:
                raise VerifyError("ARTIFACT_SIZE_MISMATCH")
            stamps[name] = _stamp(info)
        report["artifact_stat_fields"] = ["device", "inode", "mode", "links", "bytes",
                                          "modified_ns", "changed_ns"]
        report["artifact_stats_before"] = {name: list(value) for name, value in stamps.items()}
        check()
        if phase == "digests":
            hashes = {name: _hash_file(path, stamps[name], check) for name, path in paths.items()}
            if any(value != expected["sha256"] for value in hashes.values()):
                raise VerifyError("ARTIFACT_DIGEST_MISMATCH")
            report["artifacts"] = [{"file_name": name, "bytes": expected["bytes"],
                                    "sha256": hashes[name]} for name in ARTIFACT_NAMES]
        else:
            if sqlite3.sqlite_version_info < (3, 37, 0):
                raise VerifyError("SQLITE_TABLE_LIST_REQUIRED")
            metadata = _metadata(paths["restored-copy.sqlite"], check)
            if any(metadata[key] != expected[key] for key in (
                    "ordinary_table_count", "schema_sha256", "all_ordinary_table_counts_sha256")):
                raise VerifyError("RESTORED_METADATA_MISMATCH")
            report["restored_copy"] = {"file_name": "restored-copy.sqlite", **metadata}
        final_stamps = {}
        for name, path in paths.items():
            _standalone(path)
            final_stamps[name] = _stamp(_ordinary(path))
        report["artifact_stats_after"] = {name: list(value) for name, value in final_stamps.items()}
        for name in ARTIFACT_NAMES:
            if final_stamps[name] != stamps[name]:
                raise VerifyError("ARTIFACT_CHANGED")
        check()
        report.update({"passed": True, "artifact_stats_unchanged": True})
    except VerifyError as exc:
        report["error_code"] = str(exc)
    except sqlite3.Error:
        report["error_code"] = ("PHASE_TIMEOUT" if time.monotonic() - started >= timeout_seconds
                                else "SQLITE_VERIFICATION_FAILED")
    except OSError:
        report["error_code"] = "FILESYSTEM_VERIFICATION_FAILED"
    except Exception:
        report["error_code"] = "UNEXPECTED_VERIFICATION_FAILURE"
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("digests", "restored_metadata"), required=True)
    args = parser.parse_args()
    priority_adjusted = False
    try:
        os.nice(10)
        priority_adjusted = True
    except OSError:
        pass

    def alarm_handler(signum, frame):
        raise VerifyError("PHASE_TIMEOUT")

    signal.signal(signal.SIGALRM, alarm_handler)
    signal.alarm(MAX_TIMEOUT_SECONDS)
    try:
        result = verify_existing(args.phase)
    finally:
        signal.alarm(0)
    result["priority_adjusted"] = priority_adjusted
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
