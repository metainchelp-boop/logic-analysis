"""기존 콜백 호환과 실제 UNIX HTTP에서 Writer 대기 없는 상태 복구를 검증한다."""
import http.client
import json
from pathlib import Path
import socket
import sqlite3
import threading
import time
from unittest.mock import Mock, patch

from naver_engine import store as S, web as WEB
from naver_engine.tests.test_web import WebBase
from naver_runtime import collection_requests as CR
from naver_runtime.scheduler import Scheduler
from naver_runtime.server import UnixServer
from naver_runtime.tests.test_collection_requests import enabled
from naver_runtime.writer import Writer


INTEGRATION_METRICS = {}


class CollectionStatusCallbackTest(WebBase):
    def status_app(self, callback, **kwargs):
        self.app = self.make_app(owner_verification=True, verified_linking=True,
                                 collection_status=callback, **kwargs)
        return self.app

    def test_explicit_function_and_bound_method_receive_request_reader(self):
        for kind in ("function", "method"):
            with self.subTest(kind=kind):
                seen = []
                if kind == "function":
                    def callback(read_store=None):
                        seen.append(read_store)
                        return {"status": "idle"}
                    callback.read_store_supported = True
                else:
                    class Callback:
                        def status(self, *, read_store=None):
                            seen.append(read_store)
                            return {"status": "idle"}
                        status.read_store_supported = True
                    callback = Callback().status
                self.status_app(callback)
                self.assertTrue(self.app._collection_status_uses_reader)
                self.assertEqual(self.get("/collection/status", 0), (200, {"status": "idle"}))
                self.assertEqual(len(seen), 1)
                self.assertIsNot(seen[0], self.st)
                with self.assertRaises(sqlite3.ProgrammingError):
                    seen[0].access_log()

    def test_zero_arg_mock_and_nonexplicit_signatures_remain_legacy(self):
        calls = []
        def legacy():
            calls.append(())
            return {"status": "idle"}
        def kwargs_only(**kwargs):
            calls.append(kwargs)
            return {"status": "idle"}
        def positional_only(read_store=None, /):
            calls.append(read_store)
            return {"status": "idle"}
        def unmarked_keyword(read_store=None):
            calls.append(read_store)
            return {"status": "idle"}
        mock = Mock(return_value={"status": "idle"})
        for callback in (legacy, mock, kwargs_only, positional_only, unmarked_keyword):
            with self.subTest(callback=type(callback).__name__):
                self.status_app(callback)
                self.assertFalse(self.app._collection_status_uses_reader)
                self.assertEqual(self.get("/collection/status", 0), (200, {"status": "idle"}))
        self.assertEqual(calls, [(), {}, None, None])
        mock.assert_called_once_with()

    def test_explicit_protocol_ignores_signature_and_requires_strict_true_marker(self):
        calls = []
        class Legacy:
            @property
            def __signature__(self):
                raise AssertionError("콜백 signature를 자동 검사하지 않는다")
            def __call__(self):
                calls.append(())
                return {"status": "idle"}
        callback = Legacy()
        for marker in (False, None, 1, "True", {}, Mock()):
            with self.subTest(marker=type(marker).__name__):
                callback.read_store_supported = marker
                self.status_app(callback)
                self.assertFalse(self.app._collection_status_uses_reader)
                self.assertEqual(self.get("/collection/status", 0), (200, {"status": "idle"}))
        self.assertEqual(calls, [()] * 6)

    def test_callback_internal_typeerror_is_not_retried_without_reader(self):
        calls = []
        def callback(*, read_store=None):
            calls.append(read_store)
            raise TypeError("synthetic internal failure")
        callback.read_store_supported = True
        self.status_app(callback)
        status, body = self.get("/collection/status", 0)
        self.assertEqual((status, body), (500, {"error": "internal"}))
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(calls[0])
        with self.assertRaises(sqlite3.ProgrammingError):
            calls[0].access_log()

    def test_authorization_and_verification_refuse_before_callback(self):
        calls = []
        def callback(*, read_store=None):
            calls.append(read_store)
            return {"status": "idle"}
        callback.read_store_supported = True
        self.status_app(callback)
        self.assertTrue(self.app._collection_status_uses_reader)
        for actor, options in ((1, {}), (100, {}), (0, {"narrowed": True})):
            with self.subTest(actor=actor, options=options):
                self.assertEqual(self.get("/collection/status", actor, **options)[0], 403)
        self.app = self.make_app(owner_verification=True, verified_linking=False, collection_status=callback)
        self.assertEqual(self.get("/collection/status", 0), (403, {"error": "verification-read-only"}))
        self.status_app(callback)
        self.resign(0)
        self.assertEqual(self.get("/collection/status", 0)[0], 401)
        self.assertEqual(calls, [])

    def test_bound_scheduler_read_failure_closes_own_reader_without_write(self):
        task = Scheduler(enabled(), Mock(), collection_factory=lambda: self.fail("복구 재생 금지"),
                         clock=self.fc.now)
        raw_reader = S.open_reader(self.path)
        reader = Mock(wraps=raw_reader)
        reader.access_log.side_effect = S.StoreBusy("synthetic read failure")
        self.status_app(task.collection_status)
        self.app._open_read = Mock(return_value=reader)
        self.app._write_fn = Mock(side_effect=AssertionError("허가된 상태 조회 쓰기 금지"))
        self.assertEqual(self.get("/collection/status", 0),
                         (200, {"id": None, "status": "failed", "codes": ["AUDIT_UNAVAILABLE"]}))
        self.app._open_read.assert_called_once_with()
        reader.access_log.assert_called_once_with(limit=S.ACCESS_LOG_MAX_READ)
        reader.close.assert_called_once_with()
        self.app._write_fn.assert_not_called()
        self.assertIsNone(task._collection_latest)

    def test_missing_callback_keeps_unavailable_behavior(self):
        self.status_app(None)
        self.assertFalse(self.app._collection_status_uses_reader)
        self.assertEqual(self.get("/collection/status", 0), (503, {"error": "collection-unavailable"}))


