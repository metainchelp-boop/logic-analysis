"""이관 시험용 합성 제품(엔진 저장소 대역)과 합성 v21 DB.

실제 제품 소스는 공개 저장소에 넣지 않는다. 이 대역은 실제 store.open_writer 의 이관 계약만 흉내 낸다:
파일 자체 flock(LOCK_EX|LOCK_NB) · WAL · BEGIN IMMEDIATE 안에서 CREATE IF NOT EXISTS 전부 → 판 번호 확인(새 파일이면 거절)
→ 판 번호 올림 → 「돌고 있음」 회차를 failed/orphaned 로 닫음. 새 표 셋은 실제와 이름·SQL 이 다른 합성 표다.
"""
import hashlib
import os
import sqlite3
import sys

STORE_TEMPLATE = '''import fcntl
import os
import sqlite3
from datetime import datetime, timedelta, timezone

SCHEMA_VERSION = %(schema)d
KST = timezone(timedelta(hours=9))


class StoreError(RuntimeError):
    pass


_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS naver_auto_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS naver_auto_check_run (run_id INTEGER PRIMARY KEY, run_date TEXT NOT NULL, "
    "started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, accounts_total INTEGER, accounts_ok INTEGER, "
    "error_kind TEXT)",
    "CREATE TABLE IF NOT EXISTS synth_text_pk (k TEXT PRIMARY KEY, v BLOB, n REAL)",
    "CREATE TABLE IF NOT EXISTS synth_without (a TEXT, b INTEGER, c, PRIMARY KEY (a, b)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS synth_auto (id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT)",
    "CREATE INDEX IF NOT EXISTS synth_auto_body ON synth_auto (body)",
)
%(extra)s


class Store:
    def __init__(self, conn, fd):
        self._conn, self._fd = conn, fd

    def close(self):
        try:
            self._conn.close()
        finally:
            os.close(self._fd)

    def _migrate(self):
        c = self._conn
        c.execute("BEGIN IMMEDIATE")
        try:
            for sql in _SCHEMA:
                c.execute(sql)
            row = c.execute("SELECT value FROM naver_auto_meta WHERE key = 'schema_version'").fetchone()
            have = None if row is None else int(row[0])
            if have is not None and have > SCHEMA_VERSION:
                raise StoreError("newer file")
            if have != SCHEMA_VERSION:
                c.execute("INSERT INTO naver_auto_meta (key, value) VALUES ('schema_version', ?) "
                          "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (str(SCHEMA_VERSION),))
            c.execute("COMMIT")
        except BaseException:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise

    def _close_orphaned_runs(self):
        now = datetime.now(KST).isoformat()
        self._conn.execute("UPDATE naver_auto_check_run SET status = 'failed', finished_at = ?, error_kind = ? "
                           "WHERE status = 'running'", (now, 'orphaned'))


def open_writer(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise StoreError("busy")
    conn = sqlite3.connect(path, isolation_level=None, timeout=5)
    conn.execute("PRAGMA journal_mode = WAL")
    store = Store(conn, fd)
    try:
        store._migrate()
        store._close_orphaned_runs()
    except BaseException:
        store.close()
        raise
    return store
'''

EXHAUST = '''SCHEMA = (
    """CREATE TABLE IF NOT EXISTS synth_new_head (
        customer_id INTEGER NOT NULL, month TEXT NOT NULL, body TEXT NOT NULL,
        PRIMARY KEY (customer_id, month))""",
    """CREATE TABLE IF NOT EXISTS synth_new_version (
        customer_id INTEGER NOT NULL, month TEXT NOT NULL, seq INTEGER NOT NULL,
        PRIMARY KEY (customer_id, month, seq))""",
    """CREATE TABLE IF NOT EXISTS synth_new_attempt (
        customer_id INTEGER NOT NULL, month TEXT NOT NULL, status TEXT NOT NULL,
        PRIMARY KEY (customer_id, month))""",
)
'''
NEW_TABLES = ('synth_new_attempt', 'synth_new_head', 'synth_new_version')


