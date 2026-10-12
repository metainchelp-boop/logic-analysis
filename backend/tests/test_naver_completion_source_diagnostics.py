"""Offline closed projection/controller contracts; every database is synthetic."""
import ast
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time as day_time, timedelta, timezone
import gzip
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
from unittest.mock import Mock, patch

TOOLS=Path(__file__).parents[1]/'tools'
SPEC=importlib.util.spec_from_file_location('source_diagnostics',TOOLS/'naver_completion_source_diagnostics.py')
D=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
NOW=datetime(2026,10,12,19,tzinfo=D.KST)


@dataclass(frozen=True)
class SelectionSource:
    owner: object
    now: object
    snapshot: object
    present: object
    catalog: object
    catalog_state: object
    org_allowed: object
    organization: object
    fingerprint: object
    states: object
    policies: object
    manual_requests: object


class InvalidProgress(Exception):
    pass


def period(cadence, when):
    day=when.date() if isinstance(when,datetime) else when
    cycle=day if cadence=='daily' else day-timedelta(days=(day.weekday()+1)%7)
    end=day-timedelta(days=1) if cadence=='daily' else cycle-timedelta(days=1)
    return NS(cycle_day=cycle,since=end if cadence=='daily' else end-timedelta(days=6),until=end)


def bind(old,job,pid):
    return bool(old and all(old[key]==job[key] for key in ('stage_revision','generation','catalog_at','matching_fingerprint'))
        and old['possibility_id']==pid and old['snapshot_at']==job['snapshot_at'].isoformat())


class FakeStore:
    """Read API test double. Real pinned Store equivalence is a separate integration check."""
    def __init__(self,connection):
        self._conn=connection
        self.at=NOW
        self.catalog_at=NOW.isoformat()
        self.fingerprint='f'*64
        self.catalog_state='accepted'
        self.org_allowed=True
        self.ready={}
        self.states={}
        self.policies={}
        for _,pid,cid in D.TARGETS:
            self.states[cid]={'possibility_id':pid,'stage_key':'진행중','stage_revision':'r'+str(cid)}
            self.policies[cid]={'possibility_id':pid,'stage_key':'진행중','stage_revision':'r'+str(cid),
                'matched':True,'source_current':True,'decision':NS(cadence='daily',reason='MANAGED_STAGE')}

    def management_states(self): return self.states
    def inventory_snapshot(self,now): return self.at
    def decision_fingerprint(self): return self.fingerprint
    def collection_account_ready(self,cid,now): return self._collection_account_ready(cid,now.isoformat())
    def _collection_account_ready(self,cid,at): return self.ready.get(cid,True)

    def _performance_job(self,cid,kind,cycle,start,end,row,snapshot,catalog,matching_fingerprint=None):
        return dict(job_key=f'{cid}:{kind}:{cycle}:{start}:{end}',customer_id=cid,kind=kind,cycle_day=str(cycle),
            period_start=str(start),period_end=str(end),snapshot_at=snapshot,catalog_at=catalog,
            stage_revision=row['stage_revision'],matching_fingerprint=matching_fingerprint,
            generation=datetime.combine(cycle,day_time(0,1),tzinfo=D.KST).isoformat())

    def _inspection_manual_job(self,request,row,snapshot,catalog,fingerprint,now,source):
        if not request or request['request_kind']=='manual_period' or datetime.fromisoformat(request['requested_at']).date()!=now.date():
            return None
        cycle=now.date(); end=cycle-timedelta(days=1)
        start=end if row['decision'].cadence=='daily' else end-timedelta(days=6)
        job=self._performance_job(request['customer_id'],'manual',cycle,start,end,row,snapshot,catalog,fingerprint)
        job.update(job_key='inspection:'+job['job_key']+':'+request['requested_at'],requested_at=request['requested_at'],
            actor=request['actor'],generation=request['requested_at'])
        return job if self._inspection_account_valid(job,now,source) else None

    def _inspection_account_valid(self,job,now,source):
        cid=job['customer_id']; state=self.states.get(cid)
        if cid not in source.present or source.catalog_state!='accepted' or not source.org_allowed or state is None \
                or state['stage_revision']!=job['stage_revision'] or job['matching_fingerprint']!=self.fingerprint:
            return False
        if job['kind']=='manual':
            request=source.manual_requests.get(cid)
            return bool(request and request['actor']==0 and request['possibility_id']==state['possibility_id']
                and request['requested_at']==job['generation'])
        request=source.manual_requests.get(cid)
        if request and request['request_kind']!='manual_period' and request['actor']==0 \
                and datetime.fromisoformat(request['requested_at']).date()==now.date() and request['requested_at']>job['generation']:
            return False
        return job['cycle_day']==str(period(job['kind'],now).cycle_day)

    def _collection_retry_ready(self,row,at):
        return row['next_try_at']<=at and row['status'] not in ('ok','reauth_required','superseded')

    def inspection_progress(self,job):
        raw=self._conn.execute('SELECT progress_json,progress_hash FROM naver_auto_inspection_job WHERE job_key=?',(job['job_key'],)).fetchone()
        if raw is None or raw[0] is None: return None
        if hashlib.sha256(raw[0].encode()).hexdigest()!=raw[1]: raise InvalidProgress()
        return json.loads(raw[0])


