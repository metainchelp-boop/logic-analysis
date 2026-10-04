"""대행사 키로 하는 모든 네이버 호출이 지나는 **유일한 문** — GET 만 통과한다 (설계 v1.8 · 첫 조각 S4).

지키는 것(모두 시험으로 고정 · 사보타주로 확인):
1. **GET 만.** 다른 방식은 요청을 만들기 **전에** ``WriteForbidden``. 대행사 키는 1,784곳 전부 운영관리 권한이라
   이 한 줄이 「네이버 쪽을 바꾸지 않는다」의 전부다.
2. **정해진 호스트·경로만.** ``api.searchad.naver.com`` · 경로 허용 목록 · 넘겨주기(redirect) 안 따라감
   (따라가면 키가 붙은 머리글이 다른 곳으로 간다).
3. **날 번호를 받지 않는다.** ``handles`` 가 발급한 오늘 손잡이만(14일 규칙은 거기서 판정).
4. **남길 칸만** 돌려준다(``fields``) — 개인정보 칸은 저장 전에 사라진다.
5. **모르는 응답은 0 이 아니다.** 통계 모양을 모르면 ``StatsShapeUnknown`` · 요청한 번호의 줄이 빠지면 0 이 아니라
   「모름」(``missing_ids``) · 자료 기준 시각(``cycleBaseTm``)을 못 읽으면 「자료 늦음」.
6. **하위 계정 목록은 전부 받거나 전부 버린다** — 모든 쪽 200 · 받은 합계 = ``totalElements``.
7. **응답의 고객 번호가 요청한 계정과 다르면 버린다.**
8. **속도** — 초당 3건 · 429/1016 은 2→4→8초 · 10초 안에 5번이면 5분 멈춤 · 두 번 멈추면 회차 중단 ·
   한 회차 호출 수 상한.
9. **비밀값·개인정보가 로그·오류에 0** — 오류 문구에는 경로 모양·상태·코드·고객 번호 끝 4자리만.
"""
from __future__ import annotations

import base64
import collections
import hashlib
import hmac
import http.client
import json
import logging
import math
import os
import random
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import fields as F
from . import handles as H
from .credentials import ManagerCredentials, customer_tail

log = logging.getLogger("naver_engine.read")

BASE_HOST = "api.searchad.naver.com"
BASE_URL = "https://" + BASE_HOST
TIMEOUT = 20
MAX_BODY = 16 * 1024 * 1024
PAGE_SIZE = 1000
MAX_PAGES = 50
STATS_IDS_PER_CALL = 100
MAX_RANGE_DAYS = 92
DEFAULT_MAX_CALLS = 20000
CALLS_PER_SEC = 3

RATE_BACKOFF = (2.0, 4.0, 8.0)
RETRY_BACKOFF = (1.0, 2.0, 3.0)
RATE_WINDOW = 10.0
RATE_BURST = 5
RATE_PAUSE = 300.0
MAX_PAUSES = 2

_ALLOWED_METHODS = frozenset({"GET"})
_PATHS = (
    re.compile(r"/manager-accounts"),
    re.compile(r"/manager-accounts/[0-9]{1,15}/child-ad-accounts"),
    re.compile(r"/ncc/campaigns"),
    re.compile(r"/billing/bizmoney"),
    re.compile(r"/stats"),
    re.compile(r"/ncc/channels"),
    re.compile(r"/ncc/adgroups"),
    re.compile(r"/ncc/ads"),
    re.compile(r"/ncc/keywords"),
    re.compile(r"/ncc/ad-extensions"),
)
_CYCLE = re.compile(r"[0-9]{12}")
# 통계는 당분간 **캠페인 번호만** — 광고그룹·키워드 번호는 캠페인 종류가 섞이면 네이버가 400(11003)으로 거절한다.
_CAMPAIGN_ID = re.compile(r"cmp-[A-Za-z0-9-]{1,60}")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

KIND_KEY_REJECTED = "KEY_REJECTED"
KIND_RATE = "RATE"
KIND_SERVER = "SERVER"
KIND_BAD_REQUEST = "BAD_REQUEST"
KIND_NOT_FOUND = "NOT_FOUND"
KIND_NETWORK = "NETWORK"
KIND_BAD_RESPONSE = "BAD_RESPONSE"
KIND_MISMATCH = "MISMATCH"
KIND_OTHER = "OTHER"


# ── 오류 ────────────────────────────────────────────────────────────
class WriteForbidden(RuntimeError):
    """GET 이 아닌 요청 — 만들기 전에 거절."""


class PathForbidden(RuntimeError):
    """허용 목록에 없는 경로·호스트."""


class RunAbort(RuntimeError):
    """이 회차를 멈춘다(속도 제한에 두 번 멈춤 · 호출 수 상한)."""

    def __init__(self, *args, code="REQUEST_BUDGET", cause_code=None) -> None:
        allowed = {"REQUEST_BUDGET", "REQUEST_DEADLINE", "REQUEST_CALL_CAP", "RATE"}
        self.code = code if type(code) is str and code in allowed else "REQUEST_BUDGET"
        causes = {KIND_SERVER, KIND_NETWORK, KIND_RATE}
        self.cause_code = cause_code if type(cause_code) is str and cause_code in causes else None
        super().__init__(*args)


class IncompleteList(RuntimeError):
    """목록을 전부 받지 못했다 — 통째로 버린다."""


class StatsShapeUnknown(RuntimeError):
    """통계 응답 모양을 모른다 — 절대 0 으로 읽지 않는다."""

    def __init__(self, *args, code="STATS_SHAPE_UNKNOWN") -> None:
        # 저장·화면용 코드는 고정 목록만 허용한다. 응답 원문을 코드로 넘겨도 보존하지 않는다.
        allowed = {"STATS_SHAPE_UNKNOWN", "STATS_NUMERIC_INVALID", "STATS_ROW_ID_INVALID", "STATS_DATE_INVALID"}
        self.code = code if type(code) is str and code in allowed else "STATS_SHAPE_UNKNOWN"
        super().__init__(*args)


