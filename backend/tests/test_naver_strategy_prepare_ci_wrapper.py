"""Offline wrapper integration boundaries; public synthetic bytes only."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
TOOL = HERE
if not (TOOL / "ci_wrapper.py").is_file():
    TOOL = HERE.parent / "tools/naver_strategy_prepare_probe"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


W = load(TOOL / "ci_wrapper.py", "strategy_prepare_ci_wrapper_test")
S_PATH = HERE / "test_qualification_adapter.py"
if not S_PATH.is_file():
    S_PATH = HERE / "test_naver_strategy_prepare_qualification.py"
S = load(S_PATH, "strategy_prepare_ci_adapter_fixtures")
Q = S.Q
PREFIX = "backend/tests/fixtures/naver_strategy_prepare_source/"


class FakeAPI:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def run(self, run_id):
        self.calls.append(("run", run_id))
        return self.data[0]

    def jobs(self, run_id):
        self.calls.append(("jobs", run_id))
        return self.data[1]

    def artifacts(self, run_id):
        self.calls.append(("artifacts", run_id))
        return self.data[2]

    def artifact_zip(self, artifact_id):
        self.calls.append(("artifact_zip", artifact_id))
        return self.data[3]


class Old:
    def __init__(self, api=None):
        self.api = api
        self.outputs = []

    @contextlib.contextmanager
    def dependencies(self, root):
        yield {"fixed_actions_api": self.api}

    def output(self, path, script):
        self.outputs.append((path, script))


def env(head="a" * 40, event="push"):
    return {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": W.REPOSITORY,
        "GITHUB_REF": "refs/heads/" + W.BRANCH, "GITHUB_EVENT_NAME": event,
        "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": head, "GITHUB_RUN_ID": "901",
        "RUNNER_OS": "Linux", "RUNNER_ENVIRONMENT": "github-hosted",
    }


def repository(root):
    """A complete synthetic registration with sixty public fixture entries."""
    reg, bufs, _, _ = S.fixture()
    fixture = {("pkg/__init__.py" if i == 0 else "pkg/source_" + str(i) + ".py"):
               (b"" if i == 0 else ("VALUE = " + str(i) + "\n").encode())
               for i in range(60)}
    manifest = dict(source_commit=W.SOURCE, count=60, backup_included=False,
                    files={p: Q.sha(b) for p, b in fixture.items()})
    manifest_path = reg["source_fixture"]["manifest_path"]
    bufs[manifest_path] = Q.canonical(manifest)
    reg["source_fixture"].update(source_commit=W.SOURCE,
                                 manifest_sha256=Q.sha(bufs[manifest_path]))
    for p, b in fixture.items():
        bufs[PREFIX + p] = b
    adapter_bytes = (TOOL / "qualification_adapter.py").read_bytes()
    bufs[W.ADAPTER] = adapter_bytes
    test_path = "backend/tests/test_synthetic_wrapper_entry.py"
    bufs[test_path] = (b"import unittest\nclass Entry(unittest.TestCase):\n"
                       b"    def test_native_entry(self):\n        self.assertTrue(True)\n")
    reg["native_test_ids"] = ["test_native_entry"]
    reg["linux_test_ids"] = ["test_native_entry"]
    reg["source_files"] = {p: dict(bytes=len(b), sha256=Q.sha(b)) for p, b in bufs.items()}
    for p, b in bufs.items():
        path = root / p
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b)
    (root / W.TEMPLATE).write_bytes(Q.canonical({**reg, "head_sha": None}))
    return reg, bufs, test_path, Q.sha(adapter_bytes)


class WrapperBoundaries(unittest.TestCase):
    def test_wrapper_source_exact_pin(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(W, "ROOT", Path(folder).resolve()):
            path = Path(folder).resolve() / "public.py"
            path.write_bytes(b"public")
            self.assertEqual(W.read_public("public.py", W.sha(b"public")), b"public")
            with self.assertRaises(W.Refused):
                W.read_public("public.py", "a" * 64)

    def test_wrapper_source_paths_closed(self):
        for path in ("../x", "/x", "a//x", "a/./x", ".env", "a/HANDOVER.md", "store 2.py"):
            with self.subTest(path=path), self.assertRaises(W.Refused):
                W.read_public(path)

    def test_wrapper_symlink_and_hardlink_refused(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(W, "ROOT", Path(folder).resolve()):
            root = Path(folder).resolve()
            (root / "public.py").write_bytes(b"public")
            (root / "link.py").symlink_to(root / "public.py")
            with self.assertRaises(W.Refused):
                W.read_public("link.py")
            os.link(root / "public.py", root / "hard.py")
            with self.assertRaises(W.Refused):
                W.read_public("public.py")

    def test_wrapper_source_empty_and_size_boundaries(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(W, "ROOT", Path(folder).resolve()):
            path = Path(folder).resolve() / "public.py"
            path.write_bytes(b"")
            with self.assertRaises(W.Refused):
                W.read_public("public.py")
            self.assertEqual(W.read_public("public.py", allow_empty=True), b"")
            path.write_bytes(b"abcd")
            self.assertEqual(W.read_public("public.py", maximum=4), b"abcd")
            with self.assertRaises(W.Refused):
                W.read_public("public.py", maximum=3)

    def test_wrapper_registration_exact_fixture_and_dynamic_head(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(W, "ROOT", Path(folder).resolve()):
            reg, bufs, _, pin = repository(Path(folder).resolve())
            with mock.patch.object(W, "ADAPTER_SHA256", pin):
                actual, actual_bufs, manifest = W.source_registration(Q, reg["head_sha"])
            self.assertEqual(actual, reg)
            self.assertEqual(actual_bufs, bufs)
            self.assertEqual(manifest, Q.sha(Q.canonical(reg)))

    def test_wrapper_registration_extra_fixture_refused(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(W, "ROOT", Path(folder).resolve()):
            reg, _, _, pin = repository(Path(folder).resolve())
            (Path(folder).resolve() / PREFIX / "extra.py").write_bytes(b"EXTRA = True\n")
            with mock.patch.object(W, "ADAPTER_SHA256", pin), self.assertRaises(W.Refused):
                W.source_registration(Q, reg["head_sha"])

    def test_wrapper_template_fixed_head_and_self_hash_refused(self):
        for field in ("head", "self_hash"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder, mock.patch.object(W, "ROOT", Path(folder).resolve()):
                reg, _, _, pin = repository(Path(folder).resolve())
                template = {**reg, "head_sha": None}
                if field == "head":
                    template["head_sha"] = reg["head_sha"]
                else:
                    template["source_files"][W.TEMPLATE] = dict(bytes=1, sha256="a" * 64)
                (Path(folder).resolve() / W.TEMPLATE).write_bytes(Q.canonical(template))
                with mock.patch.object(W, "ADAPTER_SHA256", pin), self.assertRaises(W.Refused):
                    W.source_registration(Q, reg["head_sha"])

    def test_wrapper_unregistered_adapter_refused_before_import(self):
        with mock.patch.object(W, "ADAPTER_SHA256", None), mock.patch.object(W, "module") as imported:
            with self.assertRaises(W.Refused):
                W.dependencies()
            imported.assert_not_called()

    def test_wrapper_ci_context_attempt_and_identity_refused(self):
        for key, value in (("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_REPOSITORY", "other/repo"),
                           ("GITHUB_SHA", "bad"), ("GITHUB_RUN_ID", "01"),
                           ("GITHUB_EVENT_NAME", "workflow_dispatch")):
            bad = env(); bad[key] = value
            with self.subTest(key=key), mock.patch.dict(os.environ, bad, clear=True), self.assertRaises(W.Refused):
                W.context("push")

    def test_wrapper_native_metadata_three_reads_zero_zip(self):
        reg, bufs, _, _ = S.fixture()
        data = S.native(reg, bufs)
        receipt = Q.verify(reg, bufs, *data)
        api = FakeAPI(data)
        self.assertEqual(W.native_metadata(Q, reg, api, 123, receipt), data[:3])
        self.assertEqual(api.calls, [("run", 123), ("jobs", 123), ("artifacts", 123)])

    def test_wrapper_native_metadata_size_and_workflow_rebound(self):
        reg, bufs, _, _ = S.fixture()
        data = S.native(reg, bufs)
        receipt = Q.verify(reg, bufs, *data)
        for change in ("size", "workflow"):
            altered = copy.deepcopy(data)
            if change == "size":
                altered[2]["artifacts"][0]["size_in_bytes"] += 1
            else:
                altered[0]["workflow_id"] += 1
            api = FakeAPI(altered)
            with self.subTest(change=change), self.assertRaises(Q.Refused):
                W.native_metadata(Q, reg, api, 123, receipt)
            self.assertNotIn("artifact_zip", [c[0] for c in api.calls])

    def test_wrapper_closed_output_is_exclusive_and_private(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder).resolve() / "result.closed.json"
            self.assertEqual(W.write_closed(output, {"ok": True}), W.sha(b'{"ok":true}'))
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                W.write_closed(output, {"ok": False})
            self.assertEqual(output.read_bytes(), b'{"ok":true}')

    def qualification_case(self, folder):
        reg, bufs, _, _ = S.fixture()
        data = S.native(reg, bufs)
        api, old = FakeAPI(data), Old()
        old.api = api
        args = types.SimpleNamespace(head=reg["head_sha"], native_run_id=123,
                                     source_registry_sha256=Q.sha(Q.canonical(reg)),
                                     intent_dir=str(Path(folder).resolve()), output=str(Path(folder).resolve() / "native.closed.json"))
        patches = contextlib.ExitStack()
        patches.enter_context(mock.patch.dict(os.environ, {}, clear=True))
        patches.enter_context(mock.patch.object(W, "dependencies", return_value=(Q, old)))
        patches.enter_context(mock.patch.object(W, "source_registration", return_value=(reg, bufs, args.source_registry_sha256)))
        git = patches.enter_context(mock.patch.object(W.subprocess, "run", return_value=types.SimpleNamespace(
            returncode=0, stdout=(args.head + "\n").encode())))
        return args, api, patches, git

    def test_wrapper_local_qualification_downloads_once_to_ram(self):
        with tempfile.TemporaryDirectory() as folder:
            args, api, patches, git = self.qualification_case(folder)
            with patches:
                result = W.qualify_native(args)
                with self.assertRaises(FileExistsError):
                    W.qualify_native(args)
            self.assertEqual(api.calls.count(("artifact_zip", 234)), 1)
            self.assertFalse(result["raw_artifact_saved"])
            files = list(Path(folder).resolve().iterdir())
            self.assertEqual(len(files), 2)
            self.assertTrue(all(p.name.endswith(".closed.json") for p in files))
            self.assertEqual(git.call_args.kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")
            self.assertNotIn("packed", json.loads(Path(args.output).read_bytes()))

    def test_wrapper_failed_qualification_retains_exclusive_intent(self):
        with tempfile.TemporaryDirectory() as folder:
            args, api, patches, _ = self.qualification_case(folder)
            api.data = (*api.data[:3], b"invalid synthetic zip")
            with patches:
                with self.assertRaises(Q.Refused):
                    W.qualify_native(args)
                with self.assertRaises(FileExistsError):
                    W.qualify_native(args)
            self.assertEqual(api.calls.count(("artifact_zip", 234)), 1)
            self.assertEqual(len(list(Path(folder).resolve().iterdir())), 1)
            self.assertFalse(Path(args.output).exists())

    def test_wrapper_wrong_local_head_refused_before_api(self):
        with tempfile.TemporaryDirectory() as folder:
            args, api, patches, git = self.qualification_case(folder)
            git.return_value.stdout = b"wrong\n"
            with patches, self.assertRaises(W.Refused):
                W.qualify_native(args)
            self.assertEqual(api.calls, [])
            self.assertEqual(list(Path(folder).resolve().iterdir()), [])

    def observation_case(self):
        reg, bufs, script, sizes = S.fixture()
        data = S.native(reg, bufs)
        receipt = Q.verify(reg, bufs, *data)
        qualified = Q.qualified_registry(reg, receipt, "f" * 64)
        raw = Q.canonical(qualified)
        values = env(event="workflow_dispatch")
        values.update(PROBE_CONFIRM=W.CONFIRM, PROBE_REGISTRY_SHA256=Q.sha(raw),
                      PROBE_QUALIFIED_REGISTRY=raw.decode(), GITHUB_OUTPUT="synthetic-output")
        api, old = FakeAPI(data), Old()
        old.api = api
        patches = contextlib.ExitStack()
        patches.enter_context(mock.patch.dict(os.environ, values, clear=True))
        patches.enter_context(mock.patch.object(W, "dependencies", return_value=(Q, old)))
        patches.enter_context(mock.patch.object(W, "source_registration",
                                                return_value=(reg, bufs, Q.sha(Q.canonical(reg)))))
        patches.enter_context(mock.patch.object(W, "module", return_value=types.SimpleNamespace(
            render=lambda: (script, {k + "_bytes": v for k, v in sizes.items()}))))
        return patches, api, old, script

    def test_wrapper_observe_metadata_only_and_exact_render(self):
        patches, api, old, script = self.observation_case()
        with patches:
            result = W.observe_build(types.SimpleNamespace())
        self.assertEqual(api.calls, [("run", 123), ("jobs", 123), ("artifacts", 123)])
        self.assertEqual(old.outputs, [("synthetic-output", script)])
        self.assertEqual(result["artifact_downloads"], 0)
        self.assertFalse(result["ssh_executed_by_wrapper"])

    def test_wrapper_observe_bad_registry_refused_before_metadata(self):
        patches, api, old, _ = self.observation_case()
        with patches, mock.patch.dict(os.environ, {"PROBE_REGISTRY_SHA256": "1" * 64}):
            with self.assertRaises(W.Refused):
                W.observe_build(types.SimpleNamespace())
        self.assertEqual(api.calls, [])
        self.assertEqual(old.outputs, [])

    def test_wrapper_observe_changed_render_refused_before_metadata(self):
        patches, api, old, script = self.observation_case()
        with patches, mock.patch.object(W, "module", return_value=types.SimpleNamespace(
                render=lambda: (script + "x", dict(json_bytes=1, wire_bytes=1,
                                                  bootstrap_bytes=1, ssh_bytes=len(script) + 1)))):
            with self.assertRaises(Q.Refused):
                W.observe_build(types.SimpleNamespace())
        self.assertEqual(api.calls, [])
        self.assertEqual(old.outputs, [])

    def test_wrapper_failure_does_not_emit_exception_text(self):
        output = io.StringIO()
        with mock.patch.object(W, "observe_build", side_effect=RuntimeError("synthetic private sentinel")), contextlib.redirect_stdout(output):
            code = W.main(["observe-build"])
        self.assertEqual(code, 1)
        self.assertNotIn("sentinel", output.getvalue())
        value = json.loads(output.getvalue().split("=", 1)[1])
        self.assertEqual(value, dict(ok=False, stage="observe-build", error_code="CLOSED_WRAPPER_REFUSAL"))

    def test_wrapper_native_sanitized_workflow_env_and_repository_entry(self):
        workflow = HERE / "naver-strategy-prepare-native.yml.draft"
        if not workflow.is_file():
            workflow = HERE.parents[1] / ".github/workflows/naver-strategy-prepare-native.yml"
        section = workflow.read_text().split("      - name: 새 strategy prepare 읽기 진단", 1)[1]
        section = section.split("python3 -I -B", 1)[0]
        forwarded = set(re.findall(r'"((?:GITHUB|RUNNER)_[A-Z_]+)=\$', section))
        expected = set(env()) | {"RUNNER_TEMP"}
        self.assertEqual(forwarded, expected)
        self.assertIn("env -i", section)
        self.assertIn("unshare --net", section)
        self.assertNotIn("TOKEN", section)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(W, "ROOT", Path(folder).resolve()):
            root = Path(folder).resolve()
            reg, _, test_path, pin = repository(root)
            runner = root / "runner"; base = runner / "product-tests"; base.mkdir(parents=True)
            (base / "source-sha.txt").write_text(reg["head_sha"] + "\n")
            values = env(); values["RUNNER_TEMP"] = str(runner)
            args = types.SimpleNamespace(head_file=str(base / "source-sha.txt"),
                                         output=str(base / "strategy-prepare-tests.closed.json"))
            with mock.patch.dict(os.environ, values, clear=True), \
                 mock.patch.object(W, "ADAPTER_SHA256", pin), \
                 mock.patch.object(W, "dependencies", return_value=(Q, Old())), \
                 mock.patch.object(W, "TEST_MODULES", (test_path,)), \
                 mock.patch.object(W.platform, "system", return_value="Linux"), \
                 mock.patch.object(W.sys, "addaudithook") as audit:
                result = W.native_fixtures(args)
            audit.assert_called_once_with(W.no_network_or_process)
            self.assertEqual(result["tests"], dict(run=1, failures=0, errors=0, skips=0))
            receipt = Q.strict(Path(args.output).read_bytes(), 32768)
            self.assertEqual(receipt["source_manifest_sha256"], Q.sha(Q.canonical(reg)))
            self.assertTrue(all(receipt["checks"].values()))

    def test_wrapper_fixture_audit_denies_network_and_process(self):
        for event in ("socket.connect", "socket.__new__", "subprocess.Popen", "os.system",
                      "os.exec", "os.posix_spawn", "os.fork"):
            with self.subTest(event=event), self.assertRaises(W.Refused):
                W.no_network_or_process(event, ())
        W.no_network_or_process("open", ())


if __name__ == "__main__":
    unittest.main()
