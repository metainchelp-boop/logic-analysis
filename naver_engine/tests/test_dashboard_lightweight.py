"""실제 HTTP 월간 집계는 현재 계정 범위를 보존하고 목록 전용 상세 계산을 하지 않는다."""
from contextlib import ExitStack
from datetime import timedelta
import unittest
from unittest.mock import patch

from naver_engine import inventory as I, naver_read as N, store as S
from naver_engine.tests import test_accounts_match_reuse as TM, test_alerts as TA


class DashboardLightweightTest(unittest.TestCase):
    def setUp(self):
        self.fixture = TM.AccountsMatchReuseTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store, self.clock = self.fixture.store, self.fixture.clock
        self.full_board = I.board

    def get(self, actor=0, selection="all", *, narrowed=False):
        return self.fixture.call("/dashboard?selection=" + selection, actor, narrowed=narrowed)

    def legacy_get(self, actor=0, selection="all", *, narrowed=False):
        def source(*args, **kwargs):
            kwargs.pop("_dashboard_only", None)
            return self.full_board(*args, **kwargs)
        with patch.object(I, "board", side_effect=source):
            return self.get(actor, selection, narrowed=narrowed)

    def assert_legacy_parity(self):
        for actor, selection, narrowed in ((0, "all", False), (0, "person:100", False),
                (0, "team:11", False), (0, "unassigned", False), (100, "all", False),
                (100, "me", False), (101, "all", False), (0, "all", True), (100, "all", True)):
            with self.subTest(actor=actor, selection=selection, narrowed=narrowed):
                expected = self.legacy_get(actor, selection, narrowed=narrowed)
                actual = self.get(actor, selection, narrowed=narrowed)
                self.assertEqual(actual[0], 404 if selection.startswith("team:") else 200, actual)
                self.assertEqual(actual, expected)

    def test_real_http_does_not_read_structure_absent_or_managed_coverage(self):
        with ExitStack() as stack:
            for method in ("structure_reason_summaries", "account_times"):
                stack.enter_context(patch.object(S.Store, method,
                    side_effect=AssertionError("대시보드가 목록 전용 상세 계산을 시작했습니다: " + method)))
            stack.enter_context(patch.object(I, "_managed_coverage",
                side_effect=AssertionError("대시보드가 사용하지 않는 목록 업체 분모를 계산했습니다")))
            for actor in (0, 100, 101):
                status, body = self.get(actor)
                self.assertEqual(status, 200, body)
                self.assertEqual(body["accounts"]["total"], 6 if actor == 0 else 1)

    def test_exact_legacy_http_results_for_owner_staff_and_selection(self):
        self.assert_legacy_parity()

    def test_hidden_unknown_and_changed_owner_keep_current_permission_rules(self):
        self.clock.advance(1)
        now = self.clock.now()
        self.store.record_org(TA.org_body(now, owners=[TA.owner(11, 101), TA.owner(12, 101),
            TA.owner(13, 100), TA.owner(14, 101)]), now)
        self.assertEqual(self.get(100)[1]["accounts"]["total"], 0)
        self.assertEqual(self.get(101)[1]["accounts"]["total"], 2)
        catalog = self.store.account_catalog()
        for flags in ({"stage_hidden": True}, {"stage_known": False}):
            items = [{**r, **flags} if r["possibility_id"] == 11 else r for r in catalog["items"]]
            self.store.record_account_catalog({"generated_at": now.isoformat(), "total": len(items),
                "complete": True, "items": items}, self.fixture.ids, now)
            self.assertEqual(self.get(101)[1]["accounts"]["total"], 1)
            self.assert_legacy_parity()

    def test_failed_catalog_and_absent_account_keep_existing_unknown_results(self):
        accounts = self.store.accounts()
        absent = accounts[0]["customer_id"]
        current = {r["customer_id"]: {"customerId": r["customer_id"], "adAccountNo": r["ad_account_no"],
                   "adAccountName": r["account_name"]} for r in accounts if r["customer_id"] != absent}
        self.store.record_accounts(N.ChildAccounts(current, {1: len(current)}, ()), self.clock.now())
        self.assertEqual(self.get(100)[1]["accounts"]["total"], 0)
        self.assert_legacy_parity()
        self.store.record_account_catalog_failure(self.clock.now(), "CATALOG_FAILED")
        self.assertFalse(self.get()[1]["ready"])
        self.assert_legacy_parity()

    def test_monthly_and_daily_metrics_keep_cost_company_denominator_and_delivery(self):
        # 월간 수집을 시작하지 않고 실제 저장 원천 읽기 계약에 합성 완결 자료를 놓는다.
        now = self.clock.now()
        start, end = now.date().replace(day=1), now.date()-timedelta(days=1)
        first, second = [r["customer_id"] for r in self.store.accounts()[:2]]
        for cid, cost in ((first, 1000), (second, 2000)):
            self.store._conn.execute("""INSERT INTO naver_auto_monthly_check
                (customer_id,period_start,period_end,snapshot_at,checked_at,status,next_try_at,
                 imp,clk,spend,conversion_value,enabled_campaigns,campaign_count)
                VALUES(?,?,?,?,?,'ok',?,?,?,?,?,1,1)""",
                (cid, str(start), str(end), now.isoformat(), now.isoformat(), now.isoformat(),
                 100, 10, cost, cost*3))
        for day_offset in range((end-start).days+1):
            day = start+timedelta(days=day_offset)
            self.store._conn.execute("""INSERT INTO naver_auto_daily_performance
                (customer_id,day,possibility_id,matching_fingerprint,basic_complete,conversion_complete,conversion_attempts,
                 imp,clk,spend,conversion_value,checked_at,source_at,campaign_fingerprint)
                VALUES(?,?,11,'synthetic',1,1,0,100,10,100,0,?,?,'synthetic')""",
                (first, str(day), now.isoformat(), now.isoformat()))
        # 실제 Store가 반환하는 전일 자료가 있어야 집행 상태를 월간 비용과 별개로 판정한다.
        self.store.synchronize_management(now)
        state = self.store.management_states()[first]
        self.store._conn.execute("""INSERT INTO naver_auto_performance_job
            (job_key,customer_id,kind,cycle_day,period_start,period_end,snapshot_at,catalog_at,
             stage_revision,possibility_id,matching_fingerprint,status,checked_at,next_try_at,attempts,generation)
            VALUES('synthetic-dashboard',?,'daily',?,?,?,?,?,?,11,'synthetic','ok',?,?,0,?)""",
            (first, str(now.date()), str(end), str(end), now.isoformat(), now.isoformat(),
             state["stage_revision"], now.isoformat(), now.isoformat(), now.isoformat()))
        result = self.get()[1]
        days = (end-start).days+1
        self.assertEqual(result["totals"]["spend"], days*100+2000)
        self.assertEqual(result["advertisers"], {"total": 2, "complete": 2, "unknown": 0})
        self.assertEqual(result["delivery"], {"active": 1, "inactive": 0, "unknown": 5})
        self.assert_legacy_parity()
        # 새 연결의 이전 업체 일별 원천을 현재 업체 평균에 넣지 않는다.
        self.store._conn.execute("UPDATE naver_auto_daily_performance SET possibility_id=999 WHERE customer_id=?",
                                 (first,))
        changed = self.get()[1]
        self.assertEqual(changed["totals"]["spend"], 2000)
        self.assertEqual(changed["advertisers"], {"total": 2, "complete": 1, "unknown": 1})
        self.assert_legacy_parity()

    def test_other_staff_and_invalid_selection_still_fail_before_showing_metrics(self):
        for selection in ("person:101", "person:99999", "team:11", "team:99999"):
            with self.subTest(selection=selection):
                self.assertEqual(self.get(100, selection)[0], 404)
        self.assertEqual(self.get(100, "unassigned")[0], 400)


if __name__ == "__main__":
    unittest.main()
