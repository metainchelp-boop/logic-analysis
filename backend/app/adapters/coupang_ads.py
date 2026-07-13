"""쿠팡애즈 어댑터 — Coupang Open API(HMAC, CEA 서명).

자격: vendor_id(업체 ID), access_key, secret_key.
서명(공식): Authorization: CEA algorithm=HmacSHA256, access-key=<KEY>, signed-date=<yyMMddTHHmmssZ>, signature=<hex>
  message = datetime + method + path + query, HMAC-SHA256 hexdigest(secret_key).
  헤더 X-Requested-By = vendor_id.
참고: https://developers.coupangcorp.com/hc/en-us/articles/360033461914
※ 광고(애즈) 리포트 엔드포인트 경로는 쿠팡 광고센터 API 권한 발급 후 확정 → env COUPANG_ADS_PATH 로 주입.
"""
import os
import hmac
import hashlib
from datetime import datetime, timezone

import requests

from ._common import ads_result

BASE = os.environ.get("COUPANG_API_BASE", "https://api-gateway.coupang.com")
# 광고 리포트 경로(권한 발급 후 확정). 기본값은 자리표시 — 미설정 시 친절히 안내.
REPORT_PATH = os.environ.get("COUPANG_ADS_PATH", "")
TIMEOUT = 30


def _auth_header(method: str, path: str, query: str, access_key: str, secret_key: str):
    dt = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    message = dt + method + path + (query or "")
    signature = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={access_key}, "
        f"signed-date={dt}, signature={signature}"
    )


def fetch_performance(vendor_id: str, access_key: str, secret_key: str, date_from: str = None, date_to: str = None, days: int = 30) -> dict:
    if not (vendor_id and access_key and secret_key):
        raise RuntimeError("쿠팡 업체ID/액세스키/시크릿키가 필요합니다")
    if not REPORT_PATH:
        raise RuntimeError(
            "쿠팡애즈 리포트 경로(COUPANG_ADS_PATH) 미설정 — 쿠팡 광고센터 API 권한 발급 후 엔드포인트 경로를 넣어주세요"
        )
    query = ""
    if date_from and date_to:
        query = f"startDate={date_from.replace('-', '')}&endDate={date_to.replace('-', '')}"
        period = f"{date_from} ~ {date_to}"
    else:
        period = f"최근 {days}일"
    headers = {
        "Authorization": _auth_header("GET", REPORT_PATH, query, access_key, secret_key),
        "X-Requested-By": str(vendor_id),
        "Content-Type": "application/json;charset=UTF-8",
    }
    url = BASE + REPORT_PATH + (("?" + query) if query else "")
    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"쿠팡 API 오류({r.status_code}): {r.text[:200]}")
    rows = r.json().get("data", []) if isinstance(r.json(), dict) else r.json()
    items, t_imp, t_clk, t_sp, t_cv, t_cn = [], 0, 0, 0.0, 0.0, 0.0
    for row in rows or []:
        imp = int(float(row.get("impressions", row.get("impression", 0)) or 0))
        clk = int(float(row.get("clicks", row.get("click", 0)) or 0))
        sp = float(row.get("adcost", row.get("spend", 0)) or 0)
        cv = float(row.get("convValue", row.get("conv_value", 0)) or 0)
        cn = float(row.get("conversions", row.get("conversion", 0)) or 0)
        t_imp += imp; t_clk += clk; t_sp += sp; t_cv += cv; t_cn += cn
        items.append({
            "name": row.get("campaignName", row.get("name", "(캠페인)")),
            "impressions": imp, "clicks": clk, "spend": round(sp),
            "roas": round(cv / sp * 100) if sp else None,
        })
    totals = {"impressions": t_imp, "clicks": t_clk, "spend": round(t_sp),
              "conversions": int(t_cn), "conv_value": round(t_cv)}
    return ads_result("coupang_ads", totals, items, period)
