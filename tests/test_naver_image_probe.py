import importlib.util
import json
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "tools/naver-runtime-image-test.py"
spec = importlib.util.spec_from_file_location("image_probe", PATH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTest(TestCase):
    def test_never_starts_a_container_outside_ci(self):
        with patch.dict(os.environ, {}, clear=True), patch("sys.argv", ["probe", "naver-runtime-ci:" + "a" * 40]), \
             patch.object(probe.subprocess, "run") as execute:
            with self.assertRaises(SystemExit):
                probe.main()
        execute.assert_not_called()

    def test_probe_is_ephemeral_private_and_never_uses_operating_configuration(self):
        seen = []
        def execute(argv, **kwargs):
            self.assertEqual(argv[:4], ["docker", "compose", "--project-name", "naver-raw-env-ci"])
            self.assertIn("--rm", argv)
            compose = Path(argv[argv.index("--file") + 1])
            seen.append(compose.parent)
            config = json.loads(compose.read_text())
            service = config["services"]["probe"]
            self.assertEqual(service["network_mode"], "none")
            self.assertEqual(service["user"], "10001:10001")
            self.assertTrue(service["read_only"])
            self.assertEqual(service["pull_policy"], "never")
            self.assertNotIn("volumes", service)
            self.assertNotIn("ports", service)
            self.assertEqual(service["env_file"][0]["format"], "raw")
            envfile = Path(service["env_file"][0]["path"])
            self.assertEqual(envfile.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(envfile.read_text().splitlines()), 1)
            self.assertIn("$NAVER_PACKAGE_UNSET", envfile.read_text())
            self.assertIn("$$NAVER_PACKAGE_UNSET", service["command"][2])
            self.assertEqual(set(kwargs["env"]), {"PATH", "COMPOSE_DISABLE_ENV_FILE"})
            self.assertTrue(kwargs["check"])
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "PATH": "/usr/bin:/bin"}, clear=True), \
             patch("sys.argv", ["probe", "naver-runtime-ci:" + "a" * 40]), \
             patch.object(probe.subprocess, "run", side_effect=execute) as call:
            probe.main()
        call.assert_called_once()
        self.assertFalse(seen[0].exists())
