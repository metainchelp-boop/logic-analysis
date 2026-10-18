"""Isolated diagnostic transaction compiler and one-attempt controller.

This module deliberately has no shell, filesystem, systemd or database adapter.
The port contract is a release gate: a caller cannot claim host qualification
from these deterministic transaction tests. Historical installation files,
receipts and product prepare checks are never patched by this compiler.
"""
import hashlib
import json
import re
import types

HELPER_PIN = '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737'
PRODUCT_PIN = '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59'
OLD_MARKET_PIN = 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8'
MARKET_PIN = '9bb25d4acda4edca44aa71c238a6bf53be7dab5e093bc4f0c69d45c0d0891851'
OPERATING_SOURCE = '21cd739cf171c066b84683b24e3340feda495858'
OPERATING_OPERATION = 'b934741699a949a0856ad4114d7bc11a'
PROFILE = dict(ops_commit='19586caf7fe5579e7da70d4a2d4205c3ed603996',
               source_directory='/root/logic-analysis-deploy/data',
               database_name='logic_data.db', exporter_user='nobody',
               source_group=None, python_executable='/usr/bin/python3')
OLD_COORDINATOR = 'naver-market-export.service'
OLD_READER = 'naver-market-export-reader.service'
OLD_TIMER = 'naver-market-export.timer'
INSTALL = '/opt/metainc/naver-market-diagnostic'
OUTPUT = '/var/lib/metainc/naver-market-diagnostic'
UNIT_ROOT = '/etc/systemd/system'
ISSUES = frozenset(('input_bytes', 'rows', 'time', 'cell', 'clients', 'unknown'))
PROOF_KEYS = frozenset(('operating_receipt_sha256', 'exports_receipt_sha256',
    'prepared_receipt_sha256', 'installed_receipt_sha256',
    'original_manifest_sha256', 'source_identity_sha256',
    'runtime_identity_sha256', 'interpreter_identity_sha256'))
STEPS = ('timer_stop', 'mask_original', 'quiescence_verify',
         'install_new', 'unit_verify', 'daemon_reload', 'installed_verify',
         'run_once', 'observe')
CLEANUP = ('new_units_idle', 'remove_new', 'reload_removed',
           'unmask_owned', 'reload_unmasked', 'timer_restore', 'restored_verify')


class Invalid(ValueError):
    pass


