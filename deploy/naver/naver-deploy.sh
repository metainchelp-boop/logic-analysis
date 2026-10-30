#!/usr/bin/env bash
# 네이버 관제(engine + relay) 단순 배포 — 서버(VPS)에서 root 로 실행한다.
#
#   naver-deploy.sh inspect
#       읽기 전용. 서비스·이미지·폴더 상태를 한 줄 JSON 으로 출력한다(무엇도 바꾸지 않는다).
#   naver-deploy.sh deploy <제품 커밋 40자리> <source.tar> [--log FILE] [--result FILE]
#       시험을 통과한 정확한 커밋을 배포한다. 실패하면 직전 판으로 자동 복원한다.
#
# 지키는 것(docs/naver-simple-deploy.md 와 같은 목록):
#   - 이미지 두 개를 커밋 태그로 먼저 빌드한 뒤에만 서비스를 멈춘다.
#   - 직전 이미지 ID·unit 파일·override 파일을 서버의 복구 기록에 먼저 남긴다
#     (SSH 가 끊기거나 서버가 재부팅돼도 다음 실행이 그 기록으로 복원한다).
#   - 정지는 relay → engine(PID 0 확인), 시작은 engine → relay.
#   - engine.db* 는 제자리 보존. 엔진이 멈춘 동안에만 파일 복사(최근 3벌).
#     sqlite 로 DB 를 열지 않는다.
#   - runtime.env, nginx, ERP 터널 unit, 다른 앱, saved-exports companion 은 건드리지 않는다.
#   - execution_enabled 는 false 여야 한다.
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


def check_config():
    raw = sys.stdin.read().strip().splitlines()
    if not raw:
        fail('check-config 출력이 없습니다')
    try:
        value = json.loads(raw[-1])
    except ValueError:
        fail('check-config 출력이 JSON 이 아닙니다')
    if (not isinstance(value, dict) or value.get('command') != 'check-config' or value.get('configuration') != 'valid'
            or value.get('storage_opened') is not False or value.get('network_performed') is not False
            or not isinstance(value.get('switches'), dict)):
        fail('check-config 결과가 예상과 다릅니다')
    execution = value['switches'].get('execution')
    if execution is not False:
        fail('EXECUTION_ENABLED: 새 판의 execution 스위치가 false 가 아닙니다(%r)' % (execution,))
    print('inventory=%s execution=false' % str(value['switches'].get('inventory')).lower())


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


