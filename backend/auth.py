"""
FastAPI Authentication Module for Logic Analysis Tool (로직분석)
JWT-based authentication with SQLite database, bcrypt hashing, and role-based access control.
"""

import os
import time
import sqlite3
import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from enum import Enum

from fastapi import APIRouter, HTTPException, Request, Depends
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field

# ============================================================================
# Configuration & Setup
# ============================================================================

logger = logging.getLogger(__name__)

# ============================================================================
# 로그인 레이트 리밋 (무차별 대입 방지) — 인메모리(워커당), (IP+username) 단위
#   한도는 넉넉히: 사무실 공유 IP에서도 정상 사용자는 절대 안 걸리도록 username별 분리
# ============================================================================
_login_attempts = defaultdict(list)
_login_rate_lock = threading.Lock()
LOGIN_RATE_LIMIT = 20       # 최대 시도 횟수
LOGIN_RATE_WINDOW = 300     # 윈도우(초) — 5분

def _login_rate_ok(key: str) -> bool:
    """(IP+username)당 5분 내 20회 초과 시 False. 스레드풀 실행 대비 락 보호."""
    now = time.time()
    cutoff = now - LOGIN_RATE_WINDOW
    with _login_rate_lock:
        bucket = [t for t in _login_attempts.get(key, []) if t > cutoff]
        if len(bucket) >= LOGIN_RATE_LIMIT:
            _login_attempts[key] = bucket
            return False
        bucket.append(now)
        _login_attempts[key] = bucket
        # 메모리 누적 방지: 항목이 많아지면 만료된 키 정리
        if len(_login_attempts) > 5000:
            for k in [k for k, v in list(_login_attempts.items()) if not v or v[-1] < cutoff]:
                _login_attempts.pop(k, None)
        return True

# Database configuration
DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")

# JWT configuration
_secret_file = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), ".jwt_secret")

def _get_or_create_secret():
    """파일 기반 JWT 시크릿: 최초 실행 시 랜덤 생성 후 저장, 이후 재사용"""
    # 1순위: 환경변수
    env_secret = os.getenv("JWT_SECRET_KEY")
    if env_secret:
        return env_secret
    # 2순위: 파일에서 로드 (이전에 생성된 랜덤 시크릿)
    try:
        if os.path.exists(_secret_file):
            with open(_secret_file, "r") as f:
                secret = f.read().strip()
                if len(secret) >= 32:
                    return secret
    except Exception:
        pass
    # 3순위: 새로 생성 후 저장
    import secrets as _secrets
    new_secret = _secrets.token_hex(32)
    try:
        with open(_secret_file, "w") as f:
            f.write(new_secret)
        os.chmod(_secret_file, 0o600)
        logger.info("JWT 시크릿 자동 생성 완료 (.jwt_secret)")
    except Exception as e:
        logger.warning(f"JWT 시크릿 파일 저장 실패 (메모리에서만 사용): {e}")
    return new_secret

SECRET_KEY = _get_or_create_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# 전산(ERP) SSO — 로직분석이 전산 '내 정보' API로 토큰을 검증(별도 공유시크릿 불필요).
#   전산 로그인 토큰(localStorage 'token')을 그대로 받아 전산 my-profile 에 질의 → 사용자 식별.
SSO_SHARED_SECRET = os.getenv("SSO_SHARED_SECRET", "")  # (구 방식 호환용, 현재 미사용)
# 2026-07-09 전산 BE 서버 이전(Cafe24 → 전용서버 api.metainc.co.kr). 옛 metainc01.cafe24.com 은 중지됨.
#   env ERP_BASE_URL 로 언제든 오버라이드 가능(서버 .env). SSO 핸들러가 http/https 둘 다 시도.
ERP_BASE_URL = os.getenv("ERP_BASE_URL", "http://api.metainc.co.kr")
ERP_MY_PROFILE_PATH = os.getenv("ERP_MY_PROFILE_PATH", "/api/employee-management/my-profile")

# Password hashing configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Role enumeration
class UserRole(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    VIEWER = "viewer"


# ============================================================================
# Pydantic Models
# ============================================================================

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6)


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=6)
    name: str = Field(default="", max_length=100)
    role: UserRole = Field(default=UserRole.VIEWER)


class UpdateUserRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    role: Optional[UserRole] = None
    is_active: Optional[int] = None


