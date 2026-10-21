"""V25 exact async profile and preservation of the committed V24 config chain."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import test_naver_preview_code_upgrade as shared
import test_naver_preview_code_upgrade_v24 as previous
import test_naver_preview_code_upgrade_v23 as probe_base

MODULE = 'naver_preview_code_upgrade_v25'
TOOLS = Path(__file__).parents[1] / 'tools'
encoded, sha = previous.encoded, previous.sha


def historical_transport_functions(workflow):
    """Compare both complete codec ASTs except the exact appended read-only route."""
    import re, textwrap
    route = 'preview-conversion-recovery-v26'
    selectors = {
        ast.dump(ast.parse("bundle['operation']", mode='eval').body): (ast.NotIn, route),
        ast.dump(ast.parse("bundle.get('operation')", mode='eval').body): (ast.In, route),
        ast.dump(ast.parse("(bundle.get('operation'),bundle.get('function'))", mode='eval').body):
            (ast.NotIn, (route, 'run')),
    }

    class ExactRouteOnly(ast.NodeTransformer):
        def visit_Compare(self, node):
            self.generic_visit(node)
            allowed = selectors.get(ast.dump(node.left))
            if (allowed is None or len(node.ops) != 1 or type(node.ops[0]) is not allowed[0]
                    or len(node.comparators) != 1 or not isinstance(node.comparators[0], ast.Tuple)):
                return node
            entries = node.comparators[0].elts
            expected = ast.parse(repr(allowed[1]), mode='eval').body
            matches = [index for index, entry in enumerate(entries) if ast.dump(entry) == ast.dump(expected)]
            # Only one appended opcode (or exact opcode/run pair), never other constants or contexts.
            if matches == [len(entries)-1] and len(entries) > 1:
                node.comparators[0].elts = entries[:-1]
            return node

    found = {}
    for body in re.findall(r"python3(?: -I -B)? - <<'PY'\n(.*?)\n\s*PY", workflow, re.S):
        for node in ast.parse(textwrap.dedent(body)).body:
            if isinstance(node, ast.FunctionDef) and node.name in ('encode_ops', 'decode_ops'):
                if node.name in found:
                    raise AssertionError('duplicate historical codec definition')
                found[node.name] = ast.dump(ExactRouteOnly().visit(node), include_attributes=False)
    if set(found) != {'encode_ops', 'decode_ops'}:
        raise AssertionError('both historical codec ASTs are required')
    return found


def pin_synthetic(code):
    code.TARGET_COMMIT = 'f' * 40
    code.TARGET_SOURCE_SHA256 = 'e' * 64
    code.STORE_SHA256 = {**code.STORE_SHA256, 'target': 'd' * 64}
    code.REPORT_ASSETS = {**code.REPORT_ASSETS, '/naver/report-ui.js': (999, 'c' * 64, 'text/javascript; charset=utf-8')}


class ConfigFixture(previous.ConfigFixture):
    def __init__(self, root):
        with patch.object(previous, 'MODULE', MODULE):
            super().__init__(root)
        pin_synthetic(self.code)
        self.bridge_file = root / 'receipts' / ('preview-' + self.code.CONFIG_PREDECESSOR_COMMIT + '.json')
        self.start_file = self.bridge_file.with_name('preview-start-' + self.code.CONFIG_PREDECESSOR_COMMIT + '.json')
        self.active = dict(ok=True, stage='prepared', source_commit=self.code.CONFIG_PREDECESSOR_COMMIT,
            images={'engine': 'sha256:' + 'c' * 64, 'relay': 'sha256:' + 'd' * 64},
            files={str(self.paths[0]): sha(self.new[0])}, runtime_environment_preserved=True,
            config_operation_id=self.code.APPROVED_CONFIG_OPERATION_ID,
            package=dict(source_commit=self.code.CONFIG_PREDECESSOR_COMMIT, source_tar_gz_sha256=self.code.CONFIG_PREDECESSOR_ARCHIVE,
                         baseline=self.code.EXPECTED_BASELINE, run_id=self.code.CONFIG_PREDECESSOR_PREPARE_RUN))
        self.started = dict(ok=True, stage='internal_ready', source_commit=self.code.CONFIG_PREDECESSOR_COMMIT,
            previous_commit=self.code.CONFIG_SOURCE_COMMIT, database_policy='preserve-in-place', database_opened_by_controller=False)
        self.sync_bridge()
        def manifest(release, source, *args, **kwargs):
            if source == self.code.CONFIG_SOURCE_COMMIT:
                return root / 'historic-source', json.loads(self.new[1])
            if source == self.code.CONFIG_ROLLBACK_COMMIT:
                return root / 'historic-rollback', json.loads(self.new[2])
            if source == self.code.CONFIG_PREDECESSOR_COMMIT:
                return root / 'predecessor', self.active
            return root / 'target', {}
        self.upgrade.manifest.side_effect = manifest

    def sync_bridge(self):
        self.bridge_file.parent.mkdir(parents=True, exist_ok=True)
        self.bridge_file.write_bytes(encoded(self.active)); self.start_file.write_bytes(encoded(self.started))


class V25ConfigPreserveTest(previous.V24ConfigPreserveTest):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.fixture = ConfigFixture(Path(temp.name).resolve())

    def test_exact_committed_proof_preserves_current_bytes_and_original_payload(self):
        f = self.fixture; original = deepcopy(f.files)
        paths = f.paths + [f.bridge_file, f.start_file]
        before = {path: path.read_bytes() for path in paths}
        resolved, proof = f.resolve()
        self.assertEqual(f.files, original); self.assertEqual(resolved[0]['content'].encode(), f.new[0])
        self.assertEqual(resolved[1:], f.files[1:]); self.assertEqual(len(proof), 5)
        self.assertEqual(before, {path: path.read_bytes() for path in paths})
        f.release.write_new.assert_not_called(); f.release.command.assert_not_called()
        self.assertEqual(f.upgrade.manifest.call_count, 4)
        self.assertNotEqual(f.active['images'], f.journal['images'])

    def test_bridge_must_be_exact_v24_preserved_prepare_and_started_source(self):
        for key, value in (('runtime_environment_preserved', False), ('config_operation_id', 'f' * 32), ('source_commit', 'e' * 40)):
            f = self.fixture; old = f.active[key]; f.active[key] = value; f.sync_bridge()
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_PROOF'): f.resolve()
            f.active[key] = old; f.sync_bridge()
        for key, value in (('run_id', '12345678901'), ('baseline', 'e' * 64), ('source_tar_gz_sha256', 'f' * 64), ('source_commit', 'e' * 40)):
            f = self.fixture; old = f.active['package'][key]; f.active['package'][key] = value; f.sync_bridge()
            with self.subTest(package_key=key), self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_PROOF'): f.resolve()
            f.active['package'][key] = old; f.sync_bridge()

    def test_bridge_and_current_state_cannot_disagree(self):
        f = self.fixture; body = json.loads(f.bridge_file.read_bytes()); body['images']['engine'] = 'sha256:' + 'f' * 64
        f.bridge_file.write_bytes(encoded(body))
        with self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_PROOF'): f.resolve()

    def test_bridge_environment_digest_must_equal_committed_new_environment(self):
        f = self.fixture; f.active['files'][str(f.paths[0])] = sha(f.old[0]); f.sync_bridge()
        with self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_PROOF'): f.resolve()

    def test_bridge_started_receipt_cannot_point_to_another_predecessor_or_database_policy(self):
        f = self.fixture
        for key, value in (('previous_commit', 'f' * 40), ('database_policy', 'restore'), ('database_opened_by_controller', True), ('ok', False)):
            old = f.started[key]; f.started[key] = value; f.sync_bridge()
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_PROOF'): f.resolve()
            f.started[key] = old; f.sync_bridge()

    def test_bridge_private_proof_is_included_in_postflight_identity(self):
        f = self.fixture; _, before = f.resolve()
        f.started['operation_id'] = 'e' * 32; f.sync_bridge(); _, after = f.resolve()
        self.assertNotEqual(before, after)


class V25PrepareTest(previous.V24PrepareTest):
    def setUp(self):
        with patch.object(previous, 'ConfigFixture', ConfigFixture):
            super().setUp()

    def test_v24_bridge_drift_during_build_refuses_without_writing_current_files(self):
        f = self.fixture; current = {path: path.read_bytes() for path in f.paths}
        def mutate():
            f.started['operation_id'] = 'd' * 32; f.sync_bridge()
        self.mutate = mutate
        with self.assertRaisesRegex(ValueError, 'CONFIG_PRESERVE_DRIFT'): self.prepare()
        self.assertEqual(current, {path: path.read_bytes() for path in f.paths})
        self.assertFalse((f.release.ROOT / 'receipts' / ('preview-' + f.code.TARGET_COMMIT + '.json')).exists())


class V25ScopeTest(previous.V24ScopeTest):
    def setUp(self):
        original_load = shared.load
        def load(name):
            code = original_load(name)
            if name == MODULE: pin_synthetic(code)
            return code
        with patch.object(previous, 'MODULE', MODULE), patch.object(shared, 'load', side_effect=load):
            super().setUp()
        self.code.TARGET_COMMIT = 'f' * 40
        for name in ('engine','relay'):
            (self.new / ('preview-' + name + '.override.yml')).write_bytes(('image: ' + self.code.TARGET_COMMIT).encode())
        (self.old / 'naver_runtime/learning_jobs.py').unlink()

    def test_four_existing_paths_and_unchanged_store_work_forward_and_inverse(self):
        self.code.compatible_source(self.old, self.new, self.adapter)
        self.code.compatible_inverse_source(self.new, self.old, self.adapter)
        self.assertEqual(len(self.code.CODE_PATHS), 7)
        self.assertEqual(self.code.ADDED_SOURCE_PATHS, frozenset({'naver_runtime/learning_jobs.py'}))

    def test_worker_is_required_forward_and_is_the_only_reverse_removal(self):
        worker = self.new / 'naver_runtime/learning_jobs.py'; body = worker.read_bytes(); worker.unlink()
        with self.assertRaisesRegex(ValueError, 'CODE_SCOPE_CHANGED'): self.code.compatible_source(self.old,self.new,self.adapter)
        worker.write_bytes(body); (self.old / 'naver_runtime/rogue.py').write_bytes(b'rogue')
        with self.assertRaisesRegex(ValueError, 'CODE_SOURCE_REMOVED'): self.code.compatible_source(self.old,self.new,self.adapter)

    def test_schema_change_still_refused_even_when_store_path_is_in_scope(self):
        store = self.new / 'naver_engine/store.py'; before = store.read_bytes()
        node = next(n for n in ast.parse(before).body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SCHEMA_VERSION' for t in n.targets))
        lines = before.splitlines(keepends=True); lines[node.lineno-1:node.end_lineno] = [b'SCHEMA_VERSION = 12\n']; after = b''.join(lines)
        self.assertNotEqual(before, after)
        store.write_bytes(after); self.code.STORE_SHA256['target'] = sha(after)
        with self.assertRaisesRegex(ValueError, 'CODE_SCHEMA_CHANGED'): self.code.compatible_source(self.old,self.new,self.adapter)


class V25ProfileTest(unittest.TestCase):
    def test_pending_pins_fail_before_host_or_provider_actions(self):
        for name in ('TARGET_COMMIT', 'TARGET_SOURCE_SHA256', 'STORE_SHA256'):
            code = shared.load(MODULE); policy = shared.load('naver_preview_code_only'); adapters = [Mock() for _ in range(4)]
            if name == 'STORE_SHA256': code.STORE_SHA256['target'] = None
            else: setattr(code, name, None)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'CODE_ONLY_RELEASE_NOT_REVIEWED'):
                policy.prepare({}, *adapters, code, approved_config_operation_id=code.APPROVED_CONFIG_OPERATION_ID)
            self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_all_previous_profiles_are_still_reviewed(self):
        policy = shared.load('naver_preview_code_only'); rollback = shared.load('naver_preview_code_rollback')
        for version in range(5,25):
            code = shared.load('naver_preview_code_upgrade_v' + str(version)); policy.require_review(code); rollback.require_review(policy,code)

    def test_exact_reviewed_v25_config_option_and_scope_dispatch(self):
        code = shared.load(MODULE); pin_synthetic(code); policy = shared.load('naver_preview_code_only')
        policy.REVIEWED_TRANSITION_V25 = previous.pins(code); policy.REVIEWED_ASSETS_V25 = code.REPORT_ASSETS
        policy.require_review(code); self.assertEqual(policy.code_module_name(code.TARGET_COMMIT), MODULE)
        adapters=[Mock() for _ in range(4)]; code.prepare=Mock(return_value={'ok':True})
        result=policy.prepare({},*adapters,code,approved_config_operation_id=code.APPROVED_CONFIG_OPERATION_ID)
        self.assertTrue(result['ok']); code.prepare.assert_called_once()
        for name,value in (('CONFIG_PREDECESSOR_PREPARE_RUN','12345678901'),('ADDED_SOURCE_PATHS',frozenset()),('CONFIG_SETTINGS',{})):
            old=getattr(code,name);setattr(code,name,value)
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'CODE_ONLY_RELEASE_NOT_REVIEWED'):policy.require_review(code)
            setattr(code,name,old)
        with self.assertRaisesRegex(ValueError,'CONFIG_PRESERVE_NOT_APPROVED'):
            policy.prepare({},*adapters,code,approved_config_operation_id='f'*32)

    def test_source_config_and_model_values_remain_unchanged(self):
        code=shared.load(MODULE);prior=shared.load('naver_preview_code_upgrade_v24')
        self.assertEqual(code.OLD_COMMIT,prior.TARGET_COMMIT);self.assertEqual(code.OLD_SOURCE_SHA256,prior.TARGET_SOURCE_SHA256)
        self.assertEqual(code.CONFIG_SETTINGS,prior.CONFIG_SETTINGS);self.assertEqual(code.CONFIG_SETTINGS['NAVER_CLAUDE_MONTHLY_CAP_USD'],'unlimited')
        self.assertEqual(code.OLD_REPORT_ASSETS,prior.REPORT_ASSETS)
        self.assertEqual(code.STORE_SHA256['old'],prior.STORE_SHA256['target'])


class V25FrozenTest(unittest.TestCase):
    def test_whole_previous_controller_ast_remains_exact_after_reviewed_v25_additions(self):
        from test_naver_preview_loading_v8_preservation import strip_v25_additions, canonical
        for name in ('naver_preview_code_only', 'naver_preview_code_rollback'):
            base = subprocess.check_output(['git', 'show', '5b5db11192980485919bb2b3c8484f0f62df9e0a:backend/tools/' + name + '.py'], cwd=TOOLS)
            current = ast.parse((TOOLS / (name + '.py')).read_bytes())
            self.assertEqual(canonical(ast.parse(base)), canonical(strip_v25_additions(current)), name)

    def test_v25_selector_scope_inverse_and_config_guard_mutations_do_not_normalize(self):
        import test_naver_preview_loading_v8_preservation as frozen
        original = frozen.tree
        for mutation in ('selector', 'scope', 'guard', 'inverse', 'config_option'):
            changed = False
            def altered(name):
                nonlocal changed
                value = original(name)
                target = 'naver_preview_code_rollback' if mutation == 'inverse' else 'naver_preview_code_only'
                if name != target:
                    return value
                for node in ast.walk(value):
                    if mutation == 'selector' and isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and node.value.value == MODULE:
                        node.value.value = 'naver_preview_code_upgrade_v24'; changed = True; break
                    if isinstance(node, ast.If) and ast.unparse(node.test).startswith('transition == REVIEWED_TRANSITION_V25'):
                        if mutation == 'scope':
                            node.body[0].value.elts.append(ast.Constant(value='naver_runtime/scheduler.py')); changed = True; break
                        if mutation == 'guard':
                            node.body[-1] = ast.Pass(); changed = True; break
                    if mutation == 'inverse' and isinstance(node, ast.If) and ast.unparse(node.test) == 'transition(code) == REVIEWED_ROLLBACK_V25':
                        node.body = [ast.Pass()]; changed = True; break
                    if mutation == 'config_option' and isinstance(node, ast.If) and 'approved_config_operation_id is not None' in ast.unparse(node.test) and 'REVIEWED_TRANSITION_V25' in ast.unparse(node.test):
                        node.body = [ast.Pass()]; changed = True; break
                return value
            with self.subTest(mutation=mutation), patch.object(frozen, 'tree', side_effect=altered):
                with self.assertRaises(AssertionError):
                    frozen.V8PreservationTest().test_shared_business_functions_are_unchanged_after_exact_passive_metadata_delta()
            self.assertTrue(changed)

    def test_v25_copied_database_and_warm_helpers_are_absent(self):
        code = shared.load(MODULE)
        for name in ('db_snapshot', 'restore_db', 'warm_sources', 'verify_database_schema', 'database_contract', 'WARM_SCRIPT', 'MONITORING_SQL'):
            self.assertFalse(hasattr(code, name), name)
        tree = ast.parse((TOOLS / (MODULE + '.py')).read_text())
        self.assertFalse(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                             and isinstance(node.func.value, ast.Name) and node.func.value.id == 'sqlite3'
                             and node.func.attr == 'connect' for node in ast.walk(tree)))


class V25TransportTest(unittest.TestCase):
    def compactor(self):
        import re, textwrap
        workflow = (TOOLS.parents[1] / '.github/workflows/debug-rank.yml').read_text()
        scripts = [textwrap.dedent(body) for body in re.findall(r"python3 - <<'PY'\n(.*?)\n\s*PY", workflow, re.S)]
        functions = []
        for script in scripts:
            nodes = [node for node in ast.parse(script).body if isinstance(node, ast.FunctionDef) and node.name == 'compact_sources']
            functions.extend(nodes)
        self.assertEqual(len(functions), 2)
        from test_naver_preview_loading_v8_preservation import canonical
        self.assertEqual(canonical(functions[0]), canonical(functions[1]))
        namespace = {}
        exec(compile(ast.Module(body=ast.parse('import ast,io,tokenize').body + [functions[0]], type_ignores=[]), '<workflow-compactor>', 'exec'), namespace)
        return namespace['compact_sources']

    def bundles(self, version):
        code = shared.load('naver_preview_code_upgrade_v' + str(version))
        source = lambda name: (TOOLS / (name + '.py')).read_text()
        package = dict(baseline=code.EXPECTED_BASELINE, source_commit=code.TARGET_COMMIT,
            source_tar_gz_sha256=code.TARGET_SOURCE_SHA256, ciphertext_sha256='c' * 64, run_id='12345678901', operation='code-prepare')
        common = dict(host_source=source('naver_erp_tunnel_service_install'), upgrade_source=source('naver_preview_upgrade'),
                      lifecycle_source=source('naver_preview_lifecycle'), code_source=source('naver_preview_code_upgrade_v' + str(version)))
        return {
            'prepare': dict(common, package=package, source=source('naver_preview_release'), operation='preview-code-only-prepare',
                code_only_source=source('naver_preview_code_only'), approved_config_operation_id=getattr(code, 'APPROVED_CONFIG_OPERATION_ID', '74c912dddf824fae99012849bc4c19a5')),
            'forward': dict(common, package=dict(release=package, operation_id='9' * 32), source=source('naver_preview_code_only'),
                release_source=source('naver_preview_release'), operation='preview-code-only-upgrade', function='apply'),
            'reverse': dict(common, package=dict(release=package, operation_id='8' * 32, apply_operation_id='9' * 32),
                source=source('naver_preview_code_rollback'), code_only_source=source('naver_preview_code_only'),
                release_source=source('naver_preview_release'), operation='preview-code-only-rollback', function='run')}

    def test_source_comments_and_blank_lines_inside_strings_are_preserved(self):
        compact = self.compactor()
        source = '# outside\nx = """# in string\n\n  keep spacing\n"""\n\nvalue = "# literal" # outside\n'
        bundle = dict(source=source, code_source=source, package={'exact': '# payload'}, operation='preview-code-only-upgrade')
        before = deepcopy(bundle); result = compact(bundle)
        self.assertEqual(bundle, before); self.assertEqual(result['package'], before['package'])
        self.assertIn('# in string\n\n  keep spacing', result['source']); self.assertNotIn('# outside', result['source'])
        self.assertEqual(ast.dump(ast.parse(result['source']), include_attributes=False), ast.dump(ast.parse(source), include_attributes=False))

    def test_any_ast_change_is_refused_before_transport(self):
        compact = self.compactor(); real = ast.parse; count = 0
        def changed(source, *args, **kwargs):
            nonlocal count
            count += 1
            return real('x = 2' if count % 2 == 0 else source, *args, **kwargs)
        with patch.object(ast, 'parse', side_effect=changed), self.assertRaisesRegex(ValueError, 'SOURCE_AST_MISMATCH'):
            compact({'source': 'x = 1\n'})
        with self.assertRaisesRegex(ValueError, 'SOURCE_AST_MISMATCH'):
            compact({'source': b'x = 1\n'})

    def test_v24_and_v25_full_bundle_roundtrip_keep_existing_bounds_and_ast(self):
        import base64, gzip
        compact = self.compactor(); encode, decode, _ = shared.ContractTest().workflow_transport()
        from test_naver_preview_loading_v8_preservation import canonical
        for version in (24, 25):
            for kind, original in self.bundles(version).items():
                bundle = compact(original)
                for key in original:
                    if key == 'source' or key.endswith('_source'):
                        self.assertEqual(canonical(ast.parse(original[key])), canonical(ast.parse(bundle[key])), (version, kind, key))
                    else:
                        self.assertEqual(bundle[key], original[key])
                raw = json.dumps(bundle).encode()
                wire = 'prepare-gzip-v1:' + base64.b64encode(gzip.compress(raw, mtime=0)).decode() if kind == 'prepare' else encode(bundle)
                with self.subTest(version=version, kind=kind):
                    self.assertLessEqual(len(raw), 229376); self.assertLessEqual(len(wire), 73728)
                    decoded = json.loads(gzip.decompress(base64.b64decode(wire.removeprefix('prepare-gzip-v1:')))) if kind == 'prepare' else decode(wire)
                    self.assertEqual(decoded, bundle)

    def test_original_encoders_decoders_and_historical_non_code_operations_are_unchanged(self):
        current = (TOOLS.parents[1] / '.github/workflows/debug-rank.yml').read_text()
        base = subprocess.check_output(['git', 'show', '5b5db11192980485919bb2b3c8484f0f62df9e0a:.github/workflows/debug-rank.yml'], cwd=TOOLS).decode()
        self.assertEqual(historical_transport_functions(current), historical_transport_functions(base))
        shared.ContractTest().test_transport_keeps_other_operations_byte_identical_and_code_mode_exact()
        shared.ContractTest().test_transport_rejects_oversize_corrupt_truncated_and_trailing_gzip()

    def test_historical_transport_normalizes_only_the_exact_appended_route(self):
        current = (TOOLS.parents[1] / '.github/workflows/debug-rank.yml').read_text()
        base = subprocess.check_output(['git', 'show', '5b5db11192980485919bb2b3c8484f0f62df9e0a:.github/workflows/debug-rank.yml'], cwd=TOOLS).decode()
        historical = historical_transport_functions(base)
        self.assertEqual(historical_transport_functions(current), historical)
        for old, new in (('len(raw)>229376', 'len(raw)>229375'),
                ('len(encoded)>73728', 'len(encoded)>73727'),
                ('validate=True', 'validate=False'),
                ('not decoder.eof', 'False'), ('decoder.unused_data', 'False'),
                ('decoder.unconsumed_tail', 'False'),
                ("('preview-conversion-recovery-v26','run')", "('preview-conversion-recovery-v26','apply')"),
                ("'preview-resource-trial','preview-report-recovery'", "'unreviewed-operation','preview-report-recovery'"),
                ("'CODE_OPS_JSON_SIZE'", "'preview-conversion-recovery-v26'"),
                ("'preview-conversion-recovery-v26'):", "'preview-conversion-recovery-v26','preview-conversion-recovery-v26'):"),
                ("bundle['operation'] not in", "bundle['operation'] in")):
            with self.subTest(mutation=(old, new)):
                self.assertIn(old, current)
                changed = current.replace(old, new, 1)
                self.assertNotEqual(historical_transport_functions(changed), historical)
        with self.assertRaisesRegex(AssertionError, 'duplicate historical codec definition'):
            historical_transport_functions(current+"\npython3 - <<'PY'\ndef encode_ops(bundle):\n    return None\nPY\n")
        with self.assertRaisesRegex(AssertionError, 'both historical codec ASTs are required'):
            historical_transport_functions(current.replace('def decode_ops(encoded):', 'def other_decoder(encoded):'))

    def test_new_readonly_route_keeps_the_original_codec_rejections(self):
        import base64, gzip, zlib
        encode, decode, _ = shared.ContractTest().workflow_transport()
        bundle = dict(operation='preview-conversion-recovery-v26', function='run', package={})
        wire = encode(bundle)
        self.assertTrue(wire.startswith('code-gzip-v1:'))
        self.assertEqual(decode(wire), bundle)
        with self.assertRaisesRegex(ValueError, 'CODE_OPS_ENCODING'):
            decode(base64.b64encode(json.dumps(bundle).encode()).decode())
        with self.assertRaisesRegex(ValueError, 'CODE_OPS_OPERATION'):
            decode(encode(dict(bundle, function='apply')))
        packed = gzip.compress(json.dumps(bundle).encode())
        for data in (packed[:-1], packed+b'private-tail', packed+packed,
                     gzip.compress(b' '*229377), b'invalid-gzip'):
            with self.subTest(size=len(data)), self.assertRaises((ValueError, zlib.error)):
                decode('code-gzip-v1:'+base64.b64encode(data).decode())
        for bad in ('code-gzip-v1:!!!', 'code-gzip-v1:'+'A'*73728):
            with self.assertRaises(ValueError):
                decode(bad)
        with self.assertRaisesRegex(ValueError, 'CODE_OPS_JSON_SIZE'):
            encode(dict(bundle, source='x'*229376))

    def test_empty_ast_fields_are_compared_and_not_normalized_away(self):
        compact = self.compactor(); real = ast.parse; count = 0
        def changed(source, *args, **kwargs):
            nonlocal count
            count += 1; value = real(source, *args, **kwargs)
            if count % 2 == 0:
                self.assertEqual(value.type_ignores, []); value.type_ignores = None
            return value
        with patch.object(ast, 'parse', side_effect=changed), self.assertRaisesRegex(ValueError, 'SOURCE_AST_MISMATCH'):
            compact({'source': 'x = 1\n'})

    def test_actual_workflow_only_compacts_v24_v25_prepare_forward_and_reverse(self):
        import re, textwrap
        workflow = (TOOLS.parents[1] / '.github/workflows/debug-rank.yml').read_text()
        calls = []
        for body in re.findall(r"python3 - <<'PY'\n(.*?)\n\s*PY", workflow, re.S):
            for node in ast.walk(ast.parse(textwrap.dedent(body))):
                if isinstance(node, ast.If) and any(isinstance(part, ast.Call) and isinstance(part.func, ast.Name)
                        and part.func.id == 'compact_sources' for statement in node.body if isinstance(statement, ast.Assign) for part in ast.walk(statement)):
                    calls.append(ast.unparse(node.test))
        self.assertEqual(set(calls), {
            "operation in ('preview-code-only-upgrade', 'preview-code-only-rollback') and code_module in ('naver_preview_code_upgrade_v14', 'naver_preview_code_upgrade_v18', 'naver_preview_code_upgrade_v19', 'naver_preview_code_upgrade_v20', 'naver_preview_code_upgrade_v21', 'naver_preview_code_upgrade_v22', 'naver_preview_code_upgrade_v23', 'naver_preview_code_upgrade_v24', 'naver_preview_code_upgrade_v25', 'naver_preview_code_upgrade_v26')",
            "operation == 'preview-code-only-prepare' and code_module in ('naver_preview_code_upgrade_v14', 'naver_preview_code_upgrade_v18', 'naver_preview_code_upgrade_v19', 'naver_preview_code_upgrade_v20', 'naver_preview_code_upgrade_v21', 'naver_preview_code_upgrade_v22', 'naver_preview_code_upgrade_v23', 'naver_preview_code_upgrade_v24', 'naver_preview_code_upgrade_v25', 'naver_preview_code_upgrade_v26')"})
        self.assertEqual(len(calls), 2)
        old_builder = previous.V24WorkflowOptionTest()
        _, historical, _ = old_builder.builder('naver_preview_code_upgrade_v8')
        self.assertIsNotNone(historical)
        self.assertEqual(historical['code_source'], (TOOLS / 'naver_preview_code_upgrade_v8.py').read_text())
        self.assertEqual(historical['code_only_source'], (TOOLS / 'naver_preview_code_only.py').read_text())
        _, current, _ = old_builder.builder(MODULE, '74c912dddf824fae99012849bc4c19a5')
        self.assertIsNotNone(current)
        self.assertEqual(current['code_source'], self.compactor()({'code_source': (TOOLS / (MODULE + '.py')).read_text()})['code_source'])


