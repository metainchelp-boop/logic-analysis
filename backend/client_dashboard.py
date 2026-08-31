"""
업체별 분석 관리 대시보드 API
v3.4 — 분석→업체 등록 연동, 일자별 분석 누적, 사용자 격리
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime, date, timedelta
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


def _days_left(expires_at):
    """expires_at(문자열) → 자동삭제까지 남은 일수(정수, 0 이상). 없으면 None."""
    if not expires_at:
        return None
    try:
        left = (datetime.strptime(str(expires_at)[:10], "%Y-%m-%d") - datetime.now()).days
        return max(0, left)
    except Exception:
        return None


def _verify_client_access(conn, client_id: int, current_user: dict):
    """업체 소유권 확인. admin은 통과, manager는 created_by 확인,
    viewer(영업사원)는 본인이 등록한 영업 대상·경쟁사만(완전 개인 모드).
    업체가 없으면 404, 권한 없으면 403 반환."""
    row = conn.execute("SELECT id, created_by FROM clients WHERE id = ?", (client_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")
    if _is_admin(current_user):
        return row
    # viewer(영업사원)는 완전 개인 모드 — 본인이 등록한 업체만 접근(관리팀 광고주 비노출).
    if current_user.get("role") == "viewer":
        if row["created_by"] != current_user.get("id"):
            raise HTTPException(status_code=403, detail="본인이 등록한 영업 대상만 볼 수 있습니다.")
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

            -- 키워드별 상품 등록부 (2026-08-21, 이예은 신고)
            -- 종전엔 업체당 상품 주소가 하나(clients.naver_store_url)뿐이라, 한 업체가 상품 둘을
            -- 각각 다른 키워드로 추적하면 08:30 자동분석이 두 키워드 모두 '첫 상품' 으로 검사해
            -- 두 번째 상품 키워드가 매일 「미노출」로 기록됐다(오류 없이 그럴듯한 틀린 답).
            -- 여기에 적힌 게 있으면 그 주소를, 없으면 종전대로 업체 주소를 쓴다(무회귀).
            CREATE TABLE IF NOT EXISTS client_keyword_product (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                product_url TEXT NOT NULL,
                updated_by INTEGER,
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(client_id, keyword),
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

        # my-clients 가 매번 도는 두 쿼리를 **행 본문에 손대지 않고** 끝내기 위한 커버링 인덱스.
        #
        # 왜 필요한가(2026-08-31 서버 A/B 실측):
        #   집계  (client_id·COUNT·MAX(updated_at)·DISTINCT keyword·DISTINCT analyzed_date)
        #        → 290ms. 여기서 keyword 하나만 빼면 4ms.
        #   최신1건(client_id·keyword·product_url·analyzed_date·updated_at)
        #        → 563ms. keyword·product_url 을 빼면 13ms.
        #   위 idx_client_analyses_recent 에 keyword·product_url 이 없어, 그 두 칸 때문에
        #   18,949행마다 행 본문을 찾아간다. client_analyses 는 덩어리 다섯 칸(analysis_json
        #   19KB·report_html 11KB 등)을 안고 있어, 그 길이 곧 비용이다
        #   (8/30 업체 표에서 겪은 것과 같은 일 — 원인이 인덱스가 아니라 **덩어리 통과**다).
        #
        # ⚠️ 칸 순서가 곧 성능이다. 앞 세 칸은 기존 인덱스와 같게 두고(WHERE·ORDER BY 가 그대로
        #    듣는다) keyword·product_url 을 **뒤에** 붙였다 — 앞에 넣으면 client_id 범위 검색이
        #    깨져 오히려 느려진다.
        # ⚠️ 두 칸 중 하나만 넣으면 최신1건은 그대로 느리다. 커버링은 전부 있거나 없거나다.
        # 실측(로컬 복제본 18,949행·381MB): 집계 45→5ms · 최신1건 54→14ms ·
        #    파일 증가 +2MB · 플래너가 COVERING INDEX 로 채택하는 것까지 확인.
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_client_analyses_board
            ON client_analyses(client_id, analyzed_date DESC, updated_at DESC,
                               keyword, product_url)
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
    # 일회성: 「전산에 없음」 17곳 처분(대표 확인 2026-08-28)
    apply_missing_disposition_20260828()
    # 일회성: #591 사업자명 정정(대표 확인 2026-08-29 — 시/쉬 한 글자 차이)
    fix_client_591_bizname_20260829()
    # 일회성: 신요섭 담당 업체를 실제 담당자로 재배정 + 나머지 삭제(사장님 매핑 기준)
    reassign_sinyoseop_clients()


def fix_client_591_bizname_20260829():
    """일회성: #591 사업자명 「서한푸드」→「유성프레시」 (대표 확인 2026-08-29).

    어제 「서한푸드」로 넣었는데 04:00 매칭이 계속 빗나갔다. 대표가 전산에서 직접 확인한
    결과 — 전산 업체명은 「유성프레시」(우리 쪽 표기는 「유성프레쉬」, **시/쉬 한 글자 차이**)
    이고 「서한푸드」는 전산의 주소 필드에 있던 문자열이라 회사명 매칭에 안 걸린다.
    매칭 정규화(_sync_norm)는 공백·대소문자만 다듬지 한글 음절 차이는 못 흡수한다.

    자연 멱등 — 바꾸고 나면 WHERE 가 다시는 안 잡힌다(플래그 불필요).
    ⚠️ 화면 이름(name)은 그대로 둔다 — 직원이 보는 표기를 바꿀 이유가 없다.
    """
    try:
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE clients SET business_name='유성프레시' "
                        "WHERE id=591 AND business_name='서한푸드'")
            if cur.rowcount:
                logger.info("[사업자명정정] #591 서한푸드 → 유성프레시 (다음 04:00 매칭 대상)")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[사업자명정정] 실패(재시도 예정): {e}")


def apply_missing_disposition_20260828():
    """일회성(플래그): 전산에서 계약 단계를 못 받은 광고주 17곳 처분 — 대표 확인 2026-08-28.

    대표가 확인표(HTML)로 한 곳씩 판단한 결과를 그대로 반영한다:
      · 지우기 11곳  → status='terminated' (이 표의 정식 상태값 — 소프트 종료).
                       목록·수집·기록에서 빠지고 **데이터는 전부 보존**된다.
                       ⚠️ 하드 DELETE 금지 — 지우면 그 업체의 순위 기록이 통째로 사라진다.
      · 그대로 5곳   → contract_stage='전산 외 — 대표 확인'.
                       전산 6단계 조회(ad-sync)에 안 잡히는 업체라 단계가 영영 비는데,
                       비워 두면 「삭제 필요」 칸에 계속 남아 매번 다시 확인하게 된다.
                       04:00 동기화는 매칭 실패 시 덮어쓰지 않으므로 이 표시는 유지된다.
      · 이름 맞추기 1곳 → business_name 에 전산 표기를 넣는다.
                       단계 매칭(_match_stage)이 name·business_name 둘 다 보므로
                       화면 이름은 그대로 두고도 다음 04:00 부터 자동 매칭된다.

    ⚠️ 업체는 이름이 아니라 **번호(id)** 로 고른다 — 이 저장소는 공개라 고객 업체명을
       코드에 늘어놓지 않기 위함(번호는 서버 실측으로 확정, 2026-08-28 진단 #71).
    ⚠️ 모든 UPDATE 에 「단계가 비어 있을 때만」 가드 — 번호가 어긋나 이미 전산과
       매칭된 멀쩡한 업체를 건드리는 사고를 막는다(17곳은 전부 단계가 비어 있었다).
    """
    FLAG = 'missing_disposition_20260828'
    TERMINATE_IDS = [653, 366, 781, 600, 544, 162, 199, 393, 157, 86, 187]   # 지우기 11
    KEEP_IDS = [466, 750, 697, 756, 694]                                     # 그대로 5
    RENAME_ID, RENAME_BIZ = 591, '서한푸드'                                   # 이름 맞추기 1
    try:
        conn = _get_conn()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS _app_migrations (key TEXT PRIMARY KEY)")
            if conn.execute("SELECT 1 FROM _app_migrations WHERE key=?", (FLAG,)).fetchone():
                return
            cur = conn.cursor()
            guard = " AND (contract_stage IS NULL OR contract_stage='')"
            ph = ','.join('?' * len(TERMINATE_IDS))
            cur.execute(f"UPDATE clients SET status='terminated' WHERE id IN ({ph}) "
                        f"AND status='active'{guard}", TERMINATE_IDS)
            n_term = cur.rowcount
            ph2 = ','.join('?' * len(KEEP_IDS))
            cur.execute("UPDATE clients SET contract_stage='전산 외 — 대표 확인', "
                        "contract_stage_at=datetime('now','localtime') "
                        f"WHERE id IN ({ph2}) AND status='active'{guard}", KEEP_IDS)
            n_keep = cur.rowcount
            cur.execute(f"UPDATE clients SET business_name=? WHERE id=? AND status='active'{guard}",
                        (RENAME_BIZ, RENAME_ID))
            n_ren = cur.rowcount
            cur.execute("INSERT OR REPLACE INTO _app_migrations(key) VALUES(?)", (FLAG,))
            conn.commit()
            logger.info(f"[전산에없음처분] 완료(1회성) — 지우기 {n_term}/{len(TERMINATE_IDS)}곳(종료 처리·기록 보존) · "
                        f"그대로 {n_keep}/{len(KEEP_IDS)}곳(단계 표시) · 이름 맞추기 {n_ren}/1곳")
        finally:
            conn.close()
    except Exception as e:
        # 부팅을 죽이지 않는다 — 실패하면 플래그가 안 남아 다음 부팅에 재시도된다.
        logger.warning(f"[전산에없음처분] 실패(재시도 예정): {e}")


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


def _store_slug(url):
    """스마트스토어 URL → 스토어 슬러그. 중복 판정의 1순위 키(이름보다 안정적)."""
    m = re.search(r"smartstore\.naver\.com/([^/?#]+)", str(url or ""))
    return m.group(1).lower() if m else ""


def _norm_company(name):
    """업체명 정규화 — 공백 제거·소문자. 「달콩 농장」 == 「달콩농장」."""
    return "".join(str(name or "").split()).lower()


def _owner_label(conn, created_by):
    """등록자 표시용 이름 — 중복 안내에 「담당: OOO」로 보여준다."""
    if not created_by:
        return "담당자 미상"
    try:
        r = conn.execute("SELECT name FROM users WHERE id = ?", (created_by,)).fetchone()
        if r and r[0]:
            return str(r[0])
    except Exception:
        pass
    return f"사용자 {created_by}"


def keyword_product_url(conn, client_id, keyword, fallback=""):
    """이 (업체, 키워드) 로 추적할 상품 주소.

    등록부에 적힌 게 있으면 그것, 없으면 업체 주소(fallback).
    ⚠️ 자동분석·수동분석·보고서가 **같은 답**을 쓰도록 이 함수 하나만 지난다 —
       두 벌이면 화면과 배치가 다른 상품을 보게 된다(이 저장소의 반복 교훈).
    """
    kw = (keyword or "").strip()
    if not kw:
        return fallback or ""
    try:
        row = conn.execute(
            "SELECT product_url FROM client_keyword_product WHERE client_id=? AND keyword=?",
            (client_id, kw)).fetchone()
    except Exception:
        return fallback or ""          # 표가 아직 없는 구버전 DB — 종전 동작
    if row and (row["product_url"] or "").strip():
        return row["product_url"].strip()
    return fallback or ""


def set_keyword_product(conn, client_id, keyword, product_url, user_id=None):
    """키워드별 상품 등록·변경. 빈 주소면 등록부에서 지운다(= 업체 주소로 되돌림)."""
    kw = (keyword or "").strip()
    if not kw:
        return False
    url = (product_url or "").strip()
    if not url:
        conn.execute("DELETE FROM client_keyword_product WHERE client_id=? AND keyword=?",
                     (client_id, kw))
        return True
    conn.execute(
        "INSERT INTO client_keyword_product (client_id, keyword, product_url, updated_by, updated_at)"
        " VALUES (?,?,?,?,datetime('now','localtime'))"
        " ON CONFLICT(client_id, keyword) DO UPDATE SET"
        "   product_url=excluded.product_url, updated_by=excluded.updated_by,"
        "   updated_at=excluded.updated_at",
        (client_id, kw, url, user_id))
    return True


def _resolve_track_until(req):
    """추적 종료일 결정 — 명시 날짜 우선, 없으면 개월 수로 계산, 둘 다 없으면 무기한(None)."""
    raw = (getattr(req, "track_until", None) or "").strip()
    if raw:
        try:
            datetime.strptime(raw[:10], "%Y-%m-%d")
            return raw[:10]
        except ValueError:
            pass  # 형식이 틀리면 개월 수로 폴백
    months = getattr(req, "track_months", None)
    try:
        months = int(months) if months is not None else None
    except (TypeError, ValueError):
        months = None
    if not months or months <= 0:
        return None
    d = date.today()
    y, m = d.year + (d.month - 1 + months) // 12, (d.month - 1 + months) % 12 + 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, day).isoformat()


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
    # 경쟁사 비교(2026-07): role='competitor' + competitor_of=<광고주 client_id> 로 등록하면
    # 광고주 리스트/자동추적/정산에서 제외되고 비교 화면에서만 쓰인다. 기본은 광고주.
    role: Optional[str] = 'advertiser'
    competitor_of: Optional[int] = None
    # 플레이스 축(2026-08): vertical='place' 로 등록하면 같은 권한·30일 유예 규칙을 타되
    # 스토어 전용 자동분석 배치에서 제외된다(순위 이력은 place_rank_history 별도 축).
    vertical: Optional[str] = 'store'
    # 추적 수명주기(2026-08-20): 분석했다고 자동 추적되지 않는다 — 화면에서 명시 선택.
    #   track: True 면 매일 순위 추적 시작 / track_months: 추적 기간(개월, 종료일 자동 계산)
    #   track_until: 종료일 직접 지정(YYYY-MM-DD). 전산 계약 종료일을 그대로 넣을 때 사용.
    # ⚠️ 미전송(None)이면 종전 동작 유지 — 구버전 화면이 보내는 요청이 깨지지 않게.
    track: Optional[bool] = None
    track_months: Optional[int] = None
    track_until: Optional[str] = None
    # 중복 안내를 보고 「이 업체에 키워드만 추가」를 누르면 True 로 다시 보낸다.
    force_attach: Optional[bool] = False


class SaveRankRequest(BaseModel):
    client_id: int
    keyword: str
    product_url: Optional[str] = ''
    rank_position: Optional[int] = None
    page_number: Optional[int] = None
    check_type: Optional[str] = 'manual'


# ==================== 빠른 업체 등록 (분석 탭에서) ====================

@router.post("/quick-register")
def quick_register(req: QuickRegisterRequest, current_user: dict = Depends(get_current_user)):
    """분석 결과와 함께 업체를 빠르게 등록 (신규 또는 기존 업체에 분석 추가).
    권한: 광고주(정식 업체) 등록 = 관리팀 매니저·최고관리자만. 경쟁사 등록 = 모든 로그인 사용자
    (영업사원=viewer 포함). 단 영업사원이 등록한 경쟁사는 30일 뒤 자동 삭제(expires_at)."""
    conn = _get_conn()
    try:
        user_id = current_user["id"]
        user_role = str(current_user.get("role") or "")
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        today = date.today().isoformat()

        # 등록 유형 판정.
        #  - competitor: role='competitor' + competitor_of=<앵커 id>  → 비교 화면 전용
        #  - prospect  : role='prospect'                              → 영업 대상(영업사원 개인용)
        #  - advertiser: 그 외 기본값                                  → 정식 광고주(관리팀 소유)
        req_role = str(req.role or 'advertiser')
        is_comp = (req_role == 'competitor') and req.competitor_of
        is_prospect = (req_role == 'prospect') and not is_comp
        role = 'competitor' if is_comp else ('prospect' if is_prospect else 'advertiser')
        comp_of = int(req.competitor_of) if is_comp else None
        vertical = 'place' if str(req.vertical or 'store') == 'place' else 'store'

        # 권한: 광고주(정식 업체) 등록은 관리팀 매니저·최고관리자만.
        #       영업 대상(prospect)·경쟁사(competitor)는 로그인 사용자 전원 허용(영업사원 개인용).
        if role == 'advertiser' and user_role not in ("manager", "superadmin"):
            raise HTTPException(status_code=403, detail="정식 광고주 등록은 관리팀 매니저만 가능합니다. 영업 대상·경쟁사만 등록할 수 있습니다.")

        # 영업사원(viewer)이 등록한 영업 대상·경쟁사 → 30일 뒤 자동 삭제. 관리팀 등록분은 영구(NULL).
        is_rep = (user_role == "viewer")
        expires_at = None
        if is_rep and role in ("prospect", "competitor"):
            expires_at = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')

        if is_comp:
            # 연결 앵커(광고주 또는 영업 대상) 존재 확인 (경쟁사는 반드시 앵커에 연결)
            adv = conn.execute(
                "SELECT id FROM clients WHERE id = ? AND COALESCE(role,'advertiser') IN ('advertiser','prospect')",
                (comp_of,)
            ).fetchone()
            if not adv:
                raise HTTPException(status_code=400, detail="연결할 대상(광고주·영업 대상)을 찾을 수 없습니다.")

        # ── 중복 판정 (2026-08-20 개편) ────────────────────────────────
        # 종전: 「업체명 정확일치 AND 등록자=본인」 → ⑴ 띄어쓰기만 달라도 통과
        #       ⑵ **담당자가 다르면 검사조차 안 함**. 실측 중복 20건 중 10건이 ⑵ 유형이었다
        #       (달콩 농장/달콩농장, 안동두레농원 ×2, 남향농원 ×2 …).
        # 이제: 스토어 주소(슬러그) 1순위 → 정규화 업체명 2순위로, **등록자와 무관하게** 본다.
        #       경쟁사는 종전대로 competitor_of 범위 안에서만 비교(광고주를 덮지 않게).
        _slug = _store_slug(req.product_url) or _store_slug(getattr(req, 'store_url', ''))
        _nkey = _norm_company(req.name)
        existing = None
        _dup_owner = None
        cand = conn.execute(
            "SELECT id, name, naver_store_url, created_by, COALESCE(role,'advertiser') role, "
            "       COALESCE(competitor_of,0) comp, created_at "
            "  FROM clients "
            " WHERE status='active' AND COALESCE(vertical,'store') = ? "
            "   AND COALESCE(role,'advertiser') = ? AND COALESCE(competitor_of,0) = ?",
            (vertical, role, comp_of or 0)
        ).fetchall()
        if _slug:
            for c in cand:
                if _store_slug(c["naver_store_url"]) == _slug:
                    existing = c
                    break
        if existing is None and _nkey:
            for c in cand:
                if _norm_company(c["name"]) == _nkey:
                    existing = c
                    break
        # 남이 등록한 업체면 조용히 붙이지 않고 화면에 알린다(누가 담당인지 보여줘야 정리가 된다)
        if existing is not None and str(existing["created_by"] or "") != str(user_id):
            _dup_owner = _owner_label(conn, existing["created_by"])

        # 남이 등록한 업체면 여기서 멈추고 화면에 알린다 — 조용히 붙이면 「같은 업체 두 줄」이
        # 계속 생기고, 어느 쪽에 순위가 붙는지 아무도 모르게 된다(실측 중복 20건의 원인).
        # 화면은 이 응답을 받아 「이 업체에 키워드만 추가 / 취소」를 묻는다.
        if _dup_owner and not req.force_attach:
            return {
                "success": False,
                "duplicate": True,
                "client_id": existing["id"],
                "existing_name": existing["name"],
                "owner": _dup_owner,
                "registered_at": (existing["created_at"] or "")[:10],
                "matched_by": "스토어 주소" if _slug and _store_slug(existing["naver_store_url"]) == _slug else "업체명",
                "detail": (f"이미 등록된 업체입니다 — '{existing['name']}' "
                           f"(담당: {_dup_owner}). 같은 업체라면 키워드만 추가할 수 있습니다."),
            }

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
            # ⭐ 이 키워드로 추적할 상품을 등록부에 남긴다 (2026-08-21, 이예은 신고).
            #    업체 주소는 첫 등록 상품으로 굳어 있으므로, 두 번째 상품은 여기에만 남는다.
            #    업체 주소와 같으면 굳이 안 적는다(등록부를 필요한 것만 담게).
            _url = (req.product_url or "").strip()
            if _url and _url != (existing["naver_store_url"] or "").strip():
                try:
                    set_keyword_product(conn, client_id, req.keyword, _url, user_id)
                except Exception as _e:
                    logger.warning(f"[quick-register] 키워드별 상품 등록 실패(무시): {_e}")

            # 영업사원이 영업 대상·경쟁사를 재등록하면 자동삭제 시점 30일 연장(갱신). 관리팀 재등록은 영구 유지.
            if expires_at is not None:
                conn.execute("UPDATE clients SET expires_at = ? WHERE id = ?", (expires_at, client_id))
            msg = (f"경쟁사 '{req.name}' 분석 결과가 갱신되었습니다." if is_comp
                   else (f"영업 대상 '{req.name}' 분석 결과가 갱신되었습니다." if is_prospect
                         else f"'{req.name}' 업체에 분석 결과가 추가되었습니다."))
        else:
            # 신규 업체 등록 (광고주 · 영업 대상 · 경쟁사)
            # 추적 수명주기 — 광고주만 대상. 영업 대상·경쟁사는 계약 전/비교용이라 추적하지 않는다.
            #   track 미전송(None) = 구버전 화면 → 종전 동작(추적 ON)으로 둬 회귀를 막는다.
            _is_adv = (role == 'advertiser')
            _track_on = 1 if (_is_adv and (req.track is None or req.track)) else 0
            _track_until = _resolve_track_until(req) if _track_on else None
            cursor = conn.execute("""
                INSERT INTO clients (name, business_name, main_keywords, naver_store_url,
                    status, created_by, created_at, updated_at, role, competitor_of, expires_at, vertical,
                    track_enabled, track_until)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (req.name, req.name, req.keyword, req.product_url or '',
                  user_id, now, now, role, comp_of, expires_at, vertical,
                  _track_on, _track_until))
            client_id = cursor.lastrowid
            msg = (f"경쟁사 '{req.name}'가 등록되고 분석되었습니다." if is_comp
                   else (f"영업 대상 '{req.name}'가 등록되고 분석되었습니다." if is_prospect
                         else f"'{req.name}' 업체가 등록되고 분석 결과가 저장되었습니다."))

        # 분석 결과 저장 (일자별 누적) — 플레이스 축은 스킵(순위 이력은 place_rank_history 별도 축,
        # client_analyses 는 스토어 분석 스키마라 빈 행을 남기지 않는다)
        if vertical != 'place':
            _save_analysis_internal(conn, client_id, req.keyword, req.product_url or '',
                                    req.analysis_data, req.volume_data, req.related_data,
                                    req.shop_products, req.advertiser_data, today, now,
                                    req.report_html or '', author_id=user_id)

        # #1: 상세 HTML 저장 (있을 때만)
        # ⚠️ 2026-08-30: 업체 표가 아니라 **옆 표**(client_detail_html)에 넣는다.
        #    업체 한 곳당 1.1MB 짜리 덩어리가 업체 표에 있으면, 그 뒤 칸(계약단계 등)을
        #    읽는 모든 목록 조회가 그 덩어리를 지나가야 해서 300배 느려진다(서버 실측).
        if req.detail_html:
            try:
                from detail_html_store import set_html
                set_html(conn, client_id, req.detail_html)
                conn.execute("UPDATE clients SET updated_at = ? WHERE id = ?", (now, client_id))
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
                 "website_url, naver_store_url, main_keywords, notes, status, auto_analysis, "
                 "created_by, created_at, updated_at, role, expires_at, "
                 "COALESCE(vertical,'store') AS vertical, "
                 # 5칸 분리(2026-08-28) 판정에 쓰는 값들. 목록 화면이 이것들로
                 # 진행중·환불중·홀딩중·삭제 필요를 가른다.
                 "COALESCE(track_enabled,1) AS track_enabled, track_until, "
                 "contract_stage, contract_stage_at")
        if user_role == "viewer":
            # 영업사원(viewer) = 완전 개인 모드. 관리팀 광고주는 아예 보이지 않고,
            # 본인이 등록한 영업 대상(prospect)만 보인다(경쟁사는 각 대상 상세에서 조회).
            clients = conn.execute(
                f"SELECT {_COLS} FROM clients WHERE status='active' "
                "AND COALESCE(role,'advertiser')='prospect' AND created_by = ? "
                "ORDER BY updated_at DESC",
                (user_id,)
            ).fetchall()
        elif is_adm:
            clients = conn.execute(
                f"SELECT {_COLS} FROM clients WHERE status='active' AND COALESCE(role,'advertiser')='advertiser' ORDER BY updated_at DESC"
            ).fetchall()
        else:
            clients = conn.execute(
                f"SELECT {_COLS} FROM clients WHERE status='active' AND COALESCE(role,'advertiser')='advertiser' "
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

        # ── 5칸 분리 판정에 필요한 두 가지를 미리 모은다 (2026-08-28) ──
        # ⑴ 수집이 5회 소진된 키워드를 가진 업체(= 「확인 필요」)
        #    ⚠️ 업체당 조회하면 N+1 이 된다 — 한 번에 모아 집합으로 만든다.
        check_ids = set()
        try:
            dead = [r[0] for r in conn.execute(
                "SELECT keyword FROM collect_requests WHERE status='pending' AND attempts >= 5"
            ).fetchall()]
            if dead:
                dph = ','.join('?' * len(dead))
                # 그 업체가 대표 키워드로 쓰거나(main_keywords), 추적 상품으로 이어 둔 키워드
                for r in conn.execute(
                    f"""SELECT DISTINCT l.client_id FROM rank_link l
                          JOIN tracked_keywords k ON k.product_id = l.tracked_product_id
                         WHERE k.keyword IN ({dph})""", dead).fetchall():
                    check_ids.add(r[0])
                _dead_set = set(dead)
                for c0 in clients:
                    for kw in (c0['main_keywords'] or '').split(','):
                        if kw.strip() and kw.strip() in _dead_set:
                            check_ids.add(c0['id'])
                            break
        except Exception as _ce:
            logger.warning(f"[my-clients] 확인 필요 집계 실패(무시): {_ce}")

        # ⑵ 계약 단계를 한 번이라도 받아 본 적이 있는가.
        #    ⚠️ 이게 없으면 배포 직후(전 업체 단계 NULL)에 전부 「전산에 없음」으로
        #       삭제 필요에 쏠린다. 한 번이라도 받았을 때만 그 사유를 센다.
        try:
            _synced_once = bool(conn.execute(
                "SELECT 1 FROM clients WHERE contract_stage IS NOT NULL AND contract_stage <> '' LIMIT 1"
            ).fetchone())
        except Exception:
            _synced_once = False

        from client_buckets import classify, delete_reasons
        from datetime import date as _date
        _today = _date.today().isoformat()

        result = []
        for c in clients:
            row = dict(c)
            cid = c['id']
            row['_synced'] = _synced_once
            row['delete_reasons'] = delete_reasons(row, _today)
            row['needs_check'] = cid in check_ids
            row['bucket'] = classify(row, _today, needs_check=row['needs_check'])
            row.pop('_synced', None)
            a = agg_map.get(cid)
            row['analysis_count'] = (a['analysis_count'] if a else 0)
            row['last_analyzed'] = (a['last_analyzed'] if a else None)
            row['unique_keyword_count'] = (a['unique_keyword_count'] if a else 0)
            row['total_analysis_days'] = (a['total_analysis_days'] if a else 0)
            row['analyzed_keywords'] = ([latest_map[cid]] if cid in latest_map else [])  # 최신 1건만
            row['manager_name'] = mgr_map.get(row.get('created_by'), '')  # 담당자명
            # 영업 대상(prospect)·경쟁사 자동삭제까지 남은 일수(있을 때만)
            row['days_left'] = _days_left(row.get('expires_at'))
            result.append(row)

        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"[my-clients] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ==================== 내린 업체(보관) 목록 — 되돌리기용 ====================

@router.get("/archived-clients")
def archived_clients(current_user: dict = Depends(get_current_user)):
    """목록에서 내린 업체(status='terminated') — 「🗄 내린 업체」 탭 (2026-08-30 대표 확정).

    ⚠️ **왜 별도 경로인가** — 관리 목록(`/my-clients`)은 `status='active'` 만 내려주므로
       내린 업체를 볼 방법이 아예 없었다. 그대로 두면 **되돌릴 길 없는 한 방향 문**이 된다
       (「케이스 삭제 경로만 열고 화면 버튼을 안 만든」 전산 선례와 같은 함정).
       `/my-clients` 에 파라미터를 붙이지 않은 이유 = 그 경로는 분석·순위 집계까지 얹어
       전 직원이 매일 여는 화면이라, 손대면 그 화면 전체가 회귀 위험을 진다.
       여기는 **이름·사유·되돌리기**만 필요해 집계 없이 가볍게 읽는다.

    범위는 관리 목록과 **같은 규칙**(대표·관리자=전체 / 영업사원=본인 영업 대상 /
    그 외=본인 등록분) — 목록에서 못 보던 업체가 보관함에서 보이면 안 된다.
    """
    conn = _get_conn()
    try:
        user_id = current_user["id"]
        is_adm = _is_admin(current_user)
        user_role = current_user.get("role", "viewer")
        cols = ("id, name, business_name, naver_store_url, main_keywords, created_by, "
                "updated_at, role, COALESCE(vertical,'store') AS vertical, "
                "COALESCE(track_enabled,1) AS track_enabled, track_until, "
                "contract_stage, contract_stage_at")
        if user_role == "viewer":
            rows = conn.execute(
                f"SELECT {cols} FROM clients WHERE status='terminated' "
                "AND COALESCE(role,'advertiser')='prospect' AND created_by = ? "
                "ORDER BY updated_at DESC", (user_id,)).fetchall()
        elif is_adm:
            rows = conn.execute(
                f"SELECT {cols} FROM clients WHERE status='terminated' "
                "AND COALESCE(role,'advertiser')='advertiser' ORDER BY updated_at DESC").fetchall()
        else:
            rows = conn.execute(
                f"SELECT {cols} FROM clients WHERE status='terminated' "
                "AND COALESCE(role,'advertiser')='advertiser' "
                "AND (created_by = ? OR created_by IS NULL OR created_by = '') "
                "ORDER BY updated_at DESC", (user_id,)).fetchall()

        # 내릴 때의 사유를 그대로 다시 보여준다 — 왜 내렸는지 모르면 되돌릴지 판단할 수 없다.
        # 판정은 목록 화면과 **같은 함수**(client_buckets)를 쓴다(두 곳이 갈리면 배지가 서로 다른 말을 한다).
        try:
            synced = bool(conn.execute(
                "SELECT 1 FROM clients WHERE contract_stage IS NOT NULL AND contract_stage <> '' LIMIT 1"
            ).fetchone())
        except Exception:
            synced = False
        today = date.today().isoformat()
        out = []
        for r in rows:
            d = dict(r)
            d["_synced"] = synced
            try:
                from client_buckets import delete_reasons
                d["delete_reasons"] = delete_reasons(d, today)
            except Exception:
                d["delete_reasons"] = []
            out.append(d)
        return {"success": True, "data": out}
    except Exception as e:
        logger.error(f"[archived-clients] {e}")
        return {"success": False, "detail": str(e), "data": []}
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

        # viewer(영업사원) → 본인 등록 영업 대상만(관리팀 광고주 비노출),
        # admin → 전체 광고주, manager → 본인 등록 광고주만
        if user_role == "viewer":
            rows = conn.execute(
                "SELECT id, name, main_keywords FROM clients "
                "WHERE status = 'active' AND COALESCE(role,'advertiser')='prospect' AND created_by = ? "
                "ORDER BY name ASC",
                (user_id,)
            ).fetchall()
        elif is_adm:
            rows = conn.execute(
                "SELECT id, name, main_keywords FROM clients WHERE status = 'active' AND COALESCE(role,'advertiser')='advertiser' ORDER BY name ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, main_keywords FROM clients "
                "WHERE status = 'active' AND COALESCE(role,'advertiser')='advertiser' AND (created_by = ? OR created_by IS NULL OR created_by = '') "
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
def delete_client(client_id: int, current_user: dict = Depends(get_current_user)):
    """업체 삭제 (본인 소유분만 — 관리팀 광고주 + 영업사원 영업 대상/경쟁사).
    관련 분석/순위 데이터, 그리고 이 업체에 연결된 경쟁사도 함께 삭제(고아 방지)."""
    conn = _get_conn()
    try:
        user_id = current_user["id"]
        is_adm = _is_admin(current_user)

        # 업체 존재 및 소유권 확인 — admin은 전체, 그 외(manager·viewer)는 본인 등록분만.
        client = conn.execute("SELECT id, name, created_by FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not client:
            raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")
        if not is_adm and client['created_by'] != user_id:
            raise HTTPException(status_code=403, detail="본인이 등록한 업체만 삭제할 수 있습니다.")

        name = client['name']
        # 이 업체(광고주·영업 대상)에 연결된 경쟁사 id 수집 → 함께 삭제(고아 방지)
        linked = [r["id"] for r in conn.execute(
            "SELECT id FROM clients WHERE COALESCE(role,'advertiser')='competitor' AND competitor_of = ?",
            (client_id,)
        ).fetchall()]
        del_ids = [client_id] + linked
        for cid in del_ids:
            # 관련 데이터 삭제 (FOREIGN KEY CASCADE가 안 될 수 있으므로 명시적 삭제)
            conn.execute("DELETE FROM client_analyses WHERE client_id = ?", (cid,))
            conn.execute("DELETE FROM client_rank_history WHERE client_id = ?", (cid,))
            conn.execute("DELETE FROM clients WHERE id = ?", (cid,))
        conn.commit()

        logger.info(f"[delete-client] '{name}' (id={client_id}) + 연결 경쟁사 {len(linked)}건 deleted by user {user_id}")
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

@router.get("/rank-overview")
def rank_overview(current_user: dict = Depends(get_current_user)):
    """키워드 순위 탭 랜딩 — 업체별 순위 추적 롤업 (2026-08-04 탭 분리 1차).

    스코핑은 my_clients 와 동일: viewer=본인 영업대상(prospect)만 /
    manager=본인+무소유 광고주 / admin=전체 광고주. 집계 원천은 client_rank_history
    최근 8일치(스파크라인·전일 대비까지 한 번에) — 업체 수십×키워드 수십×8일이라
    수천 행 수준, 파이썬 집계로 충분하다.
    """
    conn = _get_conn()
    try:
        user_id = current_user["id"]
        is_adm = _is_admin(current_user)
        user_role = current_user.get("role", "viewer")
        # 플레이스 축 업체는 제외 — 이 탭(키워드 순위)은 쇼핑 순위 전용이라
        # client_rank_history 가 없는 플레이스 업체가 「주의(노출 0)」로 오인 집계되는 것 방지.
        _COLS = "id, name, naver_store_url, role"
        _V = "AND COALESCE(vertical,'store')='store' "
        if user_role == "viewer":
            clients = conn.execute(
                f"SELECT {_COLS} FROM clients WHERE status='active' "
                f"AND COALESCE(role,'advertiser')='prospect' {_V}AND created_by = ? "
                "ORDER BY name", (user_id,)).fetchall()
        elif is_adm:
            clients = conn.execute(
                f"SELECT {_COLS} FROM clients WHERE status='active' "
                f"AND COALESCE(role,'advertiser')='advertiser' {_V}ORDER BY name").fetchall()
        else:
            clients = conn.execute(
                f"SELECT {_COLS} FROM clients WHERE status='active' "
                f"AND COALESCE(role,'advertiser')='advertiser' {_V}"
                "AND (created_by = ? OR created_by IS NULL OR created_by = '') "
                "ORDER BY name", (user_id,)).fetchall()
        if not clients:
            return {"success": True, "data": [], "totals": {}}

        ids = [c["id"] for c in clients]
        ph = ",".join("?" * len(ids))
        rows = conn.execute(f"""
            SELECT client_id, keyword, rank_position,
                   substr(checked_at,1,10) AS d, id
            FROM client_rank_history
            WHERE client_id IN ({ph})
              AND checked_at >= date('now','localtime','-8 day')
            ORDER BY id
        """, ids).fetchall()

        # (client, keyword) → 날짜별 마지막 값 (id 순회라 나중 행이 그 날짜의 최종값)
        per = {}
        for r in rows:
            per.setdefault((r["client_id"], r["keyword"]), {})[r["d"]] = r["rank_position"]

        by_client = {}
        for (cid, kw), days in per.items():
            ds = sorted(days.keys())
            latest_d = ds[-1]
            latest = days[latest_d]
            prev = days[ds[-2]] if len(ds) >= 2 else None
            e = by_client.setdefault(cid, {"keywords": 0, "exposed": 0, "top10": 0,
                                           "up": 0, "down": 0, "last_checked": "",
                                           "tops": []})
            e["keywords"] += 1
            if latest is not None:
                e["exposed"] += 1
                if latest <= 10:
                    e["top10"] += 1
                e["tops"].append((latest, kw))
            if latest is not None and prev is not None:
                if latest < prev:
                    e["up"] += 1
                elif latest > prev:
                    e["down"] += 1
            if latest_d > e["last_checked"]:
                e["last_checked"] = latest_d

        out = []
        for c in clients:
            e = by_client.get(c["id"])
            item = {"id": c["id"], "name": c["name"],
                    "store_url": c["naver_store_url"] or "",
                    "role": c["role"] or "advertiser",
                    "keywords": 0, "exposed": 0, "top10": 0, "up": 0, "down": 0,
                    "last_checked": "", "top_keywords": [], "rep_series": []}
            if e:
                e["tops"].sort()
                item.update({k: e[k] for k in ("keywords", "exposed", "top10", "up", "down", "last_checked")})
                item["top_keywords"] = [{"keyword": k, "rank": r} for r, k in e["tops"][:2]]
                # 대표 키워드(최고 순위)의 8일 추이 — 대시보드 카드 미니 스파크용 (2차 확산)
                if e["tops"]:
                    _rep_kw = e["tops"][0][1]
                    _rep_days = per.get((c["id"], _rep_kw), {})
                    item["rep_series"] = [{"d": d, "rank": _rep_days[d]}
                                          for d in sorted(_rep_days.keys())]
            out.append(item)
        totals = {
            "clients": len(out),
            "keywords": sum(i["keywords"] for i in out),
            "exposed_clients": sum(1 for i in out if i["exposed"] > 0),
            "up_total": sum(i["up"] for i in out),
            "down_total": sum(i["down"] for i in out),
            "attention": sum(1 for i in out if i["keywords"] > 0 and i["exposed"] == 0),
        }
        return {"success": True, "data": out, "totals": totals}
    except Exception as e:
        logger.error(f"[rank-overview] {e}")
        return {"success": False, "detail": str(e)}
    finally:
        conn.close()


@router.get("/{client_id}/rank-board")
def rank_board(client_id: int, days: int = 8, current_user: dict = Depends(get_current_user)):
    """업체 상세 — 키워드별 최신 순위·전일 대비·시리즈·검색량 (탭 분리 1차).

    순위 원천 = client_rank_history(기본 최근 8일 — 2차 확산에서 days 파라미터로
    7/30일 추이 전환), 검색량 = client_analyses 의 키워드별 최신
    summaryCards.totalVolume(콤마 문자열 그대로 표시용).
    """
    conn = _get_conn()
    try:
        days = min(max(int(days or 8), 7), 90)
        _verify_client_access(conn, client_id, current_user)
        client = conn.execute(
            "SELECT id, name, naver_store_url, main_keywords, COALESCE(role,'advertiser') AS role "
            "FROM clients WHERE id=?", (client_id,)).fetchone()
        if not client:
            raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")

        rows = conn.execute(f"""
            SELECT keyword, rank_position, page_number,
                   substr(checked_at,1,10) AS d, checked_at, id
            FROM client_rank_history
            WHERE client_id=? AND checked_at >= date('now','localtime','-{days} day')
            ORDER BY id
        """, (client_id,)).fetchall()
        # 키워드별 상품 등록부 — 한 번만 읽어 행마다 붙인다
        _client_url = (client["naver_store_url"] or "").strip() if client else ""
        _kwp = {}
        try:
            for _r in conn.execute(
                    "SELECT keyword, product_url FROM client_keyword_product WHERE client_id=?",
                    (client_id,)):
                _u = (_r["product_url"] or "").strip()
                if _u:
                    _kwp[(_r["keyword"] or "").strip()] = _u
        except Exception:
            _kwp = {}

        # 그만 재기(억제) 키워드 — 보드에서도 뺀다. 수집이 안 도는 키워드가 화면에
        # 남아 있으면 「미노출 n일」로 계속 늘어나 지운 게 아닌 것처럼 보인다.
        try:
            from keyword_mute import muted_set
            _muted_kw = muted_set(conn, client_id)
        except Exception:
            _muted_kw = set()

        # 이어진 추적 상품(rank_link) — 상품별 키워드 목록·출처 표시의 근거.
        # 화면 통합(2026-08-29 대표 확정): 업체 보드가 자기 상품을 함께 보여준다.
        _mk_set = {k.strip() for k in (client["main_keywords"] or "").split(",") if k.strip()}
        products = []
        _prod_kw = {}   # keyword(strip) → 첫 상품 이름 (출처 표시용)
        try:
            from rank_link import get_links_for_client
            for ln in get_links_for_client(client_id):
                pid = ln["tracked_product_id"]
                _pkws = []
                for _kr in conn.execute(
                        "SELECT keyword FROM tracked_keywords WHERE product_id=?", (pid,)):
                    _k = (_kr[0] or "").strip()
                    if _k:
                        _pkws.append(_k)
                _dis = False
                try:
                    _dr = conn.execute(
                        "SELECT COALESCE(disabled_at,'') FROM tracked_products WHERE id=?",
                        (pid,)).fetchone()
                    _dis = bool(_dr and (_dr[0] or "").strip())
                except Exception:
                    pass
                products.append({
                    "id": pid,
                    "name": ln.get("product_name") or "",
                    "store_name": ln.get("store_name") or "",
                    "url": ln.get("product_url") or "",
                    "keywords": _pkws,
                    "disabled": _dis,
                    "match_method": ln.get("match_method") or "",
                })
                if not _dis:
                    for _k in _pkws:
                        _prod_kw.setdefault(_k, ln.get("product_name") or "추적 상품")
        except Exception as _pe:
            logger.warning(f"[rank-board] 이어진 상품 조회 실패(보드는 정상) [{client_id}]: {_pe}")
            products = []

        def _source_of(k):
            """행 출처 — 어디서 등록돼 재고 있는지. 지울 때 무엇이 빠지는지 알려면 필요하다."""
            k = (k or "").strip()
            if k in _mk_set:
                return {"source": "client", "source_label": "업체 키워드"}
            if k in _prod_kw:
                return {"source": "product", "source_label": f"상품 · {_prod_kw[k]}"}
            return {"source": "history", "source_label": "분석 이력"}

        per = {}
        for r in rows:
            if (r["keyword"] or "").strip() in _muted_kw:
                continue   # 그만 재기 지정 — 기록은 남아 있고 화면에서만 뺀다(재등록 시 복귀)
            per.setdefault(r["keyword"], {})[r["d"]] = {
                "rank": r["rank_position"], "page": r["page_number"], "at": r["checked_at"]}

        # 키워드별 검색량 — 최신 분석의 summaryCards.totalVolume
        vol_map = {}
        for r in conn.execute("""
            SELECT keyword, analysis_json FROM client_analyses
            WHERE client_id=? AND id IN (
                SELECT MAX(id) FROM client_analyses WHERE client_id=? GROUP BY keyword)
        """, (client_id, client_id)).fetchall():
            try:
                vol_map[r["keyword"]] = (json.loads(r["analysis_json"] or "{}")
                                         .get("summaryCards", {}).get("totalVolume", "-"))
            except (json.JSONDecodeError, TypeError):
                vol_map[r["keyword"]] = "-"

        board = []
        for kw, days in per.items():
            ds = sorted(days.keys())
            latest = days[ds[-1]]
            prev_rank = days[ds[-2]]["rank"] if len(ds) >= 2 else None
            series = [{"d": d, "rank": days[d]["rank"]} for d in ds]
            delta = None
            if latest["rank"] is not None and prev_rank is not None:
                delta = prev_rank - latest["rank"]   # 양수=상승
            # 미노출 연속일 — 시리즈 끝에서부터 연속으로 rank 가 없는 일수 (2차 확산)
            unexposed_days = 0
            for d in reversed(ds):
                if days_map_rank := days[d]["rank"]:
                    break
                unexposed_days += 1
            board.append({
                "keyword": kw, "rank": latest["rank"], "page": latest["page"],
                # 이 키워드로 추적 중인 상품 (2026-08-21 이예은 신고 — 업체당 상품 하나 전제 해소)
                "product_url": _kwp.get(kw, _client_url),
                "product_assigned": kw in _kwp,
                "prev_rank": prev_rank, "delta": delta,
                "volume": vol_map.get(kw, "-"),
                "last_checked": latest["at"], "series": series,
                "unexposed_days": unexposed_days,
                **_source_of(kw),
            })
        # 등록됐지만 아직 기록이 없는 키워드도 「기록 대기」로 보여준다 — 키워드를 추가한
        # 직원이 화면에서 아무 변화도 못 보면 고장인지 구분할 수 없기 때문(반영 현황 원칙).
        # 광고주만: 영업 대상(prospect)은 자동 추적 대상이 아니라 「대기」가 영원히 안 풀린다.
        _pending_ok = conn.execute(
            "SELECT COALESCE(auto_analysis,1) AS a, naver_store_url AS u FROM clients WHERE id=?",
            (client_id,)).fetchone()
        if (client["role"] == "advertiser" and _pending_ok and _pending_ok["a"]
                and (_pending_ok["u"] or "").strip()):
            _norm = lambda k: "".join(str(k).split()).lower()
            _known = {_norm(k) for k in per.keys()}
            _muted_norm = {_norm(k) for k in _muted_kw}
            _vol_norm = {_norm(k): v for k, v in vol_map.items()}   # 공백 변형에도 검색량 매칭
            for mk in (client["main_keywords"] or "").split(","):
                mk = mk.strip()
                if mk and _norm(mk) not in _known and _norm(mk) not in _muted_norm:
                    _known.add(_norm(mk))
                    board.append({
                        "keyword": mk, "rank": None, "page": None,
                        "product_url": _kwp.get(mk, _client_url),
                        "product_assigned": mk in _kwp,
                        "prev_rank": None, "delta": None,
                        "volume": _vol_norm.get(_norm(mk), "-"),
                        "last_checked": "", "series": [],
                        "unexposed_days": 0, "pending": True,
                        **_source_of(mk),
                    })
            # 이어진 상품에만 등록된 키워드도 「기록 대기」로 — 상품 쪽에서 등록한 직원이
            # 업체 보드에서 아무것도 못 보면 양방향이 아니라 반쪽이다(같은 반영 현황 원칙).
            for pk in _prod_kw:
                if _norm(pk) not in _known and _norm(pk) not in _muted_norm:
                    _known.add(_norm(pk))
                    board.append({
                        "keyword": pk, "rank": None, "page": None,
                        "product_url": _kwp.get(pk, _client_url),
                        "product_assigned": pk in _kwp,
                        "prev_rank": None, "delta": None,
                        "volume": _vol_norm.get(_norm(pk), "-"),
                        "last_checked": "", "series": [],
                        "unexposed_days": 0, "pending": True,
                        **_source_of(pk),
                    })
        # 정렬: 노출(순위 오름차순) 먼저, 미노출 뒤(키워드 가나다)
        board.sort(key=lambda b: (b["rank"] is None, b["rank"] if b["rank"] is not None else 0, b["keyword"]))
        kpis = {
            "keywords": len(board),
            "exposed": sum(1 for b in board if b["rank"] is not None),
            "top10": sum(1 for b in board if b["rank"] is not None and b["rank"] <= 10),
            "up": sum(1 for b in board if (b["delta"] or 0) > 0),
            "down": sum(1 for b in board if (b["delta"] or 0) < 0),
        }
        return {"success": True,
                "client": {"id": client["id"], "name": client["name"],
                           "store_url": client["naver_store_url"] or ""},
                "kpis": kpis, "board": board, "products": products}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[rank-board] {e}")
        return {"success": False, "detail": str(e)}
    finally:
        conn.close()



class TrackKeywordRequest(BaseModel):
    keyword: str


@router.get("/{client_id}/keyword-products")
def list_keyword_products(client_id: int, current_user: dict = Depends(get_current_user)):
    """이 업체의 키워드별 상품 지정 현황.

    지정이 없는 키워드는 업체 주소를 쓴다는 뜻이라, 그 사실도 함께 내려준다
    (화면이 「지정 안 함 = 업체 주소」를 그대로 보여줄 수 있게).
    """
    conn = _get_conn()
    try:
        c = conn.execute(
            "SELECT id, name, naver_store_url, main_keywords FROM clients WHERE id=?",
            (client_id,)).fetchone()
        if not c:
            raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")

        mapped = {}
        for r in conn.execute(
                "SELECT keyword, product_url, updated_at FROM client_keyword_product WHERE client_id=?",
                (client_id,)):
            mapped[(r["keyword"] or "").strip()] = {
                "productUrl": r["product_url"], "updatedAt": r["updated_at"]}

        kws = [k.strip() for k in (c["main_keywords"] or "").split(",") if k.strip()]
        base = (c["naver_store_url"] or "").strip()
        rows = []
        for kw in kws:
            m = mapped.get(kw)
            rows.append({
                "keyword": kw,
                "productUrl": (m["productUrl"] if m else base),
                "assigned": bool(m),          # False = 업체 주소를 쓰는 중
                "updatedAt": (m["updatedAt"] if m else None),
            })
        return {"success": True, "data": {
            "clientId": client_id, "clientName": c["name"],
            "clientProductUrl": base, "keywords": rows}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[keyword-products] {e}")
        raise HTTPException(status_code=500, detail="조회 중 오류가 발생했습니다.")
    finally:
        conn.close()


class KeywordProductRequest(BaseModel):
    keyword: str
    product_url: str = ""      # 빈 값 = 지정 해제(업체 주소로 되돌림)


@router.put("/{client_id}/keyword-product")
def upsert_keyword_product(client_id: int, req: KeywordProductRequest,
                           current_user: dict = Depends(get_current_user)):
    """키워드별 상품 지정·변경·해제.

    ⚠️ 지정한 다음 날 08:30 배치부터 그 상품으로 순위를 잰다 — 즉시 바뀌지 않는다.
       화면이 그 사실을 알려 줘야 직원이 「안 됐다」고 오해하지 않는다.
    """
    kw = (req.keyword or "").strip()
    if not kw:
        raise HTTPException(status_code=400, detail="키워드를 입력해주세요.")
    url = (req.product_url or "").strip()
    if url and "smartstore.naver.com" not in url and "naver.com" not in url:
        raise HTTPException(status_code=400, detail="네이버 상품 주소를 넣어주세요.")

    conn = _get_conn()
    try:
        c = conn.execute("SELECT id, main_keywords FROM clients WHERE id=?", (client_id,)).fetchone()
        if not c:
            raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")
        kws = [k.strip() for k in (c["main_keywords"] or "").split(",") if k.strip()]
        if kw not in kws:
            raise HTTPException(
                status_code=400,
                detail=f"'{kw}' 는 이 업체의 추적 키워드가 아닙니다. 먼저 키워드를 등록해주세요.")

        set_keyword_product(conn, client_id, kw, url, current_user.get("id"))
        conn.commit()
        return {"success": True, "message": (
            f"'{kw}' 를 지정한 상품으로 추적합니다. 내일 아침 배치부터 반영됩니다."
            if url else f"'{kw}' 의 상품 지정을 해제했습니다. 업체 대표 상품으로 되돌아갑니다.")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[keyword-product] {e}")
        raise HTTPException(status_code=500, detail="저장 중 오류가 발생했습니다.")
    finally:
        conn.close()


@router.post("/{client_id}/track-keyword")
def add_track_keyword(client_id: int, req: TrackKeywordRequest,
                      current_user: dict = Depends(get_current_user)):
    """키워드 순위 탭에서 추적 키워드 추가 등록 (2026-08-11, 직원 기능 요청).

    쓰기 3곳을 한 번에 정렬한다 — 어긋나면 「등록했는데 순위가 영영 안 붙는」 함정이 된다:
      ① clients.main_keywords 에 추가 → 08:00 배치·업로드 즉시 기록(rank_record)이
         이 키워드를 이 업체 몫으로 인식(둘 다 main_keywords ∪ 분석이력을 본다)
      ② rank_link 로 이어진 추적 상품이 있으면 tracked_keywords 에도 추가(축A 일관)
      ③ 온디맨드 수집 큐 등록 → 보통 수 분 안에 첫 순위가 기록됨
    수집 유니버스에는 main_keywords 가 이번에 함께 편입돼(collector._keyword_universe)
    다음 날부터는 슬롯 수집이 자동으로 커버한다.

    권한 = 이 탭의 열람 스코프와 동일(_verify_client_access). 단 영업 대상(prospect)은
    일일 자동 추적 대상이 아니므로(배치·즉시 기록 모두 광고주만) 명확한 안내와 함께 거절 —
    조용히 받아서 영원히 「대기」로 두는 것보다 낫다.
    """
    kw = (req.keyword or "").strip()
    if not kw or len(kw) > 40:
        raise HTTPException(status_code=400, detail="키워드는 1~40자로 입력해주세요.")
    # main_keywords 저장 형식이 쉼표 목록이라, 쉼표가 들어오면 목록 자체가 파손된다
    # (소비처 전부 split(",") — 「수제쿠키,선물세트」가 키워드 2개로 해석됨). 명확히 거절.
    if "," in kw:
        raise HTTPException(status_code=400, detail="키워드는 한 번에 한 개씩 등록해주세요(쉼표 없이).")
    conn = _get_conn()
    try:
        _verify_client_access(conn, client_id, current_user)
        client = conn.execute(
            "SELECT id, name, main_keywords, naver_store_url, COALESCE(role,'advertiser') AS role, "
            "COALESCE(vertical,'store') AS vertical, COALESCE(auto_analysis,1) AS auto_on "
            "FROM clients WHERE id=? AND status='active'", (client_id,)).fetchone()
        if not client:
            raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")
        if client["vertical"] != "store":
            raise HTTPException(status_code=400, detail="플레이스 업체는 「지도 순위 추적」 탭에서 등록해주세요.")
        if client["role"] != "advertiser":
            raise HTTPException(status_code=400, detail=(
                "영업 대상 업체는 일일 자동 추적 대상이 아닙니다. "
                "분석 실행 시 순위가 기록되며, 광고주로 등록하면 키워드 추적이 시작됩니다."))
        # ⚠️ 아래 두 조건은 기록 경로(배치·업로드 즉시 기록·수집 유니버스) 전부가 거르는
        # 자격이라, 여기서 받아주면 「등록 성공 → 영원히 기록 대기」 함정이 된다(적대 리뷰 확정).
        if not client["auto_on"]:
            raise HTTPException(status_code=400, detail=(
                "자동 분석이 꺼진 업체라 일일 순위 추적이 돌지 않습니다. "
                "업체 관리에서 자동 분석을 켠 뒤 등록해주세요."))
        if not (client["naver_store_url"] or "").strip():
            raise HTTPException(status_code=400, detail=(
                "스토어 주소가 등록되지 않은 업체입니다. "
                "업체 관리에서 네이버 스토어 주소를 먼저 등록해주세요."))

        _norm = lambda k: "".join(str(k).split()).lower()
        existing = set()
        for r in conn.execute("SELECT DISTINCT keyword FROM client_analyses WHERE client_id=?", (client_id,)):
            existing.add(_norm(r["keyword"] or ""))
        for r in conn.execute("SELECT DISTINCT keyword FROM client_rank_history WHERE client_id=?", (client_id,)):
            existing.add(_norm(r["keyword"] or ""))

        # ⚠️ main_keywords 는 읽고-고쳐-쓰는 목록이라, 동시 등록이 겹치면 나중 쓰기가
        # 먼저 쓰기를 지운다(lost update — 적대 리뷰 확정). 쓰기 락(BEGIN IMMEDIATE) 안에서
        # 다시 읽고 → 중복·상한 검사 → 추가까지 한 덩어리로 처리해 경합을 직렬화한다.
        conn.commit()   # 앞선 읽기의 암묵 트랜잭션 정리(BEGIN 중첩 방지)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT main_keywords FROM clients WHERE id=?", (client_id,)).fetchone()
        mk_list = [k.strip() for k in ((row["main_keywords"] if row else "") or "").split(",") if k.strip()]
        existing |= {_norm(k) for k in mk_list}

        # 그만 재기(억제)로 빠져 있던 키워드면 재등록 = 복귀 — 이력이 그대로 살아난다.
        # 억제 표는 strip 원문이라 공백 변형까지 _norm 으로 맞춰 전부 푼다.
        _restored = False
        try:
            from keyword_mute import muted_set, unmute
            for _m in [m for m in muted_set(conn, client_id) if _norm(m) == _norm(kw)]:
                unmute(conn, client_id, _m)
                _restored = True
        except Exception as _ue:
            logger.warning(f"[track-keyword] 억제 해제 실패(등록은 계속) [{kw}]: {_ue}")

        if _norm(kw) in existing:
            # 억제 해제만으로 복귀 완료 — 이력·대표 키워드가 이미 있으니 더 쓸 것이 없다.
            # ⚠️ 복귀인데 대표 키워드 목록에서 빠져 있으면(그만 재기가 뺐던 것) 다시 넣어
            #    준다 — 안 넣으면 이력이 끊기는 순간 또 사라진다.
            if _restored and _norm(kw) not in {_norm(k) for k in mk_list} and len(mk_list) < 20:
                mk_list.append(kw)
                conn.execute("UPDATE clients SET main_keywords=? WHERE id=?",
                             (",".join(mk_list), client_id))
            if _restored:
                # 축A 도 복귀 — 그만 재기가 이어진 상품에서 뺐던 키워드를 되살리고,
                # 키워드가 0개가 되어 쉬게 했던 상품이면 다시 깨운다.
                try:
                    from rank_link import get_links_for_client
                    for ln in get_links_for_client(client_id):
                        conn.execute(
                            "INSERT OR IGNORE INTO tracked_keywords (product_id, keyword) VALUES (?, ?)",
                            (ln["tracked_product_id"], kw))
                        conn.execute(
                            "UPDATE tracked_products SET disabled_at='' "
                            "WHERE id=? AND COALESCE(disabled_at,'') != ''",
                            (ln["tracked_product_id"],))
                except Exception as _re:
                    logger.warning(f"[track-keyword] 축A 복귀 실패(복귀는 유효) [{kw}]: {_re}")
            conn.commit()
            if _restored:
                return {"success": True, "restored": True, "keyword": kw,
                        "message": "그만 재기로 빠져 있던 키워드입니다 — 다시 추적합니다(이전 기록 그대로 복귀)."}
            return {"success": True, "already": True, "keyword": kw,
                    "message": "이미 추적 중인 키워드입니다."}
        if len(mk_list) >= 20:
            conn.commit()
            raise HTTPException(status_code=400, detail=(
                "직접 등록 키워드는 업체당 20개까지입니다. 안 쓰는 키워드를 정리한 뒤 등록해주세요."))

        mk_list.append(kw)
        conn.execute("UPDATE clients SET main_keywords=? WHERE id=?",
                     (",".join(mk_list), client_id))

        # 축A 동기화 — 이어진 추적 상품이 있으면 그쪽 키워드 목록에도(멱등)
        linked = 0
        try:
            from rank_link import get_links_for_client
            for ln in get_links_for_client(client_id):
                conn.execute(
                    "INSERT OR IGNORE INTO tracked_keywords (product_id, keyword) VALUES (?, ?)",
                    (ln["tracked_product_id"], kw))
                linked += 1
        except Exception as e:
            logger.warning(f"[track-keyword] 축A 동기화 실패(등록은 유효) [{kw}]: {e}")
        conn.commit()

        # 온디맨드 수집 — 커밋 뒤에 큐잉해야 수집기가 올렸을 때 main_keywords 가 보인다
        queued = False
        try:
            from collector import _enqueue_request
            _enqueue_request(kw)
            queued = True
        except Exception as e:
            logger.warning(f"[track-keyword] 온디맨드 큐 등록 실패(다음 슬롯에서 수집) [{kw}]: {e}")

        logger.info(f"[track-keyword] {client['name']}({client_id}) + '{kw}' "
                    f"(축A {linked}건 동기화, 온디맨드 {'큐잉' if queued else '실패'})")
        return {"success": True, "keyword": kw, "linked_products": linked, "queued": queued,
                "message": ("등록되었습니다. " +
                            ("보통 수 분 안에 첫 순위가 기록됩니다 — 잠시 후 새로고침해 확인하세요."
                             if queued else "다음 수집 회차에 첫 순위가 기록됩니다."))}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[track-keyword] {e}")
        return {"success": False, "detail": str(e)}
    finally:
        conn.close()

@router.post("/{client_id}/untrack-keyword")
def untrack_keyword(client_id: int, req: TrackKeywordRequest,
                    current_user: dict = Depends(get_current_user)):
    """키워드 「그만 재기」 — 양방향 정리 (2026-08-29 대표 확정 「양방향으로 작동」).

    지우지 않는다 — 억제한다(client_keyword_mute). 이유:
      · 업체 키워드는 main_keywords ∪ 분석 이력(client_analyses) 두 갈래라, 대표
        키워드에서 이름만 빼면 이력 갈래로 다시 들어와 영원히 수집된다.
      · 이력을 지우면 순위·분석 기록이 사라져 되돌릴 수 없다. 억제는 재등록 한 번으로
        기록이 그대로 복귀한다.
    한 번에 정리되는 곳(안 맞추면 「뺐는데 어딘가에선 계속 재는」 반쪽이 된다):
      ① clients.main_keywords 에서 제거   ② 억제 표에 기재(수집·기록·보드 전부가 본다)
      ③ 이어진 추적 상품(rank_link)의 tracked_keywords 에서도 제거 — 남은 키워드가
         0개가 된 상품은 지우지 않고 쉬게 한다(disabled_at — 기록 보존).
    """
    kw = (req.keyword or "").strip()
    if not kw:
        raise HTTPException(status_code=400, detail="키워드를 입력해주세요.")
    conn = _get_conn()
    try:
        _verify_client_access(conn, client_id, current_user)
        client = conn.execute("SELECT id, name FROM clients WHERE id=?", (client_id,)).fetchone()
        if not client:
            raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")

        _norm = lambda k: "".join(str(k).split()).lower()
        # main_keywords 는 읽고-고쳐-쓰는 목록 — 등록과 같은 이유로 쓰기 락 안에서 처리.
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT main_keywords FROM clients WHERE id=?", (client_id,)).fetchone()
        mk_list = [k.strip() for k in ((row["main_keywords"] if row else "") or "").split(",") if k.strip()]
        kept = [k for k in mk_list if _norm(k) != _norm(kw)]
        if len(kept) != len(mk_list):
            conn.execute("UPDATE clients SET main_keywords=? WHERE id=?",
                         (",".join(kept), client_id))

        # 억제 기재 — 입력 원문 + 대표 키워드에 있던 공백 변형까지 전부(어긋나면 그
        # 변형이 이력 갈래로 계속 잡힌다).
        from keyword_mute import mute
        _by = current_user.get("id") or 0
        mute(conn, client_id, kw, by=_by)
        for k in mk_list:
            if _norm(k) == _norm(kw) and k != kw:
                mute(conn, client_id, k, by=_by)

        # 축A — 이어진 상품의 키워드 목록에서도 제거
        unlinked = 0
        rested = 0
        try:
            from rank_link import get_links_for_client
            for ln in get_links_for_client(client_id):
                pid = ln["tracked_product_id"]
                cur = conn.execute(
                    "DELETE FROM tracked_keywords WHERE product_id=? AND TRIM(keyword)=?",
                    (pid, kw))
                unlinked += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                left = conn.execute(
                    "SELECT COUNT(*) FROM tracked_keywords WHERE product_id=?",
                    (pid,)).fetchone()[0]
                if left == 0:
                    r2 = conn.execute(
                        "UPDATE tracked_products SET disabled_at=datetime('now','localtime') "
                        "WHERE id=? AND COALESCE(disabled_at,'')=''", (pid,))
                    if r2.rowcount:
                        rested += 1
        except Exception as _ae:
            logger.warning(f"[untrack-keyword] 축A 정리 실패(억제는 유효) [{kw}]: {_ae}")
        conn.commit()

        logger.info(f"[untrack-keyword] {client['name']}({client_id}) - '{kw}' "
                    f"(대표 키워드 {'제거' if len(kept) != len(mk_list) else '없었음'}, "
                    f"상품 키워드 {unlinked}건 제거, 상품 {rested}개 휴면)")
        return {"success": True, "keyword": kw,
                "removed_from_client": len(kept) != len(mk_list),
                "unlinked_product_keywords": unlinked, "rested_products": rested,
                "message": ("양쪽(업체·상품)에서 함께 빠졌습니다. 순위 기록은 보존되며, "
                            "같은 키워드를 다시 등록하면 이전 기록 그대로 복귀합니다.")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[untrack-keyword] {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return {"success": False, "detail": str(e)}
    finally:
        conn.close()


@router.get("/rank-links")
def list_rank_links(current_user: dict = Depends(get_current_user)):
    """업체에 이어진 추적 상품 id 목록 — 화면 통합용 (2026-08-29).

    쇼핑 순위 추적 하단 「전체 도구」가 이 목록으로 **미연결 상품만** 걸러 보여준다 —
    이어진 상품은 업체 상세 보드가 이미 보여주므로 두 번 나오면 같은 것을 두 곳에서
    관리하게 된다(이번 통합이 없애려는 바로 그 문제).
    """
    conn = _get_conn()
    try:
        try:
            rows = conn.execute("SELECT DISTINCT tracked_product_id FROM rank_link").fetchall()
            ids = [r[0] for r in rows]
        except Exception:
            ids = []   # 표가 아직 없는 구버전 DB — 전부 미연결로 보인다(종전 화면 그대로)
        return {"success": True, "linked_product_ids": ids}
    except Exception as e:
        logger.error(f"[rank-links] {e}")
        return {"success": False, "detail": str(e), "linked_product_ids": []}
    finally:
        conn.close()


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


def _latest_analysis_light(conn, client_id: int):
    """업체의 가장 최근(일자) 분석 1건을 경량 파싱해 반환 (없으면 None)."""
    light_cols = """id, client_id, keyword, product_url,
        analysis_json, volume_json, related_json, advertiser_json,
        analyzed_date, created_at, updated_at,
        CASE WHEN report_html IS NOT NULL AND report_html != '' THEN 1 ELSE 0 END as has_report_html"""
    row = conn.execute(
        f"SELECT {light_cols} FROM client_analyses WHERE client_id=? ORDER BY analyzed_date DESC, updated_at DESC LIMIT 1",
        (client_id,)
    ).fetchone()
    return _parse_analysis_row_light(row) if row else None


@router.get("/{client_id}/competitors")
def list_competitors(client_id: int, current_user: dict = Depends(get_current_user)):
    """광고주에 연결된 경쟁사 목록 (각 경쟁사 최근 분석 요약 포함)."""
    conn = _get_conn()
    try:
        _verify_client_access(conn, client_id, current_user)  # 광고주 접근권
        uid = current_user.get("id")
        # 영업사원(viewer)은 '본인이 등록한 경쟁사'만(영업자료 분리). 관리팀은 전체 열람.
        sql = ("SELECT id, name, main_keywords, naver_store_url, updated_at, expires_at, created_by "
               "FROM clients WHERE COALESCE(role,'advertiser')='competitor' AND competitor_of = ? "
               "AND status='active'")
        params = [client_id]
        if str(current_user.get("role") or "") == "viewer":
            sql += " AND created_by = ?"
            params.append(uid)
        sql += " ORDER BY updated_at DESC"
        rows = conn.execute(sql, tuple(params)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["mine"] = (r["created_by"] == uid)
            la = _latest_analysis_light(conn, r["id"])
            d["has_analysis"] = bool(la)
            d["latest_keyword"] = (la or {}).get("keyword", "")
            d["latest_date"] = (la or {}).get("analyzed_date", "")
            # 자동삭제 예정(영업사원 등록분) — 남은 일수 계산
            d["days_left"] = None
            if d.get("expires_at"):
                try:
                    left = (datetime.strptime(d["expires_at"][:10], "%Y-%m-%d") - datetime.now()).days
                    d["days_left"] = max(0, left)
                except Exception:
                    pass
            out.append(d)
        return {"success": True, "data": out}
    finally:
        conn.close()


def cleanup_expired_competitors():
    """만료된(영업사원 등록·30일 경과) 영업 대상·경쟁사 자동 삭제. 스케줄러 일일 호출.
    영업 대상(prospect) 삭제 시 그에 연결된 경쟁사도 함께 정리한다.
    client_analyses는 FK ON DELETE CASCADE로 함께 삭제. 반환: 삭제 건수."""
    conn = _get_conn()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # 만료된 영업 대상·경쟁사(영업사원 등록·30일 경과)
        rows = conn.execute(
            "SELECT id, name FROM clients WHERE COALESCE(role,'advertiser') IN ('prospect','competitor') "
            "AND expires_at IS NOT NULL AND expires_at < ?", (now,)
        ).fetchall()
        expired_ids = {r["id"] for r in rows}
        # 만료된 영업 대상에 매달린 경쟁사(아직 만료 전이라도)도 함께 삭제 — 고아 방지
        for r in list(rows):
            for c in conn.execute(
                "SELECT id, name FROM clients WHERE COALESCE(role,'advertiser')='competitor' AND competitor_of = ?",
                (r["id"],)
            ).fetchall():
                if c["id"] not in expired_ids:
                    expired_ids.add(c["id"])
                    rows.append(c)
        for r in rows:
            conn.execute("DELETE FROM client_analyses WHERE client_id = ?", (r["id"],))
            conn.execute("DELETE FROM clients WHERE id = ?", (r["id"],))
        conn.commit()
        if rows:
            logger.info(f"[cleanup] 만료 영업 대상·경쟁사 {len(rows)}건 자동 삭제: {[r['name'] for r in rows]}")
        return len(rows)
    finally:
        conn.close()


@router.get("/compare")
def compare_clients(advertiser_id: int, competitor_id: int,
                    current_user: dict = Depends(get_current_user)):
    """광고주 vs 경쟁사 최근 분석 1건씩 반환 → FE가 지표 비교·격차·매트릭스 계산.
    경쟁사는 반드시 해당 광고주에 연결된 것이어야 함(교차 접근 방지)."""
    conn = _get_conn()
    try:
        adv_row = _verify_client_access(conn, advertiser_id, current_user)
        comp = conn.execute(
            "SELECT id, name, competitor_of, role, created_by FROM clients WHERE id = ?", (competitor_id,)
        ).fetchone()
        if not comp:
            raise HTTPException(status_code=404, detail="경쟁사를 찾을 수 없습니다.")
        if str(comp["role"] or 'advertiser') != 'competitor' or comp["competitor_of"] != advertiser_id:
            raise HTTPException(status_code=400, detail="해당 광고주에 연결된 경쟁사가 아닙니다.")
        # 영업사원(viewer)은 본인이 등록한 경쟁사만 비교 가능
        if str(current_user.get("role") or "") == "viewer" and comp["created_by"] != current_user.get("id"):
            raise HTTPException(status_code=403, detail="본인이 등록한 경쟁사만 볼 수 있습니다.")
        adv_name = conn.execute("SELECT name FROM clients WHERE id=?", (advertiser_id,)).fetchone()["name"]
        return {"success": True, "data": {
            "advertiser": {"id": advertiser_id, "name": adv_name, "analysis": _latest_analysis_light(conn, advertiser_id)},
            "competitor": {"id": competitor_id, "name": comp["name"], "analysis": _latest_analysis_light(conn, competitor_id)},
        }}
    finally:
        conn.close()


class CompareCoachingRequest(BaseModel):
    advertiser_id: int
    competitor_id: int
    summary: Optional[str] = ''   # FE가 계산한 지표 격차 요약(사람이 읽는 텍스트) — 토큰 절약


@router.post("/compare-coaching")
def compare_coaching(req: CompareCoachingRequest, current_user: dict = Depends(get_current_user)):
    """AI 대결 코칭 — 광고주 vs 경쟁사 지표 격차를 Claude에 넣어 '이기려면' 전략 브리핑 생성.
    FE가 넘긴 격차 요약(summary)을 우선 사용(토큰 절약). CLAUDE_API_KEY 미설정 시 친화적 안내."""
    conn = _get_conn()
    try:
        _verify_client_access(conn, req.advertiser_id, current_user)
        comp = conn.execute(
            "SELECT name, competitor_of, role, created_by FROM clients WHERE id = ?", (req.competitor_id,)
        ).fetchone()
        if not comp or str(comp["role"] or 'advertiser') != 'competitor' or comp["competitor_of"] != req.advertiser_id:
            raise HTTPException(status_code=400, detail="해당 광고주에 연결된 경쟁사가 아닙니다.")
        if str(current_user.get("role") or "") == "viewer" and comp["created_by"] != current_user.get("id"):
            raise HTTPException(status_code=403, detail="본인이 등록한 경쟁사만 볼 수 있습니다.")
        adv_name = conn.execute("SELECT name FROM clients WHERE id=?", (req.advertiser_id,)).fetchone()["name"]

        summary = (req.summary or '').strip()
        if not summary:
            # 요약 미전달 시 최소 컨텍스트 구성 (양측 최근 분석 요약)
            def _one(cid):
                la = _latest_analysis_light(conn, cid) or {}
                vol = (la.get("volume_data") or [{}])
                v0 = vol[0] if isinstance(vol, list) and vol else {}
                return f"키워드={la.get('keyword','?')}, 경쟁강도={v0.get('compIdx','?')}"
            summary = f"[광고주 {adv_name}] {_one(req.advertiser_id)}\n[경쟁사 {comp['name']}] {_one(req.competitor_id)}"

        try:
            from chat import _get_claude_client, CLAUDE_MODEL
        except Exception:
            return {"success": True, "data": {"text": "", "available": False,
                    "message": "AI 코칭을 사용하려면 관리자가 CLAUDE_API_KEY를 설정해야 합니다."}}
        client = _get_claude_client()
        if not client:
            return {"success": True, "data": {"text": "", "available": False,
                    "message": "AI 코칭을 사용하려면 관리자가 CLAUDE_API_KEY를 설정해야 합니다."}}

        system = (
            "너는 10년차 네이버 쇼핑 퍼포먼스 마케팅 전문가다. 광고주가 특정 경쟁사를 이기도록 코칭한다. "
            "반드시 아래 4개 소제목으로만, 한국어로, 실행 가능하고 구체적으로 답하라. 표·마크다운 기호 남발 금지. "
            "1) 한줄 결론(역전 가능성) 2) 지금 당장 할 것 3가지(우선순위·격차 근거) "
            "3) 경쟁사 약점을 파고들 포인트 4) 유지할 강점. 광고주 이름과 경쟁사 이름을 실제로 언급."
        )
        user_msg = (
            f"광고주 '{adv_name}' vs 경쟁사 '{comp['name']}' 비교 지표 격차입니다. "
            f"이 광고주가 이 경쟁사를 이기기 위한 전략을 코칭해줘.\n\n{summary}"
        )
        # 설정된 모델(CLAUDE_MODEL)이 유효하지 않거나 접근 불가일 때를 대비해
        # 널리 접근 가능한 모델로 폴백을 시도한다(서버 .env 오설정에도 자동 복구).
        models_to_try = []
        for m in (CLAUDE_MODEL, "claude-sonnet-4-6", "claude-haiku-4-5"):
            if m and m not in models_to_try:
                models_to_try.append(m)
        last_err = None
        for mdl in models_to_try:
            try:
                resp = client.messages.create(
                    model=mdl, max_tokens=1200,
                    system=system, messages=[{"role": "user", "content": user_msg}],
                )
                text = resp.content[0].text if resp.content else ""
                return {"success": True, "data": {"text": text, "available": True}}
            except Exception as e:
                last_err = e
                logger.error(f"[compare-coaching] Claude 호출 실패(model={mdl}): {type(e).__name__}: {e}")
                continue
        # 모든 모델 실패 — 원인 파악을 위해 오류 요약을 함께 반환(민감정보 없음).
        _detail = f"{type(last_err).__name__}: {str(last_err)[:180]}" if last_err else ""
        return {"success": True, "data": {"text": "", "available": False,
                "message": "AI 코칭 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요." + (f" ({_detail})" if _detail else "")}}
    finally:
        conn.close()


@router.get("/review-trend")
def review_trend(product_url: str, current_user: dict = Depends(get_current_user)):
    """리뷰 증가 기반 실측 판매 추정(2단계) — 같은 상품의 과거 분석 기록에서
    실제 리뷰수 스냅샷(HTML 수집분)을 모아 기간 델타로 월판매를 역산.
    스냅샷 2개 미만·간격 7일 미만이면 available=False (FE는 조용히 생략)."""
    url = (product_url or "").strip().split("?")[0]
    if not url:
        return {"success": True, "data": {"available": False}}
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT analyzed_date, analysis_json FROM client_analyses "
            "WHERE product_url LIKE ? ORDER BY analyzed_date ASC",
            (url.rstrip("/") + "%",),
        ).fetchall()
        points = []
        for r in rows:
            try:
                data = json.loads(r["analysis_json"] or "{}")
                rc = (((data.get("htmlDetail") or {}).get("reviewData")) or {}).get("reviewCount")
                if rc is not None and int(rc) > 0:
                    points.append({"date": r["analyzed_date"], "reviews": int(rc)})
            except Exception:
                continue
        # 같은 날짜는 마지막 값만
        dedup = {}
        for p in points:
            dedup[p["date"]] = p["reviews"]
        series = [{"date": d, "reviews": dedup[d]} for d in sorted(dedup.keys())]
        if len(series) < 2:
            return {"success": True, "data": {"available": False, "points": len(series)}}
        first, last = series[0], series[-1]
        try:
            d0 = datetime.strptime(first["date"][:10], "%Y-%m-%d")
            d1 = datetime.strptime(last["date"][:10], "%Y-%m-%d")
        except Exception:
            return {"success": True, "data": {"available": False}}
        days = (d1 - d0).days
        delta = last["reviews"] - first["reviews"]
        if days < 7 or delta < 0:
            return {"success": True, "data": {"available": False, "days": days}}
        monthly_reviews = delta / days * 30
        # 리뷰 작성률 11.6%(식품 평균) 역산 — SalesEstimation 배너와 동일 가정
        monthly_sales = round(monthly_reviews / 0.116)
        return {"success": True, "data": {
            "available": True,
            "days": days,
            "review_delta": delta,
            "monthly_reviews": round(monthly_reviews, 1),
            "monthly_sales_est": monthly_sales,
            "from_date": first["date"][:10],
            "to_date": last["date"][:10],
        }}
    finally:
        conn.close()


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
        # 키워드별 최신 순위 — 04:30 순위 추적 배치 적재분(300위 범위, 밖이면 행 없음/NULL).
        # 아래 seo.keywordVolume 에만 쓰며, 조회 실패해도 기존 응답은 그대로 나가게 감싼다.
        rank_map = {}
        try:
            for rr in conn.execute("""
                SELECT keyword, rank_position
                FROM client_rank_history
                WHERE client_id = ?
                  AND id IN (SELECT MAX(id) FROM client_rank_history
                             WHERE client_id = ? GROUP BY keyword)
            """, (cid, cid)).fetchall():
                rank_map[rr["keyword"]] = rr["rank_position"]
        except Exception as e:
            logger.warning(f"[portal-summary] rank lookup skipped: {e}")

        daily = []
        kw_volume = []          # 전산(①) 공유 대시보드 소비용 — 아래 seo 블록
        metrics = []            # (키워드, 검색량 숫자, 경쟁강도 숫자) — insight 문구 합성용
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
            # 검색량이 있는 키워드만 담는다(값 없는 행은 전산 화면에서 의미 없음).
            if vol not in (None, "-", ""):
                rk = rank_map.get(r["keyword"])
                kw_volume.append({
                    "keyword": r["keyword"],
                    "volume": vol,
                    "rank": str(rk) if rk not in (None, 0) else "-",
                })
            # 저장값이 문자열("12,300")일 수 있어 숫자 변환 실패 시 그 항목만 제외
            try:
                vnum = int(str(vol).replace(",", "")) if vol not in (None, "-", "") else None
            except (ValueError, TypeError):
                vnum = None
            cnum = comp if isinstance(comp, (int, float)) and not isinstance(comp, bool) else None
            metrics.append((r["keyword"], vnum, cnum))

        total = conn.execute(
            "SELECT COUNT(*) AS c FROM client_analyses WHERE client_id = ?", (cid,)).fetchone()["c"]

        insight = None
        if daily:
            top = daily[0]
            tail = f" ({top['summary']})" if top["summary"] and top["summary"] != "분석 완료" else ""
            insight = (f"최근 {total}건의 자동 분석이 누적되었습니다. "
                       f"현재 {len(daily)}개 키워드를 추적 중이며, 가장 최근 분석 키워드는 "
                       f"'{top['keyword']}'{tail}입니다.")
            # 누적된 실제 분석값에서만 문장 합성(환각 방지) — 값 없으면 해당 문장 생략
            extra = []
            with_vol = [m for m in metrics if m[1] is not None]
            if with_vol:
                tv = max(with_vol, key=lambda m: m[1])
                extra.append(f"검색량이 가장 높은 '{tv[0]}'({tv[1]:,})가 핵심 유입 키워드입니다.")
            with_comp = [m for m in metrics if m[2] is not None]
            if with_comp:
                lc = min(with_comp, key=lambda m: m[2])
                extra.append(f"경쟁강도가 가장 낮은 '{lc[0]}'({lc[2]}%)는 상위 노출을 노려볼 만합니다.")
            if extra:
                insight = insight + " " + " ".join(extra)

        out = {"found": True, "clientId": cid, "insight": insight,
               "dailyReports": daily, "totalDays": total}
        # 전산(①) 공유 대시보드 「SEO 키워드 검색량」 소비 계약 — 2026-07-28 요청 반영.
        # 값이 하나도 없으면 키 자체를 생략한다(전산이 담당자 입력값으로 폴백하도록 합의).
        # 기존 4개 필드의 의미·형식은 그대로 → 전산 미배포 상태여도 무영향.
        if kw_volume:
            out["seo"] = {"keywordVolume": kw_volume}
        return out
    except Exception as e:
        logger.error(f"[portal-summary] {e}")
        return {"found": False, "detail": str(e)}
    finally:
        conn.close()


@router.post("/contract-stage-sync")
def contract_stage_sync_now(current_user: dict = Depends(get_current_user)):
    """계약 단계 「지금 가져오기」 (2026-08-28 대표 확정).

    04:00 동기화와 **같은 함수**를 부른다 — 버튼과 배치가 다른 코드를 쓰면
    「버튼으로는 되는데 새벽엔 안 된다」 같은 어긋남이 생긴다.

    ⚠️ 이 버튼이 필요한 이유: 단계 이름 칸을 새로 만든 직후에는 값이 전부 비어 있고,
       그대로 두면 다음 날 04:00 까지 환불중·홀딩중 칸이 「미상」으로 남는다.
       한 번 눌러 즉시 채운다.
    """
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="관리자만 실행할 수 있습니다.")
    try:
        from scheduler import _run_contract_stage_sync
        res = _run_contract_stage_sync() or {}
        if not res.get("ok"):
            return {"success": False, "detail": res.get("error") or "동기화에 실패했습니다."}
        return {"success": True, "data": res}
    except Exception as e:
        logger.error(f"[contract-stage-sync] {e}")
        return {"success": False, "detail": f"동기화 중 오류: {str(e)[:150]}"}


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

# 영업사원 일일 분석 한도(관리자·매니저는 무제한). 값을 바꾸는 곳은 여기 한 곳.
VIEWER_DAILY_LIMIT = 30

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
        # 영업사원(viewer) 일일 분석 한도.
        # 2026-08-20 대표 지시로 15 → 30. 실측 근거: 영업팀 실제 사용량이 한도에
        # 눌려 있었고(15 에서 끊김), 30 이면 정상 사용이 걸리지 않는다.
        # ⚠️ 이 숫자를 화면에 다시 쓰지 말 것 — 안내 문구는 이 응답의 limit 을 읽는다.
        limit = -1 if role in ('admin', 'superadmin', 'manager') else VIEWER_DAILY_LIMIT

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
