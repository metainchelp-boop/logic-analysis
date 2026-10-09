"""임시 WAL/Store 거래의 문안 판 계약. macOS에서는 기존 open_writer inode-lock을 제외한다.

Darwin의 flock와 SQLite fcntl 잠금 충돌은 이 기능 밖의 기존 writer 회귀로 별도 검증한다.
아래 fixture도 실제 파일·SQL authorizer·Store migration/transaction/권한 검사를 사용한다.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from naver_engine import reporting as R, store as S
from naver_engine.tests import test_alerts as TA, test_account_catalog as TC
from naver_engine.tests.test_reporting import WEEK, daily_rows
from naver_engine.report_views import account_key
from app.naver_auto import scope as SC


class ReportNotesTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 9, 10, tzinfo=S.KST)
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "notes.db")
        self.st = self.open_store()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(lambda: self.st.close())
        self.st.record_org(TA.org_body(self.now), self.now)
        self.st.record_account_catalog({"generated_at": self.now.isoformat(), "total": 1,
            "complete": True, "items": [TC.company(11, "진행중")]}, [], self.now)
        self.payload = R.snapshot(WEEK, (101, 202), daily_rows(customers=(101, 202)), self.now)
        self.fingerprint = self.payload["revision_fingerprint"]
        self.seed(1)
        self.key = account_key(101)
        self.doc = {"internal_note": "내부 점검 메모", "client_feedback": "광고주 요청 원문 기록",
                    "shared_comment": "확인된 자료 안내", "next_plan": "추적 상태 확인",
                    "plan_due": "2026-10-15", "targets": {"cpa": 0, "roas": 500,
                        "spend_per_day": 10000, "source": "2026-10-08 담당자 합의"}}

    def open_store(self):
        if sys.platform != "darwin":
            return S.open_writer(self.path, clock=lambda: self.now)
        conn = sqlite3.connect(self.path, isolation_level=None)
        os.chmod(self.path, 0o600)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        store = S.Store(conn, self.path, None, writer=True, clock=lambda: self.now)
        store._migrate()
        conn.set_authorizer(S._authorizer(S.PHASE_RUN))
        return store

    def seed(self, rid, fingerprint=None):
        payload = {**self.payload, "revision_fingerprint": fingerprint or self.fingerprint}
        self.st._conn.execute("""INSERT INTO naver_auto_report_snapshot
            (report_id,possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
            VALUES(?,11,?,?,?,'ready','not_required',?)""", (rid, WEEK.key,
                fingerprint or self.fingerprint, self.now.isoformat(), json.dumps(payload)))

    def read(self, rid=1, key=None, fingerprint=None):
        return self.st.report_notes(rid, key or self.key, fingerprint or self.fingerprint)

    def save(self, version=0, document=None, **kwargs):
        return self.st.record_report_notes(kwargs.pop("report_id", 1), kwargs.pop("account_key", self.key),
            kwargs.pop("revision_fingerprint", self.fingerprint), kwargs.pop("actor", 100), self.now,
            expected_version=version, action=kwargs.pop("action", "save"),
            document=self.doc if document is None else document, **kwargs)

    def approve(self, version=1):
        return self.st.record_report_notes(1, self.key, self.fingerprint, 0, self.now,
            expected_version=version, action="approve")

    def test_missing_notes_are_empty_without_reusing_review_reason_or_writing(self):
        self.st._conn.execute("""INSERT INTO naver_auto_report_review(report_id,actor,at,decision,note)
            VALUES(1,100,?,'approved','기존 검토사유는 업무계획이 아님')""", (self.now.isoformat(),))
        before = self.st._conn.total_changes
        notes = self.read()
        self.assertEqual((notes["version"], notes["state"]), (0, "empty"))
        self.assertEqual(notes["document"]["next_plan"], "")
        self.assertIsNone(notes["shared"])
        self.assertEqual(self.st._conn.total_changes, before)

    def test_save_approve_edit_append_versions_and_never_change_report_payload_or_schema(self):
        report = self.st.report_snapshot_detail(1)
        original = deepcopy(self.doc)
        first = self.save()
        self.assertEqual((first["version"], first["state"]), (1, "draft"))
        self.assertIsNone(first["shared"])
        self.assertEqual(first["metadata"]["period"], {field: self.payload["period"][field]
            for field in ("kind", "start", "end")})
        self.assertEqual(self.doc, original)
        approved = self.approve()
        self.assertEqual((approved["version"], approved["state"]), (2, "approved"))
        self.assertEqual(approved["approved_by"], 0)
        for private in ("internal_note", "client_feedback", "내부 점검 메모", "광고주 요청 원문 기록"):
            self.assertNotIn(private, json.dumps(approved["shared"], ensure_ascii=False))
        self.assertEqual(approved["shared"]["shared_comment"], self.doc["shared_comment"])
        third = self.save(2, {**self.doc, "shared_comment": "정정 문안"})
        self.assertEqual((third["version"], third["state"]), (3, "draft"))
        self.assertIsNone(third["shared"])
        history = self.st.report_notes_history(1, self.key, self.fingerprint)
        self.assertEqual([row["version"] for row in history["items"]], [3, 2, 1])
        self.assertEqual(history["items"][1]["approved_by"], 0)
        self.assertEqual(history["items"][1]["document"]["shared_comment"], original["shared_comment"])
        self.assertEqual(self.st.report_snapshot_detail(1), report)
        self.assertEqual(self.st.meta("schema_version"), "11")

    def test_notes_survive_reopen_and_reader_cannot_write(self):
        self.save()
        self.approve()
        self.st.close()
        self.st = self.open_store()
        self.assertEqual(self.read()["version"], 2)
        with S.open_reader(self.path) as reader:
            self.assertEqual(reader.report_notes(1, self.key, self.fingerprint)["state"], "approved")
            with self.assertRaises(S.StoreRefused):
                reader.record_report_notes(1, self.key, self.fingerprint, 100, self.now,
                    expected_version=2, action="save", document=self.doc)

    def test_same_expected_version_cannot_overwrite_or_approve_changed_document(self):
        self.save()
        before = self.st._conn.total_changes
        for action in ("save", "approve"):
            with self.subTest(action=action), self.assertRaises(S.StoreRefused):
                self.st.record_report_notes(1, self.key, self.fingerprint, 100, self.now,
                    expected_version=0, action=action, document=self.doc if action == "save" else None)
        self.assertEqual(self.st._conn.total_changes, before)
        self.assertEqual(self.read()["version"], 1)

    def test_approval_requires_existing_draft_and_cannot_modify_content_or_reapprove(self):
        with self.assertRaises(S.StoreRefused):
            self.approve(0)
        self.save()
        with self.assertRaises(S.StoreRefused):
            self.st.record_report_notes(1, self.key, self.fingerprint, 100, self.now,
                expected_version=1, action="approve", document=self.doc)
        self.approve()
        with self.assertRaises(S.StoreRefused):
            self.approve(2)

    def test_account_company_and_report_versions_never_inherit_notes(self):
        self.save()
        self.approve()
        self.assertEqual(self.read(key="company")["version"], 0)
        self.assertEqual(self.read(key=account_key(202))["version"], 0)
        self.seed(2, "a" * 64)
        self.assertEqual(self.read(rid=2, fingerprint="a" * 64)["version"], 0)
        with self.assertRaises(S.StoreRefused):
            self.save(2)
        self.assertEqual(self.read()["version"], 2)

    def test_writer_rechecks_latest_after_scope_validation_in_same_transaction(self):
        original = S._report_require_scope
        def changed(store, *args):
            original(store, *args)
            self.seed(2, "b" * 64)
        with patch.object(S, "_report_require_scope", side_effect=changed), self.assertRaises(S.StoreRefused):
            self.save()
        self.assertEqual(self.read()["version"], 0)
        self.assertIsNone(self.st.report_snapshot_detail(2))

    def test_writer_requires_current_scope_owner_actor_fingerprint_and_account(self):
        for values in ({"actor": 101}, {"actor": True}, {"actor": "100"},
                       {"account_key": account_key(999)}, {"revision_fingerprint": "c" * 64}):
            with self.subTest(values=values), self.assertRaises((S.StoreRefused, SC.ScopeError)):
                self.save(**values)
        self.assertEqual(self.read()["version"], 0)

    def test_writer_rejects_stale_org_failed_catalog_and_nonmanaged_stage(self):
        self.now += timedelta(days=4)
        with self.assertRaises(S.StoreRefused):
            self.save()
        self.now -= timedelta(days=4)
        self.st.record_account_catalog_failure(self.now, "CATALOG_FAILED")
        with self.assertRaises(S.StoreRefused):
            self.save()
        self.now += timedelta(seconds=1)
        self.st.record_account_catalog({"generated_at": self.now.isoformat(), "total": 1,
            "complete": True, "items": [TC.company(11, "환불 완료")]}, [], self.now)
        with self.assertRaises(S.StoreRefused):
            self.save()

    def test_dirty_report_blocks_approval_but_allows_internal_draft(self):
        self.st._conn.execute("INSERT INTO naver_auto_report_dirty VALUES(11,?,?,1)",
                              (WEEK.key, self.now.isoformat()))
        self.save()
        with self.assertRaises(S.StoreRefused):
            self.approve()
        self.assertIsNone(self.read()["shared"])

    def test_closed_document_and_plain_text_limits_are_enforced_without_writes(self):
        invalid = [None, [], {"status": "approved"}, {"internal_note": "x" * 1001},
            {"client_feedback": "x" * 1001}, {"shared_comment": "x" * 2001},
            {"next_plan": "x" * 1001}, {"targets": {"source": "x" * 501}},
            {"internal_note": "\ud800"}, {"shared_comment": "<img src=x onerror=alert(1)>"},
            {"next_plan": "a\x00b"}, {"internal_note": 123},
            {"targets": {"cpa": 1, "source": ""}}, {"targets": {"unknown": 1}}]
        for doc in invalid:
            with self.subTest(doc=repr(doc)[:50]), self.assertRaises(S.StoreRefused):
                self.st.record_report_notes(1, self.key, self.fingerprint, 100, self.now,
                    expected_version=0, action="save", document=doc)
        self.assertEqual(self.read()["version"], 0)

    def test_targets_reject_bool_nonfinite_negative_and_strings_but_preserve_zero(self):
        for number in (True, -1, float("nan"), float("inf"), "100", 10**1000, 1e20, 2**53):
            with self.subTest(number=repr(number)[:20]), self.assertRaises(S.StoreRefused):
                self.save(document={**self.doc, "targets": {"cpa": number, "source": "합의 근거"}})
        self.assertEqual(self.save()["document"]["targets"]["cpa"], 0)

    def test_due_date_is_closed_real_date_and_allows_future_without_allowing_future_authorship(self):
        for due in ("2026-2-01", "2026-02-30", "20261015", "2026-10-15T00:00:00", 20261015):
            with self.subTest(due=due), self.assertRaises(S.StoreRefused):
                self.save(document={**self.doc, "plan_due": due})
        self.assertEqual(self.save()["document"]["plan_due"], "2026-10-15")
        with self.assertRaises(S.StoreRefused):
            self.st.record_report_notes(1, self.key, self.fingerprint, 100, self.now+timedelta(days=1),
                expected_version=1, action="save", document=self.doc)

    def test_history_is_bounded_and_cursor_is_version_not_free_sql(self):
        for version in range(25):
            self.save(version)
        first = self.st.report_notes_history(1, self.key, self.fingerprint)
        self.assertEqual(len(first["items"]), 20)
        self.assertEqual(first["next_before_version"], 6)
        second = self.st.report_notes_history(1, self.key, self.fingerprint, before_version=6)
        self.assertEqual([item["version"] for item in second["items"]], [5, 4, 3, 2, 1])
        self.assertIsNone(second["next_before_version"])
        for kw in ({"limit": 21}, {"limit": True}, {"before_version": "1 OR 1=1"}):
            with self.assertRaises(S.StoreRefused):
                self.st.report_notes_history(1, self.key, self.fingerprint, **kw)

    def test_failed_head_write_rolls_back_new_version(self):
        self.save()
        original = self.st._set_meta
        def fail(c, key, value):
            if key.startswith("report-notes-head:"):
                raise S.StoreRefused("합성 저장 실패")
            return original(c, key, value)
        with patch.object(self.st, "_set_meta", side_effect=fail), self.assertRaises(S.StoreRefused):
            self.save(1)
        self.assertEqual(self.read()["version"], 1)
        self.assertEqual(len(self.st.report_notes_history(1, self.key, self.fingerprint)["items"]), 1)

    def test_corrupted_report_scope_cannot_receive_a_document(self):
        changed = deepcopy(self.payload)
        changed["_account_reports"]["101"]["period"]["end"] = "2026-10-11"
        self.st._conn.execute("UPDATE naver_auto_report_snapshot SET payload_json=? WHERE report_id=1",
                              (json.dumps(changed),))
        with self.assertRaises(S.StoreRefused):
            self.save()

    def test_oversized_or_wrong_bound_stored_documents_fail_closed(self):
        self.save()
        key = "report-notes-head:1:" + self.key
        raw = self.st.meta(key)
        for changed in ("x" * 20000, json.dumps({**json.loads(raw), "metadata": {"report_id": 2}})):
            self.st._conn.execute("UPDATE naver_auto_meta SET value=? WHERE key=?", (changed, key))
            with self.assertRaises(S.StoreError):
                self.read()

    def test_input_cannot_spoof_period_author_or_approval_state(self):
        for values in ({"metadata": {"report_id": 2}}, {"author": {"actor": 0}},
                       {"approved_by": 0}, {"period": {"start": "2026-01-01"}}):
            with self.subTest(values=values), self.assertRaises(S.StoreRefused):
                self.save(document={**self.doc, **values})


if __name__ == "__main__":
    unittest.main()
