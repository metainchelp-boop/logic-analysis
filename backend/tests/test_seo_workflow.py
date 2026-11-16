"""SEO 생성→직원 검수→승인본 저장. 운영/외부 연결 없는 API 회귀."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import nullcontext

os.environ.setdefault("JWT_SECRET_KEY", "offline-seo-test-only")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import seo_generate as seo
from fastapi import FastAPI
from fastapi.testclient import TestClient


class SeoWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fixture.db")
        self.db_patch = patch.object(seo, "DB_PATH", self.db)
        self.db_patch.start()
        seo.init_seo_db()
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TABLE clients(id INTEGER PRIMARY KEY,name TEXT,status TEXT,role TEXT,created_by INTEGER)")
            conn.executemany("INSERT INTO clients VALUES(?,?,?,?,?)", [
                (1, "가짜 광고주", "active", "advertiser", 3),
                (2, "격리 가망", "active", "prospect", 99),
                (3, "다른 광고주", "active", "advertiser", 4)])
        self.user = {"id": 7, "username": "test-reviewer", "role": "manager"}
        app = FastAPI()
        app.include_router(seo.router)
        app.dependency_overrides[seo.get_current_user] = lambda: self.user
        self.api = TestClient(app)
        self.net = patch("socket.socket.connect", side_effect=AssertionError("external network forbidden"))
        self.net.start()

    def tearDown(self):
        self.api.close()
        self.net.stop()
        self.db_patch.stop()
        self.tmp.cleanup()

    def generate(self, extra=None, output=None, error=None, real_evidence=False):
        payload = {"keyword": "누룽지", "client_id": 1,
                   "product_url": "https://smartstore.naver.com/test/products/123",
                   "current_values": {"product_name": "기존 누룽지", "tags": None,
                                      "page_title": None, "meta_description": None}}
        payload.update(extra or {})
        raw = output if output is not None else {
            "product_names": ["누룽지"], "tags": ["간식"], "category": "식품",
            "page_title": "누룽지 상품 안내", "meta_description": "상품 정보를 확인해 보세요.",
            "rationale": ["확인된 상품 종류만 사용했습니다."],
            "field_reasons": {key: ["상품 사실을 기준으로 작성했습니다."] for key in
                              ("product_name", "tags", "page_title", "meta_description")}}
        provider = Mock()
        self.provider = provider
        provider.messages.create.side_effect = error
        provider.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(text=json.dumps(raw, ensure_ascii=False))],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1))
        context = {"top_titles": [], "categories": [], "products": [], "coverage": 0,
                   "status": "no_data", "label": "자료 없음", "notes": [], "common_terms": []}
        with patch.object(seo, "_get_claude_client", return_value=provider), \
             (nullcontext() if real_evidence else patch.object(seo, "_collect_naver_context", return_value=context)):
            return self.api.post("/api/seo/generate", json=payload)

    def test_generation_returns_four_fields_and_preserves_legacy_fields(self):
        response = self.generate()
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["recommendation"]["page_title"], "누룽지 상품 안내")
        self.assertEqual(data["recommendation"]["meta_description"], "상품 정보를 확인해 보세요.")
        self.assertEqual(data["product_names"], ["누룽지"])
        self.assertEqual(data["current_values"]["tags"], None)
        self.assertTrue(data["generation_id"])
        self.assertTrue(data["rules_version"])

    def test_review_requires_confirmation_and_saves_original_and_edited_approval_once(self):
        data = self.generate().json()["data"]
        approved = dict(data["recommendation"], product_name="직원이 검토한 누룽지")
        body = {"client_id": 1, "keyword": "누룽지", "product_url": data["product_url"],
                "generation_id": data["generation_id"], "approved_values": approved,
                "decisions": {"product_name": "edit", "tags": "hold", "page_title": "adopt", "meta_description": "adopt"}}
        self.assertFalse(self.api.post("/api/seo/save-to-client", json=body).json()["success"])
        body["reviewed"] = True
        first = self.api.post("/api/seo/save-to-client", json=body).json()
        self.assertTrue(first["success"], first)
        self.assertTrue(self.api.post("/api/seo/save-to-client", json=body).json()["success"])
        saved = self.api.get("/api/seo/client/1/saved").json()["data"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["product_name"], approved["product_name"])
        self.assertEqual(saved[0]["review"]["approved_values"]["tags"], None)
        self.assertEqual(saved[0]["review"]["original"]["recommendation"]["product_name"], "누룽지")
        self.assertEqual(saved[0]["review"]["reviewed_by"], "test-reviewer")

    def test_bad_output_types_fail_without_turning_strings_into_character_lists(self):
        result = self.generate(output={"product_names": "잘못된 이름", "tags": "키워드"}).json()
        self.assertFalse(result["success"], result)
        self.assertEqual(result["code"], "AI_RESPONSE_INVALID")

    def test_generation_checks_company_access_before_provider_call(self):
        self.assertEqual(self.generate(extra={"client_id": 2}).status_code, 403)

    def test_provider_credit_error_is_actionable_and_logs_no_raw_secret(self):
        error = RuntimeError("Error code: 400 Your credit balance is too low canary-secret-company")
        with self.assertLogs("seo_generate", level="ERROR") as logs:
            result = self.generate(error=error).json()
        self.assertEqual(result.get("code"), "AI_CREDIT_EXHAUSTED")
        self.assertNotIn("canary-secret", str(logs.output))
        self.assertNotIn("canary-secret", json.dumps(result))

    def test_recommended_rules_activation_keeps_custom_rules_history_and_old_saved_rows(self):
        self.user["role"] = "superadmin"
        self.assertTrue(self.api.put("/api/seo/rules", json={"rules_text": "기존 사용자 기준"}).json()["success"])
        self.api.post("/api/seo/save-to-client", json={"client_id": 1, "keyword": "예전 키워드", "product_name": "이전 저장"})
        self.assertTrue(self.api.post("/api/seo/rules/activate-recommended").json()["success"])
        rules = self.api.get("/api/seo/rules").json()["data"]
        self.assertTrue(rules["is_recommended_active"])
        self.assertIn("최대 10개", rules["rules_text"])
        with sqlite3.connect(self.db) as conn:
            self.assertTrue(conn.execute("SELECT 1 FROM seo_rules_history WHERE rules_text='기존 사용자 기준'").fetchone())
        saved = self.api.get("/api/seo/client/1/saved").json()["data"]
        self.assertEqual(saved[0]["product_name"], "이전 저장")
        self.assertIsNone(saved[0]["review"])

    def test_roles_and_legacy_save_contract_are_preserved(self):
        legacy = {"client_id": 1, "keyword": "누룽지", "product_name": "이전 방식", "tags": ["간식"], "source": "diagnose"}
        self.assertTrue(self.api.post("/api/seo/save-to-client", json=legacy).json()["success"])
        saved = self.api.get("/api/seo/client/1/saved").json()["data"][0]
        self.assertEqual(saved["source"], "diagnose")
        self.assertEqual(saved["tags"], ["간식"])
        self.assertIsNone(saved["review"])
        self.assertEqual(self.api.put("/api/seo/rules", json={"rules_text": "권한 없음"}).status_code, 403)
        self.assertEqual(self.api.post("/api/seo/rules/activate-recommended").status_code, 403)
        self.assertEqual(self.api.get("/api/seo/client/2/saved").status_code, 403)
        self.user["role"] = "viewer"
        self.assertEqual(self.generate().status_code, 403)
        self.assertEqual(self.api.post("/api/seo/save-to-client", json=legacy).status_code, 403)
        self.assertEqual(self.api.get("/api/seo/client/1/products").status_code, 403)
        self.assertEqual(self.api.get("/api/seo/rules").status_code, 403)

    def test_approval_cannot_be_saved_to_a_different_company_product_or_keyword(self):
        data = self.generate().json()["data"]
        base = {"client_id": 1, "keyword": "누룽지", "product_url": data["product_url"],
                "generation_id": data["generation_id"], "reviewed": True,
                "decisions": {key: "adopt" for key in seo.seo_review.FIELDS}}
        for replacement in ({"client_id": 3}, {"keyword": "다른 키워드"}, {"product_url": "https://smartstore.naver.com/test/products/999"}):
            result = self.api.post("/api/seo/save-to-client", json=dict(base, **replacement)).json()
            self.assertFalse(result["success"], result)
        self.assertEqual(self.api.get("/api/seo/client/1/saved").json()["data"], [])

    def test_invalid_output_lengths_tags_empty_names_and_missing_reasons_fail(self):
        base = {"product_names": ["누룽지"], "tags": [], "category": "식품", "page_title": "제목",
                "meta_description": "설명", "rationale": ["사실 기반"]}
        cases = ({"product_names": []}, {"product_names": [""]}, {"product_names": ["가" * 101]},
                 {"tags": ["#"]}, {"tags": [str(i) for i in range(11)]},
                 {"page_title": "가" * 101}, {"meta_description": "가" * 161}, {"rationale": []})
        for change in cases:
            with self.subTest(change=change):
                self.assertEqual(self.generate(output=dict(base, **change)).json()["code"], "AI_RESPONSE_INVALID")

    def test_bad_input_is_rejected_before_generation(self):
        for change in ({"product_url": "javascript:alert(1)"}, {"current_values": {"tags": "문자열"}},
                       {"features": "가" * 3001}):
            self.assertEqual(self.generate(extra=change).json()["code"], "INPUT_INVALID")

    def test_provider_status_errors_remain_business_failures(self):
        for status, code in ((401, "AI_AUTH_FAILED"), (403, "AI_AUTH_FAILED"), (404, "AI_MODEL_UNAVAILABLE"),
                             (429, "AI_RATE_LIMIT"), (503, "AI_UPSTREAM_ERROR"), (400, "AI_REQUEST_INVALID")):
            result = self.generate(error=RuntimeError(f"Error code: {status}")).json()
            self.assertFalse(result["success"])
            self.assertEqual(result["code"], code)

    def test_product_read_failure_is_not_reported_as_empty_success(self):
        with patch("seo_evidence.client_products", side_effect=sqlite3.OperationalError("fake failure")):
            result = self.api.get("/api/seo/client/1/products").json()
            self.assertFalse(result["success"])
        self.assertEqual(self.api.get("/api/seo/client/2/products").status_code, 403)

    def test_original_input_facts_are_preserved_after_review(self):
        data = self.generate(extra={"brand": "확인 브랜드", "category": "입력 카테고리", "features": "확인된 속성"}).json()["data"]
        self.api.post("/api/seo/save-to-client", json={"client_id": 1, "keyword": data["keyword"],
            "product_url": data["product_url"], "generation_id": data["generation_id"], "reviewed": True,
            "decisions": {key: "adopt" for key in seo.seo_review.FIELDS}})
        saved = self.api.get("/api/seo/client/1/saved").json()["data"][0]
        self.assertEqual(saved["review"]["original"]["input_facts"],
                         {"brand": "확인 브랜드", "category": "입력 카테고리", "features": "확인된 속성"})

    def test_seo_model_override_does_not_require_changing_shared_chat_model(self):
        with patch.object(seo, "CLAUDE_MODEL", "claude-sonnet-4-20250514"), \
             patch.dict(os.environ, {"SEO_CLAUDE_MODEL": "claude-sonnet-4-6"}):
            self.assertTrue(self.generate().json()["success"])
            self.assertEqual(self.provider.messages.create.call_args.kwargs["model"], "claude-sonnet-4-6")

    def test_retired_model_is_actionable_without_another_dead_provider_request(self):
        with patch.object(seo, "CLAUDE_MODEL", "claude-sonnet-4-20250514"), \
             patch.dict(os.environ, {"SEO_CLAUDE_MODEL": ""}):
            result = self.generate().json()
            self.assertEqual(result["code"], "AI_MODEL_RETIRED")
            self.provider.messages.create.assert_not_called()

    def test_real_cached_evidence_and_linked_product_flow_through_generation_and_review(self):
        url = "https://smartstore.naver.com/test/products/123"
        with sqlite3.connect(self.db) as conn:
            conn.executescript("""CREATE TABLE client_keyword_product(id INTEGER PRIMARY KEY,client_id INTEGER,keyword TEXT,product_url TEXT);
                CREATE TABLE client_analyses(id INTEGER PRIMARY KEY,client_id INTEGER,product_url TEXT,advertiser_json TEXT);
                CREATE TABLE collected_serp(keyword TEXT,collected_date TEXT,products_json TEXT,created_at TEXT,meta_json TEXT,source TEXT);
                CREATE TABLE collector_requests(keyword TEXT);""")
            conn.execute("INSERT INTO client_keyword_product VALUES(1,1,'누룽지',?)", (url,))
            conn.execute("INSERT INTO client_analyses VALUES(1,1,?,?)", (url, json.dumps({"product_info": {"product_url": url, "product_name": "확인 누룽지", "brand": "확인 브랜드"}})))
            conn.execute("INSERT INTO collected_serp VALUES('누룽지',date('now'),?,datetime('now'),NULL,'extension')",
                         (json.dumps([{"rank": i, "productId": str(1000+i), "title": "누룽지 간식 간식", "link": f"https://smartstore.naver.com/test/products/{1000+i}"} for i in range(1, 21)]),))
        products = self.api.get("/api/seo/client/1/products").json()["data"]
        self.assertEqual(products[0]["current_values"]["product_name"], "확인 누룽지")
        self.assertIsNone(products[0]["current_values"]["tags"])
        data = self.generate(extra={"current_values": products[0]["current_values"]}, real_evidence=True).json()["data"]
        self.assertEqual(data["evidence"]["coverage"], 20)
        self.assertFalse(data["evidence"]["verified_top20"])
        self.assertEqual(next(x for x in data["evidence"]["common_terms"] if x["term"] == "간식")["count"], 20)
        saved = self.api.post("/api/seo/save-to-client", json={"client_id": 1, "keyword": data["keyword"],
            "product_url": url, "generation_id": data["generation_id"], "reviewed": True,
            "decisions": {key: "adopt" for key in seo.seo_review.FIELDS}}).json()
        self.assertTrue(saved["success"])
        original = self.api.get("/api/seo/client/1/saved").json()["data"][0]["review"]["original"]
        self.assertEqual(original["evidence"]["coverage"], 20)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM collector_requests").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
