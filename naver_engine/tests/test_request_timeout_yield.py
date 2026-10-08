"""Opt-in batch timeouts cannot hide another bound, HTTP failure or earlier retry cause."""
from contextlib import ExitStack
import http.client
import json
import random
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

from naver_engine import naver_read as N
from naver_engine.tests.fake_naver import FakeClock
from naver_engine.tests.test_naver_read import NOW, check_handle, creds
from naver_engine.tests.test_network_deadline_diagnostics import DripSocket


class DeadlineTransport:
    def __init__(self, clock, *, phase='OPEN', status=None, kind='TIMEOUT', prior=None, early=False,
                 exhausted=True, remaining_ms=0, raw=False):
        self.clock, self.phase, self.status, self.kind = clock, phase, status, kind
        self.prior, self.early, self.calls = prior, early, []
        self.exhausted, self.remaining_ms, self.raw = exhausted, remaining_ms, raw
    def send(self, request, timeout):
        self.calls.append(timeout)
        if self.prior and len(self.calls) == 1:
            self.clock.advance(.01)
            if isinstance(self.prior, str):
                raise N.TransportNetworkError(N.NetworkDiagnostic(self.prior, 'OPEN', elapsed_ms=10,
                    remaining_ms=1000))
            return self.prior[0], json.dumps(self.prior[1]).encode()
        elapsed = .01 if self.early else timeout
        self.clock.advance(elapsed)
        if self.raw:
            raise TimeoutError('synthetic raw timeout')
        raise N.TransportNetworkError(N.NetworkDiagnostic(self.kind, self.phase,
            elapsed_ms=round(elapsed * 1000), remaining_ms=self.remaining_ms),
            http_status=self.status, timeout_exhausted=self.exhausted)


