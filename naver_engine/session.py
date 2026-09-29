"""관제 화면 자체 토큰 — ③ 로그인 토큰 · ① 로그인 토큰과 섞지 않는다(설계 v1.4 §5 · §9 · M11 · S11).

- 대상(aud) = ``naver-auto`` · 주체(sub) = ① 직원 번호(대표 = 0) · 만든 시각 · 끝나는 시각(1시간) · 로그인 시각 · 좁힘 표시.
- 서명 = HMAC-SHA256(비밀값 ``NAVER_AUTO_TOKEN_SECRET``) · 대조는 ``hmac.compare_digest``. 비밀값이 없거나 32자 미만이면
  **API 를 시작하지 않는다**(폴백 없음 — ③ 의 「기본 비밀값」 사고를 되풀이하지 않는다).
- 1시간마다 갱신 — 갱신 때 조직 표에서 재직을 다시 본다(부르는 쪽 ``web``) · 로그인 뒤 12시간이 지나면 갱신하지 않는다
  (전산에서 다시 들어와야 한다). 퇴사·강등은 토큰과 상관없이 **요청마다** 범위를 다시 계산해 곧바로 걸린다.
- 토큰 안에는 번호와 시각만 — 이름 · 팀 · 범위 목록을 싣지 않는다(범위는 요청마다 조직 표로 다시 계산한다).
- 좁힘 표시(``narrowed``)는 로그인 때 ① my-profile 이 스냅숏보다 좁았다는 뜻 — 요청마다 ``scope.narrowed_scope_of`` 로
  좁힌 채 다시 계산한다. 표시를 떼려면 서명을 새로 만들어야 한다.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional

from .credentials import CredentialsMissing, Secret

ENV_TOKEN_SECRET = "NAVER_AUTO_TOKEN_SECRET"
SECRET_MIN_LENGTH = 32
SECRET_MAX_LENGTH = 512
AUDIENCE = "naver-auto"
VERSION = "v1"
TOKEN_TTL = timedelta(hours=1)
SESSION_MAX = timedelta(hours=12)
CLOCK_SLACK = timedelta(minutes=5)
TOKEN_MAX_LENGTH = 1024
_KEYS = frozenset({"aud", "sub", "iat", "exp", "lat", "nar"})
_B64 = re.compile(r"[A-Za-z0-9_-]+")
KST = timezone(timedelta(hours=9))

BAD_MALFORMED = "malformed"
BAD_SIGNATURE = "signature"
BAD_AUDIENCE = "audience"
BAD_EXPIRED = "expired"
BAD_NOT_YET = "not-yet"
BAD_SESSION_OVER = "session-over"   # 로그인 뒤 12시간 — 전산에서 다시 들어온다


class TokenInvalid(Exception):
    """토큰을 받지 않음 — ``code`` 만(토큰 글자는 싣지 않는다)."""

    def __init__(self, code: str) -> None:
        super().__init__(f"토큰을 받지 않습니다: {code}")
        self.code = code


def load_token_secret(env: Optional[Mapping[str, str]] = None) -> Secret:
    """토큰 비밀값 — 없거나 · 32~512자가 아니거나 · 쓸 수 없는 글자면 ``CredentialsMissing``(이름만 · 값 없음)."""
    src = os.environ if env is None else env
    raw = (src.get(ENV_TOKEN_SECRET) or "").strip()
    if not raw:
        raise CredentialsMissing(f"토큰 비밀값이 설정되지 않았습니다: {ENV_TOKEN_SECRET}")
    if not re.fullmatch(r"[\x21-\x7e]+", raw):
        raise CredentialsMissing(f"{ENV_TOKEN_SECRET} 에 쓸 수 없는 글자가 있습니다(빈칸·줄바꿈·한글 등)")
    if not SECRET_MIN_LENGTH <= len(raw) <= SECRET_MAX_LENGTH:
        raise CredentialsMissing(f"{ENV_TOKEN_SECRET} 길이가 {SECRET_MIN_LENGTH}~{SECRET_MAX_LENGTH}자가 아닙니다")
    return Secret(raw)


@dataclass(frozen=True)
class Claims:
    emp_idx: int = field(repr=False)      # 토큰의 sub = ① 직원 번호(대표 = 0) — 표시·로그에 번호가 새지 않게
    issued_at: datetime
    expires_at: datetime
    login_at: datetime
    narrowed: bool


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    if not _B64.fullmatch(s):
        raise TokenInvalid(BAD_MALFORMED)
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (binascii.Error, ValueError):
        raise TokenInvalid(BAD_MALFORMED) from None


def _epoch(t: datetime) -> int:
    if not isinstance(t, datetime) or t.tzinfo is None:
        raise ValueError("시각에는 시간대가 있어야 한다")
    return int(t.timestamp())


def _when(v) -> datetime:
    if isinstance(v, bool) or not isinstance(v, int) or not 0 < v < 2 ** 40:
        raise TokenInvalid(BAD_MALFORMED)
    return datetime.fromtimestamp(v, KST)


class TokenSigner:
    """자체 토큰을 만들고 검사한다. 비밀값은 ``Secret.mac`` 으로만 쓴다(값을 꺼내지 않는다)."""

    def __init__(self, secret: Secret) -> None:
        if not isinstance(secret, Secret):
            raise CredentialsMissing("토큰 비밀값은 Secret 이어야 합니다")
        self._secret = secret

    def __repr__(self) -> str:
        return "TokenSigner(****)"

    def _sign(self, body: str) -> str:
        return _b64(self._secret.mac((VERSION + "." + body).encode("ascii")))

    def issue(self, sub: int, now: datetime, *, login_at: Optional[datetime] = None, narrowed: bool = False) -> str:
        """새 토큰(1시간 · 로그인 뒤 12시간을 넘기지 않는다). ``login_at`` 이 없으면 지금이 로그인 시각."""
        if isinstance(sub, bool) or not isinstance(sub, int) or sub < 0:
            raise ValueError("sub 는 ① 직원 번호(0 이상 정수)여야 한다")
        if type(narrowed) is not bool:
            raise ValueError("narrowed 는 참/거짓이어야 한다")
        lat = now if login_at is None else login_at
        if _epoch(lat) > _epoch(now):
            raise ValueError("로그인 시각이 지금보다 늦다")
        end = min(_epoch(now) + int(TOKEN_TTL.total_seconds()), _epoch(lat) + int(SESSION_MAX.total_seconds()))
        if end <= _epoch(now):
            raise TokenInvalid(BAD_SESSION_OVER)
        payload = {"aud": AUDIENCE, "sub": sub, "iat": _epoch(now), "exp": end, "lat": _epoch(lat),
                   "nar": 1 if narrowed else 0}
        body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii"))
        return VERSION + "." + body + "." + self._sign(body)

    def verify(self, token, now: datetime) -> Claims:
        """서명 · 대상 · 시각을 모두 본다. 하나라도 틀리면 ``TokenInvalid``(코드만)."""
        if not isinstance(token, str) or not token or len(token) > TOKEN_MAX_LENGTH:
            raise TokenInvalid(BAD_MALFORMED)
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != VERSION:
            raise TokenInvalid(BAD_MALFORMED)
        body, sig = parts[1], parts[2]
        if not _B64.fullmatch(body) or not _B64.fullmatch(sig):   # 글자 모양을 먼저 본다(서명 계산 전에)
            raise TokenInvalid(BAD_MALFORMED)
        if not hmac.compare_digest(sig.encode("ascii"), self._sign(body).encode("ascii")):
            raise TokenInvalid(BAD_SIGNATURE)
        try:
            p = json.loads(_unb64(body).decode("ascii"))
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise TokenInvalid(BAD_MALFORMED) from None
        if not isinstance(p, dict) or set(p) != _KEYS:
            raise TokenInvalid(BAD_MALFORMED)
        if p["aud"] != AUDIENCE:
            raise TokenInvalid(BAD_AUDIENCE)
        sub = p["sub"]
        if isinstance(sub, bool) or not isinstance(sub, int) or sub < 0 or sub >= 2 ** 63:
            raise TokenInvalid(BAD_MALFORMED)
        if p["nar"] not in (0, 1) or isinstance(p["nar"], bool):
            raise TokenInvalid(BAD_MALFORMED)
        iat, exp, lat = _when(p["iat"]), _when(p["exp"]), _when(p["lat"])
        if not (lat <= iat < exp) or exp - iat > TOKEN_TTL or exp - lat > SESSION_MAX:
            raise TokenInvalid(BAD_MALFORMED)
        if iat > now + CLOCK_SLACK:
            raise TokenInvalid(BAD_NOT_YET)
        if now >= exp:
            raise TokenInvalid(BAD_EXPIRED)
        return Claims(sub, iat, exp, lat, p["nar"] == 1)

    def refresh(self, claims: Claims, now: datetime) -> str:
        """갱신 토큰 — 같은 사람 · 같은 로그인 시각 · 같은 좁힘. 로그인 뒤 12시간이 지났으면 ``session-over``.
        **재직 확인은 부르는 쪽이 조직 표로 먼저 한다**(범위 없음이면 갱신하지 않는다)."""
        if not isinstance(claims, Claims):
            raise TokenInvalid(BAD_MALFORMED)
        if now - claims.login_at >= SESSION_MAX:
            raise TokenInvalid(BAD_SESSION_OVER)
        return self.issue(claims.emp_idx, now, login_at=claims.login_at, narrowed=claims.narrowed)
