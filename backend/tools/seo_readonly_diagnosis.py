"""Bounded, memory-only Docker reads; emit only an allowlisted SEO summary.

Run on the VPS with ``python3 -I -B -``. Never imports the application, opens
its database, calls a provider, or stores raw inspect/log/probe output on disk.
"""
import datetime as dt
import json
import re
import selectors
import subprocess
import time
from collections import namedtuple


UTC = dt.timezone.utc
KST = dt.timezone(dt.timedelta(hours=9))
EVENTS = ("provider_error", "provider_response_received", "json_parse_failed", "context_skipped")
CATEGORIES = ("auth", "credit", "rate_limit", "model_access", "request_invalid", "upstream", "network", "unknown")
MODELS = frozenset((
    "claude-sonnet-4-6", "claude-opus-4-6", "claude-opus-4-1-20250805",
    "claude-sonnet-4-5", "claude-sonnet-4-5-20250929", "claude-haiku-4-5",
    "claude-haiku-4-5-20251001", "claude-sonnet-4-20250514", "claude-opus-4-20250514",
    "claude-3-7-sonnet-20250219", "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
))
CommandResult = namedtuple("CommandResult", "output state returncode")
INSPECT_FORMAT = ('{"container_id":{{json .Id}},"image_id":{{json .Image}},'
                  '"started_at":{{json .State.StartedAt}},"restart_count":{{json .RestartCount}},'
                  '"log_driver":{{json .HostConfig.LogConfig.Type}},'
                  '"rotation":{{json .HostConfig.LogConfig.Config}}}')

# This isolated child only reads environment and one source file. No app import,
# DB, tempfile, network, subprocess, bytecode, or source evaluation is permitted.
PROBE_CODE = '''import ast, hashlib, json, os
allowed_models = MODELS_LITERAL
result = {"key_configured": bool(os.environ.get("CLAUDE_API_KEY")),
          "model": "unverified", "model_state": "unverified",
          "source_sha256": None, "read_state": "partial"}
try:
    with open("/app/seo_generate.py", "rb") as source_file:
        source = source_file.read(1048577)
    if len(source) <= 1048576:
        result["source_sha256"] = hashlib.sha256(source).hexdigest()
        result["read_state"] = "complete"
        model = os.environ.get("CLAUDE_MODEL")
        if model is None:
            for node in ast.parse(source).body:
                if (isinstance(node, ast.Assign) and
                    any(isinstance(t, ast.Name) and t.id == "CLAUDE_MODEL" for t in node.targets) and
                    isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute) and
                    isinstance(node.value.func.value, ast.Name) and node.value.func.value.id == "os" and
                    node.value.func.attr == "getenv" and len(node.value.args) == 2 and
                    isinstance(node.value.args[0], ast.Constant) and node.value.args[0].value == "CLAUDE_MODEL" and
                    isinstance(node.value.args[1], ast.Constant)):
                    model = node.value.args[1].value
        if isinstance(model, str) and model in allowed_models:
            result["model"], result["model_state"] = model, "verified"
except Exception:
    result["read_state"] = "partial"
print(json.dumps(result, sort_keys=True))
'''.replace("MODELS_LITERAL", repr(tuple(sorted(MODELS))))


def run_command(command, *, timeout, max_bytes):
    """Capture both pipes in bounded RAM, without a shell or raw error output."""
    output = bytearray()
    state = "complete"
    process = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=False)
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            selector.register(process.stderr, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    state = "timeout"
                    break
                for key, _ in selector.select(min(remaining, 0.2)):
                    chunk = key.fileobj.read1(min(65536, max_bytes - len(output) + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > max_bytes:
                            del output[max_bytes:]
                            state = "byte_limit"
                            break
                if state != "complete":
                    break
        if state != "complete":
            process.kill()
        returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        if returncode != 0 and state == "complete":
            state = "read_failed"
        return CommandResult(bytes(output), state, returncode)
    except subprocess.TimeoutExpired:
        return CommandResult(bytes(output), "timeout", None)
    except Exception:
        return CommandResult(bytes(output), "read_failed", None)
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=1)
            process.stdout.close()
            process.stderr.close()


def _timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-]\d\d:\d\d)", value):
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _iso(value, zone=UTC):
    return value.astimezone(zone).isoformat(timespec="seconds").replace("+00:00", "Z") if value else None


def _times(prefix, value):
    return {prefix + "_utc": _iso(value), prefix + "_kst": _iso(value, KST)}


