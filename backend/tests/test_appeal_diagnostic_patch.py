"""Exact 328-to-new closed appeal diagnostic transition; synthetic adapters only."""
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
    p = load(STAGE / 'tools/naver_appeal_diagnostic_patch.py', 'p9_patch_test')
    base = load(OPS_TOOLS / 'naver_preview_completion_release.py', 'p9_original_base_test')
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
                with self.subTest(field=field, method=method), self.assertRaisesRegex(ValueError, '^APPEAL_DIAGNOSTIC_PINS_PENDING$'):
                    getattr(p, method)({}, *adapters)
                self.assertTrue(all(not a.mock_calls for a in adapters))

    def test_exact_799_baseline_provider_only_assets_store_and_schema(self):
        p, _ = pinned()
        self.assertEqual(p.OLD_COMMIT,'32878e8ecec616772b619c23e796931d44f0bee1')
        self.assertEqual(p.BASE_PREPARE_RUN,'38302658575')
        self.assertEqual(p.BASE_APPLY_OPERATION,'d5b43a4d776e4ef8826fc71083255064')
        self.assertEqual(p.TARGET_COMMIT,'4d5802360c1ba23aa801b1145ca8483db3edd35f')
        self.assertEqual(len(p.TARGET_MANIFEST),163)
        self.assertEqual(set(p.OLD_MANIFEST),set(p.TARGET_MANIFEST))
        self.assertEqual(p.NEW_PATHS,frozenset())
        self.assertEqual({k for k in p.OLD_MANIFEST if p.OLD_MANIFEST[k]!=p.TARGET_MANIFEST[k]}, p.EXPECTED_CODE_PATHS)
        self.assertEqual(len(p.CODE_PATHS),4)
        self.assertEqual((p.OLD_SCHEMA,p.TARGET_SCHEMA),(21,21))
        self.assertEqual(p.STORE_SHA256['old'],p.STORE_SHA256['target'])
        self.assertEqual({k for k in p.REPORT_ASSETS if p.REPORT_ASSETS[k]!=p.OLD_REPORT_ASSETS[k]},{'/naver/operations-ui.js'})

    def test_exact_source_archive_and_native_canonical_are_pinned(self):
        p=load(STAGE/'tools/naver_appeal_diagnostic_patch.py','p9_actual_pending_test')
        self.assertEqual(p.APPROVED_TARGET_COMMIT,'4d5802360c1ba23aa801b1145ca8483db3edd35f')
        self.assertEqual(p.TARGET_COMMIT,p.APPROVED_TARGET_COMMIT)
        self.assertEqual(set(p.EXPECTED_TARGET_DELTA),p.EXPECTED_CODE_PATHS)
        self.assertEqual(p.TARGET_SOURCE_SHA256,'1db45b8e54e562bd83c12b4cf53c791426ea45fccd85162bfb0e5f27179873fe')
        self.assertEqual(p.APPROVED_TARGET_SOURCE_SHA256,p.TARGET_SOURCE_SHA256)
        self.assertEqual(p.TARGET_CANONICAL_SHA256,'b1ce7e10044552e9d50427ba15f1e201836d88747fd0d16476a917cf72dab5c8')
        self.assertEqual(p.APPROVED_CANONICAL_SHA256,p.TARGET_CANONICAL_SHA256)
        self.assertEqual(p.CI_PROOF,{'source_commit': '4d5802360c1ba23aa801b1145ca8483db3edd35f', 'tooling_head': '7622eb427a46921eee5864ec969a9d37bc751ad5', 'run_id': '38307879311', 'receipt_sha256': 'b1ce7e10044552e9d50427ba15f1e201836d88747fd0d16476a917cf72dab5c8'})
        self.assertEqual(p.APPROVED_CI_PROOF,p.CI_PROOF)
        p.require_target_pins()
        for name in ('TARGET_COMMIT','APPROVED_TARGET_COMMIT','TARGET_DELTA','EXPECTED_TARGET_DELTA','CODE_PATHS','NEW_PATHS','CI_PROOF','APPROVED_CI_PROOF','TARGET_CANONICAL_SHA256','APPROVED_CANONICAL_SHA256','TARGET_SOURCE_SHA256','APPROVED_TARGET_SOURCE_SHA256'):
            candidate,_=pinned();setattr(candidate,name,None)
            with self.subTest(pin=name),self.assertRaisesRegex(ValueError,'^APPEAL_DIAGNOSTIC_PINS_PENDING$'):candidate.require_pins()

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


    def test_p8_lifecycle_and_existing_safety_functions_are_ast_unchanged(self):
        raw=(OPS_TOOLS/'naver_observation_binding_patch.py').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'df1cf9c2ceb27e58b4657afd125151a7a25d5dea49a8fb59b49cb25cc9d1eee4')
        def functions(body):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(body).body if isinstance(n,ast.FunctionDef)}
        before,after=functions(raw),functions((STAGE/'tools/naver_appeal_diagnostic_patch.py').read_bytes())
        self.assertEqual({k for k in before if before[k]!=after.get(k)}, {'require_target_pins','bind_base','require_pins','base_success','migration_contract','compatible_source'})
        self.assertEqual(set(after)-set(before),{'learning_success','marketing_contract','validation_contract'})

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
        source = (STAGE / 'tools/naver_appeal_diagnostic_patch.py').read_text()
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
        p=load(STAGE/'tools/naver_appeal_diagnostic_patch.py','p9_actual_gate')
        p.APPROVED_CI_PROOF=None
        for operation in ('prepare','apply','rollback'):
            adapters=[Mock() for _ in range(4)]
            with patch.object(Path,'read_bytes',side_effect=AssertionError('read')) as read, self.assertRaisesRegex(ValueError,'^APPEAL_DIAGNOSTIC_PINS_PENDING$'):
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
            (p.OLD_COMMIT,p.OLD_SOURCE_SHA256,p.BASE_PREPARE_RUN,p.LEARNING_COMMIT,p.BASE_APPLY_OPERATION)]
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

    def test_eight_historical_receipts_include_exact_328_prepare_and_apply(self):
        p, _, r, u, receipts, _, roles = self.fixture()
        self.assertEqual(p.base_success(r, u)[1], receipts[p.OLD_COMMIT])
        self.assertEqual([call.args[0].name for call in u.read_file.call_args_list], ['preview-start-' + role[0] + '.json' for role in roles])

    def test_each_step_requires_source_run_previous_operation_config_and_off(self):
        for index in range(8):
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
H = load(OPS / 'tests/test_naver_inspection_continuity_transport.py', 'p9_historical_test')


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




