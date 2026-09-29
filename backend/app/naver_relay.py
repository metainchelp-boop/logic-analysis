"""③ → 관제 엔진 중계(S12) — 표준 라이브러리만.

자리: ``backend/app`` 바로 아래(③ 앱 모듈). ``app/naver_auto``(엔진이 같은 프로세스에서 쓰는 순수 모듈 · 네트워크 금지)에
두지 않는다 — 이 파일은 엔진으로 가는 연결을 만든다.

설계: docs/superpowers/specs/2026-09-27-naver-ai-autopilot-design.md (S12 · M6 · M7 · 검토 6 로그인 속도 제한).

하는 일
- 직원 브라우저의 ``/api/naver-auto/*`` 요청을 **같은 서버 안의 엔진**으로 넘기고, 엔진의 JSON 답을 그대로 돌려준다.
- 엔진 주소는 **루프백(127.0.0.1 · ::1) 또는 이 서버의 유닉스 소켓 파일만** 받는다. 그 밖의 주소는 설정 틀림 = 꺼짐.
  ⇒ 설정을 잘못 적어도 중계가 바깥으로 나가는 길은 없다(나가는 요청은 ``http.client`` 하나 · 프록시 환경변수를 읽지 않는다).
- 넘기는 머리는 **정한 것만**: ``Authorization``(엔진 토큰 모양일 때만) · ``Content-Type``(JSON) · 길이 ·
  요청한 곳(``X-Naver-Auto-Source`` — 중계가 직접 채운다). 쿠키·③ 로그인 토큰·밖에서 온 같은 이름 머리는 넘기지 않는다.
- 본문 64KB(엔진과 같다) · 주소 조각은 엔진 경로 모양만 · 다른 곳(Origin)에서 온 요청은 거절.

스위치
- ``NAVER_AUTO_WEB=on`` 일 때만 켜진다. 없거나 다른 값이면 ``/naver/`` · ``/api/naver-auto`` 는 **라우트가 아예 맞지 않아**
  없는 주소와 같은 답(GET·HEAD 404 · 그 밖 방식 405 — 정적 마운트가 주는 그대로).
- ``NAVER_AUTO_ENGINE`` = ``unix:/절대/경로.sock`` 또는 ``127.0.0.1:포트`` · ``[::1]:포트``.
  없거나 모양이 틀리면 스위치가 켜져 있어도 ``/api/naver-auto`` 는 503(engine-unavailable) — 화면은 뜬다.
  ③ 자기 자신을 가리키게 잘못 넣으면(되돌이) 503(engine-misconfigured).
  엔진을 별도 컨테이너로 띄울 때(S14)는 **유닉스 소켓** — ③ 와 엔진이 같이 붙인 **폴더**(파일 하나가 아니라) 안의 소켓.

기록
- 토큰·본문·주소(IP)·쿼리·소켓 경로는 어디에도 적지 않는다(repr 포함). 엔진에 닿지 못한 일만 종류 이름으로 종류마다 1분에 한 줄.

요청한 곳
- IPv4 는 그대로 · ``::ffff:a.b.c.d`` 는 IPv4 로 · IPv6 는 **/64 대역**(한 집·한 회선이 받는 단위)으로 묶어 넘긴다 —
  한 사람이 자기 /64 안에서 주소를 바꿔 가며 엔진의 한 곳 상한을 비켜 가지 못하게(S12 2차 검토).
"""
from __future__ import annotations

import http.client
import ipaddress
import logging
import os
import pathlib
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

log = logging.getLogger("naver_relay")

ENV_SWITCH = "NAVER_AUTO_WEB"
ENV_ENGINE = "NAVER_AUTO_ENGINE"
SWITCH_ON = "on"

