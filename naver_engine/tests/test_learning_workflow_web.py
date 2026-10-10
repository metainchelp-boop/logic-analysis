"""Real authenticated learning workflow with synthetic SQLite and fake Claude only."""
from copy import deepcopy
from datetime import date, timedelta
import json
import unittest
from unittest.mock import patch

from naver_engine import marketing_strategy as STR, store as S, reporting as R, report_views as RV
from naver_engine.tests.test_marketing_workflow_web import MarketingWorkflowWebTest as Workflow
from naver_engine.tests.test_report_revisions import ReportAdapter


class LearningWorkflowWebTest(unittest.TestCase):
    setUp = Workflow.setUp
    call = Workflow.call
    get = Workflow.get
    seed_report = Workflow.seed_report
    prepare = Workflow.prepare
    detail = Workflow.detail
    auto = Workflow.auto
    plan = Workflow.plan
    strategy = Workflow.strategy

    def learning(self, action="capture", *, actor=100, **values):
        body = {"possibility_id": 11, "account_key": self.key, "action": action, **values}
        return self.call("POST", "/automation/learning", self.signer.issue(actor, self.clock.now()), body=body)

    def provider(self, hook=None):
        seen = []
        def fake(context):
            seen.append(deepcopy(context))
            self.assertFalse(self.store._conn.in_transaction, "Provider must run outside writer transaction")
            if hook:
                hook()
            return {**STR.document_template(), "diagnosis": "관측 {{metric:spend.current}}를 검토합니다."}
        fake.model = "offline-test-model"
        fake.maximum_call_microusd = 100
        fake.monthly_budget_microusd = 200
        self.app._strategy_provider = fake
        return seen

    def reviewed(self):
        self.assertEqual(self.learning()[0], 200)
        item = self.auto()[1]["learning_assets"]["items"][0]
        response = self.learning("review", asset_id=item["asset_id"], expected_version=item["version"])
        self.assertEqual(response[0], 200, response[1])
        return response[1]

    def test_capture_is_idempotent_account_scoped_and_keeps_source_immutable(self):
        self.prepare()
        original = deepcopy(self.store.report_snapshot_detail(1))
        for _ in range(2):
            status, result, *_ = self.learning()
            self.assertEqual(status, 200, result)
            self.assertEqual(len(result["items"]), 1)
            self.assertEqual(result["items"][0]["document"]["evidence"]["spend"], 700)
            self.assertFalse(result["items"][0]["document"]["evidence"]["lag_mature"])
        self.assertEqual(self.store.report_snapshot_detail(1), original)
        self.assertIn(self.learning(actor=101)[0], (403, 404))
        self.assertIn(self.learning(account_key="f"*64)[0], (403, 404))

    def test_manual_source_ref_forgery_and_stale_review_are_refused(self):
        self.prepare()
        item = self.reviewed()
        document = deepcopy(item["document"])
        self.assertEqual(self.learning("save", asset_id="fake-report", expected_version=0, document=document)[0], 409)
        document["source_refs"] = {}
        for reserved in ("report-999", "plan-999"):
            self.assertEqual(self.learning("save", asset_id=reserved, expected_version=0, document=document)[0], 409)
        self.assertEqual(self.learning("save", asset_id=item["asset_id"], expected_version=1, document=document)[0], 409)
        self.assertEqual(self.learning("save", asset_id=item["asset_id"], expected_version=item["version"], document=document)[0], 409)
        self.assertEqual(self.learning("save", asset_id="manual", expected_version=0, document=document)[0], 200)
        self.assertEqual(self.auto()[1]["learning_assets"]["counts"], {"draft": 1, "reviewed": 1, "rejected": 0})

    def test_plan_history_is_proposed_and_never_claims_ad_execution(self):
        self.prepare()
        self.assertEqual(self.plan()[0], 200)
        self.assertEqual(self.plan("approve", 1)[0], 200)
        items = self.auto()[1]["learning_assets"]["items"]
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertEqual(item["document"]["kind"], "setting_change")
            self.assertEqual(item["document"]["evidence"]["execution"], "planned")
            self.assertFalse(item["assessment"]["causal_claim"])

    def test_claude_uses_reviewed_cases_and_persists_exact_provenance(self):
        self.prepare()
        reviewed = self.reviewed()
        seen = self.provider()
        status, result, *_ = self.strategy("generate_claude")
        self.assertEqual(status, 200, result)
        self.assertEqual((result["source"], result["state"]), ("claude", "draft"))
        self.assertEqual(len(seen), 1)
        wire = json.dumps(seen)
        self.assertNotIn(self.key, wire)
        self.assertNotIn(reviewed["asset_id"], wire)
        self.assertEqual(len(seen[0]["learning"]["cases"]), 1)
        current = self.detail()[1]["marketing_strategy"]
        self.assertEqual(current["learning_provenance"]["case_refs"], [{"asset_id": reviewed["asset_id"], "version": 2}])
        self.assertEqual(self.strategy("approve", 1)[0], 200)
        self.assertTrue(self.detail()[1]["marketing_strategy"]["references_current"])
        self.assertIsNotNone(self.detail()[1]["marketing_strategy"]["shared"])

    def test_changed_case_hides_shared_strategy_and_blocks_reapproval(self):
        self.prepare()
        reviewed = self.reviewed()
        document = {**reviewed["document"], "source_refs": {}}
        self.assertEqual(self.learning("save", asset_id="manual-case", expected_version=0, document=document)[0], 200)
        self.assertEqual(self.learning("review", asset_id="manual-case", expected_version=1)[0], 200)
        self.provider()
        self.assertEqual(self.strategy("generate_claude")[0], 200)
        self.assertEqual(self.strategy("approve", 1)[0], 200)
        document = {**reviewed["document"], "source_refs": {}, "title": "검토 내용 정정"}
        self.assertEqual(self.learning("save", asset_id="manual-case", expected_version=2, document=document)[0], 200)
        strategy = self.detail()[1]["marketing_strategy"]
        self.assertFalse(strategy["references_current"])
        self.assertIsNone(strategy["shared"])

    def test_changes_during_provider_are_rejected_without_overwriting_existing_strategy(self):
        self.prepare()
        self.reviewed()
        seen = self.provider(lambda: self.plan())
        self.assertEqual(self.strategy("generate_claude")[0], 409)
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.detail()[1]["marketing_strategy"]["version"], 0)

    def test_monthly_reservations_survive_failure_and_stop_calls_at_limit(self):
        self.prepare()
        seen = self.provider(lambda: (_ for _ in ()).throw(RuntimeError("PRIVATE PROVIDER ERROR")))
        for _ in range(2):
            status, body, *_ = self.strategy("generate_claude")
            self.assertEqual(status, 503)
            self.assertNotIn("PRIVATE", str(body))
        self.assertEqual(self.strategy("generate_claude")[0], 409)
        self.assertEqual(len(seen), 2)
        self.assertEqual(self.detail()[1]["marketing_strategy"]["version"], 0)

    def test_disabled_provider_does_not_reserve_cost_or_generate(self):
        self.prepare()
        self.assertEqual(self.strategy("generate_claude")[0], 503)
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM naver_auto_meta WHERE key LIKE 'learning-call:%'").fetchone()[0], 0)

    def test_corrupt_budget_is_not_an_allowance(self):
        self.prepare()
        seen = self.provider()
        month = self.clock.now().astimezone(S.KST).strftime("%Y-%m")
        self.store._conn.execute("INSERT INTO naver_auto_meta VALUES(?,?)", ("learning-budget:"+month, "-100"))
        self.assertEqual(self.strategy("generate_claude")[0], 503)
        self.assertEqual(seen, [])


