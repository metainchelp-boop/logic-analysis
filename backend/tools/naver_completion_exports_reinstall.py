"""Reinstall only the pinned, prepared completion export companion.

The old application must still be running and the target must never have been
started. A rolled-back installer journal is copied durably before its exact
inode is removed. Every attempt has an immutable intent/result; replay verifies
only and never starts the export jobs again. No application, database, release,
binding, prepared receipt, or system interpreter is rewritten by this module.
The existing coordinator may create SQLite WAL/SHM coordination files.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

OLD_COMMIT = '737a65952f2ddbc05a235cf2b139a4a11f4e7673'
TARGET_COMMIT = 'e7649acfc71c25d7ae9c981a6ba036b77d97897b'
ROOT_UID = 0
ROOT_GID = 0
MAX_RECEIPT = 32768
MAX_ATTEMPTS = 32
STAGES = frozenset(('input', 'prepared', 'current_state', 'lock', 'journal',
    'previous_copy', 'intent', 'journal_remove', 'install', 'verify', 'result', 'replay'))
CODES = frozenset(('REINSTALL_INPUT', 'REINSTALL_PIN', 'REINSTALL_ROOT',
    'REINSTALL_MISSING', 'REINSTALL_FILE_POLICY', 'REINSTALL_CHANGED',
    'REINSTALL_ALREADY_STARTED', 'REINSTALL_CURRENT_STATE', 'REINSTALL_JOURNAL',
    'REINSTALL_MANAGED_PRESENT', 'REINSTALL_BUSY', 'REINSTALL_PENDING',
    'REINSTALL_RECEIPT', 'REINSTALL_PREVIOUS_ATTEMPT', 'REINSTALL_UNCONFIRMED',
    'REINSTALL_INSTALL_FAILED', 'REINSTALL_FAILED'))
ROLES = frozenset(('none', 'preview_receipt', 'binding_receipt', 'prepared_artifact',
    'journal', 'previous_journal', 'intent', 'result', 'managed_artifact', 'lock'))
KINDS = frozenset(('ValueError', 'RuntimeError', 'OSError', 'FileNotFoundError',
    'PermissionError', 'FileExistsError', 'ExportInstallInvalid', 'TimeoutExpired',
    'CalledProcessError', 'ReinstallInvalid', 'OtherError'))
COMMAND_STAGES = frozenset(('unit_verify daemon_reload product_start market_start '
    'product_enable market_enable product_show market_show product_enabled market_enabled '
    'product_active market_active product_disable market_disable product_stop market_stop '
    'product_reader_show market_reader_show product_reader_stop market_reader_stop unknown').split())
COMMAND_ISSUES = frozenset(('permission_denied missing_file disk_full unit_syntax namespace '
    'readonly sqlite_open python_import command_timeout command_failed unknown').split())


def _label(value, choices, fallback):
    return value if type(value) is str and value in choices else fallback


class ReinstallInvalid(ValueError):
    def __init__(self, code, stage='input', role='none', *, cause=None, cleanup='not_needed'):
        super().__init__(code)
        kind = type(cause).__name__ if cause is not None else type(self).__name__
        self.failure_details = dict(stage=_label(stage, STAGES, 'input'),
            code=_label(code, CODES, 'REINSTALL_FAILED'),
            error_kind=_label(kind, KINDS, 'OtherError'),
            missing_role=_label(role, ROLES, 'none'), cleanup=cleanup)
        extra = getattr(cause, 'failure_details', None)
        if type(extra) is dict:
            if _label(extra.get('export_command_stage'), COMMAND_STAGES, None) is not None:
                self.failure_details['export_command_stage'] = extra['export_command_stage']
            if _label(extra.get('export_command_issue'), COMMAND_ISSUES, None) is not None:
                self.failure_details['export_command_issue'] = extra['export_command_issue']
            number = extra.get('export_command_status')
            if type(number) is int and 0 <= number <= 255:
                self.failure_details['export_command_status'] = number


def failure_report(error):
    """Return closed labels only; exception arguments/paths never leave memory."""
    details = getattr(error, 'failure_details', {})
    if type(details) is not dict:
        details = {}
    result = dict(ok=False, stage=_label(details.get('stage'), STAGES, 'input'),
        code=_label(details.get('code'), CODES, 'REINSTALL_FAILED'),
        error_kind=_label(details.get('error_kind'), KINDS, 'OtherError'),
        missing_role=_label(details.get('missing_role'), ROLES, 'none'),
        cleanup=_label(details.get('cleanup'), ('not_needed', 'rolled_back', 'failed', 'not_attempted'), 'not_attempted'),
        database_writes=False, engine_changed=False)
    for key, choices in (('export_command_stage', COMMAND_STAGES), ('export_command_issue', COMMAND_ISSUES)):
        if type(details.get(key)) is str and details[key] in choices:
            result[key] = details[key]
    number = details.get('export_command_status')
    if type(number) is int and 0 <= number <= 255:
        result['export_command_status'] = number
    return result


def _fail(code, stage, role='none'):
    raise ReinstallInvalid(code, stage, role)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()


def _sha(body):
    return hashlib.sha256(body).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate')
        result[key] = value
    return result


def _identity(info):
    return dict(dev=info.st_dev, ino=info.st_ino, uid=info.st_uid, gid=info.st_gid,
        mode=stat.S_IMODE(info.st_mode), nlink=info.st_nlink, size=info.st_size,
        mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)


def _check(info, stage, role, *, maximum=MAX_RECEIPT):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID or info.st_gid != ROOT_GID
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
            or not 0 <= info.st_size <= maximum):
        _fail('REINSTALL_FILE_POLICY', stage, role)


def _read(path, stage, role, *, keep=False):
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(fd); _check(before, stage, role)
        body = bytearray()
        while len(body) <= MAX_RECEIPT:
            chunk = os.read(fd, min(8192, MAX_RECEIPT + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
        if len(body) > MAX_RECEIPT or _identity(before) != _identity(os.fstat(fd)):
            _fail('REINSTALL_CHANGED', stage, role)
        if _identity(before) != _identity(os.lstat(path)):
            _fail('REINSTALL_CHANGED', stage, role)
        if keep:
            result = (bytes(body), _identity(before), fd); fd = None
            return result
        return bytes(body), _identity(before)
    except FileNotFoundError as error:
        raise ReinstallInvalid('REINSTALL_MISSING', stage, role, cause=error) from None
    finally:
        if fd is not None:
            os.close(fd)


def _decode(body, stage, role):
    try:
        return json.loads(body, object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('constant')))
    except (ValueError, UnicodeError):
        _fail('REINSTALL_RECEIPT', stage, role)


def _sync(folder):
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _create(path, body, stage, role):
    if len(body) > MAX_RECEIPT:
        _fail('REINSTALL_RECEIPT', stage, role)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    created = os.fstat(fd)
    try:
        os.fchown(fd, ROOT_UID, ROOT_GID); os.fchmod(fd, 0o600)
        view = memoryview(body)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError('write failed')
            view = view[written:]
        os.fsync(fd)
        info = os.fstat(fd); _check(info, stage, role)
        if (info.st_dev, info.st_ino) != (created.st_dev, created.st_ino):
            _fail('REINSTALL_CHANGED', stage, role)
        if _identity(info) != _identity(os.lstat(path)):
            _fail('REINSTALL_CHANGED', stage, role)
        _sync(path.parent)
        return _identity(info)
    except BaseException:
        # Remove only this still-owned creation, never a replaced path.
        try:
            current = os.lstat(path)
            if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                path.unlink(); _sync(path.parent)
        except OSError:
            pass
        raise
    finally:
        os.close(fd)


def _guard_exact(path, expected, digest, stage, role):
    body, identity = _read(path, stage, role)
    if identity != expected or _sha(body) != digest:
        _fail('REINSTALL_CHANGED', stage, role)
    return body


def _managed(h, plan, content):
    return {str(h.INSTALL / plan['ops_commit'] / name) for name in
        (*h.SCRIPTS, *h.COORDINATORS.values(), h.INTERPRETER)} | {
        str(h.UNITS / name) for name in content if name.endswith(('.service', '.timer'))}


def _rolled_back(h, receipt, stage):
    plan, folder, state = h._rollback_state(receipt)
    _, _, content = h._prepared(receipt)
    allowed = _managed(h, plan, content)
    required = {'version', 'operation_id', 'state', 'created_files', 'created_directories',
                'timers_enabled', 'engine_verified', 'interpreter_identity'}
    directories = {str(h.INSTALL / plan['ops_commit']), *(str(p) for p in h.OUTPUTS.values())}
    if (type(state) is not dict or not required <= set(state) or set(state) - required - {'sources'}
            or type(state['version']) is not int or state['version'] != 1
            or state['operation_id'] != receipt['operation_id'] or state['state'] != 'rolled_back'
            or state['timers_enabled'] is not False or state['engine_verified'] is not False
            or type(state['created_files']) is not list or not set(state['created_files']) <= allowed
            or type(state['created_directories']) is not list
            or any(type(p) is not str for p in state['created_directories'])
            or len(set(state['created_directories'])) != len(state['created_directories'])
            or not set(state['created_directories']) <= directories):
        _fail('REINSTALL_JOURNAL', stage, 'journal')
    for name in sorted(allowed | {str(h.INSTALL / plan['ops_commit'])}):
        if os.path.lexists(name):
            _fail('REINSTALL_MANAGED_PRESENT', stage, 'managed_artifact')
    return folder


def _not_started(release):
    path = release.ROOT / 'receipts' / ('preview-start-' + TARGET_COMMIT + '.json')
    if os.path.lexists(path):
        _fail('REINSTALL_ALREADY_STARTED', 'current_state', 'preview_receipt')


def _intent(value, operation_id, binding_sha, preview_sha, receipt):
    keys = {'version', 'operation_id', 'source_commit', 'binding_sha256', 'preview_sha256',
            'prepared_operation_id', 'original_identity', 'previous_identity', 'previous_sha256'}
    if (type(value) is not dict or set(value) != keys or type(value['version']) is not int
            or value['version'] != 1 or value['operation_id'] != operation_id
            or value['source_commit'] != TARGET_COMMIT or value['binding_sha256'] != binding_sha
            or value['preview_sha256'] != preview_sha
            or value['prepared_operation_id'] != receipt['operation_id']
            or type(value['previous_sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}', value['previous_sha256']) is None):
        _fail('REINSTALL_RECEIPT', 'replay', 'intent')
    identity_keys = set(_identity(os.stat_result((0,) * 10)))
    for key in ('original_identity', 'previous_identity'):
        if (type(value[key]) is not dict or set(value[key]) != identity_keys
                or any(type(number) is not int or number < 0 for number in value[key].values())):
            _fail('REINSTALL_RECEIPT', 'replay', 'intent')
    return value


def _result(value, operation_id, intent_sha):
    if (type(value) is not dict or set(value) !=
            {'version', 'operation_id', 'intent_sha256', 'status', 'journal', 'cleanup'}
            or type(value['version']) is not int or value['version'] != 1
            or value['operation_id'] != operation_id or value['intent_sha256'] != intent_sha
            or _label(value['status'], ('verified', 'failed'), None) is None
            or _label(value['cleanup'], ('not_needed', 'rolled_back', 'failed'), None) is None):
        _fail('REINSTALL_RECEIPT', 'replay', 'result')
    if value['status'] == 'verified' and (type(value['journal']) is not dict or
            set(value['journal']) != {'identity', 'sha256'}):
        _fail('REINSTALL_RECEIPT', 'replay', 'result')
    if value['status'] == 'failed' and value['journal'] is not None:
        _fail('REINSTALL_RECEIPT', 'replay', 'result')
    return value


def _attempts(folder, operation_id):
    names = list(folder.iterdir())
    if len(names) > 256:
        _fail('REINSTALL_RECEIPT', 'lock', 'intent')
    attempts = []
    for path in names:
        if not path.name.startswith('reinstall-'):
            continue
        match = re.fullmatch(r'reinstall-([0-9a-f]{32})\.(previous|intent|result)\.json', path.name)
        if match is None:
            _fail('REINSTALL_RECEIPT', 'lock', 'intent')
        if match[2] == 'intent':
            attempts.append((match[1], path))
    if len(attempts) > MAX_ATTEMPTS:
        _fail('REINSTALL_RECEIPT', 'lock', 'intent')
    for identity, path in attempts:
        if identity == operation_id:
            continue
        body, _ = _read(path, 'lock', 'intent')
        result_path = folder / ('reinstall-' + identity + '.result.json')
        if not os.path.lexists(result_path):
            _fail('REINSTALL_PENDING', 'lock', 'intent')
        _result(_decode(_read(result_path, 'lock', 'result')[0], 'lock', 'result'), identity, _sha(body))


def _public(operation_id, replay):
    return dict(ok=True, stage='exports_reinstall', status='already_verified' if replay else 'installed',
        operation_id=operation_id, exports_verified=True, previous_attempt_preserved=True,
        export_jobs_started=not replay, services_started=False, engine_changed=False,
        database_writes=False, source_writes=True, coordination_files_may_change=True, network_calls=0)


def reinstall(C, E, h, release, host, lifecycle, upgrade, *, helper_source, scripts, operation_id):
    """Reinstall one exact rolled-back companion; never prepare or apply a release."""
    stage = 'input'; binding = None; original_fd = None; lock_fd = None
    install_started = False; original_removed = False; previous = None; result_path = None
    try:
        C.require_pins(); E.require_pins()
        if C.OLD_COMMIT != OLD_COMMIT or C.TARGET_COMMIT != TARGET_COMMIT:
            _fail('REINSTALL_PIN', stage)
        if type(operation_id) is not str or re.fullmatch('[0-9a-f]{32}', operation_id) is None:
            _fail('REINSTALL_INPUT', stage)
        if os.geteuid() != ROOT_UID:
            _fail('REINSTALL_ROOT', stage)
        # Constructor validates the helper and script pins before receipt/host IO.
        binding = E.Binding(C, h, release, helper_source, scripts)
        stage = 'prepared'; release.trusted_dir(release.ROOT / 'receipts', mode=0o700)
        preview_path = release.ROOT / 'receipts' / ('preview-' + TARGET_COMMIT + '.json')
        preview_raw, preview_identity = _read(preview_path, stage, 'preview_receipt')
        preview = _decode(preview_raw, stage, 'preview_receipt')
        if type(preview) is not dict or type(preview.get('package')) is not dict:
            _fail('REINSTALL_RECEIPT', stage, 'preview_receipt')
        package = dict(preview['package'], operation='code-prepare')
        C.validate_package(package, release)
        target_path, target_manifest = upgrade.manifest(release, TARGET_COMMIT, package)
        if target_manifest != preview:
            _fail('REINSTALL_CHANGED', stage, 'preview_receipt')
        binding_raw, binding_identity = _read(binding.path, stage, 'binding_receipt')
        binding.load(package, verify=False)
        _, folder, _ = h._prepared(binding.receipt)
        stage = 'current_state'; _not_started(release)
        old = C.current_state(package, host, release, lifecycle, upgrade)
        C.compatible_source(old[0], target_path, upgrade)

        def current():
            _not_started(release)
            _guard_exact(preview_path, preview_identity, _sha(preview_raw), 'current_state', 'preview_receipt')
            _guard_exact(binding.path, binding_identity, _sha(binding_raw), 'current_state', 'binding_receipt')
            if C.current_state(package, host, release, lifecycle, upgrade) != old:
                _fail('REINSTALL_CURRENT_STATE', 'current_state')
            path, manifest = upgrade.manifest(release, TARGET_COMMIT, package)
            if path != target_path or manifest != target_manifest:
                _fail('REINSTALL_CHANGED', 'current_state', 'preview_receipt')
            h._prepared(binding.receipt)

        stage = 'lock'; lock_path = folder / 'reinstall.lock'
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        _check(os.fstat(lock_fd), stage, 'lock', maximum=0)
        if _identity(os.fstat(lock_fd)) != _identity(os.lstat(lock_path)):
            _fail('REINSTALL_CHANGED', stage, 'lock')
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _fail('REINSTALL_BUSY', stage, 'lock')
        _sync(folder); current(); _attempts(folder, operation_id)
        prefix = 'reinstall-' + operation_id
        previous_path = folder / (prefix + '.previous.json')
        intent_path = folder / (prefix + '.intent.json')
        result_path = folder / (prefix + '.result.json')
        journal_path = folder / 'installed.json'
        if os.path.lexists(intent_path):
            stage = 'replay'; intent_raw, _ = _read(intent_path, stage, 'intent')
            intent = _intent(_decode(intent_raw, stage, 'intent'), operation_id,
                _sha(binding_raw), _sha(preview_raw), binding.receipt)
            _guard_exact(previous_path, intent['previous_identity'], intent['previous_sha256'], stage, 'previous_journal')
            result = None
            if os.path.lexists(result_path):
                result = _result(_decode(_read(result_path, stage, 'result')[0], stage, 'result'),
                                 operation_id, _sha(intent_raw))
                if result['status'] != 'verified':
                    _fail('REINSTALL_PREVIOUS_ATTEMPT', stage, 'result')
                _guard_exact(journal_path, result['journal']['identity'], result['journal']['sha256'], stage, 'journal')
            raw, identity = _read(journal_path, stage, 'journal')
            state = _decode(raw, stage, 'journal')
            if identity == intent['original_identity'] or state.get('state') != 'installed':
                _fail('REINSTALL_UNCONFIRMED', stage, 'journal')
            binding.load(package, verify=True); current()
            if result is None:
                _create(result_path, _json(dict(version=1, operation_id=operation_id,
                    intent_sha256=_sha(intent_raw), status='verified',
                    journal=dict(identity=identity, sha256=_sha(raw)), cleanup='not_needed')), 'result', 'result')
            return _public(operation_id, True)
        if os.path.lexists(previous_path) or os.path.lexists(result_path):
            _fail('REINSTALL_PREVIOUS_ATTEMPT', 'replay', 'previous_journal')
        stage = 'journal'; _rolled_back(h, binding.receipt, stage)
        previous, original_identity, original_fd = _read(journal_path, stage, 'journal', keep=True)
        stage = 'previous_copy'
        previous_identity = _create(previous_path, previous, stage, 'previous_journal')
        intent = dict(version=1, operation_id=operation_id, source_commit=TARGET_COMMIT,
            binding_sha256=_sha(binding_raw), preview_sha256=_sha(preview_raw),
            prepared_operation_id=binding.receipt['operation_id'], original_identity=original_identity,
            previous_identity=previous_identity, previous_sha256=_sha(previous))
        stage = 'intent'; intent_raw = _json(intent)
        _create(intent_path, intent_raw, stage, 'intent')
        current(); _rolled_back(h, binding.receipt, 'journal_remove')
        _guard_exact(previous_path, previous_identity, _sha(previous), 'journal_remove', 'previous_journal')
        _guard_exact(journal_path, original_identity, _sha(previous), 'journal_remove', 'journal')
        if _identity(os.fstat(original_fd)) != original_identity:
            _fail('REINSTALL_CHANGED', 'journal_remove', 'journal')
        stage = 'journal_remove'; journal_path.unlink(); original_removed = True; _sync(folder)
        stage = 'install'; install_started = True; binding.install()
        stage = 'verify'; binding.load(package, verify=True); current()
        journal_raw, journal_identity = _read(journal_path, stage, 'journal')
        stage = 'result'
        _create(result_path, _json(dict(version=1, operation_id=operation_id,
            intent_sha256=_sha(intent_raw), status='verified',
            journal=dict(identity=journal_identity, sha256=_sha(journal_raw)), cleanup='not_needed')), stage, 'result')
        return _public(operation_id, False)
    except Exception as error:
        cleanup = 'not_needed'
        if original_removed:
            cleanup = 'failed'
            try:
                if os.path.lexists(folder / 'installed.json'):
                    binding.rollback()
                else:
                    # Installer rejected before creating its own journal. Restore
                    # the old rolled-back metadata, never a running install.
                    _create(folder / 'installed.json', previous, 'result', 'journal')
                _rolled_back(h, binding.receipt, 'result')
                cleanup = 'rolled_back'
            except Exception:
                pass
        if install_started and result_path is not None and not os.path.lexists(result_path):
            try:
                _create(result_path, _json(dict(version=1, operation_id=operation_id,
                    intent_sha256=_sha(intent_raw), status='failed', journal=None, cleanup=cleanup)), 'result', 'result')
            except Exception:
                pass
        if isinstance(error, ReinstallInvalid):
            error.failure_details['cleanup'] = cleanup
            raise
        code = 'REINSTALL_INSTALL_FAILED' if install_started else 'REINSTALL_FAILED'
        role = 'none'
        if isinstance(error, FileNotFoundError):
            code = 'REINSTALL_MISSING'
            role = ('prepared_artifact' if stage in ('prepared', 'current_state') else
                    'managed_artifact' if stage in ('install', 'verify') else 'journal')
        raise ReinstallInvalid(code, stage, role, cause=error, cleanup=cleanup) from None
    finally:
        if original_fd is not None:
            os.close(original_fd)
        if lock_fd is not None:
            os.close(lock_fd)
