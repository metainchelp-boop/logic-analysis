"""관제 DB 스키마 추가형 이관(21→22) 컨테이너 단계 — 새(또는 옛) 엔진 이미지 안에서만 실행한다.

naver-deploy.sh 의 migrate-* 모드가 `docker run --network none --read-only --user 10001:10001 ...
--entrypoint python3 <정확 이미지 ID> -I -B /opt/naver-migrate/m.py <단계> <JSON 인자>` 로 부른다.
설계: DESIGN-CLAUDE-v3.md(v3.1, 2b62dbd9) + v2 의 대체되지 않은 부분.

- 이 파일은 자기 해시를 담지 않는다. 해시는 naver-deploy.sh 의 MIGRATIONS 와 workflow 가 고정한다.
- 고정 상수(데이터·코드 경로)는 production/rehearsal 에서 바꿀 수 없다. 시험 바꿔치기(NAVER_MIGRATE_TEST=1 +
  NAVER_MIGRATE_DIR/NAVER_MIGRATE_CODE_DIR)는 mode=test 에서만 허용하고, production 에서 보이면 거부한다.
- 원본(엔진 DB)에 대한 쓰기는 chain 의 WAL checkpoint(TRUNCATE)와 비어 있음이 입증된 곁 파일 삭제, 그리고 저널을
  남긴 rename 뿐이다. 이관은 사본에서만 제품 open_writer 로 한다.
- 출력은 결과 한 줄 JSON 뿐이다. 행 값은 절대 출력하지 않는다(개수·해시·상태 코드만).
"""
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import time

DATA_DIR = '/var/lib/naver-engine'
CODE_DIR = '/opt/naver-engine'
CANON = 'engine.db'
PARTIAL = 'engine.db.v22.partial'
WORK = 'engine.db.v22.work'
PRE = 'engine.db.pre-v22'
JOURNAL = 'naver-migrate-journal.json'
RECEIPT = 'naver-migrate-receipt.json'
MARKER = 'naver-migrate-rehearsal-marker'
SIDES = ('-wal', '-shm', '-journal')
BUNDLE_RE = re.compile(r'engine\.db\.failed-v22-[0-9]{8}T[0-9]{6}Z\.d\Z')
CHUNK = 1 << 20
MIB = 1 << 20
CHAIN_DEADLINE = 40 * 60
ROWID_NAMES = ('rowid', '_rowid_', 'oid')
META_TABLE, META_KEY = 'naver_auto_meta', 'schema_version'
RUN_TABLE = 'naver_auto_check_run'
ORPHAN_COLUMNS = ('status', 'error_kind', 'finished_at')
ISO_KST = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+09:00\Z')
RUN_ID = re.compile(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')


class Abort(Exception):
    def __init__(self, code, **extra):
        super().__init__(code)
        self.code = code
        self.extra = extra


# ── 환경 ─────────────────────────────────────────────────────────────────
class Env:
    def __init__(self, mode, as_mode=None):
        test = os.environ.get('NAVER_MIGRATE_TEST') == '1'
        overrides = [k for k in ('NAVER_MIGRATE_DIR', 'NAVER_MIGRATE_CODE_DIR', 'NAVER_MIGRATE_TEST_NO_FLOCK')
                     if k in os.environ]
        if mode not in ('production', 'rehearsal', 'test'):
            raise Abort('MODE_REFUSED')
        if mode == 'test':
            if not test:
                raise Abort('MODE_REFUSED')
            self.data = os.environ.get('NAVER_MIGRATE_DIR') or ''
            self.code = os.environ.get('NAVER_MIGRATE_CODE_DIR') or ''
            if not os.path.isabs(self.data) or not os.path.isabs(self.code):
                raise Abort('MODE_REFUSED')
            self.as_mode = as_mode if as_mode in ('production', 'rehearsal') else 'production'
            self.no_flock = os.environ.get('NAVER_MIGRATE_TEST_NO_FLOCK') == '1'
        else:
            if test or overrides:
                raise Abort('TEST_OVERRIDE_IN_PRODUCTION')
            self.data, self.code, self.as_mode, self.no_flock = DATA_DIR, CODE_DIR, mode, False
        self.mode = mode
        self.test = mode == 'test'

    def p(self, name):
        return os.path.join(self.data, name)

    def check_marker(self):
        """rehearsal 은 scratch 표지가 있어야, production 은 없어야 한다(양방향)."""
        present = os.path.lexists(self.p(MARKER))
        if self.as_mode == 'rehearsal' and not present:
            raise Abort('REHEARSAL_MARKER_MISSING')
        if self.as_mode == 'production' and present:
            raise Abort('REHEARSAL_MARKER_IN_PRODUCTION')


ENV = None
DEADLINE = [None]
FLOOR = [1 << 30]


def free_bytes():
    st = os.statvfs(ENV.data)
    return st.f_bavail * st.f_frsize


def check(stage):
    if DEADLINE[0] is not None and time.monotonic() > DEADLINE[0]:
        raise Abort('DEADLINE', stage=stage)
    if free_bytes() < FLOOR[0]:
        raise Abort('MIN_FREE', stage=stage)


# ── 파일 정체성·해시 ───────────────────────────────────────────────────────
def ident(st):
    return {'dev': st.st_dev, 'ino': st.st_ino, 'size': st.st_size, 'mtime_ns': st.st_mtime_ns}


def same_inode(a, b):
    return a is not None and b is not None and a['dev'] == b['dev'] and a['ino'] == b['ino']


def same_full(a, b):
    return a is not None and b is not None and all(a[k] == b[k] for k in ('dev', 'ino', 'size', 'mtime_ns'))


def lident(name):
    try:
        st = os.lstat(ENV.p(name))
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode):
        raise Abort('NOT_REGULAR', name=name)
    return ident(st)


