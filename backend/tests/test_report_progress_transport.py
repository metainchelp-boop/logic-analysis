"""P24 pending two-source transport pins; unchanged codec/caps/nine immutable sources."""
import ast,hashlib,importlib.util
from pathlib import Path
import unittest
TOOLS=Path(__file__).resolve().parents[1]/'tools'
def load():
 spec=importlib.util.spec_from_file_location('product_basis_transport',TOOLS/'naver_report_progress_transport.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def pinned():
 t=load();text='pass';digest=hashlib.sha256(text.encode()).hexdigest()
 t.SOURCE_SHA256=t.COMPACT_SHA256=t.COMPACT_SOURCE_SHA256={k:digest for k in t.SOURCE_FILES};t.TRANSPORT_RAW_SHA256='d'*64;t.TARGET_SOURCE=t.EXPECTED_TARGET_SOURCE='b'*40
 package=dict(operation='code-prepare',baseline='a'*64,source_commit='b'*40,source_tar_gz_sha256='c'*64,ciphertext_sha256='d'*64,run_id='91827364509182736450')
 return t,dict(version=1,operation='preview-report-progress-prepare',package=package,sources={k:text for k in t.SOURCE_FILES})
class ProductBasisTransportTests(unittest.TestCase):
 def test_pending_target_and_patch_source_maps_refuse_before_module_loading(self):
  t=load();t.TARGET_SOURCE=None
  with self.assertRaisesRegex(ValueError,'PINS_PENDING'):t.require_pins()
 def test_canonical_codec_roundtrip_trailing_and_unknown_payload_fields_reject(self):
  t,value=pinned();wire=t.encode(value);self.assertEqual(t.decode(wire),value)
  for bad in (wire+'!',wire+'\n',t.PREFIX+'PRIVATE',wire.replace(t.PREFIX,'old-prefix:',1)):
   with self.assertRaises(ValueError):t.decode(bad)
  with self.assertRaises(ValueError):t.encode({**value,'PRIVATE':'PRIVATE'})
 def test_all_original_size_caps_and_codec_AST_remain_exact(self):
  t=load();self.assertEqual((t.MAX_JSON,t.MAX_WIRE,t.MAX_SOURCE,t.MAX_SOURCE_GZIP,t.MAX_CIPHERTEXT,t.MAX_PAYLOAD,t.MAX_BOOTSTRAP_B64,t.MAX_SSH),(393216,98304,160000,3*1024*1024,3*1024*1024,4*1024*1024,32768,131072))
  old=ast.parse((TOOLS/'naver_budget_format_transport.py').read_bytes());new=ast.parse((TOOLS/'naver_report_progress_transport.py').read_bytes())
  for name in ('encode','decode','unique','compact','bootstrap'):
   a=next(n for n in old.body if isinstance(n,ast.FunctionDef)and n.name==name);b=next(n for n in new.body if isinstance(n,ast.FunctionDef)and n.name==name);self.assertEqual(ast.dump(a),ast.dump(b),name)
 def test_two_exact_existing_paths_oversize_and_foreign_scope_remain_closed(self):
  t,value=pinned();self.assertEqual(t.CODE_PATHS,('naver_runtime/claude_provider.py','naver_runtime/report_output_schema.py'));self.assertEqual(t.EXPECTED_CODE_PATHS,t.CODE_PATHS)
  with self.assertRaises(ValueError):t.encode({**value,'sources':{**value['sources'],'patch':'a'*(t.MAX_SOURCE+1)}})
  for scope in ((),('unapproved.py',),('naver_runtime/claude_provider.py','extra.py'),('naver_runtime/claude_provider.py','naver_runtime/report_output_schema.py','extra.py')):
   t.CODE_PATHS=scope
   with self.subTest(scope=scope),self.assertRaises(ValueError):t.require_pins()
 def test_nine_dependency_raw_and_compact_hashes_remain_the_actual_existing_files(self):
  t=load();self.assertEqual(len(t.SOURCE_FILES),10);self.assertEqual(set(t.SOURCE_SHA256),set(t.SOURCE_FILES));self.assertEqual(set(t.COMPACT_SHA256),set(t.SOURCE_FILES))
  raw_helpers={'exports_helper','product_exporter','market_exporter'}
  for name,path in t.SOURCE_FILES.items():
   if name=='patch':continue
   raw=(TOOLS/path).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),t.SOURCE_SHA256[name],name)
   compact=raw if name in raw_helpers else t.compact(raw.decode()).encode()
   self.assertEqual(hashlib.sha256(compact).hexdigest(),t.COMPACT_SHA256[name],name)
  self.assertEqual(t.COMPACT_SOURCE_SHA256,t.COMPACT_SHA256)
if __name__=='__main__':unittest.main()
