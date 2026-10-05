"""Deployment errors expose fixed SQLite categories, never database contents."""
import sqlite3
import unittest
from test_naver_preview_code_upgrade import load


class SQLiteLabelsTest(unittest.TestCase):
    def test_fixed_sqlite_category_and_raw_error_remains_private(self):
        code = load('naver_preview_code_upgrade')
        for number, label in ((5, 'SQLITE_BUSY'), (261, 'SQLITE_BUSY'), (6, 'SQLITE_LOCKED'),
                              (8, 'SQLITE_READONLY'), (14, 'SQLITE_CANTOPEN'),
                              (11, 'SQLITE_CORRUPT'), (26, 'SQLITE_NOTADB'),
                              (10, 'SQLITE_IOERR'), (1, 'SQLITE_ERROR'), (15, 'SQLITE_PROTOCOL')):
            error = sqlite3.OperationalError('secret-value must not appear')
            error.sqlite_errorcode = number
            self.assertEqual(code._error_labels(error),
                             {'error_kind': 'OperationalError', 'error_code': label})
            self.assertNotIn('secret-value', str(code.failure_report(error)))

    def test_non_sqlite_error_cannot_spoof_code(self):
        code = load('naver_preview_code_upgrade')
        error = RuntimeError('not an approved diagnostic')
        error.sqlite_errorcode = 5
        self.assertEqual(code._error_labels(error)['error_code'], 'UNRECOGNIZED')

    def test_python310_exact_known_messages_only_without_numeric_code(self):
        code = load('naver_preview_code_upgrade')
        for message, label in (
                ('database is locked', 'SQLITE_BUSY'),
                ('database table is locked', 'SQLITE_LOCKED'),
                ('attempt to write a readonly database', 'SQLITE_READONLY'),
                ('unable to open database file', 'SQLITE_CANTOPEN'),
                ('database disk image is malformed', 'SQLITE_CORRUPT'),
                ('file is not a database', 'SQLITE_NOTADB'),
                ('disk I/O error', 'SQLITE_IOERR'),
                ('locking protocol', 'SQLITE_PROTOCOL')):
            error = sqlite3.OperationalError(message)
            self.assertFalse(hasattr(error, 'sqlite_errorcode'))
            self.assertEqual(code.failure_report(error)['error_code'], label)
            self.assertEqual(code.failure_report(sqlite3.OperationalError(message+' private-value'))['error_code'], 'UNRECOGNIZED')
            self.assertEqual(code.failure_report(RuntimeError(message))['error_code'], 'UNRECOGNIZED')
            error.sqlite_errorcode = 1
            self.assertEqual(code.failure_report(error)['error_code'], 'SQLITE_ERROR')
        self.assertNotIn('private-value', str(code.failure_report(sqlite3.OperationalError('private-value'))))
