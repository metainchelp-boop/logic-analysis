"""정정 이력은 현재 담당 범위 안에서만, 읽기 전용·상한 페이지로 제공한다."""
from copy import deepcopy
from datetime import date
import unittest
from unittest.mock import patch

from naver_engine.tests import test_report_paging as P
from naver_engine.tests import test_web as TW


class ReportRevisionWebTest(unittest.TestCase):
    call = TW.WebBase.call

    def setUp(self):
        self.signer = TW.SE.TokenSigner(TW.Secret(TW.TOKEN_SECRET))
        self.store = P.ReadReports([P.report(1, 11, P.payload(ready=True)), P.report(2, 12)])
        self.calls = []
        self.result = {"items": [deepcopy(self.store.rows[0])], "next_before_report_id": None}
        self.result["items"][0].update(revision_no=2, validation={"status": "complete"},
            change_summary={"changed_metrics": ["spend"]}, expected_customers_json="PRIVATE")
        self.result["items"][0]["payload"]["_source_account_ids"] = [987654321]
        def history(*args, **kwargs):
            self.calls.append((args, kwargs))
            return self.result
        self.store.report_history = history
        def forbidden(*args, **kwargs):
            self.fail("이력 열람에서 쓰기/수집을 시작할 수 없습니다")
        self.app = TW.WEB.App(open_read=lambda: self.store, write=forbidden, signer=self.signer,
            profiles=forbidden, clock=lambda: P.NOW, owner_verification=True, verified_linking=True,
            request_collection=forbidden, collection_status=forbidden)

    def get(self, viewer=100, query="possibility_id=11"):
        return self.call("GET", "/reports/history", self.signer.issue(viewer, P.NOW), query=query)

    def test_history_current_owner_read_only_and_private_fields_hidden(self):
        before = deepcopy(self.result)
        status, body, _, raw = self.get(query="possibility_id=11&limit=10&before_report_id=9")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["items"][0]["revision_no"], 2)
        self.assertNotIn(b"PRIVATE", raw)
        self.assertNotIn(b"987654321", raw)
        self.assertEqual(self.calls[0][1], {"period_key": None, "before_report_id": 9, "limit": 10})
        self.assertEqual(self.result, before)

    def test_other_owner_or_unknown_id_never_reaches_history(self):
        for pid in (12, 999):
            status, body, _, _ = self.get(query=f"possibility_id={pid}")
            self.assertEqual((status, body), (404, TW.WEB.NOT_VISIBLE))
        self.assertEqual(self.calls, [])

    def test_strict_bounded_query(self):
        for query in ("", "possibility_id=0", "possibility_id=11&limit=21",
                      "possibility_id=11&limit=0", "possibility_id=11&before_report_id=-1",
                      "possibility_id=11&period_key=garbage", "possibility_id=11&extra=x"):
            self.assertEqual(self.get(query=query)[:2], (400, {"error": "bad-query"}), query)
        self.assertEqual(self.get(query="possibility_id=11&period_key=weekly:2026-09-21:2026-09-27")[0], 200)

    def test_pending_revalidation_cannot_be_reviewed_in_list(self):
        self.store.rows[0]["validation"] = {"status": "pending"}
        status, body, _, _ = self.call("GET", "/reports", self.signer.issue(100, P.NOW))
        self.assertEqual(status, 200)
        self.assertFalse(body["rows"][0]["can_review"])

    def test_manual_range_requires_closed_bounded_dates_and_server_company_match(self):
        self.app._write = lambda fn: fn(self.store)
        self.store.record_access = lambda *args, **kwargs: None
        requested = []
        self.store.performance_manual_request = lambda *args, **kwargs: requested.append((args, kwargs))
        body = {"ad_account_no": "12345", "possibility_id": 11,
                "period_start": "2026-08-01", "period_end": "2026-08-31"}
        with patch.object(self.app, "_management_account", return_value=(7654321, {"possibility_id": 11})):
            status, result, _, _ = self.call("POST", "/management/collect", self.signer.issue(100, P.NOW), body)
            self.assertEqual((status, result), (200, {"status": "accepted"}))
            self.assertEqual(requested[0][1], {"start": date(2026, 8, 1), "end": date(2026, 8, 31), "possibility_id": 11})
            for changes in ({"period_end": "2026-09-01"}, {"period_end": "2026-10-03"},
                            {"period_start": "20260801"}, {"possibility_id": True}, {"period_start": None}):
                self.assertEqual(self.call("POST", "/management/collect", self.signer.issue(100, P.NOW),
                                          {**body, **changes})[0], 400)
            self.assertEqual(len(requested), 1)
        with patch.object(self.app, "_management_account", return_value=(7654321, {"possibility_id": 12})):
            self.assertEqual(self.call("POST", "/management/collect", self.signer.issue(100, P.NOW), body)[0], 404)
        self.assertEqual(len(requested), 1)


if __name__ == "__main__":
    unittest.main()
