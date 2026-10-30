#!/usr/bin/env bash
# 네이버 관제(engine + relay) 단순 배포 — 서버(VPS)에서 root 로 실행한다.
#
#   naver-deploy.sh inspect
#       읽기 전용. 서비스·이미지·폴더 상태를 한 줄 JSON 으로 출력한다(무엇도 바꾸지 않는다).
#   naver-deploy.sh deploy <제품 커밋 40자리> <source.tar> [--log FILE] [--result FILE]
#       시험을 통과한 정확한 커밋을 배포한다. 실패하면 직전 판으로 자동 복원한다.
#   naver-deploy.sh cleanup-plan
#       읽기 전용. 지워도 되는 관제 이미지 태그·release 폴더 목록과 회수량 추정, allowlist_sha256 을 낸다.
#   naver-deploy.sh cleanup <allowlist_sha256>
#       계획을 다시 세워 해시가 정확히 같을 때만 그 목록만 지운다(docker image rm 강제 없음, release 폴더 rm -r).
#
# 지키는 것(docs/naver-simple-deploy.md 와 같은 목록):
#   - 이미지 두 개를 커밋 태그로 먼저 빌드한 뒤에만 서비스를 멈춘다.
#   - 직전 이미지 ID·unit 파일·override 파일을 서버의 복구 기록에 먼저 남긴다
#     (SSH 가 끊기거나 서버가 재부팅돼도 다음 실행이 그 기록으로 복원한다).
#   - 정지는 relay → engine(PID 0 확인), 시작은 engine → relay.
#   - engine.db* 는 제자리 보존. 엔진이 멈춘 동안에만 파일 복사(보관 1벌, 크기·sha256 검증 뒤에만 직전 사본 삭제).
#   - 이미지 빌드·release 폴더 생성 전에 공간 예산을 확인한다.
#     sqlite 로 DB 를 열지 않는다.
#   - runtime.env, nginx, ERP 터널 unit, 다른 앱, saved-exports companion 은 건드리지 않는다.
#   - execution_enabled 는 false 여야 하고, 실행 중 판의 유효 스위치(inventory 등)와 새 판이 같아야 한다.
#   - check-config 는 운영 data·socket·backup·tunnel mount 없이(네트워크 없음·읽기 전용·10001) 돌린다.
#   - compose 설정 묶음(서비스 목록·mount·user 10001·restart no 등)이 직전과 같아야 한다.
#   - 공개 로그로는 고정 형식 결과 한 줄만 나간다. 명령 원문 출력은 서버의 비공개 로그에만 쓴다.
#   - 제품 SCHEMA_VERSION 이 지금 돌고 있는 판과 다르면 거부한다(우회 입력 없음).
#   - 헬스체크: engine /_engine/health 200, relay /naver/ 200, /api/naver-auto/me 401,
#     그 뒤 60초 동안 unit active + 컨테이너 RestartCount 0 + StartedAt 불변.
#
# 종료 코드: 0 성공 · 2 배포 실패 후 직전 판 복원 완료 · 3 중단된 이전 실행을 복원함(다시 실행)
#           4 복원 실패(두 서비스 정지, 사람 확인 필요) · 10 시작 전 거부(아무것도 안 바뀜) · 11 다른 배포 실행 중
set -Eeuo pipefail
umask 077

# ── 시험용 가짜 루트 ─────────────────────────────────────────────────────
# NAVER_DEPLOY_ROOT 가 비어 있으면 실제 서버. 값이 있으면 그 폴더를 / 로 보는 로컬 시험이다
# (deploy/naver/tests). 실제 서버 실행에서는 PATH 를 고정한다.
R="${NAVER_DEPLOY_ROOT:-}"
if [ -n "$R" ]; then
  TEST_MODE=1
else
  TEST_MODE=0
  PATH=/usr/sbin:/usr/bin:/sbin:/bin
  export PATH
fi
export LANG=C LC_ALL=C

# ── 서버 배치(옛 실행기 release/conversion-20261026 에서 확인한 값) ─────────────
UNIT_DIR=/etc/systemd/system
ENGINE_UNIT=metainc-naver-engine.service
RELAY_UNIT=metainc-naver-relay.service
TUNNEL_UNIT=metainc-naver-erp-tunnel.service
TMPFILES_CONF=/etc/tmpfiles.d/metainc-naver-preview.conf
RELEASES=/srv/metainc/ad-deploy-staging/releases
DATA_DIR=/var/lib/metainc/naver-engine
ENGINE_SOCK=/run/metainc/naver-engine/engine.sock
RELAY_SOCK=/run/metainc/naver-relay/relay.sock
RUNTIME_ENV=/etc/metainc/naver-engine/runtime.env
NGINX_DIR=/etc/nginx
STATE_DIR=/var/lib/metainc/naver-deploy
DB_BACKUP_PARENT=/var/backups/metainc
DB_BACKUPS=/var/backups/metainc/naver-deploy-db
HOST_HEADER=dashboard.metainc.co.kr

HOLD_SECONDS=60
READY_TIMEOUT=120
STOP_TIMEOUT=100
POLL=2
HOLD_POLL=5
if [ "$TEST_MODE" = 1 ]; then
  HOLD_SECONDS="${NAVER_DEPLOY_HOLD_SECONDS:-1}"
  READY_TIMEOUT="${NAVER_DEPLOY_READY_TIMEOUT:-3}"
  STOP_TIMEOUT="${NAVER_DEPLOY_STOP_TIMEOUT:-3}"
  POLL="${NAVER_DEPLOY_POLL:-0.1}"
  HOLD_POLL="${NAVER_DEPLOY_HOLD_POLL:-0.2}"
fi

