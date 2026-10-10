"""Exact V19 September recovery diagnosis; no collection, generation or business writes."""
import json
import os
from pathlib import Path
import re

STAGE = 'input'
SOURCE = '00701771c0583477357010e9ac731263770f1da5'
ARCHIVE = '5c77d0197fb088600e11234660f3bf3013c03eafd8e3b756b8be7b91f34fc0e3'
STORE = 'aa39afff20c48225d70e80a899234c68b862aeaa53fae43c2e0769346f3b6d62'
BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
MAX_OUTPUT = 32768
PROJECTION_SOURCE = r'''
START, END = '2026-09-01', '2026-09-30'
SAMPLES = (74789, 82569)
KEYS = ('monthly:2026-09-01:2026-09-30', 'weekly:2026-08-31:2026-09-06',
        'weekly:2026-09-07:2026-09-13', 'weekly:2026-09-14:2026-09-20',
        'weekly:2026-09-21:2026-09-27', 'weekly:2026-09-28:2026-10-04')
STATES = frozenset('reading partial ok retry limited reauth_required source_wait'.split())
ERRORS = frozenset(('REQUEST_DEADLINE REQUEST_CALL_CAP REQUEST_BUDGET RETRY_EXHAUSTED '
    'STATS_INCOMPLETE STATS_PERIOD_OPEN STATS_METRIC_MISSING STATS_METRIC_INVALID '
    'STATS_DATE_INCOMPLETE STATS_CYCLE_INVALID STATS_CYCLE_FUTURE STATS_CAMPAIGNS_INVALID '
    'CAMPAIGNS_CHANGED CHECKPOINT_INVALID SOURCE_AGGREGATING UNEXPECTED '
    'KEY_REJECTED RATE SERVER BAD_REQUEST NOT_FOUND NETWORK BAD_RESPONSE MISMATCH OTHER').split())
MAX_ACCOUNTS, MAX_TARGETS, MAX_ROWS = 4000, 2000, 100000
KST = timezone(timedelta(hours=9))


def check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise ValueError('RECOVERY_DEADLINE')


def number(value):
    if type(value) is not int or not 0 <= value <= 2**63-1:
        raise ValueError('RECOVERY_NUMBER')
    return value


def stamp(value):
    if value is None or value == '':
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(KST).isoformat()
    except (TypeError, ValueError):
        raise ValueError('RECOVERY_TIME') from None


def day(value):
    try:
        if type(value) is not str or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError('RECOVERY_DAY') from None
    return value


def enum(value, allowed):
    return value if type(value) is str and value in allowed else 'UNRECOGNIZED'


def rows(connection, query, params, limit, deadline):
    check_deadline(deadline)
    cursor = connection.execute(query, params)
    names = [column[0] for column in cursor.description]
    values = cursor.fetchmany(limit+1)
    cursor.close()
    if len(values) > limit:
        raise ValueError('RECOVERY_ROW_LIMIT')
    check_deadline(deadline)
    return [dict(zip(names, row)) for row in values]


def time_bounds(values):
    values = [stamp(value) for value in values if value is not None and value != '']
    return {'first': min(values, default=None), 'last': max(values, default=None)}


def readonly_authorizer(action, arg1, arg2, database, source):
    # Initialization PRAGMAs finish before installing this authorizer.
    allowed = (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_TRANSACTION,
               sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_RECURSIVE)
    if action in allowed:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (arg2 or '').lower() in (
            'load_extension', 'readfile', 'writefile', 'shell', 'eval', 'fts3_tokenizer') else sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg2 is None and (arg1 or '').lower() in (
            'query_only', 'database_list', 'user_version'):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and (arg1 or '').lower() == 'table_info' and arg2 == 'naver_auto_link_memory':
        return sqlite3.SQLITE_OK  # The public management snapshot checks this exact additive column.
    return sqlite3.SQLITE_DENY


def connect_reader(path):
    # Only the fixed engine path is supplied by the script, never by its package.
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ValueError('RECOVERY_DATABASE_PATH')
    connection = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, isolation_level=None, timeout=1)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA busy_timeout=1000')
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.set_authorizer(readonly_authorizer)
        if connection.execute('PRAGMA query_only').fetchone() != (1,):
            raise ValueError('RECOVERY_READER_MODE')
        if connection.execute('PRAGMA database_list').fetchall() != [(0, 'main', str(path))]:
            raise ValueError('RECOVERY_DATABASE_PATH')
        return connection
    except Exception:
        connection.close()
        raise


def attribution_starts(events, targets, deadline):
    previous, boundary, gap = {}, {}, set()
    for event in events:
        check_deadline(deadline)
        cid, pid = number(event['customer_id']), event['possibility_id']
        if pid is None:
            if cid in previous:
                gap.add(cid)
            continue
        number(pid)
        if cid in previous and (pid != previous[cid] or cid in gap):
            at = stamp(event['at'])
            if at is None:
                raise ValueError('RECOVERY_TIME')
            boundary[cid] = str(date.fromisoformat(at[:10])+timedelta(days=1))
        previous[cid] = pid
        gap.discard(cid)
    return {cid: boundary.get(cid) if previous.get(cid) == pid else None for cid, pid in targets.items()}


def job_projection(row):
    return {'customer_id': number(row['customer_id']), 'possibility_id': number(row['possibility_id']),
        'kind': enum(row['kind'], {'report_monthly', 'report_weekly'}),
        'cycle_day': day(row['cycle_day']), 'period_start': day(row['period_start']), 'period_end': day(row['period_end']),
        'status': enum(row['status'], STATES),
        'error_code': None if row['error_code'] is None else enum(row['error_code'], ERRORS),
        'checked_at': stamp(row['checked_at']), 'last_success_at': stamp(row['last_success_at']),
        'next_try_at': stamp(row['next_try_at']), 'generation': stamp(row['generation']),
        'attempts': number(row['attempts'])}


def validation_projection(row):
    raw = row['expected_customers_json']
    if type(raw) is not str or len(raw.encode()) > 32768:
        raise ValueError('RECOVERY_EXPECTED_SCOPE')
    expected = json.loads(raw)
    if not isinstance(expected, list) or len(expected) > MAX_TARGETS:
        raise ValueError('RECOVERY_EXPECTED_SCOPE')
    if any(type(cid) is not int or cid <= 0 for cid in expected) or len(set(expected)) != len(expected):
        raise ValueError('RECOVERY_EXPECTED_SCOPE')
    return {'expected': sorted(expected), 'status': enum(row['validation_status'], {'complete', 'pending', 'failed'}),
        'pending_account_days': number(row['pending_account_days']),
        'last_attempt_at': stamp(row['last_attempt_at']), 'last_checked_at': stamp(row['last_checked_at'])}


def collect(store, decisions, now, fingerprint, deadline):
    connection = store._conn
    if connection.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone() != ('11',):
        raise ValueError('RECOVERY_SCHEMA')
    if not decisions or len(decisions) > MAX_ACCOUNTS or any(row.get('source_current') is not True for row in decisions.values()):
        raise ValueError('RECOVERY_ELIGIBILITY_STALE')
    targets = {}
    for cid, row in decisions.items():
        check_deadline(deadline)
        decision = row['decision']
        if row.get('matched') is True and decision.cadence == 'daily' and decision.attributable:
            if number(cid) <= 0 or number(row['possibility_id']) <= 0:
                raise ValueError('RECOVERY_TARGET')
            targets[cid] = row['possibility_id']
    if len(targets) > MAX_TARGETS:
        raise ValueError('RECOVERY_TARGET_LIMIT')
    if type(fingerprint) is not str or not re.fullmatch('[0-9a-f]{64}', fingerprint):
        raise ValueError('RECOVERY_MATCHING')
    pids, daily, jobs, events = sorted(set(targets.values())), [], [], []
    for offset in range(0, len(targets), 200):
        ids = sorted(targets)[offset:offset+200]
        marks = ','.join('?' for _ in ids)
        daily.extend(rows(connection, 'SELECT customer_id,day,possibility_id,matching_fingerprint,basic_complete,'
            'conversion_complete,checked_at,source_at,source_generation FROM naver_auto_daily_performance '
            'WHERE customer_id IN ('+marks+') AND day BETWEEN ? AND ? ORDER BY customer_id,day',
            (*ids, START, END), len(ids)*30, deadline))
        jobs.extend(rows(connection, 'SELECT customer_id,possibility_id,kind,cycle_day,period_start,period_end,status,'
            'checked_at,last_success_at,next_try_at,generation,attempts,error_code FROM naver_auto_performance_job '
            "WHERE customer_id IN ("+marks+") AND kind IN ('report_monthly','report_weekly') AND period_start<=? "
            'AND period_end>=? ORDER BY checked_at,job_key', (*ids, END, START), MAX_ROWS-len(jobs), deadline))
        events.extend(rows(connection, 'SELECT customer_id,possibility_id,at FROM naver_auto_management_event '
            "WHERE customer_id IN ("+marks+") AND action='stage_sync' ORDER BY customer_id,event_id",
            ids, MAX_ROWS-len(events), deadline))
    boundaries = attribution_starts(events, targets, deadline)
    raw = {}
    for row in daily:
        check_deadline(deadline)
        cid, value = number(row['customer_id']), day(row['day'])
        if row['basic_complete'] not in (0, 1) or row['conversion_complete'] not in (0, 1):
            raise ValueError('RECOVERY_FLAG')
        if row['possibility_id'] is not None:
            number(row['possibility_id'])
        for key in ('checked_at', 'source_at', 'source_generation'):
            stamp(row[key])
        raw[(cid, value)] = row
    jobs = [job_projection(row) for row in jobs if targets.get(row['customer_id']) == row['possibility_id']]
    coverage = []
    for offset in range(30):
        check_deadline(deadline)
        value = str(date(2026, 9, 1)+timedelta(days=offset))
        tally = dict(day=value, expected_accounts=len(targets), current_pid_rows=0, null_pid_rows=0,
            other_pid_rows=0, missing_rows=0, basic_current_pid=0, conversion_current_pid=0,
            current_matching_rows=0, before_attribution_days=0)
        for cid, pid in targets.items():
            row = raw.get((cid, value))
            tally['before_attribution_days'] += int(boundaries[cid] is not None and value < boundaries[cid])
            bucket = 'missing_rows' if row is None else 'null_pid_rows' if row['possibility_id'] is None else \
                'current_pid_rows' if row['possibility_id'] == pid else 'other_pid_rows'
            tally[bucket] += 1
            if bucket == 'current_pid_rows':
                tally['basic_current_pid'] += int(row['basic_complete'])
                tally['conversion_current_pid'] += int(row['conversion_complete'])
                tally['current_matching_rows'] += int(row['matching_fingerprint'] == fingerprint)
        coverage.append(tally)
    grouped_jobs = []
    for kind in ('report_monthly', 'report_weekly'):
        values = [row for row in jobs if row['kind'] == kind]
        grouped_jobs.append({'kind': kind, 'jobs': len(values),
            'statuses': {state: sum(row['status'] == state for row in values) for state in sorted(STATES | {'UNRECOGNIZED'})},
            'errors': {code: sum(row['error_code'] == code for row in values) for code in sorted({row['error_code'] for row in values if row['error_code'] is not None})},
            'checked_at': time_bounds(row['checked_at'] for row in values),
            'last_success_at': time_bounds(row['last_success_at'] for row in values),
            'next_try_at': time_bounds(row['next_try_at'] for row in values)})
    metadata, dirty = {}, {}
    for offset in range(0, len(pids), 200):
        chunk = pids[offset:offset+200]
        marks, periods = ','.join('?' for _ in chunk), ','.join('?' for _ in KEYS)
        conditions = 'possibility_id IN ('+marks+') AND period_key IN ('+periods+')'
        params = (*chunk, *KEYS)
        for row in rows(connection, 'SELECT possibility_id,period_key,pending,updated_at FROM naver_auto_report_dirty WHERE '+conditions,
                        params, len(chunk)*len(KEYS), deadline):
            if row['pending'] not in (0, 1):
                raise ValueError('RECOVERY_FLAG')
            dirty[(row['possibility_id'], row['period_key'])] = {'pending': bool(row['pending']), 'updated_at': stamp(row['updated_at'])}
        validations = rows(connection, 'SELECT possibility_id,period_key,expected_customers_json,'
            "json_extract(payload_json,'$.status') AS validation_status,"
            "json_extract(payload_json,'$.pending_account_days') AS pending_account_days,"
            "json_extract(payload_json,'$.last_attempt_at') AS last_attempt_at,"
            "json_extract(payload_json,'$.last_checked_at') AS last_checked_at "
            'FROM naver_auto_report_validation WHERE '+conditions, params, len(chunk)*len(KEYS), deadline)
        for row in validations:
            metadata.setdefault((row['possibility_id'], row['period_key']), {})['validation'] = validation_projection(row)
        if connection.execute('SELECT COUNT(*) FROM naver_auto_report_snapshot').fetchone()[0] > MAX_ROWS:
            raise ValueError('RECOVERY_SNAPSHOT_LIMIT')
        snapshots = rows(connection, 'SELECT r.possibility_id,r.period_key,r.generated_at,'
            "json_extract(r.payload_json,'$.coverage.accounts') AS accounts,"
            "json_extract(r.payload_json,'$.coverage.expected_account_days') AS expected_account_days,"
            "json_extract(r.payload_json,'$.coverage.basic_complete_account_days') AS basic_complete_account_days,"
            "json_extract(r.payload_json,'$.coverage.conversion_complete_account_days') AS conversion_complete_account_days,"
            "json_extract(r.payload_json,'$.validation.status') AS validation_status,"
            "json_extract(r.payload_json,'$.validation.last_attempt_at') AS last_attempt_at,"
            "json_extract(r.payload_json,'$.validation.last_checked_at') AS last_checked_at "
            'FROM naver_auto_report_snapshot r JOIN (SELECT MAX(report_id) AS report_id '
            'FROM naver_auto_report_snapshot WHERE '+conditions+' GROUP BY possibility_id,period_key) latest '
            'ON latest.report_id=r.report_id', params, len(chunk)*len(KEYS), deadline)
        for row in snapshots:
            out = {'generated_at': stamp(row['generated_at']),
                'coverage': {key: None if row[key] is None else number(row[key]) for key in (
                    'accounts', 'expected_account_days', 'basic_complete_account_days', 'conversion_complete_account_days')},
                'validation_status': enum(row['validation_status'], {'complete', 'pending', 'failed'}),
                'last_attempt_at': stamp(row['last_attempt_at']), 'last_checked_at': stamp(row['last_checked_at'])}
            metadata.setdefault((row['possibility_id'], row['period_key']), {})['snapshot'] = out
    report_states = []
    for key in KEYS:
        items = [metadata.get((pid, key), {}) for pid in pids]
        report_states.append({'period_key': key, 'current_companies': len(pids),
            'snapshots': sum('snapshot' in item for item in items), 'validations': sum('validation' in item for item in items),
            'dirty_pending': sum(dirty.get((pid, key), {}).get('pending', False) for pid in pids),
            'validation_statuses': {state: sum(item.get('validation', {}).get('status') == state for item in items)
                for state in ('complete', 'pending', 'failed', 'UNRECOGNIZED')},
            'validation_scope_matches_current': sum(item.get('validation', {}).get('expected') == sorted(cid for cid, owner in targets.items() if owner == pid)
                for pid, item in zip(pids, items))})
    samples = []
    for pid in SAMPLES:
        ids = sorted(cid for cid, owner in targets.items() if owner == pid)
        if len(ids) > 8:
            raise ValueError('RECOVERY_SAMPLE_LIMIT')
        sample = {'possibility_id': pid, 'in_current_population': bool(ids), 'accounts': [], 'reports': []}
        for cid in ids:
            values = [raw[(cid, row['day'])] for row in coverage if (cid, row['day']) in raw]
            dates = {key: [] for key in ('current_pid', 'null_pid', 'other_pid', 'missing', 'basic_current_pid', 'conversion_current_pid', 'current_matching', 'before_attribution')}
            for tally in coverage:
                value, row = tally['day'], raw.get((cid, tally['day']))
                bucket = 'missing' if row is None else 'null_pid' if row['possibility_id'] is None else 'current_pid' if row['possibility_id'] == pid else 'other_pid'
                dates[bucket].append(value)
                if boundaries[cid] is not None and value < boundaries[cid]:
                    dates['before_attribution'].append(value)
                if bucket == 'current_pid':
                    if row['basic_complete']:
                        dates['basic_current_pid'].append(value)
                    if row['conversion_complete']:
                        dates['conversion_current_pid'].append(value)
                    if row['matching_fingerprint'] == fingerprint:
                        dates['current_matching'].append(value)
            latest = {}
            for job in jobs:
                if job['customer_id'] == cid:
                    latest[(job['kind'], job['period_start'], job['period_end'])] = job
            if len(latest) > 12:
                raise ValueError('RECOVERY_SAMPLE_LIMIT')
            sample['accounts'].append({'customer_id': cid, 'attribution_start': boundaries[cid], 'dates': dates,
                'checked_at': time_bounds(row['checked_at'] for row in values),
                'source_at': time_bounds(row['source_at'] for row in values),
                'source_generation': time_bounds(row['source_generation'] for row in values),
                'latest_report_jobs': list(latest.values())})
        for key in KEYS:
            item = metadata.get((pid, key), {})
            validation = item.get('validation')
            comparable = key == KEYS[0] and bool(ids) and validation is not None and validation['expected'] == ids \
                and all(row['matching_fingerprint'] == fingerprint for row in daily if row['customer_id'] in ids and row['possibility_id'] == pid)
            sample['reports'].append({'period_key': key, 'dirty': dirty.get((pid, key)),
                **item, 'raw_same_scope_comparable': comparable,
                'raw_basic_current_pid': sum(row['possibility_id'] == pid and row['basic_complete'] == 1 for row in daily if row['customer_id'] in ids) if comparable else None,
                'raw_conversion_current_pid': sum(row['possibility_id'] == pid and row['conversion_complete'] == 1 for row in daily if row['customer_id'] in ids) if comparable else None})
        samples.append(sample)
    check_deadline(deadline)
    return {'schema_version': 11, 'period': '2026-09', 'observed_at': stamp(now.isoformat()),
        'population': {'scope': 'current-managed-linked', 'source_current': True, 'accounts': len(targets),
            'companies': len(pids), 'stored_report_population_is_separate': True},
        'coverage': coverage, 'report_jobs': grouped_jobs, 'report_states': report_states, 'samples': samples,
        'coverage_is_stored_flags_not_completion_proof': True, 'mutations': 0}
'''
exec(compile('import json,re,sqlite3,time\nfrom datetime import date,datetime,timedelta,timezone\n'+PROJECTION_SOURCE,
             '<report-recovery-projection>', 'exec'))

