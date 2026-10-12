"""Closed dc168 setup diagnostic regressions; databases and host calls are synthetic."""
import ast
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch
TOOLS=Path(__file__).parents[1]/'tools'
SPEC=importlib.util.spec_from_file_location('setup_stale_diagnostics',TOOLS/'naver_setup_stale_diagnostics.py')
D=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(D)
NOW=datetime(2026,10,12,23,tzinfo=D.KST)
TEST_TARGETS=tuple((label,pid,adno+10**9) for label,pid,adno in D.TARGETS)

def result_fixture():
    target={'policy':{'present':True,'active':True,'cadence':'daily','reason':'MANAGED_STAGE','expected_pair_matches':True,'source_current':True},
        'scope':{'any_job_present':False,'current_row_present':False,'kind':None,'status':None,'history_rows_checked':0},
        'manual':{'present':False,'requested_today':False,'expected_pair_matches':False,'current_valid_request':False,'kind':None},
        'binding_checks':None,'failed_checks':[],
        'observation':dict(D.expected_projection('NO_OBSERVATION'),branch='NO_OBSERVATION',projection_matches_actual=True)}
    return {'schema_version':21,'projection_model':'dc168-setup-stale-v1','target_identifier_namespace':D.TARGET_NAMESPACE,
        'targets':{label:deepcopy(target) for label,_,_ in D.TARGETS},'mutations':0,
        'limits':{x:True for x in ('stored_snapshot_only','source_guards_unchanged','management_not_synchronized','collection_completion_not_proven','scheduler_budget_unobserved','ads_unchanged')}}

def portable_fixture():
    """Only fixed identifiers and schema columns; no external product dependency."""
    c=sqlite3.connect(':memory:',isolation_level=None)
    c.executescript('''CREATE TABLE naver_auto_meta(key TEXT PRIMARY KEY,value TEXT);
        INSERT INTO naver_auto_meta VALUES('schema_version','21');
        CREATE TABLE naver_auto_account(customer_id INTEGER PRIMARY KEY,ad_account_no INTEGER,present INTEGER);
        CREATE TABLE naver_auto_manual_read(customer_id INTEGER PRIMARY KEY,possibility_id INTEGER,requested_at TEXT,
            actor INTEGER,request_kind TEXT,period_start TEXT,period_end TEXT);
        CREATE TABLE naver_auto_inspection_job(job_key TEXT PRIMARY KEY,customer_id INTEGER,possibility_id INTEGER,kind TEXT,
            cycle_day TEXT,period_start TEXT,period_end TEXT,snapshot_at TEXT,catalog_at TEXT,stage_revision TEXT,
            matching_fingerprint TEXT,generation TEXT,requested_at TEXT,actor INTEGER,status TEXT,checked_at TEXT,
            next_try_at TEXT,attempts INTEGER,error_code TEXT,progress_json TEXT,progress_hash TEXT);
        CREATE TABLE naver_auto_setting_observation(history_id INTEGER,customer_id INTEGER,possibility_id INTEGER,
            stage_revision TEXT,body_json TEXT);''')
    states={};policies={}
    for (label,pid,cid),(_,_,adno) in zip(TEST_TARGETS,D.TARGETS):
        c.execute('INSERT INTO naver_auto_account VALUES(?,?,1)',(cid,adno))
        states[cid]={'possibility_id':pid,'stage_revision':'r'}
        policies[cid]={'possibility_id':pid,'stage_revision':'r','matched':True,'source_current':True,
            'decision':NS(cadence='daily',reason='MANAGED_STAGE')}
    catalog={'generated_at':NOW.isoformat()}
    store=NS(_conn=c,management_states=lambda:states,inventory_snapshot=lambda now:NOW,
        decision_fingerprint=lambda:'f'*64,_inspection_manual_job=Mock(return_value=None),
        _inspection_account_valid=Mock(return_value=False),inspection_account_valid=Mock(return_value=False),
        _inspection_catalog_proof=Mock(return_value=None),_inspection_read_proof=Mock(return_value=None),
        _inspection_context=Mock(return_value=None),setup_observation=Mock(return_value=None))
    def period(cadence,now):
        day=now.date() if cadence=='daily' else now.date()-timedelta(days=(now.weekday()+1)%7)
        return NS(cycle_day=day)
    def job(row):
        out={k:row[k] for k in ('job_key','customer_id','kind','cycle_day','period_start','period_end','catalog_at','stage_revision','matching_fingerprint','generation')}
        out['snapshot_at']=datetime.fromisoformat(row['snapshot_at'])
        if row['kind']=='manual':out.update(requested_at=row['requested_at'],actor=row['actor'])
        return out
    modules=dict(S=NS(_kst_text=lambda at,label:at.isoformat(timespec='microseconds')),
        MS=NS(snapshot=lambda store,now,stage_states:policies),I=NS(catalog_status=lambda store,now:(catalog,'accepted')),
        P=NS(period_for=period),IS=NS(_job=job,_binding=lambda row,job,pid:row['possibility_id']==pid,
            _ERROR_CODES=frozenset({'REQUEST_CALL_CAP'})),
        IC=NS(checkpoint_key=lambda key:'fixed-proof',_scope_matches=lambda row,job,pid:row['possibility_id']==pid,
            _sealed=lambda proof,fields:False,_CHECKPOINT_FIELDS=set(),_dump=lambda x:json.dumps(x,sort_keys=True),_binding=lambda row,codes:{}),
        O=NS(allows_raising=lambda state:True),Y=NS(org_freshness=lambda store,now:'current'))
    return store,modules,policies,states,catalog

