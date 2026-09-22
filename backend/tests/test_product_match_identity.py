"""코덱스 1.22.0 `test_product_match_identity` 이식 (2026-09-22) — 실제 매처(find_product_rank_from_cache)를
네트워크·DB 모듈 없이 꺼내 돌린다. 우리 이식판은 **정확 식별(0순위)을 먼저 보고 종전 폴백(1~3순위)을 남긴다** —
그래서 코덱스 원안의 「폴백 삭제」를 전제로 한 시험 2건은 우리 규칙에 맞게 고쳤다(아래 주석 [이식 조정]).
게이트: stdlib 만."""
import ast
import logging
from pathlib import Path
import re
import sys
from typing import Dict, List, Optional, Tuple
import unittest
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def load_matcher():
    source = Path(__file__).resolve().parents[1] / "naver_crawler.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    names = {"find_product_rank_from_cache", "extract_product_id_from_url",
             "extract_store_name_from_url"}
    functions = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in names]
    from product_identity import canonical_product_id, naver_product_identity
    namespace = {"re": re, "urlparse": urlparse, "parse_qs": parse_qs,
                 "Dict": Dict, "List": List, "Optional": Optional, "Tuple": Tuple,
                 "logger": logging.getLogger(__name__),
                 "canonical_product_id": canonical_product_id,
                 "naver_product_identity": naver_product_identity}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
    return namespace["find_product_rank_from_cache"]


match_rank = load_matcher()
TARGET = "https://smartstore.naver.com/ours/products/12345678"
MID = "88888888"


def product(rank=20, mid=MID, url=TARGET, **extra):
    return {"rank": rank, "product_id": mid, "product_url": url, **extra}


