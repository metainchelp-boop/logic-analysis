"""Read-only collection aggregates; no identity, amount or freeform error output."""
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import selectors
import subprocess
import time
from datetime import date, datetime, timedelta, timezone

STAGE = 'input'
CATALOG_LINKS_COMMIT = '6e4b035901027fef29266de218bfb0594227a3fe'
# These releases expose the same read-only diagnostics, including policy-aware target checks.
DAILY_LIMITED_COMMIT = '01344b145d0b679a6ee730d7fa4b5990278dd654'
RUNTIME_STATUS_COMMIT = '1b790b864ce27766251a205259fa6a332f60f72b'
MONITORING_COMMIT = '0a302856c6177c4f53145abaf9ed31b6a39654f3'
REPORTS_COMMIT = 'a38c53775c112cdf5db420f979093d6bee9e5376'
# Same diagnostics as REPORTS_COMMIT; live reads are allowed for this release.
SHM_LOCK_FIX_COMMIT = 'c21f5f05f610abf89df0c24e85c00b1bec23d01c'
# Same diagnostics and DB schema as SHM_LOCK_FIX_COMMIT; adds named owner writes on the screen only.
OWNER_ACTIONS_COMMIT = '8dd4292d82f5f98e7b4afa44a2a66b6770eaa505'
# Same diagnostics and DB schema as OWNER_ACTIONS_COMMIT; screen overhaul and display-only board fields.
SCREEN_OVERHAUL_COMMIT = 'a981b35e298aa58a52b30e266792bd0f36506c5d'
MONITORING_COMMITS = frozenset((MONITORING_COMMIT, REPORTS_COMMIT, SHM_LOCK_FIX_COMMIT, OWNER_ACTIONS_COMMIT,
                                SCREEN_OVERHAUL_COMMIT))
