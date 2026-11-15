#!/usr/bin/env bash
# 네이버 관제(engine + relay) 단순 배포 — 서버(VPS)에서 root 로 실행한다.
#
#   naver-deploy.sh inspect
#       읽기 전용. 서비스·이미지·폴더 상태를 한 줄 JSON 으로 출력한다(무엇도 바꾸지 않는다).
#   naver-deploy.sh deploy <제품 커밋 40자리> <source.tar> [--log FILE] [--result FILE]
#       시험을 통과한 정확한 커밋을 배포한다. 실패하면 직전 판으로 자동 복원한다.
#   naver-deploy.sh disk-usage
#       읽기 전용. 파일시스템·docker·폴더(du, 깊이 4)·journal 사용량을 소유자별(관제·다른 앱·OS·docker·백업)로 한 줄 JSON.
#   naver-deploy.sh app-inventory
#       철거 전 앱/nginx/데이터 경로 메타데이터만 읽어 한 줄 JSON(비밀 원문/DB 내용 미출력).
#   naver-deploy.sh cleanup-plan
#       읽기 전용. 지워도 되는 관제 이미지 태그·release 폴더 목록과 회수량 추정, allowlist_sha256 을 낸다.
#   naver-deploy.sh cleanup <allowlist_sha256>
#       계획을 다시 세워 해시가 정확히 같을 때만 그 목록만 지운다(docker image rm 강제 없음, release 폴더 rm -r).
#   naver-deploy.sh cleanup-artifacts-plan | cleanup-artifacts <allowlist_sha256>
#       같은 미사용 관제 태그·release만 정리하며 기존 배포 로그는 생성·삭제·chmod 하지 않는다. 별도 scope 해시 사용.
#   naver-deploy.sh migrate-prepare | migrate-rehearse | migrate-plan <커밋> <source.tar> <migration_id>
#   naver-deploy.sh migrate-deploy <커밋> <source.tar> <migration_id> <plan_sha256>
#   naver-deploy.sh migrate-continue | migrate-rollback | migrate-accept <run id>
#   naver-deploy.sh nginx-plan <커밋> <source.tar> <단계> | nginx-apply <커밋> <source.tar> <단계> <plan_sha256>
#       고정 nginx 단계(지금은 reconcile-upload-v1): 제품 커밋의 두 파일(해시 고정)로 업로드 두 경로만 4MiB. 고정 두 파일만 쓰고
#       nginx -t·reload 뒤 실제 요청으로 확인, 실패하면 직전 설정으로 되돌린다. 이관과 따로 승인·실행한다.
#       고정 표(MIGRATIONS)의 추가형 스키마 이관만(21-22-exhaust-v1, 22-23-reconcile-v1). deploy 의 SCHEMA_CHANGED 거절은 그대로다.
#       이관 모드에서만 DB 를 연다 — 준비된 정확 이미지 안의 고정 helper(naver_schema_migrate.py)가 사본에서만 이관하고
#       원본과 전수 대조한 뒤 저널을 남긴 두 rename 으로 바꾼다. 재부팅에도 남는 시작 차단(hold + drop-in), guarded_start,
#       ACTIVE→HEALTHY→COMPLETED 재진입 규칙, 복귀 pin 은 docs/naver-simple-deploy.md 의 「스키마 이관」 절.
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
#   - 제품 SCHEMA_VERSION 이 지금 돌고 있는 판과 다르면 거부한다(우회 입력 없음). 고정 이관 항목은 migrate-* 모드로만.
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
# 새 판에만 있는 스위치: check-config 가 내도 된다(비교 문자열에는 넣지 않는다). migrate-* 는 반드시 꺼져 있어야 한다
# (보고 대조 쓰기, 3단계 12260db~ — 이관 직후 꺼진 채 시작하고 대표가 따로 켠다). 일반 deploy 는 runtime.env 값 그대로.
OFF_SWITCHES = ('reconcile_writes',)
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


def check_config_run(image, private_log, optional_rule='any'):
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
            or not isinstance(switches, dict) or not set(SWITCHES) <= set(switches)
            or not set(switches) <= set(SWITCHES) | set(OFF_SWITCHES)
            or any(type(switches[name]) is not bool for name in OFF_SWITCHES if name in switches)
            or (optional_rule == 'off' and any(switches[name] is not False for name in OFF_SWITCHES if name in switches))
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
    """이 장치가 배포한 기록 중 최근 3개·현재·직전·복귀 pin(released 아님)을 뺀 나머지 커밋만 정리 대상으로 낸다."""
    history = json.loads(read(path)) if os.path.exists(path) else []
    keep = set(history[-3:]) | {current, previous} | pinned_rollback()[0]
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


def open_dir_nofollow(path):
    """경로의 마지막 폴더를 링크를 따르지 않고 연다. 부모 fd 에서 lstat 한 정체성(dev/inode)과 같아야 한다."""
    parent, name = os.path.split(path.rstrip('/'))
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):
            fail('BACKUP_SAFETY: 폴더가 아니거나 링크입니다 %s' % name)
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    opened = os.fstat(fd)
    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
        os.close(fd)
        fail('BACKUP_SAFETY: 여는 사이에 폴더가 바뀌었습니다 %s' % name)
    return fd


