"""광고 채널 어댑터 공용 — 지표 계산 + 정규화 결과 형태.

모든 '광고비 집행형' 채널(메타·카카오·쿠팡·GFA 등)이 같은 형태를 반환하게 해
대시보드·리포트가 공용 렌더러 하나로 처리하도록 한다.

정규화 형태:
  {source, totals:{impressions,clicks,spend,conversions,conv_value},
   ctr, cpc, roas, items:[{name,impressions,clicks,spend,roas}], item_count, period, note}
"""


def compute(impressions: float, clicks: float, spend: float, conv_value: float):
    ctr = round(clicks / impressions * 100, 2) if impressions else 0
    cpc = round(spend / clicks) if clicks else 0
    roas = round(conv_value / spend * 100) if spend else None
    return ctr, cpc, roas


def ads_result(source: str, totals: dict, items: list, period: str = "", note: str = "") -> dict:
    imp = totals.get("impressions", 0) or 0
    clk = totals.get("clicks", 0) or 0
    sp = totals.get("spend", 0) or 0
    cv = totals.get("conv_value", 0) or 0
    ctr, cpc, roas = compute(imp, clk, sp, cv)
    return {
        "source": source,
        "totals": {
            "impressions": imp, "clicks": clk, "spend": sp,
            "conversions": totals.get("conversions", 0) or 0, "conv_value": cv,
        },
        "ctr": ctr, "cpc": cpc, "roas": roas,
        "items": items, "item_count": len(items),
        "period": period, "note": note,
    }
