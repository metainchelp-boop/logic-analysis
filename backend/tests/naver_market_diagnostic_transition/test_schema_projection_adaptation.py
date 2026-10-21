"""New schema projection seams only; no existing TestCase method execution."""
import hashlib
import unittest
import test_sources as registry
import test_systemd_boundary as boundary
import test_current_guard as guard_fixture
import transition as T
import systemd_boundary as S
import strict_receiver as R


class ProjectionAdaptationTests(unittest.TestCase):
    def test_timer_fixture_never_fills_or_silently_drops_status(self):
        timer=boundary.state(T.OLD_TIMER)
        self.assertEqual(set(timer),set(S.TIMER_PROPERTIES))
        self.assertNotIn('ExecMainStatus',S.snapshot(boundary.encode(timer,kind='timer'),kind='timer'))
        injected=boundary.state(T.OLD_TIMER,ExecMainStatus='bad')
        self.assertEqual(injected['ExecMainStatus'],'bad')
        with self.assertRaises(AssertionError):boundary.encode(injected,kind='timer')
        with self.assertRaises(AssertionError):boundary.encode(timer)
        service=boundary.state(T.OLD_READER)
        self.assertEqual(set(S.snapshot(boundary.encode(service))),set(S.PROPERTIES))

    def test_command_fixture_selects_only_fixed_timer_properties(self):
        commands=boundary.Commands(dict(coordinator='fixture.service',reader='fixture-reader.service'))
        def argv(unit,properties):return ['/usr/bin/systemctl','show',unit]+['--property='+p for p in properties]
        code,body=commands(argv(T.OLD_TIMER,S.TIMER_PROPERTIES),limit=4096,timeout=8)
        self.assertEqual(code,0);self.assertNotIn('ExecMainStatus',S.snapshot(body,kind='timer'))
        code,body=commands(argv(T.OLD_READER,S.PROPERTIES),limit=4096,timeout=8)
        self.assertEqual(S.snapshot(body)['ExecMainStatus'],'0')
        with self.assertRaises(AssertionError):commands(argv(T.OLD_TIMER,S.PROPERTIES),limit=4096,timeout=8)
        with self.assertRaises(AssertionError):commands(argv(T.OLD_READER,S.TIMER_PROPERTIES),limit=4096,timeout=8)

    def test_owned_mask_fixture_preserves_invocation_specific_refusal(self):
        commands=boundary.Commands(dict(coordinator='fixture.service',reader='fixture-reader.service'))
        commands.quiesce()
        for unit in (T.OLD_READER,T.OLD_COORDINATOR):
            self.assertEqual(commands.snapshots[unit]['FragmentPath'],S.MASK_ROOT+'/'+unit)
        f=guard_fixture.CurrentGuardTests();f.setUp();self.addCleanup(f.doCleanups)
        f.guard.capture();f.calls.clear()
        f.reader.update(LoadState='masked',UnitFileState='masked-runtime',
            FragmentPath=S.MASK_ROOT+'/'+T.OLD_READER,InvocationID='8'*32)
        with self.assertRaisesRegex(T.Invalid,'CURRENT_FAILURE_CHANGED'):f.guard(require_failure=True)
        self.assertFalse(any(a[0]=='/usr/bin/journalctl' for a in f.calls))

    def test_nineteen_source_registry_and_transport_pin_chain_exact(self):
        self.assertEqual(len(registry.validate_layout()),19)
        modules,sources,host=registry.delivery_materials()
        release=R.register_release(delivery_source=host,renderer_source=registry.renderer_source(),modules=modules,sources=sources)
        self.assertEqual(release['modules']['systemd_boundary'],hashlib.sha256(modules['systemd_boundary']).hexdigest())
        self.assertEqual(release['modules']['current_guard'],hashlib.sha256(modules['current_guard']).hexdigest())
        self.assertEqual(release['delivery_sha256'],hashlib.sha256(host).hexdigest())
        self.assertEqual(registry.FILES['provisioning']['sha256'],'651927b4a93bc68f57dfac3645bd9a2c4fbdf4a0f0ec32beef94389e40a19ad0')


if __name__=='__main__':unittest.main()