class NaverApiError(RuntimeError):
    def __init__(self, kind: str, path: str, status: Optional[int] = None, code: Optional[int] = None,
                 customer: Optional[int] = None, detail: str = "") -> None:
        self.kind, self.path, self.status, self.code, self.detail = kind, path, status, code, detail
        self.customer_tail = customer_tail(customer) if customer is not None else "-"
        super().__init__(f"네이버 호출 실패 [{kind}] {path} · HTTP {status} · 코드 {code} · 계정 {self.customer_tail}"
                         + (f" · {detail}" if detail else ""))


def classify(status: Optional[int], code: Optional[int]) -> str:
    if code == 1016 or status == 429:
        return KIND_RATE
    if code in (1006, 1018) or status in (401, 403):
        return KIND_KEY_REJECTED
    if status is not None and status >= 500:
        return KIND_SERVER
    if status == 400 or code in (1014, 11003):
        return KIND_BAD_REQUEST
    if status == 404:
        return KIND_NOT_FOUND
    return KIND_OTHER


def path_shape(path: str) -> str:
    """오류·로그용 경로 모양 — 번호는 {no} 로 가린다."""
    return re.sub(r"/[0-9]+", "/{no}", path)


def _sign(secret: str, ts: str, method: str, path: str) -> str:
    msg = f"{ts}.{method}.{path}".encode("utf-8")
    return base64.b64encode(hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()).decode("ascii")


# ── 보내는 부분(바꿔 끼울 수 있음 — 시험은 가짜 네이버를 끼운다) ─────────────
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # 넘겨주기를 따라가지 않는다
        return None


class TransportUnsafe(RuntimeError):
    """믿을 수 있는 연결을 만들 수 없다(인증서 목록 없음)."""


def _verifying_context() -> ssl.SSLContext:
    """인증서를 반드시 확인하는 연결 설정 — 환경변수(SSL_CERT_FILE · SSL_CERT_DIR)로 바꿀 수 없는
    파이썬 기본 경로의 인증서 목록만 믿는다(중간에서 복호화하는 서버를 믿지 않게 · 반박 보안 검토)."""
    paths = ssl.get_default_verify_paths()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    loaded = False
    if paths.openssl_cafile and os.path.isfile(paths.openssl_cafile):
        ctx.load_verify_locations(cafile=paths.openssl_cafile)
        loaded = True
    if paths.openssl_capath and os.path.isdir(paths.openssl_capath):
        ctx.load_verify_locations(capath=paths.openssl_capath)
        loaded = True
    if not loaded:
        raise TransportUnsafe("인증서 목록을 찾지 못했습니다")
    return ctx


class UrllibTransport:
    """실제 네트워크. HTTP 오류도 예외가 아니라 (상태, 본문)으로 돌려준다. 연결 실패만 예외.

    프록시를 쓰지 않는다(환경변수 HTTPS_PROXY 무시) — 키가 붙은 요청이 네이버 말고 다른 서버를 거치지 않게.
    """

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(), urllib.request.HTTPSHandler(context=_verifying_context()))

    def send(self, req: urllib.request.Request, timeout: float) -> Tuple[int, bytes]:
        try:
            with self._opener.open(req, timeout=timeout) as r:
                return r.status, r.read(MAX_BODY + 1)
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read(MAX_BODY + 1)
            finally:
                e.close()


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(H.KST)

    def monotonic(self) -> float:
        return time.monotonic()

    def epoch_ms(self) -> int:
        return int(time.time() * 1000)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


# ── 결과 모양 ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ChildAccounts:
    """대행사에 연결된 하위 광고계정 전부(전부 받았을 때만 만들어진다)."""
    accounts: Dict[int, dict]              # 고객 번호 → 남길 칸
    per_manager: Dict[int, int]            # 관리계정 번호 → 받은 줄 수(= totalElements)
    managers: Tuple[dict, ...]

    def __repr__(self) -> str:  # 고객 번호가 로그에 새지 않게 — 개수만
        return f"ChildAccounts(accounts={len(self.accounts)}, managers={len(self.managers)})"


@dataclass(frozen=True)
class StatsResult:
    """통계 한 번 읽은 결과. 숫자가 없는 칸은 0 이 아니라 ``None``(모름)."""
    shape: str                             # top · summary
    rows: Dict[str, Dict[str, Optional[float]]]
    requested_ids: Tuple[str, ...]
    missing_ids: Tuple[str, ...]           # 요청했는데 줄이 없는 번호 — 0 이 아니라 모름
    cycle_base_tm: Optional[datetime]      # 자료가 여기까지 들어왔다(KST) · 못 읽으면 None
    until: date
    reasons: Tuple[str, ...] = field(default=())

    def __repr__(self) -> str:
        return (f"StatsResult(rows={len(self.rows)}, missing={len(self.missing_ids)}, "
                f"fresh={self.data_fresh}, reasons={self.reasons})")

    @property
    def unknown_values(self) -> Tuple[Tuple[str, str], ...]:
        """줄은 왔는데 값이 비어 있는 (번호, 지표) — 0 이 아니라 모름."""
        return tuple((i, f) for i, row in self.rows.items() for f, v in row.items() if v is None)

    @property
    def data_fresh(self) -> bool:
        """``until`` 날짜의 자료가 다 들어왔나 — 기준 시각이 그다음 날 0시 이후여야 한다."""
        if self.cycle_base_tm is None:
            return False
        return self.cycle_base_tm >= datetime.combine(self.until + timedelta(days=1), datetime.min.time(), H.KST)

    @property
    def complete(self) -> bool:
        """판정에 써도 되는가 — 빠진 줄 0 · 빈 값 0 · 자료 늦음 아님."""
        return not self.missing_ids and not self.unknown_values and self.data_fresh


