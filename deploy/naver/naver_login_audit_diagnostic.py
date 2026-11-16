#!/usr/bin/env python3
"""Fixed NAVER runtime diagnosis: no app HTTP, DB open, env read, or mutation.

Only Docker metadata/log reads and no-follow directory/file metadata observations.
Log bodies remain in bounded memory; only literal categories/kinds and counts/times leave.
"""
import contextlib
from datetime import datetime, timezone
import json
import os
import re
import resource
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time

SOURCE = 'c44a66393340314796851f4dd524dad523bd5415'
TARGETS = {
    'engine': ('1d6f986d95a2c1fce2aaeac7a872edaf4e8519e9c99acddebc1cc3a0d6e48291',
               'sha256:3b75795280e53fae096a26b735bd324c7ba76e7aa1d5c4b8a76ed5b7569b195a'),
    'relay': ('1141302033f38224116e03506edf33d9279f2b6633df30d330721f808cdc624f',
              'sha256:171e5bb8aa1673c3d1e0aefa7c48f1e1f72201f2b93c2dcdeb2f9d3134523960'),
}
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
MAX_LOG = 1024 * 1024
MAX_ROWS = 300
ERRORS = frozenset(('arguments_refused', 'uid_required', 'platform_refused',
    'container_unexpected', 'container_changed', 'mount_refused', 'docker_failed', 'json_refused',
    'command_timeout', 'command_limit', 'child_cleanup_failed', 'interrupted',
    'unsafe_directory', 'directory_changed', 'metadata_unavailable', 'log_shape_refused',
    'output_refused', 'internal_failure', 'temporary_cleanup_failed'))
KINDS = frozenset(('StoreBusy', 'StoreError', 'StoreRefused', 'OperationalError',
    'IntegrityError', 'DatabaseError', 'ProgrammingError', 'DataError', 'InterfaceError',
    'InternalError', 'NotSupportedError', 'TimeoutError', 'OSError', 'PermissionError',
    'FileNotFoundError', 'RuntimeError', 'ValueError', 'TypeError', 'MemoryError',
    'ConnectionRefusedError', 'ConnectionResetError', 'BrokenPipeError',
    'RemoteDisconnected', 'engine-timeout', 'engine-bad-answer', 'engine-cut',
    'relay-busy', 'relay-no-thread', 'engine-not-configured', 'unrecognized'))
# Exact existing log_projection templates; arbitrary exception names are NOT echoed.
TEMPLATES = {
 'engine': (
  ('audit_write_failed', r'WARNING naver_engine\.web 열람·쓰기 기록 실패: (\S{1,64})'),
  ('web_store_busy', r'WARNING naver_engine\.web 화면 API 저장소 바쁨: (\S{1,64})'),
  ('web_store_error', r'WARNING naver_engine\.web 화면 API 저장소 오류: (\S{1,64})'),
  ('web_store_refused', r'WARNING naver_engine\.web 화면 API 저장소 거절: (\S{1,64})'),
  ('web_unexpected_error', r'ERROR naver_engine\.web 화면 API 뜻밖의 오류: (\S{1,64})'),
  ('cycle_failed', r'ERROR naver_runtime 예약 회차 실패: (\S{1,64})'),
  ('job_failed', r'ERROR naver_runtime\.scheduler 예약 작업 실패: [a-z_]{1,32} (\S{1,64})')),
 'relay': (('relay_failed', r'(?:WARNING:?[ ]+(?:(?:app\.)?naver_relay )?)?관제 엔진 중계 실패: (\S{1,64})'),),
}
STAMP = re.compile(r'([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,9}))?(Z|[+-][0-9]{2}:[0-9]{2})\Z')


class Refused(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'internal_failure'
        super().__init__(self.code)


def require(ok, code):
    if not ok:
        raise Refused(code)


def integer(value, limit=2**63-1):
    return type(value) is int and 0 <= value <= limit


def decode(raw):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, 'json_refused')
            out[key] = value
        return out
    try:
        return json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(Refused('json_refused')))
    except (ValueError, UnicodeError, RecursionError):
        raise Refused('json_refused') from None


