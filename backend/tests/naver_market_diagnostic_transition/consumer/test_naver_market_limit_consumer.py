"""Closed synthetic messages only; never invoke host inspection or a journal command."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import unittest


import test_sources as portable_sources
SOURCE = portable_sources.consumer_source_path()
SPEC = importlib.util.spec_from_file_location('market_limit_consumer_under_test', SOURCE)
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
ISSUES = ('input_bytes', 'rows', 'time', 'cell', 'clients', 'unknown')
NOW = 1800000000000000


def message(issue='rows', **extra):
    return json.dumps({'status': 'failed', 'code': 'SOURCE_LIMIT',
                       'limit_issue': issue, **extra})


def record(body, stamp=NOW, invocation='a' * 32, unit=None):
    return json.dumps({'_SYSTEMD_UNIT': unit or D.UNITS['market_reader'],
                       '__REALTIME_TIMESTAMP': str(stamp),
                       '_SYSTEMD_INVOCATION_ID': invocation,
                       'MESSAGE': body}).encode()


class MarketLimitConsumerTests(unittest.TestCase):
    def assert_not_promoted(self, body):
        roles, labels = D._labels(body)
        self.assertFalse(any(label.startswith('export_source_limit') for label in labels))
        return roles, labels

    def test_all_six_producer_values_have_exact_closed_labels(self):
        for issue in ISSUES:
            with self.subTest(issue=issue):
                self.assertEqual(D._labels(message(issue)),
                                 ([], ['export_source_limit', 'export_source_limit_' + issue]))

    def test_historical_two_key_source_limit_does_not_invent_reason(self):
        self.assertEqual(D._labels('{"status":"failed","code":"SOURCE_LIMIT"}'),
                         ([], ['export_source_limit']))

    def test_historical_source_read_issues_remain_distinct(self):
        expected = {'readonly': 'sqlite_readonly', 'sqlite_open': 'sqlite_open',
                    'schema': 'sqlite_schema', 'authorized': 'sqlite_authorization',
                    'locked': 'sqlite_locked', 'corrupt': 'sqlite_corrupt',
                    'unknown': 'sqlite_unknown'}
        for issue, label in expected.items():
            with self.subTest(issue=issue):
                value = {'status': 'failed', 'code': 'SOURCE_READ', 'source_issue': issue}
                self.assertEqual(D._labels(json.dumps(value)), ([], ['export_source_read', label]))

    def test_extra_fields_cannot_promote_a_source_limit_reason(self):
        for key in ('source_issue', 'data', 'path', 'count'):
            with self.subTest(key=key):
                self.assertEqual(self.assert_not_promoted(message(**{key: 'PRIVATE_VALUE'})), ([], []))

    def test_non_string_types_are_rejected_for_each_new_contract_field(self):
        for field in ('status', 'code', 'limit_issue'):
            for value in (True, False, 0, 1, 1.5, None, [], {}, ['rows']):
                with self.subTest(field=field, value=value):
                    payload = {'status': 'failed', 'code': 'SOURCE_LIMIT', 'limit_issue': 'rows'}
                    payload[field] = value
                    self.assertEqual(self.assert_not_promoted(json.dumps(payload)), ([], []))

    def test_unlisted_enum_and_wrong_status_or_code_are_rejected(self):
        for value in ('', 'ROWS', 'not_known', 'input_bytes ', 'PRIVATE_REASON'):
            self.assertEqual(self.assert_not_promoted(message(value)), ([], []))
        for payload in ({'status': 'ok', 'code': 'SOURCE_LIMIT', 'limit_issue': 'rows'},
                        {'status': 'failed', 'code': 'SOURCE_READ', 'limit_issue': 'rows'},
                        {'status': 'failed', 'code': 'SOURCE_LIMIT', 'source_issue': 'rows'}):
            self.assertEqual(self.assert_not_promoted(json.dumps(payload)), ([], []))

    def test_duplicate_nonfinite_trailing_and_malformed_json_are_rejected(self):
        for field in ('status', 'code', 'limit_issue'):
            payload = message()[:-1] + ',"' + field + '":"PRIVATE_DUPLICATE"}'
            self.assertEqual(self.assert_not_promoted(payload), ([], []))
        for value in ('NaN', 'Infinity', '-Infinity'):
            self.assertEqual(self.assert_not_promoted(
                '{"status":"failed","code":"SOURCE_LIMIT","limit_issue":' + value + '}'), ([], []))
        for body in (message() + ' PRIVATE_TRAILING', 'prefix ' + message(),
                     message()[:-1], '["SOURCE_LIMIT","rows"]', 'null'):
            self.assertEqual(self.assert_not_promoted(body), ([], []))

    def test_prose_cannot_claim_limit_reason_but_prior_generic_hints_remain(self):
        self.assertEqual(self.assert_not_promoted('SOURCE_LIMIT limit_issue=rows PRIVATE_TEXT'), ([], []))
        self.assertEqual(self.assert_not_promoted(message(data='permission denied')),
                         ([], ['permission_denied']))

    def test_projection_filters_other_units_and_retains_latest_invocation_only(self):
        raw = b'\n'.join((record(message('input_bytes'), NOW - 2, 'b' * 32),
                           record(message('rows'), NOW - 1),
                           record(message('cell'), NOW, unit=D.UNITS['product_reader'])))
        value = D._project(raw, 'market_reader', NOW)
        self.assertEqual(value['status'], 'observed')
        self.assertEqual(value['first_timestamp_us'], NOW - 1)
        self.assertEqual(value['last_timestamp_us'], NOW - 1)
        self.assertEqual(value['events'], [{'timestamp_us': NOW - 1, 'path_roles': [],
                                          'error_labels': ['export_source_limit', 'export_source_limit_rows']}])
        rendered = json.dumps(value)
        self.assertNotIn('a' * 32, rendered)
        self.assertNotIn('b' * 32, rendered)
        self.assertNotIn('MESSAGE', rendered)
        self.assertNotIn(D.UNITS['market_reader'], rendered)

    def test_new_labels_preserve_closed_projection_budget(self):
        raw = b'\n'.join(record(message('input_bytes'), NOW - 31 + index) for index in range(32))
        projected = D._project(raw, 'market_reader', NOW)
        value = D._limit_journal(projected)
        self.assertLessEqual(len(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()),
                             D.MAX_JOURNAL_OUTPUT)
        self.assertEqual(value['first_timestamp_us'], NOW - 31)
        self.assertEqual(value['last_timestamp_us'], NOW)
        self.assertTrue(value['events'])
        for event in value['events']:
            self.assertEqual(event['error_labels'], ['export_source_limit', 'export_source_limit_input_bytes'])

    def test_rejected_private_payload_is_never_returned_or_printed(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            value = D._project(record(message(data='PRIVATE_PAYLOAD_VALUE')), 'market_reader', NOW)
        self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(stderr.getvalue(), '')
        self.assertEqual(value['events'], [])
        self.assertNotIn('PRIVATE_', json.dumps(value))


if __name__ == '__main__':
    unittest.main()
