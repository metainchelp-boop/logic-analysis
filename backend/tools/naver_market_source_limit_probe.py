"""Pinned market source-limit probe; one kernel-readonly child, no publication or services."""
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
PACKAGE = {'operation': 'code-prepare', 'baseline': '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76', 'source_commit': EXPORT_SOURCE, 'source_tar_gz_sha256': '7d02a455ff2b8b2e2bbcd598b71f5e06ffe8e9d2099f08a2e87a8ea10cbae872', 'ciphertext_sha256': '5f7bcd5b0399603b75de806ce3332be5d89997aca8c06db8807f2d6f23019416', 'run_id': '38198428850'}
SOURCE_PINS = {'exports_binding': '1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed', 'exports_helper': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737', 'product_exporter': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59', 'market_exporter': 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8'}
PHASES = ('pins', 'modules', 'operating_receipt', 'construction', 'prepared', 'verify', 'complete')
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

def _failure_component(error, helper):
    current = error.__traceback__
    while current is not None:
        if current.tb_frame.f_code is helper.verify.__code__ and 648 <= current.tb_lineno <= 652:
            unit = current.tb_frame.f_locals.get('unit')
            if type(unit) is str and unit == UNITS['market']:
                return 'market_result'
        current = current.tb_next
    return 'unclassified'
import ctypes
import importlib.util
import resource
import selectors
import signal
import sqlite3
import sys
import time
SQL_MAX, PROGRESS_MAX, WALL_MAX = (200008, 100000, 45)
ALIAS = Path('/tmp/naver-source-probe/source')
LAYOUTS = {'clients': ('clients', (('id', 30), ('naver_store_url', 8192), ('main_keywords', 8192))), 'mapping': ('client_keyword_product', (('client_id', 30), ('keyword', 8192), ('product_url', 8192))), 'mute': ('client_keyword_mute', (('client_id', 30), ('keyword', 8192))), 'observation_headers': ('collector_observations', (('observation_id', 100), ('keyword', 8192), ('collected_date', 100), ('status', 100), ('kind', 100), ('reason', 300), ('received_at', 200))), 'ledger': ('collector_observations', (('payload_hash', 100), ('products_json', 2097152), ('meta_json', 2097152))), 'serp': ('collected_serp', (('total', 100), ('products_json', 2097152), ('meta_json', 2097152)))}
PROBE_STATUS = frozenset(('not_started', 'source_limit', 'original_collect_passed', 'original_other_failure', 'readonly_precondition_failed', 'source_context_changed', 'diagnostic_guard', 'diagnostic_terminated_unknown', 'diagnostic_unavailable'))
BRANCHES = frozenset(('none', 'input_bytes', 'rows', 'time', 'cell', 'client_count', 'unclassified_source_limit'))
GUARDS = frozenset(('none', 'sql', 'opcode', 'wall', 'cpu', 'memory'))

class ProbeStop(Exception):
    pass

def empty_probe():
    return dict(status='not_started', database_opened=False, readonly_namespace_verified=False, read_transaction_fds_bound=False, path_identity_unchanged=False, collect_calls=0, observation='new_readonly_probe_not_previous_invocation', limit_branch='none', phase='unknown', fixed_table=None, fixed_column=None, bytes_exceeded=None, rows_exceeded=None, guard='none')

def _layout(locals_):
    table, columns = (locals_.get('table'), locals_.get('columns'))
    if type(table) is not str or type(columns) is not list:
        return None
    if any((type(p) is not tuple or len(p) != 2 or type(p[0]) is not str or (type(p[1]) is not int) for p in columns)):
        return None
    for phase, (fixed, caps) in LAYOUTS.items():
        if table == fixed and tuple(columns) == caps:
            return (phase, fixed, caps)
    return None

def _classify_limit(error, market):
    out = empty_probe()
    out.update(status='source_limit', limit_branch='unclassified_source_limit')
    if type(error) is not market.ExportInvalid or error.code != 'SOURCE_LIMIT':
        out.update(status='original_other_failure', limit_branch='none')
        return out
    frames, current = ([], error.__traceback__)
    while current is not None:
        frames.append(current)
        current = current.tb_next
    layout = None
    for frame in frames:
        if frame.tb_frame.f_code is market._rows.__code__:
            layout = _layout(frame.tb_frame.f_locals)
        if frame.tb_frame.f_code is market.collect.__code__:
            if frame.tb_lineno == 331:
                out['phase'] = 'exception_budget'
            elif frame.tb_lineno in (314, 328):
                out['phase'] = 'assembly'
    if layout is not None:
        out.update(phase=layout[0], fixed_table=layout[1])
    if not frames:
        return out
    frame = frames[-1]
    code, line, values = (frame.tb_frame.f_code, frame.tb_lineno, frame.tb_frame.f_locals)
    if code is market.P._Budget.tick.__code__ and line == 108:
        budget = values.get('self')
        if type(budget) is not market.P._Budget or type(budget.limits) is not market.Limits:
            return out
        if budget.limits != market.Limits() or type(budget.bytes) is not int or type(budget.rows) is not int:
            return out
        if budget.bytes < 0 or budget.rows < 0:
            return out
        be, re_ = (budget.bytes > 33554432, budget.rows > 100000)
        out.update(bytes_exceeded=be, rows_exceeded=re_, limit_branch='input_bytes' if be else 'rows' if re_ else 'time')
    elif code is market._rows.__code__ and line == 105 and (layout is not None):
        sizes = values.get('sizes')
        if type(sizes) is not tuple or len(sizes) != len(layout[2]):
            return out
        if any((x is not None and (type(x) is not int or x < 0) for x in sizes)):
            return out
        for size, (column, cap) in zip(sizes, layout[2]):
            if size is not None and size > cap:
                out.update(limit_branch='cell', fixed_column=column)
                break
    elif code is market.collect.__code__ and line == 251:
        index, limits = (values.get('index'), values.get('limits'))
        if type(index) is int and index >= 10000 and (type(limits) is market.Limits) and (limits == market.Limits()):
            out.update(limit_branch='client_count', phase='clients', fixed_table='clients')
    return out

class ProbeConnection:

    def __init__(self, conn, market, bind_fds):
        self.conn, self.market, self.bind_fds = (conn, market, bind_fds)
        self.sql = self.progress_calls = 0
        self.guard, self.bound = ('none', False)

    @property
    def in_transaction(self):
        return self.conn.in_transaction

    def execute(self, sql, params=()):
        self.sql += 1
        if self.sql > SQL_MAX:
            self.guard = 'sql'
            raise ProbeStop()
        result = self.conn.execute(sql, params)
        if not self.bound and sql.startswith('SELECT '):
            self.bind_fds()
            self.bound = True
        return result

    def set_authorizer(self, callback):
        if callback is not self.market._authorizer:
            raise ProbeStop()
        self.conn.set_authorizer(callback)

    def set_progress_handler(self, callback, steps):
        if steps != 1000 or getattr(callback, '__func__', None) is not self.market.P._Budget.progress or type(getattr(callback, '__self__', None)) is not self.market.P._Budget:
            raise ProbeStop()

        def observe():
            original = callback()
            self.progress_calls += 1
            if original != 0:
                return original
            if self.progress_calls >= PROGRESS_MAX:
                self.guard = 'opcode'
                return 1
            return 0
        self.conn.set_progress_handler(observe, steps)

def _collect_probe(market, conn, bind_fds):
    wrapped = ProbeConnection(conn, market, bind_fds)
    out = empty_probe()
    try:
        bundle = market.collect(wrapped)
        del bundle
        out['status'] = 'original_collect_passed'
    except MemoryError:
        out.update(status='diagnostic_guard', guard='memory')
    except Exception as error:
        out = _classify_limit(error, market)
        if type(error) is ProbeStop:
            out['status'] = 'source_context_changed'
    if wrapped.guard != 'none':
        out.update(status='diagnostic_guard', guard=wrapped.guard, limit_branch='none', fixed_table=None, fixed_column=None, bytes_exceeded=None, rows_exceeded=None)
    if not wrapped.bound and out['status'] in ('source_limit', 'original_collect_passed', 'original_other_failure'):
        try:
            bind_fds()
            wrapped.bound = True
        except Exception:
            out.update(status='source_context_changed', limit_branch='none', fixed_table=None, fixed_column=None, bytes_exceeded=None, rows_exceeded=None)
    out.update(database_opened=True, collect_calls=1, read_transaction_fds_bound=wrapped.bound)
    return out

def _load_exporters(sources, directory):
    if type(sources) is not dict or set(sources) != {'product_exporter', 'market_exporter'} or any((type(body) is not bytes or hashlib.sha256(body).hexdigest() != SOURCE_PINS[role] for role, body in sources.items())):
        raise ProbeStop()
    import importlib.abc
    product_name = '_naver_market_product_primitives'
    path = directory / 'naver_product_export.py'
    original = importlib.util.spec_from_file_location

    class MemoryLoader(importlib.abc.Loader):

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            module.__file__ = str(path)
            exec(compile(sources['product_exporter'], str(path), 'exec'), module.__dict__)

    def exact_spec(name, location, *args, **kwargs):
        if name != product_name or Path(location) != path or args or kwargs:
            raise ProbeStop()
        return importlib.util.spec_from_loader(name, MemoryLoader())
    market = types.ModuleType('fixed_market_limit_probe_exporter')
    market.__file__ = str(directory / 'naver_market_export.py')
    importlib.util.spec_from_file_location = exact_spec
    try:
        exec(compile(sources['market_exporter'], market.__file__, 'exec'), market.__dict__)
    finally:
        importlib.util.spec_from_file_location = original
    return market

def _file_family(directory, name, readonly=False):
    if directory.resolve() != directory or not stat.S_ISDIR(directory.lstat().st_mode):
        raise ProbeStop()
    if readonly and (not os.statvfs(directory).f_flag & os.ST_RDONLY):
        raise ProbeStop()
    out = {}
    for suffix in ('', '-wal', '-shm'):
        path = directory / (name + suffix)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.resolve() != path or (readonly and (not os.statvfs(path).f_flag & os.ST_RDONLY or not os.access(path, os.R_OK))):
            raise ProbeStop()
        out[suffix] = (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)
    return out

def _fd_snapshot():
    result = {}
    for name in os.listdir('/proc/self/fd'):
        if name.isdecimal():
            fd = int(name)
            try:
                info = os.fstat(fd)
            except OSError:
                continue
            result[fd] = (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)
    return result

def _bind_sqlite_fds(before, family):
    after = _fd_snapshot()
    actual = [value for fd, value in after.items() if fd not in before and stat.S_ISREG(value[2])]
    if len(actual) != 3 or sorted(actual) != sorted(family.values()):
        raise ProbeStop()

def _namespace(plan, family):
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise ProbeStop()
    directory = Path(plan['source_directory'])
    if _file_family(directory, plan['database_name']) != family:
        raise ProbeStop()
    root_namespace = os.stat('/proc/self/ns/mnt').st_ino
    net_namespace = os.stat('/proc/self/ns/net').st_ino
    libc = ctypes.CDLL(None, use_errno=True)
    libc.unshare.argtypes = [ctypes.c_int]
    libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p]

    def mount(source, target, kind, flags, data):
        if libc.mount(source, target, kind, flags, data) != 0:
            raise ProbeStop()
    fd = None
    try:
        if libc.unshare(131072 | 1073741824) != 0:
            raise ProbeStop()
        if os.stat('/proc/self/ns/mnt').st_ino == root_namespace or os.stat('/proc/self/ns/net').st_ino == net_namespace:
            raise ProbeStop()
        fd = os.open(directory, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
        mount(None, b'/', None, 1 << 18 | 16384, None)
        mount(b'tmpfs', b'/tmp', b'tmpfs', 2 | 4 | 8, b'size=1048576,mode=1777')
        ALIAS.mkdir(parents=True, mode=493)
        mount(('/proc/self/fd/' + str(fd)).encode(), os.fsencode(ALIAS), None, 4096, None)
        mount(None, os.fsencode(ALIAS), None, 4096 | 32 | 1 | 2 | 4 | 8, None)
    finally:
        if fd is not None:
            os.close(fd)
    if _file_family(ALIAS, plan['database_name'], True) != family:
        raise ProbeStop()
    import pwd, grp
    user = pwd.getpwnam(plan['exporter_user'])
    groups = [10001]
    if plan['source_group'] is not None:
        groups.append(grp.getgrnam(plan['source_group']).gr_gid)
    if user.pw_uid == 0 or 0 in groups:
        raise ProbeStop()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (268435456, 268435456))
    resource.setrlimit(resource.RLIMIT_CPU, (35, 40))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    for capability in range(64):
        if libc.prctl(24, capability, 0, 0, 0) != 0 and ctypes.get_errno() != 22:
            raise ProbeStop()
    if libc.prctl(47, 4, 0, 0, 0) != 0:
        raise ProbeStop()
    os.setgroups(groups)
    os.setgid(10001)
    os.setuid(user.pw_uid)
    if libc.prctl(38, 1, 0, 0, 0) != 0 or os.geteuid() == 0:
        raise ProbeStop()

    class Header(ctypes.Structure):
        _fields_ = [('version', ctypes.c_uint), ('pid', ctypes.c_int)]

    class Cap(ctypes.Structure):
        _fields_ = [('effective', ctypes.c_uint), ('permitted', ctypes.c_uint), ('inheritable', ctypes.c_uint)]
    header, caps = (Header(537396514, 0), (Cap * 2)())
    if libc.capset(ctypes.byref(header), ctypes.byref(caps)) != 0:
        raise ProbeStop()
    status = Path('/proc/self/status').read_text()
    for field in ('CapInh:', 'CapPrm:', 'CapEff:', 'CapAmb:', 'CapBnd:'):
        values = [line.split()[1] for line in status.splitlines() if line.startswith(field)]
        if len(values) != 1 or int(values[0], 16) != 0:
            raise ProbeStop()
    os.environ.clear()
    if _file_family(ALIAS, plan['database_name'], True) != family:
        raise ProbeStop()