def timestamp(value):
    match = STAMP.fullmatch(value) if isinstance(value, str) else None
    require(match is not None, 'log_shape_refused')
    try:
        text = match[1] + ('.' + (match[2] + '000000')[:6] if match[2] else '')
        return datetime.fromisoformat(text + ('+00:00' if match[3] == 'Z' else match[3])).astimezone(timezone.utc).isoformat()
    except ValueError:
        raise Refused('log_shape_refused') from None


def command(argv, limit=16384, timeout=10):
    child=None;previous={};state={'spawning':False,'pending':False};raw=bytearray();errors=bytearray()
    def stop(*_):
        state['pending']=True
        for number in previous:signal.signal(number,signal.SIG_IGN)
        if not state['spawning']:raise Refused('interrupted')
    try:
        numbers=(signal.SIGINT,signal.SIGHUP,signal.SIGTERM,signal.SIGALRM)
        mask=signal.pthread_sigmask(signal.SIG_BLOCK,numbers)
        try:
            for number in numbers:
                previous[number]=signal.getsignal(number)
                if previous[number]!=signal.SIG_IGN:signal.signal(number,stop)
        finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
        state['spawning']=True
        try:child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            env=ENV,shell=False,start_new_session=True)
        finally:state['spawning']=False
        require(not state['pending'],'interrupted');end=time.monotonic()+timeout
        with selectors.DefaultSelector() as selected:
            selected.register(child.stdout,selectors.EVENT_READ,True);selected.register(child.stderr,selectors.EVENT_READ,False)
            while selected.get_map():
                require(time.monotonic()<end,'command_timeout')
                for key,_ in selected.select(min(.2,max(.001,end-time.monotonic()))):
                    block=os.read(key.fd,8192)
                    if not block:selected.unregister(key.fileobj);continue
                    if key.data:raw.extend(block)
                    else:errors.extend(block)
                    require(len(raw)+len(errors)<=limit,'command_limit')
        return bytes(raw),bytes(errors),child.wait(timeout=max(.01,end-time.monotonic()))
    finally:
        mask=signal.pthread_sigmask(signal.SIG_BLOCK,tuple(previous))
        try:
            for number in previous:signal.signal(number,signal.SIG_IGN)
        finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
        safe=True
        try:
            if child is not None:
                try:
                    if child.poll() is None:
                        try:os.killpg(child.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                except OSError:safe=False
                try:child.wait(timeout=5)
                except Exception:safe=False
                for stream in (child.stdout,child.stderr):
                    try:stream.close()
                    except Exception:safe=False
            require(safe,'child_cleanup_failed')
        finally:
            mask=signal.pthread_sigmask(signal.SIG_BLOCK,tuple(previous))
            try:
                for number,handler in previous.items():signal.signal(number,handler)
            finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)


class Docker:
    def __init__(self, config, runner=command):
        self.config, self.runner = config, runner

    def run(self, args, limit=16384):
        out, err, code = self.runner(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock',
            '--config', self.config, *args], limit=limit, timeout=8)
        require(code == 0, 'docker_failed')
        return out, err

    def state(self, alias):
        identifier, image = TARGETS[alias]
        template = ('{"id":{{json .Id}},"image":{{json .Image}},"pid":{{json .State.Pid}},'
            '"running":{{json .State.Running}},"paused":{{json .State.Paused}},'
            '"restarting":{{json .State.Restarting}},"started_at":{{json .State.StartedAt}},'
            '"restart_count":{{json .RestartCount}},"oom_killed":{{json .State.OOMKilled}},'
            '"user":{{json .Config.User}},"readonly":{{json .HostConfig.ReadonlyRootfs}},'
            '"source":{{json (index .Config.Labels "metainc.naver.preview.source")}},'
            '"data":[{{range .Mounts}}{{if eq .Destination "/var/lib/naver-engine"}}{{json .}}{{end}}{{end}}]}')
        out, _ = self.run(['inspect', '--format', template, identifier])
        value = decode(out)
        require(isinstance(value, dict) and set(value) == set(
            'id image pid running paused restarting started_at restart_count oom_killed user readonly source data'.split()),
            'container_unexpected')
        require(value['id'] == identifier and value['image'] == image and value['source'] == SOURCE
            and value['user'] == '10001:10001' and value['readonly'] is True
            and integer(value['pid']) and value['pid'] > 0 and integer(value['restart_count'])
            and all(type(value[k]) is bool for k in ('running', 'paused', 'restarting', 'oom_killed'))
            and value['running'] and not value['paused'] and not value['restarting'], 'container_unexpected')
        timestamp(value['started_at'])
        mounts = value['data']
        require(isinstance(mounts, list), 'mount_refused')
        if alias == 'engine':
            require(len(mounts) == 1 and isinstance(mounts[0], dict) and all(
                mounts[0].get(k) == v for k, v in dict(Type='bind',
                    Source='/var/lib/metainc/naver-engine', Destination='/var/lib/naver-engine').items())
                and mounts[0].get('RW') is True, 'mount_refused')
        else:
            require(not mounts, 'mount_refused')
        return value

    def logs(self, alias):
        return self.run(['logs', '--since', '1h', '--tail', str(MAX_ROWS), '--timestamps',
                         TARGETS[alias][0]], limit=MAX_LOG)


