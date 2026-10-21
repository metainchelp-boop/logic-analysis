"""Fixed-pair metadata observation only; no imports from transition modules.

The delivery loader must verify this public module's exact SHA before execution.
These target pins describe scope, not a fresh receipt or source-body validation.
No call executes at import. observe() accepts no arguments or overrides.
"""
import errno
import json
import os
import pwd
import re
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time

APPLY = '7abd8b3965ed4b51a3b071cd218e024f'
ROLLBACK = '4aa3189c384847178ecafbfa34eb060e'
OPERATING_SOURCE = '21cd739cf171c066b84683b24e3340feda495858'
OPERATING_OPERATION = 'b934741699a949a0856ad4114d7bc11a'
SOURCE_PINS = {
    'exports_helper': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737',
    'exports_binding': '1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed',
    'product_exporter': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59',
    'market_exporter': 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8',
}
GLOBAL_SECONDS, COMMAND_SECONDS, MAX_STDOUT, MAX_JSON = 50, 4, 4096, 16384
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
PROPERTIES = ('LoadState', 'UnitFileState', 'FragmentPath', 'DropInPaths', 'Job',
              'Result', 'ExecMainStatus', 'ActiveState', 'SubState', 'InvocationID')
TIMER_PROPERTIES = tuple(x for x in PROPERTIES if x != 'ExecMainStatus')
UNITS = {
    'original_timer': 'naver-market-export.timer',
    'original_coordinator': 'naver-market-export.service',
    'original_reader': 'naver-market-export-reader.service',
    'diagnostic_coordinator': 'naver-market-diagnostic-' + APPLY + '.service',
    'diagnostic_reader': 'naver-market-diagnostic-' + APPLY + '-reader.service',
}
CONTROL = '/var/lib/metainc/naver-market-diagnostic-control'
PREPARATION = CONTROL + '/preparations/' + APPLY
LEDGER = CONTROL + '/ledger'
CODE = '/opt/metainc/naver-market-diagnostic/' + APPLY
OUTPUT = '/var/lib/metainc/naver-market-diagnostic/' + APPLY
UNIT_ROOT, MASK_ROOT = '/etc/systemd/system', '/run/systemd/system.control'
# role -> fixed path, expected kind, expected mode, owner kind.
FILES = {
    'preparation': (PREPARATION, 'directory', 0o700, 'root'),
    'prepared_pending': (PREPARATION + '/prepared.pending', 'regular', 0o600, 'root'),
    'prepared_receipt': (PREPARATION + '/prepared.json', 'regular', 0o600, 'root'),
    'ownership': (PREPARATION + '/ownership', 'directory', 0o700, 'root'),
    'ownership_pending': (PREPARATION + '/ownership/ownership.pending', 'regular', 0o600, 'root'),
    'ownership_receipt': (PREPARATION + '/ownership/ownership.json', 'regular', 0o600, 'root'),
    'ledger_operation': (LEDGER + '/' + APPLY, 'directory', 0o700, 'root'),
    'ledger_plan': (LEDGER + '/' + APPLY + '/plan.json', 'regular', 0o600, 'root'),
    'ledger_first_event': (LEDGER + '/' + APPLY + '/000001.json', 'regular', 0o600, 'root'),
    'pair_reservation': (LEDGER + '/identities/' + APPLY + '.json', 'regular', 0o600, 'root'),
    'code_directory': (CODE, 'directory', 0o755, 'root'),
    'code_market': (CODE + '/naver_market_export.py', 'regular', 0o644, 'root'),
    'code_product': (CODE + '/naver_product_export.py', 'regular', 0o644, 'root'),
    'code_coordinator': (CODE + '/naver_market_coordinate.py', 'regular', 0o644, 'root'),
    'unit_coordinator': (UNIT_ROOT + '/' + UNITS['diagnostic_coordinator'], 'regular', 0o644, 'root'),
    'unit_reader': (UNIT_ROOT + '/' + UNITS['diagnostic_reader'], 'regular', 0o644, 'root'),
    'mask_coordinator': (MASK_ROOT + '/' + UNITS['original_coordinator'], 'symlink', 0o777, 'root'),
    'mask_reader': (MASK_ROOT + '/' + UNITS['original_reader'], 'symlink', 0o777, 'root'),
    'output_directory': (OUTPUT, 'directory', 0o750, 'nobody'),
    'stage_code': (CODE + '/.naver-diag-' + APPLY, 'directory', 0o700, 'root'),
    'stage_units': (UNIT_ROOT + '/.naver-diag-' + APPLY, 'directory', 0o700, 'root'),
    'stage_masks': (MASK_ROOT + '/.naver-diag-' + APPLY, 'directory', 0o700, 'root'),
}
PUBLIC_ROLES = frozenset(('code_market', 'code_product', 'code_coordinator',
                         'unit_coordinator', 'unit_reader', 'mask_coordinator', 'mask_reader'))
