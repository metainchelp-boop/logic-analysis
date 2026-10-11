"""Offline failure/crash tests. All credentials, processes and services are synthetic."""
import ast
import base64
import copy
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import textwrap
import time
import types
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
spec = importlib.util.spec_from_file_location('config_under_test', TOOLS / 'naver_claude_config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
WORKFLOW = TOOLS.parents[1] / '.github/workflows/debug-rank.yml'
SYNTHETIC_KEY = b'SYNTHETIC-NOT-A-CREDENTIAL'


def request(operation='activate'):
    return dict(operation=operation, operation_id='a' * 32, expires_at=int(time.time()) + 600,
                baseline=config.BASELINE, source_commit=config.SOURCE_COMMIT, rollback_commit=config.ROLLBACK_COMMIT)


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE')
        result[key] = value
    return result


class Fixture:
    def __init__(self, temporary):
        self.ROOT, self.SECRET_ROOT = temporary / 'srv', temporary / 'etc'
        self.ROOT.mkdir(mode=0o700)
        self.SECRET_ROOT.mkdir(mode=0o700)
        (self.ROOT / 'receipts').mkdir(mode=0o700)
        (self.ROOT / 'releases').mkdir(mode=0o700)
        self.images = dict(engine='sha256:' + '1' * 64, relay='sha256:' + '2' * 64)
        self.rows = {name: dict(id=str(index) * 64, image=self.images[name], running=True, started='original',
                              restarts=0, project='naver-' + name, service='naver-' + name)
                     for index, name in enumerate(('engine', 'relay'), 3)}
        self.active = {name: True for name in ('engine', 'relay')}
        self.commands, self.recreates, self.bad_factory = [], 0, False
        self.UNITS = ('metainc-naver-engine.service', 'metainc-naver-relay.service')
        self.TUNNEL = 'metainc-naver-erp-tunnel.service'
        self.unit = temporary / 'unit'
        self.unit.write_bytes(b'PINNED UNIT')
        self.unit.chmod(0o644)
        self.env = self.SECRET_ROOT / 'runtime.env'
        self.write_new(self.env, b'# existing unrelated comments\nEXISTING_TOKEN=synthetic-only\nKEEP=unchanged\r\n')
        self.other = self.SECRET_ROOT / 'unrelated.pem'
        self.write_new(self.other, b'UNRELATED SYNTHETIC FILE')
        for commit in (config.SOURCE_COMMIT, config.ROLLBACK_COMMIT):
            (self.ROOT / 'releases' / ('naver-' + commit)).mkdir(mode=0o700)
            body = dict(ok=True, stage='prepared', source_commit=commit, images=self.images,
                        package={'source_commit': commit, 'retained': 'unchanged'},
                        files={str(self.env): config.digest(self.env.read_bytes()),
                               str(self.other): config.digest(self.other.read_bytes())})
            self.write_new(self.ROOT / 'receipts' / ('preview-' + commit + '.json'),
                           json.dumps(body, indent=2).encode())
        self.host = types.SimpleNamespace(baseline=lambda: config.BASELINE)

    @staticmethod
    def read_file(path, mode=None, maximum=3 * 1024 * 1024, minimum=1):
        path = Path(path)
        info = path.lstat()
        if (path.resolve() != path or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                mode is not None and stat.S_IMODE(info.st_mode) != mode or
                not minimum <= info.st_size <= maximum):
            raise ValueError('FILE_POLICY')
        return path.read_bytes()

    @staticmethod
    def trusted_dir(path, mode=0o755, new=False):
        if new:
            path.mkdir(mode=mode)
            path.chmod(mode)
        info = path.lstat()
        if path.resolve() != path or not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != mode:
            raise ValueError('DIRECTORY_POLICY')

    @staticmethod
    def write_new(path, body):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(body)
            output.flush()
            os.fsync(output.fileno())

    unique = staticmethod(unique)

    def manifest(self, release, commit, started=False):
        assert started is True
        path = self.ROOT / 'releases' / ('naver-' + commit)
        body = json.loads(self.read_file(self.ROOT / 'receipts' / ('preview-' + commit + '.json'), mode=0o600))
        for filename, digest in body['files'].items():
            if config.digest(self.read_file(Path(filename), mode=0o600)) != digest:
                raise ValueError('PREPARED_FILE_CHANGED')
        return path, body

    def unit_files(self, source, gid, release):
        if source != self.ROOT / 'releases' / ('naver-' + config.SOURCE_COMMIT):
            raise ValueError('BAD_SOURCE')
        return {self.unit: b'PINNED UNIT'}

    def _state(self, release, unit, field):
        name = 'engine' if unit == self.UNITS[0] else 'relay'
        if field == 'ActiveState':
            return 'active' if unit == self.TUNNEL or self.active[name] else 'inactive'
        return {'UnitFileState': 'enabled', 'SubState': 'dead', 'MainPID': '0'}[field]

    def _snapshot(self, release, source, images):
        if any(not row['running'] or row['image'] != images[name] for name, row in self.rows.items()):
            raise ValueError('PREVIEW_CONTAINER_STATE')
        return copy.deepcopy(self.rows)

    @staticmethod
    def compose(source, name):
        return ['docker', 'compose', '--project-name', 'naver-' + name, '--source', str(source)]

    def command(self, args, timeout=45):
        self.commands.append(args)
        if args[0] == 'env':
            return b''
        if args[:2] == ['docker', 'run'] or args[:2] == ['docker', 'exec']:
            return b'UNTRUSTED SYNTHETIC OUTPUT' if self.bad_factory else b'{"configured":true,"unlimited":true}\n'
        if args[0] == '/usr/bin/systemctl':
            action, unit = args[1:]
            name = 'engine' if unit == self.UNITS[0] else 'relay'
            assert unit in self.UNITS
            self.active[name] = action == 'start'
            self.rows[name]['running'] = action == 'start'
            if action == 'start':
                self.rows[name]['started'] = 'started-' + str(len(self.commands))
            return b''
        if args[:2] == ['docker', 'ps']:
            name = 'engine' if 'label=com.docker.compose.project=naver-engine' in args else 'relay'
            return (self.rows[name]['id'] + '\n').encode()
        if args[:2] == ['docker', 'inspect']:
            name = next(name for name, row in self.rows.items() if row['id'] == args[-1])
            row = self.rows[name]
            return json.dumps(dict(id=row['id'], image=row['image'], running=row['running'], restarting=False,
                                   pid=0, project=row['project'], service=row['service'])).encode()
        if args[:2] == ['docker', 'compose'] and '--force-recreate' in args:
            assert args[3] == 'naver-engine'
            self.recreates += 1
            self.rows['engine']['id'] = f'{100 + self.recreates:064x}'
            self.rows['engine']['running'] = False
            return b''
        raise AssertionError('UNEXPECTED_SYNTHETIC_COMMAND')

    @staticmethod
    def unix_request(socket, path):
        assert path in ('/_engine/health', '/api/naver-auto/me')
        return (200, {}, b'{}') if path == '/_engine/health' else (401, {}, b'{}')


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self.temporary.name).resolve())
        self.pwd = mock.patch.object(config.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_gid=33))
        self.pwd.start()
        self.key = mock.patch.object(config.Transaction, 'key', return_value=SYNTHETIC_KEY)
        self.key.start()
        self.tx = config.Transaction(request(), self.fixture.host, self.fixture, self.fixture, self.fixture)
        self.tx.existing_transactions()
        self.old = [path.read_bytes() for path in self.tx.paths]
        self.other = self.fixture.other.read_bytes()

    def tearDown(self):
        self.key.stop()
        self.pwd.stop()
        self.temporary.cleanup()

    def assert_restored(self):
        self.assertEqual([path.read_bytes() for path in self.tx.paths], self.old)
        self.assertEqual(self.fixture.other.read_bytes(), self.other)
        self.assertTrue(all(self.fixture.active.values()))
        self.assertEqual(self.fixture.rows['relay']['id'], '4' * 64)

    def recovery(self):
        other = config.Transaction(request('recover'), self.fixture.host, self.fixture, self.fixture, self.fixture)
        other.existing_transactions()
        return other

    def test_activation_exact_scope_unlimited_and_engine_only_recreate(self):
        result = self.tx.activate()
        self.assertEqual(result['state'], 'committed')
        self.assertEqual(result['monthly_limit'], 'unlimited')
        self.assertEqual(config.unrelated(self.fixture.env.read_bytes()), config.unrelated(self.old[0]))
        self.assertIn(b'NAVER_CLAUDE_MONTHLY_CAP_USD=unlimited\n', self.fixture.env.read_bytes())
        for index in (1, 2):
            old, new = json.loads(self.old[index]), json.loads(self.tx.paths[index].read_bytes())
            old['files'][str(self.fixture.env)] = config.digest(self.fixture.env.read_bytes())
            self.assertEqual(old, new)
        self.assertEqual(self.fixture.recreates, 1)
        self.assertEqual(self.fixture.rows['relay']['id'], '4' * 64)
        starts_stops = [command for command in self.fixture.commands if command[0] == '/usr/bin/systemctl']
        self.assertEqual(starts_stops, [['/usr/bin/systemctl', 'stop', self.fixture.UNITS[1]],
            ['/usr/bin/systemctl', 'stop', self.fixture.UNITS[0]],
            ['/usr/bin/systemctl', 'start', self.fixture.UNITS[0]],
            ['/usr/bin/systemctl', 'start', self.fixture.UNITS[1]]])
        trial = next(command for command in self.fixture.commands if command[:2] == ['docker', 'run'])
        self.assertIn('--network', trial)
        self.assertEqual(trial[trial.index('--network') + 1], 'none')
        self.assertEqual(trial[trial.index('--pull') + 1], 'never')
        self.assertFalse(set(trial) & {'--mount', '-v', '--publish', '-p'})
        self.assertIn(self.fixture.images['engine'], trial)
        self.assertEqual(trial[-5:-2], ['-I', '-S', '-B'])
        self.assertNotIn(SYNTHETIC_KEY.decode(), json.dumps(result))
        self.assertEqual(stat.S_IMODE(self.tx.folder.stat().st_mode), 0o700)
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in self.tx.folder.iterdir()))
        self.assertEqual(self.fixture.other.read_bytes(), self.other)

    def test_config_recover_before_code_rollback_restores_exact_original(self):
        self.tx.activate()
        outcome = self.recovery().recover()
        self.assertTrue(outcome['code_rollback_requires_config_recovery'])
        self.assertEqual(outcome['monthly_limit'], 'restored')
        self.assert_restored()
        self.assertEqual(self.fixture.recreates, 2)

    def test_failure_after_each_file_replace_restores_three_originals(self):
        for failing_index in range(3):
            with self.subTest(index=failing_index):
                # A fresh operation after each recovered one retains independent journals.
                self.tx.request['operation_id'] = f'{failing_index + 1:032x}'
                self.tx.folder = self.tx.root / self.tx.request['operation_id']
                real_replace = self.tx.replace
                failed = False
                def fail_once(path, body, expected):
                    nonlocal failed
                    real_replace(path, body, expected)
                    if path == self.tx.paths[failing_index] and not failed:
                        failed = True
                        raise RuntimeError('SYNTHETIC_FAILURE')
                with mock.patch.object(self.tx, 'replace', side_effect=fail_once):
                    with self.assertRaisesRegex(RuntimeError, '^CONFIG_FAILED_RECOVERED$'):
                        self.tx.activate()
                self.assert_restored()

    def test_start_failure_restores_and_does_not_require_new_image(self):
        real_start = self.tx.start
        def fail_enabled(images, previous, configured):
            if configured:
                raise RuntimeError('SYNTHETIC_START_FAILED')
            return real_start(images, previous, configured)
        with mock.patch.object(self.tx, 'start', side_effect=fail_enabled):
            with self.assertRaisesRegex(RuntimeError, '^CONFIG_FAILED_RECOVERED$'):
                self.tx.activate()
        self.assert_restored()

    def test_candidate_rejection_never_stops_services(self):
        self.fixture.bad_factory = True
        with self.assertRaisesRegex(ValueError, '^CONFIG_CANDIDATE_REJECTED$'):
            self.tx.activate()
        self.assert_restored()
        self.assertFalse(any(command[0] == '/usr/bin/systemctl' for command in self.fixture.commands))
        self.assertEqual(self.recovery().recover()['state'], 'recovered')

    def test_process_crash_during_each_partial_replace_recovers(self):
        for count in (0, 1, 2, 3):
            with self.subTest(count=count):
                self.tx.request['operation_id'] = f'{count + 8:032x}'
                self.tx.folder = self.tx.root / self.tx.request['operation_id']
                self.tx.prepare()
                self.tx.stop(self.tx.journal['images'])
                self.tx.save('stopped')
                for index in range(count):
                    self.tx.replace(self.tx.paths[index], self.tx.read(self.tx.folder / ('new-' + str(index))), self.old[index])
                self.tx.recover()
                self.assert_restored()

    def test_preparing_crash_missing_backups_recovers_without_restart(self):
        real_new = self.tx.new
        def fail_backup(path, body):
            if path.name == 'old-1':
                raise SystemExit('SYNTHETIC_PROCESS_CRASH')
            return real_new(path, body)
        with mock.patch.object(self.tx, 'new', side_effect=fail_backup):
            with self.assertRaises(SystemExit):
                self.tx.prepare()
        self.assertEqual(self.recovery().recover()['state'], 'recovered')
        self.assert_restored()
        self.assertEqual(self.fixture.recreates, 0)

    def test_missing_and_partial_initial_journal_are_recoverable(self):
        for index, initial in enumerate((None, b'', b'{"schema":')):
            with self.subTest(initial=index):
                tx = config.Transaction(dict(request('recover'), operation_id=f'{index + 20:032x}'),
                                        self.fixture.host, self.fixture, self.fixture, self.fixture)
                tx.folder.mkdir(mode=0o700)
                if initial is not None:
                    self.fixture.write_new(tx.folder / 'journal.json', initial)
                tx.existing_transactions()
                self.assertEqual(tx.recover()['state'], 'recovered')
                self.assertEqual(json.loads((tx.folder / 'journal.json').read_bytes())['state'], 'rejected')
        self.assert_restored()
        self.assertEqual(self.fixture.recreates, 0)

    def test_stale_private_temp_from_interrupted_replace_does_not_block_recover(self):
        self.tx.prepare()
        self.tx.stop(self.tx.journal['images'])
        self.tx.save('stopped')
        self.tx.replace(self.tx.paths[0], self.tx.read(self.tx.folder / 'new-0'), self.old[0])
        stale = self.tx.env.with_name('.claude-' + self.tx.request['operation_id'] + '-stale-' + self.tx.env.name)
        self.fixture.write_new(stale, b'INCOMPLETE SYNTHETIC BYTES')
        self.assertEqual(self.recovery().recover()['state'], 'recovered')
        self.assert_restored()
        self.assertEqual(stale.read_bytes(), b'INCOMPLETE SYNTHETIC BYTES')

    def test_committed_idempotency_requires_exact_live_three_files(self):
        self.tx.activate()
        self.assertEqual(self.tx.activate()['state'], 'committed')
        self.assertEqual(self.fixture.recreates, 1)
        receipt = self.tx.paths[1]
        receipt.write_bytes(receipt.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, '^CONFIG_COMMITTED_DRIFT$'):
            self.tx.activate()

    def test_recovery_refuses_unknown_env_drift_without_restart(self):
        self.tx.activate()
        commands = len(self.fixture.commands)
        self.fixture.env.write_bytes(self.fixture.env.read_bytes() + b'OTHER=unapproved\n')
        with self.assertRaisesRegex(ValueError, '^CONFIG_RECOVERY_DRIFT$'):
            self.recovery().recover()
        self.assertEqual(len(self.fixture.commands), commands)

    def test_private_backup_tampering_and_links_fail_closed(self):
        self.tx.prepare()
        backup = self.tx.folder / 'old-0'
        backup.write_bytes(b'TAMPERED SYNTHETIC')
        with self.assertRaisesRegex(ValueError, '^CONFIG_BACKUP_CHANGED$'):
            self.recovery().recover()
        backup.unlink()
        backup.symlink_to(self.fixture.env)
        with self.assertRaisesRegex(ValueError, '^FILE_POLICY$'):
            self.tx.load_journal()

    def test_other_unfinished_transaction_blocks_second_operation(self):
        self.tx.prepare()
        second = config.Transaction(dict(request(), operation_id='b' * 32), self.fixture.host,
                                    self.fixture, self.fixture, self.fixture)
        with self.assertRaisesRegex(ValueError, '^CONFIG_OTHER_TRANSACTION$'):
            second.existing_transactions()


