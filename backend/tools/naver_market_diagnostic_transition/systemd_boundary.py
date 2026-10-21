"""Closed systemd command and exact-invocation reader for the new diagnostic.

No command runs on import. This module neither installs files nor changes old
receipts. A host transaction must establish ownership and quiescence first.
Raw command/journal bytes stay in memory; only the fixed result enum escapes.
"""
import json
import os
import re
import selectors
import subprocess
import time
import transition as T

PROPERTIES = ('LoadState', 'UnitFileState', 'FragmentPath', 'DropInPaths', 'Job',
              'Result', 'ExecMainStatus', 'ActiveState', 'SubState', 'InvocationID')
TIMER_PROPERTIES = tuple(p for p in PROPERTIES if p != 'ExecMainStatus')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
MASK_ROOT = '/run/systemd/system.control'


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: T.fail('SYSTEMD_JSON')
        result[key] = value
    return result


def decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: T.fail('SYSTEMD_JSON'))
    except (ValueError, UnicodeError, TypeError, RecursionError):
        T.fail('SYSTEMD_JSON')


def bounded(argv, *, limit, timeout):
    """Drain stdout with a byte/deadline bound; stderr is never captured.

    Terminating a timed-out systemctl client does not cancel its unit job. The
    caller must treat that result as ambiguous and must never retry a start.
    """
    if (type(argv) is not list or not argv or any(type(x) is not str for x in argv)
            or type(limit) is not int or not 1 <= limit <= 32768
            or type(timeout) is not int or not 1 <= timeout <= 75):
        T.fail('SYSTEMD_COMMAND')
    process = None
    selector = selectors.DefaultSelector()
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=ENV,
            close_fds=True, start_new_session=True)
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline, chunks, size = time.monotonic() + timeout, [], 0
        while selector.get_map():
            left = deadline - time.monotonic()
            if left <= 0: T.fail('SYSTEMD_COMMAND_AMBIGUOUS')
            for key, _ in selector.select(left):
                chunk = os.read(key.fd, min(4096, limit + 1 - size))
                if not chunk:
                    selector.unregister(key.fileobj)
                    break
                chunks.append(chunk); size += len(chunk)
                if size > limit: T.fail('SYSTEMD_COMMAND_LIMIT')
        left = deadline - time.monotonic()
        if left <= 0: T.fail('SYSTEMD_COMMAND_AMBIGUOUS')
        try: code = process.wait(timeout=left)
        except subprocess.TimeoutExpired: T.fail('SYSTEMD_COMMAND_AMBIGUOUS')
        return code, b''.join(chunks)
    except OSError:
        T.fail('SYSTEMD_COMMAND_UNAVAILABLE')
    finally:
        selector.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
                try: process.wait(timeout=1)
                except subprocess.TimeoutExpired: pass
            if process.stdout is not None: process.stdout.close()


def snapshot(raw, *, kind='service'):
    if type(kind) is not str or kind not in ('service', 'timer'):
        T.fail('SYSTEMD_SNAPSHOT')
    expected = PROPERTIES if kind == 'service' else TIMER_PROPERTIES
    if type(raw) is not bytes or len(raw) > 4096: T.fail('SYSTEMD_SNAPSHOT')
    try:
        pairs = [line.split('=', 1) for line in raw.decode('ascii').splitlines()]
        if any(len(pair) != 2 for pair in pairs): T.fail('SYSTEMD_SNAPSHOT')
        value = unique(pairs)
        if (set(value) != set(expected)
                or any(any(ord(c) < 32 for c in x) for x in value.values())
                or (kind == 'service' and
                    (re.fullmatch('0|[1-9][0-9]{0,2}', value['ExecMainStatus']) is None
                     or int(value['ExecMainStatus']) > 255))):
            T.fail('SYSTEMD_SNAPSHOT')
        invocation = value['InvocationID']
        if invocation not in ('', '0' * 32): T.operation(invocation)
        return value
    except (UnicodeError, TypeError):
        T.fail('SYSTEMD_SNAPSHOT')


