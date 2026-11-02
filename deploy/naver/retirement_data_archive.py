"""Import-only frozen file archive producer. Never execute or print application data.

The reviewed transport must hash-bind this module and the preflight module, own
the pause/ingress controls, and connect sink_fd directly to GPG stdin. A complete
stream is a recovery candidate, not a claim that SQLite/application restore passed.
"""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import resource
import selectors
import stat
import sys
import tarfile
import time

SESSION = 'data-snapshot-20261102-v1'
SCHEMA = 'metainc-retirement-data-v1'
ROOTS = {'ad': '/root/ad-dashboard-deploy/data',
         'content': '/root/content-studio-deploy/data',
         'autobid': '/var/lib/docker/volumes/autobid_autobid-data/_data'}
DATA_SCOPES = ('ad', 'content', 'autobid', 'content_tmp')
SCOPES = DATA_SCOPES + ('recovery_config',)
MAX_ENTRIES = 100000
MAX_BYTES = 2 * 1024 ** 3
MAX_FILE_BYTES = MAX_BYTES
MAX_MANIFEST = 32 * 1024 ** 2
MAX_PATH_BYTES = 8 * 1024 ** 2
MAX_DELETED = 64
MAX_PINS = 256
MAX_THREADS = 8192
MAX_CONFIG_FILE = 256 * 1024
MAX_CONFIG_TOTAL = 2 * 1024 ** 2
MAX_CONFIG_OBJECTS = 16
MAX_ARCHIVE = MAX_BYTES + MAX_MANIFEST + (MAX_ENTRIES + MAX_DELETED + MAX_CONFIG_OBJECTS + 1) * 1024 + 2048
CONFIG_FIELDS = ('Env', 'Entrypoint', 'Cmd', 'User', 'WorkingDir', 'StopSignal', 'Healthcheck',
                 'Hostname', 'Domainname', 'Labels', 'ExposedPorts', 'Volumes')
HOST_FIELDS = ('Binds', 'Mounts', 'PortBindings', 'RestartPolicy', 'NetworkMode',
               'ReadonlyRootfs', 'Tmpfs', 'ShmSize', 'CapAdd', 'CapDrop', 'SecurityOpt',
               'Privileged', 'Devices', 'DeviceRequests', 'GroupAdd', 'Ulimits', 'Dns',
               'DnsSearch', 'ExtraHosts', 'Memory', 'NanoCpus', 'IpcMode', 'PidMode')
