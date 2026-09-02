"""
브라우저 수집기(크롬 확장) 연동 — 2026-08-03

배경: 2026-07-31 네이버 '검색 > 쇼핑' API가 종료(404 SE05)되어 서버에서 검색 결과를
      가져올 방법이 사라졌다. 서버 IP 직접 요청은 봇으로 차단(418)된다.
      실제 사무실 PC의 브라우저는 정상 조회되므로, 사내 전용 크롬 확장이 새벽에
      검색 결과를 모아 이 API로 올려주고 배치는 그 값을 쓴다.

설계 원칙
  · 이 모듈은 '받아서 저장'만 한다. 순위 판정·분석은 기존 코드를 그대로 쓴다.
  · 인증은 전용 토큰(COLLECTOR_TOKEN) 하나. 미설정이면 전 경로를 막는다(기본 안전).
  · 수집분은 collected_serp 에 원본 그대로 쌓고, 배치가 그날치를 읽어간다.
  · 서버는 절대 네이버를 직접 호출하지 않는다(차단·약관 위험을 브라우저 쪽에 두지 않기 위함이 아니라,
    서버 IP로는 애초에 불가능하기 때문).
"""
import os
import json
import sqlite3
import logging
from datetime import date, datetime
from typing import List, Optional

from split_rule import split_ok as _split_ok, normalize as _split_norm

from fastapi import APIRouter, HTTPException, Header, Depends
from auth import get_current_user
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/collector", tags=["collector"])

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")
COLLECTOR_TOKEN = os.getenv("COLLECTOR_TOKEN", "")

# 수집기가 한 번에 가져갈 키워드 상한 — PC 한 대가 새벽에 소화 가능한 양으로 제한
MAX_KEYWORDS = 1200

# 수집 회차 경계 — 확장이 '새벽 1시 시작'(2026-08-04 운영자 확정)이라 수집이 자정을
# 넘지 않으므로 날짜 이동이 필요 없다. 24 = 항상 당일(이동 없음). 저녁 시작으로
# 되돌릴 일이 생기면 이 값을 그 시각(예: 21)으로 바꾸면 된다.
CYCLE_START_HOUR = 24


def _effective_date() -> str:
    """수집 회차 날짜.

    수집이 밤 21시에 시작해 자정을 넘겨 끝나므로, 21시 이후 업로드는 다음 날
    04:30 배치가 쓸 데이터다 — 달력 날짜로 찍으면 자정 전 수집분(전체의 절반)이
    '어제 것'이 되어 배치의 스테일 차단에 걸려 통째로 버려진다.
    낮(온디맨드) 업로드는 그대로 오늘 날짜.
    """
    now = datetime.now()
    if now.hour >= CYCLE_START_HOUR:
        from datetime import timedelta
        return (now.date() + timedelta(days=1)).isoformat()
    return now.date().isoformat()


def init_collector_db():
    """수집 테이블 생성 (멱등)."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS collected_serp (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                collected_date TEXT NOT NULL,
                total INTEGER DEFAULT 0,
                products_json TEXT NOT NULL,
                product_count INTEGER DEFAULT 0,
                source TEXT DEFAULT 'extension',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_collected_serp_uniq
                ON collected_serp(keyword, collected_date);
            CREATE INDEX IF NOT EXISTS idx_collected_serp_date
                ON collected_serp(collected_date);
            CREATE TABLE IF NOT EXISTS collect_requests (
                keyword TEXT PRIMARY KEY,
                requested_at TEXT DEFAULT (datetime('now','localtime')),
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0
            );
        """)
        # 멱등 컬럼 가드 — attempts 없는 구스키마로 생성된 DB에도 안전하게 추가
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(collect_requests)").fetchall()}
            if "attempts" not in cols:
                conn.execute("ALTER TABLE collect_requests ADD COLUMN attempts INTEGER DEFAULT 0")
        except Exception as e:
            logger.warning(f"[collector] attempts 컬럼 가드 실패(무시): {e}")
        # 수집 메타 칸(2026-09-02 신고 #253) — CREATE TABLE IF NOT EXISTS 는 기존 표를
        # 못 고치므로 같은 방식의 멱등 가드로 가산한다. 광고 표식이 toProduct 변환에서
        # 사라지는 문제를 겪은 뒤, 걸러낸 광고 수 등 수집 조건을 함께 남기기로 했다.
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(collected_serp)").fetchall()}
            if "meta_json" not in cols:
                conn.execute("ALTER TABLE collected_serp ADD COLUMN meta_json TEXT")
        except Exception as e:
            logger.warning(f"[collector] meta_json 컬럼 가드 실패(무시): {e}")
        conn.commit()
        logger.info("수집 테이블 준비 완료")
    finally:
        conn.close()


