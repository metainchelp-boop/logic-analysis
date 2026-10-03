import importlib.util
import ast
import base64
from contextlib import closing
import gzip
import hashlib
import io
import json
import os
import random
import re
import shlex
import sqlite3
import sys
import tarfile
import textwrap
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
import zlib
from unittest.mock import Mock, patch
import test_naver_preview_upgrade as legacy_test


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1]/'tools'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sealed_code():
    """Synthetic release fixture; production pins are checked independently below."""
    module = load('naver_preview_code_upgrade')
    module.TARGET_COMMIT = 'b'*40
    module.TARGET_SOURCE_SHA256 = 'd'*64
    module.STORE_SHA256['target'] = 'e'*64
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

    def test_code_diagnose_transport_preserves_all_six_sources_with_existing_wire_bounds(self):
        encode,decode,script=self.workflow_transport()
        tools=Path(__file__).parents[1]/'tools'
        names={'source':'naver_preview_code_diagnose','code_source':'naver_preview_code_upgrade',
               'release_source':'naver_preview_release','host_source':'naver_erp_tunnel_service_install',
               'lifecycle_source':'naver_preview_lifecycle','upgrade_source':'naver_preview_upgrade'}
        bundle={key:(tools/(name+'.py')).read_text() for key,name in names.items()}
        bundle.update(operation='preview-code-diagnose',function='run',package={
            'release':dict(baseline='a'*64,source_commit='b'*40,ciphertext_sha256='c'*64,
                          source_tar_gz_sha256='d'*64,run_id='9'*20,operation='code-prepare'),
            'operation_id':'e'*32})
        self.assertLessEqual(len(json.dumps(bundle).encode()),196608)
        encoded=encode(bundle)
        self.assertEqual(decode(encoded),bundle)
        self.assertLessEqual(len(encoded),65536)
        shell="export PREVIEW_OPS_B64="+shlex.quote(encoded)+";\nset -eu\n/usr/bin/python3 -I -B - <<'PY'\n"+script+'\nPY\n'
        self.assertLess(len(('/bin/bash -c '+shlex.quote(shell)).encode()),120000)
        with self.assertRaisesRegex(ValueError,'CODE_OPS_OPERATION'):
            decode(encode(dict(bundle,function='apply')))

    def test_collection_status_transport_preserves_three_sources_with_existing_wire_bounds(self):
        encode,decode,script=self.workflow_transport()
        tools=Path(__file__).parents[1]/'tools'
        names={'source':'naver_preview_collection_status','release_source':'naver_preview_release',
               'host_source':'naver_erp_tunnel_service_install'}
        bundle={key:(tools/(name+'.py')).read_text() for key,name in names.items()}
        bundle.update(operation='preview-collection-status',function='run',package={
            'baseline':'a'*64,'source_commit':'01344b145d0b679a6ee730d7fa4b5990278dd654',
            'source_tar_gz_sha256':'b'*64})
        self.assertLessEqual(len(json.dumps(bundle).encode()),196608)
        encoded=encode(bundle)
        self.assertTrue(encoded.startswith('code-gzip-v1:'))
        self.assertEqual(decode(encoded),bundle)
        self.assertLessEqual(len(encoded),65536)
        shell="export PREVIEW_OPS_B64="+shlex.quote(encoded)+";\nset -eu\n/usr/bin/python3 -I -B - <<'PY'\n"+script+'\nPY\n'
        self.assertLess(len(('/bin/bash -c '+shlex.quote(shell)).encode()),120000)
        with self.assertRaisesRegex(ValueError,'CODE_OPS_ENCODING'):
            decode(base64.b64encode(json.dumps(bundle).encode()).decode())
        with self.assertRaisesRegex(ValueError,'CODE_OPS_OPERATION'):
            decode(encode(dict(bundle,function='apply')))

    def test_transport_keeps_other_operations_byte_identical_and_code_mode_exact(self):
        encode,decode,_=self.workflow_transport()
        for operation in ('preview-upgrade','preview-status','preview-backup','preview-publish',
                          'preview-data-audit','preview-link-audit','preview-legacy-audit',
                          'preview-inspect','preview-plan','preview-rollback','preview-lifecycle'):
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
             gzip.compress(b' '*196609),b'invalid-gzip']
        for data in bad:
            with self.subTest(size=len(data)),self.assertRaises((ValueError,zlib.error)):
                decode('code-gzip-v1:'+base64.b64encode(data).decode())
        for encoded in ('code-gzip-v1:!!!','code-gzip-v1:'+'A'*65536):
            with self.assertRaises(ValueError):
                decode(encoded)
        with self.assertRaisesRegex(ValueError,'CODE_OPS_JSON_SIZE'):
            encode(dict(bundle,source='x'*196608))
        with self.assertRaisesRegex(ValueError,'CODE_OPS_WIRE_SIZE'):
            encode(dict(bundle,source=random.Random(0).randbytes(60000).hex()))

    def test_target_probe_requires_authentication_only_for_new_verified_routes(self):
        code = sealed_code()
        release = Mock()
        def read(path, route, method='GET'):
            if route == '/_engine/health':
                return 200, {}, b'{}'
            if route in ('/naver/', '/naver/dashboard'):
                return 200, {'referrer-policy': 'no-referrer', 'cache-control': 'no-store'}, b'verificationNotice id="s-dashboard"'
            approved = tuple('/api/naver-auto'+route for route in
                             ('/links/confirm', '/collection/request', '/management/update',
                              '/management/collect', '/reports/review'))
            return (401 if method == 'GET' or route in approved else 403), {}, b''
        release.unix_request.side_effect = read
        code.probe(release, code.TARGET_COMMIT, load('naver_preview_upgrade'))
        calls = {(args[1], args[2] if len(args) > 2 else 'GET')
                 for args, _ in release.unix_request.call_args_list}
        self.assertTrue({('/api/naver-auto/links/confirm', 'POST'),
                         ('/api/naver-auto/collection/request', 'POST'),
                         ('/api/naver-auto/collection/status', 'GET'),
                         ('/api/naver-auto/reports', 'GET'),
                         ('/api/naver-auto/accounts/reasons?ad_account_no=1&page=0&selection=all', 'GET'),
                         ('/api/naver-auto/management/update', 'POST'),
                         ('/api/naver-auto/management/collect', 'POST'),
                         ('/api/naver-auto/reports/review', 'POST'),
                         ('/api/naver-auto/dashboard', 'GET'),
                         ('/naver/dashboard', 'GET'),
                         ('/api/naver-auto/issues/1/ack', 'POST'),
                         ('/api/naver-auto/settings/thresholds', 'POST')} <= calls)

    def test_probe_distinguishes_exact_old_and_target_auth_contracts(self):
        code = sealed_code()
        # Deployed abf2406 already authenticates these verified business routes.
        for source, confirm, accepted in ((code.OLD_COMMIT, 403, False),
                (code.OLD_COMMIT, 401, True), (code.TARGET_COMMIT, 401, True),
                (code.TARGET_COMMIT, 403, False), (code.TARGET_COMMIT, 200, False)):
            with self.subTest(source=source, confirm=confirm):
                release = Mock()
                def read(path, route, method='GET'):
                    if route == '/_engine/health':
                        return 200, {}, b'{}'
                    if route in ('/naver/', '/naver/dashboard'):
                        return 200, {'referrer-policy':'no-referrer','cache-control':'no-store'}, b'verificationNotice id="s-dashboard"'
                    if route == '/api/naver-auto/links/confirm':
                        return confirm, {}, b''
                    approved = ('/collection/request', '/management/update', '/management/collect', '/reports/review')
                    return (401 if method == 'GET' or route.removeprefix('/api/naver-auto') in approved else 403), {}, b''
                release.unix_request.side_effect = read
                if accepted:
                    code.probe(release, source, load('naver_preview_upgrade'))
                    for route in ('/naver/dashboard', '/api/naver-auto/dashboard'):
                        hits = [args for args, _ in release.unix_request.call_args_list if args[1] == route]
                        self.assertEqual(len(hits), 1)
                else:
                    with self.assertRaises(ValueError):
                        code.probe(release, source, load('naver_preview_upgrade'))

    def test_target_probe_rejects_each_wrong_route_status_and_health_contract(self):
        code = sealed_code()
        routes = {'/me':401, '/dashboard':401, '/collection/status':401, '/links/confirm':401,
                  '/reports':401, '/management/update':401, '/management/collect':401, '/reports/review':401,
                  '/reports/history?possibility_id=1&limit=20':401,
                  '/accounts/reasons?ad_account_no=1&page=0&selection=all':401,
                  '/collection/request':401, '/issues/1/ack':403, '/issues/1/resolve':403,
                  '/issues/1/except':403, '/settings/thresholds':403, '/links/reject':403,
                  '/links/revoke':403, '/links/preview':403, '/bell/1/read':403, '/bell/read-all':403}
        cases = [(route, value) for route, expected in routes.items()
                 for value in (200, 403 if expected == 401 else 401)]
        cases += [('/_engine/health', 'invalid'), ('/naver/', 'header'), ('/naver/', 'body'),
                  ('/naver/dashboard', 'header'), ('/naver/dashboard', 'body'), ('/naver/dashboard', 404)]
        for changed, wrong in cases:
            with self.subTest(route=changed, response=wrong):
                release = Mock()
                def read(path, route, method='GET'):
                    if route == '/_engine/health':
                        return 200, {}, b'[]' if changed == route else b'{}'
                    if route in ('/naver/', '/naver/dashboard'):
                        headers = {'referrer-policy':'no-referrer','cache-control':'no-store'}
                        return (404 if changed == route and wrong == 404 else 200,
                                {} if changed == route and wrong == 'header' else headers,
                                b'wrong' if changed == route and wrong == 'body' else b'verificationNotice id="s-dashboard"')
                    key = route.removeprefix('/api/naver-auto')
                    return (wrong if changed == key else routes[key]), {}, b''
                release.unix_request.side_effect = read
                with self.assertRaises(ValueError):
                    code.probe(release, code.TARGET_COMMIT, load('naver_preview_upgrade'))

    def test_unknown_or_mismatched_source_refuses_before_any_probe(self):
        code = sealed_code()
        release = Mock()
        for source in (None, '', 'c'*40):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'CODE_PROBE_SOURCE'):
                code.probe(release, source, load('naver_preview_upgrade'))
        for source in (code.OLD_COMMIT, code.TARGET_COMMIT, 'c'*40):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'CODE_PROBE_SOURCE'):
                code.verify_running(Path('/wrong-release'), {'source_commit':source}, release, Mock(), Mock())
        release.unix_request.assert_not_called()

    def test_only_exact_approved_code_transition_is_accepted_without_bootstrap_request(self):
        module = sealed_code()
        module.TARGET_COMMIT = 'b'*40  # A sealed target is supplied only in the fixture.
        release = load('naver_preview_release')
        package = dict(baseline=module.EXPECTED_BASELINE, source_commit=module.TARGET_COMMIT,
                       ciphertext_sha256='b'*64, source_tar_gz_sha256=module.TARGET_SOURCE_SHA256,
                       run_id='123456', operation='code-prepare')
        self.assertEqual(module.validate_package(package, release), package)
        for changes in ({'source_commit': module.OLD_COMMIT}, {'operation': 'upgrade-prepare'},
                        {'request': {}}, {'source_commit': 'f'*40}, {'baseline': 'd'*64},
                        {'source_tar_gz_sha256':'f'*64}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                module.validate_package(dict(package, **changes), release)
        host = Mock()
        with self.assertRaises(ValueError):
            module.apply({'release': package, 'request': {}}, host, release, Mock(), Mock())
        host.assert_not_called()

    def test_unsealed_or_same_as_old_target_refuses_before_any_action(self):
        module = sealed_code()
        release = load('naver_preview_release')
        package = dict(baseline=module.EXPECTED_BASELINE, source_commit='b'*40,
                       ciphertext_sha256='c'*64, source_tar_gz_sha256='d'*64,
                       run_id='123456', operation='code-prepare')
        for target in (None, '', module.OLD_COMMIT):
            with self.subTest(target=target), patch.object(module, 'TARGET_COMMIT', target):
                with self.assertRaisesRegex(ValueError, 'CODE_TARGET_NOT_PINNED'):
                    module.validate_package(package, release)
        for digest in (None, '', 'pending'):
            with self.subTest(digest=digest), patch.object(module, 'TARGET_SOURCE_SHA256', digest):
                with self.assertRaisesRegex(ValueError, 'CODE_TARGET_NOT_PINNED'):
                    module.validate_package(package, release)

    def test_only_reviewed_runtime_and_bundled_test_paths_are_allowlisted(self):
        module = load('naver_preview_code_upgrade')
        self.assertEqual(module.OLD_COMMIT, 'e132a4b6ebba40ca58fb4de3cd3a66a3c910b218')
        self.assertEqual(module.TARGET_COMMIT, '01344b145d0b679a6ee730d7fa4b5990278dd654')
        self.assertEqual(module.OLD_SOURCE_SHA256,
                         '94c0e58e700b73c4459edadeb97b34c3268a8c8483fe4107c178b9423444ae29')
        self.assertEqual(module.TARGET_SOURCE_SHA256, '0faf3865ec14802d96bf51fa376961064196105e52578f24c93e56430120693d')
        self.assertEqual(module.STORE_SHA256, {
            'old':'d33bc6315eac7b020f17ffc87a19c920a1a307b3bf9799f921759cb60a1c3e2e',
            'target':'d33bc6315eac7b020f17ffc87a19c920a1a307b3bf9799f921759cb60a1c3e2e'})
        contract = json.loads((Path(__file__).with_name('fixtures')/'naver_schema10_11_contract.json').read_text())
        # This historical migration fixture remains the original schema-11 release.
        self.assertEqual(contract['new_observed_unsealed']['sha256'],
                         '66b3f5511bc5977077eb45c6fd14cbde7be4bfdc5afbaac2abc2eca9362fca89')
        # Exact git archive delta: top-level tests, docs and seal tooling are not bundled.
        self.assertEqual(module.CODE_PATHS, {
            'backend/naver_page/app.css', 'backend/naver_page/app.js', 'backend/naver_page/index.html'})
        self.assertEqual(module.TEST_PATHS, {
            'naver_engine/tests/test_screen.py', 'naver_engine/tests/test_transfer_balance_screen.py'})

    def scenario(self, failure=None, mode='apply'):
        code = sealed_code()
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
            (root/'incoming'/'123456').mkdir(parents=True, exist_ok=True)
            previous_write = release.write_new
            def write(path, body, **kwargs):
                if Path(path).name == 'check-config.override.yml':
                    self.assertEqual(body, b'services:\n  naver-engine:\n    network_mode: none\n')
                return previous_write(path, body, **kwargs)
            release.write_new = write
            infrastructure = {'Dockerfile.naver-engine': b'FROM fixture', 'Dockerfile.naver-relay': b'FROM fixture',
                'backend/requirements.txt': b'fixture', 'naver_runtime/bootstrap.py': b'# unchanged bootstrap',
                'naver_engine/store.py': StoreScopeTest.TARGET_SOURCE}
            infrastructure.update({name: b'new fixture compose' for name in
                ('compose.naver-engine.yml','compose.naver-relay.yml','deploy/naver-engine-backup.override.yml')})
            for path in (root/'releases').iterdir():
                for name, body in infrastructure.items():
                    target = path/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(body)
                if path.name == 'naver-'+code.OLD_COMMIT:
                    (path/'naver_engine/store.py').write_bytes(StoreScopeTest.SOURCE)
                for name in ('engine','relay'):
                    # The UI update inherits all flags without adding or changing them.
                    body = ('image: '+code.OLD_COMMIT).encode()
                    if path.name != 'naver-'+code.OLD_COMMIT:
                        body = code.target_override(body, name)
                    (path/('preview-'+name+'.override.yml')).write_bytes(body)
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
            sources={name:code.OLD_COMMIT for name in ('engine','relay')}
            services={}
            execute, request_api=release.command,release.unix_request
            def track(args,**kwargs):
                result=execute(args,**kwargs)
                for name in ('engine', 'relay'):
                    build = args[:2] == ['docker', 'build'] and 'metainc/naver-'+name+':'+code.TARGET_COMMIT in args
                    config = args[:2] == ['docker', 'compose'] and args[-2:] == ['config', '--quiet'] and 'naver-'+name in args
                    if (failure == 'prepare_build_'+name and build) or (failure == 'prepare_config_'+name and config):
                        error = RuntimeError('DOCKER_BUILD_UNKNOWN' if build else 'COMMAND_FAILED')
                        error.observed_stage = code.STAGE
                        raise error
                if '--force-recreate' in args:
                    current['source']=Path(args[5]).parent.name.removeprefix('naver-')
                    sources[args[3].removeprefix('naver-')]=current['source']
                if args[:2] == ['/usr/bin/systemctl', 'stop']:
                    services[args[-1]] = 'failed' if failure=='failed_stopped' else 'inactive'
                if args[:2] == ['/usr/bin/systemctl', 'start']:
                    services[args[-1]] = 'active'
                if args[:2] == ['/usr/bin/systemctl', 'show']:
                    active=services.get(args[2], 'active')
                    values={'ActiveState':active,'SubState':'running' if active=='active' else
                            'failed' if active=='failed' else 'dead','MainPID':'123' if active=='active' else '0'}
                    if args[-2] in values:
                        return values[args[-2]].encode()
                if args[:2] == ['docker','ps']:
                    name=args[args.index('--filter')+1].removeprefix('label=com.docker.compose.project=naver-')
                    return (('3' if name=='engine' else '4')*64).encode()
                if args[:2] == ['docker','inspect'] and '.State.Restarting' in args[-2]:
                    name='engine' if args[-1]=='3'*64 else 'relay'
                    row=json.loads(result)
                    running=services.get('metainc-naver-'+name+'.service','active')=='active'
                    running=running or failure=='stop_writer_running' or (
                        failure=='rollback_writer_running' and sources[name]!=code.OLD_COMMIT)
                    row.update(source=sources[name],running=running,restarting=False,pid=123 if running else 0)
                    return json.dumps(row).encode()
                return result
            def request_api_by_code(path,route,method='GET'):
                if route == '/naver/dashboard':
                    return 200, {'referrer-policy':'no-referrer','cache-control':'no-store'}, b'id="s-dashboard"'
                if method=='POST':
                    verified = route in ('/api/naver-auto/links/confirm','/api/naver-auto/collection/request',
                        '/api/naver-auto/management/update','/api/naver-auto/management/collect','/api/naver-auto/reports/review')
                    if current['source']==code.OLD_COMMIT:
                        return (401 if verified else 403),{},b''
                    if verified and failure not in ('probe','rollback_recreate','rollback_writer_running'):
                        return 401,{},b''
                    if verified and failure=='rollback_writer_running':
                        return 200,{},b''
                return request_api(path,route,method)
            release.command,release.unix_request=track,request_api_by_code
            target=root/'releases'/('naver-'+'b'*40)
            if failure=='schema':
                (target/'naver_engine/store.py').write_text('SCHEMA_VERSION=9\n_SCHEMA=()\ndef _migrate():\n    pass\n')
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
                patch.object(code, 'OLD_SOURCE_SHA256', 'c'*64), \
                patch.object(code, 'TARGET_SOURCE_SHA256', 'c'*64), \
                patch.object(code, 'STORE_SHA256', {'old':hashlib.sha256(StoreScopeTest.SOURCE).hexdigest(),
                                                  'target':hashlib.sha256(StoreScopeTest.TARGET_SOURCE).hexdigest()}), \
                patch.object(code, 'verify_database_schema'), \
                patch.object(code, 'db_snapshot', return_value=(Path('/synthetic-snapshot'), 'd'*64)) as snapshot, \
                patch.object(code, 'restore_db') as restore, \
                patch.object(code, 'warm_sources', side_effect=(ValueError('WARM_FAILED') if failure=='warm'
                             else RuntimeError('WARM_CLEANUP_FAILED') if failure=='warm_cleanup' else None),
                             return_value={'ok':True, 'org_fresh':True, 'schema':11, 'catalog_total':2, 'management_count':1}):
            result = legacy_test.UpgradeTest().scenario(failure, mode, setup)
            if failure in ('warm','recreate','start','probe'):
                restore.assert_called_once()
            if failure == 'warm_cleanup':
                restore.assert_not_called()
            if failure=='stop_writer_running':
                snapshot.assert_not_called()
                restore.assert_not_called()
            if failure=='rollback_writer_running':
                snapshot.assert_called_once()
                restore.assert_not_called()
            return result

    def test_prepare_build_and_compose_failures_have_distinct_stages_without_starting_services(self):
        for kind in ('build', 'config'):
            for name in ('engine', 'relay'):
                with self.subTest(kind=kind, service=name):
                    result, commands, writes, restored, state = self.scenario('prepare_'+kind+'_'+name, mode='prepare')
                    self.assertIsInstance(result, RuntimeError)
                    self.assertEqual(result.observed_stage, 'code_'+kind+'_'+name)
                    self.assertEqual(str(result), 'DOCKER_BUILD_UNKNOWN' if kind == 'build' else 'COMMAND_FAILED')
                    self.assertTrue(restored)
                    self.assertEqual(state, {'engine': sealed_code().OLD_COMMIT, 'relay': sealed_code().OLD_COMMIT})
                    self.assertFalse(any(args[:2] in (['/usr/bin/systemctl', 'stop'], ['/usr/bin/systemctl', 'start']) for args in commands))
                    self.assertFalse(any(path.name == 'preview-'+'b'*40+'.json' for path, _ in writes))

    def test_code_apply_preserves_existing_request_and_never_writes_a_new_one(self):
        result, commands, writes, _, state = self.scenario('replay')
        self.assertIsInstance(result, dict, str(result))
        self.assertTrue(result['ok'])
        self.assertEqual(result['database_schema'],11)
        self.assertEqual(state, {'engine': 'b'*40, 'relay': 'b'*40})
        self.assertFalse(any(path.name == 'bootstrap-request.json' for path, _ in writes))
        self.assertFalse(any('nginx' in ' '.join(args) for args in commands))

    def test_failed_supervisor_with_proven_stopped_writers_can_snapshot_and_apply(self):
        result,commands,_,_,state=self.scenario('failed_stopped')
        self.assertIsInstance(result,dict,str(result))
        self.assertTrue(result['ok'])
        self.assertEqual(state,{'engine':'b'*40,'relay':'b'*40})
        checked=[args for args in commands if args[:2]==['docker','inspect'] and '.State.Restarting' in args[-2]]
        self.assertEqual(len(checked),2)

    def test_any_live_or_unproven_writer_blocks_snapshot_and_rollback_mutations(self):
        for failure in ('stop_writer_running','rollback_writer_running'):
            with self.subTest(failure=failure):
                result,commands,_,_,_=self.scenario(failure)
                self.assertEqual(str(result),'CODE_ROLLBACK_FAILED')
                details=result.failure_details
                self.assertEqual(details['rollback_error_code'],'ACCOUNT_WRITER_NOT_STOPPED')
                last_stop=max(i for i,args in enumerate(commands) if args[:2]==['/usr/bin/systemctl','stop'])
                self.assertFalse(any('--force-recreate' in args or args[:2]==['/usr/bin/systemctl','start']
                                     for args in commands[last_stop+1:]))
                if failure=='stop_writer_running':
                    self.assertFalse(any('--force-recreate' in args or args[:2]==['/usr/bin/systemctl','start']
                                         for args in commands))
                else:
                    # The only recreations are the forward target pair, never the old writer after failed proof.
                    self.assertEqual(sum('--force-recreate' in args for args in commands),2)

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
        probe_files = [path for path, _ in writes if path.name == 'check-config.override.yml']
        self.assertEqual(len(probe_files), 1)
        probe_path = probe_files[0]
        self.assertEqual(probe_path.parent.parent.name, 'incoming')
        self.assertRegex(probe_path.parent.name, r'^[0-9]{6,20}$')
        self.assertEqual(check[-12:-10], ['-f', str(probe_path)])
        self.assertEqual(sum(str(probe_path) in args for args in commands), 1)
        self.assertFalse(any('network' in args and ('rm' in args or 'prune' in args) for args in commands))

    def test_schema_infrastructure_or_bootstrap_uncertainty_refuses_before_any_mutation(self):
        for reason in ('image','unit','manifest','schema','infrastructure','override','bootstrap_pending',
                       'old_source','unapproved_code','unapproved_new'):
            with self.subTest(reason=reason):
                result,commands,writes,_,_=self.scenario(reason)
                self.assertIsInstance(result,Exception)
                self.assertEqual(writes,[])
                self.assertFalse(any(args[:2]==['/usr/bin/systemctl','stop'] for args in commands))

    def test_code_scope_only_allows_exact_paths_and_no_deletions_or_unsafe_files(self):
        module=sealed_code()
        upgrade=Mock()
        upgrade.read_file.side_effect=lambda path,**kwargs: Path(path).read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            old=Path(folder).resolve()/'old';new=Path(folder).resolve()/'new'
            for root in (old,new):
                (root/'backend/naver_page').mkdir(parents=True)
                (root/'backend/naver_page/app.js').write_bytes(b'old')
                (root/'backend/naver_page/sso-bootstrap.js').write_bytes(b'unchanged')
            (new/'backend/naver_page/app.js').write_bytes(b'new')
            added=new/'backend/naver_page/app.js';added.write_bytes(b'approved')
            module.compatible_code_scope(old,new,upgrade)
            forbidden=new/'backend/naver_page/sso-bootstrap.js';forbidden.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):
                module.compatible_code_scope(old,new,upgrade)
            forbidden.write_bytes(b'unchanged')
            original_mode=added.stat().st_mode & 0o777
            added.chmod(original_mode | 0o100)
            with self.assertRaisesRegex(ValueError,'CODE_SOURCE_MODE_CHANGED'):
                module.compatible_code_scope(old,new,upgrade)
            added.chmod(original_mode)
            added.unlink();added.symlink_to(forbidden)
            with self.assertRaisesRegex(ValueError,'CODE_SOURCE_PATH'):
                module.compatible_code_scope(old,new,upgrade)
            added.unlink()
            with self.assertRaisesRegex(ValueError,'CODE_SOURCE_REMOVED'):
                module.compatible_code_scope(old,new,upgrade)

    def test_transfer_balance_release_allows_only_exact_ui_and_test_paths(self):
        module=sealed_code()
        upgrade=Mock()
        upgrade.read_file.side_effect=lambda path,**kwargs: Path(path).read_bytes()
        approved=tuple(module.CODE_PATHS | module.TEST_PATHS)
        with tempfile.TemporaryDirectory() as folder:
            old=Path(folder).resolve()/'old';new=Path(folder).resolve()/'new'
            for root in (old,new):
                for name in approved:
                    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'old')
            # Only this bundled browser-discovery wrapper is newly added in the archive.
            (old/'naver_engine/tests/test_transfer_balance_screen.py').unlink()
            for name in approved:
                (new/name).write_bytes(b'approved transfer balance UI update')
            module.compatible_code_scope(old,new,upgrade)
            for name in ('naver_runtime/bootstrap.py','naver_engine/inventory_reads.py',
                         'naver_runtime/writer.py','backend/app/naver_auto/org_snapshot.py',
                         'backend/naver_page/sso-bootstrap.js','backend/app/naver_entry.py',
                         'naver_runtime/scheduler.py','naver_engine/unreviewed_view_sync.py',
                         'naver_engine/view_sync.py','naver_engine/store.py','naver_engine/web.py',
                         'backend/app/naver_auto/scope.py',
                         'naver_engine/catalog_links.py','naver_engine/naver_read.py',
                         'naver_engine/performance_reads.py','naver_engine/structure_reads.py',
                         'naver_engine/credentials.py','naver_engine/session.py',
                         'tests/naver_management_ui.test.js','tools/naver-preview-seal.py'):
                forbidden=new/name;forbidden.parent.mkdir(parents=True,exist_ok=True);forbidden.write_bytes(b'not approved')
                with self.subTest(path=name), self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):
                    module.compatible_code_scope(old,new,upgrade)
                forbidden.unlink()
            added=new/'naver_engine/tests/test_transfer_balance_screen.py'
            added.unlink();added.symlink_to(new/'backend/naver_page/app.js')
            with self.assertRaisesRegex(ValueError,'CODE_SOURCE_PATH'):
                module.compatible_code_scope(old,new,upgrade)

    def test_new_screen_test_does_not_allow_adjacent_modules_or_existing_source_deletion(self):
        module=sealed_code()
        upgrade=Mock()
        upgrade.read_file.side_effect=lambda path,**kwargs: Path(path).read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            old=Path(folder).resolve()/'old';new=Path(folder).resolve()/'new'
            for root in (old,new):
                (root/'naver_engine').mkdir(parents=True)
                (root/'naver_engine/web.py').write_bytes(b'unchanged web')
                (root/'naver_engine/credentials.py').write_bytes(b'unchanged credentials')
            (new/'naver_engine/tests').mkdir()
            (new/'naver_engine/tests/test_transfer_balance_screen.py').write_bytes(b'approved browser wrapper')
            module.compatible_code_scope(old,new,upgrade)
            adjacent=new/'naver_engine/view_sync_extra.py'
            adjacent.write_bytes(b'not approved')
            with self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):
                module.compatible_code_scope(old,new,upgrade)
            adjacent.unlink()
            credentials=new/'naver_engine/credentials.py'
            credentials.write_bytes(b'changed credentials')
            with self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):
                module.compatible_code_scope(old,new,upgrade)
            credentials.write_bytes(b'unchanged credentials')
            (new/'naver_engine/web.py').unlink()
            with self.assertRaisesRegex(ValueError,'CODE_SOURCE_REMOVED'):
                module.compatible_code_scope(old,new,upgrade)

    def test_target_view_release_rejects_previous_archive_before_prepare_actions(self):
        module=load('naver_preview_code_upgrade')
        release=load('naver_preview_release')
        package=dict(baseline=module.EXPECTED_BASELINE, source_commit=module.TARGET_COMMIT,
                     ciphertext_sha256='c'*64, source_tar_gz_sha256=module.OLD_SOURCE_SHA256,
                     run_id='123456', operation='code-prepare')
        host=Mock();lifecycle=Mock();upgrade=Mock()
        with self.assertRaisesRegex(ValueError,'CODE_TARGET_SOURCE_CHANGED'):
            module.prepare(package,host,release,lifecycle,upgrade)
        host.assert_not_called()
        self.assertEqual(host.mock_calls,[])
        self.assertEqual(lifecycle.mock_calls,[])
        self.assertEqual(upgrade.mock_calls,[])

    def test_every_partial_failure_restores_exact_old_images_and_units(self):
        for reason in ('stop','warm','recreate','start','probe'):
            with self.subTest(reason=reason):
                result,commands,writes,restored,state=self.scenario(reason)
                self.assertEqual(str(result),'CODE_FAILED_ROLLED_BACK_DB_PRESERVED')
                self.assertTrue(restored)
                old=sealed_code().OLD_COMMIT
                self.assertEqual(state,{'engine':old,'relay':old})
                self.assertFalse(any(path.name=='bootstrap-request.json' for path,_ in writes))

    def test_partial_recreation_requires_both_mixed_source_proofs_before_old_recreation(self):
        result,commands,_,_,_=self.scenario('recreate')
        self.assertEqual(str(result),'CODE_FAILED_ROLLED_BACK_DB_PRESERVED')
        recreations=[i for i,args in enumerate(commands) if '--force-recreate' in args]
        self.assertEqual(len(recreations),4)
        rollback_proofs=[args for args in commands[recreations[1]+1:recreations[2]]
                         if args[:2]==['docker','inspect'] and '.State.Restarting' in args[-2]]
        self.assertEqual({args[-1] for args in rollback_proofs},{'3'*64,'4'*64})

    def test_rollback_failure_leaves_both_isolated_services_stopped(self):
        result,commands,_,_,_=self.scenario('rollback_recreate')
        self.assertEqual(str(result),'CODE_ROLLBACK_FAILED')
        self.assertEqual(commands[-2:], [['/usr/bin/systemctl','stop','metainc-naver-relay.service'],
                                        ['/usr/bin/systemctl','stop','metainc-naver-engine.service']])

    def test_unconfirmed_warm_cleanup_never_restores_database_or_starts_old_services(self):
        result,commands,_,_,_=self.scenario('warm_cleanup')
        self.assertEqual(str(result),'CODE_ROLLBACK_FAILED')
        self.assertFalse(any(args[:2]==['/usr/bin/systemctl','start'] for args in commands))
        self.assertEqual(commands[-2:], [['/usr/bin/systemctl','stop','metainc-naver-relay.service'],
                                        ['/usr/bin/systemctl','stop','metainc-naver-engine.service']])

    def test_rollback_retains_fixed_original_failure_stage_and_operation_without_exception_text(self):
        for reason,stage,operation in (('stop','code_stop_isolated','stop_relay'),
                ('warm','account_sources_warm','warm_sources'),
                ('recreate','code_recreate','recreate_relay'),
                ('start','code_start','start_engine')):
            with self.subTest(reason=reason):
                result,_,_,_,_=self.scenario(reason)
                report=getattr(result,'failure_details',{})
                self.assertEqual(report.get('failed_stage'),stage)
                self.assertEqual(report.get('failed_operation'),operation)
                self.assertNotIn('PRIVATE',json.dumps(report))

    def test_error_report_rejects_arbitrary_uppercase_messages_and_untrusted_exception_types(self):
        code=sealed_code()
        error=type('PRIVATE_TYPE_MARKER',(RuntimeError,),{})('PRIVATE_CREDENTIAL_MARKER')
        code.STAGE='PRIVATE_STAGE_MARKER'
        code.OPERATION='PRIVATE_OPERATION_MARKER'
        report=code.failure_report(error)
        self.assertEqual(report,{'stage':'unknown','error_kind':'OtherError','error_code':'UNRECOGNIZED'})
        self.assertNotIn('PRIVATE',json.dumps(report))

    def test_workflow_code_error_output_uses_fixed_report_even_when_module_could_not_load(self):
        _,_,script=self.workflow_transport()
        guarded=next(node for node in ast.parse(script).body if isinstance(node,ast.Try))
        handler=compile(ast.Module(body=guarded.handlers[0].body,type_ignores=[]),'<workflow-error-report>','exec')
        code=sealed_code()
        for operation in ('preview-code-upgrade','preview-code-diagnose'):
            for module in (None,code):
                scope={'error':RuntimeError('PRIVATE_CREDENTIAL_MARKER'),'bundle':{'operation':operation},
                       'module':module,'re':re}
                exec(handler,scope)
                self.assertEqual(scope['result']['error_code'],'UNRECOGNIZED')
                self.assertNotIn('PRIVATE',json.dumps(scope['result']))

    def test_restored_code_must_pass_readiness_and_security_probes(self):
        code=sealed_code()
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
        module=sealed_code()
        before=b'SCHEMA_VERSION=7\n_SCHEMA=("SQL",)\n_REVISION_COLUMNS={}\ndef _migrate():\n    pass\n'
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

    def test_compressed_prepare_bundle_roundtrip_and_size_guards_use_real_workflow(self):
        tools=Path(__file__).parents[1]/'tools'
        source=lambda name:(tools/(name+'.py')).read_text()
        package=dict(baseline='a'*64,source_commit='b'*40,ciphertext_sha256='c'*64,
                     source_tar_gz_sha256='d'*64,run_id='9'*20,operation='code-prepare')
        shared=dict(host_source=source('naver_erp_tunnel_service_install'),
                    lifecycle_source=source('naver_preview_lifecycle'),
                    upgrade_source=source('naver_preview_upgrade'))
        prepare=dict(shared,package=package,source=source('naver_preview_release'),
                     code_source=source('naver_preview_code_upgrade'))
        # The account-first controller exceeds raw base64 argv limits; use the reviewed gzip transport.
        workflow=(Path(__file__).parents[2]/'.github/workflows/debug-rank.yml').read_text()
        scripts=[];lines=None
        for line in workflow.splitlines():
            if line.rstrip().endswith("<<'PY'"):
                lines=[]
            elif lines is not None:
                if line.strip()=='PY':
                    scripts.append(textwrap.dedent('\n'.join(lines)));lines=None
                else:
                    lines.append(line)
        encoder=next(script for script in scripts if "PREPARE_BUNDLE_SIZE" in script)
        body=next(node for node in ast.parse(encoder).body if isinstance(node,ast.Try)).body
        begin=next(i for i,node in enumerate(body) if isinstance(node,ast.Assign)
                   and any(isinstance(target,ast.Name) and target.id=='raw' for target in node.targets))
        encoder_nodes=body[begin:]
        encoder_nodes=encoder_nodes[:next(i for i,node in enumerate(encoder_nodes) if isinstance(node,ast.With))]
        encode_code=compile(ast.Module(body=encoder_nodes,type_ignores=[]),'<prepare-encode>','exec')
        def encode(bundle):
            scope=dict(bundle=bundle,json=json,gzip=gzip,base64=base64)
            exec(encode_code,scope)
            return scope['encoded']
        decoders=[]
        for script in scripts:
            if "wire=os.environ['PREVIEW_RELEASE_B64']" not in script:
                continue
            body=next(node for node in ast.parse(script).body if isinstance(node,ast.Try)).body
            end=next(i for i,node in enumerate(body) if isinstance(node,ast.Assign)
                     and any(isinstance(target,ast.Name) and target.id=='bundle' for target in node.targets))
            decoders.append(compile(ast.Module(body=body[1:end+1],type_ignores=[]),'<prepare-decode>','exec'))
        self.assertEqual(len(decoders),2)
        encoded=encode(prepare)
        self.assertTrue(encoded.startswith('prepare-gzip-v1:'))
        self.assertLessEqual(len(encoded),65536)
        self.assertLess(len(shlex.quote('export PREVIEW_RELEASE_B64='+shlex.quote(encoded))),120000)
        for decoder in decoders:
            def decode(wire):
                scope=dict(wire=wire,json=json,zlib=zlib,base64=base64)
                exec(decoder,scope)
                return scope['bundle']
            self.assertEqual(decode(encoded),prepare)
            packed=gzip.compress(json.dumps(prepare).encode())
            for bad in (packed[:-1], packed+b'tail', packed+packed, gzip.compress(b' '*131073), b'bad'):
                with self.assertRaises((AssertionError,ValueError,zlib.error)):
                    decode('prepare-gzip-v1:'+base64.b64encode(bad).decode())
            with self.assertRaises(AssertionError):
                decode('prepare-gzip-v1:'+'A'*65536)
        with self.assertRaisesRegex(ValueError,'PREPARE_BUNDLE_SIZE'):
            encode({'source':'x'*131072})
        with self.assertRaisesRegex(ValueError,'PREPARE_WIRE_SIZE'):
            encode({'source':random.Random(0).randbytes(60000).hex()})


