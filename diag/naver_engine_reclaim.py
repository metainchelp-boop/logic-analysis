"""네이버 관제 서버 저장 공간 2차 정리 — 대표 지시 「여기서 완수하자」(2026-10-20).

지우거나 옮기는 것은 세 가지뿐이다(2026-10-20 코드 조사 + 반박 검증 6회 통과).
  ① 배포 도구가 확인하지 않는 옛 엔진·중계 이미지 34개 판(docker image rm, -f 없음).
  ② 배포 도구가 확인하지 않는 옛 릴리스 폴더(releases/naver-<판>) — tar.gz 로 묶어 보관 폴더로 옮긴 뒤 지운다.
  ③ 배포 기록 폴더의 배포 전 DB 사본(account-db-*.sqlite 14개 · completion-db-0e33647f.sqlite) —
     gzip 으로 보관 폴더에 압축 → 풀어서 sha256 이 원본과 같은지 확인 → 원본 삭제. 언제든 같은 바이트로 되돌린다.
배포 도구가 확인하는 36개 판(이미지·릴리스 폴더·영수증) · 엔진 DB · 백업 · 영수증 JSON · 실패 보관분은 손대지 않는다.

CLEANUP_APPLY=1 이 아니면 미리보기만 한다(변경 0). 사전 조건이 하나라도 어긋나면 아무것도 바꾸지 않는다.
업체명·계정번호 미출력 — 크기·개수·판 번호 앞 7자리만 출력한다.
진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
"""
import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import time
from datetime import datetime, timedelta, timezone

