"""Synthetic SQL and WSGI parity for bounded native dashboard daily reads."""
from datetime import date, datetime, timedelta, timezone
import sqlite3
import unittest
from unittest.mock import patch
from naver_engine import dashboard as D, store as S, web as WEB
from naver_engine.tests import test_accounts_match_reuse as TM
NOW = datetime(2026,10,9,12,tzinfo=S.KST)
EXTRA_COLUMNS = {'matching_fingerprint','conversion_attempts','conversions','source_at',
 'conversion_checked_at','campaign_fingerprint','source_generation','source_revision'}

def make_store(count=405,days=8,foreign=False):
 conn=sqlite3.connect(':memory:')
 conn.execute(next(sql for sql in S._SCHEMA if 'CREATE TABLE IF NOT EXISTS naver_auto_daily_performance ' in sql))
 for col,shape in S._REVISION_COLUMNS['naver_auto_daily_performance']:
  conn.execute('ALTER TABLE naver_auto_daily_performance ADD COLUMN '+col+' '+shape)
 owners={1000+i:(None if i%7==0 else 10+i%11) for i in reversed(range(count))}
 values=[]
 for cid,pid in owners.items():
  for n in range(days):
   wrong=foreign or (cid%13==0 and n%2==0)
   values.append((cid,str(date(2026,10,1)+timedelta(days=n)),99999 if wrong else pid,'f'*64,
    int(not(cid%19==0 and n==1)),int(cid%5!=0),2,100.,10.,None if cid%17==0 else(.1 if n%2 else .2),
    2.,0.,NOW.isoformat(),NOW.isoformat(),NOW.isoformat(),'c'*64,NOW.isoformat(),1))
 conn.executemany('INSERT INTO naver_auto_daily_performance VALUES ('+','.join('?' for _ in range(18))+')',values)
 return S.Store(conn,':memory:',None,writer=False,clock=lambda:NOW),owners

def reference(store,owners,now=NOW):
 today=now.astimezone(S.KST).date()
 raw=store.daily_performance(list(owners),today.replace(day=1),today-timedelta(days=1))
 usable=[r for r in raw if r.get('possibility_id')==owners.get(r['customer_id'])]
 return D.daily_checks(usable,now),{r['customer_id'] for r in raw}

class DashboardDailyLoadingTest(unittest.TestCase):
 def fixture(self,**kw):
  store,owners=make_store(**kw);self.addCleanup(store.close);return store,owners
 def test_whole_projection_null_decimal_partial_conversion_and_owner_parity(self):
  store,owners=self.fixture();expected=reference(store,owners);actual=store.dashboard_checks(owners,NOW)
  self.assertEqual(actual,expected);self.assertEqual(len(actual[1]),405)
  self.assertTrue(any(r['status']=='partial' for r in actual[0].values()))
  self.assertTrue(any(r['spend'] is None for r in actual[0].values()))
  self.assertTrue(any(r['conversion_value']==0 for r in actual[0].values()))
  self.assertTrue(any(r['conversion_value'] is None for r in actual[0].values()))
  self.assertEqual(next(r['spend'] for r in actual[0].values() if r['spend'] is not None),1.2)
 def test_foreign_pid_rows_keep_source_presence_without_current_metrics(self):
  store,owners=self.fixture(count=5,foreign=True)
  self.assertEqual(store.dashboard_checks(owners,NOW),({},set(owners)))
  self.assertEqual(store.dashboard_checks(owners,NOW),reference(store,owners))
 def test_native_never_materializes_full_rows_or_unused_source_columns(self):
  store,owners=self.fixture();expected=reference(store,owners);denied=[]
  def authorize(action,table,col,db,source):
   if action==sqlite3.SQLITE_READ and table=='naver_auto_daily_performance' and col in EXTRA_COLUMNS:
    denied.append(col);return sqlite3.SQLITE_DENY
   return sqlite3.SQLITE_OK
  store._conn.set_authorizer(authorize)
  with patch.object(S,'_rows',side_effect=AssertionError('full materialization forbidden')):
   self.assertEqual(store.dashboard_checks(owners,NOW),expected)
  self.assertEqual(denied,[])
 def test_chunks_are_at_most_400_ids(self):
  store,owners=self.fixture(count=801);statements=[];store._conn.set_trace_callback(statements.append)
  actual=store.dashboard_checks(owners,NOW)
  compact=[q for q in statements if q.startswith('SELECT customer_id,day,possibility_id')]
  self.assertEqual(len(compact),3)
  self.assertEqual([q.partition('IN (')[2].partition(')')[0].count(',')+1 for q in compact],[400,400,1])
  self.assertEqual(actual,reference(store,owners));self.assertEqual(len(actual[1]),801)
 def test_public_daily_and_pid_filter_stay_full_sorted(self):
  store,owners=self.fixture(count=5)
  raw=store.daily_performance(reversed(list(owners)),date(2026,10,1),date(2026,10,8))
  self.assertEqual(len(raw),40);self.assertEqual(len(raw[0]),18);self.assertTrue(EXTRA_COLUMNS.issubset(raw[0]))
  self.assertEqual([(r['customer_id'],r['day']) for r in raw],sorted((r['customer_id'],r['day']) for r in raw))
  pid=next(pid for pid in owners.values() if pid is not None)
  self.assertEqual(store.daily_performance(owners,date(2026,10,1),date(2026,10,8),possibility_id=pid),[r for r in raw if r['possibility_id']==pid])
 def test_override_receives_original_order_and_three_args(self):
  store,owners=self.fixture(count=5);raw=store.daily_performance(owners,date(2026,10,1),date(2026,10,8));calls=[]
  def custom(ids,start,end):calls.append((ids,start,end));return raw
  store.daily_performance=custom
  expected=D.daily_checks([r for r in raw if r['possibility_id']==owners[r['customer_id']]],NOW),set(owners)
  self.assertEqual(store.dashboard_checks(owners,NOW),expected)
  self.assertEqual(calls,[(list(owners),date(2026,10,1),date(2026,10,8))])
 def test_first_day_empty_and_korean_date(self):
  store,owners=self.fixture(count=5)
  for now,current in((NOW.replace(day=1),owners),(NOW,{}),(datetime(2026,10,8,16,tzinfo=timezone.utc),owners)):
   self.assertEqual(store.dashboard_checks(current,now),reference(store,current,now))
 def test_overflow_and_invalid_text_keep_unknown(self):
  store,owners=self.fixture(count=5);ids=list(owners)
  store._conn.execute('UPDATE naver_auto_daily_performance SET spend=? WHERE customer_id=?',(D.MAX_NUMBER,ids[0]))
  store._conn.execute('UPDATE naver_auto_daily_performance SET clk=? WHERE customer_id=?',('invalid',ids[1]))
  self.assertEqual(store.dashboard_checks(owners,NOW),reference(store,owners))
 def test_fixed_reader_clock_failure_preserves_original_exception(self):
  calls=[];timing={}
  class Adapter:
   def dashboard_checks(self,owners,now):calls.append((owners,now));raise LookupError('synthetic')
  timed=WEB._TimedReadStore(Adapter(),timing)
  with patch.object(WEB._time,'perf_counter',side_effect=RuntimeError('clock')):
   with self.assertRaisesRegex(LookupError,'^synthetic$'):timed.dashboard_checks({},NOW)
  self.assertEqual(calls,[({},NOW)]);self.assertEqual(timing,{})
  self.assertEqual(tuple(WEB._TIMED_READ_ACCESSORS),WEB._TIMED_READ_METHODS)
  self.assertLessEqual(len('dashboard_checks'),20)
  with self.assertRaises(AttributeError):timed._conn

