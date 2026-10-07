"""목록 요약은 대형 이어읽기 JSON을 읽지 않는다. 실제 스키마·메모리 Store만 사용한다."""
from datetime import timedelta
import json
import socket
import sqlite3
import unittest
from unittest.mock import patch

from naver_engine import store as S
from naver_engine.tests.test_catalog_links import make_fixture


class WideReferenceConnection:
    """변경 전 SELECT * 결과를 실제 SQL로 읽는 비교용 연결."""
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, args=()):
        normalized = " ".join(sql.split())
        if "FROM naver_auto_performance_job ORDER BY checked_at,job_key" in normalized:
            sql = "SELECT * FROM naver_auto_performance_job ORDER BY checked_at,job_key"
        elif "FROM naver_auto_inventory_check i WHERE i.status='ok'" in normalized:
            sql = "SELECT i.* " + sql[sql.index("FROM naver_auto_inventory_check i"):]
        return self.connection.execute(sql, args)

    def __getattr__(self, name):
        return getattr(self.connection, name)


class PerformanceSummaryProjectionTest(unittest.TestCase):
    def setUp(self):
        for method in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, method, side_effect=AssertionError("외부 송신 금지"))
            guard.start()
            self.addCleanup(guard.stop)
        self.fixture = make_fixture(accounts=1, managed=1, campaigns=2, history_days=4)
        self.store, self.clock = self.fixture.store, self.fixture.clock
        self.addCleanup(self.store.close)
        self.assertEqual(self.fixture.run(limit=1, max_calls=18, max_seconds=30).counts, {"ok": 1})
        self.payload = json.dumps({"synthetic": "x" * (256 * 1024)})
        self.store._conn.execute("UPDATE naver_auto_performance_job SET progress_json=?,campaigns_json=?",
                                 (self.payload, self.payload))
        self.cid = self.store.accounts()[0]["customer_id"]
        now = self.clock.now()
        for days, status in ((3, "ok"), (2, "ok"), (1, "retry")):
            at = (now - timedelta(days=days)).isoformat()
            self.store._conn.execute("""INSERT INTO naver_auto_inventory_check
                (customer_id,day,snapshot_at,status,checked_at,bizmoney,yday_spend,yday_imp,yday_clk,
                 campaigns_json,progress_json,next_try_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (self.cid, at[:10], at, status, at, 1000+days, 100+days, 10+days, days,
                 self.payload, self.payload, at))

    def without_payload_reads(self):
        original = S._authorizer(S.PHASE_READ)
        def authorize(action, table, column, database, source):
            if action == sqlite3.SQLITE_READ and table in (
                    "naver_auto_performance_job", "naver_auto_inventory_check") \
                    and column in ("progress_json", "campaigns_json"):
                return sqlite3.SQLITE_DENY
            return original(action, table, column, database, source)
        self.store._conn.set_authorizer(authorize)

    def reference(self, method, *args):
        original = self.store._conn
        self.store._conn = WideReferenceConnection(original)
        try:
            return getattr(self.store, method)(*args)
        finally:
            self.store._conn = original

    def test_performance_summary_uses_no_payload_columns_and_equals_wide_reference(self):
        expected = self.reference("performance_checks", self.clock.now())
        self.assertEqual(expected[self.cid]["status"], "ok")
        self.assertEqual(expected[self.cid]["spend"], 2000)
        self.without_payload_reads()
        actual = self.store.performance_checks(self.clock.now())
        self.assertEqual(actual, expected)
        self.assertNotIn("synthetic", json.dumps(actual))

    def test_legacy_success_uses_no_payload_columns_and_keeps_latest_success(self):
        expected = self.reference("latest_inventory_successes")
        self.assertEqual(expected[self.cid]["spend"], 102)
        self.assertEqual(expected[self.cid]["bizmoney"], 1002)
        self.without_payload_reads()
        actual = self.store.latest_inventory_successes()
        self.assertEqual(actual, expected)
        self.assertNotIn("synthetic", json.dumps(actual))


if __name__ == "__main__":
    unittest.main()