V2_CHILDREN = {'engine.db.gz', 'manifest.json'}
V2_KEYS = {'version', 'files', 'schema', 'source_commit', 'purpose', 'pinned', 'run'}
V2_FILE_KEYS = {'size', 'sha256', 'stored', 'gz_size', 'gz_sha256'}
RUN_ID_RE = re.compile(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\Z')
SHA_RE = re.compile(r'[0-9a-f]{64}\Z')


def child_allowed(item, partial):
    return DB_NAME.match(item) or item == 'manifest.json' or (item in ('engine.db.gz', 'engine.db.gz.partial') if partial
                                                               else item == 'engine.db.gz')


def manifest_v2(value):
    """엄격한 v2 manifest(gzip 사본). 모양이 하나라도 다르면 None — 부르는 쪽이 거부한다."""
    if type(value) is not dict or set(value) != V2_KEYS or value['version'] != 2 or type(value['pinned']) is not bool:
        return None
    files = value['files']
    if type(files) is not dict or set(files) != {'engine.db'} or type(files['engine.db']) is not dict:
        return None
    entry = files['engine.db']
    if (set(entry) != V2_FILE_KEYS or entry['stored'] != 'gzip' or any(type(entry[k]) is not int or entry[k] < 0
                                                                        for k in ('size', 'gz_size'))
            or not all(isinstance(entry[k], str) and SHA_RE.match(entry[k]) for k in ('sha256', 'gz_sha256'))):
        return None
    if (type(value['schema']) is not int or not isinstance(value['source_commit'], str)
            or not HEX40.match(value['source_commit']) or value['schema'] != MANIFEST_PURPOSES.get(value['purpose'])
            or not isinstance(value['run'], str) or not RUN_ID_RE.match(value['run'])):
        return None
    return value


def read_small_child(fd, name, limit=65536):
    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        data = os.read(child, limit + 1)
    finally:
        os.close(child)
    if len(data) > limit:
        fail('BACKUP_SAFETY: manifest 가 너무 큽니다')
    return data


def backup_entries(root_fd):
    """사본 폴더 안 우리 이름 규칙의 항목을 모두 검사한다(링크·일반 파일·예상 밖 자식 종류면 거부).
    gzip 자식이 있는 완성 사본은 엄격한 v2 manifest 여야 한다. 돌려주는 값: 이름 → (dev, ino, pinned)."""
    root = os.fstat(root_fd)
    found = {}
    for name in sorted(os.listdir(root_fd)):
        if not (BACKUP_DIR_NAME.match(name) or PARTIAL_DIR_NAME.match(name)):
            continue
        info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or info.st_dev != root.st_dev:
            fail('BACKUP_SAFETY: 사본 항목이 같은 파일시스템의 실제 폴더가 아닙니다 %s' % name)
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        pinned = False
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                fail('BACKUP_SAFETY: 여는 사이에 사본 폴더가 바뀌었습니다 %s' % name)
            items = os.listdir(fd)
            partial = bool(PARTIAL_DIR_NAME.match(name))
            for item in items:
                child = os.stat(item, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(child.st_mode) or not child_allowed(item, partial):
                    fail('BACKUP_SAFETY: 사본 폴더 %s 에 예상하지 못한 항목이 있습니다' % name)
            if not partial and 'engine.db.gz' in items:
                if set(items) != V2_CHILDREN:
                    fail('BACKUP_SAFETY: gzip 사본 %s 의 자식 구성이 v2 와 다릅니다' % name)
                try:
                    value = manifest_v2(json.loads(read_small_child(fd, 'manifest.json')))
                except ValueError:
                    value = None
                if value is None:
                    fail('BACKUP_SAFETY: gzip 사본 %s 의 manifest 가 엄격한 v2 가 아닙니다' % name)
                pinned = value['pinned']
        finally:
            os.close(fd)
        found[name] = (info.st_dev, info.st_ino, pinned)
    return found


def remove_backup_entry(root_fd, name, identity):
    """root_fd 기준 상대 경로로만 지운다. 링크를 따르지 않고, 정체성이 다르면 아무것도 지우지 않는다."""
    identity = tuple(identity[:2])
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != identity:
            fail('BACKUP_SAFETY: 지우기 직전 사본 폴더가 바뀌었습니다 %s' % name)
        items = os.listdir(fd)
        partial = bool(PARTIAL_DIR_NAME.match(name))
        for item in items:
            child = os.stat(item, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(child.st_mode) or not child_allowed(item, partial):
                fail('BACKUP_SAFETY: 사본 폴더 %s 에 예상하지 못한 항목이 있습니다' % name)
        for item in items:
            os.unlink(item, dir_fd=fd)
    finally:
        os.close(fd)
    again = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    if (again.st_dev, again.st_ino) != identity or not stat.S_ISDIR(again.st_mode):
        fail('BACKUP_SAFETY: 지우기 직전 사본 이름이 다른 폴더를 가리킵니다 %s' % name)
    os.rmdir(name, dir_fd=root_fd)


def backup_prune(folder, keep):
    """완성된 사본 중 최신 keep 개와 pin 된(v2 pinned:true) 사본만 남긴다.
    모든 사본 항목을 먼저 검사하고, 하나라도 이상하면 아무것도 지우지 않는다."""
    root_fd = open_dir_nofollow(folder)
    try:
        entries = backup_entries(root_fd)
        names = sorted(name for name in entries if BACKUP_DIR_NAME.match(name))
        for name in names[:-int(keep)] if len(names) > int(keep) else []:
            if entries[name][2]:
                continue
            remove_backup_entry(root_fd, name, entries[name])
            print(name)
    finally:
        os.close(root_fd)


def partial_prune(folder):
    """이전 실행이 남긴 미완성(.partial) 사본만 지운다. 모든 사본 항목을 먼저 검사한다(링크면 거부)."""
    root_fd = open_dir_nofollow(folder)
    try:
        entries = backup_entries(root_fd)
        for name in sorted(entries):
            if PARTIAL_DIR_NAME.match(name):
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
                try:
                    migration_partial = any(item.startswith('engine.db.gz') for item in os.listdir(fd))
                finally:
                    os.close(fd)
                if migration_partial:
                    continue   # 이관 gzip 부분본: 사람이 검토할 때까지 보존
                remove_backup_entry(root_fd, name, entries[name])
                print(name)
    finally:
        os.close(root_fd)



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
ARTIFACTS_SCOPE = 'unused-naver-artifacts-v1'
RELEASE_REF = re.compile(r'releases/naver-([0-9a-f]{40})(?![0-9a-f])')
UNIT_ROOTS = ('/etc/systemd/system', '/run/systemd/system', '/usr/lib/systemd/system', '/lib/systemd/system')
UNIT_SUFFIXES = ('.service', '.timer', '.path', '.socket')


def docker(argv, timeout=120):
    done = subprocess.run(['docker'] + argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                          env={'PATH': os.environ.get('PATH', '/usr/sbin:/usr/bin:/sbin:/bin'), 'LANG': 'C'})
    return done.returncode, done.stdout.decode('utf-8', 'replace'), done.stderr.decode('utf-8', 'replace')


def docker_json(argv):
    code, out, _ = docker(argv)
    if code:
        fail('CLEANUP_PLAN: docker %s 실패' % argv[0])
    return json.loads(out)


def must_read(path, what):
    """참조 근거 파일은 반드시 읽혀야 한다. 못 읽으면 '모르는 배치'로 계획·정리를 거부한다(fail-closed)."""
    try:
        with open(path, errors='replace') as handle:
            return handle.read()
    except OSError as error:
        fail('CLEANUP_LAYOUT: %s 를 읽지 못했습니다(%s) — 모르는 배치라 거부합니다' % (what, type(error).__name__))


def human_bytes(value):
    """docker 의 사람용 크기(예: 1.23GB, 512.5MB; 1000 단위)를 바이트로."""
    match = re.fullmatch(r'\s*([0-9.]+)\s*([kKMGT]?B)\s*', str(value or ''))
    if not match:
        return None
    scale = {'B': 1, 'kB': 1000, 'KB': 1000, 'MB': 1000 ** 2, 'GB': 1000 ** 3, 'TB': 1000 ** 4}[match.group(2)]
    return int(float(match.group(1)) * scale)


def tree_bytes(path):
    """release 폴더의 디스크 블록 추정치. 링크는 따르지 않고, 다른 파일시스템으로 내려가지 않고, hardlink 는 한 번만 센다."""
    top = os.lstat(path)
    seen, total = set(), 0
    for folder, children, files in os.walk(path):
        children[:] = [c for c in children if os.lstat(os.path.join(folder, c)).st_dev == top.st_dev
                       and not os.path.islink(os.path.join(folder, c))]
        for name in files + children:
            try:
                info = os.lstat(os.path.join(folder, name))
            except OSError:
                continue
            key = (info.st_dev, info.st_ino)
            if key not in seen:
                seen.add(key)
                total += info.st_blocks * 512
    return total


def unit_sources():
    """naver 가 들어간 unit·timer 등의 모든 조각(fragment)과 drop-in(*.conf)을 네 위치에서 모으고,
    systemctl show 의 FragmentPath·DropInPaths 도 더한다. 하나라도 못 읽으면 거부한다. 내용은 출력하지 않는다."""
    paths, names = set(), set()
    for root in UNIT_ROOTS:
        base = ROOT + root
        if not os.path.isdir(base):
            continue
        try:
            entries = sorted(os.listdir(base))
        except OSError:
            fail('CLEANUP_LAYOUT: %s 를 읽지 못했습니다' % root)
        for entry in entries:
            unit = entry[:-2] if entry.endswith('.d') else entry
            if 'naver' not in unit or not unit.endswith(UNIT_SUFFIXES):
                continue
            names.add(unit)
            full = os.path.join(base, entry)
            if entry.endswith('.d'):
                if not os.path.isdir(full):
                    fail('CLEANUP_LAYOUT: drop-in 위치가 폴더가 아닙니다 %s/%s' % (root, entry))
                try:
                    confs = sorted(os.listdir(full))
                except OSError:
                    fail('CLEANUP_LAYOUT: drop-in 폴더를 읽지 못했습니다 %s/%s' % (root, entry))
                for conf in confs:
                    if conf.endswith('.conf'):
                        paths.add(os.path.join(full, conf))
            else:
                paths.add(full)
    required = ('FragmentPath', 'DropInPaths', 'LoadState')
    for unit in sorted(names):
        code = subprocess.run(['systemctl', 'show', unit, '-p', ','.join(required)],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
        if code.returncode:
            fail('CLEANUP_LAYOUT: systemctl show %s 실패' % unit)
        # 세 속성이 정확히 한 번씩 있어야 한다. 비었거나 빠졌거나 겹치거나 형식이 이상하면 모르는 배치로 거부한다.
        values = {}
        for line in code.stdout.decode('utf-8', 'replace').splitlines():
            key, sep, value = line.partition('=')
            if not sep or key not in required or key in values:
                fail('CLEANUP_LAYOUT: systemctl show %s 출력 형식 이상' % unit)
            values[key] = value
        if set(values) != set(required):
            fail('CLEANUP_LAYOUT: systemctl show %s 출력에 필수 속성이 없습니다' % unit)
        if values['LoadState'] not in ('loaded', 'masked', 'not-found'):
            fail('CLEANUP_LAYOUT: %s LoadState 가 예상 밖입니다' % unit)
        if values['LoadState'] == 'loaded' and not values['FragmentPath']:
            fail('CLEANUP_LAYOUT: %s FragmentPath 가 비었습니다' % unit)
        for key in ('FragmentPath', 'DropInPaths'):
            for item in values[key].split():
                if not item.startswith('/'):
                    fail('CLEANUP_LAYOUT: %s 경로 형식 이상' % key)
                paths.add(ROOT + item)
    texts = []
    for path in sorted(paths):
        if os.path.islink(path) and os.path.realpath(path) == '/dev/null':
            continue  # mask
        texts.append(('unit', must_read(path, 'unit 조각 ' + path[len(ROOT):])))
    return texts


def protected_state():
    """보호 대상(커밋·이미지 ID·release 참조)을 처음부터 다시 모은다. 호출할 때마다 새로 계산한다."""
    commits = {FALLBACK_COMMIT: ['fallback']}
    reasons_path = {}
    # 모든 컨테이너(실행·정지)가 쓰는 이미지 ID 와 bind 경로.
    code, out, _ = docker(['ps', '--all', '--no-trunc', '--format', '{{.ID}}'])
    if code:
        fail('CLEANUP_PLAN: docker ps 실패')
    used_images = set()
    identities = out.split()
    if identities:
        for row in docker_json(['inspect'] + identities):
            used_images.add(row.get('Image'))
            for mount in row.get('Mounts') or []:
                for commit in RELEASE_REF.findall(str(mount.get('Source') or '')):
                    reasons_path.setdefault(commit, set()).add('container-mount')
    texts = unit_sources()
    unit_dir = ROOT + '/etc/systemd/system'
    current = []
    for name in ('engine', 'relay'):
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                unit_parse(unit_dir + '/metainc-naver-' + name + '.service', name)
        except Refuse as error:
            fail('CLEANUP_LAYOUT: 현재 unit 모양을 확인하지 못했습니다 (%s)' % str(error).split(':')[0])
        commit, companion = captured.getvalue().split()
        current.append(commit)
        if companion != '-':
            texts.append(('companion', must_read(ROOT + companion, 'saved-exports companion')))
    if len(set(current)) != 1:
        fail('CLEANUP_LAYOUT: engine·relay unit 이 다른 판을 가리킵니다')
    commits.setdefault(current[0], []).append('current')
    release = ROOT + RELEASES + '/naver-' + current[0]
    for name in ('compose.naver-engine.yml', 'compose.naver-relay.yml', 'deploy/naver-engine-backup.override.yml',
                 'preview-engine.override.yml', 'preview-relay.override.yml'):
        texts.append(('compose', must_read(os.path.join(release, name), '현재 release 의 ' + name)))
    for kind, text in texts:
        for commit in RELEASE_REF.findall(text):
            reasons_path.setdefault(commit, set()).add(kind)
    pinned_commits, pinned_images = pinned_rollback()
    for commit in pinned_commits:
        commits.setdefault(commit, []).append('rollback-pin')
    used_images |= pinned_images
    for name in ('state.json', 'current.json'):
        path = ROOT + '/var/lib/metainc/naver-deploy/' + name
        if not os.path.lexists(path):
            continue
        try:
            data = json.loads(must_read(path, name))
        except ValueError:
            fail('CLEANUP_LAYOUT: %s 를 해석하지 못했습니다' % name)
        for key, value in data.items():
            if key.endswith('commit') and isinstance(value, str) and HEX40.match(value):
                commits.setdefault(value, []).append('deploy-record')
    return commits, {c: sorted(r) for c, r in reasons_path.items()}, used_images


def image_table():
    code, out, _ = docker(['image', 'ls', '--no-trunc', '--format', '{{json .}}'])
    if code:
        fail('CLEANUP_PLAN: docker image ls 실패')
    rows = []
    for line in out.splitlines():
        row = json.loads(line)
        rows.append((str(row.get('Repository')), str(row.get('Tag')), str(row.get('ID'))))
    return rows


def protected_ids(commits, used_images, table):
    ids = set(used_images)
    for repository, tag, identity in table:
        if repository in NAVER_REPOS and tag in commits:
            ids.add(identity)
    return ids


def release_identity(path):
    info = os.lstat(path)
    return '%d:%d' % (info.st_dev, info.st_ino)


def build_plan(*, artifacts_only=False):
    commits, path_refs, used_images = protected_state()
    image_commits = set(commits) | set(path_refs) if artifacts_only else commits
    table = image_table()
    keep_ids = protected_ids(image_commits, used_images, table)
    candidates, kept = [], {'protected_commits': sorted(commits), 'kept_images': 0, 'kept_releases': 0}
    for repository, tag, identity in sorted(table):
        if repository not in NAVER_REPOS or not HEX40.match(tag):
            continue
        if tag in image_commits or identity in keep_ids:
            kept['kept_images'] += 1
            continue
        rows = docker_json(['image', 'inspect', repository + ':' + tag])
        if rows[0].get('Id') != identity:
            fail('CLEANUP_PLAN: 태그가 계산 중에 바뀌었습니다')
        candidates.append({'type': 'image', 'ref': repository + ':' + tag, 'id': identity,
                           'size_bytes': int(rows[0].get('Size') or 0)})
    releases_dir = ROOT + RELEASES
    if os.path.islink(releases_dir) or not os.path.isdir(releases_dir):
        fail('CLEANUP_LAYOUT: releases 폴더가 실제 폴더가 아닙니다')
    for name in sorted(os.listdir(releases_dir)):
        match = re.fullmatch(r'naver-([0-9a-f]{40})', name)
        path = RELEASES + '/' + name
        full = ROOT + path
        if not match or os.path.islink(full) or not os.path.isdir(full):
            continue
        if match.group(1) in commits or match.group(1) in path_refs:
            kept['kept_releases'] += 1
            continue
        candidates.append({'type': 'release', 'ref': path, 'id': release_identity(full), 'size_bytes': tree_bytes(full)})
    identities = sorted([c['type'], c['ref'], c['id']] for c in candidates)
    canonical = json.dumps({'scope': ARTIFACTS_SCOPE, 'candidates': identities} if artifacts_only else identities,
                           separators=(',', ':'))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    estimate = reclaim_estimate(candidates, table, keep_ids)
    return {'candidates': candidates, 'allowlist_sha256': digest, 'kept': kept,
            'path_references': path_refs, 'reclaim_estimate': estimate,
            'counts': {'images': sum(1 for c in candidates if c['type'] == 'image'),
                       'releases': sum(1 for c in candidates if c['type'] == 'release')}}


def reclaim_estimate(candidates, table, keep_ids):
    """이미지 ID 별로 한 번만 센다. 정리 뒤에도 남는 ID(후보가 아닌 태그·별칭, 컨테이너 사용, 보호 ID)는 하한에서 뺀다.
    하한 = 그런 ID 의 docker system df -v UniqueSize 합(후보끼리만 공유하는 층은 빠지므로 보수적).
    UniqueSize 를 하나라도 모르면 하한은 null. 상한 = 후보 ID 의 image inspect Size 합(공유 층 포함)."""
    candidate_refs = {c['ref'] for c in candidates if c['type'] == 'image'}
    candidate_ids = {c['id'] for c in candidates if c['type'] == 'image'}
    surviving = set(keep_ids)
    for repository, tag, identity in table:
        if identity in candidate_ids and repository + ':' + tag not in candidate_refs:
            surviving.add(identity)  # 후보가 아닌 태그(다른 저장소 별칭·<none> 포함)가 남긴다
    freed_ids = candidate_ids - surviving
    unique = {}
    code, out, _ = docker(['system', 'df', '-v', '--format', '{{json .}}'], timeout=300)
    try:
        data = json.loads(out.strip().splitlines()[0]) if not code and out.strip() else None
        by_ref = {str(r.get('Repository')) + ':' + str(r.get('Tag')): human_bytes(r.get('UniqueSize'))
                  for r in (data or {}).get('Images') or []}
    except (ValueError, IndexError, AttributeError):
        by_ref = {}
    known = True
    for candidate in candidates:
        if candidate['type'] == 'image' and candidate['id'] in freed_ids:
            value = by_ref.get(candidate['ref'])
            if value is None:
                known = False
            else:
                unique[candidate['id']] = value
    sizes = {c['id']: c['size_bytes'] for c in candidates if c['type'] == 'image'}
    release_total = sum(c['size_bytes'] for c in candidates if c['type'] == 'release')
    lower = sum(unique.values()) if known else None
    return {'method': 'images: per unique image ID, only IDs that no other tag/alias, container or protected '
                      'commit keeps; lower bound = sum of docker system df -v UniqueSize (null if any unknown), '
                      'upper bound = sum of docker image inspect Size per candidate ID; releases: on-disk blocks '
                      '(estimate, hardlinks once, same filesystem only)',
            'image_ids_freed': len(freed_ids), 'image_ids_kept_by_other_refs': len(candidate_ids & surviving),
            'images_unique_bytes_lower_bound': lower,
            'images_size_bytes_upper_bound': sum(sizes.values()), 'releases_bytes_estimate': release_total,
            'total_lower_bound': (lower + release_total) if lower is not None else None,
            'total_upper_bound': sum(sizes.values()) + release_total}


def free_bytes():
    info = os.statvfs(ROOT + RELEASES if os.path.isdir(ROOT + RELEASES) else ROOT + '/')
    return info.f_bavail * info.f_frsize


def cleanup_plan(*, artifacts_only=False):
    plan = build_plan(artifacts_only=artifacts_only)
    if artifacts_only:
        plan.update(scope=ARTIFACTS_SCOPE, reclaim_is_estimate=True)
    plan.update(mode='cleanup-artifacts-plan' if artifacts_only else 'cleanup-plan', read_only=True, free_bytes=free_bytes(),
                generated_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    print('NAVER_DEPLOY_CLEANUP_PLAN=' + json.dumps(plan, sort_keys=True, separators=(',', ':')))


def open_verified_dir(parent_fd, name, expected, device=None):
    """parent_fd 기준으로 링크를 따르지 않고 열고, 연 fd 의 (dev, inode) 가 기대값과 같은 폴더인지 확인한다."""
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    opened = os.fstat(fd)
    if (not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != tuple(expected)
            or (device is not None and opened.st_dev != device)):
        os.close(fd)
        fail('CLEANUP_SAFETY: 연 폴더가 승인·확인한 폴더와 다릅니다')
    return fd


def unlink_name_checked(parent_fd, name, expected):
    """rmdir 직전에 그 이름이 아직 같은 (dev, inode) 를 가리키는지 확인한다."""
    again = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (again.st_dev, again.st_ino) != tuple(expected) or not stat.S_ISDIR(again.st_mode):
        fail('CLEANUP_SAFETY: 지우기 직전 이름이 다른 폴더를 가리킵니다')
    os.rmdir(name, dir_fd=parent_fd)


def empty_verified_dir(fd, device):
    """이미 확인한 폴더 fd 안만 비운다. 하위 폴더는 lstat → 열기 → fstat 대조 후 같은 fd 로만 내려간다.
    경로 문자열로 지우지 않고, 링크는 링크 자체만 지우고, 다른 파일시스템으로 내려가지 않는다."""
    for item in os.listdir(fd):
        info = os.stat(item, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            identity = (info.st_dev, info.st_ino)
            child = open_verified_dir(fd, item, identity, device)
            try:
                empty_verified_dir(child, device)
            finally:
                os.close(child)
            unlink_name_checked(fd, item, identity)
        else:
            os.unlink(item, dir_fd=fd)


def remove_release(releases_fd, name, approved):
    """승인한 (dev, inode) 의 release 폴더만 지운다. 열고 나서 대조하고, 같은 fd 로 비우고, 마지막 rmdir 직전에 다시 대조한다."""
    fd = open_verified_dir(releases_fd, name, approved)
    try:
        empty_verified_dir(fd, approved[0])
    finally:
        os.close(fd)
    unlink_name_checked(releases_fd, name, approved)


def image_still_deletable(candidate, *, artifacts_only=False):
    """지우기 직전: 태그가 아직 승인된 ID 를 가리키고, 어떤 컨테이너(정지 포함)도 그 ID 를 쓰지 않고, 보호 대상이 아닌지."""
    commits, path_refs, used_images = protected_state()
    if artifacts_only:
        commits = set(commits) | set(path_refs)
    code, out, _ = docker(['image', 'inspect', candidate['ref']])
    if code:
        return False
    try:
        if json.loads(out)[0].get('Id') != candidate['id']:
            return False
    except (ValueError, IndexError):
        return False
    if candidate['ref'].rsplit(':', 1)[1] in commits:
        return False
    if candidate['id'] in protected_ids(commits, used_images, image_table()):
        return False
    code, out, _ = docker(['ps', '--all', '--quiet', '--no-trunc', '--filter', 'ancestor=' + candidate['id']])
    return code == 0 and not out.strip()


def release_still_deletable(candidate):
    """지우기 직전: 모든 참조 근거(unit·drop-in·timer·compose·override·companion·컨테이너 mount)를 다시 모으고,
    폴더 정체성(dev/inode)이 계획 때와 같은지 본다."""
    if not re.fullmatch(re.escape(RELEASES) + r'/naver-[0-9a-f]{40}', candidate['ref']):
        return False
    commits, path_refs, _ = protected_state()
    commit = candidate['ref'].rsplit('-', 1)[1]
    if commit in commits or commit in path_refs:
        return False
    full = ROOT + candidate['ref']
    try:
        info = os.lstat(full)
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and '%d:%d' % (info.st_dev, info.st_ino) == candidate['id']


class DiscardCleanupLog:
    """The artifacts-only mode neither opens a log file nor retains command output."""
    def write(self, _text):
        pass


def cleanup(expected, private_log, *, artifacts_only=False):
    """계획을 다시 세워 해시가 정확히 같을 때만, 항목마다 지우기 직전에 다시 확인하고 그 목록만 지운다. 결과는 고정 형식 한 줄."""
    result = {'mode': 'cleanup-artifacts' if artifacts_only else 'cleanup', 'allowlist_sha256': expected, 'removed': [], 'refused': [], 'failed': [],
              'free_bytes_before': free_bytes()}
    if artifacts_only:
        result['scope'] = ARTIFACTS_SCOPE

    def finish(status, code):
        result.update(status=status, exit_code=code, free_bytes_after=free_bytes())
        print('NAVER_DEPLOY_CLEANUP_RESULT=' + json.dumps(result, sort_keys=True, separators=(',', ':')))
        sys.exit(code)
    if not re.fullmatch(r'[0-9a-f]{64}', expected or ''):
        finish('REFUSED_BAD_INPUT', 10)
    try:
        plan = build_plan(artifacts_only=artifacts_only)
    except Refuse:
        finish('REFUSED_PLAN_FAILED', 10)
    result['planned_sha256'] = plan['allowlist_sha256']
    if plan['allowlist_sha256'] != expected:
        finish('REFUSED_HASH_MISMATCH', 10)
    with (contextlib.nullcontext(DiscardCleanupLog()) if artifacts_only else open(private_log, 'a')) as log:
        for candidate in plan['candidates']:
            if candidate['type'] != 'image':
                continue
            try:
                ok = image_still_deletable(candidate, artifacts_only=artifacts_only)
            except Refuse:
                ok = False
            if not ok:
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
        releases_fd = None
        try:
            releases_fd = open_dir_nofollow(ROOT + RELEASES)
        except (Refuse, OSError):
            pass
        for candidate in plan['candidates']:
            if candidate['type'] != 'release':
                continue
            try:
                ok = releases_fd is not None and release_still_deletable(candidate)
            except Refuse:
                ok = False
            if not ok:
                result['refused'].append(candidate['ref'])
                continue
            name = candidate['ref'].rsplit('/', 1)[1]
            approved = tuple(int(part) for part in candidate['id'].split(':'))
            try:
                remove_release(releases_fd, name, approved)
                result['removed'].append(candidate['ref'])
                log.write('[remove %s] ok\n' % candidate['ref'])
            except Refuse as error:
                log.write('[remove %s] refused %s\n' % (candidate['ref'], str(error).split(':')[0]))
                result['refused'].append(candidate['ref'])
            except OSError as error:
                log.write('[remove %s] %s\n' % (candidate['ref'], type(error).__name__))
                result['failed'].append(candidate['ref'])
        if releases_fd is not None:
            os.close(releases_fd)
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
    'mode': r'(inspect|deploy|migrate-(prepare|rehearse|plan|deploy|continue|rollback|accept)|nginx-(plan|apply))', 'status': r'[A-Z_]{1,40}', 'exit_code': r'[0-9]{1,3}', 'reason': r'[A-Z_]{0,40}',
    'message': None, 'phase': r'[a-z_]{1,24}', 'new_commit': r'[0-9a-f]{40}|', 'previous_commit': r'[0-9a-f]{40}|',
    'new_engine_image': r'sha256:[0-9a-f]{64}|', 'new_relay_image': r'sha256:[0-9a-f]{64}|',
    'previous_engine_image': r'sha256:[0-9a-f]{64}|', 'previous_relay_image': r'sha256:[0-9a-f]{64}|',
    'db_backup': r'/var/backups/metainc/naver-deploy-db/[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}|',
    'downtime_seconds': r'[0-9]{0,6}', 'health_status': r'[a-z_]{0,32}',
    'health_codes': r'(engine=[0-9]{3},page=[0-9]{3},me=[0-9]{3})?', 'schema_current': r'[0-9]{0,6}',
    'schema_new': r'[0-9]{0,6}', 'switches': r'([a-z_]+=(true|false),?){0,12}', 'warnings': r'[A-Z_,]{0,400}',
    'services_stopped_confirmed': r'(true|false)?', 'database_opened_by_deploy': r'(true|false)',
    'runtime_env_changed_by_deploy': r'false', 'migration_id': r'[0-9a-z-]{0,40}',
    'migration_run': r'([0-9]{8}T[0-9]{6}Z-[0-9a-f]{12})?', 'migration_state': r'[A-Z_]{0,20}',
    'receipt_sha256': r'([0-9a-f]{64})?', 'orphans_closed': r'[0-9]{0,6}', 'pin_state': r'[a-z-]{0,12}',
    'keep_raw_now': r'(true|false|unknown)?', 'write_decision': r'(no_new_writes|new_writes|unknown)?',
    'plan_sha256': r'([0-9a-f]{64})?', 'rehearsal': r'(passed|failed)?', 'nginx_step': r'[0-9a-z-]{0,40}',
    'nginx_checks': r'[a-z0-9_=,]{0,200}'}
# 공개 로그로 나가는 유일한 줄. 모든 값은 위 형식만 통과하고, message 는 고정 문구표에서만 고른다.
MESSAGES = {
    'DEPLOYED': '배포 완료(헬스·60초 유지 통과)', 'DEPLOYED_WITH_WARNINGS': '배포 완료(헬스 통과), 마무리 경고 있음',
    'DEPLOY_FAILED_RESTORED': '새 판 실패 → 직전 판 복원·헬스 통과', 'RECOVERED_INTERRUPTED_RUN':
    '중단된 이전 배포를 직전 판으로 복원함. 다시 실행 필요', 'RESTORE_FAILED': '복원 실패. 두 서비스 정지 시도. 사람 확인 필요',
    'REFUSED': '시작 전 거부. 서비스는 그대로', 'LOCKED': '다른 관제 배포 실행 중', 'EXITED': '예상하지 못한 종료',
    'MIGRATED': '스키마 이관 배포 완료(검증·헬스 통과)', 'MIGRATED_WITH_WARNINGS': '스키마 이관 배포 완료, 경고 있음',
    'MIGRATION_HOLD': '이관 정지 보존(hold). 서비스 정지. 대표 판단 필요',
    'MIGRATION_ROLLED_BACK': '이관 되돌림: 옛 DB·옛 판 복원·헬스 통과',
    'MIGRATION_RECOVERY_REQUIRED': '모르는 이관 상태. 서비스 정지·hold 유지. 사람 확인 필요',
    'PREPARED': '이관용 이미지 준비 완료(서비스 무변경)', 'REHEARSED': '격리 리허설 통과(서비스 무변경)',
    'REHEARSAL_FAILED': '격리 리허설 실패(서비스 무변경)', 'PLANNED': '이관 계획 계산(서비스 무변경)',
    'ACCEPTED': '이관 확정: 복귀 묶음 pin 해제', 'CONTINUED': '보류된 v22 세대 재기동·헬스 통과',
    'NGINX_PLANNED': 'nginx 고정 단계 계획 계산(설정 무변경)', 'NGINX_APPLIED': 'nginx 고정 단계 적용·검증 통과',
    'NGINX_ALREADY_APPLIED': 'nginx 고정 단계가 이미 적용돼 있음(무변경)',
    'NGINX_ROLLED_BACK': 'nginx 적용 실패 → 직전 설정 복원·검증 통과',
    'NGINX_ROLLBACK_FAILED': 'nginx 복원 실패. 사람 확인 필요'}


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


# ── disk-usage: 공유 서버 디스크를 무엇이 쓰는지 읽기 전용으로 나눠 본다 ─────────────────────
# 지우기·prune·journal vacuum·로그 자르기·DB 열기·재시작·이동은 하지 않는다. 잠금도 잡지 않는다.
# 모든 외부 명령은 시간 제한을 두고, 실패하면 그 항목만 null + 사유 코드로 남긴다(전체는 성공으로 끝낸다).
# 파일 내용·환경 값·깊이 4 아래 이름은 내보내지 않는다(du 는 폴더만, 깊이 4까지).
PSEUDO_FS = {'tmpfs', 'devtmpfs', 'overlay', 'proc', 'sysfs', 'cgroup', 'cgroup2', 'devpts', 'mqueue', 'securityfs',
             'debugfs', 'tracefs', 'pstore', 'bpf', 'autofs', 'hugetlbfs', 'configfs', 'fusectl', 'binfmt_misc',
             'nsfs', 'squashfs', 'ramfs', 'rpc_pipefs', 'efivarfs', 'fuse.lxcfs', 'shm', 'nfsd'}
DU_ROOTS = ('/', '/var', '/var/lib', '/var/lib/docker', '/var/lib/containerd', '/var/log', '/var/backups', '/srv', '/opt',
            '/root', '/home', '/tmp', '/usr', '/srv/metainc', '/var/lib/metainc', '/var/backups/metainc')
TOP_N = 15
DIR_NAME = re.compile(r'[A-Za-z0-9_.@+-]{1,128}\Z')
OWNER_RULES = (
    ('naver', ('/var/lib/metainc/naver-', '/var/backups/metainc/naver-', '/srv/metainc/ad-deploy-staging',
               '/opt/metainc/naver-')),
    ('other_apps', ('/srv/metainc/', '/var/lib/metainc/', '/root/', '/opt/')),
    ('docker_internal', ('/var/lib/docker', '/var/lib/containerd', '/var/lib/buildkit')),
    ('os', ('/usr', '/var/log', '/var/cache/apt', '/var/cache', '/snap', '/var/lib/snapd', '/boot', '/lib', '/bin', '/sbin',
            '/etc', '/var/lib/apt', '/var/lib/dpkg')),
    ('backups', ('/var/backups',)),
)
MIXED = {'/', '/var', '/var/lib', '/srv', '/srv/metainc', '/var/lib/metainc', '/var/backups/metainc', '/opt', '/root',
         '/home', '/var/backups'}


def owner_of(path):
    if path in MIXED:
        return 'mixed'
    for owner, prefixes in OWNER_RULES:
        for prefix in prefixes:
            # '/' 나 '-' 로 끝나는 규칙은 접두어, 아니면 그 폴더 자신과 그 아래.
            if prefix.endswith(('/', '-')):
                if path.startswith(prefix):
                    return owner
            elif path == prefix or path.startswith(prefix + '/'):
                return owner
    return 'unclassified'


def timed(argv, timeout, low_priority=False):
    """시간 제한 실행. (상태, stdout) — 상태는 ok / timeout / not_found / exit_<코드>. stderr 는 버린다(파일 이름이 섞일 수 있다)."""
    if low_priority:
        if shutil.which('ionice'):
            argv = ['ionice', '-c', '3'] + argv
        if shutil.which('nice'):
            argv = ['nice', '-n', '19'] + argv
    try:
        done = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
                              env={'PATH': os.environ.get('PATH', '/usr/sbin:/usr/bin:/sbin:/bin'), 'LANG': 'C'})
    except subprocess.TimeoutExpired as error:
        # 시간 초과 전까지 받은 출력은 쓴다(du 는 끝난 폴더부터 낸다). 상태는 timeout 으로 남는다.
        return 'timeout', (error.stdout or b'').decode('utf-8', 'replace')
    except OSError:
        return 'not_found', ''
    return ('ok' if done.returncode == 0 else 'exit_%d' % done.returncode), done.stdout.decode('utf-8', 'replace')


def binary_bytes(text):
    """journalctl 같은 1024 단위 표기(예: 1.2G, 24.0M, 512.0K, 300B)를 바이트로."""
    match = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*([KMGTP]?)i?B?\b', text or '')
    if not match:
        return None
    return int(float(match.group(1)) * 1024 ** ' KMGTP'.index(match.group(2) or ' '))


def docker_usage(errors):
    result = {}
    status, out = timed(['docker', 'info', '--format', '{{json .}}'], 60)
    try:
        info = json.loads(out) if status == 'ok' else None
    except ValueError:
        info, status = None, 'unparseable'
    if info is None:
        errors.append({'component': 'docker_info', 'reason': status})
        result['info'] = None
    else:
        driver_status = []
        for pair in info.get('DriverStatus') or []:
            if isinstance(pair, list) and len(pair) == 2:
                driver_status.append([pick(pair[0], re.compile(r'[A-Za-z0-9 _.-]{1,64}\Z')),
                                      pick(pair[1], re.compile(r'[A-Za-z0-9 _./:-]{1,128}\Z'))])
        result['info'] = {'docker_root_dir': pick(info.get('DockerRootDir'), SAFE_PATH),
                          'driver': pick(info.get('Driver'), DIR_NAME), 'driver_status': driver_status,
                          'containerd_snapshotter': any('containerd' in str(p) for p in info.get('DriverStatus') or [])}
    status, out = timed(['docker', 'system', 'df', '--format', '{{json .}}'], 120)
    summary = {}
    if status == 'ok':
        for line in out.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            kind = {'Images': 'images', 'Containers': 'containers', 'Local Volumes': 'local_volumes',
                    'Build Cache': 'build_cache'}.get(row.get('Type'))
            if kind:
                summary[kind] = {'count': int(row['TotalCount']) if str(row.get('TotalCount', '')).isdigit() else None,
                                 'active': int(row['Active']) if str(row.get('Active', '')).isdigit() else None,
                                 'size_bytes': human_bytes(row.get('Size')),
                                 'reclaimable_bytes': human_bytes(str(row.get('Reclaimable') or '').split('(')[0])}
    if not summary:
        errors.append({'component': 'docker_system_df', 'reason': status if status != 'ok' else 'unparseable'})
    result['system_df'] = summary or None
    result['system_df_units'] = 'converted from docker human units (1000-based), approximate'
    result['build_cache'] = summary.get('build_cache') if summary else None
    status, out = timed(['docker', 'image', 'ls', '--all', '--no-trunc', '--format', '{{json .}}'], 60)
    if status != 'ok':
        errors.append({'component': 'docker_images', 'reason': status})
        result['images_by_repository'] = None
        result['dangling'] = None
        return result
    rows = []
    for line in out.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    ids = sorted({str(r.get('ID')) for r in rows if IMAGE_ID.match(str(r.get('ID')))})
    sizes = {}
    for start in range(0, len(ids), 50):
        status, out = timed(['docker', 'image', 'inspect'] + ids[start:start + 50], 60)
        try:
            for item in json.loads(out) if status == 'ok' else []:
                sizes[item.get('Id')] = int(item.get('Size') or 0)
        except ValueError:
            status = 'unparseable'
        if status != 'ok':
            errors.append({'component': 'docker_image_inspect', 'reason': status})
            break
    groups, dangling_ids = {}, set()
    for row in rows:
        repository, identity = str(row.get('Repository')), str(row.get('ID'))
        if repository == '<none>':
            dangling_ids.add(identity)
            continue
        group = groups.setdefault(pick(repository, re.compile(r'[a-z0-9][a-z0-9._/:-]{0,200}\Z')), {'tags': 0, 'ids': set()})
        group['tags'] += 1
        group['ids'].add(identity)
    by_repo = []
    for repository, group in groups.items():
        known = [sizes[i] for i in group['ids'] if i in sizes]
        by_repo.append({'repository': repository, 'owner': 'naver' if repository.startswith('metainc/naver-') else 'other_apps',
                        'tags': group['tags'], 'image_ids': len(group['ids']),
                        'size_bytes_sum': sum(known) if len(known) == len(group['ids']) else None})
    by_repo.sort(key=lambda r: -(r['size_bytes_sum'] or 0))
    result['images_by_repository'] = by_repo
    result['images_size_note'] = 'per-image Size summed per repository; shared layers are counted in each image'
    known = [sizes[i] for i in dangling_ids if i in sizes]
    result['dangling'] = {'image_ids': len(dangling_ids),
                          'size_bytes_sum': sum(known) if len(known) == len(dangling_ids) else None}
    return result


ABS_DEPTH = 4   # 규칙 경계(예: /var/lib/metainc/naver-*, /var/lib/docker/*) 의 자식까지 내려가는 절대 깊이


def unescape_mount(value):
    """mountinfo 의 \\ooo(8진수 바이트) 표기를 실제 경로로 되돌린다."""
    raw = re.sub(rb'\\([0-7]{3})', lambda m: bytes([int(m.group(1), 8)]), value.encode('utf-8', 'surrogateescape'))
    return raw.decode('utf-8', 'surrogateescape')


def encode_path(value):
    """출력용 고정·가역 표기: 공백·제어 문자·역슬래시·ASCII 밖 바이트를 mountinfo 와 같은 \\ooo 로 바꾼다.
    경로는 명령에 늘 argv 로만 넘기고(셸 없음), 출력에서만 이렇게 바꾼다."""
    if not isinstance(value, str):
        return value
    out = []
    for byte in value.encode('utf-8', 'surrogateescape'):
        out.append('\\%03o' % byte if byte <= 32 or byte >= 127 or byte == 92 else chr(byte))
    return ''.join(out)


def real_path(value):
    """절대 경로면 어떤 글자든 받는다(NUL 없음). 셸을 거치지 않으므로 공백·특수 문자도 안전하다."""
    return isinstance(value, str) and value.startswith('/') and '\0' not in value


def mount_table(errors):
    """/proc/self/mountinfo 에서 실제 파일시스템 mount 를 모두 읽는다: mountpoint·장치(major:minor)·FS 안 root·fstype.
    statvfs 가 실패해도 그 mount 는 빼지 않고 statvfs_error 로 남긴다. mountinfo 를 못 읽으면 None."""
    try:
        with open(ROOT + '/proc/self/mountinfo') as handle:
            lines = handle.read().splitlines()
    except OSError:
        errors.append({'component': 'filesystems', 'reason': 'mountinfo_unreadable'})
        return None
    rows = []
    for line in lines:
        parts = line.split()
        if '-' not in parts or len(parts) < 7:
            continue
        tail = parts[parts.index('-') + 1:]
        if not tail or tail[0] in PSEUDO_FS:
            continue
        device, fs_root, mountpoint = parts[2], unescape_mount(parts[3]), unescape_mount(parts[4])
        if not re.fullmatch(r'[0-9]+:[0-9]+', device) or not real_path(mountpoint) or not real_path(fs_root):
            # 형식을 알 수 없는 줄도 조용히 버리지 않는다.
            errors.append({'component': 'filesystems', 'path': mountpoint, 'reason': 'unsupported_mountinfo_row'})
            continue
        row = {'mountpoint': mountpoint, 'fstype': pick(tail[0], DIR_NAME), 'device': device, 'fs_root': fs_root}
        try:
            info = os.statvfs(ROOT + mountpoint)
            total = info.f_blocks * info.f_frsize
            row.update(total_bytes=total, used_bytes=total - info.f_bfree * info.f_frsize,
                       avail_bytes=info.f_bavail * info.f_frsize)
        except OSError:
            row['statvfs_error'] = 'statvfs_failed'
            errors.append({'component': 'filesystems', 'path': mountpoint, 'reason': 'statvfs_failed'})
        rows.append(row)
    return rows


def mount_order(row):
    return (row.get('fs_root', '/') != '/', len(row['mountpoint']), row['mountpoint'])


def filesystems(errors, table=None):
    """장치마다 한 줄(그 장치 전체를 보이는 mount 를 우선). statvfs 실패도 사유와 함께 남긴다."""
    table = mount_table(errors) if table is None else table
    if table is None:
        return None
    rows, seen = [], set()
    for row in sorted(table, key=mount_order):
        if row['device'] in seen:
            continue
        seen.add(row['device'])
        if row.get('statvfs_error'):
            rows.append({'mountpoint': row['mountpoint'], 'fstype': row['fstype'], 'device': row['device'],
                         'error': row['statvfs_error']})
        else:
            rows.append({key: row.get(key) for key in ('mountpoint', 'fstype', 'device', 'total_bytes', 'used_bytes',
                                                       'avail_bytes')})
    return rows



def path_depth(path):
    return 0 if path == '/' else path.count('/')


def du_tree(path, timeout, max_depth=ABS_DEPTH):
    """한 파일시스템만(-x) 훑는다(낮은 우선순위). 폴더 경로→바이트. 부분 실패(권한·시간 초과)도 받은 만큼 쓴다."""
    status, out = timed(['du', '-x', '-B1', '--max-depth=%d' % max_depth, ROOT + path], timeout, low_priority=True)
    sizes = {}
    for line in out.splitlines():
        amount, _, name = line.partition('\t')
        if not amount.isdigit() or not name.startswith(ROOT):
            continue
        name = name[len(ROOT):] or '/'
        if name != '/' and name.endswith('/'):
            name = name.rstrip('/')
        sizes[name or '/'] = int(amount)
    return status, sizes


def children_of(sizes, path):
    prefix = '/' if path == '/' else path + '/'
    return [name for name in sizes if name != path and name.startswith(prefix) and '/' not in name[len(prefix):]]


def ledger(sizes, top):
    """한 파일시스템 scan 안에서만 소유자별로 나눈다. 자식이 있으면 늘 자식으로 내려가고(규칙 경계까지 분해),
    폴더에 직접 있는 파일 몫은 그 폴더 owner 로 둔다. 부모보다 자식 합이 크면 0 으로 덮지 않고 불일치로 남긴다."""
    by_owner, problems = {}, []

    def add(owner, amount):
        by_owner[owner] = by_owner.get(owner, 0) + amount

    def walk(path):
        children = children_of(sizes, path)
        if not children:
            add(owner_of(path), sizes[path])
            return
        remainder = sizes[path] - sum(sizes[c] for c in children)
        if remainder < 0:
            problems.append({'path': path, 'reason': 'children_exceed_parent', 'excess_bytes': -remainder})
            add('inconsistent_remainder', remainder)
        elif remainder:
            add('direct_files_' + owner_of(path), remainder)
        for child in children:
            walk(child)
    walk(top)
    return by_owner, problems


def plan_scans(table):
    """장치마다: FS root('/')를 보이는 mount 하나를 훑는다(입력 순서와 무관하게 정렬해 고른다). 나머지 root '/' mount 는
    duplicate, 하위 폴더 bind 는 bind 로 표시한다. root '/' mount 가 없으면 서로 겹치지 않는 하위 폴더 bind 를 각각 훑고 subtree_only."""
    by_device = {}
    for row in table:
        by_device.setdefault(row['device'], []).append(row)
    scans, skipped = [], []
    for device in sorted(by_device):
        mounts = sorted(by_device[device], key=mount_order)
        full = [m for m in mounts if m.get('fs_root', '/') == '/']
        if full:
            scans.append((full[0], 'full'))
            for other in [m for m in mounts if m is not full[0]]:
                skipped.append({'mountpoint': other['mountpoint'], 'device': device, 'fs_root': other.get('fs_root', '/'),
                                'status': 'skipped_duplicate_device' if other.get('fs_root', '/') == '/'
                                else 'skipped_bind_subtree', 'same_device_as': full[0]['mountpoint']})
            continue
        chosen_roots = []
        for mount in sorted(mounts, key=lambda m: (len(m['fs_root']), m['fs_root'], len(m['mountpoint']), m['mountpoint'])):
            root = mount['fs_root']
            covering = [c for c in chosen_roots if root == c['fs_root'] or root.startswith(c['fs_root'].rstrip('/') + '/')]
            if covering:
                skipped.append({'mountpoint': mount['mountpoint'], 'device': device, 'fs_root': root,
                                'status': 'skipped_bind_subtree', 'same_device_as': covering[0]['mountpoint']})
                continue
            chosen_roots.append(mount)
            scans.append((mount, 'subtree_only'))
    return scans, skipped


def du_section(errors, table, timeout):
    """실제 파일시스템마다 한 번씩(-x) 훑고, 파일시스템별 장부를 따로 만든다. 다른 FS 의 자리표시 크기를 섞지 않는다."""
    if table is None:
        table = [{'mountpoint': '/', 'device': 'unknown', 'fs_root': '/', 'fstype': None}]
        coverage_note = 'mountinfo unavailable; only / scanned, coverage unknown'
    else:
        coverage_note = ('one du -x pass per real filesystem device from /proc/self/mountinfo (the mount that shows the '
                         'filesystem root; subtree-only devices are marked subtree_only); pseudo filesystems excluded')
    scans_plan, fs_rows = plan_scans(table)
    scans, status_of = {}, {}
    for row in fs_rows:
        status_of[row['mountpoint']] = (row['status'], None)
    for mount, coverage in scans_plan:
        mountpoint = mount['mountpoint']
        depth = max(1, ABS_DEPTH - path_depth(mountpoint))
        status, sizes = du_tree(mountpoint, timeout, depth)
        entry = {'mountpoint': mountpoint, 'device': mount['device'], 'fs_root': mount.get('fs_root', '/'),
                 'coverage': coverage, 'max_depth': depth, 'statvfs_used_bytes': mount.get('used_bytes')}
        if mount.get('statvfs_error'):
            entry['statvfs_error'] = mount['statvfs_error']
        if mountpoint not in sizes or status == 'timeout':
            reason = status if status != 'ok' else 'empty'
            entry.update(status='timeout' if status == 'timeout' else 'failed', reason=reason)
            errors.append({'component': 'du', 'path': mountpoint, 'reason': reason})
            if mountpoint in sizes:   # 시간 초과 전 받은 부분은 장부로 남기되 결과는 완료로 보지 않는다
                by_owner, problems = ledger(sizes, mountpoint)
                entry.update(partial_scanned_bytes=sizes[mountpoint], partial_by_owner=by_owner)
            fs_rows.append(entry)
            status_of[mountpoint] = (entry['status'], reason)
            continue
        by_owner, problems = ledger(sizes, mountpoint)
        if status != 'ok':
            state, reason = 'partial', status
            errors.append({'component': 'du', 'path': mountpoint, 'reason': status, 'partial': True})
        elif coverage == 'subtree_only':
            state, reason = 'subtree_only', 'subtree_only'
        else:
            state, reason = 'scanned', None
        entry.update(status=state, reason=reason, scanned_total_bytes=sizes[mountpoint], by_owner=by_owner,
                     consistent=not problems, inconsistencies=problems[:20])
        fs_rows.append(entry)
        scans[mountpoint] = sizes
        status_of[mountpoint] = (state, reason)
    fs_rows.sort(key=lambda r: r['mountpoint'])
    scanned = [r for r in fs_rows if r.get('scanned_total_bytes') is not None]
    overall = {}
    for row in scanned:
        for owner, amount in row['by_owner'].items():
            overall[owner] = overall.get(owner, 0) + amount
    mountpoints = sorted({r['mountpoint'] for r in table})

    def home_mount(path):
        """전체 mount 표에서 그 경로가 실제로 놓인 mount(가장 긴 mountpoint 접두어). 성공한 scan 만 보지 않는다."""
        best = None
        for mountpoint in mountpoints:
            if path == mountpoint or mountpoint == '/' or path.startswith(mountpoint + '/'):
                if best is None or len(mountpoint) > len(best):
                    best = mountpoint
        return best

    def measured(path):
        """(바이트 또는 None, 그 경로의 mount, 상태, 사유). 그 mount 가 훑어지지 않았으면 다른 FS 자리표시 값을 쓰지 않고 null."""
        home = home_mount(path)
        state, reason = status_of.get(home, ('not_scanned', 'no_scan_for_mount'))
        if home in scans and path in scans[home]:
            return scans[home][path], home, state, reason
        return None, home, state, reason if home in scans else (reason or state)

    roots = {}
    for root in DU_ROOTS:
        amount, home, state, reason = measured(root)
        if amount is None and home in scans:
            continue   # 그 FS 는 훑었지만 이 경로가 없다(존재하지 않음)
        entry = {'bytes': amount, 'filesystem': home, 'status': state, 'reason': reason, 'owner': owner_of(root)}
        if amount is not None:
            rows = []
            for child in children_of(scans[home], root):
                child_amount, child_home, child_state, child_reason = measured(child)
                rows.append((child, child_amount, child_home, child_state, child_reason))
            rows.sort(key=lambda item: -(item[1] or 0))
            entry.update(children_listed=min(len(rows), TOP_N), children_total=len(rows),
                         top=[{'path': name, 'bytes': value,
                               'owner': owner_of(name), 'filesystem': child_home, 'status': child_state}
                              for name, value, child_home, child_state, child_reason in rows[:TOP_N]])
        roots[root] = entry
    return {'coverage': coverage_note, 'absolute_max_depth': ABS_DEPTH, 'top_n': TOP_N,
            'units': 'bytes (du -B1, disk usage per filesystem; not additive with docker figures)',
            'filesystems': fs_rows, 'by_owner_overall': overall,
            'overall_scanned_total_bytes': sum(r['scanned_total_bytes'] for r in scanned),
            'incomplete': sorted({r['mountpoint'] for r in fs_rows
                                  if r['status'] not in ('scanned', 'skipped_duplicate_device', 'skipped_bind_subtree')}),
            'roots': roots, 'owner_rules': {owner: list(prefixes) for owner, prefixes in OWNER_RULES}}


def disk_usage():
    errors = []
    out = {'mode': 'disk-usage', 'read_only': True, 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    table = mount_table(errors)
    out['filesystems'] = filesystems(errors, table)
    out['docker'] = docker_usage(errors)
    timeout = int(os.environ.get('NAVER_DEPLOY_DU_TIMEOUT', '300')) if ROOT else 300
    out['du'] = du_section(errors, table, timeout)
    status, text = timed(['journalctl', '--disk-usage'], 60)
    value = binary_bytes(text.split('take up', 1)[1] if 'take up' in text else '') if status == 'ok' else None
    out['journal'] = {'bytes': value, 'units': '1024-based from journalctl, approximate'}
    if value is None:
        errors.append({'component': 'journal', 'reason': status if status != 'ok' else 'unparseable'})
    out['errors'] = errors
    encode_disk_paths(out)
    print('NAVER_DEPLOY_DISK_USAGE=' + json.dumps(out, sort_keys=True, separators=(',', ':')))


def encode_disk_paths(out):
    """경로 필드만 encode_path 로 바꾼다(키 이름·설명 문장은 그대로)."""
    out['path_encoding'] = 'paths use mountinfo-style octal escapes (\\ooo) for space, control, backslash and non-ASCII bytes'
    for row in out.get('filesystems') or []:
        row['mountpoint'] = encode_path(row.get('mountpoint'))
    for error in out.get('errors') or []:
        if 'path' in error:
            error['path'] = encode_path(error['path'])
    du = out.get('du') or {}
    for row in du.get('filesystems') or []:
        for key in ('mountpoint', 'fs_root', 'same_device_as'):
            if key in row:
                row[key] = encode_path(row[key])
        for problem in row.get('inconsistencies') or []:
            problem['path'] = encode_path(problem['path'])
    du['incomplete'] = [encode_path(p) for p in du.get('incomplete') or []]
    roots = {}
    for root, entry in (du.get('roots') or {}).items():
        entry['filesystem'] = encode_path(entry.get('filesystem'))
        for row in entry.get('top') or []:
            row['path'] = encode_path(row['path'])
            row['filesystem'] = encode_path(row.get('filesystem'))
        roots[encode_path(root)] = entry
    if 'roots' in du:
        du['roots'] = roots


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


# ── 21→22 추가형 스키마 이관(migrate-*) — DESIGN-CLAUDE-v3.md(v3.1) ───────────────────────────
# 이 표 밖의 이관은 없다. 입력으로 범위를 넓히지 못한다. helper_sha256 은 naver_schema_migrate.py 의 sha256 이고
# helper 파일 안에는 자기 해시를 두지 않는다(workflow 도 따로 고정한다).
MIGRATIONS = {
    '21-22-exhaust-v1': {
        'from_schema': 21, 'to_schema': 22,
        'from_commit': '377768a132614ae8b9ad0318aa4f87019c11a23a',
        'to_commit': '1d852289209e7f10df71a787934d9fe31c9ffde6',
        'from_store_sha256': 'f5caa352cc817a126e0c6588e7fd81d64d681391ffbc408eccb16dc265271348',
        'to_store_sha256': '741f4309feb375b7eebac0bc9a20e53263a91aa40fcc203b295beca059bfbd63',
        'to_exhaust_sha256': 'e80e2ae844d89918f1240f78bcc107fa7a62e4e64201132be25dc73dd0043c8c',
        'new_tables': {
            'naver_auto_exhaust_head': '7e947b8bb92e25b0645308f3cc84383f31c6370c11ed73d691cfd8e81d20fa5f',
            'naver_auto_exhaust_version': 'dd1241db5550e03c185ad12d782ff40881eb7fd0111daa37ec41357b41c263ad',
            'naver_auto_exhaust_attempt': '0455cf850f84b4f0b70defa297f7e2573e332000d6c617d08c5d210bee9bec29'},
        'autoindexes': ['sqlite_autoindex_naver_auto_exhaust_attempt_1', 'sqlite_autoindex_naver_auto_exhaust_head_1',
                        'sqlite_autoindex_naver_auto_exhaust_version_1'],
        'helper_sha256': '89a239a61c5ab997446a0528780f5a4b106e97c641d8412ff82391891c3148a7'},
    # 22→23(보고 대조 3단계): PR38(9649eae, 스키마 22 코드만)을 일반 deploy 로 먼저 올린 뒤에만. 21-22 run 이 accept(pin released)
    # 되기 전에는 prepare·deploy 를 거절한다(requires_released). 새 표 SCHEMA 는 reconcile_store 하나에서만 온다.
    '22-23-reconcile-v1': {
        'from_schema': 22, 'to_schema': 23,
        'from_commit': '9649eaec4147623e180d67a85ad9dc3461a8b96f',
        'to_commit': '12260dbbc946f76d9bf7e2b8562cccc5474ea9a9',
        'from_store_sha256': '741f4309feb375b7eebac0bc9a20e53263a91aa40fcc203b295beca059bfbd63',
        'to_store_sha256': 'ac0c54bbcf96627e3a17df3a6a5717b62fb8baf717876cddfda5b7bfdbb0ca08',
        'schema_module': {'path': 'naver_engine/reconcile_store.py', 'import': 'naver_engine.reconcile_store',
                          'sha256': 'd04d8a6904fa9d971dac87813f6c8735ad89c4e9ac77f64f9ba45e538e6c85bd'},
        'purpose': 'pre-migration-22-23',
        'requires_released': ['21-22-exhaust-v1'],
        'new_tables': {
            'naver_auto_recon_close_result': 'ca9099dad006c73061a732f78cf10441fdad5871fefd40a4275c32d8e0d0dfe0',
            'naver_auto_recon_month': 'dfd16b8d64d34f10db81d4c9176f9b3dc95a1063481a402281b7f5df66a4cdcd',
            'naver_auto_recon_settlement_event': '7d8d0b265d32ce890a4504e7e0920a5a40ac188355d2db15ca74857951ffa658',
            'naver_auto_recon_settlement_head': 'd702211d0c696a509acc8851208abb47b065d21c6a05ebfaf2bebd8fede8bb58',
            'naver_auto_recon_settlement_row': '7365b09956f60fd059eb529f56520344e795e38cc434abbf407f8c468e239205',
            'naver_auto_recon_settlement_version': 'f713ad26e4dd4773c12f545e6568584f8c6f53a8faa049e1ddca172a8d298521',
            'naver_auto_recon_staff_entry': '3027c77a42d561791f68725ea840c52af21156c153319c9bcb673c5d1e84c098'},
        'autoindexes': ['sqlite_autoindex_naver_auto_recon_close_result_1', 'sqlite_autoindex_naver_auto_recon_month_1',
                        'sqlite_autoindex_naver_auto_recon_settlement_event_1',
                        'sqlite_autoindex_naver_auto_recon_settlement_head_1',
                        'sqlite_autoindex_naver_auto_recon_settlement_row_1',
                        'sqlite_autoindex_naver_auto_recon_settlement_version_1',
                        'sqlite_autoindex_naver_auto_recon_settlement_version_2',
                        'sqlite_autoindex_naver_auto_recon_staff_entry_1'],
        'helper_sha256': '89a239a61c5ab997446a0528780f5a4b106e97c641d8412ff82391891c3148a7'}}
if ROOT and os.environ.get('NAVER_DEPLOY_TEST_MIGRATIONS'):
    MIGRATIONS = json.loads(read(os.environ['NAVER_DEPLOY_TEST_MIGRATIONS']))   # 가짜 루트 시험 전용


def entry_purpose(entry):
    """보관본 purpose. 21-22 항목은 칸이 없어 호환 규칙(pre-migration-<from>-<to>)으로 같은 값."""
    return entry.get('purpose') or 'pre-migration-%d-%d' % (entry['from_schema'], entry['to_schema'])


def entry_schema_module(entry):
    """새 표 SCHEMA 모듈 pin. 21-22 항목은 칸이 없어 호환 규칙(exhaust_store)으로 같은 값."""
    return entry.get('schema_module') or {'path': 'naver_engine/exhaust_store.py', 'import': 'naver_engine.exhaust_store',
                                          'sha256': entry['to_exhaust_sha256']}


MANIFEST_PURPOSES = {entry_purpose(e): e['from_schema'] for e in MIGRATIONS.values()}

STATE_DIR_PATH = '/var/lib/metainc/naver-deploy'
MIG_DIR = STATE_DIR_PATH + '/migration'
MIG_POINTER = STATE_DIR_PATH + '/migration-active'
MIG_HOLD = STATE_DIR_PATH + '/migration-hold'
MIG_PINS = STATE_DIR_PATH + '/pins'
DATA_PATH = '/var/lib/metainc/naver-engine'
DAILY_BACKUPS = '/var/backups/metainc/naver-engine'
UNIT_PATH = '/etc/systemd/system'
DROPIN_NAME = '50-naver-migration-hold.conf'
DROPIN_BODY = ('# naver-deploy migrate-* 임시 시작 차단(재부팅·의존 시작 포함). 정상 완료 때 지운다.\n'
               '[Unit]\nAssertPathExists=!/var/lib/metainc/naver-deploy/migration-hold\n'
               'AssertPathExists=/var/lib/metainc/naver-engine/engine.db\n')
MIG_UNITS = ('metainc-naver-engine.service', 'metainc-naver-relay.service')
MIB = 1024 * 1024
FLOOR = 1 << 30
GZ_CAP_RATIO = 0.35
ARCHIVE_SECONDS = 30 * 60
ENGINE_UID = 10001
MIG_STATES = ('ACTIVE', 'HEALTHY', 'HOLD', 'COMPLETED', 'ROLLED_BACK')
PIN_STATES = ('pending', 'bound-raw', 'bound-gz', 'released')


def mig_entry(identifier):
    if identifier not in MIGRATIONS:
        fail('MIGRATION_UNKNOWN: 고정 표에 없는 이관입니다')
    return MIGRATIONS[identifier]


def mig_field(identifier, field):
    value = mig_entry(identifier)[field]
    print(json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value)


def write_json_atomic(path, value, mode=0o600, owner=None):
    temporary = path + '.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'w') as handle:
        json.dump(value, handle, sort_keys=True, indent=1)
        handle.write('\n')
        handle.flush()
        if owner is not None and not ROOT:
            os.fchown(handle.fileno(), owner, owner)
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_folder(os.path.dirname(path))


def fsync_folder(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def load_json(path, default=None):
    if not os.path.lexists(path):
        return default
    if os.path.islink(path):
        fail('MIGRATION_LAYOUT: 링크인 기록 파일 %s' % path[len(ROOT):])
    try:
        return json.loads(read(path))
    except ValueError:
        fail('MIGRATION_LAYOUT: 기록을 해석하지 못했습니다 %s' % os.path.basename(path))


def run_dir(run):
    if not RUN_ID_RE.match(run):
        fail('MIGRATION_INPUT: run id 형식')
    path = ROOT + MIG_DIR + '/' + run
    os.makedirs(path, 0o700, exist_ok=True)
    return path


# ── pin(복귀 묶음) ──
def pinned_rollback():
    """released 가 아닌 모든 pin 의 (커밋들, 이미지 ID 들). 정리·prune 이 반드시 존중한다.
    pin 폴더가 없으면(처음) 빈 집합. 폴더가 아니거나·모르는 항목·읽을 수 없는 pin·필수 칸이 빠지거나 형식이 틀리면
    보호를 조용히 빼지 않고 거부한다(정리 계획·prune 전체가 멈춘다)."""
    commits, images = set(), set()
    folder = ROOT + MIG_PINS
    if not os.path.lexists(folder):
        return commits, images
    if os.path.islink(folder) or not os.path.isdir(folder):
        fail('PIN_LAYOUT: pin 폴더가 실제 폴더가 아닙니다')
    for name in sorted(os.listdir(folder)):
        if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.json', name):
            fail('PIN_LAYOUT: pin 폴더에 예상하지 못한 항목 %s' % name)
        path = os.path.join(folder, name)
        if os.path.islink(path) or not os.path.isfile(path):
            fail('PIN_LAYOUT: pin 이 일반 파일이 아닙니다 %s' % name)
        value = load_json(path, None)
        if not isinstance(value, dict) or value.get('state') not in PIN_STATES:
            fail('PIN_LAYOUT: pin 상태 이상 %s' % name)
        if value['state'] == 'released':
            continue
        if not HEX40.match(str(value.get('commit', ''))) or not all(
                re.fullmatch(r'sha256:[0-9a-f]{64}', str(value.get(key, ''))) for key in ('engine_image', 'relay_image')):
            fail('PIN_LAYOUT: pin 필수 칸(commit·engine_image·relay_image)이 없거나 형식이 다릅니다 %s' % name)
        commits.add(value['commit'])
        images.update((value['engine_image'], value['relay_image']))
    return commits, images


def mig_pin(run, action, *pairs):
    """pending(M3) → bound-raw(chain 뒤) → bound-gz(gzip 게시·검증 뒤, raw 삭제 전) → released(accept)."""
    os.makedirs(ROOT + MIG_PINS, 0o700, exist_ok=True)
    path = ROOT + MIG_PINS + '/' + run + '.json'
    current = load_json(path, {})
    fields = dict(pair.partition('=')[::2] for pair in pairs)
    order = {'create': ('', 'pending'), 'bind-raw': ('pending', 'bound-raw'), 'bind-gz': ('bound-raw', 'bound-gz'),
             'release': (None, 'released')}
    if action == 'state':
        print(current.get('state', ''))
        return
    if action == 'check':
        if current.get('state') not in ('bound-raw', 'bound-gz'):
            fail('PIN_NOT_BOUND: R7 은 bound 된 복귀 묶음만 씁니다')
        for key in ('engine_unit_sha256', 'relay_unit_sha256', 'engine_override_sha256', 'relay_override_sha256'):
            name = {'engine_unit_sha256': 'metainc-naver-engine.service', 'relay_unit_sha256': 'metainc-naver-relay.service',
                    'engine_override_sha256': 'preview-engine.override.yml',
                    'relay_override_sha256': 'preview-relay.override.yml'}[key]
            copy = ROOT + current['run_dir'] + '/' + name
            if not os.path.isfile(copy) or os.path.islink(copy) or file_sha(copy) != current[key]:
                fail('PIN_MEMBER_CHANGED: 보관된 v21 사본 %s 이 pin 과 다릅니다' % name)
        release = ROOT + RELEASES + '/naver-' + current['commit']
        if not os.path.isdir(release):
            fail('PIN_MEMBER_CHANGED: v21 release 폴더가 없습니다')
        print(current['state'])
        return
    if action not in order:
        fail('MIGRATION_INPUT: pin 동작')
    before, after = order[action]
    if before is not None and current.get('state', '') != before:
        fail('PIN_STATE: %s → %s 전이가 아닙니다(현재 %s)' % (before or '없음', after, current.get('state') or '없음'))
    current.update(fields)
    current['state'] = after
    current['run'] = run
    current.setdefault('history', []).append([after, time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())])
    write_json_atomic(path, current)


# ── 이관 기록: 활성 표지·상태·hold·drop-in·저널 ──
def mig_pointer(action, run=''):
    path = ROOT + MIG_POINTER
    if action == 'get':
        print(read(path).strip() if os.path.isfile(path) and not os.path.islink(path) else '')
    elif action == 'set':
        if os.path.lexists(path) and read(path).strip() != run:
            fail('MIGRATION_ACTIVE: 다른 이관 run 이 활성입니다')
        fd = os.open(path + '.tmp', os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(run + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(path + '.tmp', path)
        fsync_folder(os.path.dirname(path))
    elif action == 'clear':
        if os.path.lexists(path):
            if read(path).strip() != run:
                fail('MIGRATION_ACTIVE: 다른 run 의 활성 표지는 지우지 않습니다')
            os.unlink(path)
            fsync_folder(os.path.dirname(path))
    else:
        fail('MIGRATION_INPUT: pointer 동작')


def mig_status(run, *pairs):
    path = run_dir(run) + '/status.json'
    for pair in pairs:
        key, _, value = pair.partition('=')
        if key == 'state' and value not in MIG_STATES:
            fail('MIGRATION_INPUT: 상태 이름')
    state_write(path, *pairs)


def mig_status_get(run, key):
    path = ROOT + MIG_DIR + '/' + run + '/status.json'
    print((load_json(path, {}) or {}).get(key, ''))


def mig_hold(action, run=''):
    path = ROOT + MIG_HOLD
    if action == 'get':
        print(read(path).split()[0] if os.path.isfile(path) and read(path).split() else ('unknown' if os.path.lexists(path) else ''))
        return
    if action == 'create':
        if os.path.lexists(path):
            existing = read(path).split()
            if not existing or existing[0] != run:
                fail('HOLD_OTHER_RUN: 다른 run 의 hold 가 있습니다')
            return
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(run + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        fsync_folder(os.path.dirname(path))
    elif action == 'remove':
        if not os.path.lexists(path):
            return
        existing = read(path).split()
        if not existing or existing[0] != run:
            fail('HOLD_OTHER_RUN: 같은 run 의 hold 만 지웁니다')
        os.unlink(path)
        fsync_folder(os.path.dirname(path))
    else:
        fail('MIGRATION_INPUT: hold 동작')


def mig_dropin(action):
    paths = [ROOT + UNIT_PATH + '/' + unit + '.d/' + DROPIN_NAME for unit in MIG_UNITS]
    if action == 'present':
        print('yes' if any(os.path.lexists(p) for p in paths) else 'no')
    elif action == 'install':
        for path in paths:
            os.makedirs(os.path.dirname(path), 0o755, exist_ok=True)
            fd = os.open(path + '.tmp', os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, 'w') as handle:
                handle.write(DROPIN_BODY)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(path + '.tmp', path)
            fsync_folder(os.path.dirname(path))
    elif action == 'check':
        for path in paths:
            if not os.path.isfile(path) or os.path.islink(path) or read(path) != DROPIN_BODY:
                fail('DROPIN_MISSING: 시작 차단 drop-in 이 없거나 다릅니다')
    elif action == 'remove':
        for path in paths:
            if os.path.lexists(path):
                if os.path.islink(path) or read(path) != DROPIN_BODY:
                    fail('DROPIN_FOREIGN: 우리 것이 아닌 drop-in 은 지우지 않습니다')
                os.unlink(path)
                folder = os.path.dirname(path)
                fsync_folder(folder)
                if not os.listdir(folder):
                    os.rmdir(folder)
    else:
        fail('MIGRATION_INPUT: drop-in 동작')


def mig_journal(data_dir, action, *args):
    path = data_dir + '/naver-migrate-journal.json'
    value = load_json(path, None)
    if action == 'last':
        entries = (value or {}).get('entries') or []
        print(' '.join([entries[-1]['op'], entries[-1]['phase']]) if entries else '')
    elif action == 'has':
        op, phase = args
        print('yes' if any(e['op'] == op and e['phase'] == phase for e in (value or {}).get('entries') or []) else 'no')
    elif action == 'append':
        run, op, phase = args[:3]
        if value is None:
            value = {'run': run, 'entries': []}
        if value.get('run') != run:
            fail('JOURNAL_OTHER_RUN: 다른 run 의 저널입니다')
        value['entries'].append({'seq': len(value['entries']) + 1, 'op': op, 'phase': phase, 'by': 'host',
                                 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        owner = os.lstat(path).st_uid if os.path.exists(path) else ENGINE_UID
        write_json_atomic(path, value, 0o600, owner=owner)
    elif action == 'run':
        print((value or {}).get('run', ''))
    elif action == 'move':
        run = args[0]
        if value is None:
            return
        if value.get('run') != run:
            fail('JOURNAL_OTHER_RUN: 다른 run 의 저널은 옮기지 않습니다')
        target = run_dir(run) + '/journal.json'
        if os.stat(os.path.dirname(target)).st_dev == os.stat(data_dir).st_dev:
            os.rename(path, target)
        else:
            write_json_atomic(target, value)
            if load_json(target) != value:
                fail('JOURNAL_MOVE: 복사 대조 실패')
            os.unlink(path)
        fsync_folder(data_dir)
        fsync_folder(os.path.dirname(target))
    else:
        fail('MIGRATION_INPUT: journal 동작')


def mig_receipt(data_dir, run, action='copy'):
    """helper 가 DATA_DIR 에 남긴 영수증을 run 폴더로 복사(원본은 둔다)하고 sha256 을 낸다."""
    source = data_dir + '/naver-migrate-receipt.json'
    target = run_dir(run) + '/receipt.json'
    if action == 'copy':
        value = load_json(source)
        if not isinstance(value, dict) or value.get('run') != run:
            fail('RECEIPT: 이 run 의 영수증이 아닙니다')
        write_json_atomic(target, value)
        if os.path.exists(source):
            os.unlink(source)
            fsync_folder(data_dir)
    print(hashlib.sha256(json.dumps(load_json(target), sort_keys=True).encode()).hexdigest())


def mig_receipt_get(run, key):
    value = load_json(ROOT + MIG_DIR + '/' + run + '/receipt.json', {}) or {}
    item = value.get(key)
    print(json.dumps(item, sort_keys=True) if isinstance(item, (dict, list)) else ('' if item is None else item))


def mig_receipt_set(run, key, value_json):
    path = run_dir(run) + '/receipt.json'
    value = load_json(path, {})
    value[key] = json.loads(value_json)
    write_json_atomic(path, value)


def mig_args(identifier, step, mode, *pairs):
    """helper 인자 JSON. 단계에 맞는 pin 만 고정 표에서 넣는다. key=@file 은 그 JSON 파일 내용."""
    entry = mig_entry(identifier)
    args = {'mode': mode, 'migration_id': identifier}
    new_pins = {'store_sha256': entry['to_store_sha256'], 'schema_module': entry_schema_module(entry),
                'schema': entry['to_schema'], 'from_schema': entry['from_schema'],
                'new_tables': entry['new_tables'], 'autoindexes': entry['autoindexes']}
    old_pins = {'store_sha256': entry['from_store_sha256'], 'schema': entry['from_schema']}
    if step in ('chain', 'probe-new'):
        args['pins'] = new_pins
    elif step in ('seed', 'v21-refuses', 'v21-opens', 'old-refuses', 'old-opens', 'probe-old'):
        args['pins'] = old_pins
    for pair in pairs:
        key, _, value = pair.partition('=')
        if value.startswith('@'):
            args[key] = load_json(value[1:])
        elif value.startswith('json:'):
            args[key] = json.loads(value[5:])
        else:
            args[key] = value
    print(json.dumps(args, sort_keys=True, separators=(',', ':')))


def mig_tar_pins(path, identifier, current, new, schema_current, schema_new):
    entry = mig_entry(identifier)
    if (int(schema_current), int(schema_new)) != (entry['from_schema'], entry['to_schema']):
        fail('MIGRATION_SCHEMA_PAIR: 스키마 쌍이 고정 표와 다릅니다')
    if current != entry['from_commit'] or new != entry['to_commit']:
        fail('MIGRATION_COMMIT_PIN: 실행 중/새 커밋이 고정 표와 다릅니다')
    archive, items = members(path)
    module = entry_schema_module(entry)
    wanted = {'naver_engine/store.py': entry['to_store_sha256'], module['path']: module['sha256']}
    table = dict(items)
    for name, expected in wanted.items():
        if name not in table or hashlib.sha256(archive.extractfile(table[name]).read()).hexdigest() != expected:
            fail('MIGRATION_SOURCE_PIN: %s 해시가 고정 표와 다릅니다' % name)
    print('ok')


def mig_requires(identifier):
    """앞선 이관의 복귀 pin 이 released(대표 accept) 여야 다음 이관을 준비한다. pin 을 못 읽으면 거부."""
    entry = mig_entry(identifier)
    needed = set(entry.get('requires_released') or ())
    folder = ROOT + MIG_PINS
    if needed and os.path.isdir(folder):
        pinned_rollback()   # 손상 pin 이면 여기서 거부
        for name in sorted(os.listdir(folder)):
            value = load_json(os.path.join(folder, name), {}) or {}
            if value.get('migration_id') in needed and value.get('state') != 'released':
                fail('MIGRATION_ORDER: 앞선 이관(%s)이 아직 accept 되지 않았습니다' % value.get('migration_id'))
    print('ok')


def mig_store_sha_stdin(identifier):
    body = tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())).extractfile('store.py').read()
    if hashlib.sha256(body).hexdigest() != mig_entry(identifier)['from_store_sha256']:
        fail('MIGRATION_RUNNING_PIN: 실행 중 이미지의 store.py 가 고정 표의 v21 과 다릅니다')
    print('ok')


def mig_helper_pin(path, identifier):
    if file_sha(path) != mig_entry(identifier)['helper_sha256']:
        fail('MIGRATION_HELPER_PIN: helper 해시가 고정 표와 다릅니다')
    print('ok')


def file_sha(path):
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        while True:
            chunk = os.read(fd, MIB)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


# ── 시각 창·공간 ──
def kst_now():
    fake = os.environ.get('NAVER_DEPLOY_FAKE_KST') if ROOT else None
    if fake:
        return fake
    return time.strftime('%Y-%m-%dT%H:%M', time.gmtime(time.time() + 9 * 3600))


def mig_window(cutoff, state_path, after_utc_stamp=''):
    """오늘(KST) OFFSITE_OK·pending 없음·building 없음·시각 < cutoff. after 가 있으면 그 배포 뒤의 OFFSITE_OK 여야 한다."""
    now = kst_now()
    try:
        value = json.loads(read(state_path))
    except (OSError, ValueError):
        fail('WINDOW: 백업 상태를 읽지 못했습니다')
    if value.get('code') != 'OFFSITE_OK' or value.get('pending') is not None or value.get('last_offsite_day') != now[:10]:
        fail('WINDOW: 오늘 OFFSITE_OK·pending 없음 조건이 아닙니다')
    folder = os.path.dirname(state_path)
    for place in (folder, os.path.join(folder, 'local'), os.path.join(folder, 'outgoing')):
        if os.path.isdir(place) and any(re.fullmatch(r'\.building-[a-z0-9_]{8}', name) for name in os.listdir(place)):
            fail('WINDOW: 일일 백업이 진행 중입니다')
    if now[11:16] >= cutoff:
        fail('WINDOW: KST %s 이후입니다' % cutoff)
    if after_utc_stamp:
        after = time.mktime(time.strptime(after_utc_stamp, '%Y%m%dT%H%M%SZ')) - time.timezone
        if os.stat(state_path).st_mtime <= after:
            fail('WINDOW: 직전 배포 뒤의 새 OFFSITE_OK 가 아닙니다')
    print('ok')


def free_of(path):
    fake = os.environ.get('NAVER_DEPLOY_FAKE_FREE_BYTES') if ROOT else None
    info = os.statvfs(path)
    return int(fake) if fake else info.f_bavail * info.f_frsize


def size_or_zero(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return 0
    if stat.S_ISDIR(info.st_mode):
        return sum(size_or_zero(os.path.join(path, n)) for n in os.listdir(path))
    return info.st_size


def newest_pair(folder):
    """일일 백업의 최신 쌍(ZIP 은 local/, 같은 이름의 CMS 는 outgoing/ — 제품 BackupJob 배치). 하나라도 없으면 None."""
    local, outgoing = os.path.join(folder, 'local'), os.path.join(folder, 'outgoing')
    if not os.path.isdir(local) or not os.path.isdir(outgoing):
        return None
    zips = sorted(n for n in os.listdir(local) if re.fullmatch(r'naver-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.zip', n))
    if not zips:
        return None
    zip_path, cms_path = os.path.join(local, zips[-1]), os.path.join(outgoing, zips[-1][:-4] + '.cms')
    if not os.path.isfile(cms_path) or os.path.islink(cms_path) or os.path.islink(zip_path):
        return None
    return os.lstat(zip_path).st_size, os.lstat(cms_path).st_size


def keep_raw_now(data_dir, backups):
    """P_pol(대표 승인 정책 임계치 — 미래 백업 성공 보장이 아님) = max(S+Z, Z+E, Z+2E+H), S = 지금 DB+WAL.
    지금의 장치 여유 ≥ 1GiB + P_pol 이면 true. 측정 실패·다른 장치·백업 쌍 없음은 unknown."""
    try:
        if os.stat(data_dir).st_dev != os.stat(backups).st_dev:
            print('unknown')
            return
        pair = newest_pair(backups)
        if pair is None:
            print('unknown')
            return
        z, e = pair
        s = size_or_zero(data_dir + '/engine.db') + size_or_zero(data_dir + '/engine.db-wal')
        policy = max(s + z, z + e, z + 2 * e + MIB)
        print('true' if free_of(data_dir) >= FLOOR + policy else 'false')
    except OSError:
        print('unknown')


def mig_guard(*pairs):
    """장치별 실측 여유 ≥ 필요 + 1GiB. 장치끼리 합치지 않는다."""
    needs = {}
    for pair in pairs:
        path, _, amount = pair.rpartition('=')
        device = os.stat(path).st_dev
        needs.setdefault(device, [path, 0])[1] += int(amount)
    for device, (path, need) in needs.items():
        free = free_of(path)
        if free < need + FLOOR:
            fail('SPACE: 필요 %d + 1GiB, 여유 %d' % (need, free))
    print('ok')


# ── gzip 보관(v2 manifest, pinned)·검증·raw 삭제·gz 복원 ──
def mig_archive(data_dir, db_backups, run, commit, receipt_path, identifier):
    partial = db_backups + '/' + run + '.partial'
    try:
        archive_inner(data_dir, db_backups, run, commit, receipt_path, identifier)
    except BaseException as error:
        # 어떤 실패든(거부·I/O·중단) 부분본은 자동으로 지우지 않는다(대표 확인 뒤 정리).
        # 일반 partial-prune 이 보지 않는 이름으로 옮겨 둔다.
        if os.path.isdir(partial) and not os.path.islink(partial):
            target, number = db_backups + '/' + run + '.archive-failed', 1
            while os.path.lexists(target):
                number += 1
                target = db_backups + '/' + run + '.archive-failed-%d' % number
            os.rename(partial, target)
            fsync_folder(db_backups)
        if isinstance(error, Refuse):
            raise
        fail('ARCHIVE_FAILED: %s' % type(error).__name__)


def archive_inner(data_dir, db_backups, run, commit, receipt_path, identifier):
    entry = mig_entry(identifier)
    """engine.db.pre-v22 → naver-deploy-db/<run>.partial/engine.db.gz(gzip6) → 풀어서 sha 대조 → manifest v2(pinned) →
    폴더 이름 바꾸기로 게시. raw 는 여기서 지우지 않는다(G4 뒤 따로). 실패·상한 초과면 부분본을 남기고 거부."""
    import gzip
    receipt = load_json(receipt_path)
    pre = data_dir + '/engine.db.pre-v22'
    fd = os.open(pre, os.O_RDONLY | os.O_NOFOLLOW)
    started = time.monotonic()
    try:
        st = os.fstat(fd)
        expect = receipt['pre_identity']
        if (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) != (expect['dev'], expect['ino'], expect['size'],
                                                                     expect['mtime_ns']):
            fail('ARCHIVE_SOURCE: raw 원본 identity 가 영수증과 다릅니다')
        name = run
        partial = db_backups + '/' + name + '.partial'
        final = db_backups + '/' + name
        if os.path.lexists(final):
            fail('ARCHIVE_EXISTS: 같은 이름의 사본이 이미 있습니다')
        os.makedirs(db_backups, 0o700, exist_ok=True)
        if not os.path.isdir(partial):
            os.mkdir(partial, 0o700)
        target = partial + '/engine.db.gz'
        cap = int(st.st_size * GZ_CAP_RATIO) + MIB
        if ROOT and os.environ.get('NAVER_DEPLOY_FAKE_ARCHIVE_FAIL'):
            with open(target, 'wb') as handle:
                handle.write(b'partial')
            if os.environ['NAVER_DEPLOY_FAKE_ARCHIVE_FAIL'] == 'oserror':
                raise OSError(28, 'injected')
            fail('ARCHIVE_INJECTED: 시험용 보관 실패')
        raw_digest = hashlib.sha256()
        out = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(out, 'wb') as handle:
            with gzip.GzipFile(filename='', mode='wb', fileobj=handle, compresslevel=6, mtime=0) as zipped:
                while True:
                    chunk = os.read(fd, MIB)
                    if not chunk:
                        break
                    raw_digest.update(chunk)
                    zipped.write(chunk)
                    if handle.tell() > cap:
                        fail('ARCHIVE_CAP: 압축본이 상한을 넘었습니다')
                    if time.monotonic() - started > ARCHIVE_SECONDS or kst_now()[11:16] >= '23:30':
                        fail('ARCHIVE_TIMEOUT: 압축 시간 상한 또는 KST 23:30')
            handle.flush()
            os.fsync(handle.fileno())
        if raw_digest.hexdigest() != receipt['pre_sha256']:
            fail('ARCHIVE_SOURCE: 읽은 원본 sha 가 영수증과 다릅니다')
        check_digest, total = hashlib.sha256(), 0
        with gzip.open(target, 'rb') as zipped:
            while True:
                chunk = zipped.read(MIB)
                if not chunk:
                    break
                check_digest.update(chunk)
                total += len(chunk)
        if check_digest.hexdigest() != receipt['pre_sha256'] or total != st.st_size:
            fail('ARCHIVE_VERIFY: 푼 내용이 원본과 다릅니다')
        if commit != entry['from_commit']:
            fail('ARCHIVE_SOURCE: 보관할 원본 커밋이 이관 항목의 from 과 다릅니다')
        manifest = {'version': 2, 'schema': entry['from_schema'], 'source_commit': commit, 'purpose': entry_purpose(entry),
                    'pinned': True, 'run': run,
                    'files': {'engine.db': {'size': st.st_size, 'sha256': receipt['pre_sha256'], 'stored': 'gzip',
                                            'gz_size': os.path.getsize(target), 'gz_sha256': file_sha(target)}}}
        if manifest_v2(manifest) is None:
            fail('ARCHIVE_MANIFEST: v2 형식 오류')
        write_json_atomic(partial + '/manifest.json', manifest)
        os.rename(partial, final)
        fsync_folder(db_backups)
        print(name, manifest['files']['engine.db']['gz_sha256'],
              hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest())
    finally:
        os.close(fd)


def mig_unlink_pre(data_dir, receipt_path):
    receipt = load_json(receipt_path)
    pre = data_dir + '/engine.db.pre-v22'
    st = os.lstat(pre)
    expect = receipt['pre_identity']
    if (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) != (expect['dev'], expect['ino'], expect['size'],
                                                                 expect['mtime_ns']):
        fail('RAW_IDENTITY: 지울 raw 가 영수증 원본이 아닙니다')
    for suffix in ('-wal', '-shm', '-journal'):
        if os.path.lexists(pre + suffix):
            fail('RAW_SIDECAR: raw 원본 곁 파일이 있습니다')
    os.unlink(pre)
    fsync_folder(data_dir)
    print('ok')


def mig_restore_gz(copy_dir, data_dir, run, receipt_path, identifier):
    """gz → engine.db.restore.partial(O_EXCL·0600·10001) → 전체 sha·크기 확인 → restored_identity 를 영수증에
    먼저 내구 기록 → canonical 로 게시(rename). canonical·곁 파일이 없어야 한다."""
    import gzip
    receipt = load_json(receipt_path)
    manifest = manifest_v2(load_json(copy_dir + '/manifest.json'))
    entry = mig_entry(identifier)
    if manifest is None or manifest['run'] != run or manifest['files']['engine.db']['sha256'] != receipt['pre_sha256']:
        fail('RESTORE_SOURCE: 고정 사본 manifest 가 이 run 의 원본이 아닙니다')
    if (manifest['purpose'] != entry_purpose(entry) or manifest['schema'] != entry['from_schema']
            or manifest['source_commit'] != entry['from_commit']):
        fail('RESTORE_SOURCE: 고정 사본이 이 run 의 이관 항목(purpose·schema·source_commit)과 다릅니다')
    if file_sha(copy_dir + '/engine.db.gz') != manifest['files']['engine.db']['gz_sha256']:
        fail('RESTORE_SOURCE: gz 해시가 manifest 와 다릅니다')
    canonical = data_dir + '/engine.db'
    if any(os.path.lexists(canonical + s) for s in ('', '-wal', '-shm', '-journal')):
        fail('RESTORE_TARGET: canonical 또는 곁 파일이 아직 있습니다')
    partial = data_dir + '/engine.db.restore.partial'
    out = os.open(partial, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        digest, total = hashlib.sha256(), 0
        with gzip.open(copy_dir + '/engine.db.gz', 'rb') as zipped:
            while True:
                chunk = zipped.read(MIB)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
                view = memoryview(chunk)
                while view:
                    view = view[os.write(out, view):]
        os.fsync(out)
        if not ROOT:
            os.fchown(out, ENGINE_UID, ENGINE_UID)
        check = hashlib.sha256()
        os.lseek(out, 0, os.SEEK_SET)
        while True:
            chunk = os.read(out, MIB)
            if not chunk:
                break
            check.update(chunk)
        if digest.hexdigest() != receipt['pre_sha256'] or check.hexdigest() != receipt['pre_sha256'] \
                or total != manifest['files']['engine.db']['size']:
            fail('RESTORE_VERIFY: 풀어 쓴 내용이 원본과 다릅니다')
        st = os.fstat(out)
        restored = {'dev': st.st_dev, 'ino': st.st_ino, 'size': st.st_size, 'mtime_ns': st.st_mtime_ns}
    finally:
        os.close(out)
    mig_receipt_set(run, 'restored_identity', json.dumps(restored))
    os.rename(partial, canonical)
    fsync_folder(data_dir)
    print(json.dumps(restored, sort_keys=True))


# ── 계획(plan_sha256: 바뀌지 않는 값만 해시) ──
def mig_plan(identifier, current, new, tar_sha, helper_sha, engine_image, relay_image, prev_engine, prev_relay):
    entry = mig_entry(identifier)
    data = sorted(n for n in os.listdir(ROOT + DATA_PATH) if n.startswith('engine.db'))
    stable = {'migration_id': identifier, 'entry': entry, 'current_commit': current, 'new_commit': new,
              'source_tar_sha256': tar_sha, 'helper_sha256': helper_sha, 'prepared_engine_image': engine_image,
              'prepared_relay_image': relay_image, 'previous_engine_image': prev_engine,
              'previous_relay_image': prev_relay, 'data_dir_names': data,
              'policy': {'floor_bytes': FLOOR, 'p_pol': 'max(S+Z, Z+E, Z+2E+H), H=1MiB, owner policy threshold, '
                                                       'not a backup guarantee', 'gz_cap_ratio': GZ_CAP_RATIO}}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    live = {'free_bytes': free_of(ROOT + DATA_PATH), 'db_bytes': size_or_zero(ROOT + DATA_PATH + '/engine.db'),
            'wal_bytes': size_or_zero(ROOT + DATA_PATH + '/engine.db-wal')}
    pair = newest_pair(ROOT + DAILY_BACKUPS) if os.path.isdir(ROOT + DAILY_BACKUPS) else None
    live['last_backup_pair_bytes'] = list(pair) if pair else None
    print(digest)
    print(json.dumps({'plan_sha256': digest, 'stable': stable, 'live_not_hashed': live,
                      'reference_estimates_not_gates': 'see design §D'}, sort_keys=True, separators=(',', ':')))


def mig_prepared(action, new, *pairs):
    path = ROOT + MIG_DIR + '/prepared-' + new + '.json'
    if action == 'write':
        os.makedirs(ROOT + MIG_DIR, 0o700, exist_ok=True)
        write_json_atomic(path, dict(pair.partition('=')[::2] for pair in pairs))
    elif action == 'get':
        value = load_json(path, {}) or {}
        print(value.get(pairs[0], ''))
    else:
        fail('MIGRATION_INPUT: prepared 동작')


def mig_observe(run, data_dir, *pairs):
    """복구 전에 원래 관측을 남긴다(이후 만든 hold 를 근거로 쓰지 않게). 값·비밀은 없다."""
    folder = run_dir(run)
    names = sorted(n for n in os.listdir(folder) if re.fullmatch(r'observation-[0-9]+\.json', n))
    files = {}
    for name in sorted(os.listdir(data_dir)):
        if name.startswith('engine.db') or name.startswith('naver-migrate-'):
            info = os.lstat(os.path.join(data_dir, name))
            files[name] = {'dev': info.st_dev, 'ino': info.st_ino, 'size': info.st_size, 'mtime_ns': info.st_mtime_ns,
                           'kind': 'dir' if stat.S_ISDIR(info.st_mode) else 'file'}
    journal = load_json(data_dir + '/naver-migrate-journal.json', None) or {}
    hold = ROOT + MIG_HOLD
    value = {'n': len(names) + 1, 'pointer_present': os.path.lexists(ROOT + MIG_POINTER),
             'hold_present': os.path.lexists(hold), 'hold_run': read(hold).split()[0] if os.path.isfile(hold) and read(hold).split() else '',
             'dropins_present': any(os.path.lexists(ROOT + UNIT_PATH + '/' + u + '.d/' + DROPIN_NAME) for u in MIG_UNITS),
             'status': (load_json(ROOT + MIG_DIR + '/' + run + '/status.json', {}) or {}).get('state', ''),
             'journal_ops': [[e.get('op'), e.get('phase')] for e in journal.get('entries') or []],
             'files': files, 'extra': dict(pair.partition('=')[::2] for pair in pairs),
             'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    write_json_atomic(folder + '/observation-%d.json' % value['n'], value)
    print(folder + '/observation-%d.json' % value['n'])


def mig_rehearsal(action, *args):
    path = ROOT + MIG_DIR + '/rehearsal.json'
    if action == 'write':
        os.makedirs(ROOT + MIG_DIR, 0o700, exist_ok=True)
        write_json_atomic(path, dict(pair.partition('=')[::2] for pair in args))
    elif action == 'check':
        engine, relay, helper = args
        value = load_json(path, {}) or {}
        if (value.get('result') != 'passed' or value.get('engine_image') != engine or value.get('relay_image') != relay
                or value.get('helper_sha256') != helper):
            fail('REHEARSAL_MISSING: 이 준비 이미지·helper 로 통과한 리허설 기록이 없습니다')
        print('ok')
    else:
        fail('MIGRATION_INPUT: rehearsal 동작')


def identity_line(path):
    info = os.lstat(path)
    print(json.dumps({'dev': info.st_dev, 'ino': info.st_ino, 'size': info.st_size, 'mtime_ns': info.st_mtime_ns},
                     sort_keys=True))


def same_device_inode(first, second):
    a, b = os.stat(first), os.stat(second)
    print('same' if (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino) else 'different')


def json_field(text, *keys):
    value = json.loads(text)
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    print(json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else ('' if value is None else value))


def ino_of(text):
    value = json.loads(text)
    print('%s:%s' % (value['dev'], value['ino']))


MIG_COMMANDS = {
    'mig-field': mig_field, 'mig-pin': mig_pin, 'mig-pointer': mig_pointer, 'mig-status': mig_status,
    'mig-status-get': mig_status_get, 'mig-hold': mig_hold, 'mig-dropin': mig_dropin, 'mig-journal': mig_journal,
    'mig-receipt': mig_receipt, 'mig-receipt-get': mig_receipt_get, 'mig-receipt-set': mig_receipt_set,
    'mig-args': mig_args, 'mig-tar-pins': mig_tar_pins, 'mig-store-sha-stdin': mig_store_sha_stdin,
    'mig-requires': mig_requires,
    'mig-helper-pin': mig_helper_pin, 'mig-window': mig_window, 'mig-keep-raw-now': keep_raw_now,
    'mig-guard': mig_guard, 'mig-archive': mig_archive, 'mig-unlink-pre': mig_unlink_pre,
    'mig-restore-gz': mig_restore_gz, 'mig-plan': mig_plan, 'mig-prepared': mig_prepared,
    'mig-observe': mig_observe, 'mig-rehearsal': mig_rehearsal, 'identity': identity_line,
    'same-device-inode': same_device_inode, 'json-field': json_field, 'ino-of': ino_of,
    'file-sha': lambda path: print(file_sha(path)), 'kst-now': lambda: print(kst_now())}


# ── 고정 nginx 단계(nginx-plan / nginx-apply) — 보고 대조 업로드 두 경로만 4MiB ──────────────────────────
# 제품 커밋의 두 파일(sha 고정)에서만 내용을 가져온다. 바꾸는 파일은 정확히 둘:
#   ① http {} 의 conf.d 에 새 zone 파일 하나(제품 deploy/naver-engine-nginx-http.conf 그대로)
#   ② dashboard server {} 가 include 하는 관제 snippet 하나에 정확 일치 location 두 개를 더한다
#      (제품 deploy/naver-engine-nginx.conf 의 두 블록 그대로, proxy_pass 줄만 그 snippet 의 /api/naver-auto 와 같은 값).
# 다른 앱 파일·nginx.conf·site 파일은 쓰지 않는다(전후 트리 지문으로 확인). 모르는 배치면 계획 단계에서 거절한다.
import fnmatch  # noqa: E402 (nginx 단계 전용)
NGINX_STEPS = {
    'reconcile-upload-v1': {
        'product_commit': '12260dbbc946f76d9bf7e2b8562cccc5474ea9a9',
        'http_conf': {'member': 'deploy/naver-engine-nginx-http.conf',
                      'sha256': '316f42d2bfb11ff374359d0520d31cf0662210aea75894de5383df417ab26136',
                      'target': '/etc/nginx/conf.d/naver-reconcile-upload-zone.conf'},
        'locations': {'member': 'deploy/naver-engine-nginx.conf',
                      'sha256': '7fe8b87d8b95c4e5f8ca8c87d534eaf00dfb895b20efb63390e49370fb2ddbe3',
                      'paths': ['/api/naver-auto/reconcile/settlement/preview',
                                '/api/naver-auto/reconcile/settlement/confirm'],
                      'blocks_sha256': '1704ac0480f467753b1d46459c511ca91782a22d4cca86221bf489945eaafae5'},
        'zone': 'naver_reconcile_upload', 'host': 'dashboard.metainc.co.kr',
        'big_bytes': 4 * 1024 * 1024, 'small_bytes': 64 * 1024}}
if ROOT and os.environ.get('NAVER_DEPLOY_TEST_NGINX_STEPS'):
    NGINX_STEPS = json.loads(read(os.environ['NAVER_DEPLOY_TEST_NGINX_STEPS']))   # 가짜 루트 시험 전용
NGINX_ROOT = '/etc/nginx'
NGINX_HTTP_INCLUDE = 'include /etc/nginx/conf.d/*.conf;'
NGINX_PROXY_ALLOWED = (re.compile(r'http://unix:/run/metainc/naver-relay/relay\.sock:\Z'),
                       re.compile(r'http://naver_relay\Z'))
NGINX_HEADER = '# naver-deploy nginx-apply %s (제품 %s) — 보고 대조 업로드 두 경로만 4MiB. 손으로 고치지 않는다.\n'


def nginx_step(identifier):
    if identifier not in NGINX_STEPS:
        fail('NGINX_STEP_UNKNOWN: 고정 표에 없는 nginx 단계입니다')
    return NGINX_STEPS[identifier]


def nginx_dump():
    done = subprocess.run(['nginx', '-T'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                          env={'PATH': os.environ.get('PATH', '/usr/sbin:/usr/bin:/sbin:/bin'), 'LANG': 'C'})
    if done.returncode:
        fail('NGINX_LAYOUT: nginx -T 실패')
    sections, path, lines = {}, None, []
    for line in done.stdout.decode('utf-8', 'replace').splitlines(keepends=True):
        match = re.fullmatch(r'# configuration file (/[^\x00-\x1f]*):\s*', line.rstrip('\n'))
        if match:
            if path is not None:
                sections[path] = ''.join(lines)
            path, lines = match.group(1), []
        elif path is not None:
            lines.append(line)
    if path is not None:
        sections[path] = ''.join(lines)
    if not sections or any(not p.startswith(NGINX_ROOT + '/') for p in sections):
        fail('NGINX_LAYOUT: nginx -T 구획을 읽지 못했거나 /etc/nginx 밖 파일이 있습니다')
    return sections


def brace_block(text, start):
    """text[start:] 의 첫 '{' 와 짝인 '}' 다음 위치. 주석(#)·따옴표 안의 괄호는 세지 않는다."""
    depth, i, quote = 0, text.index('{', start), None
    while i < len(text):
        c = text[i]
        if quote:
            if c == quote:
                quote = None
        elif c in ('"', "'"):
            quote = c
        elif c == '#':
            i = text.find('\n', i)
            if i < 0:
                break
            continue
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                if end < len(text) and text[end] == '\n':
                    end += 1
                return end
        i += 1
    fail('NGINX_LAYOUT: 괄호 짝이 맞지 않습니다')


def line_start(text, index):
    return text.rfind('\n', 0, index) + 1


def product_blocks(text, step):
    """제품 locations 파일에서 정확 일치 두 블록(줄 단위 원문)을 순서대로 뽑는다."""
    out = []
    for path in step['locations']['paths']:
        found = [m for m in re.finditer(r'(?m)^location\s*=\s*' + re.escape(path) + r'\s*\{', text)]
        if len(found) != 1:
            fail('NGINX_PRODUCT: 제품 파일에 %s 블록이 정확히 하나가 아닙니다' % path)
        start = found[0].start()
        out.append(text[start:brace_block(text, start)])
    return out


def nginx_product(tar_path, identifier, commit):
    step = nginx_step(identifier)
    if commit != step['product_commit']:
        fail('NGINX_COMMIT_PIN: 제품 커밋이 고정 표와 다릅니다')
    archive, items = members(tar_path)
    table = dict(items)
    bodies = {}
    for key in ('http_conf', 'locations'):
        member = step[key]['member']
        if member not in table:
            fail('NGINX_PRODUCT: %s 가 원본 묶음에 없습니다' % member)
        body = archive.extractfile(table[member]).read()
        if hashlib.sha256(body).hexdigest() != step[key]['sha256']:
            fail('NGINX_PRODUCT: %s 해시가 고정 표와 다릅니다' % member)
        bodies[key] = body.decode('utf-8')
    blocks = product_blocks(bodies['locations'], step)
    if hashlib.sha256(''.join(blocks).encode()).hexdigest() != step['locations']['blocks_sha256']:
        fail('NGINX_PRODUCT: 두 location 블록 해시가 고정 표와 다릅니다')
    return step, bodies['http_conf'], blocks


def resolve_include(argument):
    return argument if argument.startswith('/') else NGINX_ROOT + '/' + argument


def nginx_layout(step, sections):
    """관제 snippet F(정확히 하나) · 그것을 include 하는 dashboard server 블록(정확히 하나) · http{} 의 conf.d include."""
    head = re.compile(r'(?m)^[ \t]*location\s+\^~\s+/api/naver-auto\s*\{')
    candidates = [p for p, text in sections.items() if head.search(text)]
    if len(candidates) != 1:
        fail('NGINX_LAYOUT: /api/naver-auto location 을 가진 파일이 정확히 하나가 아닙니다(%d)' % len(candidates))
    snippet = candidates[0]
    text = sections[snippet]
    if snippet.startswith(NGINX_ROOT + '/conf.d/') or re.search(r'(?m)^\s*(server|http)\s*\{', text):
        fail('NGINX_LAYOUT: 관제 location 파일이 server 안 include snippet 이 아닙니다')
    if len(head.findall(text)) != 1:
        fail('NGINX_LAYOUT: /api/naver-auto location 이 두 번 이상입니다')
    start = head.search(text).start()
    block = text[start:brace_block(text, start)]
    proxies = re.findall(r'(?m)^\s*proxy_pass\s+(\S+?)\s*;', block)
    if len(proxies) != 1 or not any(rule.match(proxies[0]) for rule in NGINX_PROXY_ALLOWED):
        fail('NGINX_LAYOUT: /api/naver-auto 의 proxy_pass 가 알려진 관제 중계 형식이 아닙니다')
    including = []
    for path, body in sections.items():
        for match in re.finditer(r'(?m)^[ \t]*include\s+(\S+?)\s*;', body):
            if fnmatch.fnmatch(snippet, resolve_include(match.group(1))):
                including.append((path, match.start()))
    if len(including) != 1:
        fail('NGINX_LAYOUT: 관제 snippet 을 include 하는 곳이 정확히 하나가 아닙니다(%d)' % len(including))
    site, position = including[0]
    body = sections[site]
    inside = False
    for match in re.finditer(r'(?m)^[ \t]*server\s*\{', body):
        end = brace_block(body, match.start())
        if match.start() < position < end:
            names = re.findall(r'(?m)^\s*server_name\s+([^;]+);', body[match.start():end])
            inside = any(step['host'] in name.split() for name in names)
    if not inside:
        fail('NGINX_LAYOUT: 관제 snippet 이 %s server 블록 안에서 include 되지 않습니다' % step['host'])
    main = sections.get(NGINX_ROOT + '/nginx.conf', '')
    http = re.search(r'(?m)^[ \t]*http\s*\{', main)
    if not http or NGINX_HTTP_INCLUDE not in main[http.start():brace_block(main, http.start())]:
        fail('NGINX_LAYOUT: nginx.conf 의 http {} 가 /etc/nginx/conf.d/*.conf 를 include 하지 않습니다')
    return snippet, site, start, proxies[0]


def nginx_compute(tar_path, identifier, commit):
    step, http_conf, blocks = nginx_product(tar_path, identifier, commit)
    sections = nginx_dump()
    snippet, site, start, proxy = nginx_layout(step, sections)
    current = sections[snippet]
    with open(ROOT + snippet) as handle:
        if handle.read() != current:
            fail('NGINX_LAYOUT: nginx -T 원문과 디스크 파일이 다릅니다(적용 안 된 변경)')
    target = step['http_conf']['target']
    adapted = [re.sub(r'(?m)^(\s*proxy_pass\s+)\S+?(\s*;)', lambda m: m.group(1) + proxy + m.group(2), b, count=1)
               for b in blocks]
    insert = NGINX_HEADER % (identifier, commit[:12]) + ''.join(adapted) + '\n'
    applied = insert in current
    if applied:
        new = current
    else:
        if any(re.search(r'(?m)^\s*location\s*=\s*' + re.escape(p) + r'\s*\{', current) for p in step['locations']['paths']):
            fail('NGINX_LAYOUT: 업로드 location 이 다른 내용으로 이미 있습니다')
        new = current[:line_start(current, start)] + insert + current[line_start(current, start):]
    zone_now = sections.get(target)
    if zone_now is not None and zone_now != http_conf:
        fail('NGINX_LAYOUT: zone 파일 자리가 다른 내용으로 이미 있습니다')
    if applied != (zone_now is not None):
        fail('NGINX_LAYOUT: 두 파일 중 하나만 적용된 상태입니다(사람 확인 필요)')
    for path, body in sections.items():
        if path not in (target, snippet) and 'zone=' + step['zone'] in body:
            fail('NGINX_LAYOUT: zone 이름이 다른 파일에서 이미 쓰입니다')
    info = os.lstat(ROOT + snippet)
    stable = {'step': identifier, 'entry': step, 'commit': commit, 'snippet': snippet,
              'snippet_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'new_snippet_sha256': hashlib.sha256(new.encode()).hexdigest(), 'site': site,
              'site_sha256': hashlib.sha256(sections[site].encode()).hexdigest(),
              'nginx_conf_sha256': hashlib.sha256(sections.get(NGINX_ROOT + '/nginx.conf', '').encode()).hexdigest(),
              'zone_target': target, 'zone_sha256': hashlib.sha256(http_conf.encode()).hexdigest(),
              'proxy_pass': proxy, 'already_applied': applied,
              'tree_except_sha256': nginx_tree_except(snippet, target),
              'snippet_mode': stat.S_IMODE(info.st_mode), 'snippet_uid': info.st_uid, 'snippet_gid': info.st_gid}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return digest, stable, current, new, http_conf


def nginx_tree_except(*excluded):
    """/etc/nginx 트리 지문(링크는 대상 경로 문자열, 일반 파일은 내용). 고정 두 파일만 뺀다."""
    digest = hashlib.sha256()
    base = ROOT + NGINX_ROOT
    for folder, children, files in os.walk(base):
        children.sort()
        for name in sorted(files + [c for c in children if os.path.islink(os.path.join(folder, c))]):
            full = os.path.join(folder, name)
            relative = full[len(ROOT):]
            if relative in excluded:
                continue
            digest.update(relative.encode() + b'\0')
            if os.path.islink(full):
                digest.update(b'L' + os.readlink(full).encode())
            elif os.path.isfile(full):
                digest.update(hashlib.sha256(read(full, 'rb')).digest())
    return digest.hexdigest()


def nginx_plan(tar_path, identifier, commit, out_dir):
    digest, stable, current, new, http_conf = nginx_compute(tar_path, identifier, commit)
    os.makedirs(out_dir, 0o700, exist_ok=True)
    write_json_atomic(os.path.join(out_dir, 'plan-%s.json' % digest), stable)
    print(digest, 'applied' if stable['already_applied'] else 'pending')


def write_text_atomic(path, body, mode, uid=None, gid=None):
    temporary = path + '.naver-deploy.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'w') as handle:
        handle.write(body)
        handle.flush()
        if uid is not None and not ROOT:
            os.fchown(handle.fileno(), uid, gid)
        os.fchmod(handle.fileno(), mode)
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_folder(os.path.dirname(path))


def nginx_write(tar_path, identifier, commit, expected, backup_dir):
    """계획을 다시 계산해 해시가 같을 때만: snippet 원본을 백업하고 zone 파일·새 snippet 을 쓴다."""
    digest, stable, current, new, http_conf = nginx_compute(tar_path, identifier, commit)
    if digest != expected:
        fail('NGINX_PLAN_MISMATCH: 다시 계산한 계획이 승인한 plan_sha256 과 다릅니다')
    if stable['already_applied']:
        print('already-applied')
        return
    os.makedirs(backup_dir, 0o700, exist_ok=True)
    write_text_atomic(os.path.join(backup_dir, 'snippet.orig'), current, 0o600)
    write_json_atomic(os.path.join(backup_dir, 'backup.json'), dict(stable, plan_sha256=digest))
    target = ROOT + stable['zone_target']
    write_text_atomic(target, http_conf, 0o644, 0, 0)
    write_text_atomic(ROOT + stable['snippet'], new, stable['snippet_mode'], stable['snippet_uid'], stable['snippet_gid'])
    print('written')


def nginx_restore(backup_dir):
    """백업한 snippet 원문을 되돌리고, 이번에 만든 zone 파일(내용이 계획과 같을 때만)을 지운다."""
    record = load_json(os.path.join(backup_dir, 'backup.json'))
    original = read(os.path.join(backup_dir, 'snippet.orig'))
    if hashlib.sha256(original.encode()).hexdigest() != record['snippet_sha256']:
        fail('NGINX_RESTORE: 백업 원문 해시가 다릅니다')
    write_text_atomic(ROOT + record['snippet'], original, record['snippet_mode'], record['snippet_uid'],
                      record['snippet_gid'])
    target = ROOT + record['zone_target']
    if os.path.lexists(target):
        if os.path.islink(target) or hashlib.sha256(read(target, 'rb')).hexdigest() != record['zone_sha256']:
            fail('NGINX_RESTORE: zone 자리 파일이 이번에 쓴 내용이 아닙니다(지우지 않음)')
        os.unlink(target)
        fsync_folder(os.path.dirname(target))
    print('restored')


def nginx_verify_files(backup_dir):
    """적용 뒤: 두 파일이 계획 내용이고, 그 밖 /etc/nginx 트리 지문이 그대로인지."""
    record = load_json(os.path.join(backup_dir, 'backup.json'))
    if hashlib.sha256(read(ROOT + record['snippet'], 'rb')).hexdigest() != record['new_snippet_sha256']:
        fail('NGINX_VERIFY: snippet 이 계획 내용이 아닙니다')
    if hashlib.sha256(read(ROOT + record['zone_target'], 'rb')).hexdigest() != record['zone_sha256']:
        fail('NGINX_VERIFY: zone 파일이 계획 내용이 아닙니다')
    if nginx_tree_except(record['snippet'], record['zone_target']) != record['tree_except_sha256']:
        fail('NGINX_VERIFY: 고정 두 파일 밖의 nginx 설정이 바뀌었습니다')
    print('ok')


def nginx_blocks_sha(tar_path, identifier):
    """(운영·시험 보조) 원본 묶음 locations 파일에서 뽑은 두 블록의 해시. 고정값 확인용, 상태 변경 없음."""
    step = nginx_step(identifier)
    archive, items = members(tar_path)
    body = archive.extractfile(dict(items)[step['locations']['member']]).read().decode('utf-8')
    print(hashlib.sha256(''.join(product_blocks(body, step)).encode()).hexdigest())


NGINX_COMMANDS = {'nginx-plan': nginx_plan, 'nginx-write': nginx_write, 'nginx-restore': nginx_restore,
                  'nginx-verify-files': nginx_verify_files, 'nginx-blocks-sha': nginx_blocks_sha,
                  'nginx-field': lambda identifier, key: print(nginx_step(identifier)[key]),
                  'nginx-paths': lambda identifier: print(' '.join(nginx_step(identifier)['locations']['paths'])),
                  'nginx-tree': lambda: print(nginx_tree_except())}


COMMANDS = {'unit-parse': unit_parse, 'override-check': override_check, 'subst': subst, 'tar-check': tar_check,
            'tar-extract': tar_extract, 'tree-compare': tree_compare, 'image-info': image_info,
            'container-info': container_info, 'state-write': state_write,
            'state-get': state_get, 'history-add': history_add, 'prune-list': prune_list,
            'prune-history': prune_history, 'db-files': db_files, 'same-size': same_size,
            'backup-prune': backup_prune, 'sha': sha, 'tree-sha': tree_sha, 'result-json': result_json,
            'inspect': inspect, 'verify-copy': verify_copy, 'partial-prune': partial_prune,
            'disk-budget': disk_budget, 'image-sizes': image_sizes, 'cleanup-plan': cleanup_plan, 'disk-usage': disk_usage, 'cleanup': cleanup, 'env-switches': env_switches, 'container-mounts': container_mounts,
            'cleanup-artifacts-plan': lambda: cleanup_plan(artifacts_only=True),
            'cleanup-artifacts': lambda expected: cleanup(expected, None, artifacts_only=True),
            'compose-shape': compose_shape, 'shape-diff': shape_diff, 'check-config-run': check_config_run,
            'prune-logs': prune_logs,
            'schema-file': lambda path: print(schema_of(read(path))),
            'schema-tar-stdin': lambda: print(schema_of(tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()))
                                                        .extractfile('store.py').read().decode('utf-8'))),
            'randhex': lambda: print(secrets.token_hex(16))}
COMMANDS.update(MIG_COMMANDS)
COMMANDS.update(NGINX_COMMANDS)
if __name__ == '__main__':
    _inject = os.environ.get('NAVER_DEPLOY_FAKE_FAIL_CMD') if ROOT else None
    _only_if = os.environ.get('NAVER_DEPLOY_FAKE_FAIL_IF_EXISTS') if ROOT else None
    if (_inject and all(token in sys.argv[1:] for token in _inject.split())
            and (not _only_if or os.path.lexists(ROOT + _only_if))):
        sys.exit(37)   # 가짜 루트 시험 전용: 이 helper 명령의 실패를 주입
    try:
        COMMANDS[sys.argv[1]](*sys.argv[2:])
    except Refuse as error:
        # 거부 사유는 stdout 으로 낸다: 호출하는 셸이 $(...) 로 받아 그대로 보고한다.
        print(str(error))
        sys.exit(1)
PYEOF
)

# helper 원문은 128KiB(리눅스 인자 하나 상한)를 넘을 수 있어 -c 인자가 아니라 fd 3 으로 넘긴다(표준입력은 그대로).
py() { python3 -I -B /dev/fd/3 "$@" 3<<<"$PY_HELPER"; }

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
    "database_opened_by_deploy=$DB_OPENED" "runtime_env_changed_by_deploy=false" \
    ${MIG_ID:+"migration_id=$MIG_ID"} ${MIG_RUN:+"migration_run=$MIG_RUN"} ${MIG_STATE:+"migration_state=$MIG_STATE"} \
    ${MIG_RECEIPT_SHA:+"receipt_sha256=$MIG_RECEIPT_SHA"} ${MIG_ORPHANS:+"orphans_closed=$MIG_ORPHANS"} \
    ${MIG_PIN_STATE:+"pin_state=$MIG_PIN_STATE"} ${MIG_KEEP_RAW:+"keep_raw_now=$MIG_KEEP_RAW"} \
    ${MIG_DECISION:+"write_decision=$MIG_DECISION"} ${MIG_PLAN:+"plan_sha256=$MIG_PLAN"} \
    ${MIG_REHEARSAL:+"rehearsal=$MIG_REHEARSAL"} ${NGINX_STEP:+"nginx_step=$NGINX_STEP"} \
    ${NGINX_CHECKS:+"nginx_checks=$NGINX_CHECKS"} 2>/dev/null) \
    || line='{"status":"RESULT_WRITE_FAILED"}'
  printf 'NAVER_DEPLOY_RESULT=%s\n' "$line"
  if [ -n "$RESULT_FILE" ]; then
    printf '%s\n' "$line" > "$RESULT_FILE.tmp" && mv -f "$RESULT_FILE.tmp" "$RESULT_FILE"
  fi
}

on_exit() {
  local rc=$?
  trap - EXIT ERR
  if [ "$MODE" = deploy ] || [ "${MODE#migrate-}" != "$MODE" ] || [ "${MODE#nginx-}" != "$MODE" ]; then
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
  if [ "${MODE#nginx-}" != "$MODE" ]; then
    nginx_fail "$1" "$2"
  fi
  # 이관 run(또는 이관 재진입 중): 정해진 이관 경로만 쓴다. 기존 restore_previous 를 직접 부르지 않는다.
  if [ "$MIG_ACTIVE" = 1 ] || [ "${MODE#migrate-}" != "$MODE" ]; then
    if [ "$RESTORING" = 1 ]; then
      mig_unknown "$1"
    fi
    mig_fail "$1" "$2"
  fi
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
  # 이관 표지(활성 표지·hold·drop-in)가 하나라도 있으면 이관 재진입 규칙(B.3)만 쓴다. 기존 복원보다 먼저.
  mig_recover
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
  if [ -n "$(py mig-pointer get 2>/dev/null)" ] || [ -n "$(py mig-hold get 2>/dev/null)" ] \
      || [ "$(py mig-dropin present 2>/dev/null)" != no ]; then
    cleanup_refuse REFUSED_MIGRATION_ACTIVE 10
  fi
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

artifacts_refuse() { # status exit-code; no host log side effects
  printf 'NAVER_DEPLOY_CLEANUP_RESULT={"exit_code":%s,"mode":"cleanup-artifacts","status":"%s"}\n' "$2" "$1"
  exit "$2"
}

main_cleanup_artifacts() {
  local expected=$1 phase
  printf '%s' "$expected" | grep -Eq '^[0-9a-f]{64}$' || artifacts_refuse REFUSED_BAD_INPUT 10
  if [ "$TEST_MODE" = 0 ] && [ "$(id -u)" != 0 ]; then
    artifacts_refuse REFUSED_NOT_ROOT 10
  fi
  # Existing state and global lock only. Do not create/chmod a log directory or prune logs.
  [ -d "$R$STATE_DIR" ] && [ ! -L "$R$STATE_DIR" ] || artifacts_refuse REFUSED_LAYOUT 10
  exec 9>>"$R$STATE_DIR/lock"
  flock -n 9 || artifacts_refuse LOCKED 11
  if [ -n "$(py mig-pointer get 2>/dev/null)" ] || [ -n "$(py mig-hold get 2>/dev/null)" ] \
      || [ "$(py mig-dropin present 2>/dev/null)" != no ]; then
    artifacts_refuse REFUSED_MIGRATION_ACTIVE 10
  fi
  phase=$(py state-get "$STATE_FILE" phase 2>/dev/null) || phase=''
  if phase_needs_restore "$phase"; then
    artifacts_refuse REFUSED_DEPLOY_NOT_FINISHED 10
  fi
  py cleanup-artifacts "$expected"
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
  # 빌드 예산(추정치) = 지금 실행 중인 두 이미지 Size 합(최소 512MiB). 새 Dockerfile 의 중간 층·내려받기·cache
  #   최고 사용량을 보장하는 값은 아니다.
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
  log "빌드 전 공간 예산 통과(빌드 추정 ${build_need}B + DB 사본 $((size + 268435456))B)"

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
  # helper 실패(링크·예상 밖 항목 등)는 반드시 이 셸로 전파해 멈춘다(프로세스 치환을 쓰지 않는다).
  info=$(py partial-prune "$R$DB_BACKUPS") || die BACKUP_SAFETY "$info"
  [ -z "$info" ] || log "지난 실행의 미완성 사본 정리: $info"
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
  info=$(py backup-prune "$R$DB_BACKUPS" 1) || die BACKUP_SAFETY "$info"
  [ -z "$info" ] || log "직전 DB 사본 정리(새 사본 검증 뒤): $info"

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
  info=$(py prune-list "$R$STATE_DIR/history.json" "$NEW" "$cur") || { warn IMAGE_PRUNE_FAILED "정리 목록 계산 실패"; info=''; }
  for f in $info; do
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
  done
  if [ -n "$WARNINGS" ]; then
    finish 0 DEPLOYED_WITH_WARNINGS "$WARNINGS" "$cur → $NEW 배포 완료(경고 있음)"
  fi
  finish 0 DEPLOYED '' "$cur → $NEW 배포 완료($HEALTH_CODES, 정지~헬스 준비 ${DOWNTIME:-?}초)"
}

# ════════════════════════════════════════════════════════════════════════════════════════════
# 21→22 추가형 스키마 이관(migrate-*) — DESIGN-CLAUDE-v3.md(v3.1, 2b62dbd9) + v2 의 대체되지 않은 부분.
# deploy 모드의 SCHEMA_CHANGED 거절은 그대로다. 이관은 고정 표(MIGRATIONS)의 한 항목만, 준비된 정확 이미지 ID 로만 한다.
# ════════════════════════════════════════════════════════════════════════════════════════════
MIG_HELPER="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/naver_schema_migrate.py"
BACKUP_STATE=/var/backups/metainc/naver-engine/state.json
DAILY_BACKUPS=/var/backups/metainc/naver-engine
MIG_ID=''
MIG_RUN=''
MIG_STAGE=''
MIG_ACTIVE=0
MIG_STATE=''
MIG_OUT=''
MIG_RECEIPT_SHA=''
MIG_ORPHANS=''
MIG_PIN_STATE=''
MIG_KEEP_RAW=''
MIG_DECISION=''
MIG_PLAN=''
MIG_REHEARSAL=''
MIG_NEW_ENGINE=''
MIG_NEW_RELAY=''
MIG_ALLOW_HOLD=0
MIG_HELPER_STAGED=''
DB_OPENED=false

mig_dir() { printf '%s' "$R$STATE_DIR/migration/$MIG_RUN"; }
mig_receipt_path() { printf '%s/receipt.json' "$(mig_dir)"; }

# helper 단계 하나 = docker run 하나. 끝나면 같은 이름 컨테이너가 남지 않았음을 확인한다(목록 실패도 실패).
mig_reap() { # name
  local out
  out=$(dk ps -aq --filter "name=^$1\$" 2>>"$CMD_LOG") || return 1
  if [ -n "$out" ]; then
    dk kill "$1" >>"$CMD_LOG" 2>&1 || true
    dk rm -f "$1" >>"$CMD_LOG" 2>&1 || true
    out=$(dk ps -aq --filter "name=^$1\$" 2>>"$CMD_LOG") || return 1
    [ -z "$out" ] || return 1
  fi
  return 0
}

mig_stage_helper() { # 컨테이너 사용자(10001)가 읽을 수 있는 고정 사본(0644, root 소유)을 만들고 해시를 다시 대조한다
  local sum target
  sum=$(py file-sha "$MIG_HELPER")
  [ "$sum" = "$(py mig-field "$MIG_ID" helper_sha256)" ] || return 1
  mkdir -p "$R$STATE_DIR/migration"
  target="$R$STATE_DIR/migration/helper-$(printf '%s' "$sum" | cut -c1-16).py"
  if [ ! -f "$target" ] || [ "$(py file-sha "$target")" != "$sum" ]; then
    cp "$MIG_HELPER" "$target.tmp"
    chmod 644 "$target.tmp"
    mv -f "$target.tmp" "$target"
  fi
  [ "$(py file-sha "$target")" = "$sum" ] || return 1
  MIG_HELPER_STAGED=$target
}

mig_helper() { # image bind_source step json → MIG_OUT(한 줄 JSON), 종료 코드
  local image=$1 source=$2 step=$3 args=$4 name rc=0
  if [ -z "${MIG_HELPER_STAGED:-}" ]; then
    mig_stage_helper || { MIG_OUT='{"ok":false,"code":"HELPER_STAGE"}'; return 91; }
  fi
  name="naver-migrate-$step-$(py randhex | cut -c1-12)"
  DB_OPENED=true
  MIG_OUT=$(dk run --rm --name "$name" --network none --read-only --user 10001:10001 --cap-drop ALL \
    --security-opt no-new-privileges:true --pids-limit 64 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=256m,mode=1777 \
    -v "$source:/var/lib/naver-engine" -v "$MIG_HELPER_STAGED:/opt/naver-migrate/m.py:ro" \
    --entrypoint python3 "$image" -I -B /opt/naver-migrate/m.py "$step" "$args" 2>>"$CMD_LOG" | tail -n 1) || rc=$?
  printf '[helper %s] rc=%s %s\n' "$step" "$rc" "$MIG_OUT" >> "$CMD_LOG"
  if ! mig_reap "$name"; then
    # 종료를 확인하지 못한 helper 가 남아 있을 수 있다 — 어떤 DB helper·rename·기동도 더 하지 않는다.
    log "helper 컨테이너가 남았거나 목록을 못 읽었습니다: $name"
    if [ "$MODE" = migrate-rehearse ]; then
      MIG_REHEARSAL=failed
      finish 10 REHEARSAL_FAILED HELPER_EXIT_UNCONFIRMED "리허설 helper 종료 확인 불명(scratch 보존, 운영 무변경)"
    fi
    mig_hold_stopped HELPER_EXIT_UNCONFIRMED
  fi
  if [ "$rc" = 0 ] && [ "$(py json-field "$MIG_OUT" ok 2>/dev/null)" = True ]; then
    return 0
  fi
  [ "$rc" = 0 ] && rc=3
  return "$rc"
}

mig_code() { py json-field "$MIG_OUT" code 2>/dev/null || printf 'UNPARSED'; }
mig_result() { py json-field "$MIG_OUT" result "$@"; }

image_schema() { # image → 라벨 또는 이미지 안 store.py
  local info id user src label cid schema
  info=$(dk image inspect "$1" 2>>"$CMD_LOG" | py image-info) || return 1
  read -r id user src label <<EOF
$info
EOF
  : "$id$user$src"
  if printf '%s' "$label" | grep -Eq '^[0-9]+$'; then
    printf '%s' "$label"
    return 0
  fi
  cid=$(dk create --network none "$1" 2>>"$CMD_LOG") || return 1
  schema=$(dk cp "$cid:/opt/naver-engine/naver_engine/store.py" - 2>>"$CMD_LOG" | py schema-tar-stdin) || schema=''
  dk rm "$cid" >>"$CMD_LOG" 2>&1 || true
  [ -n "$schema" ] || return 1
  printf '%s' "$schema"
}

mig_unit_dropins_ok() { # 두 unit 이 우리 drop-in 을 실제로 싣고 있는지(daemon-reload 반영 포함)
  local unit
  py mig-dropin check || return 1
  for unit in "$ENGINE_UNIT" "$RELAY_UNIT"; do
    case " $(unit_prop "$unit" DropInPaths) " in
      *"/$unit.d/50-naver-migration-hold.conf "*) ;;
      *) return 1 ;;
    esac
    [ "$(unit_prop "$unit" NeedDaemonReload)" = no ] || return 1
  done
}

mig_install_hold() {
  py mig-hold create "$MIG_RUN"
  py mig-dropin install
  systemctl daemon-reload 2>>"$CMD_LOG"
  mig_unit_dropins_ok || die HOLD_INSTALL "시작 차단 drop-in 이 반영되지 않았습니다"
  log "시작 차단: hold + drop-in(재부팅·의존 시작 포함)"
}

mig_remove_dropins() {
  local unit
  py mig-dropin remove || return 1
  systemctl daemon-reload 2>>"$CMD_LOG" || return 1
  for unit in "$ENGINE_UNIT" "$RELAY_UNIT"; do
    [ -z "$(unit_prop "$unit" DropInPaths)" ] || return 1
  done
}

mig_stop_both() {
  local ok=0
  stop_and_wait "$RELAY_UNIT" naver-relay || ok=1
  stop_and_wait "$ENGINE_UNIT" naver-engine || ok=1
  return "$ok"
}

# 정지 보존 종료: hold 를 먼저(이미 있으면 그대로) → 정지 확인 → 상태 HOLD. 이후는 대표 판단(continue/rollback).
# 모든 HOLD 종료의 시작 차단(B.1): hold 파일 + 두 unit drop-in 을 (다시) 깔고 daemon-reload 뒤 실제 적용을 확인한다.
# 확인할 수 없으면 0 이 아닌 값을 돌려준다(부르는 쪽이 정지는 그대로 하고 복구 필요로 보고한다).
mig_block_starts() {
  local hold
  py mig-hold create "${MIG_RUN:-unknown}" >>"$CMD_LOG" 2>&1 || true
  hold=$(py mig-hold get 2>/dev/null) || return 1
  [ -n "$hold" ] || return 1
  py mig-dropin install >>"$CMD_LOG" 2>&1 || return 1
  systemctl daemon-reload 2>>"$CMD_LOG" || return 1
  mig_unit_dropins_ok || return 1
}

mig_hold_stopped() { # reason
  trap - ERR
  set +e
  if ! mig_block_starts; then
    log "시작 차단(hold·drop-in)을 확인하지 못했습니다"
    mig_stop_both
    STOPPED_CONFIRMED=$( stopped_confirmed "$ENGINE_UNIT" naver-engine && stopped_confirmed "$RELAY_UNIT" naver-relay \
      && echo true || echo false )
    [ -n "$MIG_RUN" ] && py mig-status "$MIG_RUN" state=HOLD "reason=$1_START_BLOCK_UNVERIFIED" >>"$CMD_LOG" 2>&1
    MIG_STATE=HOLD
    PHASE=migration_hold
    finish 4 MIGRATION_RECOVERY_REQUIRED "${1}_START_BLOCK_UNVERIFIED" "시작 차단 확인 불가. 정지 확인=$STOPPED_CONFIRMED"
  fi
  mig_stop_both
  STOPPED_CONFIRMED=$( stopped_confirmed "$ENGINE_UNIT" naver-engine && stopped_confirmed "$RELAY_UNIT" naver-relay \
    && echo true || echo false )
  py mig-status "$MIG_RUN" state=HOLD "reason=$1" >>"$CMD_LOG" 2>&1
  MIG_STATE=HOLD
  [ "$HAVE_STATE" = 1 ] && py state-write "$STATE_FILE" "phase=migration_hold" >>"$CMD_LOG" 2>&1
  PHASE=migration_hold
  finish 12 MIGRATION_HOLD "$1" "정지 보존(hold). 정지 확인=$STOPPED_CONFIRMED"
}

mig_unknown() { # reason — 모르는 상태: 아무것도 옮기거나 지우지 않는다
  trap - ERR
  set +e
  mig_block_starts || log "시작 차단(hold·drop-in)을 확인하지 못했습니다"
  mig_stop_both
  STOPPED_CONFIRMED=$( stopped_confirmed "$ENGINE_UNIT" naver-engine && stopped_confirmed "$RELAY_UNIT" naver-relay \
    && echo true || echo false )
  [ -n "$MIG_RUN" ] && py mig-status "$MIG_RUN" state=HOLD "reason=$1" >>"$CMD_LOG" 2>&1
  MIG_STATE=HOLD
  PHASE=migration_hold
  finish 4 MIGRATION_RECOVERY_REQUIRED "$1" "모르는 이관 상태. 정지 확인=$STOPPED_CONFIRMED"
}

# 복귀 pin 에서 v21 세대 값을 읽는다(진행 중 run 이든 R7 이든 같은 곳).
mig_load_pin() {
  local pin="$R$STATE_DIR/pins/$MIG_RUN.json" body
  [ -f "$pin" ] || return 1
  body=$(cat "$pin")
  PREV_COMMIT=$(py json-field "$body" commit)
  PREV_ENGINE_IMAGE=$(py json-field "$body" engine_image)
  PREV_RELAY_IMAGE=$(py json-field "$body" relay_image)
  P_RUN_DIR=$(py json-field "$body" run_dir)
  P_COMPANION=$(py json-field "$body" companion)
  P_SWITCHES=$(py json-field "$body" switches)
  P_NEW_COMMIT=$(py json-field "$body" new_commit)
  MIG_NEW_ENGINE=$(py json-field "$body" new_engine_image)
  MIG_NEW_RELAY=$(py json-field "$body" new_relay_image)
  [ -n "$MIG_ID" ] || MIG_ID=$(py json-field "$body" migration_id)
  [ -n "$PREV_COMMIT" ] && [ -n "$PREV_ENGINE_IMAGE" ] && [ -n "$PREV_RELAY_IMAGE" ] && [ -n "$P_RUN_DIR" ]
}

# guarded_start §A 3단계: 돌릴 세대의 unit·override·이미지·컨테이너를 되살리고 실제 적용값을 다시 읽는다.
mig_service_generation() { # gen(v21|v22)
  local gen=$1 name unit image commit release saved expected mounts schema
  if [ "$gen" = v21 ]; then commit=$PREV_COMMIT; else commit=$P_NEW_COMMIT; fi
  release="$RELEASES/naver-$commit"
  for name in engine relay; do
    unit="metainc-naver-$name.service"
    if [ "$gen" = v21 ]; then saved="$R$P_RUN_DIR/$unit"; else saved="$R$P_RUN_DIR/new-$unit"; fi
    [ -f "$saved" ] || return 1
    if [ "$(py sha "$saved")" != "$(py sha "$R$UNIT_DIR/$unit")" ]; then
      write_file_atomic "$saved" "$R$UNIT_DIR/$unit" 644 || return 1
    fi
    if [ "$gen" = v21 ]; then
      saved="$R$P_RUN_DIR/preview-$name.override.yml"
      if [ ! -f "$R$release/preview-$name.override.yml" ] || [ "$(py sha "$saved")" != "$(py sha "$R$release/preview-$name.override.yml")" ]; then
        write_file_atomic "$saved" "$R$release/preview-$name.override.yml" 600 || return 1
      fi
      if [ "$name" = engine ]; then image=$PREV_ENGINE_IMAGE; else image=$PREV_RELAY_IMAGE; fi
    else
      if [ "$name" = engine ]; then image=$MIG_NEW_ENGINE; else image=$MIG_NEW_RELAY; fi
    fi
    dk image inspect "$image" >/dev/null 2>>"$CMD_LOG" || return 1
    dk tag "$image" "metainc/naver-$name:$commit" >>"$CMD_LOG" 2>&1 || return 1
  done
  systemctl daemon-reload 2>>"$CMD_LOG" || return 1
  for name in engine relay; do
    compose_args "$name" "$release" "$P_COMPANION"
    dk "${CARGS[@]}" up --no-start --no-build --force-recreate >>"$CMD_LOG" 2>&1 || return 1
  done
  for name in engine relay; do
    if [ "$gen" = v21 ]; then
      if [ "$name" = engine ]; then image=$PREV_ENGINE_IMAGE; else image=$PREV_RELAY_IMAGE; fi
    else
      if [ "$name" = engine ]; then image=$MIG_NEW_ENGINE; else image=$MIG_NEW_RELAY; fi
    fi
    mounts=$(cat "$R$P_RUN_DIR/mounts-$name.json" 2>/dev/null) || return 1
    read_container "naver-$name" || return 1
    [ "$C_IMAGE" = "$image" ] && [ "$C_RUNNING" = false ] && [ "$C_MOUNTS" = "$mounts" ] || return 1
    if [ "$name" = engine ]; then
      [ "$C_SWITCHES" = "$P_SWITCHES" ] || return 1
    fi
    [ "$(unit_prop "metainc-naver-$name.service" NeedDaemonReload)" = no ] || return 1
  done
  schema=$(image_schema "$( [ "$gen" = v21 ] && echo "$PREV_ENGINE_IMAGE" || echo "$MIG_NEW_ENGINE" )") || return 1
  expected=$( [ "$gen" = v21 ] && py mig-field "$MIG_ID" from_schema || py mig-field "$MIG_ID" to_schema )
  [ "$schema" = "$expected" ] || return 1
  info=$(py unit-parse "$R$UNIT_DIR/$ENGINE_UNIT" engine) || return 1
  [ "${info% *}" = "$commit" ] || return 1
  mig_unit_dropins_ok || return 1
}

# guarded_start(§A): hold 유지·정지 확인 → DB 세대 검증(잠금) → 서비스 세대 복원·재확인 → start intent → hold 마지막 해제 → 기동.
# 이관 전용 단계 기록: state.json 쓰기와 다시 읽은 값까지 확인한다(공통 set_phase 는 실패를 가린다 — 바꾸지 않는다).
mig_set_phase() { # phase
  PHASE=$1
  py state-write "$STATE_FILE" "phase=$1" || return 1
  [ "$(py state-get "$STATE_FILE" phase)" = "$1" ] || return 1
  log "단계: $1"
}

guarded_start() { # gen expect_identity_json expect_sha256(빈 값 가능) full(true|false)
  local gen=$1 identity=$2 sha=$3 full=$4 schema image args held
  py mig-hold create "$MIG_RUN" || return 1
  mig_stop_both || return 1
  stopped_confirmed "$ENGINE_UNIT" naver-engine && stopped_confirmed "$RELAY_UNIT" naver-relay || return 1
  if [ "$gen" = v21 ]; then
    schema=$(py mig-field "$MIG_ID" from_schema); image=$PREV_ENGINE_IMAGE
  else
    schema=$(py mig-field "$MIG_ID" to_schema); image=$MIG_NEW_ENGINE
  fi
  args=$(py mig-args "$MIG_ID" startcheck production "run=$MIG_RUN" "expect_identity=json:$identity" \
    "expect_sha256=$sha" "full=json:$full" "expect_schema=$schema")
  mig_helper "$image" "$R$DATA_DIR" startcheck "$args" || { log "startcheck 거부: $(mig_code)"; return 1; }
  mig_service_generation "$gen" || { log "서비스 세대 복원·확인 실패($gen)"; return 1; }
  # 이 함수는 `|| rc=$?` 문맥에서 불려 errexit 가 꺼져 있다 — 안전 전이의 필수 명령을 모두 직접 확인한다.
  py mig-journal "$R$DATA_DIR" append "$MIG_RUN" "start-$gen" intent \
    || { log "start intent 기록 실패 — 기동하지 않습니다"; return 3; }
  mig_set_phase starting || { log "상태 기록 실패·불명 — 기동하지 않습니다"; return 3; }
  MIG_STAGE=started
  if ! py mig-hold remove "$MIG_RUN" || ! held=$(py mig-hold get) || [ -n "$held" ]; then
    log "hold 해제 실패·불명 — 기동하지 않습니다"
    py mig-hold create "$MIG_RUN" >>"$CMD_LOG" 2>&1 || true
    return 3
  fi
  log "hold 해제(마지막) → 기동: $gen"
  systemctl start "$ENGINE_UNIT" 2>>"$CMD_LOG" || true
  systemctl start "$RELAY_UNIT" 2>>"$CMD_LOG" || true
  mig_set_phase verifying || { py mig-hold create "$MIG_RUN" || true; return 2; }
  if [ "$gen" = v21 ]; then
    health_check "$PREV_ENGINE_IMAGE" "$PREV_RELAY_IMAGE" || { py mig-hold create "$MIG_RUN" || true; return 2; }
  else
    health_check "$MIG_NEW_ENGINE" "$MIG_NEW_RELAY" || { py mig-hold create "$MIG_RUN" || true; return 2; }
  fi
  if journalctl -u "$ENGINE_UNIT" --since "-$((HOLD_SECONDS + READY_TIMEOUT + 30))s" --no-pager 2>/dev/null \
      | grep -Eq 'Traceback|StoreError|database disk image is malformed'; then
    py mig-hold create "$MIG_RUN" || true
    return 2
  fi
  py mig-journal "$R$DATA_DIR" append "$MIG_RUN" "start-$gen" "done" || { py mig-hold create "$MIG_RUN" || true; return 2; }
  return 0
}

mig_receipt_field() { py mig-receipt-get "$MIG_RUN" "$1"; }

# 새 쓰기 입증(v2 §4): 정지·잠금·checkpoint·rowid manifest. 결정: no_new_writes | new_writes | unknown
# 제품을 불러오지 않는 단계(prove·gap·bundle·restore-rename·undo)는 pin 된 v21 이미지로 돌린다(뒤 배포가 v22 태그를 정리해도 R7 가능).
mig_prove() {
  local args
  args=$(py mig-args "$MIG_ID" prove production "run=$MIG_RUN" "receipt=@$(mig_receipt_path)")
  if mig_helper "$PREV_ENGINE_IMAGE" "$R$DATA_DIR" prove "$args"; then
    MIG_DECISION=$(mig_result decision)
  else
    MIG_DECISION=unknown
  fi
  log "새 쓰기 판정: $MIG_DECISION"
}

# 엔진이 한 번도 열지 않았음이 입증된 상태(저널이 intent:start 전 + hold 유지)만 되돌린다.
mig_undo_unstarted() {
  local args receipt=''
  if [ -f "$(mig_receipt_path)" ]; then receipt="receipt=@$(mig_receipt_path)"; fi
  if [ -z "$receipt" ] && [ -f "$R$DATA_DIR/naver-migrate-receipt.json" ]; then
    receipt="receipt=@$R$DATA_DIR/naver-migrate-receipt.json"
  fi
  args=$(py mig-args "$MIG_ID" undo production "run=$MIG_RUN" ${receipt:+"$receipt"})
  mig_helper "$PREV_ENGINE_IMAGE" "$R$DATA_DIR" undo "$args"
}

mig_expected_v21() { # → identity JSON, sha, full
  local restored
  restored=$(mig_receipt_field restored_identity)
  if [ -n "$restored" ]; then
    printf '%s\n%s\nfalse\n' "$restored" "$(mig_receipt_field pre_sha256)"
  elif [ -n "$(mig_receipt_field pre_identity)" ]; then
    printf '%s\n%s\ntrue\n' "$(mig_receipt_field pre_identity)" "$(mig_receipt_field pre_sha256)"
  else
    printf '\n\nfalse\n'
  fi
}

mig_start_v21() { # 옛 세대로 guarded_start. identity 가 없으면(영수증 전 중단) 현재 canonical 을 잠금 아래 그대로 쓴다.
  local lines identity sha full rc=0
  lines=$(mig_expected_v21)
  identity=$(printf '%s\n' "$lines" | sed -n 1p)
  sha=$(printf '%s\n' "$lines" | sed -n 2p)
  full=$(printf '%s\n' "$lines" | sed -n 3p)
  if [ -z "$identity" ]; then
    identity=$(py identity "$R$DATA_DIR/engine.db") || return 1
    full=false
  fi
  guarded_start v21 "$identity" "$sha" "$full" || rc=$?
  return "$rc"
}

# B.2: 종결(COMPLETED|ROLLED_BACK) 정리. 순서가 계약이다. 표지는 마지막에 지운다.
mig_complete() { # state — errexit 가 꺼진 문맥에서도 불리므로 단계마다 직접 확인한다. 실패면 표지를 남긴다.
  local state=$1 hold
  py mig-status "$MIG_RUN" "state=$state" || mig_completion_failed STATUS_WRITE
  MIG_STATE=$state
  hold=$(py mig-hold get) || mig_completion_failed HOLD_READ
  if [ -n "$hold" ]; then
    [ "$hold" = "$MIG_RUN" ] || mig_unknown HOLD_OTHER_RUN
    mig_terminal_generation_ok "$state" || mig_hold_stopped TERMINAL_GENERATION_MISMATCH
    py mig-hold remove "$MIG_RUN" || mig_completion_failed HOLD_REMOVE
  fi
  py mig-journal "$R$DATA_DIR" move "$MIG_RUN" || mig_completion_failed JOURNAL_MOVE
  mig_remove_dropins || mig_hold_stopped DROPIN_REMOVE_FAILED
  mig_record_generation "$state" || mig_completion_failed GENERATION_RECORD
  py state-write "$STATE_FILE" "migration_id=" "migration_completed=$MIG_RUN" "phase=done" \
    || mig_completion_failed STATE_WRITE
  py mig-pointer clear "$MIG_RUN" || mig_completion_failed POINTER_CLEAR
  MIG_ACTIVE=0
  log "이관 종결 기록: $state (표지 해제)"
}

# 종결 정리 실패: 서비스는 그대로 두고(종결 세대가 이미 확인·기동됨) 활성 표지를 남겨 다음 잠금 모드가 이어서 정리한다.
mig_completion_failed() { # step
  trap - ERR
  set +e
  finish 4 MIGRATION_RECOVERY_REQUIRED "COMPLETION_$1" "종결 정리 실패($1). 활성 표지 유지 — 다음 실행이 정리를 이어 갑니다"
}

# 종결 세대 재확인(B.3 rule 3, B.2 3a): 기대 이미지로 두 서비스가 돌고, canonical inode 가 기대 identity.
mig_terminal_generation_ok() { # state
  local identity engine relay current
  if [ "$1" = COMPLETED ]; then
    identity=$(mig_receipt_field work_identity); engine=$MIG_NEW_ENGINE; relay=$MIG_NEW_RELAY
  else
    identity=$(mig_receipt_field restored_identity)
    [ -n "$identity" ] || identity=$(mig_receipt_field pre_identity)
    engine=$PREV_ENGINE_IMAGE; relay=$PREV_RELAY_IMAGE
  fi
  [ -n "$identity" ] || return 1
  current=$(py identity "$R$DATA_DIR/engine.db" 2>/dev/null) || return 1
  [ "$(py ino-of "$current")" = "$(py ino-of "$identity")" ] || return 1
  if [ "$1" = COMPLETED ]; then mig_units_match v22 || return 1; else mig_units_match v21 || return 1; fi
  read_container naver-engine && [ "$C_IMAGE" = "$engine" ] && [ "$C_RUNNING" = true ] || return 1
  read_container naver-relay && [ "$C_IMAGE" = "$relay" ] && [ "$C_RUNNING" = true ] || return 1
}

# 기대 세대의 unit 원문·적용 상태와 컨테이너 이미지·mount·스위치(F5). 서비스 상태는 바꾸지 않는다.
mig_units_match() { # gen
  local name unit saved image mounts commit info state pid
  if [ "$1" = v21 ]; then commit=$PREV_COMMIT; else commit=$P_NEW_COMMIT; fi
  for name in engine relay; do
    unit="metainc-naver-$name.service"
    if [ "$1" = v21 ]; then saved="$R$P_RUN_DIR/$unit"; else saved="$R$P_RUN_DIR/new-$unit"; fi
    [ -f "$saved" ] && [ "$(py sha "$saved")" = "$(py sha "$R$UNIT_DIR/$unit")" ] || return 1
    [ "$(unit_prop "$unit" NeedDaemonReload)" = no ] || return 1
    # 실행 상태도 세대 계약이다: unit active·MainPID 있음(조회 실패도 불일치 → 부르는 쪽이 HOLD).
    state=$(unit_prop "$unit" ActiveState) || return 1
    pid=$(unit_prop "$unit" MainPID) || return 1
    [ "$state" = active ] && [ -n "$pid" ] && [ "$pid" != 0 ] || return 1
    info=$(py unit-parse "$R$UNIT_DIR/$unit" "$name") || return 1
    [ "${info% *}" = "$commit" ] || return 1
    if [ "$1" = v21 ]; then
      if [ "$name" = engine ]; then image=$PREV_ENGINE_IMAGE; else image=$PREV_RELAY_IMAGE; fi
    else
      if [ "$name" = engine ]; then image=$MIG_NEW_ENGINE; else image=$MIG_NEW_RELAY; fi
    fi
    mounts=$(cat "$R$P_RUN_DIR/mounts-$name.json" 2>/dev/null) || return 1
    read_container "naver-$name" || return 1
    [ "$C_IMAGE" = "$image" ] && [ "$C_MOUNTS" = "$mounts" ] || return 1
    if [ "$name" = engine ]; then [ "$C_SWITCHES" = "$P_SWITCHES" ] || return 1; fi
  done
}

# B.2 종결의 세대 기록(F3): current/history 를 종결 세대에 맞춰 멱등하게 쓴다(표지 해제 전).
mig_record_generation() { # state
  local stamp_now
  stamp_now=$(date -u +%Y%m%dT%H%M%SZ)
  if [ "$1" = COMPLETED ]; then
    py state-write "$R$STATE_DIR/current.json" "commit=$P_NEW_COMMIT" "engine_image=$MIG_NEW_ENGINE" \
      "relay_image=$MIG_NEW_RELAY" "schema=$(py mig-field "$MIG_ID" to_schema)" "switches=$P_SWITCHES" \
      "deployed_at=$stamp_now" "previous_commit=$PREV_COMMIT" "migration_run=$MIG_RUN" || return 1
    py history-add "$R$STATE_DIR/history.json" "$PREV_COMMIT" || return 1
    py history-add "$R$STATE_DIR/history.json" "$P_NEW_COMMIT" || return 1
  else
    py state-write "$R$STATE_DIR/current.json" "commit=$PREV_COMMIT" "engine_image=$PREV_ENGINE_IMAGE" \
      "relay_image=$PREV_RELAY_IMAGE" "schema=$(py mig-field "$MIG_ID" from_schema)" "switches=$P_SWITCHES" \
      "deployed_at=$stamp_now" "previous_commit=$P_NEW_COMMIT" "migration_run=$MIG_RUN" || return 1
    py history-add "$R$STATE_DIR/history.json" "$PREV_COMMIT" || return 1
  fi
}

# 자동 복귀(입증된 경우만) → v21 guarded_start → ROLLED_BACK. 실패면 hold.
mig_auto_rollback() { # reason started(0|1) [exit code]
  local reason=$1 started=$2 code=${3:-2} rc=0 stamp_now args
  trap - ERR
  set +e
  RESTORING=1
  py mig-hold create "$MIG_RUN" >>"$CMD_LOG" 2>&1
  mig_stop_both || mig_unknown STOP_NOT_CONFIRMED
  mig_load_pin || mig_unknown PIN_MISSING
  if [ "$started" = 1 ]; then
    mig_prove
    if [ "$MIG_DECISION" != no_new_writes ]; then
      mig_gap_report
      mig_hold_stopped "${reason}_WRITES_${MIG_DECISION}"
    fi
    stamp_now=$(date -u +%Y%m%dT%H%M%SZ)
    args=$(py mig-args "$MIG_ID" bundle production "run=$MIG_RUN" "stamp=$stamp_now" "receipt=@$(mig_receipt_path)")
    mig_helper "$PREV_ENGINE_IMAGE" "$R$DATA_DIR" bundle "$args" || mig_unknown "BUNDLE_$(mig_code)"
    args=$(py mig-args "$MIG_ID" restore-rename production "run=$MIG_RUN" "receipt=@$(mig_receipt_path)")
    mig_helper "$PREV_ENGINE_IMAGE" "$R$DATA_DIR" restore-rename "$args" || mig_unknown "RESTORE_$(mig_code)"
  else
    mig_undo_unstarted || mig_unknown "UNDO_$(mig_code)"
  fi
  if ! py mig-window 23:00 "$R$BACKUP_STATE" >>"$CMD_LOG" 2>&1; then
    mig_hold_stopped WINDOW_PASSED_BEFORE_V21_START
  fi
  mig_start_v21 || rc=$?
  if [ "$rc" != 0 ]; then
    mig_hold_stopped V21_START_FAILED
  fi
  mig_complete ROLLED_BACK
  RESTORING=0
  finish "$code" MIGRATION_ROLLED_BACK "$reason" "옛 DB·옛 판으로 되돌림(헬스 통과)"
}

mig_gap_between() { # baseline current — 개수만. 실패하면 GAP_UNKNOWN 경고(복귀 결정은 이미 대표가 내렸다)
  local args
  args=$(py mig-args "$MIG_ID" gap production "run=$MIG_RUN" "baseline=$1" "current=$2")
  if mig_helper "$PREV_ENGINE_IMAGE" "$R$DATA_DIR" gap "$args"; then
    py json-field "$MIG_OUT" result > "$(mig_dir)/gap-$(date -u +%Y%m%dT%H%M%SZ).json"
    log "gap(개수만): 바뀐 표 $(mig_result tables_with_changes)"
  else
    warn GAP_UNKNOWN "gap 을 세지 못했습니다($(mig_code))"
  fi
}

mig_gap_report() {
  local args
  if [ -f "$R$DATA_DIR/engine.db.pre-v22" ]; then
    args=$(py mig-args "$MIG_ID" gap production "run=$MIG_RUN" baseline=engine.db.pre-v22 current=engine.db)
    if mig_helper "$PREV_ENGINE_IMAGE" "$R$DATA_DIR" gap "$args"; then
      py json-field "$MIG_OUT" result > "$(mig_dir)/gap-$(date -u +%Y%m%dT%H%M%SZ).json"
      log "gap(개수만): 바뀐 표 $(mig_result tables_with_changes)"
    fi
  fi
}

# 이관 진행 중 실패(die): 단계별로 정한 경로만 쓴다(fail_deploy 가 부른다).
mig_fail() { # code detail
  trap - ERR
  set +e
  log "이관 실패($1, 단계 $MIG_STAGE): $2"
  case "$MIG_STAGE" in
    ''|preflight)
      finish 10 REFUSED "$1" "서비스는 건드리지 않았습니다" ;;
    recorded|hold)
      py mig-dropin remove >>"$CMD_LOG" 2>&1
      systemctl daemon-reload 2>>"$CMD_LOG"
      py mig-hold remove "$MIG_RUN" >>"$CMD_LOG" 2>&1
      py mig-pin "$MIG_RUN" release >>"$CMD_LOG" 2>&1
      py mig-status "$MIG_RUN" state=ROLLED_BACK "reason=$1" >>"$CMD_LOG" 2>&1
      py state-write "$STATE_FILE" "migration_id=" "phase=aborted_before_stop" >>"$CMD_LOG" 2>&1
      py mig-pointer clear "$MIG_RUN" >>"$CMD_LOG" 2>&1
      finish 10 REFUSED "$1" "정지 전 거부. 서비스는 그대로" ;;
    stopped|chain|swapped)
      mig_auto_rollback "$1" 0 ;;
    started)
      mig_auto_rollback "$1" 1 ;;
    healthy|archiving|completing)
      warn "$1" "이관 마무리 중 실패: $2"
      mig_hold_stopped "$1" ;;
    *)
      mig_unknown "$1" ;;
  esac
}

