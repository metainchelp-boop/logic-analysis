import contextlib
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / 'app_inventory.py'
spec = importlib.util.spec_from_file_location('app_inventory', MODULE_PATH)
inventory = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = inventory
spec.loader.exec_module(inventory)

CANARY = 'PRIVATE_CANARY_customer_token_923857'
CONTAINER_ID = 'a' * 64
IMAGE_ID = 'sha256:' + 'b' * 64


class FakeRunner:
    def __init__(self, containers=None):
        self.calls = []
        self.containers = containers or {}
        self.fail = {}

    def __call__(self, argv, timeout, max_bytes):
        self.calls.append(argv)
        key = tuple(argv[:3])
        if key in self.fail:
            return self.fail[key]
        if argv[:3] == ['docker', 'ps', '-a']:
            return inventory.CommandResult(stdout='\n'.join(self.containers))
        if argv[:2] == ['docker', 'inspect']:
            return inventory.CommandResult(stdout=json.dumps(self.containers[argv[-1]]))
        if argv[:3] == ['docker', 'image', 'inspect']:
            return inventory.CommandResult(stdout=json.dumps({'id': IMAGE_ID, 'size': 12345,
                'tags': ['autobid-autobid-web:' + CANARY], 'revision': 'c' * 40}))
        if argv[:3] == ['docker', 'image', 'ls']:
            return inventory.CommandResult(stdout=json.dumps({'id': IMAGE_ID, 'repository': 'autobid-autobid-web'}) + '\n')
        if argv[:3] == ['docker', 'volume', 'ls']:
            return inventory.CommandResult(stdout='autobid_autobid-data\n' + CANARY + '\n')
        if argv[:3] == ['docker', 'volume', 'inspect']:
            return inventory.CommandResult(stdout=json.dumps({'name': argv[-1], 'driver': 'local',
                'mountpoint': '/var/lib/docker/volumes/autobid_autobid-data/_data'}))
        if argv[0] == 'du':
            return inventory.CommandResult(stdout='8192\t' + argv[-1] + '\n')
        if argv[0] == 'systemctl':
            if argv[1] in ('list-unit-files', 'list-units'):
                return inventory.CommandResult(stdout='naver-engine.service enabled\n' + CANARY + ' enabled\n')
            return inventory.CommandResult(stdout='Id=naver-engine.service\nActiveState=active\nSubState=running\nMainPID=24\nNRestarts=0\nUnitFileState=enabled\nFragmentPath=/etc/systemd/system/naver-engine.service\nDropInPaths=/etc/systemd/system/' + CANARY + '\nRequires=naver-relay.service ' + CANARY + '\n')
        if argv[0] == 'crontab':
            return inventory.CommandResult(stdout='0 3 * * * TOKEN=' + CANARY + ' /root/autobid-archive/backup.sh\n0 4 * * * curl https://' + CANARY + '\n')
        if argv[:2] == ['nginx', '-T']:
            return inventory.CommandResult(1, stdout=CANARY)
        if argv[0] == 'git':
            if argv[-1] == '--show-toplevel':
                return inventory.CommandResult(stdout=argv[2] + '\n')
            if argv[-1] == 'HEAD' and 'symbolic-ref' not in argv:
                return inventory.CommandResult(stdout='d' * 40 + '\n')
            return inventory.CommandResult(stdout=CANARY)
        return inventory.CommandResult(1, stdout=CANARY)


def raw_container(**changes):
    result = {'id': CONTAINER_ID, 'name': '/autobid_web', 'image_id': IMAGE_ID,
              'image': 'autobid-autobid-web:' + CANARY, 'status': 'running', 'running': True,
              'pid': 52, 'restart_count': 0, 'restart_policy': 'always',
              'started_at': '2026-11-01T01:02:03.123Z', 'finished_at': CANARY,
              'mounts': [{'Type': 'volume', 'Name': 'autobid_autobid-data',
                          'Source': '/var/lib/docker/volumes/autobid_autobid-data/_data',
                          'Destination': '/srv/autobid/data', 'RW': True},
                         {'Type': 'bind', 'Source': '/private/' + CANARY,
                          'Destination': '/' + CANARY, 'RW': False}],
              'ports': {'5070/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '5070'}],
                        CANARY: [{'HostIp': CANARY, 'HostPort': CANARY}]},
              'network_mode': CANARY,
              'labels': {'com.docker.compose.project': 'autobid',
                         'com.docker.compose.service': 'autobid_web',
                         'com.docker.compose.project.working_dir': '/root/content-studio-deploy',
                         'com.docker.compose.project.config_files': '/root/content-studio-deploy/docker-compose.yml,/' + CANARY,
                         'org.opencontainers.image.revision': 'e' * 40,
                         'metainc.naver.preview.source': 'f' * 40,
                         'org.opencontainers.image.source': 'https://' + CANARY,
                         CANARY: CANARY},
              'env_keys': ['DB_PATH', 'AUTOBID_DATABASE_URL', 'NAVER_X_' + CANARY,
                           'STUDIO_USERS_DB', CANARY]}
    result.update(changes)
    return result


class AppInventoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def file(self, path, data=b'PRIVATE_DATABASE_CONTENT'):
        real = self.root + path
        os.makedirs(os.path.dirname(real), exist_ok=True)
        with open(real, 'wb') as handle:
            handle.write(data)
        return real

    def test_full_synthetic_inventory_canary_no_mutation(self):
        self.file('/root/content-studio-deploy/data/studio.db')
        self.file('/var/lib/docker/volumes/autobid_autobid-data/_data/autobid.db')
        self.file('/etc/crontab', ('0 4 * * * root SECRET=' + CANARY + ' /root/content-studio-deploy/job\n').encode())
        self.file('/etc/cron.d/' + CANARY, ('@daily TOKEN=' + CANARY + ' naver-backup\n').encode())
        runner = FakeRunner({CONTAINER_ID: raw_container()})
        result = inventory.collect(runner=runner, root=self.root)
        encoded = json.dumps(result)
        self.assertNotIn(CANARY, encoded)
        self.assertNotIn('PRIVATE_DATABASE_CONTENT', encoded)
        self.assertNotIn('Config.Env', encoded)
        self.assertTrue(result['read_only'])
        self.assertEqual(result['docker']['containers'][0]['app'], 'autobid')
        self.assertEqual(result['docker']['containers'][0]['labels']['metainc.naver.preview.source'], 'f' * 40)
        self.assertEqual(result['docker']['containers'][0]['environment_presence']['AUTOBID_DATABASE_URL'], True)
        self.assertEqual(result['docker']['volumes'][0]['metadata']['usage_bytes'], 8192)
        self.assertEqual(result['git'][0]['head'], 'd' * 40)
        self.assertEqual(result['systemd']['units'][0]['NRestarts'], 0)
        self.assertEqual(result['cron'][0]['summary']['apps']['autobid']['count'], 1)
        for argv in runner.calls:
            self.assertIsInstance(argv, list)
            self.assertNotIn(CANARY, repr(argv))
            if argv[0] == 'docker':
                self.assertIn(tuple(argv[:2]), [('docker', 'ps'), ('docker', 'inspect'), ('docker', 'image'), ('docker', 'volume')])
            self.assertNotIn(argv[0], ('sh', 'bash', 'curl', 'sqlite3', 'openssl'))
        self.assertFalse(os.path.exists(self.root + '/var/lib/metainc/naver-deploy'))

    def test_unknown_dynamic_paths_are_not_queried(self):
        runner = FakeRunner({CONTAINER_ID: raw_container(name='/' + CANARY + '/ad-api',
            mounts=[{'Type': 'volume', 'Name': CANARY, 'Source': '/var/lib/docker/volumes/' + CANARY + '/_data',
                     'Destination': '/' + CANARY, 'RW': True}])})
        result = inventory.collect(runner, self.root)
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertEqual(result['docker']['containers'][0]['name'], inventory.REDACTED)
        self.assertEqual(result['docker']['volumes'][0]['name'], 'autobid_autobid-data')
        self.assertNotIn(CANARY, repr(runner.calls))

    def test_inspect_template_avoids_environment_values_and_health_logs(self):
        template = inventory.container_template()
        self.assertIn('index (split $e "=") 0', template)
        self.assertNotIn('{{json .Config.Env}}', template)
        self.assertNotIn('{{json .Config}}', template)
        self.assertNotIn('{{json .State}}', template)
        self.assertNotIn('Health', template)
        self.assertNotIn('ExecStart', template)

    def test_symlink_ancestor_refused_without_du_or_content_read(self):
        outside = tempfile.TemporaryDirectory()
        try:
            os.makedirs(self.root + '/root')
            os.symlink(outside.name, self.root + '/root/content-studio-deploy')
            runner = FakeRunner()
            collector = inventory.Collector(runner, self.root)
            result = collector.metadata('/root/content-studio-deploy/data/studio.db', usage=True)
            self.assertEqual(result['status'], 'symlink_refused')
            self.assertEqual(runner.calls, [])
        finally:
            outside.cleanup()

    def test_file_metadata_does_not_open_database_or_key(self):
        self.file('/root/ad-dashboard-deploy/data/secret.key', CANARY.encode())
        collector = inventory.Collector(FakeRunner(), self.root)
        with mock.patch('builtins.open', side_effect=AssertionError('no file contents')):
            result = collector.metadata('/root/ad-dashboard-deploy/data/secret.key')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['size_bytes'], len(CANARY))
        self.assertNotIn(CANARY, json.dumps(result))

    def test_failed_and_truncated_queries_never_become_empty_success(self):
        for failed in (inventory.CommandResult(2, CANARY),
                       inventory.CommandResult(0, CANARY, truncated=True),
                       inventory.CommandResult(-1, CANARY, error='timeout')):
            runner = FakeRunner()
            runner.fail[('docker', 'ps', '-a')] = failed
            result = inventory.collect(runner, self.root)
            self.assertEqual(result['docker']['inventory_status'], 'unavailable')
            self.assertNotIn(CANARY, json.dumps(result))
            self.assertNotEqual(result['coverage'][0]['status'], 'ok')

    def test_runner_exception_text_never_emitted(self):
        def failing(*args, **kwargs):
            raise OSError(CANARY)
        result = inventory.collect(failing, self.root)
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertTrue(any(row['status'] == 'runner_error' for row in result['coverage']))

    def test_bad_container_id_not_passed_to_inspect(self):
        runner = FakeRunner({CANARY: raw_container()})
        result = inventory.collect(runner, self.root)
        self.assertEqual(result['docker']['inventory_status'], 'unavailable')
        self.assertFalse(any(argv[:2] == ['docker', 'inspect'] for argv in runner.calls))

    def test_named_volume_paths_and_app_classification(self):
        for value in ('ad-api', 'ad-dashboard-deploy-ad-api', 'content-studio', 'autobid_web',
                      'autobid-autobid-engine', 'naver-engine', 'naver-relay', 'logic-analysis'):
            self.assertIsNotNone(inventory.classify(value), value)
        self.assertIsNone(inventory.safe_path('/root/content-studio-deploy/data/' + CANARY))
        self.assertIsNone(inventory.safe_path('/root/content-studio-deploy/../' + CANARY))
        self.assertIsNotNone(inventory.safe_path('/var/lib/docker/volumes/autobid_autobid-data/_data/autobid.db-wal'))

    def test_image_and_volume_inventory_survive_no_container(self):
        result = inventory.collect(FakeRunner(), self.root)
        self.assertEqual(result['docker']['total_containers'], 0)
        self.assertEqual(result['docker']['image_list_status'], 'ok')
        self.assertEqual(result['docker']['images'][0]['id'], IMAGE_ID)
        self.assertEqual(result['docker']['volume_list_status'], 'ok')
        self.assertEqual(result['docker']['volumes'][0]['name'], 'autobid_autobid-data')
        self.assertEqual(result['docker']['unclassified_volume_count'], 1)

    def test_actual_protected_units_and_content_basename_allowlist(self):
        for name in ('metainc-naver-engine.service', 'metainc-naver-relay.service',
                     'metainc-naver-erp-tunnel.service', 'docker.service', 'nginx.service'):
            self.assertIn(name, inventory.UNITS)
        for name in ('auth.db', 'clients.db', 'categories.db', 'copy_library.db', 'references.db',
                     'feedback.db', 'share.db', 'usage.db', 'support.db'):
            self.assertIsNotNone(inventory.safe_path('/root/content-studio-deploy/data/' + name))

    def test_absent_known_files_aggregate_not_large_repeated_rows(self):
        self.file('/root/content-studio-deploy/data/auth.db')
        result = inventory.collect(FakeRunner(), self.root)
        rows = [row for row in result['paths'] if row['path'] == '/root/content-studio-deploy']
        self.assertEqual(len(rows[0]['known_files']), 1)
        self.assertGreater(rows[0]['absent_known_file_count'], 100)
        self.assertLess(len(json.dumps(result)), 20000)

    def test_nginx_parser_linkage_returns_allowlisted_result(self):
        runner = FakeRunner()
        original = runner.__call__
        def nginx_ok(argv, timeout, max_bytes):
            if argv == ['nginx', '-T']:
                return inventory.CommandResult(stdout='# configuration file /etc/nginx/nginx.conf:\nhttp { server { listen 443; server_name logic.metainc.co.kr; location /autobid/ { proxy_pass http://127.0.0.1:5070; proxy_set_header Authorization ' + CANARY + '; } } }')
            return original(argv, timeout, max_bytes)
        result = inventory.collect(nginx_ok, self.root)
        self.assertNotEqual(result['nginx'].get('status'), 'parser_unavailable_or_failed')
        self.assertNotIn(CANARY, json.dumps(result))

    def test_cron_only_schedule_and_counts_survive(self):
        result = inventory.Collector.cron_summary('TOKEN=' + CANARY + '\n# ' + CANARY + '\n@daily KEY=' + CANARY + ' autobid\n0 1 * * * naver-engine --key ' + CANARY)
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertEqual(result['apps']['autobid']['schedules'], ['@daily'])
        self.assertEqual(result['apps']['naver']['count'], 1)
        self.assertEqual(result['unparsed_noncomment_lines'], 1)

    def test_release_paths_are_finite_and_unknown_filenames_never_queried(self):
        base = '/srv/metainc/ad-deploy-staging/releases/naver-' + 'a' * 40
        for name in ('compose.naver-engine.yml', 'compose.naver-relay.yml',
                     'deploy/naver-engine-backup.override.yml', 'preview-engine.override.yml',
                     'preview-relay.override.yml'):
            self.assertEqual(inventory.safe_path(base + '/' + name), base + '/' + name)
        companion = '/srv/metainc/ad-deploy-staging/saved-exports/' + 'b' * 32 + '/naver-saved-exports.override.yml'
        self.assertEqual(inventory.safe_path(companion), companion)
        unknown = base + '/naver-private-customer-secret.yml'
        self.assertIsNone(inventory.safe_path(unknown))
        runner = FakeRunner()
        collector = inventory.Collector(runner, self.root)
        with mock.patch.object(inventory.os, 'lstat', side_effect=AssertionError('unknown metadata forbidden')):
            result = collector.metadata(unknown, usage=True)
            mounts = collector.mounts([{'Type': 'bind', 'Source': unknown,
                                       'Destination': '/app/data', 'RW': True}])
        self.assertNotIn('private-customer-secret', json.dumps([result, mounts]))
        self.assertEqual(result['status'], 'unapproved_path')
        self.assertEqual(runner.calls, [])
        self.assertIsNone(inventory.safe_path(companion.replace('naver-saved-exports', 'naver-private')))

    def test_compose_service_identifies_autobid_in_shared_content_project(self):
        raw = raw_container(name='/content-studio-deploy-autobid_web-1',
                            image='content-studio-deploy-autobid-web:latest')
        raw['labels']['com.docker.compose.project'] = 'content-studio-deploy'
        raw['labels']['com.docker.compose.service'] = 'autobid_web'
        row = inventory.Collector(FakeRunner(), self.root).container(raw)
        self.assertEqual(row['app'], 'autobid')
        self.assertEqual(inventory.classify(name='content-studio', labels={
            'com.docker.compose.service': 'autobid_web'}), 'autobid')

    def test_related_unknown_supervisors_redacted_and_incomplete(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            if argv[1] in ('list-unit-files', 'list-units'):
                return inventory.CommandResult(stdout='autobid-keepalive.service enabled\n'
                    'autobid-keepalive.timer enabled\nautobid-' + CANARY + '.service enabled\n')
            raise AssertionError('unknown units must not be queried')
        result = inventory.Collector(runner, self.root).systemd()
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['related_unapproved_unit_count'], 3)
        self.assertEqual(result['units'], [])
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertNotIn('autobid-keepalive', json.dumps(result))
        self.assertEqual(len(calls), 2)

    def test_compose_config_file_truncation_is_explicit_and_partial(self):
        raw = raw_container()
        raw['labels']['com.docker.compose.project.config_files'] = ','.join(
            ['/root/content-studio-deploy/docker-compose.yml'] * 9)
        result = inventory.collect(FakeRunner({CONTAINER_ID: raw}), self.root)
        row = result['docker']['containers'][0]
        self.assertEqual(len(row['labels']['com.docker.compose.project.config_files']), 8)
        self.assertEqual(row['compose_config_files_total_count'], 9)
        self.assertTrue(row['compose_config_files_truncated'])
        self.assertEqual(row['compose_config_files_status'], 'incomplete')
        self.assertEqual(result['docker']['inventory_status'], 'partial')

    def test_cron_numeric_secrets_and_out_of_range_schedules_never_emitted(self):
        secret = '934857238495702384950234'
        bad = (secret + ' * * * * autobid\n60 0 1 1 0 naver-engine\n'
               '0 24 1 1 0 autobid\n0 0 32 1 0 autobid\n0 0 1 13 0 autobid\n'
               '0 0 1 1 8 autobid\n*/0 * * * * autobid\n1-0 * * * * autobid\n'
               '*/' + secret + ' * * * * autobid\n1,,2 * * * * autobid\n')
        result = inventory.Collector.cron_summary(bad)
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result['unparsed_noncomment_lines'], 10)
        self.assertEqual(result['apps']['autobid']['count'], 0)

    def test_cron_valid_ranges_steps_lists_and_zero_padding(self):
        result = inventory.Collector.cron_summary(
            '*/15 0-23/2 1,15 1-12 0,7 autobid\n05 01 01 01 0 naver-engine\n'
            '0,30 1,12 1-31/2 */2 1-5 content-studio\n')
        self.assertEqual(result['unparsed_noncomment_lines'], 0)
        self.assertEqual(result['apps']['autobid']['schedules'], ['*/15 0-23/2 1,15 1-12 0,7'])
        self.assertEqual(result['apps']['naver']['schedules'], ['05 01 01 01 0'])

    def test_statvfs_preserves_nonroot_available(self):
        info = mock.Mock(f_blocks=100, f_bfree=20, f_bavail=5, f_frsize=4096)
        with mock.patch.object(inventory.os, 'statvfs', return_value=info):
            result = inventory.Collector(FakeRunner(), self.root).filesystem()
        self.assertEqual(result['available_nonroot_bytes'], 5 * 4096)
        self.assertEqual(result['free_bytes'], 20 * 4096)

    def test_subprocess_runner_captures_only_bounded_stdout(self):
        result = inventory.run_command([sys.executable, '-I', '-c',
            'import sys;sys.stdout.write("safe");sys.stderr.write("' + CANARY + '")'], max_bytes=1000)
        self.assertEqual(result.stdout, 'safe')
        self.assertNotIn(CANARY, repr(result))
        result = inventory.run_command([sys.executable, '-I', '-c', 'import sys;sys.stderr.write("x"*4096)'], max_bytes=128)
        self.assertTrue(result.truncated)
        self.assertEqual(result.error, 'output_limit')

    def test_subprocess_timeout_is_explicit(self):
        result = inventory.run_command([sys.executable, '-I', '-c', 'import time;time.sleep(3)'], timeout=0.05)
        self.assertEqual(result.error, 'timeout')

    def test_main_refuses_oversized_report_without_partial_output(self):
        with mock.patch.object(inventory, 'collect', return_value={'value': CANARY * 10000}), \
             mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            code = inventory.main()
        self.assertEqual(code, 1)
        self.assertEqual(len(out.getvalue().splitlines()), 1)
        self.assertNotIn(CANARY, out.getvalue())
        self.assertIn('collector_output_limit', out.getvalue())

    def test_main_one_json_line_even_if_collection_fails(self):
        stream = io.StringIO()
        with mock.patch.object(inventory, 'collect', side_effect=ValueError(CANARY)), contextlib.redirect_stdout(stream):
            inventory.main()
        lines = stream.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith('NAVER_DEPLOY_APP_INVENTORY='))
        self.assertNotIn(CANARY, lines[0])
        self.assertEqual(json.loads(lines[0].split('=', 1)[1])['status'], 'collector_failed')


if __name__ == '__main__':
    unittest.main()
