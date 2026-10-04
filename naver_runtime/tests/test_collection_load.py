"""1792계정 합성 대기열: 고정 공백만 비교한다. 운영 속도/SQL/WAL 비용 시험이 아니다."""
from datetime import datetime
import socket
from unittest import TestCase
from unittest.mock import patch
from naver_engine import links as L, inventory as IC, naver_read as N, store as S
from naver_engine.tests.fake_naver import FakeClock, FakeNaver
from naver_engine.tests.test_morning import A, creds
from naver_engine.tests.test_performance_reads import MemoryPerformance
from naver_runtime.config import Config
from naver_runtime.scheduler import Scheduler


def simulate(accounts=1792, response_seconds=0, legacy_pause=False):
    clock = FakeClock(datetime(2026, 10, 11, 7, 0, tzinfo=S.KST))
    http, store = FakeNaver(), MemoryPerformance(clock)
    store.jobs = [{"customer_id": A+n, "kind": "daily" if n<285 else "weekly", "cycle_day": "2026-10-11",
        "period_start": "2026-10-10", "period_end": "2026-10-10", "snapshot_at": clock.now(),
        "job_key": f"load-{n}"} for n in range(accounts)]
    store.performance_work = lambda now,limit: [j for j in store.jobs if j["job_key"] not in store.results][:limit]
    store.structure_work = lambda now,limit: []
    store.account_catalog_status = lambda: {"at": clock.now().isoformat()}
    store.generate_reports = lambda now: None
    sent, per_tick = [], []
    def response(call):
        sent.append(clock.monotonic())
        clock.advance(response_seconds)
    http.tick = response
    http.route(r"/ncc/campaigns", lambda call: (200, []))
    http.route(r"/billing/bizmoney", lambda call: (200, {"customerId":int(call.customer),
        "bizmoney":100,"budgetLock":False,"refundLock":False}))
    task = Scheduler(Config("/synthetic/db", "/synthetic/sock", inventory_enabled=True),store,
        naver_factory=lambda:N.NaverReader(creds(),transport=http,clock=clock),
        clock=clock.now,monotonic_clock=clock.monotonic)
    began = clock.monotonic()
    with patch.object(socket.socket,"connect",side_effect=AssertionError("외부 송신 금지")), \
         patch.object(L,"accounts_due",return_value=False), patch.object(IC,"sync_catalog_due",return_value=False):
        for _ in range(accounts):
            before = len(http.calls)
            outcome = task.tick()
            if outcome["state"] != "ok":
                raise AssertionError(outcome)
            per_tick.append(len(http.calls)-before)
            if len(store.results) == accounts:
                break
            clock.advance(max(task.next_delay(),30 if legacy_pause and len(http.calls)>before else 0))
        else:
            raise AssertionError("합성 수집이 정해진 회차 안에 끝나지 않았습니다")
    return {"accounts":len(store.results),"calls":len(http.calls),"ticks":len(per_tick),
        "max_calls_per_tick":max(per_tick),"seconds":clock.monotonic()-began,
        "minimum_gap":min(b-a for a,b in zip(sent,sent[1:]))}


class CollectionLoadTests(TestCase):
    def test_1792_queue_finishes_with_identical_get_count_without_fixed_gaps(self):
        for latency in (0,2):
            with self.subTest(synthetic_response_seconds=latency):
                baseline = simulate(response_seconds=latency,legacy_pause=True)
                current = simulate(response_seconds=latency)
                self.assertEqual((baseline["accounts"],current["accounts"]),(1792,1792))
                self.assertEqual(baseline["calls"],current["calls"])
                self.assertLess(current["seconds"],baseline["seconds"])
                self.assertLessEqual(current["max_calls_per_tick"],24)
                self.assertGreaterEqual(current["minimum_gap"],1/N.CALLS_PER_SEC-1e-8)
