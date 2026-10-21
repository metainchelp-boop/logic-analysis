"""One original-market refresh after an exact restored diagnostic pair.

Isolated candidate: the production loader must pin this file and its unchanged
five dependencies, public sources and one fresh request ID. No CLI/host action
on import. Linux timer timestamp compatibility requires separate qualification.
"""
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
import types
import transition as T
import preflight as B
import current_guard as G
import systemd_boundary as S
import journal as J

CONTROL = Path('/var/lib/metainc/naver-market-diagnostic-control')
LEDGER_ROOT = CONTROL / 'ledger'
RESTORED_APPLY = 'fe01f9ef77664899845a10f45b614a61'
RESTORED_ROLLBACK = '89b2fcf8da264c16b3287b58d17735a1'
RESTORED_PLAN = '7981ededcf45a943fed04f5c6192878a4b0f8b20ce923dd2df0fcade4645428f'
START = ['/usr/bin/systemctl', 'start', T.OLD_COORDINATOR]
NEXT = ['/usr/bin/busctl', 'get-property', 'org.freedesktop.systemd1',
        '/org/freedesktop/systemd1/unit/naver_2dmarket_2dexport_2etimer',
        'org.freedesktop.systemd1.Timer', 'NextElapseUSecRealtime']
# Safety interval, not a relaxation of S.bounded's 75s/32768B limits.
SAFETY_SECONDS = 300
EXPORT_CODES = frozenset(('EXPORT_BUNDLE_INVALID EXPORT_BUNDLE_STALE EXPORT_COMMAND_FAILED '
    'EXPORT_DATABASE_NAME EXPORT_DIRECTORY_POLICY EXPORT_FILE_CHANGED EXPORT_FILE_POLICY '
    'EXPORT_IDENTITY EXPORT_IDENTITY_CHANGED EXPORT_INSTALLED_CHANGED EXPORT_JOURNAL '
    'EXPORT_OPERATION EXPORT_OUTPUT_CONFLICT EXPORT_PATH EXPORT_PIN EXPORT_PREPARED_CHANGED '
    'EXPORT_PROFILE EXPORT_PYTHON EXPORT_RECEIPT EXPORT_ROOT_REQUIRED EXPORT_RUN_NOT_VERIFIED '
    'EXPORT_SOURCE_CHANGED EXPORT_SOURCE_PATH EXPORT_SOURCE_SCOPE EXPORT_SOURCE_SYMLINK '
    'EXPORT_SYMLINK EXPORT_TIME').split())
CODES = frozenset(('REFRESH_REQUEST REFRESH_HOST REFRESH_REUSED REFRESH_PLAN '
    'REFRESH_NOT_RESTORED REFRESH_CLEANUP REFRESH_PATH REFRESH_CHANGED REFRESH_PROOF '
    'REFRESH_TIMER_NEXT REFRESH_TIMER_NEAR REFRESH_CLOCK REFRESH_DEADLINE REFRESH_COMMAND '
    'REFRESH_START_FAILED REFRESH_START_AMBIGUOUS REFRESH_VERIFY REFRESH_REFUSED '
    'JOURNAL_BUSY JOURNAL_LOCK JOURNAL_CHANGED JOURNAL_FILE JOURNAL_DIRECTORY '
    'JOURNAL_PATH JOURNAL_SIZE JOURNAL_OPERATION_RESERVED').split()) | EXPORT_CODES


def fail(code):
    T.fail(code)


def request(value):
    if (type(value) is not dict or set(value) != {'version', 'refresh_id'}
            or type(value['version']) is not int or value['version'] != 1):
        fail('REFRESH_REQUEST')
    try: T.operation(value['refresh_id'])
    except T.Invalid: fail('REFRESH_REQUEST')
    if value['refresh_id'] in (RESTORED_APPLY, RESTORED_ROLLBACK):
        fail('REFRESH_REQUEST')
    return S.decode(T.canonical(value))


