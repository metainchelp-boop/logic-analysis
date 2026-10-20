"""Fixed 382f/Foodin prepare probe. No writer, worker, HTTP or provider calls.

The host controller must prove the current image and operation before invoking
this source on stdin as uid 10001, Python -I -B, with a 30-second outer timeout.
"""
import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import sys
import time

PROFILE_SHA256 = "df48451e12d4dced2a4e3abaae9e7144ebedc2854791ae777d85ada03a4d5040"
SOURCE = "382f143ad72a5fb0389d79ba0fac199566016e8b"
OPERATION = "98dc5ca60ef2a65f9c9399b8cad1f7d9"
MODE = "foodin-strategy-prepare-382f-once-v1"
ROOT = Path("/opt/naver-engine")
DATABASE = Path("/var/lib/naver-engine/engine.db")
MAX_OUTPUT = 16384
MAX_SECONDS = 20
KST = timezone(timedelta(hours=9))
RUNTIME_EXCLUDED = frozenset((
    "backend/app/naver_entry.py", "backend/app/naver_relay.py",
    "backend/app/routers/__init__.py", "backend/app/routers/naver.py",
    "deploy/naver-backup-receiver.py", "deploy/naver-erp-tunnel/test_policy.py",
))
FAILURES = frozenset((
    "PROFILE", "IDENTITY", "CODE_PIN", "SOURCE_IMPORT", "DATABASE",
    "SCHEMA", "DEADLINE", "MUTATION", "OUTPUT", "NETWORK_FORBIDDEN",
    "PROCESS_FORBIDDEN", "UNEXPECTED",
))


def canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()


def need(value, code):
    if not value:
        raise ProbeRefused(code)


class ProbeRefused(Exception):
    pass


def check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise ValueError('SOURCE_DIAGNOSTICS_DEADLINE')


def readonly_authorizer(action, arg1, arg2, database, source):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_TRANSACTION,
                  sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (arg2 or '').lower() in (
            'load_extension', 'readfile', 'writefile', 'shell', 'eval', 'fts3_tokenizer') else sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg2 is None and (arg1 or '').lower() in ('query_only', 'database_list'):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and (arg1 or '').lower() == 'table_info' and arg2 == 'naver_auto_link_memory':
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connect_reader(path):
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ValueError('SOURCE_DIAGNOSTICS_DATABASE_PATH')
    connection = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, isolation_level=None, timeout=1)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA busy_timeout=1000')
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.set_authorizer(readonly_authorizer)
        if tuple(connection.execute('PRAGMA query_only').fetchone()) != (1,):
            raise ValueError('SOURCE_DIAGNOSTICS_READER_MODE')
        if [tuple(row) for row in connection.execute('PRAGMA database_list').fetchall()] != [(0, 'main', str(path))]:
            raise ValueError('SOURCE_DIAGNOSTICS_DATABASE_PATH')
        return connection
    except Exception:
        connection.close()
        raise


class DiscardOutput:
    """No application stdout/stderr is retained or forwarded."""
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def profile_valid(profile):
    need(type(profile) is dict and hashlib.sha256(canonical(profile)).hexdigest() == PROFILE_SHA256, "PROFILE")
    need(profile["source_commit"] == SOURCE and profile["apply_operation"] == OPERATION, "PROFILE")
    need(len(profile["code_pins"]) == 115 and profile["actor"] == 0 and profile["narrowed"] is False, "PROFILE")
    return profile


def runtime_pins(profile):
    # Dockerfile.naver-engine has exactly these four COPY source paths.
    # Preserve all 115 archive pins; only its 109 image Python files exist here.
    all_pins = profile["code_pins"]
    selected = {name: pin for name, pin in all_pins.items()
                if name.startswith(("naver_engine/", "naver_runtime/", "backend/app/naver_auto/"))
                or name == "backend/app/__init__.py"}
    need(len(all_pins) == 115 and len(selected) == 109
         and set(all_pins) - set(selected) == RUNTIME_EXCLUDED, "CODE_PIN")
    return selected


