import threading
import unittest
import hashlib
import tempfile
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
