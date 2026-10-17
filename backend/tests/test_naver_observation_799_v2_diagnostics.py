"""799 v2 portable synthetic read-only cases; no product clone or operating DB."""
from copy import deepcopy
from datetime import timedelta
import ast,hashlib,importlib.util,json,sqlite3,sys,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch

TOOLS=Path(__file__).resolve().parents[1]/'tools'
OLD_TESTS=Path(__file__).resolve().parent
if not (OLD_TESTS/'test_observation_799_identity.py').is_file():
    OLD_TESTS=TOOLS.parents[1]/'observation-readonly-799-20261013/tests'
sys.path.insert(0,str(OLD_TESTS))
from test_observation_799_identity import D as V1,fixture,save,DETAIL,NOW,EVENT,CID,PID,RID,KEY
from test_naver_observation_799_diagnostics import result_fixture as old_result_fixture
spec=importlib.util.spec_from_file_location('observation799_v2_portable',TOOLS/'naver_observation_799_diagnostics_v2.py')
D=importlib.util.module_from_spec(spec);spec.loader.exec_module(D)

class SyntheticScopeRefusal(Exception):pass

def result_fixture():
    value=old_result_fixture();value['projection_model']='799-setup-observation-v2'
    value['targets']['gomso']['learning_failure_reason']='NOT_SELECTED_TARGET'
    value['targets']['foodin']['learning_failure_reason']='REPORT_NOT_FOUND'
    return value

