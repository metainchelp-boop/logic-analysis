"""상세점검 진행자료의 실제 Writer 왕복과 고정 슬롯/저장 경계."""
from datetime import timedelta
import unittest

from naver_engine import store as S, morning_progress as P
from naver_engine.tests import test_morning as TM
from naver_engine.tests.test_catalog_links import make_fixture
from naver_runtime.writer import Writer


class MorningProgressProxyTests(unittest.TestCase):
    def setUp(self):
        fixtures = []
        def factory(path, clock=None):
            fixture = make_fixture(accounts=1,managed=1,campaigns=0)
            fixtures.append(fixture)
            return fixture.store
        self.writer = Writer("synthetic-memory",factory=factory)
        self.addCleanup(self.writer.close)
        self.proxy = self.writer.proxy
        self.clock = fixtures[0].clock
        self.writer.call(lambda st: st._conn.set_authorizer(S._authorizer(S.PHASE_RUN)))
        self.payload = {"ids":[f"cmp-{TM.A}-1"],"rows":{},"cycle":None}

    def begin(self, fingerprint="a"*64):
        return self.proxy.begin_morning_progress(TM.A,11,self.clock.now().date(),fingerprint,self.clock.now())

    def test_writer_roundtrip_detaches_values_and_reuses_only_current_generation_slots(self):
        for index in range(3):
            head = self.begin(str(index)*64)
            self.proxy.record_morning_progress(TM.A,head["generation"],"summary",0,self.payload,self.clock.now())
            returned = self.proxy.morning_progress(TM.A,11,self.clock.now().date(),self.clock.now())
            returned["chunks"].clear()
            self.assertEqual(len(self.proxy.morning_progress(TM.A,11,self.clock.now().date(),self.clock.now())["chunks"]),1)
            self.proxy.finish_morning_progress(TM.A,head["generation"],self.clock.now())
        head = self.begin("f"*64)
        self.assertEqual(head["chunks"],{})
        self.assertEqual(self.writer.call(lambda st: st._conn.execute("SELECT COUNT(*) FROM naver_auto_morning_progress").fetchone()[0]),1)
        self.assertEqual(self.writer.call(lambda st: st._conn.execute("SELECT COUNT(*) FROM naver_auto_morning_chunk").fetchone()[0]),1)
        with self.assertRaises(S.StoreRefused):
            self.proxy.record_morning_progress(TM.A,head["generation"]-1,"summary",0,self.payload,self.clock.now())

    def test_invalid_identity_generation_time_and_slots_are_rejected_without_mutation(self):
        head = self.begin()
        for cid,generation,now in ((True,1,self.clock.now()),(TM.A,True,self.clock.now()),
                (TM.A,-1,self.clock.now()),(TM.A,1,self.clock.now()+timedelta(hours=1))):
            with self.subTest(cid=cid,generation=generation,now=now):
                with self.assertRaises(S.StoreRefused):
                    self.proxy.record_morning_progress(cid,generation,"summary",0,self.payload,now)
                with self.assertRaises(S.StoreRefused):
                    self.proxy.finish_morning_progress(cid,generation,now)
        for kind,slot in (("summary",100),("daily",10000),("other",0),("daily",True)):
            with self.subTest(kind=kind,slot=slot),self.assertRaises(P.ProgressCorrupt):
                self.proxy.record_morning_progress(TM.A,head["generation"],kind,slot,self.payload,self.clock.now())
        self.assertEqual(self.proxy.morning_progress(TM.A,11,self.clock.now().date(),self.clock.now())["chunks"],{})
        with self.assertRaises(S.StoreRefused):
            self.proxy.begin_morning_progress(TM.A,True,self.clock.now().date(),"a"*64,self.clock.now())
        with self.assertRaises(S.StoreRefused):
            self.proxy.begin_morning_progress(TM.A,11,self.clock.now().date(),"a"*64,self.clock.now()+timedelta(hours=1))


if __name__ == "__main__":
    unittest.main()
