"""Draft pure qualification adapter; no API, SSH, subprocess or filesystem I/O.

The root-owned CI wrapper supplies already bounded metadata, source buffers and
one in-memory artifact per fixed run. This module neither fetches nor retries.
An unregistered author hash, fixture inventory or workflow fails closed.
Existing Q/G helpers and their original functions remain unchanged.
"""
import hashlib
import io
import json
import re
import stat
import zipfile

REPOSITORY = "metainchelp-boop/logic-analysis"
BRANCH = "codex/naver-strategy-prepare-readonly-20261020"
BASE_HEAD = "4ed89c638742d348874a22259705b73f7ce40127"
NATIVE_PATH = ".github/workflows/naver-strategy-prepare-native.yml"
DIAGNOSTIC_PATH = ".github/workflows/naver-strategy-prepare-readonly.yml"
LIMITS = dict(json=393216, wire=102400, bootstrap=32768, ssh=131072,
              decoder_memory=33554432, qualifier_output=49152, registry=32768)
RENDER_LIMITS = dict(json=196608, wire=65536, bootstrap=32768, ssh=49152)
MAX_ARCHIVE = 4 * 1024 * 1024
MAX_MEMBER = 2 * 1024 * 1024
ROLES = {"reader", "controller", "transport", "render_wrapper", "test_reader",
         "ci_wrapper", "qualification_adapter", "source_fixture"}
CHECKS = {"no_network", "readonly_database", "no_prepare_write",
          "no_provider", "no_services", "failure_exit_nonzero",
          "transport_boundaries", "closed_output"}


class Refused(ValueError):
    pass


def need(condition, code):
    if condition is not True:
        raise Refused(code)


def digest(value, length=64):
    return (type(value) is str and
            re.fullmatch("[0-9a-f]{" + str(length) + "}", value) is not None
            and value != "0" * length)


def positive(value):
    return type(value) is int and 0 < value < 2**63


def exact(left, right):
    if type(left) is not type(right):
        return False
    if type(right) is dict:
        return (left.keys() == right.keys() and
                all(exact(left[k], right[k]) for k in right))
    if type(right) is list:
        return len(left) == len(right) and all(map(lambda p: exact(*p), zip(left, right)))
    return left == right


