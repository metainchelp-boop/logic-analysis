"""Read-only status: allowlisted aggregates, approved container only, no host calls."""
import importlib.util
import ast
import json
import hashlib
import tempfile
import types
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('status_probe', Path(__file__).parents[1]/'tools/naver_preview_status.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class ProjectionTest(unittest.TestCase):
    def test_module_loaded_from_workflow_memory_can_build_reader_script(self):
        module = types.ModuleType('approved_status')
        exec(compile(SPEC.loader.get_source('status_probe'), '<approved-status>', 'exec'), module.__dict__)
        program = module.script()
        ast.parse(program)
        self.assertIn(b'S.open_reader', program)
        self.assertNotIn(b'open_writer', program)

    def test_project_only_known_codes_counts_and_time_not_payload(self):
        row = {'at': '2026-10-01T12:00:00+09:00', 'outcome': 'refused',
               'codes': ['ACCOUNTS_NONE', 'SENSITIVE_NAME'], 'row_count': 7,
               'manager_count': 2, 'absent_count': 1, 'body': 'SECRET',
               'detail': {'employee': 99}, 'sync_id': 15}
        result = M.project(row)
        self.assertEqual(result, {'at': row['at'], 'outcome': 'refused',
            'codes': ['ACCOUNTS_NONE', 'UNRECOGNIZED'], 'row_count': 7,
            'manager_count': 2, 'absent_count': 1})

    def test_bad_metadata_is_refused_and_unknown_network_codes_never_echo(self):
        base = {'at': '2026-10-01T12:00:00+09:00', 'outcome': 'accepted', 'codes': []}
        for change in ({'at': 'SECRET'}, {'at': '2026-10-01'}, {'outcome': 'SECRET'},
                       {'row_count': True}, {'row_count': -1}, {'codes': 'SECRET'}):
            with self.subTest(change=change), self.assertRaises((ValueError, TypeError)):
                M.project(dict(base, **change))
        self.assertEqual(M.project(dict(base, codes=['status-401', 'status-SECRET']))['codes'],
                         ['UNRECOGNIZED', 'status-401'])
        with self.assertRaises(ValueError):
            M.project(dict(base, counts={'employee-secret': 1}), True)


class ControllerTest(unittest.TestCase):
    def scenario(self, *, failure=None, commit='b'*40):
        package = {'baseline': 'a'*64, 'source_commit': commit, 'source_tar_gz_sha256': 'c'*64}
        cid, image = 'd'*64, 'sha256:'+'e'*64
        record = {'at': '2026-10-01T12:00:00+09:00', 'outcome': 'accepted', 'codes': [],
                  'row_count': 5, 'manager_count': 1, 'absent_count': 0}
        values = {kind: {'latest': dict(record), 'latest_accepted': dict(record)} for kind in M.KINDS}
        values['org']['latest'] = dict(record, outcome='failed', codes=['network-503'])
        values['pairing'] = {key: dict(record, counts={'prospects': 5}) for key in ('latest', 'latest_accepted')}
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

    def test_failed_latest_is_not_hidden_by_prior_accepted_or_runtime_ok(self):
        result, calls = self.scenario()
        self.assertIs(result['ok'], True)
        self.assertIs(result['all_latest_accepted'], False)
        self.assertEqual(result['sources']['org']['latest']['outcome'], 'failed')
        self.assertEqual(result['sources']['org']['latest_accepted']['outcome'], 'accepted')
        self.assertEqual(result['mutations'], 0)
        self.assertEqual(sum(args[1] == 'exec' for args, _ in calls), 1)
        self.assertNotIn('row_count', result['sources']['pairing']['latest'])

    def test_identity_refusals_never_exec(self):
        for failure in ('receipt', 'image', 'container', 'mount', 'rootfs'):
            with self.subTest(failure=failure):
                result, calls = self.scenario(failure=failure)
                self.assertIsInstance(result, ValueError)
                self.assertFalse(any(args[1] == 'exec' for args, _ in calls))

    def test_bad_result_restart_and_baseline_drift_are_not_reported_success(self):
        for failure in ('output', 'restart', 'baseline', 'command'):
            with self.subTest(failure=failure):
                result, _ = self.scenario(failure=failure)
                self.assertIsInstance(result, Exception)

    def test_package_cannot_select_database_or_unapproved_arguments(self):
        with self.assertRaises(ValueError):
            M.validate_package({'baseline': 'a'*64, 'source_commit': 'b'*40,
                                'source_tar_gz_sha256': 'c'*64, 'database': '/legacy'})

    def test_shm_lock_defect_release_refuses_before_host_access_and_fixed_release_reads(self):
        # a38c537: live engine-DB reads are suspended (incident 2026-10-05).
        package = {'baseline': 'a'*64, 'source_commit': 'a38c53775c112cdf5db420f979093d6bee9e5376',
                   'source_tar_gz_sha256': 'c'*64}
        host, release = Mock(), Mock()
        with self.assertRaisesRegex(ValueError, '^LIVE_READER_SUSPENDED$'):
            M.run(package, host, release)
        self.assertEqual(host.mock_calls, [])
        self.assertEqual(release.mock_calls, [])
        result, calls = self.scenario(commit='c21f5f05f610abf89df0c24e85c00b1bec23d01c')
        self.assertIs(result['ok'], True)
        self.assertEqual(result['source_commit'], 'c21f5f05f610abf89df0c24e85c00b1bec23d01c')
        self.assertEqual(sum(args[1] == 'exec' for args, _ in calls), 1)


if __name__ == '__main__':
    unittest.main()