@dataclass(frozen=True)
class DailyStats:
    entity_id: str
    days: Dict[str, Dict[str, Optional[float]]]   # 'YYYY-MM-DD' → 지표
    missing_days: Tuple[str, ...]
    cycle_base_tm: Optional[datetime]
    until: date

    def __repr__(self) -> str:
        return f"DailyStats(days={len(self.days)}, missing={len(self.missing_days)}, fresh={self.data_fresh})"

    @property
    def data_fresh(self) -> bool:
        if self.cycle_base_tm is None:
            return False
        return self.cycle_base_tm >= datetime.combine(self.until + timedelta(days=1), datetime.min.time(), H.KST)

    @property
    def unknown_values(self) -> Tuple[Tuple[str, str], ...]:
        return tuple((d, f) for d, row in self.days.items() for f, v in row.items() if v is None)

    @property
    def complete(self) -> bool:
        return not self.missing_days and not self.unknown_values and self.data_fresh


# ── 판독(순수) ───────────────────────────────────────────────────────
def _parse_cycle(raw) -> Optional[datetime]:
    if not isinstance(raw, str) or not _CYCLE.fullmatch(raw):
        return None
    try:
        return datetime.strptime(raw, "%Y%m%d%H%M").replace(tzinfo=H.KST)
    except ValueError:
        return None


CYCLE_MAX_AHEAD = timedelta(minutes=10)


def _not_future(cycle: Optional[datetime], now: datetime) -> Optional[datetime]:
    """자료 기준 시각이 지금보다 앞서면(시계·형식 이상) 모르는 것으로 본다."""
    if cycle is not None and cycle > now + CYCLE_MAX_AHEAD:
        return None
    return cycle


