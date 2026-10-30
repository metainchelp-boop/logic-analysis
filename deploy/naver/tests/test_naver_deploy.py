"""naver-deploy.sh 로컬 시험 — 서버·docker·systemd 없이 가짜 루트와 가짜 명령으로 돌린다.

실행: python3 -m unittest discover -s deploy/naver/tests -v
"""
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), 'naver-deploy.sh')
WORKFLOW = os.path.join(os.path.dirname(os.path.dirname(HERE)), '..', '.github', 'workflows', 'naver-deploy.yml')
RELEASES = '/srv/metainc/ad-deploy-staging/releases'
COMPANION = '/srv/metainc/ad-deploy-staging/saved-exports/' + 'a' * 32 + '/naver-saved-exports.override.yml'
C0 = 'c44a66300000000000000000000000000000c0c0'
C1 = 'abceeb7375480000000000000000000000000c1c'
C2 = '2222222222222222222222222222222222222222'
C3 = '3333333333333333333333333333333333333333'
C4 = '4444444444444444444444444444444444444444'
# 공개 출력·로그로 새면 안 되는 합성 비밀값(모든 시험의 가짜 서버에 심는다).
CANARY_RUNTIME = 'canary-runtime-secret-7f3a'
CANARY_UNIT = 'canary-unit-secret-91c2'
CANARY_TUNNEL = 'canary-tunnel-secret-3b77'
CANARY_OVERRIDE = 'canary-override-secret-5d10'
CANARY_LABEL = 'canary-label-secret-c0de'
CANARY_TMPFILES = 'canary-tmpfiles-secret-aa01'
CANARIES = (CANARY_RUNTIME, CANARY_UNIT, CANARY_TUNNEL, CANARY_OVERRIDE, CANARY_LABEL, CANARY_TMPFILES)
PRODUCTION_PATHS = ('/var/lib/metainc', '/run/metainc', '/var/backups', '/etc/metainc', 'naver-erp-tunnel',
                    'saved-exports')
MUTATING_DOCKER = ('build', 'tag', 'rmi', 'create', 'rm', 'run', 'stop', 'start', 'kill', 'cp')
MUTATING_SYSTEMCTL = ('start', 'stop', 'restart', 'daemon-reload', 'enable', 'disable', 'reload')


def unit_files(release, companion):
    """옛 실행기 naver_preview_lifecycle.unit_files 와 같은 모양(ExportProxy 로 engine 에 companion 추가)."""
    files = {}
    for number, name in enumerate(('engine', 'relay')):
        dependency = 'metainc-naver-erp-tunnel.service' if name == 'engine' else 'metainc-naver-engine.service'
        compose = ['/usr/bin/docker', 'compose', '--project-name', 'naver-' + name, '-f', release + '/compose.naver-' + name + '.yml']
        if name == 'engine':
            compose += ['-f', release + '/deploy/naver-engine-backup.override.yml']
        compose += ['-f', release + '/preview-' + name + '.override.yml']
        if name == 'engine' and companion:
            compose += ['-f', companion]
        start = ' '.join(compose + ['up', '--no-build', '--no-recreate', '--abort-on-container-exit',
                                    '--exit-code-from', 'naver-' + name, 'naver-' + name])
        stop = ' '.join(compose + ['stop', '--timeout', '45', 'naver-' + name])
        files['metainc-naver-' + name + '.service'] = (
            '[Unit]\nDescription=Naver isolated ' + name + ' supervisor\n'
            'Requires=docker.service ' + dependency + '\nAfter=docker.service ' + dependency +
            '\nAfter=systemd-tmpfiles-setup.service\nStartLimitIntervalSec=0\n\n'
            '[Service]\nType=exec\nUser=root\nGroup=root\nUMask=0077\n'
            'Environment=PATH=/usr/sbin:/usr/bin:/sbin:/bin\n'
            'ExecStartPre=/usr/bin/systemd-tmpfiles --create /etc/tmpfiles.d/metainc-naver-preview.conf\n'
            'Environment=NAVER_FAKE_UNIT_TOKEN=' + CANARY_UNIT + '\n'
            'ExecStart=' + start + '\nExecStop=' + stop + '\nRestart=always\nRestartSec=10s\n'
            'TimeoutStopSec=70s\nStandardOutput=null\nStandardError=null\n\n'
            '[Install]\nWantedBy=multi-user.target\n')
    return files


RUNTIME_ENV_BODY = ('NAVER_ENGINE_EXECUTION_ENABLED=false\nNAVER_ENGINE_INVENTORY_ENABLED=false\n'
                    'NAVER_AUTO_TOKEN_SECRET=' + CANARY_RUNTIME + '\n')
TUNNEL_UNIT_BODY = '[Service]\nEnvironment=TUNNEL_TOKEN=' + CANARY_TUNNEL + '\nExecStart=/usr/bin/ssh tunnel\n'


