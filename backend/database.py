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


def _looks_like_timestamp_place_id(v) -> bool:
    """place_id 로 저장된 값이 타임스탬프(YYYYMMDDHHMM)인지 판정.

    화면 extractPlaceId 의 「아무 7자리+ 숫자」 폴백이 등록 시각을 ID 로 오인해 저장한
    실사례 정리용(2026-08-11 — 흑해 202608111048 ×2 · 금정산성 202608111049).
    네이버 플레이스 doc_id 는 통상 7~11자리라 12자리 + 연월일시분 파싱 성공을
    타임스탬프로 본다(오탐 방어: 연도 2020~2035 범위까지 확인)."""
    s = str(v or "").strip()
    if len(s) != 12 or not s.isdigit():
        return False
    try:
        dt = datetime.strptime(s, "%Y%m%d%H%M")
        return 2020 <= dt.year <= 2035
    except ValueError:
        return False


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
        # 플레이스 지표 스냅샷 — 순위와 같은 시점의 방문자/블로그 리뷰·저장수.
        # 맞춤제안서가 이 값을 쓰기 전에는 화면에 **난수(예시)** 가 실측처럼 찍혔다(2026-08-05).
        # 캡처 파싱으로 이미 확보하던 값을 저장만 안 하고 버리고 있던 것.
        for _col in ("visitor_reviews INTEGER", "blog_reviews INTEGER", "saves INTEGER"):
            try:
                conn.execute(f"ALTER TABLE place_rank_history ADD COLUMN {_col}")
                conn.commit()
            except Exception:
                pass  # 이미 존재하면 무시
        # 자동 등록 표시(2026-08-12) — 제안서·분석을 뽑으면 그 업체·키워드가 저절로 추적에 올라간다.
        # 영업사원이 등록 화면을 따로 열 필요가 없게 만드는 대신, 계약으로 이어지지 않은 건이
        # 영원히 쌓이지 않도록 **자동 등록분만** 30일 미사용 시 자동 해제한다.
        # (사람이 직접 등록한 행은 auto_added=0 이라 이 정리에서 제외 — 손으로 넣은 건 손으로 뺀다.)
        for _col in ("auto_added INTEGER DEFAULT 0", "last_used_at TEXT"):
            try:
                conn.execute(f"ALTER TABLE place_track_target ADD COLUMN {_col}")
                conn.commit()
            except Exception:
                pass  # 이미 존재하면 무시
        # 타임스탬프가 place_id 로 잘못 저장된 레지스트리 행 정리(2026-08-11) — 화면의
        # extractPlaceId 가 「아무 7자리+ 숫자」를 ID 로 받아 등록 시각(YYYYMMDDHHMM)이
        # ID 로 들어간 실사례(흑해 202608111048 ×2 · 금정산성 202608111049). 잘못된 값이
        # 남아 있으면 러너가 그 ID 로 정확 매칭을 시도해 영영 못 찾고, self-heal 은
        # **빈 값만** 채우므로 스스로 낫지 않는다 → 여기서 비워 self-heal 재충전을 연다.
        # 자연 멱등 — 조건에 걸리는 행이 없으면 0건.
        try:
            _rows = conn.execute(
                "SELECT id, place_id FROM place_track_target "
                "WHERE place_id IS NOT NULL AND length(place_id) >= 12").fetchall()
            _fixed = 0
            for _r in _rows:
                if _looks_like_timestamp_place_id(_r["place_id"]):
                    conn.execute("UPDATE place_track_target SET place_id = '' WHERE id = ?", (_r["id"],))
                    _fixed += 1
            if _fixed:
                conn.commit()
                logger.info(f"place_track_target 타임스탬프형 place_id {_fixed}건 정리(빈 값 → self-heal 대기)")
        except Exception:
            pass
        logger.info("✅ 데이터베이스 초기화 완료")
    except Exception as e:
        logger.error(f"DB 초기화 실패: {e}")
        raise
    finally:
        conn.close()


# ==================== 플레이스(지역 검색) 순위 이력 ====================