ENRICHMENT_SOURCE = r'''
_base_collect = collect
BACKFILL_STATES = STATES | {'superseded'}


def collect(store, decisions, now, fingerprint, deadline):
    value = _base_collect(store, decisions, now, fingerprint, deadline)
    targets = {cid:row['possibility_id'] for cid,row in decisions.items()
        if row.get('matched') is True and row['decision'].cadence == 'daily' and row['decision'].attributable}
    pids = sorted(set(targets.values()))
    actual = {pid:[0,0,set()] for pid in pids}
    raw_rows, latest, backfill = 0, {}, []
    for offset in range(0, len(pids), 200):
        check_deadline(deadline)
        chunk = pids[offset:offset+200]
        marks = ','.join('?' for _ in chunk)
        owned = rows(store._conn, 'SELECT customer_id,possibility_id,day,basic_complete,conversion_complete,'
            'imp,clk,spend,conversions,conversion_value,checked_at,source_at '
            'FROM naver_auto_daily_performance WHERE possibility_id IN ('+marks+') AND day BETWEEN ? AND ?',
            (*chunk,START,END), MAX_ROWS-raw_rows, deadline)
        raw_rows += len(owned)
        for row in owned:
            check_deadline(deadline)
            number(row['customer_id'])
            day(row['day'])
            if row['basic_complete'] not in (0,1) or row['conversion_complete'] not in (0,1):
                raise ValueError('RECOVERY_FLAG')
            counts = actual[row['possibility_id']]
            counts[2].add(row['customer_id'])
            # This is the product aggregation predicate, never an inferred zero or just a stored flag.
            if R._collected(row, row['day'], now) is None:
                continue
            counts[0] += int(bool(row['basic_complete']) and all(R._number(row[key]) for key in R.BASIC_FIELDS))
            counts[1] += int(bool(row['conversion_complete']) and all(R._number(row[key]) for key in R.CONVERSION_FIELDS))
        snapshots = rows(store._conn, 'SELECT r.possibility_id,'
            "json_extract(r.payload_json,'$.coverage.expected_account_days') AS expected,"
            "json_extract(r.payload_json,'$.coverage.basic_complete_account_days') AS basic,"
            "json_extract(r.payload_json,'$.coverage.conversion_complete_account_days') AS conversion "
            'FROM naver_auto_report_snapshot r JOIN (SELECT MAX(report_id) AS report_id '
            'FROM naver_auto_report_snapshot WHERE possibility_id IN ('+marks+') AND period_key=? '
            'GROUP BY possibility_id) chosen ON chosen.report_id=r.report_id',
            (*chunk,KEYS[0]),len(chunk),deadline)
        for row in snapshots:
            latest[row['possibility_id']] = tuple(row[key] for key in ('expected','basic','conversion'))
    for offset in range(0, len(targets), 200):
        ids = sorted(targets)[offset:offset+200]
        marks = ','.join('?' for _ in ids)
        backfill.extend(rows(store._conn, 'SELECT customer_id,possibility_id,status,checked_at,last_success_at,next_try_at '
            'FROM naver_auto_performance_job WHERE customer_id IN ('+marks+") AND kind='backfill' "
            "AND period_start BETWEEN '2026-09-27' AND '2026-09-30' AND period_end='2026-09-30' "
            'AND period_start<=period_end ORDER BY checked_at,job_key', ids,MAX_ROWS-len(backfill),deadline))
    backfill = [row for row in backfill if targets.get(row['customer_id']) == row['possibility_id']]
    last = {}
    for row in backfill:
        check_deadline(deadline)
        for key in ('checked_at','last_success_at','next_try_at'):
            stamp(row[key])
        last[row['customer_id']] = enum(row['status'],BACKFILL_STATES)
    usable = {pid:counts for pid,counts in latest.items() if all(type(count) is int and count >= 0 for count in counts)
              and counts[1] <= counts[0] and counts[2] <= counts[0]}
    distribution = {}
    for counts in actual.values():
        distribution[counts[0]] = distribution.get(counts[0],0)+1
    value['monthly_valid_coverage'] = {
        'period_key':KEYS[0], 'current_companies':len(pids),'current_linked_accounts':len(targets),
        'raw_owned_account_memberships':sum(len(counts[2]) for counts in actual.values()),'raw_owned_rows':raw_rows,
        'raw_basic_valid_account_days':sum(counts[0] for counts in actual.values()),
        'raw_conversion_valid_account_days':sum(counts[1] for counts in actual.values()),
        'raw_basic_days_distribution':[{'account_days':count,'companies':companies} for count,companies in sorted(distribution.items())],
        'latest_snapshot_companies':len(latest),'latest_counts_missing_companies':len(latest)-len(usable),
        'latest_expected_account_days':sum(counts[0] for counts in usable.values()),
        'latest_basic_complete_account_days':sum(counts[1] for counts in usable.values()),
        'latest_conversion_complete_account_days':sum(counts[2] for counts in usable.values()),
        'latest_basic_complete_companies':sum(counts[0]>0 and counts[0]==counts[1] for counts in usable.values()),
        'latest_conversion_complete_companies':sum(counts[0]>0 and counts[0]==counts[2] for counts in usable.values()),
        'raw_basic_count_different_from_latest_companies':sum(actual[pid][0] != counts[1] for pid,counts in usable.items()),
        'raw_conversion_count_different_from_latest_companies':sum(actual[pid][1] != counts[2] for pid,counts in usable.items()),
        'comparison_is_counts_only':True}
    value['sample_valid_coverage'] = [{'possibility_id':pid,'raw_basic_valid_account_days':actual.get(pid,[0,0,set()])[0],
        'raw_conversion_valid_account_days':actual.get(pid,[0,0,set()])[1],
        'raw_owned_account_memberships':len(actual.get(pid,[0,0,set()])[2]),
        'latest_expected_account_days':usable[pid][0] if pid in usable else None,
        'latest_basic_complete_account_days':usable[pid][1] if pid in usable else None,
        'latest_conversion_complete_account_days':usable[pid][2] if pid in usable else None} for pid in SAMPLES]
    value['backfill_jobs'] = {'kind':'backfill','period_start_min':'2026-09-27','period_end':'2026-09-30',
        'jobs':len(backfill),'current_accounts_with_jobs':len(last),'current_accounts_without_jobs':len(targets)-len(last),
        'statuses':{state:sum(enum(row['status'],BACKFILL_STATES)==state for row in backfill) for state in sorted(BACKFILL_STATES|{'UNRECOGNIZED'})},
        'latest_account_statuses':{state:sum(status==state for status in last.values()) for state in sorted(BACKFILL_STATES|{'UNRECOGNIZED'})},
        'checked_at':time_bounds(row['checked_at'] for row in backfill),
        'last_success_at':time_bounds(row['last_success_at'] for row in backfill),
        'next_try_at':time_bounds(row['next_try_at'] for row in backfill),
        'ok_jobs_are_not_full_recovery_proof':True}
    check_deadline(deadline)
    return value
'''
PROJECTION_SOURCE += ENRICHMENT_SOURCE
exec(compile(ENRICHMENT_SOURCE, '<report-recovery-v19-enrichment>', 'exec'))


