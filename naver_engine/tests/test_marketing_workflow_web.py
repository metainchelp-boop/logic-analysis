"""계정·수치판별 전략과 계획 승인. 가짜 외부연결도 실행하지 않는다."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from naver_engine.tests import test_report_enrichment_web as TE
from naver_engine.tests import test_web as TW, test_report_accounts_web as TAW
from naver_engine import report_views as RV


class MarketingWorkflowWebTest(unittest.TestCase):
    setUp = TE.ReportEnrichmentWebTest.setUp
    call = TE.ReportEnrichmentWebTest.call
    get = TE.ReportEnrichmentWebTest.get
    seed_report = TE.ReportEnrichmentWebTest.seed_report
    prepare = TE.ReportEnrichmentWebTest.prepare
    detail = TE.ReportEnrichmentWebTest.detail

    def strategy(self, action, version=0, actor=100, **extra):
        body = {"report_id": 1, "account_key": self.key,
                "revision_fingerprint": self.payload["revision_fingerprint"],
                "expected_version": version, "action": action, **extra}
        return self.call("POST", "/reports/strategy", self.signer.issue(actor, self.clock.now()), body=body)

    def test_strategy_requires_explicit_generation_and_exact_approval(self):
        self.prepare()
        original = deepcopy(self.store.report_snapshot_detail(1))
        strategy = self.detail()[1]["marketing_strategy"]
        self.assertEqual((strategy["version"], strategy["state"], strategy["document"]), (0, "empty", None))
        self.assertFalse(strategy["provider_status"]["configured"])
        status, draft, _, _ = self.strategy("generate")
        self.assertEqual(status, 200, draft)
        self.assertEqual((draft["version"], draft["state"], draft["source"], draft["shared"]), (1, "draft", "rule_based", None))
        status, approved, _, _ = self.strategy("approve", 1)
        self.assertEqual(status, 200, approved)
        self.assertEqual(approved["shared"]["metadata"]["account_key"], self.key)
        self.assertEqual(approved["shared"]["document"], draft["document"])
        self.assertEqual(self.detail("company")[1]["marketing_strategy"]["version"], 0)
        self.assertEqual(self.store.report_snapshot_detail(1), original)

    def test_explicit_fake_claude_result_can_be_stored_and_approved_without_provider_activation(self):
        from naver_engine import marketing_strategy as STR
        self.prepare()
        original = deepcopy(self.store.report_snapshot_detail(1))
        selected = RV._account_payload(self.payload, self.key)
        calls = []
        def provider(context):
            calls.append(context)
            return {**STR.document_template(), "diagnosis": "관측: {{metric:spend.current}}"}
        generated = STR.generate(selected, provider=provider)
        self.assertEqual(generated["source"], "claude")
        # A future trusted worker must pass the same bounded storage contract. This
        # test injects a synthetic result; no HTTP route or default provider is enabled.
        with self.store._tx() as connection:
            _, _, metadata = self.store._report_notes_scope(connection, 1, self.key,
                self.payload["revision_fingerprint"])
            metadata = {**metadata, "strategy_version": 1}
            identity = f"1:{self.key}"
            current = self.store._approval_head(connection, "report-strategy", identity, metadata)
            draft = self.store._save_approval(connection, "report-strategy", identity, metadata,
                current, generated["document"], generated["source"], 100,
                self.clock.now().isoformat(), "save")
        self.assertEqual((draft["source"], draft["state"]), ("claude", "draft"))
        status, approved, _, _ = self.strategy("approve", 1)
        self.assertEqual(status, 200, approved)
        self.assertEqual(approved["shared"]["source"], "claude")
        self.assertEqual(self.detail()[1]["marketing_strategy"]["shared"], approved["shared"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(approved["provider_status"]["paid_calls"], 0)
        self.assertEqual(self.store.report_snapshot_detail(1), original)

    def test_sales_scope_cannot_read_strategy_or_write_plans_and_approvals(self):
        self.prepare()
        self.clock.advance(1)
        person = {**TAW.TA.emp(200, "합성 영업", 11, management=False),
                  "is_sales": True, "naver_sales_view": True}
        org = TAW.TA.org_body(self.clock.now(), extra_people=[person])
        org["sales_contracts"] = [{"possibility_id": 11, "seller_emp_idx": 200}]
        self.store.record_org(org, self.clock.now())
        for path, query in (("/automation", ""), ("/reports/detail", "report_id=1&account_key="+self.key)):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, query, actor=200)[0], 403)
        for action in ("generate", "save", "approve"):
            extra = {"document": {}} if action == "save" else {}
            with self.subTest(action=action):
                self.assertEqual(self.strategy(action, actor=200, **extra)[0], 403)
        self.assertEqual(self.plan(actor=200)[0], 403)
        self.assertEqual(self.plan("approve", actor=200)[0], 403)
        self.assertEqual(self.store.report_strategy(1, self.key, self.payload["revision_fingerprint"])["version"], 0)
        self.assertEqual(self.store.automation_plan(11, self.key)["version"], 0)

    def test_new_strategy_projection_preserves_refresh_and_conversion_response(self):
        self.prepare()
        frozen = deepcopy(self.store.report_snapshot_detail(1))
        state = {"validation": {"status": "pending", "last_checked_at": None},
                 "source_collected_at": self.clock.now().isoformat(),
                 "conversion_response": {"status": "complete", "received_account_days": 7,
                                         "expected_account_days": 7}}
        with patch.object(type(self.store), "report_refresh_states", return_value={"accounts": {str(TW.A): state}}):
            before = self.detail()[1]
            self.assertIn("conversion_response", before["refresh"])
            self.assertEqual(self.strategy("generate")[0], 200)
            after = self.detail()[1]
        for field in ("payload", "validation", "refresh", "collection_status", "scope"):
            self.assertEqual(before[field], after[field], field)
        self.assertEqual(self.store.report_snapshot_detail(1), frozen)

    def plan(self, action="save", version=0, actor=100, **extra):
        body = {"possibility_id": 11, "account_key": self.key, "expected_version": version, "action": action}
        if action == "save":
            body["plan"] = {"goal": "clicks", "target_value": 100, "daily_spend_cap": 10000,
                            "absolute_bid_cap": 500, "experiment_days": 7, "loss_cap": 20000, "notes": "직원 검토 계획"}
        body.update(extra)
        return self.call("POST", "/automation/plans", self.signer.issue(actor, self.clock.now()), body=body)

    def auto(self, actor=100, query=None):
        return self.get("/automation", query if query is not None else "possibility_id=11&account_key="+self.key, actor=actor)

    def test_automation_view_is_read_only_and_plan_approval_never_starts_ads(self):
        self.prepare()
        self.app._write = lambda fn: self.fail("GET은 쓰지 않아야 함")
        status, listing, _, raw = self.auto(query="")
        self.assertEqual(status, 200, listing)
        self.assertEqual([r["possibility_id"] for r in listing["accounts"]], [11])
        self.assertIsNone(listing["selection"])
        self.assertNotIn(str(TW.A).encode(), raw)
        self.assertEqual(self.auto()[1]["setup_checks"]["counts"]["attention"], 0)
        self.app._write = lambda fn: fn(self.store)
        draft = self.plan()[1]
        self.assertEqual((draft["version"], draft["state"]), (1, "draft"))
        status, approved, _, _ = self.plan("approve", 1)
        self.assertEqual(status, 200, approved)
        self.assertEqual((approved["state"], approved["execution_status"], approved["experiment_results"]), ("approved", "not_enabled", None))
        selected = self.auto()[1]
        self.assertFalse(selected["execution_enabled"])
        self.assertEqual(selected["plan"]["version"], 2)

    def test_strategy_edits_withdraw_shared_copy_and_preserve_numeric_staff_input(self):
        self.prepare()
        generated = self.strategy("generate")[1]
        self.assertEqual(self.strategy("approve", 1)[0], 200)
        document = {**generated["document"], "shared_comment": "직원 검토: 주간 예산 70,000원 범위의 계획입니다."}
        status, edited, _, _ = self.strategy("save", 2, document=document)
        self.assertEqual(status, 200, edited)
        self.assertEqual((edited["source"], edited["state"], edited["shared"]), ("staff", "draft", None))
        self.assertEqual(self.detail()[1]["marketing_strategy"]["document"], document)

    def test_exact_version_scope_and_fingerprint_fail_closed(self):
        self.prepare()
        self.assertEqual(self.strategy("generate")[0], 200)
        for extra, actor, expected in [({}, 101, 404), ({"account_key": "b"*64}, 100, 404),
                ({"revision_fingerprint": "b"*64}, 100, 409), ({"expected_version": True}, 100, 400),
                ({"unexpected": True}, 100, 400), ({}, 100, 409)]:
            self.assertEqual(self.strategy("generate", actor=actor, **extra)[0], expected)
        self.assertEqual(self.plan()[0], 200)
        self.assertEqual(self.plan()[0], 409)
        self.assertEqual(self.plan(actor=101)[0], 404)
        self.assertEqual(self.auto(actor=101)[:2], (404, TW.WEB.NOT_VISIBLE))
        self.assertEqual(self.plan(account_key="c"*64)[0], 404)

    def test_old_or_dirty_report_cannot_approve_strategy(self):
        self.prepare()
        self.assertEqual(self.strategy("generate")[0], 200)
        self.store._conn.execute("INSERT INTO naver_auto_report_dirty VALUES(11,?,?,1)",
                                (self.payload["period_key"], self.clock.now().isoformat()))
        self.assertEqual(self.strategy("approve", 1)[0], 409)
        self.seed_report(2)
        self.assertFalse(self.detail()[1]["marketing_strategy"]["can_edit"])
        self.assertEqual(self.strategy("save", 1, document=self.detail()[1]["marketing_strategy"]["document"])[0], 409)

    def changed_writer(self):
        def changed(fn):
            self.clock.advance(1)
            self.store.record_org(TAW.TA.org_body(self.clock.now(), owners=[TAW.TA.owner(11, 101), TAW.TA.owner(12, 101)]), self.clock.now())
            return fn(self.store)
        self.app._write = changed

    def test_changed_owner_is_rechecked_inside_strategy_writer(self):
        self.prepare()
        self.changed_writer()
        self.assertEqual(self.strategy("generate")[0], 404)
        self.assertEqual(self.store.report_strategy(1, self.key, self.payload["revision_fingerprint"])["version"], 0)

    def test_changed_owner_is_rechecked_inside_plan_writer(self):
        self.prepare()
        self.changed_writer()
        self.assertEqual(self.plan()[0], 404)
        self.assertEqual(self.store.automation_plan(11, self.key)["version"], 0)

    def test_caps_increase_requires_lead_even_after_intermediate_draft(self):
        self.prepare()
        self.assertEqual(self.plan()[0], 200)
        self.assertEqual(self.plan("approve", 1)[0], 200)
        increased = {**self.store.automation_plan(11, self.key)["plan"], "daily_spend_cap": 20000}
        self.assertEqual(self.plan(version=2, plan=increased)[0], 200)
        self.assertTrue(self.auto()[1]["plan"]["approval_requires_lead"])
        self.assertFalse(self.auto()[1]["can_approve"])
        self.assertEqual(self.plan("approve", 3)[0], 409)
        self.assertEqual(self.plan(version=3, plan=increased)[0], 200)
        self.assertEqual(self.plan("approve", 4)[0], 409)
        self.assertEqual(self.plan("approve", 4, actor=0)[0], 200)

    def test_plan_validation_caps_and_contract_stage(self):
        self.prepare()
        base = {"goal": "clicks", "target_value": 100, "daily_spend_cap": 10000, "absolute_bid_cap": 500,
                "experiment_days": 7, "loss_cap": 20000, "notes": ""}
        for changed in ({"goal": {}}, {"daily_spend_cap": -1}, {"absolute_bid_cap": True},
                        {"experiment_days": 1}, {"notes": "<script>"}, {"unexpected": 1}, {"target_value": 10**400}):
            self.assertEqual(self.plan(plan={**base, **changed})[0], 409)
        self.assertEqual(self.plan(plan={**base, "absolute_bid_cap": None})[0], 200)
        self.assertEqual(self.plan("approve", 1)[0], 409)
        catalog = self.store.account_catalog()
        items = [{**r, "stage": "홀딩"} if r["possibility_id"] == 11 else r for r in catalog["items"]]
        self.clock.advance(1)
        self.store.record_account_catalog({"generated_at": self.clock.now().isoformat(), "total": len(items), "complete": True, "items": items},
            [TW.E.NaverIdRow(r["possibility_id"], r["vendor"], r["customer_id_raw"], r["ad_account_no_raw"]) for r in catalog["ids"]], self.clock.now())
        status, held, _, _ = self.auto()
        self.assertEqual(status, 200, held)
        self.assertTrue(held["can_edit"])
        self.assertFalse(held["can_approve"])
        self.assertEqual(self.plan(version=1)[0], 200)
        self.assertEqual(self.plan("approve", 2)[0], 409)

    def test_canonical_holding_is_draft_only_and_expired_stage_is_read_only(self):
        self.prepare()
        for stage, editable in (("홀딩중", True), (" 홀딩 중 ", True), ("계약만료", False)):
            with self.subTest(stage=stage):
                catalog = self.store.account_catalog()
                items = [{**row, "stage": stage} if row["possibility_id"] == 11 else row
                         for row in catalog["items"]]
                self.clock.advance(1)
                self.store.record_account_catalog({"generated_at": self.clock.now().isoformat(),
                    "total": len(items), "complete": True, "items": items},
                    [TW.E.NaverIdRow(row["possibility_id"], row["vendor"], row["customer_id_raw"], row["ad_account_no_raw"])
                     for row in catalog["ids"]], self.clock.now())
                status, selected, _, _ = self.auto()
                self.assertEqual(status, 200, selected)
                self.assertEqual(selected["can_edit"], editable)
                self.assertFalse(selected["can_approve"])
                version = selected["plan"]["version"]
                self.assertEqual(self.plan(version=version)[0], 200 if editable else 409)
                self.assertEqual(self.plan("approve", version+1 if editable else version)[0], 409)


if __name__ == "__main__":
    unittest.main()