MODE = 'naver-engine-reclaim-v1'
CURRENT = '711a245ea14b590a83eb6746b760ce53275b6602'
PREVIOUS = 'b00d6bf805b43b282c04dd95970ae9ccb7d8247d'
# 배포 도구(로직분석 codex/ad-deploy-prep-20261001 @4522a8b)가 manifest() 로 이미지·릴리스 폴더·영수증을 확인하는 판.
KEEP = (
    CURRENT, PREVIOUS,
    '21cd739cf171c066b84683b24e3340feda495858', '513e52eaee4d1bb722461961639cd588df9080cd',
    '70045db75473407591d79c3bfa4e69cbb217f6b9', '9379023a7a13b0d71b79a57ebf8979591b574f9f',
    'b5e40fa01e6432ab0a62541c330652e1cb4fae2c', '114dde8a45e1753ade0ff871f024c7e5880546c5',
    '621c5efeaf607b8227898bdf65d3ef040d1740fa', '1fc2c92a18ea50dfef4e0b3da9ddd973f4017715',
    'c20089be6c2e397bedea913a8ba9448f44a03de8', '7f138a8d42bb292567ccb3e117bd0305efc42ad7',
    '7b61f64223cbd386c6971b8bc93b9ab17c11f34f', '53926862e3263097b6ed5cb7b9bc0bb7617ff1c5',
    '07890f1da91f09aca87f2b093852f46778971ba1', 'd59977f778a9a80d0c2b3e73bdcdddcceea57855',
    '8876a77e194732bfe15bcc4ae5227c54c9eb7e1f', 'be97e432ecb39e91cc54b03f9f26f2fb133ec8d0',
    '7d9b8e05ff847fabc74fdc6f1cd01fd63d77e06b', '38a4d36e2528e4fc9ba4a6c9767fe93fdd197eeb',
    'fd9132c07031cae7162fb8af2a5131a8b1aeaba0', 'c40a1dbd0132043ce5b6a6a5565c7786699b60c0',
    '4d5802360c1ba23aa801b1145ca8483db3edd35f', '32878e8ecec616772b619c23e796931d44f0bee1',
    '799d80225a8df0c897a125dcab75fd04978b1dbb', 'dc168ff8cf8dac519ea38597305a0d9dd6f6c843',
    '15f3a23c2255de98cba3670fce3b489309698e1f', '70e6657ac789ce4d72a165dbf6a6e552d2b84043',
    'faa0df6225aa5fff5c4e4884245a4884c0b5f77a', 'dadb4e89bb28021db50f1c5bb3682a6c81398003',
    'e7649acfc71c25d7ae9c981a6ba036b77d97897b', '737a65952f2ddbc05a235cf2b139a4a11f4e7673',
    '9ddb0a30e16e4177e8d419318a6f23eb6c206e2f', '09b216f26509fed97179114ee97cb0d4169ce5f8',
    '10a46ddce2116e274e27fabaf73c7a94be6cda62', 'da8e1c071f848898b8857221ac3d618786b5d0b7',
)
# 배포 도구가 참조하지 않는 옛 판 34개(이미지만 지운다).
DELETE_IMAGES = (
    '607f537b4dad65ae2e937042443d3d727155de1a', 'e1c4b3526db55d78175a1d6598f3403fdb9398f7',
    '6e4b035901027fef29266de218bfb0594227a3fe', '01344b145d0b679a6ee730d7fa4b5990278dd654',
    '1b790b864ce27766251a205259fa6a332f60f72b', '0a302856c6177c4f53145abaf9ed31b6a39654f3',
    'a38c53775c112cdf5db420f979093d6bee9e5376', 'c21f5f05f610abf89df0c24e85c00b1bec23d01c',
    '8dd4292d82f5f98e7b4afa44a2a66b6770eaa505', 'a981b35e298aa58a52b30e266792bd0f36506c5d',
    '25dc24d8760a06b2321d4fbde481769c3ce32c34', '6198be366344a82923e10ba5e323877026d82f48',
    'e4f64e165ebdf81d4127218d5c91ff6904e75958', '953c2ccdb1d74a4fd339de013a1bbbbc5f50e3b6',
    '49c42d645b90732071d0c61b8f9aaf7660e8b765', '74b79ce6381178abf9b74fff43b0fcb03c5aa60b',
    '383c8511964c13e24e884a4cee561fc9bee64102', '96f10f05b0e92651e04b2076999fa6c6ace7291e',
    '7985925dcc4ed9d75c28ae43a456964cdc78c63f', 'bd08fd07281ae5448bffb3de3d7c405887bfecd9',
    '3fa096d3d383123fdd3469c5dc68404171a6f076', '9bfcace1c6ba2a49807c5ec8feb69fde11de73bf',
    '3145da9e3021aed0c06d17f2e51525fc866f8799', 'ecb26ccee4aa8d85b0101e0d59aeafe48de1166b',
    '153c9a3a89585b00f2973a694a963ae9227ce19d', '6a0c54de9faffbf65ecee2ce57759598794bc005',
    '702bc6ed3f224638524511a6ef7d43b6dd825343', '7c99e18e29e6cb4d3f32eb41b6983529126d8f3a',
    '7f32d70d97876b806cc5bc44a7cc0f9688caeada', '00701771c0583477357010e9ac731263770f1da5',
    '27ed22b1e77213912db3750ddeb91d046fa770f5', '83ec2d34ad1d06471f638671c283bccd58533f08',
    '7e3762be2c47d5b97f5adfe0babee11a4af388ac', '0873d43580348316f869fbf35c07c563b045b209',
)
NAMES = ('engine', 'relay')
REPOS = tuple('metainc/naver-' + n for n in NAMES)
ROOT = '/srv/metainc/ad-deploy-staging'
RECEIPTS = ROOT + '/receipts'
RELEASES = ROOT + '/releases'
CONFIG_DIR = ROOT + '/claude-config/74c912dddf824fae99012849bc4c19a5'
EXPORTS_RECEIPT = RECEIPTS + '/completion-exports-e7649acfc71c25d7ae9c981a6ba036b77d97897b.json'
ARCHIVE = '/var/backups/metainc/deploy-snapshot-archive'
COMPLETION_DB = 'completion-db-0e33647f9255442bbc94c274db23d438.sqlite'
COMPLETION_PROOF = 'completion-snapshot-0e33647f9255442bbc94c274db23d438.json'
ACCOUNT_DB = re.compile(r'account-db-[0-9a-f]{32}\.sqlite')
RELEASE_DIR = re.compile(r'naver-([0-9a-f]{40})')
KST = timezone(timedelta(hours=9))
TIME_BUDGET = 900
CHUNK = 4 * 1024 * 1024

