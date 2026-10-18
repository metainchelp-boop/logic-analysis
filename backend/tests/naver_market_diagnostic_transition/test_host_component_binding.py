"""Only new component-composition/alias regressions; no operating commands."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
import host_port as H
import transition as T
import test_host_port as fixtures


class ComponentBindingTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.HostTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def create(self, plan=None, files=None):
        f = self.f
        return H.HostPort(f.plan if plan is None else plan, f.files if files is None else files,
            sources=f.src, baseline_sources={}, ledger=f.ledger, publication=f.f.pub,
            systemd=f.manager, output_identity=[1, 2, 3, 4, 5], current_guard=f.port.current_guard)

    def variants(self):
        f = self.f
        other, _ = T.compile_plan(apply_id='5' * 32, rollback_id='6' * 32,
                                 sources=f.src, previous=f.plan['previous'])
        return [(f.ledger, 'plan_hash', T.sha(T.canonical(other))),
                (f.ledger, 'plan', other), (f.f.pub, 'plan_hash', T.sha(T.canonical(other))),
                (f.f.pub, 'files', {}), (f.manager, 'plan', other)]

    def test_constructor_rejects_different_valid_component_plans_before_side_effects(self):
        for component, key, value in self.variants():
            with self.subTest(component=type(component).__name__, key=key), \
                 patch.object(component, key, value), self.assertRaisesRegex(T.Invalid, 'HOST_COMPONENT_BINDING'):
                self.create()
        self.assertEqual(self.f.manager.started, 0)
        self.assertTrue(self.f.manager.timer)
        self.assertFalse(any(Path(p).exists() or Path(p).is_symlink() for p in self.f.f.pub.expected))

    def test_component_drift_is_refused_again_under_lock_before_action(self):
        f = self.f
        for component, key, value in self.variants():
            with f.ledger.lock():
                with patch.object(component, key, value), self.assertRaisesRegex(T.Invalid, 'HOST_COMPONENT_BINDING'):
                    f.port.perform('timer_stop', f.plan, f.files)
            self.assertTrue(f.manager.timer)
        self.assertEqual(f.manager.started, 0)

    def test_caller_mutation_does_not_change_captured_plan_or_files(self):
        f = self.f
        supplied_plan, supplied_files = copy.deepcopy(f.plan), dict(f.files)
        port = self.create(supplied_plan, supplied_files)
        before_plan, before_files = copy.deepcopy(port.plan), dict(port.files)
        supplied_plan['previous']['source_identity_sha256'] = '0' * 64
        supplied_plan['controller_start_attempts_max'] = True
        supplied_files[next(iter(supplied_files))] = b'changed by caller'
        self.assertTrue(T.same(port.plan, before_plan))
        self.assertTrue(T.same(port.files, before_files))
        port._output = lambda context, *, empty: None
        with f.ledger.lock(): port.preflight(f.plan, f.files)
        self.assertEqual(f.manager.started, 0)
        self.assertTrue(f.manager.timer)


if __name__ == '__main__': unittest.main()
