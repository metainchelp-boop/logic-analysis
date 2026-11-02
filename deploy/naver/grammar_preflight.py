"""One synthetic grammar request; no source, credential or response disclosure.

The private product fixture builds the format on the CI runner. Only its bounded
JSON package travels to the existing engine. The engine's pinned transport owns
the credential; neither the runner nor this host wrapper receives it.
"""
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

SOURCE = 'c44a66393340314796851f4dd524dad523bd5415'
CANDIDATE = 'plain-prose-v12'
MAX_PACKAGE = 24576
MAX_RESPONSE = 131072
MAX_RESULT = 4096
SHA = re.compile(r'[0-9a-f]{64}\Z')
COMMIT = re.compile(r'[0-9a-f]{40}\Z')
PINS = {
    'naver_engine/__init__.py': '83ca0328fd0eb93b016be936321703ae88df5d3410b369df18c5c7290ed6bf74',
    'naver_engine/ad_reasons.py': '12cb7edc84f8f302036c16677ae51ebbbbc117aa1feba6f58fb32b906501beec',
    'naver_engine/handles.py': 'fa64d8841f352b413ea12fdb8b88ab53c73133eaf0e91a98d8c586a52e8a8e14',
    'naver_engine/inspection_fields.py': '102028ecb4f35647043b5efc1751e516c92f326252b88c3ab6c983ca7c61ba6a',
    'naver_engine/marketing_strategy.py': 'd70068f0f14e2a3e36ae56b0f89a4608f43f6e04ed1247bf4927609b739cf49d',
    'naver_engine/report_enrichment.py': 'b151e866f561b93661ef52a7f7470f04d3f616d00de14b7e81bc2db6f5c0e1d1',
    'naver_engine/reporting.py': '76a7a27ab39f69e9adf4a58547562e00776f6aaa0020df519cb2da8d032bd006',
    'naver_engine/setup_checks.py': '63f6bc01917b7f82d2f10f2466428f52e9034152ce2d4495708c9fd8988cabf5',
    'naver_engine/setup_strategy_evidence.py': '7a1b5cd328fa326f079a75e91e0a0e983ca13cd5bdd69b6c659ddee71116fdd8',
    'naver_engine/shared_budget_evidence.py': '3c4fabb77204f103d6fbe7b98f5d8a7ce937fcf0543b4e266982ce71bb99634e',
    'naver_engine/strategy_validation.py': 'df64567b9bd5810a95e619a2c76038618c9ee306cf956aecc0c63c8f04f4ba22',
    'naver_runtime/__init__.py': '27d28d6ed467edc27f1b22a7a3fedd78253d562938c3cf060ea2573ef38038ec',
    'naver_runtime/claude_provider.py': '4b463645cb304778b2331c3757b83b928d22f27f6e932cf1b23bcfe32367e2cb',
    'naver_runtime/learning_provider.py': 'f50a22c28080dfcadc6b08101a8b8779b59029ff3a6a74060423ba22ae6034be',
    'naver_runtime/provider_observability.py': '9344a464a642cfbea41c7e7a14011a466b1d9ebc495a27c36205bd94e45b21cd',
    'naver_runtime/report_output_schema.py': '3b978c85f92233fb5d4afdfce2c6b761b431db5f6c41de4b1e781829b793ee2a',
}
TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'cache_read_input_tokens',
                'cache_creation_input_tokens', 'cache_creation_5m_input_tokens',
                'cache_creation_1h_input_tokens')
REASONS = frozenset(('none', 'source-refused', 'configuration', 'policy-refused',
    'request-size', 'timeout', 'tls', 'network', 'protocol', 'unknown', 'http',
    'http-schema-complexity', 'http-unsupported-schema', 'http-credit-balance',
    'http-spend-limit', 'http-error-unclassified', 'response-size',
    'response-shape', 'response-json', 'response-schema', 'truncated', 'refusal', 'response-close',
    'host-refused', 'container-changed', 'child-failed'))
CONTAINER_FORMAT = ('{"id":{{json .Id}},"image":{{json .Image}},'
    '"running":{{json .State.Running}},"pid":{{json .State.Pid}},'
    '"started":{{json .State.StartedAt}},"restarts":{{json .RestartCount}},'
    '"user":{{json .Config.User}},"readonly":{{json .HostConfig.ReadonlyRootfs}}}')