# 보관(M12·§D): gz 게시 → pin bound-gz → G4 면 raw 삭제. 결과 시점마다 keep_raw_now 를 새로 잰다.
mig_archive_flow() {
  local out name gzsha mansha pre_size krn
  MIG_STAGE=archiving
  set_phase archiving
  pre_size=$(py json-field "$(mig_receipt_field pre_identity)" size)
  if out=$(py mig-archive "$R$DATA_DIR" "$R$DB_BACKUPS" "$MIG_RUN" "$PREV_COMMIT" "$(mig_receipt_path)" "$MIG_ID" 2>>"$CMD_LOG"); then
    read -r name gzsha mansha <<EOF
$out
EOF
    py mig-pin "$MIG_RUN" bind-gz "copy_dir=$DB_BACKUPS/$name" "gz_sha256=$gzsha" "manifest_sha256=$mansha"
    MIG_PIN_STATE=bound-gz
    DB_BACKUP="$DB_BACKUPS/$name"
    if py mig-guard "$R$DATA_DIR=$pre_size" >>"$CMD_LOG" 2>&1; then
      py mig-journal "$R$DATA_DIR" append "$MIG_RUN" unlink_pre intent
      py mig-unlink-pre "$R$DATA_DIR" "$(mig_receipt_path)" >>"$CMD_LOG"
      py mig-journal "$R$DATA_DIR" append "$MIG_RUN" unlink_pre "done"
      info=$(py backup-prune "$R$DB_BACKUPS" 1) || warn BACKUP_PRUNE_FAILED "직전 사본 정리 실패"
      [ -z "${info:-}" ] || log "pin 안 된 직전 사본 정리: $info"
      MIG_KEEP_RAW=$(py mig-keep-raw-now "$R$DATA_DIR" "$R$DAILY_BACKUPS")
      return 0
    fi
    krn=$(py mig-keep-raw-now "$R$DATA_DIR" "$R$DAILY_BACKUPS")
    MIG_KEEP_RAW=$krn
    if [ "$krn" = true ]; then
      warn RAW_KEPT_FOR_ROLLBACK_SPACE "해제 복귀 공간(G4)이 없어 raw 와 gz 를 함께 둡니다"
      return 0
    fi
    mig_hold_stopped "G4_FALSE_KEEP_RAW_$krn"
  fi
  krn=$(py mig-keep-raw-now "$R$DATA_DIR" "$R$DAILY_BACKUPS")
  MIG_KEEP_RAW=$krn
  if [ "$krn" = true ]; then
    warn ARCHIVE_PENDING "gzip 보관 실패. raw 원본을 그대로 둡니다(부분본은 대표 확인 뒤 정리)"
    return 0
  fi
  mig_hold_stopped "ARCHIVE_FAILED_KEEP_RAW_$krn"
}

