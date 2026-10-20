"""Fixed diagnostic qualification wrapper. No deployment or SSH execution.

native-fixtures: new synthetic tests only, no network.
qualify-native: root-owned local mode, native ZIP exactly once into RAM.
observe-build: exact closed registry plus current metadata, ZIP downloads zero.
All entrypoints refuse until the independent adapter hash is registered.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import types
import unittest

BASE = "backend/tools/naver_strategy_prepare_probe/"
ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = BASE + "source-registration.template.json"
ADAPTER = BASE + "qualification_adapter.py"
ADAPTER_SHA256 = "ff0f06606d2c0ec8291fb7d96deb165db2ec751cdecf7dd7ac47f032298ff8d0"
Q_PATH = "backend/tools/naver_market_operation_ledger/qualification.py"
Q_SHA256 = "06a302a5744bb24423b1f52703f5432fd2bfd40bf50a27f83eff0f4229ae0058"
REPOSITORY = "metainchelp-boop/logic-analysis"
BRANCH = "codex/naver-strategy-prepare-readonly-20261020"
CONFIRM = "READ_FOODIN_STRATEGY_PREPARE_ONCE"
SOURCE = "382f143ad72a5fb0389d79ba0fac199566016e8b"
TEST_MODULES = (
    "backend/tests/test_naver_strategy_prepare_probe.py",
    "backend/tests/test_naver_strategy_prepare_qualification.py",
    "backend/tests/test_naver_strategy_prepare_ci_wrapper.py",
)


class Refused(ValueError):
    pass


def need(value, code):
    if value is not True:
        raise Refused(code)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def digest(value, length=64):
    return type(value) is str and re.fullmatch("[0-9a-f]{"+str(length)+"}", value) is not None


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")


def read_public(relative, pin=None, maximum=1048576, *, allow_empty=False):
    need(type(relative) is str and re.fullmatch(r"[A-Za-z0-9_./-]+", relative) is not None
         and not relative.startswith("/") and all(p not in ("", ".", "..", ".env", "HANDOVER.md", "store 2.py") for p in relative.split("/")), "SOURCE_PATH")
    path = ROOT / relative
    need(not any(p.is_symlink() for p in (path, *path.parents)), "SOURCE_PATH")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and (0 if allow_empty else 1) <= before.st_size <= maximum, "SOURCE_FILE")
        body = bytearray()
        while len(body) <= maximum:
            part = os.read(fd, min(65536, maximum+1-len(body)))
            if not part:
                break
            body.extend(part)
        after, named = os.fstat(fd), path.stat(follow_symlinks=False)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
        need(identity(before) == identity(after) == identity(named) and len(body) == before.st_size, "SOURCE_CHANGED")
    finally:
        os.close(fd)
    body = bytes(body)
    if pin is not None:
        need(digest(pin) and sha(body) == pin, "SOURCE_PIN")
    return body


def module(body, name, relative):
    value = types.ModuleType(name)
    value.__file__ = str(ROOT / relative)
    sys.modules[name] = value
    exec(compile(body, value.__file__, "exec"), value.__dict__)
    return value


def dependencies():
    need(digest(ADAPTER_SHA256), "ADAPTER_REGISTRATION_PENDING")
    adapter = module(read_public(ADAPTER, ADAPTER_SHA256), "fixed_strategy_prepare_adapter", ADAPTER)
    old = module(read_public(Q_PATH, Q_SHA256), "fixed_strategy_prepare_original_qualification", Q_PATH)
    return adapter, old


def context(event):
    need(os.environ.get("GITHUB_ACTIONS") == "true"
         and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
         and os.environ.get("GITHUB_REF") == "refs/heads/"+BRANCH
         and os.environ.get("GITHUB_EVENT_NAME") == event
         and os.environ.get("GITHUB_RUN_ATTEMPT") == "1", "CONTEXT")
    head, run_id = os.environ.get("GITHUB_SHA"), os.environ.get("GITHUB_RUN_ID")
    need(digest(head, 40) and type(run_id) is str and re.fullmatch("[1-9][0-9]{0,18}", run_id) is not None
         and int(run_id) < 2**63, "CONTEXT")
    return head, int(run_id)


def source_registration(adapter, head):
    need(digest(head, 40), "SOURCE_HEAD")
    template = adapter.strict(read_public(TEMPLATE, maximum=32768), 32768)
    need(type(template) is dict and template.get("head_sha", "missing") is None, "TEMPLATE_HEAD")
    registry = {**template, "head_sha": head}
    adapter.registration(registry)
    need(TEMPLATE not in registry["source_files"], "SELF_HASH_CYCLE")
    need(registry["author_roles"]["ci_wrapper"] == BASE+"ci_wrapper.py"
         and registry["author_roles"]["qualification_adapter"] == ADAPTER, "AUTHOR_PATH")
    buffers = {}
    for path, entry in registry["source_files"].items():
        empty = (entry["bytes"] == 0 and path.startswith("backend/tests/fixtures/naver_strategy_prepare_source/")
                 and path.endswith("/__init__.py") and entry["sha256"] == sha(b""))
        buffers[path] = read_public(path, entry["sha256"], allow_empty=empty)
    manifest = adapter.source_buffers(registry, buffers)
    need(buffers[ADAPTER] == read_public(ADAPTER, ADAPTER_SHA256), "ADAPTER_PIN")
    fixture = adapter.strict(buffers[registry["source_fixture"]["manifest_path"]], 32768)
    prefix = "backend/tests/fixtures/naver_strategy_prepare_source/"
    need(fixture.get("source_commit") == SOURCE and fixture.get("count") == 60
         and fixture.get("backup_included") is False
         and type(fixture.get("files")) is dict and len(fixture["files"]) == 60, "FIXTURE_MANIFEST")
    expected = {prefix+relative for relative in fixture["files"]}
    need(expected == {path for path in buffers if path.startswith(prefix)}, "FIXTURE_SET")
    need(all(sha(buffers[prefix+relative]) == pin for relative, pin in fixture["files"].items()), "FIXTURE_PIN")
    actual = {str(path.relative_to(ROOT)) for path in (ROOT / prefix).rglob("*.py")}
    need(actual == expected, "FIXTURE_UNREGISTERED")
    return registry, buffers, manifest


def write_closed(path, value):
    body = canonical(value)
    need(0 < len(body) <= 32768, "CLOSED_SIZE")
    path = Path(path).absolute()
    need(path.name.endswith(".closed.json") and not any(p.is_symlink() for p in (path, *path.parents)), "CLOSED_PATH")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(body)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    return sha(body)


class DiscardOutput:
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def no_network_or_process(event, args):
    if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork"}:
        raise Refused("FIXTURE_EXTERNAL_CALL")


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def native_fixtures(args):
    head, _ = context("push")
    adapter, old = dependencies()
    registry, buffers, manifest = source_registration(adapter, head)
    need(platform.system() == "Linux" and os.environ.get("RUNNER_OS") == "Linux"
         and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted", "HOSTED_LINUX")
    base = Path(os.environ["RUNNER_TEMP"]).absolute() / "product-tests"
    need(Path(args.head_file).absolute() == base/"source-sha.txt"
         and Path(args.output).absolute() == base/"strategy-prepare-tests.closed.json"
         and not any(p.is_symlink() for p in (base, *base.parents)), "FIXTURE_OUTPUT_PATH")
    need((base/"source-sha.txt").read_bytes() == (head+"\n").encode("ascii"), "FIXTURE_HEAD")
    with old.dependencies(ROOT):
        pass
    sys.dont_write_bytecode = True
    sys.addaudithook(no_network_or_process)
    suite = unittest.TestSuite()
    with contextlib.redirect_stdout(DiscardOutput()), contextlib.redirect_stderr(DiscardOutput()):
        for index, path in enumerate(TEST_MODULES):
            need(path in buffers, "TEST_MODULE_PIN")
            tests = module(buffers[path], "fixed_strategy_prepare_tests_"+str(index), path)
            suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(tests))
        identifiers = sorted(test.id().rsplit(".", 1)[-1] for test in flatten(suite))
        need(identifiers == sorted(registry["native_test_ids"])
             and len(identifiers) == len(set(identifiers)), "TEST_INVENTORY")
        result = unittest.TestResult()
        suite.run(result)
    counts = dict(run=result.testsRun, failures=len(result.failures), errors=len(result.errors), skips=len(result.skipped))
    passed = counts == dict(run=len(identifiers), failures=0, errors=0, skips=0)
    value = dict(schema="strategy-prepare-native-synthetic-v1", head_sha=head,
                 source_manifest_sha256=manifest, tests=counts,
                 test_ids=registry["native_test_ids"], linux_test_ids=registry["linux_test_ids"],
                 checks={key: passed for key in adapter.CHECKS}, hosted_linux=True,
                 production_access=False, network_calls=0, mutations=0)
    write_closed(args.output, value)
    need(passed, "FIXTURE_FAILED")
    return dict(ok=True, stage="native-fixtures", tests=counts, source_manifest_sha256=manifest)


def native_metadata(adapter, registry, api, run_id, expected=None):
    """Three bounded metadata reads; never touches artifact ZIP or job logs."""
    run, jobs, artifacts = api.run(run_id), api.jobs(run_id), api.artifacts(run_id)
    if expected is not None:
        need(expected["run_id"] == run_id, "NATIVE_RECEIPT_BINDING")
        adapter.verify_metadata(registry, expected, run, jobs, artifacts)
        return run, jobs, artifacts
    adapter.run_bound(run, run_id, registry["head_sha"], adapter.NATIVE_PATH, "push")
    need(type(jobs) is dict and set(jobs) == {"total_count", "jobs"}
         and type(jobs["total_count"]) is int and jobs["total_count"] == 1
         and type(jobs["jobs"]) is list and len(jobs["jobs"]) == 1, "JOB_COUNT")
    job = jobs["jobs"][0]
    adapter.job_bound(job, run_id, registry["head_sha"], "synthetic-export", registry["native_workflow"])
    need(type(artifacts) is dict and set(artifacts) == {"total_count", "artifacts"}
         and type(artifacts["total_count"]) is int and artifacts["total_count"] == 1
         and type(artifacts["artifacts"]) is list and len(artifacts["artifacts"]) == 1, "ARTIFACT_COUNT")
    item = artifacts["artifacts"][0]
    origin = item.get("workflow_run") if type(item) is dict else None
    need(type(item) is dict and adapter.positive(item.get("id"))
         and item.get("name") == "naver-strategy-prepare-native-"+str(run_id)
         and item.get("expired") is False and adapter.positive(item.get("size_in_bytes"))
         and item["size_in_bytes"] < adapter.MAX_ARCHIVE
         and type(item.get("digest")) is str and re.fullmatch("sha256:[0-9a-f]{64}", item["digest"]) is not None
         and type(origin) is dict and adapter.exact(
             {k: origin.get(k) for k in ("id", "head_sha", "head_branch")},
             dict(id=run_id, head_sha=registry["head_sha"], head_branch=BRANCH)), "ARTIFACT_BINDING")
    return run, jobs, artifacts


def qualify_native(args):
    """Root invokes once after same-head native completion and source review."""
    need(os.environ.get("GITHUB_ACTIONS") != "true" and digest(args.head, 40)
         and digest(args.source_registry_sha256), "LOCAL_QUALIFICATION")
    adapter, old = dependencies()
    registry, buffers, manifest = source_registration(adapter, args.head)
    need(manifest == args.source_registry_sha256 and adapter.positive(args.native_run_id), "SOURCE_REGISTRY_BINDING")
    git = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD"],
                         capture_output=True, timeout=10,
                         env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"})
    need(git.returncode == 0 and git.stdout == (args.head+"\n").encode("ascii"), "LOCAL_HEAD")
    folder = Path(args.intent_dir).absolute()
    need(folder.is_dir() and not any(p.is_symlink() for p in (folder, *folder.parents)), "INTENT_PATH")
    # Exclusive creation is before any API read. A failure retains this intent;
    # a repeated invocation cannot fetch this same native artifact again.
    intent = folder / ("native-"+str(args.native_run_id)+"-"+args.head+".intent.closed.json")
    write_closed(intent, dict(schema="strategy-prepare-native-once-intent-v1", head_sha=args.head,
                             run_id=args.native_run_id, source_manifest_sha256=manifest,
                             retry_allowed=False, raw_artifact_saved=False))
    with old.dependencies(ROOT) as helpers:
        api = helpers["fixed_actions_api"]
        run, jobs, artifacts = native_metadata(adapter, registry, api, args.native_run_id)
        item = artifacts["artifacts"][0]
        packed = api.artifact_zip(item["id"])
        native = adapter.verify(registry, buffers, run, jobs, artifacts, packed)
        del packed
    receipt_sha = write_closed(args.output, native)
    return dict(ok=True, stage="qualify-native", native_receipt_sha256=receipt_sha,
                native_canonical_sha256=adapter.sha(adapter.canonical(native)),
                native_run_id=args.native_run_id, artifact_downloads=1, raw_artifact_saved=False)


def observe_build(args):
    head, current_run = context("workflow_dispatch")
    need(os.environ.get("PROBE_CONFIRM") == CONFIRM, "CONFIRM")
    expected = os.environ.get("PROBE_REGISTRY_SHA256")
    raw = os.environ.get("PROBE_QUALIFIED_REGISTRY")
    need(digest(expected) and type(raw) is str and 0 < len(raw.encode()) <= 32768, "REGISTRY_INPUT")
    adapter, old = dependencies()
    qualified = adapter.strict(raw.encode(), 32768)
    need(adapter.canonical(qualified) == raw.encode() and sha(raw.encode()) == expected, "REGISTRY_CANONICAL")
    registry, buffers, _ = source_registration(adapter, head)
    need(adapter.exact(qualified.get("source"), registry), "REGISTRY_SOURCE")
    # permit_render authenticates the entire independently reviewed registry
    # before network access; neither source file is reconstructed from inputs.
    renderer = module(buffers[registry["author_roles"]["render_wrapper"]],
                      "fixed_strategy_prepare_render", registry["author_roles"]["render_wrapper"])
    script, metadata = renderer.render()
    sizes = {name: metadata[name+"_bytes"] for name in ("json", "wire", "bootstrap", "ssh")}
    intent = dict(head_sha=head, registry_sha256=expected, exclusive=True, dispatch_count=0, retry_allowed=False)
    allowed = adapter.permit_render(qualified, expected, head, 1, intent, script, sizes)
    native = qualified["native"]
    need(current_run != native["run_id"], "RUN_REUSE")
    with old.dependencies(ROOT) as helpers:
        native_metadata(adapter, registry, helpers["fixed_actions_api"], native["run_id"], expected=native)
    old.output(os.environ.get("GITHUB_OUTPUT"), script)
    return dict(ok=True, stage="observe-build", head_sha=head, native_run_id=native["run_id"],
                registry_sha256=expected, script_sha256=allowed["script_sha256"],
                sizes=sizes, artifact_downloads=0, ssh_executed_by_wrapper=False)


def main(argv=None):
    parser = argparse.ArgumentParser()
    modes = parser.add_subparsers(dest="mode", required=True)
    native = modes.add_parser("native-fixtures")
    native.add_argument("--head-file", required=True)
    native.add_argument("--output", required=True)
    qualify = modes.add_parser("qualify-native")
    qualify.add_argument("--head", required=True)
    qualify.add_argument("--native-run-id", type=int, required=True)
    qualify.add_argument("--source-registry-sha256", required=True)
    qualify.add_argument("--intent-dir", required=True)
    qualify.add_argument("--output", required=True)
    modes.add_parser("observe-build")
    args = parser.parse_args(argv)
    try:
        result = {"native-fixtures": native_fixtures, "qualify-native": qualify_native,
                  "observe-build": observe_build}[args.mode](args)
    except BaseException:
        print("NAVER_STRATEGY_PREPARE_WRAPPER_V1="+json.dumps(
            dict(ok=False, stage=args.mode, error_code="CLOSED_WRAPPER_REFUSAL"), sort_keys=True))
        return 1
    print("NAVER_STRATEGY_PREPARE_WRAPPER_V1="+json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
