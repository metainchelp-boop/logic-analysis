"""
로직 분석 프로그램 v2 - 스케줄러 모듈
APScheduler 기반 자동 순위 체크 및 일일 리포트
"""
import logging
from datetime import datetime
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

    _scheduler.start()
    logger.info("✅ 스케줄러 시작 (순위체크: 6시간, 리포트: 09:00)")


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