def save_place_rank(business_key: str, keyword: str, rank_position=None,
                    rank_state: str = "", business_name: str = "",
                    region: str = "", user_id: int = 0,
                    visitor_reviews=None, blog_reviews=None, saves=None):
    """플레이스 (업체·키워드) 순위를 하루 1점으로 누적 저장.
    같은 날 재분석 시 그날 값을 최신으로 대체(하루 1점 유지) → 일자별 차트가 깔끔.
    rank_position None = 미노출/미확인(state로 구분).
    visitor_reviews·blog_reviews·saves 는 같은 시점의 지표 스냅샷(없으면 None — 가짜 0 금지).

    ⚠️ **「미확인」은 그날의 실측을 덮지 않는다**(2026-08-12). 종전엔 같은 날 행을 무조건
       지우고 새로 넣어서, 새벽 수집기가 잰 실제 순위가 있어도 낮에 캡처 없이 분석을 한 번
       돌리면 그 기록이 **삭제되고 「미확인」으로 바뀌었다**(실측 소실). 캡처로 못 잰 회차는
       「우리가 안 봤다」는 뜻일 뿐 「없다」가 아니므로, 본 값이 있으면 그쪽이 이긴다.
         · 실측 = 순위가 잡혔거나(노출) 찾아봤는데 없었거나(미노출)
         · 미확인 = 캡처가 없거나 판독 실패 — 아무것도 안 본 상태
       미확인 회차라도 **담당자가 채운 지표(리뷰·저장수)는 기존 행에 병합**한다(입력 유실 방지).
    """
    if not business_key or not keyword:
        return
    MEASURED = ("노출", "미노출")
    incoming_measured = (rank_position is not None
                         or str(rank_state or "").strip() in MEASURED)
    conn = _get_conn()
    try:
        if not incoming_measured:
            prev = conn.execute(
                "SELECT id, rank_position, rank_state FROM place_rank_history "
                "WHERE business_key = ? AND keyword = ? "
                "AND date(checked_at) = date('now', 'localtime') "
                "ORDER BY checked_at DESC LIMIT 1",
                (business_key, keyword)).fetchone()
            prev_measured = bool(prev and (prev["rank_position"] is not None
                                           or str(prev["rank_state"] or "").strip() in MEASURED))
            if prev_measured:
                # 실측 보존 — 순위는 그대로 두고, 이번에 새로 확보된 지표만 채운다.
                sets, vals = [], []
                for col, v in (("visitor_reviews", visitor_reviews),
                               ("blog_reviews", blog_reviews), ("saves", saves)):
                    if v is not None:
                        sets.append(f"{col} = ?")
                        vals.append(v)
                if sets:
                    vals.append(prev["id"])
                    conn.execute(f"UPDATE place_rank_history SET {', '.join(sets)} WHERE id = ?", vals)
                    conn.commit()
                return
        # 오늘 같은 (업체·키워드) 점은 최신으로 대체
        conn.execute(
            "DELETE FROM place_rank_history "
            "WHERE business_key = ? AND keyword = ? "
            "AND date(checked_at) = date('now', 'localtime')",
            (business_key, keyword)
        )
        conn.execute(
            "INSERT INTO place_rank_history "
            "(business_key, business_name, region, keyword, rank_position, rank_state, user_id, "
            " visitor_reviews, blog_reviews, saves) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (business_key, business_name or "", region or "", keyword,
             rank_position, rank_state or "", user_id or 0,
             visitor_reviews, blog_reviews, saves)
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


AUTO_TRACK_STALE_DAYS = 30          # (레거시) 자동 등록분이 이 기간 동안 안 쓰이면 자동 해제


