"""오프라인 SEO 근거와 명시적 업체 상품 연결 회귀 시험."""
import json
from pathlib import Path
import sqlite3
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from contextlib import closing
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seo_evidence import ReadError, collect_evidence, client_products


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "sample.sqlite3"
        self.now = datetime(2026, 10, 18, 10, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def cache(self, products, meta=None, day="2026-10-18", at="2026-10-18 09:00:00"):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS collected_serp (id INTEGER PRIMARY KEY, keyword TEXT, "
                         "collected_date TEXT, created_at TEXT, products_json TEXT, meta_json TEXT, source TEXT)")
            conn.execute("INSERT INTO collected_serp(keyword,collected_date,created_at,products_json,meta_json,source) "
                         "VALUES (?,?,?,?,?,?)", ("사과", day, at, json.dumps(products), json.dumps(meta), "extension"))

    def product(self, rank, **extra):
        return {"rank": rank, "productId": str(1000 + rank), "title": "사과 사과 선물",
                "link": "https://smartstore.naver.com/test/products/" + str(1000 + rank), **extra}

    def metadata(self, count=20):
        return {"rankPolicy": "organic-v3(ad:legacy-or-adId+adType+adcrUrl@ader)",
                "adSkipped": 0, "adHintMissed": 0, "rawCount": count,
                "observation": {"keyword": "사과", "status": "complete", "pagesRead": 1,
                                "finishedAt": "2026-10-18T09:00:00+09:00", "organicCount": count,
                                "coveredThroughRank": count,
                                "pageEvidence": [{"page": 1, "keyword": "사과", "verified": True,
                                                  "source": "tap", "originalSource": "tap",
                                                  "href": "https://search.shopping.naver.com/search/all?query=사과"}]}}

    def client_db(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.executescript("CREATE TABLE clients(id INTEGER PRIMARY KEY, name TEXT, naver_store_url TEXT, main_keywords TEXT);"
                               "CREATE TABLE client_keyword_product(id INTEGER PRIMARY KEY, client_id INTEGER, keyword TEXT, product_url TEXT);"
                               "CREATE TABLE client_analyses(id INTEGER PRIMARY KEY, client_id INTEGER, keyword TEXT, product_url TEXT, "
                               "advertiser_json TEXT, analysis_json TEXT, analyzed_date TEXT, updated_at TEXT);")
            conn.execute("INSERT INTO clients VALUES(1, '동명업체', 'https://smartstore.naver.com/test', '사과')")
            conn.execute("INSERT INTO clients VALUES(2, '동명업체', 'https://smartstore.naver.com/other/products/1002', '사과')")

    def link(self, client, keyword, url):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO client_keyword_product(client_id,keyword,product_url) VALUES (?,?,?)", (client, keyword, url))

    def analysis(self, client, url, advertiser=None, analysis=None, at="2026-10-18 09:00:00"):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO client_analyses(client_id,keyword,product_url,advertiser_json,analysis_json,analyzed_date,updated_at) "
                         "VALUES (?,?,?,?,?,?,?)", (client, "사과", url, json.dumps(advertiser or {}), json.dumps(analysis or {}), at[:10], at))

    def test_missing_database_is_read_error_and_is_not_created(self):
        result = collect_evidence(self.db, "사과", now=self.now)
        self.assertEqual(result["status"], "read_error")
        self.assertEqual(result["coverage"], 0)
        self.assertFalse(result["verified_top20"])
        self.assertFalse(self.db.exists())
        with self.assertRaises(ReadError):
            client_products(self.db, 1)
        self.assertFalse(self.db.exists())

    def test_partial_sample_deduplicates_id_url_and_counts_once_per_product(self):
        products = [self.product(1), self.product(2), self.product(3, productId="1001"),
                    self.product(4, link=self.product(2)["link"] + "?tracking=1"), self.product(21)]
        self.cache(products, self.metadata(5))
        result = collect_evidence(self.db, "사과", now=self.now)
        self.assertEqual(result["coverage"], 2)
        self.assertEqual([p["rank"] for p in result["products"]], [1, 2])
        term = next(t for t in result["common_terms"] if t["term"] == "사과")
        self.assertEqual(term, {"term": "사과", "count": 2, "total": 2, "percent": 100.0})
        self.assertFalse(result["verified_top20"])

    def test_twenty_organic_titles_do_not_verify_unavailable_group_catalog_handling(self):
        # 기존 시험은 출처·광고·연속 순위만으로 그룹/카탈로그 처리까지 검증됐다고 오인했다.
        self.cache([self.product(i) for i in range(1, 21)], self.metadata())
        result = collect_evidence(self.db, "사과", now=self.now)
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["label"], "상품명 자료 20/20 · 그룹/카탈로그 미확인")
        self.assertEqual(result["coverage"], 20)
        self.assertTrue(result["ads_verified"])
        self.assertFalse(result["verified_top20"])
        self.assertEqual(result["observed_at"], "2026-10-18T09:00:00+09:00")
        self.assertIn("search.shopping.naver.com", result["surface"])
        term = next(t for t in result["common_terms"] if t["term"] == "사과")
        self.assertEqual(term, {"term": "사과", "count": 20, "total": 20, "percent": 100.0})

    def test_unverifiable_group_catalog_flags_cannot_certify_twenty_products(self):
        metadata = self.metadata()
        metadata.update(group_catalog_verified=True, groupCatalogPolicy="verified")
        products = [self.product(i, groupVerified=True, isCatalog=False) for i in range(1, 21)]
        products[0]["link"] = "https://search.shopping.naver.com/catalog/1001"
        self.cache(products, metadata)
        result = collect_evidence(self.db, "사과", now=self.now)
        self.assertEqual(result["coverage"], 20)
        self.assertTrue(result["ads_verified"])
        self.assertEqual(result["status"], "unverified")
        self.assertFalse(result["verified_top20"])
        self.assertTrue(any("그룹/카탈로그" in note for note in result["notes"]))

    def test_only_explicit_client_product_and_latest_exact_product_facts_are_returned(self):
        self.client_db()
        url = "https://smartstore.naver.com/test/products/1001"
        self.link(1, "사과", url + "?tracking=1")
        self.analysis(1, url, {"product_info": {"product_url": url, "product_name": "예전 이름"}}, at="2026-10-17 09:00:00")
        self.analysis(1, url + "?tracking=2", {"product_info": {"product_url": url, "product_name": "실제 사과", "brand": "실제브랜드",
                                                                  "category1": "식품", "category2": "과일", "features": "실제 속성"}})
        self.analysis(2, url, {"product_info": {"product_url": url, "product_name": "다른 업체 비밀"}}, at="2026-10-19 09:00:00")
        result = client_products(self.db, 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["product_url"], url)
        self.assertEqual(result[0]["product_name"], "실제 사과")
        self.assertEqual(result[0]["category"], "식품 > 과일")
        self.assertEqual(result[0]["current_values"], {"product_name": "실제 사과", "tags": None, "page_title": None, "meta_description": None})
        self.assertNotIn("비밀", json.dumps(result, ensure_ascii=False))

    def test_legacy_schema_selects_latest_real_day_without_inventing_observation_time(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("CREATE TABLE collected_serp(keyword TEXT, collected_date TEXT, products_json TEXT)")
            conn.executemany("INSERT INTO collected_serp VALUES (?,?,?)", [("사과", "2026-10-17", json.dumps([self.product(1, title="어제")])),
                                                                          ("사과", "2026-10-18", json.dumps([self.product(1, title="오늘")]))])
        result = collect_evidence(self.db, "사과", now=self.now)
        self.assertEqual(result["products"][0]["title"], "오늘")
        self.assertIsNone(result["observed_at"])
        self.assertIsNone(result["surface"])
        self.assertEqual(result["status"], "unverified")

    def test_control_characters_and_credential_host_injection_are_not_product_links(self):
        self.client_db()
        invalid = ["https://smartstore.naver.com.evil/test/products/1001", "https://smartstore.naver.com@evil/test/products/1001",
                   "https://user:password@smartstore.naver.com/test/products/1001", "https://smartstore.naver.com:443/test/products/1001",
                   "https://smartstore.naver.com/test/products/10\n01", "https://evil/?nvMid=1001", "javascript:alert(1)",
                   "https://search.shopping.naver.com/catalog/1001?nvMid=1002"]
        for i, url in enumerate(invalid):
            self.link(1, str(i), url)
        self.assertEqual(client_products(self.db, 1), [])

    def test_duplicate_rank_is_not_certified_even_when_twenty_unique_ranks_remain(self):
        products = [self.product(i) for i in range(1, 21)] + [self.product(1, productId="9999", link="https://smartstore.naver.com/test/products/9999")]
        self.cache(products, self.metadata(21))
        result = collect_evidence(self.db, "사과", now=self.now)
        self.assertEqual(result["coverage"], 20)
        self.assertEqual(result["status"], "unverified")
        self.assertFalse(result["verified_top20"])

    def test_explicit_ad_is_never_a_common_term_sample_or_verified_organic_result(self):
        products = [self.product(i) for i in range(1, 21)]
        products[0].update(isAd=True, title="광고상품")
        self.cache(products, self.metadata())
        result = collect_evidence(self.db, "사과", now=self.now)
        self.assertEqual(result["coverage"], 19)
        self.assertFalse(result["ads_verified"])
        self.assertFalse(result["verified_top20"])
        self.assertFalse(any(t["term"] == "광고상품" for t in result["common_terms"]))

    def test_source_fallback_and_missing_ad_or_observation_evidence_remain_unverified(self):
        cases = {"no_meta": None, "missing_original": self.metadata(), "missing_ads": self.metadata(),
                 "wrong_keyword": self.metadata(), "wrong_host": self.metadata(), "missing_time": self.metadata()}
        del cases["missing_original"]["observation"]["pageEvidence"][0]["originalSource"]
        del cases["missing_ads"]["rankPolicy"]
        cases["wrong_keyword"]["observation"]["pageEvidence"][0]["keyword"] = "배"
        cases["wrong_host"]["observation"]["pageEvidence"][0]["href"] = "https://search.shopping.naver.com.evil/search/all"
        del cases["missing_time"]["observation"]["finishedAt"]
        for name, metadata in cases.items():
            with self.subTest(case=name):
                self.db = Path(self.temp.name) / (name + ".sqlite3")
                self.cache([self.product(i) for i in range(1, 21)], metadata)
                result = collect_evidence(self.db, "사과", now=self.now)
                self.assertEqual(result["coverage"], 20)
                self.assertEqual(result["status"], "unverified")
                self.assertFalse(result["verified_top20"])

    def test_ads_are_not_marked_verified_when_original_source_is_missing(self):
        meta = self.metadata()
        del meta["observation"]["pageEvidence"][0]["originalSource"]
        self.cache([self.product(i) for i in range(1, 21)], meta)
        self.assertFalse(collect_evidence(self.db, "사과", now=self.now)["ads_verified"])

    def test_partial_status_and_old_observation_are_distinct(self):
        self.cache([self.product(i) for i in range(1, 4)], self.metadata(3))
        result = collect_evidence(self.db, "사과", now=self.now)
        self.assertEqual((result["status"], result["label"]), ("partial", "부분 자료 3/20"))
        self.db = Path(self.temp.name) / "old.sqlite3"
        meta = self.metadata()
        meta["observation"]["finishedAt"] = "2026-10-16T23:59:59+09:00"
        self.cache([self.product(i) for i in range(1, 21)], meta, day="2026-10-19")
        result = collect_evidence(self.db, "사과", now=self.now)
        self.assertEqual((result["status"], result["collected_date"]), ("stale", "2026-10-16"))
        self.assertFalse(result["verified_top20"])

    def test_actual_finished_at_takes_precedence_over_cycle_and_envelope_dates(self):
        metadata = self.metadata()
        metadata["observation"]["actualFinishedAt"] = "2026-10-18T18:00:00+09:00"
        metadata["observation"]["finishedAt"] = "2026-10-19T00:00:00+09:00"
        self.cache([self.product(i) for i in range(1, 21)], metadata, day="2026-10-19")
        result = collect_evidence(self.db, "사과", now=self.now)
        self.assertEqual(result["observed_at"], "2026-10-18T18:00:00+09:00")
        self.assertEqual(result["collected_date"], "2026-10-18")
        self.assertFalse(result["verified_top20"])

    def test_latest_observation_does_not_sort_by_future_collector_cycle(self):
        old = self.metadata(1)
        old["observation"]["finishedAt"] = "2026-10-17T23:00:00+09:00"
        self.cache([self.product(1, title="이전")], old, day="2026-10-20", at="2026-10-18 10:00:00")
        fresh = self.metadata(1)
        fresh["observation"]["finishedAt"] = "2026-10-18T09:00:00+09:00"
        self.cache([self.product(1, title="최신")], fresh, day="2026-10-18", at="2026-10-18 09:00:00")
        self.assertEqual(collect_evidence(self.db, "사과", now=self.now)["products"][0]["title"], "최신")

    def test_no_data_and_unreadable_stored_json_are_not_the_same_state(self):
        self.cache([], self.metadata(0))
        self.assertEqual(collect_evidence(self.db, "없는 키워드", now=self.now)["status"], "no_data")
        self.assertEqual(collect_evidence(self.db, "사과", now=self.now)["status"], "no_data")
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE collected_serp SET products_json='not json'")
        result = collect_evidence(self.db, "사과", now=self.now)
        self.assertEqual(result["status"], "read_error")
        self.assertNotEqual(result["label"], "자료 없음")

    def test_public_calls_use_read_only_query_only_connections_without_network_or_queue_changes(self):
        self.cache([self.product(1)], None)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("CREATE TABLE collect_requests(keyword TEXT, status TEXT)")
            conn.execute("INSERT INTO collect_requests VALUES('사과','pending')")
            conn.execute("CREATE TABLE clients(id INTEGER PRIMARY KEY)")
        before = self.db.read_bytes()
        real_connect, connections = sqlite3.connect, []
        def checked_connect(path, *args, **kwargs):
            self.assertTrue(kwargs.get("uri"))
            self.assertIn("mode=ro", path)
            conn = real_connect(path, *args, **kwargs)
            connections.append(conn)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO collect_requests VALUES ('x','pending')")
            conn.set_trace_callback(lambda statement: self.assertFalse(statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"))))
            return conn
        with patch("seo_evidence.sqlite3.connect", checked_connect), patch.object(socket.socket, "connect", side_effect=AssertionError("네트워크 금지")):
            self.assertEqual(collect_evidence(self.db, "' OR 1=1 --", now=self.now)["status"], "no_data")
            self.assertEqual(client_products(self.db, 999), [])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertTrue(connections)
        for conn in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")

    def test_same_store_fallback_cannot_fill_current_product_values(self):
        self.client_db()
        url = "https://smartstore.naver.com/test/products/1001"
        self.link(1, "사과", url)
        self.analysis(1, url, {"product_info": {"product_name": "동일 판매처 다른 상품", "brand": "틀린브랜드"}},
                      {"targetProductInfo": {"product_name": "스토어 폴백 상품"}})
        product = client_products(self.db, 1)[0]
        self.assertIsNone(product["product_name"])
        self.assertIsNone(product["brand"])
        self.assertTrue(all(value is None for value in product["current_values"].values()))

    def test_only_actual_tags_and_meta_of_matching_product_are_returned(self):
        self.client_db()
        url = "https://m.smartstore.naver.com/test/products/1001?tracking=x"
        self.link(1, "사과", url)
        self.analysis(1, url, {"product_info": {"product_id": "1001", "product_name": "현재 상품명",
                                                  "seoInfo": {"sellerTags": [{"text": "현재태그"}], "pageTitle": "현재 타이틀", "metaDescription": "현재 설명"}}})
        self.analysis(1, "https://smartstore.naver.com/test/products/1002", {"product_info": {"product_name": "다른 상품"}}, at="2026-10-19 10:00:00")
        current = client_products(self.db, 1)[0]["current_values"]
        self.assertEqual(current, {"product_name": "현재 상품명", "tags": ["현재태그"], "page_title": "현재 타이틀", "meta_description": "현재 설명"})

    def test_explicit_store_product_url_is_allowed_but_store_home_and_analysis_only_products_are_not(self):
        self.client_db()
        self.analysis(1, "https://smartstore.naver.com/test/products/1999", {"product_info": {"product_id": "1999", "product_name": "분석만한 상품"}})
        self.assertEqual(client_products(self.db, 1), [])
        result = client_products(self.db, 2)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["product_url"], "https://smartstore.naver.com/other/products/1002")
        self.assertIsNone(result[0]["product_name"])

    def test_product_key_is_stable_for_tracking_mobile_variants_and_duplicate_links(self):
        self.client_db()
        self.link(1, "사과", "https://smartstore.naver.com/test/products/1001?tracking=1")
        first = client_products(self.db, 1)
        self.link(1, "선물", "https://m.smartstore.naver.com/test/products/1001?tracking=2")
        second = client_products(self.db, 1)
        self.assertEqual(first, second)
        self.assertEqual(client_products(self.db, "1 OR 1=1"), [])

    def test_exact_rank_links_complete_product_list_without_store_slug_or_other_client_data(self):
        self.client_db()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.executescript("CREATE TABLE rank_link(id INTEGER PRIMARY KEY,client_id INTEGER,tracked_product_id INTEGER,match_method TEXT);"
                               "CREATE TABLE tracked_products(id INTEGER PRIMARY KEY,product_url TEXT,product_name TEXT);"
                               "CREATE TABLE tracked_keywords(id INTEGER PRIMARY KEY,product_id INTEGER,keyword TEXT);"
                               "CREATE TABLE collect_requests(keyword TEXT,status TEXT);")
            conn.executemany("INSERT INTO tracked_products VALUES(?,?,?)", [
                (101, "https://m.smartstore.naver.com/test/products/1001?tracking=rank", "신뢰하지 않는 추적 상품명"),
                (102, "https://smartstore.naver.com/test/products/1002", "추적 상품명만 있음"),
                (103, "https://smartstore.naver.com/test/products/1003", "판매처 자동 연결"),
                (104, "https://smartstore.naver.com/other/products/1004", "다른 업체 상품")])
            conn.executemany("INSERT INTO rank_link VALUES(?,?,?,?)", [(1, 1, 101, "manual"), (2, 1, 102, "product_id"),
                                                                       (3, 1, 103, "store_slug"), (4, 2, 104, "manual")])
            conn.executemany("INSERT INTO tracked_keywords VALUES(?,?,?)", [(1, 101, "첫 연결 키워드"), (2, 101, "다음 키워드"),
                                                                          (3, 102, "두 번째 상품 키워드")])
            conn.execute("INSERT INTO collect_requests VALUES('기존 요청','pending')")
        self.analysis(1, "https://smartstore.naver.com/test/products/1001", {"product_info": {
            "product_url": "https://smartstore.naver.com/test/products/1001", "product_name": "검증된 분석 상품명"}})
        before = self.db.read_bytes()
        with patch.object(socket.socket, "connect", side_effect=AssertionError("네트워크 금지")):
            products = client_products(self.db, 1)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual([p["product_url"] for p in products], ["https://smartstore.naver.com/test/products/1001",
                                                              "https://smartstore.naver.com/test/products/1002"])
        self.assertEqual([p["keyword"] for p in products], ["첫 연결 키워드", "두 번째 상품 키워드"])
        self.assertEqual(products[0]["product_name"], "검증된 분석 상품명")
        self.assertIsNone(products[1]["product_name"])
        self.assertTrue(all(value is None for value in products[1]["current_values"].values()))
        self.link(1, "명시 키워드", "https://smartstore.naver.com/test/products/1001?tracking=map")
        deduplicated = client_products(self.db, 1)
        self.assertEqual(len(deduplicated), 2)
        self.assertEqual(deduplicated[0]["product_key"], products[0]["product_key"])
        self.assertEqual(deduplicated[0]["keyword"], "명시 키워드")

    def test_malformed_metadata_keeps_readable_products_but_cannot_verify_source(self):
        meta = self.metadata()
        meta["observation"]["pageEvidence"][0]["originalSource"] = ["tap"]
        meta["observation"]["status"] = ["complete"]
        self.cache([self.product(i) for i in range(1, 21)], meta)
        result = collect_evidence(self.db, "사과", now=self.now)
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["coverage"], 20)
        self.assertFalse(result["verified_top20"])

    def test_matching_row_cannot_use_nested_info_of_a_different_store_or_catalog_namespace(self):
        self.client_db()
        url = "https://smartstore.naver.com/test/products/1001"
        self.link(1, "사과", url)
        self.analysis(1, url, {"product_info": {"product_url": "https://smartstore.naver.com/other/products/1001", "product_name": "다른 스토어"}},
                      {"targetProductInfo": {"product_url": "https://search.shopping.naver.com/catalog/1001", "product_name": "다른 카탈로그"}})
        self.assertIsNone(client_products(self.db, 1)[0]["product_name"])

    def test_client_read_failure_is_distinct_from_a_normal_empty_product_list(self):
        with self.assertRaises(ReadError):
            client_products(self.db, 1)
        self.client_db()
        self.assertEqual(client_products(self.db, 999), [])
        self.assertEqual(client_products(self.db, 1), [])
        url = "https://smartstore.naver.com/test/products/1001"
        self.link(1, "사과", url)
        self.analysis(1, url)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE client_analyses SET advertiser_json='invalid json'")
        with self.assertRaises(ReadError):
            client_products(self.db, 1)

    def test_price_only_returns_real_scalar_values(self):
        for index, (price, expected) in enumerate([({"secret": "not a price"}, None), ([100], None), (True, None),
                                                    (float("nan"), None), (100, 100), (10.5, 10.5), ("9,900", "9,900")]):
            with self.subTest(price=price):
                self.db = Path(self.temp.name) / ("price" + str(index) + ".sqlite3")
                self.cache([self.product(1, price=price)], None)
                result = collect_evidence(self.db, "사과", now=self.now)
                self.assertEqual(result["products"][0]["price"], expected)


if __name__ == "__main__":
    unittest.main()
