"""Bounded, read-only GitHub Actions bytes in RAM; no qualification decisions.

Only this repository, GitHub.com and five fixed endpoint shapes are reachable.
The caller must bind returned metadata/archive/log bytes to its reviewed registry.
No credential lookup, environment-value lookup, disk output or logging occurs.
"""
import json
import math
import os
import re
import selectors
import signal
import subprocess
import time

REPOSITORY = 'metainchelp-boop/logic-analysis'
HOSTNAME = 'github.com'
JSON_MAX = 2 * 1024 * 1024
LOG_MAX = 2 * 1024 * 1024
ZIP_MAX = 4 * 1024 * 1024
HEADER_MAX = 16 * 1024
STDERR_MAX = 64 * 1024
CHUNK_MAX = 64 * 1024
TIMEOUT_SECONDS = 45
TERMINATION_SECONDS = 2
JSON_MAX_DEPTH = 32
JSON_MAX_TOKENS = 32768
ID_MAX = 2**63 - 1
ERRORS = frozenset((
    'INPUT_REFUSED', 'PROCESS_UNAVAILABLE', 'PROCESS_FAILURE', 'PROCESS_TIMEOUT',
    'STDOUT_LIMIT', 'STDERR_LIMIT', 'HTTP_REFUSED', 'HEADER_REFUSED',
    'BODY_REFUSED', 'JSON_REFUSED', 'PAGINATION_REFUSED', 'IDENTITY_REFUSED',
    'COLLECTOR_UNAVAILABLE',
))
_KINDS = frozenset(('run', 'jobs', 'artifacts', 'artifact_zip', 'job_log'))


class CollectorRefused(Exception):
    def __init__(self, code):
        super().__init__(code if type(code) is str and code in ERRORS else 'COLLECTOR_UNAVAILABLE')


def _need(value, code):
    if value is not True:
        raise CollectorRefused(code)


def _identifier(value):
    _need(type(value) is int and 0 < value <= ID_MAX, 'INPUT_REFUSED')
    return str(value)


def _request(kind, identifier):
    """Build fixed argv only. No endpoint, URL, shell or extra option parameter."""
    _need(type(kind) is str and kind in _KINDS, 'INPUT_REFUSED')
    item = _identifier(identifier)
    suffix = {
        'run': 'runs/' + item,
        'jobs': 'runs/' + item + '/jobs?per_page=100&page=1&filter=all',
        'artifacts': 'runs/' + item + '/artifacts?per_page=100&page=1',
        'artifact_zip': 'artifacts/' + item + '/zip',
        'job_log': 'jobs/' + item + '/logs',
    }[kind]
    cap = ZIP_MAX if kind == 'artifact_zip' else LOG_MAX if kind == 'job_log' else JSON_MAX
    argv = ['gh', 'api', '--hostname', HOSTNAME, '--method', 'GET', '--include',
            '-H', 'Accept-Encoding: identity', '-H', 'X-GitHub-Api-Version: 2022-11-28',
            'repos/' + REPOSITORY + '/actions/' + suffix]
    return argv, cap


