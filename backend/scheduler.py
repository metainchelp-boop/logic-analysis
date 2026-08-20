"""
로직 분석 프로그램 v3 - 스케줄러 모듈
APScheduler 기반 통합 스케줄러
- 04:00 계약단계 동기화 · 08:00 순위 추적 (맥북 브라우저 수집 01:00~07:00 분 소비)
- 08:30 전체 분석 + HTML 보고서 (08:00 캐시 재사용) → 09:30 리포트 발송(현재 발송 비활성 — 운영자 확인 후 재개)
  ※ 2026-07-27 업무시간 502 사고로 전 배치를 새벽으로 이동(업무 시작 전 종료)
- 일일 API 호출: ~147회 (기존 25,000+에서 99% 절감)
"""
import logging
import time
import json
from datetime import datetime, date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# 글로벌 스케줄러 인스턴스
_scheduler: BackgroundScheduler = None

# 08:00 순위 추적에서 캐시한 결과 → 08:30 분석에서 재사용
_api_cache = {}       # {keyword: {"prods": [...], "total": int}}
_api_cache_date = ""  # 캐시 날짜 (당일만 유효)


def start_scheduler():
    """스케줄러 시작 — 앱 시작 시 호출 (멀티 워커 환경에서 1개만 실행)"""
    global _scheduler
    if _scheduler and _scheduler.running:
        logger.warning("스케줄러가 이미 실행 중입니다.")
        return

    # 멀티 워커 환경: 파일 잠금으로 하나의 워커만 스케줄러 실행
    import fcntl
    try:
        _lock = open('/tmp/.scheduler.lock', 'w')
        fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # 잠금 획득 — 이 워커가 스케줄러 담당
        globals()['_scheduler_lock'] = _lock  # GC 방지
    except (IOError, OSError):
        logger.info("⏭ 스케줄러 — 다른 워커에서 이미 실행 중, 건너뜀")
        return

    # misfire_grace_time: 기동 직후/순간 부하로 발화시각을 놓쳐도 1시간 내면 실행
    # coalesce: 밀린 실행을 1번으로 합침 (일일 순위수집이 조용히 누락되는 것 방지)
    _scheduler = BackgroundScheduler(
        timezone="Asia/Seoul",
        job_defaults={"misfire_grace_time": 3600, "coalesce": True, "max_instances": 1},
    )

    # ⏰ 배치 시간대 이동 (2026-07-27, 운영자 승인)
    #   사유: 09:00 전체분석은 업체수×키워드마다 1~2초 대기하며 1시간 이상 도는 장시간 배치라
    #   업무시간(10시대)까지 물려, 같은 컨테이너(RAM 1.9GB·uvicorn 워커 5)의 사용자 요청이
    #   502로 실패하는 사고가 있었다(직원 신고 07-27 10:12). 체인 전체를 새벽으로 당겨
    #   업무 시작(09:00) 전에 끝나게 한다. 의존 순서(계약동기화→순위추적 캐시→분석→발송)는 유지.

    # 0) 계약단계 동기화 — 매일 04:00 (구 07:30. 분석 배치 전에 실행해 만료 업체를 제외)
    #    ※ ad-sync 소비 합의(2026-07-20) 조건 유지: 하루 1회·읽기 전용·단계당 1콜,
    #      ③ 광고센터의 06:00과 시간대 분리(04:00). 시각 변경은 ①에 통지 대상.
    _scheduler.add_job(
        _run_contract_stage_sync,
        trigger=CronTrigger(hour=4, minute=0),
        id="contract_stage_sync",
        name="계약단계 동기화 (04:00)",
        replace_existing=True,
        max_instances=1,
    )

    # 1) 순위 추적 — 매일 08:00 (2026-08-04 운영자 확정: 수집 01~07시 완료 후 소비, 데드라인 10시)
    _scheduler.add_job(
        _run_rank_tracking,
        trigger=CronTrigger(hour=8, minute=0),
        id="rank_tracking",
        name="순위 추적 (08:00)",
        replace_existing=True,
        max_instances=1,
    )

    # 2) 전체 분석 + 보고서 — 매일 08:30 (08:00 캐시 재사용)
    #    발송(08:00)까지 3시간 확보 — 기존 09→10시 간격(1시간)보다 여유가 크다.
    _scheduler.add_job(
        _run_daily_analysis,
        trigger=CronTrigger(hour=8, minute=30),
        id="daily_analysis",
        name="전체 분석 + 보고서 (08:30)",
        replace_existing=True,
        max_instances=1,
    )

    # 3) 일일 리포트 발송 — 08:00 (구 10:00. 분석 완료 후 발송 · 업무 시작 전 도착)
    _scheduler.add_job(
        _run_daily_report,
        trigger=CronTrigger(hour=9, minute=30),
        id="daily_report",
        name="일일 리포트 발송 (08:00)",
        replace_existing=True,
        max_instances=1,
    )

    # 4) DB 자동 백업 — 매일 00:30 (업체/광고주 데이터 보호)
    _scheduler.add_job(
        _run_daily_db_backup,
        trigger=CronTrigger(hour=0, minute=30),
        id="daily_db_backup",
        name="DB 자동 백업 (00:30)",
        replace_existing=True,
        max_instances=1,
    )

    # 5) 분석 보관정책 — 매일 01:00 (백업 직후). client_analyses 옛 일별 스냅샷 정리로
    #    DB 무한 성장 방지(디스크 풀 사고 예방). 전산① portal-summary 무영향(아래 함수 주석).
    _scheduler.add_job(
        _run_client_analyses_retention,
        trigger=CronTrigger(hour=1, minute=0),
        id="client_analyses_retention",
        name="분석 보관정책 (01:00)",
        replace_existing=True,
        max_instances=1,
    )

    # 6) 순위 두 축 브리지 갱신 — 매일 01:20 (보관정책 직후, 배치 전 새벽 한산한 시각).
    #    낮에 새로 등록된 업체·추적 상품을 이어 붙이고 삭제된 것들을 털어낸다.
    #    링크만 건드리므로 순위 데이터·조회 경로에는 영향이 없다.
    _scheduler.add_job(
        _run_rank_link_maintenance,
        trigger=CronTrigger(hour=1, minute=20),
        id="rank_link_maintenance",
        name="순위 축 브리지 갱신 (01:20)",
        replace_existing=True,
        max_instances=1,
    )

    # 7) 플레이스 자동 등록 추적 대상 정리 — 매일 01:40 (플레이스 수집 06:30 한참 전).
    #    제안서·분석을 뽑으면 추적이 자동 등록되므로(영업사원 동선 0), 계약으로 이어지지 않은
    #    건이 쌓여 매일 수집량을 무한히 키우지 않도록 **자동 등록분만** 30일 미사용 시 비활성.
    #    사람이 직접 등록한 행은 손대지 않는다.
    _scheduler.add_job(
        _run_place_auto_track_cleanup,
        trigger=CronTrigger(hour=1, minute=40),
        id="place_auto_track_cleanup",
        name="플레이스 자동 추적 정리 (01:40)",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.start()
    logger.info("✅ 스케줄러 시작 (계약동기화: 04:00, 순위: 08:00, 분석: 08:30, 리포트: 09:30(발송 비활성), DB백업: 00:30, 보관정책: 01:00, 축 브리지: 01:20, 플레이스 자동추적 정리: 01:40)")

    # 1회성 VACUUM — 보관정책 1회 삭제(2026-08-04)로 생긴 freelist(~2.2GB)를 디스크로 반환.
    # 스케줄러는 단일 워커에서만 기동(위 파일락)하므로 여기서 부르면 중복 실행 없음.
    _run_one_time_vacuum()


def stop_scheduler():
    """스케줄러 중지 — 앱 종료 시 호출"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("⏹ 스케줄러 종료")
    _scheduler = None


def reschedule_report(hour: int, minute: int):
    """일일 리포트 발송 시간 변경"""
    global _scheduler
    if not _scheduler or not _scheduler.running:
        logger.warning("스케줄러가 실행 중이 아닙니다.")
        return

    try:
        _scheduler.reschedule_job(
            "daily_report",
            trigger=CronTrigger(hour=hour, minute=minute),
        )
        logger.info(f"📅 리포트 발송 시간 변경: {hour:02d}:{minute:02d}")
    except Exception as e:
        logger.error(f"리포트 스케줄 변경 실패: {e}")


# ==================== 04:00 계약단계 동기화 (전산 ad-sync 소비) ====================
#   합의(2026-07-20): ① 메타 전산의 GET /api/ad-sync/contracts 를 ②(로직분석)도 소비.
#   계약이 끝난 단계(계약 만료·환불중·홀딩중) 업체는 자동 추적을 자동 중지(⏸),
#   운영 단계(진행중·전략 관리·사후 관리)로 복귀하면 자동 재개(▶).
#   - 읽기 전용 · 하루 1회(04:00 — ③ 광고센터 06:00과 시간 분리) · 단계당 1콜(총 6콜).
#   - 직원 수동 토글(auto_analysis_manual=1) 업체는 절대 덮어쓰지 않음(수동 우선).
#   - ERP_AD_SYNC_API_KEY 미설정·API 실패 시 아무것도 바꾸지 않음(안전 기본값).

PAUSE_STAGES = ["계약 만료", "환불중", "홀딩중"]          # 자동 중지 대상
RESUME_STAGES = ["진행중", "전략 관리", "사후 관리"]      # 자동 재개 대상(운영 지속 단계)


def _sync_norm(s):
    """업체명 정규화(공백 제거·소문자) — 전산 상호명 ↔ 로직분석 업체명 매칭용"""
    import re as _re
    return _re.sub(r"\s+", "", str(s or "")).lower()


def _sync_store_slug(url):
    """스마트스토어 URL → 스토어 슬러그 (이름보다 안정적인 매칭 키)"""
    import re as _re
    m = _re.search(r"smartstore\.naver\.com/([^/?#]+)", str(url or ""))
    return m.group(1).lower() if m else ""


def _decide_stage_actions(client_rows, stage_by_name, stage_by_slug):
    """순수 판정 로직(단위테스트 대상): 업체 행들과 전산 단계 맵 → (pause_ids, resume_ids).
    수동 토글 업체 제외, 매칭 안 되면 아무것도 안 함."""
    pause_ids, resume_ids = [], []
    for c in client_rows:
        if int(c["auto_analysis_manual"] or 0) == 1:
            continue  # 수동 우선
        stage = None
        slug = _sync_store_slug(c["naver_store_url"])
        if slug and slug in stage_by_slug:
            stage = stage_by_slug[slug]
        else:
            for nm in (c["name"], c["business_name"]):
                key = _sync_norm(nm)
                if key and key in stage_by_name:
                    stage = stage_by_name[key]
                    break
        if stage is None:
            continue  # 매칭 실패 — 변경 없음(수동 토글로 커버)
        cur = int(c["auto_analysis"] if c["auto_analysis"] is not None else 1)
        if stage in PAUSE_STAGES and cur != 0:
            pause_ids.append(c["id"])
        elif stage in RESUME_STAGES and cur == 0:
            resume_ids.append(c["id"])
    return pause_ids, resume_ids


def _run_contract_stage_sync():
    """04:00 — 전산 계약 단계 기반 자동 추적 중지/재개"""
    import os
    import sqlite3
    import requests

    api_key = os.getenv("ERP_AD_SYNC_API_KEY", "")
    if not api_key:
        logger.info("계약단계 동기화: ERP_AD_SYNC_API_KEY 미설정 — 건너뜀 (합의 후 서버 .env에 설정)")
        return
    base = os.getenv("ERP_BASE_URL", "http://api.metainc.co.kr").rstrip("/")
    DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")

    logger.info("🔄 계약단계 동기화 시작 (전산 ad-sync)")
    stage_by_name, stage_by_slug = {}, {}
    end_by_name, end_by_slug = {}, {}      # 전산 계약 종료일(가장 늦은 회차)
    fetched_stages = 0
    for stage in PAUSE_STAGES + RESUME_STAGES:
        try:
            resp = requests.get(
                f"{base}/api/ad-sync/contracts",
                params={"stage": stage, "has_contract": "true"},
                headers={"X-Api-Key": api_key}, timeout=15,
            )
            if resp.status_code != 200:
                logger.warning(f"  계약단계 조회 {resp.status_code} (stage={stage}) — 이 단계 건너뜀")
                continue
            items = ((resp.json() or {}).get("result") or {}).get("items") or []
            fetched_stages += 1
            for it in items:
                # 계약 종료일 — 여러 계약(회차)이 있으면 **가장 늦은 종료일**을 쓴다.
                # 연장 계약이 있는데 옛 회차 날짜로 추적을 끊으면 안 되기 때문.
                ends = [c.get("end_date") for c in (it.get("contracts") or []) if c.get("end_date")]
                end = max(ends) if ends else None
                nm = _sync_norm(it.get("company_name"))
                if nm:
                    stage_by_name[nm] = stage
                    if end:
                        end_by_name[nm] = max(end, end_by_name.get(nm, ""))
                slug = _sync_store_slug(it.get("store_url"))
                if slug:
                    stage_by_slug[slug] = stage
                    if end:
                        end_by_slug[slug] = max(end, end_by_slug.get(slug, ""))
        except Exception as e:
            logger.warning(f"  계약단계 조회 실패(stage={stage}): {e} — 이 단계 건너뜀")

    if fetched_stages == 0:
        logger.warning("계약단계 동기화: 조회 전부 실패 — 아무것도 변경하지 않음(안전 기본값)")
        return

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, business_name, naver_store_url, auto_analysis, track_until, "
            "COALESCE(auto_analysis_manual, 0) AS auto_analysis_manual "
            "FROM clients WHERE status = 'active' AND COALESCE(role,'advertiser')='advertiser' "
            "AND COALESCE(vertical,'store')='store'"
        ).fetchall()
        pause_ids, resume_ids = _decide_stage_actions(rows, stage_by_name, stage_by_slug)
        for cid in pause_ids:
            conn.execute("UPDATE clients SET auto_analysis = 0 WHERE id = ?", (cid,))
        for cid in resume_ids:
            conn.execute("UPDATE clients SET auto_analysis = 1 WHERE id = ?", (cid,))

        # 계약 종료일 동기화 — 전산이 알려준 날짜를 추적 종료일로 그대로 쓴다.
        # 계약이 연장되면 종료일도 따라 늘어나므로 사람이 손댈 일이 없다.
        # ⚠️ 수동 토글 업체는 여기서도 건드리지 않는다(단계 동기화와 같은 원칙).
        synced_end = 0
        for c in rows:
            if int(c["auto_analysis_manual"] or 0) == 1:
                continue
            end = None
            slug = _sync_store_slug(c["naver_store_url"])
            if slug and slug in end_by_slug:
                end = end_by_slug[slug]
            else:
                for nm in (c["name"], c["business_name"]):
                    k = _sync_norm(nm)
                    if k and k in end_by_name:
                        end = end_by_name[k]
                        break
            if end and end != (c["track_until"] or ""):
                conn.execute("UPDATE clients SET track_until = ? WHERE id = ?", (end, c["id"]))
                synced_end += 1
        conn.commit()
        conn.close()
        logger.info(
            f"✅ 계약단계 동기화 완료: 자동 중지 {len(pause_ids)}건 · 자동 재개 {len(resume_ids)}건 "
            f"· 계약 종료일 반영 {synced_end}건 "
            f"(전산 매칭 {len(stage_by_name)}개 업체, 수동 설정 업체는 유지)"
        )
    except Exception as e:
        logger.error(f"❌ 계약단계 동기화 DB 반영 실패: {e}")


# ==================== 08:00 순위 추적 ====================

def _collect_all_keywords(conn):
    """홈탭 추적 상품 + 업체 키워드 수집 (공통 유틸)"""
    from database import get_all_tracked_products, get_keywords_for_product

    # 홈탭 추적 상품 키워드
    home_products = get_all_tracked_products() or []
    home_keyword_map = {}  # {keyword: [(product, kw_info), ...]}
    for product in home_products:
        keywords = get_keywords_for_product(product["id"])
        for kw_info in keywords:
            kw = kw_info["keyword"].strip()
            if kw:
                if kw not in home_keyword_map:
                    home_keyword_map[kw] = []
                home_keyword_map[kw].append((product, kw_info))

    # 업체 키워드
    clients = conn.execute(
        "SELECT id, name, main_keywords, naver_store_url FROM clients WHERE status = 'active' AND COALESCE(auto_analysis, 1) = 1 AND COALESCE(role,'advertiser')='advertiser' AND COALESCE(vertical,'store')='store'"  # 관리 중단 업체 제외(호출 다이어트) · 플레이스 축 제외(스토어 크롤 대상 아님)
    ).fetchall()

    client_keyword_map = {}  # {client_id: [keywords]}
    all_client_keywords = set()

    for client in clients:
        cid = client['id']
        keywords_str = client['main_keywords'] or ''
        kw_set = set(k.strip() for k in keywords_str.split(',') if k.strip())

        past = conn.execute(
            "SELECT DISTINCT keyword FROM client_analyses WHERE client_id = ?", (cid,)
        ).fetchall()
        for row in past:
            kw = row['keyword'].strip()
            if kw:
                kw_set.add(kw)

        client_keyword_map[cid] = list(kw_set)
        all_client_keywords.update(kw_set)

    all_keywords = set(home_keyword_map.keys()) | all_client_keywords
    return home_keyword_map, clients, client_keyword_map, all_keywords


def _run_rank_tracking():
    """
    08:00 순위 추적 — 키워드당 최대 300위(3페이지)까지 조회.
    홈탭 순위 + 업체 순위를 동시에 처리.
    Rate Limit 방지를 위해 키워드당 약 18초 간격 → 약 50분 소요.
    """
    global _api_cache, _api_cache_date
    import sqlite3
    import os

    RANK_PAGES = 3          # 페이지 수 (100개 × 3 = 300위) — 호출 다이어트 D3(운영자 승인 2026-07-20): 400→300위, 배치 API 25% 절감
    DELAY_PER_KEYWORD = 18  # 키워드당 대기 시간 (초) — 네이버 실호출이 있는 키워드에만 적용
    DELAY_COLLECTED = 0.2   # 수집분 사용 키워드 간 양보 (초) — 네이버 미호출이라 간격 불필요
    DELAY_PER_PAGE = 1.5    # 같은 키워드 내 페이지 간 대기 (초)

    DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")
    today = date.today().isoformat()

    logger.info(f"🔍 순위 추적 시작 ({datetime.now().strftime('%H:%M')}) — 300위 범위, ~40분 소요 예상")

    try:
        from naver_crawler import (
            search_naver_shopping_api, _parse_api_item,
            find_product_rank_from_cache
        )
        from database import save_ranking, save_competitor_snapshot

        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row

        home_keyword_map, clients, client_keyword_map, all_keywords = _collect_all_keywords(conn)

        if not all_keywords:
            logger.info("  추적 키워드 없음. 순위 추적 건너뜀.")
            conn.close()
            return

        logger.info(f"  📋 키워드 {len(all_keywords)}개 × {RANK_PAGES}페이지 순위 추적 시작 (홈탭: {len(home_keyword_map)}, 업체: {len(set().union(*client_keyword_map.values()) if client_keyword_map else set())})")

        # 캐시 초기화
        _api_cache = {}
        _api_cache_date = today

        total_api_calls = 0
        total_rank_saved = 0
        total_errors = 0
        _review_cache = {}  # product_url -> review_count (상품당 1회, 리뷰 델타 추정용)

        for ki, keyword in enumerate(sorted(all_keywords)):
            try:
                # ── 1순위: 브라우저 수집분 (2026-08-03~) ──
                # 네이버 쇼핑 검색 API 종료(404 SE05)로 서버는 검색 결과를 못 받는다.
                # 사내 크롬 확장이 새벽에 올려둔 그날치 수집분이 있으면 그걸 그대로 쓴다.
                # 수집분이 없으면 아래 기존 API 경로를 그대로 타서, API가 되살아나거나
                # 다른 환경(로컬·테스트)에서는 종전과 똑같이 동작한다(무회귀).
                all_prods = []
                total_shop = 0
                _naver_called = False   # 이 키워드에서 네이버를 실제로 불렀는지(대기 판단용)
                _collected = None
                try:
                    from collector import load_collected
                    _collected = load_collected(keyword)
                except Exception as _ce:
                    logger.warning(f"  [{keyword}] 수집분 조회 실패(무시): {_ce}")
                if _collected:
                    all_prods = _collected["prods"]
                    total_shop = _collected["total"]
                    logger.info(f"  📥 [{keyword}] 브라우저 수집분 사용 — 상품 {len(all_prods)}개")

                # ── 2순위: 기존 검색 API (최대 300개 = 100개 × 3페이지) ──
                for page_idx in range(RANK_PAGES if not all_prods else 0):
                    start = page_idx * 100 + 1
                    shop_result = search_naver_shopping_api(keyword, display=100, start=start)
                    total_api_calls += 1
                    _naver_called = True
                    # ── 스테일 수집분 차단 ──
                    # 서빙 훅은 2일 창이라 '어제' 수집분도 돌려줄 수 있다(주간 분석용으론 유용).
                    # 그러나 순위 '기록'은 오늘 데이터여야 한다 — 어제 스냅샷을 오늘 순위로 저장하면
                    # 수집 실패 가드를 우회해 1,992건 오염 사고의 변종이 재발한다.
                    # 오늘분이 아니면 수집 실패로 취급해 저장을 건너뛴다(낮 만회 수집 후 정상화).
                    if shop_result.get("collectorServed") and shop_result.get("collectedDate") != today:
                        logger.warning(f"  ⏭️ [{keyword}] 수집분이 오늘자 아님({shop_result.get('collectedDate')}) — 순위 기록 건너뜀")
                        all_prods = []
                        break
                    items = shop_result.get("items", [])
                    if page_idx == 0:
                        total_shop = shop_result.get("total", 0)

                    for i, item in enumerate(items):
                        prod = _parse_api_item(item, start + i)
                        all_prods.append(prod)

                    # 결과가 100개 미만이면 더 이상 페이지 없음
                    if len(items) < 100:
                        break

                    # 같은 키워드 내 페이지 간 짧은 대기
                    if page_idx < RANK_PAGES - 1:
                        time.sleep(DELAY_PER_PAGE)

                # ── 수집 실패 판정 ──
                # 2026-08-01 네이버 쇼핑 검색 API 종료(404 SE05) 이후, 검색 결과가 0건이어도
                # 순위 None 을 그대로 저장해 '미노출'로 기록되던 문제(3일간 1,992건 오염).
                # 상품을 하나도 못 받았으면 '순위 없음'이 아니라 '수집 실패'이므로 저장하지 않는다.
                # (진짜 미노출은 all_prods 가 채워진 상태에서 내 상품이 안 잡히는 경우다.)
                if not all_prods:
                    total_errors += 1
                    logger.error(f"  ⚠️ [{keyword}] 검색 결과 0건 — 수집 실패로 보고 순위 저장 건너뜀"
                                 f" (미노출로 잘못 기록되는 것 방지)")
                    if ki < len(all_keywords) - 1:
                        time.sleep(DELAY_PER_KEYWORD)
                    continue

                # 09시 분석용 캐시 저장 (첫 100개만 — 기존 호환)
                _api_cache[keyword] = {"prods": all_prods[:100], "total": total_shop}

                # ── 홈탭 순위 저장 ──
                if keyword in home_keyword_map:
                    for product, kw_info in home_keyword_map[keyword]:
                        try:
                            rank, page, competitors = find_product_rank_from_cache(
                                keyword, product["product_url"], all_prods
                            )
                            # 슬러그로 저장된 스토어명 자가치유 (매칭 시 mallName 확보됨)
                            if rank is not None:
                                try:
                                    from database import heal_tracked_product_info
                                    heal_tracked_product_info(product["id"], product["product_url"], all_prods)
                                except Exception:
                                    pass
                            # 리뷰수 1회 조회 (상품당 캐시) — 실패해도 순위 저장엔 무영향
                            _purl = product.get("product_url")
                            if _purl not in _review_cache:
                                try:
                                    from naver_crawler import get_review_count
                                    _review_cache[_purl] = get_review_count(_purl)
                                    _naver_called = True   # 실제 네트워크 호출 → 종전 간격 유지
                                except Exception:
                                    _review_cache[_purl] = None
                            save_ranking(
                                product_id=product["id"],
                                keyword_id=kw_info["id"],
                                keyword=keyword,
                                rank_position=rank,
                                page_number=page,
                                check_type="scheduled",
                                review_count=_review_cache.get(_purl)
                            )
                            if competitors:
                                save_competitor_snapshot(kw_info["id"], competitors[:5])
                            total_rank_saved += 1
                        except Exception as e:
                            logger.error(f"  ❌ 홈탭 순위 저장 실패 [{product.get('product_name','')}:{keyword}]: {e}")

                # ── 업체 순위 저장 ──
                for client in clients:
                    cid = client['id']
                    product_url = client['naver_store_url'] or ''
                    if not product_url or keyword not in client_keyword_map.get(cid, []):
                        continue
                    try:
                        rank, page, _ = find_product_rank_from_cache(keyword, product_url, all_prods)
                        _save_client_rank(conn, cid, keyword, product_url, rank, page, "scheduled")
                        total_rank_saved += 1
                    except Exception as e:
                        logger.error(f"  ❌ 업체 순위 저장 실패 [{client['name']}:{keyword}]: {e}")

                # ── 키워드 간 대기 (Rate Limit 방지) ──
                # 2026-08-05 수정: 이 대기는 네이버 검색 API 호출 간격을 벌리려는 것이었다.
                # 쇼핑 검색 API 종료(7/31) 후 수집분을 쓰는 키워드는 네이버를 **한 번도 부르지 않으므로**
                # 대기할 이유가 없다. 그런데 조건 없이 18초를 쉬어 08:00~08:30 창에서
                # 약 100개 키워드만 처리되고(가나다순 고정) 나머지 800여 개는 매일 전일값으로 남았다.
                #   → 실제 네이버 호출이 있었던 키워드만 종전 간격을 유지한다(리뷰수 조회 포함).
                # 수집분 경로는 짧은 양보만 둬 DB·CPU 를 독점하지 않게 한다.
                if ki < len(all_keywords) - 1:
                    time.sleep(DELAY_PER_KEYWORD if _naver_called else DELAY_COLLECTED)

            except Exception as e:
                total_errors += 1
                logger.error(f"  ❌ [{keyword}] 순위 추적 실패: {e}")
                time.sleep(5)

        conn.close()

        # 호출 다이어트(2026-07): 08시 캐시를 디스크에도 저장 — 08~09시 사이 재배포/재시작으로
        # 메모리 캐시가 날아가도 09시 분석이 쇼핑 API를 다시 태우지 않게(키워드×1콜 낭비 방지).
        try:
            import json as _json
            _pf = os.path.join(os.path.dirname(DB_PATH), "rank_api_cache.json")
            with open(_pf, "w", encoding="utf-8") as _f:
                _json.dump({"date": today, "cache": _api_cache}, _f, ensure_ascii=False)
            logger.info(f"  💾 08시 캐시 디스크 저장: {len(_api_cache)}개 키워드")
        except Exception as _pe:
            logger.warning(f"  08시 캐시 디스크 저장 실패(무시): {_pe}")

        logger.info(
            f"✅ 순위 추적 완료: API {total_api_calls}회 (300위 범위), "
            f"순위 {total_rank_saved}건 저장, 실패 {total_errors}건 "
            f"(캐시 {len(_api_cache)}개 키워드 → 09시 분석 대기)"
        )

    except Exception as e:
        logger.error(f"❌ 순위 추적 전체 실패: {e}")


# ==================== 08:30 전체 분석 + 보고서 ====================

def _run_daily_analysis():
    """
    08:30 전체 분석 + HTML 보고서 — 08:00 캐시된 상품 데이터를 재사용.
    쇼핑 API 추가 호출 없음 (검색광고 API만 사용: 검색량 + 연관 키워드).
    캐시 미스 시에만 쇼핑 API 호출 (fallback).
    """
    global _api_cache, _api_cache_date
    import sqlite3
    import os

    DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")
    today = date.today().isoformat()

    # 만료 경쟁사 자동 삭제 (영업사원 등록·30일 경과) — 일일 1회
    try:
        from client_dashboard import cleanup_expired_competitors
        _n = cleanup_expired_competitors()
        if _n:
            logger.info(f"🗑️ 만료 경쟁사 {_n}건 자동 삭제 완료")
    except Exception as _e:
        logger.error(f"[cleanup] 만료 경쟁사 삭제 실패: {_e}")

    logger.info(f"📊 전체 분석 + 보고서 생성 시작 ({datetime.now().strftime('%H:%M')})")

    # 캐시 유효성 확인
    cache_valid = (_api_cache_date == today and len(_api_cache) > 0)
    if not cache_valid:
        # 호출 다이어트(2026-07): 메모리 캐시가 없으면(재배포·재시작) 디스크 복원 시도
        try:
            import json as _json
            _pf = os.path.join(os.path.dirname(DB_PATH), "rank_api_cache.json")
            with open(_pf, "r", encoding="utf-8") as _f:
                _saved = _json.load(_f)
            if isinstance(_saved, dict) and _saved.get("date") == today and _saved.get("cache"):
                _api_cache = _saved["cache"]
                _api_cache_date = today
                cache_valid = True
                logger.info(f"  💾 08시 캐시 디스크 복원: {len(_api_cache)}개 키워드")
        except Exception:
            pass
    if cache_valid:
        logger.info(f"  ✅ 08시 캐시 유효 — {len(_api_cache)}개 키워드 재사용 (쇼핑 API 호출 0회)")
    else:
        logger.warning(f"  ⚠️ 08시 캐시 없음 — 쇼핑 API 직접 호출로 fallback")

    try:
        from naver_crawler import (
            search_naver_shopping_api, _parse_api_item,
            get_keyword_volume
        )
        from auto_analysis import run_single_analysis, get_related_keywords

        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row

        # 활성 업체 + 키워드 수집
        clients = conn.execute(
            "SELECT id, name, main_keywords, naver_store_url FROM clients WHERE status = 'active' AND COALESCE(auto_analysis, 1) = 1 AND COALESCE(role,'advertiser')='advertiser' AND COALESCE(vertical,'store')='store'"  # 관리 중단 업체 제외(호출 다이어트) · 플레이스 축 제외(스토어 크롤 대상 아님)
        ).fetchall()

        client_keyword_map = {}
        for client in clients:
            cid = client['id']
            keywords_str = client['main_keywords'] or ''
            kw_set = set(k.strip() for k in keywords_str.split(',') if k.strip())

            past = conn.execute(
                "SELECT DISTINCT keyword FROM client_analyses WHERE client_id = ?", (cid,)
            ).fetchall()
            for row in past:
                kw = row['keyword'].strip()
                if kw:
                    kw_set.add(kw)

            client_keyword_map[cid] = list(kw_set)

        if not clients:
            logger.info("  등록된 활성 업체가 없습니다. 분석 건너뜀.")
            conn.close()
            return

        total_analyzed = 0
        total_errors = 0
        total_fallback_api = 0

        for client in clients:
            cid = client['id']
            client_name = client['name']
            product_url = client['naver_store_url'] or ''
            keywords = client_keyword_map.get(cid, [])

            if not keywords:
                continue

            logger.info(f"  📊 [{client_name}] 키워드 {len(keywords)}개 분석 시작")

            for keyword in keywords:
                try:
                    # 08시 캐시에서 상품 데이터 가져오기
                    cached = _api_cache.get(keyword) if cache_valid else None

                    if cached:
                        prods = cached["prods"]
                        total_shop = cached["total"]
                    else:
                        # 캐시 미스 — fallback API 호출
                        shop_result = search_naver_shopping_api(keyword, display=100)
                        items = shop_result.get("items", [])
                        total_shop = shop_result.get("total", 0)
                        prods = [_parse_api_item(item, i + 1) for i, item in enumerate(items)]
                        total_fallback_api += 1
                        time.sleep(2)

                    # 검색량 조회 (검색광고 API — 별도 할당량)
                    vol_data = {}
                    try:
                        vol_list = get_keyword_volume([keyword])
                        if vol_list and len(vol_list) > 0:
                            vol_data = vol_list[0]
                    except Exception:
                        pass

                    # 연관 키워드 조회 (검색광고 API)
                    related_data = {}
                    try:
                        related_data = get_related_keywords(keyword)
                    except Exception:
                        pass

                    # 캐시된 데이터로 분석 실행 (쇼핑 API 추가 호출 없음)
                    run_single_analysis(
                        client_id=cid,
                        client_name=client_name,
                        keyword=keyword,
                        product_url=product_url,
                        cached_prods=prods,
                        cached_total=total_shop,
                        cached_vol=vol_data,
                        cached_related=related_data,
                    )
                    total_analyzed += 1
                    logger.info(f"    ✅ [{keyword}] 분석 완료")

                    # 검색광고 API 간격 (1초)
                    time.sleep(1)

                except Exception as e:
                    total_errors += 1
                    logger.error(f"    ❌ [{client_name}:{keyword}] 분석 실패: {e}")
                    time.sleep(1)

        conn.close()

        # 캐시 정리 (메모리 해제)
        _api_cache.clear()

        logger.info(
            f"✅ 전체 분석 완료: 분석 {total_analyzed}건, 실패 {total_errors}건"
            f"{f', fallback API {total_fallback_api}회' if total_fallback_api > 0 else ''}"
        )

    except Exception as e:
        logger.error(f"❌ 전체 분석 실패: {e}")


def _run_daily_report():
    """일일 리포트 생성 및 발송"""
    try:
        from database import get_notification_settings, save_notification_log
        from kakao_notify import (
            is_configured, collect_daily_rank_changes,
            generate_daily_report_text, send_report_notification
        )

        settings = get_notification_settings()

        if not settings.get("notify_enabled"):
            logger.info("알림이 비활성화되어 있습니다. 리포트 발송 건너뜀.")
            return

        if not is_configured():
            logger.warning("Solapi API가 설정되지 않아 리포트 발송 불가.")
            return

        # 리포트 데이터 수집
        rank_data = collect_daily_rank_changes()
        if not rank_data:
            logger.info("리포트할 데이터가 없습니다.")
            return

        # 리포트 텍스트 생성
        report_text = generate_daily_report_text(rank_data)

        # 발송
        receiver = settings.get("receiver_phone", "")
        if receiver:
            result = send_report_notification(report_text, receiver)
            status = "success" if result.get("success") else "failed"
            save_notification_log(
                log_type="daily_report",
                status=status,
                message=report_text[:500],
                receiver_phone=receiver
            )
            logger.info(f"📊 일일 리포트 발송 {'성공' if status == 'success' else '실패'}")
        else:
            logger.warning("수신자 전화번호가 설정되지 않았습니다.")

    except Exception as e:
        logger.error(f"일일 리포트 발송 실패: {e}")
        try:
            from database import save_notification_log
            save_notification_log(
                log_type="daily_report",
                status="error",
                message=str(e)[:500]
            )
        except Exception:
            pass


def _save_client_rank(conn, client_id, keyword, product_url, rank, page, check_type="scheduled"):
    """업체 순위를 client_rank_history에 저장 (당일 중복 시 UPDATE)"""
    today = date.today().isoformat()
    existing = conn.execute(
        """SELECT id FROM client_rank_history
           WHERE client_id=? AND keyword=? AND DATE(checked_at)=? AND check_type=?""",
        (client_id, keyword, today, check_type)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE client_rank_history
            SET rank_position=?, page_number=?, checked_at=datetime('now','localtime')
            WHERE id=?
        """, (rank, page, existing['id']))
    else:
        conn.execute("""
            INSERT INTO client_rank_history
            (client_id, keyword, product_url, rank_position, page_number, check_type)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (client_id, keyword, product_url or '', rank, page, check_type))
    conn.commit()


# ==================== 00:30 DB 자동 백업 ====================

BACKUP_KEEP = 2  # 보관 개수 — DB가 ~3.5GB로 성장해 gzip 개당 ~3GB. 5개(15GB)가 35GB 디스크를
#   채워 쓰기 실패(업체 등록 500, 2026-07-20 실사고)를 유발 → 최신 2개(~6GB)로 축소.


def _prune_old_backups(backup_dir, keep=BACKUP_KEEP):
    """오래된 백업 정리 — 압축(.db.gz)·비압축(.db) 모두 대상, 최신 keep개만 보관.
    파일명이 logic_analysis_backup_YYYYMMDD_HHMMSS 라 이름 정렬 = 시간 정렬."""
    import os
    try:
        backups = sorted([
            f for f in os.listdir(backup_dir)
            if f.startswith("logic_analysis_backup_") and (f.endswith(".db") or f.endswith(".db.gz"))
        ])
        while len(backups) > keep:
            old = backups.pop(0)
            try:
                os.remove(os.path.join(backup_dir, old))
                logger.info(f"  🗑️ [DB백업] 오래된 백업 삭제: {old}")
            except Exception as e:
                logger.warning(f"[DB백업] 삭제 실패({old}): {e}")
    except Exception as e:
        logger.warning(f"[DB백업] 정리 실패: {e}")


def _run_daily_db_backup():
    """매일 자정 30분에 DB 백업 수행 (gzip 압축 · 최신 5개 보관 · 디스크 가드).
    업체(광고주) 데이터 보호를 위해 SQLite online backup API 사용.
    ⚠️ 복원 시: gunzip logic_analysis_backup_YYYYMMDD_HHMMSS.db.gz 로 풀어서 사용.
    (2026-07-10 개정) DB가 수 GB로 성장하며 비압축 14개 보관이 공유서버 디스크를
    가득 채워 타 배치(순위추적)의 DB 쓰기까지 막는 사고가 있어, 압축+개수축소+가드 적용."""
    import sqlite3
    import shutil
    import os
    import gzip

    DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")

    if not os.path.exists(DB_PATH):
        logger.warning("[DB백업] DB 파일 없음, 백업 건너뜀")
        return

    db_size = os.path.getsize(DB_PATH)
    if db_size < 4096:
        logger.warning(f"[DB백업] DB 파일 비정상 크기 ({db_size} bytes), 백업 건너뜀")
        return

    backup_dir = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")
    os.makedirs(backup_dir, exist_ok=True)

    # ── 디스크 가드 ── 백업이 디스크를 꽉 채워 앱(순위추적 등)의 DB 쓰기를 막는 사고 방지.
    #   압축 전 임시 .db(≈DB 크기) 저장 + 여유 2GB 가 확보 안 되면 이번 백업은 건너뛴다.
    try:
        free = shutil.disk_usage(backup_dir).free
        if free < db_size + 2 * 1024 ** 3:
            logger.warning(
                f"[DB백업] 디스크 여유 부족(free={free:,} < db={db_size:,}+2GB) — "
                f"이번 백업 건너뜀(앱 쓰기 보호). 오래된 백업만 정리."
            )
            _prune_old_backups(backup_dir)
            return
    except Exception:
        pass

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = os.path.join(backup_dir, f"logic_analysis_backup_{ts}.db")
    gz_path = raw_path + ".gz"

    try:
        # 업체 수 확인 (빈 DB 백업 방지)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        row = conn.execute("SELECT COUNT(*) FROM clients").fetchone()
        client_count = row[0] if row else 0
        conn.close()

        if client_count == 0:
            logger.info("[DB백업] 업체 데이터 없음, 백업 건너뜀")
            return

        # SQLite online backup (WAL 안전) → 임시 .db
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(raw_path)
        src.backup(dst)
        dst.close()
        src.close()

    except Exception as e:
        logger.error(f"❌ [DB백업] online backup 실패, 파일 복사로 대체: {e}")
        try:
            shutil.copy2(DB_PATH, raw_path)
        except Exception as e2:
            logger.error(f"❌ [DB백업] 파일 복사도 실패: {e2}")
            if os.path.exists(raw_path):
                try:
                    os.remove(raw_path)
                except Exception:
                    pass
            return

    # gzip 압축 → 원본 .db 제거 (수 GB → ~1GB, 디스크 절약)
    final_path = raw_path
    try:
        with open(raw_path, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out, length=4 * 1024 * 1024)
        os.remove(raw_path)
        final_path = gz_path
    except Exception as e:
        logger.error(f"[DB백업] 압축 실패 — 비압축본 유지: {e}")
        if os.path.exists(gz_path):
            try:
                os.remove(gz_path)
            except Exception:
                pass

    try:
        logger.info(f"✅ [DB백업] 완료: {final_path} ({os.path.getsize(final_path):,} bytes, 업체 {client_count}건)")
    except Exception:
        pass

    # 오래된 백업 정리 (최신 BACKUP_KEEP개 보관; 압축·비압축 모두 대상)
    _prune_old_backups(backup_dir)


# ==================== 01:20 순위 두 축 브리지 갱신 ====================
# 순위가 tracked_products 축과 clients 축으로 갈려 있어 같은 상품이 두 번 관리된다.
# rank_link 가 둘을 이어 두면 다음 단계(조회 통합)에서 한쪽만 읽는 화면을 고칠 수 있다.
# 이 잡은 링크 행만 만들고 지운다 — 순위 데이터·조회 경로는 건드리지 않는다.
def _run_rank_link_maintenance():
    try:
        from rank_link import run_maintenance
        res = run_maintenance()
        if res.get("success"):
            logger.info(f"🔗 순위 축 브리지 — 신규 {res.get('inserted', 0)}건 · "
                        f"고아 정리 {res.get('pruned', 0)}건 · 총 {res.get('linked_total', 0)}건")
        else:
            logger.warning(f"순위 축 브리지 갱신 실패: {res.get('detail')}")
    except Exception as e:
        # 부가 기능이라 실패해도 다른 배치에 영향을 주지 않는다.
        logger.warning(f"순위 축 브리지 갱신 예외: {e}")


def _run_place_auto_track_cleanup():
    """(레거시 정리) 자동 등록으로 생긴 추적 대상 중 30일 넘게 안 쓰인 것을 비활성으로 내린다.

    ⚠️ 자동 등록 기능은 폐지됐다(2026-08-12 — 분석·제안서는 추적에 등록하지 않는다. 스토어와
       같은 규칙). 신규 auto_added=1 행은 더는 생기지 않으므로, 이 잡은 폐지 전에 생긴 행만
       정리한다. 사람이 등록한 행(auto_added=0)은 영향 없음.
    """
    try:
        from database import deactivate_stale_auto_place_targets
        n = deactivate_stale_auto_place_targets()
        if n:
            logger.info(f"📍 플레이스 자동 추적 정리 — {n}건 비활성")
    except Exception as e:
        # 부가 기능이라 실패해도 다른 배치에 영향을 주지 않는다.
        logger.warning(f"플레이스 자동 추적 정리 예외: {e}")


# ==================== 01:00 분석 보관정책 (client_analyses 정리) ====================
# 배경: client_analyses 는 스케줄러가 (업체×키워드×일)로 매일 append 하여 4월부터 수 GB로
#   성장(2026-08 실측 4.7GB = DB 전체) → 공유서버 디스크 압박. 오래된 일별 분석 스냅샷은
#   실사용에 불필요(화면·전산 연동은 '키워드별 최신'만 소비).
# 정책 B(대표 확정 2026-08-04): 최근 30일치 + (업체·키워드별 최신 1건)은 보존, 그 외 삭제.
# ⚠️ 전산① portal-summary 계약 무영향: 그 API 는 client_id 별 `GROUP BY keyword ORDER BY
#   analyzed_date DESC LIMIT 8` 로 '키워드별 최신'만 읽으므로, 최신 1건을 항상 보존하는 이
#   정책과 충돌하지 않는다(옛 중복 스냅샷만 제거).
# 파일 크기: DELETE 는 페이지를 freelist 로 돌려 재사용케 해 '파일 무한 성장'을 멈춘다.
#   (기존 파일 크기의 즉시 축소는 VACUUM 필요 — 운영 중 락 위험이 있어 별도 통제된 시점에 수행.)
def _run_client_analyses_retention():
    import sqlite3
    import os
    DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")
    if not os.path.exists(DB_PATH):
        return
    where = ("analyzed_date < date('now','localtime','-30 days') "
             "AND id NOT IN (SELECT MAX(id) FROM client_analyses GROUP BY client_id, keyword)")
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        cur = conn.cursor()
        n = cur.execute(f"SELECT COUNT(*) FROM client_analyses WHERE {where}").fetchone()[0]
        if not n:
            logger.info("[보관정책] client_analyses 삭제 대상 없음")
            return
        cur.execute(f"DELETE FROM client_analyses WHERE {where}")
        conn.commit()
        logger.info(f"✅ [보관정책] client_analyses {n:,}행 정리 (최근 30일+키워드별 최신 보존)")
    except Exception as e:
        logger.error(f"[보관정책] 실패(무시): {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ==================== 1회성 VACUUM (freelist → 디스크 반환) ====================
# 배경: 2026-08-04 보관정책 B 1회 삭제로 client_analyses 17,283행 제거 → DB 파일 안에
#   ~2.2GB freelist(빈 페이지)만 남음. VACUUM 이 파일을 재구성해 그 공간을 실제 디스크로
#   반환한다(4.7GB → ~2.5GB 예상). VACUUM 은 DB 를 잠그므로(수십 초~수 분) 아무 때나 하면
#   그 사이 요청이 막힌다 → ① 기동 직후 저트래픽 시점까지 지연 ② 백그라운드 스레드(헬스체크
#   비차단) ③ 1회성 마커로 배포마다 재실행 방지. 실패해도 마커 미생성 → 다음 배포에서 재시도.
_VACUUM_MARKER_NAME = ".vacuum_done_2026_08_04"


def _run_one_time_vacuum():
    import os
    import threading
    DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")
    marker = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), _VACUUM_MARKER_NAME)
    if not os.path.exists(DB_PATH) or os.path.exists(marker):
        return

    def _do():
        import sqlite3
        import shutil
        conn = None
        try:
            time.sleep(120)  # 기동 직후 부하·헬스체크 창을 피해 저트래픽까지 대기
            if os.path.exists(marker):
                return
            # 안전 가드: VACUUM 은 원본 크기만큼 임시 공간이 필요 → 여유 부족 시 이번엔 생략
            size = os.path.getsize(DB_PATH)
            free = shutil.disk_usage(os.path.dirname(DB_PATH)).free
            if free < size + 1 * 1024 ** 3:
                logger.warning(f"[VACUUM] 디스크 여유 부족(free={free}, db={size}) — 이번 배포 생략, 다음 재시도")
                return
            before = size
            conn = sqlite3.connect(DB_PATH, timeout=600)
            conn.execute("VACUUM")
            conn.close()
            conn = None
            after = os.path.getsize(DB_PATH)
            with open(marker, "w") as f:
                f.write("done")
            logger.info(f"✅ [VACUUM] 1회 파일 축소 완료: {before/1073741824:.2f}GB → {after/1073741824:.2f}GB")
        except Exception as e:
            logger.error(f"[VACUUM] 실패(무시·다음 배포 재시도): {e}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    threading.Thread(target=_do, daemon=True, name="one-time-vacuum").start()
    logger.info("🧹 [VACUUM] 1회 축소 예약 — 기동 120초 후 백그라운드 실행(마커 없을 때만)")
