"""Linux의 실제 SQLite와 기존 읽기/짝/점검 경로를 통과하는 즉시 수집 통합 시험."""
from datetime import timedelta
import platform
from unittest import skipUnless

from app.naver_auto.matching import VENDOR_NAVER
from naver_engine import erp_read as E, naver_read as N, store as S
from naver_engine.tests.fake_naver import Agency
from naver_engine.tests.test_morning import Base, A, B, T0, srow, shop, creds
from naver_engine.tests.test_sync import org_payload
from naver_runtime.collection_requests import CollectionClock
from naver_runtime.scheduler import Scheduler
from naver_runtime.tests.test_collection_requests import enabled


@skipUnless(platform.system() == "Linux", "실제 Store 잠금은 Linux 전용이며 우회하지 않습니다")
class CollectionIntegrationTest(Base):
    def collection(self):
        now = T0.replace(hour=14)
        self.scene(t=now)
        self.standard_ads()
        self.st.record_org(org_payload(now - timedelta(minutes=1)), now)
        agency = Agency(self.naver, sizes=(2,))
        agency.children[101] = [dict(customerId=cid, adAccountNo=8_000_000 + cid % 1_000_000,
                                    adAccountName=shop(pid), accountRole="MASTER") for pid, cid in ((11, A), (12, B))]
        events, owner = [], self
        class Reader:
            def __init__(self):
                self.calls = 0
            def read_org_snapshot(self):
                self.calls += 1
                events.append("org")
                return org_payload(owner.fc.now())
            def read_stages(self, deadline=None):
                self.calls += 1
                events.append("stages")
                return E.StageSnapshot({p: srow(p) for p in (11, 12)}, owner.fc.now(), {}, ())
            def read_naver_customer_ids(self):
                self.calls += 1
                events.append("pairing")
                return (E.NaverIdRow(12, VENDOR_NAVER, str(B)),)
        def factory():
            clock = CollectionClock(owner.fc)
            return dict(clock=clock, erp_factory=Reader,
                        naver_factory=lambda: N.NaverReader(creds(), transport=owner.naver, clock=clock))
        task = Scheduler(enabled(), self.st, collection_factory=factory, clock=self.fc.now)
        return task, events

    def test_afternoon_request_uses_current_day_gets_and_existing_check_results(self):
        task, events = self.collection()
        requested = task.request_collection(0)
        self.assertEqual(requested["status"], "accepted")
        self.assertEqual(len(self.naver.calls), 0)
        task.tick()
        result = task.collection_status()
        self.assertEqual(result["status"], "done", result)
        self.assertEqual(result["counts"].get("targets"), 2)
        self.assertEqual(result["counts"].get("ok"), 2)
        self.assertEqual(events, ["org", "stages", "pairing"])
        self.assertTrue(all(call.method == "GET" for call in self.naver.calls))
        self.assertEqual(self.day(A)["status"], "ok")
        self.assertEqual(self.st.runs_on(self.fc.now().date())[0]["started_at"][:10], self.fc.now().date().isoformat())
        self.assertEqual(task.request_collection(0)["codes"], ["RETRY_NOT_DUE"])

    def test_failed_account_is_partial_not_done(self):
        task, _events = self.collection()
        self.ads.fail[(A, "camps")] = (403, {"code": 403})
        task.request_collection(0)
        task.tick()
        result = task.collection_status()
        self.assertEqual(result["status"], "partial", result)
        self.assertGreater(result["counts"].get("key_rejected", 0), 0)

    def test_earlier_zero_target_run_does_not_hide_newly_matched_accounts(self):
        task, _events = self.collection()
        old = self.fc.now() - timedelta(hours=1)
        run_id = self.st.begin_run(old.date(), old)
        self.st.finish_run(run_id, S.RUN_DONE, old + timedelta(minutes=1), accounts_total=0, accounts_ok=0)
        self.assertEqual(task.request_collection(0)["status"], "accepted")
        task.tick()
        result = task.collection_status()
        self.assertEqual(result["status"], "done", result)
        self.assertEqual(result["counts"].get("ok"), 2)
        self.assertEqual(len(self.st.runs_on(self.fc.now().date())), 2)
