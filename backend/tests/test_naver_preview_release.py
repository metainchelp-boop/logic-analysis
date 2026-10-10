import base64
from contextlib import redirect_stderr, redirect_stdout
import gzip
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('release', Path(__file__).parents[1] / 'tools/naver_preview_release.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def archive(name='naver_engine/web.py', kind=tarfile.REGTYPE):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as stream:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.size = 4 if kind == tarfile.REGTYPE else 0
        stream.addfile(member, io.BytesIO(b'test') if member.size else None)
    return out.getvalue()


def prepared_receipt(package):
    return {'ok': True, 'stage': 'prepared', 'source_commit': package['source_commit'],
            'package': {key: value for key, value in package.items() if key != 'operation'},
            'images': {'engine': 'sha256:'+'e'*64, 'relay': 'sha256:'+'e'*64}, 'files': {}}


def image_inspect_output(args, package):
    if '{{json .Id}}' in args:
        return json.dumps('sha256:'+'e'*64).encode()
    return (package['source_commit']+'\n').encode()


class BuildDiagnosticTest(unittest.TestCase):
    def test_pinned_compose_probes_report_fixed_categories_without_original_output(self):
        source = M.ROOT/'releases'/('naver-'+'b'*40)
        checks = [M.compose(source, name)+['config', '--quiet'] for name in ('engine','relay')]
        check = M.compose(source, 'engine');check[3] = 'naver-check-'+'b'*40+'-'+'c'*32
        check += ['-f', str(M.ROOT/'incoming'/'123456'/'check-config.override.yml')]
        checks.append(check+['run','--rm','--no-deps','--pull','never','naver-engine','python','-m','naver_runtime','check-config'])
        for args in checks:
            for marker, code in ((b'permission denied', 'DENIED'),
                    (b'all predefined address pools have been fully subnetted', 'NETWORK_POOL'),
                    (b'no space left on device', 'DISK'), (b'no such file or directory', 'MISSING_FILE'),
                    (b'yaml: line 1', 'YAML'), (b'{"error": "startup-refused", "kind": "ConfigError"}', 'CONFIG_REFUSED'),
                    (b'unrecognized', 'UNKNOWN')):
                with self.subTest(code=code, args=args), patch.object(M.subprocess, 'run', return_value=
                        subprocess.CompletedProcess(args, 1, b'PRIVATE_TOKEN', marker+b' https://private.invalid/?signed=SECRET')):
                    output, errors = io.StringIO(), io.StringIO()
                    with redirect_stdout(output), redirect_stderr(errors), self.assertRaises(RuntimeError) as raised:
                        M.command(args)
                    self.assertEqual(str(raised.exception), 'COMPOSE_PROBE_'+code)
                    self.assertEqual(output.getvalue()+errors.getvalue(), '')
            for index in (3, 5, len(args)-1):
                changed = args.copy();changed[index] = 'unreviewed'
                result = subprocess.CompletedProcess(changed, 1, b'', b'permission denied')
                self.assertEqual(M.compose_failure_code(changed, result), 'COMMAND_FAILED')

    def build_args(self, name='relay'):
        commit = 'b'*40
        source = M.ROOT/'releases'/('naver-'+commit)
        return ['docker', 'build', '--label', 'metainc.naver.preview.source='+commit,
                '-t', 'metainc/naver-'+name+':'+commit, '-f', str(source/('Dockerfile.naver-'+name)), str(source)]

    def test_build_failure_reports_only_fixed_category_without_sensitive_output(self):
        cases = (
            (b'permission denied: no space left on device', 'DENIED'),
            (b'pull access denied: repository requires authorization', 'DENIED'),
            (b'denied: requested access to the resource is denied', 'DENIED'),
            (b'failed to authorize: unexpected status: 403 Forbidden', 'DENIED'),
            (b'x509: certificate signed by unknown authority', 'TLS'),
            (b'ERROR: SSL: CERTIFICATE_VERIFY_FAILED', 'TLS'),
            (b'toomanyrequests: You have reached your pull rate limit', 'RATE'),
            (b'429 Too Many Requests', 'RATE'),
            (b'failed to authorize: failed to fetch anonymous token: 429 Too Many Requests', 'RATE'),
            (b'dial tcp: lookup registry: no such host', 'NETWORK'),
            (b'connection reset by peer', 'NETWORK'),
            (b'no space left on device', 'DISK'),
            (b'disk quota exceeded', 'DISK'),
            (b'process did not complete successfully: exit code: 1', 'STEP'),
            (b'The command returned a non-zero code: 1', 'STEP'),
            (b'unrecognized diagnostic', 'UNKNOWN'),
        )
        sensitive = b' PRIVATE_TOKEN=synthetic https://private.invalid/?signed=PRIVATE_SIGNED_URL -----BEGIN PRIVATE KEY-----'
        for marker, category in cases:
            for channel in ('stdout', 'stderr'):
                with self.subTest(category=category, channel=channel):
                    args = self.build_args()
                    streams = {'stdout': sensitive, 'stderr': sensitive}
                    streams[channel] += b'\n'+marker
                    result = subprocess.CompletedProcess(args, 1, **streams)
                    output, errors = io.StringIO(), io.StringIO()
                    with patch.object(M.subprocess, 'run', return_value=result), redirect_stdout(output), redirect_stderr(errors):
                        with self.assertRaises(RuntimeError) as raised:
                            M.command(args, timeout=600)
                    self.assertEqual(str(raised.exception), 'DOCKER_BUILD_'+category)
                    self.assertEqual(raised.exception.args, ('DOCKER_BUILD_'+category,))
                    self.assertEqual(output.getvalue()+errors.getvalue(), '')

    def test_other_commands_and_nonexact_builds_keep_generic_failure(self):
        original = self.build_args()
        cases = [['docker', 'compose', 'config', '--quiet'], ['openssl', 'cms', '-decrypt'],
                 original+['--no-cache'], ['docker', 'build', '.']]
        for index in (0, 2, 3, 4, 5, 6, 7, 8):
            changed = original.copy();changed[index] = 'unreviewed'
            cases.append(changed)
        for args in cases:
            with self.subTest(args=args), patch.object(M.subprocess, 'run',
                    return_value=subprocess.CompletedProcess(args, 1, b'PRIVATE_STDOUT', b'permission denied PRIVATE_STDERR')):
                with self.assertRaisesRegex(RuntimeError, '^COMMAND_FAILED$'):
                    M.command(args)

    def test_success_timeout_and_process_environment_are_unchanged(self):
        for name in ('engine', 'relay'):
            args = self.build_args(name)
            with patch.object(M.subprocess, 'run', return_value=subprocess.CompletedProcess(args, 0, b'original output', b'permission denied')) as run:
                self.assertEqual(M.command(args, timeout=600), b'original output')
                run.assert_called_once_with(args, input=None, capture_output=True, timeout=600,
                    env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
            with patch.object(M.subprocess, 'run', side_effect=subprocess.TimeoutExpired(args, 600)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    M.command(args, timeout=600)

    def test_bounded_diagnostic_tail_and_empty_output_remain_unknown(self):
        args = self.build_args()
        for output in (None, b'', b'permission denied'+b'x'*65536):
            with self.subTest(size=None if output is None else len(output)), patch.object(M.subprocess, 'run',
                    return_value=subprocess.CompletedProcess(args, 1, output, output)):
                with self.assertRaisesRegex(RuntimeError, '^DOCKER_BUILD_UNKNOWN$'):
                    M.command(args)


class ReleaseTest(unittest.TestCase):
    def test_transferred_ciphertext_owner_is_normalized_only_after_hash_validation(self):
        import types
        metadata = types.SimpleNamespace(st_mode=0o100600, st_uid=1000, st_gid=1000, st_nlink=1, st_size=6)
        path = Mock();path.lstat.return_value=metadata;path.read_bytes.return_value=b'cipher'
        with patch.object(M.os, 'chown') as change:
            with self.assertRaisesRegex(ValueError, 'CIPHERTEXT_HASH'):
                M.received_ciphertext(path, '0'*64)
            change.assert_not_called()
            self.assertEqual(M.received_ciphertext(path, M.sha(b'cipher')), b'cipher')
            change.assert_called_once_with(path, 0, 0)

    def simulate_start_failure(self, *, failed_up=None, up_timeout=False, failed_stop=None):
        """Controller test: only Docker, identity and time are simulated; no host or WSGI call."""
        package = {'baseline': 'a'*64, 'source_commit': 'b'*40, 'ciphertext_sha256': 'c'*64,
                   'source_tar_gz_sha256': 'd'*64, 'run_id': '123456', 'operation': 'start'}
        calls, running = [], set()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'receipts').mkdir()
            (root/'receipts'/('preview-'+package['source_commit']+'.json')).write_text(json.dumps(
                prepared_receipt(package)))

            def execute(args, **kwargs):
                calls.append(args)
                if args[:3] == ['docker', 'image', 'inspect']:
                    return subprocess.CompletedProcess(args, 0, image_inspect_output(args, package), b'')
                self.assertEqual(args[:3], ['docker', 'compose', '--project-name'])
                name = args[3]
                self.assertIn(name, {'naver-engine', 'naver-relay'})
                self.assertNotIn('down', args)
                if 'up' in args:
                    # Docker may already create/start the service before reporting failure.
                    running.add(name)
                    if name == failed_up:
                        if up_timeout:
                            raise subprocess.TimeoutExpired(args, kwargs['timeout'])
                        return subprocess.CompletedProcess(args, 1, b'', b'synthetic failure')
                if 'stop' in args:
                    if name == failed_stop:
                        return subprocess.CompletedProcess(args, 1, b'', b'synthetic stop failure')
                    running.discard(name)
                return subprocess.CompletedProcess(args, 0, b'', b'')

            host = Mock()
            host.baseline.return_value = package['baseline']
            with patch.object(M, 'ROOT', root), patch.object(M.os, 'geteuid', return_value=0), \
                 patch.object(M, 'prepared_paths', return_value=(root/'releases'/('naver-'+package['source_commit']), root/'receipts'/('preview-'+package['source_commit']+'.json'))), \
                 patch.object(M.subprocess, 'run', side_effect=execute), patch.object(M.time, 'sleep'), \
                 patch.object(M.time, 'monotonic', side_effect=[0, 46]), \
                 patch.object(M.socket.socket, 'connect', side_effect=AssertionError('unexpected socket')):
                with self.assertRaises(Exception) as raised:
                    M.start(package, host)
            self.assertFalse((root/'receipts'/('preview-start-'+package['source_commit']+'.json')).exists())
        return raised.exception, calls, running

    def test_partial_up_failure_or_timeout_also_stops_the_attempted_service(self):
        for name in ('naver-engine', 'naver-relay'):
            for timeout in (False, True):
                with self.subTest(service=name, timeout=timeout):
                    error, calls, running = self.simulate_start_failure(failed_up=name, up_timeout=timeout)
                    if timeout:
                        self.assertIsInstance(error, subprocess.TimeoutExpired)
                    else:
                        self.assertEqual(str(error), 'COMMAND_FAILED')
                    expected = ['naver-engine'] if name == 'naver-engine' else ['naver-relay', 'naver-engine']
                    self.assertEqual([args[3] for args in calls if 'stop' in args], expected)
                    self.assertFalse(running)

    def test_one_stop_failure_does_not_leave_the_other_new_service_running(self):
        error, calls, running = self.simulate_start_failure(failed_stop='naver-relay')
        self.assertEqual(str(error), 'NEW_SERVICE_STOP_FAILED')
        self.assertEqual([args[3] for args in calls if 'stop' in args], ['naver-relay', 'naver-engine'])
        self.assertEqual(running, {'naver-relay'})

    def test_plain_regular_source_extracts_only_into_new_release(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'new'
            M.extract_source(archive(), path)
            self.assertEqual((path / 'naver_engine/web.py').read_bytes(), b'test')
            with self.assertRaises(FileExistsError):
                M.extract_source(archive(), path)

    def test_traversal_links_unknown_files_and_duplicates_are_rejected(self):
        for name, kind in (('../outside', tarfile.REGTYPE), ('/etc/passwd', tarfile.REGTYPE),
                           ('naver_engine/link', tarfile.SYMTYPE), ('README.md', tarfile.REGTYPE),
                           ('naver_engine/../../bad', tarfile.REGTYPE)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'new'
                with self.assertRaises(ValueError):
                    M.extract_source(archive(name, kind), path)
                self.assertFalse(path.exists())

    def test_manifest_rejects_source_mismatch_before_writing(self):
        with self.assertRaises(ValueError):
            M.validate_payload({'schema': 1}, 'a' * 40, 'b' * 64)

    def test_ciphertext_and_source_identifiers_are_fixed_shape(self):
        good = {'baseline': 'a'*64, 'source_commit':'b'*40, 'ciphertext_sha256':'c'*64,
                'source_tar_gz_sha256':'d'*64, 'run_id':'123456', 'operation':'prepare'}
        self.assertEqual(M.validate_package(good), good)
        self.assertEqual(M.validate_package(dict(good, operation='upgrade-prepare'))['operation'], 'upgrade-prepare')
        for key in ('baseline','source_commit','ciphertext_sha256','source_tar_gz_sha256','run_id','operation'):
            value = dict(good, **{key:'../wrong'})
            with self.assertRaises(ValueError):
                M.validate_package(value)

    def test_failed_private_probe_stops_only_the_new_services(self):
        package={'baseline':'a'*64,'source_commit':'b'*40,'ciphertext_sha256':'c'*64,
                 'source_tar_gz_sha256':'d'*64,'run_id':'123456','operation':'start'}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'receipts').mkdir()
            (root/'receipts'/('preview-'+package['source_commit']+'.json')).write_text(
                json.dumps(prepared_receipt(package)))
            calls=[]
            def process(args,**kwargs):
                calls.append(args)
                return image_inspect_output(args, package) if args[:3]==['docker','image','inspect'] else b''
            host=Mock();host.baseline.return_value=package['baseline']
            with patch.object(M,'ROOT',root),patch.object(M.os,'geteuid',return_value=0), \
                 patch.object(M, 'prepared_paths', return_value=(root/'releases'/('naver-'+package['source_commit']), root/'receipts'/('preview-'+package['source_commit']+'.json'))), \
                 patch.object(M.subprocess,'run') as run,patch.object(M.time,'sleep'), \
                 patch.object(M.time,'monotonic',side_effect=[0,46]), \
                 patch.object(M.socket.socket,'connect',side_effect=OSError('synthetic unavailable')):
                def execute(args,**kwargs):
                    return subprocess.CompletedProcess(args,0,process(args),b'')
                import subprocess
                run.side_effect=execute
                with self.assertRaisesRegex(ValueError,'ENGINE_NOT_READY'):
                    M.start(package,host)
            stops=[args for args in calls if 'stop' in args]
            self.assertEqual(len(stops),2)
            self.assertEqual({args[3] for args in stops},{'naver-engine','naver-relay'})
            self.assertTrue(all('ad-api' not in args and 'down' not in args for args in calls))

    def test_private_file_rejects_links_and_wrong_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'receipt'
            target.write_text('{}')
            target.chmod(0o644)
            with self.assertRaises(ValueError):
                M.trusted_private_file(target)
            link = Path(folder)/'link'
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'SYMLINKED_PRIVATE_FILE'):
                M.trusted_private_file(link)
