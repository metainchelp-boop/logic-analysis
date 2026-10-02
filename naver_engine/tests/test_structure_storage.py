"""구조 저장소 경계. SQL/잠금을 실행하지 않는 좁은 메모리 경계 시험이다.

실제 SQLite 통합의 대체 증거가 아니다. 원천 오류의 상태 전파와 선택 쿼리 계약만 검사한다.
"""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import unittest

from naver_engine import naver_read as N, store as S, structure_reads as R
from naver_engine.tests.fake_naver import FakeClock, FakeNaver
from naver_engine.tests.test_morning import A, creds
from naver_engine.tests import test_account_catalog as TC, test_alerts as TA, test_morning as TM
from naver_engine import erp_read as E
from app.naver_auto import matching as M


NOW = datetime(2026, 10, 5, 9, tzinfo=S.KST)


class _Result:
    def __init__(self, rows=(), names=()):
        self.description = [(name,) for name in names]
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class _StructureBoundary(S.ManagedStorage):
    def __init__(self):
        self._conn = self
        self.source = '{"private":"보관전용자료"}'
        self.digest = "wrong"
        self.saved, self.selects = [], []
        self.rows, self.states = [], {}
        self.job = {"job_key": "structure:daily-test", "customer_id": A,
                    "cycle_day": "2026-10-05", "snapshot_at": NOW}

    def execute(self, query, values=()):
        if query.startswith("SELECT progress_json"):
            return _Result([(self.source, self.digest)])
        if query.startswith("SELECT attempts"):
            return _Result([(0,)])
        if query.startswith("UPDATE naver_auto_structure_job SET status"):
            self.saved.append(values)
            return _Result()
        if "FROM naver_auto_structure_job" in query:
            self.selects.append((query, values))
            names = ("customer_id", "cycle_day", "stage_revision", "status", "checked_at", "error_code", "reasons_json")
            rows = [row for row in self.rows if not values or row["customer_id"] in values]
            return _Result([tuple(row[name] for name in names) for row in rows], names)
        raise AssertionError("시험 경계를 벗어난 SQL입니다")

    @contextmanager
    def _tx(self):
        yield self

    def _need_writer(self):
        pass

    def _not_future(self, now, label):
        if now > NOW:
            raise S.StoreRefused("시험 시각 초과")

    def structure_account_valid(self, job, now):
        return job == self.job

    def structure_work(self, now, limit):
        return [self.job]

    def begin_structure_check(self, job, now):
        if not self.structure_account_valid(job, now):
            raise S.StoreRefused("시험 원천 변경")

    def management_states(self):
        return self.states


