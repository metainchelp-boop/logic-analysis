"""AI 고도화 인사이트 — 학습센터 누적 데이터를 활용한 분석·예측·추천 묶음.

데이터 출처: ChannelMetric(정기 수집 스냅샷), CampaignProposal, Report 등.
순수 통계는 analytics.py, LLM 추론은 ai_insights.py 사용.
"""
import json
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, can_edit
from .. import models, security, analytics

router = APIRouter(tags=["insights"])

KST = timezone(timedelta(hours=9))


# ── 공통 ────────────────────────────────────────────────────────────────────
def _client_for_read(db: Session, user: models.User, client_id: int) -> models.Client:
    c = db.get(models.Client, client_id)
    if not c:
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    if user.role in ("admin", "viewer") or can_edit(user, c):
        return c
    raise HTTPException(404, "광고주를 찾을 수 없습니다")


def _setting(db: Session, client_id: int, key: str, default: dict) -> dict:
    row = (db.query(models.ClientSetting)
           .filter(models.ClientSetting.client_id == client_id,
                   models.ClientSetting.key == key).first())
    if not row:
        return dict(default)
    try:
        return {**default, **json.loads(row.value_json or "{}")}
    except Exception:  # noqa: BLE001
        return dict(default)


def _save_setting(db: Session, client_id: int, key: str, value: dict):
    row = (db.query(models.ClientSetting)
           .filter(models.ClientSetting.client_id == client_id,
                   models.ClientSetting.key == key).first())
    if row:
        row.value_json = json.dumps(value, ensure_ascii=False)
    else:
        db.add(models.ClientSetting(client_id=client_id, key=key,
                                    value_json=json.dumps(value, ensure_ascii=False)))
    db.commit()


CHANNEL_LABELS = {
    "naver_searchad": "네이버 검색광고", "naver_commerce": "네이버 커머스",
    "meta_ads": "메타 광고", "kakao": "카카오모먼트", "coupang_ads": "쿠팡애즈",
    "naver_gfa": "네이버 GFA", "meta_chehum": "메타체험단", "youtube": "유튜브",
    "daangn": "당근", "toss_ads": "토스애즈", "mobon": "모비온",
}


def _lab(ch: str) -> str:
    return CHANNEL_LABELS.get(ch, ch)


# ════════════════════════════════════════════════════════════════════════
# #1 성과 예측 + 해지위험 경보
# ════════════════════════════════════════════════════════════════════════
@router.get("/insights/{client_id}/forecast")
def forecast(client_id: int, db: Session = Depends(get_db),
             user: models.User = Depends(get_current_user)):
    _client_for_read(db, user, client_id)
    ts = analytics.combined_series(db, client_id)
    roas_vals = [p["roas"] for p in ts if p["roas"] is not None]
    spend_vals = [p["spend"] for p in ts]
    n = len(ts)

    next_roas = round(analytics.forecast_next(roas_vals), 1) if len(roas_vals) >= 2 else None
    next_spend = round(analytics.forecast_next(spend_vals)) if len(spend_vals) >= 2 else None
    roas_trend = analytics.pct_change(roas_vals)

    # 해지위험 점수(0~100): 데이터 근거 가산
    risk, reasons = 0, []
    # 최신 ROAS는 가장 최근 수집일 기준(None 필터된 리스트의 끝이 아닌, 날짜 정렬된 ts의 끝)
    latest_roas = ts[-1]["roas"] if ts else None
    if latest_roas is None and roas_vals:
        latest_roas = roas_vals[-1]
    if roas_trend is not None and roas_trend < -20:
        risk += 35; reasons.append(f"ROAS 하락 추세 ({roas_trend}%)")
    if latest_roas is not None and latest_roas < 150:
        risk += 30; reasons.append(f"최근 ROAS 저조 ({latest_roas}%)")
    if len(spend_vals) >= 2 and spend_vals[-2] > 0 and spend_vals[-1] < spend_vals[-2] * 0.5:
        risk += 20; reasons.append("최근 광고비 급감(집행 축소)")
    # 체험단 리뷰 이행률 저조
    latest = analytics.latest_per_channel(db, client_id)
    mc = latest.get("meta_chehum", {})
    rate = (mc.get("summary", {}) or {}).get("avg_review_rate")
    if rate is not None and rate < 50:
        risk += 15; reasons.append(f"체험단 리뷰 이행률 저조 ({rate}%)")
    risk = min(100, risk)
    level = "높음" if risk >= 60 else ("보통" if risk >= 30 else "낮음")

    return {
        "data_points": n,
        "enough_data": n >= 3,
        "series": ts[-12:],
        "forecast": {"next_roas": next_roas, "next_spend": next_spend, "roas_trend_pct": roas_trend},
        "churn_risk": {"score": risk, "level": level, "reasons": reasons},
        "note": None if n >= 3 else "예측 정확도를 위해 수집 데이터가 더 필요합니다(최소 3회 이상).",
    }