def metadata(info):
    return dict(device=info.st_dev, inode=info.st_ino, uid=info.st_uid, gid=info.st_gid,
        mode=stat.S_IMODE(info.st_mode), links=info.st_nlink, bytes=info.st_size,
        mtime_ns=info.st_mtime_ns)


def directory_identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid


class Files:
    """Open directories only; the three SQLite leaves are lstat-only."""
    def __init__(self, base='/', root_uid=0, data_uid=10001):
        self.base, self.root_uid, self.data_uid = base, root_uid, data_uid
        self.stack, self.edges = contextlib.ExitStack(), []

    def close(self):
        self.stack.close()

    def directory(self):
        folder = os.open(self.base, DIR_FLAGS)
        self.stack.callback(os.close, folder)
        top = os.fstat(folder)
        require(stat.S_ISDIR(top.st_mode) and top.st_uid == self.root_uid
                and not top.st_mode & 0o022, 'unsafe_directory')
        for index, name in enumerate(('var', 'lib', 'metainc', 'naver-engine')):
            before = os.stat(name, dir_fd=folder, follow_symlinks=False)
            require(stat.S_ISDIR(before.st_mode) and before.st_uid ==
                (self.data_uid if index == 3 else self.root_uid) and not before.st_mode & 0o022,
                'unsafe_directory')
            child = os.open(name, DIR_FLAGS, dir_fd=folder)
            self.stack.callback(os.close, child)
            expected = directory_identity(before)
            require(directory_identity(os.fstat(child)) == expected, 'directory_changed')
            self.edges.append((folder, name, child, expected))
            folder = child
        return folder

    def validate(self):
        for parent, name, child, expected in self.edges:
            require(directory_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) == expected
                and directory_identity(os.fstat(child)) == expected, 'directory_changed')

    def observe(self):
        folder = self.directory()
        info = os.fstat(folder)
        fs = os.fstatvfs(folder)
        files = []
        for alias, name in (('database', 'engine.db'), ('wal', 'engine.db-wal'),
                            ('shared_memory', 'engine.db-shm')):
            try:
                value = os.stat(name, dir_fd=folder, follow_symlinks=False)
            except FileNotFoundError:
                files.append(dict(alias=alias, present=False, kind=None, metadata=None))
                continue
            kind = 'regular' if stat.S_ISREG(value.st_mode) else 'symlink' if stat.S_ISLNK(value.st_mode) else 'other'
            files.append(dict(alias=alias, present=True, kind=kind, metadata=metadata(value)))
        self.validate()
        return dict(directory=metadata(info), files=files, filesystem=dict(
            available_bytes=fs.f_bavail * fs.f_frsize, free_bytes=fs.f_bfree * fs.f_frsize,
            total_bytes=fs.f_blocks * fs.f_frsize, available_inodes=fs.f_favail,
            read_only=bool(fs.f_flag & getattr(os, 'ST_RDONLY', 1))),
            file_contents_read=False, write_ability='not_tested')