def validate_package(package):
    if (type(SOURCE) is not str or not re.fullmatch('[0-9a-f]{40}', SOURCE)
            or any(type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value) for value in (ARCHIVE, STORE))):
        raise ValueError('RECOVERY_TARGET_NOT_PINNED')
    expected = {'baseline': BASELINE, 'source_commit': SOURCE, 'source_tar_gz_sha256': ARCHIVE,
                'period': '2026-09', 'scope': 'current-managed-linked'}
    if type(package) is not dict or set(package) != set(expected):
        raise ValueError('RECOVERY_PACKAGE_FIELDS')
    if package != expected:
        raise ValueError('RECOVERY_PACKAGE_PIN')


def script():
    prefix = 'import hashlib,json,os,re,sqlite3,sys,time\nfrom pathlib import Path\nfrom datetime import date,datetime,timedelta,timezone\n'
    return (prefix+PROJECTION_SOURCE+'''
try:
    if os.geteuid()!=10001:
        raise ValueError('RECOVERY_IDENTITY')
    os.environ.clear()
    source=Path('/opt/naver-engine/naver_engine/store.py')
    if source.is_symlink() or not source.is_file() or source.stat().st_size>1048576 or hashlib.sha256(source.read_bytes()).hexdigest()!=__STORE_SHA__:
        raise ValueError('RECOVERY_STORE_PIN')
    sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
    from naver_engine import store as S, management_store as MS, reporting as R
    deadline=time.monotonic()+20
    connection=connect_reader(Path('/var/lib/naver-engine/engine.db'))
    reader=S.Store(connection,'/var/lib/naver-engine/engine.db',None,writer=False)
    try:
        connection.set_progress_handler(lambda: time.monotonic()>=deadline,1000)
        connection.execute('BEGIN')
        if connection.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()!=('11',):
            raise ValueError('RECOVERY_SCHEMA')
        if connection.execute('SELECT COUNT(*) FROM naver_auto_account').fetchone()[0]>MAX_ACCOUNTS:
            raise ValueError('RECOVERY_ACCOUNT_LIMIT')
        now=datetime.now(KST)
        result=collect(reader,MS.snapshot(reader,now),now,reader.decision_fingerprint(),deadline)
        if connection.total_changes!=0:
            raise ValueError('RECOVERY_MUTATION')
    finally:
        try:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
        finally:
            reader.close()
    print(json.dumps(result,sort_keys=True))
except Exception as error:
    code=str(error)
    print(json.dumps({'failure':code if re.fullmatch('RECOVERY_[A-Z_]{1,48}',code) else 'RECOVERY_READ_FAILED'}))
'''.replace('__STORE_SHA__', repr(STORE))).encode()


