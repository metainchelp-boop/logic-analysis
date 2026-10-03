"""One-GET audit projections, no production network or secrets."""
import ast
import base64
import importlib.util
import json
import hashlib
import tempfile
from pathlib import Path
import types
import unittest
import urllib.request
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('link_audit', Path(__file__).parents[1]/'tools/naver_preview_link_audit.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class LinkAuditTest(unittest.TestCase):
    def test_empty_items_remains_distinct_from_bad_payload_and_field_types(self):
        empty = M.summarize_wire(200, b'{"status":200,"result":{"items":[]}}')
        self.assertEqual((empty['state'],empty['raw_items']), ('valid',0))
        for status, body, state in ((403,b'SECRET','http_error'),(200,b'SECRET','not_json'),
                (200,b'{"status":200,"result":[]}', 'bad_envelope'),
                (200,b'{"status":200,"result":{}}','bad_items')):
            result = M.summarize_wire(status,body)
            self.assertEqual(result['state'],state)
            self.assertIsNone(result['raw_items'])
            self.assertNotIn('SECRET',json.dumps(result))

    def test_other_path_method_query_body_cannot_reach_transport(self):
        for url, method, body in ((M.URL+'?x=1','GET',None),(M.URL,'POST',None),
                                 (M.URL.replace('naver-customer-ids','org-snapshot'),'GET',None),
                                 (M.URL,'GET',b'x')):
            underlying = Mock()
            audit = M.AuditTransport(underlying)
            with self.assertRaisesRegex(ValueError,'ERP_CALL_SCOPE'):
                audit.send(urllib.request.Request(url,data=body,method=method),30)
            underlying.send.assert_not_called()

    def test_memory_script_uses_normal_reader_once_and_no_write_entrypoints(self):
        module = types.ModuleType('memory_audit')
        exec(compile(SPEC.loader.get_source('link_audit'), '<approved>', 'exec'), module.__dict__)
        code = module.script().decode()
        ast.parse(code)
        self.assertIn('E.ErpReader(E.load_erp_key(),transport=audit,max_calls=1)',code)
        self.assertIn('ErpTunnelTransport(config.erp_tunnel_socket)',code)
        self.assertIn('S.open_reader',code)
        for forbidden in ('open_writer(', 'pair_links(', 'record_pairing(', 'confirm_prospects_hold(', '.reveal(', 'NaverReader('):
            self.assertNotIn(forbidden,code)

    def test_remote_projection_rejects_extra_fields_and_sanitizes_unknown_reason(self):
        value = dict(raw=M.summarize_wire(200,b'{"status":200,"result":{"items":[]}}'),
                     reader={'state':'ok','parsed_rows':0,'error_code':None},coverage=None,
                     dry_match={'state':'not_run','counts':{},'reasons':{}},erp_calls=1)
        self.assertEqual(M.project(value),value)
        for bad in (dict(value,secret='SECRET'),dict(value,erp_calls=2),dict(value,erp_calls=True)):
            with self.assertRaises(ValueError):
                M.project(bad)
        bad = dict(value, reader={'state':'failed','parsed_rows':None,'error_code':'SECRET'})
        self.assertEqual(M.project(bad)['reader']['error_code'],'UNRECOGNIZED')

    def test_workflow_bundle_below_single_environment_argument_limit(self):
        tools = Path(__file__).parents[1]/'tools'
        package = dict(baseline='a'*64,source_commit='b'*40,source_tar_gz_sha256='c'*64)
        bundle = dict(package=package,operation='preview-link-audit',function='run',
                      source=(tools/'naver_preview_link_audit.py').read_text(),
                      release_source=(tools/'naver_preview_release.py').read_text(),
                      host_source=(tools/'naver_erp_tunnel_service_install.py').read_text())
        encoded = base64.b64encode(json.dumps(bundle).encode())
        self.assertLess(len(encoded)+len('PREVIEW_OPS_B64='),131000)
        workflow = (tools.parents[1]/'.github/workflows/debug-rank.yml').read_text()
        self.assertEqual(workflow.count("'preview-link-audit'"),4)
        self.assertIn('preview-link-audit,',workflow)

    def test_same_wire_response_is_returned_unchanged_and_counted_without_identity(self):
        body = json.dumps({'status':200,'result':{'items':[
            {'possibility_id':987654321,'vendor':'NAVER_SEARCHAD','customer_id':'1234567','name':'SECRET'},
            {'possibility_id':987654322,'vendor':'SECRET_VENDOR','customer_id':1234567},
            {'possibility_id':987654323,'vendor':None}, None]}}).encode()
        underlying = Mock(); underlying.send.return_value = (200, body)
        audit = M.AuditTransport(underlying)
        request = urllib.request.Request('http://api.metainc.co.kr/api/ad-sync/naver-customer-ids', method='GET')
        self.assertEqual(audit.send(request, 30), (200, body))
        self.assertEqual(audit.summary['raw_items'], 4)
        self.assertEqual(audit.summary['vendor'], {'naver':1,'other':1,'null':1,'missing':0,'invalid':0})
        self.assertEqual(audit.summary['fields']['customer_id']['number'], 1)
        self.assertNotIn('SECRET', json.dumps(audit.summary))
        self.assertNotIn('987654321', json.dumps(audit.summary))
        with self.assertRaisesRegex(ValueError, 'ERP_CALL_SCOPE'):
            audit.send(request, 30)
        self.assertEqual(underlying.send.call_count, 1)



class ControllerTest(unittest.TestCase):
    def scenario(self, *, failure=None):
        package = {'baseline': 'a'*64, 'source_commit': 'b'*40, 'source_tar_gz_sha256': 'c'*64}
        cid, image = 'd'*64, 'sha256:'+'e'*64
        values = dict(raw=M.summarize_wire(200,b'{"status":200,"result":{"items":[]}}'),
                      reader={'state':'ok','parsed_rows':0,'error_code':None},coverage=None,
                      dry_match={'state':'not_run','counts':{},'reasons':{}},erp_calls=1)
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve()
            files = {}
            for name in ('compose.naver-engine.yml', 'preview-engine.override.yml', 'deploy/naver-engine-backup.override.yml'):
                file = path/name
                file.parent.mkdir(exist_ok=True)
                file.write_bytes(b'approved compose')
                files[str(file)] = hashlib.sha256(file.read_bytes()).hexdigest()
            receipt = path/('preview-'+package['source_commit']+'.json')
            receipt.write_text(json.dumps({'ok': True, 'stage': 'prepared', 'source_commit': package['source_commit'],
                'package': package, 'images': {'engine': image}, 'files': files}))
            started = receipt.with_name('preview-start-'+package['source_commit']+'.json')
            started.write_text(json.dumps({'ok': failure != 'receipt', 'stage': 'internal_ready',
                                          'source_commit': package['source_commit']}))
            release = Mock()
            release.prepared_paths.return_value = path, receipt
            release.sha.side_effect = lambda value: hashlib.sha256(value).hexdigest()
            release.unique.side_effect = dict
            release.compose.return_value = ['docker', 'compose', '--project-name', 'naver-engine']
            before = {'id': cid, 'image': image, 'running': True, 'user': '10001:10001',
                      'project': 'naver-engine', 'service': 'naver-engine', 'started': 'initial', 'restarts': 0,
                      'readonly': failure != 'rootfs',
                      'data': [{'Type': 'bind', 'Destination': '/var/lib/naver-engine',
                                'Source': '/legacy' if failure == 'mount' else '/var/lib/metainc/naver-engine'}]}
            inspections = 0
            def execute(args, **kwargs):
                nonlocal inspections
                calls.append((args, kwargs))
                if args[1:3] == ['image', 'inspect']:
                    return json.dumps({'id': image, 'user': '10001:10001',
                        'source': 'x' if failure == 'image' else package['source_commit']}).encode()
                if args[1] == 'compose':
                    return cid.encode()
                if args[1] == 'inspect':
                    inspections += 1
                    return json.dumps(dict(before, image='wrong') if failure == 'container' else
                        dict(before, restarts=1) if failure == 'restart' and inspections > 1 else before).encode()
                if args[1] == 'exec':
                    self.assertEqual(args, ['docker', 'exec', '-i', '--user', '10001:10001', cid, 'python', '-I', '-B', '-'])
                    self.assertIn(b'S.open_reader', kwargs['data'])
                    if failure == 'command':
                        raise RuntimeError('SENSITIVE_EXCEPTION')
                    return b'{"SECRET":1}' if failure == 'output' else json.dumps(values).encode()
                self.fail('Unexpected command')
            release.command.side_effect = execute
            host = Mock()
            host.baseline.side_effect = [package['baseline'], 'f'*64 if failure == 'baseline' else package['baseline']]
            with patch.object(M.os, 'geteuid', return_value=0):
                try:
                    result = M.run(package, host, release)
                except Exception as error:
                    result = error
            return result, calls


    def test_existing_identity_and_postflight_gates_are_preserved(self):
        result, calls = self.scenario()
        self.assertTrue(result['ok'])
        self.assertEqual(result['mode'], 'link-audit')
        self.assertEqual(result['audit']['reader']['parsed_rows'], 0)
        self.assertEqual(result['audit']['erp_calls'], 1)
        self.assertEqual(result['database_mutations'], 0)
        self.assertEqual(result['naver_calls'], 0)
        for failure in ('receipt','image','container','mount','rootfs','output','restart','baseline','command'):
            with self.subTest(failure=failure):
                result, calls = self.scenario(failure=failure)
                self.assertIsInstance(result, Exception)
                if failure in ('receipt','image','container','mount','rootfs'):
                    self.assertFalse(any(args[1]=='exec' for args,kw in calls))


if __name__ == '__main__':
    unittest.main()
