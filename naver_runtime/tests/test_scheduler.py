from copy import deepcopy
from datetime import datetime, timedelta
import socket
from unittest import TestCase
from unittest.mock import Mock, patch

from naver_engine import alerts as A, links as L, morning as M, store as S, sync as Y
from naver_runtime.config import Config
from naver_runtime.scheduler import Scheduler
from naver_engine.backup import BackupResult
from types import SimpleNamespace
from naver_engine import naver_read as N
from naver_engine.tests.fake_naver import FakeClock, FakeNaver
from naver_engine.tests.test_morning import creds
from naver_engine import monthly_reads as MR
from naver_engine.tests.test_inventory_throughput import QueueBoundary
from naver_engine.tests.test_morning import A as CUSTOMER

NOW = datetime(2026, 10, 1, 7, 20, tzinfo=S.KST)


class MonthlyQueueBoundary(QueueBoundary):
    """읽기 순서 시험의 저장 경계. SQL 후보 필터는 Linux 저장소 시험에서 검증한다."""
    def __init__(self, now, daily_count=2):
        super().__init__(now, list(range(CUSTOMER, CUSTOMER+11)))
        self.daily_ids = self.ids[:daily_count]
        self.daily_checked = dict.fromkeys(self.ids, now-timedelta(minutes=1))
        self.monthly_data, self.monthly_results = {}, {}
        self.monthly_candidates = []

    def inventory_work(self, now, limit):
        return self.daily_ids[:limit]

    def record_inventory_check(self, cid, snapshot, now, values):
        self.daily_checked[cid] = now
        return super().record_inventory_check(cid, snapshot, now, values)

    def monthly_work(self, now, limit, *, exclude_checked_after=None):
        self.monthly_candidates = [cid for cid in self.ids if self.daily_checked[cid] < exclude_checked_after][:limit]
        return self.monthly_candidates

    def begin_monthly_check(self, cid, snapshot, now):
        if not self.inventory_account_valid(cid, snapshot, now):
            raise S.StoreRefused("시험 원천 변경")

    def monthly_progress(self, cid, start, end):
        return deepcopy(self.monthly_data.get(cid))

    def record_monthly_progress(self, cid, snapshot, now, source):
        MR.validate_progress(source, cid, *MR.window(now.date()))
        self.monthly_data[cid] = deepcopy(source)

    def record_monthly_check(self, cid, snapshot, now, values):
        self.monthly_results[cid] = deepcopy(values)
        return values["status"]