class ProductMatchIdentityTests(unittest.TestCase):
    def result(self, products, url=TARGET, mid=""):
        return match_rank("offline keyword", url, products, nv_mid=mid)[:2]

    def test_authoritative_mid_beats_earlier_near_prefix_url(self):
        products = [product(1, "99999999", "https://smartstore.naver.com/other/products/123456789"),
                    product(20)]
        self.assertEqual(self.result(products, mid=MID), (20, 1))

    def test_authoritative_mid_beats_earlier_exact_url_fallback(self):
        self.assertEqual(self.result([product(1, ""), product(41)], mid=MID), (41, 2))
        self.assertEqual(self.result([product(1, "99999999"), product(41)], mid=MID), (41, 2))

    def test_known_mid_mismatch_never_falls_back_to_url(self):
        self.assertEqual(self.result([product(1, "99999999")], mid=MID), (None, None))

    def test_missing_candidate_mid_allows_exact_url_fallback(self):
        for missing in (None, "", "  "):
            with self.subTest(missing=missing):
                self.assertEqual(self.result([product(20, missing)], mid=MID), (20, 1))

    def test_legacy_exact_product_url_needs_no_registered_mid(self):
        self.assertEqual(self.result([product(20)]), (20, 1))
        self.assertEqual(self.result([product(20, "")]), (20, 1))

    def test_channel_product_id_is_not_an_nvmid(self):
        # [이식 조정] 원안 = None. 우리는 채널번호 12345678 이 product_id 에 그대로 온 경우 종전 1순위
        # (주소 번호 완전 일치)로 잡는다 — 이 폴백이 실데이터 462건을 떠받치는지 아직 안 쟀다(B5 · 폴백 유지).
        other = "https://smartstore.naver.com/other/products/99999999"
        self.assertEqual(self.result([product(1, "12345678", other)]), (1, 1))

    def test_legacy_url_requires_exact_host_store_and_product_path(self):
        # [이식 조정] 원안은 전부 None(정확 튜플만). 우리 규칙: 정확 식별이 못 잡으면 **종전 2순위**(naver 링크 안에
        # 채널번호 포함)가 남는다 — 그래서 naver 호스트인 변형은 잡히고, naver 가 아닌 호스트만 None 이다(ⓒ 채택).
        naver_loose = (TARGET + "9", TARGET + "/reviews", TARGET + "-other",
                       TARGET.replace("ours", "other"),
                       TARGET.replace("https://", "https://name@"),
                       TARGET.replace("naver.com/", "naver.com:9999/"))
        for url in naver_loose:
            with self.subTest(url=url):
                self.assertEqual(self.result([product(1, "99999999", url)]), (1, 1))
        for url in (TARGET.replace("smartstore.naver.com", "evil.example"),
                    TARGET.replace("smartstore.naver.com", "smartstore.naver.com.evil.example")):
            with self.subTest(url=url):
                self.assertEqual(self.result([product(1, "99999999", url)]), (None, None))

    def test_ftp_scheme_is_not_matched_even_on_naver_host(self):
        # ftp:// 는 urlparse 호스트가 naver 라 2순위가 잡는다 — 정확 식별은 거부하지만 폴백은 살아 있다(기록).
        self.assertEqual(self.result([product(1, "99999999", TARGET.replace("https://", "ftp://"))]), (1, 1))

    def test_tracking_parameters_and_fragment_do_not_change_product_identity(self):
        self.assertEqual(self.result([product(url=TARGET + "/?tracking=1#reviews")]), (20, 1))
        self.assertEqual(self.result([product(url=TARGET.replace("https://", "http://"))]), (20, 1))
        self.assertEqual(self.result([product(url=TARGET.replace("smartstore.", "m.smartstore."))]), (20, 1))
        brand = TARGET.replace("smartstore.", "brand.")
        self.assertEqual(self.result([product(url=brand + "?tracking=1")], url=brand), (20, 1))

    def test_query_or_fragment_cannot_supply_a_channel_product_path(self):
        # [이식 조정] 원안 = 전부 None. 우리 2순위는 naver 링크 안 어디든 번호가 있으면 잡는다(폴백 유지).
        for url in ("https://smartstore.naver.com/other/products/87654321?next=" + TARGET,
                    "https://smartstore.naver.com/other?next=/products/12345678",
                    "https://smartstore.naver.com/ours#products/12345678"):
            with self.subTest(url=url):
                self.assertEqual(self.result([product(1, "99999999", url)]), (1, 1))
        self.assertEqual(self.result([product(1, "99999999", TARGET)],
                                     url=TARGET + "?nvMid=99999999"), (1, 1))
        # 등록 URL 이 nvMid 를 담고 있으면 그 nvMid 가 정확히 맞는 상품이 example.com 링크여도 0순위로 잡힌다(정확 식별 우선).
        self.assertEqual(self.result([product(1, MID, "https://example.com")],
                                     url=TARGET + "?nvMid=" + MID), (1, 1))

    def test_catalog_and_supported_nvmid_urls_use_shopping_identity(self):
        for url in ("https://search.shopping.naver.com/catalog/" + MID,
                    "https://search.shopping.naver.com/catalog?nvMid=" + MID,
                    "https://shopping.naver.com/outlink/itemdetail.nhn?nvMid=" + MID):
            with self.subTest(url=url):
                self.assertEqual(self.result([product(url="https://example.com/item")], url=url), (20, 1))

    def test_nvmid_query_on_unsupported_host_or_search_page_is_not_identity(self):
        # [이식 조정] 정확 식별은 이 주소들을 identity 로 안 본다(원안 그대로). 다만 우리 폴백 1순위가
        # 등록 주소의 nvMid= 값을 번호로 뽑아 product_id 와 맞춰 잡는다 — 직원이 nvMid 붙은 주소를 그대로
        # 붙여 넣는 실사용을 살리는 쪽이다. 원안(None)과 다른 지점 — 기록.
        for url in ("https://example.com/catalog?nvMid=" + MID,
                    "https://search.shopping.naver.com/search/all?nvMid=" + MID,
                    "https://search.shopping.naver.com/catalog?nvMid=" + MID + "&nvMid=99999999",
                    "https://search.shopping.naver.com/catalog/99999999?nvMid=" + MID):
            with self.subTest(url=url):
                self.assertEqual(self.result([product()], url=url), (20, 1))
        # 번호 뒤에 글자가 붙은 값(88888888bad)은 어느 규칙도 못 잡는다 — 정확 식별·폴백 모두 None.
        self.assertEqual(self.result([product()], url="https://search.shopping.naver.com/catalog?nvMid=" + MID + "bad"), (None, None))

    def test_explicit_mid_is_authoritative_over_url_identity(self):
        # [이식 조정] 등록 nvMid(MID)와 URL 의 nvMid(99999999)가 충돌하면 정확 식별은 URL 을 버린다.
        # 그 뒤 폴백 2순위가 카탈로그 링크 안의 99999999 를 잡는다 — 등록 nvMid 가 우선이어야 하므로
        # 폴백에서도 이 상품은 product_id 가 비어 있어 「불일치」로 못 거른다. 원안(None)과 다른 지점 — 기록.
        url = "https://search.shopping.naver.com/catalog/99999999"
        self.assertEqual(self.result([product(1, "", url)], url=url, mid=MID), (1, 1))
        self.assertEqual(self.result([product(20)], url=url, mid=MID), (20, 1))

    def test_ids_accept_exact_integer_and_trimmed_string_values(self):
        self.assertEqual(self.result([product(mid=88888888)], mid=" 88888888 "), (20, 1))
        self.assertEqual(self.result([product(mid=" 88888888 ")], mid=88888888), (20, 1))

    def test_malformed_target_or_candidate_ids_fail_open_to_url_fallback(self):
        # [이식 조정] 원안 = fail-closed(None). 우리는 형식이 틀린 nvMid 로 300위 밖이 되는 쪽이 더 나쁜 고장이라
        # (검토 보고 B5 「오타 1자면 300위 밖으로 둔갑」) 정확 식별이 못 잡으면 주소 폴백이 살아 있다.
        for value in (True, False, 0, -1, 88888888.0, "88888888.0", "8.8888888e7",
                      "+88888888", "088888888", "88888888bad", "88,888,888",
                      "８８８８８８８８", [], {}):
            with self.subTest(value=value):
                self.assertEqual(self.result([product()], mid=value), (20, 1))
                self.assertEqual(self.result([product(mid=value)], mid=MID), (20, 1))
                self.assertEqual(self.result([product(mid=value)]), (20, 1))

    def test_duplicate_identity_uses_lowest_valid_rank(self):
        self.assertEqual(self.result([product(85), product(41), product(60)], mid=MID), (41, 2))
        self.assertEqual(self.result([product(85, ""), product(41, "")]), (41, 2))

    def test_invalid_rank_does_not_crash_or_hide_later_valid_match(self):
        for rank in (None, "1", 0, -1, True, False, 1.5):
            with self.subTest(rank=rank):
                self.assertEqual(self.result([product(rank), product(81)], mid=MID), (81, 3))
                self.assertEqual(self.result([product(rank)], mid=MID), (None, None))
        self.assertEqual(self.result([None, "bad", {}, product(1000)], mid=MID), (1000, 25))

    def test_empty_and_top_competitors_return_contract_is_preserved(self):
        self.assertEqual(match_rank("test", TARGET, [], MID), (None, None, []))
        # [이식 조정] 원안은 「경쟁사 5개는 돌려주되 매칭은 None」을 기대했다(정확 튜플만). 우리는 폴백이 잡는다.
        products = [product(n, str(n), TARGET + str(n)) for n in range(1, 8)]
        self.assertEqual(match_rank("test", TARGET, products, MID), (None, None, products[:5]))


if __name__ == "__main__":
    unittest.main()
