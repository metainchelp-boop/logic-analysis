"""Synthetic SQLite collection projection; never connects to Docker or a server."""
import importlib.util
import ast
import hashlib
import json
import os
import sqlite3
import tempfile
import types
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from datetime import datetime

SPEC = importlib.util.spec_from_file_location('collection_status', Path(__file__).parents[1]/'tools/naver_preview_collection_status.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class CollectionTest(unittest.TestCase):
    def test_catalog_diagnostics_accept_only_two_reviewed_product_commits(self):
        self.assertEqual(M.CATALOG_LINKS_COMMITS, frozenset({
            '6e4b035901027fef29266de218bfb0594227a3fe',
            '01344b145d0b679a6ee730d7fa4b5990278dd654'}))
        self.assertEqual(M.DAILY_LIMITED_COMMIT, '01344b145d0b679a6ee730d7fa4b5990278dd654')

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

    def test_run_latest_requires_both_new_aggregates_and_unknown_commit_gets_neither(self):
        self.check_run_diagnostics(M.DAILY_LIMITED_COMMIT, {
            'daily_limited':dict(cycle_day='2026-10-01',jobs=0,current_daily_targets=1,
                current_target_rule='DAILY_CADENCE_AND_SAME_ATTRIBUTION_NOT_RETRY_PERMISSION',groups=[]),
            'managed_catalog_links':dict(auto=0,name_different=0,can_confirm=0,rejected={})})
        self.check_run_diagnostics('b'*40)

    def check_run_diagnostics(self, commit, extra=None):
        package = dict(baseline='a'*64, source_commit=commit, source_tar_gz_sha256='c'*64)
        cid, image = 'd'*64, 'sha256:'+'e'*64
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            files = {}
            for name in ('compose.naver-engine.yml', 'preview-engine.override.yml', 'deploy/naver-engine-backup.override.yml'):
                path = root/name; path.parent.mkdir(exist_ok=True); path.write_bytes(b'fixture')
                files[str(path)] = hashlib.sha256(b'fixture').hexdigest()
            receipt = root/('preview-'+package['source_commit']+'.json')
            receipt.write_text(json.dumps(dict(ok=True, stage='prepared', source_commit=package['source_commit'],
                package=package, images={'engine':image}, files=files)))
            receipt.with_name('preview-start-'+package['source_commit']+'.json').write_text(json.dumps(
                dict(ok=True, stage='internal_ready', source_commit=package['source_commit'])))
            values = dict(today='2026-10-01', prospects={'total':0,'stages':{}},
                pairing={'available':False,'statuses':{},'unmatched_prospects':None}, latest_run=None,
                today_checks={'statuses':{},'reasons':{}}, bootstrap=M.bootstrap_empty('no_request'),
                catalog_links={'auto':2,'name_different':1,'can_confirm':1,'rejected':{'legacy_end_unreadable':2}})
            if commit not in M.CATALOG_LINKS_COMMITS:
                values.pop('catalog_links')
            values.update(extra or {})
            failures = [None,'image','mount','rootfs','output','restart','unexpected_daily']
            if 'catalog_links' in values:
                failures.append('catalog_missing')
            if extra:
                failures += ['daily_limited_missing','managed_catalog_links_missing']
            for failure in failures:
                calls, inspections = [], []
                host, release = Mock(), Mock()
                host.baseline.return_value = package['baseline']
                release.prepared_paths.return_value = root, receipt
                release.sha.side_effect = lambda body: hashlib.sha256(body).hexdigest()
                release.unique.side_effect = dict
                release.compose.return_value = ['docker','compose','--project-name','naver-engine']
                def command(args, **kwargs):
                    calls.append(args)
                    if args[0] == '/usr/bin/systemctl':
                        return b'ActiveState=active\nSubState=running\nResult=success\nNRestarts=0\n'
                    if args[:3] == ['docker','compose','version']:
                        return b'2.39.4\n'
                    if args[1:3] == ['image','inspect']:
                        return json.dumps(dict(id=image,user='10001:10001',source='wrong' if failure=='image' else package['source_commit'])).encode()
                    if args[1] == 'compose':
                        return cid.encode()
                    if args[1] == 'inspect':
                        inspections.append(1)
                        return json.dumps(dict(id=cid,image=image,running=True,user='10001:10001',project='naver-engine',
                            service='naver-engine',started='2026-10-01T13:00:00+09:00',oom_killed=False,restarts=int(failure=='restart' and len(inspections)>1),
                            readonly=failure!='rootfs',data=[dict(Type='bind',Destination='/var/lib/naver-engine',
                            Source='/legacy' if failure=='mount' else '/var/lib/metainc/naver-engine')])).encode()
                    if args[1] == 'exec':
                        ast.parse(kwargs['data'])
                        self.assertEqual(kwargs['data'].decode().count('if True:'),
                            int(commit in M.CATALOG_LINKS_COMMITS)+int(commit == M.DAILY_LIMITED_COMMIT))
                        self.assertEqual(args, ['docker','exec','-i','--user','10001:10001',cid,'python','-I','-B','-'])
                        if failure == 'catalog_missing':
                            return json.dumps({key:value for key,value in values.items() if key != 'catalog_links'}).encode()
                        if failure in ('daily_limited_missing','managed_catalog_links_missing'):
                            return json.dumps({key:value for key,value in values.items() if key != failure[:-8]}).encode()
                        if failure == 'unexpected_daily':
                            return json.dumps(dict(values,daily_limited={'PRIVATE':'PRIVATE'})).encode()
                        return json.dumps(dict(values, secret='SECRET') if failure=='output' else values).encode()
                    self.fail('unexpected command')
                release.command.side_effect = command
                with self.subTest(failure=failure), patch.object(M.os, 'geteuid', return_value=0):
                    if failure:
                        with self.assertRaises(ValueError):
                            M.run(package, host, release)
                    else:
                        result = M.run(package, host, release)
                        self.assertEqual(result['collection'], values)
                        self.assertEqual(result['mutations'], 0)
                        self.assertEqual(result['lifecycle']['engine']['active'], 'active')
                        self.assertEqual(result['compose_version'], '2.39.4')
                        self.assertEqual(result['engine_state'], {'started_at':'2026-10-01T13:00:00+09:00', 'oom_killed':False})
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


if __name__ == '__main__':
    unittest.main()
