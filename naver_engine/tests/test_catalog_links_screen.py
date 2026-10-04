"""catalog-only 업체 이동·확인을 실제 Chromium→중계→WSGI→Store로 검사한다."""
import json
import os
from pathlib import Path
import subprocess
import time
from datetime import timedelta

from naver_engine import erp_read as E, links as L
from naver_engine.tests import test_screen as TS, test_web as TW, test_morning as TM
from app.naver_auto import matching as M


class CatalogLinksScreenTest(TS.BrowserTest):
    def make_app(self, **kw):
        return super().make_app(owner_verification=True, verified_linking=True, **kw)

    def test_screen_in_real_browser(self):
        self.run_catalog_browser()

    def test_old_contract_end_allows_current_owner_confirmation_in_real_browser(self):
        self.run_catalog_browser(expired_contract=True)

    def run_catalog_browser(self, *, expired_contract=False):
        now = self.fc.now()
        for decision in self.st.current_decisions():
            self.st.revoke_decision(decision.decision_id, 0, now, "합성 미확정 사례")
        prospects = {p: TM.srow(p) for p in (12, 13, 14)}
        if expired_contract:
            prospects[11] = TM.srow(11, end=now.date() - timedelta(days=120))
        self.st.record_prospects(E.StageSnapshot(prospects, now, {}, ()))
        company = "합성연결누락상호"
        items = [{"possibility_id": pid, "company_name": name, "stage": "진행중",
                  "stage_known": True, "stage_hidden": False}
                 for pid, name in ((11, company), (12, TM.NAMES[TM.B]))]
        ids = [E.NaverIdRow(pid, M.VENDOR_NAVER, str(cid)) for pid, cid in ((11, TM.A), (12, TM.B))]
        self.st.record_account_catalog({"generated_at": now.isoformat(), "total": 2,
            "complete": True, "items": items}, ids, now)
        L.pair_links(TM.FakeErp(ids), self.st, now)
        accounts = {r["customer_id"]: r for r in self.st.accounts()}
        cfg = {"base": self.base, "ceo": TW.tok(1), "staff": TW.tok(3), "now": now.isoformat(),
               "own": str(accounts[TM.A]["ad_account_no"]), "pid": 11, "company": company,
               "expired_contract": expired_contract,
               "other_company": TM.NAMES[TM.B], "shots": os.environ.get("NAVER_SCREEN_SHOTS")}
        proc = subprocess.Popen([self.node, str(Path(__file__).with_name("catalog_links_screen_browser.js")),
            json.dumps(cfg)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.node_env)
        deadline = time.monotonic() + 90
        while proc.poll() is None and time.monotonic() < deadline:
            self.engine.handle_request()
        if proc.poll() is None:
            proc.kill()
        out, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, err[-6000:])
        self.assertIn("catalog-links-screen-ok", out)
        self.assertEqual(self.stray, [])
        self.assertEqual(self.st.account_catalog()["items"], items)
        confirmed = [d for d in self.st.current_decisions() if d.decision == "confirmed"]
        self.assertEqual([(d.possibility_id, d.customer_id) for d in confirmed], [(11, TM.A)])
        self.assertEqual(bool(next(p for p in self.st.prospects() if p["possibility_id"] == 11)["present"]),
                         expired_contract)
