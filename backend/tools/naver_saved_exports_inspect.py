"""Metadata-only, fixed-candidate preflight for the saved-export release.

No SQLite connection, file-body read, environment inspection, network, service
change or arbitrary path is supported. This is intentionally independent of the
unsealed completion profile. Its result does not establish export readability,
successful collection or engine readiness; those require the actual one-shots.
"""
import grp
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys

SOURCE_DIRECTORY = Path('/root/logic-analysis-deploy/data')
DATABASE_NAME = 'logic_data.db'
ENGINE_DIRECTORY = Path('/var/lib/metainc/naver-engine')
PYTHONS = ('/usr/bin/python3', '/usr/local/bin/python3')
SYSTEMCTL = '/usr/bin/systemctl'
SYSTEMD_ANALYZE = '/usr/bin/systemd-analyze'
EXPORTER_CANDIDATE = 'naver-saved-export'
NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]{0,63}\Z')


def _name(value):
    return value if isinstance(value, str) and NAME.fullmatch(value) else None


def _metadata(path):
    """lstat only: never follow a source symlink or open any file body."""
    result = {'path': str(path), 'exists': False, 'kind': 'missing',
              'uid': None, 'gid': None, 'mode': None, 'device': None,
              'inode': None, 'error': None}
    try:
        item = os.lstat(path)
    except FileNotFoundError:
        return result
    except OSError:
        return {**result, 'kind': 'unknown', 'error': 'STAT_UNAVAILABLE'}
    kind = ('symlink' if stat.S_ISLNK(item.st_mode) else
            'directory' if stat.S_ISDIR(item.st_mode) else
            'regular' if stat.S_ISREG(item.st_mode) else 'other')
    return {**result, 'exists': True, 'kind': kind, 'uid': item.st_uid,
            'gid': item.st_gid, 'mode': format(stat.S_IMODE(item.st_mode), '04o'),
            'device': item.st_dev, 'inode': item.st_ino}


def _blocked(path):
    return {'path': str(path), 'exists': None, 'kind': 'unknown', 'uid': None,
            'gid': None, 'mode': None, 'device': None, 'inode': None,
            'error': 'SOURCE_PATH_UNAVAILABLE'}


def _group(gid):
    try:
        group = grp.getgrgid(gid)
        return {'gid': gid, 'exists': True, 'name': _name(group.gr_name)}
    except KeyError:
        return {'gid': gid, 'exists': False, 'name': None}
    except OSError:
        return {'gid': gid, 'exists': None, 'name': None}


def _account(*, uid=None, name=None):
    result = {'exists': False, 'uid': uid, 'name': name, 'primary_gid': None,
              'groups': [], 'groups_complete': False}
    try:
        account = pwd.getpwuid(uid) if uid is not None else pwd.getpwnam(name)
    except KeyError:
        return result
    except OSError:
        return {**result, 'exists': None}
    result.update(exists=True, uid=account.pw_uid, name=_name(account.pw_name),
                  primary_gid=account.pw_gid)
    if result['name'] is None:
        return result
    try:
        # Resolve only the two explicitly requested accounts, never enumerate
        # passwd/group or expose home directories, shells or group members.
        gids = sorted(set(os.getgrouplist(account.pw_name, account.pw_gid)))
        result['groups'] = [_group(gid) for gid in gids[:32]]
        result['groups_complete'] = len(gids) <= 32
    except (OSError, KeyError):
        result['groups'] = [_group(account.pw_gid)]
    return result


def _executable(path):
    entry = _metadata(path)
    # Standard runtime executables may be symlinks. Report only the followed
    # stat, never its target path; source/database symlinks stay disallowed.
    target = {'regular': False, 'root_owned_nonwritable': False}
    try:
        item = os.stat(path)
        target = {'regular': stat.S_ISREG(item.st_mode),
                  'root_owned_nonwritable': bool(stat.S_ISREG(item.st_mode) and
                                                item.st_uid == 0 and
                                                not item.st_mode & 0o022)}
    except OSError:
        pass
    return {**entry, **target}


def _systemd_version(binary):
    if not binary['root_owned_nonwritable']:
        return None
    try:
        result = subprocess.run([SYSTEMCTL, '--version'], check=False,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=3, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        # The exact standard binary's version command is the sole subprocess.
        # Never return feature flags, paths, raw output or diagnostics.
        if result.returncode != 0 or len(result.stdout) > 4096:
            return None
        first = result.stdout.splitlines()[0] if result.stdout else b''
        match = re.fullmatch(rb'systemd ([0-9]{1,4})(?:[ \t].*)?', first)
        return int(match.group(1)) if match else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def inspect_host():
    """Return a closed, private metadata projection; accepts no user input."""
    ancestry = []
    for path in reversed(SOURCE_DIRECTORY.parents):
        ancestry.append(_metadata(path) if all(item['kind'] == 'directory' for item in ancestry)
                        else _blocked(path))
    directory = (_metadata(SOURCE_DIRECTORY) if all(item['kind'] == 'directory' for item in ancestry)
                 else _blocked(SOURCE_DIRECTORY))
    source_stat = _metadata if directory['kind'] == 'directory' else _blocked
    database = source_stat(SOURCE_DIRECTORY / DATABASE_NAME)
    wal = source_stat(SOURCE_DIRECTORY / (DATABASE_NAME + '-wal'))
    shm = source_stat(SOURCE_DIRECTORY / (DATABASE_NAME + '-shm'))
    structurally_valid = (directory['kind'] == 'directory' and
                          database['kind'] == 'regular' and
                          all(item['kind'] == 'directory' for item in ancestry) and
                          all(item['kind'] in ('missing', 'regular') for item in (wal, shm)))
    systemctl = _executable(SYSTEMCTL)
    source_groups = sorted({item['gid'] for item in (directory, database, wal, shm)
                            if item['gid'] is not None})
    return {'version': 1, 'metadata_only': True,
            'source': {'source_directory': str(SOURCE_DIRECTORY),
                       'database_name': DATABASE_NAME, 'directory': directory,
                       'database': database, 'wal': wal, 'shm': shm,
                       'ancestry': ancestry, 'groups': [_group(gid) for gid in source_groups],
                       'structure_valid': structurally_valid,
                       'database_opened': False, 'readability_verified': False,
                       'readonly_namespace_verified': False},
            'engine_directory': _metadata(ENGINE_DIRECTORY),
            'identity': {'uid_10001': _account(uid=10001),
                         'group_10001': _group(10001),
                         'exporter_candidate': _account(name=EXPORTER_CANDIDATE)},
            'runtime': {'python_candidates': [_executable(path) for path in PYTHONS],
                        'inspector_python_version': list(sys.version_info[:3]),
                        'systemctl': systemctl,
                        'systemd_analyze': _executable(SYSTEMD_ANALYZE),
                        'systemd_version': _systemd_version(systemctl)},
            'source_writes': False, 'service_changes': False, 'network_calls': 0}


def main():
    if len(sys.argv) != 1:
        print('{"version":1,"error":"ARGUMENTS_NOT_SUPPORTED"}')
        return 2
    print(json.dumps(inspect_host(), sort_keys=True, separators=(',', ':'), allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
