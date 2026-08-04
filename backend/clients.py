"""
Client/Advertiser Management Module for 로직분석
FastAPI router for managing advertising agency clients (광고주)
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Query, Depends, status
from pydantic import BaseModel, Field, validator

from auth import get_current_user, require_role, require_register_permission


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")

# APIRouter
router = APIRouter(prefix="/api/clients", tags=["clients"])


# ============================================================================
# Request/Response Models
# ============================================================================

class ClientBase(BaseModel):
    """Base client model for shared fields"""
    name: str = Field(..., min_length=1, max_length=255, description="광고주명/브랜드명")
    business_name: Optional[str] = Field(default="", max_length=255, description="사업자명")
    contact_name: Optional[str] = Field(default="", max_length=255, description="담당자명")
    contact_phone: Optional[str] = Field(default="", max_length=20, description="연락처")
    contact_email: Optional[str] = Field(default="", description="이메일")
    website_url: Optional[str] = Field(default="", max_length=500, description="웹사이트")
    naver_store_url: Optional[str] = Field(default="", max_length=500, description="네이버 스토어 URL")
    main_keywords: Optional[str] = Field(default="", description="주요 키워드 (쉼표 구분)")
    notes: Optional[str] = Field(default="", description="메모")
    status: Optional[str] = Field(default="active", pattern="^(active|paused|terminated)$", description="상태")

    @validator("contact_email")
    def validate_email(cls, v):
        """Validate email format if provided"""
        if v and "@" not in v:
            raise ValueError("유효하지 않은 이메일 형식입니다")
        return v

    @validator("contact_phone")
    def validate_phone(cls, v):
        """Validate phone format if provided (basic check)"""
        if v and len(v.replace("-", "").replace(" ", "")) < 9:
            raise ValueError("유효하지 않은 전화번호 형식입니다")
        return v


class ClientCreate(ClientBase):
    """Model for creating a client"""
    pass


class ClientUpdate(BaseModel):
    """Model for updating a client (all fields optional)"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    business_name: Optional[str] = Field(None, max_length=255)
    contact_name: Optional[str] = Field(None, max_length=255)
    contact_phone: Optional[str] = Field(None, max_length=20)
    contact_email: Optional[str] = Field(None)
    website_url: Optional[str] = Field(None, max_length=500)
    naver_store_url: Optional[str] = Field(None, max_length=500)
    main_keywords: Optional[str] = Field(None)
    notes: Optional[str] = Field(None)
    status: Optional[str] = Field(None, pattern="^(active|paused|terminated)$")
    # 자동분석 여부(2026-07 호출 다이어트): 0=중지(계약만료·환불·홀딩 등 관리 중단), 1=수행
    auto_analysis: Optional[int] = Field(None, ge=0, le=1)

    @validator("contact_email")
    def validate_email(cls, v):
        """Validate email format if provided"""
        if v and "@" not in v:
            raise ValueError("유효하지 않은 이메일 형식입니다")
        return v

    @validator("contact_phone")
    def validate_phone(cls, v):
        """Validate phone format if provided"""
        if v and len(v.replace("-", "").replace(" ", "")) < 9:
            raise ValueError("유효하지 않은 전화번호 형식입니다")
        return v