def sha(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("ascii")
    except (ValueError, TypeError, RecursionError):
        raise Refused("CLOSED_JSON") from None


def strict(body, cap):
    need(type(body) is bytes and 0 < len(body) <= cap, "JSON_SIZE")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, "DUPLICATE_KEY")
            result[key] = value
        return result
    def constant(_):
        raise Refused("NONFINITE")
    try:
        return json.loads(body, object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise Refused("CLOSED_JSON") from None


def relative(path):
    return (type(path) is str and re.fullmatch(r"[A-Za-z0-9_./-]+", path) is not None
            and not path.startswith("/") and
            all(part not in ("", ".", "..") for part in path.split("/"))
            and not any(part in (".env", "HANDOVER.md", "store 2.py")
                        for part in path.split("/")))


def inventory(values):
    need(type(values) is list and len(values) > 0, "FIXTURE_INVENTORY")
    need(all(type(v) is str and re.fullmatch(r"test_[a-z0-9_]+", v)
             for v in values), "FIXTURE_IDS")
    need(len(values) == len(set(values)), "FIXTURE_IDS")
    return len(values)


def registration(value):
    """A source registration is not qualification; no null/default promotion."""
    keys = {"schema", "base_head", "head_sha", "repository", "branch", "limits",
            "source_files", "author_roles", "helper9", "native_workflow",
            "diagnostic_workflow", "base_native_counts", "native_test_ids",
            "linux_test_ids", "source_fixture", "independent_source_review_sha256",
            "independent_adapter_review_sha256", "render"}
    need(type(value) is dict and set(value) == keys, "REGISTRATION_SHAPE")
    need(value["schema"] == "strategy-prepare-source-registration-v1"
         and value["base_head"] == BASE_HEAD
         and value["repository"] == REPOSITORY and value["branch"] == BRANCH,
         "REGISTRATION_TARGET")
    need(digest(value["head_sha"], 40) and value["head_sha"] != BASE_HEAD, "NEW_HEAD")
    need(exact(value["limits"], LIMITS), "LIMITS")
    need(digest(value["independent_source_review_sha256"])
         and digest(value["independent_adapter_review_sha256"]), "REVIEW_PENDING")
    files = value["source_files"]
    need(type(files) is dict and 0 < len(files) <= 200, "SOURCE_FILES")
    for path, entry in files.items():
        need(relative(path) and type(entry) is dict
             and set(entry) == {"sha256", "bytes"} and digest(entry["sha256"])
             and type(entry["bytes"]) is int and 0 <= entry["bytes"] <= 1048576,
             "SOURCE_PIN")
        need(entry["bytes"] > 0 or
             (path.startswith("backend/tests/fixtures/naver_strategy_prepare_source/")
              and path.endswith("/__init__.py")
              and entry["sha256"] == sha(b"")), "EMPTY_SOURCE")
    roles = value["author_roles"]
    need(type(roles) is dict and set(roles) == ROLES
         and all(relative(p) and p in files for p in roles.values()), "AUTHOR_PENDING")
    helpers = value["helper9"]
    need(type(helpers) is dict and len(helpers) == 9
         and all(relative(p) and p in files for p in helpers.values()), "HELPER9")
    need(len(set(helpers.values())) == 9, "HELPER9")
    for key, path in (("native_workflow", NATIVE_PATH),
                      ("diagnostic_workflow", DIAGNOSTIC_PATH)):
        entry = value[key]
        need(type(entry) is dict
             and set(entry) == {"path", "sha256", "user_steps", "wrapper_steps"},
             "WORKFLOW_SHAPE")
        need(entry["path"] == path and digest(entry["sha256"])
             and path in files and entry["sha256"] == files[path]["sha256"],
             "WORKFLOW_PIN")
        for group in ("user_steps", "wrapper_steps"):
            names = entry[group]
            need(type(names) is list and all(type(s) is str and 0 < len(s) < 160
                                            for s in names), "STEP_REGISTRATION")
            need(len(names) == len(set(names)), "STEP_REGISTRATION")
        need(entry["user_steps"] and not
             set(entry["user_steps"]) & set(entry["wrapper_steps"]), "STEP_REGISTRATION")
    counts = value["base_native_counts"]
    need(type(counts) is dict and len(counts) == 32
         and all(type(k) is str and re.fullmatch(r"[a-z0-9-]+-tests\.txt", k)
                 and positive(v) for k, v in counts.items()), "NATIVE_COUNTS")
    need(sum(counts.values()) == 2010 and counts["report-progress-tests.txt"] == 42,
         "NATIVE_COUNTS")
    inventory(value["native_test_ids"])
    inventory(value["linux_test_ids"])
    need(set(value["linux_test_ids"]) <= set(value["native_test_ids"]),
         "LINUX_COVERAGE")
    fixture = value["source_fixture"]
    need(type(fixture) is dict and
         set(fixture) == {"source_commit", "manifest_path", "manifest_sha256",
                          "equivalence_receipt_sha256", "network_fetch"},
         "SOURCE_FIXTURE")
    need(digest(fixture["source_commit"], 40) and relative(fixture["manifest_path"])
         and fixture["manifest_path"] in files and digest(fixture["manifest_sha256"])
         and fixture["manifest_sha256"] == files[fixture["manifest_path"]]["sha256"]
         and digest(fixture["equivalence_receipt_sha256"])
         and fixture["network_fetch"] is False, "SOURCE_FIXTURE_PENDING")
    rendered = value["render"]
    need(type(rendered) is dict and set(rendered) == {"script_sha256", "sizes"}
         and digest(rendered["script_sha256"]), "RENDER_PENDING")
    sizes = rendered["sizes"]
    need(type(sizes) is dict and set(sizes) == set(RENDER_LIMITS)
         and all(positive(v) and v <= RENDER_LIMITS[k] for k, v in sizes.items()),
         "RENDER_PENDING")
    need(len(canonical(value)) <= LIMITS["registry"], "REGISTRY_SIZE")
    return value


def source_buffers(registry, buffers):
    registration(registry)
    need(type(buffers) is dict and set(buffers) == set(registry["source_files"]),
         "SOURCE_BUFFER_SET")
    for path, expected in registry["source_files"].items():
        body = buffers[path]
        need(type(body) is bytes and len(body) == expected["bytes"]
             and sha(body) == expected["sha256"], "SOURCE_BUFFER_PIN")
    return sha(canonical(registry))


def run_bound(run, run_id, head, path, event):
    need(type(run) is dict and positive(run_id) and digest(head, 40), "RUN_SHAPE")
    expected = dict(id=run_id, head_sha=head, head_branch=BRANCH, path=path,
                    event=event, run_attempt=1, status="completed", conclusion="success")
    need(exact({k: run.get(k) for k in expected}, expected)
         and positive(run.get("workflow_id"))
         and type(run.get("repository")) is dict
         and run["repository"].get("full_name") == REPOSITORY, "RUN_BINDING")


def job_bound(job, run_id, head, name, workflow):
    expected = dict(run_id=run_id, head_sha=head, name=name, run_attempt=1,
                    status="completed", conclusion="success")
    need(type(job) is dict and positive(job.get("id"))
         and exact({k: job.get(k) for k in expected}, expected), "JOB_BINDING")
    rows = job.get("steps")
    need(type(rows) is list and 0 < len(rows) <= 64, "STEPS")
    expected_names = workflow["user_steps"] + workflow["wrapper_steps"]
    need(len(rows) == len(expected_names), "STEP_COUNT")
    names, numbers = [], []
    for row in rows:
        need(type(row) is dict and type(row.get("name")) is str
             and positive(row.get("number"))
             and row.get("status") == "completed" and row.get("conclusion") == "success",
             "STEP_RESULT")
        names.append(row["name"]); numbers.append(row["number"])
    need(len(set(names)) == len(names) and set(names) == set(expected_names)
         and numbers == sorted(numbers) and len(numbers) == len(set(numbers)),
         "STEP_INVENTORY")
    need([n for n in names if n in workflow["user_steps"]] == workflow["user_steps"],
         "STEP_ORDER")


def artifact_members(item, run_id, head, prefix, packed, names):
    need(type(item) is dict and positive(item.get("id"))
         and item.get("name") == prefix + str(run_id)
         and item.get("expired") is False
         and positive(item.get("size_in_bytes")), "ARTIFACT")
    origin = item.get("workflow_run")
    need(type(origin) is dict and
         exact({k: origin.get(k) for k in ("id", "head_sha", "head_branch")},
               dict(id=run_id, head_sha=head, head_branch=BRANCH)), "ARTIFACT_ORIGIN")
    need(type(packed) is bytes and 0 < len(packed) < MAX_ARCHIVE
         and len(packed) == item["size_in_bytes"]
         and item.get("digest") == "sha256:" + sha(packed), "ARTIFACT_DIGEST")
    try:
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            rows = archive.infolist()
            need(len(rows) == len(names) and {r.filename for r in rows} == set(names)
                 and len({r.filename for r in rows}) == len(rows), "ARCHIVE_NAMES")
            need(all(not r.is_dir() and 0 < r.file_size <= MAX_MEMBER
                     and stat.S_IFMT(r.external_attr >> 16) in (0, stat.S_IFREG)
                     and not r.flag_bits & 1 for r in rows)
                 and sum(r.file_size for r in rows) < MAX_ARCHIVE, "ARCHIVE_LIMITS")
            result = {r.filename: archive.read(r) for r in rows}
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError):
        raise Refused("ARCHIVE_INVALID") from None
    need(result["source-sha.txt"] == (head + "\n").encode("ascii"), "ARTIFACT_HEAD")
    return result


