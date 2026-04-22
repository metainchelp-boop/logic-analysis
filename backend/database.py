"""
로직 분석 프로그램 v2 - 데이터베이스 모듈
SQLite 기반 상품/키워드/순위/경쟁자/알림 CRUD
"""
import sqlite3
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")


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

            -- 알림 설정 기본 행 삽입 (없으면)
            INSERT OR IGNORE INTO notification_settings (id, notify_enabled, receiver_phone, report_time)
            VALUES (1, 0, '', '09:00');
        """)
        conn.commit()
        logger.info("✅ 데이터베이스 초기화 완료")
    except Exception as e:
        logger.error(f"DB 초기화 실패: {e}")
        raise
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


# ==================== 순위 기록 ====================

def save_ranking(product_id: int, keyword_id: int, keyword: str,
                 rank_position: Optional[int], page_number: Optional[int],
                 check_type: str = "scheduled"):
    """순위 기록 저장"""
    conn = _get_conn()
    try:
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