def log_projection(stdout, stderr, alias):
    require(alias in TEMPLATES and len(stdout) + len(stderr) <= MAX_LOG, 'log_shape_refused')
    lines = stdout.splitlines() + stderr.splitlines()
    require(len(lines) <= MAX_ROWS, 'log_shape_refused')
    categories = {}
    ignored = 0
    for line in lines:
        try:
            require(len(line) <= 8192, 'log_shape_refused')
            tick, _, message = line.decode('utf-8').partition(' ')
            at = timestamp(tick)
        except (Refused, UnicodeError):
            ignored += 1
            continue
        for category, pattern in TEMPLATES[alias]:
            match = re.fullmatch(pattern, message)
            if match is not None:
                row = categories.setdefault(category, dict(count=0, first_at=at, last_at=at, kinds={}))
                row['count'] += 1
                row['first_at'], row['last_at'] = min(row['first_at'], at), max(row['last_at'], at)
                kind = match[1] if match[1] in KINDS else 'unrecognized'
                row['kinds'][kind] = row['kinds'].get(kind, 0) + 1
                break
        else:
            ignored += 1
    return dict(alias=alias, scope='last_1h_tail_300_sample', entries_inspected=len(lines),
        ignored_entries=ignored, sample_limit_reached=len(lines) == MAX_ROWS, categories=categories)


def empty_report():
    return dict(schema='naver-login-audit-diagnostic-v1', status='failed', error=None,
        read_only=True, database_opened=False, application_http_calls=0, mutations=0,
        queue_state='not_observed', containers=None, storage=None, logs=None,
        postflight_unchanged=False, child_cleanup_confirmed=True)


def diagnose(docker, files=None):
    result = empty_report()
    files = files or Files()
    try:
        before = {alias: docker.state(alias) for alias in TARGETS}
        storage = files.observe()
        logs = [log_projection(*docker.logs(alias), alias) for alias in TARGETS]
        after = {alias: docker.state(alias) for alias in TARGETS}
        require(after == before, 'container_changed')
        files.validate()
        # Release projected evidence only after the exact running container guards pass.
        result.update(status='observed', containers=[dict(alias=alias,
            **{k: before[alias][k] for k in ('pid', 'running', 'paused', 'restarting',
                'started_at', 'restart_count', 'oom_killed')}) for alias in TARGETS],
            storage=storage, logs=logs, postflight_unchanged=True)
    except BaseException as error:
        result['error'] = error.code if isinstance(error, Refused) else 'internal_failure'
        if result['error'] == 'child_cleanup_failed':
            result['child_cleanup_confirmed'] = False
    finally:
        try:
            files.close()
        except BaseException:
            result.update(status='failed', error='metadata_unavailable', postflight_unchanged=False,
                          containers=None, storage=None, logs=None)
    return result


