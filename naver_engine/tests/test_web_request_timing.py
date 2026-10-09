"""정상 대표 GET의 요청별 수치만, 기존 응답/cursor/크기/권한 경계를 그대로 보존한다."""
import io
import json
import unittest
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
from unittest.mock import patch
from naver_engine import management_store as MS, store as S, web as WEB
from naver_engine.tests.test_web import WebBase

KEY = '_request_timing'
PHASE_KEYS = {'gate_ms','viewer_ms','handler_ms','response_ms','serialize_ms','thread_cpu_ms'}

class RequestTimingTest(WebBase):
    def test_only_successful_full_owner_get_exports_finite_numeric_phases(self):
        for path in ('/accounts', '/dashboard'):
            with self.subTest(path=path):
                status, body = self.get(path, 0, query='view_sync=1')
                self.assertEqual(status, 200)
                timing = body[KEY]
                self.assertLessEqual(PHASE_KEYS, set(timing))
                allowed = PHASE_KEYS | {f'store_{name}_{suffix}' for name in WEB._TIMED_READ_METHODS
                                       for suffix in ('calls','wall_ms','thread_cpu_ms')}
                self.assertLessEqual(set(timing), allowed)
                self.assertGreater(timing['store_accounts_calls'], 0)
                for value in timing.values():
                    self.assertIs(type(value), float)
                    self.assertTrue(0 <= value <= 3600000)
                self.assertGreaterEqual(timing['response_ms'] + 0.01, timing['viewer_ms'] + timing['handler_ms'])

    def test_staff_narrowed_and_other_routes_do_not_export(self):
        for path in ('/accounts', '/dashboard'):
            for idx, narrowed in ((100, False), (0, True)):
                with self.subTest(path=path, idx=idx, narrowed=narrowed):
                    status, body = self.get(path, idx, narrowed=narrowed, query='view_sync=1')
                    self.assertEqual(status, 200)
                    self.assertNotIn(KEY, body)
        for path in ('/me', '/accounts', '/dashboard', '/board', '/health', '/not-found'):
            self.assertNotIn(KEY, self.get(path, 0)[1])
        self.assertNotIn(KEY, self.call('GET', '/me')[1])
        self.assertNotIn(KEY, self.call('POST', '/me', self.token(0))[1])

    def test_view_cursor_and_business_payload_ignore_live_request_timing(self):
        source = {'rows': [{'ad_account_no':'12345', 'mapping':'matched'}], 'matching_ready':True}
        with patch.object(WEB.INV, 'board', return_value=source):
            status, first = self.get('/accounts', 0, query='view_sync=1')
            self.assertEqual(status, 200)
            self.assertEqual(first['data'], source)
            self.assertNotIn(KEY, source)
            self.assertNotIn(KEY, first['data'])
            status, second = self.get('/accounts', 0, query='view_sync=1&view_cursor='+first['cursor'])
            self.assertEqual(status, 200)
            self.assertEqual(second['mode'], 'unchanged')
            self.assertEqual(second['cursor'], first['cursor'])
            self.assertIn(KEY, second)
            self.assertNotIn(KEY, second.get('data') or {})

    def test_business_payload_is_same_and_large_json_serializes_once(self):
        source = {'rows': [], 'matching_ready':True, 'note':'x'*100000}
        original_dump = WEB.json.dumps
        calls, holder = [], {}
        original_respond = self.app._respond
        def capture(env):
            result = original_respond(env)
            holder['wire_body'] = result[1]
            return result
        def tracked(value, *args, **kwargs):
            if value is holder.get('wire_body'):
                calls.append(1)
            return original_dump(value, *args, **kwargs)
        with patch.object(WEB.INV, 'board', return_value=source), patch.object(WEB.json, 'dumps', side_effect=tracked), patch.object(self.app,'_respond',side_effect=capture):
            status, body, headers, raw = self.call('GET', '/accounts', self.token(0),query='view_sync=1')
        self.assertEqual(status, 200)
        self.assertEqual(calls, [1])
        self.assertEqual(headers['Content-Length'], str(len(raw)))
        self.assertEqual(body.pop(KEY), {k:body_value for k,body_value in json.loads(raw)[KEY].items()})
        self.assertEqual(body['data'], source)

    def test_response_near_relay_max_keeps_original_bytes_without_timing(self):
        prefix = len(json.dumps({'note':''}, ensure_ascii=False, separators=(',',':')).encode())
        source = {'note':'x'*(WEB.VS.RESPONSE_MAX_BYTES-prefix-2)}
        expected = json.dumps(source, ensure_ascii=False, separators=(',',':')).encode()
        with patch.object(WEB.INV, 'board', return_value=source):
            status, body, _, raw = self.call('GET','/accounts',self.token(0),query='view_sync=1')
        self.assertEqual(status,200)
        self.assertNotIn(KEY,body)
        self.assertEqual(raw,expected)

    def test_json_failure_exports_no_timing_or_source(self):
        with patch.object(WEB.INV, 'board', return_value={'private':object()}):
            status, body = self.get('/accounts',0)
        self.assertEqual(status,500)
        self.assertEqual(body,{'error':'internal'})

    def test_bad_clock_observation_does_not_change_business_response(self):
        source = {'rows':[], 'matching_ready':True}
        with patch.object(WEB.INV, 'board', return_value=source), patch.object(WEB._time,'perf_counter',return_value=float('nan')):
            status,body = self.get('/accounts',0,query='view_sync=1')
        self.assertEqual(status,200)
        self.assertNotIn(KEY,body)
        self.assertEqual(body['data'],source)

    def test_spoofed_wsgi_holder_is_replaced_and_never_exports_on_staff(self):
        status, body, _, _ = self.call('GET','/me',self.token(100),headers={'naver_engine.request_timing':{'export':True, 'viewer_ms':123}})
        self.assertEqual(status,200)
        self.assertNotIn(KEY,body)

    def test_empty_business_object_and_existing_metadata_key_remain_valid(self):
        with patch.object(WEB.INV,'board',return_value={}):
            status,body = self.get('/accounts',0,query='view_sync=1')
        self.assertEqual(status,200)
        self.assertEqual(body['data'],{})
        self.assertIn(KEY,body)
        source={KEY:{'existing':True}}
        with patch.object(WEB.INV,'board',return_value=source):
            status,body=self.get('/accounts',0)
        self.assertEqual(body,source)

    def test_real_delays_are_attributed_to_viewer_and_handler(self):
        import time
        original=self.app._viewer
        def slow_viewer(*args,**kwargs):
            time.sleep(0.012)
            return original(*args,**kwargs)
        def slow_handler(*args,**kwargs):
            time.sleep(0.012)
            return {'rows':[]}
        with patch.object(self.app,'_viewer',side_effect=slow_viewer), patch.object(WEB.INV,'board',side_effect=slow_handler):
            status,body=self.get('/accounts',0,query='view_sync=1')
        self.assertEqual(status,200)
        self.assertGreaterEqual(body[KEY]['viewer_ms'],10)
        self.assertGreaterEqual(body[KEY]['handler_ms'],10)

    def test_real_reader_shares_one_management_snapshot_and_preserves_sql_count(self):
        original_open = self.app._open_read
        readers, counts = [], []
        def opened():
            reader = original_open()
            counter = [0]
            reader._conn.set_trace_callback(lambda sql: counter.__setitem__(0, counter[0]+1))
            readers.append(reader)
            counts.append(counter)
            return reader
        with patch.object(self.app, '_open_read', side_effect=opened):
            with patch.object(WEB, '_TimedReadStore', side_effect=lambda store, timings: store), \
                 patch.object(MS, 'snapshot', wraps=MS.snapshot) as baseline:
                expected_status, expected = self.get('/accounts', 0, query='view_sync=1')
                self.assertEqual(baseline.call_count, 1)
                self.assertIs(baseline.call_args.args[0], readers[-1])
            with patch.object(MS, 'snapshot', wraps=MS.snapshot) as measured:
                status, actual = self.get('/accounts', 0, query='view_sync=1&view_cursor='+expected['cursor'])
                self.assertEqual(measured.call_count, 1)
                self.assertIs(measured.call_args.args[0], readers[-1])
        self.assertEqual(status, expected_status)
        self.assertEqual(actual['mode'], 'unchanged')
        self.assertIsNone(actual['data'])
        self.assertEqual(actual['cursor'], expected['cursor'])
        self.assertEqual(counts[0], counts[1])
        self.assertEqual(actual[KEY]['store_inventory_collection_summaries_calls'], 1)
        self.assertNotIn('store_performance_checks_calls', actual[KEY])  # original self call is inclusive
        self.assertNotIn('store_structure_reason_summaries_calls', actual[KEY])

    def test_original_snapshot_and_close_happen_once_even_if_handler_fails(self):
        original_open = self.app._open_read
        for fails in (False, True):
            events = []
            def opened():
                reader = original_open()
                original_snapshot, original_close = reader.read_snapshot, reader.close
                @contextmanager
                def snapshot():
                    events.append('snapshot-enter')
                    with original_snapshot():
                        try:
                            yield
                        finally:
                            events.append('snapshot-exit')
                def close():
                    events.append('close')
                    return original_close()
                reader.read_snapshot, reader.close = snapshot, close
                return reader
            def board(ctx, store, *args, **kwargs):
                store.accounts()
                if fails:
                    raise S.StoreError('synthetic-no-raw-values')
                return {'rows': []}
            with self.subTest(fails=fails), patch.object(self.app, '_open_read', side_effect=opened), \
                 patch.object(WEB.INV, 'board', side_effect=board):
                status, body = self.get('/accounts', 0, query='view_sync=1')
            self.assertEqual(events, ['snapshot-enter', 'snapshot-exit', 'close'])
            self.assertEqual(status, 503 if fails else 200)
            if fails:
                self.assertNotIn(KEY, body)

    def test_no_delegator_for_plain_staff_narrowed_or_retired_next_request(self):
        with patch.object(WEB, '_TimedReadStore', wraps=WEB._TimedReadStore) as delegated:
            for path, idx, narrowed, query in (('/accounts',0,False,''),('/dashboard',100,False,'view_sync=1'),
                    ('/accounts',0,True,'view_sync=1'),('/me',0,False,'')):
                self.get(path,idx,narrowed=narrowed,query=query)
            self.assertEqual(delegated.call_count,0)
            token = self.token(0)
            self.assertEqual(self.call('GET','/accounts',token,query='view_sync=1')[0],200)
            self.assertEqual(delegated.call_count,1)
            original_scope = WEB.SC.scope_of
            def retired(org, who):
                return replace(original_scope(org,who),kind=WEB.SC.NONE)
            with patch.object(WEB.SC,'scope_of',side_effect=retired):
                status,body,_,_ = self.call('GET','/accounts',token,query='view_sync=1')
            self.assertEqual(status,401)
            self.assertNotIn(KEY,body)
            self.assertEqual(delegated.call_count,1)

    def test_same_app_concurrent_requests_keep_read_counts_local(self):
        joined = threading.Barrier(2)
        def board(ctx, store, scope, selection, workflow, mapping, view):
            joined.wait(timeout=3)
            store.accounts()
            if mapping == 'matched':
                store.accounts()
            return {'rows': []}
        with patch.object(WEB.INV, 'board', side_effect=board), ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(self.get,'/accounts',0,query='view_sync=1')
            two = pool.submit(self.get,'/accounts',0,query='view_sync=1&mapping=matched')
            first,second = one.result(timeout=5),two.result(timeout=5)
        self.assertEqual(first[0],200)
        self.assertEqual(second[0],200)
        # load_inventory calls accounts once before board; board adds one or two calls.
        self.assertEqual(first[1][KEY]['store_accounts_calls'],2)
        self.assertEqual(second[1][KEY]['store_accounts_calls'],3)

    def test_existing_read_delay_is_separated_from_thread_cpu(self):
        import time
        original = S.Store.accounts
        def slow(reader):
            time.sleep(.012)
            return original(reader)
        with patch.object(S.Store,'accounts',slow):
            status,body = self.get('/accounts',0,query='view_sync=1')
        self.assertEqual(status,200)
        self.assertEqual(body[KEY]['store_accounts_calls'],1)
        self.assertGreaterEqual(body[KEY]['store_accounts_wall_ms'],10)
        self.assertLess(body[KEY]['store_accounts_thread_cpu_ms'],body[KEY]['store_accounts_wall_ms'])


