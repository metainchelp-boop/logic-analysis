"""관리 파일 단회 실행: 임시 개인 폴더/합성 자료만 사용한다."""
import json
import os
import stat
import hashlib
import platform
import sqlite3
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch
from types import SimpleNamespace

from naver_engine.tests.test_requested import NOW, EmptyStore
from naver_engine.tests.fake_naver import FakeClock
from naver_engine.tests.test_sync import org_payload
from naver_engine import store as S
from naver_runtime.config import Config
from naver_runtime import bootstrap as B


def request(**change):
    body = dict(request_id="a" * 32, hold_id=7, hold_sha256="b" * 64, expected_rows=2,
                approved_by=0, expires_at=(NOW + timedelta(minutes=30)).isoformat(), max_seconds=600)
    body.update(change)
    return body


class RequestTest(TestCase):
    def test_schema_is_exact_and_bounded_without_echoing_input(self):
        self.assertEqual(B.parse_request(json.dumps(request()).encode(), NOW)["hold_id"], 7)
        for changes in ({"extra": "SECRET"}, {"approved_by": False}, {"approved_by": 1},
                        {"max_seconds": 601}, {"max_seconds": True}, {"hold_id": 0},
                        {"request_id": "../SECRET"}, {"hold_sha256": "SECRET"},
                        {"expected_rows": True}, {"expires_at": NOW.isoformat()},
                        {"expires_at": (NOW + timedelta(days=1)).isoformat()}):
            with self.subTest(changes=changes), self.assertRaises(B.BootstrapRefused) as error:
                B.parse_request(json.dumps(request(**changes)).encode(), NOW)
            self.assertNotIn("SECRET", str(error.exception))
        with self.assertRaises(B.BootstrapRefused):
            B.parse_request(b'{"request_id":"first","request_id":"second"}', NOW)

    def test_secure_file_and_exclusive_durable_receipt(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / "request.json"
            path.write_bytes(json.dumps(request()).encode())
            path.chmod(0o440)
            files = B.BootstrapFiles(path, root, root / "snapshots", os.geteuid(), os.getegid())
            self.assertEqual(B.read_request(files, NOW)["hold_id"], 7)
            path.chmod(0o640)
            with self.assertRaises(B.BootstrapRefused):
                B.read_request(files, NOW)
            path.chmod(0o440)
            alias = root / "alias"
            alias.symlink_to(path)
            unsafe = B.BootstrapFiles(alias, root, root / "snapshots", os.geteuid(), os.getegid())
            with self.assertRaises(B.BootstrapRefused):
                B.read_request(unsafe, NOW)
            receipt = root / "receipt.json"
            B.publish_receipt(receipt, {"status": "started"})
            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                B.publish_receipt(receipt, {"status": "completed"})
            self.assertEqual(json.loads(receipt.read_text()), {"status": "started"})


class BootstrapStore(EmptyStore):
    def __init__(self):
        super().__init__()
        self.events = []
        self.h = dict(hold_id=7, at=NOW, used_at=None, used_by=None,
                      body=dict(as_of=NOW.isoformat(), rows=[[], []], conflicts=[]))
        self.org = dict(body=org_payload(NOW), generated_at=NOW)
    def hold(self, kind): return self.h
    def hold_body_sha256(self, kind, hid): return "b" * 64
    def org_current(self): return self.org
    def snapshot_to(self, path):
        self.events.append("snapshot")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(fd, b"synthetic sqlite stand-in")
        os.close(fd)
        return {"synthetic": 1}
    def confirm_prospects_hold(self, hid, by):
        self.events.append("confirm")
        self.h["used_at"] = NOW
        return SimpleNamespace(present=2, now_absent=0)
    def thresholds(self): return B.M.DEFAULTS


class ExecutionTest(TestCase):
    def test_preflight_error_reports_only_known_fixed_code(self):
        config = Config("/data/db", "/socket/api", sync_enabled=True, links_enabled=True,
                        morning_enabled=True, web_enabled=True)
        env = {"NAVER_ENGINE_BOOTSTRAP_REQUEST": str(B.BootstrapFiles().request)}
        for error, expected in ((B.BootstrapRefused("REQUEST_FILE"), "REQUEST_FILE"),
                                (B.BootstrapRefused("SECRET raw payload"), "INTERNAL_ERROR"),
                                (RuntimeError("SECRET raw payload"), "INTERNAL_ERROR")):
            with self.subTest(expected=expected), patch.object(B, "read_request", side_effect=error):
                result = B.execute(config, env, None, FakeClock(NOW), None)
            self.assertEqual(result["error_code"], expected)
            self.assertNotIn("SECRET", json.dumps(result))

    def test_snapshot_precedes_confirmation_and_restart_never_repeats(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / "request.json"
            path.write_bytes(json.dumps(request()).encode())
            path.chmod(0o440)
            files = B.BootstrapFiles(path, root, root / "snapshots", os.geteuid(), os.getegid())
            store = BootstrapStore()
            writer = SimpleNamespace(call=lambda fn: fn(store), proxy=store)
            factory = Mock(return_value=dict(erp_factory=Mock(), naver_factory=Mock()))
            pair = SimpleNamespace(outcome=S.SYNC_ACCEPTED, pairing_id=1, counts={"auto": 2}, codes=())
            done = SimpleNamespace(outcome="done", run_id=1, counts={"targets": 2, "ok": 1, "account_error": 1}, codes=())
            config = Config("/data/db", "/socket/api", sync_enabled=True, links_enabled=True,
                            morning_enabled=True, web_enabled=True)
            env = {"NAVER_ENGINE_BOOTSTRAP_REQUEST": str(path)}
            with patch.object(B.L, "pair_links", return_value=pair) as pairing, \
                 patch.object(B.M, "run_requested", return_value=done) as morning:
                result = B.execute(config, env, writer, FakeClock(NOW), factory, files=files)
                self.assertEqual(result["status"], "partial")
                self.assertEqual(store.events, ["snapshot", "confirm"])
                self.assertEqual(B.execute(config, env, writer, FakeClock(NOW), factory, files=files)["status"], "already_started")
                pairing.assert_called_once()
                morning.assert_called_once()
            started = json.loads((root / ("bootstrap-" + "a" * 32 + ".json")).read_text())
            self.assertEqual(started["status"], "started")
            self.assertNotIn("body", json.dumps(result))

    def test_missing_environment_performs_no_file_or_store_io(self):
        with patch.object(B, "read_request", side_effect=AssertionError):
            self.assertEqual(B.execute(None, {}, None, None, None), {"status": "disabled"})

    def test_expired_changed_digest_demoted_owner_and_yesterday_source_refuse(self):
        for change in ("digest", "owner", "yesterday", "used", "count"):
            store = BootstrapStore()
            wanted = request()
            if change == "digest": wanted["hold_sha256"] = "c" * 64
            if change == "owner": store.org["body"]["employees"][0]["status"] = "RESIGNED"
            if change == "yesterday": store.h["body"]["as_of"] = (NOW - timedelta(days=1)).isoformat()
            if change == "used": store.h["used_at"] = NOW
            if change == "count": wanted["expected_rows"] = 1
            with self.subTest(change=change), self.assertRaises(Exception):
                B._verify(store, wanted, NOW)
            self.assertEqual(store.events, [])
        with self.assertRaises(B.BootstrapRefused):
            B._verify(BootstrapStore(), request(), NOW + timedelta(hours=4))

    def test_budget_cannot_sleep_past_limit_and_does_not_falsify_time(self):
        clock = FakeClock(NOW)
        bounded = B.BootstrapClock(clock, 2, NOW + timedelta(seconds=20))
        self.assertEqual(bounded.remaining(), 2)
        with self.assertRaises(B.N.RunAbort):
            bounded.sleep(300)
        self.assertEqual(bounded.now(), NOW + timedelta(seconds=2))
        with self.assertRaises(B.N.RunAbort): bounded.before_network()

    def test_exact_stored_text_hash_not_reserialized_json(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE naver_auto_hold(kind TEXT, sync_id INTEGER, body TEXT)")
        text = '{ "비교" : 1, "a": 2 }'
        connection.execute("INSERT INTO naver_auto_hold VALUES ('stages', 7, ?)", (text,))
        store = S.Store.__new__(S.Store)
        store._conn = connection
        self.assertEqual(store.hold_body_sha256("stages", 7), hashlib.sha256(text.encode()).hexdigest())
        self.assertNotEqual(store.hold_body_sha256("stages", 7),
                            hashlib.sha256(json.dumps(json.loads(text), sort_keys=True).encode()).hexdigest())


@skipUnless(platform.system() == "Linux", "실제 Writer/WAL은 Linux CI에서 검증")
class RealStoreBootstrapTest(TestCase):
    def test_real_writer_snapshot_accept_pair_and_synthetic_naver_get(self):
        from naver_runtime.writer import Writer
        from naver_engine import erp_read as E, naver_read as N
        from naver_engine.tests.test_morning import FakeErp, creds, Ads, quiet, shop, A
        from naver_engine.tests.fake_naver import FakeNaver
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            data, backup = root / "data", root / "backup"
            data.mkdir(mode=0o700)
            backup.mkdir(mode=0o700)
            files = B.BootstrapFiles(data / "request.json", data / "bootstrap", backup / "bootstrap",
                                     os.geteuid(), os.getegid())
            clock, transport = FakeClock(NOW), FakeNaver()
            ads = Ads(transport)
            ads.cycle = NOW.replace(hour=5)
            ads.add(A, [(1, "ELIGIBLE", False, quiet)], biz=1000.0)
            with Writer(str(data / "db"), clock=clock.now) as writer:
                writer.call(lambda st: st.record_org(org_payload(NOW), NOW))
                snapshot = E.StageSnapshot({11: E.StageRow(11, "진행중", shop(11), None, False)}, NOW, {}, ())
                hid = writer.call(lambda st: st.refuse_stages(snapshot, (B.Y.CODE_IMPLAUSIBLE_FIRST,)))
                writer.call(lambda st: st.record_accounts(N.ChildAccounts(
                    {A: {"customerId": A, "adAccountNo": A + 1, "adAccountName": shop(11)}}, {1: 1}, ()), NOW))
                digest = writer.call(lambda st: st.hold_body_sha256("stages", hid))
                files.request.write_bytes(json.dumps(request(hold_id=hid, hold_sha256=digest, expected_rows=1)).encode())
                files.request.chmod(0o440)
                def factories(bounded):
                    return dict(erp_factory=lambda: FakeErp([E.NaverIdRow(11, "NAVER_SEARCHAD", str(A))]),
                                naver_factory=lambda: N.NaverReader(creds(), clock=bounded, transport=transport))
                config = Config(str(data / "db"), str(root / "api"), sync_enabled=True, links_enabled=True,
                                morning_enabled=True, web_enabled=True)
                result = B.execute(config, {"NAVER_ENGINE_BOOTSTRAP_REQUEST": str(files.request)},
                                   writer, clock, factories, files=files)
                self.assertEqual(result["accepted_rows"], 1, result)
                self.assertEqual(result["pairing_outcome"], S.SYNC_ACCEPTED, result)
                self.assertIsNotNone(result.get("run_id"), result)
                self.assertTrue(transport.calls, result)
                self.assertTrue(all(call.method == "GET" for call in transport.calls))
                self.assertEqual(writer.call(lambda st: st.hold("stages")["used_by"]), 0)
                count = len(transport.calls)
                self.assertEqual(B.execute(config, {"NAVER_ENGINE_BOOTSTRAP_REQUEST": str(files.request)},
                                          writer, clock, factories, files=files)["status"], "already_started")
                self.assertEqual(len(transport.calls), count)
                self.assertTrue((files.snapshots / ("a" * 32 + ".sqlite")).is_file())