def pin_sources(profile):
    for relative, digest in runtime_pins(profile).items():
        need(type(relative) is str and relative.endswith(".py") and ".." not in Path(relative).parts
             and not Path(relative).is_absolute() and Path(relative).name != "store 2.py", "CODE_PIN")
        path = ROOT / relative
        need(not path.is_symlink() and path.resolve() == path and path.is_file()
             and path.stat().st_size <= 1048576, "CODE_PIN")
        need(hashlib.sha256(path.read_bytes()).hexdigest() == digest, "CODE_PIN")


def deny_network(*args, **kwargs):
    raise ProbeRefused("NETWORK_FORBIDDEN")


def audit_boundary(event, args):
    # The reader never launches an external process or creates/connects a socket.
    if event.startswith("socket."):
        raise ProbeRefused("NETWORK_FORBIDDEN")
    if event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork"}:
        raise ProbeRefused("PROCESS_FORBIDDEN")


def exception_sites(error, profile):
    sites = {(p, f, line): code for p, f, line, code in profile["trace_sites"]}
    prepare_site, leaf_site = "UNOBSERVED", "UNREGISTERED"
    node = error.__traceback__
    while node is not None:
        code = node.tb_frame.f_code
        filename = code.co_filename
        relative = filename.removeprefix(str(ROOT) + "/") if filename.startswith(str(ROOT) + "/") else None
        if relative == "naver_engine/store.py" and code.co_name == "prepare_learning_strategy":
            prepare_site = profile["prepare_sites"].get(str(node.tb_lineno), "UNREGISTERED")
        # Only the actual innermost frame is considered a leaf. Never upgrade
        # a known caller to the leaf when an unregistered function raised.
        leaf_site = sites.get((relative, code.co_name, node.tb_lineno), "UNREGISTERED")
        node = node.tb_next
    return prepare_site, leaf_site


def error_kind(error, store_module):
    if isinstance(error, store_module.StoreRefused):
        return "store-refused"
    if isinstance(error, sqlite3.Error):
        number = getattr(error, "sqlite_errorcode", None)
        number = number & 255 if type(number) is int else None
        if number in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return "sqlite-busy"
        if number == sqlite3.SQLITE_INTERRUPT:
            return "sqlite-interrupted"
        return "sqlite-error"
    if isinstance(error, (ValueError, TypeError, KeyError, AttributeError)):
        return "shape"
    return "internal"


def probe_once(reader, store_module, jobs_module, profile, now, deadline):
    """The sole product prepare call; no retry and no mutation-capable API."""
    request = profile["request"]
    check_deadline(deadline)
    try:
        prepared = reader.prepare_learning_strategy(
            request["report_id"], request["account_key"], request["revision_fingerprint"],
            profile["actor"], now, request["expected_version"], narrowed=profile["narrowed"],
        )
    except Exception as error:
        prepare_site, leaf_site = exception_sites(error, profile)
        return dict(outcome="prepare-failed", prepare_calls=1, phase="prepare",
                    prepare_site=prepare_site, leaf_site=leaf_site,
                    error_kind=error_kind(error, store_module),
                    global_active_count=None, retry_identity_equal=None)
    del prepared
    check_deadline(deadline)
    try:
        rows = reader.learning_strategy_jobs()
        need(type(rows) is list and len(rows) <= jobs_module.LIMIT == 100, "OUTPUT")
        request_identity = jobs_module.identity(
            profile["actor"], profile["narrowed"], request["report_id"], request["account_key"],
            request["revision_fingerprint"], request["expected_version"],
        )
        matching = [row for row in rows if row["job_id"] == request["retry_job_id"]]
        need(len(matching) <= 1, "OUTPUT")
        same = bool(matching and jobs_module.identity(
            matching[0]["actor"], matching[0]["narrowed"], matching[0]["report_id"],
            matching[0]["account_key"], matching[0]["revision_fingerprint"], matching[0]["expected_version"],
        ) == request_identity)
        count = sum(row["state"] in jobs_module.ACTIVE for row in rows)
        return dict(outcome="prepare-passed", prepare_calls=1, phase="metadata",
                    prepare_site=None, leaf_site=None, error_kind=None,
                    global_active_count=count, retry_identity_equal=same)
    except Exception as error:
        _, leaf_site = exception_sites(error, profile)
        return dict(outcome="metadata-failed", prepare_calls=1, phase="metadata",
                    prepare_site=None, leaf_site=leaf_site,
                    error_kind=error_kind(error, store_module),
                    global_active_count=None, retry_identity_equal=None)


