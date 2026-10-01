"""S14 패키징 계약 검사. Docker daemon·실계정·실제 env 파일은 사용하지 않는다."""
from __future__ import annotations

from decimal import Decimal
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FLAGS = (
    "SYNC_ENABLED", "LINKS_ENABLED", "MORNING_ENABLED", "ALERTS_ENABLED", "METRICS_ENABLED",
    "BACKUP_ENABLED", "WEB_ENABLED", "ISSUE_ALERTS_ENABLED",
)
SECRET_NAMES = (
    "NAVER_ENGINE_ERP_KEY", "NAVER_AUTO_TOKEN_SECRET", "NAVER_MGR_CUSTOMER_ID",
    "NAVER_MGR_API_KEY", "NAVER_MGR_SECRET_KEY", "SSO_NAVER_CONTROL_CLIENT_KEY",
)
RAW_CANARY_NAME = "NAVER_PACKAGE_RAW_CANARY"
RAW_CANARY_VALUE = 'literal:$NAVER_PACKAGE_UNSET:${NAVER_PACKAGE_UNSET:-expanded}:$$:"quoted"'


def source(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def env_example():
    return dict(line.split("=", 1) for line in source("deploy/naver-engine.env.example").splitlines()
                if line and not line.startswith("#"))


def compose_model(*files, project="naver-engine", resolve_env=False, ad_sso_key=None):
    # PATH만 상속하고 명시된 합성 키만 추가한다. 실제 NAVER/ERP/SSO 값·사용자 .env는 읽지 않는다.
    env = {"PATH": os.environ.get("PATH", ""), "COMPOSE_DISABLE_ENV_FILE": "1"}
    if ad_sso_key is not None:
        env["SSO_AD_CENTER_CLIENT_KEY"] = ad_sso_key
    executable = shutil.which("docker-compose")
    argv = [executable] if executable else [shutil.which("docker") or "docker", "compose"]
    try:
        version = subprocess.run(argv + ["version"], env=env, capture_output=True, timeout=10)
    except FileNotFoundError:
        raise unittest.SkipTest("Compose CLI 없음 — 파일 자체 검사는 별도로 수행") from None
    if version.returncode:
        raise unittest.SkipTest("Compose CLI 없음 — 파일 자체 검사는 별도로 수행")
    argv += ["--project-name", project]
    for file in files:
        argv += ["--file", str(ROOT / file)]
    # 일부 Compose v2는 --no-env-resolution에도 env_file을 environment로 펼친다.
    # 공개 예시와 합성 canary만 사용해 raw 값 보존을 그 출력에서도 검사한다.
    with tempfile.TemporaryDirectory(prefix="naver-compose-test-") as folder:
        env_path = Path(folder) / "synthetic.env"
        env_path.write_text(source("deploy/naver-engine.env.example") + "\n"
                            + RAW_CANARY_NAME + "=" + RAW_CANARY_VALUE + "\n", encoding="utf-8")
        env["NAVER_ENGINE_ENV_FILE"] = str(env_path)
        options = ["config", "--format", "json"]
        if not resolve_env:
            options.append("--no-env-resolution")
        result = subprocess.run(argv + options,
                                cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise AssertionError("합성 Compose config 검사 실패: " + result.stderr)
    return json.loads(result.stdout)


class PackagingSourceTest(unittest.TestCase):
    def assert_ci_job_isolation(self, workflow):
        # 일반 개발 검사는 무자격, 실제 수용 검사는 승인된 job별 키만 사용한다.
        global_part, marker, job_part = workflow.partition('\njobs:\n')
        self.assertTrue(marker)
        self.assertNotRegex(global_part, r'\bsecrets\b')
        pieces = re.split(r'(?m)^  ([a-z][a-z0-9-]*):\n', job_part)
        self.assertEqual('', pieces[0])
        jobs = dict(zip(pieces[1::2], pieces[2::2]))
        self.assertEqual({'linux-tests', 'backup-probe', 'backup-transfer', 'backup-recovery'}, set(jobs))
        self.assertEqual(len(jobs), len(pieces[1::2]))
        self.assertNotRegex(jobs['linux-tests'], r'\bsecrets\b|(?m:^    (?:environment|needs):)')
        branch = "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/codex/naver-backup-recovery-20261001'"
        self.assertIn(branch + " && inputs.backup_acceptance == 'none' && inputs.received_synthetic_json == ''", jobs['linux-tests'])
        expected = {
            'backup-probe': {'NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY', 'NAVER_BACKUP_KNOWN_HOSTS'},
            'backup-transfer': {'NAVER_BACKUP_RECIPIENT_CERT_PEM', 'NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY', 'NAVER_BACKUP_KNOWN_HOSTS'},
            'backup-recovery': {'NAVER_BACKUP_RECIPIENT_CERT_PEM', 'NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM',
                                'SSO_AD_CENTER_CLIENT_KEY', 'SSO_NAVER_CONTROL_CLIENT_KEY',
                                'NAVER_ENGINE_ERP_KEY', 'NAVER_AUTO_TOKEN_SECRET'},
        }
        for job, secrets in expected.items():
            body = jobs[job]
            condition = ("(inputs.backup_acceptance == 'keys' || inputs.backup_acceptance == 'restore')"
                         if job == 'backup-recovery' else "inputs.backup_acceptance == '" + job.removeprefix('backup-') + "'")
            self.assertIn('    if: ' + branch + ' && ' + condition + '\n', body)
            refs = re.findall(r'\bsecrets\.([A-Z_]+)\b', body)
            self.assertEqual(secrets, set(refs), job)
            self.assertEqual(len(secrets), len(refs), job + ': each secret reference must occur exactly once')
            self.assertEqual(len(refs), len(re.findall(r'\bsecrets\b', body)), job)
            self.assertNotIn('needs:', body)
        recovery = jobs['backup-recovery']
        self.assertIn('    environment: naver-backup-recovery\n', recovery)
        self.assertIn('unshare --net -- setpriv --reuid', recovery)
        for name in ('SSO_AD_CENTER_CLIENT_KEY', 'SSO_NAVER_CONTROL_CLIENT_KEY',
                     'NAVER_ENGINE_ERP_KEY', 'NAVER_AUTO_TOKEN_SECRET'):
            expression = '          ' + name + ": ${{ inputs.backup_acceptance == 'keys' && secrets." + name + " || '' }}"
            self.assertRegex(recovery, '(?m)^' + re.escape(expression) + '$')

    def test_every_bind_explicitly_disables_host_path_creation_in_source(self):
        for file, expected_count in (("compose.naver-engine.yml", 3),
                                     ("deploy/naver-engine-backup.override.yml", 3),
                                     ("deploy/naver-engine-ad-api.override.yml", 1)):
            lines = source(file).splitlines()
            starts = [i for i, line in enumerate(lines) if line.strip() == "- type: bind"]
            self.assertEqual(expected_count, len(starts), file)
            for start in starts:
                indent = len(lines[start]) - len(lines[start].lstrip())
                block = []
                for line in lines[start + 1:]:
                    if (line.strip() and not line.lstrip().startswith("#")
                            and len(line) - len(line.lstrip()) <= indent):
                        break
                    block.append(line)
                self.assertRegex("\n".join(block),
                                 rf"(?m)^ {{{indent + 2}}}bind:\n {{{indent + 4}}}create_host_path: false$",
                                 file + ": " + lines[start])

    def test_every_function_and_relay_default_off(self):
        values = env_example()
        for flag in FLAGS:
            self.assertEqual("false", values["NAVER_ENGINE_" + flag], flag)
        self.assertEqual("off", values["NAVER_AUTO_WEB"])
        self.assertEqual("", values["NAVER_AUTO_ENGINE"])

    def test_credentials_empty_and_no_private_decryption_key(self):
        values = env_example()
        for name in SECRET_NAMES:
            self.assertEqual("", values[name], name)
        self.assertFalse(any("PRIVATE" in name or "DECRYPT" in name for name in values))
        for file in ("Dockerfile.naver-engine", "compose.naver-engine.yml",
                     "deploy/naver-engine-backup.override.yml", "deploy/naver-engine.env.example"):
            self.assertNotRegex(source(file), r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")

    def test_image_has_only_engine_and_pure_backend_code(self):
        dockerfile = source("Dockerfile.naver-engine")
        self.assertIn("FROM python:3.12-slim-trixie", dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn('CMD ["python", "-m", "naver_runtime", "run"]', dockerfile)
        copies = re.findall(r"^COPY (.+)$", dockerfile, re.M)
        self.assertEqual([
            "naver_engine/ ./naver_engine/", "naver_runtime/ ./naver_runtime/",
            "backend/app/__init__.py ./backend/app/__init__.py",
            "backend/app/naver_auto/ ./backend/app/naver_auto/",
        ], copies)
        self.assertNotRegex(dockerfile, r"(?m)^EXPOSE\s")
        self.assertIn("openssl openssh-client", dockerfile)
        self.assertEqual(b"", (ROOT / "backend/app/__init__.py").read_bytes())

    def test_build_context_defaults_denied(self):
        rules = [line for line in source("Dockerfile.naver-engine.dockerignore").splitlines()
                 if line and not line.startswith("#")]
        self.assertEqual("**", rules[0])
        for rule in ("**/*.db*", "**/.env*", "**/*.pem", "**/*.key*", "**/tests/"):
            self.assertIn(rule, rules)
        self.assertFalse(any("README" in rule or "HANDOVER" in rule for rule in rules))
        self.assertNotIn("!backend/**", rules)

    def test_nginx_is_include_not_replacement_and_never_logs_raw_access(self):
        content = source("deploy/naver-engine-nginx.conf")
        active = "\n".join(line for line in content.splitlines() if not line.lstrip().startswith("#"))
        self.assertNotRegex(active, r"\b(?:server|http)\s*\{")
        self.assertNotRegex(active, r"\b(?:listen|server_name)\b")
        self.assertIn("access_log off;", active)
        self.assertEqual(1, active.count("access_log"))
        for value in ("$request", "$args", "$query_string", "$http_referer", "$http_authorization"):
            self.assertNotIn(value, active)
        blocks = re.findall(r"location\s+[^\{]+\{([^}]+)\}", active)
        self.assertEqual(3, len(blocks))
        for block in blocks:
            self.assertIn("proxy_set_header X-Real-IP $remote_addr;", block)
            self.assertIn("add_header Referrer-Policy no-referrer always;", block)
            self.assertIn("add_header Cache-Control no-store always;", block)
            self.assertIn('proxy_set_header Referer "";', block)
        self.assertNotIn("default_server", active)

    def test_runbook_keeps_gates_and_no_start_commands(self):
        doc = source("docs/naver-engine-deployment.md")
        for gate in ("BE #805", "S16", "시작 전 거절", "14일", "NAVER_SCREEN_REQUIRE_BROWSER=1",
                     "NAVER_RELAY_REQUIRE_APP=1", "G1~G3", "복원", "444", "0건", "실측",
                     "SSO_AD_CENTER_CLIENT_KEY", "SSO_EXCHANGE_CLIENT_KEY", "SSO_NAVER_CONTROL_CLIENT_KEY",
                     "ENV_FILE", "수신부 먼저", "FE 마지막", "별도 폐기", "sso-bootstrap.js"):
            self.assertTrue(gate in doc, f"배포 게이트 문구 누락: {gate}")
        self.assertNotIn("현재 빌드에서 한국어 설정 오류로 거절", doc)
        command_lines = re.findall(r"(?m)^docker(?:-compose| compose) .+$", doc)
        self.assertTrue(command_lines)
        for line in command_lines:
            self.assertIn("--project-name ", line)
            self.assertIn("--file ", line)
            self.assertIn(" config ", line)
            self.assertIn("--quiet", line)
            self.assertNotRegex(line, r"\b(up|start|down|prune|build|exec|run)\b")

    def test_ci_only_test_branch_read_permission_and_explicit_isolation(self):
        workflow = source(".github/workflows/naver-runtime-tests.yml")
        prepare = workflow.split("id: prepare\n", 1)[1].split("- name: 외부망 없는", 1)[0]
        self.assertRegex(prepare, r"(?m)^\s+timeout-minutes: 8$")
        self.assertIn("branches: [codex/naver-runtime-20260930, codex/naver-shared-metrics-20260930, codex/naver-sso-20260930]", workflow)
        self.assertIn("github.ref == 'refs/heads/codex/naver-runtime-20260930'", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assert_ci_job_isolation(workflow)
        self.assertNotIn("self-hosted", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertIn("sudo unshare --net", workflow)
        self.assertIn("--reuid", workflow)
        self.assertIn("env -i", workflow)
        self.assertIn("--network none", workflow)
        self.assertIn("--user 10001:10001", workflow)
        self.assertIn("--read-only", workflow)
        self.assertNotRegex(workflow, r"docker\s+(?:push|system\s+prune|volume\s+prune)\b")

    def test_ci_guard_rejects_credentials_in_development_job_or_global_env(self):
        original = source('.github/workflows/naver-runtime-tests.yml')
        injected = '    env:\n      VALUE: ${{ secrets.NAVER_ENGINE_ERP_KEY }}\n'
        for changed in (original.replace('  linux-tests:\n', '  linux-tests:\n' + injected),
                        'env:\n  VALUE: ${{ secrets.NAVER_ENGINE_ERP_KEY }}\n' + original):
            with self.assertRaises(AssertionError):
                self.assert_ci_job_isolation(changed)

    def test_ci_guard_rejects_mixed_upload_and_recovery_keys(self):
        original = source('.github/workflows/naver-runtime-tests.yml')
        for job, secret in (('backup-transfer', 'NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM'),
                            ('backup-recovery', 'NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY')):
            changed = original.replace('  ' + job + ':\n', '  ' + job + ':\n'
                                       + '    env:\n      BAD: ${{ secrets.' + secret + ' }}\n')
            with self.assertRaises(AssertionError):
                self.assert_ci_job_isolation(changed)

    def test_ci_guard_rejects_widened_acceptance_branch_or_missing_environment(self):
        original = source('.github/workflows/naver-runtime-tests.yml')
        for changed in (original.replace("github.ref == 'refs/heads/codex/naver-backup-recovery-20261001'", 'true'),
                        original.replace('    environment: naver-backup-recovery\n', '')):
            with self.assertRaises(AssertionError):
                self.assert_ci_job_isolation(changed)

    def test_ci_guard_rejects_unconditional_business_key_during_restore(self):
        original = source('.github/workflows/naver-runtime-tests.yml')
        for name in ('SSO_AD_CENTER_CLIENT_KEY', 'SSO_NAVER_CONTROL_CLIENT_KEY',
                     'NAVER_ENGINE_ERP_KEY', 'NAVER_AUTO_TOKEN_SECRET'):
            changed = original.replace('  backup-recovery:\n', '  backup-recovery:\n'
                                       + '    env:\n      EXTRA: ${{ secrets.' + name + ' }}\n')
            with self.assertRaises(AssertionError):
                self.assert_ci_job_isolation(changed)


class ComposeAssertions:
    def assert_cpu_limit(self, engine):
        cpus = Decimal(str(engine["cpus"]))
        self.assertGreater(cpus, Decimal("0"))
        self.assertLessEqual(cpus, Decimal("0.5"))

    def assert_raw_environment(self, engine):
        if "env_file" in engine:
            self.assertEqual(1, len(engine["env_file"]))
            self.assertEqual("raw", engine["env_file"][0]["format"])
        else:
            # Compose runConfig는 JSON/YAML 직렬화 뒤 모든 $를 정확히 한 번 $$로 바꾼다.
            # --no-interpolate는 경로 기본값 해석도 끄므로 사용하지 않는다.
            # https://github.com/docker/compose/blob/v2.38.2/cmd/compose/config.go#L495-L499
            self.assertEqual(RAW_CANARY_VALUE.replace("$", "$$"),
                             engine.get("environment", {}).get(RAW_CANARY_NAME))

    def assert_no_created_host_path(self, mount):
        # false 생략은 Compose JSON 정규화다. 원본의 명시값은 별도 시험으로 필수 검사한다.
        self.assertIs(mount.get("bind", {}).get("create_host_path", False), False)

    def assert_expanded_flags_off(self, engine):
        for name, value in engine["environment"].items():
            if name.endswith("_ENABLED"):
                self.assertEqual("false", value, name)


class ComposeModelTest(ComposeAssertions, unittest.TestCase):
    def test_ad_sso_key_defaults_blank_and_reaches_base_and_relay_service(self):
        for files in (("docker-compose.yml",),
                      ("docker-compose.yml", "deploy/naver-engine-ad-api.override.yml")):
            with self.subTest(files=files):
                model = compose_model(*files, project="naver-package-review")
                self.assertTrue(model["services"]["ad-api"]["environment"].get("SSO_AD_CENTER_CLIENT_KEY") == "",
                                "광고센터 전용 키의 기본값은 빈 문자열이어야 합니다")
                synthetic_key = "a" * 64
                model = compose_model(*files, project="naver-package-review", ad_sso_key=synthetic_key)
                self.assertTrue(model["services"]["ad-api"]["environment"].get("SSO_AD_CENTER_CLIENT_KEY") == synthetic_key,
                                "광고센터 전용 합성 키가 컨테이너 환경으로 전달되어야 합니다")

    def test_resolved_raw_env_uses_exact_compose_output_escaping(self):
        # 최신 Compose가 --no-env-resolution을 지켜도 펼친 출력 경로를 실제 CLI로 시험한다.
        engine = compose_model("compose.naver-engine.yml", resolve_env=True)["services"]["naver-engine"]
        self.assertNotIn("env_file", engine)
        self.assert_raw_environment(engine)
        self.assert_expanded_flags_off(engine)

    def test_engine_is_single_nonroot_readonly_service_without_host_ports(self):
        model = compose_model("compose.naver-engine.yml")
        self.assertEqual("naver-engine", model["name"])
        self.assertEqual(["naver-engine"], list(model["services"]))
        engine = model["services"]["naver-engine"]
        self.assertEqual("10001:10001", engine["user"])
        self.assertTrue(engine["read_only"])
        self.assertEqual("no", engine["restart"])
        self.assertEqual(["ALL"], engine["cap_drop"])
        self.assertIn("no-new-privileges:true", engine["security_opt"])
        self.assertEqual(["python", "-m", "naver_runtime", "run"], engine["command"])
        for field in ("ports", "expose", "container_name", "privileged", "network_mode", "depends_on"):
            self.assertNotIn(field, engine)
        self.assert_raw_environment(engine)
        self.assertEqual(64, engine["pids_limit"])
        self.assert_cpu_limit(engine)

    def test_data_and_socket_directory_mounts_are_separate_from_code_and_ad_db(self):
        engine = compose_model("compose.naver-engine.yml")["services"]["naver-engine"]
        mounts = engine["volumes"]
        self.assertEqual({"/var/lib/naver-engine", "/run/naver-engine", "/var/backups/naver-engine"},
                         {mount["target"] for mount in mounts})
        for mount in mounts:
            self.assertEqual("bind", mount["type"])
            self.assert_no_created_host_path(mount)
            self.assertTrue(mount["source"].startswith(("/var/lib/metainc/", "/run/metainc/", "/var/backups/metainc/")))
            self.assertFalse(mount.get("read_only", False))
        self.assertEqual("/var/lib/naver-engine/engine.db", engine["environment"]["NAVER_ENGINE_DB"])
        self.assertEqual("/run/naver-engine/engine.sock", engine["environment"]["NAVER_ENGINE_SOCKET"])

    def test_relay_override_preserves_existing_ad_service_contract(self):
        before = compose_model("docker-compose.yml", project="naver-package-review")
        after = compose_model("docker-compose.yml", "deploy/naver-engine-ad-api.override.yml",
                              project="naver-package-review")
        old, new = before["services"]["ad-api"], after["services"]["ad-api"]
        self.assertEqual(before["services"].keys(), after["services"].keys())
        for field in ("ports", "user", "networks", "restart", "build", "healthcheck"):
            self.assertEqual(old.get(field), new.get(field), field)
        self.assertEqual("off", new["environment"]["NAVER_AUTO_WEB"])
        self.assertEqual("", new["environment"]["NAVER_AUTO_ENGINE"])
        for key, value in old["environment"].items():
            self.assertEqual(value, new["environment"][key], key)
        self.assertTrue(all(mount in new["volumes"] for mount in old["volumes"]))
        added = [mount for mount in new["volumes"] if mount not in old["volumes"]]
        self.assertEqual(1, len(added))
        self.assertEqual("/run/naver-engine", added[0]["target"])
        self.assertTrue(added[0]["read_only"])
        self.assertIn("10001", new["group_add"])

    def test_backup_override_only_adds_three_readonly_non_decryption_files(self):
        model = compose_model("compose.naver-engine.yml", "deploy/naver-engine-backup.override.yml")
        engine = model["services"]["naver-engine"]
        secrets = [mount for mount in engine["volumes"] if mount["target"].startswith("/run/secrets/")]
        self.assertEqual({"/run/secrets/naver-backup-recipient.pem", "/run/secrets/naver-backup-upload-key",
                          "/run/secrets/naver-backup-known-hosts"}, {mount["target"] for mount in secrets})
        for mount in secrets:
            self.assertTrue(mount["read_only"])
            self.assert_no_created_host_path(mount)
        self.assert_raw_environment(engine)
        self.assert_expanded_flags_off(engine)


class ComposeNormalizationTest(ComposeAssertions, unittest.TestCase):
    def test_linux_expanded_env_and_omitted_false_bind_match_contract(self):
        engine = {"environment": {RAW_CANARY_NAME: RAW_CANARY_VALUE.replace("$", "$$"),
                                  **{"NAVER_ENGINE_" + flag: "false" for flag in FLAGS}}}
        self.assert_raw_environment(engine)
        self.assert_expanded_flags_off(engine)
        self.assert_no_created_host_path({"type": "bind", "bind": {}})
        self.assert_no_created_host_path({"type": "bind"})
        for cpus in ("0.5", 0.5):
            self.assert_cpu_limit({"cpus": cpus})

    def test_normalization_never_hides_interpolation_enabled_flags_or_created_paths(self):
        for value in (None, RAW_CANARY_VALUE, RAW_CANARY_VALUE.replace("$", "$$$$"),
                      RAW_CANARY_VALUE.replace("${NAVER_PACKAGE_UNSET:-expanded}", "expanded").replace("$", "$$")):
            with self.assertRaises(AssertionError):
                self.assert_raw_environment({"environment": {RAW_CANARY_NAME: value}})
        with self.assertRaises(AssertionError):
            self.assert_expanded_flags_off({"environment": {"NAVER_ENGINE_BACKUP_ENABLED": "true"}})
        with self.assertRaises(AssertionError):
            self.assert_no_created_host_path({"bind": {"create_host_path": True}})
        for cpus in ("0", 0, "0.50000000000000001", 0.51):
            with self.assertRaises(AssertionError):
                self.assert_cpu_limit({"cpus": cpus})


if __name__ == "__main__":
    unittest.main()
