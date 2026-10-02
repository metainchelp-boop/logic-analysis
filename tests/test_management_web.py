"""실제 WSGI·토큰·범위·매칭을 통과하는 관리 API. DB 경계만 fixture로 대체한다."""
from types import SimpleNamespace
import unittest

from naver_engine.tests import test_web as TW
from test_management_store import FixtureStore


class WebStore(FixtureStore):
    def __init__(self, now):
        super().__init__(now)
        self.org["generated_at"] = now
        self.saved, self.requests, self.audit = [], [], []
        self.reports, self.reviews = [], []
        self.pairing = None
        self.pair_rows = []
        self.catalog = {"generated_at": now.isoformat(), "total": 2, "complete": True,
                        "items": [dict(possibility_id=pid, company_name=f"계정{cid}", stage="진행중",
                                       stage_hidden=False, stage_known=True) for pid, cid in ((11, TW.A), (12, TW.B))],
                        "ids": [dict(possibility_id=pid, vendor=TW.M.VENDOR_NAVER, customer_id_raw=str(cid),
                                     ad_account_no_raw=None) for pid, cid in ((11, TW.A), (12, TW.B))]}
        self.catalog_state = {"state": "accepted", "at": now.isoformat()}
        self.states = {cid: dict(possibility_id=pid, stage_key="진행중", stage_revision=f"rev-{pid}",
                                included_revision=None, excluded_revision=None) for pid, cid in ((11, TW.A), (12, TW.B))}

    def close(self):
        pass

    def record_access(self, *args):
        self.audit.append(args)

    def record_management_override(self, cid, revision, included, actor, now, reason):
        if self.states[cid]["stage_revision"] != revision:
            raise TW.S.StoreRefused("단계가 변경되었습니다")
        self.saved.append((cid, revision, included, actor, reason))
        return self.states[cid]

    def performance_manual_request(self, cid, actor, now, **period):
        self.requests.append((cid, actor, period) if period else (cid, actor))
        return {"status": "accepted", "customer_id": cid}

    def prospects(self):
        return [dict(possibility_id=r["possibility_id"], name=r["company_name"], stage_key=r["stage"],
                     present=1, stage_conflict=0, end_unreadable=0, latest_end_date=None)
                for r in self.catalog["items"]]

    def last_pairing(self, outcome=None):
        return self.pairing

    def pairing_rows(self, pairing_id):
        return self.pair_rows

    def issues(self, *args, **kwargs):
        return []

    def link_decisions(self):
        return self.decisions, []

    def account_day_checks_on(self, day):
        return {}

    def report_snapshots(self):
        return self.reports

    def record_report_review(self, report_id, actor, now, decision, note):
        self.reviews.append((report_id, actor, decision, note))
        return {"report_id": report_id, "review_status": decision}

    def accounts_read_at(self):
        return self.account_at

    def stage_as_of(self):
        return self.account_at

    def record_decisions(self, pairs, decision, actor, now, audit_action):
        self.decisions.extend(SimpleNamespace(possibility_id=pid, customer_id=cid, decision=decision)
                              for pid, cid in pairs)
        return list(range(1, len(pairs) + 1))


