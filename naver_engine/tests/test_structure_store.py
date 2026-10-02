"""실제 SQLite 구조 큐의 재개/단계 변경/일요일 주기. 외부 HTTP는 합성이다."""
from datetime import datetime, timedelta
import socket
from unittest.mock import patch

from naver_engine import erp_read as E, structure_reads as R, store as S
from naver_engine.tests import test_morning as TM, test_alerts as TA, test_account_catalog as TC
from naver_engine.tests.fake_naver import FakeNaver
from app.naver_auto import matching as M


class StructureStoreTest(TM.Base):
    def setUp(self):
        guard=patch.object(socket.socket,"connect",side_effect=AssertionError("외부 송신 금지"))
        guard.start();self.addCleanup(guard.stop)
        super().setUp()
        self.company=TM.NAMES.get(TM.A,f"계정{TM.A}")
        self.refresh()
        self.stage("진행중")
        # Base의 Ads 라우트는 첫 일치 방식이므로 구조 전용 전송 경계를 새로 만든다.
        self.naver = FakeNaver()
        self.naver.route(r"/ncc/campaigns",lambda call:(200,[{"customerId":TM.A,"nccCampaignId":"cmp-one",
            "status":"PAUSED","statusReason":"CAMPAIGN_PAUSED"}]))
        self.naver.route(r"/ncc/(channels|adgroups|ad-extensions)",lambda call:(200,[]))

    def refresh(self):
        self.st.record_org(TA.org_body(self.fc.now()),self.fc.now())
        self.st.record_accounts(TM.kids(TM.A),self.fc.now())

    def stage(self,value):
        self.st.record_account_catalog({"generated_at":self.fc.now().isoformat(),"total":1,"complete":True,
            "items":[TC.company(11,value,company_name=self.company)]},
            [E.NaverIdRow(11,M.VENDOR_NAVER,str(TM.A))],self.fc.now())

    def test_checkpoint_restart_and_read_only_reason_projection(self):
        self.assertEqual(R.run_structure(self.reader(),self.st,self.fc.now,max_calls=2).counts,{"partial":1})
        self.assertEqual(self.st.structure_checks([TM.A],self.fc.now())[TM.A]["status"],"partial")
        self.st.close();self.st=S.open_writer(self.path,clock=self.fc.now)
        self.fc.advance(61)
        self.assertEqual(R.run_structure(self.reader(),self.st,self.fc.now).counts,{"ok":1})
        row=self.st.structure_checks([TM.A],self.fc.now())[TM.A]
        self.assertEqual(row["reasons"][0]["reason"]["code"],"CAMPAIGN_PAUSED")
        self.assertEqual(self.st.structure_work(self.fc.now()),[])
        self.assertEqual(sum(call.path=="/ncc/channels" for call in self.naver.calls),1)

    def test_finished_old_stage_is_not_reused_after_stage_revision_change(self):
        self.assertEqual(R.run_structure(self.reader(),self.st,self.fc.now).counts,{"ok":1})
        first=self.st.management_states()[TM.A]["stage_revision"]
        self.fc.advance(1);self.stage("사후 관리")
        job=self.st.structure_work(self.fc.now())[0]
        self.assertNotEqual(job["stage_revision"],first)
        self.st.begin_structure_check(job,self.fc.now())
        self.assertIsNone(self.st.structure_progress(job))

    def test_nonmanaged_is_sunday_only_but_started_cycle_resumes_monday(self):
        self.stage("환불 완료")
        self.assertEqual(self.st.structure_work(self.fc.now()),[])
        sunday=datetime(2026,10,4,9,tzinfo=S.KST)
        self.fc.advance((sunday-self.fc.now()).total_seconds());self.refresh();self.stage("환불 완료")
        self.assertEqual(R.run_structure(self.reader(),self.st,self.fc.now,max_calls=2).counts,{"partial":1})
        first=self.st.structure_work(self.fc.now())[0]
        self.fc.advance(24*3600);self.refresh();self.stage("환불 완료")
        self.assertEqual(self.st.structure_work(self.fc.now())[0]["job_key"],first["job_key"])
        self.assertEqual(R.run_structure(self.reader(),self.st,self.fc.now).counts,{"ok":1})
