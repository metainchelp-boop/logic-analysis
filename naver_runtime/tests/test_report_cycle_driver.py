"""보고서 회차 조각 구동(NV-S00) — 조각 하나 = 쓰기 줄 항목 하나 · 조각 사이에 로그인 감사가 먼저 실행된다."""
from contextlib import ExitStack
from datetime import date, datetime, timedelta
import os
import shutil
import socket
import tempfile
import threading
import time
from types import MethodType
from unittest import TestCase
from unittest.mock import patch

from naver_engine import inventory as IC, links as L, naver_read as N, store as S
from naver_engine.tests.fake_naver import FakeClock, FakeNaver
from naver_engine.tests.test_morning import creds
from naver_engine.tests.test_performance_reads import MemoryPerformance
from naver_engine.tests.test_report_generate_slices import _decisions, digest, real_store, ReportAdapter
from naver_runtime import scheduler as SC
from naver_runtime.config import Config
from naver_runtime.writer import Writer

NOW = datetime(2026, 10, 15, 7, 20, tzinfo=S.KST)
REPORT_NOW = datetime(2026, 10, 5, 10, tzinfo=S.KST)


class Calls:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def generate_reports(self, now, cycle=None):
        self.calls.append((now, cycle))
        return self.answers.pop(0) if self.answers else {"cycle": 1, "remaining": 1}


class DriverTest(TestCase):
    def test_slices_continue_with_the_same_time_until_the_three_field_result(self):
        last = {"generated": 2, "accounts_confirmed": 3, "advertisers": 2}
        store = Calls([{"cycle": 1, "remaining": 2}, {"cycle": 1, "remaining": 1}, last])
        self.assertEqual(SC.run_report_cycle(store, NOW), last)
        self.assertEqual(store.calls, [(NOW, 0), (NOW, 1), (NOW, 1)])

    def test_nothing_to_make_is_one_call(self):
        store = Calls([{"generated": 0, "accounts_confirmed": 0, "advertisers": 0}])
        self.assertEqual(SC.run_report_cycle(store, NOW)["advertisers"], 0)
        self.assertEqual(store.calls, [(NOW, 0)])

    def test_a_cycle_that_never_ends_is_bounded(self):
        store = Calls([])
        with self.assertRaises(RuntimeError):
            SC.run_report_cycle(store, NOW)
        self.assertEqual(len(store.calls), SC.REPORT_SLICES_MAX)
        self.assertEqual(store.calls[0], (NOW, 0))
        self.assertTrue(all(cycle == 1 for _now, cycle in store.calls[1:]))
        self.assertGreaterEqual(SC.REPORT_SLICES_MAX, 1+20+1)   # 여는 조각 + 업체 최대 20곳 + 여유


class SchedulerStepTest(TestCase):
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

    def scheduler(self):
        return SC.Scheduler(Config("/synthetic/data/db", "/synthetic/socket/sock", inventory_enabled=True),
                            self.store, clock=self.clock.now, monotonic_clock=self.clock.monotonic,
                            naver_factory=lambda: N.NaverReader(creds(), transport=self.http, clock=self.clock))

    def test_report_step_drives_slices_and_an_endless_cycle_fails_then_restarts_from_zero(self):
        calls = []
        endless = [True]
        def generate(now, cycle=None):
            calls.append(cycle)
            if endless[0]:
                return {"cycle": 7, "remaining": 1}
            return {"generated": 0, "accounts_confirmed": 0, "advertisers": 1} if cycle else {"cycle": 8, "remaining": 1}
        self.store.generate_reports = generate
        task = self.scheduler()
        with self.assertLogs("naver_runtime.scheduler", level="ERROR"):
            task.tick()
        self.assertIn("reports", task.last_errors)
        self.assertEqual(calls[0], 0)
        self.assertEqual(len(calls), SC.REPORT_SLICES_MAX)
        self.assertEqual(task.runtime_status()["state"], "error")
        endless[0] = False
        del calls[:]
        self.clock.advance(60)
        task.tick()
        self.assertEqual(calls, [0, 8])                      # 다음 회차는 처음(cycle=0)부터
        self.assertNotIn("reports", task.last_errors)