class V25ProbeTest(probe_base.V23ProbeTest):
    def setUp(self):
        with patch.object(probe_base, 'MODULE', MODULE):
            super().setUp()
        original = self.release.unix_request.side_effect
        self.job_status = 401
        self.jobs = '/api/naver-auto/reports/strategy/jobs?job_id=' + '0' * 32
        def request(path, route, method='GET'):
            if route == self.jobs:
                self.seen.append(route)
                return (403 if self.source == self.code.OLD_COMMIT else self.job_status), {}, b''
            return original(path, route, method)
        self.release.unix_request.side_effect = request

    def test_new_jobs_auth_probe_is_absent_on_rollback_and_401_on_target(self):
        self.source = self.code.OLD_COMMIT
        self.code.probe(self.release, self.source, self.upgrade)
        self.assertNotIn(self.jobs, self.seen)
        self.source = self.code.TARGET_COMMIT; self.seen.clear()
        self.code.probe(self.release, self.source, self.upgrade)
        self.assertIn(self.jobs, self.seen)

    def test_target_jobs_get_must_never_succeed_or_be_unknown_without_auth(self):
        self.source = self.code.TARGET_COMMIT
        for status in (200, 403, 404, 500):
            self.job_status = status
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, 'CODE_ROUTE_STATUS'):
                self.code.probe(self.release, self.source, self.upgrade)


