"""Synthetic adapter boundaries. No network, subprocess, production files."""
import copy
import importlib.util
import io
from pathlib import Path
import sys
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
ADAPTER = HERE / "qualification_adapter.py"
if not ADAPTER.is_file():
    ADAPTER = HERE.parent / "tools/naver_strategy_prepare_probe/qualification_adapter.py"
spec = importlib.util.spec_from_file_location("strategy_prepare_qualification_test", ADAPTER)
Q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(Q)


def fixture():
    paths = {k: "backend/tools/naver_strategy_prepare_probe/" + k + ".py"
             for k in Q.ROLES}
    paths["source_fixture"] = "backend/tools/naver_strategy_prepare_probe/fixture-manifest.closed.json"
    helpers = {str(i): "backend/tools/helper" + str(i) + ".py" for i in range(9)}
    buffers = {p: ("synthetic:" + p).encode() for p in
               set(paths.values()) | set(helpers.values()) | {Q.NATIVE_PATH, Q.DIAGNOSTIC_PATH}}
    files = {p: dict(bytes=len(b), sha256=Q.sha(b)) for p, b in buffers.items()}
    counts = {"suite-" + str(i) + "-tests.txt": 1 for i in range(31)}
    counts["suite-0-tests.txt"] = 1938
    counts["report-progress-tests.txt"] = 38
    script = "printf closed\n"
    sizes = dict(json=1, wire=1, bootstrap=1, ssh=len(script))
    registry = dict(
        schema="strategy-prepare-source-registration-v1", base_head=Q.BASE_HEAD,
        head_sha="a" * 40, repository=Q.REPOSITORY, branch=Q.BRANCH,
        limits=Q.LIMITS.copy(), source_files=files, author_roles=paths, helper9=helpers,
        native_workflow=dict(path=Q.NATIVE_PATH, sha256=files[Q.NATIVE_PATH]["sha256"],
                             user_steps=["Native", "Fixtures"], wrapper_steps=["Setup", "Complete"]),
        diagnostic_workflow=dict(path=Q.DIAGNOSTIC_PATH, sha256=files[Q.DIAGNOSTIC_PATH]["sha256"],
                                 user_steps=["Qualify"], wrapper_steps=["Setup", "Complete"]),
        base_native_counts=counts, native_test_ids=["test_synthetic"], linux_test_ids=["test_synthetic"],
        source_fixture=dict(source_commit="b" * 40, manifest_path=paths["source_fixture"],
                            manifest_sha256=files[paths["source_fixture"]]["sha256"],
                            equivalence_receipt_sha256="c" * 64, network_fetch=False),
        independent_source_review_sha256="d" * 64, independent_adapter_review_sha256="e" * 64,
        render=dict(script_sha256=Q.sha(script.encode()), sizes=sizes))
    return registry, buffers, script, sizes


def native(registry, buffers, mutate=None):
    manifest = Q.source_buffers(registry, buffers)
    result = dict(schema="strategy-prepare-native-synthetic-v1",
                  head_sha=registry["head_sha"], source_manifest_sha256=manifest,
                  tests=dict(run=1, failures=0, errors=0, skips=0),
                  test_ids=["test_synthetic"], linux_test_ids=["test_synthetic"],
                  checks={k: True for k in Q.CHECKS}, hosted_linux=True,
                  production_access=False, network_calls=0, mutations=0)
    members = {p: ("Ran " + str(n) + " tests in 0.001s\n\nOK\n").encode()
               for p, n in registry["base_native_counts"].items()}
    members["source-sha.txt"] = (registry["head_sha"] + "\n").encode()
    members["strategy-prepare-tests.closed.json"] = Q.canonical(result)
    if mutate:
        mutate(members)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        for path, body in members.items():
            z.writestr(path, body)
    packed = stream.getvalue()
    run = dict(id=123, head_sha=registry["head_sha"], head_branch=Q.BRANCH,
               path=Q.NATIVE_PATH, event="push", run_attempt=1, status="completed",
               conclusion="success", workflow_id=456,
               repository=dict(full_name=Q.REPOSITORY))
    job = dict(id=789, run_id=123, head_sha=registry["head_sha"], name="synthetic-export",
               run_attempt=1, status="completed", conclusion="success",
               steps=[dict(name=n, number=i + 1, status="completed", conclusion="success")
                      for i, n in enumerate(["Setup", "Native", "Fixtures", "Complete"])])
    item = dict(id=234, name="naver-strategy-prepare-native-123", expired=False,
                size_in_bytes=len(packed), digest="sha256:" + Q.sha(packed),
                workflow_run=dict(id=123, head_sha=registry["head_sha"], head_branch=Q.BRANCH))
    return run, dict(total_count=1, jobs=[job]), dict(total_count=1, artifacts=[item]), packed