def validate_result(result, profile):
    names = {"outcome", "prepare_calls", "phase", "prepare_site", "leaf_site",
             "error_kind", "global_active_count", "retry_identity_equal"}
    need(type(result) is dict and set(result) == names
         and type(result["prepare_calls"]) is int and result["prepare_calls"] == 1, "OUTPUT")
    need(type(result["outcome"]) is str and result["outcome"] in {"prepare-failed", "prepare-passed", "metadata-failed"}
         and type(result["phase"]) is str and result["phase"] in {"prepare", "metadata"}, "OUTPUT")
    leaves = {item[3] for item in profile["trace_sites"]} | {"UNREGISTERED"}
    callers = set(profile["prepare_sites"].values()) | {"UNOBSERVED", "UNREGISTERED"}
    if result["outcome"] == "prepare-passed":
        need(result["phase"] == "metadata" and all(result[k] is None for k in ("prepare_site", "leaf_site", "error_kind"))
             and type(result["global_active_count"]) is int and 0 <= result["global_active_count"] <= 100
             and type(result["retry_identity_equal"]) is bool, "OUTPUT")
    else:
        need(result["global_active_count"] is None and result["retry_identity_equal"] is None
             and type(result["leaf_site"]) is str and result["leaf_site"] in leaves
             and type(result["error_kind"]) is str and result["error_kind"] in {
                 "store-refused", "sqlite-busy", "sqlite-interrupted", "sqlite-error", "shape", "internal"},
             "OUTPUT")
        need((result["outcome"] == "prepare-failed" and result["phase"] == "prepare"
              and type(result["prepare_site"]) is str and result["prepare_site"] in callers)
             or (result["outcome"] == "metadata-failed" and result["phase"] == "metadata" and result["prepare_site"] is None),
             "OUTPUT")
    need(len(canonical(result)) <= MAX_OUTPUT, "OUTPUT")
    return result


def run_probe(profile):
    """Entrypoint for the isolated, host-guarded container subprocess only."""
    connection = reader = None
    opened = False
    try:
        profile_valid(profile)
        need(os.geteuid() == 10001, "IDENTITY")
        os.environ.clear()
        socket.socket.connect = socket.socket.connect_ex = deny_network
        sys.addaudithook(audit_boundary)
        pin_sources(profile)
        sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
        with contextlib.redirect_stdout(DiscardOutput()), contextlib.redirect_stderr(DiscardOutput()):
            from naver_engine import store as S
            from naver_runtime import learning_jobs as J
            deadline = time.monotonic() + MAX_SECONDS
            connection = connect_reader(DATABASE)
            opened = True
            reader = S.Store(connection, str(DATABASE), None, writer=False)
            need(reader.writer is False, "IDENTITY")
            connection.set_progress_handler(lambda: time.monotonic() >= deadline, 1000)
            connection.execute("BEGIN")
            schema_row = connection.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()
            need(schema_row is not None and tuple(schema_row) == ("21",), "SCHEMA")
            value = probe_once(reader, S, J, profile, datetime.now(KST), deadline)
            need(connection.total_changes == 0 and connection.in_transaction, "MUTATION")
            check_deadline(deadline)
            validate_result(value, profile)
            connection.execute("ROLLBACK")
        return dict(ok=True, mode=MODE, source_commit=SOURCE, apply_operation=OPERATION,
                    reader_mode="sqlite-mode-ro-query-only-authorizer", database_opened=True,
                    mutations=0, provider_calls=0, current_request_replay=True, diagnostic=value)
    except BaseException as error:
        code = error.args[0] if type(error) is ProbeRefused and len(error.args) == 1 and type(error.args[0]) is str and error.args[0] in FAILURES else "UNEXPECTED"
        if type(error) is ValueError and error.args == ("SOURCE_DIAGNOSTICS_DEADLINE",):
            code = "DEADLINE"
        return dict(ok=False, mode=MODE, source_commit=SOURCE, apply_operation=OPERATION,
                    database_opened=opened, mutations=0, provider_calls=0, error_code=code)
    finally:
        if connection is not None:
            try:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
            finally:
                if reader is not None:
                    reader.close()
                else:
                    connection.close()
