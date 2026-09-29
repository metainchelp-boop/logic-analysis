"""인증·암호화 — 비밀번호 해시(pbkdf2), JWT 토큰, 채널 키 암호화(Fernet)."""
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from passlib.context import CryptContext
from jose import jwt
from cryptography.fernet import Fernet

from . import secret_policy

# --- 비밀번호 해시 (pbkdf2_sha256: 순수 파이썬, 추가 빌드 불필요) ---
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(p: str) -> str:
    return pwd_context.hash(p)


def verify_password(p: str, h: str) -> bool:
    return pwd_context.verify(p, h)


# --- 채널 키 암호화 (엔벨로프 암호화의 1차 형태 — 평문 저장 금지 원칙) ---
_KEY_FILE = Path(os.environ.get("FERNET_KEY_FILE") or (Path(__file__).resolve().parent.parent / "secret.key"))


def _create_key_once(path: Path) -> bytes:
    """처음 한 번만 — 워커 여럿이 동시에 떠도 먼저 만든 키 하나로 모인다(없을 때만 만들기 · 진 쪽은 이긴 키를 읽는다).
    예전처럼 워커마다 제 키를 쓰면 한 워커가 잠근 채널 키를 다른 워커가 못 푼다(S0)."""
    key = Fernet.generate_key()
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        for _ in range(50):             # 이긴 워커가 아직 쓰는 중일 수 있다
            got = path.read_bytes()
            if got.strip():
                return got
            time.sleep(0.02)
        return path.read_bytes()
    with os.fdopen(fd, "wb") as f:
        f.write(key)
        f.flush()
        os.fsync(f.fileno())
    return key


def _get_fernet() -> Fernet:
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_bytes()
    else:
        key = _create_key_once(_KEY_FILE)
    return Fernet(key)


_fernet = _get_fernet()


# --- JWT ---
# 서명 값(S0 · 대표 결정 2026-09-29) — 환경 JWT_SECRET 이 쓸 만하면 그 값, 약하거나 없으면 서버가 만든 값(파일).
# 알려진 기본값(please-set-… · dev-secret-…)으로는 절대 서명하지 않는다. 값은 찍지 않고 출처·사유만 남긴다.
# 파일 자리: JWT_SECRET_FILE → 없으면 암호화 키 파일 옆 jwt.key(운영 = /app/data/jwt.key · 영구 볼륨).
# 모두를 한 번에 다시 로그인시키려면: 이 파일을 지우고 다시 띄운다(환경 값을 쓰는 중이면 환경 값을 바꾼다).
JWT_SECRET_FILE = Path(os.environ.get("JWT_SECRET_FILE") or (_KEY_FILE.parent / "jwt.key"))
JWT_SECRET, JWT_SOURCE, JWT_REASON = secret_policy.resolve(
    os.environ.get("JWT_SECRET"), JWT_SECRET_FILE, derive_from=_KEY_FILE.read_bytes(),
    others=secret_policy.other_secrets(),
)
JWT_ALG = "HS256"
TOKEN_HOURS = 12
_REQUIRED = {"require_exp": True, "require_sub": True}


def create_token(user_id: int, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode(
        {"sub": str(user_id), "role": role, "exp": exp}, JWT_SECRET, algorithm=JWT_ALG
    )


def decode_token(token: str) -> dict:
    """만료(exp)·주인(sub) 이 없는 토큰은 받지 않는다(S0 — 예전엔 exp 없는 토큰이 영원히 통했다)."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG], options=dict(_REQUIRED))


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


def mask(value: str) -> str:
    """비밀값을 화면에 보여줄 때 마스킹."""
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 4 else "••••"
