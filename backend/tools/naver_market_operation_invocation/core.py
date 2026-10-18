"""One fixed historical PID1 metadata query; no service or payload access.

The only production entry is observe(), with no target or command arguments.
Unit success is not export validation. Absence never proves nonexecution.
"""
import datetime
import json
import os
import re
import selectors
import subprocess
import sys
import time

APPLY = '7abd8b3965ed4b51a3b071cd218e024f'
ROLLBACK = '4aa3189c384847178ecafbfa34eb060e'
PLAN_SHA256 = 'b9b63866d280845df60d99aa0ba7c5f0d00f90b128583c291abfe1a542ed35a3'
FAILED_RUN_ID = 39092917351
UNITS = {'coordinator': 'naver-market-diagnostic-' + APPLY + '.service',
         'reader': 'naver-market-diagnostic-' + APPLY + '-reader.service'}
WINDOW = {'start': '2026-10-18T03:14:45Z', 'end': '2026-10-18T03:15:18Z'}
PROVENANCE = {
    'ledger': '7dcdfc8b2ef2bf99766b2bd59595b27b22da3c6407fbcca0b735d96e95dfe3c6',
    'window': 'e38e550f57d4d3d11e00407e2f6d615c1e517c04a9a52e301bf25b6ddd49ca0b',
    'apply': 'e37524077eb2f84bf678999a47a7fe0a5b9c5f3df318949be9aaf64050aa5b99',
    'restored': 'd11910a1312430ca5f69bf3318b7d9b044f87ae0d0bd67fc442a5bd0dee0db2e',
    'helper': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737',
    'transition': 'acd5636795506381c89ac0aa8657c7ea1b4f6a26985f50b0297fba62c7d5591a',
}
SUCCESS = '7ad2d189f7e94e70a38c781354912448'
FAILURE = 'd9b373ed55a64feb8242e02dbe79a49c'
EXIT = '98e322203f7a4ed290d09fe03c09fe15'
MESSAGE_IDS = (SUCCESS, FAILURE, EXIT)
RESULTS = frozenset(('resources', 'protocol', 'timeout', 'exit-code', 'signal',
                    'core-dump', 'watchdog', 'start-limit-hit', 'oom-kill'))
FIELDS = ('_PID', '_UID', '_COMM', '_TRANSPORT', 'UNIT', 'INVOCATION_ID',
          'MESSAGE_ID', 'UNIT_RESULT', 'EXIT_CODE', 'EXIT_STATUS')
ADDRESS = frozenset(('__CURSOR', '__REALTIME_TIMESTAMP', '__MONOTONIC_TIMESTAMP', '_BOOT_ID'))
SEQUENCE = frozenset(('__SEQNUM', '__SEQNUM_ID'))
COMMON = frozenset(FIELDS[:7]) | ADDRESS
MAX_BYTES, MAX_ROWS, TIMEOUT = 32768, 32, 8
REFUSALS = frozenset(('none', 'platform', 'command_failed', 'command_limit',
    'deadline', 'unavailable', 'json', 'schema', 'provenance', 'time_window',
    'order', 'multiple_invocations', 'duplicate', 'conflict', 'result'))
STATES = frozenset(('not_observed', 'unit_success', 'unit_failure',
                    'process_success', 'process_failure'))
ROLE_KEYS = frozenset(('state', 'invocation', 'unit_result', 'exit_kind',
    'exit_status', 'evidence_count', 'terminal_count', 'process_exit_count'))
FLAGS = ('message_read', 'diagnostic_output_read', 'service_changed',
         'export_verified', 'nonexecution_proven', 'host_clock_verified')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C', 'TZ': 'UTC'}


class Refused(ValueError):
    pass


def fail(code):
    raise Refused(code if code in REFUSALS else 'result')


def _micros(value):
    return int(datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
               .replace(tzinfo=datetime.timezone.utc).timestamp()) * 1000000


START_US, END_US = _micros(WINDOW['start']), _micros(WINDOW['end']) + 999999


def _argv():
    # API timestamps have second resolution. Include that final second only.
    return ['/usr/bin/journalctl', '--system', '--no-pager', '--quiet',
        '--output=json', '--output-fields=' + ','.join(FIELDS),
        '--since=2026-10-18 03:14:45.000000 UTC',
        '--until=2026-10-18 03:15:18.999999 UTC', '-n', str(MAX_ROWS + 1),
        '_PID=1', '_UID=0', '_COMM=systemd', '_TRANSPORT=journal'] + [
        'UNIT=' + v for v in UNITS.values()] + ['MESSAGE_ID=' + v for v in MESSAGE_IDS]


