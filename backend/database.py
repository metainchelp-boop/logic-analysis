"""
로직 분석 프로그램 v2 - 데이터베이스 모듈
SQLite 기반 상품/키워드/순위/경쟁자/알림 CRUD
"""
import sqlite3
import os
import json
import gzip
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")

# 쇼핑검색 크롤 공유 캐시 TTL(초) — 기본 3시간.
# 여러 직원/워커가 같은 키워드를 짧은 시간 내 분석할 때 네이버 재호출을 없애
# 일일 API 한도(25,000) 소진을 막는다. (운영자 지시 2026-07-10)
SHOPPING_CACHE_TTL = int(os.getenv("SHOPPING_CACHE_TTL", "10800"))


def _get_conn() -> sqlite3.Connection:
    """SQLite 연결 생성 (WAL 모드, row_factory 설정)"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    """데이터베이스 초기화 - 테이블 생성"""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tracked_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_url TEXT NOT NULL,
                product_name TEXT DEFAULT '',
                store_name TEXT DEFAULT '',
                image_url TEXT DEFAULT '',
                price INTEGER DEFAULT 0,
                product_id TEXT DEFAULT '',
                user_id INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS tracked_keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (product_id) REFERENCES tracked_products(id) ON DELETE CASCADE,
                UNIQUE(product_id, keyword)
            );

            CREATE TABLE IF NOT EXISTS rankings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                keyword_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                rank_position INTEGER,
                page_number INTEGER,
                check_type TEXT DEFAULT 'scheduled',
                checked_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (product_id) REFERENCES tracked_products(id) ON DELETE CASCADE,
                FOREIGN KEY (keyword_id) REFERENCES tracked_keywords(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS competitor_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword_id INTEGER NOT NULL,
                rank INTEGER NOT NULL,
                product_id TEXT DEFAULT '',
                product_name TEXT DEFAULT '',
                store_name TEXT DEFAULT '',
                price INTEGER DEFAULT 0,
                image_url TEXT DEFAULT '',
                product_url TEXT DEFAULT '',
                review_count INTEGER DEFAULT 0,
                rating REAL DEFAULT 0,
                captured_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (keyword_id) REFERENCES tracked_keywords(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS notification_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                notify_enabled INTEGER DEFAULT 0,
                receiver_phone TEXT DEFAULT '',
                report_time TEXT DEFAULT '09:00',
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS notification_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_type TEXT DEFAULT 'report',
                status TEXT DEFAULT 'success',
                message TEXT DEFAULT '',
                receiver_phone TEXT DEFAULT '',
                sent_at TEXT DEFAULT (datetime('now', 'localtime'))
            );

            -- 인덱스
            CREATE INDEX IF NOT EXISTS idx_rankings_keyword_id ON rankings(keyword_id);
            CREATE INDEX IF NOT EXISTS idx_rankings_checked_at ON rankings(checked_at);
            CREATE INDEX IF NOT EXISTS idx_competitor_keyword_id ON competitor_snapshots(keyword_id);
            CREATE INDEX IF NOT EXISTS idx_notification_logs_sent_at ON notification_logs(sent_at);
            CREATE INDEX IF NOT EXISTS idx_tracked_products_user_id ON tracked_products(user_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tracked_products_url_user ON tracked_products(product_url, user_id);

            -- v3.9.6 성능 인덱스 (clients/client_analyses/client_rank_history 인덱스는 각 모듈 init에서 생성)

            -- API 사용량 로그 (v3.9.13)
            CREATE TABLE IF NOT EXISTS api_usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL DEFAULT 'feedback-all',
                keyword TEXT DEFAULT '',
                client_name TEXT DEFAULT '',
                client_id INTEGER DEFAULT 0,
                call_type TEXT DEFAULT 'manual',
                model TEXT DEFAULT '',
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0,
                cost_krw INTEGER DEFAULT 0,
                user_id INTEGER DEFAULT 0,
                status TEXT DEFAULT 'success',
                error_message TEXT DEFAULT '',
                called_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_api_usage_called_at ON api_usage_logs(called_at);
            CREATE INDEX IF NOT EXISTS idx_api_usage_client ON api_usage_logs(client_id);

            -- 쇼핑검색 크롤 공유 캐시 (v6.4) — 같은 키워드 크롤 결과를 TTL 동안 공유해
            -- 네이버 쇼핑 API 중복 호출을 제거(일일 한도 소진 방지). payload=gzip(JSON).
            -- 워커별 메모리 캐시로는 5개 워커가 각자 긁으므로, DB에 두어 워커·재시작을 넘어 공유.
            CREATE TABLE IF NOT EXISTS shopping_search_cache (
                cache_key TEXT PRIMARY KEY,
                keyword TEXT NOT NULL,
                max_results INTEGER NOT NULL,
                sort TEXT DEFAULT 'sim',
                payload BLOB NOT NULL,
                product_count INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_shopping_cache_created ON shopping_search_cache(created_at);

            -- 플레이스(지역 검색) 순위 이력 (v6.6) — 플레이스는 서버 크롤이 불가(GPS 개인화·차단)해
            -- 직원 캡처로만 순위가 확보된다. 분석할 때마다 (업체·키워드) 순위를 하루 1점으로 누적해
            -- 일자별 추적 차트(§2)를 그린다. rank_position NULL = 미노출/미확인(state로 구분).
            CREATE TABLE IF NOT EXISTS place_rank_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_key TEXT NOT NULL,
                business_name TEXT DEFAULT '',
                region TEXT DEFAULT '',
                keyword TEXT NOT NULL,
                rank_position INTEGER,
                rank_state TEXT DEFAULT '',
                user_id INTEGER DEFAULT 0,
                checked_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_place_rank_bk_kw ON place_rank_history(business_key, keyword, checked_at);

            -- 플레이스 무인 추적 레지스트리 (v6.7) — 확장 프로그램(플레이스 순위 추적기)이 매일
            -- 자동 수집할 (업체 × 키워드) 목록. 키워드는 항상 지역 포함(스파이크 검증: 지역이
            -- 검색어에 있으면 오가닉 순위가 검색 위치와 무관하게 재현됨 — 2026-08-04 실측).
            -- place_id 는 첫 노출 시 자동 채움(self-heal) → business_key 'doc:' 계열로 승격.
            CREATE TABLE IF NOT EXISTS place_track_target (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_name TEXT NOT NULL,
                region TEXT DEFAULT '',
                place_id TEXT DEFAULT '',
                keyword TEXT NOT NULL,
                active INTEGER DEFAULT 1,
                created_by INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                UNIQUE(business_name, region, keyword)
            );
            CREATE INDEX IF NOT EXISTS idx_place_track_active ON place_track_target(active);

            -- 알림 설정 기본 행 삽입 (없으면)
            INSERT OR IGNORE INTO notification_settings (id, notify_enabled, receiver_phone, report_time)
            VALUES (1, 0, '', '09:00');
        """)
        conn.commit()
        # v6.3 마이그레이션: rankings.review_count (리뷰 델타 기반 판매추정용)
        try:
            conn.execute("ALTER TABLE rankings ADD COLUMN review_count INTEGER")
            conn.commit()
        except Exception:
            pass  # 이미 존재하면 무시
        logger.info("✅ 데이터베이스 초기화 완료")
    except Exception as e:
        logger.error(f"DB 초기화 실패: {e}")
        raise
    finally:
        conn.close()


