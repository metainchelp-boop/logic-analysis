"""Read-only collection aggregates; no identity, amount or freeform error output."""
import json
import os
from pathlib import Path
import re
import stat
from datetime import date, datetime, timedelta

STAGE = 'input'
CATALOG_LINKS_COMMIT = '6e4b035901027fef29266de218bfb0594227a3fe'
# catalog_links/handles and read-only management policy ASTs are identical at these pins.
DAILY_LIMITED_COMMIT = '01344b145d0b679a6ee730d7fa4b5990278dd654'
CATALOG_LINKS_COMMITS = frozenset((CATALOG_LINKS_COMMIT, DAILY_LIMITED_COMMIT))
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
            if scope.kind not in (rules.SC.ALL, rules.SC.MINE):
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


def project(value):
    fields = {'today', 'prospects', 'pairing', 'latest_run', 'today_checks', 'bootstrap'}
    if (not isinstance(value, dict) or not fields <= set(value)
            or set(value) - fields - {'management','catalog_links','daily_limited','managed_catalog_links'}):
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
    if not isinstance(package, dict) or set(package) != {'baseline', 'source_commit', 'source_tar_gz_sha256'}:
        raise ValueError('PACKAGE_FIELDS')
    for key, value in package.items():
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}' if key == 'source_commit' else '[0-9a-f]{64}', value):
            raise ValueError('PACKAGE_SHAPE')


def script(*, catalog_links=False, daily_limited=False):
    parts = ['import json,os,sys,stat,re,time\nfrom pathlib import Path\nfrom datetime import date,datetime,timedelta,timezone\n', PROJECTION_SOURCE]
    parts.append("""
try:
    if os.geteuid()!=10001:
        raise ValueError('READER_IDENTITY')
    os.environ.clear()
    sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
    from naver_engine import store as S
    reader=S.open_reader('/var/lib/naver-engine/engine.db')
    try:
        deadline=time.monotonic()+20
        reader._conn.set_progress_handler(lambda: time.monotonic()>=deadline,10000)
        reader._conn.execute('BEGIN')
        now=datetime.now(timezone(timedelta(hours=9)))
        result=collect(reader,now.date().isoformat())
        if CATALOG_LINK_DIAGNOSTIC:
            result['catalog_links']=collect_catalog_links(reader,now)
        if DAILY_LIMITED_DIAGNOSTIC:
            from naver_engine import management_store as MS
            result['daily_limited']=collect_daily_limited(reader._conn,now.date().isoformat(),MS.snapshot(reader,now))
            result['managed_catalog_links']=collect_catalog_links(reader,now,managed_only=True)
    finally:
        try:
            reader._conn.execute('ROLLBACK')
        finally:
            reader.close()
    result['bootstrap']=read_bootstrap()
    print(json.dumps(result,sort_keys=True))
except Exception:
    sys.exit(1)
""".replace('CATALOG_LINK_DIAGNOSTIC', repr(catalog_links)).replace('DAILY_LIMITED_DIAGNOSTIC', repr(daily_limited)))
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


def run(package, host, release):
    global STAGE
    STAGE = 'preflight'
    validate_package(package)
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
            or before.get('running') is not True or before.get('readonly') is not True):
        raise ValueError('PREVIEW_CONTAINER_CHANGED')
    data = before.get('data')
    if (not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict)
            or any(data[0].get(key) != value for key, value in {'Type': 'bind',
                'Destination': '/var/lib/naver-engine', 'Source': '/var/lib/metainc/naver-engine'}.items())):
        raise ValueError('PREVIEW_DATA_MOUNT')
    STAGE = 'read_only_status'
    raw = release.command(['docker', 'exec', '-i', '--user', '10001:10001', identity,
                           'python', '-I', '-B', '-'], data=script(catalog_links=commit in CATALOG_LINKS_COMMITS,
                            daily_limited=commit == DAILY_LIMITED_COMMIT), timeout=30)
    if len(raw) > 32768:
        raise ValueError('STATUS_SIZE')
    values = project(json.loads(raw, object_pairs_hook=release.unique))
    if ('catalog_links' in values) != (commit in CATALOG_LINKS_COMMITS):
        raise ValueError('CATALOG_LINK_FIELDS')
    if ('daily_limited' in values) != (commit == DAILY_LIMITED_COMMIT):
        raise ValueError('COLLECTION_LIMITED_FIELDS')
    if ('managed_catalog_links' in values) != (commit == DAILY_LIMITED_COMMIT):
        raise ValueError('CATALOG_LINK_FIELDS')
    lifecycle = lifecycle_status(release)
    version = compose_version(release)
    engine_state = {'started_at': docker_stamp(before.get('started')),
                    'oom_killed': before.get('oom_killed') if type(before.get('oom_killed')) is bool else None}
    STAGE = 'postflight'
    if container() != before or host.baseline() != package['baseline']:
        raise ValueError('POST_BASELINE')
    return {'ok': True, 'mode': 'collection-status', 'source_commit': commit, 'collection': values, 'lifecycle': lifecycle,
            'compose_version': version, 'engine_state': engine_state,
            'runtime_state_not_used_as_data_success': True, 'reader_mode': 'store-mode-ro-authorizer',
            'mutations': 0, 'existing_app_baseline_unchanged': True}