def _read(runner, command, timeout=5, max_bytes=65536):
    try:
        result = runner(command, timeout=timeout, max_bytes=max_bytes)
        state = result.state if result.state in ("complete", "timeout", "byte_limit", "read_failed") else "read_failed"
        output = result.output if isinstance(result.output, bytes) else b""
        if len(output) > max_bytes:
            output, state = output[:max_bytes], "byte_limit"
        if result.returncode != 0 and state == "complete":
            state = "read_failed"
        return CommandResult(output, state, result.returncode)
    except Exception:
        return CommandResult(b"", "read_failed", None)


def _json(result):
    if result.state != "complete":
        return None
    try:
        value = json.loads(result.output)
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeError):
        return None


def _container(value):
    if not isinstance(value, dict):
        return None
    cid, image = value.get("container_id"), value.get("image_id")
    started, restarts = _timestamp(value.get("started_at")), value.get("restart_count")
    if (not isinstance(cid, str) or not re.fullmatch(r"[a-f0-9]{64}", cid)
            or not isinstance(image, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image)
            or started is None or type(restarts) is not int or restarts < 0):
        return None
    rotation = value.get("rotation")
    rotation = rotation if isinstance(rotation, dict) else {}
    size, files = rotation.get("max-size"), rotation.get("max-file")
    safe_rotation = {"max_size": size if isinstance(size, str) and re.fullmatch(r"\d{1,10}[kKmMgG]?", size) else None,
                     "max_file": int(files) if isinstance(files, str) and re.fullmatch(r"\d{1,6}", files) else None}
    driver = value.get("log_driver")
    driver = driver if driver in ("json-file", "local", "journald", "syslog", "none", "fluentd", "awslogs", "gelf", "splunk", "gcplogs") else "unverified"
    return {"name": "logic-analysis", "container_id": cid, "image_id": image,
            **_times("started", started), "restart_count": restarts,
            "log_driver": driver, "rotation": safe_rotation}


def _runtime(value):
    value = value if isinstance(value, dict) else {}
    model = value.get("model")
    model = model if isinstance(model, str) and model in MODELS else "unverified"
    source_hash = value.get("source_sha256")
    source_hash = source_hash if isinstance(source_hash, str) and re.fullmatch(r"[a-f0-9]{64}", source_hash) else None
    key = value.get("key_configured")
    return {"key_configured": key if type(key) is bool else None, "model": model,
            "model_state": "verified" if model != "unverified" else "unverified",
            "source_sha256": source_hash,
            "read_state": "complete" if value.get("read_state") == "complete" and source_hash and type(key) is bool and model != "unverified" else "partial"}


def _status_and_category(payload):
    status_match = re.search(r'(?:Error code:\s*|status(?:_code)?[=:\s]+|["\x27]status(?:_code)?["\x27]\s*:\s*|HTTP(?:/\d(?:\.\d)?)?\s+)([1-5]\d\d)\b', payload, re.I)
    status = int(status_match.group(1)) if status_match else None
    category_match = re.search(r"\bcategory=(auth|credit|rate_limit|model_access|request_invalid|upstream|network|unknown)\b", payload)
    if category_match:
        return status, category_match.group(1)
    lower = payload.lower()
    if any(marker in lower for marker in ("credit balance", "insufficient credit", "insufficient_quota", "billing")):
        category = "credit"
    elif status == 401 or any(marker in lower for marker in ("authentication_error", "invalid api key", "invalid x-api-key")):
        category = "auth"
    elif status == 429 or "rate_limit" in lower or "rate limit" in lower:
        category = "rate_limit"
    elif status in (403, 404) or ("model" in lower and any(marker in lower for marker in ("not found", "not available", "access", "permission"))):
        category = "model_access"
    elif status is not None and status >= 500:
        category = "upstream"
    elif any(marker in lower for marker in ("connection", "network", "timed out", "timeout", "connecterror")):
        category = "network"
    elif status in (400, 413, 422) or "invalid_request_error" in lower:
        category = "request_invalid"
    else:
        category = "unknown"
    return status, category


def _event(payload):
    match = re.match(r"event=(provider_error|provider_response_received|json_parse_failed|context_skipped)\b", payload)
    if match:
        return match.group(1)
    for prefix, event in (("Claude 호출 오류:", "provider_error"), ("JSON 파싱 실패:", "json_parse_failed"),
                          ("네이버 컨텍스트 수집 실패(스킵):", "context_skipped")):
        if payload.startswith(prefix):
            return event
    if re.fullmatch(r"'.*' by .* \(tokens in=[^,]+, out=[^)]+\)", payload):
        return "provider_response_received"
    return None


