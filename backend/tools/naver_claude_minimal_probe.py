"""One explicitly authorized fixed text comparison; no DB, prompt or secret output."""
import json
import math
import time
from naver_engine import marketing_strategy as STR
from naver_runtime import claude_provider as CP, learning_provider as LP, provider_observability as OBS

PROBE = 'claude-minimal-text-v1'
PROMPT = 'Reply with OK.'
_ALLOWED = OBS._HTTP400_DIAGNOSTICS | frozenset(('none','not-enabled','unsupported-policy',
    'configuration','timeout','tls','network','protocol','unknown','http','response-size',
    'response-shape','envelope-json','truncated','response-close'))


def run(environment=None):
    """Return closed observations only; caller owns explicit one-call authorization."""
    started=time.monotonic()
    result={'version':1,'probe':PROBE,'ok':False,'stage':'configuration','diagnostic':'unknown',
        'http_status':None,'transport_calls':0,'response_closed':None,
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
                hint=CP._http400_diagnostic(response) if status==400 else 'http'
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
