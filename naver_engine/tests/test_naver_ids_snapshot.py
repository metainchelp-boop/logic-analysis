"""전체 업체 분류용 번호 자료의 시각 검사. 기존 번호 읽기 계약은 유지한다."""
import json
import unittest
from datetime import timedelta

from naver_engine import erp_read as E
from naver_engine import inventory as I
from naver_engine.credentials import Secret
from naver_engine.tests.fake_naver import FakeClock
from naver_engine.tests.test_erp_read import FakeErp, MARK_KEY, NOW
from naver_engine.tests import test_morning as TM


class NaverIdsSnapshotTest(unittest.TestCase):
    def reader(self, body):
        return E.ErpReader(Secret(MARK_KEY), FakeErp(ids=body), FakeClock(NOW))

    def test_fresh_snapshot_preserves_multiple_account_ids_for_one_company(self):
        body = {"generated_at": NOW.isoformat(), "items": [
            {"possibility_id": 11, "vendor": "NAVER_SEARCHAD", "customer_id": "100001", "ad_account_no": "8100001"},
            {"possibility_id": 11, "vendor": "NAVER_SEARCHAD", "customer_id": "100002", "ad_account_no": "8100002"},
        ]}
        self.assertEqual(self.reader(body).read_naver_customer_ids_snapshot(),
                         self.reader(body).read_naver_customer_ids())

    def test_snapshot_rejects_missing_invalid_stale_or_future_generation_time(self):
        bodies = [{"items": []}] + [{"generated_at": at, "items": []} for at in (
            None, 0, "not-a-time", NOW.replace(tzinfo=None).isoformat(),
            (NOW - timedelta(hours=2, seconds=1)).isoformat(),
            (NOW + timedelta(minutes=5, seconds=1)).isoformat(),
        )]
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(E.ErpIncomplete):
                self.reader(body).read_naver_customer_ids_snapshot()

    def test_snapshot_accepts_inclusive_freshness_and_clock_skew_limits(self):
        for at in (NOW - timedelta(hours=2), NOW + timedelta(minutes=5)):
            with self.subTest(at=at):
                self.assertEqual(self.reader({"generated_at": at.isoformat(), "items": []})
                                 .read_naver_customer_ids_snapshot(), ())

    def test_legacy_reader_still_accepts_absent_or_old_generation_time(self):
        for body in ({"items": []}, {"generated_at": "1970-01-01T00:00:00+09:00", "items": []}):
            with self.subTest(body=body):
                self.assertEqual(self.reader(body).read_naver_customer_ids(), ())

    def test_fresh_snapshot_still_rejects_any_invalid_id_row(self):
        body = {"generated_at": NOW.isoformat(), "items": [
            {"possibility_id": 11, "vendor": "NAVER_SEARCHAD", "customer_id": "100001"},
            {"possibility_id": 12, "vendor": "NAVER_SEARCHAD", "customer_id": 100002},
        ]}
        with self.assertRaises(E.ErpIncomplete):
            self.reader(body).read_naver_customer_ids_snapshot()


class CatalogSnapshotSyncTest(TM.Base):
    def test_stale_id_feed_preserves_accepted_catalog_and_marks_refresh_failed(self):
        now = self.fc.now()
        body = {"generated_at": now.isoformat(), "total": 1, "complete": True, "items": [
            {"possibility_id": 11, "company_name": "가상상점", "stage": "진행중",
             "stage_hidden": False, "stage_known": True},
        ]}
        self.st.record_account_catalog(body, [E.NaverIdRow(11, "NAVER_SEARCHAD", "100001")], now)
        before = self.st.account_catalog()
        fake = FakeErp(ids={"generated_at": (now - timedelta(hours=3)).isoformat(), "items": []})
        fake.override[(E.PATH_ACCOUNT_CATALOG, None)] = (
            200, json.dumps({"status": 200, "result": body}).encode())
        reader = E.ErpReader(Secret(MARK_KEY), fake, self.fc)
        self.assertEqual(I.sync_catalog(reader, self.st, now)["state"], "failed")
        self.assertEqual(self.st.account_catalog(), before)
        self.assertEqual(self.st.account_catalog_status()["state"], "failed")


if __name__ == "__main__":
    unittest.main()