def deactivate_stale_auto_place_targets(days: int = AUTO_TRACK_STALE_DAYS) -> int:
    """(레거시 정리) 자동 등록으로 생긴 행 중 오래 안 쓰인 것을 비활성으로 내린다.

    ⚠️ 자동 등록 기능 자체는 폐지됐다(2026-08-12 대표 확정 — 분석·제안서는 등록하지 않는다.
       스토어와 같은 규칙). 이 잡은 **폐지 전 하루 동안 자동으로 생긴 행**이 쓰이지 않으면
       스스로 사라지게 하려고 남겨 둔다(신규 auto_added=1 행은 더는 생기지 않는다).
    사람이 직접 등록한 행(auto_added=0)은 **건드리지 않는다.**
    """
    conn = _get_conn()
    try:
        cur = conn.execute(
            "UPDATE place_track_target SET active = 0 "
            "WHERE COALESCE(auto_added, 0) = 1 AND active = 1 "
            "AND COALESCE(last_used_at, created_at) < datetime('now', 'localtime', ?)",
            (f"-{int(days)} days",))
        conn.commit()
        n = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        if n:
            logger.info(f"플레이스 자동 등록 추적 대상 {n}건 비활성(마지막 사용 {days}일 초과)")
        return n
    except Exception as e:
        logger.warning(f"플레이스 자동 등록 정리 실패(무시): {e}")
        return 0
    finally:
        conn.close()


def list_place_track_targets(active_only: bool = False, user_id: int = None,
                             is_admin: bool = False) -> List[Dict]:
    """추적 대상 목록(등록순). active_only=True 면 활성만(확장 러너 동기화용).
    user_id별 격리 — 스토어 tracked_products(get_all_tracked_products)와 동일 규칙:
    본인 등록분만, admin/superadmin 또는 user_id 미지정(내부·러너 경로)은 전체."""
    conn = _get_conn()
    try:
        sql = ("SELECT id, business_name, region, place_id, keyword, active, created_at, created_by "
               "FROM place_track_target ")
        conds, params = [], []
        if active_only:
            conds.append("active = 1")
        if not is_admin and user_id is not None:
            conds.append("created_by = ?")
            params.append(int(user_id))
        if conds:
            sql += "WHERE " + " AND ".join(conds) + " "
        sql += "ORDER BY business_name, region, id"
        rows = conn.execute(sql, params).fetchall()
        return [{"id": r["id"], "business_name": r["business_name"], "region": r["region"] or "",
                 "place_id": r["place_id"] or "", "keyword": r["keyword"],
                 "active": bool(r["active"]), "created_at": r["created_at"],
                 "created_by": r["created_by"]} for r in rows]
    except Exception as e:
        logger.warning(f"플레이스 추적 대상 조회 실패(무시): {e}")
        return []
    finally:
        conn.close()


def find_place_track_place_id(business_name: str, region: str = "") -> str:
    """업체명(+지역)으로 추적 레지스트리에서 플레이스 ID 를 찾는다.

    ⚠️ 왜 필요한가(2026-08-05 실측): 무인 수집은 순위를 `doc:{place_id}` 키로 저장하는데
    (`_place_registry_business_key` — place_id 가 있으면 항상 doc: 우선), 맞춤제안서는
    업체명·지역만 받으므로 `nm:{이름}|{지역}` 키로 조회해 **등록된 업체인데도 순위 이력이
    0건**으로 나왔다. 등록된 대상은 대부분 place_id 를 갖고 있어 두 키가 영영 안 만난다.
    → 제안서가 조회 전에 이 함수로 place_id 를 찾아 doc: 키를 우선 시도하게 한다.

    이름은 공백·대소문자를 무시하고 비교하며, 지역이 주어지면 지역까지 맞는 행을 우선한다.
    못 찾으면 빈 문자열(호출부는 기존 nm: 키로 폴백)."""
    name_n = "".join(str(business_name or "").split()).lower()
    if not name_n:
        return ""
    reg_n = "".join(str(region or "").split()).lower()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT business_name, region, place_id FROM place_track_target "
            "WHERE place_id IS NOT NULL AND place_id <> ''").fetchall()
        near, loose = "", ""
        for r in rows:
            rn = "".join(str(r["business_name"] or "").split()).lower()
            if rn != name_n:
                continue
            rr = "".join(str(r["region"] or "").split()).lower()
            if reg_n and rr == reg_n:
                return str(r["place_id"])          # 이름·지역 모두 일치 — 최우선
            # 지역 표기만 다른 같은 동네(성수동 ⊂ 서울성동구성수동) — 정확 일치 다음 순위.
            # 두 화면의 지역 안내가 서로 다른 값을 유도해 생기는 불일치를 여기서 흡수한다.
            if reg_n and rr and (rr in reg_n or reg_n in rr):
                near = near or str(r["place_id"])
            loose = loose or str(r["place_id"])     # 이름만 일치 — 마지막 폴백
        return near or loose
    except Exception as e:
        logger.warning(f"플레이스 추적 ID 조회 실패(무시): {e}")
        return ""
    finally:
        conn.close()


