"""네이버 검색광고 API 어댑터 — HMAC 서명 인증 + 캠페인·성과 조회.

인증(공식): 헤더 4종 X-Timestamp(ms)/X-API-KEY(액세스라이선스)/X-Customer(CUSTOMER_ID)/
X-Signature(= base64(HMAC-SHA256("ts.method.uri", secret_key))). secret_key는 문자열 그대로 HMAC 키.
"""
import time
import hmac
import hashlib
import base64
import json as jsonlib
from datetime import date, timedelta

import requests

BASE = "https://api.searchad.naver.com"
TIMEOUT = 20

# 성과 지표: 노출·클릭·광고비·전환수·전환매출
PERF_FIELDS = ["impCnt", "clkCnt", "salesAmt", "ccnt", "convAmt"]


def _signature(timestamp: str, method: str, uri: str, secret_key: str) -> str:
    msg = f"{timestamp}.{method}.{uri}"
    digest = hmac.new(secret_key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _headers(api_key: str, secret_key: str, customer_id: str, method: str, uri: str) -> dict:
    ts = str(int(time.time() * 1000))
    return {
        "X-Timestamp": ts,
        "X-API-KEY": api_key,
        "X-Customer": str(customer_id),
        "X-Signature": _signature(ts, method, uri, secret_key),
        "Accept": "application/json",
    }


def get_campaigns(api_key: str, secret_key: str, customer_id: str) -> list:
    uri = "/ncc/campaigns"
    r = requests.get(BASE + uri, headers=_headers(api_key, secret_key, customer_id, "GET", uri), timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"캠페인 조회 실패 ({r.status_code}): {r.text[:400]}")
    return r.json() if r.text else []


def get_stats(api_key: str, secret_key: str, customer_id: str, ids: list, days: int = 7,
              date_from: str = None, date_to: str = None) -> dict:
    uri = "/stats"
    if date_from and date_to:
        since, until = date.fromisoformat(date_from), date.fromisoformat(date_to)
    else:
        until = date.today()
        since = until - timedelta(days=days)
    params = {
        "ids": ids,
        "fields": jsonlib.dumps(PERF_FIELDS),
        "timeRange": jsonlib.dumps({"since": since.isoformat(), "until": until.isoformat()}),
    }
    r = requests.get(
        BASE + uri,
        headers=_headers(api_key, secret_key, customer_id, "GET", uri),
        params=params,
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"통계 조회 실패 ({r.status_code}): {r.text[:400]}")
    return r.json() if r.text else {}


def fetch_summary(api_key: str, secret_key: str, customer_id: str) -> dict:
    """연결 테스트(가벼움) — 캠페인 목록만."""
    camps = get_campaigns(api_key, secret_key, customer_id)
    return {
        "authenticated": True,
        "campaign_count": len(camps),
        "campaigns": [
            {"name": c.get("name"), "type": c.get("campaignTp"), "status": c.get("status"), "dailyBudget": c.get("dailyBudget")}
            for c in camps[:10]
        ],
    }


def _derive(t: dict) -> dict:
    """성과 합계에서 파생 지표(CTR·CPC·ROAS) 계산."""
    return {
        "ctr": round(t["clkCnt"] / t["impCnt"] * 100, 2) if t.get("impCnt") else 0,
        "cpc": round(t["salesAmt"] / t["clkCnt"]) if t.get("clkCnt") else 0,
        "roas": round(t["convAmt"] / t["salesAmt"] * 100, 1) if t.get("salesAmt") else None,
    }


# ────────────────────────────────────────────────────────────────────────
# 쓰기(캠페인 생성) — AI 캠페인 제안의 '실제 적용'에서만 사용.
# 안전원칙: ① 미리보기(build_plan)는 호출 0, ② 실행(apply_plan live=True)도
#           모든 캠페인·그룹을 '일시중지(userLock=True)'로 생성 → 콘솔에서 직접 켜기 전엔 미집행.
# ────────────────────────────────────────────────────────────────────────

def _post(api_key: str, secret_key: str, customer_id: str, uri: str, body: dict) -> dict:
    h = _headers(api_key, secret_key, customer_id, "POST", uri)
    h["Content-Type"] = "application/json"
    r = requests.post(BASE + uri, headers=h, data=jsonlib.dumps(body), timeout=TIMEOUT)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"{uri} 생성 실패 ({r.status_code}): {r.text[:400]}")
    return r.json() if r.text else {}