VERBS = ('compose', 'up', 'run', 'exec', 'logs', 'events', 'stats', 'ps', 'inspect', 'start', 'stop', 'restart', 'wait',
         'attach', 'version', 'info', 'cp', 'build', 'buildx', 'builder', 'image', 'images', 'pull', 'load', 'rmi', 'tag',
         'push', 'save', 'commit', 'system', 'create', 'down', 'rm', 'prune', 'import')
MUTATING = frozenset(('build', 'buildx', 'builder', 'image', 'pull', 'load', 'rmi', 'tag', 'push', 'save', 'commit',
                      'system', 'create', 'down', 'rm', 'prune', 'import'))


def run(args, timeout=120):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise ValueError('CMD_FAILED:' + args[1] if len(args) > 1 else 'CMD_FAILED')
    return result.stdout.decode('utf-8', 'replace')


def size_mb(text):
    m = re.match(r'\s*([0-9.]+)\s*([kKMGT]?B)', text or '')
    if not m:
        return None
    unit = {'B': 1 / 1048576, 'kB': 1 / 1024, 'KB': 1 / 1024, 'MB': 1, 'GB': 1024, 'TB': 1048576}[m.group(2)]
    return round(float(m.group(1)) * unit, 1)


def mb(value):
    return round(value / 1048576, 1)


def free_gb():
    fs = os.statvfs('/')
    return round(fs.f_bavail * fs.f_frsize / 1073741824, 2)


def docker_df():
    rows = [json.loads(line) for line in run(['docker', 'system', 'df', '--format', '{{json .}}']).splitlines() if line.strip()]
    return {(r.get('Type') or 'OTHER').replace(' ', '_'): dict(size_mb=size_mb(r.get('Size')), reclaimable_mb=size_mb(r.get('Reclaimable')))
            for r in rows if re.fullmatch('[A-Za-z ]{1,20}', r.get('Type') or '')}


def naver_tags():
    tags = {}
    for line in run(['docker', 'images', '--no-trunc', '--format', '{{.Repository}}:{{.Tag}} {{.ID}}']).splitlines():
        ref, _, image = line.strip().partition(' ')
        if ref.split(':')[0] in REPOS:
            tags[ref] = image
    return tags


def used_images():
    ids = run(['docker', 'ps', '-a', '-q', '--no-trunc']).split()
    if not ids:
        return set()
    return {line.strip() for line in run(['docker', 'inspect', '--format', '{{.Image}}'] + ids).splitlines() if line.strip()}


def services():
    out = {}
    for name in NAMES:
        project = 'naver-engine' if name == 'engine' else 'naver-relay'
        ids = run(['docker', 'ps', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + project,
                   '--filter', 'label=com.docker.compose.service=' + project, '--format', '{{.ID}}']).split()
        if len(ids) != 1:
            out[name] = dict(found=len(ids))
            continue
        row = json.loads(run(['docker', 'inspect', '--format',
                              '{"image":{{json .Image}},"started":{{json .State.StartedAt}},"running":{{json .State.Running}},'
                              '"restarts":{{json .RestartCount}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}',
                              ids[0]]))
        row['id'] = ids[0]
        out[name] = row
    return out


def ancestors():
    out, pid = set(), os.getpid()
    while pid > 1 and pid not in out:
        out.add(pid)
        with open('/proc/%d/stat' % pid) as f:
            pid = int(f.read().rsplit(')', 1)[1].split()[1])
    return out