class QualificationBoundaries(unittest.TestCase):
    def test_qualifier_same_run_native_and_linux(self):
        reg, bufs, _, _ = fixture()
        result = Q.verify(reg, bufs, *native(reg, bufs))
        self.assertEqual(result["total"], 2007)
        self.assertEqual(result["coverage"]["duplicate_fixture_runs"], 0)
        self.assertIs(result["coverage"]["same_run"], True)
        args = native(reg, bufs)
        self.assertEqual(Q.verify_metadata(reg, result, *args[:3]),
                         {"native_artifact_downloads": 0, "metadata_binding_verified": True})
        args[2]["artifacts"][0]["id"] += 1
        with self.assertRaises(Q.Refused):
            Q.verify_metadata(reg, result, *args[:3])

    def test_qualifier_pending_registration_refused(self):
        reg, _, _, _ = fixture()
        for key in ("head_sha", "native_test_ids", "independent_adapter_review_sha256", "render"):
            bad = copy.deepcopy(reg); bad[key] = None
            with self.subTest(key=key), self.assertRaises(Q.Refused):
                Q.registration(bad)

    def test_qualifier_boolean_integer_alias_refused(self):
        reg, bufs, _, _ = fixture()
        for mutate in (lambda r: r["source_files"][next(iter(bufs))].update(bytes=True),
                       lambda r: r["render"]["sizes"].update(json=True),
                       lambda r: r["base_native_counts"].update({"suite-1-tests.txt": True})):
            bad = copy.deepcopy(reg); mutate(bad)
            with self.assertRaises(Q.Refused):
                Q.registration(bad)

    def test_qualifier_duplicate_and_nonfinite_json_refused(self):
        for body in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.assertRaises(Q.Refused):
                Q.strict(body, 1024)

    def test_qualifier_empty_init_only(self):
        reg, bufs, _, _ = fixture()
        p = "backend/tests/fixtures/naver_strategy_prepare_source/backend/app/__init__.py"
        reg["source_files"][p] = dict(bytes=0, sha256=Q.sha(b"")); bufs[p] = b""
        Q.source_buffers(reg, bufs)
        bad = copy.deepcopy(reg)
        bad["source_files"]["backend/tools/empty.py"] = bad["source_files"].pop(p)
        with self.assertRaises(Q.Refused):
            Q.registration(bad)

    def test_qualifier_source_tamper_and_traversal_refused(self):
        reg, bufs, _, _ = fixture()
        bad = dict(bufs); bad[next(iter(bad))] += b"x"
        with self.assertRaises(Q.Refused):
            Q.source_buffers(reg, bad)
        for path in ("../x.py", "/x.py", "a//b.py", "a/./b.py"):
            self.assertFalse(Q.relative(path))

    def test_qualifier_old_head_branch_attempt_refused(self):
        reg, bufs, _, _ = fixture()
        for key, value in (("head_sha", Q.BASE_HEAD), ("head_branch", "old"),
                           ("run_attempt", 2), ("event", "workflow_dispatch")):
            args = native(reg, bufs)
            args[0][key] = value
            with self.subTest(key=key), self.assertRaises(Q.Refused):
                Q.verify(reg, bufs, *args)

    def test_qualifier_step_order_and_extra_refused(self):
        reg, bufs, _, _ = fixture()
        for mode in ("order", "extra"):
            args = native(reg, bufs); rows = args[1]["jobs"][0]["steps"]
            if mode == "order":
                rows[1]["name"], rows[2]["name"] = rows[2]["name"], rows[1]["name"]
            else:
                rows.append(dict(name="Other", number=5, status="completed", conclusion="success"))
            with self.assertRaises(Q.Refused):
                Q.verify(reg, bufs, *args)

    def test_qualifier_zip_member_set_and_digest_refused(self):
        reg, bufs, _, _ = fixture()
        args = native(reg, bufs, lambda m: m.update({"extra.txt": b"raw"}))
        with self.assertRaises(Q.Refused):
            Q.verify(reg, bufs, *args)
        args = native(reg, bufs); args[2]["artifacts"][0]["digest"] = "sha256:" + "f" * 64
        with self.assertRaises(Q.Refused):
            Q.verify(reg, bufs, *args)

    def test_qualifier_suite_skip_failure_and_old_count_refused(self):
        reg, bufs, _, _ = fixture()
        for text in (b"Ran 1 tests in 0s\nOK (skipped=1)\n",
                     b"Ran 1 tests in 0s\nFAILED (failures=1)\n",
                     b"Ran 2 tests in 0s\nOK\n"):
            args = native(reg, bufs, lambda m: m.update({"suite-1-tests.txt": text}))
            with self.assertRaises(Q.Refused):
                Q.verify(reg, bufs, *args)

    def test_qualifier_linux_uncovered_inventory_refused(self):
        reg, _, _, _ = fixture()
        reg["linux_test_ids"] = ["test_not_executed"]
        with self.assertRaises(Q.Refused):
            Q.registration(reg)

    def test_qualifier_arbitrary_script_refused(self):
        reg, bufs, script, sizes = fixture()
        observed = Q.verify(reg, bufs, *native(reg, bufs))
        qualified = Q.qualified_registry(reg, observed, "f" * 64)
        pin = Q.sha(Q.canonical(qualified))
        intent = dict(head_sha=reg["head_sha"], registry_sha256=pin,
                      exclusive=True, dispatch_count=0, retry_allowed=False)
        Q.permit_render(qualified, pin, reg["head_sha"], 1, intent, script, sizes)
        changed = "x" + script[1:]
        with self.assertRaises(Q.Refused):
            Q.permit_render(qualified, pin, reg["head_sha"], 1, intent, changed, sizes)

    def test_qualifier_repeat_and_fake_closed_receipt_refused(self):
        reg, bufs, script, sizes = fixture()
        observed = Q.verify(reg, bufs, *native(reg, bufs))
        qualified = Q.qualified_registry(reg, observed, "f" * 64)
        pin = Q.sha(Q.canonical(qualified))
        intent = dict(head_sha=reg["head_sha"], registry_sha256=pin,
                      exclusive=True, dispatch_count=1, retry_allowed=False)
        with self.assertRaises(Q.Refused):
            Q.permit_render(qualified, pin, reg["head_sha"], 1, intent, script, sizes)
        bad = copy.deepcopy(qualified); bad["native"]["synthetic"]["tests"]["run"] = True
        with self.assertRaises(Q.Refused):
            Q.permit_render(bad, Q.sha(Q.canonical(bad)), reg["head_sha"], 1,
                            intent, script, sizes)

    def test_qualifier_output_cap_preserved(self):
        reg, _, _, _ = fixture()
        reg["render"]["sizes"]["ssh"] = 49153
        with self.assertRaises(Q.Refused):
            Q.registration(reg)


if __name__ == "__main__":
    unittest.main()