def next_epoch(raw):
    # Fixed D-Bus uint64 microseconds, no human date or display-format inference.
    if type(raw) is not bytes or len(raw) > 128:
        fail('REFRESH_TIMER_NEXT')
    match = re.fullmatch(rb't ([1-9][0-9]{0,19})\n', raw)
    if match is None: fail('REFRESH_TIMER_NEXT')
    microseconds = int(match[1])
    if microseconds >= (1 << 64) - 1: fail('REFRESH_TIMER_NEXT')
    return microseconds / 1_000_000


def validate(value):
    keys = {'version', 'status', 'error_code', 'attempt_consumed', 'start_requested',
        'original_export_success_verified', 'database_opened', 'diagnostic_output_read',
        'product_deployed', 'ads_written'}
    if (type(value) is not dict or set(value) != keys or type(value['version']) is not int
            or value['version'] != 1 or type(value['status']) is not str
            or value['status'] not in ('refused', 'attempt_failed', 'verified')
            or any(type(value[k]) is not bool for k in keys - {'version', 'status', 'error_code'})
            or any(value[k] for k in ('database_opened', 'diagnostic_output_read', 'product_deployed', 'ads_written'))
            or (value['start_requested'] and not value['attempt_consumed'])):
        fail('REFRESH_RESULT')
    if value['status'] == 'verified':
        if value['error_code'] is not None or not all(value[k] for k in
                ('attempt_consumed', 'start_requested', 'original_export_success_verified')):
            fail('REFRESH_RESULT')
    elif (type(value['error_code']) is not str or value['error_code'] not in CODES
            or value['original_export_success_verified']
            or (value['status'] == 'attempt_failed') != value['attempt_consumed']):
        fail('REFRESH_RESULT')
    return value


def closed_json(value):
    raw = T.canonical(validate(value))
    if len(raw) > 4096: fail('REFRESH_RESULT')
    return raw.decode('ascii')


def _result(error=None, *, consumed=False, started=False, verified=False):
    return validate(dict(version=1, status='verified' if verified else
        ('attempt_failed' if consumed else 'refused'), error_code=error,
        attempt_consumed=consumed, start_requested=started,
        original_export_success_verified=verified, database_opened=False,
        diagnostic_output_read=False, product_deployed=False, ads_written=False))


def _code(error):
    if (type(error) in (T.Invalid, B.Invalid) and len(error.args) == 1
            and type(error.args[0]) is str and error.args[0] in CODES):
        return error.args[0]
    return 'REFRESH_REFUSED'


def _absent(path):
    path = Path(path)
    # Check every existing ancestor without following a link. A missing fixed
    # parent proves absence; replaced/non-root/writable parents are refused.
    for item in reversed((path, *path.parents)):
        try: info = item.lstat()
        except FileNotFoundError: return
        if item == path: fail('REFRESH_CLEANUP')
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022):
            fail('REFRESH_PATH')


def _cleaned(ledger, plan, files, systemd):
    ledger._held()
    history = ledger.read(RESTORED_PLAN)
    if T.validate_history(history, plan) != 'restored':
        fail('REFRESH_NOT_RESTORED')
    observations = [e['observation'] for e in history
        if e.get('action') == 'observe' and e.get('state') == 'done']
    if (len(observations) != 1 or observations[0]['status'] != 'diagnostic_unavailable'
            or observations[0]['exit_status'] != 0 or observations[0]['limit_issue'] is not None):
        fail('REFRESH_NOT_RESTORED')
    for path in (*files, *(S.MASK_ROOT + '/' + u for u in plan['original_units'])):
        _absent(path)
    for key in ('coordinator', 'reader'):
        state = systemd.show(plan[key])
        if (state['LoadState'] != 'not-found' or state['FragmentPath']
                or state['DropInPaths'] or state['UnitFileState'] not in ('', 'not-found')
                or not S.idle(state)):
            fail('REFRESH_CLEANUP')
    ledger._held()


