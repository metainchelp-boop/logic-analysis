"""Exact c40-to-pending closed appeal prefix transition; synthetic adapters only."""
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
    p = load(STAGE / 'tools/naver_appeal_suffix_patch.py', 'p11_patch_test')
    base = load(OPS_TOOLS / 'naver_preview_completion_release.py', 'p11_original_base_test')
    # Synthetic proof injection exercises the protocol without remote execution.
    proof=dict(source_commit=p.APPROVED_TARGET_COMMIT,tooling_head='d'*40,run_id='12345678901',receipt_sha256='b'*64)
    p.CODE_PATHS=p.EXPECTED_CODE_PATHS;p.NEW_PATHS=frozenset()
    p.TARGET_COMMIT=p.APPROVED_TARGET_COMMIT
    p.APPROVED_TARGET_SOURCE_SHA256='e'*64
    p.TARGET_SOURCE_SHA256=p.APPROVED_TARGET_SOURCE_SHA256
    p.TARGET_CANONICAL_SHA256=p.APPROVED_CANONICAL_SHA256='b'*64
    p.CI_PROOF=dict(proof);p.APPROVED_CI_PROOF=dict(proof)
    p.TARGET_DELTA=dict(p.EXPECTED_TARGET_DELTA)
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
                with self.subTest(field=field, method=method), self.assertRaisesRegex(ValueError, '^APPEAL_SUFFIX_PINS_PENDING$'):
                    getattr(p, method)({}, *adapters)
                self.assertTrue(all(not a.mock_calls for a in adapters))

    def test_exact_c40_baseline_provider_only_assets_store_and_schema(self):
        p, _ = pinned()
        self.assertEqual(p.OLD_COMMIT,'c40a1dbd0132043ce5b6a6a5565c7786699b60c0')
        self.assertEqual(p.BASE_PREPARE_RUN,'38329975429')
        self.assertEqual(p.BASE_APPLY_OPERATION,'ee474c9b697e411ab3748f185728f56d')
        self.assertEqual(p.TARGET_COMMIT,'fd9132c07031cae7162fb8af2a5131a8b1aeaba0')
        self.assertEqual(len(p.TARGET_MANIFEST),163)
        self.assertEqual(set(p.OLD_MANIFEST),set(p.TARGET_MANIFEST))
        self.assertEqual(p.NEW_PATHS,frozenset())
        self.assertEqual({k for k in p.OLD_MANIFEST if p.OLD_MANIFEST[k]!=p.TARGET_MANIFEST[k]}, p.EXPECTED_CODE_PATHS)
        self.assertEqual(p.CODE_PATHS,frozenset({'naver_runtime/claude_provider.py'}))
        self.assertEqual((p.OLD_SCHEMA,p.TARGET_SCHEMA),(21,21))
        self.assertEqual(p.STORE_SHA256['old'],p.STORE_SHA256['target'])
        self.assertEqual({k for k in p.REPORT_ASSETS if p.REPORT_ASSETS[k]!=p.OLD_REPORT_ASSETS[k]},set())

    def test_static_target_known_but_archive_native_canonical_and_seal_are_not_claimed(self):
        p=load(STAGE/'tools/naver_appeal_suffix_patch.py','p11_pending_native_test')
        self.assertEqual(p.TARGET_COMMIT,'fd9132c07031cae7162fb8af2a5131a8b1aeaba0')
        self.assertEqual(p.APPROVED_TARGET_COMMIT,p.TARGET_COMMIT)
        self.assertEqual(p.EXPECTED_TARGET_DELTA,{'naver_runtime/claude_provider.py':(420,46315,'b11210e4f0efda22d026430c8949e0f501518ddb329601f475cb8245f0c5bc69')})
        self.assertEqual(p.OLD_SOURCE_SHA256,'afc1547c598502032fc0d34737e524627d4d7b1fd834b5204b4c11e6a4f3031a')
        # Missing-proof behavior remains reproducible after actual pins are approved.
        for field in ('TARGET_SOURCE_SHA256','TARGET_CANONICAL_SHA256','CI_PROOF','APPROVED_TARGET_SOURCE_SHA256','APPROVED_CI_PROOF','APPROVED_CANONICAL_SHA256'):
            with patch.object(p,field,None),self.subTest(field=field),self.assertRaisesRegex(ValueError,'^APPEAL_SUFFIX_PINS_PENDING$'):
                p.require_target_pins()


    def test_store_schema_migration_and_every_byte_remain_identical(self):
        p,_=pinned()
        before=b'SCHEMA_VERSION=21\n_SCHEMA=("CREATE TABLE x(a)",)\n_REVISION_COLUMNS={}\ndef _migrate():\n return None\nclass ManagedStorage:\n def reserve_learning_call(self,x,*,unlimited=False):\n  return x\n'
        p.STORE_SHA256={'old':hashlib.sha256(before).hexdigest(),'target':hashlib.sha256(before).hexdigest()}
        p.migration_contract(before,before)
        for bad in (before.replace(b'SCHEMA_VERSION=21',b'SCHEMA_VERSION=22'),before.replace(b'CREATE TABLE x(a)',b'CREATE TABLE x(a,b)'),before.replace(b'return None',b'return True'),before.replace(b'*,unlimited=False',b'*,unlimited=True'),before+b'\n# altered byte\n'):
            p.STORE_SHA256['target']=hashlib.sha256(bad).hexdigest()
            with self.subTest(mutation=bad),self.assertRaises(ValueError):p.migration_contract(before,bad)
        job=b'def clean(x):\n return x\ndef public(x):\n return x\ndef identity(x):\n return x\n'
        p.learning_job_contract(job,job)
        for name in (b'clean',b'public',b'identity'):
            mutation=job.replace(b'def '+name+b'(x):\n return x',b'def '+name+b'(x):\n return None')
            with self.assertRaisesRegex(ValueError,'^PATCH_SCHEMA$'):p.learning_job_contract(job,mutation)


    def test_p10_lifecycle_and_existing_safety_functions_are_ast_unchanged(self):
        raw=(OPS_TOOLS/'naver_appeal_prefix_patch.py').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'dbfb7aad6d2ce02c4311d5cb8232b4205d2a3d7014cbff2f7467d214e285a1eb')
        def functions(body):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(body).body if isinstance(n,ast.FunctionDef)}
        before,after=functions(raw),functions((STAGE/'tools/naver_appeal_suffix_patch.py').read_bytes())
        self.assertEqual({k for k in before if k in after and before[k]!=after[k]}, {'require_target_pins','bind_base','require_pins','base_success','provider_contract'})
        self.assertEqual(set(after)-set(before),{'appeal_success'})
        self.assertEqual(set(before)-set(after),set())
        self.assertEqual(after['compatible_source'],before['compatible_source'])
        self.assertEqual(after['compatible_inverse_source'],before['compatible_inverse_source'])


    def test_source_scope_old_chain_ci_assets_and_store_tampering_refuse(self):
        for mode in ('scope', 'same', 'ci', 'old', 'bridge', 'old_manifest', 'target_manifest', 'new_file', 'asset', 'continuity', 'budget'):
            p, _ = pinned()
            if mode == 'scope': p.CODE_PATHS |= {'naver_runtime/config.py'}
            elif mode == 'same': p.TARGET_DELTA['naver_runtime/claude_provider.py'] = p.OLD_MANIFEST['naver_runtime/claude_provider.py']
            elif mode == 'ci': p.CI_PROOF['run_id'] = '99999999999'
            elif mode == 'old': p.OLD_SOURCE_SHA256 = '0' * 64
            elif mode == 'bridge': p.BASE_APPLY_OPERATION = '0' * 32
            elif mode == 'old_manifest': p.OLD_MANIFEST['naver_engine/store.py'] = (0o644, 1, 'a' * 64)
            elif mode == 'target_manifest': p.TARGET_MANIFEST['naver_engine/store.py'] = (0o644,1,'a'*64)
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
        source = (STAGE / 'tools/naver_appeal_suffix_patch.py').read_text()
        self.assertNotIn('sqlite3.connect', source)
        self.assertNotIn('snapshot_to(', source)
        self.assertNotIn('restore_from(', source)
        self.assertNotIn('._migrate(', source)
        self.assertEqual(p.APPROVED_CONFIG_OPERATION_ID, '74c912dddf824fae99012849bc4c19a5')



    def test_provider_accepts_only_one_exact_sentence_and_preserves_every_other_byte(self):
        p,_=pinned()
        before=b'x=1\ndef _funnel_instructions():\n return "'+p.OLD_SUFFIX_INSTRUCTION+b'"\n'
        after=before.replace(p.OLD_SUFFIX_INSTRUCTION,p.NEW_SUFFIX_INSTRUCTION)
        p.provider_contract(before,after)
        mutations=(after.replace(b'x=1',b'x=2'),after.replace(b'_funnel_instructions',b'renamed'),
            after+b'\ndef other(): pass\n',after+b'# changed byte\n',
            after.replace(p.NEW_SUFFIX_INSTRUCTION,b'unapproved'),
            after.replace(b'<test>',b'<other>'),before)
        for bad in mutations:
            with self.subTest(size=len(bad)),self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.provider_contract(before,bad)
        for badbefore in (before+p.OLD_SUFFIX_INSTRUCTION,before.replace(p.OLD_SUFFIX_INSTRUCTION,b'other'),after):
            with self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.provider_contract(badbefore,after)

    def test_unresolved_gate_stops_every_operation_before_read_or_adapter(self):
        p=load(STAGE/'tools/naver_appeal_suffix_patch.py','p11_actual_gate')
        p.APPROVED_CI_PROOF=None
        for operation in ('prepare','apply','rollback'):
            adapters=[Mock() for _ in range(4)]
            with patch.object(Path,'read_bytes',side_effect=AssertionError('read')) as read, self.assertRaisesRegex(ValueError,'^APPEAL_SUFFIX_PINS_PENDING$'):
                getattr(p,operation)({},*adapters)
            self.assertFalse(any(a.mock_calls for a in adapters));read.assert_not_called()


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
            (p.BUDGET_COMMIT, p.BUDGET_SOURCE_SHA256, p.BUDGET_PREPARE_RUN, p.CONTINUITY_COMMIT, p.BUDGET_APPLY_OPERATION),
            (p.LEARNING_COMMIT,p.LEARNING_SOURCE_SHA256,p.LEARNING_PREPARE_RUN,p.BUDGET_COMMIT,p.LEARNING_APPLY_OPERATION),
            (p.BINDING_COMMIT,p.BINDING_SOURCE_SHA256,p.BINDING_PREPARE_RUN,p.LEARNING_COMMIT,p.BINDING_APPLY_OPERATION),
            (p.APPEAL_COMMIT,p.APPEAL_SOURCE_SHA256,p.APPEAL_PREPARE_RUN,p.BINDING_COMMIT,p.APPEAL_APPLY_OPERATION),
            (p.OLD_COMMIT,p.OLD_SOURCE_SHA256,p.BASE_PREPARE_RUN,p.APPEAL_COMMIT,p.BASE_APPLY_OPERATION)]
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

    def test_ten_historical_receipts_include_exact_c40_prepare_and_apply(self):
        p, _, r, u, receipts, _, roles = self.fixture()
        self.assertEqual(p.base_success(r, u)[1], receipts[p.OLD_COMMIT])
        self.assertEqual([call.args[0].name for call in u.read_file.call_args_list], ['preview-start-' + role[0] + '.json' for role in roles])

    def test_each_step_requires_source_run_previous_operation_config_and_off(self):
        for index in range(10):
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
H = load(OPS / 'tests/test_naver_inspection_continuity_transport.py', 'p11_historical_test')


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





