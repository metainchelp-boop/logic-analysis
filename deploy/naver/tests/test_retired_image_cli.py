"""Real Docker Go-template regression against a fresh private mock Unix daemon.

No existing daemon, Docker context, credential directory, or service is used.
CI and the pre-shipment workflow require the CLI; local runs may skip without it.
"""
import contextlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socketserver
import stat
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


SPEC = importlib.util.spec_from_file_location(
    'retired_image_cli_subject', Path(__file__).parents[1] / 'retired_image_inspect.py')
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)
CANARY = 'PRIVATE_SYNTHETIC_CLI_CANARY'
OMITTED = object()
OLD_PARENT = '{{json .Parent}}'
INDEX_PARENT = '{{json (index . "Parent")}}'


@contextlib.contextmanager
def private_daemon(docker, parent):
    """Serve synthetic read-only responses and refuse any other request."""
    image_id = R.CANDIDATES[0][1]
    image = {'Id': image_id, 'RepoTags': ['synthetic:' + CANARY], 'RepoDigests': [],
             'Size': 1234, 'RootFS': {'Type': 'layers', 'Layers': ['sha256:' + 'a' * 64]}}
    if parent is not OMITTED:
        image['Parent'] = parent
    info = {'ID': CANARY, 'Driver': 'overlay2', 'DriverStatus': [['Root', CANARY]],
            'DockerRootDir': '/synthetic/' + CANARY, 'ServerVersion': '29.8.1'}
    summary = {'Id': image_id, 'ParentId': '', 'RepoTags': ['synthetic:' + CANARY],
               'RepoDigests': [], 'Created': 0, 'Size': 1234, 'SharedSize': -1,
               'VirtualSize': 1234, 'Labels': {}, 'Containers': 0}
    requests = []
    refused = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            parsed = urlsplit(self.path)
            path = re.sub(r'^/v[0-9]+\.[0-9]+', '', parsed.path)
            allowed = {'/_ping': b'OK', '/info': info, '/images/json': [summary],
                       '/containers/json': [], '/images/' + image_id + '/json': image}
            query = parse_qs(parsed.query)
            valid = path in allowed and (self.command != 'HEAD' or path == '/_ping')
            if path == '/containers/json' and 'filters' in query:
                filters = json.loads(query['filters'][0])
                valid = valid and filters in ({'ancestor': [image_id]},
                                               {'ancestor': {image_id: True}})
            if not valid:
                refused.append('UNEXPECTED_READ')
                self.send_error(404, 'Synthetic route refused')
                return
            requests.append(path)
            value = allowed[path]
            body = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('API-Version', '1.54')
            self.send_header('OSType', 'linux')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

    # Keep the Unix socket path short enough on both macOS and Linux.
    with tempfile.TemporaryDirectory(prefix='naver-cli-test-', dir='/tmp') as tmp:
        os.chmod(tmp, 0o700)
        folder = Path(tmp)
        socket_path = folder / 'mock.sock'
        directory_identity = folder.lstat()
        with socketserver.UnixStreamServer(str(socket_path), Handler) as server:
            os.chmod(socket_path, 0o600)
            socket_identity = socket_path.lstat()
            endpoint = (str(docker), '--host=unix://' + str(socket_path))
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02},
                                      daemon=True)
            thread.start()

            def guard(command):
                directory = folder.lstat()
                current = socket_path.lstat()
                if (not stat.S_ISDIR(directory.st_mode)
                        or stat.S_IMODE(directory.st_mode) != 0o700
                        or directory.st_uid != os.getuid()
                        or (directory.st_dev, directory.st_ino) !=
                        (directory_identity.st_dev, directory_identity.st_ino)
                        or not stat.S_ISSOCK(current.st_mode)
                        or stat.S_IMODE(current.st_mode) != 0o600
                        or current.st_uid != os.getuid()
                        or (current.st_dev, current.st_ino) !=
                        (socket_identity.st_dev, socket_identity.st_ino)
                        or command[:2] != endpoint or not R.command_allowed(command)):
                    raise AssertionError('Private synthetic endpoint guard refused command')

            try:
                with patch.object(R, 'DOCKER', endpoint):
                    yield guard, requests, refused
            finally:
                server.shutdown()
                thread.join(timeout=5)
                if thread.is_alive():
                    raise AssertionError('Private synthetic daemon did not stop')


class ActualDockerCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        executable = shutil.which('docker')
        if executable is None:
            if os.environ.get('NAVER_REQUIRE_DOCKER_CLI') == '1':
                raise RuntimeError('Docker CLI required for regression validation')
            raise unittest.SkipTest('Docker CLI unavailable; mandatory in CI and pre-shipment')
        cls.docker = Path(executable).resolve(strict=True)

    def exercise(self, parent, old_template=False):
        template = R.IMAGE_FORMAT.replace(INDEX_PARENT, OLD_PARENT) if old_template else R.IMAGE_FORMAT
        with patch.object(R, 'IMAGE_FORMAT', template), private_daemon(self.docker, parent) as fixture:
            guard, requests, refused = fixture
            command = R.DOCKER + ('image', 'inspect', '--format', R.IMAGE_FORMAT, R.CANDIDATES[0][1])
            guard(command)
            # These inherited settings must never reach either CLI subprocess path.
            with patch.dict(os.environ, {'DOCKER_HOST': 'unix:///DO_NOT_CONNECT',
                                         'DOCKER_CONTEXT': CANARY,
                                         'DOCKER_CONFIG': '/DO_NOT_READ',
                                         'DOCKER_API_VERSION': '0.0',
                                         'HOME': '/DO_NOT_READ'}):
                self.assertFalse({'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_API_VERSION'} & set(R.ENV))
                self.assertEqual(R.ENV['HOME'], '/nonexistent')
                self.assertEqual(R.ENV['DOCKER_CONFIG'], '/nonexistent/metainc-retired-image-inspect')
                probe = subprocess.run(command, env=R.ENV, cwd='/', stdin=subprocess.DEVNULL,
                                       capture_output=True, timeout=10)
                product_runner = R.Runner()
                commands = []

                def guarded_runner(current):
                    guard(current)
                    commands.append(current[2:4])
                    return product_runner(current)

                report = R.collect_report(guarded_runner)
            self.assertFalse(refused)
            self.assertTrue(requests)
            self.assertFalse(report['delete_authorized'])
            self.assertIsNone(report['reclaimable_bytes'])
            self.assertNotIn(CANARY, R.canonical(report))
            self.assertIs(R.validate_report(report), report)
            return probe, report, commands

    def assert_complete_parent(self, parent):
        probe, report, commands = self.exercise(parent)
        self.assertEqual(probe.returncode, 0, 'Synthetic CLI projection failed; stderr suppressed')
        self.assertFalse(probe.stderr, 'Synthetic CLI emitted unexpected stderr; content suppressed')
        projected = json.loads(probe.stdout)
        self.assertEqual(projected['parent'], None if parent is OMITTED else parent)
        self.assertEqual(report['status'], 'COMPLETE_STABLE')
        self.assertEqual(report['reason'], 'OK')
        self.assertIsNone(report['diagnostic'])
        self.assertEqual(report['docker']['image_count'], 1)
        self.assertEqual(commands.count(('info', '--format')), 2)
        self.assertEqual(commands.count(('image', 'inspect')), 2)
        candidate = report['candidates'][0]
        self.assertIs(candidate['image']['parent_present'], None if parent is OMITTED else bool(parent))
        self.assertFalse(report['docker']['parent_relation_complete'])
        self.assertEqual(candidate['status'], 'NO_REFERENCES_OBSERVED')

    def test_omitted_parent_passes_actual_cli_and_collector(self):
        self.assert_complete_parent(OMITTED)

    def test_empty_parent_passes_actual_cli_and_collector(self):
        self.assert_complete_parent('')

    def test_nonempty_parent_passes_actual_cli_and_collector(self):
        self.assert_complete_parent('sha256:' + 'b' * 64)

    def test_legacy_dot_parent_negative_control_fails_actual_cli_and_collector(self):
        probe, report, commands = self.exercise(OMITTED, old_template=True)
        self.assertEqual(probe.returncode, 1)
        # This fixed text is synthetic; no stderr is printed or retained as evidence.
        self.assertIn(b'map has no entry for key "Parent"', probe.stderr)
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertEqual(report['reason'], 'COMMAND_FAILED')
        self.assertEqual(report['diagnostic'], dict(snapshot=1, command_index=4,
                         stage='IMAGE_INSPECT', code='PARENT_KEY_MISSING', exit_code=1))
        self.assertIsNone(report['docker'])
        self.assertTrue(all(item['status'] == 'UNKNOWN' for item in report['candidates']))
        self.assertEqual(commands[-1], ('image', 'inspect'))
        self.assertEqual(commands.count(('info', '--format')), 1)


class DockerCliAvailabilityPolicyTests(unittest.TestCase):
    def test_required_workflow_fails_when_cli_is_missing(self):
        with patch('shutil.which', return_value=None), patch.dict(
                os.environ, {'NAVER_REQUIRE_DOCKER_CLI': '1'}):
            with self.assertRaisesRegex(RuntimeError, 'Docker CLI required'):
                ActualDockerCliTests.setUpClass()

    def test_optional_local_run_skips_when_cli_is_missing(self):
        with patch('shutil.which', return_value=None), patch.dict(
                os.environ, {'NAVER_REQUIRE_DOCKER_CLI': '0'}):
            with self.assertRaises(unittest.SkipTest):
                ActualDockerCliTests.setUpClass()


if __name__ == '__main__':
    unittest.main()