class _Clock:
    def __init__(self):
        self.wall, self.mono = time.time(), time.monotonic()

    def now(self):
        wall, mono = time.time(), time.monotonic()
        if (not all(math.isfinite(x) for x in (wall, mono, self.wall, self.mono))
                or mono < self.mono or abs((wall-self.wall)-(mono-self.mono)) > 1):
            fail('REFRESH_CLOCK')
        return wall, mono


class _Attempt:
    """Internal adapter; all injection for tests is module patching, not input."""
    def __init__(self):
        self.started = False
        self.clock = _Clock()
        self.deadline = None

    def command(self, argv, *, limit, timeout):
        _, mono = self.clock.now()
        if self.deadline is not None:
            timeout = min(timeout, int(self.deadline - mono))
            if timeout < 1: fail('REFRESH_DEADLINE')
        return S.bounded(argv, limit=limit, timeout=timeout)

    def next(self):
        code, raw = self.command(list(NEXT), limit=128, timeout=8)
        if type(code) is not int or code != 0: fail('REFRESH_TIMER_NEXT')
        epoch = next_epoch(raw)
        wall, mono = self.clock.now()
        if epoch - wall <= SAFETY_SECONDS: fail('REFRESH_TIMER_NEAR')
        return epoch, mono

    def start(self):
        if self.started: fail('REFRESH_REUSED')
        if self.deadline is None or self.clock.now()[1] >= self.deadline:
            fail('REFRESH_DEADLINE')
        self.started = True  # Set before the subprocess request, including errors.
        try:
            code, raw = self.command(list(START), limit=4096, timeout=75)
        except Exception:
            raise T.Invalid('REFRESH_START_AMBIGUOUS') from None
        if type(code) is not int or type(raw) is not bytes or len(raw) > 4096:
            fail('REFRESH_START_AMBIGUOUS')
        if code != 0: fail('REFRESH_START_FAILED')

    def verify_command(self, args):
        allowed = []
        for kind in ('product', 'market'):
            for tail in ('.service', '-reader.service'):
                allowed.append(['systemctl', 'show', 'naver-' + kind + '-export' + tail,
                    '--property=Result', '--property=ExecMainStatus'])
            for action in ('is-enabled', 'is-active'):
                allowed.append(['systemctl', action, 'naver-' + kind + '-export.timer'])
        if type(args) is not list or args not in allowed: fail('REFRESH_COMMAND')
        code, raw = self.command(['/usr/bin/systemctl', *args[1:]], limit=4096, timeout=8)
        if type(code) is not int or code != 0 or type(raw) is not bytes or len(raw) > 4096:
            fail('REFRESH_COMMAND')
        return raw


def _compare(proofs, baseline_sources):
    fresh, baseline = B.collect(baseline_sources)
    if not T.same(fresh, proofs): fail('REFRESH_PROOF')
    return baseline


def _helper(baseline_sources):
    body = baseline_sources['exports_helper']
    if type(body) is not bytes or T.sha(body) != T.HELPER_PIN:
        fail('REFRESH_PROOF')
    helper = types.ModuleType('original_market_refresh_helper')
    exec(compile(body, '<original-helper>', 'exec'), helper.__dict__)
    return helper


def _verify_original(helper, receipt, attempt):
    try:
        verified = helper.verify(receipt, command=attempt.verify_command, require_timers=True)
    except helper.ExportInstallInvalid as error:
        if len(error.args) == 1 and type(error.args[0]) is str and error.args[0] in EXPORT_CODES:
            raise T.Invalid(error.args[0]) from None
        raise T.Invalid('REFRESH_VERIFY') from None
    if (type(verified) is not dict or verified.get('state') != 'verified'
            or verified.get('timers_enabled') is not True):
        fail('REFRESH_VERIFY')