class StoreScopeTest(unittest.TestCase):
    METHODS = b'''class Store:
    def inventory_work(self, now, limit=3):
        return []
    def record_inventory_progress(self, customer_id, snapshot_at, now, source):
        self._need_writer()
        return None
    def _need_writer(self):
        return True
'''
    _ACTUAL = json.loads((Path(__file__).with_name('fixtures')/'naver_schema10_11_contract.json').read_text())
    SOURCE = ('SCHEMA_VERSION=11\n_SCHEMA='+repr(tuple(_ACTUAL['new_observed_unsealed']['sql']))+'\n'+
        '_REVISION_COLUMNS='+repr({key: tuple(tuple(item) for item in value) for key,value in
                                   _ACTUAL['new_observed_unsealed']['revision_columns'].items()})+'\n'+
        _ACTUAL['new_observed_unsealed']['migrate']+'\n').encode()+METHODS
    TARGET_SOURCE = SOURCE  # This UI-only release does not change any Store method or byte.

    def setUp(self):
        self.code = sealed_code()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.old = Path(self.temporary.name).resolve()/'old'
        self.new = Path(self.temporary.name).resolve()/'new'
        self.upgrade = Mock()
        self.upgrade.read_file.side_effect = lambda path, **kwargs: Path(path).read_bytes()
        hashes = patch.object(self.code, 'STORE_SHA256', {
            'old':hashlib.sha256(self.SOURCE).hexdigest(), 'target':hashlib.sha256(self.TARGET_SOURCE).hexdigest()})
        hashes.start();self.addCleanup(hashes.stop)
        for root in (self.old, self.new):
            for name in ('compose.naver-engine.yml', 'compose.naver-relay.yml',
                         'deploy/naver-engine-backup.override.yml', 'Dockerfile.naver-engine',
                         'Dockerfile.naver-relay', 'backend/requirements.txt', 'naver_runtime/bootstrap.py'):
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'unchanged')
            path = root/'naver_engine/store.py'
            path.parent.mkdir(parents=True)
            path.write_bytes(self.SOURCE if root == self.old else self.TARGET_SOURCE)
            for name in ('engine', 'relay'):
                body = ('image: '+self.code.OLD_COMMIT).encode()
                if root == self.new:
                    body = self.code.target_override(body, name)
                (root/('preview-'+name+'.override.yml')).write_bytes(body)

    def test_only_pinned_schema11_to11_transition_is_accepted(self):
        self.code.compatible_source(self.old, self.new, self.upgrade)

    def test_schema_version_sql_and_migration_changes_refuse_even_with_approved_methods(self):
        for before, after in ((b'SCHEMA_VERSION=11', b'SCHEMA_VERSION=10'),
                              (b'id INTEGER', b'id TEXT'),
                              (b'self._set_meta', b'self._other_meta')):
            source = self.TARGET_SOURCE.replace(before, after)
            self.assertNotEqual(source, self.TARGET_SOURCE)
            (self.new/'naver_engine/store.py').write_bytes(source)
            with self.subTest(change=before), self.assertRaises(ValueError):
                self.code.compatible_source(self.old, self.new, self.upgrade)

    def test_repinning_store_bytes_cannot_authorize_any_schema11_contract_change(self):
        changes = (
            self.TARGET_SOURCE.replace(b'SCHEMA_VERSION=11', b'SCHEMA_VERSION=12'),
            self.TARGET_SOURCE + b'\n_SCHEMA += ("CREATE TABLE unreviewed (id INTEGER)",)\n',
            self.TARGET_SOURCE.replace(b'source_wait_attempts', b'changed_attempts'),
            self.TARGET_SOURCE.replace(b'if column not in columns:', b'if column in columns:'),
        )
        for source in changes:
            self.assertNotEqual(source, self.TARGET_SOURCE)
            (self.new/'naver_engine/store.py').write_bytes(source)
            hashes = dict(self.code.STORE_SHA256, target=hashlib.sha256(source).hexdigest())
            with self.subTest(source=source), patch.object(self.code, 'STORE_SHA256', hashes), \
                    self.assertRaisesRegex(ValueError, 'CODE_SCHEMA_CHANGED'):
                self.code.compatible_source(self.old, self.new, self.upgrade)

    def test_every_other_store_ast_change_and_method_signature_refuses(self):
        changes = (
            self.TARGET_SOURCE.replace(b'return True', b'return False'),
            self.TARGET_SOURCE+b'UNAPPROVED = True\n',
            self.TARGET_SOURCE.replace(b'class Store:', b'class Store:\n    UNAPPROVED = True'),
            self.TARGET_SOURCE.replace(b'limit=3', b'limit=24'),
            self.TARGET_SOURCE.replace(b'    def inventory_work', b'    @staticmethod\n    def inventory_work'),
            self.TARGET_SOURCE.replace(b'    def inventory_work', b'    async def inventory_work'),
            self.TARGET_SOURCE.replace(b'    def inventory_work', b'    def unapproved_work'),
            self.TARGET_SOURCE+b'    def inventory_work(self, now, limit=3):\n        return [1]\n',
            self.TARGET_SOURCE+b'class Store:\n    pass\n',
            self.TARGET_SOURCE+b'def inventory_work():\n    return [1]\n',
        )
        for source in changes:
            self.assertNotEqual(source, self.TARGET_SOURCE)
            (self.new/'naver_engine/store.py').write_bytes(source)
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.code.compatible_source(self.old, self.new, self.upgrade)

    def test_unchanged_wrong_schema_or_missing_approved_methods_is_not_a_contract(self):
        for source, error in ((self.SOURCE.replace(b'SCHEMA_VERSION=11', b'SCHEMA_VERSION=7'), 'CODE_SCHEMA_CHANGED'),
                              (self.SOURCE.split(b'class Store:')[0], 'CODE_STORE_CHANGED'),
                              (self.SOURCE.replace(b'    def record_inventory_progress',
                                                   b'    def missing_progress'), 'CODE_STORE_CHANGED')):
            for root in (self.old, self.new):
                (root/'naver_engine/store.py').write_bytes(source)
            with self.subTest(error=error), self.assertRaises(ValueError):
                self.code.compatible_source(self.old, self.new, self.upgrade)

    def test_even_comments_and_old_store_changes_need_the_exact_reviewed_hash(self):
        for root, body in ((self.old, self.SOURCE), (self.new, self.TARGET_SOURCE)):
            target=root/'naver_engine/store.py'
            target.write_bytes(b'# unreviewed comment\n'+body)
            with self.assertRaisesRegex(ValueError, 'CODE_STORE_CHANGED'):
                self.code.compatible_source(self.old, self.new, self.upgrade)
            target.write_bytes(body)