class RequestTimeoutYieldTests(unittest.TestCase):
    def run_abort(self, *, bounds=((30, True),), remaining=.333, **transport_options):
        clock = FakeClock(NOW)
        transport = DeadlineTransport(clock, **transport_options)
        reader = N.NaverReader(creds(), clock=clock, transport=transport, rng=random.Random(0))
        with patch.object(N.time, 'monotonic', side_effect=clock.monotonic), ExitStack() as stack:
            for seconds, opted in bounds:
                stack.enter_context(reader.bounded_requests(max_calls=24, max_seconds=seconds, yield_on_timeout=opted))
            clock.advance(min(b[0] for b in bounds) - remaining)
            with self.assertRaises(N.RunAbort) as caught:
                reader.get_campaigns(check_handle(now=clock.now()))
        self.assertEqual((reader._request_limits, reader._timeout_yield_bounds), ([], []))
        self.assertEqual(caught.exception.code, 'REQUEST_DEADLINE')
        return caught.exception, transport

    def test_opt_in_open_transport_and_200_body_timeouts_yield(self):
        for phase, status in (('OPEN', None), ('TRANSPORT', None), ('BODY', 200)):
            for kind in ('TIMEOUT', 'DEADLINE'):
                with self.subTest(phase=phase, kind=kind):
                    error, transport = self.run_abort(phase=phase, status=status, kind=kind)
                    self.assertIsNone(error.cause_code)
                    self.assertIsNone(error.network_diagnostic)
                    self.assertEqual(len(transport.calls), 1)
                    self.assertAlmostEqual(transport.calls[0], .333, places=5)

    def test_default_false_and_non_timeout_kinds_keep_network_failure(self):
        for opted, kind in ((False, 'TIMEOUT'), (True, 'DNS'), (True, 'RESET'), (True, 'TLS')):
            with self.subTest(opted=opted, kind=kind):
                error, _ = self.run_abort(bounds=((30, opted),), kind=kind)
                self.assertEqual(error.cause_code, N.KIND_NETWORK)
                self.assertEqual(error.network_diagnostic.kind, kind)

    def test_omitting_flag_keeps_legacy_network_failure(self):
        clock = FakeClock(NOW)
        transport = DeadlineTransport(clock)
        reader = N.NaverReader(creds(), clock=clock, transport=transport)
        with patch.object(N.time, 'monotonic', side_effect=clock.monotonic):
            with reader.bounded_requests(max_calls=24, max_seconds=30):
                self.assertEqual(reader._timeout_yield_bounds, [])
                clock.advance(29.667)
                with self.assertRaises(N.RunAbort) as caught:
                    reader.get_campaigns(check_handle(now=clock.now()))
        self.assertEqual(caught.exception.cause_code, N.KIND_NETWORK)

    def test_known_http_error_status_and_unknown_body_cannot_yield(self):
        for phase in ('OPEN', 'BODY', 'TRANSPORT'):
            for status in (401, 403, 429, 503):
                with self.subTest(phase=phase, status=status):
                    error, _ = self.run_abort(phase=phase, status=status)
                    self.assertEqual(error.cause_code, N.KIND_NETWORK)
        for phase, status in (('BODY', None), ('BODY', 206), ('OPEN', 200), ('TRANSPORT', 200)):
            with self.subTest(phase=phase, status=status):
                error, _ = self.run_abort(phase=phase, status=status)
                self.assertEqual(error.cause_code, N.KIND_NETWORK)

    def test_every_expired_nested_bound_must_opt_in(self):
        for bounds, expected in (
                (((30, True), (30, False)), N.KIND_NETWORK),
                (((30, False), (30, True)), N.KIND_NETWORK),
                (((30, True), (30, True)), None),
                (((30, False), (20, True)), None),
                (((20, False), (30, True)), N.KIND_NETWORK)):
            with self.subTest(bounds=bounds):
                error, _ = self.run_abort(bounds=bounds)
                self.assertEqual(error.cause_code, expected)

    def test_equal_nested_tuple_cleanup_preserves_outer_identity(self):
        clock = FakeClock(NOW)
        reader = N.NaverReader(creds(), clock=clock)
        with patch.object(N.time, 'monotonic', side_effect=clock.monotonic):
            with reader.bounded_requests(max_calls=24, max_seconds=30, yield_on_timeout=True):
                outer = reader._request_limits[0]
                with reader.bounded_requests(max_calls=24, max_seconds=30, yield_on_timeout=False):
                    self.assertEqual(outer, reader._request_limits[1])
                    self.assertIsNot(outer, reader._request_limits[1])
                self.assertIs(reader._request_limits[0], outer)
                self.assertIs(reader._timeout_yield_bounds[0], outer)
        self.assertEqual((reader._request_limits, reader._timeout_yield_bounds), ([], []))

    def test_prior_independent_dns_reset_server_and_rate_causes_survive_later_timeout(self):
        for prior, cause in (('DNS', N.KIND_NETWORK), ('RESET', N.KIND_NETWORK),
                             ((503, {}), N.KIND_SERVER), ((429, {'code': 1016}), N.KIND_RATE)):
            with self.subTest(prior=prior):
                error, transport = self.run_abort(bounds=((4, True),), remaining=4, prior=prior)
                self.assertEqual(error.cause_code, cause)
                self.assertEqual(len(transport.calls), 2)
                if isinstance(prior, str):
                    self.assertEqual(error.network_diagnostic.kind, prior)

    def test_full_twenty_second_timeout_keeps_prior_network_cause(self):
        error, transport = self.run_abort(remaining=30)
        self.assertEqual(transport.calls[0], 20)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(error.cause_code, N.KIND_NETWORK)

    def test_remaining_zero_diagnostic_does_not_substitute_for_actual_deadline(self):
        error, transport = self.run_abort(bounds=((4, True),), remaining=4, early=True)
        self.assertGreater(len(transport.calls), 1)
        self.assertEqual(error.cause_code, N.KIND_NETWORK)

    def test_early_wrapped_or_raw_timeout_stays_network_even_if_delivery_expires_batch(self):
        for options in ({'remaining_ms': 1}, {'exhausted': False}, {'exhausted': 1}, {'raw': True}):
            with self.subTest(options=options):
                error, _ = self.run_abort(**options)
                self.assertEqual(error.cause_code, N.KIND_NETWORK)

    def test_opt_in_flag_accepts_only_actual_booleans(self):
        reader = N.NaverReader(creds())
        for invalid in (0, 1, None, 'true', [], {}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                with reader.bounded_requests(max_calls=24, max_seconds=30, yield_on_timeout=invalid):
                    self.fail('invalid flag accepted')
        self.assertEqual((reader._request_limits, reader._timeout_yield_bounds), ([], []))


class TransportDeadlineMetadataTests(unittest.TestCase):
    def transport(self):
        transport = N.UrllibTransport.__new__(N.UrllibTransport)
        transport._opener = Mock()
        return transport

    def test_real_body_timeout_preserves_200_and_http_error_status(self):
        for status in (200, 401, 403, 429, 503):
            with self.subTest(status=status):
                clock = [0.0]
                response = http.client.HTTPResponse(DripSocket(b'PRIVATE_BODY' * 2, clock))
                response.begin()
                transport = self.transport()
                request = urllib.request.Request('https://api.searchad.naver.com/ncc/campaigns', method='GET')
                if status == 200:
                    transport._opener.open.return_value = response
                else:
                    transport._opener.open.side_effect = urllib.error.HTTPError(
                        request.full_url, status, 'PRIVATE', {}, response)
                with patch.object(N.time, 'monotonic', side_effect=lambda: clock[0]):
                    with self.assertRaises(N.TransportNetworkError) as caught:
                        transport.send(request, .2)
                self.assertEqual(caught.exception.http_status, status)
                self.assertTrue(caught.exception.timeout_exhausted)
                self.assertEqual(caught.exception.diagnostic.phase, 'BODY')
                self.assertEqual(caught.exception.diagnostic.remaining_ms, 0)
                self.assertNotIn('PRIVATE', str(caught.exception))

    def test_real_200_header_overrun_yields_only_after_own_batch_deadline(self):
        clock = FakeClock(NOW)
        response = http.client.HTTPResponse(DripSocket(b'[]', [0.0]))
        response.begin()
        transport = self.transport()
        def slow_open(request, timeout):
            clock.advance(timeout + .001)
            return response
        transport._opener.open.side_effect = slow_open
        reader = N.NaverReader(creds(), transport=transport, clock=clock)
        with patch.object(N.time, 'monotonic', side_effect=clock.monotonic):
            with reader.bounded_requests(max_calls=24, max_seconds=30, yield_on_timeout=True):
                clock.advance(29.667)
                with self.assertRaises(N.RunAbort) as caught:
                    reader.get_campaigns(check_handle(now=clock.now()))
        self.assertEqual(caught.exception.code, 'REQUEST_DEADLINE')
        self.assertIsNone(caught.exception.cause_code)
        self.assertIsNone(caught.exception.network_diagnostic)
        self.assertEqual(reader.calls, 1)
        self.assertTrue(response.isclosed())

    def test_known_status_is_recorded_before_open_overrun_budget_check(self):
        for status in (200, 401, 403, 429, 503):
            with self.subTest(status=status):
                clock = [0.0]
                response = http.client.HTTPResponse(DripSocket(b'PRIVATE_BODY', clock))
                response.begin()
                transport = self.transport()
                request = urllib.request.Request('https://api.searchad.naver.com/ncc/campaigns', method='GET')
                def slow_open(*args, **kwargs):
                    clock[0] = .5
                    if status == 200:
                        return response
                    raise urllib.error.HTTPError(request.full_url, status, 'PRIVATE', {}, response)
                transport._opener.open.side_effect = slow_open
                with patch.object(N.time, 'monotonic', side_effect=lambda: clock[0]):
                    with self.assertRaises(N.TransportNetworkError) as caught:
                        transport.send(request, .333)
                self.assertEqual(caught.exception.http_status, status)
                self.assertTrue(caught.exception.timeout_exhausted)
                self.assertEqual(caught.exception.diagnostic.phase, 'OPEN')

    def test_submillisecond_remaining_zero_does_not_claim_actual_timeout_exhaustion(self):
        clock = [0.0]
        transport = self.transport()
        def early_open(*args, **kwargs):
            clock[0] = .333 - .0004
            raise urllib.error.URLError(TimeoutError('PRIVATE'))
        transport._opener.open.side_effect = early_open
        request = urllib.request.Request('https://api.searchad.naver.com/ncc/campaigns', method='GET')
        with patch.object(N.time, 'monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(N.TransportNetworkError) as caught:
                transport.send(request, .333)
        self.assertEqual(caught.exception.diagnostic.remaining_ms, 0)
        self.assertFalse(caught.exception.timeout_exhausted)

    def test_optional_metadata_defaults_and_unsafe_values_are_conservative(self):
        diagnostic = N.NetworkDiagnostic('TIMEOUT', 'OPEN')
        default = N.TransportNetworkError(diagnostic)
        self.assertIsNone(default.http_status)
        self.assertFalse(default.timeout_exhausted)
        for value in (True, 99, 600, '503', {}):
            self.assertIsNone(N.TransportNetworkError(diagnostic, http_status=value).http_status)
        for value in (1, None, 'true', []):
            self.assertFalse(N.TransportNetworkError(diagnostic, timeout_exhausted=value).timeout_exhausted)


if __name__ == '__main__':
    unittest.main()
