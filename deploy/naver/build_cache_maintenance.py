"""Reclaim only unused Docker build cache older than 24 hours.

The plan binds the cache aggregate and all container identities/states. It is
not a per-cache-ID deletion list. Images, volumes, databases, backups and running
containers are never deletion targets. Public output is a closed numeric receipt.
"""
import contextlib
from decimal import Decimal
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys

DOCKER = ('/usr/bin/docker', '--host=unix:///var/run/docker.sock')
PRUNE = (*DOCKER, 'builder', 'prune', '--all', '--force', '--filter', 'until=24h')
DF = (*DOCKER, 'system', 'df', '--format', '{{json .}}')
PS = (*DOCKER, 'ps', '-aq', '--no-trunc')
INSPECT_FORMAT = ('{"id":{{json .Id}},"image":{{json .Image}},'
                  '"running":{{json .State.Running}},"pid":{{json .State.Pid}},'
                  '"started":{{json .State.StartedAt}},"restarts":{{json .RestartCount}}}')
CONFIRM = 'PRUNE_UNUSED_BUILD_CACHE_OLDER_THAN_24H'
SCOPE = 'unused-build-cache-older-than-24h'
SHA = re.compile(r'[0-9a-f]{64}\Z')
ID = re.compile(r'[0-9a-f]{64}\Z')
REASONS = frozenset(('PLAN_READY', 'PRUNED', 'INPUT_REFUSED', 'NOT_ROOT',
    'LOCKED', 'LOCK_PATH_REFUSED', 'DOCKER_READ_FAILED', 'SNAPSHOT_REFUSED',
    'ACTIVE_CACHE', 'PLAN_MISMATCH', 'PRUNE_FAILED', 'PRUNE_OUTCOME_UNKNOWN',
    'CONTAINER_CHANGED', 'INTERNAL_ERROR'))
NUMBERS = ('cache_count_before', 'cache_active_before', 'cache_size_before_bytes',
           'cache_reclaimable_before_bytes', 'containers_before', 'cache_count_after',
           'free_before_bytes', 'free_after_bytes', 'free_change_bytes', 'prune_exit_code')


class Refused(Exception):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def receipt(mode):
    return dict(version=1, status='refused', reason='INTERNAL_ERROR',
                mode=mode if mode in ('plan', 'apply') else 'invalid', scope=SCOPE,
                plan_sha256=None, prune_attempted=False, container_unchanged=None,
                **{name: None for name in NUMBERS})


def validate_report(value):
    expected = set(receipt('plan'))
    if type(value) is not dict or set(value) != expected:
        raise Refused('SNAPSHOT_REFUSED')
    if (type(value['version']) is not int or value['version'] != 1 or
            value['status'] not in ('planned', 'applied', 'refused') or
            value['mode'] not in ('plan', 'apply', 'invalid') or
            value['reason'] not in REASONS or value['scope'] != SCOPE or
            type(value['prune_attempted']) is not bool or
            (value['container_unchanged'] is not None and type(value['container_unchanged']) is not bool)):
        raise Refused('SNAPSHOT_REFUSED')
    if value['plan_sha256'] is not None and (type(value['plan_sha256']) is not str or
                                           not SHA.fullmatch(value['plan_sha256'])):
        raise Refused('SNAPSHOT_REFUSED')
    for name in NUMBERS:
        number = value[name]
        if number is not None and (type(number) is not int or abs(number) > 2 ** 63 or
                                  (name not in ('free_change_bytes', 'prune_exit_code') and number < 0)):
            raise Refused('SNAPSHOT_REFUSED')
    if value['status'] == 'planned' and (value['reason'] != 'PLAN_READY' or
            value['mode'] != 'plan' or value['prune_attempted'] or not value['plan_sha256']):
        raise Refused('SNAPSHOT_REFUSED')
    if value['status'] == 'applied' and (value['reason'] != 'PRUNED' or
            value['mode'] != 'apply' or not value['prune_attempted'] or
            value['container_unchanged'] is not True or value['prune_exit_code'] != 0):
        raise Refused('SNAPSHOT_REFUSED')
    return value


def run(command, timeout=30):
    return subprocess.run(command, capture_output=True, timeout=timeout,
                          env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root',
                               'LANG': 'C.UTF-8', 'DOCKER_CONFIG': '/var/empty'})


def read(command, runner):
    result = runner(command)
    if result.returncode != 0 or len(result.stdout) > 1048576:
        raise Refused('DOCKER_READ_FAILED')
    try:
        return result.stdout.decode('utf-8')
    except (UnicodeDecodeError, AttributeError):
        raise Refused('SNAPSHOT_REFUSED') from None


def count(value):
    if type(value) is not str or not re.fullmatch(r'[0-9]{1,12}', value):
        raise Refused('SNAPSHOT_REFUSED')
    return int(value)


def size(value, reclaimable=False):
    if type(value) is not str:
        raise Refused('SNAPSHOT_REFUSED')
    suffix = r'(?: \([0-9]{1,3}%\))?' if reclaimable else ''
    match = re.fullmatch(r'([0-9]{1,12}(?:\.[0-9]{1,9})?)\s*(B|kB|KB|MB|GB|TB)' + suffix, value)
    if not match:
        raise Refused('SNAPSHOT_REFUSED')
    units = {'B': 1, 'kB': 1000, 'KB': 1000, 'MB': 1000 ** 2, 'GB': 1000 ** 3, 'TB': 1000 ** 4}
    return int(Decimal(match[1]) * units[match[2]])


