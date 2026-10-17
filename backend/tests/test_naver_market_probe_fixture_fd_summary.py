"""New fixed-frame FD projection and independently exec'd synthetic writer only."""
import ast
import inspect
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import test_naver_market_source_limit_probe_namespace_provenance as F
from naver_market_probe_namespace_fixture import independent_writer, WRITER


class FixtureFdSummaryTests(unittest.TestCase):
    def setUp(self):
        self.provenance = F.Provenance()
        self.addCleanup(self.provenance.close)
        self.family = {'': (1, 101, 0o100644, 0, 0), '-wal': (1, 102, 0o100644, 0, 0), '-shm': (1, 103, 0o100644, 0, 0)}

    def project(self, before, after):
        with patch.object(F.D, '_fd_snapshot', return_value=after), self.assertRaises(F.D.ProbeStop):
            self.provenance.wrap('fd_bind', F.D._bind_sqlite_fds)(before, self.family)
        result = self.provenance.result()
        self.assertEqual(result['failure_stage'], 'fd_bind')
        self.assertNotIn('101', json.dumps(result))
        self.assertNotIn('102', json.dumps(result))
        self.assertNotIn('103', json.dumps(result))
        return result['fd_summary']

    def test_missing_shm_is_closed_family_count_only(self):
        result = self.project({}, {3: self.family[''], 4: self.family['-wal']})
        self.assertEqual(result, dict(new_regular_count=2, main_matches=1, wal_matches=1,
            shm_matches=0, extra_regular_count=0, before_family_match=False))

    def test_extra_regular_descriptor_count_is_distinct(self):
        result = self.project({}, {3: self.family[''], 4: self.family['-wal'], 5: self.family['-shm'], 6: (1, 999, 0o100644, 0, 0)})
        self.assertEqual(result, dict(new_regular_count=4, main_matches=1, wal_matches=1,
            shm_matches=1, extra_regular_count=1, before_family_match=False))

    def test_preexisting_family_match_is_boolean_only(self):
        result = self.project({3: self.family['']}, {3: self.family[''], 4: self.family['-wal'], 5: self.family['-shm']})
        self.assertEqual(result, dict(new_regular_count=2, main_matches=0, wal_matches=1,
            shm_matches=1, extra_regular_count=0, before_family_match=True))

    def test_fd_summary_out_of_range_is_rejected(self):
        values = self.provenance._get()
        values[12:18] = [65, 0, 0, 0, 0, 0]
        self.provenance.shared[:F.WORDS.size] = F.WORDS.pack(*values)
        with self.assertRaisesRegex(ValueError, '^FIXTURE_PROVENANCE_SHAPE$'):
            self.provenance.result()

    def test_independent_writer_uses_same_schema_and_never_opens_parent_db(self):
        def schema(tree):
            return next(n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr == 'executescript')
        self.assertEqual(schema(ast.parse(WRITER)), schema(ast.parse(inspect.getsource(F.tables))))
        with tempfile.TemporaryDirectory(prefix='naver-probe-fixture-') as temp:
            directory = Path(temp).resolve()
            with patch.object(sqlite3, 'connect', side_effect=AssertionError('PARENT_DATABASE_OPEN')):
                with independent_writer(directory):
                    self.assertTrue(all((directory / ('logic_data.db' + suffix)).is_file() for suffix in ('', '-wal', '-shm')))


if __name__ == '__main__':
    unittest.main()
