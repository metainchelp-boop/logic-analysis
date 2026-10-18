"""Pinned fixed-pair ledger observation; no service, DB or explicit FS writes."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import sys
import threading
import time
import types

APPLY = '7abd8b3965ed4b51a3b071cd218e024f'
ROLLBACK = '4aa3189c384847178ecafbfa34eb060e'
PLAN_SHA256 = 'b9b63866d280845df60d99aa0ba7c5f0d00f90b128583c291abfe1a542ed35a3'
DEPENDENCY_PINS = {
    'transition': 'acd5636795506381c89ac0aa8657c7ea1b4f6a26985f50b0297fba62c7d5591a',
    'journal': '27e2ec8c7b332951151dcb19bd60ec527eb768d1b1711f40069b8dd1ac191333',
}
DEPENDENCY_SIZES = {'transition': 15664, 'journal': 11244}
ROOT = Path('/var/lib/metainc/naver-market-diagnostic-control/ledger')
OWNER, GROUP = 0, 0
MAX_READ = 32 * 1024 * 1024
SECONDS = 10
STEPS = ('timer_stop', 'mask_original', 'quiescence_verify', 'install_new',
         'unit_verify', 'daemon_reload', 'installed_verify', 'run_once', 'observe')
REFUSALS = ('none', 'source_binding', 'unsupported_host', 'module_collision',
            'lock_missing', 'lock_busy', 'lock_invalid', 'context_changed',
            'plan_binding', 'ledger_rejected', 'deadline', 'read_budget', 'unavailable')
FIELDS = ('history_state', 'last_apply_step', 'last_apply_step_state',
          'run_once_intent', 'run_once_done', 'observe_intent', 'observe_done',
          'apply_blocked', 'rollback_done')


class Refused(RuntimeError):
    pass


def fail(code):
    raise Refused(code)


def _blank(code):
    return dict(version=1, status='refused', refusal=code, **dict.fromkeys(FIELDS))


def validate(value):
    if (type(value) is not dict or set(value) != {'version', 'status', 'refusal', *FIELDS}
            or type(value['version']) is not int or value['version'] != 1
            or type(value['status']) is not str or value['status'] not in ('observed', 'refused')
            or type(value['refusal']) is not str or value['refusal'] not in REFUSALS):
        fail('unavailable')
    if value['status'] == 'refused':
        if value['refusal'] == 'none' or any(value[k] is not None for k in FIELDS):
            fail('unavailable')
        return value
    if (value['refusal'] != 'none' or type(value['history_state']) is not str
            or value['history_state'] not in ('apply', 'rollback', 'restored')
            or type(value['last_apply_step']) is not str
            or value['last_apply_step'] not in ('none', *STEPS)
            or type(value['last_apply_step_state']) is not str
            or value['last_apply_step_state'] not in ('none', 'intent', 'done')
            or any(type(value[k]) is not bool for k in FIELDS[3:])):
        fail('unavailable')
    step, state = value['last_apply_step'], value['last_apply_step_state']
    index = -1 if step == 'none' else STEPS.index(step)
    if ((step == 'none') != (state == 'none')
            or value['rollback_done'] != (value['history_state'] == 'restored')
            or value['run_once_intent'] != (index >= 7)
            or value['run_once_done'] != (index > 7 or (index == 7 and state == 'done'))
            or value['observe_intent'] != (index == 8)
            or value['observe_done'] != (index == 8 and state == 'done')):
        fail('unavailable')
    return value


def closed_json(value):
    body = json.dumps(validate(value), sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False)
    if len(body.encode('ascii')) > 2048: fail('unavailable')
    return body


@contextmanager
def _modules(dependencies):
    if type(dependencies) is not dict or set(dependencies) != set(DEPENDENCY_PINS):
        fail('source_binding')
    for key, digest in DEPENDENCY_PINS.items():
        body = dependencies[key]
        if (type(body) is not bytes or len(body) != DEPENDENCY_SIZES[key]
                or hashlib.sha256(body).hexdigest() != digest):
            fail('source_binding')
    if 'transition' in sys.modules: fail('module_collision')
    transition = types.ModuleType('transition')
    journal = types.ModuleType('_fixed_readonly_journal')
    try:
        exec(compile(dependencies['transition'], '<pinned-transition>', 'exec'), transition.__dict__)
        sys.modules['transition'] = transition
        exec(compile(dependencies['journal'], '<pinned-journal>', 'exec'), journal.__dict__)
        if tuple(transition.STEPS) != STEPS: fail('source_binding')
        yield transition, journal
    finally:
        if sys.modules.get('transition') is transition: del sys.modules['transition']


class Budget:
    def __init__(self):
        self.end, self.used = time.monotonic() + SECONDS, 0
        self.fds = set()

    def tick(self):
        if time.monotonic() >= self.end: fail('deadline')

    def reserve(self, maximum):
        self.tick()
        if self.used + maximum > MAX_READ: fail('read_budget')


    @contextmanager
    def atomic_fds(self):
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        try: yield
        finally: signal.pthread_sigmask(signal.SIG_SETMASK, previous)

    def open(self, *args, **kwargs):
        self.tick()
        with self.atomic_fds():
            fd = os.open(*args, **kwargs)
            self.fds.add(fd)
            return fd

    def close(self, fd):
        with self.atomic_fds():
            os.close(fd)
            self.fds.discard(fd)

    def close_many(self, fds):
        with self.atomic_fds():
            for fd in fds:
                if fd in self.fds:
                    try: os.close(fd)
                    finally: self.fds.discard(fd)

    def finish(self):
        # No new descriptors are opened while this final cleanup is running.
        with self.atomic_fds():
            for fd in tuple(self.fds):
                try: os.close(fd)
                except OSError: pass
                finally: self.fds.discard(fd)

    def read(self, fd, size):
        self.tick()
        if self.used + size > MAX_READ: fail('read_budget')
        raw = os.read(fd, size)
        self.used += len(raw)
        self.tick()
        return raw


@contextmanager
def _deadline():
    if threading.current_thread() is not threading.main_thread(): fail('unsupported_host')
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0): fail('unsupported_host')
    budget = Budget()
    previous = signal.getsignal(signal.SIGALRM)
    def expired(_signum, _frame):
        fail('deadline')
    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, SECONDS)
        yield budget
    finally:
        try: signal.setitimer(signal.ITIMER_REAL, 0)
        finally:
            try: budget.finish()
            finally: signal.signal(signal.SIGALRM, previous)


def _ancestor(info):
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != OWNER or info.st_gid != GROUP
            or stat.S_IMODE(info.st_mode) & 0o022):
        fail('context_changed')


@contextmanager
def _directories(J, budget):
    """Keep descriptor and named identities; observations do not exclude privileged ABA."""
    held, opened = [], []
    try:
        current = Path('/')
        fd = budget.open(current, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
        opened.append(fd)
        held.append((current, fd, J.identity(os.fstat(fd))))
        _ancestor(os.fstat(fd))
        for name in ROOT.parts[1:]:
            budget.tick()
            current = current / name
            fd = budget.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=held[-1][1])
            opened.append(fd)
            held.append((current, fd, J.identity(os.fstat(fd))))
            _ancestor(os.fstat(fd))
        rootfd = held[-1][1]
        if stat.S_IMODE(os.fstat(rootfd).st_mode) != 0o700: fail('context_changed')
        for name in (APPLY, 'identities'):
            budget.tick()
            fd = budget.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=rootfd)
            opened.append(fd)
            held.append((ROOT / name, fd, J.identity(os.fstat(fd))))
            _ancestor(os.fstat(fd))
            if stat.S_IMODE(os.fstat(fd).st_mode) != 0o700: fail('context_changed')
        def check():
            for path, number, stamp in held:
                budget.tick()
                if J.identity(os.fstat(number)) != stamp or J.identity(path.lstat()) != stamp:
                    fail('context_changed')
        check()
        yield check
        check()
    finally:
        budget.close_many(reversed(opened))


def _bounded_inventory(path, maximum, budget):
    with os.scandir(path) as entries:
        for index, _entry in enumerate(entries, 1):
            budget.tick()
            if index > maximum: fail('ledger_rejected')


def _project(T, events, plan):
    mode = T.validate_history(events, plan)
    last, state = 'none', 'none'
    flags = dict(run_once_intent=False, run_once_done=False, observe_intent=False,
                 observe_done=False, apply_blocked=False, rollback_done=mode == 'restored')
    for event in events[1:]:
        action, event_state = event['action'], event['state']
        if action == 'rollback' and event_state == 'intent': break
        if action in STEPS: last, state = action, event_state
        if action in ('run_once', 'observe'): flags[action + '_' + event_state] = True
        if action == 'apply' and event_state == 'blocked': flags['apply_blocked'] = True
    return validate(dict(version=1, status='observed', refusal='none', history_state=mode,
                         last_apply_step=last, last_apply_step_state=state, **flags))


def _read(T, J, budget):
    def forbidden(*_args, **_kwargs): fail('ledger_rejected')
    class ReadonlyLedger(J.Ledger):
        lock = append = _reserve_ids = _atomic_new = _sync = forbidden
        def _file(self, path, *, links=(1,)):
            budget.reserve(J.MAX_FILE + 1)
            raw, info = J.Ledger._file(self, path, links=links)
            budget.tick()
            if info.st_gid != GROUP: fail('context_changed')
            return raw, info
        def _dir(self, path):
            budget.tick()
            return J.Ledger._dir(self, path)
    # Preserve pinned Journal code, adding ownership/deadline accounting at its
    # read-only syscall seam. In particular, an alarm after open but before the
    # original _file try/finally cannot lose the newly created descriptor.
    J.os = types.SimpleNamespace(open=budget.open, close=budget.close, read=budget.read,
        fstat=os.fstat, O_RDONLY=os.O_RDONLY, O_NOFOLLOW=os.O_NOFOLLOW, O_NONBLOCK=os.O_NONBLOCK)
    with _directories(J, budget) as check:
        lockpath = ROOT / 'transition.lock'
        try: before = lockpath.lstat()
        except FileNotFoundError: fail('lock_missing')
        def lockinfo(info):
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != OWNER or info.st_gid != GROUP
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size != 0):
                fail('lock_invalid')
        lockinfo(before)
        fd = budget.open(lockpath, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            lockinfo(os.fstat(fd))
            if J.identity(os.fstat(fd)) != J.identity(before): fail('context_changed')
            budget.tick()
            try: fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError: fail('lock_busy')
            if (J.identity(os.fstat(fd)) != J.identity(before)
                    or J.identity(lockpath.lstat()) != J.identity(before)):
                fail('context_changed')
            check()
            # Original unbound file reader needs only owner. No writer constructor/lock is used.
            reader = types.SimpleNamespace(owner=OWNER)
            planpath = ROOT / APPLY / 'plan.json'
            raw, planinfo = ReadonlyLedger._file(reader, planpath, links=(1, 2))
            plan = J.decode(raw)
            if (type(plan) is not dict or plan.get('apply_id') != APPLY
                    or plan.get('rollback_id') != ROLLBACK or T.sha(raw) != PLAN_SHA256):
                fail('plan_binding')
            ledger = ReadonlyLedger(ROOT, plan, owner=OWNER)
            ledger._fd, ledger._lock_identity = fd, J.identity(before)
            ledger._root_identity = ledger._dir(ROOT)[:2]
            _bounded_inventory(ledger.folder, J.MAX_EVENTS + J.MAX_ORPHANS + 1, budget)
            _bounded_inventory(ROOT / 'identities', J.MAX_EVENTS + J.MAX_ORPHANS, budget)
            events = J.Ledger.read(ledger, PLAN_SHA256)
            ledger._held()
            check()
            if J.identity(planpath.lstat()) != J.identity(planinfo): fail('context_changed')
            result = _project(T, events, plan)
            check()
            ledger._held()
            if J.identity(planpath.lstat()) != J.identity(planinfo): fail('context_changed')
            budget.tick()
            return result
        finally:
            budget.close(fd)


def observe(dependencies):
    """Only exact public code buffers accepted; target and IDs are immutable."""
    try:
        if sys.platform != 'linux' or os.geteuid() != 0: fail('unsupported_host')
        with _deadline() as budget:
            with _modules(dependencies) as (T, J):
                return _read(T, J, budget)
    except Refused as error:
        code = error.args[0] if len(error.args) == 1 and error.args[0] in REFUSALS else 'unavailable'
        return _blank(code)
    except Exception:
        return _blank('ledger_rejected')


if __name__ == '__main__':
    raise SystemExit('fixed_delivery_required')