class LearningCapturePipelineTest(unittest.TestCase):
    def test_new_report_records_observation_and_does_not_rewrite_it(self):
        store = ReportAdapter()
        self.addCleanup(store._conn.close)
        period = R.period("weekly", date(2026, 9, 28))
        store.seed(period.start, period.end)
        store.generate_reports(store.now)
        key = RV.account_key(101)
        rows = store.learning_assets(11, key)["items"]
        self.assertTrue(rows)
        self.assertTrue(all(r["author"]["actor"] is None for r in rows))
        count = len(rows)
        store.generate_reports(store.now)
        self.assertEqual(len(store.learning_assets(11, key)["items"]), count)

    def test_learning_failure_defers_capture_without_stopping_report(self):
        store = ReportAdapter()
        self.addCleanup(store._conn.close)
        period = R.period("weekly", date(2026, 9, 28))
        store.seed(period.start, period.end)
        with patch.object(store, "_capture_learning_report", side_effect=S.StoreRefused("합성 편입 오류")):
            store.generate_reports(store.now)
        self.assertTrue(store.report_snapshots())
        self.assertGreater(store._conn.execute("SELECT COUNT(*) FROM naver_auto_meta WHERE key LIKE 'learning-capture-pending:%'").fetchone()[0], 0)


# Imported fixture class must not be rediscovered as this module's test suite.
del Workflow
