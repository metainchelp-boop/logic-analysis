"""네이버 GFA(성과형 디스플레이) 어댑터 — 스캐폴드.

자격: account_id(GFA 광고계정 ID), api_key.
GFA(글래드 포 애드버타이저)는 공식 파트너 등록 + Beta API 신청 후 사용 가능.
엔드포인트/인증 스펙은 파트너 승인 시 제공받아 확정 → env GFA_API_BASE 로 주입.
현재는 Bearer api_key + 리포트 호출 골격만 구현(승인 후 실엔드포인트로 검증).
"""
import os

import requests

from ._common import ads_result

API_BASE = os.environ.get("GFA_API_BASE", "")
TIMEOUT = 30


def fetch_performance(account_id: str, api_key: str, date_from: str = None, date_to: str = None, days: int = 30) -> dict:
    if not (account_id and api_key):
        raise RuntimeError("GFA 광고계정 ID/API 키가 필요합니다")
    if not API_BASE:
        raise RuntimeError(
            "GFA Beta API 엔드포인트(GFA_API_BASE) 미설정 — 네이버 GFA 공식 파트너 승인 후 스펙을 받아 설정해야 합니다"
        )
    headers = {"Authorization": "Bearer " + api_key, "X-Account-Id": str(account_id)}
    params = {}
    if date_from and date_to:
        params = {"startDate": date_from, "endDate": date_to}
        period = f"{date_from} ~ {date_to}"
    else:
        period = f"최근 {days}일"
    r = requests.get(f"{API_BASE.rstrip('/')}/reports", headers=headers, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"GFA API 오류({r.status_code}): {r.text[:200]}")
    rows = r.json().get("data", []) if isinstance(r.json(), dict) else r.json()
    items, t_imp, t_clk, t_sp, t_cv, t_cn = [], 0, 0, 0.0, 0.0, 0.0
    for row in rows or []:
        imp = int(float(row.get("impressions", 0) or 0))
        clk = int(float(row.get("clicks", 0) or 0))
        sp = float(row.get("spend", row.get("cost", 0)) or 0)
        cv = float(row.get("conv_value", 0) or 0)
        cn = float(row.get("conversions", 0) or 0)
        t_imp += imp; t_clk += clk; t_sp += sp; t_cv += cv; t_cn += cn
        items.append({
            "name": row.get("name", "(캠페인)"),
            "impressions": imp, "clicks": clk, "spend": round(sp),
            "roas": round(cv / sp * 100) if sp else None,
        })
    totals = {"impressions": t_imp, "clicks": t_clk, "spend": round(t_sp),
              "conversions": int(t_cn), "conv_value": round(t_cv)}
    return ads_result("naver_gfa", totals, items, period)