# ── 내부 도우미(Python 3, 표준 라이브러리만; sqlite 를 import 하지 않는다) ─────────
PY_HELPER=$(cat <<'PYEOF'
import contextlib, hashlib, io, json, os, re, secrets, shutil, stat, subprocess, sys, tarfile, time

ROOT = os.environ.get('NAVER_DEPLOY_ROOT', '')
RELEASES = '/srv/metainc/ad-deploy-staging/releases'
COMPANION_RE = re.compile(r'/srv/metainc/ad-deploy-staging/saved-exports/[0-9a-f]{32}/naver-saved-exports\.override\.yml\Z')
HEX40 = re.compile(r'[0-9a-f]{40}\Z')
# 옛 실행기 naver_preview_release.py EXACT/PREFIXES 와 같은 범위. tests·캐시·키·env 는 뺀다.
EXACT = {'.dockerignore', 'Dockerfile.naver-engine', 'Dockerfile.naver-engine.dockerignore',
         'Dockerfile.naver-relay', 'Dockerfile.naver-relay.dockerignore', 'compose.naver-engine.yml',
         'compose.naver-relay.yml', 'backend/app/__init__.py', 'backend/app/naver_entry.py',
         'backend/app/naver_relay.py', 'backend/app/routers/naver.py', 'backend/app/routers/__init__.py',
         'backend/requirements.txt'}
PREFIXES = ('naver_engine/', 'naver_runtime/', 'backend/app/naver_auto/', 'backend/naver_page/', 'deploy/')
REQUIRED = {'Dockerfile.naver-engine', 'Dockerfile.naver-relay', 'compose.naver-engine.yml',
            'compose.naver-relay.yml', 'deploy/naver-engine-backup.override.yml', 'naver_engine/store.py'}
OVERRIDES = ('preview-engine.override.yml', 'preview-relay.override.yml')
DB_NAME = re.compile(r'engine\.db(-wal|-shm|-journal)?\Z')
BACKUP_DIR_NAME = re.compile(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\Z')


class Refuse(Exception):
    pass


def fail(message):
    raise Refuse(message)


def read(path, mode='r'):
    with open(path, mode) as handle:
        return handle.read()


def excluded(name):
    parts = name.split('/')
    return (any(part in ('tests', '__pycache__', '.git') for part in parts) or 'store 2.py' in parts
            or name == 'HANDOVER.md' or name.endswith(('.pyc', '.env', '.pem', '.key')) or '.env.' in parts[-1])


def allowed_file(name):
    return (name in EXACT or name.startswith(PREFIXES)) and not excluded(name)


def schema_of(text):
    found = re.findall(r'(?m)^SCHEMA_VERSION\s*=\s*([0-9]+)\b', text)
    if len(found) != 1:
        fail('SCHEMA_VERSION 정의를 정확히 1개 찾지 못했습니다(%d개)' % len(found))
    return int(found[0])


def unit_parse(path, name):
    """기존 unit 이 옛 실행기(naver_preview_lifecycle.unit_files)가 만든 모양인지 확인한다."""
    text = read(path)
    lines = text.splitlines()
    starts = [line[len('ExecStart='):] for line in lines if line.startswith('ExecStart=')]
    stops = [line[len('ExecStop='):] for line in lines if line.startswith('ExecStop=')]
    if len(starts) != 1 or len(stops) != 1:
        fail('LAYOUT: %s 의 ExecStart/ExecStop 줄 수가 %d/%d 입니다(1/1 이어야 함)' % (path, len(starts), len(stops)))
    if 'Restart=always' not in lines:
        fail('LAYOUT: %s 에 Restart=always 가 없습니다' % path)
    need = 'metainc-naver-erp-tunnel.service' if name == 'engine' else 'metainc-naver-engine.service'
    if not any(line.startswith('Requires=') and need in line.split() for line in lines):
        fail('LAYOUT: %s 의 Requires= 에 %s 가 없습니다' % (path, need))

    def files_of(command, tail):
        tokens = command.split(' ')
        head = ['/usr/bin/docker', 'compose', '--project-name', 'naver-' + name]
        if tokens[:4] != head:
            fail('LAYOUT: %s 명령 머리가 예상과 다릅니다: %s' % (path, ' '.join(tokens[:4])))
        rest, files = tokens[4:], []
        while len(rest) >= 2 and rest[0] == '-f':
            files.append(rest[1])
            rest = rest[2:]
        if rest != tail:
            fail('LAYOUT: %s 명령 꼬리가 예상과 다릅니다: %s' % (path, ' '.join(rest)))
        return files

    start = files_of(starts[0], ['up', '--no-build', '--no-recreate', '--abort-on-container-exit',
                                 '--exit-code-from', 'naver-' + name, 'naver-' + name])
    stop = files_of(stops[0], ['stop', '--timeout', '45', 'naver-' + name])
    if start != stop:
        fail('LAYOUT: %s 의 ExecStart 와 ExecStop compose 파일 목록이 다릅니다' % path)
    if not start:
        fail('LAYOUT: %s 에 compose 파일이 없습니다' % path)
    match = re.fullmatch(re.escape(RELEASES) + r'/naver-([0-9a-f]{40})/compose\.naver-' + name + r'\.yml', start[0])
    if not match:
        fail('LAYOUT: %s 첫 compose 파일이 releases/naver-<커밋>/compose.naver-%s.yml 이 아닙니다: %s' % (path, name, start[0]))
    commit = match.group(1)
    release = RELEASES + '/naver-' + commit
    expected = [release + '/compose.naver-' + name + '.yml']
    if name == 'engine':
        expected.append(release + '/deploy/naver-engine-backup.override.yml')
    expected.append(release + '/preview-' + name + '.override.yml')
    if start[:len(expected)] != expected:
        fail('LAYOUT: %s compose 파일 목록이 예상과 다릅니다: %s' % (path, ' '.join(start)))
    extra, companion = start[len(expected):], '-'
    if name == 'engine' and len(extra) == 1 and COMPANION_RE.match(extra[0]):
        companion = extra[0]
    elif extra:
        fail('LAYOUT: %s 에 예상하지 못한 compose 파일이 있습니다: %s' % (path, ' '.join(extra)))
    count, want = text.count(commit), 2 * len(expected)
    if count != want:
        fail('LAYOUT: %s 에 커밋 문자열이 %d번 있습니다(%d번이어야 함)' % (path, count, want))
    print(commit, companion)


def override_check(path, name, commit):
    body = read(path)
    line = '    image: metainc/naver-%s:%s' % (name, commit)
    if body.splitlines().count(line) != 1 or body.count(commit) != 1:
        fail('LAYOUT: %s 에 "%s" 줄이 정확히 한 번만 있어야 합니다' % (path, line.strip()))


def subst(source, target, old, new, expected):
    body = read(source, 'rb')
    count = body.count(old.encode())
    if count != int(expected):
        fail('REPLACE_COUNT: %s 에서 %s 가 %d번 나왔습니다(%s번이어야 함)' % (source, old[:12], count, expected))
    if new.encode() in body:
        fail('REPLACE_COUNT: %s 에 이미 새 커밋이 들어 있습니다' % source)
    out = body.replace(old.encode(), new.encode())
    if out.count(new.encode()) != count or old.encode() in out:
        fail('REPLACE_COUNT: 치환 결과가 맞지 않습니다')
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(out)
        handle.flush()
        os.fsync(handle.fileno())


def members(path):
    archive = tarfile.open(path, 'r:*')
    result, total = [], 0
    for member in archive.getmembers():
        name = member.name
        while name.startswith('./'):
            name = name[2:]
        name = name.rstrip('/')
        if name in ('', '.') and member.isdir():
            continue
        if name.startswith('/') or '..' in name.split('/') or '\\' in name or '//' in name:
            fail('ARCHIVE: 허용하지 않는 경로 %r' % member.name)
        if member.isdir():
            if not (any(item.startswith(name + '/') for item in EXACT) or name.startswith(PREFIXES)
                    or (name + '/') in PREFIXES or any(p.startswith(name + '/') for p in PREFIXES)):
                fail('ARCHIVE: 범위 밖 폴더 %s' % name)
            continue
        if not member.isfile():
            fail('ARCHIVE: 일반 파일·폴더가 아닌 항목 %s' % name)
        if not allowed_file(name):
            fail('ARCHIVE: 범위 밖 파일 %s' % name)
        total += member.size
        if member.size > 8 * 1024 * 1024 or total > 64 * 1024 * 1024 or len(result) >= 5000:
            fail('ARCHIVE: 크기 상한 초과')
        result.append((name, member))
    names = {name for name, _ in result}
    if len(names) != len(result):
        fail('ARCHIVE: 같은 경로가 두 번 들어 있습니다')
    missing = sorted(REQUIRED - names)
    if missing:
        fail('ARCHIVE: 필수 파일 없음: %s' % ', '.join(missing))
    return archive, result


def tar_check(path):
    archive, items = members(path)
    store = dict(items)['naver_engine/store.py']
    print(schema_of(archive.extractfile(store).read().decode('utf-8')))


def tar_extract(path, destination):
    archive, items = members(path)
    os.mkdir(destination, 0o700)
    for name, member in items:
        target = os.path.join(destination, name)
        parent = os.path.dirname(target)
        if not os.path.isdir(parent):
            os.makedirs(parent, 0o755)
        body = archive.extractfile(member).read()
        mode = 0o755 if member.mode & 0o111 else 0o644
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(body)
        os.chmod(target, mode)
    for folder, children, _ in os.walk(destination):
        for child in children:
            os.chmod(os.path.join(folder, child), 0o755)
    os.chmod(destination, 0o700)


def tree_compare(path, existing):
    """이미 있는 releases/naver-<커밋> 이 이 커밋의 원본과 같은지(덮어쓰지 않고) 확인한다."""
    archive, items = members(path)
    wanted, problems = {}, []
    for name, member in items:
        wanted[name] = archive.extractfile(member).read()
    for name, body in sorted(wanted.items()):
        target = os.path.join(existing, name)
        if os.path.islink(target) or not os.path.isfile(target):
            problems.append('없음 ' + name)
        elif read(target, 'rb') != body:
            problems.append('내용 다름 ' + name)
    for folder, children, files in os.walk(existing):
        for child in children:
            if os.path.islink(os.path.join(folder, child)):
                problems.append('링크 ' + os.path.relpath(os.path.join(folder, child), existing))
        for item in files:
            name = os.path.relpath(os.path.join(folder, item), existing)
            if name not in wanted and name not in OVERRIDES and not excluded(name):
                problems.append('추가 파일 ' + name)
    if problems:
        fail('RELEASE_DIR_DIFFERS: %s 가 이 커밋 원본과 다릅니다(%d건): %s' % (existing, len(problems), '; '.join(problems[:5])))


def image_info():
    rows = json.load(sys.stdin)
    if not isinstance(rows, list) or len(rows) != 1:
        fail('이미지 정보 형식 오류')
    row = rows[0]
    labels = (row.get('Config') or {}).get('Labels') or {}
    user = (row.get('Config') or {}).get('User') or '-'
    print(row.get('Id', '-'), user or '-', labels.get('metainc.naver.preview.source') or '-',
          labels.get('metainc.naver.schema') or '-')


def env_flag(values, name):
    seen = None
    for item in values or []:
        key, sep, value = item.partition('=')
        if key != name:
            continue
        if not sep or seen is not None:
            return 'invalid'
        value = value.strip().lower()
        if value in ('false', 'off', '0', ''):
            seen = False
        elif value in ('true', 'on', '1'):
            seen = True
        else:
            return 'invalid'
    return 'true' if seen else 'false'


def container_info():
    rows = json.load(sys.stdin)
    if not isinstance(rows, list) or len(rows) != 1:
        fail('컨테이너 정보 형식 오류')
    row = rows[0]
    state = row.get('State') or {}
    config = row.get('Config') or {}
    labels = config.get('Labels') or {}
    # Env 는 메모리에서 두 스위치만 본다. 값은 절대 출력하지 않는다.
    print('|'.join(str(value) for value in (
        row.get('Id', '-'), row.get('Image', '-'), str(bool(state.get('Running'))).lower(),
        str(bool(state.get('Restarting'))).lower(), state.get('Pid', '-'), state.get('StartedAt', '-'),
        row.get('RestartCount', '-'), labels.get('com.docker.compose.project', '-'),
        labels.get('com.docker.compose.service', '-'), env_flag(config.get('Env'), 'NAVER_ENGINE_EXECUTION_ENABLED'),
        config.get('User') or '-')))


SWITCHES = ('sync', 'links', 'morning', 'alerts', 'metrics', 'inventory', 'execution', 'backup', 'web',
            'issue_alerts')
ENV_NAME = re.compile(r'[A-Z][A-Z0-9_]{0,63}\Z')
RESERVED_ENV = {'PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'SHELL', 'USER'}
CHECK_DATA_TMPFS = '/var/lib/naver-engine:rw,noexec,nosuid,nodev,size=8m,uid=10001,gid=10001,mode=0700'


def canonical(values):
    return ','.join('%s=%s' % (name, 'true' if values[name] else 'false') for name in SWITCHES)


def env_to_map(items):
    result = {}
    for item in items or []:
        key, sep, value = str(item).partition('=')
        if not sep or key in result:
            fail('FLAGS: 컨테이너 환경 변수 형식이 이상합니다')
        result[key] = value
    return result


def switches_from_env(env):
    """제품 naver_runtime/config.py _flag 와 같은 규칙으로 유효 스위치를 구한다(값은 출력하지 않는다)."""
    values = {}
    for name in SWITCHES:
        raw = str(env.get('NAVER_ENGINE_%s_ENABLED' % name.upper(), 'false')).strip().lower()
        if raw in ('false', 'off', '0', ''):
            values[name] = False
        elif raw in ('true', 'on', '1'):
            values[name] = True
        else:
            fail('FLAGS: %s 스위치 값이 참/거짓이 아닙니다' % name)
    return values


def env_switches():
    rows = json.load(sys.stdin)
    if not isinstance(rows, list) or len(rows) != 1:
        fail('FLAGS: 컨테이너 정보 형식 오류')
    print(canonical(switches_from_env(env_to_map(((rows[0].get('Config') or {}).get('Env'))))))


def container_mounts():
    rows = json.load(sys.stdin)
    if not isinstance(rows, list) or len(rows) != 1:
        fail('MOUNTS: 컨테이너 정보 형식 오류')
    mounts = sorted([str(m.get('Type')), str(m.get('Source')), str(m.get('Destination')), bool(m.get('RW'))]
                    for m in rows[0].get('Mounts') or [])
    print(json.dumps(mounts, separators=(',', ':')))


def compose_shape():
    """compose config(JSON)에서 관제의 작은 설정 묶음만 뽑는다. environment(비밀값 포함)는 읽지 않는다."""
    data = json.load(sys.stdin)
    services = data.get('services') if isinstance(data, dict) else None
    if not isinstance(services, dict) or not services:
        fail('COMPOSE_SHAPE: services 가 없습니다')
    shape = {}
    for name in sorted(services):
        service = services[name] or {}
        volumes = []
        for volume in service.get('volumes') or []:
            if not isinstance(volume, dict):
                fail('COMPOSE_SHAPE: 긴 형식이 아닌 volume 이 있습니다')
            volumes.append([volume.get('type'), volume.get('source'), volume.get('target'),
                            bool(volume.get('read_only', False)),
                            bool((volume.get('bind') or {}).get('create_host_path', True))])
        tmpfs = service.get('tmpfs') or []
        if isinstance(tmpfs, str):
            tmpfs = [tmpfs]
        shape[name] = {'user': service.get('user'), 'restart': service.get('restart'),
                       'network_mode': service.get('network_mode'), 'read_only': bool(service.get('read_only', False)),
                       'volumes': sorted(volumes, key=json.dumps), 'tmpfs': sorted(tmpfs),
                       'cap_drop': sorted(service.get('cap_drop') or []),
                       'security_opt': sorted(service.get('security_opt') or [])}
    print(json.dumps(shape, sort_keys=True, separators=(',', ':')))


def shape_diff(old, new):
    old, new = json.loads(old), json.loads(new)
    problems = []
    if sorted(old) != sorted(new):
        problems.append('services')
    for name in sorted(set(old) & set(new)):
        for key in sorted(set(old[name]) | set(new[name])):
            if old[name].get(key) != new[name].get(key):
                problems.append(name + '.' + key)
    for name, service in new.items():
        if service.get('user') != '10001:10001':
            problems.append(name + '.user!=10001:10001')
        if service.get('restart') != 'no':
            problems.append(name + '.restart!=no')
    if problems:
        fail('CONFIG_SHAPE_CHANGED: ' + ', '.join(sorted(set(problems))))


def check_config_run(image, private_log):
    """새 이미지로 check-config 를 운영 data·socket·backup·tunnel mount 없이 돌린다.
    환경 값은 docker 클라이언트 환경으로만 넘기고(-e 이름), 명령줄·로그에 값이 남지 않는다."""
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        fail('CHECK_CONFIG: 이미지 ID 형식 오류')
    data = json.load(sys.stdin)
    service = ((data.get('services') or {}).get('naver-engine')) if isinstance(data, dict) else None
    if not isinstance(service, dict):
        fail('CHECK_CONFIG: naver-engine 서비스가 없습니다')
    environment = service.get('environment') or {}
    if isinstance(environment, list):
        environment = env_to_map(environment)
    argv = ['docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '10001:10001',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--pids-limit', '64',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777', '--tmpfs', CHECK_DATA_TMPFS,
            '--label', 'metainc.naver.check-config=1']
    child = {'PATH': os.environ.get('PATH', '/usr/sbin:/usr/bin:/sbin:/bin'), 'LANG': 'C'}
    for key in sorted(environment):
        value = environment[key]
        if value is None:
            continue
        if not ENV_NAME.match(key) or key in RESERVED_ENV or key.startswith(('DOCKER_', 'COMPOSE_', 'BUILDKIT_')):
            fail('CHECK_CONFIG: 넘길 수 없는 환경 변수 이름이 있습니다')
        argv += ['-e', key]
        child[key] = str(value)
    argv += [image, 'python', '-B', '-m', 'naver_runtime', 'check-config']
    done = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child, timeout=180)
    with open(private_log, 'ab') as handle:
        handle.write(b'[check-config] exit %d\n' % done.returncode)
        handle.write(done.stderr[-20000:])
    if done.returncode:
        fail('CHECK_CONFIG: check-config 종료 코드 %d' % done.returncode)
    lines = done.stdout.decode('utf-8', 'replace').strip().splitlines()
    try:
        value = json.loads(lines[-1])
    except (ValueError, IndexError):
        fail('CHECK_CONFIG: 출력이 JSON 이 아닙니다')
    switches = value.get('switches') if isinstance(value, dict) else None
    if (value.get('command') != 'check-config' or value.get('configuration') != 'valid'
            or value.get('storage_opened') is not False or value.get('network_performed') is not False
            or not isinstance(switches, dict) or set(switches) != set(SWITCHES)
            or any(type(v) is not bool for v in switches.values())):
        fail('CHECK_CONFIG: 결과가 예상과 다릅니다')
    print(canonical(switches))


def state_write(path, *pairs):
    data = {}
    if os.path.exists(path):
        data = json.loads(read(path))
    for pair in pairs:
        key, _, value = pair.partition('=')
        data[key] = value
    data['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    temporary = path + '.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(data, handle, sort_keys=True, indent=1)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory = os.open(os.path.dirname(path), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def state_get(path, key):
    if os.path.exists(path):
        print(json.loads(read(path)).get(key, ''))


def history_add(path, commit):
    history = json.loads(read(path)) if os.path.exists(path) else []
    history = [item for item in history if item != commit] + [commit]
    temporary = path + '.tmp'
    with open(temporary, 'w') as handle:
        json.dump(history, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def prune_list(path, current, previous):
    """이 장치가 배포한 기록 중 최근 3개·현재·직전을 뺀 나머지 커밋만 정리 대상으로 낸다."""
    history = json.loads(read(path)) if os.path.exists(path) else []
    keep = set(history[-3:]) | {current, previous}
    for commit in history:
        if commit not in keep and HEX40.match(commit):
            print(commit)


def prune_history(path, *removed):
    history = json.loads(read(path)) if os.path.exists(path) else []
    history = [item for item in history if item not in removed]
    temporary = path + '.tmp'
    with open(temporary, 'w') as handle:
        json.dump(history, handle)
    os.replace(temporary, path)


def db_files(folder):
    names, total = [], 0
    for name in sorted(os.listdir(folder)):
        full = os.path.join(folder, name)
        if name.startswith('engine.db'):
            if not DB_NAME.match(name):
                fail('DB_FILES: 예상하지 못한 이름 %s' % name)
            info = os.lstat(full)
            if not stat.S_ISREG(info.st_mode):
                fail('DB_FILES: 일반 파일이 아닙니다: %s' % name)
            names.append(name)
            total += info.st_size
    if 'engine.db' not in names:
        fail('DB_FILES: engine.db 가 없습니다')
    print(total, *names)


def same_size(first, second):
    if os.lstat(first).st_size != os.lstat(second).st_size:
        fail('DB_COPY: 크기가 다릅니다 %s' % os.path.basename(first))


def backup_prune(folder, keep):
    names = sorted(name for name in os.listdir(folder) if BACKUP_DIR_NAME.match(name))
    for name in names[:-int(keep)] if len(names) > int(keep) else []:
        target = os.path.join(folder, name)
        for item in os.listdir(target):
            if not (DB_NAME.match(item) or item == 'manifest.json'):
                fail('BACKUP_PRUNE: 예상하지 못한 파일 %s/%s' % (name, item))
        for item in os.listdir(target):
            os.unlink(os.path.join(target, item))
        os.rmdir(target)
        print(name)


# ── 정지 상태 DB 사본: 크기·sha256 검증 후에만 직전 사본을 지운다(보관 1벌) ─────────────
PARTIAL_DIR_NAME = re.compile(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.partial\Z')


def file_sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_copy(source_dir, target_dir, *names):
    """복사본과 원본(엔진 정지 상태)의 크기·sha256 을 비교하고 manifest.json 을 남긴다."""
    manifest = {}
    for name in names:
        if not DB_NAME.match(name):
            fail('DB_COPY: 예상하지 못한 이름 %s' % name)
        source, target = os.path.join(source_dir, name), os.path.join(target_dir, name)
        if os.lstat(source).st_size != os.lstat(target).st_size:
            fail('DB_COPY: 크기가 다릅니다 %s' % name)
        first, second = file_sha(source), file_sha(target)
        if first != second:
            fail('DB_COPY: sha256 이 다릅니다 %s' % name)
        manifest[name] = {'size': os.lstat(target).st_size, 'sha256': second}
    path = os.path.join(target_dir, 'manifest.json')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(manifest, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    for name in list(names) + ['manifest.json']:
        fd = os.open(os.path.join(target_dir, name), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def remove_backup_dir(target):
    for item in os.listdir(target):
        if not (DB_NAME.match(item) or item == 'manifest.json'):
            fail('BACKUP_PRUNE: 예상하지 못한 파일 %s' % item)
    for item in os.listdir(target):
        os.unlink(os.path.join(target, item))
    os.rmdir(target)


def partial_prune(folder):
    """이전 실행이 남긴 미완성(.partial) 사본만 지운다. 완성된 사본은 건드리지 않는다."""
    for name in sorted(os.listdir(folder)):
        if PARTIAL_DIR_NAME.match(name):
            remove_backup_dir(os.path.join(folder, name))
            print(name)


# ── 공간 예산(같은 파일시스템이면 합산) ──────────────────────────────────────────
def disk_budget(*pairs):
    """인자: 경로=필요바이트 ... 같은 장치끼리 합산해 여유와 비교한다. 시험 때만 가짜 여유 바이트를 쓴다."""
    needs, free = {}, {}
    fake = os.environ.get('NAVER_DEPLOY_FAKE_FREE_BYTES') if ROOT else None
    for pair in pairs:
        path, _, amount = pair.rpartition('=')
        try:
            info = os.statvfs(path)
            device = os.stat(path).st_dev
        except OSError:
            fail('DISK: 경로를 확인하지 못했습니다 %s' % path[len(ROOT):])
        needs[device] = needs.get(device, 0) + int(amount)
        free[device] = int(fake) if fake else info.f_bavail * info.f_frsize
    for device, need in needs.items():
        if free[device] < need:
            fail('DISK: 필요 %d 바이트, 여유 %d 바이트 (부족 %d)' % (need, free[device], need - free[device]))
    print('ok')


def image_sizes():
    """표준입력의 docker image inspect JSON 배열에서 Size 합계(바이트)."""
    rows = json.load(sys.stdin)
    print(sum(int(row.get('Size') or 0) for row in rows))


# ── 정리 계획(cleanup-plan)과 실행(cleanup) ────────────────────────────────────
# 대상은 metainc/naver-engine·metainc/naver-relay 의 커밋(40자리) 태그와 releases/naver-<40자리> 폴더뿐이다.
# 현재 판, 고정 fallback, 컨테이너(실행·정지 모두)가 쓰는 이미지 ID, 관제 unit·compose·override·companion·
# 이 장치 기록이 가리키는 판·경로는 언제나 뺀다. 그 밖(saved-exports, receipts, runtime.env, 키, 데이터 폴더,
# 백업, 다른 앱 이미지, volume, build cache)은 계획에 들어올 수 없다.
FALLBACK_COMMIT = '89a924f2416f0450f38854b531bdf8778558dca6'
NAVER_REPOS = ('metainc/naver-engine', 'metainc/naver-relay')
RELEASE_REF = re.compile(r'releases/naver-([0-9a-f]{40})(?![0-9a-f])')


def docker(argv, timeout=120):
    done = subprocess.run(['docker'] + argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                          env={'PATH': os.environ.get('PATH', '/usr/sbin:/usr/bin:/sbin:/bin'), 'LANG': 'C'})
    return done.returncode, done.stdout.decode('utf-8', 'replace'), done.stderr.decode('utf-8', 'replace')


def docker_json(argv):
    code, out, _ = docker(argv)
    if code:
        fail('CLEANUP_PLAN: docker %s 실패' % argv[0])
    return json.loads(out)


def text_or_empty(path):
    try:
        with open(path, errors='replace') as handle:
            return handle.read()
    except OSError:
        return ''


def human_bytes(value):
    """docker 의 사람용 크기(예: 1.23GB, 512.5MB; 1000 단위)를 바이트로."""
    match = re.fullmatch(r'\s*([0-9.]+)\s*([kKMGT]?B)\s*', str(value or ''))
    if not match:
        return None
    scale = {'B': 1, 'kB': 1000, 'KB': 1000, 'MB': 1000 ** 2, 'GB': 1000 ** 3, 'TB': 1000 ** 4}[match.group(2)]
    return int(float(match.group(1)) * scale)


def tree_bytes(path):
    total = 0
    for folder, children, files in os.walk(path):
        for name in files + children:
            try:
                total += os.lstat(os.path.join(folder, name)).st_blocks * 512
            except OSError:
                pass
    return total


def protected_state():
    """보호 대상: 커밋·이미지 ID·release 경로. 근거별로 남긴다."""
    commits = {FALLBACK_COMMIT: ['fallback']}
    reasons_path = {}
    texts = []
    unit_dir = ROOT + '/etc/systemd/system'
    try:
        names = sorted(os.listdir(unit_dir))
    except OSError:
        fail('CLEANUP_PLAN: unit 폴더를 읽지 못했습니다')
    for name in names:
        if 'naver' in name and name.endswith(('.service', '.timer', '.path', '.socket')):
            texts.append(('unit', text_or_empty(os.path.join(unit_dir, name))))
    current = []
    for name in ('engine', 'relay'):
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                unit_parse(unit_dir + '/metainc-naver-' + name + '.service', name)
        except Refuse as error:
            fail('CLEANUP_PLAN: 현재 unit 모양을 확인하지 못해 계획을 세우지 않습니다 (%s)' % str(error).split(':')[0])
        commit, companion = captured.getvalue().split()
        current.append(commit)
        if companion != '-':
            texts.append(('companion', text_or_empty(ROOT + companion)))
    if len(set(current)) != 1:
        fail('CLEANUP_PLAN: engine·relay unit 이 다른 판을 가리킵니다')
    commits.setdefault(current[0], []).append('current')
    release = ROOT + RELEASES + '/naver-' + current[0]
    for name in ('compose.naver-engine.yml', 'compose.naver-relay.yml', 'deploy/naver-engine-backup.override.yml',
                 'preview-engine.override.yml', 'preview-relay.override.yml'):
        texts.append(('compose', text_or_empty(os.path.join(release, name))))
    for kind, text in texts:
        for commit in RELEASE_REF.findall(text):
            reasons_path.setdefault(commit, set()).add(kind)
    for name in ('state.json', 'current.json'):
        data = text_or_empty(ROOT + '/var/lib/metainc/naver-deploy/' + name)
        try:
            data = json.loads(data) if data else {}
        except ValueError:
            fail('CLEANUP_PLAN: %s 를 읽지 못했습니다' % name)
        for key, value in data.items():
            if key.endswith('commit') and isinstance(value, str) and HEX40.match(value):
                commits.setdefault(value, []).append('deploy-record')
    # 모든 컨테이너(실행·정지)가 쓰는 이미지 ID 와 bind 경로.
    code, out, _ = docker(['ps', '--all', '--no-trunc', '--format', '{{.ID}}'])
    if code:
        fail('CLEANUP_PLAN: docker ps 실패')
    used_images = set()
    for identity in out.split():
        rows = docker_json(['inspect', identity])
        for row in rows:
            used_images.add(row.get('Image'))
            for mount in row.get('Mounts') or []:
                for commit in RELEASE_REF.findall(str(mount.get('Source') or '')):
                    reasons_path.setdefault(commit, set()).add('container-mount')
    return commits, {c: sorted(r) for c, r in reasons_path.items()}, used_images


def build_plan():
    commits, path_refs, used_images = protected_state()
    lines = docker(['image', 'ls', '--no-trunc', '--format', '{{json .}}'])
    if lines[0]:
        fail('CLEANUP_PLAN: docker image ls 실패')
    tags = []
    for line in lines[1].splitlines():
        row = json.loads(line)
        if row.get('Repository') in NAVER_REPOS and HEX40.match(row.get('Tag') or ''):
            tags.append((row['Repository'], row['Tag'], row.get('ID')))
    protected_ids = set(used_images)
    for repository, tag, identity in tags:
        if tag in commits:
            protected_ids.add(identity)
    candidates, kept = [], {'protected_commits': sorted(commits), 'kept_images': 0, 'kept_releases': 0}
    sizes = {}
    for repository, tag, identity in sorted(tags):
        if tag in commits or identity in protected_ids:
            kept['kept_images'] += 1
            continue
        rows = docker_json(['image', 'inspect', repository + ':' + tag])
        if rows[0].get('Id') != identity:
            fail('CLEANUP_PLAN: 태그가 계산 중에 바뀌었습니다')
        sizes[repository + ':' + tag] = int(rows[0].get('Size') or 0)
        candidates.append({'type': 'image', 'ref': repository + ':' + tag, 'id': identity,
                           'size_bytes': sizes[repository + ':' + tag]})
    try:
        names = sorted(os.listdir(ROOT + RELEASES))
    except OSError:
        fail('CLEANUP_PLAN: releases 폴더를 읽지 못했습니다')
    for name in names:
        match = re.fullmatch(r'naver-([0-9a-f]{40})', name)
        path = RELEASES + '/' + name
        full = ROOT + path
        if not match or os.path.islink(full) or not os.path.isdir(full):
            continue
        if match.group(1) in commits or match.group(1) in path_refs:
            kept['kept_releases'] += 1
            continue
        candidates.append({'type': 'release', 'ref': path, 'id': '', 'size_bytes': tree_bytes(full)})
    canonical = json.dumps(sorted([c['type'], c['ref'], c['id']] for c in candidates), separators=(',', ':'))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    # 회수량 추정: docker system df -v 의 UniqueSize(이 이미지만 쓰는 층) 합 = 하한
    # (후보끼리만 공유하는 층은 빠진다), image inspect Size 합 = 상한(공유 층 포함). release 는 디스크 블록 합.
    unique_total, unique_known = 0, True
    code, out, _ = docker(['system', 'df', '-v', '--format', '{{json .}}'], timeout=300)
    by_ref = {}
    try:
        data = json.loads(out.strip().splitlines()[0]) if not code and out.strip() else None
        for row in (data or {}).get('Images') or []:
            by_ref[str(row.get('Repository')) + ':' + str(row.get('Tag'))] = human_bytes(row.get('UniqueSize'))
    except (ValueError, IndexError, AttributeError):
        by_ref = {}
    for candidate in candidates:
        if candidate['type'] == 'image':
            value = by_ref.get(candidate['ref'])
            if value is None:
                unique_known = False
            else:
                unique_total += value
    release_total = sum(c['size_bytes'] for c in candidates if c['type'] == 'release')
    image_upper = sum(c['size_bytes'] for c in candidates if c['type'] == 'image')
    estimate = {'method': 'images: sum of docker system df -v UniqueSize (lower bound; layers shared only among '
                          'candidates are not counted) and sum of docker image inspect Size (upper bound); '
                          'releases: sum of on-disk blocks',
                'images_unique_bytes_lower_bound': unique_total if unique_known else None,
                'images_size_bytes_upper_bound': image_upper, 'releases_bytes': release_total,
                'total_lower_bound': (unique_total + release_total) if unique_known else release_total,
                'total_upper_bound': image_upper + release_total}
    return {'candidates': candidates, 'allowlist_sha256': digest, 'kept': kept,
            'path_references': path_refs, 'reclaim_estimate': estimate,
            'counts': {'images': sum(1 for c in candidates if c['type'] == 'image'),
                       'releases': sum(1 for c in candidates if c['type'] == 'release')}}


def free_bytes():
    info = os.statvfs(ROOT + RELEASES if os.path.isdir(ROOT + RELEASES) else ROOT + '/')
    return info.f_bavail * info.f_frsize


def cleanup_plan():
    plan = build_plan()
    plan.update(mode='cleanup-plan', read_only=True, free_bytes=free_bytes(),
                generated_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    print('NAVER_DEPLOY_CLEANUP_PLAN=' + json.dumps(plan, sort_keys=True, separators=(',', ':')))


def cleanup(expected, private_log):
    """계획을 다시 세워 해시가 정확히 같을 때만, 그 목록만 지운다. 결과는 고정 형식 한 줄."""
    result = {'mode': 'cleanup', 'allowlist_sha256': expected, 'removed': [], 'refused': [], 'failed': [],
              'free_bytes_before': free_bytes()}

    def finish(status, code):
        result.update(status=status, exit_code=code, free_bytes_after=free_bytes())
        print('NAVER_DEPLOY_CLEANUP_RESULT=' + json.dumps(result, sort_keys=True, separators=(',', ':')))
        sys.exit(code)
    if not re.fullmatch(r'[0-9a-f]{64}', expected or ''):
        finish('REFUSED_BAD_INPUT', 10)
    try:
        plan = build_plan()
    except Refuse:
        finish('REFUSED_PLAN_FAILED', 10)
    result['planned_sha256'] = plan['allowlist_sha256']
    if plan['allowlist_sha256'] != expected:
        finish('REFUSED_HASH_MISMATCH', 10)
    log = open(private_log, 'a')
    for candidate in plan['candidates']:
        if candidate['type'] != 'image':
            continue
        # 지우기 직전 다시: 이 이미지(또는 그 위에 쌓인 이미지)로 만든 컨테이너가 하나도 없어야 한다.
        code, out, _ = docker(['ps', '--all', '--quiet', '--no-trunc', '--filter', 'ancestor=' + candidate['id']])
        if code or out.strip():
            result['refused'].append(candidate['ref'])
            continue
        code, out, err = docker(['image', 'rm', candidate['ref']])
        log.write('[image rm %s] exit %d\n%s%s' % (candidate['ref'], code, out[-2000:], err[-2000:]))
        if code == 0:
            result['removed'].append(candidate['ref'])
        elif 'conflict' in err.lower() or 'in use' in err.lower() or 'being used' in err.lower():
            result['refused'].append(candidate['ref'])
        else:
            result['failed'].append(candidate['ref'])
    try:
        commits, path_refs, _ = protected_state()
    except Refuse:
        commits, path_refs = None, None
    for candidate in plan['candidates']:
        if candidate['type'] != 'release':
            continue
        if commits is None:
            result['refused'].append(candidate['ref'])
            continue
        commit = candidate['ref'].rsplit('-', 1)[1]
        full = ROOT + candidate['ref']
        parent = os.path.dirname(full)
        if (commit in commits or commit in path_refs or os.path.islink(full) or not os.path.isdir(full)
                or os.path.islink(parent)
                or os.path.realpath(full) != os.path.join(os.path.realpath(parent), os.path.basename(full))
                or not re.fullmatch(re.escape(RELEASES) + r'/naver-[0-9a-f]{40}', candidate['ref'])):
            result['refused'].append(candidate['ref'])
            continue
        done = subprocess.run(['rm', '-r', '--', full], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log.write('[rm -r %s] exit %d\n%s' % (candidate['ref'], done.returncode, done.stderr.decode('utf-8', 'replace')[-2000:]))
        (result['removed'] if done.returncode == 0 else result['failed']).append(candidate['ref'])
    log.close()
    if result['refused'] or result['failed']:
        finish('PARTIAL', 5)
    finish('CLEANED', 0)


def sha(path):
    print(hashlib.sha256(read(path, 'rb')).hexdigest())


def tree_sha(folder):
    digest = hashlib.sha256()
    if os.path.isdir(folder):
        for current, children, files in os.walk(folder):
            children.sort()
            for name in sorted(files):
                full = os.path.join(current, name)
                digest.update(os.path.relpath(full, folder).encode() + b'\0')
                if os.path.isfile(full) and not os.path.islink(full):
                    digest.update(hashlib.sha256(read(full, 'rb')).digest())
    print(digest.hexdigest())


RESULT_FIELDS = {
    'mode': r'(inspect|deploy)', 'status': r'[A-Z_]{1,40}', 'exit_code': r'[0-9]{1,3}', 'reason': r'[A-Z_]{0,40}',
    'message': None, 'phase': r'[a-z_]{1,24}', 'new_commit': r'[0-9a-f]{40}|', 'previous_commit': r'[0-9a-f]{40}|',
    'new_engine_image': r'sha256:[0-9a-f]{64}|', 'new_relay_image': r'sha256:[0-9a-f]{64}|',
    'previous_engine_image': r'sha256:[0-9a-f]{64}|', 'previous_relay_image': r'sha256:[0-9a-f]{64}|',
    'db_backup': r'/var/backups/metainc/naver-deploy-db/[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}|',
    'downtime_seconds': r'[0-9]{0,6}', 'health_status': r'[a-z_]{0,32}',
    'health_codes': r'(engine=[0-9]{3},page=[0-9]{3},me=[0-9]{3})?', 'schema_current': r'[0-9]{0,6}',
    'schema_new': r'[0-9]{0,6}', 'switches': r'([a-z_]+=(true|false),?){0,12}', 'warnings': r'[A-Z_,]{0,400}',
    'services_stopped_confirmed': r'(true|false)?', 'database_opened_by_deploy': r'false',
    'runtime_env_changed_by_deploy': r'false'}
# 공개 로그로 나가는 유일한 줄. 모든 값은 위 형식만 통과하고, message 는 고정 문구표에서만 고른다.
MESSAGES = {
    'DEPLOYED': '배포 완료(헬스·60초 유지 통과)', 'DEPLOYED_WITH_WARNINGS': '배포 완료(헬스 통과), 마무리 경고 있음',
    'DEPLOY_FAILED_RESTORED': '새 판 실패 → 직전 판 복원·헬스 통과', 'RECOVERED_INTERRUPTED_RUN':
    '중단된 이전 배포를 직전 판으로 복원함. 다시 실행 필요', 'RESTORE_FAILED': '복원 실패. 두 서비스 정지 시도. 사람 확인 필요',
    'REFUSED': '시작 전 거부. 서비스는 그대로', 'LOCKED': '다른 관제 배포 실행 중', 'EXITED': '예상하지 못한 종료'}


def result_json(*pairs):
    data = {}
    for pair in pairs:
        key, _, value = pair.partition('=')
        pattern = RESULT_FIELDS.get(key, False)
        if pattern is False:
            continue
        if pattern is not None and not re.fullmatch(pattern, value):
            value = 'invalid'
        data[key] = int(value) if key == 'exit_code' and value.isdigit() else value
    data['message'] = MESSAGES.get(data.get('status'), '')
    print(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def prune_logs(folder, keep):
    names = sorted(name for name in os.listdir(folder) if re.fullmatch(r'commands-[0-9]{8}T[0-9]{6}Z\.log', name))
    for name in names[:-int(keep)] if len(names) > int(keep) else []:
        os.unlink(os.path.join(folder, name))


# ── inspect: 읽기 전용. 원문(unit·override·label·Env)은 내보내지 않고 정해진 사실만 낸다 ──────────
SAFE_NAME = re.compile(r'[A-Za-z0-9_.@-]{1,128}\Z')
SAFE_PATH = re.compile(r'/[A-Za-z0-9_./-]{0,250}\Z')
IMAGE_ID = re.compile(r'sha256:[0-9a-f]{64}\Z')
STAMP = re.compile(r'[0-9]{4}-?[0-9]{2}-?[0-9]{2}T[0-9:.]{6,20}Z?\Z')
PHASES = {'init', 'preflight', 'preparing', 'building', 'prepared', 'stopping', 'backing_up', 'switching', 'starting',
          'verifying', 'done', 'restoring', 'restored', 'restore_failed', 'aborted_before_stop'}


def pick(value, pattern):
    if value is None:
        return None
    value = str(value)
    return value if pattern.match(value) else 'unexpected'


def run(argv):
    try:
        done = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
    except Exception:
        return None
    return done.stdout.decode('utf-8', 'replace') if done.returncode == 0 else None


def show(unit):
    fields = ('ActiveState', 'SubState', 'MainPID', 'UnitFileState', 'NRestarts', 'FragmentPath', 'DropInPaths',
              'NeedDaemonReload')
    out = run(['systemctl', 'show', unit, '-p', ','.join(fields)])
    if out is None:
        return {'available': False}
    raw = dict(line.split('=', 1) for line in out.splitlines() if '=' in line)
    result = {'available': True}
    for key in ('ActiveState', 'SubState', 'UnitFileState', 'NeedDaemonReload'):
        result[key] = pick(raw.get(key, ''), re.compile(r'[a-z-]{0,32}\Z'))
    for key in ('MainPID', 'NRestarts'):
        result[key] = int(raw[key]) if raw.get(key, '').isdigit() else None
    result['fragment_expected'] = raw.get('FragmentPath') == '/etc/systemd/system/' + unit
    result['drop_in_count'] = len(raw.get('DropInPaths', '').split())
    return result


def unit_shape(name):
    """unit 파일에서 모양만 본다(값·Environment 내용은 내보내지 않는다)."""
    path = ROOT + '/etc/systemd/system/metainc-naver-' + name + '.service'
    try:
        text = read(path)
    except Exception as error:
        return {'readable': False, 'error': type(error).__name__}
    lines = text.splitlines()
    result = {'readable': True, 'environment_lines': sum(1 for l in lines if l.startswith('Environment=')),
              'exec_start_lines': sum(1 for l in lines if l.startswith('ExecStart=')),
              'exec_stop_lines': sum(1 for l in lines if l.startswith('ExecStop=')),
              'restart_always': 'Restart=always' in lines}
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            unit_parse(path, name)
        commit, companion = captured.getvalue().split()
        result.update(shape_ok=True, commit=commit, companion=None if companion == '-' else companion,
                      commit_count=text.count(commit),
                      compose_files=(['release:compose.naver-%s.yml' % name]
                                     + (['release:deploy/naver-engine-backup.override.yml'] if name == 'engine' else [])
                                     + ['release:preview-%s.override.yml' % name]
                                     + (['saved-exports-companion'] if companion != '-' else [])))
    except Refuse:
        # 거부 사유 문장에는 unit 원문 토큰이 섞일 수 있어 내보내지 않는다.
        result['shape_ok'] = False
        found = re.findall(r'releases/naver-([0-9a-f]{40})/', text)
        result['commits_seen'] = sorted(set(found))
    return result


def override_shape(path, name):
    try:
        text = read(ROOT + path)
    except Exception as error:
        return {'readable': False, 'error': type(error).__name__}
    keys, stack = [], []
    image = None
    for line in text.splitlines():
        match = re.match(r'^( *)([A-Za-z0-9_.-]+):(.*)$', line)
        if not match:
            continue
        depth = len(match.group(1)) // 2
        stack = stack[:depth] + [match.group(2)]
        keys.append('.'.join(stack))
        if match.group(2) == 'image':
            image = match.group(3).strip()
    return {'readable': True, 'keys': keys,
            'image': image if image and re.fullmatch(r'metainc/naver-%s:[0-9a-f]{40}' % name, image) else 'unexpected',
            'line_count': len(text.splitlines())}


def tmpfiles_shape():
    try:
        text = read(ROOT + '/etc/tmpfiles.d/metainc-naver-preview.conf')
    except Exception as error:
        return {'readable': False, 'error': type(error).__name__}
    rows, other = [], 0
    for line in text.splitlines():
        match = re.fullmatch(r'd (/run/metainc(?:/naver-(?:engine|relay))?) ([0-7]{4}) ([A-Za-z0-9_-]{1,32}) '
                             r'([A-Za-z0-9_-]{1,32}) -', line.strip())
        if match:
            rows.append(list(match.groups()))
        elif line.strip():
            other += 1
    return {'readable': True, 'directories': rows, 'other_lines': other}


def labels_shape(labels):
    labels = labels or {}
    known = {'com.docker.compose.project': re.compile(r'naver-[a-z-]{1,20}\Z'),
             'com.docker.compose.service': re.compile(r'naver-[a-z-]{1,20}\Z'),
             'metainc.naver.preview.source': re.compile(r'[0-9a-f]{40}\Z'),
             'metainc.naver.schema': re.compile(r'[0-9]{1,6}\Z')}
    result = {key: pick(labels.get(key), pattern) for key, pattern in known.items() if key in labels}
    result['other_label_count'] = sum(1 for key in labels if key not in known)
    return result


def container_rows(project):
    ids = (run(['docker', 'ps', '--all', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + project,
                '--format', '{{.ID}}']) or '').split()
    rows = []
    for identity in ids:
        try:
            row = json.loads(run(['docker', 'inspect', identity]))[0]
        except Exception:
            rows.append({'id': pick(identity, re.compile(r'[0-9a-f]{64}\Z')), 'inspect': False})
            continue
        state, config = row.get('State') or {}, row.get('Config') or {}
        host = row.get('HostConfig') or {}
        env = {}
        try:
            env = env_to_map(config.get('Env'))
            switches = canonical(switches_from_env(env))
        except Refuse:
            switches = 'invalid'
        rows.append({'id': pick(row.get('Id'), re.compile(r'[0-9a-f]{64}\Z')), 'image': pick(row.get('Image'), IMAGE_ID),
                     'user': pick(config.get('User'), re.compile(r'[0-9]{1,6}:[0-9]{1,6}\Z')),
                     'status': pick(state.get('Status'), re.compile(r'[a-z]{1,16}\Z')),
                     'running': bool(state.get('Running')), 'pid': state.get('Pid') if type(state.get('Pid')) is int else None,
                     'started_at': pick(state.get('StartedAt'), STAMP),
                     'restart_count': row.get('RestartCount') if type(row.get('RestartCount')) is int else None,
                     'labels': labels_shape(config.get('Labels')),
                     'restart_policy': pick((host.get('RestartPolicy') or {}).get('Name'), re.compile(r'[a-z-]{1,20}\Z')),
                     'network_mode': pick(host.get('NetworkMode'), re.compile(r'[a-z]{1,16}\Z')),
                     'mounts': [[pick(m.get('Type'), re.compile(r'[a-z]{1,10}\Z')), pick(m.get('Source'), SAFE_PATH),
                                 pick(m.get('Destination'), SAFE_PATH), bool(m.get('RW'))]
                                for m in row.get('Mounts') or []],
                     'switches': switches})
    return rows


def listing(path, name_pattern=SAFE_NAME):
    try:
        names = sorted(os.listdir(ROOT + path))
    except Exception as error:
        return {'readable': False, 'error': type(error).__name__}
    entries = []
    for name in names:
        try:
            info = os.lstat(os.path.join(ROOT + path, name))
        except OSError:
            continue
        kind = 'dir' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'other'
        entries.append({'name': pick(name, name_pattern), 'type': kind, 'size': info.st_size,
                        'mode': oct(stat.S_IMODE(info.st_mode)), 'uid': info.st_uid, 'gid': info.st_gid,
                        'mtime': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(info.st_mtime))})
    return {'readable': True, 'entries': entries}


def state_shape(path):
    try:
        data = json.loads(read(ROOT + path))
    except FileNotFoundError:
        return None
    except Exception as error:
        return {'readable': False, 'error': type(error).__name__}
    if isinstance(data, list):
        return [pick(item, re.compile(r'[0-9a-f]{40}\Z')) for item in data]
    patterns = {'phase': re.compile(r'[a-z_]{1,24}\Z'), 'reason': re.compile(r'[A-Z_]{1,40}\Z'),
                'schema': re.compile(r'[0-9]{1,6}\Z'), 'run_dir': SAFE_PATH, 'started_at': STAMP, 'updated_at': STAMP,
                'deployed_at': STAMP, 'companion': re.compile(r'(-|/[A-Za-z0-9_./-]{1,250})\Z'),
                'switches': re.compile(r'([a-z_]+=(true|false),?){1,12}\Z')}
    result = {}
    for key, value in sorted(data.items()):
        if key.endswith('commit'):
            result[key] = pick(value, re.compile(r'[0-9a-f]{40}\Z'))
        elif key.endswith('image'):
            result[key] = pick(value, IMAGE_ID)
        elif key in patterns:
            result[key] = pick(value, patterns[key])
    return result


def version(argv, pattern):
    out = run(argv)
    match = re.search(pattern, out or '')
    return match.group(1) if match else None


def inspect():
    out = {'mode': 'inspect', 'read_only': True, 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    try:
        import pwd
        user = pwd.getpwuid(os.geteuid()).pw_name
    except Exception:
        user = None
    out['id'] = {'uid': os.geteuid(), 'gid': os.getegid(), 'user': pick(user, SAFE_NAME), 'root': os.geteuid() == 0}
    disks = {}
    for path in ('/', '/var/lib/metainc', '/var/backups/metainc', '/var/lib/docker', '/srv/metainc'):
        try:
            info = os.statvfs(ROOT + path)
            disks[path] = {'total_gb': round(info.f_blocks * info.f_frsize / 2 ** 30, 2),
                           'free_gb': round(info.f_bavail * info.f_frsize / 2 ** 30, 2)}
        except OSError as error:
            disks[path] = {'error': type(error).__name__}
    out['disk'] = disks
    out['tools'] = {'python': sys.version.split()[0],
                    'docker': version(['docker', 'version', '--format', '{{.Server.Version}}'], r'^([0-9][0-9A-Za-z.+-]{0,40})'),
                    'compose': version(['docker', 'compose', 'version', '--short'], r'^v?([0-9][0-9A-Za-z.+-]{0,40})'),
                    'systemd': version(['systemctl', '--version'], r'^systemd ([0-9]{1,4})\b'),
                    'curl': bool(shutil.which('curl')), 'flock': bool(shutil.which('flock')),
                    'systemd_run': bool(shutil.which('systemd-run'))}
    out['units'] = {unit: show(unit) for unit in ('metainc-naver-engine.service', 'metainc-naver-relay.service',
                                                  'metainc-naver-erp-tunnel.service', 'docker.service')}
    out['unit_shapes'] = {name: unit_shape(name) for name in ('engine', 'relay')}
    out['tmpfiles_conf'] = tmpfiles_shape()
    commit = out['unit_shapes']['engine'].get('commit')
    try:
        names = sorted(os.listdir(ROOT + RELEASES))
        out['releases'] = {'naver': [n for n in names if re.fullmatch(r'naver-[0-9a-f]{40}', n)],
                           'other_count': sum(1 for n in names if not re.fullmatch(r'naver-[0-9a-f]{40}', n))}
    except Exception as error:
        out['releases'] = {'readable': False, 'error': type(error).__name__}
    if commit:
        release = RELEASES + '/naver-' + commit
        current = {'path': release,
                   'overrides': {name: override_shape(release + '/preview-' + name + '.override.yml', name)
                                 for name in ('engine', 'relay')}}
        try:
            info = os.lstat(ROOT + release)
            current.update(mode=oct(stat.S_IMODE(info.st_mode)), uid=info.st_uid)
            current['schema_version'] = schema_of(read(ROOT + release + '/naver_engine/store.py'))
        except (OSError, Refuse) as error:
            current['schema_version'] = {'error': type(error).__name__}
        try:
            row = json.loads(run(['docker', 'image', 'inspect', 'metainc/naver-engine:' + commit]))[0]
            current['engine_image'] = {'id': pick(row.get('Id'), IMAGE_ID),
                                       'labels': labels_shape((row.get('Config') or {}).get('Labels'))}
        except Exception:
            current['engine_image'] = None
        out['current_release'] = current
    images = []
    for line in (run(['docker', 'image', 'ls', '--no-trunc', '--filter', 'reference=metainc/naver-*',
                      '--format', '{{json .}}']) or '').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        images.append({'repository': pick(row.get('Repository'), re.compile(r'metainc/naver-[a-z-]{1,20}\Z')),
                       'tag': pick(row.get('Tag'), SAFE_NAME), 'id': pick(row.get('ID'), IMAGE_ID)})
    out['images'] = images
    out['containers'] = {project: container_rows(project) for project in ('naver-engine', 'naver-relay')}
    out['data_dir'] = listing('/var/lib/metainc/naver-engine')
    out['db_backups'] = listing('/var/backups/metainc/naver-deploy-db', BACKUP_DIR_NAME)
    out['deploy_state'] = {name: state_shape('/var/lib/metainc/naver-deploy/' + name + '.json')
                           for name in ('state', 'current', 'history')}
    print('NAVER_DEPLOY_INSPECT=' + json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


COMMANDS = {'unit-parse': unit_parse, 'override-check': override_check, 'subst': subst, 'tar-check': tar_check,
            'tar-extract': tar_extract, 'tree-compare': tree_compare, 'image-info': image_info,
            'container-info': container_info, 'state-write': state_write,
            'state-get': state_get, 'history-add': history_add, 'prune-list': prune_list,
            'prune-history': prune_history, 'db-files': db_files, 'same-size': same_size,
            'backup-prune': backup_prune, 'sha': sha, 'tree-sha': tree_sha, 'result-json': result_json,
            'inspect': inspect, 'verify-copy': verify_copy, 'partial-prune': partial_prune,
            'disk-budget': disk_budget, 'image-sizes': image_sizes, 'cleanup-plan': cleanup_plan, 'cleanup': cleanup, 'env-switches': env_switches, 'container-mounts': container_mounts,
            'compose-shape': compose_shape, 'shape-diff': shape_diff, 'check-config-run': check_config_run,
            'prune-logs': prune_logs,
            'schema-file': lambda path: print(schema_of(read(path))),
            'schema-tar-stdin': lambda: print(schema_of(tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()))
                                                        .extractfile('store.py').read().decode('utf-8'))),
            'randhex': lambda: print(secrets.token_hex(16))}
if __name__ == '__main__':
    try:
        COMMANDS[sys.argv[1]](*sys.argv[2:])
    except Refuse as error:
        # 거부 사유는 stdout 으로 낸다: 호출하는 셸이 $(...) 로 받아 그대로 보고한다.
        print(str(error))
        sys.exit(1)
PYEOF
)

py() { python3 -I -B -c "$PY_HELPER" "$@"; }

# docker 는 깨끗한 환경으로 부른다(compose 변수 보간이 ssh 세션 변수에 흔들리지 않게).
dk() { env -i PATH="$PATH" LANG=C docker "$@"; }

log() { printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

# ── 결과 보고 ───────────────────────────────────────────────────────────────
# 공개 로그로 나가는 것은 결과 한 줄(NAVER_DEPLOY_RESULT)뿐이다. 그 줄은 helper 가 필드별 형식으로
# 걸러 내고 문구는 고정표에서 고른다. 자세한 사유·명령 출력은 서버의 비공개 로그에만 남는다.
MODE="${1:-}"
LOG_FILE=''
RESULT_FILE=''
RESULT_CODE=''
RESULT_STATUS=''
RESULT_REASON=''
PHASE='init'
NEW=''
PREV_COMMIT=''
PREV_ENGINE_IMAGE=''
PREV_RELAY_IMAGE=''
NEW_ENGINE_IMAGE=''
NEW_RELAY_IMAGE=''
DB_BACKUP=''
WARNINGS=''
STOP_STARTED=''
DOWNTIME=''
HEALTH_STATUS=''
HEALTH_CODES=''
SCHEMA_CUR=''
SCHEMA_NEW=''
CUR_SWITCHES=''
STOPPED_CONFIRMED=''
STATE_FILE="$R$STATE_DIR/state.json"
CMD_LOG=/dev/null
HAVE_STATE=0
RESTORING=0

warn() { # CODE detail
  log "주의($1): $2"
  WARNINGS="${WARNINGS}${WARNINGS:+,}$1"
}

write_result() {
  local line
  line=$(py result-json "mode=$MODE" "status=${RESULT_STATUS:-EXITED}" "exit_code=${RESULT_CODE:-1}" \
    "reason=$RESULT_REASON" "phase=$PHASE" "new_commit=$NEW" "previous_commit=$PREV_COMMIT" \
    "new_engine_image=$NEW_ENGINE_IMAGE" "new_relay_image=$NEW_RELAY_IMAGE" \
    "previous_engine_image=$PREV_ENGINE_IMAGE" "previous_relay_image=$PREV_RELAY_IMAGE" \
    "db_backup=$DB_BACKUP" "downtime_seconds=$DOWNTIME" "health_status=$HEALTH_STATUS" \
    "health_codes=$HEALTH_CODES" "schema_current=$SCHEMA_CUR" "schema_new=$SCHEMA_NEW" \
    "switches=$CUR_SWITCHES" "warnings=$WARNINGS" "services_stopped_confirmed=$STOPPED_CONFIRMED" \
    "database_opened_by_deploy=false" "runtime_env_changed_by_deploy=false" 2>/dev/null) \
    || line='{"status":"RESULT_WRITE_FAILED"}'
  printf 'NAVER_DEPLOY_RESULT=%s\n' "$line"
  if [ -n "$RESULT_FILE" ]; then
    printf '%s\n' "$line" > "$RESULT_FILE.tmp" && mv -f "$RESULT_FILE.tmp" "$RESULT_FILE"
  fi
}

on_exit() {
  local rc=$?
  trap - EXIT ERR
  if [ "$MODE" = deploy ]; then
    if [ -z "$RESULT_CODE" ]; then
      RESULT_CODE=$rc
      RESULT_STATUS=${RESULT_STATUS:-EXITED}
    fi
    write_result || true
    exit "$RESULT_CODE"
  fi
  exit "$rc"
}

finish() { # exit-code status reason detail
  RESULT_CODE=$1
  RESULT_STATUS=$2
  RESULT_REASON=$3
  log "결과: $2 ($3) — $4"
  exit "$1"
}

set_phase() {
  PHASE=$1
  if [ "$HAVE_STATE" = 1 ]; then
    py state-write "$STATE_FILE" "phase=$1"
  fi
  log "단계: $1"
}

phase_needs_restore() {
  case "$1" in
    stopping|backing_up|switching|starting|verifying|restoring|restore_failed) return 0 ;;
    *) return 1 ;;
  esac
}

# 실패 처리: 서비스를 멈추기 전이면 거부(아무것도 안 바뀜), 멈춘 뒤면 직전 판으로 복원.
fail_deploy() { # CODE detail
  trap - ERR
  set +e
  log "실패 사유($1): $2"
  if [ "$RESTORING" = 1 ]; then
    finish 4 RESTORE_FAILED "$1" "$2"
  fi
  if [ "$PHASE" = 'done' ]; then
    # 새 판은 이미 헬스를 통과했다. 기록·이미지 정리 같은 마무리 실패는 경고로만 남긴다.
    warn "$1" "마무리 정리 중 실패: $2"
    finish 0 DEPLOYED_WITH_WARNINGS "$1" "배포 완료, 마무리 경고"
  fi
  if [ "$HAVE_STATE" = 1 ] && phase_needs_restore "$PHASE"; then
    log "직전 판 $PREV_COMMIT 으로 복원합니다"
    if restore_previous; then
      finish 2 DEPLOY_FAILED_RESTORED "$1" "직전 판 $PREV_COMMIT 복원·헬스 통과"
    fi
    finish 4 RESTORE_FAILED "$1" "복원 실패. 정지 확인=$STOPPED_CONFIRMED"
  fi
  if [ "$HAVE_STATE" = 1 ]; then
    py state-write "$STATE_FILE" "phase=aborted_before_stop" "reason=$1" || true
    PHASE=aborted_before_stop
  fi
  finish 10 REFUSED "$1" "서비스는 건드리지 않았습니다"
}

die() { fail_deploy "$1" "$2"; }

on_error() {
  local rc=$1 line=$2
  # $(...)·파이프 안의 하위 셸에서는 그 하위 셸만 끝낸다. 판단은 바깥 셸이 한다.
  if [ "${BASH_SUBSHELL:-0}" != 0 ]; then
    exit "$rc"
  fi
  fail_deploy COMMAND_FAILED "명령 실패(종료 $rc, 줄 $line, 단계 $PHASE)"
}

on_signal() {
  if [ "${BASH_SUBSHELL:-0}" != 0 ]; then
    exit 1
  fi
  fail_deploy INTERRUPTED "신호 $1 을 받았습니다(단계 $PHASE)"
}

# ── systemd·docker 작은 도우미 ─────────────────────────────────────────────
unit_prop() { systemctl show "$1" -p "$2" --value; }

container_ids() { # project
  dk ps --all --no-trunc --filter "label=com.docker.compose.project=$1" --format '{{.ID}}'
}

# 한 project 의 컨테이너가 정확히 하나일 때 그 정보를 C_* 변수로 채운다.
read_container() { # project
  local project=$1 ids info
  ids=$(container_ids "$project") || return 1
  # shellcheck disable=SC2086
  set -- $ids
  if [ "$#" != 1 ]; then
    log "$project 컨테이너 수가 $# 입니다(1이어야 함)"
    return 1
  fi
  info=$(dk inspect "$1" | py container-info) || return 1
  IFS='|' read -r C_ID C_IMAGE C_RUNNING _ _ C_STARTED C_RESTARTS C_PROJECT C_SERVICE C_EXEC C_USER <<EOF
$info
EOF
  : "$C_EXEC"
  C_SWITCHES=$(dk inspect "$C_ID" | py env-switches) || return 1
  C_MOUNTS=$(dk inspect "$C_ID" | py container-mounts) || return 1
  return 0
}

project_stopped() { # project — 컨테이너가 없거나 모두 멈춤(PID 0)
  local ids id info running restarting pid rest
  ids=$(container_ids "$1") || return 1
  for id in $ids; do
    info=$(dk inspect "$id" | py container-info) || return 1
    IFS='|' read -r _ _ running restarting pid rest <<EOF
$info
EOF
    : "$rest"
    if [ "$running" != false ] || [ "$restarting" != false ] || [ "$pid" != 0 ]; then
      return 1
    fi
  done
  return 0
}

stopped_confirmed() { # unit project
  local state pid
  state=$(unit_prop "$1" ActiveState) || return 1
  pid=$(unit_prop "$1" MainPID) || return 1
  { [ "$state" = inactive ] || [ "$state" = failed ]; } && [ "$pid" = 0 ] && project_stopped "$2"
}

stop_and_wait() { # unit project
  local deadline
  log "정지: $1"
  systemctl stop "$1" 2>>"$CMD_LOG" || log "systemctl stop $1 실패"
  deadline=$((SECONDS + ${STOP_TIMEOUT%.*}))
  while :; do
    if stopped_confirmed "$1" "$2"; then
      log "정지 확인: $1 (MainPID 0, 컨테이너 PID 0)"
      return 0
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      log "정지 확인 실패: $1"
      return 1
    fi
    sleep "$POLL"
  done
}

http_code() { # socket path
  local code
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 --unix-socket "$R$1" \
    -H "Host: $HOST_HEADER" -H "Origin: https://$HOST_HEADER" -H 'X-Real-IP: 127.0.0.1' \
    "http://localhost$2" 2>/dev/null) || code=000
  case "$code" in
    [0-9][0-9][0-9]) printf '%s' "$code" ;;
    *) printf '000' ;;
  esac
}

probe_once() {
  P_ENGINE=$(http_code "$ENGINE_SOCK" /_engine/health)
  P_PAGE=$(http_code "$RELAY_SOCK" /naver/)
  P_ME=$(http_code "$RELAY_SOCK" /api/naver-auto/me)
  HEALTH_CODES="engine=$P_ENGINE,page=$P_PAGE,me=$P_ME"
  [ "$P_ENGINE" = 200 ] && [ "$P_PAGE" = 200 ] && [ "$P_ME" = 401 ]
}

health_fail() { # status detail
  HEALTH_STATUS=$1
  log "헬스 실패($1): $2"
  return 1
}

# 헬스체크: 준비(시간 제한) → 60초 유지(unit active, RestartCount 0, StartedAt 불변) → 마지막 확인.
health_check() { # engine_image relay_image
  local deadline e_id e_start e_pid e_nr r_id r_start r_pid r_nr end
  HEALTH_STATUS=checking
  deadline=$((SECONDS + ${READY_TIMEOUT%.*}))
  until probe_once; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      health_fail ready_timeout "$HEALTH_CODES"
      return 1
    fi
    sleep "$POLL"
  done
  if [ -n "$STOP_STARTED" ] && [ -z "$DOWNTIME" ]; then
    DOWNTIME=$((SECONDS - STOP_STARTED))
  fi
  log "헬스 준비: $HEALTH_CODES"
  read_container naver-engine || { health_fail container_state "engine 컨테이너 확인 실패"; return 1; }
  if [ "$C_IMAGE" != "$1" ] || [ "$C_RUNNING" != true ] || [ "$C_RESTARTS" != 0 ]; then
    health_fail container_state "engine image=$C_IMAGE running=$C_RUNNING restarts=$C_RESTARTS"
    return 1
  fi
  e_id=$C_ID; e_start=$C_STARTED
  read_container naver-relay || { health_fail container_state "relay 컨테이너 확인 실패"; return 1; }
  if [ "$C_IMAGE" != "$2" ] || [ "$C_RUNNING" != true ] || [ "$C_RESTARTS" != 0 ]; then
    health_fail container_state "relay image=$C_IMAGE running=$C_RUNNING restarts=$C_RESTARTS"
    return 1
  fi
  r_id=$C_ID; r_start=$C_STARTED
  e_pid=$(unit_prop "$ENGINE_UNIT" MainPID) || return 1
  e_nr=$(unit_prop "$ENGINE_UNIT" NRestarts) || return 1
  r_pid=$(unit_prop "$RELAY_UNIT" MainPID) || return 1
  r_nr=$(unit_prop "$RELAY_UNIT" NRestarts) || return 1
  log "유지 확인 ${HOLD_SECONDS}초 시작 (engine StartedAt=$e_start, relay StartedAt=$r_start)"
  end=$((SECONDS + ${HOLD_SECONDS%.*}))
  while [ "$SECONDS" -lt "$end" ]; do
    sleep "$HOLD_POLL"
    if [ "$(unit_prop "$ENGINE_UNIT" ActiveState)" != active ] || [ "$(unit_prop "$RELAY_UNIT" ActiveState)" != active ] \
      || [ "$(unit_prop "$ENGINE_UNIT" MainPID)" != "$e_pid" ] || [ "$(unit_prop "$RELAY_UNIT" MainPID)" != "$r_pid" ] \
      || [ "$(unit_prop "$ENGINE_UNIT" NRestarts)" != "$e_nr" ] || [ "$(unit_prop "$RELAY_UNIT" NRestarts)" != "$r_nr" ]; then
      health_fail unit_restarted "유지 중 unit 이 active 가 아니거나 재시작됨"
      return 1
    fi
    read_container naver-engine || { health_fail container_state "유지 중 engine 확인 실패"; return 1; }
    if [ "$C_ID" != "$e_id" ] || [ "$C_STARTED" != "$e_start" ] || [ "$C_RESTARTS" != 0 ] || [ "$C_RUNNING" != true ]; then
      health_fail container_restarted "유지 중 engine 재시작 감지(StartedAt $e_start → $C_STARTED, RestartCount $C_RESTARTS)"
      return 1
    fi
    read_container naver-relay || { health_fail container_state "유지 중 relay 확인 실패"; return 1; }
    if [ "$C_ID" != "$r_id" ] || [ "$C_STARTED" != "$r_start" ] || [ "$C_RESTARTS" != 0 ] || [ "$C_RUNNING" != true ]; then
      health_fail container_restarted "유지 중 relay 재시작 감지(StartedAt $r_start → $C_STARTED, RestartCount $C_RESTARTS)"
      return 1
    fi
  done
  if ! probe_once; then
    health_fail final_probe_failed "$HEALTH_CODES"
    return 1
  fi
  HEALTH_STATUS=passed
  log "헬스 통과: $HEALTH_CODES hold=${HOLD_SECONDS}s restarts=0"
  return 0
}

compose_args() { # name release companion → CARGS
  CARGS=(compose --project-name "naver-$1" -f "$R$2/compose.naver-$1.yml")
  if [ "$1" = engine ]; then
    CARGS+=(-f "$R$2/deploy/naver-engine-backup.override.yml")
  fi
  CARGS+=(-f "$R$2/preview-$1.override.yml")
  if [ "$1" = engine ] && [ "$3" != - ]; then
    CARGS+=(-f "$R$3")
  fi
}

# compose config(JSON)에서 관제의 작은 설정 묶음(mount·user·restart·서비스 목록)만 뽑는다.
# JSON 에는 runtime.env 값이 섞여 있으므로 파이프로만 넘기고 파일·로그에 남기지 않는다.
compose_shape() { # name release companion
  compose_args "$1" "$2" "$3"
  dk "${CARGS[@]}" config --format json 2>>"$CMD_LOG" | py compose-shape
}

write_file_atomic() { # source target mode
  cp "$1" "$2.naver-deploy.tmp"
  chmod "$3" "$2.naver-deploy.tmp"
  mv -f "$2.naver-deploy.tmp" "$2"
}

load_state() {
  PREV_COMMIT=$(py state-get "$STATE_FILE" prev_commit)
  NEW=${NEW:-$(py state-get "$STATE_FILE" new_commit)}
  PREV_ENGINE_IMAGE=$(py state-get "$STATE_FILE" prev_engine_image)
  PREV_RELAY_IMAGE=$(py state-get "$STATE_FILE" prev_relay_image)
  NEW_ENGINE_IMAGE=$(py state-get "$STATE_FILE" new_engine_image)
  NEW_RELAY_IMAGE=$(py state-get "$STATE_FILE" new_relay_image)
  CUR_SWITCHES=$(py state-get "$STATE_FILE" switches)
  S_RUN_DIR=$(py state-get "$STATE_FILE" run_dir)
  S_COMPANION=$(py state-get "$STATE_FILE" companion)
  S_PREV_REL="$RELEASES/naver-$PREV_COMMIT"
  if [ -n "$S_RUN_DIR" ] && [ -d "$R$S_RUN_DIR" ]; then
    CMD_LOG="$R$S_RUN_DIR/commands.log"
  fi
}

# 복원 실패 마무리: 두 서비스 정지를 시도하고, 실제로 멈췄는지 확인한 결과만 보고한다.
stop_both_and_confirm() {
  local ok=true
  stop_and_wait "$RELAY_UNIT" naver-relay || ok=false
  stop_and_wait "$ENGINE_UNIT" naver-engine || ok=false
  STOPPED_CONFIRMED=$ok
  log "정지 확인 결과: $ok"
}

# ── 복원: 기록(state.json + run 폴더 사본)만으로 직전 판을 되살린다 ───────────────
restore_previous() {
  local name unit saved target image prev_mounts ok=1
  RESTORING=1
  set +e
  trap - ERR
  load_state
  PHASE=restoring
  py state-write "$STATE_FILE" "phase=restoring"
  log "== 복원: 직전 판 $PREV_COMMIT (engine $PREV_ENGINE_IMAGE, relay $PREV_RELAY_IMAGE)"
  if [ -z "$PREV_COMMIT" ] || [ -z "$PREV_ENGINE_IMAGE" ] || [ -z "$PREV_RELAY_IMAGE" ] || [ ! -d "$R$S_RUN_DIR" ]; then
    log "복원 기록이 불완전합니다"
    ok=0
  fi
  if [ "$ok" = 1 ]; then
    stop_and_wait "$RELAY_UNIT" naver-relay || ok=0
    stop_and_wait "$ENGINE_UNIT" naver-engine || ok=0
  fi
  if [ "$ok" = 1 ]; then
    for name in engine relay; do
      unit="metainc-naver-$name.service"
      saved="$R$S_RUN_DIR/$unit"
      target="$R$UNIT_DIR/$unit"
      if [ "$(py sha "$saved")" != "$(py sha "$target")" ]; then
        log "unit 복원: $unit"
        write_file_atomic "$saved" "$target" 644 || ok=0
      fi
      saved="$R$S_RUN_DIR/preview-$name.override.yml"
      target="$R$S_PREV_REL/preview-$name.override.yml"
      if [ ! -f "$target" ] || [ "$(py sha "$saved")" != "$(py sha "$target")" ]; then
        log "override 복원: $target"
        write_file_atomic "$saved" "$target" 600 || ok=0
      fi
    done
  fi
  if [ "$ok" = 1 ]; then
    for name in engine relay; do
      if [ "$name" = engine ]; then image=$PREV_ENGINE_IMAGE; else image=$PREV_RELAY_IMAGE; fi
      if ! dk image inspect "$image" >/dev/null 2>>"$CMD_LOG"; then
        log "직전 이미지가 없습니다: $image"
        ok=0
      else
        dk tag "$image" "metainc/naver-$name:$PREV_COMMIT" >>"$CMD_LOG" 2>&1 || ok=0
      fi
    done
  fi
  if [ "$ok" = 1 ]; then
    systemctl daemon-reload 2>>"$CMD_LOG" || ok=0
  fi
  if [ "$ok" = 1 ]; then
    for name in engine relay; do
      compose_args "$name" "$S_PREV_REL" "$S_COMPANION"
      dk "${CARGS[@]}" up --no-start --no-build --force-recreate >>"$CMD_LOG" 2>&1 || { ok=0; break; }
    done
  fi
  if [ "$ok" = 1 ]; then
    for name in engine relay; do
      if [ "$name" = engine ]; then image=$PREV_ENGINE_IMAGE; else image=$PREV_RELAY_IMAGE; fi
      prev_mounts=$(cat "$R$S_RUN_DIR/mounts-$name.json" 2>/dev/null)
      if ! read_container "naver-$name" || [ "$C_IMAGE" != "$image" ] || [ "$C_MOUNTS" != "$prev_mounts" ]; then
        log "복원 컨테이너 $name 의 이미지·mount 가 기록과 다릅니다"
        ok=0
      elif [ "$name" = engine ] && [ "$C_SWITCHES" != "$CUR_SWITCHES" ]; then
        log "복원 컨테이너 스위치가 기록과 다릅니다"
        ok=0
      fi
    done
  fi
  if [ "$ok" = 1 ]; then
    systemctl start "$ENGINE_UNIT" 2>>"$CMD_LOG" || ok=0
  fi
  if [ "$ok" = 1 ]; then
    systemctl start "$RELAY_UNIT" 2>>"$CMD_LOG" || ok=0
  fi
  if [ "$ok" = 1 ] && health_check "$PREV_ENGINE_IMAGE" "$PREV_RELAY_IMAGE"; then
    PHASE=restored
    py state-write "$STATE_FILE" "phase=restored"
    log "== 복원 완료: $PREV_COMMIT 헬스 통과"
    RESTORING=0
    return 0
  fi
  log "== 복원 실패: 두 서비스를 정지하고 정지를 확인합니다(엔진이 잘못된 판으로 계속 쓰지 않게)"
  stop_both_and_confirm
  PHASE=restore_failed
  py state-write "$STATE_FILE" "phase=restore_failed" "stopped_confirmed=$STOPPED_CONFIRMED"
  RESTORING=0
  return 1
}

# 이전 실행이 서비스를 멈춘 뒤 끝나지 못했으면(SSH 끊김·재부팅·강제 종료) 먼저 직전 판으로 복원한다.
recover_if_needed() {
  local phase
  [ -f "$STATE_FILE" ] || return 0
  phase=$(py state-get "$STATE_FILE" phase)
  if phase_needs_restore "$phase"; then
    HAVE_STATE=1
    PHASE=$phase
    log "이전 실행이 단계 '$phase' 에서 끝나지 못했습니다 — 기록으로 직전 판을 복원합니다"
    NEW=''
    if restore_previous; then
      finish 3 RECOVERED_INTERRUPTED_RUN INTERRUPTED_RUN "직전 판 $PREV_COMMIT 으로 복원"
    fi
    finish 4 RESTORE_FAILED INTERRUPTED_RUN "복원 실패. 정지 확인=$STOPPED_CONFIRMED"
  fi
  case "$phase" in
    preparing|building|prepared)
      log "이전 실행이 서비스를 멈추기 전($phase)에 끝났습니다 — 바뀐 것이 없어 계속합니다"
      py state-write "$STATE_FILE" "phase=aborted_before_stop"
      ;;
  esac
}

# ── inspect ─────────────────────────────────────────────────────────────────
main_inspect() {
  py inspect
}

# ── cleanup: cleanup-plan 이 낸 allowlist_sha256 과 다시 계산한 계획이 정확히 같을 때만 그 목록만 지운다 ──
cleanup_refuse() { # status exit-code
  printf 'NAVER_DEPLOY_CLEANUP_RESULT={"exit_code":%s,"mode":"cleanup","status":"%s"}\n' "$2" "$1"
  exit "$2"
}

main_cleanup() {
  local expected=$1 phase stamp
  printf '%s' "$expected" | grep -Eq '^[0-9a-f]{64}$' || cleanup_refuse REFUSED_BAD_INPUT 10
  if [ "$TEST_MODE" = 0 ] && [ "$(id -u)" != 0 ]; then
    cleanup_refuse REFUSED_NOT_ROOT 10
  fi
  mkdir -p "$R$STATE_DIR/logs"
  chmod 700 "$R$STATE_DIR" "$R$STATE_DIR/logs"
  exec 9>>"$R$STATE_DIR/lock"
  flock -n 9 || cleanup_refuse LOCKED 11
  phase=$(py state-get "$STATE_FILE" phase 2>/dev/null) || phase=''
  if phase_needs_restore "$phase"; then
    cleanup_refuse REFUSED_DEPLOY_NOT_FINISHED 10
  fi
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  CMD_LOG="$R$STATE_DIR/logs/commands-$stamp.log"
  : > "$CMD_LOG"
  py prune-logs "$R$STATE_DIR/logs" 10
  py cleanup "$expected" "$CMD_LOG"
}

# ── deploy ──────────────────────────────────────────────────────────────────
main_deploy() {
  local tar_path cur cur_r companion name info id user src label unit
  local rel_new rel_cur run_dir stamp sum_runtime sum_tmpfiles sum_tunnel sum_nginx size files f
  local override cid new_switches shape_old shape_new build_need docker_root
  NEW=${1:-}
  tar_path=${2:-}
  printf '%s' "$NEW" | grep -Eq '^[0-9a-f]{40}$' || { NEW=''; die BAD_INPUT "커밋은 40자리 소문자 16진수여야 합니다"; }
  [ -f "$tar_path" ] || die BAD_INPUT "source.tar 가 없습니다"
  for f in docker systemctl curl python3 flock; do
    command -v "$f" >/dev/null || die MISSING_TOOL "$f 명령이 없습니다"
  done
  if [ "$TEST_MODE" = 0 ] && [ "$(id -u)" != 0 ]; then
    die NOT_ROOT "deploy 는 root 로 실행해야 합니다(unit·docker·root 전용 폴더)"
  fi
  [ -d "$R/var/lib/metainc" ] || die LAYOUT "/var/lib/metainc 가 없습니다"
  mkdir -p "$R$STATE_DIR/runs" "$R$STATE_DIR/logs"
  chmod 700 "$R$STATE_DIR" "$R$STATE_DIR/logs"

  # 직렬화: 같은 서버에서 두 배포가 겹치지 않게.
  exec 9>>"$R$STATE_DIR/lock"
  if ! flock -n 9; then
    RESULT_CODE=11
    RESULT_STATUS=LOCKED
    RESULT_REASON=LOCKED
    log "결과: LOCKED — 다른 naver-deploy 가 실행 중입니다"
    exit 11
  fi
  log "잠금 획득: $STATE_DIR/lock"
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  # docker build·compose 등 명령의 원문 출력(비공개 소스 발췌가 섞일 수 있음)은 이 비공개 파일에만 쓴다.
  CMD_LOG="$R$STATE_DIR/logs/commands-$stamp.log"
  : > "$CMD_LOG"
  py prune-logs "$R$STATE_DIR/logs" 10

  recover_if_needed

  # ── 1. 현재 배치 확인(모르는 모양이면 거부) ──
  PHASE=preflight
  log "단계: preflight"
  for unit in "$ENGINE_UNIT" "$RELAY_UNIT"; do
    [ -f "$R$UNIT_DIR/$unit" ] || die LAYOUT "$UNIT_DIR/$unit 이 없습니다"
    [ -z "$(unit_prop "$unit" DropInPaths)" ] || die LAYOUT "$unit 에 drop-in 이 있습니다(예상하지 못한 배치)"
    [ "$(unit_prop "$unit" FragmentPath)" = "$UNIT_DIR/$unit" ] || die LAYOUT "$unit FragmentPath 가 $UNIT_DIR 가 아닙니다"
    [ "$(unit_prop "$unit" ActiveState)" = active ] || die NOT_ACTIVE "$unit 이 active 가 아닙니다"
    [ "$(unit_prop "$unit" UnitFileState)" = enabled ] || die LAYOUT "$unit 이 enabled 가 아닙니다"
  done
  for unit in docker.service "$TUNNEL_UNIT"; do
    [ "$(unit_prop "$unit" ActiveState)" = active ] || die NOT_ACTIVE "$unit 이 active 가 아닙니다"
  done
  [ -f "$R$TMPFILES_CONF" ] || die LAYOUT "$TMPFILES_CONF 가 없습니다"
  info=$(py unit-parse "$R$UNIT_DIR/$ENGINE_UNIT" engine) || die LAYOUT "$info"
  cur=${info% *}; companion=${info#* }
  info=$(py unit-parse "$R$UNIT_DIR/$RELAY_UNIT" relay) || die LAYOUT "$info"
  [ "${info% *}" = "$cur" ] || die LAYOUT "engine($cur)과 relay(${info% *}) unit 이 다른 판을 가리킵니다"
  if [ "$companion" != - ]; then
    [ -f "$R$companion" ] || die LAYOUT "saved-exports companion 파일이 없습니다: $companion"
  fi
  PREV_COMMIT=$cur
  rel_cur="$RELEASES/naver-$cur"
  cur_r="$R$rel_cur"
  [ "$NEW" != "$cur" ] || die ALREADY_RUNNING "$NEW 는 이미 실행 중인 판입니다"
  for name in engine relay; do
    info=$(py override-check "$cur_r/preview-$name.override.yml" "$name" "$cur") || die LAYOUT "$info"
    info=$(dk image inspect "metainc/naver-$name:$cur" 2>>"$CMD_LOG" | py image-info) \
      || die LAYOUT "현재 이미지 metainc/naver-$name:$cur 정보를 읽지 못했습니다"
    read -r id user src label <<EOF
$info
EOF
    [ "$src" = "$cur" ] || die LAYOUT "metainc/naver-$name:$cur 의 source 라벨이 $src 입니다"
    [ "$user" = 10001:10001 ] || die LAYOUT "metainc/naver-$name:$cur 사용자 $user (10001:10001 이어야 함)"
    read_container "naver-$name" || die LAYOUT "naver-$name 컨테이너를 정확히 하나 찾지 못했습니다"
    [ "$C_RUNNING" = true ] || die NOT_ACTIVE "naver-$name 컨테이너가 실행 중이 아닙니다"
    [ "$C_IMAGE" = "$id" ] || die LAYOUT "naver-$name 컨테이너 이미지($C_IMAGE)가 태그 $cur($id)와 다릅니다"
    [ "$C_PROJECT" = "naver-$name" ] && [ "$C_SERVICE" = "naver-$name" ] || die LAYOUT "naver-$name compose 라벨이 다릅니다"
    [ "$C_USER" = 10001:10001 ] || die LAYOUT "naver-$name 컨테이너 사용자 $C_USER (10001:10001 이어야 함)"
    if [ "$name" = engine ]; then
      PREV_ENGINE_IMAGE=$id
      PREV_ENGINE_MOUNTS=$C_MOUNTS
      # 실행 중 판의 유효 스위치(제품 _flag 규칙, 컨테이너 Env 기준). 값은 참/거짓만 다룬다.
      CUR_SWITCHES=$C_SWITCHES
      case ",$CUR_SWITCHES," in
        *,execution=false,*) ;;
        *) die EXECUTION_ENABLED "실행 중 엔진의 execution 스위치가 false 가 아닙니다" ;;
      esac
    else
      PREV_RELAY_IMAGE=$id
      PREV_RELAY_MOUNTS=$C_MOUNTS
    fi
  done
  log "현재 판 $cur (engine $PREV_ENGINE_IMAGE, relay $PREV_RELAY_IMAGE, companion $companion, 스위치 $CUR_SWITCHES)"

  # ── 2. 원본 묶음과 스키마(엔진 DB 를 열지 않고 소스로 비교) ──
  SCHEMA_NEW=$(py tar-check "$tar_path") || { info=$SCHEMA_NEW; SCHEMA_NEW=''; die ARCHIVE "$info"; }
  info=$(dk image inspect "$PREV_ENGINE_IMAGE" 2>>"$CMD_LOG" | py image-info) || die LAYOUT "실행 중 engine 이미지 정보를 읽지 못했습니다"
  read -r id user src label <<EOF
$info
EOF
  if printf '%s' "$label" | grep -Eq '^[0-9]+$'; then
    SCHEMA_CUR=$label
    log "현재 스키마(이미지 라벨): $SCHEMA_CUR"
  else
    # 라벨 없는 옛 이미지: 컨테이너를 시작하지 않고(create) 이미지 안의 store.py 만 복사해 읽는다.
    cid=$(dk create --network none "$PREV_ENGINE_IMAGE" 2>>"$CMD_LOG")
    SCHEMA_CUR=$(dk cp "$cid:/opt/naver-engine/naver_engine/store.py" - 2>>"$CMD_LOG" | py schema-tar-stdin) || SCHEMA_CUR=''
    dk rm "$cid" >>"$CMD_LOG" 2>&1 || warn TEMP_CONTAINER_LEFT "임시 컨테이너 $cid 삭제 실패"
    [ -n "$SCHEMA_CUR" ] || die SCHEMA_UNKNOWN "실행 중 이미지의 SCHEMA_VERSION 을 읽지 못했습니다"
    log "현재 스키마(이미지 안 store.py): $SCHEMA_CUR"
  fi
  if [ "$SCHEMA_NEW" != "$SCHEMA_CUR" ]; then
    die SCHEMA_CHANGED "SCHEMA_VERSION 이 $SCHEMA_CUR → $SCHEMA_NEW 로 바뀝니다. 스키마 이관은 이 배포 장치에서 하지 않습니다"
  fi
  log "스키마 동일: $SCHEMA_NEW"

  # ── 2b. 빌드 전 공간 예산(이미지·release 폴더를 만들기 전에) ──
  # 빌드 예산 = 지금 실행 중인 두 이미지 Size 합(공유 층까지 모두 새로 받는 최악의 경우, 최소 512MiB)
  #           + 원본 tar 크기(release 폴더). DB 사본 예산 = DB 파일 합 + 256MiB(직전 사본은 남아 있는 상태로).
  # 같은 파일시스템이면 합산해 비교한다. 모자라면 아무것도 만들지 않고 거부한다.
  info=$(py db-files "$R$DATA_DIR") || die DB_FILES "$info"
  size=${info%% *}
  [ -d "$R$DB_BACKUP_PARENT" ] || die LAYOUT "$DB_BACKUP_PARENT 가 없습니다"
  build_need=$(dk image inspect "$PREV_ENGINE_IMAGE" "$PREV_RELAY_IMAGE" 2>>"$CMD_LOG" | py image-sizes) \
    || die LAYOUT "현재 이미지 크기를 읽지 못했습니다"
  [ "$build_need" -ge 536870912 ] || build_need=536870912
  docker_root=$(dk info --format '{{.DockerRootDir}}' 2>>"$CMD_LOG") || die LAYOUT "docker 저장 위치를 읽지 못했습니다"
  info=$(py disk-budget "$R$docker_root=$build_need" "$R$RELEASES=$(wc -c < "$tar_path" | tr -d ' ')" \
    "$R$DB_BACKUP_PARENT=$((size + 268435456))") || die DISK_PREBUILD "$info"
  log "빌드 전 공간 예산 통과(빌드 ${build_need}B + DB 사본 $((size + 268435456))B)"

  # ── 3. 복구 기록 시작(서비스를 멈추기 전) ──
  run_dir="$STATE_DIR/runs/$stamp-$(printf '%s' "$NEW" | cut -c1-12)"
  mkdir "$R$run_dir"
  for name in engine relay; do
    cp "$R$UNIT_DIR/metainc-naver-$name.service" "$R$run_dir/metainc-naver-$name.service"
    cp "$cur_r/preview-$name.override.yml" "$R$run_dir/preview-$name.override.yml"
  done
  printf '%s\n' "$PREV_ENGINE_MOUNTS" > "$R$run_dir/mounts-engine.json"
  printf '%s\n' "$PREV_RELAY_MOUNTS" > "$R$run_dir/mounts-relay.json"
  # 명령 로그를 이 실행 폴더로 옮긴다(복원 때도 같은 곳에 쓴다).
  cat "$CMD_LOG" > "$R$run_dir/commands.log"
  rm -f "$CMD_LOG"
  CMD_LOG="$R$run_dir/commands.log"
  rm -f "$STATE_FILE"
  HAVE_STATE=1
  py state-write "$STATE_FILE" "phase=preparing" "new_commit=$NEW" "prev_commit=$cur" \
    "prev_engine_image=$PREV_ENGINE_IMAGE" "prev_relay_image=$PREV_RELAY_IMAGE" "run_dir=$run_dir" \
    "companion=$companion" "schema=$SCHEMA_NEW" "switches=$CUR_SWITCHES" "started_at=$stamp"
  PHASE=preparing
  log "복구 기록: $run_dir (unit·override·mount 사본, 직전 이미지 ID, 스위치)"

  # ── 4. 새 release 폴더(이미 있으면 같은 원본인지만 확인) ──
  rel_new="$RELEASES/naver-$NEW"
  if [ -e "$R$rel_new" ]; then
    info=$(py tree-compare "$tar_path" "$R$rel_new") || die RELEASE_DIR_DIFFERS "$info"
    log "기존 release 폴더 재사용(원본 동일): $rel_new"
  else
    py tar-extract "$tar_path" "$R$rel_new"
    log "release 폴더 생성: $rel_new"
  fi
  for name in engine relay; do
    override="$R$rel_new/preview-$name.override.yml"
    py subst "$R$run_dir/preview-$name.override.yml" "$R$run_dir/new-preview-$name.override.yml" "$cur" "$NEW" 1
    if [ -e "$override" ]; then
      [ "$(py sha "$override")" = "$(py sha "$R$run_dir/new-preview-$name.override.yml")" ] \
        || die RELEASE_DIR_DIFFERS "$override 가 현재 override 에서 커밋만 바꾼 내용과 다릅니다"
    else
      write_file_atomic "$R$run_dir/new-preview-$name.override.yml" "$override" 600
    fi
  done

  # ── 5. 빌드·설정 비교·check-config(서비스를 멈추기 전) ──
  set_phase building
  for name in engine relay; do
    log "빌드: metainc/naver-$name:$NEW (출력은 비공개 명령 로그에만)"
    dk build --quiet --label "metainc.naver.preview.source=$NEW" --label "metainc.naver.schema=$SCHEMA_NEW" \
      -t "metainc/naver-$name:$NEW" -f "$R$rel_new/Dockerfile.naver-$name" "$R$rel_new" >>"$CMD_LOG" 2>&1 \
      || die BUILD_FAILED "metainc/naver-$name:$NEW 빌드 실패"
    info=$(dk image inspect "metainc/naver-$name:$NEW" 2>>"$CMD_LOG" | py image-info) || die BUILD_FAILED "새 이미지 정보 없음"
    read -r id user src label <<EOF
$info
EOF
    [ "$src" = "$NEW" ] && [ "$user" = 10001:10001 ] || die BUILD_FAILED "새 이미지 라벨/사용자 이상($src, $user)"
    if [ "$name" = engine ]; then NEW_ENGINE_IMAGE=$id; else NEW_RELAY_IMAGE=$id; fi
    # 관제 설정 묶음(서비스 목록·mount·user·restart·network·read_only·tmpfs·cap_drop·security_opt) 비교.
    shape_old=$(compose_shape "$name" "$rel_cur" "$companion") || die COMPOSE_CONFIG "현재 $name compose 설정을 읽지 못했습니다"
    shape_new=$(compose_shape "$name" "$rel_new" "$companion") || die COMPOSE_CONFIG "새 $name compose 설정이 유효하지 않습니다"
    info=$(py shape-diff "$shape_old" "$shape_new") || die CONFIG_SHAPE_CHANGED "$info"
    log "$name 설정 묶음 동일(mount·user 10001·restart no·서비스 목록)"
  done
  [ "$NEW_ENGINE_IMAGE" != "$PREV_ENGINE_IMAGE" ] || warn SAME_IMAGE_ID "새 engine 이미지 ID 가 직전과 같습니다"
  py state-write "$STATE_FILE" "new_engine_image=$NEW_ENGINE_IMAGE" "new_relay_image=$NEW_RELAY_IMAGE"

  # 새 이미지로 check-config: 운영 data·socket·backup·tunnel mount 없음, 네트워크 없음, 읽기 전용, 10001.
  # 환경은 새 compose 설정의 유효 environment(runtime.env 포함)를 값 노출 없이 넘긴다.
  compose_args engine "$rel_new" "$companion"
  new_switches=$(dk "${CARGS[@]}" config --format json 2>>"$CMD_LOG" | py check-config-run "$NEW_ENGINE_IMAGE" "$CMD_LOG") \
    || die CHECK_CONFIG "$new_switches"
  case ",$new_switches," in
    *,execution=false,*) ;;
    *) die EXECUTION_ENABLED "새 판의 execution 스위치가 false 가 아닙니다" ;;
  esac
  [ "$new_switches" = "$CUR_SWITCHES" ] || die FLAGS_CHANGED "새 판 스위치($new_switches)가 현재($CUR_SWITCHES)와 다릅니다"
  log "check-config(격리): 스위치 현재와 동일 $new_switches"

  # 디스크(빌드 뒤 다시): DB 사본 공간(DB 합 + 256MiB, 직전 사본은 남긴 채) 이 없으면 멈추기 전에 거부.
  info=$(py db-files "$R$DATA_DIR") || die DB_FILES "$info"
  size=${info%% *}
  info=$(py disk-budget "$R$DB_BACKUP_PARENT=$((size + 268435456))") || die DISK "$info"

  # 변하지 않아야 할 것들의 지문(값은 출력하지 않는다).
  sum_runtime=$(py sha "$R$RUNTIME_ENV" 2>/dev/null || echo absent)
  sum_tmpfiles=$(py sha "$R$TMPFILES_CONF")
  sum_tunnel=$(py sha "$R$UNIT_DIR/$TUNNEL_UNIT" 2>/dev/null || echo absent)
  sum_nginx=$(py tree-sha "$R$NGINX_DIR")

  # 멈추기 직전 재확인: unit 이 기록한 사본과 같은지.
  for name in engine relay; do
    [ "$(py sha "$R$UNIT_DIR/metainc-naver-$name.service")" = "$(py sha "$R$run_dir/metainc-naver-$name.service")" ] \
      || die CHANGED_DURING_PREPARE "준비 중 $name unit 이 바뀌었습니다"
  done
  set_phase prepared

  # ── 6. 정지: relay → engine ──
  set_phase stopping
  STOP_STARTED=$SECONDS
  stop_and_wait "$RELAY_UNIT" naver-relay || die STOP_FAILED "relay 정지 확인 실패"
  stop_and_wait "$ENGINE_UNIT" naver-engine || die STOP_FAILED "engine 정지 확인 실패"

  # ── 7. DB cold copy(엔진 정지 확인 상태에서만) ──
  set_phase backing_up
  stopped_confirmed "$ENGINE_UNIT" naver-engine || die DB_COPY "엔진이 멈춰 있지 않아 복사하지 않습니다"
  mkdir -p "$R$DB_BACKUPS"
  chmod 700 "$R$DB_BACKUPS"
  # 보관 1벌. 새 사본을 .partial 에 만들고 크기·sha256 검증·fsync 가 끝난 뒤에만 이름을 바꾸고
  # 그다음에 직전 사본을 지운다. 검증 실패면 새 사본만 지우고 직전 사본은 그대로 둔다.
  while read -r f; do
    [ -z "$f" ] || log "지난 실행의 미완성 사본 정리: $f"
  done < <(py partial-prune "$R$DB_BACKUPS")
  DB_BACKUP="$DB_BACKUPS/$stamp-$(printf '%s' "$cur" | cut -c1-12)"
  mkdir "$R$DB_BACKUP.partial"
  files=$(py db-files "$R$DATA_DIR")
  for f in ${files#* }; do
    cp -p "$R$DATA_DIR/$f" "$R$DB_BACKUP.partial/$f"
  done
  # shellcheck disable=SC2086
  if ! info=$(py verify-copy "$R$DATA_DIR" "$R$DB_BACKUP.partial" ${files#* }); then
    py partial-prune "$R$DB_BACKUPS" >/dev/null || true
    DB_BACKUP=''
    die DB_COPY "$info"
  fi
  mv "$R$DB_BACKUP.partial" "$R$DB_BACKUP"
  sync
  log "DB 파일 복사·검증(정지 상태, 크기·sha256): $DB_BACKUP (${files#* })"
  while read -r f; do
    [ -z "$f" ] || log "직전 DB 사본 정리(새 사본 검증 뒤): $f"
  done < <(py backup-prune "$R$DB_BACKUPS" 1 || warn BACKUP_PRUNE_FAILED "직전 DB 사본 정리 실패")

  # ── 8. unit 교체(커밋만 치환, 치환 개수 단언) → daemon-reload → 컨테이너 생성 ──
  set_phase switching
  py subst "$R$run_dir/$ENGINE_UNIT" "$R$run_dir/new-$ENGINE_UNIT" "$cur" "$NEW" 6
  py subst "$R$run_dir/$RELAY_UNIT" "$R$run_dir/new-$RELAY_UNIT" "$cur" "$NEW" 4
  write_file_atomic "$R$run_dir/new-$ENGINE_UNIT" "$R$UNIT_DIR/$ENGINE_UNIT" 644
  write_file_atomic "$R$run_dir/new-$RELAY_UNIT" "$R$UNIT_DIR/$RELAY_UNIT" 644
  sync
  systemctl daemon-reload 2>>"$CMD_LOG"
  for unit in "$ENGINE_UNIT" "$RELAY_UNIT"; do
    [ "$(unit_prop "$unit" NeedDaemonReload)" = no ] || die SWITCH "$unit daemon-reload 반영 안 됨"
  done
  for name in engine relay; do
    compose_args "$name" "$rel_new" "$companion"
    dk "${CARGS[@]}" up --no-start --no-build --force-recreate >>"$CMD_LOG" 2>&1 || die SWITCH "새 $name 컨테이너 생성 실패"
  done
  read_container naver-engine || die SWITCH "새 engine 컨테이너 확인 실패"
  [ "$C_IMAGE" = "$NEW_ENGINE_IMAGE" ] && [ "$C_RUNNING" = false ] || die SWITCH "새 engine 컨테이너 상태 이상"
  [ "$C_MOUNTS" = "$PREV_ENGINE_MOUNTS" ] || die MOUNTS_CHANGED "새 engine 컨테이너 mount 가 직전과 다릅니다"
  [ "$C_SWITCHES" = "$CUR_SWITCHES" ] || die FLAGS_CHANGED "새 engine 컨테이너 스위치가 직전과 다릅니다"
  read_container naver-relay || die SWITCH "새 relay 컨테이너 확인 실패"
  [ "$C_IMAGE" = "$NEW_RELAY_IMAGE" ] && [ "$C_RUNNING" = false ] || die SWITCH "새 relay 컨테이너 상태 이상"
  [ "$C_MOUNTS" = "$PREV_RELAY_MOUNTS" ] || die MOUNTS_CHANGED "새 relay 컨테이너 mount 가 직전과 다릅니다"

  # ── 9. 시작: engine → relay ──
  set_phase starting
  log "시작: $ENGINE_UNIT"
  systemctl start "$ENGINE_UNIT" 2>>"$CMD_LOG"
  log "시작: $RELAY_UNIT"
  systemctl start "$RELAY_UNIT" 2>>"$CMD_LOG"

  # ── 10. 헬스 + 60초 유지 ──
  set_phase verifying
  health_check "$NEW_ENGINE_IMAGE" "$NEW_RELAY_IMAGE" || die HEALTH "헬스 실패($HEALTH_STATUS $HEALTH_CODES)"

  # ── 11. 마무리 ──
  [ "$(py sha "$R$RUNTIME_ENV" 2>/dev/null || echo absent)" = "$sum_runtime" ] || warn RUNTIME_ENV_CHANGED "runtime.env 가 배포 중 바뀌었습니다(이 장치는 쓰지 않음)"
  [ "$(py sha "$R$TMPFILES_CONF")" = "$sum_tmpfiles" ] || warn TMPFILES_CHANGED "tmpfiles conf 가 배포 중 바뀌었습니다(이 장치는 쓰지 않음)"
  [ "$(py sha "$R$UNIT_DIR/$TUNNEL_UNIT" 2>/dev/null || echo absent)" = "$sum_tunnel" ] || warn TUNNEL_UNIT_CHANGED "ERP 터널 unit 이 배포 중 바뀌었습니다(이 장치는 쓰지 않음)"
  [ "$(py tree-sha "$R$NGINX_DIR")" = "$sum_nginx" ] || warn NGINX_CHANGED "nginx 설정이 배포 중 바뀌었습니다(이 장치는 쓰지 않음)"
  set_phase 'done'
  py state-write "$R$STATE_DIR/current.json" "commit=$NEW" "engine_image=$NEW_ENGINE_IMAGE" \
    "relay_image=$NEW_RELAY_IMAGE" "schema=$SCHEMA_NEW" "switches=$CUR_SWITCHES" "deployed_at=$stamp" \
    "previous_commit=$cur"
  py history-add "$R$STATE_DIR/history.json" "$cur"
  py history-add "$R$STATE_DIR/history.json" "$NEW"
  # 이미지 정리: 이 장치가 배포한 기록 중 최근 3개·현재·직전은 남긴다. 기록에 없는 태그는 건드리지 않는다.
  while read -r f; do
    [ -n "$f" ] || continue
    for name in engine relay; do
      if dk image inspect "metainc/naver-$name:$f" >/dev/null 2>&1; then
        if dk rmi "metainc/naver-$name:$f" >>"$CMD_LOG" 2>&1; then
          log "오래된 이미지 태그 정리: metainc/naver-$name:$f"
        else
          warn IMAGE_PRUNE_FAILED "이미지 태그 정리 실패: metainc/naver-$name:$f"
        fi
      fi
    done
    py prune-history "$R$STATE_DIR/history.json" "$f"
  done < <(py prune-list "$R$STATE_DIR/history.json" "$NEW" "$cur")
  if [ -n "$WARNINGS" ]; then
    finish 0 DEPLOYED_WITH_WARNINGS "$WARNINGS" "$cur → $NEW 배포 완료(경고 있음)"
  fi
  finish 0 DEPLOYED '' "$cur → $NEW 배포 완료($HEALTH_CODES, 정지~헬스 준비 ${DOWNTIME:-?}초)"
}

# ── 입구 ────────────────────────────────────────────────────────────────────
case "$MODE" in
  inspect)
    [ "$#" = 1 ] || { echo "사용: $0 inspect" >&2; exit 64; }
    main_inspect
    ;;
  cleanup-plan)
    [ "$#" = 1 ] || { echo "사용: $0 cleanup-plan" >&2; exit 64; }
    py cleanup-plan
    ;;
  cleanup)
    [ "$#" = 2 ] || { echo "사용: $0 cleanup <allowlist_sha256>" >&2; exit 64; }
    main_cleanup "$2"
    ;;
  deploy)
    shift
    [ "$#" -ge 2 ] || { echo "사용: $0 deploy <commit> <source.tar> [--log FILE] [--result FILE]" >&2; exit 64; }
    D_COMMIT=$1
    D_TAR=$2
    shift 2
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --log) LOG_FILE=$2; shift 2 ;;
        --result) RESULT_FILE=$2; shift 2 ;;
        *) echo "알 수 없는 인자: $1" >&2; exit 64 ;;
      esac
    done
    if [ -n "$LOG_FILE" ]; then
      exec >>"$LOG_FILE" 2>&1
    fi
    trap on_exit EXIT
    trap 'on_error $? $LINENO' ERR
    trap 'on_signal TERM' TERM
    trap 'on_signal INT' INT
    trap '' HUP
    log "naver-deploy deploy $D_COMMIT 시작"
    main_deploy "$D_COMMIT" "$D_TAR"
    ;;
  *)
    echo "사용: $0 inspect | cleanup-plan | cleanup <allowlist_sha256> | deploy <commit> <source.tar> [--log FILE] [--result FILE]" >&2
    exit 64
    ;;
esac