class ResolverTests(unittest.TestCase):
    def case(self,change=None):
        st,policy,payload,job,res,side=fixture();self.addCleanup(st._conn.close)
        job['actor']=res['actor']=100
        if change:change(st,policy,payload,job,res,side)
        save(st._conn,job,res,side)
        return st,policy
    def check_reason(self,expected,change=None,after=None):
        st,policy=self.case(change)
        if after:after(st)
        before=st._conn.total_changes;st._conn.execute('PRAGMA query_only=ON');st._conn.set_authorizer(D.readonly_authorizer);st._conn.execute('BEGIN')
        try:
            old=V1.learning_failure_projection(st,NOW,time.monotonic()+20,CID,PID,policy)
            actual=D.learning_failure_resolution(st,NOW,time.monotonic()+20,CID,PID,policy,authority_refusals=(SyntheticScopeRefusal,))
            self.assertEqual(st._conn.total_changes,before)
            serialize=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
            self.assertEqual(serialize(actual['learning_failure']),serialize(old))
            self.assertEqual(actual['learning_failure_reason'],expected)
            self.assertEqual(set(actual),{'learning_failure','learning_failure_reason'})
            value=result_fixture();value['targets']['foodin'].update(actual)
            if expected=='POLICY_NOT_CURRENT':value['targets']['foodin']['policy']['source_current']=False
            D.validate_result(value)
        finally:st._conn.execute('ROLLBACK');st._conn.set_authorizer(None)
    def test_observed_returns_same_five_fields(self):self.check_reason('OBSERVED')
    def test_policy_not_current(self):self.check_reason('POLICY_NOT_CURRENT',lambda s,p,*rest:p.update(source_current=False))
    def test_report_not_found(self):self.check_reason('REPORT_NOT_FOUND',after=lambda s:s._conn.execute('DELETE FROM naver_auto_report_snapshot'))
    def test_numeric_revision_changed(self):
        def change(s,p,payload,*rest):
            payload['revision_no']=5;s._conn.execute('UPDATE naver_auto_report_snapshot SET payload_json=?',(json.dumps(payload),))
        self.check_reason('NUMERIC_REVISION_MISMATCH',change)
    def test_report_scope_mismatch(self):
        def change(s,p,payload,*rest):
            payload['_account_reports']={str(1030001):payload['_account_reports'][str(CID)]}
            s._conn.execute('UPDATE naver_auto_report_snapshot SET payload_json=?',(json.dumps(payload),))
        self.check_reason('REPORT_SCOPE_MISMATCH',change)
    def test_current_report_dirty(self):self.check_reason('REPORT_DIRTY',after=lambda s:s._conn.execute('INSERT INTO naver_auto_report_dirty VALUES(?,?,1)',(PID,D.LEARNING_PERIOD)))
    def test_current_strategy_head_exists(self):self.check_reason('STRATEGY_REVISION_CHANGED',after=lambda s:s._conn.execute('INSERT INTO naver_auto_meta VALUES(?,?)',('report-strategy-head:'+str(RID)+':'+KEY,'PRIVATE')))
    def test_fixed_event_not_found(self):self.check_reason('EVENT_NOT_FOUND',lambda s,p,pl,j,r,side:r.update(at=(EVENT-timedelta(minutes=1)).isoformat()))
    def test_reservation_identity_mismatch(self):self.check_reason('RESERVATION_INVALID',lambda s,p,pl,j,r,side:r.update(proof_hash='d'*64))
    def test_event_time_invalid(self):self.check_reason('EVENT_TIME_INVALID',lambda s,p,pl,j,r,side:j.update(expires_at=j['updated_at']))
    def test_multiple_exact_events_are_ambiguous(self):
        def duplicate(st):
            old=json.loads(st._conn.execute("SELECT value FROM naver_auto_meta WHERE key LIKE 'learning-job:%'").fetchone()[0]);other=dict(old,actor=101,job_id='d'*32)
            res=json.loads(st._conn.execute("SELECT value FROM naver_auto_meta WHERE key LIKE 'learning-call:%'").fetchone()[0]);save(st._conn,other,dict(res,actor=101),dict(job_id=other['job_id'],detail=DETAIL))
        self.check_reason('EVENT_AMBIGUOUS',after=duplicate)
    def test_event_not_terminal(self):self.check_reason('EVENT_NOT_TERMINAL',lambda s,p,pl,j,r,side:j.update(state='running',diagnostic=None))
    def test_typed_current_authority_refusal(self):self.check_reason('CURRENT_AUTHORITY_REFUSED',lambda s,*rest:setattr(s._learning_actor,'side_effect',SyntheticScopeRefusal()))
    def test_current_authority_internal_error_is_not_permission_refusal(self):self.check_reason('READ_INTERNAL_ERROR',lambda s,*rest:setattr(s._learning_actor,'side_effect',RuntimeError('PRIVATE')))
    def test_current_authority_sql_error_is_not_permission_refusal(self):self.check_reason('READ_SQL_ERROR',lambda s,*rest:setattr(s._learning_actor,'side_effect',sqlite3.OperationalError('PRIVATE')))
    def test_sql_busy_uses_primary_code_only(self):
        error=sqlite3.OperationalError('PRIVATE');error.sqlite_errorcode=sqlite3.SQLITE_BUSY
        self.check_reason('READ_SQL_BUSY',lambda s,*rest:setattr(s._learning_actor,'side_effect',error))
    def test_sidecar_missing(self):self.check_reason('SIDECAR_MISSING',after=lambda s:s._conn.execute("DELETE FROM naver_auto_meta WHERE key LIKE 'learning-failure:%'"))
    def test_sidecar_job_mismatch(self):self.check_reason('SIDECAR_JOB_MISMATCH',lambda s,p,pl,j,r,side:side.update(job_id='d'*32))
    def test_sidecar_shape_invalid(self):self.check_reason('SIDECAR_SHAPE_INVALID',lambda s,p,pl,j,r,side:side['detail'].update(raw='PRIVATE'))
    def test_job_set_invalid(self):self.check_reason('JOB_SET_INVALID',after=lambda s:s._conn.execute("UPDATE naver_auto_meta SET value='{}' WHERE key LIKE 'learning-job:%'"))
    def test_sql_missing_table_is_closed(self):self.check_reason('READ_SQL_ERROR',after=lambda s:s._conn.execute('DROP TABLE naver_auto_report_snapshot'))
    def test_report_shape_invalid(self):self.check_reason('READ_SHAPE_ERROR',after=lambda s:s._conn.execute("UPDATE naver_auto_report_snapshot SET payload_json='{}broken'"))
    def test_read_deadline_cannot_return_detail(self):
        st,policy=self.case();deadline=time.monotonic()-1
        self.assertIsNone(V1.learning_failure_projection(st,NOW,deadline,CID,PID,policy))
        self.assertEqual(D.learning_failure_resolution(st,NOW,deadline,CID,PID,policy),dict(learning_failure=None,learning_failure_reason='READ_BOUND_EXCEEDED'))
    def test_other_target_does_not_read_or_borrow_event(self):
        store=Mock()
        self.assertEqual(D.learning_failure_resolution(store,NOW,time.monotonic()+20,42,74789,None),dict(learning_failure=None,learning_failure_reason='NOT_SELECTED_TARGET'))
        self.assertEqual(store.mock_calls,[])