def is_place_tracked(business_name: str, region: str = "", place_id: str = "") -> bool:
    """이 업체가 **지도 순위 추적에 등록돼 있는지**(활성 행 존재) — 등록 여부만 본다.

    ⚠️ 「순위 기록이 있는지」와 다른 질문이다. 순위 칸이 빈 이유가
       ⑴ 아예 등록이 안 됐다 ⑵ 등록은 됐는데 아직 첫 수집 전이다 로 갈리는데,
       기록(place_rank_history)만 보면 둘이 똑같아 보인다(2026-08-12).
    이름 비교는 공백·대소문자 무시, 지역은 서로 포함하면 같은 동네로 본다
    (find_place_track_place_id 와 같은 규칙 — 두 화면의 지역 표기 차이 흡수)."""
    pid = str(place_id or "").strip()
    name_n = "".join(str(business_name or "").split()).lower()
    if not pid and not name_n:
        return False
    reg_n = "".join(str(region or "").split()).lower()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT business_name, region, place_id FROM place_track_target WHERE active = 1").fetchall()
        for r in rows:
            if pid and str(r["place_id"] or "").strip() == pid:
                return True
            rn = "".join(str(r["business_name"] or "").split()).lower()
            if not name_n or rn != name_n:
                continue
            rr = "".join(str(r["region"] or "").split()).lower()
            if not reg_n or not rr or rr == reg_n or rr in reg_n or reg_n in rr:
                return True
        return False
    except Exception as e:
        logger.warning(f"플레이스 추적 등록 여부 조회 실패(무시): {e}")
        return False
    finally:
        conn.close()


def resolve_place_business_key(business_name: str, region: str = "") -> str:
    """수동 분석(「플레이스 분석」) 기록에서 그 업체의 실제 `nm:` 키를 찾는다.

    ⚠️ 왜 필요한가(2026-08-05): 키가 `nm:{정규화명}|{정규화지역}` 이라 **지역을 어떻게 적었는지가
    곧 키**인데, 두 화면의 안내가 서로 다른 값을 유도했다 —
        「플레이스 분석」  지역 (동/구/시/군)  예: 서울 성동구 성수동   (선택)
        맞춤제안서        지역 *              예: 성수동              (필수)
    안내를 각각 그대로 따르면 `…|서울성동구성수동` 과 `…|성수동` 이 되어 **다른 업체로 인식**되고,
    분석을 해 뒀는데도 순위·리뷰·저장수가 영영 안 붙는다. 영업사원에겐 「분석했는데 왜 안 나오지」로만
    보이는 함정이라, **사람이 표기를 맞추는 방어 대신 코드가 흡수**한다.

    순서: ① 정확 일치 → ② 이름이 같고 지역이 서로를 포함(성수동 ⊂ 서울성동구성수동) → ③ 이름만 일치.
    ②③ 은 후보가 여럿이면 가장 최근 기록을 쓴다. 못 찾으면 빈 문자열(호출부가 정확 키로 폴백).
    ⚠️ 이름이 아예 다르면 절대 매칭하지 않는다 — 엉뚱한 업체 자료가 제안서에 실리는 것이 미노출보다 나쁘다."""
    name_n = "".join(str(business_name or "").split()).lower()
    if not name_n:
        return ""
    reg_n = "".join(str(region or "").split()).lower()
    exact = f"nm:{name_n}|{reg_n}"
    prefix = f"nm:{name_n}|"
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT business_key, MAX(checked_at) AS last_at FROM place_rank_history "
            "WHERE business_key LIKE ? GROUP BY business_key ORDER BY last_at DESC",
            (prefix + "%",)
        ).fetchall()
        if not rows:
            return ""
        keys = [str(r["business_key"]) for r in rows]      # 최근 기록 순
        if exact in keys:
            return exact
        if reg_n:
            for k in keys:                                  # 지역 표기만 다른 같은 동네
                kr = k[len(prefix):]
                if kr and (kr in reg_n or reg_n in kr):
                    return k
        return keys[0]                                      # 이름만 일치 — 가장 최근 기록
    except Exception as e:
        logger.warning(f"플레이스 업체 키 해석 실패(무시): {e}")
        return ""
    finally:
        conn.close()