ISSUES = frozenset(('none', 'absent', 'missing_parent', 'permission_denied', 'unsafe_parent',
    'unsafe_type', 'owner_mismatch', 'mode_mismatch', 'unexpected_links', 'changed',
    'command_timeout', 'command_size', 'command_failed', 'schema_missing', 'schema_extra',
    'schema_duplicate', 'schema_invalid', 'unknown_error'))
STATE_VALUES = {
    'load': frozenset(('', 'loaded', 'not-found', 'masked', 'error', 'bad-setting', 'merged', 'stub', 'unknown')),
    'unit_file': frozenset(('', 'enabled', 'enabled-runtime', 'linked', 'linked-runtime',
        'alias', 'masked', 'masked-runtime', 'static', 'disabled', 'indirect', 'generated',
        'transient', 'bad', 'not-found', 'unknown')),
    'result': frozenset(('', 'success', 'resources', 'protocol', 'timeout', 'exit-code',
        'signal', 'core-dump', 'watchdog', 'start-limit-hit', 'oom-kill', 'skip-condition', 'unknown')),
    'active': frozenset(('', 'active', 'reloading', 'inactive', 'failed', 'activating',
        'deactivating', 'maintenance', 'refreshing', 'unknown')),
    'sub': frozenset(('', 'dead', 'waiting', 'running', 'elapsed', 'failed', 'start-pre',
        'start', 'start-post', 'exited', 'reload', 'reload-signal', 'reload-notify',
        'stop', 'stop-watchdog', 'stop-sigterm', 'stop-sigkill', 'stop-post',
        'final-watchdog', 'final-sigterm', 'final-sigkill', 'cleaning', 'auto-restart',
        'auto-restart-queued', 'unknown')),
}
INVOCATIONS = frozenset(('empty', 'zero32', 'lower_hex32', 'upper_hex32', 'other', 'missing'))
FRAGMENTS = frozenset(('exact_original_unit', 'exact_new_unit', 'exact_owned_control_mask',
                       'dev_null', 'empty', 'other', 'missing'))
REFUSALS = frozenset(('none', 'platform', 'root', 'opath_unavailable', 'signal_context',
                      'global_deadline', 'internal'))

class Fault(Exception):
    def __init__(self, issue):
        self.issue = issue
        super().__init__('closed observation failure')

class Deadline(BaseException):
    pass

def _check(deadline):
    if time.monotonic() >= deadline:
        raise Deadline()

def _alarm(_signum, _frame):
    raise Deadline()

def _identity(info, *, leaf=False):
    out = (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink)
    return out + (info.st_size, info.st_mtime_ns, info.st_ctime_ns) if leaf else out

def _safe_parent(info):
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_gid == 0
            and not stat.S_IMODE(info.st_mode) & 0o022)

