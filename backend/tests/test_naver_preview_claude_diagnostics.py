import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import naver_preview_claude_diagnostics as D


class ClaudeDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.path=Path(self.folder.name).resolve()/'test.sqlite'
        c=sqlite3.connect(self.path)
        c.executescript('CREATE TABLE naver_auto_meta(key TEXT PRIMARY KEY,value TEXT);'
            'CREATE TABLE naver_auto_access_log(log_id INTEGER PRIMARY KEY,emp_idx INTEGER,action TEXT,result TEXT);'
            'CREATE TABLE naver_auto_account(customer_id INTEGER,ad_account_no INTEGER,present INTEGER);'
            'CREATE TABLE naver_auto_report_snapshot(report_id INTEGER,possibility_id INTEGER,period_key TEXT,revision_fingerprint TEXT,generated_at TEXT,status TEXT,review_status TEXT);')
        c.execute('INSERT INTO naver_auto_account VALUES(?,?,1)',(42,D.TARGET_ACCOUNT))
        c.execute('INSERT INTO naver_auto_report_snapshot VALUES(1,?,?,?,?,?,?)',
            (D.TARGET_PID,D.PERIOD,'a'*64,'2026-10-11T05:00:00+00:00','ready','held'))
        c.commit();c.close()
        self.now=datetime(2026,10,11,6,tzinfo=timezone.utc)

    def tearDown(self):
        self.folder.cleanup()

    def collect(self):
        c=D.connect_reader(self.path)
        try:return D.collect_metadata(c,self.now)
        finally:c.close()

    def add_meta(self,key,value):
        c=sqlite3.connect(self.path);c.execute('INSERT INTO naver_auto_meta VALUES(?,?)',(key,value));c.commit();c.close()

    def test_no_reservation_no_draft_and_readonly(self):
        before=self.path.read_bytes()
        value,identity=self.collect()
        self.assertEqual(value['reservations']['count'],0)
        self.assertEqual(value['target_strategy']['version'],0)
        self.assertEqual(value['target_strategy']['state'],'empty')
        self.assertEqual(identity[0],1)
        self.assertEqual(before,self.path.read_bytes())

    def test_reservation_not_payment_or_account_attribution(self):
        self.add_meta('learning-call:'+'b'*32,json.dumps(dict(actor=987654,at='2026-10-11T14:30:00+09:00',
            reserved_microusd=31700,proof_hash='SENSITIVE-PROOF-MUST-NOT-LEAVE')))
        self.add_meta('learning-budget:2026-10','31700')
        value,_=self.collect()
        self.assertEqual(value['reservations']['count'],1)
        self.assertEqual(value['reservations']['total_reserved_microusd'],31700)
        self.assertIs(value['reservations']['actual_billed_amount'],False)
        self.assertEqual(value['reservations']['scope'],'instance_total_not_account_attributed')
        text=json.dumps(value)
        for private in ('987654','SENSITIVE-PROOF','b'*32):self.assertNotIn(private,text)

    def test_malformed_reservation_fails_closed_without_raw_output(self):
        self.add_meta('learning-call:'+'b'*32,'private-invalid-json')
        with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_RESERVATION_METADATA$'):self.collect()

    def test_strategy_only_scalar_metadata(self):
        import hashlib
        key='report-strategy-head:1:'+hashlib.sha256(b'42').hexdigest()
        self.add_meta(key,json.dumps(dict(version=1,state='draft',source='claude',
            author={'actor':987654,'at':'2026-10-11T05:45:00+00:00'},document={'diagnosis':'PRIVATE-DRAFT-TEXT'})))
        value,_=self.collect()
        self.assertEqual(value['target_strategy']['version'],1)
        self.assertEqual(value['target_strategy']['source'],'claude')
        self.assertNotIn('PRIVATE-DRAFT',json.dumps(value));self.assertNotIn('987654',json.dumps(value))

    def test_ambiguous_target_refused(self):
        c=sqlite3.connect(self.path);c.execute('INSERT INTO naver_auto_account VALUES(43,?,1)',(D.TARGET_ACCOUNT,));c.commit();c.close()
        with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_TARGET_ACCOUNT$'):self.collect()

    def test_sqlite_write_attach_and_extension_refused(self):
        c=D.connect_reader(self.path)
        try:
            for query in ("DELETE FROM naver_auto_meta","PRAGMA query_only=OFF","ATTACH DATABASE ':memory:' AS another","SELECT load_extension('private')"):
                with self.subTest(query=query),self.assertRaises(sqlite3.DatabaseError):c.execute(query)
            self.assertEqual(c.total_changes,0)
        finally:c.close()

    def test_exact_package_and_no_credentials_before_rejection(self):
        package=dict(baseline=D.BASELINE,source_commit=D.SOURCE,source_tar_gz_sha256=D.ARCHIVE,
                     target='foodin-weekly-20260928',mode='metadata-and-synthetic-only')
        D.validate_package(package)
        for replacement in ({**package,'mode':'generate'}, {**package,'api_key':'PRIVATE'}, {**package,'source_commit':'a'*40}):
            with patch.object(D.os,'geteuid',side_effect=AssertionError('too early')):
                with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_PACKAGE_PIN$'):D.run(replacement,None,None,None)

    def test_script_clears_env_forces_stub_and_blocks_network(self):
        body=D.script().decode();compile(body,'<synthetic-diagnostic>','exec')
        for forbidden in ('provider_from_environment(',"get('ANTHROPIC_API_KEY')","get('CLAUDE_API_KEY')",'record_learning_strategy(', 'reserve_learning_call('):
            self.assertNotIn(forbidden,body)
        for required in ('os.environ.clear()','transport=stub','socket.socket.connect=no_network','http.client.HTTPSConnection.request=no_network',"writer=False",'PRAGMA query_only=ON','?mode=ro'):
            self.assertIn(required,body)

    def test_safe_log_projection_emits_fixed_counts(self):
        class Logs:
            @staticmethod
            def recent_runtime_logs(engine,relay):
                return {'sources':[{'source':'docker','unit':'relay','available':True,'entries_inspected':2,
                    'templates':{'unmatched_entries':1,'categories':{'relay_failed':{'count':1,'kinds':{'engine-timeout':1,'PRIVATE':10}}}}}]}
        value=D.log_summary(Logs,'a'*64,'b'*64)
        self.assertEqual(value['relay']['engine_timeout'],1)
        self.assertNotIn('PRIVATE',json.dumps(value))
        self.assertIs(value['engine']['available'],False)

    def test_output_allowlist_rejects_raw_extra(self):
        value,_=self.collect()
        value['synthetic_preflight']=dict(status='refused',code='PROVIDER_MODEL_UNAVAILABLE',request_serialized=False,
            request_bytes=0,synthetic_transport_calls=0,learning_cases=1,conversion_complete=False,external_calls=0,draft_mutations=0)
        D.validate_result(value)
        value['raw_response']='PRIVATE'
        with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_OUTPUT_FIELDS$'):D.validate_result(value)

    def test_missing_model_stops_before_provider_transport(self):
        from types import SimpleNamespace
        prepared=dict(payload={},learning_context={},plan_context={})
        reader=SimpleNamespace(prepare_learning_strategy=lambda *args:prepared)
        class Refused(Exception):pass
        strategy=SimpleNamespace(StrategyRefused=Refused,build_context=lambda *args,**kwargs:{'learning':{'cases':[{}]},'quality':{'conversion':{'complete':False}}})
        engine=SimpleNamespace(marketing_strategy=strategy,store=SimpleNamespace())
        provider=SimpleNamespace(AnthropicProvider=lambda *args,**kwargs:self.fail('provider must not be instantiated'))
        with patch.dict(sys.modules,{'naver_engine':engine,'naver_runtime.claude_provider':provider}):
            value=D.synthetic_preflight(reader,(1,'a'*64,'b'*64,0,5),self.now,None)
        self.assertEqual(value['code'],'PROVIDER_MODEL_UNAVAILABLE')
        self.assertEqual(value['synthetic_transport_calls'],0)

    def test_unavailable_actor_is_not_context_failure(self):
        from types import SimpleNamespace
        engine=SimpleNamespace(marketing_strategy=SimpleNamespace(StrategyRefused=ValueError),store=SimpleNamespace())
        provider=SimpleNamespace(AnthropicProvider=lambda *args,**kwargs:self.fail('provider must not be instantiated'))
        with patch.dict(sys.modules,{'naver_engine':engine,'naver_runtime.claude_provider':provider}):
            value=D.synthetic_preflight(None,(1,'a'*64,'b'*64,0,None),self.now,'model')
        self.assertEqual(value['status'],'not_performed')
        self.assertEqual(value['code'],'ACTOR_UNAVAILABLE')

    def test_latest_reserve_actor_stays_internal(self):
        c=sqlite3.connect(self.path)
        c.execute("INSERT INTO naver_auto_access_log VALUES(1,987654,'learning-ai-reserve','ok')");c.commit();c.close()
        value,identity=self.collect()
        self.assertEqual(identity[-1],987654)
        self.assertNotIn('987654',json.dumps(value))


if __name__=='__main__':unittest.main()
