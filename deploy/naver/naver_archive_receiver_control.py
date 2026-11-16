#!/usr/bin/env python3
"""Install/revoke one fixed B receiver authorization; no network or service mutation.

The caller authenticates the administrator channel and pins these source bytes.
Only closed JSON enters stdin. Private keys and raw SSH configuration never leave
this process. A failed published install retains evidence for exact revocation.
"""
import base64
import contextlib
import ctypes
import datetime
import errno
import hashlib
import ipaddress
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time

SESSION = 'naver-archives-20261106-v1'
RECEIVER_SHA256 = '68ced288ad852e88cf177a0ffa0c775f781129d75a8307dd0e387466931219c9'
ROOT = '/root/.metainc-naver-archive-receiver'
TOOL_DIR = ROOT + '/' + SESSION
TOOL = TOOL_DIR + '/receiver.py'
DATA_ROOT = '/var/backups/metainc-app-retirement'
DATA_DIR = DATA_ROOT + '/' + SESSION
SSH_DIR = '/root/.ssh'
PRIMARY = SSH_DIR + '/authorized_keys'
SECONDARY = SSH_DIR + '/authorized_keys2'
PENDING = SSH_DIR + '/.metainc-' + SESSION + '.pending'
COMMAND = '/usr/bin/python3 -I -B ' + TOOL
MIN_FREE = 15 * 1024 ** 3
MAX_REQUEST, MAX_RESULT, MAX_RECEIVER = 131072, 16384, 65536
OWNER_UID, OWNER_GID = 0, 0
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
HEX = re.compile(r'[0-9a-f]{64}\Z')
META_FIELDS = {'device', 'inode', 'uid', 'gid', 'mode', 'links', 'bytes'}
RESULT_FIELDS = {'version', 'action', 'session', 'status', 'error', 'receiver_sha256',
    'expires_at', 'source_ip', 'fetch_ip', 'send_key_sha256', 'fetch_key_sha256',
    'primary', 'primary_unchanged', 'secondary', 'secondary_published', 'pending',
    'tool_directory', 'data_directory', 'receiver'}
ERRORS = frozenset(('request_refused', 'root_required', 'platform_refused', 'receiver_mismatch',
    'public_key_refused', 'ip_refused', 'install_proof_refused', 'result_refused',
    'unsafe_directory', 'unsafe_file', 'path_changed', 'file_size_refused',
    'directory_exists', 'file_exists', 'secondary_exists', 'space_insufficient',
    'write_failed', 'write_verify_failed', 'atomic_publish_unavailable',
    'atomic_publish_failed', 'secondary_mismatch', 'secondary_changed',
    'authorization_refused', 'primary_changed', 'primary_recheck_failed',
    'sshd_check_failed', 'sshd_secondary_unavailable', 'deadline_exceeded',
    'operation_failed'))


