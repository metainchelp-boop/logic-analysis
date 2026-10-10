"""Fixed V18 report diagnosis: synthetic SQLite and mocked host only."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared

TOOLS = Path(__file__).parents[1]/'tools'
SPEC = importlib.util.spec_from_file_location('recovery', TOOLS/'naver_preview_report_recovery.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
NOW = M.datetime(2026, 10, 10, 18, tzinfo=M.KST)
AT = '2026-10-06T12:00:00+09:00'
MATCHING = 'f'*64


def package():
    return dict(baseline=M.BASELINE,source_commit=M.SOURCE,source_tar_gz_sha256=M.ARCHIVE,
                period='2026-09',scope='current-managed-linked')


def fixture():
    connection = sqlite3.connect(':memory:', isolation_level=None)
    connection.executescript('''
        CREATE TABLE naver_auto_meta(key TEXT PRIMARY KEY,value TEXT);
        INSERT INTO naver_auto_meta VALUES('schema_version','11');
        CREATE TABLE naver_auto_daily_performance(customer_id INTEGER,day TEXT,possibility_id INTEGER,
            matching_fingerprint TEXT,basic_complete INTEGER,conversion_complete INTEGER,checked_at TEXT,
            source_at TEXT,source_generation TEXT,PRIMARY KEY(customer_id,day));
        CREATE TABLE naver_auto_performance_job(job_key TEXT,customer_id INTEGER,possibility_id INTEGER,kind TEXT,
            cycle_day TEXT,period_start TEXT,period_end TEXT,status TEXT,checked_at TEXT,last_success_at TEXT,
            next_try_at TEXT,generation TEXT,attempts INTEGER,error_code TEXT);
        CREATE TABLE naver_auto_management_event(event_id INTEGER PRIMARY KEY,customer_id INTEGER,
            possibility_id INTEGER,at TEXT,action TEXT);
        CREATE TABLE naver_auto_report_dirty(possibility_id INTEGER,period_key TEXT,pending INTEGER,updated_at TEXT);
        CREATE TABLE naver_auto_report_validation(possibility_id INTEGER,period_key TEXT,
            expected_customers_json TEXT,payload_json TEXT);
        CREATE TABLE naver_auto_report_snapshot(report_id INTEGER PRIMARY KEY,possibility_id INTEGER,
            period_key TEXT,generated_at TEXT,payload_json TEXT);
    ''')
    daily = []
    for offset in range(30):
        value = str(M.date(2026,9,1)+M.timedelta(days=offset))
        if offset != 26:
            daily.append((2488728,value,74789 if offset<27 else None,MATCHING,1,1,AT,AT,AT))
        daily.append((1073478,value,82569 if offset != 9 else 99999,MATCHING,1,0,AT,AT,AT))
    connection.executemany('INSERT INTO naver_auto_daily_performance VALUES(?,?,?,?,?,?,?,?,?)',daily)
    connection.executemany('INSERT INTO naver_auto_management_event VALUES(?,?,?,?,?)',[
        (1,2488728,123,'2026-09-01T12:00:00+09:00','stage_sync'),
        (2,2488728,None,'2026-09-26T12:00:00+09:00','stage_sync'),
        (3,2488728,74789,'2026-09-27T12:00:00+09:00','stage_sync')])
    connection.executemany('INSERT INTO naver_auto_performance_job VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',[
        ('a',2488728,74789,'report_monthly','2026-10-03','2026-09-01','2026-09-30','ok',AT,AT,AT,AT,1,None),
        ('b',2488728,74789,'report_weekly','2026-10-05','2026-09-28','2026-10-04','source_wait',AT,None,
         '2026-10-11T12:00:00+09:00',AT,2,'SENSITIVE_EXCEPTION'),
        ('c',2488728,999,'report_monthly','2026-10-03','2026-09-01','2026-09-30','retry',AT,None,AT,AT,4,'NETWORK')])
    key = M.KEYS[0]
    connection.execute('INSERT INTO naver_auto_report_dirty VALUES(?,?,?,?)',(74789,key,0,AT))
    validation = {'status':'pending','pending_account_days':4,'last_attempt_at':AT,'last_checked_at':None,
                  'secret_name':'PRIVATE_EMPLOYEE','_required_after':{'2488728':AT}}
    connection.execute('INSERT INTO naver_auto_report_validation VALUES(?,?,?,?)',
                       (74789,key,'[2488728]',json.dumps(validation)))
    payload = {'coverage':{'accounts':1,'expected_account_days':30,'basic_complete_account_days':26,
                          'conversion_complete_account_days':26},'validation':validation,
               'name':'PRIVATE_COMPANY','spend':987654321,'feedback':'PRIVATE_TEXT'}
    connection.execute('INSERT INTO naver_auto_report_snapshot VALUES(?,?,?,?,?)',(1,74789,key,AT,json.dumps(payload)))
    daily_policy = SimpleNamespace(cadence='daily',attributable=True)
    decisions = {cid:dict(source_current=True,matched=True,decision=daily_policy,possibility_id=pid)
        for cid,pid in ((2488728,74789),(1073478,82569),(888,1001))}
    decisions[999] = dict(source_current=True,matched=False,
        decision=SimpleNamespace(cadence='weekly',attributable=False),possibility_id=None)
    return connection, decisions


class ProjectionTest(unittest.TestCase):
    def setUp(self):
        self.connection, self.decisions = fixture()
        self.addCleanup(self.connection.close)

    def collect(self):
        return M.collect(SimpleNamespace(_conn=self.connection),self.decisions,NOW,MATCHING,time.monotonic()+20)

    def test_population_raw_null_other_missing_and_attribution_boundary_are_separate(self):
        value = self.collect()
        M.validate_result(value)
        self.assertEqual(value['population']['accounts'],3)
        self.assertEqual(value['population']['companies'],3)
        gomso, tochon = value['samples']
        account = gomso['accounts'][0]
        self.assertEqual(account['attribution_start'],'2026-09-28')
        self.assertEqual(account['dates']['null_pid'],['2026-09-28','2026-09-29','2026-09-30'])
        self.assertEqual(account['dates']['missing'],['2026-09-27'])
        self.assertEqual(len(account['dates']['before_attribution']),27)
        self.assertEqual(tochon['accounts'][0]['dates']['other_pid'],['2026-09-10'])
        self.assertEqual(value['coverage'][26]['missing_rows'],2)
        self.assertEqual(value['coverage'][27]['null_pid_rows'],1)

    def test_job_allowlists_and_snapshot_vs_current_raw_are_not_completion_claim(self):
        self.connection.execute("UPDATE naver_auto_daily_performance SET possibility_id=74789 WHERE customer_id=2488728 AND day='2026-09-28'")
        value = self.collect()
        report = value['samples'][0]['reports'][0]
        self.assertFalse(report['dirty']['pending'])
        self.assertTrue(report['raw_same_scope_comparable'])
        self.assertEqual(report['snapshot']['coverage']['basic_complete_account_days'],26)
        self.assertEqual(report['raw_basic_current_pid'],27)
        self.assertEqual(report['validation']['pending_account_days'],4)
        jobs = value['samples'][0]['accounts'][0]['latest_report_jobs']
        self.assertEqual(len(jobs),2)
        self.assertEqual(jobs[1]['error_code'],'UNRECOGNIZED')
        self.assertEqual(jobs[1]['next_try_at'],'2026-10-11T12:00:00+09:00')
        self.assertNotIn('PRIVATE',json.dumps(value))
        self.assertNotIn('987654321',json.dumps(value))
        self.assertNotIn('SENSITIVE_EXCEPTION',json.dumps(value))
        self.assertTrue(value['coverage_is_stored_flags_not_completion_proof'])
        self.assertLess(len(json.dumps(value).encode()),M.MAX_OUTPUT)

    def test_historical_scope_or_matching_change_disables_direct_comparison(self):
        for change in ("UPDATE naver_auto_report_validation SET expected_customers_json='[2488728,123]'",
                       "UPDATE naver_auto_daily_performance SET matching_fingerprint='different'"):
            with self.subTest(change=change):
                self.connection.execute('BEGIN')
                self.connection.execute(change)
                report = self.collect()['samples'][0]['reports'][0]
                self.assertFalse(report['raw_same_scope_comparable'])
                self.assertIsNone(report['raw_basic_current_pid'])
                self.connection.execute('ROLLBACK')

    def test_stale_source_wrong_schema_invalid_times_and_row_bounds_fail_closed(self):
        self.decisions[2488728]['source_current'] = False
        with self.assertRaisesRegex(ValueError,'RECOVERY_ELIGIBILITY_STALE'):
            self.collect()
        self.decisions[2488728]['source_current'] = True
        self.connection.execute("UPDATE naver_auto_meta SET value='10'")
        with self.assertRaisesRegex(ValueError,'RECOVERY_SCHEMA'):
            self.collect()
        self.connection.execute("UPDATE naver_auto_meta SET value='11'")
        self.connection.execute("UPDATE naver_auto_daily_performance SET source_at='PRIVATE_DATE'")
        with self.assertRaisesRegex(ValueError,'RECOVERY_TIME'):
            self.collect()
        with self.assertRaisesRegex(ValueError,'RECOVERY_ROW_LIMIT'):
            M.rows(self.connection,'SELECT * FROM naver_auto_daily_performance',(),1,time.monotonic()+20)
        with self.assertRaisesRegex(ValueError,'RECOVERY_DEADLINE'):
            M.collect(SimpleNamespace(_conn=self.connection),self.decisions,NOW,MATCHING,0)
        with patch.object(M,'MAX_TARGETS',1):
            with self.assertRaisesRegex(ValueError,'RECOVERY_TARGET_LIMIT'):
                self.collect()

    def test_closed_output_validator_rejects_extra_fields_wrong_dates_and_private_text(self):
        value = self.collect()
        for mutate in (lambda out:out['population'].update(employee_name='PRIVATE'),
                       lambda out:out['coverage'][0].update(day='2026-10-01'),
                       lambda out:out['samples'][0]['accounts'][0]['dates'].update(private=[]),
                       lambda out:out['report_jobs'][0]['errors'].update(PRIVATE=1),
                       lambda out:out['samples'][0]['reports'][0]['validation'].update(status='PRIVATE')):
            changed = copy.deepcopy(value)
            mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                M.validate_result(changed)

    def test_sql_projection_never_selects_money_checkpoint_or_report_body(self):
        statements = []
        self.connection.set_trace_callback(statements.append)
        self.collect()
        queries = '\n'.join(statements)
        self.assertNotIn('SELECT *',queries)
        self.assertNotIn('progress_json',queries)
        self.assertNotIn('bizmoney',queries)
        self.assertNotIn('spend',queries)
        self.assertNotIn('SELECT payload_json',queries)
        self.assertIn("json_extract(r.payload_json,'$.coverage",queries)

    def test_evidence_rejects_bool_integer_aliases_field_enum_time_and_count_forgeries(self):
        value = self.collect()
        result = dict(ok=True,mode='report-recovery-diagnostics',source_commit=M.SOURCE,
            reader_mode='sqlite-mode-ro-query-only-authorizer',mutations=0,existing_app_baseline_unchanged=True,
            collection_completion_verified=False,diagnostics=value)
        for field,wrong in (('ok',1),('mutations',False),('existing_app_baseline_unchanged',1),
                            ('collection_completion_verified',0)):
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'RECOVERY_RESULT_PIN'):
                M.validate_operation_result(dict(result,**{field:wrong}))
        for mutate in (lambda out:out['report_jobs'][0]['checked_at'].update(first='complete'),
                       lambda out:out['samples'][0]['reports'][0].update(period_key='2026-09-01'),
                       lambda out:out['coverage'][0].update(basic_current_pid=999),
                       lambda out:out.update(mutations=False),
                       lambda out:out['samples'][0]['reports'][0]['validation'].update(status='2026-09-01')):
            changed = copy.deepcopy(value);mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                M.validate_result(changed)


class ReaderTest(unittest.TestCase):
    def test_mode_ro_query_only_authorizer_refuses_writes_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = (Path(folder)/'synthetic.db').resolve()
            with sqlite3.connect(path) as writer:
                writer.execute('CREATE TABLE probe(value INTEGER)')
                writer.execute('CREATE TABLE naver_auto_link_memory(value INTEGER)')
                writer.execute('INSERT INTO probe VALUES(1)')
            writer.close()
            before = path.read_bytes()
            reader = M.connect_reader(path)
            self.assertEqual(reader.execute('PRAGMA query_only').fetchone(),(1,))
            self.assertEqual(reader.execute('PRAGMA table_info(naver_auto_link_memory)').fetchone()[1],'value')
            with self.assertRaises(sqlite3.DatabaseError):
                reader.execute('PRAGMA table_info(probe)')
            reader.execute('BEGIN')
            for statement in ('DELETE FROM probe','CREATE TABLE bad(x)',"ATTACH ':memory:' AS bad",
                              'PRAGMA query_only=OFF','PRAGMA wal_checkpoint','SELECT load_extension(\'bad\')'):
                with self.subTest(statement=statement),self.assertRaises(sqlite3.DatabaseError):
                    reader.execute(statement)
            self.assertEqual(reader.total_changes,0)
            reader.execute('ROLLBACK')
            reader.close()
            self.assertEqual(path.read_bytes(),before)

    def test_read_snapshot_is_consistent_while_synthetic_writer_advances(self):
        with tempfile.TemporaryDirectory() as folder:
            path = (Path(folder)/'synthetic.db').resolve()
            writer = sqlite3.connect(path,isolation_level=None)
            self.addCleanup(writer.close)
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('CREATE TABLE probe(value INTEGER)')
            writer.execute('INSERT INTO probe VALUES(1)')
            reader = M.connect_reader(path)
            self.addCleanup(reader.close)
            reader.execute('BEGIN')
            self.assertEqual(reader.execute('SELECT value FROM probe').fetchone(),(1,))
            writer.execute('UPDATE probe SET value=2')
            self.assertEqual(reader.execute('SELECT value FROM probe').fetchone(),(1,))
            reader.execute('ROLLBACK')
            self.assertEqual(reader.execute('SELECT value FROM probe').fetchone(),(2,))

    def test_reader_script_checks_store_pin_before_database_open_and_has_no_writer(self):
        program = M.script()
        ast.parse(program)
        self.assertLess(program.index(b'RECOVERY_STORE_PIN'),program.index(b'connection=connect_reader'))
        self.assertIn(M.STORE.encode(),program)
        self.assertIn(b'writer=False',program)
        self.assertIn(b"connection.execute('BEGIN')",program)
        self.assertIn(b"connection.execute('ROLLBACK')",program)
        self.assertIn(b'connection.total_changes!=0',program)
        self.assertNotIn(b'open_writer',program)


class ControllerTest(unittest.TestCase):
    def scenario(self, failure=None):
        connection, decisions = fixture()
        values = M.collect(SimpleNamespace(_conn=connection),decisions,NOW,MATCHING,time.monotonic()+20)
        connection.close()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve()
            files = {}
            for name in ('compose.naver-engine.yml','preview-engine.override.yml','deploy/naver-engine-backup.override.yml'):
                file = path/name
                file.parent.mkdir(exist_ok=True)
                file.write_bytes(b'approved')
                files[str(file)] = hashlib.sha256(file.read_bytes()).hexdigest()
            image, identity = 'sha256:'+'e'*64, 'd'*64
            receipt = path/('preview-'+M.SOURCE+'.json')
            receipt.write_text(json.dumps(dict(ok=True,stage='prepared',source_commit=M.SOURCE,
                package={key:value for key,value in package().items() if key not in ('scope','period')},
                images={'engine':image},files=files)))
            receipt.with_name('preview-start-'+M.SOURCE+'.json').write_text(json.dumps(
                dict(ok=failure!='receipt',stage='internal_ready',source_commit=M.SOURCE)))
            before = dict(id=identity,image=image,running=True,user='10001:10001',project='naver-engine',service='naver-engine',
                started='fixed',restarts=0,readonly=True,
                data=[dict(Type='bind',Destination='/var/lib/naver-engine',Source='/var/lib/metainc/naver-engine')])
            if failure=='mount':
                before['data'][0]['Source'] = '/legacy'
            release, host = Mock(), Mock()
            release.prepared_paths.return_value = path,receipt
            release.sha.side_effect = lambda raw:hashlib.sha256(raw).hexdigest()
            release.unique.side_effect = dict
            release.compose.return_value = ['docker','compose']
            host.baseline.return_value = M.BASELINE
            inspections = 0
            def command(args,**kwargs):
                nonlocal inspections
                if args[1:3]==['image','inspect']:
                    return json.dumps(dict(id=image,user='10001:10001',source=M.SOURCE if failure!='image' else 'x'*40)).encode()
                if args[1]=='compose':
                    return identity.encode()
                if args[1]=='inspect':
                    inspections += 1
                    return json.dumps(dict(before,restarts=1) if failure=='restart' and inspections>1 else before).encode()
                if args[1]=='exec':
                    self.assertEqual(args,['docker','exec','-i','--user','10001:10001',identity,'python','-I','-B','-'])
                    self.assertEqual(kwargs['timeout'],30)
                    if failure=='command':
                        raise RuntimeError('PRIVATE')
                    if failure=='output':
                        return b'{"PRIVATE":1}'
                    if failure=='size':
                        return b'x'*(M.MAX_OUTPUT+1)
                    if failure=='reader':
                        return b'{"failure":"RECOVERY_SCHEMA"}'
                    return json.dumps(values).encode()
                raise AssertionError('unexpected command')
            release.command.side_effect = command
            with patch.object(M.os,'geteuid',return_value=0):
                try:
                    result = M.run(package(),host,release)
                except ValueError as error:
                    result = str(error)
            return result,release,host,inspections

    def test_exact_package_failures_refuse_before_host_or_database(self):
        for change in ({'period':'2026-10'},{'source_commit':'a'*40},{'source_tar_gz_sha256':'a'*64},
                       {'baseline':'a'*64},{'scope':'all'},{'sql':'SELECT 1'},{'path':'/other'}):
            host,release = Mock(),Mock()
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'RECOVERY_PACKAGE_(FIELDS|PIN)'):
                M.run(dict(package(),**change),host,release)
            self.assertFalse(host.mock_calls or release.mock_calls)

    def test_success_has_exact_closed_result_and_no_collection_completion_claim(self):
        result,release,host,inspections = self.scenario()
        M.validate_operation_result(result)
        self.assertTrue(result['ok'])
        self.assertFalse(result['collection_completion_verified'])
        self.assertEqual(inspections,2)
        self.assertEqual(host.baseline.call_count,2)

    def test_preflight_reader_postflight_and_output_failures_never_become_success(self):
        for failure,code in (('receipt','SOURCE_NOT_READY'),('mount','PREVIEW_DATA_MOUNT'),
                ('image','PREPARED_IMAGE_CHANGED'),('restart','POST_BASELINE'),('command','RECOVERY_READER_FAILED'),
                ('output','RECOVERY_OUTPUT_FIELDS'),('size','RECOVERY_OUTPUT_LIMIT'),('reader','RECOVERY_SCHEMA')):
            with self.subTest(failure=failure):
                result,release,host,inspections = self.scenario(failure)
                self.assertEqual(result,code)
                self.assertNotIn('PRIVATE',result)
                if failure in ('command','output','size','reader','restart'):
                    self.assertEqual(inspections,2)


class TransportTest(unittest.TestCase):
    def test_actual_new_bundle_roundtrip_and_existing_v18_passive_is_unchanged(self):
        encode,decode,_ = shared.ContractTest().workflow_transport()
        bundle = dict(operation='preview-report-recovery',function='run',package=package(),
            source=(TOOLS/'naver_preview_report_recovery.py').read_text(),
            release_source=(TOOLS/'naver_preview_release.py').read_text(),
            host_source=(TOOLS/'naver_erp_tunnel_service_install.py').read_text())
        wire = encode(bundle)
        self.assertTrue(wire.startswith('code-gzip-v1:'))
        self.assertEqual(decode(wire),bundle)
        self.assertLessEqual(len(wire),65536)
        self.assertLessEqual(len(json.dumps(bundle).encode()),196608)
        with self.assertRaisesRegex(ValueError,'CODE_OPS_OPERATION'):
            decode(encode(dict(bundle,function='apply')))
        import test_naver_preview_code_upgrade_v18 as v18
        passive = v18.V18TransportTest().actual_bundles()['passive']
        self.assertEqual(decode(encode(passive)),passive)
        self.assertLessEqual(len(encode(passive)),65536)

    def test_new_workflow_operation_is_pinned_and_old_collection_module_is_unmodified(self):
        workflow = (TOOLS.parents[1]/'.github/workflows/debug-rank.yml').read_text()
        self.assertIn("github.ref == 'refs/heads/codex/ad-deploy-prep-20261001'",workflow)
        self.assertIn("assert all(v=='off' for v in inputs.values())",workflow)
        self.assertIn("'preview-report-recovery':('naver_preview_report_recovery','run')",workflow)
        self.assertIn('naver_preview_report_recovery.validate_package(package)',workflow)
        status = shared.load('naver_preview_collection_status')
        host,release = Mock(),Mock()
        with self.assertRaisesRegex(ValueError,'PASSIVE_RUNTIME_ONLY'):
            status.run({key:value for key,value in package().items() if key not in ('period','scope')},host,release)
        self.assertFalse(host.mock_calls or release.mock_calls)


if __name__ == '__main__':
    unittest.main()
