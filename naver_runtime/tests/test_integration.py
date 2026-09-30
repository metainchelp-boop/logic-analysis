"""Linux 실제 WAL+단일 writer+예약 core 연동. 네이버/ERP 응답은 모두 합성이다."""
from datetime import timedelta
import os
from pathlib import Path
import platform
import tempfile
import threading
import unittest

from naver_engine import store as S, sync as Y
from naver_engine.tests import test_morning as TM, test_alerts as TA, test_sync as TS, test_erp_alert as TEA
from naver_runtime.config import Config
from naver_runtime.scheduler import Scheduler
from naver_runtime.writer import Writer


@unittest.skipUnless(platform.system() == "Linux", "실제 flock/WAL 실행 계약은 Linux에서 검증")
class LinuxIntegrationTest(unittest.TestCase):
    def test_real_actor_morning_fake_api_and_heartbeat_without_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "engine.db")
            fixture = TM.Base()
            fixture.fc = TM.FakeClock(TM.T0)
            fixture.naver = TM.FakeNaver()
            fixture.ads = TM.Ads(fixture.naver)
            fixture.standard_ads()
            poster = TEA.FakeAlertErp()
            with Writer(path, clock=fixture.fc.now) as writer:
                def seed(store):
                    fixture.st = store
                    fixture.scene()
                    Y.sync_org(TS.FakeErp(org=TA.org_body(fixture.fc.now())), store, fixture.fc.now())
                writer.call(seed)
                def erp():
                    return TS.FakeErp(org=TA.org_body(fixture.fc.now()))
                cfg = Config.from_env({"NAVER_ENGINE_DB": path, "NAVER_ENGINE_SOCKET": folder + "/sock/api",
                                       "NAVER_ENGINE_SYNC_ENABLED": "true", "NAVER_ENGINE_LINKS_ENABLED": "true",
                                       "NAVER_ENGINE_MORNING_ENABLED": "true", "NAVER_ENGINE_ALERTS_ENABLED": "true"})
                scheduler = Scheduler(cfg, writer.proxy, clock=fixture.fc.now, erp_factory=erp,
                                      naver_factory=fixture.reader, alert_factory=lambda: TEA.poster(poster))
                first = scheduler.tick()
                self.assertEqual(first["state"], "ok", first)
                self.assertEqual(len(writer.proxy.account_days_on(TM.TODAY)), 2)
                runs = writer.proxy.runs_on(TM.TODAY)
                self.assertEqual([r["status"] for r in runs], [S.RUN_DONE])
                fixture.fc._now = TM.T0.replace(hour=8, minute=0)
                self.assertEqual(scheduler.tick()["state"], "ok")
                beat = writer.proxy.heartbeat()
                self.assertIsNotNone(beat)
                calls = len(poster.calls)
                scheduler.tick()
                self.assertEqual(len(poster.calls), calls)
                self.assertTrue(all(call.method == "GET" for call in fixture.naver.calls))
                with self.assertRaises(S.StoreBusy):
                    S.open_writer(path)
            with S.open_reader(path) as reader:
                self.assertEqual(len(reader.runs_on(TM.TODAY)), 1)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_real_writer_keeps_network_wait_outside_actor(self):
        with tempfile.TemporaryDirectory() as folder, Writer(str(Path(folder) / "engine.db")) as writer:
            entered, release = threading.Event(), threading.Event()
            def slow_network():
                entered.set()
                release.wait(5)
            thread = threading.Thread(target=slow_network)
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertEqual(writer.proxy.runs_on(TM.TODAY), [])
            finally:
                release.set()
                thread.join(5)