# ════════════════════════════════════════════════════════════════════════
# #2 채널 예산 재배분 추천
# ════════════════════════════════════════════════════════════════════════
@router.get("/insights/{client_id}/budget-advice")
def budget_advice(client_id: int, db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_user)):
    _client_for_read(db, user, client_id)
    latest = analytics.latest_per_channel(db, client_id)
    rows = []
    for ch, data in latest.items():
        kpi = analytics.kpi_from_payload(ch, data)
        if not kpi or (kpi["spend"] or 0) <= 0:
            continue
        rows.append({"channel": ch, "label": _lab(ch), "spend": round(kpi["spend"]),
                     "roas": kpi["roas"]})
    rows = [r for r in rows if r["roas"] is not None]
    if len(rows) < 2:
        return {"channels": rows, "suggestions": [],
                "note": "비교하려면 광고비가 집행된 채널이 2개 이상 필요합니다."}
    rows.sort(key=lambda r: r["roas"], reverse=True)
    best, worst = rows[0], rows[-1]
    total_spend = sum(r["spend"] for r in rows)
    avg_roas = round(sum(r["roas"] * r["spend"] for r in rows) / total_spend, 1) if total_spend else None
    suggestions = []
    if best["roas"] and worst["roas"] and best["roas"] >= worst["roas"] * 1.3:
        move = round(worst["spend"] * 0.3)
        gain = round(move * (best["roas"] - worst["roas"]) / 100)
        suggestions.append({
            "from": worst["label"], "to": best["label"], "amount": move,
            "reason": f"{worst['label']} ROAS {worst['roas']}% → {best['label']} {best['roas']}%. "
                      f"{move:,}원 이동 시 약 {gain:,}원 매출 증가 기대(추정).",
        })
    return {"channels": rows, "avg_roas": avg_roas, "suggestions": suggestions,
            "note": None if suggestions else "현재 채널 간 효율 차이가 크지 않아 재배분 권고가 없습니다."}


