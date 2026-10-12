"""Exact 799-to-328 observation binding transition; synthetic adapters only."""
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
    p = load(STAGE / 'tools/naver_observation_binding_patch.py', 'p8_patch_test')
    base = load(OPS_TOOLS / 'naver_preview_completion_release.py', 'p8_original_base_test')
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
                with self.subTest(field=field, method=method), self.assertRaisesRegex(ValueError, '^OBSERVATION_BINDING_PINS_PENDING$'):
                    getattr(p, method)({}, *adapters)
                self.assertTrue(all(not a.mock_calls for a in adapters))

    def test_exact_799_baseline_provider_only_assets_store_and_schema(self):
        p, _ = pinned()
        self.assertEqual(p.OLD_COMMIT,'799d80225a8df0c897a125dcab75fd04978b1dbb')
        self.assertEqual(p.BASE_PREPARE_RUN,'38275892133')
        self.assertEqual(p.BASE_APPLY_OPERATION,'292df5809d8d49c49256c3bc3314bb7a')
        self.assertEqual(p.TARGET_COMMIT,'32878e8ecec616772b619c23e796931d44f0bee1')
        self.assertEqual(len(p.TARGET_MANIFEST),163)
        self.assertEqual(set(p.OLD_MANIFEST),set(p.TARGET_MANIFEST))
        self.assertEqual(p.NEW_PATHS,frozenset())
        self.assertEqual({k for k in p.OLD_MANIFEST if p.OLD_MANIFEST[k]!=p.TARGET_MANIFEST[k]}, p.EXPECTED_CODE_PATHS)
        self.assertEqual(len(p.CODE_PATHS),7)
        self.assertEqual((p.OLD_SCHEMA,p.TARGET_SCHEMA),(21,21))
        self.assertNotEqual(p.STORE_SHA256['old'],p.STORE_SHA256['target'])
        self.assertEqual(p.REPORT_ASSETS,p.OLD_REPORT_ASSETS)

    def test_actual_profile_matches_verified_native_canonical_source_and_rejects_missing_pins(self):
        p=load(STAGE/'tools/naver_observation_binding_patch.py','p8_actual_pins_test')
        self.assertEqual(p.APPROVED_TARGET_COMMIT,'32878e8ecec616772b619c23e796931d44f0bee1')
        self.assertEqual(p.TARGET_COMMIT,p.APPROVED_TARGET_COMMIT)
        self.assertEqual(p.TARGET_SOURCE_SHA256,'240d2afaba63d1ada075a565ab2dc1174bc00dbde98ed152181abac7dd8ad60c')
        self.assertEqual(p.APPROVED_TARGET_SOURCE_SHA256,p.TARGET_SOURCE_SHA256)
        self.assertEqual(p.TARGET_CANONICAL_SHA256,'eaccbd10edf0226138d26e7b84de0bcddf4c295ee6d977b7975c231672e8b57c')
        self.assertEqual(p.APPROVED_CANONICAL_SHA256,p.TARGET_CANONICAL_SHA256)
        self.assertEqual(p.CI_PROOF,dict(source_commit=p.TARGET_COMMIT,
            tooling_head='72483eec34b003af3d96b5dd06301d72a665bb95',run_id='38298734740',
            receipt_sha256=p.TARGET_CANONICAL_SHA256))
        self.assertEqual(p.APPROVED_CI_PROOF,p.CI_PROOF)
        self.assertEqual(p.TARGET_DELTA,p.EXPECTED_TARGET_DELTA)
        self.assertEqual(p.CODE_PATHS,p.EXPECTED_CODE_PATHS)
        self.assertEqual(p.NEW_PATHS,frozenset())
        p.require_pins()
        for name in ('TARGET_COMMIT','TARGET_DELTA','CODE_PATHS','NEW_PATHS','CI_PROOF','APPROVED_CI_PROOF',
                     'TARGET_CANONICAL_SHA256','APPROVED_CANONICAL_SHA256','TARGET_SOURCE_SHA256',
                     'APPROVED_TARGET_SOURCE_SHA256'):
            saved=getattr(p,name)
            setattr(p,name,None)
            with self.subTest(pin=name),self.assertRaisesRegex(ValueError,'^OBSERVATION_BINDING_PINS_PENDING$'):
                p.require_pins()
            setattr(p,name,saved)

    def test_synthetic_schema_public_reserve_and_job_abi_preserve_existing_contracts(self):
        p,_=pinned()
        before=b'SCHEMA_VERSION=21\n_SCHEMA=("CREATE TABLE x(a)",)\n_REVISION_COLUMNS={}\ndef _migrate():\n return None\nclass ManagedStorage:\n def reserve_learning_call(self,x,*,unlimited=False):\n  return x\n'
        after=before+b' def reserve_observed_learning_call(self,x):\n  return x\n'
        p.STORE_SHA256={'old':hashlib.sha256(before).hexdigest(),'target':hashlib.sha256(after).hexdigest()}
        p.migration_contract(before,after)
        for bad in (after.replace(b'SCHEMA_VERSION=21',b'SCHEMA_VERSION=22'),after.replace(b'CREATE TABLE x(a)',b'CREATE TABLE x(a,b)'),after.replace(b'return None',b'return True'),after.replace(b'*,unlimited=False',b'*,unlimited=True'),after.replace(b'  return x',b'  return None',1),after.replace(b'reserve_observed_learning_call',b'other')):
            p.STORE_SHA256['target']=hashlib.sha256(bad).hexdigest()
            with self.subTest(mutation=bad),self.assertRaises(ValueError):p.migration_contract(before,bad)
        job=b'def clean(x):\n return x\ndef public(x):\n return x\ndef identity(x):\n return x\n'
        p.learning_job_contract(job,job)
        for name in (b'clean',b'public',b'identity'):
            mutation=job.replace(b'def '+name+b'(x):\n return x',b'def '+name+b'(x):\n return None')
            with self.assertRaisesRegex(ValueError,'^PATCH_SCHEMA$'):p.learning_job_contract(job,mutation)


    def test_p6_lifecycle_and_existing_safety_functions_are_ast_unchanged(self):
        raw=(OPS_TOOLS/'naver_learning_failure_patch.py').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'8dddb4156047f9a0bb64b3ad0db23eac62ca0cd858ff9c1cbffe4bbbbbc81426')
        def functions(body):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(body).body if isinstance(n,ast.FunctionDef)}
        before,after=functions(raw),functions((STAGE/'tools/naver_observation_binding_patch.py').read_bytes())
        self.assertEqual({k for k in before if before[k]!=after.get(k)}, {'require_target_pins','bind_base','require_pins','base_success','migration_contract','compatible_source'})
        self.assertEqual(set(after)-set(before),{'budget_success','provider_contract','additive_class_contract','observation_store_contract','scheduled_reserve_contract','main'})

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
        source = (STAGE / 'tools/naver_observation_binding_patch.py').read_text()
        self.assertNotIn('sqlite3.connect', source)
        self.assertNotIn('snapshot_to(', source)
        self.assertNotIn('restore_from(', source)
        self.assertNotIn('._migrate(', source)
        self.assertEqual(p.APPROVED_CONFIG_OPERATION_ID, '74c912dddf824fae99012849bc4c19a5')



    def test_provider_prompt_change_preserves_every_other_ast_node(self):
        p,_=pinned()
        before=b'x=1\ndef _funnel_instructions():\n return "old"\n'
        after=b'x=1\ndef _funnel_instructions():\n return "new"\n'
        p.provider_contract(before,after)
        for bad in (after.replace(b'x=1',b'x=2'),after.replace(b'_funnel_instructions',b'renamed'),after+b'\ndef other(): pass\n'):
            with self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.provider_contract(before,bad)

    def test_unresolved_gate_stops_every_operation_before_read_or_adapter(self):
        p=load(STAGE/'tools/naver_observation_binding_patch.py','p8_actual_gate')
        p.APPROVED_CI_PROOF=None
        for operation in ('prepare','apply','rollback'):
            adapters=[Mock() for _ in range(4)]
            with patch.object(Path,'read_bytes',side_effect=AssertionError('read')) as read, self.assertRaisesRegex(ValueError,'^OBSERVATION_BINDING_PINS_PENDING$'):
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
            (p.OLD_COMMIT, p.OLD_SOURCE_SHA256, p.BASE_PREPARE_RUN, p.BUDGET_COMMIT, p.BASE_APPLY_OPERATION)]
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

    def test_seven_historical_receipts_include_exact_799_prepare_and_apply(self):
        p, _, r, u, receipts, _, roles = self.fixture()
        self.assertEqual(p.base_success(r, u)[1], receipts[p.OLD_COMMIT])
        self.assertEqual([call.args[0].name for call in u.read_file.call_args_list], ['preview-start-' + role[0] + '.json' for role in roles])

    def test_each_step_requires_source_run_previous_operation_config_and_off(self):
        for index in range(7):
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
H = load(OPS / 'tests/test_naver_inspection_continuity_transport.py', 'p8_historical_test')


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


