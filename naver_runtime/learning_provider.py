"""Explicitly enabled, fixed-host Claude transport and conservative cost limits.

Import and configuration do not make requests. No model or price is inferred.
The store reserves maximum_call_microusd before each call against a durable cap.
"""
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import http.client
import math
import os

from naver_engine.marketing_strategy import StrategyRefused
from .claude_provider import AnthropicProvider, MAX_REQUEST_BYTES

HOST = "api.anthropic.com"
PATH = "/v1/messages"
URL = "https://" + HOST + PATH
MAX_OUTPUT_TOKENS = 2500


def _decimal(value, maximum):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise StrategyRefused("PROVIDER_CONFIGURATION_INVALID")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 < number <= maximum:
            raise ValueError()
        return number
    except (InvalidOperation, ValueError):
        raise StrategyRefused("PROVIDER_CONFIGURATION_INVALID") from None


class _Response:
    def __init__(self, response, connection):
        self._response, self._connection = response, connection
        self.status = response.status

    def read(self, maximum):
        return self._response.read(maximum)

    def close(self):
        try:
            self._response.close()
        finally:
            self._connection.close()


def _transport(request, *, timeout):
    """No proxy discovery, URL construction from input, redirect or retry path."""
    if (request.full_url != URL or request.allow_redirects is not False or request.get_method() != "POST" or
            not isinstance(request.data, bytes) or not 0 < len(request.data) <= MAX_REQUEST_BYTES or
            not isinstance(request.headers, dict) or set(request.headers) != {"x-api-key", "anthropic-version", "Content-Type"} or
            type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 20):
        raise StrategyRefused("PROVIDER_CONFIGURATION_INVALID")
    connection = None
    try:
        connection = http.client.HTTPSConnection(HOST, timeout=timeout)
        connection.request("POST", PATH, body=request.data, headers=dict(request.headers))
        response = connection.getresponse()
        return _Response(response, connection)
    except Exception:
        if connection is not None:
            connection.close()
        raise StrategyRefused("PROVIDER_UNAVAILABLE") from None


def provider_from_environment(environment=None):
    """Return None without reading credentials unless the enable flag is exact.

    Price settings are explicit USD per million tokens, versioned operationally
    with the selected model. Configuration never performs a paid validation call.
    """
    env = os.environ if environment is None else environment
    if env.get("NAVER_CLAUDE_ENABLED") != "true":
        return None
    cap = _decimal(env.get("NAVER_CLAUDE_MONTHLY_CAP_USD"), 100000)
    input_price = _decimal(env.get("NAVER_CLAUDE_INPUT_USD_PER_MILLION"), 10000)
    output_price = _decimal(env.get("NAVER_CLAUDE_OUTPUT_USD_PER_MILLION"), 10000)
    timeout = float(_decimal(env.get("NAVER_CLAUDE_TIMEOUT_SECONDS", "10"), 20))
    if timeout < 1:
        raise StrategyRefused("PROVIDER_CONFIGURATION_INVALID")
    provider = AnthropicProvider.from_environment(env, timeout=timeout, transport=_transport)
    # A byte per token is a conservative input bound for this bounded UTF-8 body.
    # Round the call upward and the monthly allowance downward to avoid overspend.
    provider.maximum_call_microusd = int((MAX_REQUEST_BYTES * input_price + MAX_OUTPUT_TOKENS * output_price).to_integral_value(rounding=ROUND_CEILING))
    provider.monthly_budget_microusd = int((cap * 1000000).to_integral_value(rounding=ROUND_FLOOR))
    if provider.monthly_budget_microusd < 1 or provider.maximum_call_microusd < 1:
        raise StrategyRefused("PROVIDER_CONFIGURATION_INVALID")
    return provider