DAILY_LIMITED_COMMITS = frozenset((DAILY_LIMITED_COMMIT, RUNTIME_STATUS_COMMIT)) | MONITORING_COMMITS
CATALOG_LINKS_COMMITS = DAILY_LIMITED_COMMITS | frozenset((CATALOG_LINKS_COMMIT,))
PROJECTION_SOURCE = r'''
STAGES = frozenset(('진행중', '전략관리', '사후관리', '홀딩중', '재계약진행중', '환불중', '계약만료'))
PAIR_STATES = frozenset('confirmed auto missing broken blocked candidate superseded'.split())
CHECK_STATES = frozenset('ok pending not_checked partial key_rejected data_late system_gap link_broken not_eligible link_missing'.split())
REASONS = frozenset('campaigns-unread bizmoney-unread stats-unread avg-incomplete lock-unread period-unreadable data-late impressions-unknown yesterday-unknown baseline-insufficient stage-unknown stage-stale recent-unknown stage-time-unknown stage-time-in-future link-broken link-missing stage-not-monitored contract-ended end-unreadable'.split())
CODES = frozenset('ACCOUNTS_STEP_PENDING ACCOUNTS_UNUSABLE PAIRING_NOT_TODAY PAIRING_STALE DONE_TODAY RUN_RUNNING RUNS_EXHAUSTED RUN_ABORT KEY_REJECTED_ALL KEY_REJECTED_MANY DEADLINE_CUT SYSTEM_GAP NAVER_SHAPE_UNKNOWN PAIR_DUPLICATE UNLINK_MASS STORE_REFUSED HANDLE_INVALID DATA_LATE NAVER_UNAVAILABLE NOT_READY_LATE RUN_ORPHANED ACCOUNT_ERROR unexpected STORE_ERROR orphaned KEY_REJECTED RATE SERVER BAD_REQUEST NOT_FOUND NETWORK BAD_RESPONSE MISMATCH OTHER'.split())
UNKNOWN = 'UNRECOGNIZED'
PAIR_COUNTS = PAIR_STATES | {'prospects', 'ignored'}
COLLECTION_COUNTS = CHECK_STATES | frozenset('targets store_refused duplicate_skipped unlinked_issues deadline_left abort_left handle_invalid account_error'.split())
BOOTSTRAP_CODES = frozenset('REQUEST_FILE REQUEST_CHANGED REQUEST_SCHEMA REQUEST_EXPIRED HOLD_CHANGED_OR_EXPIRED HOLD_DIGEST_CHANGED HOLD_ROWS_CHANGED CURRENT_OWNER_REQUIRED SOURCES_NOT_TODAY SOURCES_UNUSABLE RESTRICTED_CONFIG_REQUIRED CONFIRM_REFUSED PAIRING_REFUSED INTERNAL_ERROR'.split())
JOB_STATES = frozenset('reading partial ok retry limited reauth_required source_wait'.split())
LIMITED_CODES = frozenset('REQUEST_DEADLINE REQUEST_CALL_CAP REQUEST_BUDGET RETRY_EXHAUSTED '
    'STATS_INCOMPLETE STATS_PERIOD_OPEN STATS_METRIC_MISSING STATS_METRIC_INVALID '
    'STATS_DATE_INCOMPLETE STATS_CYCLE_INVALID STATS_CYCLE_FUTURE STATS_CAMPAIGNS_INVALID '
    'CAMPAIGNS_CHANGED CHECKPOINT_INVALID SOURCE_AGGREGATING UNEXPECTED '
    'KEY_REJECTED RATE SERVER BAD_REQUEST NOT_FOUND NETWORK BAD_RESPONSE MISMATCH OTHER NO_ERROR_RECORDED'.split())
LIMITED_ATTEMPTS = frozenset(('0','1','2','3','4','FOUR_PLUS'))
LIMITED_UNKNOWN_HISTORY = frozenset(('REQUEST_DEADLINE','REQUEST_CALL_CAP','REQUEST_BUDGET',
                                   'UNRECOGNIZED','NO_ERROR_RECORDED','RETRY_EXHAUSTED'))
LIMITED_MAX_GROUPS = 100
LINK_REFUSALS = frozenset('scope_denied selection_denied permission_denied company_or_account_unavailable '
    'other_claim existing_decision legacy_stage_conflict legacy_end_unreadable stage-not-monitored '
    'stage-time-unknown stage-stale stage-time-in-future end-date-invalid ended-end-date-unknown ended-over-14-days'.split())
MORNING_STATES = frozenset(('reading', 'blocked', 'consumed'))
MORNING_KINDS = frozenset(('daily', 'summary'))
DIAGNOSTIC_STAGES = frozenset(('identity','reader','snapshot','core','catalog','daily','managed',
    'morning','reports','rollback','close','bootstrap','output','UNRECOGNIZED'))
DIAGNOSTIC_KINDS = frozenset(('ValueError','RuntimeError','TypeError','KeyError','AttributeError',
    'JSONDecodeError','PermissionError','FileNotFoundError','OSError','OperationalError',
    'DatabaseError','IntegrityError','ProgrammingError','InterfaceError','NotSupportedError',
    'DataError','InternalError','MemoryError','StoreError','StoreBusy','StoreRefused','UNRECOGNIZED'))
SQLITE_PRIMARY = {1:'SQLITE_ERROR',5:'SQLITE_BUSY',6:'SQLITE_LOCKED',8:'SQLITE_READONLY',
    9:'SQLITE_INTERRUPT',10:'SQLITE_IOERR',11:'SQLITE_CORRUPT',14:'SQLITE_CANTOPEN',
    15:'SQLITE_PROTOCOL',17:'SQLITE_SCHEMA',18:'SQLITE_TOOBIG',19:'SQLITE_CONSTRAINT',20:'SQLITE_MISMATCH',
    21:'SQLITE_MISUSE',23:'SQLITE_AUTH',26:'SQLITE_NOTADB'}


def diagnostic_failure(stage, error):
    kind = type(error).__name__
    primary = None
    cause = error
    for unused in range(3):
        if isinstance(cause, sqlite3.Error):
            code = getattr(cause, 'sqlite_errorcode', None)
            primary = SQLITE_PRIMARY.get(code & 255, 'UNRECOGNIZED') if type(code) is int else 'UNRECOGNIZED'
            break
        cause = getattr(cause, '__cause__', None) or getattr(cause, '__context__', None)
    return {'stage':stage if stage in DIAGNOSTIC_STAGES else 'UNRECOGNIZED',
            'error_kind':kind if kind in DIAGNOSTIC_KINDS else 'UNRECOGNIZED',
            'sqlite_primary':primary}


def diagnostic_projection(value):
    if not isinstance(value, dict) or set(value) != {'diagnostic_failure'}:
        raise ValueError('COLLECTION_DIAGNOSTIC')
    item = value['diagnostic_failure']
    if (not isinstance(item, dict) or set(item) != {'stage','error_kind','sqlite_primary'}
            or not isinstance(item['stage'], str) or item['stage'] not in DIAGNOSTIC_STAGES
            or not isinstance(item['error_kind'], str) or item['error_kind'] not in DIAGNOSTIC_KINDS
            or item['sqlite_primary'] not in (None, 'UNRECOGNIZED', *SQLITE_PRIMARY.values())):
        raise ValueError('COLLECTION_DIAGNOSTIC')
    return dict(item)


def bootstrap_empty(state):
    return {'available': False, 'state': state, 'phase': None, 'started_at': None,
            'finished_at': None, 'accepted_rows': None, 'pairing_outcome': None,
            'collection_outcome': None, 'pairing_counts': {}, 'collection_counts': {}, 'codes': [], 'error_code': None}


def safe_counts(value, allowed):
    if not isinstance(value, dict):
        raise ValueError('BOOTSTRAP_COUNTS')
    return {key: number(n) for key, n in value.items() if key in allowed}


def bootstrap_projection(value):
    if not isinstance(value, dict) or set(value) != set(bootstrap_empty('not_checked')):
        raise ValueError('BOOTSTRAP_FIELDS')
    if (type(value['available']) is not bool or value['state'] not in
            ('not_checked', 'no_request', 'not_started', 'started_without_result', 'completed', 'partial', 'failed_partial')
            or value['phase'] not in (None, 'preflight', 'snapshot', 'pairing', 'collection', 'finished')
            or value['pairing_outcome'] not in (None, 'accepted', 'refused', 'failed')
            or value['collection_outcome'] not in (None, 'done', 'failed', 'refused')
            or not isinstance(value['codes'], list) or len(value['codes']) > 100):
        raise ValueError('BOOTSTRAP_STATE')
    return dict(value, started_at=stamp(value['started_at']), finished_at=stamp(value['finished_at']),
                accepted_rows=number(value['accepted_rows'], True),
                pairing_counts=counts(value['pairing_counts'], PAIR_COUNTS),
                collection_counts=counts(value['collection_counts'], COLLECTION_COUNTS),
                error_code=None if value['error_code'] is None else enum(value['error_code'], BOOTSTRAP_CODES),
                codes=sorted({enum(code, CODES) for code in value['codes']}))


def project_bootstrap(started, result):
    if not isinstance(started, dict) or started.get('status') != 'started' or started.get('phase') != 'preflight':
        raise ValueError('BOOTSTRAP_STARTED')
    out = dict(bootstrap_empty('started_without_result'), available=True,
               phase='preflight', started_at=stamp(started.get('started_at')))
    if out['started_at'] is None:
        raise ValueError('BOOTSTRAP_TIME')
    if result is not None:
        if not isinstance(result, dict) or result.get('status') not in ('completed', 'partial', 'failed_partial'):
            raise ValueError('BOOTSTRAP_RESULT')
        for key in ('request_id', 'hold_id', 'expected_rows', 'approved_by'):
            if type(result.get(key)) is not type(started.get(key)) or result.get(key) != started.get(key):
                raise ValueError('BOOTSTRAP_IDENTITY')
        out.update(state=result['status'], phase=result.get('phase'), finished_at=stamp(result.get('finished_at')),
                   accepted_rows=number(result.get('accepted_rows'), True), pairing_outcome=result.get('pairing_outcome'),
                   collection_outcome=result.get('collection_outcome'),
                   pairing_counts=safe_counts(result.get('pairing_counts', {}), PAIR_COUNTS),
                   collection_counts=safe_counts(result.get('collection_counts', {}), COLLECTION_COUNTS),
                   codes=result.get('codes', []), error_code=result.get('error_code'))
        if out['finished_at'] is None:
            raise ValueError('BOOTSTRAP_TIME')
    return bootstrap_projection(out)


def read_bootstrap(request=Path('/var/lib/naver-engine/bootstrap-request.json'),
                   directory=Path('/var/lib/naver-engine/bootstrap'), *, request_uid=0, runtime_uid=10001, gid=10001):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('BOOTSTRAP_JSON')
            out[key] = value
        return out
    def read(path, uid, mode):
        if path.resolve() != path:
            raise ValueError('BOOTSTRAP_PATH')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or (before.st_uid, before.st_gid,
                    stat.S_IMODE(before.st_mode), before.st_nlink) != (uid, gid, mode, 1)
                    or not 0 < before.st_size <= 4096):
                raise ValueError('BOOTSTRAP_FILE')
            raw = os.read(fd, 4097)
            stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns,
                               s.st_uid, s.st_gid, s.st_mode, s.st_nlink)
            if stamp(before) != stamp(os.fstat(fd)) or stamp(before) != stamp(path.lstat()) or len(raw) != before.st_size:
                raise ValueError('BOOTSTRAP_CHANGED')
            value = json.loads(raw, object_pairs_hook=unique)
            if not isinstance(value, dict):
                raise ValueError('BOOTSTRAP_JSON')
            return value
        finally:
            os.close(fd)
    try:
        req = read(request, request_uid, 0o440)
    except FileNotFoundError:
        return bootstrap_empty('no_request')
    if (set(req) != {'request_id', 'hold_id', 'hold_sha256', 'expected_rows', 'approved_by', 'expires_at', 'max_seconds'}
            or not isinstance(req['request_id'], str) or not re.fullmatch('[0-9a-f]{32}', req['request_id'])
            or not isinstance(req['hold_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', req['hold_sha256'])
            or type(req['approved_by']) is not int or req['approved_by'] != 0
            or not 1 <= number(req['hold_id']) < 2**63 or not 1 <= number(req['expected_rows']) <= 100000
            or not 1 <= number(req['max_seconds']) <= 600 or stamp(req['expires_at']) is None):
        raise ValueError('BOOTSTRAP_REQUEST')
    if directory.resolve() != directory:
        raise ValueError('BOOTSTRAP_PATH')
    try:
        st = directory.lstat()
    except FileNotFoundError:
        return bootstrap_empty('not_started')
    if not stat.S_ISDIR(st.st_mode) or (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)) != (runtime_uid, gid, 0o700):
        raise ValueError('BOOTSTRAP_DIRECTORY')
    stem = 'bootstrap-' + req['request_id']
    try:
        started = read(directory/(stem+'.json'), runtime_uid, 0o600)
    except FileNotFoundError:
        if os.path.lexists(directory/(stem+'.result.json')):
            raise ValueError('BOOTSTRAP_ORPHAN_RESULT')
        return bootstrap_empty('not_started')
    for key in ('request_id', 'hold_id', 'expected_rows', 'approved_by'):
        if type(started.get(key)) is not type(req[key]) or started.get(key) != req[key]:
            raise ValueError('BOOTSTRAP_IDENTITY')
    try:
        result = read(directory/(stem+'.result.json'), runtime_uid, 0o600)
    except FileNotFoundError:
        result = None
    return project_bootstrap(started, result)


def number(value, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not int or not 0 <= value <= 2**63-1:
        raise ValueError('COLLECTION_COUNT')
    return value


def stamp(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.isoformat()
    except (TypeError, ValueError):
        raise ValueError('COLLECTION_TIME') from None


def enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else UNKNOWN


def grouped(rows, allowed):
    result = {}
    for key, n in rows:
        key = enum(key, allowed)
        result[key] = result.get(key, 0) + number(n)
    return result


def counts(value, allowed):
    if not isinstance(value, dict) or set(value) - (allowed | {UNKNOWN}):
        raise ValueError('COLLECTION_COUNTS')
    return {key: number(n) for key, n in value.items()}


def management_windows(today, schema=10):
    day = date.fromisoformat(today)
    sunday = day-timedelta(days=(day.weekday()+1) % 7)
    result = {'daily': (day, day, 'all'), 'weekly': (sunday, sunday, 'all'),
              'backfill_recent': (day-timedelta(days=39), day, 'unfinished')}
    if schema == 11:
        # 목적을 합치지 않고 고정 40일 회차창으로 자정/요일 이월 대기도 보인다.
        result.update({kind: (day-timedelta(days=39), day, 'all') for kind in
                       ('recent', 'reconcile', 'report_weekly', 'report_monthly', 'manual', 'manual_period')})
    return result


def management_projection(value, today):
    if value is None:
        return None
    fields = {'schema_version', 'jobs', 'daily_rows', 'report_count', 'stored_totals_scope',
              'target_count', 'target_count_reason', 'counts_are_jobs_not_targets'}
    if (not isinstance(value, dict) or set(value) != fields or type(value['schema_version']) is not int
            or value['schema_version'] not in (10, 11) or value['target_count'] is not None
            or value['target_count_reason'] != 'CURRENT_ELIGIBILITY_NOT_EVALUATED'
            or value['counts_are_jobs_not_targets'] is not True
            or value['stored_totals_scope'] != 'all_stored_rows'
            or not isinstance(value['jobs'], dict)
            or set(value['jobs']) != set(management_windows(today, value['schema_version']))):
        raise ValueError('COLLECTION_MANAGEMENT')
    jobs = {}
    for kind, (since, until, status_scope) in management_windows(today, value['schema_version']).items():
        row = value['jobs'][kind]
        if (not isinstance(row, dict) or set(row) != {'since_cycle_day', 'until_cycle_day', 'status_scope',
                'statuses', 'latest_checked_at', 'latest_success_at'}
                or row['since_cycle_day'] != str(since) or row['until_cycle_day'] != str(until)
                or row['status_scope'] != status_scope):
            raise ValueError('COLLECTION_MANAGEMENT')
        statuses = counts(row['statuses'], JOB_STATES)
        if status_scope == 'unfinished' and 'ok' in statuses:
            raise ValueError('COLLECTION_MANAGEMENT')
        jobs[kind] = dict(row, statuses=statuses, latest_checked_at=stamp(row['latest_checked_at']),
                         latest_success_at=stamp(row['latest_success_at']))
    return dict(value, jobs=jobs, daily_rows=number(value['daily_rows']), report_count=number(value['report_count']))


def collect_management(connection, today):
    row = connection.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()
    schema = None if row is None else row[0]
    if schema in ('7', '8', '9'):
        return None
    if schema not in ('10', '11'):
        raise ValueError('COLLECTION_SCHEMA')
    jobs = {}
    states = tuple(sorted(JOB_STATES))
    marks = ','.join('?' for _ in states)
    for kind, (since, until, status_scope) in management_windows(today, int(schema)).items():
        args = ('backfill' if kind == 'backfill_recent' else kind, str(since), str(until))
        where = 'kind=? AND cycle_day>=? AND cycle_day<=?'
        latest = connection.execute('SELECT MAX(checked_at),MAX(COALESCE(last_success_at,CASE WHEN status=\'ok\' THEN checked_at END)) '
                                    'FROM naver_auto_performance_job WHERE '+where, args).fetchone()
        if status_scope == 'unfinished':
            where += " AND status!='ok'"
        # Collapse unknown status strings in SQL so distinct untrusted values cannot grow the output.
        rows = connection.execute('SELECT CASE WHEN status IN ('+marks+") THEN status ELSE 'UNRECOGNIZED' END,"
            'COUNT(*) FROM naver_auto_performance_job WHERE '+where+' GROUP BY 1', states+args)
        jobs[kind] = {'since_cycle_day':str(since), 'until_cycle_day':str(until), 'status_scope':status_scope,
                      'statuses':grouped(rows, JOB_STATES), 'latest_checked_at':latest[0], 'latest_success_at':latest[1]}
    return management_projection({'schema_version':int(schema), 'jobs':jobs,
        'daily_rows':connection.execute('SELECT COUNT(*) FROM naver_auto_daily_performance').fetchone()[0],
        'report_count':connection.execute('SELECT COUNT(*) FROM naver_auto_report_snapshot').fetchone()[0],
        'stored_totals_scope':'all_stored_rows', 'target_count':None,
        'target_count_reason':'CURRENT_ELIGIBILITY_NOT_EVALUATED', 'counts_are_jobs_not_targets':True}, today)


def catalog_link_projection(value):
    if (not isinstance(value, dict) or set(value) != {'auto', 'name_different', 'can_confirm', 'rejected'}
            or not isinstance(value['rejected'], dict) or set(value['rejected']) - LINK_REFUSALS):
        raise ValueError('CATALOG_LINK_FIELDS')
    out = {key:number(value[key]) for key in ('auto', 'name_different', 'can_confirm')}
    out['rejected'] = {key:number(n) for key,n in value['rejected'].items()}
    if out['auto'] + out['name_different'] != out['can_confirm'] + sum(out['rejected'].values()):
        raise ValueError('CATALOG_LINK_COUNTS')
    return out


def catalog_link_counts(context, rules, *, managed_stages=None):
    """First refusing gate, checked against the pinned product's actual allowed result."""
    if context is None or context.source_state != 'accepted':
        raise ValueError('CATALOG_LINK_SOURCE')
    ctx, scope = context.ctx, context.scope
    out = {'auto':0, 'name_different':0, 'can_confirm':0, 'rejected':{}}
    for pid in sorted(context.visible_ids):
        if managed_stages is not None:
            company = context.companies.get(pid)
            if (not company or company.get('stage_known') is not True or company.get('stage_hidden') is not False
                    or not isinstance(company.get('stage'), str)
                    or ''.join(company['stage'].split()) not in managed_stages):
                continue
        for row in ctx.rows_by_pid.get(pid, ()):
            kind = 'auto' if row['state'] == 'auto' else 'name_different' if (
                row['state'] == 'blocked' and row['code'] == 'name-different') else None
            if kind is None:
                continue
            out[kind] += 1
            pid, cid = row['possibility_id'], row['customer_id']
            own, company, account = ctx.owns.get(pid), context.companies.get(pid), ctx.accounts.get(cid)
            legacy = ctx.prospects.get(pid)
            reason = None
            if callable(getattr(rules, 'block_reason', None)):
                # New products own the identity policy. Do not replay removed handle/stage gates.
                native = rules.block_reason(context, row)
                reasons = {'confirmation-not-permitted': 'scope_denied' if scope.kind not in
                           (rules.SC.ALL, rules.SC.MINE) else 'selection_denied' if pid not in
                           context.visible_ids else 'permission_denied',
                           'company-stage-unavailable':'company_or_account_unavailable',
                           'company-unavailable':'company_or_account_unavailable',
                           'account-unavailable':'company_or_account_unavailable',
                           'account-claimed-elsewhere':'other_claim', 'pair-already-decided':'existing_decision',
                           'contract-stage-conflict':'legacy_stage_conflict',
                           'contract-end-unreadable':'legacy_end_unreadable'}
                reason = reasons.get(native, native)
            elif scope.kind not in (rules.SC.ALL, rules.SC.MINE):
                reason = 'scope_denied'
            elif pid not in context.visible_ids:
                reason = 'selection_denied'
            elif own is None or rules.SC.ACT_CONFIRM_LINK not in rules.SC.allowed_actions(ctx.org, scope, own):
                reason = 'permission_denied'
            elif not company or company['stage_hidden'] or not company['stage_known'] or not account or account['present'] != 1:
                reason = 'company_or_account_unavailable'
            elif rules.W.link_holders(ctx, pid, cid) or row.get('claimed_elsewhere'):
                reason = 'other_claim'
            elif any(d.possibility_id == pid and d.customer_id == cid for d in ctx.live_decisions):
                reason = 'existing_decision'
            elif legacy is not None and legacy['stage_conflict']:
                reason = 'legacy_stage_conflict'
            elif legacy is not None and legacy['end_unreadable']:
                reason = 'legacy_end_unreadable'
            else:
                end = None if legacy is None or legacy['latest_end_date'] is None else date.fromisoformat(legacy['latest_end_date'])
                reason = rules.H.eligibility_reason(company['stage'], context.catalog_at, end, ctx.now)
            if (reason is not None and reason not in LINK_REFUSALS) or rules.allowed(context, row) != (reason is None):
                raise ValueError('CATALOG_LINK_RULE_MISMATCH')
            if reason is None:
                out['can_confirm'] += 1
            else:
                out['rejected'][reason] = out['rejected'].get(reason, 0) + 1
    return catalog_link_projection(out)


def collect_catalog_links(store, now, *, managed_only=False):
    from naver_engine import catalog_links as CL
    from naver_engine import management as MP
    if store.meta('schema_version') != '11':
        raise ValueError('COLLECTION_SCHEMA')
    org = CL.W.load_org(store)
    scope = CL.SC.scope_of(org, 0)
    if scope.kind != CL.SC.ALL:
        raise ValueError('CATALOG_LINK_SCOPE')
    return catalog_link_counts(CL.load(store, now, org, scope, 'all', narrowed=False), CL,
                               managed_stages=MP.DAILY_STAGES if managed_only else None)


def daily_limited_projection(value, today):
    fields = {'cycle_day','jobs','current_daily_targets','current_target_rule','groups'}
    if (not isinstance(value, dict) or set(value) != fields or value['cycle_day'] != today
            or value['current_target_rule'] != 'DAILY_CADENCE_AND_SAME_ATTRIBUTION_NOT_RETRY_PERMISSION'
            or not isinstance(value['groups'], list) or len(value['groups']) > LIMITED_MAX_GROUPS):
        raise ValueError('COLLECTION_LIMITED_FIELDS')
    if number(value['jobs']) > 100000 or number(value['current_daily_targets']) > 100000:
        raise ValueError('COLLECTION_LIMITED_SIZE')
    seen, total, current = set(), 0, 0
    for row in value['groups']:
        if (not isinstance(row, dict) or set(row) != {'error_code','attempts','current_target','prior_error_evidence','jobs'}
                or not isinstance(row['error_code'], str) or row['error_code'] not in LIMITED_CODES | {UNKNOWN}
                or not isinstance(row['attempts'], str) or row['attempts'] not in LIMITED_ATTEMPTS
                or type(row['current_target']) is not bool
                or row['prior_error_evidence'] != ('UNKNOWN_NOT_RECORDED' if row['error_code'] in
                    LIMITED_UNKNOWN_HISTORY else 'NOT_APPLICABLE')):
            raise ValueError('COLLECTION_LIMITED_FIELDS')
        key = (row['error_code'],row['attempts'],row['current_target'])
        if key in seen or number(row['jobs']) == 0:
            raise ValueError('COLLECTION_LIMITED_COUNTS')
        seen.add(key)
        total += row['jobs']
        current += row['jobs'] if row['current_target'] else 0
    if total != value['jobs'] or current > value['current_daily_targets']:
        raise ValueError('COLLECTION_LIMITED_COUNTS')
    return value


def collect_daily_limited(connection, today, decisions):
    """Stored last codes only; current membership never grants a retry or reconstructs history."""
    row = connection.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()
    if row is None or row[0] != '11':
        raise ValueError('COLLECTION_SCHEMA')
    if not isinstance(decisions, dict) or not decisions:
        raise ValueError('COLLECTION_LIMITED_SOURCE')
    targets = {}
    for cid, decision in decisions.items():
        if (not isinstance(decision, dict) or decision.get('source_current') is not True
                or getattr(decision.get('decision'), 'cadence', None) not in ('daily','weekly','blocked')):
            raise ValueError('COLLECTION_LIMITED_SOURCE')
        if decision['decision'].cadence == 'daily':
            if (type(cid) is not int or cid <= 0 or type(decision.get('possibility_id')) is not int
                    or decision['possibility_id'] <= 0 or not isinstance(decision.get('stage_revision'), str)
                    or not decision['stage_revision']):
                raise ValueError('COLLECTION_LIMITED_SOURCE')
            targets[cid] = (decision['stage_revision'],decision['possibility_id'])
    groups, total, current_seen = {}, 0, set()
    rows = connection.execute("SELECT customer_id,stage_revision,possibility_id,error_code,attempts "
        "FROM naver_auto_performance_job WHERE kind='daily' AND cycle_day=? AND status='limited' LIMIT 100001", (today,))
    for cid, revision, pid, code, attempts in rows:
        total += 1
        if total > 100000:
            raise ValueError('COLLECTION_LIMITED_SIZE')
        code = 'NO_ERROR_RECORDED' if code is None else enum(code, LIMITED_CODES)
        attempts = number(attempts)
        bucket = str(attempts) if attempts <= 4 else 'FOUR_PLUS'
        current = cid in targets and targets[cid] == (revision,pid)
        if current:
            if cid in current_seen:
                raise ValueError('COLLECTION_LIMITED_COUNTS')
            current_seen.add(cid)
        key = (code,bucket,current)
        groups[key] = groups.get(key,0) + 1
        if len(groups) > LIMITED_MAX_GROUPS:
            raise ValueError('COLLECTION_LIMITED_SIZE')
    return daily_limited_projection({'cycle_day':today,'jobs':total,'current_daily_targets':len(targets),
        'current_target_rule':'DAILY_CADENCE_AND_SAME_ATTRIBUTION_NOT_RETRY_PERMISSION',
        'groups':[dict(error_code=code,attempts=attempts,current_target=current,jobs=count,
            prior_error_evidence='UNKNOWN_NOT_RECORDED' if code in LIMITED_UNKNOWN_HISTORY else 'NOT_APPLICABLE')
            for (code,attempts,current),count in sorted(groups.items())]}, today)


def morning_progress_projection(value, today):
    if (not isinstance(value, dict) or set(value) != {'day','scope','states','current_chunks'}
            or value['day'] != today or value['scope'] != 'today_current_generation_not_run_completion'
            or not isinstance(value['states'], dict) or set(value['states']) - (MORNING_STATES | {UNKNOWN})):
        raise ValueError('COLLECTION_MORNING')
    states = {}
    for state, row in value['states'].items():
        if not isinstance(row, dict) or set(row) != {'accounts','payload_bytes'}:
            raise ValueError('COLLECTION_MORNING')
        states[state] = dict(accounts=number(row['accounts']),payload_bytes=number(row['payload_bytes']))
    return dict(value, states=states, current_chunks=counts(value['current_chunks'], MORNING_KINDS))


def collect_morning_progress(connection, today):
    schema = connection.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()
    if schema is None or schema[0] != '11':
        raise ValueError('COLLECTION_MORNING_SCHEMA')
    states = {}
    for state, accounts, size, invalid in connection.execute(
            "SELECT CASE WHEN status IN ('reading','blocked','consumed') THEN status ELSE 'UNRECOGNIZED' END,"
            "COUNT(*),SUM(payload_bytes),SUM(CASE WHEN typeof(payload_bytes)!='integer' OR payload_bytes<0 "
            "THEN 1 ELSE 0 END) FROM naver_auto_morning_progress WHERE day=? GROUP BY 1", (today,)):
        if invalid:
            raise ValueError('COLLECTION_MORNING_BYTES')
        states[state] = dict(accounts=number(accounts),payload_bytes=number(size))
    # Stored checkpoints only: neither eligibility nor completed accounts are inferred from these states.
    chunks = dict(connection.execute(
        "SELECT CASE WHEN c.kind IN ('daily','summary') THEN c.kind ELSE 'UNRECOGNIZED' END,COUNT(*) "
        "FROM naver_auto_morning_chunk c JOIN naver_auto_morning_progress p "
        "ON p.customer_id=c.customer_id AND p.generation=c.generation "
        "WHERE p.day=? AND c.body IS NOT NULL GROUP BY 1", (today,)))
    return morning_progress_projection(dict(day=today,scope='today_current_generation_not_run_completion',
                                           states=states,current_chunks=chunks), today)


def reports_projection(value):
    if not isinstance(value, dict) or set(value) != {'weekly','monthly'}:
        raise ValueError('COLLECTION_REPORTS')
    result = {}
    for kind, row in value.items():
        if (not isinstance(row, dict) or set(row) != {'period_key','latest_company_reports','versions','latest_generated_at'}
                or not isinstance(row['versions'], dict) or set(row['versions']) != {'v1','v2','unknown'}):
            raise ValueError('COLLECTION_REPORTS')
        total = number(row['latest_company_reports'])
        versions = {key:number(n) for key,n in row['versions'].items()}
        latest = stamp(row['latest_generated_at'])
        key = row['period_key']
        if sum(versions.values()) != total or (total == 0) != (key is None and latest is None):
            raise ValueError('COLLECTION_REPORTS')
        if total:
            if (latest is None or not isinstance(key, str) or not re.fullmatch(
                    kind+r':[0-9]{4}-[0-9]{2}-[0-9]{2}:[0-9]{4}-[0-9]{2}-[0-9]{2}', key)):
                raise ValueError('COLLECTION_REPORTS')
            try:
                start, end = [date.fromisoformat(part) for part in key.split(':')[1:]]
                valid = (start.weekday() == 0 and end-start == timedelta(days=6)) if kind == 'weekly' else (
                    start.day == 1 and (start.year,start.month) == (end.year,end.month) and
                    (end+timedelta(days=1)).day == 1)
                if not valid:
                    raise ValueError()
            except (ValueError, OverflowError):
                raise ValueError('COLLECTION_REPORTS') from None
        result[kind] = dict(row, latest_company_reports=total, versions=versions, latest_generated_at=latest)
    return result


def collect_reports(connection):
    """주·월별 최신 저장 기간의 업체별 최신 판만 센다. 내용·식별자는 내보내지 않는다."""
    result = {}
    for kind in ('weekly','monthly'):
        key = connection.execute('SELECT MAX(period_key) FROM naver_auto_report_snapshot WHERE period_key LIKE ?',
                                 (kind+':%',)).fetchone()[0]
        row = dict(period_key=key,latest_company_reports=0,versions=dict(v1=0,v2=0,unknown=0),latest_generated_at=None)
        if key is not None:
            rows = connection.execute("""WITH latest AS (
                SELECT MAX(report_id) AS report_id FROM naver_auto_report_snapshot
                WHERE period_key=? GROUP BY possibility_id)
                SELECT CASE WHEN json_valid(r.payload_json) THEN
                    CASE WHEN json_type(r.payload_json)='object' THEN
                        CASE WHEN json_type(r.payload_json,'$.format_version') IS NULL THEN 'v1'
                             WHEN json_type(r.payload_json,'$.format_version')='integer' AND
                                  json_extract(r.payload_json,'$.format_version')=1 THEN 'v1'
                             WHEN json_type(r.payload_json,'$.format_version')='integer' AND
                                  json_extract(r.payload_json,'$.format_version')=2 THEN 'v2'
                             ELSE 'unknown' END
                        ELSE 'unknown' END ELSE 'unknown' END AS version,
                    COUNT(*),MAX(r.generated_at)
                FROM naver_auto_report_snapshot r JOIN latest l ON l.report_id=r.report_id GROUP BY 1""", (key,))
            for version, count, latest in rows:
                row['versions'][version] = number(count)
                row['latest_company_reports'] += count
                checked = stamp(latest)
                if checked is None:
                    raise ValueError('COLLECTION_REPORTS')
                if row['latest_generated_at'] is None or checked > row['latest_generated_at']:
                    row['latest_generated_at'] = checked
        result[kind] = row
    return reports_projection(result)


def project(value):
    fields = {'today', 'prospects', 'pairing', 'latest_run', 'today_checks', 'bootstrap'}
    if (not isinstance(value, dict) or not fields <= set(value)
            or set(value) - fields - {'management','catalog_links','daily_limited','managed_catalog_links','morning_progress','reports'}):
        raise ValueError('COLLECTION_FIELDS')
    today = value['today']
    if not isinstance(today, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', today):
        raise ValueError('COLLECTION_DAY')
    date.fromisoformat(today)
    p, pair, checks = value['prospects'], value['pairing'], value['today_checks']
    if (not isinstance(p, dict) or set(p) != {'total', 'stages'} or
            not isinstance(pair, dict) or set(pair) != {'available', 'statuses', 'unmatched_prospects'} or
            type(pair['available']) is not bool or not isinstance(checks, dict) or
            set(checks) != {'statuses', 'reasons'}):
        raise ValueError('COLLECTION_FIELDS')
    run = value['latest_run']
    if run is not None:
        if not isinstance(run, dict) or set(run) != {'status', 'started_at', 'finished_at', 'targets', 'complete', 'codes'}:
            raise ValueError('COLLECTION_RUN')
        if run['status'] not in ('running', 'done', 'failed') or not isinstance(run['codes'], list) or len(run['codes']) > 20:
            raise ValueError('COLLECTION_RUN')
        run = {'status': run['status'], 'started_at': stamp(run['started_at']),
               'finished_at': stamp(run['finished_at']), 'targets': number(run['targets'], True),
               'complete': number(run['complete'], True),
               'codes': sorted({enum(code, CODES) for code in run['codes']})}
        if run['started_at'] is None:
            raise ValueError('COLLECTION_TIME')
    bootstrap = bootstrap_projection(value['bootstrap'])
    result = {'today': today, 'prospects': {'total': number(p['total']), 'stages': counts(p['stages'], STAGES)},
            'pairing': {'available': pair['available'], 'statuses': counts(pair['statuses'], PAIR_STATES),
                        'unmatched_prospects': number(pair['unmatched_prospects'], True)},
            'latest_run': run, 'today_checks': {'statuses': counts(checks['statuses'], CHECK_STATES),
                                               'reasons': counts(checks['reasons'], REASONS)},
            'bootstrap': bootstrap}
    if 'management' in value:
        result['management'] = management_projection(value['management'], today)
    if 'catalog_links' in value:
        result['catalog_links'] = catalog_link_projection(value['catalog_links'])
    if 'daily_limited' in value:
        result['daily_limited'] = daily_limited_projection(value['daily_limited'], today)
    if 'managed_catalog_links' in value:
        result['managed_catalog_links'] = catalog_link_projection(value['managed_catalog_links'])
    if 'morning_progress' in value:
        result['morning_progress'] = morning_progress_projection(value['morning_progress'], today)
    if 'reports' in value:
        result['reports'] = reports_projection(value['reports'])
    return result


def collect(store, today):
    c = store._conn
    scalar = lambda sql, args=(): c.execute(sql, args).fetchone()[0]
    pairing = "(SELECT MAX(pairing_id) FROM naver_auto_pairing_run WHERE outcome='accepted')"
    available = bool(scalar("SELECT COUNT(*) FROM naver_auto_pairing_run WHERE outcome='accepted'"))
    statuses = grouped(c.execute('SELECT state,COUNT(*) FROM naver_auto_pairing_row WHERE pairing_id='+pairing+' GROUP BY state'), PAIR_STATES)
    unmatched = scalar('SELECT COUNT(*) FROM naver_auto_prospect p WHERE present=1 AND NOT EXISTS (SELECT 1 FROM naver_auto_pairing_row r WHERE r.pairing_id='+pairing+' AND r.possibility_id=p.possibility_id)') if available else None
    run = c.execute('SELECT status,started_at,finished_at,accounts_total,accounts_ok,error_kind FROM naver_auto_check_run WHERE run_date=? ORDER BY run_id DESC LIMIT 1', (today,)).fetchone()
    latest = None if run is None else dict(zip(('status','started_at','finished_at','targets','complete'), run[:5]), codes=[] if run[5] is None else [enum(run[5], CODES)])
    reasons = {}
    for (raw,) in c.execute('SELECT rules_not_run FROM naver_auto_account_day WHERE day=?', (today,)):
        missing = json.loads(raw)
        if not isinstance(missing, list) or len(missing) > 100:
            raise ValueError('COLLECTION_REASONS')
        seen = set()
        for entry in missing:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ValueError('COLLECTION_REASONS')
            seen.add(enum(entry[1], REASONS))
        for reason in seen:
            reasons[reason] = reasons.get(reason, 0) + 1
    return project({'today': today,
        'prospects': {'total': scalar('SELECT COUNT(*) FROM naver_auto_prospect WHERE present=1'),
                      'stages': grouped(c.execute('SELECT stage_key,COUNT(*) FROM naver_auto_prospect WHERE present=1 GROUP BY stage_key'), STAGES)},
        'pairing': {'available': available, 'statuses': statuses, 'unmatched_prospects': unmatched},
        'latest_run': latest,
        'today_checks': {'statuses': grouped(c.execute('SELECT status,COUNT(*) FROM naver_auto_account_day WHERE day=? GROUP BY status', (today,)), CHECK_STATES), 'reasons': reasons},
        'bootstrap': bootstrap_empty('not_checked'), 'management': collect_management(c, today)})
'''
exec(compile(PROJECTION_SOURCE, '<collection-projection>', 'exec'))