def _capture(argv, *, limit=MAX_BYTES, timeout=TIMEOUT):
    """Private command seam; observe supplies only the fixed argv above."""
    deadline = time.monotonic() + timeout
    process = None
    selector = selectors.DefaultSelector()
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=ENV,
            close_fds=True, start_new_session=True)
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        body = bytearray()
        while selector.get_map():
            left = deadline - time.monotonic()
            if left <= 0: fail('deadline')
            for key, _ in selector.select(left):
                chunk = os.read(key.fd, min(4096, limit + 1 - len(body)))
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    body.extend(chunk)
                    if len(body) > limit: fail('command_limit')
        left = deadline - time.monotonic()
        if left <= 0: fail('deadline')
        try: code = process.wait(timeout=left)
        except subprocess.TimeoutExpired: fail('deadline')
        if type(code) is not int or code != 0: fail('command_failed')
        return bytes(body)
    except OSError:
        fail('unavailable')
    finally:
        selector.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
                try: process.wait(timeout=1)
                except subprocess.TimeoutExpired: pass
            if process.stdout is not None: process.stdout.close()


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value: fail('duplicate')
        value[key] = item
    return value


def _decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique,
                          parse_constant=lambda _: fail('json'))
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        if isinstance(error, Refused): raise
        fail('json')