class UserResponse(BaseModel):
    id: int
    username: str
    name: str
    role: str
    is_active: int
    created_at: str

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    user: Optional[UserResponse] = None
    message: Optional[str] = None


class TokenData(BaseModel):
    user_id: Optional[int] = None


class MessageResponse(BaseModel):
    success: bool
    message: str


# ============================================================================
# Database Initialization
# ============================================================================

def _get_db_connection():
    """Get SQLite database connection with WAL mode and Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")  # 쓰기 잠금 시 즉시 실패 대신 최대 30초 대기
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db():
    """Initialize authentication database. Create users table and insert default admin."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()

        # Create users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT DEFAULT '',
                role TEXT DEFAULT 'viewer',
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)

        # Insert default admin if not exists (INSERT OR IGNORE로 워커 동시 실행 시 충돌 방지)
        cursor.execute("SELECT id FROM users WHERE username = ?", ("yoosub92",))
        if cursor.fetchone() is None:
            default_password = os.getenv("DEFAULT_ADMIN_PASSWORD", "")
            if not default_password:
                import secrets as _pw_secrets
                default_password = _pw_secrets.token_urlsafe(12)
                logger.warning(f"⚠️ DEFAULT_ADMIN_PASSWORD 미설정 — 임시 비밀번호 생성됨: {default_password}")
                logger.warning("⚠️ 로그인 후 반드시 비밀번호를 변경하세요!")
            password_hash = hash_password(default_password)
            cursor.execute(
                """
                INSERT OR IGNORE INTO users (username, password_hash, name, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "yoosub92",
                    password_hash,
                    "관리자",
                    UserRole.ADMIN,
                    1,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            logger.info("Default admin user created successfully")

        # 로그인 이력 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS login_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                login_at TEXT DEFAULT (datetime('now','localtime')),
                ip_address TEXT DEFAULT ''
            )
        """)
        # 로그인 이력 조회 인덱스 (관리자 화면 GROUP BY user_id / 최근순)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_user ON login_logs(user_id, login_at DESC)")

        conn.commit()
        conn.close()
        logger.info("Authentication database initialized successfully")

    except Exception as e:
        logger.error(f"Failed to initialize authentication database: {str(e)}")
        raise


# ============================================================================
# Password Hashing & Token Management
# ============================================================================

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(password, password_hash)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        logger.debug(f"Token decode failed: {str(e)}")
        return None


# ============================================================================
# User Database Operations
# ============================================================================

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Fetch user by ID from database."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, name, role, is_active, created_at FROM users WHERE id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None
    except Exception as e:
        logger.error(f"Failed to fetch user by ID: {str(e)}")
        return None


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Fetch user by username from database."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, name, role, is_active, created_at, password_hash FROM users WHERE username = ?",
            (username,),
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None
    except Exception as e:
        logger.error(f"Failed to fetch user by username: {str(e)}")
        return None


def get_all_users() -> List[Dict[str, Any]]:
    """Fetch all users from database."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, name, role, is_active, created_at FROM users ORDER BY created_at DESC"
        )
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch all users: {str(e)}")
        return []


def create_user(username: str, password: str, name: str = "", role: str = "viewer") -> Optional[Dict[str, Any]]:
    """Create new user in database."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()

        password_hash = hash_password(password)
        now = datetime.now().isoformat()

        cursor.execute(
            """
            INSERT INTO users (username, password_hash, name, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (username, password_hash, name, role, 1, now, now),
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()

        return get_user_by_id(user_id)
    except sqlite3.IntegrityError:
        logger.warning(f"Username already exists: {username}")
        return None
    except Exception as e:
        logger.error(f"Failed to create user: {str(e)}")
        return None


def update_user(user_id: int, **kwargs) -> Optional[Dict[str, Any]]:
    """Update user in database."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()

        # Build update query dynamically (화이트리스트 검증)
        allowed_fields = {"name", "role", "is_active"}
        update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields and v is not None}

        if not update_fields:
            conn.close()
            return get_user_by_id(user_id)

        update_fields["updated_at"] = datetime.now().isoformat()

        # 안전: 키 이름이 화이트리스트 + "updated_at"만 허용
        safe_keys = allowed_fields | {"updated_at"}
        for k in update_fields.keys():
            if k not in safe_keys:
                raise ValueError(f"허용되지 않은 필드: {k}")

        set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
        values = list(update_fields.values()) + [user_id]

        cursor.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
        conn.commit()
        conn.close()

        return get_user_by_id(user_id)
    except Exception as e:
        logger.error(f"Failed to update user: {str(e)}")
        return None


