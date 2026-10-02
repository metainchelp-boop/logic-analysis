"""실제 Chromium→중계→WSGI→Store. 원천과 로그인만 합성이며 외부 호출은 없다."""
import json
import os
from pathlib import Path
import subprocess
import time

from naver_engine import erp_read as E
from naver_engine.tests import test_screen as TS, test_web as TW, test_morning as TM
from app.naver_auto import matching as M


class ManagementScreenTest(TS.BrowserTest):
    def make_app(self, **kw):
        return super().make_app(owner_verification=True, verified_linking=True, **kw)

    def test_screen_in_real_browser(self):
        items=[{"possibility_id":pid,"company_name":TM.NAMES[cid],"stage":stage,
                "stage_known":True,"stage_hidden":False}
               for pid,cid,stage in ((11,TM.A,"진행중"),(12,TM.B,"환불 완료"))]
        self.st.record_account_catalog({"generated_at":self.fc.now().isoformat(),"total":2,
            "complete":True,"items":items}, [E.NaverIdRow(pid,M.VENDOR_NAVER,str(cid))
            for pid,cid in ((11,TM.A),(12,TM.B))],self.fc.now())
        self.st.synchronize_management(self.fc.now())
        accounts={r["customer_id"]:r for r in self.st.accounts()}
        cfg={"base":self.base,"ceo":TW.tok(1),"staff":TW.tok(3),"now":self.fc.now().isoformat(),
             "own":str(accounts[TM.A]["ad_account_no"]),"other":str(accounts[TM.B]["ad_account_no"]),
             "shots":os.environ.get("NAVER_SCREEN_SHOTS")}
        proc=subprocess.Popen([self.node,str(Path(__file__).with_name("management_screen_browser.js")),json.dumps(cfg)],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=self.node_env)
        deadline=time.monotonic()+90
        while proc.poll() is None and time.monotonic()<deadline:
            self.engine.handle_request()
        if proc.poll() is None:
            proc.kill()
        out,err=proc.communicate(timeout=10)
        self.assertEqual(proc.returncode,0,err[-6000:])
        self.assertIn("management-screen-ok",out)
        self.assertEqual(self.stray,[])
        self.assertEqual(self.st.account_catalog()["items"],items)
