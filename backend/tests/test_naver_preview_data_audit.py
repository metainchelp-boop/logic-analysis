"""Synthetic SQLite only; audit returns aggregates, never business identifiers."""
import hashlib
import importlib.util
import json
import sqlite3
import ast
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('data_audit', Path(__file__).parents[1]/'tools/naver_preview_data_audit.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
NOW = datetime(2026, 10, 1, 13, tzinfo=timezone(timedelta(hours=9)))


class AuditTest(unittest.TestCase):
    def fixture(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript('''CREATE TABLE naver_auto_hold (kind, sync_id, at, codes, body, used_at, used_by);
            CREATE TABLE naver_auto_org (slot, generated_at, received_at, body);
            CREATE TABLE naver_auto_account (customer_id, present);
            CREATE TABLE naver_auto_meta (key, value);''')
        body = {'as_of': NOW.isoformat(), 'rows': [[10001, 'PRIVATE_COMPANY_A', '진행중', '2026-09-30', 0],
            [10002, 'PRIVATE_COMPANY_B', '홀딩중', None, 1]], 'conflicts': [10003],
            'per_spelling': {key: 0 for key in M.SPELLINGS}}
        body['per_spelling'].update({'진행중': 2, '홀딩중': 1, '진행 중': 1})
        raw = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
        db.execute('INSERT INTO naver_auto_hold VALUES (?,?,?,?,?,?,?)',
                   ('stages', 42, NOW.isoformat(), '["IMPLAUSIBLE_FIRST"]', raw, None, None))
        org = {'owners': [{'possibility_id': 10001, 'manage_emp_idx': 901, 'name': 'PRIVATE_EMPLOYEE'},
                          {'possibility_id': 99999}]}
        db.execute('INSERT INTO naver_auto_org VALUES (?,?,?,?)',
                   ('current', NOW.isoformat(), NOW.isoformat(), json.dumps(org)))
        db.executemany('INSERT INTO naver_auto_account VALUES (?,?)', [(10001, 1), (55555, 1), (77777, 0)])
        db.execute('INSERT INTO naver_auto_meta VALUES (?,?)', ('accounts_read_at', NOW.isoformat()))
        db.commit()
        return db, raw

    def test_exact_body_pin_stage_counts_and_real_org_overlap_not_cross_id_account_matching(self):
        db, raw = self.fixture()
        before = db.total_changes
        result = M.collect(db, NOW, timedelta(hours=3), timedelta(minutes=5))
        self.assertEqual(result['hold']['hold_id'], 42)
        self.assertEqual(result['hold']['body_sha256'], hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(result['hold']['expires_at'], (NOW+timedelta(hours=3)).isoformat())
        self.assertEqual(result['counts']['unique_total'], 3)
        self.assertEqual(result['counts']['stage_conflicts'], 1)
        self.assertEqual(result['counts']['repeated_source_observations'], 1)
        self.assertEqual(result['per_stage']['진행중'], 1)
        self.assertEqual(result['org']['held_ids_with_owner_row'], 1)
        self.assertEqual(result['accounts']['present'], 2)
        self.assertIs(result['accounts']['linkage_overlap_available'], False)
        self.assertNotIn('PRIVATE_', json.dumps(result))
        for identifier in ('10001', '10002', '10003', '99999', '55555', '901'):
            self.assertNotIn(identifier, json.dumps(result))
        self.assertEqual(db.total_changes, before)

    def test_stale_used_previous_kst_day_and_malformed_holds_fail_closed(self):
        for change in ('expired', 'used', 'yesterday', 'future', 'duplicate', 'unknown_stage'):
            with self.subTest(change=change):
                db, raw = self.fixture()
                now = NOW
                if change == 'expired':
                    now += timedelta(hours=3, microseconds=1)
                elif change == 'used':
                    db.execute('UPDATE naver_auto_hold SET used_at=?', (NOW.isoformat(),))
                elif change == 'yesterday':
                    now += timedelta(days=1)
                elif change == 'future':
                    now -= timedelta(minutes=5, microseconds=1)
                else:
                    body = json.loads(raw)
                    if change == 'duplicate':
                        body['rows'].append(body['rows'][0])
                    else:
                        body['rows'][0][2] = 'PRIVATE_STAGE'
                    db.execute('UPDATE naver_auto_hold SET body=?', (json.dumps(body),))
                with self.assertRaises(ValueError):
                    M.collect(db, now, timedelta(hours=3), timedelta(minutes=5))
        db, _ = self.fixture()
        self.assertTrue(M.collect(db, NOW+timedelta(hours=3), timedelta(hours=3), timedelta(minutes=5))['hold']['within_ttl'])

    def test_reader_program_is_memory_loadable_and_output_contract_rejects_private_extra_fields(self):
        module = types.ModuleType('approved_audit')
        exec(compile(SPEC.loader.get_source('data_audit'), '<approved-audit>', 'exec'), module.__dict__)
        program = module.script()
        ast.parse(program)
        self.assertIn(b'S.open_reader', program)
        self.assertIn(b'S.HOLD_TTL', program)
        self.assertNotIn(b'open_writer', program)
        db, _ = self.fixture()
        result = module.collect(db, NOW, timedelta(hours=3), timedelta(minutes=5))
        self.assertEqual(module.validate_result(result), result)
        result['company_name'] = 'PRIVATE_COMPANY'
        with self.assertRaises(ValueError):
            module.validate_result(result)

    def test_identity_gates_and_postflight_are_identical_to_existing_status_reader(self):
        baseline = ast.parse((Path(__file__).parents[1]/'tools/naver_preview_status.py').read_text())
        candidate = ast.parse(SPEC.loader.get_source('data_audit'))
        def run_body(tree):
            return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run').body
        def prefix(nodes):
            for index, node in enumerate(nodes):
                if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                        and str(node.value.value).startswith('read_only_')):
                    return nodes[:index]
            self.fail('Reader stage missing')
        old, new = run_body(baseline), run_body(candidate)
        self.assertEqual([ast.dump(n) for n in prefix(old)], [ast.dump(n) for n in prefix(new)])
        self.assertEqual(ast.dump(old[-2]), ast.dump(new[-2]))
        with self.assertRaises(ValueError):
            M.validate_package({'baseline': 'a'*64, 'source_commit': 'b'*40,
                                'source_tar_gz_sha256': 'c'*64, 'database': '/legacy'})


if __name__ == '__main__':
    unittest.main()