def validate_package(package):
    required = {'baseline', 'source_commit', 'source_tar_gz_sha256'}
    if (not isinstance(package, dict) or set(package) not in (required,required|{'passive_runtime_only'})
            or ('passive_runtime_only' in package and package['passive_runtime_only'] is not True)):
        raise ValueError('PACKAGE_FIELDS')
    for key, value in package.items():
        if key == 'passive_runtime_only':
            continue
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}' if key == 'source_commit' else '[0-9a-f]{64}', value):
            raise ValueError('PACKAGE_SHAPE')


def script(*, catalog_links=False, daily_limited=False, morning_progress=False, reports=False):
    parts = ['import json,os,sys,stat,re,time,sqlite3\nfrom pathlib import Path\nfrom datetime import date,datetime,timedelta,timezone\n', PROJECTION_SOURCE]
    parts.append("""
diagnostic_stage='identity'
failure=None
try:
    if os.geteuid()!=10001:
        raise ValueError('READER_IDENTITY')
    os.environ.clear()
    sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
    diagnostic_stage='reader'
    from naver_engine import store as S
    reader=S.open_reader('/var/lib/naver-engine/engine.db')
    try:
        diagnostic_stage='snapshot'
        deadline=time.monotonic()+20
        reader._conn.set_progress_handler(lambda: time.monotonic()>=deadline,10000)
        reader._conn.execute('BEGIN')
        now=datetime.now(timezone(timedelta(hours=9)))
        diagnostic_stage='core'
        result=collect(reader,now.date().isoformat())
        if CATALOG_LINK_DIAGNOSTIC:
            diagnostic_stage='catalog'
            result['catalog_links']=collect_catalog_links(reader,now)
        if DAILY_LIMITED_DIAGNOSTIC:
            diagnostic_stage='daily'
            from naver_engine import management_store as MS
            result['daily_limited']=collect_daily_limited(reader._conn,now.date().isoformat(),MS.snapshot(reader,now))
            diagnostic_stage='managed'
            result['managed_catalog_links']=collect_catalog_links(reader,now,managed_only=True)
        if MORNING_PROGRESS_DIAGNOSTIC:
            diagnostic_stage='morning'
            result['morning_progress']=collect_morning_progress(reader._conn,now.date().isoformat())
        if REPORTS_DIAGNOSTIC:
            diagnostic_stage='reports'
            result['reports']=collect_reports(reader._conn)
    except Exception as error:
        failure=diagnostic_failure(diagnostic_stage,error)
        raise
    finally:
        try:
            diagnostic_stage='rollback'
            reader._conn.execute('ROLLBACK')
        except Exception as error:
            failure=failure or diagnostic_failure(diagnostic_stage,error)
            raise
        finally:
            diagnostic_stage='close'
            reader.close()
    diagnostic_stage='bootstrap'
    result['bootstrap']=read_bootstrap()
    diagnostic_stage='output'
    print(json.dumps(result,sort_keys=True))
except Exception as error:
    print(json.dumps({'diagnostic_failure':failure or diagnostic_failure(diagnostic_stage,error)},sort_keys=True))
""".replace('CATALOG_LINK_DIAGNOSTIC', repr(catalog_links)).replace('DAILY_LIMITED_DIAGNOSTIC', repr(daily_limited))
       .replace('MORNING_PROGRESS_DIAGNOSTIC', repr(morning_progress)).replace('REPORTS_DIAGNOSTIC', repr(reports)))
    return '\n'.join(parts).encode()


