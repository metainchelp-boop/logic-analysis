"""One explicitly authorized fixed text comparison; no DB, prompt or secret output."""
import json
import math
import re
import time
from naver_engine import marketing_strategy as STR
from naver_runtime import claude_provider as CP, learning_provider as LP, provider_observability as OBS

PROBE = 'claude-minimal-structured-baseline-v1'
PROMPT = 'Reply with OK.'
MAX_ERROR_BODY_BYTES = 4096
SCHEMA = {'type': 'json_schema', 'schema': {'type': 'object', 'properties': {'answer': {'type': 'string', 'enum': ['OK']}}, 'required': ['answer'], 'additionalProperties': False}}
_ALLOWED = OBS._HTTP400_DIAGNOSTICS | frozenset(('none','not-enabled','unsupported-policy',
    'configuration','timeout','tls','network','protocol','unknown','http','response-size',
    'response-shape','envelope-json','truncated','response-close',
    'http-max-tokens-parameter','http-messages-parameter','http-system-parameter'))


def _http400_diagnostic(response):
    """RAM-only bounded classification; never return remote text or identifiers."""
    try:
        raw = response.read(MAX_ERROR_BODY_BYTES+1)
    except Exception:
        return "http-error-read"
    if type(raw) is not bytes:
        return "http-error-body-type"
    if len(raw) > MAX_ERROR_BODY_BYTES:
        return "http-error-body-size"
    try:
        envelope = STR._json(raw.decode("utf-8"))
    except Exception:
        return "http-error-json"
    if (type(envelope) is not dict or envelope.get("type") != "error"
            or type(envelope.get("error")) is not dict):
        return "http-error-envelope"
    error = envelope["error"]
    if error.get("type") != "invalid_request_error":
        return "http-error-type"
    message = error.get("message")
    if type(message) is not str:
        return "http-error-message"
    if re.search(r"[\x00-\x1f\x7f]", message):
        return "http-error-control"
    try:
        complexity_sentence = "Schema is too complex for compilation."
        if message == complexity_sentence or message.startswith(complexity_sentence+" "):
            return "http-schema-complexity"
        prefixes = (
            ("You have reached your specified API usage limits", "http-spend-limit"),
            ("You have reached your specified workspace API usage limits", "http-spend-limit"),
            ("Your credit balance is too low to access the Anthropic API.", "http-credit-balance"),
        )
        for prefix, reason in prefixes:
            suffix = message[len(prefix):]
            if message.startswith(prefix) and (not suffix or suffix[0] in " .:"):
                return reason
        # A leading API parameter path identifies the rejected field only.
        # It does not prove unsupported syntax, unavailable model, or a cause.
        field, separator, _ = message.partition(": ")
        fields = (("output_config.format", "http-format-parameter"),
            ("model", "http-model-parameter"), ("thinking", "http-thinking-parameter"),
            ("output_config.effort", "http-thinking-parameter"),
            ("max_tokens", "http-max-tokens-parameter"),
            ("messages", "http-messages-parameter"), ("system", "http-system-parameter"))
        for prefix, reason in fields:
            suffix = field[len(prefix):] if field.startswith(prefix) else None
            if separator and (field == prefix or suffix and re.fullmatch(
                    r"(?:\.(?:[A-Za-z_][A-Za-z0-9_]*|[0-9]+)|\[[0-9]+\])+", suffix)):
                return reason
    except Exception:
        # A boundary label never changes the authoritative original HTTP400.
        return "http-error-unclassified"
    return "http-error-unclassified"


def _message_terms(raw):
    try:
        if type(raw) is not bytes or len(raw)>MAX_ERROR_BODY_BYTES:
            return None
        value=STR._json(raw.decode('utf-8'))
        if type(value) is not dict or value.get('type')!='error' or type(value.get('error')) is not dict:
            return None
        error=value['error'];message=error.get('message')
        if error.get('type')!='invalid_request_error' or type(message) is not str or re.search(r"[\x00-\x1f\x7f]",message):
            return None
        terms={'schema':r'\bschemas?\b','regex':r'\bregex(?:es)?\b|\bregular expressions?\b',
            'pattern':r'\bpatterns?\b','noncapturing':r'\bnon[- ]?capturing\b|\(\?:',
            'group':r'\bgroups?\b','anchor':r'\banchors?\b','reference':r'\b(?:references?|refs?)\b|\$ref\b',
            'unsupported':r'\bunsupported\b|\bnot supported\b','compile':r'\b(?:compile|compilation|compiler)\b',
            'complexity':r'\b(?:complex|complexity)\b'}
        return {name:re.search(pattern,message,re.IGNORECASE) is not None for name,pattern in terms.items()}
    except Exception:
        return None


