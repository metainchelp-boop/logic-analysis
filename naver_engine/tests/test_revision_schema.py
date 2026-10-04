"""정정용 추가형 이관 계약. 메모리 SQLite이며 제품 잠금은 바꾸지 않는다."""
import ast
import copy
import sqlite3
import unittest
from naver_engine import store as S

EXPECTED_COLUMNS = {
    'naver_auto_link_memory': (('auto_identity_fingerprint', 'TEXT'),),
    'naver_auto_performance_job': (('generation', "TEXT NOT NULL DEFAULT ''"), ('source_wait_attempts', 'INTEGER NOT NULL DEFAULT 0')),
    'naver_auto_daily_performance': (('source_generation', "TEXT NOT NULL DEFAULT ''"), ('source_revision', 'INTEGER NOT NULL DEFAULT 1')),
    'naver_auto_manual_read': (('period_start', 'TEXT'), ('period_end', 'TEXT'), ('possibility_id', 'INTEGER'), ('request_kind', "TEXT NOT NULL DEFAULT 'manual'")),
}
APPROVED_LOOP = '''for table, additions in _REVISION_COLUMNS.items():
    columns = {r[1] for r in c.execute("PRAGMA table_info(" + table + ")")}
    for column, declaration in additions:
        if column not in columns:
            c.execute("ALTER TABLE " + table + " ADD COLUMN " + column + " " + declaration)
'''


def without_approved_additions(source_tree):
    tree = copy.deepcopy(source_tree)
    assignments = [n for n in tree.body if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == '_REVISION_COLUMNS' for t in n.targets)]
    assert len(assignments) == 1 and ast.literal_eval(assignments[0].value) == EXPECTED_COLUMNS
    migrations = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_migrate']
    assert len(migrations) == 1
    expected, removed = ast.dump(ast.parse(APPROVED_LOOP).body[0]), 0
    for scope in ast.walk(migrations[0]):
        if isinstance(scope, ast.With):
            retained = []
            for statement in scope.body:
                if ast.dump(statement) == expected:
                    removed += 1
                else:
                    retained.append(statement)
            scope.body = retained
    assert removed == 1
    return tree


class RevisionSchemaTest(unittest.TestCase):
    def test_only_exact_additive_migration_is_exempt_from_general_sql_scan(self):
        from pathlib import Path
        from naver_engine.tests.test_store import sql_strings
        text = Path(S.__file__).read_text()
        self.assertFalse(any(sql.startswith('ALTER') for sql in sql_strings(without_approved_additions(ast.parse(text)))))
        for changed in (text.replace(' ADD COLUMN ', ' DROP COLUMN '),
                        text.replace('(\"generation\",', '(\"not_approved\",'),
                        text.replace('(\"auto_identity_fingerprint\", \"TEXT\")',
                                     '(\"not_approved_fingerprint\", \"TEXT\")'),
                        text.replace('(\"auto_identity_fingerprint\", \"TEXT\")',
                                     '(\"auto_identity_fingerprint\", \"INTEGER\")'),
                        text.replace('(\"auto_identity_fingerprint\", \"TEXT\")',
                                     '(\"auto_identity_fingerprint\", \"TEXT NOT NULL\")'),
                        text.replace('for table, additions in _REVISION_COLUMNS.items():', 'for table, additions in unknown.items():')):
            self.assertNotEqual(changed, text)
            with self.assertRaises(AssertionError):
                without_approved_additions(ast.parse(changed))
        extra = ast.parse(text + '\ndef outside():\n    return "ALTER TABLE x DROP COLUMN y"\n')
        self.assertTrue(any(sql.startswith('ALTER') for sql in sql_strings(without_approved_additions(extra))))

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
        self.assertEqual(conn.execute("SELECT request_kind FROM naver_auto_manual_read").fetchall(), [('manual',)])
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
