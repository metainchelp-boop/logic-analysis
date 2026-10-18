"""Pure fixed-source registration and single-result receiver.

Inputs are public source bytes and closed metadata from a separately verified
workflow reader. This module neither obtains nor authenticates remote metadata.
Expected future run IDs alone are insufficient: matching completed successful
native and dispatch metadata and the fixed-input receipt are all required.
No file, environment, subprocess, network, database or service access occurs.
"""
import hashlib
import json
import re
import delivery as D

DELIVERY_PIN = '93f7b0fedd713e5be03a2df2501bc57e825ef41564accf9bc5ea6d4590c30504'
RENDERER_PIN = 'c7031553808146394ccc899a67e8ef76fbae7946ff4a389f874d0c041feb098c'
MARKER = b'NAVER_MARKET_DIAGNOSTIC_TRANSITION_V1='
TRANSPORT = 'market-diagnostic-transition'
REPOSITORY = 'metainchelp-boop/logic-analysis'
MAX_RESULT, MAX_RECEIPT = 4096, 8192
NATIVE_EVENTS = frozenset(('push', 'workflow_dispatch'))
EXPECTED_KEYS = frozenset(('repository', 'ops_head', 'native_run_id', 'native_attempt',
    'native_workflow_id', 'native_workflow_path', 'native_event', 'workflow_run_id',
    'workflow_attempt', 'workflow_id', 'workflow_path'))
FIXED_INPUT_KEYS = EXPECTED_KEYS - {'workflow_run_id', 'workflow_attempt'}
RUN_KEYS = frozenset(('repository', 'id', 'run_attempt', 'head_sha', 'workflow_id',
    'path', 'event', 'status', 'conclusion'))
COMMON_ERRORS = frozenset(('HOST_REFUSED', 'HOST_OS_ERROR', 'INTERRUPTED'))
DECODE_ERRORS = COMMON_ERRORS | frozenset(('WIRE_SIZE', 'PACKAGE_SIZE', 'PACKAGE_JSON',
    'PACKAGE_SHAPE', 'HOST_CHANGED'))
LOAD_ERRORS = COMMON_ERRORS | frozenset(('PACKAGE_SHAPE', 'PACKAGE_SIZE', 'PACKAGE_JSON',
    'REQUEST', 'SOURCE_SHAPE', 'SOURCE_CHANGED'))
DELIVERY_ERRORS = frozenset(('WIRE_SIZE', 'PACKAGE_SIZE', 'PACKAGE_JSON', 'PACKAGE_SHAPE',
    'HOST_CHANGED', 'SOURCE_SHAPE', 'SOURCE_CHANGED', 'REQUEST', 'MODULE_COLLISION',
    'RESULT', 'RESULT_SIZE'))