def fixture_expectation(registry, manifest_hash):
    ids = registry["native_test_ids"]
    want = dict(schema="strategy-prepare-native-synthetic-v1",
                head_sha=registry["head_sha"], source_manifest_sha256=manifest_hash,
                tests=dict(run=len(ids), failures=0, errors=0, skips=0),
                test_ids=ids, linux_test_ids=registry["linux_test_ids"],
                checks={k: True for k in CHECKS},
                hosted_linux=True, production_access=False,
                network_calls=0, mutations=0)
    return want


def fixture_result(body, registry, manifest_hash):
    want = fixture_expectation(registry, manifest_hash)
    need(exact(strict(body, 32768), want), "FIXTURE_RESULT")
    return want


def verify(registry, buffers, run, jobs, artifacts, packed):
    """One native run covers Linux fixtures; caller fetches its artifact once."""
    manifest = source_buffers(registry, buffers)
    need(type(jobs) is dict
         and set(jobs) == {"total_count", "jobs"}
         and type(artifacts) is dict
         and set(artifacts) == {"total_count", "artifacts"}, "GATE_INPUT")
    rid = run.get("id") if type(run) is dict else None
    head = registry["head_sha"]
    wf = registry["native_workflow"]
    run_bound(run, rid, head, wf["path"], "push")
    need(type(artifacts["total_count"]) is int and artifacts["total_count"] == 1
         and type(artifacts["artifacts"]) is list and len(artifacts["artifacts"]) == 1,
         "ARTIFACT_COUNT")
    expected_jobs = 1
    need(type(jobs["total_count"]) is int and jobs["total_count"] == expected_jobs
         and type(jobs["jobs"]) is list and len(jobs["jobs"]) == expected_jobs,
         "JOB_COUNT")
    name = "synthetic-export"
    chosen = [j for j in jobs["jobs"] if type(j) is dict and j.get("name") == name]
    need(len(chosen) == 1, "JOB_NAME")
    job_bound(chosen[0], rid, head, name, wf)
    names = set(registry["base_native_counts"]) | {
        "strategy-prepare-tests.closed.json", "source-sha.txt"}
    item = artifacts["artifacts"][0]
    prefix = "naver-strategy-prepare-native-"
    members = artifact_members(item, rid, head, prefix, packed, names)
    suite_hashes = {}
    for path, count in registry["base_native_counts"].items():
        try:
            text = members[path].decode("utf-8")
        except UnicodeError:
            raise Refused("NATIVE_ENCODING") from None
        runs = list(re.finditer(r"(?m)^Ran ([0-9]+) tests? in [^\r\n]+$", text))
        ends = list(re.finditer(r"(?m)^OK(?: \(skipped=(0)\))?\s*$", text))
        need(len(runs) == len(ends) == 1 and runs[0].end() < ends[0].start()
             and int(runs[0][1]) == count
             and not re.search(r"(?m)^(FAILED|ERROR:|FAIL:)", text), "NATIVE_SUITE")
        suite_hashes[path] = dict(count=count, sha256=sha(members[path]))
    result = fixture_result(members["strategy-prepare-tests.closed.json"],
                            registry, manifest)
    total = 2010 + len(registry["native_test_ids"])
    return dict(schema="strategy-prepare-native-qualification-v1",
                head_sha=head, run_id=rid, job_id=chosen[0]["id"],
                artifact_id=item["id"], artifact_sha256=sha(packed),
                artifact_size=len(packed), workflow_id=run["workflow_id"],
                source_manifest_sha256=manifest, total=total,
                native_base_suites=suite_hashes,
                synthetic=dict(sha256=sha(canonical(result)), tests=result["tests"]),
                coverage=dict(native=True, hosted_linux=True, same_run=True,
                              duplicate_fixture_runs=0))