def sides_of(name):
    out = {}
    for suffix in SIDES:
        try:
            st = os.lstat(ENV.p(name + suffix))
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(st.st_mode):
            raise Abort('SIDECAR_NOT_REGULAR', name=name + suffix)
        out[suffix] = st.st_size
    return out


def sha_fd(fd):
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    count = 0
    while True:
        chunk = os.read(fd, CHUNK)
        if not chunk:
            break
        digest.update(chunk)
        count += 1
        if count % 256 == 0:
            check('sha256')
    return digest.hexdigest()


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def owned_private(fd, what):
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise Abort('FILE_SHAPE', what=what)
    if not ENV.test and st.st_uid != os.geteuid():
        raise Abort('FILE_OWNER', what=what)
    return st


def lock(fd):
    """엔진 writer 와 같은 방식(파일 자체 flock, 기다리지 않음). 잡으면 엔진이 그 inode 를 쓰고 있지 않다."""
    if ENV.no_flock:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise Abort('LOCK_BUSY') from None


def open_locked(name, expect=None, full=False):
    fd = os.open(ENV.p(name), os.O_RDWR | os.O_NOFOLLOW)
    try:
        owned_private(fd, name)
        lock(fd)
        got = ident(os.fstat(fd))
        if expect is not None and not (same_full(got, expect) if full else same_inode(got, expect)):
            raise Abort('IDENTITY_MISMATCH', name=name)
        if not same_full(got, lident(name)):
            raise Abort('IDENTITY_CHANGED', name=name)
        return fd
    except BaseException:
        os.close(fd)
        raise


def atomic_json(name, value):
    path = ENV.p(name)
    temporary = path + '.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(value, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_dir(ENV.data)


def read_json(name):
    try:
        with open(ENV.p(name)) as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None


