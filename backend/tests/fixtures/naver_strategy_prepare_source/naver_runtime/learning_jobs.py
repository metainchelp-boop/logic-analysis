"""Bounded Claude draft job metadata and one worker, without storage or network access."""
from datetime import datetime
import hashlib
import json
import re
import threading
from time import monotonic

PREFIX = 'learning-job:'
LIMIT = 100
ACTIVE = frozenset(('queued', 'running'))
TERMINAL = frozenset(('succeeded', 'failed', 'interrupted'))
FAILURES = frozenset(('context-changed', 'token-expired', 'job-interrupted', 'unknown',
    'timeout', 'tls', 'network', 'protocol', 'request-size', 'response-size', 'response-shape',
    'envelope-json', 'document-json', 'truncated', 'configuration', 'context-invalid',
    'document-invalid', 'numeric-citation-required', 'reference-unavailable', 'unconnected-evidence', 'http'))
FAILURE_PREFIX = 'learning-failure:'
FAILURE_STAGES = frozenset(('reserve', 'reserve-write', 'reserve-stop-check', 'reserve-clock',
    'reserve-fresh-authority', 'reserve-report-context', 'reserve-report-detail', 'reserve-approve-scope',
    'reserve-source-prepare', 'reserve-queued-proof', 'reserve-ledger', 'observation-bind',
    'invoke-wrapper', 'context-build', 'pre-invoke-guard', 'provider-invoke', 'document-validation', 'draft-save'))
FAILURE_CLASSES = frozenset(('store-busy', 'store-refused', 'store-error', 'sqlite-busy',
    'sqlite-error', 'provider-refused', 'authority-refused', 'internal'))


def failure_detail(value):
    """Optional bounded sidecar ABI. Never accept an exception name or text."""
    fields = {'stage', 'error_class', 'provider_invocation_attempted', 'observation_bound', 'observation_flushed'}
    if (type(value) is not dict or set(value) != fields or type(value['stage']) is not str
            or value['stage'] not in FAILURE_STAGES or type(value['error_class']) is not str
            or value['error_class'] not in FAILURE_CLASSES
            or type(value['provider_invocation_attempted']) is not bool
            or any(value[key] is not None and type(value[key]) is not bool
                   for key in ('observation_bound', 'observation_flushed'))):
        raise ValueError('LEARNING_FAILURE_INVALID')
    return dict(value)


def identity(actor, narrowed, report_id, account_key, fingerprint, version):
    return hashlib.sha256(json.dumps([actor, narrowed, report_id, account_key, fingerprint, version],
        separators=(',', ':')).encode()).hexdigest()


def clean(value):
    names = 'job_id actor narrowed report_id account_key revision_fingerprint expected_version expires_at proof_hash state created_at updated_at diagnostic result_version'
    if type(value) is not dict or set(value) != set(names.split()):
        raise ValueError('LEARNING_JOB_INVALID')
    for key, size in (('job_id', 32), ('account_key', 64), ('revision_fingerprint', 64), ('proof_hash', 64)):
        if type(value[key]) is not str or not re.fullmatch('[0-9a-f]{'+str(size)+'}', value[key]):
            raise ValueError('LEARNING_JOB_INVALID')
    if (type(value['actor']) is not int or not 0 <= value['actor'] < 2**63
            or type(value['narrowed']) is not bool or type(value['report_id']) is not int
            or not 0 < value['report_id'] < 2**63 or type(value['expected_version']) is not int
            or not 0 <= value['expected_version'] < 2**53 or value['state'] not in ACTIVE|TERMINAL):
        raise ValueError('LEARNING_JOB_INVALID')
    for key in ('expires_at', 'created_at', 'updated_at'):
        if type(value[key]) is not str or not 20 <= len(value[key]) <= 40:
            raise ValueError('LEARNING_JOB_INVALID')
        if datetime.fromisoformat(value[key]).utcoffset() is None:
            raise ValueError('LEARNING_JOB_INVALID')
    diagnostic = value['diagnostic']
    if diagnostic is not None:
        if (type(diagnostic) is not dict or set(diagnostic) != {'code', 'http_status'}
                or diagnostic['code'] not in FAILURES
                or (diagnostic['code'] == 'http' and (type(diagnostic['http_status']) is not int or not 100 <= diagnostic['http_status'] <= 599))
                or (diagnostic['code'] != 'http' and diagnostic['http_status'] is not None)):
            raise ValueError('LEARNING_JOB_INVALID')
    version = value['result_version']
    if (value['state'] == 'succeeded' and (type(version) is not int or not 0 < version < 2**53)) or (value['state'] != 'succeeded' and version is not None):
        raise ValueError('LEARNING_JOB_INVALID')
    if (value['state'] in ACTIVE|{'succeeded'} and diagnostic is not None) or (value['state'] in {'failed', 'interrupted'} and diagnostic is None):
        raise ValueError('LEARNING_JOB_INVALID')
    return value