# ════════════════════════════════════════════════════════════════════════
# #3 키워드·입찰가 학습 추천 (검색광고 캠페인 단위)
# ════════════════════════════════════════════════════════════════════════
@router.get("/insights/{client_id}/keyword-advice")
def keyword_advice(client_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    _client_for_read(db, user, client_id)
    latest = analytics.latest_per_channel(db, client_id)
    sa = latest.get("naver_searchad")
    if not sa:
        return {"items": [], "note": "검색광고 수집 데이터가 아직 없습니다."}
    items = []
    for c in sa.get("campaigns", []):
        roas = c.get("roas")
        spend = c.get("salesAmt", 0) or 0
        clk = c.get("clkCnt", 0) or 0
        if roas is None:
            action, why = "관찰", "전환 데이터 부족 — 더 지켜보기"
        elif roas >= 400 and clk >= 50:
            action, why = "입찰 ↑", f"ROAS {roas}%로 매우 효율적 — 입찰가 상향해 노출 확대"
        elif roas >= 200:
            action, why = "유지", f"ROAS {roas}% — 현 수준 유지"
        elif spend > 0 and roas < 120:
            action, why = "입찰 ↓ / OFF 검토", f"ROAS {roas}%로 저조 — 입찰가 하향 또는 중단 검토"
        else:
            action, why = "관찰", f"ROAS {roas}% — 개선 추이 관찰"
        items.append({"name": c.get("name"), "roas": roas, "spend": round(spend),
                      "clicks": clk, "action": action, "why": why})
    items.sort(key=lambda x: (x["roas"] is None, -(x["roas"] or 0)))
    return {"items": items,
            "note": "캠페인 단위 추천입니다. 키워드 단위 정밀 추천은 AI 캠페인 설계와 연계됩니다."}


# ════════════════════════════════════════════════════════════════════════
# #4 동종 광고주 비교(벤치마크)
# ════════════════════════════════════════════════════════════════════════
def _client_kpi(db: Session, client_id: int) -> dict:
    """광고주의 채널 합산 CTR·CPC·ROAS(최신 스냅샷 기준)."""
    latest = analytics.latest_per_channel(db, client_id)
    imp = clk = spend = cv = 0
    for ch, data in latest.items():
        k = analytics.kpi_from_payload(ch, data)
        if not k:
            continue
        imp += k["imp"] or 0; clk += k["clk"] or 0
        spend += k["spend"] or 0; cv += k["conv_value"] or 0
    return {
        "ctr": round(clk / imp * 100, 2) if imp else None,
        "cpc": round(spend / clk) if clk else None,
        "roas": round(cv / spend * 100, 1) if spend else None,
        "spend": int(spend) if spend else 0,
        "has_data": spend > 0 or imp > 0,
    }


@router.get("/insights/{client_id}/peer-compare")
def peer_compare(client_id: int, db: Session = Depends(get_db),
                 user: models.User = Depends(get_current_user)):
    c = _client_for_read(db, user, client_id)
    # ★보안: 비교 모집단은 '사용자가 볼 수 있는' 광고주로 제한(타 담당자 데이터 누수 방지).
    #   대표(admin)/viewer=전사 → 회사 벤치마크, 담당자=본인 범위.
    from ..deps import visible_clients
    peers = (visible_clients(db, user)
             .filter(models.Client.category == c.category,
                     models.Client.id != client_id).all()) if c.category else []
    me = _client_kpi(db, client_id)
    pop = {"ctr": [], "cpc": [], "roas": []}
    for p in peers:
        k = _client_kpi(db, p.id)
        if not k["has_data"]:
            continue
        for m in ("ctr", "cpc", "roas"):
            if k[m] is not None:
                pop[m].append(k[m])
    out = {}
    for m in ("ctr", "cpc", "roas"):
        val = me[m]
        rank = analytics.percentile_rank(val, pop[m]) if val is not None else None
        # CPC는 낮을수록 좋음 → 백분위 반전
        if m == "cpc" and rank is not None:
            rank = 100 - rank
        avg = round(sum(pop[m]) / len(pop[m]), 1) if pop[m] else None
        out[m] = {"value": val, "peer_avg": avg, "percentile": rank, "peer_n": len(pop[m])}
    return {"category": c.category, "peer_count": len(peers), "me": me, "metrics": out,
            "note": None if any(out[m]["peer_n"] for m in out) else
            "같은 업종의 비교 대상 광고주 데이터가 아직 부족합니다."}


# ════════════════════════════════════════════════════════════════════════
# #5 텍스트 분석(리뷰·댓글 감성/키워드)
# ════════════════════════════════════════════════════════════════════════
@router.get("/insights/{client_id}/text-insights")
def text_insights(client_id: int, db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_user)):
    c = _client_for_read(db, user, client_id)
    texts = []
    # 유튜브 댓글(연동·키 있을 때)
    cred = (db.query(models.ChannelCredential)
            .filter(models.ChannelCredential.client_id == client_id,
                    models.ChannelCredential.channel == "youtube",
                    models.ChannelCredential.status == "connected").first())
    if cred:
        fields = {k: security.decrypt(v) for k, v in json.loads(cred.fields_json or "{}").items()}
        url = fields.get("video_url")
        if url:
            from ..adapters import youtube
            try:
                texts = youtube.fetch_comments(url, per_video=25)
            except Exception:  # noqa: BLE001
                texts = []
    if not texts:
        return {"available": False, "text_count": 0,
                "note": "분석할 리뷰/댓글 텍스트가 아직 없어요. 유튜브 연동(+공용 API 키)이 있으면 영상 댓글을 분석합니다."}
    from .. import ai_insights
    try:
        result = ai_insights.analyze_text(texts, brand=c.name)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))
    result["available"] = True
    result["text_count"] = len(texts)
    return result


