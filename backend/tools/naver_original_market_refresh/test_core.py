"""New refresh boundaries only. Temp ledger is real; host/DB/systemd are seams."""
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import sys

HERE = Path(__file__).resolve().parent
ROOT = next((p for p in HERE.parents if (p/'backend/tools/naver_market_diagnostic_transition').is_dir()), None)
if ROOT is None:
    ROOT = Path('/Users/sinyosub/Documents/Codex/2026-10-07/new-chat-2/work/naver-claude-reference-ops-20261011')
RUNTIME = ROOT/'backend/tools/naver_market_diagnostic_transition'
sys.path.insert(0, str(RUNTIME))
spec = importlib.util.spec_from_file_location('original_market_refresh_core', HERE/'core.py')
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)
T, J, S = C.T, C.J, C.S
RealLedger = J.Ledger


class HelperError(ValueError):
    pass


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()/'ledger'; self.root.mkdir(mode=0o700)
        self.sources = {
            'helper': (ROOT/'backend/tools/naver_saved_exports.py').read_bytes(),
            'product': (ROOT/'backend/naver_product_export.py').read_bytes(),
            'old_market': (ROOT/'backend/naver_market_export.py').read_bytes(),
            'market': (RUNTIME/'diagnostic_market_export.py').read_bytes()}
        self.baseline_sources = dict(exports_binding=(ROOT/'backend/tools/naver_completion_exports.py').read_bytes(),
            exports_helper=self.sources['helper'], product_exporter=self.sources['product'],
            market_exporter=self.sources['old_market'])
        self.proofs = {k:'1'*64 for k in T.PROOF_KEYS}
        self.plan, self.files = T.compile_plan(apply_id=C.RESTORED_APPLY, rollback_id=C.RESTORED_ROLLBACK,
            sources=self.sources, previous=self.proofs)
        self.plan_hash = T.sha(T.canonical(self.plan))
        self.ledger = RealLedger(self.root, self.plan, owner=os.getuid())
        self.history = [dict(action='apply', state='intent', apply_id=C.RESTORED_APPLY,
                             rollback_id=C.RESTORED_ROLLBACK)]
        for step in T.STEPS:
            self.history.append(dict(action=step, state='intent'))
            done = dict(action=step, state='done')
            if step == 'observe':
                done['observation'] = dict(reader=self.plan['reader'], invocation_id='d'*32,
                    status='diagnostic_unavailable', limit_issue=None, exit_status=0)
            self.history.append(done)
        self.history += [dict(action='apply', state='done'), dict(action='rollback', state='intent')]
        for step in T.CLEANUP:
            self.history.extend([dict(action=step, state='intent'), dict(action=step, state='done')])
        self.history.append(dict(action='rollback', state='done'))
        with self.ledger.lock():
            for event in self.history: self.ledger.append(self.plan_hash, event)
        self.refresh_id = 'a'*32
        self.request = dict(version=1, refresh_id=self.refresh_id)
        self.calls, self.guard_calls, self.absent = [], [], []
        self.next_at = int(time.time())+1000
        self.start_code, self.start_error, self.verify_error = 0, None, None
        self.clock_shift, self.next_shift, self.drift = False, False, False
        self.cleaned = True
        self.systemd_calls = 0
        outer = self

        class Systemd:
            def __init__(self, *args, **kwargs): pass
            def show(self, unit):
                return dict(LoadState='not-found' if outer.cleaned else 'loaded', FragmentPath='',
                    DropInPaths='', UnitFileState='not-found', Job='', ActiveState='inactive', SubState='dead')
            def original_preflight(self):
                outer.systemd_calls += 1

        class Guard:
            def __init__(self, *args, **kwargs): pass
            def capture(self):
                outer.guard_calls.append('capture')
                return dict(invocation_id='d'*32)
            def __call__(self, *, require_failure):
                outer.guard_calls.append(require_failure)

        def collect(_):
            proofs = dict(outer.proofs)
            if outer.drift: proofs['source_identity_sha256'] = '2'*64
            return proofs, types.SimpleNamespace(prepared_receipt={'fixed': True})

        def verify(receipt, *, command, require_timers):
            self.assertEqual(receipt, {'fixed': True}); self.assertIs(require_timers, True)
            self.calls.append(('helper.verify',))
            if self.verify_error: raise HelperError(self.verify_error)
            command(['systemctl','show',T.OLD_COORDINATOR,'--property=Result','--property=ExecMainStatus'])
            return dict(state='verified', timers_enabled=True)

        self.helper = types.SimpleNamespace(ExportInstallInvalid=HelperError, verify=verify)
        self.original_helper_loader = C._helper
        self.original_absent = C._absent
        stack = self.enterContext(ExitStack())
        for module, name, value in [
            (C, 'LEDGER_ROOT', self.root), (C, 'RESTORED_PLAN', self.plan_hash),
            (J, 'Ledger', lambda root, plan: RealLedger(root, plan, owner=os.getuid())),
            (C.B, 'collect', collect), (C.G, 'CurrentGuard', Guard), (S, 'Systemd', Systemd),
            (S, 'bounded', self.bounded), (C, '_absent', self.absent.append),
            (C, '_helper', lambda _: self.helper)]:
            stack.enter_context(patch.object(module, name, value))

    def bounded(self, argv, *, limit, timeout):
        self.assertLessEqual(limit, 32768); self.assertLessEqual(timeout, 75)
        self.calls.append(tuple(argv))
        if argv == C.NEXT:
            n = sum(x == tuple(C.NEXT) for x in self.calls)
            epoch = self.next_at + (1 if self.next_shift and n > 1 else 0)
            return 0, ('t %d\n' % (epoch * 1_000_000)).encode()
        if argv == C.START:
            folder = self.root/('refresh-'+self.refresh_id)
            intent = json.loads((folder/'intent.json').read_bytes())
            self.assertEqual(intent['command'], C.START)
            self.assertEqual(intent['start_attempts_max'], 1)
            self.assertEqual((folder/'intent.json').stat().st_nlink, 1)
            self.assertEqual((folder/'intent.json').stat().st_mode & 0o777, 0o600)
            if self.start_error: raise self.start_error
            return self.start_code, b''
        if argv[:2] == ['/usr/bin/systemctl', 'show']:
            return 0, b'Result=success\nExecMainStatus=0\n'
        raise AssertionError('unapproved fixture command')

    def execute(self):
        return C._execute(C.request(self.request), sources=self.sources, baseline_sources=self.baseline_sources)

    def starts(self):
        return sum(x == tuple(C.START) for x in self.calls)

    def test_success_durable_intent_original_verify_and_no_replay(self):
        result = self.execute()
        self.assertEqual(result['status'], 'verified'); self.assertEqual(self.starts(), 1)
        self.assertEqual(self.guard_calls[-2:], [False, False])
        self.assertTrue(all(not result[k] for k in ('database_opened','diagnostic_output_read','product_deployed','ads_written')))
        second = self.execute()
        self.assertEqual(second['error_code'], 'REFRESH_REUSED')
        self.assertTrue(second['attempt_consumed']); self.assertEqual(self.starts(), 1)
        self.assertEqual(json.loads((self.root/('refresh-'+self.refresh_id)/'result.json').read_bytes()), result)

    def test_start_nonzero_preserved_no_verify_retry(self):
        self.start_code = 1
        out = self.execute(); self.assertEqual(out['error_code'], 'REFRESH_START_FAILED')
        self.assertTrue(out['attempt_consumed']); self.assertEqual(self.starts(), 1)
        self.assertNotIn(('helper.verify',), self.calls)
        self.execute(); self.assertEqual(self.starts(), 1)

    def test_start_timeout_consumes_attempt_and_never_restarts(self):
        self.start_error = T.Invalid('SYSTEMD_COMMAND_AMBIGUOUS')
        out = self.execute(); self.assertEqual(out['error_code'], 'REFRESH_START_AMBIGUOUS')
        self.assertTrue(out['start_requested']); self.execute(); self.assertEqual(self.starts(), 1)

    def test_helper_failure_stays_failure_and_timers_required(self):
        self.verify_error = 'EXPORT_RUN_NOT_VERIFIED'
        out = self.execute(); self.assertEqual(out['error_code'], self.verify_error)
        self.assertFalse(out['original_export_success_verified']); self.assertEqual(self.starts(), 1)

    def test_next_timestamp_strict_forms_and_types(self):
        self.assertEqual(C.NEXT, ['/usr/bin/busctl','get-property','org.freedesktop.systemd1',
            '/org/freedesktop/systemd1/unit/naver_2dmarket_2dexport_2etimer',
            'org.freedesktop.systemd1.Timer','NextElapseUSecRealtime'])
        self.assertEqual(C.next_epoch(b't 100000001\n'),100.000001)
        self.assertEqual(C.next_epoch(b't 1\n'),0.000001)
        self.assertEqual(C.next_epoch(b't 18446744073709551614\n'),((1<<64)-2)/1_000_000)
        for raw in (b't 0\n',b't 18446744073709551615\n',b't 18446744073709551616\n',
                    b't -1\n',b't +1\n',b't 01\n',b't 1.0\n',b't 1e6\n',b't  1\n',
                    b'x 100000001\n',b't 1\nt 2\n',b't 1 extra\n',b't 1\r\n',
                    b'NextElapseUSecRealtime=@100\n',b't 1',b't '+b'1'*129+b'\n',
                    't 100000001\n',True,bytearray(b't 1\n')):
            with self.subTest(raw=raw),self.assertRaises(T.Invalid):C.next_epoch(raw)

    def test_timer_imminent_or_changed_never_starts(self):
        self.next_at = int(time.time())+100
        self.assertEqual(self.execute()['error_code'], 'REFRESH_TIMER_NEAR'); self.assertEqual(self.starts(),0)
        self.calls.clear()
        self.next_at = int(time.time())+1000; self.next_shift = True
        self.assertEqual(self.execute()['error_code'], 'REFRESH_TIMER_NEXT'); self.assertEqual(self.starts(),0)

    def test_current_source_drift_and_cleanup_refused(self):
        with patch.object(C, '_compare', side_effect=T.Invalid('REFRESH_PROOF')):
            self.assertEqual(self.execute()['error_code'], 'REFRESH_PROOF')
        self.cleaned = False
        self.assertEqual(self.execute()['error_code'], 'REFRESH_CLEANUP'); self.assertEqual(self.starts(),0)

    def test_restored_history_required_and_tampering_refused(self):
        last = self.root/C.RESTORED_APPLY/('%06d.json' % len(self.history))
        last.unlink()
        out = self.execute(); self.assertEqual(out['error_code'], 'REFRESH_NOT_RESTORED')
        self.assertEqual(self.starts(),0)
        with (self.root/C.RESTORED_APPLY/'000001.json').open('ab') as stream: stream.write(b'x')
        self.assertEqual(self.execute()['status'], 'refused'); self.assertEqual(self.starts(),0)

    def test_partial_preparation_is_consumed_without_start(self):
        original = RealLedger._atomic_new
        def interrupted(ledger, path, raw):
            if path.name == 'intent.json': raise KeyboardInterrupt()
            return original(ledger, path, raw)
        with patch.object(RealLedger, '_atomic_new', interrupted), self.assertRaises(KeyboardInterrupt):
            self.execute()
        out = self.execute(); self.assertEqual(out['error_code'], 'REFRESH_REUSED')
        self.assertTrue(out['attempt_consumed']); self.assertEqual(self.starts(),0)

    def test_interruption_after_intent_is_consumed(self):
        original = RealLedger._atomic_new
        def interrupted(ledger, path, raw):
            original(ledger, path, raw)
            if path.name == 'intent.json': raise KeyboardInterrupt()
        with patch.object(RealLedger, '_atomic_new', interrupted), self.assertRaises(KeyboardInterrupt): self.execute()
        self.assertEqual(self.execute()['error_code'], 'REFRESH_REUSED'); self.assertEqual(self.starts(),0)

    def test_busy_global_lock_and_lock_identity_policy(self):
        with self.ledger.lock(), self.assertRaises(T.Invalid): self.execute()
        lock = self.root/'transition.lock'; lock.chmod(0o644)
        with self.assertRaises(T.Invalid): self.execute()
        self.assertEqual(self.starts(),0)

    def test_symlink_reused_id_no_follow_or_write(self):
        target = self.root/'untouched'; target.write_bytes(b'keep')
        (self.root/('refresh-'+self.refresh_id)).symlink_to(target)
        out = self.execute(); self.assertEqual(out['error_code'], 'REFRESH_REUSED')
        self.assertEqual(target.read_bytes(), b'keep'); self.assertEqual(self.starts(),0)

    def test_request_and_result_exact_types(self):
        for request in ({'version':True,'refresh_id':'a'*32}, {'version':1,'refresh_id':'0'*32},
                        {'version':1,'refresh_id':'a'*32,'command':'x'},
                        {'version':1,'refresh_id':C.RESTORED_APPLY}):
            with self.subTest(request=request), self.assertRaises(T.Invalid): C.request(request)
        out = C._result('REFRESH_REFUSED')
        for change in ({'database_opened':True}, {'version':True}, {'start_requested':True},
                       {'error_code':'secret raw'}, {'original_export_success_verified':True}):
            with self.subTest(change=change), self.assertRaises(T.Invalid): C.validate({**out,**change})
        self.assertIsInstance(C.closed_json(out), str)

    def test_no_clock_jump_or_extra_command_allowed(self):
        clock = C._Clock()
        with patch.object(C.time, 'time', return_value=clock.wall+10), self.assertRaises(T.Invalid): clock.now()
        attempt = C._Attempt()
        for args in (['systemctl','reset-failed',T.OLD_COORDINATOR], ['systemctl','start',T.OLD_READER],
                     ['systemctl','stop',T.OLD_TIMER], ['journalctl']):
            with self.subTest(args=args), self.assertRaises(T.Invalid): attempt.verify_command(args)
        self.assertEqual(self.starts(),0)

    def test_final_timer_check_anchors_deadline_without_start_extension(self):
        attempt = C._Attempt()
        with self.assertRaisesRegex(T.Invalid, '^REFRESH_DEADLINE$'):
            attempt.start()
        self.assertFalse(attempt.started)
        attempt.clock = types.SimpleNamespace(now=lambda: (1_000.0, 10.0))
        with patch.object(attempt, 'command', return_value=(0,b't 2000000000\n')):
            _, checked_mono = attempt.next()
        attempt.deadline = checked_mono + C.SAFETY_SECONDS
        attempt.clock = types.SimpleNamespace(now=lambda: (1_290.0, 300.0))
        calls=[]
        with patch.object(S,'bounded',side_effect=lambda a,**kw:calls.append((a,kw)) or (0,b'')):
            attempt.start()
        self.assertEqual(attempt.deadline,310.0)
        self.assertEqual(calls,[(C.START,dict(limit=4096,timeout=10))])
        expired=C._Attempt(); expired.deadline=310.0
        expired.clock=types.SimpleNamespace(now=lambda:(1_301.0,311.0))
        with patch.object(S,'bounded',side_effect=AssertionError('must not start')):
            with self.assertRaisesRegex(T.Invalid,'^REFRESH_DEADLINE$'): expired.start()
        self.assertFalse(expired.started); self.assertEqual(expired.deadline,310.0)

    def test_actual_helper_verify_keeps_four_results_two_timers_two_bundles(self):
        helper = self.original_helper_loader(self.baseline_sources)
        receipt = dict(source_identity={'fixed':1}, runtime_identity={'fixed':2}, operation_id='e'*32)
        plan = dict(exporter_user='nobody')
        calls, bundles = [], []
        def command(args):
            calls.append(args)
            return b'Result=success\nExecMainStatus=0\n' if args[1]=='show' else b'enabled\n'
        with ExitStack() as stack:
            for name, fn in [('_prepared',lambda _: (plan,self.root,{})),
                ('_source_identity',lambda _:receipt['source_identity']),
                ('_identity',lambda _:receipt['runtime_identity']),
                ('_regular',lambda *a,**k:b'{}'),
                ('_bundle_summary_for_user',lambda kind,*_: bundles.append(kind) or {'status':'ok'})]:
                stack.enter_context(patch.object(helper,name,fn))
            C._verify_original(helper,receipt,types.SimpleNamespace(verify_command=command))
            self.assertEqual(len(calls),8); self.assertEqual(bundles,['product','market'])
            self.assertEqual(sum(c[1]=='show' for c in calls),4)
            def failed(args):
                return b'Result=exit-code\nExecMainStatus=1\n' if args[2]==T.OLD_COORDINATOR else command(args)
            bundles.clear()
            with self.assertRaisesRegex(T.Invalid,'^EXPORT_RUN_NOT_VERIFIED$'):
                C._verify_original(helper,receipt,types.SimpleNamespace(verify_command=failed))
            self.assertFalse(bundles)

    def test_start_return_interruption_does_not_replay(self):
        self.start_error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): self.execute()
        self.assertEqual(self.starts(),1)
        self.assertEqual(self.execute()['error_code'],'REFRESH_REUSED')
        self.assertEqual(self.starts(),1)

    def test_public_absence_rejects_existing_symlink_writable_ancestor(self):
        safe = types.SimpleNamespace(st_mode=0o40755,st_uid=0)
        leaf = Path('/fixed/unit')
        def metadata(path):
            if path==leaf: raise FileNotFoundError()
            return safe
        with patch.object(Path,'lstat',metadata): self.original_absent(leaf)
        for bad in (types.SimpleNamespace(st_mode=0o120777,st_uid=0),
                    types.SimpleNamespace(st_mode=0o40777,st_uid=0),
                    types.SimpleNamespace(st_mode=0o40755,st_uid=1234)):
            def replaced(path): return bad if path==Path('/fixed') else metadata(path)
            with patch.object(Path,'lstat',replaced), self.assertRaises(T.Invalid): self.original_absent(leaf)
        with patch.object(Path,'lstat',lambda _:safe), self.assertRaises(T.Invalid): self.original_absent(leaf)


if __name__ == '__main__': unittest.main()