class _SlowSlices:
    """조각마다 쓰기 줄을 잠시 쥐는 가짜 저장소 — 조각 사이에 줄에 선 감사가 먼저 실행되는지만 본다."""
    def __init__(self, path, clock=None):
        self.events, self.owner = [], threading.get_ident()
        self.sliced = threading.Event()

    def close(self):
        pass

    def generate_reports(self, now, cycle=None):
        assert threading.get_ident() == self.owner
        self.events.append(("slice-start", cycle))
        if cycle == 0:
            self.sliced.set()
        time.sleep(.3)
        self.events.append(("slice-end", cycle))
        if cycle == 0:
            return {"cycle": 1, "remaining": 3}
        self._n = getattr(self, "_n", 0)+1
        return {"cycle": 1, "remaining": 3-self._n} if self._n < 3 else {"generated": 3}

    def record_access(self, *args):
        assert threading.get_ident() == self.owner
        self.events.append(("audit", None))
        return 1


class WriterInterleaveTest(TestCase):
    def test_audit_queued_during_a_slice_runs_before_the_next_slice(self):
        holder = {}
        def factory(path, clock=None):
            holder["store"] = _SlowSlices(path, clock)
            return holder["store"]
        with Writer("/synthetic/unused", factory=factory) as writer:
            result = {}
            driver = threading.Thread(target=lambda: result.update(out=SC.run_report_cycle(writer.proxy, NOW)))
            driver.start()
            self.assertTrue(holder["store"].sliced.wait(5))
            started = time.monotonic()
            writer.proxy.record_access(0, "login", "session", None, "ok", NOW)
            waited = time.monotonic()-started
            driver.join(10)
            self.assertFalse(driver.is_alive())
        events = holder["store"].events
        audit = events.index(("audit", None))
        self.assertEqual(events[audit-1], ("slice-end", 0))         # 여는 조각이 끝난 바로 다음
        self.assertEqual(events[audit+1], ("slice-start", 1))       # 다음 조각보다 먼저
        self.assertLess(waited, 1.0)                                # 회차 전체(1.2초)가 아니라 조각 하나만 기다린다
        self.assertEqual(result["out"], {"generated": 3})


class RealWriterCycleTest(TestCase):
    def test_driver_through_the_real_writer_matches_the_one_shot_generation(self):
        def build(st):
            st.groups = {101+n: 11+n for n in range(4)}
            for n in range(4):
                st.seed(date(2026, 9, 1), date(2026, 10, 4), cid=101+n, pid=11+n)

        expected = real_store(self)
        build(expected)
        want_first = expected.generate_reports(expected.now)
        expected.now += timedelta(hours=1)
        expected.seed(date(2026, 9, 23), date(2026, 9, 23), cid=102, pid=12, spend=2500)
        want_second = expected.generate_reports(expected.now)
        want = digest(expected)

        folder = tempfile.mkdtemp(prefix="nv-report-writer-")
        self.addCleanup(shutil.rmtree, folder, True)
        box = {"now": REPORT_NOW}

        def factory(path, clock=None):
            st = S.open_writer(path, clock=lambda: box["now"])
            st.now = box["now"]
            st.groups, st.cadence, st.stage, st.cadences = {}, "daily", "진행중", {}
            st.attributable, st.human_confirmed, st.open_issue_pids, st.fail_period = True, True, set(), None
            st.synchronize_management = MethodType(_decisions, st)
            for name in ("current_decisions", "issues", "seed"):
                setattr(st, name, MethodType(getattr(ReportAdapter, name), st))
            return st

        with Writer(os.path.join(folder, "engine.db"), factory=factory) as writer:
            writer.call(build)
            first = SC.run_report_cycle(writer.proxy, box["now"])
            box["now"] += timedelta(hours=1)
            writer.call(lambda st: setattr(st, "now", box["now"]))
            writer.call(lambda st: st.seed(date(2026, 9, 23), date(2026, 9, 23), cid=102, pid=12, spend=2500))
            second = SC.run_report_cycle(writer.proxy, box["now"])
            got = writer.call(digest)
        self.assertEqual((first, second), (want_first, want_second))
        self.assertEqual(got, want)
        self.assertEqual(first["advertisers"], 4)
        self.assertGreater(second["generated"], 0)
