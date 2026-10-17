"""Draft: inspect the existing saved-export Binding; never run a release.

No CLI. The independently pinned caller supplies exactly four public sources.
This is a current read-only observation, not a replay of prepare38992669442.
Base/history manifest validation is deliberately NOT repeated: it reads runtime
secret bodies. Its earlier success is only historical evidence. No gate is
changed or bypassed, because this function cannot prepare/apply/install anything.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import types

ROOT = Path('/srv/metainc/ad-deploy-staging')
EXPORT_SOURCE = 'e7649acfc71c25d7ae9c981a6ba036b77d97897b'
OPERATING_SOURCE = '21cd739cf171c066b84683b24e3340feda495858'
PACKAGE = {
    'operation': 'code-prepare',
    'baseline': '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
    'source_commit': EXPORT_SOURCE,
    'source_tar_gz_sha256': '7d02a455ff2b8b2e2bbcd598b71f5e06ffe8e9d2099f08a2e87a8ea10cbae872',
    'ciphertext_sha256': '5f7bcd5b0399603b75de806ce3332be5d89997aca8c06db8807f2d6f23019416',
    'run_id': '38198428850',
}
SOURCE_PINS = {
    'exports_binding': '1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed',
    'exports_helper': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737',
    'product_exporter': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59',
    'market_exporter': 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8',
}
# Exact reviewed set from naver_preview_completion_release.EXPORT_FAILURE_CODES.
EXPORT_CODES = frozenset('EXPORT_ALREADY_ATTEMPTED EXPORT_BUNDLE_INVALID EXPORT_BUNDLE_STALE '
    'EXPORT_COMMAND_FAILED EXPORT_DATABASE_NAME EXPORT_DIRECTORY_POLICY EXPORT_FILE_CHANGED EXPORT_FILE_POLICY '
    'EXPORT_IDENTITY EXPORT_IDENTITY_CHANGED EXPORT_INSTALLED_CHANGED EXPORT_INSTALL_CONFLICT EXPORT_JOURNAL '
    'EXPORT_OPERATION EXPORT_OUTPUT_CONFLICT EXPORT_PATH EXPORT_PIN EXPORT_PREPARED_CHANGED EXPORT_PROFILE '
    'EXPORT_PYTHON EXPORT_RECEIPT EXPORT_ROLLBACK_DRIFT EXPORT_ROOT_REQUIRED EXPORT_RUN_NOT_VERIFIED '
    'EXPORT_SOURCE_CHANGED EXPORT_SOURCE_PATH EXPORT_SOURCE_SCOPE EXPORT_SOURCE_SYMLINK EXPORT_SYMLINK EXPORT_TIME'.split())
LOCAL_CODES = frozenset(('DIAGNOSTIC_PIN', 'DIAGNOSTIC_SOURCE', 'DIAGNOSTIC_EXISTING_DIRECTORY',
    'DIAGNOSTIC_EXISTING_FILE', 'DIAGNOSTIC_RECEIPT', 'DIAGNOSTIC_COMMAND',
    'DIAGNOSTIC_COMMAND_FAILED', 'DIAGNOSTIC_COMMAND_OUTPUT', 'DIAGNOSTIC_PATH',
    'DIAGNOSTIC_READ_CHANGED', 'DIAGNOSTIC_RESULT'))
KINDS = frozenset(('ExportInstallInvalid', 'ValueError', 'RuntimeError', 'FileNotFoundError',
    'PermissionError', 'OSError', 'JSONDecodeError', 'KeyError', 'TypeError', 'TimeoutExpired'))
PHASES = ('pins', 'modules', 'operating_receipt', 'construction', 'prepared', 'verify', 'complete')
COMPONENTS = frozenset(('construction', 'prepared_artifact', 'source_identity',
    'installed_receipt', 'installed_artifact', 'product_result', 'product_reader_result',
    'market_result', 'market_reader_result', 'product_timer_enabled', 'product_timer_active',
    'market_timer_enabled', 'market_timer_active', 'product_bundle', 'market_bundle', 'unclassified'))
UNITS = {
    'product': 'naver-product-export.service',
    'product_reader': 'naver-product-export-reader.service',
    'market': 'naver-market-export.service',
    'market_reader': 'naver-market-export-reader.service',
}
TIMERS = {kind: 'naver-'+kind+'-export.timer' for kind in ('product', 'market')}
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
    if (type(PACKAGE['ciphertext_sha256']) is not str or
            re.fullmatch('[0-9a-f]{64}', PACKAGE['ciphertext_sha256']) is None):
        raise ValueError('DIAGNOSTIC_PIN')
    if type(sources) is not dict or set(sources) != set(SOURCE_PINS):
        raise ValueError('DIAGNOSTIC_SOURCE')
    for role, pin in SOURCE_PINS.items():
        body = sources[role]
        if (type(body) is not bytes or not 0 < len(body) <= MAX_PUBLIC_SOURCE or
                hashlib.sha256(body).hexdigest() != pin):
            raise ValueError('DIAGNOSTIC_SOURCE')


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def existing_directory(path, *, uid=0, gid=0, mode=0o700, new=False):
    """Match original existing-dir policy; explicitly reject its mutation option."""
    path = Path(path)
    if new or not path.is_absolute() or path.resolve() != path:
        raise ValueError('DIAGNOSTIC_EXISTING_DIRECTORY')
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or
            (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, mode)):
        raise ValueError('DIAGNOSTIC_EXISTING_DIRECTORY')


def existing_private_file(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('DIAGNOSTIC_EXISTING_FILE')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or
            (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink) != (0, 0, 0o600, 1)):
        raise ValueError('DIAGNOSTIC_EXISTING_FILE')


def _read_operating_receipt():
    """Fixed non-secret deployment receipt only; never SECRET_ROOT or main DB."""
    for folder in (ROOT, ROOT/'receipts'):
        existing_directory(folder)
    path = ROOT/'receipts'/('preview-start-'+OPERATING_SOURCE+'.json')
    existing_private_file(path)
    before = _identity(path.lstat())
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if _identity(info) != before or not 0 < info.st_size <= MAX_RECEIPT:
            raise ValueError('DIAGNOSTIC_EXISTING_FILE')
        chunks, size = [], 0
        while size <= MAX_RECEIPT:
            chunk = os.read(fd, min(4096, MAX_RECEIPT+1-size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if (size > MAX_RECEIPT or _identity(os.fstat(fd)) != before or
                _identity(path.lstat()) != before):
            raise ValueError('DIAGNOSTIC_READ_CHANGED')
        value = json.loads(b''.join(chunks), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('DIAGNOSTIC_RECEIPT')))
    finally:
        os.close(fd)
    if (type(value) is not dict or value.get('ok') is not True or
            value.get('stage') != 'internal_ready' or value.get('source_commit') != OPERATING_SOURCE or
            value.get('previous_commit') != '513e52eaee4d1bb722461961639cd588df9080cd' or
            value.get('operation_id') != 'b934741699a949a0856ad4114d7bc11a' or
            value.get('database_policy') != 'preserve-in-place' or
            value.get('execution_enabled') is not False):
        raise ValueError('DIAGNOSTIC_RECEIPT')
    # This authenticates the fixed receipt, NOT a current container/running proof.
    return True


def _command_shape(args):
    if type(args) is not list or any(type(item) is not str for item in args):
        raise ValueError('DIAGNOSTIC_COMMAND')
    for role, unit in UNITS.items():
        if args == ['systemctl', 'show', unit, '--property=Result', '--property=ExecMainStatus']:
            return role, 'result'
    for role, timer in TIMERS.items():
        for action in ('is-enabled', 'is-active'):
            if args == ['systemctl', action, timer]:
                return role, action
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
        # No shell/input/network/start/stop/restart/enable/daemon-reload is permitted.
        value = subprocess.run(['/usr/bin/systemctl'] + args[1:], capture_output=True,
            timeout=8, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
        if type(value.returncode) is not int or not 0 <= value.returncode <= 255:
            raise ValueError('DIAGNOSTIC_COMMAND_FAILED')
        if type(value.stdout) is not bytes or type(value.stderr) is not bytes or len(value.stdout)+len(value.stderr) > MAX_OUTPUT:
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
    return binding, helper


def _closed_error(error, helper=None):
    kind = type(error).__name__
    args = error.args
    code = args[0] if len(args) == 1 and type(args[0]) is str else None
    exact_export = helper is not None and type(error) is helper.ExportInstallInvalid
    if exact_export and code in EXPORT_CODES:
        return 'ExportInstallInvalid', code
    if type(error) in (ValueError, RuntimeError) and code in LOCAL_CODES:
        return kind, code
    return kind if kind in KINDS else 'OtherError', 'UNRECOGNIZED'


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
                component = kind+'_bundle'
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
                        component = role+'_result'
            elif line in (654, 655):
                kind = current.tb_frame.f_locals.get('kind')
                if type(kind) is str and kind in ('product', 'market'):
                    component = kind+'_timer_'+('enabled' if line == 654 else 'active')
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
    # The original bundle validator rethrows its own STALE as INVALID. Preserve
    # the outer code and report only the exact reviewed inner enum, never prose.
    context = error.__context__
    if (component not in ('product_bundle', 'market_bundle') or
            type(error) is not helper.ExportInstallInvalid or error.args != ('EXPORT_BUNDLE_INVALID',) or
            type(context) is not helper.ExportInstallInvalid):
        return None
    args = context.args
    if len(args) == 1 and type(args[0]) is str and args[0] in EXPORT_CODES:
        return args[0]
    return None


def _observe(binding_module, helper, sources, release, operating_receipt_check):
    """Test seam; production caller must enter diagnose() to enforce source pins."""
    phase, helper_loaded, receipt_match = 'operating_receipt', True, False
    result = {'version': 1, 'diagnostic': 'existing-export-binding-readonly',
              'observation': 'current-not-past-prepare-replay',
              'operating_source': OPERATING_SOURCE, 'export_source': EXPORT_SOURCE,
              'operating_receipt_match': False, 'running_container_verified': False,
              'base_history_revalidated': False, 'prepare_executed': False,
              'apply_executed': False, 'incoming_executed': False,
              'database_opened': False, 'runtime_secret_bodies_read': False,
              'services_changed': False, 'provider_calls': 0, 'ad_changes': 0}
    try:
        receipt_match = operating_receipt_check() is True
        if not receipt_match:
            raise ValueError('DIAGNOSTIC_RECEIPT')
        phase = 'construction'
        controller = types.SimpleNamespace(TARGET_COMMIT=EXPORT_SOURCE)
        bound = binding_module.Binding(controller, helper, release, sources['exports_helper'], {
            'naver_product_export.py': sources['product_exporter'],
            'naver_market_export.py': sources['market_exporter']})
        phase = 'prepared'
        bound.load(dict(PACKAGE), verify=False)
        phase = 'verify'
        # Same original validator and command path, with only closed readonly commands accepted.
        bound.operation(lambda: helper.verify(bound.receipt, command=bound.command))
        result.update(ok=True, phase='complete', error_kind=None, error_code=None,
                      error_component=None, underlying_export_error_code=None)
    except Exception as error:
        kind, code = _closed_error(error, helper if helper_loaded else None)
        component = _failure_component(error, helper)
        result.update(ok=False, phase=phase, error_kind=kind, error_code=code,
                      error_component=component,
                      underlying_export_error_code=_underlying_export_code(error, helper, component))
    result.update(operating_receipt_match=receipt_match, unit_result_success=release.unit_results,
                  timer_state_success=release.timer_results)
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
        return {'version': 1, 'diagnostic': 'existing-export-binding-readonly',
                'ok': False, 'phase': phase, 'error_kind': kind, 'error_code': code,
                'error_component': None, 'underlying_export_error_code': None,
                'host_observation_started': False}


def closed_json(result):
    """A final allowlisted projection; never serialize modules, receipts or exceptions."""
    common = {'version', 'diagnostic', 'ok', 'phase', 'error_kind', 'error_code',
              'error_component', 'underlying_export_error_code'}
    full = common | {'observation', 'operating_source', 'export_source',
        'operating_receipt_match', 'running_container_verified', 'base_history_revalidated',
        'prepare_executed', 'apply_executed', 'incoming_executed', 'database_opened',
        'runtime_secret_bodies_read', 'services_changed', 'provider_calls', 'ad_changes',
        'unit_result_success', 'timer_state_success'}
    short = common | {'host_observation_started'}
    if (type(result) is not dict or set(result) not in (full, short) or
            type(result.get('version')) is not int or result['version'] != 1 or
            result.get('diagnostic') != 'existing-export-binding-readonly' or
            type(result.get('ok')) is not bool or result.get('phase') not in PHASES):
        raise ValueError('DIAGNOSTIC_RESULT')
    if result['ok']:
        if (result['phase'] != 'complete' or any(result[key] is not None for key in
                ('error_kind', 'error_code', 'error_component', 'underlying_export_error_code'))):
            raise ValueError('DIAGNOSTIC_RESULT')
    elif (result['error_kind'] not in KINDS | {'OtherError'} or
            result['error_code'] not in EXPORT_CODES | LOCAL_CODES | {'UNRECOGNIZED'} or
            result['phase'] == 'complete'):
        raise ValueError('DIAGNOSTIC_RESULT')
    if set(result) == short:
        if (result['host_observation_started'] is not False or result['phase'] not in ('pins', 'modules') or
                result['ok'] or result['error_component'] is not None or result['underlying_export_error_code'] is not None):
            raise ValueError('DIAGNOSTIC_RESULT')
    else:
        if not result['ok'] and result['error_component'] not in COMPONENTS:
            raise ValueError('DIAGNOSTIC_RESULT')
        underlying = result['underlying_export_error_code']
        if (underlying is not None and (underlying not in EXPORT_CODES or
                result['error_component'] not in ('product_bundle', 'market_bundle') or
                result['error_kind'] != 'ExportInstallInvalid' or result['error_code'] != 'EXPORT_BUNDLE_INVALID')):
            raise ValueError('DIAGNOSTIC_RESULT')
        if (result['operating_source'] != OPERATING_SOURCE or result['export_source'] != EXPORT_SOURCE or
                result['observation'] != 'current-not-past-prepare-replay' or
                type(result['operating_receipt_match']) is not bool or
                any(result[key] is not False for key in ('running_container_verified',
                    'base_history_revalidated', 'prepare_executed', 'apply_executed',
                    'incoming_executed', 'database_opened', 'runtime_secret_bodies_read', 'services_changed')) or
                any(type(result[key]) is not int or result[key] != 0 for key in ('provider_calls', 'ad_changes'))):
            raise ValueError('DIAGNOSTIC_RESULT')
        units, timers = result['unit_result_success'], result['timer_state_success']
        if (type(units) is not dict or set(units) != set(UNITS) or
                any(value is not None and type(value) is not bool for value in units.values()) or
                type(timers) is not dict or set(timers) != set(TIMERS)):
            raise ValueError('DIAGNOSTIC_RESULT')
        for item in timers.values():
            if (type(item) is not dict or set(item) != {'enabled', 'active'} or
                    any(value is not None and type(value) is not bool for value in item.values())):
                raise ValueError('DIAGNOSTIC_RESULT')
    raw = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(raw.encode()) > MAX_OUTPUT:
        raise ValueError('DIAGNOSTIC_RESULT')
    return raw


if __name__ == '__main__':
    raise SystemExit('DIAGNOSTIC_PINNED_CALLER_REQUIRED')
