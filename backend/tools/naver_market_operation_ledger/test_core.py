"""New ledger adapter tests: real temp files/locks, explicit non-operating seams."""
from contextlib import ExitStack, contextmanager
import ast
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import select
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent

def load_core():
    spec = importlib.util.spec_from_file_location('fixed_ledger_core', HERE / 'core.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def dependencies():
    installed = HERE.parent / 'naver_market_diagnostic_transition'
    draft = Path('/Users/sinyosub/Documents/Codex/2026-10-07/new-chat-2/work/naver-claude-reference-ops-20261011/backend/tools/naver_market_diagnostic_transition')
    source = HERE if (HERE / 'transition.py').is_file() else installed if (installed / 'transition.py').is_file() else draft
    return {name: (source / (name + '.py')).read_bytes() for name in ('transition', 'journal')}


@contextmanager
def flock_peers(path):
    code='import os,fcntl,sys; f=os.open(sys.argv[1],os.O_RDONLY); print("ready",flush=True); sys.stdin.read(1)\ntry: fcntl.flock(f,getattr(fcntl,"LOCK_"+sys.argv[2])|fcntl.LOCK_NB)\nexcept BlockingIOError: sys.exit(3)'
    children=[]
    try:
        for mode,expected in [('SH',0),('EX',3)]:
            child=subprocess.Popen([sys.executable,'-I','-B','-c',code,str(path),mode],stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
            children.append((child,expected))
            if not select.select([child.stdout],[],[],3)[0] or child.stdout.readline().strip()!='ready':
                raise RuntimeError('fixture_peer_not_ready')
        def check():
            for child,expected in children:
                child.communicate('x',timeout=3)
                if child.returncode!=expected: raise RuntimeError('fixture_peer_lock')
        yield check
    finally:
        for child,_expected in children:
            if child.poll() is None:
                try: child.communicate('x',timeout=3)
                except subprocess.TimeoutExpired: child.kill(); child.communicate(timeout=3)


class Fixture:
    def __init__(self, base, *, strict_root=False):
        self.C = load_core(); self.buffers = dependencies()
        with self.C._modules(self.buffers) as pair: self.T, self.J = pair
        self.root = Path(base).resolve() / 'ledger'
        self.root.mkdir(mode=0o700); self.root.chmod(0o700)
        self.folder = self.root / self.C.APPLY; self.folder.mkdir(mode=0o700)
        self.ids = self.root / 'identities'; self.ids.mkdir(mode=0o700)
        self.plan = dict(apply_id=self.C.APPLY, rollback_id=self.C.ROLLBACK,
                         reader='fixed-fixture-reader.service')
        self.plan_hash = self.T.sha(self.T.canonical(self.plan))
        self.write(self.root / 'transition.lock', b'')
        self.write(self.folder / 'plan.json', self.T.canonical(self.plan))
        reservation = dict(apply_id=self.C.APPLY, rollback_id=self.C.ROLLBACK,
                           plan_sha256=self.plan_hash)
        self.write(self.ids / (self.C.APPLY + '.json'), self.T.canonical(reservation))
        self.stack = ExitStack()
        for name, value in [('ROOT', self.root), ('PLAN_SHA256', self.plan_hash),
                            ('OWNER', self.root.stat().st_uid), ('GROUP', self.root.stat().st_gid)]:
            self.stack.enter_context(mock.patch.object(self.C, name, value))
        self.stack.enter_context(mock.patch.object(self.C.sys, 'platform', 'linux'))
        self.stack.enter_context(mock.patch.object(self.C.os, 'geteuid', return_value=0))
        if not strict_root:
            # macOS temp ancestry is not a root-owned production path.
            self.stack.enter_context(mock.patch.object(self.C, '_ancestor', self.fixture_ancestor))
        self.history(self.apply_prefix('installed_verify', 'done', restored=True))

    @staticmethod
    def fixture_ancestor(info):
        if not stat.S_ISDIR(info.st_mode): raise AssertionError('fixture directory')

    @staticmethod
    def write(path, raw):
        path.write_bytes(raw); path.chmod(0o600)

    def close(self): self.stack.close()

    def apply_prefix(self, step='installed_verify', state='done', *, restored=False):
        events = [dict(action='apply', state='intent', apply_id=self.C.APPLY, rollback_id=self.C.ROLLBACK)]
        if step != 'none':
            for action in self.T.STEPS:
                events.append(dict(action=action, state='intent'))
                if action == step and state == 'intent': break
                event = dict(action=action, state='done')
                if action == 'observe':
                    event['observation'] = dict(reader=self.plan['reader'], invocation_id='a'*32,
                        status='source_limit', limit_issue='rows', exit_status=1)
                events.append(event)
                if action == step: break
        events.append(dict(action='apply', state='blocked'))
        if restored:
            events.append(dict(action='rollback', state='intent'))
            for action in self.T.CLEANUP:
                events.extend([dict(action=action, state='intent'), dict(action=action, state='done')])
            events.append(dict(action='rollback', state='done'))
        return events

    def history(self, events):
        for path in self.folder.glob('[0-9]*.json'): path.unlink()
        previous = self.plan_hash
        for index, event in enumerate(events, 1):
            payload = dict(sequence=index, previous=previous, event=event)
            previous = self.T.sha(self.T.canonical(payload))
            self.write(self.folder / ('%06d.json' % index), self.T.canonical(dict(payload, sha256=previous)))
        self.events = events

    def observe(self): return self.C.observe(self.buffers)

    def inventory(self):
        return {str(p.relative_to(self.root)): (self.J.identity(p.lstat()), p.read_bytes() if p.is_file() else None)
                for p in [self.root, *sorted(self.root.rglob('*'))]}


class LedgerReadonlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.F = Fixture(self.temp.name); self.C = self.F.C

    def tearDown(self): self.F.close(); self.temp.cleanup()

    def assert_refused(self, expected=None):
        value = self.F.observe()
        self.assertEqual(value['status'], 'refused')
        if expected: self.assertEqual(value['refusal'], expected)
        self.assertTrue(all(value[k] is None for k in self.C.FIELDS))
        self.assertIs(self.C.validate(value), value)

    def test_restored_projects_first_apply_only(self):
        value = self.F.observe()
        self.assertEqual(value['status'], 'observed')
        self.assertEqual(value['history_state'], 'restored')
        self.assertEqual(value['last_apply_step'], 'installed_verify')
        self.assertTrue(value['rollback_done']); self.assertTrue(value['apply_blocked'])
        self.assertFalse(value['run_once_intent']); self.assertFalse(value['observe_done'])

    def test_run_once_and_observe_boundaries_after_restoration(self):
        for step, state in [('run_once','intent'), ('run_once','done'), ('observe','intent'), ('observe','done')]:
            with self.subTest(step=step,state=state):
                self.F.history(self.F.apply_prefix(step,state,restored=True))
                value = self.F.observe(); self.assertEqual(value['status'], 'observed')
                self.assertTrue(value['run_once_intent']); self.assertTrue(value['rollback_done'])
                self.assertEqual(value['run_once_done'], step == 'observe' or state == 'done')
                self.assertEqual(value['observe_done'], step == 'observe' and state == 'done')

    def test_incomplete_valid_chain_is_not_restored(self):
        self.F.history(self.F.apply_prefix('run_once','intent',restored=True)[:-1])
        value = self.F.observe()
        self.assertEqual(value['history_state'], 'rollback'); self.assertFalse(value['rollback_done'])

    def test_missing_and_invalid_lock(self):
        path = self.F.root / 'transition.lock'; path.unlink()
        self.assert_refused('lock_missing')
        for body, mode in [(b'x',0o600),(b'',0o644)]:
            self.F.write(path, body); path.chmod(mode)
            self.assert_refused('lock_invalid')
        self.F.write(path,b'')
        for field in ('OWNER','GROUP'):
            with mock.patch.object(self.C,field,getattr(self.C,field)+1): self.assert_refused('lock_invalid')

    def test_lock_symlink_and_extra_hardlink(self):
        path = self.F.root / 'transition.lock'; target=self.F.root / 'other'
        path.rename(target); path.symlink_to(target)
        self.assert_refused('lock_invalid')
        path.unlink(); target.rename(path); os.link(path,target)
        self.assert_refused('lock_invalid')

    def test_actual_exclusive_writer_is_busy(self):
        code = 'import os,fcntl,sys; f=os.open(sys.argv[1],os.O_RDONLY); fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); sys.stdin.read(1)'
        process=subprocess.Popen([sys.executable,'-I','-B','-c',code,str(self.F.root/'transition.lock')],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(),'ready')
            self.assert_refused('lock_busy')
        finally:
            process.communicate('x',timeout=5)
        self.assertEqual(process.returncode,0)

    def test_shared_lock_allows_reader_and_excludes_writer(self):
        original=self.C._project
        with flock_peers(self.F.root/'transition.lock') as check:
            def locked(*args):
                check(); return original(*args)
            with mock.patch.object(self.C,'_project',side_effect=locked):
                self.assertEqual(self.F.observe()['status'],'observed')

    def test_lock_replacement_before_acquisition_refused(self):
        original=self.C.fcntl.flock
        def changed(fd, flags):
            p=self.F.root/'transition.lock'; p.unlink(); self.F.write(p,b'')
            return original(fd,flags)
        with mock.patch.object(self.C.fcntl,'flock',side_effect=changed): self.assert_refused('context_changed')

    def test_root_folder_identities_plan_races_refused(self):
        for role in ('root','folder','ids','plan'):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as temp:
                fixture=Fixture(temp); core=fixture.C; original=core._project
                try:
                    def changed(*args):
                        value=original(*args)
                        target={'root':fixture.root,'folder':fixture.folder,'ids':fixture.ids,
                                'plan':fixture.folder/'plan.json'}[role]
                        target.chmod(0o755 if target.is_dir() else 0o644)
                        return value
                    with mock.patch.object(core,'_project',side_effect=changed):
                        self.assertEqual(fixture.observe()['refusal'],'context_changed')
                finally: fixture.close()

    def test_wrong_plan_pin_and_pair_refused(self):
        with mock.patch.object(self.C,'PLAN_SHA256','f'*64): self.assert_refused('plan_binding')
        plan=dict(self.F.plan,rollback_id='c'*32)
        raw=self.F.T.canonical(plan); self.F.write(self.F.folder/'plan.json',raw)
        with mock.patch.object(self.C,'PLAN_SHA256',self.F.T.sha(raw)): self.assert_refused('plan_binding')

    def test_plan_malicious_json_and_size_refused(self):
        for raw in (b'{"x":1,"x":1}', b'{"x":NaN}', b'{"x":true} ', b'['*1200+b']'*1200, b'x'*32769):
            with self.subTest(length=len(raw)):
                self.F.write(self.F.folder/'plan.json',raw); self.assert_refused()

    def test_chain_grammar_and_missing_event_refused(self):
        raw=(self.F.folder/'000002.json').read_bytes()
        self.F.write(self.F.folder/'000002.json',raw.replace(b'timer_stop',b'timer_bad_'))
        self.assert_refused('ledger_rejected')
        self.F.history(self.F.events); (self.F.folder/'000002.json').unlink()
        self.assert_refused('ledger_rejected')
        self.F.history([self.F.events[0],dict(action='run_once',state='intent')])
        self.assert_refused('ledger_rejected')

    def test_pair_reservation_tamper_and_cross_pair_reuse(self):
        reservation=dict(apply_id=self.C.APPLY,rollback_id='e'*32,plan_sha256=self.F.plan_hash)
        self.F.write(self.F.ids/(self.C.APPLY+'.json'),self.F.T.canonical(reservation))
        self.assert_refused('ledger_rejected')
        reservation=dict(apply_id=self.C.APPLY,rollback_id=self.C.ROLLBACK,plan_sha256=self.F.plan_hash)
        self.F.write(self.F.ids/(self.C.APPLY+'.json'),self.F.T.canonical(reservation))
        other=dict(apply_id='d'*32,rollback_id=self.C.ROLLBACK,plan_sha256='e'*64)
        self.F.write(self.F.ids/('d'*32+'.json'),self.F.T.canonical(other))
        self.assert_refused('ledger_rejected')

    def test_pending_hardlink_original_contract_and_orphan_cap(self):
        peer=self.F.folder/('.pending-'+'a'*32)
        os.link(self.F.folder/'000002.json',peer)
        self.assertEqual(self.F.observe()['status'],'observed')
        peer.unlink()
        os.link(self.F.folder/'000002.json',self.F.root/'unknown-peer')
        self.assert_refused('ledger_rejected')
        (self.F.root/'unknown-peer').unlink()
        for index in range(17): self.F.write(self.F.folder/('.pending-'+format(index,'032x')),b'')
        self.assert_refused('ledger_rejected')

    def test_inventory_and_event_caps_preserved(self):
        self.F.write(self.F.folder/'unexpected',b''); self.assert_refused('ledger_rejected')
        (self.F.folder/'unexpected').unlink()
        for index in range(300): self.F.write(self.F.ids/(format(index,'032x')+'.json'),b'{}')
        self.assert_refused('ledger_rejected')

    def test_read_budget_and_monotonic_deadline(self):
        with mock.patch.object(self.C,'MAX_READ',32768): self.assert_refused('read_budget')
        with mock.patch.object(self.C.time,'monotonic',side_effect=[0,11]): self.assert_refused('deadline')

    def test_read_budget_accumulates_original_file_reads(self):
        original=os.read; lengths=[]
        def reading(*args):
            value=original(*args); lengths.append(len(value)); return value
        plan_size=len(self.F.T.canonical(self.F.plan))
        limit=32769+plan_size
        with mock.patch.object(self.C,'MAX_READ',limit),mock.patch.object(os,'read',side_effect=reading):
            self.assert_refused('read_budget')
        self.assertGreaterEqual(sum(lengths),2*plan_size)
        self.assertLessEqual(sum(lengths),limit)

    def test_alarm_interrupt_and_no_leftover_timer(self):
        before=signal.getsignal(signal.SIGALRM)
        with mock.patch.object(self.C,'SECONDS',0.03), mock.patch.object(self.C,'_read',side_effect=lambda *a: time.sleep(0.2)):
            self.assert_refused('deadline')
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL),(0.0,0.0))
        self.assertEqual(signal.getsignal(signal.SIGALRM),before)

    def test_exact_source_bytes_and_module_collision(self):
        with mock.patch.object(self.C,'_read',side_effect=AssertionError('must not reach')):
            for value in ({},dict(self.F.buffers,journal=self.F.buffers['journal']+b' '),
                          dict(self.F.buffers,transition=bytearray(self.F.buffers['transition']))):
                self.assertEqual(self.C.observe(value)['refusal'],'source_binding')
            with mock.patch.dict(sys.modules,{'transition':object()}):
                self.assertEqual(self.F.observe()['refusal'],'module_collision')
        self.assertNotIn('transition',sys.modules)

    def test_readonly_syscalls_and_original_writer_methods_unreachable(self):
        before=self.F.inventory(); original_open=os.open; calls=[]
        def read_open(path, flags, *args, **kwargs):
            self.assertEqual(flags & os.O_ACCMODE,os.O_RDONLY)
            self.assertFalse(flags & (os.O_CREAT|os.O_TRUNC|os.O_APPEND)); calls.append(flags)
            return original_open(path,flags,*args,**kwargs)
        original_modules=self.C._modules
        from contextlib import contextmanager
        @contextmanager
        def bounded_modules(values):
            with original_modules(values) as pair:
                with ExitStack() as stack:
                    for name in ('lock','append','_reserve_ids','_atomic_new','_sync'):
                        stack.enter_context(mock.patch.object(pair[1].Ledger,name,side_effect=AssertionError('writer path')))
                    yield pair
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(self.C,'_modules',bounded_modules))
            stack.enter_context(mock.patch.object(os,'open',side_effect=read_open))
            for name in ('write','fsync','mkdir','unlink','rename','link','chmod','fchmod'):
                stack.enter_context(mock.patch.object(os,name,side_effect=AssertionError('write syscall')))
            self.assertEqual(self.F.observe()['status'],'observed')
        self.assertTrue(calls); self.assertEqual(self.F.inventory(),before)
        tree=ast.parse((HERE/'core.py').read_text())
        names=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        self.assertFalse(set(names)&{'lock','_reserve_ids','_atomic_new','_sync','fsync','write','mkdir','unlink'})
        append_calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='append']
        self.assertTrue(all(isinstance(n.func.value,ast.Name) and n.func.value.id in ('held','opened') for n in append_calls))

    def test_all_open_fds_closed_on_success_and_refusal(self):
        original_open, original_close = os.open, os.close
        for failed in (False, True):
            with self.subTest(failed=failed):
                opened, closed = [], []
                def opening(*args, **kwargs):
                    fd=original_open(*args, **kwargs); opened.append(fd); return fd
                def closing(fd):
                    closed.append(fd); return original_close(fd)
                with ExitStack() as stack:
                    stack.enter_context(mock.patch.object(os,'open',side_effect=opening))
                    stack.enter_context(mock.patch.object(os,'close',side_effect=closing))
                    if failed: stack.enter_context(mock.patch.object(self.C,'_project',side_effect=self.C.Refused('context_changed')))
                    value=self.F.observe()
                self.assertEqual(value['status'],'refused' if failed else 'observed')
                self.assertEqual(sorted(opened),sorted(closed))
        opened, closed = [], []
        with mock.patch.object(os,'open',side_effect=opening), mock.patch.object(os,'close',side_effect=closing), mock.patch.object(os,'fstat',side_effect=OSError):
            self.assert_refused('ledger_rejected')
        self.assertEqual(sorted(opened), sorted(closed))

    def test_alarm_during_directory_cleanup_closes_all_fds(self):
        original_open, original_close = os.open, os.close
        opened, closed, injected = [], [], []
        def opening(*args, **kwargs):
            fd=original_open(*args, **kwargs); opened.append(fd); return fd
        def closing(fd):
            directory=stat.S_ISDIR(os.fstat(fd).st_mode)
            original_close(fd); closed.append(fd)
            if directory and not injected:
                injected.append(True); signal.raise_signal(signal.SIGALRM)
        with mock.patch.object(os,'open',side_effect=opening), mock.patch.object(os,'close',side_effect=closing):
            self.assert_refused('deadline')
        self.assertEqual(injected,[True]); self.assertEqual(sorted(opened),sorted(closed))
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL),(0.0,0.0))

    def test_alarm_after_open_before_registration_closes_all_fds(self):
        original_open, original_close = os.open, os.close
        for suffix in ('identities','transition.lock','plan.json'):
            with self.subTest(suffix=suffix):
                opened, closed, injected = [], [], []
                def opening(path,*args,**kwargs):
                    fd=original_open(path,*args,**kwargs); opened.append(fd)
                    if str(path).endswith(suffix) and not injected:
                        injected.append(True); signal.raise_signal(signal.SIGALRM)
                    return fd
                def closing(fd): original_close(fd); closed.append(fd)
                with mock.patch.object(os,'open',side_effect=opening), mock.patch.object(os,'close',side_effect=closing):
                    self.assert_refused('deadline')
                self.assertEqual(injected,[True]); self.assertEqual(sorted(opened),sorted(closed))
                self.assertEqual(signal.getitimer(signal.ITIMER_REAL),(0.0,0.0))

    def test_strict_result_types_keys_consistency_and_no_private_projection(self):
        value=self.F.observe(); self.assertIs(self.C.validate(value),value)
        raw=self.C.closed_json(value); self.assertIs(type(raw),str)
        for private in (self.C.APPLY,self.C.ROLLBACK,self.F.plan_hash,str(self.F.root),'fixed-fixture-reader'):
            self.assertNotIn(private,raw)
        changes=[{'version':True},{'extra':False},{'run_once_done':1},{'rollback_done':False},
                 {'run_once_intent':True},{'last_apply_step':'unknown'}, {'status':'refused'}]
        for delta in changes:
            with self.subTest(delta=delta), self.assertRaises(self.C.Refused): self.C.validate(dict(value,**delta))
        self.assertIs(self.C.validate(self.C._blank('lock_busy'))['history_state'],None)


if __name__=='__main__': unittest.main()
