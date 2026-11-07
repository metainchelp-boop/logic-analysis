"""Private synthetic files and real short-lived pipes; never SSH or real keys."""
import base64
import contextlib
import copy
import datetime
import hashlib
import importlib.util
import json
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


subject = load('naver_archive_refetch_client')
transport = load('naver_archive_transport')
legacy = load('naver_archive_receiver_operator')
control = load('naver_archive_receiver_control')
PAYLOAD = b'SYNTHETIC_CIPHERTEXT_ONLY\0' * 20000
KEY_CANARY = b'SYNTHETIC_PRIVATE_KEY_NEVER_READ'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


class ClientTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='.refetch-client-', dir=Path.home())
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.root.chmod(0o700)
        self.partial = self.root / subject.PRESERVED_NAME
        self.write(self.partial, PAYLOAD[:901])
        self.original = self.partial.read_bytes()
        self.original_stat = transport.identity(self.partial.stat())
        self.args = types.SimpleNamespace(
            plan=str(self.root / 'plan.json'), plan_sha256='1' * 64,
            sent_receipt=str(self.root / 'sent.json'), receipt_sha256='2' * 64,
            installed=str(self.root / 'installed.json'), install_sha256=None,
            fetch_public_key=str(self.root / 'fetch.pub'),
            transport_key=str(self.root / 'fetch-key'),
            preserved_partial=str(self.partial), preserved_sha256=subject.digest(self.original),
            output=str(self.root / subject.OUTPUT_NAME), output_receipt=str(self.root / 'fetched.json'))
        key = 'ssh-ed25519 ' + base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + b'K' * 32).decode()
        self.write(Path(self.args.fetch_public_key), key.encode(), 0o644)
        self.write(Path(self.args.transport_key), KEY_CANARY)
        self.sent = dict(status='sent_unverified', session=transport.SESSION,
                         plan_sha256=self.args.plan_sha256, bytes=len(PAYLOAD), sha256=subject.digest(PAYLOAD))
        self.config = dict(bindings={'plan_sha256': self.args.plan_sha256, 'sent_sha256': self.args.receipt_sha256},
                           cipher={'bytes': len(PAYLOAD), 'sha256': subject.digest(PAYLOAD)},
                           issued_at='19700101000000Z', start_before='19700101003000Z',
                           expires_at='19700101060000Z', fetch_key_sha256=subject.digest(key.encode()))
        self.installed = dict(status='installed', config=self.config,
                              primary_unchanged=True, secondary_published=True)
        self.write_installed()
        self.calls = []
        self.validators = []
        # The operator/server have separate closed-schema/proof tests. Here their
        # validated results are injected so these tests isolate Mac orchestration.
        self.operator = types.SimpleNamespace(read_transfer_inputs=lambda *a, **k: ({}, copy.deepcopy(self.sent)))
        self.bundle = dict(legacy_operator=legacy, legacy_controller=vars(control),
                           receiver={'LEASE_ID': subject.LEASE_ID, 'CLIENT_TIMEOUT': subject.CLIENT_TIMEOUT,
                                     'FETCH_COMMAND': 'fetch-' + subject.LEASE_ID,
                                     'validate_result': self.validators.append},
                           known_hosts=self.root / 'known-hosts')
        self.loaded = self.operator, self.bundle, transport, legacy.LocalFiles(), ROOT

    @staticmethod
    def write(path, raw, mode=0o600):
        path.write_bytes(raw)
        path.chmod(mode)

    def write_installed(self):
        raw = canonical(self.installed)
        self.write(Path(self.args.installed), raw)
        self.args.install_sha256 = subject.digest(raw)

    def actual_stream(self, code=None, timeout=None):
        code = code or ('import os; os.write(1, ' + repr(PAYLOAD) + ')')
        # Send source through stdin of -c is unnecessary; payload is small and
        # synthetic, and the transport itself still manages real process pipes.
        def stream(argv, sent, output, files, **kwargs):
            self.calls.append((argv, kwargs['timeout']))
            return transport.stream_fetch([sys.executable, '-I', '-B', '-c', code], sent,
                                          output, files, timeout=timeout or kwargs['timeout'])
        return stream

    def run_client(self, stream=None, **kwargs):
        return subject.run(self.args, loaded=self.loaded,
                           stream=stream or self.actual_stream(), now=lambda: 100, **kwargs)

    def assert_preserved(self):
        self.assertEqual(self.partial.read_bytes(), self.original)
        self.assertEqual(transport.identity(self.partial.stat()), self.original_stat)

    def test_full_stream_matches_original_sent_and_preserves_previous_partial(self):
        result = self.run_client()
        self.assertEqual(result['status'], 'fetched_unverified')
        self.assertTrue(result['preserved_unchanged'])
        self.assertEqual(Path(self.args.output).read_bytes(), PAYLOAD)
        self.assertFalse(Path(self.args.output + '.partial').exists())
        self.assert_preserved()
        raw = Path(self.args.output_receipt).read_bytes()
        self.assertEqual(subject.digest(raw), result['result_sha256'])
        self.assertEqual(json.loads(raw)['status'], 'fetched_unverified')
        self.assertLessEqual(self.calls[0][1], 16200)
        self.assertGreater(self.calls[0][1], 3600)
        self.assertEqual(self.calls[0][0][-1], 'fetch-' + subject.LEASE_ID)
        self.assertNotIn(KEY_CANARY.decode(), json.dumps(result))

    def test_transport_key_body_is_never_opened_by_client(self):
        actual_open = os.open
        def opened(path, *args, **kwargs):
            self.assertNotIn(path, (self.args.transport_key, Path(self.args.transport_key), 'fetch-key'))
            return actual_open(path, *args, **kwargs)
        with mock.patch.object(os, 'open', side_effect=opened):
            result = self.run_client()
        self.assertEqual(result['status'], 'fetched_unverified')

    def test_wrong_install_sha_and_bound_sent_refuse_before_network(self):
        self.args.install_sha256 = '0' * 64
        with self.assertRaisesRegex(subject.Refused, 'receipt_refused'):
            self.run_client()
        self.assertFalse(self.calls)
        self.write_installed()
        self.config['bindings']['sent_sha256'] = 'f' * 64
        self.write_installed()
        with self.assertRaisesRegex(subject.Refused, 'receipt_refused'):
            self.run_client()
        self.assertFalse(self.calls)
        self.assert_preserved()

    def test_start_window_checked_again_after_partial_hash(self):
        samples = iter((100, 1801))
        result = subject.run(self.args, loaded=self.loaded, stream=self.actual_stream(), now=lambda: next(samples))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'start_window_expired')
        self.assertFalse(self.calls)
        self.assert_preserved()

    def test_start_window_boundaries_and_expiry_budget(self):
        subject.check_window(self.config, 0)
        subject.check_window(self.config, 1800)
        for now in (-1, 1801):
            with self.assertRaises(subject.Refused):
                subject.check_window(self.config, now)
        invalid = dict(self.config, expires_at='19700101040000Z')
        with self.assertRaisesRegex(subject.Refused, 'lease_refused'):
            subject.check_window(invalid, 100)

    def test_old_name_new_partial_or_result_preexistence_prevents_network(self):
        for kind in ('old-name', 'new-partial', 'result'):
            with self.subTest(kind=kind):
                self.args.output = str(self.partial) if kind == 'old-name' else str(self.root / subject.OUTPUT_NAME)
                path = None
                if kind != 'old-name':
                    path = Path(self.args.output + '.partial') if kind == 'new-partial' else Path(self.args.output_receipt)
                    self.write(path, b'EXISTING_EVIDENCE')
                with self.assertRaises(Exception):
                    self.run_client()
                self.assertFalse(self.calls)
                if path is not None:
                    self.assertEqual(path.read_bytes(), b'EXISTING_EVIDENCE')
                    path.unlink()
                self.assert_preserved()

    def test_preserved_hash_mismatch_never_connects_or_changes_partial(self):
        self.args.preserved_sha256 = 'f' * 64
        result = self.run_client()
        self.assertEqual((result['status'], result['error']), ('failed', 'preserved_partial_changed'))
        self.assertFalse(self.calls)
        self.assert_preserved()

    def test_receive_failure_keeps_new_partial_and_old_partial(self):
        result = self.run_client(self.actual_stream('import os; os.write(1,b"short"); raise SystemExit(7)'))
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(Path(self.args.output).exists())
        self.assertEqual(Path(self.args.output + '.partial').read_bytes(), b'short')
        self.assert_preserved()

    def test_full_bytes_then_nonzero_does_not_publish(self):
        code = 'import os; os.write(1, ' + repr(PAYLOAD) + '); raise SystemExit(7)'
        result = self.run_client(self.actual_stream(code))
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(Path(self.args.output).exists())
        self.assertEqual(Path(self.args.output + '.partial').read_bytes(), PAYLOAD)
        self.assert_preserved()

    def test_actual_stalled_child_times_out_is_reaped_and_retains_evidence(self):
        pidpath = self.root / 'child.pid'
        code = ('import os,time; open(' + repr(str(pidpath)) + ',"w").write(str(os.getpid())); '
                'os.write(1,b"short"); time.sleep(10)')
        start = time.monotonic()
        result = self.run_client(self.actual_stream(code, timeout=.3))
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual(result['error'], 'deadline_exceeded')
        self.assertFalse(Path(self.args.output).exists())
        self.assertEqual(Path(self.args.output + '.partial').read_bytes(), b'short')
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pidpath.read_text()), 0)
        self.assert_preserved()

    def test_deadline_covers_preflight_and_no_network_happens_after_it(self):
        values = iter((0, 16201))
        result = self.run_client(monotonic=lambda: next(values))
        self.assertEqual(result['error'], 'deadline_exceeded')
        self.assertFalse(self.calls)
        self.assert_preserved()

    def test_cli_alarm_bounds_blocked_stream_and_reaps_real_child(self):
        issued = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        for name, seconds in (('issued_at', 0), ('start_before', 1800), ('expires_at', 21600)):
            self.config[name] = (issued + datetime.timedelta(seconds=seconds)).strftime('%Y%m%d%H%M%SZ')
        self.write_installed()
        pidpath = self.root / 'alarm-child.pid'
        code = ('import os,time; open(' + repr(str(pidpath)) + ',"w").write(str(os.getpid())); '
                'os.write(1,b"short"); time.sleep(10)')
        actual = transport.stream_fetch
        def stalled(argv, sent, output, files, **kwargs):
            return actual([sys.executable, '-I', '-B', '-c', code], sent, output, files, timeout=30)
        argv = [item for key, value in vars(self.args).items() for item in ('--' + key.replace('_', '-'), str(value))]
        output = io.StringIO()
        started = time.monotonic()
        mask = os.umask(0o077)
        try:
            with mock.patch.object(subject, 'CLIENT_TIMEOUT', 1), \
                 mock.patch.dict(self.bundle['receiver'], CLIENT_TIMEOUT=1), \
                 mock.patch.object(subject, 'dependencies', return_value=self.loaded), \
                 mock.patch.object(transport, 'stream_fetch', side_effect=stalled), \
                 contextlib.redirect_stdout(output):
                rc = subject.main(argv)
        finally:
            os.umask(mask)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(output.getvalue())['error'], 'deadline_exceeded')
        self.assertFalse(Path(self.args.output).exists())
        self.assertEqual(Path(self.args.output + '.partial').read_bytes(), b'short')
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pidpath.read_text()), 0)
        self.assert_preserved()

    def test_mutated_preserved_file_cannot_publish_success_receipt(self):
        def stream(*args, **kwargs):
            self.write(self.partial, b'X' * len(self.original))
            return dict(status='fetched_unverified', session=transport.SESSION,
                        plan_sha256=self.args.plan_sha256, bytes=len(PAYLOAD), sha256=subject.digest(PAYLOAD))
        result = self.run_client(stream)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['preserved_unchanged'])
        self.assertEqual(json.loads(Path(self.args.output_receipt).read_bytes())['status'], 'failed')

    def test_checked_bootstrap_rejects_symlink_and_modified_public_bytes(self):
        path = self.root / 'public.py'
        self.write(path, b'print("synthetic")\n', 0o644)
        sha = subject.digest(path.read_bytes())
        self.assertEqual(subject.bootstrap_read(path, sha), path.read_bytes())
        linked = self.root / 'linked.py'
        linked.symlink_to(path)
        with self.assertRaises(Exception):
            subject.bootstrap_read(linked, sha)
        self.write(path, b'print("changed")\n', 0o644)
        with self.assertRaisesRegex(subject.Refused, 'asset_refused'):
            subject.bootstrap_read(path, sha)

    def test_real_operator_and_server_validators_feed_the_existing_stream(self):
        path = Path(__file__).with_name('test_naver_archive_refetch_operator.py')
        spec = importlib.util.spec_from_file_location('refetch_proof_fixture', path)
        test_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(test_module)
        fixture = test_module.RefetchOperatorTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.sent.update(bytes=len(PAYLOAD), sha256=subject.digest(PAYLOAD))
        fixture.proof('sent', fixture.sent)
        fixture.result = fixture.installed_result()
        receipt = fixture.run_operator()
        old_partial = fixture.root / subject.PRESERVED_NAME
        self.write(old_partial, self.original)
        args = types.SimpleNamespace(
            plan=str(fixture.args.plan), plan_sha256=fixture.args.plan_sha256,
            sent_receipt=str(fixture.args.sent), receipt_sha256=fixture.args.sent_sha256,
            installed=str(fixture.args.output), install_sha256=receipt['receipt_sha256'],
            fetch_public_key=str(fixture.args.fetch_public_key), transport_key=str(fixture.args.admin_key),
            preserved_partial=str(old_partial), preserved_sha256=subject.digest(self.original),
            output=str(fixture.root / subject.OUTPUT_NAME), output_receipt=str(fixture.root / 'fetched.json'))
        loaded = (test_module.subject, fixture.bundle, transport, legacy.LocalFiles(), fixture.directory)
        result = subject.run(args, loaded=loaded, stream=self.actual_stream(),
                             now=lambda: subject.timestamp(fixture.result['config']['issued_at']) + 100)
        self.assertEqual(result['status'], 'fetched_unverified')
        self.assertEqual(Path(args.output).read_bytes(), PAYLOAD)
        self.assertEqual(old_partial.read_bytes(), self.original)

    def test_release_pins_load_the_actual_public_dependency_chain(self):
        # No patched hashes or network: the CLI's shipped pins must load the
        # exact released source tree, including all transitive plan validators.
        operator, bundle, actual_transport, files, directory = subject.dependencies(ROOT)
        self.assertEqual(subject.OPERATOR_SHA256,
                         subject.digest((ROOT / 'naver_archive_refetch_operator.py').read_bytes()))
        self.assertEqual(operator.RECEIVER_SHA256, subject.digest(bundle['receiver_raw']))
        self.assertEqual(bundle['receiver']['MODULE_SOURCE'], bundle['receiver_raw'])
        self.assertEqual(bundle['receiver']['SERVER_TIMEOUT'], 14400)
        self.assertEqual(bundle['receiver']['CLIENT_TIMEOUT'], subject.CLIENT_TIMEOUT)
        self.assertEqual(actual_transport.SESSION, 'naver-archives-20261106-v1')
        operator._transfer_modules(directory, files)


if __name__ == '__main__':
    unittest.main()