def qualified_registry(registry, native, independent_result_sha256):
    registration(registry)
    need(digest(independent_result_sha256), "INDEPENDENT_RESULT_PENDING")
    manifest = sha(canonical(registry))
    validate_native_receipt(registry, native, manifest)
    result = dict(schema="strategy-prepare-qualified-registry-v1",
                  source=registry, native=native,
                  independent_result_sha256=independent_result_sha256)
    need(len(canonical(result)) <= LIMITS["registry"], "REGISTRY_SIZE")
    return result


def validate_native_receipt(registry, value, manifest):
    """Checks structure only; independent canonical digest is the trust anchor."""
    need(type(value) is dict and set(value) == {
        "schema", "head_sha", "run_id", "job_id", "artifact_id", "artifact_sha256",
        "source_manifest_sha256", "total", "native_base_suites", "synthetic",
        "artifact_size", "workflow_id",
        "coverage"}, "QUALIFIED_SHAPE")
    need(value["schema"] == "strategy-prepare-native-qualification-v1"
         and value["head_sha"] == registry["head_sha"]
         and value["source_manifest_sha256"] == manifest
         and all(positive(value[k]) for k in
                 ("run_id", "job_id", "artifact_id", "artifact_size", "workflow_id"))
         and value["artifact_size"] < MAX_ARCHIVE
         and digest(value["artifact_sha256"])
         and type(value["total"]) is int
         and value["total"] == 2010 + len(registry["native_test_ids"]),
         "QUALIFIED_BINDING")
    suites = value["native_base_suites"]
    need(type(suites) is dict and set(suites) == set(registry["base_native_counts"]),
         "QUALIFIED_SUITES")
    for path, count in registry["base_native_counts"].items():
        row = suites[path]
        need(type(row) is dict and set(row) == {"count", "sha256"}
             and type(row["count"]) is int and row["count"] == count
             and digest(row["sha256"]), "QUALIFIED_SUITES")
    expected = fixture_expectation(registry, manifest)
    need(exact(value["synthetic"], dict(sha256=sha(canonical(expected)),
                                       tests=expected["tests"])), "FIXTURE_RESULT")
    need(exact(value["coverage"], dict(native=True, hosted_linux=True,
                                      same_run=True, duplicate_fixture_runs=0)),
         "QUALIFIED_COVERAGE")


