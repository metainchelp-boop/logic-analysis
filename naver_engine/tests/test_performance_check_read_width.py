"""26→18 반환 칸만 줄인다. 모든 이력·동률 순서·현재 업무/전체 응답은 원본과 같아야 한다."""
import random
import sqlite3
import unittest
from unittest.mock import patch
from datetime import timedelta

from naver_engine import store as S, management_store as MS
from naver_engine.tests import test_inventory_legacy_loading as TL

OLD_COLUMNS=("job_key","customer_id","kind","cycle_day","period_start","period_end","snapshot_at",
    "catalog_at","stage_revision","possibility_id","matching_fingerprint","status","checked_at",
    "next_try_at","attempts","error_code","progress_hash","bizmoney","bizmoney_at","last_success_at",
    "last_bizmoney","last_bizmoney_at","previous_bizmoney","previous_bizmoney_at","generation","source_wait_attempts")
UNUSED={"job_key","snapshot_at","catalog_at","matching_fingerprint","next_try_at","attempts","progress_hash","source_wait_attempts"}


class FullJobsConnection:
    def __init__(self,connection):
        self.connection=connection
    def execute(self,sql,args=()):
        marker="FROM naver_auto_performance_job ORDER BY checked_at,job_key"
        if marker in " ".join(sql.split()):
            sql="SELECT "+",".join(OLD_COLUMNS)+" "+sql[sql.index("FROM naver_auto_performance_job"):]
        return self.connection.execute(sql,args)
    def __getattr__(self,name):
        return getattr(self.connection,name)