class PolicyTests(unittest.TestCase):
    def test_closed_request_pins_and_expiry(self):
        value = request()
        self.assertIs(config.validate_request(value), value)
        cases = [dict(value, extra=True), dict(value, operation='anything'), dict(value, baseline='0' * 64),
                 dict(value, source_commit=config.ROLLBACK_COMMIT), dict(value, rollback_commit=config.SOURCE_COMMIT),
                 dict(value, operation_id='A' * 32), dict(value, expires_at=True),
                 dict(value, expires_at=int(time.time()) - 1), dict(value, expires_at=int(time.time()) + 901)]
        for case in cases:
            with self.assertRaisesRegex(ValueError, '^CONFIG_REQUEST$'):
                config.validate_request(case)

    def test_env_keeps_unrelated_bytes_and_replaces_only_named_settings(self):
        body = b'# x\r\nOTHER=has spaces\nNAVER_CLAUDE_ENABLED=false\r\nCLAUDE_API_KEY=unrelated-synthetic\n'
        result = config.candidate_env(body, SYNTHETIC_KEY)
        self.assertEqual(config.unrelated(body), config.unrelated(result))
        self.assertEqual(result.count(b'NAVER_CLAUDE_ENABLED='), 1)
        self.assertIn(b'CLAUDE_API_KEY=unrelated-synthetic\n', result)
        self.assertEqual(config.candidate_env(result, SYNTHETIC_KEY), result)

    def test_env_malformed_duplicate_key_and_boundary_rejections(self):
        cases = [(b'', SYNTHETIC_KEY), (b'NO_FINAL_LF=yes', SYNTHETIC_KEY), (b'A=\x00\n', SYNTHETIC_KEY),
                 (b'NAVER_CLAUDE_ENABLED=false\nNAVER_CLAUDE_ENABLED=false\n', SYNTHETIC_KEY),
                 (b' NAVER_CLAUDE_ENABLED = false\n', SYNTHETIC_KEY), (b'A=y\n', b'bad\nkey'),
                 (b'A=y\n', b''), (b'A=y\n', b'x' * 4097), (b'A=' + b'x' * 32765 + b'\n', SYNTHETIC_KEY)]
        for body, key in cases:
            with self.assertRaises(ValueError):
                config.candidate_env(body, key)

    def test_proc_source_prefers_anthropic_fallback_and_rejects_duplicates_drift(self):
        tx = object.__new__(config.Transaction)
        identity = dict(pid=123, id='f' * 64)
        for body, expected in ((b'OTHER=synthetic\0CLAUDE_API_KEY=fallback\0ANTHROPIC_API_KEY=preferred\0', b'preferred'),
                               (b'CLAUDE_API_KEY=fallback\0ANTHROPIC_API_KEY=\0', b'fallback')):
            with mock.patch.object(tx, 'logic_identity', return_value=identity), mock.patch.object(config.os, 'open', side_effect=[1, 2, 3]), \
                    mock.patch.object(config.os, 'read', return_value=body), mock.patch.object(config.os, 'close') as close:
                self.assertEqual(tx.key(), expected)
                self.assertEqual(close.call_count, 3)
        for body in (b'ANTHROPIC_API_KEY=x\0ANTHROPIC_API_KEY=y\0', b'CLAUDE_API_KEY=bad key\0', b'NOT_A_KEY=x\0', b'x' * 131073):
            with mock.patch.object(tx, 'logic_identity', return_value=identity), mock.patch.object(config.os, 'open', side_effect=[1, 2, 3]), \
                    mock.patch.object(config.os, 'read', return_value=body), mock.patch.object(config.os, 'close'):
                with self.assertRaisesRegex(ValueError, '^CONFIG_KEY_SOURCE_POLICY$'):
                    tx.key()
        with mock.patch.object(tx, 'logic_identity', side_effect=[identity, dict(identity, pid=124)]), \
                mock.patch.object(config.os, 'open', side_effect=[1, 2, 3]), mock.patch.object(config.os, 'read', return_value=b'CLAUDE_API_KEY=x\0'), \
                mock.patch.object(config.os, 'close'):
            with self.assertRaisesRegex(ValueError, '^CONFIG_KEY_SOURCE_CHANGED$'):
                tx.key()


