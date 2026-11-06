"""NAVER 백업 잔재 1회 정리 (대표 콘솔 수동 실행, root 전용).

사용: python3 backup_leftover_cleanup.py check   # 검사만, 아무것도 바꾸지 않음
      python3 backup_leftover_cleanup.py apply   # 검사 통과 시 ZIP 보존 이동 후 snapshot 1개만 삭제

전제: relay → engine 을 먼저 정지한다. 터널은 그대로 둔다. state.json 은 읽지도 바꾸지도 않는다.
어느 검사든 실패하면 즉시 멈추고(종료코드 1) 다음 단계로 가지 않는다. 엔진 재기동은 사람이 결정한다.
DB 를 열지 않으며 압축 해제 내용을 디스크에 쓰지 않는다(바이트 동일성 확인이며 DB 복구 시험은 아님).
"""
import hashlib
import json
import os
import stat
import subprocess
import sys
import zipfile

ROOT = '/var/backups/metainc/naver-engine/local'
KEEP_PARENT = '/var/backups/metainc'
KEEP_DIR = KEEP_PARENT + '/naver-engine-interrupted-20261106'
UNITS = ('metainc-naver-relay.service', 'metainc-naver-engine.service')
PROJECTS = ('naver-relay', 'naver-engine')
ENGINE_UID = 10001
FILES = frozenset(('snapshot.sqlite', 'packed.zip'))
CHUNK = 1024 * 1024
GIB = 1024 ** 3


class Stop(Exception):
    pass


def say(code, detail=''):
    print(code + (' ' + detail if detail else ''), flush=True)


def need(ok, code, detail=''):
    if not ok:
        raise Stop(code + (' ' + detail if detail else ''))


def run(*argv):
    out = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    need(out.returncode == 0, 'COMMAND_FAILED', argv[0])
    return out.stdout.strip()


def services_stopped():
    for unit in UNITS:
        need(run('systemctl', 'show', '-p', 'MainPID', '--value', unit) == '0', 'UNIT_STILL_RUNNING', unit)
        state = subprocess.run(('systemctl', 'is-active', unit), capture_output=True, text=True).stdout.strip()
        need(state in ('inactive', 'failed'), 'UNIT_NOT_STOPPED', unit + '=' + state)
    for project in PROJECTS:
        ids = run('docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + project)
        need(ids == '', 'CONTAINER_STILL_RUNNING', project)


def no_process_uses(path):
    real = os.path.realpath(path)
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        links = []
        try:
            links.append(os.readlink('/proc/%s/cwd' % pid))
            for fd in os.listdir('/proc/%s/fd' % pid):
                links.append(os.readlink('/proc/%s/fd/%s' % (pid, fd)))
        except OSError:
            continue
        for link in links:
            need(not (link == real or link.startswith(real + '/')), 'PATH_IN_USE', 'pid=' + pid)


def no_symlink_parents(path):
    parts = path.strip('/').split('/')
    for i in range(1, len(parts) + 1):
        p = '/' + '/'.join(parts[:i])
        need(not stat.S_ISLNK(os.lstat(p).st_mode), 'SYMLINK_IN_PATH', p)


def identity(path):
    s = os.lstat(path)
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)


def find_target():
    no_symlink_parents(ROOT)
    root = os.lstat(ROOT)
    need(stat.S_ISDIR(root.st_mode), 'ROOT_NOT_DIR')
    names = [n for n in os.listdir(ROOT) if n.startswith('.building-')]
    need(len(names) == 1, 'BUILDING_COUNT', str(len(names)))
    work = ROOT + '/' + names[0]
    s = os.lstat(work)
    need(stat.S_ISDIR(s.st_mode), 'BUILDING_NOT_DIR')
    need(s.st_uid == ENGINE_UID and stat.S_IMODE(s.st_mode) == 0o700, 'BUILDING_OWNER_MODE',
         '%d %o' % (s.st_uid, stat.S_IMODE(s.st_mode)))
    need(s.st_dev == root.st_dev, 'BUILDING_OTHER_DEVICE')
    need(set(os.listdir(work)) == FILES, 'BUILDING_FILES', ','.join(sorted(os.listdir(work))))
    for name in FILES:
        f = os.lstat(work + '/' + name)
        need(stat.S_ISREG(f.st_mode) and f.st_nlink == 1 and f.st_uid == ENGINE_UID and f.st_dev == root.st_dev,
             'FILE_SHAPE', name)
    return work


def sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(CHUNK), b''):
            h.update(block)
    return h.hexdigest()