def _child_probe(plan, sources, family, install):
    out, conn = (empty_probe(), None)
    try:
        market = _load_exporters(sources, install)
        _namespace(plan, family)
        out['readonly_namespace_verified'] = True
        before = _fd_snapshot()
        conn = sqlite3.connect((ALIAS / plan['database_name']).as_uri() + '?mode=ro', uri=True, timeout=1, isolation_level=None)
        out['database_opened'] = True

        def bind():
            if _file_family(ALIAS, plan['database_name'], True) != family:
                raise ProbeStop()
            _bind_sqlite_fds(before, family)
        collected = _collect_probe(market, conn, bind)
        collected['readonly_namespace_verified'] = True
        out = collected
        if _file_family(ALIAS, plan['database_name'], True) != family:
            out.update(status='source_context_changed', limit_branch='none')
        else:
            out['path_identity_unchanged'] = True
    except MemoryError:
        out.update(status='diagnostic_guard', guard='memory')
    except Exception:
        out['status'] = 'source_context_changed' if out['database_opened'] else 'readonly_precondition_failed'
    finally:
        if conn is not None:
            conn.close()
    return out

def _probe_json(value):
    template = empty_probe()
    if type(value) is not dict or set(value) != set(template):
        raise ValueError('DIAGNOSTIC_RESULT')
    unknown = value['status'] in ('diagnostic_guard', 'diagnostic_terminated_unknown', 'diagnostic_unavailable')
    for key in ('database_opened', 'readonly_namespace_verified', 'read_transaction_fds_bound', 'path_identity_unchanged'):
        if type(value[key]) is not bool and (not (unknown and value[key] is None)):
            raise ValueError('DIAGNOSTIC_RESULT')
    if value['status'] not in PROBE_STATUS or value['limit_branch'] not in BRANCHES or value['guard'] not in GUARDS or (not (type(value['collect_calls']) is int and value['collect_calls'] in (0, 1) or (unknown and value['collect_calls'] is None))) or (value['observation'] != template['observation']) or (value['phase'] not in set(LAYOUTS) | {'assembly', 'exception_budget', 'unknown'}) or any((value[k] is not None and type(value[k]) is not bool for k in ('bytes_exceeded', 'rows_exceeded'))):
        raise ValueError('DIAGNOSTIC_RESULT')
    table, column = (value['fixed_table'], value['fixed_column'])
    if table is not None and table not in {x[0] for x in LAYOUTS.values()}:
        raise ValueError('DIAGNOSTIC_RESULT')
    if column is not None and (not any((table == t and column in {c for c, _ in cols} for t, cols in LAYOUTS.values()))):
        raise ValueError('DIAGNOSTIC_RESULT')
    body = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(body) > MAX_OUTPUT:
        raise ValueError('DIAGNOSTIC_RESULT')
    return body