def _stats(times, readable):
    daily_utc, daily_kst = {}, {}
    for moment in times:
        for target, zone in ((daily_utc, UTC), (daily_kst, KST)):
            day = moment.astimezone(zone).date().isoformat()
            target[day] = target.get(day, 0) + 1
    return {"count": len(times) if readable else None,
            **_times("first", min(times) if times else None), **_times("last", max(times) if times else None),
            "daily_utc": dict(sorted(daily_utc.items())), "daily_kst": dict(sorted(daily_kst.items()))}


def _summarize(result, until):
    events = {key: [] for key in EVENTS}
    categories = {key: [] for key in CATEGORIES}
    status_counts, retained, invalid_timestamps = {}, [], 0
    readable = result.state == "complete" or bool(result.output)
    for line in result.output.decode("utf-8", "replace").splitlines():
        stamp, _, message = line.partition(" ")
        moment = _timestamp(stamp)
        if moment is None or moment > until:
            invalid_timestamps += 1
            continue
        retained.append(moment)
        if "[SEO생성]" not in message:
            continue
        payload = message.split("[SEO생성]", 1)[1].strip()
        event = _event(payload)
        if event:
            events[event].append(moment)
            if event == "provider_error":
                status, category = _status_and_category(payload)
                categories[category].append(moment)
                if status is not None:
                    status_counts[str(status)] = status_counts.get(str(status), 0) + 1
    state = result.state if result.state != "complete" else ("partial" if invalid_timestamps else "complete")
    return {"read_state": state, "observed_retained_lines": len(retained) if readable else None,
            "unparseable_or_outside_cutoff_lines": invalid_timestamps if readable else None,
            "range": {**_times("until", until), **_times("first_retained", min(retained) if retained else None),
                      **_times("last_retained", max(retained) if retained else None)},
            "events": {key: _stats(value, readable) for key, value in events.items()},
            "errors_by_category": {key: _stats(value, readable) for key, value in categories.items()},
            "http_status_counts": dict(sorted(status_counts.items()))}


def diagnose(*, runner=run_command, now=None):
    """Return only safe fields. Partial reads never establish historical totals."""
    started = _timestamp(now) if now is not None else dt.datetime.now(UTC)
    if started is None:
        raise ValueError("invalid diagnosis time")
    started = started.replace(microsecond=0)
    report = {"schema_version": 1, **_times("diagnosis_started", started), "state": "unverified",
              "business_generation_success": "unverified", "container_stable": None,
              "limitations": ["retained_first_is_not_incident_start", "provider_response_is_not_business_success",
                              "unlogged_key_missing_and_timeouts_unverified", "only_retained_logs_observed"],
              "reasons": [], "container": None, "runtime": _runtime(None),
              "logs": _summarize(CommandResult(b"", "read_failed", None), started)}
    inspect_command = ["docker", "inspect", "--format", INSPECT_FORMAT, "logic-analysis"]
    before = _container(_json(_read(runner, inspect_command)))
    if before is None:
        report["reasons"].append("container_source_unverified")
        return report
    report["container"] = before
    cid = before["container_id"]
    runtime = _read(runner, ["docker", "exec", cid, "python3", "-I", "-B", "-c", PROBE_CODE], timeout=10)
    report["runtime"] = _runtime(_json(runtime))
    if report["runtime"]["read_state"] != "complete":
        report["reasons"].append("runtime_read_partial")
    logs = _read(runner, ["docker", "logs", "--timestamps", "--until", _iso(started), cid],
                 timeout=40, max_bytes=32 * 1024 * 1024)
    report["logs"] = _summarize(logs, started)
    if report["logs"]["read_state"] != "complete":
        report["reasons"].append("logs_read_partial")
    after = _container(_json(_read(runner, inspect_command)))
    report["container_stable"] = before == after if after is not None else None
    if report["container_stable"] is not True:
        report["reasons"].append("container_changed_or_unverified")
    report["state"] = "partial" if report["reasons"] else "complete"
    return report


def main():
    try:
        report = diagnose()
    except Exception:
        # Never serialize an exception, command output, environment, or traceback.
        report = {"schema_version": 1, "state": "unverified", "reasons": ["diagnosis_failed"],
                  "business_generation_success": "unverified"}
    print(json.dumps(report, sort_keys=True, ensure_ascii=True))


if __name__ == "__main__":
    main()