def _auth(token: Optional[str]):
    """전용 토큰 검증 — 미설정이면 전 경로 차단(설정 실수로 열리는 것 방지)."""
    if not COLLECTOR_TOKEN:
        raise HTTPException(status_code=503, detail="수집기 토큰이 서버에 설정되지 않았습니다.")
    if not token or token != COLLECTOR_TOKEN:
        raise HTTPException(status_code=401, detail="수집기 인증 실패")


# ==================== 1) 수집할 키워드 목록 ====================

# ── 24시간 분산 (2026-08-05) ────────────────────────────────────────────
# 종전엔 새벽 01~07시에 전 키워드를 몰아 수집했다. 키워드 954개 × 4페이지 ≒ 3,800회를
# 한 가정용 IP 에서 6시간에 보내는 셈(분당 10.6회)이라, 네이버의 「짧은 시간 내에 너무
# 많은 요청」 문턱에 걸려 **IP 가 차단됐다**(2026-08-05 실사고 — 쇼핑 서비스 접속 제한).
# → 하루 24시간에 흩뿌린다. 시간당 ~40개면 분당 2.7회로 떨어진다.
#
# ⚠️ 키워드마다 **매일 같은 시간대**에 재야 한다. 슬롯이 날마다 흔들리면
#    「어제 5위 → 오늘 7위」가 순위 변동인지 측정 시각 차이인지 구분되지 않는다.
#    그래서 키워드 문자열 해시로 슬롯을 고정한다(키워드가 그대로면 슬롯도 그대로).
#
# 전산① 배려: ①은 08:40 에 순위를 캐시해 간다. 업체(광고주) 키워드를 앞 시간대에
# 몰아 두면 ① 이 보는 값의 신선도가 종전과 비슷하게 유지된다.
# ⚠️ 슬롯 규칙은 collect_slot.py 한 곳에만 둔다 — 화면(client_dashboard)이 「언제 수집되나」를
#    같은 식으로 계산해 직원에게 알려주기 때문이다. 두 곳이 갈리면 화면이 거짓말을 한다.
#    (게이트 환경에 fastapi 가 없어 이 파일을 임포트할 수 없는 것도 같은 이유다 — split_rule 선례)
from collect_slot import PRIORITY_HOURS, LATE_HOURS, slot_of as _slot_rule  # noqa: F401
# 한 시간에 내려주는 최대 개수(밀린 것 포함) — 급증 방지.
# ⚠️ 60 → 40 (2026-08-28). 이 값이 곧 네이버를 두드리는 속도의 상한이다.
#    키워드 1건 = 페이지 4장 = 요청 4번이므로 시간당 요청 수는 이 값 × 4.
#      · 2026-08-05 실제로 IP 가 막혔을 때  시간당 약 1,272요청
#      · 지금(회차가 끊겨 굶던 상태)        시간당 약    56요청
#      · 이 값 40일 때                      시간당      160요청  ← 차단선의 1/8
#    필요량은 826개/24시간 = 시간당 35개라 40이면 하루치를 다 하고도 남는다.
#    ⚠️ 올리기 전에 반드시 위 세 줄을 다시 계산할 것. 총량이 아니라 속도가 차단 기준이다.
HOURLY_CAP = 40


def _slot_of(keyword: str, priority: bool) -> int:
    """키워드 → 수집 시간대(0~23). 규칙은 collect_slot 에 있다(화면과 공유)."""
    return _slot_rule(keyword, priority)


def _tracking_client_ids(conn):
    """순위 추적 자격이 있는 업체 id 목록.

    자격 = 활성 · 광고주(영업대상·경쟁사 제외) · 스토어축 · 자동분석 ON
           · 추적 켜짐(track_enabled) · 추적 기간이 남아 있음(track_until)

    ⚠️ 2026-08-20 이전에는 이 조건이 `clients.main_keywords` 갈래에만 걸려 있었고,
       `tracked_keywords`·`client_analyses` 갈래는 **무필터**였다. 그래서
       계약 만료·환불중·홀딩중 업체와 영업사원이 등록한 영업 대상의 키워드가
       그대로 매일 수집됐다(실측: 유니버스 1,001개 중 상당수). 이제 세 갈래 전부
       이 한 곳을 지난다.

    ⚠️ 2026-08-28: 판정 문장을 tracking_eligibility 로 옮겼다. 08:00 순위 기록 배치가
       같은 뜻의 조건을 4개만 갖고 있어서 **계약이 끝난 업체 65곳의 순위가 계속
       기록되고 있었다**. 이제 수집·기록·추적 상품 세 경로가 같은 문장을 쓴다.
    """
    try:
        from tracking_eligibility import eligible_client_ids
        ids = eligible_client_ids(conn)
        if not ids:
            logger.warning("[collector] 추적 자격 업체 0곳 — 조회 실패이거나 설정 확인 필요")
        return ids
    except Exception as e:
        logger.warning(f"[collector] 추적 자격 업체 조회 실패: {e}")
        return []