class Refused(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'operation_failed'
        super().__init__(self.code)


def need(condition, code='request_refused'):
    if not condition:
        raise Refused(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def digest(value):
    return hashlib.sha256(value).hexdigest()


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


def public_key(value):
    need(type(value) is str and re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]{68}', value), 'public_key_refused')
    try:
        wire = base64.b64decode(value.split(' ')[1], validate=True)
    except ValueError:
        raise Refused('public_key_refused') from None
    need(len(wire) == 51 and wire[:19] == b'\0\0\0\x0bssh-ed25519\0\0\0\x20'
         and base64.b64encode(wire).decode('ascii') == value.split(' ')[1], 'public_key_refused')
    return value


def ipv4(value):
    try:
        need(type(value) is str and str(ipaddress.IPv4Address(value)) == value, 'ip_refused')
    except (ValueError, ipaddress.AddressValueError):
        raise Refused('ip_refused') from None
    return value


def expiry(value):
    need(type(value) is str and re.fullmatch(r'[0-9]{14}Z', value), 'result_refused')
    try:
        parsed = datetime.datetime.strptime(value, '%Y%m%d%H%M%SZ')
    except ValueError:
        raise Refused('result_refused') from None
    need(parsed.strftime('%Y%m%d%H%M%SZ') == value, 'result_refused')
    return value


def meta(info):
    return {'device': info.st_dev, 'inode': info.st_ino, 'uid': info.st_uid, 'gid': info.st_gid,
            'mode': stat.S_IMODE(info.st_mode), 'links': info.st_nlink, 'bytes': info.st_size}


def same(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid


def stamp(info):
    return same(info) + (info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def validate_result(value, *, owner=None):
    """Pure closed validator; owner injection is only for synthetic filesystem tests."""
    owner = (OWNER_UID, OWNER_GID) if owner is None else owner
    need(type(value) is dict and set(value) == RESULT_FIELDS, 'result_refused')
    need(type(value['version']) is int and value['version'] == 1
         and value['session'] == SESSION and value['receiver_sha256'] == RECEIVER_SHA256, 'result_refused')
    need(value['action'] in (None, 'install', 'revoke') and value['status'] in
         ('installed', 'revoked', 'already_absent', 'failed'), 'result_refused')
    failed = value['status'] == 'failed'
    need((type(value['error']) is str and value['error'] in ERRORS) if failed else value['error'] is None, 'result_refused')
    need(value['primary_unchanged'] is None or type(value['primary_unchanged']) is bool, 'result_refused')
    need(type(value['secondary_published']) is bool, 'result_refused')
    for name in ('source_ip', 'fetch_ip'):
        if value[name] is not None:
            ipv4(value[name])
    for name in ('send_key_sha256', 'fetch_key_sha256'):
        need(value[name] is None or type(value[name]) is str and HEX.fullmatch(value[name]), 'result_refused')
    if value['expires_at'] is not None:
        expiry(value['expires_at'])
    for name in ('primary', 'secondary', 'pending', 'tool_directory', 'data_directory', 'receiver'):
        row = value[name]
        if row is None:
            continue
        is_file = name not in ('tool_directory', 'data_directory')
        need(type(row) is dict and set(row) == META_FIELDS | ({'sha256'} if is_file else set()), 'result_refused')
        need(all(type(row[k]) is int and 0 <= row[k] <= 2 ** 63 - 1 for k in META_FIELDS), 'result_refused')
        need((row['uid'], row['gid']) == owner and row['mode'] == (0o600 if is_file else 0o700)
             and row['links'] >= 1, 'result_refused')
        if is_file:
            limit = 4096 if name in ('secondary', 'pending') else MAX_RECEIVER
            need(row['bytes'] <= limit, 'result_refused')
            need(row['links'] == 1 and type(row['sha256']) is str and HEX.fullmatch(row['sha256']), 'result_refused')
    if value['primary_unchanged'] is True:
        need(value['primary'] is not None, 'result_refused')
    if value['secondary_published']:
        need(value['secondary'] is not None and value['action'] is not None, 'result_refused')
        need(all(value[k] is not None for k in ('expires_at', 'source_ip', 'fetch_ip',
             'send_key_sha256', 'fetch_key_sha256')), 'result_refused')
        need(value['send_key_sha256'] != value['fetch_key_sha256'], 'result_refused')
    else:
        need(value['secondary'] is None, 'result_refused')
    if not failed:
        need(value['primary_unchanged'] is True and value['secondary_published'], 'result_refused')
        need(value['action'] == ('install' if value['status'] == 'installed' else 'revoke'), 'result_refused')
    if value['status'] == 'installed':
        need(all(value[k] is not None for k in ('receiver', 'tool_directory', 'data_directory', 'pending')), 'result_refused')
        need(value['receiver']['sha256'] == RECEIVER_SHA256 and value['pending'] == value['secondary'], 'result_refused')
    need(len(canonical(value)) <= MAX_RESULT, 'result_refused')
    return value


def empty_result(action=None):
    return dict(version=1, action=action, session=SESSION, status='failed', error='request_refused',
        receiver_sha256=RECEIVER_SHA256, expires_at=None, source_ip=None, fetch_ip=None,
        send_key_sha256=None, fetch_key_sha256=None, primary=None, primary_unchanged=None,
        secondary=None, secondary_published=False, pending=None, tool_directory=None,
        data_directory=None, receiver=None)


def validate_request(request, *, owner=None):
    need(type(request) is dict and request.get('action') in ('install', 'revoke'))
    if request['action'] == 'install':
        need(set(request) == {'action', 'send_public_key', 'fetch_public_key', 'source_ip', 'fetch_ip', 'receiver_b64'})
        public_key(request['send_public_key'])
        public_key(request['fetch_public_key'])
        need(request['send_public_key'] != request['fetch_public_key'], 'public_key_refused')
        ipv4(request['source_ip'])
        ipv4(request['fetch_ip'])
        need(type(request['receiver_b64']) is str and len(request['receiver_b64']) <= 4 * ((MAX_RECEIVER + 2) // 3), 'receiver_mismatch')
        try:
            receiver = base64.b64decode(request['receiver_b64'], validate=True)
        except ValueError:
            raise Refused('receiver_mismatch') from None
        need(0 < len(receiver) <= MAX_RECEIVER and digest(receiver) == RECEIVER_SHA256, 'receiver_mismatch')
        return receiver
    need(set(request) == {'action', 'installed'})
    installed = validate_result(request['installed'], owner=owner)
    need(installed['action'] == 'install' and installed['secondary_published']
         and installed['status'] in ('installed', 'failed'), 'install_proof_refused')
    return None


def authorization(request, expires):
    return ''.join('restrict,from="' + request[ip] + '",expiry-time="' + expires + '",command="'
        + COMMAND + '" ' + request[key] + '\n' for ip, key in
        (('source_ip', 'send_public_key'), ('fetch_ip', 'fetch_public_key'))).encode('ascii')


def validate_authorization(raw, installed):
    try:
        rows = raw.decode('ascii').splitlines(keepends=True)
        need(len(rows) == 2, 'authorization_refused')
        for row, ip, key in zip(rows, ('source_ip', 'fetch_ip'), ('send_key_sha256', 'fetch_key_sha256')):
            prefix = 'restrict,from="' + installed[ip] + '",expiry-time="' + installed['expires_at'] + '",command="' + COMMAND + '" '
            need(row.startswith(prefix) and row.endswith('\n') and '\r' not in row, 'authorization_refused')
            encoded = row[len(prefix):-1]
            public_key(encoded)
            need(digest(encoded.encode('ascii')) == installed[key], 'authorization_refused')
    except (UnicodeError, TypeError, KeyError):
        raise Refused('authorization_refused') from None


def rename_noreplace(parent, source, target):
    library = ctypes.CDLL(None, use_errno=True)
    try:
        rename = library.renameat2
    except AttributeError:
        raise Refused('atomic_publish_unavailable') from None
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent, source.encode('ascii'), parent, target.encode('ascii'), 1) != 0:
        raise Refused('secondary_exists' if ctypes.get_errno() == errno.EEXIST else 'atomic_publish_failed')


class Files:
    def __init__(self, root='/', uid=0, gid=0, rename=rename_noreplace):
        self.root, self.uid, self.gid, self.rename = root, uid, gid, rename

    @contextlib.contextmanager
    def directory(self, path, private=False):
        need(path.startswith('/') and all(n not in ('.', '..') for n in path.split('/')), 'unsafe_directory')
        with contextlib.ExitStack() as stack:
            fd = os.open(self.root, FLAGS)
            stack.callback(os.close, fd)
            root, initial, chain = fd, same(os.fstat(fd)), []
            def safe(info):
                need(stat.S_ISDIR(info.st_mode) and (info.st_uid, info.st_gid) == (self.uid, self.gid)
                     and not info.st_mode & 0o022, 'unsafe_directory')
            safe(os.fstat(fd))
            for name in filter(None, path.split('/')):
                before = os.stat(name, dir_fd=fd, follow_symlinks=False)
                safe(before)
                child = os.open(name, FLAGS, dir_fd=fd)
                stack.callback(os.close, child)
                need(same(before) == same(os.fstat(child)), 'path_changed')
                chain.append((fd, name, child, same(before)))
                fd = child
            if private:
                need(stat.S_IMODE(os.fstat(fd).st_mode) == 0o700, 'unsafe_directory')
            yield fd
            need(same(os.fstat(root)) == initial, 'path_changed')
            for parent, name, child, expected in chain:
                need(same(os.stat(name, dir_fd=parent, follow_symlinks=False)) == expected
                     == same(os.fstat(child)), 'path_changed')

    @contextlib.contextmanager
    def parent(self, path):
        parent, name = path.rsplit('/', 1)
        with self.directory(parent) as fd:
            yield fd, name

    def absent(self, path):
        with self.parent(path) as (fd, name):
            try:
                os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return True
            return False

    def mkdir(self, path, existing=False):
        with self.parent(path) as (fd, name):
            try:
                os.mkdir(name, 0o700, dir_fd=fd)
            except FileExistsError:
                need(existing, 'directory_exists')
            with self.directory(path, True) as child:
                result = meta(os.fstat(child))
            os.fsync(fd)
            return result

    def read(self, path, limit):
        with self.parent(path) as (parent, name):
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            need(stat.S_ISREG(before.st_mode) and (before.st_uid, before.st_gid) == (self.uid, self.gid)
                 and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600
                 and 0 <= before.st_size <= limit, 'unsafe_file')
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
            try:
                need(stamp(os.fstat(fd)) == stamp(before), 'path_changed')
                raw = bytearray()
                while True:
                    block = os.read(fd, min(8192, limit + 1 - len(raw)))
                    if not block:
                        break
                    raw.extend(block)
                    need(len(raw) <= limit, 'file_size_refused')
                need(len(raw) == before.st_size and stamp(os.fstat(fd)) == stamp(before)
                     == stamp(os.stat(name, dir_fd=parent, follow_symlinks=False)), 'path_changed')
                return bytes(raw), dict(meta(before), sha256=digest(raw))
            finally:
                os.close(fd)

    def write(self, path, raw):
        with self.parent(path) as (parent, name):
            try:
                fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=parent)
            except FileExistsError:
                raise Refused('file_exists') from None
            try:
                view = memoryview(raw)
                while view:
                    count = os.write(fd, view)
                    need(count > 0, 'write_failed')
                    view = view[count:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(parent)
        actual, metadata = self.read(path, len(raw))
        need(actual == raw, 'write_verify_failed')
        return metadata

    def publish(self, expected, result):
        with self.directory(SSH_DIR, True) as parent:
            _, actual = self.read(PENDING, 4096)
            need(actual == expected, 'secondary_mismatch')
            self.rename(parent, PENDING.rsplit('/', 1)[1], 'authorized_keys2')
            # Preserve exact revocation evidence before any fallible post-publish work.
            result['secondary'], result['secondary_published'] = expected, True
            os.fsync(parent)

    def revoke(self, expected, installed):
        with self.directory(SSH_DIR, True) as parent:
            before = os.stat('authorized_keys2', dir_fd=parent, follow_symlinks=False)
            raw, actual = self.read(SECONDARY, 4096)
            need(actual == expected, 'secondary_mismatch')
            validate_authorization(raw, installed)
            need(stamp(os.stat('authorized_keys2', dir_fd=parent, follow_symlinks=False)) == stamp(before),
                 'secondary_changed')
            os.unlink('authorized_keys2', dir_fd=parent)
            os.fsync(parent)


def sshd_secondary(ip):
    ipv4(ip)
    argv = ['/usr/sbin/sshd', '-T', '-C', 'user=root,host=' + ip + ',addr=' + ip + ',laddr=139.162.109.181,lport=22']
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}, shell=False, start_new_session=True)
    try:
        output, count, end = bytearray(), 0, time.monotonic() + 10
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, True)
            selector.register(process.stderr, selectors.EVENT_READ, False)
            while selector.get_map():
                need(time.monotonic() < end, 'sshd_check_failed')
                for key, _ in selector.select(.1):
                    block = os.read(key.fd, 8192)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    count += len(block)
                    need(count <= 65536, 'sshd_check_failed')
                    if key.data:
                        output.extend(block)
        need(process.wait(timeout=1) == 0, 'sshd_check_failed')
        validate_sshd(bytes(output))
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
        process.stdout.close()
        process.stderr.close()


def validate_sshd(raw):
    fields = (b'authorizedkeysfile', b'pubkeyauthentication', b'forcecommand', b'permitrootlogin')
    rows = {}
    for line in raw.splitlines():
        name, _, value = line.partition(b' ')
        if name in fields:
            need(name not in rows, 'sshd_check_failed')
            rows[name] = value
    need(rows.get(b'authorizedkeysfile') == b'.ssh/authorized_keys .ssh/authorized_keys2'
         and rows.get(b'pubkeyauthentication') == b'yes' and rows.get(b'forcecommand') == b'none'
         and rows.get(b'permitrootlogin') in (b'yes', b'prohibit-password', b'without-password'),
         'sshd_secondary_unavailable')


def perform(request, *, files=None, check_sshd=sshd_secondary, now=None):
    files = files or Files()
    action = request.get('action') if type(request) is dict else None
    result = empty_result(action if action in ('install', 'revoke') else None)
    writes_started = False
    try:
        receiver = validate_request(request, owner=(files.uid, files.gid))
        with files.directory('/root', True), files.directory(SSH_DIR, True):
            pass
        _, result['primary'] = files.read(PRIMARY, 65536)
        if action == 'install':
            for key in ('source_ip', 'fetch_ip'):
                result[key] = request[key]
                check_sshd(request[key])
            result['send_key_sha256'] = digest(request['send_public_key'].encode('ascii'))
            result['fetch_key_sha256'] = digest(request['fetch_public_key'].encode('ascii'))
            current = now or datetime.datetime.now(datetime.timezone.utc)
            result['expires_at'] = (current + datetime.timedelta(minutes=180)).strftime('%Y%m%d%H%M%SZ')
            raw = authorization(request, result['expires_at'])
            need(files.absent(SECONDARY) and files.absent(PENDING), 'secondary_exists')
            with files.directory(DATA_ROOT, True) as data:
                space = os.fstatvfs(data)
                need(space.f_bavail * space.f_frsize >= MIN_FREE, 'space_insufficient')
            need(files.absent(DATA_DIR), 'directory_exists')
            if not files.absent(ROOT):
                with files.directory(ROOT, True):
                    pass
                need(files.absent(TOOL_DIR), 'directory_exists')
            # All variable assets and existing paths are checked before the first write.
            writes_started = True
            files.mkdir(ROOT, existing=True)
            result['tool_directory'] = files.mkdir(TOOL_DIR)
            result['data_directory'] = files.mkdir(DATA_DIR)
            result['receiver'] = files.write(TOOL, receiver)
            result['pending'] = files.write(PENDING, raw)
            need(files.read(PRIMARY, 65536)[1] == result['primary'], 'primary_changed')
            files.publish(result['pending'], result)
            actual, metadata = files.read(SECONDARY, 4096)
            need(actual == raw and metadata == result['secondary'], 'secondary_mismatch')
            need(files.read(TOOL, MAX_RECEIVER)[1] == result['receiver'], 'receiver_mismatch')
            with files.directory(TOOL_DIR, True) as folder:
                result['tool_directory'] = meta(os.fstat(folder))
            with files.directory(DATA_DIR, True) as folder:
                result['data_directory'] = meta(os.fstat(folder))
            result['status'], result['error'] = 'installed', None
        else:
            installed = request['installed']
            for key in ('expires_at', 'source_ip', 'fetch_ip', 'send_key_sha256', 'fetch_key_sha256',
                        'secondary', 'secondary_published', 'pending', 'tool_directory', 'data_directory', 'receiver'):
                result[key] = installed[key]
            if files.absent(SECONDARY):
                result['status'] = 'already_absent'
            else:
                files.revoke(installed['secondary'], installed)
                need(files.absent(SECONDARY), 'secondary_changed')
                result['status'] = 'revoked'
            result['error'] = None
    except Refused as error:
        result['status'], result['error'] = 'failed', error.code
    except BaseException:
        result['status'], result['error'] = 'failed', 'operation_failed'
    finally:
        if writes_started and result['status'] == 'failed':
            # Report safely observable partial artifacts. Null remains unknown;
            # it never authorizes cleanup or means the path is absent.
            for name, path in (('tool_directory', TOOL_DIR), ('data_directory', DATA_DIR)):
                if result[name] is None:
                    try:
                        with files.directory(path, True) as folder:
                            result[name] = meta(os.fstat(folder))
                    except BaseException:
                        pass
            for name, path, limit in (('receiver', TOOL, MAX_RECEIVER), ('pending', PENDING, 4096)):
                if result[name] is None:
                    try:
                        result[name] = files.read(path, limit)[1]
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
    return validate_result(result, owner=(files.uid, files.gid))


def main():
    result = empty_result()
    old_handler, mask = signal.getsignal(signal.SIGALRM), os.umask(0o077)
    def expired(*_):
        raise Refused('deadline_exceeded')
    try:
        need(os.geteuid() == 0, 'root_required')
        need(sys.platform.startswith('linux'), 'platform_refused')
        need(len(sys.argv) == 1)
        signal.signal(signal.SIGALRM, expired)
        signal.alarm(60)
        raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
        need(0 < len(raw) <= MAX_REQUEST)
        result = perform(strict_json(raw))
    except Refused as error:
        result['error'] = error.code
    except BaseException:
        result['error'] = 'operation_failed'
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        os.umask(mask)
    print(canonical(validate_result(result)).decode('ascii'), flush=True)
    return 0 if result['status'] != 'failed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