def get_channels(api_key: str, secret_key: str, customer_id: str) -> list:
    """비즈채널(등록된 사이트) 목록 — 광고그룹 생성에 필요(pc/mobile 채널 ID)."""
    uri = "/ncc/channels"
    r = requests.get(BASE + uri, headers=_headers(api_key, secret_key, customer_id, "GET", uri), timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"비즈채널 조회 실패 ({r.status_code}): {r.text[:400]}")
    return r.json() if r.text else []


def build_plan(proposal: dict, customer_id: str, monthly_budget: int = 0) -> dict:
    """제안 JSON → 검색광고 API 호출 '계획'(미리보기·실행 공용). 실제 호출은 하지 않는다.

    반환: {ok, daily_budget, monthly_cap, over_budget, steps[], counts{}, note}
    """
    ns = proposal.get("naver_searchad") or {}
    daily = int(ns.get("daily_budget") or 0)
    cap = int(monthly_budget or 0)
    monthly_est = daily * 30
    over = bool(cap and monthly_est > cap)

    steps = [{
        "step": "캠페인 생성", "method": "POST", "uri": "/ncc/campaigns",
        "body": {
            "customerId": str(customer_id),
            "name": ns.get("campaign_name") or "AI 캠페인",
            "campaignTp": "WEB_SITE",
            "dailyBudget": daily,
            "userLock": True,  # ★일시중지로 생성
        },
    }]
    g_cnt = k_cnt = 0
    for g in (ns.get("ad_groups") or []):
        g_cnt += 1
        kws = g.get("keywords") or []
        k_cnt += len(kws)
        steps.append({
            "step": f"광고그룹 생성 — {g.get('name')}", "method": "POST", "uri": "/ncc/adgroups",
            "body": {
                "name": g.get("name"), "bidAmt": int(g.get("bid") or 0), "userLock": True,
                "keywords": [{"keyword": k.get("text"), "bidAmt": int(k.get("bid") or 0)} for k in kws],
            },
        })
    return {
        "ok": not over,
        "daily_budget": daily,
        "monthly_estimate": monthly_est,
        "monthly_cap": cap,
        "over_budget": over,
        "counts": {"campaigns": 1, "ad_groups": g_cnt, "keywords": k_cnt},
        "steps": steps,
        "note": "이 계획대로 생성되며, 모든 캠페인·그룹은 '일시중지' 상태로 만들어집니다. "
                "실제 노출(과금)은 네이버 검색광고 콘솔에서 직접 켜야 시작됩니다.",
    }


