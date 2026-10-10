"""Existing monitoring schema11 must survive the report JSON upgrade; no network."""
import hashlib
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch

import test_naver_preview_code_upgrade as legacy


PROGRESS_SQL = (
    """CREATE TABLE IF NOT EXISTS naver_auto_morning_progress (
        customer_id INTEGER PRIMARY KEY, possibility_id INTEGER NOT NULL, day TEXT NOT NULL,
        binding TEXT NOT NULL, campaign_fingerprint TEXT NOT NULL, generation INTEGER NOT NULL,
        status TEXT NOT NULL, next_try_at TEXT NOT NULL, payload_bytes INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_morning_chunk (
        customer_id INTEGER NOT NULL, kind TEXT NOT NULL, slot INTEGER NOT NULL,
        generation INTEGER NOT NULL, body TEXT, checksum TEXT, size INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (customer_id, kind, slot))""",
)


def monitoring_source(before):
    # Preserve the historical fixture and initializer; only this release's reviewed additions.
    marker = b'_REVISION_COLUMNS='
    start = before.index(marker) + len(marker)
    end = before.index(b'\n', start)
    import ast
    columns = ast.literal_eval(before[start:end].decode())
    columns = {'naver_auto_link_memory': (('auto_identity_fingerprint', 'TEXT'),), **columns}
    return before[:start]+repr(columns).encode()+before[end:]+b'\n_SCHEMA += '+repr(PROGRESS_SQL).encode()+b'\n'