# ==================== 플레이스(지역 검색) 순위 이력 ====================

def save_place_rank(business_key: str, keyword: str, rank_position=None,
                    rank_state: str = "", business_name: str = "",
                    region: str = "", user_id: int = 0):
    """플레이스 (업체·키워드) 순위를 하루 1점으로 누적 저장.
    같은 날 재분석 시 그날 값을 최신으로 대체(하루 1점 유지) → 일자별 차트가 깔끔.
    rank_position None = 미노출/미확인(state로 구분)."""
    if not business_key or not keyword:
        return
    conn = _get_conn()
    try:
        # 오늘 같은 (업체·키워드) 점은 최신으로 대체
        conn.execute(
            "DELETE FROM place_rank_history "
            "WHERE business_key = ? AND keyword = ? "
            "AND date(checked_at) = date('now', 'localtime')",
            (business_key, keyword)
        )
        conn.execute(
            "INSERT INTO place_rank_history "
            "(business_key, business_name, region, keyword, rank_position, rank_state, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (business_key, business_name or "", region or "", keyword,
             rank_position, rank_state or "", user_id or 0)
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"플레이스 순위 저장 실패(무시): {e}")
    finally:
        conn.close()


def get_place_rank_history(business_key: str, keyword: str, days: int = 30) -> List[Dict]:
    """(업체·키워드) 일자별 순위 시계열. 하루 1점(최신)으로 정규화해 오름차순 반환.
    반환: [{date:'YYYY-MM-DD', rank:int|None, state:str}]"""
    if not business_key or not keyword:
        return []
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT date(checked_at) AS d, rank_position, rank_state, checked_at "
            "FROM place_rank_history "
            "WHERE business_key = ? AND keyword = ? "
            "AND date(checked_at) >= date('now', 'localtime', ?) "
            "ORDER BY checked_at ASC",
            (business_key, keyword, f"-{int(days)} days")
        ).fetchall()
        # 날짜별 최신 1점
        by_day = {}
        for r in rows:
            by_day[r["d"]] = {"date": r["d"], "rank": r["rank_position"], "state": r["rank_state"] or ""}
        return [by_day[d] for d in sorted(by_day.keys())]
    except Exception as e:
        logger.warning(f"플레이스 순위 이력 조회 실패(무시): {e}")
        return []
    finally:
        conn.close()