def _os_issue(error, *, parent=False):
    if error.errno == errno.ENOENT:
        return 'missing_parent' if parent else 'absent'
    if error.errno in (errno.EACCES, errno.EPERM):
        return 'permission_denied'
    if error.errno in (errno.ELOOP, errno.ENOTDIR):
        return 'unsafe_parent' if parent else 'unsafe_type'
    return 'unknown_error'

def _file_empty(issue='unknown_error'):
    return dict(presence='unknown', kind='unknown', owner_match=None,
                mode_match=None, links='unknown', stable=None, issue=issue)

def _metadata_once(role, runtime_uid, deadline):
    """Only fixed paths; all parent descriptors are no-follow O_PATH directories.

    A successful fingerprint is private RAM metadata, never public evidence.
    No leaf data descriptor is opened and no directory is listed.
    """
    _check(deadline)
    path, expected_kind, mode, owner_kind = FILES[role]
    parts = path.split('/')[1:]
    fds, chain, result, fingerprint = [], [], None, None
    try:
        flags = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        root_fd = os.open('/', flags)
        fds.append(root_fd)
        _check(deadline)
        root_info = os.fstat(root_fd)
        if not _safe_parent(root_info):
            raise Fault('unsafe_parent')
        chain.append((None, '/', root_fd, _identity(root_info)))
        parent = root_fd
        for part in parts[:-1]:
            _check(deadline)
            try:
                before = os.stat(part, dir_fd=parent, follow_symlinks=False)
                if not _safe_parent(before):
                    raise Fault('unsafe_parent')
                child = os.open(part, flags, dir_fd=parent)
                fds.append(child)
                _check(deadline)
                if _identity(os.fstat(child)) != _identity(before):
                    raise Fault('changed')
            except OSError as error:
                issue = _os_issue(error, parent=True)
                if issue == 'missing_parent':
                    result = _file_empty(issue)
                    result.update(presence='absent', stable=True)
                    fingerprint = ('missing_parent', len(chain), tuple(x[3] for x in chain))
                    # Recheck absence after the ancestor bindings below.
                    missing = (parent, part)
                    break
                raise Fault(issue) from None
            chain.append((parent, part, child, _identity(before)))
            parent = child
        else:
            missing = None
            _check(deadline)
            try:
                before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            except OSError as error:
                issue = _os_issue(error)
                if issue != 'absent':
                    raise Fault(issue) from None
                result = _file_empty('absent')
                result.update(presence='absent', stable=True)
                fingerprint = ('absent', tuple(x[3] for x in chain))
                missing = (parent, parts[-1])
            else:
                kind = ('directory' if stat.S_ISDIR(before.st_mode) else
                        'regular' if stat.S_ISREG(before.st_mode) else
                        'symlink' if stat.S_ISLNK(before.st_mode) else 'other')
                target = None
                if kind == 'symlink' and expected_kind == 'symlink':
                    _check(deadline)
                    target = os.readlink(parts[-1], dir_fd=parent)
                expected_owner = (0, 0) if owner_kind == 'root' else (
                    (runtime_uid, 10001) if runtime_uid is not None else None)
                owner = None if expected_owner is None else (
                    (before.st_uid, before.st_gid) == expected_owner)
                modes = stat.S_IMODE(before.st_mode) == mode
                links = ('not_applicable' if kind == 'directory' else
                         'one' if before.st_nlink == 1 else
                         'two' if before.st_nlink == 2 else 'other')
                issue = ('unsafe_type' if kind != expected_kind or
                         (kind == 'symlink' and target != '/dev/null') else
                         'owner_mismatch' if owner is False else
                         'unknown_error' if owner is None else
                         'mode_mismatch' if not modes else
                         'unexpected_links' if links == 'other' or
                         (kind == 'symlink' and links != 'one') else 'none')
                result = dict(presence='present', kind=kind, owner_match=owner,
                    mode_match=modes, links=links, stable=True, issue=issue)
                _check(deadline)
                after = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if _identity(before, leaf=True) != _identity(after, leaf=True):
                    raise Fault('changed')
                if target is not None:
                    _check(deadline)
                    if os.readlink(parts[-1], dir_fd=parent) != target:
                        raise Fault('changed')
                fingerprint = (_identity(before, leaf=True), target,
                               tuple(x[3] for x in chain))
        for parent_fd, name, fd, identity in reversed(chain):
            _check(deadline)
            if _identity(os.fstat(fd)) != identity:
                raise Fault('changed')
            if parent_fd is not None:
                _check(deadline)
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if _identity(current) != identity:
                    raise Fault('changed')
            else:
                _check(deadline)
                if _identity(os.stat('/', follow_symlinks=False)) != identity:
                    raise Fault('changed')
        if missing is not None:
            _check(deadline)
            try:
                os.stat(missing[1], dir_fd=missing[0], follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise Fault('changed')
        _check(deadline)
        return result, fingerprint
    except Fault as error:
        value = _file_empty(error.issue)
        if error.issue == 'changed':
            value['stable'] = False
        return value, None
    except OSError as error:
        return _file_empty(_os_issue(error)), None
    finally:
        for fd in reversed(fds):
            os.close(fd)

def _merge_metadata(first_observation, second_observation):
    first, before = first_observation
    second, after = second_observation
    if before is not None and after is not None:
        if before != after or first != second:
            second['stable'], second['issue'] = False, 'changed'
    else:
        second['stable'] = False if 'changed' in (first['issue'], second['issue']) else None
        if second['issue'] in ('none', 'absent', 'missing_parent'):
            second['issue'] = first['issue']
    return second

def _metadata_pair(role, runtime_uid, deadline):
    first = _metadata_once(role, runtime_uid, deadline)
    _check(deadline)
    return _merge_metadata(first, _metadata_once(role, runtime_uid, deadline))

def _properties(role):
    return TIMER_PROPERTIES if role == 'original_timer' else PROPERTIES

def _capture_show(role, deadline):
    """Capture only fixed show stdout; enforce cap while process is running."""
    _check(deadline)
    argv = ['/usr/bin/systemctl', 'show', UNITS[role]]
    argv += ['--property=' + p for p in _properties(role)]
    process, selector = None, selectors.DefaultSelector()
    end = min(deadline, time.monotonic() + COMMAND_SECONDS)
    chunks, size = [], 0
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=ENV,
            close_fds=True, start_new_session=True)
        _check(deadline)
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        while selector.get_map():
            _check(deadline)
            left = end - time.monotonic()
            if left <= 0:
                raise Fault('command_timeout')
            for key, _ in selector.select(left):
                _check(deadline)
                chunk = os.read(key.fd, min(4096, MAX_STDOUT + 1 - size))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_STDOUT:
                    raise Fault('command_size')
        _check(deadline)
        left = end - time.monotonic()
        if left <= 0:
            raise Fault('command_timeout')
        try:
            code = process.wait(timeout=left)
        except subprocess.TimeoutExpired:
            raise Fault('command_timeout') from None
        _check(deadline)
        return code, b''.join(chunks)
    except OSError:
        raise Fault('command_failed') from None
    finally:
        selector.close()
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                left = deadline - time.monotonic()
                if left > 0:
                    try:
                        process.wait(timeout=min(0.05, left))
                    except subprocess.TimeoutExpired:
                        pass
            if process.stdout is not None:
                process.stdout.close()