def fail(code):
    raise Invalid(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode()


def sha(body):
    return hashlib.sha256(body).hexdigest()


def same(actual, expected):
    """JSON equality must not alias bool/int/float or tuple/list identities."""
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return (all(type(k) is str for k in actual) and set(actual) == set(expected)
                and all(same(actual[k], expected[k]) for k in expected))
    if type(expected) is list:
        return len(actual) == len(expected) and all(same(a, b) for a, b in zip(actual, expected))
    return actual == expected


def operation(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{32}', value) is None or value == '0' * 32:
        fail('OPERATION')
    return value


def digest(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        fail('PIN')
    return value


def exact_replace(body, before, after, count=1):
    if body.count(before) != count or after in body:
        fail('DERIVATION')
    result = body.replace(before, after)
    if result.replace(after, before) != body:
        fail('DERIVATION')
    return result


def compile_plan(*, apply_id, rollback_id, sources, previous):
    """Compile only pinned bytes and closed hashes, without any host access.

    previous hashes must later be re-established by the host port from the
    exact original receipts, current operating receipt and installed files.
    Supplying hashes here is not evidence that a production preflight ran.
    """
    operation(apply_id); operation(rollback_id)
    if apply_id == rollback_id:
        fail('PAIR')
    pins = dict(helper=HELPER_PIN, product=PRODUCT_PIN,
                old_market=OLD_MARKET_PIN, market=MARKET_PIN)
    if type(sources) is not dict or set(sources) != set(pins):
        fail('SOURCES')
    for key, pin in pins.items():
        body = sources[key]
        if type(body) is not bytes or not 0 < len(body) <= 262144 or sha(body) != pin:
            fail('SOURCES')
    if type(previous) is not dict or set(previous) != PROOF_KEYS:
        fail('PROOF')
    for value in previous.values():
        digest(value)
    helper = types.ModuleType('exact_saved_export_helper')
    exec(compile(sources['helper'], '<exact-saved-export-helper>', 'exec'), helper.__dict__)
    profile = helper.build_plan(**PROFILE)
    original = helper.artifacts(profile, {
            'naver_product_export.py': sources['product'],
            'naver_market_export.py': sources['old_market']}, {
            'naver_product_export.py': PRODUCT_PIN,
            'naver_market_export.py': OLD_MARKET_PIN})
    code_root = INSTALL + '/' + apply_id
    output_root = OUTPUT + '/' + apply_id
    coordinator = 'naver-market-diagnostic-' + apply_id + '.service'
    reader = 'naver-market-diagnostic-' + apply_id + '-reader.service'
    old_root = str(helper.INSTALL / profile['ops_commit'])
    old_output = str(helper.OUTPUTS['market'])
    coord_code = exact_replace(original['naver_market_coordinate.py'],
                              OLD_READER.encode(), reader.encode(), 2)
    coord_unit = original[OLD_COORDINATOR]
    coord_unit = exact_replace(coord_unit,
        (old_root + '/naver_market_coordinate.py').encode(),
        (code_root + '/naver_market_coordinate.py').encode())
    coord_unit = exact_replace(coord_unit,
        ('ReadOnlyPaths=' + helper.SOURCE_ALIAS + '/logic_data.db ' + old_root + '\n').encode(),
        ('ReadOnlyPaths=' + helper.SOURCE_ALIAS + '/logic_data.db ' + old_root + ' ' + code_root + '\n').encode())
    reader_unit = exact_replace(original[OLD_READER], OLD_COORDINATOR.encode(), coordinator.encode())
    reader_unit = exact_replace(reader_unit,
        (old_root + '/naver_market_export.py').encode(),
        (code_root + '/naver_market_export.py').encode())
    reader_unit = exact_replace(reader_unit,
        ('ReadOnlyPaths=' + old_root + '\n').encode(),
        ('ReadOnlyPaths=' + old_root + ' ' + code_root + '\n').encode())
    reader_unit = exact_replace(reader_unit, old_output.encode(), output_root.encode(), 2)
    files = {
        code_root + '/naver_market_export.py': sources['market'],
        code_root + '/naver_product_export.py': sources['product'],
        code_root + '/naver_market_coordinate.py': coord_code,
        UNIT_ROOT + '/' + coordinator: coord_unit,
        UNIT_ROOT + '/' + reader: reader_unit,
    }
    plan = dict(version=1, apply_id=apply_id, rollback_id=rollback_id,
        operating_source=OPERATING_SOURCE, operating_operation=OPERATING_OPERATION,
        previous=dict(previous), source_pins=pins, code_root=code_root,
        output_root=output_root, coordinator=coordinator, reader=reader,
        original_units=[OLD_COORDINATOR, OLD_READER], timer=OLD_TIMER,
        interpreter=old_root + '/python-export',
        manifest={path: sha(body) for path, body in sorted(files.items())},
        original_market_bundle_preserved=True,
        historical_receipts_preserved=True, product_prepare_unchanged=True,
        source_coordination_files_may_change=True, database_content_writes=False,
        controller_start_attempts_max=1, natural_timer_catchup_possible=True,
        original_timer_required=dict(enabled=True, active=True, masked=False),
        new_files_mode=0o644, new_code_directory_mode=0o755,
        new_output_mode=0o750, reader_gid=10001,
        requires_real_host_adapter=True)
    return plan, files


def validate_plan(plan, files, *, sources):
    if type(plan) is not dict:
        fail('PLAN')
    try:
        expected, expected_files = compile_plan(apply_id=plan['apply_id'],
            rollback_id=plan['rollback_id'], sources=sources, previous=plan['previous'])
    except (KeyError, TypeError):
        fail('PLAN')
    if not same(plan, expected) or not same(files, expected_files):
        fail('PLAN')
    return sha(canonical(plan))


def closed_observation(value, plan):
    keys = {'reader', 'invocation_id', 'status', 'limit_issue', 'exit_status'}
    if type(value) is not dict or set(value) != keys or value['reader'] != plan['reader']:
        fail('OBSERVATION')
    operation(value['invocation_id'])
    status, issue, exit_status = value['status'], value['limit_issue'], value['exit_status']
    if type(exit_status) is not int or not 0 <= exit_status <= 255:
        fail('OBSERVATION')
    if status == 'source_limit':
        if type(issue) is not str or issue not in ISSUES or exit_status != 1:
            fail('OBSERVATION')
    elif status == 'export_succeeded':
        if issue is not None or exit_status != 0:
            fail('OBSERVATION')
    elif status == 'diagnostic_unavailable':
        if issue is not None:
            fail('OBSERVATION')
    else:
        fail('OBSERVATION')
    return dict(value)


def validate_history(history, plan):
    """Validate the closed action grammar in addition to the port's hash chain."""
    if type(history) is not list or not 1 <= len(history) <= 256:
        fail('HISTORY')
    if history[0] != dict(action='apply', state='intent',
                         apply_id=plan['apply_id'], rollback_id=plan['rollback_id']):
        fail('HISTORY')
    mode, index, pending, ended = 'apply', 0, False, False
    for event in history[1:]:
        if type(event) is not dict:
            fail('HISTORY')
        action, state = event.get('action'), event.get('state')
        if action == 'rollback' and state == 'intent':
            if event != dict(action='rollback', state='intent') or (mode == 'restored'):
                fail('HISTORY')
            mode, index, pending, ended = 'rollback', 0, False, False
            continue
        sequence = STEPS if mode == 'apply' else CLEANUP
        if mode == 'restored' or ended:
            fail('HISTORY')
        if action == mode and state == 'blocked':
            if event != dict(action=mode, state='blocked'):
                fail('HISTORY')
            ended = True
            continue
        if action == mode and state == 'done':
            if index != len(sequence) or pending or event != dict(action=mode, state='done'):
                fail('HISTORY')
            ended = True
            if mode == 'rollback':
                mode = 'restored'
            continue
        if index >= len(sequence) or action != sequence[index]:
            fail('HISTORY')
        if state == 'intent' and not pending:
            if event != dict(action=action, state='intent'):
                fail('HISTORY')
            pending = True
        elif state == 'done' and pending:
            if action == 'observe':
                if set(event) != {'action', 'state', 'observation'}:
                    fail('HISTORY')
                closed_observation(event['observation'], plan)
            elif event != dict(action=action, state='done'):
                fail('HISTORY')
            index += 1
            pending = False
        else:
            fail('HISTORY')
    return mode


class Controller:
    """Synchronous controller. Port owns trusted durable journal and host lock.

    Port MUST implement a nonblocking exclusive host lock; immutable append
    (fsync before returning); exact baseline proof/preflight; atomic no-clobber
    files with ownership records; owned runtime masks; idle/no-job verification;
    one bounded systemd start; exact invocation-bound observation; paired cleanup
    that refuses drift and never kills an already-running original service.

    `perform` accepts only STEPS/CLEANUP below, never a shell string. Read/append
    accept only the exact plan hash. A crash after run intent makes apply
    permanently non-replayable; only rollback is permitted. Failed cleanup
    remains pending and must not claim timer restoration.
    """
    def __init__(self, port, *, sources):
        self.port, self.sources = port, sources

    def _record(self, plan_hash, action, state, **values):
        if state not in ('intent', 'done', 'blocked'):
            fail('EVENT')
        event = dict(action=action, state=state, **values)
        self.port.append(plan_hash, event)

    def _step(self, plan_hash, action, plan, files):
        self._record(plan_hash, action, 'intent')
        result = self.port.perform(action, plan, files)
        # Only the observation operation is allowed to return public data.
        if action == 'observe':
            result = closed_observation(result, plan)
            self._record(plan_hash, action, 'done', observation=result)
        else:
            if result is not None:
                fail('PORT_RESULT')
            self._record(plan_hash, action, 'done')
        return result

    def apply(self, plan, files):
        plan_hash = validate_plan(plan, files, sources=self.sources)
        with self.port.lock():
            if self.port.read(plan_hash):
                fail('ALREADY_ATTEMPTED')
            # Must establish exact current 21cd receipt, prepared/installed file
            # identities, SOURCE_LIMIT failure, timer state, no drop-ins/masks,
            # idle/no jobs, output absence and whole fixed source manifest.
            self.port.preflight(plan, files)
            self._record(plan_hash, 'apply', 'intent', apply_id=plan['apply_id'],
                         rollback_id=plan['rollback_id'])
            observation = None
            try:
                for action in STEPS:
                    value = self._step(plan_hash, action, plan, files)
                    if action == 'observe':
                        observation = value
                self._record(plan_hash, 'apply', 'done')
            except BaseException:
                # No exception string, traceback, path, output or DB value in
                # the ledger. Do not retry ambiguous starts or failed cleanup.
                self._record(plan_hash, 'apply', 'blocked')
                raise
        return dict(plan_sha256=plan_hash, observation=observation,
                    rollback_required=True, product_export_verified=False)

    def rollback(self, plan, files, *, apply_id, rollback_id):
        plan_hash = validate_plan(plan, files, sources=self.sources)
        if apply_id != plan['apply_id'] or rollback_id != plan['rollback_id']:
            fail('PAIR')
        operation(apply_id); operation(rollback_id)
        with self.port.lock():
            history = self.port.read(plan_hash)
            if validate_history(history, plan) == 'restored':
                fail('ALREADY_RESTORED')
            # Validates entire immutable chain, paired IDs, owned identities,
            # historical originals and every present new artifact before any
            # cleanup. Missing artifacts are allowed only if their recorded
            # action was not complete, or an earlier cleanup removed them.
            self.port.recovery_preflight(plan, files, history)
            self._record(plan_hash, 'rollback', 'intent')
            try:
                for action in CLEANUP:
                    self._step(plan_hash, action, plan, files)
                self._record(plan_hash, 'rollback', 'done')
            except BaseException:
                self._record(plan_hash, 'rollback', 'blocked')
                raise
        return dict(plan_sha256=plan_hash, restored=True,
                    natural_timer_catchup_possible=True,
                    product_export_verified=False)
