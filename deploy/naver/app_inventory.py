#!/usr/bin/env python3
"""Read-only, allowlisted host inventory. Never emit command output verbatim."""
import dataclasses
import datetime
import importlib.util
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

sys.dont_write_bytecode = True

MAX_BYTES = 2 * 1024 * 1024
MAX_REPORT_BYTES = 60 * 1024
TIMEOUT = 20
MAX_CONTAINERS = 128
HEX_ID = re.compile(r'(?:sha256:)?[0-9a-f]{64}\Z')
REVISION = re.compile(r'[0-9a-f]{40}\Z')
APPS = ('ad-dashboard', 'content-studio', 'autobid', 'naver', 'logic-analysis')
APP_DIRS = {
    '/root/ad-dashboard-deploy': 'ad-dashboard',
    '/root/content-studio-deploy': 'content-studio',
    '/root/autobid-archive': 'autobid',
    '/root/logic-analysis-deploy': 'logic-analysis',
    '/var/lib/metainc/naver-engine': 'naver',
    '/var/lib/metainc/naver-product-source': 'naver',
    '/var/lib/metainc/naver-market-source': 'naver',
    '/var/backups/metainc/naver-engine': 'naver',
    '/srv/metainc/ad-deploy-staging': 'naver',
}
KNOWN_FILES = ('app.db', 'autobid.db', 'engine.db', 'secret.key', 'enc.key', 'admin.pass',
               'auth.db', 'clients.db', 'categories.db', 'copy_library.db', 'references.db',
               'feedback.db', 'share.db', 'usage.db', 'support.db',
               'studio.db', 'studio_users.db', 'studio_projects.db', 'studio_shares.db',
               'studio_usage.db', 'studio_performance.db', 'studio_categories.db',
               'studio_copy.db', 'studio_support.db', 'studio_advertisers.db')
SIDECARS = ('-wal', '-shm', '-journal')
SUBDIRS = ('data', 'backups', 'sessions', 'projects', 'references')
COMPOSE_FILES = ('docker-compose.yml', 'docker-compose.yaml', 'docker-compose.autobid.yml', 'compose.yml', 'compose.yaml')
RELEASE_FILES = frozenset(('compose.naver-engine.yml', 'compose.naver-relay.yml',
                          'deploy/naver-engine-backup.override.yml',
                          'preview-engine.override.yml', 'preview-relay.override.yml'))
CONTAINER_PATHS = {'/app/data', '/srv/autobid/data', '/var/lib/naver-engine',
                   '/var/lib/naver-product-source', '/var/lib/naver-market-source',
                   '/run/metainc', '/etc/metainc', '/app', '/srv/autobid',
                   '/run/metainc/naver-relay.sock', '/run/metainc/naver-engine.sock',
                   '/run/naver-engine', '/run/naver-relay', '/run/naver-erp-tunnel'}
HOST_METADATA_PATHS = {'/run/metainc/naver-engine', '/run/metainc/naver-relay',
                       '/run/metainc/naver-engine/engine.sock', '/run/metainc/naver-relay/relay.sock',
                       '/run/metainc/naver-engine/naver-engine.sock', '/run/metainc/naver-relay/naver-relay.sock',
                       '/run/metainc-naver-erp-tunnel', '/run/metainc-naver-erp-tunnel/erp.sock',
                       '/etc/metainc/naver-engine/runtime.env', '/etc/metainc/naver-relay/runtime.env'}
VOLUME_RE = re.compile(r'(?:(?:autobid|content-studio|ad-dashboard)[-_])?(?:autobid-data|studio-data|ad-data)\Z')
UNITS = tuple(name + suffix for name in ('naver-engine', 'naver-relay', 'naver-erp-tunnel',
              'metainc-naver-engine', 'metainc-naver-relay', 'metainc-naver-erp-tunnel',
              'logic-analysis', 'ad-dashboard', 'content-studio', 'autobid',
              'autobid-engine', 'autobid-web', 'autobid-watchdog')
              for suffix in ('.service', '.timer')) + ('docker.service', 'nginx.service')
PROPERTIES = ('Id', 'ActiveState', 'SubState', 'MainPID', 'NRestarts', 'UnitFileState',
              'FragmentPath', 'DropInPaths', 'Triggers', 'TriggeredBy', 'Requires', 'Wants', 'After')
ENV_KEYS = {'DB_PATH', 'FERNET_KEY_FILE', 'AUTOBID_DATABASE_URL', 'AUTOBID_ENC_KEY',
            'AUTOBID_AGENT_KEY', 'NAVER_ENGINE_EXECUTION_ENABLED'}