# Exact existing Compose labels and the already preserved AutoBid environment.
# These are opaque inputs, never followed as instructions or executed.
CONFIG_FILES = (
    ('ad-compose', 'opaque-compose', '/root/ad-dashboard-deploy/docker-compose.yml'),
    ('content-compose', 'opaque-compose', '/root/content-studio-deploy/docker-compose.yml'),
    ('autobid-environment', 'opaque-env', '/root/content-studio-deploy/autobid/.env'),
    # Exact resolved regular files observed by control preflight 41403670586.
    ('nginx-ad', 'opaque-nginx', '/etc/nginx/sites-available/ad.metainc.co.kr'),
    ('nginx-logic', 'opaque-nginx', '/etc/nginx/sites-enabled/logic-analysis'),
    ('nginx-studio', 'opaque-nginx', '/etc/nginx/sites-available/studio.metainc.co.kr.conf'),
)
RESTART_JOURNAL = '/root/.metainc-retirement-control/' + SESSION + '/fence-complete.json'
MAX_RESTART_JOURNAL = 8192
TIMEOUT = 1800
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
MAGIC_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class Refused(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def stamp(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid,
            value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def metadata(value):
    return dict(zip(('device', 'inode', 'mode', 'uid', 'gid', 'links', 'bytes',
                     'mtime_ns', 'ctime_ns'), stamp(value)))


def tick(end):
    if time.monotonic() >= end:
        raise Refused('archive_timeout')


def clean_name(name):
    if (not isinstance(name, str) or not name or name in ('.', '..') or
            '/' in name or '\\' in name or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise Refused('name_uncovered')
    try:
        if len(name.encode('utf-8')) > 255:
            raise Refused('name_uncovered')
    except UnicodeError:
        raise Refused('name_uncovered') from None
    return name


def bounded_names(fd, maximum=MAX_ENTRIES):
    names = []
    with os.scandir(fd) as rows:
        for row in rows:
            if len(names) >= maximum:
                raise Refused('entry_limit')
            names.append(row.name)
    return sorted(names)


def integers(raw):
    rows = raw.split()
    if len(rows) > MAX_THREADS or any(re.fullmatch(rb'[1-9][0-9]{0,9}', row) is None for row in rows):
        raise Refused('cgroup_unconfirmed')
    numbers = tuple(sorted(int(row) for row in rows))
    if not numbers or len(numbers) != len(set(numbers)):
        raise Refused('cgroup_unconfirmed')
    return numbers


class Sink:
    def __init__(self, fd, end):
        if not stat.S_ISFIFO(os.fstat(fd).st_mode):
            raise Refused('encrypted_pipe_required')
        self.fd, self.end, self.total = fd, end, 0
        self.flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        if self.flags & os.O_ACCMODE not in (os.O_WRONLY, os.O_RDWR):
            raise Refused('encrypted_pipe_required')

    def __enter__(self):
        fcntl.fcntl(self.fd, fcntl.F_SETFL, self.flags | os.O_NONBLOCK)
        return self

    def __exit__(self, *unused):
        fcntl.fcntl(self.fd, fcntl.F_SETFL, self.flags)

    def write(self, data):
        if self.total + len(data) > MAX_ARCHIVE:
            raise Refused('archive_size_limit')
        view = memoryview(data)
        with selectors.DefaultSelector() as selected:
            selected.register(self.fd, selectors.EVENT_WRITE)
            while view:
                tick(self.end)
                if not selected.select(min(.2, max(.001, self.end - time.monotonic()))):
                    continue
                try:
                    count = os.write(self.fd, view[:65536])
                except BlockingIOError:
                    continue
                if count <= 0:
                    raise Refused('encrypted_pipe_failed')
                self.total += count
                view = view[count:]

    def header(self, name, size):
        info = tarfile.TarInfo(name)
        info.size, info.mode, info.uid, info.gid, info.mtime = size, 0o600, 0, 0, 0
        info.type = tarfile.REGTYPE
        self.write(info.tobuf(format=tarfile.USTAR_FORMAT, encoding='ascii'))

    def padding(self, size):
        self.write(b'\0' * ((-size) % 512))


class Snapshot:
    """Private lifetime-bound snapshot; alternate adapters are synthetic tests only."""
    def __init__(self, preflight, request, files=None, docker=None, proc=None, end=None, restart_evidence=None):
        if preflight.ROOTS != ROOTS:
            raise Refused('preflight_contract_refused')
        self.p, self.request = preflight, request
        self.end = time.monotonic() + TIMEOUT if end is None else end
        self.files = files or preflight.Files()
        self.docker = docker or preflight.Docker(self.end)
        self.proc = proc or preflight.Proc(self.files)
        self.stack = contextlib.ExitStack()
        self.entries, self.deleted, self.mapping_pins, self.recovery = [], [], [], []
        self.bases, self.private, self.guard = {}, {}, None
        self.recovery_absent = []
        self.config_parent_guards = {}
        self.restart_evidence, self.restart_pin = restart_evidence, None
        self.total = 0

    def __enter__(self):
        try:
            self.guard = self.frozen()
            self.report, self.private = self.observe()
            if self.frozen() != self.guard:
                raise Refused('freeze_changed')
            self.bases['content_tmp'] = self.stack.enter_context(self.proc.root_fd(self.request['content']['pid']))
            # Keep each fixed parent chain pinned throughout the whole stream.
            for scope in DATA_SCOPES:
                path = '/tmp' if scope == 'content_tmp' else ROOTS[scope]
                self.stack.enter_context(self.files.directory(path, self.bases.get(scope), secure=scope != 'content_tmp'))
            self.entries = self.inventory()
            self.pin_deleted()
            self.pin_mappings_and_check_io()
            self.recovery, self.recovery_absent, self.config_parent_guards = self.configuration()
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *unused):
        self.stack.close()

    def observe(self):
        private = {}
        report = self.p.collect(self.request, files=self.files, docker=self.docker,
                                proc=self.proc, end=self.end, private=private)
        if (report.get('status') != 'coverage_complete' or
                report.get('host', {}).get('external_writers') != 0 or
                report.get('host', {}).get('target_uncovered_writers') != 0 or
                set(private) != {'container_guards', 'process_identities', 'owner_scopes', 'deleted_files'}):
            raise Refused('coverage_incomplete')
        return report, private

    def frozen(self):
        if set(self.request) != {'ad', 'content'}:
            raise Refused('request_refused')
        guards = {}
        for alias in ('ad', 'content'):
            tick(self.end)
            selection = self.request[alias]
            if (set(selection) != {'id', 'pid'} or
                    not isinstance(selection['id'], str) or
                    re.fullmatch('[0-9a-f]{64}', selection['id']) is None or
                    type(selection['pid']) is not int or not 0 < selection['pid'] <= 2**32 - 1):
                raise Refused('request_refused')
            template = ('{"id":{{json .Id}},"pid":{{json .State.Pid}},"running":{{json .State.Running}},'
                        '"paused":{{json .State.Paused}},"restarting":{{json .State.Restarting}}}')
            state = self.p.json_read(self.docker.run(['inspect', '--format', template, selection['id']]))
            if (state != dict(id=selection['id'], pid=selection['pid'], running=True, paused=True, restarting=False)
                    or type(state.get('pid')) is not int or state.get('paused') is not True
                    or state.get('running') is not True or state.get('restarting') is not False):
                raise Refused('not_frozen')
            workers = self.docker.workers(selection['id'], selection['pid'])
            identities = {pid: self.proc.identity(pid) for pid, _ in workers}
            init = identities[selection['pid']]
            if any(identities[pid][1] != parent or identities[pid][2:] != init[2:] for pid, parent in workers):
                raise Refused('process_changed')
            threads = {}
            for pid in identities:
                with self.files.directory(self.proc.root + '/' + str(pid) + '/task', secure=False) as folder:
                    tids = integers(('\n'.join(bounded_names(folder, MAX_THREADS))).encode('ascii'))
                if pid not in tids or sum(len(row) for row in threads.values()) + len(tids) > MAX_THREADS:
                    raise Refused('thread_set_unconfirmed')
                threads[pid] = tids
            cgroup = self.cgroup(selection, identities, threads)
            guards[alias] = {'selection': dict(selection), 'identities': identities,
                             'threads': threads, 'cgroup': cgroup}
        if set(guards['ad']['identities']) & set(guards['content']['identities']):
            raise Refused('process_changed')
        return guards

    def cgroup(self, selection, identities, threads):
        raw = self.proc.read(selection['pid'], 'cgroup', 16384)
        rows = []
        for line in raw.splitlines():
            fields = line.decode('ascii', 'strict').split(':', 2)
            if len(fields) != 3:
                raise Refused('cgroup_unconfirmed')
            if fields[:2] == ['0', '']:
                rows.append(('v2', fields[2]))
            elif 'freezer' in fields[1].split(','):
                rows.append(('v1', fields[2]))
        if len(rows) != 1:
            raise Refused('cgroup_unconfirmed')
        version, relative = rows[0]
        if relative not in ('/system.slice/docker-' + selection['id'] + '.scope', '/docker/' + selection['id']):
            raise Refused('cgroup_unconfirmed')
        path = '/sys/fs/cgroup' + ('/freezer' if version == 'v1' else '') + relative
        for pid in identities:
            if self.proc.read(pid, 'cgroup', 16384) != raw:
                raise Refused('cgroup_unconfirmed')
        with self.files.directory(path) as folder:
            directory = stamp(os.fstat(folder))
            names = os.listdir(folder)
            if len(names) > 256 or any(stat.S_ISDIR(os.stat(name, dir_fd=folder, follow_symlinks=False).st_mode) for name in names):
                raise Refused('nested_cgroup_uncovered')
        read = lambda name: self.files.read(path + '/' + name, 65536).strip()
        expected_threads = tuple(sorted(tid for row in threads.values() for tid in row))
        if len(expected_threads) != len(set(expected_threads)):
            raise Refused('thread_set_unconfirmed')
        if version == 'v2':
            events = read('cgroup.events').splitlines()
            if read('cgroup.freeze') != b'1' or events.count(b'frozen 1') != 1 or events.count(b'populated 1') != 1:
                raise Refused('not_frozen')
            if integers(read('cgroup.procs')) != tuple(sorted(identities)) or integers(read('cgroup.threads')) != expected_threads:
                raise Refused('cgroup_tasks_changed')
        elif read('freezer.state') != b'FROZEN' or integers(read('tasks')) != expected_threads:
            raise Refused('not_frozen')
        return (version, relative, directory)

    def inventory(self):
        entries, total, path_bytes = [], 0, 0
        for scope in DATA_SCOPES:
            path = '/tmp' if scope == 'content_tmp' else ROOTS[scope]
            base = self.bases.get(scope)
            with self.files.directory(path, base, secure=base is None) as folder:
                device, mount = os.fstat(folder).st_dev, self.files.mount_id(folder)
                def walk(fd, relative, depth):
                    nonlocal total, path_bytes
                    tick(self.end)
                    if depth > 32 or len(entries) >= MAX_ENTRIES:
                        raise Refused('entry_limit')
                    before = os.fstat(fd)
                    entries.append({'scope': scope, 'relative_path': relative, 'kind': 'directory',
                                    'metadata': metadata(before), 'mount_id': mount,
                                    'object': None, 'sha256': None})
                    names = bounded_names(fd, MAX_ENTRIES - len(entries))
                    for name in names:
                        tick(self.end); clean_name(name)
                        child_path = relative + '/' + name if relative else name
                        if len(child_path.encode('utf-8')) > 4096 or len(entries) >= MAX_ENTRIES:
                            raise Refused('entry_limit')
                        path_bytes += len(child_path.encode('utf-8'))
                        if path_bytes > MAX_PATH_BYTES:
                            raise Refused('manifest_size_limit')
                        value = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        if value.st_dev != device:
                            raise Refused('filesystem_boundary')
                        if stat.S_ISDIR(value.st_mode):
                            child = os.open(name, DIR_FLAGS, dir_fd=fd)
                            try:
                                if stamp(os.fstat(child)) != stamp(value) or self.files.mount_id(child) != mount:
                                    raise Refused('filesystem_boundary')
                                walk(child, child_path, depth + 1)
                            finally:
                                os.close(child)
                        elif stat.S_ISREG(value.st_mode):
                            if value.st_nlink != 1 or not 0 <= value.st_size <= MAX_FILE_BYTES:
                                raise Refused('regular_file_uncovered')
                            total += value.st_size
                            if total > MAX_BYTES:
                                raise Refused('data_size_limit')
                            entries.append({'scope': scope, 'relative_path': child_path, 'kind': 'file',
                                            'metadata': metadata(value), 'mount_id': mount,
                                            'object': None, 'sha256': None})
                        else:
                            raise Refused('link_or_special_uncovered')
                        if stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)) != stamp(value):
                            raise Refused('file_changed')
                    if names != bounded_names(fd) or stamp(os.fstat(fd)) != stamp(before):
                        raise Refused('directory_changed')
                walk(folder, '', 0)
        self.total = total
        return entries

    def original_restart(self):
        """Pin a reviewed nonsecret fence journal; preserve its original policy.

        The fence changes only RestartPolicy. Current initial Env/command/mounts
        are encrypted separately without writing a new plaintext config file.
        """
        evidence = self.restart_evidence
        if (not isinstance(evidence, dict) or set(evidence) !=
                {'sha256', 'operator_evidence_sha256', 'control_policy_sha256'} or
                any(not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None or
                    value == '0' * 64 for value in evidence.values())):
            raise Refused('restart_evidence_unconfirmed')
        parent, name = RESTART_JOURNAL.rsplit('/', 1)
        if self.restart_pin is None:
            parents, current = [], ''
            for part in parent.split('/'):
                if not part:
                    continue
                current += '/' + part
                folder = self.stack.enter_context(self.files.directory(current))
                before = os.fstat(folder)
                if current.startswith('/root/.metainc-retirement-control') and stat.S_IMODE(before.st_mode) != 0o700:
                    raise Refused('restart_evidence_unconfirmed')
                parents.append((folder, stamp(before)))
            folder = parents[-1][0]
            value = os.stat(name, dir_fd=folder, follow_symlinks=False)
            if (not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or
                    value.st_uid != self.files.uid or (self.files.uid == 0 and value.st_gid != 0) or
                    stat.S_IMODE(value.st_mode) != 0o600 or not 0 < value.st_size <= MAX_RESTART_JOURNAL):
                raise Refused('restart_evidence_unconfirmed')
            descriptor = os.open(name, READ_FLAGS, dir_fd=folder)
            self.stack.callback(os.close, descriptor)
            self.restart_pin = (descriptor, folder, value, parents)
        descriptor, folder, value, parents = self.restart_pin
        def unchanged():
            if (stamp(os.fstat(descriptor)) != stamp(value) or
                    stamp(os.stat(name, dir_fd=folder, follow_symlinks=False)) != stamp(value) or
                    any(stamp(os.fstat(fd)) != before for fd, before in parents)):
                raise Refused('configuration_changed')
        unchanged()
        body = bytearray()
        while len(body) < value.st_size:
            tick(self.end)
            chunk = os.pread(descriptor, value.st_size - len(body), len(body))
            if not chunk:
                raise Refused('configuration_changed')
            body.extend(chunk)
        if os.pread(descriptor, 1, value.st_size):
            raise Refused('configuration_changed')
        unchanged()
        body = bytes(body)
        if hashlib.sha256(body).hexdigest() != evidence['sha256']:
            raise Refused('restart_evidence_unconfirmed')
        saved = self.p.json_read(body)
        if (not isinstance(saved, dict) or set(saved) != {'schema', 'session', 'status', 'run',
                'operator_evidence_sha256', 'control_policy_sha256', 'daemon', 'containers'} or
                saved['schema'] != 'metainc-retirement-original-restart-v1' or saved['session'] != SESSION or
                saved['status'] != 'fence_complete' or not isinstance(saved['run'], str) or
                re.fullmatch('[1-9][0-9]{0,19}-1', saved['run']) is None or
                any(saved[key] != evidence[key] for key in ('operator_evidence_sha256', 'control_policy_sha256')) or
                not isinstance(saved['daemon'], dict) or set(saved['daemon']) != {'version', 'git_commit', 'os', 'arch'} or
                any(not isinstance(item, str) or re.fullmatch('[A-Za-z0-9_.+-]{1,80}', item) is None for item in saved['daemon'].values()) or
                not isinstance(saved['containers'], dict) or set(saved['containers']) != {'ad', 'content'} or
                json.dumps(saved, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii') != body):
            raise Refused('restart_evidence_unconfirmed')
        for alias in ('ad', 'content'):
            item = saved['containers'][alias]
            if (not isinstance(item, dict) or set(item) != {'id', 'image', 'started_at', 'restart_policy'} or
                    item['id'] != self.request[alias]['id'] or item['image'] != self.p.IMAGES[alias] or
                    not isinstance(item['started_at'], str) or
                    re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z', item['started_at']) is None or
                    not isinstance(item['restart_policy'], dict) or set(item['restart_policy']) != {'Name', 'MaximumRetryCount'}):
                raise Refused('restart_evidence_unconfirmed')
            policy = item['restart_policy']
            if (policy['Name'] not in ('no', 'always', 'unless-stopped', 'on-failure') or
                    type(policy['MaximumRetryCount']) is not int or not 0 <= policy['MaximumRetryCount'] < 2**31 or
                    (policy['Name'] != 'on-failure' and policy['MaximumRetryCount'] != 0)):
                raise Refused('restart_evidence_unconfirmed')
            template = ('{"id":{{json .Id}},"image":{{json .Image}},"started_at":{{json .State.StartedAt}},'
                        '"restart_policy":{{json .HostConfig.RestartPolicy}}}')
            current = self.p.json_read(self.docker.run(['inspect', '--format', template, item['id']]))
            if current != {**item, 'restart_policy': {'Name': 'no', 'MaximumRetryCount': 0}}:
                raise Refused('restart_evidence_unconfirmed')
        return {'alias': 'original-restart-policy', 'format': 'restart-json', 'body': body,
                'source_metadata': metadata(value), 'object': None, 'bytes': len(body),
                'sha256': evidence['sha256']}

    def configuration(self):
        """Initial container configuration and fixed opaque inputs, memory only.

        Docker Config.Env is the initial container environment. The application's
        optional /app/.env is preserved separately; neither proves all runtime env.
        """
        restart = self.original_restart()
        rows, total, absent, parent_guards = [restart], restart['bytes'], [], {}
        for alias in ('ad', 'content'):
            selection = self.request[alias]
            config = ','.join('"' + key + '":{{json .Config.' + key + '}}' for key in CONFIG_FIELDS)
            host = ','.join('"' + key + '":{{json .HostConfig.' + key + '}}' for key in HOST_FIELDS)
            template = ('{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},'
                        '"config":{' + config + '},"host_config":{' + host + '},'
                        '"networks":{{json .NetworkSettings.Networks}}}')
            raw = self.docker.run(['inspect', '--format', template, selection['id']])
            if not 0 < len(raw) <= MAX_CONFIG_FILE:
                raise Refused('configuration_limit')
            value = self.p.json_read(raw)
            if (not isinstance(value, dict) or set(value) != {'id', 'name', 'image', 'config', 'host_config', 'networks'} or
                    value['id'] != selection['id'] or value['name'] != self.p.NAMES[alias] or
                    value['image'] != self.p.IMAGES[alias] or not isinstance(value['config'], dict) or
                    set(value['config']) != set(CONFIG_FIELDS) or not isinstance(value['host_config'], dict) or
                    set(value['host_config']) != set(HOST_FIELDS) or not isinstance(value['networks'], dict) or
                    len(value['networks']) > 16):
                raise Refused('configuration_unconfirmed')
            body = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')
            total += len(body)
            rows.append({'alias': alias + '-container', 'format': 'docker-json', 'body': body,
                         'source_metadata': None, 'object': None, 'bytes': len(body),
                         'sha256': hashlib.sha256(body).hexdigest()})
        targets = [(alias, format_name, path, None, False) for alias, format_name, path in CONFIG_FILES]
        targets.append(('content-dotenv', 'opaque-env', '/app/.env', self.bases['content_tmp'], True))
        for alias, format_name, path, base, optional in targets:
            parent, name = path.rsplit('/', 1)
            with contextlib.ExitStack() as chain:
                # Hold and revalidate every parent, including ctime, for this read.
                # The generic Files policy retains its one observed uid501 ad-parent exception.
                parents, current = [], ''
                for part in parent.split('/'):
                    if not part:
                        continue
                    current += '/' + part
                    folder = chain.enter_context(self.files.directory(current, base, secure=base is None))
                    parents.append((folder, stamp(os.fstat(folder))))
                    parent_guards[(alias, current)] = parents[-1][1]
                folder = parents[-1][0]
                try:
                    value = os.stat(name, dir_fd=folder, follow_symlinks=False)
                except FileNotFoundError:
                    if not optional:
                        raise Refused('configuration_missing') from None
                    absent.append(alias)
                    # Absence is checked a second time during final configuration validation.
                    for descriptor, before in parents:
                        if stamp(os.fstat(descriptor)) != before:
                            raise Refused('configuration_changed')
                    continue
                if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or not 0 <= value.st_size <= MAX_CONFIG_FILE:
                    raise Refused('configuration_unconfirmed')
                descriptor = os.open(name, READ_FLAGS, dir_fd=folder)
                chain.callback(os.close, descriptor)
                if stamp(os.fstat(descriptor)) != stamp(value):
                    raise Refused('configuration_changed')
                body = bytearray()
                while len(body) < value.st_size:
                    tick(self.end)
                    block = os.pread(descriptor, min(65536, value.st_size - len(body)), len(body))
                    if not block:
                        raise Refused('configuration_changed')
                    body.extend(block)
                if (os.pread(descriptor, 1, value.st_size) or stamp(os.fstat(descriptor)) != stamp(value) or
                        stamp(os.stat(name, dir_fd=folder, follow_symlinks=False)) != stamp(value) or
                        any(stamp(os.fstat(fd)) != before for fd, before in parents)):
                    raise Refused('configuration_changed')
                body = bytes(body)
            total += len(body)
            rows.append({'alias': alias, 'format': format_name, 'body': body,
                         'source_metadata': metadata(value), 'object': None, 'bytes': len(body),
                         'sha256': hashlib.sha256(body).hexdigest()})
        if total > MAX_CONFIG_TOTAL or len(rows) > MAX_CONFIG_OBJECTS or len({row['alias'] for row in rows}) != len(rows):
            raise Refused('configuration_limit')
        if self.total + total > MAX_BYTES:
            raise Refused('data_size_limit')
        return rows, absent, parent_guards

    def check_ref(self, ref, fd=None):
        pid, number = ref['pid'], ref['fd']
        if self.proc.identity(pid) != ref['process_identity']:
            raise Refused('process_changed')
        with self.files.directory(self.proc.root + '/' + str(pid) + '/fd', secure=False) as folder:
            current = os.stat(str(number), dir_fd=folder)
            if stamp(current) != tuple(ref['file_identity']):
                raise Refused('deleted_changed')
        if self.p.fd_flags(self.proc.read(pid, 'fdinfo/' + str(number), 4096)) != (ref['flags'], ref['mount_id']):
            raise Refused('deleted_changed')
        if fd is not None and stamp(os.fstat(fd)) != tuple(ref['file_identity']):
            raise Refused('deleted_changed')

    def pin_deleted(self):
        selected = self.private['deleted_files']
        if len(selected) > MAX_DELETED or sum(len(refs) for refs in selected.values()) > MAX_PINS:
            raise Refused('deleted_limit')
        for identity, refs in sorted(selected.items()):
            if not refs or len(refs) > MAX_PINS:
                raise Refused('deleted_limit')
            for ref in refs:
                self.check_ref(ref)
            ref = refs[0]
            with self.files.directory(self.proc.root + '/' + str(ref['pid']) + '/fd', secure=False) as folder:
                # Intentional, bounded kernel magic-link exception, verified on both sides.
                fd = os.open(str(ref['fd']), MAGIC_FLAGS, dir_fd=folder)
            self.stack.callback(os.close, fd)
            self.check_ref(ref, fd)
            value = os.fstat(fd)
            if (not stat.S_ISREG(value.st_mode) or value.st_nlink != 0 or
                    (value.st_dev, value.st_ino) != identity or not 0 <= value.st_size <= MAX_FILE_BYTES):
                raise Refused('deleted_uncovered')
            self.total += value.st_size
            if self.total > MAX_BYTES:
                raise Refused('data_size_limit')
            self.deleted.append({'fd': fd, 'refs': refs, 'metadata': metadata(value),
                                 'object': None, 'sha256': None})

    def pin_mappings_and_check_io(self):
        captured = {(row['metadata']['device'], row['metadata']['inode']): row['metadata']
                    for row in self.entries if row['kind'] == 'file'}
        captured.update({(row['metadata']['device'], row['metadata']['inode']): row['metadata'] for row in self.deleted})
        for pid, expected in sorted(self.private['process_identities'].items()):
            if self.proc.identity(pid) != expected:
                raise Refused('process_changed')
            with self.files.directory(self.proc.root + '/' + str(pid) + '/fd', secure=False) as folder:
                names = bounded_names(folder, 4096)
                for name in names:
                    target = os.readlink(name, dir_fd=folder)
                    if len(target) > 4096:
                        raise Refused('fd_limit')
                    if target in ('anon_inode:[io_uring]', 'anon_inode:[aio]'):
                        raise Refused('async_io_uncovered')
                    value = os.stat(name, dir_fd=folder)
                    if stat.S_ISREG(value.st_mode):
                        flags, _ = self.p.fd_flags(self.proc.read(pid, 'fdinfo/' + name, 4096))
                        if flags & 0o40000:  # Linux O_DIRECT, independent of the synthetic host OS.
                            raise Refused('direct_io_uncovered')
            raw = self.proc.read(pid, 'maps', 262144)
            for line in raw.splitlines():
                fields = line.split(None, 5)
                if len(fields) < 5:
                    raise Refused('mapping_unpinned')
                if fields[1][1:2] != b'w' or fields[1][3:4] != b's' or fields[4] == b'0':
                    continue
                if re.fullmatch(rb'[0-9a-f]+-[0-9a-f]+', fields[0]) is None or re.fullmatch(rb'[0-9a-f]+:[0-9a-f]+', fields[3]) is None or not fields[4].isdigit():
                    raise Refused('mapping_unpinned')
                major, minor = (int(part, 16) for part in fields[3].split(b':'))
                identity = os.makedev(major, minor), int(fields[4])
                if identity not in captured or len(self.mapping_pins) >= MAX_PINS:
                    raise Refused('mapping_unpinned')
                name = fields[0].decode('ascii')
                try:
                    with self.files.directory(self.proc.root + '/' + str(pid) + '/map_files', secure=False) as folder:
                        fd = os.open(name, MAGIC_FLAGS, dir_fd=folder)
                except OSError:
                    raise Refused('mapping_unpinned') from None
                self.stack.callback(os.close, fd)
                if metadata(os.fstat(fd)) != captured[identity]:
                    raise Refused('mapping_changed')
                self.mapping_pins.append((pid, name, fd, captured[identity]))
            if self.proc.read(pid, 'maps', 262144) != raw or self.proc.identity(pid) != expected:
                raise Refused('mapping_changed')

    @contextlib.contextmanager
    def opened(self, row):
        if 'fd' in row:
            for ref in row['refs']:
                self.check_ref(ref, row['fd'])
            yield row['fd']
            for ref in row['refs']:
                self.check_ref(ref, row['fd'])
            return
        path = '/tmp' if row['scope'] == 'content_tmp' else ROOTS[row['scope']]
        parent, _, name = row['relative_path'].rpartition('/')
        with self.files.directory(path + ('/' + parent if parent else ''), self.bases.get(row['scope']), secure=False) as directory:
            fd = os.open(name, READ_FLAGS, dir_fd=directory)
            try:
                if metadata(os.fstat(fd)) != row['metadata'] or self.files.mount_id(fd) != row['mount_id']:
                    raise Refused('file_changed')
                yield fd
                if metadata(os.stat(name, dir_fd=directory, follow_symlinks=False)) != row['metadata']:
                    raise Refused('file_changed')
            finally:
                os.close(fd)

    def content(self, row, sink=None):
        digest, count = hashlib.sha256(), 0
        with self.opened(row) as fd:
            if metadata(os.fstat(fd)) != row['metadata']:
                raise Refused('file_changed')
            size = row['metadata']['bytes']
            while count < size:
                tick(self.end)
                block = os.pread(fd, min(65536, size - count), count)
                if not block:
                    raise Refused('file_changed')
                count += len(block); digest.update(block)
                if sink is not None:
                    sink.write(block)
            if os.pread(fd, 1, size) or metadata(os.fstat(fd)) != row['metadata']:
                raise Refused('file_changed')
        return digest.hexdigest()

    def validate(self):
        if self.frozen() != self.guard:
            raise Refused('freeze_changed')
        current = self.inventory()
        original = [{**row, 'object': None, 'sha256': None} for row in self.entries]
        if current != original:
            raise Refused('tree_changed')
        for row in [row for row in self.entries if row['kind'] == 'file'] + self.deleted:
            if self.content(row) != row['sha256']:
                raise Refused('content_changed')
        for pid, name, fd, expected in self.mapping_pins:
            with self.files.directory(self.proc.root + '/' + str(pid) + '/map_files', secure=False) as folder:
                if metadata(os.stat(name, dir_fd=folder)) != expected or metadata(os.fstat(fd)) != expected:
                    raise Refused('mapping_changed')
        _, private = self.observe()
        if private != self.private or self.frozen() != self.guard:
            raise Refused('final_guard_changed')
        expected = [{**row, 'object': None} for row in self.recovery]
        if self.configuration() != (expected, self.recovery_absent, self.config_parent_guards):
            raise Refused('configuration_changed')

    def write(self, sink):
        files = [row for row in self.entries if row['kind'] == 'file'] + self.deleted
        for number, row in enumerate(files, 1):
            tick(self.end)
            row['object'] = 'objects/' + str(number).zfill(8)
            sink.header(row['object'], row['metadata']['bytes'])
            row['sha256'] = self.content(row, sink)
            sink.padding(row['metadata']['bytes'])
        for number, row in enumerate(self.recovery, len(files) + 1):
            row['object'] = 'objects/' + str(number).zfill(8)
            sink.header(row['object'], row['bytes']); sink.write(row['body']); sink.padding(row['bytes'])
        self.validate()
        manifest = {'schema': SCHEMA, 'session': SESSION, 'consistency': 'frozen_crash_recovery_candidate',
                    'application_restore_verified': False, 'scopes': list(SCOPES),
                    'containers': {alias: self.guard[alias]['selection'] for alias in ('ad', 'content')},
                    'entries': self.entries,
                    'deleted': [{key: value for key, value in row.items() if key != 'fd'} for row in self.deleted],
                    'recovery_config': [{key: value for key, value in row.items() if key != 'body'} for row in self.recovery],
                    'recovery_config_absent': self.recovery_absent,
                    'object_count': len(files) + len(self.recovery),
                    'source_bytes': sum(row['metadata']['bytes'] for row in files) + sum(row['bytes'] for row in self.recovery)}
        raw = bytearray()
        encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
        for part in encoder.iterencode(manifest):
            tick(self.end)
            encoded = part.encode('ascii')
            if len(raw) + len(encoded) > MAX_MANIFEST:
                raise Refused('manifest_size_limit')
            raw.extend(encoded)
        sink.header('manifest.json', len(raw)); sink.write(raw); sink.padding(len(raw))
        if self.frozen() != self.guard:
            raise Refused('freeze_changed')
        sink.write(b'\0' * 1024)
        return {'status': 'archive_stream_complete', 'session': SESSION,
                'archive_bytes': sink.total, 'object_count': manifest['object_count'],
                'source_bytes': manifest['source_bytes'], 'application_restore_verified': False}


def archive_snapshot(preflight, request, gpg_stdin_fd, *, files=None, docker=None, proc=None, restart_evidence=None):
    """Produce only to the caller-owned GPG pipe. Exceptions mean incomplete backup."""
    if files is None and (os.geteuid() != 0 or sys.platform != 'linux'):
        raise Refused('privilege_or_platform_refused')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    end = time.monotonic() + TIMEOUT
    try:
        with Sink(gpg_stdin_fd, end) as sink, Snapshot(preflight, request, files, docker, proc, end, restart_evidence) as snapshot:
            return snapshot.write(sink)
    except Refused:
        raise
    except BaseException:
        raise Refused('archive_incomplete') from None


if __name__ == '__main__':
    # No standalone plaintext stdout mode, including when root or redirected.
    raise SystemExit(2)
