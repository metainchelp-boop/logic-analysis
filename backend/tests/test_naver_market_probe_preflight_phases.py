"""New phase routing only: fake host primitives, no DB, service or network calls."""
from contextlib import ExitStack
import importlib.util
from pathlib import Path
import stat
import types
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve()
CORE = HERE.with_name('naver_market_source_limit_probe.py')
if not CORE.is_file():
    CORE = HERE.parents[1] / 'tools/naver_market_source_limit_probe.py'
SPEC = importlib.util.spec_from_file_location('preflight_phase_candidate', CORE)
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)


class Fixture:
    def __init__(self, fail=None):
        self.stack = ExitStack()
        self.plan = dict(ops_commit='a' * 40, source_directory='/synthetic/source',
                        database_name='fixture.db', exporter_user='nobody',
                        source_group=None, python_executable='/usr/bin/python3')
        self.bound = types.SimpleNamespace(plan=self.plan, receipt=object())
        self.binary = b'synthetic-interpreter'
        self.sources = {'product_exporter': b'product-fixture', 'market_exporter': b'market-fixture'}
        self.prepared = {'python': self.binary}
        self.info = types.SimpleNamespace(st_dev=1, st_ino=2, st_mode=stat.S_IFREG | 0o755,
            st_uid=0, st_gid=0, st_nlink=1, st_size=len(self.binary), st_mtime_ns=3, st_ctime_ns=4)
        self.helper = types.SimpleNamespace(INSTALL=Path('/synthetic/install'), MAX_INTERPRETER=1024,
            INTERPRETER='python', build_plan=Mock(return_value=self.plan),
            _prepared=Mock(return_value=(self.plan, None, self.prepared)),
            _regular=Mock(side_effect=lambda p, **kw: self.sources[
                'product_exporter' if p.name == 'naver_product_export.py' else 'market_exporter']))
        self.open = self.stack.enter_context(patch.object(D.os, 'open', return_value=17))
        self.close = self.stack.enter_context(patch.object(D.os, 'close'))
        self.read = self.stack.enter_context(patch.object(D.os, 'read', side_effect=[self.binary, b'']))
        self.fstat = self.stack.enter_context(patch.object(D.os, 'fstat', return_value=self.info))
        self.stack.enter_context(patch.object(Path, 'stat', return_value=self.info))
        self.stack.enter_context(patch.object(D.sys, 'platform', 'linux'))
        self.stack.enter_context(patch.object(D, 'SOURCE_PINS',
            {k: D.hashlib.sha256(v).hexdigest() for k, v in self.sources.items()}))
        self.family = self.stack.enter_context(patch.object(D, '_file_family', return_value={'fixture': True}))
        self.child_result = D.empty_probe()
        self.child_result.update(status='original_collect_passed', database_opened=True, collect_calls=1)
        self.child = self.stack.enter_context(patch.object(D, '_run_child', return_value=self.child_result))
        secret = RuntimeError('SECRET /private/path synthetic raw error')
        if fail == 'probe_plan': self.helper.build_plan.side_effect = secret
        elif fail == 'probe_prepared': self.helper._prepared.side_effect = secret
        elif fail == 'probe_platform': self.stack.enter_context(patch.object(D.sys, 'platform', 'other'))
        elif fail == 'probe_interpreter_open': self.open.side_effect = secret
        elif fail == 'probe_interpreter_shape': self.info.st_uid = 1
        elif fail == 'probe_interpreter_stability':
            after = types.SimpleNamespace(**vars(self.info)); after.st_ino += 1
            self.fstat.side_effect = [self.info, after]
        elif fail == 'probe_interpreter_match': self.prepared['python'] = b'different'
        elif fail == 'probe_installed_product': self.helper._regular.side_effect = secret
        elif fail == 'probe_installed_market': self.helper._regular.side_effect = [self.sources['product_exporter'], b'different']
        elif fail == 'probe_source_family': self.family.side_effect = secret
        elif fail == 'probe_child_setup': self.child.side_effect = secret

    def __enter__(self): return self
    def __exit__(self, *args): return self.stack.__exit__(*args)
    def run(self): return D._verified_probe(self.bound, self.helper, self.sources)


def diagnose_with_probe(error=None, result=None, early=False):
    class ExportError(Exception): pass
    bound = types.SimpleNamespace(receipt=object(), load=Mock(), command=Mock(),
        operation=lambda callback: callback())
    helper = types.SimpleNamespace(ExportInstallInvalid=ExportError,
        verify=Mock(side_effect=ExportError('EXPORT_RUN_NOT_VERIFIED')))
    binding = types.SimpleNamespace(Binding=Mock(return_value=bound))
    sources = dict(exports_helper=b'h', product_exporter=b'p', market_exporter=b'm')
    with ExitStack() as stack:
        stack.enter_context(patch.object(D, 'require_pins', side_effect=error if early else None))
        stack.enter_context(patch.object(D, '_load_modules', return_value=(binding, helper)))
        stack.enter_context(patch.object(D, '_read_operating_receipt', return_value=True))
        stack.enter_context(patch.object(D, '_failure_component', return_value='market_result'))
        stack.enter_context(patch.object(D, '_verified_probe', side_effect=None if early else error,
            return_value=result if result is not None else D.empty_probe()))
        return D.diagnose(sources)


