"""네이버 관제 밤 백업 사실 확인 — 읽기 전용 · 시각·크기·개수만 출력.

엔진 백업 폴더의 state.json(상태 코드·시각만), 로컬 zip·보낼 cms 크기와 만든 시각, 남은 임시 폴더(.building-*),
bootstrap 사본, 엔진 DB·WAL 크기, 그리고 지금 판 엔진 이미지의 SQLite 컴파일 옵션(SECURE_DELETE 여부)을
네트워크 없는 일회용 컨테이너에서 읽는다. 아무것도 지우거나 바꾸지 않는다.
진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
"""
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone

MODE = 'naver-backup-facts-v1'
ROOT = '/var/backups/metainc/naver-engine'
DB = '/var/lib/metainc/naver-engine/engine.db'
IMAGE = 'metainc/naver-engine:382f143ad72a5fb0389d79ba0fac199566016e8b'
NAME = re.compile(r'naver-(\d{8}T\d{6}Z)-[0-9a-f]{32}\.(zip|cms)')
KST = timezone(timedelta(hours=9))
STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(\+00:00|Z)?')


def kst(ts):
    return datetime.fromtimestamp(ts, KST).strftime('%Y-%m-%d %H:%M:%S')


def listing(folder):
    out = []
    try:
        names = sorted(os.listdir(folder))
    except FileNotFoundError:
        return None
    for name in names:
        path = os.path.join(folder, name)
        st = os.lstat(path)
        m = NAME.fullmatch(name)
        if m:
            created = datetime.strptime(m.group(1), '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            out.append(dict(kind=m.group(2), named_kst=created.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S'),
                            mtime_kst=kst(st.st_mtime), seconds_after_name=round(st.st_mtime - created.timestamp()),
                            bytes=st.st_size))
        else:
            size = st.st_size
            if os.path.isdir(path) and not os.path.islink(path):
                size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(path) for f in fs)
            label = 'building' if name.startswith('.building-') else 'state' if name == 'state.json' else \
                'state_tmp' if name.startswith('.state-') else 'OTHER'
            out.append(dict(kind=label, mtime_kst=kst(st.st_mtime), bytes=size, directory=os.path.isdir(path)))
    return out


def main():
    result = dict(mode=MODE, ok=False, mutations=0)
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        try:
            state = json.load(open(os.path.join(ROOT, 'state.json')))
            result['state'] = {k: (v if isinstance(v, str) and (STAMP.fullmatch(v) or re.fullmatch(r'[A-Z_]{1,40}|\d{4}-\d{2}-\d{2}', v))
                                   else (None if v is None else ('SET' if k in ('pending', 'last_local_file') else 'OTHER')))
                               for k, v in state.items() if k != 'version'}
        except Exception as error:
            result['state'] = dict(error=type(error).__name__)
        result['root'] = listing(ROOT)
        result['local'] = listing(os.path.join(ROOT, 'local'))
        result['outgoing'] = listing(os.path.join(ROOT, 'outgoing'))
        boot = listing(os.path.join(ROOT, 'bootstrap'))
        result['bootstrap'] = None if boot is None else dict(count=len(boot), bytes=sum(i['bytes'] for i in boot))
        total = 0
        for dp, _, fs in os.walk(ROOT):
            for f in fs:
                try:
                    total += os.lstat(os.path.join(dp, f)).st_size
                except OSError:
                    pass
        result['backup_dir_bytes'] = total
        result['db_files'] = {s or 'db': (os.path.getsize(DB + s) if os.path.exists(DB + s) else None) for s in ('', '-wal', '-shm')}
        probe = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '10001:10001',
                                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--memory', '128m',
                                IMAGE, 'python', '-I', '-B', '-c',
                                'import sqlite3,json;c=sqlite3.connect(":memory:");'
                                'print(json.dumps({"version":sqlite3.sqlite_version,'
                                '"options":[r[0] for r in c.execute("pragma compile_options")],'
                                '"secure_delete_default":c.execute("pragma secure_delete").fetchone()[0]}))'],
                               capture_output=True, timeout=120)
        lines = probe.stdout.decode('utf-8', 'replace').strip().splitlines()
        info = json.loads(lines[-1]) if probe.returncode == 0 and lines else {}
        result['engine_sqlite'] = dict(version=info.get('version'), secure_delete_default=info.get('secure_delete_default'),
                                       options=[o for o in info.get('options', []) if re.fullmatch(r'[A-Z0-9_=]{1,60}', o)],
                                       probe_exit=probe.returncode)
        result['ok'] = True
    except Exception as error:
        result['error'] = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}', str(error)) else type(error).__name__
    print('NAVER_BACKUP_FACTS_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
