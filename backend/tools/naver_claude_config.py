"""Server-local Claude configuration transaction. No provider request or DB access."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import time


# Repin these exact two reviewed releases before dispatching a new product build.
SOURCE_COMMIT = '9ddb0a30e16e4177e8d419318a6f23eb6c206e2f'
ROLLBACK_COMMIT = '09b216f26509fed97179114ee97cb0d4169ce5f8'
BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
MODEL = 'claude-sonnet-5-5'
SETTINGS = {'NAVER_CLAUDE_ENABLED': 'true', 'CLAUDE_MODEL': MODEL,
            'NAVER_CLAUDE_MONTHLY_CAP_USD': 'unlimited',
            'NAVER_CLAUDE_INPUT_USD_PER_MILLION': '2',
            'NAVER_CLAUDE_OUTPUT_USD_PER_MILLION': '10',
            'NAVER_CLAUDE_TIMEOUT_SECONDS': '20'}
ALLOWED = frozenset(SETTINGS) | {'ANTHROPIC_API_KEY'}
TERMINAL = frozenset({'committed', 'recovered', 'rejected'})
STAGE = 'input'
FACTORY_PROGRAM = (
    "import json,sys;sys.path.insert(0,'/opt/naver-engine');"
    "from naver_runtime.learning_provider import provider_from_environment;"
    "p=provider_from_environment();"
    "assert p is not None and p.model=='" + MODEL + "';"
    "assert p.monthly_budget_microusd is None and p.monthly_budget_unlimited is True;"
    "assert p.maximum_call_microusd==90536 and p._timeout==20;"
    "print(json.dumps({'configured':True,'unlimited':True},sort_keys=True,separators=(',',':')))"
)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def validate_request(request, now=None):
    now = int(time.time()) if now is None else now
    if not isinstance(request, dict) or set(request) != {
            'operation', 'operation_id', 'expires_at', 'baseline', 'source_commit', 'rollback_commit'}:
        raise ValueError('CONFIG_REQUEST')
    if (request['operation'] not in ('activate', 'recover') or request['baseline'] != BASELINE or
            request['source_commit'] != SOURCE_COMMIT or request['rollback_commit'] != ROLLBACK_COMMIT or
            not isinstance(request['operation_id'], str) or not re.fullmatch('[0-9a-f]{32}', request['operation_id']) or
            type(request['expires_at']) is not int or not now < request['expires_at'] <= now + 900):
        raise ValueError('CONFIG_REQUEST')
    return request


def unrelated(body):
    return b''.join(line for line in body.splitlines(keepends=True)
                    if line.split(b'=', 1)[0] not in {name.encode() for name in ALLOWED})


def candidate_env(original, key):
    if (not isinstance(original, bytes) or not 0 < len(original) <= 32768 or b'\x00' in original or
            not original.endswith(b'\n') or not isinstance(key, bytes) or not re.fullmatch(rb'[\x21-\x7e]{1,4096}', key)):
        raise ValueError('CONFIG_ENV_POLICY')
    values = {name.encode(): value.encode() for name, value in SETTINGS.items()}
    values[b'ANTHROPIC_API_KEY'] = key
    seen, lines = set(), []
    for line in original.splitlines(keepends=True):
        name = line.split(b'=', 1)[0]
        if name in values:
            if name in seen:
                raise ValueError('CONFIG_DUPLICATE_SETTING')
            seen.add(name)
            lines.append(name + b'=' + values[name] + b'\n')
        else:
            if any(re.match(rb'\s*' + re.escape(name) + rb'\s*=', line) for name in values):
                raise ValueError('CONFIG_SETTING_SYNTAX')
            lines.append(line)
    lines.extend(name + b'=' + values[name] + b'\n' for name in sorted(set(values) - seen))
    result = b''.join(lines)
    if len(result) > 32768 or unrelated(original) != unrelated(result):
        raise ValueError('CONFIG_ENV_SCOPE')
    return result


class Transaction:
    def __init__(self, request, host, release, upgrade, lifecycle):
        self.request, self.host, self.release, self.upgrade, self.lifecycle = request, host, release, upgrade, lifecycle
        self.root = release.ROOT / 'claude-config'
        self.folder = self.root / request['operation_id']
        self.env = release.SECRET_ROOT / 'runtime.env'
        self.paths = [self.env] + [release.ROOT / 'receipts' / ('preview-' + commit + '.json')
                                  for commit in (SOURCE_COMMIT, ROLLBACK_COMMIT)]
        self.source = release.ROOT / 'releases' / ('naver-' + SOURCE_COMMIT)
        self.journal = None

    def read(self, path, maximum=32768, minimum=1):
        return self.upgrade.read_file(path, mode=0o600, maximum=maximum, minimum=minimum)

    def sync_dir(self, path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def new(self, path, body):
        self.release.write_new(path, body)
        self.sync_dir(path.parent)

    def replace(self, path, body, expected):
        if self.read(path, minimum=0) != expected:
            raise ValueError('CONFIG_FILE_DRIFT')
        # A crash can leave a private incomplete file. Never reuse or overwrite it.
        # A fresh exclusive name lets recovery proceed without trusting stale bytes.
        temporary = path.with_name('.claude-' + self.request['operation_id'] + '-' + os.urandom(12).hex() + '-' + path.name)
        self.new(temporary, body)
        if self.read(path, minimum=0) != expected:
            raise ValueError('CONFIG_FILE_DRIFT')
        os.replace(temporary, path)
        self.sync_dir(path.parent)

    def save(self, state):
        self.journal['state'] = state
        body = json.dumps(self.journal, sort_keys=True, separators=(',', ':')).encode()
        path = self.folder / 'journal.json'
        if os.path.lexists(path):
            self.replace(path, body, self.read(path, minimum=0))
        else:
            self.new(path, body)

    def manifests(self):
        active_path, active = self.upgrade.manifest(self.release, SOURCE_COMMIT, started=True)
        self.upgrade.manifest(self.release, ROLLBACK_COMMIT, started=True)
        if active_path != self.source:
            raise ValueError('CONFIG_ACTIVE_SOURCE')
        return active

    def units(self):
        expected = self.lifecycle.unit_files(self.source, pwd.getpwnam('www-data').pw_gid, self.release)
        for path, body in expected.items():
            if self.upgrade.read_file(path, mode=0o644) != body:
                raise ValueError('CONFIG_UNIT_CHANGED')

    def running(self, images):
        self.units()
        for unit in (self.lifecycle.TUNNEL, *self.lifecycle.UNITS):
            if self.lifecycle._state(self.release, unit, 'ActiveState') != 'active':
                raise ValueError('CONFIG_SERVICE_STATE')
        for unit in self.lifecycle.UNITS:
            if self.lifecycle._state(self.release, unit, 'UnitFileState') != 'enabled':
                raise ValueError('CONFIG_SERVICE_STATE')
        return self.lifecycle._snapshot(self.release, self.source, images)

    def legacy(self):
        if self.host.baseline() != BASELINE:
            raise ValueError('CONFIG_LEGACY_CHANGED')

    def logic_identity(self):
        fields = {'id': '.Id', 'image': '.Image', 'pid': '.State.Pid', 'running': '.State.Running',
                  'started': '.State.StartedAt', 'service': '(index .Config.Labels "com.docker.compose.service")'}
        fmt = '{' + ','.join(json.dumps(key) + ':{{json ' + value + '}}' for key, value in fields.items()) + '}'
        row = json.loads(self.release.command(['docker', 'inspect', '--format', fmt, 'logic-analysis']))
        if (not isinstance(row, dict) or set(row) != set(fields) or
                not re.fullmatch('[0-9a-f]{64}', row.get('id', '')) or
                not re.fullmatch('sha256:[0-9a-f]{64}', row.get('image', '')) or
                type(row.get('pid')) is not int or row['pid'] <= 0 or row['running'] is not True or
                row.get('service') != 'logic-analysis' or not isinstance(row.get('started'), str) or not row['started']):
            raise ValueError('CONFIG_KEY_SOURCE_IDENTITY')
        return row

    def key(self):
        before = self.logic_identity()
        proc = os.open('/proc', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        process = environment = None
        try:
            process = os.open(str(before['pid']), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=proc)
            environment = os.open('environ', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=process)
            body = os.read(environment, 131073)
            if len(body) > 131072:
                raise ValueError('CONFIG_KEY_SOURCE_POLICY')
            found = {}
            for item in body.split(b'\x00'):
                name, separator, value = item.partition(b'=')
                if separator and name in (b'ANTHROPIC_API_KEY', b'CLAUDE_API_KEY'):
                    if name in found:
                        raise ValueError('CONFIG_KEY_SOURCE_POLICY')
                    found[name] = value
            key = found.get(b'ANTHROPIC_API_KEY') or found.get(b'CLAUDE_API_KEY')
            if not isinstance(key, bytes) or not re.fullmatch(rb'[\x21-\x7e]{1,4096}', key):
                raise ValueError('CONFIG_KEY_SOURCE_POLICY')
            if self.logic_identity() != before:
                raise ValueError('CONFIG_KEY_SOURCE_CHANGED')
            return key
        finally:
            for fd in (environment, process, proc):
                if fd is not None:
                    os.close(fd)

    def factory_check(self, image, candidate=None, container=None):
        if candidate is not None:
            args = ['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                    '--security-opt', 'no-new-privileges:true', '--user', '10001:10001',
                    '--memory', '128m', '--cpus', '0.25', '--pids-limit', '32',
                    '--entrypoint', 'python', '--env-file', str(candidate), image,
                    '-I', '-S', '-B', '-c', FACTORY_PROGRAM]
        else:
            args = ['docker', 'exec', container, 'python', '-I', '-S', '-B', '-c', FACTORY_PROGRAM]
        if self.release.command(args, timeout=30) != b'{"configured":true,"unlimited":true}\n':
            raise ValueError('CONFIG_PROVIDER_FACTORY')

    def candidate_check(self, image):
        candidate = self.folder / 'new-0'
        args = ['env', 'NAVER_ENGINE_ENV_FILE=' + str(candidate), *self.release.compose(self.source, 'engine'), 'config', '--quiet']
        if self.release.command(args, timeout=30).strip():
            raise ValueError('CONFIG_COMPOSE_OUTPUT')
        self.factory_check(image, candidate=candidate)

    def stopped(self, name, image):
        unit = self.lifecycle.UNITS[0 if name == 'engine' else 1]
        if (self.lifecycle._state(self.release, unit, 'ActiveState') not in ('inactive', 'failed') or
                self.lifecycle._state(self.release, unit, 'SubState') not in ('dead', 'failed') or
                self.lifecycle._state(self.release, unit, 'MainPID') != '0'):
            raise ValueError('CONFIG_WRITER_NOT_STOPPED')
        ids = self.release.command(['docker', 'ps', '--all', '--no-trunc', '--filter',
                                    'label=com.docker.compose.project=naver-' + name, '--format', '{{.ID}}']).decode().strip().splitlines()
        if len(ids) != 1 or not re.fullmatch('[0-9a-f]{64}', ids[0]):
            raise ValueError('CONFIG_WRITER_NOT_STOPPED')
        fields = {'id': '.Id', 'image': '.Image', 'running': '.State.Running', 'restarting': '.State.Restarting',
                  'pid': '.State.Pid', 'project': '(index .Config.Labels "com.docker.compose.project")',
                  'service': '(index .Config.Labels "com.docker.compose.service")'}
        fmt = '{' + ','.join(json.dumps(key) + ':{{json ' + value + '}}' for key, value in fields.items()) + '}'
        row = json.loads(self.release.command(['docker', 'inspect', '--format', fmt, ids[0]]))
        if row != {'id': ids[0], 'image': image, 'running': False, 'restarting': False, 'pid': 0,
                   'project': 'naver-' + name, 'service': 'naver-' + name}:
            raise ValueError('CONFIG_WRITER_NOT_STOPPED')

    def stop(self, images):
        for name, unit in (('relay', self.lifecycle.UNITS[1]), ('engine', self.lifecycle.UNITS[0])):
            self.release.command(['/usr/bin/systemctl', 'stop', unit], timeout=90)
            self.stopped(name, images[name])

    def start(self, images, previous, configured):
        self.release.command(self.release.compose(self.source, 'engine') +
                             ['up', '--no-start', '--no-build', '--no-deps', '--pull', 'never',
                              '--force-recreate', 'naver-engine'], timeout=90)
        for unit in self.lifecycle.UNITS:
            self.release.command(['/usr/bin/systemctl', 'start', unit], timeout=90)
        deadline = time.monotonic() + 45
        while True:
            try:
                after = self.running(images)
                if after['engine']['id'] == previous['engine']['id'] or after['relay']['id'] != previous['relay']['id']:
                    raise ValueError('CONFIG_CONTAINER_SCOPE')
                status, _, body = self.release.unix_request('/run/metainc/naver-engine/engine.sock', '/_engine/health')
                if status != 200 or not isinstance(json.loads(body), dict):
                    raise ValueError('CONFIG_HEALTH')
                if self.release.unix_request('/run/metainc/naver-relay/relay.sock', '/api/naver-auto/me')[0] != 401:
                    raise ValueError('CONFIG_AUTH_CHANGED')
                if configured:
                    self.factory_check(images['engine'], container=after['engine']['id'])
                self.legacy()
                return after
            except (OSError, ValueError, RuntimeError):
                if time.monotonic() >= deadline:
                    raise ValueError('CONFIG_START_NOT_READY') from None
                time.sleep(1)

    def load_journal(self):
        self.release.trusted_dir(self.folder, mode=0o700)
        journal = json.loads(self.read(self.folder / 'journal.json'), object_pairs_hook=self.release.unique)
        if (not isinstance(journal, dict) or set(journal) != {'schema', 'operation_id', 'source_commit', 'rollback_commit',
                'baseline', 'state', 'files', 'images', 'before'} or journal['schema'] != 1 or
                journal['operation_id'] != self.request['operation_id'] or journal['source_commit'] != SOURCE_COMMIT or
                journal['rollback_commit'] != ROLLBACK_COMMIT or journal['baseline'] != BASELINE or
                journal['state'] not in TERMINAL | {'preparing', 'prepared', 'stopped', 'replaced', 'recovering'} or
                not isinstance(journal['files'], list) or len(journal['files']) != 3 or
                not isinstance(journal['images'], dict) or set(journal['images']) != {'engine', 'relay'} or
                any(not isinstance(value, str) or not re.fullmatch('sha256:[0-9a-f]{64}', value)
                    for value in journal['images'].values()) or
                not isinstance(journal['before'], dict) or set(journal['before']) != {'engine', 'relay'}):
            raise ValueError('CONFIG_JOURNAL')
        for index, (row, path) in enumerate(zip(journal['files'], self.paths)):
            if (not isinstance(row, dict) or set(row) != {'path', 'old', 'new'} or row['path'] != str(path) or
                    any(not isinstance(row[name], str) or not re.fullmatch('[0-9a-f]{64}', row[name]) for name in ('old', 'new')) or
                    journal['state'] not in ('preparing', 'rejected') and
                    (row['old'] != digest(self.read(self.folder / ('old-' + str(index)))) or
                     row['new'] != digest(self.read(self.folder / ('new-' + str(index)))))):
                raise ValueError('CONFIG_BACKUP_CHANGED')
        for name, row in journal['before'].items():
            if (not isinstance(row, dict) or set(row) != {'id', 'image', 'running', 'started', 'restarts', 'project', 'service'} or
                    not isinstance(row['id'], str) or not re.fullmatch('[0-9a-f]{64}', row['id']) or
                    row['image'] != journal['images'][name] or row['running'] is not True or
                    type(row['restarts']) is not int or row['restarts'] != 0 or
                    not isinstance(row['started'], str) or not row['started'] or
                    row['project'] != 'naver-' + name or row['service'] != 'naver-' + name):
                raise ValueError('CONFIG_JOURNAL')
        self.journal = journal
        return journal

    def existing_transactions(self):
        if not os.path.lexists(self.root):
            self.release.trusted_dir(self.root, mode=0o700, new=True)
            self.sync_dir(self.root.parent)
        self.release.trusted_dir(self.root, mode=0o700)
        entries = list(self.root.iterdir())
        if len(entries) > 32:
            raise ValueError('CONFIG_HISTORY_BOUND')
        for folder in entries:
            if not re.fullmatch('[0-9a-f]{32}', folder.name):
                raise ValueError('CONFIG_HISTORY_POLICY')
            self.release.trusted_dir(folder, mode=0o700)
            if folder == self.folder and self.request['operation'] == 'recover':
                continue
            journal = json.loads(self.read(folder / 'journal.json'), object_pairs_hook=self.release.unique)
            if folder != self.folder and journal.get('state') not in {'recovered', 'rejected'}:
                raise ValueError('CONFIG_OTHER_TRANSACTION')

    def reject_unstarted(self):
        """Recover only the mkdir/initial-journal crash window; no active mutation."""
        self.release.trusted_dir(self.folder, mode=0o700)
        entries = {path.name for path in self.folder.iterdir()}
        if entries - {'journal.json'}:
            return False
        if 'journal.json' in entries:
            body = self.read(self.folder / 'journal.json', minimum=0)
            try:
                json.loads(body, object_pairs_hook=self.release.unique)
                return False
            except (ValueError, UnicodeError):
                pass
        self.legacy()
        active = self.manifests()
        before = self.running(active['images'])
        bodies = [self.read(path) for path in self.paths]
        if any(line.split(b'=', 1)[0] in {name.encode() for name in ALLOWED}
               for line in bodies[0].splitlines()):
            raise ValueError('CONFIG_UNSTARTED_STATE')
        self.journal = dict(schema=1, operation_id=self.request['operation_id'], source_commit=SOURCE_COMMIT,
                            rollback_commit=ROLLBACK_COMMIT, baseline=BASELINE, state='rejected',
                            files=[dict(path=str(path), old=digest(bodies[index]), new=digest(bodies[index]))
                                   for index, path in enumerate(self.paths)], images=active['images'], before=before)
        self.save('rejected')
        return True

    def prepare(self):
        global STAGE
        STAGE = 'preflight'
        self.legacy()
        active = self.manifests()
        before = self.running(active['images'])
        old = [self.read(path) for path in self.paths]
        candidate = candidate_env(old[0], self.key())
        new = [candidate]
        for body in old[1:]:
            receipt = json.loads(body, object_pairs_hook=self.release.unique)
            receipt['files'][str(self.env)] = digest(candidate)
            new.append(json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode())
        self.release.trusted_dir(self.folder, mode=0o700, new=True)
        self.sync_dir(self.root)
        self.journal = dict(schema=1, operation_id=self.request['operation_id'], source_commit=SOURCE_COMMIT,
                            rollback_commit=ROLLBACK_COMMIT, baseline=BASELINE, state='preparing',
                            files=[dict(path=str(path), old=digest(old[index]), new=digest(new[index]))
                                   for index, path in enumerate(self.paths)], images=active['images'], before=before)
        self.save('preparing')
        for index in range(3):
            self.new(self.folder / ('old-' + str(index)), old[index])
            self.new(self.folder / ('new-' + str(index)), new[index])
        self.save('prepared')
        STAGE = 'candidate'
        try:
            self.candidate_check(active['images']['engine'])
        except Exception:
            self.save('rejected')
            raise ValueError('CONFIG_CANDIDATE_REJECTED') from None
        self.legacy()
        self.manifests()
        if self.running(active['images']) != before or any(self.read(path) != old[index] for index, path in enumerate(self.paths)):
            self.save('rejected')
            raise ValueError('CONFIG_PREFLIGHT_DRIFT')

    def recover(self):
        global STAGE
        STAGE = 'recovery_preflight'
        if self.reject_unstarted():
            return self.result('recovered')
        self.load_journal()
        self.legacy()
        self.units()
        if self.journal['state'] in ('preparing', 'rejected'):
            if any(digest(self.read(path)) != self.journal['files'][index]['old'] for index, path in enumerate(self.paths)):
                raise ValueError('CONFIG_RECOVERY_DRIFT')
            self.manifests()
            self.running(self.journal['images'])
            self.save('rejected')
            return self.result('recovered')
        for index, path in enumerate(self.paths):
            if digest(self.read(path)) not in (self.journal['files'][index]['old'], self.journal['files'][index]['new']):
                raise ValueError('CONFIG_RECOVERY_DRIFT')
        if self.journal['state'] in ('recovered', 'rejected'):
            if any(digest(self.read(path)) != self.journal['files'][index]['old'] for index, path in enumerate(self.paths)):
                raise ValueError('CONFIG_RECOVERY_DRIFT')
            self.manifests()
            self.running(self.journal['images'])
            return self.result('recovered')
        self.save('recovering')
        self.stop(self.journal['images'])
        STAGE = 'recovery_restore'
        for index, path in enumerate(self.paths):
            body = self.read(self.folder / ('old-' + str(index)))
            current = self.read(path)
            if current != body:
                self.replace(path, body, current)
        self.manifests()
        self.start(self.journal['images'], self.journal['before'], False)
        self.save('recovered')
        return self.result('recovered')

    def result(self, state):
        return dict(ok=True, state=state, operation_id=self.request['operation_id'], source_commit=SOURCE_COMMIT,
                    rollback_commit=ROLLBACK_COMMIT, model=MODEL, monthly_limit='unlimited' if state == 'committed' else 'restored',
                    server_local_key_reuse=state == 'committed', paid_api_calls=0,
                    database_opened_by_controller=False, legacy_services_changed=False,
                    code_rollback_requires_config_recovery=True)

    def activate(self):
        global STAGE
        if os.path.lexists(self.folder):
            self.load_journal()
            if self.journal['state'] == 'committed':
                if any(digest(self.read(path)) != self.journal['files'][index]['new'] for index, path in enumerate(self.paths)):
                    raise ValueError('CONFIG_COMMITTED_DRIFT')
                self.legacy()
                active = self.manifests()
                current = self.running(active['images'])
                self.factory_check(active['images']['engine'], container=current['engine']['id'])
                return self.result('committed')
            raise ValueError('CONFIG_RECOVERY_REQUIRED')
        self.prepare()
        try:
            STAGE = 'stop'
            self.stop(self.journal['images'])
            self.save('stopped')
            STAGE = 'replace'
            for index, path in enumerate(self.paths):
                self.replace(path, self.read(self.folder / ('new-' + str(index))), self.read(self.folder / ('old-' + str(index))))
            self.save('replaced')
            self.manifests()
            STAGE = 'start'
            self.start(self.journal['images'], self.journal['before'], True)
            self.save('committed')
            return self.result('committed')
        except Exception:
            try:
                self.recover()
            except Exception:
                raise RuntimeError('CONFIG_FAILED_RECOVERY_REQUIRED') from None
            raise RuntimeError('CONFIG_FAILED_RECOVERED') from None


def run(request, host, release, upgrade, lifecycle):
    global STAGE
    STAGE = 'input'
    validate_request(request)
    if os.geteuid() != 0:
        raise ValueError('CONFIG_ROOT_REQUIRED')
    lock = Path('/run/metainc-naver-claude-config.lock')
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink) != (0, 0, 0o600, 1):
            raise ValueError('CONFIG_LOCK_POLICY')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        transaction = Transaction(request, host, release, upgrade, lifecycle)
        transaction.existing_transactions()
        return transaction.activate() if request['operation'] == 'activate' else transaction.recover()
    finally:
        os.close(fd)