def _num(value, what: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StatsShapeUnknown(f"숫자가 아닌 지표({what})", code="STATS_NUMERIC_INVALID")
    if isinstance(value, float) and not math.isfinite(value):
        raise StatsShapeUnknown(f"숫자가 아닌 지표({what})", code="STATS_NUMERIC_INVALID")
    return value


def _locate(body, wrapper: str) -> Tuple[str, Mapping]:
    """최상위 ``data`` 또는 명세의 감싼 모양(``summaryStatResponse``·``dailyStatResponse``)을 찾는다."""
    if not isinstance(body, Mapping):
        raise StatsShapeUnknown("통계 응답이 사전이 아님")
    wrapped = [k for k in ("summaryStatResponse", "dailyStatResponse") if k in body]
    if wrapped:
        if wrapped != [wrapper]:
            raise StatsShapeUnknown("기대와 다른 감싼 모양")
        inner = body[wrapper]
        if not isinstance(inner, Mapping):
            raise StatsShapeUnknown("감싼 모양 안쪽이 사전이 아님")
        shape = "summary" if wrapper == "summaryStatResponse" else "daily"
        body = inner
    elif "data" in body:
        shape = "top"
    else:
        raise StatsShapeUnknown("data 칸 없음")
    if not isinstance(body.get("data"), list):
        raise StatsShapeUnknown("data 가 목록이 아님")
    return shape, body


def parse_stats(body, requested_ids: Sequence[str], fields: Sequence[str], until: date) -> StatsResult:
    """캠페인 등 여러 번호의 기간 합계. 요청한 번호의 줄이 없으면 0 이 아니라 ``missing_ids``."""
    req = tuple(str(i) for i in requested_ids)
    if len(set(req)) != len(req):
        raise ValueError("요청 번호가 겹칩니다")
    shape, inner = _locate(body, "summaryStatResponse")
    rows: Dict[str, Dict[str, Optional[float]]] = {}
    for row in inner["data"]:
        if not isinstance(row, Mapping) or not isinstance(row.get("id"), str):
            raise StatsShapeUnknown("줄에 번호(id)가 없음", code="STATS_ROW_ID_INVALID")
        rid = row["id"]
        if rid not in req:
            raise StatsShapeUnknown("요청하지 않은 번호의 줄", code="STATS_ROW_ID_INVALID")
        if rid in rows:
            raise StatsShapeUnknown("같은 번호의 줄이 두 번", code="STATS_ROW_ID_INVALID")
        rows[rid] = {f: _num(row.get(f), f) for f in fields}
    cycle = _parse_cycle(inner.get("cycleBaseTm"))
    missing = tuple(i for i in req if i not in rows)
    reasons = []
    if missing:
        reasons.append("missing-rows")
    if any(v is None for row in rows.values() for v in row.values()):
        reasons.append("metric-unknown")
    if cycle is None:
        reasons.append("cycle-unknown")
    result = StatsResult(shape, rows, req, missing, cycle, until, ())
    if cycle is not None and not result.data_fresh:
        reasons.append("cycle-behind")
    return StatsResult(shape, rows, req, missing, cycle, until, tuple(reasons))


def parse_daily(body, entity_id: str, fields: Sequence[str], since: date, until: date) -> DailyStats:
    """한 번호의 하루별 지표. 빠진 날은 0 이 아니라 ``missing_days``."""
    _shape, inner = _locate(body, "dailyStatResponse")
    want = []
    d = since
    while d <= until:
        want.append(d.isoformat())
        d += timedelta(days=1)
    days: Dict[str, Dict[str, Optional[float]]] = {}
    for row in inner["data"]:
        if not isinstance(row, Mapping):
            raise StatsShapeUnknown("하루 줄이 사전이 아님")
        ds = row.get("dateStart")
        if not isinstance(ds, str) or not _DAY.fullmatch(ds[:10]):
            raise StatsShapeUnknown("하루 줄에 날짜가 없음", code="STATS_DATE_INVALID")
        ds = ds[:10]
        if ds not in want:
            raise StatsShapeUnknown("요청하지 않은 날짜의 줄", code="STATS_DATE_INVALID")
        if ds in days:
            raise StatsShapeUnknown("같은 날짜의 줄이 두 번", code="STATS_DATE_INVALID")
        de = row.get("dateEnd")
        if de is not None and (not isinstance(de, str) or de[:10] != ds):
            raise StatsShapeUnknown("하루 줄이 하루가 아님", code="STATS_DATE_INVALID")
        days[ds] = {f: _num(row.get(f), f) for f in fields}
    missing = tuple(x for x in want if x not in days)
    return DailyStats(str(entity_id), days, missing, _parse_cycle(inner.get("cycleBaseTm")), until)


def _page(body, what: str) -> Tuple[list, int, bool, Optional[int]]:
    """쪽 넘김 응답(content · totalElements · last · totalPages)."""
    if not isinstance(body, Mapping) or not isinstance(body.get("content"), list):
        raise IncompleteList(f"{what}: 쪽 모양을 모름")
    total = body.get("totalElements")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise IncompleteList(f"{what}: 전체 개수(totalElements)를 모름")
    last = body.get("last")
    pages = body.get("totalPages")
    if isinstance(pages, bool) or (pages is not None and not isinstance(pages, int)):
        pages = None
    return body["content"], total, last is True, pages


def _check_period(since: date, until: date, today: date) -> None:
    if not isinstance(since, date) or not isinstance(until, date) or isinstance(since, datetime) or isinstance(until, datetime):
        raise ValueError("기간은 날짜여야 합니다")
    if since > until:
        raise ValueError("시작이 끝보다 늦습니다")
    if until > today:
        raise ValueError("미래 날짜는 읽지 않습니다")
    if (until - since).days + 1 > MAX_RANGE_DAYS:
        raise ValueError("기간이 너무 깁니다")


def _check_fields(fields: Sequence[str], allowed=F.STAT_FIELDS_SUMMARY) -> Tuple[str, ...]:
    out = tuple(fields)
    if not out or any(f not in allowed for f in out) or len(set(out)) != len(out):
        raise ValueError("요청할 수 없는 지표입니다")
    return out


class RequestPacer:
    """직렬 실행기의 reader 교체 사이에도 유지하는 내부 공유 호출 간격.

    네이버 공식 상한이 아니라 현재 서버의 안전 예산이다. 같은 단조 시계 영역을
    사용하는 직렬 reader만 공유한다. HTTP 재시도/429 휴지는 별도로 유지한다.
    """
    def __init__(self):
        self.last_sent = None

    def pace(self, clock, sleep):
        gap = 1.0 / CALLS_PER_SEC
        now = clock.monotonic()
        if self.last_sent is not None and now-self.last_sent < gap:
            sleep(gap-(now-self.last_sent))
        self.last_sent = clock.monotonic()


# ── 관문 ─────────────────────────────────────────────────────────────
class NaverReader:
    """대행사 키로 네이버를 **읽기만** 한다. 회차(점검 한 번)마다 하나 만든다 — 호출 수·멈춤 횟수를 센다."""

    def __init__(self, credentials: ManagerCredentials, *, transport=None, clock=None, rng=None,
                 max_calls: int = DEFAULT_MAX_CALLS, pacer=None) -> None:
        if not isinstance(credentials, ManagerCredentials):
            raise TypeError("대행사 키가 아닙니다")
        self._cred = credentials
        self._transport = transport if transport is not None else UrllibTransport()
        self._clock = clock if clock is not None else SystemClock()
        self._rng = rng if rng is not None else random.Random()
        self._max_calls = max_calls
        self.calls = 0
        self._called_customers = set()
        self.pauses = 0
        self._rate_limited = False
        self._last_sent: Optional[float] = None
        self._pacer = pacer if pacer is not None else RequestPacer()
        self._rate_hits: collections.deque = collections.deque()
        self._request_limits = []

    def __repr__(self) -> str:
        return f"NaverReader(calls={self.calls}, pauses={self.pauses})"

    @property
    def rate_limited(self) -> bool:
        """이 읽기 객체가 RATE 응답을 겪었는지. 추가 작업 생략용이며 재시도 정책은 바꾸지 않는다."""
        return self._rate_limited

    @property
    def called_customers(self) -> frozenset:
        """이번 읽기 객체에서 실제 요청 예산을 쓴 계정. 서로 다른 수집기의 중복 예산 방지용."""
        return frozenset(self._called_customers)

    # 손잡이
    def manager_handle(self) -> H.ManagerHandle:
        return H.issue_manager_handle(self._cred.customer_id, self._clock.now())

    def share_pacing(self, pacer):
        """첫 HTTP 전 실행기의 공유 간격을 연결한다. 이미 읽은 객체는 재연결하지 않는다."""
        if not isinstance(pacer, RequestPacer) or (self.calls and self._pacer is not pacer):
            raise ValueError("읽기 시작 후에는 공유 간격을 바꿀 수 없습니다")
        self._pacer = pacer
        return self

    @contextmanager
    def bounded_requests(self, *, max_calls: int, max_seconds: float):
        """재시도·쪽 넘김도 실제 HTTP 관문에서 예산을 쓴다. 기존 속도·읽기전용 규칙은 유지한다."""
        if type(max_calls) is not int or max_calls < 1 or type(max_seconds) not in (int, float) \
                or not math.isfinite(max_seconds) or not 0 < max_seconds <= 60:
            raise ValueError("읽기 예산이 올바르지 않습니다")
        bound = (self.calls + max_calls, self._clock.monotonic() + max_seconds, time.monotonic() + max_seconds)
        self._request_limits.append(bound)
        try:
            yield
        finally:
            self._request_limits.remove(bound)

    def check_budget(self):
        """마지막 응답 뒤에도 호출자가 마감을 검증할 수 있다(요청 횟수는 추가하지 않는다)."""
        self._remaining()

    def _remaining(self, *, request=False):
        remaining = float(TIMEOUT)
        for call_cap, clock_end, wall_end in self._request_limits:
            if request and self.calls >= call_cap:
                raise RunAbort("bounded-call-cap", code="REQUEST_CALL_CAP")
            remaining = min(remaining, clock_end - self._clock.monotonic(), wall_end - time.monotonic())
        if remaining <= 0:
            raise RunAbort("bounded-deadline", code="REQUEST_DEADLINE")
        return remaining

    def _sleep(self, seconds):
        if self._request_limits and seconds >= self._remaining():
            raise RunAbort("bounded-deadline", code="REQUEST_DEADLINE")
        self._clock.sleep(seconds)

    # 한 곳 — 모든 요청이 여기서 만들어진다
    def _gate(self, method: str, path: str, params: Optional[Mapping[str, Any]], customer_id: int, ah=None) -> Tuple[int, bytes]:
        if method not in _ALLOWED_METHODS:
            raise WriteForbidden(f"GET 이 아닌 요청은 만들지 않습니다: {method}")
        if not any(p.fullmatch(path) for p in _PATHS):
            raise PathForbidden(f"허용하지 않은 경로: {path_shape(path)}")
        if self.calls >= self._max_calls:
            raise RunAbort("call-cap", code="REQUEST_CALL_CAP")
        self._remaining(request=True)
        if type(ah) is H.InventoryHandle:
            H.require_inventory(ah, self._clock.now())
        self._pace()
        # 원천/권한 재검증도 회차 시간을 쓴다. 검증 전의 남은 시간으로
        # HTTP를 보내면 이미 마감된 회차에서 요청하거나 타임아웃을 넘긴다.
        timeout = self._remaining(request=True)
        self.calls += 1
        self._called_customers.add(customer_id)
        ts = str(self._clock.epoch_ms())
        headers = {
            "X-Timestamp": ts,
            "X-API-KEY": self._cred.api_key.reveal(),
            "X-Customer": str(customer_id),
            "X-Signature": _sign(self._cred.secret_key.reveal(), ts, method, path),
            "Accept": "application/json",
        }
        query = urllib.parse.urlencode(params, doseq=True) if params else ""
        url = BASE_URL + path + ("?" + query if query else "")
        req = urllib.request.Request(url, headers=headers, method=method)
        if req.get_method() != "GET" or req.data is not None:
            raise WriteForbidden("GET 이 아닌 요청은 보내지 않습니다")
        if req.host != BASE_HOST or req.type != "https":
            raise PathForbidden("허용하지 않은 호스트")
        del headers
        try:
            return self._transport.send(req, timeout)
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            raise  # 연결 실패 — _request 가 종류 이름만 남기고 다시 보낸다
        except Exception as e:  # 뜻밖의 오류 — 문구에 키가 섞일 수 있어 종류 이름만 남기고 가린다
            raise NaverApiError(KIND_OTHER, path_shape(path), None, None, customer_id, type(e).__name__) from None

    def _pace(self) -> None:
        self._pacer.pace(self._clock, self._sleep)
        self._last_sent = self._clock.monotonic()

    def _note_rate(self) -> None:
        self._rate_limited = True
        now = self._clock.monotonic()
        self._rate_hits.append(now)
        while self._rate_hits and now - self._rate_hits[0] > RATE_WINDOW:
            self._rate_hits.popleft()
        if len(self._rate_hits) >= RATE_BURST:
            self.pauses += 1
            self._rate_hits.clear()
            if self.pauses >= MAX_PAUSES:
                raise RunAbort("rate-paused-twice", code="RATE")
            log.warning("[네이버 읽기] 속도 제한이 몰려 5분 멈춤(이번 회차 %d번째)", self.pauses)
            self._sleep(RATE_PAUSE)

    def _request(self, customer_id: int, path: str, params: Optional[Mapping[str, Any]] = None, *, ah=None):
        shape = path_shape(path)
        tries = {KIND_RATE: 0, KIND_SERVER: 0, KIND_NETWORK: 0}
        last_cause = None
        try:
            while True:
                status: Optional[int] = None
                code: Optional[int] = None
                try:
                    status, body = self._gate("GET", path, params, customer_id, ah)
                except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
                    kind, detail = KIND_NETWORK, type(e).__name__
                else:
                    if status == 200:
                        return self._decode(body, shape, customer_id, status)
                    if 200 < status < 300:  # 206 · 203 등 — 온전한 응답이라 믿지 않는다
                        raise NaverApiError(KIND_BAD_RESPONSE, shape, status, None, customer_id, "200 이 아닌 성공")
                    code = _error_code(body)
                    kind, detail = classify(status, code), ""
                last_cause = kind if kind in tries else None
                if kind == KIND_RATE:
                    self._note_rate()
                    if tries[KIND_RATE] >= len(RATE_BACKOFF):
                        raise NaverApiError(kind, shape, status, code, customer_id)
                    wait = RATE_BACKOFF[tries[KIND_RATE]]
                    tries[KIND_RATE] += 1
                    self._sleep(wait + self._rng.uniform(0, wait / 4))
                    continue
                if kind in (KIND_SERVER, KIND_NETWORK):
                    if tries[kind] >= len(RETRY_BACKOFF):
                        raise NaverApiError(kind, shape, status, code, customer_id, detail)
                    self._sleep(RETRY_BACKOFF[tries[kind]])
                    tries[kind] += 1
                    continue
                log.warning("[네이버 읽기] %s %s HTTP %s 코드 %s 계정 %s", kind, shape, status, code, customer_tail(customer_id))
                raise NaverApiError(kind, shape, status, code, customer_id, detail)
        except RunAbort as exc:
            # 중단 코드·예산은 유지하고 이 요청 안의 마지막 재시도 원인만 덧붙인다.
            # 요청이 성공하면 지역 변수도 끝나므로 다음 요청의 예산 종료로 번지지 않는다.
            exc.cause_code = last_cause
            raise

    @staticmethod
    def _decode(body: bytes, shape: str, customer_id: int, status: int):
        if body is None or len(body) > MAX_BODY:
            raise NaverApiError(KIND_BAD_RESPONSE, shape, status, None, customer_id, "본문 크기")
        if not body.strip():
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise NaverApiError(KIND_BAD_RESPONSE, shape, status, None, customer_id, "JSON 아님") from None

    # ── 대행사 계정(관리계정 손잡이) ─────────────────────────────────
    def _manager(self, mh) -> H.ManagerHandle:
        return H.require_manager(mh, self._clock.now(), self._cred.customer_id)

    def _all_pages(self, customer_id: int, path: str, what: str, key: str) -> List[dict]:
        """모든 쪽을 받는다 — 쪽 번호가 다르거나 같은 번호가 두 번 오거나 합계가 다르면 통째로 버린다."""
        rows: List[dict] = []
        seen = set()
        total: Optional[int] = None
        for page in range(MAX_PAGES):
            body = self._request(customer_id, path, {"page": page, "size": PAGE_SIZE})
            content, t, last, pages = _page(body, what)
            number = body.get("number")
            if number is not None and (isinstance(number, bool) or number != page):
                raise IncompleteList(f"{what}: 요청한 쪽과 받은 쪽 번호가 다름")
            for r in content:
                k = r.get(key) if isinstance(r, Mapping) else None
                if k is None or isinstance(k, (bool, dict, list)):
                    raise IncompleteList(f"{what}: 번호 없는 줄")
                if k in seen:
                    raise IncompleteList(f"{what}: 같은 번호가 두 번 옴")
                seen.add(k)
            if total is None:
                total = t
            elif t != total:
                raise IncompleteList(f"{what}: 받는 도중 전체 개수가 바뀜")
            if not all(isinstance(r, Mapping) for r in content):
                raise IncompleteList(f"{what}: 줄 모양을 모름")
            rows.extend(content)
            if len(rows) >= total or last or not content or (pages is not None and page + 1 >= pages):
                break
        else:
            raise IncompleteList(f"{what}: 쪽 넘김 상한")
        if total is None or len(rows) != total:
            raise IncompleteList(f"{what}: 받은 줄 {len(rows)} ≠ 전체 {total}")
        return rows

    def list_manager_accounts(self, mh) -> List[dict]:
        h = self._manager(mh)
        rows = self._all_pages(h.customer_id, "/manager-accounts", "관리계정 목록", "managerAccountNo")
        out = []
        for r in rows:
            kept = F.keep_manager(r)
            no = kept.get("managerAccountNo")
            if isinstance(no, bool) or not isinstance(no, int) or not 0 < no < 10 ** 15:
                # 경로 허용 목록([0-9]{1,15}) 밖 번호는 네이버 자료 문제로 본다 — 관문의 안전 거절(PathForbidden)은
                # 프로그램 결함에만 나게(검토 sync-2 · 결과로 돌려주고 기록·재시도 간격·알림이 돌게)
                raise IncompleteList("관리계정 목록: 번호 없는 줄")
            out.append(kept)
        return out

    def list_child_accounts(self, mh, manager_account_no: int) -> List[dict]:
        h = self._manager(mh)
        if isinstance(manager_account_no, bool) or not isinstance(manager_account_no, int) or manager_account_no <= 0:
            raise ValueError("관리계정 번호가 아닙니다")
        rows = self._all_pages(h.customer_id, f"/manager-accounts/{manager_account_no}/child-ad-accounts",
                               "하위 계정 목록", "customerId")
        out = []
        for r in rows:
            kept = F.keep(r, F.CHILD_ACCOUNT)
            try:
                kept["customerId"] = H.normalize_customer_id(kept.get("customerId"))
            except H.NotEligible:
                raise IncompleteList("하위 계정 목록: 고객 번호 없는 줄") from None
            ad_no = kept.get("adAccountNo")
            if isinstance(ad_no, str) and re.fullmatch(r"[1-9][0-9]{0,14}", ad_no):
                ad_no = int(ad_no)
            if isinstance(ad_no, bool) or not isinstance(ad_no, int) or not 0 < ad_no < 10 ** 15:
                raise IncompleteList("하위 계정 목록: 광고 계정 번호 없는 줄")
            kept["adAccountNo"] = ad_no
            out.append(kept)
        return out

    def list_all_children(self, mh) -> ChildAccounts:
        """모든 관리계정의 하위 계정 — 한 곳이라도 전부 못 받으면 통째로 ``IncompleteList``."""
        managers = self.list_manager_accounts(mh)
        if not managers:
            raise IncompleteList("관리계정이 0개")
        accounts: Dict[int, dict] = {}
        customer_by_ad_no: Dict[int, int] = {}
        per: Dict[int, int] = {}
        for m in managers:
            no = m["managerAccountNo"]
            kids = self.list_child_accounts(mh, no)
            expect = m.get("childAdAccountCount")  # 실측: 지금은 비어 있음(null) — 값이 오면 「0 이 아닌데 0줄」만 막는다
            if isinstance(expect, int) and not isinstance(expect, bool) and expect > 0 and not kids:
                raise IncompleteList("하위 계정 목록: 관리계정은 하위가 있다는데 0줄")
            per[no] = len(kids)
            for k in kids:
                cid = k["customerId"]
                old = accounts.get(cid)
                if old is not None and old["adAccountNo"] != k["adAccountNo"]:
                    raise IncompleteList("하위 계정 목록: 같은 고객의 광고 계정 번호가 다름")
                ad_no = k["adAccountNo"]
                old_cid = customer_by_ad_no.get(ad_no)
                if old_cid is not None and old_cid != cid:
                    raise IncompleteList("하위 계정 목록: 같은 광고 계정의 고객 번호가 다름")
                customer_by_ad_no[ad_no] = cid
                accounts.setdefault(cid, k)
        return ChildAccounts(accounts, per, tuple(managers))

    # ── 광고주 계정(계정 손잡이) ────────────────────────────────────
    def _account(self, ah, purposes) -> H.AccountHandle:
        return H.require_account(ah, self._clock.now(), purposes)

    def _same_customer(self, got, h: H.AccountHandle, shape: str) -> None:
        try:
            cid = H.normalize_customer_id(got)
        except H.NotEligible:
            raise NaverApiError(KIND_MISMATCH, shape, 200, None, h.customer_id, "응답에 고객 번호 없음") from None
        if cid != h.customer_id:
            raise NaverApiError(KIND_MISMATCH, shape, 200, None, h.customer_id, "응답의 고객 번호가 다름")

    def get_campaigns(self, ah) -> List[dict]:
        h = self._account(ah, (H.PURPOSE_CHECK, H.PURPOSE_PREVIEW, H.PURPOSE_INVENTORY))
        body = self._request(h.customer_id, "/ncc/campaigns", ah=h)
        if not isinstance(body, list):
            raise NaverApiError(KIND_BAD_RESPONSE, "/ncc/campaigns", 200, None, h.customer_id, "목록 아님")
        out = []
        for c in body:
            if not isinstance(c, Mapping) or not isinstance(c.get("nccCampaignId"), str):
                raise NaverApiError(KIND_BAD_RESPONSE, "/ncc/campaigns", 200, None, h.customer_id, "캠페인 번호 없음")
            self._same_customer(c.get("customerId"), h, "/ncc/campaigns")
            out.append(F.keep(c, F.CAMPAIGN))
        return out

    def get_bizmoney(self, ah) -> dict:
        h = self._account(ah, (H.PURPOSE_CHECK, H.PURPOSE_INVENTORY))
        body = self._request(h.customer_id, "/billing/bizmoney", ah=h)
        if not isinstance(body, Mapping):
            raise NaverApiError(KIND_BAD_RESPONSE, "/billing/bizmoney", 200, None, h.customer_id, "사전 아님")
        self._same_customer(body.get("customerId"), h, "/billing/bizmoney")
        kept = F.keep(body, F.BIZMONEY)
        # 실측(2026-09-28): 잔액은 대부분 원 아래 소수까지 온다(명세는 정수) — 정수·소수 모두 받는다.
        try:
            _num(kept.get("bizmoney"), "bizmoney")
        except StatsShapeUnknown:
            raise NaverApiError(KIND_BAD_RESPONSE, "/billing/bizmoney", 200, None, h.customer_id, "잔액 모름") from None
        if kept.get("bizmoney") is None:
            raise NaverApiError(KIND_BAD_RESPONSE, "/billing/bizmoney", 200, None, h.customer_id, "잔액 모름")
        for lock in ("budgetLock", "refundLock"):
            if not isinstance(kept.get(lock), bool):
                raise NaverApiError(KIND_BAD_RESPONSE, "/billing/bizmoney", 200, None, h.customer_id, "잠금 모름")
        return kept

    def get_structure_page(self, ah, entity, parent_id=None, *, page_token=None):
        """상태 사유의 원천만 읽는다. 문구·URL·입찰가·개인정보는 보관하지 않는다.

        공식 목록 명세의 그룹/키워드는 NEXT 페이지를 끝까지 이어야 완료이다.
        다른 목록은 배열 전체 응답이며 임의 페이지 추측을 하지 않는다.
        """
        specs = {
            "adgroup": ("/ncc/adgroups", "nccAdgroupId", "nccCampaignId", True),
            "ad": ("/ncc/ads", "nccAdId", "nccAdgroupId", False),
            "keyword": ("/ncc/keywords", "nccKeywordId", "nccAdgroupId", True),
            "ad_extension": ("/ncc/ad-extensions", "nccAdExtensionId", "ownerId", False),
            "business_channel": ("/ncc/channels", "nccBusinessChannelId", None, False),
        }
        if entity not in specs:
            raise ValueError("허용하지 않은 구조 계층입니다")
        path, id_key, parent_key, paged = specs[entity]
        valid_id = lambda v: isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", v)
        if ((parent_key and not valid_id(parent_id)) or (not parent_key and parent_id is not None)
                or (page_token is not None and (not paged or not valid_id(page_token)))):
            raise ValueError("구조 계층의 부모 또는 페이지 번호가 잘못되었습니다")
        h = self._account(ah, (H.PURPOSE_INVENTORY,))
        params = {parent_key: parent_id} if parent_key else {}
        if paged:
            params.update(recordSize=PAGE_SIZE, selector="NEXT")
            if page_token is not None:
                params["baseSearchId"] = page_token
        body = self._request(h.customer_id, path, params, ah=h)
        if not isinstance(body, list) or (paged and len(body) > PAGE_SIZE):
            raise NaverApiError(KIND_BAD_RESPONSE, path, 200, customer=h.customer_id, detail="목록 모양 이상")
        allowed = {id_key, "customerId", "status", "statusReason", "userLock", "inspectStatus",
                   "pcInspectStatus", "mobileInspectStatus", "pcChannelId", "mobileChannelId", "enable"}
        if parent_key:
            allowed.add(parent_key)
        out, seen = [], set()
        for row in body:
            if not isinstance(row, Mapping) or not valid_id(row.get(id_key)):
                raise NaverApiError(KIND_BAD_RESPONSE, path, 200, customer=h.customer_id, detail="구조 번호 없음")
            self._same_customer(row.get("customerId"), h, path)
            if parent_key and row.get(parent_key) != parent_id:
                raise NaverApiError(KIND_MISMATCH, path, 200, customer=h.customer_id, detail="부모 번호 다름")
            rid = row[id_key]
            if rid in seen or rid == page_token:
                raise NaverApiError(KIND_BAD_RESPONSE, path, 200, customer=h.customer_id, detail="구조 번호 중복")
            seen.add(rid)
            kept = {key: value for key, value in row.items() if key in allowed}
            for key in ("status", "statusReason", "inspectStatus", "pcInspectStatus", "mobileInspectStatus"):
                if kept.get(key) is not None and (not isinstance(kept[key], str) or len(kept[key]) > 160):
                    raise NaverApiError(KIND_BAD_RESPONSE, path, 200, customer=h.customer_id, detail="상태 코드 모양 이상")
            out.append(kept)
        return out, out[-1][id_key] if paged and len(out) == PAGE_SIZE else None

    def get_stats_summary(self, ah, ids: Iterable[str], since: date, until: date,
                          fields: Sequence[str] = ("impCnt", "clkCnt", "salesAmt", "ccnt")) -> StatsResult:
        """여러 번호의 기간 합계. 100개씩 나눠 부르고 합친다 — 한 묶음이라도 모양을 모르면 전체가 실패."""
        h = self._account(ah, (H.PURPOSE_CHECK, H.PURPOSE_INVENTORY))
        _check_period(since, until, H._kst_today(self._clock.now()))
        flds = _check_fields(fields)
        want = [i if isinstance(i, str) else "" for i in ids]
        if not want or any(not _CAMPAIGN_ID.fullmatch(i) for i in want) or len(set(want)) != len(want):
            raise ValueError("통계 번호는 겹치지 않는 캠페인 번호여야 합니다")
        rows: Dict[str, Dict[str, Optional[float]]] = {}
        missing: List[str] = []
        cycles: List[Optional[datetime]] = []
        shapes = set()
        for i in range(0, len(want), STATS_IDS_PER_CALL):
            chunk = want[i:i + STATS_IDS_PER_CALL]
            body = self._request(h.customer_id, "/stats", {
                "ids": chunk,
                "fields": json.dumps(list(flds)),
                "timeRange": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
            }, ah=h)
            part = parse_stats(body, chunk, flds, until)
            rows.update(part.rows)
            missing.extend(part.missing_ids)
            cycles.append(_not_future(part.cycle_base_tm, self._clock.now()))
            shapes.add(part.shape)
        cycle = None if any(c is None for c in cycles) else min(cycles)
        reasons = []
        if missing:
            reasons.append("missing-rows")
        if any(v is None for row in rows.values() for v in row.values()):
            reasons.append("metric-unknown")
        if cycle is None:
            reasons.append("cycle-unknown")
        res = StatsResult("+".join(sorted(shapes)), rows, tuple(want), tuple(missing), cycle, until, ())
        if cycle is not None and not res.data_fresh:
            reasons.append("cycle-behind")
        return StatsResult(res.shape, rows, tuple(want), tuple(missing), cycle, until, tuple(reasons))

    def get_stats_daily(self, ah, entity_id: str, since: date, until: date,
                        fields: Sequence[str] = ("impCnt", "clkCnt", "salesAmt", "ccnt")) -> DailyStats:
        h = self._account(ah, (H.PURPOSE_CHECK, H.PURPOSE_INVENTORY))
        _check_period(since, until, H._kst_today(self._clock.now()))
        flds = _check_fields(fields, F.STAT_FIELDS_DAILY)
        if not isinstance(entity_id, str) or not _CAMPAIGN_ID.fullmatch(entity_id):
            raise ValueError("캠페인 번호가 아닙니다")
        body = self._request(h.customer_id, "/stats", {
            "id": entity_id,
            "fields": json.dumps(list(flds)),
            "timeRange": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
            "timeIncrement": "1",
        }, ah=h)
        d = parse_daily(body, entity_id, flds, since, until)
        cyc = _not_future(d.cycle_base_tm, self._clock.now())
        return d if cyc is d.cycle_base_tm else DailyStats(d.entity_id, d.days, d.missing_days, cyc, d.until)

    def confirm_no_activity(self, ah, entity_ids: Iterable[str], since: date, until: date,
                            fields: Sequence[str] = ("impCnt", "clkCnt", "salesAmt", "ccnt")) -> Dict[str, bool]:
        """합계에 줄이 없던 번호가 정말 「활동 0」인지 하루별로 확인한다.

        실측(2026-09-28 · 9/9): 네이버는 활동이 없으면 **합계** 줄을 주지 않지만 **하루별**은 날마다 줄을 준다.
        돌려주는 값: 번호 → ``True``(기간의 모든 날 · 모든 지표가 정확히 0 · 자료 늦음 아님) / ``False``(그 밖 전부).
        ``False`` 는 「활동이 있었다」가 아니라 「0 이라고 확인하지 못했다」는 뜻이다 — 부르는 쪽은 ⚪ 로 둔다.
        """
        self._account(ah, (H.PURPOSE_CHECK, H.PURPOSE_INVENTORY))  # 번호가 비어 있어도 손잡이부터 본다
        out: Dict[str, bool] = {}
        for eid in entity_ids:
            d = self.get_stats_daily(ah, eid, since, until, fields)
            out[str(eid)] = bool(d.complete and d.days and all(
                v == 0 and v is not None for day in d.days.values() for v in day.values()))
        return out

    def get_channels(self, ah) -> List[dict]:
        """비즈채널 — 짝 확인 미리보기 전용(사람이 누를 때만 · 저장하지 않음 · 대표 결정 Q2)."""
        h = self._account(ah, (H.PURPOSE_PREVIEW,))
        body = self._request(h.customer_id, "/ncc/channels")
        if not isinstance(body, list):
            raise NaverApiError(KIND_BAD_RESPONSE, "/ncc/channels", 200, None, h.customer_id, "목록 아님")
        out = []
        for c in body:
            if not isinstance(c, Mapping):
                raise NaverApiError(KIND_BAD_RESPONSE, "/ncc/channels", 200, None, h.customer_id, "줄 모양")
            self._same_customer(c.get("customerId"), h, "/ncc/channels")
            out.append(F.keep(c, F.CHANNEL))
        return out


def _error_code(body: bytes) -> Optional[int]:
    try:
        j = json.loads((body or b"").decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError):
        return None
    code = j.get("code") if isinstance(j, Mapping) else None
    if isinstance(code, bool):
        return None
    if isinstance(code, int):
        return code
    if isinstance(code, str) and code.strip().isdigit():
        return int(code.strip())
    return None