def _keyword_universe(conn):
    """수집 대상 키워드 → {키워드: 우선(업체) 여부}.

    세 갈래 모두 **추적 자격이 있는 업체의 것만** 모은다(2026-08-20 개편):
      ① clients.main_keywords      — 담당자가 지정한 대표 키워드
      ② client_analyses            — 그 업체의 분석 이력 키워드
      ③ tracked_keywords           — rank_link 로 그 업체에 이어진 추적 상품의 키워드
    자격 판정은 _tracking_client_ids() 한 곳에만 있다.
    """
    uni = {}
    ids = _tracking_client_ids(conn)
    if not ids:
        logger.warning("[collector] 추적 자격 업체 0곳 — 수집 유니버스 비어 있음(설정 확인 필요)")
        return uni
    ph = ",".join("?" * len(ids))

    # ① 대표 키워드 (「그만 재기」 벨트 — untrack 이 main_keywords 에서도 빼지만 이중 방어)
    try:
        from keyword_mute import muted_map as _mm
        _muted1 = _mm(conn)
        for r in conn.execute(
                f"SELECT id, main_keywords FROM clients WHERE id IN ({ph})", ids):
            for k in (r[1] or "").split(","):
                k = k.strip()
                if k and k not in _muted1.get(r[0], ()):
                    uni[k] = True
    except Exception as e:
        logger.warning(f"[collector] 대표 키워드 조회 실패: {e}")

    # ② 분석 이력 키워드(자격 업체 것만)
    #    ⚠️ 2026-08-29: 「그만 재기」(client_keyword_mute)를 뺀다. 대표 키워드에서 이름을
    #       빼도 분석 이력에 남아 있으면 여기로 다시 들어와 영원히 수집됐다 — 오타 키워드를
    #       지울 길이 없던 원인. 다른 업체가 같은 키워드를 쓰면 그쪽 몫으로는 남는다.
    try:
        from keyword_mute import muted_map
        _muted = muted_map(conn)
        for r in conn.execute(
                f"SELECT client_id, keyword FROM client_analyses WHERE client_id IN ({ph}) "
                "GROUP BY client_id, keyword", ids):
            k = (r[1] or "").strip()
            if k and k not in _muted.get(r[0], ()):
                uni[k] = True
    except Exception as e:
        logger.warning(f"[collector] 업체 키워드 조회 실패: {e}")

    # ③ 홈탭 추적 상품 키워드.
    #    ⚠️ 「자격 업체에 이어진 것만」으로 좁히면 안 된다 — rank_link 는 상품ID가 맞는
    #    경우에만 맺어지는 보조 연결이라, 연결이 없는 추적 상품(실측 400개 중 136개)은
    #    '계약이 끝난 것'이 아니라 '어느 업체 것인지 아직 모르는 것'이다. 그걸 빼면
    #    직원이 손으로 등록한 상품 순위 추적이 통째로 죽는다.
    #    → 규칙: **자격 업체에 이어졌거나, 아무 업체에도 안 이어진 상품**은 포함.
    #            자격 없는 업체(계약만료·환불·홀딩·영업대상)에만 이어진 상품은 제외.
    #    ⚠️ 2026-08-28 보강: 「주인 없는 상품」은 01:20 정리 잡이 이틀 지켜본 뒤
    #    비활성으로 내린다. 내려간 것은 여기서도 빠진다(판정은 tracking_eligibility).
    try:
        from tracking_eligibility import eligible_tracked_product_ids, ensure_disabled_column
        ensure_disabled_column(conn)
        ok_pids = eligible_tracked_product_ids(conn)
        if ok_pids is None:          # 판정 실패 — 종전 규칙으로 폴백(추적이 멈추는 것보다 낫다)
            rows = conn.execute(
                "SELECT DISTINCT k.keyword FROM tracked_keywords k "
                " WHERE k.product_id IN (SELECT tracked_product_id FROM rank_link "
                f"                        WHERE client_id IN ({ph})) "
                "    OR k.product_id NOT IN (SELECT tracked_product_id FROM rank_link)", ids)
        elif ok_pids:
            pp = ",".join("?" * len(ok_pids))
            rows = conn.execute(
                f"SELECT DISTINCT keyword FROM tracked_keywords WHERE product_id IN ({pp})",
                list(ok_pids))
        else:
            rows = []
        for r in rows:
            k = (r[0] or "").strip()
            if k:
                uni.setdefault(k, False)
    except Exception as e:
        logger.warning(f"[collector] 추적 키워드 조회 실패: {e}")

    logger.info(f"[collector] 수집 유니버스 {len(uni)}개 (추적 자격 업체 {len(ids)}곳)")
    return uni