def snapshot(runner=run):
    try:
        rows = [json.loads(line) for line in read(DF, runner).splitlines() if line]
        cache = [row for row in rows if type(row) is dict and row.get('Type') == 'Build Cache']
        if len(cache) != 1:
            raise Refused('SNAPSHOT_REFUSED')
        row = cache[0]
        cache = {'count': count(row['TotalCount']), 'active': count(row['Active']),
                 'size': size(row['Size']), 'reclaimable': size(row['Reclaimable'], True)}
        ids = read(PS, runner).splitlines()
        if len(ids) > 256 or len(ids) != len(set(ids)) or any(not ID.fullmatch(x) for x in ids):
            raise Refused('SNAPSHOT_REFUSED')
        containers = []
        if ids:
            output = read((*DOCKER, 'inspect', '--type=container', '--format', INSPECT_FORMAT, *sorted(ids)), runner)
            containers = [json.loads(line) for line in output.splitlines() if line]
            if len(containers) != len(ids):
                raise Refused('SNAPSHOT_REFUSED')
            for container in containers:
                if (type(container) is not dict or set(container) != {'id', 'image', 'running', 'pid', 'started', 'restarts'} or
                        type(container['id']) is not str or container['id'] not in ids or
                        type(container['image']) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', container['image']) or
                        type(container['running']) is not bool or
                        any(type(container[k]) is not int or not 0 <= container[k] <= 2 ** 31 for k in ('pid', 'restarts')) or
                        type(container['started']) is not str or not re.fullmatch(r'[0-9]{4}-[0-9TZ:.+-]{10,40}', container['started'])):
                    raise Refused('SNAPSHOT_REFUSED')
            if set(c['id'] for c in containers) != set(ids):
                raise Refused('SNAPSHOT_REFUSED')
        return {'scope': SCOPE, 'cache': cache, 'containers': sorted(containers, key=lambda c: c['id'])}
    except Refused:
        raise
    except Exception:
        raise Refused('SNAPSHOT_REFUSED') from None


def available():
    info = os.statvfs('/var/lib')
    return info.f_bavail * info.f_frsize


def execute(mode, plan_sha='', confirm='', runner=run, free=available):
    result = receipt(mode)
    try:
        if mode == 'plan':
            if plan_sha or confirm:
                raise Refused('INPUT_REFUSED')
        elif mode == 'apply':
            if type(plan_sha) is not str or not SHA.fullmatch(plan_sha) or confirm != CONFIRM:
                raise Refused('INPUT_REFUSED')
        else:
            raise Refused('INPUT_REFUSED')
        before = snapshot(runner)
        result.update(plan_sha256=hashlib.sha256(canonical(before).encode()).hexdigest(),
            cache_count_before=before['cache']['count'], cache_active_before=before['cache']['active'],
            cache_size_before_bytes=before['cache']['size'], cache_reclaimable_before_bytes=before['cache']['reclaimable'],
            containers_before=len(before['containers']), free_before_bytes=free())
        if before['cache']['active'] != 0:
            raise Refused('ACTIVE_CACHE')
        if mode == 'plan':
            result.update(status='planned', reason='PLAN_READY')
            return validate_report(result)
        if plan_sha != result['plan_sha256']:
            raise Refused('PLAN_MISMATCH')
        result['prune_attempted'] = True
        prune_reason = None
        try:
            result['prune_exit_code'] = runner(PRUNE, timeout=600).returncode
            if result['prune_exit_code'] != 0:
                prune_reason = 'PRUNE_FAILED'
        except Exception:
            # The daemon may still be pruning after a lost client. Never retry.
            prune_reason = 'PRUNE_OUTCOME_UNKNOWN'
        after = snapshot(runner)
        result.update(cache_count_after=after['cache']['count'], free_after_bytes=free(),
                      container_unchanged=(before['containers'] == after['containers']))
        result['free_change_bytes'] = result['free_after_bytes'] - result['free_before_bytes']
        if not result['container_unchanged']:
            raise Refused('CONTAINER_CHANGED')
        if prune_reason:
            raise Refused(prune_reason)
        result.update(status='applied', reason='PRUNED')
    except Refused as exc:
        result['reason'] = str(exc) if str(exc) in REASONS else 'INTERNAL_ERROR'
    except Exception:
        result['reason'] = 'INTERNAL_ERROR'
    return validate_report(result)


@contextlib.contextmanager
def deployment_lock():
    """Same flock as naver-deploy; only coordination directories may be created."""
    try:
        for name in ('/var', '/var/lib', '/var/lib/metainc', '/var/lib/metainc/naver-deploy'):
            try:
                info = os.lstat(name)
            except FileNotFoundError:
                if name not in ('/var/lib/metainc', '/var/lib/metainc/naver-deploy'):
                    raise Refused('LOCK_PATH_REFUSED') from None
                os.mkdir(name, 0o700)
                info = os.lstat(name)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise Refused('LOCK_PATH_REFUSED')
        fd = os.open('/var/lib/metainc/naver-deploy/lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600)
    except OSError:
        raise Refused('LOCK_PATH_REFUSED') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            raise Refused('LOCK_PATH_REFUSED')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused('LOCKED') from None
        yield
    finally:
        os.close(fd)


def main(args):
    mode = args[0] if args else 'invalid'
    result = receipt(mode)
    try:
        if len(args) != 3:
            raise Refused('INPUT_REFUSED')
        if os.geteuid() != 0:
            raise Refused('NOT_ROOT')
        with deployment_lock():
            result = execute(*args)
    except Refused as exc:
        result['reason'] = str(exc) if str(exc) in REASONS else 'INTERNAL_ERROR'
    except Exception:
        result['reason'] = 'INTERNAL_ERROR'
    print(canonical(validate_report(result)))
    return 0 if result['status'] in ('planned', 'applied') else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
