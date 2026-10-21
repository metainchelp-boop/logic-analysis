"""시장 내보내기 원천 크기 — 읽기 전용 · 개수·바이트만 · 업체명·키워드·자료 본문 미출력.

운영 서버(root)에서 한 번 실행한다. 시장 내보내기(`backend/naver_market_export.py`)는 원천 DB 의
표를 읽으며 읽은 줄 합이 10만 줄, 읽은 글자 합이 32MiB, 걸린 시간이 30초를 넘으면 `SOURCE_LIMIT` 로 멈춘다.
그중 `collector_observations` 는 조건 없이 통째로 읽는다. 줄 수 한도에 걸렸는지 개수로만 잰다.

원천 DB 는 `mode=ro` + `query_only` + 읽기만 허용하는 authorizer 로 연다. 파일 머리글로 저장 방식을 먼저 보고
WAL 이면 곁 파일이 이미 있을 때만, 롤백 저널이면 남은 저널이 없을 때만 연다(어떤 파일도 새로 만들지 않는다).
수집기 쓰기를 막지 않도록 긴 트랜잭션 없이 짧은 개수 문장만 하나씩 돌리고, 문장마다 10초 상한을 둔다.
진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
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
STATEMENT_SECONDS = 10
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')


def auth(action, a1, a2, db, src):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_TRANSACTION):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (a2 or '').lower() in ('count', 'length', 'coalesce', 'sum', 'max', 'min', 'substr'):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def main():
    result = dict(mode=MODE, ok=False, mutations=0, stage='preflight')
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        if os.path.islink(DATABASE) or not os.path.isfile(DATABASE):
            raise ValueError('SOURCE_PATH')
        present = {k: os.path.isfile(DATABASE + k) and not os.path.islink(DATABASE + k) for k in ('-wal', '-shm', '-journal')}
        result['side_files'] = present
        with open(DATABASE, 'rb') as stream:
            head = stream.read(100)
        if len(head) < 100 or head[:16] != b'SQLite format 3\x00':
            raise ValueError('SOURCE_HEADER')
        result['header_write_read_version'] = [head[18], head[19]]    # 1 = 롤백 저널 · 2 = WAL
        if head[18] == 2 or head[19] == 2:
            if not (present['-wal'] and present['-shm']):
                raise ValueError('SOURCE_FILES_MISSING')                 # WAL 인데 곁 파일이 없으면 새로 만들지 않게 열지 않는다
        elif head[18] != 1 or head[19] != 1 or present['-journal']:
            raise ValueError('SOURCE_JOURNAL_STATE')                     # 남은 롤백 저널이 있으면 열지 않는다
        result['files_mb'] = {k or 'db': round(os.lstat(DATABASE + k).st_size / 1048576, 1)
                              for k in ('', '-wal') if k == '' or present[k]}
        result['stage'] = 'open'
        c = sqlite3.connect('file:%s?mode=ro' % DATABASE, uri=True, isolation_level=None, timeout=1)
        try:
            c.execute('PRAGMA query_only=ON')
            c.execute('PRAGMA busy_timeout=1000')
            if c.execute('PRAGMA query_only').fetchone() != (1,):
                raise ValueError('READER_MODE')
            c.set_authorizer(auth)
            clock = {'start': time.monotonic()}
            c.set_progress_handler(lambda: 1 if time.monotonic() - clock['start'] > STATEMENT_SECONDS else 0, 10000)

            def one(sql, params=()):
                clock['start'] = time.monotonic()
                return c.execute(sql, params).fetchall()
            result['stage'] = 'growth'
            days = {}
            since = (datetime.now(KST) - timedelta(days=14)).strftime('%Y-%m-%d')
            for day, n in one('SELECT substr(collected_date,1,10), count(*) FROM collector_observations '
                              'WHERE collected_date>=? GROUP BY substr(collected_date,1,10)', (since,)):
                if isinstance(day, str) and DAY.fullmatch(day):
                    days[day] = n
            result['observations_by_collected_date_14d'] = dict(sorted(days.items()))
            older = one('SELECT count(*) FROM collector_observations WHERE collected_date<?', (since,))[0][0]
            result['observations_before_window'] = older
            first = one('SELECT min(substr(collected_date,1,10)) FROM collector_observations')[0][0]
            result['oldest_collected_date'] = first if isinstance(first, str) and DAY.fullmatch(first) else None
            result['collected_serp_rows'] = one('SELECT count(*) FROM collected_serp')[0][0]
            result['observations_rows'] = one('SELECT count(*) FROM collector_observations')[0][0]
            result['stage'] = 'scan'
            t = {}
            for label, table, columns, where in (
                    ('clients_store_advertisers', 'clients', ('id', 'naver_store_url', 'main_keywords'),
                     "WHERE role='advertiser' AND COALESCE(vertical,'store')='store'"),
                    ('client_keyword_product', 'client_keyword_product', ('client_id', 'keyword', 'product_url'), ''),
                    ('client_keyword_mute', 'client_keyword_mute', ('client_id', 'keyword'), '')):
                started = time.monotonic()
                rows, size = one('SELECT count(*), coalesce(sum(%s),0) FROM %s %s' % (
                    '+'.join('coalesce(length(CAST(%s AS BLOB)),0)' % col for col in columns), table, where))[0]
                t[label] = dict(rows=rows, bytes=size, seconds=round(time.monotonic() - started, 2))
            t['collector_observations'] = dict(rows=result['observations_rows'], bytes=None, seconds=None)
            result['tables'] = t
            total_rows = sum(v['rows'] for v in t.values())
            result['totals'] = dict(rows=total_rows)
            result['limits'] = dict(rows=MAX_ROWS, bytes=MAX_INPUT, seconds=MAX_SECONDS)
            result['over'] = dict(rows=total_rows > MAX_ROWS)
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