def source_files(commit, schema, extra=None):
    files = {
        '.dockerignore': '.git\n', 'Dockerfile.naver-engine': 'FROM python:3.12-slim\n',
        'Dockerfile.naver-engine.dockerignore': '**\n', 'Dockerfile.naver-relay': 'FROM python:3.12-slim\n',
        'Dockerfile.naver-relay.dockerignore': '**\n', 'compose.naver-engine.yml': 'name: naver-engine\n',
        'compose.naver-relay.yml': 'name: naver-relay\n', 'backend/requirements.txt': 'fastapi\n',
        'backend/app/__init__.py': '', 'backend/app/naver_entry.py': '# entry\n',
        'deploy/naver-engine-backup.override.yml': 'services: {}\n',
        'naver_engine/__init__.py': '', 'naver_engine/store.py': 'SCHEMA_VERSION = %d   # fake\n' % schema,
        'naver_runtime/__main__.py': '# %s\n' % commit, 'backend/naver_page/index.html': '<p>%s</p>\n' % commit}
    files.update(extra or {})
    return files


def make_tar(path, files):
    with tarfile.open(path, 'w') as archive:
        folders = set()
        for name in sorted(files):
            parts = name.split('/')[:-1]
            for i in range(1, len(parts) + 1):
                folder = '/'.join(parts[:i])
                if folder not in folders:
                    folders.add(folder)
                    info = tarfile.TarInfo(folder + '/')
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o775
                    archive.addfile(info)
            body = files[name].encode()
            info = tarfile.TarInfo(name)
            info.size = len(body)
            info.mode = 0o664
            archive.addfile(info, io.BytesIO(body))


class FakeHost:
    def __init__(self, base):
        self.base = base
        self.root = os.path.join(base, 'root')
        self.bin = os.path.join(base, 'bin')
        os.makedirs(self.bin)
        shutil.copy(os.path.join(HERE, 'fakehost.py'), self.bin)
        tools = ['docker', 'systemctl', 'curl', 'cp', 'sqlite3']
        if shutil.which('flock') is None:
            tools.append('flock')
        for tool in tools:
            path = os.path.join(self.bin, tool)
            with open(path, 'w') as handle:
                handle.write('#!%s\nimport sys\nsys.path.insert(0, %r)\nimport fakehost\nfakehost.main(%r)\n'
                             % (sys.executable, self.bin, tool))
            os.chmod(path, 0o755)
        self.config = {'root': self.root, 'extra_labels': {'vendor.secret': CANARY_LABEL}}
        self.write_config()
        self.state = {'images': {}, 'containers': {}, 'units': {}, 'seq': 100, 'clock': 0}
        self.build_host()

    def write_config(self):
        with open(os.path.join(self.bin, 'config.json'), 'w') as handle:
            json.dump(self.config, handle)

    def set(self, **values):
        self.config.update(values)
        self.write_config()

    def file(self, path, body, mode=0o644):
        full = self.root + path
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w') as handle:
            handle.write(body)
        os.chmod(full, mode)

    def read(self, path):
        with open(self.root + path) as handle:
            return handle.read()

    def build_host(self):
        release = RELEASES + '/naver-' + C0
        for name, body in source_files(C0, 21).items():
            self.file(release + '/' + name, body)
        self.file(release + '/preview-engine.override.yml',
                  'services:\n  naver-engine:\n    image: metainc/naver-engine:%s\n' % C0, 0o600)
        self.file(release + '/preview-relay.override.yml',
                  'services:\n  naver-relay:\n    image: metainc/naver-relay:%s\n    environment:\n      NAVER_AUTO_WEB: "on"\n'
                  '      NAVER_FAKE_OVERRIDE_TOKEN: "%s"\n' % (C0, CANARY_OVERRIDE), 0o600)
        self.file(COMPANION, '{"services":{"naver-engine":{}}}\n')
        units = unit_files(release, COMPANION)
        for name, body in units.items():
            self.file('/etc/systemd/system/' + name, body)
        self.file('/etc/systemd/system/metainc-naver-erp-tunnel.service', TUNNEL_UNIT_BODY)
        self.file('/etc/tmpfiles.d/metainc-naver-preview.conf',
                  'd /run/metainc 0755 root root -\nf /etc/fake 0600 root root - %s\n' % CANARY_TMPFILES)
        self.file('/etc/metainc/naver-engine/runtime.env', RUNTIME_ENV_BODY, 0o600)
        self.file('/etc/nginx/nginx.conf', 'user www-data;\n')
        self.file('/var/lib/metainc/naver-engine/engine.db', 'SQLite format 3\0' + 'x' * 4000, 0o640)
        self.file('/var/lib/metainc/naver-engine/engine.db-wal', 'wal' * 100, 0o640)
        os.makedirs(self.root + '/var/backups/metainc/naver-engine')
        os.makedirs(self.root + '/run/metainc/naver-engine')
        os.makedirs(self.root + '/run/metainc/naver-relay')
        images = {}
        for name in ('engine', 'relay'):
            identity = 'sha256:' + hashlib.sha256(('old-' + name).encode()).hexdigest()
            images[name] = identity
            self.state['images'][identity] = {'tags': ['metainc/naver-%s:%s' % (name, C0)], 'user': '10001:10001',
                                              'labels': {'metainc.naver.preview.source': C0}, 'schema': 21}
        unrelated = 'sha256:' + 'f' * 64
        self.state['images'][unrelated] = {'tags': ['metainc/naver-engine:local-review'], 'user': '10001:10001',
                                           'labels': {}, 'schema': 21}
        for name in ('engine', 'relay'):
            self.state['units']['metainc-naver-%s.service' % name] = {
                'active': 'inactive', 'pid': 0, 'enabled': 'enabled', 'loaded': units['metainc-naver-%s.service' % name]}
        self.state['units']['docker.service'] = {'active': 'active', 'pid': 1}
        self.state['units']['metainc-naver-erp-tunnel.service'] = {'active': 'active', 'pid': 2}
        self.old_images = images
        self.save_state()
        # 지금 운영처럼 두 서비스를 가짜 systemd 로 띄운다(컨테이너 env·mount 가 가짜 compose 설정과 같아진다).
        for name in ('engine', 'relay'):
            subprocess.run([os.path.join(self.bin, 'systemctl'), 'start', 'metainc-naver-%s.service' % name], check=True)
        self.clear_calls()

    def save_state(self):
        with open(os.path.join(self.bin, 'state.json'), 'w') as handle:
            json.dump(self.state, handle)

    def load_state(self):
        with open(os.path.join(self.bin, 'state.json')) as handle:
            return json.load(handle)

    def calls(self):
        path = os.path.join(self.bin, 'calls.log')
        if not os.path.exists(path):
            return []
        with open(path) as handle:
            return [json.loads(line) for line in handle]

    def clear_calls(self):
        path = os.path.join(self.bin, 'calls.log')
        if os.path.exists(path):
            os.unlink(path)

    def tar(self, commit, schema=21, extra=None):
        path = os.path.join(self.base, 'source-%s.tar' % commit[:8])
        make_tar(path, source_files(commit, schema, extra))
        return path

    def run(self, *args, **env):
        environment = {'PATH': self.bin + ':' + os.path.dirname(sys.executable) + ':/usr/bin:/bin:/usr/sbin:/sbin',
                       'HOME': self.base, 'TMPDIR': self.base,
                       'NAVER_DEPLOY_ROOT': self.root, 'NAVER_DEPLOY_HOLD_SECONDS': '1',
                       'NAVER_DEPLOY_READY_TIMEOUT': '2', 'NAVER_DEPLOY_STOP_TIMEOUT': '2',
                       'NAVER_DEPLOY_POLL': '0.05', 'NAVER_DEPLOY_HOLD_POLL': '0.2'}
        environment.update(env)
        return subprocess.run(['bash', SCRIPT] + list(args), env=environment, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=300)

    def deploy(self, commit, schema=21, extra=None):
        return self.run('deploy', commit, self.tar(commit, schema, extra))

    def deploy_logged(self, commit, schema=21, extra=None):
        """workflow 처럼 --log/--result 로 실행. (stdout, 서버 비공개 로그, 결과 줄, 명령 로그들) 을 돌려준다."""
        log, result = os.path.join(self.base, 'deploy.log'), os.path.join(self.base, 'result.json')
        done = self.run('deploy', commit, self.tar(commit, schema, extra), '--log', log, '--result', result)
        private = ''
        for folder, _, files in os.walk(self.root + '/var/lib/metainc/naver-deploy'):
            for name in files:
                if name.startswith('commands'):
                    with open(os.path.join(folder, name), errors='replace') as handle:
                        private += handle.read()
        return done, read_text(log), read_text(result), private

    def tree(self):
        result = {}
        for folder, children, files in os.walk(self.root):
            children.sort()
            for name in sorted(files) + sorted(children):
                full = os.path.join(folder, name)
                info = os.lstat(full)
                body = b''
                if stat.S_ISREG(info.st_mode):
                    with open(full, 'rb') as handle:
                        body = handle.read()
                result[os.path.relpath(full, self.root)] = (stat.S_IMODE(info.st_mode), hashlib.sha256(body).hexdigest())
        return result

    def running(self, project):
        state = self.load_state()
        rows = [c for c in state['containers'].values() if c.get('project') == project]
        assert len(rows) == 1, rows
        return rows[0]

    def tags(self):
        return {tag for image in self.load_state()['images'].values() for tag in image['tags']}

    def deploy_state(self):
        with open(self.root + '/var/lib/metainc/naver-deploy/state.json') as handle:
            return json.load(handle)


