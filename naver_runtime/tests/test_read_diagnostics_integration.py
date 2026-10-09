"""Guarded manual read observes the actual Writer outside its busy FIFO; synthetic only."""
import threading
import unittest

from naver_engine.tests import test_detailed_collection_status as D
from naver_runtime.writer import Writer, DIAGNOSTIC_PHASE_IDS


class ReadDiagnosticsIntegrationTest(unittest.TestCase):
    def test_authorized_manual_read_is_available_during_busy_writer_without_queueing(self):
        fixture = D.DetailedCollectionStatusTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        entered, release = threading.Event(), threading.Event()
        failures = []

        class NoDatabaseStore:
            def close(self):
                pass

        writer = Writer("synthetic-only", factory=lambda path, clock: NoDatabaseStore())
        self.addCleanup(writer.close)
        observations = []

        def snapshot():
            observations.append(True)
            return writer.diagnostics()

        fixture.fixture.app._writer_diagnostics = snapshot

        def busy(store):
            entered.set()
            if not release.wait(2):
                raise AssertionError("synthetic release missing")

        def worker():
            try:
                writer.call(busy, _phase=DIAGNOSTIC_PHASE_IDS['performance_work'])
            except BaseException as error:
                failures.append(type(error).__name__)

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertEqual(fixture.fixture.call('/health?runtime=1')[0], 200)
            self.assertEqual(fixture.fixture.call('/health?collection=1', 100)[0], 403)
            self.assertEqual(observations, [])
            status, body = fixture.fixture.call('/health?collection=1')
            self.assertEqual(status, 200)
            self.assertEqual(set(body), {'collection', 'writer'})
            self.assertTrue(body['writer']['available'])
            self.assertEqual(body['writer']['active_phase'], 61)
            self.assertEqual(body['writer']['accepted'], 1)
            self.assertEqual(body['writer']['queue_depth'], 0)
            self.assertFalse(body['collection']['ledger_complete'])
            self.assertEqual(len(observations), 1)
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])


if __name__ == '__main__':
    unittest.main()
