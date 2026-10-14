"""New transport namespace only; codec/caps and the nine dependencies stay exact."""
import ast,hashlib,importlib.util,json
from pathlib import Path
import unittest
from unittest.mock import patch
TOOLS=Path(__file__).resolve().parents[1]/'tools'
def load():
 spec=importlib.util.spec_from_file_location('report_progress_transport',TOOLS/'naver_report_progress_transport.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def pinned():
 t=load();text='pass';digest=hashlib.sha256(text.encode()).hexdigest()
 t.SOURCE_SHA256=t.COMPACT_SHA256=t.COMPACT_SOURCE_SHA256={k:digest for k in t.SOURCE_FILES};t.TRANSPORT_RAW_SHA256='d'*64;t.TARGET_SOURCE=t.EXPECTED_TARGET_SOURCE='b'*40
 package=dict(operation='code-prepare',baseline='a'*64,source_commit='b'*40,source_tar_gz_sha256='c'*64,ciphertext_sha256='d'*64,run_id='91827364509182736450')
 return t,dict(version=1,operation='preview-report-progress-prepare',package=package,sources={k:text for k in t.SOURCE_FILES})
class ReportProgressTransportTests(unittest.TestCase):
 def test_pending_target_and_patch_maps_refuse(self):
  t=load()
  with self.assertRaisesRegex(ValueError,'PINS_PENDING'):t.require_pins()
 def test_codec_canonical_roundtrip_trailing_and_unknown_fields_reject(self):
  t,value=pinned();wire=t.encode(value);self.assertEqual(t.decode(wire),value)
  for bad in [wire+'!',wire+'\n',t.PREFIX+'PRIVATE',wire.replace(t.PREFIX,'old-prefix:',1)]:
   with self.assertRaises(ValueError):t.decode(bad)
  with self.assertRaises(ValueError):t.encode({**value,'PRIVATE':'PRIVATE'})
 def test_caps_and_existing_decode_function_ast_are_unchanged(self):
  t=load();self.assertEqual((t.MAX_JSON,t.MAX_WIRE,t.MAX_BOOTSTRAP_B64,t.MAX_SSH),(393216,98304,32768,131072))
  root=next(x for x in TOOLS.parents if(x/'naver-claude-reference-ops-20261011/backend/tools/naver_budget_format_transport.py').is_file())if not(TOOLS/'naver_budget_format_transport.py').is_file()else None
  old=(root/'naver-claude-reference-ops-20261011/backend/tools/naver_budget_format_transport.py')if root else TOOLS/'naver_budget_format_transport.py'
  a=ast.parse(old.read_bytes());b=ast.parse((TOOLS/'naver_report_progress_transport.py').read_bytes())
  for name in ('encode','decode','unique','compact','bootstrap'):
   x=next(n for n in a.body if isinstance(n,ast.FunctionDef)and n.name==name);y=next(n for n in b.body if isinstance(n,ast.FunctionDef)and n.name==name);self.assertEqual(ast.dump(x),ast.dump(y),name)
 def test_json_size_source_hash_and_foreign_code_path_guards_stay_closed(self):
  t,value=pinned()
  with self.assertRaises(ValueError):t.encode({**value,'sources':{**value['sources'],'patch':'a'*(t.MAX_SOURCE+1)}})
  t.CODE_PATHS=tuple(['unapproved.py']+list(t.CODE_PATHS)[1:])
  with self.assertRaises(ValueError):t.require_pins()
if __name__=='__main__':unittest.main()