class SuffixPairGuards(unittest.TestCase):
    def test_masked_historical_deltas_refuse_even_when_final_manifest_would_match(self):
        for delta,key in (('BINDING_DELTA','naver_runtime/claude_provider.py'),
                          ('STRATEGY_DELTA','naver_engine/marketing_strategy.py'),
                          ('BUDGET_DELTA','naver_runtime/claude_provider.py'),
                          ('APPEAL_DELTA','naver_runtime/claude_provider.py'),
                          ('PREFIX_DELTA','naver_runtime/claude_provider.py')):
            p,_=pinned();getattr(p,delta)[key]=(0o644,1,'0'*64)
            with self.subTest(delta=delta),self.assertRaisesRegex(ValueError,'^PATCH_SCOPE$'):p.require_pins()

    def test_inverse_always_validates_the_same_forward_pair_then_inverse_inventory(self):
        p,_=pinned();old=Path('/synthetic/old');target=Path('/synthetic/target');u=Mock()
        with patch.object(p,'compatible_source') as forward,patch.object(p,'compatible_code_scope') as scope:
            p.compatible_inverse_source(target,old,u)
            forward.assert_called_once_with(old,target,u)
            scope.assert_called_once_with(target,old,u,inverse=True)
        with patch.object(p,'compatible_source',side_effect=ValueError('CODE_SCOPE_CHANGED')),patch.object(p,'compatible_code_scope') as scope:
            with self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.compatible_inverse_source(target,old,u)
            scope.assert_not_called()

    def test_rollback_identity_is_only_c40_and_foreign_scope_is_refused(self):
        p,_=pinned()
        self.assertEqual(p.ROLLBACK_COMMIT,'c40a1dbd0132043ce5b6a6a5565c7786699b60c0')
        p.ROLLBACK_COMMIT=p.BINDING_COMMIT
        with self.assertRaisesRegex(ValueError,'^PATCH_SCOPE$'):p.require_pins()

    def test_current_base_requires_started_proof_not_returned_only_prepare_fields(self):
        p,c,r,u,receipts,starts,roles=BaselineChainTest().fixture()
        self.assertNotIn('database_opened_by_controller',receipts[p.OLD_COMMIT])
        self.assertNotIn('saved_export_companion_preserved',receipts[p.OLD_COMMIT])
        p.base_success(r,u)
        for field in ('database_opened_by_controller','database_snapshot_verified','source_warmup_performed',
                      'rollback_requires_matching_database','runtime_flags_verified','execution_enabled',
                      'saved_export_companion_preserved'):
            q,_,rr,uu,_,ss,_=BaselineChainTest().fixture();ss[q.OLD_COMMIT].pop(field)
            with self.subTest(field=field),self.assertRaises(ValueError):q.base_success(rr,uu)


if __name__=='__main__':unittest.main()