class ObservationContractTest(unittest.TestCase):
    def scheduled_source(self):
        header = 'class Worker:\n def _visit(self,method,*args,**kwargs):\n  return self.write(lambda st:self._commit(lambda:getattr(st,method)(*args,**kwargs)))\n def _run(self,job):\n'
        before = header + "  self._visit('report_schedule_work')\n  self._visit('report_schedule_reserve')\n  self._visit('report_schedule_finish')\n  self._visit('report_schedule_fail')\n  self._visit('report_schedule_started')\n  self._visit('report_schedule_response')\n"
        after = header + "  self._visit('report_schedule_work')\n  self._visit('report_schedule_started')\n  self._visit('report_schedule_response')\n  reservation=self.write(lambda st:self._commit(lambda:st.report_schedule_reserve_observed(current['job_id'],current['version'],self.clock(),getattr(self.provider,'maximum_call_microusd',None),getattr(self.provider,'monthly_budget_microusd',None),unlimited=getattr(self.provider,'monthly_budget_unlimited',False),trace_id=observation.trace.trace_id)))\n"
        return before.encode(), after.encode()

    def test_scheduled_observed_reserve_uses_typed_writer_callback_and_commit_fence(self):
        p, _ = pinned()
        before, after = self.scheduled_source()
        p.scheduled_reserve_contract(before, after)

    def test_dynamic_selector_or_missing_writer_fence_cannot_replace_typed_reserve(self):
        p, _ = pinned()
        before, after = self.scheduled_source()
        mutations = (
            after.replace(b'reservation=self.write(', b"self._visit('report_schedule_reserve_observed')\n  reservation=self.write("),
            after.replace(b'self._commit(lambda:st.report_schedule_reserve_observed', b'self._other_commit(lambda:st.report_schedule_reserve_observed'),
            after.replace(b'reservation=self.write(', b'reservation=self.other_write('),
            after.replace(b'st.report_schedule_reserve_observed(', b"getattr(st,'report_schedule_reserve_observed')(") ,
            after.replace(b'unlimited=getattr', b'unlimited_override=getattr'),
            after.replace(b'def _visit(self,method,*args,**kwargs)', b'def _visit(self,method,*args,extra=None,**kwargs)'),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, '^CODE_SCOPE_CHANGED$'):
                p.scheduled_reserve_contract(before, mutation)

    def source(self):
        before = b"""class ObservationStorage:
 def begin_provider_observation(self,prepared,actor,now,job_id,trace_id,origin):
  'legacy public binding contract'
  self._need_writer();self._not_future(now,'operation')
  if not actor:_refuse()
  with self._tx() as c:
   row=c.execute('SELECT bound').fetchone()
   if row is None:_refuse()
  return {'bound':True}
 def record_provider_observation(self,trace_id,snapshot,now):
  return snapshot
"""
        after = b"""class ObservationStorage:
 def begin_provider_observation(self,prepared,actor,now,job_id,trace_id,origin):
  'legacy public binding contract'
  self._need_writer();self._not_future(now,'operation')
  if not actor:_refuse()
  with self._tx() as c:
   self._begin_provider_observation(c,prepared,actor,now,job_id,trace_id,origin)
  return {'bound':True}
 def _begin_provider_observation(self,c,prepared,actor,now,job_id,trace_id,origin):
  self._need_writer();self._not_future(now,'operation')
  if not actor:_refuse()
  row=c.execute('SELECT bound').fetchone()
  if row is None:_refuse()
  return {'bound':True}
 def record_provider_observation(self,trace_id,snapshot,now):
  return snapshot
"""
        return before, after

    def test_exact_extraction_retains_binding_guards_and_public_signature(self):
        p, _ = pinned()
        before, after = self.source()
        p.observation_store_contract(before, after)

    def test_extraction_guards_and_authority_arguments_cannot_change(self):
        p, _ = pinned()
        before, after = self.source()
        mutations = (
            after.replace(b'if not actor:_refuse()', b'if False:_refuse()'),
            after.replace(b'if row is None:_refuse()', b'if False:_refuse()'),
            after.replace(b'c,prepared,actor,now,job_id,trace_id,origin)', b'c,prepared,0,now,job_id,trace_id,origin)', 1),
            after.replace(b'return snapshot', b'return None'),
            after.replace(b'with self._tx()', b'with self._other_tx()'),
            after.replace(b' def begin_provider_observation', b' @staticmethod\n def begin_provider_observation'),
            after.replace(b'c,prepared,actor,now,job_id,trace_id,origin):', b'c,prepared,actor,now,job_id,trace_id,origin=False):'),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, '^PATCH_SCHEMA$'):
                p.observation_store_contract(before, mutation)

    def test_scheduled_addition_preserves_the_complete_legacy_class_and_module(self):
        p, _ = pinned()
        before = b'class ReportScheduleStorage:\n def report_schedule_reserve(self,job_id,expected_version,unlimited=False):\n  return job_id\n'
        after = before + b' def report_schedule_reserve_observed(self,job_id,*,trace_id):\n  return job_id\n'
        p.additive_class_contract(before, after, 'ReportScheduleStorage', 'report_schedule_reserve_observed')
        for bad in (after.replace(b'unlimited=False', b'unlimited=True'),
                    after.replace(b'  return job_id', b'  return None', 1),
                    after + b'x=1\n', after.replace(b'def report_schedule_reserve_observed', b'def other')):
            with self.subTest(mutation=bad), self.assertRaisesRegex(ValueError, '^PATCH_SCHEMA$'):
                p.additive_class_contract(before, bad, 'ReportScheduleStorage', 'report_schedule_reserve_observed')

    def test_missing_each_execution_pin_refuses_before_file_or_host_access(self):
        fields = ('CODE_PATHS', 'NEW_PATHS', 'TARGET_COMMIT', 'TARGET_DELTA', 'TARGET_SOURCE_SHA256',
                  'TARGET_CANONICAL_SHA256', 'CI_PROOF', 'APPROVED_CI_PROOF', 'APPROVED_CANONICAL_SHA256',
                  'APPROVED_TARGET_SOURCE_SHA256')
        for field in fields:
            p, _ = pinned()
            setattr(p, field, None)
            for method in ('prepare', 'apply', 'rollback'):
                adapters = [Mock() for _ in range(4)]
                with self.subTest(field=field, method=method), patch.object(Path, 'read_bytes', side_effect=AssertionError('read')) as reader, self.assertRaisesRegex(ValueError, '^OBSERVATION_BINDING_PINS_PENDING$'):
                    getattr(p, method)({}, *adapters)
                reader.assert_not_called()
                self.assertTrue(all(not obj.mock_calls for obj in adapters))

    def test_valid_shape_wrong_canonical_source_or_delta_is_refused(self):
        for field in ('TARGET_CANONICAL_SHA256', 'TARGET_SOURCE_SHA256', 'TARGET_COMMIT'):
            p, _ = pinned()
            setattr(p, field, 'c' * (40 if field == 'TARGET_COMMIT' else 64))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, '^PATCH_NOT_PINNED$'):
                p.require_pins()
        p, _ = pinned()
        p.TARGET_DELTA = dict(p.TARGET_DELTA)
        p.TARGET_DELTA['naver_engine/store.py'] = (420, 1, 'c' * 64)
        with self.assertRaisesRegex(ValueError, '^PATCH_NOT_PINNED$'):
            p.require_pins()


if __name__ == '__main__':
    unittest.main()
