"""저장소 공개 조회 fixture와 실제 매칭·담당 규칙을 검사한다. 네트워크 없음."""
from datetime import timedelta
import unittest

from naver_engine.tests import test_morning as TM
from naver_engine.tests import test_alerts as TA
from naver_engine import erp_read as E, management_store as MS
from app.naver_auto import matching as M, scope as SC


class FixtureStore:
    """DB 경계만 대체한다. 매칭·정책·권한은 운영 구현을 그대로 호출한다."""
    def __init__(self, now):
        self.org = {"body": TA.org_body(now)}
        self.account_rows = [dict(customer_id=cid, ad_account_no=8_000_000 + cid % 1_000_000,
                                  account_name=f"계정{cid}", present=1) for cid in (TM.A, TM.B, TM.C_)]
        self.catalog = None
        self.catalog_state = None
        self.account_at = now
        self.decisions = []
        self.states = {}

    def accounts(self):
        return self.account_rows

    def account_catalog(self):
        return self.catalog

    def account_catalog_status(self):
        return self.catalog_state

    def inventory_snapshot(self, now):
        return self.account_at

    def current_decisions(self):
        return self.decisions

    def org_current(self):
        return self.org

    def management_states(self):
        return self.states


class ManagementStoreTest(unittest.TestCase):
    def setUp(self):
        self.fc = TM.FakeClock(TM.T0)
        self.st = FixtureStore(self.fc.now())

    def company(self, pid, cid, stage="진행중", **changes):
        return {"possibility_id": pid, "company_name": f"계정{cid}", "stage": stage,
                "stage_hidden": False, "stage_known": True, **changes}

    def save(self, companies, ids=()):
        self.st.catalog = {"generated_at": self.fc.now().isoformat(), "total": len(companies),
                           "complete": True, "items": companies,
                           "ids": [dict(possibility_id=r.possibility_id, vendor=r.vendor,
                                        customer_id_raw=r.customer_id_raw, ad_account_no_raw=r.ad_account_no_raw)
                                   for r in ids]}
        self.st.catalog_state = {"state": "accepted", "at": self.fc.now().isoformat()}

    def snapshot(self, states=None):
        return MS.snapshot(self.st, self.fc.now(), stage_states={} if states is None else states)

    def test_real_number_matches_follow_stage_and_unpaired_accounts_stay_unattributed(self):
        self.save([self.company(11, TM.A), self.company(12, TM.B, "환불 완료")],
                  [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A)),
                   E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.B))])
        rows = self.snapshot()
        self.assertEqual(rows[TM.A]["decision"].cadence, "daily")
        self.assertEqual(rows[TM.A]["possibility_id"], 11)
        self.assertEqual(rows[TM.A]["stage_key"], "진행중")
        self.assertEqual(rows[TM.B]["decision"].cadence, "weekly")
        self.assertEqual(rows[TM.B]["possibility_id"], 12)
        self.assertEqual(rows[TM.C_]["decision"].cadence, "weekly")
        self.assertFalse(rows[TM.C_]["decision"].attributable)
        self.assertIsNone(rows[TM.C_]["possibility_id"])

    def test_candidates_and_conflicting_number_claims_never_become_erp_attribution(self):
        self.save([self.company(11, TM.A), self.company(12, TM.A), self.company(14, TM.B)],
                  [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A)),
                   E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.A))])
        rows = self.snapshot()
        for cid in (TM.A, TM.B):
            with self.subTest(cid=cid):
                self.assertEqual(rows[cid]["decision"].cadence, "weekly")
                self.assertFalse(rows[cid]["decision"].attributable)
                self.assertIsNone(rows[cid]["possibility_id"])

    def test_hidden_or_unconfirmed_stage_collects_weekly_without_company_attribution(self):
        self.save([self.company(11, TM.A, stage_hidden=True),
                   self.company(12, TM.B, stage=None, stage_known=False)],
                  [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A)),
                   E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.B))])
        rows = self.snapshot()
        for cid in (TM.A, TM.B):
            with self.subTest(cid=cid):
                self.assertEqual(rows[cid]["decision"].cadence, "weekly")
                self.assertFalse(rows[cid]["decision"].attributable)
                self.assertIsNone(rows[cid]["possibility_id"])
                self.assertFalse(rows[cid]["matched"])
                with self.assertRaises(SC.ClientNotVisible):
                    MS.require_action(self.st, self.fc.now(), 100, cid, allow_unmatched=True)
                self.assertIsNone(MS.require_action(self.st, self.fc.now(), 0, cid,
                                                   allow_unmatched=True)["possibility_id"])

    def test_org_missing_or_stale_blocks_collection_even_with_fresh_account_and_catalog(self):
        self.save([self.company(11, TM.A)], [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        for org in (None, {"body": TA.org_body(self.fc.now() - timedelta(hours=27))}):
            with self.subTest(org=org is None):
                self.st.org = org
                rows = self.snapshot()
                self.assertTrue(all(row["decision"].cadence == "blocked" for row in rows.values()))
                self.assertTrue(all(not row["source_current"] for row in rows.values()))

    def test_same_stage_uses_stable_revision_and_stage_transition_discards_old_exclusion(self):
        self.save([self.company(11, TM.A)], [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        states = {TM.A: dict(stage_key="진행중", possibility_id=11, stage_revision="stage-7",
                             excluded_revision="stage-7")}
        row = self.snapshot(states)[TM.A]
        self.assertEqual(row["stage_revision"], "stage-7")
        self.assertEqual(row["decision"].reason, "MANAGED_STAGE")
        self.assertEqual(row["excluded_revision"], "stage-7")
        self.st.catalog["items"][0]["stage"] = "사후 관리"
        changed = self.snapshot(states)[TM.A]
        self.assertEqual(changed["decision"].cadence, "daily")
        self.assertNotEqual(changed["stage_revision"], "stage-7")
        self.assertIsNone(changed["excluded_revision"])
        self.assertEqual(states[TM.A]["excluded_revision"], "stage-7")

    def test_employee_can_act_only_on_current_own_match_and_ceo_can_act_on_all(self):
        self.save([self.company(11, TM.A), self.company(12, TM.B)],
                  [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A)),
                   E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.B))])
        self.assertEqual(MS.require_action(self.st, self.fc.now(), 100, TM.A)["possibility_id"], 11)
        self.assertEqual(MS.require_action(self.st, self.fc.now(), 0, TM.B)["possibility_id"], 12)
        for viewer, cid in ((100, TM.B), (1, TM.A), (999, TM.A), (100, 999)):
            with self.subTest(viewer=viewer, cid=cid):
                with self.assertRaises(SC.ClientNotVisible):
                    MS.require_action(self.st, self.fc.now(), viewer, cid)

    def test_only_ceo_can_explicitly_request_an_unmatched_or_conflicted_account(self):
        self.save([self.company(11, TM.A), self.company(12, TM.A)],
                  [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A)),
                   E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.A))])
        for cid in (TM.A, TM.C_):
            with self.subTest(cid=cid):
                with self.assertRaises(SC.ClientNotVisible):
                    MS.require_action(self.st, self.fc.now(), 100, cid, allow_unmatched=True)
                with self.assertRaises(SC.ClientNotVisible):
                    MS.require_action(self.st, self.fc.now(), 0, cid)
                row = MS.require_action(self.st, self.fc.now(), 0, cid, allow_unmatched=True)
                self.assertIsNone(row["possibility_id"])
                self.assertFalse(row["decision"].attributable)

    def test_action_revalidates_expected_company_and_cannot_act_on_blocked_source(self):
        self.save([self.company(11, TM.A)], [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        with self.assertRaises(SC.ClientNotVisible):
            MS.require_action(self.st, self.fc.now(), 0, TM.A, possibility_id=12)
        self.st.account_at = None
        with self.assertRaises(SC.ActionNotAllowed):
            MS.require_action(self.st, self.fc.now(), 0, TM.A, allow_unmatched=True)

    def test_stored_inclusion_is_history_only_and_does_not_promote_nonmanagement(self):
        self.save([self.company(11, TM.A, "환불완료")], [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        self.st.states = {TM.A: dict(stage_key="환불완료", possibility_id=11, stage_revision="rev-2",
                                     included_revision="rev-2", excluded_revision=None)}
        row = MS.snapshot(self.st, self.fc.now())[TM.A]
        self.assertEqual(row["decision"].reason, "NONMANAGED_STAGE")
        self.assertEqual(row["decision"].cadence, "weekly")
        self.assertEqual(row["included_revision"], "rev-2")
        self.save([self.company(12, TM.A, "환불완료")], [E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.A))])
        moved = MS.snapshot(self.st, self.fc.now())[TM.A]
        self.assertEqual(moved["decision"].cadence, "weekly")
        self.assertIsNone(moved["included_revision"])

    def test_action_rechecks_employee_transfer_and_resignation_each_time(self):
        self.save([self.company(11, TM.A)], [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        self.assertEqual(MS.require_action(self.st, self.fc.now(), 100, TM.A)["possibility_id"], 11)
        self.st.org["body"]["owners"][0]["manage_emp_idx"] = 101
        with self.assertRaises(SC.ClientNotVisible):
            MS.require_action(self.st, self.fc.now(), 100, TM.A)
        self.assertEqual(MS.require_action(self.st, self.fc.now(), 101, TM.A)["possibility_id"], 11)
        next(p for p in self.st.org["body"]["employees"] if p["idx"] == 101)["status"] = "RESIGNED"
        with self.assertRaises(SC.ClientNotVisible):
            MS.require_action(self.st, self.fc.now(), 101, TM.A)

    def test_failed_catalog_and_invalid_agency_authority_never_get_an_automatic_period(self):
        self.save([self.company(11, TM.A)], [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        self.st.catalog_state["state"] = "failed"
        self.assertTrue(all(r["decision"].cadence == "blocked" for r in self.snapshot().values()))
        self.st.catalog_state["state"] = "accepted"
        self.st.account_rows[0]["present"] = 0
        row = self.snapshot()[TM.A]
        self.assertEqual(row["decision"].reason, "AUTHORITY_INVALID")
        self.assertFalse(row["decision"].attributable)

    def test_human_confirmation_remains_authoritative_over_another_company_claim(self):
        from types import SimpleNamespace
        self.save([self.company(11, TM.A), self.company(12, TM.A)],
                  [E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.A))])
        self.st.decisions = [SimpleNamespace(possibility_id=11, customer_id=TM.A, decision="confirmed")]
        row = self.snapshot()[TM.A]
        self.assertEqual(row["possibility_id"], 11)
        self.assertEqual(row["decision"].cadence, "daily")

    def test_boolean_customer_id_and_unmatched_flag_do_not_authorize_a_numeric_account(self):
        self.save([])
        self.st.account_rows[2]["customer_id"] = 1
        with self.assertRaises(SC.ClientNotVisible):
            MS.require_action(self.st, self.fc.now(), 0, True, allow_unmatched=True)
        with self.assertRaises(ValueError):
            MS.require_action(self.st, self.fc.now(), 0, 1, allow_unmatched="false")