PREFIX = "/api/naver-auto"
BODY_MAX = 64 * 1024                  # 엔진 BODY_MAX 와 같다
QUERY_MAX = 2048                      # 엔진 QUERY_MAX 와 같다
RESPONSE_MAX = 4 * 1024 * 1024        # 엔진 답 상한(900곳 판 한 장이 수백 KB)
CONNECT_TIMEOUT = 3.0
# 한 워커에서 엔진을 동시에 기다리는 요청 상한 — ③ 다른 경로(대부분 동기 def)와 같은 스레드풀(기본 40)을 쓰므로
# 엔진이 느려도 스레드풀을 다 먹지 않게. 넘치면 기다리지 않고 바로 503(M7).
MAX_INFLIGHT = 8
TOTAL_TIMEOUT = 30.0                  # 요청 하나 전체 · gunicorn 120초 안. 엔진 미리보기(네이버 부름)는 S14 가 이보다 짧은
#                                       자체 마감(20초 안)으로 배선한다 — 넘으면 화면은 504 인데 엔진은 끝까지 돌기 때문(S12 2차 검토)
UNIX_PATH_MAX = 100                   # sun_path 108 바이트 안

SOURCE_HEADER = "X-Naver-Auto-Source"
ENGINE_HOST_HEADER = "naver-engine"   # 엔진은 Host 를 보지 않는다 — 브라우저의 Host 를 넘기지 않으려고 고정값

# 엔진이 쓰는 경로 모양(web.py ROUTES) — 영문·숫자·밑줄·빼기 조각만. 점(.)은 없다 → 「..」 로 옆길 불가.
_SUB = re.compile(r"(?:/[A-Za-z0-9_-]{1,64}){1,6}")
_QUERY = re.compile(r"[\x21-\x7e]*")
# 엔진 자체 토큰(session.py) = 「v1.본문.서명」. ③ 로그인 토큰(JWT · eyJ…)은 이 모양이 아니다 → 넘기지 않는다.
# 「bearer」 대소문자 · 사이 빈칸은 엔진이 받는 만큼 받고, 넘길 때는 「Bearer 토큰」 한 모양으로 다시 쓴다.
_ENGINE_TOKEN = re.compile(r"[Bb][Ee][Aa][Rr][Ee][Rr] +(v1\.[A-Za-z0-9_-]{1,4096}\.[A-Za-z0-9_-]{16,128}) *")
_LENGTH = re.compile(r"[0-9]{1,10}")               # 엔진 답 길이 — ASCII 숫자만(위첨자 ² 같은 숫자 모양 글자 거절)
_IP = re.compile(r"[0-9A-Fa-f:.]{1,64}")          # 엔진 _SOURCE 와 같은 모양
_TCP = re.compile(r"(127\.0\.0\.1|\[::1\]):([0-9]{1,5})")
_UNIX = re.compile(r"unix:(/[A-Za-z0-9_./-]{1,%d})" % (UNIX_PATH_MAX - 1))
_FETCH_SITES_OK = frozenset({"same-origin", "none"})

PASS_STATUS = frozenset({200, 400, 401, 403, 404, 405, 409, 413, 415, 429, 500, 503})
REASONS = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
           405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large", 415: "Unsupported Media Type",
           429: "Too Many Requests", 500: "Internal Server Error", 502: "Bad Gateway", 503: "Service Unavailable",
           504: "Gateway Timeout"}
# 답 머리는 중계가 새로 만든다(엔진 머리를 옮겨 싣지 않는다)
RESPONSE_HEADERS: Tuple[Tuple[str, str], ...] = (
    ("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"), ("Pragma", "no-cache"),
    ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"))

# 화면(/naver/) — S13 이 파일을 둔다. 여기서는 어떤 파일을 어떤 머리로 내주는지만 정한다.
PAGE_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
              ".css": "text/css; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml",
              ".woff2": "font/woff2", ".ico": "image/x-icon"}
_PAGE = re.compile(r"(?:[A-Za-z0-9_-]{1,64}/){0,3}[A-Za-z0-9_-]{1,64}(?:\.[a-z0-9]{1,5})")
# 주소창에 ① 이 준 sso 가 실려 온다 — 다른 곳으로 새지 않게(Referer 0 · 바깥 연결 0 · 틀 안에 못 넣음 · 캐시 0)
PAGE_HEADERS: Tuple[Tuple[str, str], ...] = (
    ("Cache-Control", "no-store"), ("Pragma", "no-cache"), ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
    ("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                "img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; "
                                "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"))


class RelayOff(Exception):
    """스위치가 꺼져 있다 — 부르는 쪽은 없는 주소와 똑같은 답(GET·HEAD 404 · 그 밖 405)을 돌려준다."""


