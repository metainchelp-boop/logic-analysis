"""카카오모먼트 어댑터 — Kakao Moment OpenAPI 보고서.

자격: account_id(광고계정 ID), rest_key(비즈니스 액세스 토큰).
참고: https://developers.kakao.com/docs/latest/ko/kakaomoment/report
  GET https://apis.moment.kakao.com/openapi/v4/adAccounts/report
  헤더 Authorization: Bearer {token}, adAccountId: {id}
  파라미터 start/end(YYYYMMDD), level, metricsGroup=BASIC
※ 토큰은 카카오 비즈니스 OAuth로 발급한 액세스 토큰이어야 함(REST키 자체로는 부족할 수 있음).
"""
import requests

from ._common import ads_result

BASE = "https://apis.moment.kakao.com/openapi/v4"
TIMEOUT = 30


def fetch_performance(account_id: str, rest_key: str, date_from: str = None, date_to: str = None, days: int = 30) -> dict:
    if not (account_id and rest_key):
        raise RuntimeError("카카오 광고계정 ID/토큰이 필요합니다")
    headers = {"Authorization": "Bearer " + rest_key, "adAccountId": str(account_id)}
    params = {"level": "CAMPAIGN", "metricsGroup": "BASIC"}
    if date_from and date_to:
        params["start"] = date_from.replace("-", "")
        params["end"] = date_to.replace("-", "")
        period = f"{date_from} ~ {date_to}"
    else:
        params["datePreset"] = "LAST_30_DAYS"
        period = f"최근 {days}일"
    r = requests.get(f"{BASE}/adAccounts/report", headers=headers, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"카카오 API 오류({r.status_code}): {r.text[:200]}")
    rows = r.json().get("data", []) or r.json().get("report", [])
    items, t_imp, t_clk, t_sp, t_cv, t_cn = [], 0, 0, 0.0, 0.0, 0.0
    for row in rows:
        m = row.get("metrics", row)
        imp = int(float(m.get("imp", m.get("impressions", 0)) or 0))
        clk = int(float(m.get("click", m.get("clicks", 0)) or 0))
        sp = float(m.get("cost", m.get("spend", 0)) or 0)
        cv = float(m.get("convPurchaseP_value", m.get("conv_value", 0)) or 0)
        cn = float(m.get("convPurchaseP", m.get("conversions", 0)) or 0)
        t_imp += imp; t_clk += clk; t_sp += sp; t_cv += cv; t_cn += cn
        dim = row.get("dimensions", {})
        items.append({
            "name": dim.get("campaign_name", dim.get("campaign", row.get("name", "(캠페인)"))),
            "impressions": imp, "clicks": clk, "spend": round(sp),
            "roas": round(cv / sp * 100) if sp else None,
        })
    totals = {"impressions": t_imp, "clicks": t_clk, "spend": round(t_sp),
              "conversions": int(t_cn), "conv_value": round(t_cv)}
    return ads_result("kakao", totals, items, period)
