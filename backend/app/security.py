"""인증·암호화 — 비밀번호 해시(pbkdf2), JWT 토큰, 채널 키 암호화(Fernet)."""
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from passlib.context import CryptContext
from jose import jwt
from cryptography.fernet import Fernet

from . import secret_policy

try:  # 리눅스·맥 — 워커 여럿이 같은 키 파일을 두고 겨루지 않게 잠근다
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

# --- 비밀번호 해시 (pbkdf2_sha256: 순수 파이썬, 추가 빌드 불필요) ---
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(p: str) -> str:
    return pwd_context.hash(p)


def verify_password(p: str, h: str) -> bool:
    return pwd_context.verify(p, h)


# --- 채널 키 암호화 (엔벨로프 암호화의 1차 형태 — 평문 저장 금지 원칙) ---
_KEY_FILE = Path(os.environ.get("FERNET_KEY_FILE") or (Path(__file__).resolve().parent.parent / "secret.key"))


def _read_key(path: Path):
    """있으면 그 바이트 · 없거나 비었으면 None."""
    try:
        b = path.read_bytes()
    except FileNotFoundError:
        return None
    return b if b.strip() else None


def _create_key_once(path: Path) -> bytes:
    """처음 한 번만 — 워커 여럿이 동시에 떠도 먼저 만든 키 하나로 모인다(옆 잠금 파일 · S0).
    예전엔 워커마다 제 키를 만들어 한 워커가 잠근 채널 키를 다른 워커가 못 풀었다. 빈 파일(만들다 멈춘 흔적)은 새로
    채운다 — 빈 키로는 아무것도 잠근 적이 없다. **비어 있지 않은 파일은 절대 바꾸지 않는다.**"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:  # pragma: no cover — 잠금이 없는 곳(윈도우) · 없을 때만 만들기
        key = Fernet.generate_key()
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            for _ in range(50):
                got = _read_key(path)
                if got is not None:
                    return got
                time.sleep(0.02)
            raise
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        return key
    lock = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        got = _read_key(path)
        if got is not None:
            return got
        key = Fernet.generate_key()
        fd, tmp = tempfile.mkstemp(prefix=".key-", dir=str(path.parent))
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(key)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return key
    finally:
        os.close(lock)          # 닫으면 잠금도 풀린다


def _load_key() -> bytes:
    key = _read_key(_KEY_FILE)      # 있는 키를 읽는 길 — 운영은 이 길(그대로)
    if key is None:
        key = _create_key_once(_KEY_FILE)
    return key


def _get_fernet() -> Fernet:
    return Fernet(_load_key())


_KEY_MATERIAL = _load_key()
_fernet = Fernet(_KEY_MATERIAL)


def derived_secret(label: bytes) -> str:
    """서버 키에서 쓰임새마다 다른 값을 뽑는다(되돌릴 수 없음) — 로그인 서명 · 실패 묶음 이름 등."""
    return secret_policy.derive(_KEY_MATERIAL, label)


# --- JWT ---
# 서명 값(S0 · 대표 결정 2026-09-29) — 환경 JWT_SECRET 이 쓸 만하면 그 값, 약하거나 없으면 서버가 만든 값
# (암호화 키에서 뽑음 · 워커 넷이 늘 같은 값). 알려진 기본값(please-set-… · dev-secret-…)으로는 절대 서명하지 않는다.
# 값은 찍지 않고 출처·사유만 남긴다. 모두를 한 번에 다시 로그인시키려면 환경 JWT_SECRET 에 새 강한 값을 넣고 다시 띄운다.
JWT_SECRET, JWT_SOURCE, JWT_REASON = secret_policy.resolve(
    os.environ.get("JWT_SECRET"), _KEY_MATERIAL, others=secret_policy.other_secrets(),
)
JWT_ALG = "HS256"
JWT_AUD = "ad-dashboard"        # 이 앱이 준 토큰만 — 다른 앱이 같은 서명 값을 써도 그 토큰은 받지 않는다(S0 검토)
TOKEN_HOURS = 12
_REQUIRED = {"require_exp": True, "require_sub": True, "require_aud": True}


def create_token(user_id: int, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode(
        {"sub": str(user_id), "role": role, "exp": exp, "aud": JWT_AUD}, JWT_SECRET, algorithm=JWT_ALG
    )


def decode_token(token: str) -> dict:
    """만료(exp)·주인(sub)·받는 곳(aud) 이 없는 토큰은 받지 않는다(S0 — 예전엔 exp 없는 토큰이 영원히 통했다)."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG], audience=JWT_AUD, options=dict(_REQUIRED))


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


def mask(value: str) -> str:
    """비밀값을 화면에 보여줄 때 마스킹."""
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 4 else "••••"
