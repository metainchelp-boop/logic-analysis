import contextlib
import io
import json
import tempfile
from pathlib import Path
from threading import Event
from unittest import TestCase
from unittest.mock import Mock, patch

from naver_engine.tests import test_morning as TM
from naver_engine.tests.fake_naver import FakeClock, FakeNaver, AGENCY_ID, MARK_API_KEY, MARK_SECRET
from naver_engine.tests.test_erp_read import FakeErp, MARK_KEY
from naver_engine import store as S, erp_read as E, inventory_reads as IR
from naver_runtime import __main__ as main
from naver_runtime.config import Config, ConfigError
from naver_runtime.tests.test_server import request


class InventoryRuntimeTest(TestCase):
    def runtime(self, *, setup=None, catalog_warmed=True, read_catalog=True):
        """실제 조립·Writer 큐·예약 회차·UNIX HTTP. 외부 전송과 시계만 합성한다."""
        class Clock(FakeClock):
            def before_network(self):
                pass
        clock, stop, health = Clock(TM.T0), Event(), []
        naver = FakeNaver()
        ads = TM.Ads(naver)
        ads.add(TM.A, [], biz=10)
        ads.add(TM.B, [], biz=20)
        with tempfile.TemporaryDirectory(prefix="nv-runtime-", dir="/tmp") as folder:
            root = Path(folder).resolve()
            (root/"data").mkdir()
            (root/"socket").mkdir()
            env = {"NAVER_ENGINE_DB": str(root/"data/engine.db"),
                   "NAVER_ENGINE_SOCKET": str(root/"socket/api.sock"),
                   "NAVER_ENGINE_ERP_TUNNEL_SOCKET": str(root/"tunnel/erp.sock"),
                   "NAVER_ENGINE_BACKUP_DIR": str(root/"backup"),
                   "NAVER_ENGINE_INVENTORY_ENABLED": "true",
                   "NAVER_ENGINE_ERP_KEY": MARK_KEY, "NAVER_MGR_CUSTOMER_ID": str(AGENCY_ID),
                   "NAVER_MGR_API_KEY": MARK_API_KEY, "NAVER_MGR_SECRET_KEY": MARK_SECRET}
            config = Config.from_env(env)
            with S.open_writer(config.db, clock=clock.now) as store:
                store.record_accounts(TM.kids(TM.A, TM.B), clock.now())
                if setup is not None:
                    setup(store, clock, ads, naver)
                body = {"generated_at": clock.now().isoformat(), "total": 0, "complete": True, "items": []}
                if catalog_warmed:
                    store.record_account_catalog(body, (), clock.now())
            erp = FakeErp(ids={"generated_at": clock.now().isoformat(), "items": []})
            erp.override[(E.PATH_ACCOUNT_CATALOG, None)] = (
                200, json.dumps({"status": 200, "result": body}).encode())
            def after_tick(seconds):
                self.assertEqual(seconds, 60)
                health.append(request(config.socket))
                stop.set()
                return True
            with patch.object(main, "InterruptibleClock", return_value=clock), \
                 patch.object(main.N, "SystemClock", return_value=clock), \
                 patch.object(main.N, "UrllibTransport", return_value=naver), \
                 patch.object(main, "ErpTunnelTransport", return_value=erp), \
                 patch.object(stop, "wait", side_effect=after_tick):
                self.assertEqual(main.run(config, env, stop=stop), 0)
            with S.open_reader(config.db) as store:
                rows = store.inventory_checks_on(clock.now().date())
                catalog = store.account_catalog_status() if read_catalog else None
            self.assertEqual(len(health), 1)
            self.assertTrue(all(call.method == "GET" and not call.has_body for call in naver.calls))
            self.assertTrue(all(call["method"] == "GET" and not call["has_body"] for call in erp.calls))
            return health[0], rows, naver.calls, erp.calls, catalog

    def test_warmed_catalog_and_accounts_reach_inventory_through_actual_runtime(self):
        health, rows, calls, erp, catalog = self.runtime()
        self.assertEqual(health[0], 200, health[1])
        self.assertEqual(health[1]["state"], "ok")
        self.assertEqual({cid: row["status"] for cid, row in rows.items()}, {TM.A: "ok", TM.B: "ok"})
        self.assertEqual(len(calls), 6)
        self.assertEqual(erp, [])
        self.assertEqual(catalog["state"], "accepted")

    def test_denied_account_keeps_its_warning_without_failing_runtime_health(self):
        def denied(store, clock, ads, naver):
            ads.fail[(TM.A, "camps")] = (403, {"code": 1006})
        health, rows, calls, erp, _ = self.runtime(setup=denied)
        self.assertEqual(rows[TM.A]["status"], "reauth_required")
        self.assertEqual(rows[TM.A]["error_code"], "KEY_REJECTED")
        self.assertIsNone(rows[TM.A]["yday_spend"])
        self.assertEqual(rows[TM.B]["status"], "ok")
        self.assertEqual(len(calls), 4)
        self.assertEqual(erp, [])
        self.assertEqual(health[0], 200, health[1])

    def test_due_catalog_uses_exact_two_readers_through_writer_before_inventory(self):
        health, rows, _, erp, catalog = self.runtime(catalog_warmed=False)
        self.assertEqual(health[0], 200, health[1])
        self.assertEqual([call["path"] for call in erp], [E.PATH_ACCOUNT_CATALOG, E.PATH_NAVER_IDS])
        self.assertEqual(catalog["state"], "accepted")
        self.assertEqual([row["status"] for row in rows.values()], ["ok", "ok"])

    def test_retry_and_exhausted_account_keep_unknown_amounts_and_do_not_fail_health(self):
        for prior_attempts, expected in ((0, "retry"), (3, "limited")):
            with self.subTest(status=expected):
                def incomplete(store, clock, ads, naver):
                    ads.add(TM.A, [(1, "ELIGIBLE", False, TM.steady(0, 0, 0, 0))], biz=10)
                    # 합계 생략만으로 미완결이 아니다. 일별 0 증거도 없게 만든다.
                    ads.drop_days[f"cmp-{TM.A}-1"] = {TM.YDAY}
                    for _ in range(prior_attempts):
                        IR.run_inventory(main.N.NaverReader(TM.creds(), transport=naver, clock=clock), store, clock.now)
                        clock.advance(1800)
                    naver.calls.clear()
                health, rows, calls, erp, _ = self.runtime(setup=incomplete)
                self.assertEqual(rows[TM.A]["status"], expected)
                self.assertIsNone(rows[TM.A]["yday_spend"])
                self.assertIsNotNone(rows[TM.A]["error_code"])
                self.assertEqual(rows[TM.B]["status"], "ok")
                self.assertLessEqual(len(calls), 7)  # 누락 캠페인의 일별 증거 확인 1회 포함
                self.assertEqual(erp, [])
                self.assertEqual(health[0], 200, health[1])

    def test_partial_checkpoint_is_not_complete_and_keeps_existing_call_budget(self):
        def large(store, clock, ads, naver):
            ads.add(TM.A, [(n, "ELIGIBLE", False, TM.steady()) for n in range(601)], biz=10)
        health, rows, calls, _, _ = self.runtime(setup=large)
        self.assertEqual(health[0], 200, health[1])
        self.assertEqual(rows[TM.A]["status"], "partial")
        self.assertEqual(rows[TM.A]["error_code"], "CHECKPOINT_PENDING")
        self.assertIsNone(rows[TM.A]["yday_spend"])
        self.assertEqual(rows[TM.B]["status"], "ok")
        self.assertLessEqual(len(calls), 24)
        self.assertLessEqual(sum(call.customer == str(TM.A) for call in calls), 8)

    def test_not_ready_source_keeps_failed_health_without_network_reads(self):
        def refused(store, clock, ads, naver):
            store.record_sync_event(S.SYNC_ACCOUNTS, S.SYNC_FAILED, ("INCOMPLETE_LIST",), clock.now())
        health, rows, calls, erp, _ = self.runtime(setup=refused)
        self.assertEqual(health[0], 503)
        self.assertEqual(health[1]["errors"], ["inventory"])
        self.assertEqual((rows, calls, erp), ({}, [], []))

    def test_source_change_during_read_keeps_failed_health_and_stops_next_account(self):
        def change(store, clock, ads, naver):
            naver.tick = lambda call: clock.advance(31*3600)
        health, rows, calls, erp, _ = self.runtime(setup=change)
        self.assertEqual(health[0], 503)
        self.assertEqual(health[1]["errors"], ["inventory"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(erp, [])
        self.assertFalse(any(row["status"] == "ok" for row in rows.values()))

    def test_unexpected_stored_catalog_error_keeps_failed_health_before_network(self):
        def corrupt(store, clock, ads, naver):
            store.record_account_catalog_failure(clock.now(), "CATALOG_FAILED")
            # 디스크 오류 fixture: 공개 저장 API가 만들 수 없는 손상을 주입한다.
            store._conn.execute("UPDATE naver_auto_meta SET value = ? WHERE key = ?",
                                ("{invalid-json", "account_catalog_status"))
        with self.assertLogs("naver_runtime", level="ERROR") as logs:
            health, rows, calls, erp, _ = self.runtime(setup=corrupt, catalog_warmed=False, read_catalog=False)
        self.assertEqual(health[0], 503)
        self.assertEqual(health[1]["errors"], ["scheduler"])
        self.assertEqual((rows, calls, erp), ({}, [], []))
        self.assertTrue(any("StoreError" in line for line in logs.output))


class MainTest(TestCase):
    def test_restricted_runtime_rejects_unapproved_flags_before_keys_or_storage(self):
        for flag in ("alerts_enabled", "metrics_enabled", "issue_alerts_enabled"):
            config = Config("/synthetic/data/db", "/synthetic/web/api", **{flag: True})
            with self.subTest(flag=flag), \
                 patch.object(main.E, "load_erp_key", side_effect=AssertionError), \
                 patch.object(main, "load_manager_credentials", side_effect=AssertionError), \
                 patch.object(main, "Writer", side_effect=AssertionError), \
                 self.assertRaises(ConfigError):
                main.run(config, {}, stop=Event())

    def test_all_commands_reject_alerts_including_no_network_checks(self):
        for command in ("check-config", "dry-run", "run"):
            with self.subTest(command=command), \
                 patch.object(main.E, "load_erp_key", side_effect=AssertionError), \
                 patch.object(main, "Writer", side_effect=AssertionError), \
                 contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main.main([command], env={"NAVER_ENGINE_ALERTS_ENABLED": "true"}), 2)

    def test_checks_do_not_open_store_server_or_read_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {"NAVER_ENGINE_DB": folder + "/data/db", "NAVER_ENGINE_SOCKET": folder + "/socket/api"}
            for command in ("check-config", "dry-run"):
                output = io.StringIO()
                with patch.object(main, "Writer", side_effect=AssertionError), \
                     patch.object(main, "UnixServer", side_effect=AssertionError), \
                     patch.object(main, "load_manager_credentials", side_effect=AssertionError), \
                     patch.object(main.E, "load_erp_key", side_effect=AssertionError), contextlib.redirect_stdout(output):
                    self.assertEqual(main.main([command], env=env), 0)
                body = json.loads(output.getvalue())
                self.assertFalse(body["network_performed"])
                self.assertFalse(any(body["switches"].values()))
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_invalid_config_does_not_echo_values(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            code = main.main(["check-config"], env={"NAVER_ENGINE_SYNC_ENABLED": "SECRET_MARKER"})
        self.assertEqual(code, 2)
        self.assertNotIn("SECRET_MARKER", output.getvalue())

    def test_missing_credentials_fail_before_opening_store(self):
        with patch.object(main.platform, "system", return_value="Linux"), \
             patch.object(main, "Writer") as writer, contextlib.redirect_stderr(io.StringIO()):
            code = main.main(["run"], env={"NAVER_ENGINE_SYNC_ENABLED": "true"})
        self.assertEqual(code, 2)
        writer.assert_not_called()

    def test_off_assembly_never_loads_keys(self):
        config = Config("/synthetic/data/db", "/synthetic/socket/api")
        with patch.object(main.E, "load_erp_key", side_effect=AssertionError), \
             patch.object(main, "load_manager_credentials", side_effect=AssertionError):
            options = main.dependencies(config, {}, main.InterruptibleClock(Event()))
        self.assertTrue(all(value is None for value in options.values()))

    def test_stop_interrupts_once_then_allows_run_cleanup_time(self):
        stop = Event()
        clock = main.InterruptibleClock(stop)
        stop.set()
        with self.assertRaises(main.StopRequested):
            clock.now()
        self.assertIsNotNone(clock.now().tzinfo)
        clock.sleep(300)  # 중지 뒤 재시도 대기를 하지 않는다.

    def test_existing_orphan_is_audited_before_first_tick(self):
        store = Mock(orphaned_runs=2)
        with patch.object(main.A, "record_system_alert") as alert:
            main.note_orphaned(store, main.N.SystemClock().now())
        alert.assert_called_once()

    def test_all_off_run_ticks_and_closes_without_external_calls(self):
        stop = Event()
        writer = Mock()
        writer.__enter__ = Mock(return_value=writer)
        writer.__exit__ = Mock(return_value=False)
        server = Mock()
        server.__enter__ = Mock(return_value=server)
        server.__exit__ = Mock(return_value=False)
        scheduler = Mock()
        scheduler.tick.side_effect = lambda: (stop.set() or {"state": "ok", "errors": []})
        with patch.object(main, "Writer", return_value=writer), \
             patch.object(main, "UnixServer", return_value=server), \
             patch.object(main, "Scheduler", return_value=scheduler), \
             patch.object(main, "dependencies", return_value={}):
            self.assertEqual(main.run(Config("/data/db", "/socket/api"), {}, stop=stop), 0)
        scheduler.tick.assert_called_once()
        writer.__exit__.assert_called_once()
        server.__exit__.assert_called_once()

    def test_bootstrap_runs_after_web_open_before_first_scheduler_tick(self):
        stop, events = Event(), []
        writer, server, scheduler = Mock(), Mock(), Mock()
        writer.__enter__ = Mock(return_value=writer)
        writer.__exit__ = Mock(return_value=False)
        server.__enter__ = Mock(side_effect=lambda: events.append("web_open"))
        server.__exit__ = Mock(return_value=False)
        scheduler.tick.side_effect = lambda: (events.append("tick") or stop.set() or {"state": "ok"})
        with patch.object(main, "Writer", return_value=writer), \
             patch.object(main, "UnixServer", return_value=server), \
             patch.object(main, "Scheduler", return_value=scheduler), \
             patch.object(main, "dependencies", return_value={}), \
             patch.object(main.B, "execute", side_effect=lambda *a: events.append("bootstrap") or {"status": "partial"}):
            main.run(Config("/data/db", "/socket/api"), {"NAVER_ENGINE_BOOTSTRAP_REQUEST": "synthetic"}, stop=stop)
        self.assertEqual(events, ["web_open", "bootstrap", "tick"])

    def test_bootstrap_transport_caps_timeout_and_refuses_after_budget(self):
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 10, 1, 14, tzinfo=timezone(timedelta(hours=9)))
        base = Mock()
        base.now.return_value = now
        base.monotonic.return_value = 0
        bounded = main.B.BootstrapClock(base, 2, now + timedelta(seconds=10))
        transport = Mock()
        wrapped = main.StopAwareTransport(bounded, transport)
        wrapped.send("synthetic", 20)
        transport.send.assert_called_once_with("synthetic", 2)
        base.now.return_value = now + timedelta(seconds=2)
        base.monotonic.return_value = 2
        with self.assertRaises(main.N.RunAbort):
            wrapped.send("synthetic", 20)
        self.assertEqual(transport.send.call_count, 1)