PRIOR_VALIDATION = '"""Closed validation facts; no response text, references, IDs or metric values.\n\nThese optional facts are stored beside the unchanged v1 provider trace. Older\nreaders can ignore them without losing the trace, its usage or its cost estimate.\n"""\n\nFIELDS = frozenset((\n    "document", "diagnosis", "direction", "shared_comment", "ab_comment",\n    "competitive_response", "competitive_response.hypothesis", "competitive_response.basis",\n    "funnel_comment", "funnel_comment.hypothesis", "funnel_comment.basis",\n    "appeal_points", "appeal_points.title", "appeal_points.message", "appeal_points.basis",\n    "weekly_plan.action", "weekly_plan.reason", "weekly_plan.criterion",\n    "monthly_plan.action", "monthly_plan.reason", "monthly_plan.criterion",\n))\nRULES = frozenset((\n    "document-shape", "text-shape", "market-reference-location", "funnel-reference-location",\n    "exploratory-claim", "randomized-claim", "numeric-reference-required", "reference-unavailable",\n    "funnel-shape", "funnel-hypothesis", "funnel-basis",\n    "competition-shape", "competition-hypothesis", "competition-basis",\n    "fixed-boundary", "product-unlinked", "appeal-hypothesis", "appeal-basis",\n))\nFLAGS = frozenset(("product_connected", "market_connected", "funnel_present",\n    "exploratory_learning", "randomized_learning"))\nKEYS = frozenset(("version", "field", "rule")) | FLAGS\nERROR_CODES = {rule: ("DOCUMENT_INVALID" if rule in ("document-shape", "text-shape") else\n    "NUMERIC_CITATION_REQUIRED" if rule == "numeric-reference-required" else\n    "REFERENCE_UNAVAILABLE" if rule == "reference-unavailable" else "UNCONNECTED_EVIDENCE") for rule in RULES}\n_SPECIFIC_FIELDS = {\n    "document-shape": {"document"}, "fixed-boundary": {"competitive_response", "funnel_comment", "ab_comment"},\n    "funnel-shape": {"funnel_comment"}, "funnel-hypothesis": {"funnel_comment.hypothesis"}, "funnel-basis": {"funnel_comment.basis"},\n    "competition-shape": {"competitive_response"}, "competition-hypothesis": {"competitive_response.hypothesis"},\n    "competition-basis": {"competitive_response.basis"}, "product-unlinked": {"appeal_points"},\n    "appeal-hypothesis": {"appeal_points.message"}, "appeal-basis": {"appeal_points.basis"},\n}\n\n\ndef normalize(value):\n    if (type(value) is not dict or set(value) != KEYS or type(value["version"]) is not int\n            or value["version"] != 1 or type(value["field"]) is not str or value["field"] not in FIELDS\n            or type(value["rule"]) is not str or value["rule"] not in RULES\n            or any(type(value[key]) is not bool for key in FLAGS)\n            or value["field"] not in _SPECIFIC_FIELDS.get(value["rule"], FIELDS)):\n        raise ValueError("VALIDATION_SUMMARY_INVALID")\n    return dict(value)\n\n\ndef failure(error):\n    """Never expose arbitrary exception attributes or stringify an error."""\n    try:\n        return normalize(getattr(error, "validation", None))\n    except Exception:\n        return None\n'
NEW_VALIDATION = '"""Closed validation facts; no response text, references, IDs or metric values.\n\nThese optional facts are stored beside the unchanged v1 provider trace. Older\nreaders can ignore them without losing the trace, its usage or its cost estimate.\n"""\n\nFIELDS = frozenset((\n    "document", "diagnosis", "direction", "shared_comment", "ab_comment",\n    "competitive_response", "competitive_response.hypothesis", "competitive_response.basis",\n    "funnel_comment", "funnel_comment.hypothesis", "funnel_comment.basis",\n    "appeal_points", "appeal_points.title", "appeal_points.message", "appeal_points.basis",\n    "weekly_plan.action", "weekly_plan.reason", "weekly_plan.criterion",\n    "monthly_plan.action", "monthly_plan.reason", "monthly_plan.criterion",\n))\nRULES = frozenset((\n    "document-shape", "text-shape", "market-reference-location", "funnel-reference-location",\n    "exploratory-claim", "randomized-claim", "numeric-reference-required", "reference-unavailable",\n    "funnel-shape", "funnel-hypothesis", "funnel-basis",\n    "competition-shape", "competition-hypothesis", "competition-basis",\n    "fixed-boundary", "product-unlinked", "appeal-hypothesis", "appeal-basis",\n))\nFLAGS = frozenset(("product_connected", "market_connected", "funnel_present",\n    "exploratory_learning", "randomized_learning"))\nKEYS = frozenset(("version", "field", "rule")) | FLAGS\nAPPEAL_REASONS = frozenset(("TITLE", "PREFIX", "SUFFIX", "LEXEME"))\nERROR_CODES = {rule: ("DOCUMENT_INVALID" if rule in ("document-shape", "text-shape") else\n    "NUMERIC_CITATION_REQUIRED" if rule == "numeric-reference-required" else\n    "REFERENCE_UNAVAILABLE" if rule == "reference-unavailable" else "UNCONNECTED_EVIDENCE") for rule in RULES}\n_SPECIFIC_FIELDS = {\n    "document-shape": {"document"}, "fixed-boundary": {"competitive_response", "funnel_comment", "ab_comment"},\n    "funnel-shape": {"funnel_comment"}, "funnel-hypothesis": {"funnel_comment.hypothesis"}, "funnel-basis": {"funnel_comment.basis"},\n    "competition-shape": {"competitive_response"}, "competition-hypothesis": {"competitive_response.hypothesis"},\n    "competition-basis": {"competitive_response.basis"}, "product-unlinked": {"appeal_points"},\n    "appeal-hypothesis": {"appeal_points.message"}, "appeal-basis": {"appeal_points.basis"},\n}\n\n\ndef normalize(value):\n    if (type(value) is not dict or set(value) not in (KEYS, KEYS | {"reason"}) or type(value["version"]) is not int\n            or value["version"] != 1 or type(value["field"]) is not str or value["field"] not in FIELDS\n            or type(value["rule"]) is not str or value["rule"] not in RULES\n            or any(type(value[key]) is not bool for key in FLAGS)\n            or value["field"] not in _SPECIFIC_FIELDS.get(value["rule"], FIELDS)\n            or ("reason" in value and (value["field"] != "appeal_points.message" or\n                value["rule"] != "appeal-hypothesis" or type(value["reason"]) is not str or\n                value["reason"] not in APPEAL_REASONS))):\n        raise ValueError("VALIDATION_SUMMARY_INVALID")\n    return dict(value)\n\n\ndef failure(error):\n    """Never expose arbitrary exception attributes or stringify an error."""\n    try:\n        return normalize(getattr(error, "validation", None))\n    except Exception:\n        return None\n'


