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

    def test_public_web_cannot_be_enabled_before_exchange_code(self):
        with self.assertRaisesRegex(ConfigError, "일회용"):
            Config.from_env({"NAVER_ENGINE_WEB_ENABLED": "true"})

    def test_paths_cannot_point_into_code_or_be_relative(self):
        for db in ("engine.db", str(Path(__file__).resolve().parents[2] / "engine.db")):
            with self.subTest(db=db), self.assertRaises(ConfigError):
                Config.from_env({"NAVER_ENGINE_DB": db})

    def test_shadow_dates_cannot_be_shortened(self):
        with self.assertRaises(ConfigError):
            Config.from_env({"NAVER_ENGINE_ISSUE_ALERTS_ENABLED": "true",
                             "NAVER_ENGINE_SHADOW_START": "2026-10-01",
                             "NAVER_ENGINE_ISSUE_ALERTS_FROM": "2026-10-02"})


if __name__ == "__main__":
    unittest.main()
