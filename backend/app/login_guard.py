"""S0 로그인 지킴 — 실패만 세는 제한 + 공개된 데모 비밀번호 잠금(대표 결정 2026-09-29).

실패만 센다
- 비밀번호 로그인(10분 창 · 창은 미끄러진다):
  - 한 계정 × 한 곳(공인 주소) 10번 — 남이 먼 곳에서 틀려도 **다른 곳의 그 사람은 막히지 않는다**(S0 검토 — 계정만으로
    세면 누구나 1분에 한 번씩 틀려 관리자를 영영 잠글 수 있었다).
  - 한 계정 전체 100번 — 여러 곳을 돌려 가며 한 계정을 노리는 것의 상한.
  - 한 곳 30번 — 한 곳이 여러 계정을 훑는 것의 상한.
  - 곳을 모를 때(nginx 머리가 없어 모두가 같은 내부 주소로 보임) = 한 계정 10번 · 한 계정 전체 100번만.
- 전산 SSO: 한 곳에서 **서로 다른** 토큰 120개가 ① 에 거절되면 그 곳을 막는다. 같은 토큰을 다시 누르면 새로 세지 않고
  ① 에 다시 묻지도 않는다(이미 거절된 토큰 = 바로 401) · 빈 토큰은 ① 을 부르지 않으니 세지 않는다 · ① 장애·이상한 답(502)도
  세지 않는다. 사무실 한 곳에서 전 직원이 어제 연 창의 낡은 토큰을 눌러도 막히지 않을 만큼 넉넉하게(① 토큰은 맞힐 수 없어
  이 상한은 ① 을 우리 쪽에서 두들기지 못하게 하는 것뿐이다).
- 맞게 들어오는 로그인·전산 「광고 센터」 버튼 진입은 세지 않는다.
- **먼저 자리를 잡고 확인한다** — 한 번에 몰아 보내도 상한을 넘지 못하게, 확인 전에 「실패 한 줄」을 한 거래
  (``BEGIN IMMEDIATE`` · 워커 넷이 한 줄로 선다) 안에서 세고 적는다. 맞으면 그 줄을 지우고, 틀리면 남긴다.
  예전 판은 세고 → 확인하고 → 적어서, 동시에 100번 보내면 57번이 확인까지 갔다(S0 검토 실측).
- 표 하나(login_failures)를 워커 넷이 같이 본다 · 한 시간 지난 줄은 지운다 · 표는 「없으면 만들기」로 만든다(워커 넷이
  동시에 떠도 겨루지 않는다). 비밀번호·토큰·이메일 원문은 남기지 않는다 — 이메일·토큰은 서버 키로 뽑은 HMAC 앞 32자.
- 「곳」 = 중계와 같은 규칙(``naver_relay.source_from`` · nginx 가 덮어쓰는 X-Real-IP → 없으면 연결 주소 · IPv6 /64) ·
  **공인 주소일 때만** 곳으로 센다(내부 · 루프백 · 통신사 공용 대역 100.64/10 등은 곳 없음).
- 표를 못 쓰면(잠김 5초) 들여보내지 않고 503 — 제한이 조용히 풀리지 않게.

공개된 데모 비밀번호 잠금
- 처음 설치 때 만든 데모 계정(seed.DEMO_PASSWORDS)이 아직 그 비밀번호 그대로면 비밀번호 로그인을 막는다(403).
- 단, 그 계정이 관리자이고 **쓸 수 있는 다른 관리자가 없으면** 막지 않고 경고만 남긴다(관리자 길이 끊기지 않게).
  「쓸 수 있는」 = 다른 관리자 중 데모 비밀번호 그대로인 데모 계정이 아닌 것(전산 SSO 로 들어오는 관리자 포함).
  막힌 데모 계정은 서버에서 ``python -m tools.set_password <이메일>`` 로 새 비밀번호를 줄 수 있다.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import database, naver_relay, seed, security

log = logging.getLogger("app.login_guard")

WINDOW = 600                 # 10분
ACCOUNT_SOURCE_MAX = 10      # 한 계정 × 한 곳(또는 곳 모름) 10분에 10번
ACCOUNT_MAX = 100            # 한 계정 전체 10분에 100번
SOURCE_MAX = 30              # 한 곳 10분에 30번
SSO_SOURCE_MAX = 120         # 한 곳 10분에 서로 다른 거절 토큰 120개
KEEP = 3600                  # 한 시간 지난 줄은 지운다
LOCK_WAIT = 5.0              # 표 잠금을 기다리는 최대 초

LIMITS = {"acct-src": ACCOUNT_SOURCE_MAX, "acct-local": ACCOUNT_SOURCE_MAX, "acct": ACCOUNT_MAX,
          "src": SOURCE_MAX, "sso-src": SSO_SOURCE_MAX}

BLOCKED_MSG = "로그인 실패가 너무 많습니다. 10분쯤 뒤에 다시 시도하시거나 전산 「광고 센터」 버튼으로 들어와 주세요."
BUSY_MSG = "지금 로그인 확인이 밀려 있습니다. 잠시 뒤 다시 시도해 주세요."
DEMO_MSG = ("처음 설치 때 공개된 비밀번호로는 로그인할 수 없습니다. 전산 「광고 센터」 버튼으로 들어오시거나, "
            "관리자에게 이 계정의 비밀번호를 바꿔 달라고 요청해 주세요.")

_BUCKET_LABEL = b"ad-dashboard/login-bucket/v1"


class Unavailable(Exception):
    """실패 표를 쓰지 못함 — 들여보내지 않는다(503)."""


# ── 로그(한 종류 1분에 한 줄 · 막힌 요청마다 쌓이지 않게) ─────────────
_note_lock = threading.Lock()
_notes: dict = {}


def note(kind: str, message: str) -> None:
    """종류마다 1분에 한 줄 + 그 사이 건수 — 막힌 요청이 몰려도 로그가 디스크를 채우지 않게(S0 검토)."""
    now = time.monotonic()
    with _note_lock:
        last, skipped = _notes.get(kind, (-1e9, 0))
        if now - last < 60.0:
            _notes[kind] = (last, skipped + 1)
            return
        if len(_notes) > 64:
            _notes.clear()
        _notes[kind] = (now, 0)
    log.warning("%s%s", message, f" (그 사이 {skipped}건 더)" if skipped else "")


# ── 묶음 이름(순수) ─────────────────────────────────────────────────
def _tag(value: str) -> str:
    return hmac.new(security.derived_secret(_BUCKET_LABEL).encode(), value.encode("utf-8", "surrogatepass"),
                    hashlib.sha256).hexdigest()[:32]


def account_key(email: Optional[str]) -> str:
    return _tag("acct:" + (email or "").strip().lower())


def token_tag(token: str) -> str:
    return _tag("sso:" + token)


def public_source(real_ip: Optional[str], peer: Optional[str]) -> Optional[str]:
    """중계와 같은 규칙으로 요청한 곳을 정하고, 공인 주소일 때만 돌려준다(내부·루프백·공용 대역·모양 틀림 = 없음)."""
    g = naver_relay.source_from(real_ip, peer)
    if g is None:
        return None
    try:
        a = ipaddress.ip_address(g)
    except ValueError:
        return None
    return g if a.is_global else None


def password_buckets(email: Optional[str], source: Optional[str]) -> List[str]:
    k = account_key(email)
    if source:
        return [f"acct-src:{k}:{source}", f"acct:{k}", f"src:{source}"]
    return [f"acct-local:{k}", f"acct:{k}"]


def sso_buckets(source: Optional[str]) -> List[str]:
    return ["sso-src:" + source] if source else []


def limit_of(bucket: str) -> int:
    return LIMITS[bucket.split(":", 1)[0]]


def retry_after(oldest_at: float, now: float) -> int:
    return max(1, int(math.ceil(oldest_at + WINDOW - now)))


# ── 표(표준 라이브러리 sqlite3 · 워커 넷이 같은 파일) ─────────────────
_DDL = (
    "CREATE TABLE IF NOT EXISTS login_failures ("
    "id INTEGER PRIMARY KEY, bucket TEXT NOT NULL, tag TEXT, at REAL NOT NULL, pending INTEGER NOT NULL DEFAULT 0)",
    "CREATE INDEX IF NOT EXISTS ix_login_failures_bucket_at ON login_failures(bucket, at)",
    "CREATE INDEX IF NOT EXISTS ix_login_failures_at ON login_failures(at)",
)
_ready = set()
_ready_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    path = database.DB_PATH
    try:
        c = sqlite3.connect(path, timeout=LOCK_WAIT, isolation_level=None)
        if path not in _ready:
            with _ready_lock:
                if path not in _ready:
                    for d in _DDL:
                        c.execute(d)
                    _ready.add(path)
        return c
    except sqlite3.Error as e:
        raise Unavailable(type(e).__name__) from e


@dataclass
class Ticket:
    ids: List[int] = field(default_factory=list)   # 먼저 적은 「실패 한 줄」들(맞으면 지운다)
    wait: Optional[int] = None                      # 막혔으면 기다릴 초
    known_rejected: bool = False                    # 이 곳에서 이미 거절된 SSO 토큰


def _blocked_wait(c, bucket: str, now: float, distinct_tags: bool) -> Optional[int]:
    lim = limit_of(bucket)
    since = now - WINDOW
    if distinct_tags:
        rows = c.execute("SELECT MAX(at) m FROM login_failures WHERE bucket=? AND at>? GROUP BY tag "
                         "ORDER BY m DESC LIMIT ?", (bucket, since, lim)).fetchall()
    else:
        rows = c.execute("SELECT at FROM login_failures WHERE bucket=? AND at>? ORDER BY at DESC LIMIT ?",
                         (bucket, since, lim)).fetchall()
    if len(rows) >= lim:
        # 상한 개수째로 오래된 실패가 창을 벗어나는 때까지
        return retry_after(rows[-1][0], now)
    return None


def reserve(buckets: List[str], tag: Optional[str] = None, now: Optional[float] = None) -> Ticket:
    """확인 전에 — 막혔는지 보고, 안 막혔으면 묶음마다 「실패 한 줄」을 먼저 적는다(한 거래 · 워커 넷이 한 줄로 선다).
    ``tag`` 가 있으면(SSO) 묶음 안에서 서로 다른 tag 만 세고, 같은 tag 가 이미 거절로 있으면 known_rejected."""
    now = time.time() if now is None else now
    t = Ticket()
    if not buckets:
        return t
    c = _connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        try:
            since = now - WINDOW
            if tag is not None:
                seen = c.execute(
                    "SELECT pending FROM login_failures WHERE bucket IN (%s) AND tag=? AND at>?"
                    % ",".join("?" * len(buckets)), (*buckets, tag, since)).fetchall()
                if any(p == 0 for (p,) in seen):
                    t.known_rejected = True
                    c.execute("COMMIT")
                    return t
                if seen:                       # 같은 토큰이 지금 확인 중 — 새로 세지 않는다
                    c.execute("COMMIT")
                    return t
            waits = [w for w in (_blocked_wait(c, b, now, tag is not None) for b in buckets) if w is not None]
            if waits:
                t.wait = max(waits)
                c.execute("COMMIT")
                return t
            for b in buckets:
                cur = c.execute("INSERT INTO login_failures(bucket, tag, at, pending) VALUES (?,?,?,1)", (b, tag, now))
                t.ids.append(cur.lastrowid)
            c.execute("DELETE FROM login_failures WHERE at < ?", (now - KEEP,))
            c.execute("COMMIT")
            return t
        except BaseException:
            c.execute("ROLLBACK")
            raise
    except sqlite3.Error as e:
        raise Unavailable(type(e).__name__) from e
    finally:
        c.close()


def settle(ticket: Ticket, failed: bool) -> None:
    """확인이 끝난 뒤 — 실패면 그 줄을 확정(pending 0), 아니면 지운다. 표를 못 쓰면 조용히 둔다(실패로 남는 쪽 = 보수적)."""
    if not ticket.ids:
        return
    try:
        c = _connect()
    except Unavailable:
        note("settle-unavailable", "로그인 실패 표를 정리하지 못함(나중 정리 · 실패로 남음)")
        return
    try:
        q = ",".join("?" * len(ticket.ids))
        if failed:
            c.execute(f"UPDATE login_failures SET pending=0 WHERE id IN ({q})", ticket.ids)
        else:
            c.execute(f"DELETE FROM login_failures WHERE id IN ({q})", ticket.ids)
    except sqlite3.Error:
        note("settle-unavailable", "로그인 실패 표를 정리하지 못함(나중 정리 · 실패로 남음)")
    finally:
        c.close()


def recent_count() -> int:
    """최근 10분 줄 수 — 점검 도구용."""
    c = _connect()
    try:
        return c.execute("SELECT COUNT(*) FROM login_failures WHERE at > ?", (time.time() - WINDOW,)).fetchone()[0]
    finally:
        c.close()


# ── 공개된 데모 비밀번호 ────────────────────────────────────────────
def is_published_demo(email: Optional[str], password: Optional[str]) -> bool:
    """이 이메일이 데모 계정이고, 넣은 비밀번호가 처음 공개된 그 비밀번호인가(같은 시간 비교)."""
    pw = seed.DEMO_PASSWORDS.get((email or "").strip().lower())
    if pw is None or not isinstance(password, str):
        return False
    return hmac.compare_digest(password.encode("utf-8", "surrogatepass"), pw.encode("utf-8"))


def is_any_published_demo(password: Optional[str]) -> bool:
    return any(is_published_demo(e, password) for e in seed.DEMO_PASSWORDS)


def still_on_demo_password(user) -> bool:
    pw = seed.DEMO_PASSWORDS.get((user.email or "").strip().lower())
    return pw is not None and security.verify_password(pw, user.password_hash)


def usable_other_admin(db, user) -> bool:
    """이 사람 말고 들어올 수 있는 관리자가 있는가 — 데모 비밀번호 그대로인 데모 계정은 셈에서 뺀다."""
    from . import models
    others = db.query(models.User).filter(models.User.role == "admin", models.User.id != user.id).all()
    return any(not still_on_demo_password(u) for u in others)


def demo_decision(db, user, password: str) -> str:
    """비밀번호 로그인이 맞은 뒤 — ``allow`` · ``block`` · ``warn``(관리자 길을 지키려 들여보냄)."""
    if not is_published_demo(user.email, password):
        return "allow"
    if user.role != "admin" or usable_other_admin(db, user):
        return "block"
    return "warn"


def demo_status(db) -> Tuple[int, int]:
    """(데모 비밀번호 그대로인 계정 수, 그중 관리자 수) — 점검 도구용 · 이메일은 돌려주지 않는다."""
    from . import models
    n = a = 0
    for email in seed.DEMO_PASSWORDS:
        u = db.query(models.User).filter(models.User.email == email).first()
        if u is not None and still_on_demo_password(u):
            n += 1
            a += u.role == "admin"
    return n, a
