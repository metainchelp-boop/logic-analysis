"""New probe branches only; in-memory fixtures, no production DB or host calls."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import types
import unittest
from unittest.mock import patch, MagicMock

HERE = Path(__file__).resolve()
CORE = HERE.with_name('naver_market_source_limit_probe.py')
if not CORE.is_file():
    CORE = HERE.parents[1]/'tools/naver_market_source_limit_probe.py'
SPEC = importlib.util.spec_from_file_location('market_source_limit_probe_test_core', CORE)
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
BACKEND = HERE.parents[1]
if not (BACKEND/'naver_market_export.py').is_file():
    for ancestor in HERE.parents:
        candidate = ancestor/'work/naver-claude-reference-ops-20261011/backend'
        if (candidate/'naver_market_export.py').is_file():
            BACKEND = candidate
            break
SOURCES = {'market_exporter': (BACKEND/'naver_market_export.py').read_bytes(),
           'product_exporter': (BACKEND/'naver_product_export.py').read_bytes()}


def market():
    return D._load_exporters(SOURCES, BACKEND)


def tables(conn):
    conn.executescript('''CREATE TABLE clients(id,naver_store_url,main_keywords,role,vertical);
CREATE TABLE client_keyword_product(client_id,keyword,product_url);
CREATE TABLE client_keyword_mute(client_id,keyword);
CREATE TABLE collector_observations(observation_id,keyword,collected_date,status,kind,reason,
 received_at,payload_hash,products_json,meta_json);
CREATE TABLE collected_serp(keyword,collected_date,total,products_json,meta_json);''')


def classify(call, m):
    try:
        call()
    except Exception as error:
        return D._classify_limit(error, m)
    raise AssertionError('fixture did not fail')


class MarketSourceLimitProbeTests(unittest.TestCase):
    def test_host_closed_json_text_and_child_json_bytes_contract(self):
        result = D.diagnose({})
        closed = D.closed_json(result)
        self.assertIs(type(closed), str)
        self.assertEqual(json.loads(closed), result)
        self.assertIs(type(D._probe_json(D.empty_probe())), bytes)

    def test_pinned_bytes_execute_without_second_source_load(self):
        m = market()
        self.assertEqual(m.collect.__code__.co_filename, str(BACKEND/'naver_market_export.py'))
        self.assertEqual(m.P._Budget.tick.__code__.co_firstlineno, 103)
        bad = dict(SOURCES, product_exporter=SOURCES['product_exporter']+b'\n')
        with self.assertRaises(D.ProbeStop):
            D._load_exporters(bad, BACKEND)

    def test_original_bytes_branch_and_shortcircuit_over_rows(self):
        m = market(); budget = m.P._Budget(m.Limits())
        result = classify(lambda: budget.tick(size=33554433, rows=100001), m)
        self.assertEqual(result['limit_branch'], 'input_bytes')
        self.assertIs(result['bytes_exceeded'], True)
        self.assertIs(result['rows_exceeded'], True)

    def test_original_rows_branch(self):
        m = market(); budget = m.P._Budget(m.Limits())
        self.assertEqual(classify(lambda: budget.tick(rows=100001), m)['limit_branch'], 'rows')

    def test_original_time_branch_without_second_clock(self):
        m = market(); budget = m.P._Budget(m.Limits()); budget.started -= 31
        result = classify(budget.tick, m)
        self.assertEqual(result['limit_branch'], 'time')
        self.assertIs(result['bytes_exceeded'], False)
        self.assertIs(result['rows_exceeded'], False)

    def test_progress_interrupt_rethrows_original_exception_budget_time(self):
        m = market(); conn = sqlite3.connect(':memory:', isolation_level=None); tables(conn)
        conn.executemany('INSERT INTO clients VALUES (?,?,?,?,?)',
            ((str(i),'invalid','', 'other','store') for i in range(1000)))
        clock = iter((0, 31, 32))
        with patch.object(m.P.time, 'monotonic', side_effect=lambda: next(clock, 33)):
            result = D._collect_probe(m, conn, lambda: None)
        self.assertEqual(result['limit_branch'], 'time')
        self.assertEqual(result['phase'], 'exception_budget')
        self.assertEqual(result['collect_calls'], 1)
        conn.close()

    def test_original_assembly_budget_location(self):
        m = market(); conn = sqlite3.connect(':memory:', isolation_level=None); tables(conn)
        conn.execute('INSERT INTO clients VALUES (?,?,?,?,?)',
                     ('x','https://smartstore.naver.com/probe','', 'advertiser','store'))
        clock = iter((0, 0, 31))
        with patch.object(m.P.time, 'monotonic', side_effect=lambda: next(clock, 32)):
            result = D._collect_probe(m, conn, lambda: None)
        self.assertEqual(result['limit_branch'], 'time')
        self.assertEqual(result['phase'], 'assembly')
        conn.close()

    def test_original_cell_branch_only_fixed_column(self):
        m = market(); conn = sqlite3.connect(':memory:'); tables(conn)
        conn.execute('INSERT INTO clients VALUES (?,?,?,?,?)', ('x','q'*8193,'','advertiser','store'))
        budget = m.P._Budget(m.Limits())
        result = classify(lambda: list(m._rows(conn, 'clients', list(D.LAYOUTS['clients'][1]), budget, m.Limits())), m)
        self.assertEqual((result['limit_branch'], result['fixed_table'], result['fixed_column']),
                         ('cell', 'clients', 'naver_store_url'))
        self.assertNotIn('q'*30, D._probe_json(result).decode())
        conn.close()

    def test_real_collect_client_count_before_store_filter(self):
        m = market(); conn = sqlite3.connect(':memory:', isolation_level=None); tables(conn)
        conn.executemany('INSERT INTO clients VALUES (?,?,?,?,?)',
            ((str(i),'invalid','', 'advertiser','store') for i in range(10001)))
        result = D._collect_probe(m, conn, lambda: None)
        self.assertEqual(result['limit_branch'], 'client_count')
        self.assertEqual(result['collect_calls'], 1)
        conn.close()

    def test_original_collect_pass_discards_bundle(self):
        m = market(); conn = sqlite3.connect(':memory:', isolation_level=None); tables(conn)
        result = D._collect_probe(m, conn, lambda: None)
        self.assertEqual(result['status'], 'original_collect_passed')
        self.assertTrue(result['read_transaction_fds_bound'])
        self.assertEqual(set(result), set(D.empty_probe()))
        conn.close()

    def test_unknown_source_limit_code_location_is_not_guessed(self):
        m = market()
        result = classify(lambda: (_ for _ in ()).throw(m.ExportInvalid('SOURCE_LIMIT')), m)
        self.assertEqual(result['limit_branch'], 'unclassified_source_limit')

    def test_progress_calls_original_first_and_preserves_original_stop(self):
        m = market(); installed = []
        conn = types.SimpleNamespace(set_progress_handler=lambda cb,n: installed.append((cb,n)))
        wrapped = D.ProbeConnection(conn, m, lambda: None)
        budget = m.P._Budget(m.Limits()); budget.started -= 31
        wrapped.progress_calls = D.PROGRESS_MAX
        wrapped.set_progress_handler(budget.progress, 1000)
        self.assertEqual(installed[0][0](), 1)
        self.assertEqual(wrapped.guard, 'none')

    def test_opcode_guard_is_separate(self):
        m = market(); installed = []
        wrapped = D.ProbeConnection(types.SimpleNamespace(set_progress_handler=lambda cb,n: installed.append(cb)), m, lambda: None)
        budget = m.P._Budget(m.Limits())
        wrapped.progress_calls = D.PROGRESS_MAX-1
        wrapped.set_progress_handler(budget.progress, 1000)
        self.assertEqual(installed[0](), 1)
        self.assertEqual(wrapped.guard, 'opcode')

    def test_sql_guard_never_executes_over_limit(self):
        m = market(); seen = []
        wrapped = D.ProbeConnection(types.SimpleNamespace(execute=lambda *a: seen.append(a)), m, lambda: None)
        wrapped.sql = D.SQL_MAX
        with self.assertRaises(D.ProbeStop): wrapped.execute('SELECT x')
        self.assertEqual((wrapped.guard, seen), ('sql', []))

    def test_context_failure_overrides_collect_result(self):
        m = market(); conn = sqlite3.connect(':memory:', isolation_level=None); tables(conn)
        def changed(): raise D.ProbeStop()
        result = D._collect_probe(m, conn, changed)
        self.assertEqual(result['status'], 'source_context_changed')
        self.assertEqual(result['limit_branch'], 'none')
        conn.close()

    def test_original_other_failure_without_fd_binding_is_not_confirmed(self):
        m = market(); conn = sqlite3.connect(':memory:', isolation_level=None)
        def changed(): raise D.ProbeStop()
        result = D._collect_probe(m, conn, changed)
        self.assertEqual(result['status'], 'source_context_changed')
        self.assertFalse(result['read_transaction_fds_bound'])
        conn.close()

    def test_abnormal_or_invalid_child_body_keeps_database_state_unknown(self):
        for wait_status in (256, 15, 0):
            select = MagicMock(); select.__enter__.return_value = select
            select.select.return_value = [(1,1)]
            with patch.object(D.os,'pipe',return_value=(991,992)), patch.object(D.os,'fork',return_value=123), \
                 patch.object(D.os,'close'), patch.object(D.os,'read',side_effect=[b'{',b'']), \
                 patch.object(D.os,'waitpid',return_value=(123,wait_status)), \
                 patch.object(D.selectors,'DefaultSelector',return_value=select):
                result = D._run_child({}, {}, {}, BACKEND)
            self.assertIsNone(result['database_opened'])
            self.assertIsNone(result['collect_calls'])
            D._probe_json(result)

    def test_valid_child_body_preserves_known_database_state(self):
        body = D.empty_probe(); body['status'] = 'readonly_precondition_failed'
        select = MagicMock(); select.__enter__.return_value = select
        select.select.return_value = [(1,1)]
        with patch.object(D.os,'pipe',return_value=(991,992)), patch.object(D.os,'fork',return_value=123), \
             patch.object(D.os,'close'), patch.object(D.os,'read',side_effect=[D._probe_json(body),b'']), \
             patch.object(D.os,'waitpid',return_value=(123,0)), \
             patch.object(D.selectors,'DefaultSelector',return_value=select):
            result = D._run_child({}, {}, {}, BACKEND)
        self.assertIs(result['database_opened'],False)
        self.assertEqual(result['collect_calls'],0)

    def test_fd_binding_excludes_preexisting_fd_and_unexpected_file(self):
        regular = 0o100644
        family = {'': (1,2,regular,0,0), '-wal': (1,3,regular,0,0), '-shm': (1,4,regular,0,0)}
        with patch.object(D, '_fd_snapshot', return_value={4:family[''],5:family['-wal'],6:family['-shm']}):
            D._bind_sqlite_fds({}, family)
            with self.assertRaises(D.ProbeStop): D._bind_sqlite_fds({4:family['']}, family)
        with patch.object(D, '_fd_snapshot', return_value={4:family[''],5:family['-wal'],6:family['-shm'],7:(1,9,regular,0,0)}):
            with self.assertRaises(D.ProbeStop): D._bind_sqlite_fds({}, family)

    def test_namespace_failure_precedes_database_connect(self):
        opened = []
        with patch.object(D, '_namespace', side_effect=D.ProbeStop()), patch.object(D.sqlite3, 'connect', side_effect=lambda *a,**k: opened.append(a)):
            result = D._child_probe({}, SOURCES, {}, BACKEND)
        self.assertEqual(result['status'], 'readonly_precondition_failed')
        self.assertFalse(result['database_opened'])
        self.assertEqual(opened, [])

    def test_closed_shape_rejects_values_and_unknown_column(self):
        result = D.empty_probe(); result['raw'] = 'PRIVATE'
        with self.assertRaises(ValueError): D._probe_json(result)
        result = D.empty_probe(); result.update(fixed_table='clients', fixed_column='PRIVATE')
        with self.assertRaises(ValueError): D._probe_json(result)
        result = D.empty_probe(); result.update(status='diagnostic_guard', guard='wall', database_opened=None, collect_calls=None)
        self.assertIsNone(json.loads(D._probe_json(result))['database_opened'])


if __name__ == '__main__':
    unittest.main()
