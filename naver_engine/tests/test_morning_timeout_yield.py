"""Batch timeout yielding uses real morning checks and an in-memory SQLite ledger only."""
from contextlib import contextmanager
import unittest
import urllib.parse
from types import SimpleNamespace
from unittest.mock import Mock, patch

from naver_engine import morning as M, naver_read as N
from naver_engine.tests import test_morning as TM, test_morning_continuous as MC
from naver_runtime.scheduler import Scheduler


@contextmanager
def scene():
    fixture = MC.ContinuousMorningTests(methodName='test_internal_yield_keeps_completed_account_and_continues_remaining')
    fixture.setUp()
    try:
        fixture.standard_ads()
        fixture.ads.add(TM.B, [(n, 'ELIGIBLE', False, TM.steady()) for n in range(1, 4)])
        fixture.scene()
        yield fixture
    finally:
        fixture.tearDown()
        fixture.doCleanups()


class MorningTimeoutYieldTests(unittest.TestCase):
    def test_scheduler_opts_in_only_for_inventory_continuous_morning(self):
        for inventory in (False, True):
            with self.subTest(inventory=inventory), scene() as f:
                reader = f.reader()
                scheduler = Scheduler.__new__(Scheduler)
                scheduler.config = SimpleNamespace(inventory_enabled=inventory)
                scheduler._reader = lambda: reader
                scheduler.store, scheduler.clock = f.st, f.fc.now
                scheduler._inventory_customers, scheduler._morning_retry_at = frozenset(), {}
                scheduler._monotonic, scheduler._hold_naver_rate = f.fc.monotonic, Mock()
                def observe(*args, **kwargs):
                    self.assertEqual(len(reader._timeout_yield_bounds), int(inventory))
                    if inventory:
                        bound = reader._request_limits[0]
                        self.assertIs(bound, reader._timeout_yield_bounds[0])
                        self.assertEqual(bound[0], 24)
                        self.assertAlmostEqual(bound[1] - f.fc.monotonic(), 30, places=2)
                    return M.MorningOutcome(M.OUT_DONE)
                with patch.object(M, 'run_morning', side_effect=observe) as legacy, \
                     patch.object(M, 'run_continuous', side_effect=observe) as continuous:
                    scheduler._morning()
                self.assertEqual((legacy.call_count, continuous.call_count), (int(not inventory), int(inventory)))
                self.assertEqual((reader._request_limits, reader._timeout_yield_bounds), ([], []))

    def test_batch_timeout_keeps_completed_account_checkpoint_and_resumes(self):
        with scene() as f:
            started = f.fc.now()
            def consume_before_last_request(call):
                if call.path == '/stats' and call.query.get('id') == [f'cmp-{TM.B}-1']:
                    elapsed = (f.fc.now() - started).total_seconds()
                    f.fc.advance(30 - .333 - elapsed)
            f.naver.tick = consume_before_last_request
            class LastRequestTimeout:
                failed = False
                timeout = None
                def send(self, request, timeout):
                    q = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
                    if not self.failed and q.get('id') == [f'cmp-{TM.B}-2']:
                        self.failed, self.timeout = True, timeout
                        f.fc.advance(timeout)
                        raise N.TransportNetworkError(N.NetworkDiagnostic('TIMEOUT', 'OPEN',
                            elapsed_ms=round(timeout * 1000), remaining_ms=0), timeout_exhausted=True)
                    return f.naver.send(request, timeout)
            transport = LastRequestTimeout()
            reader = f.reader()
            reader._transport = transport
            with patch.object(N.time, 'monotonic', side_effect=f.fc.monotonic):
                with reader.bounded_requests(max_calls=24, max_seconds=30, yield_on_timeout=True):
                    result = M.run_continuous(reader, f.monitored(), f.fc.now)
            self.assertTrue(transport.failed)
            self.assertAlmostEqual(transport.timeout, .333, places=5)
            self.assertEqual((result.outcome, result.codes), (M.OUT_DONE, ('BUDGET_YIELD',)))
            self.assertIsNone(Scheduler._runtime_problem('morning', result))
            self.assertEqual(f.st.account_day(TM.A, TM.TODAY)['status'], 'ok')
            self.assertIsNone(f.st.account_day(TM.B, TM.TODAY))
            saved = f.st.morning_progress(TM.B, 12, TM.TODAY, f.fc.now())
            self.assertIsNotNone(saved)
            self.assertEqual(set(saved['chunks']), {('summary', 0), ('daily', 0)})
            self.assertTrue(M.continuous_due(f.monitored(), f.fc.now()))
            first_calls = len(f.naver.calls)
            f.naver.tick = None
            next_reader = f.reader()
            with patch.object(N.time, 'monotonic', side_effect=f.fc.monotonic):
                with next_reader.bounded_requests(max_calls=24, max_seconds=30, yield_on_timeout=True):
                    resumed = M.run_continuous(next_reader, f.monitored(), f.fc.now)
            self.assertEqual(resumed.outcome, M.OUT_DONE)
            self.assertEqual(f.st.account_day(TM.B, TM.TODAY)['status'], 'ok')
            self.assertEqual(f.st.account_day(TM.B, TM.TODAY)['yday_spend'], 60000)
            self.assertTrue(all(int(c.customer) == TM.B for c in f.naver.calls[first_calls:]))
            daily = [v for kind, v in f.ads.stats_calls if kind == 'daily']
            self.assertEqual(len(daily), len(set(daily)))
            self.assertIsNone(f.st.morning_progress(TM.B, 12, TM.TODAY, f.fc.now()))


if __name__ == '__main__':
    unittest.main()
