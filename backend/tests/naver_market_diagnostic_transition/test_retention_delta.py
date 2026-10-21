"""New retention/paired-cleanup delta only; command seam, no host operations."""
import copy
import json
from pathlib import Path
import unittest
import systemd_boundary as S
import transition as T


def sources():
    from test_sources import transition_sources
    return transition_sources()


def state(unit, **updates):
    value = dict(LoadState='loaded', UnitFileState='static', FragmentPath=T.UNIT_ROOT+'/'+unit,
        DropInPaths='', Job='', Result='success', ExecMainStatus='0',
        ActiveState='inactive', SubState='dead', InvocationID='')
    value.update(updates)
    return value


class Commands:
    def __init__(self, plan):
        self.plan, self.calls, self.journal = plan, [], b''
        self.states = {plan[k]: state(plan[k]) for k in ('coordinator', 'reader')}
        self.on_show, self.on_stop, self.on_journal = None, None, None
        self.show_counts = {}

    def completed(self):
        for index, value in enumerate(self.states.values()):
            value.update(ActiveState='active', SubState='exited', InvocationID=str(index+1)*32)

    def __call__(self, argv, *, limit, timeout):
        self.calls.append(list(argv))
        if argv[:2] == ['/usr/bin/systemctl', 'show']:
            unit = argv[2]
            self.show_counts[unit] = self.show_counts.get(unit, 0) + 1
            if self.on_show: self.on_show(unit, self.show_counts[unit])
            value = self.states[unit]
            assert argv[3:] == ['--property='+p for p in S.PROPERTIES]
            return 0, ('\n'.join(p+'='+value[p] for p in S.PROPERTIES)+'\n').encode()
        if argv[0] == '/usr/bin/journalctl':
            if self.on_journal: self.on_journal()
            return 0, self.journal
        if argv[:2] == ['/usr/bin/systemctl', 'stop']:
            if self.on_stop: return self.on_stop(argv[2:])
            for unit in argv[2:]: self.states[unit].update(ActiveState='inactive', SubState='dead')
            return 0, b''
        raise AssertionError('Unexpected command in isolated delta')

    def stops(self): return [c for c in self.calls if c[:2] == ['/usr/bin/systemctl', 'stop']]


class RetentionDeltaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = sources()
        cls.plan, cls.files = T.compile_plan(apply_id='a'*32, rollback_id='b'*32,
            sources=cls.sources, previous={k: 'c'*64 for k in T.PROOF_KEYS})

    def setUp(self):
        self.command = Commands(self.plan)
        self.system = S.Systemd(self.plan, self.files, sources=self.sources, command=self.command)

    def test_only_derived_units_retain_and_manifest_binds_exact_bytes(self):
        for key in ('coordinator', 'reader'):
            path = T.UNIT_ROOT+'/'+self.plan[key]
            body = self.files[path]
            self.assertEqual(body.count(b'Type=oneshot\nRemainAfterExit=yes\n'), 1)
            self.assertEqual(self.plan['manifest'][path], T.sha(body))
            self.assertNotIn(b'ExecStop=', body)
            self.assertIn(b'ProtectSystem=strict\n', body)
        for path, body in self.files.items():
            if not path.endswith('.service'): self.assertNotIn(b'RemainAfterExit=', body)
        broken = dict(self.files)
        path = T.UNIT_ROOT+'/'+self.plan['reader']
        broken[path] = broken[path].replace(b'RemainAfterExit=yes\n', b'')
        with self.assertRaises(T.Invalid): T.validate_plan(self.plan, broken, sources=self.sources)

    def test_completed_observe_preserves_exact_invocation_without_export_claim(self):
        self.command.completed()
        observed = self.system.observe()
        self.assertEqual(observed['invocation_id'], '2'*32)
        self.assertEqual(observed['status'], 'diagnostic_unavailable')
        self.assertIsNone(observed['limit_issue'])
        self.assertEqual(observed['exit_status'], 0)
        journal = [c for c in self.command.calls if c[0] == '/usr/bin/journalctl']
        self.assertEqual(len(journal), 1)
        self.assertIn('_SYSTEMD_INVOCATION_ID='+'2'*32, journal[0])
        self.assertEqual(self.command.stops(), [])

    def test_failed_source_limit_observation_remains_exact(self):
        unit = self.plan['reader']
        self.command.states[unit].update(ActiveState='failed', SubState='failed',
            Result='exit-code', ExecMainStatus='1', InvocationID='d'*32)
        self.command.journal = json.dumps(dict(_SYSTEMD_UNIT=unit,
            _SYSTEMD_INVOCATION_ID='d'*32, MESSAGE=json.dumps(dict(status='failed',
                code='SOURCE_LIMIT', limit_issue='rows')))).encode()
        value = self.system.observe()
        self.assertEqual((value['status'], value['limit_issue'], value['exit_status']), ('source_limit','rows',1))

    def test_completed_observe_rejects_contradictory_or_executing_context(self):
        cases = [dict(SubState='running'), dict(Job='7'), dict(Result='exit-code'),
            dict(ExecMainStatus='1'), dict(InvocationID=''), dict(InvocationID='0'*32),
            dict(DropInPaths='/foreign.conf'), dict(FragmentPath='/foreign.service'),
            dict(UnitFileState='transient'), dict(LoadState='masked')]
        for update in cases:
            with self.subTest(update=update):
                self.setUp(); self.command.completed()
                self.command.states[self.plan['reader']].update(update)
                with self.assertRaises(T.Invalid): self.system.observe()
                self.assertFalse(any(c[0] == '/usr/bin/journalctl' for c in self.command.calls))

    def test_observe_refuses_replaced_invocation_after_journal(self):
        self.command.completed()
        self.command.on_journal = lambda: self.command.states[self.plan['reader']].update(InvocationID='e'*32)
        with self.assertRaisesRegex(T.Invalid, 'DIAGNOSTIC_CONTEXT_CHANGED'): self.system.observe()

    def test_completed_pair_stops_only_exact_new_units_then_requires_idle(self):
        self.command.completed(); self.system.cleanup_idle()
        self.assertEqual(self.command.stops(), [['/usr/bin/systemctl','stop',self.plan['coordinator'],self.plan['reader']]])
        self.assertTrue(all(S.idle(v) for v in self.command.states.values()))
        self.assertFalse(any(old in c for c in self.command.stops()
                             for old in (T.OLD_COORDINATOR,T.OLD_READER,T.OLD_TIMER)))
        self.assertTrue(all(n == 3 for n in self.command.show_counts.values()))

    def test_cleanup_checks_both_before_stop_and_rejects_mixed_or_foreign_state(self):
        for update in [dict(SubState='running'), dict(Result='exit-code'), dict(ExecMainStatus='1'),
            dict(Job='9'), dict(InvocationID=''), dict(InvocationID='0'*32),
            dict(DropInPaths='/foreign.conf'), dict(FragmentPath='/foreign.service'),
            dict(LoadState='not-found'), dict(UnitFileState='transient')]:
            with self.subTest(update=update):
                self.setUp(); self.command.completed()
                self.command.states[self.plan['reader']].update(update)
                with self.assertRaises(T.Invalid): self.system.cleanup_idle()
                self.assertEqual(self.command.stops(), [])

    def test_cleanup_changed_second_snapshot_blocks_stop(self):
        self.command.completed()
        def change(unit, number):
            if number == 2: self.command.states[unit]['InvocationID'] = 'e'*32
        self.command.on_show = change
        with self.assertRaisesRegex(T.Invalid, 'DIAGNOSTIC_CONTEXT_CHANGED'): self.system.cleanup_idle()
        self.assertEqual(self.command.stops(), [])

    def test_cleanup_stop_without_idle_effect_cannot_complete(self):
        self.command.completed(); self.command.on_stop = lambda units: (0,b'')
        with self.assertRaisesRegex(T.Invalid, 'DIAGNOSTIC_NOT_IDLE'): self.system.cleanup_idle()
        self.assertEqual(len(self.command.stops()), 1)

    def test_interrupted_cleanup_can_resume_remaining_completed_unit_only(self):
        self.command.completed()
        def partial(units):
            self.command.states[units[0]].update(ActiveState='inactive',SubState='dead')
            raise T.Invalid('SYSTEMD_COMMAND_AMBIGUOUS')
        self.command.on_stop = partial
        with self.assertRaisesRegex(T.Invalid,'SYSTEMD_COMMAND_AMBIGUOUS'): self.system.cleanup_idle()
        self.assertEqual(len(self.command.stops()),1)
        # A later paired rollback may resume cleanup; this never retries apply/start.
        self.command.on_stop = None; self.system.cleanup_idle()
        self.assertEqual(self.command.stops()[-1], ['/usr/bin/systemctl','stop',self.plan['reader']])
        self.assertTrue(all(S.idle(v) for v in self.command.states.values()))
        self.assertFalse(any(c[:2] == ['/usr/bin/systemctl','start'] for c in self.command.calls))

    def test_idle_failed_and_partial_missing_cleanup_stay_readonly(self):
        unit = self.plan['reader']
        self.command.states[unit].update(LoadState='not-found',FragmentPath='',UnitFileState='not-found')
        self.command.states[self.plan['coordinator']].update(ActiveState='failed',SubState='failed',Result='exit-code',ExecMainStatus='1')
        self.system.cleanup_idle(); self.assertEqual(self.command.stops(),[])
        self.command.states[unit].update(ActiveState='active',SubState='exited',InvocationID='a'*32)
        with self.assertRaises(T.Invalid): self.system.cleanup_idle()
        self.assertEqual(self.command.stops(),[])

    def test_completed_unit_cannot_be_started_as_fresh_attempt(self):
        self.command.completed()
        with self.assertRaisesRegex(T.Invalid, 'DIAGNOSTIC_NOT_IDLE'): self.system.new_idle()
        self.system.start_attempted = True
        with self.assertRaisesRegex(T.Invalid, 'DIAGNOSTIC_START_REPLAY'): self.system.start_once()
        self.assertFalse(any(c[:2] == ['/usr/bin/systemctl','start'] for c in self.command.calls))


if __name__ == '__main__': unittest.main()