def _stop(process):
    """Only our new process session; no buffered communicate() or raw error."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        process.wait(timeout=TERMINATION_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _read_process(argv, cap):
    """Bound both pipes while running. gh alone handles existing authentication."""
    process = None
    selector = None
    output = bytearray()
    stderr_size = 0
    finished = False
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
            close_fds=True, start_new_session=True)
        selector = selectors.DefaultSelector()
        for stream, role in ((process.stdout, 'stdout'), (process.stderr, 'stderr')):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, role)
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while selector.get_map():
            remaining = deadline - time.monotonic()
            _need(remaining > 0, 'PROCESS_TIMEOUT')
            for key, _ in selector.select(timeout=min(remaining, 0.25)):
                try:
                    part = os.read(key.fileobj.fileno(), CHUNK_MAX)
                except BlockingIOError:
                    continue
                if not part:
                    selector.unregister(key.fileobj)
                    continue
                if key.data == 'stdout':
                    _need(len(output) + len(part) <= cap + HEADER_MAX, 'STDOUT_LIMIT')
                    output.extend(part)
                else:
                    stderr_size += len(part)
                    _need(stderr_size <= STDERR_MAX, 'STDERR_LIMIT')
                    # Deliberately discard stderr bytes; never decode or retain them.
        remaining = deadline - time.monotonic()
        _need(remaining > 0, 'PROCESS_TIMEOUT')
        try:
            code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            raise CollectorRefused('PROCESS_TIMEOUT') from None
        finished = True
        _need(code == 0, 'PROCESS_FAILURE')
        return bytes(output)
    except CollectorRefused:
        raise
    except OSError:
        raise CollectorRefused('PROCESS_UNAVAILABLE') from None
    except Exception:
        raise CollectorRefused('COLLECTOR_UNAVAILABLE') from None
    finally:
        if process is not None:
            # A child may retain the pipes even if gh has exited. Kill only this session.
            if not finished:
                _stop(process)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        if selector is not None:
            try:
                selector.close()
            except OSError:
                pass


def _body(response, cap):
    """Single final HTTP 200, no pagination, compression or length ambiguity."""
    _need(type(response) is bytes and 0 < len(response) <= cap + HEADER_MAX, 'BODY_REFUSED')
    split = response.find(b'\r\n\r\n')
    separator = b'\r\n'
    delimiter = 4
    if split < 0:
        split = response.find(b'\n\n')
        separator = b'\n'
        delimiter = 2
    _need(0 < split <= HEADER_MAX - delimiter, 'HEADER_REFUSED')
    header, body = response[:split], response[split + delimiter:]
    _need(0 < len(body) <= cap, 'BODY_REFUSED')
    rows = header.split(separator)
    # gh --include may use LF after status and CRLF for all headers.
    if separator == b'\r\n' and b'\n' in rows[0]:
        rows = rows[0].split(b'\n', 1) + rows[1:]
    _need(len(rows) <= 128 and all(0 < len(row) <= 4096 for row in rows), 'HEADER_REFUSED')
    _need(re.fullmatch(rb'HTTP/(?:1\.[01]|2(?:\.0)?|3(?:\.0)?) 200(?: [\x20-\x7e]*)?', rows[0]) is not None, 'HTTP_REFUSED')
    values = {}
    for row in rows[1:]:
        key, sep, value = row.partition(b':')
        _need(sep == b':' and re.fullmatch(rb'[A-Za-z0-9-]+', key) is not None, 'HEADER_REFUSED')
        key = key.lower()
        _need(key not in values and all(32 <= byte <= 126 or byte == 9 for byte in value), 'HEADER_REFUSED')
        values[key] = value.strip()
    _need(b'link' not in values, 'PAGINATION_REFUSED')
    _need(values.get(b'content-encoding', b'identity') == b'identity', 'HEADER_REFUSED')
    _need(b'content-range' not in values and b'transfer-encoding' not in values, 'HEADER_REFUSED')
    if b'content-length' in values:
        value = values[b'content-length']
        _need(re.fullmatch(rb'(?:0|[1-9][0-9]{0,9})', value) is not None, 'HEADER_REFUSED')
        _need(int(value) == len(body), 'BODY_REFUSED')
    return body


def _json_shape(text):
    """Bound nesting and structural tokens before the C JSON parser allocates."""
    depth = 0
    tokens = 0
    quoted = False
    escaped = False
    for ch in text:
        if quoted:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                quoted = False
            continue
        if ch == '"':
            quoted = True
            tokens += 1
        elif ch in '[{':
            depth += 1
            tokens += 1
            _need(depth <= JSON_MAX_DEPTH, 'JSON_REFUSED')
        elif ch in ']}':
            depth -= 1
            _need(depth >= 0, 'JSON_REFUSED')
        elif ch in ',:':
            tokens += 1
        _need(tokens <= JSON_MAX_TOKENS, 'JSON_REFUSED')
    _need(depth == 0 and quoted is False and escaped is False, 'JSON_REFUSED')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, 'JSON_REFUSED')
        result[key] = value
    return result


def _integer(value):
    _need(len(value.lstrip('-')) <= 19, 'JSON_REFUSED')
    number = int(value)
    _need(-ID_MAX <= number <= ID_MAX, 'JSON_REFUSED')
    return number


def _float(value):
    _need(len(value) <= 64, 'JSON_REFUSED')
    number = float(value)
    _need(math.isfinite(number), 'JSON_REFUSED')
    return number


def _constant(_):
    raise CollectorRefused('JSON_REFUSED')


def _json(body):
    try:
        _need(type(body) is bytes and 0 < len(body) <= JSON_MAX, 'JSON_REFUSED')
        text = body.decode('utf-8')
        _json_shape(text)
        value = json.loads(text, object_pairs_hook=_unique, parse_int=_integer,
                           parse_float=_float, parse_constant=_constant)
        _need(type(value) is dict, 'JSON_REFUSED')
        return value
    except CollectorRefused:
        raise
    except Exception:
        raise CollectorRefused('JSON_REFUSED') from None


def _fetch(kind, identifier):
    argv, cap = _request(kind, identifier)
    return _body(_read_process(argv, cap), cap)


def run(run_id):
    """Read one run. Conclusion/branch/workflow/attempt qualification stays upstream."""
    value = _json(_fetch('run', run_id))
    _need(type(value.get('id')) is int and value['id'] == run_id, 'IDENTITY_REFUSED')
    repo = value.get('repository')
    _need(type(repo) is dict and repo.get('full_name') == REPOSITORY, 'IDENTITY_REFUSED')
    return value


def _collection(kind, run_id):
    value = _json(_fetch(kind, run_id))
    _need(set(value) == {'total_count', kind}, 'PAGINATION_REFUSED')
    count, rows = value['total_count'], value[kind]
    _need(type(count) is int and type(rows) is list and 0 <= count <= 100
          and count == len(rows), 'PAGINATION_REFUSED')
    ids = set()
    for item in rows:
        _need(type(item) is dict, 'IDENTITY_REFUSED')
        item_id = item.get('id')
        _identifier(item_id)
        _need(item_id not in ids, 'IDENTITY_REFUSED')
        ids.add(item_id)
        origin = item.get('run_id') if kind == 'jobs' else item.get('workflow_run', {}).get('id') if type(item.get('workflow_run')) is dict else None
        _need(type(origin) is int and origin == run_id, 'IDENTITY_REFUSED')
    return value


def jobs(run_id):
    """One all-attempts page; reject pagination/truncation. Adapter must require attempt1."""
    return _collection('jobs', run_id)


def artifacts(run_id):
    """One complete page with origin IDs; returned archive URLs are never followed."""
    return _collection('artifacts', run_id)


def artifact_zip(artifact_id):
    """RAM ZIP only. Adapter must verify metadata digest/size and bounded exact members."""
    return _fetch('artifact_zip', artifact_id)


def job_log(job_id):
    """RAM log only. Adapter must bind job/attempt and exact reviewed log grammar."""
    return _fetch('job_log', job_id)