class ClosedBoundaryTests(unittest.TestCase):
    def test_generated_child_namespace_binds_and_reads_exact_fixed_event_selector(self):
        def child_globals(module):
            tree=ast.parse(module.script().decode())
            stop=next(i for i,node in enumerate(tree.body)if isinstance(node,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='pending_failure'for t in node.targets))
            scope={};exec(compile(ast.Module(body=tree.body[:stop],type_ignores=[]),'<synthetic-child-preamble>','exec'),scope)
            return scope
        current=child_globals(D);original=child_globals(V1)
        self.assertNotIn('EVENT_SELECTOR',original)
        self.assertIs(type(current['EVENT_SELECTOR']),dict)
        self.assertEqual(current['EVENT_SELECTOR'],D.EVENT_SELECTOR)
        self.assertTrue(all(type(current['EVENT_SELECTOR'][k])is type(v)for k,v in D.EVENT_SELECTOR.items()))
        st,policy,payload,job,res,side=fixture();self.addCleanup(st._conn.close);job['actor']=res['actor']=100;save(st._conn,job,res,side)
        st._conn.execute('PRAGMA query_only=ON');st._conn.set_authorizer(D.readonly_authorizer);st._conn.execute('BEGIN');before=st._conn.total_changes
        class SelectorSpy(dict):
            def __getitem__(self,key):accesses.append(key);return super().__getitem__(key)
        accesses=[];current['EVENT_SELECTOR']=SelectorSpy(current['EVENT_SELECTOR'])
        try:
            self.assertIsNone(original['learning_failure_projection'](st,NOW,time.monotonic()+20,CID,PID,policy))
            resolved=current['learning_failure_resolution'](st,NOW,time.monotonic()+20,CID,PID,policy,authority_refusals=(SyntheticScopeRefusal,))
            self.assertEqual(resolved,dict(learning_failure=DETAIL,learning_failure_reason='OBSERVED'))
            self.assertEqual(accesses,['reserved_from','reserved_before']);self.assertEqual(st._conn.total_changes,before)
            current.pop('EVENT_SELECTOR')
            self.assertEqual(current['learning_failure_resolution'](st,NOW,time.monotonic()+20,CID,PID,policy),dict(learning_failure=None,learning_failure_reason='READ_INTERNAL_ERROR'))
        finally:st._conn.execute('ROLLBACK');st._conn.set_authorizer(None)
        source=D.script().decode()
        self.assertLess(source.index('EVENT_SELECTOR='),source.index('for relative,digest in CODE_PINS.items():'))
        self.assertLess(source.index('for relative,digest in CODE_PINS.items():'),source.index('    from app.naver_auto import org_snapshot as O,scope as SC'))
        self.assertLess(source.index('    from naver_engine import report_views as RV'),source.index('connection=connect_reader('))
    def test_v1_core_and_all_twelve_source_pins_preserved(self):
        self.assertEqual(hashlib.sha256(Path(V1.__file__).read_bytes()).hexdigest(),'a0e60b1f6cb5c3d8d24105e748bf101804f18ffc7c3b8d6198861648b3597a98')
        self.assertEqual(D.CODE_PINS,V1.CODE_PINS);self.assertEqual(len(D.CODE_PINS),12)
        for name in ('SOURCE','ARCHIVE','BASELINE','PREPARE_RUN','APPLY_OPERATION','PREVIOUS_SOURCE','P6_CONTROLLER_SHA256','NATIVE_RUN','CANONICAL_SHA256','EVENT_SELECTOR','TARGETS','TARGET_NAMESPACE','MAX_OUTPUT'):
            self.assertEqual(getattr(D,name),getattr(V1,name))
    def test_only_reason_field_is_added_to_setup_projection(self):
        value=result_fixture();D.validate_result(value)
        for row in value['targets'].values():row.pop('learning_failure_reason')
        value['projection_model']='799-setup-observation-v1';V1.validate_result(value)
    def test_reason_is_closed_and_cross_target_cannot_be_promoted(self):
        for label,reason in (('foodin','PRIVATE'),('foodin',None),('foodin',1),('foodin','NOT_SELECTED_TARGET'),('gomso','SIDECAR_MISSING')):
            value=result_fixture();value['targets'][label]['learning_failure_reason']=reason
            with self.subTest(label=label,reason=reason),self.assertRaises(ValueError):D.validate_result(value)
    def test_observed_iff_existing_five_field_detail_exists(self):
        value=result_fixture();value['targets']['foodin'].update(learning_failure=deepcopy(DETAIL),learning_failure_reason='OBSERVED');D.validate_result(value)
        for change in ({'learning_failure':None},{'learning_failure_reason':'SIDECAR_MISSING'},{'learning_failure':dict(DETAIL,raw='PRIVATE')}):
            bad=deepcopy(value);bad['targets']['foodin'].update(change)
            with self.subTest(change=list(change)),self.assertRaises(ValueError):D.validate_result(bad)
    def test_original_v1_function_ast_and_seven_sql_statements_are_preserved(self):
        old=ast.parse(V1.PROJECTION_SOURCE);new=ast.parse(D.PROJECTION_SOURCE)
        old_function=next(x for x in old.body if isinstance(x,ast.FunctionDef)and x.name=='learning_failure_projection')
        same_function=next(x for x in new.body if isinstance(x,ast.FunctionDef)and x.name=='learning_failure_projection')
        resolver=next(x for x in new.body if isinstance(x,ast.FunctionDef)and x.name=='learning_failure_resolution')
        self.assertEqual(ast.dump(old_function,include_attributes=False),ast.dump(same_function,include_attributes=False))
        sql=lambda tree:sorted(x.value for x in ast.walk(tree)if isinstance(x,ast.Constant)and type(x.value)is str and x.value.startswith('SELECT '))
        self.assertEqual(sql(old_function),sql(resolver));self.assertEqual(len(sql(resolver)),7)
    def test_sql_authorizer_and_actual_ro_connection_reject_mutation(self):
        with __import__('tempfile').TemporaryDirectory()as directory:
            path=(Path(directory)/'synthetic.db').resolve();c=sqlite3.connect(path);c.execute('CREATE TABLE invented(value TEXT)');c.commit();c.close()
            c=D.connect_reader(path)
            try:
                before=c.total_changes;c.execute('BEGIN')
                for sql in ('INSERT INTO invented VALUES(1)','DROP TABLE invented','ATTACH DATABASE ":memory:" AS extra','PRAGMA journal_mode=WAL'):
                    with self.subTest(sql=sql),self.assertRaises(sqlite3.DatabaseError):c.execute(sql)
                self.assertEqual(c.total_changes,before);c.execute('ROLLBACK')
            finally:c.close()
    def test_actual_child_contains_inline_resolver_and_real_typed_refusals(self):
        script=D.script().decode();ast.parse(script)
        self.assertIn('def learning_failure_resolution(',script)
        self.assertIn('from app.naver_auto import org_snapshot as O,scope as SC',script)
        self.assertIn('from naver_engine import report_views as RV',script)
        self.assertIn("authority_refusals=(S.StoreRefused,modules['SC'].ScopeError,modules['RV'].QueryInvalid,modules['RV'].SourceUnavailable)",script)
        self.assertLess(script.index('for relative,digest in CODE_PINS.items():'),script.index('connection=connect_reader('))
        for forbidden in ('store 2.py','HANDOVER.md','synchronize_management(','reserve_learning_call(','finish_learning_strategy_job(','generate_reports(','requests.','urllib.'):
            self.assertNotIn(forbidden,script)
    def test_unpopulated_event_refuses_before_host_or_io(self):
        package=dict(baseline=D.BASELINE,source_commit=D.SOURCE,source_tar_gz_sha256=D.ARCHIVE,mode=D.MODE,p6_controller_sha256=D.P6_CONTROLLER_SHA256,native_run_id=D.NATIVE_RUN,canonical_sha256=D.CANONICAL_SHA256,event_selector=D.EVENT_SELECTOR)
        host=Mock();release=Mock()
        with patch.object(D,'EVENT_SELECTOR',None),self.assertRaises(ValueError):D.run(package,host,release)
        self.assertEqual(host.mock_calls,[]);self.assertEqual(release.mock_calls,[])

if __name__=='__main__':unittest.main()