class PerformanceCheckReadWidthTest(unittest.TestCase):
    def setUp(self):
        self.base=TL.InventoryLegacyLoadingTest();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.store,self.now=self.base.store,self.base.now
        self.native=S.ManagedStorage.performance_checks

    def reference_checks(self):
        conn=self.store._conn;self.store._conn=FullJobsConnection(conn)
        try:return self.native(self.store,self.now)
        finally:self.store._conn=conn

    def mixed_history(self):
        randomizer=random.Random(3145)
        cur=self.store._conn.execute("SELECT * FROM naver_auto_performance_job")
        names=[d[0] for d in cur.description];base=[dict(zip(names,r)) for r in cur]
        rows=[]
        for row in base:
            for n in range(20):
                day=self.now.date()-timedelta(days=n)
                kind=("daily","weekly","manual","reconcile","report_monthly")[n%5]
                span=6 if kind=="weekly" else 29 if kind=="reconcile" else 0
                at=(self.now-timedelta(days=n//2,hours=1)).isoformat()
                values={**row,"job_key":row["job_key"]+":"+str(n),"kind":kind,"cycle_day":str(day),
                    "period_start":str(day-timedelta(days=span+1)),"period_end":str(day-timedelta(days=1)),
                    "status":("ok","retry","partial","superseded")[n%4],"checked_at":at,
                    "last_success_at":at if n%3==0 else None,"possibility_id":99999 if n%7==0 else row["possibility_id"],
                    "bizmoney":randomizer.choice([None,0,1,12.5]),"bizmoney_at":at,
                    "last_bizmoney":randomizer.choice([None,0,7.5]),"last_bizmoney_at":at,
                    "previous_bizmoney":randomizer.choice([None,0,3.5]),
                    "previous_bizmoney_at":(self.now-timedelta(days=n//2,hours=2)).isoformat(),
                    "error_code":"NETWORK" if n%4==1 else None,"progress_hash":"unused",
                    "attempts":n%4,"source_wait_attempts":n%5}
                rows.append(tuple(values.get(k) for k in names))
        self.store._conn.executemany("INSERT INTO naver_auto_performance_job ("+",".join(names)+") VALUES ("+
            ",".join("?" for _ in names)+")",rows)
        cid=self.base.cids[0]
        self.store._conn.execute("""INSERT INTO naver_auto_manual_read
            (customer_id,requested_at,actor,consumed_at,possibility_id,request_kind,period_start,period_end)
            VALUES(?,?,0,NULL,?,'manual_period',?,?)""",(cid,self.now.isoformat(),
            self.base.policies[cid]["possibility_id"],str(self.now.date()-timedelta(days=3)),str(self.now.date()-timedelta(days=1))))

    def test_unused_return_columns_denied_except_required_order_key_and_full_output_equal(self):
        self.mixed_history();expected=self.reference_checks();columns=[];denied=[]
        conn=self.store._conn
        class Observed:
            def execute(self,sql,args=()):
                cur=conn.execute(sql,args)
                if "FROM naver_auto_performance_job ORDER BY checked_at,job_key" in " ".join(sql.split()):
                    columns.append(tuple(d[0] for d in cur.description))
                return cur
            def __getattr__(self,name):return getattr(conn,name)
        original=S._authorizer(S.PHASE_READ)
        def guard(action,table,column,db,source):
            if action==sqlite3.SQLITE_READ and table=="naver_auto_performance_job" and column in UNUSED-{"job_key"}:
                denied.append(column);return sqlite3.SQLITE_DENY
            return original(action,table,column,db,source)
        conn.set_authorizer(guard);self.store._conn=Observed()
        try:actual=self.native(self.store,self.now)
        finally:self.store._conn=conn
        self.assertEqual(actual,expected)
        self.assertEqual(columns,[tuple(k for k in OLD_COLUMNS if k not in UNUSED)])
        self.assertEqual(len(columns[0]),18)
        self.assertFalse(set(columns[0])&UNUSED)
        self.assertEqual(denied,[])

    def test_multi_history_current_pid_change_weekly_reconcile_and_expired_hold_keep_projection(self):
        self.mixed_history()
        for state in ("current","changed_pid","holding_expired","failed_catalog"):
            with self.subTest(state=state):
                if state=="changed_pid":
                    self.store.record_decision(12,self.base.cids[0],"confirmed",0,self.now)
                elif state=="holding_expired":
                    catalog=self.store.account_catalog()
                    items=[{**r,"stage":"계약만료" if r["possibility_id"]==11 else "홀딩중"} for r in catalog["items"]]
                    self.store.record_account_catalog({"generated_at":self.now.isoformat(),"total":len(items),
                        "complete":True,"items":items},self.base.fixture.ids,self.now)
                elif state=="failed_catalog":
                    self.store.record_account_catalog_failure(self.now,"CATALOG_FAILED")
                self.assertEqual(self.native(self.store,self.now),self.reference_checks())

    def test_wsgi_all_payload_scope_cursor_and_custom_performance_fallback_equal_full_reference(self):
        self.mixed_history();native=self.native
        def reference(store,now,*,_policies=None):
            conn=store._conn;store._conn=FullJobsConnection(conn)
            try:return native(store,now,_policies=_policies)
            finally:store._conn=conn
        for endpoint in ("accounts","dashboard"):
            for actor,query,narrowed in ((0,"",False),(100,"",False),(101,"",False),
                    (0,"?selection=unassigned",False),(0,"",True)):
                path="/"+endpoint+query
                with self.subTest(endpoint=endpoint,actor=actor,query=query,narrowed=narrowed):
                    with patch.object(S.ManagedStorage,"performance_checks",reference):
                        expected=self.base.request(path,actor,narrowed)
                    self.assertEqual(self.base.request(path,actor,narrowed),expected)
            with patch.object(S.ManagedStorage,"performance_checks",reference):
                old=self.base.request("/"+endpoint+"?view_sync=1")[1]
            new=self.base.request("/"+endpoint+"?view_sync=1&view_cursor="+old["cursor"])[1]
            self.assertEqual(new["mode"],"unchanged")
            self.assertEqual(new["cursor"],old["cursor"])
            self.assertIsNone(new["data"])


if __name__=="__main__":
    unittest.main()
