"""New trusted management-SSH codec only; historical codecs remain untouched."""
import ast
import base64
import copy
from contextlib import contextmanager
import hashlib
import gzip
import importlib.util
import json
import lzma
import os
import stat
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import naver_completion_transport as T
import naver_completion_exports as E
import naver_preview_release as R


def sample():
    return {'version':1,'operation':'preview-completion-prepare','package':{},
        'sources':{k:'value = 1\n' for k in T.SOURCE_FILES},
        'approved_config_operation_id':'74c912dddf824fae99012849bc4c19a5'}


def controller_fixture(**values):
    # The workflow reporter and execute() load distinct copies of this module.
    path=Path(__file__).resolve().parents[1]/'tools/naver_preview_completion_release.py'
    spec=importlib.util.spec_from_file_location('completion_diagnostics_fixture',path)
    controller=importlib.util.module_from_spec(spec);spec.loader.exec_module(controller)
    for key,value in values.items():setattr(controller,key,value)
    return controller


def packed(raw):return T.PREFIX+base64.b64encode(lzma.compress(raw,preset=6)).decode()


def workflow_ssh_pressure():
    """Execute only the actual workflow's two pure pressure functions."""
    workflow=(Path(__file__).resolve().parents[2]/'.github/workflows/debug-rank.yml').read_text(encoding='utf-8')
    section=workflow.split('\n  completion-release:\n',1)[1]
    first=section.index('          def completion_ssh_scripts(')
    last=section.index('          C.require_pins()',first)
    definitions=''.join(line[10:] if line.startswith('          ') else line for line in section[first:last].splitlines(keepends=True))
    tree=ast.parse(definitions)
    assert [node.name for node in tree.body]==['completion_ssh_scripts','require_completion_ssh_pressure']
    namespace={};exec(compile(tree,'<workflow-pressure-functions>','exec'),namespace)
    return workflow,namespace['completion_ssh_scripts'],namespace['require_completion_ssh_pressure']


class CompletionSSHPressureTests(unittest.TestCase):
    def test_actual_both_scripts_and_two_quoted_exports_are_included(self):
        workflow,scripts,require=workflow_ssh_pressure();wire=T.PREFIX+'AA==';transport='AA=='
        self.assertEqual(len(scripts(workflow)),2)
        exports="export COMPLETION_B64='"+wire+"'; export COMPLETION_TRANSPORT_B64='"+transport+"';\n"
        actual=require(wire,transport,workflow)
        self.assertEqual(actual,[len((exports+script).encode('utf-8')) for script in scripts(workflow)])
        self.assertTrue(all(size>len(exports) for size in actual))
        self.assertIn('incoming=True',scripts(workflow)[0]);self.assertIn('transport.execute(bundle)',scripts(workflow)[1])

    def test_total_utf8_boundary_is_strict_and_unknown_script_shape_refuses(self):
        workflow,_,require=workflow_ssh_pressure();wire=T.PREFIX+'AA==';transport='AA=='
        bounded=wire+'A'*(131071-max(require(wire,transport,workflow)))
        self.assertEqual(max(require(bounded,transport,workflow)),131071)
        with self.assertRaisesRegex(ValueError,'COMPLETION_SSH_SIZE'):require(bounded+'A',transport,workflow)
        before,marker,section=workflow.partition('\n  completion-release:\n')
        for changed in (section.replace('          script: |\n','          script: >\n',1),
                section.replace('        uses: appleboy/ssh-action@','        uses: unsupported/ssh-action@',1)):
            with self.subTest(changed=changed[:40]),self.assertRaisesRegex(ValueError,'COMPLETION_SSH_WORKFLOW'):
                require(wire,transport,before+marker+changed)
        for value in ("'",'\n','\x00','가'):
            with self.subTest(value=repr(value)),self.assertRaisesRegex(ValueError,'COMPLETION_SSH_ENV'):
                require(wire+value,transport,workflow)

    def test_script_unicode_is_measured_as_utf8_bytes(self):
        workflow,_,require=workflow_ssh_pressure();wire=T.PREFIX+'AA==';transport='AA=='
        before,marker,section=workflow.partition('\n  completion-release:\n')
        addition='            # '+'가'*100+'\n'
        changed=before+marker+section.replace('            set -eu\n','            set -eu\n'+addition,1)
        baseline=require(wire,transport,workflow);actual=require(wire,transport,changed)
        self.assertEqual(actual[0]-baseline[0],len(addition[12:].encode('utf-8')))
        self.assertEqual(actual[1],baseline[1])


