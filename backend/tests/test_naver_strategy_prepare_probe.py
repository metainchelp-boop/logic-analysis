"""New synthetic boundaries only. No operating DB, host, network or provider."""
import ast
import base64
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import lzma
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

TEST_FOLDER = Path(__file__).resolve().parent
IN_REPOSITORY = TEST_FOLDER.name == "tests" and TEST_FOLDER.parent.name == "backend"
ROOT = TEST_FOLDER.parents[1] if IN_REPOSITORY else TEST_FOLDER.parents[3]
TOOLS = ROOT / "backend/tools" if IN_REPOSITORY else ROOT / "work/naver-claude-reference-ops-20261011/backend/tools"
DRAFT = TOOLS / "naver_strategy_prepare_probe" if IN_REPOSITORY else TEST_FOLDER
PRODUCT = TEST_FOLDER / "fixtures/naver_strategy_prepare_source" if IN_REPOSITORY else ROOT / "work/naver-claude-reference-product-20261011"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load("fixed_probe_reader_tests", DRAFT / "reader.py")
C = load("fixed_probe_controller_tests", DRAFT / "controller.py")
T = load("fixed_probe_transport_tests", DRAFT / "transport.py")
W = load("fixed_probe_render_tests", DRAFT / "render_wrapper.py")
PROFILE = json.loads((DRAFT / "profile.closed.json").read_bytes())
SENTINEL = "SYNTHETIC_VALUE_NEVER_EXPORT"
NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


class Refused(Exception):
    pass


class Jobs:
    LIMIT = 100
    ACTIVE = {"queued", "running"}

    @staticmethod
    def identity(*values):
        return tuple(values)


