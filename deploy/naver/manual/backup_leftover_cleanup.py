"""NAVER 백업 잔재 1회 정리 (대표 콘솔 수동 실행, root 전용).

사용: python3 backup_leftover_cleanup.py check   # 검사만, 아무것도 바꾸지 않음
      python3 backup_leftover_cleanup.py apply   # 검사 통과 시 ZIP 보존 이동 후 snapshot 1개만 삭제

전제: relay → engine 을 먼저 정지한다. 터널은 그대로 둔다. state.json 은 읽지도 바꾸지도 않는다.
어느 검사든 실패하면 즉시 멈추고(종료코드 1) 다음 단계로 가지 않는다. 엔진 재기동은 사람이 결정한다.
DB 를 열지 않으며 압축 해제 내용을 디스크에 쓰지 않는다(바이트 동일성 확인이며 DB 복구 시험은 아님).
두 파일은 O_NOFOLLOW 로 연 fd 에 고정하고, 해시·검증은 그 fd 로만 하며, 경로 작업 직전마다 경로가 같은
inode 를 가리키는지 다시 대조한다.
"""
import errno
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
DB = '/var/lib/metainc/naver-engine/engine.db'
UNITS = ('metainc-naver-relay.service', 'metainc-naver-engine.service')
PROJECTS = ('naver-relay', 'naver-engine')
DOCKER = ('/usr/bin/docker', '--host=unix:///var/run/docker.sock')
ENGINE_UID = 10001
FILES = ('snapshot.sqlite', 'packed.zip')
MANIFEST_MAX = 64 * 1024
CHUNK = 1024 * 1024
GIB = 1024 ** 3
STAGE = ['검사 단계(아무것도 바꾸지 않음)']


class Stop(Exception):
    pass


def say(code, detail=''):
    print(code + (' ' + detail if detail else ''), flush=True)


def need(ok, code, detail=''):
    if not ok:
        raise Stop(code + (' ' + detail if detail else ''))


def run(*argv):
    out = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    return out.returncode, out.stdout.strip()


def services_stopped():
    for unit in UNITS:
        rc, pid = run('systemctl', 'show', '-p', 'MainPID', '--value', unit)
        need(rc == 0 and pid == '0', 'UNIT_STILL_RUNNING', unit)
        _, state = run('systemctl', 'is-active', unit)
        need(state in ('inactive', 'failed'), 'UNIT_NOT_STOPPED', unit)
    for project in PROJECTS:
        rc, ids = run(*DOCKER, 'ps', '-a', '-q', '--filter', 'label=com.docker.compose.project=' + project)
        need(rc == 0 and len(ids.split()) == 1, 'CONTAINER_COUNT', project)
        rc, state = run(*DOCKER, 'inspect', '-f', '{{.State.Running}} {{.State.Pid}}', ids.split()[0])
        need(rc == 0 and state == 'false 0', 'CONTAINER_STILL_RUNNING', project)


def nobody_uses(keys):
    """keys = {(dev, ino)}. 어떤 프로세스의 cwd·root·fd·mmap 도 그 inode 를 가리키면 중단한다."""
    me = os.getpid()
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) == me:
            continue
        base = '/proc/' + pid
        if not os.path.isdir(base):
            continue                                   # 그 사이 종료한 프로세스
        refs = [base + '/cwd', base + '/root']
        try:
            refs += [base + '/fd/' + n for n in os.listdir(base + '/fd')]
            refs += [base + '/map_files/' + n for n in os.listdir(base + '/map_files')]
        except OSError as e:
            if e.errno in (errno.ENOENT, errno.ESRCH):
                continue                               # 프로세스 종료
            raise Stop('PROC_UNREADABLE pid=' + pid)
        for ref in refs:
            try:
                s = os.stat(ref)
            except OSError as e:
                if e.errno in (errno.ENOENT, errno.ESRCH):
                    continue                           # 그 항목만 닫힘 또는 프로세스 종료
                raise Stop('PROC_UNREADABLE pid=' + pid)
            need((s.st_dev, s.st_ino) not in keys, 'PATH_IN_USE', 'pid=' + pid)


