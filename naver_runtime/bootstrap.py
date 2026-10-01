"""서버 관리자가 놓은 한 번짜리 요청. 공개 관리 API/새 Writer/직접 네트워크 없음."""
from datetime import datetime, timedelta
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from naver_engine import store as S, sync as Y, links as L, morning as M, naver_read as N
from naver_engine.backup import private_directory, _publish

KEYS = frozenset({"request_id", "hold_id", "hold_sha256", "expected_rows", "approved_by",
                  "expires_at", "max_seconds"})
ERROR_CODES = frozenset({"REQUEST_SCHEMA", "REQUEST_FILE", "REQUEST_CHANGED", "REQUEST_EXPIRED",
                         "HOLD_CHANGED_OR_EXPIRED", "HOLD_DIGEST_CHANGED", "HOLD_ROWS_CHANGED",
                         "CURRENT_OWNER_REQUIRED", "SOURCES_NOT_TODAY", "SOURCES_UNUSABLE",
                         "RESTRICTED_CONFIG_REQUIRED", "CONFIRM_REFUSED", "PAIRING_REFUSED"})


class BootstrapRefused(ValueError):
    """고정 이유만 반환하며 입력/본문/개인정보를 싣지 않는다."""


def _error_code(error):
    if isinstance(error, BootstrapRefused):
        code = str(error)
        if code in ERROR_CODES:
            return code
    return "INTERNAL_ERROR"


@dataclass(frozen=True)
class BootstrapFiles:
    # 런타임에서는 기본값만 사용한다. 합성 파일 시험만 신뢰 주체를 명시적으로 주입한다.
    request: Path = Path("/var/lib/naver-engine/bootstrap-request.json")
    receipts: Path = Path("/var/lib/naver-engine/bootstrap")
    snapshots: Path = Path("/var/backups/naver-engine/bootstrap")
    request_uid: int = 0
    request_gid: int = 10001


def read_request(files, now):
    fd = None
    try:
        path = files.request
        if not path.is_absolute() or path != path.resolve():
            raise BootstrapRefused("REQUEST_FILE")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != files.request_uid
                or before.st_gid != files.request_gid or stat.S_IMODE(before.st_mode) != 0o440
                or before.st_nlink != 1 or not 0 < before.st_size <= 4096):
            raise BootstrapRefused("REQUEST_FILE")
        raw = os.read(fd, 4097)
        after, named = os.fstat(fd), path.lstat()
        stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns,
                           s.st_uid, s.st_gid, s.st_mode, s.st_nlink)
        if stamp(before) != stamp(after) or stamp(after) != stamp(named) or len(raw) != after.st_size:
            raise BootstrapRefused("REQUEST_CHANGED")
        return parse_request(raw, now)
    except OSError:
        raise BootstrapRefused("REQUEST_FILE") from None
    finally:
        if fd is not None:
            os.close(fd)