class CompletionPayloadBoundaryTests(unittest.TestCase):
    def setUp(self):self.release=T.CompletionRelease(R)
    def payload(self,source=b'synthetic-source'):
        files=[{'path':str(R.SECRET_ROOT/name),'uid':owner[0],'gid':owner[1],'mode':0o600,'content':'synthetic'}
            for name,owner in R.SECRET_OWNERS.items()]
        return {'schema':1,'purpose':'naver-owner-verification-runtime','source_commit':'f'*40,
            'source_tar_gz_b64':base64.b64encode(source).decode(),'files':files}
    def decode(self,payload,source):
        return self.release.decode_payload(json.dumps(payload,separators=(',',':')).encode(),'f'*40,R.sha(source))
    def test_new_route_accepts_source_above_legacy_bound_without_changing_legacy_decoder(self):
        source=b'x'*(2*1024*1024+1);payload=self.payload(source)
        self.assertEqual(self.decode(payload,source)[0],source)
        with self.assertRaisesRegex(ValueError,'PAYLOAD_HASH'):R.validate_payload(payload,'f'*40,R.sha(source))
        self.assertIsNot(R.decode_payload,self.release.decode_payload)
    def test_source_gzip_bound_is_strict_and_hash_and_runtime_file_policy_remain_closed(self):
        source=b'x'*(T.MAX_SOURCE_GZIP-1)
        self.assertEqual(self.release.validate_payload(self.payload(source),'f'*40,R.sha(source))[0],source)
        source=b'x'*T.MAX_SOURCE_GZIP
        with self.assertRaisesRegex(ValueError,'PAYLOAD_HASH'):self.release.validate_payload(self.payload(source),'f'*40,R.sha(source))
        source=b'synthetic';payload=self.payload(source)
        with self.assertRaisesRegex(ValueError,'PAYLOAD_HASH'):self.release.validate_payload(payload,'f'*40,'0'*64)
        for mutation in (lambda p:p['files'][0].update(path='/not-approved'),lambda p:p['files'][0].update(mode=0o644),
                lambda p:p['files'].append(p['files'][0]),lambda p:p.update(extra=1)):
            invalid=copy.deepcopy(payload);mutation(invalid)
            with self.assertRaises(ValueError):self.release.validate_payload(invalid,'f'*40,R.sha(source))
    def test_raw_payload_inclusive_four_mib_boundary_and_gzip_bomb_trailing_members_refuse(self):
        source=b'synthetic';raw=json.dumps(self.payload(source),separators=(',',':')).encode()
        bounded=raw+b' '*(T.MAX_PAYLOAD-len(raw))
        self.assertEqual(self.release.decode_payload(bounded,'f'*40,R.sha(source))[0],source)
        with self.assertRaisesRegex(ValueError,'PLAINTEXT_SIZE'):self.release.decode_payload(bounded+b' ','f'*40,R.sha(source))
        magic=b'NAVER-PREVIEW-PAYLOAD-GZIP-1\n'
        self.assertEqual(self.release.decode_payload(magic+gzip.compress(bounded),'f'*40,R.sha(source))[0],source)
        for body in (gzip.compress(bounded+b' '),gzip.compress(raw)+gzip.compress(raw),gzip.compress(raw)+b'tail',gzip.compress(raw)[:-1]):
            with self.assertRaisesRegex(ValueError,'PAYLOAD_COMPRESSION'):self.release.decode_payload(magic+body,'f'*40,R.sha(source))
    def test_duplicate_payload_fields_and_invalid_compression_refuse(self):
        for raw in (b'{"schema":1,"schema":1}',b'NAVER-PREVIEW-PAYLOAD-GZIP-1\ninvalid'):
            with self.assertRaises(ValueError):self.release.decode_payload(raw,'f'*40,'0'*64)
    def test_ciphertext_inclusive_three_mib_bound_preserves_owner_hash_and_no_read_on_oversize(self):
        def info(size,mode=stat.S_IFREG|0o600,uid=0,gid=0,links=1):
            return SimpleNamespace(st_mode=mode,st_uid=uid,st_gid=gid,st_nlink=links,st_size=size)
        body=b'x'*T.MAX_CIPHERTEXT;path=Mock();path.lstat.return_value=info(len(body));path.read_bytes.return_value=body
        self.assertEqual(self.release.received_ciphertext(path,R.sha(body)),body)
        path.read_bytes.reset_mock();path.lstat.return_value=info(len(body)+1)
        with self.assertRaisesRegex(ValueError,'CIPHERTEXT_FILE'):self.release.received_ciphertext(path,R.sha(body))
        path.read_bytes.assert_not_called()
        for unsafe in (info(1,mode=stat.S_IFLNK|0o600),info(1,uid=501),info(1,links=2),info(1,mode=stat.S_IFREG|0o644)):
            path.lstat.return_value=unsafe
            with self.assertRaisesRegex(ValueError,'CIPHERTEXT_FILE'):self.release.received_ciphertext(path,R.sha(body))
        path.lstat.return_value=info(len(body))
        with self.assertRaisesRegex(ValueError,'CIPHERTEXT_HASH'):self.release.received_ciphertext(path,'0'*64)
    def test_completion_modules_wrap_only_new_release_instance(self):
        value=sample();value['sources']['controller']='def require_pins(): pass\n'
        value['sources']['exports_binding']='def require_pins(): pass\n'
        value['sources']['release']='legacy_marker = True\n'
        actual=T.modules(value)
        self.assertIsInstance(actual['release'],T.CompletionRelease)
        self.assertTrue(actual['release'].legacy_marker)
        self.assertEqual(R.received_ciphertext.__module__,'naver_preview_release')