class FakeReader:
    def __init__(self, outcome=None, rows=None):
        self.calls = []
        self.scans = 0
        self.outcome = outcome
        self.rows = rows or []

    def prepare_learning_strategy(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.outcome is not None:
            raise self.outcome
        return {"unexported_body": SENTINEL}

    def learning_strategy_jobs(self):
        self.scans += 1
        return self.rows


def probe(reader):
    return R.probe_once(reader, types.SimpleNamespace(StoreRefused=Refused), Jobs,
                        PROFILE, NOW, time.monotonic()+5)


def function_text(path, name):
    text = path.read_text()
    item = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(text, item)


def success():
    return dict(outcome="prepare-passed", prepare_calls=1, phase="metadata",
                prepare_site=None, leaf_site=None, error_kind=None,
                global_active_count=0, retry_identity_equal=False)


class ReadonlyBoundary(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = (Path(self.folder.name)/"synthetic.sqlite3").resolve()
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('fixture')")
        connection.commit()
        connection.close()
        self.before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.reader = R.connect_reader(self.path)

    def tearDown(self):
        self.reader.close()
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.before)
        self.folder.cleanup()

    def test_sqlite_row_names_and_snapshot(self):
        self.reader.execute("BEGIN")
        self.assertEqual(self.reader.execute("SELECT value FROM sample").fetchone()["value"], "fixture")
        self.assertTrue(self.reader.in_transaction)
        self.reader.execute("ROLLBACK")
        self.assertEqual(self.reader.total_changes, 0)

    def test_sqlite_dml_ddl_attach_denied(self):
        for sql in ("INSERT INTO sample VALUES ('x')", "UPDATE sample SET value='x'",
                    "DELETE FROM sample", "CREATE TABLE extra (x)", "DROP TABLE sample",
                    "ATTACH DATABASE ':memory:' AS extra", "PRAGMA writable_schema=ON",
                    "PRAGMA query_only=OFF", "PRAGMA journal_mode=WAL"):
            with self.subTest(sql_kind=sql.split()[0]):
                with self.assertRaises(sqlite3.DatabaseError):
                    self.reader.execute(sql)
        self.assertEqual(self.reader.total_changes, 0)

    def test_sqlite_dangerous_function_authorizer(self):
        for name in ("load_extension", "readfile", "writefile", "shell", "eval", "fts3_tokenizer"):
            self.assertEqual(R.readonly_authorizer(sqlite3.SQLITE_FUNCTION, None, name, None, None), sqlite3.SQLITE_DENY)

    def test_symlink_database_denied(self):
        link = self.path.with_name("alias.sqlite3")
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            R.connect_reader(link)

    def test_original_store_prepare_reads_synthetic_database(self):
        # This is the actual hash-pinned Store class and method, not a mock.
        # The public source was independently proven unchanged from current382f.
        store_path = PRODUCT/"naver_engine/store.py"
        self.assertEqual(hashlib.sha256(store_path.read_bytes()).hexdigest(), PROFILE["code_pins"]["naver_engine/store.py"])
        sys.path[:0] = [str(PRODUCT), str(PRODUCT/"backend")]
        try:
            from naver_engine import store as S
            from naver_runtime import learning_jobs as J
            self.reader.close()
            fixture = sqlite3.connect(self.path)
            fixture.execute("CREATE TABLE naver_auto_report_snapshot (report_id INTEGER, possibility_id INTEGER, period_key TEXT, revision_fingerprint TEXT, payload_json TEXT)")
            request = PROFILE["request"]
            fixture.execute("INSERT INTO naver_auto_report_snapshot VALUES (?,?,?,?,?)",
                            (request["report_id"], 1, "weekly:2026-10-05:2026-10-11", request["revision_fingerprint"], "{}"))
            fixture.commit()
            fixture.close()
            self.before = hashlib.sha256(self.path.read_bytes()).hexdigest()
            self.reader = R.connect_reader(self.path)
            original = S.Store(self.reader, str(self.path), None, writer=False)
            self.assertIs(original.writer, False)
            self.reader.execute("BEGIN")
            # Real prepare/_report_notes_scope/report_notes._scope reaches the
            # original StoreRefused for intentionally invalid synthetic payload.
            with mock.patch.object(R, "ROOT", PRODUCT):
                result = R.probe_once(original, S, J, PROFILE, NOW, time.monotonic()+5)
            self.assertEqual(result["error_kind"], "store-refused")
            self.assertEqual(result["outcome"], "prepare-failed")
            self.assertEqual(result["prepare_site"], PROFILE["prepare_sites"]["3792"])
            expected = next(code for path, fn, line, code in PROFILE["trace_sites"]
                            if path == "naver_engine/report_notes.py" and fn == "_scope" and line == 103)
            self.assertEqual(result["leaf_site"], expected)
            self.assertEqual(self.reader.total_changes, 0)
            self.assertTrue(self.reader.in_transaction)
            self.reader.execute("ROLLBACK")
        finally:
            del sys.path[:2]


class ProbeBoundary(unittest.TestCase):
    def test_exact_one_prepare_actual_request_and_no_body(self):
        fake = FakeReader()
        result = probe(fake)
        q = PROFILE["request"]
        self.assertEqual(fake.calls, [((q["report_id"], q["account_key"], q["revision_fingerprint"], 0, NOW, 0), {"narrowed": False})])
        self.assertEqual(fake.scans, 1)
        self.assertEqual(result, success())
        self.assertNotIn(SENTINEL, json.dumps(result))

    def test_refusal_does_not_scan_jobs(self):
        fake = FakeReader(Refused(SENTINEL))
        result = probe(fake)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.scans, 0)
        self.assertEqual(result["error_kind"], "store-refused")
        self.assertNotIn(SENTINEL, json.dumps(R.validate_result(result, PROFILE)))

    def test_global_active_count_and_retry_identity(self):
        q = PROFILE["request"]
        target = dict(job_id=q["retry_job_id"], actor=0, narrowed=False, report_id=q["report_id"],
                      account_key=q["account_key"], revision_fingerprint=q["revision_fingerprint"], expected_version=0, state="failed")
        fake = FakeReader(rows=[target, {"job_id": "synthetic-other", "state": "running"},
                                {"job_id": "synthetic-queued", "state": "queued"}])
        result = probe(fake)
        self.assertEqual(result["global_active_count"], 2)
        self.assertTrue(result["retry_identity_equal"])
        self.assertNotIn(q["retry_job_id"], json.dumps(result))

    def test_retry_mismatch_false(self):
        q = PROFILE["request"]
        row = dict(job_id=q["retry_job_id"], actor=1, narrowed=False, report_id=q["report_id"],
                   account_key=q["account_key"], revision_fingerprint=q["revision_fingerprint"], expected_version=0, state="failed")
        self.assertFalse(probe(FakeReader(rows=[row]))["retry_identity_equal"])

    def test_duplicate_retry_identity_refused(self):
        q = PROFILE["request"]
        fake = FakeReader(rows=[{"job_id": q["retry_job_id"]}]*2)
        self.assertEqual(probe(fake)["outcome"], "metadata-failed")

    def test_job_overflow_refused(self):
        self.assertEqual(probe(FakeReader(rows=[{}]*101))["outcome"], "metadata-failed")

    def test_deadline_before_prepare_zero_calls(self):
        fake = FakeReader()
        with self.assertRaises(ValueError):
            R.probe_once(fake, types.SimpleNamespace(StoreRefused=Refused), Jobs, PROFILE, NOW, 0)
        self.assertEqual(fake.calls, [])

    def test_deadline_after_prepare_no_scan(self):
        fake = FakeReader()
        with mock.patch.object(R, "check_deadline", side_effect=[None, ValueError("SOURCE_DIAGNOSTICS_DEADLINE")]):
            with self.assertRaises(ValueError):
                probe(fake)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.scans, 0)

    def test_known_prepare_and_leaf_enum_without_values(self):
        line = 3790
        space = {"Refused": Refused}
        source = "\n"*(line-2)+"def prepare_learning_strategy():\n raise Refused('"+SENTINEL+"')\n"
        exec(compile(source, str(R.ROOT/"naver_engine/store.py"), "exec"), space)
        try:
            space["prepare_learning_strategy"]()
        except Refused as error:
            caller, leaf = R.exception_sites(error, PROFILE)
        self.assertEqual(caller, PROFILE["prepare_sites"][str(line)])
        self.assertEqual(leaf, next(code for path, fn, n, code in PROFILE["trace_sites"]
                                   if path == "naver_engine/store.py" and fn == "prepare_learning_strategy" and n == line))
        self.assertNotIn(SENTINEL, caller+leaf)

    def test_unknown_leaf_not_promoted_to_known_caller(self):
        def unknown():
            raise Refused(SENTINEL)
        space = {"unknown": unknown}
        line = 3790
        exec(compile("\n"*(line-2)+"def prepare_learning_strategy():\n unknown()\n",
                     str(R.ROOT/"naver_engine/store.py"), "exec"), space)
        try:
            space["prepare_learning_strategy"]()
        except Refused as error:
            caller, leaf = R.exception_sites(error, PROFILE)
        self.assertEqual(caller, PROFILE["prepare_sites"][str(line)])
        self.assertEqual(leaf, "UNREGISTERED")

    def test_output_extra_raw_fields_rejected(self):
        with self.assertRaises(R.ProbeRefused):
            R.validate_result({**success(), "raw": SENTINEL}, PROFILE)

    def test_output_boolean_numeric_aliases_rejected(self):
        for key, value in (("prepare_calls", True), ("prepare_calls", 1.0),
                           ("global_active_count", False), ("global_active_count", 0.0),
                           ("retry_identity_equal", 0)):
            with self.subTest(field=key):
                with self.assertRaises(R.ProbeRefused):
                    R.validate_result({**success(), key: value}, PROFILE)

    def test_output_unknown_or_unhashable_enum_rejected(self):
        for value in (SENTINEL, [], {}):
            with self.assertRaises(R.ProbeRefused):
                R.validate_result({**success(), "outcome": value}, PROFILE)

    def test_profile_tamper_rejected_before_identity_or_database(self):
        result = R.run_probe({**PROFILE, "actor": 1})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "PROFILE")
        self.assertIs(result["database_opened"], False)

    def test_network_process_audit_closed(self):
        for event in ("socket.connect", "socket.__new__", "subprocess.Popen", "os.system", "os.fork"):
            with self.assertRaises(R.ProbeRefused):
                R.audit_boundary(event, (SENTINEL,))
        R.audit_boundary("import", ())

    def test_runtime_subset_excludes_only_six_nonimage_files(self):
        pins = R.runtime_pins(PROFILE)
        self.assertEqual(len(pins), 109)
        self.assertEqual(set(PROFILE["code_pins"]) - set(pins), R.RUNTIME_EXCLUDED)
        self.assertIn("naver_engine/backup.py", pins)

    def test_runtime_subset_unregistered_member_refused(self):
        changed = dict(PROFILE["code_pins"])
        changed["deploy/unregistered.py"] = changed.pop(next(iter(R.RUNTIME_EXCLUDED)))
        with self.assertRaises(R.ProbeRefused):
            R.runtime_pins({**PROFILE, "code_pins": changed})

    def test_runtime_pins_missing_file_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(R, "ROOT", Path(folder).resolve()):
                with self.assertRaises(R.ProbeRefused):
                    R.pin_sources(PROFILE)