def result_json(*pairs):
    data, extra = {}, {}
    for pair in pairs:
        key, _, value = pair.partition('=')
        if key.startswith('json:'):
            try:
                extra[key[5:]] = json.loads(value) if value else None
            except ValueError:
                extra[key[5:]] = value
        elif key == 'exit_code':
            data[key] = int(value)
        else:
            data[key] = value
    data.update(extra)
    print(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


# ── inspect: 읽기 전용 명령만 실행한다 ───────────────────────────────────────
def run(argv, limit=20000):
    try:
        done = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except Exception as error:
        return {'rc': None, 'error': type(error).__name__}
    result = {'rc': done.returncode, 'out': done.stdout.decode('utf-8', 'replace')[-limit:]}
    if done.returncode:
        result['err'] = done.stderr.decode('utf-8', 'replace')[-2000:]
    return result


def show(unit):
    fields = 'Id,ActiveState,SubState,MainPID,UnitFileState,NRestarts,FragmentPath,DropInPaths,ExecMainStartTimestamp,NeedDaemonReload'
    done = run(['systemctl', 'show', unit, '-p', fields])
    if done.get('rc') != 0:
        return done
    return dict(line.split('=', 1) for line in done['out'].splitlines() if '=' in line)


def text_file(path):
    try:
        return read(ROOT + path)
    except Exception as error:
        return {'error': type(error).__name__}


def json_file(path):
    try:
        return json.loads(read(ROOT + path))
    except FileNotFoundError:
        return None
    except Exception as error:
        return {'error': type(error).__name__}


def container_rows(project):
    ids = run(['docker', 'ps', '--all', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + project,
               '--format', '{{.ID}}'])
    rows = []
    for identity in (ids.get('out') or '').split():
        done = run(['docker', 'inspect', identity], limit=10 ** 7)
        try:
            row = json.loads(done['out'])[0]
        except Exception:
            rows.append({'id': identity, 'error': 'inspect'})
            continue
        state, config = row.get('State') or {}, row.get('Config') or {}
        rows.append({'id': row.get('Id'), 'name': row.get('Name'), 'image': row.get('Image'),
                     'config_image': config.get('Image'), 'user': config.get('User'),
                     'status': state.get('Status'), 'running': state.get('Running'), 'pid': state.get('Pid'),
                     'started_at': state.get('StartedAt'), 'restart_count': row.get('RestartCount'),
                     'labels': config.get('Labels') or {},
                     'restart_policy': (row.get('HostConfig') or {}).get('RestartPolicy'),
                     'network_mode': (row.get('HostConfig') or {}).get('NetworkMode'),
                     'mounts': [{'type': m.get('Type'), 'source': m.get('Source'), 'destination': m.get('Destination'),
                                 'rw': m.get('RW')} for m in row.get('Mounts') or []],
                     # Env 값은 내보내지 않는다. 두 스위치의 참/거짓만 낸다.
                     'execution_enabled': env_flag(config.get('Env'), 'NAVER_ENGINE_EXECUTION_ENABLED'),
                     'inventory_enabled': env_flag(config.get('Env'), 'NAVER_ENGINE_INVENTORY_ENABLED')})
    return {'ids': ids, 'containers': rows}


def inspect():
    out = {'mode': 'inspect', 'read_only': True,
           'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    out['id'] = run(['id'])
    out['df'] = run(['df', '-h'])
    out['tools'] = {'python': sys.version.split()[0],
                    'docker': run(['docker', 'version', '--format', '{{.Server.Version}}']),
                    'compose': run(['docker', 'compose', 'version', '--short']),
                    'systemd': run(['systemctl', '--version'], limit=200),
                    'curl': bool(shutil.which('curl')), 'flock': bool(shutil.which('flock')),
                    'systemd_run': bool(shutil.which('systemd-run'))}
    units = {}
    for unit in ('metainc-naver-engine.service', 'metainc-naver-relay.service', 'metainc-naver-erp-tunnel.service'):
        units[unit] = {'cat': run(['systemctl', 'cat', unit]), 'show': show(unit)}
    units['docker.service'] = {'show': show('docker.service')}
    out['units'] = units
    out['tmpfiles_conf'] = text_file('/etc/tmpfiles.d/metainc-naver-preview.conf')
    layout, commit = {}, None
    for name in ('engine', 'relay'):
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                unit_parse(ROOT + '/etc/systemd/system/metainc-naver-' + name + '.service', name)
            found, companion = captured.getvalue().split()
            layout[name] = {'ok': True, 'commit': found, 'companion': None if companion == '-' else companion}
            commit = commit or found
        except Exception as error:
            layout[name] = {'ok': False, 'reason': str(error)[-500:] or type(error).__name__}
    if layout.get('engine', {}).get('ok') and layout.get('relay', {}).get('ok') \
            and layout['engine']['commit'] != layout['relay']['commit']:
        layout['same_commit'] = False
    out['layout'] = layout
    try:
        out['releases'] = sorted(os.listdir(ROOT + RELEASES))
    except Exception as error:
        out['releases'] = {'error': type(error).__name__}
    if commit:
        release = RELEASES + '/naver-' + commit
        out['current_release'] = {'path': release, 'ls': run(['ls', '-la', ROOT + release]),
                                  'overrides': {name: text_file(release + '/' + name) for name in OVERRIDES}}
        try:
            out['current_release']['schema_version'] = schema_of(read(ROOT + release + '/naver_engine/store.py'))
        except BaseException as error:
            out['current_release']['schema_version'] = {'error': type(error).__name__}
        image = run(['docker', 'image', 'inspect', 'metainc/naver-engine:' + commit], limit=10 ** 7)
        try:
            row = json.loads(image['out'])[0]
            out['current_release']['engine_image'] = {'id': row.get('Id'), 'labels': (row.get('Config') or {}).get('Labels')}
        except Exception:
            out['current_release']['engine_image'] = image
    images = run(['docker', 'image', 'ls', '--no-trunc', '--filter', 'reference=metainc/naver-*', '--format', '{{json .}}'])
    try:
        out['images'] = [json.loads(line) for line in images['out'].splitlines() if line.strip()]
    except Exception:
        out['images'] = images
    out['containers'] = {project: container_rows(project) for project in ('naver-engine', 'naver-relay')}
    out['data_dir_ls'] = run(['ls', '-la', ROOT + '/var/lib/metainc/naver-engine'])
    out['db_backups_ls'] = run(['ls', '-la', ROOT + '/var/backups/metainc/naver-deploy-db'])
    out['deploy_state'] = {'state': json_file('/var/lib/metainc/naver-deploy/state.json'),
                           'current': json_file('/var/lib/metainc/naver-deploy/current.json'),
                           'history': json_file('/var/lib/metainc/naver-deploy/history.json')}
    print('NAVER_DEPLOY_INSPECT=' + json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


COMMANDS = {'unit-parse': unit_parse, 'override-check': override_check, 'subst': subst, 'tar-check': tar_check,
            'tar-extract': tar_extract, 'tree-compare': tree_compare, 'image-info': image_info,
            'container-info': container_info, 'check-config': check_config, 'state-write': state_write,
            'state-get': state_get, 'history-add': history_add, 'prune-list': prune_list,
            'prune-history': prune_history, 'db-files': db_files, 'same-size': same_size,
            'backup-prune': backup_prune, 'sha': sha, 'tree-sha': tree_sha, 'result-json': result_json,
            'inspect': inspect,
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
MODE="${1:-}"
LOG_FILE=''
RESULT_FILE=''
RESULT_CODE=''
RESULT_STATUS=''
RESULT_MESSAGE=''
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
HEALTH_DETAIL=''
STATE_FILE="$R$STATE_DIR/state.json"
HAVE_STATE=0
RESTORING=0

warn() { log "주의: $*"; WARNINGS="${WARNINGS}${WARNINGS:+; }$*"; }

write_result() {
  local line
  line=$(py result-json "mode=$MODE" "status=${RESULT_STATUS:-UNKNOWN}" "exit_code=${RESULT_CODE:-1}" \
    "message=$RESULT_MESSAGE" "phase=$PHASE" "new_commit=$NEW" "previous_commit=$PREV_COMMIT" \
    "new_engine_image=$NEW_ENGINE_IMAGE" "new_relay_image=$NEW_RELAY_IMAGE" \
    "previous_engine_image=$PREV_ENGINE_IMAGE" "previous_relay_image=$PREV_RELAY_IMAGE" \
    "db_backup=$DB_BACKUP" "downtime_seconds=$DOWNTIME" "health=$HEALTH_DETAIL" "warnings=$WARNINGS" \
    "database_opened_by_deploy=false" "runtime_env_changed_by_deploy=false" 2>/dev/null) || line='{"status":"RESULT_WRITE_FAILED"}'
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

finish() { # code status message
  RESULT_CODE=$1
  RESULT_STATUS=$2
  RESULT_MESSAGE=$3
  log "결과: $2 — $3"
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
fail_deploy() { # code message
  trap - ERR
  set +e
  if [ "$RESTORING" = 1 ]; then
    finish 4 RESTORE_FAILED "$2"
  fi
  if [ "$PHASE" = done ]; then
    # 새 판은 이미 헬스를 통과했다. 기록·이미지 정리 같은 마무리 실패는 경고로만 남긴다.
    warn "마무리 정리 중 실패($1): $2"
    finish 0 DEPLOYED "배포 완료(헬스 통과) · 마무리 경고: $1"
  fi
  if [ "$HAVE_STATE" = 1 ] && phase_needs_restore "$PHASE"; then
    log "배포 실패($1): $2 — 직전 판 $PREV_COMMIT 으로 복원합니다"
    if restore_previous; then
      finish 2 DEPLOY_FAILED_RESTORED "$1: $2 · 직전 판 $PREV_COMMIT 복원·헬스 통과"
    fi
    finish 4 RESTORE_FAILED "$1: $2 · 복원도 실패해 두 서비스를 정지했습니다. 사람 확인 필요"
  fi
  if [ "$HAVE_STATE" = 1 ]; then
    py state-write "$STATE_FILE" "phase=aborted_before_stop" "reason=$1" || true
    PHASE=aborted_before_stop
  fi
  finish 10 REFUSED "$1: $2 (서비스는 건드리지 않았습니다)"
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
    HEALTH_DETAIL="$project 컨테이너 수가 $# 입니다(1이어야 함)"
    return 1
  fi
  info=$(dk inspect "$1" | py container-info) || return 1
  IFS='|' read -r C_ID C_IMAGE C_RUNNING _ _ C_STARTED C_RESTARTS C_PROJECT C_SERVICE C_EXEC C_USER <<EOF
$info
EOF
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

stop_and_wait() { # unit project
  local deadline state pid
  log "정지: $1"
  systemctl stop "$1" || return 1
  deadline=$((SECONDS + ${STOP_TIMEOUT%.*}))
  while :; do
    state=$(unit_prop "$1" ActiveState) || state=unknown
    pid=$(unit_prop "$1" MainPID) || pid=unknown
    if { [ "$state" = inactive ] || [ "$state" = failed ]; } && [ "$pid" = 0 ] && project_stopped "$2"; then
      log "정지 확인: $1 (MainPID 0, 컨테이너 PID 0)"
      return 0
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      log "정지 확인 실패: $1 state=$state MainPID=$pid"
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
  printf '%s' "${code:-000}"
}

probe_once() {
  P_ENGINE=$(http_code "$ENGINE_SOCK" /_engine/health)
  P_PAGE=$(http_code "$RELAY_SOCK" /naver/)
  P_ME=$(http_code "$RELAY_SOCK" /api/naver-auto/me)
  [ "$P_ENGINE" = 200 ] && [ "$P_PAGE" = 200 ] && [ "$P_ME" = 401 ]
}

# 헬스체크: 준비(시간 제한) → 60초 유지(unit active, RestartCount 0, StartedAt 불변) → 마지막 확인.
health_check() { # engine_image relay_image
  local deadline e_id e_start e_pid e_nr r_id r_start r_pid r_nr end
  HEALTH_DETAIL=''
  deadline=$((SECONDS + ${READY_TIMEOUT%.*}))
  until probe_once; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      HEALTH_DETAIL="준비 시간 초과: engine=$P_ENGINE page=$P_PAGE me=$P_ME"
      log "헬스 실패: $HEALTH_DETAIL"
      return 1
    fi
    sleep "$POLL"
  done
  if [ -n "$STOP_STARTED" ] && [ -z "$DOWNTIME" ]; then
    DOWNTIME=$((SECONDS - STOP_STARTED))
  fi
  log "헬스 준비: engine=$P_ENGINE page=$P_PAGE me=$P_ME"
  read_container naver-engine || { HEALTH_DETAIL="engine 컨테이너 확인 실패 ${HEALTH_DETAIL}"; return 1; }
  if [ "$C_IMAGE" != "$1" ] || [ "$C_RUNNING" != true ] || [ "$C_RESTARTS" != 0 ]; then
    HEALTH_DETAIL="engine 컨테이너 상태 이상(image=$C_IMAGE running=$C_RUNNING restarts=$C_RESTARTS)"
    log "헬스 실패: $HEALTH_DETAIL"
    return 1
  fi
  e_id=$C_ID; e_start=$C_STARTED
  read_container naver-relay || { HEALTH_DETAIL="relay 컨테이너 확인 실패 ${HEALTH_DETAIL}"; return 1; }
  if [ "$C_IMAGE" != "$2" ] || [ "$C_RUNNING" != true ] || [ "$C_RESTARTS" != 0 ]; then
    HEALTH_DETAIL="relay 컨테이너 상태 이상(image=$C_IMAGE running=$C_RUNNING restarts=$C_RESTARTS)"
    log "헬스 실패: $HEALTH_DETAIL"
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
      HEALTH_DETAIL="유지 중 unit 이 active 가 아니거나 재시작됨"
      log "헬스 실패: $HEALTH_DETAIL"
      return 1
    fi
    read_container naver-engine || { HEALTH_DETAIL="유지 중 engine 확인 실패"; return 1; }
    if [ "$C_ID" != "$e_id" ] || [ "$C_STARTED" != "$e_start" ] || [ "$C_RESTARTS" != 0 ] || [ "$C_RUNNING" != true ]; then
      HEALTH_DETAIL="유지 중 engine 재시작 감지(StartedAt $e_start → $C_STARTED, RestartCount $C_RESTARTS)"
      log "헬스 실패: $HEALTH_DETAIL"
      return 1
    fi
    read_container naver-relay || { HEALTH_DETAIL="유지 중 relay 확인 실패"; return 1; }
    if [ "$C_ID" != "$r_id" ] || [ "$C_STARTED" != "$r_start" ] || [ "$C_RESTARTS" != 0 ] || [ "$C_RUNNING" != true ]; then
      HEALTH_DETAIL="유지 중 relay 재시작 감지(StartedAt $r_start → $C_STARTED, RestartCount $C_RESTARTS)"
      log "헬스 실패: $HEALTH_DETAIL"
      return 1
    fi
  done
  if ! probe_once; then
    HEALTH_DETAIL="유지 후 확인 실패: engine=$P_ENGINE page=$P_PAGE me=$P_ME"
    log "헬스 실패: $HEALTH_DETAIL"
    return 1
  fi
  HEALTH_DETAIL="engine=200 page=200 me=401 hold=${HOLD_SECONDS}s restarts=0"
  log "헬스 통과: $HEALTH_DETAIL"
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
  S_RUN_DIR=$(py state-get "$STATE_FILE" run_dir)
  S_COMPANION=$(py state-get "$STATE_FILE" companion)
  S_PREV_REL="$RELEASES/naver-$PREV_COMMIT"
}

# ── 복원: 기록(state.json + run 폴더 사본)만으로 직전 판을 되살린다 ───────────────
restore_previous() {
  local name unit saved target image ok=1
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
      if ! dk image inspect "$image" >/dev/null; then
        log "직전 이미지가 없습니다: $image"
        ok=0
      else
        dk tag "$image" "metainc/naver-$name:$PREV_COMMIT" || ok=0
      fi
    done
  fi
  if [ "$ok" = 1 ]; then
    systemctl daemon-reload || ok=0
  fi
  if [ "$ok" = 1 ]; then
    for name in engine relay; do
      compose_args "$name" "$S_PREV_REL" "$S_COMPANION"
      dk "${CARGS[@]}" up --no-start --no-build --force-recreate || { ok=0; break; }
    done
  fi
  if [ "$ok" = 1 ]; then
    read_container naver-engine && [ "$C_IMAGE" = "$PREV_ENGINE_IMAGE" ] || ok=0
    read_container naver-relay && [ "$C_IMAGE" = "$PREV_RELAY_IMAGE" ] || ok=0
  fi
  if [ "$ok" = 1 ]; then
    systemctl start "$ENGINE_UNIT" || ok=0
  fi
  if [ "$ok" = 1 ]; then
    systemctl start "$RELAY_UNIT" || ok=0
  fi
  if [ "$ok" = 1 ] && health_check "$PREV_ENGINE_IMAGE" "$PREV_RELAY_IMAGE"; then
    PHASE=restored
    py state-write "$STATE_FILE" "phase=restored" "restored_at_health=$HEALTH_DETAIL"
    log "== 복원 완료: $PREV_COMMIT 헬스 통과"
    RESTORING=0
    return 0
  fi
  log "== 복원 실패: 두 서비스를 정지합니다(엔진이 잘못된 판으로 계속 쓰지 않게)"
  systemctl stop "$RELAY_UNIT"
  systemctl stop "$ENGINE_UNIT"
  PHASE=restore_failed
  py state-write "$STATE_FILE" "phase=restore_failed"
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
      finish 3 RECOVERED_INTERRUPTED_RUN "중단된 이전 배포를 직전 판 $PREV_COMMIT 으로 복원했습니다. 다시 실행하세요"
    fi
    finish 4 RESTORE_FAILED "중단된 이전 배포의 복원에 실패해 두 서비스를 정지했습니다. 사람 확인 필요"
  fi
  case "$phase" in
    preparing|prepared)
      log "이전 실행이 서비스를 멈추기 전($phase)에 끝났습니다 — 바뀐 것이 없어 계속합니다"
      py state-write "$STATE_FILE" "phase=aborted_before_stop"
      ;;
  esac
}

# ── inspect ─────────────────────────────────────────────────────────────────
main_inspect() {
  py inspect
}

# ── deploy ──────────────────────────────────────────────────────────────────
main_deploy() {
  local tar_path cur cur_r companion schema_new schema_cur name info id user src label unit
  local rel_new rel_cur run_dir stamp sum_runtime sum_tmpfiles sum_tunnel sum_nginx size files f
  local free_kb need_kb override cid check flags
  NEW=${1:-}
  tar_path=${2:-}
  printf '%s' "$NEW" | grep -Eq '^[0-9a-f]{40}$' || die BAD_INPUT "커밋은 40자리 소문자 16진수여야 합니다"
  [ -f "$tar_path" ] || die BAD_INPUT "source.tar 가 없습니다: $tar_path"
  for f in docker systemctl curl python3 flock; do
    command -v "$f" >/dev/null || die MISSING_TOOL "$f 명령이 없습니다"
  done
  if [ "$TEST_MODE" = 0 ] && [ "$(id -u)" != 0 ]; then
    die NOT_ROOT "deploy 는 root 로 실행해야 합니다(unit·docker·root 전용 폴더)"
  fi
  [ -d "$R/var/lib/metainc" ] || die LAYOUT "/var/lib/metainc 가 없습니다"
  mkdir -p "$R$STATE_DIR/runs"
  chmod 700 "$R$STATE_DIR"

  # 직렬화: 같은 서버에서 두 배포가 겹치지 않게.
  exec 9>>"$R$STATE_DIR/lock"
  if ! flock -n 9; then
    RESULT_CODE=11
    RESULT_STATUS=LOCKED
    RESULT_MESSAGE="다른 naver-deploy 가 실행 중입니다"
    log "결과: LOCKED — $RESULT_MESSAGE"
    exit 11
  fi
  log "잠금 획득: $STATE_DIR/lock"

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
    info=$(dk image inspect "metainc/naver-$name:$cur" | py image-info) || die LAYOUT "현재 이미지 metainc/naver-$name:$cur 정보를 읽지 못했습니다"
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
      [ "$C_EXEC" = false ] || die EXECUTION_ENABLED "실행 중 엔진의 execution 스위치가 false 가 아닙니다($C_EXEC)"
    else
      PREV_RELAY_IMAGE=$id
    fi
  done
  log "현재 판 $cur (engine $PREV_ENGINE_IMAGE, relay $PREV_RELAY_IMAGE, companion $companion)"

  # ── 2. 원본 묶음과 스키마(엔진 DB 를 열지 않고 소스로 비교) ──
  schema_new=$(py tar-check "$tar_path") || die ARCHIVE "$schema_new"
  info=$(dk image inspect "$PREV_ENGINE_IMAGE" | py image-info) || die LAYOUT "실행 중 engine 이미지 정보를 읽지 못했습니다"
  read -r id user src label <<EOF
$info
EOF
  if printf '%s' "$label" | grep -Eq '^[0-9]+$'; then
    schema_cur=$label
    log "현재 스키마(이미지 라벨): $schema_cur"
  else
    # 라벨 없는 옛 이미지: 컨테이너를 시작하지 않고(create) 이미지 안의 store.py 만 복사해 읽는다.
    cid=$(dk create --network none "$PREV_ENGINE_IMAGE")
    schema_cur=$(dk cp "$cid:/opt/naver-engine/naver_engine/store.py" - | py schema-tar-stdin) || schema_cur=''
    dk rm "$cid" >/dev/null || warn "임시 컨테이너 $cid 삭제 실패"
    [ -n "$schema_cur" ] || die SCHEMA_UNKNOWN "실행 중 이미지의 SCHEMA_VERSION 을 읽지 못했습니다"
    log "현재 스키마(이미지 안 store.py): $schema_cur"
  fi
  if [ "$schema_new" != "$schema_cur" ]; then
    die SCHEMA_CHANGED "SCHEMA_VERSION 이 $schema_cur → $schema_new 로 바뀝니다. 스키마 이관은 이 배포 장치에서 하지 않습니다"
  fi
  log "스키마 동일: $schema_new"

  # ── 3. 복구 기록 시작(서비스를 멈추기 전) ──
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  run_dir="$STATE_DIR/runs/$stamp-$(printf '%s' "$NEW" | cut -c1-12)"
  mkdir "$R$run_dir"
  for name in engine relay; do
    cp "$R$UNIT_DIR/metainc-naver-$name.service" "$R$run_dir/metainc-naver-$name.service"
    cp "$cur_r/preview-$name.override.yml" "$R$run_dir/preview-$name.override.yml"
  done
  rm -f "$STATE_FILE"
  HAVE_STATE=1
  py state-write "$STATE_FILE" "phase=preparing" "new_commit=$NEW" "prev_commit=$cur" \
    "prev_engine_image=$PREV_ENGINE_IMAGE" "prev_relay_image=$PREV_RELAY_IMAGE" "run_dir=$run_dir" \
    "companion=$companion" "schema=$schema_new" "started_at=$stamp"
  PHASE=preparing
  log "복구 기록: $run_dir (unit·override 사본, 직전 이미지 ID)"

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

  # ── 5. 빌드(서비스를 멈추기 전) ──
  set_phase building
  for name in engine relay; do
    log "빌드: metainc/naver-$name:$NEW"
    dk build --quiet --label "metainc.naver.preview.source=$NEW" --label "metainc.naver.schema=$schema_new" \
      -t "metainc/naver-$name:$NEW" -f "$R$rel_new/Dockerfile.naver-$name" "$R$rel_new" >/dev/null \
      || die BUILD_FAILED "metainc/naver-$name:$NEW 빌드 실패"
    info=$(dk image inspect "metainc/naver-$name:$NEW" | py image-info)
    read -r id user src label <<EOF
$info
EOF
    [ "$src" = "$NEW" ] && [ "$user" = 10001:10001 ] || die BUILD_FAILED "새 이미지 라벨/사용자 이상($src, $user)"
    if [ "$name" = engine ]; then NEW_ENGINE_IMAGE=$id; else NEW_RELAY_IMAGE=$id; fi
    compose_args "$name" "$rel_new" "$companion"
    dk "${CARGS[@]}" config --quiet || die COMPOSE_CONFIG "새 $name compose 설정이 유효하지 않습니다"
  done
  [ "$NEW_ENGINE_IMAGE" != "$PREV_ENGINE_IMAGE" ] || warn "새 engine 이미지 ID 가 직전과 같습니다"
  py state-write "$STATE_FILE" "new_engine_image=$NEW_ENGINE_IMAGE" "new_relay_image=$NEW_RELAY_IMAGE"

  # 새 이미지·실제 runtime.env 로 check-config(네트워크 없음, 별도 project, DB 미개방).
  printf 'services:\n  naver-engine:\n    network_mode: none\n' > "$R$run_dir/check-config.override.yml"
  compose_args engine "$rel_new" "$companion"
  CARGS[2]="naver-check-$(printf '%s' "$NEW" | cut -c1-12)-$(py randhex)"
  check=$(dk "${CARGS[@]}" -f "$R$run_dir/check-config.override.yml" run --rm --no-deps --pull never \
    naver-engine python -B -m naver_runtime check-config) || die CHECK_CONFIG "새 판 check-config 실패"
  flags=$(printf '%s\n' "$check" | py check-config) || die EXECUTION_ENABLED "$flags"
  log "check-config: $flags"

  # 디스크: DB cold copy 공간(+256MB) 이 없으면 멈추기 전에 거부.
  info=$(py db-files "$R$DATA_DIR") || die DB_FILES "$info"
  size=${info%% *}
  [ -d "$R$DB_BACKUP_PARENT" ] || die LAYOUT "$DB_BACKUP_PARENT 가 없습니다"
  free_kb=$(df -Pk "$R$DB_BACKUP_PARENT" | awk 'NR==2 {print $4}')
  need_kb=$((size / 1024 + 262144))
  [ "$free_kb" -ge "$need_kb" ] || die DISK "DB 복사 공간 부족(필요 ${need_kb}KB, 여유 ${free_kb}KB)"

  # 변하지 않아야 할 것들의 지문(값은 출력하지 않는다).
  sum_runtime=$(py sha "$R$RUNTIME_ENV" 2>/dev/null || echo absent)
  sum_tmpfiles=$(py sha "$R$TMPFILES_CONF")
  sum_tunnel=$(py sha "$R$UNIT_DIR/$TUNNEL_UNIT" 2>/dev/null || echo absent)
  sum_nginx=$(py tree-sha "$R$NGINX_DIR")

  # 멈추기 직전 재확인: unit 이 기록한 사본과 같고 컨테이너가 그대로인지.
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
  [ "$(unit_prop "$ENGINE_UNIT" MainPID)" = 0 ] && project_stopped naver-engine || die DB_COPY "엔진이 멈춰 있지 않아 복사하지 않습니다"
  mkdir -p "$R$DB_BACKUPS"
  chmod 700 "$R$DB_BACKUPS"
  DB_BACKUP="$DB_BACKUPS/$stamp-$(printf '%s' "$cur" | cut -c1-12)"
  mkdir "$R$DB_BACKUP"
  files=$(py db-files "$R$DATA_DIR")
  for f in ${files#* }; do
    cp -p "$R$DATA_DIR/$f" "$R$DB_BACKUP/$f"
    py same-size "$R$DATA_DIR/$f" "$R$DB_BACKUP/$f"
  done
  log "DB 파일 복사(정지 상태): $DB_BACKUP (${files#* })"
  while read -r f; do
    [ -z "$f" ] || log "오래된 DB 사본 정리: $f"
  done < <(py backup-prune "$R$DB_BACKUPS" 3 || warn "오래된 DB 사본 정리 실패")

  # ── 8. unit 교체(커밋만 치환, 치환 개수 단언) → daemon-reload → 컨테이너 생성 ──
  set_phase switching
  py subst "$R$run_dir/$ENGINE_UNIT" "$R$run_dir/new-$ENGINE_UNIT" "$cur" "$NEW" 6
  py subst "$R$run_dir/$RELAY_UNIT" "$R$run_dir/new-$RELAY_UNIT" "$cur" "$NEW" 4
  write_file_atomic "$R$run_dir/new-$ENGINE_UNIT" "$R$UNIT_DIR/$ENGINE_UNIT" 644
  write_file_atomic "$R$run_dir/new-$RELAY_UNIT" "$R$UNIT_DIR/$RELAY_UNIT" 644
  sync
  systemctl daemon-reload
  for unit in "$ENGINE_UNIT" "$RELAY_UNIT"; do
    [ "$(unit_prop "$unit" NeedDaemonReload)" = no ] || die SWITCH "$unit daemon-reload 반영 안 됨"
  done
  for name in engine relay; do
    compose_args "$name" "$rel_new" "$companion"
    dk "${CARGS[@]}" up --no-start --no-build --force-recreate
  done
  read_container naver-engine || die SWITCH "새 engine 컨테이너 확인 실패"
  [ "$C_IMAGE" = "$NEW_ENGINE_IMAGE" ] && [ "$C_RUNNING" = false ] || die SWITCH "새 engine 컨테이너 상태 이상"
  [ "$C_EXEC" = false ] || die EXECUTION_ENABLED "새 engine 컨테이너 execution 스위치가 false 가 아닙니다($C_EXEC)"
  read_container naver-relay || die SWITCH "새 relay 컨테이너 확인 실패"
  [ "$C_IMAGE" = "$NEW_RELAY_IMAGE" ] && [ "$C_RUNNING" = false ] || die SWITCH "새 relay 컨테이너 상태 이상"

  # ── 9. 시작: engine → relay ──
  set_phase starting
  log "시작: $ENGINE_UNIT"
  systemctl start "$ENGINE_UNIT"
  log "시작: $RELAY_UNIT"
  systemctl start "$RELAY_UNIT"

  # ── 10. 헬스 + 60초 유지 ──
  set_phase verifying
  health_check "$NEW_ENGINE_IMAGE" "$NEW_RELAY_IMAGE" || die HEALTH "$HEALTH_DETAIL"

  # ── 11. 마무리 ──
  [ "$(py sha "$R$RUNTIME_ENV" 2>/dev/null || echo absent)" = "$sum_runtime" ] || warn "runtime.env 가 배포 중 바뀌었습니다(이 장치는 쓰지 않음)"
  [ "$(py sha "$R$TMPFILES_CONF")" = "$sum_tmpfiles" ] || warn "tmpfiles conf 가 배포 중 바뀌었습니다(이 장치는 쓰지 않음)"
  [ "$(py sha "$R$UNIT_DIR/$TUNNEL_UNIT" 2>/dev/null || echo absent)" = "$sum_tunnel" ] || warn "ERP 터널 unit 이 배포 중 바뀌었습니다(이 장치는 쓰지 않음)"
  [ "$(py tree-sha "$R$NGINX_DIR")" = "$sum_nginx" ] || warn "nginx 설정이 배포 중 바뀌었습니다(이 장치는 쓰지 않음)"
  set_phase done
  py state-write "$R$STATE_DIR/current.json" "commit=$NEW" "engine_image=$NEW_ENGINE_IMAGE" \
    "relay_image=$NEW_RELAY_IMAGE" "schema=$schema_new" "deployed_at=$stamp" "previous_commit=$cur"
  py history-add "$R$STATE_DIR/history.json" "$cur"
  py history-add "$R$STATE_DIR/history.json" "$NEW"
  # 이미지 정리: 이 장치가 배포한 기록 중 최근 3개·현재·직전은 남긴다. 기록에 없는 태그는 건드리지 않는다.
  while read -r f; do
    [ -n "$f" ] || continue
    for name in engine relay; do
      if dk image inspect "metainc/naver-$name:$f" >/dev/null 2>&1; then
        if dk rmi "metainc/naver-$name:$f" >/dev/null; then
          log "오래된 이미지 태그 정리: metainc/naver-$name:$f"
        else
          warn "이미지 태그 정리 실패: metainc/naver-$name:$f"
        fi
      fi
    done
    py prune-history "$R$STATE_DIR/history.json" "$f"
  done < <(py prune-list "$R$STATE_DIR/history.json" "$NEW" "$cur")
  finish 0 DEPLOYED "$cur → $NEW 배포 완료($HEALTH_DETAIL, 정지~헬스 준비 ${DOWNTIME:-?}초)"
}

# ── 입구 ────────────────────────────────────────────────────────────────────
case "$MODE" in
  inspect)
    [ "$#" = 1 ] || { echo "사용: $0 inspect" >&2; exit 64; }
    main_inspect
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
    echo "사용: $0 inspect | deploy <commit> <source.tar> [--log FILE] [--result FILE]" >&2
    exit 64
    ;;
esac