class MonitoringMigrationContractTest(unittest.TestCase):
    def test_report_upgrade_preserves_the_existing_nullable_column_and_progress_tables(self):
        code = legacy.load('naver_preview_code_upgrade')
        before = legacy.StoreScopeTest.SOURCE
        after = before + b'\n# report JSON only\n'
        with patch.object(code, 'STORE_SHA256', {
                'old': hashlib.sha256(before).hexdigest(), 'target': hashlib.sha256(after).hexdigest()}):
            code.migration_contract(before, after)

    def test_repinning_cannot_authorize_any_other_schema_change(self):
        code = legacy.load('naver_preview_code_upgrade')
        before = legacy.StoreScopeTest.SOURCE
        approved = before + b'\n# report JSON only\n'
        for after in (legacy.StoreScopeTest.HISTORICAL_SOURCE, approved.replace(b"'TEXT'),)", b"'TEXT NOT NULL'),)"),
                      approved.replace(b'body TEXT, checksum', b'body BLOB, checksum'),
                      approved.replace(b'payload_bytes INTEGER NOT NULL DEFAULT 0', b'payload_bytes INTEGER DEFAULT 0'),
                      approved.replace(b'if column not in columns:', b'if column in columns:'),
                      approved.replace(b'source_wait_attempts', b'unreviewed_attempts'),
                      approved+b'\n_SCHEMA += ("CREATE TABLE unexpected(id INTEGER)",)\n'):
            self.assertNotEqual(approved, after)
            with self.subTest(after=after), patch.object(code, 'STORE_SHA256', {
                    'old': hashlib.sha256(before).hexdigest(), 'target': hashlib.sha256(after).hexdigest()}):
                with self.assertRaisesRegex(ValueError, 'CODE_SCHEMA_CHANGED'):
                    code.migration_contract(before, after)

    def test_same_version_without_existing_progress_tables_is_not_a_running_target(self):
        code = legacy.load('naver_preview_code_upgrade')
        fixture = legacy.DatabaseRollbackTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        code.DATA = fixture.data
        with closing(sqlite3.connect(fixture.db)) as connection, connection:
            connection.execute('DROP TABLE naver_auto_morning_chunk')
        with self.assertRaisesRegex(ValueError, 'DB_TARGET_SCHEMA'):
            code.verify_database_schema(code.TARGET_COMMIT, fixture.release, fixture.upgrade)

    def test_repeated_actual_initializer_preserves_all_legacy_columns_and_history(self):
        fixture = legacy.DatabaseRollbackTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with closing(sqlite3.connect(fixture.db)) as connection, connection:
            connection.executescript("""
                INSERT INTO naver_auto_link_memory
                    (possibility_id,customer_id,link,first_matched_at,last_matched_at)
                    VALUES (11,12345,'auto','first','last');
                INSERT INTO naver_auto_link_decision
                    (possibility_id,customer_id,decision,decided_by,decided_at)
                    VALUES (11,12345,'rejected',7,'prior-decision');
                INSERT INTO naver_auto_check_run (run_date,started_at,status)
                    VALUES ('2026-10-03','prior-start','running');
                INSERT INTO naver_auto_account_day
                    (customer_id,day,possibility_id,link,run_id,status,rules_run,rules_not_run,yday_spend,checked_at)
                    VALUES (12345,'2026-10-03',11,'auto',1,'partial','[]','[]',NULL,'prior-account');
                INSERT INTO naver_auto_daily_performance
                    (customer_id,day,possibility_id,matching_fingerprint,basic_complete,
                     conversion_complete,conversion_attempts,spend,checked_at,campaign_fingerprint)
                    VALUES (12345,'2026-10-02',11,'old-link',1,0,2,37.5,'prior-daily','old-campaign');
                INSERT INTO naver_auto_daily_revision
                    (customer_id,day,recorded_at,payload_json)
                    VALUES (12345,'2026-10-02','prior-revision','{"spend":37.5}');
                INSERT INTO naver_auto_report_snapshot
                    (possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
                    VALUES (11,'prior-period','old-revision','prior-report','partial','pending','{"spend":37.5}');
                INSERT INTO naver_auto_report_review (report_id,actor,at,decision,note)
                    VALUES (1,7,'prior-review','approved','synthetic-only');
            """)
            tables = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            columns = {table: [row[1] for row in connection.execute('PRAGMA table_info('+table+')')]
                       for table in tables}
            def ledger():
                return {table: connection.execute('SELECT '+','.join(columns[table])+' FROM '+table+
                                                  ' ORDER BY rowid').fetchall() for table in tables}
            before = ledger()
            self.assertGreaterEqual(sum(bool(rows) for rows in before.values()), 10)
            for _ in range(2):
                fixture.initialize_schema(connection, 11, monitoring=True)
                self.assertEqual(ledger(), before)
                self.assertEqual(connection.execute('SELECT auto_identity_fingerprint FROM naver_auto_link_memory').fetchall(), [(None,)])
            fixture.code.verify_database_schema(fixture.code.TARGET_COMMIT, fixture.release, fixture.upgrade)
            # The actual old initializer and its explicit-column write still tolerate the additions.
            fixture.initialize_schema(connection, 11)
            self.assertEqual(ledger(), before)
            connection.execute("""INSERT INTO naver_auto_link_memory
                (possibility_id,customer_id,link,first_matched_at,last_matched_at)
                VALUES (12,23456,'auto','old-writer-first','old-writer-last')""")
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchall(), [('ok',)])

    def test_incomplete_existing_schema11_cannot_be_saved_as_the_old_rollback_database(self):
        fixture = legacy.DatabaseRollbackTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.mutate_schema11()
        with closing(sqlite3.connect(fixture.db)) as connection, connection:
            connection.execute('DROP TABLE naver_auto_morning_progress')
        before = fixture.db.read_bytes()
        with self.assertRaisesRegex(ValueError, 'DB_OLD_SCHEMA'):
            fixture.code.db_snapshot(fixture.identity, fixture.release, fixture.upgrade)
        self.assertEqual(fixture.db.read_bytes(), before)

    def test_same_version_with_partial_or_wrong_actual_schema_is_refused(self):
        for statements in (
                ['DROP TABLE naver_auto_morning_progress'],
                ['DROP TABLE naver_auto_morning_chunk', PROGRESS_SQL[1].replace('checksum TEXT', 'checksum INTEGER')],
                ['ALTER TABLE naver_auto_link_memory DROP COLUMN auto_identity_fingerprint',
                 "ALTER TABLE naver_auto_link_memory ADD COLUMN auto_identity_fingerprint TEXT NOT NULL DEFAULT ''"]):
            fixture = legacy.DatabaseRollbackTest()
            fixture.setUp()
            try:
                fixture.mutate_schema11()
                with closing(sqlite3.connect(fixture.db)) as connection, connection:
                    for statement in statements:
                        connection.execute(statement)
                with self.subTest(statements=statements), self.assertRaisesRegex(ValueError, 'DB_TARGET_SCHEMA'):
                    fixture.code.verify_database_schema(fixture.code.TARGET_COMMIT, fixture.release, fixture.upgrade)
            finally:
                fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
