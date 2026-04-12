"""
로직 분석 프로그램 v2 - 카카오 알림톡 모듈
Solapi API를 통한 알림톡/SMS 발송
"""
import requests
import hashlib
import hmac
import time
import uuid
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Solapi 환경변수
SOLAPI_API_KEY = os.getenv("SOLAPI_API_KEY", "")
SOLAPI_API_SECRET = os.getenv("SOLAPI_API_SECRET", "")
SOLAPI_SENDER_PHONE = os.getenv("SOLAPI_SENDER_PHONE", "")  # 발신번호
SOLAPI_PFID = os.getenv("SOLAPI_PFID", "")  # 카카오 채널 ID (알림톡용)

SOLAPI_API_URL = "https://api.solapi.com"


def is_configured() -> bool:
    """Solapi API가 설정되어 있는지 확인"""
    return bool(SOLAPI_API_KEY and SOLAPI_API_SECRET and SOLAPI_SENDER_PHONE)


def _generate_auth_header() -> Dict[str, str]:
    """Solapi HMAC-SHA256 인증 헤더 생성"""
    date = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    salt = str(uuid.uuid4())
    signature = hmac.new(
        SOLAPI_API_SECRET.encode("utf-8"),
        (date + salt).encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return {
        "Authorization": f"HMAC-SHA256 apiKey={SOLAPI_API_KEY}, date={date}, salt={salt}, signature={signature}",
        "Content-Type": "application/json",
    }


def _send_sms(to: str, text: str) -> Dict:
    """SMS 발송 (알림톡 불가 시 fallback)"""
    try:
        headers = _generate_auth_header()
        payload = {
            "message": {
                "to": to,
                "from": SOLAPI_SENDER_PHONE,
                "text": text[:90],  # SMS 90바이트 제한 → 한글 기준 ~45자
                "type": "SMS",
            }
        }

        resp = requests.post(
            f"{SOLAPI_API_URL}/messages/v4/send",
            json=payload,
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info(f"SMS 발송 성공: {to}")
        return {"success": True, "type": "SMS", "result": result}
    except Exception as e:
        logger.error(f"SMS 발송 실패: {e}")
        return {"success": False, "type": "SMS", "error": str(e)}


def _send_lms(to: str, text: str, subject: str = "") -> Dict:
    """LMS 발송 (긴 문자)"""
    try:
        headers = _generate_auth_header()
        payload = {
            "message": {
                "to": to,
                "from": SOLAPI_SENDER_PHONE,
                "text": text[:2000],
                "type": "LMS",
                "subject": subject or "로직분석 리포트",
            }
        }

        resp = requests.post(
            f"{SOLAPI_API_URL}/messages/v4/send",
            json=payload,
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info(f"LMS 발송 성공: {to}")
        return {"success": True, "type": "LMS", "result": result}
    except Exception as e:
        logger.error(f"LMS 발송 실패: {e}")
        return {"success": False, "type": "LMS", "error": str(e)}


def _send_alimtalk(to: str, text: str, template_id: str = None) -> Dict:
    """카카오 알림톡 발송"""
    if not SOLAPI_PFID:
        logger.warning("카카오 채널 ID 미설정, LMS로 대체 발송")
        return _send_lms(to, text)

    try:
        headers = _generate_auth_header()
        payload = {
            "message": {
                "to": to,
                "from": SOLAPI_SENDER_PHONE,
                "text": text,
                "type": "ATA",  # 알림톡
                "kakaoOptions": {
                    "pfId": SOLAPI_PFID,
                }
            }
        }
        if template_id:
            payload["message"]["kakaoOptions"]["templateId"] = template_id

        resp = requests.post(
            f"{SOLAPI_API_URL}/messages/v4/send",
            json=payload,
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info(f"알림톡 발송 성공: {to}")
        return {"success": True, "type": "ATA", "result": result}
    except Exception as e:
        logger.warning(f"알림톡 발송 실패, LMS로 대체: {e}")
        return _send_lms(to, text)


def send_test_notification() -> Dict:
    """테스트 알림 발송"""
    from database import get_notification_settings, save_notification_log

    if not is_configured():
        return {"success": False, "error": "Solapi API 키가 설정되지 않았습니다."}

    settings = get_notification_settings()
    receiver = settings.get("receiver_phone", "")
    if not receiver:
        return {"success": False, "error": "수신자 전화번호가 설정되지 않았습니다."}

    test_text = (
        "[로직분석 테스트]\n"
        f"발송 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        "알림톡 연동 테스트입니다.\n"
        "정상적으로 수신되면 알림 설정이 완료된 것입니다."
    )

    result = _send_alimtalk(receiver, test_text)

    save_notification_log(
        log_type="test",
        status="success" if result.get("success") else "failed",
        message=test_text[:500],
        receiver_phone=receiver,
    )

    return result


def send_report_notification(report_text: str, receiver_phone: str) -> Dict:
    """리포트 알림 발송"""
    if not is_configured():
        return {"success": False, "error": "Solapi API 미설정"}

    return _send_alimtalk(receiver_phone, report_text)


# ==================== 리포트 데이터 수집 ====================

def collect_daily_rank_changes() -> List[Dict]:
    """
    일일 순위 변동 데이터 수집
    각 키워드별 최신 vs 이전 순위 비교
    """
    from database import (
        get_all_keywords_with_products,
        get_latest_ranking_for_keyword,
        get_previous_ranking_for_keyword
    )

    keywords = get_all_keywords_with_products()
    rank_changes = []

    for kw in keywords:
        latest = get_latest_ranking_for_keyword(kw["keyword_id"])
        previous = get_previous_ranking_for_keyword(kw["keyword_id"])

        current_rank = latest.get("rank_position") if latest else None
        previous_rank = previous.get("rank_position") if previous else None

        change = None
        if current_rank is not None and previous_rank is not None:
            change = previous_rank - current_rank  # 양수 = 상승

        rank_changes.append({
            "keyword": kw["keyword"],
            "product_name": kw["product_name"],
            "store_name": kw["store_name"],
            "current_rank": current_rank,
            "previous_rank": previous_rank,
            "change": change,
            "checked_at": latest.get("checked_at", "") if latest else "",
        })

    return rank_changes


def generate_daily_report_text(rank_data: List[Dict]) -> str:
    """일일 리포트 텍스트 생성"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"[로직분석 일일 리포트]",
        f"생성: {now}",
        f"추적 키워드: {len(rank_data)}개",
        "─" * 20,
    ]

    # 상승/하락/유지 분류
    up_list = [d for d in rank_data if d["change"] is not None and d["change"] > 0]
    down_list = [d for d in rank_data if d["change"] is not None and d["change"] < 0]
    no_change = [d for d in rank_data if d["change"] is not None and d["change"] == 0]
    not_found = [d for d in rank_data if d["current_rank"] is None]

    if up_list:
        lines.append(f"\n📈 상승 ({len(up_list)}건)")
        for d in sorted(up_list, key=lambda x: -x["change"])[:10]:
            lines.append(f"  ▲{d['change']} {d['keyword']} → {d['current_rank']}위")

    if down_list:
        lines.append(f"\n📉 하락 ({len(down_list)}건)")
        for d in sorted(down_list, key=lambda x: x["change"])[:10]:
            lines.append(f"  ▼{abs(d['change'])} {d['keyword']} → {d['current_rank']}위")

    if no_change:
        lines.append(f"\n➡️ 유지 ({len(no_change)}건)")

    if not_found:
        lines.append(f"\n⚠️ 미발견 ({len(not_found)}건)")
        for d in not_found[:5]:
            lines.append(f"  - {d['keyword']}")

    lines.append("\n─" * 20)
    lines.append("logic.metainc.co.kr")

    return "\n".join(lines)