# Fixed literal refusal set from the exact nine reviewed modules. The source
# registration verifies this set again; future source changes require review.
MODULE_REFUSALS = frozenset('''ALREADY_ATTEMPTED ALREADY_RESTORED CURRENT_ALREADY_BOUND
CURRENT_CHANGED CURRENT_COMMAND CURRENT_CONTAINER CURRENT_FAILURE_CHANGED
CURRENT_FAILURE_RESULT CURRENT_FAILURE_UNIT CURRENT_IMAGE CURRENT_PREPARED
CURRENT_PREVIOUS CURRENT_PROOF CURRENT_STARTED DERIVATION DIAGNOSTIC_ALREADY_RAN
DIAGNOSTIC_CONTEXT DIAGNOSTIC_CONTEXT_CHANGED DIAGNOSTIC_NOT_IDLE
DIAGNOSTIC_START_REPLAY ENTRYPOINT_HOST ENTRYPOINT_REQUEST EVENT HISTORY HOST_ACTION
HOST_ACTION_INTENT_REQUIRED HOST_BASELINE_CHANGED HOST_COMPONENT_BINDING
HOST_CURRENT_GUARD HOST_CURRENT_GUARD_REQUIRED HOST_OUTPUT HOST_OUTPUT_NOT_EMPTY
HOST_OUTPUT_PROOF HOST_PLAN HOST_PUBLIC_STATE HOST_RESTORE_UNVERIFIED JOURNAL_BINDING
JOURNAL_BUSY JOURNAL_CHAIN JOURNAL_CHANGED JOURNAL_DIRECTORY JOURNAL_EVENT JOURNAL_FILE
JOURNAL_INITIAL_INCOMPLETE JOURNAL_INVENTORY JOURNAL_INVOCATION JOURNAL_JSON
JOURNAL_LIMIT JOURNAL_LINK JOURNAL_LOCK JOURNAL_LOCK_REQUIRED JOURNAL_MESSAGE
JOURNAL_MULTIPLE_RESULTS JOURNAL_OPERATION_RESERVED JOURNAL_PATH JOURNAL_RESULT
JOURNAL_SEQUENCE JOURNAL_SIZE JOURNAL_WRITE OBSERVATION OPERATION
ORIGINAL_NOT_MASKED_IDLE ORIGINAL_TIMER ORIGINAL_TIMER_NOT_IDLE
ORIGINAL_TIMER_NOT_RESTORED ORIGINAL_UNIT OWNED_CHANGED OWNED_CROSS_FILESYSTEM
OWNED_DIRECTORY OWNED_FILE OWNED_GROUP OWNED_INVENTORY OWNED_KIND OWNED_LINK
OWNED_MASK_CHANGED OWNED_PARENT_CHANGED OWNED_PREPARATION_EXISTS OWNED_RECORD
OWNED_RECORD_LIMIT OWNED_RECORD_LINK OWNED_STAGE OWNED_STAGE_CHANGED
OWNED_STAGE_DIRECTORY_CHANGED OWNED_TARGET_CHANGED OWNED_TARGET_EXISTS OWNED_WRITE
PAIR PIN PLAN PORT_RESULT PREFLIGHT_CHANGED PREFLIGHT_COMMAND_FORBIDDEN
PREFLIGHT_DIRECTORY PREFLIGHT_FILE PREFLIGHT_IDENTITY PREFLIGHT_INSTALLED
PREFLIGHT_OPERATING_RECEIPT PREFLIGHT_PATH PREFLIGHT_PLAN PREFLIGHT_PREPARED
PREFLIGHT_PROOFS PREFLIGHT_RECEIPT PREFLIGHT_SOURCE PROOF PROVISION_CHANGED
PROVISION_DIRECTORY PROVISION_EXISTS PROVISION_GUARD PROVISION_INVENTORY
PROVISION_PATH PROVISION_PLAN PROVISION_RECEIPT PROVISION_RECEIPT_LIMIT
PROVISION_RECEIPT_LINK PROVISION_ROOT PROVISION_RUNTIME PROVISION_WRITE SOURCES
SYSTEMD_COMMAND SYSTEMD_COMMAND_AMBIGUOUS SYSTEMD_COMMAND_FAILED
SYSTEMD_COMMAND_LIMIT SYSTEMD_COMMAND_UNAVAILABLE SYSTEMD_JSON SYSTEMD_SNAPSHOT
SYSTEMD_UNIT SYSTEMD_UNIT_PATH'''.split())


class Invalid(ValueError):
    pass


def fail(code):
    raise Invalid(code)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          allow_nan=False).encode()
    except (ValueError, TypeError, UnicodeError, RecursionError):
        fail('RECEIVER_SHAPE')


def same(actual, expected):
    return canonical(actual) == canonical(expected)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def _request(value):
    try:
        return D.request(value)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        fail('RECEIVER_REQUEST')


def _registration():
    return dict(version=1, transport=TRANSPORT, delivery_sha256=DELIVERY_PIN,
        renderer_sha256=RENDERER_PIN, modules=dict(D.MODULE_PINS),
        sources=dict(D.SOURCE_PINS), refusal_codes_sha256=sha(canonical(sorted(MODULE_REFUSALS))))