def fixture():
    connection=sqlite3.connect(':memory:',isolation_level=None)
    connection.executescript('''
        CREATE TABLE naver_auto_meta(key TEXT PRIMARY KEY,value TEXT);
        INSERT INTO naver_auto_meta VALUES('schema_version','21');
        CREATE TABLE naver_auto_account(customer_id INTEGER PRIMARY KEY,present INTEGER);
        CREATE TABLE naver_auto_manual_read(customer_id INTEGER PRIMARY KEY,possibility_id INTEGER,requested_at TEXT,
            actor INTEGER,request_kind TEXT,period_start TEXT,period_end TEXT);
        CREATE TABLE naver_auto_inspection_job(job_key TEXT PRIMARY KEY,customer_id INTEGER,possibility_id INTEGER,kind TEXT,
            cycle_day TEXT,period_start TEXT,period_end TEXT,snapshot_at TEXT,catalog_at TEXT,stage_revision TEXT,
            matching_fingerprint TEXT,generation TEXT,requested_at TEXT,actor INTEGER,status TEXT,checked_at TEXT,
            next_try_at TEXT,attempts INTEGER,error_code TEXT,progress_json TEXT,progress_hash TEXT);
        CREATE TABLE naver_auto_product_link(possibility_id INTEGER PRIMARY KEY,store_key TEXT,stage_as_of TEXT);
        CREATE TABLE naver_auto_prospect(possibility_id INTEGER PRIMARY KEY,present INTEGER,stage_conflict INTEGER,stage_synced_at TEXT);
    ''')
    for table in ('naver_auto_performance_job','naver_auto_structure_job','naver_auto_funnel_job','naver_auto_experiment_job'):
        connection.execute('CREATE TABLE '+table+'(customer_id INTEGER,status TEXT,error_code TEXT,checked_at TEXT,next_try_at TEXT)')
    for _,pid,cid in D.TARGETS:
        connection.execute('INSERT INTO naver_auto_account VALUES(?,1)',(cid,))
        connection.execute('INSERT INTO naver_auto_prospect VALUES(?,1,0,?)',(pid,NOW.isoformat()))
    store=FakeStore(connection)
    def saved_job(row):
        job={key:row[key] for key in D.JOB_COLUMNS.split(',')[:12]}
        job['snapshot_at']=datetime.fromisoformat(job['snapshot_at'])
        if job['kind']=='manual': job.update(actor=row['actor'],requested_at=row['requested_at'])
        return job
    modules=dict(S=NS(_PerformanceSelectionSource=SelectionSource,_kst_text=lambda at,what:at.isoformat()),
        MS=NS(snapshot=lambda st,now,stage_states=None:st.policies,_organization=lambda st:NS()),
        I=NS(catalog_status=lambda st,now,header_only=False:({'generated_at':st.catalog_at},st.catalog_state)),
        P=NS(COLLECTION_START=day_time(0,1),period_for=period,
            is_due=lambda decision,day,started_cycle=None:day.weekday()==6 or started_cycle==period('weekly',day).cycle_day),
        IS=NS(_binding=bind,_job=saved_job,_observed_times=lambda progress:[]),IR=NS(CheckpointInvalid=InvalidProgress),
        O=NS(allows_raising=lambda current:current),Y=NS(org_freshness=lambda st,now:st.org_allowed),
        PE=NS(canonical_store=lambda value:value if value=='canonical-key' else None))
    return store,modules


