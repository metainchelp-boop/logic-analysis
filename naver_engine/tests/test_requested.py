"""관리자가 승인한 당일 한 회차: 합성 시계·저장소, 네트워크 없음."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase

from naver_engine import morning as M, naver_read as N, store as S
from naver_engine.credentials import ManagerCredentials, Secret
from naver_engine.tests.fake_naver import FakeClock, FakeNaver, AGENCY_ID, MARK_API_KEY, MARK_SECRET

NOW = datetime(2026, 10, 1, 14, 0, tzinfo=S.KST)


class EmptyStore:
    def __init__(self):
        self.runs = []
        self.pair = dict(at=NOW, accounts_read_at=NOW, stages_as_of=NOW,
                         decisions_hash="unchanged", pairing_id=1)
    def last_sync(self, *a): return {"at": NOW.isoformat()}
    def accounts_read_at(self): return NOW
    def stage_as_of(self): return NOW
    def accounts(self): return []
    def last_pairing(self, *a): return self.pair
    def decision_fingerprint(self): return "unchanged"
    def runs_on(self, day): return self.runs
    def my_running_runs(self): return []
    def pairing_rows(self, pid): return []
    def account_day_marks_on(self, day): return {}
    def account_days_on(self, day): return {}
    def issues(self, **kw): return []
    def prospects(self): return []
    def close_unlinked_issues(self, *a): return SimpleNamespace(closed_issues=0, mass=False)
    def begin_run(self, day, now):
        self.runs.append(dict(run_id=1, status=S.RUN_RUNNING, finished_at=None))
        return 1
    def finish_run(self, rid, status, at, **kw):
        self.runs[-1].update(status=status, finished_at=at.isoformat(), **kw)


class RequestedTest(TestCase):
    def reader(self, now=NOW):
        self.clock, self.transport = FakeClock(now), FakeNaver()
        return N.NaverReader(ManagerCredentials(AGENCY_ID, Secret(MARK_API_KEY), Secret(MARK_SECRET)),
                             clock=self.clock, transport=self.transport)

    def test_explicit_afternoon_run_does_not_change_native_window(self):
        store = EmptyStore()
        reader = self.reader()
        self.assertEqual(M.run_morning(reader, store, self.clock.now).codes, (M.CODE_AFTER_DEADLINE,))
        out = M.run_requested(reader, store, self.clock.now, max_seconds=600)
        self.assertEqual(out.outcome, M.OUT_DONE)
        self.assertEqual(len(store.runs), 1)
        self.assertEqual(self.transport.calls, [])

    def test_same_day_pairing_and_three_run_limit_remain_closed(self):
        for count, stale, wanted in ((3, False, M.CODE_RUNS_EXHAUSTED),
                                     (0, True, M.CODE_PAIRING_NOT_TODAY)):
            store = EmptyStore()
            store.runs = [dict(run_id=i, status=S.RUN_FAILED,
                               finished_at=(NOW - timedelta(hours=1)).isoformat()) for i in range(count)]
            if stale:
                store.pair["at"] = NOW - timedelta(days=1)
            reader = self.reader()
            out = M.run_requested(reader, store, self.clock.now)
            self.assertIn(wanted, out.codes)
            self.assertEqual(len(store.runs), count)
            self.assertEqual(self.transport.calls, [])

    def test_twenty_minute_retry_and_budget_validation(self):
        store = EmptyStore()
        store.runs = [dict(run_id=1, status=S.RUN_FAILED,
                           finished_at=(NOW - timedelta(minutes=19)).isoformat())]
        reader = self.reader()
        self.assertEqual(M.run_requested(reader, store, self.clock.now).codes, ("RETRY_NOT_DUE",))
        for seconds in (0, 601, True, 1.5):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                M.run_requested(reader, store, self.clock.now, max_seconds=seconds)
        with self.assertRaises(ValueError):
            M.run_requested(reader, store, self.clock.now, deadline=NOW + timedelta(seconds=601))
        self.assertEqual(len(store.runs), 1)

    def test_requested_deadline_keeps_real_clock_and_leaves_unfinished_rows(self):
        store = EmptyStore()
        # 이미 마감된 명시 요청은 회차/통신 없이 거절한다.
        reader = self.reader()
        result = M.run_requested(reader, store, self.clock.now, deadline=NOW)
        self.assertEqual(result.codes, (M.CODE_AFTER_DEADLINE,))
        self.assertEqual(store.runs, [])
        self.assertEqual(self.clock.now(), NOW)