class PreflightPhaseTests(unittest.TestCase):
    def test_all_eleven_failure_stages_closed_without_raw_error(self):
        for stage in D.PREFLIGHT_PHASES:
            with self.subTest(stage=stage), Fixture(stage) as f:
                with self.assertRaises(D.ProbeStop) as caught: f.run()
                self.assertEqual(type(caught.exception), D.ProbeStop)
                self.assertEqual(caught.exception.args, (stage,))
                self.assertTrue(caught.exception.__suppress_context__)
                self.assertNotIn('SECRET', str(caught.exception))
                self.assertEqual(f.child.call_count, int(stage == 'probe_child_setup'))

    def test_original_child_result_identity_and_unknown_state_preserved(self):
        for status in ('source_limit', 'original_collect_passed', 'original_other_failure', 'diagnostic_unavailable'):
            with self.subTest(status=status), Fixture() as f:
                f.child_result['status'] = status
                if status == 'diagnostic_unavailable':
                    f.child_result.update(database_opened=None, collect_calls=None)
                self.assertIs(f.run(), f.child_result)
                f.child.assert_called_once_with(f.plan, f.sources, {'fixture': True},
                    Path('/synthetic/install') / f.plan['ops_commit'])

    def test_success_keeps_original_read_and_call_counts(self):
        with Fixture() as f:
            f.run()
            f.helper.build_plan.assert_called_once_with(**f.plan)
            f.helper._prepared.assert_called_once_with(f.bound.receipt)
            self.assertEqual(f.open.call_count, 1)
            self.assertEqual(f.read.call_count, 2)
            self.assertEqual(f.fstat.call_count, 2)
            f.close.assert_called_once_with(17)
            self.assertEqual(f.helper._regular.call_count, 2)
            f.family.assert_called_once_with(Path(f.plan['source_directory']), f.plan['database_name'])
            f.child.assert_called_once()

    def test_stability_refusal_shortcircuits_digest_lookup(self):
        class Unreadable(dict):
            def __getitem__(self, key): raise AssertionError('digest must not be consulted')
        with Fixture('probe_interpreter_stability') as f:
            f.helper._prepared.return_value = (f.plan, None, Unreadable())
            with self.assertRaisesRegex(D.ProbeStop, '^probe_interpreter_stability$'): f.run()
            f.close.assert_called_once_with(17)

    def test_digest_refusal_still_closes_interpreter_before_scripts(self):
        with Fixture('probe_interpreter_match') as f:
            with self.assertRaisesRegex(D.ProbeStop, '^probe_interpreter_match$'): f.run()
            f.close.assert_called_once_with(17)
            f.helper._regular.assert_not_called()
            f.family.assert_not_called()

    def test_diagnose_accepts_only_exact_whitelisted_probe_stop(self):
        for stage in D.PREFLIGHT_PHASES:
            with self.subTest(stage=stage):
                result = diagnose_with_probe(D.ProbeStop(stage))
                self.assertEqual(result['phase'], stage)
                self.assertEqual(result['probe']['status'], 'diagnostic_unavailable')
                self.assertIs(result['probe']['database_opened'], False)
                self.assertEqual(result['probe']['collect_calls'], 0)
                self.assertIsInstance(D.closed_json(result), str)
        class Forged(D.ProbeStop): pass
        for error in (Forged('probe_plan'), D.ProbeStop(), D.ProbeStop('probe_plan', 'extra'),
                      D.ProbeStop('/private/SECRET'), D.ProbeStop(['probe_plan']), RuntimeError('probe_plan')):
            with self.subTest(error_type=type(error).__name__):
                result = diagnose_with_probe(error)
                self.assertEqual(result['phase'], 'probe')
                self.assertNotIn('SECRET', D.closed_json(result))

    def test_earlier_exception_cannot_spoof_probe_stage(self):
        result = diagnose_with_probe(D.ProbeStop('probe_plan'), early=True)
        self.assertEqual(result['phase'], 'pins')
        self.assertIs(result['operating_receipt_match'], False)

    def test_diagnose_preserves_below_child_results_and_success_definition(self):
        for status in ('source_limit', 'original_collect_passed', 'original_other_failure', 'diagnostic_unavailable'):
            with self.subTest(status=status):
                child = D.empty_probe(); child.update(status=status, database_opened=None if status == 'diagnostic_unavailable' else True,
                    collect_calls=None if status == 'diagnostic_unavailable' else 1)
                result = diagnose_with_probe(result=child)
                self.assertIs(result['probe'], child)
                self.assertEqual(result['phase'], 'complete')
                self.assertEqual(result['ok'], status != 'diagnostic_unavailable')

    def test_closed_phase_rejects_unknown_and_shape_changes(self):
        result = diagnose_with_probe(D.ProbeStop('probe_plan'))
        for bad in ('/private/SECRET', 'probe_installed_other', 1, None):
            with self.subTest(bad_type=type(bad).__name__):
                invalid = dict(result, phase=bad)
                with self.assertRaises(ValueError): D.closed_json(invalid)
        invalid = dict(result, extra='SECRET')
        with self.assertRaises(ValueError): D.closed_json(invalid)
        self.assertLessEqual(len(D.closed_json(result).encode()), D.MAX_OUTPUT)


if __name__ == '__main__': unittest.main()
