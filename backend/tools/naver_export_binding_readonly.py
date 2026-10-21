"""Fixed existing-export Binding diagnosis with bounded current market invocation hints. No release or exporter execution."""
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import time
import stat
import subprocess
import types
ROOT = Path('/srv/metainc/ad-deploy-staging')
EXPORT_SOURCE = 'e7649acfc71c25d7ae9c981a6ba036b77d97897b'
OPERATING_SOURCE = '21cd739cf171c066b84683b24e3340feda495858'
PACKAGE = {'operation': 'code-prepare', 'baseline': '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76', 'source_commit': EXPORT_SOURCE, 'source_tar_gz_sha256': '7d02a455ff2b8b2e2bbcd598b71f5e06ffe8e9d2099f08a2e87a8ea10cbae872', 'ciphertext_sha256': '5f7bcd5b0399603b75de806ce3332be5d89997aca8c06db8807f2d6f23019416', 'run_id': '38198428850'}
SOURCE_PINS = {'exports_binding': '1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed', 'exports_helper': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737', 'product_exporter': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59', 'market_exporter': 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8'}
EXPORT_CODES = frozenset('EXPORT_ALREADY_ATTEMPTED EXPORT_BUNDLE_INVALID EXPORT_BUNDLE_STALE EXPORT_COMMAND_FAILED EXPORT_DATABASE_NAME EXPORT_DIRECTORY_POLICY EXPORT_FILE_CHANGED EXPORT_FILE_POLICY EXPORT_IDENTITY EXPORT_IDENTITY_CHANGED EXPORT_INSTALLED_CHANGED EXPORT_INSTALL_CONFLICT EXPORT_JOURNAL EXPORT_OPERATION EXPORT_OUTPUT_CONFLICT EXPORT_PATH EXPORT_PIN EXPORT_PREPARED_CHANGED EXPORT_PROFILE EXPORT_PYTHON EXPORT_RECEIPT EXPORT_ROLLBACK_DRIFT EXPORT_ROOT_REQUIRED EXPORT_RUN_NOT_VERIFIED EXPORT_SOURCE_CHANGED EXPORT_SOURCE_PATH EXPORT_SOURCE_SCOPE EXPORT_SOURCE_SYMLINK EXPORT_SYMLINK EXPORT_TIME'.split())
LOCAL_CODES = frozenset(('DIAGNOSTIC_PIN', 'DIAGNOSTIC_SOURCE', 'DIAGNOSTIC_EXISTING_DIRECTORY', 'DIAGNOSTIC_EXISTING_FILE', 'DIAGNOSTIC_RECEIPT', 'DIAGNOSTIC_COMMAND', 'DIAGNOSTIC_COMMAND_FAILED', 'DIAGNOSTIC_COMMAND_OUTPUT', 'DIAGNOSTIC_PATH', 'DIAGNOSTIC_READ_CHANGED', 'DIAGNOSTIC_RESULT'))
KINDS = frozenset(('ExportInstallInvalid', 'ValueError', 'RuntimeError', 'FileNotFoundError', 'PermissionError', 'OSError', 'JSONDecodeError', 'KeyError', 'TypeError', 'TimeoutExpired'))
PHASES = ('pins', 'modules', 'operating_receipt', 'construction', 'prepared', 'verify', 'complete')
COMPONENTS = frozenset(('construction', 'prepared_artifact', 'source_identity', 'installed_receipt', 'installed_artifact', 'product_result', 'product_reader_result', 'market_result', 'market_reader_result', 'product_timer_enabled', 'product_timer_active', 'market_timer_enabled', 'market_timer_active', 'product_bundle', 'market_bundle', 'unclassified'))
UNITS = {'product': 'naver-product-export.service', 'product_reader': 'naver-product-export-reader.service', 'market': 'naver-market-export.service', 'market_reader': 'naver-market-export-reader.service'}
TIMERS = {kind: 'naver-' + kind + '-export.timer' for kind in ('product', 'market')}
MAX_PUBLIC_SOURCE = 160000
MAX_RECEIPT = 32768
MAX_OUTPUT = 4096

def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DIAGNOSTIC_RECEIPT')
        result[key] = value
    return result

def require_pins(sources):
    if type(PACKAGE['ciphertext_sha256']) is not str or re.fullmatch('[0-9a-f]{64}', PACKAGE['ciphertext_sha256']) is None:
        raise ValueError('DIAGNOSTIC_PIN')
    if type(sources) is not dict or set(sources) != set(SOURCE_PINS):
        raise ValueError('DIAGNOSTIC_SOURCE')
    for role, pin in SOURCE_PINS.items():
        body = sources[role]
        if type(body) is not bytes or not 0 < len(body) <= MAX_PUBLIC_SOURCE or hashlib.sha256(body).hexdigest() != pin:
            raise ValueError('DIAGNOSTIC_SOURCE')

def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

def existing_directory(path, *, uid=0, gid=0, mode=448, new=False):
    """Match original existing-dir policy; explicitly reject its mutation option."""
    path = Path(path)
    if new or not path.is_absolute() or path.resolve() != path:
        raise ValueError('DIAGNOSTIC_EXISTING_DIRECTORY')
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, mode):
        raise ValueError('DIAGNOSTIC_EXISTING_DIRECTORY')