class TimedReadDelegationTest(unittest.TestCase):
    def test_exact_args_result_identity_and_optional_attributes_are_preserved(self):
        sentinel, calls = object(), []
        class Original:
            value = sentinel
            performance_checks = None
            def accounts(self, *args, **kwargs):
                calls.append((self,args,kwargs))
                return sentinel
        original, observations = Original(), {}
        proxy = WEB._TimedReadStore(original, observations)
        self.assertIs(proxy.accounts('marker', options=sentinel),sentinel)
        self.assertEqual(calls,[(original,('marker',),{'options':sentinel})])
        self.assertIs(proxy.value,sentinel)
        self.assertIsNone(proxy.performance_checks)
        self.assertIsNone(getattr(proxy,'missing_optional',None))
        self.assertEqual(set(observations),{'accounts'})
        self.assertEqual(observations['accounts'][0],1)

    def test_original_exception_identity_survives_clock_failures(self):
        error = ValueError('synthetic-marker-never-exported')
        class Original:
            def accounts(self):
                raise error
        for clock in ([0.0,float('nan')],[1.0,0.0],[0.0,RuntimeError('clock')],[RuntimeError('clock')]):
            observations = {}
            with self.subTest(clock=clock), patch.object(WEB._time,'perf_counter',side_effect=clock):
                with self.assertRaises(ValueError) as caught:
                    WEB._TimedReadStore(Original(),observations).accounts()
            self.assertIs(caught.exception,error)
            self.assertEqual(observations,{})

    def test_success_survives_bad_clocks_and_only_fixed_names_are_collected(self):
        sentinel = object()
        class Original:
            def accounts(self): return sentinel
            def unrelated_private_name(self): return sentinel
        for clock in ([0.0,float('nan')],[1.0,0.0],[0.0,RuntimeError('clock')],[RuntimeError('clock')]):
            observations = {}
            with self.subTest(clock=clock),patch.object(WEB._time,'perf_counter',side_effect=clock):
                proxy = WEB._TimedReadStore(Original(),observations)
                self.assertIs(proxy.accounts(),sentinel)
                self.assertIs(proxy.unrelated_private_name(),sentinel)
            self.assertEqual(observations,{})