def _run_show(role, deadline):
    code, raw = _capture_show(role, deadline)
    if code != 0:
        raise Fault('command_failed')
    return raw

def _invocation(value):
    if value is None: return 'missing'
    if value == '': return 'empty'
    if value == '0' * 32: return 'zero32'
    if re.fullmatch('[0-9a-f]{32}', value): return 'lower_hex32'
    if re.fullmatch('[0-9A-F]{32}', value): return 'upper_hex32'
    return 'other'

def _unit_empty(role, issue='unknown_error'):
    return dict(load='unknown', unit_file='unknown', result='unknown', active='unknown',
        sub='unknown', fragment='missing', dropins='missing', job='missing',
        exit_kind='absent_by_kind' if role == 'original_timer' else 'missing',
        exit_status=None, invocation_format='missing', invocation_same=None,
        state_same=None, issue=issue)

def _parse_show(raw, role):
    if type(raw) is not bytes or len(raw) > MAX_STDOUT:
        raise Fault('command_size')
    try:
        text = raw.decode('ascii')
    except UnicodeError:
        raise Fault('schema_invalid') from None
    if any(ord(c) < 32 and c != '\n' for c in text) or '\x7f' in text:
        raise Fault('schema_invalid')
    if text.endswith('\n'):
        text = text[:-1]
    pairs = {}
    for line in text.split('\n'):
        if '=' not in line:
            raise Fault('schema_invalid')
        name, value = line.split('=', 1)
        if name in pairs:
            raise Fault('schema_duplicate')
        pairs[name] = value
    expected = set(_properties(role))
    if set(pairs) - expected:
        raise Fault('schema_extra')
    missing = bool(expected - set(pairs))
    value = _unit_empty(role, 'schema_missing' if missing else 'none')
    for name, prop in (('load', 'LoadState'), ('unit_file', 'UnitFileState'),
                       ('result', 'Result'), ('active', 'ActiveState'), ('sub', 'SubState')):
        got = pairs.get(prop)
        if got in STATE_VALUES[name]:
            value[name] = got
        elif got is not None and value['issue'] == 'none':
            value['issue'] = 'schema_invalid'
    fragment = pairs.get('FragmentPath')
    if fragment is None: category = 'missing'
    elif not fragment: category = 'empty'
    elif fragment == UNIT_ROOT + '/' + UNITS[role]:
        category = 'exact_original_unit' if role.startswith('original_') else 'exact_new_unit'
    elif role in ('original_coordinator', 'original_reader') and fragment == MASK_ROOT + '/' + UNITS[role]:
        category = 'exact_owned_control_mask'
    elif fragment == '/dev/null': category = 'dev_null'
    else: category = 'other'
    value['fragment'] = category
    dropins = pairs.get('DropInPaths')
    value['dropins'] = 'missing' if dropins is None else 'empty' if not dropins else 'nonempty'
    job = pairs.get('Job')
    value['job'] = ('missing' if job is None else 'idle' if job in ('', '0') else
                    'present' if re.fullmatch('[1-9][0-9]{0,19}(?: /[A-Za-z0-9_/]+)?', job) else 'invalid')
    if role != 'original_timer':
        status = pairs.get('ExecMainStatus')
        if status is None: value['exit_kind'] = 'missing'
        elif status == '': value['exit_kind'] = 'empty'
        elif re.fullmatch('0|[1-9][0-9]{0,2}', status) and int(status) <= 255:
            value['exit_kind'], value['exit_status'] = 'valid', int(status)
        else: value['exit_kind'] = 'invalid'
    value['invocation_format'] = _invocation(pairs.get('InvocationID'))
    # Raw values remain private and are used solely for before/after equality.
    return value, pairs

