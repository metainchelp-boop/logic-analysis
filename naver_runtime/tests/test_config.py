import tempfile
import unittest
from pathlib import Path

from naver_runtime.config import Config, ConfigError


class ConfigTest(unittest.TestCase):
    def test_defaults_are_off_without_secrets_or_file_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {"NAVER_ENGINE_DB": folder + "/missing/engine.db",
                   "NAVER_ENGINE_SOCKET": folder + "/socket/engine.sock"}
            config = Config.from_env(env)
            self.assertFalse(any(config.switches().values()))
            self.assertEqual(list(Path(folder).iterdir()), [])
            self.assertNotIn("SECRET", repr(config))

    def test_unknown_boolean_is_not_silently_off(self):
        with self.assertRaisesRegex(ConfigError, "설정"):
            Config.from_env({"NAVER_ENGINE_SYNC_ENABLED": "treu"})

    def test_morning_requires_both_inputs(self):
        with self.assertRaises(ConfigError):
            Config.from_env({"NAVER_ENGINE_MORNING_ENABLED": "true"})

    def test_metrics_requires_morning_and_alerts_to_keep_heartbeat_first(self):
        with self.assertRaises(ConfigError):
            Config.from_env({"NAVER_ENGINE_METRICS_ENABLED": "true"})
        cfg = Config.from_env({f"NAVER_ENGINE_{key}_ENABLED": "true"
                               for key in ('METRICS', 'SYNC', 'LINKS', 'MORNING', 'ALERTS')})
        self.assertTrue(cfg.metrics_enabled)

    def test_web_remains_opt_in_after_exchange_code(self):
        self.assertFalse(Config.from_env({}).web_enabled)
        self.assertTrue(Config.from_env({"NAVER_ENGINE_WEB_ENABLED": "true"}).web_enabled)

    def test_inventory_is_off_by_default_and_does_not_require_erp_contract_checks(self):
        self.assertFalse(Config.from_env({}).inventory_enabled)
        config = Config.from_env({"NAVER_ENGINE_INVENTORY_ENABLED": "true"})
        self.assertTrue(config.inventory_enabled)
        self.assertFalse(config.morning_enabled)
        self.assertFalse(config.metrics_enabled)
        self.assertTrue(config.switches()["inventory"])

    def test_paths_cannot_point_into_code_or_be_relative(self):
        for db in ("engine.db", str(Path(__file__).resolve().parents[2] / "engine.db")):
            with self.subTest(db=db), self.assertRaises(ConfigError):
                Config.from_env({"NAVER_ENGINE_DB": db})

    def test_shadow_dates_cannot_be_shortened(self):
        with self.assertRaises(ConfigError):
            Config.from_env({"NAVER_ENGINE_ISSUE_ALERTS_ENABLED": "true",
                             "NAVER_ENGINE_SHADOW_START": "2026-10-01",
                             "NAVER_ENGINE_ISSUE_ALERTS_FROM": "2026-10-02"})

    def test_tunnel_default_and_canonical_absolute_path(self):
        self.assertEqual(Config.from_env({}).erp_tunnel_socket, "/run/naver-erp-tunnel/erp.sock")
        for value in ("relative/erp.sock", "/erp.sock", "/run//tunnel/erp.sock",
                      "/run/tunnel/../erp.sock", "/run/./tunnel/erp.sock", "/run/tunnel/",
                      "/run/" + "x" * 101, "/run/tunnel/erp\0.sock"):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                Config.from_env({"NAVER_ENGINE_ERP_TUNNEL_SOCKET": value})

    def test_runtime_tunnel_directory_cannot_overlap_other_storage(self):
        base = {"NAVER_ENGINE_DB": "/synthetic/data/db",
                "NAVER_ENGINE_SOCKET": "/synthetic/web/api.sock",
                "NAVER_ENGINE_BACKUP_DIR": "/synthetic/backup"}
        for parent in ("/synthetic/data", "/synthetic/data/child", "/synthetic",
                       "/synthetic/web", "/synthetic/web/child", "/synthetic/backup",
                       "/synthetic/backup/child"):
            env = dict(base, NAVER_ENGINE_ERP_TUNNEL_SOCKET=parent + "/erp.sock")
            with self.subTest(parent=parent), self.assertRaises(ConfigError):
                Config.from_env(env).validate_runtime(env)
        env = dict(base, NAVER_ENGINE_ERP_TUNNEL_SOCKET="/synthetic/tunnel/erp.sock")
        Config.from_env(env).validate_runtime(env)

    def test_runtime_tunnel_rejects_symlink_alias_of_data_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            (root / "alias").symlink_to(root / "data", target_is_directory=True)
            env = {"NAVER_ENGINE_DB": str(root / "data/db"),
                   "NAVER_ENGINE_ERP_TUNNEL_SOCKET": str(root / "alias/erp.sock")}
            with self.assertRaises(ConfigError):
                Config.from_env(env).validate_runtime(env)


if __name__ == "__main__":
    unittest.main()
