"""가짜 서버 명령(docker·systemctl·curl·cp·sqlite3·flock) — naver-deploy.sh 로컬 시험 전용.

시험이 만든 bin 폴더에 이 파일과 얇은 실행 파일들이 복사된다. 모든 호출은 calls.log 에 남고,
상태는 같은 폴더의 state.json, 시험 스위치는 config.json 에 있다(환경 변수를 쓰지 않는다:
배포 스크립트가 docker 를 env -i 로 부르기 때문).
"""
import fcntl
import hashlib
import io
import json
import os
import re
import signal
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, 'state.json')
CONFIG = os.path.join(HERE, 'config.json')
LOG = os.path.join(HERE, 'calls.log')
UNIT_DIR = '/etc/systemd/system'


def load(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as handle:
        return json.load(handle)


def save(state):
    with open(STATE + '.tmp', 'w') as handle:
        json.dump(state, handle, indent=1, sort_keys=True)
    os.replace(STATE + '.tmp', STATE)


def record(tool, args):
    with open(LOG, 'a') as handle:
        handle.write(json.dumps([tool] + list(args)) + '\n')


def config():
    return load(CONFIG, {})


def tick(state):
    state['clock'] = state.get('clock', 0) + 1
    return '2026-10-30T00:00:%02d.%06dZ' % (state['clock'] % 60, state['clock'])


def new_id(state, kind):
    state['seq'] = state.get('seq', 0) + 1
    return 'sha256:' + hashlib.sha256(('%s-%d' % (kind, state['seq'])).encode()).hexdigest() if kind == 'image' \
        else hashlib.sha256(('%s-%d' % (kind, state['seq'])).encode()).hexdigest()


def resolve_image(state, ref):
    if ref in state['images']:
        return ref
    for identity, image in state['images'].items():
        if ref in image['tags']:
            return identity
    return None


def image_commit(state, identity):
    image = state['images'].get(identity) or {}
    return (image.get('labels') or {}).get('metainc.naver.preview.source')


def override_image(path):
    with open(path) as handle:
        found = re.findall(r'(?m)^\s+image:\s*(\S+)\s*$', handle.read())
    return found[-1] if found else None


def project_container(state, project):
    for identity, container in state['containers'].items():
        if container.get('project') == project:
            return identity
    return None


def release_commit(files):
    for path in files:
        match = re.search(r'/releases/naver-([0-9a-f]{40})/', path)
        if match:
            return match.group(1)
    return None


def effective_env(commit, files=()):
    """compose 가 만드는 유효 environment 의 대역: runtime.env + compose environment + 시험용 덮어쓰기."""
    env = {}
    path = config()['root'] + '/etc/metainc/naver-engine/runtime.env'
    if os.path.exists(path):
        with open(path) as handle:
            for line in handle:
                line = line.rstrip('\n')
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    env[key] = value
    env.update({'TZ': 'Asia/Seoul', 'NAVER_ENGINE_DB': '/var/lib/naver-engine/engine.db',
                'NAVER_ENGINE_SOCKET': '/run/naver-engine/engine.sock'})
    if any('naver-saved-exports' in f for f in files):
        env['NAVER_ENGINE_PRODUCT_EXPORT_FILE'] = '/var/lib/naver-product-source/bundle.json'
    env.update((config().get('env_by_commit') or {}).get(commit or '', {}))
    return env


def engine_volumes(files):
    volumes = [['/var/lib/metainc/naver-engine', '/var/lib/naver-engine', False],
               ['/run/metainc/naver-engine', '/run/naver-engine', False],
               ['/var/backups/metainc/naver-engine', '/var/backups/naver-engine', False],
               ['/run/metainc-naver-erp-tunnel', '/run/naver-erp-tunnel', True]]
    if any(f.endswith('naver-engine-backup.override.yml') for f in files):
        volumes += [['/etc/metainc/naver-engine/backup-recipient.pem', '/run/secrets/naver-backup-recipient.pem', True]]
    if any('naver-saved-exports' in f for f in files):
        volumes += [['/var/lib/metainc/naver-product-source', '/var/lib/naver-product-source', True]]
    return volumes


def compose_config(project, files):
    commit = release_commit(files)
    change = (config().get('shape_change') or {}).get(commit or '')
    if project == 'naver-engine':
        volumes = engine_volumes(files)
        service = {'user': '10001:10001', 'restart': 'no', 'read_only': True, 'cap_drop': ['ALL'],
                   'security_opt': ['no-new-privileges:true'], 'tmpfs': ['/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777'],
                   'environment': effective_env(commit, files)}
    else:
        volumes = [['/run/metainc/naver-relay', '/run/naver-relay', False],
                   ['/run/metainc/naver-engine', '/run/naver-engine', True]]
        service = {'user': '10001:10001', 'restart': 'no', 'read_only': True, 'network_mode': 'none',
                   'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
                   'environment': {'TZ': 'Asia/Seoul', 'NAVER_AUTO_WEB': 'on'}}
    if change == 'data_source' and project == 'naver-engine':
        volumes[0][0] = '/var/lib/metainc/naver-engine-empty'
    service['volumes'] = [{'type': 'bind', 'source': src, 'target': dst, 'read_only': ro,
                           'bind': {'create_host_path': False}} for src, dst, ro in volumes]
    service['image'] = 'metainc/' + project + ':' + (commit or 'unknown')
    services = {project: service}
    if change == 'restart':
        service['restart'] = 'always'
    if change == 'extra_service':
        services['naver-sidecar'] = dict(service)
    return {'name': project, 'services': services}


def create_container(state, project, files):
    tag = None
    for path in files:
        if os.path.basename(path).startswith('preview-'):
            tag = override_image(path)
    image = resolve_image(state, tag) if tag else None
    if image is None:
        sys.stderr.write('no such image %s\n' % tag)
        sys.exit(1)
    old = project_container(state, project)
    if old:
        if state['containers'][old]['running']:
            sys.stderr.write('container running\n')
            sys.exit(1)
        del state['containers'][old]
    identity = new_id(state, 'container')
    commit = image_commit(state, image)
    env = effective_env(commit, files) if project == 'naver-engine' else {'TZ': 'Asia/Seoul', 'NAVER_AUTO_WEB': 'on'}
    shape = compose_config(project, files)['services'][project]
    state['containers'][identity] = {
        'project': project, 'image': image, 'running': False, 'pid': 0, 'started': '0001-01-01T00:00:00Z',
        'restarts': 0, 'user': '10001:10001', 'inspects': 0, 'env': ['%s=%s' % kv for kv in sorted(env.items())],
        'mounts': [[v['type'], v['source'], v['target'], not v['read_only']] for v in shape['volumes']]}
    return identity


def compose(state, args):
    project, files, rest = None, [], list(args)
    while rest and rest[0] in ('--project-name', '-f'):
        if rest[0] == '--project-name':
            project = rest[1]
        else:
            files.append(rest[1])
        rest = rest[2:]
    for path in files:
        if not os.path.isfile(path):
            sys.stderr.write('missing compose file %s\n' % path)
            sys.exit(1)
    command = rest[0] if rest else ''
    if command == 'config':
        if config().get('compose_stderr'):
            sys.stderr.write(config()['compose_stderr'] + '\n')
        print(json.dumps(compose_config(project, files)))
        return
    if command == 'up' and '--no-start' in rest:
        create_container(state, project, files)
        return
    if command == 'version':
        print('2.29.0')
        return
    sys.stderr.write('fake compose: unsupported %s\n' % command)
    sys.exit(1)


def inspect_container(state, identity):
    container = state['containers'][identity]
    container['inspects'] = container.get('inspects', 0) + 1
    commit = image_commit(state, container['image'])
    if container['running'] and commit in config().get('flap', []) and container['inspects'] >= 2:
        container['started'] = tick(state)
    return {'Id': identity, 'Name': '/' + str(container.get('project') or 'other') + '-1', 'Image': container['image'],
            'RestartCount': container['restarts'],
            'State': {'Running': container['running'], 'Restarting': False, 'Pid': container['pid'],
                      'StartedAt': container['started'], 'Status': 'running' if container['running'] else 'exited'},
            'Config': {'User': container['user'], 'Env': container['env'], 'Image': container['image'],
                       'Labels': dict({'com.docker.compose.project': container['project'],
                                       'com.docker.compose.service': container['project'],
                                       'metainc.naver.preview.source': commit or ''},
                                      **(config().get('extra_labels') or {}))},
            'HostConfig': {'RestartPolicy': {'Name': 'no'}, 'NetworkMode': 'default'},
            'Mounts': [{'Type': m[0], 'Source': m[1], 'Destination': m[2], 'RW': m[3]}
                       for m in container.get('mounts') or []]}


def late_hooks(state, args):
    """시험용 경합 대역: 정리 도중(첫 image rm 뒤) 새 참조가 생기거나 태그가 다른 이미지로 옮겨지는 상황."""
    hooks = config()
    if args[:2] == ['image', 'rm']:
        state['armed'] = True
        retag = hooks.get('retag_on_rm')
        if retag and args[2] == retag['trigger'] and not state.get('retagged'):
            for image in state['images'].values():
                if retag['retag'] in image['tags']:
                    image['tags'].remove(retag['retag'])
            identity = new_id(state, 'image')
            state['images'][identity] = {'tags': [retag['retag']], 'user': '10001:10001', 'labels': {}, 'schema': 21}
            state['retagged'] = True
    late = hooks.get('late_unit')
    if (late and args[:2] == ['ps', '--all'] and not state.get('late_written')
            and not os.path.exists(hooks['root'] + late['when_missing'])):
        path = hooks['root'] + late['path']
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as handle:
            handle.write(late['body'])
        state['late_written'] = True


def docker(args):
    state = load(STATE, None)
    late_hooks(state, args)
    if args[:1] == ['compose']:
        compose(state, args[1:])
    elif args[:2] == ['image', 'inspect']:
        refs = [a for a in args[2:] if not a.startswith('-')]
        rows = []
        for ref in refs:
            identity = resolve_image(state, ref)
            if identity is None:
                sys.stderr.write('No such image\n')
                sys.exit(1)
            image = state['images'][identity]
            rows.append({'Id': identity, 'RepoTags': image['tags'], 'Size': image.get('size', 300000000),
                         'Config': {'User': image['user'], 'Labels': image['labels']}})
        print(json.dumps(rows))
    elif args[:2] == ['image', 'rm']:
        ref = args[2]
        identity = resolve_image(state, ref)
        if identity is None:
            sys.stderr.write('Error: No such image: %s\n' % ref)
            sys.exit(1)
        if ref in (config().get('in_use_on_rm') or []) or any(
                c['image'] == identity for c in state['containers'].values()):
            sys.stderr.write('Error response from daemon: conflict: unable to remove repository reference '
                             '"%s" - container is using its referenced image\n' % ref)
            sys.exit(1)
        image = state['images'][identity]
        if ref in image['tags']:
            image['tags'].remove(ref)
        if not image['tags']:
            del state['images'][identity]
        print('Untagged: ' + ref)
    elif args[:2] == ['system', 'df']:
        rows = []
        for identity, image in sorted(state['images'].items()):
            for tag in image['tags']:
                repository, _, name = tag.partition(':')
                rows.append({'Repository': repository, 'Tag': name, 'ID': identity[7:19],
                             'Size': '%.3gGB' % (image.get('size', 300000000) / 1e9),
                             'UniqueSize': '%.4gMB' % (image.get('unique', 100000000) / 1e6)})
        print(json.dumps({'Images': rows, 'Containers': [], 'Volumes': [], 'BuildCache': []}))
    elif args[:1] == ['info']:
        print('/var/lib/docker')
    elif args[:2] == ['image', 'ls']:
        for identity, image in sorted(state['images'].items()):
            for tag in image['tags']:
                repository, _, name = tag.partition(':')
                print(json.dumps({'Repository': repository, 'Tag': name, 'ID': identity}))
    elif args[:1] == ['build']:
        labels, tag, rest = {}, None, list(args[1:])
        while rest:
            if rest[0] == '--label':
                key, _, value = rest[1].partition('=')
                labels[key] = value
                rest = rest[2:]
            elif rest[0] in ('-t', '-f'):
                if rest[0] == '-t':
                    tag = rest[1]
                elif not os.path.isfile(rest[1]):
                    sys.stderr.write('no Dockerfile\n')
                    sys.exit(1)
                rest = rest[2:]
            elif rest[0] == '--quiet':
                rest = rest[1:]
            else:
                context = rest[0]
                rest = rest[1:]
        name = 'engine' if 'naver-engine' in tag else 'relay'
        if config().get('build_stderr'):
            sys.stderr.write(config()['build_stderr'] + '\n')
        if config().get('build_fail') == name:
            sys.stderr.write('build failed\n')
            sys.exit(1)
        with open(os.path.join(context, 'naver_engine/store.py')) as handle:
            schema = int(re.search(r'(?m)^SCHEMA_VERSION\s*=\s*(\d+)', handle.read()).group(1))
        for image in state['images'].values():
            if tag in image['tags']:
                image['tags'].remove(tag)
        identity = new_id(state, 'image')
        labels.update(config().get('extra_labels') or {})
        state['images'][identity] = {'tags': [tag], 'labels': labels, 'user': '10001:10001', 'schema': schema}
        print(identity)
    elif args[:1] == ['tag']:
        identity = resolve_image(state, args[1])
        if identity is None:
            sys.exit(1)
        for image in state['images'].values():
            if args[2] in image['tags']:
                image['tags'].remove(args[2])
        state['images'][identity]['tags'].append(args[2])
    elif args[:1] == ['rmi']:
        identity = resolve_image(state, args[1])
        if identity is None:
            sys.exit(1)
        image = state['images'][identity]
        image['tags'].remove(args[1])
        if not image['tags'] and not any(c['image'] == identity for c in state['containers'].values()):
            del state['images'][identity]
    elif args[:1] == ['ps']:
        projects = [a.split('=', 2)[2] for a in args if a.startswith('label=com.docker.compose.project=')]
        ancestors = [a.split('=', 1)[1] for a in args if a.startswith('ancestor=')]
        for identity, container in sorted(state['containers'].items()):
            if projects and container.get('project') != projects[0]:
                continue
            if ancestors and container['image'] != resolve_image(state, ancestors[0]):
                continue
            print(identity)
    elif args[:1] == ['inspect']:
        identities = [a for a in args[1:] if not a.startswith('-')]
        if any(identity not in state['containers'] for identity in identities):
            sys.exit(1)
        print(json.dumps([inspect_container(state, identity) for identity in identities]))
    elif args[:1] == ['create']:
        image = resolve_image(state, args[-1])
        identity = new_id(state, 'container')
        state['containers'][identity] = {'project': None, 'image': image, 'running': False, 'pid': 0,
                                         'started': '', 'restarts': 0, 'user': '10001:10001', 'env': []}
        print(identity)
    elif args[:1] == ['cp']:
        identity, _, path = args[1].partition(':')
        image = state['images'][state['containers'][identity]['image']]
        body = ('SCHEMA_VERSION = %d   # fake\n' % image['schema']).encode()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as archive:
            info = tarfile.TarInfo(os.path.basename(path))
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
        sys.stdout.buffer.write(buffer.getvalue())
    elif args[:1] == ['run']:
        # check-config 전용 대역: -e 로 이름만 받은 값을 이 프로세스 환경에서 읽어 제품과 같은 규칙으로 계산한다.
        names = [args[i + 1] for i, a in enumerate(args) if a == '-e']
        env = {name: os.environ.get(name, '') for name in names}
        switches = {}
        for name in ('sync', 'links', 'morning', 'alerts', 'metrics', 'inventory', 'execution', 'backup', 'web',
                     'issue_alerts'):
            switches[name] = env.get('NAVER_ENGINE_%s_ENABLED' % name.upper(), 'false').strip().lower() in ('true', 'on', '1')
        if config().get('check_stderr'):
            sys.stderr.write(config()['check_stderr'] + '\n')
        print(json.dumps({'command': 'check-config', 'configuration': 'valid', 'switches': switches,
                          'network_performed': False, 'storage_opened': False, 'credentials_verified': False,
                          'web_available': False, 'deployment_ready': False}))
    elif args[:1] == ['rm']:
        del state['containers'][args[1]]
    elif args[:1] == ['version']:
        print('27.0.0')
    else:
        sys.stderr.write('fake docker: unsupported %s\n' % args)
        sys.exit(1)
    save(state)


def unit_project(text):
    start = [line for line in text.splitlines() if line.startswith('ExecStart=')][0].split(' ')
    project = start[start.index('--project-name') + 1]
    files = [start[i + 1] for i, token in enumerate(start) if token == '-f']
    return project, files


def unit_file(name):
    path = config()['root'] + UNIT_DIR + '/' + name
    if not os.path.exists(path):
        return None
    with open(path) as handle:
        return handle.read()


def systemctl(args):
    state = load(STATE, None)
    units = state['units']
    if args[:1] == ['show']:
        name = args[1]
        unit = units.get(name, {'active': 'inactive', 'pid': 0})
        disk = unit_file(name)
        values = {'Id': name, 'ActiveState': unit['active'], 'SubState': 'running' if unit['active'] == 'active' else 'dead',
                  'MainPID': str(unit['pid']), 'UnitFileState': unit.get('enabled', 'enabled'),
                  'NRestarts': str(unit.get('restarts', 0)),
                  'FragmentPath': (UNIT_DIR + '/' + name) if disk is not None else '',
                  'DropInPaths': unit.get('dropins', ''), 'ExecMainStartTimestamp': '',
                  'NeedDaemonReload': 'no' if disk is None or unit.get('loaded') == disk else 'yes'}
        fields = args[args.index('-p') + 1].split(',')
        if '--value' in args:
            print(values[fields[0]])
        else:
            for field in fields:
                print('%s=%s' % (field, values[field]))
    elif args[:1] == ['cat']:
        print('# %s/%s' % (UNIT_DIR, args[1]))
        sys.stdout.write(unit_file(args[1]) or '')
    elif args[:1] == ['--version']:
        print('systemd 255 (fake)')
    elif args[:1] == ['daemon-reload']:
        for name, unit in units.items():
            disk = unit_file(name)
            if disk is not None:
                unit['loaded'] = disk
    elif args[:1] == ['stop']:
        name = args[1]
        unit = units[name]
        if name in (config().get('stop_noop') or []):
            save(state)
            return
        if unit.get('loaded'):
            project, _ = unit_project(unit['loaded'])
            identity = project_container(state, project)
            if identity:
                state['containers'][identity].update(running=False, pid=0)
        unit.update(active='inactive', pid=0)
    elif args[:1] == ['start']:
        name = args[1]
        unit = units[name]
        project, files = unit_project(unit['loaded'])
        root = config()['root']
        identity = project_container(state, project) or create_container(state, project, [root + f for f in files])
        state['seq'] = state.get('seq', 0) + 1
        state['containers'][identity].update(running=True, pid=1000 + state['seq'], started=tick(state), inspects=0)
        unit.update(active='active', pid=2000 + state['seq'])
    else:
        sys.stderr.write('fake systemctl: unsupported %s\n' % args)
        sys.exit(1)
    save(state)
    kill = config().get('kill_after')
    if kill and kill == ' '.join(args):
        os.kill(os.getppid(), signal.SIGKILL)


def curl(args):
    state = load(STATE, None)
    socket_path = args[args.index('--unix-socket') + 1]
    url = args[-1]
    path = url.split('http://localhost', 1)[1]
    fails = config().get('health_fail', [])

    def running(project):
        identity = project_container(state, project)
        if identity and state['containers'][identity]['running']:
            return image_commit(state, state['containers'][identity]['image'])
        return None
    engine = running('naver-engine')
    if socket_path.endswith('engine.sock'):
        code = '000' if engine is None else ('503' if engine in fails else '200')
    else:
        relay = running('naver-relay')
        if relay is None:
            code = '000'
        elif path == '/naver/':
            code = '200'
        elif path == '/api/naver-auto/me':
            code = '401' if engine is not None and engine not in fails else '503'
        else:
            code = '404'
    sys.stdout.write(code)
    sys.exit(7 if code == '000' else 0)


def flock(args):
    descriptor = int(args[-1])
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | (fcntl.LOCK_NB if '-n' in args else 0))
    except OSError:
        sys.exit(1)


def main(tool):
    args = sys.argv[1:]
    record(tool, args)
    if tool == 'docker':
        docker(args)
    elif tool == 'systemctl':
        systemctl(args)
    elif tool == 'curl':
        curl(args)
    elif tool == 'flock':
        flock(args)
    elif tool == 'cp':
        if config().get('cp_corrupt') and args[-1].endswith('/engine.db'):
            import subprocess
            subprocess.run(['/bin/cp'] + args, check=True)
            with open(args[-1], 'r+b') as handle:
                handle.seek(5)
                handle.write(b'#')
            return
        os.execv('/bin/cp', ['/bin/cp'] + args)
    elif tool == 'sqlite3':
        sys.stderr.write('sqlite3 must never be called by the deploy\n')
        sys.exit(99)
