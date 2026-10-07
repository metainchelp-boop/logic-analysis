"""같은 HTTP 요청의 정책 공유와 계정별 기간 묶음 조회. 실제 메모리 Store, 외부 송신 없음."""
from datetime import timedelta
import socket
import unittest
from unittest.mock import patch

from naver_engine import management_store as MS, store as S
from naver_engine.tests._performance_checks_fd73 import performance_checks as reference
from naver_engine.tests import test_accounts_match_reuse as TM
from naver_engine.tests.test_catalog_links import make_fixture


class CollectionProjectionTest(unittest.TestCase):
    def setUp(self):
        for name in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, name, side_effect=AssertionError("외부 송신 금지"))
            guard.start()
            self.addCleanup(guard.stop)
        fixture = make_fixture(accounts=4, managed=4, campaigns=0)
        self.store, self.clock = fixture.store, fixture.clock
        self.addCleanup(self.store.close)
        self.now = self.clock.now()
        self.store.synchronize_management(self.now)
        self.states = self.store.management_states()
        self.ids = sorted(self.states)
        self.end = self.now.date()-timedelta(days=1)
        for index, cid in enumerate(self.ids):
            start = self.end-timedelta(days=6 if index >= 2 else 0)
            self.job(cid, start, self.end, kind="weekly" if index >= 2 else "daily")
            for ago in range((self.end-start).days+1):
                self.day(cid, start+timedelta(days=ago), spend=(index+1)*100)

    def insert(self, table, row):
        self.store._conn.execute("INSERT INTO " + table + " (" + ",".join(row) + ") VALUES (" +
                                 ",".join("?" for _ in row) + ")", tuple(row.values()))

    def job(self, cid, start, end, *, kind="daily", key=None, **changes):
        state = self.states[cid]
        at = self.now.isoformat()
        self.insert("naver_auto_performance_job", {"job_key": key or str(cid), "customer_id": cid,
            "kind": kind, "cycle_day": str(self.now.date()), "period_start": str(start), "period_end": str(end),
            "snapshot_at": at, "catalog_at": at, "stage_revision": state["stage_revision"],
            "possibility_id": state["possibility_id"], "matching_fingerprint": "synthetic",
            "status": "ok", "checked_at": at, "next_try_at": at, "attempts": 0, "generation": at,
            "bizmoney": 1000, "bizmoney_at": at, **changes})

    def day(self, cid, day, *, spend=100, **changes):
        at = self.now.isoformat()
        self.insert("naver_auto_daily_performance", {"customer_id": cid, "day": str(day),
            "possibility_id": self.states[cid]["possibility_id"], "matching_fingerprint": "synthetic",
            "basic_complete": 1, "conversion_complete": 1, "conversion_attempts": 0,
            "imp": 10, "clk": 1, "spend": spend, "conversion_value": 0,
            "checked_at": at, "source_at": at, "campaign_fingerprint": "synthetic", **changes})

    def parity(self):
        expected = reference(self.store, self.now)
        actual = self.store.performance_checks(self.now)
        self.assertEqual(actual, expected)
        return actual

    def test_same_period_reads_are_batched_and_results_equal_account_by_account_reference(self):
        with patch.object(self.store, "daily_performance", wraps=self.store.daily_performance) as read:
            result = self.store.performance_checks(self.now)
        self.assertEqual(read.call_count, 2)
        self.assertEqual([set(call.args[0]) for call in read.call_args_list],
                         [set(self.ids[:2]), set(self.ids[2:])])
        self.assertEqual([result[cid]["spend"] for cid in self.ids], [100, 200, 2100, 2800])
        self.assertEqual(result, reference(self.store, self.now))

    def test_missing_incomplete_or_other_attribution_never_turns_into_zero_or_cross_account_sum(self):
        for sql in ("DELETE FROM naver_auto_daily_performance WHERE customer_id=? AND day=?",
                    "UPDATE naver_auto_daily_performance SET basic_complete=0 WHERE customer_id=? AND day=?",
                    "UPDATE naver_auto_daily_performance SET possibility_id=999 WHERE customer_id=? AND day=?"):
            with self.subTest(sql=sql):
                self.store._conn.execute("SAVEPOINT changed")
                try:
                    self.store._conn.execute(sql, (self.ids[2], str(self.end)))
                    result = self.parity()
                    self.assertIsNone(result[self.ids[2]]["spend"])
                    self.assertEqual(result[self.ids[3]]["spend"], 2800)
                    self.assertTrue(result[self.ids[2]]["activity_observed"])
                finally:
                    self.store._conn.execute("ROLLBACK TO changed")
                    self.store._conn.execute("RELEASE changed")

    def test_failed_recheck_keeps_success_period_balances_and_source_rechecked_time(self):
        old = (self.now-timedelta(hours=2)).isoformat()
        before = (self.now-timedelta(hours=4)).isoformat()
        self.store._conn.execute("""UPDATE naver_auto_performance_job SET status='retry',error_code='NETWORK',
            last_success_at=?,last_bizmoney=1000,last_bizmoney_at=?,previous_bizmoney=0,previous_bizmoney_at=?,
            bizmoney=NULL,bizmoney_at=NULL WHERE customer_id=?""", (old, old, before, self.ids[0]))
        self.store._conn.execute("UPDATE naver_auto_daily_performance SET checked_at=? WHERE customer_id=?",
                                 (old, self.ids[0]))
        result = self.parity()[self.ids[0]]
        self.assertEqual((result["status"], result["error_code"], result["spend"]), ("retry", "NETWORK", 100))
        self.assertEqual((result["bizmoney"], result["previous_bizmoney"], result["bizmoney_change"]), (1000, 0, 1000))
        self.assertEqual((result["last_success_at"], result["source_rechecked_at"]), (old, old))
        self.assertEqual((result["period_start"], result["period_end"]), (str(self.end), str(self.end)))

    def test_success_keeps_its_old_period_when_latest_attempt_has_different_period(self):
        earlier = self.end-timedelta(days=1)
        self.day(self.ids[0], earlier, spend=75)
        self.store._conn.execute("UPDATE naver_auto_performance_job SET period_start=?,period_end=?,checked_at=? WHERE customer_id=?",
            (str(earlier), str(earlier), (self.now-timedelta(hours=1)).isoformat(), self.ids[0]))
        self.job(self.ids[0], self.end, self.end, key="latest-failed", status="retry", error_code="SERVER")
        result = self.parity()[self.ids[0]]
        self.assertEqual((result["period_start"], result["period_end"], result["spend"]), (str(earlier), str(earlier), 75))
        self.assertEqual((result["status"], result["error_code"]), ("retry", "SERVER"))

    def test_missing_source_timestamp_keeps_metrics_but_not_source_rechecked_time(self):
        self.store._conn.execute("UPDATE naver_auto_daily_performance SET checked_at='' WHERE customer_id=? AND day=?",
                                 (self.ids[2], str(self.end)))
        result = self.parity()[self.ids[2]]
        self.assertEqual(result["spend"], 2100)
        self.assertIsNone(result["source_rechecked_at"])

    def test_stale_catalog_keeps_historical_values_and_withholds_current_policy(self):
        self.store.record_account_catalog_failure(self.now, "CATALOG_FAILED")
        result = self.parity()
        self.assertTrue(all(item["cadence"] == "blocked" and item["stale"] for item in result.values()))
        self.assertEqual([result[cid]["spend"] for cid in self.ids], [100, 200, 2100, 2800])

    def test_many_accounts_keep_each_batch_bounded_and_equal_independent_reference(self):
        fixture = make_fixture(accounts=401, managed=401, campaigns=0, history_days=1)
        store = fixture.store
        self.addCleanup(store.close)
        now = fixture.clock.now()
        with patch.object(store, "daily_performance", wraps=store.daily_performance) as read:
            result = store.performance_checks(now)
        self.assertEqual(len(result), 401)
        self.assertEqual([len(call.args[0]) for call in read.call_args_list], [400, 1])
        self.assertEqual(result, reference(store, now))

    def test_no_success_does_not_start_any_daily_source_read(self):
        self.store._conn.execute("DELETE FROM naver_auto_performance_job")
        with patch.object(self.store, "daily_performance", side_effect=AssertionError("성공 기간이 없습니다")):
            result = self.parity()
        self.assertTrue(all(item["spend"] is None and "activity_observed" not in item for item in result.values()))

    def test_two_accounts_with_same_advertiser_keep_separate_source_totals(self):
        policies = MS.snapshot(self.store, self.now)
        policies[self.ids[1]] = {**policies[self.ids[1]], "possibility_id": policies[self.ids[0]]["possibility_id"]}
        pid = policies[self.ids[0]]["possibility_id"]
        for table in ("naver_auto_performance_job", "naver_auto_daily_performance"):
            self.store._conn.execute("UPDATE " + table + " SET possibility_id=? WHERE customer_id=?", (pid, self.ids[1]))
        with patch.object(MS, "snapshot", return_value=policies):
            result = self.parity()
        self.assertEqual([result[cid]["spend"] for cid in self.ids[:2]], [100, 200])

    def test_native_store_override_keeps_old_call_shape_without_extra_policy_work(self):
        with patch.object(self.store, "structure_reason_summaries", side_effect=lambda ids, now: {"structure": "custom"}), \
                patch.object(self.store, "performance_checks", side_effect=lambda now: {"performance": "custom"}), \
                patch.object(MS, "snapshot", side_effect=AssertionError("사용자 정의 조회의 정책을 추가로 만들지 않습니다")):
            self.assertEqual(self.store.inventory_collection_summaries(self.ids, self.now),
                             ({"structure": "custom"}, {"performance": "custom"}))


