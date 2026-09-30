from datetime import datetime
from unittest import TestCase
from unittest.mock import Mock, patch

from naver_engine import alerts as A, links as L, morning as M, store as S, sync as Y
from naver_runtime.config import Config
from naver_runtime.scheduler import Scheduler
from naver_engine.backup import BackupResult

NOW = datetime(2026, 10, 1, 7, 20, tzinfo=S.KST)


class SchedulerTest(TestCase):
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
