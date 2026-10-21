import copy
from pathlib import Path
import types
import unittest
from unittest.mock import patch, MagicMock
import entrypoint as E
import transition as T
import test_transition as compiler_fixture


class EntrypointTests(unittest.TestCase):
    """Actual compiler, fixed assembly with host seams; no service/DB calls."""
    def setUp(self):
        self.sources = compiler_fixture.sources()
        self.proofs = {k: 'a' * 64 for k in T.PROOF_KEYS}
        self.value = dict(version=1, action='apply', apply_id='3' * 32, rollback_id='4' * 32)
        self.plan, self.files = T.compile_plan(apply_id=self.value['apply_id'],
            rollback_id=self.value['rollback_id'], sources=self.sources, previous=self.proofs)
        self.events = []
        self.prepared = types.SimpleNamespace(ownership_root=Path('/private/ownership'),
            ledger_root=Path('/private/ledger'), output_identity=[1,2,3,4,5],
            guard_proof={'closed': True}, prepared_sha256='b' * 64)
        self.guard = MagicMock()
        self.guard.capture.side_effect = lambda: self.record('guard', self.prepared.guard_proof)
        self.systemd = MagicMock()
        self.systemd.original_preflight.side_effect = lambda: self.record('original_preflight')
        self.publication = MagicMock()
        self.publication.prepare.side_effect = lambda: self.record('publication')
        self.port = MagicMock();self.ledger = MagicMock();self.controller = MagicMock()
        self.controller.apply.side_effect = lambda *a: self.record('apply',dict(
            plan_sha256=T.sha(T.canonical(self.plan)), rollback_required=True, product_export_verified=False,
            observation=dict(reader=self.plan['reader'], invocation_id='f' * 32,
                status='source_limit', limit_issue='rows', exit_status=1)))
        self.controller.rollback.side_effect = lambda *a,**kw: self.record('rollback',dict(
            plan_sha256=T.sha(T.canonical(self.plan)), restored=True,
            natural_timer_catchup_possible=True, product_export_verified=False))
        replacements = [patch.object(E.sys, 'platform', 'linux'), patch.object(E.os, 'geteuid', return_value=0),
            patch.object(E.B, 'collect', side_effect=lambda s:self.record('baseline',(self.proofs,types.SimpleNamespace(runtime_uid=65534)))),
            patch.object(E.S, 'Systemd', return_value=self.systemd),
            patch.object(E.G, 'CurrentGuard', return_value=self.guard),
            patch.object(E.D, 'prepare', side_effect=lambda *a,**kw:self.record('prepare',self.prepared)),
            patch.object(E.D, 'load', side_effect=lambda *a,**kw:self.record('load',self.prepared)),
            patch.object(E.P, 'Publication', return_value=self.publication),
            patch.object(E.J, 'Ledger', return_value=self.ledger),
            patch.object(E.H, 'HostPort', return_value=self.port),
            patch.object(E.T, 'Controller', return_value=self.controller)]
        self.mocks = []
        for p in replacements: self.mocks.append(p.start());self.addCleanup(p.stop)

    def record(self,event,value=None): self.events.append(event);return value
    def run_host(self): return E.run(self.value,sources=self.sources,baseline_sources={'pinned':'test seam'})

    def test_apply_composition_orders_all_preconditions_before_timer_controller(self):
        result = self.run_host()
        self.assertEqual(self.events,['baseline','original_preflight','guard','prepare','publication','apply'])
        E.G.CurrentGuard.assert_called_once_with(self.proofs)
        self.assertNotIn('command',E.S.Systemd.call_args.kwargs)
        self.assertIs(E.H.HostPort.call_args.kwargs['current_guard'],self.guard)
        self.assertIs(E.H.HostPort.call_args.kwargs['systemd'],self.systemd)
        self.assertFalse(result['original_export_success_verified'])
        self.assertFalse(result['product_deployed'])
        self.assertFalse(result['ads_written'])

    def test_public_projection_excludes_reader_and_invocation_identifiers(self):
        result = self.run_host();raw = T.canonical(result)
        self.assertNotIn(b'invocation',raw);self.assertNotIn(b'reader',raw)
        self.assertNotIn(('f'*32).encode(),raw)
        self.assertEqual(result['result']['observation'],dict(status='source_limit',limit_issue='rows',exit_status=1))

    def test_request_paths_callbacks_unknown_actions_and_aliases_reject_before_host_reads(self):
        for change in [dict(callback='yes'),dict(path='/tmp'),dict(action='retry'),dict(version=True),
                       dict(apply_id='0'*32),dict(rollback_id='3'*32)]:
            with self.subTest(change=change):
                value={**self.value,**change}
                with self.assertRaises(T.Invalid):E.run(value,sources=self.sources,baseline_sources={})
        self.assertEqual(self.events,[])

    def test_platform_and_root_boundaries_fail_before_baseline_or_preparation(self):
        for module,name,value in [(E.sys,'platform','darwin'),(E.os,'geteuid',lambda:1000)]:
            with patch.object(module,name,value),self.assertRaisesRegex(T.Invalid,'ENTRYPOINT_HOST'):
                self.run_host()
        self.assertEqual(self.events,[])

    def test_changed_exporter_source_rejected_before_any_systemd_or_preparation(self):
        self.sources['market']+=b'changed'
        with self.assertRaisesRegex(T.Invalid,'SOURCES'):self.run_host()
        self.assertEqual(self.events,['baseline']);E.S.Systemd.assert_not_called()

    def test_unsupported_original_unit_layout_does_not_provision(self):
        self.systemd.original_preflight.side_effect=T.Invalid('SYSTEMD_UNIT_PATH')
        with self.assertRaisesRegex(T.Invalid,'SYSTEMD_UNIT_PATH'):self.run_host()
        E.D.prepare.assert_not_called();self.guard.capture.assert_not_called()

    def test_missing_current_failure_does_not_provision_or_install(self):
        self.guard.capture.side_effect=T.Invalid('CURRENT_FAILURE_RESULT')
        with self.assertRaisesRegex(T.Invalid,'CURRENT_FAILURE_RESULT'):self.run_host()
        E.D.prepare.assert_not_called();self.publication.prepare.assert_not_called()

    def test_preparation_or_publication_interrupt_has_no_timer_controller_effect(self):
        E.D.prepare.side_effect=InterruptedError()
        with self.assertRaises(InterruptedError):self.run_host()
        self.controller.apply.assert_not_called()
        E.D.prepare.side_effect=lambda *a,**kw:self.prepared
        self.publication.prepare.side_effect=InterruptedError()
        with self.assertRaises(InterruptedError):self.run_host()
        self.controller.apply.assert_not_called()

    def test_ambiguous_apply_is_not_automatically_retried_or_killed(self):
        self.controller.apply.side_effect=T.Invalid('SYSTEMD_COMMAND_AMBIGUOUS')
        with self.assertRaisesRegex(T.Invalid,'SYSTEMD_COMMAND_AMBIGUOUS'):self.run_host()
        self.controller.apply.assert_called_once();self.controller.rollback.assert_not_called()

    def test_explicit_paired_rollback_loads_preparation_and_restores_bound_guard(self):
        self.value['action']='rollback';result=self.run_host()
        self.assertEqual(self.events,['baseline','load','rollback'])
        E.D.prepare.assert_not_called();self.guard.capture.assert_not_called()
        self.publication.prepare.assert_not_called()
        E.G.CurrentGuard.assert_called_once_with(self.proofs,proof=self.prepared.guard_proof)
        self.assertEqual(self.controller.rollback.call_args.kwargs,
            dict(apply_id='3'*32,rollback_id='4'*32))
        self.assertTrue(result['result']['restored']);self.assertFalse(result['original_export_success_verified'])

    def test_unknown_preparation_refuses_rollback_without_unit_actions(self):
        self.value['action']='rollback';E.D.load.side_effect=T.Invalid('PROVISION_CHANGED')
        with self.assertRaisesRegex(T.Invalid,'PROVISION_CHANGED'):self.run_host()
        E.H.HostPort.assert_not_called();self.systemd.original_preflight.assert_not_called()
        self.controller.rollback.assert_not_called()


if __name__=='__main__':unittest.main()
