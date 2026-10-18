"""Read-only diagnosis: fake Docker only, no production access or raw output."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "tools" / "seo_readonly_diagnosis.py"
SPEC = importlib.util.spec_from_file_location("seo_readonly_diagnosis", SOURCE)
diagnosis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnosis)

CANARY = "SENSITIVE_CANARY_key_keyword_name_ip_url_request_id"
CONTAINER_ID = "a" * 64
IMAGE_ID = "sha256:" + "b" * 64
SOURCE_HASH = "c" * 64
INSPECT = {
    "container_id": CONTAINER_ID,
    "image_id": IMAGE_ID,
    "started_at": "2026-10-10T00:00:00.000000000Z",
    "restart_count": 2,
    "log_driver": "json-file",
    "rotation": {"max-size": "10m", "max-file": "3", CANARY: CANARY},
    "Env": ["CLAUDE_API_KEY=" + CANARY],
}
RUNTIME = {
    "key_configured": True,
    "model": "claude-sonnet-4-6",
    "model_state": "verified",
    "source_sha256": SOURCE_HASH,
    "read_state": "complete",
    "unapproved": CANARY,
}
LOGS = (
    "2026-10-17T14:59:00.123456789Z ERROR:seo_generate:[SEO생성] Claude 호출 오류: "
    "Error code: 400 - credit balance is too low " + CANARY + "\n"
    "2026-10-17T15:01:00Z INFO:seo_generate:[SEO생성] '" + CANARY
    + "' by " + CANARY + " (tokens in=99, out=23)\n"
    "2026-10-17T15:02:00Z WARNING:seo_generate:[SEO생성] JSON 파싱 실패: " + CANARY + "\n"
    "2026-10-17T15:03:00Z WARNING:seo_generate:[SEO생성] 네이버 컨텍스트 수집 실패(스킵): "
    + CANARY + "\n"
    "2026-10-17T15:04:00Z ERROR:seo_generate:[SEO생성] event=provider_error "
    "category=rate_limit status=429 " + CANARY + "\n"
)


class FakeDocker:
    def __init__(self, logs=LOGS):
        self.logs = logs
        self.calls = []

    def __call__(self, command, **limits):
        self.calls.append((command, limits))
        if command[1] == "inspect":
            value = json.dumps(INSPECT)
        elif command[1] == "exec":
            value = json.dumps(RUNTIME)
        elif command[1] == "logs":
            value = self.logs
        else:
            raise AssertionError("Only approved read-only Docker commands are permitted")
        return diagnosis.CommandResult(value.encode(), "complete", 0)


class ReadonlyDiagnosisTests(unittest.TestCase):
    def test_counts_only_and_no_business_success_claim_or_secret_output(self):
        fake = FakeDocker()
        result = diagnosis.diagnose(runner=fake, now="2026-10-18T00:00:00Z")
        self.assertEqual(result["state"], "complete")
        self.assertEqual(result["logs"]["events"]["provider_error"]["count"], 2)
        self.assertEqual(result["logs"]["events"]["provider_response_received"]["count"], 1)
        self.assertEqual(result["logs"]["events"]["json_parse_failed"]["count"], 1)
        self.assertEqual(result["logs"]["events"]["context_skipped"]["count"], 1)
        self.assertEqual(result["logs"]["errors_by_category"]["credit"]["count"], 1)
        self.assertEqual(result["logs"]["http_status_counts"], {"400": 1, "429": 1})
        self.assertEqual(result["business_generation_success"], "unverified")
        self.assertEqual(result["runtime"]["key_configured"], True)
        self.assertEqual(result["runtime"]["source_sha256"], SOURCE_HASH)
        self.assertEqual(result["container"]["rotation"], {"max_size": "10m", "max_file": 3})
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertNotIn("retained_first_is_incident_start", result)
        self.assertIn("retained_first_is_not_incident_start", result["limitations"])
        logs_command = next(command for command, _ in fake.calls if command[1] == "logs")
        self.assertEqual(logs_command, ["docker", "logs", "--timestamps", "--until", "2026-10-18T00:00:00Z", CONTAINER_ID])
        self.assertTrue(all(limits["max_bytes"] > 0 and limits["timeout"] > 0 for _, limits in fake.calls))
        probe = next(command for command, _ in fake.calls if command[1] == "exec")
        self.assertEqual(probe[:7], ["docker", "exec", CONTAINER_ID, "python3", "-I", "-B", "-c"])

    def test_seo_workflow_skips_every_legacy_diagnosis_and_uses_existing_ssh(self):
        workflow = SOURCE.parents[2] / ".github" / "workflows" / "debug-rank.yml"
        source = workflow.read_text()
        self.assertIn("seo_logs:", source)
        self.assertIn("if: ${{ github.event.inputs.seo_logs != 'on' }}", source)
        dedicated = source.split("  seo_diagnose:\n", 1)[1]
        self.assertIn("if: ${{ github.event.inputs.seo_logs == 'on' }}", dedicated)
        for secret in ("VPS_HOST", "VPS_USER", "VPS_SSH_KEY"):
            self.assertIn("secrets." + secret, dedicated)
        self.assertIn("backend/tools/seo_readonly_diagnosis.py", dedicated)
        self.assertIn("python3 -I -B -", dedicated)
        self.assertNotIn("/tmp", dedicated)
        self.assertNotIn("docker logs", dedicated)
        self.assertNotIn("use_branch_code", dedicated)

    def test_utc_and_kst_days_are_aggregated_separately_and_retention_is_not_onset(self):
        result = diagnosis.diagnose(runner=FakeDocker(), now="2026-10-18T00:00:00Z")
        errors = result["logs"]["events"]["provider_error"]
        self.assertEqual(errors["first_utc"], "2026-10-17T14:59:00Z")
        self.assertEqual(errors["first_kst"], "2026-10-17T23:59:00+09:00")
        self.assertEqual(errors["daily_utc"], {"2026-10-17": 2})
        self.assertEqual(errors["daily_kst"], {"2026-10-17": 1, "2026-10-18": 1})

    def test_log_timeout_failure_and_truncation_never_become_confirmed_zero_counts(self):
        for state, output in (("timeout", b""), ("read_failed", b""), ("byte_limit", LOGS.encode())):
            with self.subTest(state=state):
                fake = FakeDocker()
                def runner(command, **limits):
                    if command[1] == "logs":
                        return diagnosis.CommandResult(output, state, None)
                    return fake(command, **limits)
                result = diagnosis.diagnose(runner=runner, now="2026-10-18T00:00:00Z")
                self.assertEqual(result["state"], "partial")
                self.assertEqual(result["logs"]["read_state"], state)
                self.assertEqual(result["business_generation_success"], "unverified")
                count = result["logs"]["events"]["provider_error"]["count"]
                self.assertEqual(count, 2 if output else None)
                self.assertNotIn(CANARY, json.dumps(result))

    def test_inspect_failure_stops_without_probing_an_unverified_container(self):
        calls = []
        def runner(command, **limits):
            calls.append(command)
            raise OSError(CANARY)
        result = diagnosis.diagnose(runner=runner, now="2026-10-18T00:00:00Z")
        self.assertEqual(result["state"], "unverified")
        self.assertEqual(len(calls), 1)
        self.assertIsNone(result["logs"]["events"]["provider_error"]["count"])
        self.assertNotIn(CANARY, json.dumps(result))

    def test_container_restart_or_replacement_during_read_marks_partial(self):
        fake = FakeDocker()
        inspections = 0
        def runner(command, **limits):
            nonlocal inspections
            if command[1] == "inspect":
                inspections += 1
                if inspections == 2:
                    changed = dict(INSPECT, restart_count=3, container_id="d" * 64)
                    return diagnosis.CommandResult(json.dumps(changed).encode(), "complete", 0)
            return fake(command, **limits)
        result = diagnosis.diagnose(runner=runner, now="2026-10-18T00:00:00Z")
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["container_stable"], False)
        self.assertIn("container_changed_or_unverified", result["reasons"])
        for command, _ in fake.calls:
            if command[1] in ("exec", "logs"):
                self.assertIn(CONTAINER_ID, command)

    def test_unvalidated_model_driver_rotation_or_probe_fields_never_leak(self):
        fake = FakeDocker()
        def runner(command, **limits):
            if command[1] == "exec":
                value = dict(RUNTIME, model=CANARY, source_sha256=CANARY, key_configured=CANARY)
                return diagnosis.CommandResult(json.dumps(value).encode(), "complete", 0)
            if command[1] == "inspect":
                value = dict(INSPECT, log_driver=CANARY, rotation={"max-size": CANARY, "max-file": CANARY})
                return diagnosis.CommandResult(json.dumps(value).encode(), "complete", 0)
            return fake(command, **limits)
        result = diagnosis.diagnose(runner=runner, now="2026-10-18T00:00:00Z")
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["runtime"]["model"], "unverified")
        self.assertIsNone(result["runtime"]["key_configured"])
        self.assertIsNone(result["runtime"]["source_sha256"])
        self.assertNotIn(CANARY, json.dumps(result))

    def test_provider_category_allowlist_and_status_range(self):
        cases = (("Error code: 401 - invalid x-api-key", "auth", "401"),
                 ("Error code: 400 - credit balance is too low", "credit", "400"),
                 ("Error code: 429 - rate limit", "rate_limit", "429"),
                 ("Error code: 404 - model not found", "model_access", "404"),
                 ("Error code: 422 - invalid request", "request_invalid", "422"),
                 ("Error code: 503 - unavailable", "upstream", "503"),
                 ("APIConnectionError connection failed", "network", None),
                 ("status=999 " + CANARY, "unknown", None))
        for message, category, status in cases:
            with self.subTest(category=category):
                logs = "2026-10-17T15:00:00Z ERROR [SEO생성] Claude 호출 오류: " + message + "\n"
                result = diagnosis.diagnose(runner=FakeDocker(logs), now="2026-10-18T00:00:00Z")
                self.assertEqual(result["logs"]["errors_by_category"][category]["count"], 1)
                self.assertEqual(result["logs"]["http_status_counts"], {status: 1} if status else {})
                self.assertNotIn(CANARY, json.dumps(result))

    def test_probe_reads_only_source_and_env_no_application_import_or_writes(self):
        source = b'import os\nCLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")\nraise RuntimeError("NEVER_EXECUTE")\n'
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"CLAUDE_API_KEY": CANARY}, clear=True), \
             mock.patch("builtins.open", mock.mock_open(read_data=source)) as source_open, \
             contextlib.redirect_stdout(output):
            exec(compile(diagnosis.PROBE_CODE, "<isolated-readonly-probe>", "exec"), {})
        value = json.loads(output.getvalue())
        source_open.assert_called_once_with("/app/seo_generate.py", "rb")
        self.assertEqual(value["key_configured"], True)
        self.assertEqual(value["model"], "claude-sonnet-4-6")
        self.assertEqual(value["read_state"], "complete")
        self.assertNotIn(CANARY, output.getvalue())

    def test_subprocess_capture_is_bounded_and_times_out_without_printing(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            limited = diagnosis.run_command([sys.executable, "-I", "-B", "-c",
                                            "import os; os.write(1, b'x' * 100000); os.write(2, b'y' * 100000)"],
                                           timeout=3, max_bytes=100)
            timed = diagnosis.run_command([sys.executable, "-I", "-B", "-c", "import time; time.sleep(3)"],
                                         timeout=0.05, max_bytes=100)
        self.assertEqual(limited.state, "byte_limit")
        self.assertLessEqual(len(limited.output), 100)
        self.assertEqual(timed.state, "timeout")
        self.assertEqual(output.getvalue(), "")

    def test_main_never_prints_exception_details(self):
        output = io.StringIO()
        with mock.patch.object(diagnosis, "diagnose", side_effect=RuntimeError(CANARY)), \
             contextlib.redirect_stdout(output):
            diagnosis.main()
        result = json.loads(output.getvalue())
        self.assertEqual(result["state"], "unverified")
        self.assertNotIn(CANARY, output.getvalue())

    def test_realistic_malicious_canaries_in_every_read_stay_memory_only(self):
        canaries = ("sk-ant-test-private-canary-123456", "업체명민감표식", "검색키워드민감표식",
                    "203.0.113.51", "https://private.invalid/sensitive?token=private",
                    "req_sensitive_abcdef", "ExceptionBodyPrivateCanary")
        secret = " ".join(canaries)
        fake = FakeDocker(LOGS + "2026-10-17T15:05:00Z ERROR [SEO생성] Claude 호출 오류: " + secret + "\n")
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = diagnosis.diagnose(runner=fake, now="2026-10-18T00:00:00Z")
        serialized = json.dumps(result, ensure_ascii=False)
        for canary in canaries:
            self.assertNotIn(canary, serialized)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(result["logs"]["errors_by_category"]["unknown"]["count"], 1)

    def test_invalid_timestamp_or_future_log_is_partial_not_fabricated_time(self):
        logs = ("timestamp_unknown [SEO생성] Claude 호출 오류: " + CANARY + "\n"
                "2026-10-19T00:00:00Z ERROR [SEO생성] Claude 호출 오류: " + CANARY + "\n")
        result = diagnosis.diagnose(runner=FakeDocker(logs), now="2026-10-18T00:00:00Z")
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["logs"]["unparseable_or_outside_cutoff_lines"], 2)
        self.assertIsNone(result["logs"]["range"]["first_retained_utc"])
        self.assertNotIn(CANARY, json.dumps(result))

    def test_subprocess_stdout_and_stderr_do_not_splice_partial_log_lines(self):
        code = ("import os,time; os.write(1,b'first-'); time.sleep(0.02); "
                "os.write(2,b'error-line\\n'); time.sleep(0.02); os.write(1,b'done\\n')")
        result = diagnosis.run_command([sys.executable, "-I", "-B", "-c", code], timeout=3, max_bytes=100)
        self.assertEqual(result.state, "complete")
        self.assertEqual(sorted(result.output.splitlines()), [b"error-line", b"first-done"])


if __name__ == "__main__":
    unittest.main()