class IncomingDirectoryTests(unittest.TestCase):
    @contextmanager
    def filesystem(self,configure=None):
        # Exercise real descriptor-relative traversal in an isolated fake host root.
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'srv/metainc/ad-deploy-staging').mkdir(parents=True)
            (root/'opt').mkdir()
            wrong_owner=set()
            if configure:configure(root,wrong_owner)
            opened=os.open;fstat=os.fstat;chmod=os.fchmod;mkdir=os.mkdir;fsync=os.fsync
            def open_host(path,*args,**kwargs):
                return opened(root if path=='/' else path,*args,**kwargs)
            def host_stat(fd):
                info=fstat(fd);values=list(info)
                values[4]=501 if info.st_ino in wrong_owner else 0;values[5]=0
                return os.stat_result(values)
            with patch.object(T.os,'open',side_effect=open_host),patch.object(T.os,'fstat',side_effect=host_stat),\
                    patch.object(T.os,'geteuid',return_value=0),patch.object(T.os,'fchown') as chown,\
                    patch.object(T.os,'fchmod',wraps=chmod) as modes,patch.object(T.os,'mkdir',wraps=mkdir) as creates,\
                    patch.object(T.os,'fsync',wraps=fsync) as sync:
                yield root,chown,modes,creates,sync

    def incoming(self,*,validate_error=None,uid=0,baseline='a'*64):
        value=sample();value['package']={'baseline':'a'*64,'run_id':'38100000000'}
        C=SimpleNamespace(TARGET_COMMIT='f'*40,validate_package=Mock(side_effect=validate_error,return_value=value['package']))
        release=SimpleNamespace(ROOT=Path('/srv/metainc/ad-deploy-staging'),trusted_dir=Mock())
        host=SimpleNamespace(baseline=Mock(return_value=baseline))
        modules={'controller':C,'release':release,'host':SimpleNamespace(NativeHost=Mock(return_value=host))}
        with patch.object(T,'modules',return_value=modules),patch.object(T.os,'geteuid',return_value=uid),\
                patch.object(T,'_prepare_export_directories') as prepare:
            if validate_error or uid!=0 or baseline!='a'*64:
                with self.assertRaises(ValueError):T.execute(value,incoming=True)
                prepare.assert_not_called();release.trusted_dir.assert_not_called()
            else:
                calls=[]
                release.trusted_dir.side_effect=lambda *a,**k:calls.append(('trusted',a,k))
                prepare.side_effect=lambda:calls.append(('exports',))
                result=T.execute(value,incoming=True)
                self.assertEqual(result,{'ok':True,'stage':'incoming_ready','source_commit':'f'*40})
                self.assertEqual([row[0] for row in calls],['trusted','trusted','exports','trusted'])
                self.assertEqual(calls[-1][1],(release.ROOT/'incoming'/value['package']['run_id'],))
                self.assertEqual(calls[-1][2],{'mode':0o700,'new':True})
            return C,host

    def test_false_package_refuses_before_directory_or_baseline_effects(self):
        _,host=self.incoming(validate_error=ValueError('CODE_PACKAGE'))
        host.baseline.assert_not_called()

    def test_non_root_and_baseline_drift_refuse_before_directory_effects(self):
        _,host=self.incoming(uid=501);host.baseline.assert_not_called()
        self.incoming(baseline='b'*64)

    def test_incoming_creates_only_after_authorization_and_existing_root_checks(self):
        self.incoming()

    def test_missing_fixed_directories_created_exactly_and_second_call_idempotent(self):
        with self.filesystem() as (root,chown,modes,creates,sync):
            T._prepare_export_directories()
            for relative,mode in (('srv/metainc/ad-deploy-staging/saved-exports',0o700),
                    ('opt/metainc',0o755),('opt/metainc/naver-saved-exports',0o755)):
                self.assertEqual((root/relative).stat().st_mode&0o7777,mode)
            self.assertEqual(creates.call_count,3);self.assertEqual(chown.call_count,3)
            self.assertEqual(modes.call_count,3);self.assertEqual(sync.call_count,6)
            creates.reset_mock();chown.reset_mock();modes.reset_mock();sync.reset_mock()
            T._prepare_export_directories()
            creates.assert_not_called();chown.assert_not_called();modes.assert_not_called();sync.assert_not_called()

    def test_non_root_helper_never_opens_or_creates_a_path(self):
        with patch.object(T.os,'geteuid',return_value=501),patch.object(T.os,'open') as opened,patch.object(T.os,'mkdir') as mkdir:
            with self.assertRaisesRegex(ValueError,'COMPLETION_EXPORT_DIRECTORY'):T._prepare_export_directories()
            opened.assert_not_called();mkdir.assert_not_called()

    def test_wrong_existing_mode_at_each_fixed_directory_refuses_without_repair(self):
        for relative in ('srv/metainc/ad-deploy-staging/saved-exports','opt/metainc','opt/metainc/naver-saved-exports'):
            def configure(root,owners):
                path=root/relative;path.mkdir(parents=True);path.chmod(0o750)
                if relative.endswith('/naver-saved-exports'):(root/'opt/metainc').chmod(0o755)
            with self.subTest(path=relative),self.filesystem(configure) as (root,chown,modes,creates,sync):
                with self.assertRaisesRegex(ValueError,'COMPLETION_EXPORT_DIRECTORY'):T._prepare_export_directories()
                creates.assert_not_called();chown.assert_not_called();modes.assert_not_called();sync.assert_not_called()

    def test_bad_ancestor_owner_or_writable_mode_prevents_either_leaf_creation(self):
        for issue in ('owner','writable'):
            def configure(root,owners):
                if issue=='owner':owners.add((root/'opt').stat().st_ino)
                else:(root/'opt').chmod(0o777)
            with self.subTest(issue=issue),self.filesystem(configure) as (root,chown,modes,creates,sync):
                with self.assertRaisesRegex(ValueError,'COMPLETION_EXPORT_DIRECTORY'):T._prepare_export_directories()
                self.assertFalse((root/'srv/metainc/ad-deploy-staging/saved-exports').exists())
                creates.assert_not_called();chown.assert_not_called();modes.assert_not_called()

    def test_symlink_leaf_or_ancestor_is_not_followed_or_repaired(self):
        for relative in ('srv/metainc/ad-deploy-staging/saved-exports','opt/metainc'):
            def configure(root,owners):
                target=root/'outside';target.mkdir();(root/relative).symlink_to(target,target_is_directory=True)
            with self.subTest(path=relative),self.filesystem(configure) as (root,chown,modes,creates,sync):
                with self.assertRaisesRegex(ValueError,'COMPLETION_EXPORT_DIRECTORY'):T._prepare_export_directories()
                self.assertEqual(list((root/'outside').iterdir()),[])
                creates.assert_not_called();chown.assert_not_called();modes.assert_not_called()

    def test_missing_unapproved_ancestor_is_not_created(self):
        def configure(root,owners):(root/'opt').rmdir()
        with self.filesystem(configure) as (root,chown,modes,creates,sync):
            with self.assertRaisesRegex(ValueError,'COMPLETION_EXPORT_DIRECTORY'):T._prepare_export_directories()
            self.assertFalse((root/'opt').exists());creates.assert_not_called();chown.assert_not_called();modes.assert_not_called()


