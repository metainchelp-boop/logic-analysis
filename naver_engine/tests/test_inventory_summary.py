"""이관 카드: 계정 단위 합계·부분 잔액·과거 부재·담당 경계. 합성 원천만 사용."""
from datetime import timedelta

from naver_engine import store as S, erp_read as E
from naver_engine.tests.test_account_catalog import InventoryViewTest, company
from naver_engine.tests import test_morning as TM, test_alerts as TA
from app.naver_auto import matching as M


class InventorySummaryTest(InventoryViewTest):
    def catalog(self):
        self.save([company(11, company_name=TM.NAMES[TM.A]), company(12, company_name=TM.NAMES[TM.B])],
                  [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A)), E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.B))])

    def balance(self, cid, amount):
        now = self.fc.now()
        snapshot = self.st.inventory_snapshot(now)
        self.st.begin_inventory_check(cid, snapshot, now)
        self.st.record_inventory_check(cid, snapshot, now, {"status": "partial", "bizmoney": amount})

    def test_scope_totals_do_not_change_with_list_filters_and_zero_is_known(self):
        self.catalog()
        self.balance(TM.A, 4116.83)
        self.balance(TM.B, 0)
        result = self.board()
        summary = result["summary"]
        self.assertEqual(summary["current_total"], sum(result["counts"].values()))
        self.assertEqual(summary["balance"], {"known_count": 2, "total_count": 3,
                         "known_sum": 4116, "complete": False})
        self.assertEqual(self.board(mapping="no_erp_record")["summary"], summary)
        self.assertEqual(self.board(view="balance_known")["filtered_total"], 2)
        own = self.board(100)["summary"]
        self.assertEqual(own["current_total"], 1)
        self.assertEqual(own["balance"], {"known_count": 1, "total_count": 1,
                         "known_sum": 4116, "complete": True})

    def test_unknown_is_not_zero_and_empty_scope_is_explicit(self):
        self.catalog()
        self.assertIsNone(self.board()["summary"]["balance"]["known_sum"])
        empty = self.board(selection="me")["summary"]["balance"]
        self.assertTrue(empty["complete"])
        self.assertEqual(empty["total_count"], 0)
        self.assertEqual(empty["known_sum"], 0)
        self.assertEqual(empty["known_count"], 0)

    def test_sum_before_truncation_negative_balance_and_complete(self):
        self.catalog()
        for cid, amount in ((TM.A, 1.8), (TM.B, 2.8), (TM.C_, -1.2)):
            self.balance(cid, amount)
        money = self.board()["summary"]["balance"]
        self.assertEqual(money, {"known_count": 3, "total_count": 3, "known_sum": 3, "complete": True})

    def test_failed_sources_withhold_totals_not_zero(self):
        self.catalog()
        self.balance(TM.A, 90)
        self.st.record_sync_event(S.SYNC_ACCOUNTS, S.SYNC_FAILED, ("KEY_REJECTED",), self.fc.now())
        result = self.board()["summary"]
        self.assertFalse(result["ready"])
        self.assertIsNone(result["lost_count"])
        self.assertIsNone(result["balance"]["known_sum"])
        self.assertFalse(result["balance"]["complete"])

    def lose(self, hours):
        self.fc.advance(hours * 3600)
        now = self.fc.now()
        self.st.record_org(TA.org_body(now), now)
        self.st.record_accounts(TM.kids(TM.B, TM.C_), now)
        self.catalog()

    def test_lost_accounts_separate_from_current_total_and_scoped(self):
        self.catalog()
        self.lose(1)
        self.assertEqual(self.board()["summary"]["lost_count"], 0)
        self.lose(24)
        result = self.board(view="lost")
        self.assertEqual(result["summary"]["current_total"], 2)
        self.assertEqual(result["summary"]["lost_count"], 1)
        self.assertEqual(result["filtered_total"], 1)
        row = result["rows"][0]
        self.assertEqual(row["possibility_id"], 11)
        self.assertEqual(row["collection"]["status"], "not_current")
        self.assertEqual(self.board(100, view="lost")["filtered_total"], 1)
        self.assertEqual(self.board(101, view="lost")["filtered_total"], 0)
        self.assertIsNone(result["summary"]["balance"]["known_sum"])

    def test_lost_without_verified_owner_is_owner_only(self):
        self.save([])
        self.lose(1)
        self.lose(24)
        self.save([company(91, company_name="다른업체1"), company(92, company_name="다른업체2")])
        self.assertEqual(self.board(view="lost")["filtered_total"], 1)
        self.assertEqual(self.board(100, view="lost")["filtered_total"], 0)

    def test_returning_account_clears_lost_and_stale_catalog_withholds(self):
        self.catalog()
        self.lose(1)
        self.lose(24)
        self.st.record_account_catalog_failure(self.fc.now(), "CATALOG_FAILED")
        self.assertIsNone(self.board()["summary"]["lost_count"])
        self.assertEqual(self.board(view="lost")["rows"], [])
        self.fc.advance(1)
        self.st.record_accounts(TM.kids(TM.A, TM.B, TM.C_), self.fc.now())
        self.catalog()
        self.assertEqual(self.board()["summary"]["lost_count"], 0)

    def test_invalid_view_rejected(self):
        from app.naver_auto import scope as SC
        with self.assertRaises(SC.SelectionRejected):
            self.board(view="arbitrary")

    def test_two_calendar_dates_still_need_twenty_hours(self):
        self.catalog()
        self.lose(1)
        self.lose(19)
        self.assertEqual(self.board()["summary"]["lost_count"], 0)
        self.lose(1)
        self.assertEqual(self.board()["summary"]["lost_count"], 1)

    def test_hidden_lost_owner_is_not_visible_to_staff(self):
        self.catalog()
        self.lose(1)
        self.lose(24)
        self.save([company(11, company_name=TM.NAMES[TM.A], stage_hidden=True),
                   company(12, company_name=TM.NAMES[TM.B])],
                  [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A)), E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.B))])
        self.assertEqual(self.board()["summary"]["lost_count"], 1)
        self.assertEqual(self.board(100)["summary"]["lost_count"], 0)

    def test_same_account_credential_duplicate_does_not_double_count(self):
        self.save([company(11, company_name=TM.NAMES[TM.A])],
                  [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A)), E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        self.balance(TM.A, 10.9)
        self.assertEqual(self.board()["summary"]["balance"]["known_sum"], 10)

    def test_stale_balance_from_previous_day_not_summed(self):
        self.catalog()
        self.balance(TM.A, 99)
        self.fc.advance(24 * 3600)
        self.st.record_org(TA.org_body(self.fc.now()), self.fc.now())
        self.st.record_accounts(TM.kids(TM.A, TM.B, TM.C_), self.fc.now())
        self.catalog()
        self.assertIsNone(self.board()["summary"]["balance"]["known_sum"])