def validate_base_result(value):
    # Projected strings must be fixed enums, ISO dates/times or fixed scope/period labels.
    allowed = set(STATES) | set(ERRORS) | {'UNRECOGNIZED', 'complete', 'pending', 'failed',
        'report_monthly', 'report_weekly', 'current-managed-linked', '2026-09', *KEYS}
    def walk(item):
        if item is None or type(item) is bool:
            return
        if type(item) is int:
            number(item)
            return
        if type(item) is str:
            if item in allowed:
                return
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', item):
                day(item)
                return
            if stamp(item) != item:
                raise ValueError('RECOVERY_OUTPUT_TIME')
            return
        if type(item) is list:
            if len(item) > 100:
                raise ValueError('RECOVERY_OUTPUT_LIMIT')
            for entry in item:
                walk(entry)
            return
        if type(item) is dict:
            if len(item) > 64 or any(type(key) is not str or not re.fullmatch('[a-z_]{1,64}|[A-Z_]{1,64}', key) for key in item):
                raise ValueError('RECOVERY_OUTPUT_FIELDS')
            for entry in item.values():
                walk(entry)
            return
        raise ValueError('RECOVERY_OUTPUT_TYPE')
    if type(value) is not dict or set(value) != {'schema_version','period','observed_at','population','coverage',
            'report_jobs','report_states','samples','coverage_is_stored_flags_not_completion_proof','mutations'}:
        raise ValueError('RECOVERY_OUTPUT_FIELDS')
    def fields(item, expected):
        if type(item) is not dict or set(item) != set(expected.split()):
            raise ValueError('RECOVERY_OUTPUT_FIELDS')
    def bounds(item):
        fields(item, 'first last')
        for value in item.values():
            timestamp(value)
        if (item['first'] is None) != (item['last'] is None) or item['first'] is not None and item['first'] > item['last']:
            raise ValueError('RECOVERY_OUTPUT_TIME')
    def timestamp(value):
        if value is not None and (type(value) is not str or stamp(value) != value):
            raise ValueError('RECOVERY_OUTPUT_TIME')
    def member(value, allowed):
        if type(value) is not str or value not in allowed:
            raise ValueError('RECOVERY_OUTPUT_ENUM')
    def numbers(item, keys):
        for key in keys.split():
            number(item[key])
    for key in ('coverage','report_jobs','report_states','samples'):
        if type(value[key]) is not list:
            raise ValueError('RECOVERY_OUTPUT_TYPE')
    fields(value['population'], 'scope source_current accounts companies stored_report_population_is_separate')
    population = value['population']
    numbers(population, 'accounts companies')
    if (population['scope'] != 'current-managed-linked' or population['source_current'] is not True
            or population['stored_report_population_is_separate'] is not True or population['accounts'] > MAX_TARGETS):
        raise ValueError('RECOVERY_OUTPUT_SCOPE')
    for row in value['coverage']:
        fields(row, 'day expected_accounts current_pid_rows null_pid_rows other_pid_rows missing_rows basic_current_pid conversion_current_pid current_matching_rows before_attribution_days')
        numbers(row, 'expected_accounts current_pid_rows null_pid_rows other_pid_rows missing_rows basic_current_pid conversion_current_pid current_matching_rows before_attribution_days')
        if row['expected_accounts'] != population['accounts'] or sum(row[key] for key in ('current_pid_rows','null_pid_rows','other_pid_rows','missing_rows')) != population['accounts']:
            raise ValueError('RECOVERY_OUTPUT_COUNTS')
        if any(row[key] > row['current_pid_rows'] for key in ('basic_current_pid','conversion_current_pid','current_matching_rows')) or row['before_attribution_days'] > row['expected_accounts']:
            raise ValueError('RECOVERY_OUTPUT_COUNTS')
    for row in value['report_jobs']:
        fields(row, 'kind jobs statuses errors checked_at last_success_at next_try_at')
        member(row['kind'], {'report_monthly','report_weekly'})
        if type(row['statuses']) is not dict or set(row['statuses']) != STATES | {'UNRECOGNIZED'}:
            raise ValueError('RECOVERY_OUTPUT_FIELDS')
        if type(row['errors']) is not dict or set(row['errors']) - ERRORS - {'UNRECOGNIZED'}:
            raise ValueError('RECOVERY_OUTPUT_FIELDS')
        number(row['jobs'])
        for key in row['statuses']:
            number(row['statuses'][key])
        for key in row['errors']:
            number(row['errors'][key])
        if sum(row['statuses'].values()) != row['jobs']:
            raise ValueError('RECOVERY_OUTPUT_COUNTS')
        if sum(row['errors'].values()) > row['jobs'] or row['jobs'] > MAX_ROWS:
            raise ValueError('RECOVERY_OUTPUT_COUNTS')
        for key in ('checked_at','last_success_at','next_try_at'):
            bounds(row[key])
    for row in value['report_states']:
        fields(row, 'period_key current_companies snapshots validations dirty_pending validation_statuses validation_scope_matches_current')
        member(row['period_key'], set(KEYS))
        numbers(row, 'current_companies snapshots validations dirty_pending validation_scope_matches_current')
        fields(row['validation_statuses'], 'complete pending failed UNRECOGNIZED')
        for key in row['validation_statuses']:
            number(row['validation_statuses'][key])
        if (row['current_companies'] != population['companies'] or any(row[field] > row['current_companies']
                for field in ('snapshots','validations','dirty_pending','validation_scope_matches_current'))
                or sum(row['validation_statuses'].values()) != row['validations']):
            raise ValueError('RECOVERY_OUTPUT_COUNTS')
    for sample in value['samples']:
        fields(sample, 'possibility_id in_current_population accounts reports')
        number(sample['possibility_id'])
        if (type(sample['in_current_population']) is not bool or type(sample['accounts']) is not list or type(sample['reports']) is not list
                or len(sample['accounts']) > 8 or len(sample['reports']) != 6
                or sample['in_current_population'] != bool(sample['accounts'])):
            raise ValueError('RECOVERY_OUTPUT_SCOPE')
        for account in sample['accounts']:
            fields(account, 'customer_id attribution_start dates checked_at source_at source_generation latest_report_jobs')
            number(account['customer_id'])
            if account['attribution_start'] is not None:
                day(account['attribution_start'])
            fields(account['dates'], 'current_pid null_pid other_pid missing basic_current_pid conversion_current_pid current_matching before_attribution')
            for dates in account['dates'].values():
                if type(dates) is not list or len(dates) > 30 or dates != sorted(set(dates)) or any(not START <= day(at) <= END for at in dates):
                    raise ValueError('RECOVERY_OUTPUT_DATES')
            dates = account['dates']
            partition = [at for key in ('current_pid','null_pid','other_pid','missing') for at in dates[key]]
            if (len(partition) != 30 or len(set(partition)) != 30 or any(not set(dates[key]) <= set(dates['current_pid'])
                    for key in ('basic_current_pid','conversion_current_pid','current_matching'))):
                raise ValueError('RECOVERY_OUTPUT_DATES')
            for key in ('checked_at','source_at','source_generation'):
                bounds(account[key])
            if len(account['latest_report_jobs']) > 12:
                raise ValueError('RECOVERY_OUTPUT_LIMIT')
            for job in account['latest_report_jobs']:
                fields(job, 'customer_id possibility_id kind cycle_day period_start period_end status error_code checked_at last_success_at next_try_at generation attempts')
                numbers(job, 'customer_id possibility_id attempts')
                member(job['status'], STATES | {'UNRECOGNIZED'})
                if job['error_code'] is not None:
                    member(job['error_code'], ERRORS | {'UNRECOGNIZED'})
                for field in ('cycle_day','period_start','period_end'):
                    day(job[field])
                for field in ('checked_at','last_success_at','next_try_at','generation'):
                    timestamp(job[field])
                if job['customer_id'] != account['customer_id'] or job['possibility_id'] != sample['possibility_id'] or job['kind'] not in ('report_monthly','report_weekly'):
                    raise ValueError('RECOVERY_OUTPUT_SCOPE')
        for report in sample['reports']:
            required = {'period_key','dirty','raw_same_scope_comparable','raw_basic_current_pid','raw_conversion_current_pid'}
            if type(report) is not dict or not required <= set(report) or set(report)-required-{'validation','snapshot'}:
                raise ValueError('RECOVERY_OUTPUT_FIELDS')
            member(report['period_key'], set(KEYS))
            if report['dirty'] is not None:
                fields(report['dirty'], 'pending updated_at')
                if type(report['dirty']['pending']) is not bool:
                    raise ValueError('RECOVERY_OUTPUT_TYPE')
                timestamp(report['dirty']['updated_at'])
            if 'validation' in report:
                fields(report['validation'], 'expected status pending_account_days last_attempt_at last_checked_at')
                numbers(report['validation'], 'pending_account_days')
                member(report['validation']['status'], {'complete','pending','failed','UNRECOGNIZED'})
                timestamp(report['validation']['last_attempt_at'])
                timestamp(report['validation']['last_checked_at'])
                expected = report['validation']['expected']
                if type(expected) is not list or len(expected) > 100 or expected != sorted(set(expected)) or any(type(cid) is not int or cid <= 0 for cid in expected):
                    raise ValueError('RECOVERY_OUTPUT_SCOPE')
            if 'snapshot' in report:
                fields(report['snapshot'], 'generated_at coverage validation_status last_attempt_at last_checked_at')
                fields(report['snapshot']['coverage'], 'accounts expected_account_days basic_complete_account_days conversion_complete_account_days')
                member(report['snapshot']['validation_status'], {'complete','pending','failed','UNRECOGNIZED'})
                for field in ('generated_at','last_attempt_at','last_checked_at'):
                    timestamp(report['snapshot'][field])
                for count in report['snapshot']['coverage'].values():
                    if count is not None:
                        number(count)
                counts = report['snapshot']['coverage']
                if counts['expected_account_days'] is not None and any(counts[field] is not None and counts[field] > counts['expected_account_days']
                        for field in ('basic_complete_account_days','conversion_complete_account_days')):
                    raise ValueError('RECOVERY_OUTPUT_COUNTS')
            if type(report['raw_same_scope_comparable']) is not bool:
                raise ValueError('RECOVERY_OUTPUT_TYPE')
            for key in ('raw_basic_current_pid','raw_conversion_current_pid'):
                if report[key] is not None:
                    number(report[key])
                if report['raw_same_scope_comparable'] != (report[key] is not None):
                    raise ValueError('RECOVERY_OUTPUT_SCOPE')
        if [report['period_key'] for report in sample['reports']] != list(KEYS):
            raise ValueError('RECOVERY_OUTPUT_SCOPE')
    walk(value)
    timestamp(value['observed_at'])
    if (value['observed_at'] is None or type(value['schema_version']) is not int or value['schema_version'] != 11 or value['period'] != '2026-09'
            or type(value['mutations']) is not int or value['mutations'] != 0
            or value['coverage_is_stored_flags_not_completion_proof'] is not True
            or len(value['coverage']) != 30 or len(value['report_states']) != 6
            or [row['day'] for row in value['coverage']] != [str(date(2026,9,1)+timedelta(days=offset)) for offset in range(30)]
            or [row['period_key'] for row in value['report_states']] != list(KEYS)
            or [row['kind'] for row in value['report_jobs']] != ['report_monthly','report_weekly']
            or [sample.get('possibility_id') for sample in value['samples']] != list(SAMPLES)):
        raise ValueError('RECOVERY_OUTPUT_SCOPE')