def write(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as handle:
        handle.write(body)


def sha(path):
    with open(path, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def make_product(folder, schema):
    """폴더에 합성 제품(naver_engine/·backend/)을 만든다. v22 는 exhaust_store 를 더한다."""
    extra = ''
    if schema >= 22:
        write(os.path.join(folder, 'naver_engine/exhaust_store.py'), EXHAUST)
        extra = 'from .exhaust_store import SCHEMA as _EXHAUST_SCHEMA\n_SCHEMA += _EXHAUST_SCHEMA\n'
    write(os.path.join(folder, 'naver_engine/__init__.py'), '')
    write(os.path.join(folder, 'naver_engine/store.py'), STORE_TEMPLATE % {'schema': schema, 'extra': extra})
    write(os.path.join(folder, 'backend/__init__.py'), '')
    return folder


def new_table_pins(product_v22):
    sys.path.insert(0, product_v22)
    try:
        namespace = {}
        with open(os.path.join(product_v22, 'naver_engine/exhaust_store.py')) as handle:
            exec(compile(handle.read(), 'x', 'exec'), namespace)
    finally:
        sys.path.remove(product_v22)
    conn = sqlite3.connect(':memory:')
    for statement in namespace['SCHEMA']:
        conn.execute(statement)
    rows = conn.execute('SELECT type, name, sql FROM sqlite_master').fetchall()
    conn.close()
    tables = {name: hashlib.sha256(sql.encode()).hexdigest() for kind, name, sql in rows if kind == 'table'}
    indexes = sorted(name for kind, name, _ in rows if kind == 'index')
    return tables, indexes


def entry(product_v21, product_v22, from_commit, to_commit, helper_sha, from_store_sha=None):
    tables, indexes = new_table_pins(product_v22)
    return {'from_schema': 21, 'to_schema': 22, 'from_commit': from_commit, 'to_commit': to_commit,
            'from_store_sha256': from_store_sha or sha(os.path.join(product_v21, 'naver_engine/store.py')),
            'to_store_sha256': sha(os.path.join(product_v22, 'naver_engine/store.py')),
            'to_exhaust_sha256': sha(os.path.join(product_v22, 'naver_engine/exhaust_store.py')),
            'new_tables': tables, 'autoindexes': indexes, 'helper_sha256': helper_sha}


def load_store(product):
    """합성 제품 store 를 이 프로세스에 불러온다(macOS 에서는 flock 을 끈다 — 로컬 합성 전용)."""
    import importlib.util
    path = os.path.join(product, 'naver_engine/store.py')
    spec = importlib.util.spec_from_file_location('synthetic_store_%s' % hashlib.sha1(product.encode()).hexdigest()[:8],
                                                  path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed_v21(path, product_v21, running=1, flock_off=False):
    """합성 v21 DB: 옛 대역 open_writer 로 만들고 rowid 틈·WITHOUT ROWID·AUTOINCREMENT·running 회차를 넣는다."""
    import fcntl
    original = fcntl.flock
    if flock_off:
        fcntl.flock = lambda *a, **k: None
    try:
        store = load_store(product_v21)
        store.open_writer(path).close()
    finally:
        fcntl.flock = original
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("INSERT INTO synth_text_pk (rowid, k, v, n) VALUES (101, 'a', x'00ff', 1.0)")
    conn.execute("INSERT INTO synth_text_pk (rowid, k, v, n) VALUES (7, 'b', NULL, 2)")
    conn.execute("INSERT INTO synth_text_pk (rowid, k, v, n) VALUES (8, 'canary-row-value-77', 'x', 3)")
    conn.execute("INSERT INTO synth_without VALUES ('x', 1, 3.25), ('x', 2, x'01'), ('y', 1, NULL)")
    for body in ('one', 'two', 'three'):
        conn.execute('INSERT INTO synth_auto (body) VALUES (?)', (body,))
    conn.execute("DELETE FROM synth_auto WHERE body = 'two'")
    conn.execute("INSERT INTO naver_auto_check_run (run_date, started_at, finished_at, status) VALUES "
                 "('2026-11-14', '2026-11-14T10:00:00+09:00', '2026-11-14T10:05:00+09:00', 'ok')")
    for _ in range(running):
        conn.execute("INSERT INTO naver_auto_check_run (run_date, started_at, status) VALUES "
                     "('2026-11-15', '2026-11-15T10:00:00+09:00', 'running')")
    conn.close()
