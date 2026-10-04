"""실제 Writer 큐·proxy와 메모리 Store의 자동 연결 숫자 근거 전달 회귀."""
import unittest

from app.naver_auto import matching as M
from naver_engine import erp_read as E, management_store as MS
from naver_engine.tests import test_morning as TM
from naver_engine.tests.test_catalog_links import make_fixture
from naver_runtime.writer import Writer
from naver_runtime.scheduler import _ManagedMorningStore


class AutomaticIdentityProxyTest(unittest.TestCase):
    def test_real_writer_proxy_keeps_auto_link_after_company_rename(self):
        fixtures = []

        def factory(path, clock=None):
            fixture = make_fixture(accounts=5, managed=1, campaigns=0)
            fixtures.append(fixture)
            return fixture.store  # 연결은 실제 writer 스레드에서 생성·조회·종료한다.

        with Writer("synthetic-memory", factory=factory) as writer:
            clock = fixtures[0].clock

            def seed(store):
                for decision in store.current_decisions():
                    store.revoke_decision(decision.decision_id, 0, clock.now(), "합성 자동 연결")
                return store.synchronize_management(clock.now())[TM.A]

            before = writer.call(seed)
            history = writer.call(lambda store: store.link_decisions())

            def rename(store):
                clock.advance(1)
                catalog = store.account_catalog()
                store.record_account_catalog({"generated_at": clock.now().isoformat(), "total": 1,
                    "complete": True, "items": [{**catalog["items"][0], "company_name": "전혀 달라진 상호"}]},
                    [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))], clock.now())

            writer.call(rename)
            # scheduler는 synchronize_management의 반환 대신 proxy로 이 읽기 어댑터를 부른다.
            row = MS.snapshot(writer.proxy, clock.now())[TM.A]
            self.assertEqual(row["possibility_id"], 11)
            self.assertEqual(row["decision"].cadence, "daily")
            self.assertEqual(row["stage_revision"], before["stage_revision"])
            self.assertEqual(writer.call(lambda store: store.link_decisions()), history)
            morning = _ManagedMorningStore(writer.proxy, clock.now())
            self.assertIn(TM.A, morning.daily)
            self.assertEqual([(r["possibility_id"], r["customer_id"], r["state"])
                              for r in morning.pairing_rows(None)], [(11, TM.A, "auto")])
            self.assertIsNotNone(morning.monitoring_context(TM.A, 11, clock.now()))
            evidence = writer.proxy.automatic_link_evidence()
            self.assertIn((11, TM.A), evidence)
            evidence.clear()
            self.assertIn((11, TM.A), writer.proxy.automatic_link_evidence())
            for name in ("close", "_conn", "_tx", "record_thresholds"):
                with self.subTest(name=name), self.assertRaises(AttributeError):
                    getattr(writer.proxy, name)


if __name__ == "__main__":
    unittest.main()
