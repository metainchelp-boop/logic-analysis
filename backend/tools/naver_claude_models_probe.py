"""Pinned, read-only model entitlement probe. One GET, no messages or DB access."""
import json

CLASSIFICATIONS = frozenset({'models_complete', 'models_partial', 'unauthorized', 'forbidden', 'not_found',
    'rate_limited', 'bad_request', 'server_error', 'http_error', 'timeout', 'tls_error', 'network_error',
    'protocol_error', 'invalid_response', 'response_too_large', 'config_mismatch', 'source_refused'})

PROGRAM = r'''
import http.client,json,os,re,signal,socket,ssl
MODEL='claude-sonnet-5-5'
FALLBACK='claude-sonnet-4-6'
MAXIMUM=262144

def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError()
        result[key]=value
    return result

def project(status,body):
    result={'http_status':status,'configured_model_present':False,'fallback_model_present':False,'classification':'http_error'}
    if type(status) is not int or not 100<=status<=599:
        raise ValueError()
    if status!=200:
        result['classification']={400:'bad_request',401:'unauthorized',403:'forbidden',404:'not_found',429:'rate_limited'}.get(
            status,'server_error' if 500<=status<=599 else 'http_error')
        return result
    if not isinstance(body,bytes) or len(body)>MAXIMUM:
        result['classification']='response_too_large'
        return result
    value=json.loads(body.decode('utf-8'),object_pairs_hook=unique)
    if (not isinstance(value,dict) or not isinstance(value.get('data'),list) or len(value['data'])>1000 or
            type(value.get('has_more')) is not bool or any(not isinstance(row,dict) or
            not isinstance(row.get('id'),str) or not 0<len(row['id'])<=200 for row in value['data'])):
        raise ValueError()
    models={row['id'] for row in value['data']}
    result.update(configured_model_present=MODEL in models,fallback_model_present=FALLBACK in models,
                  classification='models_partial' if value['has_more'] else 'models_complete')
    return result

def probe(environment):
    result={'http_status':None,'configured_model_present':False,'fallback_model_present':False,'classification':'invalid_response'}
    key=environment.get('ANTHROPIC_API_KEY') or environment.get('CLAUDE_API_KEY')
    if (environment.get('NAVER_CLAUDE_ENABLED')!='true' or environment.get('CLAUDE_MODEL')!=MODEL or
            environment.get('NAVER_CLAUDE_MONTHLY_CAP_USD')!='unlimited' or
            not isinstance(key,str) or not re.fullmatch(r'[\x21-\x7e]{1,4096}',key)):
        result['classification']='config_mismatch'
        return result
    connection=None
    def deadline(signum,frame):
        raise TimeoutError()
    old_handler=signal.signal(signal.SIGALRM,deadline)
    signal.alarm(8)
    try:
        connection=http.client.HTTPSConnection('api.anthropic.com',timeout=5)
        connection.request('GET','/v1/models',headers={'x-api-key':key,'anthropic-version':'2023-06-01','Accept':'application/json'})
        response=connection.getresponse()
        status=response.status
        if type(status) is not int or not 100<=status<=599:
            raise ValueError()
        result['http_status']=status
        return project(status,response.read(MAXIMUM+1) if status==200 else b'')
    except (TimeoutError,socket.timeout):
        result['classification']='timeout'
    except ssl.SSLError:
        result['classification']='tls_error'
    except OSError:
        result['classification']='network_error'
    except http.client.HTTPException:
        result['classification']='protocol_error'
    except Exception:
        result['classification']='invalid_response'
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM,old_handler)
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
    return result

if __name__=='__main__':
    print(json.dumps(probe(os.environ),sort_keys=True,separators=(',',':')))
'''


def validate_request(request, controller, now=None):
    if not isinstance(request, dict) or request.get('operation') != 'probe-models':
        raise ValueError('MODEL_PROBE_INPUT')
    controller.validate_request(dict(request, operation='activate'), now=now)
    return request


def public_result(result):
    if (not isinstance(result, dict) or set(result) != {'http_status', 'configured_model_present', 'fallback_model_present', 'classification'} or
            result['http_status'] is not None and (type(result['http_status']) is not int or not 100 <= result['http_status'] <= 599) or
            type(result['configured_model_present']) is not bool or type(result['fallback_model_present']) is not bool or
            not isinstance(result['classification'], str) or result['classification'] not in CLASSIFICATIONS or
            (result['http_status'] != 200 and (result['configured_model_present'] or result['fallback_model_present']))):
        raise ValueError('MODEL_PROBE_RESULT')
    return result


def run(request, host, release, upgrade, lifecycle, controller):
    validate_request(request, controller)
    # These methods verify exact 9ddb/09b receipts, unit bytes and running images.
    # Never call controller.run(), prepare(), key(), or journal/file methods.
    transaction = controller.Transaction(request, host, release, upgrade, lifecycle)
    transaction.legacy()
    active = transaction.manifests()
    before = transaction.running(active['images'])
    identity = before['engine']['id']
    raw = release.command(['docker', 'exec', identity, 'python', '-I', '-S', '-B', '-c', PROGRAM], timeout=15)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 512 or raw.count(b'\n') != 1 or not raw.endswith(b'\n'):
        raise ValueError('MODEL_PROBE_RESULT')
    result = public_result(json.loads(raw, object_pairs_hook=release.unique))
    transaction.legacy()
    if transaction.manifests() != active or transaction.running(active['images']) != before:
        raise ValueError('MODEL_PROBE_SOURCE_CHANGED')
    return result