def verify_metadata(registry, receipt, run, jobs, artifacts):
    """Observe-side recheck; deliberately accepts no archive/download function."""
    registration(registry)
    validate_native_receipt(registry, receipt, sha(canonical(registry)))
    rid, head = receipt["run_id"], registry["head_sha"]
    run_bound(run, rid, head, NATIVE_PATH, "push")
    need(run["workflow_id"] == receipt["workflow_id"], "WORKFLOW_ID")
    need(type(jobs) is dict and set(jobs) == {"total_count", "jobs"}
         and type(jobs["total_count"]) is int and jobs["total_count"] == 1
         and type(jobs["jobs"]) is list and len(jobs["jobs"]) == 1, "JOB_COUNT")
    job = jobs["jobs"][0]
    job_bound(job, rid, head, "synthetic-export", registry["native_workflow"])
    need(job["id"] == receipt["job_id"], "JOB_ID")
    need(type(artifacts) is dict and set(artifacts) == {"total_count", "artifacts"}
         and type(artifacts["total_count"]) is int and artifacts["total_count"] == 1
         and type(artifacts["artifacts"]) is list and len(artifacts["artifacts"]) == 1,
         "ARTIFACT_COUNT")
    item = artifacts["artifacts"][0]
    want = dict(id=receipt["artifact_id"], size_in_bytes=receipt["artifact_size"],
                digest="sha256:" + receipt["artifact_sha256"], expired=False,
                name="naver-strategy-prepare-native-" + str(rid))
    need(type(item) is dict and exact({k: item.get(k) for k in want}, want),
         "ARTIFACT_BINDING")
    origin = item.get("workflow_run")
    need(type(origin) is dict and
         exact({k: origin.get(k) for k in ("id", "head_sha", "head_branch")},
               dict(id=rid, head_sha=head, head_branch=BRANCH)), "ARTIFACT_ORIGIN")
    return {"native_artifact_downloads": 0, "metadata_binding_verified": True}


def permit_render(qualified, expected_registry_sha256, head, attempt, intent, script, sizes):
    """Final narrow gate, not an SSH runner and not permission to retry.

    The caller must pass the exact outputs of verify and qualified_registry.
    An externally supplied object without independently pinned canonical digest
    is not accepted. Root owns the exclusive durable intent before one dispatch.
    """
    need(type(qualified) is dict and digest(expected_registry_sha256)
         and sha(canonical(qualified)) == expected_registry_sha256, "REGISTRY_BINDING")
    need(set(qualified) == {"schema", "source", "native", "independent_result_sha256"}
         and qualified["schema"] == "strategy-prepare-qualified-registry-v1"
         and digest(qualified["independent_result_sha256"]), "QUALIFIED_SHAPE")
    registry = registration(qualified.get("source"))
    validate_native_receipt(registry, qualified["native"], sha(canonical(registry)))
    need(head == registry["head_sha"] and type(attempt) is int and attempt == 1,
         "DISPATCH_BINDING")
    need(type(intent) is dict and set(intent) == {"head_sha", "registry_sha256",
         "exclusive", "dispatch_count", "retry_allowed"}
         and exact(intent, dict(head_sha=head, registry_sha256=expected_registry_sha256,
                               exclusive=True, dispatch_count=0, retry_allowed=False)),
         "ONCE_INTENT")
    need(type(script) is str and script.isascii() and "\x00" not in script
         and 0 < len(script.encode()) <= LIMITS["qualifier_output"], "OUTPUT_SIZE")
    need(type(sizes) is dict and set(sizes) == {"json", "wire", "bootstrap", "ssh"}
         and all(positive(v) and v <= RENDER_LIMITS[k] for k, v in sizes.items())
         and sizes["ssh"] == len(script.encode()), "TRANSPORT_SIZE")
    need(sha(script.encode()) == registry["render"]["script_sha256"]
         and exact(sizes, registry["render"]["sizes"]), "RENDER_BINDING")
    return {"script_sha256": sha(script.encode()), "sizes": dict(sizes),
            "dispatches": 0, "ready_for_one_root_owned_dispatch": True}