def no_symlink_parents(path):
    parts = path.strip('/').split('/')
    for i in range(1, len(parts) + 1):
        p = '/' + '/'.join(parts[:i])
        need(not stat.S_ISLNK(os.lstat(p).st_mode), 'SYMLINK_IN_PATH', p)


def ident(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)


def same_path(path, fd, expected):
    a, b = os.lstat(path), os.fstat(fd)
    need(stat.S_ISREG(a.st_mode) and ident(a) == ident(b) == expected, 'PATH_CHANGED', os.path.basename(path))


def find_target(fds):
    no_symlink_parents(ROOT)
    root = os.lstat(ROOT)
    need(stat.S_ISDIR(root.st_mode), 'ROOT_NOT_DIR')
    names = [n for n in os.listdir(ROOT) if n.startswith('.building-')]
    need(len(names) == 1, 'BUILDING_COUNT', str(len(names)))
    work = ROOT + '/' + names[0]
    s = os.lstat(work)
    need(stat.S_ISDIR(s.st_mode), 'BUILDING_NOT_DIR')
    need(s.st_uid == ENGINE_UID and stat.S_IMODE(s.st_mode) == 0o700, 'BUILDING_OWNER_MODE')
    need(s.st_dev == root.st_dev, 'BUILDING_OTHER_DEVICE')
    need(sorted(os.listdir(work)) == sorted(FILES), 'BUILDING_FILES')
    for name in FILES:
        fd = os.open(work + '/' + name, os.O_RDONLY | os.O_NOFOLLOW)
        fds[name] = fd                                 # 실패해도 main 의 finally 가 닫는다
        f = os.fstat(fd)
        need(stat.S_ISREG(f.st_mode) and f.st_nlink == 1 and f.st_uid == ENGINE_UID and f.st_dev == root.st_dev,
             'FILE_SHAPE', name)
    return work, (s.st_dev, s.st_ino)


def sha_fd(fd):
    h = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    for block in iter(lambda: os.read(fd, CHUNK), b''):
        h.update(block)
    return h.hexdigest()


def verify(work, fds):
    before = {n: ident(os.fstat(fds[n])) for n in FILES}
    zip_sha = sha_fd(fds['packed.zip'])               # 보존본 해시는 검증 전에 고정
    with zipfile.ZipFile(os.fdopen(os.dup(fds['packed.zip']), 'rb')) as z:
        infos = z.infolist()
        need(sorted(i.filename for i in infos) == ['manifest.json', 'snapshot.sqlite'] and len(infos) == 2,
             'ZIP_MEMBERS')
        for i in infos:
            need(not i.is_dir() and not stat.S_ISLNK(i.external_attr >> 16), 'ZIP_MEMBER_TYPE')
        need(z.testzip() is None, 'ZIP_CRC_FAILED')
        meta = z.getinfo('manifest.json')
        need(meta.file_size <= MANIFEST_MAX, 'MANIFEST_TOO_LARGE')
        manifest = json.loads(z.read(meta))
        need(isinstance(manifest, dict) and isinstance(manifest.get('sha256'), str), 'MANIFEST_SHAPE')
        info = z.getinfo('snapshot.sqlite')
        need(info.file_size == before['snapshot.sqlite'][2], 'SIZE_MISMATCH')
        h = hashlib.sha256()
        with z.open(info) as m:
            for block in iter(lambda: m.read(CHUNK), b''):
                h.update(block)
        inner = h.hexdigest()
    outer = sha_fd(fds['snapshot.sqlite'])
    need(outer == inner == manifest['sha256'], 'SHA_MISMATCH')
    need({n: ident(os.fstat(fds[n])) for n in FILES} == before, 'CHANGED_DURING_CHECK')
    need(sha_fd(fds['packed.zip']) == zip_sha, 'ZIP_CHANGED_DURING_CHECK')
    for n in FILES:
        same_path(work + '/' + n, fds[n], before[n])
    say('VERIFIED', 'snapshot_bytes=%d zip_bytes=%d' % (before['snapshot.sqlite'][2], before['packed.zip'][2]))
    return before, zip_sha


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def apply(work, keys, fds, before, zip_sha):
    packed, snap = work + '/packed.zip', work + '/snapshot.sqlite'
    no_symlink_parents(KEEP_PARENT)
    need(not os.path.lexists(KEEP_DIR), 'KEEP_DIR_EXISTS')
    STAGE[0] = '보존 폴더 생성 중 또는 후(ZIP 이동 전)'
    os.mkdir(KEEP_DIR, 0o700)                      # 이미 있으면 FileExistsError 로 중단
    os.chmod(KEEP_DIR, 0o700)
    need(os.lstat(KEEP_DIR).st_dev == before['packed.zip'][0], 'KEEP_OTHER_DEVICE')
    target = KEEP_DIR + '/packed.zip'
    services_stopped()
    nobody_uses(keys)
    same_path(packed, fds['packed.zip'], before['packed.zip'])
    same_path(snap, fds['snapshot.sqlite'], before['snapshot.sqlite'])
    STAGE[0] = 'ZIP 이동 중 또는 후(snapshot 삭제 전)'
    os.rename(packed, target)                      # 같은 파일시스템 rename 만(교차 FS 는 OSError, 목적지는 빈 새 폴더)
    os.fsync(fds['packed.zip'])
    fsync_dir(work)
    fsync_dir(KEEP_DIR)
    fsync_dir(KEEP_PARENT)
    moved = os.lstat(target)
    need(ident(moved)[:3] == before['packed.zip'][:3] and not os.path.lexists(packed), 'KEEP_IDENTITY')
    need(sha_fd(fds['packed.zip']) == zip_sha, 'KEEP_SHA')
    say('ZIP_KEPT', target)
    services_stopped()
    nobody_uses(keys)
    same_path(snap, fds['snapshot.sqlite'], before['snapshot.sqlite'])
    STAGE[0] = 'snapshot 삭제 중 또는 후'
    os.unlink(snap)
    os.close(fds.pop('snapshot.sqlite'))           # 열린 fd 가 공간을 붙잡지 않게 바로 닫는다
    fsync_dir(work)
    os.rmdir(work)
    fsync_dir(ROOT)
    say('SNAPSHOT_REMOVED', 'bytes=%d' % before['snapshot.sqlite'][2])


