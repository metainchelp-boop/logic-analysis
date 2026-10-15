"""Three-source diagnostic epoch; closed codec and uniform layout representation."""
import ast,hashlib,importlib.util
import base64,copy,io,json,lzma,tokenize
from unittest.mock import patch
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
def wire_of(t, raw):
    return t.PREFIX + base64.b85encode(lzma.compress(raw, format=lzma.FORMAT_XZ,
        check=lzma.CHECK_CRC64, filters=[{'id':lzma.FILTER_LZMA2,
        'preset':6|lzma.PRESET_EXTREME, 'lc':4, 'pb':0}])).decode()


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
  for name in ('encode','decode','unique','bootstrap'):
   a=next(n for n in old.body if isinstance(n,ast.FunctionDef)and n.name==name);b=next(n for n in new.body if isinstance(n,ast.FunctionDef)and n.name==name);self.assertEqual(ast.dump(a),ast.dump(b),name)
  a=next(n for n in old.body if isinstance(n,ast.FunctionDef)and n.name=='compact');b=next(n for n in new.body if isinstance(n,ast.FunctionDef)and n.name=='compact')
  self.assertEqual(ast.dump(ast.Module(body=a.body[:-1],type_ignores=[])),ast.dump(ast.Module(body=b.body[:-1],type_ignores=[])))
  self.assertEqual(ast.dump(a.body[-1]),ast.dump(ast.parse('return result').body[0]))
  self.assertEqual(ast.dump(b.body[-1]),ast.dump(ast.parse('return _compact_horizontal_layout(result)').body[0]))
 def test_two_exact_existing_paths_oversize_and_foreign_scope_remain_closed(self):
  t,value=pinned();self.assertEqual(t.CODE_PATHS,('backend/naver_page/operations-ui.js','naver_engine/inspection_store.py','naver_engine/observation_store.py'));self.assertEqual(t.EXPECTED_CODE_PATHS,t.CODE_PATHS)
  with self.assertRaises(ValueError):t.encode({**value,'sources':{**value['sources'],'patch':'a'*(t.MAX_SOURCE+1)}})
  for scope in ((),('unapproved.py',),('naver_runtime/claude_provider.py','extra.py'),('naver_runtime/claude_provider.py','naver_runtime/report_output_schema.py','extra.py'),t.CODE_PATHS[:-1],t.CODE_PATHS+('extra.py',)):
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

class UniformCompactBoundaryTests(unittest.TestCase):
    def test_decompression_cap_stream_tail_and_duplicate_keys_fail_closed(self):
        t,value=pinned()
        valid=t.encode(value)
        packed=base64.b85decode(valid[len(t.PREFIX):])
        raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
        bomb=wire_of(t,b' '*(t.MAX_JSON+1))
        self.assertLess(len(bomb),t.MAX_WIRE)
        duplicate=raw.replace(b'"version":1',b'"version":1,"version":1',1)
        cases=(bomb,
            t.PREFIX+base64.b85encode(packed+b'trailing').decode(),
            t.PREFIX+base64.b85encode(packed+packed).decode(),
            t.PREFIX+base64.b85encode(packed[:-1]).decode(),
            wire_of(t,duplicate),
            wire_of(t,b'{"not":"a closed transport"}'))
        for bad in cases:
            with self.subTest(case=cases.index(bad)),self.assertRaisesRegex(ValueError,'PATCH_ENCODING'):
                t.decode(bad)

    def test_source_hash_role_shape_and_pin_alias_mutation_never_load_sources(self):
        t,value=pinned()
        mutations=[]
        for role in t.SOURCE_FILES:
            changed=copy.deepcopy(value);changed['sources'][role]='raise RuntimeError("must not execute")'
            mutations.append(changed)
        missing=copy.deepcopy(value);missing['sources'].pop('patch');mutations.append(missing)
        extra=copy.deepcopy(value);extra['sources']['foreign']='pass';mutations.append(extra)
        boolean=copy.deepcopy(value);boolean['version']=True;mutations.append(boolean)
        foreign=copy.deepcopy(value);foreign['operation']='other-operation';mutations.append(foreign)
        for i,changed in enumerate(mutations):
            with self.subTest(case=i),self.assertRaises(ValueError):t.encode(changed)
            raw=json.dumps(changed,ensure_ascii=False,separators=(',',':')).encode()
            with self.subTest(wire_case=i),self.assertRaises(ValueError):t.decode(wire_of(t,raw))
        t.COMPACT_SOURCE_SHA256=dict(t.COMPACT_SHA256,patch='e'*64)
        with self.assertRaisesRegex(ValueError,'PINS_PENDING'):t.encode(value)
        with self.assertRaisesRegex(ValueError,'PINS_PENDING'):t.decode(wire_of(t,json.dumps(value).encode()))


    def test_horizontal_layout_preserves_all_tokens_ast_fstrings_and_idempotence(self):
        t=load()
        snippets=(
            "x = 1 .real\ny = x + + 2\n",
            "result = {'a': [1, 2], 'b': (3, 4)}\n",
            "def chosen(value):\n return value + 1\n",
            "text = 'literal { } +  spaced\\nsecond line'\n",
            'text = f"literal  + {{braces}} {value + 1 : >8}"\n',
            'text = f"outer {f\'nested {value + 1}\'}"\n',
            "x = 1 # public synthetic comment\n",
        )
        tokens=lambda s:[(v.type,v.string)for v in tokenize.generate_tokens(io.StringIO(s).readline)]
        for source in snippets:
            with self.subTest(source=source):
                result=t._compact_horizontal_layout(source)
                self.assertEqual(tokens(result),tokens(source))
                self.assertEqual(ast.dump(ast.parse(result)),ast.dump(ast.parse(source)))
                self.assertEqual(t._compact_horizontal_layout(result),result)
                compile(result,'synthetic','exec')
        self.assertLess(len(t._compact_horizontal_layout("value = (1 + 2)\n")),len("value = (1 + 2)\n"))

    def test_forced_unsafe_token_merge_is_rejected_by_final_token_guard(self):
        t=load();original=t.tokenize.generate_tokens
        source='value = 1 .real\n'
        def generate(readline):
            text=readline.__self__.getvalue()
            if text=='1.':
                return iter((tokenize.TokenInfo(tokenize.NUMBER,'1',(1,0),(1,1),text),
                    tokenize.TokenInfo(tokenize.OP,'.',(1,1),(1,2),text)))
            return original(readline)
        with patch.object(t.tokenize,'generate_tokens',side_effect=generate):
            with self.assertRaisesRegex(ValueError,'COMPLETION_SOURCE_AST'):
                t._compact_horizontal_layout(source)

if __name__=='__main__':unittest.main()