def workflow_block(start, end):
    text = WORKFLOW.read_text()
    return textwrap.dedent(text.split('# ' + start + '\n', 1)[1].split('# ' + end, 1)[0])


class WorkflowTests(unittest.TestCase):
    def test_all_nine_old_jobs_guard_config_mode(self):
        text = WORKFLOW.read_text()
        jobs = re.findall(r'^  ([a-z0-9-]+):\n    if: (.+)$', text, re.M)
        self.assertEqual(len(jobs), 11)
        for name, condition in jobs:
            if name not in ('claude-config', 'claude-models'):
                self.assertTrue(condition.startswith("${{ (!inputs.claude_config || inputs.claude_config == 'off') && ("))
        job = text.split('  claude-config:\n', 1)[1]
        self.assertIn('group: deploy-logic-analysis\n      cancel-in-progress: false', job)
        self.assertIn("github.ref == 'refs/heads/codex/naver-claude-config-20261011'", job)
        self.assertIn('appleboy/ssh-action@029f5b4aeeeb58fdfe1410a5d17f967dacf36262', job)
        self.assertIn('/usr/bin/python3 -I -S -B -', job)

    def test_public_bundle_pack_and_strict_remote_decode(self):
        with tempfile.TemporaryDirectory() as temporary:
            envfile = Path(temporary) / 'github-env'
            values = {key: 'off' for key in ('ad_prepare', 'collector', 'rank_link', 'capacity', 'structure',
                                            'expired', 'queue', 'urlshape', 'use_branch_code')}
            values.update(claude_config='activate', ad_expected_baseline=json.dumps(request()))
            code = workflow_block('CLAUDE_CONFIG_PACKAGE_BEGIN', 'CLAUDE_CONFIG_PACKAGE_END')
            read_text = Path.read_text
            with mock.patch.dict(os.environ, INPUTS_JSON=json.dumps(values), GITHUB_ENV=str(envfile)), \
                    mock.patch.object(Path, 'read_text', autospec=True, side_effect=lambda path, *a, **k: read_text(TOOLS.parents[1] / path, *a, **k)):
                exec(compile(code, '<workflow-package>', 'exec'), {})
            encoded = envfile.read_text().strip().split('=', 1)[1]
        remote = workflow_block('CLAUDE_CONFIG_REMOTE_BEGIN', 'CLAUDE_CONFIG_REMOTE_END')
        tree = ast.parse(remote)
        decode_nodes = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))]
        namespace = {}
        exec(compile(ast.Module(body=decode_nodes, type_ignores=[]), '<workflow-decode>', 'exec'), namespace)
        bundle = namespace['decode'](encoded)
        self.assertEqual(bundle['request']['source_commit'], config.SOURCE_COMMIT)
        self.assertEqual(len(bundle['modules']), 5)
        self.assertNotIn(SYNTHETIC_KEY.decode(), json.dumps(bundle))
        packed = base64.b64decode(encoded)
        bad = ('!', encoded + 'x' * 65536,
               base64.b64encode(packed + b'trailing').decode(),
               base64.b64encode(gzip.compress(b'x' * 262145)).decode(),
               base64.b64encode(gzip.compress(b'{"request":{},"request":{},"modules":{}}')).decode(),
               base64.b64encode(gzip.compress(b'{"request":{},"modules":{}}')).decode())
        for value in bad:
            with self.assertRaises((ValueError, TypeError)):
                namespace['decode'](value)

    def test_remote_failure_never_outputs_exception_or_source_values(self):
        remote = workflow_block('CLAUDE_CONFIG_REMOTE_BEGIN', 'CLAUDE_CONFIG_REMOTE_END')
        module_names = ('naver_claude_config', 'naver_preview_release', 'naver_preview_upgrade', 'naver_preview_lifecycle',
                        'naver_erp_tunnel_service_install')
        sources = {name: 'pass' for name in module_names}
        sources['naver_claude_config'] = "print('SYNTHETIC-STRAY-SECRET');raise RuntimeError('SYNTHETIC-EXCEPTION-SECRET')"
        encoded = base64.b64encode(gzip.compress(json.dumps({'request': request(), 'modules': sources}).encode())).decode()
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, CLAUDE_CONFIG_B64=encoded), mock.patch('sys.stdout', output), mock.patch('sys.stderr', errors):
            with self.assertRaises(SystemExit) as failure:
                exec(compile(remote, '<workflow-remote>', 'exec'), {})
        self.assertEqual(failure.exception.code, 1)
        self.assertEqual(output.getvalue(), '{"code":"CONFIG_FAILED","ok":false,"stage":"input"}\n')
        self.assertEqual(errors.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