# ── 설정 ────────────────────────────────────────────────────────────
def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    e = os.environ if env is None else env
    return e.get(ENV_SWITCH) == SWITCH_ON


@dataclass(frozen=True, repr=False)
class Target:
    kind: str                  # "unix" · "tcp"
    path: str = ""             # unix
    host: str = ""             # tcp — 127.0.0.1 · ::1 만
    port: int = 0

    def __repr__(self) -> str:                 # 종류만 — 소켓 경로·포트를 기록·오류 문구에 싣지 않는다
        return "Target(%s)" % self.kind


def engine_target(env: Optional[Mapping[str, str]] = None) -> Optional[Target]:
    """엔진 주소 — 루프백 또는 유닉스 소켓만. 그 밖(바깥 주소 · 이름 · 모양 틀림)은 None = 꺼진 것과 같다."""
    e = os.environ if env is None else env
    raw = e.get(ENV_ENGINE)
    if not isinstance(raw, str) or not raw:
        return None
    m = _UNIX.fullmatch(raw)
    if m:
        path = m.group(1)
        if "/../" in path + "/" or "/./" in path + "/" or "//" in path:
            return None
        return Target("unix", path=path)
    m = _TCP.fullmatch(raw)
    if m:
        port = int(m.group(2))
        if not 1 <= port <= 65535:
            return None
        return Target("tcp", host="::1" if m.group(1) == "[::1]" else "127.0.0.1", port=port)
    return None


# ── 들어온 요청 · 나가는 답 ───────────────────────────────────────────
@dataclass(frozen=True)
class Incoming:
    """라우터가 브라우저 요청에서 **정한 칸만** 옮겨 담는다(나머지 머리는 여기 들어오지도 않는다)."""
    method: str
    sub: str                                            # /api/naver-auto 뒤 — "/board" 같은 모양
    query: str = field(default="", repr=False)
    authorization: Tuple[str, ...] = field(default=(), repr=False)
    content_type: Optional[str] = None
    body: Optional[bytes] = field(default=None, repr=False)
    real_ip: Optional[str] = field(default=None, repr=False)   # nginx 가 덮어쓰는 X-Real-IP
    peer: Optional[str] = field(default=None, repr=False)      # 연결한 주소
    origin: Optional[str] = field(default=None, repr=False)
    host: Optional[str] = field(default=None, repr=False)
    fetch_site: Optional[str] = None


@dataclass(frozen=True)
class Outgoing:
    status: int
    body: bytes = field(repr=False)
    headers: Tuple[Tuple[str, str], ...] = RESPONSE_HEADERS


def _err(status: int, code: str) -> Outgoing:
    return Outgoing(status, ('{"error":"%s"}' % code).encode("ascii"))


_last_warn: dict = {}                              # 종류 → 마지막으로 적은 때(종류마다 1분에 한 줄)
_warn_lock = threading.Lock()
_slots = threading.BoundedSemaphore(MAX_INFLIGHT)


def _warn(kind: str) -> None:
    """엔진에 닿지 못한 일 — 종류 이름만 · 종류마다 1분에 한 줄(요청마다 쌓이지 않게 · 한 종류가 다른 종류를 가리지 않게)."""
    now = time.monotonic()
    with _warn_lock:
        if now - _last_warn.get(kind, -1e9) < 60.0:
            return
        if len(_last_warn) > 64:
            _last_warn.clear()
        _last_warn[kind] = now
    log.warning("관제 엔진 중계 실패: %s", kind)


# ── 요청한 곳 · 다른 곳 막기 ──────────────────────────────────────────
def _grouped(v: str) -> Optional[str]:
    """주소 하나 → 엔진이 셀 「한 곳」 글자. IPv4 그대로 · IPv4 를 품은 IPv6 는 IPv4 로 · IPv6 는 /64 대역의 앞 주소."""
    try:
        a = ipaddress.ip_address(v)
    except ValueError:
        return None
    if isinstance(a, ipaddress.IPv6Address):
        if a.is_loopback:
            return str(a)
        if a.ipv4_mapped is not None:
            return str(a.ipv4_mapped)
        return str(ipaddress.IPv6Network((int(a) >> 64 << 64, 64)).network_address)
    return str(a)