def validate_result(value):
    extra = {'monthly_valid_coverage','sample_valid_coverage','backfill_jobs'}
    if type(value) is not dict or not extra <= set(value):
        raise ValueError('RECOVERY_OUTPUT_FIELDS')
    validate_base_result({key:item for key,item in value.items() if key not in extra})
    def fields(item, names):
        if type(item) is not dict or set(item) != set(names.split()):
            raise ValueError('RECOVERY_OUTPUT_FIELDS')
    def bounds(item):
        fields(item,'first last')
        for at in item.values():
            if at is not None and (type(at) is not str or stamp(at) != at):
                raise ValueError('RECOVERY_OUTPUT_TIME')
        if (item['first'] is None) != (item['last'] is None) or item['first'] is not None and item['first'] > item['last']:
            raise ValueError('RECOVERY_OUTPUT_TIME')
    monthly = value['monthly_valid_coverage']
    fields(monthly, 'period_key current_companies current_linked_accounts raw_owned_account_memberships raw_owned_rows '
        'raw_basic_valid_account_days raw_conversion_valid_account_days raw_basic_days_distribution '
        'latest_snapshot_companies latest_counts_missing_companies latest_expected_account_days '
        'latest_basic_complete_account_days latest_conversion_complete_account_days latest_basic_complete_companies '
        'latest_conversion_complete_companies raw_basic_count_different_from_latest_companies '
        'raw_conversion_count_different_from_latest_companies comparison_is_counts_only')
    for key in set(monthly)-{'period_key','raw_basic_days_distribution','comparison_is_counts_only'}:
        number(monthly[key])
    population = value['population']
    if (monthly['period_key'] != KEYS[0] or monthly['comparison_is_counts_only'] is not True
            or monthly['current_companies'] != population['companies']
            or monthly['current_linked_accounts'] != population['accounts']
            or monthly['raw_owned_rows'] > MAX_ROWS
            or any(monthly[key] > monthly['raw_owned_rows'] for key in ('raw_owned_account_memberships','raw_basic_valid_account_days','raw_conversion_valid_account_days'))
            or monthly['latest_snapshot_companies'] > population['companies']
            or any(monthly[key] > monthly['latest_snapshot_companies'] for key in ('latest_counts_missing_companies','latest_basic_complete_companies','latest_conversion_complete_companies','raw_basic_count_different_from_latest_companies','raw_conversion_count_different_from_latest_companies'))
            or monthly['latest_basic_complete_account_days'] > monthly['latest_expected_account_days']
            or monthly['latest_conversion_complete_account_days'] > monthly['latest_expected_account_days']):
        raise ValueError('RECOVERY_OUTPUT_COUNTS')
    distribution = monthly['raw_basic_days_distribution']
    if type(distribution) is not list or len(distribution) > 100:
        raise ValueError('RECOVERY_OUTPUT_LIMIT')
    for item in distribution:
        fields(item,'account_days companies')
        number(item['account_days']);number(item['companies'])
        if item['account_days'] > MAX_ROWS or item['companies'] == 0:
            raise ValueError('RECOVERY_OUTPUT_COUNTS')
    if ([item['account_days'] for item in distribution] != sorted({item['account_days'] for item in distribution})
            or sum(item['companies'] for item in distribution) != population['companies']
            or sum(item['account_days']*item['companies'] for item in distribution) != monthly['raw_basic_valid_account_days']):
        raise ValueError('RECOVERY_OUTPUT_COUNTS')
    samples = value['sample_valid_coverage']
    if type(samples) is not list or len(samples) != len(SAMPLES):
        raise ValueError('RECOVERY_OUTPUT_SCOPE')
    for item in samples:
        fields(item,'possibility_id raw_basic_valid_account_days raw_conversion_valid_account_days raw_owned_account_memberships '
            'latest_expected_account_days latest_basic_complete_account_days latest_conversion_complete_account_days')
        for key in ('possibility_id','raw_basic_valid_account_days','raw_conversion_valid_account_days','raw_owned_account_memberships'):
            number(item[key])
        latest = [item[key] for key in ('latest_expected_account_days','latest_basic_complete_account_days','latest_conversion_complete_account_days')]
        if not all(count is None for count in latest):
            for count in latest:
                number(count)
            if latest[1] > latest[0] or latest[2] > latest[0]:
                raise ValueError('RECOVERY_OUTPUT_COUNTS')
        if any(item[key] > monthly[total] for key,total in (
                ('raw_basic_valid_account_days','raw_basic_valid_account_days'),
                ('raw_conversion_valid_account_days','raw_conversion_valid_account_days'),
                ('raw_owned_account_memberships','raw_owned_account_memberships'))):
            raise ValueError('RECOVERY_OUTPUT_COUNTS')
    if [item['possibility_id'] for item in samples] != list(SAMPLES):
        raise ValueError('RECOVERY_OUTPUT_SCOPE')
    backfill = value['backfill_jobs']
    fields(backfill,'kind period_start_min period_end jobs current_accounts_with_jobs current_accounts_without_jobs '
        'statuses latest_account_statuses checked_at last_success_at next_try_at ok_jobs_are_not_full_recovery_proof')
    for key in ('jobs','current_accounts_with_jobs','current_accounts_without_jobs'):
        number(backfill[key])
    if (backfill['kind'] != 'backfill' or backfill['period_start_min'] != '2026-09-27' or backfill['period_end'] != '2026-09-30'
            or backfill['ok_jobs_are_not_full_recovery_proof'] is not True or backfill['jobs'] > MAX_ROWS
            or backfill['current_accounts_with_jobs']+backfill['current_accounts_without_jobs'] != population['accounts']
            or backfill['current_accounts_with_jobs'] > backfill['jobs']):
        raise ValueError('RECOVERY_OUTPUT_SCOPE')
    for key,total in (('statuses','jobs'),('latest_account_statuses','current_accounts_with_jobs')):
        values = backfill[key]
        if type(values) is not dict or set(values) != BACKFILL_STATES|{'UNRECOGNIZED'}:
            raise ValueError('RECOVERY_OUTPUT_FIELDS')
        for count in values.values():
            number(count)
        if sum(values.values()) != backfill[total]:
            raise ValueError('RECOVERY_OUTPUT_COUNTS')
    for key in ('checked_at','last_success_at','next_try_at'):
        bounds(backfill[key])


