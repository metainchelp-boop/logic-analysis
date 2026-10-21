"""Synthetic-only T11 codec, pin closure, export mounts and operation routing. No host calls."""
import ast
import base64
import copy
import gzip
import hashlib
import importlib.util
import json
import lzma
from pathlib import Path
import random
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


TOOLS = Path(__file__).resolve().parents[1] / 'tools'


def load():
    spec = importlib.util.spec_from_file_location('synthetic_detail_ai_transport',
        TOOLS / 'naver_report_defect_transport.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def fixture():
    t = load()
    sources = {name: 'x=1\n' for name in t.SOURCE_FILES}
    t.SOURCE_SHA256 = {name: hashlib.sha256(body.encode()).hexdigest() for name, body in sources.items()}
    t.COMPACT_SHA256 = dict(t.SOURCE_SHA256)
    t.COMPACT_SOURCE_SHA256 = t.COMPACT_SHA256
    t.TRANSPORT_RAW_SHA256 = hashlib.sha256(b'synthetic transport only').hexdigest()
    t.TARGET_SOURCE = t.EXPECTED_TARGET_SOURCE = 'b'*40
    t.CODE_PATHS = t.EXPECTED_CODE_PATHS
    return t, dict(version=1, operation='preview-report-defect-patch-prepare', package={}, sources=sources)


class TransportTests(unittest.TestCase):
    def test_unpopulated_transport_closes_every_entry_before_io_or_exec(self):
        t = load()
        t.SOURCE_SHA256 = t.COMPACT_SHA256 = None
        calls = (lambda: t.validate({}), lambda: t.encode({}), lambda: t.decode(t.PREFIX + 'unused'),
            lambda: t.bundle('preview-report-defect-patch-prepare', {}, Path('/unread')),
            lambda: t.modules({}), lambda: t.execute({}, incoming=True), lambda: t.execute({}))
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('read')) as read, \
             patch.object(t.lzma, 'LZMADecompressor', side_effect=AssertionError('decode')) as decompress, \
             patch('builtins.exec', side_effect=AssertionError('exec')) as execute:
            for call in calls:
                with self.assertRaisesRegex(ValueError, '^DETAIL_AI_PINS_PENDING$'):
                    call()
            read.assert_not_called()
            decompress.assert_not_called()
            execute.assert_not_called()

    def test_each_source_and_compact_pin_set_is_exact(self):
        for field in ('SOURCE_SHA256', 'COMPACT_SHA256'):
            for value in (None, {}, {'extra': 'a' * 64}):
                t, _ = fixture()
                setattr(t, field, value)
                with self.assertRaisesRegex(ValueError, '^DETAIL_AI_PINS_PENDING$'):
                    t.require_pins()
            for bad in (None, True, 'a' * 63, 'A' * 64, 'g' * 64):
                t, _ = fixture()
                getattr(t, field)['patch'] = bad
                with self.assertRaisesRegex(ValueError, '^DETAIL_AI_PINS_PENDING$'):
                    t.require_pins()

    def test_dedicated_three_operations_ten_sources_and_original_bounds(self):
        t, value = fixture()
        self.assertEqual(t.PREFIX, 'report-defect-patch-xz-v1:')
        self.assertEqual(set(t.FUNCTIONS), {'preview-report-defect-patch-' + name for name in ('prepare', 'apply', 'rollback')})
        self.assertEqual(len(t.SOURCE_FILES), 10)
        self.assertEqual(t.SOURCE_FILES['patch'], 'naver_report_defect_patch.py')
        self.assertEqual(t.SOURCE_FILES['controller'], 'naver_preview_completion_release.py')
        self.assertEqual((t.MAX_JSON, t.MAX_WIRE, t.MAX_SOURCE), (393216, 98304, 160000))
        self.assertEqual((t.MAX_SOURCE_GZIP, t.MAX_CIPHERTEXT, t.MAX_PAYLOAD), (3 * 1024 * 1024, 3 * 1024 * 1024, 4 * 1024 * 1024))
        for operation in t.FUNCTIONS:
            value['operation'] = operation
            self.assertEqual(t.decode(t.encode(value)), value)

    def test_utf8_json_fixed_filter_roundtrip_keeps_exact_source_hash_and_32mib_decoder_limit(self):
        t,value=fixture()
        body='x = "한글 자료 · 가설 🧪"\n'
        value['sources']['patch']=body
        t.SOURCE_SHA256['patch']=t.COMPACT_SHA256['patch']=hashlib.sha256(body.encode()).hexdigest()
        wire=t.encode(value)
        self.assertEqual(t.decode(wire),value)
        packed=base64.b64decode(wire[len(t.PREFIX):])
        reader=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=32*1024*1024)
        raw=reader.decompress(packed,max_length=t.MAX_JSON+1)
        self.assertTrue(reader.eof);self.assertEqual(reader.unused_data,b'')
        self.assertIn('한글'.encode(),raw)
        self.assertEqual(hashlib.sha256(t.decode(wire)['sources']['patch'].encode()).hexdigest(),t.COMPACT_SHA256['patch'])
        # A valid same-format header demanding 64MiB remains rejected by the unchanged limit.
        too_large=t.PREFIX+base64.b64encode(lzma.compress(raw,format=lzma.FORMAT_XZ,preset=9)).decode()
        with self.assertRaisesRegex(ValueError,'^PATCH_ENCODING$'):t.decode(too_large)

    def test_old_operations_extra_fields_bool_version_and_missing_source_refuse(self):
        t, value = fixture()
        for change in ({'operation': 'preview-budget-draft-patch-prepare'}, {'operation': 'preview-completion-prepare'},
                {'extra': True}, {'version': True}, {'version': 2}, {'package': []}, {'sources': {}}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, '^PATCH_BUNDLE$'):
                t.encode(dict(value, **change))
        for bad in ('tampered', '', True, 'x' * (t.MAX_SOURCE + 1)):
            changed = copy.deepcopy(value)
            changed['sources']['patch'] = bad
            with self.assertRaisesRegex(ValueError, '^PATCH_SOURCE$'):
                t.encode(changed)

    def test_truncated_trailing_concat_invalid_base64_and_legacy_wire_refuse(self):
        t, value = fixture()
        wire = t.encode(value)
        packed = base64.b64decode(wire[len(t.PREFIX):])
        cases = (wire[:-3], wire + 'aaaa', t.PREFIX + 'x' * (t.MAX_WIRE + 1), 'legacy:' + wire,
            t.PREFIX + base64.b64encode(packed + packed).decode(), t.PREFIX + 'not base64!')
        for changed in cases:
            with self.subTest(wire_length=len(changed)), self.assertRaisesRegex(ValueError, '^PATCH_ENCODING$'):
                t.decode(changed)

    def test_duplicate_fields_at_top_and_nested_package_are_closed(self):
        t, value = fixture()
        raw = json.dumps(value, separators=(',', ':'))
        for changed in (raw.replace('"version":1', '"version":1,"version":1'),
                raw.replace('"package":{}', '"package":{"x":1,"x":2}')):
            wire = t.PREFIX + base64.b64encode(lzma.compress(changed.encode())).decode()
            with self.assertRaisesRegex(ValueError, '^PATCH_ENCODING$'):
                t.decode(wire)

    def test_json_wire_and_decompression_pressure_bounds_are_unchanged(self):
        t, value = fixture()
        changed = copy.deepcopy(value)
        changed['package']['padding'] = 'a' * t.MAX_JSON
        with self.assertRaisesRegex(ValueError, '^PATCH_JSON_SIZE$'):
            t.encode(changed)
        changed['package']['padding'] = base64.b64encode(random.Random(17).randbytes(100000)).decode()
        with self.assertRaisesRegex(ValueError, '^PATCH_WIRE_SIZE$'):
            t.encode(changed)
        bomb = t.PREFIX + base64.b64encode(lzma.compress(b'x' * (t.MAX_JSON + 1))).decode()
        with self.assertRaisesRegex(ValueError, '^PATCH_ENCODING$'):
            t.decode(bomb)

    def test_compaction_preserves_ast_and_all_literal_tokens(self):
        t = load()
        source = ('x = "# preserve"\n# discard\ndef f(value):\n'
            '    """literal\n\n    indented text"""\n'
            '    return f"{value!r}:ok"\n')
        compact = t.compact(source)
        self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(compact)))
        self.assertIn('# preserve', compact)
        self.assertNotIn('# discard', compact)
        self.assertIn('indented text', compact)

    def test_bundle_reads_only_ten_exact_files_and_preserves_three_export_sources(self):
        t, _ = fixture()
        source = '# strip\nx = 1\n'
        original = {key: source for key in t.SOURCE_FILES}
        t.SOURCE_SHA256 = {key: hashlib.sha256(body.encode()).hexdigest() for key, body in original.items()}
        t.COMPACT_SHA256 = {key: hashlib.sha256((body if key in ('exports_helper', 'product_exporter', 'market_exporter') else t.compact(body)).encode()).hexdigest() for key, body in original.items()}
        t.COMPACT_SOURCE_SHA256 = t.COMPACT_SHA256
        p = SimpleNamespace(require_pins=Mock())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'tools'
            root.mkdir()
            for key, filename in t.SOURCE_FILES.items():
                (root / filename).write_text(original[key])
            with patch.dict(sys.modules, {'naver_report_defect_patch': p}):
                value = t.bundle('preview-report-defect-patch-prepare', {'synthetic': True}, root)
                p.require_pins.assert_called_once_with()
                self.assertEqual(len(value['sources']), 10)
                for key in ('exports_helper', 'product_exporter', 'market_exporter'):
                    self.assertEqual(value['sources'][key], source)
                self.assertNotIn('# strip', value['sources']['patch'])
                (root / t.SOURCE_FILES['patch']).write_text('changed\n')
                with self.assertRaisesRegex(ValueError, '^PATCH_SOURCE$'):
                    t.bundle('preview-report-defect-patch-prepare', {}, root)

    def module_fixture(self, fail_target=False):
        t, value = fixture()
        controller = 'def require_pins(): pass\n'
        base_sha = hashlib.sha256(controller.encode()).hexdigest()
        value['sources']['patch'] = ("BASE_CONTROLLER_SHA256=" + repr(base_sha) + "\n"
            "TARGET_COMMIT=" + repr(t.TARGET_SOURCE) + "\n"
            "CODE_PATHS=" + repr(t.CODE_PATHS) + "\n"
            "def require_target_pins():\n " + ("raise ValueError('DETAIL_AI_PINS_PENDING')" if fail_target else 'pass') + "\n"
            "def bind_base(base):\n global BASE\n BASE=base\n")
        value['sources']['controller'] = controller
        value['sources']['exports_binding'] = 'def require_pins(): pass\n'
        t.SOURCE_SHA256 = {key: hashlib.sha256(body.encode()).hexdigest() for key, body in value['sources'].items()}
        t.COMPACT_SHA256 = dict(t.SOURCE_SHA256)
        t.COMPACT_SOURCE_SHA256 = t.COMPACT_SHA256
        return t, value

    def test_module_loading_binds_original_controller_without_replacing_it(self):
        t, value = self.module_fixture()
        marker = object()
        original = sys.modules.get('naver_report_defect_patch', marker)
        modules = t.modules(value)
        self.assertIs(modules['patch'].BASE, modules['controller'])
        self.assertIsInstance(modules['release'], t.CompletionRelease)
        self.assertEqual(set(modules), {'patch', 'controller', 'host', 'release', 'lifecycle', 'upgrade', 'exports_binding', 'exports_helper'})
        self.assertIs(sys.modules.get('naver_report_defect_patch', marker), original)

    def test_pending_target_stops_before_host_module_execution(self):
        t, value = self.module_fixture(fail_target=True)
        value['sources']['host'] = "raise AssertionError('HOST_EXECUTED')\n"
        t.SOURCE_SHA256['host'] = t.COMPACT_SHA256['host'] = hashlib.sha256(value['sources']['host'].encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, '^DETAIL_AI_PINS_PENDING$'):
            t.modules(value)

    def test_controller_pin_mismatch_does_not_bind_base(self):
        t, value = self.module_fixture()
        value['sources']['patch'] = value['sources']['patch'].replace("BASE_CONTROLLER_SHA256=", "BASE_CONTROLLER_SHA256='" + '0' * 64 + "'\nIGNORED=")
        t.SOURCE_SHA256['patch'] = t.COMPACT_SHA256['patch'] = hashlib.sha256(value['sources']['patch'].encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, '^PATCH_BASELINE$'):
            t.modules(value)

    def test_patch_and_transport_target_path_guards_must_agree_before_host_exec(self):
        for field, changed in (('TARGET_COMMIT', '0'*40),
                               ('CODE_PATHS', ('naver_engine/other.py',))):
            t, value = self.module_fixture()
            value['sources']['patch'] += field+'='+repr(changed)+'\n'
            value['sources']['host'] = "raise AssertionError('HOST_EXECUTED')\n"
            for name in ('patch', 'host'):
                t.SOURCE_SHA256[name] = t.COMPACT_SHA256[name] = hashlib.sha256(value['sources'][name].encode()).hexdigest()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, '^PATCH_SCOPE$'):
                t.modules(value)

    def test_export_proxy_preserves_forward_inverse_engine_mounts_only(self):
        t, _ = fixture()
        p = SimpleNamespace(OLD_COMMIT='a' * 40, TARGET_COMMIT='b' * 40)
        helper = SimpleNamespace(COMPANION='saved.yml', _prepared=Mock(return_value=(None, Path('/synthetic/staging'), None)), verify=Mock(return_value=True))
        binding = SimpleNamespace(h=helper, receipt={'bound': True}, command=Mock(), operation=lambda callback: callback(), install=Mock(), rollback=Mock())
        release = SimpleNamespace(compose=lambda path, name: ['compose', str(path), name])
        proxy = t.ExportProxy(release, binding, p)
        for commit in (p.OLD_COMMIT, p.TARGET_COMMIT):
            self.assertEqual(proxy.compose(Path('/synthetic/naver-' + commit), 'engine')[-2:], ['-f', '/synthetic/staging/saved.yml'])
        for commit, role in ((p.TARGET_COMMIT, 'relay'), ('c' * 40, 'engine')):
            self.assertNotIn('-f', proxy.compose(Path('/synthetic/naver-' + commit), role))
        self.assertTrue(proxy.verify_exports())
        binding.install.assert_not_called()
        binding.rollback.assert_not_called()

    def execution_fixture(self):
        t, value = fixture()
        p = SimpleNamespace(OLD_COMMIT='a' * 40, TARGET_COMMIT='b' * 40, EXPECTED_BASELINE='c' * 64,
            APPROVED_CONFIG_OPERATION_ID='d' * 32, validate_package=Mock(), validate_rollback_package=Mock(),
            base_success=Mock(), historical_success=Mock(return_value=(None, {'package': {'historical': True}}, None)),
            prepare=Mock(return_value={'operation': 'prepare'}), apply=Mock(return_value={'operation': 'apply'}),
            rollback=Mock(return_value={'operation': 'rollback'}), failure_report=Mock(return_value={'stage': 'input', 'error_kind': 'ValueError', 'error_code': 'PATCH_OPERATION'}))
        binding = SimpleNamespace(load=Mock(), install=Mock(), rollback=Mock())
        release = SimpleNamespace(ROOT=Path('/synthetic/release'), trusted_dir=Mock())
        host = SimpleNamespace(baseline=Mock(return_value=p.EXPECTED_BASELINE))
        modules = dict(patch=p, release=release, host=SimpleNamespace(NativeHost=Mock(return_value=host)),
            controller=Mock(), exports_binding=SimpleNamespace(Binding=Mock(return_value=binding)),
            exports_helper=Mock(), lifecycle=Mock(), upgrade=Mock())
        return t, value, p, binding, release, host, modules

    def test_execute_routes_prepare_apply_and_inverse_without_export_install(self):
        for operation in ('prepare', 'apply', 'rollback'):
            t, value, p, binding, release, host, modules = self.execution_fixture()
            value['operation'] = 'preview-report-defect-patch-' + operation
            value['package'] = {'release': {'synthetic': True}, 'operation_id': 'e' * 32} if operation == 'apply' else {'synthetic': True}
            with patch.object(t, 'modules', return_value=modules):
                self.assertEqual(t.execute(value), {'operation': operation})
            selected = getattr(p, operation)
            self.assertEqual(selected.call_args.args[0], value['package'])
            self.assertIs(selected.call_args.args[1], host)
            self.assertIsInstance(selected.call_args.args[2], t.ExportProxy)
            self.assertEqual(selected.call_args.kwargs, {'approved_config_operation_id': p.APPROVED_CONFIG_OPERATION_ID} if operation == 'prepare' else {})
            binding.load.assert_called_once_with({'historical': True, 'operation': 'code-prepare'})
            binding.install.assert_not_called()
            binding.rollback.assert_not_called()

    def test_incoming_only_prepare_checks_package_root_and_exact_host_baseline(self):
        t, value, p, _, release, host, modules = self.execution_fixture()
        value['package'] = {'run_id': '12345678901'}
        with patch.object(t, 'modules', return_value=modules), patch.object(t.os, 'geteuid', return_value=0):
            self.assertEqual(t.execute(value, incoming=True)['stage'], 'incoming_ready')
        p.validate_package.assert_called_once_with(value['package'], release)
        self.assertEqual(release.trusted_dir.call_args_list[-1].args[0], release.ROOT / 'incoming' / '12345678901')
        self.assertEqual(release.trusted_dir.call_args_list[-1].kwargs, {'mode': 0o700, 'new': True})
        p.base_success.assert_not_called()
        for operation, uid, baseline, error in (('apply', 0, p.EXPECTED_BASELINE, 'PATCH_OPERATION'),
                ('prepare', 1000, p.EXPECTED_BASELINE, 'HOST_BASELINE'), ('prepare', 0, '0' * 64, 'HOST_BASELINE')):
            t, value, p, _, release, host, modules = self.execution_fixture()
            value['operation'] = 'preview-report-defect-patch-' + operation
            value['package'] = {'run_id': '12345678901'}
            host.baseline.return_value = baseline
            with patch.object(t, 'modules', return_value=modules), patch.object(t.os, 'geteuid', return_value=uid), self.assertRaisesRegex(ValueError, '^' + error + '$'):
                t.execute(value, incoming=True)
            release.trusted_dir.assert_not_called()

    def test_apply_extra_fields_fail_before_historical_reads_or_operation(self):
        t, value, p, _, _, _, modules = self.execution_fixture()
        value['operation'] = 'preview-report-defect-patch-apply'
        value['package'] = {'release': {}, 'operation_id': 'e' * 32, 'extra': True}
        with patch.object(t, 'modules', return_value=modules), self.assertRaisesRegex(ValueError, '^CODE_APPLY_FIELDS$'):
            t.execute(value)
        p.base_success.assert_not_called()
        p.apply.assert_not_called()

    def test_failure_projection_keeps_original_primary_failure_across_wrapper(self):
        t, value, p, binding, _, _, modules = self.execution_fixture()
        value['operation'] = 'preview-report-defect-patch-apply'
        value['package'] = {'release': {}, 'operation_id': 'e' * 32}
        error = RuntimeError('synthetic private exception text')
        error.failure_details = {'failed_stage': 'code_start', 'failed_error_code': 'RUNTIME_CONFIG_DRIFT'}
        p.failure_report.return_value = {'stage': 'code_rollback', 'error_kind': 'RuntimeError', 'error_code': 'UNRECOGNIZED',
            'failed_stage': 'code_start', 'failed_error_code': 'RUNTIME_CONFIG_DRIFT'}
        p.apply.side_effect = error
        with patch.object(t, 'modules', return_value=modules), self.assertRaises(RuntimeError) as caught:
            t.execute(value)
        self.assertIs(caught.exception, error)
        self.assertEqual(error.failure_details['failed_stage'], 'code_start')
        self.assertEqual(error.failure_details['failed_error_code'], 'RUNTIME_CONFIG_DRIFT')
        self.assertNotIn('synthetic private', json.dumps(error.failure_details))
        binding.install.assert_not_called()
        binding.rollback.assert_not_called()

    def test_payload_gzip_trailing_pressure_and_duplicate_json_are_closed(self):
        t, _ = fixture()
        release = SimpleNamespace(unique=t.unique)
        proxy = t.CompletionRelease(release)
        magic = b'NAVER-PREVIEW-PAYLOAD-GZIP-1\n'
        for plain, code in ((b'', 'PLAINTEXT_SIZE'), (b'x' * (t.MAX_PAYLOAD + 1), 'PLAINTEXT_SIZE'),
                (magic + gzip.compress(b'x' * (t.MAX_PAYLOAD + 1)), 'PAYLOAD_COMPRESSION'),
                (magic + gzip.compress(b'{}') + b'trailing', 'PAYLOAD_COMPRESSION'),
                (b'{"schema":1,"schema":1}', 'PAYLOAD_JSON')):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, '^' + code + '$'):
                proxy.decode_payload(plain, 'a' * 40, 'b' * 64)

    def test_exact_nine_dependencies_are_preserved_while_new_maps_remain_pending(self):
        for configured in (False,True):
            t=fixture()[0] if configured else load()
            if configured:t.require_pins()
            self.assertEqual({key:value for key,value in t.SOURCE_FILES.items() if key!='patch'},{
                'controller':'naver_preview_completion_release.py','host':'naver_erp_tunnel_service_install.py',
                'release':'naver_preview_release.py','lifecycle':'naver_preview_lifecycle.py',
                'upgrade':'naver_preview_upgrade.py','exports_binding':'naver_completion_exports.py',
                'exports_helper':'naver_saved_exports.py','product_exporter':'../naver_product_export.py',
                'market_exporter':'../naver_market_export.py'})
            for field in ('SOURCE_SHA256','COMPACT_SHA256','COMPACT_SOURCE_SHA256','TRANSPORT_RAW_SHA256'):
                with patch.object(t,field,None),self.subTest(configured=configured,field=field),self.assertRaisesRegex(ValueError,'^DETAIL_AI_PINS_PENDING$'):
                    t.require_pins()
            with patch.multiple(t,TARGET_SOURCE=None,EXPECTED_TARGET_SOURCE=None),patch.object(Path,'read_bytes',side_effect=AssertionError('read')) as read,patch('builtins.exec',side_effect=AssertionError('exec')) as execute,patch.object(t.lzma,'LZMADecompressor',side_effect=AssertionError('decode')) as decompress:
                self.assertIsNone(t.TARGET_SOURCE)
                self.assertEqual(t.TARGET_SOURCE,t.EXPECTED_TARGET_SOURCE)
                self.assertEqual(set(t.CODE_PATHS),set(t.EXPECTED_CODE_PATHS));self.assertEqual(len(t.CODE_PATHS),5)
                for call in (t.require_pins,lambda:t.validate({}),lambda:t.encode({}),lambda:t.decode(t.PREFIX+'unused'),lambda:t.bundle('preview-report-defect-patch-prepare',{},Path('/unread')),lambda:t.modules({}),lambda:t.execute({}),lambda:t.bootstrap(b'unread')):
                    with self.assertRaisesRegex(ValueError,'^DETAIL_AI_PINS_PENDING$'):call()
                read.assert_not_called();execute.assert_not_called();decompress.assert_not_called()


    def test_missing_each_pin_slot_closes_before_caller_access_or_io(self):
        class Unreadable:
            def __getattribute__(self, name):
                raise AssertionError('caller accessed')
        for field in ('SOURCE_SHA256', 'COMPACT_SHA256', 'COMPACT_SOURCE_SHA256',
                      'TRANSPORT_RAW_SHA256', 'TARGET_SOURCE', 'CODE_PATHS'):
            t, _ = fixture()
            setattr(t, field, None)
            calls = (lambda: t.validate(Unreadable()), lambda: t.encode(Unreadable()),
                     lambda: t.decode(Unreadable()), lambda: t.bundle(Unreadable(), package=Unreadable(), root=Unreadable()),
                     lambda: t.modules(Unreadable(), host=Unreadable()), lambda: t.bootstrap(Unreadable()),
                     lambda: t.execute(Unreadable()), lambda: t.main())
            with patch('builtins.open', side_effect=AssertionError('open')) as opened, \
                 patch.object(Path, 'read_bytes', side_effect=AssertionError('read')) as read, \
                 patch.object(t.lzma, 'LZMADecompressor', side_effect=AssertionError('decode')) as decompress, \
                 patch('builtins.exec', side_effect=AssertionError('exec')) as execute:
                for call in calls:
                    with self.subTest(field=field), self.assertRaisesRegex(ValueError, '^DETAIL_AI_PINS_PENDING$'):
                        call()
                for guarded in (opened, read, decompress, execute):
                    guarded.assert_not_called()

    def test_compatibility_aliases_exact_target_paths_and_raw_hash_are_guarded(self):
        t, _ = fixture()
        self.assertEqual((t.MAX_JSON_BYTES, t.MAX_WIRE_BYTES, t.MAX_SOURCE_BYTES), (393216, 98304, 160000))
        self.assertEqual((t.MAX_SOURCE_GZIP_BYTES, t.MAX_CIPHERTEXT_BYTES, t.MAX_PAYLOAD_BYTES),
                         (3*1024*1024, 3*1024*1024, 4*1024*1024))
        self.assertEqual((t.MAX_BOOTSTRAP_B64_BYTES, t.MAX_SSH_BYTES), (32768, 131072))
        for field, bad in (
            ('TRANSPORT_RAW_SHA256', True), ('TRANSPORT_RAW_SHA256', 'A'*64),
            ('TARGET_SOURCE', 'a'*40), ('CODE_PATHS', list(t.EXPECTED_CODE_PATHS)),
            ('CODE_PATHS', t.EXPECTED_CODE_PATHS[:-1]),
            ('CODE_PATHS', t.EXPECTED_CODE_PATHS+(t.EXPECTED_CODE_PATHS[0],)),
            ('CODE_PATHS', t.EXPECTED_CODE_PATHS[:-1]+('naver_engine/other.py',)),
            ('COMPACT_SOURCE_SHA256', dict(t.COMPACT_SHA256, patch='0'*64)),
        ):
            changed, _ = fixture()
            setattr(changed, field, bad)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, '^DETAIL_AI_PINS_PENDING$'):
                changed.require_pins()

    def test_every_source_hash_is_verified_before_any_module_exec(self):
        for key in load().SOURCE_FILES:
            t, value = fixture()
            value['sources'][key] = 'tampered=1\n'
            with self.subTest(key=key), patch('builtins.exec', side_effect=AssertionError('exec')) as execute, \
                 patch.object(Path, 'read_bytes', side_effect=AssertionError('private read')) as read:
                with self.assertRaisesRegex(ValueError, '^PATCH_SOURCE$'):
                    t.modules(value)
                execute.assert_not_called()
                read.assert_not_called()

    def test_bundle_target_pins_precede_all_source_reads(self):
        t, _ = fixture()
        p = SimpleNamespace(require_pins=Mock(side_effect=ValueError('DETAIL_AI_PINS_PENDING')))
        with patch.dict(sys.modules, {'naver_report_defect_patch': p}), \
             patch.object(Path, 'read_bytes', side_effect=AssertionError('read')) as read:
            with self.assertRaisesRegex(ValueError, '^DETAIL_AI_PINS_PENDING$'):
                t.bundle('preview-report-defect-patch-prepare', {}, Path('/synthetic/unread'))
            p.require_pins.assert_called_once_with()
            read.assert_not_called()

    def test_bootstrap_is_pure_pinned_base64_and_caps_are_exact(self):
        t, _ = fixture()
        source = b'synthetic transport only'
        with patch('builtins.open', side_effect=AssertionError('open')) as opened, \
             patch('builtins.exec', side_effect=AssertionError('exec')) as executed:
            self.assertEqual(base64.b64decode(t.bootstrap(source), validate=True), source)
            with self.assertRaisesRegex(ValueError, '^PATCH_SOURCE$'):
                t.bootstrap(source+b'changed')
            with self.assertRaisesRegex(ValueError, '^PATCH_SOURCE$'):
                t.bootstrap('text')
            opened.assert_not_called()
            executed.assert_not_called()
        for length, code in ((24576, None), (24577, 'PATCH_BOOTSTRAP_SIZE'), (160001, 'PATCH_SOURCE')):
            source = b'x'*length
            t.TRANSPORT_RAW_SHA256 = hashlib.sha256(source).hexdigest()
            if code is None:
                self.assertEqual(len(t.bootstrap(source)), 32768)
            else:
                with self.subTest(length=length), self.assertRaisesRegex(ValueError, '^'+code+'$'):
                    t.bootstrap(source)

    def test_compaction_rejects_ast_or_literal_change(self):
        t = load()
        for original, changed in (("x='literal'\n", "x='changed'\n"), ('x=1\n', 'x=2\n')):
            with patch.object(t.tokenize, 'untokenize', return_value=changed), \
                 self.assertRaisesRegex(ValueError, '^COMPLETION_SOURCE_AST$'):
                t.compact(original)

    def test_private_cipher_envelope_metadata_is_closed_without_real_file_io(self):
        t, _ = fixture()
        body = b'synthetic cipher only'
        release = SimpleNamespace(sha=lambda value: hashlib.sha256(value).hexdigest())
        proxy = t.CompletionRelease(release)
        def fake_path(**changes):
            metadata = dict(st_mode=0o100600, st_uid=0, st_gid=0, st_nlink=1, st_size=len(body))
            metadata.update(changes)
            return SimpleNamespace(lstat=Mock(return_value=SimpleNamespace(**metadata)), read_bytes=Mock(return_value=body))
        digest = hashlib.sha256(body).hexdigest()
        path = fake_path()
        with patch.object(t.os, 'chown') as chown:
            self.assertEqual(proxy.received_ciphertext(path, digest), body)
            chown.assert_not_called()
        path = fake_path(st_uid=1000, st_gid=1000)
        with patch.object(t.os, 'chown') as chown:
            self.assertEqual(proxy.received_ciphertext(path, digest), body)
            chown.assert_called_once_with(path, 0, 0)
        for change in ({'st_mode':0o120600}, {'st_mode':0o100644}, {'st_nlink':2}, {'st_size':0},
                       {'st_size':t.MAX_CIPHERTEXT+1}, {'st_uid':501}, {'st_gid':1000}):
            path = fake_path(**change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, '^CIPHERTEXT_FILE$'):
                proxy.received_ciphertext(path, digest)
            path.read_bytes.assert_not_called()
        path = fake_path()
        with self.assertRaisesRegex(ValueError, '^CIPHERTEXT_HASH$'):
            proxy.received_ciphertext(path, '0'*64)

    def test_private_helpers_and_export_proxy_also_refuse_missing_pins(self):
        t = load()
        class Unreadable:
            def __getattribute__(self, name):
                raise AssertionError('private object accessed')
        proxy = t.CompletionRelease(Unreadable())
        exports = t.ExportProxy(Unreadable(), Unreadable(), Unreadable())
        for call in (lambda: proxy.received_ciphertext(Unreadable(), Unreadable()),
                     lambda: proxy.decode_payload(Unreadable(), Unreadable(), Unreadable()),
                     lambda: proxy.validate_payload(Unreadable(), Unreadable(), Unreadable()),
                     lambda: exports.compose(Unreadable(), Unreadable()), lambda: exports.verify_exports()):
            with self.assertRaisesRegex(ValueError, '^DETAIL_AI_PINS_PENDING$'):
                call()

    def test_payload_roundtrip_is_in_memory_and_source_gzip_bound_is_preserved(self):
        t, _ = fixture()
        source = b'synthetic gzip archive only'
        owners = {name:(0,0) for name in ('one', 'two', 'three', 'four')}
        release = SimpleNamespace(unique=t.unique, sha=lambda value: hashlib.sha256(value).hexdigest(),
                                  SECRET_OWNERS=owners, SECRET_ROOT=Path('/synthetic/private'))
        proxy = t.CompletionRelease(release)
        payload = dict(schema=1, purpose='naver-owner-verification-runtime', source_commit='a'*40,
                       source_tar_gz_b64=base64.b64encode(source).decode(),
                       files=[dict(path=str(release.SECRET_ROOT/name), mode=0o600, uid=0, gid=0,
                                   content='synthetic only') for name in owners])
        digest = hashlib.sha256(source).hexdigest()
        for plain in (json.dumps(payload).encode(), b'NAVER-PREVIEW-PAYLOAD-GZIP-1\n'+gzip.compress(json.dumps(payload).encode())):
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('private read')) as read:
                self.assertEqual(proxy.decode_payload(plain, 'a'*40, digest), (source, payload['files']))
                read.assert_not_called()
        for length in (0, t.MAX_SOURCE_GZIP):
            changed = dict(payload, source_tar_gz_b64=base64.b64encode(b'x'*length).decode())
            with self.assertRaisesRegex(ValueError, '^PAYLOAD_HASH$'):
                proxy.validate_payload(changed, 'a'*40, hashlib.sha256(b'x'*length).hexdigest())


if __name__ == '__main__':
    unittest.main()