def validate_report(value):
    require(isinstance(value, dict) and set(value) == set(empty_report()), 'output_refused')
    require(value['schema'] == 'naver-login-audit-diagnostic-v1' and value['read_only'] is True
        and value['database_opened'] is False and type(value['application_http_calls']) is int
        and value['application_http_calls'] == 0 and type(value['mutations']) is int
        and value['mutations'] == 0 and value['queue_state'] == 'not_observed'
        and type(value['postflight_unchanged']) is bool and type(value['child_cleanup_confirmed']) is bool,
        'output_refused')
    require(value['status'] in ('observed', 'failed'), 'output_refused')
    if value['status'] == 'failed':
        require(value['error'] in ERRORS and value['postflight_unchanged'] is False, 'output_refused')
        # Failure never publishes partially guarded observations.
        require(all(value[k] is None for k in ('containers', 'storage', 'logs')), 'output_refused')
        return value
    require(value['error'] is None and value['postflight_unchanged'] is True
        and value['child_cleanup_confirmed'] is True, 'output_refused')
    containers = value['containers']
    require(isinstance(containers, list) and len(containers) == 2, 'output_refused')
    for alias, row in zip(TARGETS, containers):
        require(isinstance(row, dict) and set(row) == set(
            'alias pid running paused restarting started_at restart_count oom_killed'.split())
            and row['alias'] == alias and integer(row['pid']) and row['pid'] > 0
            and integer(row['restart_count']) and row['running'] is True and row['paused'] is False
            and row['restarting'] is False and type(row['oom_killed']) is bool, 'output_refused')
        timestamp(row['started_at'])
    storage = value['storage']
    require(isinstance(storage, dict) and set(storage) == set(
        'directory files filesystem file_contents_read write_ability'.split())
        and storage['file_contents_read'] is False and storage['write_ability'] == 'not_tested', 'output_refused')
    def valid_metadata(row):
        require(isinstance(row, dict) and set(row) == set('device inode uid gid mode links bytes mtime_ns'.split())
            and all(integer(n) for n in row.values()) and row['mode'] <= 0o7777, 'output_refused')
    valid_metadata(storage['directory'])
    require(isinstance(storage['files'], list) and len(storage['files']) == 3, 'output_refused')
    for alias, row in zip(('database', 'wal', 'shared_memory'), storage['files']):
        require(isinstance(row, dict) and set(row) == {'alias', 'present', 'kind', 'metadata'}
            and row['alias'] == alias and type(row['present']) is bool, 'output_refused')
        if row['present']:
            require(row['kind'] in ('regular', 'symlink', 'other'), 'output_refused')
            valid_metadata(row['metadata'])
        else:
            require(row['kind'] is None and row['metadata'] is None, 'output_refused')
    fs = storage['filesystem']
    require(isinstance(fs, dict) and set(fs) == set(
        'available_bytes free_bytes total_bytes available_inodes read_only'.split())
        and type(fs['read_only']) is bool and all(integer(fs[k]) for k in fs if k != 'read_only'), 'output_refused')
    require(isinstance(value['logs'], list) and len(value['logs']) == 2, 'output_refused')
    for alias, row in zip(TARGETS, value['logs']):
        require(isinstance(row, dict) and set(row) == set(
            'alias scope entries_inspected ignored_entries sample_limit_reached categories'.split())
            and row['alias'] == alias and row['scope'] == 'last_1h_tail_300_sample'
            and integer(row['entries_inspected'], MAX_ROWS) and integer(row['ignored_entries'], MAX_ROWS)
            and type(row['sample_limit_reached']) is bool
            and row['sample_limit_reached'] == (row['entries_inspected'] == MAX_ROWS), 'output_refused')
        categories = row['categories']
        require(isinstance(categories, dict) and set(categories) <= {c for c, _ in TEMPLATES[alias]}, 'output_refused')
        for item in categories.values():
            require(isinstance(item, dict) and set(item) == {'count', 'first_at', 'last_at', 'kinds'}
                and integer(item['count'], MAX_ROWS) and item['count'] > 0
                and isinstance(item['kinds'], dict) and set(item['kinds']) <= KINDS
                and all(integer(n, MAX_ROWS) and n > 0 for n in item['kinds'].values())
                and sum(item['kinds'].values()) == item['count'], 'output_refused')
            timestamp(item['first_at']); timestamp(item['last_at'])
            require(item['first_at'] <= item['last_at'], 'output_refused')
        require(sum(r['count'] for r in categories.values()) + row['ignored_entries'] == row['entries_inspected'], 'output_refused')
    return value


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    result = empty_report()
    old_alarm = None
    try:
        require(not args, 'arguments_refused')
        require(os.geteuid() == 0, 'uid_required')
        require(sys.platform == 'linux', 'platform_refused')
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.umask(0o077)
        def expired(*_):
            raise Refused('command_timeout')
        old_alarm = signal.signal(signal.SIGALRM, expired)
        signal.alarm(60)
        # A fresh empty Docker CLI config prevents implicit contexts/plugins/credentials.
        with tempfile.TemporaryDirectory(prefix='naver-login-audit-config-', dir='/tmp') as config:
            result = diagnose(Docker(config))
        validate_report(result)
    except BaseException as error:
        previous = result.get('child_cleanup_confirmed', True)
        result = empty_report()
        result['error'] = error.code if isinstance(error, Refused) else 'internal_failure'
        result['child_cleanup_confirmed'] = previous and result['error'] != 'child_cleanup_failed'
    finally:
        if old_alarm is not None:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_alarm)
    body = json.dumps(result, sort_keys=True, separators=(',', ':'))
    if len(body.encode()) > 32768:
        result = empty_report(); result['error'] = 'output_refused'
        body = json.dumps(result, sort_keys=True, separators=(',', ':'))
    print(body)
    return 0 if result['status'] == 'observed' else 2


if __name__ == '__main__':
    sys.exit(main())