def canonical(value):
    # Property order is part of the actual structured-output request contract.
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def schema_matches(value, schema, root=None, depth=0):
    """Conservative validator for this fixture's small supported JSON subset.

    Unknown keywords fail closed. This verifies only the synthetic grammar;
    source-reference/domain validation remains the product's responsibility.
    """
    if type(schema) is not dict or depth > 30:
        return False
    root = schema if root is None else root
    if '$ref' in schema:
        ref = schema['$ref']
        if (set(schema) != {'$ref'} or type(ref) is not str or
                not re.fullmatch(r'#/definitions/[A-Za-z_][A-Za-z_0-9]*', ref)):
            return False
        target = root.get('definitions', {}).get(ref.rsplit('/', 1)[-1])
        return schema_matches(value, target, root, depth + 1)
    allowed = {'type', 'properties', 'required', 'additionalProperties', 'items',
               'minItems', 'enum', 'pattern', 'definitions'}
    if set(schema) - allowed:
        return False
    kind = schema.get('type')
    if kind == 'object':
        props, required = schema.get('properties'), schema.get('required')
        if (type(value) is not dict or type(props) is not dict or
                type(required) is not list or any(type(k) is not str for k in required)
                or schema.get('additionalProperties') is not False
                or set(value) - set(props) or set(required) - set(value)):
            return False
        valid = all(schema_matches(item, props[key], root, depth + 1)
                    for key, item in value.items())
    elif kind == 'array':
        minimum = schema.get('minItems', 0)
        valid = (type(value) is list and type(minimum) is int and minimum >= 0
                 and len(value) >= minimum and all(
                     schema_matches(item, schema.get('items'), root, depth + 1)
                     for item in value))
    elif kind == 'string':
        valid = type(value) is str
        if valid and 'pattern' in schema:
            pattern = schema['pattern']
            valid = type(pattern) is str and re.search(pattern, value) is not None
    elif kind == 'integer':
        valid = type(value) is int
    elif kind == 'number':
        valid = type(value) in (int, float)
    elif kind == 'boolean':
        valid = type(value) is bool
    elif kind == 'null':
        valid = value is None
    else:
        return False
    if valid and 'enum' in schema:
        choices = schema['enum']
        valid = type(choices) is list and any(type(item) is type(value) and item == value for item in choices)
    return valid


def validate_package(value):
    if (type(value) is not dict or set(value) !=
            {'version', 'candidate', 'product_commit', 'format', 'schema_sha256'}
            or type(value['version']) is not int or value['version'] != 1
            or value['candidate'] != CANDIDATE
            or type(value['product_commit']) is not str or not COMMIT.fullmatch(value['product_commit'])
            or type(value['format']) is not dict or set(value['format']) != {'type', 'schema'}
            or value['format']['type'] != 'json_schema'
            or type(value['format']['schema']) is not dict
            or type(value['schema_sha256']) is not str
            or digest(canonical(value['format'])) != value['schema_sha256']
            or len(canonical(value)) > MAX_PACKAGE):
        raise ValueError('PACKAGE_REFUSED')
    return value


def build(product, commit, target):
    """Runner-only: fixed synthetic factory; never execute a network request."""
    if not COMMIT.fullmatch(commit):
        raise ValueError('COMMIT_REFUSED')
    product = Path(product).resolve()
    actual = subprocess.check_output(['git', '-C', str(product), 'rev-parse', 'HEAD'],
                                     stderr=subprocess.DEVNULL).decode().strip()
    dirty = subprocess.check_output(['git', '-C', str(product), 'status', '--porcelain',
                                     '--untracked-files=all'], stderr=subprocess.DEVNULL)
    if actual != commit or dirty.strip():
        raise ValueError('COMMIT_REFUSED')
    import socket
    import sqlite3
    def denied(*args, **kwargs):
        raise ValueError('SIDE_EFFECT_REFUSED')
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    sqlite3.connect = denied
    sys.path[:0] = [str(product), str(product / 'backend')]
    factory = importlib.import_module('naver_runtime.tests.grammar_preflight_fixture')
    fixture = factory.request_format()
    if type(fixture) is not dict or set(fixture) != {'candidate', 'format'}:
        raise ValueError('FACTORY_REFUSED')
    value = validate_package({'version': 1, **fixture, 'product_commit': commit,
                              'schema_sha256': digest(canonical(fixture['format']))})
    raw = canonical(value)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
    return {'product_commit': commit, 'candidate': CANDIDATE,
            'schema_sha256': value['schema_sha256'], 'package_sha256': digest(raw),
            'package_bytes': len(raw)}