@router.get("/keywords")
def get_collect_keywords(hour: int = None, worker: int = 0, workers: int = 1,
                         x_collector_token: str = Header(None)):
    """확장이 **이번 시간대에** 수집할 키워드를 받아간다.

    hour 를 주면 그 시간대 슬롯 + 오늘 지나간 슬롯 중 아직 못 한 것(밀린 것)을 함께 준다.
    hour 를 안 주면 종전대로 오늘 남은 전량을 준다(구버전 확장 호환 — 무회귀).

    worker/workers 를 주면 그 기계 몫만 준다(2대 이상 나눠 돌릴 때).
    안 주면 workers=1 이라 전량 — 지금 돌고 있는 1대는 아무것도 안 바뀐다.
    """
    _auth(x_collector_token)
    today = _effective_date()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        uni = _keyword_universe(conn)
        done = {r["keyword"] for r in conn.execute(
            "SELECT keyword FROM collected_serp WHERE collected_date = ?", (today,)).fetchall()}
        remaining = {k: p for k, p in uni.items() if k not in done}

        # ── 기계별로 나눠 맡기 (2026-08-27) ──
        # ⚠️ '오늘 할 일'을 세는 total 은 나누기 **전** 값을 쓴다 —
        #    화면에 「전체 866」이라고 떠야 사람이 전체 진척을 읽는다.
        w, wc = _split_norm(worker, workers)
        if wc > 1:
            remaining = {k: p for k, p in remaining.items() if _split_ok(k, w, wc)}

        if hour is None:
            todo = sorted(remaining)[:MAX_KEYWORDS]
            return {"success": True, "date": today, "mode": "all",
                    "total": len(uni), "done": len(done), "todo": len(todo),
                    "keywords": todo}

        h = max(0, min(23, int(hour)))
        now_slot, overdue = [], []
        for k, p in remaining.items():
            s = _slot_of(k, p)
            if s == h:
                now_slot.append(k)
            elif s < h:
                overdue.append((s, k))   # 오늘 지나간 슬롯인데 아직 못 한 것

        now_slot.sort()
        overdue.sort()                    # 오래 밀린 것부터
        picked = now_slot[:HOURLY_CAP]
        if len(picked) < HOURLY_CAP:
            picked += [k for _s, k in overdue[:HOURLY_CAP - len(picked)]]

        return {"success": True, "date": today, "mode": "hourly", "hour": h,
                "total": len(uni), "done": len(done),
                "slot": len(now_slot), "overdue": len(overdue),
                "worker": w, "workers": wc,
                "todo": len(picked), "keywords": picked}
    finally:
        conn.close()


# ==================== 2) 수집 결과 업로드 ====================

class SerpProduct(BaseModel):
    rank: int
    productId: Optional[str] = ""
    title: Optional[str] = ""
    link: Optional[str] = ""
    price: Optional[str] = ""
    mallName: Optional[str] = ""
    brand: Optional[str] = ""
    category1: Optional[str] = ""
    category2: Optional[str] = ""
    category3: Optional[str] = ""
    reviewCount: Optional[str] = ""


class SerpUpload(BaseModel):
    keyword: str
    total: int = 0
    products: List[SerpProduct] = []
    # 사후 재구성용 메타(2026-09-02 신고 #253 교훈 — toProduct 변환에서 광고 표식이
    # 사라져 서버 저장본만으로는 광고 혼입을 판정할 수 없었다). 구확장은 안 보낸다.
    meta: Optional[dict] = None


# 수집이 이만큼 끊겼다가 돌아오면 '환경 장애였다'고 보고 소진된 재시도를 되살린다.
REVIVE_GAP_HOURS = 6


def _revive_after_outage(conn) -> int:
    """수집이 오래 끊겼다 재개되면 시도 5회를 소진한 대기 키워드를 되살린다.

    배경(2026-08-05): 맥북 크롬에 창이 없어(`No current window`) + 네이버 자동입력 방지에
    걸려 수집이 **전량** 실패했는데, 그 실패가 키워드마다 attempts 를 5까지 올려
    `attempts < 5` 필터에서 영구 제외됐다(124건). 확장이 정상으로 돌아와도 이 키워드들은
    다시는 내려가지 않는다 — 「그 키워드가 나쁜 것」과 「수집기 환경이 죽은 것」을
    구분하지 못한 탓이다.

    판정: 마지막 성공 업로드가 6시간 넘게 없다가 지금 성공했다면 환경 장애 복구로 본다.
    이때만 되살리므로, 정상 가동 중에는 발동하지 않는다(무한 재시도 루프 불가 —
    복구 후에는 업로드가 계속 성공해 간격이 6시간을 넘지 않는다).
    """
    try:
        last = conn.execute("SELECT MAX(created_at) FROM collected_serp").fetchone()[0]
        if last:
            gap = conn.execute(
                "SELECT (julianday('now','localtime') - julianday(?)) * 24", (last,)).fetchone()[0]
            if gap is None or gap < REVIVE_GAP_HOURS:
                return 0
        cur = conn.execute(
            "UPDATE collect_requests SET attempts = 0 WHERE status='pending' AND attempts >= 5")
        n = cur.rowcount or 0
        if n:
            logger.info(f"[collector] 수집 재개 감지 — 소진된 대기 키워드 {n}건 재시도 복원")
        return n
    except Exception as e:
        # 복구는 부가 기능 — 실패해도 업로드 자체는 계속돼야 한다
        logger.warning(f"[collector] 재시도 복원 실패(무시): {e}")
        return 0


