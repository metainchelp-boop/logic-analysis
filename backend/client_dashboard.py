"""
업체별 분석 관리 대시보드 API
v3.4 — 분석→업체 등록 연동, 일자별 분석 누적, 사용자 격리
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime, date
import sqlite3
import os
import re
import json
import logging

from auth import get_current_user, require_role, require_register_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cd", tags=["client-dashboard"])

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _is_admin(user) -> bool:
    try:
        return user["role"] in ("admin", "superadmin")
    except (KeyError, TypeError):
        return False


def _verify_client_access(conn, client_id: int, current_user: dict):
    """업체 소유권 확인. admin/viewer는 통과, manager는 created_by 확인.
    업체가 없으면 404, 권한 없으면 403 반환."""
    row = conn.execute("SELECT id, created_by FROM clients WHERE id = ?", (client_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")
    if _is_admin(current_user):
        return row
    # viewer는 전체 업체 조회(읽기) 가능
    if current_user.get("role") == "viewer":
        return row
    if row["created_by"] != current_user.get("id"):
        raise HTTPException(status_code=403, detail="해당 업체에 대한 접근 권한이 없습니다.")
    return row


def init_client_dashboard_db():
    """업체 대시보드용 테이블 생성 + 마이그레이션"""
    conn = _get_conn()
    try:
        # 1) 기본 테이블 생성 (인덱스 제외)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS client_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                product_url TEXT DEFAULT '',
                analysis_json TEXT NOT NULL DEFAULT '{}',
                volume_json TEXT DEFAULT '{}',
                related_json TEXT DEFAULT '{}',
                shop_products_json TEXT DEFAULT '[]',
                advertiser_json TEXT DEFAULT '{}',
                analyzed_date TEXT DEFAULT (date('now','localtime')),
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS client_rank_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                product_url TEXT DEFAULT '',
                rank_position INTEGER,
                page_number INTEGER,
                check_type TEXT DEFAULT 'manual',
                checked_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS daily_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                usage_date TEXT NOT NULL,
                query_count INTEGER DEFAULT 0,
                UNIQUE(user_id, usage_date)
            );
        """)

        # 2) 마이그레이션: 기존 테이블에 analyzed_date 컬럼 없으면 추가
        try:
            conn.execute("SELECT analyzed_date FROM client_analyses LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE client_analyses ADD COLUMN analyzed_date TEXT DEFAULT (date('now','localtime'))")
            conn.execute("UPDATE client_analyses SET analyzed_date = date(created_at) WHERE analyzed_date IS NULL")
            logger.info("[ClientDashboard] analyzed_date column added via migration")

        # 2b) 마이그레이션: report_html 컬럼 추가
        try:
            conn.execute("SELECT report_html FROM client_analyses LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE client_analyses ADD COLUMN report_html TEXT DEFAULT ''")
            logger.info("[ClientDashboard] report_html column added via migration")

        # 2c) 마이그레이션: created_by(분석 작업자 user_id) — 누가 분석·저장했는지 추적
        try:
            conn.execute("SELECT created_by FROM client_analyses LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE client_analyses ADD COLUMN created_by INTEGER")
            logger.info("[ClientDashboard] client_analyses.created_by column added via migration")

        # 3) 기존 UNIQUE 인덱스 삭제 후 새 인덱스 생성
        try:
            conn.execute("DROP INDEX IF EXISTS idx_client_analyses_key")
        except Exception:
            pass

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_client_analyses_daily
            ON client_analyses(client_id, keyword, analyzed_date)
        """)

        # my-clients의 "업체별 최신 1건" 조회 가속용
        # (WHERE client_id IN (...) ORDER BY analyzed_date DESC, updated_at DESC).
        # 업체가 1,000개 규모로 늘어 분석이력이 수만 row가 돼도 정렬 비용을 낮춘다.
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_client_analyses_recent
            ON client_analyses(client_id, analyzed_date DESC, updated_at DESC)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_client_rank_lookup
            ON client_rank_history(client_id, keyword, checked_at)
        """)

        # 순위 이력 조회 최적화 인덱스
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_client_rank_daily
            ON client_rank_history(client_id, keyword, check_type)
        """)

        # my_clients의 MAX(id) GROUP BY (client_id, keyword) 서브쿼리 커버링 인덱스
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_client_rank_maxid
            ON client_rank_history(client_id, keyword, id)
        """)

        conn.commit()
        logger.info("[ClientDashboard] DB tables initialized")
    except Exception as e:
        logger.error(f"[ClientDashboard] DB init error: {e}")
    finally:
        conn.close()

    # 일회성 정리(멱등): 비-매니저(영업팀 '배재민')의 상승 권한/잘못된 등록 정리
    cleanup_misassigned_clients()
    # 일회성: 신요섭 담당 업체를 실제 담당자로 재배정 + 나머지 삭제(사장님 매핑 기준)
    reassign_sinyoseop_clients()


