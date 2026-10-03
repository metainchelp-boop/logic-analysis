"""Synthetic legacy database; no credentials are decrypted or returned."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import types
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('legacy_audit', Path(__file__).parents[1]/'tools/naver_preview_legacy_audit.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class LegacyAuditTest(unittest.TestCase):
    def fixture(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.executescript('''CREATE TABLE clients(id INTEGER, status TEXT, erp_possibility_id INTEGER);
            CREATE TABLE channel_credentials(id INTEGER, client_id INTEGER, channel TEXT,
                mode TEXT, status TEXT, fields_json TEXT);''')
        conn.executemany('INSERT INTO clients VALUES (?,?,?)', [(910001, 'active', 990001), (910002, 'archived', None)])
        full = json.dumps(dict(customer_id='PRIVATE_ID_CIPHERTEXT', api_license='PRIVATE_KEY', secret_key='PRIVATE_SECRET'))
        conn.executemany('INSERT INTO channel_credentials VALUES (?,?,?,?,?,?)', [
            (1, 910001, 'naver_searchad', 'delegated', 'connected', full),
            (2, 910002, 'naver_searchad', 'direct', 'connected', '{"customer_id":"PRIVATE_OTHER"}'),
            (3, 910001, 'naver_searchad', 'upload', 'disconnected', 'invalid'),
            (4, 999999, 'naver_searchad', 'PRIVATE_MODE', 'PRIVATE_STATUS', '[]'),
            (5, 910001, 'other_channel', 'direct', 'connected', full)])
        conn.commit()
        return conn

    def test_returns_only_exact_aggregate_counts_without_changes(self):
        conn = self.fixture()
        before = conn.total_changes
        result = M.collect(conn)
        self.assertEqual(result, dict(credential_rows=4, unique_clients=3,
            customer_id_ciphertext_present=2, three_fields_present=1,
            erp_linked_rows=2, three_fields_with_erp_link=1, connected_rows=2,
            active_client_rows=2, invalid_json_rows=2,
            mode_delegated_rows=1, mode_direct_rows=1, mode_upload_rows=1, mode_other_rows=1))
        self.assertEqual(M.validate_result(result), result)
        self.assertEqual(conn.total_changes, before)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('910001', json.dumps(result))

    def test_read_guard_denies_mutations_attachment_extensions_and_other_columns(self):
        conn = self.fixture()
        M.collect(conn)
        for sql in ("DELETE FROM clients", "CREATE TABLE leak(v)", "PRAGMA query_only=OFF",
                    "ATTACH ':memory:' AS other", "SELECT load_extension('anything')",
                    "SELECT id FROM channel_credentials", 'COMMIT'):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                conn.execute(sql)
        self.assertFalse(conn.in_transaction)

    def test_empty_database_and_nontext_fields_are_not_credentials(self):
        conn = self.fixture()
        conn.execute('DELETE FROM channel_credentials')
        conn.commit()
        self.assertEqual(M.collect(conn), dict.fromkeys(M.FIELDS, 0))
        conn = self.fixture()
        conn.execute("UPDATE channel_credentials SET fields_json=?", (json.dumps(dict(customer_id=123, api_license={}, secret_key=[])),))
        conn.commit()
        result = M.collect(conn)
        self.assertEqual(result['customer_id_ciphertext_present'], 0)
        self.assertEqual(result['three_fields_present'], 0)

    def test_result_and_input_are_exact_and_bounded(self):
        good = dict.fromkeys(M.FIELDS, 0)
        for field, value in [('name', 'PRIVATE'), ('credential_rows', True),
                             ('credential_rows', -1), ('credential_rows', 2**31),
                             ('connected_rows', 1), ('unique_clients', '1')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                M.validate_result(dict(good, **{field: value}))
        bad = dict(good, credential_rows=1)
        with self.assertRaises(ValueError):
            M.validate_result(bad)
        with self.assertRaises(ValueError):
            M.validate_package(dict(baseline='a'*64, source_commit='b'*40,
                                    source_tar_gz_sha256='c'*64, database='/other'))

    def runner(self):
        package = dict(baseline='a'*64, source_commit='b'*40, source_tar_gz_sha256='c'*64)
        identity = dict(id='d'*64, name='/ad-api', image='sha256:'+'e'*64, running=True,
                        user='1000', service='ad-api', started='FIXED', restarts=0)
        host = types.SimpleNamespace(baseline=Mock(return_value=package['baseline']))
        result = dict.fromkeys(M.FIELDS, 0)
        release = types.SimpleNamespace(unique=lambda pairs: dict(pairs),
            command=Mock(side_effect=[json.dumps(identity).encode(), json.dumps(result).encode(),
                                      json.dumps(identity).encode()]))
        return package, identity, host, release

    def test_runner_uses_fixed_container_default_user_script_and_checks_baseline_twice(self):
        package, identity, host, release = self.runner()
        with patch.object(M.os, 'geteuid', return_value=0):
            result = M.run(package, host, release)
        self.assertEqual(host.baseline.call_count, 2)
        self.assertTrue(result['existing_app_baseline_unchanged'])
        command = release.command.call_args_list[1]
        self.assertEqual(command.args[0], ['docker','exec','-i',identity['id'],'python','-I','-B','-'])
        self.assertEqual(command.kwargs['data'], M.fixed_script())
        program = M.fixed_script().decode()
        self.assertIn('file:/app/data/app.db?mode=ro', program)
        self.assertNotIn('app.security', program)
        self.assertNotIn('decrypt', program)
        compile(program, '<fixed-reader>', 'exec')

    def test_identity_command_failure_and_postflight_drift_fail_closed(self):
        package, identity, host, release = self.runner()
        with patch.object(M.os, 'geteuid', return_value=0):
            host.baseline.side_effect = [package['baseline'], 'f'*64]
            with self.assertRaisesRegex(ValueError, 'POST_BASELINE'):
                M.run(package, host, release)
        package, identity, host, release = self.runner()
        release.command.side_effect = [json.dumps(identity).encode(), RuntimeError('COMMAND_FAILED'), json.dumps(identity).encode()]
        with patch.object(M.os, 'geteuid', return_value=0), self.assertRaisesRegex(RuntimeError, 'COMMAND_FAILED'):
            M.run(package, host, release)
        self.assertEqual(host.baseline.call_count, 2)
        package, identity, host, release = self.runner()
        identity['service'] = 'unexpected'
        release.command.side_effect = [json.dumps(identity).encode()]
        with patch.object(M.os, 'geteuid', return_value=0), self.assertRaisesRegex(ValueError, 'LEGACY_CONTAINER_IDENTITY'):
            M.run(package, host, release)
        self.assertEqual(release.command.call_count, 1)


if __name__ == '__main__':
    unittest.main()
