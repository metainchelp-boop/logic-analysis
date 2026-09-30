from unittest import TestCase
from unittest.mock import Mock, patch
from threading import Event

from naver_runtime import __main__ as M
from naver_engine import naver_read as N


class MetricsBudgetTest(TestCase):
    def test_retry_cannot_sleep_past_metrics_deadline(self):
        base = Mock()
        base.monotonic.return_value = 100
        clock = M.MetricsClock(base, seconds=45)
        with self.assertRaises(N.RunAbort):
            clock.sleep(300)
        base.sleep.assert_not_called()

    def test_elapsed_budget_refuses_new_request(self):
        base = Mock()
        base.monotonic.return_value = 100
        clock = M.MetricsClock(base, seconds=45)
        base.monotonic.return_value = 146
        with self.assertRaises(N.RunAbort):
            clock.before_network()

    def test_transport_timeout_is_clamped_to_remaining_budget(self):
        base = Mock()
        base.monotonic.return_value = 100
        clock = M.MetricsClock(base, seconds=45)
        transport = M.StopAwareTransport(clock)
        fake = Mock(return_value=(200, b'{}'))
        base.monotonic.return_value = 140
        with patch.object(transport._transport, 'send', fake):
            transport.send(object(), 20)
        self.assertEqual(fake.call_args.args[1], 5)

    def test_stop_remains_immediate_not_an_ordinary_retry(self):
        stop = Event()
        base = M.InterruptibleClock(stop)
        clock = M.MetricsClock(base)
        stop.set()
        with self.assertRaises(M.StopRequested):
            clock.before_network()
