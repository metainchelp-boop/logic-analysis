"""인증·암호화 — 비밀번호 해시(pbkdf2), JWT 토큰, 채널 키 암호화(Fernet)."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from passlib.context import CryptContext
from jose import jwt
from cryptography.fernet import Fernet

# --- 비밀번호 해시 (pbkdf2_sha256: 순수 파이썬, 추가 빌드 불필요) ---
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(p: str) -> str:
    return pwd_context.hash(p)


def verify_password(p: str, h: str) -> bool:
    return pwd_context.verify(p, h)


# --- JWT ---
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me-in-production")
JWT_ALG = "HS256"
TOKEN_HOURS = 12


def create_token(user_id: int, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode(
        {"sub": str(user_id), "role": role, "exp": exp}, JWT_SECRET, algorithm=JWT_ALG
    )


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])


# --- 채널 키 암호화 (엔벨로프 암호화의 1차 형태 — 평문 저장 금지 원칙) ---
_KEY_FILE = Path(os.environ.get("FERNET_KEY_FILE") or (Path(__file__).resolve().parent.parent / "secret.key"))


def _get_fernet() -> Fernet:
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_bytes()
    else:
        key = Fernet.generate_key()
        _KEY_FILE.write_bytes(key)
    return Fernet(key)


_fernet = _get_fernet()


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


def mask(value: str) -> str:
    """비밀값을 화면에 보여줄 때 마스킹."""
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 4 else "••••"