def add_job(store,index=0,status='partial',error='REQUEST_CALL_CAP',next_try=None,**changes):
    _,pid,cid=D.TARGETS[index]; row=store.policies[cid]; p=period('daily',NOW)
    job=store._performance_job(cid,'daily',p.cycle_day,p.since,p.until,row,store.at,store.catalog_at,store.fingerprint)
    job['job_key']='inspection:'+job['job_key']
    job.update(possibility_id=pid,status=status,error_code=error,checked_at=NOW.isoformat(),
        next_try_at=(next_try or NOW+timedelta(minutes=2)).isoformat(),attempts=1,requested_at=None,actor=None,
        progress_json=None,progress_hash=None)
    job['snapshot_at']=job['snapshot_at'].isoformat(); job.update(changes)
    columns=list(job)
    store._conn.execute('INSERT INTO naver_auto_inspection_job ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',
        tuple(job[key] for key in columns))
    return job


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.network=patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN'))
        self.network.start();self.addCleanup(self.network.stop)
        self.store,self.modules=fixture();self.addCleanup(self.store._conn.close)

    def project(self,now=NOW):
        if self.store._conn.execute('PRAGMA query_only').fetchone() != (1,):
            self.store._conn.execute('PRAGMA query_only=ON')
        self.store._conn.set_authorizer(D.readonly_authorizer)
        baseline=self.store._conn.total_changes
        self.store._conn.execute('BEGIN')
        try:
            result=D.collect(self.store,now,time.monotonic()+20,self.modules)
            D.validate_result(result)
            self.assertEqual(self.store._conn.total_changes,baseline)
            return result
        finally:self.store._conn.execute('ROLLBACK')

    def test_no_job_and_scoped_partial_are_different_and_rank_is_snapshot_only(self):
        add_job(self.store,index=1)
        result=self.project();a=result['targets']['gomso'];b=result['targets']['foodin']
        self.assertFalse(a['inspection_job_exists_for_account']);self.assertEqual(a['snapshot_candidate_gate'],'ELIGIBLE')
        self.assertEqual(a['snapshot_candidate_rank'],1);self.assertEqual(b['latest_pair_job']['status'],'partial')
        self.assertEqual(b['snapshot_candidate_gate'],'RETRY_NOT_DUE');self.assertTrue(b['latest_pair_binding']['current_valid'])
        self.assertEqual(result['candidate_snapshot']['eligible_count'],1)
        self.assertTrue(result['limits']['dispatch_order_not_proven'])

    def test_exact_second_due_and_snapshot_use_product_microsecond_text(self):
        canonical=lambda at,what:at.astimezone(D.KST).isoformat(timespec='microseconds')
        self.modules['S']._kst_text=canonical
        self.modules['IS']._binding=lambda old,job,pid:bool(old
            and all(old[key]==job[key] for key in ('stage_revision','generation','catalog_at','matching_fingerprint'))
            and old['possibility_id']==pid and old['snapshot_at']==canonical(job['snapshot_at'],'계정 원천'))
        add_job(self.store,checked_at=canonical(NOW,'현재'),next_try_at=canonical(NOW,'현재'),
            snapshot_at=canonical(NOW,'계정 원천'))
        row=self.project()['targets']['gomso']
        self.assertEqual(row['snapshot_candidate_gate'],'ELIGIBLE')
        self.assertTrue(row['latest_pair_binding']['account_snapshot_matches'])
        self.assertTrue(row['current_job_binding_matches'])

    def test_other_pair_job_does_not_become_current_pair(self):
        add_job(self.store,possibility_id=999)
        row=self.project()['targets']['gomso']
        self.assertTrue(row['inspection_job_exists_for_account']);self.assertFalse(row['inspection_job_exists_for_expected_pair'])
        self.assertTrue(row['inspection_job_exists_for_other_pair']);self.assertEqual(row['latest_account_job']['scope'],'other_pair')
        self.assertNotIn('999',json.dumps(row))

    def test_stale_source_keeps_saved_and_current_separate(self):
        add_job(self.store)
        self.store.catalog_state='stale'
        self.store.policies[D.TARGETS[0][2]]['source_current']=False
        self.store.policies[D.TARGETS[0][2]]['decision']=NS(cadence='blocked',reason='SOURCE_STALE')
        row=self.project()['targets']['gomso']
        self.assertTrue(row['inspection_job_exists_for_expected_pair']);self.assertFalse(row['latest_pair_binding']['current_valid'])
        self.assertEqual(row['snapshot_candidate_gate'],'POLICY_BLOCKED')

    def test_management_sync_pending_closes_rank_and_count(self):
        self.store.policies[D.TARGETS[0][2]]['stage_revision']='pending-not-a-current-revision'
        result=self.project()
        self.assertFalse(result['candidate_snapshot']['rank_exact']);self.assertIsNone(result['candidate_snapshot']['eligible_count'])
        self.assertIsNone(result['targets']['foodin']['snapshot_candidate_rank'])
        self.assertEqual(result['targets']['gomso']['snapshot_candidate_gate'],'MANAGEMENT_SYNC_PENDING')

    def test_backoff_is_separate_from_due(self):
        self.store.ready[D.TARGETS[0][2]]=False
        row=self.project()['targets']['gomso']
        self.assertFalse(row['collection_account_ready']);self.assertEqual(row['snapshot_candidate_gate'],'ACCOUNT_BACKOFF')

    def test_newer_manual_generation_does_not_borrow_saved_automatic_job(self):
        add_job(self.store,status='ok',error=None)
        _,pid,cid=D.TARGETS[0]
        self.store._conn.execute('INSERT INTO naver_auto_manual_read VALUES(?,?,?,?,?,?,?)',
            (cid,pid,(NOW-timedelta(minutes=1)).isoformat(),0,'manual',None,None))
        row=self.project()['targets']['gomso']
        self.assertTrue(row['manual_read']['valid_current_inspection_request'])
        self.assertFalse(row['latest_pair_binding']['current_valid']);self.assertFalse(row['current_job_binding_matches'])
        self.assertEqual(row['snapshot_candidate_gate'],'ELIGIBLE')

    def test_prior_day_and_invalid_actor_manual_are_not_active(self):
        _,pid,cid=D.TARGETS[0]
        self.store._conn.execute('INSERT INTO naver_auto_manual_read VALUES(?,?,?,?,?,?,?)',
            (cid,pid,(NOW-timedelta(days=1)).isoformat(),0,'manual',None,None))
        row=self.project()['targets']['gomso']
        self.assertFalse(row['manual_read']['requested_today']);self.assertFalse(row['manual_read']['valid_current_inspection_request'])

    def test_weekly_gate_and_collection_start(self):
        cid=D.TARGETS[0][2];self.store.policies[cid]['decision']=NS(cadence='weekly',reason='NONMANAGED_STAGE')
        self.assertEqual(self.project()['targets']['gomso']['snapshot_candidate_gate'],'WEEKLY_NOT_DUE')
        self.assertEqual(self.project(NOW.replace(hour=0,minute=0))['targets']['foodin']['snapshot_candidate_gate'],'BEFORE_START')

    def test_changed_saved_binding_does_not_reuse_old_retry_gate(self):
        add_job(self.store,matching_fingerprint='b'*64)
        row=self.project()['targets']['gomso']
        self.assertEqual(row['snapshot_candidate_gate'],'ELIGIBLE')
        self.assertFalse(row['latest_pair_binding']['matching_revision_matches'])

    def test_canonical_product_link_requires_current_erp_stage(self):
        for index,stage in ((0,NOW.isoformat()),(1,(NOW-timedelta(days=1)).isoformat())):
            self.store._conn.execute('INSERT INTO naver_auto_product_link VALUES(?,?,?)',(D.TARGETS[index][1],'canonical-key',stage))
        result=self.project()['targets']
        self.assertTrue(result['gomso']['canonical_erp_product_link_present'])
        self.assertFalse(result['foodin']['canonical_erp_product_link_present'])
        self.assertNotIn('canonical-key',json.dumps(result))

    def settings(self,count=2):
        entities={}
        for index in range(count):
            identifier='cmp-'+str(index)
            entities[identifier]={'entity':'campaign','id':identifier,'campaign_id':identifier,'settings':{
                'dailyBudget':0,'useDailyBudget':False,'usePeriod':True,'periodStartDt':'2026-10-01T00:00:00+09:00',
                'periodEndDt':'2026-10-31','name':'PRIVATE_NAME','keyword':'PRIVATE_KEYWORD','bidAmt':None}}
        return {'campaigns':[{'nccCampaignId':key} for key in entities], 'entities':entities,
            'confirmed':False,'next_index':0,'queue':[1]}

    def test_only_exact_settings_fields_and_missing_is_unknown_not_spend(self):
        progress=self.settings();progress['entities']['grp-1']={'entity':'adgroup','id':'grp-1','campaign_id':'cmp-0',
            'settings':{'bidAmt':123,'dailyBudget':1.5,'name':'PRIVATE_NAME','salesAmt':987654321}}
        raw=json.dumps(progress);add_job(self.store,progress_json=raw,progress_hash=hashlib.sha256(raw.encode()).hexdigest())
        row=self.project()['targets']['gomso']['settings']
        self.assertEqual(row['source_state'],'current_partial');self.assertEqual(row['items'][0]['daily_budget'],0)
        self.assertFalse(row['items'][0]['use_daily_budget']);self.assertEqual(row['items'][0]['period_start'],'2026-10-01')
        self.assertEqual(row['items'][-1]['bid_amount'],123);self.assertIsNone(row['items'][-1]['daily_budget'])
        for private in ('PRIVATE_NAME','PRIVATE_KEYWORD','salesAmt','987654321','cmp-0','grp-1'):
            self.assertNotIn(private,json.dumps(row))

    def test_settings_limit_and_stale_never_become_current(self):
        progress=self.settings(21);raw=json.dumps(progress)
        add_job(self.store,progress_json=raw,progress_hash=hashlib.sha256(raw.encode()).hexdigest(),matching_fingerprint='b'*64)
        settings=self.project()['targets']['gomso']['settings']
        self.assertEqual(len(settings['items']),20);self.assertTrue(settings['truncated'])
        self.assertEqual(settings['source_state'],'stored_stale');self.assertFalse(settings['current_valid'])

    def test_invalid_checkpoint_is_closed_without_raw_body(self):
        add_job(self.store,progress_json='PRIVATE_RAW_BODY',progress_hash='0'*64)
        settings=self.project()['targets']['gomso']['settings']
        self.assertEqual(settings['source_state'],'invalid');self.assertEqual(settings['items'],[])

    def test_schema_deadline_and_targets_fail_closed(self):
        self.store._conn.execute("UPDATE naver_auto_meta SET value='11'")
        with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_SCHEMA'):
            D.collect(self.store,NOW,time.monotonic()+20,self.modules)
        with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_TARGETS'):
            D.collect(self.store,NOW,time.monotonic()+20,self.modules,targets=(('other',1,1),))
        with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_DEADLINE'):D.check_deadline(0)

    def test_output_rejects_extra_fields_unknown_enum_and_bool_as_integer(self):
        result=self.project()
        for change in ('extra','enum','bool','limit','raw'):
            value=deepcopy(result)
            if change=='extra':value['extra']='PRIVATE'
            elif change=='enum':value['targets']['gomso']['snapshot_candidate_gate']='PRIVATE'
            elif change=='bool':value['candidate_snapshot']['eligible_count']=True
            elif change=='limit':value['limits']['dispatch_order_not_proven']=False
            else:value['targets']['gomso']['manual_read']['actor']=100
            with self.subTest(change=change),self.assertRaises(ValueError):D.validate_result(value)