def reassign_sinyoseop_clients():
    """일회성(플래그): '신요섭'(superadmin) 담당으로 잘못 잡힌 업체를 실제 담당자로 재배정,
    매핑에 없는 나머지는 하드 삭제. (사장님 지정 매핑)
    안전장치: 8개 재배정이 '전부' 성공할 때만 삭제 진행. 하나라도 매칭 실패 시 전체 롤백·
    플래그 미기록(다음 배포 재시도) → 잘못 삭제 방지."""
    FLAG = 'reassign_sinyoseop_v1'
    # (정규화된 업체명, 담당 매니저명, 매칭모드)  — 정규화: 공백제거+소문자
    REASSIGN = [
        ('정다운텃밭', '양근형', 'eq'),
        ('또또바삭', '김우리', 'eq'),
        ('문경시장기름집', '김우리', 'eq'),
        ('착한농부들', '이진희', 'eq'),
        ('푸른몰식품', '이진희', 'eq'),
        ('헤만로스터스', '박성섭', 'eq'),
        ('ongyel', '박성섭', 'eq'),
        ('모씨네', '이재민', 'prefix'),  # "모씨네 Mocci Ne" 등 변형 대비
    ]
    norm = lambda s: re.sub(r'\s+', '', (s or '')).lower()
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS _app_migrations "
                "(key TEXT PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now','localtime')))"
            )
            if conn.execute("SELECT 1 FROM _app_migrations WHERE key=?", (FLAG,)).fetchone():
                return
            cur = conn.cursor()
            srow = cur.execute("SELECT id FROM users WHERE TRIM(name)='신요섭' AND role='superadmin'").fetchone()
            if not srow:
                logger.warning("[reassign] '신요섭'(superadmin) 미발견 — 보류(재시도)")
                return
            sid = srow[0]

            def mgr_id(name):
                r = cur.execute("SELECT id FROM users WHERE TRIM(name)=?", (name,)).fetchone()
                return r[0] if r else None

            clients = cur.execute(
                "SELECT id, name FROM clients WHERE created_by=? AND status='active'", (sid,)
            ).fetchall()

            satisfied, matched_cids = set(), set()
            for cid, cname in clients:
                n = norm(cname)
                for idx, (key, mname, mode) in enumerate(REASSIGN):
                    hit = (n == key) if mode == 'eq' else n.startswith(key)
                    if hit:
                        mid = mgr_id(mname)
                        if mid:
                            cur.execute(
                                "UPDATE clients SET created_by=?, updated_at=datetime('now','localtime') WHERE id=?",
                                (mid, cid)
                            )
                            satisfied.add(idx); matched_cids.add(cid)
                            logger.info(f"[reassign] '{cname}' → {mname}(uid={mid})")
                        break

            if len(satisfied) == len(REASSIGN):
                rest = [(cid, cname) for cid, cname in clients if cid not in matched_cids]
                for cid, cname in rest:
                    cur.execute("DELETE FROM client_analyses WHERE client_id=?", (cid,))
                    cur.execute("DELETE FROM client_rank_history WHERE client_id=?", (cid,))
                    cur.execute("DELETE FROM clients WHERE id=?", (cid,))
                    logger.info(f"[reassign] '{cname}' 하드삭제(신요섭 잔여분)")
                cur.execute("INSERT OR REPLACE INTO _app_migrations(key) VALUES(?)", (FLAG,))
                conn.commit()
                logger.info(f"[reassign] 완료: 재배정 {len(satisfied)}건, 삭제 {len(rest)}건 (플래그 기록)")
            else:
                conn.rollback()
                miss = [REASSIGN[i][0] for i in range(len(REASSIGN)) if i not in satisfied]
                logger.warning(f"[reassign] 매칭 미완료(미일치: {miss}) → 전체 롤백, 플래그 미기록(재시도)")
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[reassign] 실패(무시): {e}")


def cleanup_misassigned_clients():
    """일회성(DB 플래그로 1회만 실행): '배재민'(영업팀) 정리.
    - role 무관(superadmin 제외)으로 name='배재민' 계정의 등록 업체를 '하드 삭제'
      (clients + 연관 client_analyses/client_rank_history) → 담당자 탭에서 완전히 사라짐.
    - 해당 계정 role → viewer 강등.
    플래그(_app_migrations)로 1회만 실행 → 향후 동명이인 매니저 피해 방지."""
    FLAG = 'cleanup_baejaemin_v2'
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS _app_migrations "
                "(key TEXT PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now','localtime')))"
            )
            if conn.execute("SELECT 1 FROM _app_migrations WHERE key=?", (FLAG,)).fetchone():
                return  # 이미 실행됨
            cur = conn.cursor()
            users = cur.execute(
                "SELECT id, role FROM users WHERE TRIM(name) = ? AND role != 'superadmin'",
                ('배재민',)
            ).fetchall()
            total = 0
            for uid, role in users:
                cids = [r[0] for r in cur.execute("SELECT id FROM clients WHERE created_by=?", (uid,)).fetchall()]
                for cid in cids:
                    cur.execute("DELETE FROM client_analyses WHERE client_id=?", (cid,))
                    cur.execute("DELETE FROM client_rank_history WHERE client_id=?", (cid,))
                    cur.execute("DELETE FROM clients WHERE id=?", (cid,))
                cur.execute("UPDATE users SET role='viewer' WHERE id=?", (uid,))
                total += len(cids)
                logger.info(f"[cleanup] '배재민'(uid={uid}, {role}→viewer): 업체 {len(cids)}건 하드삭제")
            if users:
                # 매칭·처리됐을 때만 플래그 기록 → 0건이면 다음 배포에 재시도
                cur.execute("INSERT OR REPLACE INTO _app_migrations(key) VALUES(?)", (FLAG,))
                conn.commit()
                logger.info(f"[cleanup] 완료: 대상 {len(users)}명, 업체 {total}건 삭제 (플래그 기록)")
            else:
                conn.commit()
                logger.warning("[cleanup] '배재민' 매칭 0건 — 플래그 미기록(다음 배포 재시도)")
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[cleanup] '배재민' 정리 실패(무시): {e}")


