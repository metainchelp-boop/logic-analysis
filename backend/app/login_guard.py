"""S0 로그인 지킴 — 실패만 세는 제한 + 공개된 데모 비밀번호 잠금(대표 결정 2026-09-29).

실패만 센다
- 비밀번호 로그인: 한 계정(이메일) 10분에 10번 · 한 곳(주소) 10분에 30번 실패하면 그 뒤 시도는 429(10분 창이 미끄러진다).
- 전산 SSO: 한 곳 10분에 30번 실패(① 이 토큰을 거절한 것만 · ① 이 안 받는 것(502)은 세지 않는다).
- 맞게 들어오는 로그인·전산 「광고 센터」 버튼 진입은 세지 않는다 — 평소 사용에는 걸리지 않는다.
- 주소는 nginx 가 덮어쓰는 X-Real-IP → 없으면 연결 주소(중계와 같은 규칙) · **공인 주소일 때만** 센다.
  nginx 머리가 없어 모두가 같은 내부 주소로 보이는 상황에서 30번이 「전 직원 합계」가 되어 모두가 막히는 것을 막는다.
- 표 하나(login_failures)를 워커 넷이 같이 본다. 비밀번호·토큰·이메일 원문은 남기지 않는다(이메일은 해시 앞 32자).

공개된 데모 비밀번호 잠금
- 처음 설치 때 만든 데모 계정(seed.DEMO_PASSWORDS)이 아직 그 비밀번호 그대로면 비밀번호 로그인을 막는다(403).
- 단, 그 계정이 관리자이고 **쓸 수 있는 다른 관리자가 없으면** 막지 않고 경고만 남긴다(관리자 길이 끊기지 않게).
  「쓸 수 있는」 = 다른 관리자 중 데모 비밀번호 그대로인 데모 계정이 아닌 것(전산 SSO 로 들어오는 관리자 포함).
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import math
import time
from typing import Iterable, List, Optional, Tuple

from . import models, naver_relay, seed, security

log = logging.getLogger("app.login_guard")

WINDOW = 600                 # 10분
ACCOUNT_MAX = 10             # 한 계정 10분에 10번 실패
SOURCE_MAX = 30              # 한 곳 10분에 30번 실패
SSO_SOURCE_MAX = 30          # 한 곳 10분에 SSO 30번 실패
KEEP = 3600                  # 한 시간 지난 줄은 지운다(창의 여섯 배)

LIMITS = {"acct": ACCOUNT_MAX, "src": SOURCE_MAX, "sso-src": SSO_SOURCE_MAX}

BLOCKED_MSG = "로그인 실패가 너무 많습니다. 10분쯤 뒤에 다시 시도하시거나 전산 「광고 센터」 버튼으로 들어와 주세요."
DEMO_MSG = ("처음 설치 때 공개된 비밀번호로는 로그인할 수 없습니다. 전산 「광고 센터」 버튼으로 들어오시거나, "
            "관리자에게 이 계정을 쓰지 않도록 정리해 달라고 요청해 주세요.")


# ── 묶음 이름(순수) ─────────────────────────────────────────────────
def account_bucket(email: Optional[str]) -> str:
    e = (email or "").strip().lower()
    return "acct:" + hashlib.sha256(e.encode("utf-8", "surrogatepass")).hexdigest()[:32]


def public_source(real_ip: Optional[str], peer: Optional[str]) -> Optional[str]:
    """중계와 같은 규칙으로 요청한 곳을 정하고, 공인 주소일 때만 돌려준다(내부·루프백·모양 틀림 = 없음)."""
    g = naver_relay.source_from(real_ip, peer)
    if g is None:
        return None
    try:
        a = ipaddress.ip_address(g)
    except ValueError:
        return None
    return g if a.is_global else None


def password_buckets(email: Optional[str], source: Optional[str]) -> List[str]:
    out = [account_bucket(email)]
    if source:
        out.append("src:" + source)
    return out


def sso_buckets(source: Optional[str]) -> List[str]:
    return ["sso-src:" + source] if source else []


def limit_of(bucket: str) -> int:
    return LIMITS[bucket.split(":", 1)[0]]


def retry_after(oldest_at: float, now: float) -> int:
    return max(1, int(math.ceil(oldest_at + WINDOW - now)))


# ── 표 읽고 쓰기 ────────────────────────────────────────────────────
def blocked(db, buckets: Iterable[str], now: Optional[float] = None) -> Optional[int]:
    """창 안 실패가 상한에 닿은 묶음이 있으면 기다릴 초, 없으면 None."""
    now = time.time() if now is None else now
    since = now - WINDOW
    wait = None
    for b in buckets:
        q = (db.query(models.LoginFailure.at)
             .filter(models.LoginFailure.bucket == b, models.LoginFailure.at > since)
             .order_by(models.LoginFailure.at.desc()))
        rows = q.limit(limit_of(b)).all()
        if len(rows) >= limit_of(b):
            # 상한 개수째로 오래된 실패가 창을 벗어나는 때까지 기다린다
            w = retry_after(rows[-1][0], now)
            wait = w if wait is None else max(wait, w)
    return wait


def record(db, buckets: Iterable[str], now: Optional[float] = None) -> None:
    now = time.time() if now is None else now
    bs = list(buckets)
    if not bs:
        return
    for b in bs:
        db.add(models.LoginFailure(bucket=b, at=now))
    db.query(models.LoginFailure).filter(models.LoginFailure.at < now - KEEP).delete(synchronize_session=False)
    db.commit()


# ── 공개된 데모 비밀번호 ────────────────────────────────────────────
def is_published_demo(email: Optional[str], password: Optional[str]) -> bool:
    """이 이메일이 데모 계정이고, 넣은 비밀번호가 처음 공개된 그 비밀번호인가(같은 시간 비교)."""
    pw = seed.DEMO_PASSWORDS.get((email or "").strip().lower())
    if pw is None or not isinstance(password, str):
        return False
    return hmac.compare_digest(password.encode("utf-8", "surrogatepass"), pw.encode("utf-8"))


def still_on_demo_password(user) -> bool:
    pw = seed.DEMO_PASSWORDS.get((user.email or "").strip().lower())
    return pw is not None and security.verify_password(pw, user.password_hash)


def usable_other_admin(db, user) -> bool:
    """이 사람 말고 들어올 수 있는 관리자가 있는가 — 데모 비밀번호 그대로인 데모 계정은 셈에서 뺀다."""
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
    n = a = 0
    for email in seed.DEMO_PASSWORDS:
        u = db.query(models.User).filter(models.User.email == email).first()
        if u is not None and still_on_demo_password(u):
            n += 1
            a += u.role == "admin"
    return n, a
