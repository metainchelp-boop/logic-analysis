"""The live transport is exercised only through synthetic HTTPS connections."""
from copy import deepcopy
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from naver_engine import marketing_strategy as STR
from naver_runtime import learning_provider as P, claude_provider as C


def environment():
    return {"NAVER_CLAUDE_ENABLED": "true", "ANTHROPIC_API_KEY": "FAKE_TEST_ONLY_KEY",
            "CLAUDE_MODEL": "explicit-test-model", "NAVER_CLAUDE_MONTHLY_CAP_USD": "20",
            "NAVER_CLAUDE_INPUT_USD_PER_MILLION": "2", "NAVER_CLAUDE_OUTPUT_USD_PER_MILLION": "10"}


class Response(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status
        self.read_limits = []

    def read(self, maximum=-1):
        self.read_limits.append(maximum)
        return super().read(maximum)


class Connection:
    def __init__(self, response):
        self.response, self.requests, self.closed = response, [], False

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def envelope():
    return json.dumps({"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(STR.document_template())}]}).encode()


class LearningProviderTests(unittest.TestCase):
    def test_disabled_reads_only_flag_and_never_opens_network(self):
        class Disabled:
            def get(self, key, *args):
                if key != "NAVER_CLAUDE_ENABLED":
                    raise AssertionError("Credentials were accessed while disabled")
                return "false"
        with patch.object(P.http.client, "HTTPSConnection", side_effect=AssertionError("network")):
            self.assertIsNone(P.provider_from_environment(Disabled()))
            for value in (None, "", "TRUE", True):
                self.assertIsNone(P.provider_from_environment({"NAVER_CLAUDE_ENABLED": value}))

    def test_enabled_requires_explicit_model_credentials_prices_and_cap(self):
        required = ("ANTHROPIC_API_KEY", "CLAUDE_MODEL", "NAVER_CLAUDE_MONTHLY_CAP_USD",
                    "NAVER_CLAUDE_INPUT_USD_PER_MILLION", "NAVER_CLAUDE_OUTPUT_USD_PER_MILLION")
        with patch.object(P.http.client, "HTTPSConnection", side_effect=AssertionError("network")):
            for key in required:
                with self.subTest(key=key):
                    env = environment()
                    del env[key]
                    with self.assertRaises(STR.StrategyRefused):
                        P.provider_from_environment(env)
            provider = P.provider_from_environment(environment())
            self.assertEqual(provider.model, "explicit-test-model")
            self.assertEqual(provider.monthly_budget_microusd, 20000000)
            self.assertEqual(provider.maximum_call_microusd, 90536)
            self.assertNotIn("FAKE_TEST_ONLY_KEY", repr(provider))

    def test_nonfinite_nonpositive_and_out_of_bounds_config_are_refused(self):
        for key in ("NAVER_CLAUDE_MONTHLY_CAP_USD", "NAVER_CLAUDE_INPUT_USD_PER_MILLION", "NAVER_CLAUDE_OUTPUT_USD_PER_MILLION"):
            for value in ("0", "-1", "NaN", "Infinity", "1e999", "bad", True, None):
                with self.subTest(key=key, value=value):
                    env = environment()
                    env[key] = value
                    with self.assertRaises(STR.StrategyRefused):
                        P.provider_from_environment(env)
        for value in ("0.5", "21", "NaN"):
            env = {**environment(), "NAVER_CLAUDE_TIMEOUT_SECONDS": value}
            with self.assertRaises(STR.StrategyRefused):
                P.provider_from_environment(env)

    def test_fixed_https_host_post_path_bounded_response_and_connection_close(self):
        response = Response(envelope())
        connection = Connection(response)
        factory_calls = []
        def factory(host, **kwargs):
            factory_calls.append((host, kwargs))
            return connection
        with patch.object(P.http.client, "HTTPSConnection", side_effect=factory), patch.dict("os.environ", {"HTTPS_PROXY": "http://untrusted.invalid"}):
            result = P.provider_from_environment(environment())({"metrics": {}})
        self.assertEqual(result, STR.document_template())
        self.assertEqual(factory_calls, [("api.anthropic.com", {"timeout": 10.0})])
        self.assertEqual(len(connection.requests), 1)
        args, kwargs = connection.requests[0]
        self.assertEqual(args, ("POST", "/v1/messages"))
        request = json.loads(kwargs["body"])
        self.assertEqual((request["model"], request["max_tokens"]), ("explicit-test-model", 2500))
        self.assertEqual(kwargs["headers"]["x-api-key"], "FAKE_TEST_ONLY_KEY")
        self.assertEqual(response.read_limits, [C.MAX_RESPONSE_BYTES + 1])
        self.assertTrue(response.closed)
        self.assertTrue(connection.closed)

    def test_redirect_error_oversize_and_malformed_response_never_retry_and_always_close(self):
        for status, body in ((302, b""), (429, b""), (500, b""), (200, b"invalid"), (200, b"x" * (C.MAX_RESPONSE_BYTES + 1))):
            with self.subTest(status=status, length=len(body)):
                response = Response(body, status)
                connection = Connection(response)
                with patch.object(P.http.client, "HTTPSConnection", return_value=connection) as factory:
                    with self.assertRaises(STR.StrategyRefused) as raised:
                        P.provider_from_environment(environment())({"metrics": {}})
                self.assertEqual(factory.call_count, 1)
                self.assertEqual(len(connection.requests), 1)
                self.assertTrue(response.closed)
                self.assertTrue(connection.closed)
                self.assertNotIn("FAKE_TEST_ONLY_KEY", str(raised.exception))

    def test_transport_request_error_and_read_error_close_connections(self):
        response = Response(envelope())
        connection = Connection(response)
        connection.request = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("PRIVATE ERROR"))
        with patch.object(P.http.client, "HTTPSConnection", return_value=connection):
            with self.assertRaises(STR.StrategyRefused) as raised:
                P.provider_from_environment(environment())({})
        self.assertTrue(connection.closed)
        self.assertNotIn("PRIVATE", str(raised.exception))
        response = Response(envelope())
        response.read = lambda *args: (_ for _ in ()).throw(OSError("PRIVATE ERROR"))
        connection = Connection(response)
        with patch.object(P.http.client, "HTTPSConnection", return_value=connection):
            with self.assertRaises(STR.StrategyRefused):
                P.provider_from_environment(environment())({})
        self.assertTrue(response.closed)
        self.assertTrue(connection.closed)

    def test_request_boundaries_and_alternate_destinations_are_rejected_before_network(self):
        base = {"full_url": P.URL, "allow_redirects": False, "data": b"{}",
                "headers": {"x-api-key": "FAKE", "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                "get_method": lambda: "POST"}
        variants = ({"full_url": "https://evil.invalid/v1/messages"}, {"allow_redirects": True},
                    {"data": b"x" * (C.MAX_REQUEST_BYTES + 1)}, {"get_method": lambda: "GET"},
                    {"headers": {**base["headers"], "Host": "evil.invalid"}})
        with patch.object(P.http.client, "HTTPSConnection", side_effect=AssertionError("network")):
            for variant in variants:
                with self.subTest(fields=list(variant)):
                    with self.assertRaises(STR.StrategyRefused):
                        P._transport(SimpleNamespace(**{**base, **variant}), timeout=10)
            for timeout in (True, 0, 21, float("nan")):
                with self.assertRaises(STR.StrategyRefused):
                    P._transport(SimpleNamespace(**base), timeout=timeout)

    def test_cost_upper_bound_rounds_up_monthly_cap_rounds_down(self):
        env = {**environment(), "NAVER_CLAUDE_MONTHLY_CAP_USD": "0.123456789",
               "NAVER_CLAUDE_INPUT_USD_PER_MILLION": "0.000001", "NAVER_CLAUDE_OUTPUT_USD_PER_MILLION": "0.000001"}
        provider = P.provider_from_environment(env)
        self.assertEqual(provider.monthly_budget_microusd, 123456)
        self.assertEqual(provider.maximum_call_microusd, 1)


if __name__ == "__main__":
    unittest.main()
