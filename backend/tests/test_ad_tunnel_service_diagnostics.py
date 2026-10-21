"""전용 unit 상태 진단: 합성 출력만 사용하며 로그/키 원문을 노출하지 않는다."""
import json
import subprocess
import errno
from pathlib import Path
from unittest.mock import MagicMock
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from test_ad_tunnel_preflight import module


class ServiceDiagnosticsTests(unittest.TestCase):
    def test_diagnostic_reports_only_scalars_counts_and_exit_codes(self):
        ns = module()
        calls = []
        def probe(args):
            calls.append(args)
            if args[0] == 'systemctl':
                return subprocess.CompletedProcess(args, 0, '\n'.join((
                    'ActiveState=failed', 'SubState=failed', 'Result=exit-code', 'ExecMainCode=1',
                    'ExecMainStatus=226', 'NRestarts=0',
                    'ExecStartPre={ path=/private-marker; argv[]=/private-marker secret; code=exited ; status=226 ; }')), '')
            return subprocess.CompletedProcess(args, 0, '\n'.join((
                json.dumps({'MESSAGE': 'private-marker Failed at step NAMESPACE: Permission denied status=226'}),
                json.dumps({'MESSAGE': 'private-marker BPF IPAddress policy'}),
                json.dumps({'MESSAGE': 'private-marker GROUP EXEC exit-status'}))), '')
        group = SimpleNamespace(gr_gid=10001, gr_name='metainc-naver-erp-tunnel', gr_mem=['private-marker'])
        connection = MagicMock()
        with patch.dict(ns, probe=probe, metadata=lambda _: {'exists': False},
                tunnel_public_file_metadata=lambda _: {'exists': False, 'sha256': None}), \
                patch.object(ns['grp'], 'getgrgid', return_value=group), \
                patch.object(Path, 'resolve', return_value=Path('/synthetic/python')), \
                patch.object(ns['os'], 'access', return_value=False), \
                patch.object(ns['socket'], 'create_connection', side_effect=[connection, OSError(errno.EACCES, 'private-marker')]) as tcp:
            result = ns['tunnel_service_diagnostics']()
        self.assertEqual(result['exec_start_pre'], {'code': 1, 'status': 226})
        self.assertEqual(result['state']['ExecMainStatus'], 226)
        self.assertEqual(result['journal']['pattern_counts'], {'exec': 1, 'group': 1, 'namespace': 1,
            'permission': 1, 'bpf': 1, 'ip_address': 1, 'exit_status': 2})
        self.assertEqual(result['tcp_once'], {'be_ssh': {'success': True, 'errno': None},
            'loopback_ssh': {'success': False, 'errno': errno.EACCES}})
        self.assertEqual([call.args[0] for call in tcp.call_args_list], [('1.234.23.117', 22), ('127.0.0.1', 22)])
        self.assertTrue(all(call.kwargs == {'timeout': 2} for call in tcp.call_args_list))
        self.assertEqual(calls[1], ['journalctl', '--unit=metainc-naver-erp-tunnel.service', '-n', '30', '-o', 'json', '--no-pager'])
        self.assertEqual(set(result['files']), {'unit', 'ssh_config', 'known_hosts', 'bpf_probe'})
        self.assertNotIn('private-marker', json.dumps(result))

    def test_missing_commands_or_nontext_journal_do_not_leak_or_claim_success(self):
        ns = module()
        for value in (None, subprocess.CompletedProcess([], 0, '{"MESSAGE":[1,2]}\ninvalid\n[]', '')):
            with patch.dict(ns, probe=lambda _: value, metadata=lambda _: {'exists': False},
                    tunnel_public_file_metadata=lambda _: {'exists': False, 'sha256': None}), \
                    patch.object(ns['grp'], 'getgrgid', side_effect=KeyError), \
                    patch.object(Path, 'resolve', side_effect=FileNotFoundError), \
                    patch.object(ns['socket'], 'create_connection', side_effect=TimeoutError('private-marker')):
                result = ns['tunnel_service_diagnostics']()
            self.assertEqual(result['exec_start_pre'], {'code': None, 'status': None})
            self.assertTrue(all(value is None for value in result['state'].values()))
            self.assertFalse(result['group']['exists'])
            self.assertEqual(result['journal']['parsed_rows'], 0)
            self.assertFalse(result['tcp_once']['be_ssh']['success'])
            self.assertNotIn('private-marker', json.dumps(result))

    def test_only_public_file_paths_are_hashed_and_no_service_mutation_is_called(self):
        import ast
        from test_ad_tunnel_preflight import source
        functions = {node.name: node for node in ast.parse(source()).body if isinstance(node, ast.FunctionDef)}
        diagnostic = ast.unparse(functions['tunnel_service_diagnostics'])
        self.assertNotIn('id_ed25519', diagnostic)
        self.assertNotIn("'restart'", diagnostic)
        self.assertNotIn("'start'", diagnostic)
        self.assertNotIn("'stop'", diagnostic)
        for forbidden in ('chmod', 'chown', 'write_bytes', 'write_text', 'mkdir', 'unlink'):
            self.assertNotIn(forbidden, diagnostic)


if __name__ == '__main__':
    unittest.main()
