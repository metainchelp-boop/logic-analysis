import threading
import unittest

from naver_engine import store as S
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