@router.post("/serp")
def upload_serp(req: SerpUpload, x_collector_token: str = Header(None)):
    """확장이 키워드 1건 수집 결과를 올린다. 같은 날 같은 키워드는 덮어쓴다."""
    _auth(x_collector_token)
    kw = (req.keyword or "").strip()
    if not kw:
        raise HTTPException(status_code=400, detail="keyword 가 비어 있습니다.")
    # 빈 수집은 저장하지 않는다 — '수집 실패'가 '미노출'로 굳는 것을 막기 위함
    # (2026-08-01~03 실제로 1,992건이 그렇게 오염됐다.)
    if not req.products:
        raise HTTPException(status_code=400, detail="상품이 0건입니다. 수집 실패로 보고 저장하지 않습니다.")
    # 상품명·링크가 대부분 비면 확장 toProduct 필드 매핑 오류다 — 조용히 저장하면
    # 배치·분석이 빈 이름으로 오염되므로 여기서 소리내어 거부한다.
    filled = sum(1 for p in req.products if (p.title or "").strip() or (p.link or "").strip())
    if filled < max(1, int(len(req.products) * 0.2)):
        raise HTTPException(status_code=422,
                            detail="상품명·링크가 대부분 비어 있습니다 — 확장 필드 매핑 오류 의심. 팝업의 '수집 원본 샘플'을 확인하세요.")

    today = _effective_date()   # 회차 날짜 — 21시 이후 수집은 다음 날 배치분으로 저장
    payload = json.dumps([p.model_dump() for p in req.products], ensure_ascii=False)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        _revive_after_outage(conn)
        meta_json = json.dumps(req.meta, ensure_ascii=False) if req.meta else None
        conn.execute("""
            INSERT INTO collected_serp (keyword, collected_date, total, products_json, product_count, meta_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(keyword, collected_date) DO UPDATE SET
                total=excluded.total, products_json=excluded.products_json,
                product_count=excluded.product_count, meta_json=excluded.meta_json,
                created_at=datetime('now','localtime')
        """, (kw, today, req.total, payload, len(req.products), meta_json))
        if req.meta:
            # 걸러낸 광고 수가 서버 로그에도 남는다 — 다음 순위 신고 때
            # 「광고 포함 눈 순번」으로 바로 환산해 답할 수 있다(신고 #253 재발 방지).
            logger.info(f"[수집] {kw}: 오가닉 {len(req.products)}개 · 광고 {req.meta.get('adSkipped', '?')}개 제외 · "
                        f"중복 {req.meta.get('dupSkipped', '?')} · 원본 {req.meta.get('rawCount', '?')} · "
                        f"확장 v{req.meta.get('collectorVersion', '?')}")
        # 이 키워드가 요청 큐(주간 온디맨드)에 있었다면 완료 처리
        conn.execute("UPDATE collect_requests SET status='done' WHERE keyword=?", (kw,))
        conn.commit()
    finally:
        conn.close()

    # ── 순위 즉시 기록 (24시간 분산의 짝, 2026-08-05) ──
    # 수집이 하루에 흩어지면 08:00 배치 한 번으로는 그날치를 다 못 담는다.
    # 올라온 그 자리에서 이 키워드의 순위를 적는다(하루 1점 갱신이라 배치와 중복 무해).
    # 실패해도 업로드는 성공으로 돌려준다 — 수집이 멈추면 안 된다.
    recorded = {}
    try:
        from rank_record import record_ranks_for_keyword
        recorded = record_ranks_for_keyword(
            kw, [_normalize_collected(p.model_dump()) for p in req.products])
    except Exception as e:
        logger.warning(f"[collector] 순위 즉시 기록 실패(업로드는 성공) [{kw}]: {e}")
    return {"success": True, "keyword": kw, "saved": len(req.products), "ranked": recorded}


# ==================== 3) 수집 현황 ====================