class StoppedWriterTest(unittest.TestCase):
    def proof(self, *, state=None, row=None, ids=None, sources=None, failure=None, inspect_body=None):
        code=sealed_code()
        life=load('naver_preview_lifecycle')
        cid='c'*64
        states={'ActiveState':'failed','SubState':'failed','MainPID':'0', **(state or {})}
        images={code.OLD_COMMIT:{'engine':'sha256:'+'e'*64,'relay':'sha256:'+'f'*64},
                code.TARGET_COMMIT:{'engine':'sha256:'+'1'*64,'relay':'sha256:'+'2'*64}}
        value={'id':cid,'image':images[code.OLD_COMMIT]['relay'],'source':code.OLD_COMMIT,
               'project':'naver-relay','service':'naver-relay','running':False,'restarting':False,'pid':0,
               **(row or {})}
        commands=[]
        def command(args,**kwargs):
            commands.append(args)
            if failure is not None and args[1]==failure:
                raise OSError('PRIVATE_COMMAND_SENTINEL')
            if args[:2]==['/usr/bin/systemctl','show']:
                return states[args[-2]].encode()
            if args[:2]==['docker','ps']:
                self.assertIn('label=com.docker.compose.project=naver-relay',args)
                self.assertIn('--all',args)
                self.assertIn('--no-trunc',args)
                return (cid if ids is None else ids).encode()
            if args[:2]==['docker','inspect']:
                return json.dumps(value).encode() if inspect_body is None else inspect_body
            self.fail('Mutation or unknown command '+str(args))
        release=SimpleNamespace(command=command)
        code.stopped_writer(release,life,Path('/release/naver-'+code.OLD_COMMIT),
                            images if sources is None else sources,life.UNITS[1])
        return commands

    def test_failed_supervisor_is_safe_only_when_systemd_and_exact_container_have_no_writer(self):
        self.proof()
        self.proof(state={'ActiveState':'inactive','SubState':'dead'})
        for state in ({'ActiveState':'active'},{'ActiveState':'deactivating'},
                      {'MainPID':'123'},{'MainPID':''},{'SubState':'auto-restart'}):
            with self.subTest(state=state),self.assertRaises(ValueError):
                self.proof(state=state)
        for row in ({'running':True},{'restarting':True},{'pid':12},{'pid':False},
                    {'source':'b'*40},{'image':'sha256:'+'9'*64},{'project':'other'},
                    {'service':'other'},{'id':'d'*64},{'source':[]},{'running':0},
                    {'restarting':0},{'pid':'0'},{'running':None}):
            with self.subTest(row=row),self.assertRaises(ValueError):
                self.proof(row=row)
        for ids in ('short','c'*64+'\n'+'d'*64):
            with self.subTest(ids=ids),self.assertRaises(ValueError):
                self.proof(ids=ids)

    def test_absent_container_still_requires_systemd_dead_and_never_inspects_unknown_ids(self):
        commands=self.proof(ids='')
        self.assertFalse(any(args[:2]==['docker','inspect'] for args in commands))
        self.assertEqual(sum(args[:2]==['/usr/bin/systemctl','show'] for args in commands),3)
        with self.assertRaisesRegex(ValueError,'ACCOUNT_WRITER_NOT_STOPPED'):
            self.proof(ids='',state={'MainPID':'42'})

    def test_source_and_image_are_exact_pairs_and_initial_scope_cannot_accept_target(self):
        code=sealed_code()
        target={'source':code.TARGET_COMMIT,'image':'sha256:'+'2'*64}
        self.proof(row=target)
        old_only={code.OLD_COMMIT:{'relay':'sha256:'+'f'*64}}
        with self.assertRaisesRegex(ValueError,'ACCOUNT_WRITER_NOT_STOPPED'):
            self.proof(row=target,sources=old_only)
        for row in ({'source':code.TARGET_COMMIT},{'image':'sha256:'+'2'*64}):
            with self.subTest(row=row),self.assertRaisesRegex(ValueError,'ACCOUNT_WRITER_NOT_STOPPED'):
                self.proof(row=row)
        for sources in ({},{'unexpected':old_only[code.OLD_COMMIT]},
                        {code.OLD_COMMIT:{}},{code.OLD_COMMIT:{'relay':'mutable-tag'}}):
            with self.subTest(sources=sources),self.assertRaisesRegex(ValueError,'ACCOUNT_WRITER_NOT_STOPPED'):
                self.proof(sources=sources)

    def test_unknown_command_state_or_malformed_inspection_never_proves_a_stopped_writer(self):
        for failure in ('show','ps','inspect'):
            with self.subTest(failure=failure),self.assertRaises(OSError):
                self.proof(failure=failure)
        for raw in (b'[]',b'null',b'{}',b'{invalid',b''):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                self.proof(inspect_body=raw)


