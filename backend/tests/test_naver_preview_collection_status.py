"""Synthetic SQLite collection projection; never connects to Docker or a server."""
import importlib.util
import ast
import hashlib
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import types
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from datetime import datetime
from test_naver_preview_code_upgrade import load

SPEC = importlib.util.spec_from_file_location('collection_status', Path(__file__).parents[1]/'tools/naver_preview_collection_status.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class CollectionTest(unittest.TestCase):
    def setUp(self):
        # Existing synthetic runner tests never read this machine's /proc metadata.
        metadata = patch.object(M,'host_memory_metadata',return_value=dict(
            available=False,code='HOST_MEMORY_UNAVAILABLE'))
        metadata.start()
        self.addCleanup(metadata.stop)

    def resource_raw(self, engine='d'*64, relay='7'*64):
        return b'\n'.join(json.dumps(row).encode() for row in (
            dict(id=engine,cpu='49.73%',memory='128.5MiB / 512MiB',memory_percent='25.10%'),
            dict(id=relay,cpu='0.20%',memory='32MB / 256MiB',memory_percent='11.92%')))

    def test_resource_projection_exports_only_fixed_units_and_bounded_numbers(self):
        targets = {'engine':'d'*64,'relay':'7'*64}
        result = M.resource_projection(self.resource_raw(), targets)
        self.assertEqual(result['engine'], dict(available=True,cpu_percent=49.73,
            memory_used_bytes_approx=134742016,memory_limit_bytes_approx=536870912,memory_percent=25.10))
        self.assertEqual(result['relay']['memory_used_bytes_approx'],32000000)
        self.assertNotIn('d'*64,json.dumps(result))
        self.assertNotIn('7'*64,json.dumps(result))
        for raw in (self.resource_raw(engine='f'*64),self.resource_raw(relay='d'*64),
                    self.resource_raw()+b'\n'+json.dumps(dict(id='f'*64,cpu='1%',
                        memory='1MiB / 2MiB',memory_percent='50%')).encode(),
                    b'x'*4097,b'\xff',b'',self.resource_raw().split(b'\n')[0]):
            with self.subTest(raw_length=len(raw)),self.assertRaises(ValueError):
                M.resource_projection(raw,targets)
        first = json.loads(self.resource_raw().split(b'\n')[0])
        for key,value in (('cpu','nan%'),('cpu','1000000%'),('cpu','PRIVATE'),
                          ('memory','1MiB / 0B'),('memory','1PRIVATE / 512MiB'),
                          ('memory','1024MiB / 512MiB'),('memory_percent','100.01%'),
                          ('name','PRIVATE_SERVICE')):
            with self.subTest(field=key,value=value),self.assertRaises(ValueError):
                M.resource_projection(json.dumps(dict(first,**{key:value})).encode(),{'engine':'d'*64})
        duplicate = b'{"id":"'+b'd'*64+b'","cpu":"1%","cpu":"2%","memory":"1B / 2B","memory_percent":"50%"}'
        with self.assertRaises(ValueError):
            M.resource_projection(duplicate,{'engine':'d'*64})

    def test_resource_sample_targets_only_verified_containers_and_has_total_budget(self):
        capture = dict(reason=None,exit_code=0,stdout=self.resource_raw(),stderr=b'PRIVATE STDERR')
        with patch.object(M,'capture_process',return_value=capture) as command, \
                patch.object(M.os,'cpu_count',return_value=8), \
                patch.object(M.os,'getloadavg',return_value=(1.25,2.5,3.75)), \
                patch.object(M.time,'monotonic',side_effect=(10.0,10.5)):
            result = M.runtime_resource_sample('d'*64,'7'*64)
        args = command.call_args.args[0]
        self.assertEqual(args[:4],['docker','stats','--no-stream','--no-trunc'])
        self.assertEqual(args[-2:],['d'*64,'7'*64])
        self.assertEqual(args[4:6],['--format',M.RESOURCE_FORMAT])
        self.assertEqual(command.call_args.kwargs,dict(timeout=3.5,absolute_deadline=14.0,
                                                     stdout_limit=4096,stderr_limit=4096))
        self.assertEqual(result['host'],dict(available=True,cpu_count=8,load_average_1m=1.25,
            load_average_5m=2.5,load_average_15m=3.75))
        self.assertEqual(result['cpu_percent_basis'],'one_logical_cpu')
        self.assertEqual(result['scope'],'single_sample_not_request_profile')
        self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertNotIn('d'*64,json.dumps(result))

    def test_optional_resource_failure_is_fixed_and_never_starts_other_targets(self):
        for reason,exit_code,stdout,code in (
                ('PROCESS_TIMEOUT',None,b'PRIVATE','RESOURCE_SAMPLE_TIMEOUT'),
                ('PROCESS_OUTPUT_LIMIT',None,b'PRIVATE','RESOURCE_SAMPLE_OUTPUT_LIMIT'),
                (None,1,b'PRIVATE','RESOURCE_SAMPLE_UNAVAILABLE'),
                (None,0,b'PRIVATE','RESOURCE_SAMPLE_INVALID')):
            with self.subTest(reason=reason,exit_code=exit_code), \
                    patch.object(M,'capture_process',return_value=dict(reason=reason,
                        exit_code=exit_code,stdout=stdout,stderr=b'PRIVATE')):
                result = M.runtime_resource_sample('d'*64,'7'*64)
            self.assertEqual(result['containers'],{name:dict(available=False,code=code) for name in ('engine','relay')})
            self.assertNotIn('PRIVATE',json.dumps(result))
        raw = self.resource_raw().split(b'\n')[0]
        with patch.object(M,'capture_process',return_value=dict(reason=None,exit_code=0,stdout=raw,stderr=b'')) as command:
            result = M.runtime_resource_sample('d'*64,'RELAY_PRIVATE')
        self.assertEqual(command.call_args.args[0][-1],'d'*64)
        self.assertNotIn('RELAY_PRIVATE',command.call_args.args[0])
        self.assertEqual(result['containers']['relay'],dict(available=False,code='RESOURCE_TARGET_UNVERIFIED'))
        with patch.object(M,'capture_process') as command:
            result = M.runtime_resource_sample('PRIVATE','7'*64)
        command.assert_not_called()
        self.assertEqual(result['containers']['engine'],dict(available=False,code='RESOURCE_TARGET_UNVERIFIED'))
        with patch.object(M,'capture_process') as command, \
                patch.object(M.time,'monotonic',side_effect=(10.0,14.0)):
            result = M.runtime_resource_sample('d'*64,'7'*64)
        command.assert_not_called()
        self.assertEqual(result['containers']['engine']['code'],'RESOURCE_SAMPLE_TIMEOUT')

    def test_host_resources_reject_unavailable_or_unbounded_numeric_values(self):
        for cpus,load in ((None,(1.,2.,3.)),(True,(1.,2.,3.)),(4097,(1.,2.,3.)),
                          (8,(float('nan'),2.,3.)),(8,(-1.,2.,3.)),(8,(1000001.,2.,3.)),
                          (8,(1.,2.)),(8,('PRIVATE',2.,3.))):
            with self.subTest(cpus=cpus),patch.object(M.os,'cpu_count',return_value=cpus), \
                    patch.object(M.os,'getloadavg',return_value=load):
                self.assertEqual(M.host_resources(),dict(available=False,code='HOST_RESOURCE_UNAVAILABLE'))
        with patch.object(M.os,'getloadavg',side_effect=OSError('PRIVATE')):
            self.assertEqual(M.host_resources(),dict(available=False,code='HOST_RESOURCE_UNAVAILABLE'))

    def test_passive_storage_metadata_never_reads_content_or_follows_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'engine.db').write_bytes(b'PRIVATE')
            (root/'engine.db-wal').symlink_to(root/'engine.db')
            with patch.object(Path,'read_bytes',side_effect=AssertionError('must not read')):
                result = M.storage_metadata(root)
            self.assertEqual(result['files']['database']['bytes'],7)
            self.assertFalse(result['files']['wal']['available'])
            self.assertFalse(result['files']['shared_memory']['available'])
            self.assertNotIn('PRIVATE',json.dumps(result))
            self.assertNotIn(folder,json.dumps(result))

    def test_recent_log_projection_keeps_only_fixed_job_error_and_lifecycle_labels(self):
        messages = [
            'ERROR naver_runtime.scheduler 예약 작업 실패: reports OperationalError',
            'ERROR naver_runtime.scheduler 예약 작업 실패: inventory PRIVATE_SECRET',
            'ERROR naver_runtime 예약 회차 실패: StoreBusy',
            'ERROR naver_runtime.scheduler 예약 작업 실패 기록을 저장하지 못했습니다',
            'metainc-naver-engine.service: Main process exited, code=exited, status=1/FAILURE',
            "metainc-naver-engine.service: Failed with result 'exit-code'.",
            'naver-engine-1  | ERROR naver_runtime.scheduler 예약 작업 실패: morning ValueError',
            'OperationalError: PRIVATE token=SECRET 987654321',
            'customer PRIVATE token=SECRET']
        raw = b'\n'.join(json.dumps(dict(MESSAGE=message,__REALTIME_TIMESTAMP='1791180000000000')).encode()
                         for message in messages)
        projected = M.log_projection(raw, source='journal', unit='engine')
        self.assertEqual(projected['entries_inspected'],9)
        self.assertEqual(projected['unrecognized_entries'],1)
        self.assertIn(dict(event='job_failed',stage='reports',error_kind='OperationalError',count=1),
                      projected['events'])
        self.assertIn(dict(event='job_failed',stage='inventory',error_kind='UNRECOGNIZED',count=1),
                      projected['events'])
        self.assertIsNotNone(projected['last_recognized_at'])
        for private in ('PRIVATE','SECRET','987654321','MESSAGE'):
            self.assertNotIn(private,json.dumps(projected))
        result = M.log_projection(b'2026-10-05T05:00:00.123456789Z '+messages[0].encode(),
                                 source='docker',unit='engine')
        self.assertEqual(result['events'][0]['stage'], 'reports')
        self.assertEqual(result['last_recognized_at'],'2026-10-05T05:00:00.123456+00:00')

    def test_failed_reader_process_returns_exit_and_safe_exception_without_raw_stderr(self):
        result = M.capture_process([sys.executable, '-I', '-c',
            "import sys; sys.stderr.write('Traceback (most recent call last):\\nNameError: PRIVATE 987654321\\n'); sys.exit(1)"],
            timeout=3, stdout_limit=32768)
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(M.process_failure(result), {'code':'PROCESS_EXIT', 'exit_code':1,
            'error_kind':'NameError', 'output_limited':False})
        self.assertNotIn('PRIVATE', json.dumps(M.process_failure(result)))

    def test_process_capture_bounds_stdout_stderr_timeout_and_transfers_complete_script(self):
        for stream, limit in (('stdout',32768),('stderr',8192)):
            result = M.capture_process([sys.executable,'-I','-c',
                f"import sys; sys.{stream}.write('x'*2000000)"], timeout=3)
            self.assertEqual(result['reason'], 'PROCESS_OUTPUT_LIMIT')
            self.assertLessEqual(len(result[stream]), limit)
        result = M.capture_process([sys.executable,'-I','-c','import time;time.sleep(10)'], timeout=0.05)
        self.assertEqual(M.process_failure(result)['code'], 'PROCESS_TIMEOUT')
        result = M.capture_process([sys.executable,'-I','-c','import sys;print(len(sys.stdin.buffer.read()))'],
                                   data=b'x'*100000, timeout=3)
        self.assertEqual((result['exit_code'],result['stdout']), (0,b'100000\n'))

    def test_capture_setup_failure_cleans_up_child_with_bounded_wait(self):
        process = Mock()
        process.poll.return_value = None
        process.returncode = -9
        with patch.object(M.subprocess,'Popen',return_value=process), \
                patch.object(M.os,'set_blocking',side_effect=OSError('PRIVATE')):
            result = M.capture_process(['diagnostic-fixture'])
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=1)
        self.assertEqual(result['reason'],'PROCESS_UNAVAILABLE')

    def test_resource_absolute_deadline_includes_capture_setup_and_has_bounded_cleanup(self):
        started = M.time.monotonic()
        result = M.capture_process([sys.executable,'-I','-c','import time;time.sleep(10)'],
                                   timeout=3,absolute_deadline=started+0.05)
        self.assertEqual(result['reason'],'PROCESS_TIMEOUT')
        self.assertLess(M.time.monotonic()-started,1.5)
        self.assertNotEqual(result['exit_code'],0)

    def test_selector_creation_failure_does_not_start_a_diagnostic_child(self):
        with patch.object(M.selectors,'DefaultSelector',side_effect=OSError('PRIVATE')), \
                patch.object(M.subprocess,'Popen') as start:
            result = M.capture_process(['diagnostic-fixture'])
        start.assert_not_called()
        self.assertEqual(result['reason'],'PROCESS_UNAVAILABLE')

    def test_log_event_groups_are_capped_and_omissions_are_explicit(self):
        messages = ['ERROR naver_runtime.scheduler 예약 작업 실패: '+stage+' '+kind
                    for stage in sorted(M.LOG_STAGES) for kind in sorted(M.LOG_KINDS)]
        raw = b'\n'.join(json.dumps(dict(MESSAGE=message)).encode() for message in messages[:300])
        result = M.log_projection(raw,source='journal',unit='engine')
        self.assertEqual(len(result['events']),32)
        self.assertEqual(result['omitted_event_count'],268)
        self.assertTrue(result['sample_limit_reached'])

    def test_emitted_identity_failure_returns_only_fixed_diagnostic_not_partial_counts(self):
        output = io.StringIO()
        with patch.object(os, 'geteuid', return_value=0), contextlib.redirect_stdout(output):
            exec(compile(M.script(reports=True), '<failed-status-script>', 'exec'), {})
        self.assertEqual(json.loads(output.getvalue()), {'diagnostic_failure': {
            'stage':'identity', 'error_kind':'ValueError', 'sqlite_primary':None}})

    def test_emitted_reports_sql_failure_preserves_original_stage_through_cleanup(self):
        for close_fails in (False, True):
            with self.subTest(close_fails=close_fails):
                result, output = self.complete_emitted_fixture(deny_json=True, close_fails=close_fails)
                self.assertEqual(result, {'diagnostic_failure': {
                    'stage':'reports', 'error_kind':'OperationalError', 'sqlite_primary':'SQLITE_ERROR'}})
                self.assertNotIn('PRIVATE', output)
                self.assertNotIn('collection', result)

    def test_diagnostic_labels_use_only_sqlite_primary_codes_and_never_exception_text(self):
        for code, label in ((5,'SQLITE_BUSY'),(261,'SQLITE_BUSY'),(9,'SQLITE_INTERRUPT'),(15,'SQLITE_PROTOCOL'),
                            (23,'SQLITE_AUTH'),(26,'SQLITE_NOTADB'),(999,'UNRECOGNIZED'),
                            (None,'UNRECOGNIZED'),(True,'UNRECOGNIZED')):
            error = sqlite3.OperationalError('PRIVATE SQL account=987654321 /private/path')
            error.sqlite_errorcode = code
            error.sqlite_errorname = 'PRIVATE'
            self.assertEqual(M.diagnostic_failure('reports', error), dict(stage='reports',
                error_kind='OperationalError',sqlite_primary=label))
        private_error = type('PRIVATE_customer_987654321', (Exception,), {})('PRIVATE')
        self.assertEqual(M.diagnostic_failure('PRIVATE', private_error), dict(stage='UNRECOGNIZED',
            error_kind='UNRECOGNIZED',sqlite_primary=None))
        # A real SQLite interruption confirms the runtime numeric-code path, not message parsing.
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.set_progress_handler(lambda: 1, 1)
        with self.assertRaises(sqlite3.OperationalError) as caught:
            db.execute('SELECT 1')
        self.assertEqual(M.diagnostic_failure('core', caught.exception), dict(stage='core',
            error_kind='OperationalError',sqlite_primary='SQLITE_INTERRUPT'))

    def test_wrapped_store_failure_exposes_only_bounded_sqlite_primary_cause(self):
        store_error = type('StoreError',(Exception,),{})('PRIVATE')
        sql = sqlite3.OperationalError('PRIVATE filename')
        sql.sqlite_errorcode = 261
        store_error.__context__ = sql
        self.assertEqual(M.diagnostic_failure('reader',store_error),
                         dict(stage='reader',error_kind='StoreError',sqlite_primary='SQLITE_BUSY'))
        store_error.__context__ = store_error
        self.assertIsNone(M.diagnostic_failure('reader',store_error)['sqlite_primary'])

    def test_diagnostic_projection_rejects_unknown_fields_shapes_and_labels(self):
        valid = {'diagnostic_failure':dict(stage='reports',error_kind='OperationalError',
                                          sqlite_primary='SQLITE_INTERRUPT')}
        self.assertEqual(M.diagnostic_projection(valid), valid['diagnostic_failure'])
        for mutate in (lambda v:v.update(collection={}),
                lambda v:v['diagnostic_failure'].update(raw_error='PRIVATE'),
                lambda v:v['diagnostic_failure'].update(stage=['reports']),
                lambda v:v['diagnostic_failure'].update(error_kind='PRIVATE'),
                lambda v:v['diagnostic_failure'].update(sqlite_primary=9),
                lambda v:v.update(diagnostic_failure=None)):
            value = json.loads(json.dumps(valid)); mutate(value)
            with self.assertRaisesRegex(ValueError, '^COLLECTION_DIAGNOSTIC$'):
                M.diagnostic_projection(value)

    def test_catalog_diagnostics_accept_only_reviewed_product_commits(self):
        self.assertEqual(M.CATALOG_LINKS_COMMITS, frozenset({
            '6e4b035901027fef29266de218bfb0594227a3fe',
            '01344b145d0b679a6ee730d7fa4b5990278dd654',
            '1b790b864ce27766251a205259fa6a332f60f72b',
            '0a302856c6177c4f53145abaf9ed31b6a39654f3',
            'a38c53775c112cdf5db420f979093d6bee9e5376',
            'c21f5f05f610abf89df0c24e85c00b1bec23d01c',
            '8dd4292d82f5f98e7b4afa44a2a66b6770eaa505',
            'a981b35e298aa58a52b30e266792bd0f36506c5d',
            '25dc24d8760a06b2321d4fbde481769c3ce32c34',
            '6198be366344a82923e10ba5e323877026d82f48',
            'e4f64e165ebdf81d4127218d5c91ff6904e75958'}))
        self.assertEqual(M.DAILY_LIMITED_COMMIT, '01344b145d0b679a6ee730d7fa4b5990278dd654')
        self.assertEqual(M.DAILY_LIMITED_COMMITS, frozenset({
            '01344b145d0b679a6ee730d7fa4b5990278dd654',
            '1b790b864ce27766251a205259fa6a332f60f72b',
            '0a302856c6177c4f53145abaf9ed31b6a39654f3',
            'a38c53775c112cdf5db420f979093d6bee9e5376',
            'c21f5f05f610abf89df0c24e85c00b1bec23d01c',
            '8dd4292d82f5f98e7b4afa44a2a66b6770eaa505',
            'a981b35e298aa58a52b30e266792bd0f36506c5d',
            '25dc24d8760a06b2321d4fbde481769c3ce32c34',
            '6198be366344a82923e10ba5e323877026d82f48',
            'e4f64e165ebdf81d4127218d5c91ff6904e75958'}))
        self.assertEqual(M.REPORTS_COMMIT, 'a38c53775c112cdf5db420f979093d6bee9e5376')
        self.assertEqual(M.SHM_LOCK_FIX_COMMIT, 'c21f5f05f610abf89df0c24e85c00b1bec23d01c')
        self.assertEqual(M.OWNER_ACTIONS_COMMIT, '8dd4292d82f5f98e7b4afa44a2a66b6770eaa505')
        self.assertEqual(M.SCREEN_OVERHAUL_COMMIT, 'a981b35e298aa58a52b30e266792bd0f36506c5d')
        self.assertEqual(M.WRITER_RELIEF_COMMIT, '25dc24d8760a06b2321d4fbde481769c3ce32c34')
        code = load('naver_preview_code_upgrade')
        self.assertEqual(M.LATENCY_FIX_COMMIT, code.OLD_COMMIT)
        self.assertEqual(M.DASHBOARD_LATENCY_FIX_COMMIT, code.TARGET_COMMIT)
        self.assertEqual(M.MONITORING_COMMITS, frozenset({
            '0a302856c6177c4f53145abaf9ed31b6a39654f3',
            'a38c53775c112cdf5db420f979093d6bee9e5376',
            'c21f5f05f610abf89df0c24e85c00b1bec23d01c',
            '8dd4292d82f5f98e7b4afa44a2a66b6770eaa505',
            'a981b35e298aa58a52b30e266792bd0f36506c5d',
            '25dc24d8760a06b2321d4fbde481769c3ce32c34',
            '6198be366344a82923e10ba5e323877026d82f48',
            'e4f64e165ebdf81d4127218d5c91ff6904e75958'}))

    def test_daily_limited_uses_schema11_reader_and_separates_current_targets_from_old_jobs(self):
        fixture = json.loads((Path(__file__).with_name('fixtures')/'naver_schema10_11_contract.json').read_text())
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        for sql in fixture['new_observed_unsealed']['sql']:
            db.execute(sql)
        db.execute("INSERT INTO naver_auto_meta VALUES ('schema_version','11')")
        cases = [('daily','2026-11-02','limited','REQUEST_DEADLINE',4,1,'revision'),
                 ('daily','2026-11-02','limited','SERVER',4,2,'old-revision'),
                 ('daily','2026-11-02','limited','PRIVATE_ERROR',8,3,'revision'),
                 ('daily','2026-11-01','limited','NETWORK',4,1,'revision'),
                 ('weekly','2026-11-02','limited','NETWORK',4,1,'revision'),
                 ('daily','2026-11-02','ok',None,0,1,'revision')]
        for i, (kind, cycle, status, error, attempts, cid, revision) in enumerate(cases):
            db.execute('''INSERT INTO naver_auto_performance_job
                (job_key,customer_id,kind,cycle_day,period_start,period_end,snapshot_at,catalog_at,
                 stage_revision,possibility_id,matching_fingerprint,status,checked_at,next_try_at,attempts,error_code,bizmoney)
                VALUES(?,?,?,?, '2026-11-01','2026-11-01','private','private',?,987654321,
                       'private',?,'2026-11-02T10:00:00+09:00','2026-11-02T10:15:00+09:00',?,?,123456.75)''',
                ('private'+str(i),cid,kind,cycle,revision,status,attempts,error))
        db.commit()
        baseline = db.total_changes
        scope = dict(_A=sqlite3)
        exec(fixture['new_observed_unsealed']['authorizer'], scope)
        db.set_authorizer(scope['_authorizer'](scope['PHASE_READ']))
        decisions = {cid:dict(source_current=True, decision=types.SimpleNamespace(cadence='daily'),
                              stage_revision='revision',possibility_id=987654321) for cid in (1,2,4)}
        result = M.collect_daily_limited(db, '2026-11-02', decisions)
        self.assertEqual((result['jobs'], result['current_daily_targets']), (3,3))
        groups = {row['error_code']:row for row in result['groups']}
        self.assertEqual(groups['REQUEST_DEADLINE'], dict(error_code='REQUEST_DEADLINE',attempts='4',
            current_target=True,prior_error_evidence='UNKNOWN_NOT_RECORDED',jobs=1))
        self.assertFalse(groups['SERVER']['current_target'])
        self.assertEqual(groups['UNRECOGNIZED']['attempts'],'FOUR_PLUS')
        self.assertEqual(db.total_changes, baseline)
        self.assertEqual(M.daily_limited_projection(result, '2026-11-02'), result)
        for private in ('private','PRIVATE','987654321','123456.75','customer_id','possibility_id','revision'):
            self.assertNotIn(private, json.dumps(result))
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE naver_auto_performance_job SET attempts=0")
        decisions[1]['source_current']=False
        with self.assertRaisesRegex(ValueError, '^COLLECTION_LIMITED_SOURCE$'):
            M.collect_daily_limited(db, '2026-11-02', decisions)

    def test_daily_limited_projection_rejects_drift_leaks_ambiguity_and_excess(self):
        value = dict(cycle_day='2026-11-02', jobs=1, current_daily_targets=1,
            current_target_rule='DAILY_CADENCE_AND_SAME_ATTRIBUTION_NOT_RETRY_PERMISSION',
            groups=[dict(error_code='REQUEST_DEADLINE',attempts='4',current_target=True,
                         prior_error_evidence='UNKNOWN_NOT_RECORDED',jobs=1)])
        mutations = [lambda v:v.update(customer_id=987654321),lambda v:v.update(jobs=True),
            lambda v:v.update(cycle_day='2026-11-01'),lambda v:v.update(current_daily_targets=0),
            lambda v:v.update(current_daily_targets=100001),lambda v:v.update(groups=v['groups']*101),
            lambda v:v['groups'][0].update(error_code='PRIVATE_ERROR'),
            lambda v:v['groups'][0].update(attempts=4),lambda v:v['groups'][0].update(current_target=1),
            lambda v:v['groups'][0].update(prior_error_evidence='NO_NETWORK_ERROR'),
            lambda v:v['groups'][0].update(jobs=-1),lambda v:v['groups'][0].update(customer_id=987654321),
            lambda v:v.update(groups=v['groups']*2,jobs=2,current_daily_targets=2)]
        for mutate in mutations:
            changed=json.loads(json.dumps(value)); mutate(changed)
            with self.subTest(value=changed):
                with self.assertRaises(ValueError) as caught:
                    M.daily_limited_projection(changed,'2026-11-02')
                self.assertNotIn('PRIVATE',str(caught.exception))

    def catalog_fixture(self):
        now = datetime.fromisoformat('2026-10-03T12:00:00+09:00')
        rows = {pid: [dict(possibility_id=pid, customer_id=987654320+pid,
                          state='auto' if pid == 1 else 'blocked', code='same' if pid == 1 else 'name-different',
                          claimed_elsewhere=False, allowed=pid == 1)] for pid in range(1, 5)}
        ctx = types.SimpleNamespace(now=now, org=object(), owns={pid: object() for pid in rows},
            accounts={987654320+pid: {'present':1,'account_name':'PRIVATE_NAME'} for pid in rows},
            prospects={2:dict(stage_conflict=1,end_unreadable=1,latest_end_date=None),
                       3:dict(stage_conflict=0,end_unreadable=1,latest_end_date=None),
                       4:dict(stage_conflict=0,end_unreadable=0,latest_end_date='2026-09-01')},
            live_decisions=(), rows_by_pid=rows)
        context = types.SimpleNamespace(ctx=ctx, scope=types.SimpleNamespace(kind='ALL'),
            source_state='accepted', visible_ids=frozenset(rows), catalog_at=now,
            companies={pid:dict(stage='전략관리',stage_hidden=False,stage_known=True,company_name='PRIVATE_NAME') for pid in rows})
        rules = types.SimpleNamespace(
            SC=types.SimpleNamespace(ALL='ALL',MINE='MINE',ACT_CONFIRM_LINK='confirm_link',
                allowed_actions=lambda *args: {'confirm_link'}),
            W=types.SimpleNamespace(link_holders=lambda *args: frozenset()),
            H=types.SimpleNamespace(eligibility_reason=lambda stage,at,end,current:
                'ended-over-14-days' if end is not None and (current.date()-end).days > 14 else None),
            allowed=lambda context,row: row['allowed'])
        return context, rules

    def test_catalog_confirmation_counts_first_refusal_without_identities(self):
        context, rules = self.catalog_fixture()
        out = M.catalog_link_counts(context, rules)
        self.assertEqual((out['auto'],out['name_different'],out['can_confirm']), (1,3,1))
        self.assertEqual(out['rejected'], {'legacy_stage_conflict':1,'legacy_end_unreadable':1,'ended-over-14-days':1})
        self.assertEqual(M.catalog_link_projection(out), out)
        for private in ('PRIVATE','987654321','possibility_id','customer_id','"name"','"token"','"ref"'):
            self.assertNotIn(private, json.dumps(out))
        context.source_state='stale'
        with self.assertRaisesRegex(ValueError, '^CATALOG_LINK_SOURCE$'):
            M.catalog_link_counts(context, rules)

    def monitoring_catalog_fixture(self):
        context, rules = self.catalog_fixture()
        del rules.H  # Removed from the deployed product; diagnostics cannot call it.
        scope = dict(SC=rules.SC, W=rules.W,
                     S=types.SimpleNamespace(PAIR_AUTO='auto',PAIR_BLOCKED='blocked',PAIR_CANDIDATE='candidate'),
                     M=types.SimpleNamespace(B_NAME_DIFFERENT='name-different'))
        path = Path(__file__).with_name('fixtures')/'naver_monitoring_catalog_policy.py'
        exec(compile(path.read_text(), '<pinned-monitoring-policy>', 'exec'), scope)
        rules.allowed, rules.block_reason = scope['allowed'], scope['block_reason']
        return context, rules

    def test_actual_monitoring_policy_without_removed_handles_ignores_legacy_contract_gates(self):
        context, rules = self.monitoring_catalog_fixture()
        result = M.catalog_link_counts(context, rules)
        self.assertEqual(result, {'auto':1,'name_different':3,'can_confirm':4,'rejected':{}})
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_latest_report_versions_use_only_latest_company_editions_under_reader_authorizer(self):
        fixture = json.loads((Path(__file__).with_name('fixtures')/'naver_schema10_11_contract.json').read_text())
        db = sqlite3.connect(':memory:', isolation_level=None)
        self.addCleanup(db.close)
        for sql in fixture['new_observed_unsealed']['sql']:
            db.execute(sql)
        week = 'weekly:2026-10-05:2026-10-11'
        month = 'monthly:2026-09-01:2026-09-30'
        at = '2026-10-12T10:00:00+09:00'
        cases = [(1,1,week,'PRIVATE-BROKEN-OLD'), (2,1,week,'{"format_version":2,"spend":987654321}'),
                 (3,2,week,'{"PRIVATE":"name"}'), (4,3,week,'PRIVATE-BROKEN'),
                 (5,4,week,'{"format_version":"2"}'), (6,5,week,'[]'),
                 (7,6,week,'{"format_version":1}'), (8,7,week,'{"format_version":1.0}'),
                 (9,8,week,'{"format_version":null}'), (10,9,week,'{"format_version":true}'),
                 (11,1,month,'{"format_version":2}'),
                 (100,1,'weekly:2026-09-28:2026-10-04','PRIVATE-OLDER-PERIOD'),
                 (101,1,'monthly:2026-08-01:2026-08-31','PRIVATE-OLDER-PERIOD')]
        for rid,pid,period,payload in cases:
            generated = ('2030-01-01T10:00:00+09:00' if rid in (1,100,101) else
                         '2026-10-12T12:00:00+09:00' if rid == 2 else at)
            db.execute('''INSERT INTO naver_auto_report_snapshot
                (report_id,possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
                VALUES(?,?,?,'PRIVATE-FINGERPRINT',?,'ready','ready',?)''', (rid,pid,period,generated,payload))
        baseline = db.total_changes
        scope = dict(_A=sqlite3)
        exec(fixture['new_observed_unsealed']['authorizer'], scope)
        db.set_authorizer(scope['_authorizer'](scope['PHASE_READ']))
        db.execute('BEGIN')
        result = M.collect_reports(db)
        db.execute('ROLLBACK')
        self.assertEqual(result, {
            'weekly':dict(period_key=week,latest_company_reports=9,
                          versions=dict(v1=2,v2=1,unknown=6),latest_generated_at='2026-10-12T12:00:00+09:00'),
            'monthly':dict(period_key=month,latest_company_reports=1,
                           versions=dict(v1=0,v2=1,unknown=0),latest_generated_at=at)})
        self.assertEqual(M.reports_projection(result), result)
        self.assertEqual(db.total_changes, baseline)
        for private in ('PRIVATE','987654321','possibility_id','report_id','spend','payload'):
            self.assertNotIn(private, json.dumps(result))
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute('DELETE FROM naver_auto_report_snapshot')
        reader_authorizer = scope['_authorizer'](scope['PHASE_READ'])
        db.set_authorizer(lambda action,arg1,arg2,*rest: sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and arg2 == 'json_valid'
            else reader_authorizer(action,arg1,arg2,*rest))
        with self.assertRaises(sqlite3.DatabaseError):
            M.collect_reports(db)

    def test_reports_projection_bounds_empty_periods_and_query_failures_are_not_zero_counts(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        with self.assertRaises(sqlite3.OperationalError):
            M.collect_reports(db)
        empty = {kind:dict(period_key=None,latest_company_reports=0,versions=dict(v1=0,v2=0,unknown=0),
                          latest_generated_at=None) for kind in ('weekly','monthly')}
        self.assertEqual(M.reports_projection(empty), empty)
        for mutate in (lambda v:v.update(customer_id=987654321),
                       lambda v:v['weekly'].update(payload='PRIVATE'),
                       lambda v:v['weekly'].update(latest_company_reports=True),
                       lambda v:v['weekly']['versions'].update(v1=-1),
                       lambda v:v['weekly']['versions'].update(other=0),
                       lambda v:v['weekly'].update(period_key='PRIVATE'),
                       lambda v:v['weekly'].update(latest_generated_at='PRIVATE')):
            changed=json.loads(json.dumps(empty)); mutate(changed)
            with self.subTest(value=changed), self.assertRaises(ValueError) as caught:
                M.reports_projection(changed)
            self.assertNotIn('PRIVATE',str(caught.exception))
        for key in ('weekly:2026-10-06:2026-10-12','weekly:2026-10-05:2026-10-10',
                    'weekly:2026-99-01:2026-99-07','weekly:2026-10-05:2026-10-11:PRIVATE'):
            changed=json.loads(json.dumps(empty))
            changed['weekly'].update(period_key=key,latest_company_reports=1,versions=dict(v1=0,v2=1,unknown=0),
                                     latest_generated_at='2026-10-12T10:00:00+09:00')
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,'^COLLECTION_REPORTS$'):
                M.reports_projection(changed)

    def test_morning_progress_counts_only_today_and_live_current_generation_without_identities(self):
        fixture = json.loads((Path(__file__).with_name('fixtures')/'naver_schema10_11_contract.json').read_text())
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        for sql in fixture['new_observed_unsealed']['sql']:
            db.execute(sql)
        db.executescript((Path(__file__).with_name('fixtures')/'naver_monitoring_progress.sql').read_text())
        db.execute("INSERT INTO naver_auto_meta VALUES ('schema_version','11')")
        for cid, day, status, size in ((1,'2026-10-04','reading',30),(2,'2026-10-04','blocked',0),
                (3,'2026-10-04','consumed',0),(4,'2026-10-03','reading',100),
                (5,'2026-10-04','PRIVATE_STATUS',7),(6,'2026-10-04','PRIVATE_OTHER',8)):
            db.execute("INSERT INTO naver_auto_morning_progress VALUES(?,987654321,?,'PRIVATE_BINDING',"
                       "'PRIVATE_FINGERPRINT',2,?,'PRIVATE_TIME',?)", (cid,day,status,size))
        for cid, kind, slot, generation, body in ((1,'daily',1,2,'PRIVATE_BODY'),
                (1,'daily',2,1,'OLD_BODY'),(1,'daily',3,2,None),(1,'summary',0,2,'PRIVATE_BODY'),
                (4,'daily',1,2,'OTHER_DAY'),(99,'daily',1,2,'ORPHAN'),
                (5,'PRIVATE_KIND',1,2,'PRIVATE_BODY'),(6,'PRIVATE_OTHER',1,2,'PRIVATE_BODY')):
            db.execute("INSERT INTO naver_auto_morning_chunk VALUES(?,?,?,?,?,'PRIVATE_CHECKSUM',10)",
                       (cid,kind,slot,generation,body))
        db.commit()
        before = db.total_changes
        scope = dict(_A=sqlite3)
        exec(fixture['new_observed_unsealed']['authorizer'], scope)
        db.set_authorizer(scope['_authorizer'](scope['PHASE_READ']))
        result = M.collect_morning_progress(db, '2026-10-04')
        self.assertEqual(result, dict(day='2026-10-04',
            scope='today_current_generation_not_run_completion',
            states={'reading':dict(accounts=1,payload_bytes=30),'blocked':dict(accounts=1,payload_bytes=0),
                    'consumed':dict(accounts=1,payload_bytes=0),'UNRECOGNIZED':dict(accounts=2,payload_bytes=15)},
            current_chunks={'daily':1,'summary':1,'UNRECOGNIZED':2}))
        self.assertEqual(M.morning_progress_projection(result,'2026-10-04'), result)
        self.assertEqual(db.total_changes, before)
        for private in ('PRIVATE','OLD_BODY','ORPHAN','987654321','customer_id','possibility_id','binding','fingerprint'):
            self.assertNotIn(private, json.dumps(result))
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE naver_auto_morning_progress SET payload_bytes=0")
        db.set_authorizer(None)
        db.execute("UPDATE naver_auto_meta SET value='10'")
        with self.assertRaisesRegex(ValueError, '^COLLECTION_MORNING_SCHEMA$'):
            M.collect_morning_progress(db, '2026-10-04')
        db.execute("UPDATE naver_auto_meta SET value='11'")
        db.execute("UPDATE naver_auto_morning_progress SET payload_bytes=-1 WHERE customer_id=5")
        with self.assertRaisesRegex(ValueError, '^COLLECTION_MORNING_BYTES$'):
            M.collect_morning_progress(db, '2026-10-04')

    def test_morning_projection_rejects_leaks_bad_numbers_and_completion_claims(self):
        value = dict(day='2026-10-04',scope='today_current_generation_not_run_completion',
                     states={'reading':dict(accounts=1,payload_bytes=30)},current_chunks={'daily':1})
        for mutate in (lambda v:v.update(customer_id=987654321),lambda v:v.update(day='2026-10-03'),
                lambda v:v.update(scope='completed_accounts'),lambda v:v['states'].update(PRIVATE={}),
                lambda v:v['states']['reading'].update(accounts=True),
                lambda v:v['states']['reading'].update(payload_bytes=-1),
                lambda v:v['states']['reading'].update(payload_bytes=2**63),
                lambda v:v['states']['reading'].update(body='PRIVATE'),
                lambda v:v['current_chunks'].update(PRIVATE=1),lambda v:v['current_chunks'].update(daily=False)):
            changed=json.loads(json.dumps(value)); mutate(changed)
            with self.subTest(value=changed), self.assertRaises(ValueError) as caught:
                M.morning_progress_projection(changed,'2026-10-04')
            self.assertNotIn('PRIVATE',str(caught.exception))

    def test_complete_emitted_script_executes_policy_and_sql_under_the_actual_reader_authorizer(self):
        result, output = self.complete_emitted_fixture()
        result = M.project(result)
        self.assertEqual(result['catalog_links']['can_confirm'], 4)
        self.assertEqual(result['managed_catalog_links']['can_confirm'], 4)
        self.assertEqual(result['daily_limited']['current_daily_targets'], 1)
        self.assertEqual(result['morning_progress'], dict(day=result['today'],
            scope='today_current_generation_not_run_completion',states={},current_chunks={}))
        self.assertEqual(result['reports'], {kind:dict(period_key=None,latest_company_reports=0,
            versions=dict(v1=0,v2=0,unknown=0),latest_generated_at=None) for kind in ('weekly','monthly')})
        self.assertNotIn('PRIVATE', output)

    def complete_emitted_fixture(self, *, deny_json=False, close_fails=False, deny_glob=False, login_rows=()):
        fixture = json.loads((Path(__file__).with_name('fixtures')/'naver_schema10_11_contract.json').read_text())
        db = sqlite3.connect(':memory:', isolation_level=None)
        self.addCleanup(db.close)
        for sql in fixture['new_observed_unsealed']['sql']:
            db.execute(sql)
        db.executescript((Path(__file__).with_name('fixtures')/'naver_monitoring_progress.sql').read_text())
        db.execute("INSERT INTO naver_auto_meta VALUES ('schema_version','11')")
        if deny_json:
            db.execute("INSERT INTO naver_auto_report_snapshot (possibility_id,period_key,"
                "generated_at,status,payload_json,revision_fingerprint,review_status) VALUES (987654321,"
                "'weekly:2026-09-21:2026-09-27',"
                "'2026-10-04T10:00:00+09:00','partial','{\"format_version\":2,\"private\":\"PRIVATE\"}','PRIVATE','ready')")
        for row in login_rows:
            db.execute('INSERT INTO naver_auto_access_log (at,emp_idx,action,target_kind,target_id,result) VALUES (?,?,?,?,?,?)', row)
        scope = dict(_A=sqlite3)
        exec(fixture['new_observed_unsealed']['authorizer'], scope)
        actual_authorizer = scope['_authorizer'](scope['PHASE_READ'])
        def authorize(action, arg1, arg2, database, source):
            if action == sqlite3.SQLITE_FUNCTION and ((deny_json and arg2 == 'json_valid') or (deny_glob and arg2 == 'glob')):
                return sqlite3.SQLITE_DENY
            return actual_authorizer(action, arg1, arg2, database, source)
        db.set_authorizer(authorize)
        before = db.total_changes
        context, rules = self.monitoring_catalog_fixture()
        rules.W.load_org = lambda store: context.ctx.org
        rules.SC.scope_of = lambda org, actor: context.scope
        rules.load = lambda *args, **kwargs: context
        reader = types.SimpleNamespace(_conn=db, meta=lambda key:'11', close=Mock())
        if close_fails:
            reader.close.side_effect = RuntimeError('PRIVATE cleanup error /path/987654321')
        engine = types.ModuleType('naver_engine')
        engine.store = types.SimpleNamespace(open_reader=lambda path:reader)
        engine.catalog_links = rules
        engine.management = types.SimpleNamespace(DAILY_STAGES=frozenset(('진행중','전략관리','사후관리','재계약진행중')))
        engine.management_store = types.SimpleNamespace(snapshot=lambda *args: {
            1:dict(source_current=True, decision=types.SimpleNamespace(cadence='daily'),
                   stage_revision='synthetic',possibility_id=11)})
        output = io.StringIO()
        original_resolve = Path.resolve
        def resolve(path, *args, **kwargs):
            # The synthetic request is absent; macOS maps /var to /private/var unlike the deployment host.
            if str(path) == '/var/lib/naver-engine/bootstrap-request.json':
                return path
            return original_resolve(path, *args, **kwargs)
        with patch.dict(sys.modules, {'naver_engine':engine}), patch.object(sys,'path',list(sys.path)), \
                patch.dict(os.environ, {}), patch.object(os,'geteuid',return_value=10001), \
                patch.object(Path,'resolve',resolve), patch.object(os,'open',side_effect=FileNotFoundError), \
                contextlib.redirect_stdout(output):
            exec(compile(M.script(catalog_links=True,daily_limited=True,morning_progress=True,reports=True,
                                  login_audit=True),'<complete-status-script>','exec'), {})
        self.assertEqual(db.total_changes, before)
        self.assertFalse(db.in_transaction)
        reader.close.assert_called_once()
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE naver_auto_meta SET value='12'")
        return json.loads(output.getvalue()), output.getvalue()

    def test_native_policy_refusals_are_bounded_and_allowed_must_still_agree(self):
        context, rules = self.monitoring_catalog_fixture()
        context.visible_ids = frozenset({1})
        for native, projected in (('account-claimed-elsewhere','other_claim'),
                                  ('pair-already-decided','existing_decision'),
                                  ('contract-end-unreadable','legacy_end_unreadable')):
            rules.block_reason = lambda *args, reason=native: reason
            rules.allowed = lambda *args: False
            self.assertEqual(M.catalog_link_counts(context,rules)['rejected'], {projected:1})
        for reason, allowed in (('PRIVATE_REASON',False),(None,False),('account-unavailable',True)):
            rules.block_reason = lambda *args, reason=reason: reason
            rules.allowed = lambda *args, value=allowed: value
            with self.assertRaisesRegex(ValueError, '^CATALOG_LINK_RULE_MISMATCH$'):
                M.catalog_link_counts(context,rules)

    def test_managed_catalog_counts_use_current_four_stages_without_changing_all_counts(self):
        context, rules = self.catalog_fixture()
        context.companies[1]['stage']='진행 중'
        context.companies[2]['stage']='계약 만료'
        context.companies[3]['stage']='사후 관리'
        context.companies[4]['stage_hidden']=True
        all_counts=M.catalog_link_counts(context,rules)
        managed=M.catalog_link_counts(context,rules,
            managed_stages=frozenset(('진행중','사후관리','전략관리','재계약진행중')))
        self.assertEqual(all_counts['auto']+all_counts['name_different'],4)
        self.assertEqual(managed,dict(auto=1,name_different=1,can_confirm=1,
                                     rejected={'legacy_end_unreadable':1}))
        self.assertEqual(M.catalog_link_projection(managed),managed)

    def test_catalog_counts_refuse_policy_drift_unknown_reasons_and_output_fields(self):
        context, rules = self.catalog_fixture()
        value = M.catalog_link_counts(context, rules)
        for change in ({'customer_id':987654321}, {'can_confirm':True}, {'auto':-1}, {'name_different':2**63},
                       {'rejected':{'PRIVATE_REASON':1}}, {'rejected':{}}, {'can_confirm':2}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                M.catalog_link_projection(dict(value, **change))
        rules.allowed=lambda context,row: False
        with self.assertRaisesRegex(ValueError, '^CATALOG_LINK_RULE_MISMATCH$'):
            M.catalog_link_counts(context, rules)
        rules.H.eligibility_reason=lambda *args: 'PRIVATE_REASON'
        with self.assertRaisesRegex(ValueError, '^CATALOG_LINK_RULE_MISMATCH$') as error:
            M.catalog_link_counts(context, rules)
        self.assertNotIn('PRIVATE', str(error.exception))

    def test_catalog_counts_cover_ownership_collisions_decisions_and_stage_guards(self):
        for reason in ('scope_denied','permission_denied','company_or_account_unavailable','other_claim',
                       'existing_decision','stage-not-monitored','ended-end-date-unknown'):
            context, rules = self.catalog_fixture()
            context.visible_ids=frozenset({1})
            row=context.ctx.rows_by_pid[1][0]; row['allowed']=False
            if reason == 'scope_denied':
                context.scope.kind='TEAM'
            elif reason == 'permission_denied':
                rules.SC.allowed_actions=lambda *args: frozenset()
            elif reason == 'company_or_account_unavailable':
                context.ctx.accounts[row['customer_id']]['present']=0
            elif reason == 'other_claim':
                rules.W.link_holders=lambda *args: {987654399}
            elif reason == 'existing_decision':
                context.ctx.live_decisions=(types.SimpleNamespace(possibility_id=1,customer_id=row['customer_id']),)
            else:
                rules.H.eligibility_reason=lambda *args: reason
            with self.subTest(reason=reason):
                self.assertEqual(M.catalog_link_counts(context,rules),
                                 {'auto':1,'name_different':0,'can_confirm':0,'rejected':{reason:1}})


    def test_management_missing_schema10_tables_is_not_reported_as_empty_success(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE naver_auto_meta (key,value)')
        db.execute("INSERT INTO naver_auto_meta VALUES ('schema_version','9')")
        self.assertIsNone(M.collect_management(db, '2026-11-02'))
        db.execute("UPDATE naver_auto_meta SET value='10'")
        with self.assertRaises(sqlite3.OperationalError):
            M.collect_management(db, '2026-11-02')
        for schema in ('12', '010', 'PRIVATE'):
            db.execute('UPDATE naver_auto_meta SET value=?', (schema,))
            with self.assertRaisesRegex(ValueError, '^COLLECTION_SCHEMA$'):
                M.collect_management(db, '2026-11-02')

    def test_management_projection_refuses_unbounded_fields_counts_times_and_wrong_windows(self):
        today = '2026-11-02'
        value = dict(schema_version=10, jobs={key:dict(since_cycle_day=str(start), until_cycle_day=str(end),
            status_scope=scope, statuses={}, latest_checked_at=None, latest_success_at=None)
            for key, (start, end, scope) in M.management_windows(today).items()}, daily_rows=0, report_count=0,
            stored_totals_scope='all_stored_rows', target_count=None,
            target_count_reason='CURRENT_ELIGIBILITY_NOT_EVALUATED', counts_are_jobs_not_targets=True)
        self.assertEqual(M.management_projection(value, today), value)
        mutations = [lambda v:v.update(customer_id=987654321), lambda v:v.update(target_count=3),
            lambda v:v.update(daily_rows=True), lambda v:v.update(report_count=-1),
            lambda v:v.update(schema_version=True), lambda v:v.update(counts_are_jobs_not_targets=False),
            lambda v:v['jobs']['weekly'].update(since_cycle_day=today),
            lambda v:v['jobs']['daily'].update(statuses={'PRIVATE_STATUS':1}),
            lambda v:v['jobs']['daily'].update(statuses={'ok':2**63}),
            lambda v:v['jobs']['daily'].update(latest_checked_at='PRIVATE_TIMESTAMP'),
            lambda v:v['jobs']['backfill_recent'].update(statuses={'ok':1}),
            lambda v:v['jobs'].update(PRIVATE={})]
        for mutate in mutations:
            altered = json.loads(json.dumps(value)); mutate(altered)
            with self.assertRaises(ValueError) as error:
                M.management_projection(altered, today)
            self.assertNotIn('PRIVATE', str(error.exception))

    def test_schema11_recheck_purposes_and_source_wait_are_safe_readonly_aggregates(self):
        fixture = json.loads((Path(__file__).with_name('fixtures')/'naver_schema10_11_contract.json').read_text())
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        for sql in fixture['new_observed_unsealed']['sql']:
            db.execute(sql)
        db.execute("INSERT INTO naver_auto_meta VALUES ('schema_version','11')")
        kinds = ('recent', 'reconcile', 'report_weekly', 'report_monthly', 'manual', 'manual_period')
        for index, kind in enumerate(kinds):
            db.execute('''INSERT INTO naver_auto_performance_job
                (job_key,customer_id,kind,cycle_day,period_start,period_end,snapshot_at,catalog_at,
                 stage_revision,possibility_id,matching_fingerprint,status,checked_at,next_try_at,attempts)
                VALUES(?,987654321,?,'2026-11-01','2026-10-01','2026-10-31','private','private',
                       'private',987654322,'private','source_wait','2026-11-02T10:00:00+09:00',
                       '2026-11-02T10:15:00+09:00',0)''', ('private'+str(index), kind))
        db.commit()
        scope = dict(_A=sqlite3)
        exec(fixture['new_observed_unsealed']['authorizer'], scope)
        db.set_authorizer(scope['_authorizer'](scope['PHASE_READ']))
        result = M.collect_management(db, '2026-11-02')
        self.assertEqual(result['schema_version'], 11)
        for kind in kinds:
            self.assertEqual(result['jobs'][kind]['statuses'], {'source_wait':1})
        self.assertEqual(M.management_projection(result, '2026-11-02'), result)
        for forbidden in ('private', '987654321', '987654322', 'customer_id', 'generation'):
            self.assertNotIn(forbidden, json.dumps(result))

    def test_management_windows_are_sunday_based_and_script_keeps_readonly_bounded_transaction(self):
        for day, sunday in (('2026-11-01','2026-11-01'), ('2026-11-02','2026-11-01'),
                            ('2026-11-07','2026-11-01'), ('2026-11-08','2026-11-08')):
            self.assertEqual(str(M.management_windows(day)['weekly'][0]), sunday)
        script = M.script().decode()
        self.assertIn("reader=S.open_reader('/var/lib/naver-engine/engine.db')", script)
        self.assertIn('deadline=time.monotonic()+20', script)
        self.assertIn('set_progress_handler(lambda: time.monotonic()>=deadline,10000)', script)
        self.assertIn("reader._conn.execute('BEGIN')", script)
        self.assertIn("reader._conn.execute('ROLLBACK')", script)
        self.assertNotIn('open_writer', script)
        self.assertEqual(M.CATALOG_LINKS_COMMIT, '6e4b035901027fef29266de218bfb0594227a3fe')
        self.assertIn('if False:', script)
        diagnostic = M.script(catalog_links=True).decode()
        ast.parse(diagnostic)
        self.assertIn('if True:', diagnostic)
        self.assertIn("if store.meta('schema_version') != '11':", diagnostic)
        self.assertIn('scope = CL.SC.scope_of(org, 0)', diagnostic)
        self.assertNotIn('open_writer', diagnostic)
        for forbidden in ('urllib', 'requests.', 'read_naver_customer_ids', 'socket.'):
            self.assertNotIn(forbidden, diagnostic)

    def test_schema10_monday_includes_sunday_weekly_and_unfinished_backfill_40_days_without_identities(self):
        fixture = json.loads((Path(__file__).with_name('fixtures')/'naver_schema9_10_contract.json').read_text())
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        for sql in fixture['new_observed_unsealed']['sql']:
            db.execute(sql)
        db.execute("INSERT INTO naver_auto_meta VALUES ('schema_version','10')")
        stamp = '2026-11-02T10:00:00+09:00'
        rows = [('daily', '2026-11-02', 'ok'), ('daily', '2026-11-01', 'retry'),
                ('weekly', '2026-11-01', 'partial'), ('weekly', '2026-10-25', 'retry'),
                ('backfill', '2026-10-03', 'retry'), ('backfill', '2026-10-03', 'ok'),
                ('backfill', '2026-09-01', 'retry'), ('backfill', '2026-11-02', 'PRIVATE_STATUS')]
        for i, (kind, cycle, status) in enumerate(rows):
            db.execute('''INSERT INTO naver_auto_performance_job
                (job_key,customer_id,kind,cycle_day,period_start,period_end,snapshot_at,catalog_at,
                 stage_revision,possibility_id,matching_fingerprint,status,checked_at,next_try_at,attempts,bizmoney)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('PRIVATE_JOB'+str(i),987654321,kind,cycle,'2026-10-01','2026-10-01',stamp,stamp,
                 'PRIVATE_REV',987654322,'PRIVATE_MATCH',status,stamp,stamp,0,123456.75))
        db.execute("UPDATE naver_auto_performance_job SET checked_at='2026-11-01T10:00:00+09:00' WHERE kind='backfill' AND status='ok'")
        db.execute("UPDATE naver_auto_performance_job SET last_success_at=? WHERE kind='backfill' AND cycle_day='2026-10-03' AND status='retry'", (stamp,))
        db.execute('''INSERT INTO naver_auto_daily_performance
            (customer_id,day,matching_fingerprint,basic_complete,conversion_complete,conversion_attempts,checked_at,campaign_fingerprint)
            VALUES (987654321,'2026-10-01','PRIVATE_MATCH',1,0,1,?,'PRIVATE_CAMPAIGN')''', (stamp,))
        db.execute('''INSERT INTO naver_auto_report_snapshot
            (possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
            VALUES (987654322,'PRIVATE_PERIOD','PRIVATE_REV',?,'partial','pending','PRIVATE_PAYLOAD')''', (stamp,))
        db.commit()
        db.row_factory = sqlite3.Row
        scope = dict(_A=sqlite3)
        exec(fixture['new_observed_unsealed']['authorizer'], scope)
        db.set_authorizer(scope['_authorizer'](scope['PHASE_READ']))
        out = M.collect(types.SimpleNamespace(_conn=db), '2026-11-02')
        management = out['management']
        self.assertEqual(management['jobs']['daily']['statuses'], {'ok':1})
        self.assertEqual(management['jobs']['weekly']['since_cycle_day'], '2026-11-01')
        self.assertEqual(management['jobs']['weekly']['statuses'], {'partial':1})
        self.assertEqual(management['jobs']['backfill_recent']['statuses'], {'retry':1,'UNRECOGNIZED':1})
        self.assertEqual(management['jobs']['backfill_recent']['latest_success_at'], stamp)
        self.assertEqual(management['daily_rows'], 1)
        self.assertEqual(management['report_count'], 1)
        self.assertIsNone(management['target_count'])
        self.assertIs(management['counts_are_jobs_not_targets'], True)
        self.assertEqual(M.project(out), out)
        for forbidden in ('PRIVATE', '987654321', '987654322', '123456.75', 'customer_id', 'bizmoney'):
            self.assertNotIn(forbidden, json.dumps(out))

    def test_docker_nanosecond_z_timestamp_is_normalized_before_legacy_host_parser(self):
        class LegacyDatetime:
            @staticmethod
            def fromisoformat(value):
                if value.endswith('Z') or ('.' in value and len(value.split('.')[1].split('+')[0]) > 6):
                    raise ValueError('legacy parser rejects Docker timestamp')
                return datetime.fromisoformat(value)
        with patch.object(M, 'datetime', LegacyDatetime):
            self.assertEqual(M.docker_stamp('2026-10-01T06:23:45.123456789Z'), '2026-10-01T06:23:45.123456+00:00')
            self.assertEqual(M.docker_stamp('2026-10-01T06:23:45.1Z'), '2026-10-01T06:23:45.100000+00:00')
            self.assertEqual(M.docker_stamp('2026-10-01T06:23:45Z'), '2026-10-01T06:23:45+00:00')
        for value in ('SECRET', '2026-10-01', '2026-10-01T06:23:45.1234567890Z',
                      '2026-10-01T06:23:45Z SECRET', '2026-13-01T06:23:45Z', None):
            with self.assertRaisesRegex(ValueError, 'COLLECTION_TIME'):
                M.docker_stamp(value)

    def test_compose_version_diagnostics_never_export_freeform(self):
        release = Mock()
        for raw, want in ((b'2.39.4\n', '2.39.4'), (b'v2.39.4-desktop.2\n', '2.39.4-desktop.2'),
                          (b'2.39.4-SECRET', None), (b'SECRET', None), (b'x'*129, None)):
            release.command.return_value = raw
            self.assertEqual(M.compose_version(release), want)
        release.command.assert_called_with(['docker','compose','version','--short'], timeout=3)

    def test_optional_lifecycle_diagnostics_are_fixed_services_enums_and_bounded(self):
        release = Mock()
        responses = [b'ActiveState=active\nSubState=running\nResult=success\nNRestarts=0\n',
                     b'ActiveState=SECRET\nSubState=SECRET\nResult=SECRET\nNRestarts=SECRET\n',
                     RuntimeError('SECRET_FAILURE'), b'x'*4097]
        release.command.side_effect = responses
        out = M.lifecycle_status(release)
        self.assertEqual(set(out), {'docker','tunnel','engine','relay'})
        self.assertEqual(out['docker'], dict(available=True,active='active',substate='running',result='success',restarts=0))
        self.assertEqual(out['tunnel']['active'], 'UNRECOGNIZED')
        self.assertIsNone(out['tunnel']['restarts'])
        self.assertFalse(out['engine']['available'])
        self.assertFalse(out['relay']['available'])
        self.assertNotIn('SECRET', json.dumps(out))
        expected = ('docker.service','metainc-naver-erp-tunnel.service','metainc-naver-engine.service','metainc-naver-relay.service')
        for call, unit in zip(release.command.call_args_list, expected):
            self.assertEqual(call.args[0], ['/usr/bin/systemctl','show',unit,'--property=ActiveState,SubState,Result,NRestarts'])
            self.assertEqual(call.kwargs, {'timeout':3})

    def test_run_checks_approved_identity_and_reprojects_engine_output(self):
        self.check_run_diagnostics(M.CATALOG_LINKS_COMMIT)

    def test_passive_runtime_diagnosis_never_opens_database_or_executes_container_process(self):
        self.check_run_diagnostics(M.REPORTS_COMMIT, passive=True)

    def test_latency_profile_preserves_host_runtime_guards_and_partial_is_not_success(self):
        self.check_run_diagnostics(M.WRITER_RELIEF_COMMIT, latency=True)
        self.check_run_diagnostics(M.LATENCY_FIX_COMMIT, latency=True)
        self.check_run_diagnostics(M.DASHBOARD_LATENCY_FIX_COMMIT, latency=True)

    def test_dashboard_profile_preserves_host_runtime_guards_and_partial_is_not_success(self):
        self.check_run_diagnostics(M.LATENCY_FIX_COMMIT, dashboard=True)
        self.check_run_diagnostics(M.DASHBOARD_LATENCY_FIX_COMMIT, dashboard=True)

    def test_profile_commit_allowlist_stays_exact_before_any_host_action(self):
        for flag, commit in (('latency_profile_only', M.CATALOG_LINKS_COMMIT),
                             ('dashboard_profile_only', M.WRITER_RELIEF_COMMIT),
                             ('latency_profile_only', 'f3a9c321c2142ae759d9af482cde706a6af57564'),
                             ('dashboard_profile_only', 'f3a9c321c2142ae759d9af482cde706a6af57564'),
                             ('latency_profile_only', 'f'*40),
                             ('dashboard_profile_only', 'f'*40)):
            package = dict(baseline='a'*64, source_commit=commit, source_tar_gz_sha256='b'*64)
            package[flag] = True
            host, release = Mock(), Mock()
            with self.subTest(flag=flag, commit=commit):
                with self.assertRaisesRegex(ValueError, '^PROFILE_SOURCE_UNREVIEWED$'):
                    M.run(package, host, release)
                self.assertFalse(host.mock_calls)
                self.assertFalse(release.mock_calls)

    def test_incident_release_refuses_further_live_reader_diagnosis(self):
        package = dict(baseline='a'*64,source_commit=M.REPORTS_COMMIT,source_tar_gz_sha256='b'*64)
        host,release = Mock(),Mock()
        with self.assertRaisesRegex(ValueError,'^LIVE_READER_SUSPENDED$'):
            M.run(package,host,release)
        host.baseline.assert_not_called()
        release.command.assert_not_called()

    def test_run_reviewed_releases_require_new_aggregates_and_unknown_commit_gets_neither(self):
        # c21f5f0, 8dd4292, a981b35 and 25dc24d live reads stay allowed (a38c537 does not).
        for commit in ('01344b145d0b679a6ee730d7fa4b5990278dd654',
                       '1b790b864ce27766251a205259fa6a332f60f72b',
                       '0a302856c6177c4f53145abaf9ed31b6a39654f3',
                       'c21f5f05f610abf89df0c24e85c00b1bec23d01c',
                       '8dd4292d82f5f98e7b4afa44a2a66b6770eaa505',
                       'a981b35e298aa58a52b30e266792bd0f36506c5d',
                       '25dc24d8760a06b2321d4fbde481769c3ce32c34',
                       '6198be366344a82923e10ba5e323877026d82f48',
                       'e4f64e165ebdf81d4127218d5c91ff6904e75958'):
            with self.subTest(commit=commit):
                self.check_run_diagnostics(commit, {
                    'daily_limited':dict(cycle_day='2026-10-01',jobs=0,current_daily_targets=1,
                        current_target_rule='DAILY_CADENCE_AND_SAME_ATTRIBUTION_NOT_RETRY_PERMISSION',groups=[]),
                    'managed_catalog_links':dict(auto=0,name_different=0,can_confirm=0,rejected={})})
        self.check_run_diagnostics('b'*40)

    def check_run_diagnostics(self, commit, extra=None, passive=False, logs=None, latency=False, dashboard=False):
        package = dict(baseline='a'*64, source_commit=commit, source_tar_gz_sha256='c'*64)
        profile_pins=M.PROFILE_RELEASES.get(commit) if latency or dashboard else M.PASSIVE_RELEASES.get(commit)
        if profile_pins is not None:
            package.update(baseline=profile_pins[2],source_tar_gz_sha256=profile_pins[0])
        cid, image = 'd'*64, 'sha256:'+'e'*64
        rid, relay_image = '7'*64, 'sha256:'+'8'*64
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source_store=root/'naver_engine/store.py'
            source_store.parent.mkdir()
            source_store.write_bytes(b'SCHEMA_VERSION=11\n# synthetic reviewed store\n')
            source_store.chmod(0o644)
            fixture_profiles=dict(M.PROFILE_RELEASES)
            fixture_passive=dict(M.PASSIVE_RELEASES)
            if profile_pins is not None:
                destination = fixture_passive if passive else fixture_profiles
                destination[commit]=(profile_pins[0],hashlib.sha256(source_store.read_bytes()).hexdigest(),profile_pins[2])
            actual_verify=M.verify_profile_store
            files = {}
            for name in ('compose.naver-engine.yml', 'preview-engine.override.yml', 'deploy/naver-engine-backup.override.yml',
                         'compose.naver-relay.yml', 'preview-relay.override.yml'):
                path = root/name; path.parent.mkdir(exist_ok=True); path.write_bytes(b'fixture')
                files[str(path)] = hashlib.sha256(b'fixture').hexdigest()
            receipt = root/('preview-'+package['source_commit']+'.json')
            receipt.write_text(json.dumps(dict(ok=True, stage='prepared', source_commit=package['source_commit'],
                package=package, images={'engine':image,'relay':relay_image}, files=files)))
            receipt.with_name('preview-start-'+package['source_commit']+'.json').write_text(json.dumps(
                dict(ok=True, stage='internal_ready', source_commit=package['source_commit'])))
            if passive:
                package['passive_runtime_only'] = True
            if latency:
                package['latency_profile_only'] = True
            if dashboard:
                package['dashboard_profile_only'] = True
            phases=(['reader','org','scope','context','dashboard'] if dashboard else
                    ['reader','org','scope','context','me','staff_counts','bell']+['aggregate_'+key for key in M.PROFILE_AGGREGATES])
            profile=dict(state='complete',code=None,last_phase=phases[-1],elapsed_us=100,cpu_us=20,
                phases=[dict(phase=name,wall_us=1,cpu_us=1,completed=True) for name in phases],functions=[],
                aggregates={} if dashboard else {key:[0]*width for key,(_,width) in M.PROFILE_AGGREGATES.items()},
                cgroup_before={},cgroup_after={},read_only=True,authenticated_request=False,engine_process_shared=False)
            values = dict(today='2026-10-01', prospects={'total':0,'stages':{}},
                pairing={'available':False,'statuses':{},'unmatched_prospects':None}, latest_run=None,
                today_checks={'statuses':{},'reasons':{}}, bootstrap=M.bootstrap_empty('no_request'),
                catalog_links={'auto':2,'name_different':1,'can_confirm':1,'rejected':{'legacy_end_unreadable':2}})
            if commit not in M.CATALOG_LINKS_COMMITS:
                values.pop('catalog_links')
            values.update(extra or {})
            morning = dict(day=values['today'],scope='today_current_generation_not_run_completion',
                           states={},current_chunks={})
            login = dict(action='login',window_hours=24,since='2026-09-30T13:00:00+09:00',
                         until='2026-10-01T13:00:00+09:00',results={},kst_10min=[],
                         older_bucket_entries=0,unrecognized_time_entries=0)
            if commit in M.MONITORING_COMMITS:
                values['morning_progress'] = morning
                values['reports'] = {kind:dict(period_key=None,latest_company_reports=0,
                    versions=dict(v1=0,v2=0,unknown=0),latest_generated_at=None) for kind in ('weekly','monthly')}
                values['login_audit'] = login
            failures = [None,'image','mount','rootfs','output','restart','host_changed','unexpected_daily','exec_failed',
                'diagnostic','diagnostic_extra','diagnostic_stage','diagnostic_kind',
                'diagnostic_primary','diagnostic_size','diagnostic_restart','relay_changed','relay_image']
            failures.append('morning_missing' if commit in M.MONITORING_COMMITS else 'unexpected_morning')
            failures.append('reports_missing' if commit in M.MONITORING_COMMITS else 'unexpected_reports')
            failures.append('login_missing' if commit in M.MONITORING_COMMITS else 'unexpected_login')
            if 'catalog_links' in values:
                failures.append('catalog_missing')
            if extra:
                failures += ['daily_limited_missing','managed_catalog_links_missing']
            if passive:
                failures = [None,'image','mount','rootfs','restart','host_changed','relay_changed','relay_image',
                            'resource_timeout','resource_invalid','host_resources_unavailable',
                            'pid_changed','resource_identity_changed']
            if latency or dashboard:
                failures = [None,'image','mount','rootfs','restart','host_changed','exec_failed','profile_partial','output']
                if profile_pins is not None:
                    failures += ['profile_store_changed','profile_store_post_changed']
            for failure in failures:
                calls, inspections = [], []
                host, release = Mock(), Mock()
                host.baseline.return_value = package['baseline']
                if failure == 'host_changed':
                    host.baseline.side_effect = [package['baseline'],'f'*64]
                release.prepared_paths.return_value = root, receipt
                release.sha.side_effect = lambda body: hashlib.sha256(body).hexdigest()
                release.unique.side_effect = dict
                release.compose.side_effect = lambda path, name: ['docker','compose','--project-name','naver-'+name]
                def command(args, **kwargs):
                    calls.append(args)
                    if args[0] == '/usr/bin/systemctl':
                        return b'ActiveState=active\nSubState=running\nResult=success\nNRestarts=0\n'
                    if args[:3] == ['docker','compose','version']:
                        return b'2.39.4\n'
                    if args[1:3] == ['image','inspect'] and args[-1] == 'metainc/naver-relay:'+package['source_commit']:
                        return json.dumps(dict(id='sha256:'+'9'*64 if failure=='relay_image' else relay_image,
                                               user='10001:10001',source=package['source_commit'])).encode()
                    if args[1:3] == ['image','inspect']:
                        return json.dumps(dict(id=image,user='10001:10001',source='wrong' if failure=='image' else package['source_commit'])).encode()
                    if args[1] == 'compose':
                        return (rid if args[3] == 'naver-relay' else cid).encode()
                    if args[1] == 'inspect' and args[-1] == rid:
                        return json.dumps(dict(id=rid,image=relay_image,running=True,user='10001:10001',
                            project='naver-engine' if failure=='relay_changed' else 'naver-relay',service='naver-relay',
                            started='2026-10-01T04:00:00.123456789Z',oom_killed=False,restarts=0,readonly=True)).encode()
                    if args[1] == 'inspect':
                        inspections.append(1)
                        return json.dumps(dict(id=cid,image=image,running=True,user='10001:10001',project='naver-engine',
                            service='naver-engine',started='2026-10-01T13:00:00+09:00',oom_killed=False,restarts=int(failure in ('restart','diagnostic_restart') and len(inspections)>1),
                            **({'pid':1234+int(failure=='pid_changed' and len(inspections)>1)} if passive else {}),
                            readonly=failure!='rootfs',data=[dict(Type='bind',Destination='/var/lib/naver-engine',
                            Source='/legacy' if failure=='mount' else '/var/lib/metainc/naver-engine')])).encode()
                    if args[1] == 'exec':
                        ast.parse(kwargs['data'])
                        self.assertEqual(kwargs['timeout'], 30)
                        if latency or dashboard:
                            self.assertIn('signal.setitimer(signal.ITIMER_REAL,25)',kwargs['data'].decode())
                            if dashboard:
                                self.assertIn("DASH.board(ctx,reader,scope,selection='all')",kwargs['data'].decode())
                            self.assertEqual(args,['docker','exec','-i','--user','10001:10001',cid,'python','-I','-B','-'])
                            out=dict(profile)
                            if failure=='profile_partial':
                                out.update(state='partial',code='PROFILE_TIMEOUT')
                            if failure=='output':
                                out['private']='PRIVATE'
                            return json.dumps({'dashboard_profile' if dashboard else 'latency_profile':out}).encode()
                        self.assertEqual(kwargs['data'].decode().count('if True:'),
                            int(commit in M.CATALOG_LINKS_COMMITS)+int(commit in M.DAILY_LIMITED_COMMITS)
                            +3*int(commit in M.MONITORING_COMMITS))
                        self.assertEqual(args, ['docker','exec','-i','--user','10001:10001',cid,'python','-I','-B','-'])
                        if failure and failure.startswith('diagnostic'):
                            diagnostic = {'diagnostic_failure':dict(stage='reports',
                                error_kind='OperationalError',sqlite_primary='SQLITE_INTERRUPT')}
                            if failure == 'diagnostic_extra':
                                diagnostic['collection'] = values
                            if failure in ('diagnostic_stage','diagnostic_kind','diagnostic_primary'):
                                key = {'diagnostic_stage':'stage','diagnostic_kind':'error_kind',
                                       'diagnostic_primary':'sqlite_primary'}[failure]
                                diagnostic['diagnostic_failure'][key] = 'PRIVATE SQL /path/987654321'
                            if failure == 'diagnostic_size':
                                return json.dumps(diagnostic).encode()+b' '*32768
                            return json.dumps(diagnostic).encode()
                        if failure == 'catalog_missing':
                            return json.dumps({key:value for key,value in values.items() if key != 'catalog_links'}).encode()
                        if failure in ('daily_limited_missing','managed_catalog_links_missing'):
                            return json.dumps({key:value for key,value in values.items() if key != failure[:-8]}).encode()
                        if failure == 'unexpected_daily':
                            return json.dumps(dict(values,daily_limited={'PRIVATE':'PRIVATE'})).encode()
                        if failure == 'morning_missing':
                            return json.dumps({key:value for key,value in values.items() if key != 'morning_progress'}).encode()
                        if failure == 'unexpected_morning':
                            return json.dumps(dict(values,morning_progress=morning)).encode()
                        if failure == 'reports_missing':
                            return json.dumps({key:value for key,value in values.items() if key != 'reports'}).encode()
                        if failure == 'unexpected_reports':
                            return json.dumps(dict(values,reports={kind:dict(period_key=None,latest_company_reports=0,
                                versions=dict(v1=0,v2=0,unknown=0),latest_generated_at=None)
                                for kind in ('weekly','monthly')})).encode()
                        if failure == 'login_missing':
                            return json.dumps({key:value for key,value in values.items() if key != 'login_audit'}).encode()
                        if failure == 'unexpected_login':
                            return json.dumps(dict(values,login_audit=login)).encode()
                        return json.dumps(dict(values, secret='SECRET') if failure=='output' else values).encode()
                    self.fail('unexpected command')
                release.command.side_effect = command
                def cgroup_resources(identity,state,guard,**kwargs):
                    self.assertTrue(passive)
                    self.assertEqual(identity,cid)
                    self.assertEqual(state['pid'],1234)
                    guard.update(synthetic_guard='PRIVATE')
                    return dict(available=True,cpu_quota_usec=50000,cpu_period_usec=100000)
                def capture(args, **kwargs):
                    if passive:
                        self.assertNotEqual(args[:2],['docker','exec'])
                    if args[:2] == ['docker','stats']:
                        calls.append(args)
                        self.assertTrue(passive)
                        expected = [cid] if failure in ('relay_changed','relay_image') else [cid,rid]
                        self.assertEqual(args,['docker','stats','--no-stream','--no-trunc','--format',
                                               M.RESOURCE_FORMAT,*expected])
                        self.assertGreater(kwargs['timeout'],0)
                        self.assertLessEqual(kwargs['timeout'],4)
                        self.assertIn('absolute_deadline',kwargs)
                        self.assertEqual((kwargs['stdout_limit'],kwargs['stderr_limit']),(4096,4096))
                        raw = self.resource_raw() if len(expected)==2 else self.resource_raw().split(b'\n')[0]
                        return dict(exit_code=None if failure=='resource_timeout' else 0,
                            reason='PROCESS_TIMEOUT' if failure=='resource_timeout' else None,
                            stdout=b'PRIVATE' if failure=='resource_invalid' else raw,stderr=b'PRIVATE')
                    if args[:2] != ['docker','exec']:
                        self.assertTrue(args[0]=='/usr/bin/journalctl' or args[:2]==['docker','logs'])
                        self.assertEqual(kwargs['timeout'],5)
                        if args[:2] == ['docker','logs']:
                            # Only identity-verified containers are read, always with per-line timestamps.
                            self.assertEqual(args[:-1], ['docker','logs','--since','24h','--tail','300','--timestamps'])
                            self.assertIn(args[-1], (cid,) if failure in ('relay_changed','relay_image') else (cid,rid))
                            return dict(exit_code=0,reason=None,stdout=(logs or {}).get(args[-1],b''),stderr=b'')
                        return dict(exit_code=0,reason=None,stdout=b'',stderr=b'')
                    if failure == 'exec_failed':
                        return dict(exit_code=1,reason=None,stdout=b'',stderr=b'NameError: PRIVATE\n')
                    if failure == 'profile_store_post_changed':
                        source_store.write_bytes(b'PRIVATE altered store')
                    return dict(exit_code=0,reason=None,stdout=command(args, **kwargs),stderr=b'')
                with self.subTest(failure=failure), patch.object(M.os, 'geteuid', return_value=0), \
                        patch.object(M,'PROFILE_RELEASES',fixture_profiles), \
                        patch.object(M,'PASSIVE_RELEASES',fixture_passive), \
                        patch.object(M,'verify_profile_store',side_effect=lambda root,digest:
                            actual_verify(root,digest,uid=os.getuid(),gid=os.getgid())), \
                        patch.object(M, 'capture_process', side_effect=capture), \
                        patch.object(M,'engine_cgroup_resources',side_effect=cgroup_resources), \
                        patch.object(M,'resource_identity_unchanged',return_value=failure!='resource_identity_changed') as identity_check, \
                        patch.object(M.os,'cpu_count',return_value=None if failure=='host_resources_unavailable' else 8), \
                        patch.object(M.os,'getloadavg',return_value=(1.,2.,3.)):
                    if failure == 'profile_store_changed':
                        original=source_store.read_bytes();source_store.write_bytes(b'PRIVATE altered store')
                        with self.assertRaisesRegex(ValueError,'^PROFILE_STORE_CHANGED$'):
                            M.run(package,host,release)
                        self.assertFalse(any(args[:2]==['docker','exec'] for args in calls))
                        self.assertEqual(len(inspections),0)
                        source_store.write_bytes(original)
                    elif failure == 'profile_store_post_changed':
                        result=M.run(package,host,release)
                        self.assertFalse(result['ok'])
                        self.assertEqual(result['postflight']['code'],'POST_SOURCE_CHANGED')
                        self.assertFalse(result['postflight']['profile_source_store_unchanged'])
                        self.assertEqual(result['mutations'],0)
                        self.assertNotIn('PRIVATE',json.dumps(result))
                    elif failure == 'exec_failed':
                        result = M.run(package, host, release)
                        self.assertFalse(result['ok'])
                        self.assertEqual(result['process_failure']['error_kind'], 'NameError')
                        self.assertEqual(result['lifecycle']['engine']['active'], 'active')
                        self.assertEqual(len(result['recent_runtime_logs']['sources']),4)
                        self.assertNotIn('collection', result)
                        self.assertNotIn('PRIVATE', json.dumps(result))
                        self.assertEqual(len(inspections), 2)
                    elif failure == 'diagnostic':
                        result = M.run(package, host, release)
                        self.assertEqual({key:result[key] for key in ('ok','mode','source_commit','stage',
                            'error_kind','sqlite_primary','mutations','existing_app_baseline_unchanged')},
                            dict(ok=False, mode='collection-status',source_commit=commit,
                            stage='reports',error_kind='OperationalError',sqlite_primary='SQLITE_INTERRUPT',
                            mutations=0,existing_app_baseline_unchanged=True))
                        self.assertEqual(result['lifecycle']['engine']['active'], 'active')
                        self.assertEqual(len(inspections), 2)
                        self.assertNotIn('collection', result)
                        self.assertNotIn('PRIVATE', json.dumps(result))
                    elif failure == 'profile_partial':
                        result = M.run(package, host, release)
                        self.assertFalse(result['ok'])
                        self.assertEqual(result['mode'],'dashboard-profile' if dashboard else 'latency-profile')
                        self.assertEqual(result['dashboard_profile' if dashboard else 'latency_profile']['code'],'PROFILE_TIMEOUT')
                        self.assertEqual(len(inspections),2)
                    elif failure in ('restart','diagnostic_restart','host_changed'):
                        result = M.run(package, host, release)
                        self.assertFalse(result['ok'])
                        self.assertEqual(result['postflight']['container_unchanged'],failure=='host_changed')
                        self.assertEqual(result['existing_app_baseline_unchanged'],failure!='host_changed')
                        self.assertEqual(result['engine_state_after']['container_restarts'],int(failure!='host_changed'))
                        self.assertNotIn('collection',result)
                        self.assertEqual(result['postflight']['code'],'POST_BASELINE')
                    elif failure in ('pid_changed','resource_identity_changed'):
                        result=M.run(package,host,release)
                        self.assertFalse(result['ok'])
                        self.assertFalse(result['database_opened'])
                        self.assertEqual(result['mutations'],0)
                        self.assertEqual(result['postflight']['code'],
                            'POST_BASELINE' if failure=='pid_changed' else 'POST_RESOURCE_IDENTITY')
                        self.assertEqual(result['postflight']['container_unchanged'],failure!='pid_changed')
                        self.assertEqual(identity_check.call_count,1)
                        self.assertNotIn('PRIVATE',json.dumps(result))
                    elif failure in ('relay_changed','relay_image'):
                        # Relay evidence is optional: an unverified relay never blocks the engine diagnosis.
                        result = M.run(package, host, release)
                        self.assertTrue(result['ok'])
                        code = 'RELAY_CONTAINER_CHANGED' if failure == 'relay_changed' else 'RELAY_IMAGE_CHANGED'
                        self.assertEqual(result['relay_state'], {'verified':False,'code':code})
                        self.assertEqual(result['recent_runtime_logs']['sources'][3],
                                         dict(unit='relay',source='docker',available=False,code=code))
                        if passive:
                            self.assertTrue(result['resource_sample']['containers']['engine']['available'])
                            self.assertFalse(result['resource_sample']['containers']['relay']['available'])
                    elif failure in ('resource_timeout','resource_invalid','host_resources_unavailable'):
                        result = M.run(package,host,release)
                        self.assertTrue(result['ok'])
                        self.assertFalse(result['database_opened'])
                        self.assertEqual(result['mutations'],0)
                        self.assertEqual(len(inspections),2)
                        self.assertEqual(host.baseline.call_count,2)
                        self.assertNotIn('PRIVATE',json.dumps(result))
                        resources = result['resource_sample']
                        if failure=='host_resources_unavailable':
                            self.assertEqual(resources['host'],dict(available=False,code='HOST_RESOURCE_UNAVAILABLE'))
                            self.assertTrue(resources['containers']['engine']['available'])
                        else:
                            code = 'RESOURCE_SAMPLE_TIMEOUT' if failure=='resource_timeout' else 'RESOURCE_SAMPLE_INVALID'
                            self.assertEqual(resources['containers'],{name:dict(available=False,code=code)
                                                                      for name in ('engine','relay')})
                    elif failure:
                        with self.assertRaises(ValueError):
                            M.run(package, host, release)
                    else:
                        result = M.run(package, host, release)
                        if passive:
                            self.assertNotIn('collection',result)
                            self.assertFalse(result['database_opened'])
                            self.assertEqual(result['mode'],'runtime-diagnostics')
                            self.assertTrue(result['resource_sample']['containers']['engine']['available'])
                            self.assertTrue(result['resource_sample']['containers']['relay']['available'])
                            self.assertEqual(host.baseline.call_count,2)
                        elif latency or dashboard:
                            self.assertEqual(result['mode'],'dashboard-profile' if dashboard else 'latency-profile')
                            self.assertEqual(result['dashboard_profile' if dashboard else 'latency_profile'],profile)
                            self.assertEqual(result['reader_mode'],'store-mode-ro-authorizer')
                        else:
                            self.assertEqual(result['collection'], values)
                        self.assertEqual(result['mutations'], 0)
                        self.assertEqual(result['lifecycle']['engine']['active'], 'active')
                        self.assertEqual(result['compose_version'], '2.39.4')
                        self.assertEqual(result['engine_state'], {'started_at':'2026-10-01T13:00:00+09:00', 'oom_killed':False})
                        self.assertEqual(result['relay_state'], {'verified':True,'started_at':'2026-10-01T04:00:00.123456+00:00',
                                                                 'running':True,'oom_killed':False,'container_restarts':0})
                        sources = [(item['unit'],item['source'],item['available']) for item in result['recent_runtime_logs']['sources']]
                        self.assertEqual(sources, [('engine','journal',True),('relay','journal',True),
                                                   ('engine','docker',True),('relay','docker',True)])
                        for item in result['recent_runtime_logs']['sources']:
                            self.assertEqual('templates' in item, item['source'] == 'docker')
                        if logs:
                            self.run_log_results.append(result)
                if failure in ('image','mount','rootfs'):
                    self.assertFalse(any(args[1]=='exec' for args in calls))

    def test_fixed_request_receipt_reader_refuses_links_modes_and_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            request, directory = root/'request.json', root/'bootstrap'
            request.write_text(json.dumps(dict(request_id='a'*32, hold_id=9, hold_sha256='b'*64,
                expected_rows=3, approved_by=0, expires_at='2026-10-01T15:00:00+09:00', max_seconds=60)))
            request.chmod(0o440)
            args = dict(request_uid=os.getuid(), runtime_uid=os.getuid(), gid=os.getgid())
            self.assertEqual(M.read_bootstrap(request, directory, **args)['state'], 'not_started')
            directory.mkdir(mode=0o700)
            started = directory/('bootstrap-'+'a'*32+'.json')
            body = dict(status='started', phase='preflight', request_id='a'*32, hold_id=9,
                        expected_rows=3, approved_by=0, started_at='2026-10-01T13:00:00+09:00')
            started.write_text(json.dumps(body)); started.chmod(0o600)
            self.assertEqual(M.read_bootstrap(request, directory, **args)['state'], 'started_without_result')
            started.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'BOOTSTRAP_FILE'):
                M.read_bootstrap(request, directory, **args)
            started.chmod(0o600)
            started.write_text(json.dumps(dict(body, hold_id=10)))
            with self.assertRaisesRegex(ValueError, 'BOOTSTRAP_IDENTITY'):
                M.read_bootstrap(request, directory, **args)
            link = root/'link.json'; link.symlink_to(request)
            with self.assertRaisesRegex(ValueError, 'BOOTSTRAP_PATH'):
                M.read_bootstrap(link, directory, **args)

    def test_package_cannot_select_another_database_or_receipt(self):
        package = dict(baseline='a'*64, source_commit='b'*40, source_tar_gz_sha256='c'*64)
        host, release = Mock(), Mock()
        for extra in ({'database':'/legacy'}, {'request_id':'d'*32}, {'source_commit':'../bad'}):
            with self.assertRaises(ValueError):
                M.run(dict(package, **extra), host, release)
        release.command.assert_not_called()

    def test_memory_script_and_bootstrap_projection_never_echo_receipt_identity(self):
        module = types.ModuleType('memory_collection')
        exec(compile(SPEC.loader.get_source('collection_status'), '<approved>', 'exec'), module.__dict__)
        ast.parse(module.script())
        started = dict(status='started', phase='preflight', request_id='a'*32, hold_id=9,
                       expected_rows=3, approved_by=0, started_at='2026-10-01T13:00:00+09:00')
        out = module.project_bootstrap(started, None)
        self.assertEqual(out['state'], 'started_without_result')
        self.assertNotIn('request_id', out)
        result = dict(started, status='partial', phase='finished', collection_outcome='done',
                      collection_counts={'ok':2,'account_error':1,'SECRET_CUSTOMER':987654321},
                      codes=['ACCOUNT_ERROR','SECRET_ERROR'], error_code='SECRET_FAILURE',
                      finished_at='2026-10-01T13:01:00+09:00')
        out = module.project_bootstrap(started, result)
        self.assertEqual(out['state'], 'partial')
        self.assertEqual(out['collection_counts'], {'ok':2,'account_error':1})
        self.assertEqual(out['error_code'], 'UNRECOGNIZED')
        self.assertNotIn('SECRET', json.dumps(out))
        self.assertNotIn('987654321', json.dumps(out))

    def test_counts_do_not_export_source_rows_or_freeform_codes(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript('''
          CREATE TABLE naver_auto_meta(key,value);
          INSERT INTO naver_auto_meta VALUES('schema_version','9');
          CREATE TABLE naver_auto_prospect(possibility_id, name, stage_key, present);
          CREATE TABLE naver_auto_pairing_run(pairing_id, outcome);
          CREATE TABLE naver_auto_pairing_row(pairing_id, possibility_id, state);
          CREATE TABLE naver_auto_check_run(run_id,run_date,status,started_at,finished_at,accounts_total,accounts_ok,error_kind);
          CREATE TABLE naver_auto_account_day(day,status,rules_not_run);
          INSERT INTO naver_auto_prospect VALUES(987654321,'SECRET_NAME','진행중',1),(987654322,'SECRET_NAME','SECRET_STAGE',1);
          INSERT INTO naver_auto_pairing_run VALUES(1,'accepted');
          INSERT INTO naver_auto_pairing_row VALUES(1,987654321,'candidate');
          INSERT INTO naver_auto_check_run VALUES(1,'2026-10-01','failed','2026-10-01T13:00:00+09:00','2026-10-01T13:01:00+09:00',1,0,'SECRET_ERROR');
          INSERT INTO naver_auto_account_day VALUES('2026-10-01','partial','[["bizmoney","stats-unread"],["other","stats-unread"],["x","SECRET_REASON"]]');
        ''')
        db.set_authorizer(lambda action,*args: sqlite3.SQLITE_OK if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION) else sqlite3.SQLITE_DENY)
        out = M.collect(types.SimpleNamespace(_conn=db), '2026-10-01')
        self.assertEqual(out['prospects']['total'], 2)
        self.assertEqual(out['prospects']['stages']['UNRECOGNIZED'], 1)
        self.assertEqual(out['pairing']['unmatched_prospects'], 1)
        self.assertEqual(out['today_checks']['reasons'], {'stats-unread':1,'UNRECOGNIZED':1})
        self.assertEqual(out['latest_run']['codes'], ['UNRECOGNIZED'])
        self.assertIsNone(out['management'])
        self.assertNotIn('SECRET', json.dumps(out))
        self.assertNotIn('987654321', json.dumps(out))

    # ── a981b35 기록 틀 갈래(엔진·중계 컨테이너 출력) · 로그인 기록 집계 ──
    ENGINE_SAMPLE = [
        ('2026-10-06T00:05:01.100000000Z', 'ERROR naver_engine.web 화면 API 응답 만들기 실패: TypeError'),
        ('2026-10-06T00:05:02Z', 'WARNING naver_engine.web 화면 API 저장소 거절: StoreRefused'),
        ('2026-10-06T00:05:03Z', 'WARNING naver_engine.web 화면 API 저장소 오류: StoreError'),
        ('2026-10-06T00:05:04Z', 'WARNING naver_engine.web 화면 API 저장소 오류: 가나상회농업회사법인'),
        # 25dc24d: store busy now leaves one line in the same shape (it used to answer 503 without a line).
        ('2026-10-06T00:05:05Z', 'WARNING naver_engine.web 화면 API 저장소 바쁨: StoreBusy'),
        ('2026-10-06T00:05:06Z', 'WARNING naver_engine.web 화면 API 저장소 바쁨: StoreBusy 가나상회'),
        ('2026-10-05T23:41:00Z', 'ERROR naver_engine.web 화면 API 뜻밖의 오류: KeyError'),
        ('2026-10-06T00:15:00Z', 'ERROR naver_engine.web 화면 API 뜻밖의 오류: KeyError'),
        ('2026-10-06T00:16:00Z', "ERROR naver_engine.web 화면 API 뜻밖의 오류: KeyError 'customer 987654321'"),
        ('2026-10-06T00:17:00Z', 'WARNING naver_engine.web 열람·쓰기 기록 실패: TimeoutError'),
        ('2026-10-06T00:17:30Z', 'WARNING naver_engine.web 열람·쓰기 기록 실패: acct_987654321'),
        ('2026-10-06T00:18:00Z', 'WARNING naver_engine.web 요청한 곳 머리를 믿지 않음 — 믿을 연결이 아님(소켓 서버 표지·루프백 확인)'),
        ('2026-10-06T00:19:00Z', 'WARNING naver_engine.web 미리보기 실패: URLError'),
        ('2026-10-06T00:20:00Z', 'ERROR naver_runtime 예약 회차 실패: StoreBusy'),
        ('2026-10-06T00:21:00Z', 'ERROR naver_runtime.scheduler 예약 작업 실패: reports OperationalError'),
        ('2026-10-06T00:22:00Z', 'ERROR naver_runtime.scheduler 예약 작업 실패 기록을 저장하지 못했습니다'),
        ('2026-10-06T00:23:00Z', 'WARNING naver_engine.read [네이버 읽기] 속도 제한이 몰려 5분 멈춤(이번 회차 1번째)'),
        ('2026-10-06T00:24:00Z', 'WARNING naver_engine.read [네이버 읽기] KEY_REJECTED /ncc/campaigns/{no} HTTP 403 코드 1018 계정 …4321'),
        ('2026-10-06T00:25:00Z', 'WARNING naver_engine.read [네이버 읽기] BAD_REQUEST /ncc/ads HTTP 400 코드 PRIVATE_CODE 계정 …9876'),
        ('2026-10-06T00:26:00Z', 'WARNING naver_engine.read [네이버 읽기] OTHER /ncc/x HTTP 40000 코드 None 계정 …5555'),
        ('2026-10-06T00:27:00Z', '{"error": "startup-refused", "kind": "ConfigError"}'),
        ('2026-10-06T00:28:00Z', 'Traceback (most recent call last):'),
        ('2026-10-06T00:29:00Z', '서울 강남구 테헤란로 PRIVATE token=SECRET staff=24680 https://dashboard.metainc.co.kr/naver/?c=987654321'),
        ('2026-10-06T00:30:00Z', '관제 엔진 중계 실패: engine-timeout')]
    RELAY_SAMPLE = [
        ('2026-10-05T23:33:50Z', 'INFO:     Started server process [1]'),
        ('2026-10-05T23:33:50Z', 'INFO:     Uvicorn running on unix socket /run/naver-relay/relay.sock (Press CTRL+C to quit)'),
        ('2026-10-06T00:40:00Z', '관제 엔진 중계 실패: relay-busy'),
        ('2026-10-06T00:41:00Z', '관제 엔진 중계 실패: engine-bad-answer'),
        ('2026-10-06T00:52:00Z', '관제 엔진 중계 실패: engine-bad-answer'),
        ('2026-10-06T00:53:00Z', '관제 엔진 중계 실패: FileNotFoundError'),
        ('2026-10-06T00:54:00Z', '관제 엔진 중계 실패: PRIVATE-987654321'),
        ('2026-10-06T00:55:00Z', 'ERROR:    Exception in ASGI application'),
        ('2026-10-06T00:56:00Z', 'GET /api/naver-auto/clients/987654321 PRIVATE 가나상회'),
        ('2026-10-06T01:00:00Z', 'INFO:     Shutting down'),
        ('2026-10-06T01:00:01Z', 'INFO:     Finished server process [1]')]
    PRIVATE_MARKERS = ('987654321','4321','9876','5555','1018','24680','PRIVATE','SECRET','가나상회','테헤란',
                       'customer','acct','/ncc','KEY_REJECTED','BAD_REQUEST','token','relay.sock','dashboard','…')

    def docker_raw(self, sample, extra=b''):
        return b'\n'.join((at+' '+message).encode() for at, message in sample)+b'\nPRIVATE line without timestamp 987654321\n'+extra

    def test_engine_container_lines_are_classified_by_exact_25dc24d_templates_without_private_values(self):
        result = M.log_projection(self.docker_raw(self.ENGINE_SAMPLE), source='docker', unit='engine')
        templates = result['templates']
        self.assertEqual(templates['template_release'], '25dc24d')
        cats = templates['categories']
        self.assertEqual(set(cats), {'web_response_failed','web_store_refused','web_store_error','web_store_busy',
            'web_unexpected_error','audit_write_failed','untrusted_source_header','preview_failed','cycle_failed',
            'job_failed','failure_record_failed','naver_rate_pause','naver_http_warning','startup_refused'})
        # Trailing raw text (twice), Traceback, free text, a relay line and the untimed line never match a template.
        self.assertEqual(templates['unmatched_entries'], 6)
        self.assertEqual(result['entries_inspected'], len(self.ENGINE_SAMPLE)+1)
        self.assertEqual(cats['web_unexpected_error'], dict(count=2, first_at='2026-10-05T23:41:00+00:00',
            last_at='2026-10-06T00:15:00+00:00', kst_10min={'2026-10-06T08:40+09:00':1,'2026-10-06T09:10+09:00':1},
            older_bucket_entries=0, kinds={'KeyError':2}, other_value_entries=0))
        self.assertEqual(cats['web_response_failed']['first_at'], '2026-10-06T00:05:01.100000+00:00')
        self.assertEqual(cats['web_store_error']['kinds'], {'StoreError':1,'UNRECOGNIZED':1})
        self.assertEqual(cats['web_store_refused']['kinds'], {'StoreRefused':1})
        self.assertEqual(cats['web_store_busy']['kinds'], {'StoreBusy':1})
        self.assertEqual(cats['web_store_busy']['kst_10min'], {'2026-10-06T09:00+09:00':1})
        self.assertEqual(cats['audit_write_failed']['kinds'], {'TimeoutError':1,'UNRECOGNIZED':1})
        self.assertEqual(cats['audit_write_failed']['kst_10min'], {'2026-10-06T09:10+09:00':2})
        self.assertEqual(cats['preview_failed']['kinds'], {'URLError':1})
        self.assertEqual(cats['cycle_failed']['kinds'], {'StoreBusy':1})
        self.assertEqual(cats['job_failed']['kinds'], {'OperationalError':1})
        self.assertEqual(cats['startup_refused']['kinds'], {'ConfigError':1})
        self.assertEqual(cats['naver_http_warning']['http_status'], {'400':1,'403':1,'UNRECOGNIZED':1})
        self.assertNotIn('kinds', cats['naver_http_warning'])
        for fixed in ('untrusted_source_header','failure_record_failed','naver_rate_pause'):
            self.assertEqual(set(cats[fixed]), {'count','first_at','last_at','kst_10min','older_bucket_entries'})
            self.assertEqual(cats[fixed]['count'], 1)
        # The earlier event view is unchanged: scheduler lines stay events, template lines are not new events.
        self.assertIn(dict(event='job_failed',stage='reports',error_kind='OperationalError',count=1), result['events'])
        self.assertIn(dict(event='cycle_failed',error_kind='StoreBusy',count=1), result['events'])
        dumped = json.dumps(result, ensure_ascii=False)
        for private in self.PRIVATE_MARKERS:
            self.assertNotIn(private, dumped)
        journal = M.log_projection(b'', source='journal', unit='engine')
        self.assertNotIn('templates', journal)

    def test_relay_container_lines_use_relay_whitelist_and_fixed_uvicorn_labels(self):
        result = M.log_projection(self.docker_raw(self.RELAY_SAMPLE), source='docker', unit='relay')
        cats = result['templates']['categories']
        self.assertEqual(set(cats), {'relay_failed','uvicorn_started','uvicorn_running','uvicorn_asgi_exception',
                                     'uvicorn_shutting_down','uvicorn_finished'})
        self.assertEqual(cats['relay_failed']['kinds'], {'engine-bad-answer':2,'FileNotFoundError':1,
                                                         'UNRECOGNIZED':1,'relay-busy':1})
        self.assertEqual(cats['relay_failed']['kst_10min'], {'2026-10-06T09:40+09:00':2,'2026-10-06T09:50+09:00':3})
        self.assertEqual(cats['uvicorn_started']['first_at'], '2026-10-05T23:33:50+00:00')
        self.assertEqual(result['templates']['unmatched_entries'], 2)
        self.assertIn(dict(event='relay_failed',error_kind='engine-bad-answer',count=2), result['events'])
        dumped = json.dumps(result, ensure_ascii=False)
        for private in self.PRIVATE_MARKERS:
            self.assertNotIn(private, dumped)
        # Engine templates do not apply to the relay and vice versa.
        engine_view = M.log_projection(self.docker_raw(self.RELAY_SAMPLE), source='docker', unit='engine')
        self.assertEqual(engine_view['templates']['categories'], {})

    def test_template_buckets_and_kind_sets_are_capped_with_explicit_remainders(self):
        sample = [('2026-10-05T%02d:%d5:00Z' % (hour, tens), 'WARNING naver_engine.web 열람·쓰기 기록 실패: '+kind)
                  for hour in range(5) for tens in range(6) for kind in ('Kind'+chr(65+(hour*6+tens) % 7),)]
        result = M.log_projection(b'\n'.join((at+' '+m).encode() for at, m in sample), source='docker', unit='engine')
        row = result['templates']['categories']['audit_write_failed']
        self.assertEqual(row['count'], 30)
        self.assertEqual(len(row['kst_10min']), M.LOG_BUCKET_MAX)
        self.assertEqual(row['older_bucket_entries'], 30-M.LOG_BUCKET_MAX)
        self.assertEqual(min(row['kst_10min']), '2026-10-05T10:00+09:00')
        self.assertEqual(len(row['kinds']), M.LOG_KIND_MAX)
        self.assertEqual(sum(row['kinds'].values())+row['other_value_entries'], 30)
        self.assertEqual(M.type_name('Error123'), 'UNRECOGNIZED')
        self.assertEqual(M.type_name('_Truncated'), '_Truncated')
        self.assertEqual(M.type_name('9Error'), 'UNRECOGNIZED')
        self.assertEqual(M.type_name('x'*65), 'UNRECOGNIZED')

    def test_relay_identity_is_checked_like_the_engine_and_failures_are_fixed_codes(self):
        commit, image = M.SCREEN_OVERHAUL_COMMIT, 'sha256:'+'8'*64
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            files = {}
            for name in ('compose.naver-relay.yml','preview-relay.override.yml'):
                (root/name).write_bytes(b'fixture'); files[str(root/name)] = hashlib.sha256(b'fixture').hexdigest()
            prepared = dict(images={'relay':image}, files=files)
            def release(ps=b'7'*64, inspect=None, error=None):
                mock = Mock()
                mock.sha.side_effect = lambda body: hashlib.sha256(body).hexdigest()
                mock.compose.side_effect = lambda path, name: ['docker','compose','--project-name','naver-'+name]
                state = dict(id='7'*64,image=image,running=True,user='10001:10001',project='naver-relay',
                             service='naver-relay',started='2026-10-05T23:33:44.5Z',oom_killed=False,restarts=0,readonly=True)
                state.update(inspect or {})
                def command(args, **kwargs):
                    if error:
                        raise error
                    if args[1:3] == ['image','inspect']:
                        return json.dumps(dict(id=image,user='10001:10001',source=commit)).encode()
                    if args[1] == 'compose':
                        return ps
                    return json.dumps(state).encode()
                mock.command.side_effect = command
                return mock
            identity, state = M.relay_container(release(), root, prepared, commit)
            self.assertEqual(identity, '7'*64)
            self.assertEqual(state, {'verified':True,'started_at':'2026-10-05T23:33:44.500000+00:00','running':True,
                                     'oom_killed':False,'container_restarts':0})
            for mock, code in ((release(ps=b'PRIVATE'), 'RELAY_CONTAINER_ID'),
                               (release(inspect={'readonly':False}), 'RELAY_CONTAINER_CHANGED'),
                               (release(inspect={'service':'naver-engine'}), 'RELAY_CONTAINER_CHANGED'),
                               (release(inspect={'restarts':'PRIVATE'}), 'RELAY_UNVERIFIED'),
                               (release(error=RuntimeError('PRIVATE /var/lib 987654321')), 'RELAY_UNVERIFIED')):
                self.assertEqual(M.relay_container(mock, root, prepared, commit), (code, {'verified':False,'code':code}))
            self.assertEqual(M.relay_container(release(), root, dict(prepared, images={}), commit)[0], 'RELAY_PREPARED_IMAGE')
            (root/'preview-relay.override.yml').write_bytes(b'changed')
            self.assertEqual(M.relay_container(release(), root, prepared, commit)[0], 'RELAY_COMPOSE_CHANGED')
        calls = []
        def capture(args, **kwargs):
            calls.append(args)
            return dict(exit_code=0,reason=None,stdout=b'',stderr=b'')
        with patch.object(M, 'capture_process', side_effect=capture):
            for relay, code in (('RELAY_IMAGE_CHANGED','RELAY_IMAGE_CHANGED'), ('PRIVATE 987654321','RELAY_NOT_CHECKED'),
                                (None,'RELAY_NOT_CHECKED')):
                calls.clear()
                out = M.recent_runtime_logs('d'*64, relay)
                self.assertEqual(out['sources'][3], dict(unit='relay',source='docker',available=False,code=code))
                self.assertEqual([args[-1] for args in calls if args[:2] == ['docker','logs']], ['d'*64])
                self.assertNotIn('PRIVATE', json.dumps(out))

    def test_passive_run_reads_both_container_samples_and_never_opens_the_database(self):
        self.run_log_results = []
        logs = {'d'*64:self.docker_raw(self.ENGINE_SAMPLE), '7'*64:self.docker_raw(self.RELAY_SAMPLE)}
        with patch.object(M.sqlite3, 'connect', side_effect=AssertionError('database opened')), \
                patch.object(M, 'collect_login_audit', side_effect=AssertionError('database read')), \
                patch.object(M, 'script', side_effect=AssertionError('reader script built')):
            self.check_run_diagnostics(M.SCREEN_OVERHAUL_COMMIT, passive=True, logs=logs)
        self.assertEqual(len(self.run_log_results), 1)
        result = self.run_log_results[0]
        self.assertFalse(result['database_opened'])
        self.assertNotIn('login_audit', json.dumps(result))
        sources = {(item['unit'],item['source']):item for item in result['recent_runtime_logs']['sources']}
        self.assertEqual(sources[('engine','docker')]['templates']['categories']['audit_write_failed']['count'], 2)
        self.assertEqual(sources[('relay','docker')]['templates']['categories']['relay_failed']['count'], 5)
        dumped = json.dumps(result, ensure_ascii=False)
        for private in self.PRIVATE_MARKERS:
            self.assertNotIn(private, dumped)

    def login_rows(self, now):
        def at(delta):
            return (now-delta).isoformat(timespec='microseconds')
        from datetime import timedelta
        return [(at(timedelta(minutes=5)),0,'login','session',None,'ok'),
                (at(timedelta(minutes=6)),987654321,'login','session',987654322,'narrowed'),
                (at(timedelta(minutes=7)),None,'login','session',None,'erp-unavailable'),
                (at(timedelta(hours=3)),None,'login','session',None,'throttled'),
                (at(timedelta(hours=3)),None,'login','session',None,'PRIVATE_RESULT_987654321'),
                (at(timedelta(hours=25)),0,'login','session',None,'ok'),
                (at(timedelta(minutes=5)),0,'board','board',None,'ok'),
                (at(timedelta(minutes=5)),0,'view','client',987654321,'ok'),
                (now.strftime('%Y-%m-%d')+' PRIVATE',0,'login','session',None,'ok')]

    def test_login_audit_counts_results_and_kst_buckets_under_the_actual_reader_authorizer(self):
        fixture = json.loads((Path(__file__).with_name('fixtures')/'naver_schema10_11_contract.json').read_text())
        db = sqlite3.connect(':memory:', isolation_level=None)
        self.addCleanup(db.close)
        for sql in fixture['new_observed_unsealed']['sql']:
            db.execute(sql)
        now = datetime.fromisoformat('2026-10-06T10:31:00.250000+09:00')
        for row in self.login_rows(now):
            db.execute('INSERT INTO naver_auto_access_log (at,emp_idx,action,target_kind,target_id,result) VALUES (?,?,?,?,?,?)', row)
        before = db.total_changes
        scope = dict(_A=sqlite3)
        exec(fixture['new_observed_unsealed']['authorizer'], scope)
        db.set_authorizer(scope['_authorizer'](scope['PHASE_READ']))
        db.execute('BEGIN')
        result = M.collect_login_audit(db, now)
        db.execute('ROLLBACK')
        self.assertEqual(db.total_changes, before)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute('DELETE FROM naver_auto_access_log')
        self.assertEqual(result['results'], {
            'ok':dict(count=2,first_at='2026-10-06T10:26:00.250000+09:00',last_at='2026-10-06T10:26:00.250000+09:00'),
            'narrowed':dict(count=1,first_at='2026-10-06T10:25:00.250000+09:00',last_at='2026-10-06T10:25:00.250000+09:00'),
            'erp-unavailable':dict(count=1,first_at='2026-10-06T10:24:00.250000+09:00',last_at='2026-10-06T10:24:00.250000+09:00'),
            'throttled':dict(count=1,first_at='2026-10-06T07:31:00.250000+09:00',last_at='2026-10-06T07:31:00.250000+09:00'),
            'UNRECOGNIZED':dict(count=1,first_at='2026-10-06T07:31:00.250000+09:00',last_at='2026-10-06T07:31:00.250000+09:00')})
        self.assertEqual(result['kst_10min'], [
            dict(bucket='2026-10-06T07:30+09:00', results={'throttled':1,'UNRECOGNIZED':1}),
            dict(bucket='2026-10-06T10:20+09:00', results={'ok':1,'narrowed':1,'erp-unavailable':1})])
        self.assertEqual((result['unrecognized_time_entries'], result['older_bucket_entries']), (1, 0))
        self.assertEqual((result['since'], result['until']),
                         ('2026-10-05T10:31:00.250000+09:00','2026-10-06T10:31:00.250000+09:00'))
        self.assertEqual(M.login_audit_projection(result), result)
        for private in ('987654321','987654322','PRIVATE','emp_idx','target','board','view','client'):
            self.assertNotIn(private, json.dumps(result))

    def test_login_audit_bucket_cap_and_projection_refuses_identities_drift_and_mismatch(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE naver_auto_access_log (log_id INTEGER PRIMARY KEY, at TEXT, emp_idx INTEGER, '
                   'action TEXT, target_kind TEXT, target_id INTEGER, result TEXT)')
        now = datetime.fromisoformat('2026-10-06T10:31:00+09:00')
        from datetime import timedelta
        for n in range(30):
            db.execute("INSERT INTO naver_auto_access_log VALUES (NULL,?,0,'login','session',NULL,'ok')",
                       ((now-timedelta(minutes=10*n+1)).isoformat(timespec='microseconds'),))
        result = M.collect_login_audit(db, now)
        self.assertEqual(len(result['kst_10min']), M.LOGIN_BUCKET_MAX)
        self.assertEqual(result['older_bucket_entries'], 30-M.LOGIN_BUCKET_MAX)
        self.assertEqual(result['results']['ok']['count'], 30)
        mutations = (lambda v:v.update(emp_idx=987654321), lambda v:v['results'].update(PRIVATE=dict(count=1,first_at=None,last_at=None)),
                     lambda v:v['results']['ok'].update(count=True), lambda v:v['results']['ok'].update(target_id=1),
                     lambda v:v['kst_10min'][0].update(bucket='PRIVATE'), lambda v:v['kst_10min'][0]['results'].update(ok=0),
                     lambda v:v['kst_10min'].reverse(), lambda v:v.update(older_bucket_entries=0),
                     lambda v:v.update(window_hours=48), lambda v:v.update(since=v['until']),
                     lambda v:v['results']['ok'].update(first_at='PRIVATE'),
                     lambda v:v['kst_10min'].extend(v['kst_10min'][:1]))
        for mutate in mutations:
            changed = json.loads(json.dumps(result)); mutate(changed)
            with self.subTest(value=changed), self.assertRaises(ValueError) as caught:
                M.login_audit_projection(changed)
            self.assertNotIn('PRIVATE', str(caught.exception))
        empty = M.collect_login_audit(db, now+timedelta(days=3))
        self.assertEqual((empty['results'], empty['kst_10min']), ({}, []))

    def test_emitted_script_adds_login_audit_and_failures_keep_the_login_stage(self):
        now = datetime.now(M.KST)
        result, output = self.complete_emitted_fixture(login_rows=self.login_rows(now))
        projected = M.project(result)
        self.assertEqual(projected['login_audit']['results']['ok']['count'], 2)
        self.assertEqual(projected['login_audit']['unrecognized_time_entries'], 1)
        self.assertNotIn('987654321', output)
        self.assertNotIn('PRIVATE', output)
        failed, output = self.complete_emitted_fixture(deny_glob=True, login_rows=self.login_rows(now))
        self.assertEqual(failed, {'diagnostic_failure':{'stage':'login_audit','error_kind':'OperationalError',
                                                        'sqlite_primary':'SQLITE_ERROR'}})
        self.assertNotIn('987654321', output)


    def test_network_log_timings_keep_latest_bounded_sample_without_new_event_groups(self):
        prefix='WARNING naver_engine.read naver_network_failure kind=TIMEOUT phase=OPEN step=BIZMONEY '
        messages=[('2026-10-07T19:35:00Z',prefix+'request_elapsed_ms=20001 remaining_ms=180000'),
                  ('2026-10-07T19:36:00Z',prefix+'request_elapsed_ms=3600000 remaining_ms=0'),
                  ('2026-10-07T19:34:00Z',prefix+'request_elapsed_ms=1 remaining_ms=3600000')]
        raw=b'\n'.join((at+' '+message).encode() for at,message in messages)
        result=M.log_projection(raw,source='docker',unit='engine')
        self.assertEqual(result['unrecognized_entries'],0)
        self.assertEqual(result['events'],[dict(event='network_failure',network_kind='TIMEOUT',
            phase='OPEN',step='BIZMONEY',count=3,latest_request_elapsed_ms=3600000,latest_remaining_ms=0)])
        category=result['templates']['categories']['naver_network_failure']
        self.assertEqual(category['count'],3)
        self.assertEqual(category['kinds'],{'TIMEOUT:OPEN:BIZMONEY':3})
        self.assertEqual(category['latest_request_elapsed_ms'],3600000)
        self.assertEqual(category['latest_remaining_ms'],0)
        self.assertNotIn('request_elapsed_ms=',json.dumps(result))
        # Both existing logger names use the same strict template, including the journal path.
        line=prefix.replace('naver_engine.read naver_network_failure',
                            'naver_engine.morning morning_network_failure')+'request_elapsed_ms=0 remaining_ms=1'
        journal=json.dumps(dict(MESSAGE=line,__REALTIME_TIMESTAMP='1791401760000000')).encode()
        projected=M.log_projection(journal,source='journal',unit='engine')
        self.assertEqual(projected['events'][0]['latest_request_elapsed_ms'],0)
        self.assertEqual(projected['events'][0]['latest_remaining_ms'],1)
        self.assertNotIn('templates',projected)

    def test_network_log_timings_reject_out_of_bounds_malformed_and_freeform_suffixes(self):
        prefix='WARNING naver_engine.read naver_network_failure kind=TIMEOUT phase=OPEN step=BIZMONEY '
        invalid=('request_elapsed_ms=3600001 remaining_ms=0',
                 'request_elapsed_ms=0 remaining_ms=3600001',
                 'request_elapsed_ms=-1 remaining_ms=0','request_elapsed_ms=1.0 remaining_ms=0',
                 'request_elapsed_ms=1e3 remaining_ms=0','request_elapsed_ms=PRIVATE remaining_ms=0',
                 'request_elapsed_ms=00000000 remaining_ms=0','remaining_ms=0 request_elapsed_ms=1',
                 'request_elapsed_ms=1 remaining_ms=0 PRIVATE_URL',
                 'request_elapsed_ms=1 remaining_ms=0\tPRIVATE_ACCOUNT')
        for suffix in invalid:
            with self.subTest(suffix=suffix):
                result=M.log_projection(('2026-10-07T19:35:00Z '+prefix+suffix).encode(),source='docker',unit='engine')
                self.assertEqual(result['events'],[])
                self.assertEqual(result['unrecognized_entries'],1)
                self.assertEqual(result['templates']['categories'],{})
                self.assertEqual(result['templates']['unmatched_entries'],1)
                self.assertNotIn('PRIVATE',json.dumps(result))
        wrong_unit=M.log_projection(('2026-10-07T19:35:00Z '+prefix+
            'request_elapsed_ms=1 remaining_ms=0').encode(),source='docker',unit='relay')
        self.assertEqual(wrong_unit['events'],[])
        self.assertEqual(wrong_unit['templates']['categories'],{})

    def test_fourth_ui_passive_diagnostics_preserve_guards_without_opening_database(self):
        commit=load('naver_preview_code_upgrade_v4').TARGET_COMMIT
        self.assertEqual(commit,'49c42d645b90732071d0c61b8f9aaf7660e8b765')
        self.check_run_diagnostics(commit,passive=True)

    def test_final74_passive_diagnostics_are_exactly_pinned_without_opening_database(self):
        code=load('naver_preview_code_upgrade_v5')
        codes=[load(name) for name in ('naver_preview_code_upgrade_v5','naver_preview_code_upgrade_v6',
                                     'naver_preview_code_upgrade_v7','naver_preview_code_upgrade_v8')]
        if M.PASSIVE_COMMIT_V9 is not None:
            codes.append(load('naver_preview_code_upgrade_v9'))
        if M.PASSIVE_COMMIT_V10 is not None:
            codes.append(load('naver_preview_code_upgrade_v10'))
        self.assertEqual(M.PASSIVE_RELEASES,{item.TARGET_COMMIT:(
            item.TARGET_SOURCE_SHA256,item.STORE_SHA256['target'],item.EXPECTED_BASELINE) for item in codes})
        self.assertNotIn(code.TARGET_COMMIT,M.PROFILE_RELEASES)
        self.check_run_diagnostics(code.TARGET_COMMIT,passive=True)

    def test_final74_passive_pin_mismatch_and_active_modes_refuse_before_host_or_process(self):
        code=load('naver_preview_code_upgrade_v5')
        good=dict(source_commit=code.TARGET_COMMIT,source_tar_gz_sha256=code.TARGET_SOURCE_SHA256,
            baseline=code.EXPECTED_BASELINE,passive_runtime_only=True)
        for field in ('source_tar_gz_sha256','baseline'):
            host,release=Mock(),Mock()
            with self.subTest(field=field),patch.object(M,'capture_process') as capture:
                with self.assertRaisesRegex(ValueError,'^PASSIVE_SOURCE_PIN_CHANGED$'):
                    M.run(dict(good,**{field:'0'*64}),host,release)
                capture.assert_not_called()
            self.assertFalse(host.mock_calls)
            self.assertFalse(release.mock_calls)
        for mode in (None,'latency_profile_only','dashboard_profile_only'):
            package={k:v for k,v in good.items() if k!='passive_runtime_only'}
            if mode: package[mode]=True
            host,release=Mock(),Mock()
            with self.subTest(mode=mode),patch.object(M,'capture_process') as capture:
                with self.assertRaisesRegex(ValueError,'^(PASSIVE_RUNTIME_ONLY|PROFILE_SOURCE_UNREVIEWED)$'):
                    M.run(package,host,release)
                capture.assert_not_called()
            self.assertFalse(host.mock_calls)
            self.assertFalse(release.mock_calls)

    def test_v6_passive_diagnostics_keep_exact_pins_and_do_not_open_database(self):
        code=load('naver_preview_code_upgrade_v6')
        self.assertEqual(M.PASSIVE_RELEASES[code.TARGET_COMMIT],(
            code.TARGET_SOURCE_SHA256,code.STORE_SHA256['target'],code.EXPECTED_BASELINE))
        self.assertNotIn(code.TARGET_COMMIT,M.PROFILE_RELEASES)
        self.check_run_diagnostics(code.TARGET_COMMIT,passive=True)

    def test_v7_passive_diagnostics_keep_exact_pins_and_do_not_open_database(self):
        code=load('naver_preview_code_upgrade_v7')
        self.assertEqual(M.PASSIVE_RELEASES[code.TARGET_COMMIT],(
            code.TARGET_SOURCE_SHA256,code.STORE_SHA256['target'],code.EXPECTED_BASELINE))
        self.assertNotIn(code.TARGET_COMMIT,M.PROFILE_RELEASES)
        self.check_run_diagnostics(code.TARGET_COMMIT,passive=True)

    def test_v7_passive_pin_mismatch_and_every_active_mode_refuse_before_host_or_process(self):
        code=load('naver_preview_code_upgrade_v7')
        good=dict(source_commit=code.TARGET_COMMIT,source_tar_gz_sha256=code.TARGET_SOURCE_SHA256,
            baseline=code.EXPECTED_BASELINE,passive_runtime_only=True)
        for field in ('source_tar_gz_sha256','baseline'):
            host,release=Mock(),Mock()
            with self.subTest(field=field),patch.object(M,'capture_process') as capture:
                with self.assertRaisesRegex(ValueError,'^PASSIVE_SOURCE_PIN_CHANGED$'):
                    M.run(dict(good,**{field:'0'*64}),host,release)
                capture.assert_not_called()
            self.assertFalse(host.mock_calls)
            self.assertFalse(release.mock_calls)
        for mode in (None,'latency_profile_only','dashboard_profile_only'):
            package={k:v for k,v in good.items() if k!='passive_runtime_only'}
            if mode: package[mode]=True
            host,release=Mock(),Mock()
            with self.subTest(mode=mode),patch.object(M,'capture_process') as capture:
                with self.assertRaisesRegex(ValueError,'^(PASSIVE_RUNTIME_ONLY|PROFILE_SOURCE_UNREVIEWED)$'):
                    M.run(package,host,release)
                capture.assert_not_called()
            self.assertFalse(host.mock_calls)
            self.assertFalse(release.mock_calls)

    def test_v8_passive_diagnostics_keep_exact_pins_and_do_not_open_database(self):
        code=load('naver_preview_code_upgrade_v8')
        self.assertEqual(M.PASSIVE_RELEASES[code.TARGET_COMMIT],(
            code.TARGET_SOURCE_SHA256,code.STORE_SHA256['target'],code.EXPECTED_BASELINE))
        self.assertNotIn(code.TARGET_COMMIT,M.PROFILE_RELEASES)
        self.check_run_diagnostics(code.TARGET_COMMIT,passive=True)

    def test_v8_passive_pin_mismatch_and_every_active_mode_refuse_before_host_or_process(self):
        code=load('naver_preview_code_upgrade_v8')
        good=dict(source_commit=code.TARGET_COMMIT,source_tar_gz_sha256=code.TARGET_SOURCE_SHA256,
            baseline=code.EXPECTED_BASELINE,passive_runtime_only=True)
        for field in ('source_tar_gz_sha256','baseline'):
            host,release=Mock(),Mock()
            with self.subTest(field=field),patch.object(M,'capture_process') as capture:
                with self.assertRaisesRegex(ValueError,'^PASSIVE_SOURCE_PIN_CHANGED$'):
                    M.run(dict(good,**{field:'0'*64}),host,release)
                capture.assert_not_called()
            self.assertFalse(host.mock_calls)
            self.assertFalse(release.mock_calls)
        for mode in (None,'latency_profile_only','dashboard_profile_only'):
            package={k:v for k,v in good.items() if k!='passive_runtime_only'}
            if mode: package[mode]=True
            host,release=Mock(),Mock()
            with self.subTest(mode=mode),patch.object(M,'capture_process') as capture:
                with self.assertRaisesRegex(ValueError,'^(PASSIVE_RUNTIME_ONLY|PROFILE_SOURCE_UNREVIEWED)$'):
                    M.run(package,host,release)
                capture.assert_not_called()
            self.assertFalse(host.mock_calls)
            self.assertFalse(release.mock_calls)

    def test_v6_passive_pin_mismatch_and_every_active_mode_refuse_before_host_or_process(self):
        code=load('naver_preview_code_upgrade_v6')
        good=dict(source_commit=code.TARGET_COMMIT,source_tar_gz_sha256=code.TARGET_SOURCE_SHA256,
            baseline=code.EXPECTED_BASELINE,passive_runtime_only=True)
        for field in ('source_tar_gz_sha256','baseline'):
            host,release=Mock(),Mock()
            with self.subTest(field=field),patch.object(M,'capture_process') as capture:
                with self.assertRaisesRegex(ValueError,'^PASSIVE_SOURCE_PIN_CHANGED$'):
                    M.run(dict(good,**{field:'0'*64}),host,release)
                capture.assert_not_called()
            self.assertFalse(host.mock_calls)
            self.assertFalse(release.mock_calls)
        for mode in (None,'latency_profile_only','dashboard_profile_only'):
            package={k:v for k,v in good.items() if k!='passive_runtime_only'}
            if mode: package[mode]=True
            host,release=Mock(),Mock()
            with self.subTest(mode=mode),patch.object(M,'capture_process') as capture:
                with self.assertRaisesRegex(ValueError,'^(PASSIVE_RUNTIME_ONLY|PROFILE_SOURCE_UNREVIEWED)$'):
                    M.run(package,host,release)
                capture.assert_not_called()
            self.assertFalse(host.mock_calls)
            self.assertFalse(release.mock_calls)

    def test_reviewed_third_and_fourth_profiles_keep_bounded_readonly_guards_and_partial_results(self):
        for module in ('naver_preview_code_upgrade_v3','naver_preview_code_upgrade_v4'):
            code=load(module)
            self.assertEqual(M.PROFILE_RELEASES[code.TARGET_COMMIT],(
                code.TARGET_SOURCE_SHA256,code.STORE_SHA256['target'],code.EXPECTED_BASELINE))
            for mode in ('latency','dashboard'):
                with self.subTest(module=module,mode=mode):
                    self.check_run_diagnostics(code.TARGET_COMMIT,**{mode:True})

    def test_new_profile_archive_and_baseline_mismatch_refuse_before_host_or_process_action(self):
        self.assertEqual(set(M.PROFILE_RELEASES),{
            '953c2ccdb1d74a4fd339de013a1bbbbc5f50e3b6','49c42d645b90732071d0c61b8f9aaf7660e8b765'})
        for commit,(archive,store,baseline) in M.PROFILE_RELEASES.items():
            for mode in ('latency_profile_only','dashboard_profile_only'):
                good=dict(source_commit=commit,source_tar_gz_sha256=archive,baseline=baseline,**{mode:True})
                for field in ('source_tar_gz_sha256','baseline'):
                    host,release=Mock(),Mock()
                    with self.subTest(commit=commit,mode=mode,field=field),patch.object(M,'capture_process') as capture:
                        with self.assertRaisesRegex(ValueError,'^PROFILE_SOURCE_PIN_CHANGED$'):
                            M.run(dict(good,**{field:'0'*64}),host,release)
                        capture.assert_not_called()
                    self.assertFalse(host.mock_calls)
                    self.assertFalse(release.mock_calls)

    def test_profile_store_hash_path_and_mode_are_verified_without_database_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();source=root/'naver_engine/store.py'
            source.parent.mkdir();body=b'SCHEMA_VERSION=11\n';source.write_bytes(body);source.chmod(0o644)
            digest=hashlib.sha256(body).hexdigest()
            args=dict(uid=os.getuid(),gid=os.getgid())
            with patch.object(M.sqlite3,'connect',side_effect=AssertionError('DB forbidden')):
                M.verify_profile_store(root,digest,**args)
                source.write_bytes(body+b' altered')
                with self.assertRaisesRegex(ValueError,'^PROFILE_STORE_CHANGED$'):
                    M.verify_profile_store(root,digest,**args)
                source.write_bytes(body);source.chmod(0o666)
                with self.assertRaisesRegex(ValueError,'^PROFILE_STORE_CHANGED$'):
                    M.verify_profile_store(root,digest,**args)
                source.chmod(0o644)
                for value in (b'',b'x'*1048577):
                    source.write_bytes(value)
                    with self.subTest(size=len(value)),self.assertRaisesRegex(ValueError,'^PROFILE_STORE_CHANGED$'):
                        M.verify_profile_store(root,digest,**args)
                source.write_bytes(body)
                hardlink=source.with_name('store-hardlink.py');os.link(source,hardlink)
                with self.assertRaisesRegex(ValueError,'^PROFILE_STORE_CHANGED$'):
                    M.verify_profile_store(root,digest,**args)
                hardlink.unlink()
                source.rename(source.with_name('store-copy.py'))
                source.symlink_to(source.with_name('store-copy.py'))
                with self.assertRaisesRegex(ValueError,'^PROFILE_STORE_CHANGED$'):
                    M.verify_profile_store(root,digest,**args)

if __name__ == '__main__':
    unittest.main()