def idle(value):
    return (value['Job'] in ('', '0') and
            (value['ActiveState'], value['SubState']) in
            (('inactive', 'dead'), ('failed', 'failed')))


def completed(value):
    # active/exited is a completed retained oneshot, never an executing unit.
    return (value['Job'] in ('', '0')
            and value['UnitFileState'] in ('static', 'disabled')
            and (value['ActiveState'], value['SubState']) == ('active', 'exited')
            and value['Result'] == 'success' and value['ExecMainStatus'] == '0'
            and re.fullmatch('[0-9a-f]{32}', value['InvocationID']) is not None
            and value['InvocationID'] != '0' * 32)


def exact_failure(raw, *, unit, invocation):
    """Accept one exact exporter JSON result in one exact invocation only.

    Historical two-key SOURCE_LIMIT is retained as 'unknown'. Other journal
    prose is ignored, never promoted into a reason. Malformed JSON-looking
    result lines, duplicate results or mismatched invocation rows fail closed.
    """
    T.operation(invocation)
    if type(raw) is not bytes or len(raw) > 32768: T.fail('JOURNAL_LIMIT')
    lines = raw.splitlines()
    if len(lines) > 32: T.fail('JOURNAL_LIMIT')
    result = None
    for line in lines:
        record = decode(line)
        if (type(record) is not dict or record.get('_SYSTEMD_UNIT') != unit
                or record.get('_SYSTEMD_INVOCATION_ID') != invocation
                or type(record.get('MESSAGE')) is not str):
            T.fail('JOURNAL_INVOCATION')
        message = record['MESSAGE']
        if any(ord(c) < 32 and c not in '\t\r\n' for c in message):
            T.fail('JOURNAL_MESSAGE')
        if not message.lstrip().startswith('{'): continue
        value = decode(message)
        if type(value) is not dict or value.get('code') != 'SOURCE_LIMIT':
            continue
        if type(value.get('status')) is not str or value['status'] != 'failed':
            T.fail('JOURNAL_RESULT')
        if result is not None: T.fail('JOURNAL_MULTIPLE_RESULTS')
        if set(value) == {'status', 'code'}:
            result = 'unknown'
        elif (set(value) == {'status', 'code', 'limit_issue'}
                and type(value['limit_issue']) is str and value['limit_issue'] in T.ISSUES):
            result = value['limit_issue']
        else:
            T.fail('JOURNAL_RESULT')
    return result