def _run_child(plan, sources, family, install):
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            for fd in _fd_snapshot():
                if fd > 2 and fd != write_fd:
                    os.close(fd)
            null = os.open('/dev/null', os.O_RDWR)
            for fd in (0, 1, 2):
                os.dup2(null, fd)
            if null > 2 and null != write_fd:
                os.close(null)
            body = _probe_json(_child_probe(plan, sources, family, install))
            os.write(write_fd, body)
            os._exit(0)
        except BaseException:
            os._exit(2)
    os.close(write_fd)
    out, body, deadline, status = (empty_probe(), bytearray(), time.monotonic() + WALL_MAX, None)
    accepted = False
    timed_out = False
    try:
        with selectors.DefaultSelector() as select:
            select.register(read_fd, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                if not select.select(remaining):
                    timed_out = True
                    break
                part = os.read(read_fd, MAX_OUTPUT + 1 - len(body))
                if not part:
                    break
                body.extend(part)
                if len(body) > MAX_OUTPUT:
                    break
        if timed_out or len(body) > MAX_OUTPUT:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        _, status = os.waitpid(pid, 0)
        if timed_out:
            out.update(status='diagnostic_guard', guard='wall')
        elif os.WIFSIGNALED(status):
            if os.WTERMSIG(status) == signal.SIGXCPU:
                out.update(status='diagnostic_guard', guard='cpu')
            else:
                out['status'] = 'diagnostic_terminated_unknown'
        elif os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0 and (len(body) <= MAX_OUTPUT):
            candidate = json.loads(body, object_pairs_hook=unique)
            _probe_json(candidate)
            out, accepted = (candidate, True)
        else:
            out['status'] = 'diagnostic_unavailable'
    except Exception:
        out['status'] = 'diagnostic_unavailable'
    finally:
        os.close(read_fd)
        if status is None:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
    if not accepted:
        for key in ('database_opened', 'readonly_namespace_verified', 'read_transaction_fds_bound', 'path_identity_unchanged', 'collect_calls'):
            out[key] = None
    return out

def _verified_probe(bound, helper, sources):
    plan = bound.plan
    if plan != helper.build_plan(**plan):
        raise ProbeStop()
    install = helper.INSTALL / plan['ops_commit']
    _, _, prepared = helper._prepared(bound.receipt)
    if sys.platform != 'linux':
        raise ProbeStop()
    target = Path('/proc/self/exe')
    fd = os.open(target, os.O_RDONLY | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= helper.MAX_INTERPRETER or info.st_uid != 0 or info.st_mode & 18:
            raise ProbeStop()
        digest, total = (hashlib.sha256(), 0)
        while total <= helper.MAX_INTERPRETER:
            piece = os.read(fd, min(65536, helper.MAX_INTERPRETER + 1 - total))
            if not piece:
                break
            total += len(piece)
            digest.update(piece)
        if total > helper.MAX_INTERPRETER or _identity(os.fstat(fd)) != _identity(info) or _identity(target.stat()) != _identity(info) or (digest.hexdigest() != hashlib.sha256(prepared[helper.INTERPRETER]).hexdigest()):
            raise ProbeStop()
    finally:
        os.close(fd)
    installed = {}
    for role, name in (('product_exporter', 'naver_product_export.py'), ('market_exporter', 'naver_market_export.py')):
        body = helper._regular(install / name, mode=420)
        if type(body) is not bytes or hashlib.sha256(body).hexdigest() != SOURCE_PINS[role] or body != sources[role]:
            raise ProbeStop()
        installed[role] = body
    family = _file_family(Path(plan['source_directory']), plan['database_name'])
    return _run_child(plan, installed, family, install)

def diagnose(sources):
    phase = 'pins'
    out = {'version': 1, 'diagnostic': 'market-source-limit-readonly-probe', 'ok': False, 'phase': phase, 'operating_receipt_match': False, 'source_pins_match': False, 'original_verify_error': None, 'probe': empty_probe()}
    try:
        require_pins(sources)
        out['source_pins_match'] = True
        phase = 'modules'
        binding_module, helper = _load_modules(sources)
        phase = 'operating_receipt'
        if _read_operating_receipt() is not True:
            raise ProbeStop()
        out['operating_receipt_match'] = True
        phase = 'construction'
        release = ReadOnlyRelease()
        bound = binding_module.Binding(types.SimpleNamespace(TARGET_COMMIT=EXPORT_SOURCE), helper, release, sources['exports_helper'], {'naver_product_export.py': sources['product_exporter'], 'naver_market_export.py': sources['market_exporter']})
        phase = 'prepared'
        bound.load(dict(PACKAGE), verify=False)
        phase = 'verify'
        try:
            bound.operation(lambda: helper.verify(bound.receipt, command=bound.command))
        except Exception as error:
            if type(error) is not helper.ExportInstallInvalid or error.args != ('EXPORT_RUN_NOT_VERIFIED',) or _failure_component(error, helper) != 'market_result':
                raise
            out['original_verify_error'] = 'market_result_EXPORT_RUN_NOT_VERIFIED'
        if out['original_verify_error'] is not None:
            phase = 'probe'
            out['probe'] = _verified_probe(bound, helper, sources)
            out['ok'] = out['probe']['status'] in ('source_limit', 'original_collect_passed', 'original_other_failure')
        phase = 'complete'
    except Exception:
        out['probe']['status'] = 'diagnostic_unavailable'
    out['phase'] = phase
    return out

def closed_json(result):
    if type(result) is not dict or set(result) != {'version', 'diagnostic', 'ok', 'phase', 'operating_receipt_match', 'source_pins_match', 'original_verify_error', 'probe'} or type(result['version']) is not int or (result['version'] != 1) or (result['diagnostic'] != 'market-source-limit-readonly-probe') or (result['phase'] not in set(PHASES) | {'probe'}) or any((type(result[k]) is not bool for k in ('ok', 'operating_receipt_match', 'source_pins_match'))) or (result['original_verify_error'] not in (None, 'market_result_EXPORT_RUN_NOT_VERIFIED')):
        raise ValueError('DIAGNOSTIC_RESULT')
    _probe_json(result['probe'])
    body = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(body) > MAX_OUTPUT:
        raise ValueError('DIAGNOSTIC_RESULT')
    return body.decode('utf-8')
