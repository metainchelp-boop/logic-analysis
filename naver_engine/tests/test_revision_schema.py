"""정정용 추가형 이관 계약. 메모리 SQLite이며 제품 잠금은 바꾸지 않는다."""
import sqlite3
import unittest
from naver_engine import store as S


class RevisionSchemaTest(unittest.TestCase):
    def test_upgrade_preserves_old_rows_and_is_repeatable(self):
        conn = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE naver_auto_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO naver_auto_meta VALUES ('schema_version','10')")
        for sql in S._SCHEMA:
            conn.execute(sql)
        conn.execute("INSERT INTO naver_auto_manual_read(customer_id,requested_at,actor) VALUES(100,'2026-10-01T00:00:00+09:00',0)")
        st = object.__new__(S.Store)
        st._conn = conn
        st._migrate()
        st._migrate()
        self.assertEqual(conn.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()[0], '11')
        self.assertEqual(conn.execute("SELECT customer_id,period_start,period_end,possibility_id FROM naver_auto_manual_read").fetchall(), [(100,None,None,None)])
        for table, expected in {
            'naver_auto_performance_job': {'generation','source_wait_attempts'},
            'naver_auto_daily_performance': {'source_generation','source_revision'},
            'naver_auto_report_validation': {'expected_customers_json','payload_json'},
            'naver_auto_report_dirty': {'pending','updated_at'},
        }.items():
            self.assertTrue(expected <= {r[1] for r in conn.execute('PRAGMA table_info('+table+')')})

    def test_newer_schema_refusal_rolls_back(self):
        conn = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE naver_auto_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO naver_auto_meta VALUES ('schema_version','999')")
        st = object.__new__(S.Store)
        st._conn = conn
        with self.assertRaises(S.StoreError):
            st._migrate()
        self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [('naver_auto_meta',)])