# ════════════════════════════════════════════════════════════════════════
# #6 채널 시너지·기여도 분석
# ════════════════════════════════════════════════════════════════════════
@router.get("/insights/{client_id}/synergy")
def synergy(client_id: int, db: Session = Depends(get_db),
            user: models.User = Depends(get_current_user)):
    _client_for_read(db, user, client_id)
    series = analytics.channel_series(db, client_id)
    # 채널별 날짜→roas 매핑(3회 이상 수집된 채널만 상관 분석 대상)
    by_ch_roas, all_dates = {}, set()
    for ch, pts in series.items():
        rmap = {}
        for p in pts:
            d = (p["at"] or "")[:10]
            if not d:
                continue
            rmap[d] = p["kpi"]["roas"]; all_dates.add(d)
        if len(rmap) >= 3:
            by_ch_roas[ch] = rmap
    dates = sorted(all_dates)
    pairs = []
    chs = list(by_ch_roas.keys())
    for i in range(len(chs)):
        for j in range(i + 1, len(chs)):
            a, b = chs[i], chs[j]
            xs = [by_ch_roas[a].get(d) for d in dates]
            ys = [by_ch_roas[b].get(d) for d in dates]
            r = analytics.pearson(xs, ys)
            if r is not None and abs(r) >= 0.5:
                rel = "함께 오르내림(시너지)" if r > 0 else "상충(한쪽↑ 다른쪽↓)"
                pairs.append({"a": _lab(a), "b": _lab(b), "corr": r, "relation": rel})
    pairs.sort(key=lambda x: -abs(x["corr"]))
    return {"correlations": pairs, "channels_analyzed": [_lab(c) for c in chs],
            "note": None if pairs else "유의미한 채널 간 상관을 찾으려면 수집 이력이 더 쌓여야 합니다(채널별 3회 이상)."}


# ════════════════════════════════════════════════════════════════════════
# #7 캠페인 성공확률 예측
# ════════════════════════════════════════════════════════════════════════
@router.get("/insights/{client_id}/proposal-success/{pid}")
def proposal_success(client_id: int, pid: int, db: Session = Depends(get_db),
                     user: models.User = Depends(get_current_user)):
    c = _client_for_read(db, user, client_id)
    row = db.get(models.CampaignProposal, pid)
    if not row or row.client_id != client_id:
        raise HTTPException(404, "캠페인안을 찾을 수 없습니다")
    proposal = json.loads(row.proposal_json or "{}")
    exp_roas = (proposal.get("expected") or {}).get("roas")

    # 업종 벤치마크(동종 광고주 평균 ROAS)
    bench = peer_compare(client_id, db, user)
    peer_avg = (bench.get("metrics", {}).get("roas", {}) or {}).get("peer_avg")

    score, factors = 50, []
    if exp_roas is not None and peer_avg is not None:
        if exp_roas >= peer_avg:
            score += 20; factors.append(f"목표 ROAS({exp_roas}%)가 동종 평균({peer_avg}%) 이상")
        else:
            score -= 15; factors.append(f"목표 ROAS({exp_roas}%)가 동종 평균({peer_avg}%) 미만 — 보수적 검토")
    # 과거 본 광고주 검색광고 실적
    me = _client_kpi(db, client_id)
    if me["roas"] is not None:
        if me["roas"] >= 300:
            score += 15; factors.append(f"이 광고주 기존 ROAS 양호({me['roas']}%)")
        elif me["roas"] < 150:
            score -= 10; factors.append(f"이 광고주 기존 ROAS 저조({me['roas']}%)")
    # 데이터 충분성
    ndata = bench.get("metrics", {}).get("roas", {}).get("peer_n", 0)
    if ndata >= 3:
        score += 10; factors.append("동종 비교 표본 충분")
    else:
        factors.append("동종 비교 표본 부족 — 확률 신뢰도 낮음")
    # 키워드 구성 적정성
    groups = (proposal.get("naver_searchad") or {}).get("ad_groups") or []
    kw = sum(len(g.get("keywords") or []) for g in groups)
    if kw >= 8:
        score += 5; factors.append(f"키워드 {kw}개로 구성 적정")
    score = max(5, min(95, score))
    label = "높음" if score >= 65 else ("보통" if score >= 40 else "낮음")
    return {"proposal_id": pid, "success_probability": score, "level": label,
            "factors": factors, "expected_roas": exp_roas, "peer_avg_roas": peer_avg,
            "note": "통계·벤치마크 기반 추정치입니다. 실제 적용 결과가 쌓이면 정확도가 올라갑니다."}