class TransportBoundary(unittest.TestCase):
    def test_original_host_guard_and_codec_functions_preserved(self):
        original = TOOLS/"naver_current_inspection_b00_reason.py"
        self.assertEqual(function_text(DRAFT/"controller.py", "run"), function_text(original, "run"))
        original_transport = TOOLS/"naver_current_inspection_b00_reason_transport.py"
        for name in ("require_pins", "unique", "validate_package", "validate_dispatch_inputs",
                     "validate", "encode", "decode", "compact", "bundle", "failure", "execute"):
            self.assertEqual(function_text(DRAFT/"transport.py", name), function_text(original_transport, name))

    def test_reader_embedding_and_script_no_entrypoint_run(self):
        self.assertEqual(C.READER_SOURCE, (DRAFT/"reader.py").read_text())
        self.assertEqual(hashlib.sha256(C.READER_SOURCE.encode()).hexdigest(), C.READER_SHA256)
        source = C.script()
        compile(source, "<synthetic-compile-only>", "exec")
        self.assertLessEqual(len(source), 98304)
        self.assertNotIn(b"create_learning_strategy", source)
        self.assertNotIn(b"_submit_learning_strategy", source)

    def test_old_package_refused_before_host(self):
        class NoHost:
            def baseline(self):
                raise AssertionError("host must not be called")
        with self.assertRaises(ValueError):
            C.run({**T.PACKAGE, "source_commit": "b00d6bf805b43b282c04dd95970ae9ccb7d8247d"}, NoHost(), None)

    def test_render_caps_roundtrip_and_transport_hash(self):
        command, meta = W.render()
        self.assertLessEqual(meta["json_bytes"], 196608)
        self.assertLessEqual(meta["wire_bytes"], 65536)
        self.assertLessEqual(meta["bootstrap_bytes"], 32768)
        self.assertLessEqual(meta["ssh_bytes"], 49152)
        self.assertFalse(meta["remote_execution"])
        self.assertEqual(meta["transport_sha256"], hashlib.sha256((DRAFT/"transport.py").read_bytes()).hexdigest())
        self.assertIn("sys.exit(0 if result.get('ok') else 1)", command)
        tree = ast.parse(command.split("<<'PYCODE'\n", 1)[1].rsplit("\nPYCODE\n", 1)[0])
        values = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ("wire", "source"):
                values[node.targets[0].id] = ast.literal_eval(node.value)
        bundle = T.decode(values["wire"])
        self.assertEqual(bundle["package"], T.PACKAGE)
        self.assertEqual(base64.b64decode(values["source"]), W.bootstrap_source((DRAFT/"transport.py").read_bytes()))
        namespace = {}
        exec(compile(base64.b64decode(values["source"]), "<synthetic-bootstrap-definitions>", "exec"), namespace)
        self.assertEqual(namespace["decode"](values["wire"]), bundle)

    def test_codec_bad_wire_and_trailing_data_refused(self):
        for wire in ("", T.PREFIX+"!", T.PREFIX+"a"*65536,
                     T.PREFIX+base64.b64encode(lzma.compress(b"{}")+b"trailing").decode()):
            with self.assertRaises(ValueError):
                T.decode(wire)

    def test_bootstrap_failure_exits_nonzero_without_host_execution(self):
        command, _ = W.render()
        source = command.split("<<'PYCODE'\n", 1)[1].rsplit("\nPYCODE\n", 1)[0]
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "source":
                node.value = ast.Constant("!")
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            with self.assertRaises(SystemExit) as stopped:
                exec(compile(ast.fix_missing_locations(tree), "<synthetic-refused-bootstrap>", "exec"), {})
        self.assertEqual(stopped.exception.code, 1)
        text = stream.getvalue()
        self.assertTrue(text.startswith(W.MARKER))
        value = json.loads(text[len(W.MARKER):])
        self.assertFalse(value["ok"])
        self.assertEqual(value["error_code"], "SOURCE_DIAGNOSTICS_BOOTSTRAP_REFUSED")

    def test_codec_duplicate_and_source_tamper_refused(self):
        raw = b'{"version":1,"version":1}'
        wire = T.PREFIX+base64.b64encode(lzma.compress(raw)).decode()
        with self.assertRaises(ValueError):
            T.decode(wire)
        with self.assertRaises(ValueError):
            T.validate(dict(version=1, operation=T.OPERATION, package=T.PACKAGE,
                            sources={name: SENTINEL for name in T.SOURCE_FILES}))

    def test_closed_transport_result_and_failure_projection(self):
        result = dict(ok=True, mode=T.MODE, source_commit=T.SOURCE, mutations=0,
                      collection_completion_verified=False, reader_mode="sqlite-mode-ro-query-only-authorizer",
                      database_opened_by_controller=False, existing_app_baseline_unchanged=True,
                      diagnostics=success())
        self.assertEqual(T.project_result(result, C), result)
        with self.assertRaises(ValueError):
            T.project_result({**result, "raw": SENTINEL}, C)
        failure = T.failure(ValueError(SENTINEL))
        self.assertEqual(failure["error_code"], "UNRECOGNIZED")
        self.assertNotIn(SENTINEL, json.dumps(failure))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TestResult()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        suite.run(result)
    print(json.dumps(dict(run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                          skipped=len(result.skipped),
                          failed_ids=[test.id().rsplit(".", 1)[-1] for test, _ in (*result.failures, *result.errors)]),
                     sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() else 1)