def other_docker_clients():
    mine = ancestors()
    verbs, busy, deploy = {}, 0, 0
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) in mine:
            continue
        try:
            with open('/proc/' + pid + '/cmdline', 'rb') as f:
                raw = f.read()
        except OSError:
            continue
        argv = [t for t in raw.split(b'\0') if t]
        if not argv:
            continue
        base = os.path.basename(argv[0].decode('utf-8', 'replace'))
        if base not in ('docker', 'docker-compose', 'docker-buildx') and (
                (base.startswith('python') and argv[1:] == [b'-I', b'-B', b'-']) or b'exec(compile(' in raw):
            deploy += 1
        if base in ('docker', 'docker-compose', 'docker-buildx'):
            found = [w for w in (t.decode('utf-8', 'replace') for t in argv[1:]) if w in VERBS]
            key = '+'.join(found[:2]) or 'OTHER'
            verbs[key] = verbs.get(key, 0) + 1
            if MUTATING.intersection(found) or base == 'docker-buildx':
                busy += 1
    return dict(verbs=verbs, busy=busy, deploy_tool=deploy)


def unique_sizes():
    sizes = {}
    try:
        text = run(['docker', 'system', 'df', '-v'], timeout=180)
    except Exception:
        return sizes
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 8 and parts[0] in REPOS:
            sizes[parts[0] + ':' + parts[1]] = size_mb(parts[-2])
    return sizes


def regular(path):
    try:
        s = os.lstat(path)
    except FileNotFoundError:
        return None
    return s if stat.S_ISREG(s.st_mode) else False


def real_dir(path):
    try:
        s = os.lstat(path)
    except FileNotFoundError:
        return None
    return s if stat.S_ISDIR(s.st_mode) else False


def tree_bytes(path):
    total, files = 0, 0
    for base, dirs, names in os.walk(path):
        for name in names:
            s = os.lstat(os.path.join(base, name))
            total += s.st_size
            files += 1
    return total, files


def keep_check(tags):
    missing = {}
    for commit in KEEP:
        for repo in REPOS:
            if repo + ':' + commit not in tags:
                missing.setdefault('image', []).append(commit[:7])
        if not real_dir(RELEASES + '/naver-' + commit):
            missing.setdefault('release_dir', []).append(commit[:7])
        for name in ('preview-' + commit + '.json', 'preview-start-' + commit + '.json'):
            if not regular(RECEIPTS + '/' + name):
                missing.setdefault('receipt', []).append(commit[:7])
    if not real_dir(CONFIG_DIR):
        missing['config_dir'] = ['74c912d']
    if not regular(EXPORTS_RECEIPT):
        missing['exports_receipt'] = ['e7649ac']
    return {k: sorted(set(v)) for k, v in missing.items()}


def state():
    tags = naver_tags()
    releases = sorted(n for n in os.listdir(RELEASES))
    receipts = sorted(n for n in os.listdir(RECEIPTS))
    return dict(free_gb=free_gb(), docker=docker_df(), services=services(), tags=tags, used=used_images(),
                receipts=receipts, releases=releases, keep_missing=keep_check(tags))


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def archive_dir():
    os.makedirs(ARCHIVE, mode=0o700, exist_ok=True)
    s = os.lstat(ARCHIVE)
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or stat.S_IMODE(s.st_mode) != 0o700:
        raise ValueError('ARCHIVE_DIR_UNSAFE')
    for name in os.listdir(ARCHIVE):
        if name.endswith('.partial'):
            os.unlink(os.path.join(ARCHIVE, name))


def manifest_load():
    path = os.path.join(ARCHIVE, 'MANIFEST.json')
    if not os.path.exists(path):
        return {'version': 1, 'entries': []}
    with open(path) as f:
        return json.load(f)


