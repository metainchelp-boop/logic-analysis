"""One-off, stdlib-only probe. Its JSON stdout must be encrypted by the caller.

Run with ``docker exec -i logic-analysis python3 -`` and feed this file on stdin.
No application modules are imported. Stored rows are not an upload event log:
the application replaces a keyword/day row after a subsequent upload.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import time


QUERY_TIMEOUT_SECONDS = 10.0
VERSION_PATTERN = re.compile(r"[0-9]{1,4}(?:\.[0-9]{1,4}){1,3}")
TIME_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}")
ERROR_CODES = {
    "AUTH_REQUIRED", "LOGIN_REDIRECT", "BLOCK_TEXT", "BLOCKED", "REDIRECT",
    "NO_LIST", "NO_NEXT_DATA", "NO_PAGER", "STALE_PAGE", "SAME_AS_PREV",
    "TAP_PROBE", "CAPTCHA", "TIMEOUT", "STATUS_AUTH_ERROR", "STATUS_HTTP_ERROR",
}


def safe_time(value):
    return value if isinstance(value, str) and TIME_PATTERN.fullmatch(value) else None


def safe_version(value):
    if value is None or value == "":
        return "missing"
    return value if isinstance(value, str) and VERSION_PATTERN.fullmatch(value) else "invalid"


def safe_int(value):
    return value if type(value) is int else None


def error_labels(err, title, note):
    # Never emit a substring of arbitrary DB text, including parenthesized text.
    values = [value[:2048] if isinstance(value, str) else "" for value in (err, title, note)]
    token = re.split(r"[^A-Z_]", values[0].upper(), maxsplit=1)[0]
    code = token if token in ERROR_CODES else "OTHER"
    text = " ".join(values).lower()
    if any(word in text for word in ("auth", "login", "로그인", "인증")):
        category = "authentication"
    elif any(word in text for word in ("captcha", "자동입력", "보안문자")):
        category = "captcha"
    elif any(word in text for word in ("429", "rate_limit", "too many")):
        category = "rate_limit"
    elif code in {"STALE_PAGE", "SAME_AS_PREV"}:
        category = "stale_or_duplicate"
    elif code in {"NO_LIST", "NO_NEXT_DATA", "NO_PAGER"}:
        category = "page_structure"
    elif code == "TAP_PROBE":
        category = "diagnostic_probe"
    elif any(word in text for word in ("timeout", "timed out", "시간 초과")):
        category = "timeout"
    elif any(word in text.replace("차단 아님", "").replace("not blocked", "")
             for word in ("block", "차단", "비정상")):
        category = "blocked"
    elif code == "REDIRECT":
        category = "redirect"
    elif re.search(r"\bhttp\b|network|fetch|네트워크", text):
        category = "network_or_http"
    else:
        category = "other"
    return code, category


def select(conn, sql, parameters=()):
    if re.match(r"\s*SELECT\b", sql, re.IGNORECASE) is None:
        raise ValueError("Only SELECT is allowed")
    deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS
    conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    try:
        return conn.execute(sql, parameters).fetchall()
    finally:
        conn.set_progress_handler(None, 0)


def upload_days(conn):
    rows = select(conn, """SELECT date(created_at), COUNT(*),
        MIN(datetime(created_at)), MAX(datetime(created_at))
        FROM collected_serp
        WHERE created_at >= date('now','localtime','-2 days')
          AND created_at < date('now','localtime','+1 day')
        GROUP BY date(created_at) ORDER BY date(created_at)""")
    return [{"date": at[:10] if at else None, "stored_rows": count,
             "first_created_at": safe_time(first), "last_created_at": safe_time(last)}
            for day, count, first, last in rows
            for at in [safe_time(day + " 00:00:00") if isinstance(day, str) else None]]


def upload_hours(conn):
    rows = select(conn, """SELECT strftime('%H',created_at), COUNT(*)
        FROM collected_serp
        WHERE created_at >= date('now','localtime')
          AND created_at < date('now','localtime','+1 day')
        GROUP BY strftime('%H',created_at) ORDER BY strftime('%H',created_at)""")
    return [{"hour": int(hour) if hour is not None else None, "stored_rows": count}
            for hour, count in rows]


def latest_uploads(conn):
    rows = select(conn, """SELECT created_at, product_count, source, meta_json
        FROM collected_serp ORDER BY created_at DESC LIMIT 500""")
    versions = {}
    sources = {}
    counts = []
    times = []
    invalid_meta = 0
    for created_at, product_count, source, meta_json in rows:
        at = safe_time(created_at)
        if at:
            times.append(at)
        if safe_int(product_count) is not None:
            counts.append(product_count)
        source_label = source if source in ("extension", "api", "manual") else "other"
        sources[source_label] = sources.get(source_label, 0) + 1
        version = "missing"
        if meta_json:
            try:
                if not isinstance(meta_json, str) or len(meta_json) > 65536:
                    raise ValueError("Oversized or non-text metadata")
                meta = json.loads(meta_json)
                if not isinstance(meta, dict):
                    raise ValueError("Non-object metadata")
                version = safe_version(meta.get("collectorVersion"))
            except (ValueError, TypeError, RecursionError):
                invalid_meta += 1
                version = "invalid"
        bucket = versions.setdefault(version, {"rows": 0, "last_created_at": None})
        bucket["rows"] += 1
        if at and (bucket["last_created_at"] is None or at > bucket["last_created_at"]):
            bucket["last_created_at"] = at
    return {"sample_limit": 500, "sample_rows": len(rows),
            "first_created_at": min(times) if times else None,
            "last_created_at": max(times) if times else None,
            "collector_versions": versions, "source_counts": sources,
            "invalid_meta_rows": invalid_meta,
            "product_count": {"valid_rows": len(counts), "sum": sum(counts),
                              "min": min(counts) if counts else None,
                              "max": max(counts) if counts else None}}


def recent_blocks(conn):
    rows = select(conn, """SELECT at, err, ext_version, title, note
        FROM collector_blocks WHERE at >= datetime('now','localtime','-2 days')
        ORDER BY at DESC LIMIT 300""")
    groups = {}
    latest = []
    for at, err, version, title, note in rows:
        code, category = error_labels(err, title, note)
        at = safe_time(at)
        version = safe_version(version)
        hour = at[:13] + ":00:00" if at else None
        key = (hour, code, category, version)
        groups[key] = groups.get(key, 0) + 1
        if len(latest) < 20:
            latest.append({"at": at, "error_code": code, "category": category,
                           "collector_version": version})
    return {"window": "last_48_hours", "sample_limit": 300,
            "category_semantics": "text_heuristic_not_confirmed_cause",
            "sample_rows": len(rows), "limit_reached": len(rows) == 300,
            "groups": [{"hour": hour, "error_code": code, "category": category,
                        "collector_version": version, "rows": count}
                       for (hour, code, category, version), count in groups.items()],
            "latest_20": latest}


def request_status(conn):
    rows = select(conn, """SELECT
        CASE WHEN status IN ('pending','done') THEN status ELSE 'other' END AS state,
        COUNT(*), MIN(datetime(requested_at)), MAX(datetime(requested_at)),
        MAX(CASE WHEN typeof(attempts)='integer' THEN attempts END)
        FROM collect_requests GROUP BY state ORDER BY state""")
    return [{"status": status, "rows": count,
             "first_requested_at": safe_time(first), "last_requested_at": safe_time(last),
             "max_attempts": safe_int(attempts)}
            for status, count, first, last, attempts in rows]


def control_state(conn):
    # The deployed schema has worker/stopped/updated_at/updated_by. Never read who.
    rows = select(conn, """SELECT worker, stopped, updated_at
        FROM collector_control ORDER BY worker LIMIT 100""")
    return {"sample_limit": 100, "limit_reached": len(rows) == 100,
            "rows": [{"worker": safe_int(worker),
                      "stopped": bool(stopped) if type(stopped) is int and stopped in (0, 1) else None,
                      "updated_at": safe_time(at)} for worker, stopped, at in rows]}


def source_hashes():
    result = {}
    for name in ("main.py", "collector.py", "auth.py", "split_rule.py"):
        try:
            path = Path("/app") / name
            if not path.exists():
                result[name] = {"present": False}
                continue
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(65536), b""):
                    digest.update(block)
            result[name] = {"present": True, "sha256": digest.hexdigest()}
        except Exception as exc:
            result[name] = {"error_type": type(exc).__name__}
    return result


def main():
    result = {"probe_version": 1, "read_only": True,
              "row_count_semantics": "stored_rows_after_keyword_day_upsert",
              "environment_present": {name: bool(os.environ.get(name))
                                      for name in ("COLLECTOR_TOKEN", "API_KEY")},
              "source_files": source_hashes(), "errors": []}
    conn = None
    try:
        db_path = Path(os.environ.get("DIAG_DB_PATH", "/app/data/logic_data.db")).absolute()
        conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=2.0)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        utc, local = select(conn, "SELECT datetime('now'), datetime('now','localtime')")[0]
        result["sqlite_clock"] = {"utc": safe_time(utc), "local": safe_time(local)}
        for name, probe in (("uploads_last_3_calendar_days", upload_days),
                            ("uploads_today_by_hour", upload_hours),
                            ("latest_500_uploads", latest_uploads),
                            ("blocks_last_48_hours", recent_blocks),
                            ("collect_requests", request_status),
                            ("collector_control", control_state)):
            try:
                result[name] = probe(conn)
            except Exception as exc:
                result["errors"].append({"section": name, "error_type": type(exc).__name__})
    except Exception as exc:
        result["errors"].append({"section": "database", "error_type": type(exc).__name__})
    finally:
        if conn is not None:
            conn.close()
    print(json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(",", ":")))


if __name__ == "__main__":
    def deadline(_signal, _frame):
        raise SystemExit(124)
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(80)
    try:
        main()
    finally:
        signal.alarm(0)