def docker_stamp(value):
    """Docker RFC3339 nanoseconds/Z -> Python 3.8-compatible ISO, without loose parsing."""
    match = re.fullmatch(r'([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,9}))?(Z|[+-][0-9]{2}:[0-9]{2})', value) if isinstance(value, str) else None
    if match is None:
        raise ValueError('COLLECTION_TIME')
    normalized = match.group(1)
    if match.group(2) is not None:
        normalized += '.' + (match.group(2) + '000000')[:6]
    normalized += '+00:00' if match.group(3) == 'Z' else match.group(3)
    return stamp(normalized)


def compose_version(release):
    try:
        raw = release.command(['docker', 'compose', 'version', '--short'], timeout=3)
        if not isinstance(raw, bytes) or not 0 < len(raw) <= 128:
            return None
        value = raw.decode('ascii').strip()
        match = re.fullmatch(r'v?([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(?:-(?:desktop|rc|beta|alpha)\.[0-9]{1,3})?)', value)
        return match.group(1) if match else None
    except Exception:
        return None


def lifecycle_status(release):
    """Optional, bounded systemd metadata. No raw output survives this projection."""
    units = (('docker', 'docker.service'), ('tunnel', 'metainc-naver-erp-tunnel.service'),
             ('engine', 'metainc-naver-engine.service'), ('relay', 'metainc-naver-relay.service'))
    active = frozenset('active reloading inactive failed activating deactivating maintenance refreshing'.split())
    substates = frozenset('dead start-pre start start-post running exited reload reload-signal reload-notify stop stop-watchdog stop-sigterm stop-sigkill stop-post final-watchdog final-sigterm final-sigkill failed auto-restart auto-restart-queued cleaning'.split())
    results = frozenset('success resources timeout exit-code signal core-dump watchdog start-limit-hit oom-kill protocol exec-condition skipped assert'.split())
    out = {}
    for name, unit in units:
        try:
            raw = release.command(['/usr/bin/systemctl', 'show', unit,
                                   '--property=ActiveState,SubState,Result,NRestarts'], timeout=3)
            if not isinstance(raw, bytes) or not 0 < len(raw) <= 4096:
                raise ValueError('LIFECYCLE_SIZE')
            fields = {}
            for line in raw.decode('ascii').splitlines():
                key, sep, value = line.partition('=')
                if not sep or key in fields:
                    raise ValueError('LIFECYCLE_FIELDS')
                fields[key] = value
            if set(fields) != {'ActiveState', 'SubState', 'Result', 'NRestarts'}:
                raise ValueError('LIFECYCLE_FIELDS')
            n = fields['NRestarts']
            restarts = int(n) if re.fullmatch('[0-9]{1,19}', n) and int(n) <= 2**63-1 else None
            out[name] = {'available': True, 'active': enum(fields['ActiveState'], active),
                         'substate': enum(fields['SubState'], substates),
                         'result': enum(fields['Result'], results), 'restarts': restarts}
        except Exception:
            out[name] = {'available': False, 'code': 'LIFECYCLE_UNAVAILABLE'}
    return out


