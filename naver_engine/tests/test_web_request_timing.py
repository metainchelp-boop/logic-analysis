"""정상 대표 GET의 요청별 수치만, 기존 응답/cursor/크기/권한 경계를 그대로 보존한다."""
import io
import json
from unittest.mock import patch
from naver_engine import web as WEB
from naver_engine.tests.test_web import WebBase

KEY = '_request_timing'

class RequestTimingTest(WebBase):
    def test_only_successful_full_owner_get_exports_finite_numeric_phases(self):
        for path in ('/accounts', '/dashboard'):
            with self.subTest(path=path):
                status, body = self.get(path, 0, query='view_sync=1')
                self.assertEqual(status, 200)
                timing = body[KEY]
                self.assertEqual(set(timing), {'gate_ms','viewer_ms','handler_ms','response_ms','serialize_ms','thread_cpu_ms'})
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