class CollectionStatusBlockedWriterTest(WebBase):
    def test_actual_bound_scheduler_unix_http_reader_bypasses_fifteen_second_writer_wait(self):
        now = self.fc.now()
        request_id = self.st.record_access(0, "collection_request", "board", None, "accepted", now)
        self.st.record_access(0, "collection_run", "board", request_id, "refused", now)
        logs_before = self.st.access_log()
        self.st.close()
        writer = Writer(self.path, clock=self.fc.now)
        entered, release = threading.Event(), threading.Event()
        worker_errors, legacy_result, opened = [], [], []
        def blocked(store):
            entered.set()
            if not release.wait(25):
                raise AssertionError("synthetic Writer wait exceeded bound")
        def hold_writer():
            try:
                writer.call(blocked)
            except BaseException as exc:
                worker_errors.append(type(exc).__name__)
        task = Scheduler(enabled(), writer.proxy, collection_factory=lambda: self.fail("상태 조회 재생 금지"),
                         clock=self.fc.now)
        def old_path():
            before = time.monotonic()
            legacy_result.append((task.collection_status(), time.monotonic() - before))
        class Reader:
            def __init__(self, store):
                self.store, self.closed, self.access_calls = store, 0, 0
            def __getattr__(self, name):
                return getattr(self.store, name)
            def access_log(self, **kwargs):
                self.access_calls += 1
                return self.store.access_log(**kwargs)
            def close(self):
                self.closed += 1
                self.store.close()
        def open_read():
            reader = Reader(S.open_reader(self.path))
            opened.append(reader)
            return reader
        def no_write(fn):
            self.fail("허가된 상태 GET에서 쓰기 없음")
        self.app = WEB.App(open_read=open_read, write=no_write, signer=self.signer, profiles=self.app._profiles,
                           owner_verification=True, verified_linking=True, clock=self.fc.now,
                           collection_status=task.collection_status)
        self.assertTrue(self.app._collection_status_uses_reader)
        seen_readers = []
        original_recovery = CR.recovered_status
        def recovered(reader):
            seen_readers.append(reader)
            return original_recovery(reader)
        holder = threading.Thread(target=hold_writer)
        old_worker = threading.Thread(target=old_path)
        holder.start()
        try:
            self.assertTrue(entered.wait(5))
            socket_path = Path(self.path).parent / "collection-status.sock"
            with patch.object(CR, "recovered_status", side_effect=recovered), UnixServer(str(socket_path), self.app):
                before = time.monotonic()
                conn = http.client.HTTPConnection("local", timeout=3)
                conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                conn.sock.settimeout(3)
                conn.sock.connect(str(socket_path))
                try:
                    conn.request("GET", WEB.PREFIX + "/collection/status",
                                 headers={"Authorization": "Bearer " + self.token(0)})
                    response = conn.getresponse()
                    payload = json.loads(response.read())
                finally:
                    conn.close()
                fixed_elapsed = time.monotonic() - before
                self.assertEqual((response.status, payload),
                                 (200, {"id": request_id, "status": "refused", "codes": ["STATUS_FROM_AUDIT"]}))
                self.assertLess(fixed_elapsed, 2.0)
                self.assertFalse(release.is_set())
                self.assertTrue(holder.is_alive())
                self.assertEqual(len(opened), 1)
                self.assertEqual(seen_readers, opened)
                self.assertEqual((opened[0].closed, opened[0].access_calls), (1, 1))
            # 같은 Writer를 막은 상태에서 기존 0인자 경로는 실제 15초 대기 후 실패한다.
            old_worker.start()
            old_worker.join(18)
            self.assertFalse(old_worker.is_alive())
            self.assertEqual(legacy_result[0][0],
                             {"id": None, "status": "failed", "codes": ["AUDIT_UNAVAILABLE"]})
            self.assertGreaterEqual(legacy_result[0][1], 14.9)
            self.assertFalse(release.is_set())
            self.assertTrue(holder.is_alive())
            INTEGRATION_METRICS.update(fixed_seconds=fixed_elapsed, legacy_seconds=legacy_result[0][1],
                                       reader_connections=1, reader_closed=1, status_reads=1,
                                       authorized_writes=0, writer_blocked_during_fixed_response=True)
        finally:
            release.set()
            holder.join(5)
            if old_worker.ident is not None:
                old_worker.join(5)
            writer.close()
        self.assertFalse(holder.is_alive())
        self.assertEqual(worker_errors, [])
        with S.open_reader(self.path) as reader:
            self.assertEqual(reader.access_log(), logs_before)
