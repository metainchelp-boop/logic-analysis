"""실제 예약 회차의 현재 상태. 외부 전송·시간만 합성하고 상태 조회는 진척을 만들지 않는다."""
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
import runpy
import socket
from threading import Event, Thread
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from naver_engine import naver_read as N, store as S
from naver_engine.tests.fake_naver import FakeClock, FakeNaver
from naver_engine.tests.test_morning import creds
from naver_engine import inventory as I, links as L
from naver_engine.tests.test_performance_reads import MemoryPerformance
from naver_runtime.config import Config
from naver_runtime.scheduler import Scheduler
from naver_runtime.runtime_status import RuntimeStatus
from naver_runtime import __main__ as main


NOW = datetime(2026, 10, 15, 7, 20, tzinfo=S.KST)


class RuntimeStatusTest(TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        for method in ("connect", "connect_ex"):
            self.context.enter_context(patch.object(socket.socket, method,
                side_effect=AssertionError("외부 송신 금지")))
        self.context.enter_context(patch.object(L, "accounts_due", return_value=False))
        self.context.enter_context(patch.object(I, "sync_catalog_due", return_value=False))
        self.clock, self.http = FakeClock(NOW), FakeNaver()
        self.store = MemoryPerformance(self.clock)
        self.store.jobs = []
        self.store.structure_work = lambda now, limit: []
        self.store.account_catalog_status = lambda: {"at": self.clock.now().isoformat()}
        self.store.generate_reports = lambda now, cycle=None: []

    def scheduler(self, **options):
        reader = options.pop("naver_factory", lambda: N.NaverReader(creds(), transport=self.http, clock=self.clock))
        return Scheduler(Config("/synthetic/data/db", "/synthetic/socket/sock", inventory_enabled=True),
            self.store, clock=self.clock.now, monotonic_clock=self.clock.monotonic,
            naver_factory=reader, **options)

    def test_frozen_loop_expires_despite_repeated_reads_after_successful_tick(self):
        task = self.scheduler()
        self.assertEqual(task.tick(), {"state": "ok", "errors": []})
        initial = task.runtime_status()
        self.assertEqual(initial["indicator"], "green")
        self.assertIn(initial["state"], ("waiting", "idle"))
        self.clock.advance(initial["valid_for_seconds"] - 1)
        self.assertEqual(task.runtime_status()["verified_at"], initial["verified_at"])
        self.clock.advance(2)
        stale = task.runtime_status()
        self.assertEqual((stale["state"], stale["indicator"]), ("stale", "red"))
        self.assertEqual(stale["verified_at"], initial["verified_at"])
        self.assertEqual(self.http.calls, [])

    def test_transport_progress_is_live_but_times_out_without_blocking_status_reads(self):
        from naver_engine.tests.test_morning import A
        self.store.jobs = [{"customer_id": A, "kind": "daily", "cycle_day": "2026-10-15",
            "period_start": "2026-10-14", "period_end": "2026-10-14",
            "snapshot_at": self.clock.now(), "job_key": "daily-status"}]
        entered, release = Event(), Event()
        self.clock.before_network = lambda: None
        state = RuntimeStatus(enabled=True, clock=self.clock.now, monotonic=self.clock.monotonic)
        def response(call):
            entered.set()
            if not release.wait(3):
                raise AssertionError("합성 요청 종료 대기 초과")
            return 200, []
        self.http.route(r"/ncc/campaigns", response)
        transport = main.StopAwareTransport(self.clock, self.http, runtime_state=state, service="naver")
        task = self.scheduler(runtime_state=state,
            naver_factory=lambda: N.NaverReader(creds(), transport=transport, clock=self.clock))
        worker = Thread(target=task.tick)
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            running = task.runtime_status()
            self.assertEqual((running["state"], running["indicator"]), ("collecting", "green"))
            self.assertLessEqual(running["valid_for_seconds"], 25)  # 계정 HTTP 20초 + 관측 유예 5초
            self.clock.advance(running["valid_for_seconds"] + 1)
            self.assertEqual(task.runtime_status()["state"], "stale")
            self.assertEqual(len(self.http.calls), 1)
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())

    def test_completed_empty_collection_is_idle_not_a_claim_that_every_account_succeeded(self):
        task = self.scheduler()
        task.tick()
        self.assertEqual((task.runtime_status()["state"], task.runtime_status()["reason_code"]), ("idle", "IDLE"))

    def test_source_account_auth_failure_is_red_and_does_not_expose_details(self):
        fixture = runpy.run_path(str(Path(__file__).resolve().parents[2] /
            "tools/naver-store-selection-benchmark.py"))["make_fixture"](1, 1)
        self.addCleanup(fixture.store.close)
        self.clock, self.store, self.http = fixture.clock, fixture.store, fixture.http
        self.http.script("/manager-accounts", (403, {"code": 403, "message": "SECRET_MARKER"}))
        self.context.enter_context(patch.object(L, "accounts_due", return_value=True))
        task = self.scheduler()
        task.tick()
        value = task.runtime_status()
        self.assertEqual((value["state"], value["reason_code"], value["indicator"]),
                         ("blocked", "AUTH_REQUIRED", "red"))
        self.assertEqual(set(value), {"state", "indicator", "reason_code", "verified_at", "valid_for_seconds", "retry_at"})
        self.assertNotIn("SECRET_MARKER", repr(value))

    def test_starting_disabled_and_stop_signal_are_red(self):
        task = self.scheduler()
        self.assertEqual((task.runtime_status()["state"], task.runtime_status()["verified_at"]), ("starting", None))
        disabled = Scheduler(Config("/synthetic/db", "/synthetic/sock"), self.store,
                             clock=self.clock.now, monotonic_clock=self.clock.monotonic)
        disabled.tick()
        self.assertEqual((disabled.runtime_status()["state"], disabled.runtime_status()["indicator"]), ("disabled", "red"))
        stop = Event()
        state = RuntimeStatus(enabled=True, clock=self.clock.now, monotonic=self.clock.monotonic, stopped=stop.is_set)
        task = self.scheduler(runtime_state=state)
        task.tick()
        stop.set()
        self.assertEqual((task.runtime_status()["state"], task.runtime_status()["indicator"]), ("stopped", "red"))

    def test_wall_clock_rollback_does_not_extend_a_frozen_signal(self):
        task = self.scheduler()
        task.tick()
        initial = task.runtime_status()
        self.clock._now -= timedelta(days=1)
        self.clock.advance(initial["valid_for_seconds"] + 1)
        self.assertEqual(task.runtime_status()["state"], "stale")
        self.assertEqual(task.runtime_status()["verified_at"], initial["verified_at"])

    def test_source_block_survives_an_empty_tick_until_real_collection_verifies_recovery(self):
        self.store.valid = False
        task = self.scheduler()
        self.assertEqual(task.tick(), {"state": "failed", "errors": ["inventory"]})
        self.assertEqual(task.runtime_status()["reason_code"], "SOURCE_NOT_READY")
        self.clock.advance(1)
        task.tick()
        self.assertEqual(task.runtime_status()["state"], "blocked")
        self.store.valid = True
        self.clock.advance(29)
        task.tick()
        self.assertEqual(task.runtime_status()["indicator"], "green")

    def test_failed_manual_history_survives_actual_automatic_recovery_of_live_indicator(self):
        from dataclasses import replace
        from naver_engine import sync as Y, morning as M
        from naver_engine.tests.test_sync import org_payload
        from naver_runtime.tests.test_collection_requests import AuditStore, enabled
        self.clock.advance(6 * 3600 + 40 * 60)  # 아침 readiness 작업과 별개인 공개 수동 요청 경로.
        audit = AuditStore()
        audit.org = {"body": org_payload(self.clock.now()), "generated_at": self.clock.now()}
        for name in ("org_current", "hold", "record_access", "access_log", "runs_on"):
            setattr(self.store, name, getattr(audit, name))
        self.store.last_sync = lambda kind: {"at": self.clock.now()}
        for module, name in ((Y, "org_due"), (Y, "stages_due"), (L, "pairing_due"), (M, "morning_due"), (M, "continuous_due")):
            self.context.enter_context(patch.object(module, name, return_value=False))
        self.context.enter_context(patch("naver_runtime.scheduler._ManagedMorningStore", side_effect=lambda store,now:store))
        def failed_factory():
            raise RuntimeError("합성 수동 수집 실패")
        task = Scheduler(replace(enabled(), inventory_enabled=True), self.store,
            clock=self.clock.now, monotonic_clock=self.clock.monotonic, collection_factory=failed_factory,
            naver_factory=lambda: N.NaverReader(creds(), transport=self.http, clock=self.clock))
        self.assertEqual(task.request_collection(0)["status"], "accepted")
        task.tick()
        manual, logs = task.collection_status(), audit.access_log()
        self.assertEqual(manual["status"], "failed")
        self.assertEqual(task.runtime_status()["indicator"], "red")
        self.store.valid = False
        task.tick()  # 실제 자동 원천 검증 실패로는 수동 실패 신호를 지우지 않는다.
        self.assertEqual(task.runtime_status()["reason_code"], "RUNTIME_ERROR")
        self.store.valid = True
        self.clock.advance(1)
        task.tick()  # 아직 자동 수집 간격 전인 빈 회차도 복구 근거가 아니다.
        self.assertEqual(task.runtime_status()["reason_code"], "RUNTIME_ERROR")
        self.clock.advance(29)
        task.tick()
        self.assertEqual(task.runtime_status()["indicator"], "green")
        self.assertEqual(task.collection_status(), manual)
        self.assertEqual(audit.access_log(), logs)

    def test_step_exception_is_fixed_red_code_and_survives_skipped_step(self):
        def failed(now, cycle=None):
            raise RuntimeError("SECRET_MARKER")
        self.store.generate_reports = failed
        task = self.scheduler()
        with self.assertLogs("naver_runtime.scheduler", level="ERROR"):
            task.tick()
        self.assertEqual((task.runtime_status()["state"], task.runtime_status()["reason_code"]), ("error", "RUNTIME_ERROR"))
        self.clock.advance(1)
        task.tick()
        self.assertEqual(task.runtime_status()["state"], "error")
        self.assertNotIn("SECRET_MARKER", repr(task.runtime_status()))

    def performance_job(self):
        from naver_engine.tests.test_morning import A
        self.store.jobs = [{"customer_id": A, "kind": "daily", "cycle_day": "2026-10-15",
            "period_start": "2026-10-14", "period_end": "2026-10-14",
            "snapshot_at": self.clock.now(), "job_key": "daily-status"}]
        self.http.route(r"/ncc/campaigns", lambda call: (200, []))
        self.http.route(r"/billing/bizmoney", lambda call: (200, {"customerId": A,
            "bizmoney": 100, "budgetLock": False, "refundLock": False}))

    def test_real_rate_pause_is_red_with_same_300_second_cooldown(self):
        self.performance_job()
        self.http.script("/ncc/campaigns", *((429, {"code": 429}),) * 3)
        task = self.scheduler()
        task.tick()
        paused = task.runtime_status()
        self.assertEqual((paused["state"], paused["reason_code"], paused["indicator"]),
                         ("rate_paused", "RATE_LIMITED", "red"))
        self.assertEqual(datetime.fromisoformat(paused["retry_at"]), self.clock.now() + timedelta(seconds=300))
        sent = len(self.http.calls)
        for seconds in (60, 60, 60, 60, 59):
            self.clock.advance(seconds)
            task.tick()
            self.assertEqual(task.runtime_status()["state"], "rate_paused")
            self.assertEqual(len(self.http.calls), sent)
        self.clock.advance(1)
        task.tick()
        self.assertGreater(len(self.http.calls), sent)
        self.assertEqual(task.runtime_status()["indicator"], "green")

    def test_account_auth_error_is_not_global_engine_failure(self):
        self.performance_job()
        self.http.script("/ncc/campaigns", (403, {"code": 403}))
        task = self.scheduler()
        self.assertEqual(task.tick(), {"state": "ok", "errors": []})
        self.assertEqual(self.store.results["daily-status"]["status"], "reauth_required")
        self.assertEqual(task.runtime_status()["indicator"], "green")

    def test_long_source_sync_stays_fresh_only_with_actual_bounded_transport_progress(self):
        state = RuntimeStatus(enabled=True, clock=self.clock.now, monotonic=self.clock.monotonic)
        state.begin_cycle()
        state.begin_step("org")
        self.clock.before_network = lambda: None
        class Transport:
            def send(inner, request, timeout):
                self.clock.advance(timeout - 1)
                self.assertEqual(state.snapshot()["state"], "source_sync")
                return 200, b"{}"
        transport = main.StopAwareTransport(self.clock, Transport(), runtime_state=state, service="erp")
        for _ in range(4):
            self.clock.advance(20)
            transport.send("synthetic", 30)
        self.assertEqual(state.snapshot()["indicator"], "green")
        self.clock.advance(46)
        self.assertEqual(state.snapshot()["state"], "stale")

    def test_other_request_thread_cannot_refresh_execution_signal(self):
        state = RuntimeStatus(enabled=True, clock=self.clock.now, monotonic=self.clock.monotonic)
        state.begin_cycle()
        before = state.snapshot()
        self.clock.advance(20)
        worker = Thread(target=lambda: (state.network_started(30), state.network_finished("naver", 200)))
        worker.start()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(state.snapshot()["verified_at"], before["verified_at"])
        self.clock.advance(26)
        self.assertEqual(state.snapshot()["state"], "stale")

    def test_short_backup_stays_green_but_unobserved_long_backup_expires(self):
        self.store.runs_on = lambda day: [{"status": S.RUN_DONE}]
        for seconds, expected in ((1, "waiting"), (46, "stale")):
            with self.subTest(seconds=seconds):
                observed = []
                def backup(store, now):
                    self.clock.advance(seconds)
                    observed.append(task.runtime_status())
                    return SimpleNamespace(code="OFFSITE_OK")
                task = Scheduler(Config("/synthetic/db", "/synthetic/sock", inventory_enabled=True, backup_enabled=True),
                    self.store, clock=self.clock.now, monotonic_clock=self.clock.monotonic,
                    naver_factory=lambda: N.NaverReader(creds(), transport=self.http, clock=self.clock), backup_job=backup)
                task.tick()
                self.assertEqual(observed[0]["state"], expected)
                if seconds == 1:
                    self.assertEqual(observed[0]["reason_code"], "BACKUP_RUNNING")
                    self.assertEqual(observed[0]["indicator"], "green")
                self.assertEqual(task.runtime_status()["indicator"], "green")

    def test_outer_scheduler_failure_is_not_cleared_by_next_empty_tick(self):
        from naver_engine import morning as M
        failures = [True]
        def due(store, now):
            if failures.pop() if failures else False:
                raise RuntimeError("SECRET_MARKER")
            return False
        self.context.enter_context(patch.object(M,"continuous_due",side_effect=due))
        self.context.enter_context(patch("naver_runtime.scheduler._ManagedMorningStore", side_effect=lambda store,now:store))
        self.store.monitoring_readiness = lambda now: None
        task = Scheduler(Config("/synthetic/db", "/synthetic/sock", inventory_enabled=True, morning_enabled=True),
            self.store, clock=self.clock.now, monotonic_clock=self.clock.monotonic,
            naver_factory=lambda: N.NaverReader(creds(), transport=self.http, clock=self.clock))
        with self.assertRaises(RuntimeError):
            task.tick()
        self.assertEqual(task.runtime_status()["state"], "error")
        self.clock.advance(1)
        self.assertEqual(task.tick(), {"state": "ok", "errors": []})
        self.assertEqual(task.runtime_status()["state"], "error")
        self.clock.advance(29)
        task.tick()
        self.assertEqual(task.runtime_status()["indicator"], "green")

    def test_structure_source_change_is_visible_without_changing_existing_health(self):
        from naver_engine.tests.test_structure_collector import MemoryStructure
        structure = MemoryStructure(self.clock)
        structure.valid = False
        for name in ("structure_work", "structure_account_valid", "begin_structure_check", "structure_progress",
                     "record_structure_progress", "record_structure_check"):
            setattr(self.store, name, getattr(structure, name))
        self.http.route(r"/ncc/(campaigns|channels)", lambda call: (200, []))
        task = self.scheduler()
        self.assertEqual(task.tick(), {"state": "ok", "errors": []})
        self.assertEqual((task.runtime_status()["state"], task.runtime_status()["reason_code"]),
                         ("blocked", "SOURCE_CHANGED"))
        structure.valid = True
        self.clock.advance(30)
        task.tick()
        self.assertEqual(task.runtime_status()["indicator"], "green")

    def test_manager_auth_code_on_http_400_is_still_auth_required(self):
        fixture = runpy.run_path(str(Path(__file__).resolve().parents[2] /
            "tools/naver-store-selection-benchmark.py"))["make_fixture"](1, 1)
        self.addCleanup(fixture.store.close)
        self.clock, self.store, self.http = fixture.clock, fixture.store, fixture.http
        self.http.script("/manager-accounts", (400, {"code": 1006}))
        self.context.enter_context(patch.object(L, "accounts_due", return_value=True))
        task = self.scheduler()
        task.tick()
        self.assertEqual(task.runtime_status()["reason_code"], "AUTH_REQUIRED")

    def test_actual_reader_five_minute_pause_is_red_even_when_rate_code_was_not_http_429(self):
        state = RuntimeStatus(enabled=True, clock=self.clock.now, monotonic=self.clock.monotonic)
        state.begin_cycle()
        state.begin_step("accounts")
        state.network_finished("naver", 400)
        state.sleeping(N.RATE_PAUSE)
        self.assertEqual((state.snapshot()["state"], state.snapshot()["reason_code"]),
                         ("rate_paused", "RATE_LIMITED"))
