"""메타 광고(인스타·페북) 어댑터 — Meta Marketing API(Graph) insights.

광고계정별 자격: account_id(act_... 또는 숫자), access_token(장기 토큰).
캠페인 단위 노출·클릭·광고비·구매전환·전환매출(ROAS) 조회.
참고: https://developers.facebook.com/docs/marketing-api/insights/
※ 운영 사용엔 Meta 비즈니스 앱 검수(앱심사) + ads_read 권한 토큰 필요.
"""
import requests

from ._common import ads_result

GRAPH = "https://graph.facebook.com/v23.0"
TIMEOUT = 30
PURCHASE_ACTIONS = {
    "purchase", "omni_purchase",
    "offsite_conversion.fb_pixel_purchase", "onsite_web_purchase",
}


def _act(account_id: str) -> str:
    aid = str(account_id).strip()
    return aid if aid.startswith("act_") else "act_" + aid


def _sum_actions(rows, wanted):
    total = 0.0
    for a in rows or []:
        if a.get("action_type") in wanted:
            total += float(a.get("value", 0) or 0)
    return total


def fetch_performance(account_id: str, access_token: str, date_from: str = None, date_to: str = None, days: int = 30) -> dict:
    if not (account_id and access_token):
        raise RuntimeError("메타 광고계정 ID/액세스 토큰이 필요합니다")
    params = {
        "level": "campaign",
        "fields": "campaign_name,impressions,clicks,spend,ctr,cpc,actions,action_values",
        "access_token": access_token,
        "limit": 200,
    }
    if date_from and date_to:
        params["time_range"] = '{"since":"%s","until":"%s"}' % (date_from, date_to)
        period = f"{date_from} ~ {date_to}"
    else:
        params["date_preset"] = "last_30d"
        period = f"최근 {days}일"
    r = requests.get(f"{GRAPH}/{_act(account_id)}/insights", params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"메타 API 오류({r.status_code}): {r.text[:200]}")
    data = r.json().get("data", [])
    items, t_imp, t_clk, t_sp, t_cv, t_cn = [], 0, 0, 0.0, 0.0, 0.0
    for row in data:
        imp = int(float(row.get("impressions", 0) or 0))
        clk = int(float(row.get("clicks", 0) or 0))
        sp = float(row.get("spend", 0) or 0)
        cv = _sum_actions(row.get("action_values"), PURCHASE_ACTIONS)
        cn = _sum_actions(row.get("actions"), PURCHASE_ACTIONS)
        t_imp += imp; t_clk += clk; t_sp += sp; t_cv += cv; t_cn += cn
        items.append({
            "name": row.get("campaign_name", "(이름없음)"),
            "impressions": imp, "clicks": clk, "spend": round(sp),
            "roas": round(cv / sp * 100) if sp else None,
        })
    totals = {"impressions": t_imp, "clicks": t_clk, "spend": round(t_sp),
              "conversions": int(t_cn), "conv_value": round(t_cv)}
    return ads_result("meta_ads", totals, items, period)