# ==================== Request / Response Models ====================

class SaveAnalysisRequest(BaseModel):
    client_id: int
    keyword: str
    product_url: Optional[str] = ''
    analysis_data: Optional[Any] = {}
    volume_data: Optional[Any] = {}
    related_data: Optional[Any] = {}
    shop_products: Optional[Any] = []
    advertiser_data: Optional[Any] = {}
    report_html: Optional[str] = ''
    detail_html: Optional[str] = ''  # #1: 상세페이지 HTML(재분석/자동분석 재사용)


class QuickRegisterRequest(BaseModel):
    """분석 탭에서 빠른 업체 등록"""
    name: str
    keyword: str
    product_url: Optional[str] = ''
    analysis_data: Optional[Any] = {}
    volume_data: Optional[Any] = {}
    related_data: Optional[Any] = {}
    shop_products: Optional[Any] = []
    advertiser_data: Optional[Any] = {}
    report_html: Optional[str] = ''
    detail_html: Optional[str] = ''  # #1: 상세페이지 HTML(재분석/자동분석 재사용)


class SaveRankRequest(BaseModel):
    client_id: int
    keyword: str
    product_url: Optional[str] = ''
    rank_position: Optional[int] = None
    page_number: Optional[int] = None
    check_type: Optional[str] = 'manual'


# ==================== 빠른 업체 등록 (분석 탭에서) ====================

@router.post("/quick-register")
def quick_register(req: QuickRegisterRequest, current_user: dict = Depends(require_register_permission())):
    """분석 결과와 함께 업체를 빠르게 등록 (신규 또는 기존 업체에 분석 추가)"""
    conn = _get_conn()
    try:
        user_id = current_user["id"]
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        today = date.today().isoformat()

        # 같은 이름의 업체가 이미 있는지 확인 (본인 소유)
        existing = conn.execute(
            "SELECT id FROM clients WHERE name = ? AND created_by = ?",
            (req.name, user_id)
        ).fetchone()

        if existing:
            client_id = existing['id']
            # 키워드 업데이트 (기존 키워드에 새 키워드 추가)
            cur_kw = conn.execute(
                "SELECT main_keywords FROM clients WHERE id = ?", (client_id,)
            ).fetchone()
            kw_list = [k.strip() for k in (cur_kw['main_keywords'] or '').split(',') if k.strip()]
            if req.keyword not in kw_list:
                kw_list.append(req.keyword)
                conn.execute(
                    "UPDATE clients SET main_keywords = ?, updated_at = ? WHERE id = ?",
                    (', '.join(kw_list), now, client_id)
                )
            msg = f"'{req.name}' 업체에 분석 결과가 추가되었습니다."
        else:
            # 신규 업체 등록
            cursor = conn.execute("""
                INSERT INTO clients (name, business_name, main_keywords, naver_store_url,
                    status, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
            """, (req.name, req.name, req.keyword, req.product_url or '',
                  user_id, now, now))
            client_id = cursor.lastrowid
            msg = f"'{req.name}' 업체가 등록되고 분석 결과가 저장되었습니다."

        # 분석 결과 저장 (일자별 누적)
        _save_analysis_internal(conn, client_id, req.keyword, req.product_url or '',
                                req.analysis_data, req.volume_data, req.related_data,
                                req.shop_products, req.advertiser_data, today, now,
                                req.report_html or '', author_id=user_id)

        # #1: 상세 HTML 저장 (있을 때만)
        if req.detail_html:
            try:
                conn.execute("UPDATE clients SET detail_html = ?, updated_at = ? WHERE id = ?",
                             (req.detail_html, now, client_id))
            except Exception:
                pass

        conn.commit()
        return {"success": True, "message": msg, "client_id": client_id}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"[quick-register] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