def state_of(path):
    if not path:
        return 'unknown'
    try:
        os.lstat(path)
        return 'present'
    except FileNotFoundError:
        return 'absent'
    except OSError:
        return 'unknown'


def report_left():
    say('STAGE', STAGE[0])
    snap = packed = ''
    try:
        names = [n for n in os.listdir(ROOT) if n.startswith('.building-')]
        if len(names) == 1:
            snap, packed = ROOT + '/' + names[0] + '/snapshot.sqlite', ROOT + '/' + names[0] + '/packed.zip'
        elif not names:
            snap = packed = 'none'
    except OSError:
        pass
    for label, path in (('snapshot', snap), ('packed', packed), ('keep_dir', KEEP_DIR),
                        ('kept_zip', KEEP_DIR + '/packed.zip')):
        say('LEFT', '%s=%s' % (label, 'absent' if path == 'none' else state_of(path)))


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else ''
    fds = {}
    try:
        need(mode in ('check', 'apply'), 'USAGE', 'check|apply')
        need(os.geteuid() == 0, 'NOT_ROOT')
        services_stopped()
        work, dir_key = find_target(fds)
        keys = {dir_key} | {(os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd in fds.values()}
        nobody_uses(keys)
        before, zip_sha = verify(work, fds)
        if mode == 'apply':
            apply(work, keys, fds, before, zip_sha)
        s = os.statvfs(ROOT)
        free = s.f_bavail * s.f_frsize
        db = os.lstat(DB).st_size
        peak = db + 3 * before['packed.zip'][2] + GIB
        say('FREE', 'gib=%.2f db_gib=%.2f backup_peak_estimate_gib=%.2f estimate=%s' %
            (free / GIB, db / GIB, peak / GIB, 'enough' if free >= peak else 'short'))
        say('DONE_' + mode.upper(), '재기동 여부는 이 화면을 보고 결정합니다')
        return 0
    except Stop as e:
        say('STOPPED', str(e))
    except Exception as e:                          # 원문 값은 출력하지 않는다
        say('STOPPED', 'ERROR ' + type(e).__name__)
    finally:
        for fd in fds.values():
            os.close(fd)
        fds.clear()
    report_left()
    say('HOLD', '엔진은 정지 상태 그대로. 재기동하지 말고 이 화면을 보내 주세요.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
