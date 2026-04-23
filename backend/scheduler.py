"""
로직 분석 프로그램 v3 - 스케줄러 모듈
APScheduler 기반 통합 스케줄러
- 08:00 순위 추적 (홈탭 + 업체, 키워드당 1회 API, 결과 캐시)
- 09:00 전체 분석 + HTML 보고서 (08시 캐시 재사용, API 추가 호출 없음)
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

# 08시 순위 추적에서 캐시한 API 결과 → 09시 분석에서 재사용
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

    _scheduler = BackgroundScheduler(timezone="Asia/Seoul")

    # 1) 순위 추적 — 매일 08:00 (홈탭 + 업체, 키워드당 1회 API, 결과 캐시)
    _scheduler.add_job(
        _run_rank_tracking,
        trigger=CronTrigger(hour=8, minute=0),
        id="rank_tracking",
        name="순위 추적 (08:00)",
        replace_existing=True,
        max_instances=1,
    )

    # 2) 전체 분석 + 보고서 — 매일 09:00 (08시 캐시 재사용)
    _scheduler.add_job(
        _run_daily_analysis,
        trigger=CronTrigger(hour=9, minute=0),
        id="daily_analysis",
        name="전체 분석 + 보고서 (09:00)",
        replace_existing=True,
        max_instances=1,
    )

    # 3) 일일 리포트 발송 — 10:00 (분석 완료 후 발송)
    _scheduler.add_job(
        _run_daily_report,
        trigger=CronTrigger(hour=10, minute=0),
        id="daily_report",
        name="일일 리포트 발송 (10:00)",
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

    _scheduler.start()
    logger.info("✅ 스케줄러 시작 (순위: 08:00, 분석: 09:00, 리포트: 10:00, DB백업: 00:30)")


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
        "SELECT id, name, main_keywords, naver_store_url FROM clients WHERE status = 'active'"
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
    08:00 순위 추적 — 키워드당 최대 400위(4페이지)까지 조회.
    홈탭 순위 + 업체 순위를 동시에 처리.
    Rate Limit 방지를 위해 키워드당 약 18초 간격 → 약 50분 소요.
    """
    global _api_cache, _api_cache_date
    import sqlite3
    import os

    RANK_PAGES = 4          # 페이지 수 (100개 × 4 = 400위)
    DELAY_PER_KEYWORD = 18  # 키워드당 대기 시간 (초) — 50분 분산
    DELAY_PER_PAGE = 1.5    # 같은 키워드 내 페이지 간 대기 (초)

    DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")
    today = date.today().isoformat()

    logger.info(f"🔍 순위 추적 시작 ({datetime.now().strftime('%H:%M')}) — 400위 범위, ~50분 소요 예상")

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

        for ki, keyword in enumerate(sorted(all_keywords)):
            try:
                # ── API 호출: 최대 400개 (100개 × 4페이지) ──
                all_prods = []
                total_shop = 0
                for page_idx in range(RANK_PAGES):
                    start = page_idx * 100 + 1
                    shop_result = search_naver_shopping_api(keyword, display=100, start=start)
                    total_api_calls += 1
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

                # 09시 분석용 캐시 저장 (첫 100개만 — 기존 호환)
                _api_cache[keyword] = {"prods": all_prods[:100], "total": total_shop}

                # ── 홈탭 순위 저장 ──
                if keyword in home_keyword_map:
                    for product, kw_info in home_keyword_map[keyword]:
                        try:
                            rank, page, competitors = find_product_rank_from_cache(
                                keyword, product["product_url"], all_prods
                            )
                            save_ranking(
                                product_id=product["id"],
                                keyword_id=kw_info["id"],
                                keyword=keyword,
                                rank_position=rank,
                                page_number=page,
                                check_type="scheduled"
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

                # 키워드 간 대기 (Rate Limit 방지 — 50분 분산)
                if ki < len(all_keywords) - 1:
                    time.sleep(DELAY_PER_KEYWORD)

            except Exception as e:
                total_errors += 1
                logger.error(f"  ❌ [{keyword}] 순위 추적 실패: {e}")
                time.sleep(5)

        conn.close()
        logger.info(
            f"✅ 순위 추적 완료: API {total_api_calls}회 (400위 범위), "
            f"순위 {total_rank_saved}건 저장, 실패 {total_errors}건 "
            f"(캐시 {len(_api_cache)}개 키워드 → 09시 분석 대기)"
        )

    except Exception as e:
        logger.error(f"❌ 순위 추적 전체 실패: {e}")


# ==================== 09:00 전체 분석 + 보고서 ====================

def _run_daily_analysis():
    """
    09:00 전체 분석 + HTML 보고서 — 08시 캐시된 상품 데이터를 재사용.
    쇼핑 API 추가 호출 없음 (검색광고 API만 사용: 검색량 + 연관 키워드).
    캐시 미스 시에만 쇼핑 API 호출 (fallback).
    """
    global _api_cache, _api_cache_date
    import sqlite3
    import os

    DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")
    today = date.today().isoformat()

    logger.info(f"📊 전체 분석 + 보고서 생성 시작 ({datetime.now().strftime('%H:%M')})")

    # 캐시 유효성 확인
    cache_valid = (_api_cache_date == today and len(_api_cache) > 0)
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
            "SELECT id, name, main_keywords, naver_store_url FROM clients WHERE status = 'active'"
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

def _run_daily_db_backup():
    """매일 자정 30분에 DB 백업 수행.
    업체(광고주) 데이터 보호를 위해 SQLite online backup API 사용."""
    import sqlite3
    import shutil
    import os

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

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"logic_analysis_backup_{ts}.db")

    try:
        # 업체 수 확인 (빈 DB 백업 방지)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        row = conn.execute("SELECT COUNT(*) FROM clients").fetchone()
        client_count = row[0] if row else 0
        conn.close()

        if client_count == 0:
            logger.info("[DB백업] 업체 데이터 없음, 백업 건너뜀")
            return

        # SQLite online backup (WAL 안전)
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(backup_path)
        src.backup(dst)
        dst.close()
        src.close()

        backup_size = os.path.getsize(backup_path)
        logger.info(f"✅ [DB백업] 완료: {backup_path} ({backup_size:,} bytes, 업체 {client_count}건)")

    except Exception as e:
        logger.error(f"❌ [DB백업] 실패: {e}")
        # fallback: 파일 복사
        try:
            shutil.copy2(DB_PATH, backup_path)
            logger.info(f"✅ [DB백업] 파일 복사로 완료: {backup_path}")
        except Exception as e2:
            logger.error(f"❌ [DB백업] 파일 복사도 실패: {e2}")
            return

    # 오래된 백업 정리 (최대 14개 보관 = 약 2주)
    try:
        backups = sorted([
            f for f in os.listdir(backup_dir)
            if f.startswith("logic_analysis_backup_") and f.endswith(".db")
        ])
        while len(backups) > 14:
            old = backups.pop(0)
            old_path = os.path.join(backup_dir, old)
            os.remove(old_path)
            logger.info(f"  🗑️ [DB백업] 오래된 백업 삭제: {old}")
    except Exception as e:
        logger.warning(f"[DB백업] 정리 실패: {e}")