def _save_analysis_internal(conn, client_id, keyword, product_url,
                            analysis_data, volume_data, related_data,
                            shop_products, advertiser_data, today, now,
                            report_html='', author_id=None):
    """분석 결과 내부 저장 함수 (일자별 UPSERT)
    author_id: 분석을 실행·저장한 user_id(작업자 추적). 자동 저장 등 미상이면 None.
    주의: 호출자가 conn.commit()을 담당합니다."""
    params = (
        product_url,
        json.dumps(analysis_data or {}, ensure_ascii=False),
        json.dumps(volume_data or {}, ensure_ascii=False),
        json.dumps(related_data or {}, ensure_ascii=False),
        json.dumps(shop_products or [], ensure_ascii=False),
        json.dumps(advertiser_data or {}, ensure_ascii=False),
        report_html or '',
        now,
    )

    existing = conn.execute(
        "SELECT id FROM client_analyses WHERE client_id = ? AND keyword = ? AND analyzed_date = ?",
        (client_id, keyword, today)
    ).fetchone()

    if existing:
        # created_by는 author_id가 있을 때만 갱신(자동 재저장이 작업자 기록을 지우지 않도록)
        conn.execute("""
            UPDATE client_analyses
            SET product_url=?, analysis_json=?, volume_json=?,
                related_json=?, shop_products_json=?, advertiser_json=?,
                report_html=?, updated_at=?, created_by=COALESCE(?, created_by)
            WHERE client_id=? AND keyword=? AND analyzed_date=?
        """, params + (author_id, client_id, keyword, today))
    else:
        conn.execute("""
            INSERT INTO client_analyses
            (client_id, keyword, product_url, analysis_json, volume_json,
             related_json, shop_products_json, advertiser_json, report_html,
             analyzed_date, created_at, updated_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (client_id, keyword) + params[:7] + (today, now, now, author_id))


# ==================== 업체 목록 ====================

@router.get("/my-clients")
def my_clients(current_user: dict = Depends(get_current_user)):
    """등록된 업체 목록 + 최근 분석 요약 (admin/viewer=전체, manager=본인)"""
    conn = _get_conn()
    try:
        user_id = current_user["id"]
        is_adm = _is_admin(current_user)
        user_role = current_user.get("role", "viewer")

        # 목록에 필요한 컬럼만 선택한다. SELECT * 는 detail_html(상세페이지 HTML 통째,
        # 업체당 수십~수백 KB)까지 끌어와, 관리자(전체 336개)에서 응답이 수십~수백 MB로
        # 부풀어 워커가 메모리로 죽어(→ /api/cd/my-clients 502) 대시보드가 안 떴다.
        # detail_html은 목록 화면에서 쓰지 않으므로 제외한다.
        _COLS = ("id, name, business_name, contact_name, contact_phone, contact_email, "
                 "website_url, naver_store_url, main_keywords, notes, status, "
                 "created_by, created_at, updated_at")
        if is_adm or user_role == "viewer":
            clients = conn.execute(
                f"SELECT {_COLS} FROM clients WHERE status='active' ORDER BY updated_at DESC"
            ).fetchall()
        else:
            clients = conn.execute(
                f"SELECT {_COLS} FROM clients WHERE status='active' "
                "AND (created_by = ? OR created_by IS NULL OR created_by = '') "
                "ORDER BY updated_at DESC",
                (user_id,)
            ).fetchall()

        client_ids = [c['id'] for c in clients]
        if not client_ids:
            return {"success": True, "data": []}
        placeholders = ','.join('?' * len(client_ids))

        # 집계는 SQL(GROUP BY)에서 처리한다. 과거에는 client_analyses의 모든 row를
        # fetchall()로 메모리에 통째로 올렸는데, 관리자(업체 220개 전체)는 분석이력이
        # 수천~수만 row라 워커가 메모리로 죽어(→ /api/cd/my-clients 502) 대시보드가
        # 로드되지 않았다. 집계를 SQL로 옮겨 업체당 1줄만 가져온다.
        agg_map = {}
        for r in conn.execute(
            f"""SELECT client_id,
                       COUNT(*)                    AS analysis_count,
                       MAX(updated_at)             AS last_analyzed,
                       COUNT(DISTINCT keyword)     AS unique_keyword_count,
                       COUNT(DISTINCT analyzed_date) AS total_analysis_days
                FROM client_analyses
                WHERE client_id IN ({placeholders})
                GROUP BY client_id""",
            client_ids
        ):
            agg_map[r['client_id']] = r

        # 프론트는 업체별 "최신 1건"만 사용 → 커서를 스트리밍하며 업체당 최초 1건만 보관
        # (fetchall로 전체를 메모리에 올리지 않음)
        latest_map = {}
        for r in conn.execute(
            f"""SELECT client_id, keyword, product_url, analyzed_date, updated_at
                FROM client_analyses
                WHERE client_id IN ({placeholders})
                ORDER BY analyzed_date DESC, updated_at DESC""",
            client_ids
        ):
            cid = r['client_id']
            if cid not in latest_map:
                latest_map[cid] = {
                    'keyword': r['keyword'], 'product_url': r['product_url'],
                    'analyzed_date': r['analyzed_date'], 'updated_at': r['updated_at'],
                }

        # 담당자(등록 직원) 이름 벌크 조회 (created_by → users.name)
        mgr_ids = sorted({c['created_by'] for c in clients if c['created_by'] is not None})
        mgr_map = {}
        if mgr_ids:
            mph = ','.join('?' * len(mgr_ids))
            for u in conn.execute(
                f"SELECT id, name, username FROM users WHERE id IN ({mph})", mgr_ids
            ).fetchall():
                mgr_map[u['id']] = (u['name'] or u['username'] or '')

        result = []
        for c in clients:
            row = dict(c)
            cid = c['id']
            a = agg_map.get(cid)
            row['analysis_count'] = (a['analysis_count'] if a else 0)
            row['last_analyzed'] = (a['last_analyzed'] if a else None)
            row['unique_keyword_count'] = (a['unique_keyword_count'] if a else 0)
            row['total_analysis_days'] = (a['total_analysis_days'] if a else 0)
            row['analyzed_keywords'] = ([latest_map[cid]] if cid in latest_map else [])  # 최신 1건만
            row['manager_name'] = mgr_map.get(row.get('created_by'), '')  # 담당자명
            result.append(row)

        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"[my-clients] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ==================== 등록된 업체 간략 목록 (라우트 순서 중요: /{client_id} 보다 위) ====================

@router.get("/registered-clients")
def registered_clients(current_user: dict = Depends(get_current_user)):
    """분석 탭에서 업체 선택 드롭다운용 간략 목록"""
    conn = _get_conn()
    try:
        user_id = current_user["id"]
        is_adm = _is_admin(current_user)

        user_role = current_user.get("role", "viewer")

        # admin/viewer → 전체 업체, manager → 본인 등록분만
        if is_adm or user_role == "viewer":
            rows = conn.execute(
                "SELECT id, name, main_keywords FROM clients WHERE status = 'active' ORDER BY name ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, main_keywords FROM clients "
                "WHERE status = 'active' AND (created_by = ? OR created_by IS NULL OR created_by = '') "
                "ORDER BY name ASC",
                (user_id,)
            ).fetchall()

        return {"success": True, "data": [dict(r) for r in rows]}
    except Exception as e:
        logger.error(f"[registered-clients] {e}")
        return {"success": False, "data": [], "error": str(e)}
    finally:
        conn.close()


# ==================== 분석 결과 저장/조회 ====================

@router.post("/analyze")
def save_analysis(req: SaveAnalysisRequest, current_user: dict = Depends(require_role(["admin", "manager"]))):
    """분석 결과 저장 (admin/manager 전용, 일자별 누적)"""
    conn = _get_conn()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        today = date.today().isoformat()

        # 업체 존재 + 소유권 확인
        _verify_client_access(conn, req.client_id, current_user)

        _save_analysis_internal(conn, req.client_id, req.keyword, req.product_url or '',
                                req.analysis_data, req.volume_data, req.related_data,
                                req.shop_products, req.advertiser_data, today, now,
                                req.report_html or '', author_id=current_user.get("id"))

        # #1: 상세 HTML 저장 (있을 때만 — 빈값으로 기존 저장본을 덮어쓰지 않음)
        if req.detail_html:
            try:
                conn.execute("UPDATE clients SET detail_html = ?, updated_at = ? WHERE id = ?",
                             (req.detail_html, now, req.client_id))
            except Exception:
                pass  # detail_html 컬럼 없으면 무시(마이그레이션 전)

        # 키워드 업데이트
        cur_kw = conn.execute(
            "SELECT main_keywords FROM clients WHERE id = ?", (req.client_id,)
        ).fetchone()
        if cur_kw:
            kw_list = [k.strip() for k in (cur_kw['main_keywords'] or '').split(',') if k.strip()]
            if req.keyword not in kw_list:
                kw_list.append(req.keyword)
                conn.execute(
                    "UPDATE clients SET main_keywords = ?, updated_at = ? WHERE id = ?",
                    (', '.join(kw_list), now, req.client_id)
                )

        conn.commit()
        return {"success": True, "message": "분석 결과가 저장되었습니다."}
    except HTTPException:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"[save-analysis] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/{client_id}/analysis")
def get_analysis(client_id: int, keyword: Optional[str] = None,
                       current_user: dict = Depends(get_current_user)):
    """저장된 분석 결과 조회 (일자별 히스토리, 최근 90일 제한, 소유권 검증)
    최적화: report_html, shop_products_json 등 대용량 컬럼 제외 → 17MB → ~1MB"""
    conn = _get_conn()
    try:
        _verify_client_access(conn, client_id, current_user)
        # 목록용 경량 컬럼만 조회 (report_html 250KB/건 제외)
        light_cols = """id, client_id, keyword, product_url,
            analysis_json, volume_json, related_json, advertiser_json,
            analyzed_date, created_at, updated_at,
            CASE WHEN report_html IS NOT NULL AND report_html != '' THEN 1 ELSE 0 END as has_report_html"""
        if keyword:
            rows = conn.execute(
                f"SELECT {light_cols} FROM client_analyses WHERE client_id=? AND keyword=? ORDER BY analyzed_date DESC LIMIT 90",
                (client_id, keyword)
            ).fetchall()
            return {"success": True, "data": [_parse_analysis_row_light(r) for r in rows]}
        else:
            rows = conn.execute(
                f"SELECT {light_cols} FROM client_analyses WHERE client_id=? ORDER BY analyzed_date DESC, updated_at DESC LIMIT 200",
                (client_id,)
            ).fetchall()
            return {"success": True, "data": [_parse_analysis_row_light(r) for r in rows]}
    except Exception as e:
        logger.error(f"[get-analysis] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/{client_id}/history")
def get_analysis_history(client_id: int, keyword: str,
                               current_user: dict = Depends(get_current_user)):
    """특정 키워드의 일자별 분석 히스토리 (트렌드 보기용, 소유권 검증)"""
    conn = _get_conn()
    try:
        _verify_client_access(conn, client_id, current_user)
        rows = conn.execute("""
            SELECT analyzed_date, analysis_json, volume_json, updated_at
            FROM client_analyses
            WHERE client_id = ? AND keyword = ?
            ORDER BY analyzed_date ASC
            LIMIT 180
        """, (client_id, keyword)).fetchall()

        history = []
        for r in rows:
            try:
                ad = json.loads(r['analysis_json'] or '{}')
            except (json.JSONDecodeError, TypeError):
                ad = {}
            try:
                vd = json.loads(r['volume_json'] or '{}')
            except (json.JSONDecodeError, TypeError):
                vd = {}
            # 광고주 정보
            ai = ad.get('advertiserInfo', {})
            pc_clicks = ai.get('pcClicks', '-')
            mobile_clicks = ai.get('mobileClicks', '-')
            ad_comp_idx = ai.get('compIdx', '-')

            # 경쟁강도 정보
            ci = ad.get('competitionIndex', {})

            history.append({
                'date': r['analyzed_date'],
                'updated_at': r['updated_at'],
                'search_volume': ad.get('summaryCards', {}).get('totalVolume', '-'),
                'pc_clicks': pc_clicks,
                'mobile_clicks': mobile_clicks,
                'comp_index': ci.get('compIndex', None),
                'comp_percent': ci.get('compPercent', None),
                'ad_comp_idx': ad_comp_idx,
                'market_size': ad.get('marketRevenue', {}).get('estimatedMonthly', '-'),
            })

        return {"success": True, "data": history}
    except Exception as e:
        logger.error(f"[analysis-history] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


def _parse_analysis_row(row, include_html=False):
    """DB row를 JSON 파싱된 dict로 변환 (SELECT * 용)"""
    d = dict(row)
    for key, json_key in [
        ('analysis_json', 'analysis_data'),
        ('volume_json', 'volume_data'),
        ('related_json', 'related_data'),
        ('shop_products_json', 'shop_products'),
        ('advertiser_json', 'advertiser_data'),
    ]:
        try:
            d[json_key] = json.loads(d.pop(key, '{}'))
        except (json.JSONDecodeError, TypeError):
            d[json_key] = {}
    # 목록 조회 시 report_html은 용량이 크므로 존재 여부만 표시
    if not include_html:
        has_html = bool(d.get('report_html', ''))
        d.pop('report_html', None)
        d['has_report_html'] = has_html
    return d


def _parse_analysis_row_light(row):
    """경량 조회용 파서 (report_html, shop_products_json 제외된 SELECT 결과)"""
    d = dict(row)
    for key, json_key in [
        ('analysis_json', 'analysis_data'),
        ('volume_json', 'volume_data'),
        ('related_json', 'related_data'),
        ('advertiser_json', 'advertiser_data'),
    ]:
        try:
            d[json_key] = json.loads(d.pop(key, '{}'))
        except (json.JSONDecodeError, TypeError):
            d[json_key] = {}
    # has_report_html은 이미 SQL CASE로 계산됨
    d['has_report_html'] = bool(d.get('has_report_html', 0))
    return d


# ==================== 업체 삭제 ====================

@router.delete("/{client_id}")
def delete_client(client_id: int, current_user: dict = Depends(require_role(["admin", "manager"]))):
    """업체 삭제 (admin/manager, 관련 분석/순위 데이터도 함께 삭제)"""
    conn = _get_conn()
    try:
        user_id = current_user["id"]
        is_adm = _is_admin(current_user)

        # 업체 존재 및 소유권 확인
        client = conn.execute("SELECT id, name, created_by FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not client:
            raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")
        if not is_adm and client['created_by'] != user_id:
            raise HTTPException(status_code=403, detail="삭제 권한이 없습니다.")

        name = client['name']
        # 관련 데이터 삭제 (FOREIGN KEY CASCADE가 안 될 수 있으므로 명시적 삭제)
        conn.execute("DELETE FROM client_analyses WHERE client_id = ?", (client_id,))
        conn.execute("DELETE FROM client_rank_history WHERE client_id = ?", (client_id,))
        conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        conn.commit()

        logger.info(f"[delete-client] '{name}' (id={client_id}) deleted by user {user_id}")
        return {"success": True, "message": f"'{name}' 업체가 삭제되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[delete-client] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ==================== 보고서 HTML 다운로드 ====================

@router.get("/{client_id}/report-html")
def get_report_html(client_id: int, keyword: str, date: str,
                          current_user: dict = Depends(get_current_user)):
    """특정 일자의 저장된 HTML 보고서 반환 (소유권 검증)"""
    conn = _get_conn()
    try:
        _verify_client_access(conn, client_id, current_user)
        row = conn.execute(
            "SELECT report_html FROM client_analyses WHERE client_id=? AND keyword=? AND analyzed_date=?",
            (client_id, keyword, date)
        ).fetchone()
        if not row or not row['report_html']:
            raise HTTPException(status_code=404, detail="해당 날짜의 HTML 보고서가 없습니다.")
        return {"success": True, "html": row['report_html']}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[report-html] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ==================== 순위 추적 이력 ====================

@router.post("/rank-save")
def save_rank(req: SaveRankRequest, current_user: dict = Depends(require_role(["admin", "manager"]))):
    """순위 체크 결과 저장 (admin/manager 전용, 소유권 검증, 당일 중복 시 UPDATE)"""
    conn = _get_conn()
    try:
        _verify_client_access(conn, req.client_id, current_user)
        today = date.today().isoformat()

        # 같은 날 같은 체크 타입의 기존 기록 확인 (product_url NULL 안전 처리)
        product_url = req.product_url or ''
        check_type = req.check_type or 'manual'
        existing = conn.execute(
            """SELECT id FROM client_rank_history
               WHERE client_id=? AND keyword=? AND DATE(checked_at)=? AND check_type=?""",
            (req.client_id, req.keyword, today, check_type)
        ).fetchone()

        if existing:
            # 기존 기록 업데이트
            conn.execute("""
                UPDATE client_rank_history
                SET rank_position=?, page_number=?, checked_at=datetime('now','localtime')
                WHERE id=?
            """, (req.rank_position, req.page_number, existing['id']))
            conn.commit()
            return {"success": True, "message": "순위 기록이 업데이트되었습니다."}
        else:
            conn.execute("""
                INSERT INTO client_rank_history
                (client_id, keyword, product_url, rank_position, page_number, check_type)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (req.client_id, req.keyword, product_url,
                  req.rank_position, req.page_number, check_type))
            conn.commit()
            return {"success": True, "message": "순위 기록이 저장되었습니다."}
    except Exception as e:
        logger.error(f"[save-rank] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/{client_id}/rank-history")