def blank_result(package):
    return {'version': 1, 'candidate': CANDIDATE, 'product_commit': package['product_commit'],
        'schema_sha256': package['schema_sha256'], 'live_source': SOURCE,
        'ok': False, 'reason': 'unknown', 'transport_calls': 0,
        'child_execution_attempted': False, 'transport_outcome_unknown': False,
        'http_status': None, 'end_turn': False, 'json_object': False, 'schema_valid': False,
        'response_closed': False, 'request_bytes': 0, 'response_bytes': 0,
        'elapsed_ms': 0, 'database_opened': False, 'product_deployed': False,
        'ad_changes': 0, 'container_unchanged': None,
        'usage': {field: None for field in TOKEN_FIELDS}}


def http_reason(raw):
    """Finite booleans/classification only; remote error text never leaves RAM."""
    try:
        value = json.loads(raw)
        message = value['error']['message']
        if type(message) is not str or len(message) > 4096:
            return 'http-error-unclassified'
        low = message.lower()
        if 'schema' in low and ('complex' in low or 'compilation' in low):
            return 'http-schema-complexity'
        if ('schema' in low or 'pattern' in low) and ('not supported' in low or 'unsupported' in low):
            return 'http-unsupported-schema'
        if message.startswith('Your credit balance is too low to access the Anthropic API.'):
            return 'http-credit-balance'
        if message.startswith(('You have reached your specified API usage limits',
                               'You have reached your specified workspace API usage limits')):
            return 'http-spend-limit'
    except Exception:
        pass
    return 'http-error-unclassified'


def probe(package, provider, cp, lp):
    """One fixed-host transport; no retry, persistence, or response repair."""
    result = blank_result(package)
    started = time.monotonic()
    response = None
    try:
        if provider is None:
            result['reason'] = 'configuration'
            return result
        if provider.monthly_budget_unlimited is not True:
            result['reason'] = 'policy-refused'
            return result
        if (lp.HOST != 'api.anthropic.com' or lp.PATH != '/v1/messages'
                or cp.MAX_OUTPUT_TOKENS != 4096 or cp.MAX_REQUEST_BYTES != 32768
                or cp.MAX_RESPONSE_BYTES != MAX_RESPONSE):
            result['reason'] = 'source-refused'
            return result
        body = {'model': provider.model, 'max_tokens': 4096,
                'messages': [{'role': 'user', 'content':
                    'Return a short Korean JSON object matching the supplied schema. '
                    'Use only synthetic prose; this is a grammar test.'}],
                'output_config': {'format': package['format']}}
        if provider.model == 'claude-sonnet-5-5':
            body['thinking'] = {'type': 'between_tools'}
            body['output_config']['effort'] = 'medium'
        data = canonical(body)
        result['request_bytes'] = len(data)
        if len(data) > 32768:
            result['reason'] = 'request-size'
            return result
        request = cp.ProviderRequest(data=data, headers={'x-api-key': provider._api_key,
            'anthropic-version': '2023-06-01', 'Content-Type': 'application/json'})
        result['transport_calls'] = 1
        # This factory-installed transport preserves production's 60-second
        # common response deadline and its configured 1..20-second connect time.
        response = provider._transport(request, timeout=provider._timeout)
        if type(response.status) is not int or not 100 <= response.status <= 599:
            result['reason'] = 'response-shape'
            return result
        result['http_status'] = response.status
        limit = MAX_RESPONSE if response.status == 200 else 4096
        raw = response.read(limit + 1)
        if type(raw) is not bytes or len(raw) > limit:
            result['reason'] = 'response-size'
            return result
        result['response_bytes'] = len(raw)
        if response.status != 200:
            result['reason'] = http_reason(raw) if response.status == 400 else 'http'
            return result
        try:
            envelope = json.loads(raw)
            if type(envelope) is not dict:
                raise ValueError()
            stop = envelope.get('stop_reason')
            result['end_turn'] = stop == 'end_turn'
            if stop != 'end_turn':
                result['reason'] = 'truncated' if stop == 'max_tokens' else 'refusal' if stop == 'refusal' else 'response-shape'
                return result
            usage = envelope.get('usage')
            if type(usage) is dict:
                for field in TOKEN_FIELDS:
                    number = usage.get(field)
                    if type(number) is int and 0 <= number <= 2**53 - 1:
                        result['usage'][field] = number
            text = cp._response_text(envelope.get('content'))
            value = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            result['json_object'] = type(value) is dict
            if result['json_object']:
                result['schema_valid'] = schema_matches(value, package['format']['schema'])
        except Exception:
            result['reason'] = 'response-json'
            return result
        result['ok'] = result['json_object'] and result['schema_valid']
        result['reason'] = ('none' if result['ok'] else
                            'response-schema' if result['json_object'] else 'response-shape')
        return result
    except Exception as error:
        code = error.code if isinstance(error, lp.StrategyRefused) else lp._transport_error(error)
        result['reason'] = {'PROVIDER_TIMEOUT': 'timeout', 'PROVIDER_TLS_ERROR': 'tls',
            'PROVIDER_NETWORK_ERROR': 'network', 'PROVIDER_PROTOCOL_ERROR': 'protocol'}.get(code, 'unknown')
        return result
    finally:
        if response is not None:
            try:
                response.close()
                result['response_closed'] = True
            except Exception:
                result.update(ok=False, reason='response-close')
        result['elapsed_ms'] = max(0, int((time.monotonic() - started) * 1000))


