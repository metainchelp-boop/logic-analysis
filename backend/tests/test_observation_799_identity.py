"""Closed terminal sidecar identity tests; all rows are invented in :memory:."""
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib
import json
import sqlite3
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from test_naver_observation_799_diagnostics import D,result_fixture
NOW=datetime(2026,10,13,2,tzinfo=D.KST)
EVENT=datetime(2026,10,13,1,27,30,tzinfo=D.KST)

DETAIL=dict(stage='document-validation',error_class='provider-refused',provider_invocation_attempted=True,
    observation_bound=True,observation_flushed=False)
CID,PID,RID=90001030001,51952,41
KEY=hashlib.sha256(str(CID).encode('ascii')).hexdigest()
FP='b'*64

def fixture():
    c=sqlite3.connect(':memory:',isolation_level=None)
    c.executescript('CREATE TABLE naver_auto_meta(key TEXT PRIMARY KEY,value TEXT);'
        'CREATE TABLE naver_auto_report_snapshot(report_id INTEGER PRIMARY KEY,possibility_id INTEGER,period_key TEXT,revision_fingerprint TEXT,payload_json TEXT);'
        'CREATE TABLE naver_auto_report_dirty(possibility_id INTEGER,period_key TEXT,pending INTEGER);')
    period=dict(kind='weekly',start='2026-10-05',end='2026-10-11')
    payload=dict(period_key=D.LEARNING_PERIOD,period=period,revision_fingerprint=FP,revision_no=4,
        _account_reports={str(CID):dict(period_key=D.LEARNING_PERIOD,period=period,revision_no=4)})
    c.execute('INSERT INTO naver_auto_report_snapshot VALUES(?,?,?,?,?)',(RID,PID,D.LEARNING_PERIOD,FP,json.dumps(payload)))
    job=dict(job_id='a'*32,actor=773,narrowed=False,report_id=RID,account_key=KEY,revision_fingerprint=FP,
        expected_version=0,expires_at=(NOW+timedelta(hours=1)).isoformat(),proof_hash='c'*64,state='failed',created_at=(EVENT-timedelta(seconds=1)).isoformat(),
        updated_at=(EVENT+timedelta(seconds=15)).isoformat(),diagnostic=dict(code='document-invalid',http_status=None),result_version=None)
    reserved=dict(actor=773,at=EVENT.isoformat(),reserved_microusd=106496,proof_hash=job['proof_hash'],
        report_id=RID,account_key=KEY,possibility_id=PID)
    side=dict(job_id=job['job_id'],detail=deepcopy(DETAIL))
    store=NS(_conn=c,_learning_actor=Mock(return_value=(None,None)))
    policy=dict(possibility_id=PID,matched=True,source_current=True)
    return store,policy,payload,job,reserved,side

def save(c,job,reserved,side):
    for prefix,suffix,value in (('learning-job:',D.learning_identity(job),job),('learning-call:',job['job_id'],reserved),
                              ('learning-failure:',D.learning_identity(job),side)):
        c.execute('INSERT INTO naver_auto_meta VALUES(?,?)',(prefix+suffix,json.dumps(value)))

