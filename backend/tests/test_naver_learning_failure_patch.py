"""Exact DC-to-799 code-only transition; synthetic adapters/local source only."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

STAGE = Path(__file__).resolve().parents[1]
TOOLS = STAGE / 'tools'
OPS_TOOLS = (TOOLS if (TOOLS / 'naver_budget_draft_patch.py').is_file() else
    TOOLS.parents[2] / 'naver-claude-reference-ops-20261011/backend/tools')
OPS = OPS_TOOLS.parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pinned():
    p = load(STAGE / 'tools/naver_learning_failure_patch.py', 'p6_patch_test')
    base = load(OPS_TOOLS / 'naver_preview_completion_release.py', 'p6_original_base_test')
    p.bind_base(base)
    return p, base


def package(p):
    return dict(operation='code-prepare', baseline=p.EXPECTED_BASELINE, source_commit=p.TARGET_COMMIT,
        source_tar_gz_sha256=p.TARGET_SOURCE_SHA256, ciphertext_sha256='d' * 64, run_id='12345678901')


class ExactSourceTest(unittest.TestCase):
    def test_pending_target_refuses_before_all_adapters(self):
        for field in ('TARGET_COMMIT', 'CI_PROOF'):
            p, _ = pinned()
            setattr(p, field, None)
            for method in ('prepare', 'apply', 'rollback'):
                adapters = [Mock() for _ in range(4)]
                with self.subTest(field=field, method=method), self.assertRaisesRegex(ValueError, '^PATCH_NOT_PINNED$'):
                    getattr(p, method)({}, *adapters)
                self.assertTrue(all(not a.mock_calls for a in adapters))

    def test_exact_dc_baseline_five_paths_assets_and_schema(self):
        p, base = pinned()
        old = load(OPS_TOOLS / 'naver_budget_draft_patch.py', 'p5_frozen_test')
        old.bind_base(base)
        self.assertEqual(p.OLD_MANIFEST, old.TARGET_MANIFEST)
        self.assertEqual(p.OLD_COMMIT, 'dc168ff8cf8dac519ea38597305a0d9dd6f6c843')
        self.assertEqual(p.BASE_PREPARE_RUN, '38258857593')
        self.assertEqual(p.BASE_APPLY_OPERATION, '8137805c235747ca8a155711034e7d82')
        self.assertEqual(p.TARGET_COMMIT, '799d80225a8df0c897a125dcab75fd04978b1dbb')
        self.assertEqual(len(p.TARGET_MANIFEST), 163)
        self.assertEqual(set(p.OLD_MANIFEST), set(p.TARGET_MANIFEST))
        self.assertEqual(p.NEW_PATHS, frozenset())
        self.assertEqual({k for k in p.OLD_MANIFEST if p.OLD_MANIFEST[k] != p.TARGET_MANIFEST[k]}, p.CODE_PATHS)
        self.assertEqual(len(p.CODE_PATHS), 5)
        self.assertEqual((p.OLD_SCHEMA, p.TARGET_SCHEMA), (21, 21))
        self.assertNotEqual(p.STORE_SHA256['old'], p.STORE_SHA256['target'])
        self.assertEqual({k for k in p.REPORT_ASSETS if p.REPORT_ASSETS[k] != p.OLD_REPORT_ASSETS[k]}, {'/naver/report-ui.js'})
        self.assertEqual(p.REPORT_ASSETS['/naver/report-ui.js'][2], old.REPORT_ASSETS['/naver/report-ui.js'][2])

    def test_target_and_native_proof_are_exact_public_constants(self):
        p, _ = pinned()
        self.assertEqual(p.CI_PROOF, dict(source_commit='799d80225a8df0c897a125dcab75fd04978b1dbb',
            tooling_head='3f00365c6f8043fb48ec3f33aa0071531f27b9b4', run_id='38268019380',
            receipt_sha256='c6bb211aa96f181755a0130484618b5d7977f286ef402380bc8c196c5804513e'))
        self.assertEqual(p.TARGET_SOURCE_SHA256, '5de3b31c0eac7a021f360a68c9fa5d849dc385d498136a9143c2a1479e46fafa')

    def test_synthetic_schema_and_job_abi_accept_only_exact_contracts(self):
        p, _ = pinned()
        body = b'SCHEMA_VERSION=21\n_SCHEMA=("CREATE TABLE x(a)",)\n_REVISION_COLUMNS={}\ndef _migrate():\n    return None\n'
        with patch.dict(p.STORE_SHA256, old=hashlib.sha256(body).hexdigest(), target=hashlib.sha256(body).hexdigest()):
            p.migration_contract(body, body)
            for mutation in (body.replace(b'21', b'22'), body.replace(b'CREATE TABLE x(a)', b'CREATE TABLE x(a,b)'),
                             body.replace(b'_REVISION_COLUMNS={}', b'_REVISION_COLUMNS={"x":()}'),
                             body.replace(b'return None', b'return True')):
                with patch.dict(p.STORE_SHA256, target=hashlib.sha256(mutation).hexdigest()):
                    with self.assertRaisesRegex(ValueError, '^PATCH_SCHEMA$'): p.migration_contract(body, mutation)
        job = b'def clean(x):\n return x\ndef public(x):\n return x\ndef identity(x):\n return x\n'
        p.learning_job_contract(job, job + b'\ndef irrelevant():\n return None\n')
        for name in (b'clean', b'public', b'identity'):
            mutation = job.replace(b'def ' + name + b'(x):\n return x', b'def ' + name + b'(x):\n return None')
            with self.assertRaisesRegex(ValueError, '^PATCH_SCHEMA$'): p.learning_job_contract(job, mutation)


    def test_p5_lifecycle_functions_are_ast_unchanged(self):
        old = ast.parse((OPS_TOOLS / 'naver_budget_draft_patch.py').read_text())
        new = ast.parse((STAGE / 'tools/naver_learning_failure_patch.py').read_text())
        def functions(tree):
            return {n.name: ast.dump(n, include_attributes=False) for n in tree.body if isinstance(n, ast.FunctionDef)}
        before, after = functions(old), functions(new)
        changed = {k for k in before if before[k] != after.get(k)}
        self.assertEqual(changed, {'require_target_pins', 'bind_base', 'require_pins', 'base_success', 'compatible_source'})
        self.assertEqual(set(after) - set(before), {'continuity_success', 'learning_job_contract'})
        self.assertEqual(hashlib.sha256((OPS_TOOLS / 'naver_budget_draft_patch.py').read_bytes()).hexdigest(),
            '3b68a757d27054e55326c9e87fbb01e15635b6ac0ac0aa117187648af32b472f')

    def test_source_scope_old_chain_ci_assets_and_store_tampering_refuse(self):
        for mode in ('scope', 'same', 'ci', 'old', 'bridge', 'old_manifest', 'target_manifest', 'new_file', 'asset', 'continuity', 'budget'):
            p, _ = pinned()
            if mode == 'scope': p.CODE_PATHS |= {'naver_runtime/config.py'}
            elif mode == 'same': p.TARGET_DELTA['naver_engine/web.py'] = p.OLD_MANIFEST['naver_engine/web.py']
            elif mode == 'ci': p.CI_PROOF['run_id'] = '99999999999'
            elif mode == 'old': p.OLD_SOURCE_SHA256 = '0' * 64
            elif mode == 'bridge': p.BASE_APPLY_OPERATION = '0' * 32
            elif mode == 'old_manifest': p.OLD_MANIFEST['naver_engine/store.py'] = (0o644, 1, 'a' * 64)
            elif mode == 'target_manifest': p.TARGET_MANIFEST['naver_engine/store.py'] = p.OLD_MANIFEST['naver_engine/store.py']
            elif mode == 'new_file': p.TARGET_MANIFEST['naver_engine/invented.py'] = (0o644, 1, 'a' * 64)
            elif mode == 'asset': p.REPORT_ASSETS['/naver/report-ui.js'] = (1, 'a' * 64, 'text/plain')
            elif mode == 'continuity': p.CONTINUITY_DELTA['naver_engine/store.py'] = (0o644, 1, 'a' * 64)
            else: p.BUDGET_DELTA['naver_engine/setup_checks.py'] = (0o644, 1, 'a' * 64)
            with self.subTest(mode=mode), self.assertRaises(ValueError): p.require_pins()

    def test_unsafe_paths_close_before_blob_read(self):
        p, _ = pinned()
        for name in ('naver_engine/store 2.py', 'HANDOVER.md', '/tmp/x', 'naver_engine/../x', 'deploy/runtime.env'):
            self.assertFalse(p.safe_source_path(name))


    def test_controller_has_no_db_open_migrate_snapshot_or_restore_calls(self):
        p, _ = pinned()
        source = (STAGE / 'tools/naver_learning_failure_patch.py').read_text()
        self.assertNotIn('sqlite3.connect', source)
        self.assertNotIn('snapshot_to(', source)
        self.assertNotIn('restore_from(', source)
        self.assertNotIn('._migrate(', source)
        self.assertEqual(p.APPROVED_CONFIG_OPERATION_ID, '74c912dddf824fae99012849bc4c19a5')



class BaselineChainTest(unittest.TestCase):
    def fixture(self):
        p, c = pinned()
        secret = Path('/synthetic/secrets')
        files = {str(secret / 'runtime.env'): 'a' * 64, str(secret / 'other'): 'b' * 64}
        r = SimpleNamespace(ROOT=Path('/synthetic/release'), unique=dict, SECRET_ROOT=secret,
            SECRET_OWNERS={'runtime.env': (0, 0), 'other': (0, 0)})
        roles = [(p.HISTORICAL_TARGET, c.TARGET_SOURCE_SHA256, p.HISTORICAL_PREPARE_RUN, p.BASE_PREVIOUS_COMMIT, p.HISTORICAL_APPLY_OPERATION),
            (p.DADB_COMMIT, p.DADB_SOURCE_SHA256, p.DADB_PREPARE_RUN, p.HISTORICAL_TARGET, p.DADB_APPLY_OPERATION),
            (p.FAA0_COMMIT, p.FAA0_SOURCE_SHA256, p.FAA0_PREPARE_RUN, p.DADB_COMMIT, p.FAA0_APPLY_OPERATION),
            (p.STRATEGY_COMMIT, p.STRATEGY_SOURCE_SHA256, p.STRATEGY_PREPARE_RUN, p.FAA0_COMMIT, p.STRATEGY_APPLY_OPERATION),
            (p.CONTINUITY_COMMIT, p.CONTINUITY_SOURCE_SHA256, p.CONTINUITY_PREPARE_RUN, p.STRATEGY_COMMIT, p.CONTINUITY_APPLY_OPERATION),
            (p.OLD_COMMIT, p.OLD_SOURCE_SHA256, p.BASE_PREPARE_RUN, p.CONTINUITY_COMMIT, p.BASE_APPLY_OPERATION)]
        receipts, starts = {}, {}
        for commit, source, run, previous, operation in roles:
            receipts[commit] = dict(source_commit=commit, package=dict(source_tar_gz_sha256=source, run_id=run, baseline=p.EXPECTED_BASELINE),
                runtime_environment_preserved=True, config_operation_id=p.APPROVED_CONFIG_OPERATION_ID,
                runtime_flags_verified=True, inventory_enabled=True, execution_enabled=False, files=dict(files))
            starts[commit] = dict(ok=True, stage='internal_ready', source_commit=commit, previous_commit=previous,
                operation_id=operation, database_policy='preserve-in-place', database_schema=21, database_opened_by_controller=False,
                database_snapshot_verified=False, source_warmup_performed=False, rollback_requires_matching_database=False,
                runtime_flags_verified=True, execution_enabled=False, saved_export_companion_preserved=True)
        starts[p.HISTORICAL_TARGET].update(database_policy='paired-snapshot', database_opened_by_controller=True,
            database_snapshot_verified=True, source_status=dict(ok=True, schema=21, old_schema=11, old_tables=36,
            old_rows=389163, preserved_rows=True, migration_repeatable=True, network_calls=0,
            randomized_tables=sorted(c.RANDOMIZED_TABLES), randomized_tables_empty=True))
        receipts[c.OLD_COMMIT] = {'source_commit': c.OLD_COMMIT}
        u = SimpleNamespace(manifest=Mock(side_effect=lambda _r, commit, **_: (Path('/synthetic/naver-' + commit), receipts[commit])),
            read_file=Mock(side_effect=lambda path, **_: json.dumps(starts[Path(path).name.removeprefix('preview-start-').removesuffix('.json')]).encode()))
        return p, c, r, u, receipts, starts, roles

    def test_six_historical_receipts_include_exact_dc_prepare_and_apply(self):
        p, _, r, u, receipts, _, roles = self.fixture()
        self.assertEqual(p.base_success(r, u)[1], receipts[p.OLD_COMMIT])
        self.assertEqual([call.args[0].name for call in u.read_file.call_args_list], ['preview-start-' + role[0] + '.json' for role in roles])

    def test_each_step_requires_source_run_previous_operation_config_and_off(self):
        for index in range(6):
            for mutation in ('run', 'source', 'previous', 'operation', 'execution', 'schema', 'db', 'env', 'companion'):
                p, _, r, u, receipts, starts, roles = self.fixture()
                commit = roles[index][0]
                if mutation == 'run': receipts[commit]['package']['run_id'] = '99999999999'
                elif mutation == 'source': receipts[commit]['package']['source_tar_gz_sha256'] = '0' * 64
                elif mutation == 'previous': starts[commit]['previous_commit'] = '0' * 40
                elif mutation == 'operation': starts[commit]['operation_id'] = '0' * 32
                elif mutation == 'execution': starts[commit]['execution_enabled'] = True
                elif mutation == 'schema': starts[commit]['database_schema'] = 22
                elif mutation == 'db': starts[commit]['database_opened_by_controller'] = not starts[commit]['database_opened_by_controller']
                elif mutation == 'env': receipts[commit]['files'].pop(str(r.SECRET_ROOT / 'runtime.env'))
                else: receipts[commit]['runtime_environment_preserved'] = False
                with self.subTest(index=index, mutation=mutation), self.assertRaises(ValueError): p.base_success(r, u)

    def test_current_config_must_equal_historical_without_write(self):
        p, c, r, u, receipts, _, _ = self.fixture()
        files = [dict(path=str(r.SECRET_ROOT / name), content='synthetic-' + name) for name in r.SECRET_OWNERS]
        for value in receipts.values():
            if 'files' in value:
                value['files'] = {v['path']: hashlib.sha256(v['content'].encode()).hexdigest() for v in files}
        with patch.object(c, 'preserve_approved_config', return_value=(files, ('historical-proof',))):
            resolved, _ = p.preserve_approved_config(files, p.APPROVED_CONFIG_OPERATION_ID, receipts[p.OLD_COMMIT], r, u)
            self.assertEqual(resolved, files)
            receipts[p.OLD_COMMIT]['files'][files[0]['path']] = '0' * 64
            with self.assertRaisesRegex(ValueError, '^PATCH_CONFIG$'):
                p.preserve_approved_config(files, p.APPROVED_CONFIG_OPERATION_ID, receipts[p.OLD_COMMIT], r, u)


# Existing, unchanged synthetic lifecycle and runtime-flag cases use the new pair.
H = load(OPS / 'tests/test_naver_inspection_continuity_transport.py', 'p6_historical_test')


class LifecycleTest(H.LifecycleTests):
    def setUp(self):
        context = patch.object(H, 'pinned', pinned)
        context.start()
        self.addCleanup(context.stop)


class ActualFlagTest(H.ActualFlagHelpersTests):
    def setUp(self):
        context = patch.object(H, 'pinned', pinned)
        context.start()
        self.addCleanup(context.stop)


if __name__ == '__main__':
    unittest.main()
