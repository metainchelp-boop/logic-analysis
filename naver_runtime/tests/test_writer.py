import threading
import unittest
import hashlib
import tempfile
import time
from pathlib import Path
from unittest import mock

from naver_engine.tests import test_morning as TM
from naver_engine import store as S, erp_read as E
from naver_runtime.writer import Writer


class MemoryStore:
    def __init__(self, path, clock=None):
        self.owner = threading.get_ident()
        self.closed = False
        self.values = []

    def close(self):
        assert threading.get_ident() == self.owner
        self.closed = True

    def thresholds(self):
        assert threading.get_ident() == self.owner
        return "thresholds"


class WriterTest(unittest.TestCase):
    def test_inventory_proxy_serializes_real_store_and_returns_detached_values(self):
        with tempfile.TemporaryDirectory() as folder, Writer(str(Path(folder)/"engine.db"), clock=lambda: TM.T0) as writer:
            proxy = writer.proxy
            proxy.record_accounts(TM.kids(TM.A, TM.B), TM.T0)
            body = {"generated_at": TM.T0.isoformat(), "total": 0, "complete": True, "items": []}
            proxy.record_account_catalog(body, (), TM.T0)
            detached = proxy.account_catalog_status()
            detached["state"] = "changed-in-caller"
            self.assertEqual(proxy.account_catalog_status()["state"], "accepted")
            with self.assertRaises(E.ErpIncomplete):
                proxy.record_account_catalog(dict(body, total=1), (), TM.T0)
            self.assertEqual(proxy.account_catalog_status()["state"], "accepted")
            self.assertEqual(writer.call(lambda store: store.account_catalog())["total"], 0)
            snapshot = proxy.inventory_snapshot(TM.T0)
            work = proxy.inventory_work(TM.T0)
            work.clear()
            self.assertEqual(proxy.inventory_work(TM.T0), [TM.A, TM.B])
            results, errors = [], []
            def collect(cid):
                try:
                    self.assertTrue(proxy.inventory_account_valid(cid, snapshot, TM.T0))
                    self.assertTrue(proxy.collection_account_ready(cid, TM.T0))
                    proxy.begin_inventory_check(cid, snapshot, TM.T0)
                    progress = {"customer_id": cid, "day": TM.T0.date().isoformat(), "campaign_ids": [],
                                "fingerprint": hashlib.sha256(b"[]").hexdigest(), "next_index": 0, "batches": []}
                    proxy.record_inventory_progress(cid, snapshot, TM.T0, progress)
                    returned = proxy.inventory_progress(cid, TM.T0.date())
                    returned["batches"].append({"caller": "mutation"})
                    self.assertEqual(proxy.inventory_progress(cid, TM.T0.date())["batches"], [])
                    results.append(proxy.record_inventory_check(cid, snapshot, TM.T0,
                        {"status": "ok", "bizmoney": 10, "yday_imp": 0, "yday_clk": 0, "yday_spend": 0}))
                except BaseException as error:
                    errors.append(type(error).__name__)
            threads = [threading.Thread(target=collect, args=(cid,)) for cid in (TM.A, TM.B)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(3)
                self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(results, ["ok", "ok"])
            proxy.record_account_catalog_failure(TM.T0, "CATALOG_FAILED")
            self.assertEqual(proxy.account_catalog_status()["state"], "failed")
            self.assertEqual(writer.call(lambda store: store.account_catalog())["total"], 0)
            for name in ("close", "_conn", "_tx", "record_thresholds"):
                with self.subTest(name=name), self.assertRaises(AttributeError):
                    getattr(proxy, name)

    def test_all_calls_use_the_connection_owner(self):
        with Writer("synthetic", factory=MemoryStore) as writer:
            owner = writer.call(lambda st: st.owner)
            self.assertNotEqual(owner, threading.get_ident())
            seen = []
            workers = [threading.Thread(target=lambda: seen.append(writer.call(lambda st: threading.get_ident())))
                       for _ in range(16)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(3)
                self.assertFalse(worker.is_alive())
            self.assertEqual(seen, [owner] * 16)
            self.assertEqual(writer.proxy.thresholds(), "thresholds")
            with self.assertRaises(AttributeError):
                writer.proxy.close()
            with self.assertRaises(AttributeError):
                writer.proxy._conn

    def test_timed_out_queued_write_is_never_applied(self):
        entered, release = threading.Event(), threading.Event()
        with Writer("synthetic", factory=MemoryStore) as writer:
            blocker = threading.Thread(target=lambda: writer.call(lambda st: (entered.set(), release.wait(3))))
            blocker.start()
            self.assertTrue(entered.wait(1))
            try:
                with self.assertRaises(S.StoreBusy):
                    writer.call(lambda st: st.values.append("late"), wait=.02)
            finally:
                release.set()
                blocker.join(2)
            self.assertEqual(writer.call(lambda st: st.values), [])

    def test_cancelled_waiters_do_not_exhaust_admission_capacity(self):
        entered, release, normal_done = threading.Event(), threading.Event(), threading.Event()
        results, errors = [], []
        with Writer("synthetic", factory=MemoryStore) as writer:
            def paused(store):
                entered.set()
                self.assertTrue(release.wait(5))
            def run_paused():
                try:
                    writer.call(paused)
                except BaseException as error:
                    errors.append(error)
            blocker = threading.Thread(target=run_paused)
            blocker.start()
            normal_worker = None
            try:
                self.assertTrue(entered.wait(1))
                for _ in range(32):
                    with self.assertRaises(S.StoreBusy):
                        writer.call(lambda st: st.values.append("cancelled"), wait=.01)
                def normal(store):
                    store.values.append("normal")
                    return "normal"
                def submit_normal():
                    try:
                        results.append(writer.call(normal))
                    except BaseException as error:
                        errors.append(error)
                    finally:
                        normal_done.set()
                normal_worker = threading.Thread(target=submit_normal)
                normal_worker.start()
                until = time.monotonic() + 1
                while not normal_done.is_set() and time.monotonic() < until:
                    with writer._queue.mutex:
                        queued = any(fn is normal for _, fn in writer._queue.queue)
                    if queued:
                        break
                    time.sleep(.001)
                else:
                    self.assertTrue(normal_done.is_set(), "normal submission did not reach Writer")
            finally:
                release.set()
                blocker.join(2)
                if normal_worker is not None:
                    normal_worker.join(2)
            self.assertFalse(blocker.is_alive())
            self.assertFalse(normal_worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(results, ["normal"])
            self.assertEqual(writer.call(lambda st: list(st.values)), ["normal"])

    def test_started_write_finishes_after_its_queue_deadline(self):
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        results, errors = [], []
        with Writer("synthetic", factory=MemoryStore) as writer:
            def work(store):
                entered.set()
                self.assertTrue(release.wait(3))
                store.values.append("finished")
                return "finished"
            def submit():
                try:
                    results.append(writer.call(work, wait=.01))
                except BaseException as error:
                    errors.append(error)
                finally:
                    done.set()
            worker = threading.Thread(target=submit)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertFalse(done.wait(.04))
            finally:
                release.set()
                worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(results, ["finished"])
            self.assertEqual(writer.call(lambda st: list(st.values)), ["finished"])

    def test_dequeue_or_close_can_win_cancelled_item_removal(self):
        for remove_by in ("consumer", "close"):
            with self.subTest(remove_by=remove_by):
                entered, release = threading.Event(), threading.Event()
                cancelling, allow_remove = threading.Event(), threading.Event()
                errors = []
                stores = []
                def factory(path, clock=None):
                    store = MemoryStore(path, clock=clock)
                    stores.append(store)
                    return store
                with Writer("synthetic", factory=factory) as writer:
                    def paused(store):
                        entered.set()
                        self.assertTrue(release.wait(3))
                    def hold():
                        try:
                            writer.call(paused)
                        except BaseException as error:
                            errors.append(error)
                    original_remove = writer._discard_cancelled
                    def delay_remove(item):
                        cancelling.set()
                        self.assertTrue(allow_remove.wait(3))
                        original_remove(item)
                    def cancel_waiter():
                        try:
                            writer.call(lambda st: st.values.append("cancelled"), wait=.01)
                        except BaseException as error:
                            errors.append(error)
                    def close_writer():
                        try:
                            writer.close()
                        except BaseException as error:
                            errors.append(error)
                    blocker = threading.Thread(target=hold)
                    waiter = None
                    closer = None
                    blocker.start()
                    with mock.patch.object(writer, "_discard_cancelled", side_effect=delay_remove):
                        try:
                            self.assertTrue(entered.wait(1))
                            waiter = threading.Thread(target=cancel_waiter)
                            waiter.start()
                            self.assertTrue(cancelling.wait(1))
                            if remove_by == "close":
                                closer = threading.Thread(target=close_writer)
                                closer.start()
                                self.assertTrue(writer._stopping.wait(1))
                            release.set()
                            blocker.join(2)
                            if closer is not None:
                                closer.join(2)
                                self.assertFalse(closer.is_alive())
                            else:
                                # Waiting for this result proves the consumer passed
                                # the cancelled item before removal is resumed.
                                self.assertEqual(writer.call(lambda st: list(st.values)), [])
                        finally:
                            release.set()
                            allow_remove.set()
                            blocker.join(2)
                            if waiter is not None:
                                waiter.join(2)
                            if closer is not None:
                                closer.join(2)
                    self.assertFalse(blocker.is_alive())
                    self.assertFalse(waiter.is_alive())
                    self.assertEqual(len(errors), 1)
                    self.assertIsInstance(errors[0], S.StoreBusy)
                    self.assertEqual(str(errors[0]), "저장 대기 시간을 넘었습니다")
                    self.assertEqual(stores[0].values, [])
                    if remove_by == "consumer":
                        self.assertEqual(writer.call(lambda st: st.thresholds()), "thresholds")
                self.assertTrue(stores[0].closed)

    def test_live_waiters_keep_fifo_after_cancelled_middle_item(self):
        entered, release = threading.Event(), threading.Event()
        errors, workers = [], []
        with Writer("synthetic", factory=MemoryStore) as writer:
            def paused(store):
                entered.set()
                self.assertTrue(release.wait(3))
            def submit(fn):
                try:
                    writer.call(fn)
                except BaseException as error:
                    errors.append(error)
            blocker = threading.Thread(target=submit, args=(paused,))
            blocker.start()
            try:
                self.assertTrue(entered.wait(1))
                for label in ("first", "second", "third"):
                    fn = lambda st, value=label: st.values.append(value)
                    worker = threading.Thread(target=submit, args=(fn,))
                    workers.append(worker)
                    worker.start()
                    until = time.monotonic() + 1
                    while time.monotonic() < until:
                        with writer._queue.mutex:
                            queued = any(callback is fn for _, callback in writer._queue.queue)
                        if queued:
                            break
                        time.sleep(.001)
                    self.assertTrue(queued)
                    if label == "first":
                        with self.assertRaises(S.StoreBusy):
                            writer.call(lambda st: st.values.append("cancelled"), wait=.01)
            finally:
                release.set()
                blocker.join(2)
                for worker in workers:
                    worker.join(2)
            self.assertFalse(blocker.is_alive())
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(errors, [])
            self.assertEqual(writer.call(lambda st: list(st.values)), ["first", "second", "third"])

    def test_live_waiters_still_obey_capacity_32(self):
        entered, release = threading.Event(), threading.Event()
        errors, workers = [], []
        with Writer("synthetic", factory=MemoryStore) as writer:
            def paused(store):
                entered.set()
                self.assertTrue(release.wait(5))
            def submit(fn):
                try:
                    writer.call(fn)
                except BaseException as error:
                    errors.append(error)
            blocker = threading.Thread(target=submit, args=(paused,))
            blocker.start()
            try:
                self.assertTrue(entered.wait(1))
                for index in range(32):
                    fn = lambda st, value=index: st.values.append(value)
                    worker = threading.Thread(target=submit, args=(fn,))
                    workers.append(worker)
                    worker.start()
                    until = time.monotonic() + 1
                    while time.monotonic() < until:
                        with writer._queue.mutex:
                            queued = any(callback is fn for _, callback in writer._queue.queue)
                        if queued:
                            break
                        time.sleep(.001)
                    self.assertTrue(queued)
                with self.assertRaises(S.StoreBusy) as caught:
                    writer.call(lambda st: st.values.append("overflow"), wait=.01)
                self.assertEqual(str(caught.exception), "저장 요청이 많습니다")
            finally:
                release.set()
                blocker.join(2)
                for worker in workers:
                    worker.join(2)
            self.assertFalse(blocker.is_alive())
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(errors, [])
            self.assertEqual(writer.call(lambda st: list(st.values)), list(range(32)))


if __name__ == "__main__":
    unittest.main()