class AccountPolicyShareTest(unittest.TestCase):
    def setUp(self):
        self.fixture = TM.AccountsMatchReuseTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_actual_http_builds_current_policy_once_for_both_account_projections(self):
        with patch.object(MS, "snapshot", wraps=MS.snapshot) as policies:
            status, result = self.fixture.call("/accounts")
        self.assertEqual(status, 200)
        self.assertEqual(len(result["rows"]), 6)
        self.assertEqual(policies.call_count, 1)

    def test_each_new_http_request_rechecks_policy_and_current_owner(self):
        with patch.object(MS, "snapshot", wraps=MS.snapshot) as policies:
            self.assertEqual(self.fixture.call("/accounts", 100)[1]["total"], 1)
            self.fixture.clock.advance(1)
            from naver_engine.tests import test_alerts as TA
            now = self.fixture.clock.now()
            self.fixture.store.record_org(TA.org_body(now, owners=[TA.owner(11, 101), TA.owner(12, 101)]), now)
            self.assertEqual(self.fixture.call("/accounts", 100)[1]["total"], 0)
            self.assertEqual(policies.call_count, 2)

    def test_actual_http_payload_matches_separate_projection_for_each_scope_and_filter(self):
        for path, actor, narrowed in (("/accounts", 0, False), ("/accounts", 100, False),
                ("/accounts", 101, False), ("/accounts", 0, True),
                ("/accounts?selection=person:100", 0, False),
                ("/accounts?mapping=matched", 0, False), ("/accounts?view=lost", 100, False),
                ("/accounts?view=balance_known", 0, False)):
            with self.subTest(path=path, actor=actor, narrowed=narrowed):
                with patch.object(S.Store, "inventory_collection_summaries", None):
                    expected = self.fixture.call(path, actor, narrowed=narrowed)
                self.assertEqual(self.fixture.call(path, actor, narrowed=narrowed), expected)


if __name__ == "__main__":
    unittest.main()