def get_place_tracked_keywords(business_key: str) -> List[Dict]:
    """업체가 지금까지 분석(추적)한 키워드 목록 + 각 키워드의 최신 순위/상태.
    §2 키워드 노출 칩 렌더용. 반환: [{keyword, rank, state, checked_at}] (최신 분석 순)."""
    if not business_key:
        return []
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT keyword, rank_position, rank_state, checked_at FROM place_rank_history p "
            "WHERE business_key = ? AND checked_at = ("
            "    SELECT MAX(checked_at) FROM place_rank_history "
            "    WHERE business_key = p.business_key AND keyword = p.keyword) "
            "ORDER BY checked_at DESC",
            (business_key,)
        ).fetchall()
        return [{"keyword": r["keyword"], "rank": r["rank_position"],
                 "state": r["rank_state"] or "", "checked_at": r["checked_at"]} for r in rows]
    except Exception as e:
        logger.warning(f"플레이스 추적 키워드 조회 실패(무시): {e}")
        return []
    finally:
        conn.close()


# ==================== 플레이스 무인 추적 레지스트리 (v6.7) ====================

def add_place_track_targets(business_name: str, region: str, keywords: List[str],
                            place_id: str = "", user_id: int = 0) -> int:
    """추적 대상 (업체 × 키워드) 행 추가. 중복(업체·지역·키워드)은 조용히 무시.
    반환: 실제 추가된 행 수."""
    if not business_name or not keywords:
        return 0
    conn = _get_conn()
    added = 0
    try:
        for kw in keywords:
            kw = (kw or "").strip()
            if not kw:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO place_track_target "
                "(business_name, region, place_id, keyword, active, created_by) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (business_name.strip(), (region or "").strip(), (place_id or "").strip(), kw, user_id or 0)
            )
            added += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
        return added
    except Exception as e:
        logger.warning(f"플레이스 추적 대상 추가 실패(무시): {e}")
        return added
    finally:
        conn.close()


