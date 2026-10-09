"""Pure numeric Writer observations: no FIFO work, values, names or security bypass."""
import ast
import inspect
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from naver_engine import store as S
from naver_runtime import writer as W

KEYS=frozenset(('queue_depth','busy_duration_ms','active_phase','last_completed_phase',
               'accepted','completed','queued_cancel','full','closed','error'))


class PrivateArgument:
    def __repr__(self):raise AssertionError('Do not inspect argument')
    __str__=__repr__


class Store:
    def __init__(self,path,clock=None):
        self.owner=threading.get_ident();self.entered=threading.Event();self.release=threading.Event();self.values=[]
    def close(self):assert threading.get_ident()==self.owner
    def performance_work(self,*args,**kwargs):
        self.entered.set();assert self.release.wait(3);return True


class WriterDiagnosticsTest(unittest.TestCase):
    def create(self):
        stores=[]
        def factory(path,clock=None):
            store=Store(path,clock);stores.append(store);return store
        writer=W.Writer('synthetic-private',factory=factory)
        self.addCleanup(writer.close)
        return writer,stores[0]

    def settled(self,writer,completed):
        until=time.monotonic()+2
        while time.monotonic()<until:
            value=writer.diagnostics()
            if value['completed']>=completed:return value
            time.sleep(.001)
        self.fail('Synthetic callback counters did not settle')

    def hold(self,writer,store,*,phase=None):
        errors=[]
        def run():
            try:
                if phase is None:writer.proxy.performance_work(PrivateArgument(),secret=PrivateArgument())
                else:writer.call(lambda st:st.performance_work(),_phase=phase)
            except BaseException as exc:errors.append(type(exc).__name__)
        thread=threading.Thread(target=run);thread.start();self.assertTrue(store.entered.wait(1))
        self.addCleanup(lambda:(store.release.set(),thread.join(2)))
        return thread,errors

    def assert_numeric(self,value):
        self.assertEqual(set(value),KEYS)
        self.assertTrue(all(type(v) is int and v>=0 for v in value.values()))
        self.assertLess(len(json.dumps(value)),400)

    def test_live_snapshot_does_not_queue_or_wait_for_callback_and_phase_is_fixed_only(self):
        writer,store=self.create();worker,errors=self.hold(writer,store)
        waiter_done=threading.Event();waiter_errors=[]
        def queued():
            try:writer.call(lambda st:st.values.append('private'),wait=.5)
            except BaseException as exc:waiter_errors.append(type(exc).__name__)
            finally:waiter_done.set()
        waiter=threading.Thread(target=queued);waiter.start()
        self.addCleanup(lambda:(store.release.set(),waiter.join(2)))
        until=time.monotonic()+1
        while time.monotonic()<until:
            with writer._queue.mutex:depth=len(writer._queue.queue)
            if depth==1:break
            time.sleep(.001)
        self.assertEqual(depth,1)
        start=time.perf_counter();observed=writer.diagnostics();elapsed=(time.perf_counter()-start)*1000
        self.assert_numeric(observed);self.assertLess(elapsed,100)
        self.assertEqual(observed['queue_depth'],1);self.assertEqual(observed['active_phase'],61)
        self.assertEqual(observed['accepted'],2);self.assertEqual(observed['completed'],0)
        time.sleep(.01);later=writer.diagnostics();self.assertGreaterEqual(later['busy_duration_ms'],observed['busy_duration_ms'])
        self.assertEqual(later['accepted'],2);self.assertEqual(later['queue_depth'],1)
        store.release.set();worker.join(2);waiter.join(2)
        self.assertEqual(errors+waiter_errors,[]);self.assertTrue(waiter_done.is_set())
        final=self.settled(writer,2);self.assertEqual(final['busy_duration_ms'],0);self.assertEqual(final['active_phase'],0)
        self.assertEqual(final['queue_depth'],0);self.assertEqual(final['last_completed_phase'],0)

    def test_defaults_no_reset_and_snapshot_return_mutation_never_changes_counts(self):
        writer,store=self.create();first=writer.diagnostics();self.assert_numeric(first)
        self.assertEqual(first,dict.fromkeys(KEYS,0));self.assertEqual(inspect.signature(W.Writer.call).parameters['wait'].default,15)
        self.assertEqual(writer._queue.maxsize,32)
        self.assertFalse(hasattr(writer,'reset_diagnostics'))
        writer.call(lambda st:7,_phase=W.PHASE_WEB_WRITE);value=self.settled(writer,1)
        self.assertEqual(value['accepted'],1);self.assertEqual(value['completed'],1);self.assertEqual(value['last_completed_phase'],104)
        value.update(accepted=-1,error='private',active_phase='private')
        later=writer.diagnostics();self.assert_numeric(later);self.assertEqual(later['accepted'],1);self.assertEqual(later['error'],0)
        other,unused=self.create();self.assertEqual(other.diagnostics(),dict.fromkeys(KEYS,0))

    def test_queued_timeout_cancels_once_without_late_write_or_capacity_exhaustion(self):
        writer,store=self.create();worker,errors=self.hold(writer,store)
        for _ in range(32):
            with self.assertRaises(S.StoreBusy):writer.call(lambda st:st.values.append('cancelled'),wait=.001)
        value=writer.diagnostics();self.assert_numeric(value)
        self.assertEqual(value['accepted'],33);self.assertEqual(value['queued_cancel'],32)
        self.assertEqual(value['queue_depth'],0);self.assertEqual(value['completed'],0);self.assertEqual(value['full'],0)
        store.release.set();worker.join(2);self.assertEqual(errors,[]);self.assertEqual(store.values,[])
        final=self.settled(writer,1);self.assertEqual(final['accepted'],final['completed']+final['queued_cancel'])

    def test_close_pending_counts_queued_cancel_and_double_removal_race_once(self):
        writer,store=self.create();worker,errors=self.hold(writer,store)
        cancelled=threading.Event();allow_remove=threading.Event();original=writer._discard_cancelled;waiter_errors=[];close_errors=[]
        def delay(item):cancelled.set();self.assertTrue(allow_remove.wait(2));original(item)
        def queued():
            try:writer.call(lambda st:st.values.append('cancelled'),wait=.01)
            except BaseException as exc:waiter_errors.append(type(exc).__name__)
        def close():
            try:writer.close()
            except BaseException as exc:close_errors.append(type(exc).__name__)
        with patch.object(writer,'_discard_cancelled',side_effect=delay):
            waiter=threading.Thread(target=queued);waiter.start();closer=None
            try:
                self.assertTrue(cancelled.wait(1));self.assertEqual(writer.diagnostics()['queued_cancel'],1)
                closer=threading.Thread(target=close);closer.start();self.assertTrue(writer._stopping.wait(1))
                store.release.set();worker.join(2);closer.join(2)
                self.assertEqual(writer.diagnostics()['queue_depth'],0);self.assertEqual(writer.diagnostics()['queued_cancel'],1)
            finally:
                allow_remove.set();store.release.set();waiter.join(2);worker.join(2)
                if closer:closer.join(2)
        self.assertEqual(errors+close_errors,[]);self.assertEqual(waiter_errors,['StoreBusy']);self.assertEqual(store.values,[])
        self.assertEqual(writer.diagnostics()['accepted'],2);self.assertEqual(writer.diagnostics()['completed'],1)

    def test_shutdown_cancels_live_pending_once_and_closed_calls_are_distinct(self):
        writer,store=self.create();worker,errors=self.hold(writer,store);waiter_errors=[]
        def queued():
            try:writer.call(lambda st:st.values.append('should-not-run'))
            except BaseException as exc:waiter_errors.append(type(exc).__name__)
        waiter=threading.Thread(target=queued);waiter.start();self.addCleanup(lambda:(store.release.set(),waiter.join(2)))
        until=time.monotonic()+1
        while writer.diagnostics()['queue_depth']!=1 and time.monotonic()<until:time.sleep(.001)
        closer=threading.Thread(target=writer.close);closer.start();self.assertTrue(writer._stopping.wait(1));store.release.set()
        worker.join(2);closer.join(2);waiter.join(2)
        self.assertEqual(errors,[]);self.assertEqual(waiter_errors,['CancelledError']);self.assertEqual(store.values,[])
        final=writer.diagnostics();self.assert_numeric(final);self.assertEqual(final['queued_cancel'],1);self.assertEqual(final['completed'],1)
        with self.assertRaises(S.StoreBusy):writer.call(lambda st:None)
        closed=writer.diagnostics();self.assertEqual(closed['closed'],1);self.assertEqual(closed['accepted'],2)

    def test_callback_exception_counts_completed_without_exception_or_callable_introspection(self):
        writer,store=self.create()
        class HiddenCallable:
            def __getattribute__(self,name):
                if name in ('__name__','__qualname__','__dict__','__repr__'):raise AssertionError('Callback introspection prohibited')
                return object.__getattribute__(self,name)
            def __call__(self,st):raise RuntimeError('PRIVATE CALLBACK TEXT')
        with self.assertRaises(RuntimeError):writer.call(HiddenCallable(),_phase=29)
        value=self.settled(writer,1);self.assert_numeric(value);self.assertEqual(value['error'],1)
        self.assertEqual(value['last_completed_phase'],29);self.assertNotIn('PRIVATE',json.dumps(value))
        writer.call(lambda st:1);final=self.settled(writer,2);self.assertEqual(final['completed'],2);self.assertEqual(final['error'],1)

    def test_full_queue_preserves32_and_refusal_never_counts_as_accept_or_callback_error(self):
        writer,store=self.create();worker,errors=self.hold(writer,store);waiters=[];waiter_errors=[]
        def queued():
            try:writer.call(lambda st:True)
            except BaseException as exc:waiter_errors.append(type(exc).__name__)
        try:
            for _ in range(32):
                thread=threading.Thread(target=queued);thread.start();waiters.append(thread)
            until=time.monotonic()+1
            while writer.diagnostics()['queue_depth']!=32 and time.monotonic()<until:time.sleep(.001)
            with self.assertRaises(S.StoreBusy):writer.call(lambda st:True)
            value=writer.diagnostics();self.assertEqual(value['full'],1);self.assertEqual(value['accepted'],33);self.assertEqual(value['error'],0)
        finally:
            store.release.set();worker.join(2)
            for waiter in waiters:waiter.join(2)
        self.assertEqual(errors+waiter_errors,[]);self.assertEqual(self.settled(writer,33)['completed'],33)

    def test_phase_codes_are_fixed_immutable_and_invalid_labels_never_enter_queue(self):
        self.assertEqual(set(W.DIAGNOSTIC_PHASE_IDS),W.METHODS)
        self.assertEqual(set(W.DIAGNOSTIC_PHASE_IDS.values()),set(range(1,104)))
        self.assertEqual(W.DIAGNOSTIC_PHASE_IDS['performance_work'],61);self.assertEqual(W.DIAGNOSTIC_PHASE_IDS['structure_work'],100)
        self.assertEqual(W.DIAGNOSTIC_PHASE_IDS['record_access'],63);self.assertEqual(W.DIAGNOSTIC_PHASE_IDS['generate_reports'],29)
        with self.assertRaises(TypeError):W.DIAGNOSTIC_PHASE_IDS['private']=123
        writer,store=self.create()
        for bad in (True,False,-1,105,1.0,'performance_work',{'private':1},None):
            with self.assertRaises(S.StoreRefused):writer.call(lambda st:st.values.append('private'),_phase=bad)
        self.assertEqual(writer.diagnostics(),dict.fromkeys(KEYS,0));self.assertEqual(store.values,[])

    def test_started_callback_keeps_known_result_after_scaled_deadline_and_phase(self):
        writer,store=self.create();done=threading.Event();errors=[]
        def run():
            try:writer.call(lambda st:st.performance_work(),wait=.01,_phase=100)
            except BaseException as exc:errors.append(type(exc).__name__)
            finally:done.set()
        worker=threading.Thread(target=run);worker.start()
        try:
            self.assertTrue(store.entered.wait(1));self.assertFalse(done.wait(.04));value=writer.diagnostics()
            self.assertEqual(value['active_phase'],100);self.assertEqual(value['queued_cancel'],0);self.assertEqual(value['completed'],0)
            store.release.set();worker.join(2);self.assertEqual(errors,[]);self.assertTrue(done.is_set())
            final=self.settled(writer,1);self.assertEqual(final['last_completed_phase'],100);self.assertEqual(final['queued_cancel'],0)
        finally:store.release.set();worker.join(2)

    def test_concurrent_observers_never_reserve_fifo_or_change_counters(self):
        writer,store=self.create();worker,errors=self.hold(writer,store);observer_errors=[];counts=[]
        def observe():
            try:
                for _ in range(100):
                    value=writer.diagnostics();self.assert_numeric(value);counts.append((value['accepted'],value['completed']))
            except BaseException as exc:observer_errors.append(type(exc).__name__)
        observers=[threading.Thread(target=observe) for _ in range(8)]
        for t in observers:t.start()
        for t in observers:t.join(2);self.assertFalse(t.is_alive())
        self.assertEqual(observer_errors,[]);self.assertEqual(set(counts),{(1,0)});self.assertEqual(writer.diagnostics()['queue_depth'],0)
        store.release.set();worker.join(2);self.assertEqual(errors,[])

    def test_main_injects_manual_provider_and_fixed_web_phase_only(self):
        root=Path(__file__).resolve().parents[2];tree=ast.parse((root/'naver_runtime/__main__.py').read_text())
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='WEB' and n.func.attr=='App']
        self.assertEqual(len(calls),1);kwargs={k.arg:k.value for k in calls[0].keywords}
        self.assertEqual(ast.unparse(kwargs['writer_diagnostics']),'writer.diagnostics')
        self.assertEqual(ast.unparse(kwargs['write']),'lambda fn: writer.call(fn, _phase=PHASE_WEB_WRITE)')
