from datetime import datetime, timedelta
import json
import socket
from unittest import TestCase
from unittest.mock import Mock, patch

from naver_engine import alerts as A, links as L, morning as M, store as S, sync as Y
from naver_runtime.config import Config
from naver_runtime.scheduler import Scheduler
from naver_engine.backup import BackupResult
from types import SimpleNamespace
from naver_engine import naver_read as N
from naver_engine.tests.fake_naver import FakeClock, FakeNaver, cycle_str
from naver_engine.tests.test_morning import creds
from naver_engine import monthly_reads as MR, inventory_reads as IR
from naver_engine.tests.test_performance_reads import MemoryPerformance
from naver_engine.tests.test_structure_collector import MemoryStructure
from naver_engine.tests.test_morning import A as CUSTOMER

NOW = datetime(2026, 10, 1, 7, 20, tzinfo=S.KST)


class SchedulerTest(TestCase):
    def inventory_scene(self, kinds=None, campaign_count=0, period_days=1):
        clock, http = FakeClock(NOW.replace(day=15)), FakeNaver()
        store = MemoryPerformance(clock)
        store.structure_work = lambda now, limit: []
        kinds = kinds or ["daily", "weekly", "manual", "backfill"]*3
        store.jobs = [{"customer_id": CUSTOMER+n, "kind": kind, "cycle_day": "2026-10-15",
                       "period_start": (clock.now().date()-timedelta(days=period_days)).isoformat(),
                       "period_end": "2026-10-14",
                       "snapshot_at": clock.now(), "job_key": f"{kind}-{n}"} for n, kind in enumerate(kinds)]
        http.route(r"/ncc/campaigns", lambda call: (200, [
            {"customerId": int(call.customer), "nccCampaignId": f"cmp-{call.customer}-{n}",
             "status": "ELIGIBLE", "userLock": False, "delFlag": False} for n in range(campaign_count)]))
        http.route(r"/billing/bizmoney", lambda call: (200, {"customerId": int(call.customer),
            "bizmoney": 100, "budgetLock": False, "refundLock": False}))
        def stats(call):
            values = {"impCnt": 100, "clkCnt": 10, "salesAmt": 1000, "ccnt": 1, "convAmt": 2000}
            if "ids" in call.query:
                rows = [dict(values, id=cid) for cid in call.query["ids"]]
            else:
                start = datetime.fromisoformat(json.loads(call.query["timeRange"][0])["since"])
                rows = [dict(values, dateStart=(start+timedelta(days=n)).date().isoformat())
                        for n in range(period_days)]
            return 200, {"cycleBaseTm": cycle_str(clock.now()), "data": rows}
        http.route(r"/stats", stats)
        reader = N.NaverReader(creds(), transport=http, clock=clock)
        task = Scheduler(Config("/synthetic/data/db", "/synthetic/socket/sock", inventory_enabled=True),
                         store, naver_factory=lambda: reader, clock=clock.now, monotonic_clock=clock.monotonic)
        task._errors = []
        return clock, http, store, reader, task

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_daily_weekly_manual_backfill_share_one_24_call_30_second_queue(self, _network):
        clock, http, store, reader, task = self.inventory_scene()
        started = clock.now()
        result = task._inventory()
        self.assertGreaterEqual(result.counts.get("ok", 0), 4)
        self.assertLessEqual(len(http.calls), 24)
        self.assertLessEqual((clock.now()-started).total_seconds(), 30)
        self.assertEqual(len(store.results), result.counts["ok"])
        self.assertEqual({key.split("-")[0] for key in store.results}, {"daily", "weekly", "manual", "backfill"})
        self.assertEqual([int(c.customer) for c in http.calls[:6]], [CUSTOMER]*3+[CUSTOMER+1]*3)
        self.assertTrue(all(sum(c.customer == str(job["customer_id"]) for c in http.calls) <= 8 for job in store.jobs))
        self.assertEqual(reader.calls, len(http.calls))

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_full_daily_budget_reserves_six_calls_for_backfill_without_legacy_collectors(self, _network):
        clock, http, store, reader, task = self.inventory_scene(["daily"]*8+["backfill"]*3)
        with patch.object(MR, "run_monthly", side_effect=AssertionError("이전 월누적 수집 금지")) as monthly, \
             patch.object(IR, "run_inventory", side_effect=AssertionError("이전 전일 수집 중복 금지")) as daily:
            result = task._inventory()
            self.assertGreater(result.counts.get("ok", 0), 0)
            self.assertLessEqual(result.counts["ok"], 8)
        self.assertLessEqual(len(http.calls), 24)
        self.assertTrue(any(key.startswith("daily-") for key in store.results))
        self.assertTrue(any(key.startswith("backfill-") for key in store.results))
        self.assertLessEqual(sum(int(call.customer) >= CUSTOMER+8 for call in http.calls), 6)
        monthly.assert_not_called()
        daily.assert_not_called()

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_slow_responses_stop_all_queue_kinds_at_shared_30_second_deadline(self, _network):
        clock, http, store, reader, task = self.inventory_scene(["daily"]*5+["backfill"]*3)
        http.tick = lambda call: clock.advance(2)
        started = clock.now()
        result = task._inventory()
        self.assertEqual(result.code, "BUDGET")
        self.assertLessEqual(len(http.calls), 15)
        self.assertLessEqual((clock.now()-started).total_seconds(), 30)
        self.assertTrue(any(values["status"] == "retry" for values in store.results.values()))
        self.assertTrue(any(key.startswith("daily-") for key in store.results))
        self.assertTrue(any(key.startswith("backfill-") for key in store.results))

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_large_account_checkpoint_keeps_eight_call_cap_and_resumes_with_no_repeated_stats(self, _network):
        clock, http, store, reader, task = self.inventory_scene(["daily"], campaign_count=9, period_days=2)
        started = clock.now()
        self.assertEqual(task._inventory().counts, {"partial": 1})
        self.assertEqual(len(http.calls), 8)
        self.assertLessEqual((clock.now()-started).total_seconds(), 10)
        before = len(http.calls)
        self.assertEqual(task._inventory().counts, {"ok": 1})
        self.assertLessEqual(len(http.calls)-before, 8)
        requests = [call.query["id"][0] for call in http.calls if call.path == "/stats"]
        self.assertEqual(len(requests), 9)
        self.assertEqual(len(set(requests)), 9)

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_any_429_stops_the_queue_before_the_next_account_for_every_job_kind(self, _network):
        for kind in ("daily", "weekly", "manual", "backfill"):
            with self.subTest(kind=kind):
                clock, http, store, reader, task = self.inventory_scene([kind, "daily"])
                http.script("/ncc/campaigns", *[(429, {"code": 429})]*20)
                self.assertEqual(task._inventory().code, "BUDGET")
                self.assertTrue(reader.rate_limited)
                self.assertEqual(reader.pauses, 0)
                self.assertEqual(len(http.calls), 3)
                first = "daily-1" if kind == "backfill" else kind+"-0"
                self.assertEqual(set(store.results), {first})
                self.assertEqual(store.results[first]["status"], "retry")

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_slow_single_account_never_uses_more_than_ten_seconds(self, _network):
        clock, http, store, reader, task = self.inventory_scene(["daily"], campaign_count=9, period_days=2)
        http.tick = lambda call: clock.advance(2)
        started = clock.now()
        self.assertEqual(task._inventory().counts, {"partial": 1})
        self.assertEqual((clock.now()-started).total_seconds(), 10)
        self.assertEqual(len(http.calls), 5)
        self.assertNotIn("daily_rows", store.results["daily-0"])

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_performance_and_structure_share_the_same_account_eight_call_and_ten_second_limits(self, _network):
        for response_seconds in (0, 2):
            with self.subTest(response_seconds=response_seconds):
                clock, http, store, reader, task = self.inventory_scene(["daily"], campaign_count=9)
                structures = MemoryStructure(clock)
                structures.jobs = [dict(store.jobs[0], job_key="structure:"+store.jobs[0]["job_key"])]
                for name in ("structure_work", "structure_account_valid", "begin_structure_check", "structure_progress",
                             "record_structure_progress", "record_structure_check"):
                    setattr(store, name, getattr(structures, name))
                http.route(r"/ncc/(channels|adgroups|ads|keywords|ad-extensions)", lambda call: (200, []))
                http.tick = lambda call: clock.advance(response_seconds)
                started = clock.now()
                task._inventory()
                self.assertLessEqual(len(http.calls), 8)
                self.assertLessEqual((clock.now()-started).total_seconds(), 10)

    @patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
    def test_disjoint_performance_and_structure_accounts_share_global_24_call_30_second_budget(self, _network):
        clock, http, store, reader, task = self.inventory_scene()
        structures = MemoryStructure(clock)
        structures.jobs = [dict(store.jobs[0], customer_id=CUSTOMER+100+n,
                                job_key=f"structure:daily-{n}") for n in range(4)]
        for name in ("structure_work", "structure_account_valid", "begin_structure_check", "structure_progress",
                     "record_structure_progress", "record_structure_check"):
            setattr(store, name, getattr(structures, name))
        http.route(r"/ncc/channels", lambda call: (200, []))
        started = clock.now()
        task._inventory()
        self.assertTrue(store.results)
        self.assertTrue(structures.results)
        self.assertLessEqual(len(http.calls), 24)
        self.assertLessEqual((clock.now()-started).total_seconds(), 30)
        for cid in reader.called_customers:
            self.assertLessEqual(sum(call.customer == str(cid) for call in http.calls), 8)

    def test_inventory_runs_without_morning_or_pairing_and_keeps_bounded_tick(self):
        config = Config("/synthetic/data/db", "/synthetic/socket/sock", inventory_enabled=True)
        calls = []
        fc = FakeClock(NOW)
        reader = N.NaverReader(creds(), transport=FakeNaver(), clock=fc)
        store = Mock()
        store.structure_work.return_value = []
        store.generate_reports.side_effect = lambda now: calls.append("reports") or {"generated": 0}
        task = Scheduler(config, store, erp_factory=lambda: object(), naver_factory=lambda: reader,
                         clock=fc.now, monotonic_clock=fc.monotonic)
        with patch.object(L, "accounts_due", return_value=True), \
             patch.object(L, "sync_accounts", side_effect=lambda *a: calls.append("accounts")), \
             patch.object(L, "pairing_due", side_effect=AssertionError("계약 매칭 불필요")), \
             patch("naver_runtime.scheduler.IC.sync_catalog_due", return_value=True), \
             patch("naver_runtime.scheduler.IC.sync_catalog", side_effect=lambda *a: calls.append("catalog")), \
             patch("naver_runtime.scheduler.PR.run_performance", side_effect=lambda *a, **kw:
                   calls.append("inventory") or SimpleNamespace(code="DONE", counts={})):
            self.assertEqual(task.tick()["state"], "ok")
            task.tick()
            fc.advance(29)
            task.tick()
            self.assertEqual(calls, ["accounts", "catalog", "inventory", "reports"])
            fc.advance(1)
            task.tick()
            self.assertEqual(calls, ["accounts", "catalog", "inventory", "reports", "inventory"])
            fc.advance(30)
            task.tick()
        self.assertEqual(calls, ["accounts", "catalog", "inventory", "reports", "inventory",
                                "accounts", "catalog", "inventory", "reports"])
        self.assertEqual(store.generate_reports.call_count, 2)

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