# continue·재개 공통: pin 상태에 맞춰 보관을 마무리한다. bound-raw 면 gzip 부터, bound-gz 인데 raw 가 남았으면
# G4(해제 복귀 공간)부터 다시 재고 지금 실측 keep_raw_now 로 경고/HOLD 를 정한다.
mig_finish_archive() {
  local state pre_size krn
  [ -f "$R$DATA_DIR/engine.db.pre-v22" ] || return 0
  state=$(py mig-pin "$MIG_RUN" state) || mig_hold_stopped PIN_READ
  if [ "$state" = bound-raw ]; then
    mig_archive_flow
    return 0
  fi
  pre_size=$(py json-field "$(mig_receipt_field pre_identity)" size)
  if py mig-guard "$R$DATA_DIR=$pre_size" >>"$CMD_LOG" 2>&1; then
    py mig-journal "$R$DATA_DIR" append "$MIG_RUN" unlink_pre intent || mig_hold_stopped JOURNAL_WRITE
    py mig-unlink-pre "$R$DATA_DIR" "$(mig_receipt_path)" >>"$CMD_LOG" || mig_hold_stopped RAW_IDENTITY
    py mig-journal "$R$DATA_DIR" append "$MIG_RUN" unlink_pre "done" || mig_hold_stopped JOURNAL_WRITE
    return 0
  fi
  krn=$(py mig-keep-raw-now "$R$DATA_DIR" "$R$DAILY_BACKUPS")
  MIG_KEEP_RAW=$krn
  [ "$krn" = true ] || mig_hold_stopped "G4_FALSE_KEEP_RAW_$krn"
  warn RAW_KEPT_FOR_ROLLBACK_SPACE "해제 복귀 공간(G4)이 없어 raw 와 gz 를 함께 둡니다"
}

