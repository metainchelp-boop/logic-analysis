"""실제 Store/메모리 SQL: 후보 비용 상한과 매 회차 새 연결 정보 검증."""
from pathlib import Path
import runpy
import socket
import unittest
from unittest.mock import patch


make_fixture = runpy.run_path(str(Path(__file__).resolve().parents[2] /
    "tools/naver-store-selection-benchmark.py"))["make_fixture"]


class CollectionSelectionCostTest(unittest.TestCase):
    def setUp(self):
        for method in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, method, side_effect=AssertionError("외부 송신 금지"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_selection_does_not_rescan_all_link_decisions_for_each_account_or_history(self):
        for accounts, history in ((12, 0), (48, 3)):
            for method in ("performance_work", "structure_work"):
                with self.subTest(accounts=accounts, history=history, method=method):
                    fixture = make_fixture(accounts, accounts // 2, history_days=history)
                    store, queries = fixture.store, []
                    try:
                        store._conn.set_trace_callback(queries.append)
                        jobs = getattr(store, method)(fixture.clock.now(), 24)
                        scans = [sql for sql in queries if "FROM naver_auto_link_decision" in sql]
                        self.assertEqual(len(jobs), min(24, accounts // 2))
                        self.assertEqual({job["kind"] for job in jobs}, {"daily"})
                        # 두 번의 현재 관리대상 대조 + 후보 묶음의 지문 한 번.
                        # 계정/완결 이력 수가 증가해도 전체 판단표 읽기가 늘지 않는다.
                        self.assertLessEqual(len(scans), 3)
                    finally:
                        store.close()

    def test_next_selection_and_request_revalidate_changed_link_decisions(self):
        for method, validate in (("performance_work", "performance_account_valid"),
                                 ("structure_work", "structure_account_valid")):
            with self.subTest(method=method):
                fixture = make_fixture(12, 6)
                store, now = fixture.store, fixture.clock.now()
                try:
                    old = getattr(store, method)(now, 1)[0]
                    self.assertTrue(getattr(store, validate)(old, now))
                    store.record_decision(11, old["customer_id"], "confirmed", 0, now)
                    self.assertFalse(getattr(store, validate)(old, now))
                    new = getattr(store, method)(now, 1)[0]
                    self.assertNotEqual(old["matching_fingerprint"], new["matching_fingerprint"])
                    self.assertTrue(getattr(store, validate)(new, now))
                finally:
                    store.close()


if __name__ == "__main__":
    unittest.main()