@router.get("/status")
def collect_status(x_collector_token: str = Header(None)):
    """오늘 얼마나 모였는지 — 확장 팝업·운영자 확인용."""
    _auth(x_collector_token)
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT collected_date, COUNT(*) AS keywords, SUM(product_count) AS products,
                   MAX(created_at) AS last_at
            FROM collected_serp
            WHERE collected_date >= date('now','localtime','-6 day')
            GROUP BY collected_date ORDER BY collected_date DESC
        """).fetchall()
        pending = conn.execute(
            "SELECT COUNT(*) FROM collect_requests WHERE status='pending' AND attempts < 5").fetchone()[0]
        return {"success": True, "today": today, "pendingRequests": pending,
                "days": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/health")
def collect_health(current_user: dict = Depends(get_current_user)):
    """수집 파이프라인 건강 상태 — 화면 상단 경보 배너용 (로그인 사용자 전용).

    수집(맥북 크롬 확장)이 조용히 멈춰도 아무 신호가 없어, 다음 날 아침에야
    「순위가 안 쌓였다」로 발견되던 공백을 메운다(2026-08-05 실사고: 8/5 새벽
    수집 0건 → 08:00 순위 기록 0건, 종일 인지 못함).

    판정 — 서빙 창(오늘·어제 수집분)이 곧 사용 가능 조건이다:
      ok    : 오늘 수집분 있음 (정상)
      stale : 오늘 없음 + 어제 있음 → 분석은 되지만 **오늘 자정까지**.
              오늘 밤 수집이 돌지 않으면 내일 분석 불가.
      down  : 오늘·어제 모두 없음 → 분석 불가(수집 즉시 필요)
    """
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT collected_date, COUNT(*) AS keywords, MAX(created_at) AS last_at
            FROM collected_serp
            WHERE collected_date >= date('now','localtime','-1 day')
            GROUP BY collected_date ORDER BY collected_date DESC
        """).fetchall()
    finally:
        conn.close()

    by_date = {r["collected_date"]: r for r in rows}
    t = by_date.get(today)
    others = [r for d, r in by_date.items() if d != today]
    if t and (t["keywords"] or 0) > 0:
        state, msg = "ok", ""
    elif others:
        y = others[0]
        state = "stale"
        msg = (f"오늘 새벽 수집이 실행되지 않았습니다(마지막 수집 {y['collected_date']}). "
               "분석은 어제 수집분으로 정상 동작하지만 오늘 자정까지만 유효합니다 — "
               "수집 PC(맥북)의 전원·크롬·확장 상태를 확인해 주세요.")
    else:
        state = "down"
        msg = ("최근 2일간 수집분이 없어 분석이 불가합니다. "
               "수집 PC(맥북)의 전원·크롬·확장을 확인한 뒤 「지금 수집」을 실행해 주세요.")

    return {"success": True, "state": state, "today": today, "message": msg,
            "todayKeywords": (t["keywords"] if t else 0),
            "lastCollectedDate": (rows[0]["collected_date"] if rows else None),
            "lastAt": (rows[0]["last_at"] if rows else None)}