def read_text(path):
    if not os.path.exists(path):
        return ''
    with open(path, errors='replace') as handle:
        return handle.read()


def result_of(done):
    lines = [line for line in done.stdout.decode().splitlines() if line.startswith('NAVER_DEPLOY_RESULT=')]
    return json.loads(lines[-1].split('=', 1)[1]) if lines else {}


class DeployScriptTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='naver-deploy-test-')
        self.host = FakeHost(self.base)
        self.original_units = {name: self.host.read('/etc/systemd/system/' + name)
                               for name in ('metainc-naver-engine.service', 'metainc-naver-relay.service')}

    def tearDown(self):
        shutil.rmtree(self.base)

    def output(self, done):
        return done.stdout.decode('utf-8', 'replace')

    def assertExit(self, done, code):
        self.assertEqual(done.returncode, code, self.output(done)[-4000:])

    def index(self, calls, wanted, start=0):
        for number in range(start, len(calls)):
            if calls[number][:len(wanted)] == wanted:
                return number
        self.fail('call not found: %s' % wanted)

    def assert_previous_running(self):
        for name in ('engine', 'relay'):
            unit = 'metainc-naver-%s.service' % name
            self.assertEqual(self.host.read('/etc/systemd/system/' + unit), self.original_units[unit])
            container = self.host.running('naver-' + name)
            self.assertTrue(container['running'])
            self.assertEqual(container['image'], self.host.old_images[name])
            self.assertIn('metainc/naver-%s:%s' % (name, C0), self.host.tags())
        units = self.host.load_state()['units']
        self.assertEqual(units['metainc-naver-engine.service']['active'], 'active')
        self.assertEqual(units['metainc-naver-relay.service']['active'], 'active')

    def assert_untouched_secrets(self):
        self.assertEqual(self.host.read('/etc/metainc/naver-engine/runtime.env'), RUNTIME_ENV_BODY)
        self.assertEqual(self.host.read('/etc/nginx/nginx.conf'), 'user www-data;\n')
        self.assertEqual(self.host.read('/etc/systemd/system/metainc-naver-erp-tunnel.service'), TUNNEL_UNIT_BODY)
        self.assertEqual(self.host.read(COMPANION), '{"services":{"naver-engine":{}}}\n')
        self.assertFalse(any(call[0] == 'sqlite3' for call in self.host.calls()))
        self.assertEqual(self.host.read('/etc/tmpfiles.d/metainc-naver-preview.conf').count(CANARY_TMPFILES), 1)

    # ── 1. 정상 배포 ──
    def test_happy_deploy(self):
        db_before = self.host.read('/var/lib/metainc/naver-engine/engine.db')
        done = self.host.deploy(C1)
        self.assertExit(done, 0)
        result = result_of(done)
        self.assertEqual(result['status'], 'DEPLOYED')
        self.assertEqual(result['previous_commit'], C0)
        for canary in CANARIES:
            self.assertNotIn(canary, self.output(done))
        for name, count in (('engine', 6), ('relay', 4)):
            body = self.host.read('/etc/systemd/system/metainc-naver-%s.service' % name)
            self.assertEqual(body.count(C1), count)
            self.assertNotIn(C0, body)
            self.assertEqual(body, self.original_units['metainc-naver-%s.service' % name].replace(C0, C1))
            self.assertTrue(self.host.running('naver-' + name)['running'])
            self.assertEqual(self.host.running('naver-' + name)['restarts'], 0)
        self.assertIn(COMPANION, self.host.read('/etc/systemd/system/metainc-naver-engine.service'))
        release = RELEASES + '/naver-' + C1
        self.assertEqual(self.host.read(release + '/preview-engine.override.yml'),
                         'services:\n  naver-engine:\n    image: metainc/naver-engine:%s\n' % C1)
        self.assertIn('NAVER_AUTO_WEB: "on"', self.host.read(release + '/preview-relay.override.yml'))
        self.assertEqual(self.host.read('/var/lib/metainc/naver-engine/engine.db'), db_before)
        self.assertTrue(os.path.isdir(self.host.root + RELEASES + '/naver-' + C0), 'old release must stay')
        self.assertEqual(self.host.deploy_state()['phase'], 'done')
        self.assert_untouched_secrets()

        calls = self.host.calls()
        build = self.index(calls, ['docker', 'build'])
        stop_relay = self.index(calls, ['systemctl', 'stop', 'metainc-naver-relay.service'])
        stop_engine = self.index(calls, ['systemctl', 'stop', 'metainc-naver-engine.service'])
        copies = [n for n, c in enumerate(calls) if c[0] == 'cp' and any('engine.db' in a for a in c)]
        reload_ = self.index(calls, ['systemctl', 'daemon-reload'])
        create = self.index(calls, ['docker', 'compose'], reload_)
        start_engine = self.index(calls, ['systemctl', 'start', 'metainc-naver-engine.service'])
        start_relay = self.index(calls, ['systemctl', 'start', 'metainc-naver-relay.service'])
        self.assertTrue(build < stop_relay < stop_engine < min(copies) and max(copies) < reload_ < create
                        < start_engine < start_relay)
        self.assertEqual(len(copies), 2)  # engine.db, engine.db-wal
        backups = os.listdir(self.host.root + '/var/backups/metainc/naver-deploy-db')
        self.assertEqual(len(backups), 1)
        self.assertEqual(sorted(os.listdir(self.host.root + '/var/backups/metainc/naver-deploy-db/' + backups[0])),
                         ['engine.db', 'engine.db-wal'])
        # 라벨 없는 옛 이미지는 컨테이너를 시작하지 않고 store.py 만 복사해 스키마를 읽었다.
        self.index(calls, ['docker', 'create', '--network', 'none'])
        runs = [c for c in calls if c[:2] == ['docker', 'run']]
        self.assertEqual(len(runs), 1)  # check-config 전용 격리 컨테이너 하나

    # ── 2. 헬스 실패 → 자동 복원 ──
    def test_health_failure_restores_previous(self):
        self.host.set(health_fail=[C1])
        done = self.host.deploy(C1)
        self.assertExit(done, 2)
        self.assertEqual(result_of(done)['status'], 'DEPLOY_FAILED_RESTORED')
        self.assertIn('engine=503', self.output(done))
        self.assert_previous_running()
        self.assertEqual(self.host.deploy_state()['phase'], 'restored')
        self.assert_untouched_secrets()

    def test_crash_loop_during_hold_restores(self):
        self.host.set(flap=[C1])
        done = self.host.run('deploy', C1, self.host.tar(C1), NAVER_DEPLOY_HOLD_SECONDS='3')
        self.assertExit(done, 2)
        self.assertIn('재시작 감지', self.output(done))
        self.assert_previous_running()

    def test_restore_failure_stops_both(self):
        self.host.set(health_fail=[C1, C0])
        done = self.host.deploy(C1)
        self.assertExit(done, 4)
        self.assertEqual(result_of(done)['status'], 'RESTORE_FAILED')
        units = self.host.load_state()['units']
        self.assertEqual(units['metainc-naver-engine.service']['active'], 'inactive')
        self.assertEqual(units['metainc-naver-relay.service']['active'], 'inactive')
        self.assertEqual(self.host.deploy_state()['phase'], 'restore_failed')
        self.assertEqual(result_of(done)['services_stopped_confirmed'], 'true')
        # unit 파일과 이미지 태그는 직전 판으로 되돌려져 있다.
        for name, body in self.original_units.items():
            self.assertEqual(self.host.read('/etc/systemd/system/' + name), body)

    # ── 3. 시작 전 거부(아무것도 안 바뀜) ──
    def assert_refused_without_change(self, done, before, code=10):
        self.assertExit(done, code)
        calls = self.host.calls()
        self.assertFalse(any(c[0] == 'systemctl' and c[1] in MUTATING_SYSTEMCTL for c in calls), calls)
        self.assertFalse(any(c[:2] == ['docker', 'compose'] and 'up' in c for c in calls))
        for name, body in self.original_units.items():
            self.assertEqual(self.host.read('/etc/systemd/system/' + name), body)
        after = self.host.tree()
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)
                   and not k.startswith(('var/lib/metainc/naver-deploy', 'srv/metainc/ad-deploy-staging/releases/naver-'
                                         + C1))}
        self.assertEqual(changed, set())

    def test_schema_change_refused(self):
        before = self.host.tree()
        done = self.host.deploy(C1, schema=22)
        self.assert_refused_without_change(done, before)
        self.assertIn('SCHEMA_CHANGED', self.output(done))
        self.assertFalse(any(c[:2] == ['docker', 'build'] for c in self.host.calls()))

    def test_execution_enabled_refused(self):
        self.host.set(env_by_commit={C1: {'NAVER_ENGINE_EXECUTION_ENABLED': 'true'}})
        before = self.host.tree()
        done = self.host.deploy(C1)
        self.assert_refused_without_change(done, before)
        self.assertIn('EXECUTION_ENABLED', self.output(done))

    def test_unknown_layout_refused(self):
        path = '/etc/systemd/system/metainc-naver-engine.service'
        self.host.file(path, self.host.read(path).replace('--abort-on-container-exit ', ''))
        self.original_units['metainc-naver-engine.service'] = self.host.read(path)
        before = self.host.tree()
        done = self.host.deploy(C1)
        self.assert_refused_without_change(done, before)
        self.assertIn('LAYOUT', self.output(done))
        self.assertFalse(any(c[:2] == ['docker', 'build'] for c in self.host.calls()))

    def test_archive_out_of_scope_refused(self):
        before = self.host.tree()
        done = self.host.deploy(C1, extra={'backend/app/main.py': '# legacy app\n'})
        self.assert_refused_without_change(done, before)
        self.assertIn('ARCHIVE', self.output(done))

    def test_build_failure_refused_before_stop(self):
        self.host.set(build_fail='relay')
        before = self.host.tree()
        done = self.host.deploy(C1)
        self.assert_refused_without_change(done, before)
        self.assertEqual(self.host.deploy_state()['phase'], 'aborted_before_stop')

    # ── 4. inspect 는 읽기만 한다 ──
    def test_inspect_is_read_only(self):
        before = self.host.tree()
        done = self.host.run('inspect')
        self.assertExit(done, 0)
        after = self.host.tree()
        self.assertEqual(before, after)
        calls = self.host.calls()
        self.assertTrue(calls)
        for call in calls:
            tool, args = call[0], call[1:]
            self.assertNotIn(tool, ('cp', 'sqlite3', 'flock'), call)
            if tool == 'systemctl':
                self.assertIn(args[0], ('show', '--version'), call)  # systemctl cat(원문)도 쓰지 않는다
            if tool == 'docker':
                self.assertFalse(args[0] in MUTATING_DOCKER, call)
                if args[0] == 'compose':
                    self.assertEqual(args[1:], ['version', '--short'], call)
        lines = self.output(done).splitlines()
        self.assertEqual(len(lines), 1)
        report = json.loads(lines[0].split('NAVER_DEPLOY_INSPECT=', 1)[1])
        shape = report['unit_shapes']['engine']
        self.assertTrue(shape['shape_ok'])
        self.assertEqual(shape['commit'], C0)
        self.assertEqual(shape['companion'], COMPANION)
        self.assertEqual(shape['commit_count'], 6)
        self.assertEqual(shape['environment_lines'], 2)
        self.assertEqual(report['current_release']['schema_version'], 21)
        self.assertEqual(report['current_release']['overrides']['relay']['image'], 'metainc/naver-relay:' + C0)
        self.assertIn('services.naver-relay.environment.NAVER_FAKE_OVERRIDE_TOKEN',
                      report['current_release']['overrides']['relay']['keys'])  # 이름만, 값은 없음
        self.assertEqual(report['tmpfiles_conf'], {'readable': True, 'other_lines': 1,
                                                   'directories': [['/run/metainc', '0755', 'root', 'root']]})
        self.assertIn('engine.db', [e['name'] for e in report['data_dir']['entries']])
        engine = report['containers']['naver-engine'][0]
        self.assertIn('execution=false', engine['switches'])
        self.assertEqual(engine['labels']['other_label_count'], 1)
        self.assertEqual(report['units']['metainc-naver-erp-tunnel.service']['ActiveState'], 'active')
        for key in ('units', 'tmpfiles_conf', 'releases', 'images', 'disk', 'id', 'tools', 'deploy_state'):
            self.assertIn(key, report)

    # ── 1(P1). 공개 출력에 원문·비밀값이 섞이지 않는다 ──
    def test_inspect_prints_no_raw_text_or_canary(self):
        done = self.host.run('inspect')
        self.assertExit(done, 0)
        out = self.output(done)
        for canary in CANARIES:
            self.assertNotIn(canary, out)
        for raw in ('Environment=', 'ExecStart=', 'NAVER_AUTO_WEB: "on"', 'TUNNEL_TOKEN', 'vendor.secret'):
            self.assertNotIn(raw, out)

    def assert_no_canary(self, *texts):
        for text in texts:
            for canary in CANARIES:
                self.assertNotIn(canary, text)

    def test_deploy_outputs_and_private_logs_have_no_canary(self):
        done, log, result, private = self.host.deploy_logged(C1)
        self.assertExit(done, 0)
        self.assertEqual(self.output(done), '')  # --log 일 때 표준출력은 비어 있다
        self.assertEqual(json.loads(result)['status'], 'DEPLOYED')
        calls = read_text(os.path.join(self.host.bin, 'calls.log'))
        self.assert_no_canary(log, result, private, calls)

    # ── 2(P1). 빌드·compose 원문 stderr 는 비공개 명령 로그에만 ──
    def test_build_stderr_stays_private(self):
        canary = 'canary-private-build-stderr-1234'
        self.host.set(build_fail='engine', build_stderr=canary)
        done, log, result, private = self.host.deploy_logged(C1)
        self.assertExit(done, 10)
        self.assertEqual(json.loads(result)['reason'], 'BUILD_FAILED')
        self.assertIn(canary, private)
        for public in (self.output(done), result, log):
            self.assertNotIn(canary, public)

    def test_compose_and_check_stderr_stay_private(self):
        canaries = ('canary-compose-stderr-5678', 'canary-check-stderr-9abc')
        self.host.set(compose_stderr=canaries[0], check_stderr=canaries[1])
        done, log, result, private = self.host.deploy_logged(C1)
        self.assertExit(done, 0)
        for canary in canaries:
            self.assertIn(canary, private)
            for public in (self.output(done), result, log):
                self.assertNotIn(canary, public)

    def test_result_line_is_fixed_format(self):
        done = self.host.deploy(C1, schema=22)
        result = result_of(done)
        self.assertEqual(set(result), {
            'database_opened_by_deploy', 'db_backup', 'downtime_seconds', 'exit_code', 'health_codes', 'health_status',
            'message', 'mode', 'new_commit', 'new_engine_image', 'new_relay_image', 'phase', 'previous_commit',
            'previous_engine_image', 'previous_relay_image', 'reason', 'runtime_env_changed_by_deploy',
            'schema_current', 'schema_new', 'services_stopped_confirmed', 'switches', 'status', 'warnings'})
        self.assertEqual((result['reason'], result['schema_current'], result['schema_new']), ('SCHEMA_CHANGED', '21', '22'))
        self.assertEqual(result['message'], '시작 전 거부. 서비스는 그대로')

    # ── 3(P1). check-config 컨테이너에는 운영 mount 가 없다 ──
    def test_check_config_container_has_no_production_mounts(self):
        done = self.host.deploy(C1)
        self.assertExit(done, 0)
        runs = [c for c in self.host.calls() if c[:2] == ['docker', 'run']]
        self.assertEqual(len(runs), 1)
        args = runs[0][2:]
        for flag in ('-v', '--volume', '--mount', '--volumes-from', '--env-file', '--privileged'):
            self.assertNotIn(flag, args)
        joined = ' '.join(args)
        for path in PRODUCTION_PATHS:
            self.assertNotIn(path, joined)
        for pair in (['--network', 'none'], ['--user', '10001:10001'], ['--cap-drop', 'ALL']):
            self.assertIn(pair, [args[i:i + 2] for i in range(len(args) - 1)])
        self.assertIn('--read-only', args)
        tmpfs = [args[i + 1] for i, a in enumerate(args) if a == '--tmpfs']
        self.assertEqual([t.split(':')[0] for t in tmpfs], ['/tmp', '/var/lib/naver-engine'])
        env_names = [args[i + 1] for i, a in enumerate(args) if a == '-e']
        self.assertIn('NAVER_AUTO_TOKEN_SECRET', env_names)  # 이름만 넘기고 값은 명령줄에 없다
        self.assertTrue(all('=' not in name for name in env_names))
        self.assertNotIn(CANARY_RUNTIME, joined)
        self.assertEqual(args[-5:], ['python', '-B', '-m', 'naver_runtime', 'check-config'])
        self.assertRegex(args[-6], r'^sha256:[0-9a-f]{64}$')

    # ── 4(P1). 관제 설정 묶음(mount·user·restart·서비스 목록)이 바뀌면 멈추기 전에 거부 ──
    def test_compose_shape_changes_refused(self):
        for change in ('data_source', 'restart', 'extra_service'):
            with self.subTest(change=change):
                self.host.set(shape_change={C1: change})
                self.host.clear_calls()
                before = self.host.tree()
                done = self.host.deploy(C1)
                self.assert_refused_without_change(done, before)
                self.assertEqual(result_of(done)['reason'], 'CONFIG_SHAPE_CHANGED')
        self.host.set(shape_change={})
        self.assertExit(self.host.deploy(C1), 0)

    # ── 5(P2). 유효 스위치 보존: 현재 false 인 inventory 가 새 판에서 true 가 되면 거부 ──
    def test_runtime_flag_change_refused(self):
        self.host.set(env_by_commit={C1: {'NAVER_ENGINE_INVENTORY_ENABLED': 'true'}})
        before = self.host.tree()
        done = self.host.deploy(C1)
        self.assert_refused_without_change(done, before)
        result = result_of(done)
        self.assertEqual(result['reason'], 'FLAGS_CHANGED')
        self.assertIn('inventory=false', result['switches'])

    def test_switches_recorded_and_kept_after_restore(self):
        self.host.set(health_fail=[C1])
        done = self.host.deploy(C1)
        self.assertExit(done, 2)
        self.assertIn('inventory=false', self.host.deploy_state()['switches'])
        env = self.host.running('naver-engine')['env']
        self.assertIn('NAVER_ENGINE_INVENTORY_ENABLED=false', env)

    # ── 6. 복원 실패 시 정지가 실제로 확인됐는지 따로 보고 ──
    def test_restore_failure_reports_unconfirmed_stop(self):
        self.host.set(stop_noop=['metainc-naver-relay.service'])
        done = self.host.deploy(C1)
        self.assertExit(done, 4)
        result = result_of(done)
        self.assertEqual((result['status'], result['services_stopped_confirmed']), ('RESTORE_FAILED', 'false'))
        self.assertEqual(self.host.deploy_state()['stopped_confirmed'], 'false')

    # ── 5. 동시 실행 방지 ──
    def test_lock_conflict(self):
        folder = self.host.root + '/var/lib/metainc/naver-deploy'
        os.makedirs(folder)
        with open(folder + '/lock', 'a') as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            before = self.host.tree()
            done = self.host.deploy(C1)
        self.assertExit(done, 11)
        self.assertEqual(result_of(done)['status'], 'LOCKED')
        outside = lambda tree: {k: v for k, v in tree.items() if not k.startswith('var/lib/metainc/naver-deploy')}
        self.assertEqual(outside(before), outside(self.host.tree()))
        self.assertFalse(os.path.exists(folder + '/state.json'))
        self.assertFalse(any(c[0] in ('docker', 'systemctl') for c in self.host.calls()))

    # ── 6. 중단된 실행(SSH 끊김·재부팅 대역) → 다음 실행이 기록으로 복원 ──
    def test_interrupted_run_recovered_from_state(self):
        self.host.set(kill_after='start metainc-naver-engine.service')
        done = self.host.deploy(C1)
        self.assertEqual(done.returncode, -9, self.output(done)[-3000:])
        self.assertEqual(self.host.deploy_state()['phase'], 'starting')
        self.assertIn(C1, self.host.read('/etc/systemd/system/metainc-naver-engine.service'))
        self.host.set(kill_after=None)
        self.host.clear_calls()
        done = self.host.deploy(C2)
        self.assertExit(done, 3)
        self.assertEqual(result_of(done)['status'], 'RECOVERED_INTERRUPTED_RUN')
        self.assert_previous_running()
        self.assertEqual(self.host.deploy_state()['phase'], 'restored')
        self.assertFalse(any(c[:2] == ['docker', 'build'] for c in self.host.calls()))
        # 복원 뒤 다시 실행하면 정상 배포된다.
        done = self.host.deploy(C2)
        self.assertExit(done, 0)
        self.assertIn(C2, self.host.read('/etc/systemd/system/metainc-naver-relay.service'))

    # ── 7. 이미지 정리: 최근 3개·현재·직전은 남긴다 ──
    def test_old_tags_pruned_keep_three(self):
        for commit in (C1, C2, C3, C4):
            done = self.host.deploy(commit)
            self.assertExit(done, 0)
        tags = self.host.tags()
        for commit in (C2, C3, C4):
            self.assertIn('metainc/naver-engine:' + commit, tags)
            self.assertIn('metainc/naver-relay:' + commit, tags)
        for commit in (C0, C1):
            self.assertNotIn('metainc/naver-engine:' + commit, tags)
        self.assertIn('metainc/naver-engine:local-review', tags)  # 이 장치 기록에 없는 태그는 안 건드린다
        # 두 번째 배포부터는 이미지 라벨로 스키마를 읽는다(create 없음).
        self.assertEqual(sum(1 for c in self.host.calls() if c[:2] == ['docker', 'create']), 1)
        backups = os.listdir(self.host.root + '/var/backups/metainc/naver-deploy-db')
        self.assertEqual(len(backups), 3)

    def test_existing_identical_release_dir_is_reused(self):
        release = self.host.root + RELEASES + '/naver-' + C1
        os.makedirs(release)
        for name, body in source_files(C1, 21).items():
            self.host.file(RELEASES + '/naver-' + C1 + '/' + name, body)
        self.host.file(RELEASES + '/naver-' + C1 + '/naver_engine/tests/test_x.py', '# old executor kept tests\n')
        done = self.host.deploy(C1)
        self.assertExit(done, 0)
        self.assertIn('기존 release 폴더 재사용', self.output(done))

    def test_existing_different_release_dir_refused(self):
        self.host.file(RELEASES + '/naver-' + C1 + '/naver_engine/store.py', 'SCHEMA_VERSION = 21  # other\n')
        before = self.host.tree()
        done = self.host.deploy(C1)
        self.assert_refused_without_change(done, before)
        self.assertIn('RELEASE_DIR_DIFFERS', self.output(done))


