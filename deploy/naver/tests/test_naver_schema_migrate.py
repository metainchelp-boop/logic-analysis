"""naver_schema_migrate.py(컨테이너 helper)와 naver-deploy.sh PY_HELPER 이관 함수의 단위 시험 — 실제 SQLite, 합성 제품.

값은 모두 합성이다. 실제 제품·서버·DB 를 쓰지 않는다. flock 이 SQLite 잠금과 간섭하는 macOS 에서는 helper 의
시험 전용 NAVER_MIGRATE_TEST_NO_FLOCK 로 잠금 자체만 끄고, 잠금 경합 시험은 Linux 에서만 돈다.
"""
import fcntl
import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if os.environ.get('NAVER_MIGRATE_TESTS_SEPARATE') == '1':
    raise unittest.SkipTest('migrate-tests 작업이 따로 돌린다(naver-tools-check.yml)')
sys.path.insert(0, HERE)
import migrate_fixtures as F  # noqa: E402

HELPER = os.path.join(os.path.dirname(HERE), 'naver_schema_migrate.py')
SCRIPT = os.path.join(os.path.dirname(HERE), 'naver-deploy.sh')
NO_FLOCK = sys.platform == 'darwin'
RUN = '20261115T010101Z-' + 'b' * 12
LINUX_ONLY = unittest.skipIf(NO_FLOCK, 'flock 경합은 Linux 에서만 SQLite 잠금과 독립이다')