def register_release(*, delivery_source, renderer_source, modules, sources):
    """Validate public bytes; return only exact hashes and a closed registry.

    This registration must run before rendering or dispatch. It does not itself
    cause rendering, execution, or a native qualification run.
    """
    for body, pin, maximum in ((delivery_source, DELIVERY_PIN, D.MAX_HOST),
                              (renderer_source, RENDERER_PIN, D.MAX_BOOT)):
        if type(body) is not bytes or not 0 < len(body) <= maximum or sha(body) != pin:
            fail('REGISTRATION_SOURCE')
    for values, pins, maximum in ((modules, D.MODULE_PINS, D.MAX_MODULE),
                                 (sources, D.SOURCE_PINS, D.MAX_SOURCE)):
        if type(values) is not dict or set(values) != set(pins): fail('REGISTRATION_SHAPE')
        for role, pin in pins.items():
            body = values[role]
            if type(body) is not bytes or not 0 < len(body) <= maximum or sha(body) != pin:
                fail('REGISTRATION_SOURCE')
    codes = {code for body in modules.values()
             for code in re.findall(r"fail\('([A-Z][A-Z0-9_]{0,63})'\)", body.decode())}
    if codes != MODULE_REFUSALS: fail('REGISTRATION_REFUSALS')
    return _registration()


def _registered(value):
    if type(value) is not dict or not same(value, _registration()):
        fail('REGISTRATION_CHANGED')
    return json.loads(canonical(value))


def _positive(value):
    return type(value) is int and 0 < value < 2**63


def _path(value):
    return type(value) is str and re.fullmatch(
        r'\.github/workflows/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\.ya?ml', value) is not None


def _expected(value, *, dispatch=True):
    if type(value) is not dict or set(value) != (EXPECTED_KEYS if dispatch else FIXED_INPUT_KEYS):
        fail('EXECUTION_EXPECTED')
    if (value['repository'] != REPOSITORY or type(value['repository']) is not str
            or type(value['ops_head']) is not str
            or re.fullmatch('[0-9a-f]{40}', value['ops_head']) is None
            or value['ops_head'] == '0' * 40
            or type(value['native_event']) is not str or value['native_event'] not in NATIVE_EVENTS
            or not _path(value['native_workflow_path']) or not _path(value['workflow_path'])):
        fail('EXECUTION_EXPECTED')
    numeric = ('native_run_id', 'native_attempt', 'native_workflow_id', 'workflow_id')
    for key in numeric + (('workflow_run_id', 'workflow_attempt') if dispatch else ()):
        if not _positive(value[key]): fail('EXECUTION_EXPECTED')
    if dispatch and (value['workflow_attempt'] != 1 or value['native_run_id'] == value['workflow_run_id']):
        fail('EXECUTION_EXPECTED')
    return json.loads(canonical(value))


def fixed_input_receipt(*, registration, expected_request, expected):
    """Build the pre-dispatch receipt. No eventual dispatch run is claimed here."""
    release = _registered(registration)
    req = _request(expected_request)
    # Before dispatch the run ID does not exist. Full expected metadata is also
    # accepted after dispatch, but these two fields never enter fixed input.
    if type(expected) is dict and set(expected) == EXPECTED_KEYS:
        exp = _expected(expected)
        inputs = {k:v for k,v in exp.items() if k in FIXED_INPUT_KEYS}
    else:
        inputs = _expected(expected, dispatch=False)
    return dict(version=1, stage='fixed_input_only', inputs=inputs,
                request_sha256=sha(canonical(req)), release_sha256=sha(canonical(release)))


def bind_execution(*, registration, expected_request, expected, input_receipt,
                   observed_native, observed_workflow):
    """Match selected completed-run metadata, never infer completion from IDs.

    The caller must obtain these selected fields from its verified fixed workflow
    reader. A supplied metadata dictionary is not independent proof of its truth.
    """
    exp = _expected(expected)
    wanted_input = fixed_input_receipt(registration=registration,
        expected_request=expected_request, expected=exp)
    if type(input_receipt) is not dict or not same(input_receipt, wanted_input):
        fail('EXECUTION_INPUT')
    for native, observed in ((True, observed_native), (False, observed_workflow)):
        if type(observed) is not dict or set(observed) != RUN_KEYS: fail('EXECUTION_METADATA')
        prefix = 'native_' if native else 'workflow_'
        wanted = dict(repository=exp['repository'], id=exp[prefix+'run_id'],
            run_attempt=exp[prefix+'attempt'], head_sha=exp['ops_head'],
            workflow_id=exp['native_workflow_id'] if native else exp['workflow_id'],
            path=exp['native_workflow_path'] if native else exp['workflow_path'],
            event=exp['native_event'] if native else 'workflow_dispatch',
            status='completed', conclusion='success')
        if not same(observed, wanted): fail('EXECUTION_METADATA')
    return dict(version=1, stage='matched_supplied_completed_metadata', expected=exp,
                input_receipt_sha256=sha(canonical(input_receipt)),
                native_metadata_sha256=sha(canonical(observed_native)),
                workflow_metadata_sha256=sha(canonical(observed_workflow)))