class WorkflowConsistencyTest(unittest.TestCase):
    def test_workflow_archive_scope_matches_script(self):
        with open(SCRIPT) as handle:
            script = handle.read()
        exact = set(re.findall(r"'([^']+)'", re.search(r'EXACT = \{(.*?)\}', script, re.S).group(1)))
        prefixes = re.findall(r"'([^']+)'", re.search(r'PREFIXES = \((.*?)\)', script, re.S).group(1))
        with open(os.path.join(os.path.dirname(HERE), 'make-source-archive.sh')) as handle:
            archive = handle.read()
        block = re.search(r'# archive-paths-begin\n(.*?)# archive-paths-end', archive, re.S).group(1)
        listed = re.findall(r"^\s+(\S+) \\$", block, re.M)
        included = {item for item in listed if not item.startswith("':")}
        self.assertEqual(included, exact | {p.rstrip('/') for p in prefixes})

    def test_workflow_guards(self):
        with open(os.path.normpath(WORKFLOW)) as handle:
            workflow = handle.read()
        self.assertIn('group: deploy-logic-analysis', workflow)
        self.assertIn('cancel-in-progress: false', workflow)
        triggers = re.search(r'^on:\n((?:  .*\n|\n)*?)^\S', workflow, re.M).group(1)
        self.assertEqual(re.findall(r'^  (\w+):', triggers, re.M), ['workflow_dispatch'])
        for pin in ('actions/checkout@11d5960a326750d5838078e36cf38b85af677262',
                    'actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065',
                    'appleboy/ssh-action@029f5b4aeeeb58fdfe1410a5d17f967dacf36262',
                    'appleboy/scp-action@917f8b81dfc1ccd331fef9e2d61bdc6c8be94634'):
            self.assertIn(pin, workflow)
        for line in workflow.splitlines():
            if 'uses:' in line:
                self.assertRegex(line, r'@[0-9a-f]{40}\b', line)

    def test_workflow_publishes_only_fixed_summaries(self):
        with open(os.path.normpath(WORKFLOW)) as handle:
            workflow = handle.read()
        # 비공개 제품 빌드·설치 원문은 러너 비공개 파일로만 간다.
        build = workflow[workflow.index('docker build --quiet'):]
        build = build[:build.index('|| rc=$?')]
        self.assertIn('> "$RUNNER_TEMP/private/build-$name.log" 2>&1', build)
        self.assertIn('"$@" > "$RUNNER_TEMP/private/$name.log" 2>&1', workflow)
        for command in ('python -m pip install', 'npm install', 'playwright" install'):
            line = [l for l in workflow.splitlines() if command in l][0]
            self.assertTrue(line.strip().startswith('step '), line)
        self.assertIn('product-tests.sh" 2> "$RUNNER_TEMP/private/product-tests.stderr"', workflow)
        # 서버 단계: 서버 로그 원문을 흘리지 않고 결과 한 줄·단계 이름만 낸다.
        ssh = workflow[workflow.index('appleboy/ssh-action'):]
        for forbidden in ('sed -n', 'tail ', 'cat "$work/deploy.log"', 'wc -l < "$work/deploy.log"'):
            self.assertNotIn(forbidden, ssh)
        self.assertIn('out=$(bash "$incoming/naver-deploy.sh" inspect 2>/dev/null)', ssh)
        self.assertIn("grep '^NAVER_DEPLOY_INSPECT={'", ssh)
        self.assertIn("printf 'NAVER_DEPLOY_RESULT=%s\\n' \"$line\"", ssh)
        with open(os.path.join(os.path.dirname(HERE), 'product-tests.sh')) as handle:
            product = handle.read()
        self.assertNotIn("grep -E '^(FAIL|ERROR): ' \"$output_dir/$label.txt\" | head", product)

    def test_deploy_paths_ignored_by_logic_analysis_deploy(self):
        path = os.path.normpath(os.path.join(os.path.dirname(WORKFLOW), 'deploy.yml'))
        with open(path) as handle:
            body = handle.read()
        self.assertIn("- '.github/workflows/naver-deploy.yml'", body)
        self.assertIn("- 'deploy/naver/**'", body)
        # 이 커밋은 deploy.yml 자신도 바꾸므로, 자신도 무시 목록에 있어야 머지가 재배포를 일으키지 않는다.
        self.assertIn("- '.github/workflows/deploy.yml'", body)


if __name__ == '__main__':
    unittest.main()