def get_rank_history(client_id: int, keyword: Optional[str] = None, days: int = 90,
                           current_user: dict = Depends(get_current_user)):
    """순위 추적 이력 조회 (소유권 검증)"""
    conn = _get_conn()
    try:
        _verify_client_access(conn, client_id, current_user)
        if keyword:
            rows = conn.execute("""
                SELECT * FROM client_rank_history
                WHERE client_id=? AND keyword=?
                AND checked_at >= datetime('now','localtime', ?)
                ORDER BY checked_at ASC
            """, (client_id, keyword, f'-{days} days')).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM client_rank_history
                WHERE client_id=?
                AND checked_at >= datetime('now','localtime', ?)
                ORDER BY checked_at ASC
            """, (client_id, f'-{days} days')).fetchall()

        return {"success": True, "data": [dict(r) for r in rows]}
    except Exception as e:
        logger.error(f"[rank-history] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ==================== AI 인사이트 ====================

@router.get("/{client_id}/ai-insights")
def get_ai_insights(client_id: int, current_user: dict = Depends(get_current_user)):
    """업체별 AI 인사이트 통합 조회"""
    conn = _get_conn()
    try:
        _verify_client_access(conn, client_id, current_user)
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))
    finally:
        conn.close()

    try:
        from ai_insights import get_all_client_insights
        result = get_all_client_insights(client_id)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"[ai-insights] {e}")
        return {"success": False, "detail": str(e)}


@router.get("/portal-summary")
def portal_summary(company: str = Query(None, description="전산 광고주 회사명(폴백)"),
                   client_id: int = Query(None, description="명시적 매핑 업체 id(우선)"),
                   current_user: dict = Depends(get_current_user)):
    """전산 광고주 공유 대시보드용 — 업체 매핑(client_id 우선, 없으면 회사명) → 미리 계산된 일일 분석 요약 + 인사이트.
    무거운 재분석 없이 client_analyses(스케줄러 적재분)를 빠르게 조회. 매칭 실패 시 found=False.
    """
    name = (company or "").strip()
    if not client_id and not name:
        return {"found": False}
    conn = _get_conn()
    try:
        if client_id:  # 명시적 매핑 우선 — 회사명 무관
            row = conn.execute(
                "SELECT id, name FROM clients WHERE id = ? LIMIT 1", (client_id,)).fetchone()
        else:
            row = conn.execute(
                "SELECT id, name FROM clients WHERE name = ? AND status = 'active' ORDER BY id LIMIT 1",
                (name,)).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT id, name FROM clients WHERE name LIKE ? AND status = 'active' ORDER BY id LIMIT 1",
                    (f"%{name}%",)).fetchone()
        if not row:
            return {"found": False}
        cid = row["id"]

        # 키워드별 최신 분석 1건씩 (최대 8개) → 일일 리포트
        rep_rows = conn.execute("""
            SELECT keyword, MAX(analyzed_date) AS analyzed_date, analysis_json
            FROM client_analyses
            WHERE client_id = ?
            GROUP BY keyword
            ORDER BY analyzed_date DESC
            LIMIT 8
        """, (cid,)).fetchall()
        daily = []
        for r in rep_rows:
            try:
                ad = json.loads(r["analysis_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                ad = {}
            vol = ad.get("summaryCards", {}).get("totalVolume", None)
            comp = ad.get("competitionIndex", {}).get("compPercent", None)
            parts = []
            if vol not in (None, "-", ""):
                parts.append(f"검색량 {vol}")
            if comp is not None:
                parts.append(f"경쟁강도 {comp}%")
            daily.append({
                "date": r["analyzed_date"],
                "keyword": r["keyword"],
                "summary": " · ".join(parts) if parts else "분석 완료",
            })

        total = conn.execute(
            "SELECT COUNT(*) AS c FROM client_analyses WHERE client_id = ?", (cid,)).fetchone()["c"]

        insight = None
        if daily:
            top = daily[0]
            tail = f" ({top['summary']})" if top["summary"] and top["summary"] != "분석 완료" else ""
            insight = (f"최근 {total}건의 자동 분석이 누적되었습니다. "
                       f"현재 {len(daily)}개 키워드를 추적 중이며, 가장 최근 분석 키워드는 "
                       f"'{top['keyword']}'{tail}입니다.")

        return {"found": True, "clientId": cid, "insight": insight,
                "dailyReports": daily, "totalDays": total}
    except Exception as e:
        logger.error(f"[portal-summary] {e}")
        return {"found": False, "detail": str(e)}
    finally:
        conn.close()


@router.get("/clients-lookup")
def clients_lookup(q: str = Query(None, description="회사명 부분검색"),
                   current_user: dict = Depends(get_current_user)):
    """전산 관리 화면 피커용 — 로직분석 업체 [{id,name}] 목록(q 부분검색, 최대 30)."""
    conn = _get_conn()
    try:
        key = (q or "").strip()
        if key:
            rows = conn.execute(
                "SELECT id, name FROM clients WHERE status = 'active' AND name LIKE ? "
                "ORDER BY name LIMIT 30", (f"%{key}%",)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name FROM clients WHERE status = 'active' ORDER BY name LIMIT 30").fetchall()
        return {"success": True, "data": [{"id": r["id"], "name": r["name"]} for r in rows]}
    except Exception as e:
        logger.error(f"[clients-lookup] {e}")
        return {"success": False, "data": []}
    finally:
        conn.close()


# ==================== 일일 조회 제한 ====================

@router.get("/usage/check")
def check_usage(current_user: dict = Depends(get_current_user)):
    """일일 조회 횟수 확인"""
    conn = _get_conn()
    try:
        user_id = current_user["id"]
        today_str = date.today().isoformat()
        row = conn.execute(
            "SELECT query_count FROM daily_usage WHERE user_id=? AND usage_date=?",
            (user_id, today_str)
        ).fetchone()
        count = row['query_count'] if row else 0

        try:
            role = current_user['role']
        except (KeyError, TypeError):
            role = 'readonly'
        limit = -1 if role in ('admin', 'superadmin', 'manager') else 3

        return {
            "success": True,
            "data": {
                "used": count,
                "limit": limit,
                "remaining": limit - count if limit > 0 else -1,
                "can_query": limit < 0 or count < limit
            }
        }
    except Exception as e:
        logger.error(f"[check-usage] {e}")
        return {"success": True, "data": {"used": 0, "limit": -1, "remaining": -1, "can_query": True}}
    finally:
        conn.close()


@router.post("/usage/increment")
def increment_usage(current_user: dict = Depends(get_current_user)):
    """조회 횟수 1 증가"""
    conn = _get_conn()
    try:
        user_id = current_user["id"]
        today_str = date.today().isoformat()
        conn.execute("""
            INSERT INTO daily_usage (user_id, usage_date, query_count)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, usage_date)
            DO UPDATE SET query_count = query_count + 1
        """, (user_id, today_str))
        conn.commit()
        return {"success": True}
    except Exception as e:
        logger.error(f"[increment-usage] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/today-stats")
def today_stats(current_user: dict = Depends(get_current_user)):
    """당일 수동 분석 횟수 + 당일 보고서 출력 건수"""
    conn = _get_conn()
    try:
        today_str = date.today().isoformat()
        # 당일 수동 분석 횟수 (전체 사용자 합계)
        row = conn.execute(
            "SELECT COALESCE(SUM(query_count), 0) as total FROM daily_usage WHERE usage_date=?",
            (today_str,)
        ).fetchone()
        analysis_count = row['total'] if row else 0

        # 당일 보고서 출력 건수
        row2 = conn.execute(
            "SELECT COUNT(*) as cnt FROM reports WHERE date(created_at)=?",
            (today_str,)
        ).fetchone()
        report_count = row2['cnt'] if row2 else 0

        return {
            "success": True,
            "data": {
                "analysis_count": analysis_count,
                "report_count": report_count
            }
        }
    except Exception as e:
        logger.error(f"[today-stats] {e}")
        return {"success": True, "data": {"analysis_count": 0, "report_count": 0}}
    finally:
        conn.close()
