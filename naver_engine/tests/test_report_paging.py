"""보고서 응답의 4MiB 중계 한도: 실제 WSGI/토큰/범위 + 메모리 읽기 원천.

SQLite/네이버/유료 호출은 없다. 누락 근거의 축약은 응답에만 적용하며 원본은 보존한다.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import socket
import unittest
from unittest.mock import patch

from naver_engine.tests import test_web as TW
from naver_engine.tests import test_alerts as TA
from naver_engine import reporting as R


NOW = datetime(2026, 10, 3, 10, tzinfo=R.KST)
RELAY_LIMIT = 4*1024*1024
SCHEDULE = {"timezone": "Asia/Seoul", "weekly": "월요일 10:00", "monthly": "매월 3일 10:00"}


def payload(period=None, *, ready=False, accounts=1):
    period = period or R.period("weekly", date(2026, 9, 21))
    ids = list(range(1_000_000, 1_000_000+accounts))
    daily = []
    if ready:
        for cid in ids:
            for offset in range((period.end-period.start).days+1):
                daily.append({"customer_id": cid, "day": str(period.start+timedelta(days=offset)),
                              "imp": 100, "clk": 10, "spend": 1000, "conversions": 1,
                              "conversion_value": 2000, "basic_complete": True, "conversion_complete": True,
                              "source_at": NOW.isoformat(), "checked_at": NOW.isoformat()})
    return R.aggregate(period, ids, daily, NOW)


def report(report_id, pid, source=None):
    source = deepcopy(source if source is not None else payload())
    return {"report_id": report_id, "possibility_id": pid, "period_key": source["period_key"],
            "revision_fingerprint": source["revision_fingerprint"], "generated_at": source["generated_at"],
            "status": source["status"], "review_status": source["review_status"], "payload": source, "review": None}


class ReadReports:
    """저장소 공개 읽기 계약. 반환 원본을 복제하지 않아 응답 조립의 변조를 잡는다."""
    def __init__(self, rows):
        self.rows = rows
        ids = sorted({row["possibility_id"] for row in rows})
        self.body = TA.org_body(NOW, owners=[TA.owner(pid, 101 if pid == 12 else 100) for pid in ids])
        self.catalog = {"generated_at": NOW.isoformat(), "items": [
            {"possibility_id": pid, "company_name": "합성 업체", "stage": "진행중",
             "stage_known": True, "stage_hidden": False} for pid in ids]}

    def close(self):
        pass

    def org_current(self):
        return {"body": self.body, "generated_at": NOW}

    def account_catalog(self):
        return self.catalog

    def account_catalog_status(self):
        return {"state": "accepted"}

    def report_snapshots(self):
        return self.rows

    def prospects(self):
        return []

    def last_pairing(self, outcome):
        return None

    def issues(self, **kwargs):
        return []

    def link_decisions(self):
        return (), ()

    def accounts(self):
        return []

    def account_day_checks_on(self, day):
        return {}


class ReportPagingTest(unittest.TestCase):
    call = TW.WebBase.call

    def setUp(self):
        network = patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
        network.start()
        self.addCleanup(network.stop)
        self.signer = TW.SE.TokenSigner(TW.Secret(TW.TOKEN_SECRET))
        self.configure([report(n, 12 if n <= 25 else 11) for n in range(1, 53)])

    def configure(self, rows):
        self.store = ReadReports(rows)
        def forbidden(*args, **kwargs):
            self.fail("보고서 열람은 쓰기 또는 수집을 시작할 수 없습니다")
        self.app = TW.WEB.App(open_read=lambda: self.store, write=forbidden, signer=self.signer,
                             profiles=forbidden, clock=lambda: NOW, owner_verification=True,
                             request_collection=forbidden, collection_status=forbidden)

    def get(self, viewer=0, query=""):
        return self.call("GET", "/reports", self.signer.issue(viewer, NOW), query=query)

    def test_fixed_twenty_row_pages_total_and_next_preserve_order(self):
        seen = []
        for page, length, next_page in ((0, 20, 1), (1, 20, 2), (2, 12, None)):
            status, body, _headers, _raw = self.get(query=f"selection=all&page={page}")
            self.assertEqual(status, 200, body)
            self.assertEqual(set(body), {"rows", "total", "page", "page_size", "next_page", "schedule"})
            self.assertEqual((body["total"], body["page"], body["page_size"], body["next_page"]),
                             (52, page, 20, next_page))
            self.assertEqual(len(body["rows"]), length)
            self.assertEqual(body["schedule"], SCHEDULE)
            seen.extend(row["report_id"] for row in body["rows"])
        self.assertEqual(seen, list(range(1, 53)))
        self.assertEqual(self.get()[1], self.get(query="selection=all&page=0")[1])

    def test_staff_scope_and_selection_are_applied_before_paging_and_counting(self):
        seen = []
        for page, size, next_page in ((0, 20, 1), (1, 7, None)):
            status, body, _headers, _raw = self.get(100, f"selection=all&page={page}")
            self.assertEqual(status, 200, body)
            self.assertEqual((body["total"], len(body["rows"]), body["next_page"]), (27, size, next_page))
            self.assertTrue(all(row["possibility_id"] == 11 for row in body["rows"]))
            seen.extend(row["report_id"] for row in body["rows"])
            selected = self.get(0, f"selection=person:100&page={page}")[1]
            self.assertEqual([row["report_id"] for row in selected["rows"]],
                             [row["report_id"] for row in body["rows"]])
            self.assertEqual(selected["total"], 27)
        self.assertEqual(seen, list(range(26, 53)))
        self.assertEqual(self.get(100, "selection=person:101")[0], 404)

    def test_bad_duplicate_and_out_of_range_page_requests_are_rejected(self):
        for query in ("page=-1", "page=01", "page=1.0", "page=true", "page=", "page=1000000",
                      "page=3", "page=999999", "page=0&page=1", "page=%ZZ", "page_size=1000"):
            with self.subTest(query=query):
                self.assertEqual(self.get(query=query)[:2], (400, {"error": "bad-query"}))
        self.assertEqual(self.get(100, "page=2")[:2], (400, {"error": "bad-query"}))

    def test_missing_first_hundred_retains_full_count_and_does_not_mutate_source(self):
        source = payload(R.period("monthly", date(2026, 8, 1)), accounts=4)
        self.assertEqual(len(source["missing"]), 124)
        self.configure([report(1, 11, source)])
        before = deepcopy(self.store.rows)
        status, body, _headers, _raw = self.get()
        self.assertEqual(status, 200, body)
        got = body["rows"][0]["payload"]
        self.assertEqual(got["missing"], source["missing"][:100])
        self.assertEqual(got["missing_count"], 124)
        self.assertIs(got["missing_truncated"], True)
        self.assertEqual(self.store.rows, before)
        self.assertNotIn("missing_count", self.store.rows[0]["payload"])
        self.assertEqual(self.get()[1], body)

    def test_short_and_complete_missing_lists_keep_exact_zero_and_false(self):
        self.configure([report(1, 11), report(2, 11, payload(ready=True))])
        body = self.get()[1]
        partial, ready = [row["payload"] for row in body["rows"]]
        self.assertEqual((partial["missing_count"], len(partial["missing"])), (7, 7))
        self.assertIs(partial["missing_truncated"], False)
        self.assertEqual((ready["missing_count"], ready["missing"]), (0, []))
        self.assertIs(ready["missing_truncated"], False)
        self.assertEqual(ready["status"], "ready")

    def test_empty_scope_has_zero_page_without_invented_report(self):
        self.configure([])
        status, body, _headers, _raw = self.get()
        self.assertEqual(status, 200, body)
        self.assertEqual((body["rows"], body["total"], body["page"], body["page_size"], body["next_page"]),
                         ([], 0, 0, 20, None))
        self.assertEqual(self.get(query="page=1")[:2], (400, {"error": "bad-query"}))

    def test_305_advertisers_with_five_weeks_and_month_are_below_relay_limit(self):
        periods = [R.period("weekly", date(2026, 8, day)) for day in (3, 10, 17, 24, 31)]
        periods.append(R.period("monthly", date(2026, 8, 1)))
        templates = [payload(period) for period in periods]
        rows = [report((pid-1)*6+n+1, pid, source)
                for pid in range(1, 306) for n, source in enumerate(templates)]
        # 실제 집계 형식의 누락 31일+5주 원본은 페이지가 없으면 이미 중계 한도를 넘는다.
        unbounded = {"rows": [dict(row, company_name="합성 업체", owner=None, can_review=False) for row in rows],
                     "schedule": SCHEDULE}
        self.assertGreater(len(json.dumps(unbounded, ensure_ascii=False, separators=(",", ":")).encode()), RELAY_LIMIT)
        self.configure(rows)
        status, body, _headers, raw = self.get()
        self.assertEqual(status, 200, body)
        self.assertEqual((body["total"], len(body["rows"])), (1830, 20))
        self.assertLess(len(raw), RELAY_LIMIT)
        # 누락이 없는 전체 준비 완료 자료에도 동일한 한정 응답을 적용한다.
        ready_templates = [payload(period, ready=True) for period in periods]
        self.configure([report((pid-1)*6+n+1, pid, source)
                        for pid in range(1, 306) for n, source in enumerate(ready_templates)])
        for page, count in ((0, 20), (91, 10)):
            status, body, _headers, raw = self.get(query=f"page={page}")
            self.assertEqual(status, 200, body)
            self.assertEqual((body["total"], len(body["rows"])), (1830, count))
            self.assertTrue(all(row["status"] == "ready" for row in body["rows"]))
            self.assertLess(len(raw), RELAY_LIMIT)
