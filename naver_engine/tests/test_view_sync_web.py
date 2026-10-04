"""변경분 공개 GET 계약: 합성 저장소만 사용하고 외부 송신을 금지한다."""
import socket
import sqlite3
import unittest
import json
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

from naver_engine.tests import test_web as TW
from naver_engine.tests import test_report_paging as RP


class SnapshotReports(RP.ReadReports):
    def __init__(self, rows):
        super().__init__(rows)
        self.events = []
        self.database = None
        self.open_transaction_on_close = None

    @contextmanager
    def read_snapshot(self):
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.database = TW.S.Store(self.connection, ":memory:", None, False)
        try:
            with self.database.read_snapshot():
                self.events.append("begin")
                yield
        finally:
            self.events.append("end")

    def org_current(self):
        self.events.append("org")
        return super().org_current()

    def report_snapshots(self):
        self.events.append("reports")
        return super().report_snapshots()

    def close(self):
        if self.database is not None:
            self.open_transaction_on_close = self.connection.in_transaction
            self.database.close()
            self.database = None
        self.events.append("close")


class ViewSyncWebTest(unittest.TestCase):
    call = TW.WebBase.call

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지")))
        self.signer = TW.SE.TokenSigner(TW.Secret(TW.TOKEN_SECRET))
        self.store = SnapshotReports([RP.report(1, 11), RP.report(2, 12)])
        self.now = RP.NOW
        def forbidden(*args, **kwargs):
            self.fail("조회는 쓰기·네트워크·수집을 실행할 수 없습니다")
        self.app = TW.WEB.App(open_read=lambda: self.store, write=forbidden, signer=self.signer,
            profiles=forbidden, clock=lambda: self.now, owner_verification=True,
            request_collection=forbidden, collection_status=forbidden)

    def get(self, query="", viewer=0, token=None):
        return self.call("GET", "/reports", token or self.signer.issue(viewer, self.now), query=query)

    def test_first_opt_in_response_keeps_the_legacy_payload_and_no_store(self):
        original = self.get()[1]
        status, body, headers, _ = self.get("view_sync=1")
        self.assertEqual(status, 200)
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["mode"], "full")
        self.assertEqual(body["data"], original)
        self.assertIsNone(body["rows"])
        self.assertIsNone(body["base_cursor"])
        self.assertIsInstance(body["cursor"], str)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_same_response_sends_only_the_check_result(self):
        first = self.get("view_sync=1")[1]
        status, body, _, raw = self.get("view_sync=1&view_cursor=" + first["cursor"])
        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "unchanged")
        self.assertEqual(body["base_cursor"], first["cursor"])
        self.assertIsNone(body["data"])
        self.assertIsNone(body["rows"])
        self.assertNotIn("합성 업체".encode(), raw)

    def test_add_correction_removal_and_order_reconstruct_current_full_response(self):
        first = self.get("view_sync=1")[1]
        revised = RP.report(3, 11)
        revised["payload"]["totals"]["spend"] = 100
        added = RP.report(4, 11, RP.payload(RP.R.period("weekly", date(2026, 9, 14))))
        self.store.rows[:] = [added, revised]
        status, body, _, _ = self.get("view_sync=1&view_cursor=" + first["cursor"])
        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "delta")
        patch_rows = body["rows"]
        self.assertEqual(patch_rows["key_fields"], ["possibility_id", "period_key"])
        def key(row):
            return json.dumps([row[field] for field in patch_rows["key_fields"]], separators=(",", ":"))
        merged = {key(row): row for row in first["data"]["rows"]}
        self.assertEqual(len(patch_rows["removed"]), 1)
        for removed in patch_rows["removed"]:
            merged.pop(removed)
        for row in patch_rows["upsert"]:
            merged[key(row)] = row
        result = {**body["data"], "rows": [merged[key] for key in patch_rows["order"]]}
        self.assertEqual(result, self.get()[1])

    def test_new_login_cannot_reuse_an_identical_response_from_previous_login(self):
        first = self.get("view_sync=1")[1]
        self.now += timedelta(seconds=1)
        response = self.get("view_sync=1&view_cursor=" + first["cursor"])[1]
        self.assertEqual(response["mode"], "full")
        self.assertEqual(response["data"], self.get()[1])

    def test_permission_and_payload_reads_share_one_closed_snapshot(self):
        status, _, _, _ = self.get("view_sync=1")
        self.assertEqual(status, 200)
        self.assertEqual(self.store.events[0], "begin")
        self.assertLess(self.store.events.index("org"), self.store.events.index("reports"))
        self.assertEqual(self.store.events[-2:], ["end", "close"])
        self.assertFalse(self.store.open_transaction_on_close)

    def test_other_user_selection_and_narrowing_cursors_are_not_reused(self):
        first = self.get("view_sync=1")[1]
        query = "view_sync=1&view_cursor=" + first["cursor"]
        cases = [(query, 100, None), (query+"&selection=person:100", 0, None),
                 (query, 0, self.signer.issue(0, self.now, narrowed=True))]
        for selected, viewer, token in cases:
            with self.subTest(viewer=viewer, selected=selected):
                status, body, _, _ = self.get(selected, viewer, token)
                self.assertEqual(status, 200)
                self.assertEqual(body["mode"], "full")
                self.assertIsNone(body["base_cursor"])
                original_query = selected.replace(query, "").lstrip("&")
                self.assertEqual(body["data"], self.get(original_query, viewer, token)[1])

    def test_token_refresh_keeps_login_generation_but_midnight_resets_cursor(self):
        self.now = RP.NOW.replace(hour=23, minute=55)
        self.store.catalog["generated_at"] = self.now.isoformat()
        token = self.signer.issue(0, self.now)
        first = self.get("view_sync=1", token=token)[1]
        self.now += timedelta(minutes=1)
        refreshed = self.signer.refresh(self.signer.verify(token, self.now), self.now)
        query = "view_sync=1&view_cursor=" + first["cursor"]
        self.assertEqual(self.get(query, token=refreshed)[1]["mode"], "unchanged")
        self.now += timedelta(minutes=5)
        body = self.get(query, token=refreshed)[1]
        self.assertEqual(body["mode"], "full")
        self.assertIsNone(body["base_cursor"])

    def test_organization_change_and_unknown_cursor_return_current_full_only(self):
        first = self.get("view_sync=1")[1]
        self.store.body["employees"][0]["name"] = "변경된 대표"
        for cursor in (first["cursor"], "unknown-cursor"):
            body = self.get("view_sync=1&view_cursor=" + cursor)[1]
            self.assertEqual(body["mode"], "full")
            self.assertIsNone(body["base_cursor"])
            self.assertEqual(body["data"], self.get()[1])

    def test_read_failure_closes_real_memory_transaction_and_preserves_503(self):
        class FailedReports(SnapshotReports):
            def report_snapshots(self):
                raise TW.S.StoreError("합성 읽기 실패")
        self.store = FailedReports([RP.report(1, 11)])
        status, body, _, _ = self.get("view_sync=1")
        self.assertEqual((status, body), (503, {"error": "store-unavailable"}))
        self.assertEqual(self.store.events[-2:], ["end", "close"])
        self.assertFalse(self.store.open_transaction_on_close)

    def test_snapshot_entry_failure_closes_once_and_preserves_503(self):
        class FailedSnapshot(SnapshotReports):
            @contextmanager
            def read_snapshot(self):
                with super().read_snapshot():
                    raise TW.S.StoreError("합성 스냅숏 진입 실패")
                    yield
        self.store = FailedSnapshot([RP.report(1, 11)])
        status, body, _, _ = self.get("view_sync=1")
        self.assertEqual((status, body), (503, {"error": "store-unavailable"}))
        self.assertEqual(self.store.events, ["begin", "end", "close"])
        self.assertFalse(self.store.open_transaction_on_close)

    def test_protocol_queries_are_strict_and_do_not_expand_the_route_allowlist(self):
        for query in ("view_cursor=x", "view_sync=0", "view_sync=1&view_sync=1",
                      "view_sync=1&view_cursor=x&view_cursor=y", "view_sync=1&view_cursor=" + "x" * 129):
            with self.subTest(query=query):
                self.assertEqual(self.get(query)[0], 400)
        self.assertEqual(self.store.events, [])
        self.assertEqual(self.call("GET", "/links/pending", self.signer.issue(0, self.now),
                                   query="view_sync=1")[0], 400)
        self.assertEqual(self.call("GET", "/reports", query="view_sync=1")[0], 401)
        self.assertEqual(self.store.events, [])

    def test_resigned_and_stale_permissions_keep_errors_and_close_real_memory_snapshot(self):
        first = self.get("view_sync=1", viewer=100)[1]
        for employee in self.store.body["employees"]:
            if employee["idx"] == 100:
                employee["status"] = "RESIGNED"
        status, body, _, _ = self.get("view_sync=1&view_cursor=" + first["cursor"], viewer=100)
        self.assertEqual((status, body), (401, {"error": "no-scope"}))
        self.assertEqual(self.store.events[-2:], ["end", "close"])
        self.assertFalse(self.store.open_transaction_on_close)
        for employee in self.store.body["employees"]:
            employee["status"] = "ACTIVE"
        self.now += timedelta(hours=30)
        status, body, _, _ = self.get("view_sync=1&view_cursor=" + first["cursor"], viewer=100)
        self.assertEqual((status, body), (503, {"error": "org-stale"}))
        self.assertFalse(self.store.open_transaction_on_close)