def set_place_track_target_active(target_id: int, active: bool, user_id: int = None,
                                  is_admin: bool = False) -> bool:
    """추적 대상 활성/일시중지 토글 — 본인 등록분만(admin 전체, 스토어 삭제 규칙과 동일)."""
    conn = _get_conn()
    try:
        if is_admin or user_id is None:
            cur = conn.execute("UPDATE place_track_target SET active = ? WHERE id = ?",
                               (1 if active else 0, int(target_id)))
        else:
            cur = conn.execute(
                "UPDATE place_track_target SET active = ? WHERE id = ? AND created_by = ?",
                (1 if active else 0, int(target_id), int(user_id)))
        conn.commit()
        return bool(cur.rowcount and cur.rowcount > 0)
    except Exception as e:
        logger.warning(f"플레이스 추적 대상 토글 실패(무시): {e}")
        return False
    finally:
        conn.close()


def delete_place_track_target(target_id: int, user_id: int = None, is_admin: bool = False) -> bool:
    """추적 대상 행 삭제(순위 이력 place_rank_history 는 보존 — 재등록 시 이어짐).
    본인 등록분만(admin 전체 — 스토어 delete_tracked_product 와 동일 규칙)."""
    conn = _get_conn()
    try:
        if is_admin or user_id is None:
            cur = conn.execute("DELETE FROM place_track_target WHERE id = ?", (int(target_id),))
        else:
            cur = conn.execute("DELETE FROM place_track_target WHERE id = ? AND created_by = ?",
                               (int(target_id), int(user_id)))
        conn.commit()
        return bool(cur.rowcount and cur.rowcount > 0)
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


def save_ranking_daily(product_id: int, keyword_id: int, keyword: str,
                       rank_position: Optional[int], page_number: Optional[int],
                       check_type: str = "scheduled", review_count: Optional[int] = None):
    """순위 기록 저장 — **하루 1점**(같은 상품·키워드·유형이면 그날 것을 갱신).

    24시간 분산 수집(2026-08-05)으로 순위를 '수집되는 즉시' 적기 시작하면서 필요해졌다.
    종전 save_ranking 은 그냥 INSERT 라, 같은 날 두 경로(수집 즉시 기록 + 08:00 배치)가
    모두 쓰면 같은 날짜에 행이 둘 생겨 추이 그래프가 중복 점을 그린다.
    업체 쪽(client_rank_history)이 이미 쓰던 '당일 upsert' 규칙을 상품 쪽에도 맞춘 것.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT id FROM rankings
                WHERE product_id=? AND keyword_id=? AND check_type=?
                  AND DATE(checked_at)=DATE('now','localtime')
                ORDER BY id DESC LIMIT 1""",
            (product_id, keyword_id, check_type)).fetchone()
        if row:
            try:
                conn.execute(
                    """UPDATE rankings
                          SET rank_position=?, page_number=?, review_count=?,
                              checked_at=datetime('now','localtime')
                        WHERE id=?""",
                    (rank_position, page_number, review_count, row["id"]))
            except Exception:
                conn.execute(
                    """UPDATE rankings
                          SET rank_position=?, page_number=?,
                              checked_at=datetime('now','localtime')
                        WHERE id=?""",
                    (rank_position, page_number, row["id"]))
            conn.commit()
            return
    except Exception as e:
        logger.warning(f"순위 당일 갱신 조회 실패(신규 저장으로 진행): {e}")
    finally:
        conn.close()
    save_ranking(product_id, keyword_id, keyword, rank_position, page_number,
                 check_type, review_count)