def _show(role, deadline):
    try:
        return _parse_show(_run_show(role, deadline), role)
    except Fault as error:
        return _unit_empty(role, error.issue), None

def _unit_pair(first, second):
    before, raw_before = first
    after, raw_after = second
    if raw_before is not None and raw_after is not None:
        after['invocation_same'] = (raw_before.get('InvocationID') == raw_after.get('InvocationID')
                                   if 'InvocationID' in raw_before and 'InvocationID' in raw_after else None)
        after['state_same'] = raw_before == raw_after
        if not after['state_same']:
            after['issue'] = 'changed'
    elif after['issue'] == 'none':
        after['issue'] = before['issue']
    return after

def _base():
    return dict(version=1, state='refused', refusal='internal', summary='undetermined',
                units={r: _unit_empty(r) for r in UNITS},
                files={r: _file_empty() for r in FILES})

def _finish(value):
    if value['refusal'] != 'none':
        value['state'], value['summary'] = 'refused', 'undetermined'
        return value
    issues = [v['issue'] for v in value['units'].values()] + [v['issue'] for v in value['files'].values()]
    if 'changed' in issues:
        value['state'] = 'context_changed'
    elif (any(x not in ('none', 'absent', 'missing_parent') for x in issues)
          or any(v['state_same'] is not True for v in value['units'].values())
          or any(v['stable'] is not True for v in value['files'].values())):
        value['state'] = 'partial_observation'
    else:
        value['state'] = 'observed_stable'
    if value['state'] != 'observed_stable':
        value['summary'] = 'undetermined'
    elif any(value['files'][r]['presence'] == 'present' for r in PUBLIC_ROLES):
        value['summary'] = 'public_trace_observed'
    elif any(v['presence'] == 'present' for v in value['files'].values()):
        value['summary'] = 'private_preparation_trace_observed'
    elif all(v['presence'] == 'absent' for v in value['files'].values()):
        value['summary'] = 'no_owned_trace_observed'
    return value