# 준비된 이미지 확인: prepare 가 만든 정확 ID, 라벨 source=NEW·schema=to.
mig_check_prepared() {
  local name id user src label to
  MIG_NEW_ENGINE=$(py mig-prepared get "$NEW" engine_image)
  MIG_NEW_RELAY=$(py mig-prepared get "$NEW" relay_image)
  [ -n "$MIG_NEW_ENGINE" ] && [ -n "$MIG_NEW_RELAY" ] || die NOT_PREPARED "migrate-prepare 기록이 없습니다"
  to=$(py mig-field "$MIG_ID" to_schema)
  for name in engine relay; do
    if [ "$name" = engine ]; then id=$MIG_NEW_ENGINE; else id=$MIG_NEW_RELAY; fi
    info=$(dk image inspect "$id" 2>>"$CMD_LOG" | py image-info) || die NOT_PREPARED "준비 이미지가 없습니다: $name"
    read -r _ user src label <<EOF
$info
EOF
    [ "$src" = "$NEW" ] && [ "$user" = 10001:10001 ] && [ "$label" = "$to" ] \
      || die NOT_PREPARED "준비 이미지 라벨이 다릅니다: $name"
  done
  NEW_ENGINE_IMAGE=$MIG_NEW_ENGINE
  NEW_RELAY_IMAGE=$MIG_NEW_RELAY
}

