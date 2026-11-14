"""migrate-* 모드 종단 시험 — 가짜 systemctl/docker/curl 과 실제 helper·실제 SQLite(합성 제품 대역).

서버·제품 비밀값 없이 돈다. 「이미지 안」 helper 는 가짜 docker 가 이미지 커밋에 맞는 합성 제품 폴더로 실행한다.
VM 전용 systemd(실제 부팅·default.target) 시험은 수동 항목이다(docs/naver-simple-deploy.md 의 이관 절).
"""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import migrate_fixtures as F  # noqa: E402
from test_naver_deploy import (C0, C1, COMPANION, RELEASES, FakeHost, result_of, source_files,  # noqa: E402
                               make_tar)

HELPER = os.path.join(os.path.dirname(HERE), 'naver_schema_migrate.py')
DATA = '/var/lib/metainc/naver-engine'
STATE = '/var/lib/metainc/naver-deploy'
MIG_ID = '21-22-exhaust-v1'
NO_FLOCK = sys.platform == 'darwin'
FAKE_OLD_STORE = b'SCHEMA_VERSION = 21   # fake\n'


def kst(hour_minute='10:00'):
    return time.strftime('%Y-%m-%d', time.gmtime(time.time() + 9 * 3600)) + 'T' + hour_minute


def file_sha(path):
    with open(path, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class MigrateHost(FakeHost):
    def __init__(self, base):
        super().__init__(base)
        self.v21 = F.make_product(os.path.join(base, 'product-v21'), 21)
        self.v22 = F.make_product(os.path.join(base, 'product-v22'), 22)
        self.set(product_by_commit={C0: self.v21, C1: self.v22})
        for name in ('engine.db', 'engine.db-wal'):
            os.unlink(self.root + DATA + '/' + name)
        F.seed_v21(self.root + DATA + '/engine.db', self.v21, flock_off=NO_FLOCK)
        self.entry = F.entry(self.v21, self.v22, C0, C1, file_sha(HELPER))
        self.entries_path = os.path.join(base, 'migrations.json')
        self.write_entries()
        self.backup_state()

    def write_entries(self):
        with open(self.entries_path, 'w') as handle:
            json.dump({MIG_ID: self.entry}, handle)

    def backup_state(self, code='OFFSITE_OK', pending=None, day=None, zip_bytes=1000, cms_bytes=1000):
        folder = self.root + '/var/backups/metainc/naver-engine'
        os.makedirs(folder, exist_ok=True)
        with open(folder + '/state.json', 'w') as handle:
            json.dump({'code': code, 'pending': pending, 'last_offsite_day': day or kst()[:10]}, handle)
        name = folder + '/naver-20261115T000000Z-' + 'a' * 32 + '.zip'
        for path, size in ((name, zip_bytes), (name[:-4] + '.cms', cms_bytes)):
            with open(path, 'wb') as handle:
                handle.truncate(size)

    def migrate_tar(self, commit=C1):
        files = source_files(commit, 22)
        with open(os.path.join(self.v22, 'naver_engine/store.py')) as handle:
            files['naver_engine/store.py'] = handle.read()
        with open(os.path.join(self.v22, 'naver_engine/exhaust_store.py')) as handle:
            files['naver_engine/exhaust_store.py'] = handle.read()
        path = os.path.join(self.base, 'migrate-%s.tar' % commit[:8])
        make_tar(path, files)
        return path

    def mrun(self, *args, **env):
        values = {'NAVER_DEPLOY_TEST_MIGRATIONS': self.entries_path, 'NAVER_DEPLOY_FAKE_KST': kst()}
        values.update(env)
        return self.run(*args, **values)

    def prepare(self, **env):
        return self.mrun('migrate-prepare', C1, self.migrate_tar(), MIG_ID, **env)

    def rehearse(self, **env):
        return self.mrun('migrate-rehearse', C1, self.migrate_tar(), MIG_ID, **env)

    def plan(self, **env):
        done = self.mrun('migrate-plan', C1, self.migrate_tar(), MIG_ID, **env)
        return done, result_of(done).get('plan_sha256', '')

    def migrate(self, plan, **env):
        return self.mrun('migrate-deploy', C1, self.migrate_tar(), MIG_ID, plan, **env)

    def ready(self):
        for step in (self.prepare, self.rehearse):
            done = step()
            assert done.returncode == 0, done.stdout.decode()[-3000:]
        done, plan = self.plan()
        assert done.returncode == 0 and plan, done.stdout.decode()[-3000:]
        return plan

    def db(self, name='engine.db'):
        return self.root + DATA + '/' + name

    def meta_schema(self, name='engine.db'):
        conn = sqlite3.connect('file:%s?mode=ro&immutable=1' % self.db(name), uri=True)
        try:
            return conn.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()[0]
        finally:
            conn.close()

    def status(self, run):
        with open(self.root + STATE + '/migration/' + run + '/status.json') as handle:
            return json.load(handle)

    def markers(self):
        return {'pointer': os.path.lexists(self.root + STATE + '/migration-active'),
                'hold': os.path.lexists(self.root + STATE + '/migration-hold'),
                'dropins': any(os.path.lexists(self.root + '/etc/systemd/system/%s.d/50-naver-migration-hold.conf' % u)
                               for u in ('metainc-naver-engine.service', 'metainc-naver-relay.service'))}

    def systemctl(self, *args):
        return subprocess.run([os.path.join(self.bin, 'systemctl')] + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT)


def can_walk_processes():
    if os.path.isdir('/proc/self'):
        return True
    try:
        return subprocess.run(['ps', '-o', 'ppid=', '-p', str(os.getpid())], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


CRASH_SKIP = unittest.skipUnless(can_walk_processes(), '조상 프로세스를 볼 수 없는 환경(/proc·ps 없음)')


class MigrateDeployTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='naver-migrate-test-')
        self.host = MigrateHost(self.base)

    def tearDown(self):
        shutil.rmtree(self.base)

    def out(self, done):
        return done.stdout.decode('utf-8', 'replace')

    def assertExit(self, done, code):
        self.assertEqual(done.returncode, code, self.out(done)[-5000:])

    def index(self, calls, wanted, start=0):
        for number in range(start, len(calls)):
            if calls[number][:len(wanted)] == wanted:
                return number
        self.fail('call not found: %s' % wanted)

    def assert_old_running(self):
        for name in ('engine', 'relay'):
            container = self.host.running('naver-' + name)
            self.assertTrue(container['running'])
            self.assertEqual(container['image'], self.host.old_images[name])
        units = self.host.load_state()['units']
        self.assertEqual(units['metainc-naver-engine.service']['active'], 'active')

    # ── 1. 정상 경로 ──
    def test_prepare_rehearse_plan_migrate_complete(self):
        pre_sha = file_sha(self.host.db())
        plan = self.host.ready()
        self.host.clear_calls()
        done = self.host.migrate(plan)
        self.assertExit(done, 0)
        result = result_of(done)
        self.assertEqual(result['status'], 'MIGRATED')
        self.assertEqual(result['database_opened_by_deploy'], 'true')
        self.assertEqual(result['migration_state'], 'COMPLETED')
        self.assertEqual(result['orphans_closed'], '1')
        self.assertEqual(self.host.meta_schema(), '22')
        self.assertFalse(os.path.lexists(self.host.db('engine.db.pre-v22')), 'raw deleted after G4')
        self.assertEqual(self.host.markers(), {'pointer': False, 'hold': False, 'dropins': False})
        run = result['migration_run']
        self.assertEqual(self.host.status(run)['state'], 'COMPLETED')
        self.assertTrue(os.path.isfile(self.host.root + STATE + '/migration/' + run + '/journal.json'))
        self.assertFalse(os.path.lexists(self.host.db('naver-migrate-journal.json')))
        copy = self.host.root + '/var/backups/metainc/naver-deploy-db/' + run
        self.assertEqual(sorted(os.listdir(copy)), ['engine.db.gz', 'manifest.json'])
        with open(copy + '/manifest.json') as handle:
            manifest = json.load(handle)
        self.assertTrue(manifest['pinned'])
        self.assertEqual(manifest['files']['engine.db']['sha256'], pre_sha)
        with open(self.host.root + STATE + '/pins/' + run + '.json') as handle:
            self.assertEqual(json.load(handle)['state'], 'bound-gz')
        for name in ('engine', 'relay'):
            self.assertIn('metainc/naver-%s:rollback-%s' % (name, run[17:29]), self.host.tags())
        calls = self.host.calls()
        reload_ = self.index(calls, ['systemctl', 'daemon-reload'])
        stop = self.index(calls, ['systemctl', 'stop', 'metainc-naver-engine.service'])
        chain = next(n for n, c in enumerate(calls) if c[:2] == ['docker', 'run'] and 'chain' in c)
        start = self.index(calls, ['systemctl', 'start', 'metainc-naver-engine.service'])
        self.assertTrue(reload_ < stop < chain < start, 'hold+drop-in before stop; chain before start')
        self.assertFalse(any(c[:2] == ['docker', 'build'] for c in calls), 'migrate-deploy never builds')
        units = self.host.load_state()['units']
        self.assertEqual(units['metainc-naver-engine.service']['loaded_dropins'], [])
        with open(self.host.root + STATE + '/migration/prepared-' + C1 + '.json') as handle:
            prepared = json.load(handle)
        self.assertEqual(self.host.running('naver-engine')['image'], prepared['engine_image'])
        self.assertTrue(self.host.running('naver-engine')['running'])

    def test_next_deploy_after_completed_migration_sees_no_hold(self):
        plan = self.host.ready()
        self.assertExit(self.host.migrate(plan), 0)
        self.host.clear_calls()
        done = self.host.run('deploy', C1, self.host.migrate_tar())
        self.assertNotIn('MIGRATION_HOLD', self.out(done))
        self.assertNotIn(['systemctl', 'stop', 'metainc-naver-engine.service'], self.host.calls()[:3])
        self.assertIn('ALREADY_RUNNING', self.out(done))

    # ── 2. 시작 전 거부 ──
    def test_plain_deploy_still_refuses_schema_change_identically(self):
        done = self.host.run('deploy', C1, self.host.migrate_tar())
        self.assertExit(done, 10)
        self.assertIn('실패 사유(SCHEMA_CHANGED): SCHEMA_VERSION 이 21 → 22 로 바뀝니다. 스키마 이관은 이 배포 장치에서 하지 않습니다',
                      self.out(done))

    def test_migrate_refused_without_rehearsal_plan_or_window(self):
        self.assertExit(self.host.prepare(), 0)
        before = file_sha(self.host.db())
        done = self.host.migrate('0' * 64)
        self.assertExit(done, 10)
        self.assertIn('REHEARSAL_MISSING', self.out(done))
        self.assertExit(self.host.rehearse(), 0)
        done = self.host.migrate('0' * 64)
        self.assertExit(done, 10)
        self.assertIn('PLAN_MISMATCH', self.out(done))
        _, plan = self.host.plan()
        done = self.host.migrate(plan, NAVER_DEPLOY_FAKE_KST=kst('21:31'))
        self.assertExit(done, 10)
        self.assertIn('WINDOW', self.out(done))
        self.host.backup_state(pending='upload')
        done = self.host.migrate(plan)
        self.assertExit(done, 10)
        self.assertEqual(file_sha(self.host.db()), before)
        self.assertEqual(self.host.markers(), {'pointer': False, 'hold': False, 'dropins': False})
        self.assert_old_running()

    def test_wrong_pins_refused(self):
        self.host.entry['to_commit'] = 'f' * 40
        self.host.write_entries()
        done = self.host.prepare()
        self.assertExit(done, 10)
        self.assertIn('MIGRATION_COMMIT_PIN', self.out(done))
        self.host.entry['to_commit'] = C1
        self.host.entry['helper_sha256'] = '0' * 64
        self.host.write_entries()
        done = self.host.prepare()
        self.assertExit(done, 10)
        self.assertIn('MIGRATION_HELPER_PIN', self.out(done))

    def test_rehearsal_never_mounts_production_data(self):
        self.assertExit(self.host.prepare(), 0)
        before = file_sha(self.host.db())
        self.host.clear_calls()
        self.assertExit(self.host.rehearse(), 0)
        runs = [c for c in self.host.calls() if c[:2] == ['docker', 'run'] and '/opt/naver-migrate/m.py' in c]
        self.assertTrue(runs)
        for call in runs:
            source = call[call.index('-v') + 1].split(':')[0]
            self.assertIn('/rehearse/', source)
            self.assertNotEqual(source, self.host.root + DATA)
        self.assertEqual(file_sha(self.host.db()), before)

    # ── 3. 실패 → 복귀 ──
    def test_chain_failure_rolls_back_without_touching_original(self):
        plan = self.host.ready()
        before = file_sha(self.host.db())
        self.host.set(helper_fail={'chain': 'INJECTED'})
        done = self.host.migrate(plan)
        self.assertExit(done, 2)
        self.assertEqual(result_of(done)['status'], 'MIGRATION_ROLLED_BACK')
        self.assertEqual(file_sha(self.host.db()), before)
        self.assert_old_running()
        self.assertEqual(self.host.markers(), {'pointer': False, 'hold': False, 'dropins': False})

    def test_health_failure_without_new_writes_rolls_back_and_keeps_v22_bundle(self):
        plan = self.host.ready()
        before = file_sha(self.host.db())
        self.host.set(health_fail=[C1])
        done = self.host.migrate(plan)
        self.assertExit(done, 2)
        self.assertEqual(result_of(done)['write_decision'], 'no_new_writes')
        self.assertEqual(file_sha(self.host.db()), before)
        self.assertEqual(self.host.meta_schema(), '21')
        bundles = [n for n in os.listdir(self.host.root + DATA) if n.startswith('engine.db.failed-v22-')]
        self.assertEqual(len(bundles), 1)
        self.assert_old_running()

    def test_health_failure_with_new_writes_holds_for_owner(self):
        plan = self.host.ready()
        self.host.set(health_fail=[C1], write_on_start={'commit': C1, 'db': self.host.db()})
        done = self.host.migrate(plan)
        self.assertExit(done, 12)
        result = result_of(done)
        self.assertEqual(result['status'], 'MIGRATION_HOLD')
        self.assertEqual(result['write_decision'], 'new_writes')
        self.assertEqual(self.host.meta_schema(), '22')
        self.assertTrue(self.host.markers()['hold'])
        units = self.host.load_state()['units']
        self.assertEqual(units['metainc-naver-engine.service']['active'], 'inactive')
        refused = self.host.systemctl('start', 'metainc-naver-relay.service')
        self.assertNotEqual(refused.returncode, 0, 'hold blocks dependency start')
        self.assertEqual(self.host.load_state()['units']['metainc-naver-engine.service']['active'], 'inactive')

    @CRASH_SKIP
    def test_crash_between_renames_blocks_boot_start_and_recovers_by_identity(self):
        plan = self.host.ready()
        before = file_sha(self.host.db())
        self.host.set(helper_crash_at={'step': 'chain', 'at': 'rename1:done', 'kill_main': True})
        self.host.migrate(plan)
        self.assertFalse(os.path.lexists(self.host.db()), 'canonical absent between renames')
        for unit in ('metainc-naver-engine.service', 'metainc-naver-relay.service'):
            self.assertNotEqual(self.host.systemctl('start', unit).returncode, 0, 'boot/explicit start refused')
        self.assertFalse(os.path.lexists(self.host.db()), 'no empty DB was created')
        self.host.set(helper_crash_at=None)
        done = self.host.run('deploy', C1, self.host.migrate_tar(),
                             NAVER_DEPLOY_TEST_MIGRATIONS=self.host.entries_path, NAVER_DEPLOY_FAKE_KST=kst())
        self.assertExit(done, 3)
        self.assertEqual(file_sha(self.host.db()), before)
        self.assert_old_running()
        self.assertEqual(self.host.markers(), {'pointer': False, 'hold': False, 'dropins': False})

    @CRASH_SKIP
    def test_unknown_canonical_identity_holds_without_renaming(self):
        plan = self.host.ready()
        self.host.set(helper_crash_at={'step': 'chain', 'at': 'rename1:done', 'kill_main': True})
        self.host.migrate(plan)
        with open(self.host.db(), 'wb') as handle:      # 어떤 writer 가 O_CREAT 로 만든 빈 파일
            handle.write(b'')
        self.host.set(helper_crash_at=None)
        done = self.host.run('deploy', C1, self.host.migrate_tar(),
                             NAVER_DEPLOY_TEST_MIGRATIONS=self.host.entries_path, NAVER_DEPLOY_FAKE_KST=kst())
        self.assertIn(done.returncode, (4, 12), self.out(done)[-3000:])
        self.assertTrue(os.path.lexists(self.host.db('engine.db.pre-v22')), 'pre-v22 kept, nothing renamed')
        self.assertTrue(self.host.markers()['hold'])

    def test_crash_after_start_intent_is_potential_start(self):
        plan = self.host.ready()
        self.host.set(kill_after='start metainc-naver-engine.service')
        self.host.migrate(plan)
        self.host.set(kill_after=None)
        os.unlink(self.host.root + STATE + '/migration-hold') if os.path.exists(self.host.root + STATE + '/migration-hold') else None
        done = self.host.run('deploy', C1, self.host.migrate_tar(),
                             NAVER_DEPLOY_TEST_MIGRATIONS=self.host.entries_path, NAVER_DEPLOY_FAKE_KST=kst())
        self.assertExit(done, 3)
        self.assertIn('관측 기록', self.out(done))
        self.assertEqual(result_of(done)['write_decision'], 'no_new_writes')
        self.assertEqual(self.host.meta_schema(), '21')
        self.assert_old_running()

    # ── 4. 보관 실패와 keep_raw_now(§D) ──
    def test_archive_failure_with_policy_room_warns_and_keeps_raw(self):
        plan = self.host.ready()
        done = self.host.migrate(plan, NAVER_DEPLOY_FAKE_ARCHIVE_FAIL='1')
        self.assertExit(done, 0)
        self.assertIn('ARCHIVE_PENDING', result_of(done)['warnings'])
        self.assertEqual(result_of(done)['keep_raw_now'], 'true')
        self.assertTrue(os.path.isfile(self.host.db('engine.db.pre-v22')))

    def test_archive_failure_without_policy_room_holds(self):
        plan = self.host.ready()
        self.host.backup_state(zip_bytes=200 * 1024 ** 2)   # 희소 파일: 정책 임계치 P_pol ≥ 200MiB
        # 실측 여유 대역: 1GiB 바닥 + 100MiB — G0/G2/G4(작은 DB)는 통과하지만 결과 시점 keep_raw_now 는 false.
        done = self.host.migrate(plan, NAVER_DEPLOY_FAKE_ARCHIVE_FAIL='1',
                                 NAVER_DEPLOY_FAKE_FREE_BYTES=str((1 << 30) + 100 * 1024 ** 2))
        self.assertExit(done, 12)
        self.assertEqual(result_of(done)['keep_raw_now'], 'false')
        self.assertTrue(os.path.isfile(self.host.db('engine.db.pre-v22')))

    # ── 5. 대표 모드: rollback(R7 gz 복원)·accept·continue ──
    def test_owner_rollback_from_gz_then_accept_refused(self):
        plan = self.host.ready()
        pre_sha = file_sha(self.host.db())
        done = self.host.migrate(plan)
        self.assertExit(done, 0)
        run = result_of(done)['migration_run']
        done = self.host.mrun('migrate-rollback', run)
        self.assertExit(done, 2)
        self.assertEqual(file_sha(self.host.db()), pre_sha)
        self.assert_old_running()
        with open(self.host.root + STATE + '/migration/' + run + '/receipt.json') as handle:
            receipt = json.load(handle)
        info = os.lstat(self.host.db())
        self.assertEqual(receipt['restored_identity']['ino'], info.st_ino)
        self.assertEqual(self.host.markers(), {'pointer': False, 'hold': False, 'dropins': False})
        self.assertEqual(self.host.status(run)['state'], 'ROLLED_BACK')
        done = self.host.mrun('migrate-accept', run)
        self.assertExit(done, 10)

    def test_accept_releases_pin(self):
        plan = self.host.ready()
        done = self.host.migrate(plan)
        run = result_of(done)['migration_run']
        done = self.host.mrun('migrate-accept', run)
        self.assertExit(done, 0)
        with open(self.host.root + STATE + '/pins/' + run + '.json') as handle:
            self.assertEqual(json.load(handle)['state'], 'released')
        with open(self.host.root + '/var/backups/metainc/naver-deploy-db/' + run + '/manifest.json') as handle:
            self.assertFalse(json.load(handle)['pinned'])

    def test_continue_from_hold_starts_v22(self):
        plan = self.host.ready()
        self.host.set(health_fail=[C1], write_on_start={'commit': C1, 'db': self.host.db()})
        done = self.host.migrate(plan)
        self.assertExit(done, 12)
        run = result_of(done)['migration_run']
        self.host.set(health_fail=[], write_on_start=None)
        done = self.host.mrun('migrate-continue', run)
        self.assertExit(done, 0)
        self.assertEqual(self.host.status(run)['state'], 'COMPLETED')
        self.assertEqual(self.host.markers(), {'pointer': False, 'hold': False, 'dropins': False})

    def test_cleanup_refused_while_migration_active(self):
        plan = self.host.ready()
        self.host.set(health_fail=[C1], write_on_start={'commit': C1, 'db': self.host.db()})
        self.assertExit(self.host.migrate(plan), 12)
        done = self.host.run('cleanup-artifacts', 'a' * 64)
        self.assertIn('REFUSED_MIGRATION_ACTIVE', self.out(done))


    # ── 6. F5: 뒤 배포가 쌓여도 복귀 묶음이 남는다 ──
    def test_rollback_bundle_survives_three_later_deploys(self):
        plan = self.host.ready()
        done = self.host.migrate(plan)
        self.assertExit(done, 0)
        run = result_of(done)['migration_run']
        later = ['2' * 40, '3' * 40, '4' * 40]
        for commit in later:
            files = source_files(commit, 22)
            path = os.path.join(self.base, 'later-%s.tar' % commit[:4])
            make_tar(path, files)
            self.assertExit(self.host.run('deploy', commit, path), 0)
        tags = self.host.tags()
        for name in ('engine', 'relay'):
            self.assertIn('metainc/naver-%s:rollback-%s' % (name, run[17:29]), tags)
        self.assertIn(self.host.old_images['engine'], self.host.load_state()['images'])
        self.assertTrue(os.path.isdir(self.host.root + RELEASES + '/naver-' + C0))
        self.assertTrue(os.path.isdir(self.host.root + '/var/backups/metainc/naver-deploy-db/' + run))
        self.set_product_for(later)
        done = self.host.mrun('migrate-rollback', run)
        self.assertExit(done, 2)
        self.assertEqual(self.host.meta_schema(), '21')
        self.assert_old_running()

    def set_product_for(self, commits):
        mapping = dict(self.host.config['product_by_commit'])
        for commit in commits:
            mapping[commit] = self.host.v22
        self.host.set(product_by_commit=mapping)


class CodeOnlyDeployTest(unittest.TestCase):
    """PR34+35+36(스키마 21) 코드만 배포: 정비 보관본이 DATA_DIR 에 있으면 거절, 옮긴 뒤 통과. pin 된 v2 사본은 보존."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='naver-codeonly-test-')
        self.host = FakeHost(self.base)

    def tearDown(self):
        shutil.rmtree(self.base)

    def test_maintenance_archives_block_until_moved(self):
        self.host.file(DATA + '/engine.db.pre-compact.gz', 'gz', 0o600)
        done = self.host.deploy(C1)
        self.assertEqual(done.returncode, 10)
        self.assertIn('DB_FILES', done.stdout.decode())
        os.makedirs(self.host.root + '/var/backups/metainc/naver-maint-archives/20261115')
        os.rename(self.host.root + DATA + '/engine.db.pre-compact.gz',
                  self.host.root + '/var/backups/metainc/naver-maint-archives/20261115/engine.db.pre-compact.gz')
        done = self.host.deploy(C1)
        self.assertEqual(done.returncode, 0, done.stdout.decode()[-3000:])
        self.assertEqual(result_of(done)['status'], 'DEPLOYED')

    def test_plain_deploy_keeps_pinned_v2_copy(self):
        import gzip
        folder = self.host.root + '/var/backups/metainc/naver-deploy-db'
        pinned = folder + '/20261101T000000Z-' + '1' * 12
        os.makedirs(pinned)
        raw = b'raw'
        with gzip.open(pinned + '/engine.db.gz', 'wb') as handle:
            handle.write(raw)
        with open(pinned + '/manifest.json', 'w') as handle:
            json.dump({'version': 2, 'schema': 21, 'source_commit': C0, 'purpose': 'pre-migration-21-22',
                       'pinned': True, 'run': '20261101T000000Z-' + '1' * 12,
                       'files': {'engine.db': {'size': 3, 'sha256': hashlib.sha256(raw).hexdigest(), 'stored': 'gzip',
                                               'gz_size': 1, 'gz_sha256': file_sha(pinned + '/engine.db.gz')}}}, handle)
        legacy = folder + '/20261102T000000Z-' + '2' * 12
        os.makedirs(legacy)
        open(legacy + '/engine.db', 'w').close()
        done = self.host.deploy(C1)
        self.assertEqual(done.returncode, 0, done.stdout.decode()[-3000:])
        names = sorted(os.listdir(folder))
        self.assertIn(os.path.basename(pinned), names)
        self.assertNotIn(os.path.basename(legacy), names)
        self.assertEqual(len(names), 2)


class MigrateWorkflowTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(HERE)), '..', '.github', 'workflows',
                               'naver-deploy.yml')) as handle:
            self.workflow = handle.read()

    def test_helper_is_shipped_and_hash_checked(self):
        self.assertIn('cp deploy/naver/naver_schema_migrate.py naver-ship/naver_schema_migrate.py', self.workflow)
        self.assertIn('NSD_MIGRATE_SHA', self.workflow)
        ssh = self.workflow[self.workflow.index('appleboy/ssh-action'):]
        self.assertIn('[ "$(hash_of "$work/naver_schema_migrate.py")" = "$NSD_MIGRATE_SHA" ] || fail MIGRATE_HELPER_HASH', ssh)
        self.assertNotIn('RuntimeMaxSec', ssh)

    def test_mutating_migrate_modes_need_confirm_and_args(self):
        self.assertEqual(self.workflow.count('MIGRATE_NAVER_SCHEMA_21_TO_22_ADDITIVE'), 3)
        self.assertIn("printf '%s' \"$MIGRATION_ARG\" | grep -Eq '^[0-9a-f]{64}$'", self.workflow)
        self.assertIn('real-product-migrate.log" 2>&1', self.workflow)


@unittest.skipUnless(os.environ.get('NAVER_PRODUCT_V21_DIR') and os.environ.get('NAVER_PRODUCT_V22_DIR'),
                     '실제 제품 두 커밋 폴더가 있을 때만(로컬·배포 workflow 시험 job)')
class RealProductHelperTest(unittest.TestCase):
    """실제 제품 377768a(v21)·1d85228(v22)의 store 로 합성 DB 를 만들고 helper chain·undo 를 돈다(값은 합성)."""

    def test_real_product_chain_verify_undo(self):
        sys.path.insert(0, os.path.dirname(HERE))
        base = tempfile.mkdtemp(prefix='naver-migrate-real-')
        try:
            v21, v22 = os.environ['NAVER_PRODUCT_V21_DIR'], os.environ['NAVER_PRODUCT_V22_DIR']
            data = os.path.join(base, 'data')
            os.mkdir(data, 0o700)
            script = os.path.join(os.path.dirname(HERE), 'naver-deploy.sh')
            with open(script) as handle:
                text = handle.read()
            entry = None
            for line in text.splitlines():
                if "'from_store_sha256'" in line:
                    entry = line
            self.assertIsNotNone(entry)
            env = {'PATH': '/usr/bin:/bin', 'NAVER_MIGRATE_TEST': '1', 'NAVER_MIGRATE_DIR': data, 'LANG': 'C'}
            if NO_FLOCK:
                env['NAVER_MIGRATE_TEST_NO_FLOCK'] = '1'
            pins = real_pins(text)
            run = '20261115T000000Z-' + '1d852289209e'

            def helper(step, code, args):
                value = dict(args, mode='test', as_mode='rehearsal', run=run, migration_id=MIG_ID)
                done = subprocess.run([sys.executable, '-I', '-B', HELPER, step, json.dumps(value)],
                                      env=dict(env, NAVER_MIGRATE_CODE_DIR=code), stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
                out = json.loads(done.stdout.decode().strip().splitlines()[-1])
                self.assertTrue(out['ok'], (step, out, done.stderr.decode()[-2000:]))
                return out['result']
            open(os.path.join(data, 'naver-migrate-rehearsal-marker'), 'w').close()
            helper('seed', v21, {'pins': {'store_sha256': pins['from_store_sha256'], 'schema': 21}})
            before = file_sha(os.path.join(data, 'engine.db'))
            result = helper('chain', v22, {'floor_bytes': 0, 'pins': {
                'store_sha256': pins['to_store_sha256'], 'exhaust_sha256': pins['to_exhaust_sha256'], 'schema': 22,
                'from_schema': 21, 'new_tables': pins['new_tables'], 'autoindexes': pins['autoindexes']}})
            self.assertGreaterEqual(result['orphans_closed'], 1)
            with open(os.path.join(data, 'naver-migrate-receipt.json')) as handle:
                receipt = json.load(handle)
            helper('v21-refuses', v21, {'pins': {'store_sha256': pins['from_store_sha256'], 'schema': 21},
                                        'expect_schema': 22})
            helper('startcheck', v22, {'expect_identity': receipt['work_identity'],
                                       'expect_sha256': receipt['work_sha256'], 'full': True, 'expect_schema': 22})
            helper('undo', v22, {'receipt': receipt})
            self.assertEqual(file_sha(os.path.join(data, 'engine.db')), before)
            helper('v21-opens', v21, {'pins': {'store_sha256': pins['from_store_sha256'], 'schema': 21},
                                      'expect_schema': 21})
        finally:
            shutil.rmtree(base)


def real_pins(text):
    start = text.index('MIGRATIONS = {')
    end = text.index("if ROOT and os.environ.get('NAVER_DEPLOY_TEST_MIGRATIONS')")
    namespace = {}
    exec(text[start:end], namespace)
    return namespace['MIGRATIONS'][MIG_ID]


if __name__ == '__main__':
    unittest.main()
