"""
FastAPI Authentication Module for Logic Analysis Tool (로직분석)
JWT-based authentication with SQLite database, bcrypt hashing, and role-based access control.
"""

import os
import sqlite3
import logging
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


# ============================================================================
# API Router
# ============================================================================

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, request_obj: Request) -> LoginResponse:
    """
    User login endpoint.
    Returns JWT token and user information.
    """
    try:
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


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: Dict[str, Any] = Depends(get_current_user)) -> UserResponse:
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
async def logout(current_user: Dict[str, Any] = Depends(get_current_user)) -> MessageResponse:
    """Logout endpoint (client-side token removal)."""
    logger.info(f"User logged out: {current_user['username']}")
    return MessageResponse(success=True, message="로그아웃되었습니다.")


@router.put("/change-password", response_model=MessageResponse)
async def change_password(
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
async def list_users(current_user: Dict[str, Any] = Depends(require_role(UserRole.ADMIN))) -> List[UserResponse]:
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
async def create_new_user(
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
async def update_existing_user(
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
async def delete_existing_user(
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
async def admin_reset_password(
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
async def get_analysis_counts(
    current_user: Dict[str, Any] = Depends(require_role(UserRole.ADMIN)),
):
    """유저별 분석 실행 횟수 조회 (관리자 전용).
    clients.created_by → user_id 기준으로 client_analyses 건수를 카운팅."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT c.created_by AS user_id, COUNT(ca.id) AS cnt
               FROM client_analyses ca
               JOIN clients c ON ca.client_id = c.id
               GROUP BY c.created_by"""
        )
        rows = cursor.fetchall()
        conn.close()
        # { user_id: count } 형태로 반환
        counts = {}
        for r in rows:
            counts[str(r[0])] = r[1]
        return {"success": True, "data": counts}
    except Exception as e:
        logger.error(f"분석 횟수 조회 실패: {e}")
        return {"success": False, "error": f"분석 횟수 조회 실패: {str(e)}", "data": {}}


@router.get("/users/{user_id}/login-logs")
async def get_login_logs(
    user_id: int,
    days: int = 7,
    current_user: Dict[str, Any] = Depends(require_role(UserRole.ADMIN)),
):
    """특정 직원의 최근 로그인 이력 조회 (관리자 전용)"""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, login_at, ip_address FROM login_logs
               WHERE user_id = ? AND login_at >= datetime('now', '-' || ? || ' days')
               ORDER BY login_at DESC LIMIT 50""",
            (user_id, days),
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
