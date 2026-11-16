#!/usr/bin/env python3
"""One fixed, read-only full-cipher refetch lease; no resume or receive path.

The reviewed Mac bootstrap injects pinned L, LEGACY_SOURCE and MODULE_SOURCE.
Normal script execution only fetches. Control is an explicit bootstrap entrypoint.
Import and the config/result validators do not access files or execute commands.
"""
import base64
import contextlib
import datetime
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import signal
import stat
import sys
import time
import types

LEASE_ID = 'naver-archives-refetch-20261107-v1'
DATA_SESSION = 'naver-archives-20261106-v1'
DATA_DIR = '/var/backups/metainc-app-retirement/' + DATA_SESSION
CIPHER_PATH = DATA_DIR + '/archives.gpg'
LOCK_PATH = DATA_DIR + '/.receive.lock'
PARTIAL_PATH = DATA_DIR + '/archives.gpg.partial'
ROOT = '/root/.metainc-naver-archive-refetch'
TOOL_DIR = ROOT + '/' + LEASE_ID
TOOL = TOOL_DIR + '/refetch.py'
LEGACY_PATH = TOOL_DIR + '/legacy_control.py'
CONFIG_PATH = TOOL_DIR + '/config.json'
SSH_DIR = '/root/.ssh'
PRIMARY = SSH_DIR + '/authorized_keys'
SECONDARY = SSH_DIR + '/authorized_keys2'
PENDING = SSH_DIR + '/.metainc-' + LEASE_ID + '.pending'
OLD_PENDING = SSH_DIR + '/.metainc-' + DATA_SESSION + '.pending'
COMMAND = '/usr/bin/python3 -I -B ' + TOOL
FETCH_COMMAND = 'fetch-' + LEASE_ID
LEGACY_SHA256 = 'f058ae0585643b461fcaf5cdba7c43a48cebbfff9b43e15f7726231a0c92bebc'
SERVER_TIMEOUT, CLIENT_TIMEOUT = 14400, 16200
INSTALL_TIMEOUT, START_WINDOW, AUTH_SECONDS = 480, 1800, 21600
MAX_CIPHER, MAX_PLAN = 12 * 1024 ** 3, 256 * 1024
MAX_REQUEST, MAX_RESULT, MAX_ASSET = 512 * 1024, 16384, 131072
BLOCK = 1024 * 1024
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
HEX = re.compile(r'[0-9a-f]{64}\Z')
META_FIELDS = {'device', 'inode', 'uid', 'gid', 'mode', 'links', 'bytes'}
IDENTITY_FIELDS = META_FIELDS | {'mtime_ns', 'ctime_ns'}
BINDINGS = {'plan_sha256', 'sent_sha256', 'install_sha256', 'revoke_sha256'}
CONFIG_FIELDS = {'version', 'lease_id', 'data_session', 'cipher_path', 'cipher', 'bindings',
    'fetch_key_sha256', 'fetch_ip', 'issued_at', 'start_before', 'expires_at',
    'server_timeout', 'client_timeout', 'module_sha256', 'legacy_sha256',
    'lock_identity', 'data_identity'}
RESULT_FIELDS = {'version', 'action', 'lease_id', 'status', 'error', 'config', 'config_sha256',
    'primary', 'primary_unchanged', 'secondary', 'secondary_published', 'pending',
    'tool_directory', 'receiver', 'legacy', 'config_file'}
INSTALL_FIELDS = {'action', 'fetch_public_key', 'fetch_ip', 'cipher_bytes', 'cipher_sha256'} | {
    name + suffix for name in ('plan', 'sent', 'install', 'revoke') for suffix in ('_b64', '_sha256')}
ERRORS = frozenset(('request_refused', 'result_refused', 'config_refused', 'evidence_refused',
    'asset_refused', 'root_required', 'platform_refused', 'command_refused', 'start_expired',
    'unsafe_directory', 'unsafe_file', 'path_changed', 'file_size_refused', 'directory_exists',
    'file_exists', 'secondary_exists', 'secondary_mismatch', 'secondary_changed',
    'authorization_refused', 'primary_changed', 'primary_recheck_failed', 'public_key_refused',
    'ip_refused', 'sshd_check_failed', 'sshd_secondary_unavailable', 'write_failed',
    'write_verify_failed', 'atomic_publish_unavailable', 'atomic_publish_failed',
    'cipher_changed', 'cipher_mismatch', 'partial_exists', 'lock_refused', 'busy',
    'deadline_exceeded', 'stream_failed', 'operation_failed'))