STATE_VALUES = {'created', 'running', 'paused', 'restarting', 'removing', 'exited', 'dead'}
SERVICE_VALUES = {'active', 'inactive', 'failed', 'activating', 'deactivating', 'reloading',
                  'running', 'dead', 'exited', 'waiting', 'elapsed', 'listening', 'start',
                  'enabled', 'disabled', 'static', 'indirect', 'generated', 'masked', 'not-found',
                  'enabled-runtime', 'masked-runtime', 'alias', 'linked', 'linked-runtime', 'bad'}
REDACTED = '<redacted>'


@dataclasses.dataclass
class CommandResult:
    returncode: int = 0
    stdout: str = ''
    truncated: bool = False
    error: str = None


def run_command(argv, timeout=TIMEOUT, max_bytes=MAX_BYTES):
    """Bound both output streams together; retain stdout only, discard stderr."""
    process = None
    try:
        process = subprocess.Popen(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=False, start_new_session=True)
        deadline = time.monotonic() + timeout
        total = 0
        chunks = []
        error = None
        truncated = False
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, True)
            selector.register(process.stderr, selectors.EVENT_READ, False)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    error = 'timeout'
                    break
                events = selector.select(min(remaining, 0.2))
                for key, _ in events:
                    block = os.read(key.fileobj.fileno(), min(65536, max_bytes - total + 1))
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(block)
                    if total > max_bytes:
                        truncated = True
                        error = 'output_limit'
                        break
                    if key.data:
                        chunks.append(block)
                if error:
                    break
        if error:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()) if not error else 2)
        return CommandResult(returncode, b''.join(chunks).decode('utf-8', 'replace'), truncated, error)
    except subprocess.TimeoutExpired:
        if process:
            try:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass
        return CommandResult(-1, error='timeout')
    except (OSError, ValueError, subprocess.SubprocessError):
        return CommandResult(-1, error='command_unavailable')
    finally:
        if process:
            for stream in (process.stdout, process.stderr):
                if stream:
                    stream.close()


def integer(value):
    return value if type(value) is int and value >= 0 else None