# ── 저널(이름 바꾸기 전후를 내구성 있게 기록) ─────────────────────────────────
def journal(run, op, phase, **fields):
    data = read_json(JOURNAL) or {'run': run, 'entries': []}
    if data.get('run') != run:
        raise Abort('JOURNAL_OTHER_RUN')
    entry = {'seq': len(data['entries']) + 1, 'op': op, 'phase': phase,
             'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    entry.update(fields)
    data['entries'].append(entry)
    atomic_json(JOURNAL, data)
    if ENV.test and os.environ.get('NAVER_MIGRATE_TEST_CRASH_AT') == '%s:%s' % (op, phase):
        os._exit(137)   # 시험 전용: 이 저널 지점 직후 프로세스가 죽은 상황


def journal_rename(run, op, src, dst, expect=None):
    journal(run, op, 'intent', src=src, dst=dst, src_identity=lident(src) if expect is None else expect)
    os.rename(ENV.p(src), ENV.p(dst))
    fsync_dir(ENV.data)
    journal(run, op, 'done', src=src, dst=dst, dst_identity=lident(dst))


# ── 제품 불러오기(F6) ──────────────────────────────────────────────────────
def verify_tree(path, kind):
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not (stat.S_ISDIR(st.st_mode) if kind == 'dir' else stat.S_ISREG(st.st_mode)):
        raise Abort('CODE_PATH_REFUSED', path=os.path.relpath(path, ENV.code))
    if not ENV.test and (st.st_uid != 0 or st.st_mode & 0o022 or os.access(path, os.W_OK)):
        raise Abort('CODE_PATH_WRITABLE', path=os.path.relpath(path, ENV.code))


def file_sha(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        return sha_fd(fd)
    finally:
        os.close(fd)


def load_product(pins):
    """고정 경로·권한·해시를 먼저 확인하고 그 두 경로만 sys.path 에 넣는다(-I 는 PYTHONPATH 를 무시한다)."""
    code = ENV.code
    for folder in (code, os.path.join(code, 'naver_engine'), os.path.join(code, 'backend')):
        verify_tree(folder, 'dir')
    wanted = {'naver_engine/store.py': pins['store_sha256']}
    if pins.get('exhaust_sha256'):
        wanted['naver_engine/exhaust_store.py'] = pins['exhaust_sha256']
    for relative, expected in wanted.items():
        full = os.path.join(code, relative)
        verify_tree(full, 'file')
        if file_sha(full) != expected:
            raise Abort('SOURCE_PIN_MISMATCH', file=relative)
    sys.path[0:0] = [code, os.path.join(code, 'backend')]
    if ENV.no_flock:   # macOS 로컬 합성 시험 전용: 제품의 flock 과 SQLite 잠금 간섭을 끈다
        fcntl.flock = lambda *a, **k: None
    from naver_engine import store
    exhaust = None
    if pins.get('exhaust_sha256'):
        from naver_engine import exhaust_store as exhaust
    for module, relative in ((store, 'naver_engine/store.py'), (exhaust, 'naver_engine/exhaust_store.py')):
        if module is None:
            continue
        if os.path.realpath(module.__file__) != os.path.realpath(os.path.join(code, relative)):
            raise Abort('IMPORT_PATH_MISMATCH', file=relative)
    for relative, expected in wanted.items():
        if file_sha(os.path.join(code, relative)) != expected:
            raise Abort('SOURCE_CHANGED_AFTER_IMPORT', file=relative)
    if getattr(store, 'SCHEMA_VERSION', None) != pins['schema']:
        raise Abort('SCHEMA_VERSION_MISMATCH')
    return store, exhaust


# ── SQLite 읽기 ────────────────────────────────────────────────────────────
def q(name):
    return '"' + name.replace('"', '""') + '"'


def ro(path, immutable=False):
    uri = 'file:' + path + ('?mode=ro&immutable=1' if immutable else '?mode=ro')
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.execute('PRAGMA query_only=1')
    conn.execute('PRAGMA trusted_schema=OFF')
    return conn


def checkpoint(path):
    """정지·잠금 아래에서 WAL 을 본문으로 옮긴다. busy 가 아니고 WAL 이 비어야 성공."""
    conn = sqlite3.connect(path, isolation_level=None, timeout=5)
    try:
        busy, _, _ = conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
        conn.execute('BEGIN EXCLUSIVE')
        conn.execute('ROLLBACK')
    finally:
        conn.close()
    return busy == 0 and str(mode).lower() == 'wal'


def wal_header(path):
    """파일 머리의 쓰기/읽기 판(18·19 바이트)이 2 면 WAL 모드 파일이다(immutable 연결은 journal_mode 를 보여주지 않는다)."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        head = os.read(fd, 100)
    finally:
        os.close(fd)
    return len(head) == 100 and head[:16] == b'SQLite format 3\x00' and head[18] == 2 and head[19] == 2


def master(conn):
    return sorted(tuple(r) for r in conn.execute('SELECT type, name, tbl_name, sql FROM sqlite_master'))


def table_key(conn, name, sql):
    if (sql or '').upper().lstrip().startswith('CREATE VIRTUAL'):
        raise Abort('VIRTUAL_TABLE_REFUSED')
    rows = conn.execute('SELECT * FROM pragma_table_xinfo(?)', (name,)).fetchall()
    columns = [r[1] for r in rows]
    if re.search(r'\bWITHOUT\s+ROWID\b', sql or '', re.IGNORECASE):
        pk = [r[1] for r in sorted((r for r in rows if r[5]), key=lambda r: r[5])]
        if not pk:
            raise Abort('NO_PRIMARY_KEY')
        return ('pk', pk, columns)
    lower = {c.lower() for c in columns}
    for candidate in ROWID_NAMES:
        if candidate not in lower:
            return ('rowid', candidate, columns)
    raise Abort('ROWID_SHADOWED')


def select_rows(conn, name, key):
    kind, which, columns = key
    if kind == 'rowid':
        sql = 'SELECT %s, * FROM %s ORDER BY %s' % (which, q(name), which)
    else:
        sql = 'SELECT * FROM %s ORDER BY %s' % (q(name), ', '.join(q(c) for c in which))
    return conn.execute(sql)


def row_key(key, row):
    kind, which, columns = key
    if kind == 'rowid':
        return (row[0],)
    return tuple(row[columns.index(c)] for c in which)


def row_values(key, row):
    return tuple(row[1:]) if key[0] == 'rowid' else tuple(row)


def typed_equal(a, b):
    if len(a) != len(b):
        return False
    return all(type(x) is type(y) and x == y for x, y in zip(a, b))


def encode(value):
    if value is None:
        return b'N;'
    if type(value) is int:
        return b'I' + str(value).encode() + b';'
    if type(value) is float:
        return b'F' + value.hex().encode() + b';'
    if type(value) is str:
        raw = value.encode('utf-8', 'surrogatepass')
        return b'S' + str(len(raw)).encode() + b':' + raw
    if type(value) is bytes:
        return b'B' + str(len(value)).encode() + b':' + value
    raise Abort('UNKNOWN_VALUE_TYPE')


def row_digest(digest, key_values, values):
    digest.update(b'K' + b''.join(encode(v) for v in key_values) + b'V' + b''.join(encode(v) for v in values) + b'\n')


def tables_of(conn):
    return [(name, sql) for kind, name, _, sql in master(conn) if kind == 'table']


def manifest(conn):
    """표마다 (줄 수, 실제 rowid 또는 PK 묶음 + 모든 칸의 형 포함 sha256)."""
    out = {}
    for name, sql in tables_of(conn):
        key = table_key(conn, name, sql)
        digest, count = hashlib.sha256(), 0
        for row in select_rows(conn, name, key):
            row_digest(digest, row_key(key, row), row_values(key, row))
            count += 1
            if count % 2000 == 0:
                check('manifest')
        out[name] = {'count': count, 'sha256': digest.hexdigest()}
    return out


def meta_schema(conn):
    row = conn.execute('SELECT value FROM %s WHERE key = ?' % META_TABLE, (META_KEY,)).fetchone()
    return None if row is None else row[0]


# ── 검증(F4: 실제 rowid 포함, 허용 차이는 판 번호 한 줄과 orphan 3칸뿐) ─────────────
def expected_new_rows(exhaust, pins):
    """이미지의 SQLite 로 제품 SCHEMA 문장을 빈 :memory: 에 실행해 생기는 sqlite_master 행."""
    conn = sqlite3.connect(':memory:')
    try:
        for statement in exhaust.SCHEMA:
            conn.execute(statement)
        rows = master(conn)
    finally:
        conn.close()
    tables = {r[1]: r for r in rows if r[0] == 'table'}
    if set(tables) != set(pins['new_tables']):
        raise Abort('NEW_TABLE_SET_MISMATCH')
    for name, row in tables.items():
        if hashlib.sha256(row[3].encode()).hexdigest() != pins['new_tables'][name]:
            raise Abort('NEW_TABLE_SQL_PIN_MISMATCH', table=name)
    indexes = {r[1] for r in rows if r[0] == 'index'}
    if indexes != set(pins['autoindexes']):
        raise Abort('AUTOINDEX_SET_MISMATCH')
    return set(rows)


def verify(orig, work, exhaust, pins, orphans, window):
    if work.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise Abort('INTEGRITY_WORK')
    if orig.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
        raise Abort('INTEGRITY_ORIGINAL')
    m_orig, m_work = set(master(orig)), set(master(work))
    if not m_orig <= m_work:
        raise Abort('SCHEMA_ROW_REMOVED_OR_CHANGED')
    added = m_work - m_orig
    expected = expected_new_rows(exhaust, pins)
    if added != expected:
        raise Abort('SCHEMA_DELTA_MISMATCH', added=len(added), expected=len(expected))
    for pragma in ('page_size', 'user_version', 'application_id', 'encoding'):
        if orig.execute('PRAGMA ' + pragma).fetchone() != work.execute('PRAGMA ' + pragma).fetchone():
            raise Abort('PRAGMA_DIFFERS', pragma=pragma)
    orphan_set, closed = set(orphans), 0
    for name, sql in tables_of(orig):
        key = table_key(orig, name, sql)
        if table_key(work, name, sql) != key:
            raise Abort('TABLE_SHAPE_DIFFERS', table=name)
        columns = key[2]
        a, b = select_rows(orig, name, key), select_rows(work, name, key)
        count = 0
        while True:
            ra, rb = a.fetchone(), b.fetchone()
            if ra is None and rb is None:
                break
            if ra is None or rb is None:
                raise Abort('ROW_COUNT_DIFFERS', table=name)
            count += 1
            if count % 2000 == 0:
                check('verify')
            ka, kb = row_key(key, ra), row_key(key, rb)
            if not typed_equal(ka, kb):
                raise Abort('ROW_KEY_DIFFERS', table=name)
            va, vb = row_values(key, ra), row_values(key, rb)
            if typed_equal(va, vb):
                if name == RUN_TABLE and key[0] == 'rowid' and ka[0] in orphan_set:
                    raise Abort('ORPHAN_NOT_CLOSED')
                continue
            if name == META_TABLE and va[columns.index('key')] == META_KEY:
                expect = list(va)
                expect[columns.index('value')] = str(pins['schema'])
                if va[columns.index('value')] != str(pins['from_schema']) or not typed_equal(tuple(expect), vb):
                    raise Abort('META_CHANGE_UNEXPECTED')
                continue
            if name == RUN_TABLE and key[0] == 'rowid' and ka[0] in orphan_set:
                expect = list(va)
                index = {c: columns.index(c) for c in ORPHAN_COLUMNS}
                expect[index['status']] = 'failed'
                expect[index['error_kind']] = 'orphaned'
                expect[index['finished_at']] = vb[index['finished_at']]
                stamp = vb[index['finished_at']]
                if (va[index['status']] != 'running' or not typed_equal(tuple(expect), vb)
                        or not isinstance(stamp, str) or not ISO_KST.match(stamp)
                        or not window[0] <= stamp[:19] <= window[1]):
                    raise Abort('ORPHAN_CHANGE_UNEXPECTED')
                closed += 1
                continue
            raise Abort('ROW_VALUE_DIFFERS', table=name)
        check('verify-table')
    if closed != len(orphan_set):
        raise Abort('ORPHAN_COUNT_MISMATCH')
    for name in pins['new_tables']:
        if work.execute('SELECT COUNT(*) FROM %s' % q(name)).fetchone()[0] != 0:
            raise Abort('NEW_TABLE_NOT_EMPTY', table=name)
    return closed


# ── 단계: chain(사본 이관과 교체 — 원본 잠금을 한 프로세스가 끝까지 쥔다) ─────────────
def kst_now():
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time() + 9 * 3600))


def leftovers():
    found = []
    for name in sorted(os.listdir(ENV.data)):
        if name in (PARTIAL, WORK, PRE, JOURNAL, RECEIPT) or name.startswith((PARTIAL, WORK, PRE)) \
                or BUNDLE_RE.match(name) or name.startswith('engine.db.restore'):
            found.append(name)
    return found


def step_chain(args):
    run = args['run']
    pins = args['pins']
    FLOOR[0] = int(args['floor_bytes'])
    DEADLINE[0] = time.monotonic() + CHAIN_DEADLINE
    ENV.check_marker()
    if leftovers():
        raise Abort('LEFTOVERS', names=len(leftovers()))
    store, exhaust = load_product(pins)
    source = open_locked(CANON)                     # 이 fd 가 끝까지 원본 잠금을 쥔다(§C)
    try:
        journal(run, 'chain', 'start')
        if not checkpoint(ENV.p(CANON)):
            raise Abort('CHECKPOINT_BUSY_OR_NOT_WAL')
        sides = sides_of(CANON)
        if sides.get('-journal') is not None or sides.get('-wal', 0) != 0:
            raise Abort('SOURCE_WAL_NOT_EMPTY')
        journal(run, 'source_sides', 'intent', sides=sorted(sides))
        for suffix in ('-wal', '-shm'):
            if suffix in sides:
                os.unlink(ENV.p(CANON + suffix))
        fsync_dir(ENV.data)
        journal(run, 'source_sides', 'done')
        pre_identity = ident(os.fstat(source))
        if not same_full(pre_identity, lident(CANON)):
            raise Abort('IDENTITY_CHANGED', name=CANON)
        size = pre_identity['size']
        FLOOR[0] = int(args['floor_bytes'])
        if free_bytes() < size + 16 * MIB + FLOOR[0]:
            raise Abort('SPACE_G1')
        pre_sha = sha_fd(source)
        # 사본: 같은 fd 를 처음부터 읽으며 해시, O_EXCL·0600 새 파일에 쓰고 fsync, 새 fd 로 다시 해시.
        out = os.open(ENV.p(PARTIAL), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        digest, written = hashlib.sha256(), 0
        try:
            os.lseek(source, 0, os.SEEK_SET)
            while True:
                chunk = os.read(source, CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    view = view[os.write(out, view):]
                written += len(chunk)
                if written % (256 * MIB) < CHUNK:
                    check('copy')
            os.fsync(out)
        finally:
            os.close(out)
        if digest.hexdigest() != pre_sha or written != size:
            raise Abort('COPY_HASH_MISMATCH')
        check_fd = os.open(ENV.p(PARTIAL), os.O_RDONLY | os.O_NOFOLLOW)
        try:
            if sha_fd(check_fd) != pre_sha:
                raise Abort('COPY_REHASH_MISMATCH')
        finally:
            os.close(check_fd)
        if not same_full(ident(os.fstat(source)), pre_identity):
            raise Abort('SOURCE_CHANGED_DURING_COPY')
        journal_rename(run, 'partial_to_work', PARTIAL, WORK)
        # orphan 회차 고정 — 원본은 단일 파일·잠금 아래라 immutable 읽기가 정확하다(엔진 기동 뒤에는 쓰지 않는다).
        conn = ro(ENV.p(CANON), immutable=True)
        try:
            has_runs = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                    (RUN_TABLE,)).fetchone()
            orphans = [r[0] for r in conn.execute(
                "SELECT rowid FROM %s WHERE status = 'running' ORDER BY rowid" % RUN_TABLE)] if has_runs else []
            if meta_schema(conn) != str(pins['from_schema']):
                raise Abort('SOURCE_SCHEMA_NOT_FROM')
        finally:
            conn.close()
        window_start = kst_now()
        writer = store.open_writer(ENV.p(WORK))     # 엔진 자신의 이관 경로(사본에만)
        writer.close()
        window_end = kst_now()
        work_fd = open_locked(WORK)
        try:
            if not checkpoint(ENV.p(WORK)):
                raise Abort('WORK_CHECKPOINT_BUSY')
            wsides = sides_of(WORK)
            if wsides.get('-journal') is not None or wsides.get('-wal', 0) != 0:
                raise Abort('WORK_WAL_NOT_EMPTY')
            for suffix in ('-wal', '-shm'):
                if suffix in wsides:
                    os.unlink(ENV.p(WORK + suffix))
            fsync_dir(ENV.data)
            orig, work = ro(ENV.p(CANON), immutable=True), ro(ENV.p(WORK), immutable=True)
            try:
                closed = verify(orig, work, exhaust, pins, orphans, (window_start, window_end))
                post = manifest(work)
                if not wal_header(ENV.p(WORK)):
                    raise Abort('JOURNAL_MODE')
            finally:
                orig.close()
                work.close()
            work_identity = ident(os.fstat(work_fd))
            work_sha = sha_fd(work_fd)
            if not same_full(work_identity, lident(WORK)):
                raise Abort('IDENTITY_CHANGED', name=WORK)
        finally:
            os.close(work_fd)
        if sha_fd(source) != pre_sha or not same_full(ident(os.fstat(source)), pre_identity):
            raise Abort('SOURCE_CHANGED_DURING_VERIFY')
        receipt = {'version': 1, 'run': run, 'migration_id': args['migration_id'], 'mode': ENV.as_mode,
                   'pre_identity': pre_identity, 'pre_sha256': pre_sha, 'work_identity': work_identity,
                   'work_sha256': work_sha, 'orphans_closed': closed, 'orphan_rowids': orphans,
                   'post_manifest': post, 'sqlite_version': sqlite3.sqlite_version,
                   'migrate_window_kst': [window_start, window_end]}
        atomic_json(RECEIPT, receipt)
        # 교체(단일 파일 상태에서만): rename1 → rename2. rename2 실패면 rename1 을 그 자리에서 되돌린다.
        if sides_of(CANON) or sides_of(WORK):
            raise Abort('SIDECARS_BEFORE_SWAP')
        journal_rename(run, 'rename1', CANON, PRE, expect=pre_identity)
        try:
            journal_rename(run, 'rename2', WORK, CANON, expect=work_identity)
        except BaseException:
            if not os.path.lexists(ENV.p(CANON)):
                journal_rename(run, 'undo_rename1', PRE, CANON, expect=pre_identity)
            raise
        if not same_full(lident(CANON), work_identity) or not same_full(lident(PRE), pre_identity) \
                or not same_inode(ident(os.fstat(source)), lident(PRE)):
            raise Abort('POST_SWAP_IDENTITY')
        journal(run, 'chain', 'done')
        return {'receipt_sha256': hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest(),
                'orphans_closed': closed, 'pre_size': size, 'tables': len(post)}
    finally:
        os.close(source)


# ── 단계: observe / startcheck / prove / gap / undo / bundle / restore-rename ─────────────
def step_observe(args):
    names = [n for n in sorted(os.listdir(ENV.data))
             if n.startswith('engine.db') or n in (JOURNAL, RECEIPT, MARKER)]
    out = {}
    for name in names:
        st = os.lstat(ENV.p(name))
        out[name] = ident(st) if stat.S_ISREG(st.st_mode) else {'kind': 'dir' if stat.S_ISDIR(st.st_mode) else 'other'}
    entries = (read_json(JOURNAL) or {}).get('entries') or []
    return {'files': out, 'journal_last': entries[-1] if entries else None,
            'journal_ops': [[e['op'], e['phase']] for e in entries]}


def step_startcheck(args):
    """guarded_start 2단계: 잠금·기대 identity·(필요하면) 전체 sha·곁 파일·판 번호(WAL 포함 읽기)."""
    ENV.check_marker()
    expect = args['expect_identity']
    fd = open_locked(CANON, expect, full=args.get('full', True))
    try:
        sides = sides_of(CANON)
        if sides.get('-journal') is not None or sides.get('-wal', 0) != 0:
            raise Abort('FOREIGN_OR_LIVE_SIDECARS')
        if args.get('expect_sha256') and sha_fd(fd) != args['expect_sha256']:
            raise Abort('START_SHA_MISMATCH')
        conn = ro(ENV.p(CANON))
        try:
            schema = meta_schema(conn)
        finally:
            conn.close()
        if schema != str(args['expect_schema']):
            raise Abort('START_SCHEMA_MISMATCH')
        # 읽기 연결이 남긴 -shm 은 지운다(같은 세대의 빈 WAL 만 있을 수 있다).
        for suffix in ('-wal', '-shm'):
            if os.path.lexists(ENV.p(CANON + suffix)) and (suffix == '-shm' or os.lstat(ENV.p(CANON + suffix)).st_size == 0):
                os.unlink(ENV.p(CANON + suffix))
        return {'schema': int(schema), 'identity': ident(os.fstat(fd))}
    finally:
        os.close(fd)


def step_prove(args):
    """엔진이 한 번이라도 돌았을 수 있는 v22 세대: 새 쓰기 여부(F2). 잠금 실패·checkpoint 실패는 unknown."""
    receipt = args['receipt']
    try:
        fd = open_locked(CANON)
    except Abort as error:
        if error.code == 'LOCK_BUSY':
            return {'decision': 'unknown', 'reason': 'LOCK_BUSY'}
        raise
    try:
        if not same_inode(ident(os.fstat(fd)), receipt['work_identity']):
            return {'decision': 'unknown', 'reason': 'NOT_V22_WORK_INODE'}
        try:
            ok = checkpoint(ENV.p(CANON))
        except sqlite3.Error:
            ok = False
        conn = ro(ENV.p(CANON))          # WAL 포함 정상 읽기(immutable 금지)
        try:
            now = manifest(conn)
        finally:
            conn.close()
        changed = sorted(t for t in set(now) | set(receipt['post_manifest'])
                         if now.get(t) != receipt['post_manifest'].get(t))
        if not ok:
            return {'decision': 'unknown', 'reason': 'CHECKPOINT_FAILED', 'changed_tables': len(changed)}
        sides = sides_of(CANON)
        if sides.get('-wal', 0) != 0 or sides.get('-journal') is not None:
            return {'decision': 'unknown', 'reason': 'WAL_NOT_EMPTY', 'changed_tables': len(changed)}
        decision = 'no_new_writes' if not changed else 'new_writes'
        if decision == 'no_new_writes':
            for suffix in ('-wal', '-shm'):
                if os.path.lexists(ENV.p(CANON + suffix)):
                    os.unlink(ENV.p(CANON + suffix))
            fsync_dir(ENV.data)
        return {'decision': decision, 'changed_tables': len(changed)}
    finally:
        os.close(fd)


def sort_key(values):
    rank = {type(None): 0, int: 1, float: 1, str: 2, bytes: 3}
    return tuple((rank[type(v)], v if v is not None else 0) for v in values)


def step_gap(args):
    """기준(옛 v21 또는 v22 사본)과 현재 세대의 표별 추가·변경·제거 수. 값은 내지 않는다."""
    base_name, current_name = args['baseline'], args['current']
    for name in (base_name, current_name):
        if not (name in (CANON, PRE) or (name.startswith('engine.db.failed-v22-') and '/' in name
                                         and BUNDLE_RE.match(name.split('/')[0]) and name.endswith('/engine.db'))):
            raise Abort('GAP_PATH_REFUSED')
    base, current = ro(ENV.p(base_name), immutable=True), ro(ENV.p(current_name))
    try:
        result = {}
        names = {n for n, _ in tables_of(base)} | {n for n, _ in tables_of(current)}
        base_sql, cur_sql = dict(tables_of(base)), dict(tables_of(current))
        for name in sorted(names):
            if name not in base_sql:
                result[name] = {'added': current.execute('SELECT COUNT(*) FROM %s' % q(name)).fetchone()[0],
                                'changed': 0, 'removed': 0, 'table': 'new'}
                continue
            if name not in cur_sql:
                result[name] = {'added': 0, 'changed': 0, 'table': 'missing',
                                'removed': base.execute('SELECT COUNT(*) FROM %s' % q(name)).fetchone()[0]}
                continue
            key = table_key(base, name, base_sql[name])
            a = {row_key(key, r): row_values(key, r) for r in select_rows(base, name, key)}
            b = {row_key(key, r): row_values(key, r) for r in select_rows(current, name, key)}
            counts = {'added': len(set(b) - set(a)), 'removed': len(set(a) - set(b)),
                      'changed': sum(1 for k in set(a) & set(b) if not typed_equal(a[k], b[k]))}
            if any(counts.values()):
                result[name] = counts
        return {'tables_with_changes': len(result), 'gap': result}
    finally:
        base.close()
        current.close()


def step_undo(args):
    """엔진이 한 번도 열지 않았음이 입증된 상태만 되돌린다(호출자가 journal·hold 로 판단). 잠금은 §C."""
    run, receipt = args['run'], args.get('receipt')
    canon, pre, work = lident(CANON), lident(PRE), lident(WORK)
    if receipt is None:
        # 영수증 전 중단: 저널에 rename1 의도가 없고 canonical 이 그대로일 때만 우리 사본(partial/work)을 지운다.
        ops = [(e['op'], e['phase']) for e in (read_json(JOURNAL) or {}).get('entries') or []]
        if ('rename1', 'intent') in ops or canon is None or pre is not None:
            raise Abort('UNKNOWN_STATE_NO_RECEIPT')
        fd = open_locked(CANON)
        try:
            for name in (PARTIAL, WORK):
                for suffix in ('',) + SIDES:
                    if os.path.lexists(ENV.p(name + suffix)):
                        os.unlink(ENV.p(name + suffix))
            fsync_dir(ENV.data)
        finally:
            os.close(fd)
        return {'state': 'pre_in_place_no_receipt'}
    pre_id, work_id = receipt['pre_identity'], receipt['work_identity']
    if same_full(canon, pre_id) and pre is None:
        if work is not None:
            if not same_full(work, work_id):
                raise Abort('UNKNOWN_WORK_FILE')
            os.unlink(ENV.p(WORK))
        for name in (PARTIAL,):
            if lident(name) is not None:
                os.unlink(ENV.p(name))
        fsync_dir(ENV.data)
        return {'state': 'pre_in_place'}
    if canon is None and same_full(pre, pre_id):
        held = [open_locked(PRE, pre_id, full=True)]
        try:
            if work is not None:
                held.append(open_locked(WORK, work_id, full=True))
            journal_rename(run, 'recover_rename1_back', PRE, CANON, expect=pre_id)
            if not same_inode(ident(os.fstat(held[0])), lident(CANON)):
                raise Abort('RECOVERED_INODE_MISMATCH')
        finally:
            for fd in held:
                os.close(fd)
        if work is not None:
            os.unlink(ENV.p(WORK))
            fsync_dir(ENV.data)
        return {'state': 'between_renames_restored'}
    if same_full(canon, work_id) and same_full(pre, pre_id) and work is None:
        if sides_of(CANON):
            raise Abort('SIDECARS_PRESENT_MAYBE_STARTED')
        held = [open_locked(CANON, work_id, full=True), open_locked(PRE, pre_id, full=True)]
        try:
            if args.get('verify_sha', True):
                if sha_fd(held[0]) != receipt['work_sha256'] or sha_fd(held[1]) != receipt['pre_sha256']:
                    raise Abort('UNDO_SHA_MISMATCH')
            journal_rename(run, 'undo_swap_v22_aside', CANON, WORK, expect=work_id)
            journal_rename(run, 'undo_swap_pre_back', PRE, CANON, expect=pre_id)
            if not same_inode(ident(os.fstat(held[1])), lident(CANON)):
                raise Abort('RECOVERED_INODE_MISMATCH')
        finally:
            for fd in held:
                os.close(fd)
        os.unlink(ENV.p(WORK))
        fsync_dir(ENV.data)
        return {'state': 'swapped_unstarted_restored'}
    raise Abort('UNKNOWN_STATE')


def step_bundle(args):
    """v22 세대(본문+WAL+SHM)를 같은 세대 묶음 폴더로 옮긴다. 옛 본문이 남의 WAL 옆에 놓이지 않게."""
    run, stamp = args['run'], args['stamp']
    name = 'engine.db.failed-v22-%s.d' % stamp
    if not BUNDLE_RE.match(name):
        raise Abort('BAD_STAMP')
    fd = open_locked(CANON, args['receipt']['work_identity'])
    try:
        os.mkdir(ENV.p(name), 0o700)
        fsync_dir(ENV.data)
        moved = []
        for suffix in ('-wal', '-shm', ''):
            source = CANON + suffix
            if os.path.lexists(ENV.p(source)):
                journal_rename(run, 'bundle' + (suffix or '-main'), source, name + '/' + source)
                fsync_dir(ENV.p(name))
                moved.append(suffix or 'main')
        if not same_inode(ident(os.fstat(fd)), ident(os.lstat(ENV.p(name + '/' + CANON)))):
            raise Abort('BUNDLE_INODE_MISMATCH')
        return {'bundle': name, 'moved': moved}
    finally:
        os.close(fd)


def step_restore_rename(args):
    """raw 원본(pre-v22)을 canonical 로 되돌린다. canonical·곁 파일이 없어야 한다. pre inode 를 잠그고 확인."""
    run, receipt = args['run'], args['receipt']
    if os.path.lexists(ENV.p(CANON)) or sides_of(CANON):
        raise Abort('CANONICAL_PRESENT')
    fd = open_locked(PRE, receipt['pre_identity'], full=True)
    try:
        if sha_fd(fd) != receipt['pre_sha256']:
            raise Abort('PRE_SHA_MISMATCH')
        journal_rename(run, 'restore_pre', PRE, CANON, expect=receipt['pre_identity'])
        if not same_inode(ident(os.fstat(fd)), lident(CANON)):
            raise Abort('RESTORED_INODE_MISMATCH')
        return {'restored_identity': lident(CANON)}
    finally:
        os.close(fd)


# ── 단계: 리허설 전용(scratch 표지가 있어야만) ─────────────────────────────────────
def step_probe(args):
    """이미지 안 SQLite 버전과 PR36 이 쓰는 기능(octet_length 등)·제품 import 확인. DB 를 열지 않는다."""
    store, _ = load_product(args['pins'])
    conn = sqlite3.connect(':memory:')
    try:
        features = {}
        for name, sql in (('octet_length', "SELECT octet_length('x')"), ('json', "SELECT json('{}')"),
                          ('json_extract', "SELECT json_extract('{\"a\":1}', '$.a')"),
                          ('returning', 'CREATE TABLE t(a); INSERT INTO t VALUES (1) RETURNING a')):
            try:
                if ';' in sql:
                    first, second = sql.split(';', 1)
                    conn.execute(first)
                    conn.execute(second).fetchall()
                else:
                    conn.execute(sql).fetchall()
                features[name] = True
            except sqlite3.Error:
                features[name] = False
    finally:
        conn.close()
    return {'sqlite_version': sqlite3.sqlite_version, 'features': features, 'schema': store.SCHEMA_VERSION}


def require_rehearsal():
    if ENV.as_mode != 'rehearsal':
        raise Abort('REHEARSAL_ONLY')
    ENV.check_marker()


def step_seed(args):
    """합성 v21 DB: 옛 이미지의 open_writer 로 만들고, 표마다 형에 맞춘 합성 행·rowid 틈·running 회차를 넣는다."""
    require_rehearsal()
    if os.path.lexists(ENV.p(CANON)):
        raise Abort('SEED_TARGET_EXISTS')
    store, _ = load_product(args['pins'])
    store.open_writer(ENV.p(CANON)).close()
    conn = sqlite3.connect(ENV.p(CANON), isolation_level=None)
    seeded, skipped = 0, 0
    try:
        for name, sql in tables_of(conn):
            if name.startswith('sqlite_'):
                continue
            columns = conn.execute('SELECT name, type, "notnull", dflt_value, pk FROM pragma_table_info(?)',
                                   (name,)).fetchall()
            ok = False
            for attempt in range(3):
                values = []
                for column, declared, notnull, default, pk in columns:
                    kind = (declared or '').upper()
                    if 'INT' in kind:
                        values.append(1000 + attempt * 97 + pk)
                    elif any(t in kind for t in ('REAL', 'FLOA', 'DOUB')):
                        values.append(1.5 + attempt)
                    elif 'BLOB' in kind:
                        values.append(b'\x00synthetic' + bytes([attempt]))
                    else:
                        values.append(['synthetic', '0', '2026-11-01', 'running', 'verified'][attempt % 5] + str(attempt)
                                      if not pk else 'k-%d' % attempt)
                try:
                    conn.execute('INSERT INTO %s (%s) VALUES (%s)' % (
                        q(name), ', '.join(q(c[0]) for c in columns), ', '.join('?' * len(columns))), values)
                    ok = True
                except sqlite3.Error:
                    continue
            seeded += ok
            skipped += not ok
        conn.execute('CREATE TABLE rehearsal_text_pk (k TEXT PRIMARY KEY, v BLOB, n REAL)')
        conn.execute("INSERT INTO rehearsal_text_pk (rowid, k, v, n) VALUES (101, 'a', x'00ff', 1.0)")
        conn.execute("INSERT INTO rehearsal_text_pk (rowid, k, v, n) VALUES (7, 'b', NULL, 2)")
        conn.execute('CREATE TABLE rehearsal_without_rowid (a TEXT, b INTEGER, c, PRIMARY KEY (a, b)) WITHOUT ROWID')
        conn.execute("INSERT INTO rehearsal_without_rowid VALUES ('x', 1, 3.25), ('x', 2, x'01')")
        has_runs = conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (RUN_TABLE,)).fetchone()
        if has_runs:
            conn.execute("INSERT INTO %s (run_date, started_at, status) VALUES ('2026-11-15', "
                         "'2026-11-15T10:00:00+09:00', 'running')" % RUN_TABLE)
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:
        conn.close()
    return {'tables_seeded': seeded, 'tables_skipped': skipped, 'orphan_seeded': bool(has_runs)}


def step_v21_refuses(args):
    require_rehearsal()
    store, _ = load_product(args['pins'])
    conn = ro(ENV.p(CANON))
    try:
        before = master(conn)
    finally:
        conn.close()
    try:
        store.open_writer(ENV.p(CANON)).close()
    except store.StoreError:
        pass
    else:
        raise Abort('OLD_WRITER_ACCEPTED_NEW_FILE')
    conn = ro(ENV.p(CANON))
    try:
        if master(conn) != before or meta_schema(conn) != str(args['expect_schema']):
            raise Abort('OLD_WRITER_CHANGED_FILE')
    finally:
        conn.close()
    return {'refused': True}


def step_v21_opens(args):
    require_rehearsal()
    store, _ = load_product(args['pins'])
    store.open_writer(ENV.p(CANON)).close()
    conn = ro(ENV.p(CANON))
    try:
        if meta_schema(conn) != str(args['expect_schema']):
            raise Abort('RESTORED_SCHEMA_MISMATCH')
    finally:
        conn.close()
    return {'opened': True}


STEPS = {'chain': step_chain, 'observe': step_observe, 'startcheck': step_startcheck, 'prove': step_prove,
         'gap': step_gap, 'undo': step_undo, 'bundle': step_bundle, 'restore-rename': step_restore_rename,
         'probe': step_probe, 'seed': step_seed, 'v21-refuses': step_v21_refuses, 'v21-opens': step_v21_opens}


def main(argv):
    global ENV
    if len(argv) != 3 or argv[1] not in STEPS:
        print(json.dumps({'ok': False, 'code': 'USAGE'}))
        return 2
    step = argv[1]
    try:
        args = json.loads(argv[2])
        if not isinstance(args, dict):
            raise ValueError
        ENV = Env(args.get('mode'), args.get('as_mode'))
        if 'run' in args and not RUN_ID.match(str(args['run'])):
            raise Abort('BAD_RUN_ID')
        result = STEPS[step](args)
        print(json.dumps({'ok': True, 'step': step, 'result': result}, sort_keys=True))
        return 0
    except Abort as error:
        extra = {k: v for k, v in error.extra.items() if isinstance(v, (int, str)) and len(str(v)) < 80}
        print(json.dumps({'ok': False, 'step': step, 'code': error.code, 'detail': extra}, sort_keys=True))
        return 3
    except (ValueError, KeyError, TypeError):
        print(json.dumps({'ok': False, 'step': step, 'code': 'BAD_ARGS'}))
        return 3
    except Exception as error:   # 값·경로를 싣지 않는다
        print(json.dumps({'ok': False, 'step': step, 'code': 'UNEXPECTED', 'type': type(error).__name__}))
        return 4


if __name__ == '__main__':
    sys.exit(main(sys.argv))
