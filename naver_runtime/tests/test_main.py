import contextlib
import io
import json
import tempfile
from pathlib import Path
from threading import Event
from unittest import TestCase
from unittest.mock import Mock, patch

from naver_runtime import __main__ as main
from naver_runtime.config import Config


class MainTest(TestCase):
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
