"""시장 내보내기 실측 — 서버에 설치된 내보내기 코드의 읽기 단계(collect)만 그대로 돌려 시간·글자 수·줄 수를 잰다.

운영 서버(root)에서 한 번 실행한다. 설치본(`/opt/metainc/naver-saved-exports/<ops>/naver_market_export.py`)을
바이트코드를 쓰지 않고(-B) 불러, 원천 DB 를 `mode=ro` 로 연 뒤 `collect()` 만 부른다. 결과 파일을 쓰는
`export_database()` 는 부르지 않는다 — 묶음·서비스·타이머·원천 DB 어느 것도 바꾸지 않는다.
collect() 는 자체 authorizer·query_only 로 읽기만 한다. 원천 DB 는 WAL 이라 읽는 동안 수집기 쓰기를 막지 않는다.

1회차: 시간 상한만 120초로 늘려(다른 한도는 그대로) 실제로 몇 초·몇 바이트가 드는지 잰다.
2회차: 설치본 기본 한도 그대로 — 지금(캐시가 데워진 상태) 돌리면 통과하는지만 본다.
출력은 상태 코드·초·바이트·줄 수·묶음의 가게 수·표본 수뿐이다. 진단 전용 갈래 — main 에 합치지 않는다.
"""
import dataclasses
import importlib.util
import json
import os
import re
import sqlite3
import sys
import time

MODE = 'naver-market-export-probe-v1'
INSTALL = '/opt/metainc/naver-saved-exports/19586caf7fe5579e7da70d4a2d4205c3ed603996'
DATABASE = '/root/logic-analysis-deploy/data/logic_data.db'
TABLES = ('clients', 'client_keyword_product', 'client_keyword_mute', 'collector_observations', 'collected_serp')


def load():
    sys.dont_write_bytecode = True
    path = os.path.join(INSTALL, 'naver_market_export.py')
    for name in ('naver_market_export.py', 'naver_product_export.py'):
        full = os.path.join(INSTALL, name)
        if os.path.islink(full) or not os.path.isfile(full):
            raise ValueError('INSTALL_PATH')
    spec = importlib.util.spec_from_file_location('probe_naver_market_export', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def instrument(M):
    """_rows 를 감싸 표별 줄·글자·초를 센다(원래 함수 그대로 부르고 값은 버리지 않는다)."""
    stats = {t: dict(calls=0, rows=0, seconds=0.0) for t in TABLES}
    original = M._rows

    def rows(conn, table, columns, budget, limits, where='', params=()):
        item = stats.setdefault(table if table in TABLES else 'OTHER', dict(calls=0, rows=0, seconds=0.0))
        item['calls'] += 1
        started = time.monotonic()
        try:
            for value in original(conn, table, columns, budget, limits, where, params):
                item['rows'] += 1
                item['seconds'] += time.monotonic() - started
                yield value
                started = time.monotonic()
        finally:
            item['seconds'] += time.monotonic() - started
    M._rows = rows
    return stats


def attempt(M, limits):
    holder = {}
    base = M.P._Budget

    class Budget(base):
        def __init__(self, value):
            super().__init__(value)
            holder['budget'] = self
    M.P._Budget = Budget
    stats = instrument(M)
    started = time.monotonic()
    out = dict()
    c = sqlite3.connect('file:%s?mode=ro' % DATABASE, uri=True, isolation_level=None, timeout=1)
    try:
        bundle = M.collect(c, limits=limits)
        out.update(ok=True, stores=len(bundle['stores']),
                   cohorts=sum(len(s['cohorts']) for s in bundle['stores']),
                   statuses={k: sum(1 for s in bundle['stores'] if s['status'] == k) for k in ('ok', 'no_observations', 'ambiguous')},
                   bytes_out=len(M.P.encode(bundle, limits)))
    except Exception as error:
        text = getattr(error, 'code', None) or str(error)
        out.update(ok=False, error=text if isinstance(text, str) and re.fullmatch(r'[A-Z_]{1,40}', text) else type(error).__name__)
    finally:
        c.close()
        M.P._Budget = base
    budget = holder.get('budget')
    out['seconds'] = round(time.monotonic() - started, 2)
    out['budget'] = dict(rows=getattr(budget, 'rows', None), bytes=getattr(budget, 'bytes', None))
    out['tables'] = {k: dict(v, seconds=round(v['seconds'], 2)) for k, v in stats.items()}
    return out


def main():
    result = dict(mode=MODE, ok=False, mutations=0, stage='preflight')
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        with open(DATABASE, 'rb') as stream:
            head = stream.read(100)
        if head[:16] != b'SQLite format 3\x00' or head[18] != 2 or head[19] != 2:
            raise ValueError('SOURCE_NOT_WAL')
        if not (os.path.isfile(DATABASE + '-wal') and os.path.isfile(DATABASE + '-shm')):
            raise ValueError('SOURCE_FILES_MISSING')
        result['stage'] = 'load'
        M = load()
        defaults = M.Limits()
        result['default_limits'] = dataclasses.asdict(defaults) if dataclasses.is_dataclass(defaults) else None
        result['stage'] = 'relaxed'
        result['relaxed_time_only'] = attempt(M, dataclasses.replace(defaults, max_seconds=120))
        result['stage'] = 'default'
        M = load()
        result['default_now'] = attempt(M, M.Limits())
        result['ok'] = True
        result['stage'] = 'done'
    except Exception as error:
        text = str(error)
        result['error'] = text if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}', text) else type(error).__name__
    print('NAVER_MARKET_EXPORT_PROBE_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
