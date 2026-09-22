"""Exact Naver product identity shared by offline rank matching and nvMid lookup."""
import re
from urllib.parse import parse_qs, urlparse


def canonical_product_id(value):
    """Preserve a positive ASCII integer ID; never repair or round malformed IDs."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    value = str(value).strip()
    return value if re.fullmatch(r"[1-9][0-9]*", value) else None


def naver_product_identity(value):
    """Return a namespaced exact product identity, ignoring only tracking fields."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlparse(value.strip())
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if (parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host
            or parsed.params):
        return None
    if host in {"smartstore.naver.com", "m.smartstore.naver.com",
                "brand.naver.com", "m.brand.naver.com"}:
        match = re.fullmatch(r"/([^/]+)/products/([1-9][0-9]*)/?", parsed.path)
        if match:
            return (host.removeprefix("m."), match[1], match[2])
        return None
    if host not in {"search.shopping.naver.com", "msearch.shopping.naver.com",
                    "shopping.naver.com", "m.shopping.naver.com"}:
        return None
    catalog = re.fullmatch(r"/catalog/([1-9][0-9]*)/?", parsed.path)
    if not catalog and parsed.path not in {"/catalog", "/catalog/", "/catalog.nhn",
                                           "/detail/detail.nhn", "/outlink/itemdetail.nhn"}:
        return None
    mids = parse_qs(parsed.query, keep_blank_values=True).get("nvMid", [])
    if mids:
        mid = canonical_product_id(mids[0]) if len(mids) == 1 else None
        if not mid or (catalog and catalog[1] != mid):
            return None
        return ("nvMid", mid)
    return ("nvMid", catalog[1]) if catalog else None