def verify(work):
    snap, packed = work + '/snapshot.sqlite', work + '/packed.zip'
    before = {n: identity(work + '/' + n) for n in FILES}
    with zipfile.ZipFile(packed) as z:
        infos = z.infolist()
        need(sorted(i.filename for i in infos) == ['manifest.json', 'snapshot.sqlite'] and len(infos) == 2,
             'ZIP_MEMBERS', ','.join(i.filename for i in infos))
        for i in infos:
            need(not i.is_dir() and not stat.S_ISLNK(i.external_attr >> 16), 'ZIP_MEMBER_TYPE', i.filename)
        need(z.testzip() is None, 'ZIP_CRC_FAILED')
        manifest = json.loads(z.read('manifest.json'))
        need(isinstance(manifest, dict) and isinstance(manifest.get('sha256'), str), 'MANIFEST_SHAPE')
        info = z.getinfo('snapshot.sqlite')
        need(info.file_size == before['snapshot.sqlite'][2], 'SIZE_MISMATCH')
        h = hashlib.sha256()
        with z.open(info) as m:
            for block in iter(lambda: m.read(CHUNK), b''):
                h.update(block)
        inner = h.hexdigest()
    outer = sha_file(snap)
    need(outer == inner == manifest['sha256'], 'SHA_MISMATCH')
    need({n: identity(work + '/' + n) for n in FILES} == before, 'CHANGED_DURING_CHECK')
    say('VERIFIED', 'snapshot_bytes=%d zip_bytes=%d sha256=%s created_at=%s' %
        (before['snapshot.sqlite'][2], before['packed.zip'][2], outer, manifest.get('created_at')))
    return before, sha_file(packed)


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def free_bytes():
    s = os.statvfs(ROOT)
    return s.f_bavail * s.f_frsize


STAGE = ['검사 단계(아무것도 바꾸지 않음)']


def apply(work, before, zip_sha):
    packed = work + '/packed.zip'
    no_symlink_parents(KEEP_PARENT)
    os.mkdir(KEEP_DIR, 0o700)                      # 이미 있으면 FileExistsError 로 중단
    os.chmod(KEEP_DIR, 0o700)
    need(os.lstat(KEEP_DIR).st_dev == before['packed.zip'][0], 'KEEP_OTHER_DEVICE')
    target = KEEP_DIR + '/packed.zip'
    need(not os.path.lexists(target), 'KEEP_TARGET_EXISTS')
    STAGE[0] = '보존 폴더 생성 후(ZIP 이동 전후일 수 있음)'
    os.rename(packed, target)                      # 같은 파일시스템 rename 만 허용(교차 FS 는 OSError)
    STAGE[0] = 'ZIP 이동 후, snapshot 삭제 전'
    fd = os.open(target, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    fsync_dir(work)
    fsync_dir(KEEP_DIR)
    fsync_dir(KEEP_PARENT)
    moved = identity(target)
    need(moved[:3] == before['packed.zip'][:3] and not os.path.lexists(packed), 'KEEP_IDENTITY')
    need(sha_file(target) == zip_sha, 'KEEP_SHA')
    say('ZIP_KEPT', target)
    services_stopped()
    snap = work + '/snapshot.sqlite'
    need(identity(snap) == before['snapshot.sqlite'], 'SNAPSHOT_CHANGED')
    STAGE[0] = 'snapshot 삭제 중 또는 후'
    os.unlink(snap)
    fsync_dir(work)
    os.rmdir(work)
    fsync_dir(ROOT)
    say('SNAPSHOT_REMOVED', 'bytes=%d' % before['snapshot.sqlite'][2])


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else ''
    try:
        need(mode in ('check', 'apply'), 'USAGE', 'check|apply')
        need(os.geteuid() == 0, 'NOT_ROOT')
        services_stopped()
        work = find_target()
        no_process_uses(work)
        before, zip_sha = verify(work)
        if mode == 'apply':
            apply(work, before, zip_sha)
        free = free_bytes()
        peak = before['snapshot.sqlite'][2] + 3 * before['packed.zip'][2] + GIB
        say('FREE', 'bytes=%d gib=%.2f backup_peak_estimate_gib=%.2f' % (free, free / GIB, peak / GIB))
        say('DONE_' + mode.upper(), 'RESTART_OK' if mode == 'apply' and free >= peak else 'NO_RESTART_DECISION')
        return 0
    except Stop as e:
        say('STOPPED', str(e))
    except OSError as e:
        say('STOPPED', 'OS_ERROR ' + type(e).__name__)
    say('STAGE', STAGE[0])
    say('HOLD', '엔진은 정지 상태 그대로. 재기동하지 말고 이 화면을 보내 주세요.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