def manifest_add(entry):
    data = manifest_load()
    data['entries'] = [e for e in data['entries'] if e.get('archive') != entry['archive']] + [entry]
    data['restore'] = ('gzip -dc <archive>.gz > <receipts>/<name>; chown 0:0; chmod 0600; sha256sum must equal original_sha256. '
                       'releases-*.tar.gz: tar -xzpf into <ROOT>/releases with numeric owners.')
    tmp = os.path.join(ARCHIVE, 'MANIFEST.json.partial')
    with open(tmp, 'w') as f:
        json.dump(data, f, sort_keys=True, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, os.path.join(ARCHIVE, 'MANIFEST.json'))
    fsync_dir(ARCHIVE)


def archive_snapshot(name, expected_sha=None):
    source = RECEIPTS + '/' + name
    before = os.lstat(source)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != 0:
        return dict(result='UNSAFE_SOURCE')
    target = os.path.join(ARCHIVE, name + '.gz')
    if os.path.lexists(target):
        return dict(result='ARCHIVE_EXISTS')
    partial = target + '.partial'
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return dict(result='SOURCE_LOCKED')
        digest = hashlib.sha256()
        out_fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(out_fd, 'wb') as raw, gzip.GzipFile(filename=name, mode='wb', compresslevel=6, fileobj=raw, mtime=0) as gz, \
                os.fdopen(os.dup(fd), 'rb') as src:
            while True:
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                gz.write(chunk)
        original = digest.hexdigest()
        if expected_sha is not None and original != expected_sha:
            os.unlink(partial)
            return dict(result='PROOF_MISMATCH')
        check, packed = hashlib.sha256(), hashlib.sha256()
        with open(partial, 'rb') as f:
            for chunk in iter(lambda: f.read(CHUNK), b''):
                packed.update(chunk)
        with gzip.open(partial, 'rb') as gz:
            for chunk in iter(lambda: gz.read(CHUNK), b''):
                check.update(chunk)
        if check.hexdigest() != original:
            os.unlink(partial)
            return dict(result='VERIFY_MISMATCH')
        with open(partial, 'rb') as f:
            os.fsync(f.fileno())
        os.rename(partial, target)
        fsync_dir(ARCHIVE)
        after = os.fstat(fd)
        if (after.st_size, after.st_mtime_ns, after.st_ino) != (before.st_size, before.st_mtime_ns, before.st_ino):
            return dict(result='SOURCE_CHANGED')
        manifest_add(dict(kind='receipt-snapshot', name=name, archive=os.path.basename(target), original_size=before.st_size,
                          original_sha256=original, archive_size=os.path.getsize(target), archive_sha256=packed.hexdigest(),
                          uid=0, gid=before.st_gid, mode='%o' % stat.S_IMODE(before.st_mode), mtime_ns=before.st_mtime_ns,
                          proof_checked=expected_sha is not None, archived_at=datetime.now(timezone.utc).isoformat()))
        os.unlink(source)
        fsync_dir(RECEIPTS)
        return dict(result='ARCHIVED', original_mb=mb(before.st_size), archive_mb=mb(os.path.getsize(target)))
    finally:
        os.close(fd)