def insert_portable_job(store,**changes):
    label,pid,cid=TEST_TARGETS[1]
    row=dict(job_key='inspection:synthetic',customer_id=cid,possibility_id=pid,kind='daily',cycle_day=str(NOW.date()),
        period_start='2026-10-11',period_end='2026-10-11',snapshot_at=NOW.isoformat(timespec='microseconds'),
        catalog_at=NOW.isoformat(),stage_revision='r',matching_fingerprint='f'*64,generation=NOW.isoformat(),
        requested_at=None,actor=None,status='partial',checked_at=NOW.isoformat(),next_try_at=NOW.isoformat(),attempts=1,
        error_code='REQUEST_CALL_CAP',progress_json=None,progress_hash=None)
    row.update(changes)
    store._conn.execute('INSERT INTO naver_auto_inspection_job('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
    return row

def pinned_product_fixture(product_root):
    """Optional local equivalence audit against exact pinned product; only :memory: writes."""
    import sys
    root=Path(product_root).resolve()
    for relative,digest in D.CODE_PINS.items():
        if hashlib.sha256((root/relative).read_bytes()).hexdigest()!=digest:raise AssertionError('SYNTHETIC_PRODUCT_PIN')
    sys.path[:0]=[str(root),str(root/'backend')]
    from naver_engine import store as S,management_store as MS,inventory as I,management as P,inspection_store as IS,inspection_reads as IR,inspection_catalog as IC,sync as Y,product_evidence as PE,erp_read as E
    from app.naver_auto import org_snapshot as O,matching as M
    from naver_engine.tests import test_alerts as TA,test_account_catalog as TC,test_morning as TM
    modules=dict(S=S,MS=MS,I=I,P=P,IS=IS,IR=IR,IC=IC,O=O,Y=Y,PE=PE)
    scenarios=('no_job','partial','retry','timestamp_refresh','content_change','missing_catalog_proof','tampered_context',
        'complete','confirmed_inflight','snapshot_refresh','fingerprint_change','manual_pending','manual_consumed_pending',
        'manual_period','manual_previous_day','policy_blocked','inactive_no_job_invalid_manual','management_revision','progress_corrupt',
        'future_checked_at','identity_decoy','duplicate_identity','missing_identity')
    summaries=[]
    for scenario in scenarios:
        observed_at=NOW
        with patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')):
            st=S.Store(sqlite3.connect(':memory:',isolation_level=None),':memory:',None,True,lambda:observed_at)
            try:
                st._migrate();st.record_org(TA.org_body(NOW,owners=[TA.owner(pid,100) for _,pid,cid in TEST_TARGETS]),NOW)
                kids=TM.kids(*(cid for _,_,cid in TEST_TARGETS),*(adno for _,_,adno in D.TARGETS))
                for (label,pid,cid),(_,_,adno) in zip(TEST_TARGETS,D.TARGETS):
                    kids.accounts[cid]['adAccountNo']=adno;kids.accounts[adno]['adAccountNo']=adno+2*10**9
                st.record_accounts(kids,NOW)
                def catalog(at,changed=False):
                    st.record_account_catalog(dict(generated_at=at.isoformat(),total=2,complete=True,items=[TC.company(pid,'진행중',company_name=f'계정{cid}'+(' changed' if changed else '')) for _,pid,cid in TEST_TARGETS]),
                        [E.NaverIdRow(pid,M.VENDOR_NAVER,ad_account_no_raw=str(adno)) for _,pid,adno in D.TARGETS],at)
                catalog(NOW)
                jobs=st.inspection_work(NOW);job=next(j for j in jobs if j['customer_id']==TEST_TARGETS[1][2])
                cid=job['customer_id'];pid=TEST_TARGETS[1][1]
                if scenario not in ('no_job','manual_period','manual_previous_day','inactive_no_job_invalid_manual'):
                    st.begin_inspection_check(job,NOW)
                    progress=IR._initial([{'customerId':cid,'nccCampaignId':'cmp-private','campaignTp':'WEB_SITE','name':'PRIVATE_NAME','dailyBudget':30000,'useDailyBudget':True,'usePeriod':False}],job,NOW)
                    if scenario in ('complete','confirmed_inflight','progress_corrupt'):progress=IR._initial([],job,NOW);progress['confirmed']=True
                    st.record_inspection_progress(job,NOW,progress)
                    if scenario!='confirmed_inflight':st.record_inspection_check(job,NOW,{'status':'ok'} if scenario in ('complete','progress_corrupt') else {'status':'retry' if scenario=='retry' else 'partial','error_code':'NETWORK' if scenario=='retry' else 'REQUEST_CALL_CAP','progressed':scenario!='retry'})
                if scenario in ('timestamp_refresh','content_change'):
                    observed_at=NOW+timedelta(minutes=1);catalog(observed_at,scenario=='content_change')
                if scenario=='missing_catalog_proof':st._conn.execute("UPDATE naver_auto_meta SET value='null' WHERE key=?",(IC.CATALOG_KEY,))
                if scenario=='tampered_context':st._conn.execute("UPDATE naver_auto_meta SET value='null' WHERE key=?",(IC.checkpoint_key(job['job_key']),))
                if scenario=='snapshot_refresh':
                    observed_at=NOW+timedelta(minutes=1);st.record_accounts(kids,observed_at)
                if scenario=='fingerprint_change':
                    st._conn.execute("INSERT INTO naver_auto_link_decision(possibility_id,customer_id,decision,decided_by,decided_at) VALUES(?,?,'confirmed',0,?)",(pid,cid,NOW.isoformat()))
                if scenario in ('manual_pending','manual_consumed_pending','manual_period','manual_previous_day','inactive_no_job_invalid_manual'):
                    requested=NOW-timedelta(days=1) if scenario=='manual_previous_day' else NOW+timedelta(seconds=1)
                    observed_at=NOW+timedelta(seconds=2)
                    kind='manual_period' if scenario in ('manual_period','inactive_no_job_invalid_manual') else 'manual'
                    st._conn.execute('INSERT INTO naver_auto_manual_read(customer_id,possibility_id,requested_at,actor,request_kind,period_start,period_end,consumed_at) VALUES(?,?,?,?,?,?,?,?)',
                        (cid,pid,S._kst_text(requested,'요청'),0,kind,'2026-10-01' if kind=='manual_period' else None,'2026-10-02' if kind=='manual_period' else None,S._kst_text(observed_at,'소비') if scenario=='manual_consumed_pending' else None))
                if scenario in ('policy_blocked','inactive_no_job_invalid_manual'):
                    observed_at=NOW+timedelta(hours=31)
                if scenario=='management_revision':st._conn.execute("UPDATE naver_auto_management_state SET stage_revision='changed' WHERE customer_id=?",(cid,))
                if scenario=='progress_corrupt':
                    raw='{}';digest=hashlib.sha256(raw.encode()).hexdigest();st._conn.execute('UPDATE naver_auto_inspection_job SET progress_json=?,progress_hash=? WHERE job_key=?',(raw,digest,job['job_key']))
                    # Keep a valid context for this now-corrupt progress body to exercise the later parser check.
                    row=S._rows(st._conn.execute('SELECT * FROM naver_auto_inspection_job WHERE job_key=?',(job['job_key'],)))[0]
                    proof=st._inspection_catalog_proof(NOW)
                    value=IC._seal(dict(version=1,role='complete',binding=IC._binding(row,IS._ERROR_CODES),**{k:proof[k] for k in ('content_digest','content_epoch','stable_content_at')}))
                    st._conn.execute('UPDATE naver_auto_meta SET value=? WHERE key=?',(IC._dump(value),IC.checkpoint_key(job['job_key'])))
                if scenario=='future_checked_at':st._conn.execute('UPDATE naver_auto_inspection_job SET checked_at=? WHERE job_key=?',(S._kst_text(NOW+timedelta(minutes=1),'현재'),job['job_key']))
                if scenario=='duplicate_identity':st._conn.execute('UPDATE naver_auto_account SET ad_account_no=? WHERE customer_id=?',(D.TARGETS[1][2],D.TARGETS[1][2]))
                if scenario=='missing_identity':st._conn.execute('UPDATE naver_auto_account SET present=0 WHERE customer_id=?',(cid,))
                st.writer=False;c=st._conn;before=c.total_changes;c.set_authorizer(None);c.execute('PRAGMA query_only=ON');c.set_authorizer(D.readonly_authorizer);c.execute('BEGIN')
                try:
                    try:result=D.collect(st,observed_at,time.monotonic()+20,modules)
                    except ValueError as error:
                        expected_error={'duplicate_identity':'SOURCE_DIAGNOSTICS_TARGET_AMBIGUOUS','missing_identity':'SOURCE_DIAGNOSTICS_TARGET_NOT_FOUND'}.get(scenario)
                        assert str(error)==expected_error,(scenario,str(error));summaries.append({'scenario':scenario,'closed_refusal':str(error),'mutations':c.total_changes-before});continue
                    D.validate_result(result);b=result['targets']['foodin'];actual=D.actual_projection(st.setup_observation(cid,observed_at))
                    assert {k:b['observation'][k] for k in actual}==actual
                    expected_branch={'no_job':'NO_OBSERVATION','partial':'CURRENT_PARTIAL','retry':'CURRENT_PARTIAL','timestamp_refresh':'CURRENT_ROW_INVALID','content_change':'CURRENT_ROW_INVALID','missing_catalog_proof':'CURRENT_ROW_INVALID','tampered_context':'CURRENT_ROW_INVALID','complete':'CURRENT_COMPLETE','confirmed_inflight':'CURRENT_PARTIAL','snapshot_refresh':'CURRENT_ROW_INVALID','fingerprint_change':'CURRENT_ROW_INVALID','manual_pending':'MANUAL_PENDING','manual_consumed_pending':'MANUAL_PENDING','manual_period':'NO_OBSERVATION','manual_previous_day':'NO_OBSERVATION','policy_blocked':'POLICY_INACTIVE','inactive_no_job_invalid_manual':'NO_OBSERVATION','management_revision':'NO_CURRENT_SCOPE_ROW','progress_corrupt':'CHECKPOINT_INVALID','future_checked_at':'CURRENT_ROW_INVALID','identity_decoy':'CURRENT_PARTIAL'}[scenario]
                    assert b['observation']['branch']==expected_branch,(scenario,b['observation'])
                    if scenario=='timestamp_refresh':assert b['binding_checks']['catalog_stamp_matches'] is False and b['binding_checks']['context_current'] is True
                    if scenario=='snapshot_refresh':assert b['binding_checks']['account_snapshot_matches'] is False
                    if scenario=='confirmed_inflight':assert not b['observation']['complete'] and b['scope']['status']=='reading'
                    payload=json.dumps(result,ensure_ascii=False,separators=(',',':'))
                    assert all(str(cid) not in payload for _,_,cid in TEST_TARGETS) and 'PRIVATE_NAME' not in payload and 'cmp-private' not in payload
                    assert c.total_changes==before
                    summaries.append({'scenario':scenario,'branch':b['observation']['branch'],'projection_matches_actual':True,'mutations':c.total_changes-before,'output_bytes':len(payload.encode())})
                finally:c.execute('ROLLBACK')
            finally:st.close()
    return {'source_commit':D.SOURCE,'code_files_verified':len(D.CODE_PINS),'scenarios':summaries}

class ClosedProjectionTests(unittest.TestCase):
    def test_exact_minimal_result_and_no_raw_identity_time_settings(self):
        result=result_fixture();self.assertEqual(D.validate_result(result),result)
        payload=json.dumps(result)
        for forbidden in ('customer_id','requested_at','checked_at\"','catalog_at','daily_budget','PRIVATE_NAME'):self.assertNotIn(forbidden,payload)
    def test_unknown_or_extra_top_and_nested_fields_fail_closed(self):
        for target in ('root','policy','scope','manual','observation'):
            result=result_fixture();row=result if target=='root' else result['targets']['foodin'][target];row['private']='secret'
            with self.subTest(target=target),self.assertRaises(ValueError):D.validate_result(result)
    def test_wrong_source_namespace_model_or_schema_is_rejected(self):
        for key,value in (('target_identifier_namespace','customer_id'),('projection_model','15f-inspection-continuation-v1'),('schema_version',True),('mutations',False)):
            result=result_fixture();result[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):D.validate_result(result)
    def test_source_stale_cannot_claim_timestamp_or_generation(self):
        result=result_fixture();row=result['targets']['foodin'];row['policy'].update(active=False,cadence='blocked',reason='SOURCE_STALE');row['scope']['any_job_present']=True
        row['observation']=dict(D.expected_projection('POLICY_INACTIVE'),branch='POLICY_INACTIVE',projection_matches_actual=True)
        D.validate_result(result)
        for key in ('generation_present','checked_at_present','complete'):
            changed=deepcopy(result);changed['targets']['foodin']['observation'][key]=True
            with self.subTest(key=key),self.assertRaises(ValueError):D.validate_result(changed)
    def test_valid_manual_pending_is_not_stale_or_complete(self):
        result=result_fixture();row=result['targets']['foodin'];row['manual'].update(present=True,requested_today=True,expected_pair_matches=True,current_valid_request=True,kind='manual')
        row['observation']=dict(D.expected_projection('MANUAL_PENDING'),branch='MANUAL_PENDING',projection_matches_actual=True);D.validate_result(result)
        for key,value in (('stale',True),('complete',True),('checked_at_present',True),('generation_present',False)):
            changed=deepcopy(result);changed['targets']['foodin']['observation'][key]=value
            with self.assertRaises(ValueError):D.validate_result(changed)
    def test_unknown_reason_enum_and_bool_history_count_are_rejected(self):
        for key,value in (('reason','private error'),('cadence','hourly')):
            result=result_fixture();result['targets']['foodin']['policy'][key]=value
            with self.assertRaises(ValueError):D.validate_result(result)
        result=result_fixture();result['targets']['foodin']['scope']['history_rows_checked']=False
        with self.assertRaises(ValueError):D.validate_result(result)
    def test_output_limits_are_exact_all_true(self):
        result=result_fixture();result['limits']['ads_unchanged']=False
        with self.assertRaises(ValueError):D.validate_result(result)
    def test_no_observation_cannot_claim_complete_or_timestamp(self):
        for key in ('complete','generation_present','checked_at_present','present'):
            result=result_fixture();result['targets']['foodin']['observation'][key]=True
            with self.assertRaises(ValueError):D.validate_result(result)
    def test_projection_equivalence_is_mandatory(self):
        result=result_fixture();result['targets']['foodin']['observation']['projection_matches_actual']=False
        with self.assertRaises(ValueError):D.validate_result(result)

class CollectPathTests(unittest.TestCase):
    def setUp(self):
        self.store,self.modules,self.policies,self.states,self.catalog=portable_fixture()
        self.addCleanup(self.store._conn.close)
    def collect(self):
        result=D.collect(self.store,NOW,time.monotonic()+20,self.modules)
        D.validate_result(result)
        return result['targets']['foodin']
    def test_no_job_and_no_manual_returns_no_observation(self):
        self.assertEqual(self.collect()['observation']['branch'],'NO_OBSERVATION')
    def test_present_ad_account_namespace_excludes_same_number_customer_decoy(self):
        self.store._conn.execute('INSERT INTO naver_auto_account VALUES(?,?,1)',(D.TARGETS[1][2],12345))
        self.collect()
        self.assertEqual(self.store.setup_observation.call_args_list[-1].args[0],TEST_TARGETS[1][2])
    def test_duplicate_or_missing_present_ad_account_refuses(self):
        self.store._conn.execute('INSERT INTO naver_auto_account VALUES(?,?,1)',(D.TARGETS[1][2],D.TARGETS[1][2]))
        with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_TARGET_AMBIGUOUS'):self.collect()
        self.store._conn.execute('UPDATE naver_auto_account SET present=0 WHERE ad_account_no=?',(D.TARGETS[1][2],))
        with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_TARGET_NOT_FOUND'):self.collect()
    def test_current_row_invalid_preserves_null_observation_metadata(self):
        insert_portable_job(self.store)
        self.store.setup_observation.side_effect=lambda cid,now:dict(D.expected_projection('CURRENT_ROW_INVALID'),generation=None,checked_at=None) if cid==TEST_TARGETS[1][2] else None
        row=self.collect()
        self.assertEqual(row['observation']['branch'],'CURRENT_ROW_INVALID')
        self.assertFalse(row['binding_checks']['full_account_valid'])
    def test_scope_query_does_not_borrow_other_pid_or_revision(self):
        insert_portable_job(self.store,possibility_id=12345)
        self.store.setup_observation.side_effect=lambda cid,now:dict(D.expected_projection('NO_CURRENT_SCOPE_ROW'),generation=None,checked_at=None) if cid==TEST_TARGETS[1][2] else None
        row=self.collect();self.assertFalse(row['scope']['current_row_present']);self.assertEqual(row['observation']['branch'],'NO_CURRENT_SCOPE_ROW')
    def test_actual_return_mismatch_refuses_instead_of_diagnosing(self):
        insert_portable_job(self.store)
        with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_PROJECTION_MISMATCH'):self.collect()
    def test_progress_and_history_bounds_precede_actual_setup_call(self):
        insert_portable_job(self.store,progress_json='x'*(D.MAX_PROGRESS_BYTES+1))
        with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_ROW_LIMIT'):self.collect()
        self.assertNotIn(TEST_TARGETS[1][2],[call.args[0] for call in self.store.setup_observation.call_args_list])
    def test_schema_and_meta_size_reject_before_store_projection(self):
        self.store._conn.execute("UPDATE naver_auto_meta SET value='20' WHERE key='schema_version'")
        with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_SCHEMA'):self.collect()
        self.store.setup_observation.assert_not_called()

class ReaderBoundsTests(unittest.TestCase):
    def test_package_is_exact_dc168_no_old_15f_or_dynamic_query(self):
        package=dict(baseline=D.BASELINE,source_commit=D.SOURCE,source_tar_gz_sha256=D.ARCHIVE,mode=D.MODE);D.validate_package(package)
        for key,value in (('source_commit',D.PREVIOUS_SOURCE),('mode','current-inspection-diagnostics-ad-account-v1'),('sql','SELECT'),('pid',1)):
            with self.subTest(key=key),self.assertRaises(ValueError):D.validate_package(dict(package,**{key:value}))
    def test_script_pins_before_database_and_does_not_call_writer_scheduler_or_provider(self):
        script=D.script().decode();ast.parse(script);self.assertLess(script.index('for relative,digest in CODE_PINS.items()'),script.index("connection=connect_reader("))
        self.assertIn('os.geteuid()!=10001',script);self.assertIn('socket.socket.connect=socket.socket.connect_ex=no_network',script);self.assertIn("connection.execute('BEGIN')",script)
        self.assertIn('connection.total_changes!=0',script);self.assertIn('time.monotonic()+20',script)
        for forbidden in ('synchronize_management(','.inspection_work(','.tick(','.record_', 'Anthropic','claude','read_text('):self.assertNotIn(forbidden,script)
    def test_authorizer_denies_write_attach_pragma_and_extension(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td).resolve()/'db';c=sqlite3.connect(path);c.execute('CREATE TABLE x(n)');c.commit();c.close();reader=D.connect_reader(path)
            try:
                self.assertEqual(reader.execute('SELECT count(*) FROM x').fetchone(),(0,))
                for sql in ('INSERT INTO x VALUES(1)',"ATTACH ':memory:' AS other",'PRAGMA query_only=OFF','CREATE TABLE y(n)',"SELECT load_extension('private')"):
                    with self.subTest(sql=sql),self.assertRaises(sqlite3.DatabaseError):reader.execute(sql)
            finally:reader.close()
    def test_checkpoint_and_history_sizes_checked_before_body_reads(self):
        c=Mock();c.execute.return_value.description=[('size',)]
        c.execute.return_value.fetchmany.return_value=[(D.MAX_PROGRESS_BYTES+1,)]
        with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_ROW_LIMIT'):D.bounded_bodies(c,1,2,'r',{'job_key':'x'},time.monotonic()+20,[0])
        self.assertTrue(all('progress_json AS BLOB' in call.args[0] for call in c.execute.call_args_list))
    def test_aggregate_history_bound_and_missing_history_are_distinct(self):
        c=sqlite3.connect(':memory:');c.executescript('CREATE TABLE naver_auto_setting_observation(history_id INTEGER,customer_id INTEGER,possibility_id INTEGER,stage_revision TEXT,body_json TEXT);')
        self.addCleanup(c.close);self.assertEqual(D.bounded_bodies(c,1,2,'r',None,time.monotonic()+20,[0]),0)
        c.execute('INSERT INTO naver_auto_setting_observation VALUES(1,1,2,\'r\',\'{}\')')
        with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_ROW_LIMIT'):D.bounded_bodies(c,1,2,'r',None,time.monotonic()+20,[D.MAX_PROGRESS_TOTAL])
    def test_deadline_targets_and_progress_bodies_never_go_to_output(self):
        with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_DEADLINE'):D.check_deadline(0)
        with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_TARGETS'):D.collect(None,NOW,time.monotonic()+20,{},(('private',1,2),))
        self.assertLess(len(D.script()),98304)

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.path=self.root/'release';self.path.mkdir()
        (self.path/'deploy').mkdir();receipts=self.root/'receipts';receipts.mkdir()
        self.prepared=receipts/('preview-'+D.SOURCE+'.json')
        self.started=receipts/('preview-start-'+D.SOURCE+'.json')
        self.package=dict(baseline=D.BASELINE,source_commit=D.SOURCE,source_tar_gz_sha256=D.ARCHIVE,mode=D.MODE)
        files={}
        for relative in ('compose.naver-engine.yml','preview-engine.override.yml','deploy/naver-engine-backup.override.yml'):
            path=self.path/relative;path.write_bytes(b'SYNTHETIC_COMPOSE')
            files[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        self.image='sha256:'+'a'*64;self.identity='b'*64
        self.prepared.write_text(json.dumps(dict(ok=True,stage='prepared',source_commit=D.SOURCE,
            package=dict(self.package,run_id=D.PREPARE_RUN),runtime_environment_preserved=True,config_operation_id='74c912dddf824fae99012849bc4c19a5',files=files,images={'engine':self.image},inventory_enabled=True,execution_enabled=False,runtime_flags_verified=True)))
        self.started.write_text(json.dumps(dict(ok=True,stage='internal_ready',source_commit=D.SOURCE,
            previous_commit=D.PREVIOUS_SOURCE,operation_id=D.APPLY_OPERATION,database_policy="preserve-in-place",database_opened_by_controller=False,source_warmup_performed=False,database_snapshot_verified=False,rollback_requires_matching_database=False,saved_export_companion_preserved=True,database_schema=21,execution_enabled=False,runtime_flags_verified=True)))
        self.before=dict(id=self.identity,image=self.image,running=True,user='10001:10001',project='naver-engine',
            service='naver-engine',started='2026-10-12T10:00:00Z',restarts=0,readonly=True,
            data=[{'Type':'bind','Destination':'/var/lib/naver-engine','Source':'/var/lib/metainc/naver-engine'}])
        self.result=result_fixture()

    def scenario(self,*,reader_failure=False,engine_drift=False,legacy_drift=False,post_exception=False,payload=None):
        commands=[];inspects=[0]
        def command(args,**kwargs):
            commands.append(args)
            if args[:3]==['docker','image','inspect']:
                return json.dumps(dict(id=self.image,user='10001:10001',source=D.SOURCE)).encode()
            if args[-3:]==['ps','--all','--quiet']:return self.identity.encode()
            if args[:2]==['docker','inspect']:
                inspects[0]+=1
                if post_exception and inspects[0]>1:raise RuntimeError('PRIVATE_CONTAINER_RAW')
                result=deepcopy(self.before)
                if engine_drift and inspects[0]>1:result['restarts']=1
                return json.dumps(result).encode()
            if args[:3]==['docker','exec','-i']:
                if reader_failure:raise RuntimeError('PRIVATE_READER_RAW')
                return json.dumps(self.result if payload is None else payload,separators=(',',':')).encode()
            raise AssertionError('UNEXPECTED_COMMAND')
        release=NS(prepared_paths=lambda source:(self.path,self.prepared),trusted_private_file=Mock(),
            unique=lambda values:dict(values),sha=lambda raw:hashlib.sha256(raw).hexdigest(),
            command=command,compose=lambda path,service:['docker','compose','fixed'])
        host=NS(baseline=Mock(side_effect=[D.BASELINE,'0'*64 if legacy_drift else D.BASELINE]))
        with patch.object(D.os,'geteuid',return_value=0),patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')):
            result=D.run(self.package,host,release)
        return result,commands,host,inspects[0]

    def test_success_is_closed_and_uses_only_fixed_source_read_process(self):
        result,commands,host,inspects=self.scenario()
        self.assertTrue(result['ok']);self.assertEqual(result['diagnostics'],self.result)
        self.assertEqual(inspects,2);self.assertEqual(host.baseline.call_count,2)
        self.assertFalse(result['collection_completion_verified']);self.assertEqual(result['mutations'],0)
        self.assertTrue(any(args[:3]==['docker','exec','-i'] for args in commands))
        for forbidden in ('logs','restart','stop','up','inspect-env'):
            self.assertFalse(any(forbidden in args for args in commands))

    def test_primary_and_two_postflight_failures_are_all_preserved(self):
        result,commands,host,inspects=self.scenario(reader_failure=True,engine_drift=True,legacy_drift=True)
        self.assertFalse(result['ok']);self.assertNotIn('diagnostics',result)
        self.assertEqual(result['failure'],dict(primary_code='SOURCE_DIAGNOSTICS_READER_FAILED',
            post_engine_code='POST_ENGINE_CHANGED',post_legacy_baseline_code='POST_LEGACY_BASELINE_CHANGED'))
        self.assertEqual(inspects,2);self.assertEqual(host.baseline.call_count,2)
        self.assertNotIn('PRIVATE',json.dumps(result))

    def test_unknown_raw_reader_failure_and_postflight_exception_are_closed(self):
        result,*_=self.scenario(payload={'failure':'PRIVATE_SECRET_RAW'},post_exception=True)
        self.assertEqual(result['failure']['primary_code'],'SOURCE_DIAGNOSTICS_READ_FAILED')
        self.assertEqual(result['failure']['post_engine_code'],'POST_ENGINE_UNVERIFIED')
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertNotIn('diagnostics',result)

    def test_invalid_output_and_postflight_drift_do_not_return_partial_diagnostics(self):
        result,*_=self.scenario(payload=dict(self.result,raw='PRIVATE_RESPONSE'),legacy_drift=True)
        self.assertEqual(result['failure']['primary_code'],'SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
        self.assertEqual(result['failure']['post_legacy_baseline_code'],'POST_LEGACY_BASELINE_CHANGED')
        self.assertNotIn('diagnostics',result);self.assertNotIn('PRIVATE',json.dumps(result))


    def test_current_prepare_apply_proof_drift_refuses_before_reader(self):
        prepared=json.loads(self.prepared.read_text());started=json.loads(self.started.read_text())
        cases=[('prepare','package',dict(prepared['package'],run_id='38232778371')),
            ('start','database_opened_by_controller',True),('prepare','runtime_environment_preserved',False),
            ('start','operation_id','0'*32),('start','previous_commit','0'*40),
            ('start','database_schema',20),('start','source_warmup_performed',True),
            ('start','database_snapshot_verified',True),('start','saved_export_companion_preserved',False)]
        for target,key,value in cases:
            self.prepared.write_text(json.dumps(prepared));self.started.write_text(json.dumps(started))
            path=self.prepared if target=='prepare' else self.started
            changed=json.loads(path.read_text());changed[key]=value;path.write_text(json.dumps(changed))
            with self.subTest(target=target,key=key),self.assertRaises(ValueError):self.scenario()



    def test_actual_p4_persisted_prepare_shape_accepts_without_return_only_policy(self):
        prepared=json.loads(self.prepared.read_text())
        self.assertEqual(set(prepared),{'ok','stage','source_commit','package','images','files',
            'inventory_enabled','execution_enabled','runtime_flags_verified','runtime_environment_preserved','config_operation_id'})
        for key in ('database_policy','database_opened_by_controller','saved_export_companion_preserved'):
            self.assertNotIn(key,prepared)
        result,commands,*_=self.scenario()
        self.assertTrue(result['ok']);self.assertFalse(result['database_opened_by_controller'])
        self.assertTrue(any(args[:3]==['docker','exec','-i'] for args in commands))

    def test_persisted_started_policy_missing_or_tampered_refuses(self):
        original=json.loads(self.started.read_text())
        for key in ('database_policy','database_opened_by_controller','saved_export_companion_preserved'):
            for kind in ('missing','null','wrong'):
                changed=dict(original)
                if kind=='missing':changed.pop(key)
                elif kind=='null':changed[key]=None
                else:changed[key]='paired-snapshot' if key=='database_policy' else not original[key]
                self.started.write_text(json.dumps(changed))
                with self.subTest(key=key,kind=kind),self.assertRaisesRegex(ValueError,'^SOURCE_NOT_READY$'):self.scenario()
        self.started.write_text(json.dumps(original))

    def test_prepare_return_only_policy_cannot_substitute_started_policy(self):
        prepared=json.loads(self.prepared.read_text());prepared.update(database_policy='preserve-in-place',
            database_opened_by_controller=False,saved_export_companion_preserved=True)
        self.prepared.write_text(json.dumps(prepared));started=json.loads(self.started.read_text())
        started.pop('database_opened_by_controller');self.started.write_text(json.dumps(started))
        with self.assertRaisesRegex(ValueError,'^SOURCE_NOT_READY$'):self.scenario()





if __name__=='__main__':unittest.main()
