"""New bounded synthetic cases only; no operating calls or data."""
import ast, copy, hashlib, importlib.util, json, sqlite3, sys, tempfile, time, types, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
TOOLS=Path(__file__).resolve().parents[1]/'tools'
HERE=TOOLS
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
D=load('b00_reason',TOOLS/'naver_current_inspection_b00_reason.py')
T=load('b00_reason_transport',TOOLS/'naver_current_inspection_b00_reason_transport.py')
NOW=datetime(2026,10,18,20,0,tzinfo=timezone(timedelta(hours=9)))

def empty_result():
 return dict(schema_version=21,selector_model='b00-foodin-readonly-v1',target_identifier_namespace='ad_account_no',
 observed_at=NOW.isoformat(),target='foodin',sources={k:False for k in ('account_snapshot_current','catalog_current','organization_current','current_expected_pair','management_sync_pending')},
 job=dict(kind=None,current_daily=False,current_record_present=False,latest_matches_current=False,ordering_attempt_at=None,
 checkpoint=dict(state='missing',checked_at=None,next_try_at=None,attempts=None,next_index=None,queue_tasks=None,confirmed=None)),
 scope_equal={k:None for k in D.SCOPE_FIELDS},continuation=dict(checkpoint_state='missing',bridge_state='missing',
 facts={k:False for k in D.FACTS},resumable=False,branch='row_missing',historical_scope_components='unknown'),
 selection=dict(gate='ACCOUNT_NOT_IN_SNAPSHOT',rank_exact=False,eligible_count=None,ahead_count=None,within_selected_24=None,ordering_hint_only=True),limits=dict(D.LIMITS),mutations=0)

class B00Reason(unittest.TestCase):
 def test_sqlite_readonly_authorizer(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder).resolve()/'fixture.db';c=sqlite3.connect(path);c.execute('CREATE TABLE t(v)');c.execute('INSERT INTO t VALUES(1)');c.commit();c.close()
   c=D.connect_reader(path)
   try:
    self.assertEqual(c.execute('SELECT v FROM t').fetchone(),(1,))
    for sql in ('UPDATE t SET v=2','CREATE TABLE forbidden(v)',"ATTACH ':memory:' AS other",'PRAGMA query_only=OFF'):
     with self.assertRaises(sqlite3.DatabaseError):c.execute(sql)
    self.assertEqual(c.total_changes,0)
   finally:c.close()
 def test_old_source_package_refused(self):
  value=dict(T.PACKAGE,source_commit='15f3a23c2255de98cba3670fce3b489309698e1f')
  with self.assertRaisesRegex(ValueError,'PACKAGE'):D.validate_package(value)
 def test_old_receipt_rejected_before_docker(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder);prepared=path/'prepared.json';started=path/('preview-start-'+D.SOURCE+'.json')
   prepared.write_text('{}');started.write_text('{}')
   calls=[]
   release=types.SimpleNamespace(prepared_paths=lambda s:(path,prepared),trusted_private_file=lambda p:None,
    unique=T.unique,command=lambda *a,**k:calls.append(a))
   with patch.object(D.os,'geteuid',return_value=0),self.assertRaisesRegex(ValueError,'SOURCE_NOT_READY'):
    D.run(dict(T.PACKAGE),types.SimpleNamespace(baseline=lambda:D.BASELINE),release)
   self.assertEqual(calls,[])
 def test_namespace_target_cannot_expand(self):
  with self.assertRaisesRegex(ValueError,'TARGETS'):D.collect(None,NOW,time.monotonic()+1,{},targets=(('gomso',74789,2488728),*D.TARGETS))
 def test_closed_output_rejects_raw_and_alias(self):
  self.assertIs(D.validate_result(v:=empty_result()),v)
  for change in ('extra','alias','component'):
   bad=copy.deepcopy(v)
   if change=='extra':bad['scope_equal']['raw_hash']='a'*64
   if change=='alias':bad['continuation']['facts']['checkpoint_sealed']=1
   if change=='component':bad['continuation']['historical_scope_components']='organization'
   with self.assertRaises(ValueError):D.validate_result(bad)
 def test_fixed_daily_and_no_writer_calls(self):
  tree=ast.parse(D.PROJECTION_SOURCE);collect=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='collect')
  source=ast.get_source_segment(D.PROJECTION_SOURCE,collect)
  self.assertIn("kind='daily' AND cycle_day=?",source);self.assertEqual(D.TARGET_DAY,'2026-10-18')
  self.assertIn("period_for('daily'",source);self.assertIn('MANUAL_TAKES_PRECEDENCE',source)
  called={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
  self.assertFalse(called & {'inspection_work','synchronize_management','begin_inspection','record_inspection_progress','_set_meta','_tx'})
  self.assertIn('_inspection_order_attempt',called)
 def test_host_guard_function_byte_preserved(self):
  old=(TOOLS/'naver_current_inspection_diagnostics.py').read_text();new=(HERE/'naver_current_inspection_b00_reason.py').read_text()
  def part(s,name):return ast.get_source_segment(s,next(n for n in ast.parse(s).body if isinstance(n,ast.FunctionDef) and n.name==name))
  self.assertEqual(part(old,'run'),part(new,'run'));self.assertEqual(part(old,'script'),part(new,'script'))
 def test_three_source_roundtrip_and_tamper(self):
  raw={name:(HERE/filename if name=='diagnostic' else TOOLS/filename).read_bytes() for name,filename in T.SOURCE_FILES.items()}
  for name,body in raw.items():self.assertEqual(hashlib.sha256(body).hexdigest(),T.SOURCE_SHA256[name])
  value=dict(version=1,operation=T.OPERATION,package=dict(T.PACKAGE),sources={k:T.compact(v.decode()) for k,v in raw.items()})
  self.assertEqual(T.decode(T.encode(value)),value)
  value['sources']['diagnostic']+='\n'
  with self.assertRaises(ValueError):T.encode(value)

if __name__=='__main__':unittest.main()