# ════════════════════════════════════════════════════════════════════════
# #8 자연어 질의 비서
# ════════════════════════════════════════════════════════════════════════
def _assistant_context(db: Session, user: models.User) -> dict:
    """비서가 참고할 데이터 — 사용자 권한 범위 광고주들의 최신 핵심 KPI."""
    from ..deps import visible_clients
    clients = visible_clients(db, user).all()
    ctx = []
    for c in clients[:40]:
        k = _client_kpi(db, c.id)
        owner = db.get(models.User, c.owner_id) if c.owner_id else None
        ctx.append({"name": c.name, "category": c.category, "status": c.status,
                    "owner": owner.name if owner else None,
                    "spend": k["spend"], "ctr": k["ctr"], "cpc": k["cpc"], "roas": k["roas"]})
    return {"clients": ctx, "count": len(ctx)}


@router.post("/insights/assistant")
def assistant(question: str = Body(..., embed=True), db: Session = Depends(get_db),
              user: models.User = Depends(get_current_user)):
    q = (question or "").strip()
    if not q:
        raise HTTPException(400, "질문을 입력하세요")
    ctx = _assistant_context(db, user)
    from .. import ai_insights
    try:
        answer = ai_insights.nl_query(q, ctx)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))
    return {"question": q, "answer": answer, "clients_considered": ctx["count"]}


# ════════════════════════════════════════════════════════════════════════
# #9 자동 운영(오토파일럿) — 안전 프레임(드라이런 시뮬레이션)
# ════════════════════════════════════════════════════════════════════════
AUTOPILOT_DEFAULT = {"enabled": False, "target_roas": 300, "max_bid_change_pct": 20}


@router.get("/insights/{client_id}/autopilot")
def get_autopilot(client_id: int, db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_user)):
    _client_for_read(db, user, client_id)
    return _setting(db, client_id, "autopilot", AUTOPILOT_DEFAULT)


@router.post("/insights/{client_id}/autopilot")
def set_autopilot(client_id: int, cfg: dict = Body(...), db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_user)):
    c = _client_for_read(db, user, client_id)
    if not can_edit(user, c):
        raise HTTPException(403, "권한이 없습니다")
    merged = {**AUTOPILOT_DEFAULT, **{k: cfg.get(k) for k in AUTOPILOT_DEFAULT if k in cfg}}
    try:
        merged["target_roas"] = max(0, min(2000, int(merged["target_roas"])))
        merged["max_bid_change_pct"] = max(1, min(50, int(merged["max_bid_change_pct"])))
        merged["enabled"] = bool(merged["enabled"])
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "설정 값이 올바르지 않습니다")
    _save_setting(db, client_id, "autopilot", merged)
    return merged


@router.post("/insights/{client_id}/autopilot/simulate")
def simulate_autopilot(client_id: int, db: Session = Depends(get_db),
                       user: models.User = Depends(get_current_user)):
    """오토파일럿이 '실행한다면' 어떤 입찰 조정을 할지 미리보기. 실제 변경 없음."""
    _client_for_read(db, user, client_id)
    cfg = _setting(db, client_id, "autopilot", AUTOPILOT_DEFAULT)
    target = cfg["target_roas"]; cap = cfg["max_bid_change_pct"]
    latest = analytics.latest_per_channel(db, client_id)
    sa = latest.get("naver_searchad")
    actions = []
    if sa:
        for c in sa.get("campaigns", []):
            roas, budget = c.get("roas"), c.get("dailyBudget")
            if roas is None or budget is None:
                continue
            # ROAS가 목표보다 높으면 예산 소폭 증액, 낮으면 감액(상한 cap%)
            delta = cap if roas >= target else -cap
            new_budget = round(budget * (1 + delta / 100))
            actions.append({"campaign": c.get("name"), "roas": roas,
                            "current_daily_budget": budget, "proposed_daily_budget": new_budget,
                            "change_pct": delta,
                            "why": ("목표 초과 — 증액" if delta > 0 else "목표 미달 — 감액")})
    return {"config": cfg, "actions": actions,
            "executed": False,
            "note": "이것은 '시뮬레이션'입니다. 실제 자동 집행은 하지 않습니다 — 안전을 위해 검토 후 "
                    "AI 캠페인 설계의 '실제 적용'으로만 반영하세요."}


