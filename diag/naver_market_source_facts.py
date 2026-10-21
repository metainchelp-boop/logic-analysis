"""시장 내보내기 원천 크기 — 읽기 전용 · 개수·바이트·초만 · 업체명·키워드·자료 본문 미출력.

운영 서버(root)에서 한 번 실행한다. 시장 내보내기(`backend/naver_market_export.py`)는 원천 DB 의
네 표를 읽으며 읽은 줄 합이 10만 줄, 읽은 글자 합이 32MiB, 걸린 시간이 30초를 넘으면 `SOURCE_LIMIT` 로 멈춘다.
그중 `collector_observations` 는 조건 없이 통째로 읽는다. 어느 한도에 걸렸는지 같은 질의 모양으로 잰다.

원천 DB 는 `mode=ro` + `query_only` + 읽기만 허용하는 authorizer 로 연다. WAL·SHM 파일이 이미 있을 때만 연다
(없으면 새로 만들지 않도록 열지 않고 끝낸다). 진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
"""
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone

MODE = 'naver-market-source-facts-v1'
KST = timezone(timedelta(hours=9))
DATABASE = '/root/logic-analysis-deploy/data/logic_data.db'
MAX_ROWS = 100000
MAX_INPUT = 32 * 1024 * 1024
MAX_SECONDS = 30
DEADLINE = 45
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')
HEADER = [('observation_id', 100), ('keyword', 8192), ('collected_date', 100), ('status', 100),
          ('kind', 100), ('reason', 300), ('received_at', 200)]


def auth(action, a1, a2, db, src):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_TRANSACTION):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (a2 or '').lower() in ('count', 'length', 'coalesce', 'sum', 'max', 'min', 'substr'):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def scan(c, table, columns, where='', params=()):
    """내보내기와 같은 모양: 열마다 길이와 (한도 안이면) 값. 줄 수·바이트·초·한도 넘는 칸 수만 센다."""
    expressions = []
    for name, cap in columns:
        expressions.extend(('length(CAST(%s AS BLOB))' % name, 'CASE WHEN length(CAST(%s AS BLOB))<=%d THEN 1 END' % (name, cap)))
    started = time.monotonic()
    rows = size = over = 0
    for row in c.execute('SELECT %s FROM %s %s' % (','.join(expressions), table, where), params):
        rows += 1
        sizes = row[::2]
        size += sum(s or 0 for s in sizes)
        over += any(s is not None and s > cap for s, (_, cap) in zip(sizes, columns))
        if time.monotonic() - started > DEADLINE:
            return dict(rows=rows, bytes=size, cells_over_cap=over, seconds=round(time.monotonic() - started, 2), cut=True)
    return dict(rows=rows, bytes=size, cells_over_cap=over, seconds=round(time.monotonic() - started, 2), cut=False)


def main():
    result = dict(mode=MODE, ok=False, mutations=0, stage='preflight')
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        for suffix in ('', '-wal', '-shm'):
            path = DATABASE + suffix
            if os.path.islink(path) or not os.path.isfile(path):
                raise ValueError('SOURCE_FILES_MISSING')
        result['files_mb'] = {k or 'db': round(os.lstat(DATABASE + k).st_size / 1048576, 1) for k in ('', '-wal')}
        result['stage'] = 'open'
        c = sqlite3.connect('file:%s?mode=ro' % DATABASE, uri=True, isolation_level=None, timeout=1)
        try:
            c.execute('PRAGMA query_only=ON')
            c.execute('PRAGMA busy_timeout=1000')
            if c.execute('PRAGMA query_only').fetchone() != (1,):
                raise ValueError('READER_MODE')
            c.set_authorizer(auth)
            c.execute('BEGIN')
            result['stage'] = 'growth'
            days = {}
            since = (datetime.now(KST) - timedelta(days=14)).strftime('%Y-%m-%d')
            for day, n in c.execute('SELECT substr(collected_date,1,10), count(*) FROM collector_observations '
                                    'WHERE collected_date>=? GROUP BY substr(collected_date,1,10)', (since,)):
                if isinstance(day, str) and DAY.fullmatch(day):
                    days[day] = n
            result['observations_by_collected_date_14d'] = dict(sorted(days.items()))
            older = c.execute('SELECT count(*) FROM collector_observations WHERE collected_date<?', (since,)).fetchone()[0]
            result['observations_before_window'] = older
            first = c.execute('SELECT min(substr(collected_date,1,10)) FROM collector_observations').fetchone()[0]
            result['oldest_collected_date'] = first if isinstance(first, str) and DAY.fullmatch(first) else None
            result['collected_serp_rows'] = c.execute('SELECT count(*) FROM collected_serp').fetchone()[0]
            result['observations_rows'] = c.execute('SELECT count(*) FROM collector_observations').fetchone()[0]
            result['stage'] = 'scan'
            t = {}
            t['clients_store_advertisers'] = scan(c, 'clients', [('id', 30), ('naver_store_url', 8192), ('main_keywords', 8192)],
                                                  "WHERE role='advertiser' AND COALESCE(vertical,'store')='store'")
            t['client_keyword_product'] = scan(c, 'client_keyword_product', [('client_id', 30), ('keyword', 8192), ('product_url', 8192)])
            t['client_keyword_mute'] = scan(c, 'client_keyword_mute', [('client_id', 30), ('keyword', 8192)])
            t['collector_observations'] = scan(c, 'collector_observations', HEADER)
            result['tables'] = t
            total_rows = sum(v['rows'] for v in t.values())
            total_bytes = sum(v['bytes'] for v in t.values())
            total_seconds = round(sum(v['seconds'] for v in t.values()), 2)
            result['totals'] = dict(rows=total_rows, bytes=total_bytes, seconds=total_seconds)
            result['limits'] = dict(rows=MAX_ROWS, bytes=MAX_INPUT, seconds=MAX_SECONDS)
            result['over'] = dict(rows=total_rows > MAX_ROWS, bytes=total_bytes > MAX_INPUT, seconds=total_seconds > MAX_SECONDS,
                                  cell_cap=any(v['cells_over_cap'] for v in t.values()))
            c.execute('COMMIT')
        finally:
            c.close()
        result['ok'] = True
        result['stage'] = 'done'
    except Exception as error:
        text = str(error)
        result['error'] = text if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}', text) else type(error).__name__
    print('NAVER_MARKET_SOURCE_FACTS_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