L = globals().get('L')
LEGACY_SOURCE = globals().get('LEGACY_SOURCE')
MODULE_SOURCE = globals().get('MODULE_SOURCE')


class Refused(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'operation_failed'
        super().__init__(self.code)


class DeadlineExpired(BaseException):
    pass


def need(condition, code='request_refused'):
    if not condition:
        raise Refused(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result)
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(Refused('request_refused')))
    except (ValueError, UnicodeError, RecursionError):
        raise Refused('request_refused') from None


def hash_ok(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def number(value, limit=2 ** 63 - 1):
    return type(value) is int and 0 <= value <= limit


def identity(info):
    return dict(device=info.st_dev, inode=info.st_ino, uid=info.st_uid, gid=info.st_gid,
        mode=stat.S_IMODE(info.st_mode), links=info.st_nlink, bytes=info.st_size,
        mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)


def ipv4(value):
    try:
        need(type(value) is str and str(ipaddress.IPv4Address(value)) == value, 'ip_refused')
    except ValueError:
        raise Refused('ip_refused') from None
    return value


def parse_time(value):
    need(type(value) is str and re.fullmatch(r'[0-9]{14}Z', value), 'config_refused')
    try:
        parsed = datetime.datetime.strptime(value, '%Y%m%d%H%M%SZ').replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        raise Refused('config_refused') from None
    need(parsed.strftime('%Y%m%d%H%M%SZ') == value, 'config_refused')
    return parsed


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def stamp_time(value):
    need(isinstance(value, datetime.datetime) and value.utcoffset() == datetime.timedelta(0), 'config_refused')
    return value.strftime('%Y%m%d%H%M%SZ')


def check_deadline(deadline):
    need(time.monotonic() < deadline, 'deadline_exceeded')


def read_runtime_asset(path, limit):
    """Load pinned code before legacy Files is available; fixed paths only."""
    need(path in (TOOL, LEGACY_PATH), 'asset_refused')
    with contextlib.ExitStack() as stack:
        parent = os.open('/', FLAGS)
        stack.callback(os.close, parent)
        root_info = os.fstat(parent)
        need(stat.S_ISDIR(root_info.st_mode) and root_info.st_uid == root_info.st_gid == 0
             and not root_info.st_mode & 0o022, 'asset_refused')
        chain = []
        for name in path.split('/')[1:-1]:
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            need(stat.S_ISDIR(before.st_mode) and before.st_uid == before.st_gid == 0
                 and not before.st_mode & 0o022, 'asset_refused')
            child = os.open(name, FLAGS, dir_fd=parent)
            stack.callback(os.close, child)
            need(identity(os.fstat(child)) == identity(before), 'asset_refused')
            chain.append((parent, name, child, identity(before)))
            parent = child
        fd = os.open(path.rsplit('/', 1)[1], READ_FLAGS, dir_fd=parent)
        stack.callback(os.close, fd)
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_uid == before.st_gid == 0
             and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1
             and 0 < before.st_size <= limit, 'asset_refused')
        raw = bytearray()
        while len(raw) <= limit:
            block = os.read(fd, min(8192, limit + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
        need(len(raw) == before.st_size and identity(os.fstat(fd)) == identity(before)
             == identity(os.stat(path.rsplit('/', 1)[1], dir_fd=parent, follow_symlinks=False)), 'asset_refused')
        for p, name, child, expected in chain:
            need(identity(os.stat(name, dir_fd=p, follow_symlinks=False)) == expected
                 == identity(os.fstat(child)), 'asset_refused')
        return bytes(raw)


def legacy():
    global L, LEGACY_SOURCE
    if LEGACY_SOURCE is None:
        LEGACY_SOURCE = read_runtime_asset(LEGACY_PATH, MAX_ASSET)
    need(type(LEGACY_SOURCE) is bytes and digest(LEGACY_SOURCE) == LEGACY_SHA256, 'asset_refused')
    if L is None:
        L = types.ModuleType('naver_refetch_legacy_control')
        exec(compile(LEGACY_SOURCE, '<pinned-legacy-control>', 'exec'), L.__dict__)
    elif isinstance(L, dict):
        L = types.SimpleNamespace(**L)
    return L


def module_source():
    raw = MODULE_SOURCE if MODULE_SOURCE is not None else read_runtime_asset(TOOL, MAX_ASSET)
    need(type(raw) is bytes and 0 < len(raw) <= MAX_ASSET, 'asset_refused')
    return raw


def evidence(request, name, limit, require_canonical=False):
    encoded, expected = request[name + '_b64'], request[name + '_sha256']
    need(type(encoded) is str and len(encoded) <= 4 * ((limit + 2) // 3) and hash_ok(expected), 'evidence_refused')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise Refused('evidence_refused') from None
    need(0 < len(raw) <= limit and digest(raw) == expected, 'evidence_refused')
    value = strict_json(raw)
    need(not require_canonical or canonical(value) == raw, 'evidence_refused')
    return value


def validate_request(value, *, owner=None):
    owner = (0, 0) if owner is None else owner
    need(type(value) is dict and value.get('action') in ('install', 'revoke'))
    if value['action'] == 'revoke':
        need(set(value) == {'action', 'installed'})
        installed = validate_result(value['installed'], owner=owner)
        need(installed['action'] == 'install' and installed['secondary_published']
             and installed['status'] in ('installed', 'failed'), 'evidence_refused')
        return value
    need(set(value) == INSTALL_FIELDS)
    old = legacy()
    old.public_key(value['fetch_public_key'])
    ipv4(value['fetch_ip'])
    need(number(value['cipher_bytes'], MAX_CIPHER) and value['cipher_bytes'] > 0
         and hash_ok(value['cipher_sha256']))
    plan = evidence(value, 'plan', MAX_PLAN, True)
    # The Mac validates the full source schema. Here only the closed envelope is
    # interpreted: no plan path ever becomes a server filesystem path.
    need(type(plan) is dict and set(plan) == {'version', 'session', 'groups', 'total_bytes'}
         and type(plan['version']) is int and plan['version'] == 1 and plan['session'] == DATA_SESSION
         and type(plan['groups']) is list and 1 <= len(plan['groups']) <= 64
         and number(plan['total_bytes'], 11 * 1024 ** 3), 'evidence_refused')
    sent = evidence(value, 'sent', 4096, True)
    need(type(sent) is dict and set(sent) == {'status', 'session', 'plan_sha256', 'bytes', 'sha256'}
         and sent['status'] == 'sent_unverified' and sent['session'] == DATA_SESSION
         and sent['plan_sha256'] == value['plan_sha256'] and type(sent['bytes']) is int
         and sent['bytes'] == value['cipher_bytes'] and sent['sha256'] == value['cipher_sha256'], 'evidence_refused')
    installed = old.validate_result(evidence(value, 'install', MAX_RESULT), owner=owner)
    revoked = old.validate_result(evidence(value, 'revoke', MAX_RESULT), owner=owner)
    need(installed['action'] == 'install' and installed['status'] == 'installed'
         and installed['primary_unchanged'] is True and installed['secondary_published']
         and revoked['action'] == 'revoke' and revoked['status'] in ('revoked', 'already_absent')
         and revoked['primary_unchanged'] is True, 'evidence_refused')
    need(all(installed[k] == revoked[k] for k in installed if k not in ('action', 'status', 'error')),
         'evidence_refused')
    need(digest(value['fetch_public_key'].encode('ascii')) == installed['fetch_key_sha256'], 'evidence_refused')
    return value


def validate_meta(row, *, owner, directory=False, full=False, limit=MAX_ASSET):
    expected = IDENTITY_FIELDS if full else META_FIELDS
    need(type(row) is dict and set(row) == expected, 'result_refused')
    need(all(number(v) for v in row.values()) and (row['uid'], row['gid']) == owner
         and row['mode'] == (0o700 if directory else 0o600)
         and (row['links'] >= 1 if directory else row['links'] == 1)
         and row['bytes'] <= limit, 'result_refused')


def validate_config(value, *, owner=None):
    owner = (0, 0) if owner is None else owner
    need(type(value) is dict and set(value) == CONFIG_FIELDS, 'config_refused')
    need(type(value['version']) is int and value['version'] == 1 and value['lease_id'] == LEASE_ID
         and value['data_session'] == DATA_SESSION and value['cipher_path'] == CIPHER_PATH
         and type(value['server_timeout']) is int and value['server_timeout'] == SERVER_TIMEOUT
         and type(value['client_timeout']) is int and value['client_timeout'] == CLIENT_TIMEOUT
         and value['legacy_sha256'] == LEGACY_SHA256 and hash_ok(value['module_sha256'])
         and hash_ok(value['fetch_key_sha256']), 'config_refused')
    ipv4(value['fetch_ip'])
    issued, start, expires = (parse_time(value[k]) for k in ('issued_at', 'start_before', 'expires_at'))
    need(start - issued == datetime.timedelta(seconds=START_WINDOW)
         and expires - issued == datetime.timedelta(seconds=AUTH_SECONDS), 'config_refused')
    bindings = value['bindings']
    need(type(bindings) is dict and set(bindings) == BINDINGS and all(hash_ok(v) for v in bindings.values()), 'config_refused')
    cipher = value['cipher']
    need(type(cipher) is dict and set(cipher) == {'bytes', 'sha256', 'identity'}
         and number(cipher['bytes'], MAX_CIPHER) and cipher['bytes'] > 0 and hash_ok(cipher['sha256']), 'config_refused')
    validate_meta(cipher['identity'], owner=owner, full=True, limit=MAX_CIPHER)
    need(cipher['bytes'] == cipher['identity']['bytes'], 'config_refused')
    validate_meta(value['lock_identity'], owner=owner, full=True, limit=0)
    validate_meta(value['data_identity'], owner=owner, directory=True, full=True)
    need(cipher['identity']['device'] == value['lock_identity']['device'] == value['data_identity']['device']
         and cipher['identity']['inode'] != value['lock_identity']['inode'], 'config_refused')
    need(len(canonical(value)) <= MAX_RESULT, 'config_refused')
    return value


def build_config(request, cipher_identity, issued_at, *, lock_identity, data_identity):
    issued_at = parse_time(issued_at) if isinstance(issued_at, str) else issued_at
    result = dict(version=1, lease_id=LEASE_ID, data_session=DATA_SESSION, cipher_path=CIPHER_PATH,
        cipher=dict(bytes=request['cipher_bytes'], sha256=request['cipher_sha256'], identity=cipher_identity),
        bindings={name: request[name] for name in BINDINGS},
        fetch_key_sha256=digest(request['fetch_public_key'].encode('ascii')), fetch_ip=request['fetch_ip'],
        issued_at=stamp_time(issued_at), start_before=stamp_time(issued_at + datetime.timedelta(seconds=START_WINDOW)),
        expires_at=stamp_time(issued_at + datetime.timedelta(seconds=AUTH_SECONDS)),
        server_timeout=SERVER_TIMEOUT, client_timeout=CLIENT_TIMEOUT,
        module_sha256=digest(module_source()), legacy_sha256=LEGACY_SHA256,
        lock_identity=lock_identity, data_identity=data_identity)
    return validate_config(result, owner=(cipher_identity['uid'], cipher_identity['gid']))


def empty_result(action=None):
    return dict(version=1, action=action, lease_id=LEASE_ID, status='failed', error='request_refused',
        config=None, config_sha256=None, primary=None, primary_unchanged=None,
        secondary=None, secondary_published=False, pending=None, tool_directory=None,
        receiver=None, legacy=None, config_file=None)


def validate_result(value, *, owner=None):
    owner = (0, 0) if owner is None else owner
    need(type(value) is dict and set(value) == RESULT_FIELDS, 'result_refused')
    need(type(value['version']) is int and value['version'] == 1 and value['lease_id'] == LEASE_ID
         and value['action'] in (None, 'install', 'revoke')
         and value['status'] in ('installed', 'revoked', 'already_absent', 'failed'), 'result_refused')
    failed = value['status'] == 'failed'
    need((type(value['error']) is str and value['error'] in ERRORS) if failed else value['error'] is None, 'result_refused')
    need(value['primary_unchanged'] is None or type(value['primary_unchanged']) is bool, 'result_refused')
    need(type(value['secondary_published']) is bool, 'result_refused')
    if value['config'] is None:
        need(value['config_sha256'] is None, 'result_refused')
    else:
        validate_config(value['config'], owner=owner)
        need(value['config_sha256'] == digest(canonical(value['config'])), 'result_refused')
    for name in ('primary', 'secondary', 'pending', 'tool_directory', 'receiver', 'legacy', 'config_file'):
        row = value[name]
        if row is None:
            continue
        directory = name == 'tool_directory'
        need(type(row) is dict and set(row) == META_FIELDS | (set() if directory else {'sha256'}), 'result_refused')
        validate_meta({k: row[k] for k in META_FIELDS}, owner=owner, directory=directory,
                      limit=4096 if name in ('secondary', 'pending') else MAX_ASSET)
        need(directory or hash_ok(row['sha256']), 'result_refused')
    if value['primary_unchanged'] is True:
        need(value['primary'] is not None, 'result_refused')
    if value['secondary_published']:
        need(value['config'] is not None and value['secondary'] is not None and value['action'] is not None, 'result_refused')
    else:
        need(value['secondary'] is None, 'result_refused')
    if not failed:
        need(value['primary_unchanged'] is True and value['secondary_published']
             and value['action'] == ('install' if value['status'] == 'installed' else 'revoke'), 'result_refused')
    if value['status'] == 'installed':
        need(all(value[k] is not None for k in ('pending', 'tool_directory', 'receiver', 'legacy', 'config_file'))
             and value['pending'] == value['secondary']
             and value['receiver']['sha256'] == value['config']['module_sha256']
             and value['legacy']['sha256'] == LEGACY_SHA256
             and value['config_file']['sha256'] == value['config_sha256'], 'result_refused')
    need(len(canonical(value)) <= MAX_RESULT, 'result_refused')
    return value


class Cipher:
    """Existing data and lock only; no create, write, unlink, or chmod operations."""
    def __init__(self, files, deadline):
        self.files, self.deadline, self.stack = files, deadline, contextlib.ExitStack()

    def __enter__(self):
        try:
            old = legacy()
            self.folder = self.stack.enter_context(self.files.directory(DATA_DIR, True))
            self.data_identity = identity(os.fstat(self.folder))
            need(self.files.absent(PARTIAL_PATH), 'partial_exists')
            self.lock = os.open('.receive.lock', READ_FLAGS, dir_fd=self.folder)
            self.stack.callback(os.close, self.lock)
            info = os.fstat(self.lock)
            need(stat.S_ISREG(info.st_mode), 'lock_refused')
            self.lock_identity = identity(info)
            validate_meta(self.lock_identity, owner=(self.files.uid, self.files.gid), full=True, limit=0)
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused('busy') from None
            self.fd = os.open('archives.gpg', READ_FLAGS, dir_fd=self.folder)
            self.stack.callback(os.close, self.fd)
            info = os.fstat(self.fd)
            need(stat.S_ISREG(info.st_mode), 'cipher_changed')
            self.identity = identity(info)
            validate_meta(self.identity, owner=(self.files.uid, self.files.gid), full=True, limit=MAX_CIPHER)
            need(0 < info.st_size <= MAX_CIPHER and info.st_dev == self.lock_identity['device']
                 == self.data_identity['device'] and info.st_ino != self.lock_identity['inode'], 'cipher_changed')
            self.check()
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *args):
        self.stack.close()

    def check(self):
        check_deadline(self.deadline)
        with self.files.directory(DATA_DIR, True) as folder:
            need(identity(os.fstat(folder)) == self.data_identity == identity(os.fstat(self.folder)), 'path_changed')
            for name, fd, expected in (('.receive.lock', self.lock, self.lock_identity),
                                       ('archives.gpg', self.fd, self.identity)):
                need(identity(os.fstat(fd)) == expected == identity(os.stat(name, dir_fd=folder, follow_symlinks=False)),
                     'cipher_changed')
            try:
                os.stat('archives.gpg.partial', dir_fd=folder, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise Refused('partial_exists')

    def read(self, output=None):
        os.lseek(self.fd, 0, os.SEEK_SET)
        hashed, count = hashlib.sha256(), 0
        while True:
            self.check()
            data = os.read(self.fd, min(BLOCK, self.identity['bytes'] + 1 - count))
            if not data:
                break
            count += len(data)
            need(count <= self.identity['bytes'], 'cipher_changed')
            hashed.update(data)
            if output is not None:
                view = memoryview(data)
                while view:
                    check_deadline(self.deadline)
                    wrote = output.write(view)
                    need(type(wrote) is int and 0 < wrote <= len(view), 'stream_failed')
                    view = view[wrote:]
        self.check()
        need(count == self.identity['bytes'], 'cipher_changed')
        return {'bytes': count, 'sha256': hashed.hexdigest()}


def authorization(config, public_key):
    legacy().public_key(public_key)
    need(digest(public_key.encode('ascii')) == config['fetch_key_sha256'], 'authorization_refused')
    return ('restrict,from="' + config['fetch_ip'] + '",expiry-time="' + config['expires_at']
            + '",command="' + COMMAND + '" ' + public_key + '\n').encode('ascii')


def validate_authorization(raw, config):
    try:
        prefix = ('restrict,from="' + config['fetch_ip'] + '",expiry-time="' + config['expires_at']
                  + '",command="' + COMMAND + '" ')
        text = raw.decode('ascii')
        need(text.startswith(prefix) and text.endswith('\n') and text.count('\n') == 1
             and '\r' not in text, 'authorization_refused')
        need(authorization(config, text[len(prefix):-1]) == raw, 'authorization_refused')
    except (UnicodeError, ValueError, TypeError):
        raise Refused('authorization_refused') from None


def revoke(files, installed):
    with files.directory(SSH_DIR, True) as parent:
        before = os.stat('authorized_keys2', dir_fd=parent, follow_symlinks=False)
        raw, actual = files.read(SECONDARY, 4096)
        need(actual == installed['secondary'], 'secondary_mismatch')
        validate_authorization(raw, installed['config'])
        need(identity(os.stat('authorized_keys2', dir_fd=parent, follow_symlinks=False)) == identity(before), 'secondary_changed')
        os.unlink('authorized_keys2', dir_fd=parent)
        os.fsync(parent)


def perform(request, *, files=None, check_sshd=None, now=None):
    old = legacy()
    files = files or old.Files()
    check_sshd = check_sshd or old.sshd_secondary
    owner = files.uid, files.gid
    action = request.get('action') if type(request) is dict else None
    result = empty_result(action if action in ('install', 'revoke') else None)
    writes_started = False
    deadline = time.monotonic() + INSTALL_TIMEOUT
    try:
        validate_request(request, owner=owner)
        with files.directory('/root', True), files.directory(SSH_DIR, True):
            pass
        _, result['primary'] = files.read(PRIMARY, 65536)
        if action == 'revoke':
            installed = request['installed']
            for key in ('config', 'config_sha256', 'secondary', 'secondary_published', 'pending',
                        'tool_directory', 'receiver', 'legacy', 'config_file'):
                result[key] = installed[key]
            if files.absent(SECONDARY):
                result['status'] = 'already_absent'
            else:
                revoke(files, installed)
                need(files.absent(SECONDARY), 'secondary_changed')
                result['status'] = 'revoked'
            result['error'] = None
        else:
            old_install = evidence(request, 'install', MAX_RESULT)
            need(result['primary'] == old_install['primary'], 'primary_changed')
            need(files.absent(SECONDARY) and files.absent(OLD_PENDING) and files.absent(PENDING), 'secondary_exists')
            check_sshd(request['fetch_ip'])
            if not files.absent(ROOT):
                with files.directory(ROOT, True):
                    pass
                need(files.absent(TOOL_DIR), 'directory_exists')
            source = module_source()
            with Cipher(files, deadline) as cipher:
                need(cipher.read() == {'bytes': request['cipher_bytes'], 'sha256': request['cipher_sha256']}, 'cipher_mismatch')
                config = build_config(request, cipher.identity, now or utc_now(),
                    lock_identity=cipher.lock_identity, data_identity=cipher.data_identity)
                result['config'], result['config_sha256'] = config, digest(canonical(config))
                raw = authorization(config, request['fetch_public_key'])
                need(files.read(PRIMARY, 65536)[1] == result['primary'], 'primary_changed')
                need(files.absent(SECONDARY) and files.absent(OLD_PENDING) and files.absent(PENDING), 'secondary_exists')
                cipher.check()
                writes_started = True
                files.mkdir(ROOT, existing=True)
                result['tool_directory'] = files.mkdir(TOOL_DIR)
                result['receiver'] = files.write(TOOL, source)
                result['legacy'] = files.write(LEGACY_PATH, LEGACY_SOURCE)
                result['config_file'] = files.write(CONFIG_PATH, canonical(config))
                result['pending'] = files.write(PENDING, raw)
                need(files.read(PRIMARY, 65536)[1] == result['primary'], 'primary_changed')
                cipher.check()
                with files.directory(SSH_DIR, True) as parent:
                    need(files.read(PENDING, 4096)[1] == result['pending'], 'secondary_mismatch')
                    files.rename(parent, PENDING.rsplit('/', 1)[1], 'authorized_keys2')
                    result['secondary'], result['secondary_published'] = result['pending'], True
                    os.fsync(parent)
                need(files.read(SECONDARY, 4096) == (raw, result['secondary']), 'secondary_mismatch')
                for path, key, expected in ((TOOL, 'receiver', digest(source)),
                                           (LEGACY_PATH, 'legacy', LEGACY_SHA256),
                                           (CONFIG_PATH, 'config_file', result['config_sha256'])):
                    _, current = files.read(path, MAX_ASSET)
                    need(current == result[key] and current['sha256'] == expected, 'asset_refused')
                cipher.check()
                with files.directory(TOOL_DIR, True) as folder:
                    result['tool_directory'] = old.meta(os.fstat(folder))
                result['status'], result['error'] = 'installed', None
    except DeadlineExpired:
        result['status'], result['error'] = 'failed', 'deadline_exceeded'
    except BaseException as error:
        result['status'], result['error'] = 'failed', getattr(error, 'code', 'operation_failed')
        if result['error'] not in ERRORS:
            result['error'] = 'operation_failed'
    finally:
        if writes_started and result['status'] == 'failed':
            for key, path in (('receiver', TOOL), ('legacy', LEGACY_PATH), ('config_file', CONFIG_PATH), ('pending', PENDING)):
                if result[key] is None:
                    try:
                        result[key] = files.read(path, MAX_ASSET)[1]
                    except BaseException:
                        pass
            try:
                with files.directory(TOOL_DIR, True) as folder:
                    result['tool_directory'] = old.meta(os.fstat(folder))
            except BaseException:
                pass
            if result['pending'] is not None and not result['secondary_published']:
                try:
                    raw, metadata = files.read(SECONDARY, 4096)
                    need(metadata == result['pending'], 'secondary_mismatch')
                    validate_authorization(raw, result['config'])
                    result['secondary'], result['secondary_published'] = metadata, True
                except BaseException:
                    pass
        if result['primary'] is not None:
            try:
                result['primary_unchanged'] = files.read(PRIMARY, 65536)[1] == result['primary']
                if not result['primary_unchanged']:
                    result['status'], result['error'] = 'failed', 'primary_changed'
            except BaseException:
                result['primary_unchanged'] = False
                result['status'], result['error'] = 'failed', 'primary_recheck_failed'
    return validate_result(result, owner=owner)


def fetch(config, output, *, files=None, now=None, deadline=None):
    files = files or legacy().Files()
    validate_config(config, owner=(files.uid, files.gid))
    current = now or utc_now()
    need(parse_time(config['issued_at']) <= current <= parse_time(config['start_before'])
         and current < parse_time(config['expires_at']), 'start_expired')
    deadline = time.monotonic() + SERVER_TIMEOUT if deadline is None else deadline
    expected = {key: config['cipher'][key] for key in ('bytes', 'sha256')}
    with Cipher(files, deadline) as cipher:
        need(cipher.identity == config['cipher']['identity'] and cipher.lock_identity == config['lock_identity']
             and cipher.data_identity == config['data_identity'], 'cipher_changed')
        need(cipher.read() == expected, 'cipher_mismatch')
        need(cipher.read(output) == expected, 'cipher_mismatch')
        output.flush()
        cipher.check()
    return expected


def expired(*_):
    raise DeadlineExpired()


class UnbufferedOutput:
    """No Python stdout buffer may re-flush after the absolute alarm expires."""
    def __init__(self, fd):
        self.fd = fd

    def write(self, raw):
        return os.write(self.fd, raw)

    def flush(self):
        pass


def emit_error(code):
    """One bounded best-effort stderr record; a dead peer cannot delay exit."""
    raw = canonical({'status': 'failed', 'lease_id': LEASE_ID, 'error': code}) + b'\n'
    previous = None
    try:
        previous = fcntl.fcntl(2, fcntl.F_GETFL)
        fcntl.fcntl(2, fcntl.F_SETFL, previous | os.O_NONBLOCK)
        os.write(2, raw)
    except (OSError, ValueError):
        pass
    finally:
        if previous is not None:
            try:
                fcntl.fcntl(2, fcntl.F_SETFL, previous)
            except OSError:
                pass


def main_control():
    result = empty_result()
    previous, mask = signal.getsignal(signal.SIGALRM), os.umask(0o077)
    try:
        need(os.geteuid() == 0, 'root_required')
        need(sys.platform.startswith('linux'), 'platform_refused')
        need(len(sys.argv) == 1, 'command_refused')
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, INSTALL_TIMEOUT)
        raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
        need(0 < len(raw) <= MAX_REQUEST)
        result = perform(strict_json(raw))
    except DeadlineExpired:
        result['error'] = 'deadline_exceeded'
    except BaseException as error:
        result['error'] = getattr(error, 'code', 'operation_failed')
        if result['error'] not in ERRORS:
            result['error'] = 'operation_failed'
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        os.umask(mask)
    raw = canonical(validate_result(result))
    sys.stdout.buffer.write(raw + b'\n')
    sys.stdout.buffer.flush()
    return 0 if result['status'] in ('installed', 'revoked', 'already_absent') else 2


def main_fetch():
    previous, mask = signal.getsignal(signal.SIGALRM), os.umask(0o077)
    error = None
    try:
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, SERVER_TIMEOUT)
        need(os.geteuid() == 0, 'root_required')
        need(sys.platform.startswith('linux'), 'platform_refused')
        need(len(sys.argv) == 1 and os.environ.get('SSH_ORIGINAL_COMMAND') == FETCH_COMMAND, 'command_refused')
        old = legacy()
        files = old.Files()
        source = module_source()
        raw, _ = files.read(CONFIG_PATH, MAX_RESULT)
        config = validate_config(strict_json(raw))
        need(raw == canonical(config) and config['module_sha256'] == digest(source), 'asset_refused')
        with files.directory(TOOL_DIR, True):
            fetch(config, UnbufferedOutput(sys.stdout.fileno()), files=files)
        return 0
    except DeadlineExpired:
        error = 'deadline_exceeded'
    except BaseException as caught:
        error = getattr(caught, 'code', 'operation_failed')
        if error not in ERRORS:
            error = 'operation_failed'
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        os.umask(mask)
    # Never append a receipt or exception text to the binary ciphertext stream.
    emit_error(error)
    return 2


if __name__ == '__main__':
    sys.exit(main_fetch())