def _hex(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{32}', value) is not None and value != '0' * 32


def _number(value, maximum):
    if (type(value) is not str or re.fullmatch('0|[1-9][0-9]{0,19}', value) is None
            or int(value) > maximum): fail('schema')
    return int(value)


def _role_empty():
    return dict(state='not_observed', invocation='none', unit_result=None,
        exit_kind=None, exit_status=None, evidence_count=0,
        terminal_count=0, process_exit_count=0)


def _result(roles=None, refusal='none'):
    return dict(version=1, status='refused' if refusal != 'none' else 'observed',
        refusal=refusal, roles=roles, **{flag: False for flag in FLAGS})


def parse(raw):
    """Pure strict parser. No MESSAGE bytes or diagnostic result body accepted."""
    if type(raw) is not bytes or len(raw) > MAX_BYTES: fail('command_limit')
    lines = raw.splitlines()
    if len(lines) > MAX_ROWS: fail('command_limit')
    slots = {k: {'invocation': None, 'terminal': None, 'process': None, 'count': 0}
             for k in UNITS}
    roles_by_unit = {v: k for k, v in UNITS.items()}
    cursors, boot, last_real, last_mono = set(), None, -1, -1
    sequence_mode, sequence_id, last_sequence = None, None, -1
    for line in lines:
        record = _decode(line)
        if type(record) is not dict or not COMMON <= set(record): fail('schema')
        message = record['MESSAGE_ID']
        extra = ({'UNIT_RESULT'} if message == FAILURE else
                 {'EXIT_CODE', 'EXIT_STATUS'} if message == EXIT else set())
        present_sequence = set(record) & SEQUENCE
        if present_sequence and present_sequence != SEQUENCE: fail('schema')
        if message not in MESSAGE_IDS or set(record) != COMMON | extra | present_sequence:
            fail('schema')
        if any(type(v) is not str or len(v) > 512 or any(ord(c) < 32 for c in v)
               for v in record.values()): fail('schema')
        if (record['_PID'] != '1' or record['_UID'] != '0' or
                record['_COMM'] != 'systemd' or record['_TRANSPORT'] != 'journal' or
                record['UNIT'] not in roles_by_unit or not _hex(record['_BOOT_ID']) or
                not _hex(record['INVOCATION_ID'])): fail('provenance')
        if boot is not None and boot != record['_BOOT_ID']: fail('provenance')
        boot = record['_BOOT_ID']
        has_sequence = bool(present_sequence)
        if sequence_mode is not None and sequence_mode != has_sequence: fail('provenance')
        sequence_mode = has_sequence
        if has_sequence:
            current_id = record['__SEQNUM_ID']
            if not _hex(current_id): fail('schema')
            current_sequence = _number(record['__SEQNUM'], (1 << 64) - 1)
            if sequence_id is not None and sequence_id != current_id: fail('provenance')
            if current_sequence <= last_sequence: fail('order')
            sequence_id, last_sequence = current_id, current_sequence
        real = _number(record['__REALTIME_TIMESTAMP'], (1 << 63) - 1)
        mono = _number(record['__MONOTONIC_TIMESTAMP'], (1 << 63) - 1)
        if not START_US <= real <= END_US: fail('time_window')
        if real < last_real or mono < last_mono: fail('order')
        last_real, last_mono = real, mono
        cursor = record['__CURSOR']
        if not cursor or cursor in cursors: fail('duplicate')
        cursors.add(cursor)
        slot = slots[roles_by_unit[record['UNIT']]]
        invocation = record['INVOCATION_ID']
        if slot['invocation'] is not None and slot['invocation'] != invocation:
            fail('multiple_invocations')
        slot['invocation'], slot['count'] = invocation, slot['count'] + 1
        if message in (SUCCESS, FAILURE):
            if slot['terminal'] is not None: fail('duplicate')
            result = record.get('UNIT_RESULT')
            if message == FAILURE and result not in RESULTS: fail('schema')
            slot['terminal'] = ('unit_success', None) if message == SUCCESS else ('unit_failure', result)
        else:
            if slot['process'] is not None: fail('duplicate')
            kind, status = record['EXIT_CODE'], _number(record['EXIT_STATUS'], 255)
            if kind not in ('exited', 'killed', 'dumped') or (kind != 'exited' and status == 0):
                fail('schema')
            slot['process'] = (kind, status)
    # Two separate services must not share one runtime cycle identity.
    ids = [s['invocation'] for s in slots.values() if s['invocation'] is not None]
    if len(ids) != len(set(ids)): fail('conflict')
    roles = {}
    for role, slot in slots.items():
        item = _role_empty()
        if slot['invocation'] is None:
            roles[role] = item
            continue
        item.update(invocation='one', evidence_count=slot['count'])
        terminal, process = slot['terminal'], slot['process']
        if process:
            kind, status = process
            item.update(exit_kind=kind, exit_status=status, process_exit_count=1)
            item['state'] = 'process_success' if process == ('exited', 0) else 'process_failure'
        if terminal:
            item.update(state=terminal[0], unit_result=terminal[1], terminal_count=1)
            if terminal[0] == 'unit_success' and process and process != ('exited', 0):
                fail('conflict')
            if terminal[0] == 'unit_failure' and process == ('exited', 0): fail('conflict')
            if process and terminal[0] == 'unit_failure':
                expected = {'exited': 'exit-code', 'killed': 'signal', 'dumped': 'core-dump'}[process[0]]
                # Timeout/watchdog/resource failure can kill a process too.
                if terminal[1] in ('exit-code', 'signal', 'core-dump') and terminal[1] != expected:
                    fail('conflict')
        roles[role] = item
    return validate(_result(roles))


def validate(value):
    keys = {'version', 'status', 'refusal', 'roles'} | set(FLAGS)
    if (type(value) is not dict or set(value) != keys or type(value['version']) is not int
            or value['version'] != 1 or any(value[k] is not False for k in FLAGS)
            or type(value['refusal']) is not str or value['refusal'] not in REFUSALS):
        fail('result')
    if value['status'] == 'refused':
        if value['refusal'] == 'none' or value['roles'] is not None: fail('result')
        return value
    if (value['status'] != 'observed' or value['refusal'] != 'none'
            or type(value['roles']) is not dict or set(value['roles']) != set(UNITS)):
        fail('result')
    for item in value['roles'].values():
        if type(item) is not dict or set(item) != ROLE_KEYS: fail('result')
        if (type(item['state']) is not str or item['state'] not in STATES
                or type(item['invocation']) is not str or item['invocation'] not in ('none', 'one')):
            fail('result')
        for key in ('evidence_count', 'terminal_count', 'process_exit_count'):
            if type(item[key]) is not int or not 0 <= item[key] <= (2 if key == 'evidence_count' else 1):
                fail('result')
        if item['evidence_count'] != item['terminal_count'] + item['process_exit_count']: fail('result')
        if item['state'] == 'not_observed':
            if item != _role_empty(): fail('result')
            continue
        if item['invocation'] != 'one' or item['evidence_count'] == 0: fail('result')
        kind, status = item['exit_kind'], item['exit_status']
        if item['process_exit_count']:
            if (type(kind) is not str or kind not in ('exited', 'killed', 'dumped')
                    or type(status) is not int or not 0 <= status <= 255
                    or (kind != 'exited' and status == 0)): fail('result')
        elif kind is not None or status is not None: fail('result')
        state = item['state']
        if state.startswith('unit_'):
            if item['terminal_count'] != 1: fail('result')
            if state == 'unit_success':
                if item['unit_result'] is not None or (kind is not None and (kind, status) != ('exited', 0)):
                    fail('result')
            elif (type(item['unit_result']) is not str or item['unit_result'] not in RESULTS
                  or (kind, status) == ('exited', 0)): fail('result')
            if (state == 'unit_failure' and kind is not None
                    and item['unit_result'] in ('exit-code', 'signal', 'core-dump')
                    and item['unit_result'] != {'exited': 'exit-code', 'killed': 'signal', 'dumped': 'core-dump'}[kind]):
                fail('result')
        elif (item['terminal_count'] != 0 or item['process_exit_count'] != 1
              or item['unit_result'] is not None
              or ((kind, status) == ('exited', 0)) != (state == 'process_success')):
            fail('result')
    return value


def closed_json(value):
    body = json.dumps(validate(value), sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(body.encode('ascii')) > 4096: fail('result')
    return body


def observe():
    try:
        if not sys.platform.startswith('linux') or os.geteuid() != 0: fail('platform')
        return parse(_capture(_argv()))
    except Refused as error:
        code = error.args[0] if len(error.args) == 1 else 'unavailable'
        return validate(_result(refusal=code if code in REFUSALS else 'unavailable'))
    except Exception:
        return validate(_result(refusal='unavailable'))