def capture_process(args, *, data=b'', timeout=5, stdout_limit=32768, stderr_limit=8192):
    """Bound both pipe memory and wall time; kill only our diagnostic CLI on failure."""
    chunks = {'stdout':bytearray(), 'stderr':bytearray()}
    limits = {'stdout':stdout_limit, 'stderr':stderr_limit}
    reason, process = None, None
    try:
        with selectors.DefaultSelector() as poll:
            process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C'})
            try:
                for name in chunks:
                    stream = getattr(process, name)
                    os.set_blocking(stream.fileno(), False)
                    poll.register(stream, selectors.EVENT_READ, name)
                if data:
                    os.set_blocking(process.stdin.fileno(), False)
                    poll.register(process.stdin, selectors.EVENT_WRITE, 'stdin')
                else:
                    process.stdin.close()
                offset, deadline = 0, time.monotonic()+timeout
                while poll.get_map():
                        remaining = deadline-time.monotonic()
                        if remaining <= 0:
                            reason = 'PROCESS_TIMEOUT'; break
                        for key, _ in poll.select(remaining):
                            if key.data == 'stdin':
                                try:
                                    offset += os.write(key.fd, data[offset:offset+4096])
                                except BrokenPipeError:
                                    offset = len(data)
                                if offset == len(data):
                                    poll.unregister(key.fileobj); key.fileobj.close()
                                continue
                            body = os.read(key.fd, 4096)
                            if not body:
                                poll.unregister(key.fileobj); key.fileobj.close(); continue
                            target = chunks[key.data]
                            room = limits[key.data]-len(target)
                            target.extend(body[:room])
                            if len(body) > room:
                                reason = 'PROCESS_OUTPUT_LIMIT'; break
                        if reason:
                            break
                if reason is None:
                    try:
                        process.wait(timeout=max(0.001, deadline-time.monotonic()))
                    except subprocess.TimeoutExpired:
                        reason = 'PROCESS_TIMEOUT'
            except OSError:
                reason = 'PROCESS_UNAVAILABLE'
            finally:
                if process.poll() is None:
                    process.kill()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        reason = 'PROCESS_CLEANUP_PENDING'
                for name in ('stdin','stdout','stderr'):
                    getattr(process,name).close()
        return dict(exit_code=process.returncode, reason=reason,
                    **{key:bytes(value) for key,value in chunks.items()})
    except OSError:
        return dict(exit_code=None, reason='PROCESS_UNAVAILABLE', stdout=b'', stderr=b'')