def heal_tracked_product_info(db_product_id: int, product_url: str, prods: List[Dict]) -> bool:
    """수집 SERP에서 매칭된 아이템의 실제 스토어명·상품명으로 표시 정보를 보정한다.

    쇼핑 검색 API 종료(2026-07-31) 후 등록 시 스토어명 확보가 실패하면 URL 슬러그
    (스토어 아이디)가 store_name 에 그대로 저장되는 문제(직원 오류신고 2026-08-04)의
    자가치유 지점 — 순위 체크가 상품을 찾은 순간엔 mallName(실제 스토어명)이 손에
    있으므로 공짜로 고칠 수 있다. 슬러그이거나 빈 값일 때만 교체(정상 이름은 불변)."""
    try:
        from naver_crawler import extract_product_id_from_url, extract_store_name_from_url
        pid = extract_product_id_from_url(product_url) or ""
        slug = (extract_store_name_from_url(product_url) or "").strip()
        item = None
        for p in prods or []:
            p_pid = str(p.get("product_id") or "")
            p_url = str(p.get("product_url") or "")
            if pid and (pid == p_pid or pid in p_url):
                item = p
                break
        if not item:
            return False
        real_store = (item.get("store_name") or "").strip()
        real_name = (item.get("product_name") or "").strip()
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT store_name, product_name FROM tracked_products WHERE id=?",
                (db_product_id,)).fetchone()
            if not row:
                return False
            cur_store = (row["store_name"] or "").strip()
            cur_name = (row["product_name"] or "").strip()
            sets, vals = [], []
            if (real_store and real_store.lower() != slug.lower()
                    and (not cur_store or cur_store.lower() == slug.lower())):
                sets.append("store_name=?"); vals.append(real_store)
            if real_name and not cur_name:
                sets.append("product_name=?"); vals.append(real_name)
            if not sets:
                return False
            vals.append(db_product_id)
            conn.execute("UPDATE tracked_products SET " + ", ".join(sets)
                         + ", updated_at=datetime('now','localtime') WHERE id=?", vals)
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:
        return False


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


def get_place_latest_metrics(business_key: str, keyword: str = "", days: int = 120) -> Dict:
    """(업체) 최신 지표 스냅샷 — 방문자 리뷰·블로그 리뷰·저장수.

    맞춤제안서가 쓰던 값이 난수(예시)였던 것을 실측으로 바꾸기 위한 조회(2026-08-05).
    · 키워드를 주면 그 키워드 기록을 우선 보고, 없으면 같은 업체의 아무 키워드나 본다
      (지표는 키워드와 무관한 업체 속성이라 최신 1건이면 충분).
    · 지표마다 **각각 가장 최근에 값이 있는 기록**을 쓴다 — 저장수는 담당자 입력이라
      리뷰보다 드물게 채워지므로, 한 행만 보면 있는 값도 버리게 된다.
    · 값이 없으면 키를 빼고 반환(가짜 0 금지 → 제안서가 '—' 로 표시).
    """
    out = {}
    if not business_key:
        return out
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT keyword, visitor_reviews, blog_reviews, saves, checked_at "
            "FROM place_rank_history "
            "WHERE business_key = ? "
            "AND date(checked_at) >= date('now', 'localtime', ?) "
            "ORDER BY checked_at DESC",
            (business_key, f"-{int(days)} days")
        ).fetchall()
        kw = (keyword or "").strip()
        for scope in ("kw", "any"):
            for r in rows:
                if scope == "kw" and (not kw or r["keyword"] != kw):
                    continue
                for col in ("visitor_reviews", "blog_reviews", "saves"):
                    if col not in out and r[col] is not None:
                        out[col] = int(r[col])
            if len(out) == 3:
                break
        return out
    except Exception as e:
        logger.warning(f"플레이스 지표 조회 실패(무시): {e}")
        return {}
    finally:
        conn.close()