class ClientResponse(ClientBase):
    """Model for client response"""
    id: int
    created_by: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ClientListResponse(BaseModel):
    """Model for paginated client list response"""
    success: bool
    clients: List[ClientResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class ClientDetailResponse(BaseModel):
    """Model for single client detail response"""
    success: bool
    client: ClientResponse


class ClientCreateResponse(BaseModel):
    """Model for client creation response"""
    success: bool
    client: ClientResponse
    message: str


class ClientUpdateResponse(BaseModel):
    """Model for client update response"""
    success: bool
    client: ClientResponse
    message: str


class ClientDeleteResponse(BaseModel):
    """Model for client deletion response"""
    success: bool
    message: str


class ClientStatsResponse(BaseModel):
    """Model for client statistics response"""
    success: bool
    stats: Dict[str, int]


# ============================================================================
# Database Functions
# ============================================================================

@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrent access
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {str(e)}")
        raise
    finally:
        conn.close()


def init_clients_db():
    """Initialize clients table and indexes"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Create clients table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    business_name TEXT DEFAULT '',
                    contact_name TEXT DEFAULT '',
                    contact_phone TEXT DEFAULT '',
                    contact_email TEXT DEFAULT '',
                    website_url TEXT DEFAULT '',
                    naver_store_url TEXT DEFAULT '',
                    main_keywords TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    created_by INTEGER NOT NULL,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    updated_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """)

            # Create indexes for frequently queried columns
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_clients_status
                ON clients(status)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_clients_created_by
                ON clients(created_by)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_clients_created_at
                ON clients(created_at)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_clients_name
                ON clients(name)
            """)

            # 마이그레이션(#1): 등록 시 상세페이지 HTML 저장 → 재분석/자동분석에 재사용
            try:
                cursor.execute("SELECT detail_html FROM clients LIMIT 1")
            except Exception:
                cursor.execute("ALTER TABLE clients ADD COLUMN detail_html TEXT DEFAULT ''")
                logger.info("[clients] detail_html column added via migration")

            # 마이그레이션(#2, 2026-07 호출 다이어트): 관리 중단(계약만료·환불·홀딩) 업체의
            # 일일 자동분석·순위추적 제외 플래그. 1=자동분석 함(기본), 0=중지.
            try:
                cursor.execute("SELECT auto_analysis FROM clients LIMIT 1")
            except Exception:
                cursor.execute("ALTER TABLE clients ADD COLUMN auto_analysis INTEGER DEFAULT 1")
                logger.info("[clients] auto_analysis column added via migration")

            # 마이그레이션(#3, 2026-07 계약단계 연동): 직원이 수동으로 토글한 업체 표시.
            # 1이면 전산 계약단계 자동 동기화(07:30)가 덮어쓰지 않음(수동 우선).
            try:
                cursor.execute("SELECT auto_analysis_manual FROM clients LIMIT 1")
            except Exception:
                cursor.execute("ALTER TABLE clients ADD COLUMN auto_analysis_manual INTEGER DEFAULT 0")
                logger.info("[clients] auto_analysis_manual column added via migration")

            # 마이그레이션(#4, 2026-07 경쟁사 비교): 업체 유형과 광고주 연결.
            # role='advertiser'(기본, 정식 광고주) / 'competitor'(비교용 경쟁사).
            # competitor_of=연결된 광고주 client_id(경쟁사만). 경쟁사는 광고주 리스트·
            # 업무량·자동추적·정산·가망에서 제외되고, 비교 화면에서만 쓰인다.
            try:
                cursor.execute("SELECT role FROM clients LIMIT 1")
            except Exception:
                cursor.execute("ALTER TABLE clients ADD COLUMN role TEXT DEFAULT 'advertiser'")
                logger.info("[clients] role column added via migration")
            try:
                cursor.execute("SELECT competitor_of FROM clients LIMIT 1")
            except Exception:
                cursor.execute("ALTER TABLE clients ADD COLUMN competitor_of INTEGER DEFAULT NULL")
                logger.info("[clients] competitor_of column added via migration")

            # 마이그레이션(#5, 2026-07 경쟁사 TTL): 영업사원(viewer)이 등록한 경쟁사는
            # 30일 뒤 자동 삭제(스케줄러). expires_at=삭제 예정 시각(NULL=영구, 관리팀 등록분).
            try:
                cursor.execute("SELECT expires_at FROM clients LIMIT 1")
            except Exception:
                cursor.execute("ALTER TABLE clients ADD COLUMN expires_at TEXT DEFAULT NULL")
                logger.info("[clients] expires_at column added via migration")

            # 마이그레이션(#6, 2026-08 플레이스 축): 업체 축 구분 — 'store'(기본)/'place'.
            # 플레이스 분석의 업체 저장이 스토어와 같은 clients 파이프라인(권한·30일 유예)을 타되,
            # 스토어 전용 자동분석 배치에서는 제외하기 위한 표식.
            try:
                cursor.execute("SELECT vertical FROM clients LIMIT 1")
            except Exception:
                cursor.execute("ALTER TABLE clients ADD COLUMN vertical TEXT DEFAULT 'store'")
                logger.info("[clients] vertical column added via migration")

            logger.info("Clients database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize clients database: {str(e)}")
        raise


def dict_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert sqlite3.Row to dictionary"""
    if row is None:
        return None
    return dict(row)


