"""Fixed diagnostic baseline proof; never substitutes for helper.verify().

Only public pinned code, deployment/export receipts, installed artifacts and
filesystem/account metadata are read. No DB contents, keys, environment, bundle
bodies, service commands or provider calls are permitted. Context is private RAM;
only the eight proof hashes may be serialized by the host adapter.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import types
import transition as T

ROOT = Path('/srv/metainc/ad-deploy-staging')
OWNER = 0
GROUP = 0
MAX_RECEIPT = 32768
MAX_SOURCE = 160000
EXPORT_SOURCE = 'e7649acfc71c25d7ae9c981a6ba036b77d97897b'
SOURCE_PINS = {
    'exports_binding': '1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed',
    'exports_helper': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737',
    'product_exporter': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59',
    'market_exporter': 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8',
}
PACKAGE = dict(operation='code-prepare',
    baseline='5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
    source_commit=EXPORT_SOURCE,
    source_tar_gz_sha256='7d02a455ff2b8b2e2bbcd598b71f5e06ffe8e9d2099f08a2e87a8ea10cbae872',
    ciphertext_sha256='5f7bcd5b0399603b75de806ce3332be5d89997aca8c06db8807f2d6f23019416',
    run_id='38198428850')


class Invalid(ValueError):
    pass


def fail(code):
    raise Invalid(code)


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            fail('PREFLIGHT_RECEIPT')
        value[key] = item
    return value


def decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda _: fail('PREFLIGHT_RECEIPT'))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise Invalid('PREFLIGHT_RECEIPT') from None


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def trusted_dir(path, *, mode=0o700):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        fail('PREFLIGHT_DIRECTORY')
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != OWNER or info.st_gid != GROUP
            or stat.S_IMODE(info.st_mode) != mode):
        fail('PREFLIGHT_DIRECTORY')


def trusted_private_file(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        fail('PREFLIGHT_FILE')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != OWNER or info.st_gid != GROUP
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
            or not 0 < info.st_size <= MAX_RECEIPT):
        fail('PREFLIGHT_FILE')
    return identity(info)


def snapshot(path):
    before = trusted_private_file(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if identity(os.fstat(fd)) != before:
            fail('PREFLIGHT_CHANGED')
        raw = b''
        while len(raw) <= MAX_RECEIPT:
            chunk = os.read(fd, min(4096, MAX_RECEIPT + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
        if (len(raw) > MAX_RECEIPT or len(raw) != before[6]
                or identity(os.fstat(fd)) != before or identity(Path(path).lstat()) != before):
            fail('PREFLIGHT_CHANGED')
        return raw, before
    finally:
        os.close(fd)


class _ReceiptSnapshot:
    """Path metadata stays checked; original Binding.load consumes this exact buffer."""
    def __init__(self, path, raw):
        self.path, self.raw = path, raw
        self.parent = path.parent

    def __fspath__(self):
        return str(self.path)

    def read_bytes(self):
        return self.raw


class _Release:
    ROOT = ROOT
    unique = staticmethod(unique)
    trusted_dir = staticmethod(trusted_dir)
    trusted_private_file = staticmethod(trusted_private_file)

    def command(self, args):
        fail('PREFLIGHT_COMMAND_FORBIDDEN')


def _modules(sources):
    modules = []
    for name in ('exports_binding', 'exports_helper'):
        module = types.ModuleType('fixed_preflight_' + name)
        exec(compile(sources[name], '<pinned-' + name + '>', 'exec'), module.__dict__)
        modules.append(module)
    return modules


def _installed_state(h, plan, receipt, content, raw):
    state = decode(raw)
    keys = {'version', 'operation_id', 'state', 'created_files', 'created_directories',
            'timers_enabled', 'engine_verified', 'interpreter_identity', 'sources'}
    if (type(state) is not dict or set(state) != keys or type(state['version']) is not int
            or state['version'] != 1 or state['operation_id'] != receipt['operation_id']
            or state['state'] != 'installed' or state['timers_enabled'] is not True
            or state['engine_verified'] is not False or not h._valid_file_identity(state['interpreter_identity'])
            or type(state['sources']) is not dict or set(state['sources']) != {'product', 'market'}):
        fail('PREFLIGHT_INSTALLED')
    directory = h.INSTALL / plan['ops_commit']
    paths = {str(directory / name) if name in (*h.SCRIPTS, *h.COORDINATORS.values(), h.INTERPRETER)
             else str(h.UNITS / name) for name in content if name != h.COMPANION}
    created, directories = state['created_files'], state['created_directories']
    if (type(created) is not list or any(type(v) is not str for v in created)
            or len(created) != len(paths) or set(created) != paths
            or type(directories) is not list or any(type(v) is not str for v in directories)
            or len(directories) != len(set(directories)) or str(directory) not in directories
            or not set(directories) <= {str(directory), *(str(v) for v in h.OUTPUTS.values())}):
        fail('PREFLIGHT_INSTALLED')
    return state


def _collect(sources, binding, h):
    for directory in (ROOT, ROOT / 'receipts'):
        trusted_dir(directory)
    operating_path = ROOT / 'receipts' / ('preview-start-' + T.OPERATING_SOURCE + '.json')
    operating_raw, operating_identity = snapshot(operating_path)
    operating = decode(operating_raw)
    required = dict(ok=True, stage='internal_ready', source_commit=T.OPERATING_SOURCE,
        previous_commit='513e52eaee4d1bb722461961639cd588df9080cd',
        operation_id=T.OPERATING_OPERATION, database_policy='preserve-in-place', execution_enabled=False)
    if type(operating) is not dict or any(not T.same(operating.get(k), v) for k, v in required.items()):
        fail('PREFLIGHT_OPERATING_RECEIPT')
    release = _Release()
    scripts = {'naver_product_export.py': sources['product_exporter'],
               'naver_market_export.py': sources['market_exporter']}
    bound = binding.Binding(types.SimpleNamespace(TARGET_COMMIT=EXPORT_SOURCE), h,
                            release, sources['exports_helper'], scripts)
    exports_path = ROOT / 'receipts' / ('completion-exports-' + EXPORT_SOURCE + '.json')
    if bound.path != exports_path:
        fail('PREFLIGHT_PATH')
    exports_raw, exports_identity = snapshot(exports_path)
    decode(exports_raw)  # Reject duplicate keys/non-finite constants before original load.
    bound.path = _ReceiptSnapshot(exports_path, exports_raw)
    bound.load(dict(PACKAGE), verify=False)
    receipt = bound.receipt
    plan, folder, content = h._prepared(receipt)
    if not T.same(plan, bound.plan) or not T.same(plan, T.PROFILE):
        fail('PREFLIGHT_PLAN')
    expected = h.artifacts(plan, scripts, binding.PINS['scripts'])
    if set(content) != set(expected) | {h.INTERPRETER} or any(content[k] != v for k, v in expected.items()):
        fail('PREFLIGHT_PREPARED')
    prepared_raw = h._regular(folder / 'prepared.json', maximum=MAX_RECEIPT, mode=0o600)
    if prepared_raw != h._json(receipt):
        fail('PREFLIGHT_PREPARED')
    source, runtime = h._source_identity(plan), h._identity(plan)
    if not T.same(source, receipt['source_identity']) or not T.same(runtime, receipt['runtime_identity']):
        fail('PREFLIGHT_IDENTITY')
    uid = runtime.get('exporter_uid')
    if type(uid) is not int or not 0 < uid < 2**32:
        fail('PREFLIGHT_IDENTITY')
    installed_raw = h._regular(folder / 'installed.json', maximum=MAX_RECEIPT, mode=0o600)
    state = _installed_state(h, plan, receipt, content, installed_raw)
    manifest, interpreter = {}, None
    for name, body in content.items():
        if name == h.COMPANION:
            continue
        path = h.INSTALL / plan['ops_commit'] / name if name in (*h.SCRIPTS, *h.COORDINATORS.values(), h.INTERPRETER) else h.UNITS / name
        if name == h.INTERPRETER:
            actual, installed_identity = h._binary(path, mode=0o550, group=h.READER_GID)
            if not T.same(installed_identity, state['interpreter_identity']) or actual != body:
                fail('PREFLIGHT_INSTALLED')
            interpreter = dict(prepared=receipt['interpreter'], installed=installed_identity, sha256=T.sha(actual))
        else:
            actual = h._regular(path, mode=0o644)
            if actual != body:
                fail('PREFLIGHT_INSTALLED')
        manifest[str(path)] = T.sha(actual)
    if interpreter is None:
        fail('PREFLIGHT_INSTALLED')
    for path, expected_identity in ((operating_path, operating_identity), (exports_path, exports_identity)):
        if identity(path.lstat()) != expected_identity:
            fail('PREFLIGHT_CHANGED')
    proofs = dict(operating_receipt_sha256=T.sha(operating_raw),
        exports_receipt_sha256=T.sha(exports_raw), prepared_receipt_sha256=T.sha(prepared_raw),
        installed_receipt_sha256=T.sha(installed_raw), original_manifest_sha256=T.sha(T.canonical(manifest)),
        source_identity_sha256=T.sha(T.canonical(source)), runtime_identity_sha256=T.sha(T.canonical(runtime)),
        interpreter_identity_sha256=T.sha(T.canonical(interpreter)))
    if set(proofs) != T.PROOF_KEYS:
        fail('PREFLIGHT_PROOFS')
    for value in proofs.values():
        T.digest(value)
    # No module, binding, code body or receipt is part of the public proof map.
    private = types.SimpleNamespace(runtime_uid=uid, plan=plan,
        prepared_receipt=receipt, installed_receipt=state,
        install_directory=h.INSTALL / plan['ops_commit'], units_directory=h.UNITS,
        prepared_directory=folder)
    return proofs, private


def collect(sources):
    """Return (eight SHA256 proofs, private RAM context); host state is a separate gate."""
    if type(sources) is not dict or set(sources) != set(SOURCE_PINS):
        fail('PREFLIGHT_SOURCE')
    for name, pin in SOURCE_PINS.items():
        body = sources[name]
        if type(body) is not bytes or not 0 < len(body) <= MAX_SOURCE or T.sha(body) != pin:
            fail('PREFLIGHT_SOURCE')
    try:
        binding, helper = _modules(sources)
        return _collect(sources, binding, helper)
    except Invalid:
        raise
    except Exception:
        raise Invalid('PREFLIGHT_UNAVAILABLE') from None