class SchedulerTest(TestCase):
    def inventory_scene(self, daily_count=2):
        clock, http = FakeClock(NOW.replace(day=15)), FakeNaver()
        store = MonthlyQueueBoundary(clock.now(), daily_count)
        http.route(r"/ncc/campaigns", lambda call: (200, []))
        http.route(r"/billing/bizmoney", lambda call: (200, {"customerId": int(call.customer),
            "bizmoney": 100, "budgetLock": False, "refundLock": False}))
        reader = N.NaverReader(creds(), transport=http, clock=clock)
        task = Scheduler(Config("/synthetic/data/db", "/synthetic/socket/sock", inventory_enabled=True),
                         store, naver_factory=lambda: reader, clock=clock.now)
        task._errors = []
        return clock, http, store, reader, task

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_daily_then_monthly_share_24_calls_30_seconds_and_exclude_same_round_accounts(self, _network):
        clock, http, store, reader, task = self.inventory_scene()
        started = clock.now()
        self.assertEqual(task._inventory().counts, {"ok": 2})
        self.assertEqual(len(http.calls), 24)
        self.assertLessEqual((clock.now()-started).total_seconds(), 30)
        self.assertEqual(len(store.monthly_results), 9)
        self.assertFalse(set(store.started).intersection(store.monthly_candidates))
        self.assertEqual([int(c.customer) for c in http.calls[:6]], [CUSTOMER]*3+[CUSTOMER+1]*3)
        self.assertTrue(all(sum(c.customer == str(cid) for c in http.calls) <= 8 for cid in store.ids))
        self.assertEqual(reader.calls, 24)

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_full_daily_budget_never_starts_monthly(self, _network):
        clock, http, store, reader, task = self.inventory_scene(daily_count=8)
        with patch.object(MR, "run_monthly", wraps=MR.run_monthly) as monthly:
            self.assertEqual(task._inventory().counts, {"ok": 8})
        self.assertEqual(len(http.calls), 24)
        monthly.assert_not_called()

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_slow_daily_responses_use_shared_time_budget_before_monthly(self, _network):
        clock, http, store, reader, task = self.inventory_scene(daily_count=5)
        http.tick = lambda call: clock.advance(2)
        started = clock.now()
        with patch.object(MR, "run_monthly", wraps=MR.run_monthly) as monthly:
            task._inventory()
        self.assertEqual(len(http.calls), 15)
        self.assertEqual((clock.now()-started).total_seconds(), 30)
        monthly.assert_not_called()
        self.assertEqual(store.monthly_results, {})

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_daily_rate_pause_does_not_start_monthly_after_bounded_sleep_abort(self, _network):
        clock, http, store, reader, task = self.inventory_scene()
        http.script("/ncc/campaigns", *[(429, {"code": 429})]*20)
        started = clock.now()
        with patch.object(MR, "run_monthly", wraps=MR.run_monthly) as monthly:
            result = task._inventory()
        self.assertEqual(result.code, "DONE")
        self.assertGreater(reader.pauses, 0)
        self.assertLessEqual((clock.now()-started).total_seconds(), 30)
        monthly.assert_not_called()
        self.assertEqual(store.monthly_results, {})

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_any_daily_rate_hit_skips_monthly_even_before_pause_threshold(self, _network):
        clock, http, store, reader, task = self.inventory_scene(daily_count=1)
        http.script("/ncc/campaigns", *[(429, {"code": 429})]*20)
        with patch.object(MR, "run_monthly", wraps=MR.run_monthly) as monthly:
            self.assertEqual(task._inventory().code, "DONE")
        self.assertTrue(reader.rate_limited)
        self.assertEqual(reader.pauses, 0)
        self.assertEqual(len(http.calls), 3)
        monthly.assert_not_called()

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_monthly_rate_hit_records_attempt_but_never_starts_next_account(self, _network):
        clock, http, store, reader, task = self.inventory_scene(daily_count=0)
        http.script("/ncc/campaigns", *[(429, {"code": 429})]*20)
        self.assertEqual(task._inventory().code, "DONE")
        self.assertTrue(reader.rate_limited)
        self.assertEqual(reader.pauses, 0)
        self.assertEqual(len(http.calls), 3)
        self.assertEqual(set(store.monthly_results), {CUSTOMER})
        self.assertEqual(store.monthly_results[CUSTOMER]["status"], "retry")

    def test_inventory_runs_without_morning_or_pairing_and_keeps_bounded_tick(self):
        config = Config("/synthetic/data/db", "/synthetic/socket/sock", inventory_enabled=True)
        calls = []
        fc = FakeClock(NOW)
        reader = N.NaverReader(creds(), transport=FakeNaver(), clock=fc)
        task = Scheduler(config, Mock(), erp_factory=lambda: object(), naver_factory=lambda: reader, clock=lambda: NOW)
        with patch.object(L, "accounts_due", return_value=True), \
             patch.object(L, "sync_accounts", side_effect=lambda *a: calls.append("accounts")), \
             patch.object(L, "pairing_due", side_effect=AssertionError("계약 매칭 불필요")), \
             patch("naver_runtime.scheduler.IC.sync_catalog_due", return_value=True), \
             patch("naver_runtime.scheduler.IC.sync_catalog", side_effect=lambda *a: calls.append("catalog")), \
             patch("naver_runtime.scheduler.IR.run_inventory", side_effect=lambda *a:
                   calls.append("inventory") or SimpleNamespace(code="DONE", counts={})):
            self.assertEqual(task.tick()["state"], "ok")
            task.tick()
        self.assertEqual(calls, ["accounts", "catalog", "inventory"])

    def test_all_off_does_not_create_readers_or_touch_store(self):
        store, factory = Mock(), Mock(side_effect=AssertionError("외부 호출 금지"))
        task = Scheduler(Config("/synthetic/data/db", "/synthetic/socket/sock"), store,
                         erp_factory=factory, naver_factory=factory, alert_factory=factory,
                         clock=lambda: NOW)
        self.assertEqual(task.tick(), {"state": "ok", "errors": []})
        self.assertEqual(store.mock_calls, [])
        factory.assert_not_called()

    def test_order_fresh_readers_and_saved_thresholds(self):
        calls, instances = [], []
        def reader():
            item = object()
            instances.append(item)
            return item
        def step(name):
            return lambda *a, **kw: calls.append(name)
        config = Config("/synthetic/data/db", "/synthetic/socket/sock", sync_enabled=True,
                        links_enabled=True, morning_enabled=True, alerts_enabled=True)
        store = Mock()
        task = Scheduler(config, store, erp_factory=reader, naver_factory=reader,
                         alert_factory=reader, clock=lambda: NOW)
        with patch.object(Y, "org_due", return_value=True), patch.object(Y, "stages_due", return_value=True), \
             patch.object(L, "accounts_due", return_value=True), patch.object(L, "pairing_due", return_value=True), \
             patch.object(M, "morning_due", return_value=True), patch.object(Y, "sync_org", side_effect=step("org")), \
             patch.object(Y, "sync_stages", side_effect=step("stages")), \
             patch.object(L, "sync_accounts", side_effect=step("accounts")), \
             patch.object(L, "pair_links", side_effect=step("pairing")), \
             patch.object(M, "readiness", side_effect=step("readiness")), \
             patch.object(M, "run_morning", side_effect=step("morning")) as morning, \
             patch.object(A, "run_alerts", side_effect=step("alerts")):
            task.tick()
            task.tick()  # 같은 시각에 다시 호출해도 외부 요청을 반복하지 않는다.
        self.assertEqual(calls, ["org", "stages", "accounts", "pairing", "readiness", "morning", "alerts"])
        self.assertEqual(len(instances), 6)
        self.assertEqual(len(set(map(id, instances))), 6)
        self.assertEqual(morning.call_args.kwargs["th"], store.thresholds.return_value)

    def test_prepare_phase_only_sends_system_alerts_no_false_heartbeat(self):
        cfg = Config("/synthetic/data/db", "/synthetic/socket/sock", alerts_enabled=True)
        with patch.object(A, "dispatch") as dispatch, patch.object(A, "run_alerts") as full:
            Scheduler(cfg, Mock(), alert_factory=lambda: object(), clock=lambda: NOW).tick()
        full.assert_not_called()
        self.assertEqual(dispatch.call_args.kwargs["kind"], S.ALERT_SYSTEM)

    def test_failure_is_recorded_without_exception_content_and_next_cycle_continues(self):
        cfg = Config("/synthetic/data/db", "/synthetic/socket/sock", sync_enabled=True)
        with patch.object(Y, "org_due", return_value=True), patch.object(Y, "stages_due", return_value=False), \
             patch.object(Y, "sync_org", side_effect=RuntimeError("SECRET_MARKER")), \
             patch.object(A, "record_system_alert") as alert, self.assertLogs("naver_runtime.scheduler") as logs:
            result = Scheduler(cfg, Mock(), erp_factory=lambda: object(), clock=lambda: NOW).tick()
        self.assertEqual(result, {"state": "failed", "errors": ["org"]})
        self.assertNotIn("SECRET_MARKER", "".join(logs.output))
        alert.assert_called_once()

    def test_backup_runs_after_alerts_and_wait_is_not_failure(self):
        calls = []
        cfg = Config("/synthetic/data/db", "/synthetic/socket/sock", backup_enabled=True, alerts_enabled=True)
        st = Mock()
        st.runs_on.return_value = [{"status": S.RUN_DONE}]
        backup = Mock(side_effect=lambda *args: calls.append("backup") or BackupResult("RETRY_WAIT"))
        task = Scheduler(cfg, st, backup_job=backup, alert_factory=lambda: object(), clock=lambda: NOW)
        with patch.object(A, "dispatch", side_effect=lambda *a, **kw: calls.append("alerts")), \
             patch.object(A, "record_system_alert") as alert:
            self.assertEqual(task.tick()["state"], "ok")
        self.assertEqual(calls, ["alerts", "backup"])
        alert.assert_not_called()

    def test_backup_failure_is_health_failure_and_durable_system_alert(self):
        cfg = Config("/synthetic/data/db", "/synthetic/socket/sock", backup_enabled=True)
        st = Mock()
        st.runs_on.return_value = [{"status": S.RUN_DONE}]
        task = Scheduler(cfg, st, backup_job=lambda *a: BackupResult("UPLOAD_FAILED"), clock=lambda: NOW)
        with patch.object(A, "record_system_alert") as alert:
            self.assertEqual(task.tick(), {"state": "failed", "errors": ["backup"]})
        alert.assert_called_once()

    def test_metrics_never_delays_current_tick_heartbeat_or_backup(self):
        calls = []
        cfg = Config('/synthetic/data/db', '/synthetic/socket/sock', alerts_enabled=True,
                     metrics_enabled=True, backup_enabled=True)
        st = Mock()
        st.runs_on.return_value = [{'status': S.RUN_DONE}]
        task = Scheduler(cfg, st, alert_factory=lambda: object(), metrics_factory=lambda: object(),
                         backup_job=lambda *a: calls.append('backup') or BackupResult('ALREADY_BACKED_UP'),
                         clock=lambda: NOW)
        with patch.object(A, 'dispatch', side_effect=lambda *a, **kw: calls.append('alerts')), \
             patch('naver_runtime.scheduler.G.run_metrics', side_effect=lambda *a, **kw:
                   calls.append('metrics') or SimpleNamespace(code='DONE', counts={})):
            task.tick()
            task.tick()
        self.assertEqual(calls, ['alerts', 'backup', 'metrics'])

    def test_partial_metrics_is_failed_health_and_durable_alert(self):
        for result in (SimpleNamespace(code='NOT_READY', counts={}),
                       SimpleNamespace(code='SOURCE_CHANGED', counts={}),
                       SimpleNamespace(code='BUDGET', counts={}),
                       SimpleNamespace(code='DONE', counts={'held': 1}),
                       SimpleNamespace(code='DONE', counts={'retry': 1}),
                       SimpleNamespace(code='DONE', counts={'no_client': 1})):
            cfg = Config('/data/db', '/socket/api', metrics_enabled=True)
            task = Scheduler(cfg, Mock(), metrics_factory=lambda: object(),
                             alert_factory=lambda: object(), clock=lambda: NOW)
            with patch('naver_runtime.scheduler.G.run_metrics', return_value=result), \
                 patch.object(A, 'record_system_alert') as alert:
                self.assertEqual(task.tick(), {'state': 'failed', 'errors': ['metrics']})
            alert.assert_called_once()