def _safe_int(v):
    """문자열 가격('12,900')·None 등을 정수로. 실패 시 0."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(str(v).replace(",", "").replace("원", "").strip() or 0)
    except (ValueError, TypeError):
        return 0


def _normalize_collected(p: dict) -> dict:
    """수집분 상품 1건을 _parse_api_item(naver_crawler.py) 출력과 '완전히 같은 키'로 변환한다.

    ⚠️ 이 정규화가 없으면 순위 매칭(find_product_rank_from_cache 는 product_url·product_id 를 읽음)과
    분석(auto_analysis 는 product_name·store_name 을 읽음)이 전부 빈값·미스매치가 되어,
    수집이 정상이어도 화면은 계속 '미노출'로 나온다. price 도 int 여야 산술이 깨지지 않는다.
    수집기(SerpProduct)는 productId·title·link·mallName·price(문자열)로 저장하므로 여기서 매핑한다.
    """
    return {
        "rank": p.get("rank", 0),
        "product_id": str(p.get("productId", "") or ""),
        "product_name": p.get("title", "") or "",
        "price": _safe_int(p.get("price")),
        "hprice": None,
        "store_name": p.get("mallName", "") or "",
        "image_url": p.get("image", "") or "",
        "product_url": p.get("link", "") or "",
        "brand": p.get("brand", "") or "",
        "maker": p.get("brand", "") or "",
        "category1": p.get("category1", "") or "",
        "category2": p.get("category2", "") or "",
        "category3": p.get("category3", "") or "",
        "product_type": "",
        # 리뷰/평점/구매수는 SERP 목록에 없다(_parse_api_item 도 0). 리뷰는 상세 크롤링 경로에서만.
        "review_count": 0,
        "rating": 0,
        "purchase_count": 0,
        # 수집분 표식 — 디버깅·감사용
        "review_count_collected": _safe_int(p.get("reviewCount")),
    }


def load_collected(keyword: str, on_date: Optional[str] = None) -> Optional[dict]:
    """배치용 — 수집분에서 키워드 1건을 꺼내 _parse_api_item 포맷으로 정규화해 돌려준다.

    반환: {'total': int, 'prods': [ _parse_api_item 과 동일 키의 dict, … ]} 또는 None.
    scheduler 의 find_product_rank_from_cache·auto_analysis 가 그대로 소비할 수 있어야 한다.
    """
    on_date = on_date or date.today().isoformat()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute(
            "SELECT total, products_json FROM collected_serp WHERE keyword=? AND collected_date=?",
            (keyword, on_date)).fetchone()
        if not r:
            return None
        try:
            raw = json.loads(r["products_json"] or "[]")
        except json.JSONDecodeError:
            return None
        if not raw:
            return None
        prods = [_normalize_collected(p) for p in raw]
        return {"total": r["total"] or 0, "prods": prods}
    finally:
        conn.close()
# ==================== 4) 주간 온디맨드 요청 큐 ====================

@router.get("/requests")
def get_pending_requests(worker: int = 0, workers: int = 1,
                         x_collector_token: str = Header(None)):
    """확장이 1분 주기로 폴링 — 직원이 낮에 새 키워드를 분석하면 여기 쌓인다.

    소량(상한 10)만 내려 IP 부하를 묶는다. 수집·업로드되면 upload_serp 가 done 처리.

    ⚠️ 이 큐도 기계별로 나눠야 한다(2026-08-27). 두 대가 같은 큐를 보면
       같은 키워드를 각각 받아 **5회 재시도 한도를 2.5회 만에 태운다** —
       실제로는 절반만 시도하고 포기하게 된다. 순위 목록만 나누면 안 되는 이유다.
    """
    _auth(x_collector_token)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        # 오래된 완료분 정리(테이블 비대 방지)
        conn.execute("DELETE FROM collect_requests WHERE status='done' AND requested_at < datetime('now','localtime','-7 day')")
        # 5회 소진 후에도 재요청이 없는 사장 pending 도 7일 뒤 정리(계기판·테이블 비대 방지)
        conn.execute("DELETE FROM collect_requests WHERE status='pending' AND attempts >= 5 AND requested_at < datetime('now','localtime','-7 day')")
        # 전달 5회가 넘도록 수집이 안 된 키워드(오타·결과 0건)는 제외 — 1분마다 영원히
        # 재시도해 네이버를 계속 두드리는 폭주를 막는다. 직원이 그 키워드를 다시 분석하면
        # _enqueue_request 가 attempts 를 리셋해 5회 더 시도한다.
        w, wc = _split_norm(worker, workers)
        # 나눠 맡을 때는 걸러낸 뒤 10개가 되도록 넉넉히 읽는다(그냥 LIMIT 10 이면
        # 앞 10개가 전부 남의 몫일 때 자기 몫이 있는데도 빈손으로 돌아간다).
        rows = conn.execute("""
            SELECT keyword FROM collect_requests
            WHERE status='pending' AND attempts < 5
            ORDER BY requested_at ASC LIMIT ?
        """, (10 if wc <= 1 else 200,)).fetchall()
        kws = [r["keyword"] for r in rows if _split_ok(r["keyword"], w, wc)][:10]
        if kws:
            conn.executemany(
                "UPDATE collect_requests SET attempts = attempts + 1 WHERE keyword=?",
                [(k,) for k in kws])
        conn.commit()
        return {"success": True, "keywords": kws}
    finally:
        conn.close()


def prune_self_tail_requests() -> dict:
    """요청 큐에서 「배치가 스스로 되넣은 것」을 털어낸다(2026-08-28).

    ⚠️ 이 함수가 생긴 경위 — 실측으로 확인된 되먹임 고리다.
       08:00·08:30 배치가 순위를 적으려는데 그 키워드의 수집분이 없으면 요청 큐에
       다시 넣었다. 쇼핑 API 가 7월 말 종료돼 수집분이 없으면 무조건 이 길을 탔고,
       **수집이 못 따라간 키워드가 매일 자기를 다시 큐에 넣는** 구조가 됐다.
       큐가 813건까지 부풀자 확장은 매시간 12건(상한)을 거기에 먼저 쓰고,
       정작 순위 추적 몫은 시간당 2~3개만 했다. 하루 345개 중 288개가 이 큐였다.

    되먹임 자체는 호출부에서 막았다(enqueue_on_miss=False). 여기서는 **이미 쌓인
    것**을 턴다. 기준은 단순하다:

      · 오늘 들어온 요청            → 남긴다 (직원이 방금 화면에서 찾은 것일 수 있다)
      · 하루 지났는데 유니버스 안   → 지운다 (슬롯 수집이 어차피 매일 배정한다)
      · 유니버스 밖                 → 남긴다 (직원 화면 검색분 — 슬롯이 안 맡는다)
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        uni = set(_keyword_universe(conn).keys())
        if not uni:
            return {"pruned": 0, "kept": 0}
        rows = conn.execute(
            "SELECT keyword FROM collect_requests "
            " WHERE status='pending' "
            "   AND date(requested_at) < date('now','localtime')").fetchall()
        gone = [r["keyword"] for r in rows if r["keyword"] in uni]
        if gone:
            conn.executemany("DELETE FROM collect_requests WHERE keyword=? AND status='pending'",
                             [(k,) for k in gone])
            conn.commit()
        kept = conn.execute(
            "SELECT COUNT(*) FROM collect_requests WHERE status='pending'").fetchone()[0]
        logger.info(f"[collector] 큐 되먹임 정리 — {len(gone)}건 제거(슬롯이 맡는 키워드) · 남은 대기 {kept}건")
        return {"pruned": len(gone), "kept": kept}
    except Exception as e:
        logger.warning(f"[collector] 큐 되먹임 정리 실패(무시): {e}")
        return {"pruned": 0, "kept": 0}
    finally:
        conn.close()