class WarmSourcesTest(unittest.TestCase):
    def scenario(self, failure=None):
        code=sealed_code()
        name='naver-warm-'+code.TARGET_COMMIT+'-'+'a'*32
        identity='b'*64
        state={'exists':False}
        commands=[]
        def command(args,**kwargs):
            commands.append(args)
            if args[:2]==['docker','compose']:
                self.assertIn('--detach',args)
                self.assertEqual(args[args.index('--project-name')+1], 'naver-engine')
                self.assertEqual(args[:6], ['docker','compose','--project-name','naver-engine','-f','/synthetic-release/compose.yml'])
                self.assertEqual(args.count('-f'), 1)
                self.assertIn('--no-deps', args)
                self.assertEqual(args[args.index('--name')+1],name)
                self.assertIn('metainc.naver.warm.source='+code.TARGET_COMMIT,args)
                if failure=='create_uncertain':
                    # A killed Docker CLI does not prove the daemon's create request has completed.
                    raise TimeoutError('PRIVATE_UNCONFIRMED_CREATE')
                state['exists']=True
                if failure=='create_timeout':
                    raise TimeoutError('PRIVATE_START_ERROR')
                return (identity+'\n').encode()
            if args[:2]==['docker','wait']:
                self.assertEqual(args[-1],identity)
                if failure=='wait_timeout':
                    raise TimeoutError('PRIVATE_WAIT_ERROR')
                return b'1\n' if failure in ('script_exit','org_refused','unrecognized_script_error') else b'0\n'
            if args[:2]==['docker','logs']:
                if failure=='org_refused':
                    return b'{"ok":false,"warm_step":"warm_org_sync","warm_error_code":"ORG_NOT_ACCEPTED"}'
                if failure=='unrecognized_script_error':
                    return b'{"ok":false,"warm_step":"PRIVATE_STAGE_MARKER","warm_error_code":"PRIVATE_CREDENTIAL_MARKER"}'
                return json.dumps({'ok':True,'org_fresh':True,'schema':8 if failure=='wrong_schema' else 11,
                    'catalog_total':0 if failure=='invalid_result' else 2,'management_count':1,'accounts_total':3}).encode()
            if args[:2]==['docker','ps']:
                self.assertIn('name=^/'+name+'$',args)
                return identity.encode() if state['exists'] else b''
            if args[:2]==['docker','inspect']:
                self.assertEqual(args[-1],identity)
                return json.dumps({'source':'unrelated' if failure=='wrong_source' else code.TARGET_COMMIT,
                    'project':'unrelated' if failure=='wrong_project' else 'naver-engine',
                    'user':'0:0' if failure=='wrong_user' else '10001:10001'}).encode()
            if args[:3]==['docker','rm','--force']:
                self.assertEqual(args[-1],identity)
                if failure=='remove_failure':
                    raise OSError('PRIVATE_REMOVE_ERROR')
                if failure!='still_running':
                    state['exists']=False
                return identity.encode()
            self.fail('Unexpected command '+str(args))
        release=SimpleNamespace(command=command,
            compose=lambda path,role:['docker','compose','--project-name','naver-'+role,'-f',str(path/'compose.yml')])
        with patch.object(code.uuid,'uuid4',return_value=SimpleNamespace(hex='a'*32)):
            try:
                result=code.warm_sources(Path('/synthetic-release'),release)
            except Exception as error:
                result=error
        return result,commands,state

    def test_success_timeout_and_script_failure_all_remove_only_exact_owned_oneoff_writer(self):
        for failure in (None,'create_timeout','wait_timeout','script_exit','invalid_result','wrong_schema'):
            with self.subTest(failure=failure):
                result,commands,state=self.scenario(failure)
                if failure is None:
                    self.assertIs(result['ok'],True)
                else:
                    self.assertIsInstance(result,Exception)
                    self.assertNotEqual(str(result),'WARM_CLEANUP_FAILED')
                self.assertFalse(state['exists'])
                self.assertEqual([args for args in commands if args[:2]==['docker','rm']],
                                 [['docker','rm','--force','b'*64]])
                self.assertEqual(commands[-1][:2],['docker','ps'])

    def test_mismatched_metadata_cleanup_error_or_remaining_writer_refuses_safe_rollback(self):
        for failure in ('wrong_source','wrong_project','wrong_user','remove_failure','still_running'):
            with self.subTest(failure=failure):
                result,commands,state=self.scenario(failure)
                self.assertEqual(str(result),'WARM_CLEANUP_FAILED')
                self.assertTrue(state['exists'])
                if failure.startswith('wrong_'):
                    self.assertFalse(any(args[:2]==['docker','rm'] for args in commands))

    def test_unconfirmed_create_with_no_visible_container_does_not_claim_safe_cleanup(self):
        result,commands,state=self.scenario('create_uncertain')
        self.assertEqual(str(result),'WARM_CLEANUP_FAILED')
        self.assertFalse(state['exists'])
        self.assertFalse(any(args[:2]==['docker','rm'] for args in commands))

    def test_warm_failure_retains_original_substep_after_cleanup_and_rejects_raw_script_messages(self):
        for failure,operation,code in (('wait_timeout','warm_wait','UNRECOGNIZED'),
                ('org_refused','warm_org_sync','ORG_NOT_ACCEPTED'),
                ('unrecognized_script_error','warm_result','SOURCE_WARM_FAILED')):
            with self.subTest(failure=failure):
                result,_,state=self.scenario(failure)
                details=result.failure_details
                self.assertEqual(details['failed_operation'],operation)
                self.assertEqual(details['failed_error_code'],code)
                self.assertNotIn('PRIVATE',json.dumps(details))
                self.assertFalse(state['exists'])


