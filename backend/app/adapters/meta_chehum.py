"""메타체험단(자사 체험단 플랫폼) 어댑터 — 광고주(공급사)별 캠페인 결과 요약 조회.

메타체험단 서버의 읽기전용 연동 API(/mc_ad_api.php, 토큰 보호)를 호출한다.
회원(리뷰어) 개인정보는 가져오지 않으며 광고주별 '캠페인 결과 요약'만 제공.

설정(환경변수):
  MC_AD_API_URL    기본 https://meta-chehumdan.com/mc_ad_api.php
  MC_AD_API_TOKEN  연동 토큰(메타체험단 mc_cal/mc_ad 공용 토큰)
광고주 매칭 키 advertiser_id = 메타체험단 공급사 회원번호(cp_supply_no).
"""
import os

import requests

API_URL = os.environ.get("MC_AD_API_URL", "https://meta-chehumdan.com/mc_ad_api.php")
TOKEN = os.environ.get("MC_AD_API_TOKEN", "")
TIMEOUT = 30


def _call(mode: str, **params) -> dict:
    if not TOKEN:
        raise RuntimeError("MC_AD_API_TOKEN 미설정 — 메타체험단 연동 토큰이 필요합니다")
    q = {"token": TOKEN, "mode": mode}
    q.update({k: v for k, v in params.items() if v not in (None, "")})
    r = requests.get(API_URL, params=q, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "메타체험단 API 오류"))
    return data


def list_advertisers() -> list:
    """연동 가능한 광고주(공급사) 목록 — 대시보드 광고주 등록 시 선택용."""
    return _call("advertisers").get("advertisers", [])


def fetch_summary(advertiser_id) -> dict:
    return _call("summary", supply_no=advertiser_id)


def fetch_campaigns(advertiser_id) -> list:
    return _call("campaigns", supply_no=advertiser_id).get("campaigns", [])


def fetch_performance(advertiser_id) -> dict:
    """수집기·대시보드·AI리포트 공용 — 합계 + 캠페인 목록을 함께 반환."""
    summary = fetch_summary(advertiser_id)
    campaigns = fetch_campaigns(advertiser_id)
    return {
        "summary": {k: v for k, v in summary.items() if k not in ("ok", "mode")},
        "campaigns": campaigns,
    }
