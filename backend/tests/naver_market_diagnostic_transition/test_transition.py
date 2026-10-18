import copy
from contextlib import contextmanager
from pathlib import Path
import types
import unittest
import transition as T

import test_sources as portable_sources


def sources():
    return portable_sources.transition_sources()


class Port:
    """No host IO. Simulates interrupt boundaries, exact effects and ownership."""
    def __init__(self, *, fail_before=None, fail_after=None):
        self.history = []
        self.events = []
        self.started = 0
        self.fail_before, self.fail_after = fail_before, fail_after
        self.locked = False
        self.timer = True
        self.masked = False
        self.installed = False
        self.original = b'original-receipt-units-script-and-bundle'
        self.drift = False
        self.busy = False
        self.observation = None

    @contextmanager
    def lock(self):
        if self.locked:
            T.fail('BUSY')
        self.locked = True
        try:
            yield
        finally:
            self.locked = False

    def read(self, plan_hash):
        return copy.deepcopy(self.history)

    def append(self, plan_hash, event):
        self.history.append(copy.deepcopy(event))

    def preflight(self, plan, files):
        if self.busy or self.drift:
            T.fail('PREFLIGHT')

    def recovery_preflight(self, plan, files, history):
        if self.drift:
            T.fail('DRIFT')

    def perform(self, action, plan, files):
        if self.fail_before == action:
            raise InterruptedError('private failure text must never enter history')
        self.events.append(action)
        if action == 'timer_stop': self.timer = False
        elif action == 'mask_original': self.masked = True
        elif action == 'quiescence_verify' and self.busy: T.fail('BUSY')
        elif action == 'install_new': self.installed = True
        elif action == 'run_once':
            if self.timer or not self.masked or not self.installed:
                T.fail('NOT_QUIESCED')
            self.started += 1
        elif action == 'remove_new': self.installed = False
        elif action == 'unmask_owned': self.masked = False
        elif action == 'timer_restore': self.timer = True
        elif action == 'restored_verify':
            if not self.timer or self.masked or self.installed:
                T.fail('NOT_RESTORED')
        if self.fail_after == action:
            raise KeyboardInterrupt('simulate process interruption after effect')
        if action == 'observe':
            return self.observation or dict(reader=plan['reader'],
                invocation_id='a' * 32, status='source_limit', limit_issue='rows', exit_status=1)


class TransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = sources()
        cls.previous = {key: T.sha(key.encode()) for key in T.PROOF_KEYS}
        cls.plan, cls.files = T.compile_plan(apply_id='1' * 32, rollback_id='2' * 32,
            sources=cls.sources, previous=cls.previous)

    def controller(self, port):
        return T.Controller(port, sources=self.sources)

    def restore(self, controller):
        return controller.rollback(self.plan, self.files,
            apply_id=self.plan['apply_id'], rollback_id=self.plan['rollback_id'])

    def test_derived_sandbox_and_coordinator_are_exactly_reversible(self):
        h = types.ModuleType('original_helper')
        exec(compile(self.sources['helper'], '<original>', 'exec'), h.__dict__)
        old_root = str(h.INSTALL / T.PROFILE['ops_commit'])
        new_root = self.plan['code_root']
        source = self.files[new_root + '/naver_market_coordinate.py']
        self.assertEqual(source.replace(self.plan['reader'].encode(), T.OLD_READER.encode()),
                         h._coordinator_source(T.PROFILE, 'market').encode())
        coordinator = self.files[T.UNIT_ROOT + '/' + self.plan['coordinator']]
        coordinator = coordinator.replace((new_root + '/naver_market_coordinate.py').encode(),
            (old_root + '/naver_market_coordinate.py').encode()).replace(
            (old_root + ' ' + new_root).encode(), old_root.encode())
        self.assertEqual(coordinator, h._unit(T.PROFILE, 'market'))
        reader = self.files[T.UNIT_ROOT + '/' + self.plan['reader']]
        reader = reader.replace(self.plan['coordinator'].encode(), T.OLD_COORDINATOR.encode())
        reader = reader.replace((new_root + '/naver_market_export.py').encode(),
                                (old_root + '/naver_market_export.py').encode())
        reader = reader.replace((old_root + ' ' + new_root).encode(), old_root.encode())
        reader = reader.replace(self.plan['output_root'].encode(), str(h.OUTPUTS['market']).encode())
        self.assertEqual(reader, h._reader_unit(T.PROFILE, 'market'))
        self.assertNotIn(b'/var/lib/metainc/naver-market-source', b''.join(self.files.values()))

    def test_real_shape_ids_different_pairs_produce_distinct_bound_artifacts(self):
        import uuid
        apply_id, rollback_id = uuid.uuid4().hex, uuid.uuid4().hex
        p, f = T.compile_plan(apply_id=apply_id, rollback_id=rollback_id,
                              sources=self.sources, previous=self.previous)
        self.assertNotEqual(p['reader'], self.plan['reader'])
        self.assertNotEqual(p['manifest'], self.plan['manifest'])
        self.assertEqual(T.validate_plan(p, f, sources=self.sources), T.sha(T.canonical(p)))
        # Format only: these are local UUIDs, never claimed as actual release IDs.

    def test_ids_and_hash_types_are_closed(self):
        for bad in (None, True, 1, '0'*32, 'a'*31, 'A'*32, '../x', 'a'*32+'\n'):
            with self.subTest(bad=bad), self.assertRaises(T.Invalid):
                T.compile_plan(apply_id=bad, rollback_id='2'*32,
                               sources=self.sources, previous=self.previous)
        with self.assertRaises(T.Invalid):
            T.compile_plan(apply_id='1'*32, rollback_id='1'*32,
                           sources=self.sources, previous=self.previous)
        for bad in (True, 1, None, 'a'*63):
            p = dict(self.previous); p[next(iter(p))] = bad
            with self.assertRaises(T.Invalid):
                T.compile_plan(apply_id='1'*32, rollback_id='2'*32, sources=self.sources, previous=p)

    def test_source_and_plan_drift_rejected_before_port_call(self):
        for key in self.sources:
            wrong = dict(self.sources); wrong[key] += b'\n'
            with self.assertRaises(T.Invalid):
                T.compile_plan(apply_id='1'*32, rollback_id='2'*32, sources=wrong, previous=self.previous)
        for key, value in (('reader', T.OLD_READER), ('interpreter', '/usr/bin/python3'),
                           ('database_content_writes', True), ('controller_start_attempts_max', 2)):
            p = copy.deepcopy(self.plan); p[key] = value
            port = Port()
            with self.assertRaises(T.Invalid): self.controller(port).apply(p, self.files)
            self.assertEqual(port.events, [])

    def test_canonical_type_confusion_cannot_create_another_attempt_hash(self):
        variants = [('version', True), ('controller_start_attempts_max', True),
                    ('database_content_writes', 0), ('new_files_mode', float(0o644)),
                    ('original_units', tuple(self.plan['original_units']))]
        for key, value in variants:
            p = copy.deepcopy(self.plan); p[key] = value
            port = Port()
            with self.subTest(key=key), self.assertRaises(T.Invalid):
                self.controller(port).apply(p, self.files)
            self.assertEqual(port.events, [])
            self.assertEqual(port.history, [])
        f = dict(self.files); name = next(iter(f)); f[name] = bytearray(f[name])
        with self.assertRaises(T.Invalid): T.validate_plan(self.plan, f, sources=self.sources)
        p = copy.deepcopy(self.plan); p['original_timer_required']['active'] = 1
        with self.assertRaises(T.Invalid): T.validate_plan(p, self.files, sources=self.sources)

    def test_apply_and_pair_restore_keep_original_and_report_not_product_success(self):
        port = Port(); controller = self.controller(port)
        old = port.original
        result = controller.apply(self.plan, self.files)
        self.assertEqual(result['observation']['limit_issue'], 'rows')
        self.assertFalse(result['product_export_verified'])
        self.assertTrue(result['rollback_required'])
        self.assertEqual(port.started, 1)
        self.assertEqual(T.validate_history(port.history, self.plan), 'apply')
        restored = self.restore(controller)
        self.assertTrue(restored['restored'])
        self.assertTrue(restored['natural_timer_catchup_possible'])
        self.assertFalse(restored['product_export_verified'])
        self.assertEqual(port.original, old)
        self.assertEqual(T.validate_history(port.history, self.plan), 'restored')

    def test_every_before_after_apply_interrupt_is_rollback_only(self):
        for when in ('before', 'after'):
            for action in T.STEPS:
                with self.subTest(when=when, action=action):
                    port = Port(**{'fail_' + when: action})
                    controller = self.controller(port)
                    with self.assertRaises(BaseException): controller.apply(self.plan, self.files)
                    self.assertLessEqual(port.started, 1)
                    self.assertNotIn(b'private failure', T.canonical(port.history))
                    with self.assertRaises(T.Invalid): controller.apply(self.plan, self.files)
                    port.fail_before = port.fail_after = None
                    self.restore(controller)
                    self.assertEqual(T.validate_history(port.history, self.plan), 'restored')
                    self.assertLessEqual(port.started, 1)

    def test_every_cleanup_interruption_can_only_resume_owned_cleanup(self):
        for when in ('before', 'after'):
            for action in T.CLEANUP:
                with self.subTest(when=when, action=action):
                    port = Port(); controller = self.controller(port)
                    controller.apply(self.plan, self.files)
                    setattr(port, 'fail_' + when, action)
                    with self.assertRaises(BaseException): self.restore(controller)
                    self.assertEqual(T.validate_history(port.history, self.plan), 'rollback')
                    with self.assertRaises(T.Invalid): controller.apply(self.plan, self.files)
                    port.fail_before = port.fail_after = None
                    self.restore(controller)
                    self.assertEqual(port.started, 1)
                    with self.assertRaises(T.Invalid): self.restore(controller)

    def test_concurrency_and_original_busy_refuse_before_mutation(self):
        for key in ('locked', 'busy', 'drift'):
            port = Port(); setattr(port, key, True)
            with self.assertRaises(T.Invalid): self.controller(port).apply(self.plan, self.files)
            self.assertEqual(port.events, [])
            self.assertEqual(port.history, [])

    def test_drift_recovery_refuses_before_cleanup(self):
        port = Port(); controller = self.controller(port)
        controller.apply(self.plan, self.files)
        count = len(port.events)
        port.drift = True
        with self.assertRaises(T.Invalid): self.restore(controller)
        self.assertEqual(len(port.events), count)

    def test_mismatched_pair_and_invented_history_refuse(self):
        port = Port(); controller = self.controller(port)
        controller.apply(self.plan, self.files)
        count = len(port.events)
        with self.assertRaises(T.Invalid):
            controller.rollback(self.plan, self.files, apply_id='3'*32, rollback_id='2'*32)
        for bad in ([{'action':'rollback','state':'intent'}],
                    port.history + [{'action':'run_once','state':'intent'}],
                    port.history + [{'action':'apply','state':'done','raw':'secret'}]):
            port.history = copy.deepcopy(bad)
            with self.assertRaises(T.Invalid): self.restore(controller)
        self.assertEqual(len(port.events), count)

    def test_observation_bound_to_reader_invocation_and_exact_enum(self):
        base = dict(reader=self.plan['reader'], invocation_id='a'*32,
                    status='source_limit', limit_issue='rows', exit_status=1)
        for issue in T.ISSUES:
            self.assertEqual(T.closed_observation(dict(base, limit_issue=issue), self.plan)['limit_issue'], issue)
        for key, value in (('reader', T.OLD_READER), ('invocation_id','0'*32),
                ('status','success'), ('limit_issue','private'), ('limit_issue',True),
                ('exit_status',True), ('exit_status',0)):
            with self.assertRaises(T.Invalid): T.closed_observation(dict(base, **{key:value}), self.plan)
        with self.assertRaises(T.Invalid): T.closed_observation(dict(base, raw='secret'), self.plan)

    def test_successful_diagnostic_still_requires_restore_and_real_product_validation(self):
        port = Port(); port.observation = dict(reader=self.plan['reader'],
            invocation_id='b'*32, status='export_succeeded', limit_issue=None, exit_status=0)
        result = self.controller(port).apply(self.plan, self.files)
        self.assertFalse(result['product_export_verified'])
        self.assertTrue(result['rollback_required'])


if __name__ == '__main__': unittest.main()
