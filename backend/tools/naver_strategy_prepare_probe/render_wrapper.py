"""Local rendering only; returns a command without invoking it.

Original diagnostic transport caps and codec are preserved. The workflow's
existing Q.output 49152-byte cap remains stricter than the SSH 131072-byte cap.
"""
import ast
import base64
import hashlib
import json
from pathlib import Path
import types

DRAFT = Path(__file__).resolve().parent
IN_REPOSITORY = DRAFT.name == "naver_strategy_prepare_probe"
ROOT = DRAFT.parents[2] if IN_REPOSITORY else DRAFT.parents[3]
OPS_TOOLS = ROOT / "backend/tools" if IN_REPOSITORY else ROOT / "work/naver-claude-reference-ops-20261011/backend/tools"
MAX_BOOTSTRAP, MAX_SSH, MAX_OUTPUT = 32768, 131072, 49152
MARKER = "NAVER_STRATEGY_PREPARE_382F_ONCE_V1="
BOOTSTRAP_FUNCTIONS = frozenset(("require_pins", "unique", "validate_package", "validate",
                                "decode", "modules", "project_result", "failure", "execute"))


def bootstrap_source(body):
    """Select original function bytes needed by the decoder/executor only.

    Encode/compact/bundle/input-adapter functions remain in the registered
    transport source and run locally. No selected runtime function is edited.
    """
    source = body.decode()
    selected = [node for node in ast.parse(source).body
                if not isinstance(node, ast.FunctionDef) or node.name in BOOTSTRAP_FUNCTIONS]
    names = {node.name for node in selected if isinstance(node, ast.FunctionDef)}
    if names != BOOTSTRAP_FUNCTIONS:
        raise ValueError("BOOTSTRAP_FUNCTIONS")
    return ("\n\n".join(ast.get_source_segment(source, node) for node in selected)+"\n").encode()


def render():
    body = (DRAFT / "transport.py").read_bytes()
    transport = types.ModuleType("fixed_strategy_probe_transport")
    exec(compile(body, "<fixed-strategy-probe-transport>", "exec"), transport.__dict__)
    sources = {}
    for name, filename in transport.SOURCE_FILES.items():
        raw = ((DRAFT if name == "diagnostic" else OPS_TOOLS) / filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != transport.SOURCE_SHA256[name]:
            raise ValueError("SOURCE_PIN")
        sources[name] = transport.compact(raw.decode())
    value = dict(version=1, operation=transport.OPERATION, package=dict(transport.PACKAGE), sources=sources)
    wire = transport.encode(value)
    bootstrap_body = bootstrap_source(body)
    encoded = base64.b64encode(bootstrap_body).decode("ascii")
    if transport.decode(wire) != value or len(encoded) > MAX_BOOTSTRAP:
        raise ValueError("TRANSPORT")
    command = "set -eu\n/usr/bin/python3 -I -B - <<'PYCODE'\nimport base64,hashlib,json,os,sys,types\ntry:\n"
    command += "    wire=" + repr(wire) + "; source=" + repr(encoded) + "\n"
    command += "    if len(source)>32768:raise ValueError('SOURCE_DIAGNOSTICS_TRANSPORT_SIZE')\n    raw=base64.b64decode(source,validate=True)\n"
    command += "    if hashlib.sha256(raw).hexdigest()!=" + repr(hashlib.sha256(bootstrap_body).hexdigest()) + ":raise ValueError('SOURCE_DIAGNOSTICS_TRANSPORT_SOURCE')\n"
    command += "    transport=types.ModuleType('fixed_strategy_probe_transport');exec(raw,transport.__dict__)\n    bundle=transport.decode(wire)\n    os.environ.clear();os.environ.update(PATH='/usr/sbin:/usr/bin:/sbin:/bin',LANG='C')\n    result=transport.execute(bundle)\nexcept BaseException:\n"
    command += "    result={'ok':False,'mode':'foodin-strategy-prepare-382f-once-v1','source_commit':'382f143ad72a5fb0389d79ba0fac199566016e8b','mutations':0,'collection_completion_verified':False,'stage':'bootstrap','error_code':'SOURCE_DIAGNOSTICS_BOOTSTRAP_REFUSED'}\n"
    command += "print(" + repr(MARKER) + "+json.dumps(result,sort_keys=True,allow_nan=False));sys.exit(0 if result.get('ok') else 1)\nPYCODE\n"
    if not command.isascii() or len(command.encode()) > min(MAX_SSH, MAX_OUTPUT):
        raise ValueError("EXISTING_OUTPUT_SIZE")
    return command, dict(
        json_bytes=len(json.dumps(value, allow_nan=False, separators=(",", ":")).encode()),
        wire_bytes=len(wire), bootstrap_bytes=len(encoded), ssh_bytes=len(command.encode()),
        existing_output_limit=MAX_OUTPUT, sources=dict(transport.SOURCE_SHA256),
        compact_sources=dict(transport.COMPACT_SHA256), transport_sha256=hashlib.sha256(body).hexdigest(),
        bootstrap_source_sha256=hashlib.sha256(bootstrap_body).hexdigest(),
        bootstrap_functions=sorted(BOOTSTRAP_FUNCTIONS),
        script_sha256=hashlib.sha256(command.encode()).hexdigest(),
        remote_execution=False, qualification_reused=False,
    )
