"""저장 자료만 읽는 SEO 근거. 앱 초기화·네트워크·수집 큐 쓰기를 하지 않는다."""
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import html
import json
import math
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit, urlunsplit

_KST = timezone(timedelta(hours=9))


class ReadError(RuntimeError):
    """명시 연결 상품 자료를 읽지 못했다. 정상 빈 목록과 구분한다."""


def _text(value):
    return value.strip() if isinstance(value, str) else None


def _id(value):
    if type(value) not in (str, int):
        return None
    value = str(value).strip()
    return value if re.fullmatch(r"[1-9][0-9]*", value) else None


def _naver_product(value):
    """호스트·스토어·상품번호를 분리한다. 번호 부분일치나 가게명은 쓰지 않는다."""
    if not isinstance(value, str) or any(ord(ch) < 32 for ch in value):
        return None
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").lower()
    except (ValueError, OverflowError):
        return None
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host:
        return None
    if host in {"smartstore.naver.com", "m.smartstore.naver.com", "brand.naver.com", "m.brand.naver.com"}:
        match = re.fullmatch(r"/([^/%\\]+)/products/([1-9][0-9]*)/?", parsed.path)
        if match:
            host = host.removeprefix("m.")
            return (f"naver:{host}:{match[1]}:{match[2]}", f"https://{host}/{match[1]}/products/{match[2]}")
        return None
    if host not in {"search.shopping.naver.com", "msearch.shopping.naver.com", "shopping.naver.com", "m.shopping.naver.com"}:
        return None
    catalog = re.fullmatch(r"/catalog/([1-9][0-9]*)/?", parsed.path)
    if not catalog and parsed.path not in {"/catalog", "/catalog/", "/catalog.nhn", "/detail/detail.nhn", "/outlink/itemdetail.nhn"}:
        return None
    mids = parse_qs(parsed.query, keep_blank_values=True).get("nvMid", [])
    mid = _id(mids[0]) if len(mids) == 1 else (catalog[1] if catalog and not mids else None)
    if not mid or (catalog and catalog[1] != mid):
        return None
    return ("naver:nvMid:" + mid, "https://search.shopping.naver.com/catalog/" + mid)


def _url(value):
    canonical = _naver_product(value)
    if canonical:
        return canonical[1]
    if not isinstance(value, str) or any(ord(ch) < 32 for ch in value):
        return None
    try:
        parsed = urlsplit(value.strip())
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            return None
        return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, ""))
    except ValueError:
        return None


def _json_object(value):
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _read_object(value):
    parsed = json.loads(value or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("저장 자료가 객체가 아닙니다.")
    return parsed


def _price(value):
    if type(value) in (str, int):
        return value
    return value if type(value) is float and math.isfinite(value) else None


def _datetime(value):
    if not isinstance(value, str) or len(value) <= 10:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=_KST) if parsed.tzinfo is None else parsed.astimezone(_KST)
    except (ValueError, OverflowError):
        return None


def _category(product):
    direct = _text(product.get("category"))
    return direct or " > ".join(p for p in (_text(product.get("category" + str(i))) for i in range(1, 5)) if p) or None


def _observation(row):
    meta = _json_object(row.get("meta_json"))
    observation = meta.get("observation")
    observation = observation if isinstance(observation, dict) else {}
    raw = observation.get("actualFinishedAt") or meta.get("actualFinishedAt") or observation.get("finishedAt")
    return meta, observation, _datetime(raw)


def _clock(now):
    if isinstance(now, datetime):
        return now.replace(tzinfo=_KST) if now.tzinfo is None else now.astimezone(_KST)
    if isinstance(now, date):
        return datetime.combine(now, datetime.max.time(), tzinfo=_KST)
    return _datetime(now) or datetime.now(_KST)


def _search_surface(value):
    url = _url(value)
    if not url:
        return None
    parsed = urlsplit(url)
    if (parsed.netloc not in {"search.shopping.naver.com", "msearch.shopping.naver.com"}
            or not parsed.path.startswith("/search/")):
        return None
    return url