def process_failure(result):
    # Exception messages, file paths, source lines and arbitrary class names never leave the host.
    kinds = DIAGNOSTIC_KINDS | frozenset(('NameError','ImportError','ModuleNotFoundError',
                                        'SyntaxError','IndentationError','UnboundLocalError'))
    found = re.findall(rb'^([A-Za-z][A-Za-z0-9_]{0,63}):[^\n]*$', result['stderr'], re.M)
    kind = found[-1].decode('ascii') if found else None
    kind = kind if kind in kinds else 'UNRECOGNIZED'
    return {'code':result['reason'] or 'PROCESS_EXIT', 'exit_code':result['exit_code'],
            'error_kind':kind, 'output_limited':result['reason']=='PROCESS_OUTPUT_LIMIT'}


LOG_STAGES = frozenset('org stages accounts pairing inventory_catalog inventory reports readiness morning alerts backup metrics'.split())
LOG_KINDS = DIAGNOSTIC_KINDS | frozenset('NameError IndexError ImportError ModuleNotFoundError StoreError StoreBusy StoreRefused TimeoutError SyntaxError IndentationError UnboundLocalError'.split())
RELAY_KINDS = frozenset('engine-loop engine-not-configured relay-busy relay-no-thread engine-timeout engine-bad-answer engine-answer-too-large engine-cut ConnectionRefusedError ConnectionResetError BrokenPipeError TimeoutError OSError RemoteDisconnected BadStatusLine IncompleteRead'.split())