class Systemd:
    """Only fixed commands derived from one compiler-validated operation plan.

    The callable command seam is for isolated tests. The production entrypoint
    must construct this class with the default bounded runner and pinned plan.
    """
    def __init__(self, plan, files, *, sources, command=bounded):
        T.validate_plan(plan, files, sources=sources)
        self.plan = decode(T.canonical(plan))
        self.command = command
        self.units = frozenset((T.OLD_COORDINATOR, T.OLD_READER, T.OLD_TIMER,
                               plan['coordinator'], plan['reader']))
        self.start_attempted = False

    def _run(self, argv, *, limit=4096, timeout=8, accept=(0,)):
        code, raw = self.command(argv, limit=limit, timeout=timeout)
        if (type(code) is not int or type(raw) is not bytes or len(raw) > limit
                or code not in accept): T.fail('SYSTEMD_COMMAND_FAILED')
        return raw

    def show(self, unit):
        if unit not in self.units: T.fail('SYSTEMD_UNIT')
        kind = 'timer' if unit == T.OLD_TIMER else 'service'
        properties = TIMER_PROPERTIES if kind == 'timer' else PROPERTIES
        return snapshot(self._run(['/usr/bin/systemctl', 'show', unit] +
                                  ['--property=' + p for p in properties]), kind=kind)

    def original_preflight(self):
        self.mask_search_path()
        timer = self.show(T.OLD_TIMER)
        if (timer['LoadState'] != 'loaded' or timer['UnitFileState'] != 'enabled'
                or timer['FragmentPath'] != T.UNIT_ROOT + '/' + T.OLD_TIMER
                or timer['DropInPaths'] or timer['Job'] not in ('', '0')
                or (timer['ActiveState'], timer['SubState']) != ('active', 'waiting')):
            T.fail('ORIGINAL_TIMER')
        for unit in (T.OLD_COORDINATOR, T.OLD_READER):
            value = self.show(unit)
            if (value['LoadState'] != 'loaded' or value['DropInPaths']
                    or value['UnitFileState'] not in ('static', 'disabled')
                    or value['FragmentPath'] != T.UNIT_ROOT + '/' + unit
                    or not idle(value)): T.fail('ORIGINAL_UNIT')
        return True

    def mask_search_path(self):
        # Ordinary /run/systemd/system masks cannot shadow the existing /etc
        # units. Require the manager's actual high-priority runtime control
        # directory; unsupported host layouts fail before any timer mutation.
        raw = self._run(['/usr/bin/systemctl', 'show', '--property=UnitPath'])
        try:
            text = raw.decode('ascii')
            if not text.startswith('UnitPath=') or text.count('\n') != 1:
                T.fail('SYSTEMD_UNIT_PATH')
            paths = text.removeprefix('UnitPath=').rstrip('\n').split(' ')
            if (not paths or len(paths) != len(set(paths))
                    or MASK_ROOT not in paths or T.UNIT_ROOT not in paths
                    or paths.index(MASK_ROOT) >= paths.index(T.UNIT_ROOT)
                    or any(not p.startswith('/') or '\\' in p for p in paths)):
                T.fail('SYSTEMD_UNIT_PATH')
        except UnicodeError:
            T.fail('SYSTEMD_UNIT_PATH')
        return MASK_ROOT

    def timer_stop(self):
        self._run(['/usr/bin/systemctl', 'stop', T.OLD_TIMER])
        if not idle(self.show(T.OLD_TIMER)): T.fail('ORIGINAL_TIMER_NOT_IDLE')

    def reload(self):
        self._run(['/usr/bin/systemctl', 'daemon-reload'])

    def verify_units(self):
        self._run(['/usr/bin/systemd-analyze', 'verify'] +
            [T.UNIT_ROOT + '/' + self.plan[k] for k in ('coordinator', 'reader')],
            timeout=15)

    def masked_idle(self):
        if not idle(self.show(T.OLD_TIMER)): T.fail('ORIGINAL_TIMER_NOT_IDLE')
        for unit in (T.OLD_COORDINATOR, T.OLD_READER):
            value = self.show(unit)
            if (value['LoadState'] != 'masked' or value['DropInPaths']
                    or value['FragmentPath'] != MASK_ROOT + '/' + unit
                    or value['UnitFileState'] != 'masked-runtime' or not idle(value)):
                T.fail('ORIGINAL_NOT_MASKED_IDLE')

    def new_idle(self):
        for key in ('coordinator', 'reader'):
            unit = self.plan[key]
            value = self.show(unit)
            if (value['LoadState'] != 'loaded' or value['DropInPaths']
                    or value['UnitFileState'] not in ('static', 'disabled')
                    or value['FragmentPath'] != T.UNIT_ROOT + '/' + unit
                    or not idle(value)): T.fail('DIAGNOSTIC_NOT_IDLE')

    def _cleanup_idle_snapshot(self, unit, value):
        if value['LoadState'] == 'not-found':
            return (not value['FragmentPath'] and not value['DropInPaths'] and idle(value)
                    and value['UnitFileState'] in ('', 'not-found'))
        return (value['LoadState'] == 'loaded' and not value['DropInPaths']
                and value['UnitFileState'] in ('static', 'disabled')
                and value['FragmentPath'] == T.UNIT_ROOT + '/' + unit and idle(value))

    def cleanup_idle(self):
        # The HostPort verifies paired publication ownership before this step.
        # Partial installation and interrupted cleanup still permit idle missing
        # units. Only completed retained operation units can receive stop.
        states = [(self.plan[key], self.show(self.plan[key]))
                  for key in ('coordinator', 'reader')]
        retained = []
        for unit, value in states:
            if self._cleanup_idle_snapshot(unit, value): continue
            if (value['LoadState'] != 'loaded' or value['DropInPaths']
                    or value['FragmentPath'] != T.UNIT_ROOT + '/' + unit
                    or not completed(value)):
                T.fail('DIAGNOSTIC_NOT_IDLE')
            retained.append(unit)
        if retained:
            # Refuse changed/contradictory snapshots before any stop command.
            for unit, before in states:
                if not T.same(before, self.show(unit)):
                    T.fail('DIAGNOSTIC_CONTEXT_CHANGED')
            self._run(['/usr/bin/systemctl', 'stop'] + retained)
            # Never remove an active or running unit, including after a timeout
            # or a partially effective stop. Original idle rules remain final.
            for unit, _ in states:
                if not self._cleanup_idle_snapshot(unit, self.show(unit)):
                    T.fail('DIAGNOSTIC_NOT_IDLE')

    def start_once(self):
        if self.start_attempted: T.fail('DIAGNOSTIC_START_REPLAY')
        self.masked_idle(); self.new_idle()
        before = self.show(self.plan['reader'])
        if before['InvocationID'] not in ('', '0' * 32): T.fail('DIAGNOSTIC_ALREADY_RAN')
        # Set before invoking: failure, timeout and process interruption consume
        # the attempt. Durable controller action intent is additionally required.
        self.start_attempted = True
        self._run(['/usr/bin/systemctl', 'start', self.plan['coordinator']],
                  timeout=75, accept=(0, 1))

    def observe(self):
        unit = self.plan['reader']
        before = self.show(unit)
        if (before['FragmentPath'] != T.UNIT_ROOT + '/' + unit or before['DropInPaths']
                or before['LoadState'] != 'loaded'
                or not (idle(before) or completed(before))):
            T.fail('DIAGNOSTIC_CONTEXT')
        invocation = T.operation(before['InvocationID'])
        raw = self._run(['/usr/bin/journalctl', '--output=json', '--no-pager', '-n', '32',
            '_SYSTEMD_UNIT=' + unit, '_SYSTEMD_INVOCATION_ID=' + invocation], limit=32768)
        issue = exact_failure(raw, unit=unit, invocation=invocation)
        if not T.same(before, self.show(unit)): T.fail('DIAGNOSTIC_CONTEXT_CHANGED')
        code = int(before['ExecMainStatus'])
        status = ('source_limit' if issue is not None and code == 1
                  and before['Result'] == 'exit-code' else 'diagnostic_unavailable')
        # Unit success alone cannot verify an export bundle. That result remains
        # unavailable here; the unchanged original exporter gate is independent.
        return T.closed_observation(dict(reader=unit, invocation_id=invocation,
            status=status, limit_issue=issue if status == 'source_limit' else None,
            exit_status=code), self.plan)

    def timer_restore(self):
        self._run(['/usr/bin/systemctl', 'start', T.OLD_TIMER])
        # Persistent=true may immediately start the original natural job. Do not
        # stop or reject that legitimate catch-up as a second controller attempt.
        timer = self.show(T.OLD_TIMER)
        if (timer['LoadState'] != 'loaded' or timer['UnitFileState'] != 'enabled'
                or timer['FragmentPath'] != T.UNIT_ROOT + '/' + T.OLD_TIMER
                or timer['DropInPaths'] or timer['ActiveState'] != 'active'):
            T.fail('ORIGINAL_TIMER_NOT_RESTORED')
