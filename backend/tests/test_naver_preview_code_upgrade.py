import importlib.util
import base64
import io
import json
import tarfile
import textwrap
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import test_naver_preview_upgrade as legacy_test


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1]/'tools'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractTest(unittest.TestCase):
    def test_only_exact_approved_code_transition_is_accepted_without_bootstrap_request(self):
        module = load('naver_preview_code_upgrade')
        release = load('naver_preview_release')
        package = dict(baseline='a'*64, source_commit=module.TARGET_COMMIT,
                       ciphertext_sha256='b'*64, source_tar_gz_sha256='c'*64,
                       run_id='123456', operation='code-prepare')
        self.assertEqual(module.validate_package(package, release), package)
        for changes in ({'source_commit': module.OLD_COMMIT}, {'operation': 'upgrade-prepare'},
                        {'request': {}}, {'source_commit': 'f'*40}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                module.validate_package(dict(package, **changes), release)
        host = Mock()
        with self.assertRaises(ValueError):
            module.apply({'release': package, 'request': {}}, host, release, Mock(), Mock())
        host.assert_not_called()

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
        with patch.object(legacy_test, 'M', fixture), patch.object(code, 'TARGET_COMMIT', 'b'*40):
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
        for reason in ('image','unit','manifest','schema','infrastructure','override','bootstrap_pending'):
            with self.subTest(reason=reason):
                result,commands,writes,_,_=self.scenario(reason)
                self.assertIsInstance(result,Exception)
                self.assertEqual(writes,[])
                self.assertFalse(any(args[:2]==['/usr/bin/systemctl','stop'] for args in commands))

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
            code.verify_running(Path('/old'),{},release,life,upgrade)

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

    def test_both_remote_bundles_fit_linux_single_environment_value_limit(self):
        tools=Path(__file__).parents[1]/'tools'
        source=lambda name:(tools/(name+'.py')).read_text()
        package=dict(baseline='a'*64,source_commit='b'*40,ciphertext_sha256='c'*64,
                     source_tar_gz_sha256='d'*64,run_id='9'*20,operation='code-prepare')
        shared=dict(host_source=source('naver_erp_tunnel_service_install'),
                    lifecycle_source=source('naver_preview_lifecycle'),
                    upgrade_source=source('naver_preview_upgrade'))
        prepare=dict(shared,package=package,source=source('naver_preview_release'),
                     code_source=source('naver_preview_code_upgrade'))
        apply=dict(shared,package=dict(release=package,operation_id='e'*32),
                   operation='preview-code-upgrade',function='apply',
                   source=source('naver_preview_code_upgrade'),release_source=source('naver_preview_release'))
        for bundle in (prepare,apply):
            self.assertLess(len(base64.b64encode(json.dumps(bundle).encode()))+len('PREVIEW_RELEASE_B64='),131000)


if __name__ == '__main__':
    unittest.main()
