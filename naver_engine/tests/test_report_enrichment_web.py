"""Authenticated report enrichment/notes through the real WSGI boundary, no collection."""
from copy import deepcopy
import json
import unittest

from naver_engine.tests import test_report_accounts_web as TAW, test_web as TW
from naver_engine import report_views as RV


class ReportEnrichmentWebTest(unittest.TestCase):
    setUp = TAW.ReportAccountsWebTest.setUp
    call = TAW.ReportAccountsWebTest.call
    get = TAW.ReportAccountsWebTest.get
    seed_report = TAW.ReportAccountsWebTest.seed_report

    def prepare(self):
        self.payload = self.seed_report()
        # Production format2 snapshots carry the account's immutable membership.
        self.payload["_account_reports"][str(TW.A)]["_expected_customers"] = [TW.A]
        self.store._conn.execute("UPDATE naver_auto_report_snapshot SET payload_json=? WHERE report_id=1",
                                 (json.dumps(self.payload),))
        self.key = RV.account_key(TW.A)
        self.app._write = lambda fn: fn(self.store)
        self.document = {"internal_note": "내부 검증 기록", "client_feedback": "고객에게 받은 요청",
                         "shared_comment": "검토할 코멘트", "next_plan": "담당자 자료 확인",
                         "targets": {"cpa": 1200, "source": "테스트 합의 근거"}}

    def post(self, *, actor=100, key=None, version=0, action="save", document=None, extra=None):
        body = {"report_id": 1, "account_key": key or self.key,
                "revision_fingerprint": self.payload["revision_fingerprint"],
                "expected_version": version, "action": action}
        if action == "save":
            body["document"] = self.document if document is None else document
        body.update(extra or {})
        return self.call("POST", "/reports/notes", self.signer.issue(actor, self.clock.now()), body=body)

    def detail(self, key=None, actor=100):
        return self.get("/reports/detail", "report_id=1&account_key="+(key or self.key), actor=actor)

    def test_read_only_enrichment_has_seventeen_metrics_and_separate_account_contribution(self):
        self.prepare()
        original = deepcopy(self.store.report_snapshot_detail(1))
        status, account, _, _ = self.detail()
        self.assertEqual(status, 200, account)
        self.assertEqual(len(account["payload"]["details"]["enrichment"]["metrics"]), 17)
        self.assertEqual(account["annotations"]["state"], "empty")
        self.assertTrue(account["annotations"]["can_edit"])
        self.assertNotIn("contributions", account["scope"])
        company = self.detail("company")[1]
        self.assertEqual([row["account_key"] for row in company["scope"]["contributions"]], [self.key])
        self.assertEqual(company["scope"]["contributions"][0]["shares"]["spend"], 100)
        self.assertEqual(self.store.report_snapshot_detail(1), original)

    def test_exact_account_notes_save_approve_edit_and_shared_fields_only(self):
        self.prepare()
        status, first, _, _ = self.post()
        self.assertEqual(status, 200, first)
        self.assertEqual((first["version"], first["state"]), (1, "draft"))
        self.assertIsNone(first["shared"])
        status, approved, _, _ = self.post(version=1, action="approve", actor=0)
        self.assertEqual(status, 200, approved)
        self.assertEqual((approved["version"], approved["state"]), (2, "approved"))
        self.assertEqual(approved["shared"]["shared_comment"], self.document["shared_comment"])
        self.assertNotIn("internal_note", approved["shared"])
        self.assertNotIn("client_feedback", approved["shared"])
        company = self.detail("company")[1]
        self.assertEqual(company["annotations"]["version"], 0)
        status, changed, _, _ = self.post(version=2, document={**self.document, "shared_comment": "수정"})
        self.assertEqual(status, 200, changed)
        self.assertEqual((changed["version"], changed["state"], changed["shared"]), (3, "draft", None))
        read = self.detail()[1]["annotations"]
        self.assertEqual([item["version"] for item in read["history"]["items"]], [3, 2, 1])

    def test_conflict_scope_wrong_fingerprint_and_strict_body(self):
        self.prepare()
        self.assertEqual(self.post()[0], 200)
        self.assertEqual(self.post()[0], 409)
        self.assertEqual(self.post(actor=101)[0], 404)
        self.assertEqual(self.post(key="a"*64)[0], 404)
        self.assertEqual(self.post(extra={"revision_fingerprint": "b"*64})[0], 409)
        self.assertEqual(self.post(extra={"unexpected": True})[0], 400)
        self.assertEqual(self.post(extra={"expected_version": True})[0], 400)
        self.assertEqual(self.post(action="approve", extra={"document": self.document})[0], 400)
        self.assertEqual(self.detail(actor=101)[:2], (404, TW.WEB.NOT_VISIBLE))

    def test_old_report_notes_remain_read_only_and_new_report_has_empty_notes(self):
        self.prepare()
        self.assertEqual(self.post()[0], 200)
        self.seed_report(2, spend=200)
        self.assertFalse(self.detail()[1]["annotations"]["can_edit"])
        self.assertEqual(self.post(version=1)[0], 409)
        latest = self.get("/reports/detail", "report_id=2&account_key="+self.key)[1]
        self.assertEqual((latest["annotations"]["version"], latest["annotations"]["shared"]), (0, None))

    def test_dirty_report_keeps_internal_draft_but_blocks_shared_approval(self):
        self.prepare()
        self.store._conn.execute("INSERT INTO naver_auto_report_dirty VALUES(11,?,?,1)",
            (self.payload["period_key"], self.clock.now().isoformat()))
        self.assertEqual(self.post()[0], 200)
        self.assertEqual(self.post(version=1, action="approve")[0], 409)
        read = self.detail()[1]["annotations"]
        self.assertEqual((read["state"], read["shared"]), ("draft", None))

    def test_writer_queue_rechecks_changed_ownership_before_saving(self):
        self.prepare()
        changed_once = False
        def changed(fn):
            nonlocal changed_once
            if not changed_once:
                changed_once = True
                self.clock.advance(1)
                self.store.record_org(TAW.TA.org_body(self.clock.now(),
                    owners=[TAW.TA.owner(11, 101), TAW.TA.owner(12, 101), TAW.TA.owner(13, 100)]), self.clock.now())
            return fn(self.store)
        self.app._write = changed
        self.assertEqual(self.post()[0], 404)
        notes = self.store.report_notes(1, self.key, self.payload["revision_fingerprint"])
        self.assertEqual(notes["version"], 0)


if __name__ == "__main__":
    unittest.main()
