"""Completed real report slices refresh execution observation, not stalled work.

The real Scheduler/report driver/RuntimeStatus run with a pinned synthetic clock.
No SQLite connection, filesystem store, HTTP call, or production data is used.
"""
from datetime import datetime, timedelta
import socket
import sqlite3
from threading import Thread, get_ident
import unittest
from unittest.mock import patch

from naver_engine import inventory as I, links as L, naver_read as N, store as S
from naver_engine.tests.fake_naver import FakeClock, FakeNaver
from naver_engine.tests.test_morning import creds
from naver_engine.tests.test_performance_reads import MemoryPerformance
from naver_runtime.config import Config
from naver_runtime.scheduler import Scheduler, run_report_cycle
from naver_runtime.writer import Writer


NOW = datetime(2026, 10, 15, 9, tzinfo=S.KST)


class ReportRuntimeProgressTest(unittest.TestCase):
    def setUp(self):
        for name in ("connect", "connect_ex"):
            self.enterContext(patch.object(socket.socket, name,
                side_effect=AssertionError("no network in report progress regression")))
        self.enterContext(patch.object(sqlite3, "connect",
            side_effect=AssertionError("no database in report progress regression")))
        self.enterContext(patch.object(L, "accounts_due", return_value=False))
        self.enterContext(patch.object(I, "sync_catalog_due", return_value=False))
        self.clock, self.http = FakeClock(NOW), FakeNaver()
        self.store = MemoryPerformance(self.clock)
        self.store.jobs = []
        self.store.structure_work = lambda now, limit: []
        self.store.account_catalog_status = lambda: {"at": self.clock.now().isoformat()}
        self.store.generate_reports = lambda now, cycle=None: []
        self.task = Scheduler(Config("/synthetic/db", "/synthetic/socket", inventory_enabled=True),
            self.store, clock=self.clock.now, monotonic_clock=self.clock.monotonic,
            naver_factory=lambda: N.NaverReader(creds(), transport=self.http, clock=self.clock))

    def test_completed_report_slices_keep_actual_step_observed_for_a_long_cycle(self):
        before, during, arguments = [], [], []
        def reports(now, cycle=None):
            arguments.append((now, cycle))
            before.append(self.task.runtime_status())
            self.clock.advance(10)
            during.append(self.task.runtime_status())
            return {"cycle": cycle + 1} if cycle < 5 else []
        self.store.generate_reports = reports
        self.assertEqual(self.task.tick(), {"state": "ok", "errors": []})
        self.assertEqual([row["indicator"] for row in during], ["green"] * 6)
        self.assertEqual([row["state"] for row in during], ["waiting"] * 6)
        self.assertEqual([row["reason_code"] for row in during], ["WAITING"] * 6)
        self.assertEqual([row["verified_at"] for row in before],
            [(NOW + timedelta(seconds=10 * i)).isoformat() for i in range(6)])
        self.assertEqual([cycle for now, cycle in arguments], list(range(6)))
        self.assertTrue(all(now == NOW for now, cycle in arguments))
        self.assertEqual(self.task.last_tick, self.clock.now())
        self.assertEqual(self.task.last_errors, ())
        self.assertEqual(self.http.calls, [])

    def test_a_single_unobserved_long_slice_still_becomes_stale(self):
        observed = []
        def reports(now, cycle=None):
            self.clock.advance(46)
            observed.append(self.task.runtime_status())
            return []
        self.store.generate_reports = reports
        self.task.tick()
        self.assertEqual((observed[0]["state"], observed[0]["indicator"]), ("stale", "red"))
        self.assertEqual(observed[0]["verified_at"], NOW.isoformat())
        self.assertEqual(self.task.runtime_status()["indicator"], "green")

    def test_completed_slices_through_actual_writer_refresh_only_the_scheduler_thread(self):
        observed, workers = [], []
        def reports(now, cycle=None):
            workers.append(get_ident())
            self.clock.advance(10)
            observed.append(self.task.runtime_status())
            return {"cycle": cycle + 1} if cycle < 5 else []
        self.store.generate_reports = reports
        self.store.close = lambda: None
        with Writer("synthetic-no-db", factory=lambda path, clock: self.store) as writer:
            self.task.store = writer.proxy
            self.assertEqual(self.task.tick(), {"state": "ok", "errors": []})
            self.assertTrue(all(worker == writer._thread.ident for worker in workers))
            self.assertNotEqual(writer._thread.ident, get_ident())
        self.assertEqual([row["indicator"] for row in observed], ["green"] * 6)

    def test_failed_report_step_stays_red_until_that_step_actually_succeeds(self):
        calls = []
        def reports(now, cycle=None):
            calls.append(cycle)
            self.clock.advance(10)
            if cycle:
                raise RuntimeError("synthetic report slice failure")
            return {"cycle": 1}
        self.store.generate_reports = reports
        with self.assertLogs("naver_runtime.scheduler", level="ERROR"):
            self.assertEqual(self.task.tick(), {"state": "failed", "errors": ["reports"]})
        self.assertEqual(calls, [0, 1])
        self.assertEqual(self.task.runtime_status()["reason_code"], "RUNTIME_ERROR")
        self.clock.advance(1)
        self.assertEqual(self.task.tick(), {"state": "ok", "errors": []})
        self.assertEqual(self.task.runtime_status()["reason_code"], "RUNTIME_ERROR")
        self.store.generate_reports = lambda now, cycle=None: []
        self.clock.advance(39)
        self.assertEqual(self.task.tick(), {"state": "ok", "errors": []})
        self.assertEqual(self.task.runtime_status()["indicator"], "green")

    def test_progress_cannot_clear_failures_or_change_the_report_step(self):
        state = self.task._runtime
        state.begin_cycle()
        state.finish_step("org", ("blocked", "AUTH_REQUIRED"))
        state.begin_step("reports")
        self.clock.advance(10)
        state.step_progress()
        result = state.snapshot()
        self.assertEqual((result["state"], result["reason_code"], result["indicator"]),
            ("blocked", "AUTH_REQUIRED", "red"))
        state.finish_cycle(30, verified=True)
        self.assertEqual(state.snapshot()["reason_code"], "AUTH_REQUIRED")

    def test_other_threads_and_no_active_cycle_cannot_refresh_observation(self):
        state = self.task._runtime
        state.begin_cycle()
        state.begin_step("reports")
        initial = state.snapshot()
        self.clock.advance(20)
        other = Thread(target=state.step_progress)
        other.start()
        other.join(2)
        self.assertFalse(other.is_alive())
        self.assertEqual(state.snapshot()["verified_at"], initial["verified_at"])
        self.clock.advance(26)
        self.assertEqual(state.snapshot()["state"], "stale")
        state.finish_cycle(0)
        completed = state.snapshot()
        self.clock.advance(1)
        state.step_progress()
        self.assertEqual(state.snapshot()["verified_at"], completed["verified_at"])

    def test_failed_slice_does_not_create_a_completed_progress_signal(self):
        signals = []
        def reports(now, cycle=None):
            self.clock.advance(10)
            if cycle:
                raise RuntimeError("synthetic report slice failure")
            return {"cycle": 1}
        self.store.generate_reports = reports
        with self.assertRaises(RuntimeError):
            run_report_cycle(self.store, NOW, progress=lambda: signals.append(self.clock.now()))
        self.assertEqual(signals, [NOW + timedelta(seconds=10)])

    def test_legacy_report_driver_without_progress_keeps_same_slice_contract(self):
        calls = []
        def reports(now, cycle=None):
            calls.append((now, cycle))
            return {"cycle": 1} if cycle == 0 else ["same-result"]
        self.store.generate_reports = reports
        self.assertEqual(run_report_cycle(self.store, NOW), ["same-result"])
        self.assertEqual(calls, [(NOW, 0), (NOW, 1)])
