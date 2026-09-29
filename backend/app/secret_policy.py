"""S0 보안 준비 — 로그인 서명 비밀값이 쓸 만한지 판정하고, 쓸 만하지 않으면 서버가 만든 값을 파일에 두고 쓴다.

지키는 것(대표 결정 2026-09-29 「서버가 강한 값을 스스로 만듦」)
- 알려진 기본값(docker-compose 의 ``please-set-a-strong-secret`` · 코드의 ``dev-secret-…`` · 문서 예시 ``xxx`` 등)으로는
  **절대 서명하지 않는다.** 환경 값이 약하거나 없으면 서버가 강한 값을 한 번 만들어 파일에 두고 모든 워커가 같은 값을 쓴다.
- 사이트는 멈추지 않는다 — 값이 약해도 시작은 된다(대신 서버가 만든 값을 쓴다 · 옛 약한 값으로 서명된 토큰은
  맞지 않게 되어 모두 한 번 다시 로그인한다).
- 값은 **돌려주지도 찍지도 않는다.** 판정 결과는 짧은 사유 이름(``ok`` · ``missing`` · ``short`` · ``known-default`` ·
  ``reused`` · ``low-variety``)뿐이다.

표준 라이브러리만 쓴다(점검 도구·시험이 앱 없이도 부른다).
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets
import tempfile
from pathlib import Path
from typing import Iterable, Optional, Tuple

try:  # 리눅스·맥 — 워커 여럿이 같은 파일을 두고 겨루지 않게 잠근다
    import fcntl
except ImportError:  # pragma: no cover — 윈도우(운영 아님)
    fcntl = None

log = logging.getLogger("app.secret_policy")

MIN_LEN = 32            # 이보다 짧으면 「short」
MIN_DISTINCT = 12       # 서로 다른 글자가 이보다 적으면 「low-variety」(aaaa… · 1212… 같은 값)
GENERATED_BYTES = 48    # 서버가 만드는 값 — token_urlsafe(48) = 64글자

# 알려진 기본값·예시값 — 이 값(대소문자·앞뒤 공백 무시)이거나 아래 조각을 품으면 「known-default」.
# 새 기본값이 저장소 어딘가에 생기면 여기에도 적는다(시험이 compose·코드·문서의 기본값을 다시 읽어 대조한다).
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


def generate() -> str:
    return secrets.token_urlsafe(GENERATED_BYTES)


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, UnicodeDecodeError):
        return None


def _write_private(path: Path, value: str) -> None:
    """같은 폴더에 임시 파일(0600)을 쓰고 바꿔 끼운다 — 반쯤 쓰인 파일을 읽는 워커가 없다."""
    fd, tmp = tempfile.mkstemp(prefix=".jwt-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_or_create(path: Path) -> Tuple[str, bool]:
    """파일의 서명 값을 읽는다 — 없거나 쓸 만하지 않으면 강한 값을 만들어 둔다. (값, 새로 만들었나).
    워커 여럿이 동시에 불러도 한 값으로 모인다(옆 잠금 파일 · 잠금이 없는 곳은 「먼저 만든 것이 이긴다」)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is not None:
        lock = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            cur = _read(path)
            if cur is not None and assess(cur) == "ok":
                return cur, False
            new = generate()
            _write_private(path, new)
            return new, True
        finally:
            os.close(lock)          # 닫으면 잠금도 풀린다
    # 잠금이 없는 곳 — 새로 만들 때만 「없을 때만 만들기」로 겨루고, 진 쪽은 이긴 값을 읽는다
    cur = _read(path)
    if cur is not None and assess(cur) == "ok":
        return cur, False
    new = generate()
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        cur = _read(path)
        if cur is not None and assess(cur) == "ok":
            return cur, False
        _write_private(path, new)       # 망가진 파일 — 바꿔 끼운다
        return new, True
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(new)
    return new, True


def derive(material: bytes) -> str:
    """파일을 쓸 수 없을 때의 마지막 길 — 이미 모든 워커가 같이 쓰는 암호화 키에서 서명 값을 뽑는다(되돌릴 수 없는 뽑기).
    워커마다 제각각 값을 만들면 한 워커가 준 토큰을 다른 워커가 거절해 로그인이 제멋대로 풀린다 — 그것보다 낫다."""
    return hmac.new(material, b"ad-dashboard/jwt-signing/v1", "sha256").hexdigest() * 2


def resolve(env_value: Optional[str], file_path: Path, derive_from: Optional[bytes] = None,
            others: Iterable[Optional[str]] = ()) -> Tuple[str, str, str]:
    """(서명 값, 출처, 사유). 출처 = env(환경 값이 쓸 만함) · file(서버가 만든 파일) · derived(파일을 못 쓸 때).
    사유 = 환경 값을 안 쓴 까닭(쓸 만하면 ``ok``). 값은 첫 칸에만 있고 로그에는 출처·사유만 남는다."""
    reason = assess(env_value, others)
    if reason == "ok":
        return env_value.strip(), "env", "ok"
    try:
        value, created = load_or_create(Path(file_path))
        log.warning("로그인 서명 값 — 환경 값을 쓰지 않음(사유: %s) · 서버가 만든 값을 씀(%s)",
                    reason, "새로 만듦" if created else "파일")
        return value, "file", reason
    except OSError as e:
        if derive_from:
            log.error("로그인 서명 값 — 환경 값을 쓰지 않음(사유: %s) · 파일을 쓸 수 없어(%s) 암호화 키에서 뽑음",
                      reason, type(e).__name__)
            return derive(derive_from), "derived", reason
        raise