def public(value):
    clean(value)
    return {key: value[key] for key in ('job_id', 'report_id', 'account_key', 'revision_fingerprint',
        'expected_version', 'state', 'created_at', 'updated_at', 'diagnostic', 'result_version')}


class Busy(Exception):
    pass


class LaunchFailed(Exception):
    pass


class Worker:
    """Serializes submission only; the provider never runs in this lock or a writer callback."""
    def __init__(self, gate, *, stopped=None, commit_lock=None):
        self.gate = gate
        self._lock = threading.Lock()
        self._commit_lock = commit_lock if commit_lock is not None else threading.Lock()
        self._external_stop = stopped or (lambda: False)
        self._thread = None
        self._stopped = threading.Event()
        self._started = False
        self._finalization_lock = threading.Lock()
        self._finalizations = {}
        self._job_threads = {}

    @property
    def stopped(self):
        return self._stopped.is_set() or self._external_stop()

    def record_finalization(self, job_id, *, acknowledged, error_class):
        if (type(job_id) is not str or not re.fullmatch('[0-9a-f]{32}', job_id)
                or type(acknowledged) is not bool
                or (acknowledged and error_class is not None)
                or (not acknowledged and (type(error_class) is not str or error_class not in FAILURE_CLASSES))):
            raise ValueError('LEARNING_FINALIZATION_INVALID')
        with self._finalization_lock:
            self._finalizations.pop(job_id, None)
            self._finalizations[job_id] = {'acknowledged': acknowledged, 'error_class': error_class}
            while len(self._finalizations) > LIMIT:
                self._finalizations.pop(next(iter(self._finalizations)))

    def finalization(self, job_id):
        with self._finalization_lock:
            value = self._finalizations.get(job_id)
            if value is None:
                return None
            thread = self._job_threads.get(job_id)
            return {'acknowledged': value['acknowledged'],
                'worker_alive': thread is not None and thread.is_alive(),
                'error_class': value['error_class']}

    def wait_finalization_retry(self, delay):
        # No writer callback or commit fence is held here. The existing stopped
        # callable ABI has no notification hook; check it at most every 50 ms.
        deadline = monotonic() + delay
        while not self.stopped:
            remaining = deadline - monotonic()
            if remaining <= 0:
                return True
            self._stopped.wait(min(remaining, .05))
        return False

    def start(self, recover):
        with self._lock:
            if not self._started:
                recover()
                self._started = True

    def submit(self, lookup, create, execute, recover, launch_failed):
        with self._lock:
            if self.stopped:
                raise Busy()
            if not self._started:
                recover(); self._started = True
            existing = lookup()
            if existing is not None:
                return existing
            if not self.gate.acquire(blocking=False):
                raise Busy()
            job = None
            try:
                job = create()
                with self._finalization_lock:
                    self._thread = threading.Thread(target=self._run, args=(execute, job),
                        name='naver-claude-draft', daemon=True)
                    self._job_threads[job['job_id']] = self._thread
                    while len(self._job_threads) > LIMIT:
                        expired = next(iter(self._job_threads))
                        self._job_threads.pop(expired)
                        self._finalizations.pop(expired, None)
                self._thread.start()
                return job
            except BaseException:
                self.gate.release()
                if job is not None:
                    launch_failed(job)
                    raise LaunchFailed() from None
                raise

    def commit(self, fn):
        # Writer callback owns this brief fence. Shutdown never waits on the writer while holding it.
        with self._commit_lock:
            if self.stopped:
                raise Busy()
            return fn()

    def _run(self, execute, job):
        try:
            if not self.stopped:
                execute(job)
        finally:
            self.gate.release()

    def close(self, interrupt):
        with self._lock:
            with self._commit_lock:
                self._stopped.set()
            if self._started:
                interrupt()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(1)