class V25IncomingReceiverTest(unittest.TestCase):
    def receiver(self, version, identity):
        import base64, builtins, gzip, io, os, re, textwrap
        from contextlib import redirect_stdout
        workflow = (TOOLS.parents[1] / '.github/workflows/debug-rank.yml').read_text()
        script = next(textwrap.dedent(body) for body in re.findall(r"/usr/bin/python3 -I -B - <<'PY'\n(.*?)\n\s*PY", workflow, re.S) if 'PREVIEW_INCOMING_READY' in body)
        bundle = V25TransportTest().bundles(version)['prepare']
        if identity is None:
            bundle.pop('approved_config_operation_id')
        else:
            bundle['approved_config_operation_id'] = identity
        calls = []
        bundle['host_source'] = 'class NativeHost:\n    def baseline(self):\n        return ' + repr(bundle['package']['baseline']) + '\n'
        bundle['source'] += "\nROOT = __import__('pathlib').Path('/synthetic/incoming-root')\ndef trusted_dir(path, **kwargs):\n    __import__('builtins')._naver_incoming_test_calls.append((str(path), kwargs))\n"
        compact = V25TransportTest().compactor(); bundle = compact(bundle)
        wire = 'prepare-gzip-v1:' + base64.b64encode(gzip.compress(json.dumps(bundle).encode(), mtime=0)).decode()
        out = io.StringIO(); status = 0
        with patch.object(builtins, '_naver_incoming_test_calls', calls, create=True), patch.dict(os.environ, PREVIEW_RELEASE_B64=wire), patch.object(os, 'geteuid', return_value=0), redirect_stdout(out):
            try:
                exec(compile(script, '<actual-incoming-receiver>', 'exec'), {})
            except SystemExit as error:
                status = error.code
        return status, out.getvalue(), calls

    def test_actual_first_receiver_accepts_only_exact_v24_v25_config_identity(self):
        for version in (24, 25):
            status, output, calls = self.receiver(version, '74c912dddf824fae99012849bc4c19a5')
            with self.subTest(version=version):
                self.assertEqual(status, 0); self.assertEqual(output, 'PREVIEW_INCOMING_READY\n')
                self.assertEqual(len(calls), 3); self.assertEqual(calls[-1][1], {'mode': 0o700, 'new': True})
            status, output, calls = self.receiver(version, 'f' * 32)
            with self.subTest(version=version, wrong_identity=True):
                self.assertEqual(status, 1); self.assertEqual(output, 'PREVIEW_INCOMING_REFUSED\n'); self.assertEqual(calls, [])

    def test_original_v23_receiver_refuses_new_config_option_before_directory_actions(self):
        status, output, calls = self.receiver(23, '74c912dddf824fae99012849bc4c19a5')
        self.assertEqual(status, 1); self.assertEqual(output, 'PREVIEW_INCOMING_REFUSED\n'); self.assertEqual(calls, [])
        status, output, calls = self.receiver(23, None)
        self.assertEqual(status, 0); self.assertEqual(output, 'PREVIEW_INCOMING_READY\n'); self.assertEqual(len(calls), 3)