class StructureStorageBoundaryTests(unittest.TestCase):
    def test_corrupt_hash_is_a_checkpoint_error_and_runner_records_limited_without_http_or_source_leak(self):
        store = _StructureBoundary()
        with self.assertRaises(R.CheckpointInvalid):
            store.structure_progress(store.job)
        clock, http = FakeClock(NOW), FakeNaver()
        reader = N.NaverReader(creds(), transport=http, clock=clock)
        out = R.run_structure(reader, store, clock.now)
        self.assertEqual(out.counts, {"limited": 1})
        self.assertEqual(http.calls, [])
        self.assertEqual(len(store.saved), 1)
        self.assertEqual((store.saved[0][0], store.saved[0][4], store.saved[0][5]),
                         ("limited", "CHECKPOINT_INVALID", "[]"))
        self.assertNotIn("보관전용자료", str(store.saved)+str(out))

    def test_valid_hash_with_malformed_json_or_schema_is_still_limited_not_completed(self):
        for raw in ("{", "[]", '{"private":"보관전용자료"}'):
            with self.subTest(raw=raw):
                store = _StructureBoundary()
                store.source, store.digest = raw, hashlib.sha256(raw.encode()).hexdigest()
                with self.assertRaises(R.CheckpointInvalid):
                    store.structure_progress(store.job)
                self.assertEqual(store.record_structure_check(store.job, NOW,
                    {"status": "limited", "error_code": "CHECKPOINT_INVALID"}), "limited")
                with self.assertRaises(S.StoreRefused):
                    store.record_structure_check(store.job, NOW, {"status": "ok"})

    def test_latest_per_requested_account_is_bounded_and_preserves_stage_and_staleness_guards(self):
        store = _StructureBoundary()
        customers = list(range(A, A+401))
        store.states = {cid: {"stage_revision": "stage-now", "stage_key": "진행중", "possibility_id": 11,
                              "included_revision": None, "excluded_revision": None} for cid in customers}
        base = {"customer_id": A, "cycle_day": "2026-10-05", "stage_revision": "stage-now", "status": "ok",
                "checked_at": NOW.isoformat(), "error_code": None, "reasons_json": json.dumps([{"source": "observed"}])}
        store.rows = [base, {**base, "customer_id": A+1, "stage_revision": "stage-before"},
                      {**base, "customer_id": A+2, "cycle_day": "2026-10-04"},
                      {**base, "customer_id": A+400}]
        out = store.structure_checks(customers, NOW)
        self.assertEqual(out[A]["status"], "ok")
        self.assertEqual(out[A+1], {"status": "pending", "checked_at": None, "error_code": None,
                                  "reasons": [], "stale": True})
        self.assertEqual(out[A+2]["status"], "pending")
        self.assertTrue(out[A+2]["stale"])
        self.assertEqual(len(store.selects), 2)
        self.assertEqual([len(args) for _, args in store.selects], [400, 1])
        for query, _ in store.selects:
            self.assertIn("WITH wanted(customer_id) AS (VALUES", query)
            self.assertIn("p.customer_id=w.customer_id", query)
            self.assertIn("ORDER BY p.checked_at DESC, p.rowid DESC LIMIT 1", query)
        store.selects.clear()
        self.assertEqual(store.structure_checks([], NOW), {})
        self.assertEqual(store.selects, [])


class StructureStorageIntegrationTests(TM.Base):
    """Linux CI의 실제 단일 writer/SQLite용. Mac 잠금 우회로 실행하지 않는다."""
    def test_latest_requested_account_query_breaks_timestamp_ties_and_hides_changed_stage(self):
        now = self.fc.now()
        self.st.record_org(TA.org_body(now), now)
        self.st.record_accounts(TM.kids(A), now)
        company = TC.company(11, "진행중", company_name=TM.NAMES.get(A, f"계정{A}"))
        self.st.record_account_catalog({"generated_at": now.isoformat(), "total": 1, "complete": True,
                                        "items": [company]}, [E.NaverIdRow(11, M.VENDOR_NAVER, str(A))], now)
        http = FakeNaver()
        http.route(r"/ncc/campaigns", lambda call: (200, []))
        http.route(r"/ncc/channels", lambda call: (200, []))
        reader = N.NaverReader(creds(), transport=http, clock=self.fc)
        self.assertEqual(R.run_structure(reader, self.st, self.fc.now).counts, {"ok": 1})
        now = self.fc.now()
        original = self.st.structure_checks([A], now)[A]
        self.st.performance_manual_request(A, 100, now)
        job = self.st.structure_work(now, 1)[0]
        self.assertEqual(job["kind"], "manual")
        self.st.begin_structure_check(job, now)
        self.st.record_structure_check(job, now, {"status": "retry", "error_code": "READ_RETRY"})
        latest = self.st.structure_checks(range(A, A+401), now)
        self.assertEqual(set(latest), {A})
        self.assertEqual(latest[A]["checked_at"], original["checked_at"])
        self.assertEqual(latest[A]["status"], "retry")
        company["stage"] = "사후관리"
        self.st.record_account_catalog({"generated_at": now.isoformat(), "total": 1, "complete": True,
                                        "items": [company]}, [E.NaverIdRow(11, M.VENDOR_NAVER, str(A))], now)
        self.st.synchronize_management(now)
        changed = self.st.structure_checks([A], now)[A]
        self.assertEqual((changed["status"], changed["checked_at"], changed["reasons"]), ("pending", None, []))


if __name__ == "__main__":
    unittest.main()