def _parse(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= len(MARKER) + MAX_RESULT + 1:
        fail('RECEIVER_SIZE')
    line = raw[:-1] if raw.endswith(b'\n') else raw
    if b'\n' in line or b'\r' in line or not line.startswith(MARKER): fail('RECEIVER_LINE')
    body = line[len(MARKER):]
    if not 0 < len(body) <= MAX_RESULT: fail('RECEIVER_SIZE')
    try:
        result = D.strict(body)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        fail('RECEIVER_JSON')
    if canonical(result) != body: fail('RECEIVER_CANONICAL')
    return result


def receive(raw, *, registration, expected_request, expected, input_receipt,
            observed_native, observed_workflow):
    """Return a closed receipt only. Raw output and exception text are not retained."""
    req, release = _request(expected_request), _registered(registration)
    binding = bind_execution(registration=release, expected_request=req, expected=expected,
        input_receipt=input_receipt, observed_native=observed_native, observed_workflow=observed_workflow)
    value = _parse(raw)
    keys = {'version', 'transport', 'transport_ok', 'phase', 'error_code', 'result',
            'paired_cleanup_may_be_required'}
    if (type(value) is not dict or set(value) != keys or type(value['version']) is not int
            or value['version'] != 1 or type(value['transport']) is not str
            or value['transport'] != TRANSPORT or type(value['transport_ok']) is not bool
            or type(value['paired_cleanup_may_be_required']) is not bool
            or type(value['phase']) is not str): fail('RECEIVER_RESULT')
    if value['transport_ok']:
        if (value['phase'] != 'complete' or value['error_code'] is not None
                or value['paired_cleanup_may_be_required'] is not (req['action'] == 'apply')):
            fail('RECEIVER_RESULT')
        try:
            public = D.closed_result(value['result'], req)
        except (ValueError, TypeError, UnicodeError, RecursionError, KeyError):
            fail('RECEIVER_RESULT')
        status = public['result']['observation']['status'] if req['action'] == 'apply' else 'diagnostic_restored'
        issue = public['result']['observation']['limit_issue'] if req['action'] == 'apply' else None
        pair_provenance = 'result_and_fixed_input_receipt'
    else:
        allowed = {'decode': DECODE_ERRORS, 'load': LOAD_ERRORS,
                   'entrypoint': COMMON_ERRORS | DELIVERY_ERRORS | MODULE_REFUSALS}
        if (value['phase'] not in allowed or type(value['error_code']) is not str
                or value['error_code'] not in allowed[value['phase']] or value['result'] is not None
                or value['paired_cleanup_may_be_required'] is not True): fail('RECEIVER_RESULT')
        public, status, issue, pair_provenance = None, 'transport_refused', None, 'fixed_input_receipt_only'
    receipt = dict(version=1, transport=TRANSPORT, request=req,
        release_sha256=sha(canonical(release)), binding=binding,
        transport_ok=value['transport_ok'], phase=value['phase'], error_code=value['error_code'],
        paired_cleanup_may_be_required=value['paired_cleanup_may_be_required'],
        pair_provenance=pair_provenance, diagnostic_status=status, limit_issue=issue,
        public_result=public, original_export_success_verified=False,
        product_deployed=False, ads_written=False)
    if len(canonical(receipt)) > MAX_RECEIPT: fail('RECEIVER_RECEIPT_SIZE')
    return json.loads(canonical(receipt))