class CodecTests(unittest.TestCase):
    def test_exact_roundtrip_preserves_source_utf8_and_all_operation_packages(self):
        for operation in T.FUNCTIONS:
            value=sample();value['operation']=operation
            value['approved_config_operation_id']=value['approved_config_operation_id'] if operation.endswith('prepare') else None
            value['package']={'name':'한글','zero':0,'missing':None}
            self.assertEqual(T.decode(T.encode(value)),value)
    def test_unknown_routes_types_extra_fields_and_boolean_version_refuse(self):
        for changed in ({'operation':'preview-code-only-upgrade'},{'operation':[]},{'version':True},{'sources':{}},{'extra':1}):
            with self.subTest(changed=changed),self.assertRaises(ValueError):T.encode({**sample(),**changed})
    def test_xz_bomb_truncation_concatenation_and_wire_size_refuse(self):
        valid=T.encode(sample());body=base64.b64decode(valid[len(T.PREFIX):])
        for wire in (packed(b'x'*(T.MAX_JSON+1)),T.PREFIX+base64.b64encode(body[:-1]).decode(),
            T.PREFIX+base64.b64encode(body+body).decode(),T.PREFIX+'A'*T.MAX_WIRE,'gzip-v1:'+valid):
            with self.subTest(size=len(wire)),self.assertRaises((ValueError,lzma.LZMAError)):T.decode(wire)
    def test_duplicate_json_keys_refuse(self):
        with self.assertRaisesRegex(ValueError,'COMPLETION_DUPLICATE'):T.decode(packed(b'{"version":1,"version":1}'))
    def test_compaction_keeps_string_literal_and_ast_exact(self):
        source='"""docstring"""\n# comment\nx = " preserved  text "\n\ndef f():\n    return x\n'
        actual=T.compact(source)
        self.assertEqual(ast.dump(ast.parse(actual)),ast.dump(ast.parse(source)))
        self.assertIn('" preserved  text "',actual)
    def test_final_source_manifest_assets_and_export_pins_fit_closed_new_envelope(self):
        root=Path(__file__).parents[1]/'tools'
        p=json.loads(Path(__file__).with_name('fixtures').joinpath('completion-source-pins.json').read_text())
        source={n:(root/f).read_text() if n in ('exports_helper','product_exporter','market_exporter') else T.compact((root/f).read_text()) for n,f in T.SOURCE_FILES.items()}
        assets={}
        for name,row in p['manifest'].items():
            if name.startswith('backend/naver_page/') and name.endswith(('.js','.css','.gz')):
                mime='application/gzip' if name.endswith('.gz') else 'text/css; charset=utf-8' if name.endswith('.css') else 'text/javascript; charset=utf-8'
                assets['/naver/'+name.removeprefix('backend/naver_page/')]=(row[1],row[2],mime)
        values={'TARGET_COMMIT':p['source_commit'],'TARGET_SOURCE_SHA256':p['canonical']['gzip_sha256'],
            'STORE_SHA256':{'old':p['old_manifest']['naver_engine/store.py'][2],'target':p['manifest']['naver_engine/store.py'][2]},
            'OLD_MANIFEST':{k:tuple(v) for k,v in p['old_manifest'].items()},'TARGET_MANIFEST':{k:tuple(v) for k,v in p['manifest'].items()},
            'REPORT_ASSETS':assets,'SCHEMA_SHA256':p['schema_sha256'],
            'CI_PROOF':{'source_commit':p['source_commit'],'tooling_head':'a'*40,'run_id':'38175897274','receipt_sha256':'b'*64}}
        source['controller']+='\n'+'\n'.join(k+' = '+repr(v) for k,v in values.items())+'\n'
        scripts={name:(root.parent/name).read_bytes() for name in ('naver_product_export.py','naver_market_export.py')}
        pins={'plan':{'ops_commit':'c'*40,'source_directory':'/root/logic-analysis-deploy/data','database_name':'logic_data.db',
            'exporter_user':'naver-saved-export','source_group':None,'python_executable':'/usr/bin/python3'},
            'helper_sha256':hashlib.sha256((root/'naver_saved_exports.py').read_bytes()).hexdigest(),
            'scripts':{k:hashlib.sha256(v).hexdigest() for k,v in scripts.items()},'companion_sha256':'d'*64}
        source['exports_binding']+='\nPINS = '+repr(pins)+'\n'
        value=sample();value['sources']=source;value['package']={'baseline':'a'*64,'source_commit':p['source_commit'],
            'ciphertext_sha256':'b'*64,'source_tar_gz_sha256':p['canonical']['gzip_sha256'],'run_id':'38175897274','operation':'code-prepare'}
        wire=T.encode(value);self.assertEqual(T.decode(wire),value)
        self.assertLessEqual(len(json.dumps(value,separators=(',',':')).encode()),T.MAX_JSON)
        self.assertLessEqual(len(wire),T.MAX_WIRE)
        bootstrap=base64.b64encode((root/'naver_completion_transport.py').read_bytes()).decode()
        self.assertLessEqual(len(bootstrap),32768)
        # Linux execve per-string bound is 128KiB: each quoted export remains below it.
        self.assertLess(len('COMPLETION_B64='+wire),128*1024)
        self.assertLess(len('COMPLETION_TRANSPORT_B64='+bootstrap),128*1024)
        self.assertLess(len("export COMPLETION_B64='"+wire+"'; export COMPLETION_TRANSPORT_B64='"+bootstrap+"';\n"),128*1024)
        workflow,_,require=workflow_ssh_pressure()
        ssh_bytes=require(wire,bootstrap,workflow)
        self.assertTrue(all(size<131072 for size in ssh_bytes))
        print(json.dumps({'completion_pressure_fixture':True,'raw_bytes':len(json.dumps(value,separators=(',',':')).encode()),'wire_bytes':len(wire),
            'bootstrap_bytes':len(bootstrap),'ssh_command_bytes':ssh_bytes,'actual_credentials':False,'native_ci_proof':'synthetic_placeholder'}))

    def test_pending_binding_refuses_before_source_or_host_io(self):
        with patch.object(E,'PINS',None),patch.object(E.Path,'read_bytes') as read:
            with self.assertRaisesRegex(ValueError,'COMPLETION_EXPORTS_UNPINNED'):E.Binding(Mock(),Mock(),Mock(),b'x',{})
            read.assert_not_called()
    def test_controller_pending_refuses_before_host_modules_execute(self):
        value=sample();value['sources']['controller']='def require_pins():\n raise ValueError("CODE_TARGET_NOT_PINNED")\n'
        for key in value['sources']:
            if key!='controller':value['sources'][key]='raise AssertionError("HOST_MUST_NOT_EXECUTE")'
        with self.assertRaisesRegex(ValueError,'CODE_TARGET_NOT_PINNED'):T.modules(value)
        with patch.object(T.os,'open') as opened,patch.object(T.os,'mkdir') as mkdir:
            with self.assertRaisesRegex(ValueError,'CODE_TARGET_NOT_PINNED'):T.execute(value,incoming=True)
            opened.assert_not_called();mkdir.assert_not_called()
    def test_exporter_original_bytes_are_not_executed_as_modules(self):
        value=sample();value['sources']['controller']='def require_pins(): pass\n';value['sources']['exports_binding']='def require_pins(): pass\n'
        for key in ('product_exporter','market_exporter'):value['sources'][key]='raise AssertionError("EXPORTER_MUST_NOT_EXECUTE")'
        modules=T.modules(value)
        self.assertNotIn('product_exporter',modules);self.assertNotIn('market_exporter',modules)
    def test_companion_only_exact_target_engine_and_private_receipt_rechecked_each_time(self):
        helper=SimpleNamespace(COMPANION='naver-saved-exports.override.yml',_prepared=Mock(return_value=({},Path('/private/operation'),{})))
        release=SimpleNamespace(compose=Mock(side_effect=lambda path,name:['docker','compose','-f',str(path/name)]))
        proxy=E.ReleaseProxy(release,helper,{'exact':'receipt'},'f'*40)
        for path,name in ((Path('/releases/naver-'+'e'*40),'engine'),(Path('/releases/naver-'+'f'*40),'relay')):
            self.assertEqual(proxy.compose(path,name),['docker','compose','-f',str(path/name)])
        helper._prepared.assert_not_called()
        result=proxy.compose(Path('/releases/naver-'+'f'*40),'engine')
        self.assertEqual(result[-2:],['-f','/private/operation/naver-saved-exports.override.yml'])
        helper._prepared.assert_called_once_with({'exact':'receipt'})
    def test_installer_runs_after_controller_preflight_before_build_and_receipt_after_success(self):
        value=sample();calls=[]
        binding=Mock();binding.prepare.side_effect=lambda p:calls.append('stage') or 'wrapped'
        binding.install.side_effect=lambda:calls.append('install');binding.save.side_effect=lambda p:calls.append('save')
        C=controller_fixture(TARGET_COMMIT='f'*40)
        def prepare(*args,**kwargs):
            calls.append('preflight');kwargs['prepare_exports']();calls.append('build');return {'ok':True,'services_started':False}
        C.prepare=prepare
        module=SimpleNamespace(Binding=Mock(return_value=binding))
        m={'controller':C,'release':Mock(),'host':SimpleNamespace(NativeHost=Mock()),'exports_binding':module,'exports_helper':Mock(),'lifecycle':Mock(),'upgrade':Mock()}
        with patch.object(T,'modules',return_value=m):result=T.execute(value)
        self.assertEqual(calls,['stage','preflight','install','build','save'])
        self.assertTrue(result['export_jobs_started']);self.assertFalse(result['services_started'])
    def test_rejected_or_unproven_apply_and_rollback_do_not_remove_live_exports(self):
        for operation,code in (('preview-completion-apply','CODE_ALREADY_ATTEMPTED'),('preview-completion-rollback','CODE_ROLLBACK_OPERATION_ID'),
                ('preview-completion-apply','CODE_ROLLBACK_FAILED')):
            value=sample();value.update(operation=operation,approved_config_operation_id=None,package={'release':{}})
            binding=Mock();C=controller_fixture(TARGET_COMMIT='f'*40)
            setattr(C,T.FUNCTIONS[operation],Mock(side_effect=RuntimeError(code)))
            m={'controller':C,'release':Mock(),'host':SimpleNamespace(NativeHost=Mock()),'exports_binding':SimpleNamespace(Binding=Mock(return_value=binding)),
                'exports_helper':Mock(),'lifecycle':Mock(),'upgrade':Mock()}
            with patch.object(T,'modules',return_value=m),self.assertRaisesRegex(RuntimeError,code):T.execute(value)
            binding.rollback.assert_not_called()
    def test_only_verified_old_recovery_or_successful_explicit_rollback_removes_exports(self):
        for operation in ('preview-completion-apply','preview-completion-rollback'):
            value=sample();value.update(operation=operation,approved_config_operation_id=None,package={'release':{}})
            binding=Mock();C=controller_fixture(TARGET_COMMIT='f'*40)
            setattr(C,T.FUNCTIONS[operation],Mock(side_effect=RuntimeError('CODE_FAILED_ROLLED_BACK_DB_PRESERVED')) if operation.endswith('apply') else Mock(return_value={'ok':True}))
            m={'controller':C,'release':Mock(),'host':SimpleNamespace(NativeHost=Mock()),'exports_binding':SimpleNamespace(Binding=Mock(return_value=binding)),
                'exports_helper':Mock(),'lifecycle':Mock(),'upgrade':Mock()}
            with patch.object(T,'modules',return_value=m):
                if operation.endswith('apply'):
                    with self.assertRaisesRegex(RuntimeError,'CODE_FAILED_ROLLED_BACK_DB_PRESERVED'):T.execute(value)
                else:self.assertEqual(T.execute(value),{'ok':True})
            binding.rollback.assert_called_once()

    def test_failed_prepare_does_not_publish_binding_and_cleanup_is_attempted(self):
        value=sample();binding=Mock();C=controller_fixture(prepare=Mock(side_effect=ValueError('SYNTHETIC')),TARGET_COMMIT='f'*40)
        m={'controller':C,'release':Mock(),'host':SimpleNamespace(NativeHost=Mock()),'exports_binding':SimpleNamespace(Binding=Mock(return_value=binding)),
            'exports_helper':Mock(),'lifecycle':Mock(),'upgrade':Mock()}
        with patch.object(T,'modules',return_value=m),self.assertRaisesRegex(ValueError,'SYNTHETIC'):T.execute(value)
        binding.save.assert_not_called();binding.rollback.assert_called_once()


