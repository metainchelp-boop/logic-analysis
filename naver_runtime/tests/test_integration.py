"""Linux 실제 WAL+단일 writer+예약 core 연동. 네이버/ERP 응답은 모두 합성이다."""
from datetime import timedelta
import os
from pathlib import Path
import platform
import tempfile
import threading
import unittest
from unittest.mock import patch

from naver_engine import store as S, sync as Y
from naver_engine.tests import test_morning as TM, test_alerts as TA, test_sync as TS, test_erp_alert as TEA
from naver_runtime.config import Config
from naver_runtime.scheduler import Scheduler
from naver_runtime.writer import Writer
from naver_runtime import __main__ as main


class AssemblyStopTest(unittest.TestCase):
    def test_alert_assembly_never_starts_another_post_after_stop(self):
        stop = threading.Event()
        fake = TEA.FakeAlertErp()

        class Transport:
            def send(self, request, timeout):
                result = fake.send(request, timeout)
                stop.set()  # 첫 응답 뒤 SIGTERM 처리기가 올린 것과 같은 중지 상태.
                return result

        config = Config("/synthetic/data/db", "/synthetic/socket/api", alerts_enabled=True)
        # 수정 전·후 양쪽의 기본 전송 생성자를 막는다. 실제 회사 요청은 절대 만들지 않는다.
        with patch.object(main.EA, "UrllibTransport", return_value=Transport()), \
             patch.object(main.N, "UrllibTransport", return_value=Transport()):
            clock = main.InterruptibleClock(stop)
            options = main.dependencies(config, {"NAVER_ENGINE_ERP_KEY": TEA.MARK_KEY},
                                        clock)
            poster = options["alert_factory"]()
            poster.send_alert(TEA.payload(dedupe_key="shutdown:first"))
            with self.assertRaises(main.StopRequested):
                poster.send_alert(TEA.payload(dedupe_key="shutdown:second"))
            self.assertIsNotNone(clock.now().tzinfo)  # 중단 회차 DB 정리용 시각은 계속 받는다.
            with self.assertRaises(main.StopRequested):
                poster.send_alert(TEA.payload(dedupe_key="shutdown:third"))
        self.assertEqual(len(fake.calls), 1)


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
            response = TA.org_body(TM.T0)

            class SlowErp(TS.FakeErp):
                def read_org_snapshot(self):
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError("합성 전산 읽기 시험 시간 초과")
                    return super().read_org_snapshot()

            config = Config(str(Path(folder) / "engine.db"), folder + "/socket/api", sync_enabled=True)
            # 06:40은 계약 단계의 조용한 창이다. 실제 org_due/sync_org만 느린 ERP에서 멈춘다.
            scheduler = Scheduler(config, writer.proxy, clock=lambda: TM.T0,
                                  erp_factory=lambda: SlowErp(org=response))
            outcome = []
            thread = threading.Thread(target=lambda: outcome.append(scheduler.tick()))
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                # 실제 예약 작업이 외부 응답을 기다리는 사이 같은 writer가 DB 요청을 처리한다.
                self.assertEqual(writer.call(lambda st: st.runs_on(TM.TODAY), wait=.5), [])
                self.assertTrue(thread.is_alive())
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcome, [{"state": "ok", "errors": []}])
            self.assertIsNotNone(writer.proxy.org_current())