def inside(package):
    """Runs only within the existing engine. Never exports its environment."""
    validate_package(package)
    result = blank_result(package)
    result['reason'] = 'source-refused'
    root = Path('/opt/naver-engine')
    try:
        if os.geteuid() != 10001 or os.environ.get('NAVER_ENGINE_EXECUTION_ENABLED', 'false') != 'false':
            return result
        for name, expected in PINS.items():
            path = root / name
            if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != expected:
                return result
        import sqlite3
        def denied(*args, **kwargs):
            raise ValueError('DATABASE_FORBIDDEN')
        sqlite3.connect = denied
        sys.path[:0] = [str(root), str(root / 'backend')]
        from naver_runtime import learning_provider as lp, claude_provider as cp
        # The pinned import closure must not acquire additional product modules.
        actual = {str(Path(module.__file__).relative_to(root))
                  for name, module in sys.modules.items()
                  if name.startswith(('naver_engine', 'naver_runtime'))
                  and getattr(module, '__file__', None)}
        if actual != set(PINS):
            return result
        return probe(package, lp.provider_from_environment(), cp, lp)
    except Exception:
        return result


def validate_result(value, package):
    expected = blank_result(package)
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError('RESULT_SHAPE')
    for key in ('version', 'candidate', 'product_commit', 'schema_sha256', 'live_source',
                'database_opened', 'product_deployed', 'ad_changes'):
        if type(value[key]) is not type(expected[key]) or value[key] != expected[key]:
            raise ValueError('RESULT_FIXED')
    if type(value['reason']) is not str or value['reason'] not in REASONS:
        raise ValueError('RESULT_REASON')
    for key in ('ok', 'end_turn', 'json_object', 'schema_valid', 'response_closed',
                'child_execution_attempted', 'transport_outcome_unknown'):
        if type(value[key]) is not bool:
            raise ValueError('RESULT_BOOLEAN')
    if value['container_unchanged'] is not None and type(value['container_unchanged']) is not bool:
        raise ValueError('RESULT_CONTAINER')
    if value['transport_outcome_unknown']:
        if (not value['child_execution_attempted'] or value['transport_calls'] is not None
                or value['ok']):
            raise ValueError('RESULT_UNKNOWN_OUTCOME')
    elif type(value['transport_calls']) is not int or not 0 <= value['transport_calls'] <= 1:
        raise ValueError('RESULT_CALLS')
    for key, maximum in (('request_bytes', 32768),
                         ('response_bytes', MAX_RESPONSE), ('elapsed_ms', 210000)):
        if type(value[key]) is not int or not 0 <= value[key] <= maximum:
            raise ValueError('RESULT_NUMBER')
    if value['http_status'] is not None and (type(value['http_status']) is not int or not 100 <= value['http_status'] <= 599):
        raise ValueError('RESULT_HTTP')
    if type(value['usage']) is not dict or set(value['usage']) != set(TOKEN_FIELDS):
        raise ValueError('RESULT_USAGE')
    if any(number is not None and (type(number) is not int or not 0 <= number <= 2**53 - 1)
           for number in value['usage'].values()):
        raise ValueError('RESULT_USAGE')
    if value['ok'] and (value['reason'] != 'none' or value['transport_calls'] != 1
            or value['http_status'] != 200 or not value['end_turn']
            or not value['json_object'] or not value['schema_valid'] or not value['response_closed']):
        raise ValueError('RESULT_SUCCESS')
    if len(canonical(value)) > MAX_RESULT:
        raise ValueError('RESULT_SIZE')
    return value