# deploy 1단계와 같은 현재 배치 확인(값은 전역에). deploy 모드 코드는 손대지 않고 같은 규칙을 다시 쓴다.
mig_preflight() {
  local unit name info id user src label
  PHASE=preflight
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
  info=$(py unit-parse "$R$UNIT_DIR/$ENGINE_UNIT" engine) || die LAYOUT "$info"
  M_CUR=${info% *}; M_COMPANION=${info#* }
  info=$(py unit-parse "$R$UNIT_DIR/$RELAY_UNIT" relay) || die LAYOUT "$info"
  [ "${info% *}" = "$M_CUR" ] || die LAYOUT "engine·relay unit 이 다른 판을 가리킵니다"
  PREV_COMMIT=$M_CUR
  for name in engine relay; do
    info=$(py override-check "$R$RELEASES/naver-$M_CUR/preview-$name.override.yml" "$name" "$M_CUR") || die LAYOUT "$info"
    info=$(dk image inspect "metainc/naver-$name:$M_CUR" 2>>"$CMD_LOG" | py image-info) || die LAYOUT "현재 이미지 정보 없음"
    read -r id user src label <<EOF
$info
EOF
    : "$label"
    [ "$src" = "$M_CUR" ] && [ "$user" = 10001:10001 ] || die LAYOUT "현재 $name 이미지 라벨/사용자 이상"
    read_container "naver-$name" || die LAYOUT "naver-$name 컨테이너를 정확히 하나 찾지 못했습니다"
    [ "$C_RUNNING" = true ] && [ "$C_IMAGE" = "$id" ] || die NOT_ACTIVE "naver-$name 컨테이너 상태 이상"
    [ "$C_USER" = 10001:10001 ] || die LAYOUT "naver-$name 컨테이너 사용자 이상"
    if [ "$name" = engine ]; then
      PREV_ENGINE_IMAGE=$id; PREV_ENGINE_MOUNTS=$C_MOUNTS; CUR_SWITCHES=$C_SWITCHES
      case ",$CUR_SWITCHES," in *,execution=false,*) ;; *) die EXECUTION_ENABLED "execution 스위치가 false 가 아닙니다" ;; esac
    else
      PREV_RELAY_IMAGE=$id; PREV_RELAY_MOUNTS=$C_MOUNTS
    fi
  done
}

