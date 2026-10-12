"""Fixed-unit, read-only failure hints. Never return or persist journal text."""
import json
import os
from pathlib import PurePosixPath
import re
import selectors
import stat
import subprocess
import sys
import time

MAX_RAW = 256 * 1024
MAX_LINE = 32768
MAX_RECORDS = 32
TIMEOUT = 8
MIN_TIMESTAMP_US = 946684800000000
MAX_TIMESTAMP_US = 4102444800000000
UNITS = {'product': 'naver-product-export.service', 'market': 'naver-market-export.service'}
PATH_ROLES = (
    ('code', '/opt/metainc/naver-saved-exports'),
    ('source_alias', '/run/naver-saved-source'),
    ('product_output', '/var/lib/metainc/naver-product-source'),
    ('market_output', '/var/lib/metainc/naver-market-source'))
METADATA_PATHS = (
    ('opt_root', '/opt'), ('opt_metainc', '/opt/metainc'),
    ('code_directory', '/opt/metainc/naver-saved-exports'),
    ('var_root', '/var'), ('var_lib', '/var/lib'), ('var_metainc', '/var/lib/metainc'),
    ('product_output', '/var/lib/metainc/naver-product-source'),
    ('market_output', '/var/lib/metainc/naver-market-source')) + tuple(
        (kind+'_'+suffix, '/etc/systemd/system/naver-'+kind+'-export.'+suffix)
        for kind in ('product', 'market') for suffix in ('service', 'timer'))
ERROR_PATTERNS = (
    ('permission_error', r'\bPermissionError\b'),
    ('permission_denied', r'\b(?:permission denied|access denied)\b'),
    ('python_cannot_open', r"\bpython[0-9.]*: can't open file\b"),
    ('statvfs', r'\bstatvfs\b'),
    ('namespace', r'failed at step namespace|failed to set up mount namespacing'),
    ('export_failed', r'\bEXPORT_FAILED\b'),
    ('readonly', r'read-only file system|attempt to write a readonly database'),
    ('sqlite_open', r'unable to open database file'),
    ('missing_file', r'no such file or directory|not a directory'),
    ('network_namespace', r'failed to set up network namespacing|failed at step network'),
    ('group_setup', r'failed at step group|failed to (?:set up|determine) (?:supplementary )?group'),
    ('user_setup', r'failed at step user|failed to (?:set up|determine) user'),
    ('stdout_setup', r'failed at step std(?:out|err|in)|failed to set up standard (?:input|output|error)'),
    ('execution_setup', r'failed at step exec|failed to execute'),
    ('directory_setup', r'failed at step chdir|failed to change (?:root|working) directory'),
    ('capability_setup', r'failed at step capabilities|failed to apply capabilities'),
    ('seccomp_setup', r'failed at step seccomp|failed to apply syscall'),
    ('apparmor_setup', r'failed at step apparmor|failed to apply apparmor'),
    ('cgroup_setup', r'failed to (?:attach to|create) cgroup'))


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('DUPLICATE')
        value[key] = item
    return value


def _timestamp(value):
    if type(value) is str and re.fullmatch(r'[1-9][0-9]{0,15}', value):
        value = int(value)
    if type(value) is not int or not MIN_TIMESTAMP_US <= value <= MAX_TIMESTAMP_US:
        raise ValueError('TIMESTAMP')
    return value


def _empty(kind, status):
    return {'kind': kind, 'status': status, 'first_timestamp_us': None,
            'last_timestamp_us': None, 'events': []}


def _labels(message):
    roles = set()
    for match in re.finditer(r'(?<![A-Za-z0-9_./-])(/[A-Za-z0-9_./-]+)', message):
        path = match.group(1)
        if str(PurePosixPath(path)) != path or '..' in PurePosixPath(path).parts:
            continue
        for role, root in PATH_ROLES:
            if path == root or path.startswith(root+'/'):
                roles.add(role)
    return sorted(roles), [label for label, pattern in ERROR_PATTERNS
                          if re.search(pattern, message, flags=re.IGNORECASE)]