def source_of(inc: Incoming) -> Optional[str]:
    """nginx 가 넣는 X-Real-IP(브라우저가 보낸 값은 nginx 가 덮어쓴다) → 없으면 연결한 주소 → 둘 다 모양이 틀리면 없음.
    X-Forwarded-For 는 보지 않는다(브라우저가 앞자리를 지어낼 수 있다). IPv6 는 /64 로 묶는다."""
    return source_from(inc.real_ip, inc.peer)


def source_from(real_ip: Optional[str], peer: Optional[str]) -> Optional[str]:
    """``source_of`` 와 같은 규칙 — 머리 값과 연결 주소만으로(③ 로그인 실패 제한도 같은 규칙을 쓴다 · S0)."""
    for v in (real_ip, peer):
        if isinstance(v, str) and _IP.fullmatch(v):
            g = _grouped(v)
            if g is not None:
                return g
    return None


def _looped(inc: Incoming) -> bool:
    """엔진 주소를 ③ 자기 자신으로 잘못 넣어 중계의 요청이 되돌아왔는가 — 중계가 넣은 Host 가 루프백 연결로,
    nginx 머리(X-Real-IP) 없이 들어온 것. 밖에서 Host 만 흉내 내면(nginx 를 지나 X-Real-IP 가 붙는다) 해당 없음."""
    return (isinstance(inc.host, str) and _host_only(inc.host) == ENGINE_HOST_HEADER
            and inc.peer in ("127.0.0.1", "::1") and inc.real_ip is None)


_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _split_authority(v: str) -> Tuple[str, str]:
    """「호스트:포트」 → (호스트, 포트 글자 · 없으면 빈 값). [::1]:8080 모양도."""
    v = v.strip().lower()
    if v.startswith("["):
        end = v.find("]")
        if end < 0:
            return v, ""
        rest = v[end + 1:]
        return v[:end + 1], rest[1:] if rest.startswith(":") else rest
    if v.count(":") == 1:
        host, port = v.split(":")
        return host, port
    return v, ""


def _host_only(v: str) -> str:
    v = v.strip().lower()
    if v.startswith("["):                       # [::1]:8080
        return v[: v.find("]") + 1] if "]" in v else v
    return v.rsplit(":", 1)[0] if v.count(":") == 1 else v


def cross_origin(inc: Incoming) -> bool:
    """다른 곳(다른 사이트 · 같은 회사 다른 주소 · 같은 호스트 다른 포트 포함)의 화면이 부른 요청이면 참.
    같은 주소 화면의 fetch 는 Sec-Fetch-Site=same-origin · Origin 의 호스트·포트 = Host 의 호스트·포트(기본 포트는
    없는 것과 같다 — nginx 는 Host 에 포트를 싣지 않는다). 방식(http/https)은 Host 로 알 수 없어 비교하지 않는다 —
    브라우저는 방식이 다르면 Sec-Fetch-Site 를 same-origin 으로 보내지 않는다(그 겹이 막는다)."""
    if inc.fetch_site is not None and inc.fetch_site.strip().lower() not in _FETCH_SITES_OK:
        return True
    if inc.origin is not None:
        o = inc.origin.strip().lower()
        if o == "null" or "://" not in o:
            return True
        if not inc.host:
            return True
        scheme, rest = o.split("://", 1)
        oh, op = _split_authority(rest.split("/", 1)[0])
        if op == _DEFAULT_PORTS.get(scheme):
            op = ""
        hh, hp = _split_authority(inc.host)
        if hp in _DEFAULT_PORTS.values():
            hp = ""
        if (oh, op) != (hh, hp):
            return True
    return False


# ── 엔진 연결 ────────────────────────────────────────────────────────
class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__(ENGINE_HOST_HEADER, timeout=timeout)
        self._unix_path = path

    def connect(self):
        """리눅스는 시간 제한이 걸린 유닉스 소켓의 connect 를 대기열이 차면 기다리지 않고 바로 EAGAIN 으로 돌려준다 —
        연결 시간 제한 안에서 짧게 쉬며 다시 시도한다(엔진이 잠깐 바쁜 것을 「엔진 없음」으로 읽지 않게)."""
        end = time.monotonic() + self.timeout
        while True:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.settimeout(max(0.01, end - time.monotonic()))
                s.connect(self._unix_path)
            except BlockingIOError:
                s.close()
                if time.monotonic() >= end:
                    raise socket.timeout("connect") from None
                time.sleep(0.02)
                continue
            except BaseException:
                s.close()
                raise
            self.sock = s
            return


