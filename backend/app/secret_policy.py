"""S0 보안 준비 — 로그인 서명 값이 쓸 만한지 판정하고, 쓸 만하지 않으면 서버가 스스로 만든 강한 값을 쓴다.

지키는 것(대표 결정 2026-09-29 「서버가 강한 값을 스스로 만듦」)
- 알려진 기본값(docker-compose 의 옛 기본값 · 코드의 옛 기본값 · 문서 예시 ``xxx`` 등)으로는 **절대 서명하지 않는다.**
  환경 값이 약하거나 없으면 서버가 **이미 모든 워커가 함께 쓰는 암호화 키**(``secret.key`` · 서버가 처음 한 번 만든
  무작위 값 · 영구 볼륨)에서 서명 값을 뽑는다(HMAC · 되돌릴 수 없음).
  - 뽑는 길이 하나라 **워커 넷이 · 워커가 다시 떠도 · 컨테이너를 다시 띄워도** 늘 같은 값이다(파일을 따로 두면
    잠깐의 쓰기 실패나 파일 지우기만으로 워커마다 값이 갈려 로그인이 제멋대로 풀린다 — S0 검토).
  - 서명 값이 새어도 암호화 키는 거꾸로 못 구한다. 암호화 키 파일을 읽을 수 있는 사람은 원래 모든 것을 푼다.
- 사이트는 멈추지 않는다 — 값이 약해도 시작은 된다(옛 약한 값으로 서명된 토큰은 맞지 않게 되어 모두 한 번 다시 로그인).
- **모두를 한 번에 다시 로그인시키려면** 환경 ``JWT_SECRET`` 에 새 강한 값(32자 이상 무작위)을 넣고 다시 띄운다.
- 값은 **돌려주지도 찍지도 않는다.** 판정 결과는 짧은 사유 이름(``ok`` · ``missing`` · ``short`` · ``known-default`` ·
  ``reused`` · ``low-variety``)뿐이다.

표준 라이브러리만 쓴다(점검 도구·시험이 앱 없이도 부른다).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Iterable, Optional, Tuple

log = logging.getLogger("app.secret_policy")

MIN_LEN = 32            # 이보다 짧으면 「short」
MIN_DISTINCT = 12       # 서로 다른 글자가 이보다 적으면 「low-variety」(aaaa… · 1212… 같은 값)

# 알려진 기본값·예시값 — 이 값(대소문자·앞뒤 공백 무시)이거나 아래 조각을 품으면 「known-default」.
# 새 기본값·예시를 저장소 어딘가에 적으면 여기에도 적는다 — 시험이 compose·DEPLOY.md·run.sh·파이썬 파일에서
# ``JWT_SECRET=값`` 모양을 찾아 이 판정으로 거른다(쓸 만하다고 나오면 실패).
KNOWN_WEAK = (
    "please-set-a-strong-secret",
    "dev-secret-change-me-in-production",
    "change-me-in-production",
    "change-me",
    "changeme",
    "secret",
    "jwt-secret",
    "jwt_secret",
    "xxx",
    "s12-relay-test-only-not-a-secret",
)
WEAK_FRAGMENTS = ("please-set", "change-me", "changeme", "dev-secret", "not-a-secret", "example", "your-secret")

# 같은 컨테이너의 다른 비밀값 — 서명 값이 이것들 중 하나와 같으면 「reused」(한 값이 새면 둘 다 뚫린다)
OTHER_SECRET_NAMES = (
    "ANTHROPIC_API_KEY", "YOUTUBE_API_KEY", "MC_AD_API_TOKEN", "ERP_SYNC_API_KEY", "ERP_WEBHOOK_SECRET",
)

REASONS = ("ok", "missing", "short", "known-default", "reused", "low-variety")

JWT_LABEL = b"ad-dashboard/jwt-signing/v1"


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8", "surrogatepass"), b.encode("utf-8", "surrogatepass"))


def assess(value: Optional[str], others: Iterable[Optional[str]] = ()) -> str:
    """서명 값 판정 — 사유 이름 하나만 돌려준다(값은 어디에도 남기지 않는다)."""
    if not isinstance(value, str) or not value.strip():
        return "missing"
    v = value.strip()
    low = v.lower()
    if any(_eq(low, w) for w in KNOWN_WEAK) or any(f in low for f in WEAK_FRAGMENTS):
        return "known-default"
    if len(v) < MIN_LEN:
        return "short"
    if len(set(v)) < MIN_DISTINCT:
        return "low-variety"
    for o in others:
        if isinstance(o, str) and o.strip() and _eq(v, o.strip()):
            return "reused"
    return "ok"


def other_secrets(environ=None) -> Tuple[str, ...]:
    env = os.environ if environ is None else environ
    return tuple(env.get(n, "") for n in OTHER_SECRET_NAMES)


def derive(material: bytes, label: bytes) -> str:
    """서버가 가진 무작위 재료(암호화 키)에서 쓰임새마다 다른 값을 뽑는다 — 되돌릴 수 없음 · 64글자(256비트)."""
    if not material:
        raise ValueError("재료가 비었습니다")
    return hmac.new(material, label, hashlib.sha256).hexdigest()


def resolve(env_value: Optional[str], derive_from: bytes,
            others: Iterable[Optional[str]] = ()) -> Tuple[str, str, str]:
    """(서명 값, 출처, 사유). 출처 = env(환경 값이 쓸 만함) · derived(서버가 만든 값).
    사유 = 환경 값을 안 쓴 까닭(쓸 만하면 ``ok``). 값은 첫 칸에만 있고 로그에는 출처·사유만 남는다."""
    reason = assess(env_value, others)
    if reason == "ok":
        return env_value.strip(), "env", "ok"
    value = derive(derive_from, JWT_LABEL)
    log.warning("로그인 서명 값 — 환경 값을 쓰지 않음(사유: %s) · 서버가 만든 값을 씀", reason)
    return value, "derived", reason