def validate_operation_result(result):
    validate_package({'baseline':BASELINE,'source_commit':SOURCE,'source_tar_gz_sha256':ARCHIVE,
                      'period':'2026-09','scope':'current-managed-linked'})
    if type(result) is not dict or set(result) != {'ok','mode','source_commit','reader_mode','mutations',
            'existing_app_baseline_unchanged','collection_completion_verified','diagnostics'}:
        raise ValueError('RECOVERY_RESULT_FIELDS')
    if any(type(result[key]) is not type(expected) or result[key] != expected for key, expected in {
            'ok':True,'mode':'report-recovery-diagnostics-v19','source_commit':SOURCE,
            'reader_mode':'sqlite-mode-ro-query-only-authorizer','mutations':0,
            'existing_app_baseline_unchanged':True,'collection_completion_verified':False}.items()):
        raise ValueError('RECOVERY_RESULT_PIN')
    validate_result(result['diagnostics'])


def run(package, host, release):
    global STAGE
    STAGE = 'preflight'
    validate_package(package)
    if os.geteuid() != 0 or host.baseline() != BASELINE:
        raise ValueError('HOST_BASELINE')
    path, prepared_path = release.prepared_paths(SOURCE)
    start_path = prepared_path.with_name('preview-start-'+SOURCE+'.json')
    release.trusted_private_file(start_path)
    if any(item.stat().st_size > 32768 for item in (prepared_path, start_path)):
        raise ValueError('RECEIPT_SIZE')
    prepared = json.loads(prepared_path.read_bytes(), object_pairs_hook=release.unique)
    started = json.loads(start_path.read_bytes(), object_pairs_hook=release.unique)
    if (prepared.get('ok') is not True or prepared.get('stage') != 'prepared'
            or prepared.get('source_commit') != SOURCE or started.get('ok') is not True
            or started.get('stage') != 'internal_ready' or started.get('source_commit') != SOURCE
            or any(prepared.get('package', {}).get(key) != package[key] for key in ('baseline','source_commit','source_tar_gz_sha256'))):
        raise ValueError('SOURCE_NOT_READY')
    for file in (path/'compose.naver-engine.yml', path/'preview-engine.override.yml', path/'deploy/naver-engine-backup.override.yml'):
        if file.resolve() != file or release.sha(file.read_bytes()) != prepared.get('files', {}).get(str(file)):
            raise ValueError('COMPOSE_CHANGED')
    image_id = prepared.get('images', {}).get('engine')
    if type(image_id) is not str or not re.fullmatch('sha256:[0-9a-f]{64}', image_id):
        raise ValueError('PREPARED_IMAGE')
    fmt = '{"id":{{json .Id}},"user":{{json .Config.User}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}'
    image = json.loads(release.command(['docker','image','inspect','--format',fmt,'metainc/naver-engine:'+SOURCE]))
    if image != {'id': image_id, 'user': '10001:10001', 'source': SOURCE}:
        raise ValueError('PREPARED_IMAGE_CHANGED')
    identity = release.command(release.compose(path,'engine')+['ps','--all','--quiet']).decode().strip()
    if not re.fullmatch('[0-9a-f]{64}', identity):
        raise ValueError('PREVIEW_CONTAINER_ID')
    fmt = '{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"user":{{json .Config.User}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"started":{{json .State.StartedAt}},"restarts":{{json .RestartCount}},"readonly":{{json .HostConfig.ReadonlyRootfs}},"data":[{{range .Mounts}}{{if eq .Destination "/var/lib/naver-engine"}}{{json .}}{{end}}{{end}}]}'
    def container():
        return json.loads(release.command(['docker','inspect','--format',fmt,identity]))
    before = container()
    if (any(before.get(key) != value for key, value in {'id':identity,'image':image_id,'running':True,'user':'10001:10001',
            'project':'naver-engine','service':'naver-engine','readonly':True}.items())):
        raise ValueError('PREVIEW_CONTAINER_CHANGED')
    mounts = before.get('data')
    if (not isinstance(mounts,list) or len(mounts)!=1 or not isinstance(mounts[0],dict)
            or any(mounts[0].get(key)!=value for key,value in {'Type':'bind','Destination':'/var/lib/naver-engine',
                'Source':'/var/lib/metainc/naver-engine'}.items())):
        raise ValueError('PREVIEW_DATA_MOUNT')
    STAGE = 'read_only_report_recovery'
    failure = None
    try:
        raw = release.command(['docker','exec','-i','--user','10001:10001',identity,'python','-I','-B','-'], data=script(), timeout=30)
    except Exception:
        failure = ValueError('RECOVERY_READER_FAILED')
    finally:
        STAGE = 'postflight'
        if container()!=before or host.baseline()!=BASELINE:
            raise ValueError('POST_BASELINE')
    if failure is not None:
        raise failure from None
    if len(raw)>MAX_OUTPUT:
        raise ValueError('RECOVERY_OUTPUT_LIMIT')
    value = json.loads(raw, object_pairs_hook=release.unique)
    if type(value) is dict and set(value)=={'failure'}:
        raise ValueError(value['failure'] if type(value['failure']) is str and re.fullmatch('RECOVERY_[A-Z_]{1,48}',value['failure']) else 'RECOVERY_READ_FAILED')
    validate_result(value)
    result = {'ok':True,'mode':'report-recovery-diagnostics-v19','source_commit':SOURCE,
        'reader_mode':'sqlite-mode-ro-query-only-authorizer','mutations':0,'existing_app_baseline_unchanged':True,
        'collection_completion_verified':False,'diagnostics':value}
    validate_operation_result(result)
    return result