class AppealSourceContractTests(unittest.TestCase):
    def marketing_sources(self):
        expression='row["title"] not in APPEAL_TITLES or not row["message"].startswith("검증 가설: ") or not row["message"].endswith(_APPEAL_SUFFIXES) or _UNSUPPORTED_APPEAL.search(row["message"])'
        before='APPEAL_TITLES=("fixed",)\ndef check(row):\n if '+expression+':\n  raise StrategyRefused("UNCONNECTED_EVIDENCE",field="appeal_points.message",rule="appeal-hypothesis")\ndef summary(error):\n value={}\n return value\n'
        newfailure='error=StrategyRefused("UNCONNECTED_EVIDENCE",field="appeal_points.message",rule="appeal-hypothesis")\n  error.validation_reason=("TITLE" if row["title"] not in APPEAL_TITLES else "PREFIX" if not row["message"].startswith("검증 가설: ") else "SUFFIX" if not row["message"].endswith(_APPEAL_SUFFIXES) else "LEXEME")\n  raise error'
        after=before.replace('raise StrategyRefused("UNCONNECTED_EVIDENCE",field="appeal_points.message",rule="appeal-hypothesis")',newfailure).replace(' value={}\n return value',' value={}\n if hasattr(error,"validation_reason"):\n  summary["reason"]=error.validation_reason\n return value')
        return before.encode(),after.encode()

    def test_only_exact_reason_attachment_can_be_removed_to_restore_original_or_module(self):
        p,_=pinned();before,after=self.marketing_sources();p.marketing_contract(before,after)
        mutations=(after.replace(b'not row["message"].endswith',b'row["message"].endswith',1),
            after.replace(b'"TITLE" if',b'"PRIVATE" if'),after.replace(b'else "LEXEME"',b'else row["message"]'),
            after.replace(b'rule="appeal-hypothesis"',b'rule="appeal-basis"'),after.replace(b'APPEAL_TITLES=("fixed",)',b'APPEAL_TITLES=("wider",)'),
            after+b'\ndef other(): return True\n')
        for bad in mutations:
            with self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.marketing_contract(before,bad)

    def test_exact_optional_reason_normalizer_keeps_every_other_validation_node(self):
        p,_=pinned();before=PRIOR_VALIDATION.encode();after=NEW_VALIDATION.encode();p.validation_contract(before,after)
        for bad in (after.replace(b'"TITLE", "PREFIX", "SUFFIX", "LEXEME"',b'"TITLE", "PREFIX", "SUFFIX", "LEXEME", "OTHER"'),after.replace(b'value["reason"] not in APPEAL_REASONS',b'False'),after.replace(b'type(value["reason"]) is not str',b'False'),after+b'\ndef bypass(): return True\n'):
            with self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.validation_contract(before,bad)


    def test_normalize_reference_is_authenticated_source_not_a_foreign_ast_digest(self):
        p,_=pinned()
        node=next(n for n in ast.parse(NEW_VALIDATION).body if isinstance(n,ast.FunctionDef) and n.name=='normalize')
        approved=ast.get_source_segment(NEW_VALIDATION,node)+'\n'
        self.assertEqual(p.NORMALIZE_REFERENCE_SOURCE,approved)
        self.assertEqual(p.NORMALIZE_REFERENCE_SHA256,'b620928726e9ef8a8c12d7bb813eeccd46bf171b5cac9a214f14d200c27a7703')
        self.assertEqual(hashlib.sha256(approved.encode()).hexdigest(),p.NORMALIZE_REFERENCE_SHA256)
        for altered in (approved+'# changed reference bytes\n',approved.replace('return dict(value)','return value'),None,b'bytes are not source'):
            with self.subTest(reference_type=type(altered).__name__),patch.object(p,'NORMALIZE_REFERENCE_SOURCE',altered),self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):
                p.validation_contract(PRIOR_VALIDATION.encode(),NEW_VALIDATION.encode())

    def test_same_host_ast_comparison_accepts_an_alternate_dump_format(self):
        p,_=pinned();original_dump=ast.dump
        def host_dump(node,*args,**kwargs):
            return 'HOST_FORMAT_WITH_EMPTY_FIELDS:'+original_dump(node,*args,**kwargs)
        node=next(n for n in ast.parse(NEW_VALIDATION).body if isinstance(n,ast.FunctionDef) and n.name=='normalize')
        self.assertNotEqual(hashlib.sha256(host_dump(node,include_attributes=False).encode()).hexdigest(),'42eb02610428e13976bf83275f2df7571814697954624c20dc6fd3aa950784c8')
        with patch.object(p.ast,'dump',side_effect=host_dump):
            p.validation_contract(PRIOR_VALIDATION.encode(),NEW_VALIDATION.encode())

    def test_alternate_dump_format_does_not_allow_changed_normalizer_or_other_nodes(self):
        p,_=pinned();original_dump=ast.dump
        def host_dump(node,*args,**kwargs):
            return 'HOST_FORMAT_WITH_EMPTY_FIELDS:'+original_dump(node,*args,**kwargs)
        before=PRIOR_VALIDATION.encode();after=NEW_VALIDATION.encode()
        mutants=(after.replace(b'value["reason"] not in APPEAL_REASONS',b'False'),
            after.replace(b'value["field"] != "appeal_points.message"',b'False'),
            after.replace(b'return dict(value)',b'return value'),
            after.replace(b'def normalize(value):',b'def normalize(value, extra=None):'),
            after.replace(b'def failure(error):',b'def failure(error, bypass=False):'),
            after+b'\ndef extra_authority(): return True\n')
        with patch.object(p.ast,'dump',side_effect=host_dump):
            p.validation_contract(before,after)
            for bad in mutants:
                with self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.validation_contract(before,bad)


if __name__ == '__main__':
    unittest.main()