def timestamp(value):
    if isinstance(value, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?Z', value):
        return value
    return None


def known_volume(value):
    return isinstance(value, str) and bool(VOLUME_RE.fullmatch(value))


def safe_path(value):
    """Only previously approved application paths and fixed metadata basenames."""
    if not isinstance(value, str) or '\x00' in value or os.path.normpath(value) != value:
        return None
    if value == '/' or value in APP_DIRS or value in HOST_METADATA_PATHS:
        return value
    for base in APP_DIRS:
        if value in (base + '/' + item for item in COMPOSE_FILES):
            return value
        if value in (base + '/' + item for item in SUBDIRS):
            return value
        for directory in (base, base + '/data'):
            if value in (directory + '/' + item + suffix for item in KNOWN_FILES for suffix in ('',) + SIDECARS):
                return value
    release = re.fullmatch(r'/srv/metainc/ad-deploy-staging/releases/naver-[0-9a-f]{40}(?:/(.+))?', value)
    if release and (release[1] is None or release[1] in RELEASE_FILES):
        return value
    if re.fullmatch(r'/srv/metainc/ad-deploy-staging/saved-exports/[0-9a-f]{32}/naver-saved-exports\.override\.yml', value):
        return value
    if value.startswith('/var/lib/docker/volumes/'):
        parts = value.split('/')
        if len(parts) == 7 and known_volume(parts[5]) and parts[6] == '_data':
            return value
        if len(parts) == 8 and known_volume(parts[5]) and parts[6] == '_data' and parts[7] in {
                name + suffix for name in KNOWN_FILES for suffix in ('',) + SIDECARS}:
            return value
    return None


def classify(name='', image='', labels=None):
    labels = labels or {}
    # A shared Compose project may run several applications. Its explicit service
    # identifies the workload before the broader project or repository hints.
    values = [labels.get('com.docker.compose.service', ''), name, image,
              labels.get('com.docker.compose.project', '')]
    for value in values:
        if not isinstance(value, str):
            continue
        repository = value.split('@')[0].split(':')[0].split('/')[-1]
        if re.fullmatch(r'(?:ad-api|ad-dashboard(?:-deploy)?(?:[-_]ad-api(?:[-_]1)?)?)', repository):
            return 'ad-dashboard'
        if re.fullmatch(r'(?:content-studio(?:-deploy)?(?:[-_]content-studio(?:[-_]1)?)?)', repository):
            return 'content-studio'
        if re.fullmatch(r'(?:autobid|autobid[-_](?:web|engine|watchdog|autobid[-_](?:web|engine|watchdog))(?:[-_]1)?)', repository):
            return 'autobid'
        if re.fullmatch(r'(?:naver[-_](?:engine|relay)(?:[-_]1)?|metainc[-_]naver[-_](?:engine|relay))', repository):
            return 'naver'
        if re.fullmatch(r'logic-analysis(?:-deploy)?(?:[-_]logic-analysis(?:[-_]1)?)?', repository):
            return 'logic-analysis'
    return None


def known_name(value):
    if not isinstance(value, str):
        return REDACTED
    name = value[1:] if value.startswith('/') else value
    if '/' in name or ':' in name or '@' in name or not re.fullmatch(r'[a-z0-9_-]{1,100}', name):
        return REDACTED
    return name if classify(name) else REDACTED


def source_label(value):
    allowed = {'https://github.com/metainchelp-boop/metainc-ad-dashboard',
               'https://github.com/metainchelp-boop/metainc-content-studio',
               'https://github.com/metainchelp-boop/logic-analysis'}
    return value if isinstance(value, str) and value in allowed else REDACTED


def image_reference(value):
    if not isinstance(value, str):
        return REDACTED
    if HEX_ID.fullmatch(value):
        return value
    # Retain only known repository identities. Arbitrary tags can contain secrets.
    repository = value.split('@')[0].split(':')[0]
    leaf = repository.split('/')[-1]
    return leaf if classify(image=leaf) else REDACTED


def container_template():
    fields = {'id': '.Id', 'name': '.Name', 'image_id': '.Image', 'image': '.Config.Image',
              'status': '.State.Status', 'running': '.State.Running', 'pid': '.State.Pid',
              'started_at': '.State.StartedAt', 'finished_at': '.State.FinishedAt',
              'restart_count': '.RestartCount', 'restart_policy': '.HostConfig.RestartPolicy.Name',
              'mounts': '.Mounts', 'ports': '.HostConfig.PortBindings', 'network_mode': '.HostConfig.NetworkMode'}
    items = [json.dumps(key) + ':{{json ' + expression + '}}' for key, expression in fields.items()]
    labels = ('com.docker.compose.project', 'com.docker.compose.service', 'com.docker.compose.project.working_dir',
              'com.docker.compose.project.config_files', 'metainc.naver.preview.source',
              'org.opencontainers.image.revision', 'org.opencontainers.image.source')
    items.append('"labels":{' + ','.join(json.dumps(key) + ':{{json (index .Config.Labels ' + json.dumps(key) + ')}}' for key in labels) + '}')
    items.append('"env_keys":[{{range $i,$e := .Config.Env}}{{if $i}},{{end}}{{json (index (split $e "=") 0)}}{{end}}]')
    return '{' + ','.join(items) + '}'


class Collector:
    def __init__(self, runner=None, root=''):
        self.runner = runner or run_command
        self.root = root.rstrip('/')
        self.coverage = []
        self.metadata_cache = {}

    def command(self, query, argv, timeout=TIMEOUT, max_bytes=MAX_BYTES):
        try:
            result = self.runner(list(argv), timeout=timeout, max_bytes=max_bytes)
        except Exception:
            # A runner error can include credentials in its exception text.
            self.coverage.append({'query': query, 'status': 'runner_error'})
            return None
        if not isinstance(result, CommandResult):
            self.coverage.append({'query': query, 'status': 'runner_contract_error'})
            return None
        status = ('output_limit' if result.truncated else result.error if result.error in
                  {'timeout', 'output_limit', 'command_unavailable'} else
                  'command_failed' if result.returncode != 0 or result.error else 'ok')
        self.coverage.append({'query': query, 'status': status, 'returncode': result.returncode if type(result.returncode) is int else None,
                              'truncated': bool(result.truncated)})
        return result.stdout if status == 'ok' else None

    def parsed(self, query, text):
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            self.coverage.append({'query': query, 'status': 'parse_error'})
            return None

    def local(self, path):
        """lstat every component, refusing symlink traversal including fixture root."""
        if not safe_path(path) and path not in ('/etc/crontab', '/etc/cron.d'):
            return None, 'unapproved_path'
        real = self.root + path
        current = '/'
        try:
            for part in real.split('/'):
                if not part:
                    continue
                current = os.path.join(current, part)
                info = os.lstat(current)
                if stat.S_ISLNK(info.st_mode):
                    return None, 'symlink_refused'
            return real, 'ok'
        except FileNotFoundError:
            return None, 'absent'
        except OSError:
            return None, 'stat_failed'

    def metadata(self, path, usage=False):
        if safe_path(path) is None:
            return {'path': REDACTED, 'status': 'unapproved_path'}
        cache_key = (path, usage)
        if cache_key in self.metadata_cache:
            return dict(self.metadata_cache[cache_key])
        real, status = self.local(path)
        result = {'path': path, 'status': status}
        if not real:
            return result
        try:
            before = os.lstat(real)
            if not (stat.S_ISREG(before.st_mode) or stat.S_ISDIR(before.st_mode) or stat.S_ISSOCK(before.st_mode)):
                result['status'] = 'unsupported_file_type'
                return result
            result.update(kind='directory' if stat.S_ISDIR(before.st_mode) else 'socket' if stat.S_ISSOCK(before.st_mode) else 'file',
                          size_bytes=before.st_size, blocks_bytes=before.st_blocks * 512,
                          mode=oct(stat.S_IMODE(before.st_mode)), uid=before.st_uid, gid=before.st_gid,
                          device=before.st_dev, inode=before.st_ino, mtime_ns=before.st_mtime_ns,
                          links=before.st_nlink)
            if usage and stat.S_ISDIR(before.st_mode):
                text = self.command('directory_usage', ['du', '-P', '-x', '-s', '-B1', '--', real])
                if text is not None:
                    match = re.fullmatch(r'(\d+)\s+[^\n]+\n?', text)
                    result['usage_bytes'] = int(match[1]) if match else None
                    result['usage_status'] = 'ok' if match else 'parse_error'
                else:
                    result['usage_status'] = 'unavailable'
                after = os.lstat(real)
                if (before.st_dev, before.st_ino, before.st_mode) != (after.st_dev, after.st_ino, after.st_mode):
                    result.pop('usage_bytes', None)
                    result['status'] = 'changed_during_query'
        except OSError:
            result['status'] = 'stat_failed'
        self.metadata_cache[cache_key] = dict(result)
        return result

    def filesystem(self):
        real, status = self.local('/')
        if not real:
            return {'path': '/', 'status': status}
        try:
            info = os.statvfs(real)
            return {'path': '/', 'status': 'ok', 'total_bytes': info.f_blocks * info.f_frsize,
                    'free_bytes': info.f_bfree * info.f_frsize,
                    'available_nonroot_bytes': info.f_bavail * info.f_frsize,
                    'fragment_size_bytes': info.f_frsize}
        except OSError:
            return {'path': '/', 'status': 'statvfs_failed'}

    def mounts(self, entries):
        result = []
        for mount in entries[:128] if isinstance(entries, list) else []:
            if not isinstance(mount, dict):
                continue
            kind = mount.get('Type')
            source = safe_path(mount.get('Source'))
            destination = mount.get('Destination')
            row = {'type': kind if kind in {'bind', 'volume', 'tmpfs'} else 'unknown',
                   'source': source or REDACTED,
                   'destination': destination if destination in CONTAINER_PATHS else REDACTED,
                   'read_write': mount.get('RW') if type(mount.get('RW')) is bool else None}
            name = mount.get('Name')
            if kind == 'volume':
                row['name'] = name if known_volume(name) else REDACTED
            if source:
                row['metadata'] = self.metadata(source, usage=True)
            result.append(row)
        return result

    def container(self, raw):
        labels = raw.get('labels') if isinstance(raw.get('labels'), dict) else {}
        app = classify(raw.get('name', ''), raw.get('image', ''), labels)
        if not app:
            return None
        identifier = raw.get('id')
        image_id = raw.get('image_id')
        row = {'app': app, 'name': known_name(raw.get('name')), 'id': identifier if isinstance(identifier, str) and HEX_ID.fullmatch(identifier) else None,
               'image_id': image_id if isinstance(image_id, str) and HEX_ID.fullmatch(image_id) else None,
               'image_repository': image_reference(raw.get('image')),
               'status': raw.get('status') if raw.get('status') in STATE_VALUES else 'unknown',
               'running': raw.get('running') if type(raw.get('running')) is bool else None,
               'pid': integer(raw.get('pid')), 'restart_count': integer(raw.get('restart_count')),
               'started_at': timestamp(raw.get('started_at')), 'finished_at': timestamp(raw.get('finished_at')),
               'restart_policy': raw.get('restart_policy') if raw.get('restart_policy') in {'no', 'always', 'unless-stopped', 'on-failure'} else 'unknown',
               'mounts': self.mounts(raw.get('mounts'))}
        row['mount_list_status'] = 'ok' if isinstance(raw.get('mounts'), list) and len(raw['mounts']) <= 128 else 'partial_or_invalid'
        safe_labels = {}
        for key, value in labels.items():
            if key in ('com.docker.compose.project', 'com.docker.compose.service'):
                safe_labels[key] = known_name(value)
            elif key == 'com.docker.compose.project.working_dir':
                safe_labels[key] = safe_path(value) or REDACTED
            elif key == 'com.docker.compose.project.config_files':
                files = value.split(',') if isinstance(value, str) else []
                safe_labels[key] = [safe_path(item) or REDACTED for item in files[:8]]
                row['compose_config_files_total_count'] = len(files) if isinstance(value, str) else None
                row['compose_config_files_truncated'] = len(files) > 8
                row['compose_config_files_status'] = ('incomplete' if len(files) > 8 or
                    any(safe_path(item) is None for item in files) else 'ok' if isinstance(value, str) else 'unavailable')
            elif key == 'org.opencontainers.image.revision':
                safe_labels[key] = value if isinstance(value, str) and REVISION.fullmatch(value) else None
            elif key == 'metainc.naver.preview.source':
                safe_labels[key] = value if isinstance(value, str) and REVISION.fullmatch(value) else None
            elif key == 'org.opencontainers.image.source':
                safe_labels[key] = source_label(value)
        row['labels'] = safe_labels
        keys = raw.get('env_keys')
        row['environment_presence'] = {key: key in keys for key in sorted(ENV_KEYS)} if isinstance(keys, list) else None
        row['studio_db_variable_count'] = sum(1 for key in keys if isinstance(key, str) and re.fullmatch(r'STUDIO_[A-Z_]+_DB', key)) if isinstance(keys, list) else None
        row['naver_variable_count'] = sum(1 for key in keys if isinstance(key, str) and key.startswith('NAVER_')) if isinstance(keys, list) else None
        row['database_driver_and_path'] = 'unverified_environment_values_not_read'
        row['network_mode'] = raw.get('network_mode') if raw.get('network_mode') in {'host', 'bridge', 'none', 'default'} else 'other_or_unknown'
        row['ports'] = self.ports(raw.get('ports'))
        return row

    @staticmethod
    def ports(raw):
        result = []
        for port, bindings in list(raw.items())[:64] if isinstance(raw, dict) else []:
            if not re.fullmatch(r'\d{1,5}/(?:tcp|udp)', port) or int(port.split('/')[0]) > 65535:
                continue
            for binding in bindings[:16] if isinstance(bindings, list) else []:
                if not isinstance(binding, dict):
                    continue
                address = binding.get('HostIp', '')
                try:
                    addr = ipaddress.ip_address(address)
                    address = str(addr) if addr.is_loopback or addr.is_unspecified else REDACTED
                except ValueError:
                    address = 'default' if address == '' else REDACTED
                number = binding.get('HostPort', '')
                result.append({'container_port': port, 'host_ip': address,
                               'host_port': int(number) if isinstance(number, str) and number.isdigit() and 0 < int(number) <= 65535 else None})
        return result

    def docker(self):
        listing = self.command('docker_container_list', ['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}'])
        out = {'containers': [], 'images': [], 'volumes': [], 'inventory_status': 'unavailable'}
        identifiers = listing.splitlines() if listing is not None else []
        if any(not HEX_ID.fullmatch(value) for value in identifiers):
            self.coverage.append({'query': 'docker_container_list', 'status': 'parse_error'})
            identifiers = []
            listing = None
        out['total_containers'] = len(identifiers)
        out['inventory_status'] = 'unavailable' if listing is None else 'partial' if len(identifiers) > MAX_CONTAINERS else 'ok'
        template = container_template()
        for identifier in identifiers[:MAX_CONTAINERS]:
            text = self.command('docker_container_inspect', ['docker', 'inspect', '--format', template, identifier])
            if text is None:
                out['inventory_status'] = 'partial'
                continue
            raw = self.parsed('docker_container_inspect', text)
            if not isinstance(raw, dict):
                out['inventory_status'] = 'partial'
                continue
            row = self.container(raw)
            if row:
                out['containers'].append(row)
                if row.get('compose_config_files_status') == 'incomplete':
                    out['inventory_status'] = 'partial'
        image_ids = {row['image_id'] for row in out['containers'] if row['image_id']}
        image_listing = self.command('docker_image_list', ['docker', 'image', 'ls', '--no-trunc', '--format',
            '{"id":{{json .ID}},"repository":{{json .Repository}}}'])
        out['image_list_status'] = 'unavailable' if image_listing is None else 'ok'
        if image_listing is not None:
            for line in image_listing.splitlines()[:512]:
                raw = self.parsed('docker_image_list', line)
                if not isinstance(raw, dict):
                    out['image_list_status'] = 'partial'
                    continue
                if isinstance(raw, dict) and classify(image=raw.get('repository', '')):
                    identifier = raw.get('id')
                    if isinstance(identifier, str) and HEX_ID.fullmatch(identifier):
                        image_ids.add(identifier)
                    else:
                        out['image_list_status'] = 'partial'
            if len(image_listing.splitlines()) > 512:
                out['image_list_status'] = 'partial'
        image_template = '{"id":{{json .Id}},"size":{{json .Size}},"tags":{{json .RepoTags}},"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}}}'
        for identifier in sorted(image_ids):
            text = self.command('docker_image_inspect', ['docker', 'image', 'inspect', '--format', image_template, identifier])
            raw = self.parsed('docker_image_inspect', text) if text is not None else None
            if isinstance(raw, dict):
                returned = raw.get('id')
                if not isinstance(returned, str) or returned.removeprefix('sha256:') != identifier.removeprefix('sha256:'):
                    self.coverage.append({'query': 'docker_image_inspect', 'status': 'identity_unconfirmed'})
                    out['image_list_status'] = 'partial'
                    continue
                out['images'].append({'id': returned if isinstance(returned, str) and HEX_ID.fullmatch(returned) else None,
                    'size_bytes': integer(raw.get('size')), 'repositories': sorted({image_reference(tag) for tag in (raw.get('tags') or []) if isinstance(tag, str)}),
                    'revision': raw.get('revision') if isinstance(raw.get('revision'), str) and REVISION.fullmatch(raw['revision']) else None})
            else:
                out['image_list_status'] = 'partial'
        names = {mount['name'] for row in out['containers'] for mount in row['mounts']
                 if mount['type'] == 'volume' and known_volume(mount.get('name'))}
        volume_listing = self.command('docker_volume_list', ['docker', 'volume', 'ls', '--format', '{{.Name}}'])
        out['volume_list_status'] = 'unavailable' if volume_listing is None else 'ok'
        if volume_listing is not None:
            names.update(name for name in volume_listing.splitlines()[:512] if known_volume(name))
            out['unclassified_volume_count'] = sum(1 for name in volume_listing.splitlines()[:512] if not known_volume(name))
            if len(volume_listing.splitlines()) > 512:
                out['volume_list_status'] = 'partial'
        volume_template = '{"name":{{json .Name}},"driver":{{json .Driver}},"mountpoint":{{json .Mountpoint}}}'
        for name in sorted(names):
            text = self.command('docker_volume_inspect', ['docker', 'volume', 'inspect', '--format', volume_template, name])
            raw = self.parsed('docker_volume_inspect', text) if text is not None else None
            if isinstance(raw, dict):
                if raw.get('name') != name:
                    self.coverage.append({'query': 'docker_volume_inspect', 'status': 'identity_unconfirmed'})
                    out['volume_list_status'] = 'partial'
                    continue
                path = safe_path(raw.get('mountpoint'))
                row = {'name': name, 'driver': 'local' if raw.get('driver') == 'local' else 'other_or_unknown', 'mountpoint': path or REDACTED}
                if path:
                    row['metadata'] = self.metadata(path, usage=True)
                    row.update(self.known_file_metadata((path,)))
                out['volumes'].append(row)
            else:
                out['volume_list_status'] = 'partial'
        return out

    def known_file_metadata(self, directories):
        found = []
        absent = 0
        for directory in directories:
            for name in KNOWN_FILES:
                for suffix in ('',) + SIDECARS:
                    row = self.metadata(directory + '/' + name + suffix)
                    if row['status'] == 'absent':
                        absent += 1
                    else:
                        found.append(row)
        return {'known_files': found, 'absent_known_file_count': absent,
                'file_scope': 'fixed_allowlist_only_no_directory_enumeration'}

    def systemd(self):
        listings = [self.command('systemd_unit_files', ['systemctl', 'list-unit-files', '--type=service',
                    '--type=timer', '--no-legend', '--no-pager']),
                    self.command('systemd_units', ['systemctl', 'list-units', '--all', '--type=service',
                    '--type=timer', '--no-legend', '--no-pager', '--plain'])]
        present = set()
        related_unknown = set()
        for listing in listings:
            if listing is not None:
                for line in listing.splitlines():
                    parts = line.split()
                    if parts and parts[0] in UNITS:
                        present.add(parts[0])
                    elif parts and re.match(r'(?:metainc[-_.])?(?:naver|ad-dashboard|content-studio|autobid|logic-analysis)(?:[-_.@]|$)', parts[0]) and parts[0].endswith(('.service', '.timer')):
                        related_unknown.add(parts[0])
        units = []
        for unit in sorted(present):
            text = self.command('systemd_metadata', ['systemctl', 'show', unit,
                                *[item for prop in PROPERTIES for item in ('-p', prop)], '--no-pager'])
            if text is None:
                units.append({'name': unit, 'status': 'unavailable'})
                continue
            fields = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
            if fields.get('Id') != unit:
                units.append({'name': unit, 'status': 'identity_unconfirmed'})
                continue
            row = {'name': fields['Id'], 'status': 'ok'}
            for key in ('ActiveState', 'SubState', 'UnitFileState'):
                value = fields.get(key)
                row[key] = value if value in SERVICE_VALUES else 'unknown'
            for key in ('MainPID', 'NRestarts'):
                value = fields.get(key, '')
                row[key] = int(value) if value.isdigit() else None
            for key in ('Triggers', 'TriggeredBy', 'Requires', 'Wants', 'After'):
                values = fields.get(key, '').split()
                row[key] = [value for value in values if value in UNITS]
                row[key + '_other_count'] = len(values) - len(row[key])
            for key in ('FragmentPath', 'DropInPaths'):
                values = fields.get(key, '').split()
                row[key] = [value if value in {'/etc/systemd/system/' + unit for unit in UNITS} else REDACTED for value in values]
            units.append(row)
        return {'status': 'incomplete' if related_unknown else 'ok' if all(value is not None for value in listings) and all(row['status'] == 'ok' for row in units) else 'partial',
                'units': units, 'not_listed_known_units': [unit for unit in UNITS if unit not in present],
                'related_unapproved_unit_count': len(related_unknown),
                'related_unapproved_unit_meaning': 'name_redacted_and_metadata_not_queried',
                'not_listed_meaning': 'not_reported_by_inventory_not_proof_of_no_other_supervisor'}

    @staticmethod
    def cron_field(value, minimum, maximum):
        """Validate bounded numeric cron syntax before publishing it."""
        if not isinstance(value, str) or len(value) > 48:
            return False
        def number(text, low, high):
            return bool(re.fullmatch(r'[0-9]{1,2}', text)) and low <= int(text) <= high
        for item in value.split(','):
            pieces = item.split('/')
            if len(pieces) > 2:
                return False
            if len(pieces) == 2 and not number(pieces[1], 1, maximum - minimum + 1):
                return False
            base = pieces[0]
            if base == '*':
                continue
            bounds = base.split('-')
            if len(bounds) == 1:
                if not number(base, minimum, maximum):
                    return False
            elif len(bounds) == 2:
                if not all(number(part, minimum, maximum) for part in bounds) or int(bounds[0]) > int(bounds[1]):
                    return False
            else:
                return False
        return bool(value)

    @staticmethod
    def cron_summary(text):
        matches = {app: [] for app in APPS}
        skipped = 0
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            parts = stripped.split()
            if not parts:
                continue
            if parts[0] in {'@reboot', '@yearly', '@annually', '@monthly', '@weekly', '@daily', '@midnight', '@hourly'}:
                schedule = parts[0]
                command = ' '.join(parts[1:])
            elif len(parts) >= 6 and all(Collector.cron_field(part, minimum, maximum)
                    for part, (minimum, maximum) in zip(parts[:5], ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7)))):
                schedule = ' '.join(parts[:5])
                command = ' '.join(parts[5:])
            else:
                skipped += 1
                continue
            for app in APPS:
                tokens = {'ad-dashboard': ('ad-dashboard', 'ad-api'), 'content-studio': ('content-studio',),
                          'autobid': ('autobid',), 'naver': ('naver-engine', 'naver-relay', 'naver-backup'),
                          'logic-analysis': ('logic-analysis',)}[app]
                if any(token in command for token in tokens):
                    matches[app].append(schedule)
        return {'apps': {app: {'count': len(values), 'schedules': sorted(set(values))} for app, values in matches.items()},
                'unparsed_noncomment_lines': skipped,
                'classification': 'app_keyword_hint_not_execution_or_target_confirmation'}

    def cron(self):
        rows = []
        text = self.command('root_crontab', ['crontab', '-l', '-u', 'root'], max_bytes=262144)
        rows.append({'source': 'root_crontab', 'status': 'ok' if text is not None else 'unavailable',
                     'summary': self.cron_summary(text) if text is not None else None})
        for path in ('/etc/crontab', '/etc/cron.d'):
            real, status = self.local(path)
            if not real:
                rows.append({'source': path, 'status': status})
                continue
            try:
                if os.path.isdir(real):
                    entries = list(os.scandir(real))
                    rows.append({'source': path, 'status': 'partial' if len(entries) > 128 else 'ok', 'file_count': len(entries)})
                    for entry in entries[:128]:
                        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                            rows.append({'source': '/etc/cron.d/<file>', 'status': 'symlink_or_nonfile_refused'})
                            continue
                        rows.append(self.cron_file(entry.path, '/etc/cron.d/<file>'))
                else:
                    rows.append(self.cron_file(real, path))
            except OSError:
                rows.append({'source': path, 'status': 'read_failed'})
        return rows

    def cron_file(self, path, source):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    return {'source': source, 'status': 'unsupported_file_type'}
                raw = handle.read(262145)
            if len(raw) > 262144:
                return {'source': source, 'status': 'output_limit'}
            return {'source': source, 'status': 'ok', 'summary': self.cron_summary(raw.decode('utf-8', 'replace'))}
        except OSError:
            return {'source': source, 'status': 'read_failed'}

    def git(self, containers):
        paths = sorted({row['labels'].get('com.docker.compose.project.working_dir') for row in containers
                        if row['labels'].get('com.docker.compose.project.working_dir') in APP_DIRS})
        rows = []
        for path in paths:
            real, status = self.local(path)
            row = {'working_dir': path, 'status': status}
            if real:
                top = self.command('git_toplevel', ['git', '-C', real, 'rev-parse', '--show-toplevel'], max_bytes=4096)
                if top is None or top.strip() != real:
                    row['status'] = 'toplevel_unconfirmed'
                else:
                    head = self.command('git_head', ['git', '-C', real, 'rev-parse', 'HEAD'], max_bytes=4096)
                    branch = self.command('git_branch', ['git', '-C', real, 'symbolic-ref', '--short', '-q', 'HEAD'], max_bytes=4096)
                    row['head'] = head.strip() if head and REVISION.fullmatch(head.strip()) else None
                    row['branch'] = branch.strip() if branch and branch.strip() in {'main', 'master'} else 'other_or_detached_or_unavailable'
                    row['status'] = 'ok' if row['head'] else 'head_unavailable'
            rows.append(row)
        return rows

    def nginx(self):
        text = self.command('nginx_configuration', ['nginx', '-T'], max_bytes=MAX_BYTES)
        if text is None:
            return {'status': 'unavailable'}
        try:
            path = os.path.join(os.path.dirname(__file__), 'nginx_inventory.py')
            spec = importlib.util.spec_from_file_location('naver_nginx_inventory', path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module.summarize_nginx(text)
        except Exception:
            return {'status': 'parser_unavailable_or_failed'}


def collect(runner=None, root=''):
    collector = Collector(runner, root)
    docker = collector.docker()
    paths = []
    for base, app in APP_DIRS.items():
        row = collector.metadata(base, usage=True)
        row['app'] = app
        if row['status'] != 'absent':
            row.update(collector.known_file_metadata((base, base + '/data')))
        paths.append(row)
    return {'schema_version': 1, 'read_only': True,
            'collected_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'host_role': 'existing_vps', 'filesystem': collector.filesystem(), 'docker': docker,
            'paths': paths, 'protected_runtime_paths': [collector.metadata(path) for path in sorted(HOST_METADATA_PATHS)],
            'git': collector.git(docker['containers']), 'systemd': collector.systemd(),
            'cron': collector.cron(), 'nginx': collector.nginx(), 'coverage': collector.coverage,
            'unverified': ['container_internal_tmp_studio_databases', 'database_driver_and_environment_values',
                           'mac_agent', 'erp_runtime', 'remote_backup_restore', 'public_certificate_contents',
                           'unknown_mount_paths_and_volumes', 'unknown_service_users_and_cron_periodic_directories',
                           'filesystem_mount_topology', 'shared_image_layer_reclaim']}


def main():
    sys.dont_write_bytecode = True
    try:
        result = collect()
    except Exception:
        # Never serialize exception text or raw subprocess output.
        result = {'schema_version': 1, 'read_only': True, 'status': 'collector_failed', 'coverage': 'incomplete'}
    encoded = json.dumps(result, ensure_ascii=True, separators=(',', ':'))
    if len(encoded.encode('utf-8')) > MAX_REPORT_BYTES:
        result = {'schema_version': 1, 'read_only': True, 'status': 'collector_output_limit',
                  'coverage': 'incomplete', 'report_limit_bytes': MAX_REPORT_BYTES}
        encoded = json.dumps(result, separators=(',', ':'))
    print('NAVER_DEPLOY_APP_INVENTORY=' + encoded)
    return 1 if result.get('status') in {'collector_failed', 'collector_output_limit'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