def log_projection(raw, *, source, unit):
    """Recent log sample, never a claim that every failure was captured."""
    if source not in ('journal','docker') or unit not in ('engine','relay') or len(raw)>1048576:
        raise ValueError('LOG_SCOPE')
    rows = raw.splitlines()
    if len(rows)>300:
        raise ValueError('LOG_LIMIT')
    counts, unknown, last = {}, 0, None
    for row in rows:
        at = None
        try:
            message = row.decode('utf-8')
            if source == 'journal':
                item = json.loads(message)
                message = item['MESSAGE']
                tick = item.get('__REALTIME_TIMESTAMP')
                if isinstance(tick,str) and re.fullmatch('[0-9]{16}',tick):
                    at = datetime.fromtimestamp(int(tick)/1000000,timezone.utc).isoformat()
            else:
                tick, _, message = message.partition(' ')
                at = docker_stamp(tick)
            if not isinstance(message,str) or len(message)>4096:
                raise ValueError('LOG_MESSAGE')
        except (ValueError,KeyError,TypeError,OverflowError,OSError):
            unknown+=1; continue
        message = re.sub(r'^naver-'+unit+r'(?:-1)?\s+\|\s*','',message)
        step = re.fullmatch(r'ERROR naver_runtime.scheduler 예약 작업 실패: ([a-z_]{1,32}) ([A-Za-z][A-Za-z0-9_]{0,63})',message)
        cycle = re.fullmatch(r'ERROR naver_runtime 예약 회차 실패: ([A-Za-z][A-Za-z0-9_]{0,63})',message)
        exited = re.fullmatch(r'metainc-naver-'+unit+r'\.service: Main process exited, code=(exited|killed|dumped), status=([0-9]{1,3})/[A-Za-z0-9/_-]{1,32}',message)
        failed = re.fullmatch(r'metainc-naver-'+unit+r"\.service: Failed with result '(exit-code|signal|core-dump|timeout|watchdog|start-limit-hit|resources|protocol|oom-kill)'\.",message)
        exception = re.fullmatch(r'([A-Za-z][A-Za-z0-9_]{0,63}):[^\n]*',message)
        relay = re.fullmatch(r'(?:WARNING:?[ ]+(?:app.naver_relay )?)?관제 엔진 중계 실패: ([A-Za-z][A-Za-z0-9_-]{0,63})',message)
        event = None
        if step and step[1] in LOG_STAGES:
            event = dict(event='job_failed',stage=step[1],error_kind=enum(step[2],LOG_KINDS))
        elif cycle:
            event = dict(event='cycle_failed',error_kind=enum(cycle[1],LOG_KINDS))
        elif message == 'ERROR naver_runtime.scheduler 예약 작업 실패 기록을 저장하지 못했습니다':
            event = dict(event='failure_record_failed')
        elif exited and int(exited[2])<=255:
            event = dict(event='process_exited',exit_type=exited[1],exit_code=int(exited[2]))
        elif failed:
            event = dict(event='service_failed',result=failed[1])
        elif relay:
            event = dict(event='relay_failed',error_kind=enum(relay[1],RELAY_KINDS))
        elif exception and exception[1] in LOG_KINDS:
            event = dict(event='exception_line',error_kind=exception[1])
        if event is None:
            unknown+=1; continue
        key = json.dumps(event,sort_keys=True)
        counts[key] = counts.get(key,0)+1
        if at and (last is None or datetime.fromisoformat(at)>datetime.fromisoformat(last)):
            last = at
    ordered = sorted(counts.items())
    return dict(entries_inspected=len(rows), sample_limit_reached=len(rows)==300,
                unrecognized_entries=unknown,last_recognized_at=last,
                omitted_event_count=sum(value for key,value in ordered[32:]),
                events=[dict(json.loads(key),count=value) for key,value in ordered[:32]])


def recent_runtime_logs(identity):
    sources = []
    for unit in ('engine','relay'):
        args = ['/usr/bin/journalctl','--no-pager','--output=json',
                '--output-fields=MESSAGE,__REALTIME_TIMESTAMP','--since','24 hours ago',
                '--lines=300','--unit=metainc-naver-'+unit+'.service']
        sources.append((unit,'journal',args))
    sources.append(('engine','docker',['docker','logs','--since','24h','--tail','300','--timestamps',identity]))
    results = []
    for unit, source, args in sources:
        result = capture_process(args,timeout=5,stdout_limit=1048576,stderr_limit=1048576)
        item = dict(unit=unit,source=source)
        if result['reason'] or result['exit_code']!=0:
            item.update(available=False,failure=process_failure(result))
        else:
            try:
                raw = result['stdout'] if source=='journal' else result['stdout']+result['stderr']
                item.update(available=True,**log_projection(raw,source=source,unit=unit))
            except ValueError:
                item.update(available=False,code='LOG_PROJECTION_UNAVAILABLE')
        results.append(item)
    return dict(scope='last_24h_tail_300_per_source_sample_not_complete_history',
                sources_may_overlap_do_not_sum=True,sources=results)