def archive_releases(commits):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = os.path.join(ARCHIVE, 'releases-' + stamp + '.tar.gz')
    partial = target + '.partial'
    expected = set()
    for commit in commits:
        base = RELEASES + '/naver-' + commit
        for root, dirs, names in os.walk(base):
            for entry in dirs + names:
                expected.add(os.path.relpath(os.path.join(root, entry), RELEASES))
        expected.add('naver-' + commit)
    out_fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(out_fd, 'wb') as raw:
        with tarfile.open(fileobj=raw, mode='w:gz', compresslevel=6) as tar:
            for commit in commits:
                tar.add(RELEASES + '/naver-' + commit, arcname='naver-' + commit, recursive=True)
        raw.flush()
        os.fsync(raw.fileno())
    with tarfile.open(partial, 'r:gz') as tar:
        names = {m.name for m in tar.getmembers()}
    if names != expected:
        os.unlink(partial)
        raise ValueError('RELEASE_ARCHIVE_MISMATCH')
    digest = hashlib.sha256()
    with open(partial, 'rb') as f:
        for chunk in iter(lambda: f.read(CHUNK), b''):
            digest.update(chunk)
    os.rename(partial, target)
    fsync_dir(ARCHIVE)
    manifest_add(dict(kind='release-dirs', archive=os.path.basename(target), commits=sorted(c[:7] for c in commits),
                      entries=len(names), archive_size=os.path.getsize(target), archive_sha256=digest.hexdigest(),
                      archived_at=datetime.now(timezone.utc).isoformat()))
    removed = 0
    for commit in commits:
        path = RELEASES + '/naver-' + commit
        if real_dir(path):
            shutil.rmtree(path)
            removed += 1
    fsync_dir(RELEASES)
    return dict(removed=removed, archive_mb=mb(os.path.getsize(target)))


