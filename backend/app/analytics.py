"""분석 엔진 — AI 고도화 기능 공용 토대.

ChannelMetric(정기 수집 스냅샷) 이력에서 채널별 KPI 시계열을 뽑고,
추세(선형회귀)·상관(피어슨)·백분위 등 통계 헬퍼를 제공한다.
외부 의존성 없이 순수 파이썬으로 구현(테스트·이식 용이).
"""
import json
from typing import Optional

from sqlalchemy.orm import Session

from . import models


# ── KPI 정규화 ────────────────────────────────────────────────────────────
def kpi_from_payload(channel: str, data: dict) -> Optional[dict]:
    """채널 스냅샷 payload → 공통 광고 KPI. 광고비 집행형이 아니면 None.

    반환: {imp, clk, spend, conv, conv_value, roas, ctr, cpc}
    """
    if not isinstance(data, dict):
        return None
    if channel == "naver_searchad":
        t = data.get("totals", {}) or {}
        imp, clk, spend = t.get("impCnt", 0) or 0, t.get("clkCnt", 0) or 0, t.get("salesAmt", 0) or 0
        conv, cv = t.get("ccnt", 0) or 0, t.get("convAmt", 0) or 0
    elif data.get("source"):  # 정규화 광고채널(메타·카카오·쿠팡·GFA·업로드/수동)
        t = data.get("totals", {}) or {}
        imp, clk, spend = t.get("impressions", 0) or 0, t.get("clicks", 0) or 0, t.get("spend", 0) or 0
        conv, cv = t.get("conversions", 0) or 0, t.get("conv_value", 0) or 0
    else:
        return None
    ctr = round(clk / imp * 100, 2) if imp else 0
    cpc = round(spend / clk) if clk else 0
    roas = data.get("roas")
    if roas is None and spend:
        roas = round(cv / spend * 100, 1)
    return {"imp": imp, "clk": clk, "spend": spend, "conv": conv,
            "conv_value": cv, "roas": roas, "ctr": ctr, "cpc": cpc}


def _iso(dt) -> Optional[str]:
    if not dt:
        return None
    s = dt.isoformat()
    # 이미 오프셋이 붙은(aware) 경우 'Z'를 또 붙이지 않음
    return s if dt.tzinfo is not None else s + "Z"


# ── 시계열 추출 ────────────────────────────────────────────────────────────
def channel_series(db: Session, client_id: int) -> dict:
    """광고주의 채널별 KPI 시계열(오래된→최신). {channel: [{at, kpi}]}.

    광고비 집행형 채널만(KPI 정규화 가능한 것). 같은 날 여러 스냅샷이면 모두 포함.
    """
    rows = (
        db.query(models.ChannelMetric)
        .filter(models.ChannelMetric.client_id == client_id)
        .order_by(models.ChannelMetric.id.asc())
        .all()
    )
    out: dict = {}
    for m in rows:
        try:
            data = json.loads(m.payload_json or "{}")
        except Exception:  # noqa: BLE001
            continue
        kpi = kpi_from_payload(m.channel, data)
        if not kpi:
            continue
        out.setdefault(m.channel, []).append({"at": _iso(m.collected_at), "kpi": kpi})
    return out


def combined_series(db: Session, client_id: int) -> list:
    """수집일(YYYY-MM-DD)별 전 채널 합산 시계열(오래된→최신).

    반환: [{date, spend, conv_value, roas}]. 같은 날 여러 채널은 합산.
    """
    series = channel_series(db, client_id)
    # 같은 날·같은 채널 중복 스냅샷은 최신값만(이중계상 방지) — series는 오래된→최신 정렬
    cell: dict = {}
    for ch, pts in series.items():
        for p in pts:
            d = (p["at"] or "")[:10]
            if d:
                cell[(d, ch)] = p["kpi"]  # 뒤에 오는 최신값이 덮어씀
    bydate: dict = {}
    for (d, _ch), kpi in cell.items():
        agg = bydate.setdefault(d, {"spend": 0.0, "conv_value": 0.0})
        agg["spend"] += kpi["spend"] or 0
        agg["conv_value"] += kpi["conv_value"] or 0
    out = []
    for d in sorted(bydate):
        sp, cv = bydate[d]["spend"], bydate[d]["conv_value"]
        out.append({"date": d, "spend": round(sp),
                    "conv_value": round(cv),
                    "roas": round(cv / sp * 100, 1) if sp else None})
    return out


def latest_per_channel(db: Session, client_id: int) -> dict:
    """채널별 최신 스냅샷 데이터. {channel: data}. (전 채널 — 광고형 아닌 것 포함)"""
    rows = (
        db.query(models.ChannelMetric)
        .filter(models.ChannelMetric.client_id == client_id)
        .order_by(models.ChannelMetric.id.desc())
        .all()
    )
    out: dict = {}
    for m in rows:
        if m.channel in out:
            continue
        try:
            out[m.channel] = json.loads(m.payload_json or "{}")
        except Exception:  # noqa: BLE001
            continue
    return out


# ── 통계 헬퍼 ──────────────────────────────────────────────────────────────
def linreg(values: list):
    """[y0,y1,...] 를 x=0,1,... 에 회귀 → (slope, intercept). 표본<2면 (0, mean)."""
    ys = [float(v) for v in values if v is not None]
    n = len(ys)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0, my
    slope = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / denom
    return slope, my - slope * mx


def forecast_next(values: list, steps: int = 1):
    """선형 추세로 다음 step 값 예측(음수 방지)."""
    ys = [float(v) for v in values if v is not None]
    if not ys:
        return None
    slope, intercept = linreg(ys)
    pred = slope * (len(ys) - 1 + steps) + intercept
    return max(0.0, pred)


def pct_change(values: list):
    """첫→마지막 변화율(%). 표본<2 또는 첫값 0이면 None."""
    ys = [float(v) for v in values if v is not None]
    if len(ys) < 2 or ys[0] == 0:
        return None
    return round((ys[-1] - ys[0]) / ys[0] * 100, 1)


def pearson(xs: list, ys: list):
    """두 시계열 상관계수 r(-1~1). 길이 다르면 짧은 쪽에 맞춤. 표본<3이면 None."""
    pairs = [(float(a), float(b)) for a, b in zip(xs, ys) if a is not None and b is not None]
    n = len(pairs)
    if n < 3:
        return None
    ax = sum(p[0] for p in pairs) / n
    ay = sum(p[1] for p in pairs) / n
    sxy = sum((p[0] - ax) * (p[1] - ay) for p in pairs)
    sxx = sum((p[0] - ax) ** 2 for p in pairs)
    syy = sum((p[1] - ay) ** 2 for p in pairs)
    if sxx == 0 or syy == 0:
        return None
    return round(sxy / (sxx ** 0.5 * syy ** 0.5), 3)


def percentile_rank(value: float, population: list):
    """모집단 대비 value의 백분위(0~100). 모집단 비면 None."""
    pop = [float(v) for v in population if v is not None]
    if not pop or value is None:
        return None
    below = sum(1 for v in pop if v < value)
    equal = sum(1 for v in pop if v == value)
    return round((below + 0.5 * equal) / len(pop) * 100)