def _execute(value, *, sources, baseline_sources):
    proofs, baseline = B.collect(baseline_sources)
    plan, files = T.compile_plan(apply_id=RESTORED_APPLY, rollback_id=RESTORED_ROLLBACK,
                                 sources=sources, previous=proofs)
    if T.sha(T.canonical(plan)) != RESTORED_PLAN: fail('REFRESH_PLAN')
    attempt = _Attempt()
    systemd = S.Systemd(plan, files, sources=sources, command=attempt.command)
    guard = G.CurrentGuard(proofs, command=attempt.command)
    ledger = J.Ledger(LEDGER_ROOT, plan)
    consumed = False
    folder = LEDGER_ROOT / ('refresh-' + value['refresh_id'])
    # The lock must already exist; reuse its original root/owner/mode/inode
    # checks, and do not create a replacement transition lock for this action.
    _, lock_info = ledger._file(LEDGER_ROOT / 'transition.lock')
    if lock_info.st_size != 0: fail('JOURNAL_LOCK')
    with ledger.lock():
        try:
            ledger._held()
            if ledger._lock_identity != J.identity(lock_info): fail('JOURNAL_CHANGED')
            _, used = ledger._reservations(LEDGER_ROOT / 'identities')
            if value['refresh_id'] in used: fail('REFRESH_REUSED')
            try: folder.lstat()
            except FileNotFoundError: pass
            else:
                return _result('REFRESH_REUSED', consumed=True)
            _cleaned(ledger, plan, files, systemd)
            systemd.original_preflight()
            captured = guard.capture()
            baseline = _compare(proofs, baseline_sources)
            guard(require_failure=True)
            systemd.original_preflight()
            next_at, _ = attempt.next()
            # New private directory consumes this ID even if power is lost
            # before intent publication. Nothing resumes a partial preparation.
            folder.mkdir(mode=0o700)
            consumed = True
            os.chmod(folder, 0o700)
            ledger._dir(folder); ledger._sync(LEDGER_ROOT)
            intent = dict(version=1, operation='original-market-refresh',
                refresh_id=value['refresh_id'], source=T.OPERATING_SOURCE,
                restored_plan_sha256=RESTORED_PLAN, previous=proofs,
                current_guard_sha256=T.sha(T.canonical(captured)),
                command=list(START), start_attempts_max=1,
                next_elapse_epoch=next_at, safety_interval_seconds=SAFETY_SECONDS)
            ledger._atomic_new(folder / 'intent.json', T.canonical(intent))
            # No expensive or mutable preparation between this final source,
            # unit/job/timer check and the one start. Timer does not obey flock.
            _compare(proofs, baseline_sources)
            guard(require_failure=True)
            _cleaned(ledger, plan, files, systemd)
            systemd.original_preflight()
            latest, checked_mono = attempt.next()
            if latest != next_at: fail('REFRESH_TIMER_NEXT')
            attempt.deadline = checked_mono + SAFETY_SECONDS
            ledger._held()
            attempt.start()
            baseline = _compare(proofs, baseline_sources)
            guard(require_failure=False)
            # Only original pinned helper bytes; no diagnostic output/bundle.
            _verify_original(_helper(baseline_sources), baseline.prepared_receipt, attempt)
            guard(require_failure=False)
            _compare(proofs, baseline_sources)
            attempt.clock.now()
            if time.monotonic() >= attempt.deadline: fail('REFRESH_DEADLINE')
            result = _result(consumed=True, started=True, verified=True)
        except Exception as error:
            result = _result(_code(error), consumed=consumed, started=attempt.started)
        if consumed:
            # The immutable intent is authoritative for no-replay even if this
            # final record cannot be published. No error recovery calls start.
            ledger._dir(folder)
            ledger._atomic_new(folder / 'result.json', T.canonical(result))
        return result


def run(value, *, sources, baseline_sources):
    value = request(value)
    if sys.platform != 'linux' or os.geteuid() != 0: fail('REFRESH_HOST')
    # Existing source gates run before any private intent or service operation.
    return _execute(value, sources=sources, baseline_sources=baseline_sources)


if __name__ == '__main__':
    raise SystemExit('PINNED_WORKFLOW_REQUIRED')