def delete_user(user_id: int) -> bool:
    """Delete user from database."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()

        return True
    except Exception as e:
        logger.error(f"Failed to delete user: {str(e)}")
        return False


def update_user_password(user_id: int, new_password: str) -> bool:
    """Update user password in database."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()

        password_hash = hash_password(new_password)
        now = datetime.now().isoformat()

        cursor.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (password_hash, now, user_id),
        )
        conn.commit()
        conn.close()

        return True
    except Exception as e:
        logger.error(f"Failed to update user password: {str(e)}")
        return False


# ============================================================================
# Dependency Functions
# ============================================================================

async def get_current_user(request: Request) -> Dict[str, Any]:
    """Extract and validate JWT token from Authorization header or cookie."""
    token = None

    # Try to get token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    # Fallback to cookie
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=401,
            detail="인증이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Decode token
    payload = decode_token(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(
            status_code=401,
            detail="유효하지 않은 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("user_id")
    user = get_user_by_id(user_id)

    if not user or not user.get("is_active"):
        raise HTTPException(
            status_code=401,
            detail="사용자를 찾을 수 없거나 비활성화되었습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_role(*roles):
    """FastAPI Depends that checks if current user has required role.
    superadmin/admin은 모든 권한을 포함합니다.
    roles는 문자열 또는 리스트 모두 허용."""

    # roles가 리스트 하나로 전달된 경우 평탄화
    flat_roles = []
    for r in roles:
        if isinstance(r, (list, tuple)):
            flat_roles.extend(r)
        else:
            flat_roles.append(r)

    async def role_checker(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        user_role = current_user.get("role", "")
        # admin/superadmin은 모든 권한 포함
        if user_role in (UserRole.ADMIN, "superadmin"):
            return current_user
        if user_role not in flat_roles:
            raise HTTPException(
                status_code=403,
                detail="접근 권한이 없습니다.",
            )
        return current_user

    return role_checker


def require_register_permission():
    """업체 '등록' 전용 권한 — 관리팀 매니저 + 최고관리자(superadmin)만 허용.
    require_role과 달리 일반 admin/viewer는 등록 불가(관리부서 매니저로 제한).
    단 superadmin(최고관리자)은 절대권한이므로 허용."""
    async def _checker(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if current_user.get("role") not in ("manager", "superadmin"):
            raise HTTPException(status_code=403, detail="업체 등록은 관리팀 매니저만 가능합니다.")
        return current_user
    return _checker


# ============================================================================
# API Router
# ============================================================================

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, request_obj: Request) -> LoginResponse:
    """
    User login endpoint.
    Returns JWT token and user information.
    """
    try:
        # 무차별 대입 방지: (IP+username)당 5분 20회 초과 시 차단
        try:
            _ip = request_obj.client.host if (request_obj and request_obj.client) else ''
        except Exception:
            _ip = ''
        if not _login_rate_ok(f"{_ip}|{request.username}"):
            logger.warning(f"로그인 시도 제한 초과: ip={_ip} user={request.username}")
            raise HTTPException(status_code=429, detail="로그인 시도가 너무 많습니다. 잠시 후 다시 시도해주세요.")

        user = get_user_by_username(request.username)

        if not user or not verify_password(request.password, user.get("password_hash", "")):
            logger.warning(f"Failed login attempt for username: {request.username}")
            raise HTTPException(
                status_code=401,
                detail="사용자명 또는 비밀번호가 잘못되었습니다.",
            )

        if not user.get("is_active"):
            raise HTTPException(
                status_code=403,
                detail="비활성화된 계정입니다.",
            )

        # Create access token
        token = create_access_token(data={"user_id": user["id"]})

        user_response = UserResponse(
            id=user["id"],
            username=user["username"],
            name=user["name"],
            role=user["role"],
            is_active=user["is_active"],
            created_at=user["created_at"],
        )

        # 로그인 이력 저장
        try:
            ip = request_obj.client.host if hasattr(request_obj, 'client') and request_obj.client else ''
        except Exception:
            ip = ''
        try:
            log_conn = _get_db_connection()
            log_conn.execute(
                "INSERT INTO login_logs (user_id, username, login_at, ip_address) VALUES (?, ?, ?, ?)",
                (user["id"], user["username"], datetime.now().isoformat(), ip)
            )
            log_conn.commit()
            log_conn.close()
        except Exception as log_err:
            logger.warning(f"로그인 이력 저장 실패: {log_err}")

        logger.info(f"User logged in: {user['username']}")

        return LoginResponse(success=True, token=token, user=user_response)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login failed: {str(e)}")
        raise HTTPException(status_code=500, detail="로그인 처리 중 오류가 발생했습니다.")


class SSORequest(BaseModel):
    token: str


@router.post("/sso", response_model=LoginResponse)
def sso_login(request: SSORequest, request_obj: Request) -> LoginResponse:
    """전산(ERP) SSO 자동 로그인.
    전산이 공유 시크릿(SSO_SHARED_SECRET)으로 서명한 단기 토큰을 검증 →
    매핑되는 로직분석 사용자 자동 로그인(없으면 viewer 역할로 자동 가입)."""
    # 전산 로그인 토큰을 전산 '내 정보' API로 검증 → 사용자 식별(별도 공유시크릿 불필요).
    # URL 전달 과정에서 붙을 수 있는 앞뒤 공백·후행 슬래시 정리(토큰 자체엔 없는 문자)
    _tok = (request.token or "").strip().strip("/").strip()
    if not _tok:
        raise HTTPException(status_code=401, detail="SSO 토큰이 없습니다.")
    _bearer = _tok if _tok.lower().startswith("bearer ") else ("Bearer " + _tok)
    import requests as _rq
    # 전산 API 도달성 견고화: 설정값 + http/https 두 스킴 모두 시도(연결오류 시 다음 후보로)
    _base = ERP_BASE_URL.rstrip("/")
    _candidates = [_base]
    if _base.startswith("http://"):
        _candidates.append("https://" + _base[len("http://"):])
    elif _base.startswith("https://"):
        _candidates.append("http://" + _base[len("https://"):])
    _resp = None
    _last_err = None
    for _cand in _candidates:
        try:
            _resp = _rq.get(
                _cand + ERP_MY_PROFILE_PATH,
                headers={"Authorization": _bearer},
                timeout=8,
            )
            break  # 응답을 받으면(코드 무관) 연결 성공 → 사용
        except Exception as _e:
            _last_err = _e
            continue
    if _resp is None:
        logger.error(f"SSO 전산 검증 연결 실패: {_last_err}")
        raise HTTPException(status_code=502, detail="전산 인증 서버에 연결할 수 없습니다.")
    if _resp.status_code != 200:
        raise HTTPException(status_code=401, detail="전산 로그인 정보가 유효하지 않습니다. 전산에 먼저 로그인해주세요.")
    try:
        _result = (_resp.json() or {}).get("result") or {}
    except Exception:
        _result = {}
    sub = str(_result.get("id") or "").strip()
    if not sub or len(sub) > 100:
        raise HTTPException(status_code=401, detail="전산 사용자 식별에 실패했습니다.")
    name = (str(_result.get("name") or sub)).strip()[:100]
    username = sub  # 전산 로그인ID 를 로직분석 username 으로 사용

    # 전산 팀/권한으로 로직분석 권한 자동 결정: 관리팀 = manager, 그 외 = viewer.
    # 매칭 키워드는 env(SSO_MANAGER_TEAMS, 콤마구분)로 조정 가능. 기본 "관리팀".
    _mgr_keywords = [k.strip() for k in os.getenv("SSO_MANAGER_TEAMS", "관리팀").split(",") if k.strip()]
    _team_strings = []
    try:
        _auth = _result.get("authority") or {}
        if isinstance(_auth, dict) and _auth.get("name"):
            _team_strings.append(str(_auth.get("name")))
        for _t in (_result.get("teamList") or []):
            if isinstance(_t, dict):
                for _v in _t.values():
                    if isinstance(_v, str):
                        _team_strings.append(_v)
            elif isinstance(_t, str):
                _team_strings.append(_t)
    except Exception:
        pass
    _is_mgr_team = any(any(kw in s for kw in _mgr_keywords) for s in _team_strings)
    sso_role = "manager" if _is_mgr_team else "viewer"
    try:
        logger.info(f"SSO 권한판별: {username} teams={_team_strings} → {sso_role}")
    except Exception:
        pass

    try:
        user = get_user_by_username(username)
        if not user:
            import secrets as _secrets
            create_user(username, _secrets.token_hex(16), name=name, role=sso_role)
            user = get_user_by_username(username)  # 생성 후 재조회(일관된 dict)
            if not user:
                raise HTTPException(status_code=500, detail="사용자 자동 생성에 실패했습니다.")
            logger.info(f"SSO 자동 가입: {username} (role={sso_role})")
        else:
            # 기존 계정: 팀 기준 권한으로 동기화 — 단 admin/superadmin 은 절대 강등하지 않음
            _cur_role = str(user.get("role") or "")
            if _cur_role not in ("admin", "superadmin") and _cur_role != sso_role:
                update_user(user["id"], role=sso_role)
                user = get_user_by_username(username) or user
                logger.info(f"SSO 권한 동기화: {username} {_cur_role} → {sso_role}")
        if not user.get("is_active", True):
            raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")

        token = create_access_token(data={"user_id": user["id"]})
        user_response = UserResponse(
            id=user["id"],
            username=user["username"],
            name=user.get("name", ""),
            role=user["role"],
            is_active=user["is_active"],
            created_at=user["created_at"],
        )
        try:
            ip = request_obj.client.host if hasattr(request_obj, 'client') and request_obj.client else ''
        except Exception:
            ip = ''
        try:
            log_conn = _get_db_connection()
            log_conn.execute(
                "INSERT INTO login_logs (user_id, username, login_at, ip_address) VALUES (?, ?, ?, ?)",
                (user["id"], user["username"], datetime.now().isoformat(), 'SSO:' + ip)
            )
            log_conn.commit()
            log_conn.close()
        except Exception:
            pass
        logger.info(f"SSO 로그인: {username}")
        return LoginResponse(success=True, token=token, user=user_response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SSO 로그인 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="SSO 처리 중 오류가 발생했습니다.")


@router.get("/me", response_model=UserResponse)
def get_current_user_info(current_user: Dict[str, Any] = Depends(get_current_user)) -> UserResponse:
    """Get current authenticated user information."""
    return UserResponse(
        id=current_user["id"],
        username=current_user["username"],
        name=current_user["name"],
        role=current_user["role"],
        is_active=current_user["is_active"],
        created_at=current_user["created_at"],
    )


@router.post("/logout", response_model=MessageResponse)
def logout(current_user: Dict[str, Any] = Depends(get_current_user)) -> MessageResponse:
    """Logout endpoint (client-side token removal)."""
    logger.info(f"User logged out: {current_user['username']}")
    return MessageResponse(success=True, message="로그아웃되었습니다.")


@router.put("/change-password", response_model=MessageResponse)
def change_password(
    request: ChangePasswordRequest, current_user: Dict[str, Any] = Depends(get_current_user)
) -> MessageResponse:
    """Change current user's password."""
    try:
        user = get_user_by_username(current_user["username"])

        # Verify current password
        if not user or not verify_password(request.current_password, user.get("password_hash", "")):
            raise HTTPException(
                status_code=401,
                detail="현재 비밀번호가 잘못되었습니다.",
            )

        # Update password
        if update_user_password(current_user["id"], request.new_password):
            logger.info(f"Password changed for user: {current_user['username']}")
            return MessageResponse(success=True, message="비밀번호가 변경되었습니다.")
        else:
            raise HTTPException(status_code=500, detail="비밀번호 변경 중 오류가 발생했습니다.")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to change password: {str(e)}")
        raise HTTPException(status_code=500, detail="비밀번호 변경 중 오류가 발생했습니다.")


# ============================================================================
# User Management Endpoints (Admin Only)
# ============================================================================

@router.get("/users", response_model=List[UserResponse])
def list_users(current_user: Dict[str, Any] = Depends(require_role(UserRole.ADMIN))) -> List[UserResponse]:
    """List all users (admin only)."""
    users = get_all_users()
    return [
        UserResponse(
            id=user["id"],
            username=user["username"],
            name=user["name"],
            role=user["role"],
            is_active=user["is_active"],
            created_at=user["created_at"],
        )
        for user in users
    ]


@router.post("/users", response_model=UserResponse)
def create_new_user(
    request: CreateUserRequest, current_user: Dict[str, Any] = Depends(require_role(UserRole.ADMIN))
) -> UserResponse:
    """Create new user (admin only)."""
    try:
        user = create_user(
            username=request.username, password=request.password, name=request.name, role=request.role
        )

        if not user:
            raise HTTPException(
                status_code=400,
                detail="사용자 생성에 실패했습니다. 사용자명이 이미 존재할 수 있습니다.",
            )

        logger.info(f"User created by admin {current_user['username']}: {request.username}")

        return UserResponse(
            id=user["id"],
            username=user["username"],
            name=user["name"],
            role=user["role"],
            is_active=user["is_active"],
            created_at=user["created_at"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create user: {str(e)}")
        raise HTTPException(status_code=500, detail="사용자 생성 중 오류가 발생했습니다.")


@router.put("/users/{user_id}", response_model=UserResponse)
def update_existing_user(
    user_id: int,
    request: UpdateUserRequest,
    current_user: Dict[str, Any] = Depends(require_role(UserRole.ADMIN)),
) -> UserResponse:
    """Update user (admin only)."""
    try:
        user = get_user_by_id(user_id)

        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        # admin이 자기 자신의 role을 변경하는 것 방지
        if user_id == current_user["id"] and request.role and request.role != current_user.get("role"):
            raise HTTPException(status_code=400, detail="자신의 권한은 변경할 수 없습니다.")

        updated_user = update_user(
            user_id, name=request.name, role=request.role, is_active=request.is_active
        )

        if not updated_user:
            raise HTTPException(status_code=500, detail="사용자 업데이트 중 오류가 발생했습니다.")

        logger.info(f"User updated by admin {current_user['username']}: {user['username']}")

        return UserResponse(
            id=updated_user["id"],
            username=updated_user["username"],
            name=updated_user["name"],
            role=updated_user["role"],
            is_active=updated_user["is_active"],
            created_at=updated_user["created_at"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user: {str(e)}")
        raise HTTPException(status_code=500, detail="사용자 업데이트 중 오류가 발생했습니다.")


@router.delete("/users/{user_id}", response_model=MessageResponse)
def delete_existing_user(
    user_id: int, current_user: Dict[str, Any] = Depends(require_role(UserRole.ADMIN))
) -> MessageResponse:
    """Delete user (admin only, cannot delete self)."""
    try:
        if user_id == current_user["id"]:
            raise HTTPException(
                status_code=400,
                detail="자신의 계정을 삭제할 수 없습니다.",
            )

        user = get_user_by_id(user_id)

        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        # 삭제 전: 해당 직원의 업체/추적상품을 관리자(현재 유저)에게 재배정
        try:
            reassign_conn = _get_db_connection()
            admin_id = current_user["id"]
            reassign_conn.execute(
                "UPDATE clients SET created_by = ? WHERE created_by = ?",
                (admin_id, user_id)
            )
            reassign_conn.execute(
                "UPDATE tracked_products SET user_id = ? WHERE user_id = ?",
                (admin_id, user_id)
            )
            reassign_conn.commit()
            reassign_conn.close()
            logger.info(f"Reassigned user {user_id} data to admin {admin_id}")
        except Exception as reassign_err:
            logger.warning(f"데이터 재배정 실패: {reassign_err}")

        if delete_user(user_id):
            logger.info(f"User deleted by admin {current_user['username']}: {user['username']}")
            return MessageResponse(success=True, message="사용자가 삭제되었습니다. 업체/상품이 관리자에게 재배정되었습니다.")
        else:
            raise HTTPException(status_code=500, detail="사용자 삭제 중 오류가 발생했습니다.")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete user: {str(e)}")
        raise HTTPException(status_code=500, detail="사용자 삭제 중 오류가 발생했습니다.")


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6)


@router.put("/users/{user_id}/reset-password", response_model=MessageResponse)
def admin_reset_password(
    user_id: int,
    request: AdminResetPasswordRequest,
    current_user: Dict[str, Any] = Depends(require_role(UserRole.ADMIN)),
) -> MessageResponse:
    """관리자가 특정 사용자의 비밀번호를 리셋 (admin 전용)"""
    try:
        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
        if update_user_password(user_id, request.new_password):
            logger.info(f"Admin {current_user['username']} reset password for user ID={user_id}")
            return MessageResponse(success=True, message="비밀번호가 리셋되었습니다.")
        else:
            raise HTTPException(status_code=500, detail="비밀번호 리셋 중 오류가 발생했습니다.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin password reset failed: {str(e)}")
        raise HTTPException(status_code=500, detail="비밀번호 리셋 중 오류가 발생했습니다.")


@router.get("/users/analysis-counts")
def get_analysis_counts(
    current_user: Dict[str, Any] = Depends(require_role(UserRole.ADMIN)),
):
    """유저별 실제 분석 실행 횟수 조회 (관리자 전용).
    daily_usage 테이블에서 당일/누적 query_count를 각각 카운팅."""
    try:
        from datetime import date as _date
        today_str = _date.today().isoformat()
        conn = _get_db_connection()
        cursor = conn.cursor()
        # 누적 합계
        cursor.execute(
            """SELECT user_id, SUM(query_count) AS cnt
               FROM daily_usage
               GROUP BY user_id"""
        )
        total_counts = {}
        for r in cursor.fetchall():
            total_counts[str(r[0])] = r[1]
        # 당일 합계
        cursor.execute(
            """SELECT user_id, query_count
               FROM daily_usage
               WHERE usage_date = ?""",
            (today_str,)
        )
        today_counts = {}
        for r in cursor.fetchall():
            today_counts[str(r[0])] = r[1]
        conn.close()
        return {"success": True, "data": total_counts, "today": today_counts}
    except Exception as e:
        logger.error(f"분석 횟수 조회 실패: {e}")
        return {"success": False, "error": f"분석 횟수 조회 실패: {str(e)}", "data": {}}


@router.get("/analysis-stats")
def get_analysis_stats(current_user: Dict[str, Any] = Depends(get_current_user)):
    """로직 분석 실행 건수 통계 — 설정 탭용 (최고관리자 전용).
    전체 요약(총/이번 달/오늘) + 직원별 집계. daily_usage.query_count 기준."""
    # require_role은 admin도 통과시키므로, '최고관리자만' 보장하려 명시적으로 검사
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="최고관리자만 접근 가능합니다.")
    try:
        from datetime import date as _date
        today_str = _date.today().isoformat()
        month_start = today_str[:8] + "01"  # 이번 달 1일 (YYYY-MM-01)
        conn = _get_db_connection()
        cur = conn.cursor()
        total = cur.execute("SELECT COALESCE(SUM(query_count),0) FROM daily_usage").fetchone()[0]
        today_total = cur.execute(
            "SELECT COALESCE(SUM(query_count),0) FROM daily_usage WHERE usage_date=?", (today_str,)
        ).fetchone()[0]
        month_total = cur.execute(
            "SELECT COALESCE(SUM(query_count),0) FROM daily_usage WHERE usage_date>=?", (month_start,)
        ).fetchone()[0]
        rows = cur.execute(
            """SELECT u.id, u.username, u.name, u.role,
                      COALESCE(SUM(du.query_count),0) AS total,
                      COALESCE(SUM(CASE WHEN du.usage_date=? THEN du.query_count ELSE 0 END),0) AS today,
                      COALESCE(SUM(CASE WHEN du.usage_date>=? THEN du.query_count ELSE 0 END),0) AS month
               FROM users u
               LEFT JOIN daily_usage du ON du.user_id = u.id
               WHERE u.is_active = 1
               GROUP BY u.id
               ORDER BY total DESC, today DESC""",
            (today_str, month_start)
        ).fetchall()
        per_user = [
            {
                "user_id": r["id"], "username": r["username"],
                "name": r["name"] or r["username"], "role": r["role"],
                "total": r["total"], "today": r["today"], "month": r["month"],
            }
            for r in rows
        ]
        conn.close()
        return {
            "success": True,
            "total": total, "today": today_total, "this_month": month_total,
            "per_user": per_user,
        }
    except Exception as e:
        logger.error(f"분석 통계 조회 실패: {e}")
        return {"success": False, "error": str(e), "total": 0, "today": 0, "this_month": 0, "per_user": []}


@router.get("/users/{user_id}/login-logs")
def get_login_logs(
    user_id: int,
    days: int = 7,
    limit: int = 10,
    current_user: Dict[str, Any] = Depends(require_role(UserRole.ADMIN)),
):
    """특정 직원의 최근 로그인 이력 조회 (관리자 전용) — 최신순 최대 limit개(기본 10)."""
    try:
        limit = max(1, min(int(limit), 50))
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, login_at, ip_address FROM login_logs
               WHERE user_id = ?
               ORDER BY login_at DESC LIMIT ?""",
            (user_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()
        return {
            "success": True,
            "data": [{"id": r[0], "login_at": r[1], "ip_address": r[2]} for r in rows],
        }
    except Exception as e:
        logger.error(f"로그인 이력 조회 실패: {e}")
        return {"success": False, "data": []}