def storage_metadata(root=Path('/var/lib/metainc/naver-engine')):
    """stat only: do not open SQLite, WAL, SHM or any file content."""
    try:
        if not stat.S_ISDIR(root.lstat().st_mode):
            raise ValueError('STORAGE_DIRECTORY')
        fs = os.statvfs(root)
        files = {}
        for label,suffix in (('database',''),('wal','-wal'),('shared_memory','-shm')):
            try:
                info = (root/('engine.db'+suffix)).lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('STORAGE_FILE_TYPE')
                files[label] = dict(available=True,bytes=number(info.st_size),
                    modified_at=datetime.fromtimestamp(info.st_mtime,timezone.utc).isoformat())
            except (ValueError,OSError):
                files[label] = dict(available=False)
        return dict(available=True,free_bytes=number(fs.f_bavail*fs.f_frsize),files=files,
                    file_contents_read=False)
    except (ValueError,OSError):
        return dict(available=False,file_contents_read=False)


def run(package, host, release):
    global STAGE
    STAGE = 'preflight'
    validate_package(package)
    passive = package.get('passive_runtime_only') is True
    # Incident 2026-10-05: live reader attempts overlapped engine exits. No further
    # active probes on this release until isolated causality testing is complete.
    if package['source_commit'] == REPORTS_COMMIT and not passive:
        raise ValueError('LIVE_READER_SUSPENDED')
    package = {key:value for key,value in package.items() if key!='passive_runtime_only'}
    if os.geteuid() != 0 or host.baseline() != package['baseline']:
        raise ValueError('HOST_BASELINE')
    commit = package['source_commit']
    path, prepared_path = release.prepared_paths(commit)
    start_path = prepared_path.with_name('preview-start-'+commit+'.json')
    release.trusted_private_file(start_path)
    if any(item.stat().st_size > 32768 for item in (prepared_path, start_path)):
        raise ValueError('RECEIPT_SIZE')
    prepared = json.loads(prepared_path.read_bytes(), object_pairs_hook=release.unique)
    started = json.loads(start_path.read_bytes(), object_pairs_hook=release.unique)
    if (prepared.get('ok') is not True or prepared.get('stage') != 'prepared'
            or prepared.get('source_commit') != commit or started.get('ok') is not True
            or started.get('stage') != 'internal_ready' or started.get('source_commit') != commit
            or any(prepared.get('package', {}).get(key) != value for key, value in package.items())):
        raise ValueError('SOURCE_NOT_READY')
    for file in (path/'compose.naver-engine.yml', path/'preview-engine.override.yml',
                 path/'deploy/naver-engine-backup.override.yml'):
        if file.resolve() != file or release.sha(file.read_bytes()) != prepared.get('files', {}).get(str(file)):
            raise ValueError('COMPOSE_CHANGED')
    expected_image = prepared.get('images', {}).get('engine')
    if not isinstance(expected_image, str) or not re.fullmatch('sha256:[0-9a-f]{64}', expected_image):
        raise ValueError('PREPARED_IMAGE')
    fmt = '{"id":{{json .Id}},"user":{{json .Config.User}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}'
    image = json.loads(release.command(['docker', 'image', 'inspect', '--format', fmt, 'metainc/naver-engine:'+commit]))
    if image != {'id': expected_image, 'user': '10001:10001', 'source': commit}:
        raise ValueError('PREPARED_IMAGE_CHANGED')
    identity = release.command(release.compose(path, 'engine')+['ps', '--all', '--quiet']).decode().strip()
    if not re.fullmatch('[0-9a-f]{64}', identity):
        raise ValueError('PREVIEW_CONTAINER_ID')
    fmt = '{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"user":{{json .Config.User}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"started":{{json .State.StartedAt}},"oom_killed":{{json .State.OOMKilled}},"restarts":{{json .RestartCount}},"readonly":{{json .HostConfig.ReadonlyRootfs}},"data":[{{range .Mounts}}{{if eq .Destination "/var/lib/naver-engine"}}{{json .}}{{end}}{{end}}]}'
    def container():
        return json.loads(release.command(['docker', 'inspect', '--format', fmt, identity]))
    before = container()
    if (any(before.get(key) != value for key, value in {'id': identity, 'image': expected_image,
            'user': '10001:10001', 'project': 'naver-engine', 'service': 'naver-engine'}.items())
            or (not passive and before.get('running') is not True) or before.get('readonly') is not True):
        raise ValueError('PREVIEW_CONTAINER_CHANGED')
    data = before.get('data')
    if (not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict)
            or any(data[0].get(key) != value for key, value in {'Type': 'bind',
                'Destination': '/var/lib/naver-engine', 'Source': '/var/lib/metainc/naver-engine'}.items())):
        raise ValueError('PREVIEW_DATA_MOUNT')
    STAGE = 'read_only_status'
    def context():
        return {'lifecycle':lifecycle_status(release), 'compose_version':compose_version(release),
                'recent_runtime_logs':recent_runtime_logs(identity),
                'engine_state':{'started_at':docker_stamp(before.get('started')),
                    'oom_killed':before.get('oom_killed') if type(before.get('oom_killed')) is bool else None}}
    def postflight():
        global STAGE
        STAGE = 'postflight'
        after = container()
        unchanged = host.baseline() == package['baseline']
        same = after == before
        # Preserve failure evidence without accepting a changed runtime as a valid data read.
        return {'existing_app_baseline_unchanged':unchanged,
                'postflight':{'container_unchanged':same,'code':None if same and unchanged else 'POST_BASELINE'},
                'engine_state_after':{
                    'started_at':docker_stamp(after.get('started')),
                    'oom_killed':after.get('oom_killed') if type(after.get('oom_killed')) is bool else None,
                    'running':after.get('running') if type(after.get('running')) is bool else None,
                    'container_restarts':number(after.get('restarts'))}}
    if passive:
        details = context()
        details['storage_metadata'] = storage_metadata()
        checked = postflight()
        return {'ok':checked['postflight']['code'] is None,'mode':'runtime-diagnostics',
                'source_commit':commit,'database_opened':False,'mutations':0,**details,**checked}
    captured = capture_process(['docker', 'exec', '-i', '--user', '10001:10001', identity,
                           'python', '-I', '-B', '-'], data=script(catalog_links=commit in CATALOG_LINKS_COMMITS,
                            daily_limited=commit in DAILY_LIMITED_COMMITS,
                            morning_progress=commit in MONITORING_COMMITS,
                            reports=commit in MONITORING_COMMITS), timeout=30)
    if captured['reason'] or captured['exit_code'] != 0:
        details = context()
        checked = postflight()
        return {'ok':False,'mode':'collection-status','source_commit':commit,'stage':'reader_process',
                'process_failure':process_failure(captured),**details,**checked,'mutations':0}
    raw = captured['stdout']
    if len(raw) > 32768:
        raise ValueError('STATUS_SIZE')
    value = json.loads(raw, object_pairs_hook=release.unique)
    if isinstance(value, dict) and 'diagnostic_failure' in value:
        failure = diagnostic_projection(value)
        details = context()
        checked = postflight()
        # The receiver exits nonzero for ok=False. No partial aggregates become success or zeros.
        return {'ok':False,'mode':'collection-status','source_commit':commit,**failure,**details,
                **checked,'mutations':0}
    values = project(value)
    if ('catalog_links' in values) != (commit in CATALOG_LINKS_COMMITS):
        raise ValueError('CATALOG_LINK_FIELDS')
    if ('daily_limited' in values) != (commit in DAILY_LIMITED_COMMITS):
        raise ValueError('COLLECTION_LIMITED_FIELDS')
    if ('managed_catalog_links' in values) != (commit in DAILY_LIMITED_COMMITS):
        raise ValueError('CATALOG_LINK_FIELDS')
    if ('morning_progress' in values) != (commit in MONITORING_COMMITS):
        raise ValueError('COLLECTION_MORNING_FIELDS')
    if ('reports' in values) != (commit in MONITORING_COMMITS):
        raise ValueError('COLLECTION_REPORTS')
    details = context()
    checked = postflight()
    if checked['postflight']['code']:
        return {'ok':False,'mode':'collection-status','source_commit':commit,'stage':'postflight',
                **details,**checked,'mutations':0}
    return {'ok': True, 'mode': 'collection-status', 'source_commit': commit, 'collection': values, **details,
            'runtime_state_not_used_as_data_success': True, 'reader_mode': 'store-mode-ro-authorizer',
            'mutations': 0, **checked}
