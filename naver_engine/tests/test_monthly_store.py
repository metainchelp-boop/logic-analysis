"""월간 SQLite 계약. macOS inode flock/WAL 제약을 우회하지 않고 Linux에서 검증한다."""
from datetime import timedelta
import pathlib
import socket
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from naver_engine import store as S, inventory_reads as I, monthly_reads as M, naver_read as N, backup as B
from naver_engine.tests.fake_naver import FakeClock, FakeNaver, cycle_str
from naver_engine.tests.test_morning import A, kids, creds
from naver_engine.tests.test_monthly_reads import NOW


@unittest.skipUnless(sys.platform == "linux", "실제 inode flock+WAL 계약은 Linux CI에서 검증")
class MonthlyStoreTest(unittest.TestCase):
    def setUp(self):
        network = patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
        network.start()
        self.addCleanup(network.stop)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = pathlib.Path(self.dir.name)
        self.path = str(self.root / "engine.db")
        self.clock, self.http = FakeClock(NOW), FakeNaver()
        self.store = S.open_writer(self.path, clock=self.clock.now)
        self.addCleanup(lambda: self.store.close() if self.store else None)
        self.campaigns = [{"customerId": A, "nccCampaignId": f"cmp-{A}-1", "status": "ELIGIBLE",
                           "userLock": False, "delFlag": False}]
        self.http.route(r"/ncc/campaigns", lambda call: (200, self.campaigns))
        self.http.route(r"/billing/bizmoney", lambda call: (200, {"customerId": A, "bizmoney": 100,
                                                              "budgetLock": False, "refundLock": False}))
        self.basic_missing = False
        self.http.route(r"/stats", lambda call: (200, {"cycleBaseTm": cycle_str(self.clock.now()), "data": [
            {"id": c["nccCampaignId"], "impCnt": None if self.basic_missing else 100, "clkCnt": 10,
             "salesAmt": 1000, "convAmt": 2000} for c in self.campaigns]}))
        self.store.record_accounts(kids(A), self.clock.now())
        I.run_inventory(self.reader(), self.store, self.clock.now)
        self.clock.advance(1)

    def reader(self):
        return N.NaverReader(creds(), transport=self.http, clock=self.clock)

    def collect(self, **kwargs):
        return M.run_monthly(self.reader(), self.store, self.clock.now, **kwargs)

    def rows(self):
        return self.store.monthly_checks_on(*M.window(self.clock.now().date()))

    def reopen(self):
        self.store.close()
        self.store = None
        self.store = S.open_writer(self.path, clock=self.clock.now)

    def test_complete_snapshot_roundtrip_and_refresh_does_not_recollect(self):
        self.assertEqual(self.collect().counts, {"ok": 1})
        self.assertEqual((self.rows()[A]["spend"], self.rows()[A]["conversion_value"]), (1000, 2000))
        prior = self.rows()[A]["checked_at"]
        self.reopen()
        self.clock.advance(60)
        self.store.record_accounts(kids(A), self.clock.now())
        before = len(self.http.calls)
        self.assertEqual(self.collect().counts, {})
        self.assertEqual(len(self.http.calls), before)
        self.assertEqual(self.rows()[A]["checked_at"], prior)

    def test_period_isolation_and_same_round_daily_exclusion(self):
        cutoff = NOW
        self.assertEqual(self.store.monthly_work(self.clock.now(), exclude_checked_after=cutoff), [])
        self.collect()
        old_period, old_rows = M.window(self.clock.now().date()), self.rows()
        self.clock.advance(24*3600)
        self.store.record_accounts(kids(A), self.clock.now())
        self.assertEqual(self.rows(), {})
        I.run_inventory(self.reader(), self.store, self.clock.now)
        self.clock.advance(1)
        self.assertEqual(self.collect().counts, {"ok": 1})
        self.assertEqual(self.store.monthly_checks_on(*old_period), old_rows)

    def test_four_failures_stay_limited_across_catalog_refresh_and_restart(self):
        self.basic_missing = True
        for attempt in range(4):
            self.store.record_accounts(kids(A), self.clock.now())
            result = self.collect()
            self.assertEqual(result.counts, {"limited" if attempt == 3 else "retry": 1})
            self.clock.advance(1800)
            self.reopen()
        self.store.record_accounts(kids(A), self.clock.now())
        before = len(self.http.calls)
        self.assertEqual(self.collect().counts, {})
        self.assertEqual(len(self.http.calls), before)
        row = self.rows()[A]
        self.assertEqual(row["error_code"], "RETRY_EXHAUSTED")
        self.assertTrue(all(row[key] is None for key in M.OUTPUTS))

    def test_partial_progress_survives_refresh_and_reopen_without_double_sum(self):
        self.assertEqual(self.collect(max_calls=2).counts, {"partial": 1})
        start, end = M.window(self.clock.now().date())
        before = self.store.monthly_progress(A, start, end)
        self.reopen()
        self.clock.advance(60)
        self.store.record_accounts(kids(A), self.clock.now())
        self.assertEqual(self.collect().counts, {"ok": 1})
        self.assertEqual(self.store.monthly_progress(A, start, end), before)
        self.assertEqual(self.rows()[A]["spend"], 1000)

    def test_tampered_progress_hash_fails_closed_before_http(self):
        self.collect(max_calls=2)
        self.store._conn.execute("UPDATE naver_auto_monthly_check SET progress_json = '{}' WHERE customer_id = ?", (A,))
        before = len(self.http.calls)
        self.assertEqual(self.collect().counts, {"limited": 1})
        self.assertEqual(len(self.http.calls), before)
        self.assertIsNone(self.rows()[A]["spend"])

    def test_changed_period_or_invented_public_sum_is_refused(self):
        self.collect(max_calls=2)
        start, end = M.window(self.clock.now().date())
        source = self.store.monthly_progress(A, start, end)
        self.store.begin_monthly_check(A, self.store.inventory_snapshot(self.clock.now()), self.clock.now())
        source["period_end"] = (end-timedelta(days=1)).isoformat()
        with self.assertRaises(M.CheckpointInvalid):
            self.store.record_monthly_progress(A, self.store.inventory_snapshot(self.clock.now()), self.clock.now(), source)
        with self.assertRaises(S.StoreRefused):
            self.store.record_monthly_check(A, self.store.inventory_snapshot(self.clock.now()), self.clock.now(),
                                            {"status": "ok", "imp": 100, "clk": 10, "spend": 999,
                                             "conversion_value": 2000})

    def test_schema8_upgrade_preserves_daily_data(self):
        prior = self.store.inventory_checks_on(self.clock.now().date())
        self.store.close()
        self.store = None
        with sqlite3.connect(self.path) as raw:
            raw.execute("DROP TABLE naver_auto_monthly_check")
            raw.execute("UPDATE naver_auto_meta SET value = '8' WHERE key = 'schema_version'")
        self.store = S.open_writer(self.path, clock=self.clock.now)
        self.assertEqual(self.store.meta("schema_version"), "9")
        self.assertEqual(self.store.inventory_checks_on(self.clock.now().date()), prior)
        self.assertEqual(self.rows(), {})
        self.assertEqual(self.collect().counts, {"ok": 1})

    def test_schema9_backup_and_restore_include_monthly_rows(self):
        self.collect()
        result = B.create_local_backup(self.store.snapshot_to, self.root / "backups", now=self.clock.now())
        self.assertEqual(result.code, "LOCAL_READY")
        restored = self.root / "restored.sqlite"
        counts = B.restore_archive(result.local_path, restored, S.inspect_snapshot)
        self.assertEqual(counts["naver_auto_monthly_check"], 1)
        with S.open_reader(str(restored)) as reader:
            self.assertEqual(reader.meta("schema_version"), "9")
            self.assertEqual(reader.monthly_checks_on(*M.window(self.clock.now().date())), self.rows())


if __name__ == "__main__":
    unittest.main()
