"""수집 대상 카탈로그(읽기 전용) — 코덱스 1.22.0 `collector_catalog` 이식판 (4차 · 2026-09-22)

무엇을 답하나: 「오늘 재야 할 대상(상품 키워드 · 업체 대표 키워드)마다 **정확 식별자(nvMid)가 있는가**」.
  · product 출처 = 추적 상품(활성·자격 통과) × 그 키워드 — 등록 nvMid 가 있으면 targetId, 없으면 issue=MISSING_PRODUCT_ID
  · client 출처 = 자격 업체의 대표 키워드(억제 제외) — 스토어 주소가 카탈로그(nvMid) 주소면 그 값, 아니면 **연결된 추적 상품**
    중 같은 정확 주소의 nvMid(둘 이상이면 AMBIGUOUS_PRODUCT_ID)
운영 화면 「가동 전 점검」의 **상품 연결 확인 필요(unresolved)** 수가 여기서 나온다. 순위를 적거나 요청을 만들지 않는다.
⚠️ 원안과 다른 점 — 표가 없거나(옛 DB) 자격 판정이 실패하면 예외 대신 **None(못 쟀다)** 를 돌려준다(fail-closed 는 화면이 「미확인」으로 그린다).
⚠️ stdlib 만.
"""
import json
from collections import defaultdict
from typing import Any, Dict, List, Optional
from uuid import NAMESPACE_URL, uuid5

from collector_coord import normalize_keyword
from product_identity import canonical_product_id, naver_product_identity
from tracking_eligibility import eligible_clients_sql, eligible_tracked_product_ids


def _rows(conn, sql, args=()):
    cur = conn.execute(sql, args)
    names = [c[0] for c in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _has_table(conn, name: str) -> bool:
    try:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None
    except Exception:
        return False


def _mid(value):
    v = canonical_product_id(value)
    return v if v and len(v) <= 100 else None


def _norm(kw: str) -> str:
    try:
        return normalize_keyword(kw)
    except ValueError:
        return (kw or "").strip()


def _row(source, source_id, keyword, **values):
    raw = keyword.strip()
    name = json.dumps([source, source_id, raw], ensure_ascii=False, separators=(",", ":"))
    base = {"source": source, "rowKey": str(uuid5(NAMESPACE_URL, "collector-source:" + name)),
            "keyword": _norm(raw), "sourceKeyword": raw, "keywordId": None, "productId": None, "clientId": None,
            "clientName": "", "productUrl": "", "productName": "", "targetId": None, "identitySource": None,
            "issue": "MISSING_PRODUCT_ID"}
    base.update(values)
    return base


def _client_identity(url, linked_products):
    identity = naver_product_identity(url)
    if not identity:
        return None, None, "MISSING_PRODUCT_ID"
    if identity[0] == "nvMid":
        mid = _mid(identity[1])
        return mid, ("catalog_url" if mid else None), (None if mid else "MISSING_PRODUCT_ID")
    mids = {_mid(p.get("nv_mid")) for p in linked_products if naver_product_identity(p.get("product_url")) == identity}
    mids.discard(None)
    if len(mids) > 1:
        return None, None, "AMBIGUOUS_PRODUCT_ID"
    if mids:
        return next(iter(mids)), "linked_exact_product", None
    return None, None, "MISSING_PRODUCT_ID"


def catalog_sources(conn, day: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """대상 목록. 못 재면 None."""
    try:
        eligible = eligible_tracked_product_ids(conn, ensure_schema=False, day=day)
        if eligible is None:
            return None
        pcols = {r[1] for r in conn.execute("PRAGMA table_info(tracked_products)")}
        label = "product_name" if "product_name" in pcols else "'' AS product_name"
        nv = "nv_mid" if "nv_mid" in pcols else "'' AS nv_mid"
        products = {p["id"]: p for p in _rows(conn, f"SELECT id, product_url, {nv}, {label} FROM tracked_products ORDER BY id")
                    if p["id"] in eligible}
        keywords = _rows(conn, "SELECT id, product_id, keyword FROM tracked_keywords ORDER BY id")
        clients = _rows(conn, eligible_clients_sql("id, name, main_keywords, naver_store_url", day=day) + " ORDER BY id")
        links = _rows(conn, "SELECT client_id, tracked_product_id FROM rank_link") if _has_table(conn, "rank_link") else []
        mutes = _rows(conn, "SELECT client_id, keyword FROM client_keyword_mute") if _has_table(conn, "client_keyword_mute") else []
        maps = _rows(conn, "SELECT client_id, keyword, product_url FROM client_keyword_product") if _has_table(conn, "client_keyword_product") else []
    except Exception:
        return None
    muted = defaultdict(set)
    for m in mutes:
        if (m["keyword"] or "").strip():
            muted[m["client_id"]].add(_norm(m["keyword"]))
    mappings = defaultdict(dict)
    for m in maps:
        kw, url = (m["keyword"] or "").strip(), (m["product_url"] or "").strip()
        if kw and url:
            mappings[m["client_id"]][_norm(kw)] = url
    result: List[Dict[str, Any]] = []
    product_keywords = defaultdict(list)
    for k in keywords:
        p = products.get(k["product_id"]); raw = (k["keyword"] or "").strip()
        if not p or not raw:
            continue
        product_keywords[p["id"]].append(raw)
        mid = _mid(p.get("nv_mid"))
        result.append(_row("product", k["id"], raw, keywordId=k["id"], productId=p["id"],
                           productUrl=(p.get("product_url") or "").strip(), productName=p.get("product_name") or "",
                           targetId=mid, identitySource=("registered_nvmid" if mid else None),
                           issue=(None if mid else "MISSING_PRODUCT_ID")))
    linked = defaultdict(set)
    for l in links:
        if l["tracked_product_id"] in products:
            linked[l["client_id"]].add(l["tracked_product_id"])
    for c in clients:
        cid = c["id"]
        cps = [products[pid] for pid in sorted(linked[cid])]
        kws = {x.strip() for x in (c.get("main_keywords") or "").split(",") if x.strip()}
        for raw in sorted(kws):
            if _norm(raw) in muted[cid]:
                continue
            url = mappings[cid].get(_norm(raw)) or (c.get("naver_store_url") or "").strip()
            mid, src, issue = _client_identity(url, cps)
            result.append(_row("client", cid, raw, clientId=cid, clientName=c.get("name") or "", productUrl=url,
                               targetId=mid, identitySource=src, issue=issue))
    return result


def unresolved_count(conn, day: Optional[str] = None) -> Optional[int]:
    rows = catalog_sources(conn, day)
    if rows is None:
        return None
    return sum(1 for r in rows if r["issue"] or not r["targetId"])