def observe():
    """One fixed read-only observation. No user arguments or command seams."""
    value, start = _base(), time.monotonic()
    deadline = start + GLOBAL_SECONDS
    if sys.platform != 'linux':
        value['refusal'] = 'platform'
        return value
    if os.geteuid() != 0:
        value['refusal'] = 'root'
        return value
    if not all(hasattr(os, k) for k in ('O_PATH', 'O_DIRECTORY', 'O_NOFOLLOW', 'O_CLOEXEC')):
        value['refusal'] = 'opath_unavailable'
        return value
    if threading.current_thread() is not threading.main_thread() or signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        value['refusal'] = 'signal_context'
        return value
    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _alarm)
    armed = False
    try:
        _check(deadline)
        signal.setitimer(signal.ITIMER_REAL, max(0.000001, deadline - time.monotonic()))
        armed = True
        value['refusal'] = 'none'
        try:
            _check(deadline)
            runtime_uid = pwd.getpwnam('nobody').pw_uid
            _check(deadline)
            if type(runtime_uid) is not int or not 0 < runtime_uid < 2**32:
                runtime_uid = None
        except (KeyError, OSError):
            runtime_uid = None
        first = {}
        for role in UNITS:
            _check(deadline)
            first[role] = _show(role, deadline)
        first_files = {}
        for role in FILES:
            _check(deadline)
            first_files[role] = _metadata_once(role, runtime_uid, deadline)
        for role in FILES:
            _check(deadline)
            value['files'][role] = _merge_metadata(first_files[role],
                _metadata_once(role, runtime_uid, deadline))
        for role in UNITS:
            _check(deadline)
            value['units'][role] = _unit_pair(first[role], _show(role, deadline))
        _check(deadline)
        return _finish(value)
    except Deadline:
        value['refusal'] = 'global_deadline'
        return _finish(value)
    except Exception:
        value['refusal'] = 'internal'
        return _finish(value)
    finally:
        if armed:
            signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)

def _enum(value, allowed):
    return type(value) is str and value in allowed

def _nullable_bool(value):
    return value is None or type(value) is bool