# ════════════════════════════════════════════════════════════════════════
# #10 정기 리포트 자동 생성·예약
# ════════════════════════════════════════════════════════════════════════
SCHEDULE_DEFAULT = {"enabled": False, "day_of_month": 1}


@router.get("/insights/{client_id}/report-schedule")
def get_schedule(client_id: int, db: Session = Depends(get_db),
                 user: models.User = Depends(get_current_user)):
    _client_for_read(db, user, client_id)
    cfg = _setting(db, client_id, "report_schedule", SCHEDULE_DEFAULT)
    last = (db.query(models.Report)
            .filter(models.Report.client_id == client_id)
            .order_by(models.Report.created_at.desc()).first())
    cfg["last_report_at"] = (last.created_at.isoformat() + "Z") if last and last.created_at else None
    return cfg


@router.post("/insights/{client_id}/report-schedule")
def set_schedule(client_id: int, cfg: dict = Body(...), db: Session = Depends(get_db),
                 user: models.User = Depends(get_current_user)):
    c = _client_for_read(db, user, client_id)
    if not can_edit(user, c):
        raise HTTPException(403, "권한이 없습니다")
    merged = dict(SCHEDULE_DEFAULT)
    merged["enabled"] = bool(cfg.get("enabled"))
    try:
        merged["day_of_month"] = max(1, min(28, int(cfg.get("day_of_month", 1))))
    except Exception:  # noqa: BLE001
        merged["day_of_month"] = 1
    _save_setting(db, client_id, "report_schedule", merged)
    return merged


def run_due_reports() -> dict:
    """예약된 정기 리포트 자동 생성 — 매일 수집 후 collector가 호출.

    오늘이 예약일이고 이번 달 자동 리포트가 아직 없으면, 지난달 기준 리포트를 생성.
    실패해도 전체를 막지 않음(방어적). 발송 채널은 추후 — 생성·보관까지 수행.
    """
    from ..database import SessionLocal
    db = SessionLocal()
    made, skipped, failed = [], 0, 0
    try:
        today = datetime.now(KST)
        rows = (db.query(models.ClientSetting)
                .filter(models.ClientSetting.key == "report_schedule").all())
        for row in rows:
            try:
                cfg = json.loads(row.value_json or "{}")
            except Exception:  # noqa: BLE001
                continue
            if not cfg.get("enabled") or int(cfg.get("day_of_month", 1)) != today.day:
                skipped += 1
                continue
            cid = row.client_id
            client = db.get(models.Client, cid)
            if not client or client.status == "archived":
                continue
            # 이번 달 이미 자동 생성됐으면 skip
            month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            exists = (db.query(models.Report)
                      .filter(models.Report.client_id == cid,
                              models.Report.created_at >= month_start.replace(tzinfo=None)).first())
            if exists:
                skipped += 1
                continue
            # 지난달 기간
            last_end = today.replace(day=1) - timedelta(days=1)
            df = last_end.replace(day=1).date().isoformat()
            dt = last_end.date().isoformat()
            try:
                from .clients import _gather_perf
                from .. import report_ai
                perf = _gather_perf(db, cid, df, dt)
                if not perf:
                    continue
                ai = report_ai.generate(client.name, client.category, df, dt, perf)
                db.add(models.Report(client_id=cid, date_from=df, date_to=dt,
                                     data_json=json.dumps(perf, ensure_ascii=False),
                                     report_json=json.dumps(ai, ensure_ascii=False)))
                db.commit()
                made.append(cid)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                failed += 1
                print(f"[report-schedule] client {cid} 생성 실패: {str(e)[:200]}")
    finally:
        db.close()
    if made or failed:
        print(f"[report-schedule] 자동 리포트 생성 {len(made)}건 / 실패 {failed}건")
    return {"made": made, "skipped": skipped, "failed": failed}
