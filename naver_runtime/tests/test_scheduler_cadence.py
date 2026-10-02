"""예약 회차 간격은 실제 읽기 코드와 합성 시계·전송기로 검증한다."""
from contextlib import ExitStack
from datetime import datetime, timedelta
import socket
from threading import Event, Thread
from unittest import TestCase
from unittest.mock import Mock, patch

from naver_engine import links as L, inventory as IC, naver_read as N, store as S, morning as M
from naver_engine.tests.fake_naver import FakeClock, FakeNaver
from naver_engine.tests.test_morning import A as CUSTOMER, creds
from naver_engine.tests.test_performance_reads import MemoryPerformance
from naver_engine.tests.test_structure_collector import MemoryStructure
from naver_runtime.config import Config
from naver_runtime.scheduler import Scheduler
from naver_runtime import __main__ as main


NOW = datetime(2026, 10, 15, 7, 20, tzinfo=S.KST)


class SchedulerCadenceTests(TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.context.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지")))
        self.context.enter_context(patch.object(L, "accounts_due", return_value=False))
        self.context.enter_context(patch.object(IC, "sync_catalog_due", return_value=False))
        self.clock, self.http = FakeClock(NOW), FakeNaver()
        self.store = MemoryPerformance(self.clock)
        self.store.jobs = []
        self.store.structure_work = lambda now, limit: []
        self.store.account_catalog_status = lambda: {"at": self.clock.now().isoformat()}
        self.reports = []
        self.store.generate_reports = lambda now: self.reports.append(self.clock.monotonic())
        self.readers = []

    def scheduler(self, **switches):
        def reader():
            item = N.NaverReader(creds(), transport=self.http, clock=self.clock)
            self.readers.append(item)
            return item
        return Scheduler(Config("/synthetic/data/db", "/synthetic/socket/sock", **switches),
                         self.store, naver_factory=reader, clock=self.clock.now,
                         monotonic_clock=self.clock.monotonic)

    def performance_jobs(self, count=1):
        self.store.jobs = [{"customer_id": CUSTOMER+n, "kind": "daily", "cycle_day": "2026-10-15",
                            "period_start": "2026-10-14", "period_end": "2026-10-14",
                            "snapshot_at": self.clock.now(), "job_key": f"daily-{n}"} for n in range(count)]
        self.http.route(r"/ncc/campaigns", lambda call: (200, []))
        self.http.route(r"/billing/bizmoney", lambda call: (200, {"customerId": int(call.customer),
                        "bizmoney": 100, "budgetLock": False, "refundLock": False}))

    def structure_jobs(self, count=1):
        structures = MemoryStructure(self.clock)
        structures.jobs = [{"customer_id": CUSTOMER+100+n, "kind": "daily", "cycle_day": "2026-10-15",
                            "snapshot_at": self.clock.now(), "job_key": f"structure-{n}"} for n in range(count)]
        for name in ("structure_work", "structure_account_valid", "begin_structure_check", "structure_progress",
                     "record_structure_progress", "record_structure_check"):
            setattr(self.store, name, getattr(structures, name))
        self.http.route(r"/ncc/channels", lambda call: (200, []))
        return structures

    def test_short_inventory_tick_waits_only_until_30_seconds_from_start(self):
        original = self.store.performance_work
        self.store.performance_work = lambda now, limit: (self.clock.advance(5) or original(now, limit))
        task = self.scheduler(inventory_enabled=True)
        self.assertEqual(task.tick(), {"state": "ok", "errors": []})
        self.assertEqual(task.next_delay(), 25)
        self.clock.advance(24)
        task.tick()
        self.assertEqual(len(self.readers), 1)
        self.assertEqual(task.next_delay(), 1)
        self.clock.advance(1)
        task.tick()
        self.assertEqual(len(self.readers), 2)
        self.assertEqual(len(self.reports), 1)

    def test_inventory_with_http_waits_30_seconds_after_completion(self):
        self.performance_jobs()
        task = self.scheduler(inventory_enabled=True)
        task.tick()
        self.assertEqual(len(self.http.calls), 3)
        self.assertAlmostEqual(task.next_delay(), 30)
        self.clock.advance(29.9)
        task.tick()
        self.assertEqual(len(self.readers), 1)
        self.clock.advance(.1)
        task.tick()
        self.assertEqual(len(self.readers), 2)

    def test_rate_limit_survives_new_readers_for_300_seconds(self):
        self.performance_jobs()
        self.http.script("/ncc/campaigns", *[(429, {"code": 429})]*3)
        task = self.scheduler(inventory_enabled=True)
        task.tick()
        self.assertTrue(self.readers[0].rate_limited)
        self.assertEqual(len(self.http.calls), 3)
        self.assertAlmostEqual(task.next_delay(), 60)
        self.clock.advance(60)
        task.tick()
        self.assertEqual(len(self.readers), 1)
        self.clock.advance(239)
        task.tick()
        self.assertEqual(len(self.readers), 1)
        self.assertAlmostEqual(task.next_delay(), 1)
        self.clock.advance(1)
        task.tick()
        self.assertEqual(len(self.readers), 2)
        self.assertFalse(self.readers[1].rate_limited)

    def automatic_naver_stages(self):
        """예약 연결만 분리한다. 단계 내부 HTTP/429 판정은 실제 reader를 사용한다."""
        stages = []
        self.store.thresholds = lambda: None
        self.http.route(r"/manager-accounts", lambda call: (200, {"content": [], "totalElements": 0}))
        def read(name, reader):
            stages.append(name)
            reader.list_manager_accounts(reader.manager_handle())
        self.context.enter_context(patch.object(L, "accounts_due", return_value=True))
        self.context.enter_context(patch.object(L, "sync_accounts", side_effect=lambda reader, *a: read("accounts", reader)))
        self.context.enter_context(patch.object(M, "morning_due", return_value=True))
        self.context.enter_context(patch.object(M, "readiness", return_value=None))
        self.context.enter_context(patch.object(M, "run_morning", side_effect=lambda reader, *a, **kw: read("morning", reader)))
        self.context.enter_context(patch("naver_runtime.scheduler._ManagedMorningStore", side_effect=lambda store, now: store))
        return stages

    def test_inventory_rate_limit_blocks_same_tick_morning_but_not_reports(self):
        self.performance_jobs()
        stages = self.automatic_naver_stages()
        self.http.script("/ncc/campaigns", *[(429, {"code": 429})]*3)
        task = self.scheduler(inventory_enabled=True, morning_enabled=True)
        self.assertEqual(task.tick()["state"], "ok")
        self.assertEqual(stages, ["accounts"])
        self.assertEqual(len(self.readers), 2)
        self.assertEqual(len(self.reports), 1)
        self.clock.advance(299)
        task.tick()
        self.assertEqual(len(self.readers), 2)
        self.assertEqual(len(self.reports), 2)
        self.clock.advance(1)
        task.tick()
        self.assertEqual(stages, ["accounts", "accounts", "morning"])
        self.assertEqual(len(self.readers), 5)

    def test_accounts_rate_limit_blocks_later_naver_stages_even_after_retry_success(self):
        self.performance_jobs()
        stages = self.automatic_naver_stages()
        self.http.script("/manager-accounts", (429, {"code": 429}))
        task = self.scheduler(inventory_enabled=True, morning_enabled=True)
        self.assertEqual(task.tick()["state"], "ok")
        self.assertTrue(self.readers[0].rate_limited)
        self.assertEqual(stages, ["accounts"])
        self.assertEqual(len(self.readers), 1)
        self.assertEqual(len(self.reports), 1)
        self.clock.advance(299)
        task.tick()
        self.assertEqual(len(self.readers), 1)
        self.clock.advance(1)
        task.tick()
        self.assertEqual(stages, ["accounts", "accounts", "morning"])
        self.assertEqual(len(self.readers), 4)

    def test_morning_rate_limit_blocks_next_accounts_and_inventory_until_300_seconds(self):
        self.performance_jobs()
        stages = self.automatic_naver_stages()
        self.http.script("/manager-accounts", (200, {"content": [], "totalElements": 0}), (429, {"code": 429}))
        task = self.scheduler(inventory_enabled=True, morning_enabled=True)
        self.assertEqual(task.tick()["state"], "ok")
        self.assertEqual(stages, ["accounts", "morning"])
        self.assertEqual(len(self.readers), 3)
        self.assertTrue(self.readers[-1].rate_limited)
        self.clock.advance(299)
        task.tick()
        self.assertEqual(len(self.readers), 3)
        self.assertEqual(len(self.reports), 2)
        self.clock.advance(1)
        task.tick()
        self.assertEqual(stages, ["accounts", "morning"]*2)
        self.assertEqual(len(self.readers), 6)

    def test_normal_inventory_pause_does_not_starve_morning(self):
        self.performance_jobs()
        stages = self.automatic_naver_stages()
        task = self.scheduler(inventory_enabled=True, morning_enabled=True)
        for _ in range(2):
            self.assertEqual(task.tick()["state"], "ok")
            self.clock.advance(60)
        self.assertEqual(stages, ["accounts", "morning"]*2)
        self.assertEqual(len(self.readers), 6)
        self.assertTrue(all(not reader.rate_limited for reader in self.readers))

    def test_morning_only_rate_pause_survives_a_raised_stage_error(self):
        self.automatic_naver_stages()
        self.http.script("/manager-accounts", (429, {"code": 429}))
        def interrupted(reader, *args, **kwargs):
            reader.list_manager_accounts(reader.manager_handle())
            raise S.StoreError("합성 단계 정리 오류")
        task = self.scheduler(morning_enabled=True)
        with patch.object(M, "run_morning", side_effect=interrupted), \
             self.assertLogs("naver_runtime.scheduler", level="ERROR"):
            self.assertEqual(task.tick(), {"state": "failed", "errors": ["morning"]})
        self.clock.advance(299)
        task.tick()
        self.assertEqual(len(self.readers), 1)
        self.clock.advance(1)
        self.assertEqual(task.tick()["state"], "ok")
        self.assertEqual(len(self.readers), 2)

    def test_runtime_wait_uses_scheduler_deadline_with_its_monotonic_clock(self):
        self.performance_jobs()
        stop, writer, server = Event(), Mock(), Mock()
        writer.proxy = self.store
        writer.__enter__ = Mock(return_value=writer)
        writer.__exit__ = Mock(return_value=False)
        server.__enter__ = Mock(return_value=server)
        server.__exit__ = Mock(return_value=False)
        factory = lambda: N.NaverReader(creds(), transport=self.http, clock=self.clock)
        with patch.object(main, "Writer", return_value=writer), \
             patch.object(main, "UnixServer", return_value=server), \
             patch.object(main, "InterruptibleClock", return_value=self.clock), \
             patch.object(main, "dependencies", return_value={"naver_factory": factory}), \
             patch.object(stop, "wait", side_effect=lambda seconds: stop.set()) as wait:
            self.assertEqual(main.run(Config("/synthetic/data/db", "/synthetic/socket/sock",
                                             inventory_enabled=True), {}, stop=stop), 0)
        self.assertEqual(len(self.http.calls), 3)
        wait.assert_called_once_with(30)

    def test_structure_rate_limit_also_holds_the_next_reader(self):
        self.performance_jobs(0)
        self.structure_jobs()
        self.http.script("/ncc/campaigns", *[(429, {"code": 429})]*3)
        task = self.scheduler(inventory_enabled=True)
        task.tick()
        self.assertTrue(self.readers[0].rate_limited)
        self.clock.advance(299)
        task.tick()
        self.assertEqual(len(self.readers), 1)
        self.assertAlmostEqual(task.next_delay(), 1)
        self.clock.advance(1)
        task.tick()
        self.assertEqual(len(self.readers), 2)

    def test_rate_pause_is_preserved_when_saving_the_rate_error_fails(self):
        self.performance_jobs()
        self.http.script("/ncc/campaigns", *[(429, {"code": 429})]*3)
        self.store.record_performance_check = Mock(side_effect=S.StoreError("합성 저장 오류"))
        task = self.scheduler(inventory_enabled=True)
        with self.assertLogs("naver_runtime.scheduler", level="ERROR"):
            self.assertEqual(task.tick(), {"state": "failed", "errors": ["inventory"]})
        self.clock.advance(60)
        task.tick()
        self.assertEqual(len(self.readers), 1)

    def test_clock_jumps_cannot_advance_or_extend_monotonic_inventory_cadence(self):
        task = self.scheduler(inventory_enabled=True)
        task.tick()
        self.clock._now += timedelta(hours=1)
        task.tick()
        self.assertEqual(len(self.readers), 1)
        self.assertEqual(task.next_delay(), 30)
        self.clock._now -= timedelta(hours=2)
        self.clock.advance(30)
        task.tick()
        self.assertEqual(len(self.readers), 2)
        self.assertEqual(len(self.reports), 1)
        self.clock.advance(30)
        task.tick()
        self.assertEqual(len(self.reports), 2)

    def test_long_tick_reuses_elapsed_work_but_does_not_repeat_reports_before_60_seconds(self):
        self.performance_jobs()
        def report(now):
            self.reports.append(self.clock.monotonic())
            self.clock.advance(40)
        self.store.generate_reports = report
        task = self.scheduler(inventory_enabled=True)
        task.tick()
        self.assertEqual(task.next_delay(), 0)
        task.tick()
        self.assertEqual(len(self.readers), 2)
        self.assertEqual(len(self.reports), 1)
        self.assertGreater(task.next_delay(), 19)
        self.assertLess(task.next_delay(), 20)

    def test_source_failure_and_empty_queue_still_wait_without_spinning(self):
        for valid in (False, True):
            with self.subTest(source_valid=valid):
                self.store.valid = valid
                task = self.scheduler(inventory_enabled=True)
                self.assertEqual(task.tick()["state"], "ok" if valid else "failed")
                self.assertEqual(task.next_delay(), 30)
                before = len(self.readers)
                task.tick()
                self.assertEqual(len(self.readers), before)
                self.assertEqual(self.http.calls, [])

    def test_inventory_disabled_keeps_normal_60_second_runtime_wait(self):
        task = self.scheduler()
        task.tick()
        self.assertEqual(task.next_delay(), 60)
        self.assertEqual(self.readers, [])
        self.assertEqual(self.reports, [])

    def test_concurrent_tick_has_one_writer_and_returns_busy(self):
        entered, release = Event(), Event()
        def work(now, limit):
            entered.set()
            if not release.wait(3):
                raise AssertionError("시험 회차 종료 신호 없음")
            return []
        self.store.performance_work = work
        task = self.scheduler(inventory_enabled=True)
        outcomes = []
        running = Thread(target=lambda: outcomes.append(task.tick()))
        running.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(task.tick(), {"state": "busy"})
            self.assertEqual(len(self.readers), 1)
        finally:
            release.set()
            running.join(3)
        self.assertFalse(running.is_alive())
        self.assertEqual(outcomes, [{"state": "ok", "errors": []}])

    def test_variable_response_ticks_never_overlap_24_call_30_second_windows(self):
        self.performance_jobs(10)
        self.structure_jobs(4)
        sends, duration = [], [0]
        def response(call):
            sends.append(self.clock.monotonic())
            self.clock.advance(duration[0])
        self.http.tick = response
        task = self.scheduler(inventory_enabled=True)
        starts, finishes = [], []
        for seconds in (0, 2, 0):
            duration[0] = seconds
            prior = len(self.readers)
            for _ in range(4):
                began = self.clock.monotonic()
                task.tick()
                if len(self.readers) > prior:
                    starts.append(began)
                    finishes.append(self.clock.monotonic())
                    break
                self.clock.advance(task.next_delay())
            else:
                self.fail("예약 회차가 재개되지 않았습니다")
            self.clock.advance(task.next_delay())
        self.assertEqual(self.readers[0].calls, 24)
        self.assertTrue(all(reader.calls <= 24 for reader in self.readers))
        self.assertTrue(all(end-start <= 30 for start, end in zip(starts, finishes)))
        self.assertTrue(all(start-end >= 30-1e-8 for start, end in zip(starts[1:], finishes)))
        self.assertTrue(all(later-earlier >= 1/N.CALLS_PER_SEC-1e-8 for earlier, later in zip(sends, sends[1:])))
        self.assertTrue(all(sum(start <= at < start+30-1e-8 for at in sends) <= 24 for start in sends))
