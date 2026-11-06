"""NAVER 중단된 백업 snapshot 무손실 gzip 보존 후 정리 (대표 콘솔 수동 실행, root 전용).

사용: python3 backup_snapshot_preserve.py check   # 검사·압축 크기 측정만, 디스크에 아무것도 쓰지 않음
      python3 backup_snapshot_preserve.py apply   # gzip 보존본 작성·전량 해제 대조 후 원본과 깨진 ZIP 삭제

전제: relay → engine 을 먼저 정지한다. 터널은 그대로 둔다. state.json 은 읽지도 바꾸지도 않는다.
어느 검사든 실패하면 즉시 멈추고(종료코드 1) 다음 단계로 가지 않는다. 엔진 재기동은 사람이 결정한다.
DB 를 열지 않으며 압축 해제 내용을 디스크에 쓰지 않는다(바이트 동일성 확인이며 DB 복구 시험은 아님).
두 파일은 O_NOFOLLOW 로 연 fd 에 고정하고, 해시·검증은 그 fd 로만 하며, 경로 작업 직전마다 경로가 같은
inode 를 가리키는지 다시 대조한다.
"""
import errno
import gzip
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
GZ_LEVEL = 1
RESERVE = 512 * 1024 ** 2
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


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sha_fd(fd):
    h, n = hashlib.sha256(), 0
    os.lseek(fd, 0, os.SEEK_SET)
    for block in iter(lambda: os.read(fd, CHUNK), b''):
        h.update(block)
        n += len(block)
    return h.hexdigest(), n


class Counter:
    def __init__(self):
        self.n = 0

    def write(self, b):
        self.n += len(b)
        return len(b)

    def flush(self):
        pass


def gz_size(fd):
    """디스크에 쓰지 않고 같은 설정의 gzip 결과 바이트 수만 센다."""
    c = Counter()
    os.lseek(fd, 0, os.SEEK_SET)
    with gzip.GzipFile(filename='', mode='wb', compresslevel=GZ_LEVEL, fileobj=c, mtime=0) as g:
        for block in iter(lambda: os.read(fd, CHUNK), b''):
            g.write(block)
    return c.n


def measure(work, fds):
    before = {n: ident(os.fstat(fds[n])) for n in FILES}
    sha, size = sha_fd(fds['snapshot.sqlite'])
    need(size == before['snapshot.sqlite'][2], 'SIZE_CHANGED')
    compressed = gz_size(fds['snapshot.sqlite'])
    need({n: ident(os.fstat(fds[n])) for n in FILES} == before, 'CHANGED_DURING_CHECK')
    for n in FILES:
        same_path(work + '/' + n, fds[n], before[n])
    s = os.statvfs(ROOT)
    free = s.f_bavail * s.f_frsize
    say('MEASURED', 'snapshot_bytes=%d gzip_bytes=%d free_gib=%.2f' % (size, compressed, free / GIB))
    need(free >= compressed + RESERVE, 'SPACE_SHORT')
    return before, sha, size, compressed


def apply(work, keys, fds, before, sha, size, compressed):
    snap, packed = work + '/snapshot.sqlite', work + '/packed.zip'
    no_symlink_parents(KEEP_PARENT)
    need(not os.path.lexists(KEEP_DIR), 'KEEP_DIR_EXISTS')
    STAGE[0] = '보존 폴더 생성 중 또는 후(원본 무변경)'
    os.mkdir(KEEP_DIR, 0o700)
    os.chmod(KEEP_DIR, 0o700)
    need(os.lstat(KEEP_DIR).st_dev == before['snapshot.sqlite'][0], 'KEEP_OTHER_DEVICE')
    partial, final = KEEP_DIR + '/snapshot.sqlite.gz.partial', KEEP_DIR + '/snapshot.sqlite.gz'
    STAGE[0] = 'gzip 보존본 작성 중(원본 무변경)'
    out = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(out, 'wb') as raw:
        os.lseek(fds['snapshot.sqlite'], 0, os.SEEK_SET)
        with gzip.GzipFile(filename='', mode='wb', compresslevel=GZ_LEVEL, fileobj=raw, mtime=0) as g:
            for block in iter(lambda: os.read(fds['snapshot.sqlite'], CHUNK), b''):
                g.write(block)
        raw.flush()
        os.fsync(raw.fileno())
    need(os.lstat(partial).st_size == compressed, 'GZIP_SIZE_MISMATCH')
    STAGE[0] = 'gzip 보존본 전량 해제 대조 중(원본 무변경)'
    h, n = hashlib.sha256(), 0
    with os.fdopen(os.open(partial, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as f, \
            gzip.GzipFile(fileobj=f, mode='rb') as g:
        for block in iter(lambda: g.read(CHUNK), b''):
            h.update(block)
            n += len(block)
    need(h.hexdigest() == sha and n == size, 'GZIP_VERIFY_FAILED')
    need(sha_fd(fds['snapshot.sqlite']) == (sha, size), 'SNAPSHOT_CHANGED')
    os.rename(partial, final)
    meta = KEEP_DIR + '/snapshot.sqlite.json'
    mfd = os.open(meta, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(mfd, 'w') as m:
        json.dump({'source': 'interrupted nightly backup 2026-11-06 00:35 KST', 'sha256': sha, 'bytes': size,
                   'gzip_bytes': compressed, 'gzip_level': GZ_LEVEL}, m, sort_keys=True)
        m.flush()
        os.fsync(m.fileno())
    fsync_dir(KEEP_DIR)
    fsync_dir(KEEP_PARENT)
    say('GZIP_KEPT', final)
    services_stopped()
    nobody_uses(keys)
    same_path(snap, fds['snapshot.sqlite'], before['snapshot.sqlite'])
    same_path(packed, fds['packed.zip'], before['packed.zip'])
    STAGE[0] = '원본 삭제 중 또는 후(보존본 완성)'
    os.unlink(snap)
    os.close(fds.pop('snapshot.sqlite'))
    os.unlink(packed)
    os.close(fds.pop('packed.zip'))
    fsync_dir(work)
    os.rmdir(work)
    fsync_dir(ROOT)
    say('SNAPSHOT_REMOVED', 'bytes=%d broken_zip_removed=yes' % size)


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
    for label, path in (('snapshot', snap), ('broken_zip', packed), ('keep_dir', KEEP_DIR),
                        ('gzip_partial', KEEP_DIR + '/snapshot.sqlite.gz.partial'),
                        ('gzip_final', KEEP_DIR + '/snapshot.sqlite.gz')):
        say('LEFT', '%s=%s' % (label, 'absent' if path == 'none' else state_of(path)))


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
        before, sha, size, compressed = measure(work, fds)
        if mode == 'apply':
            apply(work, keys, fds, before, sha, size, compressed)
        for fd in list(fds.values()):
            os.close(fd)
        fds.clear()
        s = os.statvfs(ROOT)
        free = s.f_bavail * s.f_frsize
        db = os.lstat(DB).st_size
        peak = db + db // 10 * 3 + GIB
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