def validate(value):
    """Exact public projection validator; no arbitrary strings or identifiers."""
    top = {'version', 'state', 'refusal', 'summary', 'units', 'files'}
    if (type(value) is not dict or set(value) != top or type(value['version']) is not int
            or value['version'] != 1 or not _enum(value['state'],
                ('observed_stable', 'context_changed', 'partial_observation', 'refused'))
            or not _enum(value['refusal'], REFUSALS)
            or not _enum(value['summary'], ('undetermined', 'no_owned_trace_observed',
                'private_preparation_trace_observed', 'public_trace_observed'))
            or type(value['units']) is not dict or set(value['units']) != set(UNITS)
            or type(value['files']) is not dict or set(value['files']) != set(FILES)):
        raise ValueError('RESULT_SCHEMA')
    for role, item in value['units'].items():
        if type(item) is not dict or set(item) != set(_unit_empty(role)):
            raise ValueError('RESULT_SCHEMA')
        if (any(not _enum(item[k], choices) for k, choices in STATE_VALUES.items())
                or not _enum(item['fragment'], FRAGMENTS)
                or not _enum(item['dropins'], ('missing', 'empty', 'nonempty'))
                or not _enum(item['job'], ('missing', 'idle', 'present', 'invalid'))
                or not _enum(item['exit_kind'], ('absent_by_kind', 'missing', 'empty', 'valid', 'invalid'))
                or not _enum(item['invocation_format'], INVOCATIONS)
                or not _nullable_bool(item['invocation_same']) or not _nullable_bool(item['state_same'])
                or not _enum(item['issue'], ISSUES)):
            raise ValueError('RESULT_SCHEMA')
        status = item['exit_status']
        if item['exit_kind'] == 'valid':
            if type(status) is not int or not 0 <= status <= 255:
                raise ValueError('RESULT_SCHEMA')
        elif status is not None:
            raise ValueError('RESULT_SCHEMA')
        if (item['exit_kind'] == 'absent_by_kind') != (role == 'original_timer'):
            raise ValueError('RESULT_SCHEMA')
        if ((item['state_same'] is False) != (item['issue'] == 'changed')
                or (item['state_same'] is True and item['invocation_same'] is False)):
            raise ValueError('RESULT_SCHEMA')
    for role, item in value['files'].items():
        if (type(item) is not dict or set(item) != set(_file_empty())
                or not _enum(item['presence'], ('absent', 'present', 'unknown'))
                or not _enum(item['kind'], ('directory', 'regular', 'symlink', 'other', 'unknown'))
                or not _enum(item['links'], ('one', 'two', 'other', 'not_applicable', 'unknown'))
                or any(not _nullable_bool(item[k]) for k in ('owner_match', 'mode_match', 'stable'))
                or not _enum(item['issue'], ISSUES)):
            raise ValueError('RESULT_SCHEMA')
        if item['presence'] != 'present':
            if (item['kind'] != 'unknown' or item['owner_match'] is not None
                    or item['mode_match'] is not None or item['links'] != 'unknown'):
                raise ValueError('RESULT_SCHEMA')
        else:
            if (item['kind'] == 'unknown' or type(item['mode_match']) is not bool
                    or item['links'] == 'unknown'
                    or ((item['kind'] == 'directory') != (item['links'] == 'not_applicable'))):
                raise ValueError('RESULT_SCHEMA')
        if ((item['stable'] is False) != (item['issue'] == 'changed')
                or (item['issue'] in ('absent', 'missing_parent') and item['presence'] != 'absent')
                or (item['issue'] == 'none' and (item['presence'] != 'present'
                    or item['owner_match'] is not True or item['mode_match'] is not True
                    or item['stable'] is not True or item['kind'] != FILES[role][1]
                    or item['links'] == 'other'
                    or (item['kind'] == 'symlink' and item['links'] != 'one')))
                or (item['presence'] == 'unknown' and item['stable'] is True)):
            raise ValueError('RESULT_SCHEMA')
    # Reject contradictory aggregate claims, even if all enum strings are known.
    check = json.loads(json.dumps(value))
    if _finish(check) != value:
        raise ValueError('RESULT_SCHEMA')
    return value

def closed_json(value):
    validate(value)
    body = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    if len(body.encode('ascii')) > MAX_JSON:
        raise ValueError('RESULT_SIZE')
    return body