class BoundariesTests(unittest.TestCase):
    def test_package_has_no_dynamic_account_query_or_source_escape(self):
        package=dict(baseline=D.BASELINE,source_commit=D.SOURCE,source_tar_gz_sha256=D.ARCHIVE,mode=D.MODE)
        D.validate_package(package)
        for key,value in (('source_commit','f'*40),('source_tar_gz_sha256','0'*64),('targets',[]),('mode','arbitrary-query')):
            with self.subTest(key=key),self.assertRaises(ValueError):D.validate_package(dict(package,**{key:value}))

    def test_script_pins_before_database_and_never_calls_writer_or_network(self):
        source=D.script().decode();ast.parse(source)
        self.assertLess(source.index('SOURCE_DIAGNOSTICS_CODE_PIN'),source.index('connection=connect_reader'))
        for required in ('writer=False',"connection.execute('BEGIN')","connection.execute('ROLLBACK')",'time.monotonic()+20',
                'connection.total_changes!=0','socket.socket.connect=socket.socket.connect_ex=no_network','MS.snapshot'):
            self.assertIn(required,source)
        for forbidden in ('inspection_work(', '_performance_selection_source(', 'synchronize_management(', 'open_writer(',
                'run_inspection(', 'run_performance(', 'request_collection(', 'SELECT payload_json', 'store 2.py'):
            self.assertNotIn(forbidden,source)
        self.assertEqual(D.SCHEMA,21);self.assertEqual(D.MAX_OUTPUT,16384)
        self.assertEqual(len(D.CODE_PINS),11)

    def test_readonly_connection_denies_mutation_attach_and_pragma_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=(Path(directory)/'fixture.db').resolve()
            connection=sqlite3.connect(path);connection.execute('CREATE TABLE fixture(value INTEGER)');connection.commit();connection.close()
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            reader=D.connect_reader(path)
            try:
                reader.execute('BEGIN');self.assertEqual(reader.execute('SELECT count(*) FROM fixture').fetchone(),(0,))
                for sql in ('INSERT INTO fixture VALUES(1)','CREATE TABLE other(value)','PRAGMA query_only=OFF',
                            "ATTACH DATABASE ':memory:' AS other",'DROP TABLE fixture'):
                    with self.subTest(sql=sql),self.assertRaises(sqlite3.DatabaseError):reader.execute(sql)
                reader.execute('ROLLBACK');self.assertEqual(reader.total_changes,0)
            finally:reader.close()
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
            link=Path(directory)/'link.db';link.symlink_to(path)
            with self.assertRaisesRegex(ValueError,'SOURCE_DIAGNOSTICS_DATABASE_PATH'):D.connect_reader(link)

    def test_unexpanded_existing_wire_limits_fit(self):
        bundle=dict(operation='preview-source-diagnostics',function='run',package=dict(baseline=D.BASELINE,
            source_commit=D.SOURCE,source_tar_gz_sha256=D.ARCHIVE,mode=D.MODE),source=(TOOLS/'naver_completion_source_diagnostics.py').read_text(),
            release_source=(TOOLS/'naver_preview_release.py').read_text(),host_source=(TOOLS/'naver_erp_tunnel_service_install.py').read_text())
        raw=json.dumps(bundle).encode();wire='code-gzip-v1:'+__import__('base64').b64encode(gzip.compress(raw,mtime=0)).decode()
        self.assertLessEqual(len(raw),229376);self.assertLessEqual(len(wire),73728)


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
            package=self.package,files=files,images={'engine':self.image},inventory_enabled=True,execution_enabled=False,runtime_flags_verified=True)))
        self.started.write_text(json.dumps(dict(ok=True,stage='internal_ready',source_commit=D.SOURCE,
            database_schema=21,execution_enabled=False,runtime_flags_verified=True)))
        self.before=dict(id=self.identity,image=self.image,running=True,user='10001:10001',project='naver-engine',
            service='naver-engine',started='2026-10-12T10:00:00Z',restarts=0,readonly=True,
            data=[{'Type':'bind','Destination':'/var/lib/naver-engine','Source':'/var/lib/metainc/naver-engine'}])
        store,modules=fixture()
        try:self.result=D.collect(store,NOW,time.monotonic()+20,modules)
        finally:store._conn.close()

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


if __name__=='__main__':unittest.main()