def publish_receipt(path, value):
    """600 임시 파일을 fsync한 뒤 exclusive link로 공개한다. 기존 이름은 덮지 않는다."""
    root = private_directory(path.parent)
    fd, name = tempfile.mkstemp(prefix=".bootstrap-", dir=root)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False).encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        _publish(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BootstrapRefused("REQUEST_SCHEMA")
        result[key] = value
    return result


def parse_request(raw, now):
    try:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= 4096:
            raise ValueError()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        if not isinstance(value, dict) or set(value) != KEYS:
            raise ValueError()
        if not isinstance(value["request_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", value["request_id"]):
            raise ValueError()
        if not isinstance(value["hold_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["hold_sha256"]):
            raise ValueError()
        for name, low, high in (("hold_id", 1, 2 ** 63 - 1), ("expected_rows", 1, 100000),
                                ("approved_by", 0, 0), ("max_seconds", 1, 600)):
            if type(value[name]) is not int or not low <= value[name] <= high:
                raise ValueError()
        expires = datetime.fromisoformat(value["expires_at"])
        if (expires.tzinfo is None or now.tzinfo is None or not now < expires <= now + S.HOLD_TTL
                or expires.astimezone(S.KST).date() != now.astimezone(S.KST).date()):
            raise ValueError()
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise BootstrapRefused("REQUEST_SCHEMA") from None


class BootstrapClock:
    """실제 시각은 바꾸지 않고 전체 작업의 대기/다음 송신/전송 timeout을 제한한다."""
    def __init__(self, base, seconds, expires):
        self.base = base
        self.deadline = min(base.now() + timedelta(seconds=seconds), expires)
        self.end = base.monotonic() + min(seconds, (self.deadline - base.now()).total_seconds())

    def remaining(self):
        self.base.before_network() if hasattr(self.base, "before_network") else None
        left = min(self.end - self.base.monotonic(), (self.deadline - self.base.now()).total_seconds())
        if left <= 0:
            raise N.RunAbort("bootstrap-time-budget")
        return left

    def before_network(self): self.remaining()
    def now(self): return self.base.now()  # 마감 이후에도 DB 회차 정리에는 실제 시각을 준다.
    def epoch_ms(self):
        self.remaining()
        return self.base.epoch_ms()
    def monotonic(self):
        self.remaining()
        return self.base.monotonic()
    def sleep(self, seconds):
        left = self.remaining()
        self.base.sleep(min(seconds, left))
        self.remaining()


def _verify(store, request, now):
    """Writer 한 차례 안에서 본문·당일 원본·재직 대표를 다시 대조한다."""
    if now >= datetime.fromisoformat(request["expires_at"]):
        raise BootstrapRefused("REQUEST_EXPIRED")
    hold = store.hold(S.SYNC_STAGES)
    if (hold is None or hold["hold_id"] != request["hold_id"] or hold["used_at"] is not None
            or now - hold["at"] > S.HOLD_TTL or hold["at"] > now + S.FUTURE_SLACK):
        raise BootstrapRefused("HOLD_CHANGED_OR_EXPIRED")
    if store.hold_body_sha256(S.SYNC_STAGES, request["hold_id"]) != request["hold_sha256"]:
        raise BootstrapRefused("HOLD_DIGEST_CHANGED")
    body = hold["body"]
    if len(body["rows"]) + len(body["conflicts"]) != request["expected_rows"]:
        raise BootstrapRefused("HOLD_ROWS_CHANGED")
    org = store.org_current()
    if org is None or Y.O.parse_org_snapshot(org["body"]).top_managers() != frozenset({0}):
        raise BootstrapRefused("CURRENT_OWNER_REQUIRED")
    today = now.astimezone(S.KST).date()
    sources = [hold["at"], datetime.fromisoformat(body["as_of"]), org["generated_at"], store.accounts_read_at()]
    if any(t is None or t.tzinfo is None or t.astimezone(S.KST).date() != today
           or t > now + S.FUTURE_SLACK for t in sources):
        raise BootstrapRefused("SOURCES_NOT_TODAY")
    if not Y.O.allows_raising(Y.org_freshness(store, now)) or L._accounts_unusable(store):
        raise BootstrapRefused("SOURCES_UNUSABLE")


def _counts(value):
    return {k: v for k, v in (value or {}).items()
            if isinstance(k, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", k)
            and type(v) is int and v >= 0}


def execute(config, env, writer, clock, reader_factory, *, files=None):
    """WEB가 열린 뒤 main thread에서 한 번 호출한다. scheduler보다 먼저, 외부 I/O는 Writer 밖."""
    location = env.get("NAVER_ENGINE_BOOTSTRAP_REQUEST")
    if not location:
        return {"status": "disabled"}  # 파일 조회조차 없음
    files = files or BootstrapFiles()
    receipt = None
    result = {"status": "refused", "phase": "preflight"}
    try:
        if (location != str(files.request) or not (config.sync_enabled and config.links_enabled
                and config.morning_enabled and config.web_enabled) or config.alerts_enabled
                or config.metrics_enabled or config.issue_alerts_enabled):
            raise BootstrapRefused("RESTRICTED_CONFIG_REQUIRED")
        request = read_request(files, clock.now())
        stem = "bootstrap-" + request["request_id"]
        receipt = files.receipts / (stem + ".json")
        # 어떤 기존 이름도 다시 실행하지 않는다(심볼릭 링크/손상된 파일 포함).
        if receipt.exists() or receipt.is_symlink():
            return {"status": "already_started", "request_id": request["request_id"]}
        writer.call(lambda st: _verify(st, request, clock.now()))
        result.update(request_id=request["request_id"], hold_id=request["hold_id"],
                      expected_rows=request["expected_rows"], approved_by=0)
        publish_receipt(receipt, dict(result, status="started", started_at=clock.now().isoformat()))
    except Exception as error:
        # preflight 오류에도 원문·경로·예외 문자열은 노출하지 않는다.
        result["error_code"] = _error_code(error)
        return result
    budget = BootstrapClock(clock, request["max_seconds"], datetime.fromisoformat(request["expires_at"]))
    try:
        result.update(status="failed_partial", phase="snapshot")
        private_directory(files.snapshots.parent)
        snapshots = private_directory(files.snapshots)
        snapshot = snapshots / (request["request_id"] + ".sqlite")
        def snapshot_then_confirm(st):
            _verify(st, request, budget.now())
            budget.remaining()
            counts = st.snapshot_to(snapshot)
            directory = os.open(snapshots, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            result["snapshot_counts"] = _counts(counts)
            _verify(st, request, budget.now())
            budget.remaining()
            confirmed = Y.confirm_stages(st, budget.now(), 0, request["hold_id"])
            if confirmed.outcome != S.SYNC_ACCEPTED:
                raise BootstrapRefused("CONFIRM_REFUSED")
            result["accepted_rows"] = confirmed.rows
        writer.call(snapshot_then_confirm)
        result["phase"] = "pairing"
        budget.remaining()
        options = reader_factory(budget)
        paired = L.pair_links(options["erp_factory"](), writer.proxy, budget.now())
        result.update(pairing_outcome=paired.outcome, pairing_id=paired.pairing_id,
                      pairing_counts=_counts(paired.counts))
        if paired.outcome != S.SYNC_ACCEPTED:
            raise BootstrapRefused("PAIRING_REFUSED")
        result["phase"] = "collection"
        budget.remaining()
        collected = M.run_requested(options["naver_factory"](), writer.proxy, budget.now,
                                    max_seconds=request["max_seconds"], deadline=budget.deadline,
                                    th=writer.proxy.thresholds())
        result.update(collection_outcome=collected.outcome, run_id=collected.run_id,
                      collection_counts=_counts(collected.counts), codes=list(collected.codes))
        # done은 회차 종료일 뿐 모든 계정 완료가 아니다. 부분 결과를 성공으로 숨기지 않는다.
        partial = (collected.counts.get("targets", 0) != collected.counts.get("ok", 0)
                   or any(collected.counts.get(key, 0) for key in
                          ("deadline_left", "abort_left", "account_error", "handle_invalid",
                           "store_refused", "duplicate_skipped")))
        result.update(status="completed" if collected.outcome == M.OUT_DONE and not partial else "partial",
                      phase="finished")
    except BaseException as error:
        result["status"] = "failed_partial"
        result["error_code"] = _error_code(error)
        if not isinstance(error, Exception):
            raise
    finally:
        result["finished_at"] = clock.now().isoformat()
        try:
            publish_receipt(files.receipts / (stem + ".result.json"), result)
        except Exception:
            # started는 이미 durable하다. 결과 파일 실패여도 다음 부팅 자동 재시도 금지.
            result["status"] = "result_receipt_failed"
    return result
