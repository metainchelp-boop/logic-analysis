"""네이버 관제 서버 저장 공간 원인 확인 — 읽기 전용 · 집계만 · 업체명·계정번호 미출력.

호스트(root): df · docker system df · 이미지 목록(저장소·태그·크기) · 주요 폴더 du · journal 크기.
엔진 DB: 컨테이너 안 UID 10001 로 mode=ro + query_only + 쓰기 거부 authorizer,
표·색인별 크기(dbstat)와 큰 표의 날짜별 행 수. 아무것도 지우거나 바꾸지 않는다.
진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
"""
import json
import os
import re
import subprocess

MODE = 'naver-engine-storage-v1'
CODE = re.compile(r'[A-Za-z][A-Za-z0-9_.:/-]{0,95}')

READER = r'''
import json,os,re,socket,sqlite3,time
from pathlib import Path
NAME=re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,95}')
DAY=re.compile(r'\d{4}-\d{2}-\d{2}')
DATE_COLUMNS=('cycle_day','day','run_date','observed_at','created_at','recorded_at','checked_at','updated_at','at','received_at','captured_at','started_at','fired_at','ts')
def auth(action,a1,a2,db,src):
    if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_TRANSACTION):
        return sqlite3.SQLITE_OK
    if action==sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (a2 or '').lower() in ('load_extension','readfile','writefile','shell','eval','fts3_tokenizer') else sqlite3.SQLITE_OK
    if action==sqlite3.SQLITE_PRAGMA and (a1 or '').lower() in ('table_info','page_count','page_size','freelist_count'):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY
out={};stage='start'
try:
    if os.geteuid()!=10001:
        raise ValueError('READER_IDENTITY')
    def no_network(*a,**k):
        raise ValueError('READER_NETWORK_FORBIDDEN')
    socket.socket.connect=socket.socket.connect_ex=no_network
    path=Path('/var/lib/naver-engine/engine.db')
    c=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,isolation_level=None,timeout=1)
    c.execute('PRAGMA query_only=ON');c.execute('PRAGMA busy_timeout=1000');c.execute('PRAGMA trusted_schema=OFF')
    if c.execute('PRAGMA query_only').fetchone()!=(1,):
        raise ValueError('READER_MODE')
    c.set_authorizer(auth)
    deadline=time.monotonic()+90
    c.set_progress_handler(lambda:time.monotonic()>=deadline,1000)
    try:
        stage='pages'
        size=c.execute('PRAGMA page_size').fetchone()[0];pages=c.execute('PRAGMA page_count').fetchone()[0];free=c.execute('PRAGMA freelist_count').fetchone()[0]
        out['page_size']=size;out['total_mb']=round(size*pages/1048576,1);out['free_pages_mb']=round(size*free/1048576,1)
        stage='objects'
        objects={r[0]:(r[1],r[2]) for r in c.execute("SELECT name,type,tbl_name FROM sqlite_schema WHERE type IN ('table','index')")}
        stage='counts'
        tables=sorted(n for n,(kind,_) in objects.items() if kind=='table' and NAME.fullmatch(n) and not n.startswith('sqlite_'))
        counts={}
        for t in tables:
            deadline_q=time.monotonic()+6
            c.set_progress_handler(lambda:time.monotonic()>=deadline_q or time.monotonic()>=deadline,1000)
            try:
                counts[t]=c.execute('SELECT count(*) FROM "'+t+'"').fetchone()[0]
            except sqlite3.OperationalError:
                counts[t]=None
            if time.monotonic()>=deadline:
                break
        stage='sample'
        sized=[]
        for t,n in counts.items():
            if not n:
                continue
            cols=[r[1] for r in c.execute('SELECT * FROM pragma_table_info(?)',(t,))]
            expr='+'.join('coalesce(length(CAST("'+col+'" AS BLOB)),0)' for col in cols) or '0'
            deadline_q=time.monotonic()+4
            c.set_progress_handler(lambda:time.monotonic()>=deadline_q or time.monotonic()>=deadline,1000)
            try:
                avg=c.execute('SELECT avg('+expr+') FROM (SELECT * FROM "'+t+'" ORDER BY rowid DESC LIMIT 500)').fetchone()[0]
            except sqlite3.OperationalError:
                try:
                    avg=c.execute('SELECT avg('+expr+') FROM (SELECT * FROM "'+t+'" LIMIT 500)').fetchone()[0]
                except sqlite3.OperationalError:
                    avg=None
            sized.append((t,n,avg,(n*avg/1048576) if avg else None,cols))
            if time.monotonic()>=deadline:
                break
        sized.sort(key=lambda x:-(x[3] or 0))
        out['tables_top']=[dict(table=t,rows=n,avg_row_bytes=round(a) if a else None,est_mb=round(m,1) if m else None) for t,n,a,m,_ in sized[:20]]
        out['tables_counted']=len(counts);out['tables_total']=len(tables)
        stage='growth'
        growth=[]
        for t,n,a,m,cols in sized[:6]:
            col=next((name for name in DATE_COLUMNS if name in cols),None)
            entry={'table':t,'date_column':col}
            if col:
                deadline_q=time.monotonic()+8
                c.set_progress_handler(lambda:time.monotonic()>=deadline_q or time.monotonic()>=deadline,1000)
                try:
                    days=c.execute('SELECT substr("'+col+'",1,10) d,count(*) FROM "'+t+'" GROUP BY d ORDER BY d DESC LIMIT 15').fetchall()
                    entry['rows_by_day']=[[d if isinstance(d,str) and DAY.fullmatch(d) else 'OTHER',k] for d,k in days]
                except sqlite3.OperationalError:
                    entry['rows_by_day']='interrupted'
            growth.append(entry)
        out['growth']=growth
        stage='done'
        if c.total_changes!=0:
            raise ValueError('READER_MUTATION')
    finally:
        c.close()
    out['mutations']=0
    print(json.dumps(out,sort_keys=True,ensure_ascii=True,separators=(',',':')))
except Exception as e:
    msg=str(e) if isinstance(e,ValueError) and re.fullmatch('READER_[A-Z_]{1,40}',str(e) or '') else type(e).__name__
    out.update(failure=msg,stage=stage)
    print(json.dumps(out,sort_keys=True,ensure_ascii=True,separators=(',',':')))
'''


