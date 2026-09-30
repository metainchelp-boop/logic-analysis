"""§14 합성 전송만 — 업무 네트워크 0."""
import json
import unittest
from datetime import date, timedelta

from naver_engine import erp_alert as A
from naver_engine.credentials import Secret


def payload(**changes):
    data = dict(possibility_id=123, period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
                impressions=1000, clicks=20, spend=3000, conversions=2)
    data.update(changes)
    return A.build_metrics_payload(**data)


class Transport:
    def __init__(self, result=None):
        self.requests = []
        self.result = result if result is not None else {'recorded': True, 'reason': 'stored'}

    def send(self, req, timeout):
        self.requests.append(req)
        return 200, json.dumps({'status': 200, 'result': self.result}).encode()


class MetricsGateTest(unittest.TestCase):
    def test_numbers_only_fixed_path_and_one_post(self):
        transport = Transport()
        poster = A.ErpAlertPoster(Secret('SYNTHETIC-KEY-000000000000000000000'), transport=transport)
        self.assertTrue(poster.send_metrics(payload()).recorded)
        [req] = transport.requests
        self.assertEqual(req.full_url, 'http://api.metainc.co.kr/api/ad-sync/naver-metrics')
        self.assertEqual(req.get_method(), 'POST')
        self.assertEqual(json.loads(req.data), dict(possibility_id=123, period_start='2026-09-01',
            period_end='2026-09-30', impressions=1000, clicks=20, spend=3000, conversions=2))

    def test_rejects_non_integer_negative_and_unsafe_numbers(self):
        for field in ('impressions', 'clicks', 'spend', 'conversions'):
            for value in (True, None, '3', 3.0, -1, float('nan'), float('inf'), 9007199254740992):
                with self.subTest(field=field, value=value), self.assertRaises(A.AlertRejected):
                    payload(**{field: value})
        payload(impressions=9007199254740991, clicks=0, spend=0, conversions=0)
        for value in (True, None, '3', 3.0, -1, 0, 10**15):
            with self.assertRaises(A.AlertRejected):
                payload(possibility_id=value)

    def test_exact_30_days_only(self):
        for value in ('2026-09-01', None, date(2026, 8, 31), date(2026, 9, 2)):
            with self.assertRaises(A.AlertRejected):
                payload(period_start=value)

    def test_unknown_or_mismatched_acknowledgement_is_not_success(self):
        for value in ({}, {'recorded': 1, 'reason': 'stored'}, {'recorded': True, 'reason': 'no-client'},
                      {'recorded': False, 'reason': 'stored'}, {'recorded': True, 'reason': 'queued'},
                      {'recorded': True, 'reason': 'stored', 'secret': 'not-accepted'}):
            with self.subTest(value=value), self.assertRaises(A.AlertSendError):
                A.ErpAlertPoster(Secret('synthetic'), transport=Transport(value)).send_metrics(payload())
        result = A.ErpAlertPoster(Secret('synthetic'), transport=Transport(
            {'recorded': False, 'reason': 'no-client'})).send_metrics(payload())
        self.assertFalse(result.recorded)

    def test_payload_rebuilt_no_names_or_overridden_body_can_escape(self):
        class Sneaky(A.MetricsPayload):
            def body(self):
                return {'name': 'not-allowed'}
        good = payload()
        sneaky = Sneaky(**vars(good))
        transport = Transport()
        A.ErpAlertPoster(Secret('synthetic'), transport=transport).send_metrics(sneaky)
        self.assertEqual(json.loads(transport.requests[0].data), good.body())
        self.assertEqual(repr(good), 'MetricsPayload(redacted)')

    def test_handmade_invalid_payload_does_not_send(self):
        transport = Transport()
        poster = A.ErpAlertPoster(Secret('synthetic'), transport=transport)
        for invalid in ({'possibility_id': 1}, A.MetricsPayload(1, date(2026, 9, 1),
                         date(2026, 9, 30), 1, 2, True, 0)):
            with self.assertRaises(A.AlertRejected):
                poster.send_metrics(invalid)
        self.assertEqual(transport.requests, [])