class CompletionFailurePropagationTests(unittest.TestCase):
    def setUp(self):
        self.actual=controller_fixture(TARGET_COMMIT='f'*40)
        self.reporter=controller_fixture(TARGET_COMMIT='f'*40)
        self.binding=Mock()
        self.factory=Mock(return_value=self.binding)
        self.modules={'controller':self.actual,'release':Mock(),
            'host':SimpleNamespace(NativeHost=Mock()),
            'exports_binding':SimpleNamespace(Binding=self.factory),
            'exports_helper':Mock(),'lifecycle':Mock(),'upgrade':Mock()}

    def run_failure(self,error,*,operation='preview-completion-prepare'):
        value=sample()
        if operation!='preview-completion-prepare':
            value.update(operation=operation,approved_config_operation_id=None,package={'release':{}})
        with patch.object(T,'modules',return_value=self.modules),self.assertRaises(type(error)) as caught:
            T.execute(value)
        self.assertIs(caught.exception,error)
        self.assertEqual(self.reporter.STAGE,'input')
        return self.reporter.failure_report(error)

    def test_distinct_reporter_preserves_actual_prepare_stage_before_cleanup_changes_it(self):
        stages=('code_prepare_preflight','code_build_engine','code_build_relay',
            'code_config_engine','code_config_relay','code_check_config','code_prepare_postflight')
        for stage in stages:
            with self.subTest(stage=stage):
                error=ValueError('COMMAND_FAILED')
                def prepare(*args,**kwargs):
                    self.actual.STAGE=stage;self.actual.OPERATION='package'
                    raise error
                self.actual.prepare=prepare
                self.binding.rollback.side_effect=lambda:setattr(self.actual,'STAGE','code_rollback')
                report=self.run_failure(error)
                self.assertEqual(report,{'stage':'input','error_kind':'ValueError','error_code':'COMMAND_FAILED',
                    'failed_stage':stage,'failed_operation':'package',
                    'failed_error_kind':'ValueError','failed_error_code':'COMMAND_FAILED'})
                self.binding.save.assert_not_called()

    def test_binding_constructor_and_staging_failures_preserve_distinct_actual_phases(self):
        for phase in ('saved_exports_binding','saved_exports_prepare'):
            with self.subTest(phase=phase):
                self.factory.reset_mock(side_effect=True);self.binding.reset_mock(side_effect=True)
                self.factory.return_value=self.binding
                error=ValueError('EXPORT_PIN')
                if phase=='saved_exports_binding':self.factory.side_effect=error
                else:self.binding.prepare.side_effect=error
                report=self.run_failure(error)
                self.assertEqual(report['failed_stage'],phase)
                self.assertEqual(report['failed_error_code'],'EXPORT_PIN')
                if phase=='saved_exports_binding':self.binding.rollback.assert_not_called()
                else:self.binding.rollback.assert_called_once()

    def test_cleanup_error_carries_original_closed_details_and_its_own_failure(self):
        original=ValueError('EXPORT_COMMAND_FAILED')
        original.failure_details={'export_command_stage':'product_start',
            'export_command_issue':'namespace','export_command_status':1,
            'raw':'must-never-be-published'}
        cleanup=ValueError('EXPORT_ROLLBACK_DRIFT')
        cleanup.failure_details={'export_command_stage':'market_stop','export_command_issue':'command_failed',
            'export_command_status':2,'raw':'also-private'}
        def prepare(*args,**kwargs):
            self.actual.STAGE='saved_exports_install'
            raise original
        def rollback():
            self.actual.STAGE='code_rollback';self.actual.OPERATION='restore_database'
            raise cleanup
        self.actual.prepare=prepare;self.binding.rollback.side_effect=rollback
        report=self.run_failure(cleanup)
        self.assertEqual(report,{'stage':'input','error_kind':'ValueError','error_code':'EXPORT_ROLLBACK_DRIFT',
            'failed_stage':'saved_exports_install','failed_operation':'none',
            'failed_error_kind':'ValueError','failed_error_code':'EXPORT_COMMAND_FAILED',
            'cleanup_stage':'code_rollback','cleanup_operation':'restore_database',
            'cleanup_error_kind':'ValueError','cleanup_error_code':'EXPORT_ROLLBACK_DRIFT',
            'export_command_stage':'product_start','export_command_issue':'namespace','export_command_status':1})
        self.assertNotIn('raw',cleanup.failure_details)
        self.binding.save.assert_not_called()

    def test_existing_original_and_rollback_details_are_not_replaced_by_transport_stage(self):
        original=RuntimeError('CODE_FAILED_ROLLED_BACK_DB_PRESERVED')
        original.failure_details={'failed_stage':'account_sources_warm','failed_operation':'warm_result',
            'failed_error_kind':'ValueError','failed_error_code':'SOURCE_WARM_FAILED',
            'rollback_stage':'code_rollback','rollback_operation':'restore_database',
            'rollback_error_kind':'ValueError','rollback_error_code':'DB_SNAPSHOT_CHANGED'}
        self.actual.apply=Mock(side_effect=original)
        report=self.run_failure(original,operation='preview-completion-apply')
        for key,value in original.failure_details.items():self.assertEqual(report[key],value)
        self.assertEqual(report['failed_stage'],'account_sources_warm')
        self.assertEqual(report['rollback_error_code'],'DB_SNAPSHOT_CHANGED')


if __name__=='__main__':unittest.main()