def existing_private_file(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('DIAGNOSTIC_EXISTING_FILE')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink) != (0, 0, 384, 1):
        raise ValueError('DIAGNOSTIC_EXISTING_FILE')

def _read_operating_receipt():
    """Fixed non-secret deployment receipt only; never SECRET_ROOT or main DB."""
    for folder in (ROOT, ROOT / 'receipts'):
        existing_directory(folder)
    path = ROOT / 'receipts' / ('preview-start-' + OPERATING_SOURCE + '.json')
    existing_private_file(path)
    before = _identity(path.lstat())
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if _identity(info) != before or not 0 < info.st_size <= MAX_RECEIPT:
            raise ValueError('DIAGNOSTIC_EXISTING_FILE')
        chunks, size = ([], 0)
        while size <= MAX_RECEIPT:
            chunk = os.read(fd, min(4096, MAX_RECEIPT + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > MAX_RECEIPT or _identity(os.fstat(fd)) != before or _identity(path.lstat()) != before:
            raise ValueError('DIAGNOSTIC_READ_CHANGED')
        value = json.loads(b''.join(chunks), object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('DIAGNOSTIC_RECEIPT')))
    finally:
        os.close(fd)
    if type(value) is not dict or value.get('ok') is not True or value.get('stage') != 'internal_ready' or (value.get('source_commit') != OPERATING_SOURCE) or (value.get('previous_commit') != '513e52eaee4d1bb722461961639cd588df9080cd') or (value.get('operation_id') != 'b934741699a949a0856ad4114d7bc11a') or (value.get('database_policy') != 'preserve-in-place') or (value.get('execution_enabled') is not False):
        raise ValueError('DIAGNOSTIC_RECEIPT')
    return True

def _command_shape(args):
    if type(args) is not list or any((type(item) is not str for item in args)):
        raise ValueError('DIAGNOSTIC_COMMAND')
    for role, unit in UNITS.items():
        if args == ['systemctl', 'show', unit, '--property=Result', '--property=ExecMainStatus']:
            return (role, 'result')
    for role, timer in TIMERS.items():
        for action in ('is-enabled', 'is-active'):
            if args == ['systemctl', action, timer]:
                return (role, action)
    raise ValueError('DIAGNOSTIC_COMMAND')

class ReadOnlyRelease:
    ROOT = ROOT
    unique = staticmethod(unique)
    trusted_dir = staticmethod(existing_directory)
    trusted_private_file = staticmethod(existing_private_file)

    def __init__(self):
        self.unit_results = {role: None for role in UNITS}
        self.timer_results = {role: {'enabled': None, 'active': None} for role in TIMERS}

    def command(self, args):
        role, action = _command_shape(args)
        value = subprocess.run(['/usr/bin/systemctl'] + args[1:], capture_output=True, timeout=8, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
        if type(value.returncode) is not int or not 0 <= value.returncode <= 255:
            raise ValueError('DIAGNOSTIC_COMMAND_FAILED')
        if type(value.stdout) is not bytes or type(value.stderr) is not bytes or len(value.stdout) + len(value.stderr) > MAX_OUTPUT:
            raise ValueError('DIAGNOSTIC_COMMAND_OUTPUT')
        if action == 'result':
            try:
                matched = set(value.stdout.decode('ascii').splitlines()) == {'Result=success', 'ExecMainStatus=0'}
            except UnicodeError:
                matched = False
            self.unit_results[role] = value.returncode == 0 and matched
        else:
            self.timer_results[role]['enabled' if action == 'is-enabled' else 'active'] = value.returncode == 0
        if value.returncode:
            raise RuntimeError('DIAGNOSTIC_COMMAND_FAILED')
        return value.stdout

def _load_modules(sources):
    helper = types.ModuleType('fixed_existing_saved_exports')
    binding = types.ModuleType('fixed_existing_exports_binding')
    exec(compile(sources['exports_helper'], '<pinned-export-helper>', 'exec'), helper.__dict__)
    exec(compile(sources['exports_binding'], '<pinned-export-binding>', 'exec'), binding.__dict__)
    binding.require_pins()
    return (binding, helper)

def _closed_error(error, helper=None):
    kind = type(error).__name__
    args = error.args
    code = args[0] if len(args) == 1 and type(args[0]) is str else None
    exact_export = helper is not None and type(error) is helper.ExportInstallInvalid
    if exact_export and code in EXPORT_CODES:
        return ('ExportInstallInvalid', code)
    if type(error) in (ValueError, RuntimeError) and code in LOCAL_CODES:
        return (kind, code)
    return (kind if kind in KINDS else 'OtherError', 'UNRECOGNIZED')

def _failure_component(error, helper):
    """Pinned code objects and original line locations only; no traceback text.

    The helper is byte-pinned before exec. Read only fixed kind/unit equality
    results from matching frames, never stringify a frame, local, path or value.
    No original function or validator is wrapped/changed and no IO is repeated.
    """
    component = 'unclassified'
    current = error.__traceback__
    while current is not None:
        code = current.tb_frame.f_code
        bundle = getattr(helper, '_bundle_summary_for_user', None)
        verify = getattr(helper, 'verify', None)
        prepared = getattr(helper, '_prepared', None)
        if bundle is not None and code is getattr(bundle, '__code__', None):
            kind = current.tb_frame.f_locals.get('kind')
            if type(kind) is str and kind in ('product', 'market'):
                component = kind + '_bundle'
        elif verify is not None and code is getattr(verify, '__code__', None):
            line = current.tb_lineno
            if line in (633, 634):
                component = 'source_identity'
            elif line == 635:
                component = 'installed_receipt'
            elif 639 <= line <= 645:
                component = 'installed_artifact'
            elif 648 <= line <= 652:
                unit = current.tb_frame.f_locals.get('unit')
                for role, fixed in UNITS.items():
                    if type(unit) is str and unit == fixed:
                        component = role + '_result'
            elif line in (654, 655):
                kind = current.tb_frame.f_locals.get('kind')
                if type(kind) is str and kind in ('product', 'market'):
                    component = kind + '_timer_' + ('enabled' if line == 654 else 'active')
        elif prepared is not None and code is getattr(prepared, '__code__', None):
            if component == 'unclassified':
                component = 'prepared_artifact'
        elif component == 'unclassified':
            for name in ('build_plan', 'artifacts', 'render_companion', '_coordinator_source'):
                function = getattr(helper, name, None)
                if function is not None and code is getattr(function, '__code__', None):
                    component = 'construction'
        current = current.tb_next
    return component

def _underlying_export_code(error, helper, component):
    context = error.__context__
    if component not in ('product_bundle', 'market_bundle') or type(error) is not helper.ExportInstallInvalid or error.args != ('EXPORT_BUNDLE_INVALID',) or (type(context) is not helper.ExportInstallInvalid):
        return None
    args = context.args
    if len(args) == 1 and type(args[0]) is str and (args[0] in EXPORT_CODES):
        return args[0]
    return None
ERROR_PATTERNS = (('permission_error', '\\bPermissionError\\b'), ('permission_denied', '\\b(?:permission denied|access denied)\\b'), ('python_cannot_open', "\\b(?:python[0-9.]*|python-export): can't open file\\b"), ('statvfs', '\\bstatvfs\\b'), ('namespace', 'failed at step namespace|failed to set up mount namespacing'), ('export_failed', '\\bEXPORT_FAILED\\b'), ('readonly', 'read-only file system|attempt to write a readonly database'), ('sqlite_open', 'unable to open database file'), ('missing_file', 'no such file or directory|not a directory'), ('network_namespace', 'failed to set up network namespacing|failed at step network'), ('group_setup', 'failed at step group|failed to (?:set up|determine) (?:supplementary )?group'), ('user_setup', 'failed at step user|failed to (?:set up|determine) user'), ('stdout_setup', 'failed at step std(?:out|err|in)|failed to set up standard (?:input|output|error)'), ('execution_setup', 'failed at step exec|failed to execute'), ('directory_setup', 'failed at step chdir|failed to change (?:root|working) directory'), ('capability_setup', 'failed at step capabilities|failed to apply capabilities'), ('seccomp_setup', 'failed at step seccomp|failed to apply syscall'), ('apparmor_setup', 'failed at step apparmor|failed to apply apparmor'), ('cgroup_setup', 'failed to (?:attach to|create) cgroup'), ('python_module_missing', '\\bModuleNotFoundError\\b|\\bNo module named\\b'), ('python_import_error', '\\bImportError\\b|\\bcannot import name\\b'), ('python_fatal', '\\bFatal Python error:'), ('python_stdlib_init', 'could not find platform (?:in)?dependent libraries|\\b(?:init_fs_encoding|init_import_site|init_importlib):|failed to get the Python codec|failed to (?:import|initialize) (?:site|encodings)\\b'), ('dynamic_loader', 'error while loading shared libraries|cannot open shared object file|\\bsymbol lookup error\\b|\\bundefined symbol:|\\bbad ELF interpreter\\b'), ('binary_format', '\\bexec format error\\b|cannot execute binary file|wrong ELF class|invalid ELF header'))
EXPORTER_FAILURE_LABELS = {'SOURCE_READ': 'export_source_read', 'SOURCE_PATH': 'export_source_path', 'SOURCE_LIMIT': 'export_source_limit', 'SOURCE_JSON': 'export_source_json', 'SOURCE_STATE': 'export_source_state', 'OUTPUT_WRITE': 'export_output_write', 'OUTPUT_PATH': 'export_output_path', 'EXPORT_INVALID': 'export_invalid', 'EXPORT_LIMIT': 'export_limit', 'EXPORT_FAILED': 'export_failed'}
SQLITE_SOURCE_LABELS = {'readonly': 'sqlite_readonly', 'sqlite_open': 'sqlite_open', 'schema': 'sqlite_schema', 'authorized': 'sqlite_authorization', 'locked': 'sqlite_locked', 'corrupt': 'sqlite_corrupt', 'unknown': 'sqlite_unknown'}
COORDINATION_FAILURE_LABELS = {'COORDINATION_SOURCE_OPEN': 'coordination_source_open', 'COORDINATION_READER_FAILED': 'coordination_reader_failed', 'COORDINATION_TIMEOUT': 'coordination_timeout', 'COORDINATION_INVALID': 'coordination_invalid', 'COORDINATION_READER_STOP_FAILED': 'coordination_reader_stop_failed'}
MARKET_ROLES = ('market', 'market_reader')
UNIT_RESULTS = frozenset(('success', 'resources', 'timeout', 'exit-code', 'signal', 'core-dump', 'watchdog', 'start-limit-hit', 'protocol', 'exec-condition', 'oom-kill', 'unknown'))
ACTIVE_STATES = frozenset(('inactive', 'active', 'reloading', 'failed', 'activating', 'deactivating', 'maintenance', 'unknown'))
SUB_STATES = frozenset(('dead', 'condition', 'start-pre', 'start', 'start-post', 'running', 'exited', 'reload', 'stop', 'stop-watchdog', 'stop-sigterm', 'stop-sigkill', 'stop-post', 'final-watchdog', 'final-sigterm', 'final-sigkill', 'failed', 'auto-restart', 'cleaning', 'unknown'))
MARKET_STATUSES = frozenset(('observed', 'no_invocation', 'context_changed', 'limited', 'invalid', 'unavailable'))
JOURNAL_STATUSES = frozenset(('not_read', 'observed', 'empty', 'context_changed', 'limited', 'invalid', 'unavailable'))
UNIT_PROPERTIES = ('Result', 'ExecMainStatus', 'ActiveState', 'SubState', 'InvocationID')

def _market_command_limit(args):
    if type(args) is not list or any((type(item) is not str for item in args)):
        raise ValueError('DIAGNOSTIC_COMMAND')
    for role in MARKET_ROLES:
        unit = UNITS[role]
        if args == ['/usr/bin/systemctl', 'show', unit] + ['--property=' + name for name in UNIT_PROPERTIES]:
            return 4096
        prefix = ['/usr/bin/journalctl', '--output=json', '--no-pager', '-n', '32', '_SYSTEMD_UNIT=' + unit]
        if len(args) == len(prefix) + 1 and args[:-1] == prefix and re.fullmatch('_SYSTEMD_INVOCATION_ID=[0-9a-f]{32}', args[-1]) and (args[-1] != '_SYSTEMD_INVOCATION_ID=' + '0' * 32):
            return 32768
    raise ValueError('DIAGNOSTIC_COMMAND')

def _market_command(args):
    maximum = _market_command_limit(args)
    deadline = time.monotonic() + 8
    process = None
    selector = selectors.DefaultSelector()
    try:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, close_fds=True, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})
        selector.register(process.stdout, selectors.EVENT_READ)
        chunks, size = ([], 0)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                return (None, 'unavailable')
            chunk = os.read(process.stdout.fileno(), min(4096, maximum + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum:
                return (None, 'limited')
        remaining = deadline - time.monotonic()
        if remaining <= 0 or process.wait(timeout=remaining) != 0:
            return (None, 'unavailable')
        return (b''.join(chunks), None)
    except (OSError, subprocess.SubprocessError, ValueError):
        return (None, 'unavailable')
    finally:
        selector.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
            if process.stdout is not None:
                process.stdout.close()
            try:
                process.wait(timeout=1)
            except (OSError, subprocess.SubprocessError):
                pass

def _market_snapshot(raw):
    if type(raw) is not bytes or len(raw) > 4096:
        raise ValueError('DIAGNOSTIC_COMMAND_OUTPUT')
    pairs = [line.split('=', 1) for line in raw.decode('ascii').splitlines()]
    if any((len(pair) != 2 for pair in pairs)):
        raise ValueError('DIAGNOSTIC_COMMAND_OUTPUT')
    values = unique(pairs)
    if set(values) != set(UNIT_PROPERTIES) or re.fullmatch('0|[1-9][0-9]{0,2}', values['ExecMainStatus']) is None:
        raise ValueError('DIAGNOSTIC_COMMAND_OUTPUT')
    if not 0 <= int(values['ExecMainStatus']) <= 255:
        raise ValueError('DIAGNOSTIC_COMMAND_OUTPUT')
    invocation = values['InvocationID']
    if invocation not in ('', '0' * 32) and re.fullmatch('[0-9a-f]{32}', invocation) is None:
        raise ValueError('DIAGNOSTIC_COMMAND_OUTPUT')
    return values

def _market_labels(message):
    labels = [label for label, pattern in ERROR_PATTERNS if re.search(pattern, message, flags=re.IGNORECASE)]
    try:
        value = json.loads(message, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NUMBER')))
        if type(value) is dict and set(value) == {'status', 'code'} and (value['status'] == 'failed') and (type(value['code']) is str):
            label = EXPORTER_FAILURE_LABELS.get(value['code']) or COORDINATION_FAILURE_LABELS.get(value['code'])
            if label and label not in labels:
                labels.append(label)
        elif type(value) is dict and set(value) == {'status', 'code', 'source_issue'} and (value['status'] == 'failed') and (value['code'] == 'SOURCE_READ') and (type(value['source_issue']) is str) and (value['source_issue'] in SQLITE_SOURCE_LABELS):
            labels.extend((label for label in ('export_source_read', SQLITE_SOURCE_LABELS[value['source_issue']]) if label not in labels))
    except (ValueError, TypeError, RecursionError):
        pass
    return labels

def _market_journal(raw, role, invocation):
    if type(raw) is not bytes or len(raw) > 32768:
        return ('limited', 0, [])
    lines = raw.splitlines()
    if len(lines) > 32:
        return ('limited', 0, [])
    labels = set()
    try:
        for line in lines:
            value = json.loads(line, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NUMBER')))
            if type(value) is not dict or value.get('_SYSTEMD_UNIT') != UNITS[role] or value.get('_SYSTEMD_INVOCATION_ID') != invocation or (type(value.get('MESSAGE')) is not str):
                raise ValueError('RECORD')
            message = value['MESSAGE']
            if any((ord(char) < 32 and char not in '\t\r\n' for char in message)):
                raise ValueError('RECORD')
            labels.update(_market_labels(message))
        return ('observed' if lines else 'empty', len(lines), sorted(labels))
    except (ValueError, UnicodeError, TypeError, KeyError, RecursionError):
        return ('invalid', 0, [])

def _market_empty():
    return {'status': 'unavailable', 'unit_result': 'unknown', 'exit_status': None, 'active_state': 'unknown', 'sub_state': 'unknown', 'invocation_present': False, 'same_invocation': False, 'journal_status': 'not_read', 'journal_records': 0, 'error_labels': []}

def _market_unit(role):
    result = _market_empty()
    args = ['/usr/bin/systemctl', 'show', UNITS[role]] + ['--property=' + name for name in UNIT_PROPERTIES]
    raw, error = _market_command(args)
    if error:
        result['status'] = error
        return result
    try:
        before = _market_snapshot(raw)
    except (ValueError, UnicodeError):
        result['status'] = 'invalid'
        return result
    result.update(unit_result=before['Result'] if before['Result'] in UNIT_RESULTS else 'unknown', exit_status=int(before['ExecMainStatus']), active_state=before['ActiveState'] if before['ActiveState'] in ACTIVE_STATES else 'unknown', sub_state=before['SubState'] if before['SubState'] in SUB_STATES else 'unknown')
    invocation = before['InvocationID']
    if invocation in ('', '0' * 32):
        result['status'] = 'no_invocation'
        return result
    result['invocation_present'] = True
    if role == 'market' and before['Result'] == 'success' and (before['ExecMainStatus'] == '0'):
        result['status'] = 'context_changed'
        return result
    raw, error = _market_command(['/usr/bin/journalctl', '--output=json', '--no-pager', '-n', '32', '_SYSTEMD_UNIT=' + UNITS[role], '_SYSTEMD_INVOCATION_ID=' + invocation])
    journal, count, labels = (error, 0, []) if error else _market_journal(raw, role, invocation)
    after_raw, after_error = _market_command(args)
    try:
        same = after_error is None and _market_snapshot(after_raw) == before
    except (ValueError, UnicodeError):
        same = False
    if not same:
        result.update(status='context_changed', journal_status='context_changed')
        return result
    result.update(status='observed' if journal in ('observed', 'empty') else journal, same_invocation=True, journal_status=journal, journal_records=count, error_labels=labels)
    return result

def _market_failure_observation():
    result = {'trigger': 'market_result_EXPORT_RUN_NOT_VERIFIED', 'reader_pairing': 'not_proven', 'journal_coverage': 'last_32_records_per_unit'}
    for role in MARKET_ROLES:
        try:
            result[role] = _market_unit(role)
        except Exception:
            result[role] = _market_empty()
    return result

def _validate_market_failure(value):
    if type(value) is not dict or set(value) != {'trigger', 'reader_pairing', 'journal_coverage', 'market', 'market_reader'}:
        raise ValueError('DIAGNOSTIC_RESULT')
    if value['trigger'] != 'market_result_EXPORT_RUN_NOT_VERIFIED' or value['reader_pairing'] != 'not_proven' or value['journal_coverage'] != 'last_32_records_per_unit':
        raise ValueError('DIAGNOSTIC_RESULT')
    allowed = {label for label, _ in ERROR_PATTERNS} | set(EXPORTER_FAILURE_LABELS.values()) | set(SQLITE_SOURCE_LABELS.values()) | set(COORDINATION_FAILURE_LABELS.values())
    for role in MARKET_ROLES:
        row = value[role]
        if type(row) is not dict or set(row) != {'status', 'unit_result', 'exit_status', 'active_state', 'sub_state', 'invocation_present', 'same_invocation', 'journal_status', 'journal_records', 'error_labels'} or row['status'] not in MARKET_STATUSES or (row['unit_result'] not in UNIT_RESULTS) or (row['active_state'] not in ACTIVE_STATES) or (row['sub_state'] not in SUB_STATES) or (row['journal_status'] not in JOURNAL_STATUSES) or any((type(row[key]) is not bool for key in ('invocation_present', 'same_invocation'))) or (row['exit_status'] is not None and (type(row['exit_status']) is not int or not 0 <= row['exit_status'] <= 255)) or (type(row['journal_records']) is not int) or (not 0 <= row['journal_records'] <= 32) or (type(row['error_labels']) is not list) or any((type(label) is not str or label not in allowed for label in row['error_labels'])) or (row['error_labels'] != sorted(set(row['error_labels']))) or (row['error_labels'] and (not row['same_invocation'] or row['journal_status'] != 'observed')):
            raise ValueError('DIAGNOSTIC_RESULT')

def _observe(binding_module, helper, sources, release, operating_receipt_check):
    """Test seam; production caller must enter diagnose() to enforce source pins."""
    phase, helper_loaded, receipt_match = ('operating_receipt', True, False)
    result = {'version': 1, 'diagnostic': 'existing-export-binding-readonly', 'observation': 'current-not-past-prepare-replay', 'operating_source': OPERATING_SOURCE, 'export_source': EXPORT_SOURCE, 'operating_receipt_match': False, 'running_container_verified': False, 'base_history_revalidated': False, 'prepare_executed': False, 'apply_executed': False, 'incoming_executed': False, 'database_opened': False, 'runtime_secret_bodies_read': False, 'services_changed': False, 'provider_calls': 0, 'ad_changes': 0, 'market_failure': None}
    try:
        receipt_match = operating_receipt_check() is True
        if not receipt_match:
            raise ValueError('DIAGNOSTIC_RECEIPT')
        phase = 'construction'
        controller = types.SimpleNamespace(TARGET_COMMIT=EXPORT_SOURCE)
        bound = binding_module.Binding(controller, helper, release, sources['exports_helper'], {'naver_product_export.py': sources['product_exporter'], 'naver_market_export.py': sources['market_exporter']})
        phase = 'prepared'
        bound.load(dict(PACKAGE), verify=False)
        phase = 'verify'
        bound.operation(lambda: helper.verify(bound.receipt, command=bound.command))
        result.update(ok=True, phase='complete', error_kind=None, error_code=None, error_component=None, underlying_export_error_code=None)
    except Exception as error:
        kind, code = _closed_error(error, helper if helper_loaded else None)
        component = _failure_component(error, helper)
        result.update(ok=False, phase=phase, error_kind=kind, error_code=code, error_component=component, underlying_export_error_code=_underlying_export_code(error, helper, component))
        if phase == 'verify' and receipt_match and (kind == 'ExportInstallInvalid') and (code == 'EXPORT_RUN_NOT_VERIFIED') and (component == 'market_result'):
            result['market_failure'] = _market_failure_observation()
    result.update(operating_receipt_match=receipt_match, unit_result_success=release.unit_results, timer_state_success=release.timer_results)
    return result

def diagnose(sources):
    phase = 'pins'
    try:
        require_pins(sources)
        phase = 'modules'
        binding_module, helper = _load_modules(sources)
        return _observe(binding_module, helper, sources, ReadOnlyRelease(), _read_operating_receipt)
    except Exception as error:
        kind, code = _closed_error(error)
        return {'version': 1, 'diagnostic': 'existing-export-binding-readonly', 'ok': False, 'phase': phase, 'error_kind': kind, 'error_code': code, 'error_component': None, 'underlying_export_error_code': None, 'host_observation_started': False}

def closed_json(result):
    """A final allowlisted projection; never serialize modules, receipts or exceptions."""
    common = {'version', 'diagnostic', 'ok', 'phase', 'error_kind', 'error_code', 'error_component', 'underlying_export_error_code'}
    full = common | {'observation', 'operating_source', 'export_source', 'operating_receipt_match', 'running_container_verified', 'base_history_revalidated', 'prepare_executed', 'apply_executed', 'incoming_executed', 'database_opened', 'runtime_secret_bodies_read', 'services_changed', 'provider_calls', 'ad_changes', 'unit_result_success', 'timer_state_success', 'market_failure'}
    short = common | {'host_observation_started'}
    if type(result) is not dict or set(result) not in (full, short) or type(result.get('version')) is not int or (result['version'] != 1) or (result.get('diagnostic') != 'existing-export-binding-readonly') or (type(result.get('ok')) is not bool) or (result.get('phase') not in PHASES):
        raise ValueError('DIAGNOSTIC_RESULT')
    if result['ok']:
        if result['phase'] != 'complete' or any((result[key] is not None for key in ('error_kind', 'error_code', 'error_component', 'underlying_export_error_code'))):
            raise ValueError('DIAGNOSTIC_RESULT')
    elif result['error_kind'] not in KINDS | {'OtherError'} or result['error_code'] not in EXPORT_CODES | LOCAL_CODES | {'UNRECOGNIZED'} or result['phase'] == 'complete':
        raise ValueError('DIAGNOSTIC_RESULT')
    if set(result) == short:
        if result['host_observation_started'] is not False or result['phase'] not in ('pins', 'modules') or result['ok'] or (result['error_component'] is not None) or (result['underlying_export_error_code'] is not None):
            raise ValueError('DIAGNOSTIC_RESULT')
    else:
        if result['market_failure'] is not None:
            if result['ok'] or result['phase'] != 'verify' or result['error_kind'] != 'ExportInstallInvalid' or (result['error_code'] != 'EXPORT_RUN_NOT_VERIFIED') or (result['error_component'] != 'market_result'):
                raise ValueError('DIAGNOSTIC_RESULT')
            _validate_market_failure(result['market_failure'])
        if not result['ok'] and result['error_component'] not in COMPONENTS:
            raise ValueError('DIAGNOSTIC_RESULT')
        underlying = result['underlying_export_error_code']
        if underlying is not None and (underlying not in EXPORT_CODES or result['error_component'] not in ('product_bundle', 'market_bundle') or result['error_kind'] != 'ExportInstallInvalid' or (result['error_code'] != 'EXPORT_BUNDLE_INVALID')):
            raise ValueError('DIAGNOSTIC_RESULT')
        if result['operating_source'] != OPERATING_SOURCE or result['export_source'] != EXPORT_SOURCE or result['observation'] != 'current-not-past-prepare-replay' or (type(result['operating_receipt_match']) is not bool) or any((result[key] is not False for key in ('running_container_verified', 'base_history_revalidated', 'prepare_executed', 'apply_executed', 'incoming_executed', 'database_opened', 'runtime_secret_bodies_read', 'services_changed'))) or any((type(result[key]) is not int or result[key] != 0 for key in ('provider_calls', 'ad_changes'))):
            raise ValueError('DIAGNOSTIC_RESULT')
        units, timers = (result['unit_result_success'], result['timer_state_success'])
        if type(units) is not dict or set(units) != set(UNITS) or any((value is not None and type(value) is not bool for value in units.values())) or (type(timers) is not dict) or (set(timers) != set(TIMERS)):
            raise ValueError('DIAGNOSTIC_RESULT')
        for item in timers.values():
            if type(item) is not dict or set(item) != {'enabled', 'active'} or any((value is not None and type(value) is not bool for value in item.values())):
                raise ValueError('DIAGNOSTIC_RESULT')
    raw = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(raw.encode()) > MAX_OUTPUT:
        raise ValueError('DIAGNOSTIC_RESULT')
    return raw
if __name__ == '__main__':
    raise SystemExit('DIAGNOSTIC_PINNED_CALLER_REQUIRED')