def list_place_track_targets(active_only: bool = False) -> List[Dict]:
    """추적 대상 전체 목록(등록순). active_only=True 면 활성만(확장 러너용)."""
    conn = _get_conn()
    try:
        sql = ("SELECT id, business_name, region, place_id, keyword, active, created_at "
               "FROM place_track_target ")
        if active_only:
            sql += "WHERE active = 1 "
        sql += "ORDER BY business_name, region, id"
        rows = conn.execute(sql).fetchall()
        return [{"id": r["id"], "business_name": r["business_name"], "region": r["region"] or "",
                 "place_id": r["place_id"] or "", "keyword": r["keyword"],
                 "active": bool(r["active"]), "created_at": r["created_at"]} for r in rows]
    except Exception as e:
        logger.warning(f"플레이스 추적 대상 조회 실패(무시): {e}")
        return []
    finally:
        conn.close()


def set_place_track_target_active(target_id: int, active: bool) -> bool:
    """추적 대상 활성/일시중지 토글."""
    conn = _get_conn()
    try:
        conn.execute("UPDATE place_track_target SET active = ? WHERE id = ?",
                     (1 if active else 0, int(target_id)))
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"플레이스 추적 대상 토글 실패(무시): {e}")
        return False
    finally:
        conn.close()


def delete_place_track_target(target_id: int) -> bool:
    """추적 대상 행 삭제(순위 이력 place_rank_history 는 보존 — 재등록 시 이어짐)."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM place_track_target WHERE id = ?", (int(target_id),))
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"플레이스 추적 대상 삭제 실패(무시): {e}")
        return False
    finally:
        conn.close()


def heal_place_track_target_place_id(target_id: int, place_id: str) -> None:
    """첫 노출 시 발견된 place_id 를 레지스트리에 채움(self-heal).
    이미 값이 있으면 건드리지 않음 — 수동 지정 우선."""
    if not place_id:
        return
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE place_track_target SET place_id = ? "
            "WHERE id = ? AND (place_id IS NULL OR place_id = '')",
            (str(place_id).strip(), int(target_id))
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"플레이스 추적 place_id self-heal 실패(무시): {e}")
    finally:
        conn.close()


# ==================== 상품 CRUD ====================

def add_tracked_product(product_url: str, product_name: str = None,
                        store_name: str = None, image_url: str = None,
                        price: int = None, product_id: str = None,
                        user_id: int = 0) -> int:
    """추적 상품 등록, 중복이면 업데이트 후 ID 반환 (user_id별 격리, 레이스 컨디션 방지)"""
    conn = _get_conn()
    try:
        # 기존 상품 확인 (URL + user_id 기준)
        row = conn.execute(
            "SELECT id FROM tracked_products WHERE product_url = ? AND user_id = ?",
            (product_url, user_id)
        ).fetchone()

        if row:
            # 이미 있으면 정보 업데이트
            conn.execute("""
                UPDATE tracked_products SET
                    product_name = COALESCE(?, product_name),
                    store_name = COALESCE(?, store_name),
                    image_url = COALESCE(?, image_url),
                    price = COALESCE(?, price),
                    product_id = COALESCE(?, product_id),
                    updated_at = datetime('now', 'localtime')
                WHERE id = ?
            """, (product_name, store_name, image_url, price, product_id, row["id"]))
            conn.commit()
            return row["id"]
        else:
            cursor = conn.execute("""
                INSERT INTO tracked_products
                    (product_url, product_name, store_name, image_url, price, product_id, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (product_url, product_name or '', store_name or '',
                  image_url or '', price or 0, product_id or '', user_id))
            conn.commit()
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        conn.rollback()
        # 레이스 컨디션으로 중복 삽입된 경우 기존 ID 반환
        row = conn.execute(
            "SELECT id FROM tracked_products WHERE product_url = ? AND user_id = ?",
            (product_url, user_id)
        ).fetchone()
        return row["id"] if row else 0
    finally:
        conn.close()