def run(args, timeout=60, data=None, limit=8 * 1024 * 1024):
    result = subprocess.run(args, input=data, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise ValueError('CMD_FAILED:' + os.path.basename(args[0]))
    return result.stdout[:limit]


def mb(value):
    return round(value / 1048576, 1)


def code(value):
    return value if isinstance(value, str) and CODE.fullmatch(value) else 'OTHER'


def size_mb(text):
    m = re.match(r'\s*([0-9.]+)\s*([kKMGT]?B)', text or '')
    if not m:
        return None
    unit = {'B': 1 / 1048576, 'kB': 1 / 1024, 'KB': 1 / 1024, 'MB': 1, 'GB': 1024, 'TB': 1048576}[m.group(2)]
    return round(float(m.group(1)) * unit, 1)


def filesystems():
    out = []
    for path in ('/', '/var/lib/docker', '/var/lib/metainc', '/var/backups', '/srv'):
        try:
            fs = os.statvfs(path)
            out.append(dict(path=path, dev=os.stat(path).st_dev, size_gb=round(fs.f_blocks * fs.f_frsize / 1073741824, 1),
                            free_gb=round(fs.f_bavail * fs.f_frsize / 1073741824, 2),
                            used_percent=round(100 * (1 - fs.f_bfree / fs.f_blocks), 1) if fs.f_blocks else None))
        except OSError:
            out.append(dict(path=path, available=False))
    return out


def docker_summary():
    try:
        rows = [json.loads(line) for line in run(['docker', 'system', 'df', '--format', '{{json .}}']).decode().splitlines() if line.strip()]
        return [dict(type=(r.get('Type') or '').replace(' ', '_') if re.fullmatch('[A-Za-z ]{1,20}', r.get('Type') or '') else 'OTHER',
                     total=r.get('TotalCount'), active=r.get('Active'), size_mb=size_mb(r.get('Size')), reclaimable_mb=size_mb(r.get('Reclaimable')))
                for r in rows]
    except Exception:
        return dict(available=False)


def images():
    try:
        rows = [json.loads(line) for line in run(['docker', 'images', '--no-trunc', '--format', '{{json .}}']).decode().splitlines() if line.strip()]
        raw = run(['docker', 'images', '--no-trunc', '--format', '{{.ID}} {{.Size}}'])
    except Exception:
        return dict(available=False)
    used = set()
    try:
        used = {line.strip() for line in run(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.Image}}']).decode().splitlines()}
        ids = run(['docker', 'ps', '-a', '-q', '--no-trunc']).decode().split()
        if ids:
            used |= {line.strip() for line in run(['docker', 'inspect', '--format', '{{.Image}}'] + ids).decode().splitlines()}
    except Exception:
        pass
    repos, naver, dangling = {}, [], 0
    for r in rows:
        repo, tag = r.get('Repository', ''), r.get('Tag', '')
        if repo == '<none>':
            dangling += 1
        key = code(repo) if repo != '<none>' else '<none>'
        item = repos.setdefault(key, {'count': 0, 'size_mb_sum': 0.0})
        item['count'] += 1
        item['size_mb_sum'] = round(item['size_mb_sum'] + (size_mb(r.get('Size')) or 0), 1)
        if repo in ('metainc/naver-engine', 'metainc/naver-relay'):
            naver.append(dict(repo=repo.split('/')[-1], tag=tag if re.fullmatch('[0-9a-f]{40}|[A-Za-z0-9_.-]{1,40}', tag or '') else 'OTHER',
                              created=(r.get('CreatedAt') or '')[:16], size_mb=size_mb(r.get('Size')),
                              in_use=r.get('ID') in used or (repo + ':' + tag) in used))
    return dict(repositories=repos, dangling=dangling, naver_images=sorted(naver, key=lambda x: (x['repo'], x['created'])))


def du(path, depth=1):
    try:
        raw = run(['du', '-x', '-b', '-d', str(depth), path], timeout=90)
    except Exception:
        return dict(path=path, available=False)
    rows = []
    for line in raw.decode('utf-8', 'replace').splitlines():
        size, _, name = line.partition('\t')
        if size.isdigit():
            safe = name if re.fullmatch(r'/[A-Za-z0-9_./@+-]{0,200}', name) else 'OTHER'
            rows.append((int(size), safe))
    rows.sort(reverse=True)
    return dict(path=path, top=[dict(path=p, mb=mb(s)) for s, p in rows[:15]])


def backups():
    root = '/var/backups/metainc/naver-engine'
    try:
        files = []
        for base, _, names in os.walk(root):
            for name in names:
                st = os.lstat(os.path.join(base, name))
                files.append((st.st_mtime, st.st_size))
        files.sort()
        from datetime import datetime, timezone, timedelta
        kst = timezone(timedelta(hours=9))
        stamp = lambda t: datetime.fromtimestamp(t, kst).strftime('%Y-%m-%d %H:%M')
        return dict(count=len(files), total_mb=mb(sum(s for _, s in files)),
                    oldest=stamp(files[0][0]) if files else None, newest=stamp(files[-1][0]) if files else None,
                    largest_mb=mb(max((s for _, s in files), default=0)))
    except Exception:
        return dict(available=False)


def journal():
    try:
        text = run(['journalctl', '--disk-usage'], timeout=30).decode()
        m = re.search(r'take up ([0-9.]+[KMGT]?B?)', text)
        return m.group(1) if m else None
    except Exception:
        return None


def engine_db():
    try:
        cid = run(['docker', 'ps', '--no-trunc', '--filter', 'label=com.docker.compose.project=naver-engine',
                   '--filter', 'label=com.docker.compose.service=naver-engine', '--format', '{{.ID}}']).decode().split()
        if len(cid) != 1:
            return dict(available=False, found=len(cid))
        raw = run(['docker', 'exec', '-i', '--user', '10001:10001', cid[0], 'python', '-I', '-B', '-'],
                  data=READER.encode(), timeout=120, limit=256 * 1024)
        return json.loads(raw.decode().strip().splitlines()[-1])
    except Exception as error:
        return dict(available=False, error=type(error).__name__)


def main():
    result = dict(mode=MODE, ok=False, mutations=0)
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        result['filesystems'] = filesystems()
        result['docker'] = docker_summary()
        result['images'] = images()
        result['journal'] = journal()
        result['du'] = [du('/srv/metainc/ad-deploy-staging', 2), du('/root', 2), du('/var/backups/metainc/naver-engine', 1)]
        result['backups'] = backups()
        result['engine_db'] = engine_db()
        result['ok'] = 'failure' not in result['engine_db'] and result['engine_db'].get('available') is not False
    except Exception as error:
        result['error'] = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}(:[a-z]{1,20})?', str(error)) else type(error).__name__
    print('NAVER_ENGINE_STORAGE_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
