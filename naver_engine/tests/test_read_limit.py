"""GET 준비 상한 — 실제 WSGI·로컬 Store, 가짜 전산 로그인만 사용한다."""
import io
import json
from datetime import timedelta
from threading import Event, Lock, Thread, current_thread
from unittest.mock import patch

from naver_engine import store as S, web as WEB
from naver_engine.tests import test_alerts as TA
from naver_engine.tests.test_web import MARK_SSO, VERIFIER, WebBase


class ObservedGate:
    """실제 semaphore를 그대로 사용하고 대기 진입·동시 준비 수만 관찰한다."""
    def __init__(self, inner, waiter):
        self.inner, self.waiter = inner, waiter
        self.attempted, self.lock = Event(), Lock()
        self.active = self.peak = 0

    def __enter__(self):
        if current_thread().name == self.waiter:
            self.attempted.set()
        self.inner.__enter__()
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)

    def __exit__(self, *exc):
        with self.lock:
            self.active -= 1
        return self.inner.__exit__(*exc)


class ReadLimitTest(WebBase):
    def assert_released(self):
        gate = self.app._read_slots
        taken = 0
        try:
            while taken < 4 and gate.acquire(blocking=False):
                taken += 1
            self.assertEqual(taken, 4, "예외 뒤 GET 준비 차례가 남아 있지 않습니다")
            self.assertFalse(gate.acquire(blocking=False))
        finally:
            for _ in range(taken):
                gate.release()

    def test_four_gets_hold_through_response_and_login_bypasses_waiter(self):
        token = self.token(100)
        expected = self.call("GET", "/me", token)
        original_read = self.app._open_read
        reads, lock = [], Lock()
        entered = [Event() for _ in range(4)]
        release, finished = Event(), Event()
        results, errors = {}, []
        gate = ObservedGate(self.app._read_slots, "waiting-get")

        def open_read():
            with lock:
                reads.append(current_thread().name)
            return original_read()

        def get(index):
            captured = {}

            def start(status, headers):
                captured.update(status=int(status.split()[0]), headers=dict(headers))
                if index < 4:
                    entered[index].set()
                    if not release.wait(5):
                        raise AssertionError("응답 준비 시험 해제 지연")

            try:
                chunks = self.app({"REQUEST_METHOD": "GET", "PATH_INFO": WEB.PREFIX + "/me",
                    "QUERY_STRING": "", "wsgi.input": io.BytesIO(),
                    "HTTP_AUTHORIZATION": "Bearer " + token}, start)
                payload = b"".join(chunks)
                results[index] = (captured["status"], json.loads(payload), captured["headers"], payload)
            except BaseException as exc:
                errors.append(exc)
            finally:
                if index == 4:
                    finished.set()

        threads = [Thread(target=get, args=(i,), name=f"active-get-{i}", daemon=True) for i in range(4)]
        threads.append(Thread(target=get, args=(4,), name="waiting-get", daemon=True))
        with patch.object(self.app, "_read_slots", gate), patch.object(self.app, "_open_read", open_read):
            try:
                for i, thread in enumerate(threads[:4]):
                    thread.start()
                    self.assertTrue(entered[i].wait(3), errors)
                threads[4].start()
                self.assertTrue(gate.attempted.wait(3))
                self.assertFalse(finished.is_set())
                self.assertEqual(len(reads), 4, "다섯 번째 GET은 저장소를 열기 전에 기다려야 합니다")
                self.erp.person(MARK_SSO, 100)
                before = len([r for r in self.st.access_log() if r["action"] == "login"])
                status, _, _, _ = self.call("POST", "/session", body={"codeVerifier": VERIFIER, "code": MARK_SSO})
                self.assertEqual(status, 200)
                self.assertEqual(len([r for r in self.st.access_log() if r["action"] == "login"]), before + 1)
                self.assertFalse(finished.is_set(), "로그인은 GET 준비 차례를 빌리지 않습니다")
            finally:
                release.set()
                for thread in threads:
                    if thread.ident is not None:
                        thread.join(3)
            self.assertFalse(errors, [type(e).__name__ for e in errors])
            self.assertTrue(all(not t.is_alive() for t in threads))
            self.assertEqual((gate.peak, gate.active), (4, 0))
            self.assertEqual(results, {i: expected for i in range(5)})
        self.assert_released()

    def test_handled_and_escaping_errors_release_every_get_slot(self):
        token = self.token(100)
        for error, expected in ((WEB.HttpError(418, "test"), 418), (S.StoreBusy("test"), 503),
                                (RuntimeError("test"), 500), (KeyboardInterrupt(), None)):
            with self.subTest(error=type(error).__name__), patch.object(self.app, "_dispatch", side_effect=error):
                if expected is None:
                    with self.assertRaises(KeyboardInterrupt):
                        self.call("GET", "/me", token)
                else:
                    self.assertEqual(self.call("GET", "/me", token)[0], expected)
            self.assert_released()
        for body in ({"invalid": object()}, {"invalid": "\ud800"}):
            with self.subTest(serialization=type(body["invalid"]).__name__), patch.object(self.app, "_respond", return_value=(200, body)):
                self.assertEqual(self.call("GET", "/me", token)[:2], (500, {"error": "internal"}))
            self.assert_released()
        for location in ("serialization", "start-response"):
            with self.subTest(location=location):
                if location == "serialization":
                    with patch.object(WEB.json, "dumps", side_effect=MemoryError):
                        with self.assertRaises(MemoryError):
                            self.call("GET", "/me", token)
                else:
                    with self.assertRaises(ConnectionError):
                        self.app({"REQUEST_METHOD": "GET", "PATH_INFO": WEB.PREFIX + "/me",
                            "QUERY_STRING": "", "HTTP_AUTHORIZATION": "Bearer " + token},
                            lambda *_: (_ for _ in ()).throw(ConnectionError()))
            self.assert_released()

    def test_waiting_request_uses_current_clock_and_org_after_admission(self):
        for change in ("token-expired", "resigned", "owner", "org-stale"):
            with self.subTest(change=change):
                self.at(self.fc.now() + timedelta(minutes=6))
                self.st.record_org(TA.org_body(self.fc.now() - timedelta(minutes=5)), self.fc.now())
                token = self.token(100, now=self.fc.now() + timedelta(hours=27)) if change == "org-stale" else self.token(100)
                inner = self.app._read_slots
                gate = ObservedGate(inner, "fresh-get")
                result, errors = [], []
                reads, times = [], []
                original_read, original_clock = self.app._open_read, self.app._clock

                def run():
                    try:
                        result.append(self.call("GET", "/board", token, query="attention=0"))
                    except BaseException as exc:
                        errors.append(exc)

                for _ in range(4):
                    inner.acquire()
                thread = Thread(target=run, name="fresh-get", daemon=True)
                with patch.object(self.app, "_read_slots", gate), \
                     patch.object(self.app, "_open_read", side_effect=lambda: (reads.append(True), original_read())[1]), \
                     patch.object(self.app, "_clock", side_effect=lambda: (times.append(True), original_clock())[1]):
                    try:
                        thread.start()
                        self.assertTrue(gate.attempted.wait(3))
                        self.assertEqual((reads, times), ([], []))
                        if change == "token-expired":
                            self.at(self.fc.now() + timedelta(hours=1))
                        elif change == "resigned":
                            body = TA.org_body(self.fc.now())
                            for employee in body["employees"]:
                                if employee["idx"] == 100:
                                    employee["status"] = "RESIGNED"
                            self.st.record_org(body, self.fc.now())
                        elif change == "owner":
                            self.st.record_org(TA.org_body(self.fc.now(), owners=[TA.owner(11, 101), TA.owner(12, 101),
                                                                                TA.owner(14, 100)]), self.fc.now())
                        else:
                            self.at(self.fc.now() + timedelta(hours=27))
                    finally:
                        for _ in range(4):
                            inner.release()
                        thread.join(3)
                self.assertFalse(thread.is_alive())
                self.assertFalse(errors, [type(e).__name__ for e in errors])
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0], self.call("GET", "/board", token, query="attention=0"))
                status, body, _, _ = result[0]
                if change in ("token-expired", "resigned", "org-stale"):
                    self.assertEqual((status, body["error"]), {"token-expired": (401, "token-expired"),
                        "resigned": (401, "no-scope"), "org-stale": (503, "org-stale")}[change])
                else:
                    self.assertEqual(status, 200)
                    self.assertEqual({r["possibility_id"] for r in body["rows"]}, {14})
                self.assert_released()
