"""Synthetic evidence/public modules only; never SSH or real private key access."""
import base64
import contextlib
import copy
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import py_compile
import stat
import tempfile
import types
import unittest
from unittest import mock

PATH = Path(__file__).resolve().parents[1] / 'naver_archive_refetch_operator.py'
SPEC = importlib.util.spec_from_file_location('refetch_operator_tested', PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
CANARY = b'SYNTHETIC_ADMIN_KEY_BODY_MUST_NOT_BE_READ_OR_SENT'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def public_key(byte):
    return 'ssh-ed25519 ' + base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes([byte]) * 32).decode()


def meta(inode, size=100, directory=False, sha='a' * 64):
    row = dict(device=1, inode=inode, uid=0, gid=0, mode=0o700 if directory else 0o600,
               links=2 if directory else 1, bytes=size)
    if not directory:
        row['sha256'] = sha
    return row


def source_identity(size=0, mode=0o600):
    return dict(device=1, inode=2, mode=mode, uid=0, gid=0, size=size,
                links=1, mtime_ns=1, ctime_ns=2, allocated_bytes=size)


class RefetchOperatorTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='.refetch-operator-', dir=Path(__file__).parent)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.root.chmod(0o700)
        self.directory = self.root / 'tools'
        self.directory.mkdir(mode=0o700)
        (self.directory / 'preservation').mkdir(mode=0o700)
        names = list(subject.TRANSFER_PINS) + ['naver_archive_receiver_operator.py',
            'naver_archive_receiver_control.py', 'naver_archive_refetch_receiver.py',
            'preservation/server-b-known-hosts']
        for name in names:
            self.write(self.directory / name, (PATH.parent / name).read_bytes(), 0o644)
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        receiver_raw = (self.directory / 'naver_archive_refetch_receiver.py').read_bytes()
        self.patches.enter_context(mock.patch.object(subject, 'RECEIVER_SHA256', subject.digest(receiver_raw)))
        self.bundle = subject.load_bundle(self.directory)
        self.legacy, self.receiver = self.bundle['legacy_controller'], self.bundle['receiver']
        self.args = types.SimpleNamespace(action='install', admin_key=self.root / 'admin-key',
            output=self.root / 'result.json', plan=self.root / 'plan.json', sent=self.root / 'sent.json',
            old_install=self.root / 'old-install.json', old_revoke=self.root / 'old-revoke.json',
            fetch_public_key=self.root / 'fetch.pub', fetch_ip='198.51.100.2')
        self.write(self.args.admin_key, CANARY)
        self.write(self.args.fetch_public_key, (public_key(12) + ' synthetic\n').encode(), 0o644)
        files = [dict(name=name, size=2, sha256='a' * 64, identity=source_identity(2)) for name in
                 ('snapshot.sqlite.json', 'snapshot.sqlite.gz', 'packed.zip.broken')]
        self.plan = dict(version=1, session='naver-archives-20261106-v1', total_bytes=6,
            groups=[dict(kind='interrupted', name='naver-engine-interrupted-20261106',
                         identity=source_identity(mode=0o700), files=files)])
        self.proof('plan', self.plan)
        self.sent = dict(status='sent_unverified', session='naver-archives-20261106-v1',
            plan_sha256=self.args.plan_sha256, bytes=64, sha256='b' * 64)
        self.proof('sent', self.sent)
        self.old_install = self.legacy['empty_result']('install')
        self.old_install.update(status='installed', error=None, expires_at='20261107080150Z',
            source_ip='192.0.2.1', fetch_ip=self.args.fetch_ip,
            send_key_sha256=subject.digest(public_key(11).encode()),
            fetch_key_sha256=subject.digest(public_key(12).encode()), primary=meta(1),
            primary_unchanged=True, secondary=meta(2), secondary_published=True, pending=meta(2),
            tool_directory=meta(3, directory=True), data_directory=meta(4, directory=True),
            receiver=meta(5, sha=self.legacy['RECEIVER_SHA256']))
        self.legacy['validate_result'](self.old_install)
        self.old_revoke = dict(self.old_install, action='revoke', status='revoked')
        self.proof('old_install', self.old_install)
        self.proof('old_revoke', self.old_revoke)
        self.calls = []
        self.result = self.installed_result()

    def write(self, path, raw, mode=0o600):
        Path(path).write_bytes(raw)
        Path(path).chmod(mode)

    def proof(self, name, value):
        raw = canonical(value)
        self.write(getattr(self.args, name), raw)
        setattr(self.args, name + '_sha256', subject.digest(raw))

    def request(self):
        return subject._install_request(self.args, self.bundle,
            self.bundle['legacy_operator'].LocalFiles(), self.directory)

    def installed_result(self):
        request = self.request()
        identity = {k: v for k, v in meta(91, size=self.sent['bytes']).items() if k != 'sha256'}
        identity.update(mtime_ns=11, ctime_ns=12)
        lock = dict(identity, inode=92, bytes=0)
        directory = dict(identity, inode=93, bytes=4096, links=2, mode=0o700)
        config = self.receiver['build_config'](request, identity,
            datetime.datetime(2026, 11, 7, 9, 0, 0, tzinfo=datetime.timezone.utc),
            lock_identity=lock, data_identity=directory)
        result = dict(version=1, action='install', lease_id=self.receiver['LEASE_ID'], status='installed',
            error=None, config=config, config_sha256=subject.digest(canonical(config)),
            primary=copy.deepcopy(self.old_install['primary']), primary_unchanged=True,
            secondary=meta(21), secondary_published=True, pending=meta(21),
            tool_directory=meta(22, directory=True), receiver=meta(23, sha=subject.RECEIVER_SHA256),
            legacy=meta(24, sha=subject.LEGACY_CONTROLLER_SHA256),
            config_file=meta(25, size=len(canonical(config)), sha=subject.digest(canonical(config))))
        return self.receiver['validate_result'](result)

    def remote(self, argv, request, timeout):
        self.calls.append((argv, copy.deepcopy(request), timeout))
        return (2 if self.result['status'] == 'failed' else 0), copy.deepcopy(self.result)

    def run_operator(self, **kwargs):
        return subject.run(self.args, directory=self.directory, remote=kwargs.pop('remote', self.remote), **kwargs)

    def test_install_binds_every_original_proof_reused_key_and_saves_private_result(self):
        result = self.run_operator()
        argv, request, timeout = self.calls[0]
        self.assertEqual(timeout, 600)
        self.assertEqual(request, self.request())
        self.receiver['validate_request'](request)
        self.assertEqual(json.loads(self.args.output.read_bytes()), self.result)
        self.assertEqual(result['receipt_sha256'], subject.digest(self.args.output.read_bytes()))
        self.assertEqual(stat.S_IMODE(self.args.output.stat().st_mode), 0o600)
        self.assertNotIn(CANARY.decode(), repr(self.calls))
        self.assertEqual(argv[-2], self.bundle['legacy_operator'].SERVER)
        self.assertIn('IdentityAgent=none', argv)
        self.assertIn('StrictHostKeyChecking=yes', argv)
        self.assertIn('ForwardAgent=no', argv)
        self.assertEqual(result['status'], 'installed')

    def test_admin_key_body_is_never_opened(self):
        actual = os.open
        def opened(path, *args, **kwargs):
            self.assertNotIn(path, (self.args.admin_key, str(self.args.admin_key), self.args.admin_key.name))
            return actual(path, *args, **kwargs)
        with mock.patch('os.open', side_effect=opened):
            self.run_operator()
        self.assertNotIn(CANARY.decode(), repr(self.calls))

    def test_transfer_input_helper_validates_full_canonical_plan_and_receipt(self):
        result = subject.read_transfer_inputs(self.args.plan, self.args.plan_sha256,
            self.args.sent, self.args.sent_sha256, directory=self.directory)
        self.assertEqual(result, (self.plan, self.sent))

    def test_each_raw_hash_mismatch_stops_before_remote_and_output(self):
        for field in ('plan_sha256', 'sent_sha256', 'old_install_sha256', 'old_revoke_sha256'):
            old = getattr(self.args, field)
            with self.subTest(field=field):
                setattr(self.args, field, '0' * 64)
                with self.assertRaises(Exception):
                    self.run_operator()
                setattr(self.args, field, old)
                self.assertEqual(self.calls, [])
                self.assertFalse(self.args.output.exists())

    def test_noncanonical_evidence_even_with_correct_raw_sha_is_refused(self):
        for name in ('plan', 'sent', 'old_install', 'old_revoke'):
            path = getattr(self.args, name)
            raw = path.read_bytes()
            self.write(path, raw + b'\n')
            setattr(self.args, name + '_sha256', subject.digest(raw + b'\n'))
            with self.subTest(name=name), self.assertRaisesRegex(subject.Refused, 'evidence_refused'):
                self.run_operator()
            self.write(path, raw)
            setattr(self.args, name + '_sha256', subject.digest(raw))
        self.assertEqual(self.calls, [])

    def test_unknown_plan_field_duplicate_json_and_nonfinite_values_are_refused(self):
        variants = [canonical(dict(self.plan, extra=True)), b'{"version":1,"version":1}', b'NaN']
        for raw in variants:
            self.write(self.args.plan, raw)
            self.args.plan_sha256 = subject.digest(raw)
            with self.subTest(raw=raw), self.assertRaises(subject.Refused):
                self.run_operator()
        self.assertEqual(self.calls, [])

    def test_sent_plan_binding_mismatch_is_refused(self):
        self.proof('sent', dict(self.sent, plan_sha256='c' * 64))
        with self.assertRaisesRegex(subject.Refused, 'evidence_refused'):
            self.run_operator()
        self.assertEqual(self.calls, [])

    def test_revoke_must_be_successful_and_exactly_bound_to_old_install(self):
        variants = [dict(self.old_revoke, status='installed', action='install'),
                    dict(self.old_revoke, primary_unchanged=False),
                    dict(self.old_revoke, fetch_ip='198.51.100.9'),
                    dict(self.old_revoke, secondary=dict(self.old_revoke['secondary'], inode=333)),
                    dict(self.old_revoke, primary=dict(self.old_revoke['primary'], sha256='f' * 64))]
        for value in variants:
            with self.subTest(value=value):
                self.proof('old_revoke', value)
                with self.assertRaises(subject.Refused):
                    self.run_operator()
                self.assertEqual(self.calls, [])
        self.assertFalse(self.args.output.exists())

    def test_old_already_absent_receipt_is_allowed_when_all_fields_match(self):
        self.proof('old_revoke', dict(self.old_revoke, status='already_absent'))
        self.result = self.installed_result()
        self.assertEqual(self.run_operator()['status'], 'installed')

    def test_different_fetch_key_and_invalid_ip_are_refused(self):
        self.write(self.args.fetch_public_key, public_key(13).encode())
        with self.assertRaisesRegex(subject.Refused, 'evidence_refused'):
            self.run_operator()
        self.write(self.args.fetch_public_key, public_key(12).encode())
        for ip in ('198.51.100.2,198.51.100.3', '::1', '0198.51.100.2', 'example.test'):
            self.args.fetch_ip = ip
            with self.subTest(ip=ip), self.assertRaises(subject.Refused):
                self.run_operator()
        self.assertEqual(self.calls, [])

    def test_symlink_hardlink_or_insecure_evidence_is_refused(self):
        path = self.args.sent
        saved = self.root / 'sent-saved.json'
        path.rename(saved)
        for create in (lambda: path.symlink_to(saved), lambda: os.link(saved, path)):
            create()
            with self.assertRaises(Exception):
                self.run_operator()
            path.unlink()
        saved.rename(path)
        path.chmod(0o644)
        with self.assertRaises(Exception):
            self.run_operator()
        self.assertEqual(self.calls, [])

    def test_each_public_asset_hash_mismatch_is_refused_before_remote(self):
        for name in ('LEGACY_OPERATOR_SHA256', 'LEGACY_CONTROLLER_SHA256', 'RECEIVER_SHA256', 'KNOWN_HOSTS_SHA256'):
            with self.subTest(name=name), mock.patch.object(subject, name, '0' * 64):
                with self.assertRaises(Exception):
                    self.run_operator()
            self.assertEqual(self.calls, [])
        for asset in subject.TRANSFER_PINS:
            changed = dict(subject.TRANSFER_PINS, **{asset: '0' * 64})
            with self.subTest(asset=asset), mock.patch.object(subject, 'TRANSFER_PINS', changed):
                with self.assertRaisesRegex(subject.Refused, 'bundle_refused'):
                    self.run_operator()
            self.assertEqual(self.calls, [])
        self.assertFalse(self.args.output.exists())

    def test_poisoned_timestamp_valid_dependency_pyc_is_never_loaded(self):
        cold_path = self.directory / 'cold_backup_archive.py'
        raw = cold_path.read_bytes()
        before = cold_path.stat()
        malicious = b"raise RuntimeError('CACHE_POISON_MUST_NOT_EXECUTE')\n"
        self.write(cold_path, malicious + b' ' * (len(raw) - len(malicious)), 0o644)
        os.utime(cold_path, ns=(before.st_atime_ns, before.st_mtime_ns))
        py_compile.compile(str(cold_path), doraise=True)
        self.write(cold_path, raw, 0o644)
        os.utime(cold_path, ns=(before.st_atime_ns, before.st_mtime_ns))
        plan, sent = subject.read_transfer_inputs(self.args.plan, self.args.plan_sha256,
            self.args.sent, self.args.sent_sha256, directory=self.directory)
        self.assertEqual((plan, sent), (self.plan, self.sent))
        common, _ = subject._transfer_modules(self.directory, self.bundle['legacy_operator'].LocalFiles())
        self.assertIn('54fc-cold-backup-lossless-gzip6-v1', common.cold.PROFILES)
        self.assertIs(common.bundle_helper().A, common.cold)

    def test_in_memory_loader_refuses_unknown_dependencies(self):
        common, _ = subject._transfer_modules(self.directory, self.bundle['legacy_operator'].LocalFiles())
        with self.assertRaisesRegex(subject.Refused, 'bundle_refused'):
            common.sibling('unreviewed')

    def test_preexisting_output_is_preserved_and_remote_is_not_called(self):
        self.write(self.args.output, b'preserve-existing-output')
        with self.assertRaises(Exception):
            self.run_operator()
        self.assertEqual(self.args.output.read_bytes(), b'preserve-existing-output')
        self.assertEqual(self.calls, [])

    def test_remote_failure_keeps_reserved_output_and_never_retries(self):
        def failed(argv, request, timeout):
            self.calls.append((argv, request, timeout))
            raise subject.Refused('remote_unknown')
        with self.assertRaisesRegex(subject.Refused, 'remote_unknown'):
            self.run_operator(remote=failed)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.args.output.read_bytes(), b'')
        with self.assertRaises(Exception):
            self.run_operator(remote=failed)
        self.assertEqual(len(self.calls), 1)

    def test_failed_published_install_preserves_full_exact_revocation_evidence(self):
        self.result.update(status='failed', error='primary_changed', primary_unchanged=False)
        self.result['primary'] = dict(self.result['primary'], sha256='e' * 64)
        result = self.run_operator()
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['primary_unchanged'])
        self.assertTrue(self.result['secondary_published'])
        self.assertEqual(json.loads(self.args.output.read_bytes()), self.result)
        self.assertEqual(result['receipt_sha256'], subject.digest(self.args.output.read_bytes()))
        self.assertEqual(len(self.calls), 1)

    def test_failed_before_config_still_saves_bounded_report_without_claiming_no_remote_changes(self):
        self.result = self.receiver['empty_result']('install')
        self.result.update(error='busy', primary=copy.deepcopy(self.old_install['primary']), primary_unchanged=True)
        result = self.run_operator()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(json.loads(self.args.output.read_bytes()), self.result)
        self.assertEqual(len(self.calls), 1)

    def test_result_with_other_bound_plan_is_refused_but_reserved_output_remains(self):
        result = copy.deepcopy(self.result)
        result['config']['bindings']['plan_sha256'] = 'f' * 64
        result['config_sha256'] = subject.digest(canonical(result['config']))
        result['config_file']['sha256'] = result['config_sha256']
        self.result = result
        with self.assertRaisesRegex(subject.Refused, 'receipt_refused'):
            self.run_operator()
        self.assertEqual(self.args.output.read_bytes(), b'')

    def test_post_save_admin_key_metadata_change_keeps_valid_revocation_evidence(self):
        def remote(argv, request, timeout):
            result = self.remote(argv, request, timeout)
            os.utime(self.args.admin_key, ns=(1, 2))
            return result
        with self.assertRaisesRegex(subject.Refused, 'path_changed'):
            self.run_operator(remote=remote)
        self.assertEqual(json.loads(self.args.output.read_bytes()), self.result)

    def test_ssh_status_must_agree_with_valid_success_result(self):
        def bad(argv, request, timeout):
            return 2, copy.deepcopy(self.result)
        with self.assertRaisesRegex(subject.Refused, 'receipt_refused'):
            self.run_operator(remote=bad)
        self.assertEqual(self.args.output.read_bytes(), b'')

    def prepare_revoke(self):
        self.args.action = 'revoke'
        self.args.installed = self.root / 'installed.json'
        self.write(self.args.installed, canonical(self.result))
        self.args.receipt_sha256 = subject.digest(canonical(self.result))
        self.result = dict(self.result, action='revoke', status='revoked')

    def test_revoke_uses_exact_install_receipt_and_shorter_bounded_exchange(self):
        self.prepare_revoke()
        result = self.run_operator()
        _, request, timeout = self.calls[0]
        self.assertEqual(set(request), {'action', 'installed'})
        self.assertEqual(timeout, 90)
        self.assertEqual(request['installed']['action'], 'install')
        self.assertEqual(result['status'], 'revoked')

    def test_revoke_sha_mismatch_stops_before_remote(self):
        self.prepare_revoke()
        self.args.receipt_sha256 = '0' * 64
        with self.assertRaisesRegex(subject.Refused, 'evidence_refused'):
            self.run_operator()
        self.assertEqual(self.calls, [])

    def test_revoke_result_cannot_substitute_secondary_identity(self):
        self.prepare_revoke()
        self.result['secondary'] = dict(self.result['secondary'], inode=303)
        self.result['pending'] = copy.deepcopy(self.result['secondary'])
        with self.assertRaisesRegex(subject.Refused, 'receipt_refused'):
            self.run_operator()
        self.assertEqual(self.args.output.read_bytes(), b'')

    def test_bootstrap_contains_only_the_two_pinned_public_sources(self):
        raw = subject.bootstrap(self.bundle)
        self.assertIn(repr(self.bundle['legacy_raw']).encode(), raw)
        self.assertIn(repr(self.bundle['receiver_raw']).encode(), raw)
        self.assertNotIn(CANARY, raw)
        self.assertNotIn(str(self.args.admin_key).encode(), raw)
        self.assertIn(b"sys.exit(R['main_control']())", raw)

    def test_main_emits_only_safe_failure_identifier(self):
        out = io.StringIO()
        with mock.patch.object(subject, 'run', side_effect=RuntimeError(CANARY.decode())), \
                contextlib.redirect_stdout(out):
            code = subject.main(['revoke', '--admin-key', '/synthetic/admin', '--output', '/synthetic/out',
                                 '--installed', '/synthetic/installed', '--receipt-sha256', 'a' * 64])
        self.assertEqual(code, 2)
        self.assertNotIn(CANARY.decode(), out.getvalue())
        self.assertEqual(json.loads(out.getvalue()), dict(status='HOLD', error='operation_failed', retry_authorized=False))


if __name__ == '__main__':
    unittest.main()
