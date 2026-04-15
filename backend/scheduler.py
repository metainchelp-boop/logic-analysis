"""
로직 분석 프로그램 v2 - 스케줄러 모듈
APScheduler 기반 자동 순위 체크, 일일 리포트, 업체 자동 분석
"""
import logging
import time
import json
from datetime import datetime, date
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# 글로벌 스케줄러 인스턴스
_scheduler: BackgroundScheduler = None


def start_scheduler():
    """스케줄러 시작 — 앱 시작 시 호출"""
    global _scheduler
    if _scheduler and _scheduler.running:
        logger.warning("스케줄러가 이미 실행 중입니다.")
        return

    _scheduler = BackgroundScheduler(timezone="Asia/Seoul")

    # 1) 자동 순위 체크 — 매 6시간
    _scheduler.add_job(
        _run_scheduled_rank_check,
        trigger=IntervalTrigger(hours=6),
        id="rank_check",
        name="자동 순위 체크",
        replace_existing=True,
        max_instances=1,
    )

    # 2) 일일 리포트 발송 — 기본 09:00 (알림 설정에서 변경 가능)
    _scheduler.add_job(
        _run_daily_report,
        trigger=CronTrigger(hour=9, minute=0),
        id="daily_report",
        name="일일 리포트 발송",
        replace_existing=True,
        max_instances=1,
    )

    # 3) 업체 자동 분석 — 매일 09:00 (모든 업체의 키워드 자동 분석)
    _scheduler.add_job(
        _run_daily_client_analysis,
        trigger=CronTrigger(hour=9, minute=0),
        id="daily_client_analysis",
        name="업체 자동 분석",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.start()
    logger.info("✅ 스케줄러 시작 (순위체크: 6시간, 리포트: 09:00, 업체분석: 09:00)")


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


# ==================== 스케줄 작업 함수 ====================

def _run_scheduled_rank_check():
    """스케줄된 전체 상품 순위 체크"""
    try:
        from database import (
            get_all_tracked_products, get_keywords_for_product,
            save_ranking, save_competitor_snapshot,
            get_latest_ranking_for_keyword
        )
        from naver_crawler import find_product_rank

        products = get_all_tracked_products()
        if not products:
            logger.info("추적 중인 상품이 없습니다. 스케줄 순위 체크 건너뜀.")
            return

        total_checked = 0
        for product in products:
            keywords = get_keywords_for_product(product["id"])
            for kw_info in keywords:
                try:
                    rank, page, competitors = find_product_rank(
                        keyword=kw_info["keyword"],
                        product_url=product["product_url"],
                        max_pages=2
                    )
                    save_ranking(
                        product_id=product["id"],
                        keyword_id=kw_info["id"],
                        keyword=kw_info["keyword"],
                        rank_position=rank,
                        page_number=page,
                        check_type="scheduled"
                    )
                    if competitors:
                        save_competitor_snapshot(kw_info["id"], competitors[:5])
                    total_checked += 1
                except Exception as e:
                    logger.error(f"순위 체크 실패 [{product['product_name']}:{kw_info['keyword']}]: {e}")

                # API 호출 간격 조절
                import time
                time.sleep(1)

        logger.info(f"✅ 스케줄 순위 체크 완료: {total_checked}건")

    except Exception as e:
        logger.error(f"스케줄 순위 체크 전체 실패: {e}")


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
        except:
            pass


def _run_daily_client_analysis():
    """
    업체 자동 분석 — 모든 활성 업체의 등록된 키워드를 순차 분석하여 일자별 누적 저장
    매일 09:00 KST 실행
    """
    import sqlite3
    import os

    DB_PATH = os.getenv("DB_PATH", "logic_data.db")
    today = date.today().isoformat()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    logger.info(f"🔄 업체 자동 분석 시작 ({today})")

    try:
        from naver_crawler import get_keyword_volume, search_products, find_product_rank

        # 1) 모든 활성 업체 + 키워드 조회
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        clients = conn.execute(
            "SELECT id, name, main_keywords, naver_store_url FROM clients WHERE status = 'active'"
        ).fetchall()
        conn.close()

        if not clients:
            logger.info("등록된 활성 업체가 없습니다. 자동 분석 건너뜀.")
            return

        total_analyzed = 0
        total_errors = 0
        total_skipped = 0

        for client in clients:
            client_id = client['id']
            client_name = client['name']
            keywords_str = client['main_keywords'] or ''
            product_url = client['naver_store_url'] or ''

            keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
            if not keywords:
                continue

            logger.info(f"📊 [{client_name}] 키워드 {len(keywords)}개 분석 시작")

            for keyword in keywords:
                try:
                    # 검색량 조회
                    vol_data = {}
                    total_vol = 0
                    try:
                        vol_list = get_keyword_volume([keyword])
                        if vol_list and len(vol_list) > 0:
                            vol_data = vol_list[0]
                            pc = vol_data.get('monthlyPcQcCnt', 0)
                            mobile = vol_data.get('monthlyMobileQcCnt', 0)
                            if isinstance(pc, str) and pc == '< 10':
                                pc = 5
                            if isinstance(mobile, str) and mobile == '< 10':
                                mobile = 5
                            total_vol = int(pc or 0) + int(mobile or 0)
                    except Exception as e:
                        logger.warning(f"  [{keyword}] 검색량 조회 실패: {e}")

                    time.sleep(1)

                    # 상품 검색
                    prods = []
                    product_count = 0
                    try:
                        prods = search_products(keyword, max_results=40)
                        product_count = len(prods)
                    except Exception as e:
                        logger.warning(f"  [{keyword}] 상품 검색 실패: {e}")

                    time.sleep(1)

                    # 분석 데이터 구성 (ClientDashboard.jsx의 runAnalysis와 동일 구조)
                    analysis = {}

                    if product_count > 0 and total_vol > 0:
                        import math
                        comp_idx = round(product_count / total_vol, 2)
                        comp_pct = min(98, max(2, round(math.log10(comp_idx * 10 + 1) / math.log10(101) * 100)))
                        if comp_pct <= 30:
                            comp_label = '블루오션'
                            comp_color = '#059669'
                        elif comp_pct <= 70:
                            comp_label = '보통'
                            comp_color = '#d97706'
                        else:
                            comp_label = '레드오션'
                            comp_color = '#dc2626'
                        analysis['competitionIndex'] = {
                            'compIndex': comp_idx,
                            'compPercent': comp_pct,
                            'compLabel': comp_label,
                            'compColor': comp_color,
                            'productCount': product_count,
                            'searchVolume': total_vol
                        }

                    if prods:
                        prices = [p.get('price', 0) for p in prods if p.get('price', 0) > 0]
                        avg_price = round(sum(prices) / len(prices)) if prices else 0

                        # CTR × 전환율 기반 추정 (프론트엔드와 동일 공식)
                        def _get_ctr(rank):
                            if rank == 1: return 0.08
                            if rank == 2: return 0.06
                            if rank == 3: return 0.05
                            if rank == 4: return 0.04
                            if rank == 5: return 0.03
                            if rank <= 10: return 0.015
                            if rank <= 20: return 0.008
                            if rank <= 40: return 0.003
                            return 0.001

                        conv_rate = 0.035
                        top20_revenue = 0
                        for p in prods[:20]:
                            ctr = _get_ctr(p.get('rank', 40))
                            est_sales = max(1, round(total_vol * ctr * conv_rate))
                            top20_revenue += p.get('price', 0) * est_sales

                        analysis['marketRevenue'] = {
                            'avgPrice': avg_price,
                            'estimatedMonthly': top20_revenue,
                            'conversionRate': '3.5%',
                            'calculationMethod': 'CTR × 전환율'
                        }

                    if total_vol > 0:
                        analysis['summaryCards'] = {
                            'totalVolume': total_vol,
                            'productCount': product_count,
                            'compLevel': analysis.get('competitionIndex', {}).get('compLabel', '-')
                        }

                    if vol_data:
                        analysis['advertiserInfo'] = {
                            'adDepth': vol_data.get('plAvgDepth', 0),
                            'pcClicks': str(round(float(vol_data.get('monthlyAvePcClkCnt', 0) or 0), 1)),
                            'mobileClicks': str(round(float(vol_data.get('monthlyAveMobileClkCnt', 0) or 0), 1)),
                            'compIdx': vol_data.get('compIdx', '-')
                        }

                    # DB 저장 (일자별 UPSERT)
                    conn2 = sqlite3.connect(DB_PATH, timeout=10)
                    conn2.row_factory = sqlite3.Row
                    conn2.execute("PRAGMA journal_mode=WAL")

                    existing = conn2.execute(
                        "SELECT id FROM client_analyses WHERE client_id=? AND keyword=? AND analyzed_date=?",
                        (client_id, keyword, today)
                    ).fetchone()

                    params = (
                        product_url,
                        json.dumps(analysis, ensure_ascii=False),
                        json.dumps(vol_data, ensure_ascii=False),
                        json.dumps({}, ensure_ascii=False),
                        json.dumps(prods[:20] if prods else [], ensure_ascii=False),
                        json.dumps(vol_data, ensure_ascii=False),
                        '',  # report_html (서버에서는 DOM 캡처 불가)
                        now,
                    )

                    if existing:
                        conn2.execute("""
                            UPDATE client_analyses
                            SET product_url=?, analysis_json=?, volume_json=?,
                                related_json=?, shop_products_json=?, advertiser_json=?,
                                report_html=?, updated_at=?
                            WHERE client_id=? AND keyword=? AND analyzed_date=?
                        """, params + (client_id, keyword, today))
                    else:
                        conn2.execute("""
                            INSERT INTO client_analyses
                            (client_id, keyword, product_url, analysis_json, volume_json,
                             related_json, shop_products_json, advertiser_json, report_html,
                             analyzed_date, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (client_id, keyword) + params[:7] + (today, now, now))

                    # 순위 추적 (상품 URL이 있는 경우)
                    if product_url and prods:
                        try:
                            rank, page, _ = find_product_rank(keyword, product_url, max_pages=2)
                            if rank:
                                conn2.execute("""
                                    INSERT INTO client_rank_history
                                    (client_id, keyword, product_url, rank_position, page_number, check_type, checked_at)
                                    VALUES (?, ?, ?, ?, ?, 'scheduled', ?)
                                """, (client_id, keyword, product_url, rank, page, now))
                        except Exception as e:
                            logger.warning(f"  [{keyword}] 순위 추적 실패: {e}")
                        time.sleep(1)

                    conn2.commit()
                    conn2.close()

                    total_analyzed += 1
                    logger.info(f"  ✅ [{client_name}:{keyword}] 분석 완료 (검색량:{total_vol}, 상품:{product_count})")

                    # API 호출 간격 조절 (3초)
                    time.sleep(3)

                except Exception as e:
                    total_errors += 1
                    logger.error(f"  ❌ [{client_name}:{keyword}] 분석 실패: {e}")
                    time.sleep(2)

        logger.info(f"✅ 업체 자동 분석 완료: 성공 {total_analyzed}건, 실패 {total_errors}건")

    except Exception as e:
        logger.error(f"❌ 업체 자동 분석 전체 실패: {e}")