class DatabaseRollbackTest(unittest.TestCase):
    """Real isolated SQLite bytes; only privileged ownership and macOS flock interoperability are adapted."""
    ACTUAL = json.loads((Path(__file__).with_name('fixtures')/'naver_schema10_11_contract.json').read_text())

    def initialize_schema(self, connection, version):
        """Run the actual extracted initializer and SQL, with only the connection-owning Store shell adapted."""
        contract = self.ACTUAL['old' if version == 10 else 'new_observed_unsealed']
        self.assertEqual(self.ACTUAL['old']['authorizer'], self.ACTUAL['new_observed_unsealed']['authorizer'])
        scope = dict(SCHEMA_VERSION=version, _SCHEMA=tuple(contract['sql']), StoreError=RuntimeError,
                     _A=sqlite3, _REVISION_COLUMNS=contract['revision_columns'])
        exec(compile(contract['authorizer'], '<actual-store-authorizer>', 'exec'), scope)
        exec(compile(contract['migrate'], '<actual-store-initializer>', 'exec'), scope)
        owner = SimpleNamespace(_conn=connection, _tx=lambda: connection,
            _set_meta=lambda conn, key, value: conn.execute(
                'INSERT INTO naver_auto_meta (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                (key, value)))
        scope['_migrate'](owner)

    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='account-db-rollback-test-')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.data=self.root/'data';self.data.mkdir(mode=0o750)
        (self.root/'receipts').mkdir(mode=0o700)
        self.db=self.data/'engine.db'
        with closing(sqlite3.connect(self.db)) as connection, connection:
            self.initialize_schema(connection, 11)
            connection.executescript("CREATE TABLE business (id INTEGER PRIMARY KEY,value TEXT);"
                "INSERT INTO business VALUES (1,'preserved');")
            connection.execute("""INSERT INTO naver_auto_monthly_check
                (customer_id,period_start,period_end,snapshot_at,checked_at,status,spend,next_try_at)
                VALUES (1,'2026-10-01','2026-10-01','synthetic','synthetic','ok',100,'synthetic')""")
            self.old_schema = connection.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        self.db.chmod(0o600)
        self.code=sealed_code()
        def trusted_dir(path,**options):
            if options.get('new'):
                Path(path).mkdir(mode=options.get('mode',0o700))
            self.assertTrue(Path(path).is_dir())
        def write_new(path,body,**options):
            with Path(path).open('xb') as output:
                output.write(body);output.flush();os.fsync(output.fileno())
            Path(path).chmod(options.get('mode',0o600))
        self.release=SimpleNamespace(ROOT=self.root,trusted_dir=trusted_dir,write_new=write_new)
        self.upgrade=SimpleNamespace(read_file=lambda path,**options:Path(path).read_bytes())
        data_patch=patch.object(self.code,'DATA',self.data);data_patch.start();self.addCleanup(data_patch.stop)
        original_fstat=os.fstat
        def owned_identity(descriptor):
            # A non-root test host cannot chown to container uid 10001; retain real inode/mode/link checks.
            values=list(original_fstat(descriptor));values[4]=values[5]=10001
            return os.stat_result(values)
        owner_patch=patch.object(self.code.os,'fstat',side_effect=owned_identity)
        owner_patch.start();self.addCleanup(owner_patch.stop)
        if sys.platform=='darwin':
            # macOS flock conflicts with SQLite's own locks. Linux CI exercises the real lock.
            lock_patch=patch.object(self.code.fcntl,'flock')
            lock_patch.start();self.addCleanup(lock_patch.stop)
        self.identity='a'*32

    def mutate_schema11(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            self.initialize_schema(connection, 11)
            connection.execute("INSERT INTO naver_auto_manual_read (customer_id,requested_at,actor,period_start) VALUES (1,'synthetic',0,'2026-09-01')")
            connection.execute("UPDATE business SET value='new-schema-write'")

    def test_historical_schema10_initializer_still_cannot_open_the_schema11_snapshot(self):
        self.mutate_schema11()
        with closing(sqlite3.connect(self.db)) as connection:
            with self.assertRaisesRegex(RuntimeError, '이 엔진보다 새 저장 파일입니다'):
                self.initialize_schema(connection, 10)
            self.assertEqual(connection.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone(), ('11',))

    def test_running_source_checks_real_metadata_and_never_accepts_wrong_schema(self):
        for source, error in ((self.code.OLD_COMMIT, 'DB_OLD_SCHEMA'),
                              (self.code.TARGET_COMMIT, 'DB_TARGET_SCHEMA')):
            self.code.verify_database_schema(source,self.release,self.upgrade)
            with closing(sqlite3.connect(self.db)) as connection, connection:
                connection.execute("UPDATE naver_auto_meta SET value='10' WHERE key='schema_version'")
            with self.assertRaisesRegex(ValueError,error):
                self.code.verify_database_schema(source,self.release,self.upgrade)
            with closing(sqlite3.connect(self.db)) as connection, connection:
                connection.execute("UPDATE naver_auto_meta SET value='11' WHERE key='schema_version'")

    def test_real_schema11_failed_write_restores_schema11_snapshot_and_retains_failed_data(self):
        snapshot=self.code.db_snapshot(self.identity,self.release,self.upgrade)
        path,digest=snapshot
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.mutate_schema11()
        self.code.verify_database_schema(self.code.TARGET_COMMIT,self.release,self.upgrade)
        for suffix in ('-wal','-shm','-journal'):
            (self.data/('engine.db'+suffix)).write_bytes(('failed'+suffix).encode())
        self.code.restore_db(snapshot,self.identity,self.release,self.upgrade)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            self.assertEqual(connection.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone(),('11',))
            self.assertEqual(connection.execute('SELECT value FROM business').fetchone(),('preserved',))
            self.assertEqual(connection.execute('SELECT spend FROM naver_auto_monthly_check').fetchone(),(100,))
            self.assertEqual(connection.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall(),self.old_schema)
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE name='naver_auto_report_dirty'").fetchall(),[('naver_auto_report_dirty',)])
            self.assertEqual(connection.execute('SELECT customer_id,actor FROM naver_auto_manual_read').fetchall(),[])
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchall(),[('ok',)])
        # Failed DB and sidecars stay on the same filesystem as the restored live DB.
        quarantine=self.data/('.account-failed-db-'+self.identity)
        self.assertEqual({p.name for p in quarantine.iterdir()},
                         {'engine.db','engine.db-wal','engine.db-shm','engine.db-journal'})
        with closing(sqlite3.connect((quarantine/'engine.db').as_uri()+'?mode=ro&immutable=1',uri=True)) as failed:
            self.assertEqual(failed.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone(),('11',))
            self.assertEqual(failed.execute('SELECT spend FROM naver_auto_monthly_check').fetchone(),(100,))
            self.assertEqual(failed.execute('SELECT customer_id,actor FROM naver_auto_manual_read').fetchone(),(1,0))
            self.assertEqual(failed.execute('SELECT value FROM business').fetchone(),('new-schema-write',))
        self.code.verify_database_schema(self.code.OLD_COMMIT,self.release,self.upgrade)
        self.assertTrue(path.is_file())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
        self.assertFalse(any((self.data/('engine.db'+suffix)).exists() for suffix in ('-wal','-shm','-journal')))

    def test_lock_failure_does_not_create_snapshot_or_change_database(self):
        before=self.db.read_bytes()
        with patch.object(self.code.fcntl,'flock',side_effect=BlockingIOError('held')):
            with self.assertRaises(BlockingIOError):
                self.code.db_snapshot(self.identity,self.release,self.upgrade)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(list((self.root/'receipts').iterdir()),[])

    def test_changed_snapshot_digest_refuses_before_quarantining_or_overwriting_live_database(self):
        snapshot=self.code.db_snapshot(self.identity,self.release,self.upgrade)
        self.mutate_schema11();before=self.db.read_bytes()
        snapshot[0].write_bytes(snapshot[0].read_bytes()+b'tampered')
        with self.assertRaisesRegex(ValueError,'DB_SNAPSHOT_CHANGED'):
            self.code.restore_db(snapshot,self.identity,self.release,self.upgrade)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertFalse((self.data/('.account-failed-db-'+self.identity)).exists())

    def test_other_schema_is_not_accepted_as_the_schema11_rollback_snapshot(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE naver_auto_meta SET value='7' WHERE key='schema_version'")
        before=self.db.read_bytes()
        with self.assertRaisesRegex(ValueError,'DB_OLD_SCHEMA'):
            self.code.db_snapshot(self.identity,self.release,self.upgrade)
        self.assertEqual(self.db.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
