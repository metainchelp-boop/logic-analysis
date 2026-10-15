"""Run the fixed synthetic Claude probe once inside the existing engine.

No production files, configuration, database or credentials are copied or
written. The outer CI job pins this source and requires native CI success.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess

SOURCE = 'b5e40fa01e6432ab0a62541c330652e1cb4fae2c'
CORE_SHA256 = '63608c2ae7f5e14ee9c868ec5d39de44444d42115247aaa578f392efc7b027b7'
PINS_SHA256 = '5b12713b7c4a884db6be79ec4ec0d84c9e5d7489d98359015c1eea3b25e4fb07'
TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'cache_read_input_tokens',
                'cache_creation_input_tokens', 'cache_creation_5m_input_tokens', 'cache_creation_1h_input_tokens')
DIAGNOSTICS = frozenset(('none', 'not-enabled', 'unsupported-policy', 'configuration',
    'timeout', 'tls', 'network', 'protocol', 'unknown', 'http', 'response-size',
    'response-shape', 'envelope-json', 'truncated', 'response-close',
    'http-error-read', 'http-error-body-type', 'http-error-body-size', 'http-error-json',
    'http-error-envelope', 'http-error-type', 'http-error-message', 'http-error-control',
    'http-error-unclassified', 'http-schema-complexity', 'http-spend-limit',
    'http-max-tokens-parameter', 'http-messages-parameter', 'http-system-parameter', 'http-credit-balance', 'http-format-parameter', 'http-model-parameter', 'http-thinking-parameter'))
CONTAINER_FILTERS = ['--filter', 'label=com.docker.compose.project=naver-engine',
                     '--filter', 'label=com.docker.compose.service=naver-engine']
FORMAT = ('{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},'
          '"user":{{json .Config.User}},"started":{{json .State.StartedAt}},'
          '"restarts":{{json .RestartCount}},"readonly":{{json .HostConfig.ReadonlyRootfs}},'
          '"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}')


def command(args, *, data=None):
    result = subprocess.run(args, input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=45, check=False)
    if result.returncode != 0 or len(result.stdout) > 16384:
        raise ValueError('COMMAND_REFUSED')
    return result.stdout


def container(identity):
    return json.loads(command(['docker', 'inspect', '--format', FORMAT, identity]))


def validate_result(value):
    if value in ({'ok': False, 'stage': 'source-check', 'diagnostic': 'source-refused', 'transport_calls': 0},
                 {'ok': False, 'stage': 'probe-execution', 'diagnostic': 'probe-failed-unclassified', 'transport_calls': None}):
        return value
    keys = {'version', 'probe', 'ok', 'stage', 'diagnostic', 'http_status',
            'transport_calls', 'response_closed', 'checks', 'usage', 'elapsed_ms', 'message_terms'}
    if type(value) is not dict or set(value) != keys:
        raise ValueError('RESULT_SHAPE')
    if (type(value['version']) is not int or value['version'] != 1
            or value['probe'] != 'claude-text-pool-schema-v1' or type(value['ok']) is not bool
            or value['stage'] not in ('configuration', 'request', 'transport', 'http',
                'response-read', 'response-json', 'response-shape', 'response-close', 'completed')
            or type(value['diagnostic']) is not str or value['diagnostic'] not in DIAGNOSTICS
            or type(value['transport_calls']) is not int or value['transport_calls'] not in (0, 1)
            or value['response_closed'] is not None and type(value['response_closed']) is not bool):
        raise ValueError('RESULT_ENUM')
    for name, low, high in (('http_status', 100, 599), ('elapsed_ms', 0, 2**53-1)):
        number = value[name]
        if number is not None and (type(number) is not int or not low <= number <= high):
            raise ValueError('RESULT_NUMBER')
    terms = value['message_terms']
    if terms is not None and (type(terms) is not dict
            or set(terms) != set(('schema', 'regex', 'pattern', 'noncapturing', 'group', 'anchor', 'reference', 'unsupported', 'compile', 'complexity'))
            or any(type(v) is not bool for v in terms.values())
            or value['http_status'] != 400):
        raise ValueError('RESULT_MESSAGE_TERMS')
    checks = value['checks']
    if (type(checks) is not dict or set(checks) != {'http_200', 'end_turn', 'text_nonempty', 'exact_ok'}
            or any(v is not None and type(v) is not bool for v in checks.values())):
        raise ValueError('RESULT_CHECKS')
    usage = value['usage']
    if (type(usage) is not dict or set(usage) != {'status', *TOKEN_FIELDS}
            or usage['status'] not in ('unavailable', 'invalid', 'complete', 'partial')
            or any(v is not None and (type(v) is not int or not 0 <= v <= 2**53-1)
                   for k, v in usage.items() if k != 'status')):
        raise ValueError('RESULT_USAGE')
    if value['ok'] and (value['http_status'] != 200 or value['stage'] != 'completed'
            or value['diagnostic'] != 'none' or value['transport_calls'] != 1
            or value['response_closed'] is not True
            or any(checks[k] is not True for k in ('http_200', 'end_turn', 'text_nonempty'))):
        raise ValueError('RESULT_SUCCESS')
    return value


def script(core, pins):
    if not isinstance(core, bytes) or len(core) > 32768:
        raise ValueError('CORE_SIZE')
    if (hashlib.sha256(core).hexdigest() != CORE_SHA256
            or hashlib.sha256(json.dumps(pins, sort_keys=True, separators=(',', ':')).encode()).hexdigest() != PINS_SHA256):
        raise ValueError('SOURCE_CHANGED')
    if (type(pins) is not dict or len(pins) != 109
            or any(not re.fullmatch(r'(?:backend/app|naver_engine|naver_runtime)/[A-Za-z0-9_/.]+\.py', name)
                   or '..' in name.split('/') or not re.fullmatch('[0-9a-f]{64}', digest)
                   for name, digest in pins.items())):
        raise ValueError('SOURCE_PINS')
    encoded = base64.b64encode(core).decode('ascii')
    digest = hashlib.sha256(core).hexdigest()
    return ('''import base64,hashlib,json,os,sys,types
from pathlib import Path
result={'ok':False,'stage':'source-check','diagnostic':'source-refused','transport_calls':0}
try:
    pins=''' + repr(pins) + '''
    root=Path('/opt/naver-engine')
    for name,expected in pins.items():
        path=root/name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('SOURCE_CHANGED')
    if os.environ.get('NAVER_ENGINE_EXECUTION_ENABLED','false')!='false':
        raise ValueError('EXECUTION_ENABLED')
    raw=base64.b64decode(''' + repr(encoded) + ''',validate=True)
    if hashlib.sha256(raw).hexdigest()!=''' + repr(digest) + ''':raise ValueError('CORE_CHANGED')
    sys.path[:0]=[str(root),str(root/'backend')]
    result={'ok':False,'stage':'probe-execution','diagnostic':'probe-failed-unclassified','transport_calls':None}
    probe=types.ModuleType('fixed_claude_minimal_probe')
    exec(compile(raw,'fixed_claude_minimal_probe','exec'),probe.__dict__)
    result=probe.run()
except Exception:
    pass
print(json.dumps(result,sort_keys=True,allow_nan=False))
''').encode('utf-8')


def run(core, pins):
    program = script(core, pins)
    identities = command(['docker', 'ps', '--no-trunc', '--quiet'] + CONTAINER_FILTERS).decode().split()
    if len(identities) != 1 or not re.fullmatch('[0-9a-f]{64}', identities[0]):
        raise ValueError('CONTAINER_IDENTITY')
    identity = identities[0]
    before = container(identity)
    image = json.loads(command(['docker', 'image', 'inspect', '--format',
        '{"id":{{json .Id}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}',
        'metainc/naver-engine:' + SOURCE]))
    if (image.get('source') != SOURCE or not re.fullmatch('sha256:[0-9a-f]{64}', image.get('id', ''))
            or any(before.get(key) != value for key, value in {
                'id': identity, 'image': image['id'], 'running': True,
                'user': '10001:10001', 'readonly': True}.items())):
        raise ValueError('CONTAINER_CHANGED')
    # The image carries the release label; the container need not copy it.
    result = None
    try:
        raw = command(['docker', 'exec', '-i', '--user', '10001:10001', identity,
                       'python', '-I', '-B', '-'], data=program)
        result = json.loads(raw)
    finally:
        if container(identity) != before:
            raise ValueError('CONTAINER_CHANGED_AFTER_PROBE')
    validate_result(result)
    return {'version': 1, 'product_source': SOURCE, 'product_deployed': False,
            'database_opened': False, 'ad_changes': 0, 'container_unchanged': True,
            'result': result}