def get_all_tracked_products(user_id: int = None, is_admin: bool = False) -> List[Dict]:
    """추적 중인 상품 목록 (user_id별 격리, admin은 전체 조회)"""
    conn = _get_conn()
    try:
        if is_admin or user_id is None:
            rows = conn.execute(
                "SELECT * FROM tracked_products ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tracked_products WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_tracked_product(product_id: int, user_id: int = None, is_admin: bool = False):
    """추적 상품 삭제 (CASCADE로 키워드/순위/경쟁자 모두 삭제, 소유권 확인)"""
    conn = _get_conn()
    try:
        if is_admin or user_id is None:
            conn.execute("DELETE FROM tracked_products WHERE id = ?", (product_id,))
        else:
            conn.execute("DELETE FROM tracked_products WHERE id = ? AND user_id = ?", (product_id, user_id))
        conn.commit()
    finally:
        conn.close()


# ==================== 키워드 CRUD ====================

def add_tracked_keyword(product_id: int, keyword: str) -> int:
    """키워드 추가 (중복이면 기존 ID 반환)"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM tracked_keywords WHERE product_id = ? AND keyword = ?",
            (product_id, keyword)
        ).fetchone()

        if row:
            return row["id"]

        cursor = conn.execute(
            "INSERT INTO tracked_keywords (product_id, keyword) VALUES (?, ?)",
            (product_id, keyword)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_keywords_for_product(product_id: int) -> List[Dict]:
    """상품의 키워드 목록 (최신 순위 포함)"""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT tk.*,
                   (SELECT r.rank_position FROM rankings r
                    WHERE r.keyword_id = tk.id
                    ORDER BY r.checked_at DESC LIMIT 1) as latest_rank,
                   (SELECT r.checked_at FROM rankings r
                    WHERE r.keyword_id = tk.id
                    ORDER BY r.checked_at DESC LIMIT 1) as last_checked
            FROM tracked_keywords tk
            WHERE tk.product_id = ?
            ORDER BY tk.created_at ASC
        """, (product_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_keyword_product_and_count(keyword_id: int) -> Optional[Dict]:
    """키워드의 소속 상품 ID와 그 상품의 총 키워드 수를 반환 (키워드 없으면 None).
    개별 삭제 시 '마지막 1개 보호' 판정에 사용."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT product_id FROM tracked_keywords WHERE id = ?", (keyword_id,)
        ).fetchone()
        if not row:
            return None
        pid = row["product_id"]
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM tracked_keywords WHERE product_id = ?", (pid,)
        ).fetchone()["c"]
        return {"product_id": pid, "count": cnt}
    finally:
        conn.close()


def delete_tracked_keyword(keyword_id: int):
    """추적 키워드 1개 삭제. FK=ON이라 CASCADE로 순위·경쟁자 스냅샷이 함께 지워지나,
    누락 방어를 위해 자식 행을 명시적으로 먼저 삭제한다(같은 커넥션·단일 커밋)."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM rankings WHERE keyword_id = ?", (keyword_id,))
        conn.execute("DELETE FROM competitor_snapshots WHERE keyword_id = ?", (keyword_id,))
        conn.execute("DELETE FROM tracked_keywords WHERE id = ?", (keyword_id,))
        conn.commit()
    finally:
        conn.close()


# ==================== 순위 기록 ====================

def save_ranking(product_id: int, keyword_id: int, keyword: str,
                 rank_position: Optional[int], page_number: Optional[int],
                 check_type: str = "scheduled", review_count: Optional[int] = None):
    """순위 기록 저장 (review_count: 리뷰 델타 추정용, 없으면 None)"""
    conn = _get_conn()
    try:
        try:
            # review_count 컬럼 포함 저장
            conn.execute("""
                INSERT INTO rankings
                    (product_id, keyword_id, keyword, rank_position, page_number, check_type, review_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (product_id, keyword_id, keyword, rank_position, page_number, check_type, review_count))
        except Exception:
            # 구버전 DB(컬럼 없음) 폴백 — 순위는 반드시 저장
            conn.execute("""
                INSERT INTO rankings
                    (product_id, keyword_id, keyword, rank_position, page_number, check_type)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (product_id, keyword_id, keyword, rank_position, page_number, check_type))
        conn.commit()
    finally:
        conn.close()


def get_ranking_history(keyword_id: int, days: int = 30) -> List[Dict]:
    """키워드별 순위 이력 조회"""
    conn = _get_conn()
    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute("""
            SELECT * FROM rankings
            WHERE keyword_id = ? AND checked_at >= ?
            ORDER BY checked_at ASC
        """, (keyword_id, since)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_latest_ranking_for_keyword(keyword_id: int) -> Optional[Dict]:
    """키워드의 최신 순위 1건"""
    conn = _get_conn()
    try:
        row = conn.execute("""
            SELECT * FROM rankings
            WHERE keyword_id = ?
            ORDER BY checked_at DESC LIMIT 1
        """, (keyword_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_previous_ranking_for_keyword(keyword_id: int) -> Optional[Dict]:
    """키워드의 이전 순위 (최신 바로 전)"""
    conn = _get_conn()
    try:
        row = conn.execute("""
            SELECT * FROM rankings
            WHERE keyword_id = ?
            ORDER BY checked_at DESC LIMIT 1 OFFSET 1
        """, (keyword_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ==================== 경쟁 상품 스냅샷 ====================

def save_competitor_snapshot(keyword_id: int, competitors: List[Dict]):
    """경쟁 상품 스냅샷 저장 (상위 N개)"""
    conn = _get_conn()
    try:
        for comp in competitors:
            conn.execute("""
                INSERT INTO competitor_snapshots
                    (keyword_id, rank, product_id, product_name, store_name,
                     price, image_url, product_url, review_count, rating)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                keyword_id,
                comp.get("rank", 0),
                comp.get("product_id", ""),
                comp.get("product_name", ""),
                comp.get("store_name", ""),
                comp.get("price", 0),
                comp.get("image_url", ""),
                comp.get("product_url", ""),
                comp.get("review_count", 0),
                comp.get("rating", 0),
            ))
        conn.commit()
    finally:
        conn.close()


def get_latest_competitors(keyword_id: int) -> List[Dict]:
    """키워드별 최신 경쟁 상품 스냅샷"""
    conn = _get_conn()
    try:
        # 가장 최근 captured_at 기준으로 한 세트 가져오기
        latest = conn.execute("""
            SELECT captured_at FROM competitor_snapshots
            WHERE keyword_id = ?
            ORDER BY captured_at DESC LIMIT 1
        """, (keyword_id,)).fetchone()

        if not latest:
            return []

        rows = conn.execute("""
            SELECT * FROM competitor_snapshots
            WHERE keyword_id = ? AND captured_at = ?
            ORDER BY rank ASC
        """, (keyword_id, latest["captured_at"])).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ==================== 알림 설정 ====================

def get_notification_settings() -> Dict:
    """알림 설정 조회"""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM notification_settings WHERE id = 1").fetchone()
        if row:
            d = dict(row)
            d["notify_enabled"] = bool(d.get("notify_enabled", 0))
            return d
        return {
            "id": 1,
            "notify_enabled": False,
            "receiver_phone": "",
            "report_time": "09:00",
            "updated_at": None
        }
    finally:
        conn.close()


def update_notification_settings(notify_enabled: Optional[bool] = None,
                                  receiver_phone: Optional[str] = None,
                                  report_time: Optional[str] = None) -> Dict:
    """알림 설정 업데이트"""
    conn = _get_conn()
    try:
        updates = []
        params = []

        if notify_enabled is not None:
            updates.append("notify_enabled = ?")
            params.append(1 if notify_enabled else 0)
        if receiver_phone is not None:
            updates.append("receiver_phone = ?")
            params.append(receiver_phone)
        if report_time is not None:
            updates.append("report_time = ?")
            params.append(report_time)

        if updates:
            updates.append("updated_at = datetime('now', 'localtime')")
            sql = f"UPDATE notification_settings SET {', '.join(updates)} WHERE id = 1"
            conn.execute(sql, params)
            conn.commit()

        return get_notification_settings()
    finally:
        conn.close()


# ==================== 알림 로그 ====================

def save_notification_log(log_type: str, status: str, message: str,
                          receiver_phone: str = ""):
    """알림 발송 로그 저장"""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO notification_logs (log_type, status, message, receiver_phone)
            VALUES (?, ?, ?, ?)
        """, (log_type, status, message, receiver_phone))
        conn.commit()
    finally:
        conn.close()


def get_notification_logs(limit: int = 20) -> List[Dict]:
    """알림 발송 이력 조회"""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT * FROM notification_logs
            ORDER BY sent_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ==================== 일일 리포트용 데이터 수집 ====================

def get_all_keywords_with_products(user_id: int = None, is_admin: bool = False) -> List[Dict]:
    """모든 키워드와 상품 정보 조인 (user_id별 격리)"""
    conn = _get_conn()
    try:
        if is_admin or user_id is None:
            rows = conn.execute("""
                SELECT tk.id as keyword_id, tk.keyword, tk.product_id,
                       tp.product_name, tp.store_name, tp.product_url
                FROM tracked_keywords tk
                JOIN tracked_products tp ON tk.product_id = tp.id
                ORDER BY tp.id, tk.id
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT tk.id as keyword_id, tk.keyword, tk.product_id,
                       tp.product_name, tp.store_name, tp.product_url
                FROM tracked_keywords tk
                JOIN tracked_products tp ON tk.product_id = tp.id
                WHERE tp.user_id = ?
                ORDER BY tp.id, tk.id
            """, (user_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ==================== API 사용량 로깅 (v3.9.13) ====================

def save_api_usage_log(endpoint: str, keyword: str = "", client_name: str = "",
                       client_id: int = 0, call_type: str = "manual",
                       model: str = "", input_tokens: int = 0, output_tokens: int = 0,
                       cost_usd: float = 0, user_id: int = 0,
                       status: str = "success", error_message: str = ""):
    """API 호출 사용량 기록"""
    total_tokens = input_tokens + output_tokens
    cost_krw = int(cost_usd * 1400)
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO api_usage_logs
            (endpoint, keyword, client_name, client_id, call_type, model,
             input_tokens, output_tokens, total_tokens, cost_usd, cost_krw,
             user_id, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (endpoint, keyword, client_name, client_id, call_type, model,
              input_tokens, output_tokens, total_tokens, cost_usd, cost_krw,
              user_id, status, error_message))
        conn.commit()
    except Exception as e:
        logger.error(f"API 사용량 로그 저장 실패: {e}")
    finally:
        conn.close()


def get_api_usage_summary(days: int = 30) -> dict:
    """API 사용량 요약 (오늘/이번달/일별 추이)"""
    conn = _get_conn()
    try:
        today = datetime.now().strftime("%Y-%m-%d")

        # 오늘 요약
        today_row = conn.execute("""
            SELECT COUNT(*) as calls,
                   COALESCE(SUM(input_tokens), 0) as input_tokens,
                   COALESCE(SUM(output_tokens), 0) as output_tokens,
                   COALESCE(SUM(cost_krw), 0) as cost_krw
            FROM api_usage_logs
            WHERE date(called_at) = ?
        """, (today,)).fetchone()

        # 이번 달 요약
        month_start = datetime.now().strftime("%Y-%m-01")
        month_row = conn.execute("""
            SELECT COUNT(*) as calls,
                   COALESCE(SUM(input_tokens), 0) as input_tokens,
                   COALESCE(SUM(output_tokens), 0) as output_tokens,
                   COALESCE(SUM(cost_krw), 0) as cost_krw
            FROM api_usage_logs
            WHERE date(called_at) >= ?
        """, (month_start,)).fetchone()

        # 일별 추이
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        daily_rows = conn.execute("""
            SELECT date(called_at) as day,
                   COUNT(*) as calls,
                   COALESCE(SUM(input_tokens), 0) as input_tokens,
                   COALESCE(SUM(output_tokens), 0) as output_tokens,
                   COALESCE(SUM(cost_krw), 0) as cost_krw
            FROM api_usage_logs
            WHERE date(called_at) >= ?
            GROUP BY date(called_at)
            ORDER BY day
        """, (since,)).fetchall()

        # 업체별 요약 (이번 달)
        client_rows = conn.execute("""
            SELECT client_name, client_id,
                   COUNT(*) as calls,
                   COALESCE(SUM(cost_krw), 0) as cost_krw,
                   COUNT(DISTINCT keyword) as keyword_count
            FROM api_usage_logs
            WHERE date(called_at) >= ? AND client_name != ''
            GROUP BY client_name
            ORDER BY cost_krw DESC
        """, (month_start,)).fetchall()

        # 최근 호출 로그 (최근 50건)
        log_rows = conn.execute("""
            SELECT id, endpoint, keyword, client_name, call_type, model,
                   input_tokens, output_tokens, cost_krw, status, error_message,
                   called_at
            FROM api_usage_logs
            ORDER BY id DESC
            LIMIT 50
        """).fetchall()

        avg_cost = 0
        if dict(month_row)["calls"] > 0:
            avg_cost = int(dict(month_row)["cost_krw"] / dict(month_row)["calls"])

        return {
            "today": dict(today_row),
            "month": dict(month_row),
            "avg_cost": avg_cost,
            "daily_avg_cost": int(dict(month_row)["cost_krw"] / max(days, 1)),
            "daily": [dict(r) for r in daily_rows],
            "clients": [dict(r) for r in client_rows],
            "logs": [dict(r) for r in log_rows],
        }
    finally:
        conn.close()


# ==================== 쇼핑검색 크롤 공유 캐시 (v6.4) ====================
# 목적: 여러 직원(+5개 워커)이 짧은 시간에 같은 키워드를 분석할 때, 네이버 쇼핑 API
#       크롤을 1번만 하고 결과를 공유해 일일 호출 한도(25,000) 소진을 막는다.
# 설계: 실패는 전부 방어적으로 무시 → 캐시가 깨져도 분석 자체는 절대 멈추지 않는다.
#       빈 결과(429 등)는 저장하지 않아 다음 기회에 정상 재크롤된다.

def _shopping_cache_key(keyword: str, max_results: int, sort: str) -> str:
    return f"{sort}|{max_results}|{keyword}"


def get_cached_shopping_search(keyword: str, max_results: int,
                               sort: str = "sim",
                               ttl: Optional[int] = None) -> Optional[List[Dict]]:
    """TTL 내 캐시된 크롤 결과를 반환. 없거나 만료·오류면 None(=미스, 직접 크롤)."""
    ttl = SHOPPING_CACHE_TTL if ttl is None else ttl
    key = _shopping_cache_key(keyword, max_results, sort)
    conn = None
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT payload, created_at FROM shopping_search_cache WHERE cache_key = ?",
            (key,)
        ).fetchone()
        if not row:
            return None
        if (time.time() - float(row["created_at"])) > ttl:
            return None  # 만료 → 미스 취급 (정리는 저장 시 일괄)
        return json.loads(gzip.decompress(row["payload"]).decode("utf-8"))
    except Exception as e:
        logger.warning(f"[크롤캐시] 조회 실패(무시): {e}")
        return None
    finally:
        if conn is not None:
            conn.close()


def save_cached_shopping_search(keyword: str, max_results: int,
                                products: List[Dict], sort: str = "sim") -> None:
    """크롤 결과를 gzip(JSON)으로 저장. 빈 결과는 저장하지 않음. 실패는 무시."""
    if not products:
        return
    key = _shopping_cache_key(keyword, max_results, sort)
    conn = None
    try:
        payload = gzip.compress(json.dumps(products, ensure_ascii=False).encode("utf-8"))
        conn = _get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO shopping_search_cache
                   (cache_key, keyword, max_results, sort, payload, product_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (key, keyword, max_results, sort, payload, len(products), time.time())
        )
        # 오래된 캐시 정리(누적 방지): TTL의 8배(기본 24시간) 넘은 행 삭제
        conn.execute(
            "DELETE FROM shopping_search_cache WHERE created_at < ?",
            (time.time() - SHOPPING_CACHE_TTL * 8,)
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"[크롤캐시] 저장 실패(무시): {e}")
    finally:
        if conn is not None:
            conn.close()
