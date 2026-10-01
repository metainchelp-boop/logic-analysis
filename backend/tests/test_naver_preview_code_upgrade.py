import importlib.util
import ast
import base64
import gzip
import io
import json
import random
import shlex
import tarfile
import textwrap
import tempfile
from pathlib import Path
import unittest
import zlib
from unittest.mock import Mock, patch
import test_naver_preview_upgrade as legacy_test


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1]/'tools'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractTest(unittest.TestCase):
    def workflow_transport(self):
        workflow=(Path(__file__).parents[2]/'.github/workflows/debug-rank.yml').read_text()
        scripts=[];source=None
        for line in workflow.splitlines():
            if line.rstrip().endswith("<<'PY'"):
                source=[]
            elif source is not None:
                if line.strip()=='PY':
                    scripts.append(textwrap.dedent('\n'.join(source)));source=None
                else:
                    source.append(line)
        namespaces=[]
        for script,name in zip(scripts[:2],('encode_ops','decode_ops')):
            nodes=[node for node in ast.parse(script).body
                   if isinstance(node,(ast.Import,ast.ImportFrom))
                   or isinstance(node,ast.FunctionDef) and node.name==name]
            self.assertTrue(any(isinstance(node,ast.FunctionDef) for node in nodes),name)
            namespace={}
            exec(compile(ast.Module(body=nodes,type_ignores=[]),'<workflow-transport>','exec'),namespace)
            namespaces.append(namespace[name])
        self.assertIn("stream.write('PREVIEW_OPS_B64='+encode_ops(bundle)+'\\n')",scripts[0])
        self.assertIn("bundle=decode_ops(os.environ['PREVIEW_OPS_B64'])",scripts[1])
        return *namespaces,scripts[1]

    def test_code_upgrade_transport_roundtrip_preserves_full_bundle_and_shell_bound(self):
        encode,decode,script=self.workflow_transport()
        tools=Path(__file__).parents[1]/'tools'
        names={'source':'naver_preview_code_upgrade','release_source':'naver_preview_release',
               'host_source':'naver_erp_tunnel_service_install','lifecycle_source':'naver_preview_lifecycle',
               'upgrade_source':'naver_preview_upgrade'}
        bundle={key:(tools/(name+'.py')).read_text() for key,name in names.items()}
        bundle.update(operation='preview-code-upgrade',function='apply',package={
            'release':dict(baseline='a'*64,source_commit='b'*40,ciphertext_sha256='c'*64,
                          source_tar_gz_sha256='d'*64,run_id='9'*20,operation='code-prepare'),
            'operation_id':'e'*32})
        encoded=encode(bundle)
        self.assertTrue(encoded.startswith('code-gzip-v1:'))
        self.assertEqual(decode(encoded),bundle)
        shell="export PREVIEW_OPS_B64="+shlex.quote(encoded)+";\nset -eu\n/usr/bin/python3 -I -B - <<'PY'\n"+script+'\nPY\n'
        self.assertLess(len(('/bin/bash -c '+shlex.quote(shell)).encode()),120000)
        self.assertLessEqual(len(encoded),65536)

    def test_transport_keeps_other_operations_byte_identical_and_code_mode_exact(self):
        encode,decode,_=self.workflow_transport()
        for operation in ('preview-upgrade','preview-status','preview-backup','preview-publish'):
            bundle=dict(operation=operation,function='apply',package={'fixture':'unchanged'})
            encoded=base64.b64encode(json.dumps(bundle).encode()).decode()
            self.assertEqual(encode(bundle),encoded)
            self.assertEqual(decode(encoded),bundle)
            compressed='code-gzip-v1:'+base64.b64encode(gzip.compress(json.dumps(bundle).encode())).decode()
            with self.assertRaisesRegex(ValueError,'CODE_OPS_OPERATION'):
                decode(compressed)
        bundle=dict(operation='preview-code-upgrade',function='apply',package={})
        with self.assertRaisesRegex(ValueError,'CODE_OPS_ENCODING'):
            decode(base64.b64encode(json.dumps(bundle).encode()).decode())
        with self.assertRaisesRegex(ValueError,'CODE_OPS_OPERATION'):
            decode(encode(dict(bundle,function='run')))

    def test_transport_rejects_oversize_corrupt_truncated_and_trailing_gzip(self):
        encode,decode,_=self.workflow_transport()
        bundle=dict(operation='preview-code-upgrade',function='apply',package={})
        packed=gzip.compress(json.dumps(bundle).encode())
        bad=[packed[:-1],packed+b'private-tail',packed+packed,
             gzip.compress(b' '*131073),b'invalid-gzip']
        for data in bad:
            with self.subTest(size=len(data)),self.assertRaises((ValueError,zlib.error)):
                decode('code-gzip-v1:'+base64.b64encode(data).decode())
        for encoded in ('code-gzip-v1:!!!','code-gzip-v1:'+'A'*65536):
            with self.assertRaises(ValueError):
                decode(encoded)
        with self.assertRaisesRegex(ValueError,'CODE_OPS_JSON_SIZE'):
            encode(dict(bundle,source='x'*131072))
        with self.assertRaisesRegex(ValueError,'CODE_OPS_WIRE_SIZE'):
            encode(dict(bundle,source=random.Random(0).randbytes(60000).hex()))

    def test_target_probe_requires_authentication_only_for_new_verified_routes(self):
        code = load('naver_preview_code_upgrade')
        release = Mock()
        def read(path, route, method='GET'):
            if route == '/_engine/health':
                return 200, {}, b'{}'
            if route == '/naver/':
                return 200, {'referrer-policy': 'no-referrer', 'cache-control': 'no-store'}, b'verificationNotice'
            approved = ('/api/naver-auto/links/confirm', '/api/naver-auto/collection/request')
            return (401 if method == 'GET' or route in approved else 403), {}, b''
        release.unix_request.side_effect = read
        code.probe(release, code.TARGET_COMMIT, load('naver_preview_upgrade'))
        calls = {(args[1], args[2] if len(args) > 2 else 'GET')
                 for args, _ in release.unix_request.call_args_list}
        self.assertTrue({('/api/naver-auto/links/confirm', 'POST'),
                         ('/api/naver-auto/collection/request', 'POST'),
                         ('/api/naver-auto/collection/status', 'GET'),
                         ('/api/naver-auto/issues/1/ack', 'POST'),
                         ('/api/naver-auto/settings/thresholds', 'POST')} <= calls)

    def test_probe_distinguishes_exact_old_and_target_auth_contracts(self):
        code = load('naver_preview_code_upgrade')
        for source, confirm, accepted in ((code.OLD_COMMIT, 403, True),
                (code.OLD_COMMIT, 401, False), (code.TARGET_COMMIT, 401, True),
                (code.TARGET_COMMIT, 403, False), (code.TARGET_COMMIT, 200, False)):
            with self.subTest(source=source, confirm=confirm):
                release = Mock()
                def read(path, route, method='GET'):
                    if route == '/_engine/health':
                        return 200, {}, b'{}'
                    if route == '/naver/':
                        return 200, {'referrer-policy':'no-referrer','cache-control':'no-store'}, b'verificationNotice'
                    if route == '/api/naver-auto/links/confirm':
                        return confirm, {}, b''
                    return (401 if method == 'GET' or route.endswith('/collection/request') else 403), {}, b''
                release.unix_request.side_effect = read
                if accepted:
                    code.probe(release, source, load('naver_preview_upgrade'))
                else:
                    with self.assertRaises(ValueError):
                        code.probe(release, source, load('naver_preview_upgrade'))

    def test_target_probe_rejects_each_wrong_route_status_and_health_contract(self):
        code = load('naver_preview_code_upgrade')
        routes = {'/me':401, '/collection/status':401, '/links/confirm':401,
                  '/collection/request':401, '/issues/1/ack':403, '/issues/1/resolve':403,
                  '/issues/1/except':403, '/settings/thresholds':403, '/links/reject':403,
                  '/links/revoke':403, '/links/preview':403, '/bell/1/read':403, '/bell/read-all':403}
        cases = [(route, value) for route, expected in routes.items()
                 for value in (200, 403 if expected == 401 else 401)]
        cases += [('/_engine/health', 'invalid'), ('/naver/', 'header'), ('/naver/', 'body')]
        for changed, wrong in cases:
            with self.subTest(route=changed, response=wrong):
                release = Mock()
                def read(path, route, method='GET'):
                    if route == '/_engine/health':
                        return 200, {}, b'[]' if changed == route else b'{}'
                    if route == '/naver/':
                        headers = {'referrer-policy':'no-referrer','cache-control':'no-store'}
                        return (200, {} if changed == route and wrong == 'header' else headers,
                                b'wrong' if changed == route and wrong == 'body' else b'verificationNotice')
                    key = route.removeprefix('/api/naver-auto')
                    return (wrong if changed == key else routes[key]), {}, b''
                release.unix_request.side_effect = read
                with self.assertRaises(ValueError):
                    code.probe(release, code.TARGET_COMMIT, load('naver_preview_upgrade'))

    def test_unknown_or_mismatched_source_refuses_before_any_probe(self):
        code = load('naver_preview_code_upgrade')
        release = Mock()
        for source in (None, '', 'c'*40):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'CODE_PROBE_SOURCE'):
                code.probe(release, source, load('naver_preview_upgrade'))
        for source in (code.OLD_COMMIT, code.TARGET_COMMIT, 'c'*40):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'CODE_PROBE_SOURCE'):
                code.verify_running(Path('/wrong-release'), {'source_commit':source}, release, Mock(), Mock())
        release.unix_request.assert_not_called()

    def test_only_exact_approved_code_transition_is_accepted_without_bootstrap_request(self):
        module = load('naver_preview_code_upgrade')
        module.TARGET_COMMIT = 'b'*40  # A sealed target is supplied only in the fixture.
        release = load('naver_preview_release')
        package = dict(baseline=module.EXPECTED_BASELINE, source_commit=module.TARGET_COMMIT,
                       ciphertext_sha256='b'*64, source_tar_gz_sha256='c'*64,
                       run_id='123456', operation='code-prepare')
        self.assertEqual(module.validate_package(package, release), package)
        for changes in ({'source_commit': module.OLD_COMMIT}, {'operation': 'upgrade-prepare'},
                        {'request': {}}, {'source_commit': 'f'*40}, {'baseline': 'd'*64}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                module.validate_package(dict(package, **changes), release)
        host = Mock()
        with self.assertRaises(ValueError):
            module.apply({'release': package, 'request': {}}, host, release, Mock(), Mock())
        host.assert_not_called()

    def test_unsealed_or_same_as_old_target_refuses_before_any_action(self):
        module = load('naver_preview_code_upgrade')
        release = load('naver_preview_release')
        package = dict(baseline=module.EXPECTED_BASELINE, source_commit='b'*40,
                       ciphertext_sha256='c'*64, source_tar_gz_sha256='d'*64,
                       run_id='123456', operation='code-prepare')
        for target in (None, '', module.OLD_COMMIT):
            with self.subTest(target=target), patch.object(module, 'TARGET_COMMIT', target):
                with self.assertRaisesRegex(ValueError, 'CODE_TARGET_NOT_PINNED'):
                    module.validate_package(package, release)

    def test_only_reviewed_runtime_and_bundled_test_paths_are_allowlisted(self):
        module = load('naver_preview_code_upgrade')
        self.assertEqual(module.CODE_PATHS, {
            'naver_engine/web.py', 'naver_engine/sync.py',
            'naver_runtime/__main__.py', 'naver_runtime/writer.py',
            'naver_runtime/scheduler.py', 'naver_runtime/collection_requests.py',
            'backend/naver_page/app.js', 'backend/naver_page/index.html'})
        self.assertEqual(module.TEST_PATHS, {
            'naver_engine/tests/test_verified_collection.py',
            'naver_engine/tests/test_verified_collection_screen.py',
            'naver_engine/tests/verified_collection_browser.js',
            'naver_runtime/tests/test_collection_requests.py',
            'naver_runtime/tests/test_collection_integration.py'})

    def scenario(self, failure=None, mode='apply'):
        code = load('naver_preview_code_upgrade')
        fixture = load('naver_preview_upgrade')
        fixture.OLD_COMMIT = code.OLD_COMMIT
        # Shared synthetic Docker/filesystem adapter, not the old controller.
        def prepare(package, host, release, life):
            package = dict(package, source_commit=code.TARGET_COMMIT, operation='code-prepare')
            return code.prepare(package, host, release, life, fixture)
        def apply(package, host, release, life):
            package = {'release': dict(package['release'], source_commit=code.TARGET_COMMIT,
                                      operation='code-prepare'), 'operation_id': '9'*32}
            return code.apply(package, host, release, life, fixture)
        fixture.prepare, fixture.apply = prepare, apply
        def setup(root, release):
            infrastructure = {'Dockerfile.naver-engine': b'FROM fixture', 'Dockerfile.naver-relay': b'FROM fixture',
                'backend/requirements.txt': b'fixture', 'naver_runtime/bootstrap.py': b'# unchanged bootstrap',
                'naver_engine/store.py': b'SCHEMA_VERSION=7\n_SCHEMA=("CREATE TABLE fixture (id INTEGER)",)\ndef _migrate():\n    pass\n'}
            infrastructure.update({name: b'new fixture compose' for name in
                ('compose.naver-engine.yml','compose.naver-relay.yml','deploy/naver-engine-backup.override.yml')})
            for path in (root/'releases').iterdir():
                for name, body in infrastructure.items():
                    target = path/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(body)
                for name in ('engine','relay'):
                    (path/('preview-'+name+'.override.yml')).write_text('image: '+path.name.removeprefix('naver-'))
                receipt = root/'receipts'/('preview-'+path.name.removeprefix('naver-')+'.json')
                if receipt.exists():
                    value = json.loads(receipt.read_text())
                    value['files'] = {name: release.sha(Path(name).read_bytes()) for name in value['files']}
                    receipt.write_text(json.dumps(value))
            request = root/'bootstrap-request.json'
            if failure in ('bootstrap_pending','bootstrap_changed'):
                request.write_text('existing')
            if request.exists():
                request.write_text(json.dumps({'request_id':'7'*32}))
                folder = root/'bootstrap';folder.mkdir()
                for suffix, status in (('.json','started'),('.result.json','completed')):
                    (folder/('bootstrap-'+'7'*32+suffix)).write_text(json.dumps({'request_id':'7'*32,'status':status}))
                if failure=='bootstrap_pending':
                    (folder/('bootstrap-'+'7'*32+'.result.json')).unlink()
            previous_payload = release.validate_payload
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode='w:gz') as stream:
                for name, body in infrastructure.items():
                    item=tarfile.TarInfo(name);item.size=len(body);item.mode=0o644
                    stream.addfile(item,io.BytesIO(body))
            release.validate_payload=lambda *args:(archive.getvalue(),previous_payload(*args)[1])
            def extract(source, path):
                path.mkdir()
                for name, body in infrastructure.items():
                    target=path/name;target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(body)
            release.extract_source=extract
            current={'source':code.OLD_COMMIT}
            execute, request_api=release.command,release.unix_request
            def track(args,**kwargs):
                result=execute(args,**kwargs)
                if '--force-recreate' in args:
                    current['source']=Path(args[5]).parent.name.removeprefix('naver-')
                return result
            def request_api_by_code(path,route,method='GET'):
                if current['source']==code.OLD_COMMIT and failure=='probe' and method=='POST':
                    return 403,{},b''
                if (current['source']==code.TARGET_COMMIT and method=='POST'
                        and route in ('/api/naver-auto/links/confirm','/api/naver-auto/collection/request')
                        and failure not in ('probe','rollback_recreate')):
                    return 401,{},b''
                return request_api(path,route,method)
            release.command,release.unix_request=track,request_api_by_code
            target=root/'releases'/('naver-'+'b'*40)
            if failure=='schema':
                (target/'naver_engine/store.py').write_text('SCHEMA_VERSION=8\n_SCHEMA=()\ndef _migrate():\n    pass\n')
            if failure=='infrastructure':
                (target/'Dockerfile.naver-engine').write_text('FROM changed')
            if failure=='override':
                override=target/'preview-engine.override.yml';override.write_text('unapproved environment')
                receipt=root/'receipts'/('preview-'+'b'*40+'.json')
                value=json.loads(receipt.read_text());value['files'][str(override)]=release.sha(override.read_bytes())
                receipt.write_text(json.dumps(value))
            if failure=='bootstrap_changed':
                command=release.command
                def mutate(args, **kwargs):
                    result=command(args,**kwargs)
                    if args[:2]==['/usr/bin/systemctl','start']:
                        request.write_text(json.dumps({'request_id':'6'*32}))
                    return result
                release.command=mutate
            if failure=='old_source':
                receipt=root/'receipts'/('preview-'+code.OLD_COMMIT+'.json')
                value=json.loads(receipt.read_text());value['package']['source_tar_gz_sha256']='0'*64
                receipt.write_text(json.dumps(value))
            if failure=='unapproved_code':
                (target/'naver_runtime/bootstrap.py').write_text('# changed bootstrap')
            if failure=='unapproved_new':
                (target/'naver_runtime/unapproved.py').write_text('# outside approved scope')
        with patch.object(legacy_test, 'M', fixture), patch.object(code, 'TARGET_COMMIT', 'b'*40), \
                patch.object(code, 'EXPECTED_BASELINE', 'a'*64), \
                patch.object(code, 'OLD_SOURCE_SHA256', 'c'*64):
            return legacy_test.UpgradeTest().scenario(failure, mode, setup)

    def test_code_apply_preserves_existing_request_and_never_writes_a_new_one(self):
        result, commands, writes, _, state = self.scenario('replay')
        self.assertIsInstance(result, dict, str(result))
        self.assertTrue(result['ok'])
        self.assertEqual(state, {'engine': 'b'*40, 'relay': 'b'*40})
        self.assertFalse(any(path.name == 'bootstrap-request.json' for path, _ in writes))
        self.assertFalse(any('nginx' in ' '.join(args) for args in commands))

    def test_prepare_does_not_restart_services_or_touch_secrets_or_bootstrap(self):
        result, commands, writes, restored, state=self.scenario(mode='prepare')
        self.assertIsInstance(result,dict,str(result))
        self.assertFalse(result['services_started'])
        self.assertTrue(restored)
        self.assertEqual(state,{'engine':load('naver_preview_code_upgrade').OLD_COMMIT,
                                'relay':load('naver_preview_code_upgrade').OLD_COMMIT})
        self.assertFalse(any(args[:2] in (['/usr/bin/systemctl','start'],['/usr/bin/systemctl','stop']) for args in commands))
        self.assertFalse(any(path.name=='bootstrap-request.json' or path.parent.name=='secrets' for path,_ in writes))
        check=next(args for args in commands if 'check-config' in args)
        self.assertRegex(check[check.index('--project-name')+1],r'^naver-check-b{40}-[a-f0-9]{32}$')

    def test_schema_infrastructure_or_bootstrap_uncertainty_refuses_before_any_mutation(self):
        for reason in ('image','unit','manifest','schema','infrastructure','override','bootstrap_pending',
                       'old_source','unapproved_code','unapproved_new'):
            with self.subTest(reason=reason):
                result,commands,writes,_,_=self.scenario(reason)
                self.assertIsInstance(result,Exception)
                self.assertEqual(writes,[])
                self.assertFalse(any(args[:2]==['/usr/bin/systemctl','stop'] for args in commands))

    def test_code_scope_only_allows_exact_paths_and_no_deletions_or_unsafe_files(self):
        module=load('naver_preview_code_upgrade')
        upgrade=Mock()
        upgrade.read_file.side_effect=lambda path,**kwargs: Path(path).read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            old=Path(folder).resolve()/'old';new=Path(folder).resolve()/'new'
            for root in (old,new):
                (root/'naver_runtime').mkdir(parents=True)
                (root/'naver_runtime/scheduler.py').write_bytes(b'old')
                (root/'naver_runtime/config.py').write_bytes(b'unchanged')
            (new/'naver_runtime/scheduler.py').write_bytes(b'new')
            added=new/'naver_runtime/collection_requests.py';added.write_bytes(b'approved')
            module.compatible_code_scope(old,new,upgrade)
            forbidden=new/'naver_runtime/config.py';forbidden.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):
                module.compatible_code_scope(old,new,upgrade)
            forbidden.write_bytes(b'unchanged')
            added.unlink();added.symlink_to(forbidden)
            with self.assertRaisesRegex(ValueError,'CODE_SOURCE_PATH'):
                module.compatible_code_scope(old,new,upgrade)
            added.unlink();(new/'naver_runtime/scheduler.py').unlink()
            with self.assertRaisesRegex(ValueError,'CODE_SOURCE_REMOVED'):
                module.compatible_code_scope(old,new,upgrade)

    def test_every_partial_failure_restores_exact_old_images_and_units(self):
        for reason in ('stop','recreate','start','probe'):
            with self.subTest(reason=reason):
                result,commands,writes,restored,state=self.scenario(reason)
                self.assertEqual(str(result),'CODE_FAILED_ROLLED_BACK_DB_PRESERVED')
                self.assertTrue(restored)
                old=load('naver_preview_code_upgrade').OLD_COMMIT
                self.assertEqual(state,{'engine':old,'relay':old})
                self.assertFalse(any(path.name=='bootstrap-request.json' for path,_ in writes))

    def test_rollback_failure_leaves_both_isolated_services_stopped(self):
        result,commands,_,_,_=self.scenario('rollback_recreate')
        self.assertEqual(str(result),'CODE_ROLLBACK_FAILED')
        self.assertEqual(commands[-2:], [['/usr/bin/systemctl','stop','metainc-naver-relay.service'],
                                        ['/usr/bin/systemctl','stop','metainc-naver-engine.service']])

    def test_restored_code_must_pass_readiness_and_security_probes(self):
        code=load('naver_preview_code_upgrade')
        release=Mock();life=Mock();upgrade=Mock()
        life._state.return_value='active'
        upgrade.probe.side_effect=ValueError('OLD_NOT_READY')
        with self.assertRaisesRegex(ValueError,'OLD_NOT_READY'):
            code.verify_running(Path('/naver-'+code.OLD_COMMIT),
                                {'source_commit':code.OLD_COMMIT},release,life,upgrade)

    def test_changed_bootstrap_is_never_repaired_and_leaves_services_stopped(self):
        result,commands,writes,_,_=self.scenario('bootstrap_changed')
        self.assertEqual(str(result),'CODE_ROLLBACK_FAILED')
        self.assertFalse(any(path.name=='bootstrap-request.json' for path,_ in writes))

    def test_schema_comparison_ignores_whitespace_but_not_migration_or_version(self):
        module=load('naver_preview_code_upgrade')
        before=b'SCHEMA_VERSION=7\n_SCHEMA=("SQL",)\ndef _migrate():\n    pass\n'
        self.assertEqual(module.schema_contract(before),module.schema_contract(before+b'# comment\n'))
        self.assertNotEqual(module.schema_contract(before),module.schema_contract(before.replace(b'=7',b'=8')))
        with self.assertRaises(ValueError):
            module.schema_contract(b'SCHEMA_VERSION=7')

    def test_workflow_keeps_old_routes_and_reserves_code_only_rollback_time(self):
        workflow=(Path(__file__).parents[2]/'.github/workflows/debug-rank.yml').read_text()
        self.assertIn("'preview-upgrade':('naver_preview_upgrade','apply')",workflow)
        self.assertIn("'preview-code-upgrade':('naver_preview_code_upgrade','apply')",workflow)
        self.assertIn("inputs.ad_prepare == 'preview-code-upgrade' && '60m' || '12m'",workflow)
        self.assertIn("inputs.ad_prepare == 'preview-code-upgrade' && 65 || 15",workflow)
        self.assertIn('group: deploy-logic-analysis',workflow)
        # Compile every Python heredoc in the edited workflow without running any script.
        lines=workflow.splitlines();source=None
        for line in lines:
            if line.rstrip().endswith("<<'PY'"):
                source=[];continue
            if source is not None:
                if line.strip()=='PY':
                    compile(textwrap.dedent('\n'.join(source)),'<workflow-synthetic>','exec');source=None
                else:
                    source.append(line)

    def test_unchanged_prepare_bundle_fits_single_environment_value_limit(self):
        tools=Path(__file__).parents[1]/'tools'
        source=lambda name:(tools/(name+'.py')).read_text()
        package=dict(baseline='a'*64,source_commit='b'*40,ciphertext_sha256='c'*64,
                     source_tar_gz_sha256='d'*64,run_id='9'*20,operation='code-prepare')
        shared=dict(host_source=source('naver_erp_tunnel_service_install'),
                    lifecycle_source=source('naver_preview_lifecycle'),
                    upgrade_source=source('naver_preview_upgrade'))
        prepare=dict(shared,package=package,source=source('naver_preview_release'),
                     code_source=source('naver_preview_code_upgrade'))
        self.assertLess(len(base64.b64encode(json.dumps(prepare).encode()))+len('PREVIEW_RELEASE_B64='),131000)


if __name__ == '__main__':
    unittest.main()