class ManagementWebTest(unittest.TestCase):
    call = TW.WebBase.call

    def setUp(self):
        self.fc = TW.TM.FakeClock(TW.T0)
        self.st = WebStore(self.fc.now())
        self.signer = TW.SE.TokenSigner(TW.Secret(TW.TOKEN_SECRET))
        self.before_write = None
        self.app = self.make_app()

    def write(self, fn):
        if self.before_write:
            change, self.before_write = self.before_write, None
            change()
        return fn(self.st)

    def make_app(self, **changes):
        options = dict(open_read=lambda: self.st, write=self.write, signer=self.signer, profiles=None,
                       clock=self.fc.now, owner_verification=True, verified_linking=True)
        options.update(changes)
        return TW.WEB.App(**options)

    def post(self, path, actor=100, body=None):
        return self.call("POST", path, self.signer.issue(actor, self.fc.now()), body=body)[:2]

    def get(self, path, actor=100, query=""):
        return self.call("GET", path, self.signer.issue(actor, self.fc.now()), query=query)[:2]

    def update_body(self, cid=TW.A, **changes):
        row = next(row for row in self.st.account_rows if row["customer_id"] == cid)
        return {"ad_account_no": str(row["ad_account_no"]), "stage_revision": self.st.states[cid]["stage_revision"],
                "included": False, "reason": "관제 점검 변경", **changes}

    def test_staff_can_update_only_current_own_account_without_exposing_customer_id(self):
        status, body = self.post("/management/update", body=self.update_body())
        self.assertEqual(status, 200)
        self.assertEqual(body, {"updated": True, "stage_revision": "rev-11", "included": False})
        self.assertEqual(self.st.saved, [(TW.A, "rev-11", False, 100, "관제 점검 변경")])
        self.assertEqual(self.post("/management/update", body=self.update_body(TW.B))[0], 404)
        self.assertEqual(len(self.st.saved), 1)

    def test_manual_collection_is_individual_scoped_and_never_returns_raw_customer_id(self):
        body = {"ad_account_no": self.update_body()["ad_account_no"]}
        self.assertEqual(self.post("/management/collect", body=body), (200, {"status": "accepted"}))
        self.assertEqual(self.st.requests, [(TW.A, 100)])
        self.assertEqual(self.post("/management/collect", body={"ad_account_no": self.update_body(TW.B)["ad_account_no"]})[0], 404)
        unmatched = str(self.st.account_rows[2]["ad_account_no"])
        self.assertEqual(self.post("/management/collect", body={"ad_account_no": unmatched})[0], 404)
        self.assertEqual(self.post("/management/collect", 0, {"ad_account_no": unmatched})[0], 200)

    def test_writer_queue_revalidates_owner_and_stage_revision_before_mutation(self):
        def transfer():
            self.st.org["body"]["owners"][0]["manage_emp_idx"] = 101
        self.before_write = transfer
        self.assertEqual(self.post("/management/update", body=self.update_body())[0], 404)
        self.assertEqual(self.st.saved, [])
        self.st.org["body"]["owners"][0]["manage_emp_idx"] = 100
        body = self.update_body()
        self.before_write = lambda: self.st.states[TW.A].update(stage_revision="new-stage")
        self.assertEqual(self.post("/management/update", body=body), (409, {"error": "stage-changed"}))
        self.assertEqual(self.st.saved, [])

    def test_dated_collection_rechecks_account_mapping_and_owner_in_queue(self):
        body = {"ad_account_no": self.update_body()["ad_account_no"], "possibility_id": 11,
                "period_start": "2026-08-01", "period_end": "2026-08-31"}
        self.assertEqual(self.post("/management/collect", body=body)[0], 200)
        self.assertEqual(len(self.st.requests), 1)
        self.assertEqual(self.post("/management/collect", body={**body, "possibility_id": 12})[0], 404)
        self.before_write = lambda: self.st.org["body"]["owners"][0].update(manage_emp_idx=101)
        self.assertEqual(self.post("/management/collect", body=body)[0], 404)
        self.assertEqual(len(self.st.requests), 1)

    def test_reports_read_only_current_scope_and_saved_payload_without_external_reads(self):
        self.st.reports = [dict(report_id=pid, possibility_id=pid, period_key="monthly:2026-09",
                               revision_fingerprint=f"revision-{pid}", generated_at=self.fc.now().isoformat(),
                               status="ready", validation={"status": "complete"},
                               review_status="needs_staff_review", payload={"totals": {"spend": 10}})
                           for pid in (11, 12)]
        status, body = self.get("/reports")
        self.assertEqual(status, 200)
        self.assertEqual([r["report_id"] for r in body["rows"]], [11])
        self.assertTrue(body["rows"][0]["can_review"])
        self.assertEqual(body["rows"][0]["company_name"], f"계정{TW.A}")
        self.assertEqual(body["schedule"]["monthly"], "매월 3일 10:00")
        self.assertEqual(self.get("/reports", query="selection=person:101")[0], 404)
        self.assertEqual(len(self.get("/reports", actor=0)[1]["rows"]), 2)
        self.assertEqual(self.st.saved + self.st.requests + self.st.reviews, [])

    def test_management_body_and_duplicate_ad_number_are_rejected_before_mutation(self):
        for change in ({"included": "false"}, {"customer_id": TW.A}, {"reason": " "},
                       {"ad_account_no": "1.0"}, {"stage_revision": ""}):
            with self.subTest(change=change):
                self.assertEqual(self.post("/management/update", body=self.update_body(**change))[0], 400)
        self.st.account_rows[1]["ad_account_no"] = self.st.account_rows[0]["ad_account_no"]
        self.assertEqual(self.post("/management/update", body=self.update_body())[0], 404)
        self.assertEqual(self.st.saved, [])

    def test_existing_read_only_mode_and_unapproved_writes_remain_closed(self):
        self.app = self.make_app(verified_linking=False)
        self.assertEqual(self.post("/management/update", body=self.update_body())[0], 403)
        self.assertEqual(self.post("/management/collect", body={"ad_account_no": "123"})[0], 403)
        self.app = self.make_app()
        for path in ("/links/reject", "/links/revoke", "/links/preview", "/settings/thresholds", "/issues/1/ack"):
            with self.subTest(path=path):
                self.assertEqual(self.post(path, actor=0, body={})[0], 403)
        self.assertEqual(self.st.saved, [])

    def test_report_review_requires_current_owner_and_complete_report_for_approval(self):
        self.st.reports = [dict(report_id=31, possibility_id=11, status="ready", validation={"status": "complete"},
                               review_status="needs_staff_review")]
        request = {"report_id": 31, "decision": "approved", "note": "저장 수치 확인"}
        self.assertEqual(self.post("/reports/review", body=request), (200, {"report_id": 31, "review_status": "approved"}))
        self.assertEqual(self.st.reviews, [(31, 100, "approved", "저장 수치 확인")])
        self.assertEqual(self.post("/reports/review", actor=101, body=request)[0], 404)
        self.st.reports[0]["status"] = "partial"
        self.assertEqual(self.post("/reports/review", body=request), (409, {"error": "report-incomplete"}))
        self.assertEqual(self.post("/reports/review", body={**request, "decision": "held"})[0], 200)
        self.assertEqual(len(self.st.reviews), 2)

    def test_staff_can_confirm_own_uncontested_current_number_match(self):
        now = self.fc.now()
        self.st.pairing = dict(pairing_id=1, at=now, accounts_read_at=now, stages_as_of=now)
        self.st.pair_rows = [dict(possibility_id=11, customer_id=TW.A, state="auto", code="same",
                                  same_name=1, claimed_elsewhere=False)]
        ref = TW.W.make_ref(1, 11, TW.A, "auto")
        self.assertEqual(self.post("/links/confirm", body={"refs": [ref]}),
                         (200, {"decided": 1, "decision": "confirmed"}))
        self.assertEqual(self.st.decisions[0].possibility_id, 11)

    def test_staff_cannot_confirm_another_owner_or_claimed_account(self):
        now = self.fc.now()
        self.st.pairing = dict(pairing_id=1, at=now, accounts_read_at=now, stages_as_of=now)
        self.st.pair_rows = [dict(possibility_id=12, customer_id=TW.B, state="auto", code="same",
                                  same_name=1, claimed_elsewhere=False)]
        ref = TW.W.make_ref(1, 12, TW.B, "auto")
        self.assertEqual(self.post("/links/confirm", body={"refs": [ref]})[0], 404)
        self.st.pair_rows = [dict(possibility_id=11, customer_id=TW.A, state="auto", code="same",
                                  same_name=1, claimed_elsewhere=True)]
        ref = TW.W.make_ref(1, 11, TW.A, "auto")
        self.assertEqual(self.post("/links/confirm", body={"refs": [ref]})[0], 409)
        self.assertEqual(self.st.decisions, [])

    def test_report_review_rechecks_transfer_and_token_expiry_inside_writer(self):
        self.st.reports = [dict(report_id=31, possibility_id=11, status="ready", review_status="needs_staff_review")]
        request = {"report_id": 31, "decision": "approved", "note": "검수"}
        self.before_write = lambda: self.st.org["body"]["owners"][0].update(manage_emp_idx=101)
        self.assertEqual(self.post("/reports/review", body=request)[0], 404)
        self.st.org["body"]["owners"][0]["manage_emp_idx"] = 100
        self.before_write = lambda: self.fc.advance(24 * 3600)
        self.assertEqual(self.post("/reports/review", body=request)[0], 401)
        self.assertEqual(self.st.reviews, [])

    def test_catalog_only_company_reports_remain_visible_but_hidden_stage_blocks_staff(self):
        self.st.prospects = lambda: []
        self.st.catalog["items"][0]["stage"] = "환불완료"
        self.st.reports = [dict(report_id=31, possibility_id=11, status="ready", review_status="needs_staff_review", payload={})]
        status, body = self.get("/reports")
        self.assertEqual(status, 200)
        self.assertEqual([r["report_id"] for r in body["rows"]], [31])
        self.assertEqual(self.post("/reports/review", body={"report_id": 31, "decision": "held", "note": "이력 검토"})[0], 200)
        self.st.catalog["items"][0]["stage_hidden"] = True
        self.assertEqual(self.get("/reports")[1]["rows"], [])
        self.assertEqual(self.post("/reports/review", body={"report_id": 31, "decision": "held", "note": "이력 검토"})[0], 404)
        self.st.catalog_state["state"] = "failed"
        self.assertEqual(self.get("/reports"), (503, {"error": "catalog-stale"}))

    def test_denied_management_write_is_audited_without_raw_account_identifiers(self):
        self.assertEqual(self.post("/management/update", body=self.update_body(TW.B))[0], 404)
        self.assertEqual(self.st.audit[-1][1:5], ("management-update", "board", None, "denied"))
        self.assertNotIn(str(TW.B), str(self.st.audit))
