"""Native Store, new memory databases and synthetic HTTP; pure decoding only."""
from datetime import timedelta
import json
from pathlib import Path
import runpy
import sqlite3
import sys
import unittest
from unittest.mock import patch

from naver_engine import store as S,inventory as I,handles as H

make_fixture=runpy.run_path(str(Path(__file__).resolve().parents[2]/'tools/naver-store-selection-benchmark.py'))['make_fixture']


class CatalogHeaderDecodeTests(unittest.TestCase):
    def setUp(self):
        if hasattr(S,'_ACCOUNT_CATALOG_HEADER_MEMO'):S._ACCOUNT_CATALOG_HEADER_MEMO=None
        self.fixture=make_fixture(accounts=4,managed=4,campaigns=0,history_days=0)
        self.store=self.fixture.store;self.now=self.fixture.clock.now()
        self.jobs=self.store.performance_work(self.now,24);self.job=self.jobs[0]
        self.addCleanup(self.store.close)
        self.raw=self.store.meta('account_catalog')

    def put(self,raw,key='account_catalog'):
        self.store._conn.execute('UPDATE naver_auto_meta SET value=? WHERE key=?',(raw,key))

    def outcome(self,header):
        try:
            body,state=I.catalog_status(self.store,self.now,header_only=True) if header else I.catalog_status(self.store,self.now)
            return ('result',state,body.get('generated_at') if type(body) is dict else body)
        except Exception as exc:return ('error',type(exc).__name__,str(exc))

    def test_repeated_validator_decodes_same_catalog_once_and_still_reads_sql_each_time(self):
        calls=[];sql=[];native=json.loads
        def decode(raw,*args,**kw):
            if raw==self.raw:calls.append(1)
            return native(raw,*args,**kw)
        self.store._conn.set_trace_callback(sql.append)
        with patch.object(S.json,'loads',side_effect=decode):
            for _ in range(5):self.assertTrue(self.store.performance_account_valid(self.job,self.now))
        self.assertEqual(len(calls),1)
        self.assertEqual(sum("key = 'account_catalog'" in q for q in sql),5)
        self.assertEqual(sum(q.lstrip().startswith('SELECT') for q in sql),40)

    def test_public_catalog_and_default_catalog_status_still_return_full_payload(self):
        self.assertEqual(self.store.account_catalog(),json.loads(self.raw))
        self.assertEqual(I.catalog_status(self.store,self.now)[0],json.loads(self.raw))
        header,state=I.catalog_status(self.store,self.now,header_only=True)
        self.assertEqual((header,state),({'generated_at':self.now.isoformat()},'accepted'))

    def test_latest_raw_read_changes_cache_even_when_generated_at_stays_same(self):
        first=self.store.account_catalog_header();old=S._ACCOUNT_CATALOG_HEADER_MEMO
        body=json.loads(self.raw);body['synthetic_extra']=True;raw=json.dumps(body)
        self.put(raw);self.assertEqual(self.store.account_catalog_header(),first)
        self.assertIsNot(S._ACCOUNT_CATALOG_HEADER_MEMO,old)
        self.assertEqual(S._ACCOUNT_CATALOG_HEADER_MEMO[0],raw)
        body['generated_at']=(self.now-timedelta(minutes=1)).isoformat();self.put(json.dumps(body))
        self.assertEqual(self.store.account_catalog_header()['generated_at'],body['generated_at'])

    def test_header_result_mutation_cannot_poison_cache(self):
        first=self.store.account_catalog_header();first['generated_at']='changed';first['items']=[]
        second=self.store.account_catalog_header()
        self.assertEqual(second,{'generated_at':self.now.isoformat()});self.assertIsNot(first,second)

    def test_missing_generated_at_and_failed_status_keep_original_error_order(self):
        self.put('{}')
        self.assertEqual(self.outcome(False),self.outcome(True))
        self.assertEqual(self.outcome(True)[1],'KeyError')
        self.put(json.dumps({'state':'failed'}),'account_catalog_status')
        self.assertEqual(self.outcome(False),self.outcome(True));self.assertEqual(self.outcome(True)[1],'failed')

    def test_nonobject_and_nonscalar_generated_values_preserve_outcomes(self):
        for value in (None,False,23,'text',[],{}, {'generated_at':None}, {'generated_at':17},
                      {'generated_at':[]},{'generated_at':{}},{'generated_at':'invalid'}):
            for state in ('accepted','failed'):
                with self.subTest(type=type(value).__name__,state=state):
                    self.put(json.dumps(value));self.put(json.dumps({'state':state}),'account_catalog_status')
                    self.assertEqual(self.outcome(False),self.outcome(True))

    def test_duplicate_generated_keys_keep_python_last_value(self):
        self.put('{"generated_at":"invalid","generated_at":'+json.dumps(self.now.isoformat())+'}')
        self.assertEqual(self.outcome(False),self.outcome(True));self.assertEqual(self.outcome(True)[1],'accepted')

    def test_malformed_json_error_is_not_cached_and_retries_decode(self):
        self.store.account_catalog_header();self.put('{malformed');native=json.loads;calls=[]
        def decode(raw,*args,**kw):
            if raw=='{malformed':calls.append(1)
            return native(raw,*args,**kw)
        with patch.object(S.json,'loads',side_effect=decode):
            for _ in range(2):
                with self.assertRaisesRegex(S.StoreError,'저장된 기준선'):self.store.account_catalog_header()
        self.assertEqual(len(calls),2);self.assertIsNone(S._ACCOUNT_CATALOG_HEADER_MEMO)
        self.put(self.raw);self.assertEqual(self.store.account_catalog_header()['generated_at'],self.now.isoformat())

    def test_nonstring_raw_blob_uses_native_decode_without_cache(self):
        self.put(self.raw.encode());self.assertEqual(self.store.account_catalog_header()['generated_at'],self.now.isoformat())
        self.assertIsNone(S._ACCOUNT_CATALOG_HEADER_MEMO)

    def test_native_account_catalog_instance_and_class_overrides_fall_back(self):
        expected={'generated_at':self.now.isoformat(),'override':True}
        self.store.account_catalog=lambda:dict(expected)
        self.assertEqual(self.store.account_catalog_header(),expected)
        self.assertEqual(I.catalog_status(self.store,self.now,header_only=True)[0],expected)
        del self.store.account_catalog
        with patch.object(S.Store,'account_catalog',lambda self:dict(expected)):
            self.assertEqual(self.store.account_catalog_header(),expected)

    def test_native_meta_json_and_get_meta_overrides_fall_back(self):
        expected={'generated_at':self.now.isoformat(),'override':True}
        self.store._meta_json=lambda c,key:dict(expected)
        self.assertEqual(self.store.account_catalog_header(),expected);del self.store._meta_json
        self.store._get_meta=lambda c,key:json.dumps(expected)
        self.assertEqual(self.store.account_catalog_header(),expected)

    def test_unknown_header_override_is_not_used_by_catalog_status(self):
        self.store.account_catalog_header=lambda:{'generated_at':'invalid'}
        self.assertEqual(I.catalog_status(self.store,self.now,header_only=True)[1],'accepted')

    def test_legacy_boundary_without_header_method_falls_back(self):
        class Legacy:
            def account_catalog(inner):return {'generated_at':self.now.isoformat(),'items':[1]}
            def account_catalog_status(inner):return {'state':'accepted'}
        self.assertEqual(I.catalog_status(Legacy(),self.now,header_only=True),I.catalog_status(Legacy(),self.now))

    def test_decoder_function_replacement_invalidates_memo(self):
        self.store.account_catalog_header();native=json.loads;at=(self.now-timedelta(minutes=1)).isoformat()
        def changed(raw,*args,**kw):
            body=native(raw,*args,**kw)
            if raw==self.raw:body['generated_at']=at
            return body
        with patch.object(S.json,'loads',side_effect=changed):self.assertEqual(self.store.account_catalog_header()['generated_at'],at)
        self.assertEqual(self.store.account_catalog_header()['generated_at'],self.now.isoformat())

    def test_bound_is_actual_python_string_size_single_entry_and_overflow_clears(self):
        self.assertEqual(S._ACCOUNT_CATALOG_HEADER_KEY_BYTES,16*1024*1024)
        self.store.account_catalog_header();self.assertLessEqual(sys.getsizeof(S._ACCOUNT_CATALOG_HEADER_MEMO[0]),S._ACCOUNT_CATALOG_HEADER_KEY_BYTES)
        body={'generated_at':self.now.isoformat(),'padding':'한'*150}
        raw=json.dumps(body,ensure_ascii=False);self.put(raw)
        self.assertGreater(sys.getsizeof(raw),len(raw))
        with patch.object(S,'_ACCOUNT_CATALOG_HEADER_KEY_BYTES',len(raw)):
            self.assertEqual(self.store.account_catalog_header()['generated_at'],self.now.isoformat())
            self.assertIsNone(S._ACCOUNT_CATALOG_HEADER_MEMO)
        self.put(self.raw);self.store.account_catalog_header()
        self.assertEqual(S._ACCOUNT_CATALOG_HEADER_MEMO[0],self.raw)

    def test_actual_16mib_overflow_decodes_without_retaining_key(self):
        self.store.account_catalog_header()
        raw=json.dumps({'generated_at':self.now.isoformat(),'padding':'x'*(16*1024*1024)})
        self.put(raw);native=json.loads;calls=[]
        def decode(text,*args,**kw):
            if text==raw:calls.append(1)
            return native(text,*args,**kw)
        with patch.object(S.json,'loads',side_effect=decode):
            for _ in range(2):self.assertEqual(self.store.account_catalog_header()['generated_at'],self.now.isoformat())
        self.assertEqual(len(calls),2);self.assertIsNone(S._ACCOUNT_CATALOG_HEADER_MEMO)

    def test_clock_freshness_is_recomputed_on_same_cached_raw(self):
        self.store.account_catalog_header()
        for at,state in ((self.now,'accepted'),(self.now+timedelta(hours=2,seconds=1),'stale'),
                         (self.now-timedelta(minutes=5,seconds=1),'stale')):
            self.assertEqual(I.catalog_status(self.store,at,header_only=True)[1],state)

    def test_warm_memo_still_reads_meta_sql_and_respects_db_authorizer(self):
        self.store.account_catalog_header()
        def deny(action,table,column,db,source):
            return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_READ and table=='naver_auto_meta' else sqlite3.SQLITE_OK
        self.store._conn.set_authorizer(deny)
        with self.assertRaises(sqlite3.DatabaseError):self.store.account_catalog_header()
        self.assertIsNone(S._ACCOUNT_CATALOG_HEADER_MEMO)

    def test_oversized_invalid_scalar_header_value_is_not_retained(self):
        value='x'*(S._ACCOUNT_CATALOG_HEADER_VALUE_BYTES+1)
        self.put(json.dumps({'generated_at':value}))
        self.assertEqual(self.store.account_catalog_header(),{'generated_at':value})
        self.assertIsNone(S._ACCOUNT_CATALOG_HEADER_MEMO)
        with self.assertRaises(ValueError):I.catalog_status(self.store,self.now,header_only=True)
        self.assertIsNone(S._ACCOUNT_CATALOG_HEADER_MEMO)

    def test_validator_rechecks_inventory_catalog_org_decision_and_stage_changes(self):
        changes=("UPDATE naver_auto_account SET present=0",
            "UPDATE naver_auto_meta SET value='{\"state\":\"failed\"}' WHERE key='account_catalog_status'",
            "UPDATE naver_auto_org SET body='{}'",
            "UPDATE naver_auto_link_decision SET revoked_at='2026-10-05T10:00:00+09:00'",
            "UPDATE naver_auto_management_state SET stage_revision='changed'")
        for sql in changes:
            with self.subTest(sql=sql):
                f=make_fixture(accounts=4,managed=4,campaigns=0);s=f.store;at=f.clock.now()
                try:
                    job=s.performance_work(at,24)[0];self.assertTrue(s.performance_account_valid(job,at))
                    s._conn.execute(sql);self.assertFalse(s.performance_account_valid(job,at))
                finally:s.close()
        self.assertFalse(self.store.performance_account_valid(self.job,self.now+timedelta(hours=3)))

    def test_each_fake_naver_request_revalidates_and_revocation_blocks_next_http(self):
        calls=[];native=self.store.performance_account_valid
        def validate(job,now):calls.append(1);return native(job,now)
        self.store.performance_account_valid=validate
        handle=H.issue_inventory_handle(customer_id=self.job['customer_id'],snapshot_at=self.job['snapshot_at'],now=self.now,
            validate=lambda cid,snapshot,at:self.store.performance_account_valid(self.job,at))
        self.assertEqual(self.fixture.reader.get_campaigns(handle),[])
        first_calls=len(self.fixture.http.calls);self.assertEqual(first_calls,1);self.assertGreaterEqual(len(calls),3)
        self.store._conn.execute("UPDATE naver_auto_management_state SET stage_revision='changed'")
        with self.assertRaises(H.NotEligible):self.fixture.reader.get_campaigns(handle)
        self.assertEqual(len(self.fixture.http.calls),first_calls)


if __name__=='__main__':unittest.main()