mig_lock() {
  mkdir -p "$R$STATE_DIR/runs" "$R$STATE_DIR/logs"
  chmod 700 "$R$STATE_DIR" "$R$STATE_DIR/logs"
  exec 9>>"$R$STATE_DIR/lock"
  if ! flock -n 9; then
    RESULT_CODE=11; RESULT_STATUS=LOCKED; RESULT_REASON=LOCKED
    log "결과: LOCKED — 다른 naver-deploy 가 실행 중입니다"
    exit 11
  fi
  M_STAMP=$(date -u +%Y%m%dT%H%M%SZ)
  CMD_LOG="$R$STATE_DIR/logs/commands-$M_STAMP.log"
  : > "$CMD_LOG"
  py prune-logs "$R$STATE_DIR/logs" 10
}

mig_common_inputs() { # commit tar id
  NEW=$1; M_TAR=$2; MIG_ID=$3
  printf '%s' "$NEW" | grep -Eq '^[0-9a-f]{40}$' || { NEW=''; die BAD_INPUT "커밋은 40자리 소문자 16진수여야 합니다"; }
  [ -f "$M_TAR" ] || die BAD_INPUT "source.tar 가 없습니다"
  printf '%s' "$MIG_ID" | grep -Eq '^[0-9a-z-]{1,40}$' || die BAD_INPUT "migration id 형식"
  py mig-field "$MIG_ID" to_schema >/dev/null || die MIGRATION_UNKNOWN "고정 표에 없는 이관입니다"
  [ -f "$MIG_HELPER" ] || die BAD_INPUT "helper 파일이 없습니다"
  if [ "$TEST_MODE" = 0 ] && [ "$(id -u)" != 0 ]; then die NOT_ROOT "root 로 실행해야 합니다"; fi
}

mig_source_checks() { # 스키마 쌍·고정 해시·실행 중 v21 store·helper
  local cid
  SCHEMA_NEW=$(py tar-check "$M_TAR") || { info=$SCHEMA_NEW; SCHEMA_NEW=''; die ARCHIVE "$info"; }
  SCHEMA_CUR=$(image_schema "$PREV_ENGINE_IMAGE") || die SCHEMA_UNKNOWN "실행 중 이미지의 SCHEMA_VERSION 을 읽지 못했습니다"
  [ "$SCHEMA_NEW" != "$SCHEMA_CUR" ] || die MIGRATION_NOT_NEEDED "스키마가 같습니다"
  info=$(py mig-tar-pins "$M_TAR" "$MIG_ID" "$M_CUR" "$NEW" "$SCHEMA_CUR" "$SCHEMA_NEW") || die MIGRATION_REFUSED "$info"
  cid=$(dk create --network none "$PREV_ENGINE_IMAGE" 2>>"$CMD_LOG") || die LAYOUT "실행 중 이미지 store.py 를 읽지 못했습니다"
  info=$(dk cp "$cid:/opt/naver-engine/naver_engine/store.py" - 2>>"$CMD_LOG" | py mig-store-sha-stdin "$MIG_ID") || info=FAIL
  dk rm "$cid" >>"$CMD_LOG" 2>&1 || warn TEMP_CONTAINER_LEFT "임시 컨테이너 삭제 실패"
  [ "$info" = ok ] || die MIGRATION_RUNNING_PIN "실행 중 v21 이미지의 store.py 가 고정 표와 다릅니다"
  info=$(py mig-helper-pin "$MIG_HELPER" "$MIG_ID") || die MIGRATION_HELPER_PIN "$info"
  info=$(py mig-requires "$MIG_ID") || die MIGRATION_ORDER "$info"
}

mig_release_and_build_checks() { # 준비된 release 폴더·override 확인과 설정 묶음·check-config(빌드 없음)
  local name override shape_old shape_new new_switches
  M_REL_NEW="$RELEASES/naver-$NEW"
  info=$(py tree-compare "$M_TAR" "$R$M_REL_NEW") || die RELEASE_DIR_DIFFERS "$info"
  for name in engine relay; do
    override="$R$M_REL_NEW/preview-$name.override.yml"
    py subst "$R$M_RUN_DIR/preview-$name.override.yml" "$R$M_RUN_DIR/new-preview-$name.override.yml" "$M_CUR" "$NEW" 1
    if [ -e "$override" ]; then
      [ "$(py sha "$override")" = "$(py sha "$R$M_RUN_DIR/new-preview-$name.override.yml")" ] \
        || die RELEASE_DIR_DIFFERS "$override 가 현재 override 에서 커밋만 바꾼 내용과 다릅니다"
    else
      write_file_atomic "$R$M_RUN_DIR/new-preview-$name.override.yml" "$override" 600
    fi
    dk tag "$( [ "$name" = engine ] && echo "$MIG_NEW_ENGINE" || echo "$MIG_NEW_RELAY" )" "metainc/naver-$name:$NEW" >>"$CMD_LOG" 2>&1 \
      || die NOT_PREPARED "준비 이미지 태그 실패"
    shape_old=$(compose_shape "$name" "$RELEASES/naver-$M_CUR" "$M_COMPANION") || die COMPOSE_CONFIG "현재 $name compose 설정"
    shape_new=$(compose_shape "$name" "$M_REL_NEW" "$M_COMPANION") || die COMPOSE_CONFIG "새 $name compose 설정"
    info=$(py shape-diff "$shape_old" "$shape_new") || die CONFIG_SHAPE_CHANGED "$info"
  done
  compose_args engine "$M_REL_NEW" "$M_COMPANION"
  new_switches=$(dk "${CARGS[@]}" config --format json 2>>"$CMD_LOG" | py check-config-run "$MIG_NEW_ENGINE" "$CMD_LOG" off) \
    || die CHECK_CONFIG "$new_switches"
  [ "$new_switches" = "$CUR_SWITCHES" ] || die FLAGS_CHANGED "새 판 스위치가 현재와 다릅니다"
}

# ── migrate-prepare: 서버에서 v22 이미지를 한 번 빌드하고 정확 ID 를 기록한다(서비스 무변경) ──
main_migrate_prepare() {
  local name id user src label rel_new
  mig_common_inputs "$@"
  mig_lock
  recover_if_needed
  mig_preflight
  mig_source_checks
  rel_new="$RELEASES/naver-$NEW"
  if [ -e "$R$rel_new" ]; then
    info=$(py tree-compare "$M_TAR" "$R$rel_new") || die RELEASE_DIR_DIFFERS "$info"
  else
    py tar-extract "$M_TAR" "$R$rel_new"
  fi
  PHASE=building
  for name in engine relay; do
    dk build --quiet --label "metainc.naver.preview.source=$NEW" --label "metainc.naver.schema=$SCHEMA_NEW" \
      -t "metainc/naver-$name:$NEW" -f "$R$rel_new/Dockerfile.naver-$name" "$R$rel_new" >>"$CMD_LOG" 2>&1 \
      || die BUILD_FAILED "metainc/naver-$name:$NEW 빌드 실패"
    info=$(dk image inspect "metainc/naver-$name:$NEW" 2>>"$CMD_LOG" | py image-info) || die BUILD_FAILED "새 이미지 정보 없음"
    read -r id user src label <<EOF
$info
EOF
    [ "$src" = "$NEW" ] && [ "$user" = 10001:10001 ] && [ "$label" = "$SCHEMA_NEW" ] || die BUILD_FAILED "새 이미지 라벨 이상"
    if [ "$name" = engine ]; then MIG_NEW_ENGINE=$id; else MIG_NEW_RELAY=$id; fi
  done
  py mig-prepared write "$NEW" "engine_image=$MIG_NEW_ENGINE" "relay_image=$MIG_NEW_RELAY" "previous_commit=$M_CUR" \
    "previous_engine_image=$PREV_ENGINE_IMAGE" "previous_relay_image=$PREV_RELAY_IMAGE" "prepared_at=$M_STAMP"
  NEW_ENGINE_IMAGE=$MIG_NEW_ENGINE; NEW_RELAY_IMAGE=$MIG_NEW_RELAY; PREV_COMMIT=$M_CUR
  PHASE=prepared
  finish 0 PREPARED '' "이미지 준비: engine $MIG_NEW_ENGINE relay $MIG_NEW_RELAY (서비스 무변경)"
}

# ── migrate-rehearse: 준비된 정확 이미지로 scratch 에서만 끝까지(운영 DATA_DIR 은 붙이지 않는다) ──
main_migrate_rehearse() {
  local scratch data step args rc=0 helper_sha probe_new probe_old to_schema from_schema receipt
  mig_common_inputs "$@"
  mig_lock
  recover_if_needed
  mig_preflight
  mig_source_checks
  mig_check_prepared
  to_schema=$(py mig-field "$MIG_ID" to_schema)
  from_schema=$(py mig-field "$MIG_ID" from_schema)
  MIG_RUN="$M_STAMP-$(printf '%s' "$NEW" | cut -c1-12)"
  scratch="$R$STATE_DIR/rehearse/$MIG_RUN"
  data="$scratch/data"
  mkdir -p "$data"
  chmod 700 "$scratch" "$data"
  [ "$TEST_MODE" = 1 ] || chown 10001:10001 "$data"
  [ "$(py same-device-inode "$data" "$R$DATA_DIR")" = different ] || die REHEARSAL_LAYOUT "scratch 가 운영 DATA_DIR 와 같습니다"
  : > "$data/naver-migrate-rehearsal-marker"
  [ "$TEST_MODE" = 1 ] || chown 10001:10001 "$data/naver-migrate-rehearsal-marker"
  helper_sha=$(py file-sha "$MIG_HELPER")
  PHASE=rehearsing
  args=$(py mig-args "$MIG_ID" probe-old rehearsal)
  mig_helper "$PREV_ENGINE_IMAGE" "$data" probe "$args" || rc=1
  probe_old=$(mig_result sqlite_version 2>/dev/null || true)
  args=$(py mig-args "$MIG_ID" probe-new rehearsal)
  mig_helper "$MIG_NEW_ENGINE" "$data" probe "$args" || rc=1
  probe_new=$(mig_result sqlite_version 2>/dev/null || true)
  [ "$(mig_result features octet_length 2>/dev/null)" = True ] || rc=1
  if [ "$rc" = 0 ]; then
    args=$(py mig-args "$MIG_ID" seed rehearsal "run=$MIG_RUN")
    mig_helper "$PREV_ENGINE_IMAGE" "$data" seed "$args" || rc=1
  fi
  if [ "$rc" = 0 ]; then
    args=$(py mig-args "$MIG_ID" chain rehearsal "run=$MIG_RUN" floor_bytes=1073741824)
    mig_helper "$MIG_NEW_ENGINE" "$data" chain "$args" || rc=1
  fi
  if [ "$rc" = 0 ]; then
    receipt="$data/naver-migrate-receipt.json"
    args=$(py mig-args "$MIG_ID" startcheck rehearsal "run=$MIG_RUN" \
      "expect_identity=json:$(py json-field "$(cat "$receipt")" work_identity)" \
      "expect_sha256=$(py json-field "$(cat "$receipt")" work_sha256)" full=json:true "expect_schema=$to_schema")
    mig_helper "$MIG_NEW_ENGINE" "$data" startcheck "$args" || rc=1
  fi
  if [ "$rc" = 0 ]; then
    args=$(py mig-args "$MIG_ID" old-refuses rehearsal "run=$MIG_RUN" "expect_schema=$to_schema")
    mig_helper "$PREV_ENGINE_IMAGE" "$data" old-refuses "$args" || rc=1
  fi
  if [ "$rc" = 0 ]; then
    # 옛 writer 가 남긴 빈 곁 파일을 잠금 아래 정리(startcheck)한 뒤 되돌림을 시험한다.
    args=$(py mig-args "$MIG_ID" startcheck rehearsal "run=$MIG_RUN" \
      "expect_identity=json:$(py json-field "$(cat "$receipt")" work_identity)" \
      "expect_sha256=$(py json-field "$(cat "$receipt")" work_sha256)" full=json:true "expect_schema=$to_schema")
    mig_helper "$MIG_NEW_ENGINE" "$data" startcheck "$args" || rc=1
  fi
  if [ "$rc" = 0 ]; then
    args=$(py mig-args "$MIG_ID" undo rehearsal "run=$MIG_RUN" "receipt=@$receipt")
    mig_helper "$MIG_NEW_ENGINE" "$data" undo "$args" || rc=1
  fi
  if [ "$rc" = 0 ]; then
    args=$(py mig-args "$MIG_ID" old-opens rehearsal "run=$MIG_RUN" "expect_schema=$from_schema")
    mig_helper "$PREV_ENGINE_IMAGE" "$data" old-opens "$args" || rc=1
  fi
  [ "$rc" = 0 ] || log "리허설 실패 단계 코드: $(mig_code)"
  rm -rf -- "$scratch"
  MIG_REHEARSAL=$( [ "$rc" = 0 ] && echo passed || echo failed )
  py mig-rehearsal write "result=$MIG_REHEARSAL" "engine_image=$MIG_NEW_ENGINE" "relay_image=$MIG_NEW_RELAY" \
    "previous_engine_image=$PREV_ENGINE_IMAGE" "helper_sha256=$helper_sha" "run=$MIG_RUN" \
    "sqlite_new=$probe_new" "sqlite_old=$probe_old" "bind=scratch" "at=$M_STAMP"
  PREV_COMMIT=$M_CUR
  if [ "$rc" = 0 ]; then finish 0 REHEARSED '' "격리 리허설 통과(운영 DB 미사용)"; fi
  finish 10 REHEARSAL_FAILED REHEARSAL "격리 리허설 실패(운영 DB 미사용)"
}

mig_plan_now() {
  local tar_sha helper_sha
  tar_sha=$(py sha "$M_TAR")
  helper_sha=$(py file-sha "$MIG_HELPER")
  py mig-plan "$MIG_ID" "$M_CUR" "$NEW" "$tar_sha" "$helper_sha" "$MIG_NEW_ENGINE" "$MIG_NEW_RELAY" \
    "$PREV_ENGINE_IMAGE" "$PREV_RELAY_IMAGE"
}

# ── migrate-plan: 읽기 전용 계획(plan_sha256) ──
main_migrate_plan() {
  local out
  mig_common_inputs "$@"
  mig_lock
  if [ -n "$(py mig-pointer get)" ] || [ -n "$(py mig-hold get)" ] || [ "$(py mig-dropin present)" != no ]; then
    die MIGRATION_ACTIVE "이관 표지가 남아 있습니다(읽기 전용 계획은 복구하지 않습니다)"
  fi
  mig_preflight
  mig_source_checks
  mig_check_prepared
  out=$(mig_plan_now) || die PLAN "$out"
  MIG_PLAN=$(printf '%s\n' "$out" | sed -n 1p)
  printf '%s\n' "$out" | sed -n 2p > "$R$STATE_DIR/migration/plan-$MIG_PLAN.json"
  PREV_COMMIT=$M_CUR
  finish 0 PLANNED '' "plan_sha256=$MIG_PLAN"
}

# ── migrate-deploy ──
main_migrate_deploy() {
  local plan_in size files f name unit sum_runtime sum_tmpfiles sum_tunnel sum_nginx tar_size krn deployed_at rc
  plan_in=${4:-}
  mig_common_inputs "$1" "$2" "$3"
  printf '%s' "$plan_in" | grep -Eq '^[0-9a-f]{64}$' || die BAD_INPUT "plan_sha256 형식"
  mig_lock
  recover_if_needed
  MIG_STAGE=preflight
  mig_preflight
  mig_source_checks
  mig_check_prepared
  py mig-rehearsal check "$MIG_NEW_ENGINE" "$MIG_NEW_RELAY" "$(py file-sha "$MIG_HELPER")" >/dev/null \
    || die REHEARSAL_MISSING "이 준비 이미지로 통과한 격리 리허설이 없습니다"
  deployed_at=$(py state-get "$R$STATE_DIR/current.json" deployed_at 2>/dev/null || true)
  info=$(py mig-window 21:30 "$R$BACKUP_STATE" "$deployed_at") || die WINDOW "$info"
  info=$(py db-files "$R$DATA_DIR") || die DB_FILES "$info"
  size=${info%% *}
  for f in naver-migrate-journal.json naver-migrate-receipt.json; do
    [ ! -e "$R$DATA_DIR/$f" ] || die LEFTOVERS "이전 이관 기록이 DATA_DIR 에 남아 있습니다"
  done
  MIG_PLAN=$(mig_plan_now | sed -n 1p)
  [ "$MIG_PLAN" = "$plan_in" ] || die PLAN_MISMATCH "계획이 승인한 plan_sha256 과 다릅니다"
  tar_size=$(wc -c < "$M_TAR" | tr -d ' ')
  info=$(py mig-guard "$R$DATA_DIR=$((size + tar_size))") || die SPACE_G0 "$info"

  # ── M3 기록: run·활성 표지·상태 ACTIVE·pin pending(멈추기 전) ──
  MIG_RUN="$M_STAMP-$(printf '%s' "$NEW" | cut -c1-12)"
  M_RUN_DIR="$STATE_DIR/runs/$M_STAMP-$(printf '%s' "$NEW" | cut -c1-12)"
  mkdir "$R$M_RUN_DIR"
  for name in engine relay; do
    cp "$R$UNIT_DIR/metainc-naver-$name.service" "$R$M_RUN_DIR/metainc-naver-$name.service"
    cp "$R$RELEASES/naver-$M_CUR/preview-$name.override.yml" "$R$M_RUN_DIR/preview-$name.override.yml"
  done
  printf '%s\n' "$PREV_ENGINE_MOUNTS" > "$R$M_RUN_DIR/mounts-engine.json"
  printf '%s\n' "$PREV_RELAY_MOUNTS" > "$R$M_RUN_DIR/mounts-relay.json"
  cat "$CMD_LOG" > "$R$M_RUN_DIR/commands.log"
  rm -f "$CMD_LOG"
  CMD_LOG="$R$M_RUN_DIR/commands.log"
  rm -f "$STATE_FILE"
  HAVE_STATE=1
  MIG_ACTIVE=1
  MIG_STAGE=recorded
  py state-write "$STATE_FILE" "phase=preparing" "new_commit=$NEW" "prev_commit=$M_CUR" \
    "prev_engine_image=$PREV_ENGINE_IMAGE" "prev_relay_image=$PREV_RELAY_IMAGE" "run_dir=$M_RUN_DIR" \
    "companion=$M_COMPANION" "schema=$SCHEMA_NEW" "switches=$CUR_SWITCHES" "started_at=$M_STAMP" \
    "migration_id=$MIG_ID" "migration_run=$MIG_RUN" "new_engine_image=$MIG_NEW_ENGINE" "new_relay_image=$MIG_NEW_RELAY"
  for name in engine relay; do
    dk tag "$( [ "$name" = engine ] && echo "$PREV_ENGINE_IMAGE" || echo "$PREV_RELAY_IMAGE" )" \
      "metainc/naver-$name:rollback-$(printf '%s' "$MIG_RUN" | cut -c18-29)" >>"$CMD_LOG" 2>&1 || die PIN "복귀 태그 실패"
  done
  py mig-pin "$MIG_RUN" create "commit=$M_CUR" "new_commit=$NEW" "engine_image=$PREV_ENGINE_IMAGE" \
    "relay_image=$PREV_RELAY_IMAGE" "new_engine_image=$MIG_NEW_ENGINE" "new_relay_image=$MIG_NEW_RELAY" \
    "run_dir=$M_RUN_DIR" "companion=$M_COMPANION" "switches=$CUR_SWITCHES" "migration_id=$MIG_ID" \
    "engine_unit_sha256=$(py sha "$R$M_RUN_DIR/metainc-naver-engine.service")" \
    "relay_unit_sha256=$(py sha "$R$M_RUN_DIR/metainc-naver-relay.service")" \
    "engine_override_sha256=$(py sha "$R$M_RUN_DIR/preview-engine.override.yml")" \
    "relay_override_sha256=$(py sha "$R$M_RUN_DIR/preview-relay.override.yml")" \
    "release_tree_sha256=$(py tree-sha "$R$RELEASES/naver-$M_CUR")"
  MIG_PIN_STATE=pending
  # 활성 표지는 pin 뒤에(복구가 pin 으로 v21 세대를 찾는다). 표지 → 상태 ACTIVE 순.
  py mig-pointer set "$MIG_RUN"
  py mig-status "$MIG_RUN" state=ACTIVE "migration_id=$MIG_ID" "plan_sha256=$MIG_PLAN"
  MIG_STATE=ACTIVE
  P_RUN_DIR=$M_RUN_DIR; P_COMPANION=$M_COMPANION; P_SWITCHES=$CUR_SWITCHES; P_NEW_COMMIT=$NEW
  mig_release_and_build_checks
  sum_runtime=$(py sha "$R$RUNTIME_ENV" 2>/dev/null || echo absent)
  sum_tmpfiles=$(py sha "$R$TMPFILES_CONF")
  sum_tunnel=$(py sha "$R$UNIT_DIR/$TUNNEL_UNIT" 2>/dev/null || echo absent)
  sum_nginx=$(py tree-sha "$R$NGINX_DIR")
  set_phase prepared

  # ── M3a 시작 차단 → M4 정지 ──
  MIG_STAGE=hold
  mig_install_hold
  MIG_STAGE=stopped
  set_phase stopping
  STOP_STARTED=$SECONDS
  stop_and_wait "$RELAY_UNIT" naver-relay || die STOP_FAILED "relay 정지 확인 실패"
  stop_and_wait "$ENGINE_UNIT" naver-engine || die STOP_FAILED "engine 정지 확인 실패"

  # ── M5-M8 chain: 한 프로세스가 원본 잠금을 쥐고 사본 이관·검증·교체 ──
  set_phase db_copying
  MIG_STAGE=chain
  args=$(py mig-args "$MIG_ID" chain production "run=$MIG_RUN" floor_bytes=1073741824)
  mig_helper "$MIG_NEW_ENGINE" "$R$DATA_DIR" chain "$args" || die "CHAIN_$(mig_code)" "chain 실패"
  MIG_RECEIPT_SHA=$(py mig-receipt "$R$DATA_DIR" "$MIG_RUN" copy)
  [ "$MIG_RECEIPT_SHA" = "$(mig_result receipt_sha256)" ] || die RECEIPT "영수증 해시가 helper 결과와 다릅니다"
  MIG_ORPHANS=$(mig_result orphans_closed)
  MIG_STAGE=swapped
  py mig-status "$MIG_RUN" "receipt_sha256=$MIG_RECEIPT_SHA"
  py mig-pin "$MIG_RUN" bind-raw "receipt_sha256=$MIG_RECEIPT_SHA" "pre_identity=$(mig_receipt_field pre_identity)" \
    "pre_sha256=$(mig_receipt_field pre_sha256)" "raw_path=$DATA_DIR/engine.db.pre-v22"
  MIG_PIN_STATE=bound-raw
  info=$(py mig-guard "$R$DATA_DIR=0") || die SPACE_G2 "$info"
  log "chain 완료: 검증·교체(orphan 회차 $MIG_ORPHANS 건 닫힘)"

  # ── M9 unit 교체·컨테이너 생성(시작 안 함) ──
  set_phase switching
  py subst "$R$M_RUN_DIR/$ENGINE_UNIT" "$R$M_RUN_DIR/new-$ENGINE_UNIT" "$M_CUR" "$NEW" 6
  py subst "$R$M_RUN_DIR/$RELAY_UNIT" "$R$M_RUN_DIR/new-$RELAY_UNIT" "$M_CUR" "$NEW" 4
  write_file_atomic "$R$M_RUN_DIR/new-$ENGINE_UNIT" "$R$UNIT_DIR/$ENGINE_UNIT" 644
  write_file_atomic "$R$M_RUN_DIR/new-$RELAY_UNIT" "$R$UNIT_DIR/$RELAY_UNIT" 644

  # ── M10 시각 창 → guarded_start v22 ──
  if ! py mig-window 23:00 "$R$BACKUP_STATE" >>"$CMD_LOG" 2>&1; then
    mig_hold_stopped WINDOW_PASSED_BEFORE_START
  fi
  MIG_KEEP_RAW=$(py mig-keep-raw-now "$R$DATA_DIR" "$R$DAILY_BACKUPS")
  log "keep_raw_now(기동 전, 정보용): $MIG_KEEP_RAW"
  rc=0
  guarded_start v22 "$(mig_receipt_field work_identity)" "$(mig_receipt_field work_sha256)" true || rc=$?
  if [ "$rc" = 1 ]; then
    die START_CHECK "guarded_start v22 사전 확인 실패"
  elif [ "$rc" = 3 ]; then
    # start intent 기록·hold 해제 전이 실패·불명: 어떤 기동도 하지 않고 정지 보존(대표 판단).
    mig_hold_stopped START_TRANSITION_FAILED
  elif [ "$rc" != 0 ]; then
    die HEALTH "v22 헬스 실패($HEALTH_STATUS $HEALTH_CODES)"
  fi
  py mig-journal "$R$DATA_DIR" append "$MIG_RUN" health "done"
  py mig-status "$MIG_RUN" state=HEALTHY
  MIG_STATE=HEALTHY
  MIG_STAGE=healthy

  # ── M12 보관 → M13 종결 ──
  mig_archive_flow
  MIG_STAGE=completing
  [ "$(py sha "$R$RUNTIME_ENV" 2>/dev/null || echo absent)" = "$sum_runtime" ] || warn RUNTIME_ENV_CHANGED "runtime.env 변경 감지"
  [ "$(py sha "$R$TMPFILES_CONF")" = "$sum_tmpfiles" ] || warn TMPFILES_CHANGED "tmpfiles 변경 감지"
  [ "$(py sha "$R$UNIT_DIR/$TUNNEL_UNIT" 2>/dev/null || echo absent)" = "$sum_tunnel" ] || warn TUNNEL_UNIT_CHANGED "터널 unit 변경 감지"
  [ "$(py tree-sha "$R$NGINX_DIR")" = "$sum_nginx" ] || warn NGINX_CHANGED "nginx 변경 감지"
  mig_complete COMPLETED
  PHASE='done'
  if [ -n "$WARNINGS" ]; then
    finish 0 MIGRATED_WITH_WARNINGS "$WARNINGS" "$M_CUR → $NEW 이관 배포 완료(경고 있음)"
  fi
  finish 0 MIGRATED '' "$M_CUR → $NEW 이관 배포 완료"
}

