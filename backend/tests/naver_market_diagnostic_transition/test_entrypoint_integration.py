"""New entrypoint/provisioning/transaction composition on private temp files.

Real compiler, preparation, ownership, publication, ledger and controller. Only
OS identity/current-deployment/systemd/output-GID seams model Linux; no actual
root/systemd, Docker, DB, production path or network is touched. Fixture setup
is reused without collecting or rerunning any previous fixture test methods.
"""
import os
from pathlib import Path
import types
import unittest
from unittest.mock import patch
import entrypoint as E
import provisioning as Q
import transition as T
import publication as P
import journal as J
import host_port as H
import test_provisioning as preparation_fixture
import test_host_port as manager_fixture


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.f = preparation_fixture.PreparationTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.plan, self.files, self.sources = self.f.plan, self.f.files, self.f.sources
        self.manager = manager_fixture.FakeManager(self.plan)
        self.guard_calls = []
        outer = self
        class Guard:
            def __init__(self, previous, *, proof=None):
                if previous != outer.plan['previous']: T.fail('TEST_BASELINE')
                if proof is not None and proof != outer.f.guard: T.fail('TEST_PROOF')
            def capture(self): return outer.f.guard
            def __call__(self, *, require_failure):
                outer.guard_calls.append(require_failure)
                return dict(operating_source=T.OPERATING_SOURCE,
                    operating_operation=T.OPERATING_OPERATION, current_source_verified=True,
                    source_limit_invocation_verified=require_failure)
        real_publication, real_ledger = P.Publication, J.Ledger
        def publication(*args, **kwargs):
            return real_publication(*args, **kwargs, owner=self.f.uid, group=self.f.gid)
        def ledger(*args, **kwargs): return real_ledger(*args, **kwargs, owner=self.f.uid)
        def output(port, context, *, empty):
            # GID 10001 production ownership is qualified by Linux/root fixture,
            # not by chown on this Mac. All other real directory checks remain.
            path = Path(port.plan['output_root']); info = path.lstat()
            if (path.resolve() != path or P.inode(info) != port.output_identity
                    or info.st_uid != context.runtime_uid or info.st_gid != self.f.gid
                    or info.st_mode & 0o777 != 0o750): T.fail('TEST_OUTPUT')
            if empty and list(path.iterdir()): T.fail('TEST_OUTPUT_NOT_EMPTY')
        patches = [patch.object(E, 'os', types.SimpleNamespace(geteuid=lambda:0)),
            patch.object(E, 'sys', types.SimpleNamespace(platform='linux')),
            patch.object(E.B, 'collect', return_value=(self.plan['previous'],
                types.SimpleNamespace(runtime_uid=self.f.uid))),
            patch.object(E.S, 'Systemd', return_value=self.manager),
            patch.object(E.G, 'CurrentGuard', Guard),
            patch.object(E.P, 'Publication', side_effect=publication),
            patch.object(E.J, 'Ledger', side_effect=ledger),
            patch.object(H.HostPort, '_output', output)]
        for p in patches: p.start(); self.addCleanup(p.stop)
        self.old = self.f.root / 'data/original.bundle'
        self.old.write_bytes(b'unchanged original evidence')

    def run_action(self, action, **changes):
        value = dict(version=1, action=action, apply_id=self.plan['apply_id'],
                     rollback_id=self.plan['rollback_id']); value.update(changes)
        return E.run(value, sources=self.sources, baseline_sources={})

    def test_new_entrypoint_complete_pair_preserves_private_output_and_originals(self):
        applied = self.run_action('apply')
        self.assertEqual(applied['result']['observation'],
            dict(status='source_limit', limit_issue='rows', exit_status=1))
        self.assertNotIn('invocation_id', str(applied))
        self.assertFalse(applied['original_export_success_verified'])
        evidence = Path(self.plan['output_root']) / 'bundle.json'
        evidence.write_bytes(b'opaque private diagnostic evidence')
        restored = self.run_action('rollback')
        self.assertTrue(restored['result']['restored'])
        self.assertEqual(applied['preparation_sha256'], restored['preparation_sha256'])
        self.assertEqual(evidence.read_bytes(), b'opaque private diagnostic evidence')
        self.assertEqual(self.old.read_bytes(), b'unchanged original evidence')
        self.assertEqual(self.manager.started, 1)
        self.assertTrue(self.manager.timer)
        self.assertFalse(any(Path(p).exists() for p in self.files))
        self.assertEqual(self.guard_calls, [True, True, True, False, False])
        with self.assertRaisesRegex(T.Invalid, 'PROVISION_EXISTS'): self.run_action('apply')
        self.assertEqual(self.manager.started, 1)

    def test_entrypoint_partial_publication_recovers_from_saved_preparation(self):
        original = os.link
        def interrupt(source, target, **kwargs):
            original(source, target, **kwargs)
            if str(target) in self.files: raise KeyboardInterrupt()
        with patch.object(P.os, 'link', interrupt), self.assertRaises(KeyboardInterrupt):
            self.run_action('apply')
        self.assertFalse(self.manager.timer)
        self.assertEqual(self.manager.started, 0)
        result = self.run_action('rollback')
        self.assertTrue(result['result']['restored'])
        self.assertTrue(self.manager.timer)
        self.assertFalse(any(Path(p).exists() for p in self.files))
        self.assertEqual(self.manager.started, 0)

    def test_wrong_pair_recovery_cannot_borrow_preparation_or_change_live_state(self):
        self.run_action('apply')
        with self.assertRaises(T.Invalid): self.run_action('rollback', rollback_id='9' * 32)
        self.assertFalse(self.manager.timer)
        self.assertTrue(all(Path(p).exists() for p in self.files))
        self.run_action('rollback')
        self.assertTrue(self.manager.timer)
        self.assertEqual(self.manager.started, 1)


if __name__ == '__main__': unittest.main()