def _connect(db_path):
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _empty(status="no_data"):
    return {"status": status, "label": "자료 읽기 실패" if status == "read_error" else "자료 없음",
            "coverage": 0, "collected_date": None, "observed_at": None, "surface": None,
            "ads_verified": False, "verified_top20": False, "products": [], "common_terms": [],
            "notes": ["저장 자료만 사용하며 추가 수집을 요청하지 않습니다. 실시간 현재 순위는 확인하지 않았습니다."]}


def collect_evidence(db_path, keyword, now=None):
    """최신 저장 관측의 상품·문서 빈도와 한계를 반환한다.

    coverage는 사용한 고유 상품 수(0~20)이다. 상태는 no_data/read_error,
    stale(2일 전부터), unverified, partial이며, collected_date는
    회차 날짜가 아닌 확인 가능한 관측일(없으면 저장일)이다.
    현 저장 스키마에는 상품별 그룹/카탈로그 구분·처리 근거가 없으므로
    원출처·광고 제외·연속 순위를 확인해도 verified_top20는 참으로 올리지 않는다.
    """
    try:
        with closing(_connect(db_path)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(collected_serp)")}
            fields = ["products_json", "collected_date"] + [c for c in ("created_at", "meta_json", "source") if c in cols]
            rows = [dict(r) for r in conn.execute("SELECT " + ",".join(fields) + " FROM collected_serp WHERE keyword=?", (keyword,))]
        if not rows:
            return _empty()
        clock = _clock(now)
        def latest_key(candidate):
            observed = _observation(candidate)[2]
            collected = _datetime(str(candidate.get("collected_date") or "") + "T00:00:00")
            if collected and collected.date() > clock.date():
                collected = None
            return (observed if observed and observed <= clock + timedelta(minutes=5)
                    else _datetime(candidate.get("created_at")) or collected) or datetime.min.replace(tzinfo=_KST)
        row = max(rows, key=latest_key)
        raw_products = json.loads(row["products_json"])
        if not isinstance(raw_products, list):
            return _empty("read_error")
        products, seen_ids, seen_urls, seen_ranks = [], set(), set(), set()
        raw_ranks = Counter(int(_id(p.get("rank")) or 0) for p in raw_products if isinstance(p, dict))
        def explicit_ad(product):
            return any(product.get(k) not in (None, False, 0, "", "false", "0") for k in ("isAd", "is_ad", "ad", "adId"))
        ads_present = any(explicit_ad(p) for p in raw_products if isinstance(p, dict))
        for item in sorted((p for p in raw_products if isinstance(p, dict)), key=lambda p: int(_id(p.get("rank")) or 999999)):
            rank = int(_id(item.get("rank")) or 0)
            if not 1 <= rank <= 20 or rank in seen_ranks or explicit_ad(item):
                continue
            ids = {_id(item.get(k)) for k in ("nvMid", "productId", "product_id")}
            ids.discard(None)
            url = _url(item.get("link") or item.get("product_url") or item.get("url"))
            title = _text(item.get("title") or item.get("product_name"))
            if not title or (not ids and not url) or ids & seen_ids or (url and url in seen_urls):
                continue
            products.append({"rank": rank, "product_id": _id(item.get("nvMid")) or _id(item.get("productId")) or _id(item.get("product_id")),
                             "title": title, "url": url, "mall_name": _text(item.get("mallName") or item.get("mall_name")),
                             "brand": _text(item.get("brand")), "category": _category(item), "price": _price(item.get("price"))})
            seen_ids.update(ids)
            if url:
                seen_urls.add(url)
            seen_ranks.add(rank)
        result = _empty("unverified")
        meta, obs, observed = _observation(row)
        valid_time = bool(observed and observed <= clock + timedelta(minutes=5))
        stored_at = _datetime(row.get("created_at"))
        actual_date = observed.date() if valid_time else (stored_at.date() if stored_at else None)
        if actual_date is None:
            try:
                day = date.fromisoformat(row["collected_date"])
                actual_date = day if day <= clock.date() else None
            except (ValueError, TypeError):
                pass
        result.update(label="출처 미확인", coverage=len(products),
                      collected_date=actual_date.isoformat() if actual_date else None, products=products,
                      observed_at=observed.isoformat() if valid_time else None)
        if products:
            result["notes"].append("현 저장 스키마에는 상품별 그룹/카탈로그 구분과 처리 근거가 없어 상위 20개 검증을 완료할 수 없습니다.")
        if row["collected_date"] != result["collected_date"]:
            result["notes"].append("회차 날짜는 실제 관측일과 다를 수 있어 관측/저장 날짜를 사용했습니다.")
        pages = obs.get("pageEvidence")
        pages_ok = (isinstance(pages, list) and bool(pages) and type(obs.get("pagesRead")) is int
                    and len(pages) == obs["pagesRead"])
        surfaces = []
        for i, page in enumerate(pages if isinstance(pages, list) else [], 1):
            if not isinstance(page, dict):
                pages_ok = False
                continue
            surface = _search_surface(page.get("href"))
            if surface:
                surfaces.append(surface)
            # 기존 확장은 원출처가 없을 때 nextdata로 대체한다. 그 값만으로 검증하지 않는다.
            pages_ok = bool(pages_ok and type(page.get("page")) is int and page["page"] == i and page.get("keyword") == keyword
                            and page.get("verified") is True and surface
                            and isinstance(page.get("originalSource"), str)
                            and page["originalSource"] in {"tap", "router", "nextdata"}
                            and page.get("source") == page.get("originalSource"))
        result["surface"] = surfaces[0] if surfaces else None
        organic_count = obs.get("organicCount")
        ads_ok = (isinstance(meta.get("rankPolicy"), str) and meta["rankPolicy"].startswith("organic-v3(")
                  and type(meta.get("adSkipped")) is int and meta["adSkipped"] >= 0
                  and type(meta.get("adHintMissed")) is int and meta["adHintMissed"] == 0
                  and type(meta.get("rawCount")) is int and type(organic_count) is int
                  and meta["rawCount"] >= organic_count + meta["adSkipped"])
        ads_ok = ads_ok and not ads_present
        continuous = ([p["rank"] for p in products] == list(range(1, len(products) + 1))
                      and all(raw_ranks[p["rank"]] == 1 for p in products)
                      and type(obs.get("coveredThroughRank")) is int
                      and obs["coveredThroughRank"] >= len(products) and organic_count == len(raw_products))
        source_ok = bool(pages_ok and valid_time and obs.get("keyword") == keyword and isinstance(obs.get("status"), str)
                         and obs.get("status") in {"complete", "target_complete", "partial"})
        result["ads_verified"] = bool(ads_ok and source_ok)
        stale = actual_date is not None and (clock.date() - actual_date).days >= 2
        if stale:
            result.update(status="stale", label="오래된 자료")
        elif not (source_ok and ads_ok and continuous):
            result["notes"].append("원출처·관측 시각·광고 제외·연속 순위를 모두 확인하지 못했습니다.")
        elif len(products) < 20:
            result.update(status="partial", label=f"부분 자료 {len(products)}/20")
        else:
            # 단순 검증 플래그나 ID/URL만으로 그룹상품과 카탈로그 처리 사실을 증명할 수 없다.
            result.update(status="unverified", label="상품명 자료 20/20 · 그룹/카탈로그 미확인")
        counts = Counter(term for p in products for term in set(re.findall(r"[가-힣A-Za-z0-9]+", html.unescape(re.sub(r"<[^>]*>", " ", p["title"])).lower())))
        result["common_terms"] = [{"term": term, "count": count, "total": len(products), "percent": round(count * 100 / len(products), 1)}
                                  for term, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
        if not products:
            result.update(status="no_data", label="자료 없음")
        return result
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return _empty("read_error")


def client_products(db_path, client_id):
    """명시 연결 상품과 자체 식별이 맞는 최신 저장 사실만 반환한다.

    권한 검사는 호출부의 책임이다. 다른 업체 자료·판매처 이름 폴백은 쓰지 않으며
    모르는 현재값은 None이다. 업체/명시 상품 부재는 빈 목록이며 읽기 실패는 ReadError이다.
    """
    if not _id(client_id):
        return []
    try:
        with closing(_connect(db_path)) as conn:
            ccols = {r[1] for r in conn.execute("PRAGMA table_info(clients)")}
            cfields = ["id"] + [c for c in ("naver_store_url", "main_keywords") if c in ccols]
            row = conn.execute("SELECT " + ",".join(cfields) + " FROM clients WHERE id=?", (client_id,)).fetchone()
            if not row:
                return []
            client = dict(row)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            links = [dict(r) for r in conn.execute("SELECT keyword,product_url FROM client_keyword_product WHERE client_id=? ORDER BY id", (client_id,))] if "client_keyword_product" in tables else []
            if _naver_product(client.get("naver_store_url")):
                links.append({"product_url": client["naver_store_url"], "keyword": (client.get("main_keywords") or "").split(",")[0].strip()})
            if {"rank_link", "tracked_products"} <= tables:
                first_keyword = ("(SELECT k.keyword FROM tracked_keywords k WHERE k.product_id=p.id ORDER BY k.id LIMIT 1)"
                                 if "tracked_keywords" in tables else "NULL")
                # 판매처명(store_slug) 자동 연결은 상품 동일성을 증명하지 않으므로 제외한다.
                links.extend(dict(r) for r in conn.execute(
                    "SELECT p.product_url," + first_keyword + " AS keyword FROM rank_link l "
                    "JOIN tracked_products p ON p.id=l.tracked_product_id "
                    "WHERE l.client_id=? AND l.match_method IN ('manual','product_id') ORDER BY l.id", (client_id,)))
            analyses = []
            if "client_analyses" in tables:
                acols = {r[1] for r in conn.execute("PRAGMA table_info(client_analyses)")}
                afields = [c for c in ("id", "product_url", "advertiser_json", "analysis_json", "updated_at", "analyzed_date", "created_at") if c in acols]
                analyses = [dict(r) for r in conn.execute("SELECT " + ",".join(afields) + " FROM client_analyses WHERE client_id=?", (client_id,))]
        analyses.sort(key=lambda a: (a.get("updated_at") or a.get("analyzed_date") or a.get("created_at") or "", a.get("id", 0)), reverse=True)
        products, seen = [], set()
        for link in links:
            canonical = _naver_product(link.get("product_url"))
            if not canonical or canonical[0] in seen:
                continue
            key, url = canonical
            seen.add(key)
            analysis = next((a for a in analyses if (_naver_product(a.get("product_url")) or (None,))[0] == key), {})
            advertiser = _read_object(analysis.get("advertiser_json"))
            computed = _read_object(analysis.get("analysis_json"))
            info = {}
            for candidate in (advertiser.get("product_info"), computed.get("product_info"), computed.get("targetProductInfo")):
                if not isinstance(candidate, dict):
                    continue
                identity = _naver_product(candidate.get("product_url") or candidate.get("url") or candidate.get("link"))
                explicit_id = _id(candidate.get("product_id") or candidate.get("productId"))
                if ((identity and identity[0] == key)
                        or (not identity and not any(candidate.get(k) for k in ("product_url", "url", "link"))
                            and explicit_id and key.startswith("naver:smartstore.naver.com:") and explicit_id == key.rsplit(":", 1)[-1])):
                    info = candidate
                    break
            name = _text(info.get("product_name") or info.get("title"))
            features = _text(info.get("features"))
            seo = info.get("seoInfo")
            seo = seo if isinstance(seo, dict) else {}
            tags = info.get("tags")
            if tags is None and isinstance(seo.get("sellerTags"), list):
                tags = [tag.get("text") if isinstance(tag, dict) else None for tag in seo["sellerTags"]]
            tags = tags if isinstance(tags, list) and all(isinstance(t, str) and t.strip() for t in tags) else None
            products.append({"product_key": key, "product_url": url, "keyword": _text(link.get("keyword")) or "",
                             "product_name": name, "brand": _text(info.get("brand")), "category": _category(info), "features": features,
                             "current_values": {"product_name": name, "tags": tags,
                                                "page_title": _text(info.get("page_title") or seo.get("pageTitle")),
                                                "meta_description": _text(info.get("meta_description") or seo.get("metaDescription"))}})
        return products
    except (sqlite3.Error, OSError, ValueError, TypeError) as error:
        raise ReadError("저장된 연결 상품 자료를 읽지 못했습니다.") from error