def _project(raw, kind, now_us):
    """Select only the last invocation, including when it has no failure hint."""
    if kind not in UNITS or type(raw) is not bytes or len(raw) > MAX_RAW:
        return _empty(kind, 'invalid')
    try:
        now_us = _timestamp(now_us)
        lines = [line for line in raw.splitlines() if line.strip()]
        if len(lines) > MAX_RECORDS or any(len(line) > MAX_LINE for line in lines):
            return _empty(kind, 'limited')
        groups = {}
        for line in lines:
            value = json.loads(line, object_pairs_hook=_unique,
                               parse_constant=lambda value: (_ for _ in ()).throw(ValueError('NUMBER')))
            if type(value) is not dict:
                raise ValueError('RECORD')
            # Ignore manager/other-unit rows; never infer their invocation ID.
            if value.get('_SYSTEMD_UNIT') != UNITS[kind]:
                continue
            stamp = _timestamp(value.get('__REALTIME_TIMESTAMP'))
            if not now_us - 905000000 <= stamp <= now_us + 5000000:
                continue
            invocation = value.get('_SYSTEMD_INVOCATION_ID')
            message = value.get('MESSAGE')
            if (type(invocation) is not str or re.fullmatch(r'[0-9a-f]{32}', invocation) is None
                    or type(message) is not str or len(message.encode()) > MAX_LINE):
                raise ValueError('RECORD')
            roles, errors = _labels(message)
            groups.setdefault(invocation, []).append((stamp, roles, errors))
        if not groups:
            return _empty(kind, 'no_invocation')
        latest_time = max(max(row[0] for row in rows) for rows in groups.values())
        latest = [rows for rows in groups.values() if max(row[0] for row in rows) == latest_time]
        if len(latest) != 1:
            return _empty(kind, 'invalid')
        rows = sorted(latest[0], key=lambda row: row[0])
        return {'kind': kind, 'status': 'observed', 'first_timestamp_us': rows[0][0],
                'last_timestamp_us': rows[-1][0], 'events': [
                    {'timestamp_us': stamp, 'path_roles': roles, 'error_labels': errors}
                    for stamp, roles, errors in rows if roles or errors]}
    except (ValueError, UnicodeError, TypeError, RecursionError):
        return _empty(kind, 'invalid')


def _journal(kind):
    """Bound the pipe before buffering; stderr and raw text never leave memory."""
    process = None
    selector = selectors.DefaultSelector()
    try:
        process = subprocess.Popen(
            ['/usr/bin/journalctl', '--output=json', '--no-pager', '-n', '32', '-u',
             UNITS[kind], '--since', '-15min'], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, close_fds=True,
            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + TIMEOUT
        chunks = []; size = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                return None, 'unavailable'
            chunk = os.read(process.stdout.fileno(), min(65536, MAX_RAW + 1 - size))
            if not chunk:
                break
            chunks.append(chunk); size += len(chunk)
            if size > MAX_RAW:
                return None, 'limited'
        remaining = deadline - time.monotonic()
        if remaining <= 0 or process.wait(timeout=remaining) != 0:
            return None, 'unavailable'
        return b''.join(chunks), None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, 'unavailable'
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


def _metadata(role, path, blocked=False):
    result = {'role': role, 'exists': None, 'kind': 'blocked' if blocked else 'unavailable',
              'mode': None, 'uid': None, 'gid': None}
    if blocked:
        return result
    try:
        info = os.lstat(path)
        kind = ('directory' if stat.S_ISDIR(info.st_mode) else 'regular' if stat.S_ISREG(info.st_mode)
                else 'symlink' if stat.S_ISLNK(info.st_mode) else 'other')
        return {**result, 'exists': True, 'kind': kind, 'mode': format(stat.S_IMODE(info.st_mode), '04o'),
                'uid': info.st_uid if type(info.st_uid) is int and 0 <= info.st_uid <= 2147483647 else None,
                'gid': info.st_gid if type(info.st_gid) is int and 0 <= info.st_gid <= 2147483647 else None}
    except FileNotFoundError:
        return {**result, 'exists': False, 'kind': 'missing'}
    except OSError:
        return result


def inspect_host():
    """No arguments, source/DB opens, identities, environment or service changes."""
    now_us = time.time_ns() // 1000
    journals = []
    for kind in UNITS:
        raw, error = _journal(kind)
        journals.append(_empty(kind, error) if error else _project(raw, kind, now_us))
    paths = []; ancestry = {}
    for role, path in METADATA_PATHS:
        parent = str(PurePosixPath(path).parent)
        blocked = parent in ancestry and ancestry[parent] != 'directory'
        value = _metadata(role, path, blocked)
        ancestry[path] = value['kind']; paths.append(value)
    return {'version': 1, 'diagnostic_only': True, 'journals': journals, 'paths': paths,
            'source_writes': False, 'service_changes': False, 'network_calls': 0}


def main():
    if len(sys.argv) != 1:
        print('{"version":1,"error":"ARGUMENTS_NOT_SUPPORTED"}')
        return 2
    print(json.dumps(inspect_host(), sort_keys=True, separators=(',', ':'), allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