mig_owner_run() { # run → pointer·pin 로드(continue/rollback/accept 공통)
  MIG_RUN=$1
  printf '%s' "$MIG_RUN" | grep -Eq '^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$' || die BAD_INPUT "run id 형식"
  MIG_ID=$(py mig-status-get "$MIG_RUN" migration_id)
  [ -n "$MIG_ID" ] || die MIGRATION_UNKNOWN "이 run 의 이관 기록이 없습니다"
  MIG_STATE=$(py mig-status-get "$MIG_RUN" state)
  mig_load_pin || die PIN_MISSING "복귀 pin 이 없습니다"
  NEW=$P_NEW_COMMIT
  STATE_FILE="$R$STATE_DIR/state.json"
}

# ── migrate-continue: HOLD 된 v22 세대를 대표 판단으로 다시 기동 ──
main_migrate_continue() {
  local rc=0 identity
  mig_lock
  MIG_ALLOW_HOLD=1
  recover_if_needed
  mig_owner_run "$1"
  [ "$MIG_STATE" = HOLD ] || die NOT_HELD "HOLD 상태가 아닙니다($MIG_STATE)"
  [ "$(py mig-pointer get)" = "$MIG_RUN" ] || die NOT_ACTIVE_RUN "활성 run 이 아닙니다"
  MIG_ACTIVE=1; HAVE_STATE=1
  M_RUN_DIR=$P_RUN_DIR
  CMD_LOG="$R$P_RUN_DIR/commands.log"
  MIG_STAGE=started
  py mig-status "$MIG_RUN" state=ACTIVE
  info=$(py mig-window 23:00 "$R$BACKUP_STATE") || mig_hold_stopped "WINDOW_$info"
  mig_stop_both || mig_unknown STOP_NOT_CONFIRMED
  mig_prove
  [ "$MIG_DECISION" != unknown ] || mig_hold_stopped CONTINUE_PROVE_UNKNOWN
  identity=$(py identity "$R$DATA_DIR/engine.db") || mig_unknown CANONICAL_MISSING
  [ "$(py ino-of "$identity")" = "$(py ino-of "$(mig_receipt_field work_identity)")" ] || mig_unknown NOT_V22_GENERATION
  guarded_start v22 "$identity" '' false || rc=$?
  [ "$rc" = 0 ] || mig_hold_stopped CONTINUE_START_FAILED
  py mig-journal "$R$DATA_DIR" append "$MIG_RUN" health "done"
  py mig-status "$MIG_RUN" state=HEALTHY
  MIG_STAGE=healthy
  mig_finish_archive
  mig_complete COMPLETED
  finish 0 CONTINUED '' "v22 세대 재기동·헬스 통과"
}

# ── migrate-rollback(R7): bound pin 의 v21 세대로 되돌림. v22 세대는 묶음으로 보존 ──
main_migrate_rollback() {
  local rc=0 stamp_now copy_dir pre_size args bundle
  mig_lock
  MIG_ALLOW_HOLD=1
  recover_if_needed
  mig_owner_run "$1"
  py mig-pin "$MIG_RUN" check >/dev/null || die PIN_NOT_BOUND "R7 은 bound 된 복귀 묶음만 씁니다"
  case "$MIG_STATE" in HOLD|HEALTHY|COMPLETED) ;; *) die NOT_ROLLBACKABLE "되돌릴 수 있는 상태가 아닙니다($MIG_STATE)" ;; esac
  for name in engine relay; do
    dk image inspect "$( [ "$name" = engine ] && echo "$PREV_ENGINE_IMAGE" || echo "$PREV_RELAY_IMAGE" )" >/dev/null 2>&1 \
      || die PIN_MEMBER_CHANGED "pin 된 v21 이미지가 없습니다"
  done
  if [ -f "$R$DATA_DIR/engine.db.pre-v22" ]; then pre_size=0; else pre_size=$(py json-field "$(mig_receipt_field pre_identity)" size); fi
  info=$(py mig-guard "$R$DATA_DIR=$pre_size") || die SPACE_G5 "$info"
  info=$(py mig-window 23:00 "$R$BACKUP_STATE") || die WINDOW "$info"
  MIG_ACTIVE=1; HAVE_STATE=1
  CMD_LOG="$R$P_RUN_DIR/commands.log"
  py mig-pointer set "$MIG_RUN"
  py mig-status "$MIG_RUN" state=HOLD reason=ROLLBACK_IN_PROGRESS
  py mig-hold create "$MIG_RUN"
  py mig-dropin install
  systemctl daemon-reload 2>>"$CMD_LOG"
  mig_unit_dropins_ok || mig_unknown HOLD_INSTALL
  mig_stop_both || mig_unknown STOP_NOT_CONFIRMED
  mig_prove
  mig_gap_report
  stamp_now=$(date -u +%Y%m%dT%H%M%SZ)
  args=$(py mig-args "$MIG_ID" bundle production "run=$MIG_RUN" "stamp=$stamp_now" "receipt=@$(mig_receipt_path)")
  mig_helper "$PREV_ENGINE_IMAGE" "$R$DATA_DIR" bundle "$args" || mig_unknown "BUNDLE_$(mig_code)"
  bundle=$(mig_result bundle)
  if [ -f "$R$DATA_DIR/engine.db.pre-v22" ]; then
    args=$(py mig-args "$MIG_ID" restore-rename production "run=$MIG_RUN" "receipt=@$(mig_receipt_path)")
    mig_helper "$PREV_ENGINE_IMAGE" "$R$DATA_DIR" restore-rename "$args" || mig_unknown "RESTORE_$(mig_code)"
  else
    copy_dir=$(py json-field "$(cat "$R$STATE_DIR/pins/$MIG_RUN.json")" copy_dir)
    [ -n "$copy_dir" ] || mig_unknown NO_PINNED_COPY
    py mig-restore-gz "$R$copy_dir" "$R$DATA_DIR" "$MIG_RUN" "$(mig_receipt_path)" "$MIG_ID" >>"$CMD_LOG" 2>&1 || mig_unknown RESTORE_GZ_FAILED
    # raw 가 없던 복귀(F4): 풀어 놓은 v21(기준)과 묶음의 v22(현재)로 값 없이 gap 을 센다. 추가 공간이 들지 않는다.
    mig_gap_between engine.db "$bundle/engine.db"
  fi
  MIG_STAGE=rollback
  mig_start_v21 || rc=$?
  [ "$rc" = 0 ] || mig_hold_stopped V21_START_FAILED
  mig_complete ROLLED_BACK
  finish 2 MIGRATION_ROLLED_BACK OWNER_ROLLBACK "대표 승인 복귀: 옛 DB·옛 판(v22 세대는 묶음 보존)"
}

# ── migrate-accept: 대표 확정 → 복귀 묶음 pin 해제(raw 가 남았으면 지운다) ──
main_migrate_accept() {
  local copy_dir manifest
  mig_lock
  recover_if_needed
  mig_owner_run "$1"
  [ "$MIG_STATE" = COMPLETED ] || die NOT_COMPLETED "COMPLETED 상태가 아닙니다($MIG_STATE)"
  [ -z "$(py mig-pointer get)" ] || die MIGRATION_ACTIVE "활성 이관이 있습니다"
  if [ -f "$R$DATA_DIR/engine.db.pre-v22" ]; then
    py mig-unlink-pre "$R$DATA_DIR" "$(mig_receipt_path)" >>"$CMD_LOG" || die RAW_IDENTITY "raw 원본 확인 실패"
  fi
  copy_dir=$(py json-field "$(cat "$R$STATE_DIR/pins/$MIG_RUN.json")" copy_dir)
  if [ -n "$copy_dir" ] && [ -f "$R$copy_dir/manifest.json" ]; then
    manifest=$(cat "$R$copy_dir/manifest.json")
    printf '%s' "$manifest" | python3 -I -B -c 'import json,sys; v=json.load(sys.stdin); v["pinned"]=False; print(json.dumps(v,sort_keys=True,indent=1))' \
      > "$R$copy_dir/manifest.json.tmp"
    mv -f "$R$copy_dir/manifest.json.tmp" "$R$copy_dir/manifest.json"
  fi
  for name in engine relay; do
    dk image rm "metainc/naver-$name:rollback-$(printf '%s' "$MIG_RUN" | cut -c18-29)" >>"$CMD_LOG" 2>&1 \
      || warn ROLLBACK_TAG_LEFT "복귀 태그 정리 실패"
  done
  py mig-pin "$MIG_RUN" release
  MIG_PIN_STATE=released
  finish 0 ACCEPTED '' "이관 확정: 복귀 묶음 pin 해제"
}

# ── B.3 재진입: 모든 잠금 모드에서 가장 먼저(관측 → 그다음 hold) ──
mig_recover() {
  local pointer hold dropins status run started healthy obs current
  pointer=$(py mig-pointer get)
  hold=$(py mig-hold get)
  dropins=$(py mig-dropin present)
  if [ -z "$pointer" ] && [ -z "$hold" ] && [ "$dropins" = no ]; then
    return 0
  fi
  run=$pointer
  [ -n "$run" ] || run=$hold
  if [ -z "$run" ] || [ "$run" = unknown ]; then
    MIG_RUN=''
    mig_unknown MIGRATION_MARKERS_WITHOUT_RUN
  fi
  MIG_RUN=$run
  MIG_ID=$(py mig-status-get "$MIG_RUN" migration_id)
  status=$(py mig-status-get "$MIG_RUN" state)
  MIG_STATE=$status
  mig_load_pin || mig_unknown PIN_MISSING
  CMD_LOG="$R$P_RUN_DIR/commands.log"
  HAVE_STATE=1; MIG_ACTIVE=1
  case "$status" in
    COMPLETED|ROLLED_BACK)
      # rule 3: 종결 세대 재확인 → 3a~7 정리만. 정지·DB 동작·hold 생성 없음.
      mig_terminal_generation_ok "$status" || mig_hold_stopped TERMINAL_GENERATION_MISMATCH
      mig_complete "$status"
      log "종결된 이관($status)의 남은 표지만 정리했습니다"
      return 0 ;;
  esac
  # HOLD 는 과거 health 기록보다 먼저 본다(F1): 대표 모드(continue/rollback)가 그대로 이어받는다.
  if [ "$status" = HOLD ]; then
    if [ "$MIG_ALLOW_HOLD" = 1 ]; then return 0; fi
    finish 12 MIGRATION_HOLD HELD "HOLD 상태입니다. migrate-continue 또는 migrate-rollback 이 필요합니다"
  fi
  healthy=$(py mig-journal "$R$DATA_DIR" has health "done" 2>/dev/null || echo no)
  if [ "$status" = HEALTHY ] || [ "$healthy" = yes ]; then
    # rule 4: hold 를 만들지 않고 M12/M13 재개. v22 가 기대 이미지로 돌고 canonical 이 v22 inode 여야 한다.
    obs=$(py mig-observe "$MIG_RUN" "$R$DATA_DIR" rule=4)
    : "$obs"
    [ -z "$hold" ] || [ "$hold" = "$MIG_RUN" ] || mig_unknown HOLD_OTHER_RUN
    current=$(py identity "$R$DATA_DIR/engine.db" 2>/dev/null) || mig_hold_stopped CANONICAL_MISSING
    [ "$(py ino-of "$current")" = "$(py ino-of "$(mig_receipt_field work_identity)")" ] || mig_hold_stopped NOT_V22_GENERATION
    read_container naver-engine && [ "$C_IMAGE" = "$MIG_NEW_ENGINE" ] && [ "$C_RUNNING" = true ] || mig_hold_stopped V22_NOT_RUNNING
    read_container naver-relay && [ "$C_IMAGE" = "$MIG_NEW_RELAY" ] && [ "$C_RUNNING" = true ] || mig_hold_stopped V22_NOT_RUNNING
    mig_units_match v22 || mig_hold_stopped V22_UNIT_GENERATION_MISMATCH
    py mig-status "$MIG_RUN" state=HEALTHY
    MIG_STAGE=healthy
    mig_finish_archive
    mig_complete COMPLETED
    finish 3 RECOVERED_INTERRUPTED_RUN MIGRATION_RESUMED "이관 마무리 재개·완료(엔진 정지 없음)"
  fi
  # rule 2: 원래 관측을 먼저 내구 기록 → 그다음에만 hold 생성
  obs=$(py mig-observe "$MIG_RUN" "$R$DATA_DIR" "hold_observed=${hold:-absent}" "dropins_observed=$dropins")
  log "관측 기록: $obs"
  started=no
  if py mig-journal "$R$DATA_DIR" has start-v22 intent 2>/dev/null | grep -q yes \
      || py mig-journal "$R$DATA_DIR" has start-v21 intent 2>/dev/null | grep -q yes; then
    started=yes
  fi
  py mig-hold create "$MIG_RUN" || mig_unknown HOLD_OTHER_RUN
  py mig-dropin install
  systemctl daemon-reload 2>>"$CMD_LOG" || true
  if [ "$started" = yes ]; then
    MIG_STAGE=started
    mig_auto_rollback INTERRUPTED_AFTER_START 1 3
  fi
  MIG_STAGE=chain
  mig_auto_rollback INTERRUPTED_BEFORE_START 0 3
}

# ════════════════════════════════════════════════════════════════════════════════════════════
# 고정 nginx 단계(nginx-plan / nginx-apply) — 이관과 따로(자체 plan_sha256·승인·되돌림). 보고 대조 업로드 두 경로만 4MiB.
# 쓰는 파일은 고정 두 개뿐이다(conf.d zone 파일 하나 + 관제 snippet 하나). 그 밖 /etc/nginx 지문이 같아야 한다.
# ════════════════════════════════════════════════════════════════════════════════════════════
NGINX_STEP=''
NGINX_STAGE=''
NGINX_CHECKS=''
NGINX_RUN_DIR=''
NGINX_TREE_BEFORE=''
NGINX_UPLOAD_TYPE='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

nginx_body() { # bytes → 그 크기의 0 바이트 파일 경로(비공개 run 폴더)
  local path="$NGINX_RUN_DIR/body-$1"
  [ -f "$path" ] || head -c "$1" /dev/zero > "$path"
  printf '%s' "$path"
}

nginx_probe() { # method path bytes → 상태 코드(실패는 000). 실제 nginx(443)에 같은 호스트 이름으로.
  local method=$1 path=$2 bytes=$3 code body
  if [ "$method" = GET ]; then
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 30 --resolve "$HOST_HEADER:443:127.0.0.1" \
      "https://$HOST_HEADER$path" 2>/dev/null) || code=000
  else
    body=$(nginx_body "$bytes")
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 60 --resolve "$HOST_HEADER:443:127.0.0.1" \
      -X POST -H "Content-Type: $NGINX_UPLOAD_TYPE" --data-binary "@$body" "https://$HOST_HEADER$path" 2>/dev/null) || code=000
  fi
  case "$code" in [0-9][0-9][0-9]) printf '%s' "$code" ;; *) printf '000' ;; esac
}

# 지금 설정이 「업로드 경로도 64KB 초과 거절 · 관제 화면 200」인지(적용 전 기준선이자 되돌림 뒤 확인).
nginx_baseline_ok() {
  local small over page path
  small=$(py nginx-field "$NGINX_STEP" small_bytes)
  over=$((small + 4096))
  page=$(nginx_probe GET /naver/ 0)
  NGINX_CHECKS="page=$page"
  [ "$page" = 200 ] || return 1
  for path in $(py nginx-paths "$NGINX_STEP"); do
    code=$(nginx_probe POST "$path" "$over")
    NGINX_CHECKS="$NGINX_CHECKS,base=$code"
    [ "$code" = 413 ] || return 1
  done
}

# 적용 뒤: 두 업로드 경로는 4MiB 아래를 받고(413·5xx·000 아님) 넘으면 413, 그 밖 관제 경로는 64KB 초과 413.
nginx_applied_ok() {
  local small big under above code path
  small=$(py nginx-field "$NGINX_STEP" small_bytes)
  big=$(py nginx-field "$NGINX_STEP" big_bytes)
  under=$((big - 4096)); above=$((big + 4096))
  NGINX_CHECKS=''
  for path in $(py nginx-paths "$NGINX_STEP"); do
    code=$(nginx_probe POST "$path" "$under")
    NGINX_CHECKS="${NGINX_CHECKS}${NGINX_CHECKS:+,}under=$code"
    case "$code" in 413|000|5??) return 1 ;; esac
    code=$(nginx_probe POST "$path" "$above")
    NGINX_CHECKS="$NGINX_CHECKS,above=$code"
    [ "$code" = 413 ] || return 1
  done
  for path in /api/naver-auto/me /api/naver-auto/reconcile/settlement/preview/x; do
    code=$(nginx_probe POST "$path" "$((small + 4096))")
    NGINX_CHECKS="$NGINX_CHECKS,other=$code"
    [ "$code" = 413 ] || return 1
  done
  code=$(nginx_probe GET /naver/ 0)
  NGINX_CHECKS="$NGINX_CHECKS,page=$code"
  [ "$code" = 200 ]
}

nginx_reload() {
  nginx -t >>"$CMD_LOG" 2>&1 || return 1
  nginx -s reload >>"$CMD_LOG" 2>&1 || return 1
  sleep "$POLL"
}

# 적용 중 실패: 백업 원문 복원 → nginx -t → reload → 기준선·전체 트리 지문 확인.
nginx_rollback() { # reason
  trap - ERR
  set +e
  log "nginx 되돌림: $1"
  if py nginx-restore "$NGINX_RUN_DIR" >>"$CMD_LOG" 2>&1 && nginx_reload && nginx_baseline_ok \
      && [ "$(py nginx-tree)" = "$NGINX_TREE_BEFORE" ]; then
    finish 2 NGINX_ROLLED_BACK "$1" "직전 nginx 설정 복원·검증 통과"
  fi
  finish 4 NGINX_ROLLBACK_FAILED "$1" "nginx 복원 실패. 사람 확인 필요"
}

nginx_fail() { # code detail — fail_deploy 가 부른다
  trap - ERR
  set +e
  log "nginx 단계 실패($1, 단계 ${NGINX_STAGE:-preflight}): $2"
  if [ "$NGINX_STAGE" = written ]; then
    nginx_rollback "$1"
  fi
  finish 10 REFUSED "$1" "nginx 설정은 건드리지 않았습니다"
}

nginx_common() { # commit tar step
  NEW=$1; M_TAR=$2; NGINX_STEP=$3
  printf '%s' "$NEW" | grep -Eq '^[0-9a-f]{40}$' || { NEW=''; die BAD_INPUT "커밋은 40자리 소문자 16진수여야 합니다"; }
  [ -f "$M_TAR" ] || die BAD_INPUT "source.tar 가 없습니다"
  printf '%s' "$NGINX_STEP" | grep -Eq '^[0-9a-z-]{1,40}$' || die BAD_INPUT "nginx 단계 이름 형식"
  if [ "$TEST_MODE" = 0 ] && [ "$(id -u)" != 0 ]; then die NOT_ROOT "root 로 실행해야 합니다"; fi
  command -v nginx >/dev/null || die MISSING_TOOL "nginx 명령이 없습니다"
  mig_lock
  if [ -n "$(py mig-pointer get)" ] || [ -n "$(py mig-hold get)" ] || [ "$(py mig-dropin present)" != no ]; then
    die MIGRATION_ACTIVE "이관 표지가 남아 있어 nginx 단계를 하지 않습니다"
  fi
  phase=$(py state-get "$STATE_FILE" phase 2>/dev/null) || phase=''
  if phase_needs_restore "$phase"; then die DEPLOY_NOT_FINISHED "끝나지 않은 배포가 있습니다"; fi
}

main_nginx_plan() {
  local out
  nginx_common "$@"
  out=$(py nginx-plan "$M_TAR" "$NGINX_STEP" "$NEW" "$R$STATE_DIR/nginx") || die NGINX_PLAN "$out"
  MIG_PLAN=${out%% *}
  PHASE=planned
  finish 0 NGINX_PLANNED '' "nginx plan_sha256=$MIG_PLAN (${out#* })"
}

main_nginx_apply() {
  local plan_in out
  plan_in=${4:-}
  nginx_common "$1" "$2" "$3"
  printf '%s' "$plan_in" | grep -Eq '^[0-9a-f]{64}$' || die BAD_INPUT "plan_sha256 형식"
  NGINX_RUN_DIR="$R$STATE_DIR/nginx/runs/$M_STAMP"
  mkdir -p "$NGINX_RUN_DIR"
  chmod 700 "$R$STATE_DIR/nginx" "$R$STATE_DIR/nginx/runs" "$NGINX_RUN_DIR"
  PHASE=preflight
  NGINX_TREE_BEFORE=$(py nginx-tree)
  out=$(py nginx-plan "$M_TAR" "$NGINX_STEP" "$NEW" "$R$STATE_DIR/nginx") || die NGINX_PLAN "$out"
  [ "${out%% *}" = "$plan_in" ] || die NGINX_PLAN_MISMATCH "다시 계산한 계획이 승인한 plan_sha256 과 다릅니다"
  MIG_PLAN=$plan_in
  if [ "${out#* }" = applied ]; then
    # 이미 적용된 상태: 바꾸지 않고 지금 동작만 확인한다.
    nginx_applied_ok || die NGINX_VERIFY "적용된 설정의 동작 확인 실패($NGINX_CHECKS)"
    finish 0 NGINX_ALREADY_APPLIED '' "이미 적용됨(무변경, $NGINX_CHECKS)"
  fi
  nginx_baseline_ok || die NGINX_BASELINE "적용 전 기준선이 예상(업로드 64KB 초과 413·화면 200)과 다릅니다($NGINX_CHECKS)"
  NGINX_STAGE=writing
  out=$(py nginx-write "$M_TAR" "$NGINX_STEP" "$NEW" "$plan_in" "$NGINX_RUN_DIR") || die NGINX_PLAN_MISMATCH "$out"
  MIG_PLAN=$plan_in
  if [ "$out" = already-applied ]; then
    finish 0 NGINX_ALREADY_APPLIED '' "이미 적용됨(무변경)"
  fi
  NGINX_STAGE=written
  PHASE=applying
  nginx_reload || nginx_rollback NGINX_TEST_OR_RELOAD
  py nginx-verify-files "$NGINX_RUN_DIR" >>"$CMD_LOG" 2>&1 || nginx_rollback NGINX_FILES
  nginx_applied_ok || nginx_rollback "NGINX_VERIFY"
  NGINX_STAGE='done'
  PHASE='done'
  finish 0 NGINX_APPLIED '' "nginx 고정 단계 적용($NGINX_CHECKS)"
}

# ── 입구 ────────────────────────────────────────────────────────────────────
case "$MODE" in
  inspect)
    [ "$#" = 1 ] || { echo "사용: $0 inspect" >&2; exit 64; }
    main_inspect
    ;;
  app-inventory)
    [ "$#" = 1 ] || { echo "사용: $0 app-inventory" >&2; exit 64; }
    python3 -I -B "$(dirname -- "${BASH_SOURCE[0]}")/app_inventory.py"
    ;;
  cleanup-plan)
    [ "$#" = 1 ] || { echo "사용: $0 cleanup-plan" >&2; exit 64; }
    py cleanup-plan
    ;;
  disk-usage)
    # 읽기 전용 사용처 분석. 잠금을 잡지 않고 아무것도 바꾸지 않는다.
    [ "$#" = 1 ] || { echo "사용: $0 disk-usage" >&2; exit 64; }
    py disk-usage
    ;;
  cleanup)
    [ "$#" = 2 ] || { echo "사용: $0 cleanup <allowlist_sha256>" >&2; exit 64; }
    main_cleanup "$2"
    ;;
  cleanup-artifacts-plan)
    [ "$#" = 1 ] || { echo "사용: $0 cleanup-artifacts-plan" >&2; exit 64; }
    py cleanup-artifacts-plan
    ;;
  cleanup-artifacts)
    [ "$#" = 2 ] || { echo "사용: $0 cleanup-artifacts <allowlist_sha256>" >&2; exit 64; }
    main_cleanup_artifacts "$2"
    ;;
  migrate-prepare|migrate-rehearse|migrate-plan|migrate-deploy|migrate-continue|migrate-rollback|migrate-accept|nginx-plan|nginx-apply)
    shift
    case "$MODE" in
      migrate-deploy|nginx-apply) want=4 ;;
      migrate-continue|migrate-rollback|migrate-accept) want=1 ;;
      *) want=3 ;;
    esac
    [ "$#" -ge "$want" ] || { echo "사용: $0 $MODE <인자 $want 개> [--log FILE] [--result FILE]" >&2; exit 64; }
    M_ARGS=()
    while [ "${#M_ARGS[@]}" -lt "$want" ]; do M_ARGS+=("$1"); shift; done
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
    log "naver-deploy $MODE 시작"
    for f in docker systemctl curl python3 flock; do
      command -v "$f" >/dev/null || die MISSING_TOOL "$f 명령이 없습니다"
    done
    case "$MODE" in
      migrate-prepare) main_migrate_prepare "${M_ARGS[@]}" ;;
      migrate-rehearse) main_migrate_rehearse "${M_ARGS[@]}" ;;
      migrate-plan) main_migrate_plan "${M_ARGS[@]}" ;;
      migrate-deploy) main_migrate_deploy "${M_ARGS[@]}" ;;
      migrate-continue) main_migrate_continue "${M_ARGS[@]}" ;;
      migrate-rollback) main_migrate_rollback "${M_ARGS[@]}" ;;
      migrate-accept) main_migrate_accept "${M_ARGS[@]}" ;;
      nginx-plan) main_nginx_plan "${M_ARGS[@]}" ;;
      nginx-apply) main_nginx_apply "${M_ARGS[@]}" ;;
    esac
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
    echo "사용: $0 inspect | disk-usage | app-inventory | cleanup-plan | cleanup <allowlist_sha256> | cleanup-artifacts-plan | cleanup-artifacts <allowlist_sha256> | deploy <commit> <source.tar> [--log FILE] [--result FILE] | migrate-prepare|migrate-rehearse|migrate-plan <commit> <source.tar> <migration_id> | migrate-deploy <commit> <source.tar> <migration_id> <plan_sha256> | migrate-continue|migrate-rollback|migrate-accept <run> | nginx-plan <commit> <source.tar> <step> | nginx-apply <commit> <source.tar> <step> <plan_sha256>" >&2
    exit 64
    ;;
esac