def command(args, *, data=None, timeout=30):
    done = subprocess.run(args, input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          check=False, timeout=timeout, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
    if done.returncode != 0 or len(done.stdout) > 16384:
        raise ValueError('COMMAND_REFUSED')
    return done.stdout


def snapshot(identity):
    return json.loads(command(['docker', 'inspect', '--format', CONTAINER_FORMAT, identity]))


def host(package, source=None):
    validate_package(package)
    result = blank_result(package)
    result['reason'] = 'host-refused'
    identity = None
    before = None
    child_attempted = False
    try:
        if os.geteuid() != 0:
            return result
        ids = command(['docker', 'ps', '--no-trunc', '--quiet', '--filter',
            'label=com.docker.compose.project=naver-engine', '--filter',
            'label=com.docker.compose.service=naver-engine']).decode().split()
        if len(ids) != 1 or not SHA.fullmatch(ids[0]):
            return result
        identity = ids[0]
        before = snapshot(identity)
        image = json.loads(command(['docker', 'image', 'inspect', '--format',
            '{"id":{{json .Id}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}',
            'metainc/naver-engine:' + SOURCE]))
        if (image.get('source') != SOURCE or not re.fullmatch(r'sha256:[0-9a-f]{64}', image.get('id', ''))
                or any(before.get(k) != v for k, v in {'id': identity, 'image': image['id'],
                    'running': True, 'user': '10001:10001', 'readonly': True}.items())
                or type(before.get('pid')) is not int or before['pid'] <= 0):
            return result
        raw = Path(__file__).read_bytes() if source is None else source
        program = ("import base64,json\nns={'__name__':'fixed_grammar_preflight'}\n"
            "exec(compile(base64.b64decode(" + repr(base64.b64encode(raw).decode()) + "),'<fixed-preflight>','exec'),ns)\n"
            "value=ns['inside'](json.loads(base64.b64decode(" + repr(base64.b64encode(canonical(package)).decode()) + ")))\n"
            "ns['validate_result'](value,json.loads(base64.b64decode(" + repr(base64.b64encode(canonical(package)).decode()) + ")))\n"
            "print(json.dumps(value,sort_keys=True,allow_nan=False))\n").encode()
        if len(program) > 100000:
            return result
        child_attempted = True
        child = command(['docker', 'exec', '-i', '--user', '10001:10001', identity,
                         'python', '-I', '-B', '-'], data=program, timeout=210)
        result = validate_result(json.loads(child), package)
    except Exception:
        result.update(ok=False, reason='child-failed')
        if child_attempted:
            # Docker exec may have started a billed request even if its result
            # was lost. A missing receipt must never be reported as zero calls.
            result.update(transport_calls=None, transport_outcome_unknown=True)
    finally:
        result['child_execution_attempted'] = child_attempted
        if identity is not None and before is not None:
            try:
                result['container_unchanged'] = snapshot(identity) == before
            except Exception:
                result['container_unchanged'] = False
            if result['container_unchanged'] is not True:
                result.update(ok=False, reason='container-changed')
    return validate_result(result, package)


def safe_read(path, expected):
    if not SHA.fullmatch(expected):
        raise ValueError('PACKAGE_HASH')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
            raise ValueError('PACKAGE_MODE')
        raw = stream.read(MAX_PACKAGE + 1)
    if len(raw) > MAX_PACKAGE or digest(raw) != expected:
        raise ValueError('PACKAGE_HASH')
    return validate_package(json.loads(raw))


def main():
    try:
        if len(sys.argv) == 5 and sys.argv[1] == 'build':
            print('NAVER_GRAMMAR_PACKAGE=' + json.dumps(build(*sys.argv[2:]), sort_keys=True))
            return 0
        if len(sys.argv) == 4 and sys.argv[1] == 'host':
            value = host(safe_read(sys.argv[2], sys.argv[3]))
            print('NAVER_GRAMMAR_PREFLIGHT=' + canonical(value).decode())
            return 0 if value['ok'] else 1
    except Exception:
        pass
    print('NAVER_GRAMMAR_PREFLIGHT_ERROR=REFUSED')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