def get_client_by_id(client_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single client by ID"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
            row = cursor.fetchone()
            return dict_from_row(row) if row else None
    except Exception as e:
        logger.error(f"Error fetching client {client_id}: {str(e)}")
        raise


def search_clients(
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    user_id: int = None,
    is_admin: bool = False,
) -> tuple[List[Dict[str, Any]], int]:
    """Search clients with pagination and filters (유저별 격리)"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Build query
            # 경쟁사(role=competitor)는 광고주 리스트에서 제외 (비교 화면에서만 사용)
            query = "SELECT * FROM clients WHERE 1=1 AND COALESCE(role,'advertiser')='advertiser'"
            params = []

            # 유저별 격리 (admin은 전체 조회)
            if not is_admin and user_id is not None:
                query += " AND created_by = ?"
                params.append(user_id)

            if search:
                search_term = f"%{search}%"
                query += " AND (name LIKE ? OR business_name LIKE ? OR contact_name LIKE ?)"
                params.extend([search_term, search_term, search_term])

            if status and status in ["active", "paused", "terminated"]:
                query += " AND status = ?"
                params.append(status)

            # Get total count — WHERE 절만 추출하여 안전하게 COUNT 쿼리 생성
            where_idx = query.find(" WHERE ")
            count_query = "SELECT COUNT(*) as count FROM clients" + (query[where_idx:] if where_idx >= 0 else "")
            cursor.execute(count_query, params)
            total = cursor.fetchone()["count"]

            # Get paginated results
            offset = (page - 1) * per_page
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([per_page, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()
            clients = [dict_from_row(row) for row in rows]

            return clients, total
    except Exception as e:
        logger.error(f"Error searching clients: {str(e)}")
        raise


def create_client(
    data: ClientCreate,
    created_by: int,
) -> Dict[str, Any]:
    """Create a new client"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # URL 중복 등록 경고 (같은 유저가 같은 스토어 URL 재등록 방지)
            if data.naver_store_url:
                dup = cursor.execute(
                    "SELECT id, name FROM clients WHERE naver_store_url = ? AND created_by = ? AND status = 'active'",
                    (data.naver_store_url, created_by)
                ).fetchone()
                if dup:
                    raise ValueError(f"이미 동일한 스토어 URL로 등록된 업체가 있습니다: {dup['name']} (ID: {dup['id']})")

            cursor.execute("""
                INSERT INTO clients (
                    name, business_name, contact_name, contact_phone, contact_email,
                    website_url, naver_store_url, main_keywords, notes, status, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.name,
                data.business_name or "",
                data.contact_name or "",
                data.contact_phone or "",
                data.contact_email or "",
                data.website_url or "",
                data.naver_store_url or "",
                data.main_keywords or "",
                data.notes or "",
                data.status or "active",
                created_by,
            ))

            client_id = cursor.lastrowid
            client = get_client_by_id(client_id)
            logger.info(f"Client created: ID={client_id}, Name={data.name}, CreatedBy={created_by}")

            return client
    except Exception as e:
        logger.error(f"Error creating client: {str(e)}")
        raise


def update_client(
    client_id: int,
    data: ClientUpdate,
) -> Dict[str, Any]:
    """Update an existing client"""
    try:
        # Verify client exists
        existing_client = get_client_by_id(client_id)
        if not existing_client:
            raise ValueError("클라이언트를 찾을 수 없습니다")

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Build update query dynamically
            updates = []
            params = []

            if data.name is not None:
                updates.append("name = ?")
                params.append(data.name)
            if data.business_name is not None:
                updates.append("business_name = ?")
                params.append(data.business_name)
            if data.contact_name is not None:
                updates.append("contact_name = ?")
                params.append(data.contact_name)
            if data.contact_phone is not None:
                updates.append("contact_phone = ?")
                params.append(data.contact_phone)
            if data.contact_email is not None:
                updates.append("contact_email = ?")
                params.append(data.contact_email)
            if data.website_url is not None:
                updates.append("website_url = ?")
                params.append(data.website_url)
            if data.naver_store_url is not None:
                updates.append("naver_store_url = ?")
                params.append(data.naver_store_url)
            if data.main_keywords is not None:
                updates.append("main_keywords = ?")
                params.append(data.main_keywords)
            if data.notes is not None:
                updates.append("notes = ?")
                params.append(data.notes)
            if data.status is not None:
                updates.append("status = ?")
                params.append(data.status)
            if data.auto_analysis is not None:
                updates.append("auto_analysis = ?")
                params.append(int(data.auto_analysis))
                # 직원 수동 토글 표시 — 계약단계 자동 동기화가 이 업체를 덮어쓰지 않게(수동 우선)
                updates.append("auto_analysis_manual = 1")

            # Always update updated_at
            updates.append("updated_at = datetime('now','localtime')")

            if updates:
                query = f"UPDATE clients SET {', '.join(updates)} WHERE id = ?"
                params.append(client_id)
                cursor.execute(query, params)
                logger.info(f"Client updated: ID={client_id}")

            return get_client_by_id(client_id)
    except Exception as e:
        logger.error(f"Error updating client {client_id}: {str(e)}")
        raise


def delete_client(client_id: int) -> bool:
    """Delete a client"""
    try:
        # Verify client exists
        existing_client = get_client_by_id(client_id)
        if not existing_client:
            raise ValueError("클라이언트를 찾을 수 없습니다")

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM clients WHERE id = ?", (client_id,))
            logger.info(f"Client deleted: ID={client_id}")
            return True
    except Exception as e:
        logger.error(f"Error deleting client {client_id}: {str(e)}")
        raise


def get_client_stats(user_id: int = None, is_admin: bool = False) -> Dict[str, int]:
    """Get client statistics for dashboard (유저별 격리)"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 유저별 필터 조건
            where = ""
            params = []
            if not is_admin and user_id is not None:
                where = " AND created_by = ?"
                params = [user_id]

            # Total clients
            cursor.execute("SELECT COUNT(*) as count FROM clients WHERE 1=1" + where, params)
            total = cursor.fetchone()["count"]

            # Clients by status
            cursor.execute(
                "SELECT COUNT(*) as count FROM clients WHERE status = 'active'" + where, params
            )
            active = cursor.fetchone()["count"]

            cursor.execute(
                "SELECT COUNT(*) as count FROM clients WHERE status = 'paused'" + where, params
            )
            paused = cursor.fetchone()["count"]

            cursor.execute(
                "SELECT COUNT(*) as count FROM clients WHERE status = 'terminated'" + where, params
            )
            terminated = cursor.fetchone()["count"]

            # Recent 30 days
            thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
            cursor.execute(
                "SELECT COUNT(*) as count FROM clients WHERE created_at > ?" + where,
                [thirty_days_ago] + params,
            )
            recent_30days = cursor.fetchone()["count"]

            return {
                "total": total,
                "active": active,
                "paused": paused,
                "terminated": terminated,
                "recent_30days": recent_30days,
            }
    except Exception as e:
        logger.error(f"Error getting client stats: {str(e)}")
        raise


# ============================================================================
# API Endpoints (라우트 순서 중요: /stats/summary를 /{client_id} 보다 앞에 정의)
# ============================================================================

@router.get("/stats/summary", response_model=ClientStatsResponse)
def get_stats(
    current_user: Dict = Depends(get_current_user),
):
    """Get client statistics for dashboard"""
    try:
        _is_adm = current_user.get("role") in ("admin", "superadmin")
        stats = get_client_stats(user_id=current_user["id"], is_admin=_is_adm)
        return ClientStatsResponse(success=True, stats=stats)
    except Exception as e:
        logger.error(f"Error getting client stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="통계를 불러올 수 없습니다",
        )


@router.get("/diagnostics")
def get_client_diagnostics(
    current_user: Dict = Depends(require_role("admin")),
):
    """업체 데이터 점검 (admin/superadmin 전용, 조회 전용).

    '진행중(active) 업체 일부가 사라짐' 원인 파악용:
    - byStatus: 상태별 업체 수
    - recentInactive: 최근 paused/terminated로 바뀐 업체 (의도치 않은 상태 변경 의심)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, COUNT(*) as cnt FROM clients GROUP BY status")
            by_status = {row["status"]: row["cnt"] for row in cursor.fetchall()}

            cursor.execute(
                "SELECT id, name, status, updated_at FROM clients "
                "WHERE status IN ('paused','terminated') ORDER BY updated_at DESC LIMIT 30"
            )
            recent_inactive = [dict(r) for r in cursor.fetchall()]

        # 서버 디스크/DB/백업 용량 (조회 전용)
        disk = None
        try:
            import shutil
            data_dir = os.path.dirname(os.path.abspath(DB_PATH))
            du = shutil.disk_usage(data_dir)
            _GB = 1024 ** 3
            db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
            backup_dir = os.path.join(data_dir, "backups")
            backup_count, backup_bytes = 0, 0
            if os.path.isdir(backup_dir):
                for _f in os.listdir(backup_dir):
                    if _f.startswith("logic_analysis_backup_") and _f.endswith(".db"):
                        backup_count += 1
                        try:
                            backup_bytes += os.path.getsize(os.path.join(backup_dir, _f))
                        except Exception:
                            pass
            disk = {
                "totalGB": round(du.total / _GB, 1),
                "usedGB": round(du.used / _GB, 1),
                "freeGB": round(du.free / _GB, 1),
                "usedPercent": round(du.used / du.total * 100, 1) if du.total else 0,
                "dbSizeGB": round(db_size / _GB, 2),
                "backupCount": backup_count,
                "backupTotalGB": round(backup_bytes / _GB, 2),
            }
        except Exception as _de:
            logger.warning(f"디스크 사용량 조회 실패(무시): {_de}")

        return {
            "success": True,
            "data": {
                "byStatus": by_status,
                "recentInactive": recent_inactive,
                "disk": disk,
            },
        }
    except Exception as e:
        logger.error(f"Error getting client diagnostics: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="업체 데이터 점검을 불러올 수 없습니다",
        )


# ============================================================================
# 담당자 배정/재배정 (관리자 전용)
# ============================================================================

class ManagerAssignRequest(BaseModel):
    manager_id: int

class BulkReassignRequest(BaseModel):
    from_user_id: int
    to_user_id: int


@router.get("/assignable-managers")
def assignable_managers(current_user: Dict = Depends(require_role("admin"))):
    """담당자로 배정 가능한 사용자 목록 (관리자/superadmin 전용)."""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, username, role FROM users "
            "WHERE is_active=1 AND role IN ('manager','admin','superadmin') "
            "ORDER BY (role='manager') DESC, name"
        ).fetchall()
    return {"success": True, "data": [
        {"id": r["id"], "name": (r["name"] or r["username"]), "role": r["role"]} for r in rows
    ]}


@router.get("/manager-counts")
def manager_counts(current_user: Dict = Depends(require_role("admin"))):
    """담당자별 보유 업체 수 (일괄 이관의 '원본' 선택용). 비활성(퇴사) 계정도 포함."""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT u.id, u.name, u.username, u.role, u.is_active, COUNT(c.id) AS cnt "
            "FROM users u JOIN clients c ON c.created_by = u.id AND c.status='active' "
            "GROUP BY u.id HAVING cnt > 0 ORDER BY cnt DESC"
        ).fetchall()
    return {"success": True, "data": [
        {"id": r["id"], "name": (r["name"] or r["username"]), "role": r["role"],
         "is_active": r["is_active"], "count": r["cnt"]} for r in rows
    ]}


@router.put("/{client_id}/manager")
def change_client_manager(client_id: int, req: ManagerAssignRequest,
                          current_user: Dict = Depends(require_role("admin"))):
    """업체 담당자(created_by) 변경 (관리자/superadmin 전용)."""
    with get_db_connection() as conn:
        u = conn.execute("SELECT id, name, username FROM users WHERE id=? AND is_active=1", (req.manager_id,)).fetchone()
        if not u:
            raise HTTPException(status_code=404, detail="담당자(사용자)를 찾을 수 없습니다")
        if not conn.execute("SELECT 1 FROM clients WHERE id=?", (client_id,)).fetchone():
            raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다")
        conn.execute("UPDATE clients SET created_by=?, updated_at=datetime('now','localtime') WHERE id=?",
                     (req.manager_id, client_id))
    logger.info(f"[manager] client {client_id} → user {req.manager_id} (by {current_user.get('id')})")
    return {"success": True, "manager_name": (u["name"] or u["username"])}


@router.post("/reassign-bulk")
def reassign_bulk(req: BulkReassignRequest, current_user: Dict = Depends(require_role("admin"))):
    """퇴사자 등 from_user의 업체 전체를 to_user로 일괄 이관 (관리자/superadmin 전용)."""
    if req.from_user_id == req.to_user_id:
        raise HTTPException(status_code=400, detail="같은 사용자로는 이관할 수 없습니다")
    with get_db_connection() as conn:
        to_u = conn.execute("SELECT id, name, username FROM users WHERE id=? AND is_active=1", (req.to_user_id,)).fetchone()
        if not to_u:
            raise HTTPException(status_code=404, detail="이관 대상 담당자를 찾을 수 없습니다")
        n = conn.execute(
            "UPDATE clients SET created_by=?, updated_at=datetime('now','localtime') WHERE created_by=?",
            (req.to_user_id, req.from_user_id)
        ).rowcount
    logger.info(f"[reassign-bulk] {req.from_user_id} → {req.to_user_id}: {n}건 (by {current_user.get('id')})")
    return {"success": True, "moved": n, "to_name": (to_u["name"] or to_u["username"])}


@router.get("", response_model=ClientListResponse)
def list_clients(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(active|paused|terminated)?$"),
    current_user: Dict = Depends(get_current_user),
):
    """
    List all clients with pagination and search.

    - page: 페이지 번호 (기본값: 1)
    - per_page: 페이지당 항목 수 (기본값: 20, 최대: 100)
    - search: 검색어 (광고주명, 사업자명, 담당자명)
    - status: 상태 필터 (active, paused, terminated)
    """
    try:
        _is_adm = current_user.get("role") in ("admin", "superadmin")
        clients, total = search_clients(
            page=page,
            per_page=per_page,
            search=search,
            status=status,
            user_id=current_user["id"],
            is_admin=_is_adm,
        )

        total_pages = (total + per_page - 1) // per_page

        return ClientListResponse(
            success=True,
            clients=clients,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        )
    except Exception as e:
        logger.error(f"Error listing clients: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="클라이언트 목록을 불러올 수 없습니다",
        )


def _check_ownership(client, current_user):
    """업체 소유권 확인. admin은 전체 접근 가능, 그 외는 created_by 일치 필수."""
    if current_user.get("role") in ("admin", "superadmin"):
        return True
    if client and client.get("created_by") == current_user.get("id"):
        return True
    raise HTTPException(status_code=403, detail="해당 업체에 대한 접근 권한이 없습니다.")


@router.get("/{client_id}", response_model=ClientDetailResponse)
def get_client(
    client_id: int,
    current_user: Dict = Depends(get_current_user),
):
    """Get client detail by ID (소유권 검증)"""
    try:
        client = get_client_by_id(client_id)
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="클라이언트를 찾을 수 없습니다",
            )
        _check_ownership(client, current_user)

        return ClientDetailResponse(success=True, client=client)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting client {client_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="클라이언트 정보를 불러올 수 없습니다",
        )


@router.post("", response_model=ClientCreateResponse, status_code=status.HTTP_201_CREATED)
def create_new_client(
    client_data: ClientCreate,
    current_user: Dict = Depends(get_current_user),
    role_check: Dict = Depends(require_register_permission()),  # 등록=관리팀 매니저+최고관리자만
):
    """
    Create a new client.
    Requires admin or manager role.
    """
    try:
        client = create_client(client_data, current_user["id"])

        return ClientCreateResponse(
            success=True,
            client=client,
            message=f"'{client_data.name}' 클라이언트가 생성되었습니다",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error creating client: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="클라이언트 생성에 실패했습니다",
        )


@router.put("/{client_id}", response_model=ClientUpdateResponse)
def update_existing_client(
    client_id: int,
    client_data: ClientUpdate,
    current_user: Dict = Depends(get_current_user),
    role_check: None = Depends(require_role(["admin", "manager"])),
):
    """
    Update an existing client.
    Requires admin or manager role + 소유권 검증.
    """
    try:
        existing = get_client_by_id(client_id)
        if not existing:
            raise HTTPException(status_code=404, detail="클라이언트를 찾을 수 없습니다")
        _check_ownership(existing, current_user)

        client = update_client(client_id, client_data)

        return ClientUpdateResponse(
            success=True,
            client=client,
            message="클라이언트 정보가 업데이트되었습니다",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error updating client {client_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="클라이언트 업데이트에 실패했습니다",
        )


@router.delete("/{client_id}", response_model=ClientDeleteResponse)
def delete_existing_client(
    client_id: int,
    current_user: Dict = Depends(get_current_user),
    role_check: None = Depends(require_role(["admin", "manager"])),
):
    """
    Delete a client.
    Requires admin or manager role + 소유권 검증.
    """
    try:
        existing = get_client_by_id(client_id)
        if not existing:
            raise HTTPException(status_code=404, detail="클라이언트를 찾을 수 없습니다")
        _check_ownership(existing, current_user)

        delete_client(client_id)

        return ClientDeleteResponse(
            success=True,
            message="클라이언트가 삭제되었습니다",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error deleting client {client_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="클라이언트 삭제에 실패했습니다",
        )


# ============================================================================
# Initialization
# ============================================================================

def init_module():
    """Initialize the module (call once at startup)"""
    init_clients_db()
    logger.info("Client management module initialized")