def _http400_observation(response):
    raw=[]
    class Capture:
        def read(self,maximum):
            value=response.read(maximum);raw.append(value);return value
    diagnostic=_http400_diagnostic(Capture())
    return diagnostic,_message_terms(raw[0]) if len(raw)==1 else None


def run(environment=None):
    """Return closed observations only; caller owns explicit one-call authorization."""
    started=time.monotonic()
    result={'version':1,'probe':PROBE,'ok':False,'stage':'configuration','diagnostic':'unknown',
        'http_status':None,'transport_calls':0,'response_closed':None,'message_terms':None,
        'checks':{'http_200':None,'end_turn':None,'text_nonempty':None,'exact_ok':None},
        'usage':OBS.parse_usage(None),'elapsed_ms':None}
    response=None
    try:
        provider=LP.provider_from_environment(environment)
        if provider is None:
            result['diagnostic']='not-enabled'
        elif provider.monthly_budget_unlimited is not True:
            result['diagnostic']='unsupported-policy'
        else:
            result['stage']='request'
            body={'model':provider.model,'max_tokens':CP.MAX_OUTPUT_TOKENS,
                'messages':[{'role':'user','content':PROMPT}]}
            if provider.model=='claude-sonnet-5-5':
                body.update(thinking={'type':'between_tools'},output_config={'effort':'medium'})
            body.setdefault('output_config',{})['format']=SCHEMA
            request=CP.ProviderRequest(data=json.dumps(body,ensure_ascii=False,allow_nan=False,
                separators=(',',':')).encode('utf-8'),headers={'x-api-key':provider._api_key,
                'anthropic-version':'2023-06-01','Content-Type':'application/json'})
            result['stage']='transport';result['transport_calls']=1
            response=LP._transport(request,timeout=provider._timeout)
            result['stage']='http'
            status=response.status
            if type(status) is not int or not 100<=status<=599:
                raise STR.StrategyRefused('PROVIDER_RESPONSE_INVALID')
            result['http_status']=status;result['checks']['http_200']=status==200
            if status!=200:
                hint='http'
                if status==400:
                    hint,result['message_terms']=_http400_observation(response)
                result['diagnostic']=hint if type(hint) is str and hint in _ALLOWED else 'unknown'
            else:
                result['stage']='response-read'
                raw=response.read(CP.MAX_RESPONSE_BYTES+1)
                if type(raw) is not bytes:
                    raise STR.StrategyRefused('PROVIDER_RESPONSE_INVALID')
                if len(raw)>CP.MAX_RESPONSE_BYTES:
                    raise STR.StrategyRefused('PROVIDER_RESPONSE_SIZE')
                result['stage']='response-json'
                try:
                    envelope=STR._json(raw.decode('utf-8'))
                except Exception:
                    raise STR.StrategyRefused('PROVIDER_ENVELOPE_JSON_INVALID') from None
                result['stage']='response-shape'
                if type(envelope) is not dict:
                    raise STR.StrategyRefused('PROVIDER_RESPONSE_INVALID')
                result['usage']=OBS.parse_usage(envelope.get('usage'))
                result['checks']['end_turn']=envelope.get('stop_reason')=='end_turn'
                if result['checks']['end_turn'] is not True:
                    raise STR.StrategyRefused('PROVIDER_RESPONSE_TRUNCATED' if envelope.get('stop_reason')=='max_tokens' else 'PROVIDER_RESPONSE_INVALID')
                text=CP._response_text(envelope.get('content'))
                result['checks']['text_nonempty']=bool(text.strip())
                result['checks']['exact_ok']=text.strip()=='OK'
                if not result['checks']['text_nonempty']:
                    raise STR.StrategyRefused('PROVIDER_RESPONSE_INVALID')
                result.update(ok=True,stage='completed',diagnostic='none')
    except Exception as error:
        try:
            code=OBS.diagnostic(error if isinstance(error,STR.StrategyRefused) else LP._transport_error(error))
            result['diagnostic']=code if type(code) is str and code in _ALLOWED else 'unknown'
        except Exception:
            result['diagnostic']='unknown'
    finally:
        if response is not None:
            try:
                response.close();result['response_closed']=True
            except Exception:
                result['response_closed']=False
                if result['ok']:
                    result.update(ok=False,stage='response-close',diagnostic='response-close')
        elapsed=time.monotonic()-started
        if math.isfinite(elapsed) and 0<=elapsed<=(2**53-1)/1000:
            result['elapsed_ms']=int(elapsed*1000)
    return result
