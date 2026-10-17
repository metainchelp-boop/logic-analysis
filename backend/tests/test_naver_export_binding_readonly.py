"""New diagnostic-only focused tests. No operating source or host access."""
import ast
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import patch

TEST_PATH = Path(__file__).resolve()
CORE_PATH = TEST_PATH.with_name('inspect_export_binding.py')
if not CORE_PATH.is_file():
    CORE_PATH = TEST_PATH.parents[1]/'tools/naver_export_binding_readonly.py'
SPEC = importlib.util.spec_from_file_location('export_binding_diagnostic_draft', CORE_PATH)
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)


class ExportInstallInvalid(ValueError):
    pass


def fixture(failure=None, code='EXPORT_RUN_NOT_VERIFIED'):
    calls = []
    helper = types.SimpleNamespace(ExportInstallInvalid=ExportInstallInvalid)
    sources = {'exports_helper': b'public-helper', 'product_exporter': b'public-product',
               'market_exporter': b'public-market'}
    release = D.ReadOnlyRelease()

    class Binding:
        def __init__(self, *args):
            calls.append('construction')
            if failure == 'construction':
                raise ExportInstallInvalid(code)
            self.receipt = {'fixture': True}
            self.command = release.command

        def load(self, package, *, verify):
            calls.append(('load', verify, package == D.PACKAGE))
            if failure == 'prepared':
                raise ExportInstallInvalid(code)

        def operation(self, callback):
            calls.append('operation')
            return callback()

    def verify(receipt, *, command):
        calls.append('verify')
        if failure == 'verify':
            raise ExportInstallInvalid(code)
        return {'private_result_is_not_returned': 'RAW_SECRET_MARKER'}

    helper.verify = verify
    return types.SimpleNamespace(Binding=Binding), helper, sources, release, calls


def real_public_modules():
    tools = TEST_PATH.parents[1]/'tools'
    if not (tools/'naver_saved_exports.py').is_file():
        root = next(parent for parent in TEST_PATH.parents
                    if (parent/'work/naver-claude-reference-ops-20261011/backend/tools').is_dir())
        tools = root/'work/naver-claude-reference-ops-20261011/backend/tools'
    names = {'exports_binding': 'naver_completion_exports.py',
             'exports_helper': 'naver_saved_exports.py',
             'product_exporter': '../naver_product_export.py',
             'market_exporter': '../naver_market_export.py'}
    sources = {role: (tools/name).read_bytes() for role, name in names.items()}
    D.require_pins(sources)
    binding, helper = D._load_modules(sources)
    return tools, sources, binding, helper