class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.st,self.policy,self.payload,self.job,self.res,self.side=fixture();self.addCleanup(self.st._conn.close)
    def projection(self):
        return D.learning_failure_projection(self.st,NOW,time.monotonic()+20,CID,PID,self.policy)
    def save(self):save(self.st._conn,self.job,self.res,self.side)
    def payload_save(self):
        self.st._conn.execute('UPDATE naver_auto_report_snapshot SET payload_json=? WHERE report_id=?',(json.dumps(self.payload),RID))
    def test_exact_identity_returns_five_fields_and_does_not_leak_identifiers(self):
        self.save();before=self.st._conn.total_changes;out=self.projection()
        self.assertEqual(out,DETAIL);self.assertEqual(self.st._conn.total_changes,before)
        self.st._learning_actor.assert_called_once_with(PID,KEY,773,NOW,narrowed=False)
        for private in (KEY,FP,self.job['job_id'],'106496','51952','773','report_id'):
            self.assertNotIn(private,json.dumps(out))
    def test_numeric_revision_is_not_report_id_and_ad_number_is_not_customer_id(self):
        self.assertNotEqual(RID,4);self.assertNotEqual(CID,1030001);self.save();self.assertEqual(self.projection(),DETAIL)
    def test_readonly_authorizer_query_only_single_snapshot_keeps_rows_unchanged(self):
        self.save();c=self.st._conn;before=c.total_changes;c.execute('PRAGMA query_only=ON');c.set_authorizer(D.readonly_authorizer)
        c.execute('BEGIN');self.assertEqual(self.projection(),DETAIL);self.assertEqual(c.total_changes,before)
        with self.assertRaises(sqlite3.DatabaseError):c.execute("UPDATE naver_auto_meta SET value='private'")
        c.execute('ROLLBACK')
    def test_current_policy_and_authority_fail_closed(self):
        self.save()
        for changes in ({'matched':False},{'source_current':False},{'possibility_id':1}):
            old=self.policy.copy();self.policy.update(changes);self.assertIsNone(self.projection());self.policy=old
        self.st._learning_actor.side_effect=RuntimeError('PRIVATE_AUTHORITY');self.assertIsNone(self.projection())
    def test_latest_report_supersedes_old_same_period_scope(self):
        self.save();self.st._conn.execute('INSERT INTO naver_auto_report_snapshot VALUES(?,?,?,?,?)',
            (RID+1,PID,D.LEARNING_PERIOD,'d'*64,json.dumps(self.payload)));self.assertIsNone(self.projection())
    def test_period_fingerprint_numeric_account_revision_and_account_namespace_must_match(self):
        original=deepcopy(self.payload);self.save()
        changes=(lambda p:p.update(period_key='monthly:other'),lambda p:p.update(revision_fingerprint='d'*64),
            lambda p:p.update(revision_no=True),lambda p:p.update(revision_no=3),
            lambda p:p['_account_reports'][str(CID)].update(revision_no=3),
            lambda p:p.update(_account_reports={str(1030001):p['_account_reports'][str(CID)]}))
        for change in changes:
            with self.subTest(change=changes.index(change)):
                self.payload=deepcopy(original);change(self.payload);self.payload_save();self.assertIsNone(self.projection())
    def test_explicit_malformed_numeric_revision_never_promotes_by_count(self):
        self.save();c=self.st._conn
        for old in (1,2,3):
            c.execute('INSERT INTO naver_auto_report_snapshot VALUES(?,?,?,?,?)',(old,PID,D.LEARNING_PERIOD,FP,json.dumps(self.payload)))
        for malformed in (False,0,None,''):
            self.payload['revision_no']=malformed;self.payload_save();self.assertIsNone(self.projection())
        self.payload.pop('revision_no');self.payload_save();self.assertEqual(self.projection(),DETAIL)

    def test_selected_account_expected_customers_matches_current_report_view_scope(self):
        self.save();account=self.payload['_account_reports'][str(CID)]
        for malformed in ([CID+1],[],[CID,CID+1],str(CID),[float(CID)]):
            account['_expected_customers']=malformed;self.payload_save();self.assertIsNone(self.projection())
        account['_expected_customers']=[CID];self.payload_save();self.assertEqual(self.projection(),DETAIL)

    def test_dirty_pending_or_current_strategy_head_is_unknown(self):
        self.save();c=self.st._conn;c.execute('INSERT INTO naver_auto_report_dirty VALUES(?,?,1)',(PID,D.LEARNING_PERIOD));self.assertIsNone(self.projection())
        c.execute('UPDATE naver_auto_report_dirty SET pending=0');self.assertEqual(self.projection(),DETAIL)
        c.execute('INSERT INTO naver_auto_meta VALUES(?,?)',('report-strategy-head:'+str(RID)+':'+KEY,'PRIVATE'));self.assertIsNone(self.projection())
    def test_no_job_or_multiple_narrowed_jobs_is_unknown(self):
        self.assertIsNone(self.projection());self.save();other=dict(self.job,narrowed=True,job_id='d'*32)
        self.st._conn.execute('INSERT INTO naver_auto_meta VALUES(?,?)',('learning-job:'+D.learning_identity(other),json.dumps(other)))
        self.st._conn.execute('INSERT INTO naver_auto_meta VALUES(?,?)',('learning-call:'+other['job_id'],json.dumps(self.res)));self.assertIsNone(self.projection())
    def test_event_owner_is_discovered_without_fixed_actor_and_multiple_owners_is_unknown(self):
        self.job['actor']=100;self.res['actor']=100;self.save();self.assertEqual(self.projection(),DETAIL)
        self.st._learning_actor.assert_called_once_with(PID,KEY,100,NOW,narrowed=False)
        other=dict(self.job,actor=101,job_id='d'*32);reserved=dict(self.res,actor=101)
        save(self.st._conn,other,reserved,dict(self.side,job_id=other['job_id']));self.assertIsNone(self.projection())

    def test_fixed_minute_bounds_expiry_and_event_time_order_cannot_expand(self):
        original=dict(self.job);original_res=dict(self.res)
        for field,value in (('at','2026-10-13T01:26:59.999999+09:00'),('at','2026-10-13T01:28:00+09:00'),
                ('at','2026-10-12T01:27:30+09:00'),('expires_at',EVENT.isoformat()),
                ('expires_at',self.job['updated_at']),('expires_at','2026-10-13T01:27:44.999999+09:00'),
                ('created_at','2026-10-13T01:27:31+09:00'),('updated_at','2026-10-13T01:27:29+09:00')):
            with self.subTest(field=field,value=value):
                st,policy,payload,job,res,side=fixture();self.addCleanup(st._conn.close)
                (res if field=='at' else job)[field]=value;save(st._conn,job,res,side)
                self.assertIsNone(D.learning_failure_projection(st,NOW,time.monotonic()+20,CID,PID,policy))
        self.res['at']='2026-10-12T16:27:30+00:00';self.save();self.assertEqual(self.projection(),DETAIL)

    def test_completed_authorized_event_remains_readable_after_original_token_expires(self):
        self.job['expires_at']=(EVENT+timedelta(minutes=1)).isoformat()
        self.assertLess(datetime.fromisoformat(self.job['expires_at']),NOW)
        self.save();self.assertEqual(self.projection(),DETAIL)
        self.st._learning_actor.assert_called_once_with(PID,KEY,773,NOW,narrowed=False)
        self.st._learning_actor.side_effect=RuntimeError('PRIVATE_CURRENT_AUTHORITY')
        self.assertIsNone(self.projection())

    def test_nonterminal_job_is_unknown(self):
        for state in ('queued','running','succeeded'):
            with self.subTest(state=state):
                st,policy,payload,job,res,side=fixture();self.addCleanup(st._conn.close)
                job.update(state=state,diagnostic=None,result_version=1 if state=='succeeded' else None);save(st._conn,job,res,side)
                self.assertIsNone(D.learning_failure_projection(st,NOW,time.monotonic()+20,CID,PID,policy))
    def test_wrong_actor_account_fingerprint_version_and_jobkey_fail_closed(self):
        changes=({'actor':1},{'account_key':hashlib.sha256(b'1030001').hexdigest()},{'revision_fingerprint':'d'*64},
                 {'expected_version':1},{'report_id':4})
        for change in changes:
            with self.subTest(change=change):
                st,policy,payload,job,res,side=fixture();self.addCleanup(st._conn.close);job.update(change);save(st._conn,job,res,side)
                self.assertIsNone(D.learning_failure_projection(st,NOW,time.monotonic()+20,CID,PID,policy))
        self.save();self.st._conn.execute("UPDATE naver_auto_meta SET key=? WHERE key LIKE 'learning-job:%'",('learning-job:'+'e'*64,));self.assertIsNone(self.projection())
    def test_corrupt_job_abi_uuid_strict_boolean_and_timestamp_are_unknown(self):
        for change in ({'job_id':'x'*32},{'narrowed':0},{'created_at':'2026-10-13T01:27:00'},
                       {'actor':True},{'diagnostic':{'code':'unknown','http_status':400}},{'extra':'PRIVATE'}):
            with self.subTest(change=list(change)):
                st,policy,payload,job,res,side=fixture();self.addCleanup(st._conn.close);identity=D.learning_identity(job);job.update(change)
                st._conn.execute('INSERT INTO naver_auto_meta VALUES(?,?)',('learning-job:'+identity,json.dumps(job)))
                self.assertIsNone(D.learning_failure_projection(st,NOW,time.monotonic()+20,CID,PID,policy))
    def test_reservation_identity_and_size_are_checked(self):
        for change in ({'actor':774},{'proof_hash':'d'*64},{'report_id':4},{'account_key':'d'*64},
                       {'possibility_id':1},{'reserved_microusd':True},{'at':'invalid'},{'extra':'PRIVATE'}):
            with self.subTest(change=list(change)):
                st,policy,payload,job,res,side=fixture();self.addCleanup(st._conn.close);res.update(change);save(st._conn,job,res,side)
                self.assertIsNone(D.learning_failure_projection(st,NOW,time.monotonic()+20,CID,PID,policy))
    def test_sidecar_stale_retry_uuid_unknown_enum_and_nonbool_are_unknown(self):
        for change in ({'job_id':'d'*32},{'detail':dict(DETAIL,stage='PRIVATE')},{'detail':dict(DETAIL,error_class='PRIVATE')},
                       {'detail':dict(DETAIL,observation_bound=1)},{'detail':dict(DETAIL,provider_invocation_attempted=1)},
                       {'detail':dict(DETAIL,raw='PRIVATE')}):
            with self.subTest(change=list(change)):
                st,policy,payload,job,res,side=fixture();self.addCleanup(st._conn.close);side.update(change);save(st._conn,job,res,side)
                self.assertIsNone(D.learning_failure_projection(st,NOW,time.monotonic()+20,CID,PID,policy))
    def test_duplicate_json_keys_missing_sidecar_and_oversize_are_unknown(self):
        self.save();c=self.st._conn;key='learning-failure:'+D.learning_identity(self.job)
        original=json.dumps(self.side)
        for value in ('{"job_id":"'+self.job['job_id']+'","job_id":"'+self.job['job_id']+'","detail":'+json.dumps(DETAIL)+'}',
                      original+' '*1025,'{"job_id":"'+self.job['job_id']+'","detail":NaN}'):
            c.execute('UPDATE naver_auto_meta SET value=? WHERE key=?',(value,key));self.assertIsNone(self.projection())
        c.execute('DELETE FROM naver_auto_meta WHERE key=?',(key,));self.assertIsNone(self.projection())
    def test_aggregate_job_limit_cannot_select_unbounded_metadata(self):
        self.save();c=self.st._conn
        for n in range(100):c.execute('INSERT INTO naver_auto_meta VALUES(?,?)',('learning-job:'+str(n).zfill(64),'{}'))
        self.assertIsNone(self.projection())
    def test_unpopulated_fixed_event_refuses_before_host_or_operating_database(self):
        self.save()
        package=dict(baseline=D.BASELINE,source_commit=D.SOURCE,source_tar_gz_sha256=D.ARCHIVE,mode=D.MODE,
            p6_controller_sha256=D.P6_CONTROLLER_SHA256,native_run_id=D.NATIVE_RUN,canonical_sha256=D.CANONICAL_SHA256,event_selector=D.EVENT_SELECTOR)
        host=Mock();release=Mock()
        with patch.object(D,'EVENT_SELECTOR',None):
            self.assertIsNone(self.projection())
            with self.assertRaisesRegex(ValueError,'^SOURCE_DIAGNOSTICS_NOT_PINNED$'):D.run(package,host,release)
        self.assertEqual(host.mock_calls,[]);self.assertEqual(release.mock_calls,[])

    def test_null_flags_remain_unknown_not_false(self):
        self.side['detail'].update(observation_bound=None,observation_flushed=None);self.save()
        self.assertEqual(self.projection(),self.side['detail']);self.assertIsNone(self.projection()['observation_bound'])
    def test_output_closed_fields_disallow_cross_target_or_stale_policy(self):
        out=result_fixture();out['targets']['foodin']['learning_failure']=DETAIL;D.validate_result(out)
        for label in ('foodin','gomso'):
            changed=deepcopy(out);changed['targets'][label]['learning_failure']=dict(DETAIL,raw='PRIVATE')
            with self.assertRaises(ValueError):D.validate_result(changed)
        changed=deepcopy(out);changed['targets']['foodin']['policy']['source_current']=False
        with self.assertRaises(ValueError):D.validate_result(changed)

if __name__=='__main__':unittest.main()
