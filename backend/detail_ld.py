"""상세 HTML 의 **검색엔진용 상품 정보(JSON-LD Product)** 에서 판매가·카테고리·상품 번호를 읽는다.
(대표 결정 A · 2026-09-23 · 전수조사 ②·③)

## 왜 여기서 읽나 — 종전 자리는 비어 있었다

`analyze_detail_page` 는 판매가·카테고리를 `__NEXT_DATA__` 에서 읽었다. 저장된 상세 HTML 751건을
서버에서 재 보니(2026-09-23 · 읽기 전용 진단 4~6차):
  · `__NEXT_DATA__` 는 **0건** — 스마트스토어가 그 자리를 더 쓰지 않는다.
  · `__PRELOADED_STATE__` 는 751건 모두 있지만 **본 상품 칸(product)이 비어 있다** — salePrice 0 · id 없음
    (본 상품 값은 화면이 뜬 뒤 따로 받아 온다). ⚠️ 첫 보고의 「PRELOADED 에 판매가가 들어 있다」는 틀렸다.
  · 대신 **JSON-LD Product 가 746건**에 있고, 판매가(offers.price)·카테고리(category)·
    상품 번호(productID)가 거기 들어 있다.
  · og:url·canonical 은 **0건** — 붙여넣는 HTML 이 머리글을 안 담는다. 그래서 상품 주소도 여기서 만든다.

## 무회귀
  · 종전 자리(`__NEXT_DATA__` · api-price 메타)가 값을 주면 그것이 먼저다 — 여기는 **비었을 때만** 채운다.
  · 판매가는 100원~1억 원 밖이면 버린다(종전 이상탐지와 같은 선).
  · 어떤 입력에도 예외를 밖으로 내지 않는다.
⚠️ 표준 라이브러리만 — 배포 게이트가 import 한다.
"""

import json
import re

_LD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.DOTALL | re.I)
_PRODUCT_URL_RE = re.compile(r'https?://(?:m\.)?(smartstore|brand)\.naver\.com/([A-Za-z0-9_-]+)/products/(\d+)')
_SLUG_RE = re.compile(r'(?:https?:)?//(?:m\.)?(smartstore|brand)\.naver\.com/([A-Za-z0-9_-]+)')
_NOT_SLUG = {"main", "inflow", "i", "category", "products", "search", "profile", "v2", "api"}

PRICE_MIN, PRICE_MAX = 100, 100_000_000


def product_ld(html: str):
    """첫 번째 JSON-LD Product(dict) — 없거나 깨졌으면 None."""
    if not html or not isinstance(html, str) or "ld+json" not in html:
        return None
    for blk in _LD_RE.findall(html):
        try:
            d = json.loads(blk.strip())
        except Exception:
            continue
        items = d if isinstance(d, list) else [d]
        if isinstance(d, dict) and isinstance(d.get("@graph"), list):
            items = items + d["@graph"]
        for it in items:
            if isinstance(it, dict) and str(it.get("@type") or "") == "Product":
                return it
    return None


def _offer(prod):
    off = prod.get("offers") if isinstance(prod, dict) else None
    if isinstance(off, list):
        off = next((o for o in off if isinstance(o, dict)), None)
    return off if isinstance(off, dict) else {}


def price(prod) -> int:
    """판매가(원). offers.price → offers.lowPrice. 범위 밖·못 읽음이면 0."""
    off = _offer(prod)
    for k in ("price", "lowPrice"):
        v = off.get(k)
        if v is None or v == "":
            continue
        try:
            p = int(round(float(str(v).replace(",", "").strip())))
        except Exception:
            continue
        if PRICE_MIN <= p <= PRICE_MAX:
            return p
    return 0


def category(prod):
    """(전체 카테고리 이름, 대분류) — 이름에 '>' 가 있으면 그대로 · 숫자(코드)만이면 ("", "")."""
    v = prod.get("category") if isinstance(prod, dict) else None
    if isinstance(v, list):
        v = ">".join(str(x).strip() for x in v if str(x).strip())
    if not isinstance(v, str):
        return "", ""
    s = re.sub(r"\s*>\s*", ">", v.strip())
    if not s or re.fullmatch(r"[\d>\s]+", s):
        return "", ""
    return s, s.split(">")[0].strip()


def product_no(prod) -> str:
    """상품 번호(숫자 글자) — productID → sku. 숫자가 아니면 ""."""
    if not isinstance(prod, dict):
        return ""
    for k in ("productID", "sku"):
        v = str(prod.get(k) or "").strip()
        if re.fullmatch(r"\d{4,}", v):
            return v
    return ""


def product_url_with_reason(html: str):
    """(본 상품 주소, 어떻게 만들었나) — 못 만들면 ("", 사유).

    순서 — ① 본문에 JSON-LD 상품 번호와 **같은 번호**의 상품 주소(진짜 스토어 이름)가 있으면 그것
           ② 스토어 주소(슬러그)가 **한 종류뿐**이면 그 스토어 + 상품 번호로 조립
    ⚠️ JSON-LD offers.url 은 쓰지 않는다 — 실측 746건 전부 `smartstore.naver.com/main/products/N`
       (스토어 이름 대신 `main`)이다. 광고주 분석은 주소에서 스토어 이름을 꺼내 보조 대조
       (`"main" in 상품주소`)에 쓰므로, 그 주소를 넘기면 **엉뚱한 상품과 맞춰질 수 있다.**
    ⚠️ 슬러그가 여러 종류(다른 스토어 링크가 섞인 HTML)면 조립하지 않는다 — 남의 스토어 주소를
       본 상품으로 잡는 것보다 비워 두는 쪽이 안전하다(종전 규칙과 같은 원칙).
    """
    try:
        if not html or not isinstance(html, str):
            return "", "empty"
        h = html.replace("\\/", "/") if "\\/" in html else html
        prod = product_ld(h)
        if not prod:
            return "", "no-ld"
        no = product_no(prod)
        if not no:
            return "", "no-number"
        for host, slug, num in _PRODUCT_URL_RE.findall(h):
            if num == no and slug not in _NOT_SLUG:
                return f"https://{host}.naver.com/{slug}/products/{num}", "same-number"
        slugs = {(host, slug) for host, slug in _SLUG_RE.findall(h) if slug not in _NOT_SLUG}
        if len(slugs) == 1:
            host, slug = next(iter(slugs))
            return f"https://{host}.naver.com/{slug}/products/{no}", "one-store"
        return "", ("no-store" if not slugs else "many-stores")
    except Exception:
        return "", "error"


def product_url(html: str) -> str:
    """상세 HTML 에서 **본 상품 주소**를 만든다. 못 만들면 "". (규칙은 product_url_with_reason)"""
    return product_url_with_reason(html)[0]
