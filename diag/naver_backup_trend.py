"""네이버 관제 엔진 DB 증가 추세 — 밤 백업 압축본의 manifest(표별 줄 수·만든 시각)와 snapshot 크기만 읽는다.

로컬 백업 압축본(최대 7개)의 목차와 manifest.json(1 MiB 이하)만 읽고 본문은 풀지 않는다(디스크 쓰기 0).
날짜별 DB 크기와 줄 수가 늘어난 표의 하루 증가량을 출력한다. 표 이름은 코드 식별자이며 업체명·계정번호는 없다.
진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
"""
import json
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone

MODE = 'naver-backup-trend-v1'
LOCAL = '/var/backups/metainc/naver-engine/local'
NAME = re.compile(r'naver-\d{8}T\d{6}Z-[0-9a-f]{32}\.zip')
TABLE = re.compile(r'[a-z_][a-z0-9_]{0,63}')
KST = timezone(timedelta(hours=9))


def main():
    result = dict(mode=MODE, ok=False, mutations=0)
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        points = []
        for name in sorted(n for n in os.listdir(LOCAL) if NAME.fullmatch(n)):
            path = os.path.join(LOCAL, name)
            with zipfile.ZipFile(path) as packed:
                if packed.getinfo('manifest.json').file_size > 1024 * 1024:
                    raise ValueError('MANIFEST_SIZE')
                manifest = json.loads(packed.read('manifest.json'))
                size = packed.getinfo('snapshot.sqlite').file_size
            counts = manifest.get('row_counts') or {}
            created = datetime.fromisoformat(manifest['created_at']).astimezone(KST)
            points.append(dict(at=created.strftime('%Y-%m-%d %H:%M'), snapshot_bytes=size, archive_bytes=os.path.getsize(path),
                               rows={k: v for k, v in counts.items() if TABLE.fullmatch(k) and type(v) is int}))
        if len(points) < 2:
            raise ValueError('NOT_ENOUGH_BACKUPS')
        first, last = points[0], points[-1]
        days = (datetime.strptime(last['at'], '%Y-%m-%d %H:%M') - datetime.strptime(first['at'], '%Y-%m-%d %H:%M')).total_seconds() / 86400
        growth = {}
        for table in sorted(set(first['rows']) | set(last['rows'])):
            before, after = first['rows'].get(table, 0), last['rows'].get(table, 0)
            if after != before:
                growth[table] = dict(first=before, last=after, per_day=round((after - before) / days, 1),
                                     daily=[p['rows'].get(table) for p in points])
        result.update(
            backups=[dict(at=p['at'], snapshot_bytes=p['snapshot_bytes'], archive_bytes=p['archive_bytes'],
                          tables=len(p['rows']), total_rows=sum(p['rows'].values())) for p in points],
            span_days=round(days, 2),
            snapshot_bytes_per_day=round((last['snapshot_bytes'] - first['snapshot_bytes']) / days),
            growing_tables=dict(sorted(growth.items(), key=lambda kv: -abs(kv[1]['per_day']))),
            static_tables=len(set(last['rows']) - set(growth)),
            ok=True)
    except Exception as error:
        result['error'] = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}', str(error)) else type(error).__name__
    print('NAVER_BACKUP_TREND_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