def apply_plan(api_key: str, secret_key: str, customer_id: str, proposal: dict,
               live: bool = False, monthly_budget: int = 0) -> dict:
    """캠페인안 적용. live=False(기본)=미리보기만. live=True=실제 생성(모두 일시중지).

    예산 한도(monthly_budget)를 넘으면 실행을 거부한다(가드레일).
    """
    plan = build_plan(proposal, customer_id, monthly_budget)
    if not live:
        plan["dry_run"] = True
        return plan
    if plan["over_budget"]:
        raise RuntimeError(
            f"일 예산({plan['daily_budget']:,}원)의 월 환산({plan['monthly_estimate']:,}원)이 "
            f"한도({plan['monthly_cap']:,}원)를 초과해 적용을 막았습니다."
        )

    ns = proposal.get("naver_searchad") or {}
    result = {"dry_run": False, "created": {"campaign": None, "ad_groups": [], "keywords": 0}, "errors": []}

    # 1) 캠페인 생성(일시중지)
    camp = _post(api_key, secret_key, customer_id, "/ncc/campaigns", {
        "customerId": str(customer_id),
        "name": ns.get("campaign_name") or "AI 캠페인",
        "campaignTp": "WEB_SITE",
        "dailyBudget": int(ns.get("daily_budget") or 0),
        "userLock": True,
    })
    camp_id = camp.get("nccCampaignId")
    result["created"]["campaign"] = {"id": camp_id, "name": camp.get("name")}

    # 2) 비즈채널 확보(광고그룹 필수). 없으면 그룹 생성은 건너뛰고 안내.
    pc_ch = mo_ch = None
    try:
        for ch in get_channels(api_key, secret_key, customer_id):
            t = ch.get("channelTp") or ch.get("businessChannelTp")
            if t == "SITE" and not pc_ch:
                pc_ch = ch.get("nccBusinessChannelId") or ch.get("businessChannelId")
        mo_ch = pc_ch
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"비즈채널 조회 실패: {str(e)[:200]}")

    if not pc_ch:
        result["errors"].append("등록된 비즈채널(사이트)이 없어 광고그룹은 생성하지 못했습니다. "
                                 "검색광고 콘솔에서 비즈채널 등록 후 다시 적용하세요.")
        return result

    # 3) 광고그룹 + 키워드 생성(일시중지)
    for g in (ns.get("ad_groups") or []):
        try:
            ag = _post(api_key, secret_key, customer_id, "/ncc/adgroups", {
                "nccCampaignId": camp_id,
                "name": g.get("name"),
                "pcChannelId": pc_ch,
                "mobileChannelId": mo_ch,
                "bidAmt": int(g.get("bid") or 0),
                "userLock": True,
            })
            ag_id = ag.get("nccAdgroupId")
            result["created"]["ad_groups"].append({"id": ag_id, "name": ag.get("name")})
            kws = g.get("keywords") or []
            if kws and ag_id:
                _post(api_key, secret_key, customer_id, "/ncc/keywords", [
                    {"nccAdgroupId": ag_id, "keyword": k.get("text"), "bidAmt": int(k.get("bid") or 0)}
                    for k in kws
                ])
                result["created"]["keywords"] += len(kws)
        except Exception as e:  # noqa: BLE001 — 한 그룹 실패가 전체를 막지 않게
            result["errors"].append(f"광고그룹 '{g.get('name')}' 생성 실패: {str(e)[:200]}")

    result["note"] = ("생성 완료 — 모든 항목이 '일시중지' 상태입니다. "
                      "네이버 검색광고 콘솔에서 검토 후 직접 켜면 노출이 시작됩니다.")
    return result


def fetch_performance(api_key: str, secret_key: str, customer_id: str, days: int = 7,
                      date_from: str = None, date_to: str = None) -> dict:
    """캠페인 + 기간 성과 — 전체 합계와 캠페인별 행. 기간은 days 또는 date_from/to(YYYY-MM-DD)."""
    camps = get_campaigns(api_key, secret_key, customer_id)
    ids = [c.get("nccCampaignId") for c in camps if c.get("nccCampaignId")]
    out = {"authenticated": True, "campaign_count": len(camps), "days": days}
    if date_from and date_to:
        out["date_from"], out["date_to"] = date_from, date_to
    by_id = {}
    if ids:
        stats = get_stats(api_key, secret_key, customer_id, ids, days, date_from, date_to)
        rows = stats.get("data", []) if isinstance(stats, dict) else (stats or [])
        for row in rows:
            rid = row.get("id")
            if rid:
                by_id[rid] = row

    tot = {k: 0 for k in PERF_FIELDS}
    campaigns = []
    for c in camps:
        cid = c.get("nccCampaignId")
        s = by_id.get(cid, {})
        perf = {k: (s.get(k, 0) or 0) for k in PERF_FIELDS}
        for k in PERF_FIELDS:
            tot[k] += perf[k]
        campaigns.append({
            "name": c.get("name"),
            "status": c.get("status"),
            "dailyBudget": c.get("dailyBudget"),
            **perf,
            **_derive(perf),
        })
    out["campaigns"] = campaigns
    out["totals"] = tot
    out.update(_derive(tot))
    return out
