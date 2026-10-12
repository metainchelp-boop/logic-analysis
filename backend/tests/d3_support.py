"""Offline-only module loader and synthetic pinning; not an execution approval."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import types

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
AUTH = {'head': 'a' * 40, 'run_id': 123, 'receipt_sha256': 'b' * 64}
SELF = 'c' * 64

def load(name):
    path = TOOLS / name
    spec = importlib.util.spec_from_file_location('synthetic_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def controller():
    return load('naver_daily_current_diagnostics_v3.py')

def pin_controller(c):
    c.bind_verified_evidence(dict(c.APPROVED_RECEIPTS, controller_transport_identity=SELF), SELF, copy.deepcopy(AUTH))
    return c

def transport():
    return load('naver_daily_current_transport_v3.py')

def pin_transport(t):
    raw = {k: hashlib.sha256((TOOLS/n).read_bytes()).hexdigest() for k,n in t.SOURCE_FILES.items()}
    assert raw == t.SOURCE_SHA256, 'D3_FROZEN_RAW_SOURCE_MAP_MISMATCH'
    compact = {k: hashlib.sha256((TOOLS/n).read_bytes() if k == 'reader' else t.compact((TOOLS/n).read_text()).encode()).hexdigest() for k,n in t.SOURCE_FILES.items()}
    assert compact == t.COMPACT_SHA256, 'D3_FROZEN_COMPACT_SOURCE_MAP_MISMATCH'
    t.__verified_self_sha__ = SELF
    t.authorize(SELF, copy.deepcopy(AUTH))
    return t

def package():
    return pin_controller(controller()).package_expected()

def failed(code='D3_READER_FAILED'):
    c = controller()
    return dict(ok=False, mode=c.MODE, source_commit=c.SOURCE, mutations=0,
        database_opened_by_controller=False, collection_completion_verified=False,
        failure=dict(primary_code=code, post_engine_code=None, post_legacy_code=None, post_proof_code=None))
