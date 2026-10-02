"""관제 화면 API — 표준 라이브러리 WSGI 앱 하나(설계 v1.8 S11 · v1.4 §5 · §9 · §12).

③ 광고센터가 ``/api/naver-auto/*`` 를 이 앱으로 중계한다(S12). 이 파일은 **들어오는 요청만** 받는다 — 네트워크를 여는
모듈을 import 하지 않는다(① 내 정보는 관문 ``erp_profile`` · 미리보기는 부르는 쪽이 넣는 ``previewer`` 로만).

경로(모두 ``/api/naver-auto`` 아래)
- ``POST /session``(sso → 자체 토큰 · 토큰 없이 부르는 **유일한** 길) · ``POST /session/refresh``
- ``GET /me`` · ``GET /board?selection=&attention=`` · ``GET /clients/{가망}`` · ``GET /links/pending`` · ``GET /ended`` ·
  ``GET /unlinked`` · ``GET /bell`` · ``GET /settings`` · ``GET /health``
- ``POST /issues/{번호}/ack · resolve · except`` · ``POST /links/confirm · reject · revoke · preview`` ·
  ``POST /bell/{번호}/read`` · ``POST /bell/read-all`` · ``POST /settings/thresholds``(대표만) ·
  ``POST /holds/{org|stages|accounts}/confirm``(대표만)

지키는 것
- **요청마다 범위를 새로 계산한다** — 토큰에는 번호와 시각만. 퇴사·강등은 다음 요청부터(범위 없음 = 401). 로그인 때 ①
  my-profile 이 좁으면 좁힌 채로(``scope.narrowed_scope_of``). 대리 보기(``?as=``)는 없다 — 모르는 인자는 무시한다.
- **범위 밖 = 없음** — 가망 · 이슈 · 짝 후보 · 판단의 없는 번호와 범위 밖 번호는 같은 404 · 같은 본문(``CLIENT_NOT_VISIBLE``).
  묶음(짝 확인)은 하나라도 어긋나면 전체를 거절한다(아무것도 적지 않는다).
- **쓰기는 쓰는 곳 하나** — 부르는 쪽이 넣는 ``write``(엔진의 쓰기 저장소 한 곳에서 차례로)로만. 읽기는 요청마다 읽기
  전용 저장소(``open_read``). 사람 판단·이슈 손길·읽음·기준값·열람 기록을 적는 함수는 이 파일에서만 부른다(구문 시험).
- **올리기 관문(§9 · 26시간)** — 조직이 낡았으면 🙈 예외 · 「이 계정 맞음」을 거절한다(멈추기·내리기 · 확인·해결은 된다).
- **감사** — 광고주 한 장 열람 · 모든 쓰기(거절 포함) · 설정 변경 · 로그인을 ``record_access`` 로(번호와 코드만).
  열람 기록을 못 적으면 보여 주지 않는다(503).
- 응답은 ``no-store`` · 오류 문구에 토큰·번호·이름을 싣지 않는다 · 뜻밖의 오류는 종류 이름만 기록하고 500.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from app.naver_auto import org_snapshot as O
from app.naver_auto import scope as SC

from . import erp_profile as EP
from . import handles as H
from . import links as L
from . import session as SE
from . import store as S
from . import sync as Y
from . import views as W
from . import inventory as INV
from . import dashboard as DASH
from . import management_store as MS

log = logging.getLogger("naver_engine.web")

PREFIX = "/api/naver-auto"
GET, POST = "GET", "POST"            # 들어오는 요청의 방식(이 파일은 나가는 요청을 만들지 않는다)
# 제한판은 새 경로가 추가돼도 자동으로 열지 않는다. 로그인/갱신은 기술 쓰기만 허용한다.
_VERIFICATION_GETS = frozenset({"/me", "/board", "/accounts", "/dashboard", "/links/pending", "/ended", "/unlinked",
                               "/bell", "/settings", "/health", "/reports"})
_VERIFICATION_SESSIONS = frozenset({"/session", "/session/refresh"})
_VERIFIED_REQUESTS = frozenset({(POST, "/links/confirm"), (POST, "/collection/request"),
                                (GET, "/collection/status"), (POST, "/management/update"),
                                (POST, "/management/collect"), (POST, "/reports/review")})
_VERIFICATION_CLIENT = re.compile(r"/clients/[0-9]{1,18}")
BODY_MAX = 64 * 1024                 # ③ 중계 상한과 같다(S12)
QUERY_MAX = 2048
LOGIN_WINDOW = 60.0                  # 로그인은 이 초 안에
LOGIN_MAX = 60                       # 전체 이만큼까지(① 커넥션 풀을 지킨다 · 프로세스 하나 기준)
LOGIN_SOURCE_MAX = 6                 # 한 곳(요청한 곳)에서 ① 이 **거절한** 시도가 창마다 이만큼이면 그 곳을 막는다(검토 login-throttle)
#                                      받아 준 로그인 · ① 장애 · 기다리는 중인 시도는 세지 않는다 — 사무실처럼 여럿이 한 주소로 나가도(S12 검토)
LOGIN_TOKEN_MAX = 3                  # 같은 ① 토큰으로 창마다 이만큼 — 받아 주는 토큰 하나를 되풀이해 전체 창을 채우지 못하게(S12 2차 검토)
LOGIN_SOURCES_KEPT = 4096            # 기억하는 요청한 곳 수 상한(메모리)
# 요청한 곳 — ③ 중계(S12)가 넣는 머리. 중계(같은 서버 · 루프백)에서 온 요청일 때만 믿고, 아니면 연결한 주소를 쓴다.
SOURCE_HEADER = "HTTP_X_NAVER_AUTO_SOURCE"
TRUSTED_PEERS = frozenset({"127.0.0.1", "::1"})
# 유닉스 소켓으로 받는 서버(S14)는 IP 가 없다 — 그 서버가 environ 에 이 표지(True)를 넣으면 루프백과 같이 믿는다.
# HTTP_ 로 시작하지 않는 키라 브라우저 머리로는 만들 수 없다(서버만 넣는다) · 소켓 파일 권한이 곧 경계.
# 표지는 연결 주소가 **빈 값**(IP 없는 연결)일 때만 본다 — 미들웨어가 모든 요청에 넣어도 TCP 쪽은 주소로 판단(S12 2차 검토).
TRUSTED_TRANSPORT = "naver_engine.trusted_transport"
_SOURCE = re.compile(r"[0-9A-Fa-f:.]{1,64}")
LINK_BATCH_MAX = 50
NOTE_MAX = 200
PREVIEW_NAMES = 3                    # 짝 후보 미리보기 — 캠페인 이름 3개(B §4)
PREVIEW_NAME_MAX = 60
KST = S.KST

REASONS = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
           405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large", 415: "Unsupported Media Type",
           429: "Too Many Requests", 500: "Internal Server Error", 503: "Service Unavailable"}
HEADERS = (("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"),
           ("Pragma", "no-cache"), ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
           ("X-Frame-Options", "DENY"))
NOT_VISIBLE = {"error": "not-visible", "message": SC.CLIENT_NOT_VISIBLE}


class HttpError(Exception):
    def __init__(self, status: int, code: str, **extra) -> None:
        super().__init__(code)
        self.status, self.code, self.extra = status, code, extra


# ── 요청 ────────────────────────────────────────────────────────────
@dataclass
class Request:
    method: str
    path: str
    query: Mapping[str, str]
    body: Optional[dict]


@dataclass
class Viewer:
    """요청 하나의 보는 사람 — 범위는 이 요청에서 새로 계산한 것."""
    idx: int = field(repr=False)
    scope: SC.Scope = field(repr=False)
    claims: SE.Claims = field(repr=False)
    store: S.Store = field(repr=False)
    org: O.Org = field(repr=False)
    _ctx: Optional[W.Ctx] = field(default=None, repr=False)

    def ctx(self, now: datetime) -> W.Ctx:
        if self._ctx is None:
            self._ctx = W.load(self.store, now, self.org)
        return self._ctx


def _unquote(s: str) -> str:
    """퍼센트 풀기(쿼리 글자) — ``urllib`` 을 쓰지 않는다(네트워크 모듈은 관문에서만)."""
    raw = s.replace("+", " ").encode("utf-8")
    out = bytearray()
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == 0x25:   # '%'
            h = raw[i + 1:i + 3]
            if len(h) != 2 or not all(x in b"0123456789abcdefABCDEF" for x in h):
                raise HttpError(400, "bad-query")
            out.append(int(h, 16))
            i += 3
            continue
        out.append(c)
        i += 1
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        raise HttpError(400, "bad-query") from None


def _parse_query(qs: str) -> Dict[str, str]:
    if len(qs) > QUERY_MAX:
        raise HttpError(400, "bad-query")
    out: Dict[str, str] = {}
    for part in qs.split("&"):
        if not part:
            continue
        k, _sep, v = part.partition("=")
        k = _unquote(k)
        if k in out:
            raise HttpError(400, "bad-query")
        out[k] = _unquote(v)
    return out


def _read_body(environ) -> Optional[dict]:
    try:
        n = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        raise HttpError(400, "bad-length") from None
    if n < 0:
        raise HttpError(400, "bad-length")
    if n > BODY_MAX:
        raise HttpError(413, "too-large")
    if n == 0:
        return None
    ctype = (environ.get("CONTENT_TYPE") or "").split(";")[0].strip().lower()
    if ctype != "application/json":
        raise HttpError(415, "json-only")
    raw = environ["wsgi.input"].read(n)
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != n:
        raise HttpError(400, "bad-body")
    try:
        j = json.loads(bytes(raw).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise HttpError(400, "bad-json") from None
    if not isinstance(j, dict):
        raise HttpError(400, "bad-json")
    return j


def _body(req: Request, keys: frozenset, need: frozenset) -> dict:
    b = req.body or {}
    if not set(b) <= keys or not need <= set(b):
        raise HttpError(400, "bad-body")
    return b


def _pos(v) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not 0 < v < 2 ** 63:
        raise HttpError(400, "bad-body")
    return v


def _text(v, limit: int) -> str:
    if not isinstance(v, str) or not v.strip() or len(v) > limit:
        raise HttpError(400, "bad-body")
    return v


def _utf8(v) -> bool:
    """밖에서 온 글자(미리보기 캠페인 이름)가 응답에 실을 수 있는 글자인가 — 짝 없는 대리 글자 등은 뺀다."""
    if not isinstance(v, str):
        return False
    try:
        v.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _bearer(environ) -> str:
    raw = environ.get("HTTP_AUTHORIZATION") or ""
    head, _sep, tok = raw.partition(" ")
    if head.lower() != "bearer" or not tok.strip():
        raise HttpError(401, "token-missing")
    return tok.strip()


# ── 앱 ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Route:
    method: str
    pattern: "re.Pattern"
    handler: Callable
    auth: bool = True


class App:
    """WSGI 앱. ``open_read()`` = 요청마다 읽기 전용 저장소 · ``write(fn)`` = 쓰기 저장소 한 곳에서 ``fn(store)`` 를 차례로
    돌리고 결과를 돌려준다(S14 배선 — 스케줄러와 같은 쓰기 저장소) · ``previewer(handle)`` = 짝 후보 미리보기(없으면 503)."""

    def __init__(self, *, open_read: Callable[[], S.Store], write: Callable[[Callable[[S.Store], Any]], Any],
                 signer: SE.TokenSigner, profiles: EP.ErpProfileReader, clock: Optional[Callable[[], datetime]] = None,
                 previewer: Optional[Callable[[Any], List[str]]] = None, login_max: int = LOGIN_MAX,
                 login_window: float = LOGIN_WINDOW, monotonic: Optional[Callable[[], float]] = None,
                 login_source_max: int = LOGIN_SOURCE_MAX, login_token_max: int = LOGIN_TOKEN_MAX,
                 owner_verification: bool = False, verified_linking: bool = False,
                 request_collection=None, collection_status=None) -> None:
        if not isinstance(signer, SE.TokenSigner):
            raise TypeError("signer 는 TokenSigner 여야 합니다(비밀값 없이 시작하지 않는다)")
        if type(owner_verification) is not bool:
            raise TypeError("owner_verification 은 참/거짓이어야 합니다")
        if type(verified_linking) is not bool:
            raise TypeError("verified_linking 은 참/거짓이어야 합니다")
        self._open_read, self._write_fn, self._signer, self._profiles = open_read, write, signer, profiles
        # 배선/응답 호환 이름 유지: 읽기 전용 검증판도 매 요청의 기존 SC 범위를 그대로 따른다.
        self._owner_verification = owner_verification
        self._verified_linking = verified_linking
        self._request_collection, self._collection_status = request_collection, collection_status
        self._clock = clock or (lambda: datetime.now(KST))
        self._previewer = previewer
        self._login_max, self._login_window, self._login_source_max = login_max, login_window, login_source_max
        self._login_token_max = login_token_max
        self._mono = monotonic or _time.monotonic
        self._logins: List[float] = []                    # ① 을 부른 시도(전체)
        self._rejected_by: Dict[str, List[float]] = {}    # 한 곳 → ① 이 거절한 시도
        self._tokens: Dict[str, List[float]] = {}         # ① 토큰(열쇠 글자) → ① 을 부른 시도
        self._untrusted_warned = -1e18                    # 믿지 않는 연결의 요청한 곳 머리 — 1분 한 줄
        self._quiet_audit: Dict[str, float] = {}   # 로그인 전 거절 코드 → 마지막으로 기록한 때(창마다 한 줄)
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "App(naver-auto)"

    # ── WSGI ──
    def __call__(self, environ, start_response):
        status, body = self._respond(environ)
        try:
            payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError) as e:   # 글자로 못 바꾸는 값 — 머리는 그대로 · JSON 500
            log.error("화면 API 응답 만들기 실패: %s", type(e).__name__)
            status, payload = 500, b'{"error":"internal"}'
        start_response(f"{status} {REASONS.get(status, 'Error')}",
                       list(HEADERS) + [("Content-Length", str(len(payload)))])
        return [payload]

    def _respond(self, environ) -> Tuple[int, dict]:
        try:
            return self._dispatch(environ)
        except HttpError as e:
            return e.status, {"error": e.code, **e.extra}
        except SC.ClientNotVisible:
            return 404, dict(NOT_VISIBLE)
        except SC.TargetNotVisible:   # 고른 사람·팀 — 없는 번호와 범위 밖 번호가 같은 본문
            return 404, {"error": "not-visible", "message": SC.TARGET_NOT_VISIBLE}
        except SC.SelectionRejected:
            return 400, {"error": "selection-rejected", "message": SC.SELECTION_REJECTED}
        except SC.ActionNotAllowed:
            return 403, {"error": "action-not-allowed", "message": SC.ACTION_NOT_ALLOWED}
        except W.OrgUnavailable:
            return 503, {"error": "org-unavailable"}
        except S.StoreBusy:
            return 503, {"error": "store-busy"}
        except S.StoreRefused as e:   # 저장소가 이 값을 받지 않음 — 저장소 장애가 아니다(검토 client-input-503)
            log.warning("화면 API 저장소 거절: %s", type(e).__name__)
            return 409, {"error": "refused"}
        except S.StoreError as e:
            log.warning("화면 API 저장소 오류: %s", type(e).__name__)
            return 503, {"error": "store-unavailable"}
        except Exception as e:   # 뜻밖의 오류 — 종류 이름만(문구에 값이 섞일 수 있다)
            log.error("화면 API 뜻밖의 오류: %s", type(e).__name__)
            return 500, {"error": "internal"}

    def _dispatch(self, environ) -> Tuple[int, dict]:
        method = environ.get("REQUEST_METHOD") or ""
        path = environ.get("PATH_INFO") or ""
        if not path.startswith(PREFIX + "/"):
            raise HttpError(404, "not-found")
        sub = path[len(PREFIX):]
        if self._owner_verification:
            allowed = ((method == GET and (sub in _VERIFICATION_GETS or _VERIFICATION_CLIENT.fullmatch(sub)))
                       or (method == POST and sub in _VERIFICATION_SESSIONS)
                       or (self._verified_linking and (method, sub) in _VERIFIED_REQUESTS))
            if not allowed:
                # 본문 파싱·조직 조회·감사·handler 호출 전 차단: 업무 쓰기나 미리보기 호출 0.
                raise HttpError(403, "verification-read-only")
        found = [(r, m) for r in ROUTES for m in (r.pattern.fullmatch(sub),) if m is not None]
        if not found:
            raise HttpError(404, "not-found")
        hit = [(r, m) for r, m in found if r.method == method]
        if not hit:
            raise HttpError(405, "method-not-allowed")
        route, m = hit[0]
        query = _parse_query(environ.get("QUERY_STRING") or "")
        body = _read_body(environ) if method == POST else None
        req = Request(method, sub, query, body)
        now = self._now()
        if not route.auth:
            return route.handler(self, req, None, now, environ=environ, **m.groupdict())
        v = self._viewer(environ, now)
        try:
            return route.handler(self, req, v, now, **m.groupdict())
        finally:
            v.store.close()

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise HttpError(500, "clock")
        return now

    # ── 보는 사람 — 모든 경로(로그인 빼고)가 이것을 지난다 ──
    def _viewer(self, environ, now: datetime) -> Viewer:
        tok = _bearer(environ)
        try:
            claims = self._signer.verify(tok, now)
        except SE.TokenInvalid as e:
            raise HttpError(401, "token-" + e.code) from None
        store = self._open_read()
        try:
            org = W.load_org(store)
            who = claims.emp_idx
            scope = SC.narrowed_scope_of(org, who) if claims.narrowed else SC.scope_of(org, who)
            if scope.kind == SC.NONE:
                raise HttpError(401, "no-scope")   # 퇴사 · 조직 표에서 빠짐 — 다음 요청부터 0곳
            if scope.kind != SC.ALL and Y.org_freshness(store, now) in (O.FRESH_STALE, O.FRESH_NONE):
                raise HttpError(503, "org-stale")
            return Viewer(who, scope, claims, store, org)
        except BaseException:
            store.close()
            raise

    # ── 쓰기 · 감사 ──
    def _write(self, fn: Callable[[S.Store], Any]) -> Any:
        return self._write_fn(fn)

    def _audit(self, viewer_idx: Optional[int], action: str, kind: str, target_id: Optional[int], result: str,
               now: datetime, *, required: bool) -> None:
        try:
            self._write(lambda st: st.record_access(viewer_idx, action, kind, target_id, result, now))
        except Exception as e:
            log.warning("열람·쓰기 기록 실패: %s", type(e).__name__)
            if required:
                raise HttpError(503, "audit-unavailable") from None

    def _quiet(self, result: str, now: datetime) -> None:
        """로그인 전 거절(모양 틀림 · 너무 많음)을 창마다 **한 줄만** 기록한다 — 거절은 흔적을 남기되 이름 모를 한 곳이
        쓰는 곳 하나를 기록으로 채우지 못하게."""
        t = self._mono()
        with self._lock:
            last = self._quiet_audit.get(result)
            if last is not None and t - last < self._login_window:
                return
            self._quiet_audit[result] = t
        self._audit(None, "login", "session", None, result, now, required=False)

    def _window(self, book: Dict[str, List[float]], key: str, t: float) -> List[float]:
        mine = [x for x in book.get(key, ()) if t - x < self._login_window]
        if mine:
            book[key] = mine
        else:
            book.pop(key, None)
        return mine

    def _forget(self, book: Dict[str, List[float]]) -> None:
        if len(book) > LOGIN_SOURCES_KEPT:   # 오래된 것부터 잊는다(기억 상한)
            for k in sorted(book, key=lambda k: book[k][-1])[:len(book) // 2]:
                del book[k]

    def _throttle(self, source: str, token_key: str, now: datetime) -> None:
        """① 을 부를 로그인만 센다 — 전체 창 ``login_max``(① 커넥션 보호) · 같은 토큰 창마다 ``login_token_max`` ·
        한 곳에서 ① 이 **거절한** 시도가 ``login_source_max`` 에 닿으면 그 곳을 막는다(받아 준 로그인 · ① 장애 · 기다리는
        중인 시도는 한 곳 창에 없다 — 사무실 한 주소 · 검토 office-nat · inflight)."""
        t = self._mono()
        with self._lock:
            self._logins = [x for x in self._logins if t - x < self._login_window]
            rejected = self._window(self._rejected_by, source, t)
            same = self._window(self._tokens, token_key, t)
            over = (len(rejected) >= self._login_source_max or len(same) >= self._login_token_max
                    or len(self._logins) >= self._login_max)
            if not over:
                self._logins.append(t)
                self._tokens[token_key] = same + [t]
            self._forget(self._tokens)
        if over:
            self._quiet("throttled", now)
            raise HttpError(429, "too-many-logins")

    def _rejected(self, source: str) -> None:
        """① 이 거절한 시도 — 그 곳의 창에 하나(이것만 한 곳 상한을 채운다)."""
        t = self._mono()
        with self._lock:
            self._rejected_by[source] = self._window(self._rejected_by, source, t) + [t]
            self._forget(self._rejected_by)

    def _source(self, environ) -> str:
        peer = environ.get("REMOTE_ADDR") or ""
        hdr = environ.get(SOURCE_HEADER) or ""
        trusted = peer in TRUSTED_PEERS or (peer == "" and environ.get(TRUSTED_TRANSPORT) is True)
        if trusted and isinstance(hdr, str) and _SOURCE.fullmatch(hdr):
            return hdr
        if hdr and not trusted:   # 머리가 왔는데 믿을 연결이 아님 — 소켓 서버 표지 빠짐·위조가 조용히 묻히지 않게(값·주소 없이)
            t = self._mono()
            with self._lock:
                warn = t - self._untrusted_warned >= self._login_window
                if warn:
                    self._untrusted_warned = t
            if warn:
                log.warning("요청한 곳 머리를 믿지 않음 — 믿을 연결이 아님(소켓 서버 표지·루프백 확인)")
        return peer if isinstance(peer, str) and peer else "unknown"

    def _session_out(self, token: str, now: datetime, narrowed: bool) -> dict:
        """토큰의 **실제** 남은 시간 · 세션 끝(로그인 + 12시간) — 화면이 끝을 알고 전산에서 다시 들어오게(검토 expires-in)."""
        c = self._signer.verify(token, now)
        return {"token": token, "expires_in": max(0, int((c.expires_at - now).total_seconds())),
                "session_ends_at": (c.login_at + SE.SESSION_MAX).astimezone(KST).isoformat(timespec="seconds"),
                "narrowed": narrowed}

    # ── 로그인 ──
    def _h_login(self, req: Request, v: None, now: datetime, environ=None) -> Tuple[int, dict]:
        try:
            body = _body(req, frozenset({"code", "codeVerifier"}), frozenset({"code", "codeVerifier"}))
            sso = EP.load_code(body["code"])
            verifier = EP.load_code(body["codeVerifier"])
        except HttpError:
            self._quiet("bad-body", now)
            raise
        except EP.ProfileError as e:   # 토큰 모양이 틀림 — ① 을 부르지 않는다
            self._quiet(e.kind, now)
            raise HttpError(401, e.kind) from None
        source = self._source(environ or {})
        self._throttle(source, sso.bucket_key(), now)   # ① 을 부를 시도만 센다
        try:
            prof = self._profiles.read_profile(sso, verifier)
        except EP.ProfileError as e:
            if e.kind == EP.KIND_REJECTED:
                self._rejected(source)   # ① 이 거절한 시도만 그 곳의 창에(장애·모양 이상은 아님)
            self._audit(None, "login", "session", None, e.kind, now, required=False)
            raise HttpError(401 if e.kind == EP.KIND_REJECTED else 503, e.kind) from None
        store = self._open_read()
        try:
            org = W.load_org(store)
        finally:
            store.close()
        if SC.scope_of(org, prof.idx).kind == SC.NONE:
            self._audit(prof.idx, "login", "session", None, "no-scope", now, required=False)
            raise HttpError(403, "no-scope")
        narrowed = SC.profile_narrows(org, prof.idx, prof.says_manager if prof.team_known else None, prof.team_idx)
        token = self._signer.issue(prof.idx, now, narrowed=narrowed)
        self._audit(prof.idx, "login", "session", None, "narrowed" if narrowed else "ok", now, required=True)
        return 200, self._session_out(token, now, narrowed)

    def _h_refresh(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        try:
            token = self._signer.refresh(v.claims, now)   # 재직은 _viewer 가 조직 표로 방금 확인했다
        except SE.TokenInvalid as e:
            raise HttpError(401, "token-" + e.code) from None
        return 200, self._session_out(token, now, v.claims.narrowed)

    # ── 읽기 ──
    def _h_me(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        ctx = v.ctx(now)
        out = W.me(ctx, v.scope)
        counts = INV.staff_counts(ctx, v.store, v.scope)
        for person in out["people"]:
            person["account_count"] = counts.get(person["idx"], 0)
        out["inventory_enabled"] = True
        out["bell_unread"] = W.bell(v.store, v.idx, now)["unread"]
        if self._owner_verification:
            out["owner_verification"] = True
        out["verified_linking"] = self._verified_linking and v.scope.kind in (SC.ALL, SC.MINE)
        return 200, out

    def _h_accounts(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        if set(req.query) - {"selection", "workflow", "mapping", "view"}:
            raise HttpError(400, "bad-query")
        return 200, INV.board(v.ctx(now), v.store, v.scope, req.query.get("selection", "all"),
                              req.query.get("workflow", "all"), req.query.get("mapping", "all"),
                              req.query.get("view", "current"))

    def _h_dashboard(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        if set(req.query) - {"selection"}:
            raise HttpError(400, "bad-query")
        return 200, DASH.board(v.ctx(now), v.store, v.scope, req.query.get("selection", "all"))

    def _fresh_for_write(self, v: Viewer, store, now: datetime) -> Viewer:
        """쓰기 큐 실행 시점의 신원·조직을 다시 읽는다. 요청 당시 scope를 재사용하지 않는다."""
        if now >= v.claims.expires_at:
            raise HttpError(401, "token-expired")
        org = W.load_org(store)
        scope = SC.narrowed_scope_of(org, v.idx) if v.claims.narrowed else SC.scope_of(org, v.idx)
        if scope.kind == SC.NONE:
            raise HttpError(401, "no-scope")
        if not O.allows_raising(Y.org_freshness(store, now)):
            raise HttpError(409, "org-stale")
        return Viewer(v.idx, scope, v.claims, store, org)

    def _management_account(self, v: Viewer, now: datetime, ad_account_no: str, *, allow_unmatched=False):
        rows = [a for a in v.store.accounts() if a["present"] == 1
                and a["ad_account_no"] is not None and str(a["ad_account_no"]) == ad_account_no]
        if len(rows) != 1:
            raise SC.ClientNotVisible()
        cid = rows[0]["customer_id"]
        return cid, MS.require_action(v.store, now, v.idx, cid, allow_unmatched=allow_unmatched)

    def _control_write(self, v: Viewer, now: datetime, action: str, fn):
        try:
            result = self._write(fn)
        except (SC.ScopeError, HttpError, S.StoreRefused):
            self._audit(v.idx, action, "board", None, "denied", now, required=False)
            raise
        self._audit(v.idx, action, "board", None, "ok", now, required=False)
        return result

    def _h_management_update(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        body = _body(req, frozenset({"ad_account_no", "stage_revision", "included", "reason"}),
                     frozenset({"ad_account_no", "stage_revision", "included", "reason"}))
        ad_no = _text(body["ad_account_no"], 15)
        revision, reason = _text(body["stage_revision"], 200), _text(body["reason"], NOTE_MAX)
        if not re.fullmatch(r"[1-9][0-9]{0,14}", ad_no) or type(body["included"]) is not bool:
            raise HttpError(400, "bad-body")
        def update(st):
            current = self._now()
            fresh = self._fresh_for_write(v, st, current)
            cid, row = self._management_account(fresh, current, ad_no)
            if row["stage_revision"] != revision:
                raise HttpError(409, "stage-changed")
            return st.record_management_override(cid, revision, body["included"], v.idx, current, reason)
        result = self._control_write(v, now, "management-update", update)
        return 200, {"updated": True, "stage_revision": result["stage_revision"], "included": body["included"]}

    def _h_management_collect(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        body = _body(req, frozenset({"ad_account_no"}), frozenset({"ad_account_no"}))
        ad_no = _text(body["ad_account_no"], 15)
        if not re.fullmatch(r"[1-9][0-9]{0,14}", ad_no):
            raise HttpError(400, "bad-body")
        def collect(st):
            current = self._now()
            fresh = self._fresh_for_write(v, st, current)
            cid, _row = self._management_account(fresh, current, ad_no, allow_unmatched=True)
            return st.performance_manual_request(cid, v.idx, current)
        self._control_write(v, now, "management-collect", collect)
        return 200, {"status": "accepted"}

    def _report_context(self, v: Viewer, now: datetime):
        """단계별 구 목록에 없는 업체도 현재 전체 전산 목록의 담당으로 대조한다."""
        ctx = v.ctx(now)
        owns = dict(ctx.owns)
        names = {pid: row["name"] for pid, row in ctx.prospects.items()}
        catalog, state = INV.catalog_status(v.store, now)
        if state != "accepted":
            if v.scope.kind != SC.ALL:
                raise HttpError(503, "catalog-stale")
            return ctx, owns, names, False
        for company in catalog["items"]:
            pid = company["possibility_id"]
            known = company["stage_known"] and not company["stage_hidden"]
            owns[pid] = SC.ownership_for_client(ctx.org, pid, pid, SC.MATCH_PID if known else SC.MATCH_UNKNOWN)
            names[pid] = company["company_name"]
        return ctx, owns, names, True

    def _h_reports(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        if set(req.query) - {"selection"}:
            raise HttpError(400, "bad-query")
        ctx, owns, names, catalog_current = self._report_context(v, now)
        visible = SC.clients_in(ctx.org, v.scope, owns, req.query.get("selection", "all"))
        rows = []
        for report in v.store.report_snapshots():
            pid = report["possibility_id"]
            if pid not in visible:
                continue
            own = owns[pid]
            rows.append({**report, "company_name": names[pid], "owner": W._owner(ctx, own),
                         "can_review": catalog_current and report["status"] == "ready" and O.allows_raising(ctx.freshness)
                         and SC.ACT_APPROVE in SC.allowed_actions(ctx.org, v.scope, own)})
        return 200, {"rows": rows, "schedule": {"timezone": "Asia/Seoul", "weekly": "월요일 10:00",
                                                  "monthly": "매월 3일 10:00"}}

    def _h_report_review(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        body = _body(req, frozenset({"report_id", "decision", "note"}), frozenset({"report_id", "decision", "note"}))
        report_id, note = _pos(body["report_id"]), _text(body["note"], NOTE_MAX)
        if body["decision"] not in ("approved", "held"):
            raise HttpError(400, "bad-body")
        def review(st):
            current = self._now()
            fresh = self._fresh_for_write(v, st, current)
            report = next((row for row in st.report_snapshots() if row["report_id"] == report_id), None)
            if report is None:
                raise SC.ClientNotVisible()
            ctx, owns, _names, catalog_current = self._report_context(fresh, current)
            if not catalog_current:
                raise HttpError(409, "catalog-stale")
            SC.require_client(ctx.org, fresh.scope, owns, report["possibility_id"], SC.ACT_APPROVE)
            if body["decision"] == "approved" and report["status"] != "ready":
                raise HttpError(409, "report-incomplete")
            return st.record_report_review(report_id, v.idx, current, body["decision"], note)
        self._control_write(v, now, "report-review", review)
        return 200, {"report_id": report_id, "review_status": body["decision"]}

    def _h_board(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        sel = req.query.get("selection", "all")
        att = req.query.get("attention", "1")
        if att not in ("0", "1"):
            raise HttpError(400, "bad-query")
        return 200, W.board(v.ctx(now), v.store, v.scope, sel, att == "1")

    def _h_client(self, req: Request, v: Viewer, now: datetime, pid: str) -> Tuple[int, dict]:
        n = int(pid)
        try:
            out = W.client(v.ctx(now), v.store, v.scope, n)
        except (SC.ClientNotVisible, SC.ActionNotAllowed):
            self._audit(v.idx, "view", "client", n, "not-visible", now, required=False)
            raise SC.ClientNotVisible() from None
        self._audit(v.idx, "view", "client", n, "ok", now, required=True)
        return 200, out

    def _h_links_pending(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        out = W.links_pending(v.ctx(now), v.store, v.scope)
        if self._owner_verification and self._verified_linking:
            for row in out["rows"]:
                raw = W.find_ref(v.ctx(now), row["ref"])
                row["can_confirm"] = row["can_confirm"] and self._verified_row_allowed(v, raw, now)
                row["can_reject"] = False
        return 200, out

    def _verified_row_allowed(self, v: Viewer, row, now: datetime) -> bool:
        ctx = v.ctx(now)
        if v.scope.kind not in (SC.ALL, SC.MINE) or row is None or not ctx.pairing_today:
            return False
        if row["state"] != S.PAIR_AUTO and not (row["state"] == S.PAIR_BLOCKED and row["code"] == "name-different"):
            return False
        pid, cid = row["possibility_id"], row["customer_id"]
        own = ctx.owns.get(pid)
        if own is None or SC.ACT_CONFIRM_LINK not in SC.allowed_actions(ctx.org, v.scope, own):
            return False
        a, p = ctx.accounts.get(cid), ctx.prospects.get(pid)
        if not a or a["present"] != 1 or not p or p["present"] != 1 or p["stage_conflict"] or p["end_unreadable"]:
            return False
        if W.link_holders(ctx, pid, cid) or row.get("claimed_elsewhere"):
            return False
        if any(d.possibility_id == pid and d.customer_id == cid for d in ctx.live_decisions):
            return False
        read_at = v.store.accounts_read_at()
        if read_at is None or not timedelta(0) <= now - read_at <= L.ACCOUNTS_MAX_AGE:
            return False
        stage_at = v.store.stage_as_of()
        if ctx.pairing["accounts_read_at"] != read_at or ctx.pairing["stages_as_of"] != stage_at:
            return False
        end = None if p["latest_end_date"] is None else date.fromisoformat(p["latest_end_date"])
        return H.eligibility_reason(p["stage_key"], stage_at, end, now) is None

    def _h_collection_request(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        self._ceo_only(v, "collection-request", "board", now)
        if not self._verified_linking or v.claims.narrowed:
            raise HttpError(403, "verification-read-only")
        _body(req, frozenset(), frozenset())
        if not O.allows_raising(v.ctx(now).freshness):
            raise HttpError(409, "org-stale")
        if self._request_collection is None:
            raise HttpError(503, "collection-unavailable")
        result = self._request_collection(v.idx)
        return (200 if result["status"] == "accepted" else 409), result

    def _h_collection_status(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        self._ceo_only(v, "collection-status", "board", now)
        if not self._verified_linking or v.claims.narrowed:
            raise HttpError(403, "verification-read-only")
        if self._collection_status is None:
            raise HttpError(503, "collection-unavailable")
        return 200, self._collection_status()

    def _h_ended(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        return 200, W.ended(v.ctx(now), v.store, v.scope)

    def _h_unlinked(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        return 200, W.unlinked(v.ctx(now), v.scope)

    def _h_bell(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        return 200, W.bell(v.store, v.idx, now)

    def _h_settings(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        if v.scope.kind not in (SC.ALL, SC.TEAM):
            raise HttpError(403, "settings-denied")   # 담당자는 설정을 보지 않는다(v1.4 §5)
        return 200, W.settings(v.ctx(now), v.store, v.scope)

    def _h_health(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        return 200, W.health(v.ctx(now), v.store, v.scope)

    # ── 이슈 손길 ──
    def _issue(self, v: Viewer, now: datetime, iid: str) -> Tuple[int, dict]:
        n = int(iid)
        issue = v.store.issue(n) if 0 < n < 2 ** 63 else None
        if issue is None:
            raise SC.ClientNotVisible()   # 없는 이슈 = 범위 밖 이슈(같은 404)
        ctx = v.ctx(now)
        return n, {"issue": issue, "own": SC.require_client(ctx.org, v.scope, ctx.owns, issue["possibility_id"],
                                                           SC.ACT_HANDLE_ISSUE)}

    def _issue_write(self, v: Viewer, now: datetime, n: int, action: str, fn) -> Tuple[int, dict]:
        try:
            got = self._write(fn)
        except S.IssueRefused as e:
            self._audit(v.idx, action, "issue", n, "refused-" + e.code, now, required=False)
            raise HttpError(409, e.code) from None
        self._audit(v.idx, action, "issue", n, "ok", now, required=False)
        return 200, {"issue_id": n, "state": got["state"], "severity": got["severity"],
                     "exception_until": got["exception_until"]}

    def _h_issue_ack(self, req: Request, v: Viewer, now: datetime, iid: str) -> Tuple[int, dict]:
        n, _t = self._issue_checked(v, now, iid, "ack")
        return self._issue_write(v, now, n, "ack", lambda st: st.ack_issue(n, v.idx, now))

    def _h_issue_resolve(self, req: Request, v: Viewer, now: datetime, iid: str) -> Tuple[int, dict]:
        n, _t = self._issue_checked(v, now, iid, "resolve")
        return self._issue_write(v, now, n, "resolve", lambda st: st.resolve_issue(n, v.idx, now))

    def _h_issue_except(self, req: Request, v: Viewer, now: datetime, iid: str) -> Tuple[int, dict]:
        n, t = self._issue_checked(v, now, iid, "except")
        body = _body(req, frozenset({"until", "note"}), frozenset({"until", "note"}))
        try:
            until = date.fromisoformat(body["until"]) if isinstance(body["until"], str) else None
        except ValueError:
            until = None
        if until is None:
            raise HttpError(400, "bad-body")
        note = _text(body["note"], NOTE_MAX)
        ctx = v.ctx(now)
        actor = SC.issue_actor(ctx.org, v.scope, t["own"])
        if actor is None:
            raise SC.ActionNotAllowed()
        if not O.allows_raising(ctx.freshness):
            self._audit(v.idx, "except", "issue", n, "org-stale", now, required=False)
            raise HttpError(409, "org-stale")
        return self._issue_write(v, now, n, "except",
                                 lambda st: st.except_issue(n, v.idx, actor, until, note, now))

    def _issue_checked(self, v: Viewer, now: datetime, iid: str, action: str):
        try:
            return self._issue(v, now, iid)
        except (SC.ClientNotVisible, SC.ActionNotAllowed) as e:
            self._audit(v.idx, action, "issue", int(iid),
                        "not-visible" if isinstance(e, SC.ClientNotVisible) else "not-allowed", now, required=False)
            raise

    # ── 짝 확인 ──
    def _link_rows(self, v: Viewer, now: datetime, refs, *, holders_checked: bool) -> List[dict]:
        """가리킴표 묶음 → 마지막 짝 맞추기의 줄. 하나라도 없거나 · 범위 밖이거나 · 이을 수 없는 줄이면 **전체** 거절.
        ``holders_checked`` (확인 · 미리보기) — 그 계정을 다른 가망이 쥐었으면 그 가망들에도 짝 확인을 할 수 있어야 한다
        (``views.clear_for`` · 범위 밖 광고주의 짝을 빼앗거나 읽지 못하게 · 같은 409 로 누구인지 드러내지 않는다)."""
        if not isinstance(refs, list) or not 0 < len(refs) <= LINK_BATCH_MAX or len(set(map(str, refs))) != len(refs):
            raise HttpError(400, "bad-body")
        ctx = v.ctx(now)
        rows = []
        for ref in refs:
            r = W.find_ref(ctx, ref)
            if r is None:
                raise SC.ClientNotVisible()
            SC.require_client(ctx.org, v.scope, ctx.owns, r["possibility_id"], SC.ACT_CONFIRM_LINK)
            rows.append(r)
        for r in rows:   # 범위를 모두 본 뒤에 — 범위 밖 줄이 섞이면 404 가 먼저(가리킴표 순서로 드러나지 않게)
            if not W.linkable(ctx, r) or (holders_checked and not W.clear_for(ctx, v.scope, r["possibility_id"], r)):
                raise HttpError(409, "not-linkable")
        if len({(r["possibility_id"], r["customer_id"]) for r in rows}) != len(rows):
            raise HttpError(400, "bad-body")   # 같은 짝을 두 번(서로 다른 줄로) 가리킴
        return rows

    def _link_checked(self, v: Viewer, now: datetime, refs, action: str, *, holders_checked: bool) -> List[dict]:
        try:
            return self._link_rows(v, now, refs, holders_checked=holders_checked)
        except (SC.ClientNotVisible, SC.ActionNotAllowed) as e:
            self._audit(v.idx, action, "link", None, "not-visible" if isinstance(e, SC.ClientNotVisible)
                        else "not-allowed", now, required=False)
            raise
        except HttpError as e:
            if e.code == "not-linkable":
                self._audit(v.idx, action, "link", None, "not-linkable", now, required=False)
            raise

    def _decide(self, req: Request, v: Viewer, now: datetime, decision: str) -> Tuple[int, dict]:
        body = _body(req, frozenset({"refs"}), frozenset({"refs"}))
        confirm = decision == "confirmed"
        action = "link-" + ("confirm" if confirm else "reject")
        rows = self._link_checked(v, now, body["refs"], action, holders_checked=confirm)
        if confirm and not O.allows_raising(v.ctx(now).freshness):
            self._audit(v.idx, action, "link", None, "org-stale", now, required=False)
            raise HttpError(409, "org-stale")
        pairs = [(r["possibility_id"], r["customer_id"]) for r in rows]
        try:   # 판단 줄과 열람·쓰기 기록을 한 거래로 — 중간에 멈춰도 앞 줄만 남지 않는다
            ids = self._write(lambda st: st.record_decisions(pairs, decision, v.idx, now, audit_action=action))
        except S.StoreError:
            self._audit(v.idx, action, "link", None, "failed", now, required=False)
            raise
        return 200, {"decided": len(ids), "decision": decision}

    def _h_links_confirm(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        if self._owner_verification and self._verified_linking:
            body = _body(req, frozenset({"refs", "ad_account_no"}), frozenset({"refs"}))
            # 저장 큐 차례에 최신 조직/계정/계약/짝을 다시 읽는다. 앞 요청의 읽기 스냅샷을 쓰지 않는다.
            def confirm(st):
                current = self._now()
                fresh = self._fresh_for_write(v, st, current)
                rows = self._link_rows(fresh, current, body["refs"], holders_checked=True)
                if not O.allows_raising(fresh.ctx(current).freshness):
                    raise HttpError(409, "org-stale")
                if not all(self._verified_row_allowed(fresh, r, current) for r in rows):
                    raise HttpError(409, "not-verified-link")
                # 이름이 다른 계정은 사람이 원본에서 대조한 광고계정 ID를 하나씩 제출해야 한다.
                # 고객번호 끝자리나 비슷한 이름만으로 확인하거나 묶어서 우회할 수 없다.
                different = [r for r in rows if r["code"] != "same"]
                if different:
                    raw = body.get("ad_account_no")
                    if (len(rows) != 1 or not isinstance(raw, str) or not re.fullmatch(r"[1-9][0-9]{0,14}", raw)
                            or fresh.ctx(current).accounts[rows[0]["customer_id"]]["ad_account_no"] != int(raw)):
                        raise HttpError(409, "account-proof-required")
                elif "ad_account_no" in body:
                    raise HttpError(400, "bad-body")
                return st.record_decisions([(r["possibility_id"], r["customer_id"]) for r in rows],
                                           "confirmed", v.idx, current, audit_action="link-confirm")
            ids = self._write(confirm)
            return 200, {"decided": len(ids), "decision": "confirmed"}
        return self._decide(req, v, now, "confirmed")

    def _h_links_reject(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        return self._decide(req, v, now, "rejected")

    def _h_links_revoke(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        body = _body(req, frozenset({"decision_id", "reason"}), frozenset({"decision_id", "reason"}))
        did, reason = _pos(body["decision_id"]), _text(body["reason"], 64)
        found = [d for d in v.store.current_decisions() + v.store.superseded_confirmations() if d.decision_id == did]
        ctx = v.ctx(now)
        try:
            if not found:
                raise SC.ClientNotVisible()
            SC.require_client(ctx.org, v.scope, ctx.owns, found[0].possibility_id, SC.ACT_CONFIRM_LINK)
        except (SC.ClientNotVisible, SC.ActionNotAllowed):
            self._audit(v.idx, "link-revoke", "link", None, "not-visible", now, required=False)
            raise SC.ClientNotVisible() from None
        try:
            self._write(lambda st: st.revoke_decision(did, v.idx, now, reason))
        except S.StoreRefused:
            self._audit(v.idx, "link-revoke", "link", found[0].possibility_id, "refused", now, required=False)
            raise HttpError(409, "revoke-refused") from None
        self._audit(v.idx, "link-revoke", "link", found[0].possibility_id, "ok", now, required=False)
        return 200, {"revoked": did}

    def _h_links_preview(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        body = _body(req, frozenset({"ref"}), frozenset({"ref"}))
        [r] = self._link_checked(v, now, [body["ref"]], "link-preview", holders_checked=True)
        if self._previewer is None:
            raise HttpError(503, "preview-unavailable")
        ctx = v.ctx(now)
        p = ctx.prospects[r["possibility_id"]]
        end = None if p["latest_end_date"] is None else date.fromisoformat(p["latest_end_date"])
        try:
            handle = H.issue_preview_handle(customer_id=r["customer_id"], possibility_id=r["possibility_id"],
                                            candidate_id=ctx.pairing["pairing_id"], stage=p["stage_key"],
                                            stage_as_of=v.store.stage_as_of(), latest_end_date=end, now=now,
                                            requested_by=v.idx)
        except H.NotEligible as e:
            raise HttpError(409, "not-eligible", reason=e.reason) from None
        try:
            names = self._previewer(handle)
        except Exception as e:
            log.warning("미리보기 실패: %s", type(e).__name__)
            raise HttpError(503, "preview-failed") from None
        out = [n[:PREVIEW_NAME_MAX] for n in (names if isinstance(names, (list, tuple)) else []) if _utf8(n)]
        self._audit(v.idx, "link-preview", "link", r["possibility_id"], "ok", now, required=True)
        return 200, {"campaigns": out[:PREVIEW_NAMES]}

    # ── 🔔 ──
    def _h_bell_read(self, req: Request, v: Viewer, now: datetime, rid: str) -> Tuple[int, dict]:
        n = int(rid)
        if not 0 < n < 2 ** 63:
            raise HttpError(404, "not-found")
        if n not in {r["recipient_id"] for r in W.bell(v.store, v.idx, now)["items"]}:
            self._audit(v.idx, "bell-read", "alert", n, "not-found", now, required=False)
            raise HttpError(404, "not-found")
        try:
            changed = self._write(lambda st: st.mark_alert_read(n, v.idx, now))
        except S.ScreenRefused:
            self._audit(v.idx, "bell-read", "alert", n, "not-found", now, required=False)
            raise HttpError(404, "not-found") from None   # 없는 줄 = 남의 줄
        self._audit(v.idx, "bell-read", "alert", n, "ok", now, required=False)
        return 200, {"read": True, "changed": changed}

    def _h_bell_read_all(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        visible = [r["recipient_id"] for r in W.bell(v.store, v.idx, now)["items"] if not r["read"]]
        n = self._write(lambda st: sum(st.mark_alert_read(rid, v.idx, now) for rid in visible))
        self._audit(v.idx, "bell-read-all", "alert", None, "ok", now, required=False)
        return 200, {"changed": n}

    # ── 설정(대표만) ──
    def _ceo_only(self, v: Viewer, action: str, kind: str, now: datetime) -> None:
        if v.scope.kind != SC.ALL:
            self._audit(v.idx, action, kind, None, "not-allowed", now, required=False)
            raise HttpError(403, "ceo-only")

    def _h_settings_thresholds(self, req: Request, v: Viewer, now: datetime) -> Tuple[int, dict]:
        self._ceo_only(v, "thresholds", "settings", now)
        try:
            body = _body(req, frozenset({"changes"}), frozenset({"changes"}))
            if not isinstance(body["changes"], dict):
                raise HttpError(400, "bad-body")
        except HttpError:
            self._audit(v.idx, "thresholds", "settings", None, "bad-body", now, required=False)
            raise
        try:
            new = self._write(lambda st: st.record_thresholds(body["changes"], v.idx, now))
        except S.ScreenRefused as e:
            self._audit(v.idx, "thresholds", "settings", None, "refused-" + e.code, now, required=False)
            raise HttpError(409 if e.code == "no-change" else 400, e.code, fields=list(e.fields)) from None
        self._audit(v.idx, "thresholds", "settings", None, "ok", now, required=False)
        return 200, {"thresholds": W._thresholds_out(new)}

    def _h_hold_confirm(self, req: Request, v: Viewer, now: datetime, kind: str) -> Tuple[int, dict]:
        self._ceo_only(v, "hold-confirm", "hold", now)
        body = _body(req, frozenset({"hold_id"}), frozenset({"hold_id"}))
        hid = _pos(body["hold_id"])
        confirm = {S.SYNC_ORG: Y.confirm_org, S.SYNC_STAGES: Y.confirm_stages, S.SYNC_ACCOUNTS: L.confirm_accounts}[kind]
        res = self._write(lambda st: confirm(st, now, v.idx, hid))
        ok = res.outcome == S.SYNC_ACCEPTED
        self._audit(v.idx, "hold-confirm", "hold", hid, "ok" if ok else "refused", now, required=False)
        return (200 if ok else 409), {"outcome": res.outcome, "codes": list(res.codes)}


ROUTES: Tuple[Route, ...] = tuple(Route(m, re.compile(p), h, a) for m, p, h, a in (
    (POST, r"/session", App._h_login, False),
    (POST, r"/session/refresh", App._h_refresh, True),
    (GET, r"/me", App._h_me, True),
    (GET, r"/board", App._h_board, True),
    (GET, r"/accounts", App._h_accounts, True),
    (GET, r"/dashboard", App._h_dashboard, True),
    (POST, r"/management/update", App._h_management_update, True),
    (POST, r"/management/collect", App._h_management_collect, True),
    (GET, r"/reports", App._h_reports, True),
    (POST, r"/reports/review", App._h_report_review, True),
    (GET, r"/clients/(?P<pid>[0-9]{1,18})", App._h_client, True),
    (POST, r"/issues/(?P<iid>[0-9]{1,18})/ack", App._h_issue_ack, True),
    (POST, r"/issues/(?P<iid>[0-9]{1,18})/resolve", App._h_issue_resolve, True),
    (POST, r"/issues/(?P<iid>[0-9]{1,18})/except", App._h_issue_except, True),
    (GET, r"/links/pending", App._h_links_pending, True),
    (POST, r"/links/confirm", App._h_links_confirm, True),
    (POST, r"/collection/request", App._h_collection_request, True),
    (GET, r"/collection/status", App._h_collection_status, True),
    (POST, r"/links/reject", App._h_links_reject, True),
    (POST, r"/links/revoke", App._h_links_revoke, True),
    (POST, r"/links/preview", App._h_links_preview, True),
    (GET, r"/ended", App._h_ended, True),
    (GET, r"/unlinked", App._h_unlinked, True),
    (GET, r"/bell", App._h_bell, True),
    (POST, r"/bell/(?P<rid>[0-9]{1,18})/read", App._h_bell_read, True),
    (POST, r"/bell/read-all", App._h_bell_read_all, True),
    (GET, r"/settings", App._h_settings, True),
    (POST, r"/settings/thresholds", App._h_settings_thresholds, True),
    (POST, r"/holds/(?P<kind>org|stages|accounts)/confirm", App._h_hold_confirm, True),
    (GET, r"/health", App._h_health, True),
))


def build_app(*, open_read: Callable[[], S.Store], write: Callable[[Callable[[S.Store], Any]], Any],
              env: Optional[Mapping[str, str]] = None, **kw) -> App:
    """엔진 배선(S14)이 부르는 앱 만들기 — 토큰 비밀값(``NAVER_AUTO_TOKEN_SECRET``)이 없거나 32자 미만이면
    ``CredentialsMissing`` 으로 **시작하지 않는다**(폴백 없음). ① 내 정보 관문은 여기서 만든다."""
    signer = SE.TokenSigner(SE.load_token_secret(env))
    return App(open_read=open_read, write=write, signer=signer, profiles=kw.pop("profiles", None) or EP.ErpProfileReader(env=env),
               **kw)
