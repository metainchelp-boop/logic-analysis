"""현재 요약에 없는 성공만 읽는다. 합성 Store/실제 WSGI 전체 응답을 대조한다."""
from datetime import timedelta
import sqlite3
import unittest
from unittest.mock import patch

from naver_engine import management as P, management_store as MS, store as S, web as WEB
from naver_engine.tests import test_accounts_match_reuse as TM, test_account_catalog as TC


class InventoryLegacyLoadingTest(unittest.TestCase):
    def setUp(self):
        self.fixture = TM.AccountsMatchReuseTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store, self.clock = self.fixture.store, self.fixture.clock
        self.native = S.ManagedStorage.latest_inventory_successes
        self.now = self.clock.now()
        self.store.synchronize_management(self.now)
        self.policies = MS.snapshot(self.store, self.now)
        self.cids = list(self.policies)
        for cid in self.cids:
            self.job(cid)
            self.inventory(cid, self.now.date()-timedelta(days=2), "ok", balance=None, spend=0)

    def job(self, cid, *, status="ok", pid="current"):
        owner = self.policies[cid]
        kind = owner["decision"].cadence
        if kind == "blocked":
            kind = "weekly"
        period = P.period_for(kind, self.now)
        stamp = self.now.isoformat()
        current_pid = owner["possibility_id"] if pid == "current" else pid
        self.store._conn.execute("""INSERT OR REPLACE INTO naver_auto_performance_job
            (job_key,customer_id,kind,cycle_day,period_start,period_end,snapshot_at,catalog_at,
             stage_revision,possibility_id,matching_fingerprint,status,checked_at,next_try_at,attempts,generation)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)""", ("synthetic:"+str(cid),cid,kind,
            str(period.cycle_day),str(period.since),str(period.until),stamp,stamp,
            owner["stage_revision"] or "synthetic-weekly",current_pid,"synthetic",status,stamp,stamp,stamp))

    def inventory(self, cid, day, status, *, balance=None, spend=0):
        at = self.now.isoformat()
        self.store._conn.execute("""INSERT OR REPLACE INTO naver_auto_inventory_check
            (customer_id,day,snapshot_at,status,checked_at,bizmoney,yday_spend,yday_imp,yday_clk,next_try_at,
             campaigns_json,progress_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid,str(day),at,status,at,balance,spend,0,0,at,"unused","unused"))

    def request(self, path, actor=0, narrowed=False):
        return self.fixture.call(path, actor, narrowed=narrowed)

    def reference(self, path, actor=0, narrowed=False):
        native = self.native
        def legacy(self):
            return native(self)
        with patch.object(S.ManagedStorage, "latest_inventory_successes", legacy):
            return self.request(path, actor, narrowed)

    def legacy_queries(self, path):
        statements = []
        original = self.fixture.app._open_read
        def reader():
            result = original()
            result._conn.set_trace_callback(statements.append)
            return result
        with patch.object(self.fixture.app, "_open_read", reader):
            result = self.request(path)
        reads = [q for q in statements if "naver_auto_inventory_check" in q and
                 ("MAX(p.day)" in q or "WITH wanted(customer_id)" in q)]
        return result, reads

    def parity(self):
        for actor, selection, narrowed in ((0,"all",False),(0,"person:100",False),
                (0,"unassigned",False),(100,"all",False),(101,"all",False),(0,"all",True)):
            for endpoint in ("accounts", "dashboard"):
                path = "/"+endpoint+"?selection="+selection
                with self.subTest(actor=actor, endpoint=endpoint, selection=selection, narrowed=narrowed):
                    self.assertEqual(self.request(path, actor, narrowed), self.reference(path, actor, narrowed))

    def test_complete_native_get_does_not_scan_legacy_history(self):
        for path in ("/accounts", "/dashboard", "/dashboard?view_sync=1"):
            body, reads = self.legacy_queries(path)
            self.assertEqual(body[0], 200, body)
            self.assertEqual(reads, [], "현재 성공이 있는 계정에 과거 성공 전체 조회가 남아 있습니다")
        self.parity()

    def test_missing_and_current_failure_restore_only_needed_old_success(self):
        cid = self.cids[0]
        self.job(cid, status="retry")
        self.inventory(cid, self.now.date()-timedelta(days=1), "retry")
        result, reads = self.legacy_queries("/accounts")
        self.assertEqual(result[0],200,result)
        self.assertEqual(len(reads),1)
        self.assertIn("WITH wanted(customer_id)",reads[0])
        self.assertIn("VALUES ("+str(cid)+")",reads[0])
        self.assertNotIn(str(self.cids[1]),reads[0])
        row = next(r for r in result[1]["rows"] if r["customer_tail"]==str(cid)[-4:])
        self.assertTrue(row["collection"]["stale"])
        self.assertEqual(row["collection"]["spend"],0)
        self.assertIsNone(row["collection"]["bizmoney"])
        self.parity()

    def test_no_success_remains_unknown_and_attribution_change_does_not_restore_old(self):
        cid=self.cids[0]
        self.job(cid,status="retry")
        self.store._conn.execute("DELETE FROM naver_auto_inventory_check WHERE customer_id=?",(cid,))
        self.parity()
        self.inventory(cid,self.now.date()-timedelta(days=2),"ok",balance=25,spend=9)
        with patch.object(S.ManagedStorage,"attribution_changes",return_value={cid:True}):
            result,reads=self.legacy_queries("/accounts")
            self.assertEqual(reads,[])
            row=next(r for r in result[1]["rows"] if r["customer_tail"]==str(cid)[-4:])
            self.assertIsNone(row["collection"]["last_success_at"])
            self.assertIsNone(row["collection"]["spend"])
            self.parity()

    def test_foreign_pid_failed_snapshot_expired_holding_and_hidden_keep_whole_outputs(self):
        self.job(self.cids[0],pid=99999)
        self.parity()
        catalog=self.store.account_catalog()
        items=[{**r,"stage":"계약만료" if r["possibility_id"]==11 else "홀딩중"} for r in catalog["items"]]
        self.store.record_account_catalog({"generated_at":self.now.isoformat(),"total":len(items),
            "complete":True,"items":items},self.fixture.ids,self.now)
        self.parity()
        items=[{**r,"stage_hidden":True} if r["possibility_id"]==11 else r for r in items]
        self.store.record_account_catalog({"generated_at":self.now.isoformat(),"total":len(items),
            "complete":True,"items":items},self.fixture.ids,self.now)
        self.parity()
        self.clock.advance(31*3600)
        self.parity()

    def test_view_cursor_is_unchanged_across_old_and_native_subset_paths(self):
        self.job(self.cids[0],status="retry")
        for endpoint in ("accounts","dashboard"):
            path="/"+endpoint+"?view_sync=1"
            old=self.reference(path)[1]
            self.assertEqual(old["mode"],"full")
            new=self.request(path+"&view_cursor="+old["cursor"])[1]
            self.assertEqual(new["mode"],"unchanged")
            self.assertEqual(new["cursor"],old["cursor"])
            self.assertEqual(new["base_cursor"],old["cursor"])
            self.assertIsNone(new["data"])
            self.assertEqual(new["_request_timing"]["store_latest_inventory_successes_calls"],1.0)

    def test_instance_and_class_override_receive_original_no_arg_call(self):
        native=self.native
        calls=[]
        def custom(self):
            calls.append("override")
            return native(self)
        with patch.object(S.ManagedStorage,"latest_inventory_successes",custom):
            for path in ("/accounts","/dashboard?view_sync=1"):
                self.assertEqual(self.request(path)[0],200)
        self.assertEqual(calls,["override","override"])
        store=self.store
        class Reader:
            def __getattr__(self,name):
                return getattr(store,name)
        reader=Reader()
        reader.latest_inventory_successes=lambda: native(store)
        from naver_engine import inventory as I, views as W
        from app.naver_auto import scope as SC
        ctx=W.load_inventory(reader,self.now)
        expected=I.board(ctx,store,SC.scope_of(ctx.org,0))
        self.assertEqual(I.board(ctx,reader,SC.scope_of(ctx.org,0)),expected)

    def test_default_public_getter_stays_whole_and_subset_uses_exact_pk_latest_day(self):
        cid=self.cids[0]
        day=self.now.date()-timedelta(days=3)
        self.inventory(cid,day,"ok",balance=12,spend=8)
        # checked_at의 최신값 대신 성공 day의 최댓값을 선택하는 기존 계약을 보존한다.
        self.store._conn.execute("UPDATE naver_auto_inventory_check SET checked_at=? WHERE customer_id=? AND day=?",
            ((self.now+timedelta(days=1)).isoformat(),cid,str(day)))
        whole=self.store.latest_inventory_successes()
        self.assertEqual(len(whole),len(self.cids))
        self.assertEqual(self.store.latest_inventory_successes(_customer_ids=[cid,cid]),{cid:whole[cid]})
        self.assertEqual(self.store.latest_inventory_successes(_customer_ids=[]),{})
        self.assertEqual(self.store.latest_inventory_successes(_customer_ids=[999999999]),{})
        for invalid in ([True],[0],[-1],["1"]):
            with self.subTest(invalid=invalid),self.assertRaises(S.StoreRefused):
                self.store.latest_inventory_successes(_customer_ids=invalid)

    def test_subset_chunks_max_400_and_never_reads_payload(self):
        statements=[]
        self.store._conn.set_trace_callback(statements.append)
        base=S._authorizer(S.PHASE_READ)
        denied=[]
        def guard(action,table,column,db,source):
            if action==sqlite3.SQLITE_READ and table=="naver_auto_inventory_check" and column in ("campaigns_json","progress_json","progress_hash"):
                denied.append(column)
                return sqlite3.SQLITE_DENY
            return base(action,table,column,db,source)
        self.store._conn.set_authorizer(guard)
        ids=list(range(1,802))+self.cids
        result=self.store.latest_inventory_successes(_customer_ids=ids)
        self.assertEqual(result,self.native(self.store))
        queries=[q for q in statements if "WITH wanted(customer_id)" in q]
        self.assertEqual(len(queries),3)
        counts=[q.partition("VALUES ")[2].partition(") SELECT")[0].count("),(")+1 for q in queries]
        self.assertEqual(counts,[400,400,7])
        self.assertEqual(denied,[])

    def test_timed_reader_preserves_original_method_identity_and_result_exception(self):
        times={}
        wrapper=WEB._TimedReadStore(self.store,times)
        original=self.store.latest_inventory_successes
        self.assertIs(wrapper.latest_inventory_successes.__func__,original.__func__)
        self.assertEqual(wrapper.latest_inventory_successes(_customer_ids=[self.cids[0]]),
                         original(_customer_ids=[self.cids[0]]))
        with patch.object(WEB._time,"perf_counter",side_effect=RuntimeError("synthetic clock")):
            self.assertEqual(wrapper.latest_inventory_successes(_customer_ids=[]),{})
            with self.assertRaises(S.StoreRefused):
                wrapper.latest_inventory_successes(_customer_ids=[True])
        with self.assertRaises(AttributeError):
            wrapper._conn

    def test_non_store_receiver_and_wrong_function_identity_keep_no_arg_fallback(self):
        store,native=self.store,self.native
        calls=[]
        class Adapter:
            def __getattr__(self,name):
                return getattr(store,name)
            def latest_inventory_successes(self):
                calls.append(self)
                return native(store)
        adapter=Adapter()
        wrapped=WEB._TimedReadStore(adapter,{})
        self.assertIs(wrapped.latest_inventory_successes.__func__,Adapter.latest_inventory_successes)
        from naver_engine import inventory as I, views as W
        from app.naver_auto import scope as SC
        ctx=W.load_inventory(adapter,self.now)
        expected=I.board(ctx,store,SC.scope_of(ctx.org,0),_dashboard_only=True)
        actual=I.board(ctx,wrapped,SC.scope_of(ctx.org,0),_dashboard_only=True)
        self.assertEqual(actual,expected)
        self.assertEqual(calls,[adapter])
        # 함수가 잘못된 identity를 제공하더라도 native 인자를 강요하지 않는다.
        def custom():
            calls.append("wrong-func")
            return native(store)
        custom.__func__=object()
        adapter.latest_inventory_successes=custom
        self.assertEqual(I.board(ctx,wrapped,SC.scope_of(ctx.org,0),_dashboard_only=True),expected)
        self.assertEqual(calls[-1],"wrong-func")

    def test_callable_identity_property_failure_preserves_original_bound_result(self):
        calls=[]
        class Callable:
            @property
            def __func__(self):
                raise RuntimeError("합성 metadata 오류")
            def __call__(self):
                calls.append("bound-call")
                return {"synthetic":True}
        class Adapter:
            latest_inventory_successes=Callable()
        wrapped=WEB._TimedReadStore(Adapter(),{})
        self.assertEqual(wrapped.latest_inventory_successes(),{"synthetic":True})
        self.assertEqual(calls,["bound-call"])

    def test_all_missing_uses_original_whole_query_without_pk_repeat(self):
        for cid in self.cids:
            self.job(cid,status="retry")
        result,queries=self.legacy_queries("/accounts")
        self.assertEqual(result[0],200)
        self.assertEqual(len(queries),1)
        self.assertIn("MAX(p.day)",queries[0])
        self.assertNotIn("WITH wanted(customer_id)",queries[0])
        self.parity()

    def test_more_than_400_missing_uses_original_whole_query(self):
        managed={cid:{"last_success_at":None,"attribution_changed":False} for cid in range(1,402)}
        managed[402]={"last_success_at":self.now.isoformat(),"attribution_changed":False}
        with patch.object(S.ManagedStorage,"performance_checks",return_value=managed):
            result,queries=self.legacy_queries("/dashboard")
            self.assertEqual(result[0],200)
            self.assertEqual(len(queries),1)
            self.assertIn("MAX(p.day)",queries[0])
            self.assertNotIn("WITH wanted(customer_id)",queries[0])
            self.parity()


if __name__=="__main__":
    unittest.main()
