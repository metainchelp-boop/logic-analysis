"""Real synthetic SQLite rejection paths; no production data or network."""
from contextlib import redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

import test_naver_market_export as existing

M = existing.M


class MarketLimitReasonTests(unittest.TestCase):
    def setUp(self):
        self.fixture = existing.MarketExportTests()
        self.addCleanup(self.fixture.doCleanups)

    def failed_cli(self, limits, expected, *, main=existing.KEYWORD, clock=(0, 0)):
        database, output = self.fixture.fixture(main=main)
        before = (database.read_bytes(), database.stat().st_mtime_ns)
        original = M.export_database
        calls = []

        def invoke(source, destination):
            calls.append(True)
            return original(source, destination, now=existing.NOW, limits=limits)

        stream = io.StringIO()
        with patch.object(M, 'export_database', side_effect=invoke), \
                patch.object(M.P.time, 'monotonic', side_effect=clock) as monotonic, \
                redirect_stdout(stream):
            code = M.main(['--database', str(database), '--output', str(output)])
        self.assertEqual(code, 1)
        self.assertEqual(calls, [True])
        self.assertEqual(json.loads(stream.getvalue()), {
            'status': 'failed', 'code': 'SOURCE_LIMIT', 'limit_issue': expected})
        self.assertEqual(before, (database.read_bytes(), database.stat().st_mtime_ns))
        self.assertFalse(output.exists())
        self.assertNotIn(str(database), stream.getvalue())
        self.assertNotIn(main, stream.getvalue())
        return monotonic.call_count

    def test_bytes_and_rows_keep_original_short_circuit_clock_count(self):
        for limits, issue in [(M.Limits(max_input_bytes=0), 'input_bytes'),
                              (M.Limits(max_rows=0), 'rows')]:
            with self.subTest(issue=issue):
                self.assertEqual(self.failed_cli(limits, issue, clock=(0,)), 1)

    def test_time_has_no_second_measurement_or_retry(self):
        self.assertEqual(self.failed_cli(M.Limits(), 'time', clock=(0, 31)), 2)

    def test_cell_and_client_rejections_are_distinct(self):
        self.assertEqual(self.failed_cli(M.Limits(), 'cell', main='PRIVATE_' * 1100), 2)
        self.assertEqual(self.failed_cli(M.Limits(max_clients=0), 'clients'), 2)

    def test_budget_priority_matches_original_or_order(self):
        with patch.object(M.P.time, 'monotonic', return_value=0) as clock:
            budget = M.P._Budget(M.Limits(max_rows=0, max_input_bytes=0))
            try:
                budget.tick(size=1, rows=1)
            except M.ExportInvalid as error:
                before = clock.call_count
                self.assertEqual(M._limit_issue(error), 'input_bytes')
                self.assertEqual(clock.call_count, before)
            else:
                self.fail('expected the unchanged SOURCE_LIMIT guard')

    def test_unproven_exception_or_subclass_stays_unknown(self):
        class ForeignLimit(M.ExportInvalid):
            pass
        for cls in (M.ExportInvalid, ForeignLimit):
            try:
                raise cls('SOURCE_LIMIT')
            except M.ExportInvalid as error:
                self.assertEqual(M._failure_result(error), {
                    'status': 'failed', 'code': 'SOURCE_LIMIT', 'limit_issue': 'unknown'})
        self.assertEqual(M._limit_issue(M.ExportInvalid('SOURCE_LIMIT')), 'unknown')

    def test_unrecognized_leaf_cannot_claim_a_known_phase(self):
        def unrelated():
            self_value = {'rows': 100001, 'PRIVATE_': 'PRIVATE_DATA'}
            raise M.ExportInvalid('SOURCE_LIMIT')
        try:
            unrelated()
        except M.ExportInvalid as error:
            result = M._failure_result(error)
            self.assertEqual(result['limit_issue'], 'unknown')
            self.assertNotIn('PRIVATE_', json.dumps(result))

    def test_traceback_work_is_bounded(self):
        def recurse(depth):
            if depth:
                return recurse(depth - 1)
            budget = M.P._Budget(M.Limits(max_rows=0))
            budget.tick(rows=1)
        try:
            recurse(40)
        except M.ExportInvalid as error:
            self.assertEqual(M._limit_issue(error), 'unknown')

    def test_other_failure_contracts_are_identical(self):
        for error in (M.ExportInvalid('SOURCE_READ', source_issue='locked'),
                      M.ExportInvalid('SOURCE_PATH'), ValueError('PRIVATE_EXCEPTION')):
            self.assertEqual(M._failure_result(error), M.P._failure_result(error))
            self.assertNotIn('PRIVATE_', json.dumps(M._failure_result(error)))

    def test_success_cli_contract_and_single_export_unchanged(self):
        expected = {'status': 'ok', 'stores': 1, 'cohorts': 1, 'bytes': 100}
        stream = io.StringIO()
        with patch.object(M, 'export_database', return_value=expected) as export, redirect_stdout(stream):
            code = M.main(['--database', 'synthetic', '--output', 'synthetic-output'])
        self.assertEqual(code, 0)
        export.assert_called_once_with('synthetic', 'synthetic-output')
        self.assertEqual(json.loads(stream.getvalue()), expected)


if __name__ == '__main__':
    unittest.main()