class ExistingBindingDiagnosticTests(unittest.TestCase):
    def test_exact_public_sources_construct_binding_without_host_access(self):
        tools, sources, binding, helper = real_public_modules()
        with patch.object(helper, '_prepared') as prepared, patch.object(helper, 'verify') as verify:
            instance = binding.Binding(types.SimpleNamespace(TARGET_COMMIT=D.EXPORT_SOURCE),
                helper, D.ReadOnlyRelease(), sources['exports_helper'], {
                    'naver_product_export.py': sources['product_exporter'],
                    'naver_market_export.py': sources['market_exporter']})
        self.assertIsNone(instance.receipt)
        prepared.assert_not_called()
        verify.assert_not_called()
        # Compare with the existing reviewed allowlist without executing controller/host code.
        tree = ast.parse((tools/'naver_preview_completion_release.py').read_bytes())
        node = next(n for n in tree.body if isinstance(n, ast.Assign) and
                    any(isinstance(t, ast.Name) and t.id == 'EXPORT_FAILURE_CODES' for t in n.targets))
        self.assertIsInstance(node.value, ast.Call)
        literal = node.value.args[0].func.value
        self.assertEqual(D.EXPORT_CODES, frozenset(ast.literal_eval(literal).split()))

    def test_pending_cipher_pin_blocks_before_modules_and_host(self):
        with (patch.dict(D.PACKAGE, ciphertext_sha256=None),
              patch.object(D, '_load_modules') as load,
              patch.object(D, '_read_operating_receipt') as read):
            result = D.diagnose({})
        self.assertEqual((result['phase'], result['error_code']), ('pins', 'DIAGNOSTIC_PIN'))
        load.assert_not_called()
        read.assert_not_called()

    def test_foreign_source_refuses_before_any_module_execution(self):
        with patch.dict(D.PACKAGE, ciphertext_sha256='1'*64), patch.object(D, '_load_modules') as load:
            result = D.diagnose({role: b'raise RuntimeError("RAW_SECRET_MARKER")' for role in D.SOURCE_PINS})
        self.assertEqual(result['error_code'], 'DIAGNOSTIC_SOURCE')
        load.assert_not_called()

    def test_success_uses_original_load_without_verify_then_original_verify_once(self):
        binding, helper, sources, release, calls = fixture()
        result = D._observe(binding, helper, sources, release, lambda: True)
        self.assertEqual(calls, ['construction', ('load', False, True), 'operation', 'verify'])
        self.assertEqual((result['ok'], result['phase']), (True, 'complete'))
        self.assertNotIn('RAW_SECRET_MARKER', D.closed_json(result))
        self.assertFalse(result['base_history_revalidated'])
        self.assertFalse(result['running_container_verified'])

    def test_each_new_first_failure_phase_stops_following_stages(self):
        for phase in ('construction', 'prepared', 'verify'):
            with self.subTest(phase=phase):
                binding, helper, sources, release, calls = fixture(phase)
                result = D._observe(binding, helper, sources, release, lambda: True)
                self.assertEqual((result['ok'], result['phase'], result['error_code']),
                                 (False, phase, 'EXPORT_RUN_NOT_VERIFIED'))
                if phase != 'verify':
                    self.assertNotIn('verify', calls)

    def test_operating_receipt_refusal_prevents_binding_and_is_not_running_proof(self):
        binding, helper, sources, release, calls = fixture()
        result = D._observe(binding, helper, sources, release, lambda: False)
        self.assertEqual((result['phase'], result['error_code']),
                         ('operating_receipt', 'DIAGNOSTIC_RECEIPT'))
        self.assertEqual(calls, [])
        self.assertFalse(result['operating_receipt_match'])

    def test_only_exact_helper_exception_and_reviewed_single_code_are_exposed(self):
        helper = types.SimpleNamespace(ExportInstallInvalid=ExportInstallInvalid)
        self.assertEqual(D._closed_error(ExportInstallInvalid('EXPORT_FILE_POLICY'), helper),
                         ('ExportInstallInvalid', 'EXPORT_FILE_POLICY'))
        class Foreign(ExportInstallInvalid):
            pass
        for error in (Foreign('EXPORT_FILE_POLICY'), ValueError('EXPORT_FILE_POLICY'),
                      ExportInstallInvalid('EXPORT_UNREVIEWED'),
                      ExportInstallInvalid('EXPORT_FILE_POLICY', 'RAW_SECRET_MARKER'),
                      ExportInstallInvalid('RAW_SECRET_MARKER')):
            self.assertEqual(D._closed_error(error, helper)[1], 'UNRECOGNIZED')
            self.assertNotIn('RAW_SECRET_MARKER', repr(D._closed_error(error, helper)))

    def test_mutating_or_arbitrary_commands_reject_before_subprocess(self):
        release = D.ReadOnlyRelease()
        with patch.object(D.subprocess, 'run') as run:
            for args in (['systemctl', 'start', D.UNITS['product']],
                         ['systemctl', 'restart', D.UNITS['product']],
                         ['systemctl', 'daemon-reload'],
                         ['systemctl', 'show', 'other.service', '--property=Result', '--property=ExecMainStatus'],
                         ['journalctl', '--no-pager'], ['docker', 'exec', 'x', 'env'],
                         ['openssl', 'cms', '-decrypt'], ['sh', '-c', 'anything']):
                with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'DIAGNOSTIC_COMMAND'):
                    release.command(args)
        run.assert_not_called()

    def test_unit_result_projection_keeps_only_boolean_and_no_raw_output(self):
        release = D.ReadOnlyRelease()
        args = ['systemctl', 'show', D.UNITS['product'], '--property=Result', '--property=ExecMainStatus']
        raw = b'Result=success\nExecMainStatus=0\n'
        with patch.object(D.subprocess, 'run', return_value=types.SimpleNamespace(
                stdout=raw, stderr=b'', returncode=0)) as run:
            self.assertEqual(release.command(args), raw)
        self.assertEqual(release.unit_results['product'], True)
        self.assertEqual(run.call_args.args[0][0], '/usr/bin/systemctl')
        self.assertEqual(run.call_args.kwargs['timeout'], 8)
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs['env'], {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})

    def test_command_output_oversize_and_failed_service_never_expose_body(self):
        args = ['systemctl', 'show', D.UNITS['product'], '--property=Result', '--property=ExecMainStatus']
        for value in (types.SimpleNamespace(stdout=b'x'*(D.MAX_OUTPUT+1), stderr=b'', returncode=0),
                      types.SimpleNamespace(stdout=b'RAW_SECRET_MARKER', stderr=b'raw-error', returncode=1)):
            release = D.ReadOnlyRelease()
            with patch.object(D.subprocess, 'run', return_value=value):
                with self.assertRaises((ValueError, RuntimeError)) as caught:
                    release.command(args)
            self.assertNotIn('RAW_SECRET_MARKER', str(caught.exception))

    def test_existing_directory_new_option_cannot_mkdir_or_stat(self):
        with patch.object(Path, 'mkdir') as mkdir, patch.object(Path, 'lstat') as lstat:
            with self.assertRaisesRegex(ValueError, 'DIAGNOSTIC_EXISTING_DIRECTORY'):
                D.existing_directory('/fixed/not-created', new=True)
        mkdir.assert_not_called()
        lstat.assert_not_called()

    def test_release_surface_has_no_write_install_decrypt_or_history_entrypoints(self):
        release = D.ReadOnlyRelease()
        for name in ('write_new', 'extract_source', 'received_ciphertext', 'decode_payload',
                     'prepare', 'apply', 'install', 'manifest', 'base_success', 'historical_success'):
            self.assertFalse(hasattr(release, name), name)

    def test_final_projection_refuses_unknown_fields_or_phases(self):
        for value in ({'phase': 'complete', 'raw': 'RAW_SECRET_MARKER'},
                      {'phase': 'RAW_SECRET_MARKER'}, []):
            with self.assertRaisesRegex(ValueError, 'DIAGNOSTIC_RESULT'):
                D.closed_json(value)

    def test_final_projection_blocks_strings_hidden_in_boolean_or_code_slots(self):
        binding, helper, sources, release, _ = fixture()
        result = D._observe(binding, helper, sources, release, lambda: True)
        for key, value in (('error_code', 'RAW_SECRET_MARKER'),
                           ('error_component', 'RAW_SECRET_MARKER'),
                           ('underlying_export_error_code', 'RAW_SECRET_MARKER'),
                           ('operating_source', 'RAW_SECRET_MARKER'),
                           ('operating_receipt_match', 'RAW_SECRET_MARKER'),
                           ('unit_result_success', {role: 'RAW_SECRET_MARKER' for role in D.UNITS})):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'DIAGNOSTIC_RESULT'):
                D.closed_json({**result, key: value})

    def test_timer_read_commands_preserve_exit_policy_and_project_boolean(self):
        release = D.ReadOnlyRelease()
        with patch.object(D.subprocess, 'run', return_value=types.SimpleNamespace(
                stdout=b'enabled\n', stderr=b'', returncode=0)):
            release.command(['systemctl', 'is-enabled', D.TIMERS['market']])
            release.command(['systemctl', 'is-active', D.TIMERS['market']])
        self.assertEqual(release.timer_results['market'], {'enabled': True, 'active': True})
        self.assertEqual(release.timer_results['product'], {'enabled': None, 'active': None})

    def test_original_stale_bundle_context_is_closed_without_repeating_read(self):
        _, _, _, helper = real_public_modules()
        now = datetime(2026, 10, 17, 2, 0, tzinfo=timezone.utc)
        raw = json.dumps({'schema_version': 1, 'complete': True,
                          'exported_at': (now-timedelta(hours=31)).isoformat(),
                          'stores': []}).encode()
        with (patch.object(helper, '_directory', return_value=types.SimpleNamespace(st_gid=10001)) as directory,
              patch.object(helper, '_regular', return_value=raw) as read,
              patch.object(helper.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_uid=99))):
            try:
                helper._bundle_summary_for_user('product', now, 'fixture')
            except helper.ExportInstallInvalid as error:
                self.assertEqual(error.args, ('EXPORT_BUNDLE_INVALID',))
                component = D._failure_component(error, helper)
                self.assertEqual(component, 'product_bundle')
                self.assertEqual(D._underlying_export_code(error, helper, component), 'EXPORT_BUNDLE_STALE')
            else:
                self.fail('original helper must reject stale synthetic bundle')
        self.assertEqual(read.call_count, 1)
        self.assertEqual(directory.call_count, 1)

    def test_original_bad_timestamp_does_not_expose_context_exception_prose(self):
        _, _, _, helper = real_public_modules()
        raw = json.dumps({'schema_version': 1, 'complete': True,
                          'exported_at': 'RAW_SECRET_MARKER', 'stores': []}).encode()
        with (patch.object(helper, '_directory', return_value=types.SimpleNamespace(st_gid=10001)),
              patch.object(helper, '_regular', return_value=raw),
              patch.object(helper.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_uid=99))):
            try:
                helper._bundle_summary_for_user('market', datetime.now(timezone.utc), 'fixture')
            except helper.ExportInstallInvalid as error:
                component = D._failure_component(error, helper)
                closed = D._underlying_export_code(error, helper, component)
                self.assertEqual(component, 'market_bundle')
                self.assertIsNone(closed)
                self.assertNotIn('RAW_SECRET_MARKER', repr((component, closed, D._closed_error(error, helper))))
            else:
                self.fail('original helper must reject invalid synthetic timestamp')

    def test_original_verify_exact_unit_failure_component_without_host_commands(self):
        _, _, _, helper = real_public_modules()
        plan = {'fixture': True}
        receipt = {'source_identity': {}, 'runtime_identity': {}}
        queries = []
        def command(args):
            queries.append(args)
            return b'Result=success\nExecMainStatus=0\n' if len(queries) == 1 else b'Result=failed\nExecMainStatus=1\n'
        with (patch.object(helper, '_prepared', return_value=(plan, Path('/synthetic'), {})),
              patch.object(helper, '_source_identity', return_value={}),
              patch.object(helper, '_identity', return_value={}),
              patch.object(helper, '_regular', return_value=b'{}')):
            try:
                helper.verify(receipt, command=command)
            except helper.ExportInstallInvalid as error:
                self.assertEqual(error.args, ('EXPORT_RUN_NOT_VERIFIED',))
                self.assertEqual(D._failure_component(error, helper), 'product_reader_result')
            else:
                self.fail('original helper must reject unsuccessful synthetic unit')
        self.assertEqual(len(queries), 2)

    def test_original_verify_source_identity_component_precedes_all_unit_queries(self):
        _, _, _, helper = real_public_modules()
        receipt = {'source_identity': {'expected': True}, 'runtime_identity': {}}
        with (patch.object(helper, '_prepared', return_value=({}, Path('/synthetic'), {})),
              patch.object(helper, '_source_identity', return_value={}),
              patch.object(helper, '_command') as command):
            try:
                helper.verify(receipt, command=lambda _: None)
            except helper.ExportInstallInvalid as error:
                self.assertEqual(D._failure_component(error, helper), 'source_identity')
            else:
                self.fail('original helper must reject changed synthetic identity')
        command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