def load_helper():
    spec = importlib.util.spec_from_file_location('naver_schema_migrate_under_test', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def file_sha(path):
    with open(path, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def py_helper_code():
    with open(SCRIPT) as handle:
        text = handle.read()
    start = text.index("PY_HELPER=$(cat <<'PYEOF'\n") + len("PY_HELPER=$(cat <<'PYEOF'\n")
    return text[start:text.index('\nPYEOF\n)')]


class HelperBase(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='naver-migrate-unit-')
        self.data = os.path.join(self.base, 'data')
        os.mkdir(self.data, 0o700)
        self.v21 = F.make_product(os.path.join(self.base, 'v21'), 21)
        self.v22 = F.make_product(os.path.join(self.base, 'v22'), 22)
        entry = F.entry(self.v21, self.v22, 'a' * 40, 'b' * 40, 'x')
        self.pins = {'store_sha256': entry['to_store_sha256'], 'exhaust_sha256': entry['to_exhaust_sha256'],
                     'schema': 22, 'from_schema': 21, 'new_tables': entry['new_tables'],
                     'autoindexes': entry['autoindexes']}
        F.seed_v21(self.p('engine.db'), self.v21, flock_off=NO_FLOCK)

    def tearDown(self):
        shutil.rmtree(self.base)

    def p(self, name):
        return os.path.join(self.data, name)

    def env(self, code=None, **extra):
        env = {'PATH': '/usr/bin:/bin', 'NAVER_MIGRATE_TEST': '1', 'NAVER_MIGRATE_DIR': self.data,
               'NAVER_MIGRATE_CODE_DIR': code or self.v22, 'LANG': 'C'}
        if NO_FLOCK:
            env['NAVER_MIGRATE_TEST_NO_FLOCK'] = '1'
        env.update(extra)
        return env

    def helper(self, step, args, code=None, mode='test', **extra):
        value = dict(args, mode=mode, run=RUN, migration_id='x')
        done = subprocess.run([sys.executable, '-I', '-B', HELPER, step, json.dumps(value)],
                              env=self.env(code, **extra), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        lines = done.stdout.decode().strip().splitlines()
        return done.returncode, (json.loads(lines[-1]) if lines else {}), done.stdout.decode() + done.stderr.decode()

    def chain(self, **extra):
        return self.helper('chain', {'pins': self.pins, 'floor_bytes': 0}, **extra)

    def receipt(self):
        with open(self.p('naver-migrate-receipt.json')) as handle:
            return json.load(handle)


class ChainTest(HelperBase):
    def test_chain_migrates_copy_verifies_and_swaps(self):
        before = file_sha(self.p('engine.db'))
        rc, out, text = self.chain()
        self.assertEqual(rc, 0, text)
        self.assertEqual(out['result']['orphans_closed'], 1)
        self.assertEqual(file_sha(self.p('engine.db.pre-v22')), before, 'original kept byte-identical')
        receipt = self.receipt()
        self.assertEqual(receipt['pre_sha256'], before)
        conn = sqlite3.connect('file:%s?mode=ro' % self.p('engine.db'), uri=True)
        self.assertEqual(conn.execute("SELECT value FROM naver_auto_meta").fetchone()[0], '22')
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 0)
        conn.close()
        with open(self.p('naver-migrate-journal.json')) as handle:
            ops = [(e['op'], e['phase']) for e in json.load(handle)['entries']]
        for wanted in (('rename1', 'intent'), ('rename1', 'done'), ('rename2', 'intent'), ('rename2', 'done')):
            self.assertIn(wanted, ops)
        self.assertLess(ops.index(('rename1', 'intent')), ops.index(('rename2', 'intent')))
        self.assertNotIn('canary-row-value-77', text, 'no row values in output')

    def test_crash_between_renames_then_undo_by_identity(self):
        rc, _, _ = self.chain(NAVER_MIGRATE_TEST_CRASH_AT='rename1:done')
        self.assertEqual(rc, 137)
        self.assertFalse(os.path.lexists(self.p('engine.db')))
        receipt = self.receipt()
        rc, out, text = self.helper('undo', {'receipt': receipt})
        self.assertEqual(rc, 0, text)
        self.assertEqual(out['result']['state'], 'between_renames_restored')
        self.assertEqual(file_sha(self.p('engine.db')), receipt['pre_sha256'])

    def test_unknown_canonical_after_crash_is_refused(self):
        self.chain(NAVER_MIGRATE_TEST_CRASH_AT='rename1:done')
        open(self.p('engine.db'), 'wb').close()      # O_CREAT 로 생긴 빈 파일
        rc, out, _ = self.helper('undo', {'receipt': self.receipt()})
        self.assertEqual(rc, 3)
        self.assertEqual(out['code'], 'UNKNOWN_STATE')
        self.assertTrue(os.path.lexists(self.p('engine.db.pre-v22')))

    def test_undo_without_receipt_only_before_rename(self):
        rc, _, _ = self.chain(NAVER_MIGRATE_TEST_CRASH_AT='partial_to_work:done')
        self.assertEqual(rc, 137)
        os.unlink(self.p('naver-migrate-receipt.json')) if os.path.exists(self.p('naver-migrate-receipt.json')) else None
        rc, out, text = self.helper('undo', {})
        self.assertEqual(rc, 0, text)
        self.assertFalse(os.path.lexists(self.p('engine.db.v22.work')))

    def test_leftovers_refuse_chain(self):
        open(self.p('engine.db.v22.work'), 'wb').close()
        rc, out, _ = self.chain()
        self.assertEqual(out['code'], 'LEFTOVERS')

    def test_rehearsal_marker_both_directions(self):
        rc, out, _ = self.helper('chain', {'pins': self.pins, 'floor_bytes': 0, 'as_mode': 'rehearsal'})
        self.assertEqual(out['code'], 'REHEARSAL_MARKER_MISSING')
        open(self.p('naver-migrate-rehearsal-marker'), 'w').close()
        rc, out, _ = self.chain()
        self.assertEqual(out['code'], 'REHEARSAL_MARKER_IN_PRODUCTION')

    def test_production_mode_refuses_test_overrides(self):
        rc, out, _ = self.helper('observe', {}, mode='production')
        self.assertEqual(out['code'], 'TEST_OVERRIDE_IN_PRODUCTION')

    def test_source_pin_mismatch_and_symlinked_code(self):
        pins = dict(self.pins, store_sha256='0' * 64)
        rc, out, _ = self.helper('chain', {'pins': pins, 'floor_bytes': 0})
        self.assertEqual(out['code'], 'SOURCE_PIN_MISMATCH')
        link = os.path.join(self.base, 'linked')
        os.symlink(self.v22, link)
        rc, out, _ = self.helper('chain', {'pins': self.pins, 'floor_bytes': 0}, code=link)
        self.assertEqual(out['code'], 'CODE_PATH_REFUSED')
        self.assertTrue(os.path.lexists(self.p('engine.db')))

    def test_space_floor_refuses_before_copy(self):
        rc, out, _ = self.helper('chain', {'pins': self.pins, 'floor_bytes': 1 << 60})
        self.assertIn(out['code'], ('SPACE_G1', 'MIN_FREE'))
        self.assertFalse(os.path.lexists(self.p('engine.db.v22.partial')))

    @LINUX_ONLY
    def test_chain_refuses_when_engine_holds_lock(self):
        fd = os.open(self.p('engine.db'), os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            rc, out, _ = self.chain()
            self.assertEqual(out['code'], 'LOCK_BUSY')
        finally:
            os.close(fd)


class ProveGapBundleTest(HelperBase):
    def migrated(self):
        rc, _, text = self.chain()
        self.assertEqual(rc, 0, text)
        return self.receipt()

    def test_wal_only_commit_is_new_writes(self):
        receipt = self.migrated()
        conn = sqlite3.connect(self.p('engine.db'), isolation_level=None)
        conn.execute('PRAGMA wal_autocheckpoint=0')
        conn.execute("INSERT INTO synth_auto (body) VALUES ('after-start')")
        # 커밋은 WAL 에만 있다 — 본문 sha 는 그대로일 수 있다. 연결을 닫지 않고 판정한다(비정상 종료 대역).
        main_sha = file_sha(self.p('engine.db'))
        self.assertEqual(main_sha, receipt['work_sha256'])
        rc, out, text = self.helper('gap', {'baseline': 'engine.db.pre-v22', 'current': 'engine.db'})
        self.assertEqual(rc, 0, text)
        self.assertEqual(out['result']['gap']['synth_auto']['added'], 1)
        conn.close()

    def test_prove_no_writes_and_new_writes(self):
        receipt = self.migrated()
        rc, out, text = self.helper('prove', {'receipt': receipt})
        self.assertEqual(out['result']['decision'], 'no_new_writes', text)
        conn = sqlite3.connect(self.p('engine.db'), isolation_level=None)
        conn.execute("INSERT INTO synth_auto (body) VALUES ('after-start')")
        conn.close()
        rc, out, _ = self.helper('prove', {'receipt': receipt})
        self.assertEqual(out['result']['decision'], 'new_writes')

    @LINUX_ONLY
    def test_prove_lock_busy_is_unknown(self):
        receipt = self.migrated()
        fd = os.open(self.p('engine.db'), os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            rc, out, _ = self.helper('prove', {'receipt': receipt})
            self.assertEqual(out['result']['decision'], 'unknown')
        finally:
            os.close(fd)

    def test_gap_reports_counts_only(self):
        self.migrated()
        conn = sqlite3.connect(self.p('engine.db'), isolation_level=None)
        conn.execute("UPDATE synth_text_pk SET v = 'canary-secret-value' WHERE k = 'a'")
        conn.close()
        rc, out, text = self.helper('gap', {'baseline': 'engine.db.pre-v22', 'current': 'engine.db'})
        self.assertEqual(out['result']['gap']['synth_text_pk']['changed'], 1)
        self.assertNotIn('canary', text)

    def test_bundle_moves_whole_generation(self):
        receipt = self.migrated()
        conn = sqlite3.connect(self.p('engine.db'), isolation_level=None)
        conn.execute('PRAGMA wal_autocheckpoint=0')
        conn.execute("INSERT INTO synth_auto (body) VALUES ('x')")
        conn.close() if not NO_FLOCK else conn.close()
        for name in ('engine.db-wal', 'engine.db-shm'):
            if not os.path.exists(self.p(name)):
                open(self.p(name), 'wb').close()
        rc, out, text = self.helper('bundle', {'receipt': receipt, 'stamp': '20261115T020202Z'})
        self.assertEqual(rc, 0, text)
        bundle = self.p(out['result']['bundle'])
        self.assertEqual(sorted(os.listdir(bundle)), ['engine.db', 'engine.db-shm', 'engine.db-wal'])
        for name in ('engine.db', 'engine.db-wal', 'engine.db-shm'):
            self.assertFalse(os.path.lexists(self.p(name)))
        rc, out, text = self.helper('restore-rename', {'receipt': receipt})
        self.assertEqual(rc, 0, text)
        self.assertEqual(file_sha(self.p('engine.db')), receipt['pre_sha256'])


class VerifyRulesTest(unittest.TestCase):
    """verify() 반례: 실제 rowid·형·값·스키마·판 번호·orphan 3칸 계약."""

    def setUp(self):
        self.m = load_helper()
        self.base = tempfile.mkdtemp(prefix='naver-verify-')
        os.environ['NAVER_MIGRATE_TEST'] = '1'
        os.environ['NAVER_MIGRATE_DIR'] = self.base
        os.environ['NAVER_MIGRATE_CODE_DIR'] = self.base
        self.m.ENV = self.m.Env('test')
        self.m.FLOOR[0] = 0
        self.exhaust = type('X', (), {'SCHEMA': ('CREATE TABLE IF NOT EXISTS n1 (a INTEGER, b TEXT, PRIMARY KEY (a, b))',)})
        conn = sqlite3.connect(':memory:')
        conn.execute(self.exhaust.SCHEMA[0])
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='n1'").fetchone()[0]
        conn.close()
        self.pins = {'new_tables': {'n1': hashlib.sha256(sql.encode()).hexdigest()},
                     'autoindexes': ['sqlite_autoindex_n1_1'], 'schema': 22, 'from_schema': 21}

    def tearDown(self):
        for key in ('NAVER_MIGRATE_TEST', 'NAVER_MIGRATE_DIR', 'NAVER_MIGRATE_CODE_DIR'):
            os.environ.pop(key, None)
        shutil.rmtree(self.base)

    def pair(self, mutate=None, orphan=True):
        orig = sqlite3.connect(':memory:')
        for c in (orig,):
            c.execute('CREATE TABLE naver_auto_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            c.execute("INSERT INTO naver_auto_meta VALUES ('schema_version', '21')")
            c.execute('CREATE TABLE naver_auto_check_run (run_id INTEGER PRIMARY KEY, status TEXT, error_kind TEXT, '
                      'finished_at TEXT)')
            c.execute("INSERT INTO naver_auto_check_run VALUES (5, 'running', NULL, NULL)")
            c.execute('CREATE TABLE t (k TEXT PRIMARY KEY, v)')
            c.execute("INSERT INTO t (rowid, k, v) VALUES (1, 'a', 1)")
            c.execute('CREATE TABLE w (a TEXT, b INTEGER, PRIMARY KEY (a, b)) WITHOUT ROWID')
            c.execute("INSERT INTO w VALUES ('x', 1)")
        work = sqlite3.connect(':memory:')
        for line in orig.iterdump():
            if line.startswith(('BEGIN', 'COMMIT')):
                continue
            work.execute(line)
        work.execute("DELETE FROM t")
        work.execute("INSERT INTO t (rowid, k, v) VALUES (1, 'a', 1)")
        work.execute(self.exhaust.SCHEMA[0])
        work.execute("UPDATE naver_auto_meta SET value = '22'")
        if orphan:
            work.execute("UPDATE naver_auto_check_run SET status='failed', error_kind='orphaned', "
                         "finished_at='2026-11-15T10:00:01.000001+09:00' WHERE run_id = 5")
        if mutate:
            mutate(work)
        return orig, work

    def verify(self, orig, work, orphans=(5,)):
        return self.m.verify(orig, work, self.exhaust, self.pins, list(orphans),
                             ('2026-11-15T10:00:00', '2026-11-15T10:00:02'))

    def assertRefused(self, code, mutate=None, **kw):
        orig, work = self.pair(mutate, **{k: v for k, v in kw.items() if k == 'orphan'})
        with self.assertRaises(self.m.Abort) as caught:
            self.verify(orig, work, **{k: v for k, v in kw.items() if k == 'orphans'})
        self.assertEqual(caught.exception.code, code)

    def test_clean_pair_passes(self):
        orig, work = self.pair()
        self.assertEqual(self.verify(orig, work), 1)

    def test_hidden_rowid_change_is_refused(self):   # Codex 1/101 반례
        self.assertRefused('ROW_KEY_DIFFERS', lambda w: (w.execute('DELETE FROM t'),
                                                          w.execute("INSERT INTO t (rowid, k, v) VALUES (101, 'a', 1)")))

    def test_type_change_is_refused(self):
        self.assertRefused('ROW_VALUE_DIFFERS', lambda w: w.execute("UPDATE t SET v = 1.0"))

    def test_value_change_and_without_rowid_change(self):
        self.assertRefused('ROW_VALUE_DIFFERS', lambda w: w.execute("UPDATE t SET v = 2"))
        self.assertRefused('ROW_KEY_DIFFERS', lambda w: w.execute("UPDATE w SET b = 2"))

    def test_extra_row_in_new_table_refused(self):
        self.assertRefused('NEW_TABLE_NOT_EMPTY', lambda w: w.execute("INSERT INTO n1 VALUES (1, 'x')"))

    def test_schema_delta_and_pragmas(self):
        self.assertRefused('SCHEMA_DELTA_MISMATCH', lambda w: w.execute('CREATE TABLE extra (x)'))
        self.assertRefused('PRAGMA_DIFFERS', lambda w: w.execute('PRAGMA user_version = 3'))
        self.assertRefused('SCHEMA_ROW_REMOVED_OR_CHANGED', lambda w: w.execute('CREATE INDEX ti ON t (v)') and
                           w.execute('DROP INDEX ti') and w.execute('DROP TABLE w'))

    def test_orphan_rules(self):
        self.assertRefused('ORPHAN_CHANGE_UNEXPECTED',
                           lambda w: w.execute("UPDATE naver_auto_check_run SET error_kind = 'other'"))
        self.assertRefused('ORPHAN_NOT_CLOSED', orphan=False)
        self.assertRefused('ORPHAN_COUNT_MISMATCH', orphans=(5, 6))
        self.assertRefused('META_CHANGE_UNEXPECTED',
                           lambda w: w.execute("UPDATE naver_auto_meta SET value = '23'"))

    def test_rowid_shadowing(self):
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE s1 (rowid TEXT, x)')
        conn.execute('CREATE TABLE s3 (rowid TEXT, _rowid_ TEXT, oid TEXT)')
        conn.execute('CREATE TABLE s4 (id INTEGER PRIMARY KEY, x)')
        key = self.m.table_key(conn, 's1', 'CREATE TABLE s1 (rowid TEXT, x)')
        self.assertEqual(key[:2], ('rowid', '_rowid_'))
        with self.assertRaises(self.m.Abort) as caught:
            self.m.table_key(conn, 's3', 'CREATE TABLE s3 (rowid TEXT, _rowid_ TEXT, oid TEXT)')
        self.assertEqual(caught.exception.code, 'ROWID_SHADOWED')
        conn.execute('INSERT INTO s4 VALUES (9, 1)')
        key = self.m.table_key(conn, 's4', 'CREATE TABLE s4 (id INTEGER PRIMARY KEY, x)')
        row = self.m.select_rows(conn, 's4', key).fetchone()
        self.assertEqual(row[0], row[1], 'INTEGER PRIMARY KEY alias equals the real rowid')


class HostHelperTest(unittest.TestCase):
    """naver-deploy.sh PY_HELPER 이관 함수: 엄격 v2 manifest·pin prune·정책 임계치·보관·복원·pin 전이."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='naver-host-')
        self.code = py_helper_code()
        self.code_file = os.path.join(tempfile.mkdtemp(prefix='naver-host-code-'), 'helper.py')
        with open(self.code_file, 'w') as handle:   # 128KiB 인자 상한을 피해 파일로 실행(배포 스크립트는 fd 3)
            handle.write(self.code)

    def tearDown(self):
        shutil.rmtree(self.root)
        shutil.rmtree(os.path.dirname(self.code_file))

    def py(self, *args, **env):
        environment = {'PATH': '/usr/bin:/bin', 'NAVER_DEPLOY_ROOT': self.root, 'LANG': 'C'}
        environment.update(env)
        return subprocess.run([sys.executable, '-I', '-B', self.code_file] + list(args), env=environment,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def make_v2(self, folder, name, pinned, raw=b'raw'):
        path = os.path.join(folder, name)
        os.makedirs(path)
        with gzip.open(os.path.join(path, 'engine.db.gz'), 'wb') as handle:
            handle.write(raw)
        manifest = {'version': 2, 'schema': 21, 'source_commit': 'a' * 40, 'purpose': 'pre-migration-21-22',
                    'pinned': pinned, 'run': name,
                    'files': {'engine.db': {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                                            'stored': 'gzip', 'gz_size': 1,
                                            'gz_sha256': file_sha(os.path.join(path, 'engine.db.gz'))}}}
        with open(os.path.join(path, 'manifest.json'), 'w') as handle:
            json.dump(manifest, handle)
        return path

    def make_v1(self, folder, name):
        path = os.path.join(folder, name)
        os.makedirs(path)
        open(os.path.join(path, 'engine.db'), 'wb').close()
        with open(os.path.join(path, 'manifest.json'), 'w') as handle:
            json.dump({}, handle)

    def test_pinned_v2_survives_prune_and_unpinned_goes(self):
        folder = os.path.join(self.root, 'db')
        self.make_v2(folder, '20261101T000000Z-' + '1' * 12, True)
        self.make_v1(folder, '20261102T000000Z-' + '2' * 12)
        self.make_v2(folder, '20261103T000000Z-' + '3' * 12, False)
        self.make_v1(folder, '20261104T000000Z-' + '4' * 12)
        done = self.py('backup-prune', folder, '1')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(sorted(os.listdir(folder)), ['20261101T000000Z-' + '1' * 12, '20261104T000000Z-' + '4' * 12])

    def test_malformed_v2_refuses_everything(self):
        folder = os.path.join(self.root, 'db')
        bad = self.make_v2(folder, '20261101T000000Z-' + '1' * 12, False)
        self.make_v1(folder, '20261102T000000Z-' + '2' * 12)
        self.make_v1(folder, '20261103T000000Z-' + '3' * 12)
        with open(os.path.join(bad, 'manifest.json'), 'w') as handle:
            json.dump({'version': 2, 'pinned': 'yes'}, handle)
        done = self.py('backup-prune', folder, '1')
        self.assertEqual(done.returncode, 1)
        self.assertIn('BACKUP_SAFETY', done.stdout.decode())
        self.assertEqual(len(os.listdir(folder)), 3)

    def test_prune_list_respects_pins(self):
        os.makedirs(self.root + '/var/lib/metainc/naver-deploy/pins')
        history = os.path.join(self.root, 'history.json')
        commits = [c * 40 for c in '123456']
        with open(history, 'w') as handle:
            json.dump(commits, handle)
        with open(self.root + '/var/lib/metainc/naver-deploy/pins/' + RUN + '.json', 'w') as handle:
            json.dump({'state': 'bound-gz', 'commit': '1' * 40, 'engine_image': 'sha256:' + 'e' * 64,
                       'relay_image': 'sha256:' + 'f' * 64}, handle)
        done = self.py('prune-list', history, '6' * 40, '5' * 40)
        self.assertEqual(done.stdout.decode().split(), ['2' * 40, '3' * 40], 'pinned 1 is kept')

    def test_damaged_pin_refuses_instead_of_dropping_protection(self):   # PR367 T1
        pins = self.root + '/var/lib/metainc/naver-deploy/pins'
        history = os.path.join(self.root, 'history.json')
        with open(history, 'w') as handle:
            json.dump([c * 40 for c in '123456'], handle)
        os.makedirs(os.path.dirname(pins))
        open(pins, 'w').close()                                   # pin 폴더가 일반 파일
        done = self.py('prune-list', history, '6' * 40, '5' * 40)
        self.assertEqual(done.returncode, 1)
        self.assertIn('PIN_LAYOUT', done.stdout.decode())
        os.unlink(pins)
        os.makedirs(pins)
        for broken in ({'state': 'bound-gz', 'commit': '1' * 40, 'engine_image': 'sha256:' + 'e' * 64},
                       {'state': 'bound-gz', 'commit': 'zz', 'engine_image': 'sha256:' + 'e' * 64,
                        'relay_image': 'sha256:' + 'f' * 64}, {'state': 'odd'}):
            with open(pins + '/' + RUN + '.json', 'w') as handle:
                json.dump(broken, handle)
            done = self.py('prune-list', history, '6' * 40, '5' * 40)
            self.assertEqual(done.returncode, 1, broken)
            self.assertNotIn('1' * 40, done.stdout.decode().split())
        os.unlink(pins + '/' + RUN + '.json')
        open(pins + '/stray.txt', 'w').close()
        self.assertEqual(self.py('prune-list', history, '6' * 40, '5' * 40).returncode, 1)

    def test_keep_raw_now_counterexample_recomputed(self):
        # Codex V2-G3 반례 수치(합성): 기동 전 통과 → 부분 gz 가 남은 결과 시점 불통과(1GiB 바닥은 통과).
        data = self.root + '/var/lib/metainc/naver-engine'
        backups = self.root + '/var/backups/metainc/naver-engine'
        os.makedirs(data)
        os.makedirs(backups)
        with open(data + '/engine.db', 'wb') as handle:
            handle.truncate(1600000000)
        zip_path = backups + '/naver-20261115T000000Z-' + 'a' * 32 + '.zip'
        for path in (zip_path, zip_path[:-4] + '.cms'):
            with open(path, 'wb') as handle:
                handle.truncate(250000000)
        before = self.py('mig-keep-raw-now', data, backups, NAVER_DEPLOY_FAKE_FREE_BYTES='3023741824')
        after = self.py('mig-keep-raw-now', data, backups, NAVER_DEPLOY_FAKE_FREE_BYTES='2463741824')
        self.assertEqual(before.stdout.decode().strip(), 'true')
        self.assertEqual(after.stdout.decode().strip(), 'false')
        floor = self.py('mig-guard', data + '=0', NAVER_DEPLOY_FAKE_FREE_BYTES='2463741824')
        self.assertEqual(floor.returncode, 0, 'the 1GiB floor alone still passes')
        os.unlink(zip_path)
        unknown = self.py('mig-keep-raw-now', data, backups, NAVER_DEPLOY_FAKE_FREE_BYTES='9' * 12)
        self.assertEqual(unknown.stdout.decode().strip(), 'unknown')

    def archive_fixture(self):
        data = self.root + '/var/lib/metainc/naver-engine'
        os.makedirs(data)
        raw = os.urandom(4096) + b'\0' * 100000
        with open(data + '/engine.db.pre-v22', 'wb') as handle:
            handle.write(raw)
        info = os.lstat(data + '/engine.db.pre-v22')
        receipt = {'run': RUN, 'pre_sha256': hashlib.sha256(raw).hexdigest(),
                   'pre_identity': {'dev': info.st_dev, 'ino': info.st_ino, 'size': info.st_size,
                                    'mtime_ns': info.st_mtime_ns}}
        folder = self.root + '/var/lib/metainc/naver-deploy/migration/' + RUN
        os.makedirs(folder)
        with open(folder + '/receipt.json', 'w') as handle:
            json.dump(receipt, handle)
        return data, folder + '/receipt.json', raw

    def test_archive_restore_roundtrip_records_restored_identity(self):
        data, receipt_path, raw = self.archive_fixture()
        backups = self.root + '/var/backups/metainc/naver-deploy-db'
        done = self.py('mig-archive', data, backups, RUN, 'a' * 40, receipt_path)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        copy = backups + '/' + RUN
        with open(copy + '/manifest.json') as handle:
            self.assertTrue(json.load(handle)['pinned'])
        self.assertTrue(os.path.exists(data + '/engine.db.pre-v22'), 'archive never deletes raw')
        self.assertEqual(self.py('mig-unlink-pre', data, receipt_path).returncode, 0)
        done = self.py('mig-restore-gz', copy, data, RUN, receipt_path)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        with open(data + '/engine.db', 'rb') as handle:
            self.assertEqual(handle.read(), raw)
        with open(receipt_path) as handle:
            restored = json.load(handle)['restored_identity']
        self.assertEqual(restored['ino'], os.lstat(data + '/engine.db').st_ino)
        done = self.py('mig-restore-gz', copy, data, RUN, receipt_path)
        self.assertEqual(done.returncode, 1, 'canonical present → refused')

    def test_archive_failure_keeps_partial_and_raw(self):
        data, receipt_path, _ = self.archive_fixture()
        backups = self.root + '/var/backups/metainc/naver-deploy-db'
        done = self.py('mig-archive', data, backups, RUN, 'a' * 40, receipt_path, NAVER_DEPLOY_FAKE_ARCHIVE_FAIL='1')
        self.assertEqual(done.returncode, 1)
        self.assertTrue(os.path.isdir(backups + '/' + RUN + '.archive-failed'), 'partial kept for review')
        self.assertFalse(os.path.lexists(backups + '/' + RUN))
        self.assertTrue(os.path.exists(data + '/engine.db.pre-v22'))
        prune = self.py('partial-prune', backups)
        self.assertEqual(prune.returncode, 0)
        self.assertTrue(os.path.isdir(backups + '/' + RUN + '.archive-failed'), 'plain partial-prune ignores it')

    def test_archive_oserror_partial_is_protected_from_common_prune(self):   # PR367 T2
        data, receipt_path, _ = self.archive_fixture()
        backups = self.root + '/var/backups/metainc/naver-deploy-db'
        done = self.py('mig-archive', data, backups, RUN, 'a' * 40, receipt_path,
                       NAVER_DEPLOY_FAKE_ARCHIVE_FAIL='oserror')
        self.assertEqual(done.returncode, 1)
        self.assertFalse(os.path.lexists(backups + '/' + RUN + '.partial'))
        self.assertTrue(os.path.isdir(backups + '/' + RUN + '.archive-failed'))
        done = self.py('mig-archive', data, backups, RUN, 'a' * 40, receipt_path,
                       NAVER_DEPLOY_FAKE_ARCHIVE_FAIL='oserror')
        self.assertTrue(os.path.isdir(backups + '/' + RUN + '.archive-failed-2'), 'second failure kept too')
        # 이름이 .partial 인 채 남은 이관 gzip 부분본(예: 정전)도 공통 partial-prune 이 지우지 않는다.
        stray = backups + '/20261115T030303Z-' + 'd' * 12 + '.partial'
        os.makedirs(stray)
        open(stray + '/engine.db.gz', 'wb').close()
        legacy = backups + '/20261115T040404Z-' + 'e' * 12 + '.partial'
        os.makedirs(legacy)
        open(legacy + '/engine.db', 'wb').close()
        self.assertEqual(self.py('partial-prune', backups).returncode, 0)
        self.assertTrue(os.path.isdir(stray))
        self.assertFalse(os.path.lexists(legacy))

    def test_archive_refuses_changed_raw(self):
        data, receipt_path, _ = self.archive_fixture()
        backups = self.root + '/var/backups/metainc/naver-deploy-db'
        with open(data + '/engine.db.pre-v22', 'r+b') as handle:
            handle.write(b'X')
        done = self.py('mig-archive', data, backups, RUN, 'a' * 40, receipt_path)
        self.assertEqual(done.returncode, 1)
        self.assertIn('ARCHIVE_SOURCE', done.stdout.decode())
        self.assertTrue(os.path.exists(data + '/engine.db.pre-v22'))

    def test_restore_refuses_tampered_gz(self):
        data, receipt_path, _ = self.archive_fixture()
        backups = self.root + '/var/backups/metainc/naver-deploy-db'
        self.assertEqual(self.py('mig-archive', data, backups, RUN, 'a' * 40, receipt_path).returncode, 0)
        os.unlink(data + '/engine.db.pre-v22')
        with open(backups + '/' + RUN + '/engine.db.gz', 'ab') as handle:
            handle.write(b'tamper')
        done = self.py('mig-restore-gz', backups + '/' + RUN, data, RUN, receipt_path)
        self.assertEqual(done.returncode, 1)
        self.assertFalse(os.path.lexists(data + '/engine.db'))

    def test_pin_transitions(self):
        self.assertEqual(self.py('mig-pin', RUN, 'bind-gz').returncode, 1)
        self.assertEqual(self.py('mig-pin', RUN, 'create', 'commit=' + 'a' * 40).returncode, 0)
        self.assertEqual(self.py('mig-pin', RUN, 'check').returncode, 1, 'pending pin is not an R7 source')
        self.assertEqual(self.py('mig-pin', RUN, 'bind-gz').returncode, 1)
        self.assertEqual(self.py('mig-pin', RUN, 'bind-raw').returncode, 0)
        self.assertEqual(self.py('mig-pin', RUN, 'bind-gz').returncode, 0)
        self.assertEqual(self.py('mig-pin', RUN, 'state').stdout.decode().strip(), 'bound-gz')
        self.assertEqual(self.py('mig-pin', RUN, 'release').returncode, 0)

    def test_hold_and_dropins(self):
        os.makedirs(self.root + '/var/lib/metainc/naver-deploy')
        self.assertEqual(self.py('mig-hold', 'create', RUN).returncode, 0)
        other = '20261115T090909Z-' + 'c' * 12
        self.assertEqual(self.py('mig-hold', 'remove', other).returncode, 1, 'other run hold is not removed')
        self.assertEqual(self.py('mig-hold', 'create', other).returncode, 1)
        self.assertEqual(self.py('mig-dropin', 'install').returncode, 0)
        conf = self.root + '/etc/systemd/system/metainc-naver-engine.service.d/50-naver-migration-hold.conf'
        with open(conf) as handle:
            body = handle.read()
        self.assertIn('AssertPathExists=!/var/lib/metainc/naver-deploy/migration-hold', body)
        self.assertIn('AssertPathExists=/var/lib/metainc/naver-engine/engine.db', body)
        with open(conf, 'a') as handle:
            handle.write('# foreign\n')
        self.assertEqual(self.py('mig-dropin', 'remove').returncode, 1, 'foreign drop-in is never deleted')

    def test_helper_hash_literal_matches_file(self):
        namespace = {'os': os, 'json': json, 'ROOT': ''}
        text = self.code
        start = text.index('MIGRATIONS = {')
        exec(text[start:text.index("if ROOT and os.environ.get('NAVER_DEPLOY_TEST_MIGRATIONS')")], namespace)
        entry = namespace['MIGRATIONS']['21-22-exhaust-v1']
        self.assertEqual(entry['helper_sha256'], file_sha(HELPER))
        self.assertEqual(entry['from_commit'], '377768a132614ae8b9ad0318aa4f87019c11a23a')
        self.assertEqual(entry['to_commit'], '1d852289209e7f10df71a787934d9fe31c9ffde6')
        with open(HELPER, 'rb') as handle:
            self.assertNotIn(entry['helper_sha256'].encode(), handle.read(), 'helper holds no self hash')

    def test_tar_pins_refuse_wrong_source(self):
        from test_naver_deploy import make_tar, source_files
        tar = os.path.join(self.root, 's.tar')
        files = source_files('1d852289209e7f10df71a787934d9fe31c9ffde6', 22,
                             {'naver_engine/exhaust_store.py': 'SCHEMA = ()\n'})
        make_tar(tar, files)
        done = self.py('mig-tar-pins', tar, '21-22-exhaust-v1', '377768a132614ae8b9ad0318aa4f87019c11a23a',
                       '1d852289209e7f10df71a787934d9fe31c9ffde6', '21', '22')
        self.assertEqual(done.returncode, 1)
        self.assertIn('MIGRATION_SOURCE_PIN', done.stdout.decode())


if __name__ == '__main__':
    unittest.main()
