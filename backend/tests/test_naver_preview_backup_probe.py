import importlib.util
import ast
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import http.server
import shutil
import socketserver
import threading
import unittest
from contextlib import closing
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('backup_probe', Path(__file__).parents[1] / 'tools/naver_preview_backup_probe.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class BackupProbeTest(unittest.TestCase):
    def simulate(self, *, failure=None, mutate_image=False, changed_file=False, post_baseline=False, volumes=None):
        package = {'baseline': 'a'*64, 'source_commit': 'b'*40, 'run_id': '123456'}
        image = 'sha256:' + 'e'*64
        cid = 'f'*64
        body = b'SYNTHETIC_CONFIG_ONLY'
        prepared = {'ok': True, 'stage': 'prepared', 'source_commit': package['source_commit'],
                    'images': {'engine': image},
                    'files': {str(M.SECRET_ROOT/name): hashlib.sha256(body).hexdigest() for name in M.MOUNTS}}
        sent = {'status': 'synthetic_transfer_verified', 'ciphertext': {'sha256': 'c'*64, 'size': 1234},
                'expected_kst_date': '2026-10-01', 'expected_row_counts': {'synthetic_leads': 3, 'synthetic_events': 2}}
        calls = []
        def read(path, **kwargs):
            if str(path).endswith('.json'):
                return json.dumps(prepared).encode()
            return b'CHANGED' if changed_file else body
        def execute(args, **kwargs):
            calls.append((args, kwargs))
            if args[1:3] == ['image', 'inspect']:
                if failure == 'inspect':
                    raise RuntimeError('SENSITIVE_ERROR_MUST_NOT_LEAK')
                return json.dumps({'Id': 'sha256:'+'d'*64 if mutate_image else image,
                    'Config': {'User': '10001:10001', 'Labels': {'metainc.naver.preview.source': package['source_commit']},
                               'Volumes': volumes}}).encode()
            if args[1] == 'create':
                if failure == 'create':
                    raise RuntimeError('SENSITIVE_ERROR_MUST_NOT_LEAK')
                return cid.encode()
            if args[1] == 'start':
                if failure == 'start':
                    raise subprocess.TimeoutExpired(args, 450)
                if failure == 'receipt':
                    return b'{"secret":"SENSITIVE_ERROR_MUST_NOT_LEAK"}'
                return json.dumps(sent).encode()
            if args[1] == 'rm':
                if failure == 'cleanup':
                    raise RuntimeError('SENSITIVE_ERROR_MUST_NOT_LEAK')
                self.assertEqual(args, ['/usr/bin/docker', 'rm', '--force', cid])
                return cid.encode()
            self.fail('Unexpected command')
        host = Mock()
        host.baseline.side_effect = [package['baseline'], 'd'*64 if post_baseline else package['baseline']]
        with patch.object(M.os, 'geteuid', return_value=0), patch.object(M, 'read_trusted', side_effect=read), \
                patch.object(M, 'command', side_effect=execute):
            result = M.run(package, host)
        self.assertNotIn('SENSITIVE_ERROR_MUST_NOT_LEAK', json.dumps(result))
        return result, calls

    def test_success_means_engine_host_upload_only_not_readback_or_recovery(self):
        result, calls = self.simulate()
        self.assertTrue(result['ok'])
        self.assertTrue(result['engine_host_sender_verified'])
        for name in ['operating_data_used', 'production_data_mounted', 'scheduler_started',
                     'recovery_key_used', 'receiver_readback_verified', 'isolated_restore_verified']:
            self.assertIs(result[name], False)
        self.assertEqual([args[1] for args, _ in calls], ['image', 'create', 'start', 'rm'])
        start = next(options for args, options in calls if args[1] == 'start')
        self.assertEqual(start['data'], M.PROBE_SCRIPT.encode())

    def test_start_timeout_invalid_receipt_and_cleanup_failure_never_pass(self):
        for failure in ['start', 'receipt', 'cleanup']:
            with self.subTest(failure=failure):
                result, calls = self.simulate(failure=failure)
                self.assertFalse(result['ok'])
                self.assertTrue(result['manual_review_required'])
                self.assertEqual(sum(args[1] == 'rm' for args, _ in calls), 1)

    def test_create_failure_never_removes_an_existing_named_container(self):
        result, calls = self.simulate(failure='create')
        self.assertFalse(result['ok'])
        self.assertFalse(any(args[1] in ['start', 'rm'] for args, _ in calls))

    def test_image_inspect_failure_is_identifiable_without_creating_any_container(self):
        result, calls = self.simulate(failure='inspect')
        self.assertFalse(result['ok'])
        self.assertEqual(result['stage'], 'preflight_image_inspect')
        self.assertEqual([args[1] for args, _ in calls], ['image'])

    def test_image_inspect_errors_have_only_fixed_nonsecret_codes(self):
        args = ['/usr/bin/docker', 'image', 'inspect', '--format', 'fixture', 'synthetic:fixture']
        cases = [
            (b'template parsing error: map has no entry for key "Volumes"', 'INSPECT_TEMPLATE_ERROR'),
            (b'permission denied while trying to connect to the Docker daemon socket', 'DOCKER_ACCESS_DENIED'),
            (b'Error response from daemon: No such image: synthetic:fixture', 'IMAGE_MISSING'),
            (b'Cannot connect to the Docker daemon at unix:///synthetic/socket', 'DOCKER_DAEMON_UNAVAILABLE'),
            (b'unrecognized failure', 'COMMAND_FAILED'),
        ]
        for stderr, code in cases:
            with self.subTest(code=code):
                completed = subprocess.CompletedProcess(args, 1, b'SENSITIVE_STDOUT', stderr+b' SENSITIVE_DETAIL')
                with patch.object(M.subprocess, 'run', return_value=completed) as execute:
                    with self.assertRaises(RuntimeError) as caught:
                        M.command(args)
                    self.assertEqual(execute.call_count, 1)
                with patch.object(M, 'probe', side_effect=caught.exception):
                    receipt = M.run({}, Mock())
                self.assertFalse(receipt['ok'])
                self.assertEqual(receipt['error_code'], code)
                self.assertNotIn('SENSITIVE', json.dumps(receipt))
                self.assertTrue(receipt['manual_review_required'])

    def test_noninspect_stderr_stays_discarded_and_large_output_is_rejected(self):
        args = ['/usr/bin/docker', 'start', '--attach', '--interactive', 'f'*64]
        with patch.object(M.subprocess, 'run', return_value=subprocess.CompletedProcess(args, 0, b'x'*8193)) as execute:
            with self.assertRaises(RuntimeError) as caught:
                M.command(args)
            self.assertEqual(execute.call_args.kwargs['stderr'], subprocess.DEVNULL)
        with patch.object(M, 'probe', side_effect=caught.exception):
            self.assertEqual(M.run({}, Mock())['error_code'], 'OUTPUT_TOO_LARGE')

    def test_changed_image_or_secret_fails_before_any_container_creation(self):
        for options in [{'mutate_image': True}, {'changed_file': True}, {'volumes': {'/unexpected': {}}}]:
            with self.subTest(options=options):
                result, calls = self.simulate(**options)
                self.assertFalse(result['ok'])
                self.assertFalse(any(args[1] == 'create' for args, _ in calls))

    def test_actual_docker_template_handles_optional_volumes_and_projects_only_source_label(self):
        docker = shutil.which('docker')
        self.assertIsNotNone(docker, 'Docker CLI is required; this test never contacts a real daemon.')
        _, calls = self.simulate()
        args = calls[0][0]
        template = args[args.index('--format')+1]
        state = {}
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_HEAD(self):
                self.send_response(200)
                self.send_header('Api-Version', '1.52')
                self.end_headers()
            def do_GET(self):
                if self.path.endswith('/json'):
                    body = json.dumps(state['image']).encode()
                elif self.path.endswith('/_ping'):
                    body = b'OK'
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        with tempfile.TemporaryDirectory(prefix='nvp-') as folder:
            endpoint = str(Path(folder)/'engine.sock')
            with socketserver.UnixStreamServer(endpoint, Handler) as server:
                thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
                thread.start()
                try:
                    for declared in ('missing', None, {}, {'/unexpected': {}}):
                        config = {'User': '10001:10001', 'Labels': {
                            'metainc.naver.preview.source': 'b'*40, 'unrelated': 'SENSITIVE_LABEL'*1000}}
                        if declared != 'missing':
                            config['Volumes'] = declared
                        state['image'] = {'Id': 'sha256:'+'e'*64, 'Config': config}
                        result = subprocess.run([docker, 'image', 'inspect', '--format', template, 'synthetic:fixture'],
                            capture_output=True, timeout=10, env={'PATH': '/usr/bin:/bin',
                                'DOCKER_HOST': 'unix://'+endpoint, 'DOCKER_API_VERSION': '1.52', 'DOCKER_CONFIG': folder})
                        self.assertEqual(result.returncode, 0, result.stderr.decode())
                        self.assertNotIn(b'SENSITIVE_LABEL', result.stdout)
                        self.assertLess(len(result.stdout), 8192)
                        image = json.loads(result.stdout)
                        self.assertEqual(image['Config']['Volumes'], None if declared == 'missing' else declared)
                finally:
                    server.shutdown()
                    thread.join(timeout=5)

    def test_existing_application_baseline_change_is_not_reported_as_success(self):
        result, _ = self.simulate(post_baseline=True)
        self.assertFalse(result['ok'])

    def test_invalid_input_does_not_read_host_files_or_execute_commands(self):
        with patch.object(M, 'command') as command, patch.object(M, 'read_trusted') as read:
            self.assertFalse(M.run({'source_commit': '../escape'}, Mock())['ok'])
            command.assert_not_called()
            read.assert_not_called()

    def test_receipt_does_not_accept_impossible_date_or_noninteger_counts(self):
        good = {'status': 'synthetic_transfer_verified', 'ciphertext': {'sha256': 'c'*64, 'size': 1234},
                'expected_kst_date': '2026-10-01', 'expected_row_counts': {'synthetic_leads': 3, 'synthetic_events': 2}}
        for change in [{'expected_kst_date': '2026-99-99'},
                       {'expected_row_counts': {'synthetic_leads': 3.0, 'synthetic_events': 2}}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                M.validate_receipt(dict(good, **change))

    def test_file_reader_rejects_symlink_public_permissions_and_hardlink(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder).resolve()/'config'
            target.write_bytes(b'SYNTHETIC_CONFIG_ONLY')
            target.chmod(0o600)
            kwargs = {'uid': os.getuid(), 'gid': os.getgid()}
            self.assertEqual(M.read_trusted(target, **kwargs), b'SYNTHETIC_CONFIG_ONLY')
            link = target.parent/'link'
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                M.read_trusted(link, **kwargs)
            target.chmod(0o644)
            with self.assertRaises(ValueError):
                M.read_trusted(target, **kwargs)
            target.chmod(0o600)
            os.link(target, target.parent/'hardlink')
            with self.assertRaises(ValueError):
                M.read_trusted(target, **kwargs)

    def test_embedded_snapshot_really_contains_only_three_leads_and_two_events(self):
        tree = ast.parse(M.PROBE_SCRIPT)
        snapshot = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'snapshot')
        namespace = {'sqlite3': sqlite3, 'closing': closing}
        exec(compile(ast.Module(body=[snapshot], type_ignores=[]), '<synthetic-snapshot>', 'exec'), namespace)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'synthetic.db'
            self.assertEqual(namespace['snapshot'](target), {'synthetic_leads': 3, 'synthetic_events': 2})
            with closing(sqlite3.connect(target)) as db:
                tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
                self.assertEqual(tables, [('synthetic_events',), ('synthetic_leads',)])
                self.assertEqual(db.execute('SELECT * FROM synthetic_leads').fetchall(), [(1,10),(2,20),(3,30)])
                self.assertEqual(db.execute('SELECT * FROM synthetic_events').fetchall(), [(1,'test-only'),(2,'not-operating-data')])

    def test_container_is_fresh_nonroot_readonly_with_only_three_backup_mounts(self):
        args = M.container_command('sha256:' + 'e'*64, '123456')
        self.assertEqual(args[:2], ['/usr/bin/docker', 'create'])
        self.assertIn('--read-only', args)
        self.assertEqual(args[args.index('--user')+1], '10001:10001')
        self.assertEqual(args[args.index('--cap-drop')+1], 'ALL')
        self.assertEqual(args[args.index('--network')+1], 'bridge')
        self.assertEqual(args[args.index('--entrypoint')+1], 'python')
        self.assertEqual(args[-4:], ['sha256:'+'e'*64, '-I', '-B', '-'])
        mounts = [args[i+1] for i, value in enumerate(args) if value == '--mount']
        self.assertEqual(len(mounts), 3)
        self.assertTrue(all(value.endswith(',readonly') for value in mounts))
        self.assertFalse(any(word in ' '.join(args) for word in
                             ['runtime.env', 'engine.db', '/var/lib/', '/var/backups/', 'erp.sock', '--env-file', '--privileged']))

    def test_identifiers_are_fixed_and_input_cannot_supply_paths_or_commands(self):
        good = {'baseline': 'a'*64, 'source_commit': 'b'*40, 'run_id': '123456'}
        self.assertEqual(M.validate_package(good), good)
        for field in good:
            with self.subTest(field=field), self.assertRaises(ValueError):
                M.validate_package(dict(good, **{field: '../bad'}))
        with self.assertRaises(ValueError):
            M.validate_package(dict(good, path='/tmp/elsewhere'))


if __name__ == '__main__':
    unittest.main()