def main():
    apply = os.environ.get('CLEANUP_APPLY') == '1'
    started = time.monotonic()
    result = dict(mode=MODE, apply=apply, ok=False, mutations=0)
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        now = datetime.now(KST)
        minute = now.hour * 60 + now.minute
        if minute >= 23 * 60 + 30 or minute < 60:
            raise ValueError('BACKUP_WINDOW')
        if not (set(DELETE_IMAGES).isdisjoint(KEEP) and len(set(KEEP)) == 36 and len(set(DELETE_IMAGES)) == 34):
            raise ValueError('LIST_INVALID')
        before = state()
        result['before'] = dict(free_gb=before['free_gb'], docker=before['docker'], naver_tags=len(before['tags']),
                                receipts=len(before['receipts']), releases=len(before['releases']), keep_missing=before['keep_missing'])
        svc = before['services']
        for name in NAMES:
            row = svc.get(name, {})
            if row.get('running') is not True or row.get('source') != CURRENT:
                raise ValueError('SERVICE_NOT_CURRENT')
        if before['keep_missing']:
            raise ValueError('KEEP_SET_INCOMPLETE')
        clients = other_docker_clients()
        result['other_docker_clients'] = clients
        if clients['busy']:
            raise ValueError('DOCKER_CLIENT_BUSY')
        if clients['deploy_tool']:
            raise ValueError('DEPLOY_TOOL_RUNNING')
        keep_ids = {before['tags'][r + ':' + c] for c in KEEP for r in REPOS}
        sizes = unique_sizes()
        image_plan, skipped = [], {}
        for commit in DELETE_IMAGES:
            for repo in REPOS:
                ref = repo + ':' + commit
                image = before['tags'].get(ref)
                if image is None:
                    skipped['missing'] = skipped.get('missing', 0) + 1
                elif image in before['used']:
                    skipped['in_use'] = skipped.get('in_use', 0) + 1
                elif image in keep_ids:
                    skipped['same_as_keep'] = skipped.get('same_as_keep', 0) + 1
                else:
                    image_plan.append(ref)
        known = {r + ':' + c for c in KEEP + DELETE_IMAGES for r in REPOS}
        release_plan, release_other, release_bytes = [], 0, 0
        for name in before['releases']:
            m = RELEASE_DIR.fullmatch(name)
            if not m:
                release_other += 1
                continue
            path = RELEASES + '/' + name
            s = real_dir(path)
            if m.group(1) in KEEP:
                continue
            if not s or s.st_uid != 0:
                release_other += 1
                continue
            release_plan.append(m.group(1))
            release_bytes += tree_bytes(path)[0]
        proof = None
        try:
            with open(RECEIPTS + '/' + COMPLETION_PROOF) as f:
                value = json.load(f).get('database_sha256')
            proof = value if isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) else None
        except (OSError, ValueError):
            proof = None
        snap_plan, snap_bytes, other_sqlite = [], 0, 0
        for name in before['receipts']:
            if name == COMPLETION_DB or ACCOUNT_DB.fullmatch(name):
                s = regular(RECEIPTS + '/' + name)
                if s:
                    snap_plan.append((name, s.st_size))
                    snap_bytes += s.st_size
            elif name.endswith('.sqlite'):
                other_sqlite += 1
        snap_plan.sort(key=lambda x: -x[1])
        result['plan'] = dict(
            images=len(image_plan), image_commits=len({r.split(':')[1] for r in image_plan}),
            image_unique_mb=round(sum(sizes.get(r) or 0 for r in image_plan), 1), image_skipped=skipped,
            unknown_naver_tags=len([r for r in before['tags'] if r not in known]),
            release_dirs=len(release_plan), release_mb=mb(release_bytes), release_other=release_other,
            snapshots=len(snap_plan), snapshot_mb=mb(snap_bytes), completion_proof=proof is not None,
            other_sqlite_in_receipts=other_sqlite)
        if not apply:
            result['ok'] = True
            return
        try:
            os.nice(19)
            subprocess.run(['ionice', '-c3', '-p', str(os.getpid())], capture_output=True, timeout=10)
        except Exception:
            pass
        archive_dir()
        snaps = {}
        for name, _ in snap_plan:
            if time.monotonic() - started > TIME_BUDGET:
                snaps['deferred'] = snaps.get('deferred', 0) + 1
                continue
            expected = proof if name == COMPLETION_DB else None
            if name == COMPLETION_DB and proof is None:
                snaps['no_proof'] = snaps.get('no_proof', 0) + 1
                continue
            outcome = archive_snapshot(name, expected)
            key = outcome['result']
            snaps[key] = snaps.get(key, 0) + 1
            if key == 'ARCHIVED':
                result['mutations'] += 1
                snaps['original_mb'] = round(snaps.get('original_mb', 0) + outcome['original_mb'], 1)
                snaps['archive_mb'] = round(snaps.get('archive_mb', 0) + outcome['archive_mb'], 1)
        result['snapshots'] = snaps
        if release_plan:
            result['releases'] = archive_releases(release_plan)
            result['mutations'] += result['releases']['removed']
        removed, failed = 0, 0
        for ref in image_plan:
            try:
                run(['docker', 'image', 'rm', ref], timeout=120)
                removed += 1
            except Exception:
                failed += 1
        result['mutations'] += removed
        result['images'] = dict(removed=removed, failed=failed)
        after = state()
        result['after'] = dict(free_gb=after['free_gb'], docker=after['docker'], naver_tags=len(after['tags']),
                               receipts=len(after['receipts']), releases=len(after['releases']), keep_missing=after['keep_missing'])
        archived = {n for n, _ in snap_plan} - set(after['receipts'])
        checks = dict(
            services_unchanged=all(after['services'].get(n) == svc.get(n) for n in NAMES),
            keep_set_intact=not after['keep_missing'],
            other_tags_unchanged={r: i for r, i in before['tags'].items() if r not in image_plan}
            == {r: i for r, i in after['tags'].items() if r not in image_plan},
            receipts_only_archived=set(before['receipts']) - set(after['receipts']) == archived
            and set(after['receipts']) <= set(before['receipts']),
            archived_count_match=len(archived) == snaps.get('ARCHIVED', 0),
            releases_only_planned=set(before['releases']) - set(after['releases']) == {'naver-' + c for c in release_plan}
            and set(after['releases']) <= set(before['releases']),
        )
        result['checks'] = checks
        result['ok'] = all(checks.values()) and failed == 0
    except Exception as error:
        result['error'] = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}(:[a-z]{1,20})?', str(error)) else type(error).__name__
    finally:
        result['seconds'] = round(time.monotonic() - started, 1)
        print('NAVER_ENGINE_RECLAIM_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