class DashboardDailyHttpParityTest(unittest.TestCase):
 def setUp(self):
  self.fixture=TM.AccountsMatchReuseTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
  self.store,self.clock=self.fixture.store,self.fixture.clock;now=self.clock.now()
  first,second=[r['customer_id'] for r in self.store.accounts()[:2]];start,end=now.date().replace(day=1),now.date()-timedelta(days=1)
  for cid in(first,second):
   self.store._conn.execute('''INSERT INTO naver_auto_monthly_check
    (customer_id,period_start,period_end,snapshot_at,checked_at,status,next_try_at,imp,clk,spend,conversion_value,enabled_campaigns,campaign_count)
    VALUES(?,?,?,?,?,'ok',?,?,?,?,?,1,1)''',(cid,str(start),str(end),now.isoformat(),now.isoformat(),now.isoformat(),100,10,1000,3000))
  for cid,pid in((first,11),(second,999999)):
   for n in range((end-start).days+1):
    self.store._conn.execute('''INSERT INTO naver_auto_daily_performance
     (customer_id,day,possibility_id,matching_fingerprint,basic_complete,conversion_complete,conversion_attempts,
      imp,clk,spend,conversion_value,checked_at,campaign_fingerprint)
     VALUES(?,?,?,'synthetic',1,1,0,100,10,0.1,0,?,'synthetic')''',(cid,str(start+timedelta(days=n)),pid,now.isoformat()))
 def test_whole_http_payload_scope_matches_old_raw_reader(self):
  for actor,narrowed,selection in((0,False,'all'),(0,False,'person:100'),(0,False,'unassigned'),(100,False,'all'),(101,False,'all'),(0,True,'all')):
   path='/dashboard?selection='+selection
   with patch.object(S.ManagedStorage,'dashboard_checks',None):expected=self.fixture.call(path,actor,narrowed=narrowed)
   actual=self.fixture.call(path,actor,narrowed=narrowed);self.assertEqual(actual,expected);self.assertEqual(actual[0],200)
 def test_foreign_source_removes_monthly_fallback_and_preserves_cursor(self):
  status,first=self.fixture.call('/dashboard?view_sync=1');self.assertEqual(status,200)
  self.assertIn('store_dashboard_checks_calls',first['_request_timing']);cursor=first['cursor']
  with patch.object(S.ManagedStorage,'dashboard_checks',None):status,second=self.fixture.call('/dashboard?view_sync=1&view_cursor='+cursor)
  self.assertEqual(status,200);self.assertEqual(second['mode'],'unchanged');self.assertEqual(second['cursor'],cursor)
  self.assertEqual(first['data']['totals']['spend'],.1*(self.clock.now().day-1))
if __name__=='__main__':unittest.main()
