"""인증된 읽기 전용 상세점검 완료 진단. 합성 저장소/WSGI만 사용한다."""
import unittest
import json
import sqlite3
import pathlib
import subprocess
import shutil
from datetime import timedelta
from unittest.mock import patch

from naver_engine.tests import test_accounts_match_reuse as TM
from naver_engine import store as S, management_store as MS, web as WEB
from naver_engine import collection_diagnostics as CD


class DetailedCollectionStatusTest(unittest.TestCase):
    def setUp(self):
        self.fixture = TM.AccountsMatchReuseTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store, self.clock = self.fixture.store, self.fixture.clock

    def test_current_daily_missing_account_days_cannot_be_reported_complete(self):
        status, body = self.fixture.call('/health?collection=1')
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {'collection'})
        value = body['collection']
        self.assertTrue(value['ready'])
        self.assertEqual(value['targets'], 2)
        self.assertEqual(value['counts']['pending'], 2)
        self.assertEqual(value['counts']['recorded'], 0)
        self.assertFalse(value['ledger_complete'])

    def seed(self, status='ok', *, missing=(), wrong_pid=False):
        now = self.clock.now()
        policies = MS.snapshot(self.store, now)
        daily = [(cid, row) for cid, row in policies.items() if row['decision'].cadence == 'daily']
        rid = self.store.begin_run(now.date(), now)
        for cid, row in daily:
            self.store.record_account_day(rid, cid, status=status, rules_run=(), rules_not_run=missing,
                checked_at=now, possibility_id=999 if wrong_pid else row['possibility_id'], link='confirmed')
        self.store.finish_run(rid, S.RUN_DONE, now, accounts_total=len(daily), accounts_ok=len(daily) if status=='ok' else 0)
        return daily

    def get(self):
        status, body = self.fixture.call('/health?collection=1')
        self.assertEqual(status, 200)
        return body['collection']

    def test_all_current_account_days_ok_and_no_missing_rules_are_complete(self):
        self.seed()
        value = self.get()
        self.assertEqual((value['targets'], value['counts']['ok'], value['counts']['recorded']), (2,2,2))
        self.assertTrue(value['ledger_complete'])
        self.assertEqual(value['scope'], 'current_daily_accounts')

    def test_recorded_partial_data_late_or_key_rejected_is_not_ledger_complete(self):
        for status in ('partial','data_late','key_rejected','system_gap','not_eligible'):
            with self.subTest(status=status):
                self.seed(status)
                value = self.get()
                self.assertEqual(value['counts']['recorded'], 2)
                self.assertEqual(value['counts'][status], 2)
                self.assertFalse(value['ledger_complete'])

    def test_ok_with_unexecuted_rules_is_recorded_but_not_complete(self):
        self.seed(missing=(('bizmoney', 'stats-unread'),))
        value = self.get()
        self.assertEqual((value['counts']['ok'], value['counts']['rules_not_run']), (2,2))
        self.assertFalse(value['ledger_complete'])

    def test_foreign_pid_is_pending_and_never_current_completion(self):
        self.seed(wrong_pid=True)
        value = self.get()
        self.assertEqual((value['counts']['pending'], value['counts']['pid_mismatch']), (2,2))
        self.assertEqual(value['counts']['recorded'], 0)
        self.assertFalse(value['ledger_complete'])

    def test_prior_day_results_are_not_current_completion(self):
        self.seed()
        self.store._conn.execute('UPDATE naver_auto_account_day SET day=?',
                                 ((self.clock.now().date()-timedelta(days=1)).isoformat(),))
        value = self.get()
        self.assertEqual((value['counts']['pending'], value['counts']['recorded']), (2,0))
        self.assertFalse(value['ledger_complete'])

    def test_authority_denial_happens_before_diagnostic_read_without_writes(self):
        with patch.object(S.Store, 'detailed_collection_status', side_effect=AssertionError('forbidden read')):
            for actor, narrowed in ((100,False),(101,False),(0,True)):
                with self.subTest(actor=actor, narrowed=narrowed):
                    self.assertEqual(self.fixture.call('/health?collection=1', actor, narrowed=narrowed)[0],403)
            self.fixture.app._verified_linking = False
            self.assertEqual(self.fixture.call('/health?collection=1')[0],403)

    def test_exact_query_and_default_health_and_runtime_poll_are_preserved(self):
        with patch.object(S.Store, 'detailed_collection_status', side_effect=AssertionError('opt-in only')):
            for query in ('collection=0','collection=1&runtime=1','collection=1&selection=all'):
                self.assertEqual(self.fixture.call('/health?'+query)[0],400)
            with patch.object(WEB.W, 'health', return_value={'ok':True,'runs':[]}):
                self.assertEqual(self.fixture.call('/health')[1]['runs'],[])
            self.assertEqual(set(self.fixture.call('/health?runtime=1')[1]), {'runtime'})

    def test_stale_org_refuses_before_diagnostic_read(self):
        self.clock.advance(27*60*60)
        with patch.object(S.Store, 'detailed_collection_status', side_effect=AssertionError('stale read')):
            self.assertEqual(self.fixture.call('/health?collection=1'), (409,{'error':'org-stale'}))

    def test_failed_catalog_is_unavailable_not_vacuously_complete(self):
        self.seed()
        self.store.record_account_catalog_failure(self.clock.now(),'CATALOG_FAILED')
        value = self.get()
        self.assertFalse(value['ready'])
        self.assertIsNone(value['targets'])
        self.assertFalse(value['ledger_complete'])

    def test_valid_and_wrong_binding_checkpoint_states_are_counted_without_bodies(self):
        daily = self.seed()
        for index, (cid, row) in enumerate(daily):
            saved = self.store.begin_morning_progress(cid,row['possibility_id'],self.clock.now().date(),
                                                       'a'*64,self.clock.now())
            if index:
                self.store.finish_morning_progress(cid,saved['generation'],self.clock.now(),blocked=True)
        value = self.get()
        self.assertEqual(value['checkpoints'], {'reading':1,'blocked':1,'binding_mismatch':0})
        self.assertFalse(value['ledger_complete'])
        self.store._conn.execute("UPDATE naver_auto_morning_progress SET binding='invalid' WHERE status='reading'")
        value = self.get()
        self.assertEqual(value['checkpoints'], {'reading':0,'blocked':1,'binding_mismatch':1})
        self.assertFalse(value['ledger_complete'])

    def test_stale_checkpoint_is_separate_from_current_remaining_work(self):
        daily = self.seed()
        cid, row = daily[0]
        self.store.begin_morning_progress(cid,row['possibility_id'],self.clock.now().date(),'a'*64,self.clock.now())
        self.store._conn.execute('UPDATE naver_auto_morning_progress SET day=?',
            ((self.clock.now().date()-timedelta(days=1)).isoformat(),))
        value = self.get()
        self.assertEqual(value['checkpoints'], {'reading':0,'blocked':0,'binding_mismatch':1})
        self.assertTrue(value['ledger_complete'])

    def test_unreadable_or_oversized_rules_are_bounded_and_never_reported_complete(self):
        self.seed()
        for raw in ('PRIVATE_DIAGNOSTIC_MARK', '{"private":1}', 'null', '['*2000+']'*2000,
                    '[['+json.dumps('PRIVATE_DIAGNOSTIC_MARK'+'x'*1000000)+',"error"]]'):
            with self.subTest(length=len(raw)):
                self.store._conn.execute('UPDATE naver_auto_account_day SET rules_not_run=?',(raw,))
                value = self.get()
                self.assertEqual(value['counts']['unreadable'],2)
                self.assertFalse(value['ledger_complete'])
                encoded = json.dumps(value)
                self.assertLess(len(encoded),2000)
                self.assertNotIn('PRIVATE_DIAGNOSTIC_MARK',encoded)

    def test_manual_ui_has_one_get_and_blocks_duplicate_and_scoped_requests(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, '기존 UI 검증용 Node 필요')
        source = pathlib.Path(__file__).resolve().parents[2]/'backend/naver_page/app.js'
        script = r'''
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const code=fs.readFileSync(process.argv[1],'utf8');
const fn=code.slice(code.indexOf('  function loadCollectionDiagnostics('),code.indexOf('  function setSpane('));
let resolve, requests=[], allowed=true;
const ctx={state:{gen:1,busy:{}},fullCollectionAllowed:()=>allowed,num:x=>typeof x==='number'?String(x):'—',
errText:()=> '안전한 오류',api:(method,path)=>{requests.push([method,path]);return new Promise(r=>resolve=r);}};
vm.createContext(ctx);vm.runInContext(fn,ctx);
(async()=>{
 const button={disabled:false},output={textContent:''};
 assert.strictEqual(requests.length,0);
 ctx.loadCollectionDiagnostics(button,output);ctx.loadCollectionDiagnostics(button,output);
 assert.deepStrictEqual(requests,[['GET','/health?collection=1']]);assert.strictEqual(button.disabled,true);
 resolve({collection:{ready:true,day:'2026-10-09',targets:2,counts:{recorded:2,ok:1,partial:1},checkpoints:{},ledger_complete:false}});
 await Promise.resolve();await Promise.resolve();
 assert.strictEqual(button.disabled,false);assert.ok(output.textContent.includes('미완결'));
 assert.ok(output.textContent.includes('원천 재대조를 보증하지 않습니다'));
 allowed=false;ctx.loadCollectionDiagnostics(button,output);assert.strictEqual(requests.length,1);
 allowed=true;ctx.loadCollectionDiagnostics(button,output);ctx.state.gen++;
 const saved=output.textContent;resolve({collection:{ready:true,ledger_complete:true}});
 await Promise.resolve();await Promise.resolve();assert.strictEqual(output.textContent,saved);
 console.log('manual diagnostics UI PASS');
})().catch(error=>{console.error(error);process.exitCode=1});
'''
        result = subprocess.run([node,'-e',script,str(source)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'manual diagnostics UI PASS')

    def test_only_one_policy_snapshot_and_no_financial_or_chunk_reads(self):
        self.seed()
        original = self.fixture.app._open_read
        tables, closes = [], []
        def open_read():
            reader = original()
            def authorize(operation, table, column, database, trigger):
                if operation == sqlite3.SQLITE_READ:
                    tables.append((table,column))
                    if table == 'naver_auto_morning_chunk' or (table == 'naver_auto_account_day' and column not in
                            {'customer_id','possibility_id','status','rules_not_run','day'}):
                        return sqlite3.SQLITE_DENY
                if operation in (sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            reader._conn.set_authorizer(authorize)
            close = reader.close
            def closed():
                closes.append(1)
                return close()
            reader.close = closed
            return reader
        with patch.object(self.fixture.app, '_open_read', side_effect=open_read), \
                patch.object(MS, 'snapshot', wraps=MS.snapshot) as snapshot:
            value = self.get()
        self.assertEqual(snapshot.call_count,1)
        self.assertTrue(value['ledger_complete'])
        self.assertEqual(closes,[1])
        self.assertFalse(any(table=='naver_auto_morning_chunk' for table,column in tables))
        self.assertEqual(set(value), {'scope','day','checked_at','ready','targets','counts','checkpoints','ledger_complete'})
        self.assertTrue(all(type(count) is int and count>=0 for count in value['counts'].values()))
        self.assertTrue(all(type(count) is int and count>=0 for count in value['checkpoints'].values()))
        raw = json.dumps(value)
        self.assertNotIn('customer_id',raw)
        self.assertNotIn('possibility_id',raw)
        self.assertNotIn('bizmoney',raw)

    def test_optional_writer_ram_projection_is_closed_and_authorized_only(self):
        value = {key: 0 for key in CD.WRITER_KEYS}
        calls = []
        def getter():
            calls.append(1)
            return {**value, 'queue_depth':2, 'active_phase':29, 'busy_duration_ms':120}
        self.fixture.app._writer_diagnostics = getter
        status, body = self.fixture.call('/health?collection=1')
        self.assertEqual(status,200)
        self.assertEqual(body['writer'], {'available':True, **value,'queue_depth':2,'active_phase':29,'busy_duration_ms':120})
        self.assertEqual(calls,[1])
        self.fixture.call('/health?runtime=1')
        self.fixture.call('/health?collection=1',100)
        self.fixture.call('/health?collection=1',0,narrowed=True)
        self.assertEqual(calls,[1])
        for invalid in ({**value,'error':'private'}, {**value,'extra':'private'},
                        {**value,'active_phase':105}, {**value,'queue_depth':True}, {'queue_depth':0}):
            self.fixture.app._writer_diagnostics = lambda: invalid
            self.assertEqual(self.fixture.call('/health?collection=1')[1]['writer'], {'available':False})
        def failing():
            raise RuntimeError('private')
        self.fixture.app._writer_diagnostics = failing
        self.assertEqual(self.fixture.call('/health?collection=1')[1]['writer'], {'available':False})


if __name__ == '__main__':
    unittest.main()