def _open(target: Target, timeout: float) -> http.client.HTTPConnection:
    """엔진으로 가는 연결 — 검사한 Target 으로만 만든다(루프백 · 유닉스 소켓)."""
    if target.kind == "unix":
        return _UnixConnection(target.path, timeout)
    if target.kind == "tcp" and target.host in ("127.0.0.1", "::1"):
        return http.client.HTTPConnection(target.host, target.port, timeout=timeout)
    raise ValueError("engine-target")


class _Truncated(Exception):
    """엔진 답이 말한 길이만큼 오지 않았다(도중에 끊김)."""


def _read_exact(resp: http.client.HTTPResponse, conn: http.client.HTTPConnection, deadline: float, n: int) -> bytes:
    """말한 길이(n)만큼 끝까지 — 도중에 끊기면 ``_Truncated``(잘린 본문을 200 으로 넘기지 않는다)."""
    buf = bytearray()
    while len(buf) < n:
        left = deadline - time.monotonic()
        if left <= 0:
            raise socket.timeout("total")
        if conn.sock is not None:
            conn.sock.settimeout(left)
        chunk = resp.read(min(65536, n - len(buf)))
        if not chunk:
            raise _Truncated()
        buf += chunk
    return bytes(buf)


def relay(inc: Incoming, env: Optional[Mapping[str, str]] = None, *, total_timeout: float = TOTAL_TIMEOUT) -> Outgoing:
    """들어온 요청 하나를 엔진으로 넘긴다. 스위치가 꺼져 있으면 ``RelayOff``."""
    if not enabled(env):
        raise RelayOff()
    if cross_origin(inc):
        return _err(403, "cross-origin")
    if inc.method not in ("GET", "POST"):
        return _err(405, "method-not-allowed")
    if _looped(inc):
        _warn("engine-loop")                           # 엔진 주소를 ③ 자기 자신으로 잘못 넣었다 — 제 요청이 되돌아옴
        return _err(503, "engine-misconfigured")
    if not isinstance(inc.sub, str) or not _SUB.fullmatch(inc.sub):
        return _err(404, "not-found")
    q = inc.query or ""
    if len(q) > QUERY_MAX or not _QUERY.fullmatch(q):
        return _err(400, "bad-query")
    if len(inc.authorization) > 1:
        return _err(400, "bad-authorization")

    headers = {"Host": ENGINE_HOST_HEADER, "Accept": "application/json", "Connection": "close"}
    body = b""
    if inc.method == "POST":
        body = inc.body or b""
        if len(body) > BODY_MAX:
            return _err(413, "too-large")
        if body:
            ctype = (inc.content_type or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return _err(415, "json-only")
            headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
    tok = _ENGINE_TOKEN.fullmatch(inc.authorization[0]) if inc.authorization else None
    if tok:
        headers["Authorization"] = "Bearer " + tok.group(1)      # 엔진 토큰만 · ③ 토큰은 넘기지 않는다
    src = source_of(inc)
    if src is not None:
        headers[SOURCE_HEADER] = src

    target = engine_target(env)
    if target is None:
        _warn("engine-not-configured")
        return _err(503, "engine-unavailable")

    if not _slots.acquire(blocking=False):
        _warn("relay-busy")
        return _err(503, "relay-busy")
    try:
        return _forward(inc, target, headers, body, q, total_timeout)
    finally:
        _slots.release()


def _cut(box: list) -> None:
    """마감 — 엔진과의 연결을 끊는다. 조금씩 흘리는 답 · 1xx 되풀이처럼 「읽을 때마다 시간 제한이 새로 열리는」 경우도
    전체 시간(total_timeout) 안에 끝나게 하는 유일한 겹. ``box`` 에 연결이 아직 없으면(연결 중) 할 일 없음 —
    연결은 자기 시간 제한(CONNECT_TIMEOUT ≤ 전체)으로 끝나고, 끝난 뒤 ``late()`` 가 잡는다."""
    for sock in list(box):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _forward(inc: Incoming, target: Target, headers: dict, body: bytes, q: str, total_timeout: float) -> Outgoing:
    deadline = time.monotonic() + max(0.01, total_timeout)
    path = PREFIX + inc.sub + ("?" + q if q else "")
    conn = _open(target, min(CONNECT_TIMEOUT, max(0.01, total_timeout)))
    box: list = []                                     # 마감 감시가 끊을 연결(연결된 뒤에 담는다)
    timer = threading.Timer(max(0.0, deadline - time.monotonic()), _cut, (box,))
    timer.daemon = True

    def late() -> bool:
        return time.monotonic() >= deadline - 0.005

    try:
        try:
            timer.start()                              # 연결을 열기 전에 — 스레드를 못 만들면 연결 없이 끝낸다
        except RuntimeError:
            _warn("relay-no-thread")
            return _err(503, "relay-busy")
        try:
            conn.connect()
            sock = conn.sock
            box.append(sock)
            if late():
                raise socket.timeout("total")
            sock.settimeout(max(0.01, deadline - time.monotonic()))
            conn.putrequest(inc.method, path, skip_host=True, skip_accept_encoding=True)
            for k, v in headers.items():
                conn.putheader(k, v)
            try:
                conn.endheaders(body if body else None)
            except (BrokenPipeError, ConnectionResetError):
                if late():
                    raise
                # 엔진이 본문을 다 받기 전에 답하고 닫았다(413·405 등) — 이미 보낸 답이 있으면 그것을 읽는다
            resp = conn.getresponse()
            if late():                                  # 마감이 머리를 읽는 도중에 끊었다 — 잘린 머리를 판정하지 않는다
                _warn("engine-timeout")
                return _err(504, "engine-timeout")
            status = resp.status
            ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
            length = (resp.getheader("Content-Length") or "").strip()
            if status not in PASS_STATUS or ctype != "application/json":
                _warn("engine-bad-answer")
                return _err(502, "bad-gateway")
            # 엔진은 늘 길이를 말한다 — 길이 없는 답(조각 · 끊길 때까지)은 잘렸는지 알 수 없어 받지 않는다
            if not _LENGTH.fullmatch(length) or resp.getheader("Transfer-Encoding"):
                _warn("engine-bad-answer")
                return _err(502, "bad-gateway")
            if int(length) > RESPONSE_MAX:
                _warn("engine-answer-too-large")
                return _err(502, "bad-gateway")
            data = _read_exact(resp, conn, deadline, int(length))
        except socket.timeout:
            _warn("engine-timeout")
            return _err(504, "engine-timeout")
        except (_Truncated, OSError, http.client.HTTPException) as e:
            if late():                                  # 마감이 끊은 연결 — 엔진이 늦은 것
                _warn("engine-timeout")
                return _err(504, "engine-timeout")
            _warn("engine-cut" if isinstance(e, _Truncated) else type(e).__name__)
            return _err(503, "engine-unavailable")
        except ValueError:                              # 뜻밖의 답 모양 — ③ 500·스택으로 새지 않게
            _warn("engine-bad-answer")
            return _err(502, "bad-gateway")
    finally:
        timer.cancel()
        conn.close()
    return Outgoing(status, data)


# ── 화면 파일 ────────────────────────────────────────────────────────
def page_file(root: pathlib.Path, rest: str) -> Optional[pathlib.Path]:
    """/naver/ 아래 파일 — 정한 확장자 · 정한 글자만 · 폴더 밖(링크 포함)으로 못 나간다. 없으면 None."""
    if rest in ("", "index.html"):
        rest = "index.html"
    elif not isinstance(rest, str) or not _PAGE.fullmatch(rest):
        return None
    if pathlib.PurePosixPath(rest).suffix not in PAGE_TYPES:
        return None
    try:
        base = root.resolve(strict=True)
        p = (base / rest).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if base not in p.parents or not p.is_file():
        return None
    if p.suffix not in PAGE_TYPES:          # 폴더 안 링크가 다른 종류(.py·.env)를 가리키면 — 요청 이름만 보면 통과한다
        return None
    return p


def page_type(p: pathlib.Path) -> str:
    return PAGE_TYPES[p.suffix]