def _enqueue_request(keyword: str):
    """수집분이 없는 키워드를 요청 큐에 넣는다(중복 무해 — 멱등).

    이미 done 인 키워드도 다시 pending 으로 되돌린다 — done 은 '그날 수집됨'일 뿐이라
    2일 이상 지나 서빙이 다시 miss 나면 재수집이 필요하기 때문.
    """
    kw = (keyword or "").strip()
    if not kw:
        return
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            conn.execute("""
                INSERT INTO collect_requests (keyword, status)
                VALUES (?, 'pending')
                ON CONFLICT(keyword) DO UPDATE SET
                    status='pending',
                    requested_at=datetime('now','localtime'),
                    attempts=0
                WHERE collect_requests.status != 'pending'
                   OR collect_requests.attempts >= 5
            """, (kw,))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[collector] 요청 큐 등록 실패(무시): {e}")


# ==================== 5) 검색 API 대체 서빙 ====================

def _to_api_item(p: dict) -> dict:
    """수집분 상품 1건 → 네이버 검색 API 원본 item 형식(역변환).

    search_naver_shopping_api 의 반환을 그대로 흉내내기 위한 것.
    소비자는 전부 _parse_api_item 을 거치므로, 그 함수가 읽는 키
    (title·productId·link·lprice·mallName·brand·maker·image·category1~3·productType)만 맞추면 된다.
    """
    return {
        "title": p.get("title", "") or "",
        "productId": str(p.get("productId", "") or ""),
        "link": p.get("link", "") or "",
        "lprice": str(_safe_int(p.get("price"))),
        "hprice": "",
        "mallName": p.get("mallName", "") or "",
        "image": "",
        "brand": p.get("brand", "") or "",
        "maker": p.get("brand", "") or "",
        "category1": p.get("category1", "") or "",
        "category2": p.get("category2", "") or "",
        "category3": p.get("category3", "") or "",
        "productType": "",
    }


def serve_from_collected(keyword: str, display: int = 100, start: int = 1,
                         enqueue_on_miss: bool = True) -> Optional[dict]:
    """죽은 쇼핑 검색 API 를 수집분으로 대체 서빙한다.

    search_naver_shopping_api 최상단에서 호출된다(원본 API 응답과 같은 형식으로 반환).
    · 오늘/어제(2일 내) 수집분이 있으면 → {'total':…, 'items':[원본형식…]} 로 페이징 서빙
    · 없으면 → 요청 큐에 등록하고 None (호출부가 기존 API 경로로 폴백 — API 부활 시 무회귀)

    이 한 지점으로 분석기·광고주 분석·키워드 노출·자동 분석이 전부 수집분 위에서 돌게 된다.
    낮 분석은 새벽(03시) 스냅샷 기준이라 '실시간'은 아니지만, 순위·시장 구도가 하루 안에
    급변하는 경우는 드물어 실사용상 차이가 작다.
    """
    kw = (keyword or "").strip()
    if not kw:
        return None
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute("""
            SELECT total, products_json, collected_date FROM collected_serp
            WHERE keyword=? AND collected_date >= date('now','localtime','-1 day')
            ORDER BY collected_date DESC LIMIT 1
        """, (kw,)).fetchone()
    finally:
        conn.close()
    if not r:
        if enqueue_on_miss:
            _enqueue_request(kw)
        return None
    try:
        raw = json.loads(r["products_json"] or "[]")
    except json.JSONDecodeError:
        return None
    if not raw:
        return None
    raw.sort(key=lambda p: p.get("rank", 0) or 0)
    end = start + max(1, min(display, 100)) - 1
    page = [_to_api_item(p) for p in raw if start <= (p.get("rank", 0) or 0) <= end]
    # collectedDate: 순위 기록 배치가 '오늘분인지' 판별하는 데 쓴다 — 어제 스냅샷이
    # 오늘 순위로 기록되는 것(수집 실패 가드 우회)을 막기 위한 필수 표식.
    return {"total": r["total"] or len(raw), "start": start,
            "display": len(page), "items": page,
            "collectorServed": True, "collectedDate": r["collected_date"]}
