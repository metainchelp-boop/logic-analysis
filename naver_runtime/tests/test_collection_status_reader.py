"""수집 상태의 감사 읽기는 요청 Reader를 사용하며 재시작 요청을 재생하지 않는다."""
from copy import deepcopy
from threading import Event
from unittest import TestCase
from unittest.mock import MagicMock, patch

from naver_engine import store as S
from naver_runtime.scheduler import Scheduler
from naver_runtime import __main__ as MAIN
from naver_runtime.config import Config
from naver_runtime.tests.test_collection_requests import AuditStore, NOW, enabled


class StatusReader(AuditStore):
    def __init__(self, *, failure=False, falsey=False):
        super().__init__()
        self.calls, self.failure, self.falsey = 0, failure, falsey

    def __bool__(self):
        return not self.falsey

    def access_log(self, **kwargs):
        self.calls += 1
        if self.failure:
            raise S.StoreBusy("synthetic read failure")
        return super().access_log(**kwargs)


class CollectionStatusReaderTest(TestCase):
    def test_real_runtime_assembly_selects_bound_scheduler_reader_callback(self):
        stop, assembled = Event(), []
        stop.set()
        original_app = MAIN.WEB.App
        def assemble(**kwargs):
            app = original_app(**kwargs)
            assembled.append(app)
            return app
        env = {"SSO_NAVER_CONTROL_CLIENT_KEY": "0123456789abcdef" * 4,
               "NAVER_AUTO_TOKEN_SECRET": "local-test-token-signing-value-000000000000"}
        with patch.object(MAIN, "Writer", return_value=MagicMock()), \
             patch.object(MAIN, "UnixServer", return_value=MagicMock()), \
             patch.object(MAIN.WEB, "App", side_effect=assemble):
            self.assertEqual(MAIN.run(Config("/tmp/synthetic/data/db", "/tmp/synthetic/socket/api",
                                             web_enabled=True), env, stop=stop), 0)
        self.assertEqual(len(assembled), 1)
        self.assertTrue(assembled[0]._collection_status_uses_reader)
        self.assertIsInstance(assembled[0]._collection_status.__self__, Scheduler)

    def task(self, store):
        return Scheduler(enabled(), store, collection_factory=lambda: self.fail("복구 조회에서 재생 금지"),
                         clock=lambda: NOW)

    def accepted(self, store):
        return store.record_access(0, "collection_request", "board", None, "accepted", NOW)

    def test_terminal_audit_and_interrupted_request_are_fresh_without_cache_or_replay(self):
        proxy, reader = StatusReader(failure=True), StatusReader()
        task = self.task(proxy)
        request = self.accepted(reader)
        self.assertEqual(task.collection_status(read_store=reader),
                         {"id": request, "status": "failed", "codes": ["PROCESS_RESTARTED_NOT_REPLAYED"]})
        reader.record_access(0, "collection_run", "board", request, "refused", NOW)
        before = deepcopy(reader.logs)
        self.assertEqual(task.collection_status(read_store=reader),
                         {"id": request, "status": "refused", "codes": ["STATUS_FROM_AUDIT"]})
        self.assertIsNone(task._collection_latest)
        self.assertIsNone(task._collection_pending)
        self.assertEqual(reader.logs, before)
        self.assertEqual((proxy.calls, reader.calls), (0, 2))

    def test_current_memory_accepted_running_and_final_take_priority_and_are_copied(self):
        proxy, reader = StatusReader(failure=True), StatusReader(failure=True)
        task = self.task(proxy)
        for status in ("accepted", "running", "done", "partial", "refused", "failed"):
            with self.subTest(status=status):
                latest = {"id": 3, "status": status, "codes": ["CURRENT"], "extra": {"count": 1}}
                task._collection_latest = latest
                result = task.collection_status(read_store=reader)
                self.assertEqual(result, latest)
                result["codes"].append("mutated")
                result["extra"]["count"] = 9
                self.assertEqual(latest["codes"], ["CURRENT"])
                self.assertEqual(latest["extra"]["count"], 1)
        self.assertEqual((proxy.calls, reader.calls), (0, 0))

    def test_falsey_reader_is_used_and_legacy_no_reader_still_uses_own_store(self):
        proxy, reader = StatusReader(), StatusReader(falsey=True)
        request = self.accepted(reader)
        task = self.task(proxy)
        self.assertEqual(task.collection_status(read_store=reader)["id"], request)
        self.assertEqual((proxy.calls, reader.calls), (0, 1))
        self.assertEqual(task.collection_status(), {"id": None, "status": "idle", "codes": []})
        self.assertEqual((proxy.calls, reader.calls), (1, 1))

    def test_read_failure_is_closed_and_never_becomes_cached_status(self):
        proxy, reader = StatusReader(failure=True), StatusReader(failure=True)
        task = self.task(proxy)
        self.assertEqual(task.collection_status(read_store=reader),
                         {"id": None, "status": "failed", "codes": ["AUDIT_UNAVAILABLE"]})
        self.assertIsNone(task._collection_latest)
        reader.failure = False
        self.assertEqual(task.collection_status(read_store=reader),
                         {"id": None, "status": "idle", "codes": []})
        self.assertEqual((proxy.calls, reader.calls), (0, 2))

    def test_disabled_collection_factory_does_not_read_either_store(self):
        proxy, reader = StatusReader(failure=True), StatusReader(failure=True)
        task = Scheduler(enabled(), proxy, clock=lambda: NOW)
        self.assertEqual(task.collection_status(read_store=reader),
                         {"id": None, "status": "idle", "codes": []})
        self.assertEqual((proxy.calls, reader.calls), (0, 0))
