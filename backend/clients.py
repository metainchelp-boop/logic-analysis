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
from pydantic import BaseModel, Field, EmailStr, validator

from auth import get_current_user, require_role


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_PATH = os.getenv("DB_PATH", "logic_analysis.db")

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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrent access
    conn.execute("PRAGMA journal_mode=WAL")
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
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
            query = "SELECT * FROM clients WHERE 1=1"
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

            # Get total count
            count_query = query.replace("SELECT *", "SELECT COUNT(*) as count", 1)
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

            # Always update updated_at
            updates.append("updated_at = CURRENT_TIMESTAMP")

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
# API Endpoints
# ============================================================================

@router.get("", response_model=ClientListResponse)
async def list_clients(
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="클라이언트 목록을 불러올 수 없습니다",
        )


@router.get("/{client_id}", response_model=ClientDetailResponse)
async def get_client(
    client_id: int,
    current_user: Dict = Depends(get_current_user),
):
    """Get client detail by ID"""
    try:
        client = get_client_by_id(client_id)
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="클라이언트를 찾을 수 없습니다",
            )

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
async def create_new_client(
    client_data: ClientCreate,
    current_user: Dict = Depends(get_current_user),
    role_check: None = Depends(require_role(["admin", "manager"])),
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
async def update_existing_client(
    client_id: int,
    client_data: ClientUpdate,
    current_user: Dict = Depends(get_current_user),
    role_check: None = Depends(require_role(["admin", "manager"])),
):
    """
    Update an existing client.
    Requires admin or manager role.
    """
    try:
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
async def delete_existing_client(
    client_id: int,
    current_user: Dict = Depends(get_current_user),
    role_check: None = Depends(require_role(["admin"])),
):
    """
    Delete a client.
    Requires admin role only.
    """
    try:
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


@router.get("/stats/summary", response_model=ClientStatsResponse)
async def get_stats(
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="통계를 불러올 수 없습니다",
        )


# ============================================================================
# Initialization
# ============================================================================

def init_module():
    """Initialize the module (call once at startup)"""
    init_clients_db()
    logger.info("Client management module initialized")
